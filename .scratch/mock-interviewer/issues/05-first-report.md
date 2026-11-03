# 05: First Report end to end

**What to build:** When a Session ends, a Report is generated and shown within about a minute: a short summary, the Overall Signal with a one-line rationale, and a rubric table where each dimension is scored 1–4 with timestamped evidence. If generation fails I see a Retry button.

**Blocked by:** 04 (Timer and ending a Session)

**Status:** ready-for-agent

- [ ] Ending a Session starts Report generation; `GET report` returns a generating status until ready
- [ ] The model is called with a forced structured `submit_report`; output is validated and retried once, else status `report_failed`
- [ ] Retry (via regenerate) rebuilds the Report from stored events
- [ ] Rubric: all nine dimensions scored 1–4 with 1–3 evidence items; every evidence `t_ms` exists in the event log
- [ ] Overall Signal computed in code from the weighted average (Testing 2×) with the agreed thresholds (Strong No, No, Lean No, Lean Hire, Hire, Strong Hire) and the Testing/Correctness cap; the model writes only the rationale
- [ ] Correctness is labeled as assessed by reading, not executed
- [ ] Report stores model and token usage
- [ ] Report seam harness exists; tests cover signal thresholds and cap, validation retry and `report_failed`
