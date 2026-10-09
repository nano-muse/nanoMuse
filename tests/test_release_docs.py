"""scripts/release-docs.py: the News lists are milestones and stay as written; the version moves
everywhere else."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "release-docs.py"

README = """# nanoMuse

Latest: **1.0.0 Keel**.

## 🗞️ News

- `2026-10-07` 📄 Our paper is available on [arXiv](https://arxiv.org/abs/2610.08699).
- `2026-10-09` 🚀 Version [1.0.0 Keel](https://github.com/nano-muse/nanoMuse/releases/tag/v1.0.0) is out.
- `2026-09-25` 🎉 nanoMuse is released.

| **Android** | [nanoMuse-1.0.0-arm64.apk](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-1.0.0-arm64.apk) |
"""


@pytest.fixture(scope="module")
def release_docs() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_docs", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_news_lines_stay_as_written_and_the_version_moves_elsewhere(
    release_docs: ModuleType,
) -> None:
    text, left = release_docs.edit_page(README, "1.0.0", "1.0.1", "Keel", "Still")
    lines = text.split("\n")
    news = [line for line in lines if release_docs.NEWS_LINE.match(line)]
    assert news == [
        "- `2026-10-07` 📄 Our paper is available on [arXiv](https://arxiv.org/abs/2610.08699).",
        "- `2026-10-09` 🚀 Version [1.0.0 Keel]"
        "(https://github.com/nano-muse/nanoMuse/releases/tag/v1.0.0) is out.",
        "- `2026-09-25` 🎉 nanoMuse is released.",
    ]
    assert "Latest: **1.0.1 Still**." in text
    assert "download/v1.0.1/nanoMuse-1.0.1-arm64.apk" in text
    assert left == 0
    # the list is still one block in the same place
    assert lines.index(news[0]) == README.split("\n").index(news[0])


def test_a_major_version_is_a_milestone_and_a_smaller_one_is_not(release_docs: ModuleType) -> None:
    assert release_docs.is_major("1.0.0") and release_docs.is_major("2.0.0")
    assert not release_docs.is_major("1.0.1")
    assert not release_docs.is_major("1.1.0")
    assert not release_docs.is_major("0.1.41")


def test_a_milestone_line_keeps_its_words_through_two_releases(release_docs: ModuleType) -> None:
    """1.0.0's line says more than the link; two releases later it still says exactly that,
    with its own date, version and tag, and nothing was added to the list by the script."""
    page = (
        "- `2026-10-09` 🚀 Version [1.0.0 Keel]"
        "(https://github.com/nano-muse/nanoMuse/releases/tag/v1.0.0) is out, for the phone, the"
        " desktop and the browser; it installs over the version before and keeps your data.\n"
        "- `2026-10-08` 🤗 Our paper is on [Hugging Face Daily Papers]"
        "(https://huggingface.co/papers/2610.08699), ranked third on the list for October 8.\n"
    )
    once, _ = release_docs.edit_page(page, "1.0.0", "1.0.1", "Keel", "Still")
    twice, left = release_docs.edit_page(once, "1.0.1", "1.1.0", "Still", "Reach")
    assert twice == page
    assert left == 0


def test_a_page_without_news_only_moves_the_version(release_docs: ModuleType) -> None:
    page = "Download [v1.0.0](…/tag/v1.0.0) · 1.0.0 Keel · nanoMuse-1.0.0-arm64.apk · 1.0.0-win"
    text, left = release_docs.edit_page(page, "1.0.0", "1.0.1", "Keel", "Still")
    assert (
        text
        == "Download [v1.0.1](…/tag/v1.0.1) · 1.0.1 Still · nanoMuse-1.0.1-arm64.apk · 1.0.1-win"
    )
    assert left == 0


def _tree(tmp_path: Path) -> None:
    """A repository root with the pages the script edits."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n- a line\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(README, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "zh").mkdir()
    (tmp_path / "docs" / "readme").mkdir()
    (tmp_path / "docs" / "index.md").write_text("[v1.0.0](…/tag/v1.0.0)\n", encoding="utf-8")
    (tmp_path / "docs" / "zh" / "index.md").write_text("[v1.0.0](…/tag/v1.0.0)\n", encoding="utf-8")
    (tmp_path / "docs" / "readme" / "README_zh.md").write_text(README, encoding="utf-8")
    (tmp_path / "docs" / "release-notes-template.md").write_text(
        "Codenames: Foundation, Keel (CHANGELOG.md has the list).\n", encoding="utf-8"
    )


def test_dry_run_prints_and_writes_nothing(
    release_docs: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    _tree(tmp_path)
    before = {p: p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.md")}

    code = release_docs.main(["1.0.0", "1.0.1", "Keel", "Still", "2026-10-20", "--dry-run"])

    assert code == 0
    out = capsys.readouterr().out
    assert "README.md: News, left as written" in out
    assert "  - `2026-10-09` 🚀 Version [1.0.0 Keel]" in out
    assert "dry run, nothing written" in out
    assert "no News line" in out
    assert {p: p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.md")} == before


def test_a_major_version_asks_for_a_news_line_by_hand(
    release_docs: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    _tree(tmp_path)

    code = release_docs.main(["1.0.0", "2.0.0", "Keel", "Reach", "2027-01-01"])

    assert code == 0
    out = capsys.readouterr().out
    assert "a News line for 2.0.0 Reach (`2027-01-01`, first in the list" in out
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    # the script wrote the version everywhere but the News list, and added no line to it
    assert "Latest: **2.0.0 Reach**." in readme
    assert "download/v2.0.0/nanoMuse-2.0.0-arm64.apk" in readme
    news = [line for line in readme.split("\n") if release_docs.NEWS_LINE.match(line)]
    assert news == [line for line in README.split("\n") if release_docs.NEWS_LINE.match(line)]
    assert "## [2.0.0] - 2027-01-01 · Reach" in (tmp_path / "CHANGELOG.md").read_text(
        encoding="utf-8"
    )
