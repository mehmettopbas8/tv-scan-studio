from dataclasses import replace
import pytest
from tv_scan_studio.planner import ScanPlan, iter_tasks


def test_sampling_is_seeded_unique_budgeted_and_subset_of_full_space():
    full = ScanPlan("study", ("A", "B"), ("15",), {"in_0": list(range(100))})
    sample = replace(full, method="sample", sample_budget=17, sample_seed=42)
    selected = list(iter_tasks(sample))
    assert len(selected) == sample.task_count == 17
    assert len({key for key, _ in selected}) == 17
    assert selected == list(iter_tasks(ScanPlan.from_dict(sample.to_dict())))
    assert {key for key, _ in selected} <= {key for key, _ in iter_tasks(full)}
    assert selected != list(iter_tasks(replace(sample, sample_seed=43)))
    assert full.task_count == 200


def test_huge_population_sampling_does_not_walk_cartesian_space():
    plan = ScanPlan("study", ("A",), ("15",),
                    {f"in_{i}": list(range(10)) for i in range(25)},
                    method="sample", sample_budget=3)
    assert plan.cartesian_count == 10 ** 25
    assert len(list(iter_tasks(plan))) == 3


@pytest.mark.parametrize("budget", [None, 0, -1, True, 1.5])
def test_invalid_sampling_budget(budget):
    with pytest.raises(ValueError):
        ScanPlan("study", ("A",), ("15",), {}, method="sample", sample_budget=budget).validate()


def test_budget_above_population_selects_every_task():
    full = ScanPlan("study", ("A",), ("15",), {"in_0": [7, 8, 9]})
    assert list(iter_tasks(replace(full, method="sample", sample_budget=10))) == list(iter_tasks(full))
