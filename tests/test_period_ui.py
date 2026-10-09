import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from copy import deepcopy
from PySide6 import QtCore, QtWidgets as Q
from tv_scan_studio.app import StudioWindow, GncZihinDriver
from tv_scan_studio.period_dialog import PeriodDialog
from tv_scan_studio.period_research import validation_plan
from tv_scan_studio.planner import enqueue_plan
from test_period_research import setup, selected, finish, HOLDOUT


def window(tmp_path):
    app = Q.QApplication.instance() or Q.QApplication([])
    store, project, run_id, plan, ids = setup(tmp_path)
    studio = StudioWindow(store); studio.worker_timer.stop()
    return app, studio, store, project, ids


def close(app, studio):
    if studio.help_registry.active_tour:
        studio.help_registry.active_tour.finish()
    studio.window.close(); app.processEvents()


def test_period_dialog_preview_tour_cancel_are_readonly(tmp_path):
    app, studio, store, project, ids = window(tmp_path)
    context = selected(store, project, ids[:2])
    before = deepcopy((store.tasks(project), store.scan_runs(project), store.settings(project)))
    dialog = PeriodDialog(lambda window: validation_plan(context, window), "Seçilen adaylar", training=False,
        parent=studio.window, help_registry=studio.help_registry)
    try:
        assert not dialog.apply.isEnabled()
        dialog.start.setText("2026-03-31"); dialog.stop.setText("2026-04-30")
        assert not dialog.apply.isEnabled() and "çakışmadan" in dialog.status.text()
        dialog.start.setText("2026-04-01")
        assert dialog.apply.isEnabled()
        assert len(dialog.scope.specs) == 8
        app.processEvents()
        dialog.reject()
        assert dialog.approved_plan is None
        assert (store.tasks(project), store.scan_runs(project), store.settings(project)) == before
    finally:
        dialog.scope.finish_scope(); dialog.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        close(app, studio)


def approve(dialog):
    dialog.start.setText("2026-04-01"); dialog.stop.setText("2026-04-30")
    dialog.confirm()
    return Q.QDialog.Accepted


def test_period_action_requires_approval_and_preserves_date_driver_guard(tmp_path, monkeypatch):
    app, studio, store, project, ids = window(tmp_path)
    calls, messages = [], []
    try:
        studio.selected_result_rows = lambda: store.results(project)[:1]
        monkeypatch.setattr(PeriodDialog, "exec", lambda self: Q.QDialog.Rejected)
        monkeypatch.setattr(studio, "_start_plan_admission", lambda *args, **kwargs: calls.append((args, kwargs)))
        monkeypatch.setattr(Q.QMessageBox, "information", lambda *args: messages.append(args[-1]))
        studio.period_selected_results(training=False)
        assert not calls
        monkeypatch.setattr(PeriodDialog, "exec", approve)
        monkeypatch.setattr(GncZihinDriver, "date_range_ready", False)
        studio.period_selected_results(training=False)
        assert not calls and "sürücü hazır değil" in messages[-1]
        monkeypatch.setattr(GncZihinDriver, "date_range_ready", True)
        monkeypatch.setattr(GncZihinDriver, "deep_capture_ready", True)
        studio.period_selected_results(training=False)
        assert len(calls) == 1
        plan = calls[0][0][1]
        assert plan.date_range == HOLDOUT and plan.research["stage"] == "validation"
        assert calls[0][1] == {"new_run": True, "settings": {}}
        assert "results.period" in studio.help_registry.specs
    finally:
        close(app, studio)


def test_next_training_action_reuses_training_axes_not_holdout_winner(tmp_path, monkeypatch):
    app, studio, store, project, ids = window(tmp_path)
    calls = []
    try:
        plan = validation_plan(selected(store, project, ids[:1]), HOLDOUT)
        _, run_id = enqueue_plan(store, project, plan, new_run=True, return_run_id=True)
        finish(store, project, run_id)
        # Pick a validation result only to identify the completed stage, not its parameters.
        studio.selected_result_rows = lambda: [row for row in store.results(project) if row["payload"]["date_range"] == HOLDOUT]
        def next_window(dialog):
            assert "otomatik seçilmez" in dialog.summary.toPlainText()
            dialog.start.setText("2026-02-01"); dialog.stop.setText("2026-04-30")
            dialog.confirm(); return Q.QDialog.Accepted
        monkeypatch.setattr(PeriodDialog, "exec", next_window)
        monkeypatch.setattr(GncZihinDriver, "date_range_ready", True)
        monkeypatch.setattr(GncZihinDriver, "deep_capture_ready", True)
        monkeypatch.setattr(studio, "_start_plan_admission", lambda *args, **kwargs: calls.append((args, kwargs)))
        studio.period_selected_results(training=True)
        assert len(calls) == 1
        training = calls[0][0][1]
        assert training.input_values == {"in_0": [7, 9], "in_1": [21, 25]}
        assert training.research["previous_validation_run_id"] == run_id
        assert "results.next_training" in studio.help_registry.specs
    finally:
        close(app, studio)
