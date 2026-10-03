import pytest

from tv_scan_studio.pine import parse_strategy_inputs, strategy_title


SOURCE = '''
//@version=6
strategy("Example", overlay=true)
use_filter = input.bool(true, "Use Filter")
length = input.int(20, "Length", minval=1)
ratio = input.float(1.5, "RR")
session = input.session("0930-1600", "Session")
'''


def test_parses_supported_inputs():
    inputs = parse_strategy_inputs(SOURCE)
    assert [(item.variable, item.kind, item.default) for item in inputs] == [
        ("use_filter", "bool", True),
        ("length", "int", 20),
        ("ratio", "float", 1.5),
        ("session", "session", "0930-1600"),
    ]


def test_parses_typed_pine_declarations_in_10am_style():
    source = '''
strategy("ICT 10AM First FVG Daily Strategy")
GROUP_SESSION = "Session"
string timezoneInput = input.string("America/New_York", "Timezone", group=GROUP_SESSION)
int startHour = input.int(10, "Setup start hour", minval=0, maxval=23, group=GROUP_SESSION)
bool closeAtEnd = input.bool(true, "Close open position", group=GROUP_SESSION)
float orderQty = input.float(1.0, "Contracts", minval=0.001, step=1.0)
'''
    inputs = parse_strategy_inputs(source)
    assert [(item.variable, item.kind, item.default) for item in inputs] == [
        ("timezoneInput", "string", "America/New_York"),
        ("startHour", "int", 10),
        ("closeAtEnd", "bool", True),
        ("orderQty", "float", 1.0),
    ]
    assert inputs[0].group == "Session"
    assert not any(item.manual_definition_required for item in inputs)


def test_rejects_indicator():
    with pytest.raises(ValueError, match="strategy"):
        parse_strategy_inputs('indicator("Example")\nlength=input.int(20)')


def test_extracts_strategy_title():
    assert strategy_title('strategy("My Strategy", overlay=true)') == "My Strategy"
    assert strategy_title('strategy(title="Named", overlay=false)') == "Named"


def test_parses_multiline_named_arguments_and_metadata():
    source = '''
strategy("Metadata")
length = input.int(
    defval=20, title="Length, bars", minval=1, maxval=100, step=5,
    options=[10, 20, 30], group="Entry", tooltip="Lookback"
)
'''
    item = parse_strategy_inputs(source)[0]
    assert (item.default, item.title) == (20, "Length, bars")
    assert item.options == (10, 20, 30)
    assert (item.minimum, item.maximum, item.step) == (1, 100, 5)
    assert (item.group, item.tooltip) == ("Entry", "Lookback")
    assert item.manual_definition_required is False


def test_marks_dynamic_values_for_manual_definition():
    item = parse_strategy_inputs('strategy("Dynamic")\nlength = input.int(DEFAULT_LENGTH, "Length")')[0]
    assert item.default is None
    assert item.manual_definition_required is True


def test_unresolved_display_group_does_not_erase_known_default():
    source = 'strategy("ICT")\ng_CORE = "Core"\nlength = input.int(3, "Length", minval=2, group=g_CORE)'
    item = parse_strategy_inputs(source)[0]
    assert item.default == 3
    assert item.manual_definition_required is False
    assert item.group == "Core"
    assert item.metadata_warnings == ()


def test_preserves_unsupported_inputs_to_keep_tradingview_id_order():
    source = '''
strategy("Order")
length = input.int(20, "Length")
line_color = input.color(color.blue, "Line Color")
enabled = input.bool(true, "Enabled")
generic = input("value", "Generic")
'''
    inputs = parse_strategy_inputs(source)
    assert [item.variable for item in inputs] == ["length", "line_color", "enabled", "generic"]
    assert [item.kind for item in inputs] == ["int", "color", "bool", "input"]
    assert inputs[1].manual_definition_required is True
    assert inputs[3].manual_definition_required is True
