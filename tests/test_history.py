"""History and replay seam: the Session list and the replay data, read from stored events."""

from backend.history import list_history, replay
from tests.report_harness import ReportHarness, submit_report


async def test_the_list_shows_title_date_duration_and_overall_signal_newest_first(
    reports: ReportHarness,
) -> None:
    older = reports.ended_session()
    reports.model.script(submit_report())
    await reports.generate(older.id)
    newer = reports.session(problem_md="# Three Sum\n\nFind triples.")
    newer.end(90)

    rows = list_history(reports.store)

    assert [r["id"] for r in rows] == [newer.id, older.id]
    assert rows[1]["title"] == "Two Sum"
    assert rows[1]["duration_ms"] == 600_000
    assert rows[1]["overall_signal"] in {"Strong No", "No", "Lean No", "Lean Hire", "Hire", "Strong Hire"}
    assert rows[1]["created_at"]
    assert (rows[0]["title"], rows[0]["duration_ms"], rows[0]["overall_signal"]) == (
        "Three Sum", 90_000, None)


async def test_replay_has_every_snapshot_run_and_the_code_that_ran(reports: ReportHarness) -> None:
    log = reports.session(starter_code="# start\n")
    first = log.code(60, "x = 1\n")
    log.run(70, stdout="ok\n")
    log.code(100, "x = 2\n")
    log.end(120)

    data = replay(reports.store, log.id)

    assert data is not None
    events = {e["seq"]: e for e in data["events"]}
    [run] = [e for e in data["events"] if e["type"] == "run"]
    assert run["payload"]["snapshot_seq"] == first.seq
    assert events[first.seq]["payload"]["code"] == "x = 1\n"
    assert data["duration_ms"] == 120_000


async def test_markers_for_runs_hints_phases_and_silence_gaps(reports: ReportHarness) -> None:
    log = reports.session()
    log.event(20, "phase_changed", to="approach", by="agent", **{"from": "clarify"})
    log.code(30, "x = 1\n")
    log.run(40, stderr="Boom", exit_code=1)
    log.event(50, "hint_given", level=2, text="Think about a map.", requested=True)
    log.event(55, "interviewer_note", observation="private")
    log.end(200)  # nothing from the Candidate after the Run at 40 s

    data = replay(reports.store, log.id)

    assert data is not None
    simple = [(m["kind"], m["t_ms"], m["label"]) for m in data["markers"]]
    assert simple == [
        ("phase", 20_000, "Phase: approach"),
        ("run", 40_000, "Run failed"),
        ("silence", 40_000, "Silence 2:40"),
        ("hint", 50_000, "Hint L2"),
    ]
    [silence] = [m for m in data["markers"] if m["kind"] == "silence"]
    assert (silence["t_ms"], silence["end_ms"]) == (40_000, 200_000)
    assert all(e["type"] != "interviewer_note" for e in data["events"])


async def test_replay_of_an_unknown_session_is_none(reports: ReportHarness) -> None:
    assert replay(reports.store, "ses_nope") is None
