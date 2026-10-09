import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import time

import pytest
from PySide6 import QtCore, QtWidgets

from tv_scan_studio.backup import BackupAttachment, BackupCancelled, create_backup, restore_backup, verify_backup
from tv_scan_studio.backup_jobs import BackupJob
from tv_scan_studio.storage import Store


def fixture(tmp_path):
    store = Store(tmp_path / "active.db")
    store.create_project("EMA", 'strategy("EMA")')
    source = tmp_path / "report.bin"
    source.write_bytes(b"report" * 300_000)
    return store, source


@pytest.mark.parametrize("phase", ["Yedek kapsamı", "Veritabanı anlık", "Veritabanı ve Pine",
                                  "Ek dosya hazırlanıyor", "Yedek ZIP", "Yedek manifesti",
                                  "Yedek dosyalarının", "Doğrulanmış yedek"])
def test_create_cancel_at_every_phase_preserves_existing_backup(tmp_path, phase):
    store, source = fixture(tmp_path)
    target = tmp_path / "existing.zip"
    create_backup(store, target)
    original = target.read_bytes()
    event = threading.Event()
    def progress(value):
        if value["stage"].startswith(phase):
            event.set()
    with pytest.raises(BackupCancelled):
        create_backup(store, target, attachments=[BackupAttachment(source, "report")],
                      check_cancel=event.is_set, progress=progress)
    assert target.read_bytes() == original
    assert source.read_bytes() == b"report" * 300_000
    assert not list(tmp_path.glob("tv-scan-backup-*"))


@pytest.mark.parametrize("phase", ["Geri yükleme hedefi", "Yedek manifesti", "Yedek dosyalarının",
                                  "Veritabanı ayrı", "Ek dosya geri", "Veritabanı bütünlüğü",
                                  "Doğrulanmış dosyalar"])
def test_restore_cancel_at_every_phase_leaves_no_published_targets(tmp_path, phase):
    store, source = fixture(tmp_path)
    backup = tmp_path / "backup.zip"
    create_backup(store, backup, attachments=[BackupAttachment(source, "report")])
    event = threading.Event()
    def progress(value):
        if value["stage"].startswith(phase):
            event.set()
    destination = tmp_path / "restored.db"
    with pytest.raises(BackupCancelled):
        restore_backup(backup, destination, check_cancel=event.is_set, progress=progress)
    assert not destination.exists()
    assert not (tmp_path / "restored-files").exists()
    assert store.projects()[0]["name"] == "EMA"


def test_cancellation_during_asset_publication_rolls_back_own_files(tmp_path, monkeypatch):
    from tv_scan_studio import backup as module
    store, source = fixture(tmp_path)
    backup = tmp_path / "backup.zip"
    create_backup(store, backup, attachments=[BackupAttachment(source, "report")])
    original_copy = module._Operation.copy
    event = threading.Event()
    def cancel_during_copy(operation, incoming, outgoing):
        if str(getattr(incoming, "name", "")).endswith("asset-0"):
            outgoing.write(b"partial")
            event.set()
        original_copy(operation, incoming, outgoing)
    monkeypatch.setattr(module._Operation, "copy", cancel_during_copy)
    with pytest.raises(BackupCancelled):
        restore_backup(backup, tmp_path / "restored.db", check_cancel=event.is_set)
    assert not (tmp_path / "restored-files").exists()
    assert not (tmp_path / "restored.db").exists()


def test_job_keeps_qt_events_alive_and_reports_cancel_without_output(tmp_path, monkeypatch):
    from tv_scan_studio import backup_jobs as module
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    entered = threading.Event()
    def cooperative_job(store, destination, *, check_cancel, progress, **kwargs):
        entered.set()
        progress({"stage": "Test aşaması", "bytes": 0})
        while not check_cancel():
            time.sleep(0.002)
        raise BackupCancelled()
    monkeypatch.setattr(module, "create_backup", cooperative_job)
    job = BackupJob("create", store=None, destination=tmp_path / "cancelled.zip")
    results, stages, ticks = [], [], []
    job.result.connect(results.append)
    job.progress.connect(stages.append)
    timer = QtCore.QTimer()
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(1)
    job.start()
    deadline = time.monotonic() + 3
    try:
        while len(ticks) < 5 and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.002)
        assert entered.is_set() and ticks and stages
        job.cancel()
        while job.isRunning() and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.002)
        assert job.wait(1000)
        application.processEvents()
        assert results == [{"status": "cancelled", "operation": "create"}]
        assert not (tmp_path / "cancelled.zip").exists()
    finally:
        timer.stop()
        job.cancel()
        job.wait(1000)


def test_job_success_and_restore_snapshot(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store, source = fixture(tmp_path)
    target = tmp_path / "backup.zip"
    job = BackupJob("create", store=store, destination=target,
                    attachments=[BackupAttachment(source, "report")])
    results = []
    job.result.connect(results.append)
    job.start()
    assert job.wait(5000)
    application.processEvents()
    assert results[0]["status"] == "ready"
    assert verify_backup(target)["attachments"]
    restored = tmp_path / "restored.db"
    job2 = BackupJob("restore", source=target, destination=restored)
    job2.result.connect(results.append)
    job2.start()
    assert job2.wait(5000)
    application.processEvents()
    assert results[-1]["status"] == "ready"
    assert Store(restored).projects()[0]["name"] == "EMA"
