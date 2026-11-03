"""Characterize upstream usage versus relay-only fallback accounting."""

import json

import pytest
from fastapi.responses import StreamingResponse
from test_cloud import make_stack, sign_up


@pytest.mark.asyncio
@pytest.mark.parametrize("reports_usage", [True, False])
async def test_stream_usage_is_measured_only_when_the_provider_reports_it(reports_usage):
    _, client, sender, upstream, _ = make_stack()
    upstream.router.routes[:] = [route for route in upstream.router.routes if getattr(route, "path", "") != "/compat/v1/chat/completions"]

    @upstream.post("/compat/v1/chat/completions")
    async def chat():
        async def frames():
            yield 'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            if reports_usage:
                yield 'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":5,"prompt_tokens_details":{"cached_tokens":70}}}\n\n'
            yield "data: [DONE]\n\n"

        return StreamingResponse(frames(), media_type="text/event-stream")

    async with client:
        signed = await sign_up(client, sender, identifier="usage@example.org")
        headers = {"Authorization": f"Bearer {signed['api_key']}"}
        response = await client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "model": "deepseek-v4.1-flash",
                "stream": True,
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert response.status_code == 200
        frames = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:") and "[DONE]" not in line]
        usages = [frame["usage"] for frame in frames if "usage" in frame]
        recent = (await client.get("/v1/me", headers=headers)).json()["recent"][0]
        if reports_usage:
            assert usages == [{"prompt_tokens": 100, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 70}}]
            assert recent["prompt_tokens"] == 100
            assert recent["completion_tokens"] == 5
        else:
            # This is an estimate in the relay ledger, not a provider measurement.
            assert usages == []
            assert recent["prompt_tokens"] > 0
            assert recent["completion_tokens"] > 0
