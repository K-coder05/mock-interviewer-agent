# 09: Proactive Interviewer: Triggers, guardrails and Nudges

**What to build:** The Interviewer speaks up on its own when it should. If I go quiet it Nudges me ("What are you thinking right now?") after a Phase-dependent silence; it prompts at time checkpoints. It is never chatty: unprompted speech respects a cooldown and a cap, while replies to my direct questions are never held back. Every Trigger and its outcome is logged so the behavior can be tuned.

**Blocked by:** 04 (Timer and ending a Session), 08 (Phases)

**Status:** done

- [x] Trigger engine consumes the per-Session event queue and logs `trigger` events with reason and outcome (spoke/silent/suppressed)
- [x] Silence trigger uses per-Phase thresholds from config (45/45/90/60 s)
- [x] Time checkpoints: 50% elapsed with no code, 10 min left, 5 min left
- [x] Guardrails apply to every unprompted utterance: 45 s cooldown, max 3 per 5 min; typed messages and direct questions exempt
- [x] `stay_silent` produces no speech and logs its reason
- [x] One decision call in flight per Session; events arriving meanwhile coalesce into the next call
- [x] Live Session test: 90 s of silence while implementing produces exactly one Nudge
- [x] Live Session tests cover cooldown, cap and coalescing with the fake clock

## Comments

**Built (ticket 09):**
- `backend/agent/triggers.py`: `Trigger(reason, detail)` (replaces the old `Trigger` literal in `interviewer.py`), `TriggerConfig` (from `config.yaml` `interview.proactive_cooldown_s`, `max_proactive_per_5min`, `silence_nudge_s`; stored per Session in `settings.proactive`), `coalesce()` and `TriggerEngine`. The engine observes every event as `LiveSession._append` writes it (the per-Session queue, consumed in order) and keeps all its state from events, so replaying a stored log rebuilds it (ticket 13). `due(now_ms)` returns the time-based Triggers (called from `LiveSession.tick`, every second in production); `suppression(now_ms)` applies the guardrails.
- Triggers: `silence` (per-Phase threshold, none in Wrap-up; measured from the latest of Candidate activity — speech, edit, Run, paste, a user Phase click — the Interviewer's last words and the timer start; one per silence, a new silence needs new Candidate activity), `time` with detail `half_time_no_code` / `10_min_left` / `5_min_left` (each once; checkpoints are skipped if the Session is shorter than them; if several time-left ones are crossed at once only the latest fires), `phase_overrun` (detail = Phase; once per stay in a Phase, using `phases.OVERRUN_MIN`; closes the ticket 08 gap). No proactive Triggers before the timer starts or after time is up.
- Exempt (never held back): `session_start`, `typed_message` (+ its `typed_message_unanswered` follow-up), `time_up`, `session_end`. Everything else is proactive: 45 s cooldown after the Interviewer's last utterance (any utterance), max 3 proactive utterances that actually spoke in a rolling 5 min.
- Reply queue: `LiveSession._pending` collects Triggers while a call is in flight; the next call coalesces them: the lead is chosen by `triggers.PRIORITY` (all exempt reasons first, so a batch with a typed message or time-up is exempt and a queued `time_up` is never lost), the others are listed in the turn message ("Also since your last turn: ..."). Guardrails are checked when the call is about to start, so a Nudge queued behind a reply meets the cooldown.
- `trigger` event per decision call (or suppressed attempt): `reason`, `detail?`, `proactive`, `coalesced?` [{reason, detail?}], `outcome` spoke/silent/suppressed, plus `suppressed_by` (cooldown/cap), `silent_reason` (from `stay_silent`) or `error` (failed call, logged as silent). A Nudge = `proactive` and `spoke`. `trigger` events are excluded from the Report timeline.
- Interviewer: `stay_silent(reason)` tool (appended to `TOOLS`); `Decision.silent_reason` (speech alongside it wins). Prompt section "Speaking up on your own". The turn's `<trigger>` now carries a description (`silence (implement): ...`).
- Harness: `ScriptedModel` turns may contain an `asyncio.Event` (the stream waits there: holds a call in flight); `harness.elapse(..., wait=False)`; `harness.wait_for_interviewer(sid)`. Tests: `tests/test_triggers.py`; `test_timer.py` scripts the proactive turns now on its path.

**Design decisions / deferred:**
- A suppressed Trigger is dropped, not retried later (keeps "one Nudge per silence"; the Interviewer still sees time left on its next turn).
- A proactive call is not cancelled by new input (ticket 12: cancel when the Candidate starts speaking). Never-while-speaking guard and muted silence (code activity only, `muted_silence_multiplier`) are ticket 11: add a `speaking`/mute state to `TriggerEngine.observe`/`suppression` and an `utterance` (voice) Trigger whose exemption for direct questions needs deciding there (`Trigger.proactive` is by reason today).
- Ticket 10: add `run` (after `run_reaction_delay_s`, already in config), `stuck`, `coding_pause` reasons to `TriggerReason`, `PRIORITY` and `_DESCRIPTIONS`, and detect them in `TriggerEngine.due`/`observe`. `give_hint` counts as unprompted speech when it comes from a proactive Trigger — the guardrail check already happens before the call.
- Not clicked through in a browser or run against the real API.
