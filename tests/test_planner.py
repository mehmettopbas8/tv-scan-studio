from itertools import islice

import pytest

from tv_scan_studio.planner import ScanPlan, enqueue_plan, iter_tasks


def test_scan_plan_rejects_incomplete_or_invalid_backtest_dates():
    import pytest

    base = {"study_id": "study", "symbols": ("OANDA:XAUUSD",),
            "timeframes": ("15",), "input_values": {"in_0": [3]}}
    for dates in ({"from": "2025-01-01"},
                  {"from": "2025-02-30", "to": "2025-03-01"},
                  {"from": "2025-12-31", "to": "2025-01-01"}):
        with pytest.raises(ValueError, match="Tarih aralığı"):
            ScanPlan(**base, date_range=dates).validate()
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
    assert value.workload_factors() == (
        ("symbols", 2), ("timeframes", 2), ("variants", 1),
        ("in_0", 2), ("in_1", 2),
    )
    all_keys = [key for key, _ in iter_tasks(value)]
    assert len(all_keys) == len(set(all_keys)) == value.task_count
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


def test_invalid_enqueue_preserves_existing_settings_and_project(tmp_path):
    store = Store(tmp_path / "atomic.db")
    project = store.create_project("Atomic", 'strategy("Atomic")')
    store.save_settings(project, {"old": "preserved"})
    before = store.project(project)
    with pytest.raises(ValueError):
        enqueue_plan(store, project, ScanPlan("study", (), ("15",), {}))
    assert store.settings(project) == {"old": "preserved"}
    assert store.project(project) == before
    assert store.tasks(project) == []


def test_generation_failure_rolls_back_settings_and_all_inserted_tasks(tmp_path, monkeypatch):
    import tv_scan_studio.planner as planner
    store = Store(tmp_path / "rollback.db")
    project = store.create_project("Rollback", 'strategy("Rollback")')
    store.save_settings(project, {"old": "preserved"})
    before = store.project(project)
    def failing_tasks(_plan, **_options):
        yield "first", {"symbol": "X"}
        raise RuntimeError("interrupted generation")
    monkeypatch.setattr(planner, "iter_tasks", failing_tasks)
    with pytest.raises(RuntimeError, match="interrupted"):
        enqueue_plan(store, project, plan(), settings={"input_ui": {"in_0": {"decision": "Tara"}}})
    assert store.settings(project) == {"old": "preserved"}
    assert store.project(project) == before
    assert store.tasks(project) == []


def test_successful_enqueue_commits_plan_and_ui_snapshot_together(tmp_path):
    store = Store(tmp_path / "success.db")
    project = store.create_project("Success", 'strategy("Success")')
    ui = {"in_0": {"decision": "Tara", "values": [10, 20]}}
    assert enqueue_plan(store, project, plan(), settings={"input_ui": ui}) == 16
    assert store.settings(project)["input_ui"] == ui
    assert store.settings(project)["input_values"] == plan().input_values
    assert store.counts(project) == {"pending": 16}


@pytest.mark.parametrize("changes", [
    {"timeout": float("nan")}, {"timeout": float("inf")}, {"timeout": True},
    {"poll_interval": float("nan")}, {"poll_interval": float("inf")},
    {"stable_reads": 1.5}, {"stable_reads": True},
    {"criteria": {"min_profit_factor": float("nan")}},
    {"costs": {"assumptions": {"spread": float("inf")}}},
])
def test_plan_rejects_nonfinite_controls_and_invalid_read_count(changes):
    base = {"study_id": "study", "symbols": ("X",), "timeframes": ("15",), "input_values": {}}
    with pytest.raises(ValueError):
        ScanPlan(**(base | changes)).validate()


@pytest.mark.parametrize("changes,error", [
    ({"symbols": ("OANDA:EURUSD", "OANDA:EURUSD")}, "Aynı sembol"),
    ({"timeframes": ("15", "15")}, "Aynı timeframe"),
    ({"input_values": {"in_0": [3, 3]}}, "in_0 inputu"),
    ({"variants": [{"in_1": True}, {"in_1": True}]}, "Kontrollü varyant"),
    ({"input_values": {"in_0": [float("nan")]}}, "JSON"),
])
def test_plan_rejects_duplicate_or_unserializable_choices(changes, error):
    base = {"study_id": "study", "symbols": ("OANDA:EURUSD",),
            "timeframes": ("15",), "input_values": {"in_0": [3]}}
    base.update(changes)
    with pytest.raises(ValueError, match=error):
        ScanPlan(**base).task_count


def test_coupled_variants_do_not_create_unwanted_cartesian_combinations():
    value = ScanPlan(
        "study", ("OANDA:DE30EUR",), ("15",), {"in_0": [1, 2]},
        variants=[{"in_58": True, "in_62": False},
                  {"in_58": False, "in_62": True}],
    )
    tasks = list(iter_tasks(value))
    assert value.task_count == len(tasks) == 4
    assert dict(value.workload_factors())["variants"] == 2
    assert {(payload["inputs"]["in_58"], payload["inputs"]["in_62"])
            for _, payload in tasks} == {(True, False), (False, True)}
    assert ScanPlan.from_dict(value.to_dict()).task_count == 4
    with pytest.raises(ValueError, match="ezemez"):
        ScanPlan("study", ("X",), ("15",), {"in_0": [1]},
                 variants=[{"in_0": 2}]).validate()
