import pytest

from tv_scan_studio.combinations import combination_count, iter_combinations, numeric_range


def test_combination_generation_is_lazy_and_complete():
    values = {"enabled": [True, False], "length": [10, 20, 30]}
    assert combination_count(values) == 6
    assert len(list(iter_combinations(values))) == 6


def test_numeric_range_includes_end():
    assert numeric_range(0.1, 0.3, 0.1) == [0.1, 0.2, 0.3]


def test_numeric_range_rejects_invalid_step():
    with pytest.raises(ValueError):
        numeric_range(1, 2, 0)

