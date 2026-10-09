from types import SimpleNamespace

import pytest

from tv_scan_studio.tradingview import GncZihinDriver, TradingViewError


def model():
    return {"bound": True, "inputs": [{"id": "in_0", "value": 8, "studyId": "owned"}],
            "first_trade_index": 0, "currency": "TRY",
            "performance": {"net_profit": 98, "closed_count": 1, "open_count": 1,
                            "commission_paid": 5},
            "trades": [
                {"tradeNumber": 1, "entry": {"time": 1000, "type": "le"},
                 "exit": {"time": 2000, "type": "lx"}, "profit": {"value": 100},
                 "commission": 3},
                {"tradeNumber": 2, "isOpen": True,
                 "entry": {"time": 3000, "type": "le"},
                 "exit": {"time": 4000, "type": "lx"}, "profit": {"value": -7},
                 "commission": 2}]}


def read(data):
    driver = object.__new__(GncZihinDriver)
    driver.target_guard = lambda target: None
    driver._motor = SimpleNamespace(_eval=lambda target, script: data)
    return driver.normal_report_model_state("target", "owned", {"in_0": 8})


def test_explicit_open_partition_and_entry_commission():
    result = read(model())
    assert result.closed_count == 1
    assert result.open_count == 1
    assert result.open_entry_commission == 2
    assert result.closed_trades[0]["tp"]["v"] == 100
    assert result.currency == "TRY"


@pytest.mark.parametrize("change", [
    lambda d: d.update(bound=False),
    lambda d: d["inputs"][0].update(studyId="personal"),
    lambda d: d["inputs"][0].update(value=9),
    lambda d: d["trades"][1].pop("isOpen"),
    lambda d: d["trades"][1].update(isOpen=False),
    lambda d: d["trades"][1].update(tradeNumber=1),
    lambda d: d["performance"].update(net_profit=99),
    lambda d: d["performance"].update(commission_paid=6),
    lambda d: d["performance"].update(open_count=True),
    lambda d: d.update(first_trade_index=1),
])
def test_ambiguous_or_unreconciled_report_rejected(change):
    data = model()
    change(data)
    with pytest.raises(TradingViewError):
        read(data)


def test_open_row_position_is_not_inferred_from_order():
    data = model()
    data["trades"].reverse()
    result = read(data)
    assert result.closed_count == 1
    assert result.closed_trades[0]["tp"]["v"] == 100


def test_interleaved_open_positions_and_partial_closed_exits():
    from copy import deepcopy
    data = model()
    closed = deepcopy(data["trades"][0])
    closed.update(tradeNumber=3, commission=4)
    closed["profit"]["value"] = 50
    # Same entry time is valid for separately reported partial exits.
    closed["exit"]["time"] = 2500
    opened = deepcopy(data["trades"][1])
    opened.update(tradeNumber=4, commission=1)
    data["trades"] = [opened, data["trades"][0], data["trades"][1], closed]
    data["performance"].update(closed_count=2, open_count=2,
                               commission_paid=10, net_profit=147)
    result = read(data)
    assert result.closed_count == result.open_count == 2
    assert result.open_entry_commission == 3
    assert sum(t["tp"]["v"] for t in result.closed_trades) == 150


def test_two_reads_include_open_row_content_in_stability_check():
    from copy import deepcopy
    first = model()
    second = deepcopy(first)
    second["trades"][1]["profit"]["value"] = -8
    values = iter([first, second])
    driver = object.__new__(GncZihinDriver)
    driver.target_guard = lambda target: None
    driver._motor = SimpleNamespace(_eval=lambda target, script: next(values))
    with pytest.raises(TradingViewError, match="iki okumada"):
        driver.normal_report_model_state("target", "owned", {"in_0": 8})


@pytest.mark.parametrize("change", [
    lambda d: d["trades"][0].update(profit="100"),
    lambda d: d["trades"][0]["profit"].update(value=float("nan")),
    lambda d: d["trades"][0].update(commission=float("inf")),
    lambda d: d["inputs"][0].update(value=float("nan")),
    lambda d: d["trades"][0]["exit"].update(type="sx"),
    lambda d: d["trades"][0]["entry"].update(time=True),
    lambda d: d["trades"][0]["exit"].update(time=0),
])
def test_nonfinite_malformed_or_invalid_closed_rows_fail_closed(change):
    data = model()
    change(data)
    with pytest.raises(TradingViewError):
        read(data)
