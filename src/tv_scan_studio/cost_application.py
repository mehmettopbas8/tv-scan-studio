"""Preflight checks for cost assumptions that TradingView cannot apply implicitly."""

from __future__ import annotations

import math
from typing import Any


def strategy_property_values(definitions: list[dict[str, Any]],
                             assumptions: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve Properties by observed metadata, never by strategy-specific in_N offsets."""
    fields = {
        "initial_capital": ("Initial Capital", "float"),
        "position_size": ("Default entry/order Qty Value", "float"),
        "commission_value": ("Commission Value", "float"),
        "slippage": ("Backtesting slippage for market orders", "integer"),
        "commission_type": ("Commission Type", "text"),
    }
    values = []
    for key, (name, kind) in fields.items():
        value = assumptions.get(key)
        if kind == "text":
            valid = value in {"percent", "cash_per_contract", "cash_per_order"}
        else:
            valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                     and math.isfinite(value) and value >= 0
                     and (key not in {"initial_capital", "position_size"} or value > 0)
                     and (kind != "integer" or float(value).is_integer()))
        if not valid:
            raise ValueError(f"Geçersiz Strategy Properties beklentisi: {key}")
        matches = [d for d in definitions if d.get("groupId") == "strategy_props"
                   and d.get("name") == name and d.get("type") == kind]
        if len(matches) != 1 or not matches[0].get("id"):
            raise ValueError(f"Benzersiz Strategy Properties alanı bulunamadı: {key}")
        if kind == "text" and value not in matches[0].get("options", []):
            raise ValueError("Komisyon türü TradingView seçeneklerinde yok.")
        values.append({"id": matches[0]["id"], "value": value})
    qty = [d for d in definitions if d.get("groupId") == "strategy_props"
           and d.get("name") == "Default entry/order Qty Type" and d.get("type") == "text"]
    if len(qty) != 1 or "fixed" not in qty[0].get("options", []):
        raise ValueError("Kontrat emir türü TradingView seçeneklerinde yok.")
    values.append({"id": qty[0]["id"], "value": "fixed"})
    if len({v["id"] for v in values}) != len(values):
        raise ValueError("Strategy Properties alan kimlikleri çakışıyor.")
    return values


def validate_spread_mapping(costs: dict[str, Any]) -> None:
    """A nonzero spread needs an explicit strategy input; Properties has no spread field."""
    assumptions = costs.get("assumptions") or {}
    spread = assumptions.get("spread", 0)
    if isinstance(spread, bool) or not isinstance(spread, (int, float)) \
            or not math.isfinite(spread) or spread < 0:
        raise ValueError("Spread değeri geçerli ve sıfır veya pozitif olmalıdır.")
    if spread == 0:
        return
    input_id = (costs.get("input_mapping") or {}).get("spread")
    if not input_id or (costs.get("tradingview_inputs") or {}).get(input_id) != spread:
        raise ValueError(
            "Sıfırdan büyük spread TradingView Properties içinde uygulanmaz. "
            "Stratejideki spread inputunu eşleyin veya spreadi sıfırlayın."
        )
