from copy import deepcopy
from dataclasses import replace
import pytest

from tv_scan_studio.storage import Store
from tv_scan_studio.planner import ScanPlan, enqueue_plan, iter_tasks
from tv_scan_studio.period_research import (date_window, selection_context, validation_plan,
    walkforward_training_plan, completed_validation)

CODE = 'strategy("EMA")\na=input.int(8,"Fast EMA",minval=1,maxval=20)\nb=input.int(21,"Slow EMA",minval=1,maxval=100)'
TRAIN = {"from": "2026-01-01", "to": "2026-03-31"}
HOLDOUT = {"from": "2026-04-01", "to": "2026-04-30"}


def finish(store, project, run_id, evidence_transform=None):
    result_ids = []
    while task := store.claim_next(1, [project], run_ids=[run_id]):
        evidence = {"symbol": task.payload["symbol"], "timeframe": task.payload["timeframe"],
                "inputs": task.payload["inputs"], "period": task.payload["date_range"],
                "report_currency": "TRY", "cost_verification_scope": "strategy_properties_ui_spread_unverified"}
        if evidence_transform:
            evidence_transform(evidence, task.payload)
        store.complete(task.id, 1, {"profit_factor": 1.5}, "hassas", verified=True, evidence=evidence)
        result_ids.append(store.result_history(task.id)[-1]["id"])
    return result_ids


def setup(tmp_path, *, finished=True, evidence_transform=None):
    store = Store(tmp_path / "period.db")
    project = store.create_project("EMA", CODE)
    plan = ScanPlan("study", ["BIST:XU030D1!"], ["15"], {"in_0": [7, 9], "in_1": [21, 25]},
        date_range=TRAIN, costs={"assumptions": {"initial_capital": 100000}})
    _, run_id = enqueue_plan(store, project, plan, new_run=True, return_run_id=True)
    ids = finish(store, project, run_id, evidence_transform) if finished else []
    return store, project, run_id, plan, ids


def selected(store, project, ids):
    with store.connect() as connection:
        return selection_context(connection, project, ids, CODE)


def test_legacy_deep_requested_period_is_not_selection_evidence(tmp_path):
    def legacy(evidence, payload):
        evidence.update(report_source="deep_xlsx", period=payload["date_range"])
    store, project, _, _, ids = setup(tmp_path, evidence_transform=legacy)
    with pytest.raises(ValueError, match="rapor dönemi"):
        selected(store, project, ids[:1])


def test_observed_deep_period_drives_selection_and_holdout_proof(tmp_path):
    def actual(evidence, payload):
        evidence.update(report_source="deep_xlsx", report_period_provenance="deep_export_observed",
            report_period=deepcopy(payload["date_range"]), period={"from": "1900-01-01", "to": "1900-01-02"})
    store, project, _, _, ids = setup(tmp_path, evidence_transform=actual)
    holdout = validation_plan(selected(store, project, ids[:1]), HOLDOUT)
    _, child = enqueue_plan(store, project, holdout, new_run=True, return_run_id=True)
    finish(store, project, child, actual)
    with store.connect() as connection:
        assert completed_validation(connection, project, child, CODE)


def test_legacy_deep_holdout_does_not_unlock_walkforward(tmp_path):
    store, project, _, _, ids = setup(tmp_path)
    holdout = validation_plan(selected(store, project, ids[:1]), HOLDOUT)
    _, child = enqueue_plan(store, project, holdout, new_run=True, return_run_id=True)
    def legacy(evidence, payload):
        evidence.update(report_source="deep_xlsx", period=payload["date_range"])
    finish(store, project, child, legacy)
    with store.connect() as connection, pytest.raises(ValueError):
        completed_validation(connection, project, child, CODE)


def test_holdout_freezes_whole_packages_and_preserves_training(tmp_path):
    store, project, run_id, plan, ids = setup(tmp_path)
    before = deepcopy(store.results(project))
    context = selected(store, project, [ids[0], ids[3]])
    validation = validation_plan(context, HOLDOUT)
    assert validation.input_values == {}
    assert validation.variants == [{"in_0": 7, "in_1": 21}, {"in_0": 9, "in_1": 25}]
    assert [payload["inputs"] for _, payload in iter_tasks(validation)] == validation.variants
    _, child_run = enqueue_plan(store, project, validation, new_run=True, return_run_id=True)
    assert child_run != run_id and store.results(project) == before
    snapshot = store.scan_runs(project)[0]["plan_snapshot"]
    assert snapshot["research"]["candidate_result_ids"] == [ids[0], ids[3]]
    assert snapshot["research"]["selection_period"] == TRAIN
    assert snapshot["research"]["validation_period"] == HOLDOUT
    assert enqueue_plan(store, project, validation, run_id=child_run) == 0


@pytest.mark.parametrize("window", [None, {}, {"from": "2026-02-01", "to": "2026-04-30"},
    {"from": "2026-03-31", "to": "2026-04-30"}, {"from": "2026-04-30", "to": "2026-04-01"},
    {"from": "2026-4-1", "to": "2026-04-30"}])
def test_invalid_or_overlapping_validation_does_not_write(tmp_path, window):
    store, project, _, _, ids = setup(tmp_path)
    before = deepcopy((store.tasks(project), store.settings(project), store.scan_runs(project)))
    with pytest.raises(ValueError):
        validation_plan(selected(store, project, [ids[0]]), window)
    assert (store.tasks(project), store.settings(project), store.scan_runs(project)) == before


@pytest.mark.parametrize("change", ["inputs", "period", "criteria", "candidate", "stage"])
def test_modified_frozen_request_is_rejected_atomically(tmp_path, change):
    store, project, _, _, ids = setup(tmp_path)
    plan = validation_plan(selected(store, project, [ids[0]]), HOLDOUT)
    if change == "inputs":
        plan = replace(plan, variants=[{"in_0": 8, "in_1": 21}])
    elif change == "period":
        plan = replace(plan, date_range={"from": "2026-05-01", "to": "2026-05-31"})
    elif change == "criteria":
        plan = replace(plan, criteria={"min_profit_factor": 2})
    else:
        research = deepcopy(plan.research)
        research["candidate_result_ids" if change == "candidate" else "stage"] = [ids[1]] if change == "candidate" else "training"
        plan = replace(plan, research=research)
    before = deepcopy((store.tasks(project), store.settings(project), store.scan_runs(project)))
    with pytest.raises(ValueError):
        enqueue_plan(store, project, plan, new_run=True)
    assert (store.tasks(project), store.settings(project), store.scan_runs(project)) == before


def test_validation_results_cannot_select_candidates_and_walkforward_is_sequential(tmp_path):
    store, project, _, _, ids = setup(tmp_path)
    holdout = validation_plan(selected(store, project, [ids[0], ids[1]]), HOLDOUT)
    _, validation_run = enqueue_plan(store, project, holdout, new_run=True, return_run_id=True)
    next_training_period = {"from": "2026-02-01", "to": "2026-04-30"}
    with store.connect() as connection, pytest.raises(ValueError, match="bütün testleri"):
        walkforward_training_plan(connection, project, validation_run, CODE, next_training_period)
    holdout_ids = finish(store, project, validation_run)
    with pytest.raises(ValueError, match="aday seçimi"):
        selected(store, project, holdout_ids)
    with store.connect() as connection:
        training = walkforward_training_plan(connection, project, validation_run, CODE, next_training_period)
    assert training.input_values == {"in_0": [7, 9], "in_1": [21, 25]}
    assert training.research["previous_validation_run_id"] == validation_run
    _, next_run = enqueue_plan(store, project, training, new_run=True, return_run_id=True)
    next_ids = finish(store, project, next_run)
    context = selected(store, project, next_ids[:2])
    assert context["previous_validation_run_id"] == validation_run
    next_holdout = validation_plan(context, {"from": "2026-05-01", "to": "2026-05-31"}, previous_validation_period=HOLDOUT)
    _, next_validation_run = enqueue_plan(store, project, next_holdout, new_run=True, return_run_id=True)
    assert next_validation_run != validation_run
    assert store.scan_runs(project)[0]["plan_snapshot"]["research"]["selection_run_id"] == next_run


@pytest.mark.parametrize("period", [{"from": "2025-12-01", "to": "2026-04-30"}, TRAIN,
    {"from": "2026-02-01", "to": "2026-04-20"}])
def test_walkforward_rejects_backward_or_premature_training_windows(tmp_path, period):
    store, project, _, _, ids = setup(tmp_path)
    plan = validation_plan(selected(store, project, ids[:1]), HOLDOUT)
    _, run_id = enqueue_plan(store, project, plan, new_run=True, return_run_id=True)
    finish(store, project, run_id)
    with store.connect() as connection, pytest.raises(ValueError, match="ileri taşınmalı"):
        walkforward_training_plan(connection, project, run_id, CODE, period)


def test_report_period_outside_selection_is_not_holdout_proof(tmp_path):
    store, project, run_id, plan, _ = setup(tmp_path, finished=False)
    ids = []
    while task := store.claim_next(1, [project], run_ids=[run_id]):
        store.complete(task.id, 1, {}, "hassas", verified=True, evidence={"symbol": task.payload["symbol"],
            "timeframe": "15", "inputs": task.payload["inputs"], "period": HOLDOUT,
            "cost_verification_scope": "strategy_properties_ui_spread_unverified"})
        ids.append(store.result_history(task.id)[-1]["id"])
    with pytest.raises(ValueError, match="seçim dönemi dışında"):
        selected(store, project, ids[:1])


def test_training_reopened_during_staging_rejects_final_commit(tmp_path):
    store, project, parent_run, _, ids = setup(tmp_path)
    validation = validation_plan(selected(store, project, ids[:1]), HOLDOUT)
    old_settings, old_runs, old_count = store.settings(project), store.scan_runs(project), len(store.tasks(project))
    def reopened(_processed, _inserted):
        with store.connect() as connection:
            connection.execute("UPDATE tasks SET status='pending' WHERE id=(SELECT task_id FROM run_tasks WHERE run_id=? LIMIT 1)", (parent_run,))
    with pytest.raises(ValueError, match="bekleyen/çalışan"):
        enqueue_plan(store, project, validation, new_run=True, progress=reopened)
    assert store.settings(project) == old_settings
    assert store.scan_runs(project) == old_runs and len(store.tasks(project)) == old_count


def test_changed_source_and_foreign_results_cannot_freeze_selection(tmp_path):
    store, project, _, _, ids = setup(tmp_path)
    other = store.create_project("Other", CODE)
    with pytest.raises(ValueError, match="stratejinin"):
        selected(store, other, ids[:1])
    with store.connect() as connection:
        connection.execute("UPDATE projects SET pine_source=? WHERE id=?", (CODE + "\n// changed", project))
    with store.connect() as connection, pytest.raises(ValueError, match="Pine kaynağı"):
        selection_context(connection, project, ids[:1], CODE + "\n// changed")


def test_candidate_invalidated_after_selection_cannot_commit_holdout(tmp_path):
    store, project, run_id, _, ids = setup(tmp_path)
    plan = validation_plan(selected(store, project, ids[:1]), HOLDOUT)
    with store.connect() as connection:
        task_id = connection.execute("SELECT task_id FROM result_history WHERE id=?", (ids[0],)).fetchone()[0]
        connection.execute("UPDATE tasks SET status='pending' WHERE id=?", (task_id,))
    task = store.claim_next(1, [project], run_ids=[run_id])
    store.invalidate(task.id, 1, "Evidence invalidated in fixture", {}, {})
    old_runs, old_settings, count = store.scan_runs(project), store.settings(project), len(store.tasks(project))
    with pytest.raises(ValueError, match="doğrulanmış sonuç"):
        enqueue_plan(store, project, plan, new_run=True)
    assert store.scan_runs(project) == old_runs and store.settings(project) == old_settings
    assert len(store.tasks(project)) == count


def test_coarse_fine_retains_walkforward_predecessor_and_fixed_candidates(tmp_path):
    from tv_scan_studio.coarse_fine import candidate_context, refinement_plan
    store, project, _, plan, ids = setup(tmp_path)
    # A user explicitly makes a coarse training run; no automatic winner selection.
    coarse = replace(plan, method="coarse")
    _, coarse_run = enqueue_plan(store, project, coarse, new_run=True, return_run_id=True)
    coarse_ids = finish(store, project, coarse_run)
    holdout = validation_plan(selected(store, project, coarse_ids[:1]), HOLDOUT)
    _, validation_run = enqueue_plan(store, project, holdout, new_run=True, return_run_id=True)
    finish(store, project, validation_run)
    with store.connect() as connection:
        next_training = walkforward_training_plan(connection, project, validation_run, CODE,
            {"from": "2026-02-01", "to": "2026-04-30"})
    _, next_run = enqueue_plan(store, project, next_training, new_run=True, return_run_id=True)
    training_ids = finish(store, project, next_run)
    with store.connect() as connection:
        context = candidate_context(connection, project, training_ids[:1], CODE)
    fine = refinement_plan(context, "in_0", [6, 7, 8])
    _, fine_run = enqueue_plan(store, project, fine, new_run=True, return_run_id=True)
    fine_ids = finish(store, project, fine_run)
    context = selected(store, project, fine_ids[:1])
    assert context["previous_validation_run_id"] == validation_run
    final = validation_plan(context, {"from": "2026-05-01", "to": "2026-05-31"}, previous_validation_period=HOLDOUT)
    assert final.variants == [{"in_0": 6, "in_1": 21}]
    assert enqueue_plan(store, project, final, new_run=True) == 1
