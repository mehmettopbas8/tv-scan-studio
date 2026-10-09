"""Relocation checks use fresh synthetic data, never personal archives."""
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from tv_scan_studio.backup import BackupAttachment, BackupCancelled, create_backup, restore_backup, verify_backup
from tv_scan_studio.research_archives import import_archive, open_managed_archive
from tv_scan_studio.restored_assets import reference_hash, resolve_restored_asset
from tv_scan_studio.storage import Store


def fixture(tmp_path):
    old = tmp_path / 'old'
    old.mkdir()
    store = Store(old / 'studio.db')
    source = old / 'input.jsonl'
    source.write_text(json.dumps({'symbol': 'TEST:DEMO', 'tf': '15', 'params': {'ema': 8},
                                 'metrics': {'trades': 1}, 'valid': True}) + '\n', encoding='utf-8')
    imported = import_archive(source, old / 'research-archives')
    store.save_app_settings({'historical_archive_path': str(imported['path'].resolve())})
    screenshot = old / 'failure.png'
    screenshot.write_bytes(b'synthetic screenshot bytes')
    project = store.create_project('Fixture', 'strategy("Fixture")')
    store.enqueue(project, 'task', {'inputs': {}})
    task = store.claim_next(1)
    store.fail(task.id, 1, 'synthetic failure', screenshot_path=str(screenshot.resolve()), max_attempts=1)
    return store, imported, screenshot, task


def test_relocated_archive_and_evidence_work_when_old_root_unavailable(tmp_path):
    store, imported, screenshot, task = fixture(tmp_path)
    history = store.attempt_history(task.id)
    reference = str(screenshot.resolve())
    backup = tmp_path / 'backup.zip'
    manifest = create_backup(store, backup, attachments=[
        BackupAttachment(imported['path'], 'archive'), BackupAttachment(screenshot, 'evidence')])
    assert manifest['format'] == 3
    assert len(manifest['attachments']) == 3  # authenticated companion manifest
    assert 'old' not in json.dumps(manifest['bindings'])
    destination = tmp_path / 'new' / 'restored.db'
    result = restore_backup(backup, destination)
    (tmp_path / 'old').rename(tmp_path / 'old-unavailable')
    restored = Store(destination)
    assert restored.attempt_history(task.id) == history
    saved = restored.app_settings()['historical_archive_path']
    managed = open_managed_archive(saved, destination.parent / 'research-archives')
    assert managed['manifest']['record_count'] == 1
    assert managed['manifest']['verification'] == 'historical_unverified'
    assert len(result['restored_archives']) == 1
    assert resolve_restored_asset(restored, reference).read_bytes() == b'synthetic screenshot bytes'
    resolve_restored_asset(restored, reference).write_bytes(b'changed')
    with pytest.raises(ValueError, match='checksum'):
        resolve_restored_asset(restored, reference)


@pytest.mark.parametrize('change', ['escape', 'wrong_hash', 'wrong_kind', 'duplicate', 'bad_ref'])
def test_malicious_bindings_fail_before_destination_creation(tmp_path, change):
    store, imported, screenshot, _ = fixture(tmp_path)
    backup = tmp_path / 'backup.zip'
    create_backup(store, backup, attachments=[BackupAttachment(imported['path'], 'archive')])
    with zipfile.ZipFile(backup) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(contents['manifest.json'])
    binding = manifest['bindings'][0]
    if change == 'escape': binding['source_member'] = '../escape.jsonl'
    if change == 'wrong_hash': binding['source_sha256'] = '0' * 64
    if change == 'wrong_kind': binding['kind'] = 'rewrite_immutable_history'
    if change == 'duplicate': manifest['bindings'].append(dict(binding))
    if change == 'bad_ref': manifest['attachments'][0]['reference_sha256'] = '../private'
    contents['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(backup, 'w') as archive:
        for name, data in contents.items(): archive.writestr(name, data)
    target = tmp_path / 'new' / 'restore.db'
    with pytest.raises(ValueError): restore_backup(backup, target)
    assert not target.exists()
    assert not (target.parent / 'research-archives').exists()


def test_portable_archive_metadata_tamper_with_rehashed_zip_fails(tmp_path):
    store, imported, _, _ = fixture(tmp_path)
    backup = tmp_path / 'backup.zip'
    create_backup(store, backup, attachments=[BackupAttachment(imported['path'], 'archive')])
    with zipfile.ZipFile(backup) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(contents['manifest.json'])
    name = manifest['bindings'][0]['manifest_member']
    metadata = json.loads(contents[name]); metadata['record_count'] = 900
    contents[name] = json.dumps(metadata).encode()
    manifest['files'][name] = hashlib.sha256(contents[name]).hexdigest()
    next(d for d in manifest['attachments'] if d['member'] == name)['size'] = len(contents[name])
    contents['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(backup, 'w') as archive:
        for member, data in contents.items(): archive.writestr(member, data)
    assert verify_backup(backup)['format'] == 3
    with pytest.raises(ValueError): restore_backup(backup, tmp_path / 'new' / 'restored.db')
    assert not (tmp_path / 'new').exists()


def test_generic_report_and_evidence_relocate_without_archive(tmp_path):
    old = tmp_path / 'old'; old.mkdir()
    store = Store(old / 'studio.db')
    report, evidence = old / 'report.txt', old / 'evidence.png'
    report.write_bytes(b'report'); evidence.write_bytes(b'evidence')
    refs = [str(p.resolve()) for p in (report, evidence)]
    backup = tmp_path / 'backup.zip'
    manifest = create_backup(store, backup, attachments=[BackupAttachment(report, 'report'), BackupAttachment(evidence, 'evidence')])
    assert manifest['format'] == 3 and manifest['bindings'] == []
    destination = tmp_path / 'new' / 'restored.db'
    restore_backup(backup, destination)
    old.rename(tmp_path / 'old-unavailable')
    restored = Store(destination)
    assert [resolve_restored_asset(restored, ref).read_bytes() for ref in refs] == [b'report', b'evidence']


def test_v2_attachments_still_read_without_inventing_bindings(tmp_path):
    store = Store(tmp_path / 'studio.db')
    report = tmp_path / 'report.txt'; report.write_bytes(b'legacy')
    backup = tmp_path / 'backup.zip'
    create_backup(store, backup, attachments=[BackupAttachment(report, 'report')])
    with zipfile.ZipFile(backup) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(contents['manifest.json']); manifest['format'] = 2
    manifest.pop('bindings')
    for descriptor in manifest['attachments']: descriptor.pop('reference_sha256')
    contents['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(backup, 'w') as archive:
        for name, data in contents.items(): archive.writestr(name, data)
    assert verify_backup(backup)['format'] == 2
    result = restore_backup(backup, tmp_path / 'new' / 'restored.db')
    assert result['restored_asset_index'] == []
    assert Path(result['restored_attachments'][0]).read_bytes() == b'legacy'


def test_cancel_managed_publication_rolls_back_only_owned_outputs(tmp_path):
    store, imported, _, _ = fixture(tmp_path)
    backup = tmp_path / 'backup.zip'
    create_backup(store, backup, attachments=[BackupAttachment(imported['path'], 'archive')])
    destination = tmp_path / 'new' / 'restored.db'
    cancelled = []
    def progress(value):
        if value['stage'] == 'Doğrulanmış arşiv yeni uygulama alanına bağlanıyor':
            cancelled.append(True)
    with pytest.raises(BackupCancelled):
        restore_backup(backup, destination, check_cancel=lambda: bool(cancelled), progress=progress)
    assert not destination.exists()
    assert not (destination.parent / 'restored-files').exists()
    assert not (destination.parent / 'research-archives').exists()
    assert imported['path'].is_file()


def test_existing_managed_target_is_never_overwritten(tmp_path):
    store, imported, _, _ = fixture(tmp_path)
    backup = tmp_path / 'backup.zip'
    create_backup(store, backup, attachments=[BackupAttachment(imported['path'], 'archive')])
    destination = tmp_path / 'new' / 'restored.db'
    owned = destination.parent / 'research-archives' / imported['manifest']['archive_id']
    owned.mkdir(parents=True)
    sentinel = owned / 'user.txt'; sentinel.write_bytes(b'keep')
    with pytest.raises(FileExistsError): restore_backup(backup, destination)
    assert sentinel.read_bytes() == b'keep'
    assert not destination.exists()
    assert not (destination.parent / 'restored-files').exists()


def test_explicit_managed_companion_is_not_duplicated(tmp_path):
    store, imported, _, _ = fixture(tmp_path)
    manifest = create_backup(store, tmp_path / 'backup.zip', attachments=[
        BackupAttachment(imported['path'], 'archive'),
        BackupAttachment(imported['path'].parent / 'manifest.json', 'archive')])
    assert len(manifest['attachments']) == 2
    assert len(manifest['bindings']) == 1


def test_second_backup_preserves_original_immutable_references(tmp_path):
    store, imported, screenshot, task = fixture(tmp_path)
    report = store.path.parent / 'report.txt'; report.write_bytes(b'synthetic report')
    original_refs = [str(p.resolve()) for p in (screenshot, report)]
    history = store.attempt_history(task.id)
    first = tmp_path / 'first.zip'
    create_backup(store, first, attachments=[BackupAttachment(imported['path'], 'archive'),
        BackupAttachment(screenshot, 'evidence'), BackupAttachment(report, 'report')])
    restore_backup(first, tmp_path / 'middle' / 'studio.db')
    middle = Store(tmp_path / 'middle' / 'studio.db')
    relocated = [resolve_restored_asset(middle, ref) for ref in original_refs]
    middle_refs = [str(p.resolve()) for p in relocated]
    second = tmp_path / 'second.zip'
    manifest = create_backup(middle, second, attachments=[
        BackupAttachment(middle.app_settings()['historical_archive_path'], 'archive'),
        BackupAttachment(relocated[0], 'evidence'), BackupAttachment(relocated[1], 'report')])
    for descriptor, original in zip([d for d in manifest['attachments'] if d['category'] != 'archive'], original_refs):
        assert descriptor['reference_aliases'] == [reference_hash(original)]
    restore_backup(second, tmp_path / 'last' / 'studio.db')
    last = Store(tmp_path / 'last' / 'studio.db')
    (tmp_path / 'old').rename(tmp_path / 'old-unavailable')
    (tmp_path / 'middle').rename(tmp_path / 'middle-unavailable')
    assert last.attempt_history(task.id) == history
    for refs in (original_refs, middle_refs):
        assert [resolve_restored_asset(last, ref).read_bytes() for ref in refs] == [b'synthetic screenshot bytes', b'synthetic report']
    assert open_managed_archive(last.app_settings()['historical_archive_path'],
                               last.path.parent / 'research-archives')['manifest']['record_count'] == 1


@pytest.mark.parametrize('tamper', ['bytes', 'index_hash', 'collision', 'escape', 'category'])
def test_rebackup_rejects_tampered_or_ambiguous_index(tmp_path, tamper):
    store, _, screenshot, _ = fixture(tmp_path)
    original = str(screenshot.resolve())
    first = tmp_path / 'first.zip'
    create_backup(store, first, attachments=[BackupAttachment(screenshot, 'evidence')])
    restore_backup(first, tmp_path / 'middle' / 'studio.db')
    middle = Store(tmp_path / 'middle' / 'studio.db')
    selected = resolve_restored_asset(middle, original)
    entries = middle.app_settings()['restored_asset_index']
    if tamper == 'bytes': selected.write_bytes(b'tampered')
    if tamper == 'index_hash': entries[0]['sha256'] = '0' * 64
    if tamper == 'collision': entries.append(dict(entries[0]))
    if tamper == 'escape': entries[0]['relative_path'] = '../outside.png'
    if tamper == 'category': entries[0]['category'] = []
    middle.save_app_settings({'restored_asset_index': entries})
    second = tmp_path / 'second.zip'; second.write_bytes(b'keep existing')
    with pytest.raises(ValueError):
        create_backup(middle, second, attachments=[BackupAttachment(selected, 'evidence')])
    assert second.read_bytes() == b'keep existing'


@pytest.mark.parametrize('aliases', [['invalid'], ['0' * 64, '0' * 64], [False], 'not-a-list', ['primary'], ['collision']])
def test_malicious_reference_aliases_are_rejected(tmp_path, aliases):
    store, _, screenshot, _ = fixture(tmp_path)
    report = store.path.parent / 'report.txt'; report.write_bytes(b'report')
    backup = tmp_path / 'backup.zip'
    create_backup(store, backup, attachments=[BackupAttachment(screenshot, 'evidence'), BackupAttachment(report, 'report')])
    with zipfile.ZipFile(backup) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(contents['manifest.json'])
    if aliases == ['primary']: aliases = [manifest['attachments'][0]['reference_sha256']]
    if aliases == ['collision']: aliases = [manifest['attachments'][1]['reference_sha256']]
    manifest['attachments'][0]['reference_aliases'] = aliases
    contents['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(backup, 'w') as archive:
        for name, data in contents.items(): archive.writestr(name, data)
    target = tmp_path / 'new' / 'studio.db'
    with pytest.raises(ValueError): restore_backup(backup, target)
    assert not target.exists()
