"""Session engine: creates Sessions and owns each live Session.

A LiveSession accepts the same client messages the WebSocket carries, appends events to the
Session's event log with server-owned `seq` and `t_ms` (ms since Session start, from the injected
monotonic clock), and emits server messages to whoever is subscribed.
"""

from __future__ import annotations

import dataclasses
import difflib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from backend.clock import Clock
from backend.config import ModelIds
from backend.db import Event, SessionRecord, Store

logger = logging.getLogger(__name__)

ServerMessage = dict[str, Any]
Listener = Callable[[ServerMessage], Awaitable[None]]


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
    ) -> None:
        self.record = record
        self._store = store
        self._clock = clock
        self._started_at_ms = clock.monotonic_ms()
        self._code = ""
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

    async def handle(self, message: dict[str, Any]) -> None:
        """Process one client message (the WebSocket payload)."""
        kind = message.get("type")
        if kind == "code_update":
            await self._on_code_update(message)
        else:
            await self._emit_error("unknown_message", f"Unknown message type: {kind!r}")

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

    def _snapshot(self, code: str, *, t_ms: int | None = None) -> Event | None:
        """Record `code` as a code snapshot unless it equals the last one (dedup)."""
        if code == self._code:
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
        return self._append(
            "code_snapshot",
            {"code": code, "diff_from_prev": diff, "chars_added": added, "chars_removed": removed},
            t_ms=t_ms,
        )


class SessionManager:
    """Creates Sessions and keeps the in-memory LiveSession for each one started this process."""

    def __init__(
        self,
        *,
        store: Store,
        clock: Clock,
        defaults: SessionDefaults,
    ) -> None:
        self._store = store
        self._clock = clock
        self._defaults = defaults
        self._live: dict[str, LiveSession] = {}

    def create(self, *, problem_md: str, starter_code: str | None = None) -> LiveSession:
        starter = starter_code or None
        settings: dict[str, Any] = {
            "duration_min": self._defaults.duration_min,
            "autocomplete": False,
            "models": dataclasses.asdict(self._defaults.models),
        }
        record = self._store.create_session(
            title=_title_of(problem_md),
            problem_md=problem_md,
            starter_code=starter,
            private_notes=None,
            settings=settings,
        )
        live = LiveSession(record, store=self._store, clock=self._clock)
        live.begin()
        self._live[record.id] = live
        return live

    def live(self, session_id: str) -> LiveSession | None:
        return self._live.get(session_id)
