from __future__ import annotations

import pytest

from nanomuse.server.watch_discovery import (
    MAX_CANDIDATES,
    normalize_watch,
    reference_watches,
    suggest_watches,
)

REPO = "https://github.com/Example-Org/Project"
SCHOLAR = "https://scholar.google.com/citations?user=aBcD_234efGH&hl=en"


@pytest.mark.parametrize(
    ("text", "kind", "target", "confirmed"),
    [
        (f"I maintain {REPO}.", "github_repo", "example-org/project", True),
        (
            f"最近忙着整理文档，我在 GitHub 上开源的仓库是 {REPO}，新版本还要再测两天。",
            "github_repo",
            "example-org/project",
            True,
        ),
        (f"{REPO} 是我维护的项目", "github_repo", "example-org/project", True),
        (f"I contribute to {REPO}", "github_repo", "example-org/project", False),
        (f"Your project: {REPO}", "github_repo", "example-org/project", False),
        ("我的 GitHub 用户名是 Example-Org。", "github_user", "example-org", True),
        (
            "我的 GitHub 账号是 https://github.com/Example-Org\x00\u200b ",
            "github_user",
            "example-org",
            True,
        ),
        ("My GitHub handle is @Example-Org.", "github_user", "example-org", True),
        (
            "My GitHub account is https://github.com/Example-Org.",
            "github_user",
            "example-org",
            True,
        ),
        (
            "My GitHub account is github.com/Example-Org, I use it for releases.",
            "github_user",
            "example-org",
            True,
        ),
        (
            "我的 GitHub 账号是 https://github.com/Example-Org，主要用于开源。",
            "github_user",
            "example-org",
            True,
        ),
        (
            "My GitHub account is @Example-Org, I maintain several repos.",
            "github_user",
            "example-org",
            True,
        ),
        ("My OpenAlex ID is A123456.", "research_author", "A123456", True),
        (
            "My ORCID is https://orcid.org/0000-0002-1825-0097",
            "research_author",
            "0000-0002-1825-0097",
            True,
        ),
        (f"我的谷歌学术主页是 {SCHOLAR}。", "scholar_profile", "aBcD_234efGH", False),
        ("我的论文是 https://doi.org/10.5555/Sample。", "research_work", "10.5555/sample", True),
        ("Track citations to 10.5555/Sample", "research_work", "10.5555/sample", True),
        (f"每周帮我看看这个仓库的新 issue: {REPO}", "github_repo", "example-org/project", True),
        (
            "Keep me updated on new papers about Graph Neural Networks.",
            "research_topic",
            "graph neural networks",
            True,
        ),
        ("请持续跟踪对抗鲁棒性相关的新论文。", "research_topic", "对抗鲁棒性", True),
        ("我的研究方向是图神经网络的可解释性。", "research_topic", "图神经网络的可解释性", False),
        ("I study multimodal retrieval.", "research_topic", "multimodal retrieval", False),
        (
            "Watch my feed https://example.org/lab/changes",
            "feed",
            "https://example.org/lab/changes",
            True,
        ),
        (
            "我的订阅源是 https://example.org/lab/changes",
            "feed",
            "https://example.org/lab/changes",
            False,
        ),
    ],
)
def test_limited_identity_evidence(text: str, kind: str, target: str, confirmed: bool) -> None:
    [suggestion] = suggest_watches(text)
    assert (suggestion.kind, suggestion.target, suggestion.confirmed) == (kind, target, confirmed)
    # Even direct-looking text in an email or a connector can only suggest a source.
    [external] = suggest_watches(text, personal=False)
    assert external.target == target
    assert external.confirmed is False


@pytest.mark.parametrize(
    "text",
    [
        f"Compare this repository with {REPO}",
        f"My colleague maintains {REPO}",
        f"If I owned it, my repo would be {REPO}",
        f"Don't track {REPO}.",
        f"I used to maintain {REPO}",
        f"我不想关注 {REPO}",
        f"我的仓库是 {REPO}。\n请不要自动关注。",
        f"My repository is {REPO}\nPlease don't monitor this.",
        f"Example code follows\n    I maintain {REPO}",
        f"I maintain {REPO} and https://github.com/example-org/Other",
        f"Please review this: [my repository]({REPO})",
        "My Scholar profile is Jane Example.",
        "我研究机器学习",
        "我的研究方向是地址",
        "I run A12345",
        f"Forwarded message\nI maintain {REPO}",
        f"Summarize the following:\nI maintain {REPO}",
        f"这句原话是“\nI maintain {REPO}\n”",
        f"请翻译以下示例：\n我的仓库是 {REPO}",
        f"\x60\x60\x60\nI maintain {REPO}\n\x60\x60\x60",
        f"> I maintain {REPO}",
        f"“我维护的项目是 {REPO}”",
        f"I maintain {REPO}?",
        f"我的仓库是 {REPO} 吗？",
        "I maintain https://github.com/settings/profile",
        "I maintain https://github.com/example/project?access_token=example",
        "I maintain http://github.com/example/project",
        "My OpenAlex ID is §19§",  # literal placeholder has no external authority
        "I study 1234",
        "I study １２３４",
        "I study ¾ ¾ ¾",
        "I study x_ _x",
    ],
)
def test_no_relationship_no_registration(text: str) -> None:
    assert suggest_watches(text) == []


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/a.rss",
        "https://127.0.0.1/a.rss",
        "https://[::1]/a.rss",
        "https://example.org:443/a.rss",
        "https://user@example.org/a.rss",
        "https://localhost/a.rss",
        "https://test.localhost/a.rss",
        "https://test.internal/a.rss",
        "https://example.org/a.rss?token=x",
        "https://example.org/a.rss#x",
        "https://example.org/../a.rss",
        "https://example.org/%2e%2e/a.rss",
        "https://example.org//other.org/a.rss",
        "https://[::/a.rss",
    ],
)
def test_ineligible_feeds_are_never_suggested(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_watch("feed", url)
    assert not suggest_watches(f"Watch my feed {url}")


def test_research_identity_requires_exact_source() -> None:
    assert normalize_watch("scholar_profile", SCHOLAR) == "aBcD_234efGH"
    with pytest.raises(ValueError):
        normalize_watch("scholar_profile", SCHOLAR + "&view_op=view_citation")
    with pytest.raises(ValueError):
        normalize_watch("research_author", "0000-0002-1825-0098")
    with pytest.raises(ValueError):
        normalize_watch("github_user", "https://github.com/search")


def test_reference_is_always_pending_and_compares_distinct_turns() -> None:
    [first] = reference_watches(f"帮我看看这里的文档 {REPO}。")
    [second] = reference_watches(f"讨论里说 {REPO}/issues/12 仍然需要处理。")
    assert first.kind == "github_repo"
    assert first.target == second.target == "example-org/project"
    assert not first.confirmed and not second.confirmed
    assert not suggest_watches(f"帮我看看这里的文档 {REPO}。")
    assert len(reference_watches(f"{REPO}/issues/12 和 {REPO}/issues/13")) == 1


@pytest.mark.parametrize(
    "text",
    [
        "https://example.org/an-unrelated-web-page",
        f"举例：\n{REPO}",
        f"> {REPO}",
        f"不再跟踪 {REPO}",
        f"Forwarded message\n{REPO}",
        "Book a room in A1022",
        "My GitHub account is https://github.com/Exam\x00ple-Org",
        "https://example.org/first?url=https://github.com/a/b",
    ],
)
def test_incidental_references_exclude_ambiguous_or_unusable_evidence(text: str) -> None:
    assert reference_watches(text) == []


def test_bounded_deduplication_does_not_discard_direct_evidence() -> None:
    text = "\n".join(
        [f"Your repository: {REPO}", f"I maintain {REPO}"]
        + [f"Watch https://github.com/example-org/project-{i}" for i in range(20)]
    )
    watches = suggest_watches(text)
    assert len(watches) == MAX_CANDIDATES
    assert watches[0].confirmed
    assert suggest_watches("x" * 6100 + f"\nWatch {REPO}") == []


def test_ongoing_work_in_natural_language_is_a_suggestion_without_claiming_ownership():
    for text in (
        f"这周我一直在帮 {REPO} 处理用户反馈，下个月要发版。",
        f"We regularly review pull requests for {REPO} before each release.",
    ):
        assert [(c.target, c.confirmed) for c in suggest_watches(text)] == [
            ("example-org/project", False)
        ]
        assert not suggest_watches(text, personal=False)
