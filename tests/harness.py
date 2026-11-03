"""Live Session test harness, reused by every Session test.

- FakeClock: time only moves when a test advances it.
- ScriptedModel: a fake model (problem prep and Interviewer) that replays canned text and tool
  calls and records every request it receives. No real API calls.
- LiveSessionHarness: the message driver. Creates Sessions through the real SessionManager and
  Store (temp SQLite file), sends WebSocket-shaped client messages, and exposes the resulting
  event log and the server messages the Session emitted. Ending a Session starts Report
  generation on the same ScriptedModel (script a `submit_report` turn to have it succeed).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from backend.agent.model import ModelEvent, ModelRequest, TextDelta, ToolCall, Usage
from backend.agent.prep import ProblemBrief
from backend.config import ModelIds, RunnerConfig
from backend.db import Event, SessionRecord, Store
from backend.feedback.generator import ReportGenerator
from backend.runner import Runner
from backend.session import ServerMessage, SessionDefaults, SessionManager, Style

DEFAULT_MODELS = ModelIds(
    prep="claude-opus-5-5", interviewer="claude-sonnet-5-5", report="claude-opus-5-5"
)


DEFAULT_BRIEF: ProblemBrief = {
    "approaches": [
        {
            "name": "Brute force",
            "idea": "Check every pair.",
            "time_complexity": "O(n^2)",
            "space_complexity": "O(1)",
        },
        {
            "name": "Hash map",
            "idea": "Store complements while scanning once.",
            "time_complexity": "O(n)",
            "space_complexity": "O(n)",
        },
    ],
    "key_insights": ["A complement lookup turns the pair search into one pass."],
    "pitfalls": ["Using the same element twice."],
    "edge_case_categories": [
        {"name": "Duplicates", "description": "Equal values that together hit the target."},
        {"name": "Negatives", "description": "Negative numbers and zero."},
    ],
    "clarifications": [
        {"question": "Is there always exactly one answer?", "default_answer": "Yes."},
    ],
    "follow_ups": ["What if the input is sorted?"],
}


class FakeClock:
    """`tick_per_read_ms` > 0 makes every read advance time, simulating work taking real time."""

    def __init__(self, start_ms: int = 1_000_000, tick_per_read_ms: int = 0) -> None:
        self._now_ms = start_ms
        self.tick_per_read_ms = tick_per_read_ms

    def monotonic_ms(self) -> int:
        self._now_ms += self.tick_per_read_ms
        return self._now_ms

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("time cannot go backwards")
        self._now_ms += round(seconds * 1000)


ScriptItem = str | ToolCall | Usage | Exception

DEFAULT_USAGE_TOKENS = (1000, 200)
"""(input, output) tokens reported for a scripted turn that doesn't script its own Usage."""


class ScriptedModel:
    """Each call to `stream` consumes the next scripted turn.

    A turn is a sequence of strings (streamed as text deltas), ToolCalls (yielded in order),
    Usage and exceptions (raised at that point, e.g. a ModelError mid-stream). Like the real
    client, a turn that completes reports its Usage before its tool calls: by default
    DEFAULT_USAGE_TOKENS on the requested model, unless the turn scripts a Usage itself.
    """

    def __init__(self, turns: Sequence[Sequence[ScriptItem]] = ()) -> None:
        self._turns: list[Sequence[ScriptItem]] = list(turns)
        self.requests: list[ModelRequest] = []

    def script(self, *turn: ScriptItem) -> None:
        self._turns.append(turn)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        self.requests.append(request)
        if not self._turns:
            raise AssertionError("ScriptedModel called with no scripted turn left")
        turn = self._turns.pop(0)
        if not any(isinstance(item, (Usage, Exception)) for item in turn):
            usage = Usage(request.model, *DEFAULT_USAGE_TOKENS)
            first_tool = next((i for i, x in enumerate(turn) if isinstance(x, ToolCall)), len(turn))
            turn = [*turn[:first_tool], usage, *turn[first_tool:]]
        for item in turn:
            await asyncio.sleep(0)  # like a real stream, let other tasks run between items
            if isinstance(item, Exception):
                raise item
            yield TextDelta(item) if isinstance(item, str) else item


class LiveSessionHarness:
    def __init__(self, db_path: Path, runner: Runner | None = None) -> None:
        self.clock = FakeClock()
        self.model = ScriptedModel()
        self.store = Store(db_path)
        self.reports = ReportGenerator(
            store=self.store, model=self.model, model_id=DEFAULT_MODELS.report
        )
        self.manager = SessionManager(
            store=self.store,
            clock=self.clock,
            runner=runner or Runner(RunnerConfig(timeout_s=5)),
            model=self.model,
            reports=self.reports,
            defaults=SessionDefaults(duration_min=45, timeout_grace_s=60, models=DEFAULT_MODELS),
            timer_poll_s=None,  # tests drive the timer with `elapse` instead of a polling loop
        )
        self.sent: dict[str, list[ServerMessage]] = {}

    async def aclose(self) -> None:
        await self.manager.close()  # also stops in-flight Report generation
        self.store.close()

    async def start(
        self,
        *,
        problem_md: str = "# Problem\n\nSolve it.",
        starter_code: str | None = None,
        private_notes: str | None = None,
        style: Style | None = None,
        brief: ProblemBrief | None = DEFAULT_BRIEF,
        duration_min: int | None = None,
    ) -> str:
        """Run problem prep, create a Session and capture every server message it emits.

        Prep consumes the next scripted model turn: by default a valid `submit_problem_brief`
        call with `brief`. Pass `brief=None` to script the prep turns yourself (before calling
        start). Script Interviewer turns after start.
        """
        if brief is not None:
            self.model.script(ToolCall("submit_problem_brief", brief))
        live = await self.manager.create(
            problem_md=problem_md,
            starter_code=starter_code,
            private_notes=private_notes,
            style=style or Style(preset="faang_standard"),
            duration_min=duration_min,
        )
        messages = self.sent.setdefault(live.id, [])

        async def capture(message: ServerMessage) -> None:
            messages.append(message)

        live.subscribe(capture)
        return live.id

    async def send(self, session_id: str, type: str, **payload: Any) -> None:
        live = self.manager.live(session_id)
        assert live is not None, f"no live Session {session_id}"
        await live.handle({"type": type, **payload})
        if type == "end_session":
            await live.wait_for_interviewer()

    async def connect(self, session_id: str) -> None:
        """A client connected (as the WebSocket does); the first one triggers the greeting."""
        live = self.manager.live(session_id)
        assert live is not None
        live.client_connected()
        await live.wait_for_interviewer()

    async def say(self, session_id: str, text: str) -> None:
        """Type a message to the Interviewer and wait for its streamed reply to finish."""
        await self.send(session_id, "utterance", text=text, channel="text")
        live = self.manager.live(session_id)
        assert live is not None
        await live.wait_for_interviewer()

    async def finish_run(self, session_id: str) -> None:
        """Wait for the Session's in-flight Run to complete (Runs execute in the background)."""
        live = self.manager.live(session_id)
        assert live is not None
        await live.wait_for_run()

    def advance(self, seconds: float) -> None:
        self.clock.advance(seconds)

    async def elapse(self, session_id: str, seconds: float) -> None:
        """Move the clock forward, let the Session's timer react, and wait for any Interviewer
        reply (time-up prompt, closing) it caused."""
        self.clock.advance(seconds)
        live = self.manager.live(session_id)
        assert live is not None
        await live.tick()
        await live.wait_for_interviewer()

    async def finish_report(self, session_id: str) -> dict[str, Any] | None:
        """Wait for the Session's Report generation (started when it ended); returns the
        `GET report` view."""
        await self.reports.wait(session_id)
        return self.reports.view(session_id)

    def session(self, session_id: str) -> SessionRecord:
        record = self.store.get_session(session_id)
        assert record is not None
        return record

    def events(self, session_id: str, type: str | None = None) -> list[Event]:
        events = self.store.events(session_id)
        return [e for e in events if type is None or e.type == type]

    def messages(self, session_id: str, type: str | None = None) -> list[ServerMessage]:
        return [m for m in self.sent.get(session_id, []) if type is None or m["type"] == type]


__all__ = [
    "DEFAULT_BRIEF",
    "FakeClock",
    "LiveSessionHarness",
    "ScriptedModel",
    "Style",
    "ToolCall",
    "Usage",
]
