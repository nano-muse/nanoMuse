"""Windows handles for the data export's pinned, no-follow directory walk."""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path


def open_no_follow(path: Path, *, directory: bool) -> int:
    """Return an owned CRT descriptor; ancestors must remain open until it is closed."""
    if sys.platform != "win32":
        raise OSError("Windows export handles are only available on Windows")
    else:
        import msvcrt

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
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        # Directory handles allow reading but prevent deletion, renaming and in-place
        # reparse changes. Files allow current writers (e.g. SQLite), but not replacement.
        # Attribute-only handles do not participate in Windows sharing checks, so a
        # directory also needs FILE_LIST_DIRECTORY for its deny-write/delete flags.
        # https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew
        handle = create(
            str(path),
            0x81 if directory else 0x80000000,  # LIST_DIRECTORY | READ_ATTRIBUTES / GENERIC_READ
            1 if directory else 3,  # FILE_SHARE_READ / FILE_SHARE_READ | FILE_SHARE_WRITE
            None,
            3,  # OPEN_EXISTING
            0x00200000 | 0x02000000,  # OPEN_REPARSE_POINT | BACKUP_SEMANTICS
            None,
        )
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            close(handle)
            raise
