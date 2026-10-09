import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.help_system import HelpRegistry, HelpSpec, TourSpec
from tv_scan_studio.storage import Store


def test_task_dialog_help_has_own_anchor_shared_tour_and_safe_cleanup(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "tasks.db")
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    calls = []
    monkeypatch.setattr(studio, "create_portable_backup", lambda: calls.append("backup"))
    monkeypatch.setattr(studio, "restore_portable_backup", lambda: calls.append("restore"))
    def inspect(dialog):
        dialog.show()
        app.processEvents()
        registry = dialog.help_registry
        assert len([key for key in registry.specs if key.startswith("tasks.")]) == 12
        assert registry.active_tour is not None
        assert registry.active_tour.window is dialog
        assert studio.help_registry.active_tour is registry.active_tour
        assert not registry.missing_controls(dialog)
        tour = registry.active_tour
        tour.skip.click()
        assert not tour.timer.isActive()
        assert store.app_settings()["help_tour_tasks_backup_completed"]
        registry.start_tour("tasks_backup")
        reopened = registry.active_tour
        dialog.accept()
        assert registry.active_tour is None
        assert not reopened.timer.isActive()
        return 0
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        studio.show_tasks_backup()
        assert calls == []
        assert not store.projects()
    finally:
        studio.window.close()
        app.processEvents()


def test_replaced_page_retires_help_and_active_timer():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    page = QtWidgets.QWidget(window)
    target = QtWidgets.QPushButton("Eski", page)
    registry = HelpRegistry(window)
    registry.register(HelpSpec("old", 1, "Eski", "Eski açıklama.", "Eski ayrıntı.", target))
    registry.register_tour(TourSpec("old", 1, ((target, "Eski", "Eski rehber.", None),)))
    window.show()
    try:
        tour = registry.start_tour("old")
        registry.remove_tree(page)
        assert not registry.specs
        assert not registry.tours
        assert registry.resolve(target) is None
        assert registry.active_tour is None
        assert not tour.timer.isActive()
        # A rebuilt page can reuse its stable feature IDs without collision.
        new_target = QtWidgets.QPushButton("Yeni", window)
        registry.register(HelpSpec("old", 1, "Yeni", "Yeni açıklama.", "Yeni ayrıntı.", new_target))
    finally:
        window.close()
        app.processEvents()
