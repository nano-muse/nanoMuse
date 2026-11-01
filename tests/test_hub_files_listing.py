"""A hub directory listing that was cut says so.

(The rest of the hub tests skip on Windows for their POSIX shell; this one builds a
directory only, so it runs everywhere.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanomuse.hub import actions


def test_a_cut_directory_listing_says_it_was_cut(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(actions, "FILES_MAX", 3)
        cut = actions.run("files", {"path": str(tmp_path)})
        full = actions.run("files", {"path": str(tmp_path / "f0.txt")})
    assert len(cut["entries"]) == 3 and cut["truncated"] is True and cut["total"] == 5
    assert "truncated" not in full  # a single file is never a cut listing
