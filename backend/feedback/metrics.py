"""Deterministic metrics computed from the event log (no model).

Metrics derived from events that later tickets add (`hint_given`, `mic_muted`/`mic_unmuted`) are
computed from whatever exists, so they report zero until those events are logged.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from backend.db import Event
from backend.feedback.tests import ExecutedTest, extract_executed_tests

SILENCE_GAP_MS = 60_000
LARGE_PASTE_CHARS = 200
"""A paste longer than this is logged as a `paste` event (and shown in the metrics)."""

HINT_LEVELS = (1, 2, 3, 4)
_EXCEPTION = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning))\b")


def _error_type(run: Event) -> str | None:
    """The exception class a failed Run ended with (last traceback line), `TimeoutError` for a
    timeout, else None."""
    if run.payload.get("timed_out"):
        return "TimeoutError"
    if run.payload.get("exit_code") == 0:
        return None
    for line in reversed(str(run.payload.get("stderr", "")).splitlines()):
        if match := _EXCEPTION.match(line.strip()):
            return match.group(1).rsplit(".", 1)[-1]
    return "Unknown"


def _first_code_ms(events: Sequence[Event]) -> int | None:
    """When the Candidate first changed the code from the starter code (or an empty buffer)."""
    started = next((e for e in events if e.type == "session_started"), None)
    starter = str(started.payload.get("starter_code") or "") if started else ""
    for e in events:
        if e.type != "code_snapshot":
            continue
        code = str(e.payload.get("code", ""))
        if code.strip() and code.strip() != starter.strip():
            return e.t_ms
    return None


def _silence_gaps(events: Sequence[Event], end_ms: int) -> list[dict[str, int]]:
    """Stretches over 60 s with no Candidate speech, typing, Run or paste."""
    marks = [0]
    for e in events:
        if e.type in ("run", "paste") or (
            e.type == "utterance" and e.payload.get("speaker") == "user"
        ):
            marks.append(e.t_ms)
        elif e.type == "code_snapshot" and e.t_ms > 0:  # the starter snapshot is at 0
            marks.append(e.t_ms)
    marks = sorted(set(marks)) + [end_ms]
    return [
        {"start_ms": a, "end_ms": b, "duration_ms": b - a}
        for a, b in zip(marks, marks[1:])
        if b - a > SILENCE_GAP_MS
    ]


def _muted_ms(events: Sequence[Event], end_ms: int) -> int:
    total, since = 0, None
    for e in events:
        if e.type == "mic_muted" and since is None:
            since = e.t_ms
        elif e.type == "mic_unmuted" and since is not None:
            total, since = total + e.t_ms - since, None
    return total + (end_ms - since if since is not None else 0)


def compute_metrics(
    events: Sequence[Event], tests: Sequence[ExecutedTest] | None = None
) -> dict[str, Any]:
    if tests is None:
        tests = extract_executed_tests(events)
    runs = [e for e in events if e.type == "run"]
    ended = next((e for e in events if e.type == "session_ended"), None)
    end_ms = ended.t_ms if ended else (events[-1].t_ms if events else 0)
    words = {"user": 0, "interviewer": 0}
    for e in events:
        if e.type == "utterance" and e.payload.get("speaker") in words:
            words[e.payload["speaker"]] += len(str(e.payload.get("text", "")).split())

    first_code = _first_code_ms(events)
    coding_words = coding_wpm = None
    if first_code is not None:
        coding_words = sum(
            len(str(e.payload.get("text", "")).split())
            for e in events
            if e.type == "utterance" and e.payload.get("speaker") == "user" and e.t_ms >= first_code
        )
        minutes = (end_ms - first_code) / 60_000
        coding_wpm = round(coding_words / minutes, 1) if minutes > 0 else 0.0

    spoken = words["user"] + words["interviewer"]
    hints = Counter(
        str(e.payload.get("level")) for e in events if e.type == "hint_given"
    )
    pastes = [
        {"t_ms": e.t_ms, "length": int(e.payload.get("length", 0))}
        for e in events
        if e.type == "paste"
    ]
    return {
        "duration_ms": end_ms,
        "time_to_first_code_ms": first_code,
        "time_to_first_run_ms": runs[0].t_ms if runs else None,
        "time_to_first_test_ms": min((t.t_ms for t in tests), default=None),
        "runs": len(runs),
        "failed_runs": sum(
            1 for r in runs if r.payload.get("exit_code") != 0 or r.payload.get("timed_out")
        ),
        "error_types": dict(Counter(t for r in runs if (t := _error_type(r)))),
        "silence_gaps": _silence_gaps(events, end_ms),
        "candidate_words": words["user"],
        "interviewer_words": words["interviewer"],
        "candidate_talk_ratio": round(words["user"] / spoken, 2) if spoken else None,
        "coding_words": coding_words,
        "coding_words_per_minute": coding_wpm,
        "hints_by_level": {str(level): hints.get(str(level), 0) for level in HINT_LEVELS},
        "large_pastes": pastes,
        "muted_ms": _muted_ms(events, end_ms),
    }
