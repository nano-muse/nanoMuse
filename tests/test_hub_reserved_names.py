"""The hub's file actions refuse a name Windows cannot hold, as the files tool does.

(The rest of the hub tests skip on Windows for their POSIX shell; this one writes
nothing, so it runs everywhere.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanomuse.hub import actions
from nanomuse.tools import files as files_module


@pytest.mark.parametrize(
    "name",
    [
        "NUL",
        "NUL.txt",
        "con.log",
        "COM¹",
        "LPT².txt",
        "report ",
        "report./notes.txt",
        r"NUL\notes.txt",
    ],
)
def test_a_windows_device_name_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    # the files module's own switch, not os.name (see its docstring)
    monkeypatch.setattr(files_module, "ON_WINDOWS", True, raising=False)
    with pytest.raises(actions.ActionError) as e:
        actions.file_put(str(tmp_path / name), "eA==")
    assert e.value.code == "bad_name"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "name",
    [
        "NUL.txt",
        "AUX.md",
        " NUL.txt",
        "COM³.log",
        "report ",
        "folder./notes.txt",
        r"folder \notes.txt",
        r"\\.\NUL",
    ],
)
async def test_files_validate_the_original_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(files_module, "ON_WINDOWS", True)
    result = await files_module.Files(workspace=tmp_path).execute(
        action="write", path=name, content="x"
    )
    assert not result.ok
    assert list(tmp_path.iterdir()) == []


def test_regular_windows_paths_and_posix_names_stay_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(files_module, "ON_WINDOWS", True)
    for name in (".", "..", r"C:\notes\file.txt", r"\\server\share\file.txt", "console.txt"):
        assert files_module.refuses_windows_path(name) is None
    monkeypatch.setattr(files_module, "ON_WINDOWS", False)
    for name in ("NUL.txt", "report.", "report "):
        assert files_module.refuses_windows_path(name) is None
