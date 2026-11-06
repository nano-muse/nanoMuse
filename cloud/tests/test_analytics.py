"""0.28: what each chat call looked like and how it went (the `calls` rows and the live
meter), the kept turns' shape (`sample_stats`), the analytics pages behind the console, and
the platform names the relay gives the clients it sees."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from nanomuse_cloud import analytics as an
from nanomuse_cloud.api import create_app
from nanomuse_cloud.client import is_app, is_nanomuse_client, platform_of, ua_family
from nanomuse_cloud.config import Settings
from nanomuse_cloud.db import Database
from nanomuse_cloud.senders import LogSender
from nanomuse_cloud.service import Cloud

# the tests call the models as one of the apps would; `apps_only` (0.28) refuses other software
APP_UA = {"User-Agent": "nanoMuse/0.0 (tests)"}

ADMIN = {"X-Admin-Token": "admin"}
PHONE_UA = "nanoMuse/1.0.6 (iOS 27.2; iPhone)"


# -- the client software's name ------------------------------------------------------------------


def test_platform_of_tells_the_apps_apart_and_names_the_rest():
    assert platform_of("nanoMuse-Android/1.0.6 (Pixel 8)") == "android"
    assert platform_of("nanoMuse-iOS/1.0.6 (iPhone)") == "ios"
    # the phones' model calls carry the system in brackets: iOS was "runtime" before 0.28
    assert platform_of(PHONE_UA) == "ios"
    assert platform_of("nanoMuse/1.0.6 (Android 16; Pixel 8)") == "android"
    assert platform_of("nanoMuse/0.4.0 (darwin)") == "macos"
    assert platform_of("nanoMuse/0.4.0 (Windows 11)") == "windows"
    assert platform_of("nanoMuse/0.4.0") == "runtime"
    # the runtime of 1.0.6 and earlier called the models with the OpenAI SDK's own string
    assert platform_of("AsyncOpenAI/Python 1.109.1") == "runtime"
    assert platform_of("deepseek-harness/1.2.0-rc.2") == "desktop"
    assert platform_of("nanoMuse-Desktop/1.0.6 Electron") == "desktop"
    assert platform_of("Minis/1.14 (iPhone)") == "minis"
    assert platform_of("Mozilla/5.0 (Macintosh)") == "browser"
    for ua in ("", "python-requests/2.32", "Go-http-client/1.1", "curl/8.4", "OpenAI/Python 1.5", "nanoMuse-Pool-Worker/1.0"):
        assert platform_of(ua) == "other", ua
        assert not is_app(platform_of(ua))
    assert is_app("ios") and is_app("browser")
    assert is_nanomuse_client("runtime") and is_nanomuse_client("browser")
    assert not is_nanomuse_client("minis") and not is_nanomuse_client("other")


def test_ua_family_groups_by_the_first_token():
    assert ua_family("") == "(empty)"
    assert ua_family("Mozilla/5.0 (X11; Linux) Chrome/130") == "Mozilla"
    assert ua_family("python-requests/2.32.3") == "python-requests"
    assert ua_family(PHONE_UA) == "nanoMuse"
    assert ua_family("nanoMuse-Android/1.0.6 (Pixel 8)") == "nanoMuse-Android"
    assert len(ua_family("x" * 100 + "/1")) <= 40


# -- a request's shape, a turn's shape, an account's score -----------------------------------------


def test_request_shape_counts_without_reading():
    body = {
        "messages": [
            {"role": "system", "content": "be brief"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
                ],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"type": "function", "function": {"name": "phone_tap", "arguments": "{}"}}],
            },
            {"role": "tool", "content": "ok", "tool_call_id": "1"},
        ],
        "tools": [{"type": "function", "function": {"name": "web_search"}}, {"type": "function", "function": {"name": "phone_tap"}}],
    }
    shape = an.request_shape(body)
    assert shape == {"messages": 4, "images": 1, "tools": 2, "tool_names_offered": ["web_search", "phone_tap"], "hands": True}
    assert an.request_shape({"messages": [{"role": "user", "content": "hi"}]}) == {
        "messages": 1,
        "images": 0,
        "tools": 0,
        "tool_names_offered": [],
        "hands": False,
    }
    assert an.request_shape({"messages": "nonsense", "tools": 3})["messages"] == 0
    assert an.is_hands_tool("mcp__nanomuse__computer_click") and an.is_hands_tool("android_swipe") and not an.is_hands_tool("web_search")


def test_tool_names_from_replies_and_chunks_are_joined_distinct_and_cut():
    reply = {"choices": [{"message": {"role": "assistant", "tool_calls": [{"function": {"name": "a"}}, {"function": {"name": "b"}}]}}]}
    chunk = {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "a", "arguments": ""}}]}}]}
    assert an.reply_tool_names(reply) == ["a", "b"]
    assert an.reply_tool_names("not a dict") == [] and an.reply_tool_names({"choices": [{"message": {}}]}) == []
    assert an.delta_tool_names(chunk) == ["a"] and an.delta_tool_names({"choices": [{"delta": {"content": "x"}}]}) == []
    assert an.join_tool_names(["a", "b,c", "a", "", "d"]) == "a,b c,d"
    assert len(an.join_tool_names([f"tool_{i}" for i in range(200)])) <= 400


def test_sample_shape_keeps_figures_and_a_hash_never_the_words():
    request = json.dumps(
        [
            {"role": "user", "content": "Plan my trip to Kyoto next week, three days, temples and food"},
            {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "web_search", "arguments": "{}"}}]},
            {"role": "tool", "content": "..."},
            {
                "role": "user",
                "content": [{"type": "text", "text": "  Looks good,   book the  first "}, {"type": "image_url", "image_url": {}}],
            },
        ]
    )
    row = an.sample_shape("s1", "acc1", 1700000000, "qwen", request, "Done. " * 20, json.dumps({"ua": PHONE_UA}))
    assert row["sample_id"] == "s1" and row["account_id"] == "acc1" and row["platform"] == "ios"
    assert row["messages"] == 4 and row["pictures"] == 1 and row["tool_calls"] == 1 and row["hands"] == 0
    assert row["trivial"] == 0 and row["user_chars"] == len("  Looks good,   book the  first ")
    assert row["reply_chars"] == 120 and row["bytes"] == len(request) + 120
    # the hash is of the normalised words: spacing and case do not make a different message
    again = an.sample_shape("s2", "acc1", 1, "qwen", json.dumps([{"role": "user", "content": "looks good, book the first"}]), "", "{}")
    assert again["user_hash"] == row["user_hash"] and len(row["user_hash"]) == 16
    assert not any(word in json.dumps(row) for word in ("Kyoto", "book", "Done"))
    # a greeting, a bare "test", a message too short to mean anything: trivial
    for text in ("hi", "你好", "test", "1", ""):
        assert an.sample_shape("s", "a", 1, "m", json.dumps([{"role": "user", "content": text}]), "x", "{}")["trivial"] == 1, text
    # a short message late in a conversation, or beside a picture, is not
    deep = json.dumps([{"role": "user", "content": "first"}, {"role": "assistant", "content": "ok"}, {"role": "user", "content": "go on"}])
    assert an.sample_shape("s", "a", 1, "m", deep, "x", "{}")["trivial"] == 0
    # bad JSON is a row with zeros, not an exception
    assert an.sample_shape("s", "a", 1, "m", "{not json", "x", "{also bad")["messages"] == 0
    # the operator's tools make a screen-operation turn
    hands = json.dumps(
        [{"role": "user", "content": "open settings"}, {"role": "assistant", "tool_calls": [{"function": {"name": "phone_tap"}}]}]
    )
    assert an.sample_shape("s", "a", 1, "m", hands, "x", "{}")["hands"] == 1


def test_score_account_tiers():
    score = an.Analytics.score_account
    assert score(0, 0, 0, 0, 0, 0, 0) == (0, "low")
    # thirty useful, distinct, tool-using turns: high
    s, tier = score(30, 0, 0, 30, 10, 20, 5)
    assert s >= 60 and tier == "high"
    # a handful of good turns is not yet high, whatever the score
    s, tier = score(5, 0, 0, 5, 0, 0, 0)
    assert tier == "medium"
    # all trivial: low; half the turns one repeated message: low
    assert score(20, 20, 0, 20, 0, 0, 0) == (0, "low")
    assert score(40, 0, 0, 10, 0, 0, 0)[1] == "low"
    assert 0 <= score(1000, 0, 0, 1000, 1000, 1000, 1000)[0] <= 100


def test_percentile_is_nearest_rank():
    assert an.percentile([], 0.5) == 0
    assert an.percentile([5], 0.99) == 5
    assert an.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.5) == 5
    assert an.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == 10
    assert an.percentile([10, 1, 5], 0.0) == 1


# -- the live meter --------------------------------------------------------------------------------


def _finish(meter: an.LiveMeter, call: an.InFlightCall, status: str = "ok", **more) -> dict:
    row = {
        "ts": call.ts,
        "account_id": call.account_id,
        "model": call.model,
        "platform": call.platform,
        "family": "nanoMuse",
        "status": status,
        "detail": "",
        "stream": 1,
        "wait_ms": 10,
        "ttft_ms": 500,
        "total_ms": 2000,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "messages": 1,
        "images": 0,
        "tools": 0,
        "tool_names": "",
        "hands": 0,
        "retries": 0,
        "request_id": "r",
    }
    row.update(more)
    meter.finish(call, row)
    return row


def test_live_meter_phases_minutes_and_summary():
    meter = an.LiveMeter(keep=5)
    c = meter.start("account-one", "qwen", "ios", True, {"images": 1, "hands": True})
    view = meter.running()[0]
    assert view["phase"] == "waiting" and view["account"] == "account-" and view["images"] == 1 and view["hands"] is True
    meter.slot(c)
    assert meter.running()[0]["phase"] == "upstream"
    meter.first(c)
    first_at = c.first_at
    meter.first(c)  # the first token is the first token
    assert c.first_at == first_at and meter.running()[0]["phase"] == "streaming"
    _finish(meter, c)
    assert meter.running() == [] and meter.counts["ok"] == 1
    for i in range(6):
        _finish(meter, meter.start("a", "qwen", "android", False), "upstream_timeout" if i == 0 else "ok", ttft_ms=100 * (i + 1))
    assert len(meter.finished) == 5  # the ring keeps the newest
    assert meter.counts["ok"] == 6 and meter.counts["upstream_timeout"] == 1
    now = int(time.time())
    minutes = meter.minutes(now, 3)
    assert len(minutes) == 3 and minutes[-1]["t"] == now - now % 60 and sum(m["n"] for m in minutes) == 5
    assert all("_ttft" not in m for m in minutes)
    s = meter.summary(now - 600)
    assert s["requests"] == 5 and s["ok"] == 5 and s["errors"] == 0 and s["p50_ttft_ms"] > 0 and s["tokens_out"] == 250
    assert meter.recent(2)[0]["ts"] >= meter.recent(2)[1]["ts"] and "account_id" not in meter.recent(1)[0]
    # warmed rows count in the window like the ones seen live
    fresh = an.LiveMeter()
    assert fresh.warm(meter.finished) == 5 and fresh.summary(now - 600)["requests"] == 5 and fresh.counts["ok"] == 0


# -- through the app -------------------------------------------------------------------------------


def fake_upstream() -> FastAPI:
    up = FastAPI()
    up.state.requests = []
    up.state.chat_503s = 0
    up.state.delay_s = 0.0
    up.state.cached_tokens = 0  # when set, the usage says this many prompt tokens came from the cache

    @up.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        up.state.requests.append(body)
        if up.state.delay_s:
            await asyncio.sleep(up.state.delay_s)
        if up.state.chat_503s:
            up.state.chat_503s -= 1
            return JSONResponse(status_code=503, content={"error": {"message": "busy"}})
        if body.get("model") == "boom":
            return JSONResponse(status_code=500, content={"error": {"message": "upstream exploded"}})
        if any("forbidden words" in str(m.get("content")) for m in body.get("messages") or [] if isinstance(m, dict)):
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "DataInspectionFailed: inappropriate content", "code": "data_inspection_failed"}},
            )
        tools = body.get("tools") or []
        cached = {"prompt_tokens_details": {"cached_tokens": up.state.cached_tokens}} if up.state.cached_tokens else {}
        if body.get("stream"):

            async def gen():
                if tools:
                    name = tools[0]["function"]["name"]
                    chunk = {
                        "choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"name": name, "arguments": ""}}]}}]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
                for piece in ("你好", "，", "世界"):
                    yield f"data: {json.dumps({'choices': [{'index': 0, 'delta': {'content': piece}}]})}\n\n"
                yield f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 40, 'completion_tokens': 6, **cached}})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")
        message: dict = {"role": "assistant", "content": "hi"}
        if tools:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"type": "function", "function": {"name": tools[0]["function"]["name"], "arguments": "{}"}}],
            }
        return {
            "id": "c1",
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, **cached},
        }

    return up


def make_settings(**more) -> Settings:
    return Settings(
        database=":memory:",
        secret="test-secret",
        admin_token="admin",
        upstream_base="http://upstream/v1",
        upstream_key="sk-upstream",
        signup_tokens=1000,
        daily_cap_tokens=100_000,
        per_minute_requests=100,
        chat_concurrency=2,
        chat_retry_base_s=0,
        public_base="http://cloud.test",
        **more,
    )


@pytest.fixture
def stack():
    up = fake_upstream()
    settings = make_settings()
    sender = LogSender()
    cloud = Cloud(settings, Database(":memory:"), sender)
    app = create_app(settings, cloud, upstream_transport=httpx.ASGITransport(app=up))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cloud.test", headers=APP_UA)
    return app, client, sender, up, cloud


async def sign_up(client, sender, identifier="13800138000", ua=PHONE_UA):
    headers = {"User-Agent": ua}
    r = await client.post("/v1/auth/code", json={"identifier": identifier}, headers=headers)
    assert r.status_code == 204, r.text
    _, code = sender.sent[-1]
    r = await client.post("/v1/auth/verify", json={"identifier": identifier, "code": code, "device": "phone"}, headers=headers)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['api_key']}", "User-Agent": ua}, r.json()["account"]["id"]


def rows(cloud) -> list[dict]:
    return [dict(r) for r in cloud.db.calls_since(0)]


async def test_every_chat_leaves_a_calls_row_with_its_shape_and_how_it_went(stack):
    app, client, sender, up, cloud = stack
    headers, aid = await sign_up(client, sender)
    plain = {"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    tools = [{"type": "function", "function": {"name": "phone_tap", "parameters": {}}}]
    pictured = [{"role": "user", "content": [{"type": "text", "text": "what"}, {"type": "image_url", "image_url": {"url": "data:,x"}}]}]

    r = await client.post("/v1/chat/completions", headers=headers, json=plain)
    assert r.status_code == 200
    r = await client.post("/v1/chat/completions", headers=headers, json={**plain, "messages": pictured, "tools": tools, "stream": True})
    assert r.status_code == 200 and "你好" in r.text
    r = await client.post("/v1/chat/completions", headers=headers, json={**plain, "tools": tools})
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "phone_tap"
    r = await client.post(
        "/v1/chat/completions", headers=headers, json={**plain, "messages": [{"role": "user", "content": "forbidden words"}]}
    )
    assert r.status_code == 400
    r = await client.post(
        "/v1/chat/completions",
        headers=headers,
        json={**plain, "messages": [{"role": "user", "content": "forbidden words"}], "stream": True},
    )
    assert r.status_code == 200 and b"content_rejected" in r.content
    settings = app.state.settings
    object.__setattr__(settings, "models", settings.models + (type(settings.models[0])(id="boom", name="Boom", upstream="boom"),))
    r = await client.post("/v1/chat/completions", headers=headers, json={**plain, "model": "boom"})
    assert r.status_code == 502
    r = await client.post("/v1/chat/completions", headers=headers, json={**plain, "model": "boom", "stream": True})
    assert r.status_code == 200 and b'"code": "upstream"' in r.content or b"upstream" in r.content
    up.state.chat_503s = 1
    r = await client.post("/v1/chat/completions", headers=headers, json=plain)
    assert r.status_code == 200

    got = rows(cloud)
    assert [c["status"] for c in got] == [
        "ok",
        "ok",
        "ok",
        "content_rejected",
        "content_rejected",
        "upstream_error",
        "upstream_error",
        "ok",
    ]
    assert all(
        c["account_id"] == aid and c["platform"] == "ios" and c["family"] == "nanoMuse" and c["model"] == got[0]["model"] for c in got[:5]
    )
    first, streamed, called, rejected, rejected_stream, boom, boom_stream, retried = got
    assert first["stream"] == 0 and first["prompt_tokens"] == 100 and first["completion_tokens"] == 50 and first["messages"] == 1
    assert first["hands"] == 0 and first["tools"] == 0 and first["images"] == 0 and first["request_id"]
    assert streamed["stream"] == 1 and streamed["images"] == 1 and streamed["tools"] == 1 and streamed["hands"] == 1
    assert streamed["tool_names"] == "phone_tap" and streamed["prompt_tokens"] == 40 and streamed["completion_tokens"] == 6
    assert called["tool_names"] == "phone_tap" and called["hands"] == 1
    assert rejected["detail"] == "400" and rejected_stream["detail"] == "400" and rejected_stream["stream"] == 1
    assert boom["detail"] == "500" and boom["model"] == "boom" and boom_stream["detail"] == "500"
    assert retried["retries"] == 1 and retried["status"] == "ok"
    assert all(c["total_ms"] >= c["ttft_ms"] >= 0 and c["wait_ms"] >= 0 for c in got)
    # never a word of the conversation
    dumped = json.dumps(got)
    assert "forbidden" not in dumped and "你好" not in dumped and "what" not in dumped


async def test_a_budget_refusal_is_a_row_too_and_the_account_page_sums_them(stack):
    app, client, sender, up, cloud = stack
    headers, aid = await sign_up(client, sender)
    plain = {"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    for _ in range(7):
        assert (await client.post("/v1/chat/completions", headers=headers, json=plain)).status_code == 200
    r = await client.post("/v1/chat/completions", headers=headers, json=plain)
    assert r.status_code == 402
    got = rows(cloud)
    assert len(got) == 8 and got[-1]["status"] == "refused" and got[-1]["detail"] == "out_of_tokens"
    assert got[-1]["wait_ms"] == 0 and got[-1]["ttft_ms"] == 0
    page = (await client.get(f"/v1/admin/accounts/{aid}", headers=ADMIN)).json()
    assert page["calls"]["n"] == 8 and page["calls"]["ok"] == 7 and page["calls"]["refused"] == 1 and page["calls"]["errors"] == 0
    assert page["calls"]["avg_total_ms"] >= 0 and page["calls"]["last_ts"]
    # deleting the account takes its rows along
    r = await client.post("/v1/admin/delete", headers=ADMIN, json={"account_id": aid})
    assert r.status_code in (200, 204), r.text
    assert rows(cloud) == [] and cloud.db.calls_count() == 0


async def test_the_live_view_shows_the_gate_the_queue_and_the_last_hour(stack):
    app, client, sender, up, cloud = stack
    headers, _aid = await sign_up(client, sender)
    plain = {"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}], "stream": True}
    live = (await client.get("/v1/admin/live", headers=ADMIN)).json()
    assert live["gate"] == {"active": 0, "waiting": 0, "limit": 2} and live["running"] == [] and len(live["minutes"]) == 60
    assert live["settings"]["chat_concurrency"] == 2 and live["last_10m"]["requests"] == 0 and live["models"]
    assert (await client.get("/v1/admin/live")).status_code == 401

    up.state.delay_s = 0.3
    tasks = [asyncio.create_task(client.post("/v1/chat/completions", headers=headers, json=plain)) for _ in range(3)]
    await asyncio.sleep(0.15)
    live = (await client.get("/v1/admin/live", headers=ADMIN)).json()
    # two slots, three requests: two with the provider, one waiting for a slot
    assert live["gate"]["active"] == 2 and live["gate"]["waiting"] == 1
    phases = sorted(c["phase"] for c in live["running"])
    assert phases == ["upstream", "upstream", "waiting"]
    assert all(c["account"].endswith("") and len(c["account"]) == 8 for c in live["running"])
    for t in tasks:
        assert (await t).status_code == 200
    live = (await client.get("/v1/admin/live", headers=ADMIN)).json()
    assert live["running"] == [] and live["gate"]["active"] == 0
    assert live["last_10m"]["requests"] == 3 and live["last_10m"]["ok"] == 3 and live["last_10m"]["waited_share"] > 0
    assert live["last_10m"]["p95_wait_ms"] >= 100 and live["last_hour"]["tokens_out"] == 18
    assert live["since_start"]["counts"]["ok"] == 3 and len(live["recent"]) == 3
    # the three calls fall in the current minute's bucket, or the previous one when the clock
    # turned over between them and the read (CI saw 0 == 3 once at hh:mm:00.7)
    assert sum(m["n"] for m in live["minutes"][-2:]) == 3 and live["in_flight"] == {"requests": 0, "accounts": 0, "limit": 4}


async def test_a_queued_stream_hears_where_it_stands_and_a_slow_one_stays_warm(stack, monkeypatch):
    """0.31: two slots and four streams. The third and fourth wait at the gate and, every tick,
    get a chunk with no choices and a `nanomuse` field: `queued`, how many are ahead (0 for
    the third, 1 for the fourth), how long they have waited; then `working` once the slot is
    theirs. While the provider takes its time over the first bytes, a comment line goes out
    every tick, which every SSE parser skips. The words of the reply and the usage are the
    same as without any of it, and the telemetry rows count the wait at the gate."""
    from nanomuse_cloud import api as api_mod

    monkeypatch.setattr(api_mod, "STATUS_TICK", 0.05)
    monkeypatch.setattr(api_mod, "KEEPALIVE_TICK", 0.05)
    app, client, sender, up, cloud = stack
    headers, _aid = await sign_up(client, sender)
    plain = {"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}], "stream": True}
    up.state.delay_s = 0.4

    async def one():
        r = await client.post("/v1/chat/completions", headers=headers, json=plain)
        assert r.status_code == 200
        return r.text

    tasks = []
    for _ in range(4):
        tasks.append(asyncio.create_task(one()))
        await asyncio.sleep(0.02)  # arrival order is the queue's order
    texts = [await t for t in tasks]

    def statuses(text: str) -> list[dict]:
        out = []
        for line in text.splitlines():
            if line.startswith("data:") and '"nanomuse"' in line:
                out.append(json.loads(line[5:].strip())["nanomuse"])
        return out

    def words(text: str) -> str:
        out = []
        for line in text.splitlines():
            if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                continue
            obj = json.loads(line[5:].strip())
            for ch in obj.get("choices") or []:
                out.append(ch["delta"].get("content") or "")
        return "".join(out)

    # the first two never waited: no status chunks, keepalive comments only
    for text in texts[:2]:
        assert statuses(text) == [] and ": keepalive" in text and words(text) == "你好，世界"
    # the third waited behind nobody, the fourth behind one; both then heard "working"
    third, fourth = statuses(texts[2]), statuses(texts[3])
    assert third[0]["phase"] == "queued" and third[0]["ahead"] == 0 and third[0]["waited_ms"] >= 40
    assert fourth[0]["phase"] == "queued" and fourth[0]["ahead"] == 1
    assert third[-1]["phase"] == "working" and fourth[-1]["phase"] == "working" and "ahead" not in third[-1]
    assert all(s["phase"] == "queued" for s in third[:-1]) and third[-1]["waited_ms"] >= third[0]["waited_ms"]
    for text in texts[2:]:
        assert words(text) == "你好，世界" and text.rstrip().endswith("data: [DONE]")
        # a status chunk is a chat chunk with no choices: the shape every parser lets through
        chunk = json.loads(next(line for line in text.splitlines() if '"nanomuse"' in line)[5:])
        assert chunk["object"] == "chat.completion.chunk" and chunk["choices"] == [] and chunk["model"] == "qwen3.8-27b"
    live = (await client.get("/v1/admin/live", headers=ADMIN)).json()
    assert live["gate"] == {"active": 0, "waiting": 0, "limit": 2}
    assert live["last_10m"]["requests"] == 4 and live["last_10m"]["ok"] == 4 and live["last_10m"]["waited_share"] == 0.5
    assert live["last_hour"]["tokens_out"] == 24


async def test_a_waiter_that_leaves_the_queue_gives_its_place_back(stack, monkeypatch):
    """The app closes a stream while it waits at the gate (the person gave up): its place goes,
    the ones behind move up, and the slot it would have taken is handed to the next in line."""
    from nanomuse_cloud import api as api_mod

    monkeypatch.setattr(api_mod, "STATUS_TICK", 0.05)
    app, client, sender, up, cloud = stack
    headers, _aid = await sign_up(client, sender)
    plain = {"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}], "stream": True}
    up.state.delay_s = 0.4
    tasks = [asyncio.create_task(client.post("/v1/chat/completions", headers=headers, json=plain)) for _ in range(3)]
    await asyncio.sleep(0.15)
    live = (await client.get("/v1/admin/live", headers=ADMIN)).json()
    assert live["gate"] == {"active": 2, "waiting": 1, "limit": 2}
    tasks[2].cancel()
    with pytest.raises(asyncio.CancelledError):
        await tasks[2]
    await asyncio.sleep(0.05)
    live = (await client.get("/v1/admin/live", headers=ADMIN)).json()
    assert live["gate"]["waiting"] == 0 and live["gate"]["active"] == 2
    for t in tasks[:2]:
        assert (await t).status_code == 200
    live = (await client.get("/v1/admin/live", headers=ADMIN)).json()
    assert live["gate"] == {"active": 0, "waiting": 0, "limit": 2}
    assert live["since_start"]["counts"].get("client_gone", 0) == 1


def test_the_gate_hands_slots_out_in_arrival_order():
    """The gate on its own: tickets take slots in the order they asked, `ahead` counts the
    queue in front, a ticket released before its turn leaves no hole, and `slot()` is the
    same wait in one piece. A gate with no limit holds nobody."""
    from nanomuse_cloud.api import UpstreamGate

    async def run():
        gate = UpstreamGate(1)
        a, b, c = gate.ticket(), gate.ticket(), gate.ticket()
        assert await a.acquire(0.01) is True and gate.active == 1
        assert await b.acquire(0.01) is False and await c.acquire(0.01) is False
        assert (b.ahead, c.ahead, gate.waiting) == (0, 1, 2)
        b.release()  # gives up its place
        assert (c.ahead, gate.waiting) == (0, 1)
        a.release()  # the slot goes to c, not to anyone new
        d = gate.ticket()
        assert await d.acquire(0.01) is False and await c.acquire(0.01) is True
        assert gate.active == 1 and d.ahead == 0
        c.release()
        assert await d.acquire(None) is True
        d.release()
        assert gate.snapshot() == {"active": 0, "waiting": 0, "limit": 1}
        async with gate.slot():
            assert gate.active == 1
        assert gate.active == 0
        # a ticket granted after its holder stopped waiting hands the slot on when released
        e, f = gate.ticket(), gate.ticket()
        assert await e.acquire(None) is True and await f.acquire(0.01) is False
        e.release()  # f's future is granted now, though f is not awaiting
        assert gate.active == 1 and f.held is False
        f.release()
        assert gate.active == 0 and gate.waiting == 0
        free = UpstreamGate(0)
        assert await free.ticket().acquire(0.01) is True and free.waiting == 0

    asyncio.run(run())


async def test_the_analytics_pages_answer_from_the_rows(stack):
    app, client, sender, up, cloud = stack
    phone, aid = await sign_up(client, sender)
    desk, _ = await sign_up(client, sender, "someone@example.com", ua="deepseek-harness/1.2.0")
    script, _ = await sign_up(client, sender, "13900139000", ua="python-requests/2.32")
    # the script's calls are answered here so the pages have non-app rows to show; with the
    # switch on (the default) they would be refused (test_controls)
    cloud.controls.set("apps_only", False, actor="tests")
    tools = [{"type": "function", "function": {"name": "phone_tap"}}]
    for h, extra in ((phone, {"tools": tools}), (phone, {}), (desk, {"stream": True}), (script, {}), (script, {})):
        r = await client.post(
            "/v1/chat/completions", headers=h, json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}], **extra}
        )
        assert r.status_code == 200
    r = await client.post(
        "/v1/chat/completions", headers=phone, json={"model": "qwen3.8-flash", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 200

    usage = (await client.get("/v1/admin/analytics/usage?days=7", headers=ADMIN)).json()
    assert usage["days"] == 7 and len(usage["rows"]) == 7
    today = usage["rows"][-1]
    assert today["requests"] == 6 and set(today["models"]) == {"qwen3.8-27b", "qwen3.8-flash"}
    assert today["models"]["qwen3.8-27b"]["requests"] == 5 and today["models"]["qwen3.8-27b"]["accounts"] == 3
    assert {m["model"] for m in usage["models"]} == {"qwen3.8-27b", "qwen3.8-flash"}
    assert usage["totals"]["requests"] == 6 and usage["totals"]["cost_cny"] > 0

    day = (await client.get("/v1/admin/analytics/day", headers=ADMIN)).json()
    assert (
        day["calls"]["calls"] == 6
        and day["calls"]["by_status"] == {"ok": 6}
        and day["calls"]["hands"] == 1
        and day["calls"]["with_tools"] == 1
    )
    assert day["calls"]["p50_total_ms"] >= day["calls"]["p50_ttft_ms"] >= 0
    assert {p["platform"]: p["requests"] for p in day["platforms"]} == {"ios": 3, "desktop": 1, "other": 2}
    assert {p["platform"]: p["accounts"] for p in day["platforms"]} == {"ios": 1, "desktop": 1, "other": 1}
    assert len(day["hours"]) == 24 and sum(m["requests"] for h in day["hours"] for m in h["models"].values()) == 6
    assert sum(h["requests"] for h in day["hours"]) == 6 and len(day["latency"]) == 24 and sum(x["n"] for x in day["latency"]) == 6
    assert day["top_accounts"][0]["requests"] >= 2 and "identifier" in day["top_accounts"][0] and "hint" in day["top_accounts"][0]
    assert day["by_model_status"] == {"qwen3.8-27b": {"ok": 5}, "qwen3.8-flash": {"ok": 1}}
    assert day["errors"] == [] and day["content_rejected"] == []
    assert (await client.get("/v1/admin/analytics/day?day=1", headers=ADMIN)).json()["calls"]["calls"] == 0

    platforms = (await client.get("/v1/admin/analytics/platforms?days=7", headers=ADMIN)).json()
    by = {p["platform"]: p for p in platforms["platforms"]}
    assert by["ios"]["requests"] == 3 and by["desktop"]["requests"] == 1 and by["other"]["requests"] == 2
    assert by["ios"]["app"] is True and by["other"]["app"] is False
    assert by["ios"]["accounts"] == 1 and by["ios"]["calls"]["n"] == 3 and by["ios"]["calls"]["ok_share"] == 1.0
    assert by["ios"]["calls"]["hands_share"] == pytest.approx(1 / 3) and by["desktop"]["calls"]["stream_share"] == 1.0
    assert by["ios"]["versions"] == [{"version": "1.0.6", "requests": 3}]
    assert platforms["accounts_with_requests"] == 3 and platforms["multi_platform_accounts"] == 0
    assert {c["platforms"] for c in platforms["combinations"]} == {"ios", "desktop", "other"}
    assert platforms["accounts_by_last_client"] and platforms["own_models"] == [] and platforms["known_platforms"][0] == "android"

    hands = (await client.get("/v1/admin/analytics/hands?days=7", headers=ADMIN)).json()
    assert hands["summary"]["calls"] == 6 and hands["summary"]["hands"] == 1 and hands["summary"]["hands_accounts"] == 1
    assert hands["tools"] == [{"tool": "phone_tap", "calls": 1, "hands": True, "platforms": {"ios": 1}}]
    assert hands["days_series"][-1]["hands"] == 1 and hands["days_series"][-1]["platforms"]["ios"] == 1
    assert hands["platforms"][0]["platform"] == "ios" and hands["platforms"][0]["hands"] == 1
    assert hands["accounts"][0]["account_id"] == aid and hands["accounts"][0]["turns"] == 1 and "hint" in hands["accounts"][0]

    cohorts = (await client.get("/v1/admin/analytics/cohorts?days=14", headers=ADMIN)).json()
    assert cohorts["pool"]["limited"] == 3 and sum(b["accounts"] for b in cohorts["pool"]["buckets"]) == 3
    assert cohorts["pool"]["never_used"] == 0 and cohorts["pool"]["spent_cny"] > 0
    assert cohorts["exhaustion"]["accounts"] == 0 and cohorts["exhaustion"]["median_days"] is None
    assert cohorts["after_exhaustion"]["total"] == 0
    assert cohorts["own_key"] == {
        "window_days": 14,
        "own_key_likely": 0,
        "both": 0,
        "cloud_only": 3,
        "app_open_no_model": 0,
        "synced_any": 0,
        "accounts": [],
    }
    assert len(cohorts["retention"]) == 1 and cohorts["retention"][0]["signups"] == 3 and cohorts["retention"][0]["chat"][0] == 3
    assert cohorts["retention"][0]["chat"][1] is None  # a week that has not started yet

    abuse = (await client.get("/v1/admin/analytics/abuse?days=7", headers=ADMIN)).json()
    fam = {f["family"]: f for f in abuse["families"]}
    assert fam["python-requests"]["requests"] == 2 and fam["python-requests"]["app"] is False and fam["nanoMuse"]["app"] is True
    assert fam["deepseek-harness"]["platform"] == "desktop" and fam["nanoMuse"]["accounts"] == 1
    assert abuse["summary"]["non_app_requests"] == 2 and abuse["summary"]["non_app_accounts"] == 1 and abuse["summary"]["requests"] == 6
    assert (
        abuse["suspects"][0]["family"] == "python-requests"
        and abuse["suspects"][0]["requests"] == 2
        and "identifier" in abuse["suspects"][0]
    )
    assert len(abuse["suspects"]) == 1 and abuse["shared_addresses"] == [] and "places" in abuse
    assert {s["family"] for s in abuse["sign_ins"]} == {"nanoMuse", "deepseek-harness", "python-requests"}

    # the clamps
    assert (await client.get("/v1/admin/analytics/usage?days=9999", headers=ADMIN)).json()["days"] == 365
    assert (await client.get("/v1/admin/analytics/usage?days=0", headers=ADMIN)).json()["days"] == 1
    for path in ("usage", "day", "platforms", "cohorts", "hands", "quality", "abuse"):
        assert (await client.get(f"/v1/admin/analytics/{path}")).status_code == 401


async def test_the_usage_page_says_how_much_of_the_prompts_the_cache_served(stack):
    """0.31: the cache is the difference between a prompt billed whole and one billed at a
    fifth, and between four seconds to the first token and one. The Usage page says how many
    prompt tokens the provider served from its cache, per day, per model and in all (from the
    ledger, which has the figure back to the first version that billed it), each call's row
    carries its own (`calls.cached_tokens`), and the turns people ran on keys of their own
    (POST /v1/turns) are counted by provider and model under `own_keys`."""
    app, client, sender, up, cloud = stack
    headers, aid = await sign_up(client, sender)
    plain = {"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    # a cold call, then two with 80 of the 100 prompt tokens from the cache (one streamed: 40 → 30)
    assert (await client.post("/v1/chat/completions", headers=headers, json=plain)).status_code == 200
    up.state.cached_tokens = 80
    assert (await client.post("/v1/chat/completions", headers=headers, json=plain)).status_code == 200
    up.state.cached_tokens = 30
    assert (await client.post("/v1/chat/completions", headers=headers, json={**plain, "stream": True})).status_code == 200
    got = rows(cloud)
    assert [(r["prompt_tokens"], r["cached_tokens"]) for r in got] == [(100, 0), (100, 80), (40, 30)]

    usage = (await client.get("/v1/admin/analytics/usage?days=7", headers=ADMIN)).json()
    today = usage["rows"][-1]
    assert (today["prompt_tokens"], today["cached_tokens"]) == (240, 110)
    assert today["models"]["qwen3.8-27b"]["cached_tokens"] == 110
    assert usage["totals"]["cached_tokens"] == 110 and usage["models"][0]["cached_tokens"] == 110
    assert usage["own_keys"] == []

    # a turn run on the person's own OpenAI key, sent up afterwards with its usage; one on a
    # key whose client did not say how much was cached counts 0 cached, not nothing
    for i, (provider, model, u) in enumerate(
        (
            ("openai", "gpt-5.6", {"prompt_tokens": 2_000, "completion_tokens": 40, "cached_tokens": 1_500}),
            ("openai", "gpt-5.6", {"prompt_tokens": 1_000, "completion_tokens": 10, "cached_tokens": 5_000}),  # clamped
            ("anthropic", "claude-5", {"prompt_tokens": 300, "completion_tokens": 20}),
        )
    ):
        turn = {
            "id": f"t-{i}",
            "model": model,
            "provider": provider,
            "messages": [{"role": "user", "content": "hi"}],
            "response": {"message": {"role": "assistant", "content": "hello"}, "usage": u},
        }
        assert (await client.post("/v1/turns", headers=headers, json=turn)).status_code == 201
    usage = (await client.get("/v1/admin/analytics/usage?days=7", headers=ADMIN)).json()
    assert usage["totals"]["cached_tokens"] == 110  # the hosted figures are the relay's own calls only
    own = {(o["provider"], o["model"]): o for o in usage["own_keys"]}
    assert set(own) == {("openai", "gpt-5.6"), ("anthropic", "claude-5")}
    assert own[("openai", "gpt-5.6")]["turns"] == 2 and own[("openai", "gpt-5.6")]["accounts"] == 1
    assert (own[("openai", "gpt-5.6")]["prompt_tokens"], own[("openai", "gpt-5.6")]["cached_tokens"]) == (3_000, 2_500)
    assert (own[("anthropic", "claude-5")]["prompt_tokens"], own[("anthropic", "claude-5")]["cached_tokens"]) == (300, 0)
    # the relay's own turns in the record carry the figure too (written off the loop)
    while app.state.record_tasks:
        await asyncio.gather(*list(app.state.record_tasks))
    turns = cloud.db._conn.execute("SELECT source, prompt_tokens, cached_tokens FROM turns ORDER BY ts, rowid").fetchall()
    assert sorted((r[0], r[1], r[2]) for r in turns) == sorted(
        [("cloud", 100, 0), ("cloud", 100, 80), ("cloud", 40, 30), ("own", 2_000, 1_500), ("own", 1_000, 1_000), ("own", 300, 0)]
    )
    # 0.31.1: the table is read from the own turns' figures rows (own_figures), one small row
    # per own turn written with it, never from the turns' bodies; an own turn sent up again
    # under the same id replaces its row rather than adding one
    assert cloud.db.own_figures_count() == 3
    assert (await client.post("/v1/turns", headers=headers, json=turn)).status_code == 201
    assert cloud.db.own_figures_count() == 3
    # the own turns kept before 0.31.1 have no figures row: the backfill writes them a page
    # at a time, oldest first, and the table counts them as they come (the steps run here
    # without a wait between them, so the loop's own step cannot come in between)
    analytics = app.state.analytics
    with cloud.db.tx() as c:
        c.execute("DELETE FROM own_figures")
    cloud.db.settings_put("own_figures.cursor", [0, 0])
    analytics.figures_done = False
    assert cloud.db.own_usage_by_provider(0) == []
    assert analytics.own_figures_step(2) == 2 and cloud.db.own_figures_count() == 2 and analytics.figures_done is False
    assert analytics.own_figures_step(2) == 1 and cloud.db.own_figures_count() == 3 and analytics.figures_done is True
    assert analytics.own_figures_step(2) == 0
    usage = (await client.get("/v1/admin/analytics/usage?days=7", headers=ADMIN)).json()
    assert {(o["provider"], o["model"]): (o["turns"], o["prompt_tokens"], o["cached_tokens"]) for o in usage["own_keys"]} == {
        ("openai", "gpt-5.6"): (2, 3_000, 2_500),
        ("anthropic", "claude-5"): (1, 300, 0),
    }
    assert usage["own_keys_pending"] is False
    # Data controls' delete takes the figures rows with the turns
    assert (await client.delete("/v1/me/samples", headers=headers)).status_code == 200
    assert cloud.db.own_figures_count() == 0
    assert (await client.get("/v1/admin/analytics/usage?days=7", headers=ADMIN)).json()["own_keys"] == []


async def test_kept_turns_get_a_shape_row_and_older_ones_are_backfilled(stack):
    app, client, sender, up, cloud = stack
    headers, aid = await sign_up(client, sender)
    assert (await client.post("/v1/me/contribute", headers=headers, json={"on": True})).status_code == 200
    # three turns kept before 0.28 have no shape row: written straight into `samples`
    for text in ("hi", "Plan my week around two deadlines and a trip", "Plan my week around two deadlines and a trip"):
        cloud.db.add_sample(
            aid, "qwen3.8-27b", json.dumps([{"role": "user", "content": text}]), "Here is a plan " * 5, 10, 20, json.dumps({"ua": PHONE_UA})
        )
    assert cloud.db.sample_count() == 3 and cloud.db.sample_stats_count() == 0
    # a turn kept now carries its row at once
    r = await client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "What is the capital of Peru"}]},
    )
    assert r.status_code == 200
    assert cloud.db.sample_count() == 4 and cloud.db.sample_stats_count() == 1

    analytics = app.state.analytics
    quality = analytics.quality(7)
    assert quality["coverage"] == {"samples": 4, "described": 1, "backfill_done": False, "share": 0.25}
    # the backfill walks newest first, in pages, and remembers where it was; a turn that has
    # its row already is left as it is
    assert analytics.backfill_step(2) == 2 and cloud.db.sample_stats_count() == 2
    assert cloud.db.settings_get("sample_stats.cursor")[0] != [-1, -1]
    assert analytics.backfill_step(2) == 2 and cloud.db.sample_stats_count() == 4 and analytics.backfill_done is False
    assert analytics.backfill_step(2) == 0 and analytics.backfill_done is True
    assert cloud.db.settings_get("sample_stats.cursor")[0] == [-1, -1]
    # a fresh Analytics (a restart) sees the finished cursor and reads nothing
    fresh = an.Analytics(cloud, an.LiveMeter(), lambda: None, lambda: {"active": 0, "waiting": 0, "limit": 1})
    assert fresh.backfill_step(2) == 0 and fresh.backfill_done is True

    quality = (await client.get("/v1/admin/analytics/quality?days=7", headers=ADMIN)).json()
    assert quality["coverage"]["backfill_done"] is True and quality["coverage"]["share"] == 1.0
    assert quality["period"]["turns"] == 4 and quality["period"]["accounts"] == 1 and quality["period"]["trivial"] == 1
    assert quality["period"]["repeated_turns"] == 0  # a message twice is not yet a repeat (three is)
    assert quality["all_time"]["turns"] == 4 and quality["series"][-1]["turns"] == 4
    assert sum(t["accounts"] for t in quality["tiers"]) == 1
    acc = quality["top_accounts"][0]
    assert (
        acc["turns"] == 4 and acc["trivial"] == 1 and acc["repeat_share"] == 0.25 and acc["platform"] == "ios" and acc["contribute"] is True
    )
    assert acc["tier"] in ("medium", "low") and "identifier" in acc and "hint" in acc
    assert quality["by_platform"][0]["platform"] == "ios" and quality["by_platform"][0]["turns"] == 4
    assert not any(word in json.dumps(quality) for word in ("Peru", "deadlines", "plan"))
    # the person turning the switch off and deleting their turns takes the rows along
    r = await client.delete("/v1/me/samples", headers=headers)
    assert r.status_code in (200, 204), r.text
    assert cloud.db.sample_count() == 0 and cloud.db.sample_stats_count() == 0
    # a turn whose shape row never got written (the second write failed) is not lost to the
    # figures: the daily pass finds it by its missing row, and finds nothing the next day
    cloud.db.add_sample(aid, "qwen3.8-27b", json.dumps([{"role": "user", "content": "Draft the invoice mail"}]), "Sure", 5, 5, "{}")
    assert cloud.db.sample_count() == 1 and cloud.db.sample_stats_count() == 0
    assert fresh.describe_missing() == 1 and cloud.db.sample_stats_count() == 1
    assert fresh.describe_missing() == 0
    # the pass looks a few days back only (older turns are the paged backfill's): a turn
    # without its row from before the window is left alone, so the walk stays short
    cloud.db.add_sample(aid, "qwen3.8-27b", json.dumps([{"role": "user", "content": "An old one"}]), "Yes", 5, 5, "{}")
    with cloud.db.tx() as c:
        c.execute(
            "UPDATE samples SET ts=? WHERE id NOT IN (SELECT sample_id FROM sample_stats)", (int(time.time()) - fresh.REPAIR_WINDOW_S - 60,)
        )
    assert cloud.db.sample_count() == 2 and fresh.describe_missing() == 0


async def test_the_analytics_loop_warms_the_meter_sweeps_old_calls_and_backfills():
    """The lifespan task: on start the last hour's rows come back into the meter, the
    backfill runs to the end, and rows older than CALLS_KEEP_DAYS go."""
    up = fake_upstream()
    settings = make_settings(calls_keep_days=1, events_keep_days=1)
    sender = LogSender()
    cloud = Cloud(settings, Database(":memory:"), sender)
    aid = cloud.db.create_account("hash", "phone", "138****8000", 0, account_id="a")["id"]
    now = int(time.time())
    # the timelines' lines age out the same way; the trace of a deletion does not
    with cloud.db.tx() as c:
        c.execute("INSERT INTO events(account_id, ts, kind, detail) VALUES (?,?,?,?)", (aid, now - 3 * 86400, "sign_in.code", "pixel"))
        c.execute("INSERT INTO events(account_id, ts, kind, detail) VALUES (?,?,?,?)", ("", now - 3 * 86400, "account.deleted", "x"))
        c.execute("INSERT INTO events(account_id, ts, kind, detail) VALUES (?,?,?,?)", (aid, now - 120, "sign_in.code", "mac"))
    base = {
        "account_id": aid,
        "model": "m",
        "platform": "ios",
        "family": "nanoMuse",
        "status": "ok",
        "detail": "",
        "stream": 1,
        "wait_ms": 0,
        "ttft_ms": 1,
        "total_ms": 2,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "messages": 1,
        "images": 0,
        "tools": 0,
        "tool_names": "",
        "hands": 0,
        "retries": 0,
        "request_id": "",
    }
    cloud.db.add_call({**base, "ts": now - 120})
    cloud.db.add_call({**base, "ts": now - 3 * 86400})
    cloud.db.add_sample(aid, "m", json.dumps([{"role": "user", "content": "an old kept turn"}]), "r", 1, 1, "{}")
    app = create_app(settings, cloud, upstream_transport=httpx.ASGITransport(app=up))
    with TestClient(app):
        meter = app.state.meter
        deadline = time.time() + 5

        # the events sweep follows the calls sweep in the same tick: wait for both (a slow runner
        # can be between the two when the calls are already gone)
        def events_left() -> int:
            return int(cloud.db._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

        while time.time() < deadline and (not app.state.analytics.backfill_done or cloud.db.calls_count() > 1 or events_left() > 2):
            time.sleep(0.05)
        assert meter.summary(now - 3600)["requests"] == 1  # the recent row, back in the meter
        assert app.state.analytics.backfill_done is True and cloud.db.sample_stats_count() == 1
        assert cloud.db.calls_count() == 1  # the three-day-old row is gone
        kinds = sorted(str(r["kind"]) for r in cloud.db._conn.execute("SELECT kind FROM events").fetchall())
        assert kinds == ["account.deleted", "sign_in.code"]


# -- 0.30: the long reads run on a connection of their own ---------------------------------------


def test_the_reader_sees_committed_rows_and_refuses_to_write(tmp_path):
    """A file database hands the pages a second, read-only connection: it reads what the
    first committed, a write through it fails, and an in-memory database (one connection)
    hands back itself."""
    db = Database(str(tmp_path / "relay.sqlite"))
    reader = db.reader()
    assert reader is not db and reader.read_only is True and db.reader() is reader
    aid = db.create_account("hash", "phone", "138****8000", 0, account_id="a")["id"]
    assert reader.account(aid) is not None and reader.account_counts()["total"] == 1
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        reader.add_event(aid, "sign_in.code", "x")
    assert Database(":memory:").reader() is not None
    mem = Database(":memory:")
    assert mem.reader() is mem
    db.optimize()  # the planner's statistics: a no-op on a small file, never an error


def test_the_pages_read_through_the_read_only_service(tmp_path):
    """`Cloud.reads` is the service over the reader: the pages it serves see every committed
    row and leave the relay's own connection alone; writing through it fails."""
    settings = replace(make_settings(), database=str(tmp_path / "relay.sqlite"))
    cloud = Cloud(settings, Database(settings.database), LogSender())
    aid = cloud.db.create_account("hash", "phone", "138****8000", 0, account_id="a")["id"]
    reads = cloud.reads
    assert reads.db is cloud.db.reader() and reads.db is not cloud.db and reads.s is cloud.s
    assert reads.admin_overview(7)["accounts"]["total"] == 1
    assert reads.admin_data(7)["accounts"]["total"] == 1
    assert reads.admin_invites()["funnel"]["invited"] == 0
    assert reads.admin_account(aid, 7)["account"]["id"] == aid
    assert [m["id"] for m in reads.admin_turns()] == []
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        reads.note(aid, "sign_in.code", "x")
    # a setting the operator changes is the one the next view reads (a fresh copy each time)
    cloud.admin_update_settings({"allowance_cny": 12.5}, actor="test")
    assert cloud.reads.s.allowance_cny == 12.5


async def test_the_data_view_sums_tokens_from_the_shape_rows_and_fills_older_ones_in(stack):
    """The Data view's sums come from `sample_stats`, never from the conversation rows; a
    shape row written before 0.30 has no tokens (-1) until the tokens backfill copies them
    from the turn, a page at a time, remembering where it was."""
    app, client, sender, up, cloud = stack
    headers, aid = await sign_up(client, sender)
    assert (await client.post("/v1/me/contribute", headers=headers, json={"on": True})).status_code == 200
    # two turns kept before 0.30: a shape row each, without tokens
    for text in ("Plan my week around two deadlines", "Draft the invoice mail"):
        sid = cloud.db.add_sample(aid, "qwen3.8-27b", json.dumps([{"role": "user", "content": text}]), "Sure " * 10, 100, 50, "{}")
        cloud.db.add_sample_stats([an.sample_shape(sid, aid, int(time.time()), "qwen3.8-27b", "[]", "", "{}")])
    assert cloud.db.sample_stats_without_tokens() == 2
    # a turn kept now carries its tokens at once
    r = await client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "What is the capital of Peru"}]},
    )
    assert r.status_code == 200
    view = cloud.reads.admin_data(7)
    assert view["tokens_pending"] == 2 and view["totals"]["samples"] == 3
    fresh_tokens = view["totals"]["prompt_tokens"] + view["totals"]["completion_tokens"]
    assert fresh_tokens > 0  # the new turn's only; the two older rows count as nothing yet
    analytics = app.state.analytics
    assert analytics.tokens_step(2) == 2 and cloud.db.sample_stats_without_tokens() == 1
    assert cloud.db.settings_get("sample_stats.tokens_cursor")[0] != [-1, -1]
    assert analytics.tokens_step(2) == 1 and analytics.tokens_done is True
    assert cloud.db.sample_stats_without_tokens() == 0
    view = cloud.reads.admin_data(7)
    assert view["tokens_pending"] == 0
    assert view["totals"]["prompt_tokens"] + view["totals"]["completion_tokens"] == fresh_tokens + 2 * 150
    assert view["by_account"][0]["prompt_tokens"] == 200 + view["recent"][0]["prompt_tokens"]
    assert {p["platform"]: p["samples"] for p in view["by_platform"]} == {"other": 2, "ios": 1}  # the two synthetic rows carry no UA
    # a fresh Analytics (a restart) sees the finished cursor and reads nothing
    fresh = an.Analytics(cloud, an.LiveMeter(), lambda: None, lambda: {"active": 0, "waiting": 0, "limit": 1})
    assert fresh.tokens_step(2) == 0 and fresh.tokens_done is True
    # the export runs in a thread over a temporary file, whole and with its length
    r = await client.get("/v1/admin/samples/export?since=0", headers=ADMIN)
    assert r.status_code == 200 and r.headers["content-length"] == str(len(r.content))
    lines = [json.loads(line) for line in r.text.splitlines()]
    assert len(lines) == 3 and all("account_id" not in line for line in lines)


# -- the hub: a device may say which model it runs on --------------------------------------------


def test_a_device_reports_its_own_model_by_ids_only():
    settings = Settings(database=":memory:", secret="test-secret", admin_token="admin", public_base="http://cloud.test")
    sender = LogSender()
    cloud = Cloud(settings, Database(":memory:"), sender)
    app = create_app(settings, cloud)
    with TestClient(app) as c:
        assert c.post("/v1/auth/code", json={"identifier": "13800138000"}).status_code == 204
        _, code = sender.sent[-1]
        key = c.post("/v1/auth/verify", json={"identifier": "13800138000", "code": code, "device": "test"}).json()["api_key"]

        def say_hello(llm):
            with c.websocket_connect("/v1/hub", headers={"Authorization": f"Bearer {key}"}) as ws:
                device = {
                    "id": "pc-1",
                    "name": "desk",
                    "kind": "computer",
                    "os": "macOS",
                    "version": "1.0.6",
                    "actions": ["info", "screen"],
                }
                if llm is not None:
                    device["llm"] = llm
                ws.send_json({"type": "hello", "device": device})
                assert ws.receive_json()["type"] == "welcome"

        say_hello({"provider": "openrouter", "model": "anthropic/claude-sonnet-4.5"})
        rows = [dict(r) for r in cloud.db.devices_detail()]
        assert rows[0]["llm_provider"] == "openrouter" and rows[0]["llm_model"] == "anthropic/claude-sonnet-4.5"
        # a hello without the field keeps what was reported; a bad value is dropped, a key never lands
        say_hello(None)
        rows = [dict(r) for r in cloud.db.devices_detail()]
        assert rows[0]["llm_provider"] == "openrouter"
        say_hello({"provider": "sk-live-abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", "model": "https://x"})
        rows = [dict(r) for r in cloud.db.devices_detail()]
        assert rows[0]["llm_provider"] == "openrouter" and rows[0]["llm_model"] == "anthropic/claude-sonnet-4.5"
        say_hello({"provider": "cloud", "model": "Qwen/Qwen3.6-27B-FP8"})
        rows = [dict(r) for r in cloud.db.devices_detail()]
        assert (rows[0]["llm_provider"], rows[0]["llm_model"]) == ("cloud", "Qwen/Qwen3.6-27B-FP8")
        platforms = c.get("/v1/admin/analytics/platforms?days=7", headers=ADMIN).json()
        assert platforms["own_models"] == [
            {"provider": "cloud", "devices": 1, "accounts": 1, "models": [{"model": "Qwen/Qwen3.6-27B-FP8", "devices": 1}]}
        ]


def test_platform_percentiles_from_sqlite_match_the_nearest_rank_helper():
    """The platform page's latencies are ranked in SQLite; they are the figures the Python
    helper gives, call for call, with the waits over every call and the rest over the calls
    that went well."""
    import random

    db = Database(":memory:")
    rng = random.Random(7)
    now = int(time.time())
    rows: dict[str, list[dict]] = {"ios": [], "desktop": []}
    for platform, n in (("ios", 37), ("desktop", 4)):
        for i in range(n):
            status = "ok" if rng.random() < 0.8 else rng.choice(["refused", "upstream_error"])
            row = {
                "ts": now - 60 - i,
                "account_id": "a",
                "model": "m",
                "platform": platform,
                "family": "app",
                "status": status,
                "wait_ms": rng.randint(0, 900),
                "ttft_ms": rng.randint(100, 9000),
                "total_ms": rng.randint(1000, 60000),
            }
            rows[platform].append(row)
            db.add_call(row)
    got = {str(r["platform"]): dict(r) for r in db.calls_latency_by_platform(now - 3600, now + 1)}
    counts = {str(r["platform"]): dict(r) for r in db.calls_by_platform(now - 3600, now + 1)}
    for platform, calls in rows.items():
        ok = [c for c in calls if c["status"] == "ok"]
        assert got[platform]["p95_wait_ms"] == an.percentile([c["wait_ms"] for c in calls], 0.95)
        assert got[platform]["p50_ttft_ms"] == an.percentile([c["ttft_ms"] for c in ok], 0.5)
        assert got[platform]["p95_ttft_ms"] == an.percentile([c["ttft_ms"] for c in ok], 0.95)
        assert got[platform]["p50_total_ms"] == an.percentile([c["total_ms"] for c in ok], 0.5)
        assert counts[platform]["n"] == len(calls) and counts[platform]["ok"] == len(ok)
        assert counts[platform]["errors"] == sum(1 for c in calls if c["status"] == "upstream_error")
        assert counts[platform]["refused"] == sum(1 for c in calls if c["status"] == "refused")
