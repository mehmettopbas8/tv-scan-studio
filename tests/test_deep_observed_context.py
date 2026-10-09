from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import pytest
from tv_scan_studio.deep_export import (DeepExport, DeepExportError,
    observed_report_period, observed_report_currency, summarize_deep_export)


def report(range_="Sep 6, 2026, 20:00 — Sep 20, 2026, 20:00", zone="America/New_York", **properties):
    return DeepExport({}, {"Timezone": zone, **properties}, (), range_, "fixture-sha", 1)


def ms(year, month, day, hour=0, minute=0):
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def test_observed_export_range_exact_utc_boundary_no_plan_parameter():
    export = report()
    before = deepcopy(export)
    period = observed_report_period(export, "America/New_York")
    assert period == {"from_ms": ms(2026, 9, 7), "to_ms": ms(2026, 9, 21) - 1,
                      "end_exclusive_ms": ms(2026, 9, 21), "timezone": "UTC"}
    assert export == before


def test_day_only_end_is_inclusive_in_utc_not_request_copy():
    period = observed_report_period(report("Sep 7, 2026 — Sep 20, 2026", "Etc/UTC"), "Etc/UTC")
    assert period["from_ms"] == ms(2026, 9, 7)
    assert period["to_ms"] == ms(2026, 9, 21) - 1


def test_day_only_chart_timezone_preserves_real_offset():
    period = observed_report_period(report("Sep 7, 2026 — Sep 7, 2026", "Europe/Istanbul"), "Europe/Istanbul")
    assert period["from_ms"] == ms(2026, 9, 6, 21)
    assert period["end_exclusive_ms"] == ms(2026, 9, 7, 21)


def test_timezone_dst_transition_preserves_actual_duration():
    period = observed_report_period(report("Mar 7, 2026 — Mar 8, 2026"), "America/New_York")
    assert period["end_exclusive_ms"] - period["from_ms"] == 47 * 3600000


@pytest.mark.parametrize("range_", ["", "2026-01-01", "Sep 7, 2026 — broken", "Sep 20, 2026 — Sep 7, 2026",
    "Sep 7, 2026, 00:00 — Sep 7, 2026, 00:00", "Sep 7, 2026 — Sep 8, 2026, 00:00",
    "Nov 1, 2026, 01:30 — Nov 2, 2026, 00:00", "Mar 8, 2026, 02:30 — Mar 9, 2026, 00:00"])
def test_bad_or_ambiguous_observed_ranges_fail_closed(range_):
    with pytest.raises(DeepExportError):
        observed_report_period(report(range_), "America/New_York")


@pytest.mark.parametrize("zone", ["unknown/zone", "", None, "Europe/Istanbul"])
def test_missing_invalid_or_mismatched_report_timezone_rejected(zone):
    with pytest.raises(DeepExportError):
        observed_report_period(report(), zone)


@pytest.mark.parametrize("code", ["USD", "EUR", "AUD", "GBP", "NZD", "CAD", "CHF", "HKD",
    "JPY", "NOK", "SEK", "SGD", "TRY", "ZAR"])
def test_flattened_base_currency_has_no_authoritative_section(code):
    export = report(**{"Base currency": code})
    assert observed_report_currency(export) is None
    assert observed_report_currency(report(**{"BASE CURRENCY": code.lower()})) is None


@pytest.mark.parametrize("value", ["Default", "", "USD/EUR", "ABC", "US Dollars", "$", None, 123])
def test_unknown_currency_not_inferred(value):
    assert observed_report_currency(report(**{"Base currency": value, "Symbol": "OANDA:EURUSD", "Currency": "USD"})) is None


def test_trade_header_symbol_currency_and_capital_do_not_invent_report_currency():
    export = report(**{"Symbol": "OANDA:EURUSD", "Currency": "USD", "Initial capital": "100000 USD"})
    export = replace(export, trades=({"Net PnL USD": 123},))
    assert observed_report_currency(export) is None


def test_duplicate_case_insensitive_base_currency_is_ambiguous_even_if_same_value():
    assert observed_report_currency(report(**{"Base currency": "USD", "Base Currency": "USD"})) is None


def test_explicit_trade_currency_conflict_keeps_report_currency_unknown():
    export = replace(report(**{"Base currency": "TRY"}), trades=({"Net PnL USD": 123},))
    assert observed_report_currency(export) is None
    export = replace(export, properties={**export.properties, "Base currency": "USD"})
    assert observed_report_currency(export) is None


def test_pine_input_title_cannot_masquerade_as_currency_or_section():
    # Synthetic workbook-shaped fixture: parser intentionally preserves existing
    # flattened properties compatibility; it does not authenticate label ownership.
    tables = {
        "Performance": [["Net profit", 1, 1], ["Gross profit", 2], ["Gross loss", 1],
                        ["Max drawdown (intrabar)", 1, 1]],
        "Trades analysis": [["Total trades", 0], ["Percent profitable", None, 0]],
        "Trades": [["Trade number", "Type", "Date and time", "Net PnL USD"]],
        "Properties": [["Backtesting range", "Sep 7, 2026 — Sep 8, 2026"],
                       ["Symbol", "BIST:XU030D1!"], ["Timeframe", "15 minutes"],
                       ["Timezone", "Etc/UTC"], ["Strategy properties", None],
                       ["Base currency", "USD"], ["Inputs", None]],
    }
    export = summarize_deep_export(tables)
    assert export.properties["Base currency"] == "USD"  # Not deleted or invented.
    assert observed_report_currency(export) is None  # Never promoted to evidence.


@pytest.mark.parametrize("currency", ["USD", "EUR", "TRY"])
def test_exact_observed_performance_headers_identify_currency(currency):
    headers = ("", f"All {currency}", "All %", f"Long {currency}", "Long %", f"Short {currency}", "Short %")
    export = replace(report(), performance_headers=headers, performance_headers_provenance="performance_sheet_row1")
    assert observed_report_currency(export) == currency
    assert observed_report_currency(replace(export, performance_headers_provenance="unknown")) is None


@pytest.mark.parametrize("headers", [
    None, (), ("", "All USD", "All %"),
    ("", None, "All %", "Long USD", "Long %", "Short USD", "Short %"),
    ("", "All USD", "All %", "Long EUR", "Long %", "Short USD", "Short %"),
    ("", "All ABC", "All %", "Long ABC", "Long %", "Short ABC", "Short %"),
    ("", "All USD", "All USD", "Long USD", "Long %", "Short USD", "Short %"),
    ("USD", "All USD", "All %", "Long USD", "Long %", "Short USD", "Short %"),
    ("", "All usd", "All %", "Long USD", "Long %", "Short USD", "Short %"),
    ("", "All USD", "All %", "Long USD", "Long %", "Short USD", "Short %", "Other"),
])
def test_unknown_mixed_or_malformed_performance_headers_stay_unknown(headers):
    export = replace(report(**{"Base currency": "USD"}), performance_headers=headers,
                     performance_headers_provenance="performance_sheet_row1")
    assert observed_report_currency(export) is None


def test_exact_performance_evidence_conflicting_with_trade_unit_stays_unknown():
    headers = ("", "All TRY", "All %", "Long TRY", "Long %", "Short TRY", "Short %")
    export = replace(report(), performance_headers=headers, performance_headers_provenance="performance_sheet_row1",
                     trades=({"Net PnL USD": 123},))
    assert observed_report_currency(export) is None


def test_parser_retains_actual_performance_row_not_flattened_property():
    from test_deep_export import tables
    source = tables()
    headers = ["", "All USD", "All %", "Long USD", "Long %", "Short USD", "Short %"]
    source["Performance"].insert(0, headers)
    source["Properties"].append(["Base currency", "TRY"])
    export = summarize_deep_export(source)
    assert export.performance_headers == tuple(headers)
    assert export.performance_headers_provenance == "performance_sheet_row1"
    assert export.properties["Base currency"] == "TRY"
    assert observed_report_currency(export) == "USD"


@pytest.mark.parametrize("currency", ["USD", "TRY", "EUR"])
def test_native_monetary_header_selects_correct_trade_pnl_without_conversion(currency):
    from test_deep_export import tables
    from tv_scan_studio.deep_export import normalized_closed_trades
    source = tables()
    source["Performance"].insert(0, ["", f"All {currency}", "All %", f"Long {currency}", "Long %", f"Short {currency}", "Short %"])
    source["Trades"][0][-1] = f"Net PnL {currency}"
    export = summarize_deep_export(source)
    assert observed_report_currency(export) == currency
    assert export.trade_pnl_header == f"Net PnL {currency}"
    closed = normalized_closed_trades(export)
    assert [row["tp"]["v"] for row in closed] == [20.0, -2.09]


@pytest.mark.parametrize("trade_header", ["Net PnL TRY", "Net PnL EUR", "Net PnL ABC", "Net PnL try"])
def test_parser_rejects_unproven_or_conflicting_non_usd_units(trade_header):
    from test_deep_export import tables
    source = tables()
    source["Trades"][0][-1] = trade_header
    with pytest.raises(DeepExportError, match="para birim"):
        summarize_deep_export(source)
    source["Performance"].insert(0, ["", "All USD", "All %", "Long USD", "Long %", "Short USD", "Short %"])
    with pytest.raises(DeepExportError, match="para birim"):
        summarize_deep_export(source)


def test_parser_rejects_two_net_pnl_units_even_with_consistent_performance():
    from test_deep_export import tables
    source = tables()
    source["Performance"].insert(0, ["", "All USD", "All %", "Long USD", "Long %", "Short USD", "Short %"])
    source["Trades"][0].append("Net PnL TRY")
    with pytest.raises(DeepExportError, match="para birim"):
        summarize_deep_export(source)
