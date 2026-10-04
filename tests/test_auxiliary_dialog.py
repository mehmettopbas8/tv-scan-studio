import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


def test_settings_dialog_shows_content_on_every_open(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "studio.db"))
    studio.window.show()
    application.processEvents()
    page = studio.settings_page
    opened = []

    def inspect(dialog):
        dialog.show()
        application.processEvents()
        assert dialog.layout().itemAt(0).widget() is page
        assert page.isVisible()
        assert studio.settings_status.isVisible()
        assert page.findChildren(QtWidgets.QLineEdit)
        opened.append(dialog.windowTitle())
        dialog.hide()
        return 0

    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        for _ in range(2):
            studio._show_auxiliary(6, "Genel ayarlar")
            assert studio.pages.widget(6) is page
            assert page.isHidden()
        assert opened == ["Genel ayarlar", "Genel ayarlar"]
    finally:
        studio.window.close()
