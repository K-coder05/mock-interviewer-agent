# 11: Voice input

**What to build:** Everything I say is captured continuously and goes on the record. I see my interim speech in gray and final speech in black, and the Interviewer hears every utterance and decides whether to respond. It never speaks while I'm speaking. I can mute my mic; while muted, silence Nudges only consider my code activity, and the Report notes long muted stretches.

**Blocked by:** 09 (Proactive Interviewer: Triggers, guardrails and Nudges)

**Status:** ready-for-agent

- [ ] Speech-provider interface (start, stop, interim, final with timings) backed by browser speech recognition, auto-restarting while the Session is live
- [ ] Utterance boundary: final result or 1.2 s silence; logged as `utterance` with `channel: voice`
- [ ] Client sends `speaking` from interim results; no proactive speech while speaking (interim within 1.5 s)
- [ ] Frontend flushes `code_update` before every final utterance
- [ ] Mute/unmute logged; while muted the silence trigger uses code activity only with the configured multiplier (2×)
- [ ] Muted-time metric; Report notes it under Communication when over 2 min
- [ ] Live Session tests cover the never-interrupt guard and muted silence behavior
