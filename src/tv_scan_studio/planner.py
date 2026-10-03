"""Deterministic, lazy scan plan generation."""

from __future__ import annotations

import hashlib
import json
from datetime import date
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
    variants: list[dict[str, Any]] = field(default_factory=list)
    date_range: dict[str, Any] = field(default_factory=dict)
    costs: dict[str, Any] = field(default_factory=dict)
    criteria: dict[str, Any] = field(default_factory=dict)
    timeout: float = 75
    poll_interval: float = 0.7
    stable_reads: int = 3

    def validate(self, *, require_study_id: bool = True) -> None:
        if require_study_id and not self.study_id.strip():
            raise ValueError("TradingView strateji kimliği gerekli.")
        if not self.symbols or any(not value.strip() for value in self.symbols):
            raise ValueError("En az bir geçerli sembol gerekli.")
        if not self.timeframes or any(not value.strip() for value in self.timeframes):
            raise ValueError("En az bir geçerli timeframe gerekli.")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Aynı sembol birden fazla seçilemez; görev sayısı şişer.")
        if len(set(self.timeframes)) != len(self.timeframes):
            raise ValueError("Aynı timeframe birden fazla seçilemez; görev sayısı şişer.")
        if any(not values for values in self.input_values.values()):
            raise ValueError("Her taranan input en az bir değer içermelidir.")
        if any(not isinstance(variant, dict) or not variant for variant in self.variants):
            raise ValueError("Her kontrollü varyant dolu bir input sözlüğü olmalıdır.")
        if any(set(variant) & set(self.input_values) for variant in self.variants):
            raise ValueError("Kontrollü varyantlar temel tarama inputlarını ezemez.")
        def distinct(values: list[Any], label: str) -> None:
            try:
                keys = [json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
                        for value in values]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{label} JSON olarak kaydedilebilir olmalı.") from exc
            if len(set(keys)) != len(keys):
                raise ValueError(f"{label} yinelenen değer içeriyor; görev sayısı şişer.")
        for name, values in self.input_values.items():
            distinct(values, f"{name} inputu")
        distinct(self.variants, "Kontrollü varyant")
        if self.date_range:
            start, end = self.date_range.get("from"), self.date_range.get("to")
            if not isinstance(start, str) or not isinstance(end, str):
                raise ValueError("Tarih aralığında başlangıç ve bitiş YYYY-MM-DD olmalıdır.")
            try:
                start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
            except ValueError as exc:
                raise ValueError("Tarih aralığı YYYY-MM-DD biçiminde olmalıdır.") from exc
            if start_date.isoformat() != start or end_date.isoformat() != end or start_date > end_date:
                raise ValueError("Tarih aralığı geçerli ve başlangıç bitişten önce olmalıdır.")
        if self.timeout <= 0:
            raise ValueError("Zaman aşımı sıfırdan büyük olmalıdır.")
        if self.poll_interval <= 0 or self.stable_reads < 1:
            raise ValueError("Doğrulama poll süresi pozitif, stabil okuma en az 1 olmalıdır.")

    @property
    def task_count(self) -> int:
        return prod((size for _, size in self.workload_factors()), start=1)

    def workload_factors(self) -> tuple[tuple[str, int], ...]:
        """Expose the exact multiplicative factors used by task generation."""
        self.validate(require_study_id=False)
        return (("symbols", len(self.symbols)), ("timeframes", len(self.timeframes)),
                ("variants", len(self.variants) or 1),
                *((key, len(values)) for key, values in self.input_values.items()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ScanPlan":
        return cls(
            study_id=value["study_id"], symbols=tuple(value["symbols"]),
            timeframes=tuple(value["timeframes"]), input_values=value["input_values"],
            variants=value.get("variants", []),
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
                for variant in (plan.variants or [{}]):
                    payload = {
                        "study_id": plan.study_id, "symbol": symbol, "timeframe": timeframe,
                        "inputs": {**inputs, **variant}, "date_range": plan.date_range, "costs": plan.costs,
                        "criteria": plan.criteria, "timeout": plan.timeout,
                        "poll_interval": plan.poll_interval, "stable_reads": plan.stable_reads,
                    }
                    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    task_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                    yield task_key, payload


def enqueue_plan(store: Store, project_id: int, plan: ScanPlan) -> int:
    store.save_settings(project_id, plan.to_dict())
    return store.enqueue_many(project_id, iter_tasks(plan))
