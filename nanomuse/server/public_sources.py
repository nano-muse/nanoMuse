"""Bounded, anonymous observations from the GitHub and OpenAlex public APIs."""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

_GITHUB = "https://api.github.com"
_OPENALEX = "https://api.openalex.org"
_LOGIN = r"[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?"
_REPO = rf"{_LOGIN}/[a-z0-9._-]{{1,100}}"
_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.ASCII)
_MAX_BYTES = 2 * 1024 * 1024
_LIMIT = 25
_PAPER_WINDOW = timedelta(days=90)
_ISSUE_WINDOW = timedelta(days=14)


@dataclass(frozen=True)
class PublicItem:
    key: str
    text: str
    url: str


def normalize_target(kind: str, target: str) -> str:
    """Only fixed public identifiers or a short literal topic reach these APIs."""
    value = target.strip().lower()
    if kind in {"github_repo", "github_user"}:
        value = value.removeprefix("https://github.com/").removesuffix("/")
        pattern = _REPO if kind == "github_repo" else _LOGIN
        if re.fullmatch(pattern, value, re.ASCII) and value.split("/")[-1] not in {".", ".."}:
            return value
    if kind == "research_work":
        value = value.removeprefix("https://doi.org/")
        if len(value) <= 200 and _DOI.fullmatch(value) and not {".", ".."} & set(value.split("/")):
            return value
    if kind == "research_author":
        author_id = value.removeprefix("https://openalex.org/").upper()
        if re.fullmatch(r"A[1-9][0-9]{0,14}", author_id):
            return author_id
        orcid = value.removeprefix("https://orcid.org/").upper()
        if re.fullmatch(r"(?:[0-9]{4}-){3}[0-9]{3}[0-9X]", orcid):
            digits = orcid.replace("-", "")
            total = 0
            for digit in digits[:-1]:
                total = (total + int(digit)) * 2
            if digits[-1] == "0123456789X"[(12 - total % 11) % 11]:
                return orcid
    if kind == "research_topic":
        value = " ".join(value.split())
        if re.fullmatch(r"[\w -]{4,80}", value) and any(c.isalpha() for c in value):
            return value
    raise ValueError("Unsupported public source or invalid target")


async def _json(client: httpx.AsyncClient, url: str, params: dict[str, str]) -> dict[str, Any]:
    # No redirects, network-derived URLs, authentication or ambient session cookies.
    async with client.stream("GET", url, params=params) as response:
        if response.status_code != 200:
            raise RuntimeError(f"Public API returned HTTP {response.status_code}")
        size = response.headers.get("content-length")
        if size is not None and (not size.isdecimal() or int(size) > _MAX_BYTES):
            raise ValueError("Oversized public API response")
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise ValueError("Unexpected public API content encoding")
        body = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
            if len(body) + len(chunk) > _MAX_BYTES:
                raise ValueError("Oversized public API response")
            body.extend(chunk)
    obj = json.loads(body)
    if not isinstance(obj, dict):
        raise ValueError("Invalid public API response")
    return obj


def _rows(obj: dict[str, Any], field: str) -> list[dict[str, Any]]:
    rows = obj.get(field)
    if (
        not isinstance(rows, list)
        or len(rows) > _LIMIT
        or not all(isinstance(r, dict) for r in rows)
    ):
        raise ValueError("Invalid public API list")
    return rows


def _title(row: dict[str, Any]) -> str:
    text = row.get("title")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Missing public record title")
    return " ".join(text.split())[:240]


async def _issues(
    client: httpx.AsyncClient, kind: str, target: str, now: datetime
) -> list[PublicItem]:
    scope = "repo" if kind == "github_repo" else "user"
    start = now - _ISSUE_WINDOW
    data = await _json(
        client,
        f"{_GITHUB}/search/issues",
        {
            "q": f"{scope}:{target} is:issue is:open created:>={start.date().isoformat()}",
            "sort": "created",
            "order": "desc",
            "per_page": str(_LIMIT),
        },
    )
    if data.get("incomplete_results") is not False:
        raise ValueError("Incomplete GitHub search")
    items = []
    for row in _rows(data, "items"):
        if "pull_request" in row or row.get("state") == "closed":
            continue
        if row.get("state") != "open":
            raise ValueError("Invalid issue state")
        repository = row["repository_url"]
        prefix = f"{_GITHUB}/repos/"
        if not isinstance(repository, str) or not repository.startswith(prefix):
            raise ValueError("Invalid issue repository")
        repo = normalize_target("github_repo", repository[len(prefix) :])
        if target != (repo if scope == "repo" else repo.split("/")[0]):
            raise ValueError("Unexpected issue repository")
        number = row["number"]
        if type(number) is not int or number < 1:
            raise ValueError("Invalid issue number")
        created = datetime.fromisoformat(row["created_at"])
        if start <= created <= now:
            label = f"{repo}#{number}"
            items.append(
                PublicItem(
                    f"github:{label}",
                    f"Open issue {label} ({created.date()}): {_title(row)}",
                    f"https://github.com/{repo}/issues/{number}",
                )
            )
    return items


def _work_id(row: dict[str, Any]) -> str:
    match = re.fullmatch(r"https://openalex\.org/(W[1-9][0-9]{0,14})", row["id"])
    if match is None:
        raise ValueError("Invalid OpenAlex work ID")
    return match.group(1)


async def _works(
    client: httpx.AsyncClient,
    filters: str,
    *,
    search: str = "",
    topics: bool = False,
    limit: int = _LIMIT,
) -> list[dict[str, Any]]:
    params = {
        "filter": filters,
        "sort": "publication_date:desc",
        "per_page": str(limit),
        "select": "id,title,publication_date" + (",type,primary_topic" if topics else ""),
    }
    if search:
        params["search"] = f'"{search}"'
    return _rows(await _json(client, f"{_OPENALEX}/works", params), "results")


def _papers(rows: list[dict[str, Any]], label: str, start: date, end: date) -> list[PublicItem]:
    items = []
    for row in rows:
        work = _work_id(row)
        published = date.fromisoformat(row["publication_date"])
        if start <= published <= end:
            items.append(
                PublicItem(
                    f"openalex:{work}",
                    f"{label} ({published}): {_title(row)}",
                    f"https://openalex.org/{work}",
                )
            )
    return items


def _primary_topic(row: dict[str, Any]) -> tuple[str, str] | None:
    topic = row.get("primary_topic")
    if not isinstance(topic, dict):
        return None
    key, name, score = topic.get("id"), topic.get("display_name"), topic.get("score")
    if not isinstance(key, str) or not re.fullmatch(
        r"https://openalex\.org/T[1-9][0-9]{0,14}", key
    ):
        return None
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(score, (float, int))
        or isinstance(score, bool)
    ):
        return None
    if not 0.8 <= score <= 1:
        return None
    return key.rsplit("/", 1)[1], " ".join(name.split())[:120]


async def _related(
    client: httpx.AsyncClient, portfolio: list[dict[str, Any]], field: str, author: str, today: date
) -> list[PublicItem]:
    # Choose one OpenAlex primary topic using public catalog metadata only. Untagged or
    # low-confidence papers still count in the denominator; a lone mention never starts a search.
    distinct = {_work_id(row): row for row in portfolio}
    papers = [
        row
        for row in distinct.values()
        if row.get("type") in {"article", "preprint", "review"}
        and today - timedelta(days=730) <= date.fromisoformat(row["publication_date"]) <= today
    ][:10]
    votes = Counter(topic for row in papers if (topic := _primary_topic(row)) is not None)
    if not votes:
        return []
    (topic_id, name), count = votes.most_common(1)[0]
    if count < 3 or count * 5 < len(papers) * 3:
        return []
    start = today - timedelta(days=7)
    # Exclude this author's works in the graph, including works outside the sampled portfolio.
    rows = await _works(
        client,
        f"primary_topic.id:{topic_id},{field}:!{author},type:article|preprint|review,"
        f"from_publication_date:{start},to_publication_date:{today}",
        topics=True,
        limit=5,
    )
    matches = [row for row in rows if _primary_topic(row) == (topic_id, name)]
    return _papers(
        matches, f'Related research in the author’s recurring topic "{name}"', start, today
    )[:3]


async def _research(
    client: httpx.AsyncClient, kind: str, target: str, today: date
) -> list[PublicItem]:
    start = today - _PAPER_WINDOW
    dates = f"from_publication_date:{start},to_publication_date:{today}"
    if kind == "research_topic":
        rows = await _works(client, dates, search=target)
        return _papers(rows, f'Research matching "{target}"', start, today)
    authored: list[PublicItem] = []
    related: list[PublicItem] = []
    if kind == "research_work":
        obj = await _json(
            client,
            f"{_OPENALEX}/works/https://doi.org/{quote(target, safe='/')}",
            {"select": "id,doi"},
        )
        if normalize_target("research_work", obj["doi"]) != target:
            raise ValueError("Unexpected DOI")
        ids = [_work_id(obj)]
        label = f"Paper citing DOI {target}"
    else:
        field = "authorships.author.id" if target.startswith("A") else "authorships.author.orcid"
        # Older works can still receive new citations. Fetch the author's most recent 25 works
        # independently of publication age, then match their IDs in a single citation lookup.
        portfolio = await _works(
            client, f"{field}:{target},to_publication_date:{today}", topics=True
        )
        ids = [_work_id(row) for row in portfolio]
        authored = _papers(portfolio, f"Work by author {target}", start, today)
        label = f"Paper citing a work by author {target}"
        related = await _related(client, portfolio, field, target, today)
    if not ids:
        return authored
    citing = await _works(client, f"cites:{'|'.join(ids)},{dates}")
    # A newer paper can cite an earlier paper by the same author.
    items = {item.key: item for item in authored}
    for item in [*_papers(citing, label, start, today), *related]:
        items.setdefault(item.key, item)
    return list(items.values())


async def fetch_public(kind: str, target: str, *, now: datetime) -> list[PublicItem]:
    """Get the latest bounded sample. Unavailable and malformed responses never become baselines."""
    target = normalize_target(kind, target)
    now = now.astimezone(UTC)
    headers = {
        "User-Agent": "nanoMuse/public-watch",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }
    try:
        async with (
            asyncio.timeout(18),
            httpx.AsyncClient(headers=headers, timeout=8, follow_redirects=False) as client,
        ):
            if kind in {"github_repo", "github_user"}:
                return await _issues(client, kind, target, now)
            return await _research(client, kind, target, now.date())
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        raise RuntimeError("Could not read a complete public source sample") from None
