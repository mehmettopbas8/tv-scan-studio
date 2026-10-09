import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from tv_scan_studio.backup import BackupAttachment, create_backup, restore_backup, verify_backup
from tv_scan_studio.storage import Store


def setup(tmp_path):
    store = Store(tmp_path / "active.db")
    project = store.create_project("Backup", 'strategy("Backup")')
    return store, project


def rewrite(source, transform):
    with zipfile.ZipFile(source) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(contents["manifest.json"])
    transform(contents, manifest)
    contents["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(source, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)


def test_selected_assets_restore_without_touching_originals_and_history_preserved(tmp_path):
    store, project = setup(tmp_path)
    store.enqueue(project, "task", {"inputs": {}})
    task = store.claim_next(1)
    store.complete(task.id, 1, {"trades": 10}, "hassas", verified=True)
    files = []
    for category in ("archive", "report", "evidence"):
        directory = tmp_path / category
        directory.mkdir()
        path = directory / "same-name.bin"
        path.write_bytes(category.encode())
        files.append(BackupAttachment(path, category))
    backup = tmp_path / "backup.zip"
    manifest = create_backup(store, backup, attachments=files)
    assert manifest["format"] == 3
    assert len(manifest["attachments"]) == 3
    assert all("path" not in item for item in manifest["attachments"])
    verified = verify_backup(backup)
    restored_path = tmp_path / "new" / "restored.db"
    result = restore_backup(backup, restored_path)
    restored = Store(restored_path)
    assert restored.result_history(task.id) == store.result_history(task.id)
    assert restored.attempt_history(task.id) == store.attempt_history(task.id)
    assert len(result["restored_attachments"]) == 3
    for descriptor, restored_file, original in zip(verified["attachments"], result["restored_attachments"], files):
        assert Path(restored_file).read_bytes() == original.path.read_bytes()
        assert hashlib.sha256(Path(restored_file).read_bytes()).hexdigest() == verified["files"][descriptor["member"]]
        assert Path(restored_file).is_relative_to(tmp_path / "new" / "restored-files")
    assert store.project(project)["name"] == "Backup"


def test_missing_and_duplicate_selection_preserve_existing_backup(tmp_path):
    store, _ = setup(tmp_path)
    backup = tmp_path / "old.zip"
    create_backup(store, backup)
    before = backup.read_bytes()
    source = tmp_path / "source.txt"
    source.write_text("report")
    for choices in ([BackupAttachment(tmp_path / "missing", "report")],
                    [BackupAttachment(source, "report"), BackupAttachment(source, "evidence")],
                    [BackupAttachment(source, "unsupported")], [BackupAttachment(backup, "archive")]):
        with pytest.raises(ValueError):
            create_backup(store, backup, attachments=choices)
        assert backup.read_bytes() == before


def test_copying_changed_source_does_not_replace_existing_backup(tmp_path, monkeypatch):
    store, _ = setup(tmp_path)
    backup = tmp_path / "old.zip"
    create_backup(store, backup)
    before = backup.read_bytes()
    source = tmp_path / "report.txt"
    source.write_text("original")
    real_copy = shutil.copyfile
    def changed(original, destination):
        result = real_copy(original, destination)
        Path(original).write_text("changed")
        return result
    monkeypatch.setattr(shutil, "copyfile", changed)
    with pytest.raises(ValueError, match="değişti"):
        create_backup(store, backup, attachments=[BackupAttachment(source, "report")])
    assert backup.read_bytes() == before


@pytest.mark.parametrize("damage", ["missing", "checksum", "size", "undeclared"])
def test_damaged_attachment_rejects_before_creating_targets(tmp_path, damage):
    store, _ = setup(tmp_path)
    source = tmp_path / "report.txt"
    source.write_text("report")
    backup = tmp_path / "backup.zip"
    create_backup(store, backup, attachments=[BackupAttachment(source, "report")])
    def mutate(contents, manifest):
        name = manifest["attachments"][0]["member"]
        if damage == "missing":
            del contents[name]
        elif damage == "checksum":
            contents[name] = b"broken"
        elif damage == "size":
            manifest["attachments"][0]["size"] += 1
        else:
            manifest["attachments"] = []
    rewrite(backup, mutate)
    destination = tmp_path / "new" / "restored.db"
    with pytest.raises(ValueError):
        restore_backup(backup, destination)
    assert not destination.exists()
    assert not destination.with_name("restored-files").exists()


@pytest.mark.parametrize("member", ["attachments/report/../bad", "attachments/report/CON.txt",
                                    "attachments/report/bad. ", "C:/bad", "attachments\\report\\bad"])
def test_unsafe_members_rejected(tmp_path, member):
    store, _ = setup(tmp_path)
    source = tmp_path / "report.txt"
    source.write_text("report")
    backup = tmp_path / "backup.zip"
    create_backup(store, backup, attachments=[BackupAttachment(source, "report")])
    def mutate(contents, manifest):
        old = manifest["attachments"][0]["member"]
        manifest["attachments"][0]["member"] = member
        contents[member] = contents.pop(old)
        manifest["files"][member] = manifest["files"].pop(old)
    rewrite(backup, mutate)
    with pytest.raises(ValueError):
        restore_backup(backup, tmp_path / "restored.db")
    assert not (tmp_path / "restored.db").exists()


def test_asset_publication_failure_cleans_only_owned_files(tmp_path, monkeypatch):
    store, _ = setup(tmp_path)
    source = tmp_path / "report.txt"
    source.write_text("report")
    backup = tmp_path / "backup.zip"
    create_backup(store, backup, attachments=[BackupAttachment(source, "report")])
    real_copy = shutil.copyfileobj
    def fail_publish(incoming, outgoing, *args):
        if str(getattr(incoming, "name", "")).endswith("asset-0"):
            outgoing.write(b"partial")
            raise OSError("copy failed")
        return real_copy(incoming, outgoing, *args)
    monkeypatch.setattr(shutil, "copyfileobj", fail_publish)
    with pytest.raises(OSError, match="copy failed"):
        restore_backup(backup, tmp_path / "restored.db")
    assert not (tmp_path / "restored.db").exists()
    assert not (tmp_path / "restored-files").exists()
    assert source.read_text() == "report"
    assert store.projects()


def test_legacy_v1_and_existing_resource_directory_are_preserved(tmp_path):
    store, _ = setup(tmp_path)
    backup = tmp_path / "legacy.zip"
    create_backup(store, backup)
    def v1(_contents, manifest):
        manifest["format"] = 1
        manifest.pop("attachments")
    rewrite(backup, v1)
    assert verify_backup(backup)["format"] == 1
    restore_backup(backup, tmp_path / "legacy-restored.db")
    report = tmp_path / "report.txt"
    report.write_text("report")
    create_backup(store, backup, attachments=[BackupAttachment(report, "report")])
    existing = tmp_path / "restored-files"
    existing.mkdir()
    sentinel = existing / "user.txt"
    sentinel.write_text("keep")
    with pytest.raises(FileExistsError):
        restore_backup(backup, tmp_path / "restored.db")
    assert sentinel.read_text() == "keep"
    assert not (tmp_path / "restored.db").exists()
