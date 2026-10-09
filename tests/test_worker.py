import pytest
from dataclasses import replace
from types import SimpleNamespace

from tv_scan_studio.storage import Store
from tv_scan_studio.tradingview import (GncZihinDriver, StrategySnapshot, TradingViewError,
                                        chart_resolution, date_range_matches, symbol_matches,
                                        wait_for_verified_result)
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

    def chart_timezone(self, target_id):
        return "Europe/Istanbul"


@pytest.mark.parametrize("label,resolution", [
    ("1m", "1"), ("5m", "5"), ("15", "15"), ("1H", "60"),
    ("4h", "240"), ("1D", "D"), ("1W", "W"), ("1M", "1M"),
])
def test_chart_resolution_preserves_minutes_vs_months(label, resolution):
    assert chart_resolution(label) == resolution


def test_one_minute_result_cannot_be_verified_on_monthly_chart():
    driver = FakeDriver([snapshot(timeframe="1M") for _ in range(20)])
    with pytest.raises(TradingViewError):
        wait_for_verified_result(driver, "target-1", "study-1", {
            "symbol": "OANDA:EURUSD", "timeframe": "1m", "inputs": {},
        }, timeout=0.1, poll_interval=0, stable_reads=2)


def snapshot(symbol="OANDA:EURUSD", timeframe="15", inputs=None, period=None,
             report_source="chart"):
    return StrategySnapshot(
        symbol=symbol,
        timeframe=timeframe,
        status_type=2,
        inputs=inputs if inputs is not None else {"in_0": 20},
        metrics={"trades": 100, "profit_factor": 1.5, "win_rate_pct": 45, "max_drawdown_pct": 4, "net_profit": 1000},
        period=period if period is not None else {},
        report_source=report_source,
    )


def test_wait_requires_stable_matching_symbol_timeframe_inputs_and_period():
    expected = {"symbol": "OANDA:EURUSD", "timeframe": "15", "inputs": {"in_0": 20}, "date_range": {"from": "2025-01-01", "to": "2025-12-31"}}
    driver = FakeDriver([
        snapshot(symbol="OANDA:GBPUSD", period={"dateRange": {"backtest": {"from": 1735678800000, "to": 1767128400000}}}),
        *[snapshot(period={"dateRange": {"backtest": {"from": 1735678800000, "to": 1767128400000}}},
                   report_source="deep_strategy_report") for _ in range(3)],
    ])
    result = wait_for_verified_result(driver, "target-1", "study-1", expected, timeout=1, poll_interval=0, stable_reads=3)
    assert result.metrics["profit_factor"] == 1.5


def test_old_completed_report_is_rejected_until_new_report_even_with_identical_metrics():
    expected = {"symbol": "OANDA:EURUSD", "timeframe": "15", "inputs": {"in_0": 20},
                "require_fresh_report": True}
    old = replace(snapshot(), report_fresh=False)
    fresh = replace(snapshot(), report_fresh=True)
    driver = FakeDriver([old] * 5 + [fresh] * 3)
    result = wait_for_verified_result(driver, "target-1", "study-1", expected,
        timeout=1, poll_interval=0, stable_reads=3)
    assert result.report_fresh is True
    assert result.metrics == old.metrics  # Identical outcomes are legal; stale objects are not.


def test_report_currency_must_stabilize_with_metrics_before_verification():
    usd = replace(snapshot(), report_currency="USD")
    lira = replace(snapshot(), report_currency="TRY")
    driver = FakeDriver([usd, usd, lira, lira, lira])
    result = wait_for_verified_result(driver, "target-1", "study-1",
        {"symbol": "OANDA:EURUSD", "timeframe": "15", "inputs": {"in_0": 20}},
        timeout=1, poll_interval=0, stable_reads=3)
    assert result.report_currency == "TRY"
    with pytest.raises(StopIteration):
        next(driver.snapshots)


@pytest.mark.parametrize("fresh", [False, None])
def test_stable_input_echo_without_report_freshness_cannot_verify(fresh):
    from tv_scan_studio.tradingview import VerificationMismatch
    driver = FakeDriver([replace(snapshot(), report_fresh=fresh)] * 30)
    with pytest.raises(VerificationMismatch):
        wait_for_verified_result(driver, "target-1", "study-1",
            {"symbol": "OANDA:EURUSD", "timeframe": "15", "inputs": {"in_0": 20},
             "require_fresh_report": True}, timeout=.1, poll_interval=0, stable_reads=3)


def test_report_restart_requires_guard_and_records_old_object_before_restart():
    driver = GncZihinDriver()
    with pytest.raises(TradingViewError, match="koruması"):
        driver.refresh_chart_report("owned", "study")
    events = []
    driver.target_guard = lambda target: events.append(("guard", target))
    def evaluate(target, study, body):
        assert body.index("before:s.reportData()") < body.index("s.restart(true)")
        events.append(("restart", target))
        return True
    driver._eval = evaluate
    driver.refresh_chart_report("owned", "study")
    assert events == [("guard", "owned"), ("restart", "owned"), ("guard", "owned")]


def test_matching_chart_dates_cannot_verify_deep_report():
    from tv_scan_studio.tradingview import VerificationMismatch

    period = {"dateRange": {"backtest": {"from": 1735678800000, "to": 1767128400000}}}
    expected = {"symbol": "OANDA:EURUSD", "timeframe": "15", "inputs": {"in_0": 20},
                "date_range": {"from": "2025-01-01", "to": "2025-12-31"}}
    driver = FakeDriver([snapshot(period=period) for _ in range(20)])
    with pytest.raises(VerificationMismatch):
        wait_for_verified_result(driver, "target-1", "study-1", expected,
                                 timeout=0.1, poll_interval=0, stable_reads=2)


@pytest.mark.parametrize("observed,expected_value", [(True, 1), (1, True), (None, None)])
def test_chart_result_rejects_wrong_input_type_or_missing_key(observed, expected_value):
    from tv_scan_studio.tradingview import VerificationMismatch

    inputs = {} if observed is None else {"in_0": observed}
    driver = FakeDriver([snapshot(inputs=inputs) for _ in range(30)])
    with pytest.raises(VerificationMismatch):
        wait_for_verified_result(driver, "target-1", "study-1", {
            "symbol": "OANDA:EURUSD", "timeframe": "15", "inputs": {"in_0": expected_value},
        }, timeout=0.1, poll_interval=0, stable_reads=2)


def test_date_range_requires_real_backtest_period():
    period = {"dateRange": {"backtest": {"from": 1735678800000, "to": 1767128400000}}}
    assert date_range_matches({"from": "2025-01-01", "to": "2025-12-31"}, period, "Europe/Istanbul")
    assert not date_range_matches({"from": "2024-01-01"}, period, "Europe/Istanbul")
    assert not date_range_matches({"from": "2025-01-01"}, {}, "Europe/Istanbul")
    assert not date_range_matches({"from": "2025-01-01"}, period)
    assert not date_range_matches({"from": "2025-01-01"}, period, "UTC")
    assert not date_range_matches({"from": "2025-01-01"}, period, "Invalid/Zone")
    assert date_range_matches({"from_ms": 1735678800000, "to_ms": 1767128400000}, period)
    assert not date_range_matches({"from_ms": 1735678800001}, period)


def test_provider_qualified_symbol_must_match_exactly():
    assert symbol_matches("OANDA:DE30EUR", "OANDA:DE30EUR")
    assert not symbol_matches("OANDA:DE30EUR", "FX:DE30EUR")
    assert symbol_matches("DE30EUR", "OANDA:DE30EUR")


def test_delayed_symbol_requires_authoritative_current_series_identity():
    identity = {"full_name": "BIST_DLY:XU030D1!", "pro_name": "BIST:XU030D1!",
                "name": "XU030D1!", "exchange": "BIST"}
    assert symbol_matches("BIST:XU030D1!", "BIST_DLY:XU030D1!", identity)
    assert not symbol_matches("BIST:XU030D1!", "BIST_DLY:XU030D1!")
    for key in identity:
        assert not symbol_matches("BIST:XU030D1!", "BIST_DLY:XU030D1!",
                                  {**identity, key: "different"})
    assert not symbol_matches("FX:XU030D1!", "BIST_DLY:XU030D1!", identity)


def test_delayed_symbol_can_verify_stable_results_without_relaxing_provider():
    observed = replace(snapshot(symbol="BIST_DLY:XU030D1!"), symbol_identity={
        "full_name": "BIST_DLY:XU030D1!", "pro_name": "BIST:XU030D1!",
        "name": "XU030D1!", "exchange": "BIST"})
    result = wait_for_verified_result(FakeDriver([observed] * 3), "target-1", "study-1",
        {"symbol": "BIST:XU030D1!", "timeframe": "15", "inputs": {"in_0": 20}},
        timeout=1, poll_interval=0, stable_reads=3)
    assert result.symbol_identity["pro_name"] == "BIST:XU030D1!"


@pytest.mark.parametrize("warning_state", ["unknown", "present"])
def test_scan_worker_completes_a_verified_task(tmp_path, warning_state):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Scan", 'strategy("Scan")')
    payload = {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20}, "timeout": 1, "poll_interval": 0,
        "criteria": {"min_trades": 60, "min_profit_factor": 1.4, "max_drawdown_pct": 5},
    }
    store.enqueue(project, "task-1", payload)
    warning = {"state": warning_state, "provenance": "strategy_report_dom"}
    driver = FakeDriver([replace(snapshot(), warning_state=warning_state,
                                 warning_evidence=warning) for _ in range(3)])

    assert ScanWorker(1, "target-1", store, driver, [project]).run_one() is True
    assert store.counts(project) == {"done": 1}
    assert store.results(project)[0]["classification"] == "hassas"
    assert store.results(project)[0]["evidence"]["target_id"] == "target-1"
    assert store.results(project)[0]["evidence"]["tradingview_warning_state"] == warning_state
    assert store.results(project)[0]["evidence"]["tradingview_warning_evidence"] == warning
    task_id = store.results(project)[0]["task_id"]
    assert store.result_history(task_id)[-1]["warning_state"] == warning_state
    assert driver.configured[0][0] == "target-1"


@pytest.mark.parametrize("currency", ["USD", "TRY", None])
def test_normal_worker_preserves_explicit_report_currency_and_history(tmp_path, currency):
    store = Store(tmp_path / "currency.db")
    project = store.create_project("Currency", 'strategy("Currency")')
    store.enqueue(project, "currency-task", {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20}, "timeout": 1, "poll_interval": 0,
    })
    driver = FakeDriver([replace(snapshot(), report_currency=currency)] * 3)
    assert ScanWorker(1, "target-1", store, driver, [project]).run_one()
    result = store.results(project)[0]
    assert result["verified"] is True
    assert result["evidence"]["report_currency"] == currency
    assert result["evidence"]["report_currency_provenance"] == ("strategy_report_currency" if currency else "unknown")
    assert store.result_history(result["task_id"])[-1]["evidence"]["report_currency"] == currency


def test_layout_guard_blocks_configuration_when_tab_changes(tmp_path):
    store = Store(tmp_path / "guard.db")
    project = store.create_project("Guard", 'strategy("Guard")')
    store.enqueue(project, "guard-task", {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20}})
    driver = FakeDriver([])
    def changed_layout(_target_id):
        raise ValueError("Worker layoutu değişti")
    with pytest.raises(ValueError, match="Worker layoutu değişti"):
        ScanWorker(1, "target-1", store, driver, target_guard=changed_layout).run_one()
    assert driver.configured == []
    assert store.counts(project) == {"pending": 1}
    assert store.tasks(project_id=project)[0]["attempts"] == 0


def test_requested_dates_without_application_are_invalid_before_chart_mutation(tmp_path):
    store = Store(tmp_path / "dates.db")
    project = store.create_project("Dates", 'strategy("Dates")')
    store.enqueue(project, "date-task", {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20},
        "date_range": {"from": "2025-01-01", "to": "2025-12-31"},
    })
    driver = FakeDriver([])
    assert ScanWorker(1, "target-1", store, driver).run_one() is True
    assert driver.configured == []
    result = store.results(project)[0]
    assert result["classification"] == "geçersiz"
    assert result["verified"] is False
    assert result["evidence"]["requested_date_range"]["from"] == "2025-01-01"


def test_date_ui_ready_alone_cannot_complete_without_deep_capture(tmp_path):
    store = Store(tmp_path / "date-no-deep.db")
    project = store.create_project("Dates", 'strategy("Dates")')
    store.enqueue(project, "date-task", {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20},
        "date_range": {"from": "2025-01-01", "to": "2025-12-31"},
    })
    driver = FakeDriver([])
    driver.date_range_ready = True
    driver.configure_date_range = lambda *_args: pytest.fail("date UI must not be touched")
    assert ScanWorker(1, "target-1", store, driver).run_one() is True
    assert driver.configured == []
    assert store.results(project)[0]["verified"] is False


def test_dated_worker_requires_download_folder_before_chart_mutation(tmp_path):
    store = Store(tmp_path / "missing-downloads.db")
    project = store.create_project("Dates", 'strategy("Dates")')
    store.enqueue(project, "date-task", {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20},
        "date_range": {"from": "2025-01-01", "to": "2025-12-31"},
    })
    class DeepDriver(FakeDriver):
        date_range_ready = True
        deep_capture_ready = True
        def configure_date_range(self, *_args): pytest.fail("date UI must not be touched")
        def refresh_deep_report(self, *_args): return True
        def download_deep_xlsx(self, *_args): return True
        def deep_report_ui_state(self, *_args): return None
        def chart_timezone(self, *_args): return "UTC"
        def strategy_properties_ui_state(self, *_args): return None
    driver = DeepDriver([])
    assert ScanWorker(1, "target-1", store, driver, [project],
                      target_guard=lambda _target: None,
                      download_directory=tmp_path / "missing").run_one() is True
    assert driver.configured == []
    assert store.results(project)[0]["verified"] is False


def test_dated_worker_uses_deep_capture_not_chart_summary(tmp_path, monkeypatch):
    from tv_scan_studio import worker as worker_module

    store = Store(tmp_path / "dated-deep.db")
    project = store.create_project("Dates", 'strategy("Dates")\nlength=input.int(20,"Length")')
    store.enqueue(project, "date-task", {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 21},
        "date_range": {"from": "2025-01-01", "to": "2025-12-31"},
        "costs": {"assumptions": {"initial_capital": 100000}},
    })

    class DeepDriver(FakeDriver):
        date_range_ready = True
        deep_capture_ready = True
        def configure_date_range(self, *_args): pass
        def refresh_deep_report(self, *_args): return True
        def download_deep_xlsx(self, *_args): return True
        def deep_report_ui_state(self, *_args): return None
        def chart_timezone(self, *_args): return "UTC"
        def strategy_properties_ui_state(self, *_args): return None

    driver = DeepDriver([snapshot(inputs={"in_0": 20})])
    calls = []
    def fake_capture(_driver, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            report=SimpleNamespace(
                metrics={"trades": 100, "profit_factor": 1.5, "win_rate_pct": 45,
                         "max_drawdown_pct": 4, "net_profit": 1000}, sha256="fresh-task-xlsx"),
            trades=(), chart_timezone="UTC", verified_changed_inputs=("in_0",), symbol_identity=None,
            report_period={"from_ms": 1735689600000, "to_ms": 1767225599999},
            report_currency=None, warning_state="unknown", warning_evidence=None,
        )
    monkeypatch.setattr(worker_module, "capture_task_deep_export", fake_capture)
    guard = lambda target: None
    worker = ScanWorker(1, "target-1", store, driver, [project], target_guard=guard,
                        download_directory=tmp_path)
    assert worker.run_one() is True
    result = store.results(project)[0]
    assert result["verified"] is True
    assert result["evidence"]["report_source"] == "deep_xlsx"
    assert result["evidence"]["deep_sha256"] == "fresh-task-xlsx"
    assert result["evidence"]["period"] == {"from_ms": 1735689600000, "to_ms": 1767225599999}
    assert result["evidence"]["report_period_provenance"] == "deep_export_observed"
    assert result["evidence"]["requested_date_range"] == {"from": "2025-01-01", "to": "2025-12-31"}
    assert result["evidence"]["tradingview_warning_state"] == "unknown"
    assert result["evidence"]["cost_verification_scope"] == "strategy_properties_ui_and_xlsx_spread_unverified"
    assert calls[0]["changed_input_ids"] == {"in_0"}
    assert calls[0]["guard"] is guard
    assert len(driver.configured) == 1


def test_dated_worker_does_not_complete_if_deep_capture_fails(tmp_path, monkeypatch):
    from tv_scan_studio import worker as worker_module

    store = Store(tmp_path / "dated-fail.db")
    project = store.create_project("Dates", 'strategy("Dates")')
    store.enqueue(project, "date-task", {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20},
        "date_range": {"from": "2025-01-01", "to": "2025-12-31"},
    })
    class DeepDriver(FakeDriver):
        date_range_ready = True
        deep_capture_ready = True
        def configure_date_range(self, *_args): pass
        def refresh_deep_report(self, *_args): return True
        def download_deep_xlsx(self, *_args): return True
        def deep_report_ui_state(self, *_args): return None
        def chart_timezone(self, *_args): return "UTC"
        def strategy_properties_ui_state(self, *_args): return None
    driver = DeepDriver([snapshot()])
    def fail_capture(*_args, **_kwargs):
        raise ValueError("Deep XLSX report stale")
    monkeypatch.setattr(worker_module, "capture_task_deep_export", fail_capture)
    assert ScanWorker(1, "target-1", store, driver, [project],
                      target_guard=lambda _target: None,
                      download_directory=tmp_path).run_one() is True
    assert store.counts(project) == {"pending": 1}
    assert store.results(project) == []


def test_live_driver_rechecks_layout_before_each_mutation(monkeypatch):
    from tv_scan_studio import tradingview

    driver = GncZihinDriver.__new__(GncZihinDriver)
    calls = []
    driver._eval = lambda _target, _study, body: calls.append(body)
    def guard(_target):
        if len(calls) == 1:
            raise ValueError("layout switched after symbol")
    driver.target_guard = guard
    monkeypatch.setattr(tradingview.time, "sleep", lambda _seconds: None)
    with pytest.raises(ValueError, match="layout switched"):
        driver.configure("worker-1", "study", "OANDA:XAUUSD", "15", {"in_0": 4})
    assert len(calls) == 1
    assert "setSymbol" in calls[0]


def test_live_driver_sends_one_minute_not_monthly_resolution(monkeypatch):
    from tv_scan_studio import tradingview

    driver = GncZihinDriver.__new__(GncZihinDriver)
    calls = []
    driver.target_guard = lambda _target: None
    driver._eval = lambda _target, _study, body: calls.append(body)
    monkeypatch.setattr(tradingview.time, "sleep", lambda _seconds: None)

    driver.configure("worker-1", "study", "OANDA:EURUSD", "1m", {})

    assert 'c.setResolution("1",{})' in calls[1]
    assert 'c.setResolution("1M",{})' not in calls[1]


def test_date_ui_adapter_guards_every_step_but_is_not_enabled(monkeypatch):
    from tv_scan_studio import tradingview

    driver = GncZihinDriver.__new__(GncZihinDriver)
    actions = []
    driver.target_guard = lambda target: actions.append(("guard", target))
    driver._motor = SimpleNamespace(insert_text=lambda target, value: actions.append(("insert", target, value)))
    def evaluate(target, study, body):
        actions.append(("eval", target, study, body))
        if "fields[0].blur();return fields[0].value" in body:
            return "2025-01-01"
        if "fields[1].blur();return fields[1].value" in body:
            return "2025-12-31"
        return True
    driver._eval = evaluate
    monkeypatch.setattr(tradingview.time, "sleep", lambda _seconds: None)
    driver.configure_date_range("worker-1", "study-1", {
        "from": "2025-01-01", "to": "2025-12-31"})
    assert driver.date_range_ready is True
    assert tuple(d.isoformat() for d in driver._configured_report_dates['worker-1']) == (
        '2025-01-01', '2025-12-31')
    assert [action[0] for action in actions] == (
        ["guard", "eval"] * 2
        + ["guard", "eval", "guard", "insert", "guard", "eval"] * 2
        + ["guard", "eval"]
    )
    assert "strategy_report_date_trigger_missing" in actions[1][3]
    assert "custom_date_range_action_missing" in actions[3][3]
    assert actions[7] == ("insert", "worker-1", "2025-01-01")
    assert actions[13] == ("insert", "worker-1", "2025-12-31")
    assert "date_submit_unavailable" in actions[-1][3]


def test_date_ui_adapter_rejects_unconfirmed_field_before_submit(monkeypatch):
    from tv_scan_studio import tradingview

    driver = GncZihinDriver.__new__(GncZihinDriver)
    driver.target_guard = lambda _target: None
    driver._configured_report_dates = {'worker-1': ('old', 'receipt')}
    driver._motor = SimpleNamespace(insert_text=lambda *_args: pytest.fail("must not type"))
    actions = []
    def evaluate(_target, _study, body):
        actions.append(body)
        return False if "field.focus();field.select()" in body else True
    driver._eval = evaluate
    monkeypatch.setattr(tradingview.time, "sleep", lambda _seconds: None)
    with pytest.raises(TradingViewError, match="beklenen adımı onaylamadı"):
        driver.configure_date_range("worker-1", "study-1", {
            "from": "2025-01-01", "to": "2025-12-31"})
    assert len(actions) == 3
    assert "submit.click" not in "".join(actions)
    assert 'worker-1' not in driver._configured_report_dates


def test_date_ui_adapter_rejects_bad_range_and_missing_layout_guard():
    driver = GncZihinDriver.__new__(GncZihinDriver)
    driver.target_guard = None
    with pytest.raises(TradingViewError, match="Geçersiz"):
        driver.configure_date_range("worker-1", "study-1", {
            "from": "2025-12-31", "to": "2025-01-01"})
    with pytest.raises(TradingViewError, match="layout koruması"):
        driver.configure_date_range("worker-1", "study-1", {
            "from": "2025-01-01", "to": "2025-12-31"})


def test_replay_preflight_uses_visible_state_and_fails_closed():
    driver = GncZihinDriver.__new__(GncZihinDriver)
    class Motor:
        state = None
        def _eval(self, _target, expression):
            assert 'replay-bottom-toolbar' in expression
            assert 'Bar replay' in expression
            return self.state
    driver._motor = Motor()
    driver._motor.state = True
    assert driver.replay_active("worker-1") is True
    driver._motor.state = False
    assert driver.replay_active("worker-2") is False
    driver._motor.state = None
    with pytest.raises(TradingViewError, match="Replay durumu okunamadı"):
        driver.replay_active("worker-1")


def test_deep_report_ui_state_parses_visible_key_stats_and_rejects_ambiguity():
    driver = GncZihinDriver.__new__(GncZihinDriver)

    class Motor:
        result = None

        def _eval(self, target, expression):
            assert target == "worker-2"
            assert "Key stats" in expression
            assert 'widgetbar-pages-with-tabs' in expression
            return self.result

    driver._motor = Motor()
    driver._motor.result = {
        "dateLabel": "Sep 7, 2026 — Sep 20, 2026", "deep": True,
        "pending": False, "totalPnl": "Total PnL+17.91USD+0.02%",
        "maxDrawdown": "Max drawdown28.72USD0.03%",
        "profitableTrades": "Profitable trades50.00%14/28",
        "profitFactor": "Profit factor1.328",
        "grossProfit": "Gross profit117.91USD", "grossLoss": "Gross loss100.00USD",
    }
    result = driver.deep_report_ui_state("worker-2")
    assert result.date_label == "Sep 7, 2026 — Sep 20, 2026"
    assert result.update_pending is False
    assert result.total_pnl == 17.91
    assert result.metrics == {"net_profit": 17.91, "max_drawdown_pct": 0.03,
                              "win_rate_pct": 50, "trades": 28, "profit_factor": 1.328}
    driver._motor.result["totalPnl"] = "Total PnL−632.09USD−0.63%"
    with_open = driver.deep_report_ui_state("worker-2")
    assert with_open.metrics["net_profit"] == 17.91
    assert with_open.total_pnl == -632.09
    saved = driver._motor.result.pop("grossProfit")
    with pytest.raises(TradingViewError, match="temel metrik"):
        driver.deep_report_ui_state("worker-2")
    driver._motor.result["grossProfit"] = saved
    driver._motor.result = {**driver._motor.result, "pending": None}
    with pytest.raises(TradingViewError, match="güncelleme/tarih"):
        driver.deep_report_ui_state("worker-2")
    driver._motor.result = {**driver._motor.result, "error": "deep_report_not_unique"}
    with pytest.raises(TradingViewError, match="görünür ve benzersiz"):
        driver.deep_report_ui_state("worker-2")
    driver._motor.result = {"deep": False}
    with pytest.raises(TradingViewError, match="görünür ve benzersiz"):
        driver.deep_report_ui_state("worker-2")


def test_deep_ui_actions_require_guard_and_pending_refresh(monkeypatch):
    from tv_scan_studio import tradingview
    from tv_scan_studio.tradingview import DeepReportUiState

    driver = GncZihinDriver.__new__(GncZihinDriver)
    driver.target_guard = None
    with pytest.raises(TradingViewError, match="koruması"):
        driver.refresh_deep_report("worker-3")
    with pytest.raises(TradingViewError, match="koruması"):
        driver.download_deep_xlsx("worker-3")

    actions = []
    driver.target_guard = lambda target: actions.append(("guard", target))
    state = DeepReportUiState("Sep 7, 2026 — Sep 18, 2026", {"trades": 28}, False)
    driver.deep_report_ui_state = lambda target: state
    driver._motor = SimpleNamespace(_eval=lambda target, script: actions.append(
        ("eval", target, script)) or True)
    monkeypatch.setattr(tradingview.time, "sleep", lambda _seconds: None)
    with pytest.raises(TradingViewError, match="tazelik kanıtlanamaz"):
        driver.refresh_deep_report("worker-3")
    assert not any(item[0] == "eval" for item in actions)

    actions.clear()
    assert driver.download_deep_xlsx("worker-3") is True
    assert [item[0] for item in actions] == ["guard", "guard", "eval", "guard", "eval"]
    assert "report_menu_not_unique" in actions[2][2]
    assert "xlsx_action_not_unique" in actions[4][2]

    actions.clear()
    driver.deep_report_ui_state = lambda target: DeepReportUiState(state.date_label, state.metrics, True)
    with pytest.raises(TradingViewError, match="bekleyen"):
        driver.download_deep_xlsx("worker-3")
    assert not any(item[0] == "eval" for item in actions)

    phases = iter((True, False, False, False))
    driver.deep_report_ui_state = lambda target: DeepReportUiState(
        state.date_label, state.metrics, next(phases))
    actions.clear()
    assert driver.refresh_deep_report("worker-3") is True
    assert [item[0] for item in actions] == ["guard", "guard", "eval", "guard", "guard", "guard"]
    assert "update_report_not_unique" in actions[2][2]


@pytest.mark.parametrize('receipt', ['matching', 'wrong_date', 'wrong_target', 'unstable'])
def test_auto_deep_report_requires_task_date_receipt(monkeypatch, receipt):
    from datetime import date
    from tv_scan_studio import tradingview
    from tv_scan_studio.tradingview import DeepReportUiState
    driver = GncZihinDriver.__new__(GncZihinDriver)
    driver.target_guard = lambda target: None
    dates = (date(2026, 9, 7), date(2026, 9, 17))
    driver._configured_report_dates = {
        'other' if receipt == 'wrong_target' else 'worker':
        (dates[0], date(2026, 9, 18)) if receipt == 'wrong_date' else dates}
    calls = []
    def state(target):
        calls.append(target)
        return DeepReportUiState('Sep 7, 2026 — Sep 17, 2026',
                                {'trades': 99 if receipt == 'unstable' and len(calls)>10 else 24}, False)
    driver.deep_report_ui_state = state
    monkeypatch.setattr(tradingview.time, 'sleep', lambda seconds: None)
    if receipt == 'matching':
        assert driver.refresh_deep_report('worker') is True
        with pytest.raises(TradingViewError):
            driver.refresh_deep_report('worker')
    else:
        with pytest.raises(TradingViewError):
            driver.refresh_deep_report('worker')


@pytest.mark.parametrize("label,expected", [("Percent", "percent"),
    ("Cash per contract", "cash_per_contract"), ("Per contract", "cash_per_contract"),
    ("Cash per order", "cash_per_order"), ("Per order", "cash_per_order")])
def test_strategy_properties_ui_reader_closes_without_saving(monkeypatch, label, expected):
    from tv_scan_studio import tradingview

    driver = GncZihinDriver.__new__(GncZihinDriver)
    actions = []
    driver.target_guard = lambda target: actions.append(("guard", target))
    values = {"capital": "100,000", "size": "2", "sizeType": "Quantity",
              "commission": "0.01", "commissionType": label, "slippage": "2"}
    responses = iter((True, values, True, True))
    driver._motor = SimpleNamespace(_eval=lambda target, script: actions.append(
        ("eval", target, script)) or next(responses))
    monkeypatch.setattr(tradingview.time, "sleep", lambda _seconds: None)
    state = driver.strategy_properties_ui_state("worker-3")
    assert state.commission_type == expected
    assert (state.initial_capital, state.position_size, state.commission_value,
            state.slippage_ticks) == (100000, 2, 0.01, 2)
    assert [item[0] for item in actions] == ["guard", "eval", "guard", "eval", "guard", "eval", "guard", "eval"]
    assert "return ![...document.querySelectorAll" in actions[-1][2]


@pytest.mark.parametrize('mismatch', [False, True])
def test_worker_applies_properties_and_checks_ui(tmp_path, mismatch):
    from tv_scan_studio.tradingview import StrategyPropertiesUiState
    store = Store(tmp_path / 'properties.db')
    project = store.create_project('Costs', 'strategy("Costs")')
    assumptions = dict(initial_capital=100000, position_size=1, commission_value=.04,
                       commission_type='percent', slippage=10)
    store.enqueue(project, 'costs', dict(study_id='study-1', symbol='OANDA:EURUSD',
        timeframe='15', inputs={'in_0':20}, costs={'assumptions':assumptions},
        timeout=1, poll_interval=0))
    driver = FakeDriver([snapshot() for _ in range(3)])
    applied = []
    driver.configure_strategy_properties = lambda target, study, costs: applied.append(costs)
    driver.strategy_properties_ui_state = lambda target: StrategyPropertiesUiState(
        100000, 1, 'contracts', .04, 'percent', 0 if mismatch else 10)
    ScanWorker(1, 'target-1', store, driver, target_guard=lambda target: None).run_one()
    assert applied == [assumptions]
    if mismatch:
        assert store.counts(project) != {'done':1}
    else:
        assert store.results(project)[0]['evidence']['cost_verification_scope'] == 'strategy_properties_ui_spread_unverified'


def test_worker_applies_and_verifies_cost_inputs(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Costs", 'strategy("Costs")')
    payload = {"study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
               "inputs": {"in_0": 20}, "costs": {"tradingview_inputs": {"in_1": 0.1}},
               "timeout": 1, "poll_interval": 0}
    store.enqueue(project, "cost", payload)
    cost_snapshot = snapshot(inputs={"in_0": 20, "in_1": 0.1})
    driver = FakeDriver([cost_snapshot, cost_snapshot, cost_snapshot])
    ScanWorker(1, "target-1", store, driver).run_one()
    assert driver.configured[0][-1]["in_1"] == 0.1
    assert store.counts(project) == {"done": 1}
    assert store.results(project)[0]["evidence"]["cost_verification_scope"] == "not_verified"


def test_unmapped_strategy_property_cost_is_rejected_before_chart_mutation(tmp_path):
    store = Store(tmp_path / "unsupported-cost.db")
    project = store.create_project("Costs", 'strategy("Costs")')
    store.enqueue(project, "unsupported", {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20},
        "costs": {"tradingview_inputs": {"commission_value": 0.1}},
    })
    driver = FakeDriver([])
    assert ScanWorker(1, "target-1", store, driver).run_one() is True
    assert driver.configured == []
    result = store.results(project)[0]
    assert result["classification"] == "geçersiz"
    assert result["verified"] is False


def test_unmapped_spread_is_rejected_before_chart_mutation(tmp_path):
    store = Store(tmp_path / "spread.db")
    project = store.create_project("Spread", 'strategy("Spread")')
    store.enqueue(project, "unmapped-spread", {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {}, "costs": {"assumptions": {"spread": 1.5}},
    })
    driver = FakeDriver([])
    assert ScanWorker(1, "target-1", store, driver).run_one() is True
    assert driver.configured == []
    result = store.results(project)[0]
    assert result["classification"] == "geçersiz"
    assert result["verified"] is False
    assert result["evidence"]["costs"]["assumptions"]["spread"] == 1.5


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


@pytest.mark.parametrize("changes", [
    {"net_profit": None}, {"profit_factor": float("nan")},
    {"trades": True}, {"win_rate_pct": 101}, {"max_drawdown_pct": -1},
])
def test_incomplete_or_invalid_core_metrics_cannot_be_successful(changes):
    metrics = {"trades": 100, "profit_factor": 1.5, "win_rate_pct": 45,
               "max_drawdown_pct": 4, "net_profit": 1000}
    metrics.update(changes)
    assert classify(metrics, {}) == "geçersiz"


def test_zero_trade_result_is_not_a_successful_preset():
    metrics = {"trades": 0, "profit_factor": 0, "win_rate_pct": 0,
               "max_drawdown_pct": 0, "net_profit": 0}
    assert classify(metrics, {}) == "elenmiş"


def test_worker_invalidates_incomplete_report_instead_of_saving_success(tmp_path):
    store = Store(tmp_path / "incomplete.db")
    project = store.create_project("Incomplete", 'strategy("Incomplete")')
    store.enqueue(project, "missing-net", {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20}, "timeout": 1, "poll_interval": 0,
    })
    incomplete = replace(snapshot(), metrics={"trades": 100, "profit_factor": 1.5,
                                              "win_rate_pct": 45, "max_drawdown_pct": 4})
    assert ScanWorker(1, "target-1", store, FakeDriver([incomplete] * 3), [project]).run_one()
    result = store.results(project)[0]
    assert result["classification"] == "geçersiz"
    assert result["verified"] is False


def test_worker_rejects_trade_total_mismatch_without_ftmo_gate(tmp_path):
    store = Store(tmp_path / "mismatch.db")
    project = store.create_project("Mismatch", 'strategy("Mismatch")')
    store.enqueue(project, "mismatched-net", {
        "study_id": "study-1", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20}, "timeout": 1, "poll_interval": 0,
        "criteria": {},
    })
    trade = {"e": {"tm": 1_750_000_000_000, "tp": "long"},
             "x": {"tm": 1_750_000_060_000}, "tp": {"v": 5}}
    mismatched = replace(snapshot(), trades=(trade,))
    assert ScanWorker(1, "target-1", store, FakeDriver([mismatched] * 3), [project]).run_one()
    result = store.results(project)[0]
    assert result["classification"] == "geçersiz"
    assert result["verified"] is False
    assert result["metrics"]["trade_pnl_reconciled"] is False


def test_classification_requires_all_robustness_gates():
    metrics = {"trades": 100, "profit_factor": 1.5, "win_rate_pct": 45,
               "max_drawdown_pct": 4, "net_profit": 1000}
    validation = {"neighbor_passed": True, "cost_stress_passed": True, "provider_check_passed": True}
    assert classify(metrics, {"min_trades": 60}, validation) == "dayanıklı"
    assert classify(metrics, {"min_trades": 60}, {}) == "hassas"


def test_classification_applies_ftmo_loss_limits_when_metrics_exist():
    metrics = {"trades": 100, "profit_factor": 1.5, "win_rate_pct": 45,
               "max_drawdown_pct": 4, "max_daily_loss_pct": 5.1,
               "max_total_loss_pct": 2, "net_profit": 1000,
               "risk_evidence_scope": "intraday_equity"}
    assert classify(metrics, {"max_daily_loss_pct": 5, "max_total_loss_pct": 10}) == "elenmiş"


def test_closed_trade_proxy_cannot_pass_ftmo_intraday_risk():
    metrics = {"trades": 100, "profit_factor": 1.5, "win_rate_pct": 45,
               "max_drawdown_pct": 4, "max_daily_loss_pct": 2,
               "max_total_loss_pct": 3, "net_profit": 1000,
               "risk_evidence_scope": "closed_trades_only"}
    assert classify(metrics, {"max_daily_loss_pct": 5, "max_total_loss_pct": 10}) == "geçersiz"


def test_classification_rejects_missing_risk_evidence():
    metrics = {"trades": 100, "profit_factor": 1.5, "win_rate_pct": 45,
               "max_drawdown_pct": 4, "net_profit": 1000}
    assert classify(metrics, {"max_daily_loss_pct": 5}) == "geçersiz"
    assert classify(metrics, {"max_total_loss_pct": 10}) == "geçersiz"
    metrics.update(max_daily_loss_pct=2, max_total_loss_pct=3, trade_pnl_reconciled=False)
    assert classify(metrics, {"max_daily_loss_pct": 5}) == "geçersiz"


def test_classification_ignores_unrequested_unavailable_risk_metric():
    metrics = {"trades": 100, "profit_factor": 1.5, "win_rate_pct": 45,
               "max_drawdown_pct": 4, "net_profit": 1000,
               "max_total_loss_pct": None}
    assert classify(metrics, {}) == "hassas"
    assert classify(metrics, {"max_total_loss_pct": 10}) == "geçersiz"


def test_worker_completes_when_unrequested_risk_metric_is_unavailable(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("No risk gate", 'strategy("No risk gate")')
    store.enqueue(project, "trade", {"study_id": "study-1", "symbol": "OANDA:EURUSD",
                                    "timeframe": "15", "inputs": {"in_0": 20},
                                    "timeout": 1, "poll_interval": 0, "criteria": {}})
    trade = {"e": {"tm": 1_750_000_000_000, "tp": "le"},
             "x": {"tm": 1_750_003_600_000}, "tp": {"v": 100}, "v": 100100}
    live_like = StrategySnapshot(
        symbol="OANDA:EURUSD", timeframe="15", status_type=2,
        inputs={"in_0": 20},
        metrics={"trades": 1, "profit_factor": 1.5, "win_rate_pct": 100,
                 "max_drawdown_pct": 1, "net_profit": 100},
        period={}, trades=(trade,),
    )
    worker = ScanWorker(1, "target-1", store,
                        FakeDriver([live_like, live_like, live_like]), [project])
    assert worker.run_one()
    assert store.counts(project) == {"done": 1}
    assert store.results(project)[0]["metrics"]["max_total_loss_pct"] is None


def test_ftmo_drawdown_gate_is_exclusive():
    metrics = {"trades": 60, "profit_factor": 1.4, "win_rate_pct": 40,
               "max_drawdown_pct": 5, "net_profit": 1}
    assert classify(metrics, {"max_drawdown_pct_exclusive": 5}) == "elenmiş"


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
