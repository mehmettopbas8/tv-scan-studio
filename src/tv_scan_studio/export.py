"""CSV exports for scan results."""

from __future__ import annotations

import csv
import json
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def export_results_csv(rows: Iterable[dict[str, Any]], destination: str | Path) -> int:
    """Write result rows with stable columns and flattened payload/metrics."""
    materialized = list(rows)
    payload_keys = sorted({key for row in materialized for key in row["payload"]})
    metric_keys = sorted({key for row in materialized for key in row["metrics"]})
    evidence_keys = sorted({key for row in materialized for key in row.get("evidence", {})})
    fieldnames = ["task_key", "classification", "verified"]
    fieldnames += [f"input.{key}" for key in payload_keys]
    fieldnames += [f"metric.{key}" for key in metric_keys]
    fieldnames += [f"observed.{key}" for key in evidence_keys]

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in materialized:
            output = {
                "task_key": row["task_key"],
                "classification": row["classification"],
                "verified": row["verified"],
            }
            output.update({f"input.{key}": row["payload"].get(key, "") for key in payload_keys})
            output.update({f"metric.{key}": row["metrics"].get(key, "") for key in metric_keys})
            output.update({f"observed.{key}": row.get("evidence", {}).get(key, "") for key in evidence_keys})
            writer.writerow(output)
    return len(materialized)


BASE_COLUMNS = (
    "task_id", "task_key", "status", "classification", "verified", "error",
    "symbol", "timeframe", "period_from", "period_to", "period_timezone", "attempts",
    "started_at", "finished_at", "trades", "profit_factor", "win_rate_pct",
    "max_drawdown_pct", "net_profit", "research_source_id", "costs_json",
    "evidence_json", "other_metrics_json", "other_inputs_json",
)


def task_export_columns(input_ids: Iterable[str]) -> list[str]:
    return [*BASE_COLUMNS, *(f"input.{key}" for key in input_ids)]


def flatten_task_record(row: dict[str, Any], input_ids: Iterable[str]) -> dict[str, Any]:
    payload, metrics = row["payload"], row["metrics"]
    inputs = payload.get("inputs") or {}
    dates = payload.get("date_range") or {}
    input_ids = tuple(input_ids)
    chart_zone = (row.get("evidence") or {}).get("chart_timezone")
    try:
        period_zone = ZoneInfo(chart_zone) if isinstance(chart_zone, str) and chart_zone else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        period_zone = timezone.utc
    epoch_period = any(isinstance(dates.get(key), (int, float)) and
                       not isinstance(dates.get(key), bool)
                       for key in ("from_ms", "from", "to_ms", "to"))
    period_timezone = (chart_zone if isinstance(period_zone, ZoneInfo) else
                       "UTC (chart timezone unavailable)" if epoch_period else "")

    def stamp(value: Any) -> str:
        return (datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")
                if isinstance(value, (int, float)) else "")

    def period(value: Any) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value,
                                          period_zone).date().isoformat()
        return str(value or "")

    output = {
        "task_id": row["task_id"], "task_key": row["task_key"],
        "status": row["status"], "classification": row["classification"],
        "verified": row["verified"], "error": row["error"],
        "symbol": payload.get("symbol", ""), "timeframe": payload.get("timeframe", ""),
        "period_from": period(dates.get("from_ms", dates.get("from", ""))),
        "period_to": period(dates.get("to_ms", dates.get("to", ""))),
        "period_timezone": period_timezone,
        "attempts": row["attempts"], "started_at": stamp(row["started_at"]),
        "finished_at": stamp(row["finished_at"]),
        "trades": metrics.get("trades"), "profit_factor": metrics.get("profit_factor"),
        "win_rate_pct": metrics.get("win_rate_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "net_profit": metrics.get("net_profit"),
        "research_source_id": payload.get("research_source_id", ""),
        "costs_json": json.dumps(payload.get("costs") or {}, ensure_ascii=False, sort_keys=True),
        "evidence_json": json.dumps(row.get("evidence") or {}, ensure_ascii=False, sort_keys=True),
        "other_metrics_json": json.dumps({k: v for k, v in metrics.items()
                                           if k not in {"trades", "profit_factor", "win_rate_pct",
                                                        "max_drawdown_pct", "net_profit"}},
                                          ensure_ascii=False, sort_keys=True),
        "other_inputs_json": json.dumps({k: v for k, v in inputs.items() if k not in input_ids},
                                        ensure_ascii=False, sort_keys=True),
    }
    output.update({f"input.{key}": inputs.get(key) for key in input_ids})
    return output


def export_task_csv(records: Iterable[dict[str, Any]], destination: str | Path,
                    input_ids: Iterable[str]) -> int:
    """Stream all requested task rows without materializing the scan universe."""
    input_ids = tuple(input_ids)
    columns = task_export_columns(input_ids)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow(flatten_task_record(record, input_ids))
            count += 1
    return count


def export_project_task_scope(store, project_id: int, destination: str | Path, *,
                              successful: bool = False, visible_ids: set[int] | None = None,
                              excel: bool = False) -> int:
    """Export a selected project scope with every observed input column.

    The first pass discovers the schema only; the second streams rows to disk.
    Failed tasks with no result row remain in the all-tasks scope.
    """
    from .result_filters import SUCCESS_CLASSES

    def selected(connection):
        for record in store.iter_task_records(project_id, connection=connection):
            if successful and (record["classification"] not in SUCCESS_CLASSES
                               or not record["verified"]):
                continue
            if visible_ids is not None and record["task_id"] not in visible_ids:
                continue
            yield record

    with store.connect() as connection:
        connection.execute("BEGIN")  # Both passes see one immutable SQLite snapshot.
        input_ids: set[str] = set()
        count = 0
        for record in selected(connection):
            count += 1
            input_ids.update((record["payload"].get("inputs") or {}).keys())
        if not count:
            return 0
        writer = export_task_xlsx if excel else export_task_csv
        written = writer(selected(connection), destination, sorted(input_ids))
        if written != count:
            raise RuntimeError("Dışa aktarma sırasında görev sayısı değişti; dosyayı doğrulayın.")
        return written


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _xlsx_cell(reference: str, value: Any, *, header: bool = False) -> str:
    if value is None or value == "":
        return ""
    style = ' s="1"' if header else ""
    if isinstance(value, bool):
        return f'<c r="{reference}" t="b"{style}><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)) and math.isfinite(value):
        return f'<c r="{reference}"{style}><v>{value}</v></c>'
    text = escape("".join(character for character in str(value)
                          if ord(character) in (9, 10, 13) or ord(character) >= 32))
    return f'<c r="{reference}" t="inlineStr"{style}><is><t>{text}</t></is></c>'


def _xlsx_sheet(stream, records: Iterable[dict[str, Any]], columns: list[str],
                input_ids: tuple[str, ...]) -> int:
    prefix = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
              'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetData>')
    stream.write(prefix.encode("utf-8"))
    def write_row(number: int, values: Iterable[Any], *, header: bool = False) -> None:
        cells = "".join(_xlsx_cell(f"{_column_name(index)}{number}", value, header=header)
                        for index, value in enumerate(values, 1))
        stream.write(f'<row r="{number}">{cells}</row>'.encode("utf-8"))

    write_row(1, columns, header=True)
    count = 0
    for count, record in enumerate(records, 1):
        row = flatten_task_record(record, input_ids)
        write_row(count + 1, (row[column] for column in columns))
    end = (f'</sheetData><autoFilter ref="A1:{_column_name(len(columns))}{count + 1}"/>'
           '</worksheet>')
    stream.write(end.encode("utf-8"))
    return count


def export_task_xlsx(records: Iterable[dict[str, Any]], destination: str | Path,
                     input_ids: Iterable[str]) -> int:
    """Write a filterable, frozen-header Excel file with bounded memory."""
    import itertools

    input_ids = tuple(input_ids)
    columns = task_export_columns(input_ids)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    iterator = iter(records)
    sheets = 0
    count = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        while True:
            batch = list(itertools.islice(iterator, 1))
            if not batch and sheets:
                break
            sheets += 1
            with archive.open(f"xl/worksheets/sheet{sheets}.xml", "w") as stream:
                current = _xlsx_sheet(stream, itertools.chain(batch, itertools.islice(iterator, 1_048_574)),
                                      columns, input_ids)
            count += current
            if not batch:
                break
        archive.writestr("[Content_Types].xml", _xlsx_content_types(sheets))
        archive.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>'
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                         '</Relationships>')
        archive.writestr("xl/workbook.xml", _xlsx_workbook(sheets))
        archive.writestr("xl/_rels/workbook.xml.rels", _xlsx_workbook_rels(sheets))
        archive.writestr("xl/styles.xml", _XLSX_STYLES)
    return count


def _xlsx_content_types(sheets: int) -> str:
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheets + 1)
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f'{overrides}</Types>')


def _xlsx_workbook(sheets: int) -> str:
    entries = "".join(f'<sheet name="Tarama {index}" sheetId="{index}" r:id="rId{index}"/>'
                      for index in range(1, sheets + 1))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{entries}</sheets></workbook>')


def _xlsx_workbook_rels(sheets: int) -> str:
    entries = "".join(f'<Relationship Id="rId{index}" '
                      'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                      f'Target="worksheets/sheet{index}.xml"/>' for index in range(1, sheets + 1))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{entries}<Relationship Id="rId{sheets + 1}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/></Relationships>')


_XLSX_STYLES = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<fonts count="2"><font><sz val="10"/><name val="Aptos"/><color rgb="FF3A322A"/></font>'
                '<font><b/><sz val="10"/><name val="Aptos"/><color rgb="FF3A322A"/></font></fonts>'
                '<fills count="2"><fill><patternFill patternType="none"/></fill>'
                '<fill><patternFill patternType="solid"><fgColor rgb="FFF5ECDD"/><bgColor indexed="64"/></patternFill></fill></fills>'
                '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                '<xf numFmtId="0" fontId="1" fillId="1" borderId="0" xfId="0" applyFill="1" applyFont="1"/></cellXfs>'
                '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                '</styleSheet>')
