"""The Interviewer's decision call: context from the event log in, streamed speech and tool calls out.

The Interviewer owns the prompt and the tool definitions and validates what the model returns;
the Session engine owns the event log and applies the resulting Decision.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from backend.agent.context import build_turn_message
from backend.agent.model import ModelClient, ModelRequest, TextDelta
from backend.db import Event

logger = logging.getLogger(__name__)

# Replies are 1-3 spoken sentences; the headroom covers any adaptive thinking.
DECISION_MAX_TOKENS = 1024

ClarifiedBy = Literal["interviewer", "candidate"]
# Why the Interviewer is asked to respond. Later tickets add silence, run, stuck, time...
Trigger = Literal[
    "session_start", "typed_message", "typed_message_unanswered", "time_up", "session_end"
]

RECORD_CLARIFICATION: dict[str, Any] = {
    "name": "record_clarification",
    "description": (
        "Record a clarification of the problem so it stays binding for the rest of the "
        "interview and appears under the problem for the candidate. Use by='interviewer' when "
        "you supplied the answer, by='candidate' when the answer is the candidate's own stated "
        "assumption."
    ),
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The clarifying question, concisely."},
            "answer": {"type": "string", "description": "The binding answer, concisely."},
            "by": {"type": "string", "enum": ["interviewer", "candidate"]},
        },
        "required": ["question", "answer", "by"],
        "additionalProperties": False,
    },
}

TOOLS = [RECORD_CLARIFICATION]


@dataclass(frozen=True)
class Clarification:
    question: str
    answer: str
    by: ClarifiedBy


@dataclass(frozen=True)
class Decision:
    text: str
    clarifications: list[Clarification] = field(default_factory=list)


def _clarification(value: dict[str, Any]) -> Clarification | None:
    question, answer, by = value.get("question"), value.get("answer"), value.get("by")
    if not (isinstance(question, str) and question.strip()):
        return None
    if not (isinstance(answer, str) and answer.strip()):
        return None
    if by == "interviewer" or by == "candidate":
        return Clarification(question.strip(), answer.strip(), by)
    return None


class Interviewer:
    def __init__(self, model: ModelClient, *, model_id: str, system: str) -> None:
        self._model = model
        self._model_id = model_id
        self._system = system

    async def decide(
        self,
        events: Sequence[Event],
        *,
        now_ms: int,
        remaining_ms: int | None = None,
        trigger: Trigger,
        on_text: Callable[[str], Awaitable[None]],
    ) -> Decision:
        """Make one decision call. Text is passed to `on_text` as it streams; tool calls are
        validated and returned once the stream ends. Raises ModelError on API failures."""
        request = ModelRequest(
            model=self._model_id,
            system=self._system,
            messages=[
                {"role": "user", "content": build_turn_message(
                        events, now_ms=now_ms, remaining_ms=remaining_ms, trigger=trigger
                    )}
            ],
            tools=TOOLS,
            max_tokens=DECISION_MAX_TOKENS,
            effort="low",
        )
        text: list[str] = []
        clarifications: list[Clarification] = []
        async for event in self._model.stream(request):
            if isinstance(event, TextDelta):
                if event.text:
                    text.append(event.text)
                    await on_text(event.text)
            elif event.name == RECORD_CLARIFICATION["name"]:
                if (clarification := _clarification(event.input)) is not None:
                    clarifications.append(clarification)
                else:
                    logger.warning("ignoring invalid record_clarification input: %r", event.input)
            else:
                logger.warning("ignoring unknown tool call %r", event.name)
        return Decision(text="".join(text).strip(), clarifications=clarifications)
