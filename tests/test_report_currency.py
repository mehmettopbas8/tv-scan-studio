import pytest
from tv_scan_studio.report_currency import report_currency_code


@pytest.mark.parametrize("value", ["USD", "TRY", "EUR"])
def test_explicit_known_report_currency_is_preserved(value):
    assert report_currency_code(value) == value


@pytest.mark.parametrize("value", [None, "", "Default", "usd", "OANDA:EURUSD", " USD", {}, True, 1])
def test_unknown_symbol_account_or_malformed_currency_is_not_inferred(value):
    assert report_currency_code(value) is None


def test_snapshot_currency_reads_explicit_report_field_not_series_or_input(monkeypatch):
    from tv_scan_studio.tradingview import GncZihinDriver
    driver = GncZihinDriver()
    data = {"symbol": "BIST:XU030D1!", "tf": "15", "status": {"type": 2},
            "inputs": [{"id": "Base currency", "value": "USD"}], "metrics": {}, "period": {},
            "report_currency": "TRY"}
    scripts = []
    def evaluate(_target, _study, script):
        scripts.append(script)
        return data
    monkeypatch.setattr(driver, "_eval", evaluate)
    result = driver.snapshot("target", "study")
    assert result.report_currency == "TRY"
    assert "r?.currency" in scripts[0]
    data["report_currency"] = "Default"
    assert driver.snapshot("target", "study").report_currency is None
