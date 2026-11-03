# 10: Reacting to Runs and being stuck, plus Hints

**What to build:** The Interviewer reacts after I run code — asking about a failure or what I expected — and notices when I'm stuck, Probing first and then offering laddered Hints. After a big burst of code and a pause it asks me to walk through it. If I ask for a hint I get the next level immediately; "just tell me" gets at most a concrete next step, never code. It records private observations for the Report.

**Blocked by:** 02 (Run your code), 09 (Proactive Interviewer: Triggers, guardrails and Nudges)

**Status:** ready-for-agent

- [ ] Decision context includes the last 3 Runs, current code with line numbers and the last diff
- [ ] Run-finished trigger fires after the configured delay, merged with speech in the meantime
- [ ] Stuck trigger: 3 failing Runs in a row or the same exception twice
- [ ] Coding-pause trigger: ≥25 lines changed then 30 s idle
- [ ] `give_hint(level, text)` logs `hint_given` with level 1–4; explicit requests get one level above the last Hint
- [ ] Probes are never logged as Hints and don't affect coachability
- [ ] `note` logs private `interviewer_note` events, never shown live, included in Report input
- [ ] Live Session tests cover each trigger and the explicit-hint-request rule
