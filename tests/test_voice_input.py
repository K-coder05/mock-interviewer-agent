"""Live Session seam: voice input — spoken utterances, the never-interrupt guard and muting."""

import asyncio
from typing import Any

import pytest

from tests.harness import LiveSessionHarness, ToolCall
from tests.report_harness import ReportHarness, submit_report

SILENT = ToolCall("stay_silent", {"reason": "they are narrating while coding"})


async def _connected(harness: LiveSessionHarness) -> str:
    session_id = await harness.start()
    harness.model.script("Hi, welcome.")
    await harness.connect(session_id)
    return session_id


def _triggers(harness: LiveSessionHarness, session_id: str) -> list[dict[str, Any]]:
    events = harness.events(session_id, "trigger")
    return [e.payload for e in events if e.payload["reason"] != "session_start"]


async def test_a_final_spoken_utterance_goes_on_the_record_and_the_interviewer_hears_it(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    harness.advance(10)

    harness.model.script("Sure, the input fits in memory.")
    await harness.speak(session_id, "does the input fit in memory", duration_s=2.5)

    utterance = harness.events(session_id, "utterance")[-2]
    assert utterance.payload == {
        "speaker": "user",
        "channel": "voice",
        "text": "does the input fit in memory",
        "start_ms": utterance.t_ms - 2500,
        "end_ms": utterance.t_ms,
    }
    assert _triggers(harness, session_id) == [
        {"reason": "utterance", "proactive": False, "outcome": "spoke"}
    ]
    turn = str(harness.model.requests[-1].messages)
    assert "Candidate: does the input fit in memory" in turn  # spoken, so not marked (typed)
    assert "<trigger>utterance" in turn


async def test_the_interviewer_may_stay_silent_after_spoken_narration(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    n_done = len(harness.messages(session_id, "interviewer_done"))

    harness.model.script(SILENT)  # no forced reply, unlike a typed message
    await harness.speak(session_id, "so now I loop over the numbers")

    assert len(harness.model.requests) == 3  # prep, greeting, this one
    assert len(harness.messages(session_id, "interviewer_done")) == n_done
    assert _triggers(harness, session_id)[-1]["outcome"] == "silent"


async def test_spoken_replies_are_not_held_back_by_the_cooldown_or_cap(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)  # the greeting just spoke: cooldown is running
    for i in range(5):
        harness.model.script(f"Okay {i}.")
        await harness.speak(session_id, f"thought number {i}")
        harness.advance(5)

    triggers = _triggers(harness, session_id)
    assert [t["outcome"] for t in triggers] == ["spoke"] * 5
    assert not any(t["proactive"] for t in triggers)  # replies, not Nudges


async def test_a_spoken_utterance_during_the_run_delay_is_merged_into_one_reply(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")
    harness.advance(50)
    await harness.send(session_id, "run", code="raise ValueError('x')\n")
    await harness.finish_run(session_id)

    harness.model.script("What did you expect there?")
    await harness.speak(session_id, "hmm that failed")
    await harness.elapse(session_id, 10)

    [trigger] = _triggers(harness, session_id)
    assert trigger["reason"] == "utterance"
    assert trigger["coalesced"] == [{"reason": "run", "detail": "failed"}]


async def test_utterance_and_speaking_messages_are_validated(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "utterance", text="hello", channel="telepathy")
    await harness.send(session_id, "utterance", text="  ", channel="voice")
    await harness.send(session_id, "speaking", active="false")

    assert [m["code"] for m in harness.messages(session_id, "error")] == [
        "invalid_message",
        "invalid_message",
        "invalid_message",
    ]
    assert len(harness.events(session_id, "utterance")) == 1  # only the greeting


# --- never while the Candidate is speaking -----------------------------------------------------


async def test_no_nudge_starts_while_the_candidate_is_speaking(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")

    await harness.elapse(session_id, 89)
    await harness.speaking(session_id)  # interim speech just as the silence threshold passes
    await harness.elapse(session_id, 1)

    [trigger] = _triggers(harness, session_id)
    assert trigger == {
        "reason": "silence",
        "detail": "implement",
        "proactive": True,
        "outcome": "suppressed",
        "suppressed_by": "speaking",
    }
    assert len(harness.model.requests) == 2  # no call was made: prep and the greeting only


async def test_interim_speech_holds_back_a_checkpoint_until_the_candidate_stops(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")
    await harness.send(session_id, "code_update", code="def solve():\n")
    harness.model.script(SILENT)  # the long silence (and Phase overrun) on the way there
    await harness.elapse(session_id, 34 * 60)  # 11 min left

    def time_triggers() -> list[dict[str, Any]]:
        return [t for t in _triggers(harness, session_id) if t["reason"] == "time"]

    harness.advance(59)
    for _ in range(3):  # keeps talking across the 10-minute checkpoint
        await harness.speaking(session_id)
        await harness.elapse(session_id, 1)
    assert [t.get("suppressed_by") for t in time_triggers()] == ["speaking"]

    await harness.speaking(session_id)
    await harness.elapse(session_id, 1)  # interim speech 1 s ago: still speaking
    assert len(time_triggers()) == 1

    harness.model.script("You have about ten minutes left.")
    await harness.elapse(session_id, 0.5)  # 1.5 s after the last interim result
    assert time_triggers()[-1] == {
        "reason": "time",
        "detail": "10_min_left",
        "proactive": True,
        "outcome": "spoke",
    }


async def test_a_spoken_reply_waits_for_the_candidate_to_finish(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    release = asyncio.Event()
    harness.model.script("Let me think about that.", release)
    await harness.send(session_id, "utterance", text="is the list sorted", channel="text")
    await asyncio.sleep(0)  # that reply is in flight

    # while that reply streams, the candidate says something and goes on talking
    await harness.send(session_id, "utterance", text="I mean ascending", channel="voice")
    await harness.speaking(session_id)
    release.set()
    await harness.wait_for_interviewer(session_id)
    await harness.elapse(session_id, 1)  # still talking: their speech has not settled

    assert [(t["reason"], t["outcome"]) for t in _triggers(harness, session_id)] == [
        ("typed_message", "spoke"),
    ]
    harness.model.script("Yes, ascending.")
    await harness.speak(session_id, "or descending")  # then they finish and go quiet
    assert [(t["reason"], t["outcome"]) for t in _triggers(harness, session_id)] == [
        ("typed_message", "spoke"),
        ("utterance", "spoke"),  # one reply to both fragments
    ]
    turn = str(harness.model.requests[-1].messages)
    assert "I mean ascending" in turn and "or descending" in turn


async def test_a_run_reaction_merged_into_a_held_back_spoken_reply_is_not_lost(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")
    harness.advance(50)
    await harness.send(session_id, "run", code="raise ValueError('x')\n")
    await harness.finish_run(session_id)
    await harness.speaking(session_id)  # still talking when the utterance's reply would start
    await harness.send(session_id, "utterance", text="hmm", channel="voice", start_ms=0, end_ms=1)
    for _ in range(4):  # past the Run's delay, but still talking (interim results keep coming)
        await harness.speaking(session_id)
        await harness.elapse(session_id, 1)
    assert _triggers(harness, session_id) == []  # the Run's reaction waits for the speech

    harness.model.script("What did you expect that to print?")
    await harness.send(session_id, "speaking", active=False)
    await harness.elapse(session_id, 2)  # quiet again: one reply, carrying the Run's reaction
    assert _triggers(harness, session_id) == [
        {
            "reason": "utterance",
            "proactive": False,
            "coalesced": [{"reason": "run", "detail": "failed"}],
            "outcome": "spoke",
        }
    ]


async def test_a_typed_message_is_answered_even_while_speech_is_detected(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.speaking(session_id)
    harness.model.script("Yes, it is sorted.")
    await harness.say(session_id, "is it sorted?")
    assert _triggers(harness, session_id)[-1]["outcome"] == "spoke"


# --- settling: fragments of one spoken thought share one decision call -------------------------


async def test_fragments_inside_the_settle_window_get_one_decision_call(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    calls = len(harness.model.requests)

    await harness.speak(session_id, "I think I want to", settle=False)
    harness.advance(1.0)  # a short pause: speech recognition finalized the fragment
    await harness.speak(session_id, "use a sorted", settle=False)
    harness.advance(0.5)
    harness.model.script("What would the keys be?")
    await harness.speak(session_id, "dictionary if that makes sense")

    assert len(harness.model.requests) == calls + 1
    turn = str(harness.model.requests[-1].messages)
    assert "I think I want to" in turn and "dictionary if that makes sense" in turn
    assert [t["reason"] for t in _triggers(harness, session_id)] == ["utterance"]


async def test_nothing_is_sent_before_the_speech_settles(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)
    calls = len(harness.model.requests)

    await harness.speak(session_id, "so the capacity is", settle=False)
    await harness.elapse(session_id, harness.settle_s(session_id) - 0.25)
    assert len(harness.model.requests) == calls

    harness.model.script("Yes, always positive.")
    await harness.elapse(session_id, 0.25)
    assert len(harness.model.requests) == calls + 1


async def test_a_pause_longer_than_the_settle_window_is_answered_on_its_own(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    harness.model.script(ToolCall("stay_silent", {"reason": "mid-thought"}))
    await harness.speak(session_id, "let me think")
    harness.model.script("Go on.")
    await harness.speak(session_id, "okay I have an idea")

    assert [(t["reason"], t["outcome"]) for t in _triggers(harness, session_id)] == [
        ("utterance", "silent"),
        ("utterance", "spoke"),
    ]


async def test_a_typed_message_answers_speech_still_settling(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)
    await harness.speak(session_id, "one more thing", settle=False)
    harness.model.script("Sure, go ahead.")
    await harness.say(session_id, "can I ask about inputs?")
    await harness.elapse(session_id, 5)  # the spoken fragment gets no second reply

    assert [t["reason"] for t in _triggers(harness, session_id)] == ["typed_message"]
    assert "one more thing" in str(harness.model.requests[-1].messages)


def test_the_settle_window_comes_from_config() -> None:
    from backend.agent.triggers import TriggerConfig

    assert TriggerConfig.from_settings({"utterance_settle_s": 2.5}).utterance_settle_s == 2.5
    assert TriggerConfig.from_settings({}).utterance_settle_s == 1.5


# --- muting ------------------------------------------------------------------------------------


async def test_muting_and_unmuting_are_logged_once_per_change(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)
    await harness.mute(session_id)
    await harness.mute(session_id)  # already muted
    harness.advance(30)
    await harness.mute(session_id, False)

    assert [e.type for e in harness.events(session_id) if e.type.startswith("mic_")] == [
        "mic_muted",
        "mic_unmuted",
    ]


async def test_while_muted_silence_counts_only_code_activity_with_a_doubled_threshold(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")
    await harness.mute(session_id)

    await harness.elapse(session_id, 179)  # 2 x 90 s
    assert _triggers(harness, session_id) == []
    harness.model.script("How is it going?")
    await harness.elapse(session_id, 1)
    assert [t["reason"] for t in _triggers(harness, session_id)] == ["silence"]

    # code activity opens a new silence, again doubled
    await harness.send(session_id, "code_update", code="def solve():\n")
    await harness.elapse(session_id, 179)
    assert len(_triggers(harness, session_id)) == 1
    harness.model.script(SILENT)
    await harness.elapse(session_id, 1)
    assert len(_triggers(harness, session_id)) == 2


async def test_while_muted_a_phase_click_does_not_restart_the_silence(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")
    await harness.mute(session_id)
    await harness.elapse(session_id, 100)
    await harness.send(session_id, "set_phase", phase="test")  # not code activity; test: 2 x 60 s

    harness.model.script(SILENT)
    await harness.elapse(session_id, 20)
    assert [t["detail"] for t in _triggers(harness, session_id)] == ["test"]


async def test_unmuting_restores_the_normal_silence_threshold(harness: LiveSessionHarness) -> None:
    session_id = await _connected(harness)
    await harness.send(session_id, "set_phase", phase="implement")
    await harness.mute(session_id)
    await harness.elapse(session_id, 60)
    await harness.mute(session_id, False)

    await harness.elapse(session_id, 89)
    assert _triggers(harness, session_id) == []
    harness.model.script(SILENT)
    await harness.elapse(session_id, 1)
    assert [t["reason"] for t in _triggers(harness, session_id)] == ["silence"]


# --- the Report --------------------------------------------------------------------------------


def _communication(view: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = view["report"]["rubric"]
    return next(r for r in rows if r["dimension"] == "communication")


async def test_the_report_notes_over_two_minutes_muted_under_communication(
    reports: ReportHarness,
) -> None:
    log = reports.session()
    log.say(10, "I'll start with a brute force.")
    log.event(60, "mic_muted")
    log.event(150, "mic_unmuted")
    log.event(400, "mic_muted")  # 90 s + 50 s = 2:20 muted in total
    log.end(450)
    reports.model.script(submit_report())

    view = await reports.generate(log.id)

    assert view["metrics"]["muted_ms"] == 140_000
    assert _communication(view)["note"] == (
        "Your mic was muted for 2:20 in total, so your think-aloud during that time wasn't "
        "captured; Communication is judged on less evidence."
    )
    message = str(reports.model.requests[0].messages[0]["content"])
    assert "Candidate muted their microphone" in message
    assert "muted" in str(reports.model.requests[0].system)


async def test_two_minutes_muted_or_less_adds_no_note(reports: ReportHarness) -> None:
    log = reports.session()
    log.event(60, "mic_muted")
    log.event(180, "mic_unmuted")
    log.end(450)
    reports.model.script(submit_report())

    view = await reports.generate(log.id)

    assert view["metrics"]["muted_ms"] == 120_000
    assert _communication(view)["note"] is None


async def test_muting_in_a_live_session_feeds_the_report_metric(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _connected(harness)
    await harness.mute(session_id)
    harness.advance(150)
    await harness.mute(session_id, False)
    harness.advance(10)
    harness.model.script("Thanks for your time.")
    harness.model.script(submit_report())
    await harness.send(session_id, "end_session")

    view = await harness.finish_report(session_id)
    assert view is not None
    assert view["metrics"]["muted_ms"] == 150_000
    assert _communication(view)["note"] is not None


async def test_the_utterance_silence_boundary_comes_from_config_and_is_kept_per_session(
    harness: LiveSessionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.config import load_config

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    assert load_config().voice.utterance_silence_ms == 1200

    session_id = await harness.start()
    assert harness.session(session_id).settings["voice"]["utterance_silence_ms"] == 1200
