from dataclasses import replace
import pytest
from tv_scan_studio.planner import ScanPlan, iter_tasks


def constrained(op="<"):
    return ScanPlan("study", ("A", "B"), ("15",), {"fast": [7, 8, 9], "slow": [8, 9]},
                    constraints=[{"left": "fast", "operator": op, "right": "slow"}])


@pytest.mark.parametrize("op,remaining", [("<", 6), ("<=", 10), (">", 2), (">=", 6)])
def test_constraint_counts_and_generation_agree(op, remaining):
    plan = constrained(op)
    assert plan.constraint_counts() == {"before": 12, "skipped": 12-remaining, "remaining": remaining}
    tasks = list(iter_tasks(plan))
    assert len(tasks) == plan.task_count == remaining
    assert all(plan.accepts_inputs(payload["inputs"]) for _, payload in tasks)


def test_sampling_selects_only_valid_tasks_reproducibly():
    plan = replace(constrained(), method="sample", sample_budget=4, sample_seed=23)
    assert len(list(iter_tasks(plan))) == 4
    assert list(iter_tasks(plan)) == list(iter_tasks(ScanPlan.from_dict(plan.to_dict())))
    assert all(plan.accepts_inputs(payload["inputs"]) for _, payload in iter_tasks(plan))


@pytest.mark.parametrize("change", [
    {"operator": "=="}, {"right": "missing"}, {"right": "fast"},
])
def test_invalid_rule_rejected(change):
    plan = constrained()
    with pytest.raises(ValueError):
        replace(plan, constraints=[{**plan.constraints[0], **change}]).validate()


def test_boolean_relationship_is_rejected():
    with pytest.raises(ValueError):
        replace(constrained(), input_values={"fast": [True], "slow": [9]}).validate()
