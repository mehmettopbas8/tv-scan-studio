"""Task-bound Deep report capture; live UI actions remain fail-closed."""

from __future__ import annotations

import threading
import time
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from .deep_export import (DeepExport, DeepExportError, read_deep_export,
                          verify_deep_export, verify_deep_input_values,
                          wait_for_unique_fresh_xlsx, xlsx_download_baseline)
from .tradingview import (StrategyPropertiesUiState, StrategySnapshot,
                          chart_resolution, symbol_matches)


_DOWNLOAD_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class DeepCapture:
    report: DeepExport
    trades: tuple[dict[str, Any], ...]
    verified_changed_inputs: tuple[str, ...]
    target_id: str
    study_id: str
    chart_timezone: str


def _assert_chart_task(snapshot: StrategySnapshot, expected: dict[str, Any]) -> None:
    def input_matches(key: str, value: Any) -> bool:
        if key not in snapshot.inputs:
            return False
        observed = snapshot.inputs[key]
        # Python considers True == 1; Pine bool and numeric inputs are distinct.
        if isinstance(value, bool) or isinstance(observed, bool):
            return type(observed) is type(value) and observed == value
        return observed == value

    if (snapshot.status_type != 2 or not symbol_matches(expected["symbol"], snapshot.symbol)
            or snapshot.timeframe != chart_resolution(expected["timeframe"])
            or any(not input_matches(key, value)
                   for key, value in expected.get("inputs", {}).items())):
        raise DeepExportError("Worker chart/strateji durumu Deep görev değerleriyle eşleşmiyor.")


def _wait_chart_task(driver: Any, target_id: str, study_id: str,
                     expected: dict[str, Any], guard: Callable[[str], None],
                     *, timeout: float = 10) -> None:
    """Allow brief TradingView calculation status changes, never a wrong identity."""
    deadline = time.monotonic() + timeout
    while True:
        guard(target_id)
        snapshot = driver.snapshot(target_id, study_id)
        # Wrong symbol, timeframe or input is never a transient calculation state.
        _assert_chart_task(replace(snapshot, status_type=2), expected)
        if snapshot.status_type == 2:
            return
        if time.monotonic() >= deadline:
            _assert_chart_task(snapshot, expected)
        time.sleep(0.25)


def verify_strategy_properties_ui(state: StrategyPropertiesUiState, assumptions: dict[str, Any]) -> None:
    required = ("initial_capital", "position_size", "slippage", "commission_value", "commission_type")
    if not isinstance(state, StrategyPropertiesUiState) or not isinstance(assumptions, dict) \
            or any(key not in assumptions for key in required):
        raise DeepExportError("TradingView maliyet türü veya UI kanıtı eksik.")
    if assumptions["commission_type"] not in {"percent", "cash_per_contract", "cash_per_order"}:
        raise DeepExportError("TradingView komisyon türü beklentisi geçersiz.")
    for name, actual in (("initial_capital", state.initial_capital),
                         ("position_size", state.position_size),
                         ("commission_value", state.commission_value),
                         ("slippage", state.slippage_ticks)):
        expected = assumptions[name]
        if isinstance(expected, bool) or not isinstance(expected, (int, float)) \
                or not math.isfinite(expected) or not math.isclose(float(actual), float(expected),
                                                                   rel_tol=0, abs_tol=0.005 if name == "initial_capital" else 1e-8):
            raise DeepExportError(f"TradingView maliyet UI değeri görevle eşleşmiyor: {name}")
    if state.order_size_type != "contracts" or state.commission_type != assumptions["commission_type"]:
        raise DeepExportError("TradingView emir veya komisyon türü görevle eşleşmiyor.")


def capture_task_deep_export(driver: Any, *, target_id: str, study_id: str,
                             expected: dict[str, Any], pine_source: str,
                             changed_input_ids: set[str], download_directory: str | Path,
                             guard: Callable[[str], None], timeout: float = 75) -> DeepCapture:
    """Refresh, download and verify one report without mixing worker downloads.

    The driver must implement refresh_deep_report and download_deep_xlsx as
    guarded UI actions. Until those actions pass a live 9222 test, workers must
    keep date_range_ready=False and must not call this as verified execution.
    """
    if not expected.get("date_range") or timeout <= 0:
        raise DeepExportError("Deep görev tarihi veya zaman aşımı eksik.")
    for action in ("refresh_deep_report", "download_deep_xlsx", "strategy_properties_ui_state"):
        if not callable(getattr(driver, action, None)):
            raise DeepExportError(f"Deep rapor sürücü eylemi hazır değil: {action}.")
    if not _DOWNLOAD_LOCK.acquire(timeout=timeout):
        raise DeepExportError("Başka workerın XLSX indirmesi sürüyor.")
    try:
        _wait_chart_task(driver, target_id, study_id, expected, guard)
        zone = driver.chart_timezone(target_id)
        guard(target_id)
        cost_before = driver.strategy_properties_ui_state(target_id)
        verify_strategy_properties_ui(cost_before, expected.get("costs", {}).get("assumptions", {}))
        guard(target_id)
        if driver.refresh_deep_report(target_id) is not True:
            raise DeepExportError("Deep raporun yeniden hesaplandığı kanıtlanmadı.")
        guard(target_id)
        ui_before = driver.deep_report_ui_state(target_id)
        if ui_before.update_pending:
            raise DeepExportError("Deep rapor güncellemesi hâlâ bekliyor.")
        baseline = xlsx_download_baseline(download_directory)
        started_ns = time.time_ns()
        guard(target_id)
        if driver.download_deep_xlsx(target_id) is not True:
            raise DeepExportError("Deep XLSX indirme eylemi doğrulanmadı.")
        path = wait_for_unique_fresh_xlsx(
            download_directory, baseline=baseline, started_ns=started_ns, timeout=timeout,
        )
        report = read_deep_export(path, downloaded_after_ns=started_ns)
        _wait_chart_task(driver, target_id, study_id, expected, guard)
        if driver.chart_timezone(target_id) != zone:
            raise DeepExportError("Worker chart saat dilimi indirme sırasında değişti.")
        guard(target_id)
        ui_after = driver.deep_report_ui_state(target_id)
        if ui_before != ui_after:
            raise DeepExportError("Deep rapor indirme sırasında değişti.")
        guard(target_id)
        cost_after = driver.strategy_properties_ui_state(target_id)
        if cost_before != cost_after:
            raise DeepExportError("TradingView Strategy Properties indirme sırasında değişti.")
        trades = verify_deep_export(
            report, symbol=expected["symbol"], timeframe=expected["timeframe"],
            date_range=expected["date_range"], chart_timezone=zone,
            cost_assumptions=expected.get("costs", {}).get("assumptions", {}),
            ui_metrics=ui_after.metrics, ui_date_label=ui_after.date_label,
            ui_update_pending=ui_after.update_pending,
        )
        verified = verify_deep_input_values(
            report, pine_source=pine_source, expected_inputs=expected.get("inputs", {}),
            changed_input_ids=changed_input_ids,
        )
        return DeepCapture(report, trades, verified, target_id, study_id, zone)
    finally:
        _DOWNLOAD_LOCK.release()
