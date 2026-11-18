"""Linux filesystem confinement for one command, executed in a fresh interpreter.

The parent never restricts its own threads. The kernel applies the rules to this
process and all its descendants before the requested program starts.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from pathlib import Path


def abi_version() -> int:
    if sys.platform != "linux" or platform.machine() not in ("x86_64", "aarch64"):
        return 0
    libc = ctypes.CDLL(None, use_errno=True)
    return max(0, int(libc.syscall(444, 0, 0, 1)))


class Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def restrict(
    workspace: Path, temporary: Path, readonly: list[Path], lookup: list[Path] | None = None
) -> None:
    abi = abi_version()
    if abi < 3:
        raise RuntimeError("Workspace commands require Linux Landlock ABI 3 or newer")
    libc = ctypes.CDLL(None, use_errno=True)

    def check(result: int) -> int:
        if result < 0:
            raise OSError(ctypes.get_errno(), "Could not restrict workspace access")
        return result

    # ABI 3 adds truncate, ABI 5 adds device ioctl. Unknown future rights are not assumed.
    handled = (1 << (16 if abi >= 5 else 15)) - 1
    fd = check(libc.syscall(444, ctypes.byref(Ruleset(handled)), ctypes.sizeof(Ruleset), 0))
    read = (1 << 0) | (1 << 2) | (1 << 3)
    file_rights = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 14) | (1 << 15)
    try:
        for path, rights in [
            *((p, read) for p in readonly),
            *((p, 1 << 3) for p in lookup or []),
            (workspace, handled),
            (temporary, handled),
            *((Path(p), file_rights & handled) for p in ("/dev/null", "/dev/zero", "/dev/urandom")),
        ]:
            if not path.exists():
                continue
            path_fd = os.open(path, getattr(os, "O_PATH", 0) | os.O_CLOEXEC)
            try:
                if not path.is_dir():
                    rights &= file_rights
                check(libc.syscall(445, fd, 1, ctypes.byref(PathRule(rights, path_fd)), 0))
            finally:
                os.close(path_fd)
        check(libc.prctl(38, 1, 0, 0, 0))  # PR_SET_NO_NEW_PRIVS
        check(libc.syscall(446, fd, 0))
    finally:
        os.close(fd)


def main() -> None:
    import json

    policy = json.loads(sys.argv[1])
    workspace, temporary = Path(policy["workspace"]), Path(policy["temporary"])
    restrict(
        workspace,
        temporary,
        [Path(p) for p in policy["readonly"]],
        [Path(p) for p in policy.get("lookup", [])],
    )
    for name in ("PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH"):
        os.environ.pop(name, None)
    os.environ.update(
        HOME=str(temporary),
        TMPDIR=str(temporary),
        NANOMUSE_SANDBOX="landlock",
        PATH=os.pathsep.join(
            [str(Path(sys.executable).parent), "/usr/local/bin", "/usr/bin", "/bin"]
        ),
    )
    os.chdir(workspace)
    os.execvpe(sys.argv[2], sys.argv[2:], os.environ)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"Workspace command refused: {exc}", file=sys.stderr)
        raise SystemExit(126) from exc
