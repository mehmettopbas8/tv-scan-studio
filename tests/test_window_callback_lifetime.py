import sys

from PySide6 import QtCore, QtTest
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


def test_empty_strategy_plan_signals_do_not_raise(tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    studio = StudioWindow(Store(tmp_path / "empty.db"))
    assert studio._plan_parsed_inputs == []
    studio.symbols.setText("BIST:XU030D1!")
    studio.timeframes.setText("15")
    studio.date_from.setText("2025-01-01")
    studio.date_to.setText("2025-12-31")
    studio.preview_plan()
    assert errors == []
    assert studio.store.total_counts().get("pending", 0) == 0


def test_tab_discovery_callback_is_cancelled_with_closed_window(tmp_path, monkeypatch):
    import tv_scan_studio.app as module
    studio = StudioWindow(Store(tmp_path / "closed.db"))
    discovered = []
    monkeypatch.setattr(module, "open_chart_tabs", lambda *args, **kwargs: [])
    monkeypatch.setattr(studio, "discover_targets", lambda: discovered.append(True))
    studio.create_worker_tabs()
    studio.window.close()
    studio.window.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    QtTest.QTest.qWait(1300)
    assert discovered == []
