from __future__ import annotations

import logging

import httpx
import pytest
from starlette.testclient import TestClient
from uvicorn.protocols.utils import get_path_with_query_string

from showcase_gateway import app as app_module
from showcase_gateway.config import Lane, Settings, text_only
from showcase_gateway.llm import extract_usage, pinned, prepare_body
from showcase_gateway.logs import RedactTokens, redact
from showcase_gateway.sessions import (
    Provider,
    Refused,
    Session,
    SessionManager,
    check_provider,
    resolve_provider,
)

from .conftest import FakeRunner, body, make_settings


async def client_for(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://localhost:8000")


async def test_a_visitor_gets_a_private_muse(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "1.2.3.4"})
        assert r.status_code == 201, r.text
        sess = body(r)
        assert sess["server_url"].startswith("http://") and sess["server_url"].endswith(
            ".s.localhost:8000"
        )
        assert sess["token"] and sess["ttl_s"] == 600 and sess["byok"] is False
        name = f"nm-{sess['id']}"
        env = runner.running[name]
        # the container's model lives behind this gateway, with a key of its own
        assert env["NANOMUSE_LLM_BASE_URL"] == f"http://10.0.0.1:8000/llm/{sess['id']}/main"
        assert env["NANOMUSE_GUI_BASE_URL"] == f"http://10.0.0.1:8000/llm/{sess['id']}/gui"
        assert env["NANOMUSE_LLM_API_KEY"] != settings.main.api_key
        assert env["NANOMUSE_SERVER_TOKEN"] == sess["token"]
        assert env["NANOMUSE_GUI_ENABLED"] == "1"
        # no account to sign in to: the web app opens on the chat, not the Cloud sign-in
        assert env["NANOMUSE_CLOUD_REQUIRED"] == "0"
        # the phone's traffic on the session host reaches the container
        host = sess["server_url"].split("//")[1]
        r = await c.get("/api/state?token=x", headers={"host": host})
        assert r.status_code == 200 and r.text == "container says /api/state"
        assert r.headers["x-upstream"] == "yes"
        # the phone itself (the site's origin) decides approvals and holds on the session
        # host: the browser's preflight is answered here, and the relayed answer is stamped
        # for that origin alone
        site = "http://localhost:8000"
        r = await c.options(
            "/api/approvals/ap_1",
            headers={
                "host": host,
                "origin": site,
                "access-control-request-method": "POST",
                "access-control-request-headers": "authorization,content-type",
            },
        )
        assert r.status_code == 204
        assert r.headers["access-control-allow-origin"] == site
        assert "authorization" in r.headers["access-control-allow-headers"].lower()
        assert "POST" in r.headers["access-control-allow-methods"]
        assert "PUT" in r.headers["access-control-allow-methods"]
        r = await c.post("/api/approvals/ap_1", json={}, headers={"host": host, "origin": site})
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == site
        # any other origin gets the runtime's answer as it is, with no such header
        r = await c.post(
            "/api/approvals/ap_1", json={}, headers={"host": host, "origin": "https://evil.example"}
        )
        assert r.status_code == 200 and "access-control-allow-origin" not in r.headers
        # one at a time per visitor
        r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "1.2.3.4"})
        assert r.status_code == 429 and body(r)["error"] == "already_running"
        # another visitor is fine
        r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "5.6.7.8"})
        assert r.status_code == 201
        # status needs the token; ending it stops the container
        r = await c.get(f"/api/demo/session/{sess['id']}")
        assert r.status_code == 404
        r = await c.get(
            f"/api/demo/session/{sess['id']}", headers={"authorization": f"Bearer {sess['token']}"}
        )
        assert r.status_code == 200 and body(r)["id"] == sess["id"]
        r = await c.delete(
            f"/api/demo/session/{sess['id']}", headers={"authorization": f"Bearer {sess['token']}"}
        )
        assert r.status_code == 204 and name in runner.stopped
        r = await c.get("/api/state", headers={"host": host})
        assert r.status_code == 404
        info = body(await c.get("/api/demo/info"))
        assert info["active_sessions"] == 1 and info["demo_model"] == "demo-model"


async def test_the_visitors_clock_reaches_the_container(world):
    """The page sends the browser's IANA zone; the container's TZ is set from it, so a
    reminder "in 2 minutes" is due in 2 minutes and the Muse quotes the visitor's time.
    Nothing sent, or a name that is not a zone's shape, leaves the container on UTC."""
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        r = await c.post(
            "/api/demo/session",
            json={"time_zone": "America/Argentina/Buenos_Aires"},
            headers={"x-forwarded-for": "1.2.3.4"},
        )
        assert r.status_code == 201, r.text
        assert runner.running[f"nm-{body(r)['id']}"]["TZ"] == "America/Argentina/Buenos_Aires"
        r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "5.6.7.8"})
        assert r.status_code == 201 and "TZ" not in runner.running[f"nm-{body(r)['id']}"]
        for bad in ("Asia/Shanghai; rm -rf /", "../etc", "x" * 65, "Europe/"):
            r = await c.post(
                "/api/demo/session", json={"time_zone": bad}, headers={"x-forwarded-for": "9.9.9.9"}
            )
            assert r.status_code == 422, bad


async def test_a_dead_container_is_logged_without_the_query(world, caplog):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "1.2.3.4"})
        sess = body(r)
        host = sess["server_url"].split("//")[1]

        upstream.down = True
        with caplog.at_level("INFO", logger="showcase.proxy"):
            r = await c.get("/?token=secret-token&ui=lite", headers={"host": host})
        upstream.down = False
        assert r.status_code == 502
        # the path is in the log; an older ?token= link's query is not
        lines = [rec.getMessage() for rec in caplog.records if "upstream" in rec.getMessage()]
        assert lines and all("/" in line and "secret-token" not in line for line in lines)


def uvicorn_request_lines(app):
    """``app`` behind the request lines uvicorn writes, formatted as uvicorn formats them
    (``uvicorn.protocols.http.*`` and ``uvicorn.protocols.websockets.*``): the path with the
    query string as it arrived, HTTP on ``uvicorn.access``, the upgrade on ``uvicorn.error``.
    The test client does not run uvicorn, so this stands in for it."""

    async def logged(scope, receive, send):
        if scope["type"] == "websocket":
            logging.getLogger("uvicorn.error").info(
                '%s - "WebSocket %s" [accepted]', "1.2.3.4:50000", get_path_with_query_string(scope)
            )
        elif scope["type"] == "http":
            logging.getLogger("uvicorn.access").info(
                '%s - "%s %s HTTP/%s" %d',
                "1.2.3.4:50000",
                scope["method"],
                get_path_with_query_string(scope),
                scope["http_version"],
                200,
            )
        await app(scope, receive, send)

    return logged


async def test_a_token_in_the_address_never_reaches_the_servers_log(world, monkeypatch, caplog):
    settings, runner, upstream, clock, manager, app = world
    relayed: list[str] = []

    async def fake_proxy_ws(ws, url, touch, label="", first=None, accepted=False):
        relayed.append(url)
        if not accepted:
            await ws.accept()
        await ws.close(code=1000)

    monkeypatch.setattr(app_module, "proxy_ws", fake_proxy_ws)
    with TestClient(uvicorn_request_lines(app)) as tc:
        sess = tc.post("/api/demo/session", json={}, headers={"x-forwarded-for": "1.2.3.4"}).json()
        token = sess["token"]
        host = sess["server_url"].split("//")[1]
        with caplog.at_level("INFO"):
            # an older page or app still sending the token the old way: the socket is served
            # (the runtime behind it says what it thinks of the form), the page is served
            with tc.websocket_connect(f"/ws?token={token}", headers={"host": host}) as ws:
                closed = ws.receive()
            assert closed["type"] == "websocket.close" and relayed
            r = tc.get(f"/?token={token}&ui=lite", headers={"host": host})
            assert r.status_code == 200
    lines = [rec.getMessage() for rec in caplog.records]
    assert any('"WebSocket /ws?token=[redacted]" [accepted]' in line for line in lines)
    assert any('"GET /?token=[redacted]&ui=lite HTTP/1.1" 200' in line for line in lines)
    # httpx names the whole URL of what the gateway relays to the container, at INFO
    assert any("http://10.0.0.2:8787/?token=[redacted]&ui=lite" in line for line in lines)
    # nothing anywhere, from any logger, carries the value
    assert token not in "\n".join(lines)


def test_the_filter_redacts_a_token_wherever_it_sits():
    assert redact("GET /?token=abc.def-ghi&ui=lite") == "GET /?token=[redacted]&ui=lite"
    assert redact('"WebSocket /ws?token=s3cret" [accepted]') == (
        '"WebSocket /ws?token=[redacted]" [accepted]'
    )
    assert redact("Token=UPPER done") == "Token=[redacted] done"
    assert redact("tokens=3 and a_token=x stay") == "tokens=3 and a_token=x stay"
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "%s %(path)s", None, None
    )
    record.args = {"path": "/ws?token=one"}
    assert RedactTokens().filter(record) and record.args == {"path": "/ws?token=[redacted]"}
    record.args = ("/ws?token=two", 200)
    RedactTokens().filter(record)
    assert record.args == ("/ws?token=[redacted]", 200)
    # httpx logs the URL as an object, not a string
    record.args = (httpx.URL("http://10.0.0.2:8787/?token=three&ui=lite"), 200)
    RedactTokens().filter(record)
    assert record.args == ("http://10.0.0.2:8787/?token=[redacted]&ui=lite", 200)


async def test_the_showcase_is_full_and_the_daily_count(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        for i in range(3):
            r = await c.post(
                "/api/demo/session", json={}, headers={"x-forwarded-for": f"9.9.9.{i}"}
            )
            assert r.status_code == 201
        r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "9.9.9.9"})
        assert r.status_code == 503 and body(r)["error"] == "full"
        # a visitor who starts and ends sessions all day hits the daily count
        for sid in list(manager.sessions):
            await manager.end(sid)
        for _ in range(2):
            r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "9.9.9.0"})
            assert r.status_code == 201
            await manager.end(body(r)["id"])
        r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "9.9.9.0"})
        assert r.status_code == 429 and body(r)["error"] == "daily_limit"


async def test_model_calls_are_metered(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        sess = body(await c.post("/api/demo/session", json={}))
        env = runner.running[f"nm-{sess['id']}"]
        key = env["NANOMUSE_LLM_API_KEY"]
        path = f"/llm/{sess['id']}/main/chat/completions"
        # wrong key
        r = await c.post(path, json={"model": "x"}, headers={"authorization": "Bearer nope"})
        assert r.status_code == 401
        # the demo key goes on, the container's key does not
        r = await c.post(path, json={"model": "x"}, headers={"authorization": f"Bearer {key}"})
        assert r.status_code == 200
        sent = upstream.calls[-1]
        assert sent.headers["authorization"] == "Bearer sk-demo"
        assert str(sent.url) == "https://models.example/chat/completions"
        # the gui lane has its own upstream
        r = await c.post(
            f"/llm/{sess['id']}/gui/chat/completions",
            json={"model": "x", "stream": True},
            headers={"authorization": f"Bearer {key}"},
        )
        assert r.status_code == 200
        sent = upstream.calls[-1]
        assert sent.headers["authorization"] == "Bearer sk-gui"
        assert str(sent.url) == "https://gui.example/chat/completions"
        assert b'"include_usage": true' in sent.content
        s = manager.get(sess["id"])
        assert s.requests == 2 and s.tokens == 20
        assert manager.day_requests == 2 and manager.day_tokens == 20
        # the third call is the last one allowed (3 per session), the fourth is refused
        upstream.stream = True
        r = await c.post(
            path, json={"model": "x", "stream": True}, headers={"authorization": f"Bearer {key}"}
        )
        assert r.status_code == 200 and "text/event-stream" in r.headers["content-type"]
        assert s.requests == 3 and s.tokens == 30
        r = await c.post(path, json={"model": "x"}, headers={"authorization": f"Bearer {key}"})
        assert r.status_code == 429
        assert body(r)["error"]["type"] == "session_budget"


async def test_bring_your_own_key(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        r = await c.post(
            "/api/demo/session",
            json={
                "provider": {
                    "base_url": "http://byok.example/v1",
                    "api_key": "sk-visitor-1",
                    "model": "m",
                }
            },
        )
        assert r.status_code == 400 and body(r)["error"] == "bad_provider"
        r = await c.post(
            "/api/demo/session",
            json={
                "provider": {
                    "base_url": "https://evil.example/v1",
                    "api_key": "sk-visitor-1",
                    "model": "m",
                }
            },
        )
        assert r.status_code == 400 and body(r)["error"] == "provider_not_allowed"
        r = await c.post(
            "/api/demo/session",
            json={
                "provider": {
                    "base_url": "https://byok.example/v1/",
                    "api_key": "sk-visitor-1",
                    "model": "m",
                }
            },
        )
        assert r.status_code == 201, r.text
        sess = body(r)
        assert sess["byok"] is True and sess["quota"]["requests"] is None
        env = runner.running[f"nm-{sess['id']}"]
        assert env["NANOMUSE_LLM_MODEL"] == "m" and env["NANOMUSE_GUI_MODEL"] == "m"
        # the visitor's key never reaches the container
        assert "sk-visitor-1" not in env.values()
        key = env["NANOMUSE_LLM_API_KEY"]
        for _ in range(5):  # no budget of ours applies
            r = await c.post(
                f"/llm/{sess['id']}/main/chat/completions",
                json={"model": "m"},
                headers={"authorization": f"Bearer {key}"},
            )
            assert r.status_code == 200
        sent = upstream.calls[-1]
        assert sent.headers["authorization"] == "Bearer sk-visitor-1"
        # pinned to the address the name resolved to when it was checked: the name only as
        # Host and SNI, so a later DNS answer pointing inside our network changes nothing
        assert str(sent.url) == "https://93.184.216.34/v1/chat/completions"
        assert sent.headers["host"] == "byok.example"
        assert sent.extensions["sni_hostname"] == "byok.example"
        assert manager.day_requests == 0


async def test_sessions_end_on_their_own(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        a = body(await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "1.1.1.1"}))
        b = body(await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "2.2.2.2"}))
        clock.now += 130  # past the idle limit, both untouched
        await c.get("/api/state", headers={"host": f"{b['id']}.s.localhost"})  # b is in use
        await manager.reap_once()
        assert manager.get(a["id"]) is None and f"nm-{a['id']}" in runner.stopped
        assert manager.get(b["id"]) is not None
        clock.now += 600  # past the session's whole lifetime
        await manager.reap_once()
        assert manager.get(b["id"]) is None


def test_check_provider_refuses_private_addresses():
    def resolve(host: str, port: int) -> list[str]:
        return {"models.example": ["93.184.216.34"], "inside.example": ["10.1.2.3"]}[host]

    with pytest.raises(Refused) as exc:
        check_provider("https://inside.example/v1", ("inside.example",), resolve)
    assert exc.value.code == "bad_provider"
    with pytest.raises(Refused) as exc:
        check_provider("https://models.example:8443/v1", ("models.example",), lambda h, p: [])
    assert exc.value.code == "bad_provider"
    assert (
        check_provider("https://models.example/v1/", ("models.example",), resolve)
        == "https://models.example/v1"
    )
    assert resolve_provider("https://models.example:8443/v1/", ("models.example",), resolve) == (
        "https://models.example:8443/v1",
        "models.example",
        ("93.184.216.34",),
    )
    assert pinned("https://models.example:8443/v1/chat", "93.184.216.34") == (
        "https://93.184.216.34:8443/v1/chat",
        "models.example",
    )
    assert pinned("https://models.example/v1", "2606:2800:220:1:248:1893:25c8:1946") == (
        "https://[2606:2800:220:1:248:1893:25c8:1946]/v1",
        "models.example",
    )


def test_usage_parsing():
    assert extract_usage(b'{"usage": {"prompt_tokens": 3, "completion_tokens": 4}}') == 7
    sse = b'data: {"x":1}\n\ndata: {"usage":{"total_tokens":42}}\n\ndata: [DONE]\n\n'
    assert extract_usage(sse) == 42
    responses = b'data: {"type":"response.completed","response":{"usage":{"input_tokens":5,"output_tokens":6}}}\n\n'
    assert extract_usage(responses) == 11
    assert extract_usage(b"nothing here") is None
    assert prepare_body(b'{"stream": false}', "chat/completions") == b'{"stream": false}'
    assert b"include_usage" in prepare_body(b'{"stream": true}', "v1/chat/completions")
    assert prepare_body(b'{"stream": true}', "responses") == b'{"stream": true}'


def test_which_deepseek_models_see():
    # the rule shared by every client (contract C4): DeepSeek is text-only before v4.1, and
    # anything whose id says vision or ocr sees
    assert text_only("deepseek-v4-pro")
    assert text_only("DeepSeek-V4-Flash")
    assert text_only("deepseek-v4")
    assert text_only("deepseek-chat") and text_only("deepseek-reasoner")
    assert not text_only("deepseek-v4.1-flash")
    assert not text_only("deepseek-v4.2-pro") and not text_only("deepseek-v5")
    assert not text_only("deepseek-vl-vision") and not text_only("deepseek-ocr")
    # every other family is taken as sighted (the runtime finds out for itself)
    assert not text_only("qwen3.8-27b") and not text_only("qwen3.5-plus")
    assert not text_only("")


def test_the_lanes_have_their_own_defaults(monkeypatch):
    # chat: deepseek-v4.1-flash; hands: qwen3.8-27b — the GUI model is a fixed default, not
    # the chat model, whatever the chat model is
    for name in ("MAIN_MODEL", "GUI_PROVIDER", "GUI_MODEL", "GUI_BASE_URL", "GUI_API_KEY"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("MAIN_BASE_URL", "https://llm.example/compatible-mode/v1")
    monkeypatch.setenv("MAIN_API_KEY", "sk-demo")
    s = Settings.from_env()
    assert s.main.model == "deepseek-v4.1-flash"
    assert s.gui.model == "qwen3.8-27b"
    monkeypatch.setenv("MAIN_MODEL", "qwen3.5-plus")
    assert Settings.from_env().gui.model == "qwen3.8-27b"


def test_empty_gui_lines_in_the_env_file_mean_the_default(monkeypatch):
    # .env.example ships GUI_PROVIDER= … GUI_API_KEY= empty; copied as they are, they used to
    # leave the operator lane without a model — the gateway answered 404 "no_lane" and every
    # phone task on the showcase failed at its first step
    monkeypatch.setenv("MAIN_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("MAIN_BASE_URL", "https://llm.example/compatible-mode/v1")
    monkeypatch.setenv("MAIN_API_KEY", "sk-demo")
    for name in ("GUI_PROVIDER", "GUI_MODEL", "GUI_BASE_URL", "GUI_API_KEY"):
        monkeypatch.setenv(name, "")
    gui = Settings.from_env().gui
    assert gui.configured
    assert gui.model == "qwen3.8-27b" and gui.provider == "openai"
    assert gui.base_url == "https://llm.example/compatible-mode/v1" and gui.api_key == "sk-demo"
    # a value set is taken as it is
    monkeypatch.setenv("GUI_MODEL", "qwen3-vl-plus")
    assert Settings.from_env().gui.model == "qwen3-vl-plus"


def test_a_visitors_own_provider_gets_its_own_gui_lane():
    # OpenRouter: the hands use qwen/qwen3.8-27b on the visitor's key, whatever they chat with
    p = Provider("https://openrouter.ai/api/v1", "sk-or", "deepseek/deepseek-v4.1-flash")
    assert p.gui_model == "qwen/qwen3.8-27b"
    assert p.lane("main").model == "deepseek/deepseek-v4.1-flash"
    assert p.lane("gui").model == "qwen/qwen3.8-27b" and p.lane("gui").api_key == "sk-or"
    # 阿里云百炼: qwen3.8-27b on the same key
    p = Provider("https://dashscope.aliyuncs.com/compatible-mode/v1", "sk-bl", "deepseek-v4-pro")
    assert p.gui_model == "qwen3.8-27b"
    # anywhere else, the one model does both
    p = Provider("https://api.deepseek.com/v1", "sk-ds", "deepseek-chat", host="api.deepseek.com")
    assert p.gui_model == "deepseek-chat"
    # …and that is what the container is started with
    runner = FakeRunner()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    manager = SessionManager(make_settings(), runner, http=client)
    sess = Session(
        id="abc",
        token="t",
        llm_key="k",
        ip="1.2.3.4",
        created_at=0.0,
        expires_at=1.0,
        container="nm-abc",
        byok=Provider("https://openrouter.ai/api/v1", "sk-or", "deepseek/deepseek-v4.1-flash"),
    )
    env = manager._env_for(sess)
    assert env["NANOMUSE_LLM_MODEL"] == "deepseek/deepseek-v4.1-flash"
    assert env["NANOMUSE_GUI_MODEL"] == "qwen/qwen3.8-27b"
    assert "NANOMUSE_LLM_VISION" not in env  # v4.1 sees
    assert manager.llm_lane(sess, "k", "gui").model == "qwen/qwen3.8-27b"
    assert manager.llm_lane(sess, "k", "main").model == "deepseek/deepseek-v4.1-flash"


def test_a_text_only_chat_model_is_kept_away_from_the_screenshots():
    # DeepSeek on Model Studio answers a message with a picture in it with an empty reply
    # rather than an error, so the runtime cannot find out by itself: the gateway says so
    runner = FakeRunner()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    blind = make_settings(main=Lane("openai", "deepseek-v4-pro", "https://m.example", "sk"))
    sess = Session(
        id="abc",
        token="t",
        llm_key="k",
        ip="1.2.3.4",
        created_at=0.0,
        expires_at=1.0,
        container="nm-abc",
    )
    env = SessionManager(blind, runner, http=client)._env_for(sess)
    assert env["NANOMUSE_LLM_VISION"] == "off"
    assert env["NANOMUSE_GUI_MODEL"] == "gui-model"  # the operator lane still looks
    sighted = make_settings(main=Lane("openai", "qwen3.5-plus", "https://m.example", "sk"))
    assert "NANOMUSE_LLM_VISION" not in SessionManager(sighted, runner, http=client)._env_for(sess)
    # DeepSeek V4.1 Flash reads pictures: the default chat model keeps its eyes
    flash = make_settings(main=Lane("openai", "deepseek-v4.1-flash", "https://m.example", "sk"))
    assert "NANOMUSE_LLM_VISION" not in SessionManager(flash, runner, http=client)._env_for(sess)
