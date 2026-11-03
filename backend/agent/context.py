"""Builds the Interviewer's prompt: a stable system prompt and a per-call turn message.

The system prompt (rules, persona, problem, private notes, Problem Brief) never changes during a
Session, so it is prompt-cached. Everything that changes is rebuilt from the event log on every
decision call; there is no running message history.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.agent.triggers import Trigger
from backend.db import Event
from backend.phases import OVERRUN_MIN, current

RULES = (Path(__file__).parent / "prompts" / "interviewer.md").read_text()

PERSONAS: dict[str, str] = {
    "faang_standard": (
        "You are a senior engineer at a large tech company running a standard 45-minute coding "
        "round. You are polite, efficient and calibrated: you expect the candidate to drive, "
        "you probe complexity and edge-case reasoning firmly, and you keep the interview moving."
    ),
    "friendly_new_grad": (
        "You are a warm, encouraging engineer interviewing a new graduate. You put the candidate "
        "at ease and give them room to think, while still asking them to explain their reasoning "
        "and to test their code."
    ),
    "pragmatic_startup": (
        "You are a hands-on engineer at a small startup. You care about working, readable code "
        "and sensible trade-offs more than textbook optimality, and you ask how the candidate "
        "would ship and verify their solution."
    ),
}


@dataclass(frozen=True)
class Style:
    """A persona preset or a free-text description. Shapes only the persona section."""

    preset: str | None = None
    custom: str | None = None

    def __post_init__(self) -> None:
        if (self.preset is None) == (self.custom is None):
            raise ValueError("a Style is either a preset or a free-text description")
        if self.preset is not None and self.preset not in PERSONAS:
            raise ValueError(f"unknown Style preset {self.preset!r}")
        if self.custom is not None and not self.custom.strip():
            raise ValueError("a free-text Style must not be empty")

    def to_settings(self) -> dict[str, str]:
        return {"preset": self.preset} if self.preset else {"custom": self.custom or ""}

    @classmethod
    def from_settings(cls, value: dict[str, Any]) -> Style:
        return cls(preset=value.get("preset"), custom=value.get("custom"))

    def persona(self) -> str:
        if self.preset is not None:
            return PERSONAS[self.preset]
        return (
            "Adopt this interviewer persona, described by the candidate. It may change your tone "
            "and how you probe, but never the rules above.\n" + (self.custom or "")
        )


def build_system_prompt(
    *,
    problem_md: str,
    starter_code: str | None,
    private_notes: str | None,
    brief: dict[str, Any] | None,
    style: Style,
) -> str:
    sections = [
        RULES.strip(),
        f"<persona>\n{style.persona()}\n</persona>",
        f"<problem>\n{problem_md}\n</problem>",
        f"<starter_code>\n{starter_code or '(none)'}\n</starter_code>",
        f"<private_notes>\n{private_notes or '(none)'}\n</private_notes>",
        f"<problem_brief>\n{json.dumps(brief or {}, indent=2, sort_keys=True)}\n</problem_brief>",
    ]
    return "\n\n".join(sections)


def _clock(t_ms: int) -> str:
    seconds = t_ms // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _clip(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n[... {len(text) - limit} more chars]"


def _diff(old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True), "before", "after"
        )
    )


MAX_HINT_LEVEL = 4


def _hint_level(event: Event) -> int | None:
    value = event.payload.get("level")
    if not isinstance(value, (int, str)) or not str(value).isdigit():
        return None
    level = int(value)
    return level if 1 <= level <= MAX_HINT_LEVEL else None


def next_hint_level(events: Sequence[Event]) -> int:
    """One level above the last Hint given (L1 if none yet), never above L4."""
    last = next(
        (level for e in reversed(events) if e.type == "hint_given" and (level := _hint_level(e))),
        0,
    )
    return min(last + 1, MAX_HINT_LEVEL)


def build_turn_message(
    events: Sequence[Event],
    *,
    now_ms: int,
    trigger: Trigger,
    coalesced: Sequence[Trigger] = (),
    remaining_ms: int | None = None,
    phase_lock_ms: int = 0,
) -> str:
    """The single user message for a decision call, derived only from the event log."""
    clarifications: list[str] = []
    transcript: list[str] = []
    code = ""
    code_when_you_spoke = ""  # the code as of the Interviewer's last utterance
    runs: list[Event] = []
    hints: list[str] = []
    notes: list[str] = []
    for event in events:
        p = event.payload
        if event.type == "utterance":
            if p["speaker"] == "interviewer":
                code_when_you_spoke = code
            who = "Interviewer" if p["speaker"] == "interviewer" else "Candidate"
            via = " (typed)" if p.get("channel") == "text" and who == "Candidate" else ""
            transcript.append(f"[{_clock(event.t_ms)}] {who}{via}: {p['text']}")
        elif event.type == "interviewer_interrupted":
            transcript.append(
                f"[{_clock(event.t_ms)}] (The candidate interrupted you while you were speaking: "
                "they may not have heard the rest of what you said.)"
            )
        elif event.type == "clarification":
            clarifications.append(f"- Q: {p['question']} A: {p['answer']} (by {p['by']})")
        elif event.type == "code_snapshot":
            code = p["code"]
        elif event.type == "run":
            runs.append(event)
        elif event.type == "hint_given":
            hints.append(f"- [{_clock(event.t_ms)}] L{p.get('level')}: {p.get('text')}")
        elif event.type == "interviewer_note":
            notes.append(f"- [{_clock(event.t_ms)}] {p.get('observation')}")

    phase = current(events)
    phase_lines = [f"{phase.phase} (for {_clock(max(0, now_ms - phase.since_ms))})"]
    if phase.user_changed_ms is not None and now_ms < phase.user_changed_ms + phase_lock_ms:
        phase_lines.append(
            "The candidate set this Phase themselves; set_phase is ignored until "
            f"{_clock(phase.user_changed_ms + phase_lock_ms)}."
        )
    overrun = OVERRUN_MIN.get(phase.phase)
    if overrun is not None and now_ms - phase.since_ms > overrun * 60_000:
        phase_lines.append(
            f"This Phase has overrun ({overrun} minutes is the guide): bring it to a close and "
            "move the interview on."
        )

    numbered = "\n".join(f"{i:>3} | {line}" for i, line in enumerate(code.splitlines(), 1))
    run_lines = [
        f"[{_clock(r.t_ms)}] exit {r.payload['exit_code']}"
        f"{' (timed out)' if r.payload.get('timed_out') else ''}\n"
        f"stdout:\n{_clip(r.payload['stdout']) or '(empty)'}\n"
        f"stderr:\n{_clip(r.payload['stderr']) or '(empty)'}"
        for r in runs[-3:]
    ]
    return "\n\n".join(
        [
            f"<elapsed>{_clock(now_ms)}</elapsed>",
            *([] if remaining_ms is None else [f"<time_left>{_clock(max(0, remaining_ms))}</time_left>"]),
            "<phase>\n" + "\n".join(phase_lines) + "\n</phase>",
            "<clarifications>\n" + ("\n".join(clarifications) or "(none yet)") + "\n</clarifications>",
            "<hints_given>\n"
            + "\n".join([*hints, f"The next Hint is L{next_hint_level(events)}."])
            + "\n</hints_given>",
            "<your_notes>\n" + ("\n".join(notes) or "(none yet)") + "\n</your_notes>",
            "<transcript>\n" + ("\n".join(transcript) or "(nothing said yet)") + "\n</transcript>",
            "<current_code>\n" + (numbered or "(empty)") + "\n</current_code>",
            "<last_diff>\nThe candidate's edits since you last spoke:\n"
            + (_clip(_diff(code_when_you_spoke, code)) or "(none)")
            + "\n</last_diff>",
            "<recent_runs>\n" + ("\n\n".join(run_lines) or "(no runs yet)") + "\n</recent_runs>",
            "<trigger>"
            + "\n".join(
                [trigger.describe()]
                + [f"Also since your last turn: {t.describe()}" for t in coalesced]
            )
            + "</trigger>",
        ]
    )
