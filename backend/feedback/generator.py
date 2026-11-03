"""Runs Report generation in the background and answers `GET report`.

One generator serves first generation (started when a Session ends), Retry after
`report_failed`, regeneration and Abandoned Sessions alike: each rebuilds the Report
from the stored event log only.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.agent.model import ModelClient
from backend.db import Store
from backend.feedback.report import ReportFailed, generate_report

logger = logging.getLogger(__name__)


class ReportGenerator:
    def __init__(self, *, store: Store, model: ModelClient, model_id: str) -> None:
        self._store = store
        self._model = model
        self._model_id = model_id
        """The configured Report model; a regeneration uses the current config."""
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, session_id: str) -> bool:
        """Start generating the Session's Report in the background (replacing any earlier
        Report once it succeeds). False if the Session is unknown or still live. A no-op while one
        is already in flight."""
        record = self._store.get_session(session_id)
        if record is None or record.status == "live":
            return False
        if not self.generating(session_id):
            task = asyncio.create_task(self._generate(session_id))
            self._tasks[session_id] = task
            task.add_done_callback(lambda t: self._forget(session_id, t))
        return True

    def _forget(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(session_id) is task:
            del self._tasks[session_id]

    def generating(self, session_id: str) -> bool:
        task = self._tasks.get(session_id)
        return task is not None and not task.done()

    async def wait(self, session_id: str) -> None:
        """Wait for the in-flight generation (if any) to finish; used by tests."""
        if (task := self._tasks.get(session_id)) is not None:
            await asyncio.gather(task, return_exceptions=True)

    def view(self, session_id: str) -> dict[str, Any] | None:
        """What `GET report` returns: `generating` while in flight, the Report once ready,
        otherwise the Session's status (`report_failed` shows Retry). None if no such Session."""
        record = self._store.get_session(session_id)
        if record is None:
            return None
        if self.generating(session_id):
            return {"status": "generating"}
        if record.status == "report_ready" and (report := self._store.get_report(session_id)):
            return {"status": "report_ready", **report.to_dict()}
        return {"status": record.status}

    async def close(self) -> None:
        tasks = [t for t in self._tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _generate(self, session_id: str) -> None:
        record = self._store.get_session(session_id)
        assert record is not None
        try:
            generated = await generate_report(
                self._model,
                model_id=self._model_id,
                record=record,
                events=self._store.events(session_id),
            )
            self._store.save_report(
                session_id,
                model=generated.model,
                metrics=generated.metrics,
                report=generated.report,
                usage=generated.usage,
            )
        except ReportFailed:
            logger.warning("Report generation failed for Session %s", session_id)
            self._fail(session_id)
        except Exception:
            logger.exception("Report generation crashed for Session %s", session_id)
            self._fail(session_id)

    def _fail(self, session_id: str) -> None:
        """A failed regeneration keeps the Report already stored (still `report_ready`);
        otherwise the Session becomes `report_failed` and the client offers Retry."""
        try:
            if self._store.get_report(session_id) is None:
                self._store.set_status(session_id, "report_failed")
        except Exception:
            logger.exception("Could not record the failed Report for Session %s", session_id)
