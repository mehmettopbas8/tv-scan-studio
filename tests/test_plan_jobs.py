import os
import time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from tv_scan_studio.plan_jobs import PlanCountJob, PlanCountController
from tv_scan_studio.planner import ScanPlan


def wait_until(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert predicate()


def test_snapshot_and_exact_counts():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    plan = ScanPlan("study", ("A",), ("15",), {"fast": [7, 8, 9], "slow": [8, 9]},
                    constraints=[{"left": "fast", "operator": "<", "right": "slow"}])
    job = PlanCountJob(plan, 1)
    plan.input_values["fast"].clear()
    results = []
    job.result.connect(results.append)
    job.start()
    wait_until(app, lambda: bool(results) and not job.isRunning())
    assert results == [{"revision": 1, "status": "ready", "before": 6, "skipped": 3, "remaining": 3, "tasks": 3}]


def test_cancel_keeps_qt_events_responsive_and_stale_results_are_ignored():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = PlanCountController()
    results, ticks = [], []
    controller.result.connect(results.append)
    timer = QtCore.QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(1)
    big = ScanPlan("study", ("A",), ("15",), {"a": list(range(10000)), "b": list(range(10000))},
                   constraints=[{"left": "a", "operator": "<", "right": "b"}])
    controller.start(big)
    wait_until(app, lambda: len(ticks) >= 3)
    controller.cancel()
    wait_until(app, lambda: bool(results) and not controller.jobs)
    assert results[-1]["status"] == "cancelled"
    revision = controller.start(ScanPlan("study", ("A",), ("15",), {}))
    controller.deliver({"revision": revision - 1, "status": "ready", "tasks": 999})
    wait_until(app, lambda: not controller.jobs)
    assert results[-1]["tasks"] == 1
    assert all(value.get("tasks") != 999 for value in results)
    timer.stop()
