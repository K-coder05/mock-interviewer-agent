# Mock Interviewer Agent — Spec Sheet

Nov 2, 2026 · @Khiem

## Overview

A single-user, locally hosted web app for live mock coding interviews. You paste any problem, solve it in Python 3 in a browser IDE, and talk out loud to an interviewer powered by Claude. The app records everything you say, type and run. At the end it produces a feedback report with evidence and timestamps.

Domain terms (Session, Candidate Test, Probe, Hint, Nudge, Overall Signal, …) are defined in `GLOSSARY.md`.

The core principle: **it grades your process, not a hidden test suite.** It judges how you clarify, choose an approach, communicate, write code, and above all, write and run your own test cases to check your answer.

**Goals**

- Bring your own problem: paste any prompt, with optional private notes for the interviewer.
- Live Python 3 editor with a Run button for your own ad-hoc tests.
- A realistic, proactive interviewer you can speak or type to at any time.
- A full session timeline (speech, code snapshots, runs, interviewer notes) that drives an evidence-based feedback report.
- Runs on your laptop: `git clone` → add `ANTHROPIC_API_KEY` → one command to start.

**Non-goals (v1)**

- No LLM-generated or hidden test cases, and no pass/fail scoring. Testing is your job, and the report grades how well you did it.
- No languages other than Python 3.
- No accounts, multi-user support, cloud deploy or hardened sandbox. It's a trusted single user on localhost.
- No problem bank. You supply problems. A saved list of problems you've used is a v2 nice-to-have.

## Key design decisions

| Area | Decision | Why |
| --- | --- | --- |
| Form factor | Local web app on `localhost` | A browser IDE feels closest to CoderPad/HackerRank |
| Frontend | React + TypeScript + Vite, Monaco editor | Monaco is the VS Code editor, with Python highlighting built in |
| Backend | Python 3.11+, FastAPI, one WebSocket per session | Async streaming; same language as the code runner |
| LLM | Anthropic Messages API via the `anthropic` Python SDK | Live turns use `claude-sonnet-5-5` for low latency; the final report uses `claude-opus-5-5` for depth. Both are configurable. |
| Talking | Voice + text: always-on speech-to-text, spoken replies, typed chat fallback | Think-aloud is the main signal for feedback, and real interviews are spoken |
| Interviewer | Proactive and realistic: watches code, runs and silence, then decides to speak or stay quiet | Real interviewers nudge, probe complexity and ask you to test |
| Execution | Run button executes your buffer in a local subprocess with limits; output goes to you and the interviewer | You validate with your own inputs, as real interviews allow |
| Tests | None generated. The interviewer never supplies test cases; it asks you to. | The skill being practiced is writing your own tests |
| Storage | SQLite file and an append-only event log | Zero setup, easy to replay and export |
| Scoring | The LLM scores rubric dimensions with evidence; code derives the Overall Signal from the weighted scores | Signal stays consistent and recomputable across regenerations |
| Correctness | Judged by the LLM reading the final code, labeled "assessed by reading, not executed" | Executing hidden cases would contradict the no-hidden-tests principle |

## User flow

A session goes setup → live interview → feedback, and every session is saved for replay.

1. **Setup screen**
   - Paste the problem statement (Markdown). Optional fields: function signature or starter code, and private interviewer notes (e.g. "the intended solution is O(n) with a hashmap"). The notes are never shown to you during the session.
   - Starter code, if given, is preloaded into the editor and recorded as the Session's first code snapshot at t=0 (so it isn't counted as code you wrote).
   - Choose a duration (default 45 min) and a style: one of three presets ("FAANG standard", "Friendly new-grad", "Pragmatic startup") or a free-text description. Style changes only the interviewer persona, never rubric weights, so scores stay comparable.
   - Choose whether editor autocomplete is on (default off). It's fixed for the Session, stored in the settings and labeled on the report.
   - The screen recommends headphones (for the echo guard) and notes that only the Python standard library is available.
   - Click **Start**. The backend runs a one-time *problem prep* call (see Interviewer agent) while an "Interviewer is reading the problem…" screen is shown (it can take 15–40 s). If prep fails after one retry, you return to the setup screen with your input intact and no Session is created. The timer starts when the interviewer's greeting begins; it opens with a greeting and a restatement of the problem.
2. **Live interview.** The interviewer moves through phases and the UI shows the current phase. A phase is a label, not a gate: either side can set any phase, including going back (e.g. from Test to Approach after a test exposes a wrong algorithm). The last change wins, but after you set the phase the agent can't call `set_phase` for 2 minutes.
   1. Clarify: you ask questions; the interviewer answers and records each clarification.
   2. Approach: you explain the plan; the interviewer probes trade-offs and complexity.
   3. Implement: you code while thinking aloud.
   4. Test and verify: you choose inputs, trace them and run them.
   5. Wrap-up: final complexity, follow-ups, and your questions. Follow-ups are discussed, not graded as a second problem; you may write code for one, but Correctness is judged on the last snapshot before Wrap-up began.
3. **End.** Click **End Interview**, or the timer runs out. There's a 5-minute warning; at 0:00 the interviewer says time is up and asks for any last thought, and the Session ends automatically 60 s later (or sooner if you click End). There's no overtime. The interviewer closes politely and gives no verdict yet.
4. **Feedback report.** Generated in about 20–60 s. It shows scores, evidence, strengths, improvements and a clickable timeline. If generation fails, the Session is marked `report_failed` and the report page shows a **Retry** button.
5. **History.** A list of past sessions, each with its report and full replay (code at any moment, plus the transcript). Each can be deleted (with confirmation), which hard-deletes its events and report.

A refreshed tab reconnects and resumes the live Session; the timer keeps running on the wall clock. On backend startup, any `live` Session with no events in the last 10 minutes is marked `abandoned`. Abandoned Sessions don't generate a report automatically; they show a **Generate report** button.

## Architecture

Two local processes, a React frontend and a FastAPI backend, connect over one WebSocket per session. Everything that happens is appended to the session's event log. The trigger engine, the interviewer and the report generator all read from that log.

&#91;embedded content: System architecture · browser, backend, Anthropic API\]

The interviewer writes its own replies and tool calls (hints, notes, clarifications, phase changes) back into the same log. That way replay and the report see exactly what happened live.

## Frontend

The interview screen has three panes and a top bar, and everything is visible at once. No tab-switching mid-interview.

| Region | Contents | Behavior |
| --- | --- | --- |
| Top bar | Timer (counts down), phase indicator, mic status, mute-interviewer toggle, End Interview | The phase indicator follows the agent's `phase` but you can click it to set any phase (forward or back); the timer turns red at 5 min left |
| Left pane (\~30%) | Problem statement (rendered Markdown), list of clarifications | Clarifications auto-append whenever the interviewer answers one |
| Center pane (\~45%) | Monaco editor (Python 3), with a console below it | Run button (`Cmd/Ctrl+Enter`), optional stdin box, stdout/stderr/exit code/runtime shown in the console |
| Right pane (\~25%) | Conversation transcript and a text input | Shows your speech (interim results in gray, final in black) and interviewer replies (streamed); typed messages always get a reply |

**Editor requirements**

- Monaco with `language: "python"`, a 4-space tab, and no autocomplete or IntelliSense by default, to keep it interview-realistic. It can be turned on only on the setup screen, not mid-Session.
- Paste detection: a paste over 200 characters is logged as an event, and the report notes it. Pastes are never penalized in the rubric.
- Code sync: send `code_update` to the backend after 1.5 s of idle typing or every 10 s while typing, whichever comes first. Also flush a `code_update` immediately before sending each final utterance and each `run`, so any reply to you sees your current buffer. Send the full buffer each time; the backend diffs.

**Feedback and history screens**

- Report view: summary at the top, then the rubric table, strengths and improvements, your tests, and the timeline.
- Replay view: a timeline scrubber; at any timestamp it shows the code snapshot (read-only Monaco) beside the transcript scrolled to that moment. Timeline markers for runs, hints, phase changes and long silences.

State management: React context or Zustand. No Redux needed.

## Voice and think-aloud capture

Everything you say goes on the record, as in a real interview. The interviewer hears it all and decides on each utterance whether to respond. There is no separate "talk to interviewer" button. That single design choice is what lets the app capture your thought process.

**Speech-to-text (STT)**

- Default: the browser Web Speech API (`SpeechRecognition`, `continuous = true`, `interimResults = true`). It's free and needs no setup, but it works fully only in Chrome/Edge, and audio is processed by the browser vendor's servers.
- Optional (v2): local Whisper (`faster-whisper`) behind the same interface. The frontend streams audio chunks over the WebSocket and the backend returns transcripts. Use it for privacy or for Firefox/Safari.
- STT sits behind a `SpeechProvider` interface: `start()`, `stop()`, `onInterim(text)`, `onFinal(text, startMs, endMs)`.
- Utterance boundary: a final result, or 1.2 s of silence. Each final utterance becomes an `utterance` event with `channel: "voice"`.
- Auto-restart: Web Speech stops after long silences, so restart on `onend` while the session is active.

**Mic modes:** *Always listening* is the only v1 mode. Push-to-talk is deferred to v2 (Space can't work because the editor is focused while coding; a modifier Monaco doesn't use, such as holding Right-Alt, is the likely binding). Mute stops capture entirely and logs a `mic_muted` event so silence isn't miscounted: while muted, the silence trigger considers only code activity, with its threshold doubled, and if you're muted for more than 2 min in total the report notes it under Communication, since your think-aloud wasn't captured.

**Text-to-speech (TTS)**

- Default: the browser `speechSynthesis` API, with voice and rate settable in Settings. Speak sentence by sentence as tokens stream in, to cut perceived latency.
- Barge-in: if your speech is detected while TTS is playing, stop TTS immediately and log `interviewer_interrupted`.
- Echo guard: STT keeps running while TTS speaks; any transcript that closely matches the interviewer's current text is discarded, so it can't hear itself, and anything else counts as barge-in. Pausing STT during TTS is a fallback setting for speaker users only, since it disables barge-in. Headphones are recommended.
- Mute-interviewer toggle: replies show as text only.

**Typed channel:** you can type to the interviewer at any time. A typed message is logged as `utterance` with `channel: "text"` and always gets a reply.

**Scratchpad (v2):** a small notes tab under the problem for jotting down examples, saved as `scratchpad_update` events. Deferred: spoken examples already cover traced tests.

## Code execution and self-testing

The Run button executes exactly what's in your editor. Nothing is injected, wrapped or tested behind your back. You write the calls, asserts and prints that prove your solution works.

**Runner (`backend/runner.py`)**

- Before running, force a `code_snapshot` of the exact buffer (deduped as usual); the `run` event references that snapshot's `seq`.
- Write the buffer to a fresh temp dir as `main.py` and run `python3 -I -u main.py` via `asyncio.create_subprocess_exec`. `-I` is isolated mode: no user site-packages and no env vars. The interpreter is the system `python3` (configurable), never the backend's virtualenv, so only the standard library is available. The startup check confirms it's 3.11+.
- Limits (configurable): 10 s wall-clock timeout (kill the process group), 512 MB memory (`resource.setrlimit(RLIMIT_AS)` in `preexec_fn`; Linux enforces it, macOS largely ignores it, so rely on the timeout there), 64 KB output cap per stream (truncated with a marker), and the temp dir as the working directory.
- Optional stdin from the console's stdin box.
- Returns `{stdout, stderr, exit_code, duration_ms, timed_out, truncated}`.
- One run at a time per session. A second click while running cancels and restarts.
- Security stance: this is guarding against accidental infinite loops and memory blowups, not malicious code. You are the only user. Running inside a Docker container is a v2 option.

**What the interviewer sees:** every `run` event, including the code hash, the output and any error, goes into the agent's context and can trigger a reaction (see triggers).

**Testing behavior (the core skill being practiced)**

- The interviewer never proposes concrete test inputs. If you ask "what should I test?", it turns it back to you: "What cases worry you about this code?"
- It can prompt you to test ("How would you convince me this works?") once you say you're done or move to submit without having run anything.
- A *Candidate Test* is one concrete input you chose in order to check behavior: *executed* (it ran as part of a Run) or *traced* (spoken and walked through by hand). A Run isn't a test in itself; it may contain zero or many. A test is *verified* if you stated its expected result: an assert always counts; a printed call counts only if you said or wrote (in a comment) the expected value within about 30 s. Unverified tests are listed separately as "ran but not verified".
- During problem prep, the LLM privately lists the edge-case *categories* relevant to the problem (empty input, single element, duplicates, negatives, overflow-sized input, and so on). This list is never shown during the session or used to run anything. It's used only at report time to grade how complete your own testing was.
- A test extractor (in `feedback/tests.py`) finds the tests you wrote: `assert` statements, calls in `if __name__ == "__main__":`, calls followed by `print`, stdin inputs, and examples you spoke aloud ("if the input is \[1, 2, 3\]..."). It uses Python `ast` for the code, and the LLM tags spoken examples at report time.

## Session recorder

Every session is an append-only, timestamped event log, and it is the single source of truth. The live agent, the feedback report and replay all read from it. The backend owns the timestamps: `t_ms` is milliseconds since session start, taken from the server's monotonic clock.

**Event envelope**

```json
{"id": "evt_01J…", "session_id": "ses_01J…", "seq": 142, "t_ms": 734210, "type": "utterance", "payload": { }}
```

| Type | Payload | Emitted by |
| --- | --- | --- |
| `session_started` | problem, settings, model ids | backend |
| `utterance` | `speaker` (user/interviewer), `channel` (voice/text), `text`, `start_ms`, `end_ms` | frontend (user), agent (interviewer) |
| `code_snapshot` | `code`, `diff_from_prev` (unified), `chars_added`, `chars_removed` | backend on each `code_update` that differs |
| `paste` | `length`, `text` | frontend |
| `run` | `snapshot_seq`, `stdin`, `stdout`, `stderr`, `exit_code`, `duration_ms`, `timed_out` | runner |
| `phase_changed` | `from`, `to`, `by` (agent/user) | agent or UI |
| `clarification` | `question`, `answer`, `by` (interviewer/candidate: who supplied the binding answer) | agent tool call |
| `hint_given` | `level` (1–4), `text` | agent tool call |
| `interviewer_note` | private observation (e.g. "didn't consider empty input") | agent tool call; never shown live |
| `trigger` | `reason` (silence, stuck, run, coding_pause, time, …), `outcome` (spoke/silent/suppressed) | trigger engine; a *Nudge* is a trigger whose outcome is `spoke` |
| `mic_muted` / `mic_unmuted`, `interviewer_interrupted` | — | frontend |
| `session_ended` | `reason` (user/timeout), final code | backend |

**Rules**

- Starter code (if any) is the first `code_snapshot`, at `t_ms` 0.
- Every `run` is preceded by a forced snapshot of the code that ran.
- Store a full `code` snapshot on every change, so replay is trivial. At \~45 min and \~300 snapshots of a few KB each, size doesn't matter.
- Code snapshots are deduped: there's no event if the buffer is unchanged.
- Events are written to SQLite and pushed onto an in-memory per-session queue that the trigger engine consumes.
- Export: `GET /sessions/{id}/export` returns JSONL of all events plus the report.

## Interviewer agent

The interviewer is an event-driven loop. A trigger engine watches the event log. When something worth reacting to happens, it makes one *decision call* to Claude, which either speaks or stays silent, and can log notes, hints, clarifications and phase changes as tool calls.

**1. Problem prep (once, at session start)**

One call to `claude-opus-5-5` turns your problem and private notes into a hidden `problem_brief` (JSON): candidate approaches (brute force → optimal) with time/space complexity, key insights, common pitfalls, edge-case categories, likely clarifying questions with default answers (so answers stay consistent), and 2–3 follow-up questions. It is never shown to you live and goes into the cached system prompt.

**2. Triggers**

| Trigger | Condition (defaults, configurable) | Typical reaction |
| --- | --- | --- |
| Typed message | Any | Always replies |
| Spoken utterance | Final utterance received | Replies if you asked something or finished a thought; stays silent during mid-coding narration |
| Run finished | 3 s after a `run` event, merged with anything you say meanwhile | Asks about a failure or a surprising output, or asks what you expected |
| Silence | No speech and no code change for 45 s (Clarify/Approach), 90 s (Implement) or 60 s (Test). While muted: code activity only, threshold doubled | Nudge: "What are you thinking right now?" |
| Stuck | 3 failing runs in a row, or the same exception twice | Probes, then offers a hint from the ladder if you're still stuck |
| Coding pause | 25 or more lines changed, then 30 s idle | "Can you walk me through this part?" |
| Time checkpoint | 50% elapsed with no code yet; 10 min left; 5 min left | Time management prompt or wrap-up |
| Phase / done | You say you're done, or the agent detects the phase has ended | Moves to testing, complexity or follow-ups |

**Guardrails on proactive speech:** never while you're speaking (any interim transcript in the last 1.5 s); a 45 s cooldown after the interviewer last spoke; at most 3 unprompted utterances per 5 min. The guardrails apply to every unprompted utterance, whether Probe, Nudge or Hint. Only replies to typed messages and direct questions are exempt.

**3. Decision call**

- Model `claude-sonnet-5-5`, `max_tokens` about 400, streaming. Target: first token in under 1.5 s and first audio in under 2.5 s.
- The context is rebuilt fresh from the event log on every call. There is no running message history, so no tool-result bookkeeping. Structure:
  1. System prompt: persona and rules, plus the problem and `problem_brief`, marked with `cache_control` (prompt caching).
  2. A single user message holding: elapsed/remaining time, current phase, hints given so far, clarifications, the full transcript (a 45-min session is about 10k tokens, so no summarization is needed in v1), current code with line numbers, the last diff, the last 3 runs, and the trigger reason.
- Output: any text Claude writes is spoken (streamed to the UI and TTS sentence by sentence). Tool calls are side effects, applied when the stream ends:
  - `stay_silent(reason)` with no text means nothing is spoken; the reason is logged.
  - `record_clarification(question, answer, by)`, where `by` is `candidate` when the answer is your own stated assumption
  - `give_hint(level, text)`, where `text` is also what's spoken
  - `set_phase(phase)`: ignored for 2 min after you set the phase yourself
  - `note(observation)`: private evidence for the report, such as "jumped into coding without stating complexity"
- Concurrency: one call in flight per session. Events that arrive meanwhile are coalesced into the next call. A proactive call is cancelled if you start speaking; a reply to your question is not.

**4. Behavior rules (system prompt essentials)**

- Act as a real interviewer, not a tutor. Keep replies to 1–3 spoken sentences, conversational, with no Markdown or code blocks, because they're read aloud.
- Never give the solution or write code. Never propose test inputs. Ask the candidate for them.
- Answer clarifying questions from the private notes or `problem_brief` defaults, and stay consistent once you've answered. If neither implies an answer, don't invent one: ask "What would you assume?" and record the candidate's stated assumption as the binding clarification (`by: candidate`). Stating assumptions is a positive signal in the report.
- Hint ladder; climb only after you've visibly struggled: L1 a probing question → L2 point at the relevant area → L3 name the technique → L4 a concrete next step. Every hint is logged. An explicit request ("can I get a hint?") is honored immediately at one level above the last hint given (starting at L1); "just tell me the answer" gets at most L4, never code.
- Probe the way real interviewers do: complexity, trade-offs, "what happens if…", and asking you to trace a test by hand. A Probe is an assessment question, not help: it's never logged as a hint and never counts against coachability.
- Follow-ups in Wrap-up are discussion: a variant, a scale question or a trade-off, not a second graded problem.
- The Session's style shapes only the persona section of the prompt.
- Don't praise or judge mid-session beyond a neutral acknowledgment. Evaluation happens in the report.
- Bring a phase to a close if you're over time on it, e.g. clarifying for more than 8 min.

## Feedback report

The report combines **deterministic metrics computed in code** with **an LLM evaluation grounded in timestamped evidence**. Every score must cite moments from the timeline, so feedback is specific ("at 14:32 you started coding before stating complexity"), not generic.

**1. Deterministic metrics (`feedback/metrics.py`, no LLM)**

- Time per phase, and time to the first line of code, first run and first test.
- Number of runs and how many failed; error types (`IndexError`, `TimeoutError`, ...).
- Silence gaps over 60 s, with timestamps.
- Talk ratio: words you spoke vs the interviewer, and words per minute while coding.
- Hints by level; large pastes; total time muted.
- Your tests: the extracted list (see Code execution) with input, executed or traced, verified or unverified, and its result.

**2. LLM evaluation**

- One call to `claude-opus-5-5` with: the problem, `problem_brief` (including the private edge-case categories), the full transcript, interviewer notes, about 10 key code snapshots (at each phase change, before and after each run, and final), all runs, and the metrics above.
- The final code for Correctness is the last snapshot before Wrap-up began (or the final code if Wrap-up never started).
- Structured output via a forced tool call `submit_report(...)`, validated with Pydantic and retried once if invalid. If that fails too, the Session goes to `report_failed`.
- Rubric: score each dimension 1–4 (1 = strong concern, 4 = strong signal), with 1–3 evidence items `{t_ms, quote_or_code, comment}`:

| Dimension | What a 4 looks like |
| --- | --- |
| Problem understanding | Restated the problem, asked about input size, constraints and edge cases before designing |
| Approach and algorithm | Gave brute force first, then reasoned to optimal; explained trade-offs |
| Communication | Kept up a think-aloud; the interviewer could always follow the reasoning |
| Code quality | Readable names, sensible decomposition, idiomatic Python |
| Correctness | Final code is correct for all edge-case categories in the brief (assessed by reading, not executed; the report says so) |
| Testing and self-validation (weighted 2×) | Chose tests without being prompted, stated expected results, covered normal + edge + adversarial cases, traced by hand before running, fixed what the tests found |
| Complexity analysis | Stated time/space correctly, unprompted, for the final solution |
| Coachability and hints | Used hints well; few needed (Probes don't count as hints) |
| Time management | Phases fit the time limit, with room left for testing |

**3. Report contents (in this order)**

1. A 3–4 sentence summary and the Overall Signal with a one-line rationale. The signal is computed in code, not chosen by the LLM (the LLM writes only the rationale). From the weighted rubric average (Testing counts 2×): < 1.75 Strong No, < 2.25 No, < 2.6 Lean No, < 3.0 Lean Hire, < 3.5 Hire, otherwise Strong Hire. A score of 1 in Testing or Correctness caps the signal at No. Labels show whether autocomplete was on.
2. Rubric table with scores and clickable evidence; each timestamp jumps the replay.
3. Top 3 strengths and top 3 improvements, each improvement with a concrete drill ("Next session, say the complexity out loud before your first line of code").
4. A testing breakdown: tests you wrote, grouped by category and marked executed/traced and verified/unverified ("ran but not verified" listed separately), plus the edge-case categories you missed. Missed categories are revealed only now.
5. Phase timeline bar and metrics.
6. An "Ideal walkthrough": a short description of how a strong candidate would have handled this problem, with the approach and complexity always visible. The optimal solution code is collapsed behind a **Reveal ideal walkthrough** click, so you can retry the problem unspoiled. This is the only place a solution is shown.

**Cross-session trends (v2):** a chart of rubric scores across sessions on the History page.

## API contracts

REST handles session lifecycle and reads. One WebSocket per live session carries everything real-time. All messages are JSON with a `type` field.

**REST**

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions` | Create from `{problem_md, starter_code?, private_notes?, duration_min, style, autocomplete}`; runs problem prep (one retry) and returns `{session_id}`, or an error with no Session created |
| GET | `/api/sessions` | List past sessions (title, date, duration, overall signal) |
| GET | `/api/sessions/{id}` | Session metadata plus all events (for replay) |
| POST | `/api/sessions/{id}/end` | End the session and start report generation |
| GET | `/api/sessions/{id}/report` | The report, or `{status: "generating"}` |
| GET | `/api/sessions/{id}/export` | JSONL download |
| POST | `/api/sessions/{id}/report?regenerate=true` | Rebuild the report from stored events; also backs Retry (after `report_failed`) and Generate report (for `abandoned`) |
| DELETE | `/api/sessions/{id}` | Hard-delete the Session, its events and its report |

**WebSocket `/ws/sessions/{id}`**

| Direction | `type` | Payload |
| --- | --- | --- |
| client → server | `utterance` | `text, channel, start_ms, end_ms` |
| client → server | `speaking` | `active: bool` (from interim results; used for the never-interrupt guard) |
| client → server | `code_update` | `code` |
| client → server | `run` | `code, stdin?` |
| client → server | `set_phase` / `ui_event` | `phase` / paste, mute, interrupted |
| server → client | `interviewer_delta` | `msg_id, text` (streamed tokens) |
| server → client | `interviewer_done` | `msg_id, full_text` |
| server → client | `interviewer_cancel` | `msg_id` (stop TTS) |
| server → client | `run_result` | runner output |
| server → client | `phase`, `clarification`, `timer` | state updates for the UI |
| server → client | `error` | `code, message` (e.g. API key missing, rate limited) |

If the WebSocket reconnects, the client sends its last seen `seq` and the server replays the missed events.

## Data model and storage

One SQLite file (`data/interviews.db`) holds three tables. Use SQLAlchemy 2.x or plain `aiosqlite`. JSON columns are stored as TEXT.

```sql
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,          -- ulid
  created_at TEXT NOT NULL,
  ended_at TEXT,
  title TEXT,                   -- first line of the problem
  problem_md TEXT NOT NULL,
  starter_code TEXT,
  private_notes TEXT,
  settings_json TEXT NOT NULL,  -- duration, style, models, autocomplete
  problem_brief_json TEXT,      -- from problem prep (hidden)
  status TEXT NOT NULL          -- live | ended | abandoned | report_ready | report_failed
);

CREATE TABLE events (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  seq INTEGER NOT NULL,
  t_ms INTEGER NOT NULL,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  UNIQUE(session_id, seq)
);

CREATE TABLE reports (
  session_id TEXT PRIMARY KEY REFERENCES sessions(id),
  created_at TEXT NOT NULL,
  model TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  report_json TEXT NOT NULL,
  usage_json TEXT              -- input/output tokens for cost tracking
);
```

A report can be regenerated from the stored events, for example with a newer model or a revised rubric, via `POST /api/sessions/{id}/report?regenerate=true`.

## Config, setup and project structure

Setup takes one command after cloning. Secrets go in `.env`; everything tunable goes in `config.yaml`.

**Setup**

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY=...
make install                  # uv sync (backend) + npm install (frontend)
make dev                      # uvicorn on :8000 + vite on :5173 (proxying /api and /ws)
# open http://localhost:5173 in Chrome
```

Requirements: Python 3.11+, Node 20+, Chrome or Edge (for Web Speech). The backend checks for the API key at startup and fails with a clear message if it's missing.

**`config.yaml` (defaults)**

```yaml
models:
  prep: claude-opus-5-5
  interviewer: claude-sonnet-5-5
  report: claude-opus-5-5
interview:
  default_duration_min: 45
  proactive_cooldown_s: 45
  max_proactive_per_5min: 3
  silence_nudge_s: {clarify: 45, approach: 45, implement: 90, test: 60}
  run_reaction_delay_s: 3
  muted_silence_multiplier: 2
  user_phase_lock_s: 120
  timeout_grace_s: 60
  abandon_after_idle_min: 10
  style_presets: [faang_standard, friendly_new_grad, pragmatic_startup]
runner:
  python: python3       # system interpreter, not the backend venv; stdlib only
  timeout_s: 10
  memory_mb: 512
  output_cap_kb: 64
voice:
  stt: webspeech        # webspeech | whisper (v2)
  tts: browser          # browser | off
  utterance_silence_ms: 1200
  pause_stt_during_tts: false   # fallback for speakers; disables barge-in
```

**Project structure**

```text
mock-interviewer/
├─ backend/
│  ├─ main.py              # FastAPI app, REST + WS routes
│  ├─ config.py            # loads config.yaml + .env
│  ├─ db.py                # SQLite models + queries
│  ├─ session.py           # SessionManager: event log, queue, timer
│  ├─ runner.py            # sandboxed subprocess execution
│  ├─ agent/
│  │  ├─ prep.py           # problem_brief generation
│  │  ├─ triggers.py       # trigger engine + guardrails
│  │  ├─ interviewer.py    # decision call, streaming, tool handling
│  │  ├─ context.py        # builds the prompt from the event log
│  │  └─ prompts/          # system prompt, prep prompt, report prompt (.md)
│  └─ feedback/
│     ├─ metrics.py        # deterministic metrics
│     ├─ tests.py          # extracts user-written tests via ast
│     ├─ report.py         # LLM evaluation + schema (Pydantic)
│     └─ rubric.yaml
├─ frontend/
│  └─ src/
│     ├─ pages/            # Setup, Interview, Report, History
│     ├─ components/       # Editor, Console, Transcript, TopBar, Timeline
│     ├─ voice/            # SpeechProvider (webspeech), TTS queue, echo guard
│     └─ ws.ts             # typed WebSocket client + reconnect
├─ data/                   # interviews.db (gitignored)
├─ tests/                  # pytest: runner, triggers, metrics, test extractor
├─ config.yaml
├─ .env.example
└─ Makefile
```

## Build milestones and acceptance criteria

The milestones are ordered so each one is usable on its own. After M2 you can already practice with text chat and get a report. Voice and proactivity come after that.

1. **M1: Editor + runner + text chat.** Setup page, Monaco, Run button with limits, WebSocket, problem prep, a reactive text-only interviewer with `record_clarification` (so answers stay consistent from day one), the event log in SQLite.
2. **M2: Recorder + feedback report.** All event types, deterministic metrics, test extractor, LLM report, computed Overall Signal, report page.
3. **M3: Proactive interviewer.** Trigger engine, guardrails, tool calls (hints, notes, phases), timer and phase UI.
4. **M4: Voice.** Web Speech STT, browser TTS with sentence streaming, barge-in, echo guard, mute.
5. **M5: Replay + history.** Timeline scrubber, code at any timestamp, sessions list, delete, export.
6. **v2 (optional):** local Whisper STT, Docker runner, cross-session trend chart, saved problem list (linking retries), scratchpad, push-to-talk.

**Acceptance criteria**

- [ ] Fresh clone to first interview in 5 minutes or less with `make install && make dev`.
- [ ] `while True: pass` is killed after the timeout and the UI stays responsive.
- [ ] Interviewer first token arrives in under 1.5 s (p50) after you finish speaking.
- [ ] The interviewer never states a solution or proposes a concrete test input during a session (spot-check 5 sessions plus a prompt-regression test).
- [ ] Going silent for 90 s while implementing produces exactly one nudge.
- [ ] The interviewer never speaks over you (no proactive message while `speaking: true`).
- [ ] Every rubric score in the report cites at least one timestamp that exists in the event log.
- [ ] The report lists the tests you actually wrote and the edge-case categories you missed.
- [ ] Replay shows the exact code at any chosen timestamp, and every `run` maps to the snapshot that ran.
- [ ] The Overall Signal is reproducible from the rubric scores alone (same scores → same signal).
- [ ] pytest covers the runner limits, trigger timing (with a fake clock), metrics and the test extractor.

## Risks and open questions

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Web Speech mis-hears technical terms ("deque", "O of n log n") | Garbled transcript weakens feedback | Pass the problem's key terms to the agent so it reads past STT errors; Whisper option in v2 |
| Voice latency feels unnatural | Breaks immersion | Sentence-level TTS streaming, prompt caching, Sonnet for live turns; Haiku as a configurable fallback |
| Interviewer is too chatty or too quiet | Unrealistic practice | All thresholds in `config.yaml`; log trigger decisions so you can tune them |
| Model leaks the solution under pressure ("just tell me") | Defeats practice | Hard rule in the system prompt and a prompt-regression test; L4 hint is a step, never code |
| macOS ignores the memory limit | A runaway allocation could swap | Wall-clock timeout plus process-group kill; Docker runner in v2 |
| API cost per session | Minor | Caching the system prompt and brief; `usage_json` per report so you can watch it |

**Resolved questions**

- Ideal walkthrough: generated, with the solution code hidden behind a Reveal click.
- Company-style presets: three presets plus free text; persona only, never scoring.
- Paste detection: noted only, never penalized.
