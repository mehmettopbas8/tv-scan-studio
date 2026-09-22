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


def test_supervisor_rejects_shared_target(tmp_path):
    supervisor = WorkerSupervisor(Store(tmp_path / "studio.db"), ParallelFakeDriver())
    with pytest.raises(ValueError, match="bağımsız"):
        supervisor.start([WorkerAssignment(1, "target-1", (1,)), WorkerAssignment(2, "target-1", (1,))])


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
