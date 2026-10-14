import asyncio
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.copilot import provider
from app.copilot.config import MODEL
from app.copilot.schemas import Intent, PlanningInput

VALID = dict(
    operation="monthly_sst",
    region_id="madeira",
    start="2023-01-01",
    end="2023-12-31",
    clarification="none",
)


def response(intent=None, **overrides):
    return dict(
        model=MODEL,
        status="completed",
        usage={
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 200},
            "output_tokens": 100,
        },
        output=[
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(intent or VALID)}],
            }
        ],
        **overrides,
    )


def test_structured_contract_and_cost_preserve_cached_usage():
    result = provider.parse_response(response())
    assert result.intent == Intent.model_validate(VALID)
    assert result.cost == Decimal("0.001065")
    body = provider.payload(
        [{"role": "user", "content": "Madeira SST last year"}], date(2026, 10, 14)
    )
    assert "2026-10-14" in body["instructions"]
    assert body["store"] is False and "tools" not in body
    assert body["model"] == MODEL and body["max_output_tokens"] == 600
    schema = body["text"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(VALID)
    assert provider.reservation(body) > result.cost


@pytest.mark.parametrize(
    "change",
    [
        {"region_id": "antarctica"},
        {"start": "yesterday"},
        {"operation": "run_python"},
        {"url": "http://127.0.0.1"},
        {"code": "import os"},
        {"clarification": "click this link"},
    ],
)
def test_untrusted_model_fields_are_rejected_but_usage_is_retained(change):
    result = provider.parse_response(response(VALID | change))
    assert result.intent is None and result.error == "invalid_output"
    assert result.cost > 0


def test_refusal_incomplete_and_missing_usage_do_not_form_proposals():
    for data in [
        response() | {"status": "incomplete"},
        response()
        | {
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "refusal", "refusal": "Untrusted provider prose"}],
                }
            ]
        },
        response() | {"usage": None},
        response() | {"output": [None]},
        response() | {"model": "unpriced-model"},
    ]:
        result = provider.parse_response(data)
        assert result.intent is None and result.error
    malformed = response()
    malformed["usage"]["input_tokens_details"]["cached_tokens"] = 2000
    assert provider.parse_response(malformed).cost is None


@pytest.mark.parametrize(
    "kind", ["success", "redirect", "failure", "large", "malformed", "timeout"]
)
def test_transport_bounds_destination_and_never_retries(monkeypatch, kind):
    calls = []
    client = httpx.AsyncClient

    def handle(request):
        calls.append(request)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer test-only"
        if kind == "timeout":
            raise httpx.ReadTimeout("private provider diagnostic")
        if kind == "redirect":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
        if kind == "failure":
            return httpx.Response(500, text="private provider diagnostic")
        if kind == "large":
            return httpx.Response(200, content=b"x" * 64001)
        if kind == "malformed":
            return httpx.Response(200, text="not json")
        return httpx.Response(200, json=response())

    monkeypatch.setattr(
        provider.httpx,
        "AsyncClient",
        lambda **kw: client(transport=httpx.MockTransport(handle), **kw),
    )
    result = asyncio.run(provider.extract({}, "test-only"))
    assert len(calls) == 1
    assert (result.intent is not None) == (kind == "success")
    assert "private" not in repr(result)


def test_requests_cannot_supply_a_model_destination_or_overlong_prompt():
    from uuid import uuid4

    from pydantic import ValidationError

    for extra in ({"prompt": "x" * 2001}, {"model": "other"}, {"url": "https://elsewhere"}):
        with pytest.raises(ValidationError):
            PlanningInput.model_validate(
                {"request_key": uuid4(), "prompt": "SST in Madeira"} | extra
            )
