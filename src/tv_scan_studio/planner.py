"""Deterministic, lazy scan plan generation."""

from __future__ import annotations

import hashlib
import json
import random
import operator
from datetime import date
from dataclasses import asdict, dataclass, field, replace
from math import prod, isfinite
from typing import Any, Iterator, Callable

from .combinations import iter_combinations
from .storage import Store
from .pine import parse_strategy_inputs, validate_input_value


class PlanCancelled(RuntimeError):
    """Cancellation is not a successful empty/partial plan."""


def _check_cancel(cancel_requested):
    if cancel_requested is not None and cancel_requested():
        raise PlanCancelled("Plan işlemi iptal edildi; yarım plan kaydedilmedi.")


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
    method: str = "cartesian"
    sample_budget: int | None = None
    sample_seed: int = 0
    constraints: list[dict[str, str]] = field(default_factory=list)
    research: dict[str, Any] = field(default_factory=dict)

    def validate(self, *, require_study_id: bool = True) -> None:
        if self.method not in {"cartesian", "sample", "coarse"}:
            raise ValueError("Geçersiz tarama yöntemi.")
        if not isinstance(self.research, dict):
            raise ValueError("Araştırma bağlantısı geçersiz.")
        if self.method == "sample" and (isinstance(self.sample_budget, bool)
                or not isinstance(self.sample_budget, int) or self.sample_budget < 1):
            raise ValueError("Örnekleme bütçesi pozitif tam sayı olmalıdır.")
        if isinstance(self.sample_seed, bool) or not isinstance(self.sample_seed, int):
            raise ValueError("Örnekleme tohumu tam sayı olmalıdır.")
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
        for rule in self.constraints:
            if not isinstance(rule, dict) or set(rule) != {"left", "operator", "right"}:
                raise ValueError("Ayar ilişkisi iki ayar ve bir karşılaştırma içermelidir.")
            if rule["operator"] not in {"<", "<=", ">", ">="}:
                raise ValueError("Ayar ilişkisi <, ≤, > veya ≥ olmalıdır.")
            if rule["left"] == rule["right"]:
                raise ValueError("Ayar ilişkisi iki farklı ayar arasında olmalıdır.")
            for name in (rule["left"], rule["right"]):
                choices = self.input_values.get(name)
                if choices is None:
                    if not self.variants or any(name not in variant for variant in self.variants):
                        raise ValueError(f"{name}: ilişki için her testte bir değer gerekli.")
                    choices = [variant[name] for variant in self.variants]
                if any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not isfinite(value) for value in choices):
                    raise ValueError(f"{name}: ilişkiler yalnız sonlu sayısal ayarlara uygulanabilir.")
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
        if isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)) or not isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("Zaman aşımı sıfırdan büyük olmalıdır.")
        if (isinstance(self.poll_interval, bool) or not isinstance(self.poll_interval, (int, float))
                or not isfinite(self.poll_interval) or self.poll_interval <= 0
                or isinstance(self.stable_reads, bool) or not isinstance(self.stable_reads, int) or self.stable_reads < 1):
            raise ValueError("Doğrulama poll süresi pozitif, stabil okuma en az 1 olmalıdır.")
        try:
            json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Plan, maliyet ve başarı ölçütleri sonlu ve kaydedilebilir değerler içermelidir.") from exc

    @property
    def task_count(self) -> int:
        total = self.eligible_count
        return min(total, self.sample_budget) if self.method == "sample" else total

    def accepts_inputs(self, inputs: dict[str, Any]) -> bool:
        operations = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
        return all(operations[rule["operator"]](inputs[rule["left"]], inputs[rule["right"]])
                   for rule in self.constraints)

    @property
    def eligible_count(self) -> int:
        return self.count_eligible()

    def count_eligible(self, *, cancel_requested=None, progress=None) -> int:
        _check_cancel(cancel_requested)
        self.validate(require_study_id=False)
        if not self.constraints:
            return self.cartesian_count
        inputs_count = examined = 0
        for inputs in iter_combinations(self.input_values):
            for variant in (self.variants or [{}]):
                _check_cancel(cancel_requested)
                examined += 1
                inputs_count += self.accepts_inputs({**inputs, **variant})
                if progress is not None and examined % 256 == 0:
                    progress(examined, inputs_count)
        _check_cancel(cancel_requested)
        if progress is not None:
            progress(examined, inputs_count)
        return inputs_count * len(self.symbols) * len(self.timeframes)

    def constraint_counts(self) -> dict[str, int]:
        before, remaining = self.cartesian_count, self.eligible_count
        return {"before": before, "skipped": before - remaining, "remaining": remaining}

    @property
    def cartesian_count(self) -> int:
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
            criteria=value.get("criteria", {}), timeout=value.get("timeout", 75),
            poll_interval=value.get("poll_interval", 0.7),
            stable_reads=value.get("stable_reads", 3),
            method=value.get("method", "cartesian"),
            sample_budget=value.get("sample_budget"), sample_seed=value.get("sample_seed", 0),
            constraints=value.get("constraints", []),
            research=value.get("research", {}),
        )


def iter_tasks(plan: ScanPlan, *, cancel_requested: Callable[[], bool] | None = None) -> Iterator[tuple[str, dict[str, Any]]]:
    _check_cancel(cancel_requested)
    plan.validate()
    if plan.constraints:
        candidates = (task for task in iter_tasks(replace(plan, constraints=[], method="cartesian"), cancel_requested=cancel_requested)
                      if plan.accepts_inputs(task[1]["inputs"]))
        if plan.method != "sample":
            yield from candidates
        else:
            # Uniform reservoir over eligible tasks, never over invalid tasks.
            rng = random.Random(plan.sample_seed)
            reservoir = []
            for index, task in enumerate(candidates):
                if index < plan.sample_budget:
                    reservoir.append((index, task))
                else:
                    position = rng.randrange(index + 1)
                    if position < plan.sample_budget:
                        reservoir[position] = (index, task)
            for _, task in sorted(reservoir):
                _check_cancel(cancel_requested)
                yield task
        return
    if plan.method == "sample":
        # Floyd sampling uses O(budget) memory and arbitrary-sized integer
        # populations, without traversing or materializing the Cartesian space.
        rng = random.Random(plan.sample_seed)
        total, count = plan.cartesian_count, plan.task_count
        selected = set()
        for upper in range(total - count, total):
            _check_cancel(cancel_requested)
            candidate = rng.randrange(upper + 1)
            selected.add(upper if candidate in selected else candidate)
        axes = [list(plan.symbols), list(plan.timeframes), *plan.input_values.values(), plan.variants or [{}]]
        for ordinal in sorted(selected):
            _check_cancel(cancel_requested)
            positions = []
            for axis in reversed(axes):
                ordinal, position = divmod(ordinal, len(axis))
                positions.append(position)
            picked = [axis[position] for axis, position in zip(axes, reversed(positions), strict=True)]
            inputs = dict(zip(plan.input_values, picked[2:-1], strict=True))
            single = ScanPlan.from_dict({**plan.to_dict(), "method": "cartesian",
                "symbols": [picked[0]], "timeframes": [picked[1]],
                "input_values": {key: [value] for key, value in inputs.items()},
                "variants": [picked[-1]] if picked[-1] else []})
            yield from iter_tasks(single, cancel_requested=cancel_requested)
        return
    for symbol in plan.symbols:
        for timeframe in plan.timeframes:
            for inputs in iter_combinations(plan.input_values):
                for variant in (plan.variants or [{}]):
                    _check_cancel(cancel_requested)
                    payload = {
                        "study_id": plan.study_id, "symbol": symbol, "timeframe": timeframe,
                        "inputs": {**inputs, **variant}, "date_range": plan.date_range, "costs": plan.costs,
                        "criteria": plan.criteria, "timeout": plan.timeout,
                        "poll_interval": plan.poll_interval, "stable_reads": plan.stable_reads,
                    }
                    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    task_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                    yield task_key, payload
    _check_cancel(cancel_requested)


def enqueue_plan(store: Store, project_id: int, plan: ScanPlan, *,
                 settings: dict[str, Any] | None = None, cancel_requested=None, progress=None,
                 require_pending_subset=False, new_run=False, run_id=None, return_run_id=False) -> int | tuple[int, int]:
    _check_cancel(cancel_requested)
    plan.validate()
    if not isinstance(new_run, bool) or (run_id is not None and (isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1)):
        raise ValueError("Geçerli tarama koşusu kimliği gerekli.")
    if new_run and run_id is not None:
        raise ValueError("Yeni koşu ve devam et aynı anda seçilemez.")
    snapshot = plan.to_dict()
    project = store.project(project_id)
    if project is None:
        raise ValueError("Kayıtlı strateji bulunamadı.")
    if plan.research:
        if not new_run and run_id is None:
            raise ValueError("Ayrıntılı araştırma ayrı bir koşuda kaydedilmeli.")
        from .period_research import validate_research_request
        with store.connect() as connection:
            validate_research_request(connection, project_id, plan.to_dict(), project["pine_source"])
    definitions = {f"in_{index}": spec for index, spec in enumerate(
        parse_strategy_inputs(project["pine_source"]))}
    # Legacy plans without parsed declarations remain readable. When source
    # declarations exist, every selected/mapped value must match that source.
    if definitions:
        selections = list(plan.input_values.items())
        selections.extend((key, [value]) for variant in plan.variants for key, value in variant.items())
        selections.extend((key, [value]) for key, value in plan.costs.get("tradingview_inputs", {}).items())
        for key, values in selections:
            if key not in definitions:
                raise ValueError(f"{key}: kayıtlı kaynakta ayar bulunamadı.")
            for value in values:
                validate_input_value(definitions[key], value)
    if settings:
        if set(settings) & set(snapshot):
            raise ValueError("Ek arayüz ayarları doğrulanmış planı değiştiremez.")
        snapshot.update(settings)
    run_request = {"mode": "new" if new_run else "resume", "plan": plan.to_dict(), "run_id": run_id} if new_run or run_id is not None else None
    return store.enqueue_many(project_id, iter_tasks(plan, cancel_requested=cancel_requested), settings=snapshot,
                              check_cancel=lambda: _check_cancel(cancel_requested), progress=progress,
                              require_pending_subset=require_pending_subset, expected_source=project["pine_source"],
                              run_request=run_request, return_run_id=return_run_id)
