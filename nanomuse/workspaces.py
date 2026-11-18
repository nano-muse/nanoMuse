"""Space-bound file roots and command sandboxes for one runtime owner."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from copy import copy
from functools import lru_cache
from pathlib import Path
from typing import IO, Any

from nanomuse.sandbox import Sandbox, interpreter_roots
from nanomuse.workspace_runner import abi_version

PREFIX = "@spaces/"


def split_path(path: str) -> tuple[str, str]:
    if path.startswith(PREFIX):
        space, separator, relative = path[len(PREFIX) :].partition("/")
        if not separator or space == "personal":
            raise PermissionError("Invalid space file path")
        return space, relative
    return "personal", path


def file_path(space: str, relative: str) -> str:
    return relative if space == "personal" else f"{PREFIX}{space}/{relative}"


@contextmanager
def open_file(root: Path, target: Path, mode: str) -> Iterator[IO]:
    """Open through directory descriptors so replacing a symlink cannot escape a root."""
    options: dict[str, Any] = {} if "b" in mode else {"encoding": "utf-8", "errors": "replace"}
    parts = target.relative_to(root).parts
    if not parts or any(part in (".", "..") for part in parts):
        raise PermissionError("Invalid workspace file path")
    if os.name != "posix":
        if target.resolve() != target or not target.is_relative_to(root):
            raise PermissionError("Workspace file must not be a symbolic link")
        with target.open(mode, **options) as stream:
            yield stream
        return
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            if mode.startswith(("w", "a")):
                try:
                    os.mkdir(part, mode=0o700, dir_fd=directory)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        flags = os.O_RDONLY
        if mode.startswith("w"):
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        elif mode.startswith("a"):
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        fd = os.open(parts[-1], flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        with os.fdopen(fd, mode, **options) as stream:
            yield stream
    finally:
        os.close(directory)


@lru_cache(maxsize=1)
def command_abi() -> int:
    return abi_version()


class WorkspaceSandbox(Sandbox):
    """Fail closed if filesystem confinement cannot be enforced on this machine."""

    def __init__(
        self,
        workspace: Path,
        data_dir: Path,
        readonly: list[Path] | None = None,
        outer: Sandbox | None = None,
    ):
        self.workspace = workspace.resolve()
        self.data_dir = data_dir.resolve()
        self.active = True  # wrapping is mandatory even when the kernel rejects it
        self.blocks_network = False
        self.outer = copy(outer) if outer is not None and outer.active else None
        if self.outer is not None:
            self.outer.workspace = self.workspace
            self.outer.extra_roots = []
            self.outer.shared = []
            self.outer.shared_ro = []
            self.outer.ro_roots = [Path(__file__).parent]
            self.blocks_network = self.outer.blocks_network
        self.version = str(command_abi())
        self.reason = "" if command_abi() >= 3 else "Linux Landlock ABI 3 or newer is required"
        if outer is not None and outer.settings.mode == "bwrap" and not outer.active:
            self.reason = "The required bubblewrap sandbox is unavailable"
        self.readonly = [
            Path(p).resolve() for p in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc")
        ] + [
            p.resolve()
            for p in [
                *interpreter_roots(),
                Path(sys.prefix),
                Path(sys.base_prefix),
                Path(__file__).parent,
                *(readonly or []),
            ]
        ]
        # A parent grant would reveal every child, including the other spaces and vault.
        for root in [self.workspace, *self.readonly]:
            if self.data_dir.is_relative_to(root):
                self.reason = "Runtime data must be outside readable workspace and system roots"

    @property
    def status(self) -> str:
        return f"unavailable: {self.reason}" if self.reason else f"Landlock ABI {self.version}"

    def describe(self) -> str:
        if self.reason:
            return "Workspace commands are unavailable: " + self.reason
        return (
            "Commands can read system libraries and this space's files, and can write only "
            "inside this workspace. Other spaces and runtime data are inaccessible. "
            "Network access is assessed separately."
        )

    def wrap(self, argv: list[str], network: bool, cwd: Path) -> list[str]:
        if self.reason:
            raise RuntimeError(self.describe())
        temporary = self.workspace / ".nanomuse-tmp"
        temporary.mkdir(mode=0o700, exist_ok=True)
        if temporary.is_symlink() or temporary.resolve().parent != self.workspace:
            raise RuntimeError("Invalid workspace temporary directory")
        # -I ignores user Python startup hooks before the restriction is installed.
        command = [
            sys.executable,
            "-I",
            str(Path(__file__).with_name("workspace_runner.py")),
            json.dumps(
                {
                    "workspace": str(self.workspace),
                    "temporary": str(temporary),
                    "readonly": [str(p) for p in self.readonly],
                    "lookup": [str(Path(__file__).parent.parent)],
                }
            ),
            *argv,
        ]
        return self.outer.wrap(command, network, cwd) if self.outer is not None else command


def space_directory(data_dir: Path, owner: str, space: str) -> Path:
    directory = (
        data_dir.resolve()
        / "space-workspaces"
        / hashlib.sha256(owner.encode()).hexdigest()[:24]
        / space
    )
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() != directory:
        raise PermissionError("A space workspace must not contain symbolic links")
    return directory
