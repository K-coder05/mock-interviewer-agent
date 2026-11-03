# 12: Voice output

**What to build:** The Interviewer's replies are spoken aloud sentence by sentence as they stream, so they feel fast. If I start talking it stops immediately. It never hears and reacts to its own voice. I can mute the Interviewer and read replies as text only.

**Blocked by:** 11 (Voice input)

**Status:** ready-for-agent

- [ ] Sentence-level TTS queue using browser speech synthesis; voice and rate configurable
- [ ] Barge-in: Candidate speech during TTS stops it and logs `interviewer_interrupted`
- [ ] A proactive call in flight is cancelled (`interviewer_cancel`) when the Candidate starts speaking; replies to questions are not
- [ ] Echo guard discards transcripts closely matching the Interviewer's current text; STT keeps running
- [ ] Config fallback to pause STT during TTS (speakers only) works and disables barge-in
- [ ] Mute-interviewer toggle shows replies as text only
- [ ] Automated tests for the echo-guard matcher (pure function)
