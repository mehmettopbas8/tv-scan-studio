"""Append-only execution evidence, independent of the mutable queue projection."""
import hashlib
import json
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS attempt_history (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    attempt_number INTEGER NOT NULL,
    worker_id INTEGER,
    event TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS attempt_history_task ON attempt_history(task_id,id);
CREATE TABLE IF NOT EXISTS result_history (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    attempt_number INTEGER NOT NULL,
    payload TEXT NOT NULL,
    metrics TEXT NOT NULL,
    evidence TEXT NOT NULL,
    source_snapshot TEXT NOT NULL,
    source_provenance TEXT NOT NULL,
    classification TEXT NOT NULL,
    verified INTEGER NOT NULL,
    warning_state TEXT NOT NULL CHECK(warning_state IN ('present','absent','unknown')),
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS result_history_task ON result_history(task_id,id);
CREATE TABLE IF NOT EXISTS evaluation_policies (
    id INTEGER PRIMARY KEY,policy_key TEXT NOT NULL UNIQUE,definition TEXT NOT NULL,created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS result_evaluations (
    id INTEGER PRIMARY KEY,result_id INTEGER NOT NULL REFERENCES result_history(id),
    policy_id INTEGER NOT NULL REFERENCES evaluation_policies(id),classification TEXT NOT NULL,
    created_at REAL NOT NULL,UNIQUE(result_id,policy_id)
);
CREATE TABLE IF NOT EXISTS history_migrations (name TEXT PRIMARY KEY,created_at REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS attempt_history_no_update BEFORE UPDATE ON attempt_history
BEGIN SELECT RAISE(ABORT,'attempt history is immutable'); END;
CREATE TRIGGER IF NOT EXISTS attempt_history_no_delete BEFORE DELETE ON attempt_history
BEGIN SELECT RAISE(ABORT,'attempt history is immutable'); END;
CREATE TRIGGER IF NOT EXISTS result_history_no_update BEFORE UPDATE ON result_history
BEGIN SELECT RAISE(ABORT,'result history is immutable'); END;
CREATE TRIGGER IF NOT EXISTS result_history_no_delete BEFORE DELETE ON result_history
BEGIN SELECT RAISE(ABORT,'result history is immutable'); END;
CREATE TRIGGER IF NOT EXISTS evaluation_policies_no_update BEFORE UPDATE ON evaluation_policies
BEGIN SELECT RAISE(ABORT,'evaluation policy is immutable'); END;
CREATE TRIGGER IF NOT EXISTS evaluation_policies_no_delete BEFORE DELETE ON evaluation_policies
BEGIN SELECT RAISE(ABORT,'evaluation policy is immutable'); END;
CREATE TRIGGER IF NOT EXISTS result_evaluations_no_update BEFORE UPDATE ON result_evaluations
BEGIN SELECT RAISE(ABORT,'result evaluation is immutable'); END;
CREATE TRIGGER IF NOT EXISTS result_evaluations_no_delete BEFORE DELETE ON result_evaluations
BEGIN SELECT RAISE(ABORT,'result evaluation is immutable'); END;
"""


def encode(value):
    # Preserve legacy metric representations (including Infinity) losslessly.
    # Plan admission validates finite settings separately; archival is not validation.
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def append_attempt(connection, task_id, event, *, detail=None):
    row = connection.execute(
        "SELECT t.attempts,t.worker_id,t.payload,p.pine_source FROM tasks t "
        "JOIN projects p ON p.id=t.project_id WHERE t.id=?", (task_id,)).fetchone()
    source = row["pine_source"]
    snapshot = {"payload": json.loads(row["payload"]), "detail": detail or {}}
    membership = connection.execute("SELECT run_id,test_key FROM run_tasks WHERE task_id=?", (task_id,)).fetchone()
    if membership:
        snapshot["run_id"] = membership["run_id"]
        snapshot["test_key"] = membership["test_key"]
    if event == "claimed":
        snapshot["source"] = source
        snapshot["source_hash"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
    connection.execute(
        "INSERT INTO attempt_history(task_id,attempt_number,worker_id,event,snapshot,created_at) VALUES(?,?,?,?,?,?)",
        (task_id, row["attempts"], row["worker_id"], event, encode(snapshot), time.time()))


def append_result(connection, task_id, metrics, evidence, classification, verified, *, created_at=None, legacy=False):
    row = connection.execute("SELECT attempts,payload FROM tasks WHERE id=?", (task_id,)).fetchone()
    claim = connection.execute(
        "SELECT snapshot FROM attempt_history WHERE task_id=? AND attempt_number=? AND event='claimed' ORDER BY id DESC LIMIT 1",
        (task_id, row["attempts"])).fetchone()
    source = json.loads(claim["snapshot"]).get("source", "") if claim else ""
    provenance = "claim_snapshot" if claim and not legacy else "legacy_source_unverified"
    warning_state = (evidence or {}).get("tradingview_warning_state", "unknown")
    if warning_state not in {"present", "absent", "unknown"}:
        raise ValueError("TradingView uyarı durumu present/absent/unknown olmalıdır.")
    cursor = connection.execute(
        "INSERT INTO result_history(task_id,attempt_number,payload,metrics,evidence,source_snapshot,source_provenance,classification,verified,warning_state,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (task_id, row["attempts"], row["payload"], encode(metrics), encode(evidence or {}), source,
         provenance, classification, int(verified), warning_state, created_at if created_at is not None else time.time()))
    payload = json.loads(row["payload"])
    append_evaluation(connection, cursor.lastrowid,
        {"criteria": payload.get("criteria", {}), "validation": payload.get("validation", {}),
         "classifier": "legacy-unversioned" if legacy else "classification-v1"}, classification)


def append_evaluation(connection, result_id, definition, classification):
    encoded = encode(definition)
    key = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    connection.execute("INSERT OR IGNORE INTO evaluation_policies(policy_key,definition,created_at) VALUES(?,?,?)",
                       (key, encoded, time.time()))
    policy_id = connection.execute("SELECT id FROM evaluation_policies WHERE policy_key=?", (key,)).fetchone()[0]
    connection.execute("INSERT OR IGNORE INTO result_evaluations(result_id,policy_id,classification,created_at) VALUES(?,?,?,?)",
                       (result_id, policy_id, classification, time.time()))
    return int(connection.execute("SELECT id FROM result_evaluations WHERE result_id=? AND policy_id=?",
                                  (result_id, policy_id)).fetchone()[0])


def migrate_legacy(connection):
    """Archive available old results once; never invent old attempts or source proof."""
    if connection.execute("SELECT 1 FROM history_migrations WHERE name='legacy-results-v1'").fetchone():
        return
    rows = connection.execute(
        "SELECT r.*,e.evidence FROM results r LEFT JOIN verification_evidence e ON e.task_id=r.task_id").fetchall()
    for row in rows:
        append_result(connection, row["task_id"], json.loads(row["metrics"]),
                      json.loads(row["evidence"]) if row["evidence"] else {}, row["classification"],
                      bool(row["verified"]), created_at=row["created_at"], legacy=True)
    connection.execute("INSERT INTO history_migrations VALUES('legacy-results-v1',?)", (time.time(),))
