import copy
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import pytest
from PySide6 import QtCore, QtWidgets
from tv_scan_studio.comparison import build_comparison, period_summary
from tv_scan_studio.storage import Store
from tv_scan_studio.app import StudioWindow


def record(value=8):
    return {"task_id": value, "task_key": str(value), "verified": True,
        "source_snapshot": 'strategy("EMA")\nn=input.int(8,"Fast EMA")',
        "source_provenance": "claim_snapshot", "warning_state": "unknown",
        "payload": {"symbol": "BIST:XU030D1!", "timeframe": "15", "inputs": {"in_0": value},
                    "date_range": {"from": "2026-09-01", "to": "2026-09-30"},
                    "costs": {"assumptions": {"initial_capital": 100000}}},
        "evidence": {"symbol": "BIST:XU030D1!", "timeframe": "15", "period": {"from": 1, "to": 2}, "inputs": {"in_0": value},
                     "report_currency": "TRY", "cost_verification_scope": "strategy_properties_ui_spread_unverified"},
        "classification": "hassas", "metrics": {"profit_factor": 1.5}}


def model(rows):
    return build_comparison(SimpleNamespace(result_history=lambda _id: []), rows)


@pytest.mark.parametrize("count", [0, 1, 6])
def test_comparison_enforces_two_to_five_results(count):
    with pytest.raises(ValueError, match="2–5"):
        model([record(value) for value in range(count)])


def test_inputs_readable_warning_unknown_and_model_is_readonly():
    rows = [record(), record(9)]
    before = copy.deepcopy(rows)
    comparison = model(rows)
    assert comparison["differences"] == comparison["missing"] == []
    assert ("Ayar: Fast EMA", ["8", "9"]) in comparison["lines"]
    assert ("TradingView uyarısı", ["Bilinmiyor", "Bilinmiyor"]) in comparison["lines"]
    assert ("Kâr faktörü (PF)", ["1.5", "1.5"]) in comparison["lines"]
    assert ("Strateji kaynağı", ["EMA (kaynak 1)", "EMA (kaynak 1)"]) in comparison["lines"]
    assert ("Maliyet (plan)", ["Sermaye: 100000", "Sermaye: 100000"]) in comparison["lines"]
    assert "kazanç garantisi" in comparison["warning"]
    assert rows == before


def test_five_columns_and_mismatched_actual_chart_context():
    rows = [record(value) for value in range(8, 13)]
    rows[-1]["evidence"]["symbol"] = "OANDA:EURUSD"
    rows[-1]["evidence"]["timeframe"] = "60"
    comparison = model(rows)
    assert all(len(values) == 5 for _label, values in comparison["lines"])
    assert {"grafikteki sembol", "grafikteki zaman dilimi"} <= set(comparison["differences"])


def test_requested_inputs_are_not_substituted_for_actual_input_evidence():
    rows = [record(), record(9)]
    rows[0]["evidence"]["inputs"] = {"in_0": 7}
    rows[1]["evidence"].pop("inputs")
    comparison = model(rows)
    assert "uygulanan ayarlar" in comparison["missing"]
    assert "planlanan/grafikteki ayar uyuşmazlığı" in comparison["differences"]
    assert ("Grafikteki ayar: Fast EMA", ["7", "Kanıt yok"]) in comparison["lines"]


def test_legacy_deep_requested_period_is_not_observed_comparison_context():
    rows = [record(), record(9)]
    for row in rows:
        row["evidence"].update(report_source="deep_xlsx", period=row["payload"]["date_range"])
    comparison = model(rows)
    assert "rapor dönemi" in comparison["missing"]
    assert dict(comparison["lines"])["Dönem (rapor)"] == ["Kanıt yok", "Kanıt yok"]


def test_deep_comparison_uses_export_observed_not_requested_period():
    rows = [record(), record(9)]
    observed = {"from": "2026-09-10", "to": "2026-09-20"}
    for row in rows:
        row["evidence"].update(report_source="deep_xlsx", period=row["payload"]["date_range"],
            report_period_provenance="deep_export_observed", report_period=observed)
    comparison = model(rows)
    assert "rapor dönemi" not in comparison["missing"]
    assert comparison["raw_lines"]["Dönem (rapor)"] == [observed, observed]
    assert dict(comparison["lines"])["Dönem (rapor)"] == [period_summary(observed)] * 2


def test_period_display_keeps_exact_raw_context_and_explicit_utc():
    rows = [record(), record(9)]
    rows[0]["evidence"]["period"] = {"dateRange": {"backtest": {"from": 1790899200000, "to": 1790985600001}}}
    comparison = model(rows)
    assert dict(comparison["lines"])["Dönem (plan)"] == ["01.09.2026\n– 30.09.2026"] * 2
    assert "03.10.2026\n00:00:00.001 UTC" in dict(comparison["lines"])["Dönem (rapor)"][0]
    assert comparison["raw_lines"]["Dönem (rapor)"][0]["to"] == 1790985600001
    assert "rapor dönemi" in comparison["differences"]
    assert period_summary({"from_ms": 0, "to_ms": 1000}) == "01.01.1970\n00:00:00 UTC\n– 01.01.1970\n00:00:01 UTC"


@pytest.mark.parametrize("value", [True, float("inf"), float("nan"), 10**100, "not-a-date", "2026-02-30"])
def test_unreadable_period_is_not_replaced_by_a_plausible_date(value):
    assert "Biçim okunamadı" in period_summary({"from": value, "to": "2026-09-30"})
    assert period_summary(None) == "Kanıt yok"
    assert "Belirtilmedi" in period_summary({"from": "2026-09-01"})


@pytest.mark.parametrize("dimension,label", [
    ("source", "strateji kaynağı"), ("symbol", "sağlayıcı"), ("timeframe", "zaman dilimi"),
    ("period", "rapor dönemi"), ("planned_period", "planlanan dönem"),
    ("currency", "para birimi"), ("capital", "sermaye"),
])
def test_context_differences_are_visible(dimension, label):
    rows = [record(), record(9)]
    changed = rows[1]
    if dimension == "source":
        changed["source_snapshot"] += "\n// different source"
    elif dimension == "symbol":
        changed["payload"]["symbol"] = "OANDA:EURUSD"
        changed["evidence"]["symbol"] = "OANDA:EURUSD"
    elif dimension == "timeframe":
        changed["payload"]["timeframe"] = changed["evidence"]["timeframe"] = "60"
    elif dimension == "period":
        changed["evidence"]["period"]["to"] = 3
    elif dimension == "planned_period":
        changed["payload"]["date_range"]["to"] = "2026-10-01"
    elif dimension == "currency":
        changed["evidence"]["report_currency"] = "USD"
    else:
        changed["payload"]["costs"]["assumptions"]["initial_capital"] = 200000
    comparison = model(rows)
    assert label in comparison["differences"]
    assert "doğrudan adil karşılaştırma değildir" in comparison["warning"]


def test_equal_missing_context_does_not_claim_equal_proof():
    rows = [record(), record(9)]
    for row in rows:
        row.pop("source_snapshot")
        row["evidence"] = {}
    comparison = model(rows)
    assert {"strateji kaynağı", "rapor dönemi", "para birimi", "sermaye", "uygulanan maliyetler"} <= set(comparison["missing"])
    assert "Aynı koşullarda test edildiği söylenemez" in comparison["warning"]
    assert all("Ayar: Fast EMA" != label for label, _ in comparison["lines"])


def test_comparison_uses_frozen_source_not_current_project(tmp_path):
    store = Store(tmp_path / "frozen.db")
    project = store.create_project("EMA", 'strategy("EMA")\nn=input.int(8,"Original EMA")')
    for value in (8, 9):
        store.enqueue(project, str(value), {"symbol": "BIST:XU030D1!", "timeframe": "15", "inputs": {"in_0": value}})
        task = store.claim_next(1, [project])
        store.complete(task.id, 1, {"profit_factor": 1.5}, "hassas", verified=True)
    rows = store.results(project)
    before = copy.deepcopy(rows)
    with store.connect() as connection:
        connection.execute("UPDATE projects SET pine_source=? WHERE id=?",
            ('strategy("Other")\nx=input.int(100,"Wrong current title")', project))
    comparison = build_comparison(store, rows)
    assert ("Ayar: Original EMA", ["8", "9"]) in comparison["lines"]
    assert "Wrong current title" not in str(comparison["lines"])
    assert store.results(project) == before


def test_comparison_popup_has_readonly_help_and_clean_lifetime(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "help.db"))
    studio.worker_timer.stop()
    rows = [record(), record(9)]
    monkeypatch.setattr(studio, "selected_result_rows", lambda: rows)
    observed = []
    def inspect(dialog):
        dialog.show()
        app.processEvents()
        scope = dialog.help_registry
        assert not scope.missing_controls(dialog)
        assert scope.active_tour is not None
        scope.active_tour.skip.click()
        assert studio.store.app_settings()["help_tour_viewer.comparison_completed"]
        scope.specs["viewer.comparison.guide"].target.click()
        tour = scope.active_tour
        table = scope.specs["viewer.comparison.table"].target
        assert table.editTriggers() == QtWidgets.QAbstractItemView.NoEditTriggers
        assert table.horizontalHeaderItem(0).text() == "Test 1"
        assert all(table.verticalHeaderItem(index).toolTip() for index in range(table.rowCount()))
        assert all(table.horizontalHeaderItem(index).toolTip() for index in range(table.columnCount()))
        index = next(index for index in range(table.rowCount()) if table.verticalHeaderItem(index).text() == "Ayar: Fast EMA")
        assert table.item(index, 0).background().color().name() == "#fff3d6"
        assert table.item(3, 0).text() == "15 dakika"
        period_index = next(index for index in range(table.rowCount()) if table.verticalHeaderItem(index).text() == "Dönem (plan)")
        assert table.item(period_index, 0).text() == "01.09.2026\n– 30.09.2026"
        assert '"from": "2026-09-01"' in table.item(period_index, 0).toolTip()
        dialog.accept()
        assert scope.active_tour is None and not tour.timer.isActive()
        observed.append(True)
        return QtWidgets.QDialog.Accepted
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        studio.compare_selected_results()
        assert observed == [True]
        assert not studio.store.projects() and studio.supervisor is None
    finally:
        studio.window.close()
        app.processEvents()


def test_raw_period_difference_is_highlighted_even_when_display_matches(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "raw-period.db"))
    studio.worker_timer.stop()
    rows = [record(), record(9)]
    for row, note in zip(rows, ("original", "different")):
        row["payload"]["date_range"]["extra_scope"] = note
    monkeypatch.setattr(studio, "selected_result_rows", lambda: rows)
    def inspect(dialog):
        table = dialog.help_registry.specs["viewer.comparison.table"].target
        index = next(index for index in range(table.rowCount()) if table.verticalHeaderItem(index).text() == "Dönem (plan)")
        assert table.item(index, 0).text() == table.item(index, 1).text()
        assert table.item(index, 0).background().color().name() == "#fff3d6"
        assert "original" in table.item(index, 0).toolTip()
        assert "different" in table.item(index, 1).toolTip()
        return QtWidgets.QDialog.Rejected
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        studio.compare_selected_results()
    finally:
        studio.window.close()
        app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


@pytest.mark.parametrize("count,enabled", [(1, False), (2, True), (5, True), (6, False)])
def test_selection_limits_button_and_direct_slot(tmp_path, monkeypatch, count, enabled):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "limit.db"))
    studio.worker_timer.stop()
    rows = [record(value) for value in range(count)]
    monkeypatch.setattr(studio, "selected_result_rows", lambda: rows)
    monkeypatch.setattr(studio.results_table, "selectionModel", lambda: SimpleNamespace(selectedRows=lambda: rows))
    messages, dialogs = [], []
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *_args: messages.append(_args[-1]))
    monkeypatch.setattr(QtWidgets.QDialog, "exec", lambda _dialog: dialogs.append(True) or QtWidgets.QDialog.Rejected)
    try:
        studio.update_result_actions()
        assert studio.result_compare.isEnabled() == enabled
        studio.compare_selected_results()
        assert bool(dialogs) == enabled
        assert bool(messages) != enabled
        assert not studio.store.projects() and studio.supervisor is None
    finally:
        studio.window.close()
        app.processEvents()
