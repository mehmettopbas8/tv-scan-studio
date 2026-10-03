from pathlib import Path
from subprocess import CompletedProcess

import io
import json
import urllib.error

import pytest

from tv_scan_studio.windows import (TabCreationError, cdp_healthy, cdp_owned_by_tradingview,
                                    chart_targets, find_tradingview_executables,
                                    launch_with_cdp, open_chart_tabs,
                                    worker_layout_candidates)


def test_worker_layouts_must_have_distinct_saved_chart_ids():
    targets = [
        {"id": "original", "url": "https://www.tradingview.com/chart/Coding/"},
        {"id": "worker-1", "url": "https://www.tradingview.com/chart/Unique1/"},
        {"id": "worker-2", "url": "https://www.tradingview.com/chart/Unique2/"},
    ]
    names = {"original": "Coding", "worker-1": "TV Scan Worker 1",
             "worker-2": "TV Scan Worker 2"}
    assert worker_layout_candidates(targets, names) == {
        "worker-1": "Unique1", "worker-2": "Unique2"}
    targets[2]["url"] = targets[1]["url"]
    with pytest.raises(ValueError, match="benzersiz"):
        worker_layout_candidates(targets, names)
    targets[2]["url"] = "https://www.tradingview.com/chart/Unique2/"
    names["worker-2"] = "Coding"
    assert worker_layout_candidates(targets, names) == {"worker-1": "Unique1"}


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
            return Response(json.dumps([{"id": "original", "type": "page", "url": "https://www.tradingview.com/chart/abc/"}]).encode())
        return Response(json.dumps({"id": f"new-{len(calls)}", "type": "page",
                                    "url": "https://www.tradingview.com/chart/abc/"}).encode())
    created = open_chart_tabs(2, port=9222, urlopen=fake_open, owner_check=lambda: True)
    assert created == ["new-2", "new-3"]
    assert all(call.full_url.startswith("http://127.0.0.1:9222/json/new?") for call in calls[1:])
    assert all(call.method == "PUT" for call in calls[1:])
    with pytest.raises(ValueError):
        open_chart_tabs(17, urlopen=fake_open, owner_check=lambda: True)


def test_store_desktop_500_uses_existing_chart_page_and_verifies_new_tab():
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *_args): pass

    source = {"id": "original", "type": "page",
              "url": "https://www.tradingview.com/chart/abc/"}
    tabs = [source]
    opened = []

    def fake_open(request, timeout):
        if isinstance(request, str):
            return Response(json.dumps(tabs).encode())
        raise urllib.error.HTTPError(request.full_url, 500, "Could not create new page", {}, None)

    def page_opener(target_id, url):
        opened.append((target_id, url))
        tabs.append({"id": f"worker-{len(opened)}", "type": "page", "url": url})

    created = open_chart_tabs(2, urlopen=fake_open, owner_check=lambda: True,
                              page_opener=page_opener)
    assert created == ["worker-1", "worker-2"]
    assert opened == [("original", source["url"])] * 2


def test_store_desktop_500_does_not_silently_retry_unknown_tab():
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *_args): pass

    def fake_open(request, timeout):
        if isinstance(request, str):
            return Response(json.dumps([{"id": "original", "type": "page",
                                         "url": "https://www.tradingview.com/chart/abc/"}]).encode())
        raise urllib.error.HTTPError(request.full_url, 500, "Could not create new page", {}, None)

    with pytest.raises(TabCreationError, match="yeniden denemeden önce") as caught:
        open_chart_tabs(1, timeout=0, urlopen=fake_open, owner_check=lambda: True,
                        page_opener=lambda *_: None)
    assert caught.value.created_targets == ()


def test_partial_store_tab_creation_reports_confirmed_target():
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *_args): pass

    tabs = [{"id": "original", "type": "page",
             "url": "https://www.tradingview.com/chart/abc/"}]
    attempts = []

    def fake_open(request, timeout):
        if isinstance(request, str):
            return Response(json.dumps(tabs).encode())
        raise urllib.error.HTTPError(request.full_url, 500, "Could not create new page", {}, None)

    def page_opener(_target_id, url):
        attempts.append(url)
        if len(attempts) == 1:
            tabs.append({"id": "worker-1", "type": "page", "url": url})

    with pytest.raises(TabCreationError, match="yeniden denemeden önce") as caught:
        open_chart_tabs(2, timeout=0, urlopen=fake_open, owner_check=lambda: True,
                        page_opener=page_opener)
    assert caught.value.created_targets == ("worker-1",)
    assert len(attempts) == 2


def test_second_port_and_existing_target_ids_are_rejected_before_worker_use():
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *_args): pass

    calls = []
    def fake_open(request, timeout):
        calls.append(request)
        if isinstance(request, str):
            return Response(json.dumps([{"id": "live-chart", "type": "page",
                                         "url": "https://www.tradingview.com/chart/abc/"}]).encode())
        return Response(json.dumps({"id": "live-chart", "type": "page",
                                    "url": "https://www.tradingview.com/chart/abc/"}).encode())

    assert not cdp_healthy(9333)
    with pytest.raises(ValueError, match="9222"):
        open_chart_tabs(1, port=9333, urlopen=fake_open, owner_check=lambda: True)
    with pytest.raises(ValueError, match="9222"):
        launch_with_cdp("does-not-matter.exe", port=9333)
    assert calls == []
    with pytest.raises(RuntimeError, match="kimliği doğrulanamadı"):
        open_chart_tabs(1, urlopen=fake_open, owner_check=lambda: True)


def test_new_target_must_be_a_tradingview_chart():
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *_args): pass

    def fake_open(request, timeout):
        if isinstance(request, str):
            return Response(json.dumps([{"id": "old", "type": "page",
                                         "url": "https://www.tradingview.com/chart/abc/"}]).encode())
        return Response(json.dumps({"id": "new", "type": "page",
                                    "url": "https://example.com/"}).encode())

    with pytest.raises(RuntimeError, match="chart değil"):
        open_chart_tabs(1, urlopen=fake_open, owner_check=lambda: True)


def test_cdp_owner_must_be_tradingview_desktop(monkeypatch):
    from tv_scan_studio import windows

    monkeypatch.setattr(windows.os, "name", "nt")
    for output, expected in (("TradingView\n", True),
                             ("TradingView\nTradingView\n", True),
                             ("chrome\n", False),
                             ("TradingView\nchrome\n", False), ("", False)):
        def fake_run(*args, **kwargs):
            assert "Get-NetTCPConnection" in args[0][-1]
            return CompletedProcess(args[0], 0, stdout=output, stderr="")
        assert cdp_owned_by_tradingview(run=fake_run) is expected
    assert not cdp_owned_by_tradingview(
        run=lambda *args, **kwargs: CompletedProcess(args[0], 1, stdout="TradingView\n", stderr="error"))


def test_cdp_owner_netstat_fallback_after_powershell_access_denied(monkeypatch):
    from tv_scan_studio import windows

    monkeypatch.setattr(windows.os, "name", "nt")
    sockets = ("  TCP    127.0.0.1:9222    0.0.0.0:0    LISTENING    21440\n"
               "  TCP    127.0.0.1:9222    127.0.0.1:50000    TIME_WAIT    0\n")

    def fake_run(args, **_kwargs):
        if "Get-NetTCPConnection" in args[-1]:
            return CompletedProcess(args, 1, stdout="", stderr="Access denied")
        if args[0] == "netstat":
            return CompletedProcess(args, 0, stdout=sockets, stderr="")
        assert "Get-Process -Id $_" in args[-1]
        return CompletedProcess(args, 0, stdout="TradingView\n", stderr="")

    assert cdp_owned_by_tradingview(run=fake_run)


def test_cdp_owner_netstat_fallback_rejects_other_or_unresolved_owner(monkeypatch):
    from tv_scan_studio import windows

    monkeypatch.setattr(windows.os, "name", "nt")

    def fake_run(args, **_kwargs):
        if "Get-NetTCPConnection" in args[-1]:
            return CompletedProcess(args, 1, stdout="", stderr="Access denied")
        if args[0] == "netstat":
            return CompletedProcess(args, 0,
                                    stdout="TCP 127.0.0.1:9222 0.0.0.0:0 LISTENING 21440\n",
                                    stderr="")
        return CompletedProcess(args, 0, stdout="chrome\n", stderr="")

    assert not cdp_owned_by_tradingview(run=fake_run)


def test_wrong_cdp_owner_blocks_chart_reads_and_tab_creation_before_network():
    calls = []
    def fake_open(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Network must not be called")
    with pytest.raises(RuntimeError, match="TradingView Desktop"):
        chart_targets(urlopen=fake_open, owner_check=lambda: False)
    with pytest.raises(RuntimeError, match="yeni sekme açılmadı"):
        open_chart_tabs(1, urlopen=fake_open, owner_check=lambda: False)
    assert not calls
