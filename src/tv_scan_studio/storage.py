"""SQLite persistence for projects, tasks, attempts and resumable queues."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import time
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    pine_source TEXT NOT NULL,
    pine_hash TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    priority INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    worker_id INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    started_at REAL,
    finished_at REAL,
    updated_at REAL NOT NULL,
    UNIQUE(project_id, task_key)
);
CREATE INDEX IF NOT EXISTS tasks_claim_idx ON tasks(status, project_id, id);
CREATE TABLE IF NOT EXISTS results (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    metrics TEXT NOT NULL,
    classification TEXT NOT NULL,
    verified INTEGER NOT NULL CHECK(verified IN (0, 1)),
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS results_project_idx ON results(project_id, classification);
CREATE TABLE IF NOT EXISTS verification_evidence (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    evidence TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS project_settings (
    project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    settings TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    worker_id INTEGER,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    screenshot_path TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS event_log_created_idx ON event_log(created_at DESC);
CREATE INDEX IF NOT EXISTS event_log_task_idx ON event_log(task_id, created_at DESC);
CREATE TABLE IF NOT EXISTS validation_links (
    parent_task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    child_task_id INTEGER NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    passed INTEGER CHECK(passed IN (0, 1)),
    created_at REAL NOT NULL,
    PRIMARY KEY(parent_task_id, child_task_id)
);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class ClaimedTask:
    id: int
    project_id: int
    task_key: str
    payload: dict[str, Any]
    attempts: int


class _ClosingConnection(sqlite3.Connection):
    """Keep transaction semantics while releasing Windows SQLite file locks."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(projects)")}
            if "pine_hash" not in columns:
                connection.execute("ALTER TABLE projects ADD COLUMN pine_hash TEXT")
            task_columns = {row["name"] for row in connection.execute("PRAGMA table_info(tasks)")}
            if "started_at" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN started_at REAL")
            if "finished_at" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN finished_at REAL")
            for row in connection.execute("SELECT id,pine_source FROM projects WHERE pine_hash IS NULL"):
                digest = hashlib.sha256(row["pine_source"].encode("utf-8")).hexdigest()
                connection.execute("UPDATE projects SET pine_hash=? WHERE id=?", (digest, row["id"]))

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None,
                                     factory=_ClosingConnection)
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _refresh_project_status(connection: sqlite3.Connection, project_id: int) -> None:
        rows = connection.execute(
            "SELECT status,COUNT(*) count FROM tasks WHERE project_id=? GROUP BY status",
            (project_id,),
        ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        if counts.get("running", 0):
            status = "running"
        elif counts.get("pending", 0):
            status = "queued"
        elif counts and sum(counts.values()) == counts.get("cancelled", 0):
            status = "cancelled"
        elif counts:
            status = "complete"
        else:
            status = "draft"
        connection.execute(
            "UPDATE projects SET status=?,updated_at=? WHERE id=?",
            (status, time.time(), project_id),
        )

    def create_project(self, name: str, pine_source: str, priority: int = 0) -> int:
        now = time.time()
        pine_hash = hashlib.sha256(pine_source.encode("utf-8")).hexdigest()
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO projects(name,pine_source,pine_hash,priority,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (name, pine_source, pine_hash, priority, now, now),
            )
            return int(cursor.lastrowid)

    def enqueue(self, project_id: int, task_key: str, payload: dict[str, Any]) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO tasks(project_id,task_key,payload,updated_at) VALUES(?,?,?,?)",
                (project_id, task_key, json.dumps(payload, ensure_ascii=False), time.time()),
            )
            self._refresh_project_status(connection, project_id)
            return cursor.rowcount == 1

    def enqueue_many(self, project_id: int, tasks: Any) -> int:
        inserted = 0
        now = time.time()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for task_key, payload in tasks:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO tasks(project_id,task_key,payload,updated_at) VALUES(?,?,?,?)",
                    (project_id, task_key, json.dumps(payload, ensure_ascii=False), now),
                )
                inserted += cursor.rowcount
            self._refresh_project_status(connection, project_id)
            connection.commit()
        return inserted

    def save_settings(self, project_id: int, settings: dict[str, Any]) -> None:
        now = time.time()
        with self.connect() as connection:
            current = connection.execute(
                "SELECT settings FROM project_settings WHERE project_id=?", (project_id,)
            ).fetchone()
            merged = json.loads(current["settings"]) if current else {}
            merged.update(settings)
            encoded = json.dumps(merged, ensure_ascii=False, sort_keys=True)
            connection.execute(
                "INSERT INTO project_settings(project_id,settings,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET settings=excluded.settings,updated_at=excluded.updated_at",
                (project_id, encoded, now),
            )
            connection.execute(
                "UPDATE projects SET updated_at=? WHERE id=?", (now, project_id)
            )

    def settings(self, project_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT settings FROM project_settings WHERE project_id=?", (project_id,)
            ).fetchone()
        return json.loads(row["settings"]) if row else None

    def save_app_settings(self, settings: dict[str, Any]) -> None:
        now = time.time()
        with self.connect() as connection:
            for key, value in settings.items():
                connection.execute(
                    "INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                    (str(key), json.dumps(value, ensure_ascii=False), now),
                )

    def app_settings(self) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute("SELECT key,value FROM app_settings").fetchall()
        return {str(row["key"]): json.loads(row["value"]) for row in rows}

    def log_event(self, level: str, message: str, *, project_id: int | None = None,
                  task_id: int | None = None, worker_id: int | None = None,
                  screenshot_path: str | None = None) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO event_log(project_id,task_id,worker_id,level,message,screenshot_path,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (project_id, task_id, worker_id, level, message, screenshot_path, time.time()),
            )
            return int(cursor.lastrowid)

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM event_log ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def recover_interrupted(self) -> int:
        with self.connect() as connection:
            project_ids = [int(row[0]) for row in connection.execute(
                "SELECT DISTINCT project_id FROM tasks WHERE status='running'"
            ).fetchall()]
            cursor = connection.execute(
                "UPDATE tasks SET status='pending',worker_id=NULL,started_at=NULL,updated_at=? "
                "WHERE status='running'",
                (time.time(),),
            )
            for project_id in project_ids:
                self._refresh_project_status(connection, project_id)
            return cursor.rowcount

    def claim_next(
        self, worker_id: int, project_ids: list[int] | None = None
    ) -> ClaimedTask | None:
        """Atomically reserve one pending task for a worker.

        Project priority is considered first. Supplying ``project_ids`` limits a
        worker to its explicit assignments.
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            parameters: list[Any] = []
            assignment_filter = ""
            if project_ids is not None:
                if not project_ids:
                    connection.rollback()
                    return None
                placeholders = ",".join("?" for _ in project_ids)
                assignment_filter = f" AND t.project_id IN ({placeholders})"
                parameters.extend(project_ids)
            row = connection.execute(
                "SELECT t.id,t.project_id,t.task_key,t.payload,t.attempts "
                "FROM tasks t JOIN projects p ON p.id=t.project_id "
                "WHERE t.status='pending' AND p.status NOT IN ('paused','cancelled')" + assignment_filter + " "
                "ORDER BY p.priority DESC,t.id LIMIT 1",
                parameters,
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            updated = connection.execute(
                "UPDATE tasks SET status='running',worker_id=?,attempts=attempts+1,"
                "started_at=?,finished_at=NULL,updated_at=? "
                "WHERE id=? AND status='pending'",
                (worker_id, time.time(), time.time(), row["id"]),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return None
            self._refresh_project_status(connection, int(row["project_id"]))
            connection.commit()
            return ClaimedTask(
                id=int(row["id"]),
                project_id=int(row["project_id"]),
                task_key=str(row["task_key"]),
                payload=json.loads(row["payload"]),
                attempts=int(row["attempts"]) + 1,
            )

    def complete(
        self,
        task_id: int,
        worker_id: int,
        metrics: dict[str, Any],
        classification: str,
        *,
        verified: bool,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        if not verified:
            raise ValueError("Doğrulanmamış görev tamamlandı olarak kaydedilemez.")
        now = time.time()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT project_id FROM tasks WHERE id=? AND status='running' AND worker_id=?",
                (task_id, worker_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise ValueError("Görev bu worker tarafından çalıştırılmıyor.")
            connection.execute(
                "INSERT INTO results(task_id,project_id,metrics,classification,verified,created_at) "
                "VALUES(?,?,?,?,1,?) ON CONFLICT(task_id) DO UPDATE SET "
                "metrics=excluded.metrics,classification=excluded.classification,verified=1,created_at=excluded.created_at",
                (task_id, row["project_id"], json.dumps(metrics, ensure_ascii=False), classification, now),
            )
            connection.execute(
                "UPDATE tasks SET status='done',finished_at=?,updated_at=? WHERE id=?",
                (now, now, task_id),
            )
            connection.execute(
                "INSERT INTO verification_evidence(task_id,evidence,created_at) VALUES(?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET evidence=excluded.evidence,created_at=excluded.created_at",
                (task_id, json.dumps(evidence or {}, ensure_ascii=False), now),
            )
            self._resolve_validation(connection, task_id, classification != "elenmiş")
            self._refresh_project_status(connection, int(row["project_id"]))
            connection.commit()

    def fail(self, task_id: int, worker_id: int, error: str, max_attempts: int = 3,
             screenshot_path: str | None = None) -> str:
        if max_attempts < 1:
            raise ValueError("Maksimum deneme en az 1 olmalıdır.")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT attempts,payload FROM tasks WHERE id=? AND status='running' AND worker_id=?",
                (task_id, worker_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise ValueError("Görev bu worker tarafından çalıştırılmıyor.")
            payload = json.loads(row["payload"])
            payload["last_error"] = error
            status = "manual_review" if int(row["attempts"]) >= max_attempts else "pending"
            connection.execute(
                "UPDATE tasks SET status=?,worker_id=NULL,payload=?,finished_at=?,updated_at=? WHERE id=?",
                (status, json.dumps(payload, ensure_ascii=False),
                 time.time() if status == "manual_review" else None, time.time(), task_id),
            )
            connection.execute(
                "INSERT INTO event_log(project_id,task_id,worker_id,level,message,screenshot_path,created_at) "
                "SELECT project_id,id,?, ?, ?, ?, ? FROM tasks WHERE id=?",
                (worker_id, "error" if status == "manual_review" else "warning", error,
                 screenshot_path, time.time(), task_id),
            )
            project_id = connection.execute("SELECT project_id FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
            if status == "manual_review":
                self._resolve_validation(connection, task_id, False)
            self._refresh_project_status(connection, int(project_id))
            connection.commit()
            return status

    def invalidate(self, task_id: int, worker_id: int, error: str,
                   metrics: dict[str, Any], evidence: dict[str, Any]) -> None:
        now = time.time()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT project_id FROM tasks WHERE id=? AND status='running' AND worker_id=?",
                (task_id, worker_id),
            ).fetchone()
            if row is None:
                connection.rollback(); raise ValueError("Görev bu worker tarafından çalıştırılmıyor.")
            connection.execute(
                "INSERT INTO results(task_id,project_id,metrics,classification,verified,created_at) "
                "VALUES(?,?,?,?,0,?) ON CONFLICT(task_id) DO UPDATE SET metrics=excluded.metrics,"
                "classification='geçersiz',verified=0,created_at=excluded.created_at",
                (task_id, row["project_id"], json.dumps(metrics, ensure_ascii=False), "geçersiz", now),
            )
            connection.execute(
                "INSERT INTO verification_evidence(task_id,evidence,created_at) VALUES(?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET evidence=excluded.evidence,created_at=excluded.created_at",
                (task_id, json.dumps(evidence, ensure_ascii=False), now),
            )
            connection.execute(
                "UPDATE tasks SET status='failed',finished_at=?,updated_at=? WHERE id=?",
                (now, now, task_id),
            )
            connection.execute(
                "INSERT INTO event_log(project_id,task_id,worker_id,level,message,created_at) VALUES(?,?,?,?,?,?)",
                (row["project_id"], task_id, worker_id, "error", error, now),
            )
            self._resolve_validation(connection, task_id, False)
            self._refresh_project_status(connection, int(row["project_id"]))
            connection.commit()

    def results(self, project_id: int, classification: str | Iterable[str] | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT t.id task_id,t.task_key,t.payload,r.metrics,r.classification,r.verified,r.created_at,e.evidence "
            "FROM results r JOIN tasks t ON t.id=r.task_id "
            "LEFT JOIN verification_evidence e ON e.task_id=r.task_id WHERE r.project_id=?"
        )
        parameters: list[Any] = [project_id]
        if classification is not None:
            classes = (classification,) if isinstance(classification, str) else tuple(classification)
            if not classes:
                return []
            query += " AND r.classification IN (" + ",".join("?" for _ in classes) + ")"
            parameters.extend(classes)
        query += " ORDER BY t.id"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            {
                "task_id": int(row["task_id"]),
                "task_key": str(row["task_key"]),
                "payload": json.loads(row["payload"]),
                "metrics": json.loads(row["metrics"]),
                "classification": str(row["classification"]),
                "verified": bool(row["verified"]),
                "created_at": float(row["created_at"]),
                "evidence": json.loads(row["evidence"]) if row["evidence"] else {},
            }
            for row in rows
        ]

    def task_summaries(self, status: str | None, *, project_id: int | None = None,
                       limit: int = 500) -> tuple[int, list[dict[str, Any]]]:
        """Bounded task browser for dashboard counters, without loading huge queues."""
        if status not in {None, "pending", "running", "done", "failed", "manual_review", "cancelled"}:
            raise ValueError("Geçersiz görev durumu.")
        where = []
        parameters: list[Any] = []
        if status is not None:
            where.append("t.status=?")
            parameters.append(status)
        if project_id is not None:
            where.append("t.project_id=?")
            parameters.append(project_id)
        condition = " WHERE " + " AND ".join(where) if where else ""
        with self.connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM tasks t" + condition, parameters).fetchone()[0]
            rows = connection.execute(
                "SELECT t.id,t.task_key,t.payload,p.name project_name FROM tasks t "
                "JOIN projects p ON p.id=t.project_id" + condition + " ORDER BY t.id DESC LIMIT ?",
                (*parameters, max(1, min(limit, 5000))),
            ).fetchall()
        return total, [{"task_id": row["id"], "task_key": row["task_key"],
                        "project": row["project_name"], "payload": json.loads(row["payload"])}
                       for row in rows]

    def iter_task_records(self, project_id: int, *, connection: sqlite3.Connection | None = None):
        """Stream every planned task, including failures without a result row."""
        query = (
            "SELECT t.id,t.task_key,t.payload,t.status,t.attempts,t.started_at,t.finished_at,"
            "r.metrics,r.classification,r.verified,e.evidence,"
            "(SELECT message FROM event_log WHERE task_id=t.id ORDER BY created_at DESC LIMIT 1) last_event "
            "FROM tasks t LEFT JOIN results r ON r.task_id=t.id "
            "LEFT JOIN verification_evidence e ON e.task_id=t.id "
            "WHERE t.project_id=? ORDER BY t.id"
        )
        with (nullcontext(connection) if connection is not None else self.connect()) as active_connection:
            for row in active_connection.execute(query, (project_id,)):
                payload = json.loads(row["payload"])
                yield {
                    "task_id": int(row["id"]), "task_key": row["task_key"],
                    "payload": payload, "status": row["status"], "attempts": row["attempts"],
                    "started_at": row["started_at"], "finished_at": row["finished_at"],
                    "metrics": json.loads(row["metrics"]) if row["metrics"] else {},
                    "classification": row["classification"] or "sonuç yok",
                    "verified": bool(row["verified"]) if row["verified"] is not None else False,
                    "evidence": json.loads(row["evidence"]) if row["evidence"] else {},
                    "error": payload.get("last_error") or row["last_event"] or "",
                }

    def enqueue_validation(self, parent_task_id: int, stage: str,
                           task_key: str, payload: dict[str, Any]) -> bool:
        if stage not in {"neighbor", "cost_stress", "provider_check"}:
            raise ValueError(f"Geçersiz doğrulama aşaması: {stage}")
        now = time.time()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            parent = connection.execute(
                "SELECT project_id FROM tasks WHERE id=? AND status='done'", (parent_task_id,)
            ).fetchone()
            if parent is None:
                connection.rollback(); raise ValueError("Yalnızca tamamlanmış görev doğrulanabilir.")
            cursor = connection.execute(
                "INSERT OR IGNORE INTO tasks(project_id,task_key,payload,updated_at) VALUES(?,?,?,?)",
                (parent["project_id"], task_key, json.dumps(payload, ensure_ascii=False), now),
            )
            child = connection.execute(
                "SELECT id FROM tasks WHERE project_id=? AND task_key=?",
                (parent["project_id"], task_key),
            ).fetchone()
            connection.execute(
                "INSERT OR IGNORE INTO validation_links(parent_task_id,child_task_id,stage,created_at) "
                "VALUES(?,?,?,?)", (parent_task_id, child["id"], stage, now),
            )
            self._refresh_project_status(connection, int(parent["project_id"]))
            connection.commit()
            return cursor.rowcount == 1

    @staticmethod
    def _resolve_validation(connection: sqlite3.Connection, child_task_id: int, passed: bool) -> None:
        link = connection.execute(
            "SELECT parent_task_id FROM validation_links WHERE child_task_id=?", (child_task_id,)
        ).fetchone()
        if link is None:
            return
        parent_id = int(link["parent_task_id"])
        connection.execute(
            "UPDATE validation_links SET passed=? WHERE child_task_id=?", (int(passed), child_task_id)
        )
        rows = connection.execute(
            "SELECT stage,COUNT(*) total,SUM(CASE WHEN passed=1 THEN 1 ELSE 0 END) passed_count,"
            "SUM(CASE WHEN passed=0 THEN 1 ELSE 0 END) failed_count,"
            "SUM(CASE WHEN passed IS NULL THEN 1 ELSE 0 END) pending_count "
            "FROM validation_links WHERE parent_task_id=? GROUP BY stage", (parent_id,)
        ).fetchall()
        stages = {str(row["stage"]): dict(row) for row in rows}
        evidence_row = connection.execute(
            "SELECT evidence FROM verification_evidence WHERE task_id=?", (parent_id,)
        ).fetchone()
        evidence = json.loads(evidence_row["evidence"]) if evidence_row else {}
        gate_names = {"neighbor": "neighbor_passed", "cost_stress": "cost_stress_passed",
                      "provider_check": "provider_check_passed"}
        validation = evidence.setdefault("validation", {})
        for stage, gate in gate_names.items():
            data = stages.get(stage)
            validation[gate] = bool(data and data["pending_count"] == 0 and data["failed_count"] == 0)
        connection.execute(
            "UPDATE verification_evidence SET evidence=?,created_at=? WHERE task_id=?",
            (json.dumps(evidence, ensure_ascii=False), time.time(), parent_id),
        )
        durable = all(validation.get(gate) is True for gate in gate_names.values())
        connection.execute(
            "UPDATE results SET classification=? WHERE task_id=? AND verified=1",
            ("dayanıklı" if durable else "hassas", parent_id),
        )

    def counts(self, project_id: int) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT status,COUNT(*) count FROM tasks WHERE project_id=? GROUP BY status",
                (project_id,),
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def projects(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT p.id,p.name,p.status,p.priority,p.created_at,p.updated_at,"
                "COUNT(t.id) task_count,"
                "SUM(CASE WHEN t.status='done' THEN 1 ELSE 0 END) done_count,"
                "SUM(CASE WHEN t.status='pending' THEN 1 ELSE 0 END) pending_count,"
                "SUM(CASE WHEN t.status='running' THEN 1 ELSE 0 END) running_count,"
                "SUM(CASE WHEN t.status='cancelled' THEN 1 ELSE 0 END) cancelled_count,"
                "SUM(CASE WHEN t.status IN ('failed','manual_review') THEN 1 ELSE 0 END) issue_count "
                "FROM projects p LEFT JOIN tasks t ON t.project_id=p.id "
                "GROUP BY p.id ORDER BY p.priority DESC,p.updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def project(self, project_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        return dict(row) if row else None

    def total_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT status,COUNT(*) count FROM tasks GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def update_project(self, project_id: int, *, priority: int | None = None,
                       status: str | None = None) -> None:
        allowed = {"draft", "queued", "running", "paused", "complete", "cancelled"}
        if status is not None and status not in allowed:
            raise ValueError(f"Geçersiz proje durumu: {status}")
        if priority is None and status is None:
            return
        assignments: list[str] = []
        parameters: list[Any] = []
        if priority is not None:
            assignments.append("priority=?"); parameters.append(int(priority))
        if status is not None:
            assignments.append("status=?"); parameters.append(status)
        assignments.append("updated_at=?"); parameters.append(time.time())
        parameters.append(project_id)
        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE projects SET {','.join(assignments)} WHERE id=?", parameters
            )
            if cursor.rowcount != 1:
                raise ValueError("Proje bulunamadı.")

    def cancel_pending(self, project_id: int) -> int:
        now = time.time()
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status='cancelled',finished_at=?,updated_at=? "
                "WHERE project_id=? AND status='pending'", (now, now, project_id),
            )
            connection.execute(
                "UPDATE projects SET status='cancelled',updated_at=? WHERE id=?",
                (now, project_id),
            )
            return cursor.rowcount

    def retry_task(self, task_id: int) -> None:
        with self.connect() as connection:
            row = connection.execute("SELECT project_id FROM tasks WHERE id=?", (task_id,)).fetchone()
            cursor = connection.execute(
                "UPDATE tasks SET status='pending',worker_id=NULL,started_at=NULL,finished_at=NULL,"
                "updated_at=? WHERE id=? AND status IN ('failed','manual_review','cancelled')",
                (time.time(), task_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Görev yeniden denenebilir durumda değil.")
            self._refresh_project_status(connection, int(row["project_id"]))

    def retry_tasks(self, project_id: int) -> int:
        """Return failed, manual-review and cancelled tasks to the queue."""
        now = time.time()
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status='pending',worker_id=NULL,started_at=NULL,finished_at=NULL,"
                "updated_at=? WHERE project_id=? AND status IN ('failed','manual_review','cancelled')",
                (now, project_id),
            )
            if cursor.rowcount:
                connection.execute(
                    "UPDATE projects SET status='queued',updated_at=? WHERE id=?", (now, project_id)
                )
            return cursor.rowcount

    def tasks(self, project_id: int, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM tasks WHERE project_id=?"
        parameters: list[Any] = [project_id]
        if status is not None:
            query += " AND status=?"; parameters.append(status)
        query += " ORDER BY id"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def research_provider_status(self, project_id: int) -> dict[str, list[dict[str, Any]]]:
        """Keep historical research evidence separate from new local provider tasks."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT t.id,t.status,t.payload,r.classification,r.verified "
                "FROM tasks t LEFT JOIN results r ON r.task_id=t.id "
                "WHERE t.project_id=? ORDER BY t.id", (project_id,),
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            payload = json.loads(row["payload"])
            source_id = payload.get("research_source_id")
            if not source_id or payload.get("validation_stage") != "provider_check":
                continue
            if row["status"] == "done" and row["verified"]:
                outcome = "passed" if row["classification"] not in ("elenmiş", "geçersiz") else "failed_threshold"
            elif row["status"] in ("failed", "manual_review", "cancelled"):
                outcome = "invalid"
            else:
                outcome = row["status"]
            grouped.setdefault(source_id, []).append({
                "task_id": int(row["id"]), "symbol": payload["symbol"],
                "status": outcome, "classification": row["classification"],
            })
        return grouped

    def dashboard_stats(self, project_id: int | None = None) -> dict[str, Any]:
        where = " WHERE project_id=?" if project_id is not None else ""
        parameters: tuple[Any, ...] = (project_id,) if project_id is not None else ()
        with self.connect() as connection:
            counts = connection.execute(
                "SELECT status,COUNT(*) count FROM tasks" + where + " GROUP BY status",
                parameters,
            ).fetchall()
            completed = connection.execute(
                "SELECT COUNT(*) count,MIN(started_at) first,MAX(finished_at) last "
                "FROM tasks" + where + (" AND" if where else " WHERE") +
                " status='done' AND started_at IS NOT NULL AND finished_at IS NOT NULL", parameters,
            ).fetchone()
            candidate_where = " WHERE project_id=?" if project_id is not None else ""
            candidates = connection.execute(
                "SELECT classification,COUNT(*) count FROM results" + candidate_where +
                " GROUP BY classification", parameters,
            ).fetchall()
        count_map = {str(row["status"]): int(row["count"]) for row in counts}
        done = int(completed["count"] or 0)
        span = max(0.0, float(completed["last"] or 0) - float(completed["first"] or 0))
        # A few near-instant offline runs are not a meaningful throughput/ETA sample.
        tests_per_hour = done * 3600 / span if done >= 5 and span >= 60 else 0.0
        remaining = count_map.get("pending", 0) + count_map.get("running", 0)
        eta_seconds = remaining * 3600 / tests_per_hour if tests_per_hour > 0 else None
        return {
            "counts": count_map, "tests_per_hour": tests_per_hour,
            "eta_seconds": eta_seconds,
            "candidates": {str(row["classification"]): int(row["count"]) for row in candidates},
        }

    def observed_seconds_per_test(self, project_id: int | None = None) -> float | None:
        condition = " AND project_id=?" if project_id is not None else ""
        parameters: tuple[Any, ...] = (project_id,) if project_id is not None else ()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT AVG(finished_at-started_at) average FROM tasks "
                "WHERE status='done' AND started_at IS NOT NULL AND finished_at>started_at" + condition,
                parameters,
            ).fetchone()
        return float(row["average"]) if row and row["average"] is not None else None
