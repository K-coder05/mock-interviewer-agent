"""The model client interface shared by problem prep, the Interviewer and (later) the Report.

Callers depend only on this protocol, so tests inject a scripted fake and production injects
`AnthropicModelClient` (`backend/agent/anthropic_client.py`). A stream yields text deltas as they
arrive; tool calls are yielded once the model's turn is complete. Callers own their tool
definitions and must validate tool inputs (model output is untrusted).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Effort = Literal["low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict[str, Any]


ModelEvent = TextDelta | ToolCall


@dataclass(frozen=True)
class ModelRequest:
    model: str
    system: str
    """Stable for the whole Session: the client prompt-caches it (together with `tools`), so
    anything that changes between calls belongs in `messages`."""
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_tokens: int = 1024
    effort: Effort | None = None


class ModelError(Exception):
    """The model call failed in a way the UI should explain (rate limit, outage, refusal...)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ModelClient(Protocol):
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...
