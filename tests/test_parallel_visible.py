import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
from PySide6 import QtWidgets
from tv_scan_studio.app import StudioWindow, ChartPreparationJob
from tv_scan_studio.storage import Store


def test_parallel_choice_persisted_and_measured_rate(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "studio.db")
    project = store.create_project("EMA", 'strategy("EMA")\nn=input.int(8,"Fast EMA")')
    studio = StudioWindow(store)
    studio.parallel_count.setValue(3)
    assert store.app_settings()["parallel_graphs"] == 3
    studio.result_project.setCurrentIndex(studio.result_project.findData(project))
    studio.plan_project.setCurrentIndex(studio.plan_project.findData(project))
    studio.supervisor = SimpleNamespace(running=True, states={1: SimpleNamespace(completed=4, status="running", error=None),
                                                            2: SimpleNamespace(completed=2, status="failed", error="failure")})
    studio._active_run_id = 1
    studio._active_run_project = project
    monkeypatch.setattr(store, "run_performance", lambda _run: {
        "tests_per_hour": 360, "average_tests_per_hour": 360,
        "verified_count": 6, "eta_seconds": None})
    studio._refresh_result_progress()
    assert "360 test/saat" in studio.run_performance.text()
    assert "aktif grafik: 1" in studio.run_performance.text()
    assert not studio.parallel_count.isEnabled()
    studio.supervisor.running = False
    studio._refresh_result_progress()
    studio._refresh_result_progress()
    assert "360 test/saat" in studio.run_performance.text()
    studio.supervisor = None
    studio.window.close()


def test_worker_counters_without_verified_run_do_not_claim_speed(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "counters.db")
    store.create_project("EMA", 'strategy("EMA")\nn=input.int(8)')
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    studio.supervisor = SimpleNamespace(running=True, states={
        1: SimpleNamespace(completed=2000, status="running", error=None)})
    try:
        studio._refresh_result_progress()
        assert "ölçüm bekleniyor" in studio.run_performance.text()
        assert "2000" not in studio.run_performance.text()
    finally:
        studio.supervisor = None
        studio.window.close()


def test_parallel_preparation_uses_separate_retry_journal(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = {"id": 1}
    first = ChartPreparationJob(None, store, project)
    second = ChartPreparationJob(None, store, project, slot=1)
    retry = ChartPreparationJob(None, store, project, slot=1)
    assert first.journal_key != second.journal_key
    assert second.journal_key == retry.journal_key


def test_parallel_discovery_excludes_chosen_targets_but_checks_all_collisions(monkeypatch):
    from tv_scan_studio import preparation
    monkeypatch.setattr(preparation, "strategy_structure_matches", lambda *args: True)
    targets = [{"id": key, "url": f"https://www.tradingview.com/chart/{chart}/"}
               for key, chart in (("a", "first"), ("b", "second"), ("personal", "coding"))]
    driver = SimpleNamespace(layout_name=lambda key: "Coding" if key == "personal" else "TV Scan Worker " + {"a": "1", "b": "2", "clone": "1"}[key],
        inventory=lambda: [{"target_id": key, "strategies": [{"id": key}]} for key in ("a", "b")])
    project = {"pine_source": 'strategy("EMA")'}
    first = preparation.find_prepared_chart(driver, targets, project)
    second = preparation.find_prepared_chart(driver, targets, project, excluded_targets={first.target_id})
    assert {first.target_id, second.target_id} == {"a", "b"}
    assert preparation.find_prepared_chart(driver, targets, project, excluded_targets={"a", "b"}).target_id is None
    targets.append({"id": "clone", "url": targets[0]["url"]})
    assert preparation.find_prepared_chart(driver, targets, project, excluded_targets={"b"}).target_id is None
