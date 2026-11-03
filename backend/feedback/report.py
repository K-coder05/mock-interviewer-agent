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
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.agent.model import ModelClient, ModelError, ModelRequest, ToolCall, Usage
from backend.db import Event, SessionRecord
from backend.feedback.metrics import compute_metrics
from backend.feedback.prompt import REPORT_SYSTEM_PROMPT
from backend.feedback.rubric import DIMENSION_KEYS, DIMENSIONS, overall_signal
from backend.feedback.tests import ExecutedTest, extract_executed_tests

logger = logging.getLogger(__name__)

REPORT_MAX_TOKENS = 32_000
ATTEMPTS = 2  # one retry
CORRECTNESS_NOTE = "Assessed by reading the code, not by executing it."
WRAP_UP = "wrap_up"  # the Phase whose start freezes the code judged for Correctness
TYPICAL = "Typical case"
OTHER = "Other"


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

_EXECUTED_CATEGORY = _object(
    {
        "id": {"type": "string", "description": "An id from <candidate_tests>, e.g. x1."},
        "category": {"type": "string"},
    }
)

_TRACED_TEST = _object(
    {
        "t_ms": {
            "type": "integer",
            "description": "Copied exactly from the Candidate utterance where the walk-through began.",
        },
        "input": {"type": "string", "description": "The concrete input, as the Candidate said it."},
        "expected_result": {
            "type": "string",
            "description": "The expected result the Candidate stated, or an empty string.",
        },
        "expected_stated": {"type": "boolean"},
        "category": {"type": "string"},
    }
)

_STRENGTH = _object(
    {
        "title": {"type": "string", "description": "A few words naming the strength."},
        "detail": {"type": "string", "description": "One or two sentences citing what happened."},
    }
)

_IMPROVEMENT = _object(
    {
        "title": {"type": "string", "description": "A few words naming the weakness."},
        "detail": {"type": "string", "description": "One or two sentences citing what happened."},
        "drill": {
            "type": "string",
            "description": "One concrete thing to practice next session, e.g. 'Say the "
            "complexity out loud before your first line of code.'",
        },
    }
)

_IDEAL_WALKTHROUGH = _object(
    {
        "approach": {
            "type": "string",
            "description": "How a strong candidate would handle this problem, step by step: "
            "clarifying, brute force, the optimal approach, tests worth running.",
        },
        "complexity": {"type": "string", "description": "Time and space of the optimal solution."},
        "code": {"type": "string", "description": "The optimal solution in Python 3."},
    },
    "The only place a solution is shown; the app hides `code` until the Candidate reveals it.",
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
            "executed_test_categories": {
                "type": "array",
                "items": _EXECUTED_CATEGORY,
                "description": "One entry per test id in <candidate_tests>.",
            },
            "traced_tests": {
                "type": "array",
                "items": _TRACED_TEST,
                "description": "Tests the Candidate walked through by hand without running them.",
            },
            "strengths": {
                "type": "array",
                "items": _STRENGTH,
                "description": "Exactly three, most important first.",
            },
            "improvements": {
                "type": "array",
                "items": _IMPROVEMENT,
                "description": "Exactly three, most important first, each with a drill.",
            },
            "ideal_walkthrough": _IDEAL_WALKTHROUGH,
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


class _ExecutedCategory(_Model):
    id: str
    category: str


class _TracedTest(_Model):
    t_ms: int
    input: str = Field(min_length=1)
    expected_result: str
    expected_stated: bool
    category: str


class _Strength(_Model):
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class _Improvement(_Strength):
    drill: str = Field(min_length=1)


class _IdealWalkthrough(_Model):
    approach: str = Field(min_length=1)
    complexity: str = Field(min_length=1)
    code: str = Field(min_length=1)


class Submission(_Model):
    summary: str = Field(min_length=1)
    signal_rationale: str = Field(min_length=1)
    rubric: _Rubric
    executed_test_categories: list[_ExecutedCategory]
    traced_tests: list[_TracedTest]
    strengths: list[_Strength] = Field(min_length=3, max_length=3)
    improvements: list[_Improvement] = Field(min_length=3, max_length=3)
    ideal_walkthrough: _IdealWalkthrough

    def scores(self) -> dict[str, _Score]:
        return {key: getattr(self.rubric, key) for key in DIMENSION_KEYS}


def test_categories(record: SessionRecord) -> list[str]:
    """The categories a test can be filed under: the brief's Edge-Case Categories, then two
    catch-alls."""
    brief = record.problem_brief or {}
    names = [c["name"] for c in brief.get("edge_case_categories", [])]
    return list(dict.fromkeys([*names, TYPICAL, OTHER]))


def validate_submission(
    value: Any,
    log_t_ms: set[int],
    *,
    test_ids: Collection[str] = (),
    categories: Sequence[str] = (TYPICAL, OTHER),
) -> tuple[Submission | None, list[str]]:
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
    filed = [t.id for t in submission.executed_test_categories]
    if missing := sorted(set(test_ids) - set(filed)):
        problems.append(f"executed_test_categories: no category for {', '.join(missing)}")
    if len(set(filed)) != len(filed):
        problems.append("executed_test_categories: each test id must appear once")
    allowed = ", ".join(f'"{c}"' for c in categories)
    for tagged in submission.executed_test_categories:
        if tagged.id not in test_ids:
            problems.append(f"executed_test_categories: {tagged.id!r} is not a test id")
        if tagged.category not in categories:
            problems.append(
                f"executed_test_categories: category {tagged.category!r} must be one of {allowed}"
            )
    for traced in submission.traced_tests:
        if traced.t_ms not in log_t_ms:
            problems.append(
                f"traced_tests: t_ms {traced.t_ms} is not the timestamp of any timeline entry"
            )
        if traced.category not in categories:
            problems.append(f"traced_tests: category {traced.category!r} must be one of {allowed}")
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


def _describe_test(test: ExecutedTest) -> str:
    source = test.source if "\n" not in test.source else "\n" + test.source
    return (
        f"- {test.id} [{_stamp(test.t_ms)}] {test.form}, "
        f"{'expectation stated' if test.verified else 'no expectation stated'}, "
        f"{'stopped the run' if test.outcome == 'failed' else 'ran'}: {source}"
    )


def build_report_message(
    record: SessionRecord,
    events: Sequence[Event],
    metrics: dict[str, Any],
    tests: Sequence[ExecutedTest] = (),
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
            "<candidate_tests>\nExecuted tests found in the code the candidate ran (extracted in code):\n"
            + ("\n".join(_describe_test(t) for t in tests) or "(none)")
            + "\nFile each under one of these categories: "
            + ", ".join(f'"{c}"' for c in test_categories(record))
            + "\n</candidate_tests>",
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


def _testing(
    submission: Submission, record: SessionRecord, tests: Sequence[ExecutedTest]
) -> dict[str, Any]:
    """The testing breakdown: tests grouped by category, executed ones that ran without a stated
    expectation listed apart, and the brief's Edge-Case Categories no test covered."""
    tagged = {c.id: c.category for c in submission.executed_test_categories}
    entries: list[dict[str, Any]] = [
        {
            "id": t.id,
            "kind": "executed",
            "form": t.form,
            "input": t.source,
            "verified": t.verified,
            "outcome": t.outcome,
            "expected_result": None,
            "category": tagged.get(t.id, OTHER),
            "t_ms": t.t_ms,
            "runs": t.runs,
        }
        for t in tests
    ] + [
        {
            "id": f"t{i}",
            "kind": "traced",
            "form": "traced",
            "input": t.input,
            "verified": t.expected_stated,
            "outcome": None,
            "expected_result": t.expected_result if t.expected_stated and t.expected_result else None,
            "category": t.category,
            "t_ms": t.t_ms,
            "runs": 0,
        }
        for i, t in enumerate(submission.traced_tests, 1)
    ]
    unverified = [e for e in entries if e["kind"] == "executed" and not e["verified"]]
    covered = {e["category"] for e in entries}
    brief = record.problem_brief or {}
    return {
        "groups": [
            {"category": c, "tests": [e for e in entries if e["category"] == c and e not in unverified]}
            for c in test_categories(record)
            if any(e["category"] == c and e not in unverified for e in entries)
        ],
        "ran_but_not_verified": unverified,
        "missed_categories": [
            c for c in brief.get("edge_case_categories", []) if c["name"] not in covered
        ],
        "totals": {
            "executed": sum(e["kind"] == "executed" for e in entries),
            "traced": sum(e["kind"] == "traced" for e in entries),
            "verified": sum(bool(e["verified"]) for e in entries),
        },
    }


def _assemble(
    submission: Submission,
    events: Sequence[Event],
    record: SessionRecord,
    tests: Sequence[ExecutedTest],
) -> dict[str, Any]:
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
        "testing": _testing(submission, record, tests),
        "strengths": [s.model_dump() for s in submission.strengths],
        "improvements": [i.model_dump() for i in submission.improvements],
        "ideal_walkthrough": submission.ideal_walkthrough.model_dump(),
        "autocomplete": bool(record.settings.get("autocomplete")),
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
    tests = extract_executed_tests(events)
    metrics = compute_metrics(events, tests)
    categories = test_categories(record)
    message = build_report_message(record, events, metrics, tests)
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
            submission, problems = validate_submission(
                submitted[-1].input,
                log_t_ms,
                test_ids={t.id for t in tests},
                categories=categories,
            )
            if submission is not None:
                return GeneratedReport(
                    model=served_by,
                    report=_assemble(submission, events, record, tests),
                    metrics=metrics,
                    usage={**usage, "attempts": attempt},
                )
        logger.warning("report attempt %d was invalid: %s", attempt, "; ".join(problems[:5]))
    raise ReportFailed("The Report could not be generated. Please retry.")
