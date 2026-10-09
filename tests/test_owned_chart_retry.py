"""Owned-layout retries must never silently adopt another matching chart."""
from types import SimpleNamespace

import pytest

from tv_scan_studio.preparation import find_prepared_chart


@pytest.mark.parametrize("owned_studies", [[], [{"name": "Wrong", "input_ids": []}],
    [{"name": "EMA", "input_ids": ["in_0"]}, {"name": "Other"}]])
def test_unready_owned_chart_does_not_fall_back(owned_studies):
    targets = [{"id": target, "url": f"https://www.tradingview.com/chart/{chart}/"}
        for target, chart in (("owned", "ownedChart"), ("baseline", "baselineChart"))]
    matching = {"name": "EMA", "input_ids": ["in_0"]}
    driver = SimpleNamespace(layout_name=lambda target: "TV Scan Worker " + {"owned": "5", "baseline": "4"}[target],
        inventory=lambda: [{"target_id": "owned", "strategies": owned_studies},
            {"target_id": "baseline", "strategies": [matching]}])
    project = {"pine_source": 'strategy("EMA")\nfast=input.int(8,"Fast EMA")'}
    assert find_prepared_chart(driver, targets, project,
        preferred_chart_id="ownedChart").target_id is None
    assert find_prepared_chart(driver, targets, project).target_id == "baseline"


def test_missing_owned_chart_does_not_fall_back():
    matching = {"name": "EMA", "input_ids": ["in_0"]}
    driver = SimpleNamespace(layout_name=lambda _: "TV Scan Worker 4",
        inventory=lambda: [{"target_id": "baseline", "strategies": [matching]}])
    targets = [{"id": "baseline", "url": "https://www.tradingview.com/chart/baselineChart/"}]
    project = {"pine_source": 'strategy("EMA")\nfast=input.int(8,"Fast EMA")'}
    assert find_prepared_chart(driver, targets, project,
        preferred_chart_id="missing_owned_chart").target_id is None


def test_owned_chart_identity_survives_changed_target_id():
    matching = {"name": "EMA", "input_ids": ["in_0"]}
    targets = [{"id": target, "url": f"https://www.tradingview.com/chart/{chart}/"}
        for target, chart in (("baseline", "baselineChart"), ("new_target", "ownedChart"))]
    driver = SimpleNamespace(layout_name=lambda target: "TV Scan Worker " + {"new_target": "5", "baseline": "4"}[target],
        inventory=lambda: [{"target_id": target["id"], "strategies": [matching]} for target in targets])
    project = {"pine_source": 'strategy("EMA")\nfast=input.int(8,"Fast EMA")'}
    result = find_prepared_chart(driver, targets, project, preferred_chart_id="ownedChart")
    assert (result.target_id, result.chart_id) == ("new_target", "ownedChart")
    assert find_prepared_chart(driver, targets, project, preferred_chart_id="ownedChart",
        excluded_targets={"new_target"}).target_id is None


@pytest.mark.parametrize("journals,expected", [
    ({"automatic_preparation": {"chart_id": "retry0"},
      "automatic_preparation_parallel_1": {"chart_id": "retry1"},
      "prepared_chart_id": "final0"}, ["retry0", "retry1", None]),
    ({"prepared_chart_id": "final0"}, ["final0", None, None]),
])
def test_prepare_and_start_binds_each_slot_to_its_own_journal(tmp_path, monkeypatch, journals, expected):
    from PySide6 import QtWidgets
    from tv_scan_studio import app as module
    from tv_scan_studio.storage import Store
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "slot-preference.db")
    project = store.create_project("EMA", 'strategy("EMA")\nfast=input.int(8,"Fast EMA")')
    studio = module.StudioWindow(store)
    studio.worker_timer.stop()
    studio.source_timer.stop()
    studio.plan_project.setCurrentIndex(studio.plan_project.findData(project))
    studio.symbols.setText("BIST:XU030D1!")
    studio.timeframes.setText("15")
    studio.parallel_count.setValue(3)
    studio.preview_plan()
    monkeypatch.setattr(store, "settings", lambda _: journals)
    monkeypatch.setattr(module, "cdp_healthy", lambda: True)
    monkeypatch.setattr(module, "chart_targets", lambda: [])
    monkeypatch.setattr(module, "GncZihinDriver", lambda *_: SimpleNamespace(layout_name=lambda _: "TV Scan Worker 1"))
    calls = []
    def discover(*args, preferred_chart_id=None, excluded_targets=()):
        calls.append((preferred_chart_id, set(excluded_targets)))
        return SimpleNamespace(target_id=f"slot{len(calls)-1}", chart_id=f"chart{len(calls)-1}")
    monkeypatch.setattr(module, "find_prepared_chart", discover)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *_: QtWidgets.QMessageBox.No)
    try:
        studio.prepare_and_start()
        assert [call[0] for call in calls] == expected
        assert [call[1] for call in calls] == [set(), {"slot0"}, {"slot0", "slot1"}]
        assert store.tasks(project) == []
    finally:
        studio.window.close()
        application.processEvents()
