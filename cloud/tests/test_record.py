"""0.29: the record — every chat turn in full, its pictures as files (record.py)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import itertools
import json
import time
from dataclasses import replace

import httpx
import pytest
from test_cloud import APP_UA, PNG_1PX, fake_upstream, sign_up

from nanomuse_cloud.api import create_app
from nanomuse_cloud.db import Database
from nanomuse_cloud.record import BLOB_PREFIX, MediaStore, StreamAssembler, attach_media, detach_media, media_refs
from nanomuse_cloud.senders import LogSender
from nanomuse_cloud.service import Cloud

PNG_URL = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()
PNG_SHA = hashlib.sha256(PNG_1PX).hexdigest()
ADMIN = {"X-Admin-Token": "admin"}


def relay(tmp_path, **overrides):
    """A relay like test_cloud's ``stack``, with the record's files under ``tmp_path``."""
    from nanomuse_cloud.config import Settings

    up = fake_upstream()
    settings = Settings(
        database=":memory:",
        secret="test-secret",
        admin_token="admin",
        upstream_base="http://upstream/compat/v1",
        upstream_key="sk-upstream",
        signup_tokens=1000,
        daily_cap_tokens=100_000,
        per_minute_requests=100,
        chat_retry_base_s=0,
        public_base="http://cloud.test",
        media_dir=str(tmp_path / "blobs"),
        **overrides,
    )
    sender = LogSender()
    cloud = Cloud(settings, Database(":memory:"), sender)
    app = create_app(settings, cloud, upstream_transport=httpx.ASGITransport(app=up))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cloud.test", headers=APP_UA)
    return app, client, sender, up, cloud


async def settled(app) -> None:
    """The record is written off the loop after the answer left; wait for it."""
    while app.state.record_tasks:
        await asyncio.gather(*list(app.state.record_tasks))
        # gather may finish immediately; let the queued discard callbacks run.
        await asyncio.sleep(0)


FULL_TURN = [
    {"role": "system", "content": "SOUL and memory: the person's name is Ada"},
    {"role": "user", "content": [{"type": "text", "text": "what is on my screen"}, {"type": "image_url", "image_url": {"url": PNG_URL}}]},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "tap", "arguments": "{}"}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "tapped; the screen now shows the inbox"},
]


def test_detach_puts_every_picture_once_and_attach_brings_it_back(tmp_path):
    store = MediaStore(tmp_path)
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "image_url", "image_url": {"url": PNG_URL, "detail": "low"}}]},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": PNG_URL}},
                {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "input_audio", "input_audio": {"data": base64.b64encode(b"RIFFwav").decode(), "format": "wav"}}],
        },
        {"role": "user", "content": "plain words"},
    ]
    out, media = detach_media(msgs, store)
    assert out[0]["content"][1] == {"type": "image_url", "image_url": {"url": BLOB_PREFIX + PNG_SHA, "detail": "low"}}
    assert out[1]["content"][0]["image_url"]["url"] == BLOB_PREFIX + PNG_SHA  # the same picture: the same file
    assert out[1]["content"][1]["image_url"]["url"] == "https://x/y.png"  # a link is a link
    assert out[2]["content"][0]["input_audio"]["format"] == "wav" and out[2]["content"][0]["input_audio"]["data"].startswith(BLOB_PREFIX)
    assert out[3] == msgs[3]
    assert [(m["mime"], m["bytes"]) for m in media] == [("image/png", len(PNG_1PX)), ("audio/wav", 7)]
    assert store.has(PNG_SHA) and store.path(PNG_SHA).read_bytes() == PNG_1PX
    assert media_refs(out) == {PNG_SHA, media[1]["sha256"]}
    back = attach_media(out, store, {m["sha256"]: m["mime"] for m in media})
    assert back[0]["content"][1]["image_url"]["url"] == PNG_URL
    # the originals were not touched
    assert msgs[0]["content"][1]["image_url"]["url"] == PNG_URL
    # a file trimmed from the store stays a reference
    store.delete(PNG_SHA)
    assert attach_media(out, store, {})[0]["content"][1]["image_url"]["url"] == BLOB_PREFIX + PNG_SHA


def test_stream_assembler_rebuilds_the_message():
    a = StreamAssembler()
    chunks = [
        {"choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": "think "}}]},
        {"choices": [{"index": 0, "delta": {"reasoning_content": "hard", "content": None}}]},
        {"choices": [{"index": 0, "delta": {"content": "Open"}}]},
        {"choices": [{"index": 0, "delta": {"content": "ing."}}]},
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "tap", "arguments": ""}}]
                    },
                }
            ]
        },
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"x": 1'}}]}}]},
        {
            "choices": [
                {"index": 0, "delta": {"tool_calls": [{"index": 1, "id": "call_2", "function": {"name": "wait", "arguments": "{}"}}]}}
            ]
        },
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "0}"}}]}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 2}},
    ]
    for c in chunks:
        a.feed(c)
    assert a.message() == {
        "role": "assistant",
        "content": "Opening.",
        "reasoning_content": "think hard",
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "tap", "arguments": '{"x": 10}'}},
            {"id": "call_2", "type": "function", "function": {"name": "wait", "arguments": "{}"}},
        ],
        "finish_reason": "tool_calls",
    }
    assert StreamAssembler().message() == {"role": "assistant", "content": ""}


async def test_every_cloud_turn_is_kept_whole_and_read_back_by_the_account(tmp_path):
    """Whatever the Help-improve switch says, the record holds the turn as it happened: the
    system prompt, the picture (as a file), the tool's result, the model's whole answer —
    for the account's own devices and the operator, never for another account."""
    app, client, sender, up, cloud = relay(tmp_path)
    data = await sign_up(client, sender, identifier="rec-a@example.com")
    headers = {"Authorization": f"Bearer {data['api_key']}", "User-Agent": "nanoMuse-Android/1.0.7", "Accept-Language": "zh-CN"}
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["contribute"]["on"] is False  # the training switch is off, the record is not a switch
    assert me["contribute"]["record"] == {"on": True, "turns": 0, "own": 0, "files": 0, "media_bytes": 0, "keep_days": 0}

    r = await client.post(
        "/v1/chat/completions",
        headers={**headers, "X-NanoMuse-Device": "pixel-1", "X-NanoMuse-Conversation": "conv-7"},
        json={
            "model": "qwen3.8-27b",
            "messages": FULL_TURN,
            "temperature": 0.2,
            "tools": [{"type": "function", "function": {"name": "tap"}}],
        },
    )
    assert r.status_code == 200
    request_id = r.headers["x-nanomuse-request"]
    # and a streamed, thinking one in another conversation
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={**headers, "X-NanoMuse-Conversation": "conv-8"},
        json={"model": "qwen3.8-27b", "stream": True, "enable_thinking": True, "messages": [{"role": "user", "content": "hi"}]},
    ) as s:
        await s.aread()
    await settled(app)

    turns = (await client.get("/v1/turns", headers=headers)).json()["turns"]
    assert [t["conversation"] for t in turns] == ["conv-8", "conv-7"]  # newest first
    whole = turns[1]
    assert whole["id"] == request_id and whole["device"] == "pixel-1" and whole["platform"] == "android" and whole["source"] == "cloud"
    assert whole["status"] == "ok" and whole["model"] == "qwen3.8-27b"
    req = whole["request"]
    assert req["model"] == "qwen3.8-27b" and req["temperature"] == 0.2 and req["tools"][0]["function"]["name"] == "tap"
    assert "user" not in req and "stream_options" not in req  # the relay's own fields
    assert req["enable_thinking"] is False  # the relay's default went up with it, and is kept as sent
    assert [m["role"] for m in req["messages"]] == ["system", "user", "assistant", "tool"]
    assert req["messages"][0]["content"].startswith("SOUL and memory")
    assert req["messages"][1]["content"][1] == {"type": "image_url", "image_url": {"url": BLOB_PREFIX + PNG_SHA}}
    assert req["messages"][3]["content"] == "tapped; the screen now shows the inbox"
    assert whole["response"] == {
        "message": {"role": "assistant", "content": "hi", "finish_reason": "stop"},
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cached_tokens": 0},
    }
    assert whole["prompt_tokens"] == 100 and whole["completion_tokens"] == 50
    assert whole["media"] == 1 and whole["media_bytes"] == len(PNG_1PX)
    assert whole["meta"] == {
        "ua": "nanoMuse-Android/1.0.7",
        "lang": "zh-CN",
        "media": [{"sha256": PNG_SHA, "mime": "image/png", "bytes": len(PNG_1PX)}],
    }
    assert "account_id" not in whole and "ip" not in whole["meta"]  # the person's own view
    streamed = turns[0]
    assert streamed["response"]["message"] == {"role": "assistant", "content": "你好，世界", "reasoning_content": "先想一下"}
    assert streamed["response"]["usage"] == {"prompt_tokens": 40, "completion_tokens": 26, "cached_tokens": 0}  # reasoning counted in
    assert streamed["device"] == "" and streamed["platform"] == "android"
    # one turn by id, one conversation by name
    assert (await client.get(f"/v1/turns/{request_id}", headers=headers)).json()["id"] == request_id
    assert [t["id"] for t in (await client.get("/v1/turns?conversation=conv-7", headers=headers)).json()["turns"]] == [request_id]
    # the picture, for this account
    r = await client.get(f"/v1/blobs/{PNG_SHA}", headers=headers)
    assert r.status_code == 200 and r.content == PNG_1PX and r.headers["content-type"] == "image/png"
    assert "immutable" in r.headers["cache-control"]
    h = await client.head(f"/v1/blobs/{PNG_SHA}", headers=headers)
    assert h.status_code == 200 and h.headers["content-length"] == str(len(PNG_1PX))
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["contribute"]["record"] == {"on": True, "turns": 2, "own": 0, "files": 1, "media_bytes": len(PNG_1PX), "keep_days": 0}

    # another account: not its turn, not its file, even knowing the hash and the id
    other = await sign_up(client, sender, identifier="rec-b@example.com", device="mac")
    theirs = {"Authorization": f"Bearer {other['api_key']}"}
    assert (await client.get("/v1/turns", headers=theirs)).json() == {"turns": []}
    assert (await client.get(f"/v1/turns/{request_id}", headers=theirs)).status_code == 404
    assert (await client.get(f"/v1/blobs/{PNG_SHA}", headers=theirs)).status_code == 404
    assert (await client.head(f"/v1/blobs/{PNG_SHA}", headers=theirs)).status_code == 404

    # the operator: the whole record, account ids and addresses included, and the files
    got = (await client.get("/v1/admin/turns", headers=ADMIN)).json()
    assert got["total"] == 2 and got["turns"][1]["account_id"] == data["account"]["id"] and "ip" in got["turns"][1]["meta"]
    assert (await client.get(f"/v1/admin/turns?account_id={other['account']['id']}", headers=ADMIN)).json()["total"] == 0
    r = await client.get("/v1/admin/turns/export", headers=ADMIN)
    lines = [json.loads(ln) for ln in r.text.splitlines() if ln]
    assert len(lines) == 2 and {ln["id"] for ln in lines} == {t["id"] for t in turns} and all("account_id" in ln for ln in lines)
    assert (await client.get(f"/v1/admin/blobs/{PNG_SHA}", headers=ADMIN)).content == PNG_1PX
    view = (await client.get("/v1/admin/record?days=3", headers=ADMIN)).json()
    assert view["on"] is True and view["keep_days"] == 0 and view["media_cap_bytes"] == 50 * 1024**3
    assert view["totals"] == {
        "n": 2,
        "accounts": 1,
        "own": 0,
        "partial": 0,
        "media": 1,
        "media_bytes": len(PNG_1PX),
        "files": 1,
        "store_bytes": len(PNG_1PX),
        "questions": 1,  # 0.31: the full turn's call came after a tool's result; the other opened a question
    }
    assert len(view["days"]) == 3 and view["days"][-1]["turns"] == 2 and view["days"][-1]["media"] == 1
    assert view["days"][-1]["questions"] == 1 and view["questions"]["n"] == 1 and view["questions"]["pending"] == 0
    # the training view is untouched by all this: the switch was off, nothing is there
    assert (await client.get("/v1/admin/samples", headers=ADMIN)).json()["total"] == 0


async def test_a_slower_record_cannot_list_an_older_turn_above_a_newer_one(tmp_path, monkeypatch):
    """The rows are written off the loop, so a turn whose picture is still decoding can
    take longer than a plain turn that answered after it. The listing is newest first by
    (ts, rowid): the timestamp is the turn's own and the writes follow the answers, or
    the older turn lands with a later timestamp and a later rowid and reads as newer."""
    app, client, sender, up, cloud = relay(tmp_path)
    data = await sign_up(client, sender, identifier="rec-race@example.com")
    headers = {"Authorization": f"Bearer {data['api_key']}", **APP_UA}
    real_record = cloud.record_turn
    records = itertools.count()

    def slow_first_record(*args, **kwargs):
        if next(records) == 0:
            time.sleep(0.3)  # the first turn's picture, still decoding when the second lands
        return real_record(*args, **kwargs)

    monkeypatch.setattr(cloud, "record_turn", slow_first_record)
    for conversation in ("conv-a", "conv-b"):
        r = await client.post(
            "/v1/chat/completions",
            headers={**headers, "X-NanoMuse-Conversation": conversation},
            json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.status_code == 200
    await settled(app)
    turns = (await client.get("/v1/turns", headers=headers)).json()["turns"]
    assert [t["conversation"] for t in turns] == ["conv-b", "conv-a"]  # newest first


async def test_a_turn_on_an_own_key_is_put_up_with_its_files(tmp_path):
    app, client, sender, up, cloud = relay(tmp_path)
    data = await sign_up(client, sender, identifier="own-a@example.com")
    headers = {"Authorization": f"Bearer {data['api_key']}", "User-Agent": "nanoMuse-Desktop/1.0.7"}
    # HEAD, then PUT: the file is checked against its name
    assert (await client.head(f"/v1/blobs/{PNG_SHA}", headers=headers)).status_code == 404
    r = await client.put(f"/v1/blobs/{PNG_SHA}", headers={**headers, "Content-Type": "image/png"}, content=b"not the picture")
    assert r.status_code == 400 and r.json()["error"]["code"] == "hash_mismatch"
    r = await client.put(f"/v1/blobs/{PNG_SHA}", headers={**headers, "Content-Type": "application/zip"}, content=PNG_1PX)
    assert r.status_code == 400
    r = await client.put("/v1/blobs/nothex", headers={**headers, "Content-Type": "image/png"}, content=PNG_1PX)
    assert r.status_code == 400
    r = await client.put(f"/v1/blobs/{PNG_SHA}", headers={**headers, "Content-Type": "image/png"}, content=PNG_1PX)
    assert r.status_code == 200 and r.json() == {"sha256": PNG_SHA, "bytes": len(PNG_1PX), "mime": "image/png", "known": False}
    r = await client.put(f"/v1/blobs/{PNG_SHA}", headers={**headers, "Content-Type": "image/png"}, content=PNG_1PX)
    assert r.json()["known"] is True
    assert (await client.head(f"/v1/blobs/{PNG_SHA}", headers=headers)).status_code == 200
    # too big for one file
    big = b"\x89PNG" + b"\0" * (cloud.s.blob_max_bytes + 1)
    r = await client.put(f"/v1/blobs/{hashlib.sha256(big).hexdigest()}", headers={**headers, "Content-Type": "image/png"}, content=big)
    assert r.status_code == 413

    turn = {
        "id": "t-0001",
        "ts": 1792800000,
        "model": "gpt-5.6",
        "provider": "openai",
        "conversation": "conv-1",
        "messages": [
            {"role": "system", "content": "SOUL"},
            {
                "role": "user",
                "content": [{"type": "text", "text": "see"}, {"type": "image_url", "image_url": {"url": BLOB_PREFIX + PNG_SHA}}],
            },
        ],
        "response": {"message": {"role": "assistant", "content": "I see a dot."}, "usage": {"prompt_tokens": 12, "completion_tokens": 5}},
        "temperature": 0.5,
    }
    r = await client.post("/v1/turns", headers={**headers, "X-NanoMuse-Device": "mac-1"}, json=turn)
    assert r.status_code == 201, r.text
    assert r.json() == {"id": f"own-{data['account']['id'][:8]}-t-0001", "ts": 1792800000}
    # a reference to a file nobody put up, and shapes the relay cannot keep
    bad_ref = {
        **turn,
        "id": "t-0002",
        "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": BLOB_PREFIX + "0" * 64}}]}],
    }
    r = await client.post("/v1/turns", headers=headers, json=bad_ref)
    assert r.status_code == 400 and r.json()["error"]["code"] == "unknown_blob"
    for bad in ({**turn, "model": ""}, {**turn, "messages": []}, {**turn, "response": {"text": "x"}}, {**turn, "messages": "hi"}):
        assert (await client.post("/v1/turns", headers=headers, json=bad)).status_code == 400
    # a picture inline is taken out the same way as on a Cloud turn
    inline = {
        **turn,
        "id": "t-0003",
        "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": PNG_URL}}]}],
        "status": "partial",
    }
    assert (await client.post("/v1/turns", headers=headers, json=inline)).status_code == 201

    turns = (await client.get("/v1/turns", headers=headers)).json()["turns"]
    assert [t["id"][-6:] for t in turns] == ["t-0003", "t-0001"]
    own = turns[1]
    assert own["source"] == "own" and own["platform"] == "desktop" and own["device"] == "mac-1" and own["conversation"] == "conv-1"
    assert own["ts"] == 1792800000 and own["model"] == "gpt-5.6" and own["meta"]["provider"] == "openai"
    assert own["request"] == {"model": "gpt-5.6", "messages": turn["messages"], "temperature": 0.5}
    assert own["response"] == {
        "message": {"role": "assistant", "content": "I see a dot."},
        "usage": {"prompt_tokens": 12, "completion_tokens": 5, "cached_tokens": 0},
    }
    assert own["media"] == 1 and own["media_bytes"] == len(PNG_1PX)
    assert turns[0]["status"] == "partial" and turns[0]["request"]["messages"][0]["content"][0]["image_url"]["url"] == BLOB_PREFIX + PNG_SHA
    # `status` is the turn's, not a field of the request the model saw
    assert "status" not in turns[0]["request"]
    me = (await client.get("/v1/me", headers=headers)).json()
    record = {"on": True, "turns": 2, "own": 2, "files": 1, "media_bytes": len(PNG_1PX), "keep_days": 0}
    assert me["contribute"]["record"] == record
    # the flip answers the same figures (0.30): an app that redraws Data controls from it keeps them
    flipped = (await client.post("/v1/me/contribute", headers=headers, json={"on": False})).json()
    assert flipped["on"] is False and flipped["record"] == record
    assert (await client.get("/v1/admin/record", headers=ADMIN)).json()["totals"]["own"] == 2
    # the record's events never carry words
    events = (await client.get("/v1/me/events", headers=headers)).json()["events"]
    assert all("SOUL" not in json.dumps(e) for e in events)


async def test_deleting_the_record_removes_only_the_files_nobody_else_holds(tmp_path):
    app, client, sender, up, cloud = relay(tmp_path)
    a = await sign_up(client, sender, identifier="del-a@example.com")
    b = await sign_up(client, sender, identifier="del-b@example.com", device="mac")
    ha = {"Authorization": f"Bearer {a['api_key']}"}
    hb = {"Authorization": f"Bearer {b['api_key']}"}
    other_png = PNG_1PX + b"\0"  # a second picture, only A's
    for h, pics in ((ha, [PNG_URL, "data:image/png;base64," + base64.b64encode(other_png).decode()]), (hb, [PNG_URL])):
        msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": p}} for p in pics]}]
        assert (await client.post("/v1/chat/completions", headers=h, json={"model": "qwen3.8-27b", "messages": msgs})).status_code == 200
    await settled(app)
    other_sha = hashlib.sha256(other_png).hexdigest()
    assert cloud.media.has(PNG_SHA) and cloud.media.has(other_sha)
    assert (await client.get("/v1/admin/record", headers=ADMIN)).json()["totals"]["store_bytes"] == len(PNG_1PX) + len(other_png)

    r = await client.delete("/v1/me/samples", headers=ha)
    assert r.json() == {"deleted": 0, "turns": 1, "files": 1}  # the shared picture stays for B
    assert not cloud.media.has(other_sha) and cloud.media.has(PNG_SHA)
    assert (await client.get("/v1/turns", headers=ha)).json() == {"turns": []}
    assert (await client.get(f"/v1/blobs/{PNG_SHA}", headers=ha)).status_code == 404  # A holds no reference any more
    assert (await client.get(f"/v1/blobs/{PNG_SHA}", headers=hb)).status_code == 200
    # deleting B's account takes the last reference and the file with it
    assert (await client.post("/v1/auth/delete", headers=hb)).status_code == 204
    assert not cloud.media.has(PNG_SHA)
    assert cloud.db.turn_count() == 0 and cloud.db.record_totals()["files"] == 0


async def test_retention_and_the_cap_sweep_the_oldest_first(tmp_path):
    app, client, sender, up, cloud = relay(tmp_path, record_keep_days=7, media_max_gb=0.000001)  # ~1 KB cap
    a = await sign_up(client, sender, identifier="old-a@example.com")
    ha = {"Authorization": f"Bearer {a['api_key']}"}
    # an old turn, written as the relay would have eight days ago
    old_png = b"\x89PNG" + b"\1" * 300
    cloud.media.put(old_png)
    old_sha = hashlib.sha256(old_png).hexdigest()
    from nanomuse_cloud.record import pack

    cloud.db.add_turn(
        {
            "id": "old-1",
            "account_id": a["account"]["id"],
            "ts": cloud.clock() - 8 * 86400,
            "model": "qwen3.8-27b",
            "request": pack({"messages": []}),
            "response": pack({"message": {"role": "assistant", "content": "old"}}),
            "meta": "{}",
        },
        [{"sha256": old_sha, "mime": "image/png", "bytes": len(old_png)}],
    )
    # and three fresh ones with pictures of 600 bytes each: the cap holds one and a bit
    shas = []
    for i in range(3):
        pic = b"\x89PNG" + bytes([i]) * 600
        shas.append(hashlib.sha256(pic).hexdigest())
        msgs = [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(pic).decode()}}],
            }
        ]
        assert (await client.post("/v1/chat/completions", headers=ha, json={"model": "qwen3.8-27b", "messages": msgs})).status_code == 200
        await settled(app)
        cloud.db._conn.execute("UPDATE blobs SET last_used_at=last_used_at+? WHERE sha256=?", (i + 1, shas[-1]))  # order the uses
    assert cloud.db.turn_count() == 4 and all(cloud.media.has(s) for s in shas) and cloud.media.has(old_sha)

    swept = cloud.sweep_record()
    assert swept["turns"] == 1 and swept["files"] == 1  # the old turn and its picture
    assert not cloud.media.has(old_sha) and cloud.db.turn("old-1") is None
    assert swept["trimmed"] == 2  # 1800 bytes over a ~1 KB cap: the two least recently used go
    assert not cloud.media.has(shas[0]) and not cloud.media.has(shas[1]) and cloud.media.has(shas[2])
    # the turns whose pictures went stay, with a reference to nothing
    turns = (await client.get("/v1/turns", headers=ha)).json()["turns"]
    assert len(turns) == 3 and turns[-1]["request"]["messages"][0]["content"][0]["image_url"]["url"] == BLOB_PREFIX + shas[0]
    assert (await client.get(f"/v1/blobs/{shas[0]}", headers=ha)).status_code == 404
    assert (await client.get(f"/v1/blobs/{shas[2]}", headers=ha)).status_code == 200
    assert cloud.sweep_record() == {"turns": 0, "files": 0, "trimmed": 0}
    assert (await client.get("/v1/me", headers=ha)).json()["contribute"]["record"]["keep_days"] == 7


async def test_a_relay_that_keeps_no_record(tmp_path):
    app, client, sender, up, cloud = relay(tmp_path, record_turns=False)
    a = await sign_up(client, sender, identifier="none-a@example.com")
    ha = {"Authorization": f"Bearer {a['api_key']}"}
    msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": PNG_URL}}]}]
    assert (await client.post("/v1/chat/completions", headers=ha, json={"model": "qwen3.8-27b", "messages": msgs})).status_code == 200
    await settled(app)
    assert cloud.db.turn_count() == 0 and not cloud.media.has(PNG_SHA) and not list((tmp_path / "blobs").rglob("*"))
    me = (await client.get("/v1/me", headers=ha)).json()
    assert me["contribute"]["record"] == {"on": False, "turns": 0, "own": 0, "files": 0, "media_bytes": 0, "keep_days": 0}
    assert (await client.get("/v1/turns", headers=ha)).json() == {"turns": []}
    r = await client.post(
        "/v1/turns", headers=ha, json={"model": "m", "messages": msgs, "response": {"message": {"role": "assistant", "content": "x"}}}
    )
    assert r.status_code == 404
    assert (await client.put(f"/v1/blobs/{PNG_SHA}", headers={**ha, "Content-Type": "image/png"}, content=PNG_1PX)).status_code == 404
    assert (await client.get("/v1/admin/record", headers=ADMIN)).json()["on"] is False


async def test_the_faces_clips_travel_with_the_profile(tmp_path):
    """A device that animated the drawn face puts the clips up as files and names them in
    the profile; the other devices download them instead of rendering their own."""
    app, client, sender, up, cloud = relay(tmp_path)
    a = await sign_up(client, sender, identifier="clip-a@example.com")
    ha = {"Authorization": f"Bearer {a['api_key']}"}
    clip = b"\x00\x00\x00\x18ftypmp42" + b"\0" * 100
    sha = hashlib.sha256(clip).hexdigest()
    face = {"idle": base64.b64encode(b"RIFF\0\0\0\0WEBPVP8 ").decode()}
    # a clip the account never put up is refused; so is a picture where a video should be
    r = await client.put(
        "/v1/me/profile", headers=ha, json={"device": "mac-1", "avatar": "face", "face": face, "clips": {"idle": {"sha256": sha}}}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "unknown_blob"
    assert (await client.put(f"/v1/blobs/{sha}", headers={**ha, "Content-Type": "video/mp4"}, content=clip)).status_code == 200
    r = await client.put(
        "/v1/me/profile",
        headers=ha,
        json={"device": "mac-1", "avatar": "face", "face": face, "clips": {"idle": {"sha256": sha, "mime": "image/png"}}},
    )
    assert r.status_code == 400
    r = await client.put(
        "/v1/me/profile",
        headers=ha,
        json={"device": "mac-1", "avatar": "face", "face": face, "clips": {"idle": {"sha256": sha}, "nap": {"sha256": sha}}},
    )
    assert r.status_code == 400
    r = await client.put(
        "/v1/me/profile", headers=ha, json={"device": "mac-1", "avatar": "face", "face": face, "clips": {"idle": {"sha256": sha}}}
    )
    assert r.status_code == 200 and r.json()["rev"] == 1
    prof = (await client.get("/v1/me/profile", headers=ha)).json()
    assert prof["clips"] == {"idle": {"sha256": sha, "mime": "video/mp4", "bytes": len(clip)}} and prof["has_face"] is True
    # another device of the account reads the clip; a write that names only the name keeps the clips
    assert (await client.get(f"/v1/blobs/{sha}", headers=ha)).content == clip
    assert (await client.put("/v1/me/profile", headers=ha, json={"device": "pixel-1", "name": "Mu"})).status_code == 200
    assert (await client.get("/v1/me/profile", headers=ha)).json()["clips"]["idle"]["sha256"] == sha
    # a new face drawn without a word about clips: the old face's clips do not fit it and go (0.30)
    other = {"idle": base64.b64encode(b"RIFF\0\0\0\0WEBPVP8 other").decode()}
    assert (await client.put("/v1/me/profile", headers=ha, json={"device": "pixel-1", "avatar": "face", "face": other})).status_code == 200
    assert (await client.get("/v1/me/profile", headers=ha)).json()["clips"] is None
    assert (await client.put("/v1/me/profile", headers=ha, json={"device": "mac-1", "clips": {"idle": {"sha256": sha}}})).status_code == 200
    assert (await client.get("/v1/me/profile", headers=ha)).json()["clips"]["idle"]["sha256"] == sha
    # `clips: null` clears them; so does leaving the drawn face
    assert (await client.put("/v1/me/profile", headers=ha, json={"device": "pixel-1", "clips": None})).status_code == 200
    assert (await client.get("/v1/me/profile", headers=ha)).json()["clips"] is None
    assert (await client.put("/v1/me/profile", headers=ha, json={"device": "mac-1", "clips": {"idle": {"sha256": sha}}})).status_code == 200
    assert (await client.put("/v1/me/profile", headers=ha, json={"device": "mac-1", "avatar": "dragon"})).status_code == 200
    assert (await client.get("/v1/me/profile", headers=ha)).json()["clips"] is None
    # the upload's own reference keeps the file readable until the record is deleted
    assert (await client.get(f"/v1/blobs/{sha}", headers=ha)).status_code == 200
    assert (await client.delete("/v1/me/samples", headers=ha)).json()["files"] == 1
    assert (await client.get(f"/v1/blobs/{sha}", headers=ha)).status_code == 404 and not cloud.media.has(sha)


@pytest.mark.parametrize("bad", ["zz", "0" * 63, "../x"])
async def test_a_blob_name_is_a_hash(tmp_path, bad):
    app, client, sender, up, cloud = relay(tmp_path)
    a = await sign_up(client, sender, identifier="hash-a@example.com")
    ha = {"Authorization": f"Bearer {a['api_key']}"}
    assert (await client.get(f"/v1/blobs/{bad}", headers=ha)).status_code == 404
    assert (await client.get(f"/v1/admin/blobs/{bad}", headers=ADMIN)).status_code == 404


async def test_uploads_are_paced_and_the_account_and_the_store_have_caps(tmp_path):
    """0.30: one account sends so many turns and files a minute, holds so many MB of files,
    and nothing is taken past the store's cap until the trim has run. A file the account
    already holds costs nothing again."""
    app, client, sender, up, cloud = relay(tmp_path, record_uploads_per_minute=4, media_account_max_mb=1)
    a = await sign_up(client, sender, identifier="pace-a@example.com")
    ha = {"Authorization": f"Bearer {a['api_key']}"}
    big = b"\x89PNG" + b"\7" * (700 * 1024)
    sha = hashlib.sha256(big).hexdigest()
    r = await client.put(f"/v1/blobs/{sha}", headers={**ha, "Content-Type": "image/png"}, content=big)
    assert r.status_code == 200 and r.json()["known"] is False
    # the same file again: known, and not counted against the cap a second time
    r = await client.put(f"/v1/blobs/{sha}", headers={**ha, "Content-Type": "image/png"}, content=big)
    assert r.status_code == 200 and r.json()["known"] is True
    other = b"\x89PNG" + b"\\8" * (700 * 1024)  # two bytes a repeat: about 1.4 MiB
    r = await client.put(f"/v1/blobs/{hashlib.sha256(other).hexdigest()}", headers={**ha, "Content-Type": "image/png"}, content=other)
    assert r.status_code == 413 and r.json()["error"]["code"] == "quota_exceeded"
    assert not cloud.media.has(hashlib.sha256(other).hexdigest())  # refused before anything was written
    # an own-key turn with pictures inline is measured the same way, before it is decoded
    turn = {
        "model": "gpt-x",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(other).decode()}}],
            }
        ],
        "response": {"message": {"role": "assistant", "content": "a picture"}},
    }
    r = await client.post("/v1/turns", headers=ha, json=turn)
    assert r.status_code == 413 and r.json()["error"]["code"] == "quota_exceeded"
    # the pace: four uploads this minute were the three PUTs and the POST; the fifth waits
    small = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        "response": {"message": {"role": "assistant", "content": "hello"}},
    }
    r = await client.post("/v1/turns", headers=ha, json=small)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert cloud.db.turn_count(a["account"]["id"]) == 0
    # another account is not slowed by it, and the store's cap stops everyone
    b = await sign_up(client, sender, identifier="pace-b@example.com")
    hb = {"Authorization": f"Bearer {b['api_key']}"}
    assert (await client.post("/v1/turns", headers=hb, json=small)).status_code == 201
    cloud.s = replace(cloud.s, media_max_gb=0.000001)  # ~1 KB, already passed by the 700 KB file
    r = await client.put(f"/v1/blobs/{hashlib.sha256(other).hexdigest()}", headers={**hb, "Content-Type": "image/png"}, content=other)
    assert r.status_code == 507 and r.json()["error"]["code"] == "store_full"
    # a turn without pictures still goes up: the cap is about the files
    assert (await client.post("/v1/turns", headers=hb, json=small)).status_code == 201


async def test_the_trim_spares_the_clips_a_profile_wears(tmp_path):
    app, client, sender, up, cloud = relay(tmp_path, media_max_gb=0.000001)  # ~1 KB cap
    a = await sign_up(client, sender, identifier="clip-trim@example.com")
    clip = b"\x00\x00\x00\x18ftypmp42" + b"\1" * 800
    clip_sha, _ = cloud.media.put(clip)
    cloud.db.add_blob(clip_sha, "video/mp4", len(clip), a["account"]["id"], "profile")
    pics = []
    for i in range(3):
        pic = b"\x89PNG" + bytes([i]) * 600
        sha, _ = cloud.media.put(pic)
        cloud.db.add_blob(sha, "image/png", len(pic), a["account"]["id"], "turn")
        cloud.db._conn.execute("UPDATE blobs SET last_used_at=? WHERE sha256=?", (1000 + i, sha))
        pics.append(sha)
    cloud.db._conn.execute("UPDATE blobs SET last_used_at=1 WHERE sha256=?", (clip_sha,))  # the oldest use of all
    swept = cloud.sweep_record()
    # the three pictures go (1800 bytes over a ~1 KB cap with the 800-byte clip staying); the clip never does
    assert swept["trimmed"] == 3 and cloud.media.has(clip_sha) and not any(cloud.media.has(s) for s in pics)
    assert cloud.db.blob(clip_sha) is not None
    assert cloud.sweep_record()["trimmed"] == 0  # over the cap still, with nothing left to trim


async def test_a_delete_the_disk_refused_is_tried_again_at_the_sweep(tmp_path, monkeypatch):
    from pathlib import Path

    app, client, sender, up, cloud = relay(tmp_path)
    a = await sign_up(client, sender, identifier="stuck@example.com")
    ha = {"Authorization": f"Bearer {a['api_key']}"}
    r = await client.put(f"/v1/blobs/{PNG_SHA}", headers={**ha, "Content-Type": "image/png"}, content=PNG_1PX)
    assert r.status_code == 200
    real_unlink = Path.unlink
    refused: list[str] = []

    def stuck_unlink(self, *args, **kwargs):
        if self.name == PNG_SHA and not refused:
            refused.append(self.name)
            raise PermissionError(13, "Permission denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", stuck_unlink)
    r = await client.delete("/v1/me/samples", headers=ha)
    assert r.status_code == 200 and r.json()["files"] == 0  # the row went, the file did not
    assert cloud.media.has(PNG_SHA) and cloud.db.blob(PNG_SHA) is None
    assert (cloud.media.root / MediaStore.RETRY_FILE).read_text().strip() == PNG_SHA
    assert cloud.sweep_record()["files"] == 1  # the sweep tries again and it goes
    assert not cloud.media.has(PNG_SHA) and not (cloud.media.root / MediaStore.RETRY_FILE).exists()
    assert cloud.media.retry_deletes() == 0


async def test_a_partial_turn_says_why_it_ended(tmp_path):
    app, client, sender, up, cloud = relay(tmp_path)
    a = await sign_up(client, sender, identifier="ended@example.com")
    ha = {"Authorization": f"Bearer {a['api_key']}"}
    turn = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        "response": {"message": {"role": "assistant", "content": "hel"}},
    }
    r = await client.post("/v1/turns", headers=ha, json={**turn, "id": "t1", "status": "partial", "ended": "aborted"})
    assert r.status_code == 201
    r = await client.post("/v1/turns", headers=ha, json={**turn, "id": "t2", "status": "partial", "ended": "Not A Word!"})
    assert r.status_code == 201
    r = await client.post("/v1/turns", headers=ha, json={**turn, "id": "t3", "status": "ok", "ended": "aborted"})
    assert r.status_code == 201
    turns = {t["id"].rsplit("-", 1)[-1]: t for t in (await client.get("/v1/turns", headers=ha)).json()["turns"]}
    assert turns["t1"]["status"] == "partial" and turns["t1"]["meta"]["ended"] == "aborted"
    assert turns["t2"]["status"] == "partial" and "ended" not in turns["t2"]["meta"]
    assert turns["t3"]["status"] == "ok" and "ended" not in turns["t3"]["meta"]
    assert "ended" not in turns["t1"]["request"] and "status" not in turns["t1"]["request"]


def test_pace_counts_within_a_sliding_window():
    from nanomuse_cloud.service import Pace

    t = [100.0]
    pace = Pace(2, 60.0, clock=lambda: t[0])
    assert pace.allow("a") and pace.allow("a") and not pace.allow("a")
    assert pace.allow("b")  # another key, its own count
    t[0] = 159.0
    assert not pace.allow("a")
    t[0] = 161.0
    assert pace.allow("a")  # the first two slid out of the window
    assert Pace(0, 60.0).allow("anyone")  # a limit of 0 is no limit
    # the table is bounded: a flood of keys does not grow it without end
    pace = Pace(1, 60.0, clock=lambda: t[0])
    pace.MAX_KEYS = 10
    for i in range(30):
        assert pace.allow(f"k{i}")
    assert len(pace._seen) <= 10
