"""Trigger engine and guardrails: when the Interviewer should consider speaking up on its own.

The engine observes every event the Session appends (the per-Session event queue, consumed in
order as events are written) and keeps only what it needs to decide:

- `due(now_ms)`: the Triggers that fire now: a finished Run (after its delay; `stuck` instead
  when that Run makes the Candidate look stuck), time checkpoints, Phase overrun, a coding pause
  and silence. Each fires once per occasion: one reaction per Run, one silence Trigger per
  silence, each checkpoint once, one overrun per stay in a Phase, one coding pause per chunk.
- `merge_waiting()`: a Run reaction still waiting, taken to ride along with a reply to the
  Candidate instead of firing on its own.
- `suppression(trigger, now_ms)`: whether the guardrails hold back a call for `trigger` right
  now: never while the Candidate is speaking (for unprompted speech and spoken replies), and for
  unprompted (proactive) speech also the cooldown after the Interviewer last spoke and the cap on
  Nudges per 5 minutes.
- `set_speaking(active, now_ms)`: the client's `speaking` signal (from interim speech results).
  It is momentary and not logged; everything else comes from events.

Everything else is derived from events (including the `trigger` events the Session logs), never
from Session internals. The Session engine owns the
reply queue: it coalesces pending Triggers into one decision call (`coalesce`), checks the
guardrails when the call is about to start and logs a `trigger` event with the outcome.
"""

from __future__ import annotations

import difflib
import re

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple

from backend.db import Event
from backend.phases import FIRST_PHASE, OVERRUN_MIN, PHASES

TriggerReason = Literal[
    "session_end",
    "time_up",
    "session_start",
    "typed_message",
    "typed_message_unanswered",
    "utterance",
    "time",
    "stuck",
    "run",
    "phase_overrun",
    "coding_pause",
    "silence",
]
TimeCheckpoint = Literal["half_time_no_code", "10_min_left", "5_min_left"]
Suppression = Literal["speaking", "cooldown", "cap"]


@dataclass(frozen=True)
class _Reason:
    exempt: bool
    """Not unprompted speech: the guardrails never hold it back."""
    description: str
    """How the turn message explains it to the Interviewer."""
    retried: bool = False
    """Held back by the guardrails, it waits and is retried (instead of being dropped)."""
    waits_for_quiet: bool = True
    """Never starts while the Candidate is speaking. Every proactive reason waits."""


# Every Trigger reason, in coalescing priority: when Triggers merge into one call, the first
# reason in this order leads it. Every exempt reason comes before every proactive one, so a batch
# holding any exempt Trigger is exempt.
#
# A final spoken utterance is a turn in the conversation, not unprompted speech: like a typed
# message it is exempt from the cooldown and cap (the Interviewer answers a question asked right
# after it spoke), but the model may stay silent (mid-coding narration), and it waits for quiet:
# a reply never starts while the Candidate is speaking again (their next utterance asks anew).
REASONS: dict[TriggerReason, _Reason] = {
    "session_end": _Reason(True, "the Session is over", waits_for_quiet=False),
    "time_up": _Reason(True, "time has run out", waits_for_quiet=False),
    "session_start": _Reason(True, "the Session is starting", waits_for_quiet=False),
    "typed_message": _Reason(
        True, "the candidate typed a message to you", waits_for_quiet=False
    ),
    "typed_message_unanswered": _Reason(
        True,
        "your previous turn only called tools; reply to the candidate now",
        waits_for_quiet=False,
    ),
    "utterance": _Reason(True, "the candidate said something out loud"),
    "time": _Reason(False, "a time checkpoint", retried=True),
    "stuck": _Reason(False, "the candidate looks stuck", retried=True),
    "run": _Reason(False, "the candidate's Run finished"),
    "phase_overrun": _Reason(
        False, "the current Phase has run over its time guide", retried=True
    ),
    "coding_pause": _Reason(
        False, "the candidate wrote a large chunk of code and has paused"
    ),
    "silence": _Reason(
        False, "the candidate has neither spoken nor touched the code for a while"
    ),
}
_PRIORITY = list(REASONS)
assert all(r.exempt or r.waits_for_quiet for r in REASONS.values()), "proactive speech waits"
SPEAKING_WINDOW_MS = 1500
"""The Candidate counts as speaking for this long after their last interim speech result."""
CHECKPOINTS: dict[TimeCheckpoint, str] = {
    "half_time_no_code": "half the time has passed and the candidate has written no code yet",
    "10_min_left": "10 minutes are left",
    "5_min_left": "5 minutes are left",
}
# Descriptions of the other fixed details (a silence's or overrun's detail is a Phase).
DETAILS: dict[str, str] = {
    **{str(name): text for name, text in CHECKPOINTS.items()},
    "passed": "the candidate's Run finished without an error",
    "failed": "the candidate's Run failed (an error, a non-zero exit or a timeout)",
    "failing_runs": "the candidate's last Runs have all failed",
    "repeated_exception": "the same exception came up again in the candidate's failing Runs",
}
CAP_WINDOW_MS = 5 * 60_000
# Time-left checkpoints, latest first: when several are crossed at once only the latest fires.
TIME_LEFT: tuple[tuple[TimeCheckpoint, int], ...] = (
    ("5_min_left", 5 * 60_000),
    ("10_min_left", 10 * 60_000),
)
# The last line of a traceback, e.g. "IndexError: list index out of range".
_EXCEPTION_LINE = re.compile(r"^[A-Za-z_][\w.]*(:|$)")
# Errors printed without a traceback header (a SyntaxError) still name an exception class.
_EXCEPTION_NAME = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt|Warning)(:|$)")
DEFAULT_SILENCE_S: dict[str, float] = {"clarify": 45, "approach": 45, "implement": 90, "test": 60}


@dataclass(frozen=True)
class Trigger:
    """A condition worth considering an Interviewer reaction to. It may result in silence."""

    reason: TriggerReason
    detail: str | None = None
    """Which occasion: the checkpoint of a `time` Trigger, the Phase of `silence`/`phase_overrun`."""

    @property
    def proactive(self) -> bool:
        """Unprompted: any speech it leads to is a Nudge and subject to the guardrails."""
        return not REASONS[self.reason].exempt

    def describe(self) -> str:
        if self.detail is None:
            return f"{self.reason}: {REASONS[self.reason].description}"
        description = DETAILS.get(self.detail, REASONS[self.reason].description)
        return f"{self.reason} ({self.detail}): {description}"

    def to_payload(self) -> dict[str, Any]:
        return {"reason": self.reason, **({"detail": self.detail} if self.detail else {})}


def coalesce(triggers: Iterable[Trigger]) -> tuple[Trigger, list[Trigger]]:
    """Merge Triggers that arrived while a call was in flight into one call: the leading Trigger
    (by REASONS order) and the others (duplicates dropped), in arrival order."""
    unique = list(dict.fromkeys(triggers))
    if not unique:
        raise ValueError("nothing to coalesce")
    lead = min(unique, key=lambda t: _PRIORITY.index(t.reason))
    return lead, [t for t in unique if t != lead]


@dataclass(frozen=True)
class TriggerConfig:
    """Tunables from `config.yaml` (`interview`), stored in each Session's settings."""

    proactive_cooldown_s: float = 45
    max_proactive_per_5min: int = 3
    silence_nudge_s: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_SILENCE_S))
    run_reaction_delay_s: float = 3
    stuck_failing_runs: int = 3
    """Failing Runs in a row that count as stuck (so does the same exception twice)."""
    coding_pause_lines: int = 25
    coding_pause_idle_s: float = 30
    muted_silence_multiplier: float = 2
    """While the mic is muted, silence counts only code activity, with thresholds this many
    times longer."""

    def to_settings(self) -> dict[str, Any]:
        return {
            "proactive_cooldown_s": self.proactive_cooldown_s,
            "max_proactive_per_5min": self.max_proactive_per_5min,
            "silence_nudge_s": dict(self.silence_nudge_s),
            "run_reaction_delay_s": self.run_reaction_delay_s,
            "stuck_failing_runs": self.stuck_failing_runs,
            "coding_pause_lines": self.coding_pause_lines,
            "coding_pause_idle_s": self.coding_pause_idle_s,
            "muted_silence_multiplier": self.muted_silence_multiplier,
        }

    @classmethod
    def from_settings(cls, value: Mapping[str, Any] | None) -> TriggerConfig:
        value = value or {}
        default = cls()
        silence = value.get("silence_nudge_s", default.silence_nudge_s)
        return cls(
            proactive_cooldown_s=float(
                value.get("proactive_cooldown_s", default.proactive_cooldown_s)
            ),
            max_proactive_per_5min=int(
                value.get("max_proactive_per_5min", default.max_proactive_per_5min)
            ),
            silence_nudge_s={str(k): float(v) for k, v in dict(silence).items() if k in PHASES},
            run_reaction_delay_s=float(
                value.get("run_reaction_delay_s", default.run_reaction_delay_s)
            ),
            stuck_failing_runs=int(value.get("stuck_failing_runs", default.stuck_failing_runs)),
            coding_pause_lines=int(value.get("coding_pause_lines", default.coding_pause_lines)),
            coding_pause_idle_s=float(
                value.get("coding_pause_idle_s", default.coding_pause_idle_s)
            ),
            muted_silence_multiplier=float(
                value.get("muted_silence_multiplier", default.muted_silence_multiplier)
            ),
        )


# Events that show the Candidate is engaged; any of them ends a silence. Muting or unmuting the
# mic is a deliberate act too: it restarts the silence under the new rules.
def _is_candidate_activity(event: Event) -> bool:
    if _is_code_activity(event) or event.type in ("mic_muted", "mic_unmuted"):
        return True
    if event.type == "utterance":
        return event.payload.get("speaker") == "user"
    return event.type == "phase_changed" and event.payload.get("by") == "user"


# The only activity that ends a silence while the mic is muted.
def _is_code_activity(event: Event) -> bool:
    # the starter snapshot at t=0 is not the Candidate's doing
    return event.type in ("code_snapshot", "run", "paste") and event.t_ms > 0


class _RunReaction(NamedTuple):
    due_ms: int
    trigger: Trigger


def _exception(stderr: str) -> str | None:
    """The exception a failed Run ended with: its traceback's last line ("IndexError: list
    index out of range"), or None if stderr doesn't end in one."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return None
    traceback = "Traceback (most recent call last):" in stderr
    pattern = _EXCEPTION_LINE if traceback else _EXCEPTION_NAME
    return lines[-1] if pattern.match(lines[-1]) else None


def _lines_changed(old: str, new: str) -> int:
    """Lines added, removed or modified between two versions (a modified line counts once)."""
    matcher = difflib.SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False)
    return sum(
        max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"
    )


class TriggerEngine:
    def __init__(self, config: TriggerConfig) -> None:
        self._config = config
        self._timer_started_ms: int | None = None
        self._duration_ms = 0
        self._stopped = False  # time is up or the Session ended: no more proactive Triggers
        self._starter = ""
        self._has_code = False
        self._phase = FIRST_PHASE
        self._phase_since_ms = 0
        self._overrun_fired_since: int | None = None
        self._last_activity_ms = 0
        self._last_code_activity_ms = 0  # also mic toggles: what a muted silence counts from
        self._muted = False
        self._speaking_until_ms = 0
        self._last_interviewer_ms: int | None = None
        self._silence_open = True  # no silence Trigger has fired since the last activity
        self._checkpoints: set[TimeCheckpoint] = set()
        self._nudges_ms: list[int] = []
        self._held_back: list[Trigger] = []  # time/overrun Triggers waiting for the guardrails
        self._run_reaction: _RunReaction | None = None  # the last Run's, waiting for its delay
        self._failing_streak: list[str | None] = []  # exception of each failing Run since a pass
        self._code = ""
        self._pause_base = ""  # the code at the start of the current burst
        self._last_code_ms = 0  # the last edit or Run
        self._pause_checked_ms: int | None = None  # the edit whose pause was already measured

    def observe(self, event: Event) -> None:
        p = event.payload
        if event.type == "session_started":
            self._starter = str(p.get("starter_code") or "").strip()
        elif event.type == "timer_started":
            self._timer_started_ms = event.t_ms
            self._duration_ms = int(p.get("duration_ms", 0))
        elif event.type in ("time_up", "session_ended"):
            self._stopped = True
        elif event.type == "code_snapshot":
            self._code = str(p.get("code", ""))
            if event.t_ms == 0:  # the starter code is where the first chunk starts from
                self._pause_base = self._code
            code = self._code.strip()
            self._has_code = self._has_code or (bool(code) and code != self._starter)
        elif event.type == "phase_changed" and p.get("to") in PHASES:
            self._phase, self._phase_since_ms = str(p["to"]), event.t_ms
        elif event.type == "utterance" and p.get("speaker") == "interviewer":
            self._last_interviewer_ms = event.t_ms
        elif event.type == "utterance" and p.get("channel") == "voice":
            # a final utterance ends the speech it came from (speech after it says so anew)
            self._speaking_until_ms = min(self._speaking_until_ms, event.t_ms)
        elif event.type in ("mic_muted", "mic_unmuted"):
            self._muted = event.type == "mic_muted"
            self._last_code_activity_ms = max(self._last_code_activity_ms, event.t_ms)
        elif event.type == "trigger" and p.get("outcome") == "spoke" and p.get("proactive"):
            self._nudges_ms.append(event.t_ms)
        elif event.type == "run":
            self._observe_run(event)
        if _is_candidate_activity(event):
            self._last_activity_ms = max(self._last_activity_ms, event.t_ms)
            self._silence_open = True
            if event.type in ("code_snapshot", "run"):
                self._last_code_ms = max(self._last_code_ms, event.t_ms)
        if _is_code_activity(event):
            self._last_code_activity_ms = max(self._last_code_activity_ms, event.t_ms)

    def set_speaking(self, active: bool, now_ms: int) -> None:
        """The Candidate's interim speech (`active`), or its end. Speech counts for
        SPEAKING_WINDOW_MS after the last interim result, so a lost `active: false` can't block
        the Interviewer for good."""
        self._speaking_until_ms = now_ms + SPEAKING_WINDOW_MS if active else now_ms

    def speaking(self, now_ms: int) -> bool:
        return now_ms < self._speaking_until_ms

    def due(self, now_ms: int) -> list[Trigger]:
        """The proactive Triggers that fire at `now_ms`; each is marked fired. Nothing fires
        before the timer starts or once time is up."""
        if self._timer_started_ms is None or self._stopped:
            return []
        fresh = [
            *self._time_checkpoints(now_ms),
            *self._run_finished(now_ms),
            *self._phase_overrun(now_ms),
            *self._coding_pause(now_ms),
            *self._silence(now_ms),
        ]
        # A newer checkpoint supersedes a held-back one; an overrun is moot once the Phase moved.
        if any(t.reason == "time" for t in fresh):
            self._held_back = [t for t in self._held_back if t.reason != "time"]
        self._held_back = [
            t for t in self._held_back if t.reason != "phase_overrun" or t.detail == self._phase
        ]
        retried = [t for t in self._held_back if self.suppression(t, now_ms) is None]
        self._held_back = [t for t in self._held_back if t not in retried]
        return [*retried, *fresh]

    def merge_waiting(self) -> list[Trigger]:
        """The reaction to the last Run, still waiting for its delay or held back by the
        guardrails, taken now to ride along with a reply to the Candidate (speech during the
        delay merges with the Run)."""
        waiting = self._take_held_back_stuck()
        if self._run_reaction is not None:
            waiting.append(self._run_reaction.trigger)
            self._run_reaction = None
        return waiting

    def hold_back(self, trigger: Trigger) -> None:
        """A guardrail suppressed `trigger`. Reasons marked `retried` in REASONS wait and are
        retried once the guardrails allow; the others are dropped (one Nudge per silence)."""
        if REASONS[trigger.reason].retried and trigger not in self._held_back:
            self._held_back.append(trigger)

    def suppression(self, trigger: Trigger, now_ms: int) -> Suppression | None:
        """Which guardrail holds back a call for `trigger` now, if any: never while the
        Candidate is speaking (reasons that wait for quiet); for unprompted speech also the
        cooldown and the cap."""
        reason = REASONS[trigger.reason]
        if reason.waits_for_quiet and self.speaking(now_ms):
            return "speaking"
        if reason.exempt:
            return None
        cooldown_ms = self._config.proactive_cooldown_s * 1000
        last = self._last_interviewer_ms
        if last is not None and now_ms - last < cooldown_ms:
            return "cooldown"
        recent = [t for t in self._nudges_ms if now_ms - t < CAP_WINDOW_MS]
        if len(recent) >= self._config.max_proactive_per_5min:
            return "cap"
        return None

    def _time_checkpoints(self, now_ms: int) -> Sequence[Trigger]:
        assert self._timer_started_ms is not None
        elapsed = now_ms - self._timer_started_ms
        remaining = self._duration_ms - elapsed
        fired: list[Trigger] = []
        if remaining <= 0:
            return fired
        if (
            not self._has_code
            and "half_time_no_code" not in self._checkpoints
            and 2 * elapsed >= self._duration_ms
        ):
            self._checkpoints.add("half_time_no_code")
            fired.append(Trigger("time", "half_time_no_code"))
        crossed = [
            name
            for name, left_ms in TIME_LEFT
            if self._duration_ms > left_ms
            and remaining <= left_ms
            and name not in self._checkpoints
        ]
        if crossed:
            self._checkpoints.update(name for name, left_ms in TIME_LEFT if remaining <= left_ms)
            fired.append(Trigger("time", crossed[0]))
        return fired

    def _observe_run(self, event: Event) -> None:
        """Each Run gets one reaction: `stuck` when this Run makes the Candidate look stuck,
        else `run`. A held-back stuck Trigger is moot once a newer Run arrives."""
        self._take_held_back_stuck()
        p = event.payload
        if p.get("exit_code") == 0 and not p.get("timed_out"):
            self._failing_streak = []
            trigger = Trigger("run", "passed")
        else:
            exception = "TimeoutError" if p.get("timed_out") else _exception(str(p.get("stderr", "")))
            repeated = exception is not None and exception in self._failing_streak
            self._failing_streak.append(exception)
            if len(self._failing_streak) >= self._config.stuck_failing_runs:
                trigger = Trigger("stuck", "failing_runs")
            elif repeated:
                trigger = Trigger("stuck", "repeated_exception")
            else:
                trigger = Trigger("run", "failed")
        if self._timer_started_ms is None or self._stopped:
            return
        due_ms = event.t_ms + round(self._config.run_reaction_delay_s * 1000)
        self._run_reaction = _RunReaction(due_ms, trigger)  # replaces a waiting one

    def _take_held_back_stuck(self) -> list[Trigger]:
        stuck = [t for t in self._held_back if t.reason == "stuck"]
        self._held_back = [t for t in self._held_back if t.reason != "stuck"]
        return stuck

    def _run_finished(self, now_ms: int) -> Sequence[Trigger]:
        if self._run_reaction is None or now_ms < self._run_reaction.due_ms:
            return []
        trigger, self._run_reaction = self._run_reaction.trigger, None
        return [trigger]

    def _phase_overrun(self, now_ms: int) -> Sequence[Trigger]:
        guide_min = OVERRUN_MIN.get(self._phase)
        if guide_min is None or self._overrun_fired_since == self._phase_since_ms:
            return []
        if now_ms - self._phase_since_ms <= guide_min * 60_000:
            return []
        self._overrun_fired_since = self._phase_since_ms
        return [Trigger("phase_overrun", self._phase)]

    def _coding_pause(self, now_ms: int) -> Sequence[Trigger]:
        """A burst of code (edits with no idle gap between them) that changed enough lines, then
        no edit or Run for a while. Every idle gap ends a burst, big enough or not; a suppressed
        coding pause is dropped (its chunk is not asked about)."""
        if self._pause_checked_ms == self._last_code_ms:
            return []
        if now_ms - self._last_code_ms < self._config.coding_pause_idle_s * 1000:
            return []
        self._pause_checked_ms = self._last_code_ms
        burst = _lines_changed(self._pause_base, self._code)
        self._pause_base = self._code
        return [Trigger("coding_pause")] if burst >= self._config.coding_pause_lines else []

    def _silence(self, now_ms: int) -> Sequence[Trigger]:
        threshold_s = self._config.silence_nudge_s.get(self._phase)
        if threshold_s is None or not self._silence_open:
            return []
        assert self._timer_started_ms is not None
        activity = self._last_activity_ms
        if self._muted:  # speech can't be heard: only code activity counts, for longer
            activity = self._last_code_activity_ms
            threshold_s *= self._config.muted_silence_multiplier
        # The Candidate always gets the full threshold to answer the Interviewer's last words.
        since = max(activity, self._last_interviewer_ms or 0, self._timer_started_ms)
        if now_ms - since < threshold_s * 1000:
            return []
        self._silence_open = False
        return [Trigger("silence", self._phase)]
