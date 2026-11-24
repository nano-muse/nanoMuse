"""Offline fixtures for the read-only public watch adapters."""

from datetime import UTC, datetime
from functools import partial

import httpx
import pytest

from nanomuse.server import public_sources
from nanomuse.server.public_sources import PublicItem, fetch_public, normalize_target

NOW = datetime(2026, 5, 17, 12, tzinfo=UTC)


def api(monkeypatch, handler):
    def respond(request):
        assert request.method == "GET" and request.url.scheme == "https"
        assert request.url.host in {"api.github.com", "api.openalex.org"}
        assert "Authorization" not in request.headers and "Cookie" not in request.headers
        return handler(request)

    client = partial(httpx.AsyncClient, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(public_sources.httpx, "AsyncClient", client)


def issue(number=2, **overrides):
    return {
        "state": "open",
        "number": number,
        "title": "A new review request",
        "repository_url": "https://api.github.com/repos/Team/Project",
        "html_url": "https://example.org/untrusted",
        "created_at": "2026-05-17T01:23:45Z",
        **overrides,
    }


@pytest.mark.parametrize(
    "kind,target,scope",
    [
        ("github_repo", "https://github.com/Team/Project/", "repo:team/project"),
        ("github_user", "Team", "user:team"),
    ],
)
async def test_owned_public_open_issues_only(monkeypatch, kind, target, scope):
    def respond(request):
        assert request.url.path == "/search/issues"
        assert request.url.params["q"] == scope + " is:issue is:open created:>=2026-05-03"
        assert request.url.params["sort"] == "created"
        return httpx.Response(
            200,
            json={
                "incomplete_results": False,
                "items": [
                    issue(),
                    issue(3, pull_request={}),
                    issue(4, state="closed"),
                    issue(5, created_at="2026-01-01T00:00:00Z"),
                    issue(6, created_at="2027-01-01T00:00:00Z"),
                ],
            },
        )

    api(monkeypatch, respond)
    assert await fetch_public(kind, target, now=NOW) == [
        PublicItem(
            "github:team/project#2",
            "Open issue team/project#2 (2026-05-17): A new review request",
            "https://github.com/team/project/issues/2",
        )
    ]


@pytest.mark.parametrize(
    "data",
    [
        {"incomplete_results": True, "items": []},
        {"incomplete_results": False},
        {
            "incomplete_results": False,
            "items": [issue(repository_url="https://api.github.com/repos/other/project")],
        },
        {"incomplete_results": False, "items": [issue(number=-1)]},
    ],
)
async def test_partial_or_wrong_owner_cannot_advance_github_baseline(monkeypatch, data):
    api(monkeypatch, lambda _: httpx.Response(200, json=data))
    with pytest.raises(RuntimeError):
        await fetch_public("github_user", "team", now=NOW)


def work(number, title="Proof notes", day="2026-05-16"):
    return {"id": f"https://openalex.org/W{number}", "title": title, "publication_date": day}


@pytest.mark.parametrize(
    "author,criterion",
    [
        ("https://openalex.org/a123", "authorships.author.id:A123"),
        ("https://orcid.org/0000-0000-0000-001X", "authorships.author.orcid:0000-0000-0000-001X"),
    ],
)
async def test_author_tracks_publications_and_recent_citations_of_older_works(
    monkeypatch, author, criterion
):
    def respond(request):
        assert request.url.path == "/works"
        filters = request.url.params["filter"].split(",")
        if filters[0] == criterion:
            assert filters[1:] == ["to_publication_date:2026-05-17"]
            rows = [work(11), work(12, day="2021-01-01")]
        else:
            assert filters == [
                "cites:W11|W12",
                "from_publication_date:2026-02-16",
                "to_publication_date:2026-05-17",
            ]
            rows = [work(13, "Follow-up"), work(11), work(14, day="2026-05-20")]
        return httpx.Response(200, json={"results": rows})

    api(monkeypatch, respond)
    items = await fetch_public("research_author", author, now=NOW)
    assert [item.key for item in items] == ["openalex:W11", "openalex:W13"]
    assert items[1].url == "https://openalex.org/W13" and "Follow-up" in items[1].text


async def test_doi_resolution_uses_exact_match_and_only_public_citation_lookup(monkeypatch):
    def respond(request):
        if request.url.path == "/works/https://doi.org/10.1234/example":
            return httpx.Response(
                200,
                json={"id": "https://openalex.org/W123", "doi": "https://doi.org/10.1234/Example"},
            )
        assert request.url.params["filter"].startswith("cites:W123,")
        return httpx.Response(200, json={"results": [work(14)]})

    api(monkeypatch, respond)
    items = await fetch_public("research_work", "https://doi.org/10.1234/EXAMPLE", now=NOW)
    assert len(items) == 1 and "citing DOI 10.1234/example" in items[0].text


@pytest.mark.parametrize(
    "kind,target,rows",
    [
        (
            "research_work",
            "10.1234/expected",
            {"id": "https://openalex.org/W123", "doi": "https://doi.org/10.1234/different"},
        ),
        (
            "research_topic",
            "quantum optics",
            {
                "results": [
                    {
                        "id": "https://example.org/",
                        "title": "A title",
                        "publication_date": "2026-05-16",
                    }
                ]
            },
        ),
    ],
)
async def test_invalid_research_response_is_unavailable(monkeypatch, kind, target, rows):
    api(monkeypatch, lambda _: httpx.Response(200, json=rows))
    with pytest.raises(RuntimeError):
        await fetch_public(kind, target, now=NOW)


async def test_topic_sends_bounded_literal_query_and_filters_stale_results(monkeypatch):
    def respond(request):
        assert request.url.params["search"] == '"quantum optics"'
        assert (
            request.url.params["filter"]
            == "from_publication_date:2026-02-16,to_publication_date:2026-05-17"
        )
        return httpx.Response(200, json={"results": [work(20), work(21, day="2020-04-01")]})

    api(monkeypatch, respond)
    assert [i.key for i in await fetch_public("research_topic", "Quantum optics", now=NOW)] == [
        "openalex:W20"
    ]


@pytest.mark.parametrize(
    "kind,target",
    [
        ("scholar_profile", "scholarid"),
        ("research_author", "Someone Famous"),
        ("research_author", "0000-0000-0000-0011"),
        ("research_work", "10.1234/../../authors"),
        ("github_user", "team OR user:other"),
        ("github_repo", "https://example.org/team/project"),
        ("research_topic", "project: secret"),
        ("research_topic", "https://example.org/key"),
    ],
)
def test_invalid_identifiers_cannot_address_arbitrary_services(kind, target):
    with pytest.raises(ValueError):
        normalize_target(kind, target)


@pytest.mark.parametrize(
    "status,headers,content",
    [
        (403, {}, b""),
        (429, {"retry-after": "900"}, b""),
        (302, {"Location": "https://example.org"}, b""),
        (206, {}, b'{"results":[]}'),
        (200, {}, b'{"results"'),
        (200, {"Content-Length": "5000000"}, b"{}"),
        (200, {}, b" " * (2 * 1024 * 1024 + 1)),
    ],
)
async def test_http_failures_are_never_reported_as_empty_samples(
    monkeypatch, status, headers, content
):
    api(
        monkeypatch,
        lambda _: httpx.Response(status, headers=headers, stream=httpx.ByteStream(content)),
    )
    with pytest.raises(RuntimeError):
        await fetch_public("research_topic", "quantum optics", now=NOW)


def tagged_work(n, *, score=0.92, topic=17, day="2026-05-16"):
    return {
        **work(n, day=day),
        "type": "article",
        "primary_topic": {
            "id": f"https://openalex.org/T{topic}",
            "display_name": f"Specific topic {topic}",
            "score": score,
        },
    }


async def test_related_read_requires_a_recurring_primary_topic_and_filters_recent_publications(
    monkeypatch,
):
    query_count = 0

    def respond(request):
        nonlocal query_count
        query_count += 1
        params = request.url.params
        filters = params["filter"]
        if filters.startswith("authorships.author.id:A123,"):
            assert "primary_topic" in params["select"]
            return httpx.Response(
                200,
                json={
                    "results": [
                        tagged_work(11),
                        tagged_work(12),
                        tagged_work(13),
                        tagged_work(14, topic=18),
                        tagged_work(15, score=0.3),
                    ]
                },
            )
        if filters.startswith("cites:"):
            return httpx.Response(200, json={"results": [work(27)]})
        assert filters == (
            "primary_topic.id:T17,authorships.author.id:!A123,type:article|preprint|review,"
            "from_publication_date:2026-05-10,to_publication_date:2026-05-17"
        )
        assert params["per_page"] == "5" and "search" not in params
        return httpx.Response(
            200,
            json={
                "results": [
                    tagged_work(21),
                    tagged_work(22, score=0.4),
                    tagged_work(23, topic=22),
                    tagged_work(24, day="2026-05-08"),
                    tagged_work(27),
                ]
            },
        )

    api(monkeypatch, respond)
    rows = await fetch_public("research_author", "A123", now=NOW)
    assert query_count == 3
    related = [r for r in rows if r.text.startswith("Related research")]
    assert len(related) == 1 and related[0].key == "openalex:W21"
    assert "Specific topic 17" in related[0].text
    assert next(r for r in rows if r.key == "openalex:W27").text.startswith("Paper citing")


@pytest.mark.parametrize(
    "portfolio",
    [
        [tagged_work(1), tagged_work(2)],
        [tagged_work(1), tagged_work(1), tagged_work(1)],
        [tagged_work(i, score=0.3) for i in range(1, 6)],
        [tagged_work(i, day="2020-01-01") for i in range(1, 6)],
        [
            tagged_work(1),
            tagged_work(2),
            tagged_work(3),
            tagged_work(4, topic=18),
            tagged_work(5, topic=19),
            tagged_work(6, topic=20),
        ],
    ],
)
async def test_uncertain_or_stale_author_interests_do_not_trigger_a_topic_query(
    monkeypatch, portfolio
):
    def respond(request):
        filters = request.url.params["filter"]
        if filters.startswith("authorships.author.id:A123,"):
            return httpx.Response(200, json={"results": portfolio})
        assert filters.startswith("cites:")
        return httpx.Response(200, json={"results": []})

    api(monkeypatch, respond)
    await fetch_public("research_author", "A123", now=NOW)
