import threading

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
    payload = {"study_id": "sid", "symbol": "OANDA:EURUSD", "timeframe": "15",
               "inputs": {"in_0": 20}, "poll_interval": 0, "timeout": 1,
               "criteria": {"min_trades": 60}}
    for index in range(4):
        store.enqueue(first, f"first-{index}", payload)
        store.enqueue(second, f"second-{index}", payload)
    supervisor = WorkerSupervisor(store, ParallelFakeDriver(), heartbeat_seconds=0.01)
    supervisor.start([
        WorkerAssignment(1, "target-1", (first,), "sid-one"),
        WorkerAssignment(2, "target-2", (second,), "sid-two"),
    ], stop_when_idle=True)
    assert supervisor.wait(5)
    assert store.counts(first) == {"done": 4}
    assert store.counts(second) == {"done": 4}
    assert supervisor.states[1].completed == 4
    assert supervisor.states[2].completed == 4
    assert {row["evidence"]["target_id"] for row in store.results(first)} == {"target-1"}
    assert {row["evidence"]["target_id"] for row in store.results(second)} == {"target-2"}


def test_supervisor_rejects_shared_target(tmp_path):
    supervisor = WorkerSupervisor(Store(tmp_path / "studio.db"), ParallelFakeDriver())
    with pytest.raises(ValueError, match="bağımsız"):
        supervisor.start([WorkerAssignment(1, "target-1", (1,)), WorkerAssignment(2, "target-1", (1,))])


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
