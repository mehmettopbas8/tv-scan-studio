import hashlib
import json
from pathlib import Path

import pytest

from tv_scan_studio.research import (describe_session_choice, iter_successful_research_records, load_catalog,
                                     provider_check_tasks, with_provider_status)
from tv_scan_studio.storage import Store


pytestmark = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "src/tv_scan_studio/data/ftmo_session_20260923.json").is_file(),
    reason="Optional private research catalog is not bundled",
)


def test_seven_successful_export_rows_keep_evidence_and_costs():
    rows = list(iter_successful_research_records(load_catalog()))
    assert len(rows) == 7
    assert all(row["classification"] == "ağır maliyet başarılı" for row in rows)
    assert all(row["payload"]["costs"]["commission_pct"] == .04 for row in rows)
    assert all(row["evidence"]["alternative_provider"] == "pending" for row in rows)
    assert all(row["evidence"]["forward"] == "not_started" for row in rows)


def test_research_session_names_explain_source_codes():
    records = load_catalog()["records"]
    labels = [describe_session_choice(record) for record in records]
    assert all("Ana:" in label and "Makro:" in label for label in labels)
    assert any("Özel: C7" in label for label in labels)


def test_catalog_keeps_seven_distinct_cost_passes_without_provider_claim():
    catalog = load_catalog()
    records = catalog["records"]
    assert catalog["session_tests"] == {"planned": 33075, "valid": 32923,
                                         "failed": 152, "moderate_passes": 501}
    assert catalog["heavy_tests"] == {"valid": 501, "passes": 7}
    assert len(records) == len({row["id"] for row in records}) == 7
    assert {row["candidate"] for row in records} == {"DE30EUR", "NAS100USD"}
    assert all(row["evidence"]["alternative_provider"] == "pending" for row in records)
    assert {round(row["coverage_days"]) for row in records} == {107, 387}
    assert all(row["heavy_metrics"]["trades"] >= 60 and row["heavy_metrics"]["pf"] >= 1.4
               and row["heavy_metrics"]["win"] >= 40 and row["heavy_metrics"]["dd"] < 5
               for row in records)


def test_provider_tasks_preserve_exact_period_and_reject_mixed_symbols():
    catalog = load_catalog()
    record = catalog["records"][0]
    source = "source used by validated mapping"
    project = {"pine_source": source, "pine_hash": hashlib.sha256(source.encode()).hexdigest()}
    adapted = {**catalog, "mapping_source_sha256": project["pine_hash"],
               "strategy_title": "Example"}
    project["pine_source"] = 'strategy("Example")'
    project["pine_hash"] = hashlib.sha256(project["pine_source"].encode()).hexdigest()
    adapted["mapping_source_sha256"] = project["pine_hash"]
    adapted["records"] = [{**record, "input_titles": {}}]
    tasks = provider_check_tasks(adapted, [record["id"]], project, "study", "CAPITALCOM:GER40")
    assert len(tasks) == 1
    payload = tasks[0][1]
    assert payload["symbol"] == "CAPITALCOM:GER40"
    assert payload["date_range"]["from_ms"] == record["period"]["dateRange"]["backtest"]["from"]
    assert payload["criteria"]["max_drawdown_pct_exclusive"] == 5
    assert payload["research_source_id"] == record["id"]
    with pytest.raises(ValueError, match="OANDA dışındaki"):
        provider_check_tasks(adapted, [record["id"]], project, "study", "OANDA:DE30EUR")


def test_provider_evidence_tracks_new_task_without_rewriting_historical_result(tmp_path):
    catalog = load_catalog()
    source_id = catalog["records"][0]["id"]
    store = Store(tmp_path / "studio.db")
    project_id = store.create_project("Research", 'strategy("Research")')
    store.enqueue(project_id, "provider-1", {
        "research_source_id": source_id, "validation_stage": "provider_check",
        "symbol": "CAPITALCOM:GER40",
    })
    queued = with_provider_status(catalog, store.research_provider_status(project_id))
    assert queued["records"][0]["evidence"]["alternative_provider"] == "queued"
    task = store.claim_next(1)
    store.complete(task.id, 1, {"profit_factor": 1.5}, "hassas", verified=True)
    passed = with_provider_status(catalog, store.research_provider_status(project_id))
    assert passed["records"][0]["evidence"]["alternative_provider"] == "passed"
    assert catalog["records"][0]["evidence"]["alternative_provider"] == "pending"


def test_all_real_presets_prepare_idempotent_provider_tasks_without_starting_worker(tmp_path):
    catalog = load_catalog()
    # The user's live Pine file may evolve. Exercise the historical input-title
    # mapping with an immutable synthetic source shaped like that catalog.
    titles = {}
    for record in catalog["records"]:
        for key, title in record["input_titles"].items():
            index = int(key[3:])
            assert index not in titles or titles[index] == title
            titles[index] = title
    source = 'strategy(' + json.dumps(catalog["strategy_title"]) + ')\n'
    source += '\n'.join(
        f'item_{index}=input.int(0,{json.dumps(titles.get(index, f"Unused {index}"))})'
        for index in range(max(titles) + 1)
    )
    store = Store(tmp_path / "research.db")
    project_id = store.create_project("Research", source)
    project = store.project(project_id)
    compatible_catalog = {**catalog, "mapping_source_sha256": project["pine_hash"]}
    records = catalog["records"]
    de30 = [row["id"] for row in records if row["candidate"] == "DE30EUR"]
    nas100 = [row["id"] for row in records if row["candidate"] == "NAS100USD"]
    tasks = provider_check_tasks(compatible_catalog, de30, project, "study", "CAPITALCOM:GER40")
    tasks += provider_check_tasks(compatible_catalog, nas100, project, "study", "CAPITALCOM:US100")
    assert len(tasks) == 7
    assert len({key for key, _ in tasks}) == 7
    assert store.enqueue_many(project_id, tasks) == 7
    assert store.enqueue_many(project_id, tasks) == 0
    assert all(task[1]["date_range"]["from_ms"] < task[1]["date_range"]["to_ms"] for task in tasks)


def test_current_pine_drift_cannot_prepare_historical_provider_tasks(tmp_path):
    catalog = load_catalog()
    source = 'strategy("Different Pine revision")\nlength=input.int(3,"Length")'
    store = Store(tmp_path / "current-research.db")
    project_id = store.create_project("Current ICT", source)
    project = store.project(project_id)
    if project["pine_hash"] != catalog["mapping_source_sha256"]:
        with pytest.raises(ValueError, match="aynı değil"):
            provider_check_tasks(catalog, [catalog["records"][0]["id"]], project,
                                 "study", "CAPITALCOM:GER40")
