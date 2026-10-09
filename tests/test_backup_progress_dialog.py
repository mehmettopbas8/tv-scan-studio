import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time

from PySide6 import QtCore, QtWidgets as Q

from tv_scan_studio.backup import BackupCancelled
from tv_scan_studio.backup_jobs import BackupJob
from tv_scan_studio.backup_dialog import BackupProgressDialog


def test_escape_cancels_without_closing_until_worker_finishes(tmp_path, monkeypatch):
    from tv_scan_studio import backup_jobs
    application = Q.QApplication.instance() or Q.QApplication([])
    def slow_cancel(store, destination, *, check_cancel, progress, **kwargs):
        progress({"stage": "Kontrol ediliyor", "bytes": 1024})
        while not check_cancel():
            time.sleep(0.002)
        time.sleep(0.03)
        raise BackupCancelled()
    monkeypatch.setattr(backup_jobs, "create_backup", slow_cancel)
    job = BackupJob("create", destination=tmp_path / "cancelled.zip")
    dialog = BackupProgressDialog(job)
    # Do not let an automatic tour obstruct the cancellation control in this test.
    dialog.help_registry.read_settings = lambda: {"help_tour_backup_operation_completed": True}
    dialog.show()
    dialog.start()
    application.processEvents()
    assert len(dialog.help_registry.specs) == 5
    dialog.reject()
    assert dialog.isVisible() and dialog.job is job
    assert not dialog.cancel_button.isEnabled()
    assert "İptal ediliyor" in dialog.status.text()
    assert "İptal istendi" in dialog.help_registry.specs["backup.operation.cancel"].text()
    deadline = time.monotonic() + 3
    while dialog.job is not None and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.002)
    assert dialog.job is None
    assert dialog.outcome["status"] == "cancelled"
    assert not dialog.isVisible()
    assert not (tmp_path / "cancelled.zip").exists()


def test_late_cancel_after_publication_is_success(tmp_path, monkeypatch):
    from tv_scan_studio import backup_jobs
    application = Q.QApplication.instance() or Q.QApplication([])
    def published(store, destination, *, check_cancel, progress, **kwargs):
        # Simulate a committed result, then a request arriving before run returns.
        job.cancel()
        return {"project_count": 1, "attachments": []}
    monkeypatch.setattr(backup_jobs, "create_backup", published)
    job = BackupJob("create", destination=tmp_path / "backup.zip")
    dialog = BackupProgressDialog(job)
    dialog.help_registry.read_settings = lambda: {"help_tour_backup_operation_completed": True}
    dialog.start()
    dialog.exec()
    assert dialog.outcome["status"] == "ready"
    assert dialog.job is None


def test_main_window_close_defers_until_backup_thread_retires(tmp_path, monkeypatch):
    from tv_scan_studio import backup_jobs
    from tv_scan_studio.app import StudioWindow
    from tv_scan_studio.storage import Store
    application = Q.QApplication.instance() or Q.QApplication([])
    def slow_cancel(store, destination, *, check_cancel, progress, **kwargs):
        while not check_cancel():
            time.sleep(0.002)
        raise BackupCancelled()
    monkeypatch.setattr(backup_jobs, "create_backup", slow_cancel)
    studio = StudioWindow(Store(tmp_path / "active.db"))
    studio.window.show()
    observed = []
    def request_close():
        studio.window.close()
        observed.append(studio.window.isVisible())
    QtCore.QTimer.singleShot(25, request_close)
    result = studio._run_backup_job("create", store=studio.store, destination=tmp_path / "cancelled.zip")
    assert observed == [True]
    assert result["status"] == "cancelled"
    assert studio._backup_dialog is None
    application.processEvents()
    assert not studio.window.isVisible()
