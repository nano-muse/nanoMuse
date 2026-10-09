#!/usr/bin/env python3
"""The release-day edits to the pages that name the current version.

    scripts/release-docs.py <old> <new> <old-codename> <new-codename> <date> [--dry-run]
    scripts/release-docs.py 0.1.40 0.1.41 Clear Still 2026-10-20

- ``CHANGELOG.md``: a ``## [<new>] - <date> · <Codename>`` heading goes right under
  ``## [Unreleased]`` so the Unreleased bullets fall under it; the empty ``### Cloud / Runtime /
  …`` headings for the next version are put back by hand (see the previous release commit).
- ``README.md``, ``docs/readme/README_*.md``, ``docs/index.md``, ``docs/zh/index.md``: ``<old> <OldName>`` becomes
  ``<new> <NewName>``, every ``v<old>`` tag and ``nanoMuse-<old>`` asset name moves to the new
  version. A *News* list (lines ``- `<date>` …``) is left as written: its lines are milestones,
  and a milestone's line keeps its date, its version and its words for good. A major version
  (``x.0.0``) is a milestone and gets a new line, written by hand and put first, in the ten
  READMEs and on the homepage's ``index.html``; a smaller release gets none, the download
  tables and the version line say what the current version is.
- ``docs/release-notes-template.md``: the new codename joins the list.
- ``docs/roadmap.md`` (the past-releases table) and ``docs/parity.md`` (cells that said "next
  release") are edited by hand.

``--dry-run`` writes nothing and prints, for every page with a News list, its first three News
lines (unchanged by this script) so the reviewer sees what a new milestone line would go above.

Run from the repository root. ``scripts/release-bump.sh`` comes before this, ``scripts/rebrand.py``
in between; CONTRIBUTING.md has the whole recipe.
"""

from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

NEWS_LINE = re.compile(r"^- `(\d{4}-\d{2}-\d{2})` ")

PAGES = [
    "README.md",
    "docs/index.md",
    "docs/zh/index.md",
]


def news_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """``(start, end)`` of every run of consecutive News lines, ``end`` exclusive."""
    blocks: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        if NEWS_LINE.match(lines[i]):
            j = i
            while j < len(lines) and NEWS_LINE.match(lines[j]):
                j += 1
            blocks.append((i, j))
            i = j
        else:
            i += 1
    return blocks


def move_version(line: str, old: str, new: str, oldname: str, newname: str) -> str:
    """Every mention of the old version in one line becomes the new one."""
    line = line.replace(f"{old} {oldname}", f"{new} {newname}")
    line = line.replace(f"v{old}", f"v{new}").replace(f"nanoMuse-{old}", f"nanoMuse-{new}")
    return re.sub(rf"(?<![\d.]){re.escape(old)}-", f"{new}-", line)


def edit_page(text: str, old: str, new: str, oldname: str, newname: str) -> tuple[str, int]:
    """The page after the release edit, and how many lines still name the old version.

    Outside the News lists every mention moves to the new version. A News list is left as
    written: every line of it is a milestone and keeps its date, its version and its words."""
    lines = text.split("\n")
    blocks = news_blocks(lines)
    in_news = {i for start, end in blocks for i in range(start, end)}
    out = [
        line if i in in_news else move_version(line, old, new, oldname, newname)
        for i, line in enumerate(lines)
    ]
    left = sum(1 for i, line in enumerate(out) if old in line and i not in in_news)
    return "\n".join(out), left


def is_major(version: str) -> bool:
    """``x.0.0``: a milestone with a News line of its own."""
    parts = version.split(".")
    return len(parts) == 3 and parts[1] == "0" and parts[2] == "0"


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    if len(argv) != 5:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    old, new, oldname, newname, date = argv
    if not Path("pyproject.toml").is_file():
        print("run from the repository root", file=sys.stderr)
        return 2

    changelog = Path("CHANGELOG.md")
    s = changelog.read_text(encoding="utf-8")
    marker = "## [Unreleased]\n\n"
    if marker not in s or f"## [{new}]" in s:
        print(
            "CHANGELOG.md: no empty Unreleased marker, or the version is already there",
            file=sys.stderr,
        )
        return 1
    if not dry_run:
        changelog.write_text(
            s.replace(marker, f"{marker}## [{new}] - {date} · {newname}\n\n", 1), encoding="utf-8"
        )

    pages = [*PAGES, *sorted(glob.glob("docs/readme/README_*.md"))]
    for name in pages:
        p = Path(name)
        text, left = edit_page(p.read_text(encoding="utf-8"), old, new, oldname, newname)
        if dry_run:
            lines = text.split("\n")
            for start, end in news_blocks(lines):
                print(f"{name}: News, left as written")
                for line in lines[start : min(end, start + 3)]:
                    print(f"  {line}")
        else:
            p.write_text(text, encoding="utf-8")
        print(f"{name}: {left} line(s) still naming {old} outside the News list")

    template = Path("docs/release-notes-template.md")
    s = template.read_text(encoding="utf-8")
    if f", {oldname} (CHANGELOG" not in s:
        print(
            "docs/release-notes-template.md: the codename list does not end with the previous name",
            file=sys.stderr,
        )
        return 1
    if not dry_run:
        template.write_text(
            s.replace(f", {oldname} (CHANGELOG", f", {oldname}, {newname} (CHANGELOG"),
            encoding="utf-8",
        )
    news = (
        f"a News line for {new} {newname} (`{date}`, first in the list, the same words in the "
        "ten READMEs and on the homepage; the earlier versions' lines stay), "
        if is_major(new)
        else "no News line (the News lists are milestones; this is not a major version), "
    )
    print(
        ("dry run, nothing written. " if dry_run else "")
        + "by hand now: "
        + news
        + "the homepage's version line and download links, docs/roadmap.md's past-releases row, "
        "docs/parity.md, the empty Unreleased headings in CHANGELOG.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
