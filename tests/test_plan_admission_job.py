import os
import threading
import time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6 import QtCore, QtWidgets
from tv_scan_studio.plan_jobs import PlanAdmissionJob
from tv_scan_studio.planner import ScanPlan, PlanCancelled, enqueue_plan
from tv_scan_studio.storage import Store


def wait_until(app, predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert predicate()


def test_chunked_progress_cancel_after_final_batch_rolls_back(tmp_path):
    store = Store(tmp_path / "rollback.db")
    project = store.create_project("EMA", 'strategy("EMA")\na = input.int(8)')
    store.save_settings(project, {"old": "keep"})
    cancel = threading.Event()
    progress = []
    def report(processed, inserted):
        progress.append((processed, inserted))
        if processed == 600:
            cancel.set()
    plan = ScanPlan("study", ("A",), ("15",), {"in_0": list(range(600))})
    with pytest.raises(PlanCancelled):
        enqueue_plan(store, project, plan, progress=report, cancel_requested=cancel.is_set)
    assert progress == [(256, 256), (512, 512), (600, 600)]
    assert store.tasks(project) == []
    assert store.settings(project) == {"old": "keep"}


def test_background_admission_snapshot_and_retry_no_duplicates(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "admit.db")
    project = store.create_project("EMA", 'strategy("EMA")\na = input.int(8)')
    plan = ScanPlan("study", ("A",), ("15",), {"in_0": list(range(600))})
    settings = {"input_ui": {"in_0": {"values": [7, 8, 9]}}}
    job = PlanAdmissionJob(store, project, plan, settings=settings)
    plan.input_values["in_0"].clear()
    settings["input_ui"].clear()
    results, progress = [], []
    job.result.connect(results.append)
    job.progress.connect(progress.append)
    job.start()
    wait_until(app, lambda: bool(results) and not job.isRunning())
    assert results[-1] == {"project_id": project, "status": "ready", "inserted": 600,
                           "run_id": store.scan_runs(project)[0]["id"]}
    assert len(store.tasks(project)) == 600
    assert store.settings(project)["input_ui"]["in_0"]["values"] == [7, 8, 9]
    assert [p["processed"] for p in progress] == [256, 512, 600]
    # Progress is provisional, not proof of a committed queue.
    assert enqueue_plan(store, project, job.plan) == 0
    assert len(store.tasks(project)) == 600


def test_background_admission_cancel_keeps_ui_responsive(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "cancel.db")
    project = store.create_project("EMA", 'strategy("EMA")\na = input.int(8)\nb = input.int(21)')
    store.save_settings(project, {"old": "keep"})
    plan = ScanPlan("study", ("A",), ("15",),
                    {"in_0": list(range(10000)), "in_1": list(range(10000))})
    job = PlanAdmissionJob(store, project, plan)
    results, ticks = [], []
    job.result.connect(results.append)
    timer = QtCore.QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(1)
    try:
        job.start()
        wait_until(app, lambda: len(ticks) >= 3)
        job.cancel()
        wait_until(app, lambda: bool(results) and not job.isRunning())
        assert results[-1]["status"] == "cancelled"
        assert store.tasks(project) == []
        assert store.settings(project) == {"old": "keep"}
    finally:
        timer.stop()
        job.cancel()
        job.wait(5000)
