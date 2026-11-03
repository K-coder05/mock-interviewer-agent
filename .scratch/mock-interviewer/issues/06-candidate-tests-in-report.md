# 06: Candidate Tests in the Report

**What to build:** The Report shows the Candidate Tests I wrote or spoke: each marked executed or traced, and verified (I stated the expected result) or unverified. Prints whose expected value I never stated are listed separately as "ran but not verified". Only now are the Edge-Case Categories I missed revealed.

**Blocked by:** 02 (Run your code), 05 (First Report end to end)

**Status:** done

- [x] Executed tests extracted from code via syntax-tree analysis: asserts, calls under the main guard, printed calls, stdin inputs
- [x] Traced tests are tagged from the transcript by the model at Report time
- [x] Asserts are verified; a printed call is verified only if the expected value was said or commented within ~30 s
- [x] Testing breakdown groups tests by category and lists missed Edge-Case Categories from the Problem Brief
- [x] Testing rubric rewards stated expectations
- [x] Report seam tests cover each extraction form and the verified/unverified rules

## Comments

**Built (ticket 06):**
- `backend/feedback/tests.py`: `extract_executed_tests(events)` parses the code each Run executed with `ast`: module-level and main-guard `assert`s, calls under the main guard (bare or assigned), `print(f(x))` at module level or under the guard, and non-empty Run stdin. Statements after the traceback's failing `main.py` line are dropped as never reached; the same statement across Runs is one test (first time, run count, latest outcome). Ids `x1...`.
- Verified: asserts always; otherwise a comment on the call's lines or alone on the line above, or a Candidate utterance within 30 s of the Run, matching the `EXPECTATION` keyword heuristic (expect/should/->/returns/equals/answer...). Heuristic, generous; a spoken expectation verifies every non-assert test of that Run.
- Report: `submit_report` gained `executed_test_categories` (id -> category) and `traced_tests` (`t_ms`, `input`, `expected_result`, `expected_stated`, `category`); both required, validated (known ids, categories from the brief plus "Typical case"/"Other", `t_ms` in the log) with the existing retry. The message has a `<candidate_tests>` section; the system prompt tells the model to tag, report traced tests and reward stated expectations in Testing.
- Report JSON `testing`: `groups` (by category, verified or not except the next list), `ran_but_not_verified` (executed, no stated expectation), `missed_categories` (brief categories no test was filed under; revealed only here), `totals`. Report page shows "Your tests". Untagged executed tests default to "Other".
- Harness: `submit_report(executed=..., traced=[...])` and `traced(t, input, expected=..., category=...)`; tests in `tests/test_candidate_tests.py`.

**Notes for later tickets:**
- 07: `Submission`/`SUBMIT_REPORT_TOOL` now include the test fields; add new fields alongside. Metrics could use `extract_executed_tests` for "time to first test".
- A traced test's `t_ms` only has to exist in the log, not be a Candidate utterance. Executed outcomes are per statement only (no printed values).
- Review (code-review, medium): fixed the failing line now being the module-level traceback frame; spoken expectations looking only 30 s back (+5 s) with a stricter keyword list; old Reports without `testing` no longer crash the page; every extracted test must be filed exactly once; asserts/printed calls inside a called `main`/`test*` function are found; stdin counted only if the code reads input; duplicate category names collapsed; non-int `snapshot_seq` tolerated. Left: a spoken expectation still verifies every non-assert test of that Run; tests are deduplicated by statement text across Runs (a fixed failure shows its latest outcome); asserts nested in loops/ifs/other helper functions are not found; categories covered by unverified prints still count as covered.
