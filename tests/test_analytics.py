from tv_scan_studio.analytics import analyze_trades
from datetime import datetime, timezone


def trade(entry, exit_, pnl, side="le", session="NYAM", equity=100000, dd=100):
    return {"e": {"tm": entry, "tp": side, "c": f"Entry [{session}]"},
            "x": {"tm": exit_}, "tp": {"v": pnl}, "v": equity, "dd": {"v": dd}}


def test_trade_analytics_cover_risk_timing_direction_and_concentration():
    day = 1_750_000_000_000
    rows = [
        trade(day, day + 3_600_000, 500, "le", "NYAM", 100500, 0),
        trade(day + 1_800_000, day + 7_200_000, -300, "se", "LONDON", 100200, 300),
        trade(day + 86_400_000, day + 90_000_000, -700, "se", "NYAM", 99500, 700),
    ]
    result = analyze_trades(rows, 100000)
    assert result["analyzed_trades"] == 3
    assert result["max_daily_loss"] == 700
    assert result["max_daily_loss_pct"] == .7
    assert result["max_total_loss_pct"] == .5
    assert result["risk_evidence_scope"] == "closed_trades_only"
    assert result["max_concurrent_positions"] == 2
    assert result["long_short"]["short"]["trades"] == 2
    assert result["max_loss_streak"] == 2
    assert result["duration_histogram"]["1–4 saat"] == 3
    assert result["streak_distribution"] == {"Kazanç ×1": 1, "Kayıp ×2": 1}
    assert result["session_pnl"] == {"LONDON": -300.0, "NYAM": -200.0}


def test_new_york_day_and_hour_follow_dst_rules():
    winter = int(datetime(2025, 1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    summer = int(datetime(2025, 7, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    rows = [trade(winter, winter + 3_600_000, 100),
            trade(summer, summer + 3_600_000, 200)]
    result = analyze_trades(rows, 100000, "America/New_York")
    assert result["daily_pnl"] == {"2024-12-31": 100.0, "2025-06-30": 200.0}
    assert result["hourly_pnl"] == {"20:00": 100.0, "21:00": 200.0}
    assert result["analysis_timezone"] == "America/New_York"


def test_missing_capital_never_looks_like_zero_percent_daily_loss():
    day = 1_750_000_000_000
    result = analyze_trades([trade(day, day + 3_600_000, -500, equity=99500)])
    assert result["max_daily_loss"] == 500
    assert result["max_daily_loss_pct"] is None
    assert result["max_total_loss_pct"] is None


def test_closed_trade_only_report_gets_labeled_reconstruction_not_reported_equity():
    day = 1_750_000_000_000
    rows = [
        {"e": {"tm": day, "tp": "long"}, "x": {"tm": day + 60_000}, "tp": {"v": 10}},
        {"e": {"tm": day + 30_000, "tp": "short"},
         "x": {"tm": day + 120_000}, "tp": {"v": -20}},
    ]
    result = analyze_trades(rows, 100)
    assert result["equity_curve"] == []
    assert [point["equity"] for point in result["closed_trade_equity_curve"]] == [100, 110, 90]
    assert [point["drawdown"] for point in result["closed_trade_equity_curve"]] == [0, 0, 20]
    assert result["risk_evidence_scope"] == "closed_trades_only"
    assert analyze_trades(rows)["closed_trade_equity_curve"] == []
