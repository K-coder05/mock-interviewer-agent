"""SQLite storage: sessions, the append-only event log, and reports.

The Store is the only module that touches SQL. It assigns each event's `seq`, so ordering is
server-owned and survives engine restarts.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from backend.ids import new_id

SessionStatus = Literal["live", "ended", "abandoned", "report_ready", "report_failed"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  ended_at TEXT,
  title TEXT,
  problem_md TEXT NOT NULL,
  starter_code TEXT,
  private_notes TEXT,
  settings_json TEXT NOT NULL,
  problem_brief_json TEXT,
  status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  seq INTEGER NOT NULL,
  t_ms INTEGER NOT NULL,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  UNIQUE(session_id, seq)
);
CREATE TABLE IF NOT EXISTS reports (
  session_id TEXT PRIMARY KEY REFERENCES sessions(id),
  created_at TEXT NOT NULL,
  model TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  report_json TEXT NOT NULL,
  usage_json TEXT
);
"""


@dataclass(frozen=True)
class SessionRecord:
    id: str
    created_at: str
    ended_at: str | None
    title: str
    problem_md: str
    starter_code: str | None
    private_notes: str | None
    settings: dict[str, Any]
    problem_brief: dict[str, Any] | None
    status: SessionStatus

    def to_public_dict(self) -> dict[str, Any]:
        """Fields safe to send to the client (never private notes or the Problem Brief)."""
        return {
            "id": self.id,
            "created_at": self.created_at,
            "ended_at": self.ended_at,
            "title": self.title,
            "problem_md": self.problem_md,
            "starter_code": self.starter_code,
            "settings": self.settings,
            "status": self.status,
        }


@dataclass(frozen=True)
class Event:
    id: str
    session_id: str
    seq: int
    t_ms: int
    type: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "seq": self.seq,
            "t_ms": self.t_ms,
            "type": self.type,
            "payload": self.payload,
        }


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def create_session(
        self,
        *,
        title: str,
        problem_md: str,
        starter_code: str | None,
        private_notes: str | None,
        settings: dict[str, Any],
        problem_brief: dict[str, Any] | None,
    ) -> SessionRecord:
        record = SessionRecord(
            id=new_id("ses"),
            created_at=datetime.now(timezone.utc).isoformat(),
            ended_at=None,
            title=title,
            problem_md=problem_md,
            starter_code=starter_code,
            private_notes=private_notes,
            settings=settings,
            problem_brief=problem_brief,
            status="live",
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO sessions (id, created_at, ended_at, title, problem_md, starter_code,"
                " private_notes, settings_json, problem_brief_json, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.created_at,
                    record.ended_at,
                    record.title,
                    record.problem_md,
                    record.starter_code,
                    record.private_notes,
                    json.dumps(record.settings),
                    None if problem_brief is None else json.dumps(problem_brief),
                    record.status,
                ),
            )
        return record

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return None if row is None else self._record(row)

    def list_sessions(self) -> list[SessionRecord]:
        """All Sessions, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        return [self._record(r) for r in rows]

    @staticmethod
    def _record(row: sqlite3.Row) -> SessionRecord:
        brief = row["problem_brief_json"]
        return SessionRecord(
            id=row["id"],
            created_at=row["created_at"],
            ended_at=row["ended_at"],
            title=row["title"],
            problem_md=row["problem_md"],
            starter_code=row["starter_code"],
            private_notes=row["private_notes"],
            settings=json.loads(row["settings_json"]),
            problem_brief=None if brief is None else json.loads(brief),
            status=row["status"],
        )

    def end_session(self, session_id: str) -> str:
        """Mark the Session ended now; returns the `ended_at` timestamp."""
        ended_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET status = 'ended', ended_at = ? WHERE id = ?",
                (ended_at, session_id),
            )
        return ended_at

    def append_event(
        self, session_id: str, *, t_ms: int, type: str, payload: dict[str, Any]
    ) -> Event:
        with self._lock, self._conn:
            (max_seq,) = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM events WHERE session_id = ?", (session_id,)
            ).fetchone()
            event = Event(
                id=new_id("evt"),
                session_id=session_id,
                seq=max_seq + 1,
                t_ms=t_ms,
                type=type,
                payload=payload,
            )
            self._conn.execute(
                "INSERT INTO events (id, session_id, seq, t_ms, type, payload_json)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (event.id, session_id, event.seq, t_ms, type, json.dumps(payload)),
            )
        return event

    def events(self, session_id: str, *, after_seq: int = 0) -> list[Event]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE session_id = ? AND seq > ? ORDER BY seq",
                (session_id, after_seq),
            ).fetchall()
        return [
            Event(
                id=r["id"],
                session_id=r["session_id"],
                seq=r["seq"],
                t_ms=r["t_ms"],
                type=r["type"],
                payload=json.loads(r["payload_json"]),
            )
            for r in rows
        ]
