"""History and replay seam: the Session list and the replay data, read from stored events."""

import json

from backend.history import delete_session, export_jsonl, list_history, replay
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


async def test_export_is_jsonl_of_every_event_plus_the_report(reports: ReportHarness) -> None:
    log = reports.ended_session()
    log.event(40, "interviewer_note", observation="private")
    reports.model.script(submit_report())
    await reports.generate(log.id)

    text = export_jsonl(reports.store, log.id)

    assert text is not None and text.endswith("\n")
    lines = [json.loads(line) for line in text.splitlines()]
    events = [line for line in lines if line["kind"] == "event"]
    assert len(events) == len(reports.store.events(log.id))
    assert any(e["type"] == "interviewer_note" for e in events)
    assert [line["kind"] for line in lines][0] == "session"
    assert lines[-1]["kind"] == "report"
    assert lines[-1]["report"]["overall_signal"]["label"]


async def test_export_without_a_report_has_no_report_line_and_unknown_is_none(
    reports: ReportHarness,
) -> None:
    log = reports.ended_session()
    text = export_jsonl(reports.store, log.id)
    assert text is not None
    assert "report" not in [json.loads(line)["kind"] for line in text.splitlines()]
    assert export_jsonl(reports.store, "ses_nope") is None


async def test_delete_removes_the_session_its_events_and_its_report(reports: ReportHarness) -> None:
    keep = reports.ended_session()
    gone = reports.ended_session()
    reports.model.script(submit_report())
    await reports.generate(gone.id)

    assert delete_session(reports.store, gone.id, generating=False) == "deleted"

    assert reports.store.get_session(gone.id) is None
    assert reports.store.events(gone.id) == []
    assert reports.store.get_report(gone.id) is None
    assert [r["id"] for r in list_history(reports.store)] == [keep.id]
    assert reports.store.events(keep.id)
    assert delete_session(reports.store, gone.id, generating=False) == "not_found"


async def test_a_live_or_generating_session_is_not_deleted(reports: ReportHarness) -> None:
    live = reports.session()
    ended = reports.ended_session()

    assert delete_session(reports.store, live.id, generating=False) == "busy"
    assert delete_session(reports.store, ended.id, generating=True) == "busy"
    assert reports.store.get_session(live.id) is not None
    assert reports.store.get_session(ended.id) is not None


async def test_regenerating_replaces_the_old_report_from_the_stored_events(
    reports: ReportHarness,
) -> None:
    log = reports.ended_session()
    reports.model.script(submit_report(summary="First."))
    await reports.generate(log.id)
    reports.model.script(submit_report(summary="Second."))

    view = await reports.generate(log.id)

    assert view["status"] == "report_ready"
    assert view["report"]["summary"] == "Second."
    assert reports.report(log.id).report["summary"] == "Second."  # type: ignore[union-attr]
