"""Read TradingView Strategy Report XLSX exports without executing workbook content.

The export is evidence only after the caller also verifies the live worker layout,
Deep mode, selected dates, chart inputs and a fresh download for the same task.
"""

from __future__ import annotations

import hashlib
import math
import posixpath
import re
import time as clock
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .pine import parse_strategy_inputs
from .report_currency import report_currency_code
from .tradingview import chart_resolution, symbol_matches


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
REQUIRED_SHEETS = ("Performance", "Trades analysis", "Trades", "Properties")
MAX_XLSX_BYTES = 128 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_TRADE_ROWS = 500_000


class DeepExportError(ValueError):
    """A download is missing, stale, incompatible or internally inconsistent."""


def xlsx_download_baseline(directory: str | Path) -> frozenset[str]:
    """Remember existing XLSX names before clicking the target's download action."""
    folder = Path(directory)
    if not folder.is_dir():
        raise DeepExportError("TradingView indirme klasörü bulunamadı.")
    return frozenset(item.name for item in folder.iterdir()
                     if item.is_file() and item.suffix.lower() == ".xlsx")


def wait_for_unique_fresh_xlsx(directory: str | Path, *, baseline: frozenset[str],
                               started_ns: int, timeout: float = 75,
                               poll_interval: float = 0.25) -> Path:
    """Claim one completed new download; never guess among concurrent XLSX files.

    This only identifies a fresh file. The caller must still prove the guarded
    target, refreshed Deep UI and task/export identity before using its results.
    """
    folder = Path(directory)
    if not folder.is_dir() or started_ns <= 0 or timeout <= 0:
        raise DeepExportError("TradingView indirme bekleme ayarları geçersiz.")
    deadline = clock.monotonic() + timeout
    last_signature: tuple[str, int, int] | None = None
    stable = 0
    while clock.monotonic() < deadline:
        candidates: list[tuple[Path, int, int]] = []
        new_files: list[Path] = []
        for item in folder.iterdir():
            if item.name in baseline or item.suffix.lower() != ".xlsx":
                continue
            try:
                stat = item.stat()
            except OSError:
                continue
            if item.is_file():
                new_files.append(item)
            # Windows may give a new file the same timestamp tick as the click.
            # The pre-click filename baseline is the primary freshness guard.
            if item.is_file() and stat.st_mtime_ns >= started_ns:
                candidates.append((item, stat.st_size, stat.st_mtime_ns))
        # Count every file absent from the baseline before applying the timestamp
        # gate. Clock/filesystem precision must not conceal a competing download.
        if len(new_files) > 1:
            raise DeepExportError("Aynı anda birden fazla yeni XLSX bulundu; indirme belirsiz.")
        if candidates:
            item, size, mtime_ns = candidates[0]
            signature = (item.name, size, mtime_ns)
            stable = stable + 1 if signature == last_signature else 1
            last_signature = signature
            if stable >= 2 and size > 0 and zipfile.is_zipfile(item):
                return item
        else:
            last_signature = None
            stable = 0
        clock.sleep(max(0.01, poll_interval))
    raise DeepExportError("Yeni ve kararlı TradingView XLSX indirmesi tamamlanmadı.")


@dataclass(frozen=True, slots=True)
class DeepExport:
    metrics: dict[str, float | int]
    properties: dict[str, str]
    trades: tuple[dict[str, Any], ...]
    backtesting_range: str
    sha256: str
    mtime_ns: int
    performance_headers: tuple[str, ...] = ()
    performance_headers_provenance: str = "unknown"
    trade_pnl_header: str | None = None
    open_trade_count: int = 0
    open_pnl: float | None = None


def _trade_pnl_header(headers) -> str:
    monetary = [key for key in headers if isinstance(key, str) and key.startswith("Net PnL ")]
    if len(monetary) != 1 or report_currency_code(monetary[0][8:]) is None:
        raise DeepExportError("TradingView işlem kâr/zarar para birimi eksik veya belirsiz.")
    return monetary[0]


@dataclass(frozen=True, slots=True)
class DeepStrategyProperties:
    initial_capital: float
    default_order_size: float
    default_order_unit: str
    commission_value: float
    slippage_ticks: int


def strategy_properties(report: DeepExport) -> DeepStrategyProperties:
    """Read the Strategy Properties fields, distinct from similarly named Pine inputs.

    The XLSX Commission field has no unit/type label; this only observes its
    numeric value and must not be used to assert that a requested percentage
    or cash-per-contract mode was applied.
    """
    values = report.properties

    def scalar(name: str) -> float:
        raw = values.get(name, "")
        if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", raw):
            raise DeepExportError(f"TradingView Strategy Properties alanı okunamadı: {name}")
        number = float(raw)
        if not -float("inf") < number < float("inf"):
            raise DeepExportError(f"TradingView Strategy Properties alanı sonlu değil: {name}")
        return number

    order = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s+(.+?)\s*", values.get("Default order size", ""))
    slip = re.fullmatch(r"\s*(\d+)\s+ticks?\s*", values.get("Slippage", ""))
    if order is None or slip is None:
        raise DeepExportError("TradingView emir büyüklüğü veya slippage birimi okunamadı.")
    return DeepStrategyProperties(
        initial_capital=scalar("Initial capital"),
        default_order_size=float(order.group(1)),
        default_order_unit=order.group(2),
        commission_value=scalar("Commission"),
        slippage_ticks=int(slip.group(1)),
    )


def verify_deep_property_scalars(report: DeepExport, *, initial_capital: float,
                                 position_size: float, slippage_ticks: int,
                                 commission_value: float | None = None) -> DeepStrategyProperties:
    """Reject different Strategy Properties; matching commission numbers do not prove its mode."""
    observed = strategy_properties(report)
    expected = (initial_capital, position_size, slippage_ticks)
    if commission_value is not None:
        expected += (commission_value,)
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in expected):
        raise DeepExportError("Beklenen TradingView maliyet ayarları geçersiz.")
    if initial_capital <= 0 or position_size <= 0 or slippage_ticks < 0 or not float(slippage_ticks).is_integer():
        raise DeepExportError("Beklenen TradingView maliyet ayarları geçersiz.")
    if abs(observed.initial_capital - initial_capital) > 0.005:
        raise DeepExportError("TradingView başlangıç sermayesi görevle eşleşmiyor.")
    if observed.default_order_unit != "contracts" or abs(observed.default_order_size - position_size) > 1e-8:
        raise DeepExportError("TradingView emir büyüklüğü görevle eşleşmiyor veya birimi belirsiz.")
    if observed.slippage_ticks != slippage_ticks:
        raise DeepExportError("TradingView slippage göreviyle eşleşmiyor.")
    if commission_value is not None and abs(observed.commission_value - commission_value) > 1e-8:
        raise DeepExportError("TradingView komisyon sayısı görevle eşleşmiyor; birim yine doğrulanmadı.")
    return observed


def verify_deep_input_values(report: DeepExport, *, pine_source: str,
                             expected_inputs: dict[str, Any],
                             changed_input_ids: set[str]) -> tuple[str, ...]:
    """Prove changed Pine inputs in XLSX Properties by unique display title.

    This is intentionally limited to changed inputs. A duplicate/missing title,
    unsupported input kind or ambiguous display value cannot establish that an
    export belongs to the task; the caller must reject, not guess by row order.
    """
    definitions = parse_strategy_inputs(pine_source)
    title_counts: dict[str, int] = {}
    for item in definitions:
        title_counts[item.title] = title_counts.get(item.title, 0) + 1
    verified: list[str] = []
    for input_id in sorted(changed_input_ids, key=lambda key: int(key[3:]) if re.fullmatch(r"in_\d+", key) else -1):
        match = re.fullmatch(r"in_(\d+)", input_id)
        if match is None or input_id not in expected_inputs or int(match.group(1)) >= len(definitions):
            raise DeepExportError("Değişen TradingView input kimliği Pine kaynağıyla eşleşmiyor.")
        definition = definitions[int(match.group(1))]
        title = definition.title
        if (definition.manual_definition_required or not title.strip()
                or title_counts[title] != 1 or title not in report.properties):
            raise DeepExportError(f"Değişen input raporda tekil başlıkla doğrulanamıyor: {input_id}")
        expected, shown = expected_inputs[input_id], report.properties[title]
        if definition.kind == "bool":
            matched = type(expected) is bool and shown == ("On" if expected else "Off")
        elif definition.kind in {"int", "float"}:
            numeric = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", shown)
            matched = (type(expected) in {int, float} and numeric is not None
                       and math.isfinite(expected)
                       and math.isclose(float(shown), float(expected), rel_tol=1e-9, abs_tol=1e-9))
        elif definition.kind in {"string", "session", "timeframe"}:
            matched = type(expected) is str and shown == expected
        else:
            raise DeepExportError(f"Değişen input türü XLSX ile doğrulanamıyor: {input_id}")
        if not matched:
            raise DeepExportError(f"Değişen input değeri XLSX raporuyla eşleşmiyor: {input_id}")
        verified.append(input_id)
    return tuple(verified)


def normalized_closed_trades(report: DeepExport, *, authenticated_timezone: str | None = None) -> tuple[dict[str, Any], ...]:
    """Convert paired XLSX entry/exit rows for closed-trade analytics.

    TradingView exports Excel serial dates in the chart's configured timezone.
    The duplicated PnL on entry and exit rows is counted only once. These
    records contain no intrabar equity, so they cannot prove FTMO loss limits.
    """
    # Conversion is not provenance. The capture path may supply a zone only
    # after every native row matches the independently bound Deep model.
    zone_name = authenticated_timezone or report.properties.get("Timezone", "")
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise DeepExportError("TradingView işlem saat dilimi eksik veya geçersiz.") from exc

    def timestamp_ms(row: dict[str, Any]) -> int:
        serial = row.get("Date and time")
        if isinstance(serial, bool) or not isinstance(serial, (int, float)) or not 1 <= serial <= 2958465:
            raise DeepExportError("TradingView işlem tarihi Excel seri zamanı değil.")
        local = datetime(1899, 12, 30) + timedelta(days=serial)
        aware = local.replace(tzinfo=zone)
        if aware.utcoffset() != local.replace(tzinfo=zone, fold=1).utcoffset():
            raise DeepExportError("TradingView işlem tarihi saat diliminde belirsiz.")
        if aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local:
            raise DeepExportError("TradingView işlem tarihi saat diliminde belirsiz veya geçersiz.")
        return round(aware.timestamp() * 1000)

    pairs: dict[int, dict[str, dict[str, Any]]] = {}
    headers = set().union(*(row.keys() for row in report.trades)) if report.trades else set()
    pnl_header = report.trade_pnl_header or (_trade_pnl_header(headers) if headers else None)
    if headers and _trade_pnl_header(headers) != pnl_header:
        raise DeepExportError("TradingView işlem para birimi sütunuyla eşleşmiyor.")
    has_unit_header = bool(report.performance_headers and report.performance_headers[0] == "")
    if pnl_header and (pnl_header != "Net PnL USD" or has_unit_header) and observed_report_currency(report) != pnl_header[8:]:
        raise DeepExportError("TradingView işlem ve rapor para birimleri doğrulanamadı.")
    for row in report.trades:
        number = row.get("Trade number")
        kind = str(row.get("Type") or "")
        match = re.fullmatch(r"(Entry|Exit) (long|short)", kind)
        if isinstance(number, bool) or not isinstance(number, int) or number < 1 or match is None:
            raise DeepExportError("TradingView işlem numarası veya türü geçersiz.")
        record = pairs.setdefault(number, {})
        key = match.group(1).lower()
        if key in record:
            raise DeepExportError("TradingView işleminde yinelenen giriş veya çıkış var.")
        record[key] = row

    normalized: list[dict[str, Any]] = []
    open_values: list[float] = []
    for number in sorted(pairs):
        record = pairs[number]
        if set(record) != {"entry", "exit"}:
            raise DeepExportError("TradingView işleminin giriş veya çıkış satırı eksik.")
        entry, exit_ = record["entry"], record["exit"]
        side = str(entry["Type"]).split()[1]
        if exit_["Type"] != f"Exit {side}":
            raise DeepExportError("TradingView işlem yönü giriş ve çıkışta farklı.")
        entry_ms = timestamp_ms(entry)
        is_open = exit_.get("Signal") == "Open"
        # Native Deep exports explicitly write "Open" instead of inventing an
        # exit time for an unclosed position. Numeric mark times remain checked.
        exit_ms = None if is_open and exit_.get("Date and time") == "Open" else timestamp_ms(exit_)
        if exit_ms is not None and exit_ms < entry_ms:
            raise DeepExportError("TradingView işlem çıkışı girişten önce.")
        pnl = exit_.get(pnl_header)
        if isinstance(pnl, bool) or not isinstance(pnl, (int, float)) or not -float("inf") < pnl < float("inf"):
            raise DeepExportError("TradingView işlem kâr/zararı geçersiz.")
        if entry.get("Signal") == "Open":
            raise DeepExportError("TradingView açık işlem işareti giriş satırında olamaz.")
        if is_open:
            open_values.append(float(pnl))
            continue
        normalized.append({
            "e": {"tm": entry_ms, "tp": side, "c": str(entry.get("Signal") or "")},
            "x": {"tm": exit_ms}, "tp": {"v": float(pnl)},
        })
    _verify_open_totals(open_values, report.open_trade_count, report.open_pnl)
    if len(normalized) != report.metrics["trades"]:
        raise DeepExportError("TradingView eşleştirilmiş işlem sayısı raporla uyuşmuyor.")
    if abs(sum(item["tp"]["v"] for item in normalized) - report.metrics["net_profit"]) > 0.05:
        raise DeepExportError("TradingView işlem kâr/zararı rapor toplamıyla uyuşmuyor.")
    return tuple(normalized)


def _verify_open_totals(values: list[float], count: int, pnl: float | None) -> None:
    if type(count) is not int or count < 0 or len(values) != count:
        raise DeepExportError("TradingView açık işlem sayısı raporla uyuşmuyor.")
    if values or pnl is not None:
        if type(pnl) not in {int, float} or not math.isfinite(pnl) or abs(sum(values) - pnl) > 0.05:
            raise DeepExportError("TradingView açık işlem kâr/zararı raporla uyuşmuyor.")


def _cell_value(cell: ET.Element, shared: list[str]) -> str | float | int | None:
    kind = cell.get("t")
    raw = cell.findtext(f"{{{MAIN}}}v")
    if cell.find(f"{{{MAIN}}}f") is not None:
        raise DeepExportError("TradingView dışa aktarımında formül var; değer güvenle okunamadı.")
    if kind == "inlineStr":
        return "".join(part.text or "" for part in cell.iter(f"{{{MAIN}}}t"))
    if kind == "s":
        try:
            return shared[int(raw or "")]
        except (ValueError, IndexError) as exc:
            raise DeepExportError("XLSX shared string dizini geçersiz.") from exc
    if kind in {"str", "e"}:
        return raw or ""
    if kind == "b":
        return 1 if raw == "1" else 0
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise DeepExportError("XLSX sayısal hücresi geçersiz.") from exc
    if not (-float("inf") < value < float("inf")):
        raise DeepExportError("XLSX sayısal hücresi sonlu değil.")
    return int(value) if value.is_integer() else value


def _sheet_rows(xml: bytes, shared: list[str]) -> list[list[Any]]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise DeepExportError("XLSX sayfa XML'i okunamadı.") from exc
    rows: list[list[Any]] = []
    for row in root.findall(f".//{{{MAIN}}}sheetData/{{{MAIN}}}row"):
        cells: dict[int, Any] = {}
        for cell in row.findall(f"{{{MAIN}}}c"):
            reference = cell.get("r", "")
            match = re.fullmatch(r"([A-Z]{1,3})[1-9]\d*", reference)
            if not match:
                raise DeepExportError("XLSX hücre konumu geçersiz.")
            column = 0
            for character in match.group(1):
                column = column * 26 + ord(character) - ord("A") + 1
            if column > 64:
                raise DeepExportError("TradingView XLSX sütun sınırı aşıldı.")
            cells[column - 1] = _cell_value(cell, shared)
        rows.append([cells.get(column) for column in range(max(cells, default=-1) + 1)])
    return rows


def _read_tables(path: Path) -> dict[str, list[list[Any]]]:
    if path.suffix.lower() != ".xlsx" or not path.is_file() or path.stat().st_size > MAX_XLSX_BYTES:
        raise DeepExportError("Geçerli ve sınırlı boyutta bir XLSX gerekli.")
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise DeepExportError("TradingView XLSX arşivi açılamadı.") from exc
    with archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
            raise DeepExportError("TradingView XLSX açılmış boyut sınırını aşıyor.")
        try:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        except (KeyError, ET.ParseError) as exc:
            raise DeepExportError("TradingView XLSX çalışma kitabı yapısı eksik.") from exc
        targets = {item.get("Id"): item.get("Target") for item in relations.findall(f"{{{PKG_REL}}}Relationship")}
        names: dict[str, str] = {}
        for sheet in workbook.findall(f".//{{{MAIN}}}sheets/{{{MAIN}}}sheet"):
            name, relation = sheet.get("name"), sheet.get(f"{{{REL}}}id")
            if name in names:
                raise DeepExportError("XLSX yinelenen sayfa adı içeriyor.")
            if name and relation in targets:
                target = targets[relation] or ""
                entry = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
                if not entry.startswith("xl/worksheets/") or ".." in entry.split("/"):
                    raise DeepExportError("XLSX sayfa bağlantısı güvenli değil.")
                names[name] = entry
        missing = set(REQUIRED_SHEETS) - names.keys()
        if missing:
            raise DeepExportError("TradingView XLSX sayfaları eksik: " + ", ".join(sorted(missing)))
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            try:
                strings = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = ["".join(t.text or "" for t in item.iter(f"{{{MAIN}}}t"))
                          for item in strings.findall(f"{{{MAIN}}}si")]
            except ET.ParseError as exc:
                raise DeepExportError("XLSX metin dizisi okunamadı.") from exc
        tables = {}
        for name in REQUIRED_SHEETS:
            try:
                tables[name] = _sheet_rows(archive.read(names[name]), shared)
            except KeyError as exc:
                raise DeepExportError("TradingView XLSX sayfası bulunamadı.") from exc
        return tables


def _labeled_rows(rows: list[list[Any]], label: str) -> list[list[Any]]:
    return [row for row in rows if row and str(row[0] or "").strip() == label]


def _value(rows: list[list[Any]], label: str, column: int = 1) -> Any:
    found = _labeled_rows(rows, label)
    if len(found) != 1 or len(found[0]) <= column or found[0][column] is None:
        raise DeepExportError(f"TradingView XLSX alanı eksik veya belirsiz: {label}")
    return found[0][column]


def _number(rows: list[list[Any]], label: str, column: int = 1) -> float:
    value = _value(rows, label, column)
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise DeepExportError(f"TradingView XLSX sayısal alanı geçersiz: {label}")
    return float(value)


def summarize_deep_export(tables: dict[str, list[list[Any]]], sha256: str = "",
                          mtime_ns: int = 0) -> DeepExport:
    missing = set(REQUIRED_SHEETS) - tables.keys()
    if missing:
        raise DeepExportError("TradingView XLSX sayfaları eksik: " + ", ".join(sorted(missing)))
    performance = tables["Performance"]
    analysis = tables["Trades analysis"]
    raw_properties = tables["Properties"]
    trade_rows = tables["Trades"]
    if not trade_rows or len(trade_rows) - 1 > MAX_TRADE_ROWS:
        raise DeepExportError("TradingView işlem listesi boş veya desteklenen sınırdan büyük.")
    headers = [str(value or "") for value in trade_rows[0]]
    required_headers = {"Trade number", "Type", "Date and time"}
    if not required_headers.issubset(headers) or len(set(headers)) != len(headers):
        raise DeepExportError("TradingView işlem sütunları eksik veya yineleniyor.")
    pnl_header = _trade_pnl_header(headers)
    trades = tuple(dict(zip(headers, row)) for row in trade_rows[1:] if any(value is not None for value in row))
    total_trades = _number(analysis, "Total trades")
    if not total_trades.is_integer() or total_trades < 0:
        raise DeepExportError("TradingView toplam işlem sayısı geçersiz.")
    exits = [row for row in trades if str(row.get("Type", "")).startswith("Exit ")]
    open_exits = [row for row in exits if row.get("Signal") == "Open"]
    open_labels = _labeled_rows(analysis, "Total open trades")
    open_count_value = _number(analysis, "Total open trades") if open_labels or open_exits else 0.0
    if not math.isfinite(open_count_value) or not open_count_value.is_integer() or open_count_value < 0:
        raise DeepExportError("TradingView açık işlem sayısı geçersiz.")
    open_pnl_labels = _labeled_rows(performance, "Open PnL")
    open_pnl = _number(performance, "Open PnL") if open_pnl_labels or open_exits else None
    open_values = []
    for row in open_exits:
        value = row.get(pnl_header)
        if type(value) not in {int, float} or not math.isfinite(value):
            raise DeepExportError("TradingView açık işlem kâr/zararı geçersiz.")
        open_values.append(float(value))
    _verify_open_totals(open_values, int(open_count_value), open_pnl)
    if len(exits) - len(open_exits) != int(total_trades):
        raise DeepExportError("TradingView işlem listesi ile toplam işlem sayısı eşleşmiyor.")
    gross_profit = _number(performance, "Gross profit")
    gross_loss = _number(performance, "Gross loss")
    net_profit = _number(performance, "Net profit")
    if abs((gross_profit - gross_loss) - net_profit) > 0.05:
        raise DeepExportError("TradingView kâr/zarar toplamları uzlaşmıyor.")
    if gross_loss < 0 or gross_profit < 0:
        raise DeepExportError("TradingView brüt kâr/zarar işaretleri geçersiz.")
    properties: dict[str, str] = {}
    for row in raw_properties:
        if len(row) >= 2 and row[0] is not None and row[1] is not None:
            key = str(row[0]).strip()
            if key in properties:
                raise DeepExportError("TradingView Properties etiketi yineleniyor: " + key)
            properties[key] = str(row[1]).strip()
    backtesting_range = properties.get("Backtesting range", "")
    if not backtesting_range or not properties.get("Symbol") or not properties.get("Timeframe"):
        raise DeepExportError("TradingView XLSX rapor kimliği eksik.")
    metrics: dict[str, float | int] = {
        "trades": int(total_trades),
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else 0.0,
        "win_rate_pct": _number(analysis, "Percent profitable", 2),
        "max_drawdown_pct": _number(performance, "Max drawdown (intrabar)", 2),
        "net_profit": net_profit,
        "net_profit_pct": _number(performance, "Net profit", 2),
    }
    # Keep the actual first Performance row, not labels reconstructed from metrics
    # or Properties/Pine inputs. Unknown layouts are retained but not promoted.
    headers_evidence = tuple(str(value) if value is not None else "" for value in performance[0]) if performance else ()
    report = DeepExport(metrics, properties, trades, backtesting_range, sha256, mtime_ns,
                        headers_evidence, "performance_sheet_row1", pnl_header,
                        int(open_count_value), open_pnl)
    # Legacy USD exports without a Performance header remain readable, but do not
    # gain report-currency evidence. Other units require explicit matching proof.
    if (pnl_header != "Net PnL USD" or (headers_evidence and headers_evidence[0] == "")) and observed_report_currency(report) != pnl_header[8:]:
        raise DeepExportError("TradingView işlem ve rapor para birimleri eşleşmiyor veya belirsiz.")
    return report


def read_deep_export(path: str | Path, *, downloaded_after_ns: int = 0) -> DeepExport:
    source = Path(path)
    if not source.is_file():
        raise DeepExportError("Yeni TradingView XLSX indirmesi bulunamadı.")
    before = source.stat()
    if before.st_mtime_ns < downloaded_after_ns:
        raise DeepExportError("Yeni TradingView XLSX indirmesi bulunamadı.")
    tables = _read_tables(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise DeepExportError("TradingView XLSX okunurken değişti; rapor doğrulanamadı.")
    return summarize_deep_export(tables, digest, after.st_mtime_ns)


_TIMEFRAME_LABELS = {
    "1": "1 minute", "2": "2 minutes", "3": "3 minutes", "5": "5 minutes", "15": "15 minutes",
    "30": "30 minutes", "60": "1 hour", "120": "2 hours", "240": "4 hours",
    "D": "1 day", "W": "1 week", "M": "1 month", "1M": "1 month",
}


def _utc_bounds(backtesting_range: str, chart_timezone: str) -> tuple[datetime, datetime]:
    if not isinstance(backtesting_range, str) or not isinstance(chart_timezone, str):
        raise DeepExportError("TradingView XLSX tarih aralığı veya saat dilimi okunamadı.")
    bounds = backtesting_range.split(" — ")
    if len(bounds) != 2:
        raise DeepExportError("TradingView XLSX tarih aralığı okunamadı.")
    try:
        zone = ZoneInfo(chart_timezone)
        try:
            local = [datetime.strptime(value, "%b %d, %Y, %H:%M") for value in bounds]
        except ValueError:
            # Date-only exports include the stated final day. Minute-precision
            # exports already expose the exclusive final boundary (verifier contract).
            local = [datetime.strptime(value, "%b %d, %Y") for value in bounds]
            local[1] += timedelta(days=1)
        for stamp in local:
            aware = stamp.replace(tzinfo=zone)
            if (aware.utcoffset() != stamp.replace(tzinfo=zone, fold=1).utcoffset() or
                    aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != stamp):
                raise DeepExportError("TradingView XLSX tarihinin saat dilimi dönüşümü belirsiz veya geçersiz.")
        local = [stamp.replace(tzinfo=zone) for stamp in local]
    except (ValueError, OverflowError, ZoneInfoNotFoundError) as exc:
        raise DeepExportError("TradingView XLSX saat dilimi veya tarihi geçersiz.") from exc
    start, stop = local[0].astimezone(timezone.utc), local[1].astimezone(timezone.utc)
    if start >= stop:
        raise DeepExportError("TradingView XLSX tarih aralığı boş veya ters.")
    return start, stop


def observed_report_period(report: DeepExport, chart_timezone: str) -> dict[str, Any]:
    """Observed export range in UTC, without any requested-plan substitution.

    to_ms is inclusive; end_exclusive_ms retains the exact exported boundary.
    This parser alone does not prove task/layout identity or a fresh download.
    """
    if report.properties.get("Timezone") != chart_timezone:
        raise DeepExportError("TradingView XLSX gözlenen döneminin saat dilimi eşleşmiyor.")
    start, stop = _utc_bounds(report.backtesting_range, chart_timezone)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    # Integer datetime arithmetic, avoiding float rounding of exact boundaries.
    start_ms = (start - epoch) // timedelta(milliseconds=1)
    stop_ms = (stop - epoch) // timedelta(milliseconds=1)
    return {"from_ms": start_ms, "to_ms": stop_ms - 1,
            "end_exclusive_ms": stop_ms, "timezone": "UTC"}


def observed_report_currency(report: DeepExport) -> str | None:
    """Currency explicitly attached to monetary Performance columns.

    Fixed All/Long/Short monetary and percentage columns were observed in native
    exports. Require their exact seven-column schema and consistent known code;
    unknown layouts remain None. Flattened Properties include Pine titles and are
    not authoritative. Symbol/account names and trade-column units never establish
    the report currency by themselves.
    """
    headers = report.performance_headers
    if (report.performance_headers_provenance != "performance_sheet_row1" or
            not isinstance(headers, tuple) or len(headers) != 7 or
            any(not isinstance(value, str) for value in headers)):
        return None
    if headers[0] != "" or (headers[2], headers[4], headers[6]) != ("All %", "Long %", "Short %"):
        return None
    supported = {"USD", "EUR", "AUD", "GBP", "NZD", "CAD", "CHF", "HKD",
                 "JPY", "NOK", "SEK", "SGD", "TRY", "ZAR"}
    codes = []
    for index, label in ((1, "All"), (3, "Long"), (5, "Short")):
        match = re.fullmatch(label + r" ([A-Z]{3})", headers[index])
        if match is None or match.group(1) not in supported:
            return None
        codes.append(match.group(1))
    if len(set(codes)) != 1:
        return None
    code = codes[0]
    trade_units = {match.group(1) for row in report.trades for key in row
                   if (match := re.fullmatch(r"Net PnL ([A-Z]{3})", key))}
    return code if not trade_units or trade_units == {code} else None


def verify_deep_total_pnl(report: DeepExport, total_pnl: float) -> None:
    """Reconcile observed open-inclusive UI total without relabeling closed net.

    Missing Open PnL is not an observed zero, even with no open trade rows.
    The caller still has to bind UI and export to the same fresh guarded report.
    """
    values = (total_pnl, report.metrics.get("net_profit"), report.open_pnl)
    if any(type(value) not in {int, float} or not math.isfinite(value) for value in values):
        raise DeepExportError("Canlı Deep toplam/açık işlem kârı eksik veya geçersiz.")
    if abs(total_pnl - (report.metrics["net_profit"] + report.open_pnl)) > 0.011:
        raise DeepExportError("Canlı Deep toplam kârı kapanmış ve açık işlemlerle eşleşmiyor.")


def verify_deep_export(report: DeepExport, *, symbol: str, timeframe: str,
                       date_range: dict[str, str], chart_timezone: str,
                       cost_assumptions: dict[str, Any],
                       ui_metrics: dict[str, float | int] | None = None,
                       ui_date_label: str | None = None,
                       ui_update_pending: bool | None = None,
                       symbol_identity: dict[str, Any] | None = None,
                       model_state: Any = None,
                       expected_inputs: dict[str, Any] | None = None,
                       study_id: str | None = None) -> tuple[dict[str, Any], ...]:
    """Verify XLSX identity and trades against the task and live report UI.

    This does not by itself verify that the UI/export came from the same guarded
    target after the latest input change. The download controller must enforce that.
    """
    if not report.sha256 or report.mtime_ns <= 0:
        raise DeepExportError("XLSX dosya kimliği veya indirme zamanı eksik.")
    if (report.properties["Symbol"] != symbol and
            not (":" in symbol and symbol_matches(symbol, report.properties["Symbol"], symbol_identity))):
        raise DeepExportError("TradingView XLSX sembolü görevle eşleşmiyor.")
    expected_tf = _TIMEFRAME_LABELS.get(chart_resolution(timeframe), "")
    if not expected_tf or report.properties["Timeframe"] != expected_tf:
        raise DeepExportError("TradingView XLSX zaman dilimi görevle eşleşmiyor.")
    if model_state is None and report.properties.get("Timezone") != chart_timezone:
        raise DeepExportError("TradingView XLSX saat dilimi chart ile eşleşmiyor.")
    required_costs = ("initial_capital", "position_size", "slippage", "commission_value")
    if not isinstance(cost_assumptions, dict) or any(name not in cost_assumptions for name in required_costs):
        raise DeepExportError("Görev Strategy Properties beklentileri eksik.")
    verify_deep_property_scalars(
        report, initial_capital=cost_assumptions["initial_capital"],
        position_size=cost_assumptions["position_size"],
        slippage_ticks=cost_assumptions["slippage"],
        commission_value=cost_assumptions["commission_value"],
    )
    try:
        requested_from = date.fromisoformat(date_range["from"])
        requested_to = date.fromisoformat(date_range["to"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DeepExportError("Görev tarih aralığı geçersiz.") from exc
    if requested_from > requested_to:
        raise DeepExportError("Görev tarih aralığı ters.")
    if model_state is not None:
        if not study_id or expected_inputs is None:
            raise DeepExportError("Bağımsız Deep strateji/ayar beklentisi eksik.")
        from .deep_model_evidence import verify_model_bound_export
        verify_model_bound_export(report, model_state, study_id=study_id,
            chart_timezone=chart_timezone, expected={'symbol': symbol, 'timeframe': timeframe,
                'date_range': date_range, 'inputs': expected_inputs, 'symbol_identity': symbol_identity})
    else:
        # Legacy explicit-property contracts remain fail-closed. Native captures
        # use the separate manager-bound proof, not guessed/mutated properties.
        observed_from, observed_end_exclusive = _utc_bounds(report.backtesting_range, chart_timezone)
        expected_from = datetime.combine(requested_from, time.min, timezone.utc)
        expected_end_exclusive = datetime.combine(requested_to + timedelta(days=1), time.min, timezone.utc)
        if observed_from != expected_from or observed_end_exclusive != expected_end_exclusive:
            raise DeepExportError("TradingView XLSX tarih aralığı görevle eşleşmiyor.")
    if ui_update_pending is not False:
        raise DeepExportError("Canlı Deep rapor henüz güncel olarak doğrulanmadı.")
    try:
        ui_from, ui_to = [datetime.strptime(part.strip(), "%b %d, %Y").date()
                          for part in (ui_date_label or "").split(" — ")]
    except ValueError as exc:
        raise DeepExportError("Canlı Deep rapor tarih etiketi okunamadı.") from exc
    if (ui_from, ui_to) != (requested_from, requested_to):
        raise DeepExportError("Canlı Deep rapor tarih aralığı görevle eşleşmiyor.")
    if ui_metrics is None:
        raise DeepExportError("Canlı Deep rapor metrikleri okunmadı.")
    tolerances = {"trades": 0, "net_profit": 0.011, "profit_factor": 0.001,
                  "win_rate_pct": 0.011, "max_drawdown_pct": 0.011}
    for name, tolerance in tolerances.items():
        observed, shown = report.metrics.get(name), ui_metrics.get(name)
        if (isinstance(shown, bool) or not isinstance(shown, (float, int))
                or not math.isfinite(shown) or observed is None):
            raise DeepExportError("Canlı Deep rapor metriği eksik: " + name)
        if abs(float(observed) - float(shown)) > tolerance:
            raise DeepExportError("Canlı Deep rapor metriği XLSX ile eşleşmiyor: " + name)
    return normalized_closed_trades(report,
        authenticated_timezone=chart_timezone if model_state is not None else None)
