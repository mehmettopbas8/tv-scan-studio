"""Synthetic adapter contracts; native provenance is a separate live gate."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from tv_scan_studio.tradingview import GncZihinDriver, TradingViewError


def data():
    return {'bound': True, 'strategy_id': 'study', 'symbol': 'BIST_DLY:XU030D1!',
            'timeframe': '15', 'chart_timezone': 'America/New_York',
            'selected_dates': {'from': '2026-09-07', 'to': '2026-09-18'},
            'request_from_ms': 1788739200000, 'request_end_exclusive_ms': 1789776000000,
            'inputs': {'in_1': 9, 'in_2': True}, 'status_type': 2,
            'update_pending': False, 'initial_loading': False,
            'settings': {'dateRange': {'backtest': {'from': 1788762600000, 'to': 1789760700000}}},
            'trades': [{'tradeNumber': 1, 'entry': {'time': 1788853500000, 'type': 'se'},
                        'exit': {'time': 1788876900000, 'type': 'sx'}}],
            'performance': {'all': {'totalTrades': 1, 'netProfit': -10}}, 'currency': 'TRY'}


def driver_for(values):
    driver = GncZihinDriver()
    reads, guards = [], []
    iterator = iter(values)
    def evaluate(target, script):
        reads.append((target, script))
        return deepcopy(next(iterator))
    driver._motor = SimpleNamespace(_eval=evaluate)
    driver.target_guard = guards.append
    return driver, reads, guards


def test_reader_preserves_distinct_selected_request_and_market_periods():
    driver, reads, guards = driver_for([data(), data()])
    state = driver.deep_report_model_state('target', 'study')
    assert state.provenance == 'visible_deep_manager'
    assert state.request_from_ms == 1788739200000
    assert state.settings['dateRange']['backtest']['from'] == 1788762600000
    assert state.settings['dateRange']['backtest']['to'] == 1789760700000
    assert 'end_exclusive_ms' not in state.settings['dateRange']['backtest']
    assert state.selected_dates == {'from': '2026-09-07', 'to': '2026-09-18'}
    assert state.chart_timezone == 'America/New_York'
    assert state.currency == 'TRY'
    assert state.inputs == {'in_1': 9, 'in_2': True}
    assert guards == ['target'] * 4
    assert len(reads) == 2
    script = reads[0][1]
    assert 'reportData(' not in script
    assert '_reportDataDeepBacktesting?._value!==report' in script
    assert "'deep-backtesting'" in script
    assert 'i<30' in script and 'j<15' in script
    assert "inputs[key]=value.v" in script
    assert 'value.text' not in script


@pytest.mark.parametrize('key,value', [
    ('bound', False), ('bound', 1), ('error', 'deep_reference_unknown'),
    ('strategy_id', 'other'), ('status_type', True), ('status_type', 1),
    ('update_pending', True), ('update_pending', 0), ('initial_loading', True),
    ('initial_loading', 0), ('request_from_ms', True), ('request_from_ms', 1788739200000.0),
    ('request_end_exclusive_ms', 1789775999999), ('chart_timezone', None),
    ('chart_timezone', 'Invalid/Zone'), ('symbol', 'XU030D1!'), ('timeframe', 15),
    ('timeframe', '0'), ('inputs', {}), ('inputs', {'text': 'private'}),
    ('inputs', {'in_1': {'v': 9}}), ('inputs', {'in_1': float('nan')}),
    ('inputs', {'in_1': 2**2000}),
    ('selected_dates', {'from': '2026-09-7', 'to': '2026-09-18'}),
    ('selected_dates', {'from': '2026-09-18', 'to': '2026-09-07'}),
    ('selected_dates', {'from': '9999-12-31', 'to': '9999-12-31'}),
    ('settings', {'dateRange': []}), ('settings', {'dateRange': {'backtest': {'from': True, 'to': 1789760700000}}}),
    ('settings', {'dateRange': {'backtest': {'from': 1788739199999, 'to': 1789760700000}}}),
    ('trades', [None]), ('performance', {'all': {'netProfit': float('inf')}}),
    ('currency', 'Default'), ('currency', True), ('currency', 'try'),
])
def test_reader_rejects_unbound_unready_or_unsafe_primitives(key, value):
    observed = data()
    observed[key] = value
    driver, _, _ = driver_for([observed])
    with pytest.raises(TradingViewError):
        driver.deep_report_model_state('target', 'study')


@pytest.mark.parametrize('change', ['currency', 'settings', 'inputs', 'trades'])
def test_reader_requires_stable_independent_model(change):
    second = data()
    if change == 'currency':
        second[change] = 'USD'
    elif change == 'settings':
        second[change]['dateRange']['backtest']['to'] -= 900000
    elif change == 'inputs':
        second[change]['in_1'] = 8
    else:
        second[change][0]['entry']['time'] += 900000
    driver, _, _ = driver_for([data(), second])
    with pytest.raises(TradingViewError, match='okuma sırasında değişti'):
        driver.deep_report_model_state('target', 'study')


def test_reader_does_not_infer_missing_currency():
    observed = data()
    observed['currency'] = None
    driver, _, _ = driver_for([observed, observed])
    assert driver.deep_report_model_state('target', 'study').currency is None


def test_reader_requires_external_target_guard_before_read():
    driver, reads, _ = driver_for([])
    driver.target_guard = None
    with pytest.raises(TradingViewError, match='koruması'):
        driver.deep_report_model_state('target', 'study')
    assert not reads
