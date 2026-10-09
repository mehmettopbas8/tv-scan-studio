import threading
import sys
import traceback
from dataclasses import asdict

import pytest

from tv_scan_studio.storage import Store
from tv_scan_studio.supervisor import WorkerAssignment, WorkerState, WorkerSupervisor
from tv_scan_studio.tradingview import StrategySnapshot


class ParallelFakeDriver:
    def targets(self): return ["target-1", "target-2"]

    def configure(self, target_id, study_id, symbol, timeframe, inputs): pass

    def snapshot(self, target_id, study_id):
        return StrategySnapshot(
            symbol="OANDA:EURUSD", timeframe="15", status_type=2,
            inputs={"in_0": 20},
            metrics={"trades": 100, "profit_factor": 1.5, "win_rate_pct": 45,
                     "max_drawdown_pct": 4, "net_profit": 1000}, period={},
        )


def test_worker_run_scope_leaves_other_run_pending(tmp_path):
    from tv_scan_studio.planner import ScanPlan, enqueue_plan
    store = Store(tmp_path / "run-scope.db")
    project = store.create_project("Parallel", 'strategy("Parallel")\na=input.int(20)')
    plan = ScanPlan("sid", ("OANDA:EURUSD",), ("15",), {"in_0": [20]},
                    poll_interval=.001, timeout=1, stable_reads=1)
    enqueue_plan(store, project, plan, new_run=True)
    old_run = store.scan_runs(project)[0]["id"]
    enqueue_plan(store, project, plan, new_run=True)
    selected_run = store.scan_runs(project)[0]["id"]
    supervisor = WorkerSupervisor(store, ParallelFakeDriver(), heartbeat_seconds=.01)
    supervisor.start([WorkerAssignment(1, "target-1", (project,), "sid", (selected_run,))], stop_when_idle=True)
    assert supervisor.wait(5)
    assert supervisor.states[1].completed == 1
    assert store.run_tasks(old_run)[0]["status"] == "pending"
    assert store.run_tasks(selected_run)[0]["status"] == "done"


def test_two_independent_workers_drain_queue(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Parallel", 'strategy("Parallel")')
    payload = {"study_id": "sid", "symbol": "OANDA:EURUSD", "timeframe": "15",
               "inputs": {"in_0": 20}, "poll_interval": 0, "timeout": 1,
               "criteria": {"min_trades": 60}}
    for index in range(8): store.enqueue(project, str(index), payload)
    supervisor = WorkerSupervisor(store, ParallelFakeDriver(), heartbeat_seconds=0.01)
    supervisor.start([
        WorkerAssignment(1, "target-1", (project,), "sid-one"),
        WorkerAssignment(2, "target-2", (project,), "sid-two"),
    ], stop_when_idle=True)
    assert supervisor.wait(5)
    assert store.counts(project) == {"done": 8}
    assert sum(state.completed for state in supervisor.states.values()) == 8
    assert all(state.completed > 0 for state in supervisor.states.values())


def test_workers_only_process_their_assigned_projects(tmp_path):
    store = Store(tmp_path / "assigned-projects.db")
    first = store.create_project("First", 'strategy("First")')
    second = store.create_project("Second", 'strategy("Second")')
    unassigned = store.create_project("Unassigned", 'strategy("Unassigned")')
    payload = {"study_id": "sid", "symbol": "OANDA:EURUSD", "timeframe": "15",
               "inputs": {"in_0": 20}, "poll_interval": 0, "timeout": 1, "stable_reads": 1,
               "criteria": {"min_trades": 60}}
    # Assignment isolation is not a disk-throughput benchmark. Two tasks still
    # prove repeated claims without tying correctness to eight fsync-heavy jobs.
    for index in range(2):
        store.enqueue(first, f"first-{index}", payload)
        store.enqueue(second, f"second-{index}", payload)
        store.enqueue(unassigned, f"unassigned-{index}", payload)
    supervisor = WorkerSupervisor(store, ParallelFakeDriver(), heartbeat_seconds=0.01)
    supervisor.start([
        WorkerAssignment(1, "target-1", (first,), "sid-one"),
        WorkerAssignment(2, "target-2", (second,), "sid-two"),
    ], stop_when_idle=True)
    try:
        finished = supervisor.wait(5)
        frames = sys._current_frames()
        diagnostics = {
            "states": {key: asdict(value) for key, value in supervisor.states.items()},
            "threads": [{"name": thread.name, "alive": thread.is_alive(),
                         "stack": ''.join(traceback.format_stack(frames[thread.ident]))
                         if thread.ident in frames else "terminated"}
                        for thread in supervisor._threads],
        }
        assert finished, diagnostics
    finally:
        if supervisor.running:
            supervisor.request_stop()
            assert supervisor.wait(5), "Worker did not terminate after cancellation"
    assert store.counts(first) == {"done": 2}
    assert store.counts(second) == {"done": 2}
    assert store.counts(unassigned) == {"pending": 2}
    assert all(row['attempts'] == 0 for row in store.tasks(unassigned))
    assert supervisor.states[1].completed == 2
    assert supervisor.states[2].completed == 2
    assert all(state.status == 'idle' and state.error is None and state.attempts == 2
               for state in supervisor.states.values())
    assert {row["evidence"]["target_id"] for row in store.results(first)} == {"target-1"}
    assert {row["evidence"]["target_id"] for row in store.results(second)} == {"target-2"}


def test_supervisor_rejects_shared_target(tmp_path):
    supervisor = WorkerSupervisor(Store(tmp_path / "studio.db"), ParallelFakeDriver())
    with pytest.raises(ValueError, match="bağımsız"):
        supervisor.start([WorkerAssignment(1, "target-1", (1,)), WorkerAssignment(2, "target-1", (1,))])


def test_request_stop_is_nonblocking_and_preserves_next_task(tmp_path):
    import time
    entered, release = threading.Event(), threading.Event()
    class SlowDriver(ParallelFakeDriver):
        def configure(self, *args):
            entered.set()
            assert release.wait(5)
    store = Store(tmp_path / "stop.db")
    project = store.create_project("Stop", 'strategy("Stop")')
    payload = {"study_id": "sid", "symbol": "OANDA:EURUSD", "timeframe": "15",
               "inputs": {"in_0": 20}, "poll_interval": 0, "timeout": 1}
    for key in ("current", "next"):
        store.enqueue(project, key, payload)
    supervisor = WorkerSupervisor(store, SlowDriver())
    try:
        supervisor.start([WorkerAssignment(1, "target-1", (project,))])
        assert entered.wait(3)
        before = time.monotonic()
        supervisor.request_stop()
        supervisor.request_stop()
        assert time.monotonic() - before < 0.2
        assert supervisor.running and supervisor.stopping
        assert supervisor.states[1].status == "stopping"
        assert not supervisor.wait(0)
        assert supervisor.restart_failed() == []
        assert store.counts(project) == {"running": 1, "pending": 1}
    finally:
        release.set()
        assert supervisor.wait(5)
    assert not supervisor.stopping
    assert supervisor.stop_requested
    assert supervisor.states[1].status == "stopped"
    assert store.counts(project) == {"done": 1, "pending": 1}
    assert store.tasks(project, "pending")[0]["attempts"] == 0


def test_stop_during_target_guard_does_not_claim_a_task(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def slow_guard(_target):
        entered.set()
        assert release.wait(5)
    store = Store(tmp_path / "guard-stop.db")
    project = store.create_project("Stop", 'strategy("Stop")')
    store.enqueue(project, "waiting", {})
    supervisor = WorkerSupervisor(store, ParallelFakeDriver(), target_guard=slow_guard)
    try:
        supervisor.start([WorkerAssignment(1, "target-1", (project,))])
        assert entered.wait(3)
        supervisor.request_stop()
    finally:
        release.set()
        assert supervisor.wait(5)
    assert store.counts(project) == {"pending": 1}
    assert store.tasks(project)[0]["attempts"] == 0


@pytest.mark.parametrize("failures", [1, 3])
def test_retry_attempts_do_not_inflate_completed_tests(tmp_path, failures):
    class RetryDriver(ParallelFakeDriver):
        calls = 0

        def configure(self, *args):
            self.calls += 1
            if self.calls <= failures:
                raise RuntimeError("temporary failure")

    store = Store(tmp_path / "retry.db")
    project = store.create_project("Retry", 'strategy("Retry")')
    store.enqueue(project, "one-test", {
        "study_id": "sid", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20}, "poll_interval": 0, "timeout": 1,
    })
    supervisor = WorkerSupervisor(store, RetryDriver())
    supervisor.start([WorkerAssignment(1, "target-1", (project,))], stop_when_idle=True)
    assert supervisor.wait(5)
    state = supervisor.states[1]
    assert state.attempts == (2 if failures == 1 else 3)
    assert state.completed == (1 if failures == 1 else 0)
    assert store.counts(project) == ({"done": 1} if failures == 1 else {"manual_review": 1})


def test_changed_layout_stops_worker_without_claiming_task(tmp_path):
    store = Store(tmp_path / "guarded.db")
    project = store.create_project("Guarded", 'strategy("Guarded")')
    store.enqueue(project, "pending-task", {
        "study_id": "sid", "symbol": "OANDA:EURUSD", "timeframe": "15",
        "inputs": {"in_0": 20}})
    def guard(_target_id):
        raise ValueError("layout changed")
    supervisor = WorkerSupervisor(store, ParallelFakeDriver(), target_guard=guard)
    supervisor.start([WorkerAssignment(1, "target-1", (project,))], stop_when_idle=True)
    assert supervisor.wait(5)
    assert supervisor.states[1].status == "failed"
    assert store.counts(project) == {"pending": 1}
    assert store.tasks(project_id=project)[0]["attempts"] == 0


def test_supervisor_restarts_terminal_failed_worker_at_most_three_times(tmp_path, monkeypatch):
    store = Store(tmp_path / "studio.db")
    supervisor = WorkerSupervisor(store, ParallelFakeDriver(), heartbeat_seconds=0)
    assignment = WorkerAssignment(1, "target-1", ())
    supervisor.states[1] = state = WorkerState(1, "target-1", status="failed")
    supervisor._assignments[1] = (assignment, True)

    started = []
    monkeypatch.setattr(supervisor, "_start_thread", lambda item, stop: started.append((item, stop)))
    for expected in range(1, 4):
        state.status = "failed"
        assert supervisor.restart_failed() == [1]
        assert state.restarts == expected
    state.status = "failed"
    assert supervisor.restart_failed() == []
    assert len(started) == 3


def test_worker_initialization_failure_is_terminal_and_preserves_queue(tmp_path, monkeypatch):
    store = Store(tmp_path / 'init-failure.db')
    project = store.create_project('Init', 'strategy("Init")')
    store.enqueue(project, 'pending', {})
    def broken_worker(*args, **kwargs):
        raise ValueError('synthetic initialization failure')
    monkeypatch.setattr('tv_scan_studio.supervisor.ScanWorker', broken_worker)
    supervisor = WorkerSupervisor(store, ParallelFakeDriver())
    supervisor.start([WorkerAssignment(1, 'target-1', (project,))], stop_when_idle=True)
    assert supervisor.wait(5)
    assert not supervisor.running
    state = supervisor.states[1]
    assert state.status == 'failed'
    assert state.error == 'synthetic initialization failure'
    assert state.completed == state.attempts == 0
    assert store.counts(project) == {'pending': 1}
    assert store.tasks(project)[0]['attempts'] == 0
    assert store.events()[0]['message'] == state.error
