"""nanoMuse Web: sign in with a code, get a kept Muse, come back to it."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import replace

import httpx
import pytest
from starlette.testclient import TestClient

from showcase_gateway.accounts import AccountManager, AccountStore
from showcase_gateway.app import create_app
from showcase_gateway.sessions import SessionManager
from showcase_gateway.trials import TrialManager, TrialStore

from .conftest import Clock, FakeRunner, Upstream, body, make_settings


@pytest.fixture
def web():
    settings = make_settings()
    runner = FakeRunner()
    upstream = Upstream()
    clock = Clock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler))
    manager = SessionManager(settings, runner, http=client, clock=clock)
    trials = TrialManager(settings, TrialStore(":memory:"), clock=clock)
    accounts = AccountManager(settings, runner, AccountStore(":memory:"), http=client, clock=clock)
    app = create_app(settings, manager, client=client, trials=trials, accounts=accounts)
    return settings, runner, upstream, clock, accounts, app


async def client_for(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://localhost:8000")


async def sign_in(c, ident: str, ip: str = "1.2.3.4"):
    r = await c.post("/api/web/code", json={"identifier": ident}, headers={"x-forwarded-for": ip})
    assert r.status_code == 204, r.text
    return await c.post(
        "/api/web/verify",
        json={"identifier": ident, "code": "246810"},
        headers={"x-forwarded-for": ip},
    )


async def test_the_page_and_a_first_sign_in(web):
    settings, runner, upstream, clock, accounts, app = web
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        r = await c.get("/web/")
        assert r.status_code == 200 and "nanoMuse Web" in r.text and "/api/web/verify" in r.text
        r = await c.get("/web", follow_redirects=False)
        assert r.status_code == 308 and r.headers["location"] == "/web/"

        # a wrong code is the relay's message, passed on
        r = await c.post("/api/web/code", json={"identifier": "someone@example.com"})
        assert r.status_code == 204
        r = await c.post(
            "/api/web/verify", json={"identifier": "someone@example.com", "code": "000000"}
        )
        assert r.status_code == 400 and body(r)["error"] == "code_wrong"

        r = await sign_in(c, "someone@example.com")
        assert r.status_code == 200, r.text
        assert upstream.invites[-1] == ""  # none given, none sent
        me = body(r)
        token = me["url"].split("token=")[1]
        assert me["slug"].startswith("w") and len(me["slug"]) == 12
        assert me["url"] == f"http://{me['slug']}.s.localhost:8000/#token={token}"
        assert me["running"] is True and me["channel"] == "email"
        # the relay saw the visitor's address, not the gateway's
        code_calls = [x for x in upstream.calls if x.url.path == "/v1/auth/code"]
        assert code_calls[-1].headers["x-forwarded-for"] == "1.2.3.4"
        # the container: kept, on the web network, signed in with a key of the account's that
        # lapses on its own; the standing key the relay issued is signed out again, and the
        # gateway's store holds no key at all
        kept = runner.kept[f"nmw-{me['slug']}"]
        env = kept["env"]
        assert env["NANOMUSE_CLOUD_KEY"] == "nm_sess1"
        assert upstream.revoked == ["nm_key1"]
        session_key_call = [x for x in upstream.calls if x.url.path == "/v1/auth/session-key"][-1]
        assert json.loads(session_key_call.content) == {"device": "Web", "ttl_s": 7 * 86400}
        assert [r[0] for r in accounts.store.db.execute("SELECT key FROM accounts")] == [""]
        assert accounts.live[me["slug"]].key == ""
        assert env["NANOMUSE_CLOUD_BASE_URL"] == "http://relay:8787"
        assert env["NANOMUSE_HUB_NAME"] == "Web" and env["NANOMUSE_ONBOARDED"] == "1"
        assert "NANOMUSE_HUB_DEVICE_ID" not in env and "NANOMUSE_HUB_KIND" not in env
        assert env["NANOMUSE_SERVER_TOKEN"] == token
        assert "NANOMUSE_LLM_BASE_URL" not in env  # the runtime makes the Cloud its model itself
        assert kept["network"] == "web-net" and kept["image"] == "nanomuse:web"
        assert set(kept["volumes"].values()) == {"/data", "/workspace", "/home/muse"}
        # and the browser's traffic on the account host reaches it
        host = me["origin"].split("//")[1]
        r = await c.get("/api/state", headers={"host": host})
        assert r.status_code == 200 and r.text == "container says /api/state"
        info = body(await c.get("/api/demo/info"))
        assert info["web"] == {
            "enabled": True,
            "accounts": 1,
            "running": 1,
            "max_accounts": 2,
            "max_running": 1,
        }


async def test_coming_back_wakes_the_same_muse(web):
    settings, runner, upstream, clock, accounts, app = web
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        me = body(await sign_in(c, "someone@example.com"))
        name = f"nmw-{me['slug']}"
        host = me["origin"].split("//")[1]

        # quiet for long enough: the container is stopped, not removed
        clock.now += settings.web_idle_stop_s + 1
        await accounts.reap_once()
        assert runner.kept[name]["running"] is False and name in runner.kept
        assert accounts.stats()["running"] == 0

        # a request on its host without the token does not wake it: a browser with only the
        # address gets the wake page, an API call a 503 to retry
        r = await c.get("/", headers={"host": host, "accept": "text/html"})
        assert r.status_code == 200 and "/__wake" in r.text and "Waking" in r.text
        assert "http://localhost:8000/web/" in r.text  # where to sign in again
        r = await c.get("/api/state", headers={"host": host})
        assert r.status_code == 503 and body(r)["error"] == "asleep"
        assert r.headers["retry-after"] == "3"
        assert runner.kept[name]["running"] is False and runner.kept[name]["starts"] == 1
        # a wrong token neither
        r = await c.post("/__wake", headers={"host": host, "authorization": "Bearer nope"})
        assert r.status_code == 401 and body(r)["error"] == "token"
        assert runner.kept[name]["running"] is False

        # the account's token wakes it — same slug, same token, same volumes
        token = me["url"].split("token=")[1]
        r = await c.post("/__wake", headers={"host": host, "authorization": f"Bearer {token}"})
        assert r.status_code == 204 and runner.kept[name]["running"] is True
        assert runner.kept[name]["starts"] == 2
        r = await c.get("/api/state", headers={"host": host})
        assert r.status_code == 200 and r.text == "container says /api/state"

        # asleep again: a bearer request, a signed link (the runtime's tickets) and the legacy
        # ?token= each prove the token too
        clock.now += settings.web_idle_stop_s + 1
        await accounts.reap_once()
        r = await c.get("/api/state", headers={"host": host, "authorization": f"Bearer {token}"})
        assert r.status_code == 200 and runner.kept[name]["starts"] == 3
        clock.now += settings.web_idle_stop_s + 1
        await accounts.reap_once()
        path = "/api/files/out/a.png"
        exp = int(time.time()) + 3600
        sig = hmac.new(token.encode(), f"{exp}\n{path}".encode(), hashlib.sha256).hexdigest()[:32]
        r = await c.get(f"{path}?exp={exp}&sig={sig}", headers={"host": host})
        assert r.status_code == 200 and runner.kept[name]["starts"] == 4
        clock.now += settings.web_idle_stop_s + 1
        await accounts.reap_once()
        r = await c.get(
            f"{path}?exp={exp}&sig=badbadbadbadbadbadbadbadbadbadba", headers={"host": host}
        )
        assert r.status_code == 503 and runner.kept[name]["starts"] == 4
        r = await c.get(f"/api/state?token={token}", headers={"host": host})
        assert r.status_code == 200 and runner.kept[name]["starts"] == 5

        # signing in again from another browser: the relay issues a fresh key, so the
        # container is recreated with it; slug and token stay
        again = body(await sign_in(c, "someone@example.com", ip="9.9.9.9"))
        assert again["slug"] == me["slug"] and again["url"] == me["url"]
        assert runner.kept[name]["env"]["NANOMUSE_CLOUD_KEY"] == "nm_sess2"
        assert runner.kept[name]["starts"] == 1  # a new container
        assert upstream.revoked == ["nm_key1", "nm_key2"]


async def test_a_lapsed_key_means_signing_in_again(web):
    """The key a container was started with runs out (WEB_KEY_TTL_S): the Muse is not woken
    on it — the person signs in again and gets a new container with a fresh key, over the
    same volumes."""
    settings, runner, upstream, clock, accounts, app = web
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        me = body(await sign_in(c, "someone@example.com"))
        name = f"nmw-{me['slug']}"
        host = me["origin"].split("//")[1]
        token = me["url"].split("token=")[1]
        stored = accounts.store.by_slug(me["slug"])
        assert stored is not None and stored.key_expires_at > time.time() + 6 * 86400
        # asleep, and the key's time has passed
        clock.now += settings.web_idle_stop_s + 1
        await accounts.reap_once()
        accounts.store.db.execute("UPDATE accounts SET key_expires_at = ?", (clock.now - 1,))
        accounts.store.db.commit()
        r = await c.post("/__wake", headers={"host": host, "authorization": f"Bearer {token}"})
        assert r.status_code == 401 and body(r)["error"] == "sign_in_again"
        assert runner.kept[name]["running"] is False
        # the container gone altogether (an operator's docker rm) and no key at hand: the same
        await runner.remove(name)
        accounts.store.db.execute("UPDATE accounts SET key_expires_at = 0")
        accounts.store.db.commit()
        r = await c.post("/__wake", headers={"host": host, "authorization": f"Bearer {token}"})
        assert r.status_code == 401 and body(r)["error"] == "sign_in_again"
        # signing in again: a new container, the same slug and token
        again = body(await sign_in(c, "someone@example.com"))
        assert again["slug"] == me["slug"] and again["url"] == me["url"]
        assert runner.kept[name]["env"]["NANOMUSE_CLOUD_KEY"] == "nm_sess2"


def test_the_socket_s_first_frame_wakes_a_slept_muse(web, monkeypatch):
    """The web app opens its socket without the token in the address and sends it in the
    first frame; a slept Muse is woken on that frame and the frame goes on to the runtime."""
    import showcase_gateway.app as app_module

    settings, runner, upstream, clock, accounts, app = web
    relayed: list[dict] = []

    async def fake_proxy_ws(ws, url, on_activity, label="", first=None, accepted=False):
        relayed.append({"url": url, "first": first, "accepted": accepted})
        if not accepted:
            await ws.accept()
        await ws.close(code=1000)

    monkeypatch.setattr(app_module, "proxy_ws", fake_proxy_ws)
    with TestClient(app) as tc:
        r = tc.post("/api/web/code", json={"identifier": "someone@example.com"})
        assert r.status_code == 204
        me = tc.post(
            "/api/web/verify", json={"identifier": "someone@example.com", "code": "246810"}
        ).json()
        name = f"nmw-{me['slug']}"
        host = me["origin"].split("//")[1]
        token = me["url"].split("token=")[1]
        clock.now += settings.web_idle_stop_s + 1
        assert tc.portal is not None  # open while the client is entered
        tc.portal.call(accounts.reap_once)
        assert runner.kept[name]["running"] is False

        # no token, or a wrong one: 4404, nothing starts
        with tc.websocket_connect("/ws", headers={"host": host}) as ws:
            ws.send_text(json.dumps({"kind": "hello"}))
            closed = ws.receive()
        assert closed["type"] == "websocket.close" and closed["code"] == 4404
        with tc.websocket_connect("/ws", headers={"host": host}) as ws:
            ws.send_text(json.dumps({"kind": "auth", "token": "nope"}))
            closed = ws.receive()
        assert closed["code"] == 4404
        assert runner.kept[name]["running"] is False and relayed == []

        # the account's token in the first frame: woken, and the frame travels on
        frame = json.dumps({"kind": "auth", "token": token})
        with tc.websocket_connect("/ws", headers={"host": host}) as ws:
            ws.send_text(frame)
            closed = ws.receive()
        assert closed["type"] == "websocket.close" and closed["code"] == 1000
        assert runner.kept[name]["running"] is True and runner.kept[name]["starts"] == 2
        assert relayed == [{"url": "ws://10.0.1.1:8787/ws", "first": frame, "accepted": True}]

        # up already: relayed straight away, the runtime does its own first-frame check
        with tc.websocket_connect("/ws", headers={"host": host}) as ws:
            closed = ws.receive()
        assert relayed[-1] == {"url": "ws://10.0.1.1:8787/ws", "first": None, "accepted": False}


async def test_a_restarted_gateway_finds_the_running_muses(web):
    settings, runner, upstream, clock, accounts, app = web
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        me = body(await sign_in(c, "someone@example.com"))
    # a new gateway process over the same store and runner
    fresh = AccountManager(settings, runner, accounts.store, http=accounts.http, clock=clock)
    await fresh.startup()
    assert fresh.stats()["running"] == 1
    live = fresh.live[me["slug"]]
    assert live.address == "10.0.1.1" and live.token == me["url"].split("token=")[1]


async def test_the_caps(web):
    settings, runner, upstream, clock, accounts, app = web
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        first = body(await sign_in(c, "a@example.com"))
        # one running at a time (web_max_running=1): a second account's Muse needs the first
        # to have been quiet for a while
        r = await sign_in(c, "b@example.com", ip="2.2.2.2")
        assert r.status_code == 503 and body(r)["error"] == "web_busy"
        clock.now += 600
        r = await sign_in(c, "b@example.com", ip="2.2.2.2")
        assert r.status_code == 200, r.text
        assert runner.kept[f"nmw-{first['slug']}"]["running"] is False
        # and no more than two accounts here
        clock.now += 600
        r = await sign_in(c, "c@example.com", ip="3.3.3.3")
        assert r.status_code == 503 and body(r)["error"] == "web_full"
        # an unknown host is still "ended"
        r = await c.get("/api/state", headers={"host": "wnotanaccount.s.localhost:8000"})
        assert r.status_code == 404


async def test_switched_off(web):
    settings, runner, upstream, clock, accounts, app = web
    off = replace(settings, web_enabled=False)
    manager = SessionManager(off, runner, http=accounts.http, clock=clock)
    app = create_app(off, manager, client=accounts.http)
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        # the web entry is then the phone in the browser: the showcase site
        r = await c.get("/web/")
        assert r.status_code == 302 and r.headers["location"] == "http://localhost:8000/"
        r = await c.post("/api/web/code", json={"identifier": "a@example.com"})
        assert r.status_code == 404 and body(r)["error"] == "web_off"


async def test_an_invite_code_is_passed_on_to_the_relay(web):
    settings, runner, upstream, clock, accounts, app = web
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        r = await c.get("/web/?invite=abcd2345")
        assert r.status_code == 200 and 'id="invite"' in r.text
        assert "¥" not in r.text  # no amounts on the way in; the account page has them
        assert "Mainland China phone number or e-mail" in r.text and "/api/web/login" in r.text
        assert "phone_region" in r.text  # the relay's refusal of an overseas number, in Chinese too
        r = await c.post("/api/web/code", json={"identifier": "invited@example.com"})
        assert r.status_code == 204
        r = await c.post(
            "/api/web/verify",
            json={"identifier": "invited@example.com", "code": "246810", "invite": "ABCD2345"},
        )
        assert r.status_code == 200, r.text
        assert upstream.invites[-1] == "ABCD2345"
        r = await c.post(
            "/api/web/verify",
            json={"identifier": "invited@example.com", "code": "246810", "invite": "x" * 33},
        )
        assert r.status_code == 422


async def test_the_password_way_in(web):
    settings, runner, upstream, clock, accounts, app = web
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        # the relay's refusals are passed on: no password yet, wrong password
        r = await c.post("/api/web/login", json={"identifier": "13800138000", "password": "x"})
        assert r.status_code == 400 and body(r)["error"] == "no_password"
        r = await c.post(
            "/api/web/login", json={"identifier": "someone@example.com", "password": "nope"}
        )
        assert r.status_code == 400 and body(r)["error"] == "password_wrong"
        r = await c.post(
            "/api/web/login", json={"identifier": "someone@example.com", "password": ""}
        )
        assert r.status_code == 422

        r = await c.post(
            "/api/web/login",
            json={"identifier": "someone@example.com", "password": "correct horse"},
        )
        assert r.status_code == 200, r.text
        me = body(r)
        assert me["slug"].startswith("w") and "token=" in me["url"]
        assert upstream.calls[-1].url.path != "/v1/auth/code"  # no code was asked for
        # the same account by code lands on the same Muse
        r2 = await sign_in(c, "someone@example.com")
        assert body(r2)["slug"] == me["slug"]
