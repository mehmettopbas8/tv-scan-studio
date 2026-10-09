import pytest

from tv_scan_studio.report_warnings import classify_warning, WARNING_DOM_READ
from tv_scan_studio.tradingview import GncZihinDriver, StrategySnapshot


def bound(**changes):
    return dict(bound=True, study_id="s1", strategy_name="EMA", language="en", texts=[], **changes)


def test_warning_defaults_are_unknown():
    snapshot = StrategySnapshot("BIST:XU030D1!", "15", 2, {}, {}, {})
    assert snapshot.warning_state == "unknown" and snapshot.warning_evidence is None


def test_visible_bound_warning_present():
    data = bound()
    data["texts"] = ["Caution! This strategy may use look-ahead bias, which can lead to unrealistically profitable results."]
    result = classify_warning(data, "s1")
    assert result["state"] == "present" and result["text"] == data["texts"][0]


@pytest.mark.parametrize("data", [None, {}, {"bound": False},
    {"bound": True, "study_id": "other", "language": "en", "strategy_name": "EMA", "texts": []},
    {"bound": True, "study_id": "s1", "language": "tr", "strategy_name": "EMA", "texts": []},
    {"bound": True, "study_id": "s1", "language": "en", "strategy_name": "", "texts": []},
    {"bound": True, "study_id": "s1", "language": "en", "strategy_name": "EMA", "texts": [None]}])
def test_missing_ambiguous_unsupported_never_absent(data):
    assert classify_warning(data, "s1")["state"] == "unknown"


def test_no_banner_or_unrelated_alert_does_not_prove_absence():
    data = bound()
    assert classify_warning(data, "s1")["state"] == "unknown"
    data["texts"] = ["Webhook delivery failed — 401 Unauthorized.", "The word look-ahead occurs in a generic explanation."]
    assert classify_warning(data, "s1")["state"] == "unknown"


def test_driver_readback_is_readonly_and_fail_unknown():
    driver = object.__new__(GncZihinDriver)
    observed = []
    driver._eval = lambda target, study, body: observed.append((target, study, body)) or bound()
    assert driver.report_warning_state("target", "s1")["state"] == "unknown"
    assert observed[0] == ("target", "s1", WARNING_DOM_READ)
    assert ".click(" not in WARNING_DOM_READ and ".setInput" not in WARNING_DOM_READ
    assert "data-study-id" in WARNING_DOM_READ and "widgetbar-pages-with-tabs" in WARNING_DOM_READ
    def failure(*args):
        raise RuntimeError("CDP missing")
    driver._eval = failure
    assert driver.report_warning_state("target", "s1")["state"] == "unknown"


def test_snapshot_preserves_warning_fields():
    driver = object.__new__(GncZihinDriver)
    observed = bound()
    observed["texts"] = ["This strategy may use look-ahead bias"]
    calls = []
    driver._eval = lambda *args: calls.append(args) or {
        "status": {"type": 2}, "symbol": "SYM", "tf": "15", "inputs": [], "warning_observed": observed}
    warning = classify_warning(observed, "s1")
    snapshot = driver.snapshot("target", "s1")
    assert snapshot.warning_state == "present" and snapshot.warning_evidence == warning
    assert len(calls) == 1  # no additional CDP round trip per stability poll
