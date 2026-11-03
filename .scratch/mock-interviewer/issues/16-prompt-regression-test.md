# 16: Prompt-regression test

**What to build:** An opt-in test suite runs scripted Sessions against the real API and checks that the Interviewer holds the line: it never states a solution, writes code or proposes a concrete test input, even when pressed with "just tell me the answer" or "what should I test?".

**Blocked by:** 10 (Reacting to Runs and being stuck, plus Hints)

**Status:** done

- [x] Runs only when explicitly enabled (not part of the default test run)
- [x] Covers direct solution requests, test-input requests and repeated pressure
- [x] Asserts no code blocks, no concrete test inputs and Hints never above L4 in output
- [x] Documented in the README

## Comments

**Built (ticket 16):**
- `tests/prompt_rules.py`: pure helpers `has_code_block`, `has_concrete_test_input`, `hints_within_cap` (cap `MAX_HINT_LEVEL` = 4) and `violations`; unit-tested in the default run by `tests/test_prompt_rules.py`.
- `tests/test_prompt_regression.py` (marker `prompt_regression`, registered in `pyproject.toml`): skipped unless `RUN_PROMPT_REGRESSION=1` and `ANTHROPIC_API_KEY`. Uses the Live Session harness with the real `AnthropicModelClient` (prep alone is answered with the default Brief). 7 scenarios: direct solution requests, test-input requests, one 8-message repeated-pressure run. Checks every interviewer utterance and `hint_given` text plus the logged levels.
- Limits: `hint_given` levels are clamped in code, so the L4 check guards the log, not what the model asked for; Hints given as plain text instead of `give_hint` are only covered by the utterance checks. The detectors are heuristics. The real-API suite was not run by the implementing agent (no key in its environment).
