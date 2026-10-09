import json
import sqlite3
import pytest
from tv_scan_studio.storage import Store, SCHEMA


def task_store(tmp_path):
    store = Store(tmp_path / "history.db")
    project = store.create_project("EMA", 'strategy("EMA")\na=input.int(8)')
    store.enqueue(project, "one", {"inputs": {"in_0": 8}})
    return store, project


def test_attempts_recovery_and_results_preserve_source_at_claim(tmp_path):
    store, project = task_store(tmp_path)
    first = store.claim_next(1, [project])
    store.fail(first.id, 1, "temporary")
    second = store.claim_next(2, [project])
    assert second.id == first.id and second.attempts == 2
    assert store.recover_interrupted() == 1
    third = store.claim_next(3, [project])
    with store.connect() as connection:
        connection.execute("UPDATE projects SET pine_source=? WHERE id=?", ('strategy("Changed")', project))
    store.complete(third.id, 3, {"profit_factor": 1.5}, "aday", verified=True,
                   evidence={"tradingview_warning_state": "absent"})
    events = store.attempt_history(first.id)
    assert [e["event"] for e in events] == ["claimed", "failed", "claimed", "interrupted", "claimed", "completed"]
    assert [e["attempt_number"] for e in events] == [1, 1, 2, 2, 3, 3]
    result = store.result_history(first.id)[0]
    assert result["source_snapshot"] == 'strategy("EMA")\na=input.int(8)'
    assert result["source_provenance"] == "claim_snapshot"
    assert result["warning_state"] == "absent"
    assert result["attempt_number"] == 3


def test_reexecution_keeps_previous_result_and_history_is_immutable(tmp_path):
    store, project = task_store(tmp_path)
    task = store.claim_next(1, [project])
    store.complete(task.id, 1, {"trades": 10}, "aday", verified=True)
    before = store.result_history(task.id)[0]
    with store.connect() as connection:
        connection.execute("UPDATE tasks SET status='pending' WHERE id=?", (task.id,))
    store.claim_next(2, [project])
    store.invalidate(task.id, 2, "wrong inputs", {"trades": 2}, {})
    results = store.result_history(task.id)
    assert results[0] == before
    assert len(results) == 2 and results[1]["verified"] == 0
    assert [r["warning_state"] for r in results] == ["unknown", "unknown"]
    assert store.results(project)[0]["classification"] == "geçersiz"
    for table in ("result_history", "attempt_history"):
        with store.connect() as connection:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                connection.execute(f"DELETE FROM {table}")
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                connection.execute(f"UPDATE {table} SET task_id=task_id")


def test_legacy_migration_preserves_ids_and_is_idempotent(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO projects(id,name,pine_source,created_at,updated_at) VALUES(100,'Old','strategy(\"Old\")',1,1)")
        connection.execute("INSERT INTO tasks(id,project_id,task_key,payload,status,attempts,updated_at) VALUES(200,100,'old','{}','done',3,1)")
        connection.execute("INSERT INTO results VALUES(200,100,?,'aday',1,1)", (json.dumps({"profit_factor": float('inf')}),))
    store = Store(path)
    assert store.tasks(100)[0]["id"] == 200
    result = store.result_history(200)[0]
    assert result["source_provenance"] == "legacy_source_unverified"
    assert result["source_snapshot"] == ""
    assert result["warning_state"] == "unknown"
    assert result["metrics"]["profit_factor"] == float('inf')
    assert store.attempt_history(200) == []  # Old attempts are unknown, not reconstructed.
    reopened = Store(path)
    assert reopened.result_history(200) == [result]


def test_invalid_warning_state_rolls_back_completion_and_history(tmp_path):
    store, project = task_store(tmp_path)
    task = store.claim_next(1, [project])
    with pytest.raises(ValueError, match="uyarı durumu"):
        store.complete(task.id, 1, {}, "aday", verified=True,
                       evidence={"tradingview_warning_state": "probably absent"})
    assert store.result_history(task.id) == []
    assert [event["event"] for event in store.attempt_history(task.id)] == ["claimed"]
    assert store.counts(project) == {"running": 1}
    assert store.results(project) == []


def test_policy_reevaluation_preserves_test_and_original_result(tmp_path):
    store, project = task_store(tmp_path)
    task = store.claim_next(1, [project])
    metrics = {"trades": 100, "profit_factor": 1.5, "win_rate_pct": 50,
               "net_profit": 100, "max_drawdown_pct": 2}
    store.complete(task.id, 1, metrics, "hassas", verified=True)
    frozen = store.result_history(task.id)[0]
    task_rows = store.tasks(project)
    strict = store.reevaluate_result(frozen["id"], {"min_profit_factor": 2})
    lenient = store.reevaluate_result(frozen["id"], {"min_profit_factor": 1})
    assert store.reevaluate_result(frozen["id"], {"min_profit_factor": 2}) == strict
    evaluations = store.result_evaluations(frozen["id"])
    assert len(evaluations) == 3
    assert next(row for row in evaluations if row["id"] == strict)["classification"] == "elenmiş"
    assert next(row for row in evaluations if row["id"] == lenient)["classification"] == "hassas"
    assert store.result_history(task.id) == [frozen]
    assert store.tasks(project) == task_rows
    assert store.results(project)[0]["classification"] == "hassas"
    for table in ("evaluation_policies", "result_evaluations"):
        with store.connect() as connection:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                connection.execute(f"DELETE FROM {table}")


def test_invalid_policy_does_not_create_evaluation(tmp_path):
    store, project = task_store(tmp_path)
    task = store.claim_next(1, [project])
    store.invalidate(task.id, 1, "wrong inputs", {}, {})
    result = store.result_history(task.id)[0]
    before = store.result_evaluations(result["id"])
    for policy in ({"unknown": 3}, {"min_profit_factor": float('nan')}, {"min_trades": True},
                   {"max_drawdown_pct_exclusive": 101}):
        with pytest.raises(ValueError):
            store.reevaluate_result(result["id"], policy)
    assert store.result_evaluations(result["id"]) == before
    identifier = store.reevaluate_result(result["id"], {"min_profit_factor": 1})
    assert next(row for row in store.result_evaluations(result["id"]) if row["id"] == identifier)["classification"] == "geçersiz"
