import csv
import json
import zipfile
from xml.etree import ElementTree as ET

from tv_scan_studio.export import export_task_csv, export_task_xlsx
from tv_scan_studio.historical import legacy_scan_record


def test_turkish_excel_csv_localizes_only_typed_scalars(tmp_path):
    source = {"symbol": "BIST:XU030D1!", "tf": "15", "valid": True, "pass": True,
              "params": {"in_0": 7, "in_1": False, "in_2": -0.03,
                         "in_3": "1.2; özel\nmetin", "in_4": 1.2e-10},
              "metrics": {"pf": 1.71234567890123, "net": -1000.25}}
    record = legacy_scan_record(source, 1, source_sha256="test")
    path = tmp_path / "excel-tr.csv"
    assert export_task_csv(iter([record]), path, source["params"], excel_tr=True) == 1
    assert path.read_bytes().startswith(b'\xef\xbb\xbf')
    with path.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream, delimiter=";"))
    assert row["profit_factor"] == "1,71234567890123"
    assert row["net_profit"] == "-1000,25"
    assert row["verified"] == row["input.in_1"] == "YANLIŞ"
    assert row["input.in_0"] == "7"
    assert row["input.in_2"] == "-0,03"
    assert row["input.in_3"] == source["params"]["in_3"]
    assert float(row["input.in_4"].replace(",", ".")) == 1.2e-10
    assert json.loads(row["evidence_json"])["legacy_record"] == source


def test_excel_columns_have_readable_widths_and_wrapped_header(tmp_path):
    path = tmp_path / "readable.xlsx"
    export_task_xlsx([], path, ["in_0"])
    with zipfile.ZipFile(path) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        widths = sheet.find("{*}cols")
        assert len(widths) == 25
        assert all(float(col.get("width")) >= 16 for col in widths)
        assert sheet.find("{*}sheetData/{*}row").get("ht") == "30"
        assert 'wrapText="1"' in archive.read("xl/styles.xml").decode()
        assert sheet.find("{*}autoFilter").get("ref") == "A1:Y1"
