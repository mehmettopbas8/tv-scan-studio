"""Validation and expansion of user-authored scan value specifications."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def parse_scan_values(value: Any) -> list[Any] | None:
    """Return concrete values; ``None`` means the input is excluded from scanning."""
    if value is None or value == "exclude":
        return None
    if isinstance(value, list):
        if not value:
            raise ValueError("Değer listesi boş olamaz; dışlamak için 'exclude' kullanın.")
        return value
    if not isinstance(value, dict):
        return [value]
    if not {"start", "stop", "step"}.issubset(value):
        raise ValueError("Aralık nesnesi start, stop ve step alanlarını içermelidir.")
    try:
        start = Decimal(str(value["start"])); stop = Decimal(str(value["stop"]))
        step = Decimal(str(value["step"]))
    except InvalidOperation as exc:
        raise ValueError("Aralık değerleri sayı olmalıdır.") from exc
    if step == 0:
        raise ValueError("Aralık adımı sıfır olamaz.")
    if (stop - start) * step < 0:
        raise ValueError("Aralık adımının yönü başlangıç/bitiş ile uyuşmuyor.")
    values: list[int | float] = []
    current = start
    compare = (lambda item: item <= stop) if step > 0 else (lambda item: item >= stop)
    while compare(current):
        values.append(int(current) if current == current.to_integral_value() else float(current))
        if len(values) >= 1_000_000:
            raise ValueError("Tek input aralığı en fazla 1.000.000 değer üretebilir.")
        current += step
    return values
