import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import zipfile
from PySide6 import QtCore, QtWidgets as Q
from tv_scan_studio import support_dialog as module
from tv_scan_studio.support_package import generated_item, file_item


def dialog(monkeypatch):
    app = Q.QApplication.instance() or Q.QApplication([])
    monkeypatch.setattr(module, "diagnostic_items", lambda store: (generated_item("counts", "İsimsiz sayılar", {"tasks": 3}),))
    instance = module.SupportDialog(object())
    return app, instance


def settle(app, instance):
    deadline = time.monotonic() + 15
    while instance.job is not None and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.005)
    assert instance.job is None


def dispose(app, instance):
    if instance.job is not None: instance.reject(); settle(app, instance)
    instance.scope.finish_scope(); instance.reject(); instance.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_default_preview_help_and_tour_do_not_export(monkeypatch, tmp_path):
    app, instance = dialog(monkeypatch)
    try:
        assert instance.selected_items() == () and not instance.create.isEnabled()
        assert "tasks" in instance.preview.toPlainText()
        assert len(instance.scope.specs) == 14
        assert all(spec.target.toolTip() for spec in instance.scope.specs.values())
        instance.show(); app.processEvents()
        instance.scope.start_tour("local_support")
        assert instance.job is None and not list(tmp_path.iterdir())
        instance.scope.finish_scope()
    finally: dispose(app, instance)


def test_manual_file_unchecked_consent_required_and_async_zip(monkeypatch, tmp_path):
    app, instance = dialog(monkeypatch)
    private = tmp_path / "private.pine"; private.write_text("secret source", encoding="utf-8")
    target = tmp_path / "support.zip"
    try:
        instance.contents.item(0).setCheckState(QtCore.Qt.Checked)
        assert instance.preview_file(private)
        assert not instance.preview_file(private)
        assert not instance.create_zip(target)
        settle(app, instance)
        assert instance.contents.item(0).checkState() == QtCore.Qt.Checked
        assert instance.contents.item(1).checkState() == QtCore.Qt.Unchecked
        instance.contents.item(1).setCheckState(QtCore.Qt.Checked)
        assert not instance.create.isEnabled() and "onay" in instance.block_reason()
        instance.consent.setChecked(True)
        assert instance.create_zip(target)
        settle(app, instance)
        assert instance.outcome["status"] == "ready"
        with zipfile.ZipFile(target) as archive:
            assert archive.read("files/0001-private.pine") == b"secret source"
        assert "yüklenmedi" in instance.status.text()
        instance.contents.item(1).setCheckState(QtCore.Qt.Unchecked)
        assert not instance.consent.isChecked()
    finally: dispose(app, instance)


def test_changed_preview_rejected_and_technical_error_visible(monkeypatch, tmp_path):
    app, instance = dialog(monkeypatch)
    path = tmp_path / "changed.txt"; path.write_bytes(b"first")
    try:
        instance.items.append(file_item(path, 1)); instance.rebuild()
        instance.contents.item(1).setCheckState(QtCore.Qt.Checked); instance.consent.setChecked(True)
        path.write_bytes(b"later")
        target = tmp_path / "no.zip"
        assert instance.create_zip(target); settle(app, instance)
        assert not target.exists() and instance.outcome["status"] == "error"
        assert "değişti" in instance.details.toPlainText()
        assert not instance.details.isHidden()
    finally: dispose(app, instance)


def test_binary_and_truncated_preview_removal_never_deletes_file(monkeypatch, tmp_path):
    app, instance = dialog(monkeypatch)
    path = tmp_path / "image.bin"; path.write_bytes(b"\x00" * 70000)
    try:
        instance.items.append(file_item(path, 1)); instance.rebuild(); instance.contents.setCurrentRow(1)
        assert "Kısaltılmış" in instance.preview.toPlainText()
        assert "İkili dosya" in instance.preview.toPlainText()
        instance.remove_file()
        assert path.exists() and len(instance.items) == 1
    finally: dispose(app, instance)


def test_close_as_cancel_waits_for_thread_retirement(monkeypatch):
    app, instance = dialog(monkeypatch)
    class SlowJob(QtCore.QThread):
        progress = QtCore.Signal(object)
        result = QtCore.Signal(object)
        def __init__(self): super().__init__(); self.cancelled = False
        def cancel(self): self.cancelled = True
        def run(self):
            while not self.cancelled: self.msleep(5)
            self.msleep(30); self.result.emit({"status": "cancelled"})
    job = SlowJob(); finished = []
    instance.finished.connect(finished.append)
    try:
        instance.show(); instance.start_job(job); instance.reject()
        assert instance.job is job and not finished and instance.closing
        assert "İptal ediliyor" in instance.status.text()
        settle(app, instance)
        assert finished == [Q.QDialog.Rejected]
    finally: dispose(app, instance)


def test_late_close_keeps_published_success(monkeypatch, tmp_path):
    app, instance = dialog(monkeypatch)
    class PublishedJob(QtCore.QThread):
        progress = QtCore.Signal(object)
        result = QtCore.Signal(object)
        def cancel(self): pass
        def run(self): self.msleep(30); self.result.emit({"status": "ready", "destination": str(tmp_path / "saved.zip")})
    try:
        instance.start_job(PublishedJob()); instance.reject(); settle(app, instance)
        assert instance.outcome["status"] == "ready" and "yüklenmedi" in instance.status.text()
    finally: dispose(app, instance)


def test_remove_one_attachment_preserves_other_scope_and_revokes_consent(monkeypatch, tmp_path):
    app, instance = dialog(monkeypatch)
    first = tmp_path / "a.txt"; second = tmp_path / "b.txt"
    first.write_bytes(b"A"); second.write_bytes(b"B")
    try:
        instance.items.extend((file_item(first, 1), file_item(second, 2))); instance.rebuild()
        instance.contents.item(0).setCheckState(QtCore.Qt.Checked)
        instance.contents.item(2).setCheckState(QtCore.Qt.Checked); instance.consent.setChecked(True)
        instance.contents.setCurrentRow(1); instance.remove_file()
        assert [item.key for item in instance.selected_items()] == ["counts", "file_2"]
        assert not instance.consent.isChecked() and not instance.create.isEnabled()
        assert first.read_bytes() == b"A" and second.read_bytes() == b"B"
    finally: dispose(app, instance)


def test_existing_destination_not_overwritten(monkeypatch, tmp_path):
    app, instance = dialog(monkeypatch)
    target = tmp_path / "existing.zip"; target.write_bytes(b"existing")
    try:
        instance.contents.item(0).setCheckState(QtCore.Qt.Checked)
        assert instance.create_zip(target); settle(app, instance)
        assert target.read_bytes() == b"existing"
        assert instance.outcome["status"] == "error" and instance.job is None
        assert instance.create.isEnabled()
    finally: dispose(app, instance)
