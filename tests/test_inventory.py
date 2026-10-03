from tv_scan_studio.tradingview import (GncZihinDriver, confirmed_strategy_identity_matches,
                                        strategy_structure_matches)


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
