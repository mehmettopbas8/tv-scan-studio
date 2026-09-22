from tv_scan_studio.analytics import analyze_trades


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
    assert result["max_concurrent_positions"] == 2
    assert result["long_short"]["short"]["trades"] == 2
    assert result["max_loss_streak"] == 2
    assert result["session_pnl"] == {"LONDON": -300.0, "NYAM": -200.0}
