import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from tv_scan_studio.historical_dialog import HistoricalDialog
from tv_scan_studio.storage import Store


def test_history_help_is_complete_persistent_and_does_not_export(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "history.db")
    calls = []
    monkeypatch.setattr(HistoricalDialog, "choose_archive", lambda *_: calls.append("open"))
    monkeypatch.setattr(HistoricalDialog, "export_records", lambda *_: calls.append("export"))
    dialog = HistoricalDialog(store)
    dialog.show()
    app.processEvents()
    registry = dialog.help_registry
    tour = registry.active_tour
    assert tour.window is dialog
    assert "arşiv yükle" in registry.specs["history.export"].text()
    while not tour.ended:
        tour.next.click()
    assert not registry.missing_controls(dialog)
    assert not tour.timer.isActive()
    assert calls == []
    assert store.app_settings()["help_tour_history_completed"]
    registry.start_tour("history")
    dialog.accept()
    assert registry.active_tour is None
    reopened = HistoricalDialog(store)
    reopened.show()
    app.processEvents()
    assert reopened.help_registry.active_tour is None
    reopened.accept()
