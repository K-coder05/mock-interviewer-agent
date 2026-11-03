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
from backend.agent.model import ModelClient, ModelRequest, TextDelta, ToolCall
from backend.agent.triggers import Trigger
from backend.db import Event
from backend.phases import PHASES

logger = logging.getLogger(__name__)

# Replies are 1-3 spoken sentences; the headroom covers any adaptive thinking.
DECISION_MAX_TOKENS = 1024

ClarifiedBy = Literal["interviewer", "candidate"]

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

SET_PHASE: dict[str, Any] = {
    "name": "set_phase",
    "description": (
        "Move the interview's current Phase when the conversation has moved on (for example "
        "from clarifying to discussing the approach). A Phase is only a label and may move "
        "backwards. Ignored while the candidate's own choice of Phase is still locked."
    ),
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "properties": {"phase": {"type": "string", "enum": list(PHASES)}},
        "required": ["phase"],
        "additionalProperties": False,
    },
}

STAY_SILENT: dict[str, Any] = {
    "name": "stay_silent",
    "description": (
        "Say nothing this turn. Call it, with no text, when speaking up now would interrupt "
        "productive work or add nothing. The reason is logged privately to tune your behavior."
    ),
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Why staying silent is right, briefly."}
        },
        "required": ["reason"],
        "additionalProperties": False,
    },
}

# Deterministic order: the tool list is part of the prompt-cached prefix.
TOOLS = [RECORD_CLARIFICATION, SET_PHASE, STAY_SILENT]


@dataclass(frozen=True)
class Clarification:
    question: str
    answer: str
    by: ClarifiedBy


@dataclass(frozen=True)
class Decision:
    text: str
    clarifications: list[Clarification] = field(default_factory=list)
    phase: str | None = None
    """The last valid `set_phase` the model asked for."""
    silent_reason: str | None = None
    """The `stay_silent` reason, when the model chose silence."""


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
        phase_lock_ms: int = 0,
        trigger: Trigger,
        coalesced: Sequence[Trigger] = (),
        on_text: Callable[[str], Awaitable[None]],
    ) -> Decision:
        """Make one decision call. Text is passed to `on_text` as it streams; tool calls are
        validated and returned once the stream ends. Raises ModelError on API failures."""
        request = ModelRequest(
            model=self._model_id,
            system=self._system,
            messages=[
                {"role": "user", "content": build_turn_message(
                        events,
                        now_ms=now_ms,
                        remaining_ms=remaining_ms,
                        phase_lock_ms=phase_lock_ms,
                        trigger=trigger,
                        coalesced=coalesced,
                    )}
            ],
            tools=TOOLS,
            max_tokens=DECISION_MAX_TOKENS,
            effort="low",
        )
        text: list[str] = []
        clarifications: list[Clarification] = []
        phase: str | None = None
        silent_reason: str | None = None
        async for event in self._model.stream(request):
            if isinstance(event, TextDelta):
                if event.text:
                    text.append(event.text)
                    await on_text(event.text)
            elif not isinstance(event, ToolCall):
                continue  # Usage: logged by the client
            elif event.name == RECORD_CLARIFICATION["name"]:
                if (clarification := _clarification(event.input)) is not None:
                    clarifications.append(clarification)
                else:
                    logger.warning("ignoring invalid record_clarification input: %r", event.input)
            elif event.name == SET_PHASE["name"]:
                if event.input.get("phase") in PHASES:
                    phase = str(event.input["phase"])
                else:
                    logger.warning("ignoring invalid set_phase input: %r", event.input)
            elif event.name == STAY_SILENT["name"]:
                reason = event.input.get("reason")
                given = reason.strip() if isinstance(reason, str) else ""
                silent_reason = given or "(none given)"
            else:
                logger.warning("ignoring unknown tool call %r", event.name)
        spoken = "".join(text).strip()
        if spoken and silent_reason is not None:
            logger.warning("stay_silent called alongside speech; the speech stands")
            silent_reason = None
        return Decision(
            text=spoken, clarifications=clarifications, phase=phase, silent_reason=silent_reason
        )
