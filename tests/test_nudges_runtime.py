"""The runtime's side of the star-ask policy (contract C1), the release check (C2) and the
feed's daily routine (C5). No request leaves the machine: every relay here is a mock
transport or a monkeypatched client."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from nanomuse import nudges
from nanomuse.config import Settings
from nanomuse.llm import MockLLM
from nanomuse.schema import LLMResponse
from nanomuse.server import create_app, update
from nanomuse.server.service import MuseService


# ----------------------------------------------------------------------------- nudges: the policy
def test_normalize_keeps_the_defaults_where_the_relay_makes_no_sense():
    assert nudges.normalize(None) == nudges.DEFAULT_NUDGES
    assert nudges.normalize([1, 2]) == nudges.DEFAULT_NUDGES
    odd = {
        "version": 7,
        "star": {
            "enabled": "yes",  # not a bool: the default stays
            "url": "ftp://nowhere",  # not http(s): the default stays
            "cooldown_days": 3,
            "max_asks": 999,  # out of range: the default stays
            "moments": {"tasks": [10, 3, 3, 1.0], "days_used": "7,30", "goal_done": False},
            "extra": 1,
        },
        "other": {},
    }
    out = nudges.normalize(odd)
    assert out["version"] == 7
    star = out["star"]
    assert star["enabled"] is True and star["url"] == nudges.DEFAULT_NUDGES["star"]["url"]
    assert star["cooldown_days"] == 3 and star["max_asks"] == 4
    assert star["moments"]["tasks"] == [1, 3, 10]  # distinct, sorted
    assert star["moments"]["days_used"] == [7, 30]  # a string is not a list: the default
    assert star["moments"]["goal_done"] is False and star["moments"]["signed_in"] is True
    assert "extra" not in star and "other" not in out
    assert star["text"] == "" and star["text_zh"] == ""


def test_normalize_keeps_the_star_cards_sentence_from_the_relay():
    """``star.text`` / ``star.text_zh`` (relay, this round): trimmed, kept up to 200
    characters, dropped beyond that or when they are not strings; empty by default."""
    out = nudges.normalize(
        {"star": {"text": "  A word from the relay.  ", "text_zh": "来自中继的一句话。"}}
    )
    assert out["star"]["text"] == "A word from the relay."
    assert out["star"]["text_zh"] == "来自中继的一句话。"
    long = nudges.normalize({"star": {"text": "x" * 201, "text_zh": ["no"]}})
    assert long["star"]["text"] == "" and long["star"]["text_zh"] == ""
    assert nudges.normalize({"star": {"text": "y" * 200}})["star"]["text"] == "y" * 200


def _relay(handler) -> httpx.AsyncClient:  # noqa: ANN001
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_policy_fetches_once_a_day_and_keeps_the_last_good_copy(tmp_path: Path):
    calls: list[str] = []
    answer = {"status": 200, "body": {"version": 3, "star": {"cooldown_days": 2, "max_asks": 9}}}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(answer["status"], json=answer["body"])

    now = [1_000_000.0]
    policy = nudges.NudgesPolicy(
        tmp_path, "https://relay.test/", client=_relay(handler), clock=lambda: now[0]
    )
    assert policy.view()["source"] == "default" and policy.view()["stale"] is True
    first = asyncio.run(policy.refresh())
    assert calls == ["/v1/nudges"]
    assert first["policy"]["version"] == 3 and first["policy"]["star"]["cooldown_days"] == 2
    assert first["policy"]["star"]["url"] == nudges.DEFAULT_NUDGES["star"]["url"]  # filled in
    assert first["source"] == "relay" and first["stale"] is False and first["error"] is None
    # within the day: no request
    now[0] += 3600
    asyncio.run(policy.refresh())
    assert len(calls) == 1
    # ``force`` asks now; a relay that fails leaves the copy and says so
    answer["status"] = 500
    forced = asyncio.run(policy.refresh(force=True))
    assert len(calls) == 2
    assert forced["policy"]["version"] == 3 and forced["error"] == "HTTPStatusError"
    # a day later the relay is asked again — and a failed try is not repeated before another day
    now[0] += nudges.REFRESH_S
    asyncio.run(policy.refresh())
    asyncio.run(policy.refresh())
    assert len(calls) == 3
    # the copy survives a restart (the file under the data dir), with when it came
    again = nudges.NudgesPolicy(tmp_path, "https://relay.test", clock=lambda: now[0])
    assert again.policy["version"] == 3 and again.source == "relay"
    assert again.fetched_at == pytest.approx(1_000_000.0)
    assert json.loads((tmp_path / "nudges.json").read_text("utf-8"))["policy"]["version"] == 3


def test_policy_takes_the_copy_that_rides_with_a_sign_in(tmp_path: Path):
    now = [5_000.0]
    policy = nudges.NudgesPolicy(tmp_path, "https://relay.test", clock=lambda: now[0])
    assert policy.take({"recent": []}) is False  # /v1/me of an older relay: no policy
    assert policy.take({"version": 2, "star": {"enabled": False}}) is True
    view = policy.view()
    assert view["policy"]["star"]["enabled"] is False and view["source"] == "me"
    assert view["stale"] is False and policy.due is False

    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no fetch is due after a sign-in copy")

    policy._client = _relay(never)
    asyncio.run(policy.refresh())


def test_policy_without_a_relay_or_with_an_old_one_stays_on_the_defaults(tmp_path: Path):
    def old_relay(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    policy = nudges.NudgesPolicy(tmp_path, "https://relay.test", client=_relay(old_relay))
    view = asyncio.run(policy.refresh())
    assert view["policy"] == nudges.DEFAULT_NUDGES and view["source"] == "default"
    assert view["error"] == "HTTPStatusError"
    none = nudges.NudgesPolicy(tmp_path / "other", "")
    assert asyncio.run(none.refresh())["policy"] == nudges.DEFAULT_NUDGES


# ----------------------------------------------------------------------------- nudges: the API
@pytest.fixture()
def server(settings: Settings):  # noqa: ANN201
    settings.server.token = "secret-token"
    llm = MockLLM([])
    service = MuseService(settings, llm=llm)
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        yield client, service, llm


def test_api_nudges_serves_the_policy_and_the_sign_in_copy(server, monkeypatch):
    client, service, _ = server
    calls = 0

    async def fake_refresh(force: bool = False) -> dict:
        nonlocal calls
        calls += 1
        service.nudges.force = force
        return service.nudges.view()

    monkeypatch.setattr(service.nudges, "refresh", fake_refresh)
    view = client.get("/api/nudges").json()
    assert view["policy"] == nudges.DEFAULT_NUDGES and view["source"] == "default"
    assert service.nudges.force is False
    client.get("/api/nudges?refresh=1")
    assert service.nudges.force is True and calls == 2
    assert TestClient(client.app).get("/api/nudges").status_code == 401

    # the account read carries the relay's policy: it becomes today's copy
    async def fake_me() -> dict:
        return {
            "id": "acct",
            "recent": [],
            "nudges": {"version": 5, "star": {"max_asks": 2}},
        }

    monkeypatch.setattr(service.hub, "me", fake_me)
    assert client.get("/api/cloud/me").json()["nudges"]["version"] == 5
    assert service.nudges.policy["version"] == 5 and service.nudges.policy["star"]["max_asks"] == 2
    assert service.nudges.source == "me"


# ----------------------------------------------------------------------------- release check
def test_release_check_asks_the_mirror_first_and_github_second(monkeypatch):
    asked: list[str] = []
    index = {
        "repo": "nano-muse/nanoMuse",
        "releases": [
            {"tag": "v0.1.40", "name": "0.1.40", "published_at": "2026-10-01", "assets": []},
            {"tag": "v0.1.39", "name": "0.1.39", "published_at": "2026-09-20", "assets": []},
        ],
    }
    mirror_ok = True

    class Client:
        def __init__(self, *a, **k): ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):  # noqa: ANN001
            asked.append(url)
            if url == update.INDEX_URL:
                assert kwargs["timeout"] == update.INDEX_TIMEOUT_S
                if not mirror_ok:
                    raise update.httpx.ConnectError("mirror down")
                return httpx.Response(200, json=index, request=httpx.Request("GET", url))
            return httpx.Response(
                200,
                json={
                    "tag_name": "v0.1.41",
                    "html_url": "https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.41",
                },
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(update.httpx, "AsyncClient", Client)
    monkeypatch.delenv("NANOMUSE_CLOUD_KEY", raising=False)
    monkeypatch.delenv("NANOMUSE_NO_UPDATE_CHECK", raising=False)

    check = update.UpdateCheck(True, current="0.1.35")
    view = asyncio.run(check.view())
    assert asked == [update.INDEX_URL]  # the mirror answered: GitHub is not asked
    assert view["latest"] == "0.1.40" and view["newer"] is True and view["source"] == "nanomuse.cn"
    assert view["url"].endswith("/releases/tag/v0.1.40")
    assert view["download_url"] == update.DOWNLOAD_PAGE
    assert view["checked_at"] and datetime.fromisoformat(view["checked_at"]).tzinfo is not None
    # the cache holds for a day; "check now" asks again
    asyncio.run(check.view())
    assert len(asked) == 1
    mirror_ok = False
    view = asyncio.run(check.view(force=True))
    assert asked[1:] == [update.INDEX_URL, update.RELEASES_API]
    assert view["latest"] == "0.1.41" and view["source"] == "github" and view["error"] is None
    assert update.latest_from_index({"releases": [{"tag": "nightly"}]}) == ""
    assert (
        update.latest_from_index({"releases": [{"tag": "v0.1.2"}, {"tag": "v0.1.10"}]}) == "v0.1.10"
    )


def test_api_update_check_now(server, monkeypatch):
    client, _, _ = server
    monkeypatch.delenv("NANOMUSE_CLOUD_KEY", raising=False)
    monkeypatch.delenv("NANOMUSE_NO_UPDATE_CHECK", raising=False)
    forced: list[bool] = []

    async def fake_view(self: update.UpdateCheck, force: bool = False) -> dict:
        forced.append(force)
        return {"current": self.current, "enabled": True, "latest": None, "newer": False}

    monkeypatch.setattr(update.UpdateCheck, "view", fake_view)
    client.get("/api/update")
    client.get("/api/update?refresh=1")
    assert forced == [False, True]


# ----------------------------------------------------------------------------- feed routine
def test_feed_routine_is_due_at_its_time_and_the_first_day_is_written_on_onboarding(server):
    client, service, llm = server
    service.set_feed_instructions("Short.")
    # written before today's (or yesterday's) scheduled time → due; after it → not
    scheduled = service.feed_scheduled_at()
    data = service.feed_posts()
    data["generated_at"] = (scheduled - timedelta(hours=5)).astimezone(UTC).isoformat()
    service._save_feed(data)
    assert service.feed_posts_due()
    data["generated_at"] = (scheduled + timedelta(minutes=1)).astimezone(UTC).isoformat()
    service._save_feed(data)
    assert not service.feed_posts_due()
    # a batch asked for by hand minutes ago is today's batch, even before the hour
    data["generated_at"] = datetime.now(UTC).isoformat()
    service._save_feed(data)
    assert not service.feed_posts_due()
    # the hour itself is honoured: "7:30" stored as "07:30", the scheduled moment has it
    service.set_feed_instructions(time="7:30")
    assert service.feed_scheduled_at().strftime("%H:%M") == "07:30"

    # the first run complete, a model there: the first feed day is written in the background
    service._save_feed({**service.feed_posts(), "posts": [], "generated_at": None})
    llm.script.append(
        LLMResponse(content='[{"title": "Day one", "body": "Hello.", "area": "planning"}]')
    )
    r = client.post("/api/onboarded", json={"done": True})
    assert r.json() == {"onboarded": True, "feed_started": True}
    for _ in range(100):
        if service.feed_posts()["posts"]:
            break
        time.sleep(0.05)
    assert [p["title"] for p in service.feed_posts()["posts"]] == ["Day one"]
    assert service.feed_posts()["generated_at"]
    # with posts there already, onboarding again writes nothing
    assert client.post("/api/onboarded", json={"done": True}).json()["feed_started"] is False
    # background: the main thread saw no turn (a C1 task is a person-started turn)
    main = service.threads["main"]
    assert not [e for e in main.timeline.events if e.get("type") in ("user", "assistant")]


def test_feed_routine_backs_off_after_a_failed_batch(server, monkeypatch):
    client, service, llm = server
    service.set_feed_instructions("Short.")
    assert service.feed_posts_due()
    attempts = 0

    async def boom(n: int = 3, *, scheduled: bool = False) -> dict:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("model down")

    monkeypatch.setattr(service, "write_feed_posts", boom)
    asyncio.run(service._run_feed_routine())
    asyncio.run(service._run_feed_routine())
    assert attempts == 1  # the next try is an hour later, not the next tick
    service._feed_failed_at = None
    asyncio.run(service._run_feed_routine())
    assert attempts == 2
