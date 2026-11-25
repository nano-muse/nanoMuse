"""0.31: where a turn came from (provenance.py) — the headers on a Cloud turn and the
fields on an uploaded one, own-key turns in the training view, what the apps report
around a turn (/v1/events), the export's pseudonym and the deletions ledger."""

from __future__ import annotations

import json
import time

import pytest
from test_cloud import sign_up
from test_record import ADMIN, relay, settled

from nanomuse_cloud import provenance
from nanomuse_cloud.client import ClientInfo, from_headers, platform_from

# -- the vocabulary, without a relay ---------------------------------------------------------


def test_the_fields_are_validated_one_by_one():
    got = provenance.from_headers(
        {
            "x-nanomuse-run": "Schedule",
            "x-nanomuse-turn": "3",
            "x-nanomuse-step": "2",
            "x-nanomuse-trajectory": "traj_01:abc",
            "x-nanomuse-trajectory-step": "7",
            "x-nanomuse-platform": "DESKTOP",
        }
    )
    assert got == {"run": "schedule", "turn": 3, "step": 2, "trajectory": "traj_01:abc", "trajectory_step": 7, "platform": "desktop"}
    # a value the relay cannot keep reads as not said, never as a guess
    bad = provenance.from_headers(
        {
            "x-nanomuse-run": "person typed",
            "x-nanomuse-turn": "-1",
            "x-nanomuse-step": "lots",
            "x-nanomuse-trajectory": "has space",
            "x-nanomuse-trajectory-step": "99999999999",
            "x-nanomuse-platform": "other",
        }
    )
    assert bad == provenance.EMPTY
    assert provenance.from_headers({}) == provenance.EMPTY
    # the body of an uploaded turn says first; a header fills in what it left out
    merged = provenance.from_body({"run": "feed", "turn": 2}, {"x-nanomuse-run": "person", "x-nanomuse-platform": "ios"})
    assert merged["run"] == "feed" and merged["turn"] == 2 and merged["platform"] == "ios"
    assert provenance.said(merged) == {"run": "feed", "turn": 2, "platform": "ios"}
    # a run word the relay has not met is kept as said (an app ahead of the relay), within the shape
    assert provenance.from_headers({"x-nanomuse-run": "replay_2"})["run"] == "replay_2"
    assert "minis" not in provenance.PLATFORM_CLAIMS and "other" not in provenance.PLATFORM_CLAIMS


def test_the_script_of_what_the_person_wrote():
    assert provenance.script_of("What is on my screen?") == "latin"
    assert provenance.script_of("帮我看看屏幕上有什么") == "zh"
    assert provenance.script_of("画面に何がありますか") == "ja"  # kana beside the Han characters
    assert provenance.script_of("화면에 뭐가 있어") == "ko"
    assert provenance.script_of("что на экране") == "ru"
    assert provenance.script_of("ما الذي على الشاشة") == "ar"
    assert provenance.script_of("อะไรอยู่บนหน้าจอ") == "th"
    assert provenance.script_of("123 😀 ...") == ""
    assert provenance.script_of("") == ""
    assert provenance.script_of("ok 好的 好的 好的") == "zh"  # the majority of letters decides
    assert provenance.last_user_text([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]) == "a"
    assert provenance.last_user_text([{"role": "user", "content": [{"type": "text", "text": "x"}, {"type": "image_url"}]}]) == "x"
    assert provenance.last_user_text("nope") == ""


def test_the_subject_is_stable_and_blind():
    a = provenance.subject_of("s", "acct-1")
    assert a == provenance.subject_of("s", "acct-1") and len(a) == 16 and a != provenance.subject_of("s", "acct-2")
    assert a != provenance.subject_of("other secret", "acct-1")


def test_client_events_are_codes_and_numbers_only():
    e = provenance.clean_event(
        {
            "kind": "sentinel.decision",
            "ts": 1792800000,
            "turn": "fa96b12265d54779",
            "conversation": "conv-1",
            "data": {
                "tool": "shell",
                "risk": "sensitive",
                "decision": "ask",
                "n": 2,
                "ok": True,
                "nested": {"a": 1},
                "list": [1],
                "Bad Key": "x",
            },
        }
    )
    assert e == {
        "kind": "sentinel.decision",
        "ts": 1792800000,
        "turn_id": "fa96b12265d54779",
        "conversation": "conv-1",
        "data": {"tool": "shell", "risk": "sensitive", "decision": "ask", "n": 2, "ok": True},
    }
    # a value that looks like prose is left out; a kind of the wrong shape, the whole event
    long = provenance.clean_event({"kind": "turn.feedback", "data": {"vote": "down", "note": "the model said " + "x" * 200}})
    assert long is not None and long["data"] == {"vote": "down"}
    assert provenance.clean_event({"kind": "Turn Feedback", "data": {}}) is None
    assert provenance.clean_event({"kind": "a.b.c.d.e", "data": {}}) is None
    assert provenance.clean_event("turn.feedback") is None
    assert provenance.clean_event({"kind": "app.opened"}) == {"kind": "app.opened", "ts": 0, "turn_id": "", "conversation": "", "data": {}}


def test_the_platform_claim_beats_the_user_agent_only_when_it_is_one_of_ours():
    info = from_headers({"user-agent": "node", "x-nanomuse-platform": "desktop"}, "127.0.0.1")
    assert info.platform == "desktop" and info.platform_hint == "desktop"
    assert from_headers({"user-agent": "node", "x-nanomuse-platform": "minis"}, "127.0.0.1").platform == "other"
    assert from_headers({"user-agent": "nanoMuse-Android/1.0.7"}, "127.0.0.1").platform == "android"
    assert ClientInfo(ua="nanoMuse-iOS/1.0.7", platform_hint="").platform == "ios"
    assert platform_from({"ua": "node", "platform": "desktop"}) == "desktop"
    assert platform_from({"ua": "node", "platform": "nonsense"}) == "other"
    assert platform_from({"ua": "nanoMuse/1.0.7 (iOS 26.1; iPhone)"}) == "ios"


# -- through the relay -----------------------------------------------------------------------


async def test_a_cloud_turn_carries_who_ran_it_into_the_record_the_training_view_and_the_calls(tmp_path):
    app, client, sender, up, cloud = relay(tmp_path)
    data = await sign_up(client, sender, identifier="prov-a@example.com")
    headers = {"Authorization": f"Bearer {data['api_key']}", "User-Agent": "nanoMuse-Android/1.0.8"}
    assert (await client.post("/v1/me/contribute", headers=headers, json={"on": True})).status_code == 200
    said = {
        "X-NanoMuse-Device": "pixel-1",
        "X-NanoMuse-Conversation": "conv-9",
        "X-NanoMuse-Run": "schedule",
        "X-NanoMuse-Turn": "4",
        "X-NanoMuse-Step": "2",
        "X-NanoMuse-Trajectory": "hands-01",
        "X-NanoMuse-Trajectory-Step": "3",
    }
    r = await client.post(
        "/v1/chat/completions",
        headers={**headers, **said},
        json={"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "打开设置里的蓝牙"}]},
    )
    assert r.status_code == 200
    request_id = r.headers["x-nanomuse-request"]
    # a streamed turn a person typed, with no headers but the run
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={**headers, "X-NanoMuse-Run": "person", "X-NanoMuse-Turn": "1"},
        json={"model": "qwen3.8-27b", "stream": True, "messages": [{"role": "user", "content": "hello there"}]},
    ) as s:
        await s.aread()
        streamed_id = s.headers["x-nanomuse-request"]
    await settled(app)

    # the record: the columns in the turn's own row, read back by the account and the operator
    mine = (await client.get("/v1/turns", headers=headers)).json()["turns"]
    by_id = {t["id"]: t for t in mine}
    t = by_id[request_id]
    assert (t["run"], t["turn"], t["step"], t["trajectory"], t["trajectory_step"], t["script"]) == ("schedule", 4, 2, "hands-01", 3, "zh")
    assert t["conversation"] == "conv-9" and t["platform"] == "android"
    st = by_id[streamed_id]
    assert st["run"] == "person" and st["turn"] == 1 and st["script"] == "latin" and "step" not in st and "trajectory" not in st
    admin_turn = (await client.get("/v1/admin/turns?conversation=conv-9", headers=ADMIN)).json()["turns"][0]
    assert admin_turn["run"] == "schedule" and admin_turn["trajectory"] == "hands-01"
    # the record's export carries the subject beside the account id
    lines = [json.loads(ln) for ln in (await client.get("/v1/admin/turns/export", headers=ADMIN)).text.splitlines() if ln]
    assert {ln["subject"] for ln in lines} == {cloud.subject_of(data["account"]["id"])} and all(ln["account_id"] for ln in lines)

    # the training view: the kept turn's meta says the same, names the record's turn, and the export's subject
    samples = (await client.get("/v1/admin/samples", headers=ADMIN)).json()["samples"]
    assert len(samples) == 2
    first = next(s for s in samples if s["meta"]["turn_id"] == request_id)
    assert first["meta"]["source"] == "cloud" and first["meta"]["run"] == "schedule" and first["meta"]["turn"] == 4
    assert first["meta"]["trajectory"] == "hands-01" and first["meta"]["trajectory_step"] == 3 and first["meta"]["script"] == "zh"
    assert first["meta"]["conversation"] == "conv-9" and "ip" in first["meta"]
    r = await client.get("/v1/admin/samples/export", headers=ADMIN)
    lines = [json.loads(ln) for ln in r.text.splitlines() if ln]
    assert all("account_id" not in ln and "ip" not in ln["meta"] for ln in lines)
    assert {ln["subject"] for ln in lines} == {cloud.subject_of(data["account"]["id"])}
    assert {ln["platform"] for ln in lines} == {"android"}
    # the shape rows beside them, for the quality page
    stats = cloud.db._conn.execute("SELECT run, source, turn_id FROM sample_stats ORDER BY ts").fetchall()
    assert sorted((r["run"], r["source"], r["turn_id"]) for r in stats) == sorted(
        [("schedule", "cloud", request_id), ("person", "cloud", streamed_id)]
    )
    # and the telemetry row
    calls = cloud.db._conn.execute("SELECT request_id, run FROM calls ORDER BY id").fetchall()
    assert {(r["request_id"], r["run"]) for r in calls} == {(request_id, "schedule"), (streamed_id, "person")}


async def test_an_own_key_turn_joins_the_training_view_when_the_switch_is_on(tmp_path):
    app, client, sender, up, cloud = relay(tmp_path)
    data = await sign_up(client, sender, identifier="prov-own@example.com")
    # the desktop's uploads go out from Node, whose user agent says nothing; the header does
    headers = {"Authorization": f"Bearer {data['api_key']}", "User-Agent": "node", "X-NanoMuse-Platform": "desktop"}
    turn = {
        "id": "t-1",
        "ts": 1792800000,
        "model": "gpt-5.6",
        "provider": "openai",
        "conversation": "conv-1",
        "run": "goal",
        "turn": 6,
        "step": 1,
        "messages": [
            {"role": "system", "content": "SOUL: the person's name is Ada"},
            {"role": "user", "content": "check whether the report went out"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "SECRET contents of the file"},
        ],
        "response": {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "send", "arguments": "{}"}}],
            },
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        },
    }
    # switch off: the record keeps the turn, the training view does not
    r = await client.post("/v1/turns", headers=headers, json=turn)
    assert r.status_code == 201, r.text
    assert (await client.get("/v1/admin/samples", headers=ADMIN)).json()["total"] == 0
    kept = (await client.get("/v1/admin/turns", headers=ADMIN)).json()["turns"][0]
    assert kept["source"] == "own" and kept["platform"] == "desktop" and kept["run"] == "goal" and kept["turn"] == 6 and kept["step"] == 1
    assert kept["script"] == "latin" and kept["meta"]["platform"] == "desktop"
    # the body's own fields do not land in the request the record keeps
    assert not ({"run", "turn", "step", "trajectory", "platform"} & set(kept["request"]))

    # switch on: the training view too, in the same shape as a Cloud turn's, never the system prompt or the tool's result
    assert (await client.post("/v1/me/contribute", headers=headers, json={"on": True})).status_code == 200
    r = await client.post("/v1/turns", headers=headers, json={**turn, "id": "t-2", "trajectory": "desk-7", "trajectory_step": 2})
    assert r.status_code == 201, r.text
    own_id = r.json()["id"]
    got = (await client.get("/v1/admin/samples", headers=ADMIN)).json()
    assert got["total"] == 1
    s = got["samples"][0]
    assert s["platform"] == "desktop" and s["model"] == "gpt-5.6"
    assert [m["role"] for m in s["request"]] == ["user", "assistant", "tool"]
    assert s["request"][2] == {"role": "tool", "tool_call_id": "c1", "content": "", "omitted": True}
    dumped = json.dumps(s, ensure_ascii=False)
    assert "SECRET" not in dumped and "Ada" not in dumped
    assert s["response"] == "" and s["meta"]["tool_calls"][0]["function"]["name"] == "send"  # a turn that only called a tool
    assert s["meta"]["source"] == "own" and s["meta"]["provider"] == "openai" and s["meta"]["turn_id"] == own_id
    assert (
        s["meta"]["run"] == "goal" and s["meta"]["turn"] == 6 and s["meta"]["trajectory"] == "desk-7" and s["meta"]["trajectory_step"] == 2
    )
    assert s["meta"]["platform"] == "desktop" and s["meta"]["script"] == "latin" and s["prompt_tokens"] == 12
    # the quality page's shape row says source and run too
    row = cloud.db._conn.execute("SELECT platform, run, source, turn_id FROM sample_stats").fetchone()
    assert tuple(row) == ("desktop", "goal", "own", own_id)
    # a partial own-key turn is in the record, not in the training view
    r = await client.post("/v1/turns", headers=headers, json={**turn, "id": "t-3", "status": "partial", "ended": "aborted"})
    assert r.status_code == 201 and (await client.get("/v1/admin/samples", headers=ADMIN)).json()["total"] == 1
    # /v1/me counts the sample like any other
    assert (await client.get("/v1/me", headers=headers)).json()["contribute"]["samples"] == 1


async def test_the_apps_reports_are_kept_tied_to_their_turns_and_deleted_with_the_data(tmp_path):
    app, client, sender, up, cloud = relay(tmp_path)
    data = await sign_up(client, sender, identifier="prov-ev@example.com")
    headers = {"Authorization": f"Bearer {data['api_key']}", "User-Agent": "nanoMuse-iOS/1.0.8", "X-NanoMuse-Device": "iphone-1"}
    acct8 = data["account"]["id"][:8]
    reported_at = int(time.time()) - 2
    approved_at = reported_at + 1
    events = [
        {
            "kind": "sentinel.decision",
            "ts": reported_at,
            "turn": "fa96b12265d54779",
            "conversation": "c1",
            "data": {"tool": "shell", "risk": "sensitive", "decision": "ask"},
        },
        {
            "kind": "approval.result",
            "ts": approved_at,
            "turn": "fa96b12265d54779",
            "data": {"tool": "shell", "allow": True, "scope": "once", "by": "person"},
        },
        {"kind": "turn.stopped", "turn": "t-9", "source": "own", "data": {"reason": "slow"}},
        {"kind": "turn.feedback", "turn": "fa96b12265d54779", "data": {"vote": "down", "reason": "wrong", "note": "it said " + "x" * 300}},
        {"kind": "not a kind", "data": {}},
        "garbage",
    ]
    r = await client.post("/v1/events", headers=headers, json={"events": events})
    assert r.status_code == 202 and r.json() == {"kept": 4, "dropped": 2}
    # the shapes the relay refuses outright
    assert (await client.post("/v1/events", headers=headers, json={"events": "x"})).status_code == 400
    assert (await client.post("/v1/events", headers=headers, json={"events": [{"kind": "app.opened"}] * 101})).status_code == 413

    got = (await client.get("/v1/admin/client-events", headers=ADMIN)).json()
    assert got["total"] == 4 and "turn.feedback" in got["kinds"]
    by_kind = {e["kind"]: e for e in got["events"]}
    assert by_kind["sentinel.decision"]["data"] == {"tool": "shell", "risk": "sensitive", "decision": "ask"}
    assert by_kind["sentinel.decision"]["ts"] == reported_at and by_kind["sentinel.decision"]["conversation"] == "c1"
    assert by_kind["sentinel.decision"]["platform"] == "ios" and by_kind["sentinel.decision"]["device"] == "iphone-1"
    assert by_kind["approval.result"]["data"]["allow"] is True
    assert by_kind["turn.stopped"]["turn_id"] == f"own-{acct8}-t-9" and by_kind["turn.stopped"]["ts"] > approved_at
    assert by_kind["turn.feedback"]["data"] == {"vote": "down", "reason": "wrong"}  # the prose never arrived
    assert all(e["account_id"] == data["account"]["id"] for e in got["events"])
    # by kind, and per account
    only = (await client.get("/v1/admin/client-events?kind=turn.feedback,turn.stopped", headers=ADMIN)).json()["events"]
    assert {e["kind"] for e in only} == {"turn.feedback", "turn.stopped"}
    assert (await client.get(f"/v1/admin/client-events?account_id={data['account']['id']}", headers=ADMIN)).json()["total"] == 4
    assert (await client.get("/v1/admin/client-events?account_id=nobody", headers=ADMIN)).json()["total"] == 0
    # the export: subject, no account id
    lines = [json.loads(ln) for ln in (await client.get("/v1/admin/client-events/export", headers=ADMIN)).text.splitlines() if ln]
    assert len(lines) == 4 and all("account_id" not in ln for ln in lines)
    assert {ln["subject"] for ln in lines} == {cloud.subject_of(data["account"]["id"])}
    # the summary: figures by kind and the split of each kind's codes
    summary = (await client.get("/v1/admin/client-events/summary?days=30", headers=ADMIN)).json()
    assert summary["total"] == 4 and summary["accounts"] == 1 and summary["kinds"]["sentinel.decision"] == 1
    assert summary["facets"]["sentinel.decision"] == {"decision": {"ask": 1}, "risk": {"sensitive": 1}}
    assert summary["facets"]["turn.feedback"] == {"vote": {"down": 1}, "reason": {"wrong": 1}}
    assert summary["facets"]["approval.result"]["allow"] == {"true": 1}
    assert len(summary["days"]) == 30 and sum(d.get("sentinel.decision", 0) for d in summary["days"]) == 1
    assert json.dumps(summary).count("xxxx") == 0

    # Data controls' delete takes the reports with the turns, and writes the ledger
    r = await client.delete("/v1/me/samples", headers=headers)
    assert r.status_code == 200
    assert (await client.get("/v1/admin/client-events", headers=ADMIN)).json()["total"] == 0
    ledger = (await client.get("/v1/admin/deletions", headers=ADMIN)).json()["deletions"]
    assert [(d["subject"], d["scope"]) for d in ledger] == [(cloud.subject_of(data["account"]["id"]), "samples")]
    assert (await client.get(f"/v1/admin/deletions?since={ledger[0]['ts'] + 1}", headers=ADMIN)).json()["deletions"] == []


async def test_deleting_the_account_leaves_only_the_ledger_line(tmp_path):
    app, client, sender, up, cloud = relay(tmp_path)
    data = await sign_up(client, sender, identifier="prov-del@example.com")
    headers = {"Authorization": f"Bearer {data['api_key']}", "User-Agent": "nanoMuse-Android/1.0.8"}
    subject = cloud.subject_of(data["account"]["id"])
    await client.post("/v1/events", headers=headers, json={"events": [{"kind": "app.opened", "data": {}}]})
    assert (await client.get("/v1/admin/client-events", headers=ADMIN)).json()["total"] == 1
    r = await client.post("/v1/auth/delete", headers=headers)
    assert r.status_code == 204, r.text
    assert (await client.get("/v1/admin/client-events", headers=ADMIN)).json()["total"] == 0
    ledger = (await client.get("/v1/admin/deletions", headers=ADMIN)).json()["deletions"]
    assert [(d["subject"], d["scope"]) for d in ledger] == [(subject, "account")]
    # nothing else of the account is left to name it; the pseudonym is not the id
    assert data["account"]["id"] not in subject and len(subject) == 16


async def test_events_are_paced_per_account(tmp_path):
    app, client, sender, up, cloud = relay(tmp_path)
    data = await sign_up(client, sender, identifier="prov-pace@example.com")
    headers = {"Authorization": f"Bearer {data['api_key']}", "User-Agent": "nanoMuse-Android/1.0.8"}
    cloud.event_pace = replace_limit(cloud.event_pace, 2)
    for _ in range(2):
        assert (await client.post("/v1/events", headers=headers, json={"events": [{"kind": "app.opened"}]})).status_code == 202
    r = await client.post("/v1/events", headers=headers, json={"events": [{"kind": "app.opened"}]})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


def replace_limit(pace, limit):
    pace.limit = limit
    return pace


@pytest.mark.parametrize("word", ["hub", "feed", "goal", "person", "schedule"])
def test_every_known_run_word_passes(word):
    assert provenance.from_headers({"x-nanomuse-run": word})["run"] == word and word in provenance.KNOWN_RUNS
