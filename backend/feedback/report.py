"""Report generation: one model call over a stored event log, validated, with the Overall Signal
computed in code.

The model submits its evaluation through the strict `submit_report` tool (Opus 5.5 rejects a
forced `tool_choice`, so the prompt instructs the call, as in problem prep). The input is
validated (schema, 1-4 scores, 1-3 evidence items, every evidence `t_ms` present in the event log)
and the call retried once, with the problems found, before `ReportFailed` is raised.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.agent.model import ModelClient, ModelError, ModelRequest, ToolCall, Usage
from backend.db import Event, SessionRecord
from backend.feedback.metrics import compute_metrics
from backend.feedback.prompt import REPORT_SYSTEM_PROMPT
from backend.feedback.rubric import DIMENSION_KEYS, DIMENSIONS, overall_signal

logger = logging.getLogger(__name__)

REPORT_MAX_TOKENS = 32_000
ATTEMPTS = 2  # one retry
CORRECTNESS_NOTE = "Assessed by reading the code, not by executing it."
WRAP_UP = "wrap_up"  # the Phase whose start freezes the code judged for Correctness


class ReportFailed(Exception):
    """Report generation failed after its retry; the Session becomes `report_failed`."""


# --- the tool --------------------------------------------------------------------------------

def _object(properties: dict[str, Any], description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    if description:
        schema["description"] = description
    return schema


_EVIDENCE = _object(
    {
        "t_ms": {
            "type": "integer",
            "description": "Copied exactly from the timeline entry this evidence refers to.",
        },
        "quote_or_code": {"type": "string"},
        "comment": {"type": "string"},
    }
)

_DIMENSION_SCORE = _object(
    {
        "score": {"type": "integer", "enum": [1, 2, 3, 4]},
        "evidence": {
            "type": "array",
            "items": _EVIDENCE,
            "description": "One to three evidence items.",
        },
    }
)

SUBMIT_REPORT_TOOL: dict[str, Any] = {
    "name": "submit_report",
    "description": "Submit the feedback report for this interview. Call exactly once.",
    "strict": True,
    "input_schema": _object(
        {
            "summary": {"type": "string"},
            "signal_rationale": {"type": "string"},
            "rubric": _object({d.key: _DIMENSION_SCORE for d in DIMENSIONS}),
        }
    ),
}


# --- validation ------------------------------------------------------------------------------

class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class _Evidence(_Model):
    t_ms: int
    quote_or_code: str = Field(min_length=1)
    comment: str = Field(min_length=1)


class _Score(_Model):
    score: Literal[1, 2, 3, 4]
    evidence: list[_Evidence] = Field(min_length=1, max_length=3)


class _Rubric(_Model):
    problem_understanding: _Score
    approach: _Score
    communication: _Score
    code_quality: _Score
    correctness: _Score
    testing: _Score
    complexity: _Score
    coachability: _Score
    time_management: _Score


assert tuple(_Rubric.model_fields) == DIMENSION_KEYS, "the validator must match the rubric"


class Submission(_Model):
    summary: str = Field(min_length=1)
    signal_rationale: str = Field(min_length=1)
    rubric: _Rubric

    def scores(self) -> dict[str, _Score]:
        return {key: getattr(self.rubric, key) for key in DIMENSION_KEYS}


def validate_submission(value: Any, log_t_ms: set[int]) -> tuple[Submission | None, list[str]]:
    """The submission if valid, else the problems found (fed back to the model on retry)."""
    try:
        submission = Submission.model_validate(value)
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(p) for p in err['loc']) or '(input)'}: {err['msg']}"
            for err in exc.errors()
        ]
        return None, problems
    problems = [
        f"rubric.{key}.evidence: t_ms {e.t_ms} is not the timestamp of any timeline entry"
        for key, score in submission.scores().items()
        for e in score.evidence
        if e.t_ms not in log_t_ms
    ]
    return (None, problems) if problems else (submission, [])


# --- the prompt ------------------------------------------------------------------------------

def _clock(t_ms: int) -> str:
    seconds = t_ms // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _stamp(t_ms: int) -> str:
    return f"[t_ms={t_ms} {_clock(t_ms)}]"


def _clip(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n[... {len(text) - limit} more chars]"


def _numbered(code: str) -> str:
    return "\n".join(f"{i:>3} | {line}" for i, line in enumerate(code.splitlines(), 1)) or "(empty)"


def correctness_snapshot(events: Sequence[Event]) -> Event | None:
    """The code judged for Correctness: the last snapshot before Wrap-up began, or the final
    snapshot if Wrap-up never began."""
    chosen: Event | None = None
    for event in events:
        if event.type == "phase_changed" and event.payload.get("to") == WRAP_UP:
            break
        if event.type == "code_snapshot":
            chosen = event
    return chosen


def _key_snapshot_seqs(events: Sequence[Event], correctness: Event | None) -> set[int]:
    """Snapshots shown in full: the code each Run executed, the Correctness code and the final
    code. Other edits appear as one-line entries."""
    seqs = {int(e.payload["snapshot_seq"]) for e in events if e.type == "run"}
    snapshots = [e for e in events if e.type == "code_snapshot"]
    if snapshots:
        seqs.add(snapshots[-1].seq)
    if correctness is not None:
        seqs.add(correctness.seq)
    return seqs


def _timeline_entry(event: Event, full_snapshots: set[int]) -> str:
    p, stamp = event.payload, _stamp(event.t_ms)
    if event.type == "session_started":
        return f"{stamp} Session started"
    if event.type == "utterance":
        who = "Interviewer" if p.get("speaker") == "interviewer" else "Candidate"
        via = " (typed)" if p.get("channel") == "text" and who == "Candidate" else ""
        return f"{stamp} {who}{via}: {p.get('text', '')}"
    if event.type == "code_snapshot":
        change = f"+{p.get('chars_added', 0)}/-{p.get('chars_removed', 0)} chars"
        if event.seq in full_snapshots:
            return f"{stamp} Code snapshot #{event.seq} ({change}):\n{_numbered(str(p.get('code', '')))}"
        return f"{stamp} Code edited ({change})"
    if event.type == "run":
        timed_out = " (timed out)" if p.get("timed_out") else ""
        stdin = f"stdin:\n{_clip(str(p['stdin']))}\n" if p.get("stdin") else ""
        return (
            f"{stamp} Run of code snapshot #{p.get('snapshot_seq')}: exit {p.get('exit_code')}"
            f"{timed_out}\n{stdin}"
            f"stdout:\n{_clip(str(p.get('stdout', ''))) or '(empty)'}\n"
            f"stderr:\n{_clip(str(p.get('stderr', ''))) or '(empty)'}"
        )
    if event.type == "clarification":
        return f"{stamp} Clarification (by {p.get('by')}): Q: {p.get('question')} A: {p.get('answer')}"
    if event.type == "session_ended":
        return f"{stamp} Session ended ({p.get('reason')})"
    return f"{stamp} {event.type}: {json.dumps(p, sort_keys=True)}"


def build_report_message(
    record: SessionRecord, events: Sequence[Event], metrics: dict[str, Any]
) -> str:
    """The single user message for the Report call, derived only from the stored Session."""
    correctness = correctness_snapshot(events)
    full = _key_snapshot_seqs(events, correctness)
    timeline = [_timeline_entry(e, full) for e in events]
    clarifications = [
        f"- Q: {e.payload.get('question')} A: {e.payload.get('answer')} (by {e.payload.get('by')})"
        for e in events
        if e.type == "clarification"
    ]
    settings = record.settings
    correctness_code = (
        f"Code snapshot #{correctness.seq} {_stamp(correctness.t_ms)}:\n"
        f"{_numbered(str(correctness.payload.get('code', '')))}"
        if correctness is not None
        else "(the candidate wrote no code)"
    )
    return "\n\n".join(
        [
            f"<problem>\n{record.problem_md}\n</problem>",
            f"<starter_code>\n{record.starter_code or '(none)'}\n</starter_code>",
            f"<private_notes>\n{record.private_notes or '(none)'}\n</private_notes>",
            "<problem_brief>\n"
            + json.dumps(record.problem_brief or {}, indent=2, sort_keys=True)
            + "\n</problem_brief>",
            f"<settings>\nduration: {settings.get('duration_min')} min\n"
            f"editor autocomplete: {'on' if settings.get('autocomplete') else 'off'}\n</settings>",
            "<clarifications>\n" + ("\n".join(clarifications) or "(none)") + "\n</clarifications>",
            "<timeline>\n" + "\n\n".join(timeline) + "\n</timeline>",
            f"<code_for_correctness>\n{correctness_code}\n</code_for_correctness>",
            "<metrics>\n" + json.dumps(metrics, indent=2, sort_keys=True) + "\n</metrics>",
        ]
    )


# --- generation ------------------------------------------------------------------------------

@dataclass(frozen=True)
class GeneratedReport:
    model: str
    """The model that served the accepted attempt."""
    report: dict[str, Any]
    metrics: dict[str, Any]
    usage: dict[str, int]
    """Token usage summed over every attempt (failed ones cost tokens too)."""


def _assemble(submission: Submission, events: Sequence[Event]) -> dict[str, Any]:
    scores = submission.scores()
    signal = overall_signal({key: s.score for key, s in scores.items()})
    correctness = correctness_snapshot(events)
    return {
        "summary": submission.summary,
        "overall_signal": {
            "label": signal.label,
            "weighted_average": round(float(signal.weighted_average), 2),
            "capped": signal.capped,
            "rationale": submission.signal_rationale,
        },
        "rubric": [
            {
                "dimension": d.key,
                "label": d.label,
                "weight": d.weight,
                "score": scores[d.key].score,
                "evidence": [e.model_dump() for e in scores[d.key].evidence],
                "note": CORRECTNESS_NOTE if d.key == "correctness" else None,
            }
            for d in DIMENSIONS
        ],
        "correctness": {
            "executed": False,
            "note": CORRECTNESS_NOTE,
            "snapshot_seq": None if correctness is None else correctness.seq,
            "t_ms": None if correctness is None else correctness.t_ms,
        },
    }


def _add_usage(total: dict[str, int], usage: Usage) -> None:
    for field in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        total[field] = total.get(field, 0) + int(getattr(usage, field))


async def generate_report(
    model: ModelClient, *, model_id: str, record: SessionRecord, events: Sequence[Event]
) -> GeneratedReport:
    """Evaluate one stored Session. Raises ReportFailed after the retry."""
    metrics = compute_metrics(events)
    message = build_report_message(record, events, metrics)
    log_t_ms = {e.t_ms for e in events}
    usage: dict[str, int] = {}
    problems: list[str] = []
    for attempt in range(1, ATTEMPTS + 1):
        content = message
        if problems:
            content += (
                "\n\n<previous_attempt_problems>\nYour previous submit_report call was rejected:\n"
                + "\n".join(f"- {p}" for p in problems[:20])
                + "\nFix these and call submit_report again.\n</previous_attempt_problems>"
            )
        request = ModelRequest(
            model=model_id,
            system=REPORT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            tools=[SUBMIT_REPORT_TOOL],
            max_tokens=REPORT_MAX_TOKENS,
            effort="high",
        )
        served_by = model_id
        calls: list[ToolCall] = []
        try:
            async for event in model.stream(request):
                if isinstance(event, Usage):
                    _add_usage(usage, event)
                    served_by = event.model
                elif isinstance(event, ToolCall):
                    calls.append(event)
        except ModelError as exc:
            logger.warning("report attempt %d failed: %s (%s)", attempt, exc.message, exc.code)
            problems = []
            continue
        except Exception:
            logger.exception("report attempt %d failed", attempt)
            problems = []
            continue
        submitted = [c for c in calls if c.name == SUBMIT_REPORT_TOOL["name"]]
        if not submitted:
            problems = ["no submit_report call was made"]
        else:
            submission, problems = validate_submission(submitted[-1].input, log_t_ms)
            if submission is not None:
                return GeneratedReport(
                    model=served_by,
                    report=_assemble(submission, events),
                    metrics=metrics,
                    usage={**usage, "attempts": attempt},
                )
        logger.warning("report attempt %d was invalid: %s", attempt, "; ".join(problems[:5]))
    raise ReportFailed("The Report could not be generated. Please retry.")
