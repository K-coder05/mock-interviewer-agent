# 08: Phases

**What to build:** The top bar shows the current Phase (Clarify, Approach, Implement, Test, Wrap-up). The Interviewer moves it as the Session progresses, and I can click to set any Phase, forward or back. After I set it, the Interviewer won't change it for 2 minutes. The Report shows time per Phase as a timeline bar and judges Correctness on my code as of the start of Wrap-up.

**Blocked by:** 03 (Problem prep and a text-chat Interviewer), 05 (First Report end to end)

**Status:** ready-for-agent

- [ ] `phase_changed` events record from, to and by (agent/user)
- [ ] Agent `set_phase` is ignored for the configured lock (2 min) after a user change
- [ ] Phases can move backward
- [ ] Time-per-phase metric sums all intervals per Phase; Report shows a phase timeline bar
- [ ] Correctness uses the last snapshot before Wrap-up began (final code if Wrap-up never began)
- [ ] Interviewer brings an overrun Phase to a close (e.g. clarifying > 8 min)
- [ ] Live Session tests cover the user lock and backward moves; Report seam test covers Correctness snapshot selection
