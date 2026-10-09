import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from copy import deepcopy
from dataclasses import replace

import pytest
from PySide6 import QtWidgets

from tv_scan_studio.help_system import HelpRegistry
from tv_scan_studio.planner import ScanPlan, enqueue_plan
from tv_scan_studio.run_choice import RunChoice
from tv_scan_studio.scan_runs import comparable_plan
from tv_scan_studio.storage import Store


@pytest.fixture
def context(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "runs.db")
    project = store.create_project("EMA", 'strategy("EMA")\na = input.int(8)')
    plan = ScanPlan("study", ("BIST:XU030D1!",), ("15",), {"in_0": [7, 8, 9]})
    choice = RunChoice(store)
    choice.refresh(project)
    yield app, store, project, plan, choice
    choice.close()
    choice.deleteLater()
    app.processEvents()


def test_default_new_resume_and_frozen_restore_without_writes(context):
    _, store, project, plan, choice = context
    assert choice.request(project, plan) == {"new_run": True}
    assert not choice.restore.isEnabled()
    _, run_id = enqueue_plan(store, project, plan, new_run=True, return_run_id=True)
    choice.refresh(project, selected=run_id)
    assert choice.request(project, plan) == {"run_id": run_id}
    snapshots = []
    choice.restore_requested.connect(snapshots.append)
    before = store.run_tasks(run_id)
    choice.restore.click()
    assert len(snapshots) == 1
    assert comparable_plan(snapshots[0]) == comparable_plan(plan.to_dict())
    snapshots[0]["input_values"]["in_0"].append(10)
    assert choice.runs[run_id]["plan_snapshot"]["input_values"] == {"in_0": [7, 8, 9]}
    assert store.run_tasks(run_id) == before
    rebound = replace(deepcopy(plan), study_id="different-live-study")
    assert choice.request(project, rebound) == {"run_id": run_id}
    rebound.input_values["in_0"] = [8, 9]
    with pytest.raises(ValueError, match="planı değişmiş"):
        choice.request(project, rebound)
    with pytest.raises(ValueError, match="Strateji değişti"):
        choice.request(project + 1, plan)


def test_legacy_not_resumable_and_source_change_is_explained(context):
    _, store, project, plan, choice = context
    enqueue_plan(store, project, plan)
    choice.refresh(project)
    assert choice.choice.count() == 1
    _, run_id = enqueue_plan(store, project, plan, new_run=True, return_run_id=True)
    choice.refresh(project, selected=run_id)
    with store.connect() as connection:
        connection.execute("UPDATE projects SET pine_source=pine_source || ' ' WHERE id=?", (project,))
    with pytest.raises(ValueError, match="kodu değişmiş"):
        choice.request(project, plan)
    restored = []
    choice.restore_requested.connect(restored.append)
    choice.restore.click()
    assert not restored
    assert "Yeni tarama" in choice.status.text()


def test_all_controls_have_help_and_tour_does_not_restore_or_admit(context):
    app, store, project, plan, choice = context
    registry = HelpRegistry(choice)
    choice.register_help(registry)
    for target in (choice.label, choice.choice, choice.restore, choice.status, choice.guide):
        assert registry.resolve(target)
        assert target.toolTip()
    assert "Önce devam edilecek" in registry.specs["runs.restore"].text()
    choice.show()
    app.processEvents()
    registry.start_tour("runs")
    app.processEvents()
    assert store.tasks(project) == []
    assert store.scan_runs(project) == []
    registry.finish_scope()
