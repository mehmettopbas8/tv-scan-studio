from dataclasses import replace

import pytest

from tv_scan_studio import deep_capture
from tv_scan_studio.deep_export import DeepExport, DeepExportError
from tv_scan_studio.tradingview import DeepReportUiState, StrategyPropertiesUiState, StrategySnapshot


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
    assert (driver.refreshed, driver.downloaded) == (1, 1)
    assert guarded == ["worker-2"] * 8


def test_capture_rejects_series_identity_change_during_download(tmp_path, monkeypatch):
    driver, report, expected, guard, guarded = setup_capture(tmp_path, monkeypatch)
    original = driver.snapshot
    identities = iter([{"feed": "before"}, {"feed": "after"}])
    driver.snapshot = lambda target, study: replace(original(target, study), symbol_identity=next(identities))
    with pytest.raises(DeepExportError, match="sembol kimliği"):
        deep_capture.capture_task_deep_export(driver, target_id="worker-2", study_id="study-2",
            expected=expected, pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            changed_input_ids={"in_0"}, download_directory=tmp_path, guard=guard)


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
