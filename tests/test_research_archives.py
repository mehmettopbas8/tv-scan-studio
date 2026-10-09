import gzip
import hashlib
import json
from pathlib import Path

import pytest

from tv_scan_studio.research_archives import ArchiveCancelled, import_archive, list_archives, verify_managed_archive


def row(phase=None, period=None, pine=None):
    return {"symbol": "BIST:XU030D1!", "tf": "15", "valid": True, "pass": True,
            "params": {"in_0": 8}, "metrics": {"pf": 1.5}, "phase": phase,
            "period": {"dateRange": {"backtest": period or {}}}, "pine_sha256": pine}


def write(path, rows):
    data = "\n".join(json.dumps(item) for item in rows).encode()
    path.write_bytes(gzip.compress(data) if path.suffix == ".gz" else data)
    return path.read_bytes()


def test_manifest_preserves_phases_period_source_counts_and_idempotence(tmp_path):
    source = tmp_path / "original.jsonl.gz"
    data = write(source, [row("baseline", {"from": 1, "to": 2}, "a" * 64),
                          row("heavy", {"from": 1, "to": 2}, "a" * 64),
                          row("provider", {"from": 2, "to": 3}), row()])
    root = tmp_path / "application-data" / "research-archives"
    first = import_archive(source, root)
    second = import_archive(source, root)
    assert not first["reused"] and second["reused"]
    assert first["path"] == second["path"]
    assert source.read_bytes() == data == first["path"].read_bytes()
    manifest = first["manifest"]
    assert manifest["sha256"] == hashlib.sha256(data).hexdigest()
    assert manifest["record_count"] == 4
    assert manifest["phases"] == {"baseline": 1, "heavy": 1, "provider": 1, "unknown": 1}
    assert manifest["pine_sources"] == {"a" * 64: 2, "unknown": 2}
    assert sum(item["records"] for item in manifest["periods"]) == 4
    assert manifest["verification"] == "historical_unverified"
    assert len(list_archives(root)) == 1
    source.unlink()  # Simulate original being moved/deleted outside the application.
    assert verify_managed_archive(first["path"].parent)["record_count"] == 4


def test_identical_rows_in_separate_phase_files_are_not_silently_merged(tmp_path):
    root = tmp_path / "managed"
    paths = [tmp_path / "normal.jsonl", tmp_path / "heavy.jsonl"]
    for path, phase in zip(paths, ("baseline", "heavy")):
        write(path, [row(phase)])
        import_archive(path, root)
        import_archive(path, root)
    manifests = list_archives(root)
    assert len(manifests) == 2
    assert sum(item["record_count"] for item in manifests) == 2


def test_invalid_or_cancelled_import_has_no_published_archive(tmp_path):
    root = tmp_path / "managed"
    source = tmp_path / "bad.jsonl"
    source.write_text('{"params": {}}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        import_archive(source, root)
    assert list(root.iterdir()) == []
    write(source, [row() for _ in range(300)])
    cancelled = False
    def progress(value):
        nonlocal cancelled
        if value.get("records") == 256:
            cancelled = True
    with pytest.raises(ArchiveCancelled):
        import_archive(source, root, cancel_requested=lambda: cancelled, progress=progress)
    assert list(root.iterdir()) == []
    assert source.exists()


@pytest.mark.parametrize("damage", ["bytes", "counts", "phase", "filename", "bool_count", "identity"])
def test_managed_archive_revalidated_on_reopen(tmp_path, damage):
    source = tmp_path / "source.jsonl"
    write(source, [row("heavy")])
    result = import_archive(source, tmp_path / "managed")
    directory = result["path"].parent
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if damage == "bytes":
        result["path"].write_bytes(b"broken")
    elif damage == "counts":
        manifest["record_count"] += 1
    elif damage == "phase":
        manifest["phases"] = {"baseline": 1}
    elif damage == "bool_count":
        manifest["record_count"] = True
    elif damage == "identity":
        manifest["archive_id"] = "a" * 64
    else:
        manifest["archive_file"] = "../../original.jsonl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_managed_archive(directory)
    assert source.exists()
