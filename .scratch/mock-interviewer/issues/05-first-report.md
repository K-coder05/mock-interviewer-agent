# 05: First Report end to end

**What to build:** When a Session ends, a Report is generated and shown within about a minute: a short summary, the Overall Signal with a one-line rationale, and a rubric table where each dimension is scored 1–4 with timestamped evidence. If generation fails I see a Retry button.

**Blocked by:** 04 (Timer and ending a Session)

**Status:** done

- [x] Ending a Session starts Report generation; `GET report` returns a generating status until ready
- [x] The model is called with a forced structured `submit_report`; output is validated and retried once, else status `report_failed`
- [x] Retry (via regenerate) rebuilds the Report from stored events
- [x] Rubric: all nine dimensions scored 1–4 with 1–3 evidence items; every evidence `t_ms` exists in the event log
- [x] Overall Signal computed in code from the weighted average (Testing 2×) with the agreed thresholds (Strong No, No, Lean No, Lean Hire, Hire, Strong Hire) and the Testing/Correctness cap; the model writes only the rationale
- [x] Correctness is labeled as assessed by reading, not executed
- [x] Report stores model and token usage
- [x] Report seam harness exists; tests cover signal thresholds and cap, validation retry and `report_failed`

## Comments

**Built (ticket 05):**
- `backend/feedback/`: `rubric.py` (the nine `DIMENSIONS` with keys, labels, "what a 4 looks like", Testing weight 2; `overall_signal(scores)` computes the weighted average exactly with `Fraction`, applies the thresholds and the Testing/Correctness cap at No, and reports `capped`), `prompt.py` (Report system prompt + rubric; kept as a Python string, not a `.md` under `agent/prompts/`), `report.py` (strict `submit_report` tool: `summary`, `signal_rationale`, `rubric.{dimension}.{score 1-4, evidence[{t_ms, quote_or_code, comment}]}`; Pydantic validation incl. 1-3 evidence items and every `t_ms` present in the event log; one retry whose message lists the problems found; `ReportFailed` after that; Opus 5.5, effort high, `tool_choice` auto as in prep), `metrics.py` (minimal: duration, runs, failed runs, word counts), `generator.py` (`ReportGenerator`: `start`, `generating`, `wait`, `view`, `close`; runs in the background and serves first generation, Retry and regeneration alike, always from the stored events, with the configured `models.report`).
- Correctness: judged on the last snapshot before a `phase_changed` to `wrap_up` (else the final snapshot), labeled "Assessed by reading the code, not by executing it." on the rubric row and in `report.correctness.executed: false`.
- Report JSON: `summary`, `overall_signal {label, weighted_average, capped, rationale}`, `rubric[] {dimension, label, weight, score, evidence, note}`, `correctness`. The `reports` row stores the serving model (`Usage.model`, which can differ under refusal fallback), metrics and usage summed over attempts (`input/output/cache_read/cache_creation tokens, attempts`).
- Model seam: new `Usage` event (yielded after text, before tool calls) from `AnthropicModelClient`; the Interviewer ignores it. `ScriptedModel` adds a default `Usage` to every completed turn unless the turn scripts one.
- Session engine: `LiveSession.end` calls `on_ended` (`SessionManager` passes `ReportGenerator.start`) after the status becomes `ended` and before `session_ended` is sent. `Store` gained `set_status`, `save_report` (replaces, sets `report_ready`), `get_report`.
- API: `GET /api/sessions/{id}/report` -> `{status: "generating"}` while in flight, the Report (`status: report_ready`, `report`, `model`, `usage`, `metrics`, `created_at`) once ready, else `{status: <session status>}`. `POST /api/sessions/{id}/report?regenerate=true` starts generation (409 while live).
- Frontend: `#/sessions/{id}/report` Report page (polls every 2 s while generating; summary, Overall Signal + rationale, rubric table with mm:ss evidence, Correctness note, model and tokens; Retry on `report_failed`, Generate report for `ended`/`abandoned` without a report). After `session_ended` the interview page swaps End Interview for a View report link (no auto-redirect, so the closing reply stays readable).
- Report seam harness (`tests/report_harness.py`, fixture `reports`): `reports.session()` / `ended_session()` return an `EventLog` (`say`, `code`, `run`, `event`, `end`, times in seconds); `submit_report(scores, evidence_t_ms=..., **overrides)` builds a valid tool call; `await reports.generate(sid)` returns the `GET report` view. The Live Session harness now also has `harness.reports` and `await harness.finish_report(sid)`; its fixture is async (`aclose`).

**Notes for later tickets:**
- 06: add Candidate Tests to `build_report_message` / `_assemble` and to the tool schema (traced-test tagging); `EventLog.code/run` cover executed-test fixtures.
- 07: extend `metrics.py`; strengths/improvements/Ideal Walkthrough are new `submit_report` fields (update `Submission` and `SUBMIT_REPORT_TOOL` together; both are strict).
- 08: Correctness selection keys on `phase_changed.payload.to == "wrap_up"` (`report.WRAP_UP`); use that Phase id or update the constant.
- 13: an Abandoned Session can use `ReportGenerator.start` as is (it only refuses `live`). After a backend restart mid-generation a Session stays `ended`; the Report page shows Generate report.
- 14: evidence `t_ms` is ready for replay jumps; the Report page renders it as plain mm:ss for now.
- 15: regeneration already replaces the stored Report on success; a failed regeneration keeps the old Report (status stays `report_ready`).
- Ending a Session in Live Session tests without scripting `submit_report` makes Report generation fail quietly in the background (logged); script a turn when a test cares.
- Review (code-review, medium): fixed a failed regeneration hiding the stored Report, unguarded `save_report` errors, Report polling stopping after one failed fetch, finished tasks kept forever, the instant redirect that hid the closing reply. Left: shutdown cancels in-flight generations (Session stays `ended`, Generate report recovers); Report states share `sessions.status` per the spec schema; `?regenerate=true` kept per the spec contract; clarifications appear both as a summary and in the timeline; candidate text is not escaped in the prompt (single-user tool, only self-inflation possible).
- Not clicked through in a browser or run against the real API; the endpoints were smoke-tested through an ASGI transport with the scripted model.
