import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import threading
import time

from PySide6 import QtCore, QtWidgets as Q

from tv_scan_studio.historical_dialog import HistoricalDialog
from tv_scan_studio.research_archives import ArchiveCancelled
from tv_scan_studio.storage import Store


def drain(dialog, app):
    deadline = time.monotonic() + 5
    while dialog.load_job is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert dialog.load_job is None


def test_background_archive_cancel_keeps_previous_rows_and_settings(tmp_path, monkeypatch):
    from tv_scan_studio import archive_jobs
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "active.db")
    dialog = HistoricalDialog(store)
    old_rows = dialog.rows
    settings = store.app_settings()
    entered = threading.Event()
    def slow_import(source, root, *, cancel_requested, progress):
        entered.set()
        progress({"stage": "Kontrol", "records": 256})
        while not cancel_requested():
            time.sleep(0.002)
        raise ArchiveCancelled()
    monkeypatch.setattr(archive_jobs, "import_archive", slow_import)
    dialog.show()
    assert dialog.load_archive(tmp_path / "input.jsonl")
    assert not dialog.load_archive(tmp_path / "duplicate.jsonl")
    ticks = []
    timer = QtCore.QTimer()
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(1)
    deadline = time.monotonic() + 3
    try:
        while len(ticks) < 5 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.002)
        assert entered.is_set() and len(ticks) >= 5
        assert not dialog.open_button.isEnabled()
        assert "bitir veya iptal" in dialog.help_registry.specs["history.open"].text()
        dialog.cancel_load.click()
        assert "iptal ediliyor" in dialog.status.text()
        drain(dialog, app)
        assert dialog.rows is old_rows
        # Tour completion keys may be persisted independently; no archive path was changed.
        assert store.app_settings().get("historical_archive_path") == settings.get("historical_archive_path")
        assert "önceki görüntü" in dialog.status.text()
        assert dialog.open_button.isEnabled()
        assert not dialog.activity.isVisible()
    finally:
        timer.stop()
        dialog.accept()


def test_close_waits_for_job_and_bad_archive_keeps_previous_view(tmp_path, monkeypatch):
    from tv_scan_studio import archive_jobs
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "active.db")
    dialog = HistoricalDialog(store)
    dialog.help_registry.read_settings = lambda: {"help_tour_history_completed": True}
    def slow_import(source, root, *, cancel_requested, progress):
        while not cancel_requested():
            time.sleep(0.002)
        time.sleep(0.02)
        raise ArchiveCancelled()
    monkeypatch.setattr(archive_jobs, "import_archive", slow_import)
    dialog.show()
    dialog.load_archive("unused.jsonl")
    dialog.close()
    assert dialog.isVisible() and dialog.load_job is not None
    drain(dialog, app)
    assert not dialog.isVisible()
    assert not store.app_settings().get("historical_archive_path")


def test_actual_job_publishes_only_on_complete_success(tmp_path):
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "active.db")
    source = tmp_path / "good.jsonl"
    source.write_text(json.dumps({"symbol": "BIST:XU030D1!", "tf": "15", "params": {"in_0": 8},
                                  "metrics": {"pf": 1.2}, "valid": True}), encoding="utf-8")
    dialog = HistoricalDialog(store)
    assert dialog.load_archive(source)
    assert dialog.rows == []
    drain(dialog, app)
    assert len(dialog.rows) == 1 and not dialog.rows[0]["verified"]
    previous = dialog.rows
    path = store.app_settings()["historical_archive_path"]
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not JSON", encoding="utf-8")
    dialog.load_archive(bad)
    drain(dialog, app)
    assert dialog.rows is previous
    assert store.app_settings()["historical_archive_path"] == path
    assert "Arşiv açılamadı" in dialog.status.text()
    assert not store.projects()
    assert not dialog.help_registry.missing_controls(dialog)
    dialog.accept()


def test_load_popup_is_read_only_and_timer_retires(tmp_path, monkeypatch):
    from tv_scan_studio import archive_jobs
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "active.db")
    store.save_app_settings({"help_tour_history_completed": True})
    def slow_import(source, root, *, cancel_requested, progress):
        while not cancel_requested():
            time.sleep(0.002)
        raise ArchiveCancelled()
    monkeypatch.setattr(archive_jobs, "import_archive", slow_import)
    dialog = HistoricalDialog(store)
    dialog.show()
    dialog.load_archive("unused.jsonl")
    app.processEvents()
    tour = dialog.help_registry.active_tour
    assert tour is not None
    assert any(step[0] is dialog.cancel_load for step in tour.steps)
    while not tour.ended:
        tour.next.click()
    assert not dialog.load_job.cancel_event.is_set()
    assert not tour.timer.isActive()
    assert store.app_settings()["help_tour_history_load_completed"]
    dialog.load_guide.click()
    reopened_tour = dialog.help_registry.active_tour
    dialog.cancel_loading()
    drain(dialog, app)
    assert reopened_tour.ended and not reopened_tour.timer.isActive()
    assert dialog.help_registry.active_tour is None
    assert not store.projects()
    dialog.accept()
