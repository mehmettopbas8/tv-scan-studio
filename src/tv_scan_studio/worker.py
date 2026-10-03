"""Queue worker orchestration independent from the desktop UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re
from typing import Any, Callable

from .storage import Store
from .tradingview import TradingViewDriver, VerificationMismatch, wait_for_verified_result
from .analytics import analyze_trades
from .deep_capture import capture_task_deep_export, verify_strategy_properties_ui
from .cost_application import validate_spread_mapping


@dataclass(slots=True)
class ScanWorker:
    worker_id: int
    target_id: str
    store: Store
    driver: TradingViewDriver
    project_ids: list[int] | None = None
    study_id_override: str | None = None
    target_guard: Callable[[str], None] | None = None
    download_directory: Path | None = None

    def run_one(self) -> bool:
        # A moved/closed layout must not consume a queued task or retry budget.
        if self.target_guard is not None:
            self.target_guard(self.target_id)
        task = self.store.claim_next(self.worker_id, self.project_ids)
        if task is None:
            return False
        try:
            payload = task.payload
            try:
                validate_spread_mapping(payload.get("costs") or {})
            except ValueError as exc:
                self.store.invalidate(task.id, self.worker_id, str(exc), {},
                                      {"target_id": self.target_id, "costs": payload.get("costs")})
                return True
            required = {"study_id", "symbol", "timeframe", "inputs"}
            missing = required.difference(payload)
            if missing:
                raise ValueError("Eksik görev alanları: " + ", ".join(sorted(missing)))
            requested_dates = payload.get("date_range") or {}
            configure_dates = getattr(self.driver, "configure_date_range", None)
            deep_actions_ready = all(callable(getattr(self.driver, name, None)) for name in (
                "refresh_deep_report", "download_deep_xlsx", "deep_report_ui_state",
                "chart_timezone", "strategy_properties_ui_state",
            ))
            if requested_dates and (
                not callable(configure_dates) or not getattr(self.driver, "date_range_ready", False)
                or not deep_actions_ready or not getattr(self.driver, "deep_capture_ready", False)
                or self.target_guard is None or self.download_directory is None
                or not self.download_directory.is_dir()
            ):
                self.store.invalidate(
                    task.id, self.worker_id,
                    "Tarihli Deep rapor yakalama eylemleri hazır değil; bu görev doğrulanmış tarama sayılamaz.",
                    {}, {"target_id": self.target_id, "requested_date_range": requested_dates},
                )
                return True
            study_id = self.study_id_override or payload["study_id"]
            configured_inputs = dict(payload["inputs"])
            cost_inputs = payload.get("costs", {}).get("tradingview_inputs", {})
            unsupported = [key for key in cost_inputs if not re.fullmatch(r"in_\d+", str(key))]
            if unsupported:
                self.store.invalidate(
                    task.id, self.worker_id,
                    "Maliyet eşlemesi Pine input ID'si değil; TradingView Strategy Properties uygulanmış sayılamaz.",
                    {}, {"target_id": self.target_id, "unsupported_cost_input_ids": unsupported},
                )
                return True
            configured_inputs.update(cost_inputs)
            assumptions = payload.get("costs", {}).get("assumptions", {})
            configure_properties = getattr(self.driver, "configure_strategy_properties", None)
            apply_properties = bool(assumptions) and callable(configure_properties)
            if apply_properties and self.target_guard is None:
                self.store.invalidate(task.id, self.worker_id,
                    "Maliyet ayarı için benzersiz worker koruması gerekli.", {},
                    {"target_id": self.target_id})
                return True
            previous_inputs = {}
            if requested_dates:
                if self.target_guard is not None:
                    self.target_guard(self.target_id)
                previous_inputs = self.driver.snapshot(self.target_id, study_id).inputs
            if self.target_guard is not None:
                self.target_guard(self.target_id)
            self.driver.configure(
                self.target_id, study_id, payload["symbol"],
                payload["timeframe"], configured_inputs,
            )
            if apply_properties:
                configure_properties(self.target_id, study_id, assumptions)
            if requested_dates:
                if self.target_guard is not None:
                    self.target_guard(self.target_id)
                configure_dates(self.target_id, study_id, requested_dates)
            expected = dict(payload)
            expected["inputs"] = configured_inputs
            if requested_dates:
                project = self.store.project(task.project_id)
                if project is None:
                    raise ValueError("Tarihli görevin Pine projesi bulunamadı.")
                changed = {key for key, value in configured_inputs.items()
                           if key not in previous_inputs or previous_inputs[key] != value
                           or (isinstance(previous_inputs[key], bool) != isinstance(value, bool))}
                capture = capture_task_deep_export(
                    self.driver, target_id=self.target_id, study_id=study_id,
                    expected=expected, pine_source=project["pine_source"],
                    changed_input_ids=changed, download_directory=self.download_directory,
                    guard=self.target_guard, timeout=float(payload.get("timeout", 75)),
                )
                metrics = dict(capture.report.metrics)
                trades = capture.trades
                evidence = {
                    "symbol": payload["symbol"], "timeframe": payload["timeframe"],
                    "inputs": configured_inputs, "period": requested_dates,
                    "target_id": self.target_id, "study_id": study_id,
                    "report_source": "deep_xlsx", "deep_sha256": capture.report.sha256,
                    "chart_timezone": capture.chart_timezone,
                    "verified_changed_inputs": capture.verified_changed_inputs,
                    "cost_verification_scope": "strategy_properties_ui_and_xlsx_spread_unverified",
                }
            else:
                result = wait_for_verified_result(
                    self.driver, self.target_id, study_id, expected,
                    timeout=float(payload.get("timeout", 75)),
                    poll_interval=float(payload.get("poll_interval", 0.7)),
                    stable_reads=int(payload.get("stable_reads", 3)),
                )
                metrics = dict(result.metrics or {})
                trades = result.trades
                evidence = {
                    "symbol": result.symbol, "timeframe": result.timeframe,
                    "inputs": result.inputs, "period": result.period,
                    "target_id": self.target_id, "study_id": study_id,
                    "cost_verification_scope": "not_verified",
                }
                if apply_properties:
                    self.target_guard(self.target_id)
                    properties = self.driver.strategy_properties_ui_state(self.target_id)
                    verify_strategy_properties_ui(properties, assumptions)
                    evidence["cost_verification_scope"] = "strategy_properties_ui_spread_unverified"
            assumptions = payload.get("costs", {}).get("assumptions", {})
            analysis = analyze_trades(
                trades, float(assumptions.get("initial_capital", 0)),
                str(assumptions.get("analysis_timezone", "UTC")),
            )
            metrics.update(analysis)
            if analysis and isinstance(metrics.get("net_profit"), (int, float)):
                delta = abs(float(metrics["net_profit"]) - float(analysis["trade_analysis_net_profit"]))
                metrics["trade_report_net_delta"] = delta
                metrics["trade_pnl_reconciled"] = delta <= max(1.0, abs(float(metrics["net_profit"])) * 0.001)
            core_error = _core_metrics_error(metrics)
            if core_error:
                self.store.invalidate(task.id, self.worker_id, core_error, metrics, evidence)
                return True
            if metrics.get("trade_pnl_reconciled") is False:
                self.store.invalidate(
                    task.id, self.worker_id,
                    "İşlem listesinin toplam kârı Strategy Tester net kârıyla eşleşmiyor.",
                    metrics, evidence,
                )
                return True
            classification = classify(
                metrics, payload.get("criteria", {}),
                payload.get("validation", {}),
            )
            if classification == "geçersiz":
                self.store.invalidate(
                    task.id, self.worker_id,
                    "FTMO risk sınırı için açık pozisyonları da kapsayan gün içi equity kanıtı eksik.",
                    metrics, evidence,
                )
                return True
            self.store.complete(
                task.id, self.worker_id, metrics, classification, verified=True,
                evidence=evidence,
            )
        except VerificationMismatch as exc:
            if task.attempts >= 3:
                snapshot = exc.snapshot
                self.store.invalidate(
                    task.id, self.worker_id, str(exc),
                    (snapshot.metrics or {}) if snapshot else {},
                    {"symbol": snapshot.symbol, "timeframe": snapshot.timeframe,
                     "inputs": snapshot.inputs, "period": snapshot.period,
                     "target_id": self.target_id,
                     "study_id": self.study_id_override or task.payload.get("study_id")}
                    if snapshot else {"target_id": self.target_id},
                )
                return True
            self.store.fail(task.id, self.worker_id, str(exc))
        except Exception as exc:
            screenshot_path = None
            screenshot = getattr(self.driver, "screenshot", None)
            if callable(screenshot):
                try:
                    destination = self.store.path.parent / "screenshots" / f"task-{task.id}-attempt-{task.attempts}.png"
                    screenshot_path = screenshot(self.target_id, destination)
                except Exception as capture_exc:
                    self.store.log_event(
                        "warning", f"Ekran görüntüsü alınamadı: {capture_exc}",
                        project_id=task.project_id, task_id=task.id, worker_id=self.worker_id,
                    )
            self.store.fail(task.id, self.worker_id, str(exc), screenshot_path=screenshot_path)
        return True


def _core_metrics_error(metrics: dict[str, Any]) -> str | None:
    """Reject incomplete or non-finite Strategy Tester summaries before ranking."""
    required = ("trades", "profit_factor", "win_rate_pct", "max_drawdown_pct", "net_profit")
    for name in required:
        value = metrics.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return f"Strategy Tester temel metriği eksik veya geçersiz: {name}."
    trades = metrics["trades"]
    if trades < 0 or int(trades) != trades:
        return "Strategy Tester işlem sayısı geçersiz."
    if (metrics["profit_factor"] < 0 or not 0 <= metrics["win_rate_pct"] <= 100
            or metrics["max_drawdown_pct"] < 0):
        return "Strategy Tester temel metriği beklenen aralık dışında."
    return None


def classify(
    metrics: dict[str, Any], criteria: dict[str, Any], validation: dict[str, Any] | None = None
) -> str:
    if _core_metrics_error(metrics):
        return "geçersiz"
    if metrics.get("trade_pnl_reconciled") is False:
        return "geçersiz"
    if metrics["trades"] == 0:
        return "elenmiş"
    required_risk = {name for name in ("max_daily_loss_pct", "max_total_loss_pct") if name in criteria}
    if required_risk and metrics.get("risk_evidence_scope") != "intraday_equity":
        return "geçersiz"
    if any(metrics.get(name) is None for name in required_risk):
        return "geçersiz"
    checks = (
        metrics.get("trades", 0) >= criteria.get("min_trades", 0),
        (metrics.get("profit_factor") or 0) >= criteria.get("min_profit_factor", 0),
        metrics.get("win_rate_pct", 0) >= criteria.get("min_win_rate_pct", 0),
        metrics.get("max_drawdown_pct", float("inf")) < criteria.get("max_drawdown_pct_exclusive", float("inf")),
        metrics.get("max_drawdown_pct", float("inf")) <= criteria.get("max_drawdown_pct", float("inf")),
        metrics.get("net_profit", 0) >= criteria.get("min_net_profit", float("-inf")),
        "max_daily_loss_pct" not in criteria
        or metrics["max_daily_loss_pct"] <= criteria["max_daily_loss_pct"],
        "max_total_loss_pct" not in criteria
        or metrics["max_total_loss_pct"] <= criteria["max_total_loss_pct"],
    )
    if not all(checks):
        return "elenmiş"
    validation = validation or {}
    required = ("neighbor_passed", "cost_stress_passed", "provider_check_passed")
    return "dayanıklı" if all(validation.get(key) is True for key in required) else "hassas"
