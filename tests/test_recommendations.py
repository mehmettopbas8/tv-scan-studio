from tv_scan_studio.pine import parse_strategy_inputs
from tv_scan_studio.recommendations import historical_values_by_input, input_dependencies, suggest_input


def test_suggestions_preserve_defaults_and_bounded_range():
    source = '''strategy("Demo")
group_name = "Core"
enabled = input.bool(true, "Enabled", group=group_name)
length = input.int(2, "Length", minval=2, maxval=4, active=enabled, group=group_name)
mode = input.string("A", "Mode", options=["A", "B"])
'''
    enabled, length, mode = parse_strategy_inputs(source)
    assert enabled.default is True and not enabled.manual_definition_required
    assert suggest_input(enabled).values == (False, True)
    assert suggest_input(length).values == (2, 3)
    assert suggest_input(mode).values == ("A", "B")
    assert input_dependencies(source) == {"length": "enabled"}


def test_unknown_default_has_no_fabricated_range():
    item = parse_strategy_inputs('strategy("Demo")\nx = input.int(DEFAULT, "X")')[0]
    assert suggest_input(item).values == ()


def test_typed_pine_input_dependency_is_detected():
    source = ('strategy("Demo")\n'
              'bool enabled = input.bool(true, "Enabled")\n'
              'int length = input.int(3, "Length", active=enabled)')
    assert input_dependencies(source) == {"length": "enabled"}


def test_explicit_pine_tooltip_marks_alert_only_risk_as_scan_exclusion_candidate():
    source = ('strategy("Demo")\n'
              'risk=input.float(1.0,"Risk",tooltip="Backtest boyutunu ETKILEMEZ.")\n'
              'message=str.tostring(risk)')
    item = parse_strategy_inputs(source)[0]
    suggestion = suggest_input(item, source)
    assert suggestion.declared_no_backtest_effect
    assert not suggestion.unused_in_source
    assert "backtest etkisi" in suggestion.note


def test_risk_tooltip_without_explicit_no_effect_claim_is_not_excluded():
    source = ('strategy("Demo")\n'
              'risk=input.float(2.0,"Daily Risk",tooltip="Daily backtest risk budget")\n'
              'qty=100/risk')
    item = parse_strategy_inputs(source)[0]
    assert not suggest_input(item, source).declared_no_backtest_effect


def test_unused_source_detection_is_conservative_about_other_mentions():
    unused_source = 'strategy("Demo")\nlength=input.int(3,"Length")'
    item = parse_strategy_inputs(unused_source)[0]
    assert suggest_input(item, unused_source).unused_in_source
    assert not suggest_input(item, unused_source + "\nplot(length)").unused_in_source
    assert not suggest_input(item, unused_source + "\n// length is documented").unused_in_source


def test_history_uses_only_verified_successful_observations():
    rows = [
        {"verified": True, "classification": "hassas", "metrics": {"profit_factor": 1.8},
         "payload": {"inputs": {"in_0": 7}}},
        {"verified": True, "classification": "dayanıklı", "metrics": {"profit_factor": 1.5},
         "payload": {"inputs": {"in_0": 5}}},
        {"verified": False, "classification": "hassas", "metrics": {"profit_factor": 3},
         "payload": {"inputs": {"in_0": 99}}},
        {"verified": True, "classification": "elenmiş", "metrics": {"profit_factor": 1},
         "payload": {"inputs": {"in_0": 1}}},
    ]
    assert historical_values_by_input(rows) == {"in_0": (7, 5)}
