import os
import time
from types import SimpleNamespace
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.planner import ScanPlan
from tv_scan_studio.storage import Store
from tv_scan_studio.supervisor import WorkerAssignment


def wait_until(app, predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert predicate()


def make_studio(tmp_path):
    store = Store(tmp_path / "admission.db")
    project = store.create_project("EMA", 'strategy("EMA")\na = input.int(8)\nb = input.int(21)')
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    return studio, store, project


def test_admission_duplicate_guard_and_success_callback(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio, store, project = make_studio(tmp_path)
    calls = []
    plan = ScanPlan("study", ("A",), ("15",), {"in_0": list(range(600)), "in_1": [21]})
    try:
        assert studio._start_plan_admission(project, plan, lambda run_id: calls.append(len(store.run_tasks(run_id))))
        job = studio._admission_job
        assert not studio._start_plan_admission(project, plan)
        assert studio._admission_job is job
        assert not studio.enqueue_plan_button.isEnabled()
        assert "geri alınır" in studio.help_registry.specs["scan.cancel_queue"].text()
        wait_until(app, lambda: studio._admission_job is None)
        assert calls == [600]
        assert "600 yeni görev" in studio.plan_status.text()
        assert not studio._preparing
    finally:
        studio.window.close()
        app.processEvents()


def test_close_cancels_admission_without_launching_workers(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio, store, project = make_studio(tmp_path)
    old_settings = store.settings(project)
    calls = []
    plan = ScanPlan("study", ("A",), ("15",),
                    {"in_0": list(range(10000)), "in_1": list(range(10000))})
    studio.window.show()
    studio._start_plan_admission(project, plan, lambda _run_id: calls.append("launch"))
    studio.window.close()
    assert studio._count_closing
    wait_until(app, lambda: studio._admission_job is None and not studio.window.isVisible())
    assert not calls
    assert store.tasks(project) == []
    assert store.settings(project) == old_settings


def test_explicit_ui_runs_resume_without_duplicates_and_new_preserves_old(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio, store, project = make_studio(tmp_path)
    try:
        studio.plan_project.setCurrentIndex(studio.plan_project.findData(project))
        studio.symbols.setText("BIST:XU030D1!")
        studio.timeframes.setText("15")
        studio.study_id.setText("study")
        studio.plan_inputs.cellWidget(0, 3).setCurrentText("Tara")
        studio.plan_inputs.item(0, 4).setData(256, [7, 8, 9])
        plan = studio._current_plan()
        admitted = []
        request = studio.run_choice.request(project, plan)
        assert request == {"new_run": True}
        studio._start_plan_admission(project, plan, admitted.append, **request)
        assert not studio.run_choice.isEnabled()
        assert not studio.plan_project.isEnabled()
        wait_until(app, lambda: studio._admission_job is None)
        first = admitted[-1]
        old_tasks = store.run_tasks(first)
        assert len(old_tasks) == 3
        assert studio.run_choice.request(project, plan) == {"run_id": first}
        studio._start_plan_admission(project, plan, admitted.append, run_id=first)
        wait_until(app, lambda: studio._admission_job is None)
        assert admitted == [first, first]
        assert store.run_tasks(first) == old_tasks
        studio.symbols.setText("A")
        studio.preview_plan()
        assert not studio.enqueue_plan_button.isEnabled()
        assert "Kayıtlı planı yükleyin" in studio.field_errors.text()
        studio.run_choice.restore.click()
        assert studio.symbols.text() == "BIST:XU030D1!"
        studio.study_id.setText("rebound-study")
        assert studio.run_choice.request(project, studio._current_plan()) == {"run_id": first}
        studio.run_choice.choice.setCurrentIndex(0)
        studio._start_plan_admission(project, plan, admitted.append, new_run=True)
        wait_until(app, lambda: studio._admission_job is None)
        assert admitted[-1] != first
        assert store.run_tasks(first) == old_tasks
        assert len(store.tasks(project)) == 6
        studio._active_run_id = first
        studio._active_run_project = project
        studio.result_project.setCurrentIndex(studio.result_project.findData(project))
        studio._refresh_result_progress()
        assert "0/3 test" in studio.run_progress.text()
    finally:
        studio.window.close()
        app.processEvents()


def test_worker_start_uses_committed_scope_not_editable_worker_table(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio, store, project = make_studio(tmp_path)
    import tv_scan_studio.app as module
    captured = []
    class Supervisor:
        running = True
        states = {}
        def __init__(self, *_args, **_kwargs):
            pass
        def start(self, assignments, **options):
            captured.append((assignments, options))
        def stop(self):
            self.running = False
    try:
        plan = ScanPlan("study", ("A",), ("15",), {"in_0": [8], "in_1": [21]})
        from tv_scan_studio.planner import enqueue_plan
        _, run_id = enqueue_plan(store, project, plan, new_run=True, return_run_id=True)
        studio.driver = SimpleNamespace()
        monkeypatch.setattr(module, "cdp_healthy", lambda *_args: True)
        monkeypatch.setattr(module, "WorkerSupervisor", Supervisor)
        monkeypatch.setattr(studio, "_validate_live_worker_assignments", lambda assignments: None)
        assignment = WorkerAssignment(1, "isolated", (project,), "study", (run_id,))
        studio.start_workers(confirmed=True, prepared_assignments=[assignment])
        assert captured == [([assignment], {"stop_when_idle": True})]
        assert studio._active_run_id == run_id
        assert studio._active_run_project == project
    finally:
        studio.window.close()
        app.processEvents()


def test_restore_frozen_variants_without_research_archive(tmp_path):
    from dataclasses import replace
    from tv_scan_studio.planner import enqueue_plan
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio, store, project = make_studio(tmp_path)
    try:
        studio.symbols.setText("BIST:XU030D1!")
        studio.timeframes.setText("15")
        studio.study_id.setText("study")
        plan = studio._current_plan()
        plan = replace(plan, input_values={"in_0": [8]}, variants=[{"in_1": 21}, {"in_1": 22}])
        _, run_id = enqueue_plan(store, project, plan, new_run=True, return_run_id=True)
        studio.run_choice.refresh(project, selected=run_id)
        studio._research_catalog = {"available": False}
        studio.run_choice.restore.click()
        studio.study_id.setText("new-runtime-study")
        restored = studio._current_plan()
        assert restored.variants == plan.variants
        assert studio.run_choice.request(project, restored) == {"run_id": run_id}
        restored.variants[0]["in_1"] = 23
        assert studio._current_plan().variants == plan.variants
        studio.symbols.setText("A")
        import pytest
        with pytest.raises(ValueError, match="Kayıtlı ayar paketleri"):
            studio._current_plan()
    finally:
        studio.window.close()
        app.processEvents()
