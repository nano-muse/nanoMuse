"""Offline public feed fixtures. No DNS or HTTP calls leave these tests."""

import asyncio
import socket
from datetime import UTC, datetime
from functools import partial

import httpx
import pytest

from nanomuse.server import public_feed
from nanomuse.server.public_feed import fetch_feed, parse_feed

NOW = datetime(2026, 5, 17, 12, tzinfo=UTC)
FEED = "https://example.org/blog/feed"
RSS = b"""<rss version="2.0"><channel><item>
  <title>Registration opened</title><guid>article-1</guid><link>/events/spring</link>
  <pubDate>Sat, 16 May 2026 10:00:00 +0000</pubDate>
  <description><![CDATA[<!DOCTYPE html><html><body>Publication text.</body></html>]]></description>
</item><item><guid>article-1</guid><title>Duplicate</title></item>
<item><title>From the archive</title><pubDate>Wed, 01 Jan 2020 00:00:00 GMT</pubDate></item>
<item><title>Upcoming</title><pubDate>Sun, 31 May 2026 10:00:00 GMT</pubDate></item>
<item><description><![CDATA[<p>Short notice <b>for customers</b></p>]]></description>
<link>https://example.org/announcement?access=private</link></item>
</channel></rss>"""


def test_rss_keys_dates_plain_text_and_conservative_article_links():
    rows = parse_feed(RSS, FEED, now=NOW)
    assert [(r.text, r.url) for r in rows] == [
        ("Registration opened", "https://example.org/events/spring"),
        ("Short notice for customers", FEED),
    ]
    revised = parse_feed(RSS.replace(b"Registration opened", b"Open registration"), FEED, now=NOW)
    assert [r.key for r in rows] == [r.key for r in revised]


def test_atom_namespace_fallback_and_relative_xml_base():
    doc = b"""<feed xmlns="http://www.w3.org/2005/Atom" xml:base="/news/">
    <entry xml:base="releases/"><id>publication:8</id><updated>2026-05-16T12:00:00Z</updated>
    <title type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">Version <b>three</b></div></title>
    <link rel="self" href="internal.atom"/>
    <link rel="alternate" href="https://example.org:8443/disallowed"/>
    <link xml:base="v3/" href="notes"/></entry></feed>"""
    items = parse_feed(doc, FEED, now=NOW)
    assert len(items) == 1 and items[0].text == "Version three"
    assert items[0].url == "https://example.org/news/releases/v3/notes"


def test_rdf_namespaced_items():
    feed = b"""<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns="http://purl.org/rss/1.0/"><item rdf:about="original-id">
    <title>Community notes</title><link>https://example.org/notes</link></item></rdf:RDF>"""
    assert parse_feed(feed, FEED, now=NOW)[0].url == "https://example.org/notes"


def test_reject_dtd_but_accept_doctype_text_in_rss_description():
    with pytest.raises(ValueError, match="document types"):
        parse_feed(b"<!DOCTYPE rss>" + RSS, FEED, now=NOW)
    assert parse_feed(RSS, FEED, now=NOW)


def hook(monkeypatch, handler, *, ips=("8.8.8.8",)):
    async def resolve(host, port, **kwargs):
        assert (host, port) == ("example.org", 443)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    client = partial(httpx.AsyncClient, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(public_feed.httpx, "AsyncClient", client)


async def test_transport_pins_address_preserves_tls_host_and_never_replays_cookies(monkeypatch):
    paths = []

    def respond(r):
        paths.append(r.url.path)
        assert r.method == "GET" and r.url.host == "8.8.8.8" and r.url.scheme == "https"
        assert r.headers["host"] == "example.org" and r.extensions["sni_hostname"] == "example.org"
        assert "Cookie" not in r.headers and "Authorization" not in r.headers
        if len(paths) == 1:
            return httpx.Response(
                301, headers={"Location": "/blog/canonical/rss", "Set-Cookie": "sample=1"}
            )
        return httpx.Response(
            200, stream=httpx.ByteStream(RSS), headers={"Content-Length": str(len(RSS))}
        )

    hook(monkeypatch, respond)
    _, items = await fetch_feed(FEED, now=NOW)
    assert paths == ["/blog/feed", "/blog/canonical/rss"] and len(items) == 2


async def test_feed_tries_another_checked_address_after_connect_failure(monkeypatch):
    hosts = []

    def respond(r):
        hosts.append(r.url.host)
        if len(hosts) == 1:
            raise httpx.ConnectError("address unavailable")
        return httpx.Response(200, stream=httpx.ByteStream(RSS))

    hook(monkeypatch, respond, ips=("8.8.8.8", "1.1.1.1"))
    assert (await fetch_feed(FEED, now=NOW))[1]
    assert hosts == ["8.8.8.8", "1.1.1.1"]


@pytest.mark.parametrize("ips", [("127.0.0.1",), ("8.8.8.8", "192.168.0.1"), ("224.0.0.2",), ()])
async def test_feed_requires_every_resolved_address_to_be_public(monkeypatch, ips):
    hook(monkeypatch, lambda _: pytest.fail("unexpected GET"), ips=ips)
    with pytest.raises(RuntimeError):
        await fetch_feed(FEED, now=NOW)


@pytest.mark.parametrize(
    "status,headers,body",
    [
        (200, {"Content-Length": "10"}, b"abc"),
        (206, {}, RSS),
        (200, {}, b"<rss>"),
        (200, {}, b"x" * (1024 * 1024 + 1)),
        (301, {"Location": "https://other.example.org/rss"}, b""),
        (302, {"Location": "https://example.org/account?key=example"}, b""),
    ],
)
async def test_partial_reads_and_invalid_redirects_do_not_create_baselines(
    monkeypatch, status, headers, body
):
    hook(
        monkeypatch,
        lambda _: httpx.Response(status, headers=headers, stream=httpx.ByteStream(body)),
    )
    with pytest.raises(RuntimeError):
        await fetch_feed(FEED, now=NOW)


async def test_site_uses_its_one_advertised_feed_without_following_page_links(monkeypatch):
    paths = []
    page = b"""<!DOCTYPE html><html><head><base href="/news/">
        <link rel="alternate" type="application/atom+xml" href="/news/atom">
        <link rel="alternate" type="application/atom+xml" href="atom">
        </head><body><a href="/private">more</a></body></html>"""

    def respond(r):
        paths.append(r.url.path)
        return httpx.Response(200, stream=httpx.ByteStream(page if len(paths) == 1 else RSS))

    hook(monkeypatch, respond)
    feed, items = await fetch_feed("https://example.org", now=NOW)
    assert paths == ["/", "/news/atom"] and feed == "https://example.org/news/atom"
    assert items[0].text == "Registration opened"


@pytest.mark.parametrize(
    "links",
    [
        '<link rel="alternate" type="application/rss+xml" href="https://other.example.org/feed">',
        '<link rel="alternate" type="application/atom+xml" href="/a"><link rel="alternate" type="application/rss+xml" href="/b">',
        '</head><body><link rel="alternate" type="application/rss+xml" href="/tracking">',
    ],
)
async def test_homepage_without_one_clear_feed_does_not_follow_another_link(monkeypatch, links):
    paths = []

    def respond(r):
        paths.append(r.url.path)
        return httpx.Response(
            200, stream=httpx.ByteStream(("<html><head>" + links + "</head></html>").encode())
        )

    hook(monkeypatch, respond)
    with pytest.raises(RuntimeError):
        await fetch_feed("https://example.org", now=NOW)
    assert paths == ["/"]
