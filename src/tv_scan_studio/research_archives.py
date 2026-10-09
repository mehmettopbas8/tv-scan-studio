"""Content-addressed local research archives; import never upgrades verification."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time

from .historical import iter_legacy_scan_records


class ArchiveCancelled(Exception):
    pass


def _check(cancel_requested):
    if cancel_requested and cancel_requested():
        raise ArchiveCancelled("Arşiv aktarımı iptal edildi.")


def _publish_archive(owned, target, cancel_requested=None):
    """Bound transient Windows rename failures without replacing an archive.

    Access denied can also be permanent: four attempts over 350 ms are a
    recovery opportunity, not an assertion about the cause of the failure.
    """
    delays = (0.05, 0.1, 0.2)
    for attempt in range(len(delays) + 1):
        _check(cancel_requested)
        if target.exists():
            raise FileExistsError("Arşiv başka bir aktarım tarafından yayımlandı.")
        try:
            owned.rename(target)
            return
        except OSError as error:
            if (target.exists() or getattr(error, "winerror", None) not in {5, 32, 33}
                    or attempt == len(delays)):
                raise
            _check(cancel_requested)
            time.sleep(delays[attempt])


def _hash(path, cancel_requested=None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            _check(cancel_requested)
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _period_key(period):
    # Missing evidence stays missing; file names and summary totals are not evidence.
    return json.dumps(period or None, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def inspect_archive(path, *, cancel_requested=None, progress=None):
    phases, periods, classifications, pine_sources = Counter(), Counter(), Counter(), Counter()
    count = 0
    for row in iter_legacy_scan_records(path, check_cancel=lambda: _check(cancel_requested)):
        _check(cancel_requested)
        count += 1
        phases[row["payload"].get("source_phase") or "unknown"] += 1
        periods[_period_key(row["payload"].get("date_range"))] += 1
        classifications[row["classification"]] += 1
        pine_sources[row["evidence"].get("historical_pine_sha256") or "unknown"] += 1
        if progress and count % 256 == 0:
            progress({"stage": "Arşiv kayıtları kontrol ediliyor", "records": count})
    if not count:
        raise ValueError("Arşivde tarama kaydı yok.")
    return {"record_count": count, "phases": dict(phases),
            "periods": [{"period": json.loads(key), "records": value} for key, value in sorted(periods.items())],
            "classifications": dict(classifications), "pine_sources": dict(pine_sources),
            "verification": "historical_unverified"}


def _read_manifest(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Arşiv klasörü eksik veya bağlantı.")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 16_000_000:
        raise ValueError("Arşiv manifesti eksik veya geçersiz.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or type(manifest.get("format")) is not int or manifest.get("format") != 1
            or manifest.get("archive_file") not in {"source.jsonl", "source.jsonl.gz"}
            or manifest.get("archive_id") != directory.name):
        raise ValueError("Arşiv manifesti geçersiz.")
    if len(directory.name) != 64 or any(c not in "0123456789abcdef" for c in directory.name):
        raise ValueError("Arşiv kaynak kimliği geçersiz.")
    if manifest.get("sha256") != manifest["archive_id"]:
        raise ValueError("Arşiv kaynak kimliği checksum ile uyuşmuyor.")
    return manifest


def verify_managed_archive(directory, *, cancel_requested=None):
    directory = Path(directory)
    manifest = _read_manifest(directory)
    path = directory / manifest["archive_file"]
    if path.is_symlink() or not path.is_file() or path.stat().st_size != manifest.get("size"):
        raise ValueError("Arşiv dosyası eksik veya boyutu değişmiş.")
    if _hash(path, cancel_requested) != manifest.get("sha256"):
        raise ValueError("Arşiv checksum uyuşmuyor; kopya değiştirilmiş.")
    observed = inspect_archive(path, cancel_requested=cancel_requested)
    archived = {key: manifest.get(key) for key in observed}
    if json.dumps(archived, sort_keys=True) != json.dumps(observed, sort_keys=True):
        raise ValueError("Arşiv manifestindeki kayıt sayıları veya kapsam dosyayla uyuşmuyor.")
    return manifest


def archive_catalog(root, *, cancel_requested=None):
    """Metadata inventory, not file verification. A bad entry cannot hide good ones."""
    root = Path(root)
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Arşiv veri klasörü geçersiz.")
    entries = []
    for directory in sorted(root.iterdir()):
        _check(cancel_requested)
        if len(directory.name) != 64 or any(c not in "0123456789abcdef" for c in directory.name):
            continue
        try:
            manifest = _read_manifest(directory)
            if (not isinstance(manifest.get("source_name"), str) or
                    type(manifest.get("record_count")) is not int or manifest["record_count"] < 1 or
                    not isinstance(manifest.get("phases"), dict) or
                    any(not isinstance(phase, str) or type(count) is not int or count < 1
                        for phase, count in manifest["phases"].items()) or
                    sum(manifest["phases"].values()) != manifest["record_count"]):
                raise ValueError("Arşiv liste bilgisi geçersiz.")
            entries.append({"archive_id": directory.name, "manifest": manifest,
                            "path": directory / manifest["archive_file"], "status": "unchecked"})
        except (ValueError, OSError, UnicodeError, RecursionError) as error:
            entries.append({"archive_id": directory.name, "status": "error", "message": str(error)})
    return entries


def open_managed_archive(path, root, *, cancel_requested=None):
    """Never republish damaged managed bytes under a new identity."""
    path, root = Path(path), Path(root)
    if path.parent.parent.resolve() != root.resolve() or path.is_symlink():
        raise ValueError("Kayıtlı arşiv uygulama veri alanında değil.")
    manifest = verify_managed_archive(path.parent, cancel_requested=cancel_requested)
    if path.name != manifest["archive_file"]:
        raise ValueError("Kayıtlı arşiv dosyası manifestle uyuşmuyor.")
    return {"manifest": manifest, "path": path, "reused": True}


def import_archive(source, root, *, cancel_requested=None, progress=None):
    """Copy and validate before atomic directory publication; keep originals intact."""
    source, root = Path(source), Path(root)
    if source.parent.parent.resolve() == root.resolve():
        return open_managed_archive(source, root, cancel_requested=cancel_requested)
    if source.is_symlink() or not source.is_file():
        raise ValueError("Mevcut bir JSONL arşiv dosyası seç.")
    compressed = source.suffix.lower() == ".gz"
    if not compressed and source.suffix.lower() != ".jsonl":
        raise ValueError("Arşiv JSONL veya sıkıştırılmış JSONL biçiminde olmalı.")
    _check(cancel_requested)
    expected = _hash(source, cancel_requested)
    target = root / expected
    if target.exists():
        manifest = verify_managed_archive(target, cancel_requested=cancel_requested)
        return {"manifest": manifest, "path": target / manifest["archive_file"], "reused": True}
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".archive-import-", dir=root) as temporary:
        staging = Path(temporary)
        owned = staging / "ready"
        owned.mkdir()
        copied = owned / ("source.jsonl.gz" if compressed else "source.jsonl")
        if progress:
            progress({"stage": "Arşiv uygulama veri alanına kopyalanıyor", "records": 0})
        with source.open("rb") as incoming, copied.open("xb") as outgoing:
            while True:
                _check(cancel_requested)
                block = incoming.read(1024 * 1024)
                if not block:
                    break
                outgoing.write(block)
        if _hash(copied, cancel_requested) != expected or _hash(source, cancel_requested) != expected:
            raise ValueError("Kaynak arşiv aktarım sırasında değişti; yeniden seç.")
        metadata = inspect_archive(copied, cancel_requested=cancel_requested, progress=progress)
        manifest = {"format": 1, "archive_id": expected, "sha256": expected,
                    "archive_file": copied.name, "source_name": source.name,
                    "size": copied.stat().st_size,
                    "imported_at": datetime.now(timezone.utc).isoformat(), **metadata}
        (owned / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        _check(cancel_requested)
        try:
            _publish_archive(owned, target, cancel_requested)
        except OSError:
            if not target.exists():
                raise
            # A concurrent import may have published the same content, not extra rows.
            manifest = verify_managed_archive(target, cancel_requested=cancel_requested)
            return {"manifest": manifest, "path": target / manifest["archive_file"], "reused": True}
    return {"manifest": manifest, "path": target / manifest["archive_file"], "reused": False}


def list_archives(root):
    root = Path(root)
    if not root.exists():
        return []
    result = []
    for path in sorted(root.iterdir()):
        if path.is_symlink() or not path.is_dir() or len(path.name) != 64 or any(c not in "0123456789abcdef" for c in path.name):
            continue
        result.append(verify_managed_archive(path))
    return result
