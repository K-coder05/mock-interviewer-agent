"""Deterministic metrics computed from the event log (no model). Ticket 07 adds the rest."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from backend.db import Event


def compute_metrics(events: Sequence[Event]) -> dict[str, Any]:
    runs = [e for e in events if e.type == "run"]
    words = {"user": 0, "interviewer": 0}
    for e in events:
        if e.type == "utterance" and e.payload.get("speaker") in words:
            words[e.payload["speaker"]] += len(str(e.payload.get("text", "")).split())
    ended = next((e for e in events if e.type == "session_ended"), None)
    return {
        "duration_ms": ended.t_ms if ended else (events[-1].t_ms if events else 0),
        "runs": len(runs),
        "failed_runs": sum(
            1 for r in runs if r.payload.get("exit_code") != 0 or r.payload.get("timed_out")
        ),
        "candidate_words": words["user"],
        "interviewer_words": words["interviewer"],
    }
