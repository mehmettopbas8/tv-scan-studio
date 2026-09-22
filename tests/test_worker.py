from tv_scan_studio.storage import Store
from tv_scan_studio.tradingview import StrategySnapshot, TradingViewError, date_range_matches, wait_for_verified_result
from tv_scan_studio.worker import ScanWorker, classify


class FakeDriver:
    def __init__(self, snapshots):
        self.snapshots = iter(snapshots)
        self.configured = []

    def targets(self):
        return ["target-1", "target-2"]

    def configure(self, target_id, study_id, symbol, timeframe, inputs):
        self.configured.append((target_id, study_id, symbol, timeframe, inputs))

    def snapshot(self, target_id, study_id):
        return next(self.snapshots)


def snapshot(symbol="OANDA:EURUSD", timeframe="15", inputs=None, period=None):
    return StrategySnapshot(
        symbol=symbol,
        timeframe=timeframe,
        status_type=2,
        inputs=inputs or {"in_0": 20},
        metrics={"trades": 100, "profit_factor": 1.5, "win_rate_pct": 45, "max_drawdown_pct": 4, "net_profit": 1000},
        period=period if period is not None else {},
    )


def test_wait_requires_stable_matching_symbol_timeframe_inputs_and_period():
    expected = {"symbol": "OANDA:EURUSD", "timeframe": "15", "inputs": {"in_0": 20}, "date_range": {"from": "2025-01-01", "to": "2025-12-31"}}
    driver = FakeDriver([
        snapshot(symbol="OANDA:GBPUSD", period={"dateRange": {"backtest": {"from": 1735678800000, "to": 1767128400000}}}),
        *[snapshot(period={"dateRange": {"backtest": {"from": 1735678800000, "to": 1767128400000}}}) for _ in range(3)],
    ])
    result = wait_for_verified_result(driver, "target-1", "study-1", expected, timeout=1, poll_interval=0, stable_reads=3)
    assert result.metrics["profit_factor"] == 1.5


def test_date_range_requires_real_backtest_period():
    period = {"dateRange": {"backtest": {"from": 1735678800000, "to": 1767128400000}}}
    assert date_range_matches({"from": "2025-01-01", "to": "2025-12-31"}, period)
    assert not date_range_matches({"from": "2024-01-01"}, period)
    assert not date_range_matches({"from": "2025-01-01"}, {})


def test_scan_worker_completes_a_verified_task(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Scan", 'strategy("Scan")')
    payload = {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20}, "timeout": 1, "poll_interval": 0,
        "criteria": {"min_trades": 60, "min_profit_factor": 1.4, "max_drawdown_pct": 5},
    }
    store.enqueue(project, "task-1", payload)
    driver = FakeDriver([snapshot(), snapshot(), snapshot()])

    assert ScanWorker(1, "target-1", store, driver, [project]).run_one() is True
    assert store.counts(project) == {"done": 1}
    assert store.results(project)[0]["classification"] == "hassas"
    assert store.results(project)[0]["evidence"]["target_id"] == "target-1"
    assert driver.configured[0][0] == "target-1"


def test_worker_applies_and_verifies_cost_inputs(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Costs", 'strategy("Costs")')
    payload = {"study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
               "inputs": {"in_0": 20}, "costs": {"tradingview_inputs": {"commission_value": 0.1}},
               "timeout": 1, "poll_interval": 0}
    store.enqueue(project, "cost", payload)
    cost_snapshot = snapshot(inputs={"in_0": 20, "commission_value": 0.1})
    driver = FakeDriver([cost_snapshot, cost_snapshot, cost_snapshot])
    ScanWorker(1, "target-1", store, driver).run_one()
    assert driver.configured[0][-1]["commission_value"] == 0.1
    assert store.counts(project) == {"done": 1}


def test_worker_uses_target_specific_study_id(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Layout", 'strategy("Layout")')
    payload = {"study_id": "project-default", "symbol": "OANDA:EURUSD", "timeframe": "15",
               "inputs": {"in_0": 20}, "timeout": 1, "poll_interval": 0}
    store.enqueue(project, "layout", payload)
    driver = FakeDriver([snapshot(), snapshot(), snapshot()])
    ScanWorker(1, "target-1", store, driver, study_id_override="layout-specific").run_one()
    assert driver.configured[0][1] == "layout-specific"
    assert store.results(project)[0]["evidence"]["study_id"] == "layout-specific"


def test_classification_rejects_failed_criteria():
    assert classify({"trades": 20, "profit_factor": 2, "win_rate_pct": 60, "max_drawdown_pct": 2, "net_profit": 5}, {"min_trades": 60}) == "elenmiş"


def test_classification_requires_all_robustness_gates():
    metrics = {"trades": 100, "profit_factor": 1.5, "win_rate_pct": 45,
               "max_drawdown_pct": 4, "net_profit": 1000}
    validation = {"neighbor_passed": True, "cost_stress_passed": True, "provider_check_passed": True}
    assert classify(metrics, {"min_trades": 60}, validation) == "dayanıklı"
    assert classify(metrics, {"min_trades": 60}, {}) == "hassas"


def test_classification_applies_ftmo_loss_limits_when_metrics_exist():
    metrics = {"trades": 100, "profit_factor": 1.5, "win_rate_pct": 45,
               "max_drawdown_pct": 4, "max_daily_loss_pct": 5.1, "net_profit": 1000}
    assert classify(metrics, {"max_daily_loss_pct": 5, "max_total_loss_pct": 10}) == "elenmiş"


def test_persistent_verification_mismatch_becomes_invalid(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Invalid", 'strategy("Invalid")')
    payload = {"study_id": "sid", "symbol": "OANDA:EURUSD", "timeframe": "15",
               "inputs": {"in_0": 20}, "timeout": 0.001, "poll_interval": 0}
    store.enqueue(project, "invalid", payload)
    wrong = snapshot(symbol="OANDA:GBPUSD")
    for _ in range(3):
        ScanWorker(1, "target-1", store, FakeDriver([wrong] * 100)).run_one()
    assert store.counts(project) == {"failed": 1}
    result = store.results(project)[0]
    assert result["classification"] == "geçersiz"
    assert result["verified"] is False
    assert result["evidence"]["symbol"] == "OANDA:GBPUSD"
