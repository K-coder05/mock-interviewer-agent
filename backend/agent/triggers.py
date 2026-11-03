"""Trigger engine and guardrails: when the Interviewer should consider speaking up on its own.

The engine observes every event the Session appends (the per-Session event queue, consumed in
order as events are written) and keeps only what it needs to decide:

- `due(now_ms)`: the time-based Triggers that fire now (silence, time checkpoints, Phase overrun).
  Each fires once per occasion: one silence Trigger per silence, each checkpoint once, one overrun
  per stay in a Phase.
- `suppression(now_ms)`: whether the guardrails hold back an unprompted (proactive) utterance
  right now: the cooldown after the Interviewer last spoke, and the cap on Nudges per 5 minutes.

Everything is derived from events (including the `trigger` events the Session logs), never from
Session internals. The Session engine owns the
reply queue: it coalesces pending Triggers into one decision call (`coalesce`), checks the
guardrails when the call is about to start and logs a `trigger` event with the outcome.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from backend.db import Event
from backend.phases import FIRST_PHASE, OVERRUN_MIN, PHASES

TriggerReason = Literal[
    "session_end",
    "time_up",
    "session_start",
    "typed_message",
    "typed_message_unanswered",
    "time",
    "phase_overrun",
    "silence",
]
TimeCheckpoint = Literal["half_time_no_code", "10_min_left", "5_min_left"]
Suppression = Literal["cooldown", "cap"]


@dataclass(frozen=True)
class _Reason:
    exempt: bool
    """Not unprompted speech: the guardrails never hold it back."""
    description: str
    """How the turn message explains it to the Interviewer."""


# Every Trigger reason, in coalescing priority: when Triggers merge into one call, the first
# reason in this order leads it. Every exempt reason comes before every proactive one, so a batch
# holding any exempt Trigger is exempt.
REASONS: dict[TriggerReason, _Reason] = {
    "session_end": _Reason(True, "the Session is over"),
    "time_up": _Reason(True, "time has run out"),
    "session_start": _Reason(True, "the Session is starting"),
    "typed_message": _Reason(True, "the candidate typed a message to you"),
    "typed_message_unanswered": _Reason(
        True, "your previous turn only called tools; reply to the candidate now"
    ),
    "time": _Reason(False, "a time checkpoint"),
    "phase_overrun": _Reason(False, "the current Phase has run over its time guide"),
    "silence": _Reason(
        False, "the candidate has neither spoken nor touched the code for a while"
    ),
}
_PRIORITY = list(REASONS)
CHECKPOINTS: dict[TimeCheckpoint, str] = {
    "half_time_no_code": "half the time has passed and the candidate has written no code yet",
    "10_min_left": "10 minutes are left",
    "5_min_left": "5 minutes are left",
}
CAP_WINDOW_MS = 5 * 60_000
# Time-left checkpoints, latest first: when several are crossed at once only the latest fires.
TIME_LEFT: tuple[tuple[TimeCheckpoint, int], ...] = (
    ("5_min_left", 5 * 60_000),
    ("10_min_left", 10 * 60_000),
)
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
        description = CHECKPOINTS.get(self.detail, REASONS[self.reason].description)  # type: ignore[call-overload]
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

    def to_settings(self) -> dict[str, Any]:
        return {
            "proactive_cooldown_s": self.proactive_cooldown_s,
            "max_proactive_per_5min": self.max_proactive_per_5min,
            "silence_nudge_s": dict(self.silence_nudge_s),
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
        )


# Events that show the Candidate is engaged; any of them ends a silence.
def _is_candidate_activity(event: Event) -> bool:
    if event.type in ("code_snapshot", "run", "paste"):
        return event.t_ms > 0  # the starter snapshot at t=0 is not the Candidate's doing
    if event.type == "utterance":
        return event.payload.get("speaker") == "user"
    return event.type == "phase_changed" and event.payload.get("by") == "user"


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
        self._last_interviewer_ms: int | None = None
        self._silence_open = True  # no silence Trigger has fired since the last activity
        self._checkpoints: set[TimeCheckpoint] = set()
        self._nudges_ms: list[int] = []
        self._held_back: list[Trigger] = []  # time/overrun Triggers waiting for the guardrails

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
            code = str(p.get("code", "")).strip()
            self._has_code = self._has_code or (bool(code) and code != self._starter)
        elif event.type == "phase_changed" and p.get("to") in PHASES:
            self._phase, self._phase_since_ms = str(p["to"]), event.t_ms
        elif event.type == "utterance" and p.get("speaker") == "interviewer":
            self._last_interviewer_ms = event.t_ms
        elif event.type == "trigger" and p.get("outcome") == "spoke" and p.get("proactive"):
            self._nudges_ms.append(event.t_ms)
        if _is_candidate_activity(event):
            self._last_activity_ms = max(self._last_activity_ms, event.t_ms)
            self._silence_open = True

    def due(self, now_ms: int) -> list[Trigger]:
        """The proactive Triggers that fire at `now_ms`; each is marked fired. Nothing fires
        before the timer starts or once time is up."""
        if self._timer_started_ms is None or self._stopped:
            return []
        fresh = [
            *self._time_checkpoints(now_ms),
            *self._phase_overrun(now_ms),
            *self._silence(now_ms),
        ]
        # A newer checkpoint supersedes a held-back one; an overrun is moot once the Phase moved.
        if any(t.reason == "time" for t in fresh):
            self._held_back = [t for t in self._held_back if t.reason != "time"]
        self._held_back = [
            t for t in self._held_back if t.reason != "phase_overrun" or t.detail == self._phase
        ]
        retried: list[Trigger] = []
        if self._held_back and self.suppression(now_ms) is None:
            retried, self._held_back = self._held_back, []
        return [*retried, *fresh]

    def hold_back(self, trigger: Trigger) -> None:
        """A guardrail suppressed `trigger`. Time checkpoints and Phase overruns are retried once
        the guardrails allow; a silence is not (one Nudge per silence)."""
        if trigger.reason in ("time", "phase_overrun") and trigger not in self._held_back:
            self._held_back.append(trigger)

    def suppression(self, now_ms: int) -> Suppression | None:
        """Which guardrail holds back an unprompted utterance now, if any."""
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

    def _phase_overrun(self, now_ms: int) -> Sequence[Trigger]:
        guide_min = OVERRUN_MIN.get(self._phase)
        if guide_min is None or self._overrun_fired_since == self._phase_since_ms:
            return []
        if now_ms - self._phase_since_ms <= guide_min * 60_000:
            return []
        self._overrun_fired_since = self._phase_since_ms
        return [Trigger("phase_overrun", self._phase)]

    def _silence(self, now_ms: int) -> Sequence[Trigger]:
        threshold_s = self._config.silence_nudge_s.get(self._phase)
        if threshold_s is None or not self._silence_open:
            return []
        assert self._timer_started_ms is not None
        # The Candidate always gets the full threshold to answer the Interviewer's last words.
        since = max(self._last_activity_ms, self._last_interviewer_ms or 0, self._timer_started_ms)
        if now_ms - since < threshold_s * 1000:
            return []
        self._silence_open = False
        return [Trigger("silence", self._phase)]
