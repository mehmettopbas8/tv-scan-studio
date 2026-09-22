from pathlib import Path
from subprocess import CompletedProcess

from tv_scan_studio.windows import find_tradingview_executables


def test_finds_normal_and_store_installations(tmp_path):
    local = tmp_path / "local"; normal = local / "Programs" / "TradingView" / "TradingView.exe"
    normal.parent.mkdir(parents=True); normal.touch()
    store = tmp_path / "store"; store.mkdir(); (store / "TradingView.exe").touch()
    def fake_run(*args, **kwargs):
        return CompletedProcess(args[0], 0, stdout=str(store) + "\n", stderr="")
    found = find_tradingview_executables(env={"LOCALAPPDATA": str(local)}, run=fake_run)
    assert normal in found
    assert store / "TradingView.exe" in found
