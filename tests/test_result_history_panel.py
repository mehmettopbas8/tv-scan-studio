import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtWidgets

from tv_scan_studio.app import StudioWindow
from tv_scan_studio.help_system import HelpRegistry
from tv_scan_studio.result_history_panel import ResultHistoryPanel
from tv_scan_studio.storage import Store


@pytest.fixture
def context(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "history-ui.db")
    project = store.create_project("EMA", 'strategy("EMA")\na=input.int(8)')
    store.enqueue(project, "test", {"inputs": {"in_0": 8}, "symbol": "A", "timeframe": "15",
        "criteria": {"min_profit_factor": 1, "max_drawdown_pct_exclusive": 5}})
    task = store.claim_next(1, [project])
    store.complete(task.id, 1, {"trades": 100, "profit_factor": 1.5, "win_rate_pct": 50,
        "net_profit": 100, "max_drawdown_pct": 2}, "hassas", verified=True,
        evidence={"tradingview_warning_state": "unknown"})
    yield app, store, project, task.id
    app.processEvents()


def test_history_readonly_help_and_confirmed_idempotent_evaluation(context, monkeypatch):
    app, store, project, task = context
    panel = ResultHistoryPanel(store, task)
    registry = HelpRegistry(panel)
    panel.register_help(registry)
    before = (store.tasks(project), store.result_history(task), store.results(project))
    frozen = store.result_history(task)[0]
    try:
        assert "Bilinmiyor" in panel.summary.text()
        assert "kaynak kaydedildi" in panel.summary.text()
        assert 'strategy("EMA")' not in panel.technical.toPlainText()
        assert len(registry.specs) == 25
        assert panel.attempts.rowCount() == 2
        panel.fields["min_profit_factor"].setText("2")
        monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *_args: QtWidgets.QMessageBox.No)
        panel.evaluate.click()
        assert len(store.result_evaluations(frozen["id"])) == 1
        monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *_args: QtWidgets.QMessageBox.Yes)
        panel.evaluate.click()
        panel.evaluate.click()
        assert len(store.result_evaluations(frozen["id"])) == 2
        assert panel.evaluations.item(1, 1).text() == "elenmiş"
        assert "Özgün sonuç" in panel.status.text()
        assert (store.tasks(project), store.result_history(task), store.results(project)) == before
        panel.show()
        app.processEvents()
        panel.guide.click()
        app.processEvents()
        assert len(store.result_evaluations(frozen["id"])) == 2
        registry.finish_scope()
        assert (store.tasks(project), store.result_history(task), store.results(project)) == before
    finally:
        panel.close()
        panel.deleteLater()


def test_invalid_policy_visible_and_missing_snapshot_disabled(context, monkeypatch):
    _, store, project, task = context
    panel = ResultHistoryPanel(store, task)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *_args: QtWidgets.QMessageBox.Yes)
    before = store.result_evaluations(panel.selected()["id"])
    try:
        for invalid in ("nan", "101", "-1", "not-a-number"):
            panel.fields["max_drawdown_pct_exclusive"].setText(invalid)
            panel.evaluate.click()
            assert "kaydedilmedi" in panel.status.text()
            assert store.result_evaluations(panel.selected()["id"]) == before
        store.enqueue(project, "pending", {})
        pending = store.tasks(project)[-1]["id"]
        empty = ResultHistoryPanel(store, pending)
        assert not empty.evaluate.isEnabled()
        assert "henüz sonuç" in empty.summary.text()
        empty.close()
        empty.deleteLater()
    finally:
        panel.close()
        panel.deleteLater()


def test_detail_replacement_retires_help_and_keeps_history(context):
    app, store, project, task = context
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    try:
        studio.refresh_results()
        studio.open_result_details_by_id(task)
        first = studio.result_detail_dock.widget().findChild(ResultHistoryPanel)
        assert first is not None
        assert studio.help_registry.specs["result_history.select"].target is first.selector
        studio.open_result_details_by_id(task)
        second = studio.result_detail_dock.widget().findChild(ResultHistoryPanel)
        assert second is not first
        assert studio.help_registry.specs["result_history.select"].target is second.selector
        assert len(store.result_history(task)) == 1
    finally:
        studio.window.close()
        app.processEvents()
