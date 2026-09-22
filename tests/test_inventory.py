from tv_scan_studio.tradingview import GncZihinDriver, strategy_structure_matches


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


def test_strategy_structure_requires_title_and_exact_input_ids():
    strategy = {"name": "My Strategy", "input_ids": ["in_0", "in_1"]}
    assert strategy_structure_matches(strategy, "My Strategy", 2)
    assert not strategy_structure_matches(strategy, "Other", 2)
    assert not strategy_structure_matches(strategy, "My Strategy", 3)
