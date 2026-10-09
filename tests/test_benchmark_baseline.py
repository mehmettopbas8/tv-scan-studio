import json
import sqlite3
from copy import deepcopy

import pytest

from tv_scan_studio.benchmark import BaselineObserver, import_baseline_observation, _hash, load_record, serialize_record


def old_database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE projects(id INTEGER, pine_source TEXT);
        CREATE TABLE tasks(id INTEGER,project_id INTEGER,status TEXT,attempts INTEGER,
                           worker_id INTEGER,started_at REAL,finished_at REAL,payload TEXT);
        CREATE TABLE results(task_id INTEGER,verified INTEGER,metrics TEXT);
        CREATE TABLE verification_evidence(task_id INTEGER,evidence TEXT);
    """)
    db.execute("INSERT INTO projects VALUES(1,?)", ('strategy("EMA")',))
    for task in range(1, 9):
        db.execute("INSERT INTO tasks VALUES(?,1,'pending',0,NULL,NULL,NULL,?)", (task,
            json.dumps({"symbol": "BIST:XU030D1!", "timeframe": "15", "inputs": {"in_0": task}})))
    return db


def finished_observer(db):
    observer = BaselineObserver(db, 1, list(range(1, 9)))
    observer.poll(db, observed_at=900)
    db.execute("UPDATE tasks SET status='running',attempts=1,worker_id=id,started_at=1000")
    observer.poll(db, observed_at=1010)
    db.execute("UPDATE tasks SET status='done',finished_at=1080")
    for task in range(1, 9):
        db.execute("INSERT INTO results VALUES(?,1,?)", (task, '{"trades":1}'))
        payload = db.execute("SELECT payload FROM tasks WHERE id=?", (task,)).fetchone()[0]
        db.execute("INSERT INTO verification_evidence VALUES(?,?)", (task, payload))
    observer.poll(db, observed_at=1090)
    return observer


def test_legacy_observer_reads_only_and_keeps_versioned_evidence(tmp_path):
    db = old_database()
    observer = finished_observer(db)
    before = db.total_changes
    manifest = observer.manifest()
    artifact = tmp_path / "native-proof.txt"
    artifact.write_text("synthetic test fixture NOT native acceptance")
    context = dict(machine="same", tradingview_version="same", account_tier="same", protocol="same")
    record = import_baseline_observation(manifest, workers=8, build_sha256="a" * 64,
        context=context, evidence_paths=[artifact])
    assert db.total_changes == before
    assert record["active_seconds"] == 80 and record["peak_concurrency"] == 8
    assert record["verified_count"] == 8 and record["acceptance"] is False
    assert record["eligible_for_review"]
    assert load_record(serialize_record(record)) == record
    assert "pine_source" not in json.dumps(manifest)


def test_completed_legacy_database_cannot_retroactively_be_observed():
    db = old_database()
    db.execute("UPDATE tasks SET status='done',attempts=1,started_at=1000,finished_at=1080")
    with pytest.raises(ValueError, match="önce"):
        BaselineObserver(db, 1, list(range(1, 9)))


def test_missed_claim_transition_fails_closed():
    db = old_database()
    observer = BaselineObserver(db, 1, list(range(1, 9)))
    db.execute("UPDATE tasks SET status='done',attempts=1,started_at=1000,finished_at=1080")
    with pytest.raises(ValueError, match="gözlenmeyen"):
        observer.poll(db, observed_at=1090)


@pytest.mark.parametrize("mutation", ["source", "payload", "time", "result"])
def test_changed_evidence_rejects(mutation):
    db = old_database()
    observer = finished_observer(db)
    if mutation == "source":
        db.execute("UPDATE projects SET pine_source='different'")
    elif mutation == "payload":
        db.execute("UPDATE tasks SET payload='{}' WHERE id=1")
    elif mutation == "time":
        db.execute("UPDATE tasks SET finished_at=1081 WHERE id=1")
    else:
        db.execute("UPDATE results SET metrics='{}' WHERE task_id=1")
    with pytest.raises(ValueError):
        observer.poll(db, observed_at=1100)


def test_manifest_tamper_and_incomplete_reject(tmp_path):
    db = old_database()
    observer = BaselineObserver(db, 1, list(range(1, 9)))
    with pytest.raises(ValueError, match="bütünüyle"):
        observer.manifest()
    manifest = finished_observer(db).manifest()
    manifest["task_count"] = 99
    with pytest.raises(ValueError, match="manifest"):
        import_baseline_observation(manifest, workers=8, build_sha256="a" * 64, context={}, evidence_paths=[])


@pytest.mark.parametrize("change", ["proof", "final", "gap", "overlap", "bool_count", "bool_time"])
def test_rehashed_contradictory_manifest_still_rejects(change):
    manifest = finished_observer(old_database()).manifest()
    if change == "proof":
        manifest["results"][1]["result_hash"] = "not-a-sha"
    elif change == "final":
        manifest["intervals"][0]["outcome"] = "failed"
    elif change == "gap":
        manifest["intervals"][0]["attempt"] = 2
    elif change == "overlap":
        extra = deepcopy(manifest["intervals"][0])
        manifest["intervals"][0]["outcome"] = "pending"
        extra["attempt"] = 2
        manifest["intervals"].append(extra)
    elif change == "bool_count":
        manifest["task_count"] = True
    else:
        manifest["last_poll"] = True
    manifest["manifest_hash"] = _hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
    with pytest.raises(ValueError):
        import_baseline_observation(manifest, workers=8, build_sha256="a" * 64,
            context=dict(machine="same", tradingview_version="same", account_tier="same", protocol="same"), evidence_paths=[])


@pytest.mark.parametrize("status", ["running", "pending", "failed"])
def test_completed_observed_task_cannot_revert(status):
    db = old_database()
    observer = finished_observer(db)
    db.execute("UPDATE tasks SET status=? WHERE id=1", (status,))
    with pytest.raises(ValueError):
        observer.poll(db, observed_at=1100)


def test_attempt_cannot_advance_before_previous_terminal_observed():
    db = old_database()
    observer = BaselineObserver(db, 1, list(range(1, 9)))
    db.execute("UPDATE tasks SET status='running',attempts=1,worker_id=id,started_at=1000")
    observer.poll(db, observed_at=1010)
    db.execute("UPDATE tasks SET attempts=2,started_at=1020 WHERE id=1")
    with pytest.raises(ValueError, match="Yeni deneme"):
        observer.poll(db, observed_at=1030)


@pytest.mark.parametrize("table", ["results", "verification_evidence"])
def test_completed_result_evidence_disappearance_rejects(table):
    db = old_database()
    observer = finished_observer(db)
    db.execute(f"DELETE FROM {table} WHERE task_id=1")
    with pytest.raises(ValueError, match="eksik"):
        observer.poll(db, observed_at=1100)


def test_old_observer_and_current_run_compare_same_workload_without_live_promotion(tmp_path, monkeypatch):
    """Six synthetic records test interoperability, never benchmark performance."""
    from tv_scan_studio.benchmark import capture_run, compare_records
    from tv_scan_studio.planner import ScanPlan, enqueue_plan, iter_tasks
    from tv_scan_studio.storage import Store

    source = 'strategy("EMA")\nfast=input.int(8,"Fast EMA")'
    context = dict(machine="fixture", tradingview_version="fixture", account_tier="fixture", protocol="fixture")
    proof = tmp_path / "synthetic-proof.txt"
    proof.write_text("Synthetic fixture; not native or live performance evidence.")
    baseline, candidate = [], []
    for workers in (1, 2, 8):
        plan = ScanPlan("new-study", ("BIST:XU030D1!",), ("15",), {"in_0": list(range(1, 9))},
            date_range={"from": "2026-09-07", "to": "2026-09-18"},
            costs={"assumptions": {"initial_capital": 1000000, "commission_value": .01}})
        db = old_database()
        db.execute("UPDATE projects SET pine_source=?", (source,))
        for task_id, (_, payload) in enumerate(iter_tasks(plan), 1):
            # Runtime study identity and policy can differ without changing a test.
            payload = {**payload, "study_id": "old-study", "criteria": {"profit_factor": 1.4}}
            db.execute("UPDATE tasks SET payload=? WHERE id=?", (json.dumps(payload), task_id))
        observer = BaselineObserver(db, 1, list(range(1, 9)))
        current = Store(tmp_path / f"current-{workers}.db")
        project = current.create_project("EMA", source)
        _, run_id = enqueue_plan(current, project, plan, new_run=True, return_run_id=True)
        for batch in range(8 // workers):
            start = 1000 + batch * 80
            monkeypatch.setattr("time.time", lambda: start)
            claimed = []
            for worker in range(1, workers + 1):
                task = current.claim_next(worker, [project], run_ids=[run_id])
                claimed.append(task)
                db.execute("UPDATE tasks SET status='running',attempts=1,worker_id=?,started_at=? WHERE id=?",
                    (worker, start, task.id))
            observer.poll(db, observed_at=start + 1)
            monkeypatch.setattr("time.time", lambda: start + 80)
            for worker, task in enumerate(claimed, 1):
                current.complete(task.id, worker, {"trades": 1}, "elenmiş", verified=True)
                db.execute("UPDATE tasks SET status='done',finished_at=? WHERE id=?", (start + 80, task.id))
                db.execute("INSERT INTO results VALUES(?,1,?)", (task.id, '{"trades":1}'))
                payload = db.execute("SELECT payload FROM tasks WHERE id=?", (task.id,)).fetchone()[0]
                db.execute("INSERT INTO verification_evidence VALUES(?,?)", (task.id, payload))
            observer.poll(db, observed_at=start + 80)
        baseline.append(import_baseline_observation(observer.manifest(), workers=workers,
            build_sha256="a" * 64, context=context, evidence_paths=[proof]))
        with current.connect() as connection:
            candidate.append(capture_run(connection, run_id, workers=workers, build_sha256="b" * 64,
                context=context, provenance="real_tradingview", evidence_paths=[proof], now=2000))
        db.close()
    report = compare_records(baseline, candidate)
    assert [row["ratio"] for row in report["rows"]] == [1, 1, 1]
    assert report["performance_gate"] == "open"
    assert not report["live_evidence_reviewed"]
    assert len({record["source_hash"] for record in baseline + candidate}) == 1
    assert len({record["workload_hash"] for record in baseline + candidate}) == 1
    assert all(record["acceptance"] is False for record in baseline + candidate)
