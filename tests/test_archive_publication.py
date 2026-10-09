from pathlib import Path
import json

import pytest

from tv_scan_studio import research_archives as archives


def windows_error(code=5):
    error = PermissionError("simulated directory publication failure")
    error.winerror = code
    return error


@pytest.mark.parametrize("code", [5, 32, 33])
def test_transient_windows_error_retries_atomic_rename(tmp_path, monkeypatch, code):
    owned, target = tmp_path / "ready", tmp_path / "published"
    owned.mkdir()
    (owned / "source").write_text("unchanged")
    attempts, sleeps, successes = [], [], []
    def rename(self, destination):
        attempts.append(destination)
        if len(attempts) < 3:
            raise windows_error(code)
        # Isolate retry scheduling from an additional real Windows lock.
        successes.append((self, destination))
        return destination
    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(archives.time, "sleep", sleeps.append)
    archives._publish_archive(owned, target)
    assert len(attempts) == 3 and sleeps == [0.05, 0.1]
    assert successes == [(owned, target)]
    assert (owned / "source").read_text() == "unchanged"
    assert not target.exists()


def test_real_publication_after_transient_errors_uses_product_waits(tmp_path, monkeypatch):
    owned, target = tmp_path / "ready", tmp_path / "published"
    owned.mkdir()
    (owned / "source").write_text("unchanged")
    original = Path.rename
    attempts = []
    def rename(self, destination):
        attempts.append(destination)
        if len(attempts) < 3:
            raise windows_error()
        return original(self, destination)
    monkeypatch.setattr(Path, "rename", rename)
    # Do not mock sleep: the real filesystem uses the bounded product recovery.
    archives._publish_archive(owned, target)
    assert 3 <= len(attempts) <= 4
    assert (target / "source").read_text() == "unchanged"
    assert not owned.exists()


def test_permanent_windows_error_exhausts_bounded_attempts(tmp_path, monkeypatch):
    owned, target = tmp_path / "ready", tmp_path / "published"
    owned.mkdir()
    error, attempts, sleeps = windows_error(), [], []
    def rename(self, destination):
        attempts.append(destination)
        raise error
    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(archives.time, "sleep", sleeps.append)
    with pytest.raises(PermissionError) as caught:
        archives._publish_archive(owned, target)
    assert caught.value is error
    assert len(attempts) == 4 and sleeps == [0.05, 0.1, 0.2]
    assert owned.exists() and not target.exists()


def test_non_windows_permission_error_is_not_retried(tmp_path, monkeypatch):
    owned, target = tmp_path / "ready", tmp_path / "published"
    owned.mkdir()
    attempts = []
    def rename(self, destination):
        attempts.append(destination)
        raise PermissionError("permanent policy denial")
    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(PermissionError):
        archives._publish_archive(owned, target)
    assert len(attempts) == 1


def test_cancellation_during_retry_does_not_publish(tmp_path, monkeypatch):
    owned, target = tmp_path / "ready", tmp_path / "published"
    owned.mkdir()
    cancelled = False
    def rename(self, destination):
        raise windows_error()
    def sleep(seconds):
        nonlocal cancelled
        cancelled = True
    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(archives.time, "sleep", sleep)
    with pytest.raises(archives.ArchiveCancelled):
        archives._publish_archive(owned, target, lambda: cancelled)
    assert owned.exists() and not target.exists()


def test_concurrent_publication_is_not_overwritten(tmp_path, monkeypatch):
    owned, target = tmp_path / "ready", tmp_path / "published"
    owned.mkdir()
    attempts = []
    def rename(self, destination):
        attempts.append(destination)
        target.mkdir()
        (target / "source").write_text("concurrent original")
        raise windows_error()
    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(PermissionError):
        archives._publish_archive(owned, target)
    assert len(attempts) == 1
    assert (target / "source").read_text() == "concurrent original"
    assert owned.exists()


def test_already_existing_empty_directory_is_not_replaced(tmp_path):
    owned, target = tmp_path / "ready", tmp_path / "published"
    owned.mkdir()
    target.mkdir()
    with pytest.raises(FileExistsError):
        archives._publish_archive(owned, target)
    assert owned.exists() and list(target.iterdir()) == []


def test_import_revalidates_concurrent_archive_and_reuses_it(tmp_path, monkeypatch):
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps({"symbol": "BIST:XU030D1!", "tf": "15",
                                 "valid": True, "params": {"in_0": 8},
                                 "metrics": {"pf": 1.5}}))
    original = Path.rename
    def rename(self, destination):
        original(self, destination)  # Simulate another importer winning publication.
        raise windows_error()
    monkeypatch.setattr(Path, "rename", rename)
    result = archives.import_archive(source, tmp_path / "managed")
    assert result["reused"] is True
    assert archives.verify_managed_archive(result["path"].parent)["record_count"] == 1
    assert result["path"].read_bytes() == source.read_bytes()
