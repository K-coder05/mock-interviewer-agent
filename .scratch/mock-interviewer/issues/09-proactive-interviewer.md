# 09: Proactive Interviewer: Triggers, guardrails and Nudges

**What to build:** The Interviewer speaks up on its own when it should. If I go quiet it Nudges me ("What are you thinking right now?") after a Phase-dependent silence; it prompts at time checkpoints. It is never chatty: unprompted speech respects a cooldown and a cap, while replies to my direct questions are never held back. Every Trigger and its outcome is logged so the behavior can be tuned.

**Blocked by:** 04 (Timer and ending a Session), 08 (Phases)

**Status:** ready-for-agent

- [ ] Trigger engine consumes the per-Session event queue and logs `trigger` events with reason and outcome (spoke/silent/suppressed)
- [ ] Silence trigger uses per-Phase thresholds from config (45/45/90/60 s)
- [ ] Time checkpoints: 50% elapsed with no code, 10 min left, 5 min left
- [ ] Guardrails apply to every unprompted utterance: 45 s cooldown, max 3 per 5 min; typed messages and direct questions exempt
- [ ] `stay_silent` produces no speech and logs its reason
- [ ] One decision call in flight per Session; events arriving meanwhile coalesce into the next call
- [ ] Live Session test: 90 s of silence while implementing produces exactly one Nudge
- [ ] Live Session tests cover cooldown, cap and coalescing with the fake clock
