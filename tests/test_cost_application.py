import pytest

from tv_scan_studio.cost_application import strategy_property_values
from tv_scan_studio.tradingview import GncZihinDriver, TradingViewError


def definitions():
    names = [('Initial Capital', 'float'), ('Default entry/order Qty Value', 'float'),
             ('Commission Value', 'float'), ('Backtesting slippage for market orders', 'integer'),
             ('Commission Type', 'text'), ('Default entry/order Qty Type', 'text')]
    return [dict(id=f'in_{100+i}', name=name, type=kind, groupId='strategy_props',
                 options=['percent', 'cash_per_contract', 'cash_per_order', 'fixed'])
            for i, (name, kind) in enumerate(names)]


def assumptions():
    return dict(initial_capital=100000, position_size=1, commission_value=.04,
                commission_type='percent', slippage=10)


def test_metadata_resolution_is_not_a_fixed_offset():
    values = strategy_property_values(definitions(), assumptions())
    assert values == [dict(id=f'in_{100+i}', value=v)
                      for i, v in enumerate([100000, 1, .04, 10, 'percent', 'fixed'])]


@pytest.mark.parametrize('key,value', [('slippage', 1.5), ('slippage', True),
    ('commission_value', -1), ('initial_capital', 0), ('position_size', float('nan')),
    ('commission_type', 'unknown')])
def test_invalid_costs_fail_before_mutation(key, value):
    costs = assumptions()
    costs[key] = value
    with pytest.raises(ValueError):
        strategy_property_values(definitions(), costs)


@pytest.mark.parametrize('case', ['missing', 'duplicate', 'pine', 'unsupported'])
def test_unrecognized_schema_fails_closed(case):
    schema = definitions()
    if case == 'missing': schema.pop()
    if case == 'duplicate': schema.append(schema[0])
    if case == 'pine': schema[0]['groupId'] = 'pine_inputs'
    if case == 'unsupported': schema[4]['options'] = []
    with pytest.raises(ValueError):
        strategy_property_values(schema, assumptions())


def test_driver_requires_guard_before_reading_or_writing():
    driver = GncZihinDriver.__new__(GncZihinDriver)
    driver.target_guard = None
    with pytest.raises(TradingViewError):
        driver.configure_strategy_properties('worker', 'study', assumptions())


@pytest.mark.parametrize('matches', [True, False])
def test_driver_checks_property_readback(matches):
    driver = GncZihinDriver.__new__(GncZihinDriver)
    calls = []
    driver.target_guard = lambda target: calls.append(('guard', target))
    observed = strategy_property_values(definitions(), assumptions()) if matches else []
    replies = iter([definitions(), True, observed])
    driver._eval = lambda target, study, script: calls.append(('eval', target, study)) or next(replies)
    if matches:
        driver.configure_strategy_properties('worker', 'study', assumptions())
    else:
        with pytest.raises(TradingViewError):
            driver.configure_strategy_properties('worker', 'study', assumptions())
    assert [c[0] for c in calls] == ['guard', 'eval'] * 3
