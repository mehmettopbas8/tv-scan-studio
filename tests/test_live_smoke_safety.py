import sys

import pytest

from tools import live_two_worker_smoke as smoke


def test_live_smoke_never_reads_tabs_when_9222_is_unavailable(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["smoke", "--strategy-name", "Demo",
                                   "--execute", "I_UNDERSTAND"])
    monkeypatch.setattr(smoke, "cdp_healthy", lambda port: False)
    monkeypatch.setattr(smoke, "chart_targets", lambda **_kwargs: pytest.fail(
        "No targets should be read without CDP 9222"))
    with pytest.raises(SystemExit, match="9222 hazır değil"):
        smoke.main()


def test_live_smoke_rejects_duplicate_layout_ids_before_worker(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["smoke", "--strategy-name", "Demo",
                                   "--execute", "I_UNDERSTAND"])
    monkeypatch.setattr(smoke, "cdp_healthy", lambda port: True)

    class Driver:
        def layout_name(self, target):
            return {"first": "TV Scan Worker 1", "second": "TV Scan Worker 2"}[target]

    monkeypatch.setattr(smoke, "GncZihinDriver", Driver)
    monkeypatch.setattr(smoke, "chart_targets", lambda **_kwargs: [
        {"id": "first", "url": "https://www.tradingview.com/chart/Same/"},
        {"id": "second", "url": "https://www.tradingview.com/chart/Same/"}])
    with pytest.raises(ValueError, match="benzersiz"):
        smoke.main()


def test_live_smoke_inspects_only_named_distinct_worker_layouts(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["smoke", "--strategy-name", "Demo",
                                   "--execute", "I_UNDERSTAND"])
    monkeypatch.setattr(smoke, "cdp_healthy", lambda port: True)
    inspected = []

    class Driver:
        def layout_name(self, target):
            return {"original": "Coding", "first": "TV Scan Worker 1",
                    "second": "TV Scan Worker 2"}[target]

        def strategies(self, target):
            inspected.append(target)
            return []

    monkeypatch.setattr(smoke, "GncZihinDriver", Driver)
    monkeypatch.setattr(smoke, "chart_targets", lambda **_kwargs: [
        {"id": "original", "url": "https://www.tradingview.com/chart/Coding/"},
        {"id": "first", "url": "https://www.tradingview.com/chart/First/"},
        {"id": "second", "url": "https://www.tradingview.com/chart/Second/"}])
    with pytest.raises(SystemExit, match="tek bir hazır"):
        smoke.main()
    assert inspected == ["first"]
