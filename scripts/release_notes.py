#!/usr/bin/env python3
"""Assemble the GitHub release body for a version.

``docs/releases/v<version>.md`` is written by hand — the title, the story, *Highlights*,
*Upgrade Notes*, *Community* and the Chinese version in the ``<details>`` block at the end
(``docs/release-notes-template.md`` is the shape). What GitHub knows is added here, the way
GitHub's own generated notes put it: *What's Changed* (every pull request merged into
``main`` between the previous tag and this one, ``title by @author in url``), *New
Contributors* (whose first merged pull request is in this release), *Contributors*, and
the *Full Changelog* compare link. They land where the notes say ``<!-- pull requests -->``
— before the Chinese block when the marker is missing — so the hand-written part stays
English first with the Chinese at the end.

    scripts/release_notes.py 0.1.25                 # body on stdout; previous tag found
    scripts/release_notes.py 0.1.25 --previous v0.1.24 --target v0.1.25 -o /tmp/notes.md

Needs ``git`` and ``gh`` (signed in). ``scripts/release-apk.sh`` runs it when it publishes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "nano-muse/nanoMuse"
MARKER = "<!-- pull requests -->"
GOOD_FIRST = f"https://github.com/{REPO}/contribute"


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    author: str
    url: str


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def git(*args: str) -> str:
    return run("git", "-C", str(ROOT), *args)


def previous_tag(target: str) -> str:
    """The newest ``v*`` tag reachable from the commit before ``target`` (so a tag on the
    target itself is skipped)."""
    out = git("describe", "--tags", "--abbrev=0", "--match", "v*", f"{target}^").strip()
    if not out:
        raise SystemExit(f"no earlier v* tag before {target}")
    return out


def merged_numbers(previous: str, target: str) -> list[int]:
    """Pull request numbers merged between the two refs, oldest first.

    A pull request merged with a merge commit is read off the commit's subject (``Merge pull
    request #n``); one merged by rebase leaves no such commit, so GitHub is asked which commit
    it recorded as the merge and that commit is looked for in the range. Without ``gh`` the
    merge commits alone are listed."""
    log = git("log", f"{previous}..{target}", "--format=%H %s", "--reverse")
    position: dict[str, int] = {}
    found: dict[int, int] = {}
    for index, line in enumerate(log.splitlines()):
        sha, _, subject = line.partition(" ")
        position[sha] = index
        m = re.search(r"^Merge pull request #(\d+)", subject)
        if m:
            found.setdefault(int(m.group(1)), index)
    try:
        raw = run(
            "gh", "pr", "list", "--repo", REPO, "--state", "merged", "--base", "main",
            "--json", "number,mergeCommit", "--limit", "500",
        )  # fmt: skip
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"gh pr list failed ({exc}); listing merge commits only", file=sys.stderr)
        raw = "[]"
    for item in json.loads(raw):
        sha = str((item.get("mergeCommit") or {}).get("oid") or "")
        if sha in position:
            found.setdefault(int(item["number"]), position[sha])
    return [number for number, _ in sorted(found.items(), key=lambda kv: (kv[1], kv[0]))]


def pull_request(number: int) -> PullRequest:
    raw = run("gh", "pr", "view", str(number), "--repo", REPO, "--json", "number,title,author,url")
    data = json.loads(raw)
    # gh reports a GitHub App as "app/dependabot"; GitHub itself writes "@dependabot".
    author = str((data.get("author") or {}).get("login") or "ghost")
    if author.startswith("app/"):
        author = author[len("app/") :] + "[bot]"
    return PullRequest(
        number=int(data["number"]),
        title=str(data["title"]).strip(),
        author=author,
        url=str(data["url"]),
    )


def first_merged_number(login: str) -> int | None:
    raw = run(
        "gh", "pr", "list", "--repo", REPO, "--author", login, "--state", "merged",
        "--base", "main", "--json", "number", "--limit", "500",
    )  # fmt: skip
    numbers = [int(p["number"]) for p in json.loads(raw)]
    return min(numbers) if numbers else None


def is_bot(login: str) -> bool:
    return login.endswith("[bot]") or login == "ghost"


def mention(login: str) -> str:
    """``dependabot[bot]`` is mentioned as ``@dependabot``, the way GitHub writes it."""
    return login[: -len("[bot]")] if login.endswith("[bot]") else login


def generated(previous: str, target: str, prs: list[PullRequest]) -> str:
    lines: list[str] = ["## What's Changed", ""]
    if prs:
        lines += [f"* {pr.title} by @{mention(pr.author)} in {pr.url}" for pr in prs]
    else:
        lines.append("* No pull requests were merged for this release.")
    lines += ["", "## New Contributors", ""]
    humans = sorted({pr.author for pr in prs if not is_bot(pr.author)}, key=str.lower)
    in_release = {pr.number for pr in prs}
    newcomers: list[str] = []
    for login in humans:
        first = first_merged_number(login)
        if first is not None and first in in_release:
            url = next(pr.url for pr in prs if pr.author == login and pr.number == first)
            newcomers.append(f"* @{login} made their first contribution in {url}")
    if newcomers:
        lines += newcomers
    else:
        lines.append(
            "* No first-time contributors in this release; yours could be the next one: "
            f"[good first issues]({GOOD_FIRST})."
        )
    lines += ["", "## Contributors", ""]
    lines.append(" · ".join(f"@{login}" for login in humans) if humans else "(none)")
    bots = sorted({pr.author for pr in prs if is_bot(pr.author)}, key=str.lower)
    if bots:
        lines.append("")
        lines.append("And the bots: " + ", ".join(f"@{mention(b)}" for b in bots) + ".")
    lines += [
        "",
        f"**Full Changelog**: https://github.com/{REPO}/compare/{previous}...{target}",
    ]
    return "\n".join(lines)


def assemble(notes: str, block: str) -> str:
    """``block`` where the marker is; otherwise before the ``<details>`` Chinese block;
    otherwise at the end."""
    if MARKER in notes:
        return notes.replace(MARKER, block, 1)
    at = notes.find("<details>")
    if at < 0:
        return notes.rstrip("\n") + "\n\n" + block + "\n"
    return notes[:at].rstrip("\n") + "\n\n" + block + "\n\n" + notes[at:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("version", help="x.y.z — reads docs/releases/v<version>.md")
    ap.add_argument(
        "--previous", help="the previous tag (default: the newest v* tag before --target)"
    )
    ap.add_argument(
        "--target", help="the commit or tag of this release (default: v<version>, else HEAD)"
    )
    ap.add_argument(
        "--notes", type=Path, help="the hand-written notes (default: docs/releases/v<version>.md)"
    )
    ap.add_argument("-o", "--output", type=Path, help="write the body here instead of stdout")
    args = ap.parse_args(argv)

    notes_path = args.notes or ROOT / "docs" / "releases" / f"v{args.version}.md"
    if not notes_path.is_file():
        print(f"release notes not found: {notes_path}", file=sys.stderr)
        return 1
    target = args.target
    if not target:
        tag = f"v{args.version}"
        exists = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
            capture_output=True,
        )
        target = tag if exists.returncode == 0 else "HEAD"
    previous = args.previous or previous_tag(target)
    prs = [pull_request(n) for n in merged_numbers(previous, target)]
    body = assemble(notes_path.read_text(encoding="utf-8"), generated(previous, target, prs))
    if args.output:
        args.output.write_text(body, encoding="utf-8")
        print(f"{args.output}: {len(prs)} pull requests since {previous}", file=sys.stderr)
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
