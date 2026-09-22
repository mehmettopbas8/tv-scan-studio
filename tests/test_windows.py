from pathlib import Path
from subprocess import CompletedProcess

import io
import json

import pytest

from tv_scan_studio.windows import find_tradingview_executables, open_chart_tabs


def test_finds_normal_and_store_installations(tmp_path):
    local = tmp_path / "local"; normal = local / "Programs" / "TradingView" / "TradingView.exe"
    normal.parent.mkdir(parents=True); normal.touch()
    store = tmp_path / "store"; store.mkdir(); (store / "TradingView.exe").touch()
    def fake_run(*args, **kwargs):
        return CompletedProcess(args[0], 0, stdout=str(store) + "\n", stderr="")
    found = find_tradingview_executables(env={"LOCALAPPDATA": str(local)}, run=fake_run)
    assert normal in found
    assert store / "TradingView.exe" in found


def test_new_workers_open_as_tabs_on_the_same_cdp_port():
    calls = []
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *_args): pass
    def fake_open(request, timeout):
        calls.append(request)
        if isinstance(request, str):
            return Response(json.dumps([{"type": "page", "url": "https://www.tradingview.com/chart/abc/"}]).encode())
        return Response(json.dumps({"id": f"new-{len(calls)}"}).encode())
    created = open_chart_tabs(2, port=9222, urlopen=fake_open)
    assert created == ["new-2", "new-3"]
    assert all(call.full_url.startswith("http://127.0.0.1:9222/json/new?") for call in calls[1:])
    assert all(call.method == "PUT" for call in calls[1:])
    with pytest.raises(ValueError):
        open_chart_tabs(17, urlopen=fake_open)
