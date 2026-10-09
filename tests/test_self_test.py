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
    # This CLI mode owns a fresh Qt process in production. Reusing the full
    # suite's QApplication applies its stylesheet to unrelated retained widgets
    # and can hang in native event processing; test the actual process boundary.
    from tv_scan_studio.processes import run_hidden
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    script = '''
import sys
from tv_scan_studio import app
sys.argv = ["tv-scan-studio", "--ui-smoke-test"]
def forbidden():
    raise AssertionError("Live database or instance mutex must not be touched")
app.data_path = forbidden
app.desktop_instance = forbidden
application = app.QtWidgets.QApplication([])
original_process_events = application.processEvents
event_calls = []
def bounded_events(*args):
    event_calls.append(args)
    return original_process_events(*args)
application.processEvents = bounded_events
assert app.main() == 0
assert len(event_calls) >= 9
assert all(len(args) == 2 and args[1] == 50 for args in event_calls)
'''
    result = run_hidden([sys.executable, "-c", script], capture_output=True,
                        text=True, encoding="utf-8", timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "TVScanStudio").exists()
