"""Report completeness (ticket 07): deterministic metrics, strengths/improvements, Ideal
Walkthrough, pastes and the autocomplete label."""

from typing import Any

from tests.harness import LiveSessionHarness
from tests.report_harness import ReportHarness, submit_report

SLOW = "def f(xs):\n    return xs[5]\n"


async def metrics_of(
    reports: ReportHarness, log: Any, executed: dict[str, str] | None = None
) -> dict[str, Any]:
    reports.model.script(submit_report(executed=executed))
    view = await reports.generate(log.id)
    metrics: dict[str, Any] = view["metrics"]
    return metrics


async def test_time_to_first_code_run_and_test(reports: ReportHarness) -> None:
    log = reports.session(starter_code="def f(xs):\n    pass\n")
    log.code(120, "def f(xs):\n    return xs\n")
    log.code(200, "def f(xs):\n    return xs\n\nassert f([1]) == [1]\n")
    log.run(260, stdout="")
    log.end(600)

    m = await metrics_of(reports, log, {"x1": "Typical case"})

    assert m["time_to_first_code_ms"] == 120_000
    assert m["time_to_first_run_ms"] == 260_000
    assert m["time_to_first_test_ms"] == 260_000


async def test_no_code_run_or_test_gives_none(reports: ReportHarness) -> None:
    log = reports.session()
    log.say(10, "Thinking.")
    log.end(100)

    m = await metrics_of(reports, log)

    assert m["time_to_first_code_ms"] is None
    assert m["time_to_first_run_ms"] is None
    assert m["time_to_first_test_ms"] is None


async def test_runs_failures_and_error_types(reports: ReportHarness) -> None:
    log = reports.session()
    log.code(10, SLOW)
    trace = "Traceback (most recent call last):\n  File \"main.py\", line 4\nIndexError: list index out of range\n"
    log.run(20, stderr=trace, exit_code=1)
    log.run(30, stderr=trace, exit_code=1)
    log.run(40, stderr="ValueError: bad\n", exit_code=1)
    log.run(50, stdout="ok\n")
    log.event(60, "run", snapshot_seq=1, stdin="", stdout="", stderr="", exit_code=-9,
              duration_ms=1, timed_out=True, truncated=False)
    log.end(100)

    m = await metrics_of(reports, log)

    assert (m["runs"], m["failed_runs"]) == (5, 4)
    assert m["error_types"] == {"IndexError": 2, "ValueError": 1, "TimeoutError": 1}


async def test_silence_gaps_over_sixty_seconds(reports: ReportHarness) -> None:
    log = reports.session()
    log.say(10, "Let me think.")
    log.say(50, "OK.")  # 40 s: not a gap
    log.code(200, "x = 1\n")  # 150 s gap
    log.say(230, "Writing.")
    log.end(300)  # 70 s gap to the end

    m = await metrics_of(reports, log)

    assert m["silence_gaps"] == [
        {"start_ms": 50_000, "end_ms": 200_000, "duration_ms": 150_000},
        {"start_ms": 230_000, "end_ms": 300_000, "duration_ms": 70_000},
    ]


async def test_talk_ratio_and_words_per_minute_while_coding(reports: ReportHarness) -> None:
    log = reports.session()
    log.say(10, "one two three four", speaker="user")  # before coding
    log.say(20, "a b c d e f g h", speaker="interviewer")
    log.code(60, "x = 1\n")
    log.say(90, " ".join(["w"] * 30))  # while coding
    log.end(180)  # coding for 2 minutes

    m = await metrics_of(reports, log)

    assert m["candidate_words"] == 34
    assert m["interviewer_words"] == 8
    assert m["candidate_talk_ratio"] == 0.81
    assert m["coding_words"] == 30
    assert m["coding_words_per_minute"] == 15.0


async def test_hints_by_level_and_muted_time_light_up_from_later_events(
    reports: ReportHarness,
) -> None:
    log = reports.session()
    log.event(100, "hint_given", level=1, text="What about a map?")
    log.event(200, "hint_given", level=1, text="Think again.")
    log.event(300, "hint_given", level=3, text="Use a hash map.")
    log.event(400, "mic_muted")
    log.event(430, "mic_unmuted")
    log.event(500, "mic_muted")  # still muted at the end
    log.end(560)

    m = await metrics_of(reports, log)

    assert m["hints_by_level"] == {"1": 2, "2": 0, "3": 1, "4": 0}
    assert m["muted_ms"] == 30_000 + 60_000


async def test_report_has_strengths_improvements_with_drills_and_ideal_walkthrough(
    reports: ReportHarness,
) -> None:
    log = reports.ended_session()
    reports.model.script(submit_report())

    view = await reports.generate(log.id)

    report = view["report"]
    assert [s["title"] for s in report["strengths"]] == ["Strength 1", "Strength 2", "Strength 3"]
    assert [i["drill"] for i in report["improvements"]] == ["Drill 1.", "Drill 2.", "Drill 3."]
    assert report["ideal_walkthrough"]["approach"].startswith("Ask about duplicates")
    assert report["ideal_walkthrough"]["complexity"] == "O(n) time, O(n) space."
    assert "def two_sum" in report["ideal_walkthrough"]["code"]


async def test_two_strengths_are_rejected_and_retried(reports: ReportHarness) -> None:
    log = reports.ended_session()
    good = submit_report()
    bad = submit_report(strengths=good.input["strengths"][:2])
    reports.model.script(bad)
    reports.model.script(good)

    view = await reports.generate(log.id)

    assert view["status"] == "report_ready"
    assert len(reports.model.requests) == 2
    assert "strengths" in str(reports.model.requests[1].messages[0]["content"])


async def test_improvement_without_a_drill_is_rejected(reports: ReportHarness) -> None:
    log = reports.ended_session()
    bad = [{"title": "t", "detail": "d", "drill": ""}] * 3
    reports.model.script(submit_report(improvements=bad))
    reports.model.script(submit_report(improvements=bad))

    view = await reports.generate(log.id)

    assert view["status"] == "report_failed"


async def test_report_labels_autocomplete(reports: ReportHarness) -> None:
    on = reports.session(autocomplete=True)
    on.end(60)
    off = reports.session()
    off.end(60)
    reports.model.script(submit_report())
    reports.model.script(submit_report())

    assert (await reports.generate(on.id))["report"]["autocomplete"] is True
    assert (await reports.generate(off.id))["report"]["autocomplete"] is False


async def test_pastes_appear_in_metrics_and_are_not_a_rubric_input(reports: ReportHarness) -> None:
    log = reports.session()
    log.event(40, "paste", length=350, text="x" * 350)
    log.end(100)

    m = await metrics_of(reports, log)

    assert m["large_pastes"] == [{"t_ms": 40_000, "length": 350}]
    message = str(reports.model.requests[0].messages[0]["content"])
    assert "never lower a score" in str(reports.model.requests[0].system)
    assert '"length": 350' in message


async def test_live_session_logs_only_pastes_over_200_characters(
    harness: LiveSessionHarness,
) -> None:
    sid = await harness.start(autocomplete=True)
    await harness.send(sid, "ui_event", event="paste", text="x" * 200)
    await harness.send(sid, "ui_event", event="paste", text="y" * 201)
    await harness.send(sid, "ui_event", event="mic_muted")

    [paste] = harness.events(sid, "paste")
    assert paste.payload == {"length": 201, "text": "y" * 201}
    assert harness.session(sid).settings["autocomplete"] is True
