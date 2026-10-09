from dataclasses import replace
import json
import threading
import zipfile

import pytest

from tv_scan_studio import support_package as module
from tv_scan_studio.storage import Store


def test_default_diagnostics_only_export_allowlisted_counts(tmp_path):
    store = Store(tmp_path / "private-account.db")
    store.create_project("SECRET ACCOUNT", 'strategy("SECRET CODE")')
    store.save_app_settings({"secret": "SECRET TOKEN"})
    items = module.diagnostic_items(store)
    target = tmp_path / "support.zip"
    manifest = module.create_support_zip(items, target)
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == {item.name for item in items} | {"manifest.json"}
        content = b"".join(archive.read(name) for name in archive.namelist())
        assert b"SECRET" not in content
        assert str(tmp_path).encode() not in content
        assert json.loads(archive.read("diagnostics/counts.json"))["projects"] == 1
        assert json.loads(archive.read("manifest.json")) == manifest
    assert manifest["automatic_upload"] is False
    assert store.projects()[0]["name"] == "SECRET ACCOUNT"


def test_explicit_selection_exports_exact_preview_bytes_only(tmp_path):
    chosen = tmp_path / "chosen.txt"
    chosen.write_bytes(b"selected" * 20000)
    excluded = tmp_path / "excluded.txt"
    excluded.write_bytes(b"NOT SELECTED")
    selected = module.file_item(chosen, 1)
    assert len(selected.preview) == module.PREVIEW_BYTES
    manifest = module.create_support_zip([selected], tmp_path / "selected.zip")
    with zipfile.ZipFile(tmp_path / "selected.zip") as archive:
        assert archive.read(selected.name) == chosen.read_bytes()
        assert len(archive.namelist()) == 2
    assert manifest["files"][0]["sha256"] == selected.sha256
    assert excluded.read_bytes() == b"NOT SELECTED"


@pytest.mark.parametrize("change", ["same_size", "grow", "delete"])
def test_changed_preview_is_not_published(tmp_path, change):
    source = tmp_path / "source.txt"
    source.write_bytes(b"original")
    item = module.file_item(source, 1)
    if change == "delete":
        source.unlink()
    else:
        source.write_bytes(b"modified" if change == "same_size" else b"much bigger modified")
    with pytest.raises((ValueError, FileNotFoundError)):
        module.create_support_zip([item], tmp_path / "new.zip")
    assert not (tmp_path / "new.zip").exists()
    assert not list(tmp_path.glob(".tvscan-support-*"))


@pytest.mark.parametrize("stage", ["Seçilen içerikler", "ZIP içeriği"])
def test_cancel_during_write_or_verification_removes_owned_temporary(tmp_path, stage):
    event = threading.Event()
    item = module.generated_item("test", "Test", {"text": "x" * 2000000})
    def progress(value):
        if value["stage"].startswith(stage):
            event.set()
    with pytest.raises(module.SupportCancelled):
        module.create_support_zip([item], tmp_path / "cancelled.zip", cancel=event.is_set, progress=progress)
    assert not (tmp_path / "cancelled.zip").exists()
    assert not list(tmp_path.glob(".tvscan-support-*"))


def test_existing_or_racing_destination_is_never_overwritten(tmp_path, monkeypatch):
    item = module.generated_item("test", "Test", {})
    destination = tmp_path / "existing.zip"
    destination.write_bytes(b"existing")
    with pytest.raises(ValueError):
        module.create_support_zip([item], destination)
    assert destination.read_bytes() == b"existing"
    destination = tmp_path / "race.zip"
    publish = module.publish_new
    def racing_link(source, target):
        target.write_bytes(b"other writer")
        publish(source, target)
    monkeypatch.setattr(module, "publish_new", racing_link)
    with pytest.raises(FileExistsError):
        module.create_support_zip([item], destination)
    assert destination.read_bytes() == b"other writer"
    assert not list(tmp_path.glob(".tvscan-support-*"))


@pytest.mark.parametrize("name", ["../private", "/absolute", "files/../private", "files/a:b",
                                  "files/a\\b", "files//duplicate", "files/a\n", "manifest.json"])
def test_unsafe_names_rejected_before_io(tmp_path, name):
    item = replace(module.generated_item("test", "Test", {}), name=name)
    with pytest.raises(ValueError):
        module.create_support_zip([item], tmp_path / "invalid.zip")
    assert not list(tmp_path.glob(".tvscan-support-*"))


@pytest.mark.parametrize("items", [[], [object()], [None]])
def test_invalid_selection_has_explanatory_error(tmp_path, items):
    with pytest.raises(ValueError):
        module.create_support_zip(items, tmp_path / "invalid.zip")


def test_duplicate_or_mutated_generated_content_rejected(tmp_path):
    item = module.generated_item("test", "Test", {})
    with pytest.raises(ValueError):
        module.create_support_zip([item, item], tmp_path / "duplicate.zip")
    with pytest.raises(ValueError, match="Önizlemeden"):
        module.create_support_zip([replace(item, content=b"changed")], tmp_path / "changed.zip")
    assert not (tmp_path / "changed.zip").exists()
    assert not list(tmp_path.glob(".tvscan-support-*"))


def test_publication_failure_cleans_up(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("publication unavailable")
    monkeypatch.setattr(module, "publish_new", fail)
    with pytest.raises(OSError):
        module.create_support_zip([module.generated_item("test", "Test", {})], tmp_path / "new.zip")
    assert not (tmp_path / "new.zip").exists()
    assert not list(tmp_path.glob(".tvscan-support-*"))
