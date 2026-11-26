"""Previously installed clients use the same Cloud account and chat API after the provider switch."""

from __future__ import annotations

import json

import httpx
import pytest
from test_cloud import APP_UA, sign_up

from nanomuse_cloud.api import create_app
from nanomuse_cloud.config import PREVIOUS_CLOUD_MODEL, QIANFAN_BASE, QIANFAN_CHAT, QIANFAN_GUI, QIANFAN_IMAGE, QIANFAN_VIDEO, Settings
from nanomuse_cloud.db import Database
from nanomuse_cloud.senders import LogSender
from nanomuse_cloud.service import Cloud


@pytest.fixture
def qianfan(monkeypatch):
    monkeypatch.delenv("CLOUD_MODELS")
    monkeypatch.delenv("CLOUD_MEDIA_ENABLED")
    monkeypatch.setenv("UPSTREAM_BASE", QIANFAN_BASE)
    monkeypatch.setenv("QIANFAN_API_KEY", "primary-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "compat-key")
    return Settings(database=":memory:", secret="test-secret", per_minute_requests=100)


def test_qianfan_credentials_and_prices(monkeypatch, qianfan):
    assert qianfan.upstream_key == "primary-key"
    assert not qianfan.any_model_members and not qianfan.catalog_enabled
    assert qianfan.unlisted_model("some-other-model", "chat") is None
    assert qianfan.model(QIANFAN_CHAT).cached_in_rate == 0.02
    gui = qianfan.model(QIANFAN_GUI)
    assert gui.chat_cost_uy(131072, 200) == round(131072 * 1.2 + 200 * 7.2)
    assert gui.chat_cost_uy(131073, 200) == 131073 * 3 + 200 * 18
    monkeypatch.delenv("QIANFAN_API_KEY")
    assert Settings().upstream_key == "compat-key"
    monkeypatch.delenv("DASHSCOPE_API_KEY")
    monkeypatch.setenv("UPSTREAM_KEY", "previous-provider")
    assert Settings().upstream_key == ""
    monkeypatch.setenv("QIANFAN_API_KEY", "baidu-only")
    monkeypatch.setenv("UPSTREAM_BASE", "https://self-hosted.invalid/v1")
    assert Settings().upstream_key == "previous-provider"


async def test_qianfan_cached_models_and_hands_share_the_same_account(qianfan):
    calls = []

    def upstream(req: httpx.Request) -> httpx.Response:
        assert req.url == f"{QIANFAN_BASE}/chat/completions"
        assert req.headers["authorization"] == "Bearer primary-key"
        assert "x-nanomuse-trajectory" not in req.headers
        body = json.loads(req.content)
        calls.append(body)
        usage = {"prompt_tokens": 1000, "completion_tokens": 100}
        message = {"choices": [{"message": {"content": "ok"}}], "usage": usage}
        if body.get("stream"):
            answer = {"choices": [{"delta": {"content": "ok"}}]}
            return httpx.Response(
                200, content=f"data: {json.dumps(answer)}\n\ndata: {json.dumps({'choices': [], 'usage': usage})}\n\ndata: [DONE]\n\n"
            )
        return httpx.Response(200, json=message)

    sender = LogSender()
    cloud = Cloud(qianfan, Database(":memory:"), sender)
    app = create_app(qianfan, cloud, upstream_transport=httpx.MockTransport(upstream))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cloud.test", headers=APP_UA) as client:
        signed = await sign_up(client, sender)
        auth = {"Authorization": f"Bearer {signed['api_key']}"}
        listing = (await client.get("/v1/models", headers=auth)).json()
        assert [m["id"] for m in listing["data"]] == [QIANFAN_CHAT, QIANFAN_GUI, QIANFAN_IMAGE, QIANFAN_VIDEO]
        assert listing["data"][0]["nanomuse"]["recommended_for"] == ["chat"]
        assert listing["data"][1]["nanomuse"]["recommended_for"] == ["gui"]
        old = await client.get(f"/v1/models/{PREVIOUS_CLOUD_MODEL}", headers=auth)
        assert old.status_code == 200 and old.json()["id"] == QIANFAN_CHAT
        assert (await client.get("/v1/models/", headers=auth)).json() == listing
        prompt = {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://image.invalid/picture.png"}}]}
        for saved in (PREVIOUS_CLOUD_MODEL, "deepseek-v4.1-flash", "qwen3.8-27b", "qwen3.8-flash"):
            reply = await client.post(
                "/v1/chat/completions", headers=auth, json={"model": saved, "messages": [prompt], "reasoning_effort": "high"}
            )
            assert reply.status_code == 200 and reply.json()["model"] == QIANFAN_CHAT
            assert calls[-1]["model"] == QIANFAN_CHAT and calls[-1]["thinking"] == {"type": "enabled"}
            assert "enable_thinking" not in calls[-1]
        old_screen = {
            "role": "system",
            "content": "You are the hands of Muse, a personal agent, on the user's own Android phone. You see the screen only as a screenshot.",
        }
        for saved, messages, headers in (
            (PREVIOUS_CLOUD_MODEL, [prompt], {**auth, "X-NanoMuse-Trajectory": "screen-run"}),
            (PREVIOUS_CLOUD_MODEL, [old_screen, prompt], auth),
            (QIANFAN_GUI, [prompt], auth),
        ):
            reply = await client.post("/v1/chat/completions", headers=headers, json={"model": saved, "messages": messages, "stream": True})
            assert reply.status_code == 200 and "[DONE]" in reply.text
            assert calls[-1]["model"] == QIANFAN_GUI and calls[-1]["enable_thinking"] is False
            assert "thinking" not in calls[-1] and calls[-1]["stream_options"] == {"include_usage": True}
        assert all(call["model"] != PREVIOUS_CLOUD_MODEL for call in calls)
        assert len({call["user"] for call in calls}) == 1
        before = len(calls)
        unknown = await client.post("/v1/chat/completions", headers=auth, json={"model": "unoffered", "messages": [prompt]})
        assert unknown.status_code == 404 and len(calls) == before
