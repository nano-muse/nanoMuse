"""Web search providers: DuckDuckGo by default, Brave / Tavily / Serply / You.com / Parallel /
Keenable / SearXNG by settings, the fallback to DuckDuckGo with a note, keys from the vault,
the tool, the API and the doctor."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nanomuse import search as search_mod
from nanomuse.config import SearchSettings, Settings, apply_app_settings, load_app_settings
from nanomuse.llm import MockLLM
from nanomuse.search import SearchResult, WebSearchProvider, _region
from nanomuse.server.api import create_app
from nanomuse.server.service import MuseService
from nanomuse.tools import WebSearch
from nanomuse.vault import CredentialVault

DDG_ROWS = [
    {"title": "nanoMuse", "href": "https://github.com/nano-muse/nanoMuse", "body": "An agent."},
    {"title": "Muse", "href": "https://example.com/muse", "body": "Something else."},
]


class Wire:
    """Answers the HTTP a provider sends; records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.body: Any = {}
        self.text: str | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.text is not None:
            return httpx.Response(self.status, text=self.text)
        return httpx.Response(self.status, json=self.body)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            search_mod,
            "_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.handler)),
        )


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    w = Wire()
    w.install(monkeypatch)
    return w


@pytest.fixture
def ddg(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """DuckDuckGo answers from a list instead of the network; records the calls."""
    calls: list[dict[str, Any]] = []

    async def fake(query: str, max_results: int, region: str) -> list[SearchResult]:
        calls.append({"query": query, "max_results": max_results, "region": region})
        return [
            SearchResult(title=r["title"], url=r["href"], snippet=r["body"])
            for r in DDG_ROWS[:max_results]
        ]

    monkeypatch.setattr(WebSearchProvider, "_ddg", staticmethod(fake))
    return calls


def test_region_codes():
    assert _region("") == ("", "")
    assert _region("wt-wt") == ("", "")
    assert _region("cn-zh") == ("CN", "zh")
    assert _region("US-EN") == ("US", "en")
    assert _region("nonsense") == ("", "")


async def test_duckduckgo_is_the_default(ddg):
    p = WebSearchProvider(SearchSettings())
    assert p.name == "duckduckgo" and p.configured and p.host == "duckduckgo.com"
    assert p.describe() == "DuckDuckGo (no key needed)"
    results, note = await p.search("nanomuse", 1, "cn-zh")
    assert note == "" and [r.title for r in results] == ["nanoMuse"]
    assert ddg == [{"query": "nanomuse", "max_results": 1, "region": "cn-zh"}]


async def test_brave(wire: Wire, ddg):
    wire.body = {
        "web": {
            "results": [
                {"title": "A", "url": "https://a.example", "description": " first "},
                {"title": "B", "url": "https://b.example", "description": "second"},
                {"title": "C", "url": "https://c.example", "description": "third"},
            ]
        }
    }
    p = WebSearchProvider(SearchSettings(provider="brave", api_key="brv-key"))
    assert p.configured and p.host == "api.search.brave.com"
    assert p.describe() == "Brave Search (key set)"
    results, note = await p.search("nanomuse", 2, "cn-zh")
    assert note == "" and ddg == []
    assert [(r.title, r.snippet) for r in results] == [("A", "first"), ("B", "second")]
    req = wire.requests[0]
    assert req.method == "GET" and req.url.host == "api.search.brave.com"
    assert req.headers["X-Subscription-Token"] == "brv-key"
    assert req.url.params["q"] == "nanomuse" and req.url.params["count"] == "2"
    assert req.url.params["country"] == "CN" and req.url.params["search_lang"] == "zh"
    # no region → no country/lang parameters
    await p.search("x", 1, "")
    assert "country" not in wire.requests[1].url.params


async def test_tavily(wire: Wire, ddg):
    wire.body = {
        "results": [
            {"title": "T", "url": "https://t.example", "content": "x" * 1000},
        ]
    }
    p = WebSearchProvider(SearchSettings(provider="tavily", api_key="tvly-key"))
    results, note = await p.search("nanomuse", 5, "")
    assert note == "" and ddg == []
    assert results[0].title == "T" and len(results[0].snippet) == 400
    req = wire.requests[0]
    assert req.method == "POST" and req.url == "https://api.tavily.com/search"
    assert req.headers["Authorization"] == "Bearer tvly-key"
    assert json.loads(req.content) == {
        "query": "nanomuse",
        "max_results": 5,
        "search_depth": "basic",
    }


async def test_serply(wire: Wire, ddg):
    wire.body = {
        "results": [
            {"title": "G", "link": "https://g.example", "description": "  " + ("s" * 500) + "  "},
            {"title": "H", "link": "https://h.example", "description": "second"},
        ]
    }
    p = WebSearchProvider(SearchSettings(provider="serply", api_key="srp-key"))
    assert p.configured and p.host == "api.serply.io"
    assert p.describe() == "Serply (key set)"
    results, note = await p.search("nanomuse", 15, "cn-zh")
    assert note == "" and ddg == []
    assert len(results) == 2
    assert results[0].title == "G" and results[0].url == "https://g.example"
    assert results[0].snippet == "s" * 400
    req = wire.requests[0]
    assert req.method == "GET" and req.url.host == "api.serply.io"
    assert req.url.path == "/v1/search"
    assert req.headers["X-Api-Key"] == "srp-key"
    assert req.headers["User-Agent"] == "nanoMuse"
    assert req.url.params["q"] == "nanomuse" and req.url.params["num"] == "10"
    assert req.url.params["gl"] == "CN"
    # no region → no gl parameter; max_results trims the returned list
    results, _ = await p.search("x", 1, "")
    assert "gl" not in wire.requests[1].url.params and wire.requests[1].url.params["num"] == "1"
    assert [r.title for r in results] == ["G"]
    # a refused key or rate limit falls back to DuckDuckGo with the usual note
    wire.status = 401
    results, note = await p.search("nanomuse", 2, "")
    assert note == "Serply failed (the key was refused (HTTP 401)); results from DuckDuckGo"
    assert [r.title for r in results] == ["nanoMuse", "Muse"] and len(ddg) == 1
    wire.status = 429
    _, note = await p.search("nanomuse", 2, "")
    assert note == "Serply failed (rate limited (HTTP 429)); results from DuckDuckGo"


async def test_you_without_a_key(wire: Wire, ddg):
    wire.body = {
        "results": {
            "web": [
                {"title": "Y", "url": "https://y.example", "description": " first "},
                {"title": "Z", "url": "https://z.example", "snippets": ["from snippets", "more"]},
            ],
            "news": [{"title": "N", "url": "https://n.example", "description": "news"}],
        }
    }
    p = WebSearchProvider(SearchSettings(provider="you"))
    # no key is a configured provider, not a fallback to DuckDuckGo
    assert p.configured and p.host == "api.you.com"
    assert p.describe() == "You.com (no key: 100 searches a day)"
    results, note = await p.search("nanomuse", 3, "cn-zh")
    assert note == "" and ddg == []
    assert [(r.title, r.snippet) for r in results] == [
        ("Y", "first"),
        ("Z", "from snippets"),
        ("N", "news"),
    ]
    req = wire.requests[0]
    assert req.method == "GET" and req.url.host == "api.you.com"
    assert req.url.path == "/v1/agents/search"
    assert "X-API-Key" not in req.headers
    assert req.headers["User-Agent"] == "youdotcom-integration/nano-muse-nanomuse"
    assert req.url.params["query"] == "nanomuse" and req.url.params["count"] == "3"
    assert req.url.params["country"] == "CN"
    await p.search("x", 1, "")
    assert "country" not in wire.requests[1].url.params
    # web results come first; the count caps the list
    results, _ = await p.search("nanomuse", 2, "")
    assert [r.title for r in results] == ["Y", "Z"]
    # past the daily limit: a clear reason, then DuckDuckGo once
    wire.status = 429
    results, note = await p.search("nanomuse", 2, "")
    assert (
        note == "You.com failed (the keyless limit is used up (HTTP 429)); results from DuckDuckGo"
    )
    assert [r.title for r in results] == ["nanoMuse", "Muse"] and len(ddg) == 1
    wire.status = 401
    _, note = await p.search("nanomuse", 2, "")
    assert "the keyless limit is used up (HTTP 401)" in note


async def test_you_with_a_key(wire: Wire, ddg):
    wire.body = {
        "results": {"web": [{"title": "K", "url": "https://k.example", "description": "d"}]}
    }
    p = WebSearchProvider(SearchSettings(provider="you", api_key="ydc-key"))
    # the Sentinel sees the host the search really goes to
    assert p.configured and p.host == "ydc-index.io"
    assert p.describe() == "You.com (key set)"
    results, note = await p.search("nanomuse", 2, "")
    assert note == "" and ddg == [] and results[0].title == "K"
    req = wire.requests[0]
    assert (
        req.method == "GET" and req.url == "https://ydc-index.io/v1/search?query=nanomuse&count=2"
    )
    assert req.headers["X-API-Key"] == "ydc-key"
    assert req.headers["User-Agent"] == "youdotcom-integration/nano-muse-nanomuse"
    # a refused key reads as one, not as the keyless limit
    wire.status = 401
    _, note = await p.search("nanomuse", 2, "")
    assert "the key was refused (HTTP 401)" in note


def _parallel_reply(rows: list[dict[str, Any]], structured: bool = True) -> dict[str, Any]:
    """What Parallel's Search MCP answers to ``tools/call``: the results as JSON text, and the
    same object as ``structuredContent``."""
    found = {"search_id": "search_1", "results": rows, "warnings": None}
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(found)}],
        "isError": False,
    }
    if structured:
        result["structuredContent"] = found
    return {"jsonrpc": "2.0", "id": 1, "result": result}


PARALLEL_ROWS = [
    {
        "url": "https://github.com/nano-muse/nanoMuse",
        "title": "nanoMuse",
        "publish_date": None,
        "excerpts": ["# nanoMuse\n\nAn open-source  personal agent.", "On every device."],
    },
    {"url": "https://nanomuse.cn/docs/", "title": "Docs", "excerpts": []},
    {"url": "https://example.com/three", "title": "Three", "excerpts": ["third"]},
]


async def test_parallel_without_a_key(wire: Wire, ddg):
    wire.body = _parallel_reply(PARALLEL_ROWS)
    p = WebSearchProvider(SearchSettings(provider="parallel"))
    # keyless is a configured provider, not a fallback to DuckDuckGo
    assert p.configured and p.host == "search.parallel.ai"
    assert p.describe() == "Parallel (no key: free, lower limits)"
    results, note = await p.search("nanomuse agent", 2, "cn-zh")
    assert note == "" and ddg == []
    # the excerpts become one line; the count caps the list
    assert [(r.title, r.url, r.snippet) for r in results] == [
        (
            "nanoMuse",
            "https://github.com/nano-muse/nanoMuse",
            "# nanoMuse An open-source personal agent. On every device.",
        ),
        ("Docs", "https://nanomuse.cn/docs/", ""),
    ]
    req = wire.requests[0]
    assert req.method == "POST" and req.url == "https://search.parallel.ai/mcp"
    assert "Authorization" not in req.headers
    assert req.headers["MCP-Protocol-Version"] == "2025-06-18"
    assert "text/event-stream" in req.headers["Accept"]
    call = json.loads(req.content)
    assert call["method"] == "tools/call" and call["params"]["name"] == "web_search"
    args = call["params"]["arguments"]
    assert args["objective"] == "nanomuse agent" and args["search_queries"] == ["nanomuse agent"]
    # one session id for the provider's life: Parallel counts its free tier by it
    await p.search("other", 2, "")
    again = json.loads(wire.requests[1].content)["params"]["arguments"]
    assert args["session_id"] and again["session_id"] == args["session_id"]
    # a reply with the results as text only reads the same
    wire.body = _parallel_reply(PARALLEL_ROWS, structured=False)
    results, _ = await p.search("nanomuse", 3, "")
    assert [r.title for r in results] == ["nanoMuse", "Docs", "Three"]


async def test_parallel_with_a_key(wire: Wire, ddg):
    wire.body = _parallel_reply(PARALLEL_ROWS[:1])
    p = WebSearchProvider(SearchSettings(provider="parallel", api_key="par-key"))
    assert p.configured and p.host == "search.parallel.ai"
    assert p.describe() == "Parallel (key set)"
    results, note = await p.search("nanomuse", 2, "")
    assert note == "" and [r.title for r in results] == ["nanoMuse"]
    assert wire.requests[0].headers["Authorization"] == "Bearer par-key"
    # a refused key reads as one
    wire.status = 401
    _, note = await p.search("nanomuse", 2, "")
    assert note == "Parallel failed (the key was refused (HTTP 401)); results from DuckDuckGo"


async def test_parallel_reads_an_event_stream(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.dumps(_parallel_reply(PARALLEL_ROWS[:1]))
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text=f"event: message\ndata: {body}\n\n",
        )

    monkeypatch.setattr(
        search_mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    p = WebSearchProvider(SearchSettings(provider="parallel", fallback=False))
    results, _ = await p.search("nanomuse", 2, "")
    assert [r.url for r in results] == ["https://github.com/nano-muse/nanoMuse"]


async def test_parallel_errors_are_said(wire: Wire, ddg):
    """Each failure names Parallel and why; with fallback on, DuckDuckGo answers once and the
    note says so, with it off the search fails. Nothing switches providers quietly."""
    p = WebSearchProvider(SearchSettings(provider="parallel"))
    strict = WebSearchProvider(SearchSettings(provider="parallel", fallback=False))
    tool_error = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": "Missing required argument: objective."}],
            "isError": True,
        },
    }
    cases: list[tuple[int, Any, str]] = [
        (200, tool_error, "Missing required argument: objective."),
        (
            200,
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "bad params"}},
            "MCP error: bad params",
        ),
        (200, {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}, "no search results"),
        (429, {}, "the free limit is reached for now (HTTP 429)"),
        (500, {}, "HTTP 500"),
    ]
    for status, body, reason in cases:
        wire.status, wire.body = status, body
        results, note = await p.search("nanomuse", 2, "")
        assert note.startswith("Parallel failed (") and reason in note
        assert note.endswith("; results from DuckDuckGo") and results
        with pytest.raises(RuntimeError, match="Parallel failed") as err:
            await strict.search("nanomuse", 2, "")
        assert reason in str(err.value)
    assert len(ddg) == len(cases)  # once per fallback search, never for the strict one
    wire.status, wire.text = 200, "<html>not an MCP server</html>"
    with pytest.raises(RuntimeError, match="not JSON-RPC"):
        await strict.search("nanomuse", 2, "")
    # the test button reports the error without falling back
    r = await p.probe()
    assert r["ok"] is False and "not JSON-RPC" in r["error"] and len(ddg) == len(cases)
    # the tool says the search failed rather than answering from elsewhere
    out = await WebSearch(provider=strict).execute(query="nanomuse")
    assert out.error and "Parallel failed (the reply was not JSON-RPC" in out.error


async def test_parallel_timeout(monkeypatch: pytest.MonkeyPatch, ddg):
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("")

    monkeypatch.setattr(
        search_mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(slow))
    )
    strict = WebSearchProvider(SearchSettings(provider="parallel", fallback=False))
    with pytest.raises(RuntimeError, match=r"search\.parallel\.ai did not answer within 20s"):
        await strict.search("nanomuse", 2, "")
    assert ddg == []
    _, note = await WebSearchProvider(SearchSettings(provider="parallel")).search("q", 2, "")
    assert note == (
        "Parallel failed (search.parallel.ai did not answer within 20s); results from DuckDuckGo"
    )


async def test_parallel_cancellation(monkeypatch: pytest.MonkeyPatch, ddg):
    """A cancelled search stops: it is not an error to fall back from."""
    started = asyncio.Event()

    async def hang(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(
        search_mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(hang))
    )
    p = WebSearchProvider(SearchSettings(provider="parallel"))
    task = asyncio.create_task(p.search("nanomuse", 2, ""))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ddg == []


async def test_parallel_goes_through_the_sentinel_as_its_host(wire: Wire):
    tool = WebSearch(provider=WebSearchProvider(SearchSettings(provider="parallel")))
    assessment = tool.assess({"query": "q"})
    assert assessment.egress and assessment.egress_target == "search.parallel.ai"
    assert assessment.egress_configured


def test_parallel_is_saved_and_others_kept(settings: Settings):
    assert SearchSettings().provider == "duckduckgo"
    apply_app_settings(settings, {"search": {"provider": "parallel"}})
    assert settings.connectors.search.provider == "parallel"
    # a provider this version does not know leaves the saved choice as it was
    apply_app_settings(settings, {"search": {"provider": "bing"}})
    assert settings.connectors.search.provider == "parallel"


KEENABLE_ROWS = [
    {
        "title": "nanoMuse",
        "url": "https://github.com/nano-muse/nanoMuse",
        "description": "",
        "snippet": "nanoMuse\n\nAn open-source  personal agent.\nOn every device.",
        "acquired_at": "2026-10-20T08:00:00Z",
    },
    {"title": "Docs", "url": "https://nanomuse.cn/docs/", "description": "", "snippet": "d" * 600},
    {"title": "Three", "url": "https://example.com/three", "description": "", "snippet": "third"},
]


async def test_keenable_without_a_key(wire: Wire, ddg):
    wire.body = {"results": KEENABLE_ROWS}
    p = WebSearchProvider(SearchSettings(provider="keenable"))
    # keyless is a configured provider, not a fallback to DuckDuckGo
    assert p.configured and p.host == "api.keenable.ai"
    assert p.describe() == "Keenable (no key: 1,000 searches an hour)"
    results, note = await p.search("nanomuse agent", 2, "cn-zh")
    assert note == "" and ddg == []
    # the snippet becomes one line of at most 400 characters; the count caps the list
    assert [(r.title, r.url, r.snippet) for r in results] == [
        (
            "nanoMuse",
            "https://github.com/nano-muse/nanoMuse",
            "nanoMuse An open-source personal agent. On every device.",
        ),
        ("Docs", "https://nanomuse.cn/docs/", "d" * 400),
    ]
    req = wire.requests[0]
    assert req.method == "POST" and req.url == "https://api.keenable.ai/v1/search/public"
    assert req.headers["X-Keenable-Title"] == "nanoMuse"
    assert "X-API-Key" not in req.headers
    # Keenable takes no region: the body is the query and the count
    assert json.loads(req.content) == {"query": "nanomuse agent", "max_results": 2}
    # past the keyless limit: a clear reason, then DuckDuckGo once
    wire.status = 429
    results, note = await p.search("nanomuse", 2, "")
    assert note == (
        "Keenable failed (the keyless limit is reached for now (HTTP 429)); results from DuckDuckGo"
    )
    assert [r.title for r in results] == ["nanoMuse", "Muse"] and len(ddg) == 1


async def test_keenable_with_a_key(wire: Wire, ddg):
    wire.body = {"results": KEENABLE_ROWS[:1]}
    p = WebSearchProvider(SearchSettings(provider="keenable", api_key="kn-key"))
    # the same host with a key, so the Sentinel shows the same destination
    assert p.configured and p.host == "api.keenable.ai"
    assert p.describe() == "Keenable (key set)"
    results, note = await p.search("nanomuse", 2, "")
    assert note == "" and ddg == [] and [r.title for r in results] == ["nanoMuse"]
    req = wire.requests[0]
    assert req.method == "POST" and req.url == "https://api.keenable.ai/v1/search"
    assert req.headers["X-API-Key"] == "kn-key"
    assert req.headers["X-Keenable-Title"] == "nanoMuse"
    # a refused key reads as one, not as the keyless limit
    wire.status = 401
    _, note = await p.search("nanomuse", 2, "")
    assert note == "Keenable failed (the key was refused (HTTP 401)); results from DuckDuckGo"
    wire.status = 429
    _, note = await p.search("nanomuse", 2, "")
    assert note == "Keenable failed (rate limited (HTTP 429)); results from DuckDuckGo"


async def test_keenable_goes_through_the_sentinel_as_its_host(wire: Wire):
    tool = WebSearch(provider=WebSearchProvider(SearchSettings(provider="keenable")))
    assessment = tool.assess({"query": "q"})
    assert assessment.egress and assessment.egress_target == "api.keenable.ai"
    assert assessment.egress_configured


def test_keenable_is_saved_and_others_kept(settings: Settings):
    apply_app_settings(settings, {"search": {"provider": "keenable"}})
    assert settings.connectors.search.provider == "keenable"
    apply_app_settings(settings, {"search": {"provider": "bing"}})
    assert settings.connectors.search.provider == "keenable"


SPECSTREAM_SOURCES = [
    {
        "title": "nanoMuse",
        "url": "https://github.com/nano-muse/nanoMuse",
        "snippet": "page summary",
        "highlights": ["An open-source personal agent.", "On every\ndevice."],
    },
    {"title": "Docs", "url": "https://nanomuse.cn/docs/", "snippet": "d" * 600, "highlights": []},
    "not a source",
    {"title": "Three", "url": "https://example.com/three", "snippet": "third"},
]


async def test_specstream(wire: Wire, ddg):
    wire.body = {"data": {"sources": SPECSTREAM_SOURCES}, "error": None}
    p = WebSearchProvider(SearchSettings(provider="specstream", api_key="ss-key"))
    assert p.configured and p.host == "api.specstream.ai"
    assert p.describe() == "SpecStream (key set)"
    results, note = await p.search("nanomuse agent", 2, "cn-zh")
    assert note == "" and ddg == []
    # the passages make the snippet, on one line; the page summary stands in, capped at 400
    assert [(r.title, r.url, r.snippet) for r in results] == [
        (
            "nanoMuse",
            "https://github.com/nano-muse/nanoMuse",
            "An open-source personal agent. On every device.",
        ),
        ("Docs", "https://nanomuse.cn/docs/", "d" * 400),
    ]
    req = wire.requests[0]
    assert req.method == "GET" and req.url.host == "api.specstream.ai"
    assert req.url.path == "/v1/web-search"
    assert req.headers["Authorization"] == "Bearer ss-key"
    assert dict(req.url.params) == {
        "q": "nanomuse agent",
        "num": "2",
        "speed": "fast",
        "passages": "true",
        "country": "CN",
        "language": "zh",
    }
    # no region: neither country nor language is sent; the count is capped at 20
    await p.search("nanomuse", 50, "")
    params = wire.requests[1].url.params
    assert "country" not in params and "language" not in params and params["num"] == "20"


async def test_specstream_failures_fall_back_with_a_reason(wire: Wire, ddg):
    p = WebSearchProvider(SearchSettings(provider="specstream", api_key="ss-key"))
    wire.status = 402
    wire.body = {"error": {"code": "insufficient_credit", "message": "add credit"}}
    results, note = await p.search("nanomuse", 2, "")
    assert note == (
        "SpecStream failed (the SpecStream account has no credit left (HTTP 402));"
        " results from DuckDuckGo"
    )
    assert [r.title for r in results] == ["nanoMuse", "Muse"] and len(ddg) == 1
    wire.status = 401
    _, note = await p.search("nanomuse", 2, "")
    assert note == "SpecStream failed (the key was refused (HTTP 401)); results from DuckDuckGo"
    wire.status = 429
    _, note = await p.search("nanomuse", 2, "")
    assert note == "SpecStream failed (rate limited (HTTP 429)); results from DuckDuckGo"


async def test_specstream_without_a_key_sends_nothing(wire: Wire, ddg):
    p = WebSearchProvider(SearchSettings(provider="specstream"))
    assert not p.configured
    _, note = await p.search("nanomuse", 2, "")
    assert note == "SpecStream: no API key; results from DuckDuckGo"
    assert wire.requests == [] and len(ddg) == 1


async def test_specstream_goes_through_the_sentinel_as_its_host(wire: Wire):
    settings = SearchSettings(provider="specstream", api_key="ss-key")
    tool = WebSearch(provider=WebSearchProvider(settings))
    assessment = tool.assess({"query": "q"})
    assert assessment.egress and assessment.egress_target == "api.specstream.ai"
    assert assessment.egress_configured


def test_specstream_is_saved(settings: Settings):
    apply_app_settings(settings, {"search": {"provider": "specstream"}})
    assert settings.connectors.search.provider == "specstream"


async def test_searxng(wire: Wire, ddg):
    wire.body = {"results": [{"title": "S", "url": "https://s.example", "content": "from searx"}]}
    p = WebSearchProvider(SearchSettings(provider="searxng", base_url="http://127.0.0.1:8080/"))
    assert p.configured and p.host == "127.0.0.1"
    assert p.describe() == "SearXNG at http://127.0.0.1:8080/"
    results, note = await p.search("nanomuse", 3, "cn-zh")
    assert note == "" and results[0].snippet == "from searx" and ddg == []
    req = wire.requests[0]
    assert str(req.url).startswith("http://127.0.0.1:8080/search?")
    assert req.url.params["format"] == "json" and req.url.params["language"] == "zh-CN"
    await p.search("x", 1, "")
    assert "language" not in wire.requests[1].url.params
    # a SearXNG that is not one (HTML instead of JSON) is a clear error, not a traceback
    wire.text = "<html>not a search api</html>"
    results, note = await p.search("nanomuse", 3, "")
    assert "not JSON" in note and "results from DuckDuckGo" in note
    assert [r.title for r in results] == ["nanoMuse", "Muse"]


async def test_failures_fall_back_to_duckduckgo_with_a_note(
    wire: Wire, ddg, monkeypatch: pytest.MonkeyPatch
):
    p = WebSearchProvider(SearchSettings(provider="brave", api_key="k"))
    wire.status = 429
    results, note = await p.search("nanomuse", 2, "")
    assert (
        results and note == "Brave Search failed (rate limited (HTTP 429)); results from DuckDuckGo"
    )
    wire.status = 401
    _, note = await p.search("nanomuse", 2, "")
    assert "the key was refused (HTTP 401)" in note
    wire.status = 500
    wire.text = "boom"
    _, note = await p.search("nanomuse", 2, "")
    assert "HTTP 500: boom" in note
    assert len(ddg) == 3

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("")

    monkeypatch.setattr(
        search_mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(unreachable))
    )
    _, note = await p.search("nanomuse", 2, "")
    assert (
        note
        == "Brave Search failed (could not reach api.search.brave.com); results from DuckDuckGo"
    )
    wire.install(monkeypatch)
    # the probe (the test button) does not fall back
    wire.status = 429
    wire.text = None
    r = await p.probe()
    assert r["ok"] is False and "rate limited" in r["error"] and len(ddg) == 4
    # fallback = false: the query never reaches DuckDuckGo's host
    strict = WebSearchProvider(SearchSettings(provider="brave", api_key="k", fallback=False))
    with pytest.raises(RuntimeError, match="rate limited"):
        await strict.search("nanomuse", 2, "")
    unset = WebSearchProvider(SearchSettings(provider="brave", fallback=False))
    with pytest.raises(RuntimeError, match="no API key"):
        await unset.search("nanomuse", 2, "")
    assert len(ddg) == 4


async def test_unconfigured_provider_uses_duckduckgo_and_says_so(wire: Wire, ddg):
    p = WebSearchProvider(SearchSettings(provider="brave"))
    assert not p.configured and p.describe() == "Brave Search (no key)"
    results, note = await p.search("nanomuse", 2, "")
    assert results and note == "Brave Search: no API key; results from DuckDuckGo"
    assert wire.requests == []
    p = WebSearchProvider(SearchSettings(provider="searxng"))
    assert not p.configured
    _, note = await p.search("nanomuse", 2, "")
    assert note == "SearXNG: no instance URL; results from DuckDuckGo"


async def test_key_from_the_vault(tmp_path, wire: Wire):
    vault = CredentialVault(tmp_path / "vault")
    p = WebSearchProvider(
        SearchSettings(provider="tavily", api_key="{{vault:SEARCH_API_KEY}}"), vault=vault
    )
    assert p.api_key() == "" and not p.configured  # placeholder, nothing behind it
    vault.set("SEARCH_API_KEY", "tvly-real")
    assert p.api_key() == "tvly-real" and p.configured
    wire.body = {"results": []}
    await p.probe()
    assert wire.requests[0].headers["Authorization"] == "Bearer tvly-real"


async def test_probe_reports_the_provider(wire: Wire):
    wire.body = {"web": {"results": [{"title": "Hit", "url": "https://h", "description": "d"}]}}
    p = WebSearchProvider(SearchSettings(provider="brave", api_key="k"))
    r = await p.probe()
    assert r["ok"] and r["provider"] == "Brave Search" and r["results"] == 1
    assert r["first"] == "Hit" and isinstance(r["ms"], int)


async def test_tool_renders_results_and_the_note(wire: Wire, ddg):
    tool = WebSearch(provider=WebSearchProvider(SearchSettings(provider="brave", api_key="k")))
    assessment = tool.assess({"query": "q"})
    assert assessment.egress_target == "api.search.brave.com" and assessment.egress_configured
    wire.body = {
        "web": {"results": [{"title": "A", "url": "https://a.example", "description": "first"}]}
    }
    out = await tool.execute(query="nanomuse", max_results=1)
    assert out.output == "1. A\n   https://a.example\n   first"
    wire.status = 429
    out = await tool.execute(query="nanomuse", max_results=2)
    lines = out.output.splitlines()
    assert lines[0].startswith("(Brave Search failed") and lines[1] == "1. nanoMuse"
    assert (await tool.execute(query="  ")).error
    # the default tool is DuckDuckGo
    plain = WebSearch()
    assert plain.provider.name == "duckduckgo"
    assert plain.assess({"query": "q"}).egress_target == "duckduckgo.com"


def test_settings_layering(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    apply_app_settings(
        settings,
        {"search": {"provider": "searxng", "base_url": "http://searx.lan:8080/", "api_key": None}},
    )
    web = settings.connectors.search
    assert web.provider == "searxng" and web.base_url == "http://searx.lan:8080"
    apply_app_settings(settings, {"search": {"provider": "nonsense"}})
    assert web.provider == "searxng"  # ignored, not crashed
    apply_app_settings(settings, {"search": {"api_key": "{{vault:SEARCH_API_KEY}}"}})
    assert web.api_key == "{{vault:SEARCH_API_KEY}}"
    # environment variables
    monkeypatch.chdir(settings.data_dir)  # no ./config/config.toml here
    monkeypatch.delenv("NANOMUSE_CONFIG", raising=False)
    monkeypatch.setenv("NANOMUSE_SEARCH_PROVIDER", "brave")
    monkeypatch.setenv("NANOMUSE_SEARCH_API_KEY", "env-key")
    monkeypatch.setenv("NANOMUSE_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("NANOMUSE_WORKSPACE", str(settings.agent.workspace))
    from nanomuse.config import load_settings

    loaded = load_settings(None)
    assert loaded.connectors.search.provider == "brave"
    assert loaded.connectors.search.api_key == "env-key"


def test_connections_search(settings: Settings, wire: Wire, ddg):
    settings.server.token = "secret-token"
    service = MuseService(settings, llm=MockLLM([]))
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        view = client.get("/api/connections").json()["search"]
        assert view["provider"] == "duckduckgo" and view["configured"] and not view["from_app"]
        assert view["key_source"] == "none"
        assert [p["id"] for p in view["providers"]] == [
            "duckduckgo",
            "brave",
            "tavily",
            "serply",
            "you",
            "parallel",
            "keenable",
            "specstream",
            "searxng",
        ]
        assert view["providers"][1]["needs_key"] and view["providers"][1]["keys_url"]
        assert not view["providers"][1]["optional_key"]
        serply = view["providers"][3]
        assert serply["needs_key"] and not serply["optional_key"] and serply["keys_url"]
        you = view["providers"][4]
        assert not you["needs_key"] and you["optional_key"] and you["keys_url"]
        parallel = view["providers"][5]
        assert parallel["id"] == "parallel" and parallel["label"] == "Parallel"
        assert not parallel["needs_key"] and parallel["optional_key"] and parallel["keys_url"]
        keenable = view["providers"][6]
        assert keenable["id"] == "keenable" and keenable["label"] == "Keenable"
        assert not keenable["needs_key"] and keenable["optional_key"] and keenable["keys_url"]
        specstream = view["providers"][7]
        assert specstream["id"] == "specstream" and specstream["label"] == "SpecStream"
        assert specstream["needs_key"] and not specstream["optional_key"] and specstream["keys_url"]

        # You.com without a key is configured: the picker needs nothing more
        r = client.put("/api/connections/search", json={"provider": "you"}).json()
        assert r["provider"] == "you" and r["configured"] is True and r["key_source"] == "none"
        wire.body = {"results": {"web": [{"title": "Y", "url": "https://y", "description": "d"}]}}
        r = client.post("/api/connections/search/test").json()
        assert r["ok"] and r["provider"] == "You.com" and r["results"] == 1
        assert wire.requests[-1].url.host == "api.you.com"

        # so is Keenable
        r = client.put("/api/connections/search", json={"provider": "keenable"}).json()
        assert r["provider"] == "keenable" and r["configured"] is True
        assert r["key_source"] == "none"
        wire.body = {"results": KEENABLE_ROWS[:1]}
        r = client.post("/api/connections/search/test").json()
        assert r["ok"] and r["provider"] == "Keenable" and r["results"] == 1
        assert wire.requests[-1].url.host == "api.keenable.ai"

        # Brave without a key: allowed, but not configured — searches fall back
        r = client.put("/api/connections/search", json={"provider": "brave"})
        assert r.status_code == 200
        view = r.json()
        assert view["provider"] == "brave" and view["configured"] is False and view["from_app"]
        r = client.post("/api/connections/search/test").json()
        assert r["ok"] is False and "needs an API key" in r["error"]
        tool = service.app.tools.get("web_search")
        assert isinstance(tool, WebSearch) and tool.provider.name == "brave"

        # the key goes to the vault, never into the settings file
        r = client.put("/api/connections/search", json={"api_key": " brv-key "}).json()
        assert r["key_source"] == "vault" and r["configured"] is True
        assert service.app.vault.get("SEARCH_API_KEY") == "brv-key"
        saved = load_app_settings(settings.data_dir)
        assert saved["search"] == {"provider": "brave", "api_key": "{{vault:SEARCH_API_KEY}}"}
        wire.body = {"web": {"results": [{"title": "Hit", "url": "https://h", "description": "d"}]}}
        r = client.post("/api/connections/search/test").json()
        assert r["ok"] and r["provider"] == "Brave Search" and r["results"] == 1
        assert wire.requests[-1].headers["X-Subscription-Token"] == "brv-key"

        # removing the key
        r = client.put("/api/connections/search", json={"api_key": ""}).json()
        assert r["key_source"] == "none" and r["configured"] is False
        assert service.app.vault.get("SEARCH_API_KEY") is None

        # SearXNG by URL; bad input is a 400
        assert client.put("/api/connections/search", json={"provider": "bing"}).status_code == 400
        assert (
            client.put("/api/connections/search", json={"base_url": "ftp://x"}).status_code == 400
        )
        r = client.put(
            "/api/connections/search",
            json={"provider": "searxng", "base_url": "http://127.0.0.1:8080/"},
        ).json()
        assert r["provider"] == "searxng" and r["base_url"] == "http://127.0.0.1:8080"
        assert r["configured"] is True
        assert tool.provider.host == "127.0.0.1"

        # back to DuckDuckGo: the test runs a real (here: faked) search
        r = client.put("/api/connections/search", json={"provider": "duckduckgo"}).json()
        assert r["configured"] is True
        r = client.post("/api/connections/search/test").json()
        assert r["ok"] and r["provider"] == "DuckDuckGo" and r["results"] == 2
