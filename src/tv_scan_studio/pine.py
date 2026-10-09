"""Conservative Pine strategy declaration and input parser."""

from __future__ import annotations

import ast
import re
import math
from dataclasses import dataclass
from typing import Any

STRATEGY_RE = re.compile(r"(?m)^\s*strategy\s*\(")
INPUT_START_RE = re.compile(
    r"(?m)^[ \t]*(?:(?:var|varip|const)[ \t]+)?"
    r"(?:(?:bool|int|float|string|color|timeframe|session)[ \t]+)?"
    r"(?P<variable>[A-Za-z_]\w*)[ \t]*=[ \t]*"
    r"input(?:\.(?P<kind>[A-Za-z_]\w*))?[ \t]*\("
)
SUPPORTED_KINDS = {"bool", "int", "float", "string", "timeframe", "session"}
UNRESOLVED = object()


def strategy_title(source: str) -> str:
    match = STRATEGY_RE.search(source)
    if not match:
        raise ValueError("Yalnızca strategy() içeren Pine kodları desteklenir.")
    body = _call_body(source, match.end() - 1)
    if body is None:
        raise ValueError("strategy() bildirimi tamamlanmamış.")
    positional: list[str] = []
    named: dict[str, str] = {}
    for argument in _split_arguments(body):
        name, value = _named_argument(argument)
        (positional.append(value) if name is None else named.__setitem__(name, value))
    title = _literal(named.get("title", positional[0] if positional else ""))
    if title is UNRESOLVED or not isinstance(title, str) or not title:
        raise ValueError("strategy() başlığı kesin olarak okunamadı.")
    return title

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
    metadata_warnings: tuple[str, ...] = ()

def validate_input_value(spec: PineInput, value: Any) -> None:
    """Validate typed values against the source declaration, without coercion."""
    label = spec.title
    if spec.kind in {"int", "float"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{label}: sonlu sayısal değer gerekli.")
        if spec.kind == "int" and not isinstance(value, int):
            raise ValueError(f"{label}: tam sayı gerekli.")
        if spec.minimum is not None and value < spec.minimum:
            raise ValueError(f"{label}: en küçük değer {spec.minimum}.")
        if spec.maximum is not None and value > spec.maximum:
            raise ValueError(f"{label}: en büyük değer {spec.maximum}.")
        if spec.step is not None:
            if not math.isfinite(spec.step) or spec.step <= 0:
                raise ValueError(f"{label}: kodda geçersiz adım tanımı var.")
            origin = spec.minimum if spec.minimum is not None else spec.default
            if not isinstance(origin, (int, float)) or isinstance(origin, bool):
                raise ValueError(f"{label}: adım başlangıcı doğrulanamıyor.")
            units = (value - origin) / spec.step
            if not math.isfinite(units) or not math.isclose(units, round(units), abs_tol=1e-8, rel_tol=0):
                raise ValueError(f"{label}: {spec.step} adımına uygun değer gerekli.")
    elif spec.kind == "bool" and not isinstance(value, bool):
        raise ValueError(f"{label}: açık/kapalı değeri gerekli.")
    elif spec.kind in {"string", "session", "timeframe"} and not isinstance(value, str):
        raise ValueError(f"{label}: metin değeri gerekli.")
    if spec.options is not None and value not in spec.options:
        raise ValueError(f"{label}: kodda tanımlı seçenekleri kullanın.")


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
    # Resolve only direct string constants used by display metadata. Do not
    # evaluate Pine expressions or infer a dynamic trading input's default.
    constants = {}
    for constant in re.finditer(
        r'(?m)^\s*(?:(?:var|const)\s+)?(?:string\s+)?([A-Za-z_]\w*)\s*=\s*("(?:[^"\\]|\\.)*")\s*$',
        source,
    ):
        value = _literal(constant.group(2))
        if isinstance(value, str):
            constants[constant.group(1)] = value

    def metadata_literal(token: str) -> Any:
        return constants[token.strip()] if token.strip() in constants else _literal(token)

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
        title = metadata_literal(title_token) if title_token else match.group("variable")
        options = _literal(named["options"]) if "options" in named else None
        minimum = _literal(named["minval"]) if "minval" in named else None
        maximum = _literal(named["maxval"]) if "maxval" in named else None
        step = _literal(named["step"]) if "step" in named else None
        group = metadata_literal(named["group"]) if "group" in named else None
        tooltip = metadata_literal(named["tooltip"]) if "tooltip" in named else None
        metadata = {"başlık": title, "seçenekler": options, "minimum": minimum,
                    "maksimum": maximum, "adım": step, "grup": group, "açıklama": tooltip}
        warnings = tuple(name for name, value in metadata.items() if value is UNRESOLVED)
        # Display-only metadata must not make an otherwise known default unusable.
        manual = kind not in SUPPORTED_KINDS or default is UNRESOLVED
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
            metadata_warnings=warnings,
        ))
    return inputs
