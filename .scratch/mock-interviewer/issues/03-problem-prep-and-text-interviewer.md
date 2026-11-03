# 03: Problem prep and a text-chat Interviewer

**What to build:** When I click Start, the app prepares a hidden Problem Brief while showing "Interviewer is reading the problem…". I can add private notes and pick a Style (three presets or free text). The Interviewer then greets me and restates the problem. I can type to it at any time and always get a short, streamed, conversational reply. When I ask a clarifying question it answers consistently with my private notes and the Problem Brief; if neither covers it, it asks what I'd assume and treats my assumption as binding. Clarifications appear under the problem.

**Blocked by:** 01 (Skeleton: start a Session and type code)

**Status:** done

- [x] Problem prep produces a Problem Brief (approaches, insights, pitfalls, Edge-Case Categories, default clarification answers, follow-ups), stored hidden on the Session
- [x] Prep failure after one retry returns to setup with input intact and creates no Session
- [x] Private notes and the Problem Brief are never sent to the client
- [x] Style preset or free text is stored in settings and shapes only the persona section of the prompt
- [x] Interviewer greets and restates the problem; typed messages always get a streamed reply (`interviewer_delta` / `interviewer_done`)
- [x] Decision-call context is rebuilt from the event log each time; system prompt (persona, problem, Brief) is prompt-cached
- [x] `record_clarification` logs a `clarification` event with `by` interviewer/candidate and the UI appends it under the problem
- [x] Interviewer never gives the solution, writes code or proposes test inputs (system-prompt rules)
- [x] Live Session tests with a scripted fake model cover a typed exchange and a clarification with `by: candidate`

## Comments

**Built (ticket 03):**
- Model seam (`backend/agent/model.py`): `ModelClient.stream(ModelRequest)` shared by prep, the Interviewer and (later) the Report. `ModelRequest.system` is stable per Session and prompt-cached; `effort` is optional; `ModelError(code, message)` is how API failures reach the UI. `backend/agent/anthropic_client.py` (`AnthropicModelClient`, `anthropic>=2.4.0`) streams via `client.beta.messages.stream`, marks the system block with `cache_control`, enables server-side refusal fallback (`fallbacks: "default"`) on models that support it, maps SDK errors to `ModelError` codes (`rate_limited`, `api_key_invalid`, `model_unavailable`, ...), treats `refusal` as an error and drops tool calls on `max_tokens`. Logs token/cache usage per call.
- Problem prep (`backend/agent/prep.py`, prompt `prompts/prep.md`): Opus, effort high, the brief is submitted through a strict `submit_problem_brief` tool (approaches, key_insights, pitfalls, edge_case_categories {name, description}, clarifications {question, default_answer}, follow_ups). Validated, retried once, else `PrepFailed`. `SessionManager.create` is now async and runs prep before persisting anything; `POST /api/sessions` returns 502 on `PrepFailed`. The brief is stored in `sessions.problem_brief_json` (`SessionRecord.problem_brief`, excluded from `to_public_dict` like private notes).
- Style: `Style(preset | custom)` in `backend/agent/context.py` (presets `faang_standard`, `friendly_new_grad`, `pragmatic_startup`), stored as `settings.style`; it only fills the `<persona>` section of the system prompt.
- Interviewer (`backend/agent/interviewer.py`, `context.py`, prompt `prompts/interviewer.md`): system prompt = rules + persona + problem + starter + private notes + brief. Each decision call sends one user message rebuilt from the event log (elapsed, clarifications, transcript, numbered current code, last 3 runs, trigger). Sonnet, effort low, `max_tokens` 1024 (headroom for adaptive thinking). Tool: `record_clarification(question, answer, by)`; invalid tool inputs are logged and ignored.
- Session engine: takes `model`. `utterance` (channel `text`) is logged (`speaker: "user"`) and always answered; `client_connected()` (called by the WebSocket on connect) greets once per live Session (trigger `session_start`). Replies stream as `interviewer_delta`, then `interviewer_done` and an interviewer `utterance` event with `msg_id`; a reply failing mid-stream emits `interviewer_cancel` + `error`. If the model answers a typed message with only tool calls, one follow-up call (`typed_message_unanswered`) gets the spoken reply. Clarifications append a `clarification` event and emit `clarification` (with `seq`). One reply in flight; typed messages arriving meanwhile queue a single follow-up reply built from the log.
- Frontend: setup has private notes, Style select + free text, and an "Interviewer is reading the problem…" screen; on failure it returns to the form with input intact. Interview page: conversation pane (streamed replies, typed input, flushes code before sending), clarifications listed under the problem, initial transcript/clarifications from the event log.
- Harness: `await harness.start(..., private_notes, style, brief=DEFAULT_BRIEF)` auto-scripts the prep turn (pass `brief=None` to script prep yourself; script Interviewer turns *after* start). `await harness.connect(sid)` (greeting), `await harness.say(sid, text)` (typed message + wait for reply). `ScriptedModel` turns may contain exceptions to raise mid-stream and yield control between items.

**Notes for later tickets:**
- Ticket 09 owns real coalescing/cancellation and `stay_silent`; extend `Trigger` in `interviewer.py` and route new triggers through `LiveSession._request_reply` (currently the newest trigger wins when queued). Add tools to `interviewer.TOOLS` (keep the list deterministic: it is part of the cached prefix).
- Ticket 04: start the timer at the greeting (`client_connected` → first `interviewer_delta`). Ticket 05: reuse `ModelClient`; Opus 5.5 rejects forced `tool_choice`, so use `auto` + a prompt instruction + `strict: true` as prep does.
- Ticket 13: greeting is guarded by an in-memory flag; a rehydrated Session should skip it if the log already has an interviewer utterance. The frontend loads utterances/clarifications from `GET /api/sessions/{id}` before opening the socket.
- Ticket 16: the "never solve / never write code / never propose tests" rules live only in `prompts/interviewer.md`; brief secrecy is also prompt-only.
- Review (two-axis): fixed partial streams never closed, tool-only replies to typed messages, duplicated utterance payloads, untyped trigger. Left: refusal fallback + effort settings in the client are beyond the ticket's letter (kept for latency and Opus/Sonnet 5.5 refusal handling); `FALLBACK_MODELS` is a hard-coded list; prompt text uses "interview" as a noun (model-facing only).
- Not clicked through in a real browser or against the real API; the adapter was smoke-tested against a mocked HTTP transport (request shape, cache_control, fallback beta, stream parsing).
