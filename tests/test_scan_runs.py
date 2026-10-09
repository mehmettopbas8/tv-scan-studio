from dataclasses import replace
import threading
import sqlite3
import pytest
from tv_scan_studio.storage import Store
from tv_scan_studio.planner import ScanPlan, PlanCancelled, enqueue_plan


def fixture(tmp_path):
    store = Store(tmp_path / "runs.db")
    project = store.create_project("EMA", 'strategy("EMA")\na=input.int(8)')
    plan = ScanPlan("study", ("A",), ("15",), {"in_0": [7, 8, 9]})
    return store, project, plan


def test_new_run_preserves_results_and_resume_reuses_task_ids(tmp_path):
    store, project, plan = fixture(tmp_path)
    assert enqueue_plan(store, project, plan, new_run=True) == 3
    first_run = store.scan_runs(project)[0]
    first_ids = [task["id"] for task in store.run_tasks(first_run["id"])]
    task = store.claim_next(1, [project], run_ids=[first_run["id"]])
    assert task.run_id == first_run["id"]
    store.complete(task.id, 1, {"trades": 20}, "hassas", verified=True)
    frozen = store.result_history(task.id)
    assert enqueue_plan(store, project, replace(plan, study_id="new-binding"), run_id=first_run["id"]) == 0
    assert [t["id"] for t in store.run_tasks(first_run["id"])] == first_ids
    assert enqueue_plan(store, project, replace(plan, criteria={"min_profit_factor": 2}), new_run=True,
                        require_pending_subset=True) == 3
    second_run = store.scan_runs(project)[0]
    assert second_run["id"] != first_run["id"]
    second_tasks = store.run_tasks(second_run["id"])
    assert not set(first_ids) & {t["id"] for t in second_tasks}
    assert [t["test_key"] for t in second_tasks] == [t["test_key"] for t in store.run_tasks(first_run["id"])]
    assert store.result_history(task.id) == frozen
    assert frozen[0]["run_id"] == first_run["id"]
    next_task = store.claim_next(2, [project], run_ids=[second_run["id"]])
    assert next_task.id in {t["id"] for t in second_tasks}
    assert next_task.run_id == second_run["id"]
    assert store.scan_runs(project)[1] == first_run


def test_resume_rejects_changed_plan_or_foreign_run(tmp_path):
    store, project, plan = fixture(tmp_path)
    enqueue_plan(store, project, plan, new_run=True)
    run_id = store.scan_runs(project)[0]["id"]
    before = store.settings(project)
    for changed in (replace(plan, symbols=("B",)), replace(plan, criteria={"min_profit_factor": 2})):
        with pytest.raises(ValueError, match="planı değişti"):
            enqueue_plan(store, project, changed, run_id=run_id)
    other = store.create_project("Other", 'strategy("Other")\na=input.int(8)')
    with pytest.raises(ValueError, match="bu stratejiye ait değil"):
        enqueue_plan(store, other, plan, run_id=run_id)
    assert store.settings(project) == before
    assert len(store.scan_runs(project)) == 1
    assert len(store.tasks(project)) == 3


def test_cancel_new_run_rolls_back_run_membership_and_settings(tmp_path):
    store, project, plan = fixture(tmp_path)
    checks = 0
    def cancel():
        nonlocal checks
        checks += 1
        return checks >= 14
    with pytest.raises(PlanCancelled):
        enqueue_plan(store, project, plan, new_run=True, cancel_requested=cancel)
    assert store.scan_runs(project) == []
    assert store.tasks(project) == []
    assert store.settings(project) is None


def test_legacy_memberships_preserve_ids_on_reopen(tmp_path):
    store, project, _plan = fixture(tmp_path)
    store.enqueue(project, "legacy", {})
    old_id = store.tasks(project)[0]["id"]
    run = store.scan_runs(project)[0]
    assert run["kind"] == "legacy" and run["source_hash"] is None
    reopened = Store(store.path)
    assert reopened.scan_runs(project) == [run]
    assert reopened.run_tasks(run["id"])[0]["id"] == old_id
    for table in ("scan_runs", "run_tasks"):
        with store.connect() as connection:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                connection.execute(f"DELETE FROM {table}")


def test_changed_source_refuses_claim_without_consuming_attempt(tmp_path):
    store, project, plan = fixture(tmp_path)
    enqueue_plan(store, project, plan, new_run=True)
    with store.connect() as connection:
        connection.execute("UPDATE projects SET pine_source='changed' WHERE id=?", (project,))
    with pytest.raises(ValueError, match="kaynağı değişti"):
        store.claim_next(1, [project])
    assert all(t["status"] == "pending" and t["attempts"] == 0 for t in store.tasks(project))


def test_cancel_after_run_insert_rolls_back_entire_admission(tmp_path, monkeypatch):
    store, project, plan = fixture(tmp_path)
    cancel = threading.Event()
    original = store.connect
    def connect():
        connection = original()
        connection.set_trace_callback(lambda sql: cancel.set() if sql.startswith("INSERT INTO scan_runs") else None)
        return connection
    monkeypatch.setattr(store, "connect", connect)
    with pytest.raises(PlanCancelled):
        enqueue_plan(store, project, plan, new_run=True, cancel_requested=cancel.is_set)
    assert cancel.is_set()
    assert store.scan_runs(project) == []
    assert store.tasks(project) == []
    assert store.settings(project) is None
