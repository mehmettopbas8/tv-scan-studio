"""Preview-bound local support archives. No network or automatic private files."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile
import zipfile

from . import __version__

CHUNK = 1024 * 1024
PREVIEW_BYTES = 64 * 1024


class SupportCancelled(Exception):
    pass


@dataclass(frozen=True)
class SupportItem:
    key: str
    label: str
    name: str
    size: int
    sha256: str
    preview: bytes
    content: bytes | None = None
    path: Path | None = None


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def generated_item(key, label, value):
    content = json_bytes(value)
    return SupportItem(key, label, f"diagnostics/{key}.json", len(content), hashlib.sha256(content).hexdigest(), content, content=content)


def diagnostic_items(store):
    """Allowlisted scalar/count queries; never reads source, raw errors or settings blobs."""
    from PySide6 import __version__ as qt_version
    with store.connect() as connection:
        connection.execute("BEGIN")
        counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("projects", "tasks", "results", "scan_runs", "result_history", "attempt_history")}
        counts["verified_results"] = connection.execute("SELECT COUNT(*) FROM results WHERE verified=1").fetchone()[0]
        states = {state: connection.execute("SELECT COUNT(*) FROM tasks WHERE status=?", (state,)).fetchone()[0]
                  for state in ("pending", "running", "done", "failed", "cancelled", "manual_review")}
        states["other"] = counts["tasks"] - sum(states.values())
    return (
        generated_item("environment", "Uygulama ve çalışma ortamı", {"application_version": __version__,
            "python": sys.version.split()[0], "pyside6": qt_version, "platform": sys.platform,
            "packaged": bool(getattr(sys, "frozen", False)), "network_upload": False}),
        generated_item("counts", "İsimsiz kayıt sayıları", counts),
        generated_item("task_states", "İsimsiz görev durum sayıları", states),
    )


def check_cancel(check):
    if check is not None and check():
        raise SupportCancelled("Destek paketi iptal edildi; yeni ZIP yayımlanmadı.")


def checked_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Bağlantı dosyası/klasörü yerine gerçek dosyayı açıkça seç.")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Destek paketine yalnız normal dosyalar eklenebilir.")
    return path


def file_item(path, number, *, cancel=None, progress=None):
    """Only called for a file the user explicitly chose to inspect."""
    check_cancel(cancel)
    path = checked_path(path)
    if type(number) is not int or number < 1:
        raise ValueError("Dosya seçimi kimliği geçersiz.")
    digest, size, preview = hashlib.sha256(), 0, bytearray()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            check_cancel(cancel); digest.update(chunk); size += len(chunk)
            preview.extend(chunk[:max(0, PREVIEW_BYTES - len(preview))])
            if progress:
                progress({"stage": "Seçilen dosyanın önizlemesi ve checksum'ı hazırlanıyor", "bytes": size})
    check_cancel(cancel)
    return SupportItem(f"file_{number}", path.name, f"files/{number:04d}-{path.name}", size, digest.hexdigest(), bytes(preview), path=path)


def validate_selection(items):
    if not items:
        raise ValueError("En az bir içerik seç ve önizlemesini kontrol et.")
    keys, names = set(), set()
    for item in items:
        if (not isinstance(item, SupportItem) or not isinstance(item.name, str)
                or not isinstance(item.key, str) or not item.key
                or not isinstance(item.sha256, str) or len(item.sha256) != 64
                or any(character not in "0123456789abcdef" for character in item.sha256)
                or not isinstance(item.preview, bytes)
                or (item.content is not None and not isinstance(item.content, bytes))):
            raise ValueError("Destek içeriği veya ZIP kapsamı geçersiz.")
        path = PurePosixPath(item.name)
        if (path.is_absolute() or ".." in path.parts or path.as_posix() != item.name
                or any(character in item.name for character in ':\x00\r\n')
                or "\\" in item.name or len(path.parts) != 2 or path.parts[0] not in {"diagnostics", "files"}
                or item.key in keys or item.name in names or type(item.size) is not int or item.size < 0
                or (item.content is None) == (item.path is None)):
            raise ValueError("Destek içeriği veya ZIP kapsamı geçersiz.")
        keys.add(item.key); names.add(item.name)


def publish_new(temporary, destination):
    # Windows rename is atomic and fails if the destination already exists.
    # POSIX rename replaces existing files, so use an exclusive link there.
    if os.name == "nt":
        os.rename(temporary, destination)
    else:
        os.link(temporary, destination)


def create_support_zip(items, destination, *, cancel=None, progress=None):
    """Publishes a new path only, after matching every byte to the preview digest."""
    items = tuple(items); validate_selection(items); check_cancel(cancel)
    destination = Path(destination).absolute()
    for part in (destination, *destination.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("ZIP hedefi için gerçek bir klasör ve yeni dosya adı seç.")
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise ValueError("Yeni bir ZIP dosya adı seç; mevcut dosyaların üzerine yazılmaz.")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".tvscan-support-", suffix=".tmp", dir=destination.parent)
    os.close(descriptor); temporary = Path(temporary_name)
    manifest = {"format": 1, "kind": "local_support", "automatic_upload": False,
        "files": [{"name": item.name, "size": item.size, "sha256": item.sha256} for item in items]}
    try:
        processed = 0
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in items:
                check_cancel(cancel); digest, size = hashlib.sha256(), 0
                if item.content is not None:
                    chunks = (item.content[offset:offset + CHUNK] for offset in range(0, len(item.content), CHUNK))
                    source = None
                else:
                    source = checked_path(item.path).open("rb")
                    chunks = iter(lambda: source.read(CHUNK), b"")
                try:
                    with archive.open(item.name, "w", force_zip64=True) as output:
                        for chunk in chunks:
                            check_cancel(cancel); digest.update(chunk); size += len(chunk)
                            output.write(chunk); processed += len(chunk)
                            if progress:
                                progress({"stage": "Seçilen içerikler ZIP'e yazılıyor", "bytes": processed})
                finally:
                    if source is not None:
                        source.close()
                if size != item.size or digest.hexdigest() != item.sha256:
                    raise ValueError("Önizlemeden sonra içerik değişti. Yeniden önizle ve seç; paket kaydedilmedi.")
            archive.writestr("manifest.json", json_bytes(manifest))
        check_cancel(cancel)
        with zipfile.ZipFile(temporary) as archive:
            for item in items:
                check_cancel(cancel); digest, size = hashlib.sha256(), 0
                with archive.open(item.name) as handle:
                    while chunk := handle.read(CHUNK):
                        check_cancel(cancel); digest.update(chunk); size += len(chunk)
                        if progress:
                            progress({"stage": "ZIP içeriği doğrulanıyor", "bytes": size})
                if size != item.size or digest.hexdigest() != item.sha256:
                    raise ValueError("ZIP içerik doğrulaması başarısız; paket kaydedilmedi.")
        check_cancel(cancel)
        publish_new(temporary, destination)
        return manifest
    finally:
        temporary.unlink(missing_ok=True)
