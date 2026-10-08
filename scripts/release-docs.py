#!/usr/bin/env python3
"""The release-day edits to the pages that name the current version.

    scripts/release-docs.py <old> <new> <old-codename> <new-codename> <date> [--dry-run]
    scripts/release-docs.py 0.1.40 0.1.41 Clear Still 2026-10-20

- ``CHANGELOG.md``: a ``## [<new>] - <date> · <Codename>`` heading goes right under
  ``## [Unreleased]`` so the Unreleased bullets fall under it; the empty ``### Cloud / Runtime /
  …`` headings for the next version are put back by hand (see the previous release commit).
- ``README.md``, ``docs/readme/README_*.md``, ``docs/index.md``, ``docs/zh/index.md``: ``<old> <OldName>`` becomes
  ``<new> <NewName>``, every ``v<old>`` tag and ``nanoMuse-<old>`` asset name moves to the new
  version. In a *News* list (lines ``- `<date>` …``) the one line that names the latest version
  (``[<old> <OldName>](…/tag/v<old>)``) is rewritten for the new version and its date and moved
  to the top, so the list stays newest first; the paper, the first release and the other
  milestones keep their lines, their dates and their order. The homepage's ``index.html`` is
  edited by hand the same way.
- ``docs/release-notes-template.md``: the new codename joins the list.
- ``docs/roadmap.md`` (the past-releases table) and ``docs/parity.md`` (cells that said "next
  release") are edited by hand.

``--dry-run`` writes nothing and prints, for every page with a News list, its first three News
lines as they would be after the edit.

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


def edit_page(
    text: str, old: str, new: str, oldname: str, newname: str, date: str
) -> tuple[str, int]:
    """The page after the release edit, and how many lines still name the old version.

    Outside the News lists every mention moves to the new version. Inside a News list only
    the line that names the latest version changes: it gets the new version, codename and
    date and goes to the top of its list; the other milestone lines are left as written, in
    their order."""
    lines = text.split("\n")
    blocks = news_blocks(lines)
    in_news = {i for start, end in blocks for i in range(start, end)}
    out = [
        line if i in in_news else move_version(line, old, new, oldname, newname)
        for i, line in enumerate(lines)
    ]
    for start, end in blocks:
        block = out[start:end]
        latest = [i for i, line in enumerate(block) if f"/tag/v{old}" in line]
        if not latest:
            continue
        i = latest[0]
        line = move_version(block[i], old, new, oldname, newname)
        line = NEWS_LINE.sub(f"- `{date}` ", line, count=1)
        block = [line] + block[:i] + block[i + 1 :]
        out[start:end] = block
    left = sum(1 for i, line in enumerate(out) if old in line and i not in in_news)
    return "\n".join(out), left


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
        text, left = edit_page(p.read_text(encoding="utf-8"), old, new, oldname, newname, date)
        if dry_run:
            lines = text.split("\n")
            for start, end in news_blocks(lines):
                print(f"{name}: News after the edit")
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
    print(
        ("dry run, nothing written. " if dry_run else "")
        + "by hand now: the homepage's News list (the same move), docs/roadmap.md's "
        "past-releases row, docs/parity.md, the empty Unreleased headings in CHANGELOG.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
