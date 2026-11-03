# 16: Prompt-regression test

**What to build:** An opt-in test suite runs scripted Sessions against the real API and checks that the Interviewer holds the line: it never states a solution, writes code or proposes a concrete test input, even when pressed with "just tell me the answer" or "what should I test?".

**Blocked by:** 10 (Reacting to Runs and being stuck, plus Hints)

**Status:** ready-for-agent

- [ ] Runs only when explicitly enabled (not part of the default test run)
- [ ] Covers direct solution requests, test-input requests and repeated pressure
- [ ] Asserts no code blocks, no concrete test inputs and Hints never above L4 in output
- [ ] Documented in the README
