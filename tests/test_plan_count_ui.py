import os
import time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store
from tv_scan_studio.planner import ScanPlan


def wait_until(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert predicate()


def studio_for(tmp_path):
    store = Store(tmp_path / "count.db")
    store.create_project("EMA", 'strategy("EMA")\nfast = input.int(8, "Fast EMA")')
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    return studio


def big_plan():
    return ScanPlan("study", ("A",), ("15",),
                    {"a": list(range(10000)), "b": list(range(10000))},
                    constraints=[{"left": "a", "operator": "<", "right": "b"}])


def test_async_count_cancel_invalid_edit_and_late_result(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = studio_for(tmp_path)
    monkeypatch.setattr(studio, "_current_plan", big_plan)
    try:
        started = time.monotonic()
        studio.preview_plan()
        assert time.monotonic() - started < 1
        assert not studio.enqueue_plan_button.isEnabled()
        assert "arka planda" in studio.plan_status.text()
        studio.prepare_and_start()
        assert not studio._preparing
        assert "sayımını tamamlayın" in studio.plan_status.text()
        studio._cancel_or_retry_count()
        wait_until(app, lambda: not studio.plan_counter.jobs and studio._count_result is not None)
        assert studio._count_result["status"] == "cancelled"
        assert studio.cancel_count_button.text() == "Sayımı yeniden dene"
        studio._cancel_or_retry_count()
        assert studio.plan_counter.jobs
        def invalid():
            raise ValueError("Zaman dilimi eksik")
        monkeypatch.setattr(studio, "_current_plan", invalid)
        studio.preview_plan()
        before = studio.plan_status.text()
        wait_until(app, lambda: not studio.plan_counter.jobs)
        studio._receive_plan_count({"revision": studio.plan_counter.revision, "status": "ready", "tasks": 999})
        studio._plan_count_progress({"revision": studio.plan_counter.revision, "examined": 999})
        assert studio._count_result is None
        assert studio.plan_status.text() == before == "Zaman dilimi eksik"
    finally:
        studio.window.close()
        app.processEvents()


def test_close_cancels_and_defers_until_threads_retire(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = studio_for(tmp_path)
    monkeypatch.setattr(studio, "_current_plan", big_plan)
    studio.window.show()
    studio.preview_plan()
    studio.window.close()
    assert studio._count_closing
    wait_until(app, lambda: not studio.plan_counter.jobs and not studio.window.isVisible())
    assert not studio.worker_timer.isActive()


def test_completed_count_displays_exact_totals_without_recount(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = studio_for(tmp_path)
    plan = ScanPlan("study", ("A",), ("15",),
                    {"a": list(range(101)), "b": list(range(101))},
                    constraints=[{"left": "a", "operator": "<", "right": "b"}])
    monkeypatch.setattr(studio, "_current_plan", lambda: plan)
    try:
        studio.preview_plan()
        wait_until(app, lambda: studio._count_result is not None and not studio.plan_counter.jobs)
        assert studio._count_result["tasks"] == 5050
        assert "Kural öncesi: 10,201" in studio.constraint_editor.status.text()
        assert "Atlanan: 5,151" in studio.constraint_editor.status.text()
        assert "5,050 görev" in studio.plan_status.text()
        revision = studio.plan_counter.revision
        studio.preview_plan()
        assert studio.plan_counter.revision == revision
        assert not studio.plan_counter.jobs
        assert studio.enqueue_plan_button.isEnabled()
    finally:
        studio.window.close()
        app.processEvents()
