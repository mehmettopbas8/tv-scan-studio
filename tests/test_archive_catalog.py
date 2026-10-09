import json
import os
import time
import threading
import csv
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore, QtWidgets as Q
from tv_scan_studio.research_archives import archive_catalog, import_archive
from tv_scan_studio.historical_dialog import HistoricalDialog
from tv_scan_studio.storage import Store


def source(path, phases):
    path.write_text("\n".join(json.dumps({"symbol": "BIST:XU030D1!", "tf": "15", "phase": phase,
        "params": {"in_0": 8}, "metrics": {"pf": 1.5}, "valid": True, "pass": index % 2 == 0})
        for index, phase in enumerate(phases)), encoding="utf-8")
    return path


def drain(dialog, app):
    deadline = time.monotonic() + 10
    while dialog.load_job is not None and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.002)
    assert dialog.load_job is None


def test_catalog_metadata_is_not_file_verification_and_bad_manifest_is_isolated(tmp_path, monkeypatch):
    from tv_scan_studio import research_archives
    root = tmp_path / "managed"
    first = import_archive(source(tmp_path / "one.jsonl", ["baseline"]), root)
    second = import_archive(source(tmp_path / "two.jsonl", ["heavy"]), root)
    (first["path"].parent / "manifest.json").write_text("broken", encoding="utf-8")
    monkeypatch.setattr(research_archives, "verify_managed_archive", lambda *_args, **_kwargs: pytest.fail("Catalog must not hash all archives"))
    entries = archive_catalog(root)
    assert len(entries) == 2
    assert {entry["status"] for entry in entries} == {"unchecked", "error"}
    assert next(entry for entry in entries if entry["status"] == "unchecked")["archive_id"] == second["manifest"]["archive_id"]


def test_modified_managed_copy_cannot_be_imported_as_a_new_archive(tmp_path):
    root = tmp_path / "managed"
    imported = import_archive(source(tmp_path / "one.jsonl", ["baseline"]), root)
    source(imported["path"], ["heavy"])  # Still parseable, but no longer the registered content.
    before = {path.name for path in root.iterdir()}
    with pytest.raises(ValueError, match="boyutu|checksum"):
        import_archive(imported["path"], root)
    assert {path.name for path in root.iterdir()} == before


def test_switching_archives_phase_filter_and_reopen_preserve_separate_records(tmp_path):
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "active.db")
    dialog = HistoricalDialog(store)
    first = source(tmp_path / "first.jsonl", ["baseline", "heavy", None])
    second = source(tmp_path / "second.jsonl", ["provider"])
    try:
        dialog.load_archive(first); drain(dialog, app)
        first_id = dialog.catalog.currentData()["archive_id"]
        assert dialog.load_archive(second)
        drain(dialog, app)
        assert dialog.load_result['status'] == 'ready', dialog.load_result
        assert dialog.catalog.count() == 2 and len(dialog.rows) == 1
        for index in range(dialog.catalog.count()):
            if dialog.catalog.itemData(index)["archive_id"] == first_id:
                dialog.catalog.setCurrentIndex(index)
        assert len(dialog.rows) == 1  # Selection is not confirmation.
        dialog.catalog_open.click(); drain(dialog, app)
        assert len(dialog.rows) == 3
        dialog.phase.setCurrentIndex(dialog.phase.findData("heavy"))
        assert dialog.phase.currentText() == "Ağır maliyet"
        assert "heavy" in dialog.phase.itemData(dialog.phase.currentIndex(), QtCore.Qt.ToolTipRole)
        assert len(dialog.selected_records()) == 1
        assert dialog.selected_records()[0]["payload"]["source_phase"] == "heavy"
        dialog.filter.setCurrentIndex(1)
        assert dialog.selected_records() == []
        dialog.filter.setCurrentIndex(0)
        dialog.phase.setCurrentIndex(dialog.phase.findData("unknown"))
        assert len(dialog.selected_records()) == 1
        assert dialog.selected_records()[0]["payload"]["source_phase"] is None
        dialog.load_archive(first); drain(dialog, app)
        assert dialog.catalog.count() == 2 and len(dialog.rows) == 3
        first.unlink(); second.unlink()
        assert not store.projects()
    finally:
        dialog.close(); app.processEvents()
    reopened = HistoricalDialog(store)
    try:
        drain(reopened, app)
        assert reopened.catalog.count() == 2 and len(reopened.rows) == 3
        assert reopened.load_result["status"] == "ready"
    finally:
        reopened.close(); app.processEvents()


def test_corrupt_selected_copy_preserves_view_settings_and_other_archives(tmp_path):
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "active.db")
    dialog = HistoricalDialog(store)
    try:
        dialog.load_archive(source(tmp_path / "first.jsonl", ["baseline"])); drain(dialog, app)
        bad_entry = dialog.catalog.currentData()
        dialog.load_archive(source(tmp_path / "second.jsonl", ["heavy"])); drain(dialog, app)
        previous = dialog.rows
        saved = store.app_settings()["historical_archive_path"]
        source(bad_entry["path"], ["different-phase"])
        index = next(index for index in range(dialog.catalog.count()) if dialog.catalog.itemData(index)["archive_id"] == bad_entry["archive_id"])
        dialog.catalog.setCurrentIndex(index)
        dialog.catalog_open.click(); drain(dialog, app)
        assert dialog.load_result["status"] == "error"
        assert "Arşiv açılamadı" in dialog.status.text()
        assert dialog.rows is previous
        assert store.app_settings()["historical_archive_path"] == saved
        assert len(archive_catalog(dialog.archive_root)) == 2
    finally:
        dialog.close(); app.processEvents()


def test_new_catalog_help_preserves_old_completed_tour_and_never_opens_files(tmp_path):
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "active.db")
    store.save_app_settings({"help_tour_history_completed": True})
    dialog = HistoricalDialog(store)
    try:
        dialog.show(); app.processEvents()
        registry = dialog.help_registry
        assert registry.active_tour is None
        assert not registry.missing_controls(dialog)
        dialog.phase.setFocus(); app.processEvents()
        tour = registry.active_tour
        assert tour is not None
        tour.skip.click()
        assert store.app_settings()["help_tour_history_catalog_completed"]
        registry.specs["history.catalog_guide"].target.click()
        reopened = registry.active_tour
        while not reopened.ended:
            reopened.next.click()
        assert not reopened.timer.isActive()
        assert dialog.load_job is None and dialog.rows == []
        assert not store.projects()
    finally:
        dialog.close(); app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_catalog_cancel_is_responsive_and_preserves_loaded_archive(tmp_path, monkeypatch):
    from tv_scan_studio import archive_jobs
    from tv_scan_studio.research_archives import ArchiveCancelled
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "active.db")
    dialog = HistoricalDialog(store)
    entered = threading.Event()
    def slow_catalog(root, *, cancel_requested):
        entered.set()
        while not cancel_requested():
            time.sleep(.002)
        raise ArchiveCancelled()
    timer = QtCore.QTimer()
    ticks = []
    timer.timeout.connect(lambda: ticks.append(True))
    try:
        dialog.load_archive(source(tmp_path / "first.jsonl", ["baseline"])); drain(dialog, app)
        old_rows, old_entries = dialog.rows, dialog.catalog_entries
        assert dialog.load_result['status'] == 'ready', dialog.load_result
        old_path = store.app_settings()["historical_archive_path"]
        monkeypatch.setattr(archive_jobs, "archive_catalog", slow_catalog)
        timer.start(1)
        assert dialog.refresh_catalog()
        assert not dialog.refresh_catalog()
        deadline = time.monotonic() + 3
        while len(ticks) < 5 and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.002)
        assert entered.is_set() and len(ticks) >= 5
        assert not dialog.catalog_open.isEnabled() and not dialog.phase.isEnabled()
        dialog.cancel_loading(); drain(dialog, app)
        assert dialog.rows is old_rows and dialog.catalog_entries is old_entries
        assert store.app_settings()["historical_archive_path"] == old_path
        assert dialog.catalog_open.isEnabled()
    finally:
        timer.stop(); dialog.close(); app.processEvents()


def test_phase_and_status_export_scope_does_not_merge_archives(tmp_path, monkeypatch):
    app = Q.QApplication.instance() or Q.QApplication([])
    dialog = HistoricalDialog(Store(tmp_path / "active.db"))
    try:
        assert dialog.load_archive(source(tmp_path / "first.jsonl", ["heavy", "heavy", "baseline"]))
        drain(dialog, app)
        assert dialog.load_result["status"] == "ready", dialog.load_result
        assert len(dialog.rows) == 3, dialog.status.text()
        assert dialog.phase.findData("heavy") >= 0, dialog.status.text()
        dialog.phase.setCurrentIndex(dialog.phase.findData("heavy"))
        dialog.filter.setCurrentIndex(1)
        destination = tmp_path / "scoped.csv"
        monkeypatch.setattr(Q.QFileDialog, "getSaveFileName", lambda *_args: (str(destination), "CSV (*.csv)"))
        dialog.export_records()
        with destination.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 1 and rows[0]["verified"] == "False"
    finally:
        dialog.close(); app.processEvents()


def test_initial_catalog_cannot_discard_explicit_archive_or_restore_old_selection(tmp_path, monkeypatch):
    from tv_scan_studio import archive_jobs
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "active.db")
    root = tmp_path / "research-archives"
    old = import_archive(source(tmp_path / "old.jsonl", ["baseline"]), root)
    store.save_app_settings({"historical_archive_path": str(old["path"])})
    entered, release = threading.Event(), threading.Event()
    original = archive_jobs.archive_catalog
    def gated_catalog(root, *, cancel_requested):
        entered.set()
        while not release.wait(.002):
            if cancel_requested():
                from tv_scan_studio.research_archives import ArchiveCancelled
                raise ArchiveCancelled()
        return original(root, cancel_requested=cancel_requested)
    monkeypatch.setattr(archive_jobs, "archive_catalog", gated_catalog)
    dialog = HistoricalDialog(store)
    try:
        assert entered.wait(3)
        requested = source(tmp_path / "chosen.jsonl", ["heavy", "heavy", "baseline"])
        assert dialog.load_archive(requested)
        assert not dialog.load_archive(tmp_path / "duplicate.jsonl")
        assert dialog.rows == []
        release.set(); drain(dialog, app)
        assert dialog.load_result["status"] == "ready"
        assert len(dialog.rows) == 3
        assert dialog.catalog.currentData()["manifest"]["source_name"] == "chosen.jsonl"
        dialog.phase.setCurrentIndex(dialog.phase.findData("heavy")); dialog.filter.setCurrentIndex(1)
        assert len(dialog.selected_records()) == 1
        assert dialog.initial_requested is None and not dialog.initial_catalog_pending
    finally:
        release.set(); dialog.close(); drain(dialog, app); app.processEvents()


@pytest.mark.parametrize("action", ["cancel", "close", "catalog_error"])
def test_pending_initial_selection_obeys_cancel_close_and_catalog_error(tmp_path, monkeypatch, action):
    from tv_scan_studio import archive_jobs
    from tv_scan_studio.research_archives import ArchiveCancelled
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "active.db")
    (tmp_path / "research-archives").mkdir()
    entered, release = threading.Event(), threading.Event()
    def gated_catalog(root, *, cancel_requested):
        entered.set()
        while not release.wait(.002):
            if cancel_requested(): raise ArchiveCancelled()
        raise ValueError("catalog failed")
    monkeypatch.setattr(archive_jobs, "archive_catalog", gated_catalog)
    dialog = HistoricalDialog(store)
    try:
        assert entered.wait(3)
        assert dialog.load_archive(source(tmp_path / "chosen.jsonl", ["heavy"]))
        if action == "cancel": dialog.cancel_loading()
        elif action == "close": dialog.close()
        else: release.set()
        drain(dialog, app)
        assert dialog.initial_requested is None and not dialog.initial_catalog_pending
        if action == "catalog_error":
            assert dialog.load_result["status"] == "ready", dialog.load_result
            assert len(dialog.rows) == 1
        else:
            assert dialog.rows == [] and not store.app_settings().get("historical_archive_path")
            assert dialog.load_result["status"] == "cancelled"
    finally:
        release.set(); dialog.close(); drain(dialog, app); app.processEvents()


@pytest.mark.parametrize("explicit", [False, True])
def test_cancel_after_catalog_result_before_handlers_never_launches_saved_or_explicit_archive(tmp_path, monkeypatch, explicit):
    from tv_scan_studio import archive_jobs
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "active.db")
    root = tmp_path / "research-archives"
    old = import_archive(source(tmp_path / "old.jsonl", ["baseline"]), root)
    store.save_app_settings({"historical_archive_path": str(old["path"])})
    result_emitted = threading.Event()
    class CompletedCatalog(archive_jobs.ArchiveCatalogJob):
        def run(self):
            # Signals are queued for the GUI; hold event processing until the
            # ready result and finished signal exist, then issue a late cancel.
            self.result.emit({"status": "catalog_ready", "entries": archive_catalog(self.root)})
            result_emitted.set()
    monkeypatch.setattr(archive_jobs, "ArchiveCatalogJob", CompletedCatalog)
    dialog = HistoricalDialog(store)
    started = []
    original_start = dialog.start_archive_job
    def track_start(job, message):
        started.append(job); return original_start(job, message)
    monkeypatch.setattr(dialog, "start_archive_job", track_start)
    try:
        if explicit:
            assert dialog.load_archive(source(tmp_path / "chosen.jsonl", ["heavy"]))
        assert result_emitted.wait(3)
        assert dialog.load_job.wait(3000)  # No GUI handlers have run yet.
        dialog.cancel_loading()
        drain(dialog, app)
        assert not started and dialog.rows == []
        assert dialog.initial_requested is None and dialog.initial_saved is None
        assert store.app_settings()["historical_archive_path"] == str(old["path"])
        assert old["path"].exists()
        assert len(archive_catalog(root)) == 1
    finally:
        dialog.close(); drain(dialog, app); app.processEvents()


def test_file_change_during_display_read_is_rejected(tmp_path, monkeypatch):
    from tv_scan_studio import archive_jobs
    app = Q.QApplication.instance() or Q.QApplication([])
    dialog = HistoricalDialog(Store(tmp_path / "active.db"))
    original_reader = archive_jobs.iter_legacy_scan_records
    def mutating_reader(path, *, check_cancel):
        yield from original_reader(path, check_cancel=check_cancel)
        source(path, ["changed-after-read"])
    monkeypatch.setattr(archive_jobs, "iter_legacy_scan_records", mutating_reader)
    try:
        dialog.load_archive(source(tmp_path / "first.jsonl", ["baseline"])); drain(dialog, app)
        assert dialog.load_result["status"] == "error"
        assert not dialog.rows
        assert not dialog.store.app_settings().get("historical_archive_path")
    finally:
        dialog.close(); app.processEvents()
