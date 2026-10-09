from types import SimpleNamespace

import pytest

from tv_scan_studio.tradingview import GncZihinDriver, TradingViewError, pine_source_hash


def driver_for(rows, saved):
    driver = GncZihinDriver()
    calls = []
    def evaluate(target, expression, **kwargs):
        calls.append(expression)
        if 'listSavedScripts' in expression:
            return rows
        assert 'getSource' in expression
        return saved
    driver._motor = SimpleNamespace(_eval=evaluate)
    return driver, calls


def candidate(source='source'):
    return {'scriptName': 'TV Scan Source ' + pine_source_hash(source)[:20],
            'scriptIdPart': 'USER;private', 'version': '1.0'}


def test_reconciliation_requires_full_source_and_version():
    driver, calls = driver_for([candidate()], {'source': 'source', 'version': '1.0'})
    assert driver._find_saved_private_source('owned', pine_source_hash('source')) == ('USER;private', '1.0')
    assert len(calls) == 2


@pytest.mark.parametrize('rows,saved', [
    (None, None), ({}, None), ([candidate(), candidate()], None),
    ([candidate()], {'source': 'different', 'version': '1.0'}),
    ([candidate()], {'source': 'source', 'version': '2.0'}),
    ([candidate()], None),
])
def test_unverified_reconciliation_never_writes(rows, saved):
    driver, calls = driver_for(rows, saved)
    with pytest.raises(TradingViewError):
        driver._find_saved_private_source('owned', pine_source_hash('source'))
    assert all('saveNewScript' not in call and 'createStudy' not in call for call in calls)


@pytest.mark.parametrize('pending', [True, False])
def test_existing_exact_private_script_is_reused_without_save(pending):
    driver = GncZihinDriver()
    source = 'source'
    study = {'id': 'study', 'pine_id': 'USER;private', 'pine_version': '1.0'}
    inventories = iter([[], [], [study]])
    driver.strategies = lambda target: next(inventories)
    driver.saved_strategy_source_hash = lambda *args: pine_source_hash(source)
    calls, persisted = [], []
    def evaluate(target, expression, **kwargs):
        calls.append(expression)
        assert 'saveNewScript' not in expression
        if 'listSavedScripts' in expression:
            return [candidate()]
        if 'getSource' in expression:
            return source if 'async' in expression else {'source': source, 'version': '1.0'}
        assert persisted[-1]['pine_id'] == 'USER;private'
        assert 'createStudy' in expression
        return 'study'
    driver._motor = SimpleNamespace(_eval=evaluate)
    journal = {'source_hash': pine_source_hash(source), 'save_requested': pending}
    assert driver.load_private_source('owned', source, journal=journal,
        persist=persisted.append, guard=lambda target: None) == study
    assert journal['study_id'] == 'study'


def test_eval_failure_is_not_misreported_as_a_closed_connection():
    from tv_scan_studio.app import StudioWindow
    message = StudioWindow._friendly_error(RuntimeError('CDP eval hatası: duplicate script'))
    assert 'kapatın' not in message
    assert 'Teknik açıklamayı' in message
