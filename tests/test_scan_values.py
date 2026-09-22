import pytest

from tv_scan_studio.scan_values import parse_scan_values


def test_list_scalar_range_and_exclusion():
    assert parse_scan_values([1, 2]) == [1, 2]
    assert parse_scan_values(True) == [True]
    assert parse_scan_values("exclude") is None
    assert parse_scan_values({"start": 0.5, "stop": 1.0, "step": 0.25}) == [0.5, 0.75, 1]
    assert parse_scan_values({"start": 3, "stop": 1, "step": -1}) == [3, 2, 1]


def test_invalid_ranges_are_rejected():
    with pytest.raises(ValueError, match="sıfır"):
        parse_scan_values({"start": 1, "stop": 2, "step": 0})
    with pytest.raises(ValueError, match="yönü"):
        parse_scan_values({"start": 1, "stop": 2, "step": -1})
