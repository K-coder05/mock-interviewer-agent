"""FastAPI app: REST for Session lifecycle and reads, one WebSocket per live Session."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from backend.clock import Clock, SystemClock
from backend.config import Config, load_config
from backend.db import Store
from backend.session import ServerMessage, SessionDefaults, SessionManager


class CreateSessionRequest(BaseModel):
    problem_md: str = Field(min_length=1)
    starter_code: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str


def create_app(config: Config | None = None, clock: Clock | None = None) -> FastAPI:
    config = config or load_config()
    store = Store(config.db_path)
    manager = SessionManager(
        store=store,
        clock=clock or SystemClock(),
        defaults=SessionDefaults(
            duration_min=config.default_duration_min,
            models={
                "prep": config.models.prep,
                "interviewer": config.models.interviewer,
                "report": config.models.report,
            },
        ),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        store.close()

    app = FastAPI(title="Mock Interviewer", lifespan=lifespan)

    @app.post("/api/sessions", response_model=CreateSessionResponse)
    def create_session(body: CreateSessionRequest) -> CreateSessionResponse:
        live = manager.create(problem_md=body.problem_md, starter_code=body.starter_code)
        return CreateSessionResponse(session_id=live.id)

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        record = store.get_session(session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "session": {
                "id": record.id,
                "created_at": record.created_at,
                "ended_at": record.ended_at,
                "title": record.title,
                "problem_md": record.problem_md,
                "starter_code": record.starter_code,
                "settings": record.settings,
                "status": record.status,
            },
            "events": [e.to_dict() for e in store.events(session_id)],
        }

    @app.websocket("/ws/sessions/{session_id}")
    async def session_socket(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        live = manager.live(session_id)
        if live is None:
            await websocket.send_json(
                {"type": "error", "code": "session_not_live", "message": "Session is not live"}
            )
            await websocket.close(code=4404)
            return

        async def send(message: ServerMessage) -> None:
            await websocket.send_json(message)

        unsubscribe = live.subscribe(send)
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    message = None
                if not isinstance(message, dict):
                    await send(
                        {"type": "error", "code": "invalid_message", "message": "Expected a JSON object"}
                    )
                    continue
                await live.handle(message)
        except WebSocketDisconnect:
            pass
        finally:
            unsubscribe()

    return app
