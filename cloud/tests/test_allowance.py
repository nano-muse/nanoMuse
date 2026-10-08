"""How the allowance is counted: the price table against the provider's, cached input
tokens, DeepSeek's idle hours, the estimate when a provider sends no usage, pictures sent
in, clips by resolution, the boundary under concurrent requests, and what /v1/me shows.
In-memory SQLite, a fake provider, no network."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from conftest import BUSY_HOUR
from fastapi import Request
from fastapi.responses import StreamingResponse
from test_cloud import PNG_1PX, fake_upstream, sign_up

from nanomuse_cloud.api import create_app
from nanomuse_cloud.config import DEFAULT_MODELS, ModelSpec, Settings
from nanomuse_cloud.db import Database
from nanomuse_cloud.senders import LogSender
from nanomuse_cloud.service import Cloud, Usage, estimate_tokens, usage_from_json

ADMIN = {"X-Admin-Token": "admin"}
# 2026-10-07T15:00:00Z is 23:00 in Beijing: inside DeepSeek's idle hours (22:00 to 8:00)
IDLE_HOUR = 1791385200
CHAT_PATH = "/compat/v1/chat/completions"
M = 1_000_000


def make(**overrides):
    up = fake_upstream()
    kw = dict(
        database=":memory:",
        secret="test-secret",
        admin_token="admin",
        upstream_base="http://upstream/compat/v1",
        upstream_key="sk-upstream",
        dashscope_base="http://upstream/ds/api/v1",
        signup_tokens=0,
        daily_cap_tokens=0,
        per_minute_requests=100,
        allowance_cny=10,
        public_base="http://cloud.test",
    )
    kw.update(overrides)
    settings = Settings(**kw)
    sender = LogSender()
    cloud = Cloud(settings, Database(":memory:"), sender)
    app = create_app(settings, cloud, upstream_transport=httpx.ASGITransport(app=up))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cloud.test")
    return app, client, sender, up, cloud


def replace_chat(up, handler) -> None:
    """The fake provider answers chat with `handler` instead of its usual reply."""
    up.router.routes[:] = [rt for rt in up.router.routes if getattr(rt, "path", "") != CHAT_PATH]
    up.add_api_route(CHAT_PATH, handler, methods=["POST"])


def by_id(model_id: str) -> ModelSpec:
    return next(m for m in DEFAULT_MODELS if m.id == model_id)


def test_price_table_is_the_providers():
    """The shipped menu carries Model Studio's Beijing list prices as read on 2026-10-07
    (help.aliyun.com/zh/model-studio/model-pricing and /context-cache). A change here is a
    deliberate one, made against the provider's page."""
    ds = by_id("deepseek-v4.1-flash")
    assert (ds.price_in, ds.price_out) == (2.0, 8.0)
    assert (ds.price_in_idle, ds.price_out_idle, ds.idle_hours) == (1.0, 4.0, (22, 8))
    assert ds.cached_in_rate == 0.1
    q27 = by_id("qwen3.8-27b")
    assert (q27.price_in, q27.price_out, q27.cached_in_rate) == (3.0, 12.0, 0.2)
    assert (q27.price_in_idle, q27.price_out_idle) == (0.0, 0.0)  # priced the same all day
    flash = by_id("qwen3.8-flash")
    assert (flash.price_in, flash.price_out, flash.cached_in_rate) == (0.8, 2.7, 0.2)
    img = by_id("qwen-image-3.0")
    assert (img.price_image, img.price_image_2k, img.price_image_in) == (0.18, 0.18, 0.02)
    i2v = by_id("wan2.2-i2v-flash")
    assert i2v.price_second == 0.10 and dict(i2v.price_second_res) == {"720P": 0.20, "1080P": 0.48}
    t2v = by_id("wan2.2-t2v-plus")
    assert t2v.price_second == 0.14 and dict(t2v.price_second_res) == {"1080P": 0.70}
    # the public shape carries every figure, so a client can show the price it pays
    pub = ds.to_public()["nanomuse"]["price_cny"]
    assert pub["per_m_input"] == 2.0 and pub["per_m_input_idle"] == 1.0 and pub["idle_hours"] == [22, 8]
    assert pub["per_m_cached_input"] == 0.2
    assert by_id("wan2.2-i2v-flash").to_public()["nanomuse"]["price_cny"]["per_second_res"] == {"720P": 0.20, "1080P": 0.48}


def test_chat_cost_cached_tokens_and_idle_hours():
    """One yuan per million tokens is one micro-yuan a token. A cached prompt token costs its
    share of a fresh one; in the idle hours the idle prices apply to both ends; the
    reservation (no time given) is at the day price; nothing goes below zero."""
    ds = by_id("deepseek-v4.1-flash")
    assert ds.chat_cost_uy(M, 0) == 2 * M and ds.chat_cost_uy(0, M) == 8 * M
    assert ds.chat_cost_uy(M, 0, cached_tokens=M) == round(0.2 * M)  # all of it from the cache: 10 %
    assert ds.chat_cost_uy(M, 0, cached_tokens=M // 2) == round(1.1 * M)
    assert ds.chat_cost_uy(M, 0, cached_tokens=5 * M) == round(0.2 * M)  # more cached than prompt: clamped
    assert ds.chat_cost_uy(M, M, at=BUSY_HOUR) == 10 * M
    assert ds.chat_cost_uy(M, M, at=IDLE_HOUR) == 5 * M
    assert ds.chat_cost_uy(M, M, cached_tokens=M, at=IDLE_HOUR) == round(0.1 * M + 4 * M)
    assert ds.chat_cost_uy(-5, -5) == 0 and ds.chat_cost_uy(0, 0, cached_tokens=10) == 0
    # a model without idle prices costs the same at any hour, and a cache rate of 1 is no discount
    q27 = by_id("qwen3.8-27b")
    assert q27.chat_cost_uy(M, M, at=IDLE_HOUR) == q27.chat_cost_uy(M, M, at=BUSY_HOUR) == 15 * M
    plain = ModelSpec(id="p", name="P", upstream="p", price_in=2.0, price_out=8.0)
    assert plain.chat_cost_uy(M, 0, cached_tokens=M) == 2 * M and plain.idle_at(IDLE_HOUR) is False
    # the hour boundaries, in Beijing time: 22:00 starts the idle hours, 8:00 ends them
    beijing_midnight = 1791388800  # 2026-10-07T16:00:00Z = 2026-10-08T00:00:00+08:00
    for hour, idle in ((21.999, False), (22, True), (23.5, True), (0, True), (7.999, True), (8, False), (14, False)):
        assert ds.idle_at(beijing_midnight + int(hour * 3600)) is idle, hour
    # a window that does not wrap, and no window at all
    day = ModelSpec(id="d", name="D", upstream="d", price_in=2.0, price_in_idle=1.0, idle_hours=(1, 5))
    assert day.idle_at(beijing_midnight + 3600) is True and day.idle_at(beijing_midnight + 5 * 3600) is False
    none = ModelSpec(id="n", name="N", upstream="n", price_in=2.0, price_in_idle=1.0, idle_hours=(3, 3))
    assert none.idle_at(beijing_midnight + 3 * 3600) is False
    # what CLOUD_MODELS may say: a list for the hours, an object for the prices by resolution
    spec = ModelSpec(
        id="v", name="V", upstream="v", kind="video", output_modalities=("video",), price_second=0.1, price_second_res={"720p": 0.2}
    )
    assert spec.price_second_res == (("720P", 0.2),) and spec.video_cost_uy(5, "720P") == 1 * M and spec.video_cost_uy(5) == round(0.5 * M)
    assert spec.video_cost_uy(5, "4K") == round(0.5 * M)  # an unknown tier: the base price
    for bad in (dict(idle_hours=(1,)), dict(idle_hours=(1, 25)), dict(cached_in_rate=1.5), dict(cached_in_rate=-0.1)):
        with pytest.raises(ValueError):
            ModelSpec(id="x", name="X", upstream="x", **bad)
    # pictures: the one drawn, and any sent in
    img = by_id("qwen-image-3.0")
    assert img.image_cost_uy("1024*1024") == 180_000 and img.image_cost_uy("1024*1024", inputs=1) == 200_000


def test_usage_from_json_shapes():
    """OpenAI's shape with the cached breakdown, DashScope's native names, the Anthropic
    shape that counts the cache beside the input, and the replies that say nothing usable."""
    u = usage_from_json({"usage": {"prompt_tokens": 1000, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 800}}})
    assert u == Usage(1000, 20, 800)
    assert usage_from_json({"usage": {"input_tokens": 30, "output_tokens": 4, "input_tokens_details": {"cached_tokens": 10}}}) == Usage(
        30, 4, 10
    )
    assert usage_from_json({"usage": {"input_tokens": 30, "output_tokens": 4, "cache_read_input_tokens": 1000}}) == Usage(1030, 4, 1000)
    assert usage_from_json(
        {"usage": {"prompt_tokens": 10, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 99}}}
    ) == Usage(10, 2, 10)
    assert usage_from_json({"usage": {"prompt_tokens": 10, "completion_tokens": 2, "prompt_tokens_details": None}}) == Usage(10, 2, 0)
    # nothing usable: the caller estimates instead of charging nothing
    assert usage_from_json({"usage": {}}) is None
    assert usage_from_json({"usage": {"prompt_tokens": 0, "completion_tokens": 0}}) is None
    assert usage_from_json({"usage": {"prompt_tokens": "many"}}) is None
    assert usage_from_json({"usage": None}) is None and usage_from_json({}) is None


async def test_cached_prompt_tokens_cost_their_cached_rate():
    """The provider served most of a long prompt from its cache (the agent's system prompt
    and history, turn after turn): the ledger counts those tokens at the cached rate, whole
    reply and stream alike, and the line says how many were cached."""
    app, client, sender, up, cloud = make()
    data = await sign_up(client, sender)
    auth = {"Authorization": f"Bearer {data['api_key']}"}

    async def cached(request: Request):
        body = await request.json()
        usage = {"prompt_tokens": 10_000, "completion_tokens": 100, "prompt_tokens_details": {"cached_tokens": 9_000}}
        if body.get("stream"):

            async def gen():
                yield f"data: {json.dumps({'choices': [{'index': 0, 'delta': {'content': 'ok'}}]})}\n\n"
                yield f"data: {json.dumps({'choices': [], 'usage': usage})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")
        return {"choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}], "usage": usage}

    replace_chat(up, cached)
    messages = [{"role": "user", "content": "hi"}]
    r = await client.post("/v1/chat/completions", headers=auth, json={"model": "deepseek-v4.1-flash", "messages": messages})
    assert r.status_code == 200
    # 1 000 fresh at ¥2/M + 9 000 cached at ¥0.2/M + 100 out at ¥8/M
    whole = 1_000 * 2 + 9_000 * 0.2 + 100 * 8
    me = (await client.get("/v1/me", headers=auth)).json()
    assert me["recent"][0]["cost_cny"] == round(whole / M, 4) and me["recent"][0]["detail"] == {"cached_tokens": 9_000}
    assert me["recent"][0]["prompt_tokens"] == 10_000 and me["recent"][0]["completion_tokens"] == 100
    assert me["spend"]["total"] == round(whole / M, 4)
    # the same turn with the cache ignored would have cost four and a half times as much
    assert whole * 4 < 10_000 * 2 + 100 * 8 < whole * 5

    r = await client.post("/v1/chat/completions", headers=auth, json={"model": "deepseek-v4.1-flash", "messages": messages, "stream": True})
    assert r.status_code == 200 and "[DONE]" in r.text
    me = (await client.get("/v1/me", headers=auth)).json()
    assert me["recent"][0]["cost_cny"] == round(whole / M, 4) and me["recent"][0]["detail"] == {"cached_tokens": 9_000}
    assert me["spend"]["total"] == round(2 * whole / M, 4)
    # the Qwen model's rate is 20 %
    r = await client.post("/v1/chat/completions", headers=auth, json={"model": "qwen3.8-27b", "messages": messages})
    assert r.status_code == 200
    me = (await client.get("/v1/me", headers=auth)).json()
    assert me["recent"][0]["cost_cny"] == round((1_000 * 3 + 9_000 * 0.6 + 100 * 12) / M, 4)


async def test_idle_hours_are_charged_at_the_idle_price():
    """A DeepSeek turn charged between 22:00 and 8:00 Beijing time costs half; the Qwen
    models cost the same at any hour; the ledger line says the idle price applied."""
    app, client, sender, up, cloud = make()
    data = await sign_up(client, sender)
    auth = {"Authorization": f"Bearer {data['api_key']}"}
    messages = [{"role": "user", "content": "hi"}]
    day = (100 * 2 + 50 * 8) / M  # the fake provider's 100 in / 50 out
    r = await client.post("/v1/chat/completions", headers=auth, json={"model": "deepseek-v4.1-flash", "messages": messages})
    assert r.status_code == 200
    me = (await client.get("/v1/me", headers=auth)).json()
    assert me["recent"][0]["cost_cny"] == round(day, 4) and "detail" not in me["recent"][0]

    cloud.clock = lambda: IDLE_HOUR
    r = await client.post("/v1/chat/completions", headers=auth, json={"model": "deepseek-v4.1-flash", "messages": messages})
    assert r.status_code == 200
    me = (await client.get("/v1/me", headers=auth)).json()
    assert me["recent"][0]["cost_cny"] == round(day / 2, 4) and me["recent"][0]["detail"] == {"idle": True}
    r = await client.post("/v1/chat/completions", headers=auth, json={"model": "qwen3.8-27b", "messages": messages})
    assert r.status_code == 200
    me = (await client.get("/v1/me", headers=auth)).json()
    assert me["recent"][0]["cost_cny"] == round((100 * 3 + 50 * 12) / M, 4) and "detail" not in me["recent"][0]
    assert me["spend"]["total"] == round(day + day / 2 + (100 * 3 + 50 * 12) / M, 4)
    # the reservation while a chat runs is at the day price whatever the hour
    assert cloud.chat_reserve_uy(cloud.s.model("deepseek-v4.1-flash")) == 6000 * 2 + 1500 * 8


async def test_no_usage_from_the_provider_is_estimated_the_same_way():
    """A provider that sends no usage: the reply's tokens are estimated from its text, the
    same rule for a whole reply and a stream (CJK at a token a character), never charged as
    zero; a `usage` object with nothing in it counts as none."""
    app, client, sender, up, cloud = make()
    data = await sign_up(client, sender)
    auth = {"Authorization": f"Bearer {data['api_key']}"}
    text = "你好，世界。" * 20

    async def silent(request: Request):
        body = await request.json()
        if body.get("stream"):

            async def gen():
                for i in range(0, len(text), 7):
                    yield f"data: {json.dumps({'choices': [{'index': 0, 'delta': {'content': text[i : i + 7]}}]}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'choices': [], 'usage': {}})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")
        return {"choices": [{"index": 0, "message": {"role": "assistant", "content": text}}]}

    replace_chat(up, silent)
    messages = [{"role": "user", "content": "说点什么"}]
    r = await client.post("/v1/chat/completions", headers=auth, json={"model": "qwen3.8-27b", "messages": messages})
    assert r.status_code == 200
    r = await client.post("/v1/chat/completions", headers=auth, json={"model": "qwen3.8-27b", "messages": messages, "stream": True})
    assert r.status_code == 200
    me = (await client.get("/v1/me", headers=auth)).json()
    stream, whole = me["recent"][0], me["recent"][1]
    assert whole["completion_tokens"] == estimate_tokens(text) == stream["completion_tokens"] > 0
    assert whole["prompt_tokens"] == stream["prompt_tokens"] > 0
    assert whole["cost_cny"] == stream["cost_cny"] > 0


async def test_an_edit_counts_the_picture_sent_in():
    """A picture drawn from words costs the output price; an edit costs that plus the
    picture sent in, and is refused up front when the two together do not fit (¥0.19 left:
    the picture out alone would have fitted, in and out do not)."""
    app, client, sender, up, cloud = make(allowance_cny=0.37)
    data = await sign_up(client, sender)
    auth = {"Authorization": f"Bearer {data['api_key']}"}
    r = await client.post("/v1/images/generations", headers=auth, json={"model": "qwen-image-3.0", "prompt": "a dragon"})
    assert r.status_code == 200
    me = (await client.get("/v1/me", headers=auth)).json()
    assert me["recent"][0]["cost_cny"] == 0.18 and me["spend"]["left"] == 0.19
    files = {"image": ("in.png", PNG_1PX, "image/png")}
    form = {"model": "qwen-image-3.0", "prompt": "make it blue"}
    r = await client.post("/v1/images/edits", headers=auth, data=form, files=files)
    assert r.status_code == 429 and r.json()["error"]["code"] == "allowance_exhausted"
    me = (await client.get("/v1/me", headers=auth)).json()
    assert me["spend"]["left"] == 0.19 and [r["requests"] for r in me["usage"]["total"]["by_kind"]] == [1]
    assert not [r for r in up.state.requests if r[0] == "image" and "blue" in json.dumps(r[2])]  # never sent upstream


async def test_an_edit_is_charged_in_and_out():
    """With room for both, the edit's ledger line is the picture out plus the picture in."""
    app, client, sender, up, cloud = make(allowance_cny=0.41)
    data = await sign_up(client, sender)
    auth = {"Authorization": f"Bearer {data['api_key']}"}
    r = await client.post("/v1/images/generations", headers=auth, json={"model": "qwen-image-3.0", "prompt": "a dragon"})
    assert r.status_code == 200
    files = {"image": ("in.png", PNG_1PX, "image/png")}
    form = {"model": "qwen-image-3.0", "prompt": "make it blue"}
    r = await client.post("/v1/images/edits", headers=auth, data=form, files=files)
    assert r.status_code == 200, r.text
    me = (await client.get("/v1/me", headers=auth)).json()
    assert me["recent"][0]["cost_cny"] == 0.2 and me["recent"][1]["cost_cny"] == 0.18
    assert me["spend"]["total"] == 0.38 and me["spend"]["left"] == 0.03


async def test_clips_are_priced_by_resolution_and_charged_once():
    """A clip's price follows the resolution asked for (the apps ask for 480P); it is held
    against the allowance from submission, charged once when the task is first seen done,
    and never again however often the task is polled."""
    app, client, sender, up, cloud = make(allowance_cny=5)
    data = await sign_up(client, sender)
    auth = {"Authorization": f"Bearer {data['api_key']}"}
    path = "/api/v1/services/aigc/video-generation/video-synthesis"

    async def submit(parameters: dict) -> str:
        body = {"model": "wan2.2-i2v-flash", "input": {"prompt": "wave", "img_url": "oss://x"}, "parameters": parameters}
        r = await client.post(path, headers=auth, json=body)
        assert r.status_code == 200, r.text
        return r.json()["output"]["task_id"]

    t480 = await submit({"resolution": "480P"})
    t1080 = await submit({"resolution": "1080P"})
    tsize = await submit({"size": "1280*720"})
    caller = cloud.authenticate(data["api_key"])
    held = cloud.db.pending_video_cost(caller.account_id)
    assert held == round((0.10 + 0.48 + 0.20) * 5 * M)
    # a fourth at 1080P (¥2.40) no longer fits in what is left of ¥5 beyond the ¥3.90 held
    r = await client.post(
        path,
        headers=auth,
        json={"model": "wan2.2-i2v-flash", "input": {"prompt": "x", "img_url": "oss://y"}, "parameters": {"resolution": "1080P"}},
    )
    assert r.status_code == 429 and r.json()["error"]["code"] == "allowance_exhausted"
    # polled: running, then done, then done again and again; each charged once, at the
    # price fixed when it was submitted
    for n, task_id in enumerate((t480, t1080, tsize), start=1):
        for _ in range(4):
            assert (await client.get(f"/api/v1/tasks/{task_id}", headers=auth)).status_code == 200
        rows = [r for r in (await client.get("/v1/me", headers=auth)).json()["recent"] if r["kind"] == "video"]
        assert len(rows) == n
    me = (await client.get("/v1/me", headers=auth)).json()
    clips = [r["cost_cny"] for r in me["recent"] if r["kind"] == "video"]
    assert sorted(clips) == [0.5, 1.0, 2.4] and me["spend"]["total"] == 3.9 and me["spend"]["left"] == 1.1
    assert cloud.db.pending_video_cost(caller.account_id) == 0
    # with the clips charged the hold is gone; a 1080P clip (¥2.40) still does not fit in ¥1.10, a 480P one (¥0.50) does
    r = await client.post(
        path,
        headers=auth,
        json={"model": "wan2.2-i2v-flash", "input": {"prompt": "x", "img_url": "oss://y"}, "parameters": {"resolution": "1080P"}},
    )
    assert r.status_code == 429
    assert (await submit({"resolution": "480P"})).startswith("task-")


async def test_clips_never_polled_are_settled_by_the_relay():
    """A clip the app never polls to an end (the app was closed) is still charged: shortly
    before the hour's hold lapses the relay asks the provider itself, charges a SUCCEEDED
    clip once, lets a FAILED one go, and asks about a task once more before the row is
    purged. A poll after the relay settled a task charges nothing more, and the other way
    round; a handful of tasks per tick."""
    app, client, sender, up, cloud = make(allowance_cny=5)
    data = await sign_up(client, sender)
    auth = {"Authorization": f"Bearer {data['api_key']}"}
    path = "/api/v1/services/aigc/video-generation/video-synthesis"
    caller = cloud.authenticate(data["api_key"])
    settle = app.state.settle_video_tasks

    async def submit() -> str:
        body = {"model": "wan2.2-i2v-flash", "input": {"prompt": "wave", "img_url": "oss://x"}, "parameters": {"resolution": "480P"}}
        r = await client.post(path, headers=auth, json=body)
        assert r.status_code == 200, r.text
        return r.json()["output"]["task_id"]

    done, failed, running, polled, gone, extra = [await submit() for _ in range(6)]
    up.state.task_status.update({done: "SUCCEEDED", failed: "FAILED", running: "RUNNING", gone: 404, extra: "SUCCEEDED"})
    clip = round(0.10 * 5 * M)
    assert cloud.db.pending_video_cost(caller.account_id) == 6 * clip
    # the app polled one of them to the end: charged by the poll
    for _ in range(2):
        assert (await client.get(f"/api/v1/tasks/{polled}", headers=auth)).status_code == 200
    assert cloud.db.video_task(polled)["charged"] == 1
    # too young: the relay asks about nothing yet
    assert await settle() == 0
    # 50 minutes on: the five unsettled tasks are due; a tick takes a handful
    with cloud.db.tx() as c:
        c.execute("UPDATE video_tasks SET created_at = created_at - 3100")
    asked_before = len([r for r in up.state.requests if r[0] == "task"])
    assert await settle(limit=2) == 2
    assert len([r for r in up.state.requests if r[0] == "task"]) == asked_before + 2
    assert await settle() == 3
    assert await settle() == 0  # each asked once; nothing due for a second look yet
    rows = {t: cloud.db.video_task(t) for t in (done, failed, running, gone, extra, polled)}
    assert rows[done]["status"] == "SUCCEEDED" and rows[done]["charged"] == 1
    assert rows[extra]["status"] == "SUCCEEDED" and rows[extra]["charged"] == 1
    assert rows[failed]["status"] == "FAILED" and rows[failed]["charged"] == 0
    assert rows[gone]["status"] == "UNKNOWN" and rows[gone]["charged"] == 0
    assert rows[running]["status"] == "RUNNING" and rows[running]["charged"] == 0 and rows[running]["checks"] == 1
    assert rows[polled]["checks"] == 0  # settled by the app's poll; never asked about
    me = (await client.get("/v1/me", headers=auth)).json()
    clips = [r for r in me["recent"] if r["kind"] == "video"]
    assert len(clips) == 3 and me["spend"]["total"] == 1.5  # polled, done, extra: ¥0.50 each
    # only the running one still holds money (and only until the hour is up)
    assert cloud.db.pending_video_cost(caller.account_id) == clip
    # the app comes back and polls the settled ones: nothing charged twice
    for t in (done, extra, failed):
        assert (await client.get(f"/api/v1/tasks/{t}", headers=auth)).status_code == 200
    me = (await client.get("/v1/me", headers=auth)).json()
    assert len([r for r in me["recent"] if r["kind"] == "video"]) == 3 and me["spend"]["total"] == 1.5
    # the hold has lapsed and the row is about to be purged: one more look, and it finished
    with cloud.db.tx() as c:
        c.execute("UPDATE video_tasks SET created_at = created_at - ?", (3 * 86400 - 3600,))
    up.state.task_status[running] = "SUCCEEDED"
    assert await settle() == 1  # the running one only; the others were answered for good
    assert cloud.db.video_task(running)["charged"] == 1 and cloud.db.video_task(running)["checks"] == 2
    assert await settle() == 0
    me = (await client.get("/v1/me", headers=auth)).json()
    assert len([r for r in me["recent"] if r["kind"] == "video"]) == 4 and me["spend"]["total"] == 2.0
    # a provider that does not answer is not counted as a check; the next tick asks again
    fresh = await submit()
    with cloud.db.tx() as c:
        c.execute("UPDATE video_tasks SET created_at = created_at - 3100 WHERE task_id=?", (fresh,))
    up.state.task_status[fresh] = 500
    assert await settle() == 0 and cloud.db.video_task(fresh)["checks"] == 0
    up.state.task_status[fresh] = "SUCCEEDED"
    assert await settle() == 1 and cloud.db.video_task(fresh)["charged"] == 1


async def test_two_chats_at_the_boundary_do_not_both_pass():
    """With less than one typical turn left, two chats started together: the first holds a
    turn's worth, so the second is refused rather than both passing the same check; the
    ledger has one line, and the overrun is at most the one turn under way."""
    turn = (6000 * 3 + 1500 * 12) / M  # the reservation for qwen3.8-27b, ¥0.036
    app, client, sender, up, cloud = make(allowance_cny=round(turn * 0.9, 4))
    data = await sign_up(client, sender)
    auth = {"Authorization": f"Bearer {data['api_key']}"}
    seen = 0

    async def slow(request: Request):
        nonlocal seen
        seen += 1
        await asyncio.sleep(0.05)
        return {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }

    replace_chat(up, slow)
    body = {"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]}
    rs = await asyncio.gather(*(client.post("/v1/chat/completions", headers=auth, json=body) for _ in range(2)))
    assert sorted(r.status_code for r in rs) == [200, 429] and seen == 1
    refused = next(r for r in rs if r.status_code == 429).json()["error"]
    assert refused["code"] == "allowance_exhausted" and refused["left"] == round(turn * 0.9, 4)
    me = (await client.get("/v1/me", headers=auth)).json()
    assert len(me["recent"]) == 2 and [r["kind"] for r in me["recent"]] == ["chat", "credit"]
    assert me["spend"]["total"] == round((100 * 3 + 50 * 12) / M, 4)
    # once settled, the next chat is let through again (the real charge was far under the hold)
    assert (await client.post("/v1/chat/completions", headers=auth, json=body)).status_code == 200


async def test_me_figures_agree_with_the_ledger():
    """What every client prints — spent, the pool, what is left, in yuan — is one quantity
    from one ledger: left is pool minus spent, the breakdown by kind sums to the total, and
    the sign-up credit is not spend."""
    app, client, sender, up, cloud = make(allowance_cny=10)
    data = await sign_up(client, sender)
    auth = {"Authorization": f"Bearer {data['api_key']}"}
    messages = [{"role": "user", "content": "hi"}]
    for model in ("deepseek-v4.1-flash", "qwen3.8-27b", "qwen3.8-flash"):
        assert (await client.post("/v1/chat/completions", headers=auth, json={"model": model, "messages": messages})).status_code == 200
    assert (
        await client.post("/v1/images/generations", headers=auth, json={"model": "qwen-image-3.0", "prompt": "a cat"})
    ).status_code == 200
    me = (await client.get("/v1/me", headers=auth)).json()
    sp = me["spend"]
    chat = (100 * 2 + 50 * 8 + 100 * 3 + 50 * 12 + 100 * 0.8 + 50 * 2.7) / M
    assert sp["currency"] == "CNY" and sp["grant"] == 10 and sp["total"] == round(chat + 0.18, 4)
    assert sp["left"] == round(10 - sp["total"], 4) and sp["today"] == sp["total"]
    assert sp["left_usd"] == round(sp["left"] / sp["usd_cny"], 4)
    by_kind = {r["kind"]: r["cost_cny"] for r in me["usage"]["total"]["by_kind"]}
    assert by_kind == {"chat": round(chat, 4), "image": 0.18}
    assert round(sum(by_kind.values()), 4) == sp["total"]
    # the ledger's credit line (the sign-up) is on the statement but not in the spend
    kinds = [r["kind"] for r in me["recent"]]
    assert kinds.count("credit") == 1 and round(sum(r["cost_cny"] for r in me["recent"]), 4) == sp["total"]
    # the operator's view of the same account says the same numbers
    accounts = (await client.get("/v1/admin/accounts", headers=ADMIN)).json()["accounts"]
    row = next(a for a in accounts if a["id"] == me["account"]["id"])
    assert row["spent_cny"] == sp["total"] and row["grant_cny"] == sp["grant"] and row["left_cny"] == sp["left"]
