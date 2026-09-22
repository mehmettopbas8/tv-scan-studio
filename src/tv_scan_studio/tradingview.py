"""TradingView CDP adapter built on the existing gnc-zihin motor."""

from __future__ import annotations

import importlib.util
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class TradingViewError(RuntimeError):
    pass


class VerificationMismatch(TradingViewError):
    def __init__(self, message: str, snapshot: "StrategySnapshot | None"):
        super().__init__(message)
        self.snapshot = snapshot


@dataclass(frozen=True, slots=True)
class StrategySnapshot:
    symbol: str
    timeframe: str
    status_type: int | None
    inputs: dict[str, Any]
    metrics: dict[str, Any] | None
    period: dict[str, Any] | None


class TradingViewDriver(Protocol):
    def targets(self) -> list[str]: ...
    def snapshot(self, target_id: str, study_id: str) -> StrategySnapshot: ...
    def configure(self, target_id: str, study_id: str, symbol: str, timeframe: str, inputs: dict[str, Any]) -> None: ...


class GncZihinDriver:
    """Thin, target-explicit wrapper; importing it never starts TradingView."""

    def __init__(self, motor_path: str | Path | None = None):
        if motor_path is None or not str(motor_path).strip():
            from . import motor_bridge
            self._motor = motor_bridge
            return
        path = Path(motor_path)
        spec = importlib.util.spec_from_file_location("tv_scan_studio_ciz_paralel", path)
        if spec is None or spec.loader is None:
            raise TradingViewError(f"Motor yüklenemedi: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._motor = module

    def targets(self) -> list[str]:
        return list(self._motor.bul_hedefler())

    def strategies(self, target_id: str) -> list[dict[str, Any]]:
        result = self._motor._eval(target_id, """(()=>{
          const c=TradingViewApi._activeChartWidgetWV.value();
          return c._chartWidget.model().dataSources()
            .filter(x=>typeof x.reportData==='function')
            .map(x=>({id:x.id?.(),name:x.name?.(),status:x._status?.value?.()}));
        })()""")
        return result if isinstance(result, list) else []

    def inventory(self) -> list[dict[str, Any]]:
        """Discover target strategies concurrently so one stale target cannot serialize timeouts."""
        targets = self.targets()

        def inspect(target_id: str) -> dict[str, Any]:
            try:
                return {"target_id": target_id, "strategies": self.strategies(target_id), "error": None}
            except Exception as exc:
                return {"target_id": target_id, "strategies": [], "error": str(exc)}

        with ThreadPoolExecutor(max_workers=min(16, max(1, len(targets)))) as pool:
            return list(pool.map(inspect, targets))

    def _eval(self, target_id: str, study_id: str, body: str) -> Any:
        prefix = (
            "const c=TradingViewApi._activeChartWidgetWV.value(),"
            f"s=c._chartWidget.model().dataSources().find(x=>x.id?.()==={json.dumps(study_id)});"
            "if(!s)return {error:'study_missing'};"
        )
        result = self._motor._eval(target_id, "(()=>{" + prefix + body + "})()")
        if isinstance(result, dict) and result.get("error"):
            raise TradingViewError(f"Strateji bulunamadı: {study_id}")
        return result

    def snapshot(self, target_id: str, study_id: str) -> StrategySnapshot:
        data = self._eval(target_id, study_id, """
            const r=s.reportData(),p=r?.performance,a=p?.all;
            return {status:s._status?.value?.(),symbol:c.symbol(),tf:String(c.resolution()),
              inputs:c.getStudyById(s.id()).getInputValues(),
              metrics:a?{trades:a.totalTrades,profit_factor:a.profitFactor,
                win_rate_pct:a.percentProfitable*100,max_drawdown_pct:p.maxStrategyDrawDownPercent*100,
                net_profit:a.netProfit,net_profit_pct:a.netProfitPercent*100}:null,
              period:r?.settings||null};
        """)
        status = data.get("status") or {}
        return StrategySnapshot(
            symbol=str(data.get("symbol", "")), timeframe=str(data.get("tf", "")),
            status_type=status.get("type") if isinstance(status, dict) else None,
            inputs={item["id"]: item.get("value") for item in data.get("inputs", [])
                    if re.fullmatch(r"in_\d+", str(item.get("id", "")))},
            metrics=data.get("metrics"), period=data.get("period"),
        )

    def configure(self, target_id: str, study_id: str, symbol: str, timeframe: str, inputs: dict[str, Any]) -> None:
        values = [{"id": key, "value": value} for key, value in inputs.items()]
        self._eval(target_id, study_id, f"c.setSymbol({json.dumps(symbol)},{{}});return true;")
        time.sleep(1.2)
        self._eval(target_id, study_id, f"c.setResolution({json.dumps(timeframe)},{{}});return true;")
        time.sleep(0.8)
        self._eval(target_id, study_id, f"c.getStudyById(s.id()).setInputValues({json.dumps(values)});return true;")

    def screenshot(self, target_id: str, destination: str | Path) -> str:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._motor.screenshot(target_id, str(path))
        return str(path)


def symbol_matches(requested: str, observed: str) -> bool:
    contract = requested.rsplit(":", 1)[-1]
    return observed == requested or observed.endswith(":" + contract)


def date_range_matches(expected: dict[str, Any], period: dict[str, Any] | None) -> bool:
    if not expected:
        return True
    backtest = ((period or {}).get("dateRange") or {}).get("backtest") or {}
    for key in ("from", "to"):
        requested = expected.get(key)
        if not requested:
            continue
        observed = backtest.get(key)
        if not isinstance(observed, (int, float)):
            return False
        observed_date = datetime.fromtimestamp(observed / 1000).date().isoformat()
        if observed_date != requested:
            return False
    return True


def wait_for_verified_result(
    driver: TradingViewDriver,
    target_id: str,
    study_id: str,
    expected: dict[str, Any],
    *,
    timeout: float = 75,
    poll_interval: float = 0.7,
    stable_reads: int = 3,
) -> StrategySnapshot:
    """Return only a stable result whose chart and inputs match the task."""
    deadline = time.monotonic() + timeout
    previous: str | None = None
    stable = 0
    last: StrategySnapshot | None = None
    while time.monotonic() < deadline:
        last = driver.snapshot(target_id, study_id)
        state = json.dumps([last.metrics, last.period], sort_keys=True)
        requested_tf = {"1H": "60", "4H": "240", "1D": "D", "1W": "W"}.get(expected["timeframe"], expected["timeframe"])
        period_matches = date_range_matches(expected.get("date_range") or {}, last.period)
        valid = (
            last.status_type == 2
            and last.metrics is not None
            and symbol_matches(expected["symbol"], last.symbol)
            and last.timeframe == requested_tf
            and all(last.inputs.get(key) == value for key, value in expected.get("inputs", {}).items())
            and period_matches
        )
        stable = stable + 1 if valid and state == previous else (1 if valid else 0)
        previous = state
        if stable >= stable_reads:
            return last
        time.sleep(max(0.01, poll_interval))
    raise VerificationMismatch(f"Sonuç doğrulanamadı; son durum: {last!r}", last)
