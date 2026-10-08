"""End-to-end through the ASGI app, with a fake provider standing in for the upstream."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from nanomuse_cloud.api import create_app
from nanomuse_cloud.config import Settings
from nanomuse_cloud.db import Database
from nanomuse_cloud.identifiers import BadIdentifier, parse
from nanomuse_cloud.senders import LogSender
from nanomuse_cloud.service import Cloud, CloudError

PNG_1PX = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


# the catalogue's facts the two 0.17 key ways carry since 0.21 (providers.py; additive fields)
WAY_FACTS = {
    "bailian": {
        "name": "Alibaba Cloud Bailian",
        "name_zh": "阿里云百炼",
        "key_url": "https://bailian.console.aliyun.com/?apiKey=1",
        "covers": ["chat", "vision", "image", "video"],
        "auth": ["key"],
    },
    "openrouter": {
        "name": "OpenRouter",
        "name_zh": "OpenRouter",
        "key_url": "https://openrouter.ai/keys",
        "covers": ["chat", "vision", "image"],
        "auth": ["key", "oauth-openrouter"],
    },
}


def fake_upstream() -> FastAPI:
    up = FastAPI()
    up.state.requests = []

    # what the provider lists under the key: chat and picture models, and the spoken / heard /
    # embedded ones the catalog leaves out (ids only, as Model Studio's compatible mode gives them)
    up.state.catalog_ids = [
        "qwen3.8-27b",
        "deepseek-v4-pro",
        "qwen3-vl-plus",
        "vanchin/deepseek-v3",
        "qwen-image-edit-max",
        "wan2.7-image",
        "qwen3-tts-flash",
        "qwen3.7-text-embedding",
        "qwen3-omni-flash-realtime",
        "fun-asr-flash-2026-06-15",
    ]

    @up.get("/compat/v1/models")
    async def models(request: Request):
        up.state.requests.append(("models", dict(request.headers), None))
        if up.state.catalog_ids is None:  # the provider is down
            return JSONResponse(status_code=503, content={"error": {"message": "unavailable"}})
        return {"object": "list", "data": [{"id": i, "object": "model", "owned_by": "system"} for i in up.state.catalog_ids]}

    # what the probes find (catalog.py): the retired model answers 4xx, these read the picture
    up.state.retired = {"qwen-1.8b-chat"}
    up.state.sighted = {"qwen3-vl-plus", "deepseek-v4-pro", "qwen3.8-27b"}

    @up.post("/compat/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        up.state.requests.append(("chat", dict(request.headers), body))
        if body.get("model") == "boom":
            return JSONResponse(status_code=500, content={"error": {"message": "upstream exploded"}})
        if body.get("model") in up.state.retired:
            return JSONResponse(status_code=400, content={"error": {"message": "Model not exist.", "code": "invalid_parameter_error"}})
        if body.get("reasoning_effort") not in (None, "none") and body.get("enable_thinking") is False:
            # Model Studio's actual refusal of an app's thinking level next to the relay's old default
            return JSONResponse(
                status_code=400,
                content={
                    "error": {"message": "'reasoning_effort' must be 'none' when 'enable_thinking' is false", "code": "InvalidParameter"}
                },
            )
        pictured = any(
            isinstance(m.get("content"), list)
            and any(p.get("type") == "image_url" for p in m["content"] if isinstance(p, dict))
            and any("colour" in str(p.get("text", "")) for p in m["content"] if isinstance(p, dict))  # the probe's question
            for m in body.get("messages") or []
            if isinstance(m, dict)
        )
        if pictured and not body.get("stream"):
            seen = body.get("model") in up.state.sighted
            return {
                "id": "c1",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Magenta." if seen else "Red."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 3, "total_tokens": 33},
            }
        thinking = body.get("enable_thinking") is True  # a thinking model's turn: reasoning first, then the words
        if body.get("stream"):

            async def gen():
                if thinking:
                    for piece in ("先想", "一下"):
                        chunk = {
                            "id": "c1",
                            "object": "chat.completion.chunk",
                            "model": body["model"],
                            "choices": [{"index": 0, "delta": {"reasoning_content": piece, "content": None}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                for piece in ("你好", "，", "世界"):
                    chunk = {
                        "id": "c1",
                        "object": "chat.completion.chunk",
                        "model": body["model"],
                        "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                if thinking:
                    # DashScope's native shape counts the reasoning apart from the words
                    usage = {"prompt_tokens": 40, "completion_tokens": 6, "output_tokens_details": {"reasoning_tokens": 20}}
                else:
                    usage = {"prompt_tokens": 40, "completion_tokens": 6}
                yield f"data: {json.dumps({'id': 'c1', 'object': 'chat.completion.chunk', 'choices': [], 'usage': usage})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")
        message = {"role": "assistant", "content": "hi"}
        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        if thinking:
            message = {"role": "assistant", "reasoning_content": "先想一下", "content": "hi"}
            # OpenAI's shape: the reasoning is inside completion_tokens, broken down below it
            usage = {**usage, "completion_tokens_details": {"reasoning_tokens": 30}}
        return {
            "id": "c1",
            "object": "chat.completion",
            "model": body["model"],
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": usage,
        }

    up.state.image_429s = 0  # how many times the next pictures are refused with a 429 first

    @up.post("/ds/api/v1/services/aigc/multimodal-generation/generation")
    async def draw(request: Request):
        body = await request.json()
        up.state.requests.append(("image", dict(request.headers), body))
        if up.state.image_429s > 0:
            up.state.image_429s -= 1
            return JSONResponse(
                status_code=429,
                content={"code": "Throttling.RateQuota", "message": "Requests rate limit exceeded, please try again later."},
            )
        return {"output": {"choices": [{"message": {"content": [{"image": "http://upstream/pic.png"}]}}]}}

    @up.get("/pic.png")
    async def pic():
        from fastapi.responses import Response

        return Response(content=PNG_1PX, media_type="image/png")

    # DashScope's asynchronous video API: submit, poll, upload policy.
    @up.post("/ds/api/v1/services/aigc/video-generation/video-synthesis")
    async def video(request: Request):
        body = await request.json()
        up.state.requests.append(("video", dict(request.headers), body))
        if body.get("model") == "nope":
            return JSONResponse(status_code=404, content={"code": "InvalidParameter", "message": "Model not exist"})
        if not body.get("input"):
            return JSONResponse(status_code=400, content={"code": "InvalidParameter", "message": "prompt is required"})
        nth = sum(1 for r in up.state.requests if r[0] == "video" and r[2].get("input"))
        return {"output": {"task_id": f"task-{41 + nth}", "task_status": "PENDING"}, "request_id": "r1"}

    @up.get("/ds/api/v1/tasks/{task_id}")
    async def task(task_id: str, request: Request):
        up.state.requests.append(("task", dict(request.headers), task_id))
        polls = sum(1 for r in up.state.requests if r[0] == "task" and r[2] == task_id)
        status = "RUNNING" if polls == 1 else "SUCCEEDED"
        return {"output": {"task_id": task_id, "task_status": status, "video_url": "http://upstream/clip.mp4"}}

    @up.get("/ds/api/v1/uploads")
    async def uploads(request: Request):
        up.state.requests.append(("uploads", dict(request.headers), dict(request.query_params)))
        return {"data": {"upload_dir": "tmp/x", "upload_host": "http://oss", "policy": "p", "signature": "s", "oss_access_key_id": "k"}}

    return up


@pytest.fixture
def stack():
    up = fake_upstream()
    settings = Settings(
        database=":memory:",
        secret="test-secret",
        admin_token="admin",
        upstream_base="http://upstream/compat/v1",
        upstream_key="sk-upstream",
        dashscope_base="http://upstream/ds/api/v1",
        signup_tokens=1000,
        daily_cap_tokens=100_000,
        per_minute_requests=100,
        public_base="http://cloud.test",
    )
    sender = LogSender()
    cloud = Cloud(settings, Database(":memory:"), sender)
    app = create_app(settings, cloud, upstream_transport=httpx.ASGITransport(app=up))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cloud.test")
    return app, client, sender, up, cloud


async def sign_up(client, sender, identifier="13800138000", device="pixel", invite="", headers=None):
    r = await client.post("/v1/auth/code", json={"identifier": identifier}, headers=headers)
    assert r.status_code == 204, r.text
    ident, code = sender.sent[-1]
    r = await client.post(
        "/v1/auth/verify", json={"identifier": identifier, "code": code, "device": device, "invite": invite}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_identifiers():
    assert parse("138 0013 8000").value == "+8613800138000"
    assert parse("+8613800138000").hint == "138****8000"
    assert parse("0086 13800138000").value == "+8613800138000"
    assert parse("+14155552671").channel == "phone"
    assert parse("Someone@Example.COM").value == "someone@example.com"
    assert parse("someone@example.com").hint == "so***@example.com"
    for bad in ("", "12345", "not an address", "@x.com", "1234567890123456789"):
        with pytest.raises(BadIdentifier):
            parse(bad)


async def test_signup_grants_and_lists_models(stack):
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    assert data["api_key"].startswith("nm_")
    assert data["created"] is True
    assert data["tokens"] == {"unlimited": False, "granted": 1000, "used": 0, "remaining": 1000, "used_today": 0, "daily_cap": 100_000}
    assert data["account"]["hint"] == "138****8000"
    assert data["base_url"] == "http://cloud.test"
    ids = [m["id"] for m in data["models"]]
    assert "qwen3.8-27b" in ids and "qwen-image-3.0" in ids and "wan2.2-i2v-flash" in ids
    video = next(m for m in data["models"] if m["id"] == "wan2.2-i2v-flash")
    assert video["nanomuse"]["kind"] == "video" and video["architecture"]["output_modalities"] == ["video"]

    headers = {"Authorization": f"Bearer {data['api_key']}"}
    r = await client.get("/v1/models", headers=headers)
    assert r.status_code == 200
    plus = next(m for m in r.json()["data"] if m["id"] == "qwen3.8-27b")
    assert plus["architecture"]["input_modalities"] == ["text", "image"]
    assert plus["nanomuse"]["recommended"] is True

    # The same number again: same account, a second key, no second grant.
    again = await sign_up(client, sender, device="tablet")
    assert again["created"] is False
    assert again["tokens"]["granted"] == 1000
    assert again["api_key"] != data["api_key"]


async def test_wrong_code_and_expiry_rules(stack):
    app, client, sender, up, cloud = stack
    r = await client.post("/v1/auth/code", json={"identifier": "a@mail.example"})
    assert r.status_code == 204
    r = await client.post("/v1/auth/verify", json={"identifier": "a@mail.example", "code": "000000"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_wrong"
    r = await client.post("/v1/auth/verify", json={"identifier": "a@mail.example", "code": "12"})
    assert r.status_code == 400
    r = await client.post("/v1/auth/verify", json={"identifier": "nobody@mail.example", "code": "123456"})
    assert r.json()["error"]["code"] == "code_expired"
    r = await client.post("/v1/auth/code", json={"identifier": "garbage"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_identifier"
    # Three codes in ten minutes is the ceiling per identifier.
    for _ in range(2):
        assert (await client.post("/v1/auth/code", json={"identifier": "a@mail.example"})).status_code == 204
    r = await client.post("/v1/auth/code", json={"identifier": "a@mail.example"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "code_too_often"


async def test_a_stored_code_cannot_be_read_back_from_the_database(stack):
    """Six digits are a lookup table. Hashed plainly, a code is recoverable by anyone who can
    read the database — a backup, a stolen file — so the relay's own secret must be part of it.
    A plain `sha256(code)` row fails this test; the fix is the keyed hash in `service`."""
    app, client, sender, up, cloud = stack
    await client.post("/v1/auth/code", json={"identifier": "a@mail.example"})
    _, code = sender.sent[-1]
    stored = str(cloud.db.live_code(parse("a@mail.example").hash(cloud.s.hmac_key))["code_hash"])
    assert stored != hashlib.sha256(code.encode()).hexdigest()
    # the person's own try still works, so the keyed form is checked the same way
    r = await client.post("/v1/auth/verify", json={"identifier": "a@mail.example", "code": code})
    assert r.status_code == 200, r.text


def test_a_relay_that_sends_codes_refuses_to_start_without_a_secret():
    """`CODE_SENDER=smtp` with no `CLOUD_SECRET` would hash every identifier with the published
    development key, so whoever holds the database alone reads the member list and any live
    code. The command line exits on this; a relay built any other way is refused as well."""
    sending = Settings(database=":memory:", sender="smtp", smtp_host="smtp.test", smtp_from="nanoMuse <no-reply@test>")
    assert sending.dev_mode
    with pytest.raises(RuntimeError, match="CLOUD_SECRET"):
        Cloud(sending, Database(":memory:"))
    # the same relay with a secret starts, and a relay whose codes only reach the log may not
    Cloud(dataclasses.replace(sending, secret="s"), Database(":memory:"))
    Cloud(dataclasses.replace(sending, sender="log"), Database(":memory:"))


async def test_chat_is_relayed_and_charged(stack):
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    headers = {"Authorization": f"Bearer {data['api_key']}"}

    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "hi"
    assert r.json()["model"] == "qwen3.8-27b"
    assert r.headers["x-nanomuse-charged"] == "150"
    kind, up_headers, up_body = up.state.requests[-1]
    assert up_headers["authorization"] == "Bearer sk-upstream"
    assert up_body["model"] == "qwen3.8-27b" and up_body["user"]
    assert up_body["enable_thinking"] is False  # CHAT_DEFAULTS filled in

    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["tokens"]["used"] == 150 and me["tokens"]["remaining"] == 850
    assert me["recent"][0]["kind"] == "chat" and me["recent"][0]["charged"] == 150

    # Flash is cheaper: 100×0.3 + 50×0.3 = 45.
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-flash", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.headers["x-nanomuse-charged"] == "45"

    # A model we do not offer is refused before anything is forwarded.
    n = len(up.state.requests)
    r = await client.post("/v1/chat/completions", headers=headers, json={"model": "gpt-4o", "messages": []})
    assert r.status_code == 404 and r.json()["error"]["code"] == "model_not_offered"
    assert len(up.state.requests) == n

    # Upstream failures come back as 502 in the relay's words (the provider's under
    # ``upstream``), uncharged.
    used = cloud.me(cloud.authenticate(data["api_key"]))["tokens"]["used"]
    settings = app.state.settings
    object.__setattr__(settings, "models", settings.models + (type(settings.models[0])(id="boom", name="Boom", upstream="boom"),))
    r = await client.post("/v1/chat/completions", headers=headers, json={"model": "boom", "messages": []})
    assert r.status_code == 502
    err = r.json()["error"]
    assert err["code"] == "upstream_500" and "exploded" not in err["message"] and "exploded" in err["upstream"]
    assert cloud.me(cloud.authenticate(data["api_key"]))["tokens"]["used"] == used


async def test_stream_refused_upstream_is_not_charged(stack):
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    settings = app.state.settings
    object.__setattr__(settings, "models", settings.models + (type(settings.models[0])(id="boom", name="Boom", upstream="boom"),))
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        headers=headers,
        json={"model": "boom", "stream": True, "messages": [{"role": "user", "content": "hi " * 500}]},
    ) as r:
        assert r.status_code == 200
        body = (await r.aread()).decode()
    lines = [ln for ln in body.split("\n") if ln.startswith("data:")]
    assert lines[-1] == "data: [DONE]"
    err = json.loads(lines[0][5:])["error"]
    assert err["code"] == "upstream_500" and err["upstream"] == "upstream exploded"
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["tokens"]["used"] == 0  # nothing was generated, nothing is owed
    assert not [row for row in me["recent"] if row["kind"] == "chat"]


async def test_stream_passes_through_and_charges_from_usage_chunk(stack):
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        headers=headers,
        json={"model": "qwen3.8-27b", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = (await r.aread()).decode()
    lines = [ln for ln in body.split("\n") if ln.startswith("data:")]
    assert lines[-1] == "data: [DONE]"
    pieces = []
    for ln in lines[:-1]:
        obj = json.loads(ln[5:])
        assert obj.get("model") in ("qwen3.8-27b", None)
        for ch in obj.get("choices", []):
            pieces.append(ch["delta"]["content"])
    assert "".join(pieces) == "你好，世界"
    up_body = up.state.requests[-1][2]
    assert up_body["stream_options"] == {"include_usage": True}
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["tokens"]["used"] == 46  # 40 + 6 from the usage chunk


async def test_out_of_tokens_and_bad_keys(stack):
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    # Seven full-price calls of 150 exhaust a 1000-token grant.
    for _ in range(7):
        r = await client.post(
            "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
        )
        assert r.status_code == 200
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 402 and r.json()["error"]["code"] == "out_of_tokens"

    # An admin top-up brings it back.
    me = (await client.get("/v1/me", headers=headers)).json()
    accounts = (await client.get("/v1/admin/accounts", headers={"X-Admin-Token": "admin"})).json()["accounts"]
    assert accounts[0]["hint"] == me["account"]["hint"]
    r = await client.post("/v1/admin/grant", headers={"X-Admin-Token": "admin"}, json={"account_id": accounts[0]["id"], "tokens": 500})
    assert r.status_code == 200
    # ...or by the phone number itself, which is hashed the same way.
    r = await client.post("/v1/admin/grant", headers={"X-Admin-Token": "admin"}, json={"identifier": "138 0013 8000", "tokens": 0})
    assert r.status_code == 200 and r.json()["granted"] == 1500
    r = await client.post("/v1/admin/grant", headers={"X-Admin-Token": "admin"}, json={"identifier": "nobody@example.com", "tokens": 1})
    assert r.status_code == 404
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 200
    assert (await client.get("/v1/admin/accounts")).status_code == 401

    # Bad, missing and revoked keys.
    assert (await client.get("/v1/models")).status_code == 401
    assert (await client.get("/v1/models", headers={"Authorization": "Bearer nm_nope"})).status_code == 401
    assert (await client.get("/v1/models", headers={"Authorization": "Bearer sk-other"})).status_code == 401
    assert (await client.post("/v1/auth/sign-out", headers=headers)).status_code == 204
    r = await client.get("/v1/me", headers=headers)
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_key"


async def test_a_rate_limited_picture_is_tried_again_behind_the_gate(stack, monkeypatch):
    """DashScope allows an account a couple of image tasks at a time and says 429 past that.
    The relay waits it out (with growing pauses) instead of handing the app a 502 that
    quotes the provider; only when it never clears does the app hear `provider_busy`."""
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    accounts = (await client.get("/v1/admin/accounts", headers={"X-Admin-Token": "admin"})).json()["accounts"]
    await client.post("/v1/admin/grant", headers={"X-Admin-Token": "admin"}, json={"account_id": accounts[0]["id"], "tokens": 1_000_000})
    naps: list[float] = []

    async def no_sleep(seconds: float) -> None:
        naps.append(seconds)

    monkeypatch.setattr("nanomuse_cloud.api.asyncio.sleep", no_sleep)

    up.state.image_429s = 2
    r = await client.post("/v1/images/generations", headers=headers, json={"model": "qwen-image-3.0", "prompt": "a dragon"})
    assert r.status_code == 200, r.text
    assert naps == [2.0, 4.0]
    assert sum(1 for k, _, _ in up.state.requests if k == "image") == 3
    assert r.headers["x-nanomuse-charged"] == "30000"

    # never clears: a 429 of the relay's own, a stable code, no charge
    naps.clear()
    up.state.image_429s = 99
    before = (await client.get("/v1/me", headers=headers)).json()
    r = await client.post("/v1/images/generations", headers=headers, json={"model": "qwen-image-3.0", "prompt": "a dragon"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "provider_busy"
    assert r.json()["error"]["retry_after"] == 20
    assert len(naps) == 4  # IMAGE_RETRIES
    after = (await client.get("/v1/me", headers=headers)).json()
    assert after["usage"] == before["usage"]
    up.state.image_429s = 0


async def test_pictures_are_drawn_a_couple_at_a_time(stack):
    """Six at once from six devices: the gate lets two through at a time, the rest queue,
    all six come back — the provider never sees more than two in flight."""
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    accounts = (await client.get("/v1/admin/accounts", headers={"X-Admin-Token": "admin"})).json()["accounts"]
    await client.post("/v1/admin/grant", headers={"X-Admin-Token": "admin"}, json={"account_id": accounts[0]["id"], "tokens": 1_000_000})
    in_flight = {"now": 0, "peak": 0}

    async def slow(request: Request):
        in_flight["now"] += 1
        in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
        await asyncio.sleep(0.05)
        in_flight["now"] -= 1
        return {"output": {"choices": [{"message": {"content": [{"image": "http://upstream/pic.png"}]}}]}}

    # the slow handler takes the place of the fake's usual one
    up.router.routes[:] = [
        rt for rt in up.router.routes if getattr(rt, "path", "") != "/ds/api/v1/services/aigc/multimodal-generation/generation"
    ]
    up.add_api_route("/ds/api/v1/services/aigc/multimodal-generation/generation", slow, methods=["POST"])

    rs = await asyncio.gather(
        *(
            client.post("/v1/images/generations", headers=headers, json={"model": "qwen-image-3.0", "prompt": f"dragon {i}"})
            for i in range(6)
        )
    )
    # four of one account's requests may be under way at once (MAX_IN_FLIGHT); the two
    # over that are told so rather than queued
    assert sorted(r.status_code for r in rs) == [200] * 4 + [429] * 2
    assert {r.json()["error"]["code"] for r in rs if r.status_code == 429} == {"too_many_in_flight"}
    assert in_flight["peak"] <= 2
    # once they are done, the account's slots are free again
    assert cloud.in_flight.count(cloud.authenticate(data["api_key"]).account_id) == 0


async def test_images_go_through_dashscope_native(stack):
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    # 30 000 per picture is more than the 1 000 grant: refused first.
    r = await client.post(
        "/v1/images/generations", headers=headers, json={"model": "qwen-image-3.0", "prompt": "a small dragon", "size": "1024x1024"}
    )
    assert r.status_code == 402
    accounts = (await client.get("/v1/admin/accounts", headers={"X-Admin-Token": "admin"})).json()["accounts"]
    await client.post("/v1/admin/grant", headers={"X-Admin-Token": "admin"}, json={"account_id": accounts[0]["id"], "tokens": 100_000})

    r = await client.post(
        "/v1/images/generations",
        headers=headers,
        json={"model": "qwen-image-3.0", "prompt": "a small dragon", "size": "1024x1024", "response_format": "b64_json"},
    )
    assert r.status_code == 200, r.text
    assert base64.b64decode(r.json()["data"][0]["b64_json"]) == PNG_1PX
    kind, up_headers, up_body = up.state.requests[-1]
    assert kind == "image" and up_body["model"] == "qwen-image-3.0"
    assert up_body["parameters"] == {"size": "1024*1024", "watermark": False, "prompt_extend": False}
    assert up_body["input"]["messages"][0]["content"] == [{"text": "a small dragon"}]
    assert r.headers["x-nanomuse-charged"] == "30000"

    r = await client.post(
        "/v1/images/edits",
        headers=headers,
        data={"model": "qwen-image-3.0", "prompt": "same dragon, waving", "n": "1", "size": "1024x1024"},
        files={"image": ("image0.png", PNG_1PX, "image/png")},
    )
    assert r.status_code == 200, r.text
    kind, up_headers, up_body = up.state.requests[-1]
    content = up_body["input"]["messages"][0]["content"]
    assert content[0]["image"].startswith("data:image/png;base64,") and content[1] == {"text": "same dragon, waving"}
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["tokens"]["used"] == 60_000


async def test_unconfigured_upstream_answers_503(stack):
    app, client, sender, up, cloud = stack
    object.__setattr__(app.state.settings, "upstream_key", "")
    data = await sign_up(client, sender)
    r = await client.post(
        "/v1/chat/completions", headers={"Authorization": f"Bearer {data['api_key']}"}, json={"model": "qwen3.8-27b", "messages": []}
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unconfigured"
    assert (await client.get("/healthz")).json()["ok"] is True


async def test_unconfigured_upstream_holds_nothing(stack):
    # Before 0.23.1 the chat and video routes reserved the turn's price and only then found
    # there was no key, so the hold was never settled: after max_in_flight such turns the
    # account was refused with too_many_in_flight until the holds timed out.
    app, client, sender, up, cloud = stack
    object.__setattr__(app.state.settings, "upstream_key", "")
    data = await sign_up(client, sender)
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    account_id = cloud.authenticate(data["api_key"]).account_id
    for _ in range(cloud.s.max_in_flight + 1):
        r = await client.post("/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": []})
        assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unconfigured"
        r = await client.post(
            "/api/v1/services/aigc/video-generation/video-synthesis",
            headers=headers,
            json={"model": "wan2.2-i2v-flash", "input": {"prompt": "a wave"}, "parameters": {"duration": 5}},
        )
        assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unconfigured"
    assert cloud.in_flight.count(account_id) == 0
    health = (await client.get("/v1/admin/health", headers={"X-Admin-Token": "admin"})).json()
    assert health["in_flight"]["requests"] == 0


def make_stack(**overrides):
    up = fake_upstream()
    kwargs = dict(
        database=":memory:",
        secret="test-secret",
        admin_token="admin",
        upstream_base="http://upstream/compat/v1",
        upstream_key="sk-upstream",
        dashscope_base="http://upstream/ds/api/v1",
        public_base="http://cloud.test",
    )
    kwargs.update(overrides)
    settings = Settings(**kwargs)
    sender = LogSender()
    cloud = Cloud(settings, Database(":memory:"), sender)
    app = create_app(settings, cloud, upstream_transport=httpx.ASGITransport(app=up))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cloud.test")
    return app, client, sender, up, cloud


async def test_private_relay_only_lets_listed_identifiers_in():
    app, client, sender, up, cloud = make_stack(allowed_identifiers="139 0000 1111, Me@Example.com", signup_open=False)
    r = await client.post("/v1/auth/code", json={"identifier": "13800138000"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_invited"
    assert sender.sent == []
    for ok in ("13900001111", "+8613900001111", "me@example.com"):
        r = await client.post("/v1/auth/code", json={"identifier": ok})
        assert r.status_code == 204, (ok, r.text)
    data = await sign_up(client, sender, identifier="me@example.com", device="desk")
    assert data["account"]["hint"] == "m***@example.com"
    assert data["account"]["member"] is True and data["spend"]["unlimited"] is True


async def test_open_signup_members_unlimited_everyone_else_has_one_allowance():
    # The released relay: anyone may sign in; the listed people have no limit,
    # the rest have one pool for good (¥10 in production) at the provider's
    # list prices — chat, pictures and clips alike.
    app, client, sender, up, cloud = make_stack(
        allowed_identifiers="Me@Example.com",
        signup_tokens=0,
        daily_cap_tokens=0,
        per_minute_requests=0,
        allowance_cny=0.002,
        invite_bonus_cny=5,
        usd_cny=7.0,
    )
    admin = {"X-Admin-Token": "admin"}
    guest = await sign_up(client, sender, identifier="13800138000", device="pixel")
    assert guest["account"]["member"] is False
    assert guest["spend"] == {
        "currency": "CNY",
        "total": 0,
        "grant": 0.002,
        "left": 0.002,
        "unlimited": False,
        "warn": False,
        "usd_cny": 7.0,
        "total_usd": 0,
        "grant_usd": 0.0003,
        "left_usd": 0.0003,
        "today": 0,
        "today_usd": 0,
        "allowance_cny": 0.002,
        "invite_bonus_cny": 5,
        "invitee_bonus_cny": 5,
        # the 0.5 co-creation bonus is gone; the names stay for the apps of the time
        "contribute_bonus_cny": 0,
        "contribute_bonus_available": False,
        "own_key_docs": "https://nanomuse.cn/own-key",
        "openrouter_url": "https://openrouter.ai/keys",
        # 0.17: a mainland phone account is pointed to Bailian first, then OpenRouter, then an invite;
        # 0.21 adds the catalogue's facts to the two key ways (additive) and the whole card as `guidance`
        "ways": [
            {"id": "bailian", "url": "https://nanomuse.cn/own-key", "mainland_only": True, **WAY_FACTS["bailian"]},
            {"id": "openrouter", "url": "https://openrouter.ai/keys", "mainland_only": False, **WAY_FACTS["openrouter"]},
            {"id": "invite", "url": guest["invite"]["url"], "bonus_cny": 5},
        ],
        "guidance": guest["spend"]["guidance"],
        # what a 0.4 app still reads: the pool as the "cap", no midnight
        "daily_cap": 0.002,
        "daily_cap_usd": 0.0003,
        "day_offset_h": 8,
        "resets_at": 0,
        "credit_left": 0,
        "left_today": 0.002,
    }
    assert guest["region"] == "cn"
    assert guest["clips"]["unlimited"] is True
    # the allowance is the first line of the statement
    assert guest["recent"][0]["kind"] == "credit" and guest["recent"][0]["detail"] == {"credit_uy": 2000, "from": "signup"}
    # Prices travel with the model list, so the apps can show them.
    price = next(m for m in guest["models"] if m["id"] == "qwen3.8-27b")["nanomuse"]["price_cny"]
    assert price["per_m_input"] == 3.0 and price["per_m_output"] == 12.0

    headers = {"Authorization": f"Bearer {guest['api_key']}"}
    # 100 prompt + 50 completion tokens at ¥3 / ¥12 per million = ¥0.0009.
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 200
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["spend"]["today"] == 0.0009 and me["spend"]["total"] == 0.0009 and me["spend"]["left"] == 0.0011
    assert me["spend"]["warn"] is False
    assert me["recent"][0]["cost_cny"] == 0.0009
    # Chats are priced after the fact, so one starts as long as anything is left:
    # the second and third go through (¥0.0027), the fourth does not — and the
    # refusal says what is left and where the two ways on lead.
    for _ in range(2):
        assert (
            await client.post(
                "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
            )
        ).status_code == 200
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["spend"]["left"] == 0 and me["spend"]["warn"] is True
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "allowance_exhausted" and "¥0.002" in err["message"] and "keep working" in err["message"]
    assert err["left"] == 0 and err["grant"] == 0.002 and err["own_key_docs"] == "https://nanomuse.cn/own-key"
    assert (
        err["invite_url"].startswith("https://nanomuse.cn/web/?invite=")
        and len(err["invite_url"]) == len("https://nanomuse.cn/web/?invite=") + 8
    )
    assert "co-creation" not in err["message"] and "invite a friend" in err["message"] and "own model key" in err["message"]
    assert err["invite_bonus_cny"] == 5 and err["invitee_bonus_cny"] == 5
    assert err["contribute_bonus_available"] is False and err["contribute_bonus_cny"] == 0
    # A picture that would go over is refused before it is drawn.
    r = await client.post("/v1/images/generations", headers=headers, json={"model": "qwen-image-3.0", "prompt": "a dragon"})
    assert r.status_code == 429 and not any(k == "image" for k, _, _ in up.state.requests)
    # The data switch earns nothing (there is no co-creation bonus any more) …
    r = await client.post("/v1/me/contribute", headers=headers, json={"on": True})
    assert r.status_code == 200 and r.json()["bonus_granted"] is False and r.json()["bonus_available"] is False
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["spend"]["grant"] == 0.002 and me["spend"]["left"] == 0 and me["contribute"]["on"] is True
    # … the operator's credit does (¥10): the chat goes through again.
    r = await client.post("/v1/admin/credit", headers=admin, json={"identifier": "13800138000", "cny": 10, "note": "thanks"})
    assert r.status_code == 200
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["spend"]["grant"] == 10.002 and me["spend"]["left"] == round(10.002 - 0.0027, 4) and me["spend"]["warn"] is False
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 200
    await client.post("/v1/me/contribute", headers=headers, json={"on": False})
    r = await client.post("/v1/me/contribute", headers=headers, json={"on": True})
    assert r.json()["bonus_granted"] is False
    assert (await client.get("/v1/me", headers=headers)).json()["spend"]["grant"] == 10.002

    # The listed person has no limit and sees none.
    member = await sign_up(client, sender, identifier="me@example.com", device="desk")
    assert member["account"]["member"] is True and member["spend"]["grant"] == 0 and member["spend"]["left"] is None
    assert member["spend"]["unlimited"] is True and member["spend"]["daily_cap"] == 0
    mh = {"Authorization": f"Bearer {member['api_key']}"}
    for _ in range(4):
        assert (
            await client.post(
                "/v1/chat/completions", headers=mh, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
            )
        ).status_code == 200
    r = await client.post("/v1/images/generations", headers=mh, json={"model": "qwen-image-3.0", "prompt": "a dragon"})
    assert r.status_code == 200
    me = (await client.get("/v1/me", headers=mh)).json()
    assert me["spend"]["today"] == round(4 * 0.0009 + 0.18, 4)

    # The operator's view carries money next to tokens, and can make a guest a member.
    listing = (await client.get("/v1/admin/accounts", headers=admin)).json()
    s = listing["settings"]
    assert s["signup_open"] is True and s["allowance_cny"] == 0.002 and s["usd_cny"] == 7.0
    assert s["invite_bonus_cny"] == 5 and s["invitee_bonus_cny"] == 5 and s["contributors"] == 1 and s["improve_default"] is False
    assert "daily_cap_cny" not in s and "video_clips_free" not in s
    assert s["prices"]["qwen-image-3.0"]["per_image"] == 0.18
    by_id = {a["identifier"]: a for a in listing["accounts"]}
    g, m = by_id["+8613800138000"], by_id["me@example.com"]
    assert g["member"] is False and g["spent_today_cny"] == 0.0036 and g["spent_cny"] == 0.0036
    assert g["grant_cny"] == 10.002 and g["left_cny"] == round(10.002 - 0.0036, 4) and g["contribute_bonus_at"] is None
    assert "credit_uy" not in g and "grant_uy" not in g and "clips_bonus" not in g
    assert m["member"] is True and m["listed"] is True and m["unlimited"] is False and m["left_cny"] is None
    usage = (await client.get("/v1/admin/usage", headers=admin)).json()["days"]
    assert {(u["kind"], u["cost_cny"]) for u in usage} == {("chat", round(8 * 0.0009, 4)), ("image", 0.18)}

    r = await client.post("/v1/admin/unlimited", headers=admin, json={"identifier": "138 0013 8000"})
    assert r.status_code == 204
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["account"]["member"] is True and me["spend"]["unlimited"] is True
    assert (
        await client.post(
            "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
        )
    ).status_code == 200
    listing = (await client.get("/v1/admin/accounts", headers=admin)).json()
    g = next(a for a in listing["accounts"] if a["identifier"] == "+8613800138000")
    assert g["member"] is True and g["unlimited"] is True and g["listed"] is False


def test_prices_and_day_boundary():
    s = Settings(database=":memory:", day_offset_h=8, usd_cny=7.1)
    m = s.model("qwen3.8-27b")
    assert m.chat_cost_uy(1_000_000, 0) == 3_000_000 and m.chat_cost_uy(0, 1_000_000) == 12_000_000
    assert m.chat_cost_uy(333, 21) == round(333 * 3 + 21 * 12)
    img = s.model("qwen-image-3.0")
    assert s.model("qwen-image-3.0-pro") is img  # what 0.1.21 phones still ask for
    assert s.model("MiniMax/MiniMax-H3") is None and s.model("nope") is None
    assert img.image_cost_uy("1024*1024") == 180_000 and img.image_cost_uy("2048x2048") == 180_000 and img.image_cost_uy(None) == 180_000
    vid = s.model("wan2.2-i2v-flash")
    assert vid.video_cost_uy(5) == 500_000 and vid.video_cost_uy(vid.clip_seconds) == 500_000 and vid.video_cost_uy(0) == 0
    # 2026-09-29 02:00 UTC is still the 29th in Beijing; its day began at 16:00 UTC on the 28th.
    t = 1790647200  # 2026-09-29T02:00:00Z
    assert s.day_start(t) == t - 10 * 3600
    assert s.day_start(t) == s.day_start(t + 13 * 3600)  # 15:00 UTC = 23:00 Beijing, same day
    assert s.day_start(t + 14 * 3600 + 1) == s.day_start(t) + 86400  # 16:00:01 UTC = the 30th
    assert s.cny_to_usd(25) == round(25 / 7.1, 4) and s.uy_to_cny(1234) == 0.0012


async def test_video_is_relayed_under_dashscope_paths(stack):
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    await client.post("/v1/admin/grant", headers={"X-Admin-Token": "admin"}, json={"identifier": "13800138000", "tokens": 1_000_000})

    # The app's probe: an unknown name is 404, an offered one answers 400 on an empty body (nothing charged).
    r = await client.post(
        "/api/v1/services/aigc/video-generation/video-synthesis",
        headers=headers,
        json={"model": "wan2.6-i2v", "input": {}, "parameters": {}},
    )
    assert r.status_code == 404
    r = await client.post(
        "/api/v1/services/aigc/video-generation/video-synthesis",
        headers=headers,
        json={"model": "wan2.2-i2v-flash", "input": {}, "parameters": {}},
    )
    assert r.status_code == 400 and r.json()["message"] == "prompt is required"
    assert (await client.get("/v1/me", headers=headers)).json()["tokens"]["used"] == 0

    # Upload policy, then the task itself, with the operator's key and the OSS header passed on.
    r = await client.get("/api/v1/uploads", params={"action": "getPolicy", "model": "wan2.2-i2v-flash"}, headers=headers)
    assert r.status_code == 200 and r.json()["data"]["upload_dir"] == "tmp/x"
    kind, up_headers, q = up.state.requests[-1]
    assert kind == "uploads" and up_headers["authorization"] == "Bearer sk-upstream" and q["model"] == "wan2.2-i2v-flash"
    r = await client.post(
        "/api/v1/services/aigc/video-generation/video-synthesis",
        headers={**headers, "X-DashScope-OssResourceResolve": "enable"},
        json={"model": "wan2.2-i2v-flash", "input": {"prompt": "a dragon waves"}, "parameters": {"duration": 4}},
    )
    assert r.status_code == 200 and r.json()["output"]["task_id"] == "task-42"
    kind, up_headers, up_body = up.state.requests[-1]
    assert kind == "video" and up_headers["x-dashscope-async"] == "enable" and up_headers["x-dashscope-ossresourceresolve"] == "enable"
    assert up_headers["authorization"] == "Bearer sk-upstream" and up_body["model"] == "wan2.2-i2v-flash"
    assert (await client.get("/v1/me", headers=headers)).json()["tokens"]["used"] == 0  # nothing until the clip exists

    # Polling: still running, then done — charged once, however often it is asked again.
    r = await client.get("/api/v1/tasks/task-42", headers=headers)
    assert r.status_code == 200 and r.json()["output"]["task_status"] == "RUNNING"
    assert (await client.get("/v1/me", headers=headers)).json()["tokens"]["used"] == 0
    for _ in range(2):
        r = await client.get("/api/v1/tasks/task-42", headers=headers)
        assert r.status_code == 200 and r.json()["output"]["video_url"].endswith("clip.mp4")
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["tokens"]["used"] == 200_000 and me["recent"][0]["kind"] == "video"
    # The owner sees the task, another account does not.
    other = await sign_up(client, sender, identifier="13900001111", device="other")
    r = await client.get("/api/v1/tasks/task-42", headers={"Authorization": f"Bearer {other['api_key']}"})
    assert r.status_code == 404
    # Too little grant left for a clip: refused before the provider is asked.
    r = await client.post(
        "/api/v1/services/aigc/video-generation/video-synthesis",
        headers={"Authorization": f"Bearer {other['api_key']}"},
        json={"model": "wan2.2-i2v-flash", "input": {"prompt": "x"}, "parameters": {}},
    )
    assert r.status_code == 402


async def test_unlimited_relay_meters_but_never_refuses():
    up = fake_upstream()
    settings = Settings(
        database=":memory:",
        secret="test-secret",
        admin_token="admin",
        upstream_base="http://upstream/compat/v1",
        upstream_key="sk-upstream",
        dashscope_base="http://upstream/ds/api/v1",
        public_base="http://cloud.test",
        signup_tokens=0,
        daily_cap_tokens=0,
        per_minute_requests=0,
    )
    assert settings.unlimited
    sender = LogSender()
    cloud = Cloud(settings, Database(":memory:"), sender)
    app = create_app(settings, cloud, upstream_transport=httpx.ASGITransport(app=up))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cloud.test")
    data = await sign_up(client, sender)
    assert data["tokens"]["unlimited"] is True and data["tokens"]["granted"] == 0
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    for _ in range(3):
        r = await client.post(
            "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
        )
        assert r.status_code == 200
    r = await client.post("/v1/images/generations", headers=headers, json={"model": "qwen-image-3.0", "prompt": "a dragon"})
    assert r.status_code == 200
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["tokens"] == {"unlimited": True, "granted": 0, "used": 450 + 30_000, "remaining": 0, "used_today": 30_450, "daily_cap": 0}
    accounts = (await client.get("/v1/admin/accounts", headers={"X-Admin-Token": "admin"})).json()
    assert accounts["settings"]["unlimited"] is True
    assert accounts["accounts"][0]["used_today"] == 30_450 and accounts["accounts"][0]["requests"] == 4


async def test_admin_sees_identifiers_and_people_can_leave(stack):
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender, identifier="Someone@Example.com", device="pixel")
    await sign_up(client, sender, identifier="13800138000", device="desk")
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    admin = {"X-Admin-Token": "admin"}

    listing = (await client.get("/v1/admin/accounts", headers=admin)).json()
    by_id = {a["identifier"]: a for a in listing["accounts"]}
    assert set(by_id) == {"someone@example.com", "+8613800138000"}
    a = by_id["someone@example.com"]
    assert a["hint"] == "so***@example.com" and a["channel"] == "email" and a["live_keys"] == 1 and a["devices"] == []
    assert "id_hash" not in a and "identifier_enc" not in a
    # The database itself holds no plaintext.
    row = cloud.db.account(a["id"])
    assert "someone" not in row["identifier_enc"] and cloud.crypto.decrypt(a["id"], row["identifier_enc"]) == "someone@example.com"
    assert cloud.crypto.decrypt("other-account", row["identifier_enc"]) is None
    assert listing["settings"]["models"][0] == "deepseek-v4.1-flash"
    usage = (await client.get("/v1/admin/usage", headers=admin)).json()
    assert usage["days"] == []

    # Disable and re-enable by identifier; a disabled account's key stops working.
    r = await client.post("/v1/admin/disable", headers=admin, json={"identifier": "someone@example.com"})
    assert r.status_code == 204
    assert (await client.get("/v1/me", headers=headers)).status_code == 401
    r = await client.post("/v1/admin/disable", headers=admin, json={"identifier": "someone@example.com", "disabled": False})
    assert r.status_code == 204
    assert (await client.get("/v1/me", headers=headers)).status_code == 200

    # The person deletes themselves: key dead, account gone, the number can sign up afresh.
    r = await client.post("/v1/auth/delete", headers=headers)
    assert r.status_code == 204
    assert (await client.get("/v1/me", headers=headers)).status_code == 401
    listing = (await client.get("/v1/admin/accounts", headers=admin)).json()
    assert [a["identifier"] for a in listing["accounts"]] == ["+8613800138000"]
    again = await sign_up(client, sender, identifier="someone@example.com", device="pixel")
    assert again["created"] is True

    # The operator removes the other one.
    r = await client.post("/v1/admin/delete", headers=admin, json={"identifier": "138 0013 8000"})
    assert r.status_code == 204
    assert (await client.post("/v1/admin/delete", headers=admin, json={"identifier": "138 0013 8000"})).status_code == 404


async def test_the_operator_sees_addresses_clients_and_every_line(stack):
    """0.10: sign-ins, requests and events carry the address and the client; the account view
    lists the addresses, the statement and the timeline page through to the first line, and
    one address can be looked up across accounts. The training export drops the address."""
    app, client, sender, up, cloud = stack
    phone = {"X-Forwarded-For": "203.0.113.7, 10.0.0.1", "User-Agent": "nanoMuse-Android/0.1.27 (Pixel 8)"}
    desk = {"X-Forwarded-For": "198.51.100.2", "User-Agent": "nanoMuse/0.1.27 (linux)"}
    r = await client.post("/v1/auth/code", json={"identifier": "13800138000"}, headers=phone)
    assert r.status_code == 204
    code = sender.sent[-1][1]
    r = await client.post("/v1/auth/verify", json={"identifier": "13800138000", "code": code, "device": "pixel"}, headers=phone)
    data = r.json()
    headers = {"Authorization": f"Bearer {data['api_key']}", **phone}
    admin = {"X-Admin-Token": "admin"}
    for _ in range(3):
        r = await client.post(
            "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
        )
        assert r.status_code == 200
    # the same person from the desk, with the password way in
    r = await client.post("/v1/auth/password", headers=headers, json={"password": "correct horse"})
    assert r.status_code == 204
    r = await client.post("/v1/auth/login", json={"identifier": "13800138000", "password": "correct horse", "device": "desk"}, headers=desk)
    assert r.status_code == 200
    desk_headers = {"Authorization": f"Bearer {r.json()['api_key']}", **desk}
    r = await client.post(
        "/v1/chat/completions", headers=desk_headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 200

    acc = (await client.get(f"/v1/admin/accounts/{data['account']['id']}", headers=admin)).json()
    a = acc["account"]
    assert (
        a["first_ip"] == "203.0.113.7"
        and a["last_ip"] == "198.51.100.2"
        and a["last_platform"] == "linux"
        and a["last_version"] == "0.1.27"
    )
    assert a["last_seen_at"] is not None
    assert [(s["device"], s["ip"], s["platform"], s["version"]) for s in acc["sessions"]] == [
        ("pixel", "203.0.113.7", "android", "0.1.27"),
        ("desk", "198.51.100.2", "linux", "0.1.27"),
    ]
    addresses = {x["ip"]: x for x in acc["addresses"]}
    assert set(addresses) == {"203.0.113.7", "198.51.100.2"}
    assert addresses["203.0.113.7"]["platforms"] == ["android"] and addresses["203.0.113.7"]["n"] >= 4
    opening = sum(1 for r_ in acc["recent"] if r_["kind"] in ("grant", "credit"))  # the sign-up's opening lines
    total = 4 + opening
    assert acc["ledger_total"] == total and acc["events_total"] >= 4
    assert {r_["ip"] for r_ in acc["recent"] if r_["kind"] == "chat"} == {"203.0.113.7", "198.51.100.2"}
    assert all(e["ip"] for e in acc["events"])

    # the statement, two lines at a time, to the first one
    seen, before = [], 0
    while True:
        page = (
            await client.get(
                f"/v1/admin/accounts/{data['account']['id']}/ledger?limit=2{f'&before={before}' if before else ''}", headers=admin
            )
        ).json()
        assert page["total"] == total
        if not page["rows"]:
            break
        seen += page["rows"]
        before = page["rows"][-1]["id"]
    assert len(seen) == total and [r_["kind"] for r_ in seen][-1] == "grant"
    assert [r_["id"] for r_ in seen] == sorted((r_["id"] for r_ in seen), reverse=True)
    page = (await client.get(f"/v1/admin/accounts/{data['account']['id']}/events?limit=1000", headers=admin)).json()
    assert page["total"] == len(page["rows"]) and {e["kind"] for e in page["rows"]} >= {
        "account.created",
        "sign_in.code",
        "sign_in.password",
        "password.set",
    }

    # one address, across accounts
    found = (await client.get("/v1/admin/address?ip=203.0.113.7", headers=admin)).json()
    assert [x["hint"] for x in found["accounts"]] == ["138****8000"] and found["accounts"][0]["n"] >= 4
    assert (await client.get("/v1/admin/address", headers=admin)).status_code == 400
    listing = (await client.get("/v1/admin/accounts", headers=admin)).json()["accounts"]
    assert listing[0]["last_ip"] == "198.51.100.2" and listing[0]["last_platform"] == "linux"

    # with "help improve" on, the kept turn carries the address for the operator — and the
    # training export leaves it out
    r = await client.post("/v1/me/contribute", headers=headers, json={"on": True})
    assert r.status_code == 200
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "kept"}]}
    )
    assert r.status_code == 200
    kept = (await client.get("/v1/admin/samples", headers=admin)).json()["samples"]
    assert kept[0]["meta"]["ip"] == "203.0.113.7" and kept[0]["platform"] == "android"
    exported = (await client.get(f"/v1/admin/samples/export?account_id={data['account']['id']}", headers=admin)).text
    line = json.loads(exported.strip())
    assert "ip" not in line["meta"] and "account_id" not in line and line["response"] == "hi"
    view = (await client.get("/v1/admin/data", headers=admin)).json()
    assert [(x["hint"], x["samples"]) for x in view["by_account"]] == [("138****8000", 1)]


async def test_the_showcase_visitors_reach_the_admin_page(monkeypatch):
    """0.10: with WEB_ADMIN_URL + WEB_ADMIN_TOKEN the relay passes the gateway's visitors view
    through (/v1/admin/demo) and puts one account's demos in its drawer; without them the
    panel is told so and the drawer carries None."""
    app, client, sender, up, cloud = make_stack(web_admin_url="http://gateway/api/demo/admin", web_admin_token="shh")
    seen: list[httpx.Request] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers.get("x-admin-token") != "shh":
            return httpx.Response(403, json={"error": "forbidden"})
        account = request.url.params.get("account", "")
        if account:
            return httpx.Response(
                200,
                json={
                    "visitor": {"id": account, "hint": "so…", "signins": 2, "sessions": 1, "first_ip": "1.2.3.4", "last_ip": "5.6.7.8"},
                    "visits": [{"id": "abc", "ip": "5.6.7.8"}],
                    "visits_total": 1,
                },
            )
        return httpx.Response(
            200,
            json={
                "signin_required": True,
                "visitors": [{"id": "x", "hint": "so…"}],
                "visitors_total": 1,
                "visits": [],
                "visits_total": 0,
                "days": int(request.url.params.get("days", 0)),
                "active": [],
            },
        )

    real = httpx.AsyncClient
    monkeypatch.setattr("nanomuse_cloud.api.httpx.AsyncClient", lambda *a, **kw: real(transport=httpx.MockTransport(gateway)))
    admin = {"X-Admin-Token": "admin"}
    view = (await client.get("/v1/admin/demo?days=7", headers=admin)).json()
    assert view["available"] is True and view["visitors_total"] == 1 and view["days"] == 7
    data = await sign_up(client, sender)
    acc = (await client.get(f"/v1/admin/accounts/{data['account']['id']}", headers=admin)).json()
    assert acc["demo"]["visitor"]["first_ip"] == "1.2.3.4" and acc["demo"]["visits_total"] == 1
    assert seen[-1].url.params["account"] == data["account"]["id"]

    # not configured: the panel says so, the drawer has nothing to show
    monkeypatch.undo()
    app2, client2, sender2, up2, cloud2 = make_stack()
    assert (await client2.get("/v1/admin/demo", headers=admin)).json() == {"available": False, "places": {}}
    data2 = await sign_up(client2, sender2)
    assert (await client2.get(f"/v1/admin/accounts/{data2['account']['id']}", headers=admin)).json()["demo"] is None


async def test_members_see_the_models_under_the_key_and_pick():
    """0.10: GET /v1/models for a member carries, after the menu, the usable models the
    provider lists under the operator's key — sorted into chat and pictures by their ids,
    the spoken / heard / embedded ones left out — so the apps' pickers offer them. Guests see
    the menu alone; the list is cached and a provider that stops answering leaves it in place.
    (Names only here — the probes are the next test.)"""
    app, client, sender, up, cloud = make_stack(allowed_identifiers="Me@Example.com", allowance_cny=0.5, catalog_probe=False)
    member = await sign_up(client, sender, identifier="me@example.com", device="desk")
    guest = await sign_up(client, sender, identifier="13800138000", device="pixel")
    mh = {"Authorization": f"Bearer {member['api_key']}"}
    gh = {"Authorization": f"Bearer {guest['api_key']}"}

    menu_ids = [m.id for m in cloud.s.models]
    listing = (await client.get("/v1/models", headers=mh)).json()
    ids = [m["id"] for m in listing["data"]]
    assert ids[: len(menu_ids)] == menu_ids  # the menu first, in its order
    extra = {m["id"]: m for m in listing["data"] if m["nanomuse"].get("catalog")}
    assert set(extra) == {"deepseek-v4-pro", "qwen3-vl-plus", "vanchin/deepseek-v3", "qwen-image-edit-max", "wan2.7-image"}
    assert extra["deepseek-v4-pro"]["nanomuse"]["kind"] == "chat" and extra["deepseek-v4-pro"]["nanomuse"]["listed"] is False
    assert extra["deepseek-v4-pro"]["nanomuse"]["priced_as"] == "qwen3.8-27b"
    assert extra["vanchin/deepseek-v3"]["architecture"]["input_modalities"] == ["text"]  # not known to read pictures
    assert extra["deepseek-v4-pro"]["nanomuse"]["vision"] is False  # by name: only V4.1 and later read pictures
    assert extra["qwen3-vl-plus"]["nanomuse"]["vision"] is True and extra["qwen3-vl-plus"]["architecture"]["input_modalities"] == [
        "text",
        "image",
    ]
    assert extra["qwen3-vl-plus"]["nanomuse"]["verified"] is False  # the name's word, no probe asked
    assert extra["qwen-image-edit-max"]["nanomuse"]["kind"] == "image" and extra["wan2.7-image"]["architecture"]["output_modalities"] == [
        "image"
    ]
    assert listing["nanomuse"]["catalog"] == {"models": 5, "error": "", "probing": False}
    # the provider was asked with the operator's key, once; the second read is from the cache
    asked = [q for q in up.state.requests if q[0] == "models"]
    assert len(asked) == 1 and asked[0][1]["authorization"] == "Bearer sk-upstream"
    await client.get("/v1/models", headers=mh)
    assert len([q for q in up.state.requests if q[0] == "models"]) == 1
    # a guest: the menu, nothing more
    glist = (await client.get("/v1/models", headers=gh)).json()
    assert [m["id"] for m in glist["data"]] == menu_ids and glist["nanomuse"] == {"any_model": False}
    # a catalog model chats under its own id, priced as the dearest menu model
    r = await client.post(
        "/v1/chat/completions", json={"model": "vanchin/deepseek-v3", "messages": [{"role": "user", "content": "hi"}]}, headers=mh
    )
    assert r.status_code == 200, r.text
    assert [q for q in up.state.requests if q[0] == "chat"][-1][2]["model"] == "vanchin/deepseek-v3"
    # the provider goes quiet: the list stands, the error is said
    app.state.catalog.fetched_at = 0
    up.state.catalog_ids = None  # the provider answers 503
    listing = (await client.get("/v1/models", headers=mh)).json()
    assert len([m for m in listing["data"] if m["nanomuse"].get("catalog")]) == 5
    assert listing["nanomuse"]["catalog"]["models"] == 5 and listing["nanomuse"]["catalog"]["error"]


def test_the_catalog_sorts_ids_by_their_shape():
    from nanomuse_cloud.catalog import classify

    assert classify("qwen3.8-27b") == ("chat", True)  # the 3.5+ generations read pictures
    assert classify("deepseek-v4.1-flash") == ("chat", True)  # V4.1 reads them on Model Studio (checked)
    assert classify("deepseek-v4.2-pro") == ("chat", True) and classify("deepseek-v5") == ("chat", True)
    assert classify("deepseek-v4-flash") == ("chat", False)  # V4 does not — it guesses or returns nothing
    assert classify("vanchin/deepseek-v3") == ("chat", False)
    assert classify("qwen3-vl-plus") == ("chat", True)
    assert classify("qvq-max") == ("chat", True)
    assert classify("gui-plus") == ("chat", True)
    assert classify("vanchin/deepseek-ocr") == ("chat", True)
    assert classify("kimi-k2.5") == ("chat", True) and classify("kimi-k2-thinking") == ("chat", False)
    assert classify("qwen-mt-plus") == ("chat", False)
    assert (
        classify("qwen-image-3.0")[0] == "image" and classify("wan2.7-image-pro")[0] == "image" and classify("z-image-turbo")[0] == "image"
    )
    assert (
        classify("wan2.2-i2v-flash")[0] == "video" and classify("wan2.2-t2v-plus")[0] == "video" and classify("wan2.6-kf2v")[0] == "video"
    )
    for other in (
        "qwen3-tts-flash",
        "qwen3-asr-flash-realtime",
        "MiniMax/speech-02-hd",
        "qwen3.7-text-embedding",
        "qwen3.7-text-rerank",
        "qwen3-omni-flash",
        "qwen3.8-livetranslate-flash-realtime",
        "qwen-audio-3.0-asr-flash",
        "qwen3-s2s-flash-realtime-2025-09-22",
        "sre-gpu-auto-handle",
        "not a model",
        "",
    ):
        assert classify(other) == ("other", False), other
    assert classify("deepseek-v4-pro") == ("chat", False) and classify("deepseek-v3.2") == ("chat", False)
    assert classify("deepseek-vision-x") == ("chat", True) and classify("deepseek-ocr") == ("chat", True)


async def test_the_catalog_asks_each_model_whether_it_answers_and_sees():
    """0.11: after the list is read, every chat model is asked two one-word questions in the
    background; a model the provider refuses (retired) is left off the list, the vision flag
    is what the model answered about the magenta square (a blind model guesses red), and the answers are kept in the
    database so a restart does not ask again. The admin page sees the whole of it."""
    up0 = fake_upstream()
    ids = list(up0.state.catalog_ids) + ["qwen-1.8b-chat", "qwen-plus"]
    app, client, sender, up, cloud = make_stack(allowed_identifiers="Me@Example.com", allowance_cny=0.5)
    up.state.catalog_ids = ids
    member = await sign_up(client, sender, identifier="me@example.com", device="desk")
    mh = {"Authorization": f"Bearer {member['api_key']}"}
    admin = {"X-Admin-Token": "admin"}

    first = (await client.get("/v1/models", headers=mh)).json()
    catalog = app.state.catalog
    assert first["nanomuse"]["catalog"]["probing"] is True or catalog._probing is not None
    await catalog._probing  # the background round
    probes = [q for q in up.state.requests if q[0] == "chat"]
    # the retired model was asked once (its refusal is the answer); the rest twice (text, then the picture)
    by_model: dict[str, int] = {}
    for q in probes:
        by_model[q[2]["model"]] = by_model.get(q[2]["model"], 0) + 1
    assert by_model["qwen-1.8b-chat"] == 1 and by_model["qwen-plus"] == 2 and by_model["deepseek-v4-pro"] == 2
    assert "qwen-image-edit-max" not in by_model  # picture models are not asked

    listing = (await client.get("/v1/models", headers=mh)).json()
    extra = {m["id"]: m for m in listing["data"] if m["nanomuse"].get("catalog")}
    assert "qwen-1.8b-chat" not in extra  # the provider's "no" takes it off the list
    assert extra["qwen-plus"]["nanomuse"]["vision"] is False and extra["qwen-plus"]["nanomuse"]["verified"] is True
    assert extra["qwen-plus"]["architecture"]["input_modalities"] == ["text"]
    assert extra["vanchin/deepseek-v3"]["nanomuse"]["vision"] is False  # the name guessed right; now verified
    # the name said text-only (V4, not 4.1); the probe's word wins
    assert extra["deepseek-v4-pro"]["nanomuse"]["vision"] is True and extra["deepseek-v4-pro"]["nanomuse"]["verified"] is True
    assert extra["deepseek-v4-pro"]["architecture"]["input_modalities"] == ["text", "image"]
    assert listing["nanomuse"]["catalog"]["models"] == 6 and listing["nanomuse"]["catalog"]["probing"] is False

    # kept: a second catalog over the same database asks nothing more
    n_before = len([q for q in up.state.requests if q[0] == "chat"])
    from nanomuse_cloud.catalog import Catalog

    again = Catalog(ttl_s=3600, probe_ttl_s=7 * 86400, store=cloud.db)
    await again.get(app.state.http, cloud.s.upstream_base, cloud.s.upstream_key)
    if again._probing is not None:
        await again._probing
    assert len([q for q in up.state.requests if q[0] == "chat"]) == n_before
    assert {e.id for e in again.entries} == {e.id for e in catalog.entries}

    # the admin page: what the key has, which were refused, with the provider's words
    r = await client.get("/v1/admin/catalog", headers=admin)
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["enabled"] and summary["probe"] and summary["pending"] == 0
    assert [u["id"] for u in summary["unusable"]] == ["qwen-1.8b-chat"] and "Model not exist" in summary["unusable"][0]["note"]
    assert {m["id"]: m["vision"] for m in summary["models"] if m["kind"] == "chat"}["deepseek-v4-pro"] is True


async def test_the_thinking_default_follows_what_the_request_already_says():
    """The shipped default (`enable_thinking: false`) saves reasoning tokens — but an app that
    sets a thinking level sends `reasoning_effort`, and Model Studio refuses that next to
    `enable_thinking: false`. The relay reads what the request says about reasoning, in any
    of the dialects, and sets the default accordingly."""
    from nanomuse_cloud.api import apply_chat_defaults, thinking_requested

    d = {"enable_thinking": False}
    for body, wants in (
        ({}, None),
        ({"enable_thinking": True}, True),
        ({"thinking": {"type": "enabled"}}, True),
        ({"thinking": {"type": "disabled"}}, False),
        ({"thinking": True}, True),
        ({"reasoning_effort": "low"}, True),
        ({"reasoning_effort": "none"}, False),
        ({"thinking_budget": 2000}, True),
    ):
        assert thinking_requested(body) is wants, body
    silent: dict = {"model": "m"}
    apply_chat_defaults(silent, d)
    assert silent["enable_thinking"] is False
    effort: dict = {"reasoning_effort": "medium"}
    apply_chat_defaults(effort, d)
    assert effort == {"reasoning_effort": "medium", "enable_thinking": True}
    none: dict = {"reasoning_effort": "none"}
    apply_chat_defaults(none, d)
    assert none == {"reasoning_effort": "none", "enable_thinking": False}
    # declined one way, asked another: the decline wins and the effort is made consistent
    mixed: dict = {"thinking": {"type": "disabled"}, "reasoning_effort": "high"}
    apply_chat_defaults(mixed, d)
    assert mixed["enable_thinking"] is False and mixed["reasoning_effort"] == "none"
    explicit: dict = {"enable_thinking": True, "reasoning_effort": "low"}
    apply_chat_defaults(explicit, d)
    assert explicit == {"enable_thinking": True, "reasoning_effort": "low"}

    # end to end: the request that used to come back 400 goes through
    app, client, sender, up, cloud = make_stack(catalog_probe=False)
    data = await sign_up(client, sender, identifier="13800138000", device="pixel")
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    r = await client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "qwen3.8-27b", "reasoning_effort": "low", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200, r.text
    sent = [q for q in up.state.requests if q[0] == "chat"][-1][2]
    assert sent["enable_thinking"] is True and sent["reasoning_effort"] == "low"


async def test_an_upstream_refusal_is_written_down_with_the_providers_words():
    """The `upstream.error` event names the model and keeps the provider's message, so the
    admin page says why a request failed — never what was asked."""
    from nanomuse_cloud.api import upstream_detail

    raw = b'{"error":{"message":"\'reasoning_effort\' must be \'none\' when \'enable_thinking\' is false","code":"InvalidParameter"}}'
    assert upstream_detail("chat", 400, "qwen3.8-27b", raw) == (
        "chat 400 qwen3.8-27b: 'reasoning_effort' must be 'none' when 'enable_thinking' is false"
    )
    assert upstream_detail("chat", 502, "m", b"<html>bad gateway</html>") == "chat 502 m"
    assert upstream_detail("chat", 400, "m", b'{"message": "plain\\nlines"}') == "chat 400 m: plain lines"

    app, client, sender, up, cloud = make_stack(catalog_probe=False)
    data = await sign_up(client, sender, identifier="13800138000", device="pixel")
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    up.state.retired.add("qwen3.8-flash")
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-flash", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 400
    events = (await client.get("/v1/me/events", headers=headers)).json()["events"]
    err = next(e for e in events if e["kind"] == "upstream.error")
    assert err["detail"] == "chat 400 qwen3.8-flash: Model not exist."
    # the streaming path says the same
    r = await client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "qwen3.8-flash", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200 and b"Model not exist" in r.content
    events = (await client.get("/v1/me/events", headers=headers)).json()["events"]
    assert sum(1 for e in events if e["detail"] == "chat 400 qwen3.8-flash: Model not exist.") == 2


def test_a_content_check_refusal_is_said_plainly():
    """Bailian's content check says no in two spellings; both become one plain sentence with
    a stable code (`content_rejected`), not the provider's "green net" words — and an image
    prompt it declines is a 400 about the words, not a 502 about the provider."""
    from nanomuse_cloud.api import content_check_refusal, relay_error_body

    native = b'{"request_id":"x","code":"DataInspectionFailed","message":"Green net check rejected text (input)"}'
    compat = b'{"error":{"code":"data_inspection_failed","message":"Input data may contain inappropriate content.","type":"invalid_request_error"}}'
    other = b'{"error":{"message":"Model not exist.","code":"InvalidParameter"}}'
    assert content_check_refusal(native) and content_check_refusal(compat) and not content_check_refusal(other)
    for raw in (native, compat):
        err = relay_error_body(400, raw)["error"]
        assert err["code"] == "content_rejected"
        assert err["message"].startswith("The model provider's content check declined")
        assert "upstream" in err  # the provider's words ride along for bug reports
    # an ordinary 400 still passes the provider's own words through, as before
    assert relay_error_body(400, other)["error"] == {"message": "Model not exist.", "type": "upstream", "code": "upstream_400"}
    assert relay_error_body(429, other)["error"]["code"] == "upstream_busy"


def tiny_xdb(ranges: list[tuple[str, str, str]]) -> bytes:
    """A real xdb (structure 3, IPv4) with just these ranges — the format geo.py reads:
    header, 256×256 vector index, the segment index, the region strings."""
    import ipaddress
    import struct

    HEADER, CELLS = 256, 256 * 256
    segs = sorted((int(ipaddress.ip_address(a)), int(ipaddress.ip_address(b)), r.encode()) for a, b, r in ranges)
    index_start = HEADER + CELLS * 8
    index_len = 14 * len(segs)
    data_start = index_start + index_len
    data, ptrs, p = b"", [], data_start
    for _, _, region in segs:
        ptrs.append((p, len(region)))
        data += region
        p += len(region)
    index = b"".join(struct.pack("<IIHI", s, e, ln, ptr) for (s, e, _), (ptr, ln) in zip(segs, ptrs, strict=True))
    vector = bytearray(CELLS * 8)
    # each (first, second octet) cell gets the byte range of the entries that can hold it
    by_cell: dict[int, list[int]] = {}
    for i, (s, e, _) in enumerate(segs):
        for cell in range(s >> 16, (e >> 16) + 1):
            by_cell.setdefault(cell, []).append(i)
    for cell, rows in by_cell.items():
        struct.pack_into("<II", vector, cell * 8, index_start + 14 * rows[0], index_start + 14 * (rows[-1] + 1))
    header = bytearray(HEADER)
    struct.pack_into("<HHIII", header, 0, 3, 1, 0, index_start, data_start)
    struct.pack_into("<HH", header, 16, 4, 4)
    return bytes(header) + bytes(vector) + index + data


async def test_addresses_come_with_where_they_are(tmp_path):
    """0.11: the admin page's answers carry `places` — country, province, city — for the
    addresses they show, read from ip2region's file in the data directory (nothing is sent
    anywhere); private addresses are "本地网络"; an address the file does not know is left
    out; a missing file means places stay unknown and the page is told."""
    from nanomuse_cloud.geo import Geo, Xdb, collect_ips, group_places, parse_region

    db = tmp_path / "ip2region_v4.xdb"
    db.write_bytes(
        tiny_xdb(
            [
                ("1.2.3.0", "1.2.3.255", "中国|浙江省|杭州市|阿里|CN"),
                ("8.8.8.0", "8.8.8.255", "United States|California|0|Google LLC|US"),
                ("1.2.4.0", "1.2.4.255", "中国|北京市|北京市|联通|CN"),
            ]
        )
    )
    x = Xdb.load(db)
    import ipaddress

    assert x.search(ipaddress.ip_address("1.2.3.4").packed) == "中国|浙江省|杭州市|阿里|CN"
    assert x.search(ipaddress.ip_address("1.2.4.200").packed).startswith("中国|北京市")
    assert x.search(ipaddress.ip_address("1.2.5.1").packed) == "" and x.search(ipaddress.ip_address("9.9.9.9").packed) == ""
    p = parse_region("中国|浙江省|杭州市|阿里|CN")
    assert (p.country, p.province, p.city, p.isp, p.code, p.text) == ("中国", "浙江省", "杭州市", "阿里", "CN", "中国 · 浙江省 · 杭州市")
    assert parse_region("中国|北京市|北京市|联通|CN").text == "中国 · 北京市"
    assert parse_region("United States|California|0|Google LLC|US").text == "United States · California"
    assert parse_region("中国|华东|浙江省|杭州市|阿里").province == "浙江省"  # the older layout
    assert parse_region("0|0|0|0|0").country == ""

    geo = Geo(str(db))
    assert geo.ready and geo.status()["families"] == [4]
    assert geo.place("1.2.3.4").text == "中国 · 浙江省 · 杭州市" and geo.place("::ffff:8.8.8.8").code == "US"
    assert geo.place("10.0.0.1").local and geo.place("127.0.0.1").text == "本地网络"
    assert geo.place("9.9.9.9") is None and geo.place("not an ip") is None and geo.place("") is None
    assert geo.place("2400:3200::1") is None  # no IPv6 file
    assert collect_ips({"a": [{"ip": "1.2.3.4", "x": {"last_ip": "8.8.8.8", "first_ip": ""}}], "ip": "10.0.0.1"}) == {
        "1.2.3.4",
        "8.8.8.8",
        "10.0.0.1",
    }
    grouped = group_places([("1.2.3.4", 5), ("1.2.3.9", 1), ("8.8.8.8", 2), ("9.9.9.9", 7), ("10.0.0.1", 1)], geo)
    assert [(g["country"], g["province"], g["n"], g["ips"]) for g in grouped] == [
        ("", "", 7, 1),
        ("中国", "浙江省", 6, 2),
        ("United States", "California", 2, 1),
        ("本地网络", "", 1, 1),
    ]

    # through the relay: a sign-in from Hangzhou, and the page's answers say so
    app, client, sender, up, cloud = make_stack(geoip_db=str(db), catalog_probe=False)
    assert app.state.geo.ready
    data = await sign_up(client, sender, identifier="13800138000", device="pixel", headers={"X-Forwarded-For": "1.2.3.4"})
    headers = {"Authorization": f"Bearer {data['api_key']}", "X-Forwarded-For": "1.2.3.4"}
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 200
    admin = {"X-Admin-Token": "admin"}
    listing = (await client.get("/v1/admin/accounts", headers=admin)).json()
    assert listing["accounts"][0]["last_ip"] == "1.2.3.4" and listing["places"]["1.2.3.4"]["text"] == "中国 · 浙江省 · 杭州市"
    account_id = data["account"]["id"]
    detail = (await client.get(f"/v1/admin/accounts/{account_id}", headers=admin)).json()
    assert detail["places"]["1.2.3.4"]["city"] == "杭州市"
    addr = (await client.get("/v1/admin/address", headers=admin, params={"ip": "1.2.3.4"})).json()
    assert addr["place"]["province"] == "浙江省" and addr["accounts"][0]["id"] == account_id
    unknown = (await client.get("/v1/admin/address", headers=admin, params={"ip": "9.9.9.9"})).json()
    assert unknown["place"] is None
    overview = (await client.get("/v1/admin/overview", headers=admin)).json()
    assert overview["geo"]["ready"] is True
    places = (await client.get("/v1/admin/places", headers=admin, params={"days": 7})).json()
    assert places["geo"]["ready"] and places["demo_visitors"] is None  # no showcase gateway configured
    assert places["accounts"] == [{"country": "中国", "code": "CN", "province": "浙江省", "n": 1, "ips": 1}]
    assert places["requests"][0]["n"] == 1 and places["signins"][0]["country"] == "中国" and places["new_accounts"][0]["n"] == 1

    # no file, no fetch (an in-memory database has no directory): places stay unknown, honestly
    app2, client2, *_ = make_stack(catalog_probe=False)
    assert not app2.state.geo.enabled
    overview2 = (await client2.get("/v1/admin/overview", headers=admin)).json()
    assert overview2["geo"] == {"enabled": False, "ready": False, "families": [], "error": "", "fetching": False, "file": ""}
    assert overview2["places"] == {}


def test_code_mail_has_text_and_html_in_both_languages():
    from nanomuse_cloud.senders import compose_code_mail

    msg = compose_code_mail("no-reply@mail.nanomuse.cn", "someone@example.com", "123456", 10)
    assert msg["From"] == "nanoMuse <no-reply@mail.nanomuse.cn>" and msg["To"] == "someone@example.com"
    assert "123456" in msg["Subject"]
    parts = {p.get_content_type(): p.get_content() for p in msg.iter_parts()}
    assert set(parts) == {"text/plain", "text/html"}
    assert "验证码是 123456" in parts["text/plain"] and "Your nanoMuse code is 123456" in parts["text/plain"]
    assert "1 2 3 4 5 6" in parts["text/html"] and "10 分钟" in parts["text/html"] and "10 minutes" in parts["text/html"]
    assert "<script" not in parts["text/html"]


def test_provider_picture_urls_are_only_fetched_from_the_provider():
    from nanomuse_cloud.api import _provider_url_ok

    own = ("dashscope.aliyuncs.com",)
    assert _provider_url_ok("https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/x/y.png", own)
    assert _provider_url_ok("https://dashscope.aliyuncs.com/api/v1/files/1", own)
    assert _provider_url_ok("http://upstream/pic.png", ("upstream",))
    assert not _provider_url_ok("http://dashscope-result.oss-cn-beijing.aliyuncs.com/x.png", own)  # plain http, not our host
    assert not _provider_url_ok("https://169.254.169.254/latest/meta-data/", own)
    assert not _provider_url_ok("https://evil.example.com/aliyuncs.com/x.png", own)
    assert not _provider_url_ok("file:///etc/passwd", own)
    assert not _provider_url_ok("", own)


def test_a_video_task_seen_twice_stays_charged():
    db = Database(":memory:")
    db.create_account("h", "phone", "138****8000", 0, account_id="a1")
    db.insert_video_task("t1", "a1", "wan-x", cost_uy=500)
    assert db.mark_video_charged("t1") is True
    db.insert_video_task("t1", "a1", "wan-x", cost_uy=500)  # a retried submission answer, same task id
    assert db.mark_video_charged("t1") is False
    row = db.video_task("t1")
    assert row is not None and row["charged"] == 1


async def test_data_controls_keep_the_training_view_only_and_are_deletable(stack):
    """With IMPROVE_DEFAULT unset the switch starts off: nothing about a chat turn is kept.
    On: what the person wrote and what the model answered (its tool calls with it) land in
    ``samples`` — never the system prompt, a tool's result or a picture — for the operator,
    exported without the account id; a delete removes them, and the switch earns nothing."""
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender, identifier="dev-a@example.com")
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    admin = {"X-Admin-Token": "admin"}
    msgs = [{"role": "user", "content": "hi"}]
    r = await client.post("/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": msgs})
    assert r.status_code == 200
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["contribute"]["on"] is False and me["contribute"]["samples"] == 0 and me["contribute"]["default_on"] is False
    assert me["contribute"]["privacy_url"] == "https://nanomuse.cn/privacy/" and "what you wrote" in me["contribute"]["keeps"]["kept"]
    assert me["contribute"]["bonus_cny"] == 0 and me["contribute"]["bonus_available"] is False
    assert (await client.get("/v1/admin/samples", headers=admin)).json() == {"samples": [], "total": 0, "places": {}}

    r = await client.post("/v1/me/contribute", headers=headers, json={"on": True})
    assert r.status_code == 200
    assert r.json()["on"] is True and r.json()["samples"] == 0 and r.json()["bonus_granted"] is False
    # a full agent turn: system prompt, a picture, a tool call and its result
    turn = [
        {"role": "system", "content": "SOUL and memory: the person's name is Ada"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what is this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "SECRET FILE CONTENTS"},
    ]
    r = await client.post(
        "/v1/chat/completions",
        headers={**headers, "User-Agent": "nanoMuse-Android/0.1.27", "Accept-Language": "zh-CN"},
        json={"model": "qwen3.8-27b", "messages": turn},
    )
    assert r.status_code == 200
    # and a streamed one
    async with client.stream(
        "POST", "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "stream": True, "messages": msgs}
    ) as r:
        await r.aread()
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["contribute"]["on"] is True and me["contribute"]["samples"] == 2
    got = (await client.get("/v1/admin/samples", headers=admin)).json()
    assert got["total"] == 2 and [s["response"] for s in got["samples"]] == ["你好，世界", "hi"]
    first = got["samples"][1]
    assert [m["role"] for m in first["request"]] == ["user", "assistant", "tool"]
    assert first["request"][0]["content"] == [{"type": "text", "text": "what is this"}, {"type": "image_url", "omitted": True}]
    assert first["request"][1]["tool_calls"][0]["function"]["name"] == "read"
    assert first["request"][2] == {"role": "tool", "tool_call_id": "c1", "content": "", "omitted": True}
    dumped = json.dumps(first)
    assert "AAAA" not in dumped and "Ada" not in dumped and "SECRET" not in dumped
    # 0.10: the address goes with the turn for the operator (the test client has none)
    assert first["meta"] == {"ua": "nanoMuse-Android/0.1.27", "lang": "zh-CN", "ip": first["meta"]["ip"]}
    assert first["platform"] == "android"
    assert first["prompt_tokens"] == 100 and first["completion_tokens"] == 50
    account = (await client.get(f"/v1/admin/accounts/{data['account']['id']}", headers=admin)).json()["account"]
    assert account["contribute"] is True and account["samples"] == 2
    overview = (await client.get("/v1/admin/overview", headers=admin)).json()
    assert overview["contributions"] == {"accounts": 1, "samples": 2}
    # the operator's data view: who has it on, what came in, by day / model / app, the newest turns
    dv = (await client.get("/v1/admin/data?days=7", headers=admin)).json()
    assert dv["default_on"] is False and dv["accounts"]["on"] == 1 and dv["accounts"]["total"] == 1 and dv["accounts"]["share"] == 1.0
    assert dv["totals"]["samples"] == 2 and dv["period"]["samples"] == 2 and dv["period"]["accounts"] == 1
    assert len(dv["days"]) == 7 and dv["days"][-1]["samples"] == 2 and dv["days"][-1]["turned_on"] == 1 and dv["days"][-1]["accounts"] == 1
    assert len(dv["by_model"]) == 1 and dv["by_model"][0]["model"] == "qwen3.8-27b" and dv["by_model"][0]["samples"] == 2
    assert dv["by_model"][0]["tokens"] == dv["period"]["prompt_tokens"] + dv["period"]["completion_tokens"] > 0
    assert sorted(dv["by_platform"], key=lambda x: x["platform"]) == [
        {"platform": "android", "samples": 1},
        {"platform": "other", "samples": 1},
    ]
    assert [s["response"] for s in dv["recent"]] == ["你好，世界", "hi"] and dv["recent"][0]["hint"] == data["account"]["hint"]
    # the export has no account ids
    r = await client.get("/v1/admin/samples/export", headers=admin)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(ln) for ln in r.text.splitlines() if ln]
    assert len(lines) == 2 and all("account_id" not in ln for ln in lines)
    assert {ln["response"] for ln in lines} == {"hi", "你好，世界"}
    # off again: nothing more is kept, but what was kept stays counted until the person deletes it
    r = await client.post("/v1/me/contribute", headers=headers, json={"on": False})
    assert r.json()["on"] is False and r.json()["samples"] == 2 and r.json()["bonus_granted"] is False
    r = await client.post("/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": msgs})
    assert (await client.get("/v1/admin/samples", headers=admin)).json()["total"] == 2
    assert (await client.get("/v1/me", headers=headers)).json()["contribute"]["samples"] == 2
    r = await client.delete("/v1/me/samples", headers=headers)
    assert r.json() == {"deleted": 2}
    assert (await client.get("/v1/me", headers=headers)).json()["contribute"]["samples"] == 0
    kinds = [e["kind"] for e in (await client.get("/v1/me/events", headers=headers)).json()["events"]]
    assert {"contribute.on", "contribute.off", "contribute.deleted"} <= set(kinds) and "contribute.default" not in kinds
    dv = (await client.get("/v1/admin/data?days=1", headers=admin)).json()
    assert (
        dv["accounts"]["on"] == 0
        and dv["accounts"]["turned_off_ever"] == 1
        and dv["days"][0]["turned_off"] == 1
        and dv["days"][0]["deleted"] == 1
    )
    # deleting the account takes any samples with it
    await client.post("/v1/me/contribute", headers=headers, json={"on": True})
    await client.post("/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": msgs})
    assert cloud.db.sample_count() == 1
    assert (await client.post("/v1/auth/delete", headers=headers)).status_code == 204
    assert cloud.db.sample_count() == 0


async def test_improve_default_applies_to_new_accounts_only():
    """IMPROVE_DEFAULT=1: an account made from now on starts with the switch on, said on its
    timeline as the relay's default (not as a choice), and may turn it off; an account from
    before keeps what it had. The invite bonus goes to both sides either way."""
    app, client, sender, up, cloud = make_stack(allowance_cny=10, invite_bonus_cny=5)
    before = await sign_up(client, sender, identifier="dev-a@example.com")
    assert before["contribute"]["on"] is False
    cloud.s = dataclasses.replace(cloud.s, improve_default=True)  # the operator sets IMPROVE_DEFAULT=1 and restarts
    me = (await client.get("/v1/me", headers={"Authorization": f"Bearer {before['api_key']}"})).json()
    assert me["contribute"]["on"] is False and me["contribute"]["default_on"] is True
    code = (await client.get("/v1/me/invite", headers={"Authorization": f"Bearer {before['api_key']}"})).json()["code"]

    after = await sign_up(client, sender, identifier="dev-b@example.com", invite=code)
    assert after["contribute"]["on"] is True and after["contribute"]["samples"] == 0 and after["contribute"]["default_on"] is True
    headers = {"Authorization": f"Bearer {after['api_key']}"}
    kinds = [e["kind"] for e in (await client.get("/v1/me/events", headers=headers)).json()["events"]]
    assert "contribute.default" in kinds and "contribute.on" not in kinds
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 200 and cloud.db.sample_count() == 1
    # +¥5 for each of them: the newcomer's pool is ¥15, the inviter's too
    assert after["spend"]["grant"] == 15 and after["invite"]["invitee_bonus_cny"] == 5
    credits = [r_["detail"] for r_ in after["recent"] if r_["kind"] == "credit"]
    assert {"credit_uy": 5_000_000, "from": "invited", "friend": before["account"]["id"][:8]} in credits
    me = (await client.get("/v1/me", headers={"Authorization": f"Bearer {before['api_key']}"})).json()
    assert me["spend"]["grant"] == 15 and me["invite"]["invites"] == 1 and me["invite"]["earned_cny"] == 5
    # the newcomer turns it off: nothing more is kept
    r = await client.post("/v1/me/contribute", headers=headers, json={"on": False})
    assert r.json()["on"] is False and r.json()["samples"] == 1
    await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert cloud.db.sample_count() == 1
    dv = (await client.get("/v1/admin/data?days=1", headers={"X-Admin-Token": "admin"})).json()
    assert dv["default_on"] is True and dv["accounts"] == {
        "total": 2,
        "on": 0,
        "off": 2,
        "share": 0.0,
        "turned_off_ever": 1,
        "with_samples": 1,
    }
    assert dv["days"][0]["default_on"] == 1 and dv["days"][0]["turned_off"] == 1 and dv["days"][0]["turned_on"] == 0


def test_long_samples_are_cut_whole_and_old_cut_rows_still_load():
    """A conversation over the sample limit is shortened message by message (then text by
    text) so that what is stored parses; a row cut at a character count by 0.5.1 gives back
    the messages that are whole instead of failing the list and the export."""
    from nanomuse_cloud.service import _fit_messages, _load_messages

    msgs = [{"role": "system", "content": "be brief"}] + [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i} " + "x" * 500} for i in range(40)
    ]
    text, cut = _fit_messages(msgs, 3000)
    assert cut and len(text) <= 3000
    kept = json.loads(text)
    assert kept[0] == msgs[0] and kept[-1] == msgs[-1] and kept[1]["content"].startswith("turn 3")
    # one huge paste: the text is cut, the message stays
    text, cut = _fit_messages([{"role": "user", "content": "y" * 10_000}], 1000)
    assert cut and len(text) <= 1000 and json.loads(text)[0]["content"].endswith("[…]")
    text, cut = _fit_messages(msgs[:3], 100_000)
    assert not cut and json.loads(text) == msgs[:3]
    # the 0.5.1 shape: JSON cut mid-string
    old = json.dumps(msgs[:6], ensure_ascii=False)[:1800]
    back, cut = _load_messages(old)
    assert cut and 1 <= len(back) < 6 and back[0] == msgs[0]
    assert _load_messages("") == ([], False)
    assert _load_messages(json.dumps(msgs[:2])) == (msgs[:2], False)


def test_database_from_before_0_4_migrates(tmp_path):
    """A relay upgraded in place: the accounts table lacks the 0.4 columns and the
    partial unique index on invite_code must not be attempted before they exist."""
    import sqlite3

    from nanomuse_cloud.db import Database

    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE accounts (
            id TEXT PRIMARY KEY, id_hash TEXT NOT NULL UNIQUE, channel TEXT NOT NULL, hint TEXT NOT NULL,
            created_at INTEGER NOT NULL, disabled INTEGER NOT NULL DEFAULT 0, grant_tokens INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO accounts (id, id_hash, channel, hint, created_at) VALUES ('a1', 'h1', 'email', 'a***@x', 1);
        """
    )
    conn.commit()
    conn.close()
    db = Database(path)
    cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(accounts)").fetchall()}
    assert {"invite_code", "invited_by", "credit_uy", "clips_bonus", "contribute"} <= cols
    names = {r["name"] for r in db._conn.execute("PRAGMA index_list(accounts)").fetchall()}
    assert "accounts_invite_code" in names
    assert db._conn.execute("SELECT invite_code, contribute FROM accounts WHERE id='a1'").fetchone()[0] == ""


def test_database_from_0_4_moves_to_the_lifetime_allowance(tmp_path):
    """0.4 kept a daily cap and credit beyond it; 0.5 has one pool. On the first open the
    service seeds every account with what it had spent plus the allowance, plus any 0.4
    credit still unused — nobody starts in debt, an invite's money is kept. A second open
    changes nothing, and accounts made afterwards start with the allowance alone."""
    import sqlite3

    path = str(tmp_path / "v04.db")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE accounts (
            id TEXT PRIMARY KEY, id_hash TEXT NOT NULL UNIQUE, channel TEXT NOT NULL, hint TEXT NOT NULL,
            created_at INTEGER NOT NULL, granted INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0,
            disabled INTEGER NOT NULL DEFAULT 0, identifier_enc TEXT NOT NULL DEFAULT '', unlimited INTEGER NOT NULL DEFAULT 0,
            password_hash TEXT NOT NULL DEFAULT '', password_set_at INTEGER, failed_logins INTEGER NOT NULL DEFAULT 0,
            locked_until INTEGER, invite_code TEXT NOT NULL DEFAULT '', invited_by TEXT NOT NULL DEFAULT '',
            invites INTEGER NOT NULL DEFAULT 0, credit_uy INTEGER NOT NULL DEFAULT 0, credit_used_uy INTEGER NOT NULL DEFAULT 0,
            clips_bonus INTEGER NOT NULL DEFAULT 0, contribute INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL, ts INTEGER NOT NULL, kind TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '', prompt_tokens INTEGER NOT NULL DEFAULT 0, completion_tokens INTEGER NOT NULL DEFAULT 0,
            charged INTEGER NOT NULL DEFAULT 0, request_id TEXT NOT NULL DEFAULT '', cost_uy INTEGER NOT NULL DEFAULT 0,
            extra TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO accounts (id, id_hash, channel, hint, created_at, invites, credit_uy, credit_used_uy)
            VALUES ('heavy', 'h1', 'email', 'a***@x', 1, 1, 3000000, 400000);
        INSERT INTO accounts (id, id_hash, channel, hint, created_at) VALUES ('fresh', 'h2', 'email', 'b***@x', 2);
        INSERT INTO ledger (account_id, ts, kind, model, charged, cost_uy) VALUES ('heavy', 10, 'chat', 'm', 100, 12500000);
        INSERT INTO ledger (account_id, ts, kind, model, charged, cost_uy) VALUES ('heavy', 11, 'video', 'v', 100, 500000);
        INSERT INTO ledger (account_id, ts, kind, charged, extra) VALUES ('heavy', 12, 'credit', 0, '{"credit_uy":3000000}');
        """
    )
    conn.commit()
    conn.close()

    settings = Settings(database=path, secret="s", admin_token="admin", allowance_cny=10, signup_tokens=0)
    db = Database(path)
    assert "accounts.grant_uy" in db.added
    Cloud(settings, db, LogSender())
    grants = {r["id"]: (int(r["grant_uy"]), r["contribute_bonus_at"]) for r in db._conn.execute("SELECT * FROM accounts")}
    # heavy: ¥13 spent + ¥10 + ¥2.6 of unused 0.4 credit; fresh: ¥10 — and no bonus taken yet
    assert grants == {"heavy": (25_600_000, None), "fresh": (10_000_000, None)}
    db.close()

    db2 = Database(path)
    assert db2.added == set()
    Cloud(settings, db2, LogSender())
    assert {int(r["grant_uy"]) for r in db2._conn.execute("SELECT * FROM accounts")} == {25_600_000, 10_000_000}
    a = db2.create_account("h3", "email", "c***@x", 0, grant_uy=settings.allowance_uy)
    assert int(a["grant_uy"]) == 10_000_000
    db2.close()


async def test_members_may_name_any_model_of_the_right_kind():
    # The menu is the menu for everyone; a member may ask for any model the provider has
    # under the operator's key, by its id, as long as it is used for what it is. The
    # ledger prices it as the dearest menu model of its kind, marked as such.
    app, client, sender, up, cloud = make_stack(allowed_identifiers="Me@Example.com", allowance_cny=0.5)
    member = await sign_up(client, sender, identifier="me@example.com", device="desk")
    guest = await sign_up(client, sender, identifier="13800138000", device="pixel")
    mh = {"Authorization": f"Bearer {member['api_key']}"}
    gh = {"Authorization": f"Bearer {guest['api_key']}"}
    assert member["account"]["any_model"] is True and guest["account"]["any_model"] is False

    # the menu says who may go beyond it (0.10: and lists what the key has, for members — below)
    assert (await client.get("/v1/models", headers=mh)).json()["nanomuse"]["any_model"] is True
    assert (await client.get("/v1/models", headers=gh)).json()["nanomuse"] == {"any_model": False}

    # a typed id is checked with the kind it is for
    r = await client.get("/v1/models/deepseek-v4-pro", params={"kind": "chat"}, headers=mh)
    assert r.status_code == 200
    nm = r.json()["nanomuse"]
    assert nm["listed"] is False and nm["kind"] == "chat" and nm["priced_as"] == "qwen3.8-27b"
    r = await client.get("/v1/models/deepseek-v4-pro", headers=mh)
    assert r.status_code == 404 and "kind=" in r.json()["error"]["message"]
    r = await client.get("/v1/models/deepseek-v4-pro", params={"kind": "chat"}, headers=gh)
    assert r.status_code == 404 and r.json()["error"]["code"] == "model_not_offered"
    r = await client.get("/v1/models/not a model", params={"kind": "chat"}, headers=mh)
    assert r.status_code == 404

    # the chat goes upstream under the typed id, and is priced as the dearest chat model
    body = {"model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "hi"}]}
    r = await client.post("/v1/chat/completions", json=body, headers=mh)
    assert r.status_code == 200, r.text
    assert up.state.requests[-1][2]["model"] == "deepseek-v4-pro"
    assert r.json()["model"] == "deepseek-v4-pro"
    me = (await client.get("/v1/me", headers=mh)).json()
    assert me["recent"][0]["model"] == "deepseek-v4-pro"
    assert me["recent"][0]["cost_cny"] == round((100 * 3.0 + 50 * 12.0) / 1_000_000, 4)

    # not for a guest, and never across kinds — a menu model or a typed one
    r = await client.post("/v1/chat/completions", json=body, headers=gh)
    assert r.status_code == 404 and r.json()["error"]["code"] == "model_not_offered"
    r = await client.post("/v1/chat/completions", json={**body, "model": "qwen-image-3.0"}, headers=mh)
    assert r.status_code == 404 and "image model, not a chat" in r.json()["error"]["message"]
    r = await client.post("/v1/images/generations", json={"model": "deepseek-v4-pro", "prompt": "a cat"}, headers=gh)
    assert r.status_code == 404

    # the permission is the operator's to switch off
    object.__setattr__(app.state.settings, "any_model_members", False)
    r = await client.post("/v1/chat/completions", json=body, headers=mh)
    assert r.status_code == 404
    assert (await client.get("/v1/me", headers=mh)).json()["account"]["any_model"] is False


async def test_wrong_passwords_from_one_network_are_capped_across_accounts():
    """A list of numbers tried once each never trips the per-account lockout; the per-network
    ceiling does. Codes still work from there, and another network is not affected."""
    app, client, sender, up, cloud = make_stack(login_fail_per_ip_hour=3)
    for who in ("13800138000", "13900001111"):
        data = await sign_up(client, sender, identifier=who, device="phone")
        auth = {"Authorization": f"Bearer {data['api_key']}"}
        assert (await client.post("/v1/auth/password", headers=auth, json={"password": "correct horse"})).status_code == 204
    bad = {"X-Forwarded-For": "203.0.113.9"}
    for who in ("13800138000", "13900001111", "13700000000"):
        r = await client.post("/v1/auth/login", json={"identifier": who, "password": "nope", "device": "d"}, headers=bad)
        assert r.status_code == 401 and r.json()["error"]["code"] == "bad_credentials"
    # the fourth try from that address is refused before the password is even looked at
    r = await client.post("/v1/auth/login", json={"identifier": "13800138000", "password": "correct horse", "device": "d"}, headers=bad)
    assert r.status_code == 429 and r.json()["error"]["code"] == "locked"
    assert "network" in r.json()["error"]["message"]
    # a code from the same address still works, and the right password from elsewhere does too
    assert (await client.post("/v1/auth/code", json={"identifier": "13800138000"}, headers=bad)).status_code == 204
    r = await client.post(
        "/v1/auth/login",
        json={"identifier": "13800138000", "password": "correct horse", "device": "d"},
        headers={"X-Forwarded-For": "198.51.100.5"},
    )
    assert r.status_code == 200


async def test_requests_under_way_are_held_against_the_allowance():
    """Several requests started together cannot each pass the allowance check and
    together overshoot it: each is reserved while it runs (a picture at its price, a chat
    at a typical turn's), and at most MAX_IN_FLIGHT of one account's run at once."""
    from nanomuse_cloud.service import InFlight

    app, client, sender, up, cloud = make_stack(
        allowed_identifiers="Me@Example.com", signup_tokens=0, daily_cap_tokens=0, per_minute_requests=0, allowance_cny=0.4, usd_cny=7.0
    )
    guest = await sign_up(client, sender, identifier="13800138000", device="pixel")
    headers = {"Authorization": f"Bearer {guest['api_key']}"}
    caller = cloud.authenticate(guest["api_key"])
    picture = cloud.s.model("qwen-image-3.0").image_cost_uy("1024*1024")
    grant = cloud.s.cny_to_uy(0.4)
    assert picture > 0 and picture * 3 > grant > picture  # one fits, three do not

    # a chat under way holds a typical turn's price; a picture that no longer fits on top
    # of what is held is refused, although the ledger alone would have let it through
    cloud.check_budget(caller, request_id="chat-1", hold_uy=grant - picture // 2)
    assert cloud.in_flight.reserved(caller.account_id) == grant - picture // 2
    with pytest.raises(CloudError) as refused:
        cloud.check_budget(caller, minimum=1, cost_uy=picture, request_id="pic-1")
    assert refused.value.code == "allowance_exhausted"
    cloud.settle(caller, "chat-1")
    cloud.check_budget(caller, minimum=1, cost_uy=picture, request_id="pic-1")  # fits now
    cloud.settle(caller, "pic-1")
    assert cloud.in_flight.reserved(caller.account_id) == 0

    # the cap on requests under way, whatever they cost
    for i in range(cloud.s.max_in_flight):
        cloud.check_budget(caller, request_id=f"c{i}", hold_uy=0)
    with pytest.raises(CloudError) as refused:
        cloud.check_budget(caller, request_id="one-more", hold_uy=0)
    assert refused.value.code == "too_many_in_flight" and refused.value.status == 429
    for i in range(cloud.s.max_in_flight):
        cloud.settle(caller, f"c{i}")
    cloud.check_budget(caller, request_id="one-more", hold_uy=0)
    cloud.settle(caller, "one-more")

    # a clip still being made holds its price until it is charged
    r = await client.post(
        "/api/v1/services/aigc/video-generation/video-synthesis",
        headers=headers,
        json={"model": "wan2.2-i2v-flash", "input": {"prompt": "a dragon"}, "parameters": {"duration": 3}},
    )
    assert r.status_code == 200, r.text
    held = cloud.db.pending_video_cost(caller.account_id)
    assert held > 0
    with pytest.raises(CloudError):  # nothing left beside the clip under way
        cloud.check_budget(caller, minimum=1, cost_uy=grant - held + 1)
    # polled to SUCCEEDED (the fake says so on the second poll): charged, no longer held
    task_id = r.json()["output"]["task_id"]
    for _ in range(2):
        assert (await client.get(f"/api/v1/tasks/{task_id}", headers=headers)).status_code == 200
    assert cloud.db.pending_video_cost(caller.account_id) == 0

    # a reservation nobody settled lapses on its own (a client gone before its stream began)
    clock = [0.0]
    lapsing = InFlight(2, ttl_s=10, clock=lambda: clock[0])
    lapsing.reserve("a", "r1", 5)
    lapsing.reserve("a", "r2", 7)
    assert lapsing.full("a") and lapsing.reserved("a") == 12 and lapsing.snapshot() == {"a": 2}
    clock[0] = 11
    assert not lapsing.full("a") and lapsing.reserved("a") == 0 and lapsing.snapshot() == {}
    # over the HTTP surface, the response says so
    for i in range(cloud.s.max_in_flight):
        cloud.check_budget(caller, request_id=f"h{i}", hold_uy=0)
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_in_flight"


async def test_samples_page_by_ts_and_id_so_a_busy_second_loses_nothing(stack):
    """The export reads 1000 rows a page and the console 20; both used to page by `ts<last`,
    which skipped every other row written in the same second as the page's last one."""
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    aid = data["account"]["id"]
    ids = [cloud.db.add_sample(aid, "m", '[{"role":"user","content":"hi"}]', str(i), 1, 1) for i in range(2300)]
    # all of them land within a second or two: the paging has to cope with a page ending mid-second,
    # and the order stays newest first by the order they happened, not by the random id
    lines = [json.loads(ln) for ln in "".join(cloud.export_samples()).splitlines() if ln]
    assert [ln["id"] for ln in lines] == ids[::-1]
    # the console's paged view, through the API, same thing
    admin = {"X-Admin-Token": "admin"}
    seen: list[str] = []
    before, before_id = 0, ""
    while True:
        q = f"/v1/admin/samples?account_id={aid}&limit=700" + (f"&before={before}&before_id={before_id}" if before else "")
        items = (await client.get(q, headers=admin)).json()["samples"]
        if not items:
            break
        seen += [s["id"] for s in items]
        before, before_id = items[-1]["ts"], items[-1]["id"]
    assert seen == ids[::-1]


async def test_admin_health_is_aggregates_only(stack):
    app, client, sender, up, cloud = stack
    admin = {"X-Admin-Token": "admin"}
    data = await sign_up(client, sender)
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 200
    assert (await client.get("/v1/admin/health")).status_code == 401
    r = await client.get("/v1/admin/health", headers=admin)
    assert r.status_code == 200
    health = r.json()
    assert health["ok"] is True and health["problems"] == []
    assert health["in_flight"] == {"requests": 0, "accounts": 0, "limit": 4}
    assert health["last_hour"]["requests"] == 1 and health["last_hour"]["upstream_errors"] == 0
    assert health["last_hour"]["sign_ins"] == 1 and health["db"]["writable"] is True
    assert health["hub"]["online"] == 0 and health["hub"]["dropped_frames"] == 0
    # nothing in it names an account (not the id, not the number, not its hint;
    # a bare "138" would also match the epoch in "time" for part of each day)
    assert data["account"]["id"] not in r.text
    assert "13800138000" not in r.text and data["account"]["hint"] not in r.text


async def test_session_keys_expire_on_their_own(stack):
    """nanoMuse Web starts a person's container with a key that stops working by itself,
    so the gateway keeps no standing key of theirs (0.13)."""
    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    r = await client.post("/v1/auth/session-key", headers=headers, json={"device": "nanoMuse Web", "ttl_s": 120})
    assert r.status_code == 200, r.text
    short = r.json()
    assert short["api_key"].startswith("nm_") and short["api_key"] != data["api_key"]
    assert 100 <= short["expires_at"] - __import__("time").time() <= 121
    short_headers = {"Authorization": f"Bearer {short['api_key']}"}
    me = (await client.get("/v1/me", headers=short_headers)).json()
    assert me["account"]["id"] == data["account"]["id"]
    sessions = {s["device"]: s for s in (await client.get("/v1/me/sessions", headers=headers)).json()["sessions"]}
    assert sessions["nanoMuse Web"]["expires_at"] == short["expires_at"] and sessions["nanoMuse Web"]["via"] == "session"
    assert sessions["pixel"]["expires_at"] is None
    # the ceiling, and a bad ttl
    r = await client.post("/v1/auth/session-key", headers=headers, json={"ttl_s": 10**9})
    assert r.json()["expires_at"] - __import__("time").time() <= cloud.SESSION_KEY_MAX_S + 1
    assert (await client.post("/v1/auth/session-key", headers=headers, json={"ttl_s": "soon"})).status_code == 400
    # a session key cannot mint another: a key good for two minutes would otherwise hand
    # itself ninety days, and a leaked container key would hold the account for ever
    before = len((await client.get("/v1/me/sessions", headers=headers)).json()["sessions"])
    r = await client.post("/v1/auth/session-key", headers=short_headers, json={"ttl_s": 86400})
    assert r.status_code == 403 and r.json()["error"]["code"] == "session_from_session"
    assert len((await client.get("/v1/me/sessions", headers=headers)).json()["sessions"]) == before
    # past its time it is no key at all — without being revoked by anyone
    key_hash = __import__("hashlib").sha256(short["api_key"].encode()).hexdigest()
    cloud.db._conn.execute("UPDATE api_keys SET expires_at=? WHERE key_hash=?", (int(__import__("time").time()) - 1, key_hash))
    r = await client.get("/v1/me", headers=short_headers)
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_key"
    sessions = (await client.get("/v1/me/sessions", headers=headers)).json()["sessions"]
    assert "nanoMuse Web" not in {s["device"] for s in sessions}


# -- 0.17: lanes, reasoning, region ----------------------------------------------------------


async def test_the_menu_says_which_lane_each_model_is_for(stack, monkeypatch):
    """Contract C4: every chat model on the menu says what it is `for` — `chat`, `gui` or
    both — and which lane it is the recommended pick in; the apps' pickers filter on it and
    take the recommended one of each lane as the default. Picture and clip models are for
    neither (their `kind` says what they do)."""
    from nanomuse_cloud.config import DEFAULT_MODELS, ModelSpec, _models_from_env, menu_warnings

    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    by_id = {m["id"]: m["nanomuse"] for m in data["models"]}
    assert by_id["deepseek-v4.1-flash"]["for"] == ["chat"] and by_id["deepseek-v4.1-flash"]["recommended_for"] == ["chat"]
    assert by_id["qwen3.8-27b"]["for"] == ["gui", "chat"] and by_id["qwen3.8-27b"]["recommended_for"] == ["gui"]
    assert by_id["qwen3.8-flash"]["for"] == ["chat"] and by_id["qwen3.8-flash"]["recommended_for"] == []
    assert by_id["qwen-image-3.0"]["for"] == [] and by_id["wan2.2-i2v-flash"]["for"] == []
    assert by_id["deepseek-v4.1-flash"]["recommended"] is True and by_id["qwen3.8-27b"]["recommended"] is True
    # the same from GET /v1/models, with the prices the brief fixed
    listing = (await client.get("/v1/models", headers={"Authorization": f"Bearer {data['api_key']}"})).json()
    ds = next(m for m in listing["data"] if m["id"] == "deepseek-v4.1-flash")
    assert ds["name"] == "DeepSeek V4.1 Flash" and ds["architecture"]["input_modalities"] == ["text", "image"]
    assert ds["nanomuse"]["price_cny"]["per_m_input"] == 2.0 and ds["nanomuse"]["price_cny"]["per_m_output"] == 8.0
    assert ds["nanomuse"]["in_mult"] == 0.7 and ds["nanomuse"]["out_mult"] == 0.7
    assert [m.id for m in DEFAULT_MODELS][:2] == ["deepseek-v4.1-flash", "qwen3.8-27b"]
    assert menu_warnings(DEFAULT_MODELS) == []  # exactly one recommended per lane

    # the lanes come from CLOUD_MODELS under the JSON name `for`
    monkeypatch.setenv(
        "CLOUD_MODELS",
        json.dumps(
            [
                {"id": "a", "name": "A", "upstream": "a", "for": ["gui"], "recommended": True, "recommended_for": ["gui"]},
                {"id": "b", "name": "B", "upstream": "b", "recommended": True},
                {"id": "p", "name": "P", "upstream": "p", "kind": "image", "output_modalities": ["image"]},
            ]
        ),
    )
    menu = _models_from_env()
    assert [m.lanes for m in menu] == [("gui",), ("chat",), ()]
    assert [m.recommended_lanes for m in menu] == [("gui",), ("chat",), ()]
    assert menu[0].to_public()["nanomuse"]["for"] == ["gui"] and menu[2].to_public()["nanomuse"]["for"] == []
    assert menu_warnings(menu) == []
    assert menu_warnings(menu[:1]) == ["0 chat models recommended for chat (none); the apps expect one"]
    assert menu_warnings((menu[1], menu[1])) == ["2 chat models recommended for chat (b, b); the apps expect one"] + [
        "0 chat models recommended for gui (none); the apps expect one"
    ]
    # a model recommended for both lanes without `recommended_for` counts in both
    both = ModelSpec(id="c", name="C", upstream="c", for_=("chat", "gui"), recommended=True)
    assert both.recommended_lanes == ("chat", "gui")
    # what is refused: an unknown lane, a lane on a picture model, a recommendation without the flag or outside the lanes
    for bad in (
        dict(for_=("voice",)),
        dict(kind="image", output_modalities=("image",), for_=("chat",)),
        dict(recommended_for=("chat",)),
        dict(for_=("gui",), recommended=True, recommended_for=("chat",)),
    ):
        with pytest.raises(ValueError):
            ModelSpec(id="x", name="X", upstream="x", **bad)
    # the admin page lists the lanes next to the prices
    admin = (await client.get("/v1/admin/accounts", headers={"X-Admin-Token": "admin"})).json()["settings"]
    assert admin["model_lanes"]["qwen3.8-27b"] == ["gui", "chat"] and admin["recommended_for"] == {
        "deepseek-v4.1-flash": ["chat"],
        "qwen3.8-27b": ["gui"],
    }


async def test_reasoning_passes_through_and_is_paid_for(stack):
    """A thinking model's turn: `enable_thinking` and the `reasoning_content` the app sends
    back in the history go upstream as they are, the reasoning in the reply (whole or as
    stream deltas) comes back untouched, and the reasoning tokens are counted as completion
    tokens whichever way the provider reports them."""
    from nanomuse_cloud.service import Usage, usage_from_json

    # the counting rule on its own: OpenAI's shape has them inside, DashScope's apart
    assert usage_from_json(
        {"usage": {"prompt_tokens": 10, "completion_tokens": 50, "completion_tokens_details": {"reasoning_tokens": 30}}}
    ) == Usage(10, 50)
    assert usage_from_json(
        {"usage": {"prompt_tokens": 10, "completion_tokens": 6, "output_tokens_details": {"reasoning_tokens": 20}}}
    ) == Usage(10, 26)
    assert usage_from_json({"usage": {"prompt_tokens": 10, "completion_tokens": 6, "completion_tokens_details": {}}}) == Usage(10, 6)
    assert usage_from_json(
        {"usage": {"prompt_tokens": 10, "completion_tokens": 0, "completion_tokens_details": {"reasoning_tokens": 7}}}
    ) == Usage(10, 7)

    app, client, sender, up, cloud = stack
    data = await sign_up(client, sender)
    auth = {"Authorization": f"Bearer {data['api_key']}"}
    history = [
        {"role": "user", "content": "1+1?"},
        {"role": "assistant", "reasoning_content": "two ones", "content": "2"},
        {"role": "user", "content": "and again"},
    ]
    body = {"model": "deepseek-v4.1-flash", "messages": history, "enable_thinking": True}
    r = await client.post("/v1/chat/completions", json=body, headers=auth)
    assert r.status_code == 200, r.text
    sent = up.state.requests[-1][2]
    assert sent["enable_thinking"] is True and sent["messages"] == history  # untouched, reasoning_content and all
    reply = r.json()["choices"][0]["message"]
    assert reply["reasoning_content"] == "先想一下" and reply["content"] == "hi"
    me = (await client.get("/v1/me", headers=auth)).json()
    assert me["recent"][0]["completion_tokens"] == 50  # OpenAI's shape: the 30 reasoning are inside the 50
    assert me["recent"][0]["cost_cny"] == round((100 * 2.0 + 50 * 8.0) / 1_000_000, 4)

    # streamed: the reasoning deltas pass as they are; the usage counts them (DashScope counts apart)
    r = await client.post("/v1/chat/completions", json={**body, "stream": True}, headers=auth)
    assert r.status_code == 200
    frames = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:") and "[DONE]" not in line]
    deltas = [c["delta"] for f in frames for c in f.get("choices") or []]
    assert [d.get("reasoning_content") for d in deltas[:2]] == ["先想", "一下"] and deltas[2:] == [
        {"content": "你好"},
        {"content": "，"},
        {"content": "世界"},
    ]
    assert all(f["model"] == "deepseek-v4.1-flash" for f in frames)
    me = (await client.get("/v1/me", headers=auth)).json()
    assert me["recent"][0]["prompt_tokens"] == 40 and me["recent"][0]["completion_tokens"] == 26
    # the default stands when the app says nothing: no reasoning asked, none returned
    r = await client.post("/v1/chat/completions", json={"model": "deepseek-v4.1-flash", "messages": history}, headers=auth)
    assert r.status_code == 200 and up.state.requests[-1][2]["enable_thinking"] is False
    assert "reasoning_content" not in r.json()["choices"][0]["message"]


async def test_a_chat_starts_while_anything_of_the_allowance_is_left():
    """The reservation held while a chat runs (a typical turn's price) keeps requests
    started together from overshooting the allowance; it must not refuse a single, normal
    turn on an account with less than that left. The second turn started on top of the
    first is what it refuses."""
    from nanomuse_cloud.service import CHAT_RESERVE_COMPLETION_TOKENS, CHAT_RESERVE_PROMPT_TOKENS

    app, client, sender, up, cloud = make_stack(allowance_cny=0.02)
    data = await sign_up(client, sender)
    auth = {"Authorization": f"Bearer {data['api_key']}"}
    spec = cloud.model_for("qwen3.8-27b", "chat", None)
    reserve = cloud.chat_reserve_uy(spec)
    assert reserve == spec.chat_cost_uy(CHAT_RESERVE_PROMPT_TOKENS, CHAT_RESERVE_COMPLETION_TOKENS)
    assert reserve > cloud.s.allowance_uy  # the hold is more than the whole allowance here
    body = {"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    r = await client.post("/v1/chat/completions", json=body, headers=auth)
    assert r.status_code == 200, r.text  # the turn runs
    # two at once: the first holds its reserve, the second finds nothing left beyond it
    caller = cloud.authenticate(data["api_key"])
    cloud.check_budget(caller, request_id="first", hold_uy=reserve)
    with pytest.raises(CloudError) as refused:
        cloud.check_budget(caller, request_id="second", hold_uy=reserve)
    assert refused.value.code == "allowance_exhausted"
    cloud.settle(caller, "first")
    cloud.check_budget(caller, request_id="third", hold_uy=reserve)  # and again once the first is settled
    cloud.settle(caller, "third")


async def test_me_says_where_the_person_is_and_orders_the_ways_on_by_it(tmp_path):
    """Contract C5: `/v1/me` carries `region` — `cn` for a mainland phone number or an
    address placed in mainland China, `intl` for an address placed elsewhere (Hong Kong,
    Macao and Taiwan count as elsewhere: Bailian does not sign them up), `unknown` when
    neither is known — and the "ways on" when the allowance is out lead the mainland to
    Bailian first, everyone else to OpenRouter first. The refusal says the same."""
    from nanomuse_cloud.geo import Place
    from nanomuse_cloud.service import REGIONS, region_of_place

    assert REGIONS == ("cn", "intl", "unknown")
    assert region_of_place(None) == "unknown" and region_of_place(Place()) == "unknown"
    assert region_of_place(Place(country="本地网络", local=True)) == "unknown"
    assert region_of_place(Place(country="中国", code="CN", province="浙江省", city="杭州市")) == "cn"
    assert region_of_place(Place(country="中国", code="CN", province="香港")) == "intl"  # the older layout: no HK code
    assert region_of_place(Place(country="中国", code="TW", province="台湾省")) == "intl"
    assert region_of_place(Place(country="United States", code="US", province="California")) == "intl"

    db = tmp_path / "ip2region_v4.xdb"
    db.write_bytes(
        tiny_xdb(
            [
                ("1.2.3.0", "1.2.3.255", "中国|浙江省|杭州市|阿里|CN"),
                ("8.8.8.0", "8.8.8.255", "United States|California|0|Google LLC|US"),
                ("1.2.9.0", "1.2.9.255", "中国|香港|0|HKT|HK"),
            ]
        )
    )
    app, client, sender, up, cloud = make_stack(
        geoip_db=str(db), catalog_probe=False, allowance_cny=0.002, invite_url="https://nanomuse.cn/web/?invite="
    )
    assert app.state.geo.ready

    def auth(data, ip):
        return {"Authorization": f"Bearer {data['api_key']}", "X-Forwarded-For": ip}

    # a mainland number is `cn` wherever it signs in from; an address decides for the rest
    phone = await sign_up(client, sender, identifier="13800138000", device="pixel", headers={"X-Forwarded-For": "8.8.8.8"})
    assert phone["region"] == "cn"  # the sign-in answer carries it too
    assert (await client.get("/v1/me", headers=auth(phone, "8.8.8.8"))).json()["region"] == "cn"
    us = await sign_up(client, sender, identifier="me@example.com", device="desk", headers={"X-Forwarded-For": "8.8.8.8"})
    assert us["region"] == "intl"
    hk = await sign_up(client, sender, identifier="hk@example.com", device="desk", headers={"X-Forwarded-For": "1.2.9.9"})
    assert hk["region"] == "intl"
    hz = await sign_up(client, sender, identifier="hz@example.com", device="desk", headers={"X-Forwarded-For": "1.2.3.4"})
    assert hz["region"] == "cn"
    nowhere = await sign_up(client, sender, identifier="who@example.com", device="desk", headers={"X-Forwarded-For": "9.9.9.9"})
    assert nowhere["region"] == "unknown"
    # a foreign number: not the mainland; the address says the rest
    abroad = await sign_up(client, sender, identifier="+14155552671", device="desk", headers={"X-Forwarded-For": "8.8.8.8"})
    assert abroad["region"] == "intl"
    # the region follows the address the request comes from, for an account without a mainland number
    assert (await client.get("/v1/me", headers=auth(us, "1.2.3.4"))).json()["region"] == "cn"
    assert (await client.get("/v1/me", headers=auth(us, "10.0.0.1"))).json()["region"] == "unknown"

    # the ways on, in order: the mainland to Bailian, the rest to OpenRouter, the invitation last
    cn_ways = (await client.get("/v1/me", headers=auth(phone, "8.8.8.8"))).json()["spend"]["ways"]
    assert [w["id"] for w in cn_ways] == ["bailian", "openrouter", "invite"]
    assert cn_ways[0] == {"id": "bailian", "url": "https://nanomuse.cn/own-key", "mainland_only": True, **WAY_FACTS["bailian"]}
    assert cn_ways[1] == {"id": "openrouter", "url": "https://openrouter.ai/keys", "mainland_only": False, **WAY_FACTS["openrouter"]}
    assert (
        cn_ways[2]["id"] == "invite" and cn_ways[2]["url"].startswith("https://nanomuse.cn/web/?invite=") and cn_ways[2]["bonus_cny"] == 5
    )
    for who, ip in ((us, "8.8.8.8"), (nowhere, "9.9.9.9")):
        ways = (await client.get("/v1/me", headers=auth(who, ip))).json()["spend"]["ways"]
        assert [w["id"] for w in ways] == ["openrouter", "bailian", "invite"], who["region"]

    # the refusal when the allowance is out says the way that fits the person
    async def exhaust(data, ip):
        hdr = auth(data, ip)
        body = {"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
        for _ in range(3):
            assert (await client.post("/v1/chat/completions", headers=hdr, json=body)).status_code == 200
        r = await client.post("/v1/chat/completions", headers=hdr, json=body)
        assert r.status_code == 429 and r.json()["error"]["code"] == "allowance_exhausted"
        return r.json()["error"]

    err = await exhaust(phone, "8.8.8.8")
    assert err["region"] == "cn" and [w["id"] for w in err["ways"]] == ["bailian", "openrouter", "invite"]
    assert "阿里云百炼" in err["message"] and "free tier for mainland China" in err["message"] and "OpenRouter" not in err["message"]
    assert "one key" in err["message"] and "a plan you already pay for (ChatGPT, Claude or Kimi" in err["message"]
    assert err["guidance"]["region"] == "cn" and err["guidance"]["providers"][0]["id"] == "bailian"
    err = await exhaust(us, "8.8.8.8")
    assert err["region"] == "intl" and [w["id"] for w in err["ways"]] == ["openrouter", "bailian", "invite"]
    assert "OpenRouter, with one account, one key and pay as you go, or OpenAI first" in err["message"]
    assert "Alibaba Cloud Bailian only signs up accounts from mainland China" in err["message"]
    assert "a plan you already pay for (ChatGPT, Claude or Kimi" in err["message"]
    assert err["openrouter_url"] == "https://openrouter.ai/keys" and err["own_key_docs"] == "https://nanomuse.cn/own-key"
    assert [p["id"] for p in err["guidance"]["providers"][:2]] == ["openrouter", "openai"]
    err = await exhaust(nowhere, "9.9.9.9")
    assert err["region"] == "unknown" and "OpenRouter or OpenAI outside mainland China, Alibaba Cloud Bailian inside" in err["message"]
    assert "invite a friend (+¥5 for each of you)" in err["message"] and "keep working" in err["message"]
    assert [p["id"] for p in err["guidance"]["providers"][:2]] == ["openrouter", "bailian"]
    # a picture refused up front says the same
    r = await client.post("/v1/images/generations", headers=auth(us, "8.8.8.8"), json={"model": "qwen-image-3.0", "prompt": "a cat"})
    assert r.status_code == 429 and r.json()["error"]["region"] == "intl"

    # without a geo file: the mainland number is still `cn`, everyone else `unknown`
    app2, client2, sender2, *_ = make_stack(catalog_probe=False)
    assert not app2.state.geo.enabled
    p2 = await sign_up(client2, sender2, identifier="13800138000", device="pixel", headers={"X-Forwarded-For": "8.8.8.8"})
    e2 = await sign_up(client2, sender2, identifier="me@example.com", device="desk", headers={"X-Forwarded-For": "8.8.8.8"})
    assert p2["region"] == "cn" and e2["region"] == "unknown"
    # the public config names the OpenRouter page next to the Bailian one
    cfg = (await client2.get("/v1/config")).json()
    assert cfg["openrouter_url"] == "https://openrouter.ai/keys"
