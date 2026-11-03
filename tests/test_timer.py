"""Live Session seam: the countdown timer, 5-minute warning, time-up grace and ending."""

from tests.harness import LiveSessionHarness


async def _connected(
    harness: LiveSessionHarness, *, duration_min: int | None = None
) -> str:
    session_id = await harness.start(duration_min=duration_min)
    harness.model.script("Hi, welcome.")
    await harness.connect(session_id)
    return session_id


async def test_duration_is_chosen_at_setup_and_stored_in_settings(
    harness: LiveSessionHarness,
) -> None:
    default = await harness.start()
    chosen = await harness.start(duration_min=30)

    assert harness.session(default).settings["duration_min"] == 45
    assert harness.session(chosen).settings["duration_min"] == 30


async def test_timer_starts_at_the_greeting_not_at_session_creation(
    harness: LiveSessionHarness,
) -> None:
    session_id = await harness.start(duration_min=30)
    harness.advance(120)  # time spent on the loading/setup side is not charged
    assert harness.messages(session_id, "timer") == []

    harness.model.script("Hi, welcome.")
    await harness.connect(session_id)

    [timer] = harness.messages(session_id, "timer")
    assert timer["state"] == "running"
    assert timer["remaining_ms"] == 30 * 60_000
    assert timer["duration_ms"] == 30 * 60_000
    [started] = harness.events(session_id, "timer_started")
    assert started.t_ms == 120_000
    # the timer message comes with the greeting, before it is finished
    types = [m["type"] for m in harness.sent[session_id]]
    assert types.index("timer") < types.index("interviewer_done")


async def test_five_minute_warning_is_emitted_once(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness, duration_min=10)

    await harness.elapse(session_id, 4 * 60 + 59)
    assert [m["state"] for m in harness.messages(session_id, "timer")] == ["running"]

    await harness.elapse(session_id, 1)
    await harness.elapse(session_id, 30)

    timers = harness.messages(session_id, "timer")
    assert [m["state"] for m in timers] == ["running", "warning"]
    assert timers[1]["remaining_ms"] == 5 * 60_000
    assert len(harness.events(session_id, "timer_warning")) == 1
    assert harness.session(session_id).status == "live"


async def test_time_up_prompts_for_a_last_thought_then_auto_ends_after_the_grace(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness, duration_min=10)
    await harness.send(session_id, "code_update", code="print('final')\n")

    harness.model.script("Time is up. Any last thoughts?")
    await harness.elapse(session_id, 10 * 60)

    assert [m["state"] for m in harness.messages(session_id, "timer")][-1] == "time_up"
    assert "time_up" in str(harness.model.requests[-1].messages)
    assert harness.messages(session_id, "interviewer_done")[-1]["full_text"].startswith("Time is up")
    assert harness.session(session_id).status == "live"

    await harness.elapse(session_id, 59)
    assert harness.session(session_id).status == "live"
    assert harness.events(session_id, "session_ended") == []

    harness.model.script("Thanks, that's all the time we have. Take care.")
    await harness.elapse(session_id, 1)

    [ended] = harness.events(session_id, "session_ended")
    assert ended.payload == {"reason": "timeout", "final_code": "print('final')\n"}
    assert ended.t_ms == 11 * 60_000
    record = harness.session(session_id)
    assert record.status == "ended"
    assert record.ended_at is not None
    assert harness.messages(session_id, "session_ended")[-1]["reason"] == "timeout"
    closing = harness.messages(session_id, "interviewer_done")[-1]["full_text"]
    assert closing.startswith("Thanks")
    assert "session_end" in str(harness.model.requests[-1].messages)
    assert harness.events(session_id)[-1].type == "session_ended"


async def test_end_interview_ends_early_with_a_polite_close_and_no_further_timer(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness, duration_min=45)
    await harness.send(session_id, "code_update", code="x = 1\n")
    harness.model.script("Thanks for your time today.")

    await harness.send(session_id, "end_session")

    [ended] = harness.events(session_id, "session_ended")
    assert ended.payload == {"reason": "user", "final_code": "x = 1\n"}
    assert harness.session(session_id).status == "ended"
    assert harness.messages(session_id, "interviewer_done")[-1]["full_text"].startswith("Thanks")
    assert harness.messages(session_id, "timer")[-1]["state"] == "ended"

    # the clock running on changes nothing; ending twice is a no-op
    n = len(harness.events(session_id))
    await harness.elapse(session_id, 3600)
    await harness.send(session_id, "end_session")
    assert len(harness.events(session_id)) == n
    assert len(harness.events(session_id, "session_ended")) == 1


async def test_ending_during_the_grace_wins_over_auto_end(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness, duration_min=10)
    harness.model.script("Time is up. Any last thoughts?")
    await harness.elapse(session_id, 10 * 60)

    harness.model.script("Thank you, take care.")
    await harness.send(session_id, "end_session")
    await harness.elapse(session_id, 600)

    [ended] = harness.events(session_id, "session_ended")
    assert ended.payload["reason"] == "user"


async def test_messages_after_the_session_ended_are_rejected(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    harness.model.script("Goodbye.")
    await harness.send(session_id, "end_session")
    n = len(harness.events(session_id))

    await harness.send(session_id, "utterance", text="wait!", channel="text")
    await harness.send(session_id, "code_update", code="late = 1\n")

    assert len(harness.events(session_id)) == n
    assert harness.messages(session_id, "error")[-1]["code"] == "session_ended"


async def test_ending_before_the_interview_started_skips_the_closing(
    harness: LiveSessionHarness,
) -> None:
    session_id = await harness.start()

    await harness.send(session_id, "end_session")

    assert harness.session(session_id).status == "ended"
    assert harness.model.requests[-1].model == "claude-opus-5-5"  # only prep ever ran


async def test_a_failed_greeting_still_starts_the_timer(harness: LiveSessionHarness) -> None:
    from backend.agent.model import ModelError

    session_id = await harness.start()
    harness.model.script(ModelError("rate_limited", "slow down"))
    await harness.connect(session_id)

    assert len(harness.events(session_id, "timer_started")) == 1
