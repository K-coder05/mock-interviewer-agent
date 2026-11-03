"""Live Session seam: voice output — barge-in logging and cancelling a proactive call when the
Candidate starts speaking (a reply to them is never cancelled)."""

import asyncio
from typing import Any

import pytest

from tests.harness import LiveSessionHarness
from tests.report_harness import ReportHarness, submit_report

WAIT_S = 5


async def _connected(harness: LiveSessionHarness) -> str:
    session_id = await harness.start()
    harness.model.script("Hi, welcome.")
    await harness.connect(session_id)
    return session_id


def _triggers(harness: LiveSessionHarness, session_id: str) -> list[dict[str, Any]]:
    events = harness.events(session_id, "trigger")
    return [e.payload for e in events if e.payload["reason"] != "session_start"]


async def _replied(harness: LiveSessionHarness, session_id: str) -> None:
    """Wait for the Interviewer, failing (not hanging) if a gated call is never released."""
    await asyncio.wait_for(harness.wait_for_interviewer(session_id), WAIT_S)


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_a_nudge_in_flight_is_cancelled_when_the_candidate_starts_speaking(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")
    gate = asyncio.Event()
    harness.model.script("You've been quiet for a while,", gate, " how is it going?")
    await harness.elapse(session_id, 90, wait=False)  # the silence Nudge starts streaming
    await _settle()
    [delta] = harness.messages(session_id, "interviewer_delta")[-1:]

    await harness.speaking(session_id)
    await _replied(harness, session_id)

    assert harness.messages(session_id, "interviewer_cancel") == [
        {"type": "interviewer_cancel", "msg_id": delta["msg_id"]}
    ]
    assert harness.messages(session_id, "interviewer_done")[-1]["full_text"] == "Hi, welcome."
    assert len(harness.events(session_id, "utterance")) == 1  # only the greeting was said
    assert _triggers(harness, session_id) == [
        {
            "reason": "silence",
            "detail": "implement",
            "proactive": True,
            "outcome": "suppressed",
            "suppressed_by": "speaking",
            "cancelled": True,
        }
    ]
    assert not gate.is_set()


async def test_a_cancelled_stuck_reaction_is_retried_once_the_candidate_is_quiet(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")
    harness.advance(50)
    for _ in range(3):
        await harness.send(session_id, "run", code="raise ValueError('x')\n")
        await harness.finish_run(session_id)
    gate = asyncio.Event()
    harness.model.script("Hmm,", gate, " what is that error telling you?")
    await harness.elapse(session_id, 3, wait=False)
    await _settle()
    await harness.speaking(session_id)
    await _replied(harness, session_id)
    assert _triggers(harness, session_id)[-1]["outcome"] == "suppressed"

    harness.model.script("What is that error telling you?")
    await harness.elapse(session_id, 2, wait=False)
    await _replied(harness, session_id)
    last = _triggers(harness, session_id)[-1]
    assert (last["reason"], last["outcome"]) == ("stuck", "spoke")


async def test_a_reply_to_the_candidate_is_not_cancelled_when_they_start_speaking(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    gate = asyncio.Event()
    harness.model.script("Yes,", gate, " the list is sorted.")
    await harness.send(session_id, "utterance", text="is the list sorted?", channel="text")
    await _settle()

    await harness.speaking(session_id)
    gate.set()
    await _replied(harness, session_id)

    assert harness.messages(session_id, "interviewer_cancel") == []
    assert harness.messages(session_id, "interviewer_done")[-1]["full_text"] == (
        "Yes, the list is sorted."
    )
    assert _triggers(harness, session_id)[-1]["outcome"] == "spoke"


async def test_speech_ending_does_not_cancel_a_nudge(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")
    gate = asyncio.Event()
    harness.model.script("How is it going,", gate, " any blockers?")
    await harness.elapse(session_id, 90, wait=False)
    await _settle()

    await harness.speaking(session_id, False)
    gate.set()
    await _replied(harness, session_id)

    assert harness.messages(session_id, "interviewer_cancel") == []
    assert _triggers(harness, session_id)[-1]["outcome"] == "spoke"


async def test_barge_in_is_logged_and_the_interviewer_knows_it_was_cut_off(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    [done] = harness.messages(session_id, "interviewer_done")

    await harness.send(session_id, "ui_event", event="interrupted", msg_id=done["msg_id"])
    await harness.send(session_id, "ui_event", event="interrupted", msg_id=42)  # bad id: dropped

    [event] = harness.events(session_id, "interviewer_interrupted")
    assert event.payload == {"msg_id": done["msg_id"]}
    harness.model.script("Go ahead.")
    await harness.say(session_id, "sorry, one question")
    turn = str(harness.model.requests[-1].messages)
    assert "The candidate interrupted you while you were speaking" in turn


async def test_barge_in_shows_in_the_report_timeline(reports: ReportHarness) -> None:
    log = reports.session()
    log.say(10, "Let me explain the approach.", speaker="interviewer")
    log.event(12, "interviewer_interrupted", msg_id="msg_1")
    log.end(300)
    reports.model.script(submit_report())

    await reports.generate(log.id)

    message = str(reports.model.requests[0].messages[0]["content"])
    assert "Candidate interrupted the Interviewer while it was speaking" in message


async def test_tts_settings_come_from_config_and_are_kept_per_session(
    harness: LiveSessionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.config import load_config

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    voice = load_config().voice
    assert (voice.tts, voice.tts_voice, voice.tts_rate, voice.pause_stt_during_tts) == (
        "browser",
        None,
        1.0,
        False,
    )

    session_id = await harness.start()
    assert harness.session(session_id).settings["voice"] == {
        "utterance_silence_ms": 1200,
        "tts": "browser",
        "tts_voice": None,
        "tts_rate": 1.0,
        "pause_stt_during_tts": False,
    }
