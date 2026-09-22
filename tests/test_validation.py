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
