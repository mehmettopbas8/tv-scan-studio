"""Resolve relocated bytes without rewriting immutable provenance paths."""
import hashlib
import os
from pathlib import Path, PurePosixPath


def reference_hash(reference):
    return hashlib.sha256(os.path.normcase(os.path.abspath(str(reference))).encode('utf-8')).hexdigest()


def _digest_valid(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _relative_asset(base, name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or name.startswith('/') or any(p in {'', '.', '..'} for p in name.split('/'))):
        raise ValueError('Geri yüklenen dosya yolu güvenli değil.')
    path = base.joinpath(*PurePosixPath(name).parts)
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.resolve().is_relative_to(base):
        raise ValueError('Geri yüklenen dosya uygulama alanında değil.')
    return path


def validated_index(base, entries):
    if not isinstance(entries, list):
        raise ValueError('Geri yüklenen dosya indeksi geçersiz.')
    base = Path(base).resolve()
    seen = set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {'reference_sha256','sha256','category','relative_path'}
                or not _digest_valid(entry['reference_sha256']) or not _digest_valid(entry['sha256'])
                or not isinstance(entry['category'], str)
                or entry['category'] not in {'archive','report','evidence'}
                or entry['reference_sha256'] in seen):
            raise ValueError('Geri yüklenen dosya bağlantısı geçersiz veya belirsiz.')
        seen.add(entry['reference_sha256'])
        yield entry, _relative_asset(base, entry['relative_path'])


def verified_reference_aliases(base, entries, selected_path, content_sha256):
    """Preserve old immutable references only for a path/hash-bound selected file."""
    selected = Path(selected_path).resolve()
    aliases = []
    for entry, path in validated_index(base, entries):
        if path.resolve() != selected:
            continue
        if entry['sha256'] != content_sha256:
            raise ValueError('Yeniden yedeklenen dosya önceki checksum ile uyuşmuyor.')
        if not path.is_file():
            raise ValueError('Yeniden yedeklenen dosya eksik.')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != content_sha256:
            raise ValueError('Yeniden yedeklenen dosya checksum uyuşmuyor.')
        if entry['reference_sha256'] != reference_hash(selected):
            aliases.append(entry['reference_sha256'])
    return aliases


def resolve_restored_asset(store, original_reference, *, check_cancel=None):
    entries = list(validated_index(store.path.parent,
                                  store.app_settings().get('restored_asset_index', [])))
    matches = [(e, path) for e, path in entries
               if e['reference_sha256'] == reference_hash(original_reference)]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError('Geri yüklenen dosya bağlantısı belirsiz.')
    entry, path = matches[0]
    if not path.is_file():
        raise ValueError('Geri yüklenen dosya eksik.')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            if check_cancel and check_cancel():
                from .backup import BackupCancelled
                raise BackupCancelled('Kanıt kontrolü iptal edildi.')
            digest.update(block)
    if digest.hexdigest() != entry.get('sha256'):
        raise ValueError('Geri yüklenen dosya checksum uyuşmuyor.')
    return path
