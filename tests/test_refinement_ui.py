import copy
import os
import time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets as Q
from tv_scan_studio.app import StudioWindow, GncZihinDriver
from tv_scan_studio.refinement_dialog import RefinementDialog
from tv_scan_studio.coarse_fine import refinement_plan
from tv_scan_studio.planner import enqueue_plan
from tv_scan_studio.scan_runs import comparable_plan
from test_coarse_fine import coarse, context


def setup(tmp_path):
    app = Q.QApplication.instance() or Q.QApplication([])
    store, project, _, _, ids = coarse(tmp_path)
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    return app, store, project, ids, studio


def close(app, studio):
    if studio.help_registry.active_tour is not None:
        studio.help_registry.active_tour.finish()
    studio.window.close()
    app.processEvents()


def test_refinement_preview_and_cancel_never_write_and_help_is_scoped(tmp_path):
    app, store, project, ids, studio = setup(tmp_path)
    before = copy.deepcopy((store.tasks(project), store.scan_runs(project), store.settings(project)))
    dialog = RefinementDialog(context(store, project, ids[:2]), studio.window, studio.help_registry)
    try:
        assert not dialog.apply.isEnabled()
        assert "Fast EMA" in dialog.candidates.toPlainText()
        assert "15 dakika" in dialog.candidates.toPlainText()
        dialog.values.setText("6, 7, 8")
        assert dialog.apply.isEnabled() and "6" in dialog.status.text()
        assert "refinement.apply" in dialog.scope.specs
        app.processEvents()
        dialog.values.setText("[0]")
        assert not dialog.apply.isEnabled()
        dialog.reject()
        assert dialog.approved_plan is None
        assert (store.tasks(project), store.scan_runs(project), store.settings(project)) == before
    finally:
        dialog.scope.finish_scope(); dialog.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        close(app, studio)


def test_fine_restore_ignores_stale_ui_and_keeps_frozen_packages(tmp_path):
    app, store, project, ids, studio = setup(tmp_path)
    try:
        fine = refinement_plan(context(store, project, ids[:2]), "in_0", [6, 7, 8])
        snapshot = fine.to_dict()
        snapshot["input_ui"] = {"in_0": {"decision": "Sabit bırak", "values": [19]}}
        studio.load_plan_inputs(saved_snapshot=snapshot)
        restored = studio._current_plan()
        assert restored.input_values == fine.input_values
        assert restored.variants == fine.variants
        assert restored.research == fine.research
        assert studio.refinement_detach.isEnabled()
        original = copy.deepcopy(store.scan_runs(project))
        studio.detach_refinement()
        assert studio._current_plan().research == {}
        assert store.scan_runs(project) == original
        assert "results.refine" in studio.help_registry.specs
    finally:
        close(app, studio)


def test_approval_reaches_new_run_admission_only_after_confirm(tmp_path, monkeypatch):
    app, store, project, ids, studio = setup(tmp_path)
    calls = []
    try:
        studio.selected_result_rows = lambda: store.results(project)[:1]
        monkeypatch.setattr(RefinementDialog, "exec", lambda self: Q.QDialog.Rejected)
        monkeypatch.setattr(studio, "_start_plan_admission", lambda *args, **kwargs: calls.append((args, kwargs)))
        studio.refine_selected_results()
        assert not calls
        def confirm(dialog):
            dialog.values.setText("[7, 8, 9]")
            dialog.confirm()
            return Q.QDialog.Accepted
        monkeypatch.setattr(RefinementDialog, "exec", confirm)
        monkeypatch.setattr(GncZihinDriver, "date_range_ready", True)
        monkeypatch.setattr(GncZihinDriver, "deep_capture_ready", True)
        studio.refine_selected_results()
        assert len(calls) == 1
        assert calls[0][0][1].research["candidate_result_ids"]
        assert calls[0][1] == {"new_run": True, "settings": {}}
        studio._preparing = True
        studio.refine_selected_results()
        assert len(calls) == 1
    finally:
        studio._preparing = False
        close(app, studio)


def test_coarse_method_has_no_sampling_budget_and_preserves_plan(tmp_path):
    app, store, project, ids, studio = setup(tmp_path)
    try:
        studio.scan_method.setCurrentIndex(studio.scan_method.findData("coarse"))
        assert studio._current_plan().method == "coarse"
        assert not studio.sample_budget.isEnabled()
        assert "kaba" in studio.help_registry.specs["sampling.method"].text().lower()
        assert not any(row["status"] == "pending" for row in store.tasks(project))
    finally:
        close(app, studio)


def test_date_capability_guard_does_not_queue_approved_plan(tmp_path, monkeypatch):
    app, store, project, ids, studio = setup(tmp_path)
    try:
        before = copy.deepcopy((store.tasks(project), store.scan_runs(project)))
        studio.selected_result_rows = lambda: store.results(project)[:1]
        def confirm(dialog):
            dialog.values.setText("[7, 8, 9]")
            dialog.confirm()
            return Q.QDialog.Accepted
        monkeypatch.setattr(RefinementDialog, "exec", confirm)
        monkeypatch.setattr(GncZihinDriver, "date_range_ready", False)
        messages = []
        monkeypatch.setattr(Q.QMessageBox, "information", lambda *args: messages.append(args[-1]))
        studio.refine_selected_results()
        assert "sürücü hazır değil" in messages[-1]
        assert (store.tasks(project), store.scan_runs(project)) == before
        assert studio._admission_job is None
    finally:
        close(app, studio)


def test_confirmed_fine_admission_is_async_and_returns_to_scan_without_start(tmp_path, monkeypatch):
    app, store, project, ids, studio = setup(tmp_path)
    try:
        original = copy.deepcopy(store.results(project))
        studio.selected_result_rows = lambda: store.results(project)[:1]
        def confirm(dialog):
            dialog.values.setText("[7, 8, 9]")
            dialog.confirm()
            return Q.QDialog.Accepted
        monkeypatch.setattr(RefinementDialog, "exec", confirm)
        monkeypatch.setattr(GncZihinDriver, "date_range_ready", True)
        monkeypatch.setattr(GncZihinDriver, "deep_capture_ready", True)
        studio.refine_selected_results()
        assert studio._admission_job is not None
        assert not studio.result_refine.isEnabled()
        deadline = time.monotonic() + 8
        while studio._admission_job is not None and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.001)
        assert studio._admission_job is None
        assert studio.pages.currentIndex() == 2
        assert store.results(project) == original
        assert len(store.scan_runs(project)) == 2
        assert len(store.tasks(project)) == 7
        assert studio._current_plan().research["stage"] == "fine"
        assert studio.supervisor is None or not studio.supervisor.running
    finally:
        close(app, studio)


def test_ui_generated_coarse_plan_fine_restore_is_exactly_resumable(tmp_path):
    app, store, project, ids, studio = setup(tmp_path)
    try:
        studio.study_id.setText("study")
        coarse_plan = studio._current_plan()
        _, run_id = enqueue_plan(store, project, coarse_plan, new_run=True, return_run_id=True)
        candidate_ids = []
        for _ in range(coarse_plan.task_count):
            task = store.claim_next(1, [project], run_ids=[run_id])
            store.complete(task.id, 1, {"profit_factor": 1.5}, "hassas", verified=True,
                evidence={"symbol": task.payload["symbol"], "timeframe": "15", "inputs": task.payload["inputs"],
                    "period": {"from": 1, "to": 2}, "cost_verification_scope": "strategy_properties_ui_spread_unverified"})
            candidate_ids.append(store.result_history(task.id)[-1]["id"])
        fine = refinement_plan(context(store, project, candidate_ids[:2]), "in_0", [6, 7, 8])
        _, fine_run = enqueue_plan(store, project, fine, new_run=True, return_run_id=True)
        studio.load_plan_inputs(saved_snapshot=fine.to_dict())
        studio.run_choice.refresh(project, selected=fine_run)
        assert comparable_plan(studio._current_plan().to_dict()) == comparable_plan(fine.to_dict())
        assert studio.run_choice.request(project, studio._current_plan()) == {"run_id": fine_run}
    finally:
        close(app, studio)
