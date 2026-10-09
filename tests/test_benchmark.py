"""Synthetic fixtures test the harness; they never constitute live acceptance."""
import pytest

from tv_scan_studio.benchmark import capture_run, compare_records, artifact_digest, load_record, serialize_record, _hash
from tv_scan_studio.planner import ScanPlan, enqueue_plan
from tv_scan_studio.storage import Store


CONTEXT = dict(machine="machine-A", tradingview_version="same-version",
               account_tier="same-tier", protocol="same-controlled-workload-v1")


def capture(tmp_path, monkeypatch, workers=1, build="a", provenance="real_tradingview",
            count=8, fail=False, unfinished=False, source='strategy("EMA")\na=input.int(8)'):
    store = Store(tmp_path / f"{build}-{workers}-{provenance}.db")
    project = store.create_project("EMA", source)
    enqueue_plan(store, project, ScanPlan("sid", ("BIST:XU030D1!",), ("15",),
                                        {"in_0": list(range(count))}), new_run=True)
    run = store.scan_runs(project)[0]["id"]
    for batch in range((count + workers - 1) // workers):
        start = 1000 + batch * 80
        tasks = []
        monkeypatch.setattr("time.time", lambda: start)
        for worker in range(1, workers + 1):
            task = store.claim_next(worker, [project], run_ids=[run])
            if task:
                tasks.append((worker, task))
        monkeypatch.setattr("time.time", lambda: start + 80)
        for worker, task in tasks:
            if unfinished:
                continue
            if fail and task.id == tasks[0][1].id:
                store.fail(task.id, worker, "failed", max_attempts=1)
            else:
                store.complete(task.id, worker, {"trades": 1}, "elenmiş", verified=True)
    evidence = tmp_path / "explicit-evidence.txt"
    evidence.write_text("test fixture, NOT actual live evidence", encoding="utf-8")
    with store.connect() as connection:
        return capture_run(connection, run, workers=workers, build_sha256=build * 64,
                           context=CONTEXT, provenance=provenance,
                           evidence_paths=[evidence], now=20000)


def test_union_rates_and_explicit_review_gate(tmp_path, monkeypatch):
    old = [capture(tmp_path, monkeypatch, w, "a") for w in (1, 2, 8)]
    new = [capture(tmp_path, monkeypatch, w, "b") for w in (1, 2, 8)]
    assert [r["active_seconds"] for r in old] == [640, 320, 80]
    assert [r["peak_concurrency"] for r in old] == [1, 2, 8]
    report = compare_records(old, new)
    assert report["performance_gate"] == "open"
    assert not report["live_evidence_reviewed"]
    assert report["anecdotal_reference"]["verified"] is False
    assert all(r["acceptance"] is False for r in old + new)
    report = compare_records(old, new, reviewed_hashes=[r["record_hash"] for r in old + new])
    assert report["performance_gate"] == "passed"  # reviewer API only, no real gate proof


@pytest.mark.parametrize("option", [{"provenance": "synthetic"}, {"fail": True}, {"unfinished": True}, {"count": 3}])
def test_ineligible_data_never_compared(tmp_path, monkeypatch, option):
    record = capture(tmp_path, monkeypatch, **option)
    assert not record["eligible_for_review"] and record["reasons"]
    with pytest.raises(ValueError):
        compare_records([record], [record])


def test_cross_source_and_tamper_rejected(tmp_path, monkeypatch):
    old = [capture(tmp_path, monkeypatch, w, "a") for w in (1, 2, 8)]
    new = [capture(tmp_path, monkeypatch, w, "b", source='strategy("different")') for w in (1, 2, 8)]
    with pytest.raises(ValueError, match="karşılaştırılabilir"):
        compare_records(old, new)
    old[0]["tests_per_hour"] = 9999
    with pytest.raises(ValueError, match="değiştirilmiş"):
        compare_records(old, new)


def test_no_500_cap(tmp_path, monkeypatch):
    record = capture(tmp_path, monkeypatch, workers=8, count=504)
    assert record["task_count"] == record["verified_count"] == 504
    assert record["eligible_for_review"]


def test_empty_evidence_rejected(tmp_path):
    path = tmp_path / "empty"
    path.touch()
    with pytest.raises(ValueError, match="Boş"):
        artifact_digest(path)


def test_record_roundtrip_never_promotes_acceptance(tmp_path, monkeypatch):
    record = capture(tmp_path, monkeypatch)
    assert load_record(serialize_record(record)) == record
    record["acceptance"] = True
    record["record_hash"] = _hash({k: v for k, v in record.items() if k != "record_hash"})
    with pytest.raises(ValueError, match="kabul"):
        serialize_record(record)


def test_regression_remains_open_even_after_review(tmp_path, monkeypatch):
    old = [capture(tmp_path, monkeypatch, w, "a") for w in (1, 2, 8)]
    new = [capture(tmp_path, monkeypatch, w, "b") for w in (1, 2, 8)]
    new[2]["active_seconds"] *= 2
    new[2]["tests_per_hour"] /= 2
    new[2]["record_hash"] = _hash({k: v for k, v in new[2].items() if k != "record_hash"})
    report = compare_records(old, new, reviewed_hashes=[r["record_hash"] for r in old + new])
    assert report["performance_gate"] == "open"
    assert report["rows"][2]["regression_requires_explanation"]
