# Spec: Mock Interviewer

Status: ready-for-agent

Source: `Mock Interviewer Agent — Spec Sheet.md` (the detailed design reference) and `GLOSSARY.md` (canonical vocabulary). Where this spec and the sheet disagree, the sheet's resolved decisions win; flag the conflict.

## Problem Statement

As someone preparing for coding interviews, I can grind problems alone, but solo practice doesn't train what interviewers actually assess: clarifying the problem, talking through an approach, communicating while coding, and above all proving my own code works by choosing and running my own tests. Online judges hand me a hidden test suite and a pass/fail, which trains the opposite habit. Human mock interviews are scarce, expensive and hard to schedule, and their feedback is rarely specific or evidence-based.

## Solution

A single-user web app that runs on my laptop. I paste any problem, and a Claude-powered **Interviewer** conducts a realistic, timed **Session**: it listens to me think aloud (voice, with typed fallback), watches my code and my **Runs**, answers **Clarifications** consistently, **Probes** my reasoning, **Nudges** me when I go quiet or get stuck, and gives laddered **Hints** only when I'm genuinely stuck — but never gives the solution and never proposes test inputs. Everything I say, type and run is recorded as an append-only event log. When the Session ends, I get a **Report** that grades my process against a rubric, with every score citing timestamped evidence, a breakdown of my **Candidate Tests** against the hidden **Edge-Case Categories**, a mechanically derived **Overall Signal**, and an optional **Ideal Walkthrough**. I can replay any past Session at any moment.

## User Stories

### Setup

1. As a Candidate, I want to paste any problem statement in Markdown, so that I can practice on exactly the problems I care about.
2. As a Candidate, I want to optionally provide a function signature or starter code, so that the Session matches how the problem is usually presented.
3. As a Candidate, I want starter code preloaded into my editor and excluded from "code I wrote" metrics, so that my metrics reflect only my own work.
4. As a Candidate, I want to add private notes for the Interviewer (e.g. the intended complexity), so that it can steer and answer like an interviewer who knows the problem.
5. As a Candidate, I want my private notes never shown to me during the Session, so that they don't spoil the problem.
6. As a Candidate, I want to choose a Session duration (default 45 min), so that I can match real interview lengths.
7. As a Candidate, I want to pick a Style preset ("FAANG standard", "Friendly new-grad", "Pragmatic startup") or describe one in free text, so that the Interviewer's persona matches what I'm preparing for.
8. As a Candidate, I want Style to never change scoring, so that Reports stay comparable across Sessions.
9. As a Candidate, I want to decide on the setup screen whether editor autocomplete is on, so that I can choose realism vs comfort before starting.
10. As a Candidate, I want to be told that headphones are recommended and only the Python standard library is available, so that I'm not surprised mid-Session.
11. As a Candidate, I want a clear "Interviewer is reading the problem…" screen while the Problem Brief is prepared, so that I know the app is working.
12. As a Candidate, I want the timer to start only when the Interviewer's greeting begins, so that prep time isn't charged to me.
13. As a Candidate, I want a failed problem prep to return me to setup with my input intact and no Session created, so that I can just retry.
14. As a Candidate, I want the Interviewer to open with a greeting and a restatement of the problem, so that the Session feels like a real interview.

### Live Session: workspace

15. As a Candidate, I want the problem, editor, console and conversation all visible at once, so that I never tab-switch mid-Session.
16. As a Candidate, I want a Python 3 editor with highlighting and 4-space tabs but no autocomplete by default, so that it feels like CoderPad.
17. As a Candidate, I want a Run button (and Cmd/Ctrl+Enter) that executes exactly my buffer with nothing injected, so that I'm responsible for my own calls, asserts and prints.
18. As a Candidate, I want an optional stdin box, so that I can test programs that read input.
19. As a Candidate, I want to see stdout, stderr, exit code and runtime for each Run, so that I can judge my results.
20. As a Candidate, I want an infinite loop or runaway allocation to be killed after a timeout while the UI stays responsive, so that a bug doesn't wreck my Session.
21. As a Candidate, I want huge output truncated with a visible marker, so that a print loop doesn't freeze the page.
22. As a Candidate, I want clicking Run while a Run is in progress to cancel and restart it, so that I'm never stuck waiting.
23. As a Candidate, I want Clarifications to auto-append under the problem, so that I can refer back to agreed constraints.
24. As a Candidate, I want a countdown timer that turns red at 5 minutes left, so that I manage my time.
25. As a Candidate, I want a phase indicator that follows the Interviewer but that I can click to set any Phase, forward or back, so that I'm in control of the flow.
26. As a Candidate, I want the Interviewer to not override a Phase I just set for 2 minutes, so that we don't fight over it.

### Live Session: talking

27. As a Candidate, I want everything I say captured continuously without pressing a button, so that my think-aloud is on the record like in a real interview.
28. As a Candidate, I want to see my interim speech in gray and final speech in black, so that I know I'm being heard.
29. As a Candidate, I want to type to the Interviewer at any time and always get a reply, so that I can communicate when speech fails.
30. As a Candidate, I want Interviewer replies streamed as text and spoken sentence by sentence, so that responses feel fast and natural.
31. As a Candidate, I want the Interviewer to stop talking the moment I start speaking, so that I can interrupt as I would a person.
32. As a Candidate, I want the Interviewer to never hear and react to its own voice, so that the conversation isn't polluted by echo.
33. As a Candidate, I want to mute my mic, so that I can handle background noise or step away.
34. As a Candidate, I want muting not to trigger false silence Nudges, so that I'm not pestered while muted.
35. As a Candidate, I want to mute the Interviewer's voice and read replies as text only, so that I can practice in a quiet environment.
36. As a Candidate, I want the Interviewer to read past speech-recognition errors on technical terms, so that "deck" vs "deque" doesn't derail it.

### Live Session: Interviewer behavior

37. As a Candidate, I want the Interviewer to answer clarifying questions consistently with the Problem Brief and my private notes, so that the problem doesn't shift under me.
38. As a Candidate, I want the Interviewer to ask "What would you assume?" when the problem leaves something open, and treat my stated assumption as binding, so that I practice stating assumptions.
39. As a Candidate, I want the Interviewer to Probe complexity, trade-offs and "what happens if…", so that I practice defending my reasoning.
40. As a Candidate, I want Probes never to count against me, so that being questioned doesn't look like needing help.
41. As a Candidate, I want the Interviewer to Nudge me after prolonged silence (longer while implementing), so that I keep thinking aloud.
42. As a Candidate, I want exactly one Nudge per silence, not a stream of them, so that it feels human.
43. As a Candidate, I want the Interviewer to react after a Run — asking about a failure or what I expected — so that I reflect on results.
44. As a Candidate, I want the Interviewer to notice when I'm stuck (repeated failures or the same exception) and Probe before Hinting, so that I get a chance to recover myself.
45. As a Candidate, I want Hints to climb a ladder from a probing question to a concrete next step, so that I get the least help necessary.
46. As a Candidate, I want an explicit hint request honored immediately at the next level, so that I'm not forced to visibly struggle first.
47. As a Candidate, I want "just tell me the answer" to get at most a concrete next step and never code, so that the practice isn't defeated.
48. As a Candidate, I want the Interviewer to ask me to walk through a large chunk of new code after I pause, so that I practice explaining my code.
49. As a Candidate, I want time-checkpoint prompts (halfway with no code, 10 and 5 minutes left), so that I learn to pace myself.
50. As a Candidate, I want the Interviewer to never speak while I'm speaking, so that I'm never talked over.
51. As a Candidate, I want unprompted Interviewer speech capped (cooldown and per-5-minute limit) while direct replies are exempt, so that it's neither chatty nor unresponsive.
52. As a Candidate, I want the Interviewer to never propose test inputs and to turn "what should I test?" back on me, so that I practice the core skill.
53. As a Candidate, I want the Interviewer to prompt me to test when I claim I'm done without having tested, so that I build the habit.
54. As a Candidate, I want the Interviewer to stay neutral and never praise or judge mid-Session, so that I don't read verdicts into its tone.
55. As a Candidate, I want short conversational replies with no Markdown or code, so that spoken output sounds natural.
56. As a Candidate, I want follow-up questions in Wrap-up to be discussion rather than a second graded problem, so that extra time is a bonus, not a risk.
57. As a Candidate, I want the Interviewer to close a phase I've overrun (e.g. clarifying more than 8 min), so that I don't burn the Session.

### Ending

58. As a Candidate, I want an End Interview button, so that I can finish early.
59. As a Candidate, I want a 5-minute warning and, at 0:00, a "time's up, any last thought?" with a 60-second grace before auto-end, so that the ending feels real but bounded.
60. As a Candidate, I want the Interviewer to close politely with no verdict, so that evaluation is left to the Report.
61. As a Candidate, I want a refreshed tab to reconnect and resume my Session with nothing lost, so that a browser hiccup doesn't ruin practice.
62. As a Candidate, I want a Session left hanging by a crash to become an Abandoned Session I can still generate a Report for, so that the practice isn't wasted.

### Report

63. As a Candidate, I want a Report within about a minute of ending, so that feedback is fresh.
64. As a Candidate, I want each rubric dimension scored 1–4 with 1–3 timestamped evidence items, so that feedback is specific, not generic.
65. As a Candidate, I want every evidence timestamp to jump the replay to that moment, so that I can see exactly what happened.
66. As a Candidate, I want Testing and self-validation weighted double, so that the Report emphasizes the skill I'm practicing.
67. As a Candidate, I want an Overall Signal (Strong No … Strong Hire) computed mechanically from the scores, with a one-line rationale, so that it's consistent and explainable.
68. As a Candidate, I want a 1 in Testing or Correctness to cap the Overall Signal at No, so that the signal reflects real hiring bars.
69. As a Candidate, I want Correctness clearly labeled as assessed by reading, not executed, so that I know its limits.
70. As a Candidate, I want Correctness judged on my code as of the start of Wrap-up, so that exploratory follow-up code doesn't hurt me.
71. As a Candidate, I want a list of my Candidate Tests marked executed or traced and verified or unverified, so that I see how rigorous my testing was.
72. As a Candidate, I want prints whose expected value I never stated listed as "ran but not verified", so that I learn to state expectations.
73. As a Candidate, I want the Edge-Case Categories I missed revealed only in the Report, so that I learn what to cover next time.
74. As a Candidate, I want top 3 strengths and top 3 improvements, each improvement with a concrete drill, so that I know what to practice next.
75. As a Candidate, I want deterministic metrics — time per phase, time to first code/Run/test, Runs and failures, error types, silence gaps, talk ratio, Hints by level, pastes, time muted — so that I have objective numbers.
76. As a Candidate, I want a phase timeline bar, so that I can see how I spent my time.
77. As a Candidate, I want large pastes noted but never penalized, so that the record is honest without punishing me.
78. As a Candidate, I want the Report to show whether autocomplete was on, so that I can interpret code-quality metrics fairly.
79. As a Candidate, I want the Report to note if I was muted for long stretches, so that thin Communication evidence is explained.
80. As a Candidate, I want an Ideal Walkthrough whose approach is visible but whose code is hidden until I click Reveal, so that I can retry the problem unspoiled.
81. As a Candidate, I want a Retry button if Report generation fails, so that a transient API error doesn't lose my feedback.
82. As a Candidate, I want to regenerate a Report from the stored events (e.g. with a newer model), so that old Sessions can benefit from improvements.
83. As a Candidate, I want to see token usage per Report, so that I can watch API cost.

### History, replay and export

84. As a Candidate, I want a list of past Sessions with title, date, duration and Overall Signal, so that I can track my practice.
85. As a Candidate, I want to scrub through a Session's timeline and see the exact code at any moment beside the transcript, so that I can review my process.
86. As a Candidate, I want timeline markers for Runs, Hints, Phase changes and long silences, so that I can jump to key moments.
87. As a Candidate, I want each Run in replay to show the exact code that ran, so that I can understand its output.
88. As a Candidate, I want to export a Session as JSONL with its Report, so that I own my data.
89. As a Candidate, I want to delete a Session with confirmation, so that I can discard botched or test Sessions.

### Operator (me, setting up and tuning)

90. As the operator, I want clone → add API key → one command to start, so that setup takes under 5 minutes.
91. As the operator, I want a clear startup error if the API key is missing or the Python interpreter is older than 3.11, so that misconfiguration is obvious.
92. As the operator, I want all thresholds, limits and model ids in one config file, so that I can tune the Interviewer without code changes.
93. As the operator, I want every Trigger and its outcome (spoke, silent, suppressed) logged, so that I can tune chattiness from evidence.
94. As the operator, I want clear UI errors for API failures like rate limits, so that I know when the Interviewer is down rather than silent.

## Implementation Decisions

**Architecture**
- Two local processes: a React + TypeScript frontend (Vite, Monaco) and a Python 3.11+ FastAPI backend. One WebSocket per live Session carries all real-time traffic; REST handles lifecycle and reads.
- The per-Session append-only event log is the single source of truth. The live Interviewer, the Report and replay all read from it. The backend owns timestamps (milliseconds since Session start, from a monotonic clock).
- Storage is one SQLite file with three tables: sessions, events, reports. JSON stored as text. Session status is one of live, ended, abandoned, report_ready, report_failed.
- Models are configurable: Opus for problem prep and the Report, Sonnet for live decisions.

**Modules (deep modules, small interfaces)**
- **Session engine**: owns a live Session — accepts client messages (utterance, speaking, code_update, run, set_phase, ui_event), appends events, runs the trigger engine and guardrails, owns the timer (warnings, 60 s grace, auto-end), Phase state and the 2-minute user Phase lock, coalesces/cancels Interviewer calls, and emits server messages. Takes an injected clock, Interviewer model client and Runner. On startup, marks stale live Sessions abandoned. Supports replay of missed events after reconnect from a last-seen sequence number.
- **Interviewer**: builds the decision-call context fresh from the event log each time (no running message history; system prompt with persona, Style, problem and Problem Brief, prompt-cached), streams text as speech, and applies tool calls at stream end: stay_silent, record_clarification (with `by`: interviewer or candidate), give_hint (level 1–4), set_phase, note.
- **Problem prep**: one call producing the hidden Problem Brief (approaches with complexity, insights, pitfalls, Edge-Case Categories, default clarification answers, follow-ups). One retry; failure creates no Session.
- **Runner**: executes a buffer in a fresh temp dir with the system Python interpreter (configurable, never the backend's environment; standard library only) in isolated mode, with wall-clock timeout and process-group kill, memory limit where the OS enforces it, per-stream output cap, optional stdin. One Run at a time per Session; a new Run cancels the old.
- **Report generator**: from a stored event log, computes deterministic metrics, extracts Candidate Tests, calls the model with a forced structured `submit_report` tool (validated, retried once, else report_failed), and computes the Overall Signal in code. Used for first generation, Retry, regeneration and abandoned Sessions alike.
- **Candidate Test extractor**: finds executed Candidate Tests from code via syntax-tree analysis (asserts, calls under the main guard, printed calls, stdin) and has the model tag traced tests from the transcript at Report time; marks each verified (assert, or expected value said/commented within ~30 s) or unverified.
- **Frontend voice layer**: a speech-provider interface (start, stop, interim, final with timings) backed by the browser speech-recognition API with auto-restart; sentence-level TTS queue; barge-in; echo guard as a pure matcher that discards transcripts closely matching the Interviewer's current text.

**Event log contract** (event envelope: id, session id, seq, t_ms, type, payload)
- session_started (problem, settings incl. Style, autocomplete, model ids), utterance (speaker, channel voice/text, text, start/end), code_snapshot (full code, diff, chars added/removed), paste, run (references the snapshot seq of the code that ran, plus stdin/stdout/stderr/exit/duration/timed_out), phase_changed (from, to, by agent/user), clarification (question, answer, by), hint_given (level, text), interviewer_note, trigger (reason, outcome spoke/silent/suppressed — a Nudge is a trigger that spoke), mic_muted/mic_unmuted, interviewer_interrupted, session_ended (reason, final code).
- Starter code is the first snapshot at t=0. Every Run is preceded by a forced snapshot. Snapshots are deduped.
- The frontend flushes a code_update before every final utterance and every Run, in addition to idle/periodic sync.

**Interviewer rules (system-prompt essentials)**
- Real interviewer, not tutor; 1–3 spoken sentences, no Markdown/code; neutral acknowledgments only.
- Never give the solution, write code or propose test inputs.
- Clarifications from private notes / Problem Brief; otherwise ask the Candidate to state an assumption and record it as binding.
- Probes are assessment, never logged as Hints. Hints climb L1–L4 after visible struggle; explicit requests get the next level immediately; never code.
- Follow-ups in Wrap-up are discussion only. Style shapes only the persona section.

**Trigger engine and guardrails**
- Triggers: typed message (always reply), final utterance, Run finished (after a short delay, merged with speech), silence (per-Phase thresholds; while muted, code activity only with doubled threshold), stuck (3 failing Runs or same exception twice), coding pause (≥25 lines then 30 s idle), time checkpoints, Phase/done.
- Guardrails on every unprompted utterance (Probe, Nudge or Hint): never while the Candidate is speaking (interim speech within 1.5 s), 45 s cooldown, max 3 per 5 min. Replies to typed messages and direct questions are exempt.
- One decision call in flight per Session; events arriving meanwhile coalesce into the next. A proactive call is cancelled if the Candidate starts speaking; a reply is not.

**Report**
- Rubric dimensions scored 1–4 with 1–3 evidence items each: problem understanding, approach, communication, code quality, correctness, testing (2×), complexity, coachability, time management. Every evidence timestamp must exist in the event log.
- Overall Signal from the weighted average: < 1.75 Strong No, < 2.25 No, < 2.6 Lean No, < 3.0 Lean Hire, < 3.5 Hire, else Strong Hire; a 1 in Testing or Correctness caps at No. The model writes only the rationale.
- Correctness is judged by reading the last snapshot before Wrap-up (or final code if Wrap-up never began) and labeled as not executed.
- Ideal Walkthrough approach always visible; code hidden behind Reveal.

**API contracts**
- REST: create Session (problem, starter code, private notes, duration, Style, autocomplete; runs prep), list Sessions, get Session with events, end Session, get Report (or generating status), export JSONL, regenerate Report (also backs Retry and Generate report), delete Session (hard delete).
- WebSocket client→server: utterance, speaking, code_update, run, set_phase, ui_event (paste, mute, interrupted). Server→client: interviewer_delta, interviewer_done, interviewer_cancel, run_result, phase, clarification, timer, error. Reconnect sends last seen seq; server replays missed events.

**Config**
- Secrets in an env file; everything tunable (models, durations, cooldowns, caps, silence thresholds, muted multiplier, Phase lock, grace, abandon idle threshold, Style presets, runner interpreter and limits, voice settings including the speaker-only "pause STT during TTS" fallback) in one config file.

**Milestones** (each usable on its own)
1. Editor + Runner + text chat + problem prep + Clarifications + event log.
2. Full recorder + Report (metrics, Candidate Test extraction, Overall Signal, Report page).
3. Proactive Interviewer (triggers, guardrails, Hints, notes, Phases, timer UI).
4. Voice (STT, sentence TTS, barge-in, echo guard, mute).
5. Replay + history (scrubber, code at any time, list, delete, export).

## Testing Decisions

**What makes a good test here:** tests exercise external behavior through the highest available seam — messages in, events and server messages out — never internal helpers, private state or prompt wording. Time is always controlled by a fake clock, never real sleeps. The model is always a scripted fake in the regular suite, returning canned text and tool calls, so tests assert on what the system does with model output, not on the model.

**Seams (agreed):**
1. **Live Session seam (primary).** Drive the Session engine with the same messages the WebSocket carries plus fake-clock advances; assert on the resulting event log and emitted server messages. Covers the trigger engine and guardrails (exactly one Nudge after 90 s implementing silence; no proactive speech while speaking; cooldown and caps; muted silence behavior), Phase changes and the 2-minute user lock, forced snapshot before Run and t=0 starter snapshot, code dedup, Clarifications including `by: candidate`, Hint levels including explicit requests, call coalescing and proactive-call cancellation, timer warnings / grace / auto-end, abandoned marking on startup, and reconnect replay. The trigger engine has no separate seam.
2. **Report seam.** Feed a stored event log (built via the Live Session seam or fixtures) with a scripted fake model returning `submit_report`; assert on the Report. Covers deterministic metrics, Candidate Test extraction (executed/traced, verified/unverified), Overall Signal thresholds and cap, Correctness snapshot selection, evidence timestamps existing in the log, validation retry then report_failed, regeneration and abandoned-Session generation.
3. **Runner seam.** Real subprocesses: `while True: pass` killed at the timeout, output cap with marker, stdin, isolation (backend packages not importable), cancel-and-restart.

**Outside the regular suite:**
- An opt-in prompt-regression test against the real API asserting the Interviewer never states a solution, writes code or proposes a concrete test input, including under "just tell me the answer" pressure.
- Frontend: only the echo-guard matcher gets automated tests (pure function). All other voice/UI behavior is verified manually against the acceptance criteria.

**Prior art:** none — greenfield repo. The first Live Session test should establish the harness (fake clock, scripted model, message driver) that the rest reuse.

## Out of Scope

- Hidden or model-generated test cases, executing the Candidate's code against anything at grading time, pass/fail scoring.
- Languages other than Python 3; third-party Python packages in the Runner.
- Accounts, multi-user, cloud deploy, hardened/Docker sandbox.
- A problem bank or linking retries of the same problem (v2: saved problem list).
- Local Whisper STT, push-to-talk, the scratchpad, cross-session trend charts (all v2).
- Toggling autocomplete mid-Session; overtime past the 60 s grace.
- Penalizing pastes.

## Further Notes

- macOS largely ignores the memory limit; the wall-clock timeout and process-group kill are the real protection there.
- Browser speech recognition works fully only in Chrome/Edge and sends audio to the browser vendor; this is accepted for v1.
- Latency targets: Interviewer first token under 1.5 s (p50) after the Candidate finishes speaking; first audio under 2.5 s. Prompt caching of the system prompt and Problem Brief is required to hit them.
- Acceptance criteria in the spec sheet remain the definition of done for v1.
