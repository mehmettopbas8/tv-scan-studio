from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tv_scan_studio.deep_export import DeepExport, DeepExportError, verify_deep_export
from tv_scan_studio.deep_model_evidence import verify_model_bound_export
from tv_scan_studio.tradingview import DeepReportModelState


def fixture():
    zone = ZoneInfo('America/New_York')
    def point(text, kind, signal):
        stamp = datetime.fromisoformat(text)
        return {'time': round(stamp.replace(tzinfo=zone).timestamp() * 1000),
                'type': kind, 'id': signal}, (stamp - datetime(1899, 12, 30)).total_seconds() / 86400
    first, _ = point('2026-09-07T02:30', 'le', '')
    last, _ = point('2026-09-18T15:45', 'sx', '')
    entry, entry_serial = point('2026-09-08T03:45', 'le', 'Long')
    exit_, exit_serial = point('2026-09-08T04:00', 'lx', 'Exit')
    open_entry, open_serial = point('2026-09-18T15:30', 'se', 'Short')
    trades = ({'tradeNumber': 1, 'entry': entry, 'exit': exit_, 'profit': {'value': 10}},
              {'tradeNumber': 2, 'entry': open_entry, 'exit': last,
               'profit': {'value': -3}, 'isOpen': True})
    def row(number, kind, stamp, signal, pnl):
        return {'Trade number': number, 'Type': kind, 'Date and time': stamp,
                'Signal': signal, 'Net PnL TRY': pnl}
    report = DeepExport({'trades': 1, 'net_profit': 10}, {}, (
        row(1, 'Entry long', entry_serial, 'Long', 10),
        row(1, 'Exit long', exit_serial, 'Exit', 10),
        row(2, 'Entry short', open_serial, 'Short', -3),
        row(2, 'Exit short', 'Open', 'Open', -3)),
        'Sep 7, 2026, 02:30 — Sep 18, 2026, 15:45', 'sha', 1,
        ('', 'All TRY', 'All %', 'Long TRY', 'Long %', 'Short TRY', 'Short %'),
        'performance_sheet_row1', 'Net PnL TRY', 1, -3)
    dates = {'from': '2026-09-07', 'to': '2026-09-18'}
    model = DeepReportModelState(1788739200000, 1789776000000, dates,
        'America/New_York', 'study', {'in_1': 9}, 'BIST:XU030D1!', '15', 2, False, False,
        {'dateRange': {'backtest': {'from': first['time'], 'to': last['time']}}}, trades,
        {'all': {'netProfit': 10, 'totalTrades': 1, 'totalOpenTrades': 1}, 'openPL': -3}, 'TRY')
    expected = {'date_range': dates, 'symbol': 'BIST:XU030D1!', 'timeframe': '15', 'inputs': {'in_1': 9}}
    return report, model, expected


def verify(report, model, expected):
    return verify_model_bound_export(report, model, expected=expected,
                                    study_id='study', chart_timezone='America/New_York')


def test_complete_native_shaped_correspondence_without_timezone_property():
    report, model, expected = fixture()
    before = deepcopy(report)
    period = verify(report, model, expected)
    assert period['to_ms'] == model.settings['dateRange']['backtest']['to']
    assert period['provenance'] == 'deep_model_and_export_rows'
    assert 'end_exclusive_ms' not in period
    assert 'Timezone' not in report.properties and report == before
    assert report.trades[-1]['Date and time'] == 'Open'


def test_extreme_end_date_rejected_without_overflow():
    report, model, expected = fixture()
    expected['date_range'] = {'from': '2026-09-07', 'to': '9999-12-31'}
    with pytest.raises(DeepExportError):
        verify(report, replace(model, selected_dates=expected['date_range']), expected)


def test_oversized_numeric_metric_rejected_without_overflow():
    report, model, expected = fixture()
    with pytest.raises(DeepExportError):
        verify(replace(report, metrics={'trades': 1, 'net_profit': 10 ** 1000}), model, expected)


def test_export_verifier_uses_model_without_manufacturing_timezone_or_midnights():
    report, model, expected = fixture()
    metrics = {'trades': 1, 'net_profit': 10, 'profit_factor': 2,
               'win_rate_pct': 100, 'max_drawdown_pct': 1}
    report = replace(report, metrics=metrics, properties={
        'Symbol': 'BIST:XU030D1!', 'Timeframe': '15 minutes',
        'Initial capital': '100000', 'Default order size': '1 contracts',
        'Commission': '0', 'Slippage': '0 ticks'})
    def run(**changes):
        args = dict(symbol=expected['symbol'], timeframe=expected['timeframe'],
            date_range=expected['date_range'], chart_timezone='America/New_York',
            cost_assumptions={'initial_capital': 100000, 'position_size': 1,
                              'commission_value': 0, 'slippage': 0},
            ui_metrics=metrics, ui_date_label='Sep 7, 2026 — Sep 18, 2026',
            ui_update_pending=False, model_state=model, expected_inputs=expected['inputs'], study_id='study')
        args.update(changes)
        return verify_deep_export(report, **args)
    closed = run()
    assert len(closed) == 1 and closed[0]['tp']['v'] == 10
    assert 'Timezone' not in report.properties
    for changes in ({'model_state': None}, {'study_id': None}, {'expected_inputs': None},
                    {'ui_update_pending': True}, {'ui_date_label': 'Sep 8, 2026 — Sep 18, 2026'},
                    {'expected_inputs': {'in_1': 8}}):
        with pytest.raises(DeepExportError):
            run(**changes)


@pytest.mark.parametrize('field,value', [('strategy_id', 'other'), ('provenance', 'chart'),
    ('chart_timezone', 'Etc/UTC'), ('status_type', 1), ('update_pending', True),
    ('initial_loading', True), ('inputs', {'in_1': 8}), ('inputs', {'in_1': True}),
    ('symbol', 'OANDA:EURUSD'), ('timeframe', '1'), ('request_from_ms', True),
    ('request_end_exclusive_ms', 1789775999999), ('currency', 'USD')])
def test_wrong_independent_context_rejected(field, value):
    report, model, expected = fixture()
    with pytest.raises(DeepExportError):
        verify(report, replace(model, **{field: value}), expected)


@pytest.mark.parametrize('change', ['time', 'signal', 'direction', 'pnl', 'duplicate', 'open', 'open_time', 'period'])
def test_forged_or_unpaired_export_rejected(change):
    report, model, expected = fixture()
    rows = deepcopy(list(report.trades))
    if change == 'time': rows[0]['Date and time'] += 1 / 86400
    elif change == 'signal': rows[0]['Signal'] = 'Other'
    elif change == 'direction': rows[0]['Type'] = 'Entry short'
    elif change == 'pnl': rows[0]['Net PnL TRY'] = 9
    elif change == 'duplicate': rows[1] = deepcopy(rows[0])
    elif change == 'open': rows[-1]['Signal'] = 'Exit'
    elif change == 'open_time': rows[-1]['Date and time'] = None
    else: report = replace(report, backtesting_range='Sep 7, 2026, 02:30 — Sep 18, 2026, 15:44')
    with pytest.raises(DeepExportError):
        verify(replace(report, trades=tuple(rows)), model, expected)


@pytest.mark.parametrize('flag', ['false', None, 0, 1])
def test_nonboolean_native_open_marker_rejected(flag):
    report, model, expected = fixture()
    trades = deepcopy(list(model.trades))
    trades[0]['isOpen'] = flag
    with pytest.raises(DeepExportError):
        verify(report, replace(model, trades=tuple(trades)), expected)
