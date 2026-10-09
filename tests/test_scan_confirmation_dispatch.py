"""Exercise the real Qt question dialog, without touching TradingView.

This is local dispatch evidence, not native packaged/live acceptance.
"""
import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore, QtTest, QtWidgets

import tv_scan_studio.app as module
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


@pytest.mark.parametrize("answer,keyboard", [(QtWidgets.QMessageBox.Yes, False),
    (QtWidgets.QMessageBox.No, False), (QtWidgets.QMessageBox.Yes, True)])
def test_real_confirmation_dispatches_only_yes(tmp_path, monkeypatch, answer, keyboard):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "confirmation.db")
    project = store.create_project("EMA", 'strategy("EMA")\nfast=input.int(8,"Fast EMA")')
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    studio.source_timer.stop()
    studio.plan_project.setCurrentIndex(studio.plan_project.findData(project))
    studio.symbols.setText("BIST:XU030D1!")
    studio.timeframes.setText("15")
    studio.preview_plan()
    monkeypatch.setattr(module, "cdp_healthy", lambda: True)
    monkeypatch.setattr(module, "chart_targets", lambda: [])
    monkeypatch.setattr(module, "GncZihinDriver", lambda *_args: SimpleNamespace(
        layout_name=lambda _target: "TV Scan Worker 1"))
    monkeypatch.setattr(module, "find_prepared_chart", lambda *_args, **_kwargs: SimpleNamespace(
        target_id="owned", chart_id="independent"))
    discoveries = []

    def stop_before_live_discovery():
        discoveries.append("approved")
        raise ValueError("LOCAL_TEST_STOPS_BEFORE_LIVE_DISCOVERY")

    monkeypatch.setattr(studio, "discover_targets", stop_before_live_discovery)
    observed = []
    deadline = time.monotonic() + 3
    timer = QtCore.QTimer()
    timer.setInterval(10)

    def answer_real_dialog():
        dialog = app.activeModalWidget()
        if isinstance(dialog, QtWidgets.QMessageBox):
            observed.append(dialog.windowTitle())
            timer.stop()
            if keyboard:
                QtTest.QTest.keyClick(dialog, QtCore.Qt.Key_Return)
            else:
                dialog.button(answer).click()
        elif time.monotonic() > deadline:
            timer.stop()

    timer.timeout.connect(answer_real_dialog)
    timer.start()
    try:
        studio.prepare_and_start()
        assert observed == ["Tarama grafiği kullanım onayı"]
        assert discoveries == (["approved"] if answer == QtWidgets.QMessageBox.Yes else [])
        assert store.tasks(project) == []
        assert store.scan_runs(project) == []
        if answer == QtWidgets.QMessageBox.Yes:
            assert store.settings(project)["prepared_chart_id"] == "independent"
            assert "LOCAL_TEST_STOPS_BEFORE_LIVE_DISCOVERY" in studio.connection_status.text()
        else:
            assert "prepared_chart_id" not in (store.settings(project) or {})
            assert "tarama başlatılmadı" in studio.connection_status.text()
        assert not studio._preparing
    finally:
        timer.stop()
        studio.window.close()
        app.processEvents()
