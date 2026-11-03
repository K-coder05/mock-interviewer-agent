"""The Interviewer's model client interface.

Session code depends only on this protocol, so tests inject a scripted fake and production
injects an Anthropic-backed client (added with the text-chat Interviewer). A stream yields text
deltas as they arrive; tool calls are yielded once the model's turn is complete.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


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
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_tokens: int = 400


class ModelClient(Protocol):
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...
