from tv_scan_studio.sensitivity import one_input_neighbors, possible_no_effect_inputs


def test_neighbors_require_same_context_and_one_changed_input():
    base = {"task_id": 1, "payload": {"symbol": "DE30", "timeframe": "15",
            "date_range": {"from": 1, "to": 2}, "costs": {"commission": .04},
            "inputs": {"in_0": 2, "in_1": True}}}

    def candidate(task_id, *, symbol="DE30", commission=.04, value=3, enabled=True):
        return {"task_id": task_id, "payload": {"symbol": symbol, "timeframe": "15",
                "date_range": {"from": 1, "to": 2}, "costs": {"commission": commission},
                "inputs": {"in_0": value, "in_1": enabled}}}

    rows = [base, candidate(2), candidate(3, symbol="NAS100"),
            candidate(4, commission=.08), candidate(5, enabled=False)]
    neighbors = one_input_neighbors(base, rows)
    assert [(item["row"]["task_id"], item["input_id"]) for item in neighbors] == [(2, "in_0")]


def test_possible_no_effect_needs_three_verified_values_and_identical_full_results():
    metrics = {"trades": 80, "profit_factor": 1.7,
               "max_drawdown_pct": 4.0, "net_profit": 900, "daily_pnl": {"2026-01-01": 90}}

    def result(value, *, symbol="DE30", verified=True, daily=90):
        return {"verified": verified, "classification": "hassas",
                "payload": {"symbol": symbol, "timeframe": "15",
                            "date_range": {"from": 1, "to": 2},
                            "costs": {"commission": 0.04},
                            "inputs": {"in_0": value, "in_1": True}},
                "metrics": {**metrics, "daily_pnl": {"2026-01-01": daily}}}

    equal = [result(2), result(3), result(4)]
    assert possible_no_effect_inputs(equal) == {"in_0": 3}
    assert possible_no_effect_inputs(equal[:2]) == {}
    assert possible_no_effect_inputs([*equal[:2], result(4, verified=False)]) == {}
    assert possible_no_effect_inputs([*equal[:2], result(4, symbol="NAS100")]) == {}
    assert possible_no_effect_inputs([*equal, result(5, daily=91)]) == {}
    assert possible_no_effect_inputs([{**equal[0], "metrics": {"trades": 80}}, *equal[1:2]]) == {}
