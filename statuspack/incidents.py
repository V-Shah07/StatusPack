"""SQLite-backed incident log, eval scores, and remediation log.

One tiny module so every phase shares the same store. Timestamps are stored as
ISO-8601 UTC strings.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "statuspack.db"


def _now() -> str:
    return datetime.now(UTC).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    public_id TEXT,
    monitor_id INTEGER,
    status TEXT NOT NULL,               -- 'open' | 'resolved'
    started_at TEXT NOT NULL,           -- when the failure was observed
    detected_at TEXT NOT NULL,          -- when our app received the alert
    resolved_at TEXT,                   -- when recovery was observed
    alert_transition TEXT,              -- Datadog transition, e.g. 'Triggered'/'Recovered'
    summary TEXT,                       -- Phase 4 LLM summary
    raw_alert TEXT                      -- original webhook payload (JSON string)
);

CREATE TABLE IF NOT EXISTS eval_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    labeled_set_size INTEGER NOT NULL,
    catch_rate REAL NOT NULL,
    false_positive_rate REAL NOT NULL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS remediation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL,
    service TEXT NOT NULL,
    proposed_action TEXT,
    confidence REAL,
    gate_decision TEXT NOT NULL,        -- 'executed' | 'refused'
    reason TEXT,
    recovered INTEGER                   -- 1/0/NULL: did the next check pass?
);
"""


@dataclass
class Incident:
    id: int
    service: str
    public_id: str | None
    monitor_id: int | None
    status: str
    started_at: str
    detected_at: str
    resolved_at: str | None
    alert_transition: str | None
    summary: str | None
    raw_alert: str | None


class IncidentStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = str(db_path)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- incidents ---------------------------------------------------------
    def open_incident(
        self,
        service: str,
        *,
        public_id: str | None = None,
        monitor_id: int | None = None,
        started_at: str | None = None,
        alert_transition: str | None = None,
        raw_alert: str | None = None,
    ) -> int:
        """Record a new open incident. If one is already open for this service,
        return its id instead of creating a duplicate."""
        existing = self.get_open_incident(service)
        if existing:
            return existing.id
        detected_at = _now()
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO incidents
                   (service, public_id, monitor_id, status, started_at, detected_at,
                    alert_transition, raw_alert)
                   VALUES (?, ?, ?, 'open', ?, ?, ?, ?)""",
                (
                    service,
                    public_id,
                    monitor_id,
                    started_at or detected_at,
                    detected_at,
                    alert_transition,
                    raw_alert,
                ),
            )
            return int(cur.lastrowid)

    def resolve_incident(self, service: str, *, resolved_at: str | None = None) -> int | None:
        """Mark the open incident for a service as resolved. Returns its id or None."""
        incident = self.get_open_incident(service)
        if not incident:
            return None
        with self._conn() as conn:
            conn.execute(
                "UPDATE incidents SET status='resolved', resolved_at=? WHERE id=?",
                (resolved_at or _now(), incident.id),
            )
        return incident.id

    def set_summary(self, incident_id: int, summary: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE incidents SET summary=? WHERE id=?", (summary, incident_id))

    def get_open_incident(self, service: str) -> Incident | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM incidents WHERE service=? AND status='open' "
                "ORDER BY id DESC LIMIT 1",
                (service,),
            ).fetchone()
        return _to_incident(row) if row else None

    def get_incident(self, incident_id: int) -> Incident | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        return _to_incident(row) if row else None

    def list_incidents(self, limit: int = 100) -> list[Incident]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_to_incident(r) for r in rows]

    # --- eval scores -------------------------------------------------------
    def record_eval(
        self,
        labeled_set_size: int,
        catch_rate: float,
        false_positive_rate: float,
        details: str | None = None,
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO eval_scores
                   (run_at, labeled_set_size, catch_rate, false_positive_rate, details)
                   VALUES (?, ?, ?, ?, ?)""",
                (_now(), labeled_set_size, catch_rate, false_positive_rate, details),
            )
            return int(cur.lastrowid)

    # --- remediation -------------------------------------------------------
    def log_remediation(
        self,
        service: str,
        *,
        proposed_action: str | None,
        confidence: float | None,
        gate_decision: str,
        reason: str | None,
        recovered: bool | None = None,
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO remediation_log
                   (logged_at, service, proposed_action, confidence, gate_decision,
                    reason, recovered)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    _now(),
                    service,
                    proposed_action,
                    confidence,
                    gate_decision,
                    reason,
                    None if recovered is None else int(recovered),
                ),
            )
            return int(cur.lastrowid)


def _to_incident(row: sqlite3.Row | dict[str, Any]) -> Incident:
    return Incident(
        id=row["id"],
        service=row["service"],
        public_id=row["public_id"],
        monitor_id=row["monitor_id"],
        status=row["status"],
        started_at=row["started_at"],
        detected_at=row["detected_at"],
        resolved_at=row["resolved_at"],
        alert_transition=row["alert_transition"],
        summary=row["summary"],
        raw_alert=row["raw_alert"],
    )
