"""Report seam: a stored event log plus a scripted `submit_report` in, the stored Report out."""

from typing import Any

import pytest

from backend.agent.model import ModelError
from tests.harness import LiveSessionHarness, Usage
from tests.report_harness import ReportHarness, submit_report


async def test_report_has_summary_signal_and_nine_scored_dimensions_with_evidence(
    reports: ReportHarness,
) -> None:
    log = reports.ended_session()
    reports.model.script(submit_report(evidence_t_ms=30_000))

    view = await reports.generate(log.id)

    assert view["status"] == "report_ready"
    report = view["report"]
    assert report["summary"] == "You clarified well but tested late."
    assert report["overall_signal"]["label"] == "Hire"  # every dimension 3 -> 3.0
    assert report["overall_signal"]["rationale"] == "Solid approach; testing was thin."
    assert [row["dimension"] for row in report["rubric"]] == [
        "problem_understanding",
        "approach",
        "communication",
        "code_quality",
        "correctness",
        "testing",
        "complexity",
        "coachability",
        "time_management",
    ]
    for row in report["rubric"]:
        assert row["score"] == 3
        assert [e["t_ms"] for e in row["evidence"]] == [30_000]
    assert reports.status(log.id) == "report_ready"


async def test_report_stores_the_serving_model_and_token_usage(reports: ReportHarness) -> None:
    log = reports.ended_session()
    reports.model.script(
        Usage("claude-opus-5-5", input_tokens=12_000, output_tokens=3_000,
              cache_read_input_tokens=500, cache_creation_input_tokens=0),
        submit_report(),
    )

    view = await reports.generate(log.id)

    assert view["model"] == "claude-opus-5-5"
    assert view["usage"] == {
        "input_tokens": 12_000,
        "output_tokens": 3_000,
        "cache_read_input_tokens": 500,
        "cache_creation_input_tokens": 0,
        "attempts": 1,
    }
    [request] = reports.model.requests
    assert request.model == "claude-opus-5-5"
    assert [t["name"] for t in request.tools] == ["submit_report"]


async def test_correctness_is_labeled_as_assessed_by_reading_not_executed(
    reports: ReportHarness,
) -> None:
    log = reports.ended_session()
    reports.model.script(submit_report())

    report = (await reports.generate(log.id))["report"]

    [correctness] = [r for r in report["rubric"] if r["dimension"] == "correctness"]
    assert "not by executing" in correctness["note"]
    assert report["correctness"]["executed"] is False
    others = [r["note"] for r in report["rubric"] if r["dimension"] != "correctness"]
    assert others == [None] * 8


def _scores(testing: int, correctness: int, others: list[int]) -> dict[str, int]:
    """`others` in rubric order, skipping correctness and testing."""
    keys = ["problem_understanding", "approach", "communication", "code_quality",
            "complexity", "coachability", "time_management"]
    return {**dict(zip(keys, others, strict=True)), "testing": testing, "correctness": correctness}


# Weighted sum / 10 (Testing counts 2x). Expected labels worked out by hand from the spec sheet:
# < 1.75 Strong No, < 2.25 No, < 2.6 Lean No, < 3.0 Lean Hire, < 3.5 Hire, else Strong Hire.
@pytest.mark.parametrize(
    ("scores", "average", "label"),
    [
        (_scores(1, 1, [1, 1, 1, 1, 1, 1, 1]), 1.0, "Strong No"),
        (_scores(2, 2, [2, 2, 1, 1, 2, 2, 1]), 1.7, "Strong No"),
        (_scores(2, 2, [2, 2, 2, 1, 2, 2, 1]), 1.8, "No"),
        (_scores(2, 2, [3, 3, 2, 2, 2, 2, 2]), 2.2, "No"),
        (_scores(2, 2, [3, 3, 3, 2, 2, 2, 2]), 2.3, "Lean No"),
        (_scores(2, 2, [3, 3, 3, 3, 3, 2, 2]), 2.5, "Lean No"),
        (_scores(2, 2, [3, 3, 3, 3, 3, 3, 2]), 2.6, "Lean Hire"),
        (_scores(3, 3, [3, 3, 3, 3, 3, 3, 2]), 2.9, "Lean Hire"),
        (_scores(3, 3, [3, 3, 3, 3, 3, 3, 3]), 3.0, "Hire"),
        (_scores(4, 4, [3, 3, 3, 3, 3, 3, 4]), 3.4, "Hire"),
        (_scores(4, 4, [4, 3, 3, 3, 3, 3, 4]), 3.5, "Strong Hire"),
        (_scores(4, 4, [4, 4, 4, 4, 4, 4, 4]), 4.0, "Strong Hire"),
        # Testing weighs double: the same scores with Testing and Communication swapped differ.
        (_scores(4, 2, [2, 2, 2, 2, 2, 2, 2]), 2.4, "Lean No"),
        (_scores(2, 2, [2, 2, 4, 2, 2, 2, 2]), 2.2, "No"),
    ],
)
async def test_overall_signal_is_computed_from_weighted_scores(
    reports: ReportHarness, scores: dict[str, int], average: float, label: str
) -> None:
    log = reports.ended_session()
    reports.model.script(submit_report(scores))

    signal = (await reports.generate(log.id))["report"]["overall_signal"]

    assert signal["label"] == label
    assert signal["weighted_average"] == average
    assert signal["capped"] is False


@pytest.mark.parametrize(
    ("scores", "uncapped"),
    [
        (_scores(1, 4, [4, 4, 4, 4, 4, 4, 4]), "Hire"),  # 3.4
        (_scores(4, 1, [4, 4, 4, 4, 4, 4, 4]), "Strong Hire"),  # 3.7
        (_scores(1, 3, [3, 3, 3, 3, 3, 3, 2]), "Lean No"),  # 2.5
    ],
)
async def test_a_one_in_testing_or_correctness_caps_the_signal_at_no(
    reports: ReportHarness, scores: dict[str, int], uncapped: str
) -> None:
    log = reports.ended_session()
    reports.model.script(submit_report(scores))

    signal = (await reports.generate(log.id))["report"]["overall_signal"]

    assert signal["label"] == "No"
    assert signal["capped"] is True


async def test_the_cap_never_raises_a_lower_signal(reports: ReportHarness) -> None:
    log = reports.ended_session()
    reports.model.script(submit_report(_scores(1, 2, [2, 2, 1, 1, 2, 2, 1])))  # 1.6

    signal = (await reports.generate(log.id))["report"]["overall_signal"]

    assert signal["label"] == "Strong No"
    assert signal["capped"] is False


async def test_the_model_cannot_choose_the_signal(reports: ReportHarness) -> None:
    log = reports.ended_session()
    reports.model.script(submit_report(overall_signal="Strong Hire"))  # not in the schema
    reports.model.script(submit_report(_scores(2, 2, [2, 2, 2, 2, 2, 2, 2])))

    view = await reports.generate(log.id)

    assert view["report"]["overall_signal"]["label"] == "No"
    assert view["usage"]["attempts"] == 2


async def test_every_evidence_timestamp_exists_in_the_event_log(reports: ReportHarness) -> None:
    log = reports.ended_session()  # events at t_ms 0, 30000, 35000, 300000, 320000, 600000
    reports.model.script(submit_report(evidence_t_ms=31_000))  # no event at 31 s
    reports.model.script(submit_report(evidence_t_ms=320_000))

    view = await reports.generate(log.id)

    assert view["status"] == "report_ready"
    log_t_ms = {e.t_ms for e in reports.store.events(log.id)}
    for row in view["report"]["rubric"]:
        assert all(e["t_ms"] in log_t_ms for e in row["evidence"])
    first, retry = reports.model.requests
    assert "31000" in retry.messages[0]["content"]  # the retry is told what was wrong
    assert "31000" not in first.messages[0]["content"]


def _with(dimension: str, **fields: object) -> dict[str, object]:
    """A rubric (as submit_report builds it) with one dimension's fields replaced."""
    rubric: dict[str, object] = submit_report().input["rubric"]
    rubric[dimension] = {**rubric[dimension], **fields}  # type: ignore[dict-item]
    return rubric


def _without(dimension: str) -> dict[str, object]:
    rubric: dict[str, object] = submit_report().input["rubric"]
    del rubric[dimension]
    return rubric


EVIDENCE = {"t_ms": 0, "quote_or_code": "q", "comment": "c"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"rubric": _without("testing")},
        {"rubric": _with("approach", score=5)},
        {"rubric": _with("approach", score=0)},
        {"rubric": _with("approach", score="3")},
        {"rubric": _with("approach", evidence=[])},
        {"rubric": _with("approach", evidence=[EVIDENCE] * 4)},
        {"rubric": _with("approach", evidence=[{"t_ms": 0, "quote_or_code": "q"}])},
        {"summary": "  "},
        {"signal_rationale": ""},
    ],
    ids=[
        "missing-dimension",
        "score-above-4",
        "score-below-1",
        "score-as-string",
        "no-evidence",
        "four-evidence-items",
        "evidence-missing-comment",
        "blank-summary",
        "blank-rationale",
    ],
)
async def test_an_invalid_report_is_retried_once_then_the_session_is_report_failed(
    reports: ReportHarness, overrides: dict[str, Any]
) -> None:
    log = reports.ended_session()
    reports.model.script(submit_report(**overrides))
    reports.model.script(submit_report(**overrides))

    view = await reports.generate(log.id)

    assert view == {"status": "report_failed"}
    assert reports.status(log.id) == "report_failed"
    assert reports.report(log.id) is None
    assert len(reports.model.requests) == 2


async def test_a_report_without_the_tool_call_is_retried(reports: ReportHarness) -> None:
    log = reports.ended_session()
    reports.model.script("Here is my evaluation in prose.")
    reports.model.script(submit_report())

    view = await reports.generate(log.id)

    assert view["status"] == "report_ready"
    assert view["usage"]["attempts"] == 2
    assert view["usage"]["input_tokens"] == 2 * 1000  # both attempts are paid for


async def test_api_failures_on_both_attempts_make_the_session_report_failed(
    reports: ReportHarness,
) -> None:
    log = reports.ended_session()
    reports.model.script(ModelError("rate_limited", "The Anthropic API is rate limiting requests."))
    reports.model.script(ModelError("model_unavailable", "The Anthropic API is unavailable (529)."))

    view = await reports.generate(log.id)

    assert view == {"status": "report_failed"}


async def test_retry_after_report_failed_rebuilds_the_report_from_stored_events(
    reports: ReportHarness,
) -> None:
    log = reports.ended_session()
    reports.model.script(ModelError("rate_limited", "rate limited"))
    reports.model.script(ModelError("rate_limited", "rate limited"))
    assert (await reports.generate(log.id))["status"] == "report_failed"

    reports.model.script(submit_report(evidence_t_ms=300_000))
    view = await reports.generate(log.id)  # Retry is a regeneration

    assert view["status"] == "report_ready"
    assert reports.status(log.id) == "report_ready"
    retry = reports.model.requests[-1].messages[0]["content"]
    assert "Can the input be empty?" in retry  # built from the stored event log
    assert "return [0, 1]" in retry


async def test_regenerating_replaces_the_previous_report(reports: ReportHarness) -> None:
    log = reports.ended_session()
    reports.model.script(submit_report(summary="First take."))
    await reports.generate(log.id)

    reports.model.script(submit_report(summary="Second take."))
    view = await reports.generate(log.id)

    assert view["report"]["summary"] == "Second take."


async def test_a_failed_regeneration_keeps_the_previous_report(reports: ReportHarness) -> None:
    log = reports.ended_session()
    reports.model.script(submit_report(summary="First take."))
    await reports.generate(log.id)

    reports.model.script(ModelError("rate_limited", "rate limited"))
    reports.model.script(ModelError("rate_limited", "rate limited"))
    view = await reports.generate(log.id)

    assert view["status"] == "report_ready"
    assert view["report"]["summary"] == "First take."


async def test_a_live_session_has_no_report_to_generate(reports: ReportHarness) -> None:
    log = reports.session()

    assert reports.reports.start(log.id) is False
    assert reports.reports.view(log.id) == {"status": "live"}
    assert reports.model.requests == []


async def test_correctness_reads_the_last_code_before_wrap_up(reports: ReportHarness) -> None:
    log = reports.session()
    log.code(300, "def solve():\n    return 'judged'\n")
    log.event(1500, "phase_changed", to="wrap_up", by="agent", **{"from": "test"})
    log.code(1600, "def follow_up():\n    return 'exploratory'\n")
    log.end(1700)
    reports.model.script(submit_report())

    report = (await reports.generate(log.id))["report"]

    assert report["correctness"]["t_ms"] == 300_000
    content = reports.model.requests[0].messages[0]["content"]
    judged = content.split("<code_for_correctness>")[1]
    assert "judged" in judged and "exploratory" not in judged


async def test_ending_a_live_session_starts_report_generation(
    harness: LiveSessionHarness,
) -> None:
    session_id = await harness.start()
    harness.model.script("Hi, welcome.")
    await harness.connect(session_id)
    harness.advance(30)
    harness.model.script("No, it has at least two numbers.")
    await harness.say(session_id, "Can the list be empty?")
    assert harness.reports.view(session_id) == {"status": "live"}

    harness.model.script("Thanks for your time.")  # the closing reply
    harness.model.script(submit_report(evidence_t_ms=30_000))  # then the Report
    await harness.send(session_id, "end_session")
    assert harness.reports.view(session_id) == {"status": "generating"}

    view = await harness.finish_report(session_id)

    assert view is not None and view["status"] == "report_ready"
    assert harness.session(session_id).status == "report_ready"
    request = harness.model.requests[-1]
    assert request.model == "claude-opus-5-5"
    assert "Can the list be empty?" in request.messages[0]["content"]
