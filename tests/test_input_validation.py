import pytest
from tv_scan_studio.pine import PineInput, validate_input_value
from tv_scan_studio.validation import followup_payloads


def test_numeric_boundaries_types_and_step():
    spec = PineInput("ema", "int", 8, "Fast EMA", minimum=7, maximum=9, step=1)
    for value in (7, 8, 9):
        validate_input_value(spec, value)
    for value in (6, 10, True, 8.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            validate_input_value(spec, value)
    decimal = PineInput("risk", "float", .3, "Risk", minimum=.1, maximum=.5, step=.1)
    validate_input_value(decimal, .3)
    with pytest.raises(ValueError, match="adım"):
        validate_input_value(decimal, .25)


def test_neighbors_respect_source_bounds_and_step():
    spec = PineInput("ema", "int", 8, "Fast EMA", minimum=7, maximum=9, step=1)
    payload = {"inputs": {"in_0": 7}}
    rows = list(followup_payloads(payload, "", input_specs={"in_0": spec}))
    assert [(stage, row["inputs"]["in_0"]) for stage, row in rows] == [("neighbor", 8)]


def test_options_and_boolean_values_are_not_coerced():
    with pytest.raises(ValueError):
        validate_input_value(PineInput("enabled", "bool", True, "Enabled"), 1)
    with pytest.raises(ValueError):
        validate_input_value(PineInput("mode", "string", "A", "Mode", options=("A", "B")), "C")
