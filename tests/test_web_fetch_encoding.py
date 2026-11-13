"""Streamed native-fetch regressions for the encoding failure reported in #641."""

from __future__ import annotations

import gzip
import json
from collections.abc import AsyncIterator, Callable
from functools import partial

import httpx
import pytest

from nanomuse.tools import web
from nanomuse.tools.web import WebFetch, fetch_public


class _WireStream(httpx.AsyncByteStream):
    def __init__(self, body: bytes, chunk_size: int) -> None:
        self.chunks = [body[i : i + chunk_size] for i in range(0, len(body), chunk_size)]
        self.yielded = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.yielded += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def _response(
    body: bytes, ctype: str, compressed: bool, chunk_size: int = 7, status: int = 200
) -> tuple[httpx.Response, _WireStream]:
    wire = gzip.compress(body, mtime=0) if compressed else body
    stream = _WireStream(wire, chunk_size)
    headers = [("Content-Type", ctype), ("Content-Length", str(len(wire)))]
    if compressed:
        headers.append(("Content-Encoding", "gzip"))
    # stream= leaves decompression to HTTPX's normal aiter_bytes(), as on the network.
    return httpx.Response(status, headers=headers, stream=stream), stream


ResponseHandler = Callable[[httpx.Request], httpx.Response]
TransportInjector = Callable[[ResponseHandler], httpx.MockTransport]


@pytest.fixture
def inject_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> TransportInjector:
    def inject(handler: ResponseHandler) -> httpx.MockTransport:
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(web, "fetch_public", partial(fetch_public, transport=transport))
        return transport

    return inject


JSON_BODY = '{"message":"read once", "city":"北京"}'.encode()
HTML_BODY = (
    b"<html><head><title>Reading</title></head><body><main><h2>Heading</h2>"
    b"<p>A <strong>useful</strong> page.</p></main><script>hidden()</script></body></html>"
)


@pytest.mark.parametrize("compressed", [False, True], ids=["plain", "gzip"])
@pytest.mark.parametrize("chunk_size", [1, 7, 65536])
@pytest.mark.parametrize(
    "body,ctype", [(JSON_BODY, "application/json"), (HTML_BODY, "text/html")], ids=["json", "html"]
)
async def test_fetch_public_decodes_once_and_keeps_response_metadata(
    compressed: bool, chunk_size: int, body: bytes, ctype: str
) -> None:
    response, stream = _response(body, ctype, compressed, chunk_size, status=201)
    response.headers.update({"X-Trace": "retained", "Cache-Control": "no-cache"})
    response.headers = httpx.Headers(
        [*response.headers.multi_items(), ("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")]
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    result = await fetch_public(
        "https://public.example/data", timeout=5, transport=httpx.MockTransport(handler)
    )
    assert result.content == body
    assert result.status_code == 201
    assert result.request is requests[0] and result.request.method == "GET"
    assert str(result.url) == "https://public.example/data"
    assert result.headers["content-type"] == ctype
    assert result.headers["x-trace"] == "retained"
    assert result.headers["cache-control"] == "no-cache"
    assert result.headers.get_list("set-cookie") == ["a=1", "b=2"]
    assert "content-encoding" not in result.headers
    assert int(result.headers["content-length"]) == len(body)
    assert stream.closed and stream.yielded == len(stream.chunks)


@pytest.mark.parametrize("compressed", [False, True], ids=["plain", "gzip"])
@pytest.mark.parametrize("chunk_size", [1, 7, 65536])
@pytest.mark.parametrize(
    "body,ctype", [(JSON_BODY, "application/json"), (HTML_BODY, "text/html")], ids=["json", "html"]
)
async def test_web_fetch_renders_streamed_json_and_html(
    compressed: bool,
    chunk_size: int,
    body: bytes,
    ctype: str,
    inject_transport: TransportInjector,
) -> None:
    response, stream = _response(body, ctype, compressed, chunk_size)
    inject_transport(lambda request: response)
    result = await WebFetch().execute(url="https://public.example/data")
    assert result.ok, result.error
    prefix = f"URL: https://public.example/data\nContent-Type: {ctype}\n\n"
    if ctype == "application/json":
        assert result.output == prefix + json.dumps(json.loads(body), ensure_ascii=False, indent=2)
    else:
        assert result.output == prefix + "# Reading\n\n## Heading\n\nA **useful** page."
        assert "hidden()" not in result.output and "<main>" not in result.output
    assert stream.closed


@pytest.mark.parametrize("compressed", [False, True], ids=["plain", "gzip"])
@pytest.mark.parametrize("chunk_size", [1, 65536])
async def test_fetch_public_caps_decoded_bytes_and_corrects_length(
    monkeypatch: pytest.MonkeyPatch, compressed: bool, chunk_size: int
) -> None:
    monkeypatch.setattr(web, "MAX_BODY_BYTES", 1000)
    body = b"x" * 4096
    response, stream = _response(body, "text/plain", compressed, chunk_size)
    result = await fetch_public(
        "https://public.example/big",
        timeout=5,
        transport=httpx.MockTransport(lambda request: response),
    )
    assert result.content == body[:1000]
    assert result.headers["content-length"] == "1000"
    assert "content-encoding" not in result.headers
    assert stream.closed
    if chunk_size == 1:
        assert stream.yielded < len(stream.chunks), "the capped reader consumed the whole stream"


@pytest.mark.parametrize("compressed", [False, True], ids=["plain", "gzip"])
async def test_web_fetch_applies_text_truncation_after_the_decoded_body_cap(
    monkeypatch: pytest.MonkeyPatch, compressed: bool, inject_transport: TransportInjector
) -> None:
    monkeypatch.setattr(web, "MAX_BODY_BYTES", 800)
    response, stream = _response(b"x" * 4096, "text/plain", compressed)
    inject_transport(lambda request: response)
    result = await WebFetch().execute(url="https://public.example/big", max_chars=500)
    assert result.ok, result.error
    assert result.output == (
        "URL: https://public.example/big\nContent-Type: text/plain\n\n"
        + "x" * 500
        + "\n... [truncated, 800 chars total]"
    )
    assert stream.closed


@pytest.mark.parametrize("compressed", [False, True], ids=["plain", "gzip"])
async def test_web_fetch_keeps_http_errors_and_readable_body(
    compressed: bool, inject_transport: TransportInjector
) -> None:
    response, stream = _response(HTML_BODY, "text/html", compressed, status=404)
    inject_transport(lambda request: response)
    result = await WebFetch().execute(url="https://public.example/missing")
    assert not result.ok and result.error == "HTTP 404"
    assert result.output == "# Reading\n\n## Heading\n\nA **useful** page."
    assert stream.closed


@pytest.mark.parametrize(
    "invalid", [b"not a gzip stream", gzip.compress(JSON_BODY, mtime=0)[:-8] + b"badcrc!!"]
)
async def test_invalid_gzip_fails_explicitly_and_a_later_fetch_recovers(
    invalid: bytes, inject_transport: TransportInjector
) -> None:
    streams: list[_WireStream] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/bad":
            stream = _WireStream(invalid, 7)
            response = httpx.Response(
                200,
                headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
                stream=stream,
            )
        else:
            response, stream = _response(JSON_BODY, "application/json", True)
        streams.append(stream)
        return response

    transport = inject_transport(handler)
    with pytest.raises(httpx.DecodingError):
        await fetch_public("https://public.example/bad", timeout=5, transport=transport)
    bad = await WebFetch().execute(url="https://public.example/bad")
    assert not bad.ok and bad.error and bad.error.startswith("request failed:")
    assert bad.output == ""
    good = await WebFetch().execute(url="https://public.example/good")
    assert good.ok and '"message": "read once"' in good.output
    assert all(stream.closed for stream in streams)


async def test_web_fetch_keeps_transport_timeout_errors(
    inject_transport: TransportInjector,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    inject_transport(handler)
    result = await WebFetch(timeout=5).execute(url="https://public.example/slow")
    assert not result.ok and result.error == "request failed: read timed out"
