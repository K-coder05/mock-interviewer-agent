"""Phases: the Interviewer and the Candidate move the label; the Candidate's choice is locked."""

from backend.phases import time_per_phase
from tests.harness import LiveSessionHarness, ToolCall
from tests.report_harness import ReportHarness, submit_report


async def _connected(harness: LiveSessionHarness) -> str:
    session_id = await harness.start()
    harness.model.script("Hi, welcome.")
    await harness.connect(session_id)
    return session_id


def _changes(harness: LiveSessionHarness, session_id: str) -> list[tuple[str, str, str]]:
    return [
        (e.payload["from"], e.payload["to"], e.payload["by"])
        for e in harness.events(session_id, "phase_changed")
    ]


async def test_the_interviewer_moves_the_phase_and_the_event_records_from_to_and_by(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)

    harness.model.script("Okay, go ahead.", ToolCall("set_phase", {"phase": "approach"}))
    await harness.say(session_id, "I think a hash map works.")

    assert _changes(harness, session_id) == [("clarify", "approach", "agent")]
    assert harness.messages(session_id, "phase") == [
        {"type": "phase", "phase": "approach", "by": "agent"}
    ]


async def test_an_invalid_or_unchanged_agent_phase_is_ignored(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)

    harness.model.script("Sure.", ToolCall("set_phase", {"phase": "clarify"}))
    await harness.say(session_id, "One question.")
    harness.model.script("Sure.", ToolCall("set_phase", {"phase": "lunch"}))
    await harness.say(session_id, "Another.")

    assert harness.events(session_id, "phase_changed") == []


async def test_the_user_can_set_any_phase_and_move_backward(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)

    await harness.send(session_id, "set_phase", phase="test")
    await harness.send(session_id, "set_phase", phase="approach")

    assert _changes(harness, session_id) == [
        ("clarify", "test", "user"),
        ("test", "approach", "user"),
    ]


async def test_an_invalid_user_phase_is_an_error(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)

    await harness.send(session_id, "set_phase", phase="nope")

    assert harness.events(session_id, "phase_changed") == []
    assert harness.messages(session_id, "error")[-1]["code"] == "invalid_message"


async def test_the_agent_cannot_change_the_phase_for_two_minutes_after_the_user(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")

    harness.advance(119)
    harness.model.script("Okay.", ToolCall("set_phase", {"phase": "test"}))
    await harness.say(session_id, "Starting.")
    assert "set_phase is ignored" in str(harness.model.requests[-1].messages)
    assert _changes(harness, session_id) == [("clarify", "implement", "user")]

    harness.advance(2)
    harness.model.script("Okay.", ToolCall("set_phase", {"phase": "test"}))
    await harness.say(session_id, "Done coding.")
    assert "set_phase is ignored" not in str(harness.model.requests[-1].messages)
    assert _changes(harness, session_id)[-1] == ("implement", "test", "agent")


async def test_the_user_can_override_the_agent_inside_the_lock(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")

    await harness.send(session_id, "set_phase", phase="approach")

    assert _changes(harness, session_id)[-1] == ("implement", "approach", "user")


async def test_an_overrun_phase_is_flagged_to_the_interviewer(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)

    harness.advance(7 * 60)
    harness.model.script("Okay.")
    await harness.say(session_id, "Still thinking about inputs.")
    assert "overrun" not in str(harness.model.requests[-1].messages)

    harness.advance(2 * 60)
    harness.model.script("Let's move on. What is your plan?")
    await harness.say(session_id, "One more question.")
    assert "has overrun" in str(harness.model.requests[-1].messages)


async def test_time_per_phase_sums_every_interval(reports: ReportHarness) -> None:
    log = reports.session()
    log.event(60, "phase_changed", to="approach", by="agent", **{"from": "clarify"})
    log.event(120, "phase_changed", to="implement", by="agent", **{"from": "approach"})
    log.event(300, "phase_changed", to="approach", by="user", **{"from": "implement"})
    log.event(360, "phase_changed", to="implement", by="user", **{"from": "approach"})
    log.end(600)

    assert time_per_phase(reports.store.events(log.id), 600_000) == {
        "clarify": 60_000,
        "approach": 120_000,
        "implement": 420_000,
        "test": 0,
        "wrap_up": 0,
    }
    reports.model.script(submit_report())
    view = await reports.generate(log.id)
    assert view["metrics"]["phase_ms"]["approach"] == 120_000


async def test_correctness_uses_the_final_code_when_wrap_up_never_began(
    reports: ReportHarness,
) -> None:
    log = reports.session()
    log.code(300, "def solve():\n    return 'first'\n")
    log.event(400, "phase_changed", to="test", by="agent", **{"from": "implement"})
    log.code(500, "def solve():\n    return 'final'\n")
    log.end(600)
    reports.model.script(submit_report())

    report = (await reports.generate(log.id))["report"]

    assert report["correctness"]["t_ms"] == 500_000


async def test_correctness_uses_the_last_snapshot_before_wrap_up_began_again(
    reports: ReportHarness,
) -> None:
    log = reports.session()
    log.code(300, "def solve():\n    return 'a'\n")
    log.code(400, "def solve():\n    return 'b'\n")
    log.event(450, "phase_changed", to="wrap_up", by="user", **{"from": "test"})
    log.code(500, "def solve():\n    return 'c'\n")
    log.event(550, "phase_changed", to="implement", by="user", **{"from": "wrap_up"})
    log.code(560, "def solve():\n    return 'd'\n")
    log.event(570, "phase_changed", to="wrap_up", by="user", **{"from": "implement"})
    log.code(580, "def solve():\n    return 'e'\n")
    log.end(600)
    reports.model.script(submit_report())

    report = (await reports.generate(log.id))["report"]

    assert report["correctness"]["t_ms"] == 560_000
