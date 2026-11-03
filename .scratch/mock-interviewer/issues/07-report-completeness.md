# 07: Report completeness

**What to build:** The Report gains the remaining deterministic metrics, top 3 strengths and top 3 improvements (each with a concrete drill), and an Ideal Walkthrough whose approach is visible but whose code stays hidden until I click Reveal. Large pastes are noted but never penalized, and the Report shows whether autocomplete was on (chosen on the setup screen only).

**Blocked by:** 05 (First Report end to end)

**Status:** done

- [x] Metrics: time to first code/Run/test, Runs and failures, error types, silence gaps over 60 s, talk ratio and words per minute while coding, Hints by level, large pastes
- [x] Pastes over 200 characters are logged as `paste` events and appear in metrics; the rubric never penalizes them
- [x] Autocomplete toggle exists on setup only, is stored in settings, and is labeled on the Report
- [x] Strengths and improvements (3 each), each improvement with a drill
- [x] Ideal Walkthrough: approach and complexity visible; code collapsed behind Reveal
- [x] Report seam tests cover the deterministic metrics

## Comments

**Built (ticket 07):**
- `metrics.py` (full): time to first code (first snapshot differing from the starter)/Run/test (`extract_executed_tests`), Runs and failures, `error_types` (last traceback exception class, `TimeoutError` for timeouts), `silence_gaps` over 60 s (no Candidate speech, edit, Run or paste), talk ratio, words per minute from first code to the end, `hints_by_level` (from `hint_given`), `large_pastes`, `muted_ms` (from `mic_muted`/`mic_unmuted`). Hints and muting read zero until those events exist.
- Pastes: client sends `ui_event {event: "paste", text}`; `LiveSession` logs a `paste` event (`length`, `text`) only above 200 characters (`LARGE_PASTE_CHARS`). Monaco `onDidPaste` wired in `CodeEditor`. The prompt tells the model never to penalize pastes.
- Autocomplete: setup checkbox -> `POST /api/sessions {autocomplete}` -> `settings.autocomplete` (fixed per Session); Report JSON `autocomplete`, labeled on the Report page next to the Overall Signal.
- `submit_report` gained `strengths` (3), `improvements` (3, each with `drill`) and `ideal_walkthrough {approach, complexity, code}`; validated (exactly 3, non-empty), assembled into the Report JSON. Report page: strengths/improvements, Metrics, Ideal walkthrough with the code in a collapsed `<details>` ("Reveal"), which is hidden client-side only (the code is in the Report JSON).
- Tests: `tests/test_report_completeness.py`. Harness: `submit_report` supplies the new fields; `reports.session(autocomplete=)`; `harness.start(autocomplete=)`.

**Notes for later tickets:**
- 08: time per phase is not computed yet (no `phase_changed` events exist); add it to `compute_metrics`.
- 10/11: `mic_muted`/`mic_unmuted` events are not logged by anything yet; `muted_ms` and `ui_event` handling for them are still to add.
- Not clicked through in a browser.
