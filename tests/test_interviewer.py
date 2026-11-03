"""Live Session seam: problem prep and the text-chat Interviewer, driven by a scripted fake model."""

import asyncio

import pytest

from backend.agent.model import ModelError
from backend.agent.prep import PrepFailed
from tests.harness import DEFAULT_BRIEF, LiveSessionHarness, Style, ToolCall


async def test_start_prepares_a_hidden_problem_brief_with_the_prep_model(
    harness: LiveSessionHarness,
) -> None:
    session_id = await harness.start(
        problem_md="# Two Sum\n\nFind two numbers.", private_notes="Intended: O(n) hash map."
    )

    assert harness.session(session_id).problem_brief == DEFAULT_BRIEF
    [prep] = harness.model.requests
    assert prep.model == "claude-opus-5-5"
    assert "Find two numbers." in str(prep.messages)
    assert "Intended: O(n) hash map." in str(prep.messages)


async def test_prep_is_retried_once_after_an_invalid_brief(harness: LiveSessionHarness) -> None:
    harness.model.script(ToolCall("submit_problem_brief", {"approaches": []}))
    harness.model.script(ToolCall("submit_problem_brief", DEFAULT_BRIEF))

    session_id = await harness.start(brief=None)

    assert harness.session(session_id).problem_brief == DEFAULT_BRIEF
    assert len(harness.model.requests) == 2


async def test_prep_failing_twice_creates_no_session(harness: LiveSessionHarness) -> None:
    harness.model.script("I think the answer is a hash map.")  # no tool call
    harness.model.script(ToolCall("submit_problem_brief", {"pitfalls": "none"}))

    with pytest.raises(PrepFailed):
        await harness.start(brief=None)

    assert len(harness.model.requests) == 2
    assert harness.store.list_sessions() == []


async def test_first_client_connection_gets_a_streamed_greeting(harness: LiveSessionHarness) -> None:
    session_id = await harness.start(problem_md="# Two Sum\n\nFind two numbers.")
    harness.model.script("Hi, thanks for joining. ", "Today you'll find two numbers that sum to a target.")

    harness.advance(2)
    await harness.connect(session_id)
    await harness.connect(session_id)  # a second client (e.g. another tab) doesn't greet again

    greeting = harness.model.requests[-1]
    assert greeting.model == "claude-sonnet-5-5"
    assert "session_start" in str(greeting.messages)
    deltas = harness.messages(session_id, "interviewer_delta")
    [done] = harness.messages(session_id, "interviewer_done")
    assert [d["text"] for d in deltas] == [
        "Hi, thanks for joining. ",
        "Today you'll find two numbers that sum to a target.",
    ]
    assert {d["msg_id"] for d in deltas} == {done["msg_id"]}
    assert done["full_text"] == (
        "Hi, thanks for joining. Today you'll find two numbers that sum to a target."
    )
    [utterance] = harness.events(session_id, "utterance")
    assert utterance.payload["speaker"] == "interviewer"
    assert utterance.payload["text"] == done["full_text"]
    assert utterance.t_ms == 2_000


async def test_a_typed_message_is_logged_and_always_gets_a_streamed_reply(
    harness: LiveSessionHarness,
) -> None:
    session_id = await harness.start()
    harness.model.script("Hello! Let's get started.")
    await harness.connect(session_id)

    harness.advance(30)
    harness.model.script("Sure, ", "take your time.")
    await harness.say(session_id, "Can I think for a second?")

    utterances = harness.events(session_id, "utterance")
    assert [(u.payload["speaker"], u.payload["text"]) for u in utterances] == [
        ("interviewer", "Hello! Let's get started."),
        ("user", "Can I think for a second?"),
        ("interviewer", "Sure, take your time."),
    ]
    assert utterances[1].payload["channel"] == "text"
    assert utterances[1].t_ms == 30_000
    assert [d["text"] for d in harness.messages(session_id, "interviewer_delta")][-2:] == [
        "Sure, ",
        "take your time.",
    ]
    assert harness.messages(session_id, "interviewer_done")[-1]["full_text"] == (
        "Sure, take your time."
    )


async def test_each_decision_call_rebuilds_its_context_from_the_event_log_with_a_stable_system(
    harness: LiveSessionHarness,
) -> None:
    session_id = await harness.start(starter_code="def two_sum(nums, target):\n    pass\n")
    harness.model.script("Hello!")
    await harness.connect(session_id)
    await harness.send(session_id, "code_update", code="def two_sum(nums, target):\n    seen = {}\n")
    harness.model.script("Okay.")
    await harness.say(session_id, "I'll use a dictionary.")

    greeting, reply = harness.model.requests[1:]
    assert greeting.system == reply.system
    assert len(reply.messages) == 1  # no running history: one message rebuilt from the log
    context = str(reply.messages[0]["content"])
    assert "Hello!" in context
    assert "I'll use a dictionary." in context
    assert "seen = {}" in context
    assert "typed_message" in context


async def test_clarifications_from_the_brief_are_recorded_and_shown_under_the_problem(
    harness: LiveSessionHarness,
) -> None:
    session_id = await harness.start()
    harness.model.script(
        "Yes, there is always exactly one answer.",
        ToolCall(
            "record_clarification",
            {
                "question": "Is there always exactly one answer?",
                "answer": "Yes.",
                "by": "interviewer",
            },
        ),
    )

    await harness.say(session_id, "Is there always exactly one answer?")

    [clarification] = harness.events(session_id, "clarification")
    assert clarification.payload == {
        "question": "Is there always exactly one answer?",
        "answer": "Yes.",
        "by": "interviewer",
    }
    [message] = harness.messages(session_id, "clarification")
    assert message["by"] == "interviewer" and message["seq"] == clarification.seq


async def test_an_open_question_becomes_a_binding_assumption_by_the_candidate(
    harness: LiveSessionHarness,
) -> None:
    session_id = await harness.start()
    harness.model.script("Good question. What would you assume?")
    await harness.say(session_id, "Can the input be empty?")
    harness.model.script(
        "Okay, let's go with that.",
        ToolCall(
            "record_clarification",
            {
                "question": "Can the input be empty?",
                "answer": "Assume the input always has at least two numbers.",
                "by": "candidate",
            },
        ),
    )

    await harness.say(session_id, "I'd assume there are always at least two numbers.")

    [clarification] = harness.events(session_id, "clarification")
    assert clarification.payload["by"] == "candidate"
    assert clarification.payload["answer"] == "Assume the input always has at least two numbers."
    assert harness.messages(session_id, "clarification")[0]["by"] == "candidate"
    # The binding clarification is part of every later decision call's context.
    harness.model.script("Sure.")
    await harness.say(session_id, "Okay, starting now.")
    assert "Assume the input always has at least two numbers." in str(
        harness.model.requests[-1].messages
    )


async def test_invalid_tool_calls_are_ignored(harness: LiveSessionHarness) -> None:
    session_id = await harness.start()
    harness.model.script(
        "Okay.", ToolCall("record_clarification", {"question": "Sorted?", "by": "someone"})
    )

    await harness.say(session_id, "Is it sorted?")

    assert harness.events(session_id, "clarification") == []
    assert harness.messages(session_id, "interviewer_done")[-1]["full_text"] == "Okay."


async def test_private_notes_and_the_brief_never_reach_the_client(
    harness: LiveSessionHarness,
) -> None:
    secret_notes = "SECRET-NOTES: intended O(n) with a hash map"
    session_id = await harness.start(private_notes=secret_notes)
    harness.model.script("Hello!")
    await harness.connect(session_id)

    system = harness.model.requests[-1].system
    assert secret_notes in system
    assert "Store complements while scanning once." in system  # from the brief
    client_visible = str(
        [harness.session(session_id).to_public_dict()]
        + [e.to_dict() for e in harness.events(session_id)]
        + harness.messages(session_id)
    )
    assert "SECRET-NOTES" not in client_visible
    assert "Store complements while scanning once." not in client_visible


async def test_style_is_stored_in_settings_and_changes_only_the_persona_section(
    harness: LiveSessionHarness,
) -> None:
    systems = []
    for style in (Style(preset="friendly_new_grad"), Style(custom="A terse principal engineer.")):
        session_id = await harness.start(style=style)
        assert harness.session(session_id).settings["style"] == style.to_settings()
        harness.model.script("Hello!")
        await harness.connect(session_id)
        systems.append(harness.model.requests[-1].system)

    def without_persona(system: str) -> str:
        before, rest = system.split("<persona>", 1)
        return before + rest.split("</persona>", 1)[1]

    assert without_persona(systems[0]) == without_persona(systems[1])
    assert "A terse principal engineer." in systems[1]
    assert systems[0] != systems[1]


async def test_a_model_failure_is_reported_to_the_client(harness: LiveSessionHarness) -> None:
    session_id = await harness.start()

    await harness.say(session_id, "Hello?")  # nothing scripted: the fake model raises

    [error] = harness.messages(session_id, "error")
    assert error["code"] == "interviewer_failed"
    assert harness.messages(session_id, "interviewer_done") == []


async def test_typed_messages_during_a_reply_are_answered_by_one_follow_up_reply(
    harness: LiveSessionHarness,
) -> None:
    session_id = await harness.start()
    harness.model.script("First ", "reply.")
    harness.model.script("Second reply.")

    await harness.send(session_id, "utterance", text="One", channel="text")
    while not harness.messages(session_id, "interviewer_delta"):  # the first reply is streaming
        await asyncio.sleep(0)
    await harness.send(session_id, "utterance", text="Two", channel="text")
    await harness.say(session_id, "Three")

    done = harness.messages(session_id, "interviewer_done")
    assert [d["full_text"] for d in done] == ["First reply.", "Second reply."]
    follow_up = str(harness.model.requests[-1].messages)
    assert "Two" in follow_up and "Three" in follow_up


async def test_a_typed_message_answered_only_with_a_tool_call_still_gets_a_spoken_reply(
    harness: LiveSessionHarness,
) -> None:
    session_id = await harness.start()
    harness.model.script(
        ToolCall(
            "record_clarification",
            {"question": "Is there always one answer?", "answer": "Yes.", "by": "interviewer"},
        )
    )
    harness.model.script("Yes, there's always exactly one answer.")

    await harness.say(session_id, "Is there always one answer?")

    assert len(harness.events(session_id, "clarification")) == 1
    assert [d["full_text"] for d in harness.messages(session_id, "interviewer_done")] == [
        "Yes, there's always exactly one answer."
    ]
    # The retry sees the clarification it already recorded, so it won't record it twice.
    assert "Is there always one answer?" in str(harness.model.requests[-1].messages)


async def test_a_reply_that_fails_mid_stream_is_cancelled(harness: LiveSessionHarness) -> None:
    session_id = await harness.start()
    harness.model.script("Let me ", ModelError("model_unavailable", "Overloaded."))

    await harness.say(session_id, "Hello?")

    [delta] = harness.messages(session_id, "interviewer_delta")
    [cancel] = harness.messages(session_id, "interviewer_cancel")
    assert harness.messages(session_id, "error")[0]["code"] == "model_unavailable"
    assert cancel["msg_id"] == delta["msg_id"]
    assert harness.messages(session_id, "interviewer_done") == []
    assert [e.payload["speaker"] for e in harness.events(session_id, "utterance")] == ["user"]
