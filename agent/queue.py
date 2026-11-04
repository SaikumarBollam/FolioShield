"""
Durable local agent queue backed by SQLite (Python standard library).

Jobs survive process restarts and network interruptions. Failed jobs use
exponential backoff and move to dead_letter after max attempts.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now() -> float:
    return time.time()


def _iso(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(ts or _now(), tz=timezone.utc).isoformat()


class AgentQueue:
    """SQLite-backed durable queue for agent synchronization jobs."""

    def __init__(self, path: str | Path = "agent_queue.sqlite3"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                idempotency_key TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs(idempotency_key) WHERE idempotency_key IS NOT NULL")
        self._conn.commit()

    def enqueue(self, job_type: str, payload: Dict[str, Any], idempotency_key: Optional[str] = None,
                max_attempts: int = 5) -> Dict[str, Any]:
        if idempotency_key:
            existing = self._conn.execute("SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                return dict(existing)
        job_id = str(uuid.uuid4())
        now = _now()
        self._conn.execute(
            "INSERT INTO jobs(job_id, job_type, payload, status, attempts, max_attempts, next_attempt_at, idempotency_key, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (job_id, job_type, json.dumps(payload, default=str), "queued", 0, max_attempts, now, idempotency_key, _iso(now), _iso(now)),
        )
        self._conn.commit()
        return self.get(job_id) or {}

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def due_jobs(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE status IN ('queued','retrying') AND next_attempt_at <= ? ORDER BY created_at LIMIT ?",
            (_now(), limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_running(self, job_id: str) -> None:
        self._update(job_id, status="running")

    def mark_succeeded(self, job_id: str, result: Optional[Dict[str, Any]] = None) -> None:
        job = self.get(job_id)
        payload = json.loads(job["payload"]) if job else {}
        if result:
            payload["result"] = result
        self._conn.execute(
            "UPDATE jobs SET status='succeeded', payload=?, updated_at=? WHERE job_id=?",
            (json.dumps(payload, default=str), _iso(), job_id),
        )
        self._conn.commit()

    def mark_failed(self, job_id: str, error: str, backoff_base: int = 5, backoff_max: int = 300) -> Dict[str, Any]:
        job = self.get(job_id)
        if not job:
            return {}
        attempts = int(job["attempts"]) + 1
        max_attempts = int(job["max_attempts"])
        if attempts >= max_attempts:
            status = "dead_letter"
            next_attempt = _now()
        else:
            status = "retrying"
            delay = min(backoff_base * (2 ** (attempts - 1)), backoff_max)
            next_attempt = _now() + delay
        self._conn.execute(
            "UPDATE jobs SET status=?, attempts=?, next_attempt_at=?, last_error=?, updated_at=? WHERE job_id=?",
            (status, attempts, next_attempt, str(error)[:500], _iso(), job_id),
        )
        self._conn.commit()
        return self.get(job_id) or {}

    def retry_dead_letter(self, job_id: str) -> Optional[Dict[str, Any]]:
        self._conn.execute(
            "UPDATE jobs SET status='queued', attempts=0, next_attempt_at=?, last_error=NULL, updated_at=? WHERE job_id=? AND status='dead_letter'",
            (_now(), _iso(), job_id),
        )
        self._conn.commit()
        return self.get(job_id)

    def _update(self, job_id: str, status: str) -> None:
        self._conn.execute("UPDATE jobs SET status=?, updated_at=? WHERE job_id=?", (status, _iso(), job_id))
        self._conn.commit()

    def counts(self) -> Dict[str, int]:
        rows = self._conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
        return {r["status"]: int(r["n"]) for r in rows}

    def close(self) -> None:
        self._conn.close()
