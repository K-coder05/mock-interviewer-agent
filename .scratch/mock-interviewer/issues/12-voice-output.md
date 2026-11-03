# 12: Voice output

**What to build:** The Interviewer's replies are spoken aloud sentence by sentence as they stream, so they feel fast. If I start talking it stops immediately. It never hears and reacts to its own voice. I can mute the Interviewer and read replies as text only.

**Blocked by:** 11 (Voice input)

**Status:** done

- [x] Sentence-level TTS queue using browser speech synthesis; voice and rate configurable
- [x] Barge-in: Candidate speech during TTS stops it and logs `interviewer_interrupted`
- [x] A proactive call in flight is cancelled (`interviewer_cancel`) when the Candidate starts speaking; replies to questions are not
- [x] Echo guard discards transcripts closely matching the Interviewer's current text; STT keeps running
- [x] Config fallback to pause STT during TTS (speakers only) works and disables barge-in
- [x] Mute-interviewer toggle shows replies as text only
- [x] Automated tests for the echo-guard matcher (pure function)

## Comments

**Built (ticket 12):**
- `frontend/src/voice/tts.ts`: `SentenceTts` on `speechSynthesis`: `push(msgId, delta)` speaks each complete sentence (. ! ? … or a line break) as it streams, `finish` speaks the rest, `cancel(msgId)` (on `interviewer_cancel`) and `interrupt()` (barge-in) stop it and drop the reply's later deltas, `setEnabled(false)` mutes. `speaking` covers the whole reply (also the gaps while it still streams); `echoReference()` is the text being spoken, kept for `ECHO_TAIL_MS` (3 s) after speech stops since recognition reports words late. Voice and rate from `config.yaml` `voice.tts_voice` / `tts_rate` (`tts: off` disables TTS); all stored in `settings.voice` (`VoiceConfig.from_config`).
- `frontend/src/voice/echoGuard.ts`: `isEcho(transcript, interviewerText)` (pure): echo when >= 70% of the transcript's words match, in order, the Interviewer's text (word LCS; case/punctuation/apostrophes ignored; words of 4+ letters match with about one misrecognized letter per 4). Tests: `echoGuard.test.ts` (vitest, new `npm test`, part of `make test`/`make check`).
- `InterviewPage`: STT keeps running during TTS; echo interims/finals are dropped before anything is shown or sent. Any other interim or final while TTS speaks is a barge-in: TTS stops at once and `ui_event {event: "interrupted", msg_id}` is sent. With `voice.pause_stt_during_tts: true` the recognizer is stopped while TTS speaks (no barge-in possible) and restarted after. "Interviewer voice on / Interviewer muted" toggle in the top bar (replies are text only; remembered in localStorage).
- Session: `ui_event interrupted` -> `interviewer_interrupted {msg_id}` (shown to the Interviewer in the turn transcript as having been cut off, and in the Report timeline). A proactive call's model stream is cancelled when `speaking {active: true}` arrives: `interviewer_cancel` for its msg_id (if it streamed), nothing logged as said, a `trigger` event `outcome: suppressed, suppressed_by: speaking, cancelled: true`, and the Triggers go through `hold_back` like any speech suppression (stuck and Run reactions retry, silence is dropped). Replies (typed, spoken utterance, start/time-up/end) are never cancelled. Once the stream has finished, the call's tool calls are applied whole (no cancel mid-apply).
- Tests: `tests/test_voice_output.py` (cancellation, retry after cancel, replies not cancelled, `speaking: false` doesn't cancel, interrupted logging + context, Report timeline, TTS settings). Gated tests use a timeout so a regression fails instead of hanging.

**Deferred / notes for later tickets:**
- TTS voice and rate are set in `config.yaml`, not in a Settings screen (no settings UI exists yet).
- Interviewer utterances are still logged with `channel: "text"` (the server doesn't know whether the client spoke them; Interviewer muting is client-only).
- A short Candidate word that the Interviewer also just said ("okay") while it speaks counts as echo (no barge-in); the trade-off keeps early echo interims (1-2 words) from stopping TTS.
- 13 (reconnect): TTS only speaks replies streamed live; replayed history is not spoken.
- Frontend voice behavior (TTS, barge-in, echo, fallback, mute toggle) is verified manually only (spec); not clicked through in a browser here.
- Review (two-axis code-review): fixed barge-in before a reply's first sentence silently dropping that reply from TTS (`interrupt()` now only acts while speaking), barge-in still wired with the `pause_stt_during_tts` fallback (now off), the configured voice missing on the first sentence (voice list primed early), a ref written during render, a duplicated TTS-enabled check (`ttsEnabled`), an unused `threshold` parameter and unclear names (`_proactive_call`, `refreshSpeaking`). Left: `interviewer_interrupted.msg_id` isn't checked against a logged Interviewer utterance (the reply may still be streaming, so it isn't logged yet); muting the Interviewer mid-reply drops the rest of that reply even if unmuted again; every new event type still needs a branch in both `context.py` and `report.py` (existing pattern); the turn-transcript note about being interrupted and the remembered Interviewer-mute toggle go slightly beyond the spec's wording.

- 2026-11-02 (orchestrator): Not yet verified in a real browser. Code is built and type-checked; speech behavior needs a manual Chrome check.
