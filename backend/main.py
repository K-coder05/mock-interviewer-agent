"""FastAPI app: REST for Session lifecycle and reads, one WebSocket per live Session."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, model_validator

from backend.agent.anthropic_client import AnthropicModelClient
from backend.agent.context import PERSONAS, Style
from backend.agent.model import ModelClient
from backend.agent.prep import PrepFailed
from backend.clock import Clock, SystemClock
from backend.config import Config, load_config
from backend.db import Store
from backend.runner import Runner
from backend.session import ServerMessage, SessionDefaults, SessionManager


class StyleInput(BaseModel):
    """A preset id or a free-text persona description (exactly one)."""

    preset: str | None = None
    custom: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _one_of(self) -> StyleInput:
        if self.custom is not None and not self.custom.strip():
            self.custom = None
        if (self.preset is None) == (self.custom is None):
            raise ValueError("give either a Style preset or a free-text description")
        if self.preset is not None and self.preset not in PERSONAS:
            raise ValueError(f"unknown Style preset; choose one of {sorted(PERSONAS)}")
        return self


class CreateSessionRequest(BaseModel):
    problem_md: str = Field(min_length=1)
    starter_code: str | None = None
    private_notes: str | None = None
    style: StyleInput = StyleInput(preset="faang_standard")
    duration_min: int | None = Field(default=None, ge=5, le=180)


class CreateSessionResponse(BaseModel):
    session_id: str


def create_app(
    config: Config | None = None, clock: Clock | None = None, model: ModelClient | None = None
) -> FastAPI:
    config = config or load_config()
    store = Store(config.db_path)
    manager = SessionManager(
        store=store,
        clock=clock or SystemClock(),
        runner=Runner(config.runner),
        model=model or AnthropicModelClient(config.api_key),
        defaults=SessionDefaults(
            duration_min=config.default_duration_min,
            timeout_grace_s=config.timeout_grace_s,
            models=config.models,
        ),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await manager.close()
        store.close()

    app = FastAPI(title="Mock Interviewer", lifespan=lifespan)

    @app.post("/api/sessions", response_model=CreateSessionResponse)
    async def create_session(body: CreateSessionRequest) -> CreateSessionResponse:
        """Runs problem prep (with one retry) before creating anything; on failure nothing is
        created and the client returns to setup with its input intact."""
        try:
            live = await manager.create(
                problem_md=body.problem_md,
                starter_code=body.starter_code,
                private_notes=body.private_notes,
                style=Style(preset=body.style.preset, custom=body.style.custom),
                duration_min=body.duration_min,
            )
        except PrepFailed as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return CreateSessionResponse(session_id=live.id)

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        record = store.get_session(session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "session": record.to_public_dict(),
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
        live.client_connected()
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
