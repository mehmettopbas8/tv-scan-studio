import zipfile

import pytest

from tv_scan_studio.backup import create_backup, verify_backup
from tv_scan_studio.storage import Store


def test_backup_contains_consistent_database_and_pine_sources(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Backup", 'strategy("Backup")')
    store.enqueue(project, "one", {"symbol": "OANDA:EURUSD"})
    destination = tmp_path / "backup.tvscan.zip"
    manifest = create_backup(store, destination)
    verified = verify_backup(destination)
    assert manifest["project_count"] == 1
    assert verified["files"] == manifest["files"]
    with zipfile.ZipFile(destination) as archive:
        assert archive.read(f"pine/project-{project}.pine").decode() == 'strategy("Backup")'


def test_backup_verification_rejects_tampering(tmp_path):
    store = Store(tmp_path / "studio.db")
    store.create_project("Backup", 'strategy("Backup")')
    destination = tmp_path / "backup.tvscan.zip"
    create_backup(store, destination)
    with zipfile.ZipFile(destination) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    contents["database/tv-scan-studio.db"] = b"tampered"
    with zipfile.ZipFile(destination, "w") as archive:
        for name, value in contents.items():
            archive.writestr(name, value)
    with pytest.raises(ValueError, match="checksum"):
        verify_backup(destination)
