"""User-visible result filtering, independent from export scope."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable


SUCCESS_CLASSES = frozenset({"hassas", "dayanıklı"})


def _day(value):
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, timezone.utc).date().isoformat()
    return str(value or "")[:10]


def _metric_number(metrics: dict[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _passes_metric_bound(metrics: dict[str, Any], key: str, bound: float, *,
                         active: bool, minimum: bool) -> bool:
    if not active:
        return True
    number = _metric_number(metrics, key)
    return number is not None and (number >= bound if minimum else number <= bound)


def _tested_period(row: dict[str, Any]) -> dict[str, Any]:
    observed = (row.get("evidence") or {}).get("period")
    if isinstance(observed, dict) and observed:
        return ((observed.get("dateRange") or {}).get("backtest") or {}
                if "dateRange" in observed else observed)
    return ((row.get("payload") or {}).get("date_range") or {})


def filter_results(rows: Iterable[dict[str, Any]], *, classification: str = "Başarılı",
                   min_pf: float = 0, max_dd: float = 100, min_trades: int = 0,
                   min_win: float = 0, min_net: float = float("-inf"),
                   symbol: str = "", timeframe: str = "", evidence: str = "Tümü",
                   date_from: str = "", date_to: str = "",
                   cost_scenario: str = "Tümü") -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        kind = row.get("classification")
        if classification == "Başarılı" and (kind not in SUCCESS_CLASSES or not row.get("verified")):
            continue
        if classification not in {"Başarılı", "Tümü"} and kind != classification:
            continue
        metrics = row.get("metrics") or {}
        if not _passes_metric_bound(metrics, "profit_factor", min_pf,
                                    active=min_pf > 0, minimum=True):
            continue
        if not _passes_metric_bound(metrics, "max_drawdown_pct", max_dd,
                                    active=max_dd < 100, minimum=False):
            continue
        if not _passes_metric_bound(metrics, "trades", min_trades,
                                    active=min_trades > 0, minimum=True):
            continue
        if not _passes_metric_bound(metrics, "win_rate_pct", min_win,
                                    active=min_win > 0, minimum=True):
            continue
        if not _passes_metric_bound(metrics, "net_profit", min_net,
                                    active=min_net > -1_000_000_000, minimum=True):
            continue
        payload = row.get("payload") or {}
        scenario = ((payload.get("costs") or {}).get("assumptions") or {}).get("scenario")
        if cost_scenario != "Tümü" and (scenario or "Belirtilmedi") != cost_scenario:
            continue
        if symbol and symbol.casefold() not in str(payload.get("symbol") or "").casefold():
            continue
        if timeframe and timeframe.strip() != str(payload.get("timeframe") or ""):
            continue
        if evidence == "Doğrulanmış" and not row.get("verified"):
            continue
        if evidence == "Doğrulanmamış" and row.get("verified"):
            continue
        if date_from or date_to:
            period = _tested_period(row)
            # A task's creation time is not evidence of the tested market period.
            start = _day(period.get("from_ms", period.get("from")))
            end = _day(period.get("to_ms", period.get("to")))
            if not start or not end or start > end:
                continue
            if date_from and end < date_from:
                continue
            if date_to and start > date_to:
                continue
        selected.append(row)
    return selected
