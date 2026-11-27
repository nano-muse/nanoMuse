"""Read a bounded public RSS or Atom feed without sending credentials."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import re
import socket
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from nanomuse.server.public_sources import PublicItem
from nanomuse.server.watch_discovery import normalize_watch

_LIMIT = 1024 * 1024
_ATOM = "{http://www.w3.org/2005/Atom}"
_RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
_RSS1 = "{http://purl.org/rss/1.0/}"
_XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
_DC_DATE = "{http://purl.org/dc/elements/1.1/}date"
_WINDOW = timedelta(days=90)


async def _feed_body(response: httpx.Response) -> bytes:
    if response.status_code != 200:
        raise ValueError(f"Feed returned HTTP {response.status_code}.")
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        raise ValueError("Unsupported feed encoding.")
    size = response.headers.get("content-length")
    if size is not None and (not size.isdecimal() or int(size) > _LIMIT):
        raise ValueError("Invalid feed size.")
    body = bytearray()
    async for chunk in response.aiter_raw(chunk_size=32 * 1024):
        if len(body) + len(chunk) > _LIMIT:
            raise ValueError("The feed is too large.")
        body.extend(chunk)
    if size is not None and int(size) != len(body):
        raise ValueError("Incomplete feed.")
    return bytes(body)


async def _download(target: str) -> tuple[bytes, str]:
    host = urlsplit(target).hostname
    assert host is not None
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(ipaddress.ip_address(str(info[4][0])) for info in infos))
    if not addresses or any(not a.is_global or a.is_multicast or a.is_reserved for a in addresses):
        raise ValueError("The feed must have a public address.")
    # Use only the resolved addresses for the whole read. Verify TLS for the original host.
    headers = {
        "Host": host,
        "User-Agent": "nanoMuse/public-watch",
        "Accept-Encoding": "identity",
        "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml, text/html",
    }
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=6) as client:
        for address in addresses[:2]:
            try:
                for _ in range(3):
                    async with client.stream(
                        "GET",
                        httpx.URL(target).copy_with(host=str(address)),
                        headers=headers,
                        extensions={"sni_hostname": host},
                    ) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise ValueError("Incomplete feed redirect.")
                            target = normalize_watch("feed", urljoin(target, location))
                            if urlsplit(target).hostname != host:
                                raise ValueError("Feed moved to a different host.")
                            client.cookies.clear()
                            continue
                        return await _feed_body(response), target
                raise ValueError("Too many feed redirects.")
            except (httpx.ConnectError, httpx.ConnectTimeout):
                continue
    raise RuntimeError("Could not connect to the public feed.")


class _FeedTree(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        # CDATA often contains an HTML document with its own doctype. Only an XML DTD matters.
        raise ValueError("Feed document types are unsupported.")


def _entry_text(row: ET.Element, namespace: str) -> str:
    for tag in ("title", "summary", "description"):
        element = row.find(namespace + tag)
        if element is not None:
            text = " ".join(element.itertext()).strip()[:2400]
            if re.search(r"</?[a-z][^>]*>", text, re.I):
                text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
            text = " ".join(text.split())[:240]
            if text:
                return text
    return ""


def _recent(row: ET.Element, namespace: str, now: datetime) -> bool:
    value = (
        row.findtext(namespace + "published")
        or row.findtext(namespace + "pubDate")
        or row.findtext(_DC_DATE)
        or row.findtext(namespace + "updated")
    )
    if not value:
        # A silent first baseline and stable entry identities handle feeds without dates.
        return True
    try:
        stamp = datetime.fromisoformat(value.strip())
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
        except (ValueError, IndexError, TypeError, OverflowError):
            return True  # An optional date is sometimes just a nonstandard human label.
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return now - _WINDOW <= stamp <= now


def parse_feed(body: bytes, target: str, *, now: datetime, base: str = "") -> list[PublicItem]:
    if len(body) > _LIMIT:
        raise ValueError("The feed is too large.")
    root = ET.fromstring(body, parser=ET.XMLParser(target=_FeedTree()))
    if root.tag == _ATOM + "feed":
        ns, parent, entry = _ATOM, root, "entry"
    elif root.tag == _RDF + "RDF":
        ns, parent, entry = _RSS1, root, "item"
    elif root.tag == "rss" and (channel := root.find("channel")) is not None:
        ns, parent, entry = "", channel, "item"
    else:
        raise ValueError("Expected an RSS or Atom feed.")
    base = urljoin(base or target, root.get(_XML_BASE, ""))
    if parent is not root:
        base = urljoin(base, parent.get(_XML_BASE, ""))
    items: dict[str, PublicItem] = {}
    for row in parent.findall(ns + entry)[:40]:
        if not _recent(row, ns, now):
            continue
        title = _entry_text(row, ns)
        if not title:
            continue
        url = target
        for el in row.findall(ns + "link"):
            link = el.get("href") if ns == _ATOM else el.text
            if link and el.get("rel", "alternate") == "alternate":
                try:
                    row_base = urljoin(base, row.get(_XML_BASE, ""))
                    link_base = urljoin(row_base, el.get(_XML_BASE, ""))
                    url = normalize_watch("feed", urljoin(link_base, link.strip()))
                    break
                except ValueError:
                    continue
        identity = (
            row.findtext(ns + "id") or row.findtext(ns + "guid") or row.get(_RDF + "about") or ""
        ).strip() or (url if url != target else title)
        key = "feed:" + hashlib.sha256((target + "\n" + identity).encode()).hexdigest()
        items.setdefault(key, PublicItem(key, title, url))
    return list(items.values())


class _FeedLinks(HTMLParser):
    """Read publisher-declared feeds in the HTML head. Body links do not identify a feed."""

    def __init__(self) -> None:
        super().__init__()
        self.in_head = False
        self.finished = False
        self.links: list[str] = []
        self.base = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "head" and not self.finished:
            self.in_head = True
        if tag == "body":
            self.finished = True
        if not self.in_head or self.finished:
            return
        data = dict(attrs)
        href = data.get("href") or ""
        if tag == "base" and not self.base:
            self.base = href
        if (
            tag == "link"
            and len(self.links) < 32
            and "alternate" in (data.get("rel") or "").lower().split()
            and (data.get("type") or "").lower().split(";")[0].strip()
            in {"application/atom+xml", "application/rss+xml"}
        ):
            self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.finished = True


def _advertised_feed(body: bytes, site: str) -> str:
    head = _FeedLinks()
    head.feed(body[: 128 * 1024].decode("utf-8", errors="replace"))
    base = urljoin(site, head.base)
    urls = set()
    for href in head.links:
        if not href:
            continue
        try:
            url = normalize_watch("feed", urljoin(base, href))
        except ValueError:
            continue
        if urlsplit(url).hostname == urlsplit(site).hostname and url != site:
            urls.add(url)
    if len(urls) != 1:
        raise ValueError("Choose a specific RSS or Atom feed from this website.")
    return urls.pop()


async def fetch_feed(target: str, *, now: datetime) -> tuple[str, list[PublicItem]]:
    target = normalize_watch("feed", target)
    try:
        async with asyncio.timeout(15):
            body, base = await _download(target)
            if re.match(
                rb"\s*(?:<!doctype\s+html\b|<html\b|<head\b)",
                body.removeprefix(b"\xef\xbb\xbf"),
                re.I,
            ):
                advertised = _advertised_feed(body, base)
                body, base = await _download(advertised)
        return base, parse_feed(body, base, now=now.astimezone(UTC), base=base)
    except (httpx.HTTPError, OSError, ET.ParseError, ValueError, LookupError):
        raise RuntimeError("Could not read a complete public feed") from None
