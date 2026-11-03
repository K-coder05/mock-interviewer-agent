"""The rubric and the Overall Signal.

The model scores each dimension 1-4 with evidence; the Overall Signal is derived here, in code,
from the weighted scores alone (same scores -> same signal), so it is consistent across
regenerations. The model only writes the one-line rationale.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

SignalLabel = Literal["Strong No", "No", "Lean No", "Lean Hire", "Hire", "Strong Hire"]


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    strong: str
    """What a 4 looks like."""
    weight: int = 1


DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        "problem_understanding",
        "Problem understanding",
        "Restated the problem, asked about input size, constraints and edge cases before designing.",
    ),
    Dimension(
        "approach",
        "Approach and algorithm",
        "Gave brute force first, then reasoned to optimal; explained trade-offs.",
    ),
    Dimension(
        "communication",
        "Communication",
        "Kept up a think-aloud; the interviewer could always follow the reasoning.",
    ),
    Dimension(
        "code_quality",
        "Code quality",
        "Readable names, sensible decomposition, idiomatic Python.",
    ),
    Dimension(
        "correctness",
        "Correctness",
        "Final code is correct for all edge-case categories in the brief (assessed by reading "
        "the code, not by executing it).",
    ),
    Dimension(
        "testing",
        "Testing and self-validation",
        "Chose tests without being prompted, stated expected results, covered normal + edge + "
        "adversarial cases, traced by hand before running, fixed what the tests found.",
        weight=2,
    ),
    Dimension(
        "complexity",
        "Complexity analysis",
        "Stated time/space correctly, unprompted, for the final solution.",
    ),
    Dimension(
        "coachability",
        "Coachability and hints",
        "Used hints well; few needed (Probes don't count as hints).",
    ),
    Dimension(
        "time_management",
        "Time management",
        "Phases fit the time limit, with room left for testing.",
    ),
)

DIMENSION_KEYS = tuple(d.key for d in DIMENSIONS)

# Upper bounds (exclusive) of the weighted average for each label; above the last is Strong Hire.
THRESHOLDS: tuple[tuple[Fraction, SignalLabel], ...] = (
    (Fraction("1.75"), "Strong No"),
    (Fraction("2.25"), "No"),
    (Fraction("2.6"), "Lean No"),
    (Fraction("3.0"), "Lean Hire"),
    (Fraction("3.5"), "Hire"),
)
LABELS: tuple[SignalLabel, ...] = (
    "Strong No", "No", "Lean No", "Lean Hire", "Hire", "Strong Hire"
)
CAP: SignalLabel = "No"
"""A 1 in any of CAPPING_DIMENSIONS caps the signal here."""
CAPPING_DIMENSIONS = ("testing", "correctness")


@dataclass(frozen=True)
class Signal:
    label: SignalLabel
    weighted_average: Fraction
    capped: bool
    """True when the cap lowered the label."""


def overall_signal(scores: Mapping[str, int]) -> Signal:
    """The Overall Signal from one 1-4 score per rubric dimension."""
    total = sum(d.weight * scores[d.key] for d in DIMENSIONS)
    average = Fraction(total, sum(d.weight for d in DIMENSIONS))
    label: SignalLabel = "Strong Hire"
    for bound, candidate in THRESHOLDS:
        if average < bound:
            label = candidate
            break
    capped = False
    if any(scores[k] == 1 for k in CAPPING_DIMENSIONS) and LABELS.index(label) > LABELS.index(CAP):
        label, capped = CAP, True
    return Signal(label=label, weighted_average=average, capped=capped)
