from dataclasses import replace
import pytest
from tv_scan_studio.planner import ScanPlan, PlanCancelled, iter_tasks, enqueue_plan
from tv_scan_studio.storage import Store


def plan():
    return ScanPlan("study", ("A",), ("15",), {"left": list(range(100)), "right": list(range(100))})


@pytest.mark.parametrize("method", ["cartesian", "sample"])
def test_cancel_constrained_generation_even_when_no_task_is_eligible(method):
    value = replace(plan(), method=method, sample_budget=3,
                    constraints=[{"left": "left", "operator": ">", "right": "right"}])
    checks = 0
    def cancel():
        nonlocal checks
        checks += 1
        return checks >= 20
    with pytest.raises(PlanCancelled):
        list(iter_tasks(value, cancel_requested=cancel))
    assert checks == 20


def test_count_cancellation_and_progress():
    value = replace(plan(), constraints=[{"left": "left", "operator": "<", "right": "right"}])
    reports = []
    with pytest.raises(PlanCancelled):
        value.count_eligible(cancel_requested=lambda: bool(reports), progress=lambda *counts: reports.append(counts))
    assert reports[0][0] == 256


def test_cancel_admission_rolls_back_tasks_and_settings(tmp_path):
    store = Store(tmp_path / "cancel.db")
    project = store.create_project("Legacy", 'strategy("Legacy")')
    store.save_settings(project, {"old": "keep"})
    checks = 0
    def cancel():
        nonlocal checks
        checks += 1
        return checks >= 12
    with pytest.raises(PlanCancelled):
        enqueue_plan(store, project, plan(), cancel_requested=cancel)
    assert store.tasks(project) == []
    assert store.settings(project) == {"old": "keep"}
