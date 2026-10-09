from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
from types import MethodType, SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from tv_scan_studio import deep_capture
from tv_scan_studio.deep_export import DeepExport, DeepExportError
from tv_scan_studio.tradingview import (DeepReportModelState, DeepReportUiState, GncZihinDriver,
                                      StrategyPropertiesUiState, StrategySnapshot, TradingViewError)


def setup_capture(tmp_path, monkeypatch):
    report = DeepExport(
        metrics={"trades": 1, "profit_factor": 1.5, "win_rate_pct": 100,
                 "max_drawdown_pct": 0.03, "net_profit": 20, "net_profit_pct": 0.02},
        properties={"Symbol": "OANDA:XAUUSD", "Timeframe": "1 minute",
                    "Timezone": "America/New_York", "Initial capital": "100000",
                    "Default order size": "2 contracts", "Slippage": "2 ticks",
                    "Commission": "0.01", "Length": "3"},
        trades=({"Trade number": 1, "Type": "Entry long", "Date and time": 46275.09,
                 "Net PnL USD": 20},
                {"Trade number": 1, "Type": "Exit long", "Date and time": 46275.10,
                 "Net PnL USD": 20}),
        backtesting_range="Sep 6, 2026, 20:00 — Sep 20, 2026, 20:00",
        sha256="abc", mtime_ns=1,
    )
    ui = DeepReportUiState(
        "Sep 7, 2026 — Sep 20, 2026",
        {"trades": 1, "profit_factor": 1.5, "win_rate_pct": 100,
         "max_drawdown_pct": 0.03, "net_profit": 20}, False,
    )
    class Driver:
        refreshed = 0
        downloaded = 0
        inputs = {"in_0": 3}
        ui_after = ui
        def snapshot(self, target, study):
            assert (target, study) == ("worker-2", "study-2")
            return StrategySnapshot("OANDA:XAUUSD", "1", 2, self.inputs, {}, {})
        def chart_timezone(self, target): return "America/New_York"
        def strategy_properties_ui_state(self, target):
            return StrategyPropertiesUiState(100000, 2, "contracts", 0.01, "percent", 2)
        def refresh_deep_report(self, target):
            self.refreshed += 1
            return True
        def deep_report_ui_state(self, target):
            return ui if self.downloaded == 0 else self.ui_after
        def download_deep_xlsx(self, target):
            self.downloaded += 1
            (tmp_path / "fresh.xlsx").write_bytes(b"mock")
            return True
    driver = Driver()
    monkeypatch.setattr(deep_capture, "wait_for_unique_fresh_xlsx", lambda *_args, **_kwargs: tmp_path / "fresh.xlsx")
    monkeypatch.setattr(deep_capture, "read_deep_export", lambda *_args, **_kwargs: report)
    expected = {"symbol": "OANDA:XAUUSD", "timeframe": "1", "inputs": {"in_0": 3},
                "date_range": {"from": "2026-09-07", "to": "2026-09-20"},
                "costs": {"assumptions": {"initial_capital": 100000, "position_size": 2,
                                          "slippage": 2, "commission_value": 0.01,
                                          "commission_type": "percent"}}}
    guarded = []
    def guard(target): guarded.append(target)
    return driver, report, expected, guard, guarded


def test_deep_chart_check_distinguishes_minute_from_monthly():
    expected = {"symbol": "OANDA:EURUSD", "timeframe": "1m", "inputs": {}}
    minute = StrategySnapshot("OANDA:EURUSD", "1", 2, {}, {}, {})
    monthly = replace(minute, timeframe="1M")
    deep_capture._assert_chart_task(minute, expected)
    with pytest.raises(DeepExportError, match="zaman|durumu"):
        deep_capture._assert_chart_task(monthly, expected)


def test_deep_chart_accepts_bist_alias_only_with_current_series_identity():
    expected = {"symbol": "BIST:XU030D1!", "timeframe": "15", "inputs": {"in_1": 9}}
    snapshot = StrategySnapshot("BIST_DLY:XU030D1!", "15", 2, {"in_1": 9}, {}, {},
        symbol_identity={"full_name": "BIST_DLY:XU030D1!", "pro_name": "BIST:XU030D1!",
                         "name": "XU030D1!", "exchange": "BIST"})
    deep_capture._assert_chart_task(snapshot, expected)
    for identity in (None, dict(snapshot.symbol_identity, exchange="OANDA"),
                     dict(snapshot.symbol_identity, full_name="BIST:OTHER")):
        with pytest.raises(DeepExportError):
            deep_capture._assert_chart_task(replace(snapshot, symbol_identity=identity), expected)


def test_task_bound_capture_refreshes_then_claims_one_export(tmp_path, monkeypatch):
    driver, report, expected, guard, guarded = setup_capture(tmp_path, monkeypatch)
    capture = deep_capture.capture_task_deep_export(
        driver, target_id="worker-2", study_id="study-2", expected=expected,
        pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
        changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard,
    )
    assert capture.report is report
    assert capture.verified_changed_inputs == ("in_0",)
    assert len(capture.trades) == 1
    assert capture.report_period == {"from_ms": 1788739200000, "to_ms": 1789948799999,
                                     "end_exclusive_ms": 1789948800000, "timezone": "UTC"}
    assert capture.report_currency is None
    assert capture.warning_state == "unknown"
    assert (driver.refreshed, driver.downloaded) == (1, 1)
    assert guarded == ["worker-2"] * 8


@pytest.mark.parametrize('total,open_pnl,valid', [(20,0,True),(21,0,False),(20,None,False)])
def test_capture_reconciles_observed_total_pnl(tmp_path, monkeypatch, total, open_pnl, valid):
    driver, report, expected, guard, _ = setup_capture(tmp_path, monkeypatch)
    report = replace(report, open_pnl=open_pnl)
    state = replace(driver.deep_report_ui_state('worker-2'), total_pnl=total)
    driver.deep_report_ui_state = lambda target: state
    monkeypatch.setattr(deep_capture, 'read_deep_export', lambda *_args, **_kwargs: report)
    def capture():
        return deep_capture.capture_task_deep_export(
            driver, target_id='worker-2', study_id='study-2', expected=expected,
            pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={'in_0'}, download_directory=tmp_path, guard=guard)
    if valid:
        assert capture().report.open_pnl == 0
    else:
        with pytest.raises(DeepExportError, match='toplam'):
            capture()


def test_capture_rejects_series_identity_change_during_download(tmp_path, monkeypatch):
    driver, report, expected, guard, guarded = setup_capture(tmp_path, monkeypatch)
    original = driver.snapshot
    identities = iter([{"feed": "before"}, {"feed": "after"}])
    driver.snapshot = lambda target, study: replace(original(target, study), symbol_identity=next(identities))
    with pytest.raises(DeepExportError, match="sembol kimliği"):
        deep_capture.capture_task_deep_export(driver, target_id="worker-2", study_id="study-2",
            expected=expected, pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard)


def test_capture_preserves_bound_warning_without_claiming_absence(tmp_path, monkeypatch):
    driver, _report, expected, guard, _guarded = setup_capture(tmp_path, monkeypatch)
    original = driver.snapshot
    warning = {"state": "present", "provenance": "strategy_report_dom",
               "text": "This strategy may use look-ahead bias", "reason": "visible_lookahead_warning"}
    driver.snapshot = lambda target, study: replace(original(target, study),
        warning_state="present", warning_evidence=warning)
    capture = deep_capture.capture_task_deep_export(driver, target_id="worker-2", study_id="study-2",
        expected=expected, pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
        changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard)
    assert capture.warning_state == "present"
    assert capture.warning_evidence == warning


def test_task_bound_capture_waits_for_transient_calculation_but_not_wrong_input(tmp_path, monkeypatch):
    driver, _report, expected, guard, _guarded = setup_capture(tmp_path, monkeypatch)
    original = driver.snapshot
    states = iter((1, 2, 1, 2))
    driver.snapshot = lambda target, study: replace(original(target, study), status_type=next(states))
    monkeypatch.setattr(deep_capture.time, "sleep", lambda _seconds: None)
    capture = deep_capture.capture_task_deep_export(
        driver, target_id="worker-2", study_id="study-2", expected=expected,
        pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
        changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard,
    )
    assert capture.verified_changed_inputs == ("in_0",)

    driver, _report, expected, guard, _guarded = setup_capture(tmp_path, monkeypatch)
    driver.inputs = {"in_0": 99}
    original = driver.snapshot
    driver.snapshot = lambda target, study: replace(original(target, study), status_type=1)
    with pytest.raises(DeepExportError, match="eşleşmiyor"):
        deep_capture.capture_task_deep_export(
            driver, target_id="worker-2", study_id="study-2", expected=expected,
            pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard,
        )


def test_task_bound_capture_rejects_missing_refresh_without_download(tmp_path, monkeypatch):
    driver, _report, expected, guard, _guarded = setup_capture(tmp_path, monkeypatch)
    driver.refresh_deep_report = lambda _target: False
    with pytest.raises(DeepExportError, match="yeniden hesaplandığı"):
        deep_capture.capture_task_deep_export(
            driver, target_id="worker-2", study_id="study-2", expected=expected,
            pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard,
        )
    assert driver.downloaded == 0


def test_task_bound_capture_rejects_wrong_commission_type_before_refresh(tmp_path, monkeypatch):
    driver, _report, expected, guard, _guarded = setup_capture(tmp_path, monkeypatch)
    expected["costs"]["assumptions"]["commission_type"] = "cash_per_order"
    with pytest.raises(DeepExportError, match="komisyon türü"):
        deep_capture.capture_task_deep_export(
            driver, target_id="worker-2", study_id="study-2", expected=expected,
            pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard,
        )
    assert (driver.refreshed, driver.downloaded) == (0, 0)


@pytest.mark.parametrize("missing_action", ["refresh_deep_report", "download_deep_xlsx",
                                            "strategy_properties_ui_state"])
def test_task_bound_capture_requires_both_live_actions_before_reading_chart(
        tmp_path, monkeypatch, missing_action):
    driver, _report, expected, guard, guarded = setup_capture(tmp_path, monkeypatch)
    setattr(driver, missing_action, None)
    with pytest.raises(DeepExportError, match=missing_action):
        deep_capture.capture_task_deep_export(
            driver, target_id="worker-2", study_id="study-2", expected=expected,
            pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard,
        )
    assert guarded == []
    assert (driver.refreshed, driver.downloaded) == (0, 0)


@pytest.mark.parametrize("observed,expected_value", [(True, 1), (1, True), (None, None)])
def test_task_bound_capture_rejects_ambiguous_or_missing_input(
        tmp_path, monkeypatch, observed, expected_value):
    driver, _report, expected, guard, _guarded = setup_capture(tmp_path, monkeypatch)
    expected["inputs"] = {"in_0": expected_value}
    driver.inputs = {} if observed is None else {"in_0": observed}
    with pytest.raises(DeepExportError, match="eşleşmiyor"):
        deep_capture.capture_task_deep_export(
            driver, target_id="worker-2", study_id="study-2", expected=expected,
            pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard,
        )
    assert (driver.refreshed, driver.downloaded) == (0, 0)


def test_task_bound_capture_rejects_ui_change_or_stale_pine_input(tmp_path, monkeypatch):
    driver, report, expected, guard, _guarded = setup_capture(tmp_path, monkeypatch)
    driver.ui_after = replace(driver.ui_after, date_label="Sep 8, 2026 — Sep 20, 2026")
    with pytest.raises(DeepExportError, match="indirme sırasında değişti"):
        deep_capture.capture_task_deep_export(
            driver, target_id="worker-2", study_id="study-2", expected=expected,
            pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard,
        )
    (tmp_path / "fresh.xlsx").unlink()
    driver.downloaded = 0
    driver.ui_after = driver.deep_report_ui_state("worker-2")
    expected["inputs"]["in_0"] = 4
    driver.inputs = {"in_0": 4}
    with pytest.raises(DeepExportError, match="değeri XLSX"):
        deep_capture.capture_task_deep_export(
            driver, target_id="worker-2", study_id="study-2", expected=expected,
            pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard,
        )


def test_layout_change_before_post_download_ui_read_stops_verification(tmp_path, monkeypatch):
    driver, _report, expected, _guard, _guarded = setup_capture(tmp_path, monkeypatch)
    guarded = []

    def guard(target):
        guarded.append(target)
        if len(guarded) == 7:
            raise ValueError("Worker layoutu değişti")

    monkeypatch.setattr(deep_capture, "verify_deep_export",
                        lambda *_args, **_kwargs: pytest.fail("Layout değişiminden sonra rapor doğrulanmamalı"))
    with pytest.raises(ValueError, match="layoutu değişti"):
        deep_capture.capture_task_deep_export(
            driver, target_id="worker-2", study_id="study-2", expected=expected,
            pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard,
        )
    assert guarded == ["worker-2"] * 7
    assert driver.downloaded == 1


def test_chart_timezone_change_during_download_rejects_report(tmp_path, monkeypatch):
    driver, _report, expected, guard, _guarded = setup_capture(tmp_path, monkeypatch)
    zones = iter(("America/New_York", "Etc/UTC"))
    driver.chart_timezone = lambda _target: next(zones)
    monkeypatch.setattr(deep_capture, "verify_deep_export",
                        lambda *_args, **_kwargs: pytest.fail("Saat dilimi değişmiş rapor doğrulanmamalı"))
    with pytest.raises(DeepExportError, match="saat dilimi indirme sırasında değişti"):
        deep_capture.capture_task_deep_export(
            driver, target_id="worker-2", study_id="study-2", expected=expected,
            pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard,
        )
    assert driver.downloaded == 1


def test_second_worker_cannot_read_or_download_while_first_owns_xlsx_lock(
        tmp_path, monkeypatch):
    driver, _report, expected, guard, guarded = setup_capture(tmp_path, monkeypatch)
    assert deep_capture._DOWNLOAD_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(DeepExportError, match="Başka workerın XLSX indirmesi"):
            deep_capture.capture_task_deep_export(
                driver, target_id="worker-2", study_id="study-2", expected=expected,
                pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
                changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard,
                timeout=0.01,
            )
        assert guarded == []
        assert (driver.refreshed, driver.downloaded) == (0, 0)
    finally:
        deep_capture._DOWNLOAD_LOCK.release()


@pytest.mark.parametrize("chart_currency", ["USD", None])
def test_capture_persists_observed_performance_header_currency(tmp_path, monkeypatch, chart_currency):
    driver, report, expected, guard, _ = setup_capture(tmp_path, monkeypatch)
    report = replace(report, performance_headers=("", "All USD", "All %", "Long USD", "Long %", "Short USD", "Short %"),
                     performance_headers_provenance="performance_sheet_row1")
    monkeypatch.setattr(deep_capture, "read_deep_export", lambda *_args, **_kwargs: report)
    original = driver.snapshot
    driver.snapshot = lambda target, study: replace(original(target, study), report_currency=chart_currency)
    capture = deep_capture.capture_task_deep_export(driver, target_id="worker-2", study_id="study-2",
        expected=expected, pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
        changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard)
    assert capture.report_currency == "USD"
    assert capture.report.performance_headers_provenance == "performance_sheet_row1"


def test_capture_rejects_proven_header_currency_different_from_live_report(tmp_path, monkeypatch):
    driver, report, expected, guard, _ = setup_capture(tmp_path, monkeypatch)
    report = replace(report, performance_headers=("", "All USD", "All %", "Long USD", "Long %", "Short USD", "Short %"),
                     performance_headers_provenance="performance_sheet_row1")
    monkeypatch.setattr(deep_capture, "read_deep_export", lambda *_args, **_kwargs: report)
    original = driver.snapshot
    driver.snapshot = lambda target, study: replace(original(target, study), report_currency="TRY")
    with pytest.raises(DeepExportError, match="para birimi"):
        deep_capture.capture_task_deep_export(driver, target_id="worker-2", study_id="study-2",
            expected=expected, pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard)
    assert deep_capture._DOWNLOAD_LOCK.acquire(blocking=False)
    deep_capture._DOWNLOAD_LOCK.release()


def test_capture_does_not_substitute_chart_currency_for_unknown_export_units(tmp_path, monkeypatch):
    driver, report, expected, guard, _ = setup_capture(tmp_path, monkeypatch)
    report.properties["Base currency"] = "USD"  # May be a Pine title, not section proof.
    original = driver.snapshot
    driver.snapshot = lambda target, study: replace(original(target, study), report_currency="USD")
    capture = deep_capture.capture_task_deep_export(driver, target_id="worker-2", study_id="study-2",
        expected=expected, pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
        changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard)
    assert capture.report_currency is None


def setup_native_model_capture(tmp_path, monkeypatch):
    """Use the production reader over native-shaped motor receipts, not a reader stub."""
    driver, report, expected, guard, guarded = setup_capture(tmp_path, monkeypatch)
    zone = ZoneInfo('America/New_York')

    def point(text, kind, signal):
        stamp = datetime.fromisoformat(text)
        return ({'time': round(stamp.replace(tzinfo=zone).timestamp() * 1000),
                 'type': kind, 'id': signal},
                (stamp - datetime(1899, 12, 30)).total_seconds() / 86400)

    first, _ = point('2026-09-07T02:30', 'le', '')
    last, _ = point('2026-09-18T15:45', 'lx', '')
    entry, entry_serial = point('2026-09-08T03:45', 'le', 'Long')
    exit_, exit_serial = point('2026-09-08T04:00', 'lx', 'Exit')
    properties = dict(report.properties)
    del properties['Timezone']  # Real export need not provide this property.
    report = replace(report, properties=properties,
        trades=({'Trade number': 1, 'Type': 'Entry long', 'Date and time': entry_serial,
                 'Signal': 'Long', 'Net PnL USD': 20},
                {'Trade number': 1, 'Type': 'Exit long', 'Date and time': exit_serial,
                 'Signal': 'Exit', 'Net PnL USD': 20}),
        backtesting_range='Sep 7, 2026, 02:30 — Sep 18, 2026, 15:45',
        performance_headers=('', 'All USD', 'All %', 'Long USD', 'Long %', 'Short USD', 'Short %'),
        performance_headers_provenance='performance_sheet_row1',
        trade_pnl_header='Net PnL USD', open_trade_count=0, open_pnl=0)
    model = DeepReportModelState(1788739200000, 1789948800000,
        dict(expected['date_range']), 'America/New_York', 'study-2', {'in_0': 3},
        'OANDA:XAUUSD', '1', 2, False, False,
        {'dateRange': {'backtest': {'from': first['time'], 'to': last['time']}}},
        ({'tradeNumber': 1, 'entry': entry, 'exit': exit_, 'profit': {'value': 20}},),
        {'all': {'netProfit': 20, 'totalTrades': 1, 'totalOpenTrades': 0}, 'openPL': 0}, 'USD')
    payload = asdict(model)
    payload.pop('provenance')
    payload.update(bound=True, trades=list(payload['trades']))
    receipts = []

    def evaluate(target, script):
        assert target == 'worker-2'
        assert 'manager._fromDate' in script and 'report.trades' in script
        receipts.append(target)
        return deepcopy(payload)

    driver.target_guard = guard
    driver._motor = SimpleNamespace(_eval=evaluate)
    driver.deep_report_model_state = MethodType(GncZihinDriver.deep_report_model_state, driver)
    monkeypatch.setattr(deep_capture, 'read_deep_export', lambda *_args, **_kwargs: report)
    return driver, report, model, expected, guard, guarded, payload, receipts


def capture_native(driver, expected, tmp_path, guard):
    return deep_capture.capture_task_deep_export(driver, target_id='worker-2', study_id='study-2',
        expected=expected, pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
        changed_input_ids={'in_0'}, download_directory=tmp_path, guard=guard)


def assert_download_lock_retired():
    assert deep_capture._DOWNLOAD_LOCK.acquire(blocking=False)
    deep_capture._DOWNLOAD_LOCK.release()


def test_production_model_bound_capture_preserves_independent_evidence(tmp_path, monkeypatch):
    driver, report, model, expected, guard, guarded, payload, receipts = setup_native_model_capture(tmp_path, monkeypatch)
    untouched = deepcopy(report)
    capture = capture_native(driver, expected, tmp_path, guard)
    assert capture.report is report and report == untouched
    assert 'Timezone' not in report.properties
    assert capture.verified_changed_inputs == ('in_0',)
    assert len(capture.trades) == 1 and capture.trades[0]['tp']['v'] == 20
    assert capture.report_currency == 'USD'
    assert capture.report_period == {
        'from_ms': model.settings['dateRange']['backtest']['from'],
        'to_ms': model.settings['dateRange']['backtest']['to'], 'timezone': 'UTC',
        'endpoint_semantics': 'observed_data_timestamps',
        'provenance': 'deep_model_and_export_rows', 'export_timezone': 'America/New_York'}
    assert 'end_exclusive_ms' not in capture.report_period
    assert capture.model_evidence == {
        'provenance': 'visible_deep_manager',
        'model_sha256': hashlib.sha256(json.dumps(asdict(model), sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest(),
        'request_from_ms': model.request_from_ms,
        'request_end_exclusive_ms': model.request_end_exclusive_ms,
        'selected_dates': expected['date_range'], 'export_sha256': report.sha256,
        'export_timezone': 'America/New_York'}
    payload['selected_dates']['from'] = '2026-09-08'
    assert capture.model_evidence['selected_dates']['from'] == '2026-09-07'
    assert receipts == ['worker-2'] * 4  # Two guarded native reads per capture boundary.
    assert guarded == ['worker-2'] * 16
    assert (driver.refreshed, driver.downloaded) == (1, 1)
    assert_download_lock_retired()


@pytest.mark.parametrize('field,value', [
    ('inputs', {'in_0': 4}), ('selected_dates', {'from': '2026-09-08', 'to': '2026-09-20'}),
    ('performance', {'all': {'netProfit': 21, 'totalTrades': 1, 'totalOpenTrades': 0}, 'openPL': 0})])
def test_native_model_change_between_download_boundaries_rejects_capture(tmp_path, monkeypatch, field, value):
    driver, report, model, expected, guard, _, payload, receipts = setup_native_model_capture(tmp_path, monkeypatch)
    # Each reader's own double-read is stable; only the download separates the models.
    second = dict(payload, **{field: value})
    if field == 'selected_dates':
        second['request_from_ms'] += 86400000
        second['settings'] = {'dateRange': {'backtest': {
            'from': model.trades[0]['entry']['time'], 'to': model.settings['dateRange']['backtest']['to']}}}
    first_eval = driver._motor._eval
    driver._motor._eval = lambda target, script: deepcopy(second) if driver.downloaded else first_eval(target, script)
    monkeypatch.setattr(deep_capture, 'verify_deep_export',
        lambda *_args, **_kwargs: pytest.fail('Changed native source must not reach export verification'))
    with pytest.raises(DeepExportError, match='kaynağı indirme sırasında değişti'):
        capture_native(driver, expected, tmp_path, guard)
    assert driver.downloaded == 1
    assert_download_lock_retired()


@pytest.mark.parametrize('boundary', ['before', 'after'])
@pytest.mark.parametrize('fault', ['motor_error', 'missing_bound', 'missing_settings', 'missing_inputs', 'no_receipt'])
def test_production_model_reader_failure_is_fail_closed(tmp_path, monkeypatch, boundary, fault):
    driver, report, model, expected, guard, _, payload, receipts = setup_native_model_capture(tmp_path, monkeypatch)
    original_eval = driver._motor._eval

    def evaluate(target, script):
        if (driver.downloaded == 0) == (boundary == 'before'):
            if fault == 'motor_error':
                raise TradingViewError('Native model transport unavailable')
            if fault == 'no_receipt':
                return None
            broken = deepcopy(payload)
            broken.pop({'missing_bound': 'bound', 'missing_settings': 'settings',
                        'missing_inputs': 'inputs'}[fault])
            return broken
        return original_eval(target, script)

    driver._motor._eval = evaluate
    monkeypatch.setattr(deep_capture, 'verify_deep_export',
        lambda *_args, **_kwargs: pytest.fail('Failed model read must never fall back to legacy proof'))
    with pytest.raises(TradingViewError):
        capture_native(driver, expected, tmp_path, guard)
    assert driver.downloaded == (0 if boundary == 'before' else 1)
    assert_download_lock_retired()


@pytest.mark.parametrize('boundary', ['before', 'after'])
def test_callable_model_reader_returning_none_never_uses_legacy_fallback(tmp_path, monkeypatch, boundary):
    driver, report, model, expected, guard, _, _, _ = setup_native_model_capture(tmp_path, monkeypatch)
    # Give legacy verification a fully valid export so rejection cannot depend on
    # native-only properties being absent.
    _, legacy_report, _, _, _ = setup_capture(tmp_path, monkeypatch)
    driver.deep_report_model_state = lambda target, study: (
        None if (driver.downloaded == 0) == (boundary == 'before') else model)
    monkeypatch.setattr(deep_capture, 'read_deep_export', lambda *_args, **_kwargs: legacy_report)
    monkeypatch.setattr(deep_capture, 'verify_deep_export',
        lambda *_args, **_kwargs: pytest.fail('None model must not reach legacy verification'))
    with pytest.raises(DeepExportError, match='kaynağı okunamadı'):
        capture_native(driver, expected, tmp_path, guard)
    assert driver.downloaded == (0 if boundary == 'before' else 1)
    assert_download_lock_retired()
