from tv_scan_studio.tradingview import (GncZihinDriver, confirmed_strategy_identity_matches,
                                        strategy_structure_matches)
import pytest
from tv_scan_studio.tradingview import TradingViewError, SourceReadUnavailable, pine_source_hash


def test_source_panel_is_opened_and_restored_only_when_needed(monkeypatch):
    driver = GncZihinDriver()
    reads = iter([None, "hash"])
    def read(*_args):
        value = next(reads)
        if value is None:
            raise SourceReadUnavailable("closed")
        return value
    actions, guards = [], []
    monkeypatch.setattr(driver, "strategy_source_hash", read)
    monkeypatch.setattr(driver._motor, "_eval", lambda _target, expression: actions.append(expression) or True)
    assert driver.ensure_strategy_source_hash("worker", "sid", guard=guards.append) == "hash"
    assert len(actions) == 3
    assert 'aria-label="Pine"' in actions[0]
    assert 'aria-label="Close"' in actions[1]
    assert guards == ["worker"] * 5


def test_source_panel_is_not_changed_when_source_already_readable(monkeypatch):
    driver = GncZihinDriver()
    monkeypatch.setattr(driver, "strategy_source_hash", lambda *_args: "hash")
    monkeypatch.setattr(driver._motor, "_eval", lambda *_args: pytest.fail("No panel mutation permitted"))
    assert driver.ensure_strategy_source_hash("worker", "sid", guard=lambda _target: None) == "hash"


def test_source_panel_preserves_existing_editor_or_modal(monkeypatch):
    driver = GncZihinDriver()
    monkeypatch.setattr(driver, "strategy_source_hash", lambda *_args: (_ for _ in ()).throw(SourceReadUnavailable("unavailable")))
    actions = []
    monkeypatch.setattr(driver._motor, "_eval", lambda _target, expression: actions.append(expression) or False)
    with pytest.raises(SourceReadUnavailable, match="korunuyor"):
        driver.ensure_strategy_source_hash("worker", "sid", guard=lambda _target: None)
    assert len(actions) == 1


def test_source_panel_restore_failure_is_not_manual_confirmation_fallback(monkeypatch):
    driver = GncZihinDriver()
    reads = iter([None, "hash"])
    def read(*_args):
        result = next(reads)
        if result is None:
            raise SourceReadUnavailable("closed")
        return result
    monkeypatch.setattr(driver, "strategy_source_hash", read)
    actions = iter([True, False])
    monkeypatch.setattr(driver._motor, "_eval", lambda *_args: next(actions))
    with pytest.raises(TradingViewError, match="kapatılamadı") as error:
        driver.ensure_strategy_source_hash("worker", "sid", guard=lambda _target: None)
    assert not isinstance(error.value, SourceReadUnavailable)


def test_source_panel_guard_rejection_prevents_open(monkeypatch):
    driver = GncZihinDriver()
    monkeypatch.setattr(driver._motor, "_eval", lambda *_args: pytest.fail("Wrong worker must not be touched"))
    def reject(_target):
        raise ValueError("layout changed")
    with pytest.raises(ValueError, match="layout changed"):
        driver.ensure_strategy_source_hash("worker", "sid", guard=reject)


def test_source_hash_normalizes_only_line_endings():
    assert pine_source_hash('strategy("Demo")\r\n') == pine_source_hash('strategy("Demo")\n')
    assert pine_source_hash('strategy("Demo")\n') != pine_source_hash('strategy("Other")\n')
    assert pine_source_hash('strategy("Demo")\n') != pine_source_hash('strategy("Demo")\n\n')


def test_source_hash_reads_complete_bound_saved_source(monkeypatch):
    driver = GncZihinDriver()
    monkeypatch.setattr(driver._motor, "_eval", lambda *_args: {
        "source": 'strategy("Demo")\r\n', "pine_id": "USER;one", "version": "1.0"})
    assert driver.strategy_source_hash("target", "study") == pine_source_hash('strategy("Demo")\n')


@pytest.mark.parametrize("data", [None, {}, {"source": ""},
    {"source": 'strategy("Demo")', "pine_id": "USER;one"}, {"source": 123}])
def test_source_hash_rejects_unavailable_or_partial_evidence(monkeypatch, data):
    driver = GncZihinDriver()
    monkeypatch.setattr(driver._motor, "_eval", lambda *_args: data)
    with pytest.raises(TradingViewError, match="doğrulanmadı"):
        driver.strategy_source_hash("target", "study")


def test_inventory_keeps_failed_targets(monkeypatch):
    driver = object.__new__(GncZihinDriver)
    monkeypatch.setattr(driver, "targets", lambda: ["ready", "stale"])
    def strategies(target):
        if target == "stale": raise TimeoutError("timeout")
        return [{"id": "sid", "status": {"type": 2}}]
    monkeypatch.setattr(driver, "strategies", strategies)
    rows = driver.inventory()
    assert rows[0]["strategies"][0]["id"] == "sid"
    assert rows[1]["strategies"] == []
    assert "timeout" in rows[1]["error"]


def test_snapshot_excludes_internal_pine_payload(monkeypatch):
    driver = object.__new__(GncZihinDriver)
    monkeypatch.setattr(driver, "_eval", lambda *_args: {
        "status": {"type": 2}, "symbol": "OANDA:EURUSD", "tf": "15",
        "inputs": [
            {"id": "text", "value": "encrypted-source"},
            {"id": "pineId", "value": "USER;secret"},
            {"id": "in_0", "value": 20},
            {"id": "in_12", "value": True},
            {"id": "__profile", "value": False},
        ],
        "metrics": {"trades": 1}, "period": {},
    })
    snapshot = driver.snapshot("target", "study")
    assert snapshot.inputs == {"in_0": 20, "in_12": True}


def test_strategy_structure_requires_title_and_pine_input_ids():
    strategy = {"name": "My Strategy", "input_ids": ["in_0", "in_1"]}
    assert strategy_structure_matches(strategy, "My Strategy", 2)
    assert not strategy_structure_matches(strategy, "Other", 2)
    assert not strategy_structure_matches(strategy, "My Strategy", 3)
    assert strategy_structure_matches(
        {"name": "My Strategy", "input_ids": ["in_0", "in_1", "in_154", "in_155"]},
        "My Strategy", 2,
    )


def test_confirmed_identity_rejects_changed_or_missing_input_inventory():
    strategy = {"name": "My Strategy", "pine_id": "USER;one",
                "input_ids": ["in_0", "in_1", "in_154"]}
    identity = {"pine_id": "USER;one", "pine_hash": "hash", "user_source_confirmed": True,
                "input_ids": ["in_0", "in_1", "in_154"]}
    check = lambda item, saved: confirmed_strategy_identity_matches(
        item, saved, pine_hash="hash", expected_title="My Strategy", expected_input_count=2,
    )
    assert check(strategy, identity)
    assert not check({**strategy, "input_ids": ["in_0", "in_1", "in_155"]}, identity)
    assert not check(strategy, {**identity, "input_ids": []})
    assert not check({**strategy, "input_ids": ["in_0", "in_1", "in_1"]}, identity)


def test_confirmed_identity_accepts_legacy_strategy_property_suffix_only():
    strategy = {"name": "My Strategy", "pine_id": "USER;one",
                "input_ids": ["in_0", "in_1"],
                "property_input_ids": ["in_2", "in_3"]}
    identity = {"pine_id": "USER;one", "pine_hash": "hash",
                "user_source_confirmed": True,
                "input_ids": ["in_0", "in_1", "in_2", "in_3"]}
    check = lambda item, saved: confirmed_strategy_identity_matches(
        item, saved, pine_hash="hash", expected_title="My Strategy", expected_input_count=2,
    )
    assert check(strategy, identity)
    assert not check({**strategy, "property_input_ids": []}, identity)
    assert not check(strategy, {**identity, "input_ids": ["in_0", "in_1", "in_2", "in_4"]})


def test_confirmed_identity_rejects_changed_build_with_same_title_and_inputs():
    strategy = {"name": "Demo", "pine_id": "USER;one", "input_ids": ["in_0"],
                "pine_digest": "confirmed-build", "pine_version": "1.0"}
    identity = {**strategy, "pine_hash": "local-source", "user_source_confirmed": True}
    def check(observed):
        return confirmed_strategy_identity_matches(observed, identity,
            pine_hash="local-source", expected_title="Demo", expected_input_count=1)
    assert check(strategy)
    assert not check({**strategy, "pine_digest": "another-build"})
    assert not check({**strategy, "pine_digest": None})
    assert not check({**strategy, "pine_version": "2.0"})


def test_automatic_source_evidence_requires_hash_and_bound_build():
    strategy = {"name":"Demo", "pine_id":"USER;one", "input_ids":["in_0"],
                "pine_digest":"build", "pine_version":"1.0"}
    identity = {**strategy, "pine_hash":"project", "user_source_confirmed":True,
                "source_verification":"editor_saved_source_sha256", "source_sha256":pine_source_hash('strategy("Demo")')}
    def check(saved, source='strategy("Demo")'):
        return confirmed_strategy_identity_matches(strategy,saved,pine_hash="project",
            expected_title="Demo",expected_input_count=1,expected_source=source)
    assert check(identity)
    for key in ("source_sha256","pine_digest","pine_version"):
        assert not check({**identity,key:None})
    assert not check({**identity,"source_sha256":"partial"})
    assert not check({**identity,"source_sha256":"a"*64})
    assert not check(identity, 'strategy("Different")')
    assert not check(identity, None)
