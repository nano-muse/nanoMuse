"""The agent's data as one zip: `GET /api/data/export`.

The desktop's rooms host has had *Download your agent data* since 0.1.30 (a zip written to
Downloads); this is the same file for the web client, and for anyone whose runtime runs on
another machine: the reply is the zip itself, so nothing is written to the runtime's disk.

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
import stat
import sys
import time
import zipfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path

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
    "approvals.json",
    "contacts.vcf",
    "contacts-cache.json",
    "calendar-cache.json",
    "firstrun.json",
    "audit.jsonl",
)

# Folders of the chats, as the runtime keeps them.
DIRS = ("threads", "sessions")

README = """Your nanoMuse data, exported {when}

profile.json        the agent's name and look
feed_posts.json     the Feed as it was written
ideas.json          the ideas kept for a new chat
memory.db           what the agent remembers
goals.db            goals and their steps
reminders.db        reminders and routines
triggers.db         standing instructions that fire on something happening
approvals.json      the approvals it was given
contacts.vcf        the agent's address book
contacts-cache.json the contacts it looked up
calendar-cache.json the calendar as last read
firstrun.json       the first-conversation state
audit.jsonl         every tool call it made, in order
threads/            the chats, one file each
sessions/           the running state of a conversation

Not in this zip, on purpose: the secrets themselves (vault.enc, vault.key), the app's own
password (server_token), the key that signs notifications (push-vapid.json), the settings
file (it can hold an API key in the clear), the logs, and workspace/ (your own files).
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
    # Resolve configured ancestors (e.g. macOS /var), then pin every component of that
    # path. The data directory itself, and every exported descendant, must not be a link.
    path = path.absolute()
    path = path.parent.resolve(strict=True) / path.name
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
    # Preserve the original metadata without ZipInfo.from_file's second pathname lookup.
    stamp = time.localtime(info.st_mtime)
    entry = zipfile.ZipInfo(name, stamp[:6])
    entry.external_attr = (info.st_mode & 0xFFFF) << 16
    entry.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(entry, content)


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


def agent_data_zip(data_dir: Path) -> bytes:
    """The zip's bytes: every file of the agent's data that is there, and the README."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        try:
            with _data_directory(data_dir) as (root, fd):
                for name in FILES:
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
            "README.txt", README.format(when=datetime.now(UTC).isoformat(timespec="seconds"))
        )
    return out.getvalue()


__all__ = ["DIRS", "FILES", "MAX_FILE_BYTES", "README", "agent_data_zip", "filename"]
