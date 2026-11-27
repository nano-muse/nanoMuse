from __future__ import annotations

from types import SimpleNamespace as NS

import openai
import pytest

from nanomuse.config import LLMSettings
from nanomuse.llm.openai_chat import PartialStreamError
from nanomuse.llm.openai_responses import OpenAIResponsesLLM, _response_failure


class _Stream:
    def __init__(self, events):
        self.events = list(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.events:
            raise StopAsyncIteration
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("rate_limit_exceeded", openai.RateLimitError),
        ("server_error", openai.InternalServerError),
        ("vector_store_timeout", openai.InternalServerError),
        ("invalid_prompt", openai.BadRequestError),
        ("data_residency_mismatch", openai.BadRequestError),
        ("invalid_image", openai.BadRequestError),
    ],
)
def test_response_failed_is_classified(code, expected):
    assert isinstance(_response_failure(NS(code=code, message="failed")), expected)


async def test_visible_responses_delta_is_not_retried():
    import httpx

    llm = OpenAIResponsesLLM(
        LLMSettings(api_key="x", base_url="http://localhost", stream=True, max_retries=2)
    )
    calls = 0

    async def fake_create(**_):
        nonlocal calls
        calls += 1
        return _Stream(
            [
                NS(type="response.output_text.delta", delta="visible"),
                openai.APIConnectionError(request=httpx.Request("POST", "http://localhost")),
            ]
        )

    llm.client.responses.create = fake_create  # type: ignore[method-assign]
    deltas: list[str] = []
    with pytest.raises(PartialStreamError):
        await llm._send({"model": "m", "input": []}, deltas.append)
    assert calls == 1 and deltas == ["visible"]
