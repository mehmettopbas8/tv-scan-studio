"""Comparable one-input neighbors for evidence-bounded sensitivity views."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable


def one_input_neighbors(anchor: dict[str, Any], rows: Iterable[dict[str, Any]]):
    """Return only observations that differ in exactly one Pine input.

    Symbol, timeframe, date range and cost assumptions must match. This is a
    descriptive comparison, never proof that an input is causally irrelevant.
    """
    origin = anchor.get("payload") or {}
    base_inputs = origin.get("inputs") or {}
    comparable = ("symbol", "timeframe", "date_range", "costs")
    neighbors = []
    for row in rows:
        if row.get("task_id") == anchor.get("task_id"):
            continue
        payload = row.get("payload") or {}
        if any(payload.get(key) != origin.get(key) for key in comparable):
            continue
        inputs = payload.get("inputs") or {}
        if inputs.keys() != base_inputs.keys():
            continue
        changed = [key for key in base_inputs if inputs[key] != base_inputs[key]]
        if len(changed) == 1:
            key = changed[0]
            neighbors.append({"input_id": key, "base_value": base_inputs[key],
                              "other_value": inputs[key], "row": row})
    return neighbors


def possible_no_effect_inputs(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Flag, never exclude, inputs with 3+ controlled values and identical results.

    All other task settings, other input values, classification and complete
    metrics must match. This observation is local to tested conditions and does
    not prove the input is causally inert on other symbols or periods.
    """
    required = {"trades", "profit_factor", "max_drawdown_pct", "net_profit"}
    groups: dict[tuple[str, str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        if not row.get("verified"):
            continue
        metrics = row.get("metrics") or {}
        if not required.issubset(metrics) or any(metrics[key] is None for key in required):
            continue
        payload = row.get("payload") or {}
        inputs = payload.get("inputs") or {}
        if not inputs:
            continue
        context = {key: value for key, value in payload.items() if key != "inputs"}
        outcome = json.dumps({"classification": row.get("classification"), "metrics": metrics},
                             sort_keys=True, ensure_ascii=False, default=str)
        for input_id, value in inputs.items():
            others = {key: other for key, other in inputs.items() if key != input_id}
            group = (input_id,
                     json.dumps(context, sort_keys=True, ensure_ascii=False, default=str),
                     json.dumps(others, sort_keys=True, ensure_ascii=False, default=str))
            groups[group][json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)].add(outcome)
    flagged: dict[str, int] = {}
    for (input_id, _context, _others), by_value in groups.items():
        if len(by_value) < 3:
            continue
        outcomes = {outcome for signatures in by_value.values() for outcome in signatures}
        if len(outcomes) == 1:
            flagged[input_id] = max(flagged.get(input_id, 0), len(by_value))
    return flagged
