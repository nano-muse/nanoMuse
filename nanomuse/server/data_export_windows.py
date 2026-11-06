"""Windows handles for the data export's pinned, no-follow directory walk."""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path


class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UnicodeString)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", wintypes.LPVOID),
        ("SecurityQualityOfService", wintypes.LPVOID),
    ]


class _IoStatusBlock(ctypes.Structure):
    # The first field is a union of NTSTATUS and a pointer; only its size matters here.
    _fields_ = [("Status", wintypes.LPVOID), ("Information", ctypes.c_size_t)]


def _open_relative(name: str, parent: int, *, directory: bool) -> int:
    """Open one child of a pinned directory, even if its pathname becomes a junction."""
    if sys.platform != "win32":
        raise OSError("Windows export handles are only available on Windows")
    else:
        native = ctypes.WinDLL("ntdll")
        create = native.NtCreateFile
        create.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            ctypes.POINTER(_ObjectAttributes),
            ctypes.POINTER(_IoStatusBlock),
            wintypes.LPVOID,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.LPVOID,
            wintypes.ULONG,
        ]
        create.restype = ctypes.c_int32
        to_error = native.RtlNtStatusToDosError
        to_error.argtypes = [ctypes.c_int32]
        to_error.restype = wintypes.ULONG
        buffer = ctypes.create_unicode_buffer(name)
        length = len(name.encode("utf-16-le"))
        unicode_name = _UnicodeString(length, length + 2, ctypes.cast(buffer, wintypes.LPWSTR))
        attributes = _ObjectAttributes(
            ctypes.sizeof(_ObjectAttributes),
            parent,
            ctypes.pointer(unicode_name),
            0x1040,  # OBJ_CASE_INSENSITIVE | OBJ_DONT_REPARSE
            None,
            None,
        )
        handle = wintypes.HANDLE()
        result = _IoStatusBlock()
        # RootDirectory pins lookup to the opened object. Share flags alone cannot do
        # this: FILE_WRITE_ATTRIBUTES can change a reparse point without sharing checks.
        # https://learn.microsoft.com/windows/win32/api/winternl/nf-winternl-ntcreatefile
        status = create(
            ctypes.byref(handle),
            0x100081 if directory else 0x120089,  # SYNCHRONIZE | LIST | ATTRS / FILE_GENERIC_READ
            ctypes.byref(attributes),
            ctypes.byref(result),
            None,
            0,
            1 if directory else 3,  # share read; files also share write
            1,  # FILE_OPEN
            0x200020 | (1 if directory else 0x40),  # OPEN_REPARSE_POINT | SYNC | DIR/NON_DIR
            None,
            0,
        )
        if status < 0:
            raise ctypes.WinError(to_error(status))
        assert handle.value is not None
        return handle.value


def open_no_follow(path: Path, *, directory: bool, parent_fd: int | None = None) -> int:
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
        # Share flags prevent replacement. Parent-relative opens also prevent a changed
        # reparse point from redirecting lookup. Files allow current writers (e.g. SQLite).
        # Attribute-only handles do not participate in Windows sharing checks, so a
        # directory also needs FILE_LIST_DIRECTORY for its deny-write/delete flags.
        # https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew
        if parent_fd is None:
            # Only the filesystem anchor is opened by an absolute pathname.
            handle = create(
                str(path),
                0x81 if directory else 0x80000000,  # LIST_DIRECTORY | ATTRS / GENERIC_READ
                1 if directory else 3,  # FILE_SHARE_READ / FILE_SHARE_READ | FILE_SHARE_WRITE
                None,
                3,  # OPEN_EXISTING
                0x00200000 | 0x02000000,  # OPEN_REPARSE_POINT | BACKUP_SEMANTICS
                None,
            )
            if handle == wintypes.HANDLE(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            handle = _open_relative(path.name, msvcrt.get_osfhandle(parent_fd), directory=directory)
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            close(handle)
            raise
