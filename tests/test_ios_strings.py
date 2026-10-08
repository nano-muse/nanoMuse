"""The iOS strings catalogue is one JSON object per key. A key listed twice is valid JSON for
most parsers, which then keep one of the two entries and drop the other without a word; Xcode
does the same when it compiles the catalogue, so the translations that ship depend on which
entry won. This test parses the catalogue with every key pair in hand and fails on the first
repeat, at any depth, so a merge or a hand edit cannot leave two entries behind."""

from __future__ import annotations

import json
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
