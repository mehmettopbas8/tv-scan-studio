"""Immutable run snapshots and memberships; mutable tasks retain legacy IDs."""
import hashlib
import json
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_runs (
 id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),
 kind TEXT NOT NULL CHECK(kind IN ('legacy','scan')),
 plan_snapshot TEXT NOT NULL,source_snapshot TEXT NOT NULL,source_hash TEXT,
 created_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS scan_runs_legacy ON scan_runs(project_id) WHERE kind='legacy';
CREATE TABLE IF NOT EXISTS run_tasks (
 task_id INTEGER PRIMARY KEY REFERENCES tasks(id),run_id INTEGER NOT NULL REFERENCES scan_runs(id),
 test_key TEXT NOT NULL,UNIQUE(run_id,test_key)
);
CREATE INDEX IF NOT EXISTS run_tasks_run ON run_tasks(run_id,task_id);
CREATE TRIGGER IF NOT EXISTS scan_runs_no_update BEFORE UPDATE ON scan_runs
BEGIN SELECT RAISE(ABORT,'scan run is immutable'); END;
CREATE TRIGGER IF NOT EXISTS scan_runs_no_delete BEFORE DELETE ON scan_runs
BEGIN SELECT RAISE(ABORT,'scan run is immutable'); END;
CREATE TRIGGER IF NOT EXISTS run_tasks_no_update BEFORE UPDATE ON run_tasks
BEGIN SELECT RAISE(ABORT,'run membership is immutable'); END;
CREATE TRIGGER IF NOT EXISTS run_tasks_no_delete BEFORE DELETE ON run_tasks
BEGIN SELECT RAISE(ABORT,'run membership is immutable'); END;
"""


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def legacy_run(connection, project_id):
    connection.execute("INSERT OR IGNORE INTO scan_runs(project_id,kind,plan_snapshot,source_snapshot,source_hash,created_at) "
                       "VALUES(?,'legacy',?,'',NULL,?)", (project_id, encode({"legacy": True, "source_unverified": True}), time.time()))
    return int(connection.execute("SELECT id FROM scan_runs WHERE project_id=? AND kind='legacy'", (project_id,)).fetchone()[0])


def migrate(connection):
    for row in connection.execute("SELECT DISTINCT project_id FROM tasks WHERE id NOT IN (SELECT task_id FROM run_tasks)").fetchall():
        run_id = legacy_run(connection, row["project_id"])
        connection.execute("INSERT INTO run_tasks(task_id,run_id,test_key) SELECT id,?,task_key FROM tasks "
                           "WHERE project_id=? AND id NOT IN (SELECT task_id FROM run_tasks)", (run_id, row["project_id"]))


def test_identity(payload, source):
    # Runtime bindings and evaluation thresholds do not identify a TradingView test.
    identity = {key: value for key, value in payload.items()
                if key not in {"criteria", "validation", "study_id", "timeout", "poll_interval", "stable_reads"}}
    identity["source_hash"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return hashlib.sha256(encode(identity).encode("utf-8")).hexdigest()


def comparable_plan(plan):
    return encode({key: value for key, value in plan.items()
                   if key not in {"study_id", "timeout", "poll_interval", "stable_reads", "input_ui"}
                   and not (key == "research" and not value)})


def select_run(connection, project_id, request, source):
    if request is None:
        return legacy_run(connection, project_id), ""
    if request["plan"].get("research"):
        from .period_research import validate_research_request
        validate_research_request(connection, project_id, request["plan"], source)
    if request["mode"] == "new":
        cursor = connection.execute("INSERT INTO scan_runs(project_id,kind,plan_snapshot,source_snapshot,source_hash,created_at) "
            "VALUES(?,'scan',?,?,?,?)", (project_id, encode(request["plan"]), source,
                hashlib.sha256(source.encode("utf-8")).hexdigest(), time.time()))
        run_id = int(cursor.lastrowid)
    else:
        run_id = request["run_id"]
        row = connection.execute("SELECT * FROM scan_runs WHERE id=? AND project_id=? AND kind='scan'", (run_id, project_id)).fetchone()
        if row is None:
            raise ValueError("Devam edilecek tarama koşusu bu stratejiye ait değil.")
        if row["source_snapshot"] != source or comparable_plan(json.loads(row["plan_snapshot"])) != comparable_plan(request["plan"]):
            raise ValueError("Koşunun kaynağı veya planı değişti. Yeni koşu oluşturun; yalnız başarı ölçütü için ayrı değerlendirme kullanın.")
    return run_id, f"run:{run_id}:"
