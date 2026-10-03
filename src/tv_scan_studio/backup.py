"""Portable, checksummed project backups."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from .storage import Store


BACKUP_FORMAT = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(store: Store, destination: str | Path) -> dict[str, Any]:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tv-scan-backup-") as temp:
        temp_path = Path(temp)
        database_copy = temp_path / "tv-scan-studio.db"
        source = store.connect()
        target = sqlite3.connect(database_copy)
        try:
            source.backup(target)
            snapshot_projects = target.execute(
                "SELECT id,pine_source FROM projects ORDER BY id").fetchall()
        finally:
            target.close()
            source.close()
        files: dict[str, str] = {"database/tv-scan-studio.db": _sha256(database_copy)}
        pine_files: list[tuple[Path, str]] = []
        for project_id, pine_source in snapshot_projects:
            pine = temp_path / f"project-{project_id}.pine"
            pine.write_text(str(pine_source), encoding="utf-8", newline="")
            archive_name = f"pine/project-{project_id}.pine"
            files[archive_name] = _sha256(pine)
            pine_files.append((pine, archive_name))
        manifest = {
            "format": BACKUP_FORMAT, "created_at": time.time(),
            "project_count": len(pine_files), "files": files, "pine_newlines": "preserved",
        }
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(database_copy, "database/tv-scan-studio.db")
            for source, archive_name in pine_files:
                archive.write(source, archive_name)
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def verify_backup(source: str | Path) -> dict[str, Any]:
    source = Path(source)
    with zipfile.ZipFile(source) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != BACKUP_FORMAT:
            raise ValueError("Desteklenmeyen yedek formatı.")
        if "database/tv-scan-studio.db" not in manifest.get("files", {}):
            raise ValueError("Yedekte veritabanı checksum kaydı yok.")
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Yedek yinelenen dosya adları içeriyor.")
        names = set(archive.namelist())
        for name, expected in manifest.get("files", {}).items():
            if name not in names:
                raise ValueError(f"Yedek dosyası eksik: {name}")
            observed = hashlib.sha256(archive.read(name)).hexdigest()
            if observed != expected:
                raise ValueError(f"Yedek checksum uyuşmuyor: {name}")
    return manifest


def restore_backup(source: str | Path, destination: str | Path) -> dict[str, Any]:
    """Restore into a new DB only; never overwrite or switch the active store.

    No ZIP path is extracted. Verify the exact bytes again after reopening the
    archive, then validate SQLite before creating the requested output file.
    Running claims are left intact for normal application startup recovery.
    """
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Geri yükleme için yeni bir veritabanı dosyası seçin.")
    manifest = verify_backup(source)
    with tempfile.TemporaryDirectory(prefix="tv-scan-restore-") as temporary:
        staged = Path(temporary) / "restored.db"
        with zipfile.ZipFile(source) as archive, archive.open("database/tv-scan-studio.db") as incoming:
            with staged.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
        if _sha256(staged) != manifest["files"]["database/tv-scan-studio.db"]:
            raise ValueError("Yedek veritabanı okuma sırasında değişti; checksum uyuşmuyor.")
        connection = sqlite3.connect(staged.as_uri() + "?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Yedek SQLite bütünlük kontrolünü geçemedi.")
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"projects", "tasks", "results", "verification_evidence",
                    "project_settings", "event_log", "app_settings"}.issubset(tables):
                raise ValueError("Yedekte uygulamanın gerekli veritabanı tabloları eksik.")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("Yedekte proje/görev ilişkileri tutarsız.")
            projects = connection.execute("SELECT id,pine_source FROM projects").fetchall()
            if manifest.get("pine_newlines") not in {None, "preserved"}:
                raise ValueError("Desteklenmeyen Pine satır sonu biçimi.")
            expected_pine = {}
            for project_id, pine_source in projects:
                data = pine_source.encode("utf-8")
                allowed = {hashlib.sha256(data).hexdigest()}
                if manifest.get("pine_newlines") is None:
                    # Older Windows backups used text-mode newline translation.
                    # Accept that exact historical transformation, not arbitrary
                    # whitespace changes or source normalization.
                    allowed.add(hashlib.sha256(data.replace(b"\n", b"\r\n")).hexdigest())
                expected_pine[f"pine/project-{project_id}.pine"] = allowed
            archived_pine = {name: value for name, value in manifest["files"].items()
                             if name.startswith("pine/")}
            if (set(expected_pine) != set(archived_pine)
                    or any(archived_pine[name] not in allowed for name, allowed in expected_pine.items())
                    or manifest.get("project_count") != len(projects)):
                raise ValueError("Yedekteki Pine kaynakları ve proje sayısı veritabanıyla uyuşmuyor.")
        finally:
            connection.close()
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create also rejects a destination created after preflight.
        with destination.open("xb") as outgoing, staged.open("rb") as incoming:
            try:
                shutil.copyfileobj(incoming, outgoing)
            except BaseException:
                outgoing.close()
                destination.unlink(missing_ok=True)
                raise
    return manifest
