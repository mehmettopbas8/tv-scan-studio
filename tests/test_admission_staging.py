import threading
import os
import time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from tv_scan_studio.storage import Store
from tv_scan_studio.planner import ScanPlan, PlanCancelled, enqueue_plan


def setup_store(tmp_path):
    store = Store(tmp_path / "stage.db")
    project = store.create_project("EMA", 'strategy("EMA")\na = input.int(8)')
    store.save_settings(project, {"old": "keep"})
    plan = ScanPlan("study", ("A",), ("15",), {"in_0": list(range(600))})
    return store, project, plan


def test_staging_does_not_hold_app_write_lock(tmp_path):
    store, project, plan = setup_store(tmp_path)
    snapshots = []
    def report(processed, staged):
        # A second connection can write while generation is in progress.
        store.save_app_settings({"tour_completed": True})
        snapshots.append((store.counts(project), store.settings(project)))
    assert enqueue_plan(store, project, plan, progress=report) == 600
    assert len(snapshots) == 3
    assert all(counts == {} and settings == {"old": "keep"} for counts, settings in snapshots)
    assert store.app_settings()["tour_completed"] is True


def test_source_changed_during_staging_rejected_without_overwriting_settings(tmp_path):
    store, project, plan = setup_store(tmp_path)
    changed = False
    def report(*_counts):
        nonlocal changed
        if not changed:
            with store.connect() as connection:
                connection.execute("UPDATE projects SET pine_source=? WHERE id=?", ('strategy("Changed")', project))
            changed = True
    with pytest.raises(ValueError, match="kaynağı hazırlık sırasında değişti"):
        enqueue_plan(store, project, plan, progress=report)
    assert store.tasks(project) == []
    assert store.settings(project) == {"old": "keep"}


def test_late_unrelated_pending_task_blocks_admission_atomically(tmp_path):
    store, project, plan = setup_store(tmp_path)
    def report(processed, _staged):
        if processed == 600:
            store.enqueue(project, "other-plan", {"unrelated": True})
    with pytest.raises(ValueError, match="başka bir taramadan"):
        enqueue_plan(store, project, plan, progress=report, require_pending_subset=True)
    assert [task["task_key"] for task in store.tasks(project)] == ["other-plan"]
    assert store.settings(project) == {"old": "keep"}


def test_same_pending_plan_is_allowed_and_idempotent(tmp_path):
    store, project, plan = setup_store(tmp_path)
    assert enqueue_plan(store, project, plan, require_pending_subset=True) == 600
    assert enqueue_plan(store, project, plan, require_pending_subset=True) == 0
    assert len(store.tasks(project)) == 600


def test_cancel_during_final_sql_copy_rolls_back(tmp_path, monkeypatch):
    store, project, plan = setup_store(tmp_path)
    plan.input_values["in_0"] = list(range(5000))
    cancel = threading.Event()
    original = store.connect
    def connect():
        connection = original()
        def trace(sql):
            if sql.startswith("INSERT OR IGNORE INTO tasks") and "admission.queue" in sql:
                cancel.set()
        connection.set_trace_callback(trace)
        return connection
    monkeypatch.setattr(store, "connect", connect)
    with pytest.raises(PlanCancelled):
        enqueue_plan(store, project, plan, cancel_requested=cancel.is_set)
    assert cancel.is_set()
    assert store.tasks(project) == []
    assert store.settings(project) == {"old": "keep"}


def test_cancel_while_waiting_for_write_lock_is_prompt(tmp_path, monkeypatch):
    from PySide6 import QtWidgets
    from tv_scan_studio.plan_jobs import PlanAdmissionJob
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store, project, plan = setup_store(tmp_path)
    attempted = threading.Event()
    original = store.connect
    def connect():
        connection = original()
        connection.set_trace_callback(lambda sql: attempted.set() if sql == "BEGIN IMMEDIATE" else None)
        return connection
    with original() as lock:
        lock.execute("BEGIN IMMEDIATE")
        monkeypatch.setattr(store, "connect", connect)
        job = PlanAdmissionJob(store, project, plan)
        results = []
        job.result.connect(results.append)
        try:
            job.start()
            deadline = time.monotonic() + 5
            while not attempted.is_set() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.001)
            assert attempted.is_set()
            started = time.monotonic()
            job.cancel()
            while (job.isRunning() or not results) and time.monotonic() - started < 1:
                app.processEvents()
                time.sleep(.001)
            assert not job.isRunning()
            assert results[-1]["status"] == "cancelled"
        finally:
            job.cancel()
            lock.rollback()
            job.wait(5000)
    assert store.tasks(project) == []
    assert store.settings(project) == {"old": "keep"}


@pytest.mark.parametrize("cancelled", [False, True])
def test_owned_staging_files_removed_on_completion_or_cancel(tmp_path, monkeypatch, cancelled):
    import tv_scan_studio.storage as storage
    store, project, plan = setup_store(tmp_path)
    paths = []
    original = storage.tempfile.TemporaryDirectory
    def temporary_directory(**options):
        temporary = original(**options)
        paths.append(Path(temporary.name))
        return temporary
    monkeypatch.setattr(storage.tempfile, "TemporaryDirectory", temporary_directory)
    cancel = threading.Event()
    if cancelled:
        with pytest.raises(PlanCancelled):
            enqueue_plan(store, project, plan, cancel_requested=cancel.is_set,
                         progress=lambda *_args: cancel.set())
    else:
        assert enqueue_plan(store, project, plan) == 600
    assert paths and all(not path.exists() for path in paths)
    assert store.path.exists()
