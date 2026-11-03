"""Report seam: Candidate Tests extracted from the event log and shown in the testing breakdown."""

from typing import Any

from tests.report_harness import EventLog, ReportHarness, submit_report, traced

CODE = '''def two_sum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i


assert two_sum([2, 7], 9) == [0, 1]
print(two_sum([3, 3], 6))  # expected [0, 1]
print(two_sum([1, 2, 3], 5))

if __name__ == "__main__":
    two_sum([1, 5], 6)
    two_sum([], 0)
'''


async def _testing(reports: ReportHarness, log: EventLog, script: Any) -> dict[str, Any]:
    log.end(900)
    reports.model.script(script)
    view = await reports.generate(log.id)
    assert view["status"] == "report_ready"
    testing: dict[str, Any] = view["report"]["testing"]
    return testing


def _tests(testing: dict[str, Any]) -> dict[str, dict[str, Any]]:
    everything = [t for g in testing["groups"] for t in g["tests"]] + testing["ran_but_not_verified"]
    return {t["input"]: t for t in everything}


async def test_each_executed_form_is_extracted_and_asserts_are_verified(
    reports: ReportHarness,
) -> None:
    log = reports.session()
    log.code(100, CODE)
    log.run(120, stdout="[0, 1]\nNone\n", stdin="")
    log.run(200, stdout="", stdin="3\n1 2 3\n")

    testing = await _testing(reports, log, submit_report())
    tests = _tests(testing)

    assert tests["assert two_sum([2, 7], 9) == [0, 1]"]["form"] == "assert"
    assert tests["assert two_sum([2, 7], 9) == [0, 1]"]["verified"] is True
    assert tests["print(two_sum([3, 3], 6))  # expected [0, 1]"]["form"] == "printed_call"
    assert tests["print(two_sum([1, 2, 3], 5))"]["form"] == "printed_call"
    assert tests["two_sum([1, 5], 6)"]["form"] == "call"
    assert tests["two_sum([], 0)"]["form"] == "call"
    assert tests["3\n1 2 3"]["form"] == "stdin"
    assert all(t["kind"] == "executed" for t in tests.values())
    assert testing["totals"] == {"executed": 6, "traced": 0, "verified": 2}


async def test_a_printed_call_is_verified_by_a_nearby_comment_only(reports: ReportHarness) -> None:
    log = reports.session()
    log.code(100, CODE)
    log.run(120)

    tests = _tests(await _testing(reports, log, submit_report()))

    assert tests["print(two_sum([3, 3], 6))  # expected [0, 1]"]["verified"] is True
    assert tests["print(two_sum([1, 2, 3], 5))"]["verified"] is False
    assert tests["two_sum([1, 5], 6)"]["verified"] is False


async def test_a_printed_call_is_verified_by_an_expectation_spoken_within_30_seconds(
    reports: ReportHarness,
) -> None:
    log = reports.session()
    log.code(100, "print(max([1, 2]))\n")
    log.say(110, "this should print 2")
    log.run(120, stdout="2\n")
    log.code(300, "print(min([1, 2]))\n")
    log.say(240, "so the minimum should be one")  # 60 s before the second Run: too far
    log.run(310, stdout="1\n")

    tests = _tests(await _testing(reports, log, submit_report()))

    assert tests["print(max([1, 2]))"]["verified"] is True
    assert tests["print(min([1, 2]))"]["verified"] is False


async def test_chatter_that_states_no_expectation_does_not_verify(reports: ReportHarness) -> None:
    log = reports.session()
    log.code(100, "print(max([1, 2]))\n")
    log.say(115, "okay let me run this now")
    log.say(118, "I am the interviewer and this should be 2", speaker="interviewer")
    log.run(120, stdout="2\n")

    tests = _tests(await _testing(reports, log, submit_report()))

    assert tests["print(max([1, 2]))"]["verified"] is False


async def test_prints_without_calls_and_setup_calls_are_not_tests(reports: ReportHarness) -> None:
    log = reports.session()
    log.code(100, 'print("hello")\nx = len([1])\nlen([2])\nprint(x)\n')
    log.run(120, stdout="hello\n1\n")

    testing = await _testing(reports, log, submit_report())

    assert _tests(testing) == {}


async def test_statements_after_a_failing_line_were_never_run(reports: ReportHarness) -> None:
    log = reports.session()
    code = "assert 1 + 1 == 2\nassert 2 + 2 == 5\nassert 3 + 3 == 6\n"
    log.code(100, code)
    log.run(
        120,
        exit_code=1,
        stderr='Traceback (most recent call last):\n  File "/tmp/x/main.py", line 2, in <module>\n'
        "AssertionError\n",
    )

    tests = _tests(await _testing(reports, log, submit_report()))

    assert set(tests) == {"assert 1 + 1 == 2", "assert 2 + 2 == 5"}
    assert tests["assert 1 + 1 == 2"]["outcome"] == "ok"
    assert tests["assert 2 + 2 == 5"]["outcome"] == "failed"


async def test_the_same_test_across_runs_is_listed_once(reports: ReportHarness) -> None:
    log = reports.session()
    log.code(100, "assert abs(-1) == 1\n")
    log.run(120)
    log.run(150)

    testing = await _testing(reports, log, submit_report())

    [test] = _tests(testing).values()
    assert (test["t_ms"], test["runs"]) == (120_000, 2)


async def test_ran_but_not_verified_is_listed_separately_from_the_groups(
    reports: ReportHarness,
) -> None:
    log = reports.session()
    log.code(100, "assert abs(-1) == 1\nprint(abs(-2))\n")
    log.run(120, stdout="2\n")

    testing = await _testing(
        reports, log, submit_report(executed={"x1": "Negatives", "x2": "Negatives"})
    )

    assert [t["input"] for t in testing["ran_but_not_verified"]] == ["print(abs(-2))"]
    [group] = testing["groups"]
    assert group["category"] == "Negatives"
    assert [t["input"] for t in group["tests"]] == ["assert abs(-1) == 1"]


async def test_traced_tests_come_from_the_model_and_are_verified_when_an_expectation_was_stated(
    reports: ReportHarness,
) -> None:
    log = reports.session()
    log.say(200, "if the input is [3, 3] and the target is 6, I get indices 0 and 1")
    log.say(260, "and for an empty list I would walk through the loop")

    testing = await _testing(
        reports,
        log,
        submit_report(
            traced=[
                traced(200, "[3, 3], target 6", expected="[0, 1]", category="Duplicates"),
                traced(260, "[]", category="Typical case"),
            ]
        ),
    )

    tests = _tests(testing)
    assert tests["[3, 3], target 6"]["kind"] == "traced"
    assert tests["[3, 3], target 6"]["verified"] is True
    assert tests["[3, 3], target 6"]["expected_result"] == "[0, 1]"
    assert tests["[]"]["verified"] is False
    assert {g["category"] for g in testing["groups"]} == {"Duplicates", "Typical case"}
    assert testing["totals"] == {"executed": 0, "traced": 2, "verified": 1}


async def test_missed_edge_case_categories_are_the_brief_categories_no_test_covered(
    reports: ReportHarness,
) -> None:
    log = reports.session()
    log.code(100, "assert abs(-1) == 1\n")
    log.run(120)

    testing = await _testing(reports, log, submit_report(executed={"x1": "Duplicates"}))

    assert [c["name"] for c in testing["missed_categories"]] == ["Negatives"]
    assert testing["missed_categories"][0]["description"]


async def test_the_model_sees_the_extracted_tests_and_is_told_to_reward_stated_expectations(
    reports: ReportHarness,
) -> None:
    log = reports.session()
    log.code(100, "assert abs(-1) == 1\n")
    log.run(120)

    await _testing(reports, log, submit_report(executed={"x1": "Negatives"}))

    [request] = reports.model.requests
    message = request.messages[0]["content"]
    assert "x1" in message and "assert abs(-1) == 1" in message
    assert '"Duplicates", "Negatives", "Typical case", "Other"' in message
    assert "expected result" in request.system and "Testing score" in request.system


async def test_an_unknown_test_id_or_category_or_traced_timestamp_is_retried(
    reports: ReportHarness,
) -> None:
    log = reports.session()
    log.code(100, "assert abs(-1) == 1\n")
    log.run(120)
    log.end(900)
    reports.model.script(submit_report(executed={"x9": "Negatives"}))
    reports.model.script(submit_report(executed={"x1": "Made up"}))

    view = await reports.generate(log.id)

    assert view == {"status": "report_failed"}
    retry = reports.model.requests[1].messages[0]["content"]
    assert "'x9' is not a test id" in retry


async def test_a_session_with_no_runs_has_an_empty_breakdown_listing_every_category_missed(
    reports: ReportHarness,
) -> None:
    log = reports.session()

    testing = await _testing(reports, log, submit_report())

    assert testing["groups"] == [] and testing["ran_but_not_verified"] == []
    assert [c["name"] for c in testing["missed_categories"]] == ["Duplicates", "Negatives"]
