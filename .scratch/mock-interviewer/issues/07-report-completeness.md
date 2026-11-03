# 07: Report completeness

**What to build:** The Report gains the remaining deterministic metrics, top 3 strengths and top 3 improvements (each with a concrete drill), and an Ideal Walkthrough whose approach is visible but whose code stays hidden until I click Reveal. Large pastes are noted but never penalized, and the Report shows whether autocomplete was on (chosen on the setup screen only).

**Blocked by:** 05 (First Report end to end)

**Status:** ready-for-agent

- [ ] Metrics: time to first code/Run/test, Runs and failures, error types, silence gaps over 60 s, talk ratio and words per minute while coding, Hints by level, large pastes
- [ ] Pastes over 200 characters are logged as `paste` events and appear in metrics; the rubric never penalizes them
- [ ] Autocomplete toggle exists on setup only, is stored in settings, and is labeled on the Report
- [ ] Strengths and improvements (3 each), each improvement with a drill
- [ ] Ideal Walkthrough: approach and complexity visible; code collapsed behind Reveal
- [ ] Report seam tests cover the deterministic metrics
