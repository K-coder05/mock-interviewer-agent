"""Live Session seam: reacting to Runs, being stuck and coding pauses; Hints and private notes."""

from typing import Any

from tests.harness import LiveSessionHarness, ToolCall
from tests.report_harness import ReportHarness, submit_report

SILENT = ToolCall("stay_silent", {"reason": "let them read the output"})
PASSING = "print(1)\n"
FAILING = "raise ValueError('bad input')\n"


async def _implementing(harness: LiveSessionHarness) -> str:
    """A connected Session in the Implement Phase, past the greeting's cooldown."""
    session_id = await harness.start()
    harness.model.script("Hi, welcome.")
    await harness.connect(session_id)
    await harness.send(session_id, "set_phase", phase="implement")
    harness.advance(50)
    return session_id


async def _run(harness: LiveSessionHarness, session_id: str, code: str) -> None:
    await harness.send(session_id, "run", code=code)
    await harness.finish_run(session_id)


def _triggers(harness: LiveSessionHarness, session_id: str) -> list[dict[str, Any]]:
    events = harness.events(session_id, "trigger")
    return [e.payload for e in events if e.payload["reason"] != "session_start"]


def _last_turn(harness: LiveSessionHarness) -> str:
    return str(harness.model.requests[-1].messages)


async def test_a_finished_run_triggers_the_interviewer_after_the_configured_delay(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _implementing(harness)
    await _run(harness, session_id, FAILING)

    await harness.elapse(session_id, 2)
    assert _triggers(harness, session_id) == []

    harness.model.script("What did you expect that to print?")
    await harness.elapse(session_id, 1)

    assert _triggers(harness, session_id) == [
        {"reason": "run", "detail": "failed", "proactive": True, "outcome": "spoke"}
    ]
    assert "<trigger>run (failed)" in _last_turn(harness)
    await harness.elapse(session_id, 60)
    assert len(_triggers(harness, session_id)) == 1  # one reaction per Run


async def test_speech_during_the_run_delay_is_merged_into_one_reply(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _implementing(harness)
    await _run(harness, session_id, PASSING)
    harness.advance(1)

    harness.model.script("Okay. What did you expect it to print?")
    await harness.say(session_id, "That printed 1, which is what I wanted.")
    await harness.elapse(session_id, 5)

    assert _triggers(harness, session_id) == [
        {
            "reason": "typed_message",
            "proactive": False,
            "coalesced": [{"reason": "run", "detail": "passed"}],
            "outcome": "spoke",
        }
    ]
    assert "Also since your last turn: run (passed)" in _last_turn(harness)


async def _run_and_react(harness: LiveSessionHarness, session_id: str, code: str) -> None:
    """Run `code` and let the Interviewer's (silent) reaction to it happen."""
    await _run(harness, session_id, code)
    harness.model.script(SILENT)
    await harness.elapse(session_id, 3)


async def test_three_failing_runs_in_a_row_mean_stuck(harness: LiveSessionHarness) -> None:
    session_id = await _implementing(harness)
    await _run_and_react(harness, session_id, "raise KeyError('a')\n")
    await _run_and_react(harness, session_id, "raise IndexError('b')\n")
    await _run_and_react(harness, session_id, "import sys\nsys.exit(2)\n")
    await _run_and_react(harness, session_id, PASSING)  # a passing Run ends the streak
    await _run_and_react(harness, session_id, "raise TypeError('c')\n")

    assert [(t["reason"], t["detail"]) for t in _triggers(harness, session_id)] == [
        ("run", "failed"),
        ("run", "failed"),
        ("stuck", "failing_runs"),
        ("run", "passed"),
        ("run", "failed"),
    ]
    assert "<trigger>stuck (failing_runs)" in str(harness.model.requests[-3].messages)


async def test_the_same_exception_twice_means_stuck(harness: LiveSessionHarness) -> None:
    session_id = await _implementing(harness)
    await _run_and_react(harness, session_id, "x = [1]\nprint(x[3])\n")
    await _run_and_react(harness, session_id, "x = [1, 2]\nprint(x[5])\n")

    assert [(t["reason"], t["detail"]) for t in _triggers(harness, session_id)] == [
        ("run", "failed"),
        ("stuck", "repeated_exception"),
    ]


async def test_the_same_syntax_error_twice_means_stuck(harness: LiveSessionHarness) -> None:
    session_id = await _implementing(harness)  # a SyntaxError is printed without a traceback
    await _run_and_react(harness, session_id, "def f(:\n")
    await _run_and_react(harness, session_id, "def f(:\n    pass\n")

    assert [t["detail"] for t in _triggers(harness, session_id)] == [
        "failed",
        "repeated_exception",
    ]


async def test_a_stuck_trigger_held_back_by_the_cooldown_is_retried(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _implementing(harness)
    await _run_and_react(harness, session_id, FAILING)
    harness.model.script("Sure.")
    await harness.say(session_id, "I'll try again.")
    await _run(harness, session_id, FAILING)  # the same exception, inside the cooldown

    await harness.elapse(session_id, 3)
    assert _triggers(harness, session_id)[-1]["outcome"] == "suppressed"

    harness.model.script("What do you think is raising that error?")
    await harness.elapse(session_id, 42)
    assert _triggers(harness, session_id)[-1] == {
        "reason": "stuck",
        "detail": "repeated_exception",
        "proactive": True,
        "outcome": "spoke",
    }


def _lines(n: int, start: int = 0) -> str:
    return "".join(f"x{i} = {i}\n" for i in range(start, start + n))


async def test_a_large_chunk_of_code_then_a_pause_asks_for_a_walkthrough(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _implementing(harness)
    await harness.send(session_id, "code_update", code=_lines(10))
    harness.advance(10)
    await harness.send(session_id, "code_update", code=_lines(24))
    await harness.elapse(session_id, 30)
    assert _triggers(harness, session_id) == []  # 24 lines is not enough

    # the pause ended that burst: the next one counts from the code as of the pause
    await harness.send(session_id, "code_update", code=_lines(25))
    await harness.elapse(session_id, 30)
    assert _triggers(harness, session_id) == []

    await harness.send(session_id, "code_update", code=_lines(40))
    harness.advance(20)
    await harness.send(session_id, "code_update", code=_lines(50))
    await harness.elapse(session_id, 29)
    assert _triggers(harness, session_id) == []

    harness.model.script("Can you walk me through this part?")
    await harness.elapse(session_id, 1)
    assert _triggers(harness, session_id) == [
        {"reason": "coding_pause", "proactive": True, "outcome": "spoke"}
    ]
    assert "<trigger>coding_pause" in _last_turn(harness)


async def test_the_decision_context_has_the_last_three_runs_numbered_code_and_the_last_diff(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _implementing(harness)
    for i in range(4):
        await _run_and_react(harness, session_id, f"print('run {i}')\n")
    await harness.send(session_id, "code_update", code="def solve(nums):\n    return nums\n")

    harness.model.script("Go on.")
    await harness.say(session_id, "Here is my function.")

    turn = _last_turn(harness)
    assert "run 0" not in turn
    assert all(f"run {i}" in turn for i in (1, 2, 3))
    assert "  1 | def solve(nums):" in turn and "  2 |     return nums" in turn
    last_diff = turn.split("<last_diff>")[1].split("</last_diff>")[0]
    assert "+    return nums" in last_diff  # everything since the Interviewer last spoke
    assert "-print('run 3')" not in last_diff  # the greeting came before any code


def _hint(level: int, text: str, *, requested: bool = False) -> ToolCall:
    return ToolCall("give_hint", {"level": level, "text": text, "requested": requested})


def _hints(harness: LiveSessionHarness, session_id: str) -> list[tuple[int, bool]]:
    return [
        (e.payload["level"], e.payload["requested"])
        for e in harness.events(session_id, "hint_given")
    ]


async def test_a_hint_when_stuck_is_spoken_and_logged_with_its_level(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _implementing(harness)
    await _run_and_react(harness, session_id, FAILING)
    await _run(harness, session_id, FAILING)
    harness.model.script(_hint(1, "What does your code do when the input is invalid?"))

    await harness.elapse(session_id, 3)

    [hint] = harness.events(session_id, "hint_given")
    assert hint.payload == {
        "level": 1,
        "text": "What does your code do when the input is invalid?",
        "requested": False,
    }
    assert harness.events(session_id, "utterance")[-1].payload["text"] == hint.payload["text"]
    assert harness.messages(session_id, "interviewer_done")[-1]["full_text"] == hint.payload["text"]
    assert _triggers(harness, session_id)[-1]["outcome"] == "spoke"


async def test_an_explicit_request_gets_one_level_above_the_last_hint_up_to_level_four(
    harness: LiveSessionHarness,
) -> None:
    session_id = await _implementing(harness)
    harness.model.script(_hint(1, "What have you tried?", requested=True))
    await harness.say(session_id, "Can I get a hint?")
    harness.model.script(_hint(2, "Look at your loop bounds."))
    await harness.say(session_id, "I'm still lost.")

    # the model asks for the wrong level; an explicit request always gets the next one
    harness.model.script(_hint(1, "Think about which technique fits.", requested=True))
    await harness.say(session_id, "Another hint please.")
    harness.model.script(_hint(2, "Try storing what you have seen so far.", requested=True))
    await harness.say(session_id, "Just tell me the answer.")
    harness.model.script(_hint(4, "Start by writing the loop over the input.", requested=True))
    await harness.say(session_id, "Please, just tell me.")

    assert _hints(harness, session_id) == [(1, True), (2, False), (3, True), (4, True), (4, True)]
    assert "The next Hint is L3." in str(harness.model.requests[-3].messages)


async def test_hints_climb_one_rung_at_a_time(harness: LiveSessionHarness) -> None:
    session_id = await _implementing(harness)
    harness.model.script("Okay, think about it.", _hint(4, "Use a dictionary of complements."))
    await harness.say(session_id, "I have no idea.")

    assert _hints(harness, session_id) == [(1, False)]
    assert harness.events(session_id, "utterance")[-1].payload["text"] == (
        "Okay, think about it. Use a dictionary of complements."
    )


async def test_probes_are_not_hints(harness: LiveSessionHarness) -> None:
    session_id = await _implementing(harness)
    harness.model.script("What is the time complexity of that?")
    await harness.say(session_id, "I think my approach works.")

    assert harness.events(session_id, "hint_given") == []


async def test_notes_are_logged_privately_and_never_sent_live(harness: LiveSessionHarness) -> None:
    session_id = await _implementing(harness)
    harness.model.script(
        "Okay.", ToolCall("note", {"observation": "Started coding without stating complexity."})
    )
    await harness.say(session_id, "Let me just start coding.")

    [note] = harness.events(session_id, "interviewer_note")
    assert note.payload == {"observation": "Started coding without stating complexity."}
    assert "complexity" not in str(harness.sent[session_id])


async def test_hints_and_private_notes_reach_the_report_input_and_probes_are_not_hints(
    reports: ReportHarness,
) -> None:
    log = reports.session()
    log.say(60, "What is the complexity of that?", speaker="interviewer")  # a Probe
    log.event(120, "hint_given", level=2, text="Look at your loop bounds.", requested=True)
    log.event(130, "interviewer_note", observation="Started coding without stating complexity.")
    log.end(600)
    reports.model.script(submit_report())

    report = await reports.generate(log.id)

    message = str(reports.model.requests[-1].messages)
    assert "t_ms=120000 02:00] Hint L2 (the candidate asked for it): Look at your loop bounds." in message
    assert (
        "t_ms=130000 02:10] Interviewer private note: Started coding without stating complexity."
        in message
    )
    assert "Probes" in str(reports.model.requests[-1].system)
    assert report is not None
    assert report["metrics"]["hints_by_level"] == {"1": 0, "2": 1, "3": 0, "4": 0}
