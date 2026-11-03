"""Builds the Interviewer's prompt: a stable system prompt and a per-call turn message.

The system prompt (rules, persona, problem, private notes, Problem Brief) never changes during a
Session, so it is prompt-cached. Everything that changes is rebuilt from the event log on every
decision call; there is no running message history.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.db import Event

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


def build_turn_message(events: Sequence[Event], *, now_ms: int, trigger: str) -> str:
    """The single user message for a decision call, derived only from the event log."""
    clarifications: list[str] = []
    transcript: list[str] = []
    code = ""
    runs: list[Event] = []
    for event in events:
        p = event.payload
        if event.type == "utterance":
            who = "Interviewer" if p["speaker"] == "interviewer" else "Candidate"
            via = " (typed)" if p.get("channel") == "text" and who == "Candidate" else ""
            transcript.append(f"[{_clock(event.t_ms)}] {who}{via}: {p['text']}")
        elif event.type == "clarification":
            clarifications.append(f"- Q: {p['question']} A: {p['answer']} (by {p['by']})")
        elif event.type == "code_snapshot":
            code = p["code"]
        elif event.type == "run":
            runs.append(event)

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
            "<clarifications>\n" + ("\n".join(clarifications) or "(none yet)") + "\n</clarifications>",
            "<transcript>\n" + ("\n".join(transcript) or "(nothing said yet)") + "\n</transcript>",
            "<current_code>\n" + (numbered or "(empty)") + "\n</current_code>",
            "<recent_runs>\n" + ("\n\n".join(run_lines) or "(no runs yet)") + "\n</recent_runs>",
            f"<trigger>{trigger}</trigger>",
        ]
    )
