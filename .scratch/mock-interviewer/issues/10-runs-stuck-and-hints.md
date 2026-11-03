# 10: Reacting to Runs and being stuck, plus Hints

**What to build:** The Interviewer reacts after I run code — asking about a failure or what I expected — and notices when I'm stuck, Probing first and then offering laddered Hints. After a big burst of code and a pause it asks me to walk through it. If I ask for a hint I get the next level immediately; "just tell me" gets at most a concrete next step, never code. It records private observations for the Report.

**Blocked by:** 02 (Run your code), 09 (Proactive Interviewer: Triggers, guardrails and Nudges)

**Status:** done

- [x] Decision context includes the last 3 Runs, current code with line numbers and the last diff
- [x] Run-finished trigger fires after the configured delay, merged with speech in the meantime
- [x] Stuck trigger: 3 failing Runs in a row or the same exception twice
- [x] Coding-pause trigger: ≥25 lines changed then 30 s idle
- [x] `give_hint(level, text)` logs `hint_given` with level 1–4; explicit requests get one level above the last Hint
- [x] Probes are never logged as Hints and don't affect coachability
- [x] `note` logs private `interviewer_note` events, never shown live, included in Report input
- [x] Live Session tests cover each trigger and the explicit-hint-request rule

## Comments

**Built (ticket 10):**
- `backend/agent/triggers.py`: new reasons in the one `REASONS` table (all proactive, priority after `time`): `stuck`, `run`, `coding_pause` (before `silence`). Details `run` passed/failed, `stuck` failing_runs/repeated_exception (descriptions in `DETAILS`). `TriggerConfig` gained `run_reaction_delay_s` (3), `stuck_failing_runs` (3), `coding_pause_lines` (25), `coding_pause_idle_s` (30), all in `config.yaml` `interview` and stored in `settings.proactive`.
  - Every Run gets one reaction, `run_reaction_delay_s` after the `run` event: `stuck` if that Run makes 3 failing Runs in a row (non-zero exit or timeout) or repeats an exception (traceback last line; an `...Error:` line printed without a traceback such as a SyntaxError; TimeoutError) already seen since the last passing Run, else `run`. A newer Run replaces a waiting reaction. A passing Run resets the streak.
  - Merged with speech: a typed message during the delay takes the waiting reaction (`TriggerEngine.merge_waiting`) into the same reply (lead `typed_message`, `coalesced: [run]`).
  - Coding pause: a burst is the edits between two idle gaps; lines changed (difflib, a modified line counts once) from the code at the start of the burst >= 25, then 30 s with no edit or Run. Every idle gap ends a burst, big enough or not.
  - Held back by the guardrails: `stuck` is retried (until a newer Run); `run` and `coding_pause` are dropped like a silence. Which reasons are retried is the `retried` flag in `REASONS`.
- Interviewer: `give_hint(level, text, requested)` and `note(observation)` tools (appended to `TOOLS`). The Hint text is spoken (streamed as part of the reply). Level enforced in code from the log (`context.next_hint_level`): `requested` gets exactly one above the last Hint (L1 first, capped at L4); an unrequested Hint is clamped to at most the next level (never skips rungs). Session logs `hint_given {level, text, requested}` and `interviewer_note {observation}` (no server message: never shown live).
- Turn message: `<hints_given>` (with "The next Hint is L<n>."), `<your_notes>`, `<last_diff>` (the Candidate's edits since the Interviewer last spoke, clipped); code with line numbers and last 3 runs were already there. Prompt sections on Run/stuck/pause reactions, the Hint ladder, explicit requests and "just tell me" (L4 at most, never code), Probes vs Hints, notes.
- Report input: timeline entries `Hint L<n> (the candidate asked for it): ...` and `Interviewer private note: ...`; Report prompt: Coachability is judged from Hint entries only, Probes never count. `hints_by_level` already read `hint_given`.
- Tests: `tests/test_runs_stuck_hints.py` (Live Session: run delay, merge with speech, both stuck rules, stuck retry, coding pause, context, hints, explicit-request rule incl. L4 cap, rung clamp, probes, notes; Report seam: hints/notes in the Report input).

**Notes for later tickets:**
- 11 (voice): "merged with speech" only covers typed messages today; a final spoken utterance during the delay should call `merge_waiting()` the same way. Coding-pause idle ignores speech (the Candidate may already be narrating; the model can `stay_silent`).
- 14 (replay): `hint_given` events are the timeline markers for Hints; `interviewer_note` must stay hidden from the replay transcript unless deliberately shown after the Session.
- 16 (prompt regression): test against the real API that "just tell me the answer" yields at most a level-4 step with no code, that an explicit request uses `give_hint` with `requested: true`, that first stuck turns Probe before hinting, and that Probes don't go through `give_hint`. The level is enforced in code, but whether the model calls `give_hint` at all (instead of hinting in plain text, which would not be logged) is only prompt-enforced.
- Not clicked through in a browser or run against the real API.
- Review (two-axis code-review): fixed the retried-reasons list living outside `REASONS` (now a `retried` flag), SyntaxErrors (no traceback header) never counting as a repeated exception, spread-out small edits adding up to a false coding pause (bursts now end at every idle gap), `<last_diff>` being only the last autosave snapshot's diff, plus small cleanups (`_RunReaction`, one stuck filter). Left: the failing streak also counts Runs before the timer starts / after time is up; the same exception across a passing Run isn't stuck (streak resets on a pass, by design); `requested` and "Probe before hinting" are trusted to the model (ticket 16); `requested` is an addition to the sheet's `hint_given {level, text}` schema; Hint level parsing exists in both `context._hint_level` (events) and `interviewer._hint` (model input); the coding-pause and silence bookkeeping depend on when `due()` runs, so replaying a log rebuilds them only approximately (ticket 13).
