"""Portable, checksummed project backups."""

from __future__ import annotations

import hashlib
import json
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
        finally:
            target.close()
            source.close()
        files: dict[str, str] = {"database/tv-scan-studio.db": _sha256(database_copy)}
        pine_files: list[tuple[Path, str]] = []
        for project in store.projects():
            details = store.project(int(project["id"]))
            if not details:
                continue
            pine = temp_path / f"project-{project['id']}.pine"
            pine.write_text(str(details["pine_source"]), encoding="utf-8")
            archive_name = f"pine/project-{project['id']}.pine"
            files[archive_name] = _sha256(pine)
            pine_files.append((pine, archive_name))
        manifest = {
            "format": BACKUP_FORMAT, "created_at": time.time(),
            "project_count": len(pine_files), "files": files,
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
        names = set(archive.namelist())
        for name, expected in manifest.get("files", {}).items():
            if name not in names:
                raise ValueError(f"Yedek dosyası eksik: {name}")
            observed = hashlib.sha256(archive.read(name)).hexdigest()
            if observed != expected:
                raise ValueError(f"Yedek checksum uyuşmuyor: {name}")
    return manifest
