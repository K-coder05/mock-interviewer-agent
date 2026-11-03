"""Session engine: creates Sessions and owns each live Session.

A LiveSession accepts the same client messages the WebSocket carries, appends events to the
Session's event log with server-owned `seq` and `t_ms` (ms since Session start, from the injected
monotonic clock), and emits server messages to whoever is subscribed.
"""

from __future__ import annotations

import asyncio
import dataclasses
import difflib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from backend.agent.context import Style, build_system_prompt
from backend.agent.interviewer import Decision, Interviewer, Trigger
from backend.agent.model import ModelClient, ModelError
from backend.agent.prep import prepare_problem_brief
from backend.clock import Clock
from backend.config import ModelIds
from backend.db import Event, SessionRecord, Store
from backend.ids import new_id
from backend.runner import Runner

logger = logging.getLogger(__name__)

Speaker = Literal["user", "interviewer"]
ServerMessage = dict[str, Any]
Listener = Callable[[ServerMessage], Awaitable[None]]

__all__ = ["LiveSession", "ServerMessage", "SessionDefaults", "SessionManager", "Style"]


@dataclass(frozen=True)
class SessionDefaults:
    duration_min: int
    models: ModelIds


def _title_of(problem_md: str) -> str:
    for line in problem_md.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:120]
    return "Untitled problem"


def _char_changes(old: str, new: str) -> tuple[int, int]:
    added = removed = 0
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed


class LiveSession:
    def __init__(
        self,
        record: SessionRecord,
        *,
        store: Store,
        clock: Clock,
        runner: Runner,
        model: ModelClient,
    ) -> None:
        self.record = record
        self._store = store
        self._clock = clock
        self._runner = runner
        self._interviewer = Interviewer(
            model,
            model_id=record.settings["models"]["interviewer"],
            system=build_system_prompt(
                problem_md=record.problem_md,
                starter_code=record.starter_code,
                private_notes=record.private_notes,
                brief=record.problem_brief,
                style=Style.from_settings(record.settings["style"]),
            ),
        )
        self._started_at_ms = clock.monotonic_ms()
        self._code = ""
        self._snapshot_seq: int | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._greeted = False
        self._reply_task: asyncio.Task[None] | None = None
        self._reply_trigger: Trigger | None = None
        self._listeners: list[Listener] = []

    @property
    def id(self) -> str:
        return self.record.id

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Register a server-message listener; returns an unsubscribe function."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def begin(self) -> None:
        """Record the Session's opening events at t=0: session_started, then any starter code."""
        record = self.record
        self._append(
            "session_started",
            {
                "problem_md": record.problem_md,
                "starter_code": record.starter_code,
                "settings": record.settings,
            },
            t_ms=0,
        )
        if record.starter_code is not None:
            self._snapshot(record.starter_code, t_ms=0)

    def client_connected(self) -> None:
        """A client attached. The first one starts the interview: the Interviewer greets the
        Candidate and restates the problem."""
        if not self._greeted:
            self._greeted = True
            self._request_reply("session_start")

    async def handle(self, message: dict[str, Any]) -> None:
        """Process one client message (the WebSocket payload)."""
        kind = message.get("type")
        if kind == "code_update":
            await self._on_code_update(message)
        elif kind == "run":
            await self._on_run(message)
        elif kind == "utterance":
            await self._on_utterance(message)
        else:
            await self._emit_error("unknown_message", f"Unknown message type: {kind!r}")

    async def wait_for_run(self) -> None:
        """Wait for the in-flight Run (if any) to finish; used by tests and shutdown."""
        task = self._run_task
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def wait_for_interviewer(self) -> None:
        """Wait until the Interviewer has finished replying (including any queued reply)."""
        while (task := self._reply_task) is not None and not task.done():
            await asyncio.gather(task, return_exceptions=True)

    def _now_ms(self) -> int:
        return max(0, self._clock.monotonic_ms() - self._started_at_ms)

    def _append(self, type: str, payload: dict[str, Any], *, t_ms: int | None = None) -> Event:
        t = self._now_ms() if t_ms is None else t_ms
        return self._store.append_event(self.id, t_ms=t, type=type, payload=payload)

    async def _emit(self, message: ServerMessage) -> None:
        for listener in list(self._listeners):
            try:
                await listener(message)
            except Exception:  # one dead connection must not starve the others
                logger.warning("dropping failed listener for Session %s", self.id, exc_info=True)
                self._listeners.remove(listener)

    async def _emit_error(self, code: str, message: str) -> None:
        await self._emit({"type": "error", "code": code, "message": message})

    async def _on_code_update(self, message: dict[str, Any]) -> None:
        code = message.get("code")
        if not isinstance(code, str):
            await self._emit_error("invalid_message", "code_update requires a string `code`")
            return
        self._snapshot(code)

    async def _on_utterance(self, message: dict[str, Any]) -> None:
        text, channel = message.get("text"), message.get("channel", "text")
        if not isinstance(text, str) or not text.strip() or channel != "text":
            await self._emit_error(
                "invalid_message", "utterance requires non-empty `text` and channel 'text'"
            )
            return
        self._append_utterance("user", text.strip(), self._now_ms())
        self._request_reply("typed_message")  # a typed message always gets a reply

    def _request_reply(self, trigger: Trigger) -> None:
        """Start a reply, or, if one is streaming, queue one more: it is built from the event
        log when it starts, so it covers everything that arrived meanwhile."""
        self._reply_trigger = trigger
        if self._reply_task is None or self._reply_task.done():
            self._reply_task = asyncio.create_task(self._reply_loop())

    async def _reply_loop(self) -> None:
        while (trigger := self._reply_trigger) is not None:
            self._reply_trigger = None
            try:
                await self._reply(trigger)
            except asyncio.CancelledError:
                raise
            except ModelError as exc:
                logger.warning("Interviewer call failed for Session %s: %s", self.id, exc.message)
                await self._emit_error(exc.code, exc.message)
            except Exception:
                logger.exception("Interviewer call failed for Session %s", self.id)
                await self._emit_error("interviewer_failed", "The Interviewer failed to respond")

    async def _reply(self, trigger: Trigger) -> None:
        decision = await self._decide(trigger)
        if decision is not None and not decision.text and trigger == "typed_message":
            # A typed message always gets a spoken reply, even if the model only called a tool.
            await self._decide("typed_message_unanswered")

    async def _decide(self, trigger: Trigger) -> Decision | None:
        """One decision call, streamed to clients and applied to the event log. A reply that
        fails part-way is cancelled (`interviewer_cancel`) and the error re-raised."""
        msg_id = new_id("msg")
        streamed = False

        async def on_text(text: str) -> None:
            nonlocal streamed
            streamed = True
            await self._emit({"type": "interviewer_delta", "msg_id": msg_id, "text": text})

        start = self._now_ms()
        try:
            decision = await self._interviewer.decide(
                self._store.events(self.id), now_ms=start, trigger=trigger, on_text=on_text
            )
        except BaseException:
            if streamed:
                await self._emit({"type": "interviewer_cancel", "msg_id": msg_id})
            raise
        if decision.text:
            self._append_utterance("interviewer", decision.text, start, msg_id=msg_id)
            await self._emit(
                {"type": "interviewer_done", "msg_id": msg_id, "full_text": decision.text}
            )
        elif streamed:  # whitespace only: nothing to keep
            await self._emit({"type": "interviewer_cancel", "msg_id": msg_id})
        for clarification in decision.clarifications:
            payload = dataclasses.asdict(clarification)
            event = self._append("clarification", payload)
            await self._emit({"type": "clarification", "seq": event.seq, **payload})
        return decision

    def _append_utterance(
        self, speaker: Speaker, text: str, start_ms: int, *, msg_id: str | None = None
    ) -> Event:
        now = self._now_ms()
        payload: dict[str, Any] = {
            "speaker": speaker,
            "channel": "text",
            "text": text,
            "start_ms": start_ms,
            "end_ms": now,
        }
        if msg_id is not None:
            payload["msg_id"] = msg_id
        return self._append("utterance", payload, t_ms=now)

    async def _on_run(self, message: dict[str, Any]) -> None:
        code, stdin = message.get("code"), message.get("stdin") or ""
        if not isinstance(code, str) or not isinstance(stdin, str):
            await self._emit_error("invalid_message", "run requires a string `code` (and `stdin`)")
            return
        # Only one Run per Session: a new one cancels the old.
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()
            await asyncio.gather(self._run_task, return_exceptions=True)
        self._snapshot(code)  # forced snapshot (deduped); the run event references its seq
        assert self._snapshot_seq is not None
        await self._emit({"type": "run_started", "snapshot_seq": self._snapshot_seq})
        self._run_task = asyncio.create_task(self._execute(code, stdin, self._snapshot_seq))

    async def _execute(self, code: str, stdin: str, snapshot_seq: int) -> None:
        try:
            result = await self._runner.run(code, stdin)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Runner failed for Session %s", self.id)
            await self._emit_error("run_failed", "The Runner failed to execute your code")
            return
        payload = {"snapshot_seq": snapshot_seq, "stdin": stdin, **dataclasses.asdict(result)}
        self._append("run", payload)
        await self._emit({"type": "run_result", **payload})

    def _snapshot(self, code: str, *, t_ms: int | None = None) -> Event | None:
        """Record `code` as a code snapshot unless it equals the last one (dedup)."""
        if code == self._code and self._snapshot_seq is not None:
            return None
        previous, self._code = self._code, code
        added, removed = _char_changes(previous, code)
        diff = "".join(
            difflib.unified_diff(
                previous.splitlines(keepends=True),
                code.splitlines(keepends=True),
                fromfile="before",
                tofile="after",
            )
        )
        event = self._append(
            "code_snapshot",
            {"code": code, "diff_from_prev": diff, "chars_added": added, "chars_removed": removed},
            t_ms=t_ms,
        )
        self._snapshot_seq = event.seq
        return event


class SessionManager:
    """Creates Sessions and keeps the in-memory LiveSession for each one started this process."""

    def __init__(
        self,
        *,
        store: Store,
        clock: Clock,
        runner: Runner,
        model: ModelClient,
        defaults: SessionDefaults,
    ) -> None:
        self._store = store
        self._clock = clock
        self._runner = runner
        self._model = model
        self._defaults = defaults
        self._live: dict[str, LiveSession] = {}

    async def create(
        self,
        *,
        problem_md: str,
        starter_code: str | None = None,
        private_notes: str | None = None,
        style: Style,
    ) -> LiveSession:
        """Run problem prep, then persist and start the Session.

        Raises PrepFailed (after prep's one retry) without creating anything.
        """
        starter = starter_code or None
        notes = (private_notes or "").strip() or None
        brief = await prepare_problem_brief(
            self._model,
            model_id=self._defaults.models.prep,
            problem_md=problem_md,
            starter_code=starter,
            private_notes=notes,
        )
        settings: dict[str, Any] = {
            "duration_min": self._defaults.duration_min,
            "autocomplete": False,
            "style": style.to_settings(),
            "models": dataclasses.asdict(self._defaults.models),
        }
        record = self._store.create_session(
            title=_title_of(problem_md),
            problem_md=problem_md,
            starter_code=starter,
            private_notes=notes,
            settings=settings,
            problem_brief=brief,
        )
        live = LiveSession(
            record, store=self._store, clock=self._clock, runner=self._runner, model=self._model
        )
        live.begin()
        self._live[record.id] = live
        return live

    def live(self, session_id: str) -> LiveSession | None:
        return self._live.get(session_id)
