"""Live Session seam: drive a Session with WebSocket-shaped messages and a fake clock,
assert on the event log and emitted server messages."""

from tests.harness import LiveSessionHarness


async def test_creating_a_session_persists_it_live_and_emits_session_started(
    harness: LiveSessionHarness,
) -> None:
    session_id = harness.start(problem_md="# Two Sum\n\nFind two numbers.")

    session = harness.session(session_id)
    assert session.status == "live"
    assert session.title == "Two Sum"
    events = harness.events(session_id)
    assert [e.type for e in events] == ["session_started"]
    assert events[0].seq == 1
    assert events[0].t_ms == 0
    assert events[0].payload["problem_md"] == "# Two Sum\n\nFind two numbers."
    assert events[0].payload["settings"]["autocomplete"] is False


async def test_starter_code_is_the_first_code_snapshot_at_t0(harness: LiveSessionHarness) -> None:
    harness.advance(5)  # wall time before creation must not leak into t_ms
    harness.clock.tick_per_read_ms = 7  # nor may time spent while creating the Session
    session_id = harness.start(starter_code="def two_sum(nums, target):\n    pass\n")

    events = harness.events(session_id)
    assert [e.type for e in events] == ["session_started", "code_snapshot"]
    snapshot = events[1]
    assert snapshot.t_ms == 0
    assert snapshot.seq == 2
    assert snapshot.payload["code"] == "def two_sum(nums, target):\n    pass\n"


async def test_no_starter_code_means_no_initial_snapshot(harness: LiveSessionHarness) -> None:
    session_id = harness.start(starter_code="")

    assert harness.events(session_id, "code_snapshot") == []


async def test_code_updates_record_each_distinct_buffer_with_server_seq_and_t_ms(
    harness: LiveSessionHarness,
) -> None:
    session_id = harness.start(starter_code="def f():\n    pass\n")

    harness.advance(12.5)
    await harness.send(session_id, "code_update", code="def f():\n    return 1\n")
    harness.advance(1.5)
    await harness.send(session_id, "code_update", code="def f():\n    return 1\n")  # unchanged
    harness.advance(10)
    await harness.send(session_id, "code_update", code="def f():\n    return 42\n")

    snapshots = harness.events(session_id, "code_snapshot")
    assert [(s.seq, s.t_ms) for s in snapshots] == [(2, 0), (3, 12_500), (4, 24_000)]
    assert [s.payload["code"] for s in snapshots] == [
        "def f():\n    pass\n",
        "def f():\n    return 1\n",
        "def f():\n    return 42\n",
    ]
    second = snapshots[1].payload
    assert second["chars_added"] == 8  # "return 1" replaces "pass"
    assert second["chars_removed"] == 4
    assert "-    pass" in second["diff_from_prev"]
    assert "+    return 1" in second["diff_from_prev"]


async def test_resending_the_starter_code_produces_no_snapshot(harness: LiveSessionHarness) -> None:
    session_id = harness.start(starter_code="x = 1\n")

    harness.advance(3)
    await harness.send(session_id, "code_update", code="x = 1\n")

    assert len(harness.events(session_id, "code_snapshot")) == 1


async def test_unknown_messages_get_an_error_and_no_event(harness: LiveSessionHarness) -> None:
    session_id = harness.start()

    await harness.send(session_id, "teleport")

    assert [m["code"] for m in harness.messages(session_id, "error")] == ["unknown_message"]
    assert [e.type for e in harness.events(session_id)] == ["session_started"]
