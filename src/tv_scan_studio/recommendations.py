"""Conservative scan ranges with explicit provenance and Pine dependencies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

from .pine import PineInput


@dataclass(frozen=True, slots=True)
class InputSuggestion:
    values: tuple[Any, ...]
    source: str
    note: str
    active_when: str | None = None
    unused_in_source: bool = False
    declared_no_backtest_effect: bool = False


def _declares_no_backtest_effect(tooltip: str | None) -> bool:
    """Use an explicit Pine tooltip claim as a reversible scan suggestion, not proof."""
    if not tooltip:
        return False
    normalized = tooltip.casefold()
    return bool(re.search(r"backtest.{0,60}(?:etk[iı]lemez|does not affect|no effect)", normalized)
                or re.search(r"(?:does not affect|no effect).{0,60}backtest", normalized))


def _bounded_numeric(item: PineInput) -> tuple[int | float, ...]:
    default = Decimal(str(item.default))
    if item.step is not None and item.step > 0:
        step = Decimal(str(item.step))
    elif item.kind == "int":
        step = Decimal(1)
    else:
        step = max(abs(default) / Decimal(10), Decimal("0.1"))
    lower = Decimal(str(item.minimum)) if item.minimum is not None else None
    upper = Decimal(str(item.maximum)) if item.maximum is not None else None
    values = []
    for candidate in (default - step, default, default + step):
        if (lower is not None and candidate < lower) or (upper is not None and candidate > upper):
            continue
        value = int(candidate) if item.kind == "int" else float(candidate)
        if value not in values:
            values.append(value)
    return tuple(values)


def suggest_input(item: PineInput, source: str = "", *,
                  prior_values: Iterable[Any] = (), active_when: str | None = None) -> InputSuggestion:
    """Suggest values and flag an input whose variable has no other source use."""
    uses = len(re.findall(rf"\b{re.escape(item.variable)}\b", source)) if source else 0
    unused = bool(source and uses == 1)
    no_backtest_effect = _declares_no_backtest_effect(item.tooltip)
    dependency = f"Yalnızca {active_when} etkinken" if active_when else ""
    if item.manual_definition_required:
        return InputSuggestion((), "Pine", "Varsayılan güvenle okunamadı; grafikten doğrula.",
                               active_when, unused, no_backtest_effect)
    if item.options:
        values = tuple(item.options)
        origin, note = "Pine seçenekleri", "Stratejide tanımlı seçenekler."
    elif item.kind == "bool":
        values = (False, True)
        origin, note = "Pine türü", "Kapalı ve açık durumları."
    elif item.kind in {"int", "float"} and isinstance(item.default, (int, float)):
        values = _bounded_numeric(item)
        origin, note = "Tahmini", "Varsayılan çevresi; performans garantisi değildir."
    else:
        values = (item.default,)
        origin, note = "Pine varsayılanı", "Otomatik geniş aralık önerilmez."
    history = tuple(dict.fromkeys(prior_values))
    if history and len(history) <= 12 and all(type(value) is type(item.default) for value in history):
        values = history
        origin, note = "Proje geçmişi", "Önceki sonuç değerleri; sembol ve dönemi ayrıca karşılaştırın."
    if dependency:
        note = f"{dependency}. {note}"
    if unused:
        note = f"Değişken kaynakta yalnız tanımlanmış; otomatik dışlama adayı. {note}"
    if no_backtest_effect:
        note = f"Pine açıklaması backtest etkisi olmadığını söylüyor; taramadan çıkarma adayı. {note}"
    return InputSuggestion(values, origin, note, active_when, unused, no_backtest_effect)


def input_dependencies(source: str) -> dict[str, str]:
    """Only simple Pine active=<switch> guards are inferred; no causal claim."""
    pattern = re.compile(
        r"(?m)^\s*(?:(?:bool|int|float|string|color)\s+)?"
        r"([A-Za-z_]\w*)\s*=\s*input(?:\.\w+)?\s*\("
    )
    from .pine import _call_body, _named_argument, _split_arguments

    dependencies = {}
    for match in pattern.finditer(source):
        body = _call_body(source, match.end() - 1)
        if body is None:
            continue
        for argument in _split_arguments(body):
            name, value = _named_argument(argument)
            if name == "active" and re.fullmatch(r"(?:not\s+)?[A-Za-z_]\w*", value.strip()):
                dependencies[match.group(1)] = value.strip()
    return dependencies


def historical_values_by_input(rows: Iterable[dict[str, Any]], limit: int = 12) -> dict[str, tuple[Any, ...]]:
    """Offer values observed in verified successful project tasks, strongest PF first."""
    from .result_filters import SUCCESS_CLASSES

    eligible = [row for row in rows if row.get("verified")
                and row.get("classification") in SUCCESS_CLASSES]
    eligible.sort(key=lambda row: float((row.get("metrics") or {}).get("profit_factor") or 0), reverse=True)
    values: dict[str, list[Any]] = {}
    for row in eligible:
        for key, value in ((row.get("payload") or {}).get("inputs") or {}).items():
            bucket = values.setdefault(key, [])
            if value not in bucket and len(bucket) < limit:
                bucket.append(value)
    return {key: tuple(bucket) for key, bucket in values.items()}
