"""Built-in editable starting profiles for common funded-account scans."""

from __future__ import annotations

FTMO_SYMBOL_PROFILES = {
    "FTMO FX + Endeks": (
        "OANDA:EURUSD", "OANDA:GBPUSD", "OANDA:USDJPY", "OANDA:XAUUSD",
        "OANDA:DE30EUR", "OANDA:NAS100USD", "OANDA:SPX500USD",
    ),
    "FTMO FX Majör": (
        "OANDA:EURUSD", "OANDA:GBPUSD", "OANDA:USDJPY",
        "OANDA:AUDUSD", "OANDA:USDCAD", "OANDA:USDCHF",
    ),
}

COST_SCENARIOS = {
    "Özel": 1.0,
    "Normal": 1.0,
    "Orta stres": 1.5,
    "Ağır stres": 2.0,
}


def apply_cost_multiplier(commission: float, spread: float, slippage: int,
                          multiplier: float) -> dict[str, float | int]:
    if multiplier <= 0:
        raise ValueError("Maliyet çarpanı sıfırdan büyük olmalıdır.")
    return {
        "commission_value": round(commission * multiplier, 8),
        "spread": round(spread * multiplier, 8),
        "slippage": round(slippage * multiplier),
    }
