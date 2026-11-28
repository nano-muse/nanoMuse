"""A file kept to the one person it belongs to.

POSIX takes a mode: ``0600``, the owner reads and writes and nobody else does. Windows
has no mode, and ``chmod`` there clears a read-only flag and nothing else, so every call
to it around this codebase left the calendars, address books, token and key files it
meant to protect open to the machine's other local accounts. The ACL is set instead:
inheritance off, the one account in full control.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class _TokenUser(ctypes.Structure):
        _fields_ = [("User", _SidAndAttributes)]

    @lru_cache(maxsize=1)
    def _windows_user_sid() -> str | None:
        """Return the current process user's SID string (``S-1-...``), or ``None``."""
        token_query = 0x0008
        token_user_class = 1

        try:
            advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except OSError:
            return None

        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPWSTR),
        ]
        advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
        ):
            return None
        try:
            needed = wintypes.DWORD(0)
            advapi32.GetTokenInformation(token, token_user_class, None, 0, ctypes.byref(needed))
            if needed.value == 0:
                return None
            buf = ctypes.create_string_buffer(needed.value)
            if not advapi32.GetTokenInformation(
                token, token_user_class, buf, needed, ctypes.byref(needed)
            ):
                return None
            token_user = ctypes.cast(buf, ctypes.POINTER(_TokenUser)).contents
            sid_ptr = wintypes.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(token_user.User.Sid, ctypes.byref(sid_ptr)):
                return None
            try:
                return sid_ptr.value or None
            finally:
                kernel32.LocalFree(ctypes.cast(sid_ptr, ctypes.c_void_p))
        finally:
            kernel32.CloseHandle(token)

else:

    def _windows_user_sid() -> str | None:
        """Return the current process user's SID string (``S-1-...``), or ``None``."""
        return None


def _windows_principal() -> str | None:
    """Return an unambiguous ``icacls`` principal for the current Windows user.

    A bare ``USERNAME`` is ambiguous whenever the computer or domain name matches the
    user name (for example ``admin\\admin``): ``icacls`` can resolve it to the domain or
    machine SID instead of the user account, locking the process out of its own file once
    inheritance is removed. Granting by process token SID avoids name resolution altogether.
    """
    sid = _windows_user_sid()
    if sid:
        return f"*{sid}"
    user = os.environ.get("USERNAME")
    if not user:
        return None
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{user}" if domain else user


def keep_private(path: Path | str) -> None:
    """Make ``path`` readable by its owner and no other local account.

    On POSIX this is ``chmod 0600`` and raises as that does. On Windows the inherited
    access rules come off and the current account alone keeps full control (granted by
    its process token SID when available, falling back to ``USERDOMAIN\\USERNAME``); a
    command that cannot run (no account identity, an ``icacls`` that refused) is left
    alone rather than unwriting the file, the way a mode no platform honours would be.
    """
    if sys.platform == "win32":
        import subprocess

        principal = _windows_principal()
        if principal:  # a service without an identifiable user keeps the file's default rules
            subprocess.run(
                ["icacls", os.fspath(path), "/inheritance:r", "/grant:r", f"{principal}:(F)"],
                capture_output=True,
                check=False,
            )
    else:
        os.chmod(path, 0o600)
