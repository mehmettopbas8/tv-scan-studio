"""Preflight checks for cost assumptions that TradingView cannot apply implicitly."""

from __future__ import annotations

import math
import re
from typing import Any


def validate_direct_order_quantity(source: str, input_values: dict[str, list[Any]],
                                   costs: dict[str, Any]) -> None:
    """Reject a misleading Properties quantity for directly input-sized orders.

    This deliberately does not claim to interpret computed risk-sizing expressions.
    Literal strings/comments are masked before finding executable entry/order calls.
    """
    from .pine import _call_body, _named_argument, _split_arguments, parse_strategy_inputs

    masked = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*',
                    lambda match: ' ' * len(match[0]), source)
    definitions = {item.variable: (f'in_{index}', item)
                   for index, item in enumerate(parse_strategy_inputs(source))}
    expected = (costs.get('assumptions') or {}).get('position_size')
    if expected is None:
        return
    for match in re.finditer(r'\bstrategy\.(?:entry|order)\s*\(', masked):
        body = _call_body(masked, match.end() - 1)
        if body is None:
            continue
        arguments = dict(_named_argument(argument) for argument in _split_arguments(body))
        expression = arguments.get('qty', '').strip()
        if expression not in definitions:
            continue
        key, item = definitions[expression]
        if item.kind not in {'int', 'float'} or item.manual_definition_required:
            continue
        override = (costs.get('tradingview_inputs') or {}).get(key)
        selected = [override] if override is not None else input_values.get(key, [item.default])
        # An explicit quantity scan is intentional; don't replace or suppress its
        # combinations with a single Properties value. This check targets fixed
        # quantity setups only, not economic verification of a sizing scan.
        if len(selected) > 1 and override is None:
            continue
        if any(value != expected for value in selected):
            raise ValueError(
                f'Emir miktarı stratejide “{item.title}” inputundan belirleniyor. '
                'TradingView varsayılan pozisyon ayarı bunu değiştirmez. '
                'Pozisyon boyutunu bu inputa eşleyin veya input değerleriyle aynı tutun.'
            )


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
