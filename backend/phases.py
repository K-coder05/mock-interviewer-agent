"""Phases: a descriptive label for where the Session is. Derived from `phase_changed` events.

A Session starts in `clarify` (no event is logged for that). A Phase is a label, not a gate: it
can move in any direction, by the Interviewer (`agent`) or the Candidate (`user`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from backend.db import Event

PHASES = ("clarify", "approach", "implement", "test", "wrap_up")
FIRST_PHASE = PHASES[0]
WRAP_UP = "wrap_up"

# Minutes after which the Interviewer is told to bring a Phase to a close.
OVERRUN_MIN = {"clarify": 8, "approach": 10, "implement": 25, "test": 10}

ChangedBy = Literal["agent", "user"]


@dataclass(frozen=True)
class PhaseState:
    phase: str
    since_ms: int
    user_changed_ms: int | None
    """When the Candidate last set the Phase (None if never)."""


def current(events: Sequence[Event]) -> PhaseState:
    state = PhaseState(FIRST_PHASE, 0, None)
    for e in events:
        if e.type == "phase_changed" and e.payload.get("to") in PHASES:
            by_user = e.payload.get("by") == "user"
            state = PhaseState(
                str(e.payload["to"]), e.t_ms, e.t_ms if by_user else state.user_changed_ms
            )
    return state


def time_per_phase(events: Sequence[Event], end_ms: int) -> dict[str, int]:
    """Milliseconds spent in each Phase, summing every interval (Phases can be revisited)."""
    totals = dict.fromkeys(PHASES, 0)
    phase, since = FIRST_PHASE, 0
    for e in events:
        if e.type == "phase_changed" and e.payload.get("to") in PHASES:
            totals[phase] += max(0, e.t_ms - since)
            phase, since = str(e.payload["to"]), e.t_ms
    totals[phase] += max(0, end_ms - since)
    return totals
