"""History and replay: the Session list and everything the replay page needs, read from the
stored events (and the Report, when there is one)."""

from __future__ import annotations

from typing import Any

from backend.db import Event, Store
from backend.feedback.metrics import silence_gaps


def duration_ms(events: list[Event]) -> int:
    """How long the Session ran: its end event, else its last event."""
    ended = next((e for e in events if e.type == "session_ended"), None)
    return ended.t_ms if ended else max((e.t_ms for e in events), default=0)


def list_history(store: Store) -> list[dict[str, Any]]:
    """Past Sessions, newest first: title, date, duration and Overall Signal (None while there is
    no Report)."""
    rows = []
    for record in store.list_sessions():
        report = store.get_report(record.id)
        signal = report.report.get("overall_signal") if report else None
        rows.append(
            {
                "id": record.id,
                "title": record.title,
                "created_at": record.created_at,
                "status": record.status,
                "duration_ms": duration_ms(store.events(record.id)),
                "overall_signal": signal["label"] if signal else None,
            }
        )
    return rows


def _marker(kind: str, t_ms: int, label: str, end_ms: int | None = None) -> dict[str, Any]:
    return {"kind": kind, "t_ms": t_ms, "end_ms": end_ms, "label": label}


def markers(events: list[Event], end_ms: int) -> list[dict[str, Any]]:
    """Timeline markers: Runs, Hints, Phase changes and silence gaps, in time order."""
    found = []
    for e in events:
        if e.type == "run":
            ok = e.payload.get("exit_code") == 0 and not e.payload.get("timed_out")
            found.append(_marker("run", e.t_ms, "Run passed" if ok else "Run failed"))
        elif e.type == "hint_given":
            found.append(_marker("hint", e.t_ms, f"Hint L{e.payload.get('level')}"))
        elif e.type == "phase_changed":
            found.append(_marker("phase", e.t_ms, f"Phase: {e.payload.get('to')}"))
    for gap in silence_gaps(events, end_ms):
        seconds = gap["duration_ms"] // 1000
        label = f"Silence {seconds // 60}:{seconds % 60:02d}"
        found.append(_marker("silence", gap["start_ms"], label, gap["end_ms"]))
    return sorted(found, key=lambda m: m["t_ms"])


def replay(store: Store, session_id: str) -> dict[str, Any] | None:
    """The Session, its events (the Interviewer's private notes left out) and the markers."""
    record = store.get_session(session_id)
    if record is None:
        return None
    events = store.events(session_id)
    end_ms = duration_ms(events)
    return {
        "session": record.to_public_dict(),
        "events": [e.to_dict() for e in events if e.type != "interviewer_note"],
        "duration_ms": end_ms,
        "markers": markers(events, end_ms),
    }
