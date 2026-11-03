# 01: Skeleton: start a Session and type code

**What to build:** The first end-to-end path through every layer. After cloning, `make install && make dev` starts the backend and frontend; the backend refuses to start with a clear message if the API key is missing. On the setup screen I paste a problem (Markdown) and optional starter code and click Start; a Session is created and stored, and the interview screen opens with the rendered problem and a Python 3 Monaco editor (4-space tabs, no autocomplete) preloaded with the starter code. As I type, the editor syncs to the backend over the Session's WebSocket and each distinct buffer is recorded as a code snapshot in the event log.

This ticket also establishes the Live Session test harness (message driver, fake clock, scripted fake model) that all later Session tests reuse. See the spec's Testing Decisions.

**Blocked by:** None (can start immediately)

**Status:** done

- [ ] Fresh clone → `make install && make dev` → setup screen works in Chrome
- [x] Backend fails fast with a clear message when the API key is missing
- [x] Creating a Session persists it (status `live`) and emits `session_started`
- [x] Starter code (if any) is recorded as the first code snapshot at t=0 and appears in the editor
- [x] Code syncs after 1.5 s idle or every 10 s while typing; unchanged buffers produce no snapshot
- [x] Events carry server-owned `seq` and `t_ms` from a monotonic clock
- [x] Live Session harness exists and a test drives a Session through code updates with a fake clock and asserts on the event log

## Comments

**Built (ticket 01):**
- Backend (`backend/`): `config.py` (config.yaml + .env; `ConfigError` when `ANTHROPIC_API_KEY` is missing), `__main__.py` (`python -m backend [--check] [--reload]`, prints a clear error and exits 1 without the key), `db.py` (`Store`: sessions/events/reports tables; assigns `seq` per Session on append), `clock.py` (`Clock` protocol + `SystemClock`), `session.py` (`SessionManager.create` persists a `live` Session, emits `session_started` at t=0 and the starter code as the first `code_snapshot` at t=0; `LiveSession.handle(message)` processes WebSocket-shaped messages, currently `code_update` with dedup + unified diff + chars added/removed; unknown types get an `error` server message), `agent/model.py` (`ModelClient` protocol: `stream(ModelRequest)` yields `TextDelta`s then `ToolCall`s), `main.py` (`create_app`: `POST /api/sessions`, `GET /api/sessions/{id}`, `WS /ws/sessions/{id}`).
- Frontend (`frontend/`): Vite + React + TS. Setup page (problem Markdown + optional starter code → Start), interview page (rendered problem, Monaco Python editor bundled locally, 4-space tabs, autocomplete off), `codeSync.ts` (send after 1.5 s idle or every 10 s while typing; skips unchanged buffers; `flush()` ready for "before final utterance / Run"), `ws.ts` typed socket.
- Live Session harness (`tests/harness.py`, fixture `harness` in `tests/conftest.py`): `FakeClock` (`advance(seconds)`, optional `tick_per_read_ms`), `ScriptedModel` (scripted text/tool-call turns, records `requests`), `LiveSessionHarness` (`start()`, `await send(sid, type, **payload)`, `advance()`, `events(sid, type)`, `messages(sid, type)`, `session(sid)`).

**Commands:** `make install`, `make dev`, `make test` (pytest), `make typecheck` (mypy --strict + tsc), `make check`; single file: `uv run pytest tests/test_live_session.py`.

**Notes for later tickets:**
- The Session engine does not take a model yet (removed as speculative after review). `tests/harness.py` already builds a `ScriptedModel` as `harness.model`; ticket 03 should add a `model: ModelClient` param to `SessionManager`/`LiveSession`, pass `harness.model` in, and add the Anthropic-backed client (plus the `anthropic` dependency) for production.
- Code review (two-axis) found no spec gaps. Fixed: single event-append path (`LiveSession.begin()`), typed `SessionStatus`, `ModelIds` passed through, idempotent unsubscribe, a failing listener no longer blocks the others. Left: char-level diff is O(n^2) (fine for interview-sized buffers); frontend `CodeSync` timing has no automated test (spec limits frontend tests to the echo guard); the unmount flush can be dropped if the socket is still connecting.
- `Clock` only has `monotonic_ms()`. Timer/trigger tickets will need scheduling (e.g. `call_later` or a `tick()` the engine runs); extend `FakeClock` so `advance()` fires due callbacks.
- `t_ms` is measured from Session creation. Ticket 04 starts the *timer* at the greeting; that's separate from the event-log time base.
- Live Sessions are held in memory only; after a backend restart the WebSocket replies `session_not_live` and closes (reconnect/abandoned marking is ticket 13).
- No private notes, Style, duration or autocomplete inputs on setup yet (settings store defaults: 45 min, autocomplete false); ticket 03/04 add them.
- Manually verified the full stack via the Vite proxy (create Session, WS `code_update`, event log). Not clicked through in a real Chrome window by the agent.

- 2026-11-02 (orchestrator): Not yet verified in a real browser. Unticked the Chrome box until someone runs `make dev` and uses the setup screen in Chrome.
