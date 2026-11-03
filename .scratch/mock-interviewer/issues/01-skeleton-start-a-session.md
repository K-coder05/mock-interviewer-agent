# 01: Skeleton: start a Session and type code

**What to build:** The first end-to-end path through every layer. After cloning, `make install && make dev` starts the backend and frontend; the backend refuses to start with a clear message if the API key is missing. On the setup screen I paste a problem (Markdown) and optional starter code and click Start; a Session is created and stored, and the interview screen opens with the rendered problem and a Python 3 Monaco editor (4-space tabs, no autocomplete) preloaded with the starter code. As I type, the editor syncs to the backend over the Session's WebSocket and each distinct buffer is recorded as a code snapshot in the event log.

This ticket also establishes the Live Session test harness (message driver, fake clock, scripted fake model) that all later Session tests reuse. See the spec's Testing Decisions.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Fresh clone → `make install && make dev` → setup screen works in Chrome
- [ ] Backend fails fast with a clear message when the API key is missing
- [ ] Creating a Session persists it (status `live`) and emits `session_started`
- [ ] Starter code (if any) is recorded as the first code snapshot at t=0 and appears in the editor
- [ ] Code syncs after 1.5 s idle or every 10 s while typing; unchanged buffers produce no snapshot
- [ ] Events carry server-owned `seq` and `t_ms` from a monotonic clock
- [ ] Live Session harness exists and a test drives a Session through code updates with a fake clock and asserts on the event log
