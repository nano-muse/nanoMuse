"""The hub's file actions refuse a name Windows cannot hold, as the files tool does.

(The rest of the hub tests skip on Windows for their POSIX shell; this one writes
nothing, so it runs everywhere.)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nanomuse.hub import actions


def test_a_windows_device_name_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "name", "nt")
    with pytest.raises(actions.ActionError) as e:
        actions.file_put(str(tmp_path / "NUL"), "eA==")  # "a"
    assert "device name" in e.value.message
    assert list(tmp_path.iterdir()) == []
