from dataclasses import replace
import copy
import pytest
from tv_scan_studio.coarse_fine import candidate_context, refinement_plan, valid_period
from tv_scan_studio.planner import ScanPlan, enqueue_plan, iter_tasks
from tv_scan_studio.storage import Store


CODE = 'strategy("EMA")\nn=input.int(8,"Fast EMA",minval=1,maxval=20)\ns=input.int(21,"Slow EMA",minval=1,maxval=100)'


@pytest.mark.parametrize("period", [None, {}, {"from": 1}, {"from": 2, "to": 1},
    {"from": True, "to": 2}, {"from": 1, "to": float("inf")}, {"from": "bad", "to": "2026-09-30"}])
def test_missing_or_invalid_report_period_is_not_accepted(period):
    assert not valid_period(period)


def coarse(tmp_path, *, finish=True, evidence_transform=None):
    store = Store(tmp_path / "coarse.db")
    project = store.create_project("EMA", CODE)
    plan = ScanPlan("study", ("BIST:XU030D1!",), ("15",), {"in_0": [7, 9], "in_1": [21, 25]},
        method="coarse", costs={"assumptions": {"initial_capital": 100000}}, date_range={"from": "2026-09-01", "to": "2026-09-30"})
    _, run_id = enqueue_plan(store, project, plan, new_run=True, return_run_id=True)
    ids = []
    for _ in range(4 if finish else 1):
        task = store.claim_next(1, [project], run_ids=[run_id])
        evidence = {"symbol": task.payload["symbol"], "timeframe": "15", "inputs": task.payload["inputs"],
                    "period": {"from": 1, "to": 2}, "cost_verification_scope": "strategy_properties_ui_spread_unverified"}
        if evidence_transform:
            evidence_transform(evidence, task.payload)
        store.complete(task.id, 1, {"profit_factor": 1.5}, "hassas", verified=True, evidence=evidence)
        ids.append(store.result_history(task.id)[-1]["id"])
    return store, project, run_id, plan, ids


def context(store, project, ids):
    with store.connect() as connection:
        return candidate_context(connection, project, ids, store.project(project)["pine_source"])


def test_legacy_deep_period_cannot_select_refinement_candidate(tmp_path):
    def legacy(evidence, payload):
        evidence.update(report_source="deep_xlsx", period=payload["date_range"])
    store, project, _, _, ids = coarse(tmp_path, evidence_transform=legacy)
    before = copy.deepcopy((store.tasks(project), store.scan_runs(project)))
    with pytest.raises(ValueError, match="rapor dönemi"):
        context(store, project, ids[:1])
    assert (store.tasks(project), store.scan_runs(project)) == before


def test_export_observed_deep_period_can_select_refinement_candidate(tmp_path):
    observed = {"from": "2026-09-10", "to": "2026-09-20"}
    def actual(evidence, payload):
        evidence.update(report_source="deep_xlsx", period=payload["date_range"],
            report_period_provenance="deep_export_observed", report_period=observed)
    store, project, _, _, ids = coarse(tmp_path, evidence_transform=actual)
    selected = context(store, project, ids[:1])
    assert selected["records"][0]["evidence"]["report_period"] == observed
    assert refinement_plan(selected, "in_0", [7, 8]).task_count == 2


def test_coarse_keeps_cartesian_task_identity_and_has_no_cap():
    plan = ScanPlan("s", ("BIST:XU030D1!",), ("15",), {"in_0": list(range(700))}, method="coarse")
    assert plan.task_count == 700
    assert list(iter_tasks(plan)) == list(iter_tasks(replace(plan, method="cartesian")))
    constrained = replace(plan, input_values={"in_0": [1, 3], "in_1": [2, 4]},
        constraints=[{"left": "in_0", "operator": "<", "right": "in_1"}])
    assert len(list(iter_tasks(constrained))) == 3


def test_selected_candidates_stay_frozen_as_packages_and_lineage_is_immutable(tmp_path):
    store, project, run_id, coarse_plan, ids = coarse(tmp_path)
    before = copy.deepcopy(store.results(project))
    # Choose both slow EMA settings; never recombine unrelated candidate coordinates.
    fine = refinement_plan(context(store, project, [ids[0], ids[1]]), "in_0", [6, 7, 8])
    assert fine.input_values == {"in_0": [6, 7, 8]}
    assert fine.variants == [{"in_1": 21}, {"in_1": 25}]
    assert fine.task_count == 6
    count, fine_run = enqueue_plan(store, project, fine, new_run=True, return_run_id=True)
    assert count == 6 and fine_run != run_id
    snapshot = store.scan_runs(project)[0]["plan_snapshot"]
    assert snapshot["research"]["parent_run_id"] == run_id
    assert snapshot["research"]["candidate_result_ids"] == [ids[0], ids[1]]
    assert len(store.run_tasks(run_id)) == 4
    assert store.results(project) == before
    assert enqueue_plan(store, project, fine, run_id=fine_run) == 0


def test_unfinished_coarse_run_cannot_be_refined(tmp_path):
    store, project, _, _, ids = coarse(tmp_path, finish=False)
    with pytest.raises(ValueError, match="bekleyen/çalışan"):
        context(store, project, ids)


@pytest.mark.parametrize("values", [[0], [21], [True], [8.5], [float("inf")], [8, 8], []])
def test_fine_values_obey_pine_and_dedup_validation(tmp_path, values):
    store, project, _, _, ids = coarse(tmp_path)
    with pytest.raises(ValueError):
        refinement_plan(context(store, project, [ids[0]]), "in_0", values)


def test_plan_changes_after_approval_roll_back_tasks_settings_and_new_run(tmp_path):
    store, project, _, _, ids = coarse(tmp_path)
    fine = refinement_plan(context(store, project, [ids[0]]), "in_0", [7, 8, 9])
    before_tasks, before_settings, before_runs = store.tasks(project), store.settings(project), store.scan_runs(project)
    with pytest.raises(ValueError, match="aday/onay"):
        enqueue_plan(store, project, replace(fine, input_values={"in_0": [8, 9, 10]}), new_run=True)
    assert store.tasks(project) == before_tasks and store.settings(project) == before_settings and store.scan_runs(project) == before_runs


def test_changed_source_and_foreign_candidate_are_rejected(tmp_path):
    store, project, _, _, ids = coarse(tmp_path)
    foreign = store.create_project("Other", CODE + "\n// different")
    with pytest.raises(ValueError, match="stratejinin"):
        context(store, foreign, ids)
    with store.connect() as connection:
        connection.execute("UPDATE projects SET pine_source=? WHERE id=?", (CODE + "\n// changed", project))
    with pytest.raises(ValueError, match="Pine kaynağı"):
        context(store, project, ids)
