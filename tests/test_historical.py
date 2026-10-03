"""The bundled historical export must reflect the preserved scan, not summary counts."""

from collections import Counter
import csv
from pathlib import Path

import pytest

from tv_scan_studio.historical import iter_historical_records
from tv_scan_studio.export import export_task_csv, export_task_xlsx


pytestmark = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "src/tv_scan_studio/data/ftmo_overnight_33075.jsonl.gz").is_file(),
    reason="Optional private historical scan archive is not bundled",
)


def test_historical_archive_contains_actual_success_and_failure_rows():
    counts = Counter()
    failed = None
    for row in iter_historical_records():
        counts["rows"] += 1
        counts[row["classification"]] += 1
        if row["status"] == "failed":
            failed = row
            counts["failed"] += 1
    assert counts["rows"] == 33_075
    assert counts["orta maliyet geçti"] == 501
    assert counts["elenmiş"] == 32_422
    assert counts["geçersiz"] == 152
    assert counts["failed"] == 152
    assert failed["error"]
    assert failed["payload"]["inputs"]


def test_all_historical_rows_export_to_csv_with_failure_reason(tmp_path):
    records = iter_historical_records()
    first = next(records)
    from itertools import chain

    path = tmp_path / "all.csv"
    assert export_task_csv(chain((first,), records), path, first["payload"]["inputs"]) == 33_075
    counts = Counter()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            counts["rows"] += 1
            counts[row["classification"]] += 1
            if row["status"] == "failed":
                assert row["error"]
                counts["failed"] += 1
    assert counts["rows"] == 33_075
    assert counts["failed"] == 152
    assert counts["orta maliyet geçti"] == 501


def test_all_historical_rows_export_to_excel(tmp_path):
    from itertools import chain
    import zipfile
    import xml.etree.ElementTree as ET

    records = iter_historical_records()
    first = next(records)
    path = tmp_path / "all.xlsx"
    assert export_task_xlsx(chain((first,), records), path, first["payload"]["inputs"]) == 33_075
    with zipfile.ZipFile(path) as archive:
        with archive.open("xl/worksheets/sheet1.xml") as stream:
            count = sum(1 for _event, element in ET.iterparse(stream, events=("end",))
                        if element.tag.endswith("}row"))
    assert count == 33_076  # Header plus every preserved task.
