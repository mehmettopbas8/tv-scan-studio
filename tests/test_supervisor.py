import threading

import pytest

from tv_scan_studio.storage import Store
from tv_scan_studio.supervisor import WorkerAssignment, WorkerSupervisor
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
