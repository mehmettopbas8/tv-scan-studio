from dataclasses import replace
import pytest
from tv_scan_studio.planner import ScanPlan, enqueue_plan
from tv_scan_studio.storage import Store


@pytest.mark.parametrize("change", [
    {"input_values": {"in_0": [10]}},
    {"input_values": {"in_0": [8.0]}},
    {"input_values": {"in_0": [True]}},
    {"input_values": {"in_0": [float("nan")]}},
    {"input_values": {"in_99": [8]}},
    {"input_values": {}, "variants": [{"in_0": 10}]},
    {"costs": {"tradingview_inputs": {"in_0": 10}}},
])
def test_invalid_source_value_does_not_save_settings_or_enqueue(tmp_path, change):
    store = Store(tmp_path / "validation.db")
    project = store.create_project("EMA", 'strategy("EMA")\nema = input.int(8, "Fast EMA", minval=7, maxval=9, step=1)')
    store.save_settings(project, {"original": True})
    plan = ScanPlan("study", ("BIST:XU030D1!",), ("15",), {"in_0": [7, 8, 9]})
    with pytest.raises(ValueError):
        enqueue_plan(store, project, replace(plan, **change))
    assert store.settings(project) == {"original": True}
    assert store.tasks(project) == []


def test_valid_fast_ema_values_are_admitted(tmp_path):
    store = Store(tmp_path / "valid.db")
    project = store.create_project("EMA", 'strategy("EMA")\nema = input.int(8, "Fast EMA", minval=7, maxval=9, step=1)')
    plan = ScanPlan("study", ("BIST:XU030D1!",), ("15",), {"in_0": [7, 8, 9]})
    assert enqueue_plan(store, project, plan) == 3


@pytest.mark.parametrize("field,value", [
    ("timeout", True), ("timeout", "75"), ("timeout", float("inf")),
    ("poll_interval", False), ("poll_interval", "0.7"),
    ("stable_reads", True), ("stable_reads", 3.5), ("stable_reads", "3"),
])
def test_saved_plan_does_not_coerce_invalid_runtime_types(field, value):
    saved = ScanPlan("study", ("X",), ("15",), {}).to_dict()
    saved[field] = value
    restored = ScanPlan.from_dict(saved)
    with pytest.raises(ValueError):
        restored.validate()
