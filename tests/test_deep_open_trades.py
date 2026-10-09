from copy import deepcopy
from dataclasses import replace
import pytest
from test_deep_export import tables
from tv_scan_studio.deep_export import DeepExportError, summarize_deep_export, normalized_closed_trades


def open_tables():
    source = tables()
    source['Trades'][0].append('Signal')
    for row in source['Trades'][1:]:
        row.append('Closed')
    # Native export order is exit then entry, and even Open is typed Exit.
    source['Trades'].extend([
        [3, 'Exit long', 46283.14, 4.25, 'Open'],
        [3, 'Entry long', 46283.13, 4.25, 'Long'],
    ])
    source['Trades analysis'].append(['Total open trades', 1])
    source['Performance'].append(['Open PnL', 4.25])
    return source


def test_open_trade_raw_rows_preserved_and_closed_analytics_reconcile_separately():
    source = open_tables()
    original = deepcopy(source)
    report = summarize_deep_export(source)
    assert report.open_trade_count == 1 and report.open_pnl == 4.25
    assert len(report.trades) == 6
    closed = normalized_closed_trades(report)
    assert len(closed) == 2
    assert sum(row['tp']['v'] for row in closed) == pytest.approx(17.91)
    assert source == original and len(report.trades) == 6


def test_native_deep_open_timestamp_is_preserved_without_fabricated_exit():
    source = open_tables()
    source['Trades'][-2][2] = 'Open'
    report = summarize_deep_export(source)
    assert len(normalized_closed_trades(report)) == 2
    assert report.trades[-2]['Date and time'] == 'Open'


@pytest.mark.parametrize('timestamp', ['OPEN','',None,True])
def test_open_position_does_not_allow_other_invalid_exit_timestamps(timestamp):
    source = open_tables()
    source['Trades'][-2][2] = timestamp
    with pytest.raises(DeepExportError):
        normalized_closed_trades(summarize_deep_export(source))


def test_closed_position_cannot_use_open_timestamp():
    source = open_tables()
    source['Trades'][1][2] = 'Open'
    with pytest.raises(DeepExportError):
        normalized_closed_trades(summarize_deep_export(source))


@pytest.mark.parametrize('change', ['missing_count', 'missing_pnl', 'wrong_count', 'wrong_pnl', 'missing_marker', 'bad_count'])
def test_open_rows_cannot_be_silently_dropped_without_report_evidence(change):
    source = open_tables()
    if change == 'missing_count': source['Trades analysis'].pop()
    elif change == 'missing_pnl': source['Performance'].pop()
    elif change == 'wrong_count': source['Trades analysis'][-1][1] = 2
    elif change == 'wrong_pnl': source['Performance'][-1][1] = 0
    elif change == 'missing_marker': source['Trades'][-2][-1] = 'Long'
    elif change == 'bad_count': source['Trades analysis'][-1][1] = True
    with pytest.raises(DeepExportError):
        summarize_deep_export(source)


@pytest.mark.parametrize('change', ['unpaired', 'duplicate_exit', 'wrong_side', 'entry_marker', 'wrong_pnl_metadata'])
def test_open_pairs_still_require_identity_direction_and_independent_totals(change):
    source = open_tables()
    if change == 'unpaired': source['Trades'].pop()
    elif change == 'duplicate_exit': source['Trades'].append(source['Trades'][-2].copy())
    elif change == 'wrong_side': source['Trades'][-1][1] = 'Entry short'
    elif change == 'entry_marker': source['Trades'][-1][-1] = 'Open'
    if change == 'duplicate_exit':
        with pytest.raises(DeepExportError): summarize_deep_export(source)
        return
    report = summarize_deep_export(source)
    if change == 'wrong_pnl_metadata': report = replace(report, open_pnl=0)
    with pytest.raises(DeepExportError): normalized_closed_trades(report)


def test_unknown_signal_is_not_treated_as_open():
    source = open_tables()
    source['Trades'][-2][-1] = 'OPEN'
    with pytest.raises(DeepExportError): summarize_deep_export(source)


def test_closed_only_report_cannot_hide_an_open_trade_count():
    source = tables()
    source['Trades analysis'].append(['Total open trades', 1])
    source['Performance'].append(['Open PnL', 0])
    with pytest.raises(DeepExportError): summarize_deep_export(source)


def test_zero_open_rows_and_zero_open_pnl_are_valid_and_explicit():
    source = tables()
    source['Trades analysis'].append(['Total open trades', 0])
    source['Performance'].append(['Open PnL', 0])
    report = summarize_deep_export(source)
    assert report.open_trade_count == 0 and report.open_pnl == 0
    assert len(normalized_closed_trades(report)) == 2


def test_zero_open_count_does_not_hide_nonzero_open_pnl():
    source = tables()
    source['Trades analysis'].append(['Total open trades', 0])
    source['Performance'].append(['Open PnL', 5])
    with pytest.raises(DeepExportError): summarize_deep_export(source)
