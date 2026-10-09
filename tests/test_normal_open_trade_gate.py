"""Normal chart summaries cannot treat synthetic open trades as closed results."""

from types import SimpleNamespace

import pytest

from tv_scan_studio.storage import Store
from tv_scan_studio.tradingview import GncZihinDriver, StrategySnapshot, NormalReportModelState
from tv_scan_studio.worker import ScanWorker


def test_snapshot_exposes_native_open_count_and_first_index():
    driver = GncZihinDriver.__new__(GncZihinDriver)
    captured = []
    driver._eval = lambda target, study, script: captured.append(script) or {
        "status": {"type": 2}, "symbol": "OANDA:EURUSD", "tf": "15",
        "inputs": [{"id": "in_0", "value": 7}],
        "metrics": {"trades": 1, "observed_open_trade_count": 1,
                    "report_first_trade_index": 0, "profit_factor": 1.5,
                    "win_rate_pct": 50, "max_drawdown_pct": 2,
                    "net_profit": 100, "net_profit_pct": 1},
        "trades": [], "period": {}, "warning_observed": None,
    }
    result = driver.snapshot("target", "study")
    assert result.metrics["observed_open_trade_count"] == 1
    assert result.metrics["report_first_trade_index"] == 0
    assert "a.totalOpenTrades" in captured[0]
    assert "r?.firstTradeIndex" in captured[0]


def _run(tmp_path, open_count, model=None):
    store = Store(tmp_path / "normal-open.db")
    project = store.create_project("Open position", 'strategy("Open position")')
    store.enqueue(project, "single", {"study_id": "study", "symbol": "OANDA:EURUSD",
        "timeframe": "15", "inputs": {"in_0": 7}, "timeout": 1,
        "poll_interval": 0, "stable_reads": 3})
    trade = {"e": {"tm": 1_700_000_000_000, "tp": "long"},
             "x": {"tm": 1_700_000_060_000}, "tp": {"v": 99.5}}
    result = StrategySnapshot("OANDA:EURUSD", "15", 2, {"in_0": 7},
        {"trades": 1, "observed_open_trade_count": open_count,
         "report_first_trade_index": 0, "profit_factor": 1.5,
         "win_rate_pct": 50, "max_drawdown_pct": 2, "net_profit": 100},
        {}, (trade,))
    driver = SimpleNamespace(configure=lambda *_: None, snapshot=lambda *_: result)
    if model is not None:
        driver.normal_report_model_state = lambda *_: model
    assert ScanWorker(1, "target", store, driver,
                      target_guard=lambda *_: None).run_one() is True
    return store, project


@pytest.mark.parametrize("open_count", [1, None, -1, True])
def test_observed_open_or_invalid_count_is_rejected_before_tolerant_reconciliation(tmp_path, open_count):
    store, project = _run(tmp_path, open_count)
    row = store.results(project)[0]
    assert row["classification"] == "geçersiz"
    assert row["verified"] == 0
    assert "trade_analysis_net_profit" not in row["metrics"]
    assert row["metrics"]["observed_open_trade_count"] == open_count


def test_observed_zero_open_count_keeps_normal_closed_path(tmp_path):
    store, project = _run(tmp_path, 0)
    row = store.results(project)[0]
    assert row["verified"] == 1
    assert row["metrics"]["trade_analysis_net_profit"] == 99.5
    assert row["metrics"]["trade_pnl_reconciled"] is True


def _model(profit):
    trade = {"e": {"tm": 1_700_000_000_000, "tp": "long"},
             "x": {"tm": 1_700_000_060_000}, "tp": {"v": profit}}
    return NormalReportModelState((trade,), 1, 1, 2, 100, 5, "TRY", {"in_0": 7})


def test_bound_model_counts_only_closed_and_adjusts_open_entry_commission(tmp_path):
    store, project = _run(tmp_path, 1, _model(102))
    row = store.results(project)[0]
    assert row["verified"] == 1
    assert row["metrics"]["analyzed_trades"] == 1
    assert row["metrics"]["trade_analysis_net_profit"] == 102
    assert row["metrics"]["net_profit"] == 100
    assert row["metrics"]["trade_report_net_delta"] == 0
    assert row["evidence"]["report_currency"] == "TRY"


def test_bound_model_cannot_pass_old_relative_tolerance(tmp_path):
    store, project = _run(tmp_path, 1, _model(101.5))
    row = store.results(project)[0]
    assert row["verified"] == 0
    assert row["metrics"]["trade_pnl_reconciled"] is False
