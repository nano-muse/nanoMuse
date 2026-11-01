"""Exports hold the file they checked, including when another process changes a path."""

from __future__ import annotations

import io
import os
import stat
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from nanomuse.server import data_export as export

EXCLUDED = b"excluded fixture content"


def entries(data: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(export.agent_data_zip(data))) as archive:
        return {name: archive.read(name) for name in archive.namelist() if name != "README.txt"}


def symlink(path: Path, target: Path, *, directory: bool = False) -> None:
    try:
        path.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


@pytest.mark.parametrize("name", ["profile.json", "threads/chat.json", "sessions/nested/chat.json"])
def test_export_rejects_hardlinks_to_excluded_data(tmp_path: Path, name: str) -> None:
    secret = tmp_path / "vault.key"
    secret.write_bytes(EXCLUDED)
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.hardlink_to(secret)
    except OSError as exc:
        pytest.skip(f"hardlinks unavailable: {exc}")
    assert entries(tmp_path) == {}


def test_export_keeps_regular_nested_files_and_skips_links(tmp_path: Path) -> None:
    (tmp_path / "profile.json").write_bytes(b"profile")
    nested = tmp_path / "threads" / "nested"
    nested.mkdir(parents=True)
    (nested / "chat.json").write_bytes(b"chat")
    secret = tmp_path / "vault.key"
    secret.write_bytes(EXCLUDED)
    symlink(nested / "linked.json", secret)
    symlink(tmp_path / "sessions", nested, directory=True)
    assert entries(tmp_path) == {"profile.json": b"profile", "threads/nested/chat.json": b"chat"}


@pytest.mark.skipif(os.name == "nt", reason="Windows denies replacement while the handle is open")
@pytest.mark.parametrize("name", ["profile.json", "threads/chat.json"])
def test_export_does_not_reopen_a_file_replaced_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    secret = tmp_path / "vault.key"
    secret.write_bytes(EXCLUDED)
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"allowed")
    identity = path.stat().st_ino
    fstat = os.fstat
    swapped = False

    def swap(fd: int) -> os.stat_result:
        nonlocal swapped
        info = fstat(fd)
        if not swapped and info.st_ino == identity and stat.S_ISREG(info.st_mode):
            swapped = True
            path.unlink()
            path.symlink_to(secret)
        return info

    monkeypatch.setattr(export.os, "fstat", swap)
    result = entries(tmp_path)
    assert swapped
    assert result.get(name) in (None, b"allowed")
    assert EXCLUDED not in result.values()


@pytest.mark.skipif(os.name == "nt", reason="POSIX no-follow open race")
def test_export_rejects_file_replaced_just_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "vault.key").write_bytes(EXCLUDED)
    candidate = tmp_path / "profile.json"
    candidate.write_bytes(b"allowed")
    original = export._open

    def swap(path: Path, *, directory: bool = False, parent_fd: int | None = None) -> int:
        if path == candidate:
            path.unlink()
            path.symlink_to(tmp_path / "vault.key")
        return original(path, directory=directory, parent_fd=parent_fd)

    monkeypatch.setattr(export, "_open", swap)
    assert entries(tmp_path) == {}


@pytest.mark.skipif(os.name == "nt", reason="Windows pins ancestor names with deny-delete handles")
@pytest.mark.parametrize("folder", ["threads", "threads/nested"])
def test_export_uses_pinned_directory_after_name_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, folder: str
) -> None:
    data = tmp_path / "data"
    root = data / folder
    root.mkdir(parents=True)
    (root / "chat.json").write_bytes(b"allowed")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "chat.json").write_bytes(EXCLUDED)
    original = os.listdir
    identity = root.stat().st_ino
    swapped = False

    def swap(path: str | bytes | os.PathLike[str] | int) -> list[str]:
        nonlocal swapped
        names = original(path)
        if isinstance(path, int) and os.fstat(path).st_ino == identity:
            root.rename(tmp_path / "previous")
            root.symlink_to(outside, target_is_directory=True)
            swapped = True
        return names

    monkeypatch.setattr(export.os, "listdir", swap)
    assert entries(data) == {f"{folder}/chat.json": b"allowed"}
    assert swapped


@pytest.mark.skipif(os.name == "nt", reason="POSIX no-follow directory-open race")
def test_export_rejects_directory_replaced_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    folder = data / "threads"
    folder.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "chat.json").write_bytes(EXCLUDED)
    original = export._open

    def swap(path: Path, *, directory: bool = False, parent_fd: int | None = None) -> int:
        if path == folder:
            folder.rmdir()
            folder.symlink_to(outside, target_is_directory=True)
        return original(path, directory=directory, parent_fd=parent_fd)

    monkeypatch.setattr(export, "_open", swap)
    assert entries(data) == {}


def test_export_reads_size_from_open_file_and_skips_growth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export, "MAX_FILE_BYTES", 32)
    path = tmp_path / "profile.json"
    path.write_bytes(b"small")
    identity = path.stat().st_ino
    fstat = os.fstat
    grown = False

    def grow(fd: int) -> os.stat_result:
        nonlocal grown
        info = fstat(fd)
        if not grown and info.st_ino == identity and stat.S_ISREG(info.st_mode):
            grown = True
            path.write_bytes(b"x" * 100)
        return info

    monkeypatch.setattr(export.os, "fstat", grow)
    assert entries(tmp_path) == {}
    assert grown


def test_export_skips_oversized_files_but_keeps_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export, "MAX_FILE_BYTES", 16)
    (tmp_path / "profile.json").write_bytes(b"x" * 16)
    (tmp_path / "feed_posts.json").write_bytes(b"y" * 17)
    assert entries(tmp_path) == {"profile.json": b"x" * 16}


@pytest.mark.skipif(os.name == "nt", reason="POSIX special files")
def test_export_skips_fifo_without_waiting_for_a_writer(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "profile.json")
    assert entries(tmp_path) == {}


def test_export_missing_directory_still_has_a_readme(tmp_path: Path) -> None:
    assert entries(tmp_path / "missing") == {}


def test_export_keeps_metadata_from_the_validated_file(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_bytes(b"profile")
    timestamp = 1_700_000_000
    os.utime(path, (timestamp, timestamp))
    with zipfile.ZipFile(io.BytesIO(export.agent_data_zip(tmp_path))) as archive:
        info = archive.getinfo("profile.json")
        assert info.date_time == time.localtime(timestamp)[:6]
        assert info.external_attr >> 16 == path.stat().st_mode & 0xFFFF


@pytest.mark.skipif(os.name != "nt", reason="Windows handle sharing and junctions")
def test_windows_export_pins_ancestors_and_skips_junctions(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "profile.json").write_bytes(b"allowed")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "chat.json").write_bytes(EXCLUDED)
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(data / "threads"), str(outside)],
        check=True,
        capture_output=True,
    )
    with export._data_directory(data):
        with pytest.raises(PermissionError):
            data.rename(tmp_path / "moved")
    assert entries(data) == {"profile.json": b"allowed"}


@pytest.mark.skipif(os.name != "nt", reason="Windows file handle lifetime")
def test_windows_export_file_handle_denies_replacement(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_bytes(b"allowed")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(EXCLUDED)
    with export._data_directory(tmp_path) as (root, parent_fd):
        fd = export._open(root / path.name, parent_fd=parent_fd)
        try:
            with pytest.raises(PermissionError):
                replacement.replace(path)
            assert os.read(fd, 100) == b"allowed"
        finally:
            os.close(fd)
    replacement.replace(path)  # handles were released, including the pinned ancestors
