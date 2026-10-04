import csv
import json
import zipfile
from xml.etree import ElementTree as ET

from tv_scan_studio.historical import legacy_scan_record, iter_legacy_scan_records
from tv_scan_studio.export import export_task_csv, export_task_xlsx, flatten_task_record, task_export_columns


def test_legacy_row_preserves_evidence_without_claiming_verification(tmp_path):
    original = {"symbol": "BIST:XU030D1!", "tf": "15", "valid": True, "pass": True,
                "params": {"in_0": 7, "in_1": False}, "metrics": {"pf": 1.7, "dd": 2.1},
                "period": {"dateRange": {"backtest": {"from": 1735689600000, "to": 1735776000000}}}}
    record = legacy_scan_record(original, 1, source_sha256="archive")
    assert record["verified"] is False
    assert record["evidence"]["legacy_record"] == original
    assert record["metrics"]["profit_factor"] == 1.7
    csv_path, xlsx_path = tmp_path / "legacy.csv", tmp_path / "legacy.xlsx"
    assert export_task_csv([record], csv_path, ["in_0", "in_1"]) == 1
    assert export_task_xlsx([record], xlsx_path, ["in_0", "in_1"]) == 1
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["profit_factor"] == "1.7" and row["input.in_0"] == "7"
    assert json.loads(row["evidence_json"])["legacy_record"] == original
    with zipfile.ZipFile(xlsx_path) as archive:
        xml = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        assert len(xml.find("{*}sheetData")) == 2
        assert archive.testzip() is None


def test_real_archive_exports_match_every_record(tmp_path):
    from pathlib import Path
    import pytest
    archive_path = Path(__file__).parents[1] / "src/tv_scan_studio/data/ftmo_overnight_33075.jsonl.gz"
    if not archive_path.is_file():
        pytest.skip("Private historical archive is optional and never bundled")
    records = list(iter_legacy_scan_records(archive_path))
    assert len(records) == 33075
    inputs = sorted({key for row in records for key in row["payload"]["inputs"]})
    csv_path, xlsx_path = tmp_path / "history.csv", tmp_path / "history.xlsx"
    assert export_task_csv(iter(records), csv_path, inputs) == len(records)
    assert export_task_xlsx(iter(records), xlsx_path, inputs) == len(records)
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        for expected, saved in zip(records, csv.DictReader(stream), strict=True):
            assert saved["task_key"] == expected["task_key"]
            assert saved["symbol"] == expected["payload"]["symbol"]
            assert saved["verified"] == "False"
            assert json.loads(saved["evidence_json"])["legacy_record"] == expected["evidence"]["legacy_record"]
    with zipfile.ZipFile(xlsx_path) as archive:
        assert archive.testzip() is None
        columns = task_export_columns(inputs)
        count = 0
        with archive.open("xl/worksheets/sheet1.xml") as stream:
            for event, element in ET.iterparse(stream, events=("end",)):
                if element.tag.endswith("}row"):
                    if count:
                        expected = flatten_task_record(records[count - 1], inputs)
                        saved = []
                        for cell in element:
                            if cell.get("t") == "inlineStr":
                                saved.append(cell.find("{*}is/{*}t").text or "")
                            elif cell.get("t") == "b":
                                saved.append(cell.find("{*}v").text == "1")
                            else:
                                saved.append(float(cell.find("{*}v").text))
                        # Empty cells are omitted by the exporter. Values stay ordered.
                        expected_values = [expected[key] for key in columns if expected[key] is not None and expected[key] != ""]
                        assert saved == expected_values
                    count += 1
                    element.clear()
        assert count == len(records) + 1
