import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets as Q

from tv_scan_studio.backup_selection import BackupSelection
from tv_scan_studio.help_system import HelpRegistry


def test_selection_is_explicit_deduplicated_and_non_destructive(tmp_path, monkeypatch):
    application = Q.QApplication.instance() or Q.QApplication([])
    parent = Q.QDialog()
    selection = BackupSelection(parent)
    assert selection.items() == ()
    path = tmp_path / "report.csv"
    path.write_text("metric,value\nPF,1.4", encoding="utf-8")
    original = path.read_bytes()
    monkeypatch.setattr(Q.QFileDialog, "getOpenFileNames", lambda *args: ([str(path)], ""))
    selection.add_buttons["report"].click()
    selection.add_buttons["report"].click()
    assert len(selection.items()) == 1
    assert selection.items()[0].category == "report"
    assert not selection.add_paths([path, tmp_path / "missing.csv"], "evidence")
    assert len(selection.items()) == 1
    assert "Dosya okunamadı" in selection.status.text()
    selection.listing.setCurrentRow(0)
    selection.remove.click()
    assert selection.items() == ()
    assert path.read_bytes() == original
    parent.close()


def test_help_covers_selection_and_does_not_select_files(tmp_path, monkeypatch):
    application = Q.QApplication.instance() or Q.QApplication([])
    parent = Q.QDialog()
    selection = BackupSelection(parent)
    registry = HelpRegistry(parent)
    selection.register_help(registry)
    assert len(registry.specs) == 8
    for spec in registry.specs.values():
        assert spec.target.toolTip()
    assert "Önce" in registry.specs["backup.files.remove"].text()
    monkeypatch.setattr(Q.QFileDialog, "getOpenFileNames", lambda *args: (_ for _ in ()).throw(AssertionError("Help must not pick files")))
    parent.show()
    selection.guide.click()
    application.processEvents()
    assert selection.items() == ()
    assert registry.active_tour is not None
    registry.finish_scope()
    parent.close()
