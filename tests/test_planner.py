from itertools import islice

import pytest

from tv_scan_studio.planner import ScanPlan, enqueue_plan, iter_tasks
from tv_scan_studio.storage import Store


def plan():
    return ScanPlan(
        study_id="abc123", symbols=("OANDA:EURUSD", "OANDA:GBPUSD"),
        timeframes=("15", "1H"), input_values={"in_0": [10, 20], "in_1": [True, False]},
        date_range={"from": "2025-01-01", "to": "2025-12-31"},
        criteria={"min_trades": 60, "min_profit_factor": 1.4},
    )


def test_plan_count_and_lazy_task_generation():
    value = plan()
    assert value.task_count == 16
    first_two = list(islice(iter_tasks(value), 2))
    assert len(first_two) == 2
    assert first_two[0][0] != first_two[1][0]
    assert first_two[0][1]["date_range"]["from"] == "2025-01-01"


def test_enqueue_is_idempotent_and_settings_round_trip(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Plan", 'strategy("Plan")')
    value = plan()
    assert enqueue_plan(store, project, value) == 16
    assert enqueue_plan(store, project, value) == 0
    assert store.counts(project) == {"pending": 16}
    assert ScanPlan.from_dict(store.settings(project)).task_count == 16


def test_invalid_plan_is_rejected():
    with pytest.raises(ValueError, match="sembol"):
        ScanPlan("study", (), ("15",), {}).validate()
