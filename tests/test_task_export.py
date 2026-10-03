import csv
import zipfile
from xml.etree import ElementTree as ET

from tv_scan_studio.export import (export_project_task_scope, export_task_csv,
                                   export_task_xlsx, flatten_task_record)
from tv_scan_studio.storage import Store


def test_all_task_export_keeps_failed_tasks_and_typed_excel_metrics(tmp_path):
    store = Store(tmp_path / "studio.db")
    project = store.create_project("Export", 'strategy("Export")\nlength=input.int(3,"Length")')
    assert store.enqueue(project, "passed", {"symbol": "OANDA:DE30EUR", "timeframe": "15",
                                             "inputs": {"in_0": 3}})
    success = store.claim_next(1)
    store.complete(success.id, 1, {"trades": 82, "profit_factor": 1.69,
                                    "max_drawdown_pct": 4.3}, "hassas", verified=True)
    assert store.enqueue(project, "failed", {"symbol": "OANDA:DE30EUR", "timeframe": "15",
                                             "inputs": {"in_0": 4}})
    failed = store.claim_next(1)
    store.fail(failed.id, 1, "CDP bağlantısı koptu", max_attempts=1)
    records = list(store.iter_task_records(project))
    assert len(records) == 2
    assert records[1]["classification"] == "sonuç yok"
    assert records[1]["error"] == "CDP bağlantısı koptu"

    csv_path = tmp_path / "all.csv"
    xlsx_path = tmp_path / "all.xlsx"
    assert export_task_csv(iter(records), csv_path, ["in_0"]) == 2
    assert export_task_xlsx(iter(records), xlsx_path, ["in_0"]) == 2
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["profit_factor"] == "1.69"
    assert rows[1]["error"] == "CDP bağlantısı koptu"
    assert rows[1]["input.in_0"] == "4"
    with zipfile.ZipFile(xlsx_path) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        assert len(sheet.find("{*}sheetData")) == 3
        assert archive.testzip() is None


def test_export_periods_are_readable_and_excel_rejects_illegal_xml_characters(tmp_path):
    record = {"task_id": 1, "task_key": "date", "status": "failed",
              "classification": "sonuç yok", "verified": False, "error": "bad\x00input",
              "attempts": 1, "started_at": None, "finished_at": None,
              "payload": {"date_range": {"from": 1_700_000_000_000, "to": 1_700_086_400_000},
                          "inputs": {}}, "metrics": {}, "evidence": {}}
    csv_path, xlsx_path = tmp_path / "period.csv", tmp_path / "period.xlsx"
    assert export_task_csv([record], csv_path, []) == 1
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["period_from"] == "2023-11-14"
    assert row["period_to"] == "2023-11-15"
    assert export_task_xlsx([record], xlsx_path, []) == 1
    with zipfile.ZipFile(xlsx_path) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        assert "badinput" in ET.tostring(sheet, encoding="unicode")


def test_epoch_period_export_uses_chart_timezone_and_labels_utc_fallback(tmp_path):
    record = {"task_id": 1, "task_key": "boundary", "status": "done",
              "classification": "hassas", "verified": True, "error": "",
              "attempts": 1, "started_at": None, "finished_at": None,
              "payload": {"date_range": {"from_ms": 1735678800000, "to_ms": 1767128400000},
                          "inputs": {}}, "metrics": {},
              "evidence": {"chart_timezone": "Europe/Istanbul"}}
    local = flatten_task_record(record, [])
    assert local["period_from"] == "2025-01-01"
    assert local["period_to"] == "2025-12-31"
    assert local["period_timezone"] == "Europe/Istanbul"
    csv_path, xlsx_path = tmp_path / "chart-period.csv", tmp_path / "chart-period.xlsx"
    assert export_task_csv([record], csv_path, []) == 1
    assert export_task_xlsx([record], xlsx_path, []) == 1
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        saved = next(csv.DictReader(stream))
    assert saved["period_from"] == "2025-01-01"
    assert saved["period_timezone"] == "Europe/Istanbul"
    with zipfile.ZipFile(xlsx_path) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        text = ET.tostring(sheet, encoding="unicode")
        assert "2025-01-01" in text and "Europe/Istanbul" in text
    record["evidence"] = {}
    utc = flatten_task_record(record, [])
    assert utc["period_from"] == "2024-12-31"
    assert utc["period_timezone"] == "UTC (chart timezone unavailable)"
    record["payload"]["date_range"] = {"from": "2025-01-01", "to": "2025-12-31"}
    record["evidence"] = {"chart_timezone": "Europe/Istanbul"}
    assert flatten_task_record(record, [])["period_timezone"] == "Europe/Istanbul"


def test_project_scope_matrix_keeps_failures_and_later_input_columns(tmp_path):
    store = Store(tmp_path / "matrix.db")
    project = store.create_project("Matrix", 'strategy("Matrix")')
    store.enqueue(project, "success", {"symbol": "DE30", "inputs": {"in_0": 3}})
    success = store.claim_next(1)
    store.complete(success.id, 1, {"profit_factor": 1.7}, "hassas", verified=True)
    store.enqueue(project, "failure", {"symbol": "DE30", "inputs": {"in_1": 9}})
    failure = store.claim_next(1)
    store.fail(failure.id, 1, "CDP bağlantısı koptu", max_attempts=1)
    store.enqueue(project, "excluded", {"symbol": "NAS100", "inputs": {"in_2": 12}})
    excluded = store.claim_next(1)
    store.complete(excluded.id, 1, {"profit_factor": 0.8}, "elenmiş", verified=True)

    all_csv = tmp_path / "all.csv"
    success_csv = tmp_path / "success.csv"
    visible_csv = tmp_path / "visible.csv"
    all_xlsx = tmp_path / "all.xlsx"
    assert export_project_task_scope(store, project, all_csv) == 3
    assert export_project_task_scope(store, project, success_csv, successful=True) == 1
    assert export_project_task_scope(store, project, visible_csv,
                                     visible_ids={success.id, excluded.id}) == 2
    assert export_project_task_scope(store, project, all_xlsx, excel=True) == 3
    with all_csv.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert {row["task_key"] for row in rows} == {"success", "failure", "excluded"}
    assert rows[1]["error"] == "CDP bağlantısı koptu"
    assert rows[1]["input.in_1"] == "9"
    assert rows[2]["input.in_2"] == "12"
    with success_csv.open(encoding="utf-8-sig", newline="") as stream:
        assert [row["task_key"] for row in csv.DictReader(stream)] == ["success"]
    with visible_csv.open(encoding="utf-8-sig", newline="") as stream:
        assert [row["task_key"] for row in csv.DictReader(stream)] == ["success", "excluded"]
    with zipfile.ZipFile(all_xlsx) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        text = ET.tostring(sheet, encoding="unicode")
        assert "input.in_0" in text and "input.in_1" in text and "input.in_2" in text
        assert "CDP bağlantısı koptu" in text
