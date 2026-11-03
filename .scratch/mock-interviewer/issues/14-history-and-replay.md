# 14: History and replay

**What to build:** A History page lists my past Sessions with title, date, duration and Overall Signal. Opening one shows its Report and a replay: a timeline scrubber that shows the exact code at any moment beside the transcript, with markers for Runs, Hints, Phase changes and long silences. Clicking any evidence timestamp in a Report jumps the replay there.

**Blocked by:** 05 (First Report end to end)

**Status:** done

- [x] Sessions list (title = first line of the problem, date, duration, Overall Signal)
- [x] Replay shows the read-only code snapshot at any chosen timestamp beside the transcript scrolled to that moment
- [x] Each Run in replay shows the exact code that ran
- [x] Timeline markers for Runs, Hints, Phase changes and silence gaps
- [x] Evidence timestamps in the Report jump the replay

## Comments

**Built (ticket 14):**
- `backend/history.py`: `list_history(store)` (id, title, created_at, status, duration_ms from the end event else the last event, Overall Signal label or null) and `replay(store, id)` (public Session, events without `interviewer_note`, `duration_ms`, `markers` for Runs, Hints, Phase changes and silence gaps, time-ordered; silence reuses `metrics.silence_gaps`, now public). API: `GET /api/sessions` and `GET /api/sessions/{id}/replay`.
- Frontend: `#/history` (`HistoryPage`, linked from Setup and the Report page; live rows link to the interview, others to the Report page). The Report page now embeds `ReplayPanel` (range scrubber, clickable marker track, read-only code at the moment beside the transcript up to it, "Runs so far" with the exact code each Run executed via `snapshot_seq`). Evidence and Candidate-test timestamps in the Report are buttons that set the replay position and scroll to it. Pure state in `frontend/src/replay.ts` (`codeAt`, `transcriptAt`, `runsAt`, `clock`), tested in `replay.test.ts`.
- Tests: `tests/test_history.py` (list fields and order, replay events/code that ran, markers incl. silence, notes hidden, unknown Session).

**Notes for ticket 15:** export/delete/regenerate buttons belong on `HistoryPage` rows and the Report page; there is no replay route of its own (replay lives on the Report page, so a deep link to a moment is not supported). The replay panel is not clicked through in a browser (typecheck and unit tests only).
