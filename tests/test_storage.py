from concurrent.futures import ThreadPoolExecutor
import hashlib

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
