import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import csv
import json
import zipfile
import time
from xml.etree import ElementTree as ET
from PySide6 import QtWidgets as Q
from tv_scan_studio.storage import Store
from tv_scan_studio.historical_dialog import HistoricalDialog


def wait_load(dialog, app):
    deadline = time.monotonic() + 30
    while dialog.load_job is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert dialog.load_job is None
    assert dialog.load_result["status"] == "ready"


def test_archive_paging_filter_exports_and_reopen(tmp_path, monkeypatch):
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "active.db")
    archive = tmp_path / "history.jsonl"
    rows = [{"symbol": "BIST:XU030D1!", "tf": "15", "valid": True, "pass": i % 2 == 0,
             "params": {"in_0": i}, "metrics": {"pf": 1.5, "dd": 2}} for i in range(205)]
    archive.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    dialog = HistoricalDialog(store)
    assert dialog.load_archive(archive)
    wait_load(dialog, app)
    managed = store.app_settings()["historical_archive_path"]
    assert managed != str(archive)
    assert "research-archives" in managed
    assert dialog.load_archive(archive)
    wait_load(dialog, app)
    assert "tekrar eklenmedi" in dialog.status.text()
    archive.unlink()
    dialog.show(); app.processEvents()
    assert dialog.table.isVisible() and dialog.table.rowCount() == 100
    dialog.next.click()
    assert dialog.visible_rows[0]["payload"]["inputs"]["in_0"] == 100
    dialog.filter.setCurrentIndex(1)
    assert len(dialog.selected_records()) == 103
    dialog.table.selectRow(0)
    assert "yeniden doğrulanmadı" in dialog.detail.toPlainText()
    csv_path, xlsx_path = tmp_path / "filtered.csv", tmp_path / "filtered.xlsx"
    monkeypatch.setattr(Q.QFileDialog, "getSaveFileName", lambda *args: (str(csv_path), "CSV (*.csv)"))
    dialog.export_button.click()
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        saved = list(csv.DictReader(stream))
    assert len(saved) == 103 and all(row["verified"] == "False" for row in saved)
    monkeypatch.setattr(Q.QFileDialog, "getSaveFileName", lambda *args: (str(xlsx_path), "Türkçe Excel CSV (*.csv)"))
    dialog.export_button.click()
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        saved = list(csv.DictReader(stream, delimiter=";"))
    assert len(saved) == 103 and saved[0]["profit_factor"] == "1,5"
    assert saved[0]["verified"] == "YANLIŞ"
    assert "noktalı virgül" in dialog.status.text()
    monkeypatch.setattr(Q.QFileDialog, "getSaveFileName", lambda *args: (str(xlsx_path), "Excel (*.xlsx)"))
    dialog.export_button.click()
    with zipfile.ZipFile(xlsx_path) as package:
        assert len(ET.fromstring(package.read("xl/worksheets/sheet1.xml")).find("{*}sheetData")) == 104
    assert store.projects() == []  # Browsing/exporting never inserts runnable work.
    dialog.close()
    reopened = HistoricalDialog(store)
    wait_load(reopened, app)
    assert len(reopened.rows) == 205
    reopened.close()


def test_real_history_filter_counts_and_failure_details(tmp_path):
    from pathlib import Path
    app = Q.QApplication.instance() or Q.QApplication([])
    store = Store(tmp_path / "actual.db")
    dialog = HistoricalDialog(store)
    path = Path(__file__).parents[1] / "src/tv_scan_studio/data/ftmo_overnight_33075.jsonl.gz"
    if not path.is_file():
        import pytest
        pytest.skip("Private archive is optional")
    assert dialog.load_archive(path)
    wait_load(dialog, app)
    assert len(dialog.rows) == 33075
    for choice, count in ((1, 501), (2, 32422), (3, 152)):
        dialog.filter.setCurrentIndex(choice)
        assert len(dialog.selected_records()) == count
    dialog.table.selectRow(0)
    assert dialog.visible_rows[0]["error"]
    dialog.filter.setCurrentIndex(0)
    dialog.page = 330
    dialog.render_page()
    assert dialog.table.rowCount() == 75 and not dialog.next.isEnabled()
    assert not store.projects()
    dialog.close()
