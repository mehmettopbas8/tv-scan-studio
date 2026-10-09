"""Interrupted intent and parallel finalization retain slot ownership."""
from types import SimpleNamespace

from PySide6 import QtWidgets

from tv_scan_studio import app as module
from tv_scan_studio.storage import Store


def test_pending_intent_without_chart_identity_never_discovers_fallback(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "pending.db")
    source = 'strategy("EMA")\nfast=input.int(8,"Fast EMA")'
    project = store.create_project("EMA", source)
    studio = module.StudioWindow(store)
    studio.worker_timer.stop()
    studio.source_timer.stop()
    studio.plan_project.setCurrentIndex(studio.plan_project.findData(project))
    studio.symbols.setText("BIST:XU030D1!")
    studio.timeframes.setText("15")
    studio.preview_plan()
    journal = {"requested": True, "name": "TV Scan Worker 5", "before_target_ids": ["baseline"]}
    store.save_settings(project, {"automatic_preparation": journal, "prepared_chart_id": "oldBaseline"})
    monkeypatch.setattr(module, "cdp_healthy", lambda: True)
    monkeypatch.setattr(module, "chart_targets", lambda: [])
    monkeypatch.setattr(module, "GncZihinDriver", lambda *_: SimpleNamespace())
    discoveries = []
    monkeypatch.setattr(module, "find_prepared_chart", lambda *a, **kw: discoveries.append(kw))
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *_: QtWidgets.QMessageBox.No)
    try:
        studio.prepare_and_start()
        assert discoveries == []
        assert store.tasks(project) == []
        assert store.settings(project)["automatic_preparation"] == journal
        assert store.settings(project)["prepared_chart_id"] == "oldBaseline"
    finally:
        studio.window.close()
        application.processEvents()


def test_parallel_preparation_does_not_overwrite_primary_finalized_identity(tmp_path, monkeypatch):
    store = Store(tmp_path / "parallel.db")
    source = 'strategy("EMA")'
    project = store.create_project("EMA", source)
    store.save_settings(project, {"prepared_chart_id": "primaryChart"})
    before = [{"id": "personal", "url": "https://www.tradingview.com/chart/coding/"}]
    after = before + [{"id": "parallel", "url": "https://www.tradingview.com/chart/parallelChart/"}]
    snapshots = iter([before, after, after, after])
    monkeypatch.setattr(module, "chart_targets", lambda: next(snapshots))
    def load(target, actual_source, *, journal, persist, guard):
        assert target == "parallel" and actual_source == source
        guard(target)
    driver = SimpleNamespace(layout_name=lambda target: "Coding" if target == "personal" else "TV Scan Worker 1",
        create_empty_layout=lambda *_: None, load_private_source=load)
    job = module.ChartPreparationJob(driver, store, {"id": project, "pine_source": source}, slot=1)
    completed = []
    job.completed.connect(completed.append)
    job.run()
    assert completed == [{"project_id": project, "success": True}]
    settings = store.settings(project)
    assert settings["prepared_chart_id"] == "primaryChart"
    assert settings["automatic_preparation_parallel_1"]["chart_id"] == "parallelChart"
    assert "automatic_preparation" not in settings
