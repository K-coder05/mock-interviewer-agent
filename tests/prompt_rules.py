"""Pure assertion helpers for the prompt-regression suite (`tests/test_prompt_regression.py`).

They judge Interviewer output text and the logged Hint levels, with no model and no I/O, so
their own tests (`tests/test_prompt_rules.py`) run in the default test run. The detectors are
deliberately simple heuristics: they look for the shapes a leaked solution takes (a code block,
a statement of Python, a literal input), not for every possible leak.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MAX_HINT_LEVEL = 4

_FENCE = re.compile(r"```|~~~")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_PYTHON_STATEMENT = re.compile(
    r"^\s*(?:def |class |for \w+ in |while .+:|if .+:|elif .+:|else:|return\b|import |from \w+ import |"
    r"\w+(?:\[[^\]]*\])?\s*[-+*/]?=\s*\S)",
    re.MULTILINE,
)
_INDENTED_LINE = re.compile(r"^(?: {4}|\t)\S", re.MULTILINE)
# What makes an inline span code rather than a term such as `nums` or `O(n)`.
_CODE_SPAN = re.compile(r"[=\[\]{}]|\w\(.*\)|\bin\b|\breturn\b")

_NUMBER = r"-?\d+(?:\.\d+)?"
_NUMBER_COLLECTION = re.compile(rf"[\[({{]\s*{_NUMBER}(?:\s*,\s*{_NUMBER})+\s*[\])}}]")
_STRING_LITERAL_ARG = re.compile(r"""[(\[,]\s*["'][^"']*["']\s*[,)\]]""")
_ASSIGNED_VALUE = re.compile(rf"""\b\w+\s*=\s*(?:{_NUMBER}|\[|["'])""")
_CALL_WITH_NUMBERS = re.compile(rf"\b\w+\(\s*{_NUMBER}(?:\s*,\s*{_NUMBER})*\s*\)")
_STRING_INPUT = re.compile(r"""\b(?:input|string|s)\s+(?:like|such as|of|=)\s+["'][^"']+["']""", re.I)


def has_code_block(text: str) -> bool:
    """A fenced block, a run of indented lines, a line that is a Python statement, or an inline
    `code span` that is more than a bare identifier (`nums`) or a complexity (`O(n)`)."""
    if _FENCE.search(text) or _INDENTED_LINE.search(text) or _PYTHON_STATEMENT.search(text):
        return True
    return any(
        _CODE_SPAN.search(span) and not re.fullmatch(r"[OΘ]\([^)]*\)", span.strip())
        for span in _INLINE_CODE.findall(text)
    )


def has_concrete_test_input(text: str) -> bool:
    """A literal input the Candidate could type: a list of numbers (`[2, 7, 11]`), an assigned
    value (`target = 9`), a call with numeric arguments (`f(3, 4)`) or a quoted string argument.
    Saying "an empty list" or "negative numbers" is not concrete."""
    return any(
        pattern.search(text)
        for pattern in (
            _NUMBER_COLLECTION,
            _ASSIGNED_VALUE,
            _CALL_WITH_NUMBERS,
            _STRING_LITERAL_ARG,
            _STRING_INPUT,
        )
    )


def hints_within_cap(levels: Iterable[int], cap: int = MAX_HINT_LEVEL) -> bool:
    """Every Hint level is an integer from 1 to `cap` (L4, a concrete next step, is the ceiling)."""
    return all(1 <= level <= cap for level in levels)


def violations(text: str) -> list[str]:
    """What is wrong with one Interviewer utterance, as short labels (empty when it is fine)."""
    found = []
    if has_code_block(text):
        found.append("code block")
    if has_concrete_test_input(text):
        found.append("concrete test input")
    return found
