"""Generate deterministic follow-up tasks for staged robustness validation."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Iterator

from .storage import Store


def _key(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def followup_payloads(payload: dict[str, Any], alternative_symbol: str) -> Iterator[tuple[str, dict[str, Any]]]:
    for input_id, value in payload.get("inputs", {}).items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        step = max(abs(value) * 0.05, 1 if isinstance(value, int) else 0.01)
        for direction in (-1, 1):
            child = deepcopy(payload)
            candidate = value + direction * step
            child["inputs"][input_id] = int(round(candidate)) if isinstance(value, int) else round(candidate, 8)
            child["validation_stage"] = "neighbor"
            yield "neighbor", child
    for multiplier in (1.5, 2.0):
        child = deepcopy(payload)
        assumptions = child.setdefault("costs", {}).setdefault("assumptions", {})
        mapping = child["costs"].get("input_mapping", {})
        configured = child["costs"].setdefault("tradingview_inputs", {})
        for name in ("commission_value", "spread", "slippage"):
            assumptions[name] = assumptions.get(name, 0) * multiplier
            if name in mapping:
                configured[mapping[name]] = assumptions[name]
        child["validation_stage"] = "cost_stress"
        child["cost_multiplier"] = multiplier
        yield "cost_stress", child
    if alternative_symbol.strip():
        child = deepcopy(payload)
        child["symbol"] = alternative_symbol.strip()
        child["validation_stage"] = "provider_check"
        yield "provider_check", child


def enqueue_followups(store: Store, parent_task_id: int, payload: dict[str, Any],
                      alternative_symbol: str) -> int:
    inserted = 0
    for stage, child in followup_payloads(payload, alternative_symbol):
        inserted += int(store.enqueue_validation(parent_task_id, stage, _key(child), child))
    return inserted
