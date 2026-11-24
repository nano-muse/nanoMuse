"""Recognise durable interests and public identifiers in locally available context.

Discovery is offline. A direct declaration and a reference in connected material have
different authority, even when their text is identical.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import SplitResult, parse_qs, urlsplit

from nanomuse.server.public_sources import normalize_target
from nanomuse.server.watch_grammar import (
    _BROAD,
    _LOGIN,
    _ONGOING,
    _OWN,
    _QUOTED,
    _REFERENCE,
    _RELATED,
    _REQUEST,
    _RESERVED,
    _TOPIC_INTEREST,
    _TOPIC_REQUEST,
    _UNCERTAIN,
)

MAX_TEXT = 6000
MAX_CANDIDATES = 4


@dataclass(frozen=True)
class WatchCandidate:
    kind: str
    target: str
    label: str
    confirmed: bool


def _url_parts(ref: str) -> SplitResult:
    u = urlsplit(ref)
    if u.scheme != "https" or not u.hostname or u.netloc.lower() != u.hostname or u.fragment:
        raise ValueError("Expected a public HTTPS URL")
    return u


def normalize_watch(kind: str, target: str) -> str:
    """Validate a watch selector and return its stable identity, or raise ValueError."""
    if (
        not target
        or len(target) > 512
        or any(c.isspace() for c in target)
        and kind != "research_topic"
    ):
        raise ValueError("Invalid watch target")
    if kind == "scholar_profile":
        if target.startswith("https://"):
            u = _url_parts(target)
            query = parse_qs(u.query, keep_blank_values=True)
            ids = query.get("user", [])
            if (
                u.hostname != "scholar.google.com"
                or u.path != "/citations"
                or not (query.keys() <= {"user", "hl"} and len(ids) == 1)
            ):
                raise ValueError("Expected a Google Scholar profile")
            target = ids[0]
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,32}", target):
            raise ValueError("Invalid Scholar ID")
        return target
    if kind == "feed":
        u = _url_parts(target)
        host = u.hostname or ""
        path = u.path.lstrip("/")
        if (
            u.query
            or "?" in target
            or "#" in target
            or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}", host)
            or host.endswith((".local", ".internal", ".localhost", ".lan", ".home", ".onion"))
            or not re.fullmatch(r"[A-Za-z0-9._~/-]{0,256}", path)
            or any(p in {".", ".."} for p in path.split("/"))
            or u.path.startswith("//")
        ):
            raise ValueError("Expected a public feed URL")
        return f"https://{host}{u.path or '/'}"
    value = normalize_target(kind, target)
    if kind in {"github_repo", "github_user"} and value.split("/")[0] in _RESERVED:
        raise ValueError("Expected a GitHub account")
    return value


def _public_id(ref: str, context: str) -> tuple[str, str] | None:
    if ref.startswith("10."):
        kind = "research_work"
    elif re.fullmatch(r"A[1-9][0-9]{0,14}|(?:[0-9]{4}-){3}[0-9]{3}[0-9X]", ref, re.I):
        kind = "research_author"
    else:
        ref = ref if "://" in ref else "https://" + ref
        try:
            u = _url_parts(ref)
        except ValueError:
            return None
        if u.hostname == "scholar.google.com":
            kind = "scholar_profile"
        elif u.query or u.fragment:
            return None
        elif u.hostname == "github.com":
            ref = u.path.strip("/").removesuffix(".git")
            kind = "github_repo" if "/" in ref else "github_user"
        elif u.hostname in {"doi.org", "dx.doi.org"}:
            kind, ref = "research_work", u.path.lstrip("/")
        elif u.hostname in {"openalex.org", "orcid.org"}:
            kind, ref = "research_author", u.path.lstrip("/")
        elif re.search(
            r"(?:^|/)(?:feed|rss|atom)(?:/|$)|\.(?:atom|rss|xml)$", u.path, re.I
        ) or re.search(r"\b(?:atom|rss|feed)\b|订阅源", context, re.I):
            kind = "feed"
        elif context and re.search(
            r"\b(?:website|site|blog|subscribe to|watch|monitor)\b|网站|官网|博客|订阅|关注",
            context,
            re.I,
        ):
            kind = "feed"
        else:
            return None
    try:
        return kind, normalize_watch(kind, ref)
    except ValueError:
        return None


def _topic(text: str) -> str:
    phrase = " ".join(text.split()).strip()
    if (
        not 4 <= len(phrase) <= 80
        or sum(c.isalpha() for c in phrase) < 4
        or phrase.lower() in _BROAD
    ):
        return ""
    if not re.fullmatch(r"[\w -]+", phrase) or re.search(
        r"[_\d]{3,}|\b(?:my|your|http|and then|please)\b|然后|帮我|我的|地址", phrase, re.I
    ):
        return ""
    if not (len(phrase.split()) >= 2 or len(re.findall(r"[\u3400-\u9fff]", phrase)) >= 4):
        return ""
    return phrase


def _matched_ref(match: re.Match[str]) -> str:
    ref = match.group().rstrip(".,;!?")
    while ref.endswith(")") and ref.count("(") < ref.count(")"):
        ref = ref[:-1]
    return ref


def _candidates(line: str, personal: bool) -> list[WatchCandidate]:
    refs: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        ref = _matched_ref(match)
        refs.append(ref)
        return f"§{len(refs) - 1}§" + match.group()[len(ref) :]

    # Markdown link labels are descriptive text, not evidence of an ownership claim.
    line = re.sub(
        r"\[[^\]\n]{1,120}\]\((https?://[^\s<>]+?)\)(?=[\s.,;!?，。；！、？]|$)", r"\1", line
    )
    # A bare login needs a GitHub label. An existing URL must pass through unchanged;
    # "is" before that URL is a verb, not another person's GitHub handle.
    line = re.sub(
        rf"((?:my github (?:username|handle|login|account)(?: is)?|我的\s*github\s*(?:账号|帐号|账户|用户名)(?:是|为)?)\s*[:：]?\s*)(?!(?:is|at)\b|https?:|github\.com/)@?({_LOGIN})(?=[\s.,，。！!?？]|$)",
        r"\1https://github.com/\2",
        line,
        flags=re.I,
    )
    line = _REFERENCE.sub(substitute, line)
    output: list[WatchCandidate] = []
    for clause in re.split(r"[.。；;！!，]|,\s+", line):
        clause = clause.strip(" \t,，")
        if "?" in clause or "？" in clause or clause.endswith(("吗", "么", "呢")):
            continue
        tokens = list(re.finditer(r"§(\d+)§", clause))
        if not tokens:
            request = _TOPIC_REQUEST.fullmatch(clause)
            topic = request or _TOPIC_INTEREST.fullmatch(clause)
            if topic and (value := _topic(next(v for v in topic.groups() if v))):
                try:
                    target = normalize_watch("research_topic", value)
                except ValueError:
                    continue
                output.append(
                    WatchCandidate("research_topic", target, value, bool(request and personal))
                )
            continue
        if len(tokens) != 1:
            continue
        token = tokens[0]
        evidence = clause[: token.start()] + "@" + clause[token.end() :]
        owned = bool(_OWN.fullmatch(evidence))
        requested = bool(_REQUEST.fullmatch(evidence))
        ongoing = personal and len(evidence) < 220 and _ONGOING.search(evidence)
        if not (owned or requested or ongoing or _RELATED.fullmatch(evidence)):
            continue
        ref = refs[int(token[1])]
        if re.fullmatch(r"A[1-9][0-9]{0,14}", ref, re.I) and "openalex" not in evidence.lower():
            continue
        reading = _public_id(ref, evidence)
        if not reading:
            continue
        kind, target = reading
        # A Scholar profile supplies neither an OpenAlex author ID nor proof that a
        # name match is the same person. Keep it pending for an explicit identity match.
        confirmed = (
            personal and kind != "scholar_profile" and (requested or (owned and kind != "feed"))
        )
        label = f"@{target}" if kind == "github_user" else target
        output.append(WatchCandidate(kind, target, label, confirmed))
    return output


def _evidence_lines(text: str) -> Iterator[str]:
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT].rsplit("\n", 1)[0] if "\n" in text[:MAX_TEXT] else ""
    # A final instruction like "don't monitor this" can qualify a declaration on
    # a previous line. Suppressing this message leaves previously confirmed choices intact.
    if re.search(
        r"(?:don't|don’t|do not|never|stop)\s+(?:(?:automatically|ever)\s+)?(?:watch|track|monitor|follow|subscribe)|"
        r"(?:别再?|不要|不用|不想|停止|取消|不再)(?:(?:自动|定期|持续|帮我))*"
        r"(?:关注|跟踪|追踪|监测|监控|订阅|提醒)",
        text,
        re.I,
    ):
        return
    fenced = False
    quoted_until = ""
    for raw in text.splitlines():
        # Some clipboard integrations append NUL or zero-width space to a copied URL.
        # Discard only trailing delimiters. An invisible character inside can split an ID.
        raw = raw.rstrip(" \t\x00\u200b")
        if "\x00" in raw or "\u200b" in raw:
            continue
        line = " ".join(raw.split())
        if line.startswith(("\x60\x60\x60", "~~~")):
            fenced = not fenced
            continue
        if fenced or raw.startswith(("    ", "\t")) or line.startswith((">", "|", "#", "//")):
            continue
        if quoted_until:
            if quoted_until in line:
                quoted_until = ""
            continue
        for opening, closing in (("“", "”"), ("「", "」"), ("『", "』"), ('"', '"')):
            if opening in line and closing not in line.split(opening, 1)[1]:
                quoted_until = closing
                break
        if quoted_until:
            continue
        if re.search(
            r"forwarded message|转发邮件|(?:以下|下面)(?:是)?(?:引文|引用|示例|转述|聊天记录)|"
            r"(?:example|(?:translate|summari[sz]e|review)(?: the following| this)?|quoted text|transcript|"
            r"(?:he|she|they|someone) (?:said|wrote)|例如|举例|原文|翻译|[他她]说)[：:]\s*$",
            line,
            re.I,
        ):
            break
        if "§" not in line and not _QUOTED.search(line) and not _UNCERTAIN.search(line):
            yield line


def suggest_watches(text: str, *, personal: bool = True) -> list[WatchCandidate]:
    """Return a bounded set of relationship-backed watches without performing any I/O."""
    found: dict[tuple[str, str], WatchCandidate] = {}
    for line in _evidence_lines(text):
        for watch in _candidates(line, personal):
            key = watch.kind, watch.target
            if key in found:
                if watch.confirmed:
                    found[key] = watch
            elif len(found) < MAX_CANDIDATES:
                found[key] = watch
    return list(found.values())


def reference_watches(text: str) -> list[WatchCandidate]:
    """Identify public references for corroboration across distinct personal turns.

    A reference alone confers no permission, however often it occurs. Ordinary webpages and
    names cannot identify an academic author, a GitHub account, or a structured feed.
    """
    found: dict[tuple[str, str], WatchCandidate] = {}
    for line in _evidence_lines(text):
        for match in _REFERENCE.finditer(line):
            ref = _matched_ref(match)
            if re.fullmatch(r"A[1-9][0-9]{0,14}", ref, re.I) and not re.search(
                r"openalex(?:\s+(?:author|id))?\s*[:：]?\s*$", line[: match.start()], re.I
            ):
                continue
            # Issues in separate conversations can corroborate the same repository.
            path = re.fullmatch(
                r"(?:https://)?github\.com/([^/?#]+/[^/?#]+)/(?:issues|pull|discussions)/[1-9][0-9]*",
                ref,
                re.I,
            )
            if path:
                ref = "https://github.com/" + path[1]
            identity = _public_id(ref, "")
            if identity and identity not in found:
                kind, target = identity
                found[identity] = WatchCandidate(kind, target, target, False)
                if len(found) == MAX_CANDIDATES:
                    return list(found.values())
    return list(found.values())
