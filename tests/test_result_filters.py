from tv_scan_studio.result_filters import filter_results


ROWS = [
    {"task_id": 1, "classification": "hassas", "verified": True,
     "payload": {"symbol": "OANDA:DE30EUR", "timeframe": "15"},
     "metrics": {"profit_factor": 1.7, "max_drawdown_pct": 4.2, "trades": 82,
                 "win_rate_pct": 47, "net_profit": 1200}, "created_at": 1_700_000_000},
    {"task_id": 2, "classification": "elenmiş", "verified": True,
     "payload": {"symbol": "OANDA:NAS100USD", "timeframe": "5"},
     "metrics": {"profit_factor": 1.1, "max_drawdown_pct": 7, "trades": 30,
                 "win_rate_pct": 35, "net_profit": -20}, "created_at": 1_700_000_100},
]


def test_default_only_success_and_numeric_filter():
    assert [row["task_id"] for row in filter_results(ROWS)] == [1]
    assert filter_results(ROWS, min_pf=1.8) == []
    assert filter_results(ROWS, max_dd=4) == []
    assert filter_results(ROWS, min_trades=80, min_win=45, symbol="de30", timeframe="15") == [ROWS[0]]


def test_unverified_candidate_is_not_presented_as_success():
    unverified = {**ROWS[0], "task_id": 3, "verified": False}
    assert filter_results([unverified]) == []
    assert filter_results([unverified], classification="Tümü") == [unverified]


def test_all_view_and_date_range_do_not_change_source_rows():
    assert len(filter_results(ROWS, classification="Tümü")) == 2
    assert filter_results(ROWS, classification="Tümü", date_from="2025-01-01") == []
    assert len(ROWS) == 2


def test_date_filter_uses_backtest_period_not_record_creation():
    row = dict(ROWS[0])
    row["payload"] = {**row["payload"], "date_range": {
        "from_ms": 1_735_689_600_000,  # 2025-01-01 UTC
        "to_ms": 1_767_139_200_000,    # 2025-12-31 UTC
    }}
    assert filter_results([row], date_from="2025-06-01", date_to="2025-06-30") == [row]
    assert filter_results([row], date_from="2026-01-01") == []
    assert filter_results([row], date_to="2024-12-31") == []


def test_date_filter_does_not_substitute_task_creation_for_missing_period():
    assert filter_results(ROWS[:1], date_from="2023-11-14", date_to="2023-11-14") == []
    incomplete = {**ROWS[0], "payload": {**ROWS[0]["payload"],
                  "date_range": {"from": "2023-11-14"}}}
    assert filter_results([incomplete], date_from="2023-11-14") == []


def test_date_filter_prefers_observed_period_over_requested_period():
    row = {**ROWS[0], "payload": {**ROWS[0]["payload"],
           "date_range": {"from": "2025-01-01", "to": "2025-12-31"}},
           "evidence": {"period": {"dateRange": {"backtest": {
               "from": "2024-01-01", "to": "2024-12-31"}}}}}
    assert filter_results([row], date_from="2025-06-01") == []
    assert filter_results([row], date_from="2024-06-01", date_to="2024-06-30") == [row]
    row["evidence"] = {"period": {"dateRange": {}}}
    assert filter_results([row], date_from="2025-06-01") == []


def test_cost_scenario_filter_uses_applied_task_assumption():
    normal = {**ROWS[0], "payload": {**ROWS[0]["payload"],
              "costs": {"assumptions": {"scenario": "Normal"}}}}
    heavy = {**ROWS[0], "task_id": 3, "payload": {**ROWS[0]["payload"],
             "costs": {"assumptions": {"scenario": "Ağır stres"}}}}
    assert filter_results([normal, heavy], cost_scenario="Ağır stres") == [heavy]
    assert filter_results([normal, heavy], cost_scenario="Normal") == [normal]
    assert filter_results([ROWS[0]], cost_scenario="Belirtilmedi") == [ROWS[0]]


def test_active_numeric_filter_never_treats_missing_or_nonfinite_metric_as_zero():
    missing = {**ROWS[0], "metrics": {}}
    assert filter_results([missing], max_dd=5) == []
    assert filter_results([missing], min_pf=1.5) == []
    assert filter_results([missing], min_trades=40) == []
    assert filter_results([missing], min_win=40) == []
    assert filter_results([missing], min_net=0) == []
    assert filter_results([missing]) == [missing]
    invalid = {**ROWS[0], "metrics": {**ROWS[0]["metrics"],
               "max_drawdown_pct": float("nan"), "profit_factor": "bad"}}
    assert filter_results([invalid], max_dd=5) == []
    assert filter_results([invalid], min_pf=1.5) == []
