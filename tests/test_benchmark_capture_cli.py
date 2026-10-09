import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from tv_scan_studio.planner import ScanPlan, enqueue_plan
from tv_scan_studio.storage import Store


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "capture_run_benchmark.py"


def fixture_args(tmp_path):
    database = tmp_path / "run.db"
    store = Store(database)
    project = store.create_project("EMA", 'strategy("EMA")\na=input.int(8)')
    enqueue_plan(store, project, ScanPlan("sid", ("BIST:XU030D1!",), ("15",),
                                        {"in_0": [7, 8, 9]}), new_run=True)
    run = store.scan_runs(project)[0]["id"]
    for _ in range(3):
        task = store.claim_next(1, [project], run_ids=[run])
        store.complete(task.id, 1, {"trades": 1}, "elenmiş", verified=True)
    exe = tmp_path / "explicit.exe"
    exe.write_bytes(b"synthetic EXE identity fixture")
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("synthetic fixture, not live evidence")
    context = tmp_path / "context.json"
    context.write_text(json.dumps(dict(machine="A", tradingview_version="same",
                                      account_tier="same", protocol="same")))
    output = tmp_path / "record.json"
    args = [sys.executable, str(SCRIPT), "--database", str(database), "--run", str(run),
            "--workers", "1", "--exe", str(exe), "--context-json", str(context),
            "--evidence", str(evidence), "--output", str(output)]
    return args, database, exe, context, output, evidence


@pytest.mark.parametrize("live", [False, True])
def test_capture_is_readonly_hashes_actual_exe_and_small_run_is_ineligible(tmp_path, live):
    args, database, exe, _, output, _ = fixture_args(tmp_path)
    before = database.read_bytes()
    with sqlite3.connect(database) as db:
        logical_before = list(db.iterdump())
    result = subprocess.run(args + (["--real-tradingview"] if live else []),
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    record = json.loads(output.read_text())
    assert record["build_sha256"] == hashlib.sha256(exe.read_bytes()).hexdigest()
    assert record["provenance"] == ("real_tradingview" if live else "local_unverified")
    assert record["acceptance"] is False and not record["eligible_for_review"]
    assert record["verified_count"] == 3
    assert database.read_bytes() == before
    with sqlite3.connect(database) as db:
        assert list(db.iterdump()) == logical_before


def test_existing_output_never_overwritten(tmp_path):
    args, _, _, _, output, _ = fixture_args(tmp_path)
    output.write_text("keep")
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0 and output.read_text() == "keep"


@pytest.mark.parametrize("context", ["{", "[]", '{"machine":"A"}',
    '{"machine":"A","tradingview_version":"V","account_tier":"T","protocol":""}'])
def test_invalid_context_cannot_publish(tmp_path, context):
    args, _, _, context_path, output, _ = fixture_args(tmp_path)
    context_path.write_text(context)
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0 and not output.exists()


def test_missing_evidence_cannot_publish(tmp_path):
    args, _, _, _, output, evidence = fixture_args(tmp_path)
    evidence.unlink()
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0 and not output.exists()


def test_symlink_evidence_rejected_before_database_open(tmp_path, monkeypatch):
    args, _, _, _, output, evidence = fixture_args(tmp_path)
    spec = importlib.util.spec_from_file_location("capture_cli_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == evidence or original(path))
    monkeypatch.setattr(module.sqlite3, "connect", lambda *a, **kw: pytest.fail("DB opened before rejection"))
    with pytest.raises(SystemExit) as error:
        module.main(args[2:])
    assert error.value.code == 2 and not output.exists()
