"""Exports hold the file they checked, including when another process changes a path."""

from __future__ import annotations

import ctypes
import io
import os
import sqlite3
import stat
import struct
import subprocess
import sys
import threading
import time
import zipfile
from ctypes import wintypes
from pathlib import Path

import pytest

from nanomuse.server import data_export as export

EXCLUDED = b"excluded fixture content"


def entries(data: Path, databases: dict[str, sqlite3.Connection] | None = None) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(export.agent_data_zip(data, databases=databases))) as archive:
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


def test_export_keeps_a_file_older_than_the_zip_clock(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_bytes(b"profile")
    other = tmp_path / "feed_posts.json"
    other.write_bytes(b"feed")
    os.utime(path, (170000000.0, 170000000.0))  # 1975-06-01, before the zip clock's 1980
    with zipfile.ZipFile(io.BytesIO(export.agent_data_zip(tmp_path))) as archive:
        assert archive.read("profile.json") == b"profile"
        assert archive.read("feed_posts.json") == b"feed"
        assert archive.getinfo("profile.json").date_time == (1980, 1, 1, 0, 0, 0)
        assert archive.testzip() is None


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
        with pytest.raises(PermissionError):
            tmp_path.rename(tmp_path.with_name(f"{tmp_path.name}-moved"))
    assert entries(data) == {"profile.json": b"allowed"}
    data.rename(tmp_path / "moved")  # ancestor handles were released


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


def _set_windows_junction(path: Path, target: Path) -> None:
    """Change an empty directory using only attribute access, which bypasses share locks."""
    if sys.platform != "win32":
        raise OSError("Windows junction fixture")
    else:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create.restype = wintypes.HANDLE
        control = kernel.DeviceIoControl
        control.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        control.restype = wintypes.BOOL
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        handle = create(str(path), 0x100, 7, None, 3, 0x02200000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            substitute = ("\\??\\" + str(target)).encode("utf-16-le")
            printable = str(target).encode("utf-16-le")
            data = struct.pack("<HHHH", 0, len(substitute), len(substitute) + 2, len(printable))
            data += substitute + b"\0\0" + printable + b"\0\0"
            buffer = ctypes.create_string_buffer(
                struct.pack("<LHH", 0xA0000003, len(data), 0) + data
            )
            returned = wintypes.DWORD()
            if not control(
                handle, 0x900A4, buffer, len(buffer) - 1, None, 0, ctypes.byref(returned), None
            ):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            close(handle)


@pytest.mark.skipif(os.name != "nt", reason="Windows in-place junction conversion")
def test_windows_export_uses_parent_handle_after_reparse_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "threads"
    folder.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "chat.json").write_bytes(EXCLUDED)
    identity = folder.stat().st_ino
    fstat = os.fstat
    swapped = False

    def swap(fd: int) -> os.stat_result:
        nonlocal swapped
        info = fstat(fd)
        if not swapped and info.st_ino == identity and stat.S_ISDIR(info.st_mode):
            _set_windows_junction(folder, outside)
            swapped = True
        return info

    monkeypatch.setattr(export.os, "fstat", swap)
    assert entries(tmp_path) == {}
    assert swapped
    folder.rmdir()  # remove the junction after all handles close


def _spilling_database(db: Path) -> None:
    """A database whose next big uncommitted transaction spills into the main file."""
    con = sqlite3.connect(db)
    con.execute("PRAGMA page_size=512")
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, payload BLOB)")
    con.executemany("INSERT INTO t(payload) VALUES (?)", [(b"x" * 400,) for _ in range(50)])
    con.commit()
    con.close()


def _spill_and_hold(db: Path, spilled: threading.Event, hold: threading.Event) -> threading.Thread:
    def writer() -> None:
        wcon = sqlite3.connect(db, timeout=60)
        wcon.execute("PRAGMA cache_size=2")  # a few inserts force the cache to spill
        wcon.execute("BEGIN")
        wcon.executemany(
            "INSERT INTO t(payload) VALUES (?)", [(bytes([i % 256]) * 480,) for i in range(4000)]
        )
        spilled.set()
        hold.wait(timeout=60)
        wcon.rollback()
        wcon.close()

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    return thread


def test_a_database_stuck_mid_write_is_left_out_rather_than_shipped_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export, "DATABASE_WAIT_S", 0.2)
    path = tmp_path / "memory.db"
    _spilling_database(path)
    source = sqlite3.connect(path, timeout=0)
    spilled, hold = threading.Event(), threading.Event()
    thread = _spill_and_hold(path, spilled, hold)
    assert spilled.wait(30)
    try:
        assert "memory.db" not in entries(tmp_path, {"memory.db": source})
    finally:
        hold.set()
        thread.join(timeout=30)
        source.close()


def test_a_database_exports_as_a_self_consistent_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    _spilling_database(path)
    source = sqlite3.connect(path)
    try:
        got = entries(tmp_path, {"memory.db": source})
    finally:
        source.close()
    check = sqlite3.connect(":memory:")
    try:
        check.deserialize(got["memory.db"])
        assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert check.execute("SELECT count(*) FROM t").fetchone()[0] == 50
    finally:
        check.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction at the configured data root")
def test_windows_export_follows_a_junction_data_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    (real / "threads").mkdir(parents=True)
    (real / "profile.json").write_bytes(b"profile")
    (real / "threads" / "chat.json").write_bytes(b"chat")
    root = tmp_path / "linked-root"
    root.mkdir()
    _set_windows_junction(root, real)
    assert entries(root) == {"profile.json": b"profile", "threads/chat.json": b"chat"}


def test_export_follows_a_configured_symlink_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "profile.json").write_bytes(b"profile")
    root = tmp_path / "linked-root"
    symlink(root, real, directory=True)
    assert entries(root) == {"profile.json": b"profile"}


def test_export_keeps_resolved_root_when_configured_link_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "profile.json").write_bytes(b"profile")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "profile.json").write_bytes(EXCLUDED)
    root = tmp_path / "linked-root"
    symlink(root, real, directory=True)
    resolve = Path.resolve

    def retarget(path: Path, strict: bool = False) -> Path:
        resolved = resolve(path, strict=strict)
        if path == root:
            root.unlink()
            symlink(root, outside, directory=True)
        return resolved

    monkeypatch.setattr(Path, "resolve", retarget)
    assert entries(root) == {"profile.json": b"profile"}


@pytest.mark.skipif(os.name == "nt", reason="POSIX ancestor replacement race")
def test_database_snapshot_never_reopens_the_live_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data, outside = tmp_path / "data", tmp_path / "outside"
    for folder, value in [(data, "allowed"), (outside, "excluded fixture")]:
        folder.mkdir()
        with sqlite3.connect(folder / "memory.db") as db:
            db.execute("CREATE TABLE t(value TEXT)")
            db.execute("INSERT INTO t VALUES (?)", (value,))
    source = sqlite3.connect(data / "memory.db")
    snapshot = export._database_snapshot
    swapped = False

    def swap(connection: sqlite3.Connection) -> bytes | None:
        nonlocal swapped
        data.rename(tmp_path / "original")
        symlink(data, outside, directory=True)
        swapped = True
        return snapshot(connection)

    monkeypatch.setattr(export, "_database_snapshot", swap)
    try:
        got = entries(data, {"memory.db": source})
    finally:
        source.close()
    assert swapped
    check = sqlite3.connect(":memory:")
    try:
        if "memory.db" in got:
            check.deserialize(got["memory.db"])
            assert check.execute("SELECT value FROM t").fetchall() == [("allowed",)]
    finally:
        check.close()


@pytest.mark.parametrize("name", export.DATABASES)
def test_database_snapshot_includes_committed_wal_rows(tmp_path: Path, name: str) -> None:
    writer = sqlite3.connect(tmp_path / name)
    source = sqlite3.connect(tmp_path / name)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE t(value TEXT)")
        writer.execute("INSERT INTO t VALUES ('committed')")
        writer.commit()
        writer.execute("INSERT INTO t VALUES ('uncommitted')")
        got = entries(tmp_path, {name: source})
        check = sqlite3.connect(":memory:")
        try:
            check.deserialize(got[name])
            assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert check.execute("SELECT value FROM t").fetchall() == [("committed",)]
        finally:
            check.close()
    finally:
        source.close()
        writer.close()


def test_corrupt_database_does_not_fall_back_to_raw_bytes(tmp_path: Path) -> None:
    (tmp_path / "memory.db").write_bytes(b"SQLite format 3\0" + b"bad" * 100)
    assert "memory.db" not in entries(tmp_path)


def test_database_snapshot_bounds_the_result_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "memory.db"
    _spilling_database(path)
    monkeypatch.setattr(export, "MAX_FILE_BYTES", 1_024)
    source = sqlite3.connect(path)
    try:
        assert "memory.db" not in entries(tmp_path, {"memory.db": source})
    finally:
        source.close()


def test_database_snapshot_stops_at_its_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "memory.db"
    _spilling_database(path)
    monkeypatch.setattr(export, "DATABASE_WAIT_S", 0)
    source = sqlite3.connect(path)
    try:
        assert "memory.db" not in entries(tmp_path, {"memory.db": source})
    finally:
        source.close()


def test_export_keeps_a_file_newer_than_the_zip_clock(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_bytes(b"profile")
    timestamp = 7_258_118_400  # 2200-01-01, after the zip clock's 2107 ceiling
    os.utime(path, (timestamp, timestamp))
    if time.localtime(path.stat().st_mtime).tm_year <= 2107:
        pytest.skip("filesystem clamps future timestamps before the ZIP ceiling")
    with zipfile.ZipFile(io.BytesIO(export.agent_data_zip(tmp_path))) as archive:
        assert archive.read("profile.json") == b"profile"
        assert archive.getinfo("profile.json").date_time == (2107, 12, 31, 23, 59, 58)
        assert archive.testzip() is None


def test_database_from_another_data_directory_is_not_exported(tmp_path: Path) -> None:
    data, outside = tmp_path / "data", tmp_path / "outside"
    data.mkdir()
    outside.mkdir()
    _spilling_database(data / "memory.db")
    _spilling_database(outside / "memory.db")
    source = sqlite3.connect(outside / "memory.db")
    try:
        assert "memory.db" not in entries(data, {"memory.db": source})
    finally:
        source.close()


def test_database_without_an_active_store_is_named_in_readme(tmp_path: Path) -> None:
    _spilling_database(tmp_path / "memory.db")
    with zipfile.ZipFile(io.BytesIO(export.agent_data_zip(tmp_path))) as archive:
        assert "memory.db" not in archive.namelist()
        assert b"Databases omitted" in archive.read("README.txt")


def test_database_export_does_not_commit_the_runtime_transaction(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    _spilling_database(path)
    source = sqlite3.connect(path)
    try:
        source.execute("DELETE FROM t")
        assert "memory.db" not in entries(tmp_path, {"memory.db": source})
        assert source.in_transaction
        source.rollback()
        assert source.execute("SELECT count(*) FROM t").fetchone()[0] == 50
    finally:
        source.close()


def test_owned_connection_snapshot_stays_consistent_when_file_times_are_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable

    path = tmp_path / "memory.db"
    _spilling_database(path)
    writer = sqlite3.connect(path)
    writer.executemany("INSERT INTO t(payload) VALUES (?)", [(b"x" * 400,) for _ in range(400)])
    writer.commit()
    changed = False

    class Source(sqlite3.Connection):
        def backup(
            self,
            target: sqlite3.Connection,
            *,
            pages: int,
            progress: Callable[[int, int, int], None],
            sleep: float,
        ) -> None:
            def update(status: int, remaining: int, total: int) -> None:
                nonlocal changed
                if remaining and not changed:
                    writer.execute("UPDATE t SET payload = ?", (b"new" * 150,))
                    writer.commit()
                    changed = True
                progress(status, remaining, total)

            super().backup(target, pages=pages, progress=update, sleep=sleep)

    source = sqlite3.connect(path, factory=Source)
    info = path.stat()
    monkeypatch.setattr(export, "_database_info", lambda path, fd: info)
    try:
        got = entries(tmp_path, {"memory.db": source})
        assert changed
        check = sqlite3.connect(":memory:")
        try:
            check.deserialize(got["memory.db"])
            assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert check.execute("SELECT count(DISTINCT payload) FROM t").fetchone()[0] == 1
            assert check.execute("SELECT count(*) FROM t").fetchone()[0] == 450
        finally:
            check.close()
    finally:
        source.close()
        writer.close()


def test_the_export_carries_the_data_the_runtime_actually_keeps(tmp_path: Path) -> None:
    """The manifest is a whitelist, and the runtime grew folders the list never learned:
    skills edited in the app, the contacts sources, the per-task traces, and the delivery
    outbox whose pending rows a restore must still owe — losing them silently is losing
    the user's data while the zip says "your nanoMuse data, exported"."""
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "morning-brief").mkdir()
    (tmp_path / "skills" / "morning-brief" / "SKILL.md").write_bytes(b"# brief")
    (tmp_path / "contacts").mkdir()
    (tmp_path / "contacts" / "work.vcf").write_bytes(b"BEGIN:VCARD")
    (tmp_path / "phone-traces").mkdir()
    (tmp_path / "phone-traces" / "task-1.jsonl").write_bytes(b"{}")
    (tmp_path / "computer-traces").mkdir()
    (tmp_path / "computer-traces" / "task-2.jsonl").write_bytes(b"{}")
    _spilling_database(tmp_path / "scheduled-deliveries.db")
    (tmp_path / "nudges.json").write_bytes(b"[]")
    # deliberately this device's own concerns, named in the README's "not in this zip"
    (tmp_path / "sync.json").write_bytes(b"{}")
    (tmp_path / "channels").mkdir()
    (tmp_path / "channels" / "pairing.json").write_bytes(b"{}")

    source = sqlite3.connect(tmp_path / "scheduled-deliveries.db")
    try:
        got = entries(tmp_path, {"scheduled-deliveries.db": source})
    finally:
        source.close()
    assert "skills/morning-brief/SKILL.md" in got
    assert "contacts/work.vcf" in got
    assert "phone-traces/task-1.jsonl" in got
    assert "computer-traces/task-2.jsonl" in got
    assert "scheduled-deliveries.db" in got
    assert "nudges.json" in got
    assert not any(name.startswith("channels/") for name in got)
    assert "sync.json" not in got


def test_database_export_preserves_the_runtime_connection_lock(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    _spilling_database(path)
    source = sqlite3.connect(path)
    try:
        source.execute("BEGIN")
        source.execute("SELECT count(*) FROM t").fetchone()
        assert "memory.db" not in entries(tmp_path, {"memory.db": source})
        # Closing an unrelated raw descriptor releases process-wide SQLite locks on
        # POSIX. Another process must still be unable to commit over this read lock.
        attempt = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sqlite3,sys\n"
                "db=sqlite3.connect(sys.argv[1],timeout=0)\n"
                "try:\n"
                " db.execute('DELETE FROM t'); db.commit(); print('written')\n"
                "except sqlite3.OperationalError:\n"
                " print('locked')\n"
                "finally:\n"
                " db.close()\n",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert attempt.stdout.strip() == "locked"
        source.rollback()
        assert source.execute("SELECT count(*) FROM t").fetchone()[0] == 50
    finally:
        source.close()
