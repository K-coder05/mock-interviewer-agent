# 04: Timer and ending a Session

**What to build:** A countdown timer (default 45 min, chosen on setup) starts when the Interviewer's greeting begins. It turns red at 5 minutes left with a warning. At 0:00 the Interviewer says time is up and asks for any last thought; the Session ends automatically 60 s later. I can click End Interview at any time. The Interviewer closes politely with no verdict.

**Blocked by:** 03 (Problem prep and a text-chat Interviewer)

**Status:** done

- [x] Duration is chosen on setup and stored in settings
- [x] Timer starts at greeting, not at Session creation; `timer` updates reach the UI
- [x] 5-minute warning turns the timer red
- [x] At 0:00 the Interviewer prompts for a last thought; auto-end after the configured grace (60 s) unless ended earlier
- [x] End Interview and auto-end both emit `session_ended` (reason user/timeout, final code) and set status `ended`
- [x] Live Session tests with the fake clock cover warning, grace and auto-end

## Comments

**Built (ticket 04):**
- Duration: `duration_min` on `POST /api/sessions` (1-180, default from config), stored in `settings.duration_min`; `settings.timeout_grace_s` (from `interview.timeout_grace_s`) stored alongside. Setup page has a duration field (5-180 min).
- Timer (`LiveSession`): starts on the first greeting delta (`_start_timer`, event `timer_started`), not at creation. `tick()` is the only timer logic: 5-minute `timer_warning`, at 0:00 `time_up` (Interviewer reply with trigger `time_up`), then `end("timeout")` after the grace. A polling task calls `tick()` every second in production; the harness disables it (`timer_poll_s=None`) and tests call `await harness.elapse(sid, seconds)`.
- Ending: `end_session` WS message or auto-end -> Interviewer closes (trigger `session_end`, no verdict, skipped if never greeted) -> `session_ended {reason: user|timeout, final_code}` event, `Store.end_session` (status `ended`, `ended_at`), server messages `timer {state: ended}` and `session_ended`. Idempotent; later client messages get error `session_ended`.
- Server `timer` message: `{state: running|warning|time_up|ended, remaining_ms, duration_ms}`, sent on changes only; the UI counts down locally. Turn message now includes `<time_left>`.
- UI: top-bar countdown (red + note at warning/time-up), End Interview button (confirm), composer disabled after the end.

**Notes for later tickets:**
- Ticket 05: report generation should be kicked off after `session_ended`; `LiveSession.end` is the place (status moves to `report_*` later).
- Ticket 13: on reconnect the server does not re-send the current `timer` state (a refreshed tab shows `--:--` until the next change); resend it on connect. A greeting that fails before any delta leaves the timer unstarted. `SessionManager.close()` is called on app shutdown.
- Ticket 09: the reply queue is newest-trigger-wins, so a queued `time_up` can be replaced by a later trigger; coalescing should keep time triggers.
- Not clicked through in a browser.
