"""Portable, checksummed project backups."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from contextlib import closing
from pathlib import Path
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable
from typing import Any

from .storage import Store
from .restored_assets import reference_hash, verified_reference_aliases


BACKUP_FORMAT = 2
ATTACHMENT_CATEGORIES = frozenset({"archive", "report", "evidence"})


def _digest_valid(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


class BackupCancelled(Exception):
    """A cooperative cancellation before successful publication."""


class _Operation:
    def __init__(self, check_cancel=None, progress=None):
        self.check_cancel = check_cancel
        self.progress = progress
        self.stage = ""
        self.processed = 0
        self._last_report = 0.0

    def check(self):
        if self.check_cancel and self.check_cancel():
            raise BackupCancelled("Yedek işlemi iptal edildi; tamamlanmış bir dosya yayımlanmadı.")

    def report(self, stage):
        self.check()
        self.stage = stage
        self.processed = 0
        self._last_report = time.monotonic()
        if self.progress:
            self.progress({"stage": stage, "bytes": 0})
        self.check()

    def advance(self, count):
        self.check()
        self.processed += count
        now = time.monotonic()
        if self.progress and now - self._last_report >= 0.1:
            self._last_report = now
            self.progress({"stage": self.stage, "bytes": self.processed})
        self.check()

    def copy(self, incoming, outgoing):
        if self.check_cancel is None and self.progress is None:
            shutil.copyfileobj(incoming, outgoing)
            return
        while True:
            self.check()
            chunk = incoming.read(1024 * 1024)
            if not chunk:
                break
            outgoing.write(chunk)
            self.advance(len(chunk))

    def hash(self, path):
        with Path(path).open("rb") as incoming:
            return _stream_hash(incoming, self)

    def add_zip(self, archive, path, name):
        self.check()
        with Path(path).open("rb") as incoming, archive.open(name, "w", force_zip64=True) as outgoing:
            self.copy(incoming, outgoing)


@dataclass(frozen=True)
class BackupAttachment:
    path: Path
    category: str


def _safe_member(name):
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or "\x00" in name or name.startswith("/")
            or any(part in {"", ".", ".."} or part != part.rstrip(" .")
                   or part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL",
                       *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
                   for part in name.split("/"))):
        raise ValueError("Yedekte güvenli olmayan dosya adı var.")
    return PurePosixPath(name)


def _stream_hash(stream, operation=None):
    digest = hashlib.sha256()
    while True:
        if operation:
            operation.check()
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        if operation:
            operation.advance(len(chunk))
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(store: Store, destination: str | Path, *,
                  attachments: Iterable[BackupAttachment] = (), check_cancel=None,
                  progress=None) -> dict[str, Any]:
    operation = _Operation(check_cancel, progress)
    operation.report("Yedek kapsamı kontrol ediliyor")
    destination = Path(destination)
    protected = (store.path, Path(str(store.path) + "-wal"), Path(str(store.path) + "-shm"))
    if destination.resolve() in {path.resolve() for path in protected}:
        raise ValueError("Yedek dosyası aktif veritabanının veya yardımcı dosyalarının üzerine yazılamaz. Ayrı bir ZIP dosyası seçin.")
    selected = list(attachments)
    managed = []
    # A selected managed source needs its authenticated manifest, not a guessed
    # basename-based association. Generic files receive portable resolver IDs,
    # but no managed-archive binding without an explicitly selected source.
    from .research_archives import verify_managed_archive
    for item in tuple(selected):
        path = Path(item.path)
        if (item.category == 'archive' and path.parent.parent.resolve() ==
                (store.path.parent / 'research-archives').resolve()):
            metadata = verify_managed_archive(path.parent, cancel_requested=check_cancel)
            if path.name == 'manifest.json':
                continue  # An explicitly selected verified companion is not a source.
            if path.name != metadata['archive_file']:
                raise ValueError('Seçilen arşiv kaynağı manifestle uyuşmuyor.')
            manifest_path = path.parent / 'manifest.json'
            if not any(Path(other.path).resolve() == manifest_path.resolve() for other in selected):
                selected.append(BackupAttachment(manifest_path, 'archive'))
            managed.append((path.resolve(), manifest_path.resolve(), metadata))
    seen = set()
    for item in selected:
        operation.check()
        path = Path(item.path)
        if item.category not in ATTACHMENT_CATEGORIES:
            raise ValueError("Yedek dosyası kategorisi arşiv, rapor veya kanıt olmalıdır.")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Seçilen yedek dosyası eksik veya bağlantı: {path.name}")
        _safe_member(path.name)
        if path.resolve() == destination.resolve() or path.resolve() in seen:
            raise ValueError("Yedek hedefi kaynak olamaz; aynı dosya iki kez seçilemez.")
        seen.add(path.resolve())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tv-scan-backup-", dir=destination.parent) as temp:
        temp_path = Path(temp)
        database_copy = temp_path / "tv-scan-studio.db"
        source = store.connect()
        target = sqlite3.connect(database_copy)
        try:
            operation.report("Veritabanı anlık görüntüsü hazırlanıyor")
            source.backup(target, pages=256, progress=lambda *_: operation.check(), sleep=0.05)
            snapshot_projects = target.execute(
                "SELECT id,pine_source FROM projects ORDER BY id").fetchall()
            saved_row = target.execute("SELECT value FROM app_settings WHERE key='historical_archive_path'").fetchone()
            saved_archive = json.loads(saved_row[0]) if saved_row else None
            asset_row = target.execute("SELECT value FROM app_settings WHERE key='restored_asset_index'").fetchone()
            saved_assets = json.loads(asset_row[0]) if asset_row else []
        finally:
            target.close()
            source.close()
        operation.report("Veritabanı ve Pine kaynakları doğrulanıyor")
        files: dict[str, str] = {"database/tv-scan-studio.db": operation.hash(database_copy)}
        pine_files: list[tuple[Path, str]] = []
        for project_id, pine_source in snapshot_projects:
            operation.check()
            pine = temp_path / f"project-{project_id}.pine"
            pine.write_text(str(pine_source), encoding="utf-8", newline="")
            archive_name = f"pine/project-{project_id}.pine"
            files[archive_name] = operation.hash(pine)
            pine_files.append((pine, archive_name))
        attachment_files = []
        descriptors = []
        portable = bool(selected)
        by_source = {}
        for index, item in enumerate(selected):
            operation.report(f"Ek dosya hazırlanıyor ({index + 1}/{len(selected)})")
            original = Path(item.path)
            copied = temp_path / f"attachment-{index}"
            # Check the original before and after copying; never silently snapshot a moving file.
            expected = operation.hash(original)
            if check_cancel is None and progress is None:
                shutil.copyfile(original, copied)
            else:
                with original.open("rb") as incoming, copied.open("xb") as outgoing:
                    operation.copy(incoming, outgoing)
            if operation.hash(copied) != expected or operation.hash(original) != expected:
                raise ValueError(f"Seçilen dosya yedeklenirken değişti: {original.name}")
            archive_name = f"attachments/{item.category}/{index}-{original.name}"
            files[archive_name] = expected
            descriptors.append({"member": archive_name, "category": item.category,
                                "name": original.name, "size": copied.stat().st_size})
            if portable:
                descriptors[-1]['reference_sha256'] = reference_hash(original)
                descriptors[-1]['reference_aliases'] = verified_reference_aliases(
                    store.path.parent, saved_assets, original, expected)
            by_source[original.resolve()] = archive_name
            attachment_files.append((copied, archive_name))
        bindings = []
        for path, manifest_path, metadata in managed:
            bindings.append({'kind': 'historical_archive', 'archive_id': metadata['archive_id'],
                'source_member': by_source[path], 'manifest_member': by_source[manifest_path],
                'source_sha256': metadata['sha256'],
                'selected': isinstance(saved_archive, str) and reference_hash(saved_archive) == reference_hash(path)})
        manifest = {
            "format": 3 if portable else BACKUP_FORMAT, "created_at": time.time(),
            "project_count": len(pine_files), "files": files, "pine_newlines": "preserved",
            "attachments": descriptors,
        }
        if portable:
            manifest['bindings'] = bindings
        staged_zip = temp_path / "backup.zip"
        operation.report("Yedek ZIP dosyası oluşturuluyor")
        with zipfile.ZipFile(staged_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            operation.add_zip(archive, database_copy, "database/tv-scan-studio.db")
            for source, archive_name in pine_files:
                operation.add_zip(archive, source, archive_name)
            for source, archive_name in attachment_files:
                operation.add_zip(archive, source, archive_name)
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        verify_backup(staged_zip, check_cancel=check_cancel, progress=progress)
        operation.report("Doğrulanmış yedek kaydediliyor")
        operation.check()
        os.replace(staged_zip, destination)
    return manifest


def verify_backup(source: str | Path, *, check_cancel=None, progress=None) -> dict[str, Any]:
    operation = _Operation(check_cancel, progress)
    operation.report("Yedek manifesti kontrol ediliyor")
    source = Path(source)
    with zipfile.ZipFile(source) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict) or type(manifest.get("format")) is not int or manifest["format"] not in {1, 2, 3}:
            raise ValueError("Desteklenmeyen yedek formatı.")
        if not isinstance(manifest.get("files"), dict) or "database/tv-scan-studio.db" not in manifest["files"]:
            raise ValueError("Yedekte veritabanı checksum kaydı yok.")
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Yedek yinelenen dosya adları içeriyor.")
        names = set(archive.namelist())
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Yedekte Windows üzerinde çakışan dosya adları var.")
        if names != set(manifest["files"]) | {"manifest.json"}:
            missing = set(manifest["files"]) - names
            if missing:
                raise ValueError("Yedek dosyası eksik: " + str(sorted(missing)[0]))
            raise ValueError("Yedekte manifest dışında dosya var.")
        descriptors = manifest.get("attachments", [])
        if not isinstance(descriptors, list) or (manifest["format"] == 1 and descriptors):
            raise ValueError("Yedek ek dosya listesi geçersiz.")
        declared = set()
        for item in descriptors:
            operation.check()
            if not isinstance(item, dict) or item.get("category") not in ATTACHMENT_CATEGORIES:
                raise ValueError("Yedek ek dosya kategorisi geçersiz.")
            member = item.get("member")
            parts = _safe_member(member).parts
            if (len(parts) != 3 or parts[:2] != ("attachments", item["category"])
                    or member in declared or member not in manifest["files"]
                    or not isinstance(item.get("name"), str)
                    or len(_safe_member(item["name"]).parts) != 1
                    or type(item.get("size")) is not int or item["size"] < 0):
                raise ValueError("Yedek ek dosya kaydı geçersiz.")
            if archive.getinfo(member).file_size != item["size"]:
                raise ValueError("Yedek ek dosya boyutu uyuşmuyor.")
            declared.add(member)
            if manifest['format'] == 3 and not _digest_valid(item.get('reference_sha256')):
                raise ValueError('Yedek taşınabilir dosya kimliği geçersiz.')
            aliases = item.get('reference_aliases', [])
            if (not isinstance(aliases, list) or any(not _digest_valid(alias) for alias in aliases)
                    or len(set(aliases)) != len(aliases) or item.get('reference_sha256') in aliases
                    or (manifest['format'] != 3 and aliases)):
                raise ValueError('Yedek eski dosya bağlantıları geçersiz.')
        bindings = manifest.get('bindings', [])
        if not isinstance(bindings, list) or (manifest['format'] != 3 and bindings):
            raise ValueError('Yedek taşınabilir bağlantıları geçersiz.')
        refs = [ref for item in descriptors for ref in
                [item.get('reference_sha256'), *item.get('reference_aliases', [])]]
        if manifest['format'] == 3 and len(set(refs)) != len(refs):
            raise ValueError('Yedek dosya bağlantıları yineleniyor.')
        bound_sources, selected_count = set(), 0
        descriptor_by_member = {item['member']: item for item in descriptors}
        for binding in bindings:
            if (not isinstance(binding, dict) or set(binding) != {'kind','archive_id','source_member','manifest_member','source_sha256','selected'}
                    or binding['kind'] != 'historical_archive' or not _digest_valid(binding['archive_id'])
                    or binding['source_sha256'] != binding['archive_id'] or type(binding['selected']) is not bool
                    or not isinstance(binding['source_member'], str) or not isinstance(binding['manifest_member'], str)
                    or binding['source_member'] == binding['manifest_member']
                    or binding['source_member'] in bound_sources):
                raise ValueError('Yedek arşiv bağlantısı geçersiz.')
            for key in ('source_member', 'manifest_member'):
                member = binding[key]
                if not isinstance(member, str) or member not in descriptor_by_member or descriptor_by_member[member]['category'] != 'archive':
                    raise ValueError('Yedek arşiv bağlantısı kapsam dışında.')
            if manifest['files'][binding['source_member']] != binding['source_sha256']:
                raise ValueError('Yedek arşiv bağlantısı checksum uyuşmuyor.')
            bound_sources.add(binding['source_member'])
            selected_count += binding['selected']
        if selected_count > 1:
            raise ValueError('Yedek seçili arşiv bağlantısı belirsiz.')
        if {name for name in manifest["files"] if name.startswith("attachments/")} != declared:
            raise ValueError("Yedekte ek dosya manifesti eksik.")
        for name, expected in manifest.get("files", {}).items():
            operation.report("Yedek dosyalarının bütünlüğü kontrol ediliyor")
            _safe_member(name)
            if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
                raise ValueError("Yedek checksum biçimi geçersiz.")
            if name != "database/tv-scan-studio.db" and not name.startswith("pine/") and name not in declared:
                raise ValueError("Yedekte desteklenmeyen dosya kapsamı var.")
            if name not in names:
                raise ValueError(f"Yedek dosyası eksik: {name}")
            with archive.open(name) as stream:
                observed = _stream_hash(stream, operation)
            if observed != expected:
                raise ValueError(f"Yedek checksum uyuşmuyor: {name}")
    return manifest


def restore_backup(source: str | Path, destination: str | Path, *,
                   attachment_directory: str | Path | None = None,
                   check_cancel=None, progress=None) -> dict[str, Any]:
    """Restore into a new DB only; never overwrite or switch the active store.

    No ZIP path is extracted. Verify the exact bytes again after reopening the
    archive, then validate SQLite before creating the requested output file.
    Running claims are left intact for normal application startup recovery.
    """
    operation = _Operation(check_cancel, progress)
    operation.report("Geri yükleme hedefi kontrol ediliyor")
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Geri yükleme için yeni bir veritabanı dosyası seçin.")
    manifest = verify_backup(source, check_cancel=check_cancel, progress=progress)
    descriptors = manifest.get("attachments", [])
    attachment_directory = (Path(attachment_directory) if attachment_directory is not None else
                            destination.with_name(destination.stem + "-files"))
    if manifest['format'] == 3:
        if (any(p.is_symlink() for p in (attachment_directory, *attachment_directory.parents))
                or not attachment_directory.resolve().is_relative_to(destination.parent.resolve())):
            raise ValueError('Taşınabilir ek dosyalar yeni veritabanı alanında olmalıdır.')
    if descriptors and (attachment_directory.exists() or attachment_directory.is_symlink()):
        raise FileExistsError("Ek dosyalar için yeni bir hedef klasörü seçin.")
    with tempfile.TemporaryDirectory(prefix="tv-scan-restore-") as temporary:
        staged = Path(temporary) / "restored.db"
        operation.report("Veritabanı ayrı hedef için hazırlanıyor")
        with zipfile.ZipFile(source) as archive, archive.open("database/tv-scan-studio.db") as incoming:
            with staged.open("xb") as outgoing:
                operation.copy(incoming, outgoing)
        if operation.hash(staged) != manifest["files"]["database/tv-scan-studio.db"]:
            raise ValueError("Yedek veritabanı okuma sırasında değişti; checksum uyuşmuyor.")
        staged_assets = []
        staged_by_member = {}
        with zipfile.ZipFile(source) as archive:
            for index, item in enumerate(descriptors):
                operation.report(f"Ek dosya geri yükleniyor ({index + 1}/{len(descriptors)})")
                path = Path(temporary) / f"asset-{index}"
                with archive.open(item["member"]) as incoming, path.open("xb") as outgoing:
                    operation.copy(incoming, outgoing)
                if operation.hash(path) != manifest["files"][item["member"]]:
                    raise ValueError("Yedek ek dosyası okuma sırasında değişti; checksum uyuşmuyor.")
                staged_assets.append((path, PurePosixPath(item["member"]).parts[1:]))
                staged_by_member[item['member']] = path
        # Validate the managed tree before any requested destination is created.
        managed_staged = []
        for binding in manifest.get('bindings', []):
            tree = Path(temporary) / 'managed' / binding['archive_id']
            tree.mkdir(parents=True)
            metadata = json.loads(staged_by_member[binding['manifest_member']].read_text(encoding='utf-8'))
            if not isinstance(metadata, dict) or metadata.get('archive_file') not in {'source.jsonl','source.jsonl.gz'}:
                raise ValueError('Taşınabilir arşiv manifesti geçersiz.')
            for member, name in ((binding['manifest_member'], 'manifest.json'),
                                 (binding['source_member'], metadata['archive_file'])):
                with staged_by_member[member].open('rb') as incoming, (tree / name).open('xb') as outgoing:
                    operation.copy(incoming, outgoing)
            from .research_archives import verify_managed_archive
            verified = verify_managed_archive(tree, cancel_requested=check_cancel)
            if verified['archive_id'] != binding['archive_id']:
                raise ValueError('Taşınabilir arşiv kaynak kimliği uyuşmuyor.')
            managed_staged.append((binding, tree, verified['archive_file']))
        operation.report("Veritabanı bütünlüğü kontrol ediliyor")
        connection = sqlite3.connect(staged.as_uri() + "?mode=ro", uri=True)
        connection.set_progress_handler(lambda: int(bool(check_cancel and check_cancel())), 1000)
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
            saved_row = connection.execute("SELECT value FROM app_settings WHERE key='historical_archive_path'").fetchone()
            saved_path = json.loads(saved_row[0]) if saved_row else None
            for binding in manifest.get('bindings', []):
                if binding['selected']:
                    descriptor = next(d for d in descriptors if d['member'] == binding['source_member'])
                    if not isinstance(saved_path, str) or reference_hash(saved_path) != descriptor['reference_sha256']:
                        raise ValueError('Seçili arşiv bağlantısı veritabanı ayarıyla uyuşmuyor.')
            if manifest.get("pine_newlines") not in {None, "preserved"}:
                raise ValueError("Desteklenmeyen Pine satır sonu biçimi.")
            expected_pine = {}
            for project_id, pine_source in projects:
                operation.check()
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
        except sqlite3.OperationalError:
            operation.check()
            raise
        finally:
            connection.close()
        operation.report("Doğrulanmış dosyalar yeni hedefe kaydediliyor")
        destination.parent.mkdir(parents=True, exist_ok=True)
        created_files = []
        created_directories = []
        restored_assets = []
        restored_index = []
        restored_archives = []
        try:
            if descriptors:
                # Reserve an entirely new directory. Never extract ZIP paths over user files.
                attachment_directory.parent.mkdir(parents=True, exist_ok=True)
                attachment_directory.mkdir()
                created_directories.append(attachment_directory)
                for index, (path, parts) in enumerate(staged_assets):
                    output = attachment_directory.joinpath(*parts)
                    if output.parent not in created_directories:
                        output.parent.mkdir()
                        created_directories.append(output.parent)
                    with output.open("xb") as outgoing, path.open("rb") as incoming:
                        created_files.append(output)
                        operation.copy(incoming, outgoing)
                    restored_assets.append(str(output.resolve()))
                    if manifest['format'] == 3:
                        descriptor = descriptors[index]
                        for reference in [descriptor['reference_sha256'], *descriptor.get('reference_aliases', [])]:
                            restored_index.append({'reference_sha256': reference,
                                'sha256': manifest['files'][descriptor['member']], 'category': descriptor['category'],
                                'relative_path': output.resolve().relative_to(destination.parent.resolve()).as_posix()})
            for binding, tree, source_name in managed_staged:
                operation.report('Doğrulanmış arşiv yeni uygulama alanına bağlanıyor')
                root = destination.parent / 'research-archives'
                if any(p.is_symlink() for p in (root, *root.parents)):
                    raise ValueError('Yeni arşiv alanı bağlantı olamaz.')
                if not root.exists():
                    root.mkdir()
                    created_directories.append(root)
                owned = root / binding['archive_id']
                if owned.exists() or owned.is_symlink():
                    raise FileExistsError('Arşiv geri yükleme hedefi zaten var; ayrı veri alanı seçin.')
                owned.mkdir()
                created_directories.append(owned)
                for name in ('manifest.json', source_name):
                    output = owned / name
                    with output.open('xb') as outgoing, (tree / name).open('rb') as incoming:
                        created_files.append(output)
                        operation.copy(incoming, outgoing)
                restored_archives.append(str((owned / source_name).resolve()))
            if manifest['format'] == 3:
                # Only mutable routing settings change. Claim/result history and
                # its original paths/bytes remain exactly as backed up.
                with closing(sqlite3.connect(staged)) as routing:
                    routing.execute("INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                        ('restored_asset_index', json.dumps(restored_index), time.time()))
                    for index, (binding, _, _) in enumerate(managed_staged):
                        if binding['selected']:
                            routing.execute("INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?) "
                                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                                ('historical_archive_path', json.dumps(restored_archives[index]), time.time()))
                    routing.commit()
            # Exclusive create also rejects a destination created after preflight.
            with destination.open("xb") as outgoing, staged.open("rb") as incoming:
                created_files.append(destination)
                operation.copy(incoming, outgoing)
            operation.check()
        except BaseException:
            # Only remove exact files/directories created by this attempt, not an existing target.
            for path in reversed(created_files):
                path.unlink(missing_ok=True)
            for path in reversed(created_directories):
                path.rmdir()
            raise
    return {**manifest, "restored_attachments": restored_assets,
            "restored_archives": restored_archives, "restored_asset_index": restored_index}
