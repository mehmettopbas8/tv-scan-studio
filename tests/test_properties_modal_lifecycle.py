"""The cost reader must not leave a dialog behind for the next worker task."""

from types import SimpleNamespace

import pytest

from tv_scan_studio.tradingview import GncZihinDriver, TradingViewError


_VALUES = {
    "capital": "100,000", "size": "2", "sizeType": "Quantity",
    "commission": "0.04", "commissionType": "Percent", "slippage": "10",
}


def _driver(responses, guards=None):
    driver = GncZihinDriver.__new__(GncZihinDriver)
    calls = []
    values = iter(responses)
    guard_calls = [0]

    def guard(target):
        guard_calls[0] += 1
        calls.append(("guard", target))
        if guards and guard_calls[0] in guards:
            raise TradingViewError("worker layout changed")

    def evaluate(target, script):
        calls.append(("eval", target, script))
        return next(values)

    driver.target_guard = guard
    driver._motor = SimpleNamespace(_eval=evaluate)
    return driver, calls


def test_owned_properties_dialog_waits_until_actually_closed(monkeypatch):
    monkeypatch.setattr("tv_scan_studio.tradingview.time.sleep", lambda _seconds: None)
    driver, calls = _driver([True, _VALUES, True, False, False, True])
    result = driver.strategy_properties_ui_state("worker-1")
    assert result.slippage_ticks == 10
    checks = [item[2] for item in calls if item[0] == "eval"]
    assert len(checks) == 6
    assert "return ![...document.querySelectorAll" in checks[-1]


def test_ignored_close_fails_instead_of_leaving_successful_read(monkeypatch):
    monkeypatch.setattr("tv_scan_studio.tradingview.time.sleep", lambda _seconds: None)
    driver, calls = _driver([True, _VALUES, True, *([False] * 10)])
    with pytest.raises(TradingViewError, match="kaybolduğu doğrulanamadı"):
        driver.strategy_properties_ui_state("worker-1")
    assert sum(kind == "eval" for kind, *_ in calls) == 13


def test_close_selector_failure_reports_exact_dom_reason():
    driver, calls = _driver([True, _VALUES, {"error": "properties_close_not_unique"}])
    with pytest.raises(TradingViewError, match="properties_close_not_unique"):
        driver.strategy_properties_ui_state("worker-1")
    assert sum(kind == "eval" for kind, *_ in calls) == 3


def test_preexisting_dialog_is_not_closed():
    driver, calls = _driver([{"error": "properties_dialog_already_open"}])
    with pytest.raises(TradingViewError, match="properties_dialog_already_open"):
        driver.strategy_properties_ui_state("worker-1")
    assert sum(kind == "eval" for kind, *_ in calls) == 1


def test_failed_guard_does_not_close_dialog():
    driver, calls = _driver([True, _VALUES], guards={3})
    with pytest.raises(TradingViewError, match="worker layout changed"):
        driver.strategy_properties_ui_state("worker-1")
    assert sum(kind == "eval" for kind, *_ in calls) == 2
