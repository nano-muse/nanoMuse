"""Admission follows the final Qianfan model, including requests from earlier apps."""

import asyncio
import json

import httpx
import pytest
from test_cloud import APP_UA, sign_up

from nanomuse_cloud.api import create_app
from nanomuse_cloud.config import PREVIOUS_CLOUD_MODEL, QIANFAN_BASE, QIANFAN_CHAT, QIANFAN_GUI, Settings
from nanomuse_cloud.db import Database
from nanomuse_cloud.senders import LogSender
from nanomuse_cloud.service import Cloud


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "{}",
        json.dumps({QIANFAN_CHAT: 60}),
        json.dumps({QIANFAN_CHAT: 60, PREVIOUS_CLOUD_MODEL: 60}),
        json.dumps({QIANFAN_CHAT: 60, QIANFAN_GUI: 60, "other": 2}),
        json.dumps({QIANFAN_CHAT: True, QIANFAN_GUI: 1}),
        json.dumps({QIANFAN_CHAT: 1, QIANFAN_GUI: 0}),
        json.dumps({QIANFAN_CHAT: 1, QIANFAN_GUI: -1}),
        json.dumps({QIANFAN_CHAT: 1, QIANFAN_GUI: 2.5}),
        json.dumps({QIANFAN_CHAT: 1, QIANFAN_GUI: "2"}),
        f'{{"{QIANFAN_CHAT}":1,"{QIANFAN_GUI}":2,"{QIANFAN_CHAT}":3}}',
    ],
)
def test_rejects_invalid_model_limits_for_qianfan(monkeypatch, raw):
    monkeypatch.delenv("CLOUD_MODELS", raising=False)
    monkeypatch.setenv("CHAT_MODEL_CONCURRENCY", raw)
    with pytest.raises(ValueError, match="CHAT_MODEL_CONCURRENCY"):
        Settings(upstream_base=QIANFAN_BASE)


def test_only_explicit_qianfan_configuration_splits_the_pool(monkeypatch):
    monkeypatch.delenv("CLOUD_MODELS", raising=False)
    monkeypatch.delenv("CHAT_MODEL_CONCURRENCY", raising=False)
    assert Settings(upstream_base=QIANFAN_BASE).chat_model_concurrency == {}
    limits = {QIANFAN_CHAT: 60, QIANFAN_GUI: 60}
    monkeypatch.setenv("CHAT_MODEL_CONCURRENCY", json.dumps(limits))
    assert Settings(upstream_base=QIANFAN_BASE + "/").chat_model_concurrency == limits
    assert Settings(upstream_base="https://self-hosted.invalid/v1").chat_model_concurrency == {}


@pytest.mark.parametrize("split", [False, True])
async def test_stream_and_nonstream_use_the_final_models_gate(monkeypatch, split):
    monkeypatch.delenv("CLOUD_MODELS", raising=False)
    monkeypatch.setenv("QIANFAN_API_KEY", "test-only")
    monkeypatch.setenv("CHAT_MODEL_CONCURRENCY", json.dumps({QIANFAN_CHAT: 1, QIANFAN_GUI: 1}) if split else "")
    settings = Settings(
        upstream_base=QIANFAN_BASE,
        database=":memory:",
        secret="test-only",
        admin_token="test-only",
        chat_concurrency=1,
        max_in_flight=8,
        record_turns=False,
    )
    admin = {"X-Admin-Token": settings.admin_token}
    sender = LogSender()
    cloud = Cloud(settings, Database(":memory:"), sender)
    release = {key: asyncio.Event() for key in ("chat", "second-chat", "screen", "second-screen")}
    started = {key: asyncio.Event() for key in release}
    routed = {}

    async def upstream(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        label = body["messages"][0]["content"]
        routed[label] = body["model"]
        started[label].set()
        await release[label].wait()
        if body.get("stream"):
            return httpx.Response(200, content='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    app = create_app(settings, cloud, upstream_transport=httpx.MockTransport(upstream))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cloud.test", headers=APP_UA) as client:
        signed = await sign_up(client, sender)
        auth = {"Authorization": f"Bearer {signed['api_key']}"}

        async def submit(label, model, stream=False, hands=False):
            headers = {**auth, "X-NanoMuse-Trajectory": "old-screen-run"} if hands else auth
            return await client.post(
                "/v1/chat/completions",
                headers=headers,
                json={"model": model, "stream": stream, "messages": [{"role": "user", "content": label}]},
            )

        async def state(active, waiting):
            while True:
                view = (await client.get("/v1/admin/live", headers=admin)).json()
                if view["gate"]["active"] == active and view["gate"]["waiting"] == waiting:
                    return view
                await asyncio.sleep(0.005)

        async with asyncio.timeout(10), asyncio.TaskGroup() as group:
            chat = group.create_task(submit("chat", PREVIOUS_CLOUD_MODEL))
            await started["chat"].wait()
            screen = group.create_task(submit("screen", PREVIOUS_CLOUD_MODEL, stream=True, hands=True))
            if not split:
                view = await state(1, 1)
                assert view["model_gates"] == {} and view["settings"]["chat_concurrency"] == 1
                assert not started["screen"].is_set()
                release["chat"].set()
                await started["screen"].wait()
                release["screen"].set()
            else:
                await started["screen"].wait()  # legacy Hands can run while chat is full
                second_chat = group.create_task(submit("second-chat", "qwen3.8-flash", stream=True))
                second_screen = group.create_task(submit("second-screen", QIANFAN_GUI))
                view = await state(2, 2)
                assert view["gate"]["limit"] == view["settings"]["chat_concurrency"] == 2
                assert view["model_gates"] == {m: {"active": 1, "waiting": 1, "limit": 1} for m in (QIANFAN_CHAT, QIANFAN_GUI)}
                health = (await client.get("/v1/admin/health", headers=admin)).json()
                assert health["model_gates"] == view["model_gates"]
                assert health["chat_upstream"] == {**view["gate"], "retries": settings.chat_retries}
                release["screen"].set()
                await started["second-screen"].wait()
                assert not started["second-chat"].is_set()
                release["chat"].set()
                await started["second-chat"].wait()
                release["second-screen"].set()
                release["second-chat"].set()
                assert (await second_chat).status_code == (await second_screen).status_code == 200
            assert (await chat).status_code == (await screen).status_code == 200
        assert all(model == (QIANFAN_GUI if "screen" in label else QIANFAN_CHAT) for label, model in routed.items())
        await asyncio.wait_for(state(0, 0), timeout=2)
