# 15: Export, delete and regenerate

**What to build:** From History I can export a Session as JSONL with its Report, delete a Session after confirming, and regenerate its Report from the stored events.

**Blocked by:** 14 (History and replay)

**Status:** done

- [x] Export returns JSONL of all events plus the Report
- [x] Delete (with confirmation) hard-deletes the Session, its events and its Report
- [x] Regenerate rebuilds the Report from stored events and replaces the old one

## Comments

**Built (ticket 15):**
- `backend/history.py`: `export_jsonl` (lines tagged `kind`: `session`, one `event` per stored event incl. interviewer notes, `report` when present) and `delete_session` (refuses a live Session or one whose Report is generating -> `busy`). `Store.delete_session` removes events, Report and Session. API: `GET /api/sessions/{id}/export` (download, `application/x-ndjson`) and `DELETE /api/sessions/{id}` (404 unknown, 409 busy).
- Regenerate reuses the existing `POST .../report?regenerate=true` (a failed regeneration keeps the old Report); now covered by a test.
- Frontend: History rows get Export, Generate/Regenerate report and Delete (window.confirm); the Report page has Export JSONL, Regenerate report and Delete (returns to History). Not clicked through in a browser.
- Tests in `tests/test_history.py`.
