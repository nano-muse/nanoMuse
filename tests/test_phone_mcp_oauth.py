"""OAuth refresh must negotiate JSON and leave saved tokens intact on invalid responses."""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1] / "android/src"
TRANSPORTS = [
    ROOT / "ios/default_mount/usr/local/lib/minis-mcp-cli/transport/http.py",
    ROOT
    / "android/app/src/main/assets/default_mount/usr/local/lib/minis-mcp-cli/transport/http.py",
]


@pytest.fixture(params=TRANSPORTS, ids=["ios", "android"])
def transport(request: pytest.FixtureRequest) -> ModuleType:
    spec = importlib.util.spec_from_file_location("phone_mcp_http", request.param)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refresh_requests_json_and_preserves_optional_secret(
    transport: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = {
        "access_token": "fixture-access",
        "refresh_token": "fixture-refresh",
        "token_endpoint": "https://example.com/token",
        "client_id": "fixture-client",
        "resource": "https://example.com/mcp",
    }
    post = Mock(return_value=httpx.Response(200, json={"access_token": "fixture-updated"}))
    save = Mock()
    monkeypatch.setattr(transport.httpx, "post", post)
    monkeypatch.setattr(transport, "_save_oauth_tokens", save)
    client = transport.HTTPTransport({"url": "https://example.com/mcp"}, "fixture-server")
    updated = client._oauth_refresh(tokens)
    assert updated["access_token"] == "fixture-updated"
    assert updated["refresh_token"] == tokens["refresh_token"]
    assert tokens["access_token"] == "fixture-access"
    assert post.call_args.kwargs["headers"] == {"Accept": "application/json"}
    form = post.call_args.kwargs["data"]
    assert form["grant_type"] == "refresh_token"
    assert form["resource"] == tokens["resource"]
    assert "client_secret" not in form
    save.assert_called_once_with("fixture-server", updated)


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, '{"error":"incorrect_client_credentials","access_token":"fixture-updated"}'),
        (200, '{"error":null,"access_token":"fixture-updated"}'),
        (200, "error=incorrect_client_credentials&error_description=private"),
        (200, "<html>private</html>"),
        (200, "[]"),
        (200, '{"access_token":42}'),
        (200, '{"access_token":"  "}'),
        (400, '{"error":"invalid_grant"}'),
        (500, "private response"),
    ],
)
def test_failed_refresh_never_replaces_tokens(
    transport: ModuleType, monkeypatch: pytest.MonkeyPatch, status: int, body: str
) -> None:
    tokens = {
        "access_token": "fixture-access",
        "refresh_token": "fixture-refresh",
        "token_endpoint": "https://example.com/token",
        "client_id": "fixture-client",
    }
    original = dict(tokens)
    monkeypatch.setattr(
        transport.httpx, "post", Mock(return_value=httpx.Response(status, text=body))
    )
    save = Mock()
    monkeypatch.setattr(transport, "_save_oauth_tokens", save)
    client = transport.HTTPTransport({"url": "https://example.com/mcp"}, "fixture-server")
    assert client._oauth_refresh(tokens) is None
    assert tokens == original
    save.assert_not_called()
