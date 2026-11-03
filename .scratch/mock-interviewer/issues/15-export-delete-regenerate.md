# 15: Export, delete and regenerate

**What to build:** From History I can export a Session as JSONL with its Report, delete a Session after confirming, and regenerate its Report from the stored events.

**Blocked by:** 14 (History and replay)

**Status:** ready-for-agent

- [ ] Export returns JSONL of all events plus the Report
- [ ] Delete (with confirmation) hard-deletes the Session, its events and its Report
- [ ] Regenerate rebuilds the Report from stored events and replaces the old one
