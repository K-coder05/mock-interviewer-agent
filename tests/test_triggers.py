"""Live Session seam: the proactive Interviewer — Triggers, guardrails, Nudges and coalescing."""

import asyncio
from typing import Any

import pytest

from tests.harness import LiveSessionHarness, ToolCall
from tests.report_harness import ReportHarness, submit_report

SILENT = ToolCall("stay_silent", {"reason": "they are reading"})


async def _connected(harness: LiveSessionHarness, *, duration_min: int | None = None) -> str:
    session_id = await harness.start(duration_min=duration_min)
    harness.model.script("Hi, welcome.")
    await harness.connect(session_id)
    return session_id


def _triggers(harness: LiveSessionHarness, session_id: str) -> list[dict[str, Any]]:
    """Logged Triggers after the greeting (itself the `session_start` Trigger)."""
    events = harness.events(session_id, "trigger")
    return [e.payload for e in events if e.payload["reason"] != "session_start"]


def _nudges(harness: LiveSessionHarness, session_id: str) -> list[dict[str, Any]]:
    return [
        t for t in _triggers(harness, session_id) if t["outcome"] == "spoke" and t["proactive"]
    ]


async def test_ninety_seconds_of_silence_while_implementing_produces_exactly_one_nudge(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")

    await harness.elapse(session_id, 89)
    assert _nudges(harness, session_id) == []

    harness.model.script("What are you thinking right now?")
    await harness.elapse(session_id, 1)
    assert "<trigger>silence" in str(harness.model.requests[-1].messages)
    [nudge] = _nudges(harness, session_id)
    assert nudge["reason"] == "silence"
    assert harness.messages(session_id, "interviewer_done")[-1]["full_text"] == (
        "What are you thinking right now?"
    )

    for _ in range(10):  # the same silence never produces a second Nudge
        await harness.elapse(session_id, 60)
    assert len(_nudges(harness, session_id)) == 1


@pytest.mark.parametrize(
    ("phase", "threshold_s"), [("approach", 45), ("implement", 90), ("test", 60)]
)
async def test_the_silence_threshold_depends_on_the_phase(
    harness: LiveSessionHarness, phase: str, threshold_s: int
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase=phase)

    await harness.elapse(session_id, threshold_s - 1)
    assert _triggers(harness, session_id) == []

    harness.model.script(SILENT)
    await harness.elapse(session_id, 1)
    assert [t["reason"] for t in _triggers(harness, session_id)] == ["silence"]


async def test_silence_in_clarify_counts_from_the_greeting_and_wrap_up_has_no_nudge(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.elapse(session_id, 44)
    assert _triggers(harness, session_id) == []
    harness.model.script(SILENT)
    await harness.elapse(session_id, 1)
    assert len(_triggers(harness, session_id)) == 1

    await harness.send(session_id, "set_phase", phase="wrap_up")
    await harness.elapse(session_id, 5 * 60)
    assert len(_triggers(harness, session_id)) == 1


async def test_candidate_activity_restarts_the_silence(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")

    await harness.elapse(session_id, 80)
    await harness.send(session_id, "code_update", code="def solve():\n")
    await harness.elapse(session_id, 80)
    assert _triggers(harness, session_id) == []

    harness.model.script("How is it going?")
    await harness.elapse(session_id, 10)
    assert len(_nudges(harness, session_id)) == 1

    # new activity opens a new silence, which may be nudged once more
    await harness.send(session_id, "code_update", code="def solve():\n    pass\n")
    harness.model.script("What are you thinking now?")
    await harness.elapse(session_id, 90)
    assert len(_nudges(harness, session_id)) == 2


async def test_stay_silent_speaks_nothing_and_logs_its_reason(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)
    n_done = len(harness.messages(session_id, "interviewer_done"))

    harness.model.script(ToolCall("stay_silent", {"reason": "they are typing steadily"}))
    await harness.elapse(session_id, 45)

    [trigger] = _triggers(harness, session_id)
    assert trigger == {
        "reason": "silence",
        "detail": "clarify",
        "proactive": True,
        "outcome": "silent",
        "silent_reason": "they are typing steadily",
    }
    assert len(harness.messages(session_id, "interviewer_done")) == n_done
    assert harness.messages(session_id, "interviewer_delta")[-1]["text"] == "Hi, welcome."
    assert [e.payload["text"] for e in harness.events(session_id, "utterance")] == ["Hi, welcome."]


async def test_time_checkpoints_at_half_time_without_code_and_ten_and_five_minutes_left(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness, duration_min=30)
    await harness.send(session_id, "set_phase", phase="implement")  # no overrun before 25 min
    harness.model.script(SILENT)  # the first silence
    await harness.elapse(session_id, 90)

    await harness.elapse(session_id, 15 * 60 - 90 - 1)
    assert [t["reason"] for t in _triggers(harness, session_id)] == ["silence"]

    harness.model.script("We're halfway through. How do you want to use the remaining time?")
    await harness.elapse(session_id, 1)
    assert "half the time has passed" in str(harness.model.requests[-1].messages)

    harness.model.script("About ten minutes left.")
    await harness.elapse(session_id, 5 * 60)
    harness.model.script("Five minutes left, let's start wrapping up.")
    await harness.elapse(session_id, 5 * 60)

    checkpoints = [
        (t["detail"], t["outcome"]) for t in _triggers(harness, session_id) if t["reason"] == "time"
    ]
    assert checkpoints == [
        ("half_time_no_code", "spoke"),
        ("10_min_left", "spoke"),
        ("5_min_left", "spoke"),
    ]


async def test_no_half_time_checkpoint_once_code_is_written(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness, duration_min=30)
    await harness.send(session_id, "set_phase", phase="implement")
    await harness.send(session_id, "code_update", code="def solve(nums):\n")
    harness.advance(15 * 60)
    harness.model.script(SILENT)  # the silence since the last edit

    await harness.elapse(session_id, 0)

    assert [t["reason"] for t in _triggers(harness, session_id)] == ["silence"]


async def test_a_nudge_inside_the_cooldown_is_suppressed_logged_and_a_checkpoint_retried(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness, duration_min=30)
    await harness.send(session_id, "set_phase", phase="implement")
    harness.advance(19 * 60 + 30)
    await harness.send(session_id, "code_update", code="x = 1\n")
    harness.model.script("Sure, go ahead.")
    await harness.say(session_id, "Can I use a dict?")
    n_requests = len(harness.model.requests)

    await harness.elapse(session_id, 30)  # 10 minutes left, 30 s after the Interviewer spoke

    assert _triggers(harness, session_id)[-1] == {
        "reason": "time",
        "detail": "10_min_left",
        "proactive": True,
        "outcome": "suppressed",
        "suppressed_by": "cooldown",
    }
    assert len(harness.model.requests) == n_requests

    # a held-back checkpoint is retried once the cooldown is over (a silence would not be)
    await harness.elapse(session_id, 14)
    assert len(harness.model.requests) == n_requests
    harness.model.script("About ten minutes left. How do you want to use them?")
    await harness.elapse(session_id, 1)
    assert _triggers(harness, session_id)[-1] == {
        "reason": "time",
        "detail": "10_min_left",
        "proactive": True,
        "outcome": "spoke",
    }


async def test_at_most_three_nudges_per_five_minutes(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)
    for i in range(3):  # a fresh silence every 45 s, each nudged
        harness.model.script(f"Nudge {i}")
        await harness.elapse(session_id, 45)
        await harness.send(session_id, "code_update", code=f"step = {i}\n")
    assert len(_nudges(harness, session_id)) == 3
    n_requests = len(harness.model.requests)

    await harness.elapse(session_id, 45)  # the fourth within 5 minutes

    assert _triggers(harness, session_id)[-1]["outcome"] == "suppressed"
    assert _triggers(harness, session_id)[-1]["suppressed_by"] == "cap"
    assert len(harness.model.requests) == n_requests

    # the suppressed silence is not retried; once the first Nudge (at 0:45) has left the
    # 5-minute window, a new silence may be nudged again
    await harness.elapse(session_id, 60)
    assert len(_triggers(harness, session_id)) == 4
    harness.advance(60)  # 5:00
    await harness.send(session_id, "code_update", code="step = 4\n")
    harness.model.script("Still with me?")
    await harness.elapse(session_id, 45)
    assert len(_nudges(harness, session_id)) == 4


async def test_typed_messages_are_answered_inside_the_cooldown_and_over_the_cap(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    for i in range(3):
        harness.model.script(f"Nudge {i}")
        await harness.elapse(session_id, 45)
        await harness.send(session_id, "code_update", code=f"step = {i}\n")

    harness.model.script("Yes, you may assume that.")
    await harness.say(session_id, "Can I assume the input is sorted?")

    assert harness.messages(session_id, "interviewer_done")[-1]["full_text"].startswith("Yes")
    assert _triggers(harness, session_id)[-1] == {
        "reason": "typed_message",
        "proactive": False,
        "outcome": "spoke",
    }
    assert len(_nudges(harness, session_id)) == 3  # a reply is not a Nudge


async def test_one_call_in_flight_and_everything_meanwhile_coalesces_into_the_next(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness, duration_min=10)
    gate = asyncio.Event()
    harness.model.script("Let me think", gate, " about that.")
    harness.model.script("Time's up. Any last thoughts?")
    n_requests = len(harness.model.requests)

    await harness.send(session_id, "utterance", text="first question", channel="text")
    await asyncio.sleep(0)
    await harness.send(session_id, "utterance", text="second question", channel="text")
    await harness.send(session_id, "utterance", text="third question", channel="text")
    await harness.elapse(session_id, 10 * 60, wait=False)  # time is up mid-reply
    for _ in range(5):
        await asyncio.sleep(0)
    assert len(harness.model.requests) == n_requests + 1  # still only the first call

    gate.set()
    await harness.wait_for_interviewer(session_id)

    assert len(harness.model.requests) == n_requests + 2
    second = str(harness.model.requests[-1].messages)
    assert "second question" in second and "third question" in second
    assert "<trigger>time_up" in second  # a queued time-up is never replaced by a later Trigger
    assert "Also since your last turn: typed_message" in second
    assert _triggers(harness, session_id)[-1] == {
        "reason": "time_up",
        "proactive": False,
        "coalesced": [{"reason": "typed_message"}],
        "outcome": "spoke",
    }


async def test_a_nudge_queued_behind_a_reply_is_checked_against_the_cooldown(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    harness.advance(40)
    gate = asyncio.Event()
    harness.model.script("Good question,", gate, " yes.")

    await harness.send(session_id, "utterance", text="Can values repeat?", channel="text")
    await asyncio.sleep(0)
    harness.advance(5)  # the Candidate's last activity is 5 s ago, but the greeting was 45 s ago
    await harness.send(session_id, "set_phase", phase="clarify")  # no-op, not activity
    gate.set()
    await harness.wait_for_interviewer(session_id)

    harness.advance(40)  # 45 s since the typed message, 40 s since the reply
    await harness.elapse(session_id, 0)
    assert [t["reason"] for t in _triggers(harness, session_id)] == ["typed_message"]


async def test_an_overrun_phase_triggers_the_interviewer_once_per_stay(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    harness.advance(8 * 60)
    harness.model.script("Negatives are allowed.")
    await harness.say(session_id, "Hmm, what about negatives?")
    harness.advance(45)  # past the cooldown; the edit below keeps it from being a silence
    await harness.send(session_id, "code_update", code="# plan\n")

    harness.model.script("Let's move on. What's your plan?")
    await harness.elapse(session_id, 1)

    [overrun] = _triggers(harness, session_id)[1:]
    assert overrun == {
        "reason": "phase_overrun",
        "detail": "clarify",
        "proactive": True,
        "outcome": "spoke",
    }
    assert "has overrun" in str(harness.model.requests[-1].messages)
    await harness.send(session_id, "code_update", code="x = 1\n")
    await harness.elapse(session_id, 30)
    assert len(_triggers(harness, session_id)) == 2


async def test_a_failed_decision_call_is_logged_as_silent_with_the_error(
    harness: LiveSessionHarness,
) -> None:
    from backend.agent.model import ModelError

    session_id = await _connected(harness)
    harness.model.script(ModelError("rate_limited", "slow down"))

    await harness.elapse(session_id, 45)

    assert _triggers(harness, session_id)[-1] == {
        "reason": "silence",
        "detail": "clarify",
        "proactive": True,
        "outcome": "silent",
        "error": "rate_limited",
    }
    assert harness.messages(session_id, "error")[-1]["code"] == "rate_limited"


async def test_guardrails_and_thresholds_come_from_config_and_are_kept_per_session(
    harness: LiveSessionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.config import load_config

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    triggers = load_config().triggers
    assert triggers.proactive_cooldown_s == 45
    assert triggers.max_proactive_per_5min == 3
    assert triggers.silence_nudge_s == {"clarify": 45, "approach": 45, "implement": 90, "test": 60}
    assert triggers.muted_silence_multiplier == 2

    session_id = await harness.start()
    assert harness.session(session_id).settings["proactive"] == {
        "proactive_cooldown_s": 45,
        "max_proactive_per_5min": 3,
        "silence_nudge_s": {"clarify": 45, "approach": 45, "implement": 90, "test": 60},
        "run_reaction_delay_s": 3,
        "stuck_failing_runs": 3,
        "coding_pause_lines": 25,
        "coding_pause_idle_s": 30,
        "muted_silence_multiplier": 2,
    }


async def test_trigger_events_stay_out_of_the_report_input(reports: ReportHarness) -> None:
    log = reports.session()
    log.event(
        45,
        "trigger",
        reason="silence",
        detail="clarify",
        proactive=True,
        outcome="silent",
        silent_reason="reading the problem",
    )
    log.end(600)
    reports.model.script(submit_report())

    await reports.generate(log.id)

    assert "reading the problem" not in str(reports.model.requests[-1].messages)
