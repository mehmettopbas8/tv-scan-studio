import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store
from tv_scan_studio.backup import verify_backup
from tv_scan_studio.backup import create_backup
import pytest


def test_task_filters_and_backup_restore_inside_dialog(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "active.db")
    project = store.create_project("EMA", 'strategy("EMA")\nn=input.int(8,"Fast EMA")')
    store.enqueue(project, "done", {"symbol": "BIST:XU030D1!", "timeframe": "15", "inputs": {"in_0": 9}})
    task = store.claim_next(1, [project])
    store.complete(task.id, 1, {"profit_factor": 1.1}, "hassas", verified=True)
    store.save_result_preset(project, task.id, "EMA 9")
    store.enqueue(project, "pending", {"symbol": "BIST:XU030D1!", "timeframe": "15"})
    backup = tmp_path / "backup.tvscan.zip"
    restored = tmp_path / "restored.db"
    choices = iter((str(backup), str(restored)))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *args: (next(choices), ""))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *args: (str(backup), ""))
    studio = StudioWindow(store)
    before = store.counts(project)
    real_exec = QtWidgets.QDialog.exec
    def inspect(dialog):
        from tv_scan_studio.backup_dialog import BackupProgressDialog
        if isinstance(dialog, BackupProgressDialog):
            return real_exec(dialog)
        dialog.show(); application.processEvents()
        table = dialog.findChild(QtWidgets.QTableWidget, "backupTaskTable")
        states = dialog.findChild(QtWidgets.QComboBox, "backupTaskState")
        assert table.isVisible() and table.rowCount() == 2
        states.setCurrentIndex(states.findData("pending"))
        assert table.rowCount() == 1 and table.item(0, 1).text() == "Bekleyen"
        states.setCurrentIndex(states.findData("done"))
        assert table.rowCount() == 1 and table.item(0, 1).text() == "Tamamlanan"
        dialog.findChild(QtWidgets.QPushButton, "createTaskBackup").click()
        assert verify_backup(backup)["project_count"] == 1
        status = dialog.findChild(QtWidgets.QLabel, "backupOperationStatus")
        assert "doğrulandı" in status.text()
        dialog.findChild(QtWidgets.QPushButton, "restoreTaskBackup").click()
        assert "otomatik geçilmedi" in status.text()
        assert Store(restored).saved_presets()[0]["name"] == "EMA 9"
        assert store.counts(project) == before
        assert studio.store.path == store.path
        from tv_scan_studio.backup_selection import BackupSelection
        selection = dialog.findChild(BackupSelection)
        report = tmp_path / "selected-report.csv"
        report.write_text("PF,1.4", encoding="utf-8")
        selection.add_paths([report], "report")
        monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *args: (str(backup), ""))
        dialog.findChild(QtWidgets.QPushButton, "createTaskBackup").click()
        assert len(verify_backup(backup)["attachments"]) == 1
        assert "1 ek dosya" in status.text()
        second_restore = tmp_path / "with-files.db"
        monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *args: (str(second_restore), ""))
        dialog.findChild(QtWidgets.QPushButton, "restoreTaskBackup").click()
        assert "1 ek dosya ayrı klasöre" in status.text()
        assert "otomatik içe aktarılmadı" in status.text()
        assert list((tmp_path / "with-files-files" / "report").iterdir())[0].read_bytes() == report.read_bytes()
        dialog.hide()
        return 0
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        button = next(button for button in studio.window.findChildren(QtWidgets.QPushButton)
                      if button.text() == "Görevler ve yedekleme")
        button.click()
    finally:
        studio.window.close()


def test_backup_rejects_active_database_target(tmp_path):
    store = Store(tmp_path / "active.db")
    store.create_project("Preserved", 'strategy("Preserved")')
    for target in (store.path, str(store.path) + "-wal", str(store.path) + "-shm"):
        with pytest.raises(ValueError, match="aktif veritabanı"):
            create_backup(store, target)
    assert store.projects()[0]["name"] == "Preserved"
