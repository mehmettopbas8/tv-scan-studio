import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


def test_empty_preset_help_has_direction_and_never_applies_settings(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "presets.db")
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    calls = []
    monkeypatch.setattr(studio, "apply_saved_preset", lambda *_args: calls.append("apply"))
    def inspect(dialog):
        dialog.show()
        app.processEvents()
        registry = dialog.help_registry
        assert "Sonuçlar" in registry.specs["presets.reuse"].text()
        assert not registry.specs["presets.reuse"].target.isEnabled()
        tour = registry.active_tour
        assert tour.window is dialog
        while not tour.ended:
            tour.next.click()
        assert not registry.missing_controls(dialog)
        assert not tour.timer.isActive()
        assert store.app_settings()["help_tour_presets_completed"]
        dialog.accept()
        return 0
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        studio.show_saved_presets()
        assert calls == []
        assert not store.projects()
    finally:
        studio.window.close()
        app.processEvents()
