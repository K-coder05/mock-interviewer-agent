# 13: Reconnect and Abandoned Sessions

**What to build:** If I refresh the tab mid-Session it reconnects and resumes with nothing lost and the timer still correct. If the app crashed and a Session was left hanging, it becomes an Abandoned Session that I can still generate a Report for.

**Blocked by:** 05 (First Report end to end)

**Status:** done

- [x] Client sends its last seen `seq` on reconnect; server replays missed events; timer continues on wall clock
- [x] On backend startup, `live` Sessions with no events in the configured window (10 min) become `abandoned`
- [x] Abandoned Sessions don't auto-generate a Report; a Generate report button triggers it
- [x] Live Session tests cover reconnect replay and abandoned marking

## Comments

**Built (ticket 13):**
- Reconnect: the WebSocket takes `?last_seq=N`; `LiveSession.attach(listener, last_seq)` reads the log and subscribes with no await in between, sends `replay {events, last_seq}` (events after N, `interviewer_note` left out), then the current `timer` state, then everything else in order (messages emitted meanwhile are held back). It replaces the old broadcast-the-timer-on-connect. Server messages for logged events now carry `seq` (`interviewer_done`, `run_result`, `phase`, `session_ended`; `clarification` already did).
- Backend restart: `SessionManager.live(id)` rebuilds a `live` Session it doesn't hold from its log (`LiveSession.resume`): time carries on from the wall clock (new `Clock.wall_ms()`; `created_at` now comes from the injected clock), so the downtime counts against the timer and new events are timed after it; code/dedup, timer warning/time-up, greeted state and the trigger engine are rebuilt; `TriggerEngine.resumed` drops what came due while down (past checkpoints, overrun, Run reaction, coding pause) and restarts the silence. A resumed Session past its time ends with `timeout` on the next tick.
- Abandoned: `SessionManager.abandon_stale()` runs at app startup (lifespan): a `live` Session whose last event (`created_at + max t_ms`) is `interview.abandon_after_idle_min` (10) or more ago becomes `abandoned`; no event is logged, no Report starts. The Report page's existing Generate report button (`POST .../report?regenerate=true`) generates it.
- Frontend: `SessionSocket` reconnects with backoff (0.5-5 s) and sends the page's last seen seq; messages sent while disconnected are queued (latest `code_update` only, `speaking` dropped) and close() flushes a still-connecting socket's queue first (ticket 01 note). Close code 4404 / `session_not_live` stops retrying and shows the Session as ended. `sessionLog.ts` rebuilds page state from events: a reload restores the transcript, the code (last snapshot, not the starter code), the last Run result, Phase, mic and clarifications; a replay merges in without duplicates (Interviewer replies by msg_id, the Candidate's own words matched to the entries the page added). "Running…" clears on disconnect (ticket 02 note); "Reconnecting…" shows in the top bar.
- Tests: `tests/test_reconnect.py` (replay contents and order, empty replay, live messages after the replay, seq on messages, reconnect after the end, abandoned marking incl. idle from last event and non-live untouched, Generate report for an Abandoned Session, resume after restart with wall-clock timer and continued t_ms, timeout after a long downtime, no stale Triggers on resume). Harness: `reconnect(sid, last_seq=)`, `restart(downtime_s=)`.

**Notes:**
- Ended Sessions still stay in `SessionManager._live` until restart (a reconnect after the end gets the replay and `timer: ended`).
- Replayed history is not spoken by TTS. The frontend reconnect/merge is verified by typecheck and a TestClient WebSocket smoke test only, not clicked through in a browser.
- An in-flight Run or Interviewer reply at a crash is lost (no event was logged); speaking state is momentary and not rebuilt.
