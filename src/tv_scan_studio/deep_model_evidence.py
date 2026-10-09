"""Authenticate native export timing against the independently bound Deep model.

Selected civil dates, requested UTC window and actual data endpoints are distinct.
This never injects a Timezone property into the downloaded workbook.
"""
from datetime import date, datetime, time, timedelta, timezone
import math
from zoneinfo import ZoneInfo

from .deep_export import DeepExportError, observed_report_currency
from .tradingview import chart_resolution, symbol_matches


def _fail(message):
    raise DeepExportError(message)


def _number(value):
    if type(value) not in {int, float}:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _epoch(value):
    return type(value) is int and 0 < value < 253402300800000


def _local_epoch(stamp, zone):
    aware = stamp.replace(tzinfo=zone)
    if (aware.utcoffset() != stamp.replace(tzinfo=zone, fold=1).utcoffset()
            or aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != stamp):
        _fail("Deep dışa aktarım zamanı belirsiz veya geçersiz.")
    return round(aware.timestamp() * 1000)


def verify_model_bound_export(report, model, *, expected, study_id, chart_timezone):
    """Return observed inclusive data endpoints after complete native row proof.

    Capture must separately enforce before/after model stability and source guard.
    A forged dataclass or checksum is not independent native acceptance evidence.
    """
    from .tradingview import DeepReportModelState
    if (not isinstance(model, DeepReportModelState) or model.provenance != "visible_deep_manager"
            or model.strategy_id != study_id or model.chart_timezone != chart_timezone
            or model.status_type != 2 or model.update_pending is not False
            or model.initial_loading is not False):
        _fail("Bağımsız Deep rapor kimliği veya hazır durumu doğrulanamadı.")
    dates = expected.get("date_range", {})
    try:
        start, end = date.fromisoformat(dates['from']), date.fromisoformat(dates['to'])
        zone = ZoneInfo(chart_timezone)
    except (KeyError, TypeError, ValueError) as exc:
        raise DeepExportError("Deep görev tarih/saat dilimi geçersiz.") from exc
    if start > end or end == date.max or model.selected_dates != dates:
        _fail("Bağımsız Deep seçili tarihleri görevle eşleşmiyor.")
    lower = round(datetime.combine(start, time.min, timezone.utc).timestamp() * 1000)
    upper = round(datetime.combine(end + timedelta(days=1), time.min, timezone.utc).timestamp() * 1000)
    if (not _epoch(model.request_from_ms) or not _epoch(model.request_end_exclusive_ms)
            or (model.request_from_ms, model.request_end_exclusive_ms) != (lower, upper)):
        _fail("Deep motorunun istediği UTC test penceresi görevle eşleşmiyor.")
    if (model.timeframe != chart_resolution(expected['timeframe'])
            or not symbol_matches(expected['symbol'], model.symbol, expected.get('symbol_identity'))):
        _fail("Bağımsız Deep sembol/zaman dilimi görevle eşleşmiyor.")
    for key, wanted in expected.get('inputs', {}).items():
        actual = model.inputs.get(key)
        if key not in model.inputs or (type(actual) is not type(wanted) and
                (isinstance(actual, bool) or isinstance(wanted, bool))) or actual != wanted:
            _fail("Bağımsız Deep ayarı görevle eşleşmiyor: " + key)
    period = (model.settings.get('dateRange') or {}).get('backtest') or {}
    first, last = period.get('from'), period.get('to')
    if not _epoch(first) or not _epoch(last) or not lower <= first <= last < upper:
        _fail("Gözlenen Deep veri dönemi seçili test penceresinin dışında.")
    try:
        labels = [datetime.strptime(part, '%b %d, %Y, %H:%M')
                  for part in report.backtesting_range.split(' — ')]
    except (ValueError, TypeError) as exc:
        raise DeepExportError("Deep dışa aktarım veri dönemi okunamadı.") from exc
    if len(labels) != 2 or tuple(_local_epoch(stamp, zone) for stamp in labels) != (first, last):
        _fail("Deep XLSX veri dönemi bağımsız rapor zamanlarıyla eşleşmiyor.")
    if observed_report_currency(report) != model.currency or model.currency is None:
        _fail("Deep XLSX para birimi bağımsız raporla eşleşmiyor.")
    all_ = model.performance.get('all') or {}
    for observed, native in ((report.metrics.get('net_profit'), all_.get('netProfit')),
                             (report.metrics.get('trades'), all_.get('totalTrades')),
                             (report.open_trade_count, all_.get('totalOpenTrades')),
                             (report.open_pnl, model.performance.get('openPL'))):
        if not _number(observed) or not _number(native) or abs(observed - native) > .011:
            _fail("Deep XLSX işlem/kâr toplamı bağımsız raporla eşleşmiyor.")
    native_trades = {}
    for trade in model.trades:
        number = trade.get('tradeNumber') if isinstance(trade, dict) else None
        # The independently observed native schema omits isOpen for closed
        # trades and emits true for open trades. Preserve that raw distinction.
        if (type(number) is not int or number < 1 or number in native_trades
                or ('isOpen' in trade and type(trade['isOpen']) is not bool)):
            _fail("Bağımsız Deep işlem kimliği belirsiz.")
        native_trades[number] = trade
    if len(report.trades) != 2 * len(native_trades):
        _fail("Deep XLSX satır sayısı bağımsız işlem listesiyle eşleşmiyor.")
    seen = set()
    open_count = 0
    for row in report.trades:
        number = row.get('Trade number')
        kind, side = str(row.get('Type', '')).partition(' ')[::2]
        if type(number) is not int or number not in native_trades or kind not in {'Entry', 'Exit'} or side not in {'long', 'short'}:
            _fail("Deep XLSX işlem eşlemesi geçersiz.")
        key = (number, kind)
        if key in seen:
            _fail("Deep XLSX işlem satırı yineleniyor.")
        seen.add(key)
        trade = native_trades[number]
        point = trade.get(kind.lower()) or {}
        expected_type = ('l' if side == 'long' else 's') + ('e' if kind == 'Entry' else 'x')
        pnl = (trade.get('profit') or {}).get('value')
        shown_pnl = row.get(report.trade_pnl_header)
        if (point.get('type') != expected_type or not _epoch(point.get('time'))
                or not _number(pnl) or not _number(shown_pnl) or abs(pnl - shown_pnl) > .011):
            _fail("Deep XLSX işlem yönü/kârı bağımsız raporla eşleşmiyor.")
        if kind == 'Exit' and trade.get('isOpen', False):
            open_count += 1
            if row.get('Signal') != 'Open' or point.get('id') != '':
                _fail("Deep açık işlem kimliği eşleşmiyor.")
            if row.get('Date and time') == 'Open':
                continue
        elif row.get('Signal') != point.get('id') or row.get('Signal') == 'Open':
            _fail("Deep XLSX işlem sinyali bağımsız raporla eşleşmiyor.")
        serial = row.get('Date and time')
        if not _number(serial) or not 1 <= serial <= 2958465:
            _fail("Deep XLSX sayısal işlem zamanı eksik.")
        stamp = datetime(1899, 12, 30) + timedelta(days=serial)
        if abs(_local_epoch(stamp, zone) - point['time']) > 1:
            _fail("Deep XLSX işlem zamanı bağımsız raporla eşleşmiyor.")
    if open_count != report.open_trade_count:
        _fail("Deep açık işlem sayısı bağımsız raporla eşleşmiyor.")
    return {'from_ms': first, 'to_ms': last, 'timezone': 'UTC',
            'endpoint_semantics': 'observed_data_timestamps',
            'provenance': 'deep_model_and_export_rows',
            'export_timezone': chart_timezone}
