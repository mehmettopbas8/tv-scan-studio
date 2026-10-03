"""Derive deterministic risk and behavior analytics from TradingView closed trades."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any, Iterable
from zoneinfo import ZoneInfo


def analyze_trades(trades: Iterable[dict[str, Any]], initial_capital: float = 0,
                   analysis_timezone: str = "UTC") -> dict[str, Any]:
    zone = ZoneInfo(analysis_timezone)
    normalized = []
    for trade in trades:
        entry, exit_ = trade.get("e") or {}, trade.get("x") or {}
        if not isinstance(entry.get("tm"), (int, float)) or not isinstance(exit_.get("tm"), (int, float)):
            continue
        pnl = float((trade.get("tp") or {}).get("v") or 0)
        entry_time = datetime.fromtimestamp(entry["tm"] / 1000, timezone.utc).astimezone(zone)
        exit_time = datetime.fromtimestamp(exit_["tm"] / 1000, timezone.utc).astimezone(zone)
        side = "long" if str(entry.get("tp", "")).lower().startswith("l") else "short"
        comment = str(entry.get("c") or "")
        session_match = re.search(r"\[([^\]]+)\]", comment)
        normalized.append({
            "entry": entry_time, "exit": exit_time, "pnl": pnl, "side": side,
            "session": session_match.group(1) if session_match else "Bilinmiyor",
            "equity": trade.get("v"), "drawdown": (trade.get("dd") or {}).get("v"),
        })
    if not normalized:
        return {}
    daily_pnl: defaultdict[str, float] = defaultdict(float)
    daily_count: Counter[str] = Counter()
    hourly_pnl: defaultdict[str, float] = defaultdict(float)
    weekday_pnl: defaultdict[str, float] = defaultdict(float)
    session_pnl: defaultdict[str, float] = defaultdict(float)
    side_stats = {"long": {"trades": 0, "net_profit": 0.0}, "short": {"trades": 0, "net_profit": 0.0}}
    durations = []
    duration_histogram = {"0–5 dk": 0, "5–15 dk": 0, "15–60 dk": 0,
                          "1–4 saat": 0, "4+ saat": 0}
    streak_distribution: Counter[str] = Counter()
    streak_kind = None
    streak_length = 0
    wins = losses = current_win = current_loss = 0
    max_wins = max_losses = 0
    intervals = []
    equity = []
    for trade in sorted(normalized, key=lambda item: item["exit"]):
        day = trade["exit"].date().isoformat()
        daily_pnl[day] += trade["pnl"]; daily_count[day] += 1
        hourly_pnl[f"{trade['entry'].hour:02d}:00"] += trade["pnl"]
        weekday_pnl[trade["entry"].strftime("%A")] += trade["pnl"]
        session_pnl[trade["session"]] += trade["pnl"]
        side_stats[trade["side"]]["trades"] += 1
        side_stats[trade["side"]]["net_profit"] += trade["pnl"]
        duration = max(0.0, (trade["exit"] - trade["entry"]).total_seconds() / 60)
        durations.append(duration)
        bucket = ("0–5 dk" if duration < 5 else "5–15 dk" if duration < 15 else
                  "15–60 dk" if duration < 60 else "1–4 saat" if duration < 240 else "4+ saat")
        duration_histogram[bucket] += 1
        kind = "Kazanç" if trade["pnl"] > 0 else "Kayıp" if trade["pnl"] < 0 else "Başabaş"
        if kind != streak_kind and streak_length:
            streak_distribution[f"{streak_kind} ×{streak_length}"] += 1
            streak_length = 0
        streak_kind, streak_length = kind, streak_length + 1
        intervals.extend(((trade["entry"], 1), (trade["exit"], -1)))
        if trade["pnl"] > 0:
            wins += 1; current_win += 1; current_loss = 0; max_wins = max(max_wins, current_win)
        elif trade["pnl"] < 0:
            losses += 1; current_loss += 1; current_win = 0; max_losses = max(max_losses, current_loss)
        if trade["equity"] is not None:
            equity.append({"time": int(trade["exit"].timestamp() * 1000), "equity": trade["equity"],
                           "drawdown": trade["drawdown"]})
    if streak_length:
        streak_distribution[f"{streak_kind} ×{streak_length}"] += 1
    closed_trade_curve = []
    if (initial_capital > 0 and math.isfinite(initial_capital) and len(equity) < 2
            and all(math.isfinite(item["pnl"]) for item in normalized)):
        # Deep XLSX has closed-trade P/L but no intrabar equity samples. Keep
        # this reconstruction separate from reported equity and FTMO risk proof.
        capital = float(initial_capital)
        peak = capital
        closed_trade_curve.append({"time": int(min(item["entry"] for item in normalized).timestamp() * 1000),
                                   "equity": capital, "drawdown": 0.0})
        for item in sorted(normalized, key=lambda trade: trade["exit"]):
            capital += item["pnl"]
            peak = max(peak, capital)
            closed_trade_curve.append({"time": int(item["exit"].timestamp() * 1000),
                                       "equity": capital, "drawdown": peak - capital})
    concurrent = maximum = 0
    for _, delta in sorted(intervals, key=lambda item: (item[0], item[1])):
        concurrent += delta; maximum = max(maximum, concurrent)
    worst_day = min(daily_pnl, key=daily_pnl.get)
    best_day = max(daily_pnl, key=daily_pnl.get)
    max_daily_loss = max(0.0, -daily_pnl[worst_day])
    net = sum(daily_pnl.values())
    observed_equity = [float(item["equity"]) for item in normalized
                       if isinstance(item["equity"], (int, float))]
    max_total_loss_pct = (
        max(0.0, (initial_capital - min(observed_equity)) / initial_capital * 100)
        if initial_capital > 0 and observed_equity else None
    )
    concentration_base = sum(abs(value) for value in daily_pnl.values()) or 1
    return {
        "max_daily_loss": max_daily_loss,
        "max_daily_loss_pct": round(max_daily_loss / initial_capital * 100, 8) if initial_capital > 0 else None,
        "max_total_loss_pct": round(max_total_loss_pct, 8) if max_total_loss_pct is not None else None,
        "risk_evidence_scope": "closed_trades_only",
        "analysis_timezone": analysis_timezone,
        "avg_daily_trades": mean(daily_count.values()), "max_daily_trades": max(daily_count.values()),
        "max_concurrent_positions": maximum,
        "best_day": {"date": best_day, "pnl": daily_pnl[best_day]},
        "worst_day": {"date": worst_day, "pnl": daily_pnl[worst_day]},
        "max_win_streak": max_wins, "max_loss_streak": max_losses,
        "duration_minutes": {"average": mean(durations), "median": median(durations), "maximum": max(durations)},
        "duration_histogram": duration_histogram,
        "streak_distribution": dict(sorted(streak_distribution.items())),
        "long_short": side_stats, "hourly_pnl": dict(sorted(hourly_pnl.items())),
        "weekday_pnl": dict(weekday_pnl), "session_pnl": dict(sorted(session_pnl.items())),
        "daily_pnl": dict(sorted(daily_pnl.items())), "equity_curve": equity,
        "closed_trade_equity_curve": closed_trade_curve,
        "top_day_concentration_pct": max(abs(value) for value in daily_pnl.values()) / concentration_base * 100,
        "trade_analysis_net_profit": net, "analyzed_trades": len(normalized),
    }
