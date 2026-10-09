import pytest
from tv_scan_studio.storage import Store
from tv_scan_studio.planner import ScanPlan, enqueue_plan


def fixture(tmp_path):
    store = Store(tmp_path / "speed.db")
    project = store.create_project("EMA", 'strategy("EMA")\na=input.int(8)')
    plan = ScanPlan("sid", ("BIST:XU030D1!",), ("15",), {"in_0": list(range(1, 21))})
    enqueue_plan(store, project, plan, new_run=True)
    return store, project, plan, store.scan_runs(project)[0]["id"]


def complete(store, project, run, start, stop, monkeypatch, worker=1):
    monkeypatch.setattr("time.time", lambda: start)
    task = store.claim_next(worker, [project], run_ids=[run])
    monkeypatch.setattr("time.time", lambda: stop)
    store.complete(task.id, worker, {"trades": 1}, "elenmiş", verified=True)
    return task


def test_verified_run_scoped_rates_exclude_pause_and_other_runs(tmp_path, monkeypatch):
    store, project, plan, run = fixture(tmp_path)
    for index in range(3):
        complete(store, project, run, 1000 + index * 20, 1020 + index * 20, monkeypatch)
    for index in range(3):
        complete(store, project, run, 1200 + index * 20, 1220 + index * 20, monkeypatch)
    stats = store.run_performance(run, now=1260)
    assert stats["verified_count"] == stats["window_verified_count"] == 6
    assert stats["active_seconds"] == 120  # 140-second pause excluded
    assert stats["tests_per_hour"] == stats["average_tests_per_hour"] == 180
    assert stats["eta_seconds"] == 280
    enqueue_plan(store, project, plan, new_run=True)
    other = store.scan_runs(project)[0]["id"]
    complete(store, project, other, 1260, 1280, monkeypatch)
    assert store.run_performance(run, now=1280)["verified_count"] == 6
    assert store.run_performance(other, now=1280)["tests_per_hour"] == 0
    assert store.dashboard_stats(project)["tests_per_hour"] == 0  # no implicit cross-run speed
    stats = store.run_performance(run, now=1600)
    assert stats["tests_per_hour"] == 0 and stats["eta_seconds"] is None
    assert stats["average_tests_per_hour"] == 180


def test_parallel_intervals_not_summed_and_failed_work_consumes_time(tmp_path, monkeypatch):
    store, project, _, run = fixture(tmp_path)
    for index in range(3):
        for worker in (1, 2):
            complete(store, project, run, 1000 + index * 20, 1020 + index * 20, monkeypatch, worker)
    stats = store.run_performance(run, now=1060)
    assert stats["active_seconds"] == 60 and stats["tests_per_hour"] == 360
    monkeypatch.setattr("time.time", lambda: 1060)
    task = store.claim_next(1, [project], run_ids=[run])
    monkeypatch.setattr("time.time", lambda: 1080)
    store.fail(task.id, 1, "failure", max_attempts=1)
    stats = store.run_performance(run, now=1080)
    assert stats["verified_count"] == 6 and stats["active_seconds"] == 80
    assert stats["tests_per_hour"] == 270


def test_future_missing_and_invalidated_evidence_never_counts(tmp_path, monkeypatch):
    store, project, _, run = fixture(tmp_path)
    tasks = [complete(store, project, run, 1000+i*20, 1020+i*20, monkeypatch) for i in range(6)]
    assert store.run_performance(run, now=1010)["verified_count"] == 0
    with store.connect() as connection:
        connection.execute("UPDATE results SET verified=0 WHERE task_id=?", (tasks[0].id,))
    stats = store.run_performance(run, now=1120)
    assert stats["verified_count"] == 5 and stats["tests_per_hour"] == 150
    assert store.run_performance(None, now=1120)["tests_per_hour"] == 0


def test_open_claim_window_clipping_and_uncertain_interruption(tmp_path, monkeypatch):
    store, project, _, run = fixture(tmp_path)
    for i in range(5):
        complete(store, project, run, 1000+i*20, 1020+i*20, monkeypatch)
    monkeypatch.setattr("time.time", lambda: 1100)
    task = store.claim_next(1, [project], run_ids=[run])
    stats = store.run_performance(run, now=1160)
    assert stats["active_seconds"] == 160
    assert stats["tests_per_hour"] == pytest.approx(112.5)
    monkeypatch.setattr("time.time", lambda: 1170)
    store.recover_interrupted()
    stats = store.run_performance(run, now=1170)
    assert stats["timing_uncertain"]
    assert stats["tests_per_hour"] == stats["average_tests_per_hour"] == 0


def test_heterogeneous_costs_suppress_eta(tmp_path, monkeypatch):
    store, project, _, run = fixture(tmp_path)
    for i in range(6):
        complete(store, project, run, 1000+i*20, 1020+i*20, monkeypatch)
    with store.connect() as connection:
        connection.execute("UPDATE tasks SET payload=json_set(payload,'$.costs.commission',0.04) "
            "WHERE id=(SELECT MAX(task_id) FROM run_tasks WHERE run_id=?)", (run,))
    stats = store.run_performance(run, now=1120)
    assert stats["tests_per_hour"] == 180 and stats["eta_seconds"] is None


def test_estimate_requires_exact_source_plan_and_verified_sample(tmp_path, monkeypatch):
    from dataclasses import replace
    store, project, plan, run = fixture(tmp_path)
    assert store.observed_seconds_per_test(project, plan=plan.to_dict()) is None
    for i in range(6):
        complete(store, project, run, 1000+i*20, 1020+i*20, monkeypatch)
    assert store.observed_seconds_per_test(project) is None
    assert store.observed_seconds_per_test(project, plan=plan.to_dict()) == 20
    changed = replace(plan, timeframes=("60",))
    assert store.observed_seconds_per_test(project, plan=changed.to_dict()) is None
    with store.connect() as connection:
        connection.execute("UPDATE projects SET pine_source='changed' WHERE id=?", (project,))
    assert store.observed_seconds_per_test(project, plan=plan.to_dict()) is None


def test_recent_window_clips_long_attempt_without_importing_old_completions(tmp_path, monkeypatch):
    store, project, _, run = fixture(tmp_path)
    complete(store, project, run, 900, 1000, monkeypatch)
    for i in range(5):
        complete(store, project, run, 1200+i*20, 1220+i*20, monkeypatch)
    stats = store.run_performance(run, now=1500)
    assert stats["verified_count"] == 6 and stats["window_verified_count"] == 5
    assert stats["active_seconds"] == 200
    assert stats["window_active_seconds"] == 100
    assert stats["tests_per_hour"] == 180 and stats["average_tests_per_hour"] == 108


def test_retry_time_in_denominator_without_duplicate_success_count(tmp_path, monkeypatch):
    store, project, _, run = fixture(tmp_path)
    for i in range(4):
        complete(store, project, run, 1000+i*20, 1020+i*20, monkeypatch)
    monkeypatch.setattr("time.time", lambda: 1080)
    task = store.claim_next(1, [project], run_ids=[run])
    monkeypatch.setattr("time.time", lambda: 1100)
    store.fail(task.id, 1, "transient", max_attempts=3)
    complete(store, project, run, 1100, 1120, monkeypatch)
    stats = store.run_performance(run, now=1120)
    assert stats["verified_count"] == 5 and stats["active_seconds"] == 120
    assert stats["tests_per_hour"] == 150


@pytest.mark.parametrize("workers", [1, 2, 8])
def test_parallel_elapsed_union_at_one_two_and_eight_workers(tmp_path, monkeypatch, workers):
    store, project, _, run = fixture(tmp_path)
    waves = 8 // workers
    for wave in range(waves):
        for worker in range(1, workers + 1):
            complete(store, project, run, 1000 + wave*60, 1060 + wave*60, monkeypatch, worker)
    stats = store.run_performance(run, now=1000 + waves*60)
    assert stats["verified_count"] == 8
    assert stats["active_seconds"] == waves * 60
    assert stats["average_tests_per_hour"] == workers * 60
