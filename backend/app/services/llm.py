"""Thin wrapper around the Anthropic SDK for schema-validated (structured) responses."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from app.config import Settings

log = logging.getLogger(__name__)

# Server-side refusal fallback: if a safety classifier declines, the API retries on a
# suitable fallback model inside the same request.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """A non-retryable model failure (bad request, refusal, truncated output)."""


class LLMTransientError(LLMError):
    """A retryable failure: rate limit, overload, network error."""


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(max_retries=3)


def structured_call[T: BaseModel](
    settings: Settings,
    *,
    system: str,
    content: list[dict[str, Any]],
    schema: type[T],
) -> T:
    try:
        response = _client().beta.messages.parse(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=schema,
            output_config={"effort": settings.anthropic_effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as exc:
        raise LLMTransientError(str(exc)) from exc
    except anthropic.APIStatusError as exc:
        if exc.status_code in (408, 409, 529):
            raise LLMTransientError(str(exc)) from exc
        raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
    except ValidationError as exc:
        # parse() validates eagerly; incomplete JSON (e.g. a max_tokens cut-off) lands here.
        raise LLMError(f"Model output did not match the {schema.__name__} schema: {exc.errors()[0]['msg']}") from exc

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise LLMError(f"Model declined the request (category: {category})")
    if response.stop_reason == "max_tokens":
        raise LLMError("Model output was truncated (max_tokens reached)")
    if response.parsed_output is None:
        raise LLMError("Model returned no parseable output")

    log.info(
        "LLM %s ok: request_id=%s in=%s out=%s",
        schema.__name__,
        response._request_id,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    return response.parsed_output
