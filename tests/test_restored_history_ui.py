"""Restored history must reopen without its original installation directory."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets as Q

from tv_scan_studio.backup import BackupAttachment, create_backup, restore_backup
from tv_scan_studio.historical_dialog import HistoricalDialog
from tv_scan_studio.research_archives import import_archive
from tv_scan_studio.storage import Store
from test_historical_dialog import wait_load


def test_restored_history_dialog_reopens_after_original_directory_moves(tmp_path):
    app = Q.QApplication.instance() or Q.QApplication([])
    original = tmp_path / "original"
    original.mkdir()
    store = Store(original / "studio.db")
    source = original / "history.jsonl"
    source.write_text(json.dumps({"symbol": "BIST:XU030D1!", "tf": "15",
                                 "valid": True, "pass": True,
                                 "params": {"emaFastLen": 8},
                                 "metrics": {"pf": 1.5, "dd": 2}}), encoding="utf-8")
    imported = import_archive(source, original / "research-archives")
    store.save_app_settings({"historical_archive_path": str(imported["path"].resolve())})
    backup = tmp_path / "portable.zip"
    create_backup(store, backup, attachments=[BackupAttachment(imported["path"], "archive")])
    destination = tmp_path / "restored" / "studio.db"
    restore_backup(backup, destination)
    # Move only this test's temporary directory; the old absolute reference is unavailable.
    original.rename(tmp_path / "original-unavailable")
    restored = Store(destination)
    dialog = HistoricalDialog(restored)
    try:
        wait_load(dialog, app)
        assert len(dialog.rows) == 1
        assert dialog.rows[0]["payload"]["symbol"] == "BIST:XU030D1!"
        assert "Yeniden doğrulanmadı" in dialog.status.text()
        assert restored.projects() == []
        with restored.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    finally:
        dialog.close()
        app.processEvents()


def test_restore_status_distinguishes_archive_access_from_live_verification(tmp_path, monkeypatch):
    from tv_scan_studio.app import StudioWindow
    app = Q.QApplication.instance() or Q.QApplication([])
    original = tmp_path / "source-install"
    original.mkdir()
    store = Store(original / "studio.db")
    source = original / "history.jsonl"
    source.write_text(json.dumps({"symbol": "TEST:DEMO", "tf": "15", "params": {},
                                 "valid": True, "metrics": {"pf": 1.5}}), encoding="utf-8")
    imported = import_archive(source, original / "research-archives")
    store.save_app_settings({"historical_archive_path": str(imported["path"].resolve())})
    backup = tmp_path / "portable.zip"
    create_backup(store, backup, attachments=[BackupAttachment(imported["path"], "archive")])
    destination = tmp_path / "different-install" / "studio.db"
    monkeypatch.setattr(Q.QFileDialog, "getOpenFileName", lambda *args: (str(backup), ""))
    monkeypatch.setattr(Q.QFileDialog, "getSaveFileName", lambda *args: (str(destination), ""))
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    try:
        studio.restore_portable_backup()
        message = studio.dashboard_status.text()
        assert "yeni veri alanında açılabilir" in message
        assert "yeni TradingView sonuçları veya görevler sayılmadı" in message
        assert "otomatik geçilmedi" in message
        assert "otomatik içe aktarılmadı" not in message
        assert studio.store.path == store.path
        assert store.app_settings()["historical_archive_path"] == str(imported["path"].resolve())
    finally:
        studio.window.close()
        app.processEvents()
