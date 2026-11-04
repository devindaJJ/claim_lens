"""Claude integration tests against a mocked HTTP transport (no network, no API key).

They pin down the request the SDK actually sends and the handling of each kind of response.
"""

from __future__ import annotations

import json
from datetime import date

import anthropic
import httpx2 as httpx
import pytest

from app.config import Settings
from app.schemas.domain import ClaimType
from app.services import llm
from app.services.extraction.claude import ClaudeExtractor
from tests.conftest import doc

DOCUMENT = doc(
    "Policy Number DM-AUTO-2025-001\nClaimant Name Amara Perera\nDate of Loss 14/03/2025\nAmount Claimed $4,250.00\nType of Claim Collision"
)

EXTRACTION = {
    "policy_number": {"value": "DM-AUTO-2025-001", "confidence": 0.98, "evidence": "DM-AUTO-2025-001"},
    "claimant_name": {"value": "Amara Perera", "confidence": 0.97, "evidence": "Amara Perera"},
    "incident_date": {"value": "2025-03-14", "confidence": 0.95, "evidence": "Date of Loss 14/03/2025"},
    "amount": {"value": 4250.0, "confidence": 0.96, "evidence": "$4,250.00"},
    "claim_type": {"value": "auto_collision", "confidence": 0.93, "evidence": "Collision"},
    "incident_description": "Rear-end collision.",
}


def _message(text: str | None, stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}] if text is not None else [],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


@pytest.fixture
def mock_api(monkeypatch):
    """Route SDK calls to a handler; returns the list of captured requests."""
    captured: list[httpx.Request] = []
    responses: list[httpx.Response] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return responses.pop(0)

    client = anthropic.Anthropic(
        api_key="test-key", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(llm, "_client", lambda: client)
    return captured, responses


def test_request_shape_and_parsing(mock_api):
    captured, responses = mock_api
    responses.append(httpx.Response(200, json=_message(json.dumps(EXTRACTION))))

    result = ClaudeExtractor(Settings(anthropic_effort="medium")).extract(DOCUMENT)

    body = json.loads(captured[0].content)
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"
    assert llm.FALLBACK_BETA in captured[0].headers["anthropic-beta"]
    assert "<document>" in body["messages"][0]["content"][-1]["text"]

    claim = result.claim
    assert (claim.policy_number, claim.incident_date, claim.amount) == ("DM-AUTO-2025-001", date(2025, 3, 14), 4250.0)
    assert claim.claim_type == ClaimType.AUTO_COLLISION
    assert result.fields["incident_date"].grounded  # evidence quoted verbatim from the document


def test_refusal_is_a_hard_error(mock_api):
    _, responses = mock_api
    responses.append(httpx.Response(200, json=_message(None, stop_reason="refusal")))
    with pytest.raises(llm.LLMError, match="declined"):
        ClaudeExtractor(Settings()).extract(DOCUMENT)


def test_truncated_output_is_a_hard_error(mock_api):
    _, responses = mock_api
    responses.append(httpx.Response(200, json=_message('{"policy_number": {', stop_reason="max_tokens")))
    with pytest.raises(llm.LLMError):
        ClaudeExtractor(Settings()).extract(DOCUMENT)


@pytest.mark.parametrize("status", [429, 529, 500])
def test_overload_and_rate_limits_are_retryable(mock_api, status):
    _, responses = mock_api
    responses.append(
        httpx.Response(status, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
    )
    with pytest.raises(llm.LLMTransientError):
        ClaudeExtractor(Settings()).extract(DOCUMENT)


def test_bad_request_is_not_retryable(mock_api):
    _, responses = mock_api
    responses.append(
        httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}})
    )
    with pytest.raises(llm.LLMError) as excinfo:
        ClaudeExtractor(Settings()).extract(DOCUMENT)
    assert not isinstance(excinfo.value, llm.LLMTransientError)
