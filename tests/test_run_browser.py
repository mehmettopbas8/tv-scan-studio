import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from copy import deepcopy
from PySide6 import QtCore, QtWidgets as Q
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.help_system import HelpRegistry
from tv_scan_studio.planner import ScanPlan, enqueue_plan
from tv_scan_studio.run_browser import RunBrowser
from tv_scan_studio.storage import Store


def setup(tmp_path):
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "history.db")
    project = store.create_project("EMA", 'strategy("PRIVATE SOURCE")\na=input.int(8)')
    plan = ScanPlan("study", ("A",), ("15",), {"in_0": list(range(1, 206))})
    enqueue_plan(store, project, plan, new_run=True)
    parent = Q.QWidget()
    registry = HelpRegistry(parent, store.app_settings, store.save_app_settings)
    dialog = RunBrowser(store, parent=parent, help_registry=registry)
    return app, store, project, parent, dialog


def test_all_pages_and_tour_leave_tasks_runs_and_results_unchanged(tmp_path):
    app, store, project, parent, dialog = setup(tmp_path)
    before = deepcopy((store.tasks(project), store.scan_runs(project), store.results(project)))
    try:
        assert dialog.tasks.rowCount() == 100
        assert "205" in dialog.status.text() and not dialog.previous.isEnabled()
        ids = [row["id"] for row in dialog.rows]
        dialog.next.click(); ids += [row["id"] for row in dialog.rows]
        dialog.next.click(); ids += [row["id"] for row in dialog.rows]
        assert dialog.tasks.rowCount() == 5 and not dialog.next.isEnabled()
        assert len(set(ids)) == 205
        assert "PRIVATE SOURCE" not in dialog.context.toPlainText()
        dialog.previous.click(); assert dialog.tasks.rowCount() == 100
        dialog.show(); app.processEvents()
        tour = dialog.scope.active_tour
        assert tour is not None
        tour.skip.click()
        assert store.app_settings()["help_tour_run_browser_completed"]
        dialog.guide.click(); assert dialog.scope.active_tour is not None
        dialog.close_button.click(); app.processEvents()
        assert dialog.scope.active_tour is None
        assert (store.tasks(project), store.scan_runs(project), store.results(project)) == before
    finally:
        dialog.scope.finish_scope(); dialog.close(); parent.close(); app.processEvents()


def test_resultless_failed_attempt_visible_in_details(tmp_path, monkeypatch):
    app, store, project, parent, dialog = setup(tmp_path)
    task = store.claim_next(1, [project])
    store.fail(task.id, 1, "PRIVATE ERROR")
    dialog.load_page()
    opened = []
    def inspect(details):
        from tv_scan_studio.result_history_panel import ResultHistoryPanel
        panel = details.findChild(ResultHistoryPanel)
        assert panel is not None
        assert panel.attempts.rowCount() == 2
        assert not panel.evaluate.isEnabled()
        assert panel.records == []
        opened.append(True)
        details.accept()
        return Q.QDialog.Accepted
    monkeypatch.setattr(Q.QDialog, "exec", inspect)
    try:
        assert not dialog.details.isEnabled()
        dialog.tasks.selectRow(0)
        assert dialog.details.isEnabled()
        dialog.details.click()
        assert opened and not store.results(project)
    finally:
        dialog.scope.finish_scope(); dialog.close(); parent.close(); app.processEvents()


def test_app_support_and_run_browser_open_only_and_have_help(tmp_path, monkeypatch):
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "app.db")
    studio = StudioWindow(store); studio.worker_timer.stop()
    inspected = []
    def inspect(dialog):
        assert dialog.windowTitle() in {"Yerel destek paketi", "Koşu ve deneme geçmişi"}
        assert dialog.scope.specs
        inspected.append(dialog.windowTitle())
        dialog.reject()
        return Q.QDialog.Rejected
    monkeypatch.setattr(Q.QDialog, "exec", inspect)
    try:
        assert "settings.support" in studio.help_registry.specs
        assert "results.run_history" in studio.help_registry.specs
        studio.support_package_button.click()
        studio.run_history_button.click()
        assert len(inspected) == 2
        assert not store.projects()
        assert studio._support_dialog is None
    finally:
        studio.help_registry.finish_scope(); studio.window.close()
        app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete); app.processEvents()


def test_root_close_cancels_support_job_before_dialog_is_destroyed(tmp_path):
    from tv_scan_studio.support_dialog import SupportDialog
    import time
    app = Q.QApplication.instance() or Q.QApplication([])
    studio = StudioWindow(Store(tmp_path / "close.db")); studio.worker_timer.stop()
    dialog = SupportDialog(studio.store, parent=studio.window, help_registry=studio.help_registry)
    studio._support_dialog = dialog
    class SlowJob(QtCore.QThread):
        progress = QtCore.Signal(object)
        result = QtCore.Signal(object)
        def __init__(self): super().__init__(); self.cancelled = False
        def cancel(self): self.cancelled = True
        def run(self):
            while not self.cancelled: self.msleep(2)
            self.msleep(30); self.result.emit({"status": "cancelled"})
    job = SlowJob(); finished = []
    dialog.finished.connect(finished.append)
    try:
        dialog.show(); dialog.start_job(job)
        assert studio._before_count_close() is False
        assert studio._count_closing and dialog.closing and not finished
        deadline = time.monotonic() + 3
        while dialog.job is not None and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.002)
        assert dialog.job is None and finished == [Q.QDialog.Rejected]
        assert studio._before_count_close() is True
    finally:
        job.cancel(); job.wait(1000)
        studio._support_dialog = None
        dialog.scope.finish_scope(); studio.help_registry.finish_scope()
        dialog.deleteLater(); studio.window.close(); app.processEvents()


def test_sensitivity_details_use_frozen_names_and_explain_exclusions(tmp_path):
    from test_sensitivity_evidence import setup as sensitivity_setup
    app = Q.QApplication.instance() or Q.QApplication([])
    store, project, rows = sensitivity_setup(tmp_path, lambda evidence: evidence.pop("report_currency"))
    studio = StudioWindow(store); studio.worker_timer.stop()
    try:
        studio._result_by_id = {row["task_id"]: row for row in rows}
        studio.result_project.setCurrentIndex(studio.result_project.findData(project))
        studio.open_result_details_by_id(rows[0]["task_id"])
        registry = studio.help_registry
        table = registry.specs["sensitivity.table"].target
        excluded = registry.specs["sensitivity.excluded"].target
        assert table.rowCount() == 1 and table.columnCount() == 8
        assert table.item(0, 0).text() == "Fast EMA"
        assert table.item(0, 7).text() == "Bilinmiyor"
        assert "para birimi" in excluded.toPlainText()
        before = deepcopy(store.results(project))
        registry.specs["sensitivity.guide"].target.click()
        assert registry.active_tour is not None
        registry.active_tour.finish()
        assert store.results(project) == before
    finally:
        studio.help_registry.finish_scope(); studio.window.close(); app.processEvents()
