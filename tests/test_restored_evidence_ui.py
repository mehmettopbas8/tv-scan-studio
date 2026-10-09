"""Relocated evidence presentation preserves immutable event references."""
import pytest

from tv_scan_studio.app import event_evidence_tooltip
from tv_scan_studio.backup import BackupAttachment, create_backup, restore_backup
from tv_scan_studio.storage import Store


@pytest.mark.parametrize("state", ["ready", "missing", "corrupt"])
def test_restored_evidence_tooltip_is_explicit_and_preserves_history(tmp_path, state):
    store = Store(tmp_path / "old.db")
    evidence = tmp_path / "proof.png"
    evidence.write_bytes(b"fixture-evidence")
    reference = str(evidence.resolve())
    backup = tmp_path / "portable.zip"
    create_backup(store, backup, attachments=[BackupAttachment(evidence, "evidence")])
    destination = tmp_path / "new" / "restored.db"
    restored_info = restore_backup(backup, destination)
    restored = Store(destination)
    from pathlib import Path
    moved = Path(restored_info["restored_attachments"][0])
    evidence.unlink()
    if state == "missing":
        moved.unlink()
    elif state == "corrupt":
        moved.write_bytes(b"changed")
    before = restored.app_settings()
    message = event_evidence_tooltip(restored, reference)
    assert reference in message
    assert "Özgün kayıt (değiştirilmedi)" in message
    assert restored.app_settings() == before
    if state == "ready":
        assert "dosya bütünlüğü doğrulandı" in message
        assert str(moved) in message
    else:
        assert "kanıt açılamıyor" in message
        assert "dosya bütünlüğü doğrulandı" not in message


def test_unmapped_and_absent_evidence_are_not_promoted(tmp_path):
    store = Store(tmp_path / "empty.db")
    assert "kaydedilmedi" in event_evidence_tooltip(store, None)
    message = event_evidence_tooltip(store, tmp_path / "missing.png")
    assert "varsayılmaz" in message
    assert "bütünlüğü doğrulandı" not in message


def test_automatic_presentation_never_reads_evidence(tmp_path, monkeypatch):
    import tv_scan_studio.restored_assets as assets
    monkeypatch.setattr(assets, "resolve_restored_asset", lambda *_args: (_ for _ in ()).throw(AssertionError("Automatic refresh must not hash files")))
    message = event_evidence_tooltip(Store(tmp_path / "fixture.db"), "proof.png", verify=False)
    assert "çift tıkla" in message
    assert "Henüz doğrulanmadı" in message
