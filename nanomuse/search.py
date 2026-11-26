"""Web search behind the ``web_search`` tool.

DuckDuckGo needs no key and is the default, but it is scraped, not served: it rate-limits
and breaks now and then. When that matters, pick a provider with an API — Brave, Tavily or
Serply or SpecStream with a key, You.com with or without one (keyless, 100 searches a day), Keenable
with or without one (keyless, 1,000 searches an hour), Parallel's
Search MCP with or without one, or a SearXNG instance you run yourself — in ``[connectors.search]`` or from *Connections →
Web search*. Whatever is picked, a failed search falls back to DuckDuckGo once, with a
note in the result, so a lapsed key does not stop a task.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from nanomuse.config import SearchSettings
from nanomuse.logger import logger
from nanomuse.vault import CredentialVault

PROVIDERS: dict[str, dict[str, Any]] = {
    "duckduckgo": {"label": "DuckDuckGo", "needs_key": False, "host": "duckduckgo.com"},
    "brave": {
        "label": "Brave Search",
        "needs_key": True,
        "host": "api.search.brave.com",
        "keys_url": "https://brave.com/search/api/",
    },
    "tavily": {
        "label": "Tavily",
        "needs_key": True,
        "host": "api.tavily.com",
        "keys_url": "https://app.tavily.com/",
    },
    "serply": {
        "label": "Serply",
        "needs_key": True,
        "host": "api.serply.io",
        "keys_url": "https://serply.io/",
    },
    # Keyless: `api.you.com`, 100 searches a day per address. With a key: the keyed Search
    # API at `ydc-index.io`. `host` names whichever one a search goes to.
    "you": {
        "label": "You.com",
        "needs_key": False,
        "optional_key": True,
        "host": "api.you.com",
        "keyed_host": "ydc-index.io",
        "keys_url": "https://you.com/platform/api-keys",
    },
    # Parallel's Search MCP: anonymous (free, Fast mode, lower limits) or with a key as a
    # Bearer token for higher ones; the same endpoint either way.
    "parallel": {
        "label": "Parallel",
        "needs_key": False,
        "optional_key": True,
        "host": "search.parallel.ai",
        "keys_url": "https://platform.parallel.ai/",
    },
    # Keenable: the same host with or without a key. Keyless allows 1,000 searches an hour per
    # address; a key in `X-API-Key` lifts the hourly cap.
    "keenable": {
        "label": "Keenable",
        "needs_key": False,
        "optional_key": True,
        "host": "api.keenable.ai",
        "keys_url": "https://keenable.ai/console",
    },
    # SpecStream: the fast tier with page passages, so a result's snippet is the part of its page
    # that answers the query. A key from specstream.ai/workspace, sent as a Bearer token.
    "specstream": {
        "label": "SpecStream",
        "needs_key": True,
        "host": "api.specstream.ai",
        "keys_url": "https://specstream.ai/workspace",
    },
    "searxng": {"label": "SearXNG", "needs_key": False, "host": ""},
}
TIMEOUT = 20.0
# On You.com requests only, at the vendor's request, so they can tell nanoMuse's traffic apart.
YOU_USER_AGENT = "youdotcom-integration/nano-muse-nanomuse"
PARALLEL_MCP_URL = "https://search.parallel.ai/mcp"
# Keenable's keyless endpoint wants the calling app's name; it goes on every Keenable request.
KEENABLE_TITLE = "nanoMuse"
MCP_PROTOCOL_VERSION = "2025-06-18"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

    def render(self, index: int) -> str:
        return f"{index}. {self.title or '(no title)'}\n   {self.url}\n   {self.snippet}"


class SearchError(Exception):
    """The provider did not answer with results."""


def _region(region: str) -> tuple[str, str]:
    """``'cn-zh'`` → (country ``CN``, language ``zh``); DuckDuckGo's region codes are what
    the tool's parameter uses, the others take country and language apart."""
    region = (region or "").strip().lower()
    if not region or region == "wt-wt" or "-" not in region:
        return "", ""
    country, lang = region.split("-", 1)
    return country.upper(), lang.lower()


class WebSearchProvider:
    """One provider, chosen by settings, with DuckDuckGo behind it as the fallback."""

    def __init__(self, settings: SearchSettings, vault: CredentialVault | None = None):
        self.settings = settings
        self.vault = vault
        # Parallel counts its free tier per session: one id for the life of this provider.
        self.session_id = uuid.uuid4().hex

    @property
    def name(self) -> str:
        return self.settings.provider

    @property
    def label(self) -> str:
        return PROVIDERS[self.name]["label"]

    @property
    def host(self) -> str:
        """Where a search goes — what the Sentinel shows as the egress target."""
        if self.name == "searxng":
            return urlparse(self.settings.base_url).hostname or "searxng"
        if self.name == "you" and self.api_key():
            return str(PROVIDERS[self.name]["keyed_host"])
        return str(PROVIDERS[self.name]["host"])

    def api_key(self) -> str:
        key = self.settings.api_key
        if key and self.vault is not None and self.vault.has_placeholders(key):
            key = self.vault.resolve(key, strict=False)
            if self.vault.has_placeholders(key):
                key = ""
        return key

    @property
    def configured(self) -> bool:
        """Is what the provider needs there — a key, or an instance URL?"""
        if PROVIDERS[self.name]["needs_key"]:
            return bool(self.api_key())
        if self.name == "searxng":
            return bool(self.settings.base_url)
        return True

    def describe(self) -> str:
        if self.name == "duckduckgo":
            return "DuckDuckGo (no key needed)"
        if self.name == "searxng":
            return f"SearXNG at {self.settings.base_url or '(no URL set)'}"
        if self.name == "you" and not self.api_key():
            return "You.com (no key: 100 searches a day)"
        if self.name == "parallel" and not self.api_key():
            return "Parallel (no key: free, lower limits)"
        if self.name == "keenable" and not self.api_key():
            return "Keenable (no key: 1,000 searches an hour)"
        return f"{self.label} ({'key set' if self.api_key() else 'no key'})"

    async def search(
        self, query: str, max_results: int = 6, region: str = ""
    ) -> tuple[list[SearchResult], str]:
        """Results and a note: empty when the configured provider answered, otherwise why
        DuckDuckGo answered instead."""
        if self.name == "duckduckgo":
            return await self._ddg(query, max_results, region), ""
        if not self.configured:
            missing = "no API key" if PROVIDERS[self.name]["needs_key"] else "no instance URL"
            if not self.settings.fallback:
                raise RuntimeError(f"{self.label}: {missing}")
            logger.warning(
                "{} is the search provider but has {}; using DuckDuckGo", self.label, missing
            )
            return await self._ddg(
                query, max_results, region
            ), f"{self.label}: {missing}; results from DuckDuckGo"
        try:
            return await self._call(query, max_results, region), ""
        except Exception as exc:  # noqa: BLE001 — a failed provider must not stop the task
            reason = self.explain(exc)
            if not self.settings.fallback:
                raise RuntimeError(f"{self.label} failed ({reason})") from exc
            logger.warning("{} search failed ({}); using DuckDuckGo", self.label, reason)
            return await self._ddg(
                query, max_results, region
            ), f"{self.label} failed ({reason}); results from DuckDuckGo"

    async def probe(self, query: str = "nanoMuse personal agent") -> dict[str, Any]:
        """One search against the configured provider, no fallback — for the test button."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            results = (
                await self._ddg(query, 3, "")
                if self.name == "duckduckgo"
                else await self._call(query, 3, "")
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": self.explain(exc)}
        return {
            "ok": True,
            "provider": self.label,
            "results": len(results),
            "first": results[0].title if results else "",
            "ms": int((loop.time() - started) * 1000),
        }

    def explain(self, exc: Exception) -> str:
        """Why a search failed, in words: httpx's timeouts have empty messages."""
        if isinstance(exc, httpx.ConnectTimeout | httpx.ConnectError):
            return f"could not reach {self.host}" + (f" ({exc})" if str(exc) else "")
        if isinstance(exc, httpx.TimeoutException):
            return f"{self.host} did not answer within {TIMEOUT:g}s"
        if isinstance(exc, SearchError):
            return str(exc)
        return f"{type(exc).__name__}: {str(exc)[:160]}".rstrip(": ")

    # ------------------------------------------------------------------ providers
    async def _call(self, query: str, max_results: int, region: str) -> list[SearchResult]:
        if self.name == "brave":
            return await self._brave(query, max_results, region)
        if self.name == "tavily":
            return await self._tavily(query, max_results)
        if self.name == "serply":
            return await self._serply(query, max_results, region)
        if self.name == "you":
            return await self._you(query, max_results, region)
        if self.name == "parallel":
            return await self._parallel(query, max_results)
        if self.name == "keenable":
            return await self._keenable(query, max_results)
        if self.name == "specstream":
            return await self._specstream(query, max_results, region)
        if self.name == "searxng":
            return await self._searxng(query, max_results, region)
        return await self._ddg(query, max_results, region)

    @staticmethod
    async def _ddg(query: str, max_results: int, region: str) -> list[SearchResult]:
        def _search() -> list[dict[str, Any]]:
            from ddgs import DDGS

            with DDGS() as ddgs:
                return list(ddgs.text(query, region=region or "wt-wt", max_results=max_results))

        rows = await asyncio.to_thread(_search)
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("href") or r.get("url") or "",
                snippet=(r.get("body") or "").strip(),
            )
            for r in rows
        ]

    async def _brave(self, query: str, max_results: int, region: str) -> list[SearchResult]:
        country, lang = _region(region)
        params: dict[str, Any] = {"q": query, "count": min(max_results, 20)}
        if country:
            params["country"] = country
        if lang:
            params["search_lang"] = lang
        async with _client() as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params=params,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self.api_key(),
                },
            )
        _raise_for(resp)
        rows = (resp.json().get("web") or {}).get("results") or []
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("url") or "",
                snippet=(r.get("description") or "").strip(),
            )
            for r in rows[:max_results]
        ]

    async def _tavily(self, query: str, max_results: int) -> list[SearchResult]:
        async with _client() as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={"query": query, "max_results": min(max_results, 20), "search_depth": "basic"},
                headers={
                    "Authorization": f"Bearer {self.api_key()}",
                    "Content-Type": "application/json",
                },
            )
        _raise_for(resp)
        rows = resp.json().get("results") or []
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("url") or "",
                snippet=(r.get("content") or "").strip()[:400],
            )
            for r in rows[:max_results]
        ]

    async def _serply(self, query: str, max_results: int, region: str) -> list[SearchResult]:
        """Serply: Google web search results at ``api.serply.io`` with ``X-Api-Key``."""
        country, _lang = _region(region)
        params: dict[str, Any] = {"q": query, "num": min(max_results, 10)}
        if country:
            params["gl"] = country
        async with _client() as client:
            resp = await client.get(
                "https://api.serply.io/v1/search",
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "nanoMuse",
                    "X-Api-Key": self.api_key(),
                },
            )
        _raise_for(resp)
        rows = resp.json().get("results") or []
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("link") or "",
                snippet=(r.get("description") or "").strip()[:400],
            )
            for r in rows[:max_results]
        ]

    async def _you(self, query: str, max_results: int, region: str) -> list[SearchResult]:
        """You.com: the keyless endpoint at ``api.you.com`` (100 searches a day), or with a
        key the Search API at ``ydc-index.io``. Both answer ``results.web[]`` and
        ``results.news[]`` in the same shape; web results come first."""
        key = self.api_key()
        country, _lang = _region(region)
        params: dict[str, Any] = {"query": query, "count": min(max_results, 20)}
        if country:
            params["country"] = country
        headers = {"Accept": "application/json", "User-Agent": YOU_USER_AGENT}
        if key:
            headers["X-API-Key"] = key
        url = "https://ydc-index.io/v1/search" if key else "https://api.you.com/v1/agents/search"
        async with _client() as client:
            resp = await client.get(url, params=params, headers=headers)
        if not key and resp.status_code in (401, 403, 429):
            raise SearchError(f"the keyless limit is used up (HTTP {resp.status_code})")
        _raise_for(resp)
        found = resp.json().get("results") or {}
        rows = list(found.get("web") or []) + list(found.get("news") or [])
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("url") or "",
                snippet=(r.get("description") or _first(r.get("snippets"))).strip()[:400],
            )
            for r in rows[:max_results]
        ]

    async def _parallel(self, query: str, max_results: int) -> list[SearchResult]:
        """Parallel: the ``web_search`` tool of its Search MCP, one ``tools/call`` over
        Streamable HTTP. The server takes a call without the ``initialize`` handshake, so a
        search is one request. A tool error comes back as ``isError`` with a sentence."""
        key = self.api_key()
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if key:
            headers["Authorization"] = f"Bearer {key}"
        call = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "web_search",
                "arguments": {
                    "objective": query,
                    "search_queries": [query],
                    "session_id": self.session_id,
                },
            },
        }
        async with _client() as client:
            resp = await client.post(PARALLEL_MCP_URL, json=call, headers=headers)
        if not key and resp.status_code == 429:
            raise SearchError("the free limit is reached for now (HTTP 429)")
        if resp.status_code >= 400:
            _raise_for(resp)
        reply = _mcp_reply(resp)
        if error := reply.get("error"):
            raise SearchError(f"MCP error: {str(error.get('message') or error)[:160]}")
        result = reply.get("result") or {}
        text = "".join(
            c.get("text") or "" for c in result.get("content") or [] if c.get("type") == "text"
        )
        if result.get("isError"):
            raise SearchError(text.strip()[:160] or "the search tool reported an error")
        found = result.get("structuredContent")
        if not isinstance(found, dict):
            try:
                found = json.loads(text)
            except ValueError as exc:
                raise SearchError("the reply carried no search results") from exc
        rows = found.get("results") if isinstance(found, dict) else None
        if not isinstance(rows, list):
            raise SearchError("the reply carried no search results")
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("url") or "",
                # Excerpts are markdown over several lines; one line keeps the list readable.
                snippet=" ".join(" ".join(_strings(r.get("excerpts"))).split())[:400],
            )
            for r in rows[:max_results]
            if isinstance(r, dict)
        ]

    async def _keenable(self, query: str, max_results: int) -> list[SearchResult]:
        """Keenable: ``/v1/search/public`` without a key (1,000 searches an hour per address),
        ``/v1/search`` with one in ``X-API-Key``; the same host and body either way. A
        result's text is its ``snippet``, page text over several lines."""
        key = self.api_key()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Keenable-Title": KEENABLE_TITLE,
        }
        if key:
            headers["X-API-Key"] = key
        url = "https://api.keenable.ai/v1/search" + ("" if key else "/public")
        async with _client() as client:
            resp = await client.post(
                url, json={"query": query, "max_results": min(max_results, 20)}, headers=headers
            )
        if not key and resp.status_code == 429:
            raise SearchError("the keyless limit is reached for now (HTTP 429)")
        _raise_for(resp)
        rows = resp.json().get("results") or []
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("url") or "",
                # The snippet is page text over several lines; one line keeps the list readable.
                snippet=" ".join((r.get("snippet") or "").split())[:400],
            )
            for r in rows[:max_results]
        ]

    async def _specstream(self, query: str, max_results: int, region: str) -> list[SearchResult]:
        """SpecStream: ``GET /v1/web-search`` at ``api.specstream.ai`` with a Bearer key, on the
        fast tier with ``passages=true``. A source's ``highlights`` are the passages of its page
        closest to the query; they make the snippet, and the page summary stands in without them."""
        country, lang = _region(region)
        params: dict[str, Any] = {
            "q": query,
            "num": min(max_results, 20),
            "speed": "fast",
            "passages": "true",
        }
        if country:
            params["country"] = country
        if lang:
            params["language"] = lang
        async with _client() as client:
            resp = await client.get(
                "https://api.specstream.ai/v1/web-search",
                params=params,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.api_key()}",
                    "User-Agent": "nanoMuse",
                },
            )
        if resp.status_code == 402:
            raise SearchError("the SpecStream account has no credit left (HTTP 402)")
        _raise_for(resp)
        rows = (resp.json().get("data") or {}).get("sources") or []
        results = []
        for r in rows[:max_results]:
            if not isinstance(r, dict):
                continue
            text = " ".join(h for h in r.get("highlights") or [] if isinstance(h, str))
            results.append(
                SearchResult(
                    title=r.get("title") or "",
                    url=r.get("url") or "",
                    snippet=" ".join((text or r.get("snippet") or "").split())[:400],
                )
            )
        return results

    async def _searxng(self, query: str, max_results: int, region: str) -> list[SearchResult]:
        country, lang = _region(region)
        params: dict[str, Any] = {"q": query, "format": "json"}
        if lang:
            params["language"] = f"{lang}-{country}" if country else lang
        base = self.settings.base_url.rstrip("/")
        async with _client() as client:
            resp = await client.get(
                f"{base}/search", params=params, headers={"Accept": "application/json"}
            )
        _raise_for(resp)
        rows = resp.json().get("results") or []
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("url") or "",
                snippet=(r.get("content") or "").strip(),
            )
            for r in rows[:max_results]
        ]


def _strings(items: Any) -> list[str]:
    """The strings of a list, else none."""
    return [i for i in items if isinstance(i, str)] if isinstance(items, list) else []


def _first(snippets: Any) -> str:
    """The first entry of a list of strings, else nothing."""
    if isinstance(snippets, list) and snippets and isinstance(snippets[0], str):
        return snippets[0]
    return ""


def _mcp_reply(resp: httpx.Response) -> dict[str, Any]:
    """The JSON-RPC answer of a Streamable HTTP reply: a JSON body, or the last ``data:``
    message of an event stream."""
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        data = [ln[5:].strip() for ln in resp.text.splitlines() if ln.startswith("data:")]
        body = data[-1] if data else ""
    else:
        body = resp.text
    try:
        reply = json.loads(body)
    except ValueError as exc:
        raise SearchError("the reply was not JSON-RPC (is the URL an MCP server?)") from exc
    if not isinstance(reply, dict):
        raise SearchError("the reply was not JSON-RPC (is the URL an MCP server?)")
    return reply


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code == 401 or resp.status_code == 403:
        raise SearchError(f"the key was refused (HTTP {resp.status_code})")
    if resp.status_code == 429:
        raise SearchError("rate limited (HTTP 429)")
    if resp.status_code >= 400:
        raise SearchError(f"HTTP {resp.status_code}: {resp.text[:120]}")
    try:
        resp.json()
    except ValueError as exc:
        raise SearchError("the reply was not JSON (is the URL a search API?)") from exc


__all__ = ["PROVIDERS", "SearchError", "SearchResult", "WebSearchProvider"]
