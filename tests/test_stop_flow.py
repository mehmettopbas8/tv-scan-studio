import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


def test_stop_button_requests_without_join_and_reports_real_completion(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "ui-stop.db")
    project = store.create_project("Stop", 'strategy("Stop")')
    store.enqueue(project, "current", {"symbol": "BIST:XU030D1!", "timeframe": "15"})
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    task = store.claim_next(1, [project])
    calls = []
    supervisor = SimpleNamespace(running=True, stopping=False, stop_requested=False,
                                 states={}, restart_failed=lambda: [])
    def request_stop():
        calls.append("request")
        supervisor.stop_requested = supervisor.stopping = True
    def forbidden_join(*_args, **_kwargs):
        raise AssertionError("UI must not join worker threads")
    supervisor.request_stop = request_stop
    supervisor.stop = forbidden_join
    studio.supervisor = supervisor
    try:
        studio.stop_workers()
        assert calls == ["request"]
        assert "Durduruluyor" in studio.worker_status.text()
        assert "Durduruluyor" in studio.run_progress.text()
        studio.refresh_worker_states()
        assert "Durduruluyor" in studio.connection_status.text()
        assert "Durduruluyor" in studio.run_progress.text()
        store.complete(task.id, 1, {"trades": 10}, "hassas", verified=True)
        supervisor.running = supervisor.stopping = False
        studio.refresh_worker_states()
        assert "Durdu" in studio.worker_status.text()
        assert "Tarama durdu" in studio.connection_status.text()
        assert "Tarama durdu" in studio.run_progress.text()
    finally:
        supervisor.running = False
        studio.window.close()
