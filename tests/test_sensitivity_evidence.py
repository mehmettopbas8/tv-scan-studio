from copy import deepcopy
import pytest
from tv_scan_studio.storage import Store
from tv_scan_studio.planner import ScanPlan, enqueue_plan
from tv_scan_studio.sensitivity import build_sensitivity, verified_no_effect_inputs
from tv_scan_studio.sensitivity import _proof

CODE = 'strategy("EMA")\na=input.int(8,"Fast EMA")\nb=input.int(21,"Slow EMA")'


def setup(tmp_path, change=None):
    store = Store(tmp_path / "sensitivity.db")
    project = store.create_project("EMA", CODE)
    plan = ScanPlan("study", ["BIST:XU030D1!"], ["15"], {"in_0": [7, 8, 9], "in_1": [21]},
                    date_range={"from": "2026-01-01", "to": "2026-03-31"},
                    costs={"assumptions": {"initial_capital": 100000, "commission_value": .1}})
    enqueue_plan(store, project, plan)
    while task := store.claim_next(1, [project]):
        evidence = {"symbol": task.payload["symbol"], "timeframe": "15", "inputs": task.payload["inputs"],
                    "period": {"from": 1767225600000, "to": 1774915200000},
                    "report_currency": "TRY", "cost_verification_scope": "strategy_properties_ui_spread_unverified",
                    "tradingview_warning_state": "unknown"}
        if change and task.payload["inputs"]["in_0"] == 9:
            change(evidence)
        store.complete(task.id, 1, {"trades": 80, "profit_factor": 1.5, "max_drawdown_pct": 2, "net_profit": 100},
                       "hassas", verified=True, evidence=evidence)
    return store, project, store.results(project)


def test_default_uses_latest_immutable_proof_and_is_readonly(tmp_path):
    store, project, rows = setup(tmp_path)
    original = deepcopy((rows, store.tasks(project), store.scan_runs(project)))
    model = build_sensitivity(store, rows[0], rows)
    assert len(model["neighbors"]) == 2 and model["excluded"] == []
    assert all(item["row"]["source_provenance"] == "claim_snapshot" for item in model["neighbors"])
    assert all(item["row"]["warning_label"] == "Bilinmiyor" for item in model["neighbors"])
    assert verified_no_effect_inputs(store, rows) == {"in_0": 3}
    assert (store.results(project), store.tasks(project), store.scan_runs(project)) == original


@pytest.mark.parametrize("field,fragment", [("period", "Rapor dönemi"), ("symbol", "sembol"),
    ("timeframe", "zaman dilimi"), ("report_currency", "para birimi"),
    ("cost_verification_scope", "maliyet"), ("inputs", "Pine ayarları")])
def test_missing_evidence_is_excluded_not_equal(tmp_path, field, fragment):
    store, _, rows = setup(tmp_path, lambda evidence: evidence.pop(field))
    model = build_sensitivity(store, rows[0], rows)
    assert len(model["neighbors"]) == 1
    assert any(fragment in reason for exclusion in model["excluded"] for reason in exclusion["reasons"])
    assert verified_no_effect_inputs(store, rows) == {}


@pytest.mark.parametrize("field,value", [("report_currency", "USD"), ("timeframe", "60"),
    ("symbol", "OANDA:EURUSD"), ("inputs", {"in_0": 1, "in_1": 21}),
    ("period", {"from": 1767225600000, "to": 1774915200001})])
def test_different_observed_context_or_millisecond_period_excluded(tmp_path, field, value):
    store, _, rows = setup(tmp_path, lambda evidence: evidence.__setitem__(field, value))
    model = build_sensitivity(store, rows[0], rows)
    assert len(model["neighbors"]) == 1 and len(model["excluded"]) == 1


def test_current_invalidated_result_cannot_reuse_verified_history(tmp_path):
    store, project, rows = setup(tmp_path)
    with store.connect() as connection:
        connection.execute("UPDATE results SET verified=0 WHERE task_id=?", (rows[-1]["task_id"],))
    model = build_sensitivity(store, rows[0], rows)
    assert len(model["neighbors"]) == 1
    assert "güncel ve doğrulanmış" in model["excluded"][0]["reasons"][0]
    assert store.result_history(rows[-1]["task_id"])[-1]["verified"] == 1


def test_source_project_edits_do_not_replace_frozen_source(tmp_path):
    store, project, rows = setup(tmp_path)
    with store.connect() as connection:
        connection.execute("UPDATE projects SET pine_source=? WHERE id=?", (CODE + '\n// modified', project))
    assert len(build_sensitivity(store, rows[0], rows)["neighbors"]) == 2


def test_running_new_attempt_does_not_reuse_previous_evidence(tmp_path):
    store, _, rows = setup(tmp_path)
    with store.connect() as connection:
        connection.execute("UPDATE tasks SET status='running',attempts=attempts+1 WHERE id=?", (rows[-1]["task_id"],))
    assert len(build_sensitivity(store, rows[0], rows)["neighbors"]) == 1


def test_report_outside_requested_period_excluded(tmp_path):
    store, _, rows = setup(tmp_path, lambda evidence: evidence.__setitem__("period", {"from": 1, "to": 2}))
    assert "dönemin dışında" in build_sensitivity(store, rows[0], rows)["excluded"][0]["reasons"][0]


def test_nonfinite_stale_ui_value_does_not_crash(tmp_path):
    store, _, rows = setup(tmp_path)
    anchor = deepcopy(rows[0])
    anchor["metrics"]["net_profit"] = float("nan")
    assert build_sensitivity(store, anchor, rows)["anchor"] is None


@pytest.mark.parametrize("dimension", ["source", "provider", "timeframe", "capital", "costs", "planned_period", "other_input"])
def test_proven_but_different_conditions_cannot_be_neighbors(tmp_path, dimension):
    store, project, rows = setup(tmp_path)
    symbol = "OANDA:EURUSD" if dimension == "provider" else "BIST:XU030D1!"
    timeframe = "60" if dimension == "timeframe" else "15"
    costs = {"assumptions": {"initial_capital": 200000 if dimension == "capital" else 100000,
                             "commission_value": .2 if dimension == "costs" else .1}}
    dates = {"from": "2025-12-01" if dimension == "planned_period" else "2026-01-01", "to": "2026-03-31"}
    plan = ScanPlan("study", [symbol], [timeframe], {"in_0": [10], "in_1": [22 if dimension == "other_input" else 21]},
                    date_range=dates, costs=costs)
    if dimension == "source":
        with store.connect() as connection:
            connection.execute("UPDATE projects SET pine_source=? WHERE id=?", (CODE + '\n// other source', project))
    enqueue_plan(store, project, plan, new_run=True)
    task = store.claim_next(1, [project])
    store.complete(task.id, 1, rows[0]["metrics"], "hassas", verified=True,
        evidence={"symbol": symbol, "timeframe": timeframe, "inputs": task.payload["inputs"],
                  "period": rows[0]["evidence"]["period"], "report_currency": "TRY",
                  "cost_verification_scope": "strategy_properties_ui_spread_unverified"})
    model = build_sensitivity(store, rows[0], store.results(project))
    assert len(model["neighbors"]) == 2
    assert model["excluded"][0]["task_id"] == task.id
    assert "farklı" in model["excluded"][0]["reasons"][0]


def test_missing_history_never_falls_back_to_supplied_verified_projection(tmp_path):
    store, _, rows = setup(tmp_path)
    forged = deepcopy(rows[0])
    forged["task_id"] = 999999
    model = build_sensitivity(store, rows[0], [*rows, forged])
    assert len(model["neighbors"]) == 2
    assert model["excluded"] == [{"task_id": 999999, "reasons": ["Değişmez sonuç geçmişi bulunamadı."]}]


@pytest.mark.parametrize("key,value", [("profit_factor", float("nan")), ("net_profit", float("inf")),
    ("trades", -1), ("trades", True), ("trades", 1.5), ("max_drawdown_pct", -1), ("profit_factor", None)])
def test_bad_core_metric_is_not_valid_sensitivity_evidence(tmp_path, key, value):
    store, _, rows = setup(tmp_path)
    record = store.result_history(rows[0]["task_id"])[-1]
    record.update(current_verified=True, current_attempt=record["attempt_number"], task_status="done")
    record["metrics"][key] = value
    assert any("metrikleri" in reason for reason in _proof(record)[1])


def test_deep_xlsx_requested_dates_are_not_observed_report_proof(tmp_path):
    def surrogate(evidence):
        evidence.update(report_source="deep_xlsx", period={"from": "2026-01-01", "to": "2026-03-31"})
    store, _, rows = setup(tmp_path, surrogate)
    model = build_sensitivity(store, rows[0], rows)
    assert len(model["neighbors"]) == 1
    assert any("istenen tarih" in reason for reason in model["excluded"][0]["reasons"])


def test_deep_xlsx_explicit_observed_export_period_accepted(tmp_path):
    def observed(evidence):
        evidence.update(report_source="deep_xlsx", report_period=deepcopy(evidence["period"]),
                        report_period_provenance="deep_export_observed")
        evidence["period"] = {"from": "2026-01-01", "to": "2026-03-31"}
    store, _, rows = setup(tmp_path, observed)
    assert len(build_sensitivity(store, rows[0], rows)["neighbors"]) == 2


def test_different_cost_proof_scope_is_not_equal(tmp_path):
    store, _, rows = setup(tmp_path, lambda evidence: evidence.__setitem__(
        "cost_verification_scope", "strategy_properties_scalars_only"))
    model = build_sensitivity(store, rows[0], rows)
    assert len(model["neighbors"]) == 1
    assert "maliyet doğrulama kapsamı" in model["excluded"][0]["reasons"][0]


@pytest.mark.parametrize("provenance", ["planned", "requested", "requested_dates"])
def test_explicit_planned_surrogates_rejected(tmp_path, provenance):
    store, _, rows = setup(tmp_path, lambda evidence: evidence.__setitem__("report_period_provenance", provenance))
    assert len(build_sensitivity(store, rows[0], rows)["neighbors"]) == 1


def test_selected_projection_change_requires_refresh(tmp_path):
    store, _, rows = setup(tmp_path)
    stale = deepcopy(rows[0])
    stale["metrics"]["net_profit"] = 200
    model = build_sensitivity(store, stale, rows)
    assert model["anchor"] is None and model["neighbors"] == []
    assert "listeyi yenileyip" in model["excluded"][-1]["reasons"][0]


@pytest.mark.parametrize("state,label", [("present", "Var"), ("absent", "Yok"), ("unknown", "Bilinmiyor")])
def test_warning_state_is_never_inferred(tmp_path, state, label):
    store, _, rows = setup(tmp_path, lambda evidence: evidence.__setitem__("tradingview_warning_state", state))
    model = build_sensitivity(store, rows[0], rows)
    assert model["neighbors"][-1]["row"]["warning_label"] == label


@pytest.mark.parametrize("period", [{}, {"from": None, "to": None}, {"from": True, "to": False},
    {"from": float("inf"), "to": float("inf")}, {"from": 2, "to": 1}, {"dateRange": None}])
def test_invalid_period_excluded_with_reason_without_crash(tmp_path, period):
    store, _, rows = setup(tmp_path, lambda evidence: evidence.__setitem__("period", period))
    model = build_sensitivity(store, rows[0], rows)
    assert len(model["neighbors"]) == 1
    assert "Rapor dönemi" in model["excluded"][0]["reasons"][0]
