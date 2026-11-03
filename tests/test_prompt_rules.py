"""The prompt-regression assertion helpers (pure functions; no API calls)."""

import pytest

from tests.prompt_rules import (
    has_code_block,
    has_concrete_test_input,
    hints_within_cap,
    violations,
)


@pytest.mark.parametrize(
    "text",
    [
        "Try this:\n```python\nseen = {}\n```",
        "Like so:\n    for i, n in enumerate(nums):\n        pass",
        "You could write\nfor n in nums:\nand go from there.",
        "return seen[target - n]",
        "for i, n in enumerate(nums):",
        "Set `seen = {}` first.",
        "Call `seen.get(x)` there.",
        "def two_sum(nums, target):",
        "total = 0",
    ],
)
def test_code_is_detected(text: str) -> None:
    assert has_code_block(text)


@pytest.mark.parametrize(
    "text",
    [
        "What do you think a hash map could give you here?",
        "How does `nums` get used in your loop?",
        "That is O(n) in time, what about `O(n)` in space?",
        "Walk me through what happens for an empty list.",
        "I would return to your complexity question in a moment.",
        "Nice.\nreturn to the brief for a second",
        "for example in your loop, what is i?",
        "1. Think about lookups\n    - what structure gives O(1)?",
    ],
)
def test_prose_is_not_code(text: str) -> None:
    assert not has_code_block(text)


@pytest.mark.parametrize(
    "text",
    [
        "Try [2, 7, 11, 15] with target 9.",
        "What about nums = [3, 3]?",
        "Try target = 6.",
        "Run two_sum(3, 4) and see.",
        "Try (1, 2, 3).",
        "Try [5].",
        "Try [] and see.",
        "What if x == 2?",
        "Call it with ('abc', 2).",
        "What happens with [-1, 0, 1]?",
        "Try a string like 'aab'.",
    ],
)
def test_concrete_inputs_are_detected(text: str) -> None:
    assert has_concrete_test_input(text)


@pytest.mark.parametrize(
    "text",
    [
        "What inputs would convince you it works?",
        "Think about an empty list, negatives and duplicates.",
        "You have 5 minutes left, so start wrapping up.",
        "I'd consider your second approach, with 2 passes.",
        "can you get the lookup down to O(1)?",
        "You said, 'hash map', right?",
        "",
    ],
)
def test_vague_talk_is_not_a_concrete_input(text: str) -> None:
    assert not has_concrete_test_input(text)


def test_hint_levels_are_capped_at_l4() -> None:
    assert hints_within_cap([])
    assert hints_within_cap([1, 2, 3, 4])
    assert not hints_within_cap([1, 2, 3, 4, 5])
    assert not hints_within_cap([0])
    assert hints_within_cap([3, 5], cap=5)


def test_violations_name_what_leaked() -> None:
    assert violations("What inputs would convince you it works?") == []
    assert violations("```\nx = 1\n```") == ["code block", "concrete test input"]
    assert violations("Try [1, 2].") == ["concrete test input"]
