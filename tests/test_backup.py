import zipfile

import pytest

from tv_scan_studio.backup import create_backup, verify_backup, restore_backup
from tv_scan_studio.storage import Store


@pytest.mark.parametrize("source", ['strategy("LF")\nsize=input.int(1,"Size")\n',
                                    'strategy("CRLF")\r\nsize=input.int(1,"Size")\r\n'])
def test_backup_preserves_exact_pine_line_endings(tmp_path, source):
    store = Store(tmp_path / "lines.db")
    project = store.create_project("Lines", source)
    backup = tmp_path / "lines.zip"
    manifest = create_backup(store, backup)
    assert manifest["pine_newlines"] == "preserved"
    with zipfile.ZipFile(backup) as archive:
        assert archive.read(f"pine/project-{project}.pine") == source.encode()
    restore_backup(backup, tmp_path / "restored.db")


def test_legacy_windows_newline_translated_backup_restores(tmp_path):
    import hashlib
    import json
    source = 'strategy("Legacy")\nsize=input.int(1,"Size")\n'
    store = Store(tmp_path / "legacy.db")
    project = store.create_project("Legacy", source)
    backup = tmp_path / "legacy.zip"
    create_backup(store, backup)
    with zipfile.ZipFile(backup) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(contents["manifest.json"])
    del manifest["pine_newlines"]
    name = f"pine/project-{project}.pine"
    contents[name] = source.encode().replace(b"\n", b"\r\n")
    manifest["files"][name] = hashlib.sha256(contents[name]).hexdigest()
    contents["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(backup, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    restored_path = tmp_path / "restored.db"
    restore_backup(backup, restored_path)
    assert Store(restored_path).project(project)["pine_source"] == source


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


def test_pine_files_use_the_same_database_snapshot(tmp_path, monkeypatch):
    store = Store(tmp_path / "snapshot.db")
    project = store.create_project("Snapshot", 'strategy("Snapshot")')
    def refuse_live_reads(*args):
        raise AssertionError("Pine sources must come from the backed-up snapshot")
    monkeypatch.setattr(store, "projects", refuse_live_reads)
    monkeypatch.setattr(store, "project", refuse_live_reads)
    backup = tmp_path / "snapshot.zip"
    create_backup(store, backup)
    with zipfile.ZipFile(backup) as archive:
        assert archive.read(f"pine/project-{project}.pine").decode() == 'strategy("Snapshot")'


def test_restore_preserves_finished_results_and_recovers_running_only_on_startup(tmp_path):
    store = Store(tmp_path / "original.db")
    project = store.create_project("Restore", 'strategy("Restore")')
    store.enqueue(project, "done", {"symbol": "OANDA:EURUSD"})
    done = store.claim_next(1)
    store.complete(done.id, 1, {"trades": 7}, "hassas", verified=True)
    store.enqueue(project, "running", {"symbol": "OANDA:SPX500USD"})
    store.claim_next(2)
    backup = tmp_path / "backup.zip"
    create_backup(store, backup)
    output = tmp_path / "new" / "restored.db"
    restore_backup(backup, output)
    restored = Store(output)
    assert restored.counts(project) == {"done": 1, "running": 1}
    assert restored.results(project) == store.results(project)
    assert restored.recover_interrupted() == 1
    assert restored.counts(project) == {"done": 1, "pending": 1}
    assert store.counts(project) == {"done": 1, "running": 1}
    assert restored.results(project) == store.results(project)
    with pytest.raises(FileExistsError):
        restore_backup(backup, output)


def test_restore_rejects_invalid_database_without_creating_target(tmp_path):
    import hashlib
    import json
    backup = tmp_path / "invalid.zip"
    data = b"not a database"
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("database/tv-scan-studio.db", data)
        archive.writestr("manifest.json", json.dumps({"format": 1,
            "files": {"database/tv-scan-studio.db": hashlib.sha256(data).hexdigest()}}))
    output = tmp_path / "restored.db"
    import sqlite3
    with pytest.raises(sqlite3.DatabaseError):
        restore_backup(backup, output)
    assert not output.exists()


@pytest.mark.parametrize("mismatch", ["source", "count", "missing"])
def test_restore_rejects_consistent_checksums_but_inconsistent_projects(tmp_path, mismatch):
    import hashlib
    import json
    store = Store(tmp_path / "projects.db")
    project = store.create_project("Pine", 'strategy("Pine")')
    backup = tmp_path / "mismatch.zip"
    create_backup(store, backup)
    with zipfile.ZipFile(backup) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(contents["manifest.json"])
    pine = f"pine/project-{project}.pine"
    if mismatch == "source":
        contents[pine] = b'strategy("Other")'
        manifest["files"][pine] = hashlib.sha256(contents[pine]).hexdigest()
    elif mismatch == "count":
        manifest["project_count"] += 1
    else:
        del contents[pine]
        del manifest["files"][pine]
    contents["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(backup, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    verify_backup(backup)
    destination = tmp_path / "restored.db"
    with pytest.raises(ValueError, match="veritabanıyla uyuşmuyor"):
        restore_backup(backup, destination)
    assert not destination.exists()
