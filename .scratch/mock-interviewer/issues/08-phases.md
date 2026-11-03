# 08: Phases

**What to build:** The top bar shows the current Phase (Clarify, Approach, Implement, Test, Wrap-up). The Interviewer moves it as the Session progresses, and I can click to set any Phase, forward or back. After I set it, the Interviewer won't change it for 2 minutes. The Report shows time per Phase as a timeline bar and judges Correctness on my code as of the start of Wrap-up.

**Blocked by:** 03 (Problem prep and a text-chat Interviewer), 05 (First Report end to end)

**Status:** done

- [x] `phase_changed` events record from, to and by (agent/user)
- [x] Agent `set_phase` is ignored for the configured lock (2 min) after a user change
- [x] Phases can move backward
- [x] Time-per-phase metric sums all intervals per Phase; Report shows a phase timeline bar
- [x] Correctness uses the last snapshot before Wrap-up began (final code if Wrap-up never began)
- [x] Interviewer brings an overrun Phase to a close (e.g. clarifying > 8 min)
- [x] Live Session tests cover the user lock and backward moves; Report seam test covers Correctness snapshot selection

## Comments

**Built (ticket 08):**
- `backend/phases.py`: Phase ids (`clarify`, `approach`, `implement`, `test`, `wrap_up`), `current(events)` and `time_per_phase(events, end_ms)`; the Session starts in `clarify` with no event. `WRAP_UP` moved here (`report.py` imports it).
- Session: client `set_phase {phase}` (user, always applies, any direction); Interviewer tool `set_phase` (ignored for `interview.user_phase_lock_s`, 120 s, after the Candidate's last change; stored in `settings.user_phase_lock_s`). Both log `phase_changed {from, to, by: agent|user}` and emit `{type: "phase", phase, by}`. Setting the current Phase is a no-op.
- Interviewer context: a `<phase>` block with time in Phase, the lock, and an overrun notice (clarify 8, approach 10, implement 25, test 10 min; `phases.OVERRUN_MIN`); prompt rules added. No new Trigger: the overrun is acted on at the next turn (proactive reactions are ticket 09).
- Metrics `phase_ms` (all intervals summed). Report page: phase timeline bar + legend in Metrics (hidden on older Reports). Top bar: Phase buttons, current highlighted, disabled after the end.
- Tests: `tests/test_phases.py` (Live Session lock/backward/overrun; Report seam: time per phase, Correctness snapshot selection incl. no Wrap-up and Wrap-up revisited).

**Notes:** Not clicked through in a browser. Correctness uses the first move to Wrap-up (a later move back does not extend it).
