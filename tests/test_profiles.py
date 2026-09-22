import pytest

from tv_scan_studio.profiles import FTMO_SYMBOL_PROFILES, apply_cost_multiplier


def test_ftmo_profiles_are_provider_qualified_and_editable_starting_values():
    assert FTMO_SYMBOL_PROFILES
    assert all(":" in symbol for profile in FTMO_SYMBOL_PROFILES.values() for symbol in profile)


def test_cost_stress_multiplier():
    assert apply_cost_multiplier(0.1, 1.2, 2, 1.5) == {
        "commission_value": 0.15, "spread": 1.8, "slippage": 3,
    }
    with pytest.raises(ValueError):
        apply_cost_multiplier(0.1, 1, 1, 0)
