import time
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

import pytest

from tv_scan_studio.analytics import analyze_trades
from tv_scan_studio.deep_export import (DeepExportError, _sheet_rows,
                                        normalized_closed_trades,
                                        read_deep_export, summarize_deep_export,
                                        strategy_properties,
                                        verify_deep_export,
                                        verify_deep_input_values,
                                        verify_deep_property_scalars,
                                        wait_for_unique_fresh_xlsx,
                                        xlsx_download_baseline)


def tables():
    return {
        "Performance": [
            ["Net profit", 17.91, 0.02],
            ["Gross profit", 72.46],
            ["Gross loss", 54.55],
            ["Max drawdown (intrabar)", 28.72, 0.03],
        ],
        "Trades analysis": [
            ["Total trades", 2],
            ["Percent profitable", None, 50.0],
        ],
        "Trades": [
            ["Trade number", "Type", "Date and time", "Net PnL USD"],
            [1, "Entry long", 46275.09027777778, 20.0],
            [1, "Exit long", 46275.09375, 20.0],
            [2, "Entry short", 46283.118055555555, -2.09],
            [2, "Exit short", 46283.12291666667, -2.09],
        ],
        "Properties": [
            ["Backtesting range", "Sep 6, 2026, 20:00 — Sep 20, 2026, 20:00"],
            ["Symbol", "OANDA:XAUUSD"],
            ["Timeframe", "1 minute"],
            ["Initial capital", "100000"],
            ["Default order size", "2 contracts"],
            ["Commission", "0.01"],
            ["Slippage", "2 ticks"],
            ["Timezone", "America/New_York"],
        ],
    }


def write_minimal_xlsx(path):
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relationships = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    content = tables()
    names = list(content)
    workbook = (
        f'<workbook xmlns="{namespace}" xmlns:r="{relationships}"><sheets>'
        + "".join(f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
                  for index, name in enumerate(names, 1))
        + "</sheets></workbook>"
    )
    rels = (
        f'<Relationships xmlns="{package_rel}">'
        + "".join(f'<Relationship Id="rId{index}" Target="worksheets/sheet{index}.xml"/>'
                  for index in range(1, len(names) + 1))
        + "</Relationships>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        for index, name in enumerate(names, 1):
            rows = []
            for row_index, row in enumerate(content[name], 1):
                cells = []
                for column_index, value in enumerate(row):
                    if value is None:
                        continue
                    ref = f"{chr(ord('A') + column_index)}{row_index}"
                    if isinstance(value, str):
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
                    else:
                        cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml",
                f'<worksheet xmlns="{namespace}"><sheetData>{"".join(rows)}</sheetData></worksheet>',
            )


def test_deep_export_reconciles_metrics_trades_and_properties():
    report = summarize_deep_export(tables(), sha256="abc", mtime_ns=123)
    assert report.metrics == {
        "trades": 2, "profit_factor": 1.328323, "win_rate_pct": 50.0,
        "max_drawdown_pct": 0.03, "net_profit": 17.91, "net_profit_pct": 0.02,
    }
    assert report.properties["Commission"] == "0.01"
    assert len(report.trades) == 4
    assert report.sha256 == "abc" and report.mtime_ns == 123


def test_deep_export_reads_distinct_strategy_property_scalars():
    source = tables()
    source["Properties"][4][1] = "2 contracts"
    report = summarize_deep_export(source)
    observed = verify_deep_property_scalars(
        report, initial_capital=100000, position_size=2, slippage_ticks=2,
    )
    assert observed == strategy_properties(report)
    assert observed.commission_value == 0.01
    assert observed.default_order_unit == "contracts"


def test_deep_export_proves_changed_pine_input_values_by_unique_title():
    source = tables()
    source["Properties"].extend([
        ["Length", "4"], ["Enabled", "On"], ["Mode", "B"],
    ])
    pine = ('strategy("Scan")\n'
            'length = input.int(3, "Length")\n'
            'enabled = input.bool(false, "Enabled")\n'
            'mode = input.string("A", "Mode", options=["A", "B"])')
    result = verify_deep_input_values(
        summarize_deep_export(source), pine_source=pine,
        expected_inputs={"in_0": 4, "in_1": True, "in_2": "B"},
        changed_input_ids={"in_2", "in_0", "in_1"},
    )
    assert result == ("in_0", "in_1", "in_2")


def test_deep_export_rejects_stale_or_ambiguous_changed_input():
    source = tables()
    source["Properties"].append(["Length", "3"])
    report = summarize_deep_export(source)
    with pytest.raises(DeepExportError, match="değeri XLSX"):
        verify_deep_input_values(
            report, pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            expected_inputs={"in_0": 4}, changed_input_ids={"in_0"},
        )
    with pytest.raises(DeepExportError, match="tekil başlık"):
        verify_deep_input_values(
            report, pine_source=('strategy("Scan")\na=input.int(3,"Length")\n'
                                 'b=input.int(3,"Length")'),
            expected_inputs={"in_0": 3}, changed_input_ids={"in_0"},
        )
    with pytest.raises(DeepExportError, match="kimliği"):
        verify_deep_input_values(
            report, pine_source='strategy("Scan")\nlength=input.int(3,"Length")',
            expected_inputs={"in_4": 4}, changed_input_ids={"in_4"},
        )


@pytest.mark.parametrize("field,value,error", [
    ("Initial capital", "90000", "başlangıç sermayesi"),
    ("Default order size", "3 contracts", "emir büyüklüğü"),
    ("Default order size", "2 % of equity", "emir büyüklüğü"),
    ("Slippage", "3 ticks", "slippage"),
])
def test_deep_export_rejects_different_strategy_property_scalars(field, value, error):
    source = tables()
    source["Properties"][4][1] = "2 contracts"
    next(row for row in source["Properties"] if row[0] == field)[1] = value
    with pytest.raises(DeepExportError, match=error):
        verify_deep_property_scalars(
            summarize_deep_export(source), initial_capital=100000,
            position_size=2, slippage_ticks=2,
        )


def test_deep_export_rejects_nonfinite_expected_property_value():
    with pytest.raises(DeepExportError, match="geçersiz"):
        verify_deep_property_scalars(
            summarize_deep_export(tables()), initial_capital=float("nan"),
            position_size=2, slippage_ticks=2,
        )


def test_xlsx_closed_trades_pair_rows_and_convert_chart_local_serial_time():
    source = tables()
    source["Trades"] = [
        ["Trade number", "Type", "Date and time", "Net PnL USD", "Signal"],
        [1, "Exit long", 46275.09027777778, 20.0, "TP1 Hit"],
        [1, "Entry long", 46275.08541666667, 20.0, "Long [Daily] Try 1"],
        [2, "Exit short", 46275.09236111111, -2.09, "Stop"],
        [2, "Entry short", 46275.08541666667, -2.09, "Short [NY] Try 1"],
    ]
    result = normalized_closed_trades(summarize_deep_export(source))
    assert len(result) == 2
    assert result[0]["e"]["tp"] == "long"
    assert result[0]["e"]["c"] == "Long [Daily] Try 1"
    assert result[0]["tp"]["v"] == 20.0
    assert result[0]["x"]["tm"] > result[0]["e"]["tm"]
    assert result[0]["e"]["tm"] == 1789020180000
    assert "v" not in result[0]  # No intrabar equity evidence in this export.
    analysis = analyze_trades(result, 100000, "America/New_York")
    assert analysis["analyzed_trades"] == 2
    assert analysis["trade_analysis_net_profit"] == pytest.approx(17.91)
    assert analysis["risk_evidence_scope"] == "closed_trades_only"


@pytest.mark.parametrize("mutation,error", [
    (lambda rows: rows.pop(), "giriş veya çıkış"),
    (lambda rows: rows.__setitem__(2, [1, "Entry short", 46275.08541666667, 20.0]), "yönü"),
    (lambda rows: rows.__setitem__(2, [1, "Entry long", 46276.0, 20.0]), "önce"),
])
def test_xlsx_closed_trades_rejects_unpaired_or_conflicting_rows(mutation, error):
    source = tables()
    source["Trades"] = [
        ["Trade number", "Type", "Date and time", "Net PnL USD"],
        [1, "Exit long", 46275.09027777778, 20.0],
        [1, "Entry long", 46275.08541666667, 20.0],
        [2, "Exit short", 46275.09236111111, -2.09],
        [2, "Entry short", 46275.08541666667, -2.09],
    ]
    mutation(source["Trades"])
    report = summarize_deep_export(source)
    with pytest.raises(DeepExportError, match=error):
        normalized_closed_trades(report)


def test_xlsx_closed_trades_rejects_ambiguous_fall_back_time():
    source = tables()
    ambiguous = (datetime(2026, 11, 1, 1, 30) - datetime(1899, 12, 30)).total_seconds() / 86400
    source["Trades"] = [
        ["Trade number", "Type", "Date and time", "Net PnL USD"],
        [1, "Exit long", ambiguous, 20.0],
        [1, "Entry long", ambiguous, 20.0],
        [2, "Exit short", ambiguous, -2.09],
        [2, "Entry short", ambiguous, -2.09],
    ]
    with pytest.raises(DeepExportError, match="belirsiz"):
        normalized_closed_trades(summarize_deep_export(source))


def test_deep_export_rejects_missing_or_ambiguous_evidence():
    source = tables()
    del source["Properties"]
    with pytest.raises(DeepExportError, match="sayfaları eksik"):
        summarize_deep_export(source)
    source = tables()
    source["Trades"] = source["Trades"][:-1]
    with pytest.raises(DeepExportError, match="işlem listesi"):
        summarize_deep_export(source)
    source = tables()
    source["Performance"][0][1] = 30
    with pytest.raises(DeepExportError, match="uzlaşmıyor"):
        summarize_deep_export(source)
    source = tables()
    source["Properties"].append(["Symbol", "OTHER:XAUUSD"])
    with pytest.raises(DeepExportError, match="yineleniyor"):
        summarize_deep_export(source)


def test_xlsx_sheet_parser_handles_strings_numbers_and_rejects_formulas():
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    xml = f'''<worksheet xmlns="{namespace}"><sheetData><row r="1">
      <c r="A1" t="str"><v>Net profit</v></c>
      <c r="B1"><v>17.91</v></c>
      <c r="D1" t="inlineStr"><is><t>USD</t></is></c>
    </row></sheetData></worksheet>'''.encode()
    assert _sheet_rows(xml, []) == [["Net profit", 17.91, None, "USD"]]
    formula_xml = xml.replace(b"<v>17.91</v>", b"<f>1+1</f><v>2</v>")
    with pytest.raises(DeepExportError, match="formül"):
        _sheet_rows(formula_xml, [])


def test_read_deep_export_parses_workbook_and_rejects_stale_file(tmp_path):
    path = tmp_path / "deep.xlsx"
    write_minimal_xlsx(path)
    modified = path.stat().st_mtime_ns
    report = read_deep_export(path, downloaded_after_ns=modified - 1)
    assert report.metrics["trades"] == 2
    assert report.properties["Symbol"] == "OANDA:XAUUSD"
    assert len(report.sha256) == 64
    with pytest.raises(DeepExportError, match="Yeni TradingView XLSX"):
        read_deep_export(path, downloaded_after_ns=modified + 1)


def test_fresh_xlsx_claim_ignores_old_file_and_requires_one_stable_new_file(tmp_path):
    old = tmp_path / "old.xlsx"
    with zipfile.ZipFile(old, "w") as archive:
        archive.writestr("old", "data")
    baseline = xlsx_download_baseline(tmp_path)
    started_ns = time.time_ns()
    new = tmp_path / "report.xlsx"
    with zipfile.ZipFile(new, "w") as archive:
        archive.writestr("new", "data")
    assert wait_for_unique_fresh_xlsx(
        tmp_path, baseline=baseline, started_ns=started_ns,
        timeout=1, poll_interval=0.01,
    ) == new


def test_fresh_xlsx_claim_fails_closed_on_ambiguous_downloads(tmp_path):
    baseline = xlsx_download_baseline(tmp_path)
    started_ns = time.time_ns()
    for name in ("first.xlsx", "second.xlsx"):
        with zipfile.ZipFile(tmp_path / name, "w") as archive:
            archive.writestr("data", name)
    with pytest.raises(DeepExportError, match="birden fazla"):
        wait_for_unique_fresh_xlsx(
            tmp_path, baseline=baseline, started_ns=started_ns,
            timeout=1, poll_interval=0.01,
        )


def test_fresh_xlsx_claim_rejects_old_or_incomplete_file(tmp_path):
    baseline = xlsx_download_baseline(tmp_path)
    started_ns = time.time_ns()
    incomplete = tmp_path / "incomplete.xlsx"
    incomplete.write_bytes(b"not a complete XLSX")
    with pytest.raises(DeepExportError, match="tamamlanmadı"):
        wait_for_unique_fresh_xlsx(
            tmp_path, baseline=baseline, started_ns=started_ns,
            timeout=0.04, poll_interval=0.01,
        )


@pytest.mark.parametrize("timeframe", ["1", "1m", "2", "2m"])
def test_deep_export_utc_dates_and_ui_metrics_match_live_worker(timeframe):
    report = summarize_deep_export(tables(), sha256="abc", mtime_ns=123)
    if timeframe in {"2", "2m"}:
        report.properties["Timeframe"] = "2 minutes"
    trades = verify_deep_export(
        report, symbol="OANDA:XAUUSD", timeframe=timeframe,
        date_range={"from": "2026-09-07", "to": "2026-09-20"},
        chart_timezone="America/New_York",
        cost_assumptions={"initial_capital": 100000, "position_size": 2,
                          "slippage": 2, "commission_value": 0.01},
        ui_metrics={"trades": 2, "net_profit": 17.91, "profit_factor": 1.328,
                    "win_rate_pct": 50, "max_drawdown_pct": 0.03},
        ui_date_label="Sep 7, 2026 — Sep 20, 2026", ui_update_pending=False,
    )
    assert len(trades) == 2
    assert sum(trade["tp"]["v"] for trade in trades) == pytest.approx(report.metrics["net_profit"])


@pytest.mark.parametrize("change,error", [
    ({"symbol": "OANDA:EURUSD"}, "sembolü"),
    ({"timeframe": "15"}, "zaman dilimi"),
    ({"date_range": {"from": "2026-09-08", "to": "2026-09-20"}}, "tarih aralığı"),
    ({"chart_timezone": "Etc/UTC"}, "saat dilimi"),
    ({"chart_timezone": "America/Toronto"}, "saat dilimi"),
    ({"ui_metrics": {"trades": 2, "net_profit": 999, "profit_factor": 1.328,
                     "win_rate_pct": 50, "max_drawdown_pct": 0.03}}, "net_profit"),
    ({"ui_metrics": None}, "metrikleri okunmadı"),
    ({"ui_date_label": "Sep 8, 2026 — Sep 20, 2026"}, "tarih aralığı"),
    ({"ui_date_label": None}, "tarih etiketi"),
    ({"ui_update_pending": True}, "henüz güncel"),
    ({"ui_update_pending": None}, "henüz güncel"),
    ({"ui_update_pending": 0}, "henüz güncel"),
    ({"ui_metrics": {"trades": 2, "net_profit": float("nan"), "profit_factor": 1.328,
                     "win_rate_pct": 50, "max_drawdown_pct": 0.03}}, "metriği eksik"),
    ({"cost_assumptions": {}}, "beklentileri eksik"),
    ({"cost_assumptions": {"initial_capital": 100000, "position_size": 1,
                            "slippage": 2, "commission_value": 0.01}}, "emir büyüklüğü"),
    ({"cost_assumptions": {"initial_capital": 100000, "position_size": 2,
                            "slippage": 3, "commission_value": 0.01}}, "slippage"),
    ({"cost_assumptions": {"initial_capital": 100000, "position_size": 2,
                            "slippage": 2, "commission_value": 0.02}}, "komisyon sayısı"),
])
def test_deep_export_rejects_wrong_task_or_stale_ui(change, error):
    report = summarize_deep_export(tables(), sha256="abc", mtime_ns=123)
    expected = {"symbol": "OANDA:XAUUSD", "timeframe": "1",
                "date_range": {"from": "2026-09-07", "to": "2026-09-20"},
                "chart_timezone": "America/New_York",
                "cost_assumptions": {"initial_capital": 100000, "position_size": 2,
                                     "slippage": 2, "commission_value": 0.01},
                "ui_metrics": {"trades": 2, "net_profit": 17.91, "profit_factor": 1.328,
                               "win_rate_pct": 50, "max_drawdown_pct": 0.03},
                "ui_date_label": "Sep 7, 2026 — Sep 20, 2026",
                "ui_update_pending": False}
    expected.update(change)
    with pytest.raises(DeepExportError, match=error):
        verify_deep_export(report, **expected)


def test_deep_export_rejects_broken_trade_pairs_even_when_headline_metrics_match():
    source = tables()
    source["Trades"] = [row for row in source["Trades"]
                        if not (row[0] == 1 and row[1] == "Entry long")]
    report = summarize_deep_export(source, sha256="abc", mtime_ns=123)
    with pytest.raises(DeepExportError, match="giriş veya çıkış"):
        verify_deep_export(
            report, symbol="OANDA:XAUUSD", timeframe="1",
            date_range={"from": "2026-09-07", "to": "2026-09-20"},
            chart_timezone="America/New_York",
            cost_assumptions={"initial_capital": 100000, "position_size": 2,
                              "slippage": 2, "commission_value": 0.01},
            ui_metrics={"trades": 2, "net_profit": 17.91, "profit_factor": 1.328,
                        "win_rate_pct": 50, "max_drawdown_pct": 0.03},
            ui_date_label="Sep 7, 2026 — Sep 20, 2026", ui_update_pending=False,
        )
