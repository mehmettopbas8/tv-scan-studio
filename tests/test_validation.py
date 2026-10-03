from tv_scan_studio.storage import Store
from tv_scan_studio.validation import enqueue_followups, followup_payloads


def base_payload():
    return {
        "study_id": "sid", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20, "in_1": True},
        "costs": {"assumptions": {"commission_value": .1, "spread": 1, "slippage": 2},
                  "tradingview_inputs": {"in_7": .1},
                  "input_mapping": {"commission_value": "in_7"}},
    }


def test_followups_cover_neighbors_cost_stress_and_provider():
    rows = list(followup_payloads(base_payload(), "FX:EURUSD"))
    assert [stage for stage, _ in rows].count("neighbor") == 2
    assert [stage for stage, _ in rows].count("cost_stress") == 2
    assert rows[-1][0] == "provider_check"
    heavy = [payload for stage, payload in rows if stage == "cost_stress"][-1]
    assert heavy["costs"]["tradingview_inputs"]["in_7"] == .2


def test_cost_stress_is_not_generated_from_metadata_only():
    payload = base_payload()
    payload["costs"]["input_mapping"] = {}
    payload["costs"]["tradingview_inputs"] = {}
    assert not [row for row in followup_payloads(payload, "") if row[0] == "cost_stress"]


def test_cost_stress_uses_complete_strategy_properties_without_pine_mapping():
    payload = base_payload()
    costs = {'initial_capital':100000, 'position_size':1, 'commission_value':.02,
             'commission_type':'percent', 'slippage':5, 'spread':0}
    payload['costs'] = {'assumptions':costs}
    rows = [child for stage, child in followup_payloads(payload, '') if stage == 'cost_stress']
    assert len(rows) == 2
    assert [row['costs']['assumptions']['slippage'] for row in rows] == [8, 10]
    assert [row['costs']['assumptions']['commission_value'] for row in rows] == [.03, .04]
    assert costs['slippage'] == 5


def test_zero_costs_do_not_claim_a_stress_variation():
    payload = base_payload()
    payload['costs'] = {'assumptions':dict(initial_capital=100000, position_size=1,
        commission_value=0, commission_type='percent', slippage=0, spread=0)}
    assert not [row for row in followup_payloads(payload, '') if row[0] == 'cost_stress']


def test_cost_stress_requires_a_nonzero_verified_baseline_mapping():
    payload = base_payload()
    payload["costs"]["tradingview_inputs"]["in_7"] = 99
    assert not [row for row in followup_payloads(payload, "") if row[0] == "cost_stress"]
    payload["costs"]["tradingview_inputs"]["in_7"] = 0
    payload["costs"]["assumptions"]["commission_value"] = 0
    assert not [row for row in followup_payloads(payload, "") if row[0] == "cost_stress"]


def test_all_validation_gates_promote_parent_to_durable(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Validation", 'strategy("Validation")')
    store.enqueue(project, "parent", base_payload())
    parent = store.claim_next(1)
    store.complete(parent.id, 1, {"trades": 100}, "hassas", verified=True, evidence={})
    assert enqueue_followups(store, parent.id, base_payload(), "FX:EURUSD") == 5
    while child := store.claim_next(2):
        store.complete(child.id, 2, {"trades": 100}, "hassas", verified=True, evidence={})
    parent_result = next(row for row in store.results(project) if row["task_id"] == parent.id)
    assert parent_result["classification"] == "dayanıklı"
    assert all(parent_result["evidence"]["validation"].values())


def test_failed_validation_child_keeps_parent_sensitive(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Validation", 'strategy("Validation")')
    store.enqueue(project, "parent", base_payload())
    parent = store.claim_next(1)
    store.complete(parent.id, 1, {"trades": 100}, "hassas", verified=True, evidence={})
    enqueue_followups(store, parent.id, base_payload(), "FX:EURUSD")
    child = store.claim_next(2)
    store.fail(child.id, 2, "invalid", max_attempts=1)
    parent_result = next(row for row in store.results(project) if row["task_id"] == parent.id)
    assert parent_result["classification"] == "hassas"
    assert parent_result["evidence"]["validation"]["neighbor_passed"] is False
