"""The iOS strings catalogue is one JSON object per key. A key listed twice is valid JSON for
most parsers, which then keep one of the two entries and drop the other without a word; Xcode
does the same when it compiles the catalogue, so the translations that ship depend on which
entry won. This test parses the catalogue with every key pair in hand and fails on the first
repeat, at any depth, so a merge or a hand edit cannot leave two entries behind."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

IOS = Path(__file__).resolve().parents[1] / "android" / "src" / "ios"
CATALOGUES = sorted(IOS.glob("*.xcstrings"))


def _duplicates(path: Path) -> list[str]:
    found: list[str] = []

    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        for key, n in Counter(k for k, _ in pairs).items():
            if n > 1:
                found.append(key)
        return dict(pairs)

    with path.open(encoding="utf-8") as f:
        json.load(f, object_pairs_hook=hook)
    return found


@pytest.mark.skipif(not CATALOGUES, reason="no iOS tree in this checkout")
@pytest.mark.parametrize("path", CATALOGUES, ids=lambda p: p.name)
def test_no_duplicate_keys_in_xcstrings(path: Path) -> None:
    assert _duplicates(path) == [], f"{path.name} lists these keys more than once"


def test_the_check_sees_a_repeat(tmp_path: Path) -> None:
    twice = tmp_path / "twice.xcstrings"
    twice.write_text('{"strings": {"a": {}, "b": {}, "a": {}}}', encoding="utf-8")
    assert _duplicates(twice) == ["a"]


LOCALES = ("de", "es", "fr", "ja", "ko", "ru", "zh-Hans", "zh-Hant")
APP_LOCALIZED = re.compile(r'AppLocalized\(\s*"((?:[^"\\]|\\.)*)"')


def _swift_literal(raw: str) -> str:
    return raw.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")


def _keys_in(text: str) -> set[str]:
    """The literal AppLocalized keys in ``text``; an interpolated one is not a catalogue key."""
    return {
        _swift_literal(m.group(1)) for m in APP_LOCALIZED.finditer(text) if "\\(" not in m.group(1)
    }


def _marked_spots(text: str) -> str:
    """The lines of an upstream file that are ours: each ``// nanoMuse:`` comment with the
    statement or block that follows it (the lines indented deeper than the comment, and the
    brace that closes them). Upstream's own lines, and their strings, are left out."""
    lines = text.split("\n")
    ours: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "nanoMuse:" not in line:
            i += 1
            continue
        base = len(line) - len(line.lstrip(" "))
        ours.append(line)
        # a comment on its own line marks the statement or block below it; a trailing comment
        # marks the line it sits on (plus any continuation indented under it)
        j, first = i + 1, line.lstrip().startswith("//")
        while j < len(lines):
            cur = lines[j]
            if not cur.strip():
                j += 1
                continue
            indent = len(cur) - len(cur.lstrip(" "))
            if first or indent > base:
                ours.append(cur)
                first = False
                j += 1
                continue
            if indent == base and cur.lstrip().startswith("}"):
                ours.append(cur)
                j += 1
            break
        i = j
    return "\n".join(ours)


def _our_keys() -> set[str]:
    """Every string our Swift passes to AppLocalized as a literal: all of NanoMuse/, plus the
    ``// nanoMuse:`` spots inside upstream's files."""
    keys: set[str] = set()
    for path in sorted(IOS.rglob("*.swift")):
        text = path.read_text(encoding="utf-8")
        keys |= _keys_in(text if "NanoMuse" in path.parts else _marked_spots(text))
    return keys


@pytest.mark.skipif(not (IOS / "NanoMuse").is_dir(), reason="no iOS tree in this checkout")
def test_every_nanomuse_string_is_in_the_catalogue_in_every_locale() -> None:
    """A user-visible string is added in English first, then 简体中文, then every other locale the
    catalogue already has (AGENTS.md). The keys our own views use must therefore exist and carry
    all nine languages; upstream's strings are upstream's business."""
    with (IOS / "Localizable.xcstrings").open(encoding="utf-8") as f:
        strings = json.load(f)["strings"]
    ours = _our_keys()
    assert len(ours) > 500, "the regex stopped seeing our AppLocalized calls"
    missing_keys = sorted(k for k in ours if k not in strings)
    assert missing_keys == [], f"not in Localizable.xcstrings: {missing_keys[:10]}"
    short: dict[str, list[str]] = {}
    for key in sorted(ours):
        entry = strings[key]
        if entry.get("shouldTranslate") is False:
            continue
        have = entry.get("localizations") or {}
        lacking = [loc for loc in LOCALES if loc not in have]
        if lacking:
            short[key] = lacking
    assert short == {}, f"{len(short)} of our strings lack a locale, e.g. {list(short.items())[:5]}"


def test_marked_spots_take_the_block_under_the_comment_and_nothing_else() -> None:
    text = (
        'Text(AppLocalized("upstream line"))\n'
        "// nanoMuse: ours\n"
        'Section(AppLocalized("ours one")) {\n'
        '    Text(AppLocalized("ours two"))\n'
        "\n"
        "}\n"
        'Text(AppLocalized("upstream again"))\n'
        '    .help(AppLocalized("still upstream")) // nanoMuse: trailing marker\n'
        'Text(AppLocalized("not ours"))\n'
    )
    assert _keys_in(_marked_spots(text)) == {"ours one", "ours two", "still upstream"}
    assert (
        _keys_in('AppLocalized("a\\"b")') == {'a"b'}
        and _keys_in('AppLocalized("x \\(y)")') == set()
    )
