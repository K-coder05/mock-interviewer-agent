"""Live Session seam: reconnecting clients (missed-event replay, timer state), Sessions rebuilt
from their log after a backend restart, and Abandoned Sessions."""

import asyncio

from tests.harness import LiveSessionHarness, ToolCall
from tests.report_harness import submit_report

TIMEOUT_S = 5  # a gated test fails instead of hanging


async def _connected(harness: LiveSessionHarness, *, duration_min: int = 45) -> str:
    session_id = await harness.start(duration_min=duration_min, starter_code="def f():\n    pass\n")
    harness.model.script("Hi, welcome.")
    await harness.connect(session_id)
    return session_id


def _last_seq(harness: LiveSessionHarness, session_id: str) -> int:
    return harness.events(session_id)[-1].seq


async def test_a_reconnecting_client_gets_the_events_it_missed_then_the_timer(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    seen = _last_seq(harness, session_id)  # the tab closes here
    harness.advance(30)
    await harness.send(session_id, "code_update", code="def f():\n    return 1\n")
    harness.model.script(
        "Sounds good.", ToolCall("note", {"observation": "Jumped straight into code."})
    )
    await harness.say(session_id, "I'll use a hash map.")

    messages = await harness.reconnect(session_id, last_seq=seen)

    replay, timer = messages
    assert replay["type"] == "replay"
    types = [e["type"] for e in replay["events"]]
    assert types[:3] == ["code_snapshot", "utterance", "utterance"]
    assert "interviewer_note" not in types  # private: never sent live
    assert all(e["seq"] > seen for e in replay["events"])
    assert replay["last_seq"] == _last_seq(harness, session_id)
    assert [e["payload"].get("text") for e in replay["events"] if e["type"] == "utterance"] == [
        "I'll use a hash map.",
        "Sounds good.",
    ]
    assert timer == {
        "type": "timer",
        "state": "running",
        "remaining_ms": 45 * 60_000 - 30_000,
        "duration_ms": 45 * 60_000,
    }
    assert len(harness.events(session_id, "timer_started")) == 1  # no second greeting


async def test_a_client_that_saw_everything_gets_an_empty_replay(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)

    replay, _timer = await harness.reconnect(session_id, last_seq=_last_seq(harness, session_id))

    assert replay["events"] == []


async def test_a_reconnecting_client_receives_live_messages_after_the_replay(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    received = []

    async def listener(message: dict[str, object]) -> None:
        received.append(message)

    live = harness.manager.live(session_id)
    assert live is not None
    await live.attach(listener, last_seq=_last_seq(harness, session_id))
    harness.model.script("Go ahead.")
    await harness.say(session_id, "Can I start?")

    assert [m["type"] for m in received] == [
        "replay",
        "timer",
        "interviewer_delta",
        "interviewer_done",
    ]


async def test_messages_for_logged_events_carry_their_seq(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)
    harness.model.script("Go ahead.")

    await harness.say(session_id, "Can I start?")
    await harness.send(session_id, "set_phase", phase="approach")
    await harness.send(session_id, "run", code="print(1)\n")
    await harness.finish_run(session_id)

    seq_of = {e.type: e.seq for e in harness.events(session_id)}  # the last of each type
    assert harness.messages(session_id, "interviewer_done")[-1]["seq"] == seq_of["utterance"]
    assert harness.messages(session_id, "phase")[-1]["seq"] == seq_of["phase_changed"]
    assert harness.messages(session_id, "run_result")[-1]["seq"] == seq_of["run"]


async def test_a_client_reconnecting_after_the_end_is_told_the_session_ended(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    seen = _last_seq(harness, session_id)
    harness.model.script("Thanks, that's time.")
    harness.model.script(submit_report())
    await harness.send(session_id, "end_session")

    replay, timer = await harness.reconnect(session_id, last_seq=seen)

    assert replay["events"][-1]["type"] == "session_ended"
    assert timer["state"] == "ended"
    await asyncio.wait_for(harness.finish_report(session_id), TIMEOUT_S)


async def test_a_session_idle_past_the_window_at_startup_becomes_abandoned(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    harness.advance(120)
    await harness.send(session_id, "code_update", code="def f():\n    return 1\n")

    await harness.restart(downtime_s=10 * 60)  # crashed; back 10 min after the last event

    assert harness.session(session_id).status == "abandoned"
    assert harness.manager.live(session_id) is None  # can't be resumed
    assert harness.events(session_id, "session_ended") == []  # it never received an end
    assert not harness.reports.generating(session_id)  # no Report until asked for


async def test_an_abandoned_session_generates_a_report_when_asked(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    harness.advance(60)
    await harness.restart(downtime_s=60 * 60)
    harness.model.script(submit_report())

    assert harness.reports.start(session_id)  # the Generate report button
    view = await asyncio.wait_for(harness.finish_report(session_id), TIMEOUT_S)

    assert view is not None
    assert view["status"] == "report_ready"


async def test_idle_is_measured_from_the_last_event_not_from_creation(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness, duration_min=90)
    harness.advance(40 * 60)
    await harness.send(session_id, "code_update", code="def f():\n    return 1\n")

    await harness.restart(downtime_s=9 * 60)

    assert harness.session(session_id).status == "live"


async def test_only_live_sessions_are_marked_abandoned(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)
    harness.model.script("Thanks, that's time.")
    harness.model.script(submit_report())
    await harness.send(session_id, "end_session")
    await asyncio.wait_for(harness.finish_report(session_id), TIMEOUT_S)

    await harness.restart(downtime_s=60 * 60)

    assert harness.session(session_id).status == "report_ready"


async def test_a_recent_session_resumes_after_a_restart_with_the_timer_on_the_wall_clock(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness, duration_min=30)
    harness.advance(100)
    await harness.send(session_id, "code_update", code="def f():\n    return 1\n")
    seen = _last_seq(harness, session_id)

    await harness.restart(downtime_s=120)
    replay, timer = await harness.reconnect(session_id, last_seq=seen)

    assert harness.session(session_id).status == "live"
    assert replay["events"] == []
    # the downtime counts: 100 s before the crash + 120 s down
    assert timer["state"] == "running"
    assert timer["remaining_ms"] == 30 * 60_000 - 220_000
    assert len(harness.events(session_id, "timer_started")) == 1  # not greeted again
    # the log carries on where it was: same code is deduped, new events are timed after the gap
    await harness.send(session_id, "code_update", code="def f():\n    return 1\n")
    assert _last_seq(harness, session_id) == seen
    harness.advance(5)
    await harness.send(session_id, "code_update", code="def f():\n    return 2\n")
    assert harness.events(session_id)[-1].t_ms == 225_000


async def test_a_resumed_session_whose_time_ran_out_while_down_ends_on_timeout(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness, duration_min=5)
    harness.advance(60)
    await harness.send(session_id, "code_update", code="def f():\n    return 1\n")

    await harness.restart(downtime_s=6 * 60)  # 7 min in: past 5 min + 60 s grace
    harness.model.script("That's all the time we have.")
    harness.model.script(submit_report())
    await asyncio.wait_for(harness.elapse(session_id, 1), TIMEOUT_S)

    [ended] = harness.events(session_id, "session_ended")
    assert ended.payload["reason"] == "timeout"
    assert ended.payload["final_code"] == "def f():\n    return 1\n"
    await asyncio.wait_for(harness.finish_report(session_id), TIMEOUT_S)


async def test_a_resumed_session_does_not_repeat_triggers_that_were_due_while_down(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness, duration_min=45)
    harness.advance(50)
    await harness.send(session_id, "run", code="raise ValueError('x')\n")
    await harness.finish_run(session_id)

    await harness.restart(downtime_s=5 * 60)  # a Run reaction and a silence were due meanwhile
    await harness.elapse(session_id, 1)

    triggers = [e.payload["reason"] for e in harness.events(session_id, "trigger")]
    assert triggers == ["session_start"]  # nothing fired the moment it came back
