"""Parameter value validation and lazy combination generation."""

from __future__ import annotations

from itertools import product
from math import prod
from typing import Any, Iterable, Iterator


def combination_count(values: dict[str, list[Any]]) -> int:
    return prod(len(items) for items in values.values()) if values else 1


def iter_combinations(values: dict[str, list[Any]]) -> Iterator[dict[str, Any]]:
    names = list(values)
    for row in product(*(values[name] for name in names)):
        yield dict(zip(names, row, strict=True))


def numeric_range(start: float, stop: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("Adım sıfırdan büyük olmalıdır.")
    if stop < start:
        raise ValueError("Bitiş başlangıçtan küçük olamaz.")
    count = int(round((stop - start) / step))
    result = [round(start + index * step, 10) for index in range(count + 1)]
    if result[-1] < stop and stop - result[-1] > 1e-9:
        result.append(stop)
    return result

