"""The hub's file actions refuse a name Windows cannot hold, as the files tool does.

(The rest of the hub tests skip on Windows for their POSIX shell; this one writes
nothing, so it runs everywhere.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanomuse.hub import actions
from nanomuse.tools import files as files_module


def test_a_windows_device_name_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the files module's own switch, not os.name (see its docstring)
    monkeypatch.setattr(files_module, "ON_WINDOWS", True, raising=False)
    with pytest.raises(actions.ActionError) as e:
        actions.file_put(str(tmp_path / "NUL"), "eA==")  # "a"
    assert "device name" in e.value.message
    assert list(tmp_path.iterdir()) == []
