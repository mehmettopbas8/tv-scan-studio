"""Queue worker orchestration independent from the desktop UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .storage import Store
from .tradingview import TradingViewDriver, VerificationMismatch, wait_for_verified_result


@dataclass(slots=True)
class ScanWorker:
    worker_id: int
    target_id: str
    store: Store
    driver: TradingViewDriver
    project_ids: list[int] | None = None
    study_id_override: str | None = None

    def run_one(self) -> bool:
        task = self.store.claim_next(self.worker_id, self.project_ids)
        if task is None:
            return False
        try:
            payload = task.payload
            required = {"study_id", "symbol", "timeframe", "inputs"}
            missing = required.difference(payload)
            if missing:
                raise ValueError("Eksik görev alanları: " + ", ".join(sorted(missing)))
            study_id = self.study_id_override or payload["study_id"]
            configured_inputs = dict(payload["inputs"])
            configured_inputs.update(payload.get("costs", {}).get("tradingview_inputs", {}))
            self.driver.configure(
                self.target_id, study_id, payload["symbol"],
                payload["timeframe"], configured_inputs,
            )
            expected = dict(payload)
            expected["inputs"] = configured_inputs
            result = wait_for_verified_result(
                self.driver, self.target_id, study_id, expected,
                timeout=float(payload.get("timeout", 75)),
                poll_interval=float(payload.get("poll_interval", 0.7)),
                stable_reads=int(payload.get("stable_reads", 3)),
            )
            classification = classify(
                result.metrics or {}, payload.get("criteria", {}),
                payload.get("validation", {}),
            )
            self.store.complete(
                task.id, self.worker_id, result.metrics or {}, classification, verified=True,
                evidence={
                    "symbol": result.symbol, "timeframe": result.timeframe,
                    "inputs": result.inputs, "period": result.period,
                    "target_id": self.target_id, "study_id": study_id,
                },
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


def classify(
    metrics: dict[str, Any], criteria: dict[str, Any], validation: dict[str, Any] | None = None
) -> str:
    checks = (
        metrics.get("trades", 0) >= criteria.get("min_trades", 0),
        (metrics.get("profit_factor") or 0) >= criteria.get("min_profit_factor", 0),
        metrics.get("win_rate_pct", 0) >= criteria.get("min_win_rate_pct", 0),
        metrics.get("max_drawdown_pct", float("inf")) <= criteria.get("max_drawdown_pct", float("inf")),
        metrics.get("net_profit", 0) >= criteria.get("min_net_profit", float("-inf")),
    )
    if not all(checks):
        return "elenmiş"
    validation = validation or {}
    required = ("neighbor_passed", "cost_stress_passed", "provider_check_passed")
    return "dayanıklı" if all(validation.get(key) is True for key in required) else "hassas"
