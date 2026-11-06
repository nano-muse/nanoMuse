"""The agent's data as one zip: `GET /api/data/export`.

The desktop's rooms host has had *Download your agent data* since 0.1.30 (a zip written to
Downloads); this is the same file for the web client, and for anyone whose runtime runs on
another machine: the reply is the zip itself. SQLite snapshots use private temporary
files which are removed before the reply is returned.

What goes in is what the runtime keeps about the person and its own work: the profile and
the look, the rooms (feed, ideas, memory, goals, reminders, triggers), the address book,
the approvals it was given, and the chats as it holds them (`threads/`, `sessions/`).

What never goes in is a credential or a key: `vault.enc` and `vault.key` (the secrets
themselves), `server_token` (the app's own password), `push-vapid.json` (the private key
that signs notifications). The settings file is left out for the same reason: it can hold
an API key in the clear, and the person sets those in the app anyway. `logs/` and
`workspace/` are left out as well: the first is noise, the second is the person's own files.
The README in the zip says all of this.
"""

from __future__ import annotations

import io
import os
import sqlite3
import stat
import sys
import time
import zipfile
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from nanomuse.logger import logger

# As the desktop's export: one file this big is not worth shipping inside a zip.
MAX_FILE_BYTES = 64 * 1024 * 1024

# Files of the agent's data, straight under the data dir. A missing one is simply not in
# the zip: every one of them appears when the feature that owns it has been used.
FILES = (
    "profile.json",
    "feed_posts.json",
    "ideas.json",
    "memory.db",
    "goals.db",
    "reminders.db",
    "triggers.db",
    "scheduled-deliveries.db",
    "nudges.json",
    "approvals.json",
    "contacts.vcf",
    "contacts-cache.json",
    "calendar-cache.json",
    "firstrun.json",
    "audit.jsonl",
)

# The SQLite databases among the files: shipped as a self-consistent snapshot, not as the
# raw bytes of a file a writer may be mid-way through (the rollback journal never ships).
DATABASES = ("memory.db", "goals.db", "reminders.db", "triggers.db", "scheduled-deliveries.db")

# Retry budget for SQLite's online backup of an already-open database.
DATABASE_WAIT_S = 5.0

# Folders of the chats, as the runtime keeps them.
DIRS = ("threads", "sessions", "skills", "contacts", "phone-traces", "computer-traces")

README = """Your nanoMuse data, exported {when}

profile.json              the agent's name and look
feed_posts.json           the Feed as it was written
ideas.json                the ideas kept for a new chat
memory.db                 what the agent remembers
goals.db                  goals and their steps
reminders.db              reminders and routines
triggers.db               standing instructions that fire on something happening
scheduled-deliveries.db   what a reminder or routine still owes a chat, mid-delivery
nudges.json               the relay's nudges as last fetched
approvals.json            the approvals it was given
contacts.vcf              the agent's address book
contacts-cache.json       the contacts it looked up
contacts/                 the address-book sources, as uploaded
calendar-cache.json       the calendar as last read
skills/                   skills stored in the data directory, one folder each
phone-traces/             what ran on the phone, one file per task
computer-traces/          what ran on the computer, one file per task
firstrun.json             the first-conversation state
audit.jsonl               every tool call it made, in order
threads/                  the chats, one file each
sessions/                 the running state of a conversation

Database entries are committed SQLite snapshots. Private temporary output files are
removed before the export is returned. Any omitted databases are listed below.

Not in this zip, on purpose: the secrets themselves (vault.enc, vault.key), the app's own
password (server_token), the key that signs notifications (push-vapid.json), the settings
file (it can hold an API key in the clear), the pairing credentials (channels/), this
device's own sync cursor (sync.json; another device's copy would fight it), the push
subscription endpoints (push-subscriptions.json), the logs, and workspace/ (your own files).
"""


def stamp() -> str:
    """The timestamp a file name carries: sortable, and legal on every filesystem."""
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def filename() -> str:
    return f"nanomuse-data-{stamp()}.zip"


def _open(path: Path, *, directory: bool = False, parent_fd: int | None = None) -> int:
    """Open one entry, never following it, relative to an already pinned parent."""
    if sys.platform == "win32":
        from nanomuse.server.data_export_windows import open_no_follow

        return open_no_follow(path, directory=directory, parent_fd=parent_fd)
    else:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if directory:
            flags |= os.O_DIRECTORY
        return os.open(path if parent_fd is None else path.name, flags, dir_fd=parent_fd)


def _is_link(info: os.stat_result) -> bool:
    # fstat on a Windows junction does not necessarily report S_IFLNK.
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


@contextmanager
def _directory(path: Path, parent_fd: int | None = None) -> Iterator[int]:
    fd = _open(path, directory=True, parent_fd=parent_fd)
    try:
        info = os.fstat(fd)
        if _is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise OSError("export directory is not a regular directory")
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _data_directory(path: Path) -> Iterator[tuple[Path, int]]:
    # Resolve the whole configured path (e.g. macOS /var, or a data root the user moved to
    # a bigger disk as a junction): the root is the one link the user set up themselves.
    # Every exported descendant below it is pinned without following, and must not be a link.
    path = path.resolve(strict=True)
    with ExitStack() as stack:
        current = Path(path.anchor)
        fd = stack.enter_context(_directory(current))
        for part in path.parts[1:]:
            current /= part
            fd = stack.enter_context(_directory(current, fd))
        yield path, fd


def _read_file(path: Path, parent_fd: int) -> tuple[os.stat_result, bytes] | None:
    """Validate and read the same object, with a bound even if it grows during the read."""
    try:
        fd = _open(path, parent_fd=parent_fd)
        try:
            before = os.fstat(fd)
            if (
                _is_link(before)
                or not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > MAX_FILE_BYTES
            ):
                return None
            with os.fdopen(fd, "rb", closefd=False) as source:
                content = source.read(MAX_FILE_BYTES + 1)
            after = os.fstat(fd)
            if (
                len(content) > MAX_FILE_BYTES
                or after.st_nlink != 1
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ctime_ns != before.st_ctime_ns
            ):
                return None
            return before, content
        finally:
            os.close(fd)
    except OSError:
        # A missing, inaccessible or replaced entry does not prevent exporting the rest.
        return None


def _add_file(z: zipfile.ZipFile, path: Path, fd: int, name: str) -> None:
    checked = _read_file(path, fd)
    if checked is None:
        return
    info, content = checked
    _write_entry(z, name, info, content)


def _write_entry(z: zipfile.ZipFile, name: str, info: os.stat_result, content: bytes) -> None:
    # Preserve the original metadata without ZipInfo.from_file's second pathname lookup.
    # The zip's own clock starts in 1980: an older file (a migrated photo, a 1970-epoch
    # stamp a sync tool kept) keeps its bytes and lands at the floor, not a failed export.
    stamp = min(
        max(time.localtime(info.st_mtime)[:6], (1980, 1, 1, 0, 0, 0)),
        (2107, 12, 31, 23, 59, 58),
    )
    entry = zipfile.ZipInfo(name, stamp)
    entry.external_attr = (info.st_mode & 0xFFFF) << 16
    entry.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(entry, content)


def _database_info(path: Path, parent_fd: int) -> os.stat_result:
    # Do not open and close a raw database descriptor: on POSIX closing any descriptor
    # can release SQLite's process-wide locks. Snapshot reads use the runtime's existing
    # connection; this stat only checks the archive entry and supplies its metadata.
    info = (
        path.lstat()
        if sys.platform == "win32"
        else os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    )
    if _is_link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OSError("database export entry is linked or is not a regular file")
    return info


def _database_snapshot(source: sqlite3.Connection) -> bytes | None:
    """SQLite's online backup reads the already-owned connection, with bounded retries."""
    if source.in_transaction:
        return None
    deadline = time.monotonic() + DATABASE_WAIT_S
    page_size = source.execute("PRAGMA page_size").fetchone()[0]
    page_count = source.execute("PRAGMA page_count").fetchone()[0]
    if page_size * page_count > MAX_FILE_BYTES:
        return None
    with TemporaryDirectory(prefix="nanomuse-export-") as temporary:
        snapshot_path = Path(temporary) / "snapshot.db"
        snapshot = sqlite3.connect(snapshot_path)
        try:
            snapshot.execute(f"PRAGMA page_size={page_size}")
            snapshot.execute(f"PRAGMA max_page_count={MAX_FILE_BYTES // page_size}")

            def progress(status: int, remaining: int, total: int) -> None:
                if total * page_size > MAX_FILE_BYTES:
                    raise ValueError("database snapshot exceeds export size limit")
                if source.in_transaction:
                    raise ValueError("source connection has an uncommitted transaction")
                if time.monotonic() >= deadline:
                    raise TimeoutError("database snapshot exceeded export deadline")

            source.backup(snapshot, pages=64, progress=progress, sleep=0.05)
            # WAL is incorporated by SQLite's snapshot, not copied as a sidecar. The
            # standalone result must use rollback mode, including its file header.
            snapshot.execute("PRAGMA journal_mode=DELETE")
        finally:
            snapshot.close()
        with snapshot_path.open("rb") as result:
            content = result.read(MAX_FILE_BYTES + 1)
        return content if len(content) <= MAX_FILE_BYTES else None


def _add_database(
    z: zipfile.ZipFile,
    path: Path,
    fd: int,
    name: str,
    sources: Mapping[str, sqlite3.Connection],
) -> bool:
    """Return false when an existing database could not safely be included."""
    try:
        before = _database_info(path, fd)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    source = sources.get(name)
    if source is None:
        return False
    try:
        # Only the expected store's main database may fill this archive entry. Explicit
        # sources from another data directory or in-memory connections are refused.
        database_path = next(
            (row[2] for row in source.execute("PRAGMA database_list") if row[1] == "main"), ""
        )
        if not database_path or Path(database_path).resolve(strict=True) != path:
            return False
        content = _database_snapshot(source)
        if content is None:
            return False
        after = _database_info(path, fd)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            return False
        _write_entry(z, name, before, content)
        return True
    except (OSError, sqlite3.Error, ValueError) as exc:
        logger.warning("{} could not be snapshotted; skipped from this export: {}", name, exc)
        return False


def _add_tree(z: zipfile.ZipFile, root: Path, fd: int, under: str) -> None:
    try:
        names = sorted(os.listdir(root if sys.platform == "win32" else fd))
    except OSError:
        return
    for name in names:
        path = root / name
        archive_name = f"{under}/{name}"
        # The directory open is no-follow too, so swapping a tree after enumeration
        # cannot redirect child opens. Windows may enumerate a changed pathname, but
        # each returned name is opened relative to the original directory handle.
        try:
            with _directory(path, fd) as child_fd:
                _add_tree(z, path, child_fd, archive_name)
            continue
        except OSError:
            pass
        _add_file(z, path, fd, archive_name)


def agent_data_zip(
    data_dir: Path, *, databases: Mapping[str, sqlite3.Connection] | None = None
) -> bytes:
    """The zip's bytes: every file of the agent's data that is there, and the README."""
    omitted: list[str] = []
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        try:
            with _data_directory(data_dir) as (root, fd):
                for name in FILES:
                    if name in DATABASES:
                        if not _add_database(z, root / name, fd, name, databases or {}):
                            omitted.append(name)
                    else:
                        _add_file(z, root / name, fd, name)
                for folder in DIRS:
                    try:
                        with _directory(root / folder, fd) as child_fd:
                            _add_tree(z, root / folder, child_fd, folder)
                    except OSError:
                        continue
        except OSError:
            pass
        z.writestr(
            "README.txt",
            README.format(when=datetime.now(UTC).isoformat(timespec="seconds"))
            + (
                "\nDatabases omitted because a safe snapshot was unavailable: "
                + ", ".join(omitted)
                + ". Retry from the running app with the relevant feature enabled, after writes finish.\n"
                if omitted
                else ""
            ),
        )
    return out.getvalue()


__all__ = [
    "DATABASES",
    "DIRS",
    "FILES",
    "MAX_FILE_BYTES",
    "README",
    "agent_data_zip",
    "filename",
]
