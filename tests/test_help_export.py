import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


def test_export_help_is_safe_and_pdf_restriction_is_explained(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "export.db")
    store.create_project("Export", 'strategy("Export")')
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    writes = []
    dialogs = []
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *_args: writes.append("file") or ("", ""))
    def inspect(dialog):
        dialogs.append(dialog)
        dialog.show()
        app.processEvents()
        registry = dialog.help_registry
        tour = registry.active_tour
        assert tour.window is dialog
        while not tour.ended:
            tour.next.click()
        assert writes == []
        assert not registry.missing_controls(dialog)
        registry.specs["export.format"].target.setCurrentText("PDF")
        assert not registry.specs["export.kind"].target.isEnabled()
        assert "CSV veya Excel" in registry.specs["export.kind"].text()
        dialog.reject()
        return QtWidgets.QDialog.Rejected
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        studio.export_current_results()
        assert writes == []
        from PySide6 import QtCore
        import shiboken6
        assert dialogs[0].help_registry.active_tour is None
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        assert not shiboken6.isValid(dialogs[0])
    finally:
        studio.window.close()
        app.processEvents()


def test_selected_export_scope_passes_only_selected_ids(tmp_path, monkeypatch):
    import tv_scan_studio.app as module
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "selected.db")
    store.create_project("Selected", 'strategy("Selected")')
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    selected = [{"task_id": 71, "classification": "dayanıklı", "verified": True}]
    monkeypatch.setattr(studio, "selected_result_rows", lambda: selected)
    captures = []
    def export(*args, **kwargs):
        captures.append(kwargs)
        return 1
    monkeypatch.setattr(module, "export_project_task_scope", export)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *_args: (str(tmp_path / "selected.xlsx"), "Excel (*.xlsx)"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *_args: None)
    def inspect(dialog):
        registry = dialog.help_registry
        registry.specs["export.scope"].target.setCurrentIndex(2)
        registry.specs["export.format"].target.setCurrentText("Excel (.xlsx)")
        assert "1 kayıt" in registry.specs["export.count"].target.text()
        return QtWidgets.QDialog.Accepted
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        studio.export_current_results()
        assert len(captures) == 1
        assert captures[0]["visible_ids"] == {71}
        assert captures[0]["excel"] is True
    finally:
        studio.window.close()
        app.processEvents()
