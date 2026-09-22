"""Conservative Pine strategy declaration and input parser."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any

STRATEGY_RE = re.compile(r"(?m)^\s*strategy\s*\(")
INPUT_START_RE = re.compile(
    r"(?m)^\s*(?P<variable>[A-Za-z_]\w*)\s*=\s*input(?:\.(?P<kind>[A-Za-z_]\w*))?\s*\("
)
SUPPORTED_KINDS = {"bool", "int", "float", "string", "timeframe", "session"}
UNRESOLVED = object()

@dataclass(frozen=True, slots=True)
class PineInput:
    variable: str
    kind: str
    default: Any
    title: str
    options: tuple[Any, ...] | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    step: int | float | None = None
    group: str | None = None
    tooltip: str | None = None
    manual_definition_required: bool = False

def _literal(value: str) -> Any:
    value = value.strip()
    if value == "true": return True
    if value == "false": return False
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return UNRESOLVED

def _call_body(source: str, opening_parenthesis: int) -> str | None:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(opening_parenthesis, len(source)):
        char = source[index]
        if quote:
            if escaped: escaped = False
            elif char == "\\": escaped = True
            elif char == quote: quote = None
            continue
        if char in {'"', "'"}: quote = char
        elif char in "([": depth += 1
        elif char in ")]":
            depth -= 1
            if depth == 0: return source[opening_parenthesis + 1:index]
    return None

def _split_arguments(body: str) -> list[str]:
    arguments: list[str] = []
    start = depth = 0
    quote: str | None = None
    escaped = False
    for index, char in enumerate(body):
        if quote:
            if escaped: escaped = False
            elif char == "\\": escaped = True
            elif char == quote: quote = None
            continue
        if char in {'"', "'"}: quote = char
        elif char in "([": depth += 1
        elif char in ")]": depth -= 1
        elif char == "," and depth == 0:
            arguments.append(body[start:index].strip())
            start = index + 1
    arguments.append(body[start:].strip())
    return [argument for argument in arguments if argument]

def _named_argument(argument: str) -> tuple[str | None, str]:
    match = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.*)$", argument, re.DOTALL)
    return (match.group(1), match.group(2)) if match else (None, argument)

def parse_strategy_inputs(source: str) -> list[PineInput]:
    if not STRATEGY_RE.search(source):
        raise ValueError("Yalnızca strategy() içeren Pine kodları desteklenir.")
    inputs: list[PineInput] = []
    for match in INPUT_START_RE.finditer(source):
        kind = match.group("kind") or "input"
        body = _call_body(source, match.end() - 1)
        if body is None:
            inputs.append(PineInput(match.group("variable"), kind, None, match.group("variable"), manual_definition_required=True))
            continue
        positional: list[str] = []
        named: dict[str, str] = {}
        for argument in _split_arguments(body):
            name, value = _named_argument(argument)
            (positional.append(value) if name is None else named.__setitem__(name, value))
        default = _literal(named.get("defval", positional[0] if positional else ""))
        title_token = named.get("title", positional[1] if len(positional) > 1 else "")
        title = _literal(title_token) if title_token else match.group("variable")
        options = _literal(named["options"]) if "options" in named else None
        minimum = _literal(named["minval"]) if "minval" in named else None
        maximum = _literal(named["maxval"]) if "maxval" in named else None
        step = _literal(named["step"]) if "step" in named else None
        group = _literal(named["group"]) if "group" in named else None
        tooltip = _literal(named["tooltip"]) if "tooltip" in named else None
        manual = kind not in SUPPORTED_KINDS or any(
            value is UNRESOLVED for value in (default, title, options, minimum, maximum, step, group, tooltip)
        )
        inputs.append(PineInput(
            variable=match.group("variable"), kind=kind,
            default=None if default is UNRESOLVED else default,
            title=match.group("variable") if title is UNRESOLVED else str(title),
            options=tuple(options) if isinstance(options, (list, tuple)) else None,
            minimum=minimum if isinstance(minimum, (int, float)) else None,
            maximum=maximum if isinstance(maximum, (int, float)) else None,
            step=step if isinstance(step, (int, float)) else None,
            group=group if isinstance(group, str) else None,
            tooltip=tooltip if isinstance(tooltip, str) else None,
            manual_definition_required=manual,
        ))
    return inputs
