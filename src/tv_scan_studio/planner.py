"""Deterministic, lazy scan plan generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from math import prod
from typing import Any, Iterator

from .combinations import iter_combinations
from .storage import Store


@dataclass(frozen=True, slots=True)
class ScanPlan:
    study_id: str
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    input_values: dict[str, list[Any]]
    date_range: dict[str, Any] = field(default_factory=dict)
    costs: dict[str, Any] = field(default_factory=dict)
    criteria: dict[str, Any] = field(default_factory=dict)
    timeout: float = 75
    poll_interval: float = 0.7
    stable_reads: int = 3

    def validate(self) -> None:
        if not self.study_id.strip():
            raise ValueError("TradingView strateji kimliği gerekli.")
        if not self.symbols or any(not value.strip() for value in self.symbols):
            raise ValueError("En az bir geçerli sembol gerekli.")
        if not self.timeframes or any(not value.strip() for value in self.timeframes):
            raise ValueError("En az bir geçerli timeframe gerekli.")
        if any(not values for values in self.input_values.values()):
            raise ValueError("Her taranan input en az bir değer içermelidir.")
        if self.timeout <= 0:
            raise ValueError("Zaman aşımı sıfırdan büyük olmalıdır.")
        if self.poll_interval <= 0 or self.stable_reads < 1:
            raise ValueError("Doğrulama poll süresi pozitif, stabil okuma en az 1 olmalıdır.")

    @property
    def task_count(self) -> int:
        self.validate()
        return len(self.symbols) * len(self.timeframes) * prod(
            (len(values) for values in self.input_values.values()), start=1
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ScanPlan":
        return cls(
            study_id=value["study_id"], symbols=tuple(value["symbols"]),
            timeframes=tuple(value["timeframes"]), input_values=value["input_values"],
            date_range=value.get("date_range", {}), costs=value.get("costs", {}),
            criteria=value.get("criteria", {}), timeout=float(value.get("timeout", 75)),
            poll_interval=float(value.get("poll_interval", 0.7)),
            stable_reads=int(value.get("stable_reads", 3)),
        )


def iter_tasks(plan: ScanPlan) -> Iterator[tuple[str, dict[str, Any]]]:
    plan.validate()
    for symbol in plan.symbols:
        for timeframe in plan.timeframes:
            for inputs in iter_combinations(plan.input_values):
                payload = {
                    "study_id": plan.study_id, "symbol": symbol, "timeframe": timeframe,
                    "inputs": inputs, "date_range": plan.date_range, "costs": plan.costs,
                    "criteria": plan.criteria, "timeout": plan.timeout,
                    "poll_interval": plan.poll_interval, "stable_reads": plan.stable_reads,
                }
                canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                task_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                yield task_key, payload


def enqueue_plan(store: Store, project_id: int, plan: ScanPlan) -> int:
    store.save_settings(project_id, plan.to_dict())
    return store.enqueue_many(project_id, iter_tasks(plan))
