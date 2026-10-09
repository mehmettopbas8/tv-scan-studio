import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6 import QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


@pytest.mark.parametrize("page_index,feature", [(0, "management"), (3, "preparation"), (5, "research"), (6, "settings")])
def test_auxiliary_help_anchors_to_dialog_and_restores_page(tmp_path, monkeypatch, page_index, feature):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "aux.db")
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    page = studio.pages.widget(page_index)
    def inspect(dialog):
        dialog.show()
        app.processEvents()
        scope = dialog.help_registry
        tour = scope.active_tour
        assert tour is not None
        assert tour.window is dialog
        assert scope is not studio.help_registry
        assert all(step[0].isVisible() for step in tour.steps)
        tour.skip.click()
        assert store.app_settings()[f"help_tour_{feature}_completed"]
        scope.start_tour(feature)
        tour = scope.active_tour
        dialog.accept()
        assert not tour.timer.isActive()
        return 0
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        studio._show_auxiliary(page_index, feature)
        assert studio.pages.widget(page_index) is page
        assert page.isHidden()
        assert not store.projects()
    finally:
        studio.window.close()
        app.processEvents()
