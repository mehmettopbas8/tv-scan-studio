import pytest
from tv_scan_studio.symbol_search import search_url, catalogue_results


def test_search_query_is_encoded_and_bounded():
    assert "text=BIST%3AXU030D1%21" in search_url("BIST:XU030D1!")
    with pytest.raises(ValueError):
        search_url(" ")
    with pytest.raises(ValueError):
        search_url("x" * 121)


def test_catalogue_keeps_codes_separate_from_readable_names():
    row = {"symbol": "<em>XU030D1!</em>", "description": "BIST 30 &amp; Futures", "exchange": "BIST"}
    assert catalogue_results({"symbols": [row, row, {}, None]}) == [{
        "code": "BIST:XU030D1!", "name": "BIST 30 & Futures", "exchange": "BIST", "type": ""}]
    with pytest.raises(ValueError):
        catalogue_results({"symbols": "bad"})
