import sys

from tv_scan_studio import app


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
