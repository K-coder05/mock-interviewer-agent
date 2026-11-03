"""Report seam test harness, reused by every Report test (tickets 05-08).

- EventLog: writes a stored event log for a Session directly (fixtures), with times in seconds
  since Session start. Logs built through the Live Session seam work just as well: the Report
  only ever reads the Store.
- submit_report(): a valid `submit_report` tool call whose fields can be overridden, so a test
  states only what it cares about (scores, evidence, a malformed field...).
- ReportHarness: a real Store (temp SQLite file) and ReportGenerator driven by a ScriptedModel.
  `await generate(sid)` runs generation to completion and returns what `GET report` would.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.agent.model import ToolCall
from backend.agent.prep import ProblemBrief
from backend.db import Event, ReportRecord, SessionRecord, Store
from backend.feedback.generator import ReportGenerator
from backend.feedback.rubric import DIMENSION_KEYS
from tests.harness import DEFAULT_BRIEF, DEFAULT_MODELS, ScriptedModel


def traced(t: float, input: str, *, expected: str = "", category: str = "Typical case") -> dict[str, Any]:
    """A `traced_tests` item at `t` seconds; `expected` empty means no expectation was stated."""
    return {
        "t_ms": round(t * 1000),
        "input": input,
        "expected_result": expected,
        "expected_stated": bool(expected),
        "category": category,
    }


def submit_report(
    scores: Mapping[str, int] | None = None,
    *,
    evidence_t_ms: int = 0,
    summary: str = "You clarified well but tested late.",
    rationale: str = "Solid approach; testing was thin.",
    executed: Mapping[str, str] | None = None,
    traced: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> ToolCall:
    """A valid `submit_report` call. Every dimension scores 3 (or `scores[key]`) with one evidence
    item at `evidence_t_ms` (t=0 always exists: `session_started`). `overrides` replace top-level
    fields of the tool input verbatim. `executed` maps test ids ("x1"...) to categories; `traced`
    is the `traced_tests` list."""
    rubric = {
        key: {
            "score": (scores or {}).get(key, 3),
            "evidence": [
                {"t_ms": evidence_t_ms, "quote_or_code": f"{key} quote", "comment": f"{key} note"}
            ],
        }
        for key in DIMENSION_KEYS
    }
    payload: dict[str, Any] = {
        "summary": summary,
        "signal_rationale": rationale,
        "rubric": rubric,
        "executed_test_categories": [{"id": i, "category": c} for i, c in (executed or {}).items()],
        "traced_tests": traced or [],
        **overrides,
    }
    return ToolCall("submit_report", payload)


class EventLog:
    """Appends events to one Session's log. `at` is seconds since Session start."""

    def __init__(self, store: Store, record: SessionRecord) -> None:
        self._store = store
        self.record = record
        self.code_now = record.starter_code or ""
        self._snapshot_seq: int | None = None

    @property
    def id(self) -> str:
        return self.record.id

    def event(self, at: float, type: str, **payload: Any) -> Event:
        return self._store.append_event(self.id, t_ms=round(at * 1000), type=type, payload=payload)

    def say(self, at: float, text: str, *, speaker: str = "user") -> Event:
        t_ms = round(at * 1000)
        return self.event(
            at, "utterance", speaker=speaker, channel="text", text=text, start_ms=t_ms, end_ms=t_ms
        )

    def code(self, at: float, code: str) -> Event:
        self.code_now = code
        event = self.event(
            at, "code_snapshot", code=code, diff_from_prev="", chars_added=len(code), chars_removed=0
        )
        self._snapshot_seq = event.seq
        return event

    def run(
        self, at: float, *, stdout: str = "", stderr: str = "", exit_code: int = 0, stdin: str = ""
    ) -> Event:
        assert self._snapshot_seq is not None, "a Run needs a code snapshot first"
        return self.event(
            at,
            "run",
            snapshot_seq=self._snapshot_seq,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=40,
            timed_out=False,
            truncated=False,
        )

    def end(self, at: float, *, reason: str = "user") -> Event:
        event = self.event(at, "session_ended", reason=reason, final_code=self.code_now)
        self._store.end_session(self.id)
        return event


class ReportHarness:
    def __init__(self, db_path: Path) -> None:
        self.model = ScriptedModel()
        self.store = Store(db_path)
        self.reports = ReportGenerator(
            store=self.store, model=self.model, model_id=DEFAULT_MODELS.report
        )

    async def aclose(self) -> None:
        await self.reports.close()
        self.store.close()

    def session(
        self,
        *,
        problem_md: str = "# Two Sum\n\nReturn indices of two numbers adding to target.",
        starter_code: str | None = None,
        brief: ProblemBrief | None = DEFAULT_BRIEF,
    ) -> EventLog:
        """A Session with its opening events at t=0 (session_started, starter snapshot)."""
        record = self.store.create_session(
            title=problem_md.lstrip("# ").splitlines()[0],
            problem_md=problem_md,
            starter_code=starter_code,
            private_notes=None,
            settings={
                "duration_min": 45,
                "timeout_grace_s": 60,
                "autocomplete": False,
                "style": {"preset": "faang_standard"},
                "models": {
                    "prep": DEFAULT_MODELS.prep,
                    "interviewer": DEFAULT_MODELS.interviewer,
                    "report": DEFAULT_MODELS.report,
                },
            },
            problem_brief=brief,
        )
        log = EventLog(self.store, record)
        log.event(0, "session_started", problem_md=problem_md, starter_code=starter_code,
                  settings=record.settings)
        if starter_code is not None:
            log.code(0, starter_code)
        return log

    def ended_session(self) -> EventLog:
        """A short, ended Session: a clarifying question, code, one Run and the end."""
        log = self.session()
        log.say(30, "Can the input be empty?")
        log.say(35, "No, it always has at least two numbers.", speaker="interviewer")
        log.code(300, "def two_sum(nums, target):\n    return [0, 1]\n")
        log.run(320, stdout="[0, 1]\n")
        log.end(600)
        return log

    async def generate(self, session_id: str) -> dict[str, Any]:
        """Generate (or regenerate) the Report to completion; returns the `GET report` view."""
        self.reports.start(session_id)
        await self.reports.wait(session_id)
        view = self.reports.view(session_id)
        assert view is not None
        return view

    def report(self, session_id: str) -> ReportRecord | None:
        return self.store.get_report(session_id)

    def status(self, session_id: str) -> str:
        record = self.store.get_session(session_id)
        assert record is not None
        return record.status


__all__ = ["EventLog", "ReportHarness", "submit_report", "traced"]
