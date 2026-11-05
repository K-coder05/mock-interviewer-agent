"""Problem prep: one model call that turns the problem and private notes into the hidden Problem Brief.

The model submits the brief through the `submit_problem_brief` tool; the input is validated and
the call retried once. If both attempts fail, `PrepFailed` is raised and no Session is created.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.agent.model import ModelClient, ModelError, ModelRequest, ToolCall, Usage

logger = logging.getLogger(__name__)

ProblemBrief = dict[str, Any]

PREP_PROMPT = (Path(__file__).parent / "prompts" / "prep.md").read_text()
PREP_MAX_TOKENS = 16_000
ATTEMPTS = 2  # one retry


@dataclass(frozen=True)
class PreparedBrief:
    brief: ProblemBrief
    usage: Usage
    """Token usage summed over every attempt (a failed attempt costs tokens too); `model` is
    the model that served the accepted one."""
    attempts: int


def _sum_usage(total: Usage | None, usage: Usage) -> Usage:
    if total is None:
        return usage
    return Usage(
        model=usage.model,
        input_tokens=total.input_tokens + usage.input_tokens,
        output_tokens=total.output_tokens + usage.output_tokens,
        cache_read_input_tokens=total.cache_read_input_tokens + usage.cache_read_input_tokens,
        cache_creation_input_tokens=(
            total.cache_creation_input_tokens + usage.cache_creation_input_tokens
        ),
    )


class PrepFailed(Exception):
    """Problem prep failed after its retry; the caller must not create a Session."""


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_STRING = {"type": "string"}
_STRINGS = {"type": "array", "items": _STRING}

BRIEF_SCHEMA = _object(
    {
        "approaches": {
            "type": "array",
            "items": _object(
                {
                    "name": _STRING,
                    "idea": _STRING,
                    "time_complexity": _STRING,
                    "space_complexity": _STRING,
                }
            ),
        },
        "key_insights": _STRINGS,
        "pitfalls": _STRINGS,
        "edge_case_categories": {
            "type": "array",
            "items": _object({"name": _STRING, "description": _STRING}),
        },
        "clarifications": {
            "type": "array",
            "items": _object({"question": _STRING, "default_answer": _STRING}),
        },
        "follow_ups": _STRINGS,
    }
)

BRIEF_TOOL: dict[str, Any] = {
    "name": "submit_problem_brief",
    "description": "Submit the hidden Problem Brief for this interview. Call exactly once.",
    "strict": True,
    "input_schema": BRIEF_SCHEMA,
}


def _matches(value: Any, schema: dict[str, Any]) -> bool:
    """Checks `value` against the small JSON-Schema subset BRIEF_SCHEMA uses."""
    kind = schema["type"]
    if kind == "string":
        return isinstance(value, str)
    if kind == "array":
        return isinstance(value, list) and all(_matches(v, schema["items"]) for v in value)
    if kind == "object":
        props: dict[str, Any] = schema["properties"]
        return (
            isinstance(value, dict)
            and set(value) == set(props)
            and all(_matches(value[k], s) for k, s in props.items())
        )
    raise ValueError(f"unsupported schema type {kind!r}")


def validate_brief(value: Any) -> ProblemBrief | None:
    """The brief if it is well-formed and has at least one approach and edge-case category."""
    if not _matches(value, BRIEF_SCHEMA):
        return None
    if not value["approaches"] or not value["edge_case_categories"]:
        return None
    brief: ProblemBrief = value
    return brief


def _prep_message(problem_md: str, starter_code: str | None, private_notes: str | None) -> str:
    parts = [f"<problem>\n{problem_md}\n</problem>"]
    if starter_code:
        parts.append(f"<starter_code>\n{starter_code}\n</starter_code>")
    parts.append(f"<private_notes>\n{private_notes or '(none)'}\n</private_notes>")
    return "\n\n".join(parts)


async def prepare_problem_brief(
    model: ModelClient,
    *,
    model_id: str,
    problem_md: str,
    starter_code: str | None,
    private_notes: str | None,
) -> PreparedBrief:
    request = ModelRequest(
        model=model_id,
        system=PREP_PROMPT,
        messages=[
            {"role": "user", "content": _prep_message(problem_md, starter_code, private_notes)}
        ],
        tools=[BRIEF_TOOL],
        max_tokens=PREP_MAX_TOKENS,
        effort="high",
    )
    usage: Usage | None = None
    for attempt in range(1, ATTEMPTS + 1):
        calls: list[ToolCall] = []
        try:
            async for event in model.stream(request):
                if isinstance(event, Usage):
                    usage = _sum_usage(usage, event)
                elif isinstance(event, ToolCall):
                    calls.append(event)
        except ModelError as exc:
            logger.warning("problem prep attempt %d failed: %s (%s)", attempt, exc.message, exc.code)
            continue
        except Exception:
            logger.exception("problem prep attempt %d failed", attempt)
            continue
        for call in calls:
            if call.name == BRIEF_TOOL["name"] and (brief := validate_brief(call.input)):
                return PreparedBrief(brief, usage or Usage(model_id, 0, 0), attempt)
        logger.warning("problem prep attempt %d returned no valid Problem Brief", attempt)
    raise PrepFailed("The Interviewer could not prepare the problem. Please try again.")
