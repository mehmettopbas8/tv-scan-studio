"""SQLite persistence for projects, tasks, attempts and resumable queues."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
"""


@dataclass(frozen=True, slots=True)
class ClaimedTask:
    id: int
    project_id: int
    task_key: str
    payload: dict[str, Any]
    attempts: int


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(projects)")}
            if "pine_hash" not in columns:
                connection.execute("ALTER TABLE projects ADD COLUMN pine_hash TEXT")
            for row in connection.execute("SELECT id,pine_source FROM projects WHERE pine_hash IS NULL"):
                digest = hashlib.sha256(row["pine_source"].encode("utf-8")).hexdigest()
                connection.execute("UPDATE projects SET pine_hash=? WHERE id=?", (digest, row["id"]))

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.row_factory = sqlite3.Row
        return connection

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
            connection.commit()
        return inserted

    def save_settings(self, project_id: int, settings: dict[str, Any]) -> None:
        now = time.time()
        encoded = json.dumps(settings, ensure_ascii=False, sort_keys=True)
        with self.connect() as connection:
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
            cursor = connection.execute(
                "UPDATE tasks SET status='pending',worker_id=NULL,updated_at=? WHERE status='running'",
                (time.time(),),
            )
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
                "WHERE t.status='pending'" + assignment_filter + " "
                "ORDER BY p.priority DESC,t.id LIMIT 1",
                parameters,
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            updated = connection.execute(
                "UPDATE tasks SET status='running',worker_id=?,attempts=attempts+1,updated_at=? "
                "WHERE id=? AND status='pending'",
                (worker_id, time.time(), row["id"]),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return None
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
                "UPDATE tasks SET status='done',updated_at=? WHERE id=?", (now, task_id)
            )
            connection.execute(
                "INSERT INTO verification_evidence(task_id,evidence,created_at) VALUES(?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET evidence=excluded.evidence,created_at=excluded.created_at",
                (task_id, json.dumps(evidence or {}, ensure_ascii=False), now),
            )
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
                "UPDATE tasks SET status=?,worker_id=NULL,payload=?,updated_at=? WHERE id=?",
                (status, json.dumps(payload, ensure_ascii=False), time.time(), task_id),
            )
            connection.execute(
                "INSERT INTO event_log(project_id,task_id,worker_id,level,message,screenshot_path,created_at) "
                "SELECT project_id,id,?, ?, ?, ?, ? FROM tasks WHERE id=?",
                (worker_id, "error" if status == "manual_review" else "warning", error,
                 screenshot_path, time.time(), task_id),
            )
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
            connection.execute("UPDATE tasks SET status='failed',updated_at=? WHERE id=?", (now, task_id))
            connection.execute(
                "INSERT INTO event_log(project_id,task_id,worker_id,level,message,created_at) VALUES(?,?,?,?,?,?)",
                (row["project_id"], task_id, worker_id, "error", error, now),
            )
            connection.commit()

    def results(self, project_id: int, classification: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT t.task_key,t.payload,r.metrics,r.classification,r.verified,r.created_at,e.evidence "
            "FROM results r JOIN tasks t ON t.id=r.task_id "
            "LEFT JOIN verification_evidence e ON e.task_id=r.task_id WHERE r.project_id=?"
        )
        parameters: list[Any] = [project_id]
        if classification is not None:
            query += " AND r.classification=?"
            parameters.append(classification)
        query += " ORDER BY t.id"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            {
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
                "COUNT(t.id) task_count FROM projects p LEFT JOIN tasks t ON t.project_id=p.id "
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
