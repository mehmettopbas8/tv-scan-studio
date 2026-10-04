import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6 import QtCore, QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store
from tv_scan_studio.research import load_catalog, read_imported_catalog, iter_successful_research_records


def result_fixture(store):
    project = store.create_project("EMA", 'strategy("EMA")\nn=input.int(8,"Fast EMA")')
    store.enqueue(project, "test", {"symbol": "BIST:XU030D1!", "timeframe": "15", "inputs": {"in_0": 9}, "costs": {"commission": 0.04}})
    task = store.claim_next(1, [project])
    store.complete(task.id, 1, {"trades": 100, "profit_factor": 1.2}, "hassas", verified=True, evidence={"scope": "test"})
    return project, task.id


def test_presets_are_actual_results_deduplicated_and_persistent(tmp_path):
    store = Store(tmp_path / "preset.db")
    project, task = result_fixture(store)
    before = store.results(project)
    first = store.save_result_preset(project, task, "EMA 9")
    assert store.save_result_preset(project, task, "Duplicate") == first
    restored = Store(store.path).saved_presets()
    assert len(restored) == 1
    assert restored[0]["snapshot"]["result"] == before[0]
    assert store.results(project) == before
    with pytest.raises(ValueError):
        store.save_result_preset(project, 999, "Invalid")


def test_preset_reuse_is_consentful_does_not_enqueue_and_rejects_source_drift(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "preset-ui.db")
    project, task = result_fixture(store)
    store.save_result_preset(project, task, "EMA 9")
    studio = StudioWindow(store)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *args: QtWidgets.QMessageBox.Yes)
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *args: None)
    try:
        preset = store.saved_presets()[0]
        before = store.counts(project)
        assert studio.apply_saved_preset(preset)
        assert studio.symbols.text() == "BIST:XU030D1!"
        assert studio.plan_inputs.item(0, 4).data(QtCore.Qt.UserRole) == [9]
        assert store.counts(project) == before
        with store.connect() as connection:
            connection.execute("UPDATE projects SET pine_hash='different' WHERE id=?", (project,))
        assert not studio.apply_saved_preset(preset)
        assert store.counts(project) == before
    finally:
        studio.window.close()


def test_import_validates_archive_and_does_not_claim_runtime_verification(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text('{"records": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        read_imported_catalog(path)
    catalog = load_catalog()
    if not catalog.get("available", True):
        pytest.skip("Optional research fixture absent")
    path.write_text(json.dumps(catalog), encoding="utf-8")
    imported = read_imported_catalog(path)
    assert imported["imported_unverified"]
    assert all(not row["verified"] for row in iter_successful_research_records(imported))


def test_empty_and_saved_preset_dialogs_are_readable(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "dialogs.db")
    studio = StudioWindow(store)
    counts = []
    def inspect(dialog):
        listing = dialog.findChild(QtWidgets.QListWidget)
        counts.append(listing.count())
        if listing.count():
            assert "Fast EMA: 9" in dialog.findChild(QtWidgets.QPlainTextEdit).toPlainText()
        else:
            assert "Henüz preset" in dialog.findChild(QtWidgets.QLabel).text()
        return 0
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        studio.show_saved_presets()
        project, task = result_fixture(store)
        store.save_result_preset(project, task, "EMA 9")
        studio.show_saved_presets()
        assert counts == [0, 1]
        assert not studio.archive_open_button.isEnabled()
    finally:
        studio.window.close()
