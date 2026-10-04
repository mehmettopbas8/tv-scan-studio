import sys
from pathlib import Path

from tv_scan_studio import app


def test_application_icon_is_available_and_decodable(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = app.QtWidgets.QApplication.instance() or app.QtWidgets.QApplication([])
    icon_path = Path(app.__file__).parent / "assets" / "app-icon.ico"
    assert icon_path.is_file()
    icon = app.QtGui.QIcon(str(icon_path))
    assert not icon.isNull()
    for size in (16, 32, 48, 256):
        assert not icon.pixmap(size, size).isNull()


def test_packaged_self_test_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["tv-scan-studio", "--self-test"])
    assert app.main() == 0
    assert not (tmp_path / "TVScanStudio").exists()


def test_packaged_ui_smoke_uses_isolated_database_and_no_live_instance(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(sys, "argv", ["tv-scan-studio", "--ui-smoke-test"])
    monkeypatch.setattr(app, "data_path", lambda: (_ for _ in ()).throw(
        AssertionError("Live database must not be opened")))
    monkeypatch.setattr(app, "desktop_instance", lambda: (_ for _ in ()).throw(
        AssertionError("Live instance mutex must not be touched")))
    assert app.main() == 0
    assert not (tmp_path / "TVScanStudio").exists()
