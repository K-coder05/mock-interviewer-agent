"""Production ModelClient backed by the Anthropic Messages API (streaming).

- The system prompt is sent as one block marked with `cache_control`, so the tools + system prefix
  (persona, rules, problem, Problem Brief) is prompt-cached across a Session's decision calls.
- Server-side refusal fallback (`fallbacks: "default"`) is enabled on models that support it.
- API failures surface as ModelError with a code the UI can show (rate limited, unavailable...).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from backend.agent.model import ModelError, ModelEvent, ModelRequest, TextDelta, ToolCall

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept `fallbacks: "default"` (Haiku has no server-side fallback).
FALLBACK_MODELS = frozenset({"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"})


class AnthropicModelClient:
    def __init__(self, api_key: str, *, client: anthropic.AsyncAnthropic | None = None) -> None:
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": [
                {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": request.messages,
        }
        if request.tools:
            params["tools"] = request.tools
        if request.effort:
            params["output_config"] = {"effort": request.effort}
        if request.model in FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"

        try:
            async with self._client.beta.messages.stream(**params) as stream:
                async for event in stream:
                    if event.type == "text":
                        yield TextDelta(event.text)
                message = await stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise ModelError("api_key_invalid", "The Anthropic API key was rejected.") from exc
        except anthropic.RateLimitError as exc:
            raise ModelError("rate_limited", "The Anthropic API is rate limiting requests.") from exc
        except anthropic.BadRequestError as exc:
            logger.error("Anthropic API rejected the request: %s", exc.message)
            raise ModelError("model_request_invalid", "The Anthropic API rejected the request.") from exc
        except anthropic.APIStatusError as exc:
            raise ModelError(
                "model_unavailable", f"The Anthropic API is unavailable ({exc.status_code})."
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ModelError("model_unreachable", "Could not reach the Anthropic API.") from exc
        except ValueError as exc:  # tool input JSON the SDK could not parse at all
            raise ModelError("model_output_invalid", "The model returned malformed output.") from exc

        usage = message.usage
        logger.info(
            "model call %s: stop=%s in=%s cache_read=%s cache_write=%s out=%s",
            message.model,
            message.stop_reason,
            usage.input_tokens,
            usage.cache_read_input_tokens,
            usage.cache_creation_input_tokens,
            usage.output_tokens,
        )
        if message.stop_reason == "refusal":
            raise ModelError("model_refused", "The model declined to respond.")
        if message.stop_reason == "max_tokens":
            logger.warning("model call hit max_tokens; dropping any (possibly truncated) tool calls")
            return
        for block in message.content:
            if block.type == "tool_use" and isinstance(block.input, dict):
                yield ToolCall(block.name, dict(block.input))
