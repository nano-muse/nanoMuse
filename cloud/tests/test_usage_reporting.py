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


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("outcome", ["error", "empty", "metadata", "reasoning", "tool", "tool_estimated"])
async def test_charges_only_completions_with_generated_output(stream, outcome):
    _, client, sender, upstream, cloud = make_stack()
    upstream.router.routes[:] = [route for route in upstream.router.routes if getattr(route, "path", "") != "/compat/v1/chat/completions"]
    usage = {"prompt_tokens": 41, "completion_tokens": 12}
    tools = {"tool_calls": [{"index": 0, "function": {"name": "lookup", "arguments": "{}"}}]}

    @upstream.post("/compat/v1/chat/completions")
    async def chat():
        if outcome == "error":
            packets = [{"error": {"code": "failed"}, "usage": usage}]
        elif outcome == "empty":
            packets = []
        else:
            message = {"role": "assistant", "content": ""}
            if outcome == "reasoning":
                message["reasoning_content"] = "Working this out"
            if outcome.startswith("tool"):
                message.update(tools)
            packets = [{"choices": [{"delta" if stream else "message": message}]}]
            if outcome != "tool_estimated":
                if stream:
                    packets.append({"choices": [], "usage": usage})
                else:
                    packets[0]["usage"] = usage
        if not stream:
            return packets[0] if packets else {"choices": []}

        async def frames():
            for packet in packets:
                yield f"data: {json.dumps(packet)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(frames(), media_type="text/event-stream")

    async with client:
        signed = await sign_up(client, sender)
        headers = {"Authorization": f"Bearer {signed['api_key']}"}
        response = await client.post(
            "/v1/chat/completions",
            headers=headers,
            json={"model": "deepseek-v4.1-flash", "stream": stream, "messages": [{"role": "user", "content": "hello"}]},
        )
        recent = (await client.get("/v1/me", headers=headers)).json()["recent"]
        charges = [r for r in recent if r["kind"] == "chat"]
        assert not cloud.in_flight.snapshot()
        call = cloud.db.calls_since(0)[0]
        if outcome in {"error", "empty", "metadata"}:
            assert response.status_code == (200 if stream else 502)
            assert '"error"' in response.text
            if stream:
                assert response.text.count("[DONE]") == 1 and response.text.index('"error"') < response.text.index("[DONE]")
            assert charges == []
            assert call["status"] != "ok" and call["prompt_tokens"] == call["completion_tokens"] == 0
        else:
            assert response.status_code == 200 and '"error"' not in response.text
            assert call["status"] == "ok" and len(charges) == 1
            if outcome == "tool_estimated":
                assert charges[0]["completion_tokens"] > 0
            else:
                assert charges[0]["prompt_tokens"] == 41 and charges[0]["completion_tokens"] == 12


@pytest.mark.parametrize("ending", ["error_packet", "eof"])
async def test_interrupted_stream_charges_partial_tool_output_once(ending):
    _, client, sender, upstream, cloud = make_stack()
    upstream.router.routes[:] = [route for route in upstream.router.routes if getattr(route, "path", "") != "/compat/v1/chat/completions"]

    @upstream.post("/compat/v1/chat/completions")
    async def chat():
        async def frames():
            delta = {"tool_calls": [{"index": 0, "function": {"name": "lookup", "arguments": "{}"}}]}
            yield f"data: {json.dumps({'choices': [{'delta': delta}]})}\n\n"
            if ending == "error_packet":
                yield 'data: {"error":{"code":"failed"},"usage":{"prompt_tokens":9000,"completion_tokens":8000}}\n\n'

        return StreamingResponse(frames(), media_type="text/event-stream")

    async with client:
        signed = await sign_up(client, sender)
        headers = {"Authorization": f"Bearer {signed['api_key']}"}
        response = await client.post(
            "/v1/chat/completions",
            headers=headers,
            json={"model": "deepseek-v4.1-flash", "stream": True, "messages": [{"role": "user", "content": "hello"}]},
        )
        assert response.status_code == 200 and response.text.index('"tool_calls"') < response.text.index('"error"') < response.text.index(
            "[DONE]"
        )
        assert not cloud.in_flight.snapshot() and cloud.db.calls_since(0)[0]["status"] != "ok"
        recent = (await client.get("/v1/me", headers=headers)).json()["recent"]
        charges = [r for r in recent if r["kind"] == "chat"]
        assert len(charges) == 1 and 0 < charges[0]["completion_tokens"] < 8000
