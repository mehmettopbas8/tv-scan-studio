from concurrent.futures import ThreadPoolExecutor
import hashlib
import subprocess
import sys
import json

import pytest

from tv_scan_studio.storage import Store


def test_project_stores_pine_source_hash(tmp_path):
    store = Store(tmp_path / "studio.db")
    source = 'strategy("Hash")'
    project = store.create_project("Hash", source)
    assert store.project(project)["pine_hash"] == hashlib.sha256(source.encode()).hexdigest()


def test_interrupted_tasks_are_requeued(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("FTMO ICT", 'strategy("ICT")')
    store.enqueue(project, "EURUSD|15|1", {"symbol": "EURUSD"})
    with store.connect() as connection:
        connection.execute("UPDATE tasks SET status='running',worker_id=3")
    assert store.recover_interrupted() == 1
    assert store.counts(project) == {"pending": 1}


def test_process_exit_recovers_claims_without_repeating_completed_results(tmp_path):
    database = tmp_path / 'restart.db'
    script = '''
import os,sys
from tv_scan_studio.storage import Store
s=Store(sys.argv[1])
p=s.create_project('Restart','strategy("Restart")')
for key in ('finished','interrupted','waiting'): s.enqueue(p,key,{})
t=s.claim_next(1,[p])
s.complete(t.id,1,{'trades':1},'hassas',verified=True,evidence={})
assert s.claim_next(2,[p]) is not None
os._exit(17)
'''
    child = subprocess.run([sys.executable, '-c', script, str(database)],
                           capture_output=True, text=True, timeout=30)
    assert child.returncode == 17, child.stderr
    recovery = '''
import sys,json
from tv_scan_studio.storage import Store
s=Store(sys.argv[1]); recovered=s.recover_interrupted()
claimed=[]
while (t:=s.claim_next(3,[1])) is not None:
 claimed.append(t.task_key)
 s.complete(t.id,3,{'trades':1},'hassas',verified=True,evidence={})
print(json.dumps({'recovered':recovered,'claimed':claimed,'counts':s.counts(1),'results':len(s.results(1))}))
'''
    restarted = subprocess.run([sys.executable, '-c', recovery, str(database)],
                               capture_output=True, text=True, timeout=30)
    assert restarted.returncode == 0, restarted.stderr
    state = json.loads(restarted.stdout)
    assert state == {'recovered':1,'claimed':['interrupted','waiting'],
                     'counts':{'done':3},'results':3}


def test_two_workers_never_claim_the_same_task(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Parallel", 'strategy("Parallel")')
    for index in range(20):
        store.enqueue(project, str(index), {"index": index})

    def claim(worker_id):
        return store.claim_next(worker_id, [project])

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(claim, [1, 2]))

    assert all(task is not None for task in claimed)
    assert claimed[0].id != claimed[1].id
    assert store.counts(project) == {"pending": 18, "running": 2}


def test_failure_retries_then_moves_to_manual_review(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Retry", 'strategy("Retry")')
    store.enqueue(project, "one", {"symbol": "EURUSD"})

    for attempt in range(1, 4):
        task = store.claim_next(7)
        assert task.attempts == attempt
        expected = "manual_review" if attempt == 3 else "pending"
        assert store.fail(task.id, 7, f"failure {attempt}") == expected
    assert store.counts(project) == {"manual_review": 1}


def test_only_verified_running_task_can_be_completed(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Results", 'strategy("Results")')
    store.enqueue(project, "EURUSD|15", {"symbol": "EURUSD", "timeframe": "15"})
    task = store.claim_next(2)

    with pytest.raises(ValueError, match="Doğrulanmamış"):
        store.complete(task.id, 2, {"profit_factor": 1.7}, "dayanıklı", verified=False)

    store.complete(task.id, 2, {"profit_factor": 1.7}, "dayanıklı", verified=True)
    assert store.counts(project) == {"done": 1}
    results = store.results(project)
    assert results[0]["metrics"] == {"profit_factor": 1.7}
    assert results[0]["verified"] is True
    assert len(store.results(project, {"hassas", "dayanıklı"})) == 1
    assert store.results(project, {"elenmiş", "geçersiz"}) == []
    total, summary = store.task_summaries("done")
    assert total == 1
    assert summary[0]["task_key"] == "EURUSD|15"
    assert store.project(project)["status"] == "complete"


def test_project_control_retry_and_dashboard_stats(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Control", 'strategy("Control")')
    store.update_project(project, priority=7, status="queued")
    assert store.project(project)["priority"] == 7
    store.enqueue(project, "one", {"symbol": "EURUSD"})
    store.enqueue(project, "two", {"symbol": "GBPUSD"})
    task = store.claim_next(1, [project])
    store.fail(task.id, 1, "broken", max_attempts=1)
    assert store.counts(project)["manual_review"] == 1
    store.retry_task(task.id)
    assert store.counts(project)["pending"] == 2
    cancelled = store.cancel_pending(project)
    assert cancelled == 2
    stats = store.dashboard_stats(project)
    assert stats["counts"] == {"cancelled": 2}
    assert stats["tests_per_hour"] == 0
    assert stats["eta_seconds"] is None


def test_dashboard_task_browser_scopes_to_one_project_and_all_states(tmp_path):
    store = Store(tmp_path / "scoped.db")
    first = store.create_project("First", 'strategy("First")')
    second = store.create_project("Second", 'strategy("Second")')
    store.enqueue(first, "one", {"symbol": "EURUSD"})
    store.enqueue(first, "two", {"symbol": "GBPUSD"})
    store.enqueue(second, "other", {"symbol": "USDJPY"})
    store.cancel_pending(first)
    total, rows = store.task_summaries(None, project_id=first)
    assert total == 2
    assert {row["task_key"] for row in rows} == {"one", "two"}
    assert store.task_summaries("cancelled", project_id=first)[0] == 2
    assert store.task_summaries("pending", project_id=first)[0] == 0
    project = next(row for row in store.projects() if row["id"] == first)
    assert project["cancelled_count"] == 2


def test_dashboard_rate_requires_meaningful_sample(tmp_path):
    store = Store(tmp_path / "rate.db")
    project = store.create_project("Rate", 'strategy("Rate")')
    for index in range(2):
        store.enqueue(project, str(index), {})
        task = store.claim_next(1)
        store.complete(task.id, 1, {"trades": 1}, "elenmiş", verified=True)
    stats = store.dashboard_stats(project)
    assert stats["tests_per_hour"] == 0
    assert stats["eta_seconds"] is None


def test_bulk_retry_returns_recoverable_project_tasks_to_queue(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Retry", 'strategy("Retry")')
    store.enqueue(project, "one", {})
    task = store.claim_next(2, [project])
    assert task is not None
    store.fail(task.id, 2, "broken", max_attempts=1)

    assert store.retry_tasks(project) == 1
    assert store.counts(project) == {"pending": 1}
    assert store.project(project)["status"] == "queued"


def test_project_settings_merge_preserves_verified_identity(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Identity", 'strategy("Identity")')
    store.save_settings(project, {"tradingview_identity": {"pine_id": "USER;abc"}})
    store.save_settings(project, {"study_id": "sid", "symbols": ["OANDA:EURUSD"]})
    assert store.settings(project)["tradingview_identity"]["pine_id"] == "USER;abc"
    assert store.settings(project)["study_id"] == "sid"


def test_paused_project_is_not_claimed(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Paused", 'strategy("Paused")')
    store.enqueue(project, "one", {})
    store.update_project(project, status="paused")
    assert store.claim_next(1, [project]) is None
    store.update_project(project, status="queued")
    assert store.claim_next(1, [project]) is not None
