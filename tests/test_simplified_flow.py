import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtGui, QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store
from tv_scan_studio.preparation import find_prepared_chart, PreparationState
from tv_scan_studio.windows import worker_layout_candidates


def test_scan_confirmation_names_period_timezone_and_effective_costs():
    plan = SimpleNamespace(date_range={"from": "2026-09-07", "to": "2026-09-18"},
        costs={"assumptions": {"analysis_timezone": "Europe/Istanbul", "initial_capital": 100000,
            "position_size": 1, "commission_value": .01, "spread": 0, "slippage": 2,
            "scenario": "Ağır stres"}})
    text = StudioWindow._scan_confirmation_conditions(plan)
    for expected in ("2026-09-07 – 2026-09-18", "Europe/Istanbul", "100000",
                     "Komisyon (%): 0.01", "Spread: 0", "Kayma (tick): 2", "Ağır stres"):
        assert expected in text
    plan.date_range = None
    assert "Grafikte erişilebilen geçmiş" in StudioWindow._scan_confirmation_conditions(plan)


def test_friendly_timeframes_round_trip_without_changing_resolution():
    codes = ["1", "2", "15", "60", "240", "1D", "1W", "1M"]
    labels = ", ".join(StudioWindow._timeframe_label(code) for code in codes)
    assert StudioWindow._timeframe_codes(labels) == codes
    assert StudioWindow._timeframe_codes("15, 1H") == ["15", "1H"]


def test_result_mismatch_is_not_mistaken_for_connection_error():
    assert "istenen ayarlarla" in StudioWindow._friendly_error("Sonuç doğrulanamadı: trades=[10061]")


def test_completed_scan_is_not_labelled_stopped(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "completed.db")
    project = store.create_project("EMA", 'strategy("EMA")')
    store.enqueue(project, "one", {"symbol": "BIST:XU030D1!", "timeframe": "15"})
    studio = StudioWindow(store)
    task = store.claim_next(1)
    studio.plan_project.setCurrentIndex(studio.plan_project.findData(project))
    studio.result_project.setCurrentIndex(studio.result_project.findData(project))
    studio.supervisor = SimpleNamespace(running=False, states={}, restart_failed=lambda: [])
    try:
        studio.refresh_worker_states()
        assert studio.run_progress.text().startswith("Tarama durdu:")
        store.complete(task.id, 1, {"trades": 10, "profit_factor": .8}, "elenmiş", verified=True)
        studio.refresh_worker_states()
        assert studio.run_progress.text().startswith("Tarama tamamlandı: 1/1")
    finally:
        studio.supervisor = None
        studio.window.close()


def test_result_progress_recovers_completed_scan_after_reopen(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "reopened.db")
    project = store.create_project("EMA", 'strategy("EMA")')
    store.enqueue(project, "one", {"symbol": "BIST:XU030D1!", "timeframe": "15"})
    task = store.claim_next(1)
    store.complete(task.id, 1, {"trades": 10, "profit_factor": .8}, "elenmiş", verified=True)
    other = store.create_project("Other", 'strategy("Other")')
    studio = StudioWindow(store)
    try:
        studio.result_project.setCurrentIndex(studio.result_project.findData(project))
        studio.refresh_results()
        assert studio.run_progress.text().startswith("Tarama tamamlandı: 1/1")
        studio.result_project.setCurrentIndex(studio.result_project.findData(other))
        studio.plan_project.setCurrentIndex(studio.plan_project.findData(project))
        studio.supervisor = SimpleNamespace(running=True,
            states={1: SimpleNamespace(error="Other strategy connection failure")})
        studio.refresh_results()
        assert "henüz tarama başlatılmadı" in studio.run_progress.text()
    finally:
        studio.supervisor = None
        studio.window.close()


def test_unique_save_preserves_legacy_duplicates_and_explicit_copy(tmp_path):
    store = Store(tmp_path / "studio.db")
    source = 'strategy("A")\nn=input.int(8,"Fast EMA",minval=1)'
    first = store.create_project("Old", source)
    second = store.create_project("Old duplicate", source)
    assert store.save_unique_project("New name", source) == (first, False)
    copy, created = store.save_unique_project("Copy", source, copy=True)
    assert created and copy not in (first, second)
    assert len(store.projects()) == 3


def test_three_main_routes_and_save_flow(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "studio.db"))
    try:
        assert [b.text() for b in studio.nav_group.buttons()] == ["Stratejiler", "Tarama", "Sonuçlar"]
        assert studio.pages.currentIndex() == 1
        studio.project_name.setText("EMA")
        studio.pine_source.setPlainText('strategy("EMA")\nn=input.int(8,"Fast EMA")\nplot(ta.ema(close,n))')
        studio.save_project(); studio.save_project()
        assert len(studio.store.projects()) == 1
        studio.prepare_saved_strategy()
        assert studio.pages.currentIndex() == 2
        assert studio.plan_project.currentData() == studio._saved_project_id
        assert studio.plan_inputs.item(0, 4).text() == "—"
        studio.symbols.setText("BIST:XU030D1!"); studio.timeframes.setText("15")
        assert studio.enqueue_plan_button.isEnabled()  # Preparation no longer needs a manual study picker.
    finally:
        studio.worker_timer.stop(); studio.source_timer.stop(); studio.window.close()


def test_wheel_never_changes_closed_controls(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "studio.db"))
    try:
        combo = studio.cost_scenario
        combo.setCurrentText("Özel")
        spin = studio.commission
        spin.setValue(0)
        for control in (combo, spin):
            event = QtGui.QWheelEvent(QtCore.QPointF(10, 10), QtCore.QPointF(10, 10),
                QtCore.QPoint(), QtCore.QPoint(0, -120), QtCore.Qt.NoButton,
                QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
            application.sendEvent(control, event)
        assert combo.currentText() == "Özel"
        assert spin.value() == 0
    finally:
        studio.worker_timer.stop(); studio.window.close()


def test_conflicting_workers_do_not_disable_independent_chart():
    targets = [{"id": "a", "url": "https://www.tradingview.com/chart/shared/"},
               {"id": "b", "url": "https://www.tradingview.com/chart/shared/"},
               {"id": "c", "url": "https://www.tradingview.com/chart/unique/"}]
    names = {"a": "TV Scan Worker 1", "b": "TV Scan Worker 1", "c": "TV Scan Worker 2"}
    assert worker_layout_candidates(targets, names) == {"c": "unique"}


def test_preparation_without_matching_chart_returns_action_not_success():
    driver = SimpleNamespace(layout_name=lambda target: "Coding",
        inventory=lambda: [{"target_id": "a", "strategies": []}])
    result = find_prepared_chart(driver,
        [{"id": "a", "url": "https://www.tradingview.com/chart/personal/"}],
        {"pine_source": 'strategy("EMA")\nn=input.int(8,"Fast EMA")'})
    assert result.state == PreparationState.ACTION_REQUIRED
    assert result.target_id is None
    assert "korunuyor" in result.technical_detail


def test_default_preparation_does_not_adopt_mixed_strategy_layout():
    matching = {"id": "ema", "name": "EMA", "input_ids": ["in_0"]}
    driver = SimpleNamespace(layout_name=lambda target: "TV Scan Worker " + target,
        inventory=lambda: [
            {"target_id": "1", "strategies": [matching, {"name": "Other"}]},
            {"target_id": "2", "strategies": [matching]}])
    targets = [{"id": "1", "url": "https://www.tradingview.com/chart/mixed/"},
               {"id": "2", "url": "https://www.tradingview.com/chart/dedicated/"}]
    project = {"pine_source": 'strategy("EMA")\nn=input.int(8,"Fast EMA")'}
    result = find_prepared_chart(driver, targets, project, preferred_chart_id="mixed")
    assert result.chart_id is None
    assert result.state == PreparationState.ACTION_REQUIRED
    assert find_prepared_chart(driver, targets, project).chart_id == "dedicated"
    assert find_prepared_chart(driver, targets[:1], project).target_id is None


def test_closing_window_cancels_all_background_timers(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "close.db"))
    studio._connection_timer = QtCore.QTimer(studio.window)
    studio._connection_timer.start(1500)
    studio.source_timer.start()
    studio.window.close()
    assert not studio.worker_timer.isActive()
    assert not studio.source_timer.isActive()
    assert not studio._connection_timer.isActive()


def test_remote_symbol_picker_displays_name_but_returns_exact_code(tmp_path, monkeypatch):
    from tv_scan_studio import app as module
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    class Reply(QtCore.QObject):
        finished = QtCore.Signal()
        def error(self): return module.QtNetwork.QNetworkReply.NoError
        def readAll(self):
            return b'{"symbols":[{"symbol":"AAPL","exchange":"NASDAQ","description":"Apple Inc."}]}'
    class Manager(QtCore.QObject):
        def get(self, request):
            assert bytes(request.rawHeader("Origin")) == b"https://www.tradingview.com"
            reply = Reply(self)
            QtCore.QTimer.singleShot(0, reply.finished.emit)
            return reply
    monkeypatch.setattr(module.QtNetwork, "QNetworkAccessManager", Manager)
    studio = StudioWindow(Store(tmp_path / "search.db"))
    def select(dialog):
        dialog.findChild(QtWidgets.QLineEdit).setText("Apple")
        next(b for b in dialog.findChildren(QtWidgets.QPushButton)
             if b.text() == "TradingView'de ara").click()
        application.processEvents()
        listing = dialog.findChild(QtWidgets.QListWidget)
        item = next(listing.item(i) for i in range(listing.count())
                    if listing.item(i).data(QtCore.Qt.UserRole) == "NASDAQ:AAPL")
        assert item.text() == "Apple Inc. · NASDAQ"
        item.setCheckState(QtCore.Qt.Checked)
        return QtWidgets.QDialog.Accepted
    monkeypatch.setattr(QtWidgets.QDialog, "exec", select)
    try:
        studio.choose_symbols()
        assert studio.symbols.text() == "NASDAQ:AAPL"
    finally:
        studio.window.close()
