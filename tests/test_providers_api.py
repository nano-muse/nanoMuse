"""``GET /api/providers`` and the ChatGPT sign-in over HTTP (``/api/chatgpt/*``).

The sign-in is run end to end against stubs: the callback port is not bound (the paste
fallback carries the callback), or bound on an ephemeral port a fake browser calls; the token
exchange is an ``httpx.MockTransport``. Nothing reaches OpenAI.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from nanomuse.config import MediaSettings, Settings
from nanomuse.llm import MockLLM
from nanomuse.llm.chatgpt import LoginFlow, TokenStore
from nanomuse.server import create_app
from nanomuse.server.service import MuseService
from tests.test_chatgpt import TOKEN_URL, jwt, token
from tests.test_server import wait_for


def _make(settings: Settings) -> tuple[TestClient, MuseService]:
    settings.server.token = "secret-token"
    service = MuseService(settings, llm=MockLLM([]))
    app = create_app(settings, service)
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer secret-token"
    return client, service


@pytest.fixture()
def server(settings: Settings) -> Iterator[tuple[TestClient, MuseService]]:
    client, service = _make(settings)
    with client:
        yield client, service


def _exchange(request: httpx.Request) -> httpx.Response:
    assert str(request.url) == TOKEN_URL
    form = dict(p.split("=", 1) for p in request.content.decode().split("&"))
    assert form["grant_type"] == "authorization_code" and form["code"] == "abc"
    return httpx.Response(
        200, json={"access_token": jwt(), "refresh_token": "rt", "expires_in": 3600}
    )


def _stub_login(
    service: MuseService, monkeypatch: pytest.MonkeyPatch, bind: bool = False
) -> list[str]:
    """The flow against fakes: the token endpoint is a mock transport; without ``bind`` the
    callback port is not opened (the paste fallback carries the callback). Returns the
    ports bound, for the fake browser."""
    ports: list[str] = []
    service.chatgpt.http = httpx.AsyncClient(transport=httpx.MockTransport(_exchange))
    service.chatgpt.token_url = TOKEN_URL
    if bind:
        service.chatgpt.port = 0

        original_listen = LoginFlow.listen

        async def listen(self: LoginFlow) -> bool:
            ok = await original_listen(self)
            if ok and self._server is not None:
                ports.append(str(self._server.sockets[0].getsockname()[1]))
            return ok

        monkeypatch.setattr(LoginFlow, "listen", listen)
    else:

        async def no_port(self: LoginFlow) -> bool:
            self._result = asyncio.get_running_loop().create_future()
            return False

        monkeypatch.setattr(LoginFlow, "listen", no_port)
    return ports


# ----------------------------------------------------------------------------- providers
def test_providers_signed_out_with_the_default_model(server):
    client, service = server
    assert TestClient(client.app).get("/api/providers").status_code == 401
    view = client.get("/api/providers").json()
    assert view["region"] == ""
    ids = [p["id"] for p in view["providers"]]
    assert len(ids) == 20 and "nanomuse_cloud" not in ids
    # DeepSeek is the default chat model, by its host; the hands follow the chat model
    assert view["configured"]["chat"]["provider"] == "deepseek"
    assert view["configured"]["chat"]["protocol"] == "openai"
    assert view["configured"]["chat"]["source"] == "config"
    assert view["configured"]["hands"]["provider"] == "deepseek"
    assert view["configured"]["image"] is None and view["configured"]["video"] is None
    deepseek = next(p for p in view["providers"] if p["id"] == "deepseek")
    assert deepseek["configured"] == ["chat", "hands"] and deepseek["signed_in"] is False
    assert "key_url" in deepseek and "capabilities" in deepseek  # the catalogue's keys
    assert view["capabilities"] == ["chat", "vision"]
    assert view["unavailable"]["chat"] == "" and view["unavailable"]["vision"] == ""
    assert view["unavailable"]["image"].startswith("Pictures need a provider with image models")
    assert view["unavailable"]["video"].startswith("Clips need a provider with video models")
    assert view["chatgpt"] == {"signed_in": False, "label": "", "capabilities": ["chat", "vision"]}
    # the language and the region of the sentence
    zh = client.get("/api/providers?lang=zh&region=cn").json()
    assert zh["region"] == "cn"
    assert zh["unavailable"]["image"].startswith("生成图片需要有图像模型的服务商：阿里云百炼")
    en_cn = client.get("/api/providers?region=cn").json()["unavailable"]["image"]
    assert "Alibaba Cloud Bailian" in en_cn and "OpenRouter" not in en_cn


def test_providers_with_an_image_slot(settings: Settings):
    settings.image = MediaSettings(provider="bailian", api_key="sk-test")
    client, service = _make(settings)
    with client:
        view = client.get("/api/providers").json()
    assert "image" in view["capabilities"] and "video" in view["capabilities"]
    assert view["unavailable"]["image"] == "" and view["unavailable"]["video"] == ""
    image = view["configured"]["image"]
    assert image["provider"] == "bailian" and image["model"] == "qwen-image-3.0"
    assert image["source"] == "config"
    assert view["configured"]["video"]["provider"] == "bailian"
    bailian = next(p for p in view["providers"] if p["id"] == "bailian")
    assert bailian["configured"] == ["image", "video"]
    # the key never travels
    assert "sk-test" not in json.dumps(view)


def test_providers_follow_the_agents_language(settings: Settings):
    settings.agent.language = "中文"
    client, service = _make(settings)
    with client:
        view = client.get("/api/providers").json()
    assert view["unavailable"]["image"].startswith("生成图片")


# ----------------------------------------------------------------------------- chatgpt
def test_chatgpt_status_and_logout_signed_out(server):
    client, service = server
    status = client.get("/api/chatgpt/status").json()
    assert status["signed_in"] is False and status["pending"] is False
    assert status["models"] == ["gpt-5.6-sol", "gpt-5.4", "gpt-5.4-mini"]
    assert "url" not in status and "error" not in status
    assert client.post("/api/chatgpt/logout").json() == {"ok": True, "was_signed_in": False}
    # a callback with nothing pending
    r = client.post(
        "/api/chatgpt/callback", json={"url": "http://localhost:1455/auth/callback?code=x&state=y"}
    )
    assert r.status_code == 409 and "no_login" in r.json()["detail"]


def test_chatgpt_status_with_a_store_never_shows_the_tokens(server):
    client, service = server
    TokenStore.in_dir(service.data_dir).save(token())
    status = client.get("/api/chatgpt/status").json()
    assert status["signed_in"] is True and status["label"] == "ChatGPT Plus"
    assert status["plan"] == "plus" and status["account_id"] == "acct-1"
    assert 3500 < status["expires_in"] <= 3600
    assert jwt() not in json.dumps(status) and "rt-a" not in json.dumps(status)
    view = client.get("/api/providers").json()
    assert view["chatgpt"] == {
        "signed_in": True,
        "label": "ChatGPT Plus",
        "capabilities": ["chat", "vision"],
    }
    assert next(p for p in view["providers"] if p["id"] == "openai")["signed_in"] is True
    assert client.post("/api/chatgpt/logout").json() == {"ok": True, "was_signed_in": True}
    assert not (service.data_dir / "chatgpt.json").exists()
    assert client.get("/api/chatgpt/status").json()["signed_in"] is False


def test_chatgpt_login_by_pasted_callback_then_use_it_for_the_chat(server, monkeypatch):
    client, service = server
    _stub_login(service, monkeypatch)

    started = client.post("/api/chatgpt/login").json()
    query = parse_qs(urlparse(started["url"]).query)
    assert started["url"].startswith("https://auth.openai.com/oauth/authorize?")
    assert query["code_challenge"] and query["code_challenge_method"] == ["S256"]
    assert query["state"] and query["redirect_uri"] == ["http://localhost:1455/auth/callback"]
    assert started["callback"] == "http://localhost:1455/auth/callback"
    assert 590 < started["expires_in"] <= 600 and started["port_bound"] is False
    state = query["state"][0]

    status = client.get("/api/chatgpt/status").json()
    assert status["pending"] is True and status["url"] == started["url"]
    assert status["signed_in"] is False and "error" not in status
    # a second login while one waits is the same one
    again = client.post("/api/chatgpt/login").json()
    assert again["url"] == started["url"]

    # the wrong state: refused, nothing exchanged, the login still waits
    bad = client.post(
        "/api/chatgpt/callback",
        json={"url": "http://localhost:1455/auth/callback?code=abc&state=someone-else"},
    )
    assert bad.status_code == 400 and "state_mismatch" in bad.json()["detail"]
    assert client.get("/api/chatgpt/status").json()["pending"] is True
    nonsense = client.post("/api/chatgpt/callback", json={"url": "https://example.com/"})
    assert nonsense.status_code == 400 and "bad_callback" in nonsense.json()["detail"]

    ok = client.post(
        "/api/chatgpt/callback",
        json={"url": f"http://localhost:1455/auth/callback?code=abc&state={state}"},
    )
    assert ok.json() == {"ok": True}
    status = wait_for(lambda: (s := client.get("/api/chatgpt/status").json())["signed_in"] and s)
    assert status["pending"] is False and status["label"] == "ChatGPT Plus"
    assert "error" not in status
    assert (service.data_dir / "chatgpt.json").exists()

    # the runtime does not switch the model by itself; the app does, as the web console does
    assert service.settings.llm.provider == "openai"
    llm = client.put(
        "/api/connections/llm",
        json={"provider": "chatgpt", "model": "", "base_url": "", "api_key": ""},
    ).json()
    assert llm["provider"] == "chatgpt" and llm["model"] == "gpt-5.6-sol" and llm["base_url"] == ""
    assert type(getattr(service.app.llm, "inner", service.app.llm)).__name__ == "CodexLLM"
    assert service.settings.llm.base_url is None
    assert client.get("/api/connections").json()["llm"]["provider"] == "chatgpt"
    view = client.get("/api/providers").json()
    assert view["configured"]["chat"] == {
        "provider": "chatgpt",
        "model": "gpt-5.6-sol",
        "protocol": "chatgpt",
        "source": "chatgpt",
    }
    assert view["configured"]["hands"]["provider"] == "chatgpt"
    openai = next(p for p in view["providers"] if p["id"] == "openai")
    assert openai["signed_in"] is True and openai["configured"] == ["chat", "hands"]
    assert view["capabilities"] == ["chat", "vision"]
    assert view["unavailable"]["image"] != ""  # the sign-in draws no pictures
    # the saved settings carry no key and no endpoint for the sign-in
    saved = json.loads((service.data_dir / "app-settings.json").read_text("utf-8"))
    assert saved["llm"]["provider"] == "chatgpt" and saved["llm"]["base_url"] == ""
    assert saved["llm"]["model"] == "gpt-5.6-sol"


def test_chatgpt_login_through_the_loopback_port(server, monkeypatch):
    client, service = server
    ports = _stub_login(service, monkeypatch, bind=True)
    started = client.post("/api/chatgpt/login").json()
    assert started["port_bound"] is True and len(ports) == 1
    state = parse_qs(urlparse(started["url"]).query)["state"][0]
    # the browser lands on the runtime's port
    r = httpx.get(f"http://127.0.0.1:{ports[0]}/auth/callback?code=abc&state={state}")
    assert r.status_code == 200 and "Signed in" in r.text
    status = wait_for(lambda: (s := client.get("/api/chatgpt/status").json())["signed_in"] and s)
    assert status["label"] == "ChatGPT Plus" and status["pending"] is False


def test_a_refused_sign_in_reports_the_error_until_the_next_login(server, monkeypatch):
    client, service = server
    _stub_login(service, monkeypatch)
    started = client.post("/api/chatgpt/login").json()
    state = parse_qs(urlparse(started["url"]).query)["state"][0]
    client.post(
        "/api/chatgpt/callback",
        json={
            "url": f"http://localhost:1455/auth/callback?error=access_denied"
            f"&error_description=The+person+said+no&state={state}"
        },
    )
    status = wait_for(
        lambda: (s := client.get("/api/chatgpt/status").json())["pending"] is False and s
    )
    assert status["signed_in"] is False
    assert status["error"] == "The person said no" and status["error_code"] == "cancelled"
    # the next login starts clean
    fresh = client.post("/api/chatgpt/login").json()
    assert fresh["url"] != started["url"]
    status = client.get("/api/chatgpt/status").json()
    assert status["pending"] is True and "error" not in status
    # logout stops a pending login too
    assert client.post("/api/chatgpt/logout").json() == {"ok": True, "was_signed_in": False}
    status = client.get("/api/chatgpt/status").json()
    assert status["pending"] is False and "error" not in status


def test_a_login_that_nobody_finishes_times_out(server, monkeypatch):
    client, service = server
    _stub_login(service, monkeypatch)
    # a short wait through the manager directly: the route uses the default ten minutes
    started = client.portal.call(service.chatgpt.login, 0.2)
    assert started["expires_in"] <= 1
    status = wait_for(
        lambda: (s := client.get("/api/chatgpt/status").json())["pending"] is False and s
    )
    assert status["error_code"] == "timeout" and status["signed_in"] is False
