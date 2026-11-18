"""Append-only JSONL audit trail of everything the agent did (and was refused).

Every entry carries a hash-chain link (``seq``, ``prev``, ``entry_hash``) signed with
HMAC-SHA256, so a line edited, deleted or reordered after the fact is found by
:meth:`AuditLog.verify`. The chain is tamper-evident, not unforgeable: the Sentinel
and the agent share one trust domain (D1), so anyone who holds the device and the
signing key can re-sign a whole chain. The key therefore never lives in the vault
key file: it is injected, read from the OS keychain, or kept in its own ``audit.key``
file next to the log, and the design (``docs/sentinel.md``) says this boundary out
loud. Lines written before signing existed carry no hash fields and verify as
``unsigned``; they are still readable by :meth:`AuditLog.tail`.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import stat
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from nanomuse.private import keep_private

_ZERO_HASH = "0" * 64
_AUDIT_KEY_ENV = "NANOMUSE_AUDIT_KEY"
_KEYRING_SERVICE = "nanoMuse"
_KEYRING_ACCOUNT = "audit-signing-key"

# Security identifiers no audit key may be open to, in string form. Only the
# file's owner (and the machine's own accounts, which the DACL walk below
# leaves alone) may read the key.
_BROAD_WINDOWS_SIDS = frozenset(
    {
        "S-1-1-0",  # Everyone
        "S-1-5-11",  # Authenticated Users
        "S-1-5-32-545",  # Users
        "S-1-5-32-546",  # Guests
        "S-1-5-7",  # Anonymous
        "S-1-5-4",  # Interactive
        "S-1-5-2",  # Network
        "S-1-5-6",  # Service
    }
)


def _windows_key_file_is_private(key_file: Path) -> bool:
    """True when the file's DACL grants nothing to a broad group.

    Windows has no mode bits: a file written 0600 still reports 0666, so the
    POSIX check cannot run there and every key read was refused. The DACL is
    read instead, through GetNamedSecurityInfo, and any access-allowed entry
    naming a broad group refuses the file. A DACL that cannot be read at all
    fails closed: the caller refuses the key rather than trusting a file it
    could not check. This runs only on Windows; it is never called on POSIX,
    where the mode bits say what the DACL would.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.windll.advapi32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    se_file_object = 1
    dacl_security_information = 0x00000004
    acl_size_information = 2
    access_allowed_ace_type = 0
    access_allowed_callback_ace_type = 9

    class AclSizeInfo(ctypes.Structure):
        _fields_ = [
            ("AceCount", wintypes.DWORD),
            ("AclBytesInUse", wintypes.DWORD),
            ("AclBytesFree", wintypes.DWORD),
        ]

    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.BOOL),
    ]
    advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    try:
        error = advapi32.GetNamedSecurityInfoW(
            os.fspath(key_file),
            se_file_object,
            dacl_security_information,
            None,
            None,
            ctypes.byref(ctypes.c_void_p()),
            None,
            ctypes.byref(descriptor),
        )
        if error != 0 or not descriptor:
            return False
        present = wintypes.BOOL()
        defaulted = wintypes.BOOL()
        dacl = ctypes.c_void_p()
        if not advapi32.GetSecurityDescriptorDacl(
            descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
        ):
            return False
        if not present or not dacl:
            return False  # no DACL: everyone may read
        info = AclSizeInfo()
        if not advapi32.GetAclInformation(
            dacl, ctypes.byref(info), ctypes.sizeof(info), acl_size_information
        ):
            return False
        for index in range(info.AceCount):
            ace = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace)):
                return False
            ace_type = ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte)).contents.value
            if ace_type not in (access_allowed_ace_type, access_allowed_callback_ace_type):
                continue  # a deny entry grants nothing
            ace_address = ace.value
            if ace_address is None:
                return False
            sid = ctypes.c_void_p(ace_address + 8)  # ACE header (4) + access mask (4)
            text_holder = ctypes.pointer(wintypes.LPWSTR())
            if not advapi32.ConvertSidToStringSidW(sid, text_holder):
                return False
            text = text_holder.contents
            try:
                sid_string = text.value
            finally:
                kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
            if sid_string in _BROAD_WINDOWS_SIDS:
                return False
        return True
    except Exception:  # noqa: BLE001 - an unreadable DACL fails closed, never open
        return False
    finally:
        if descriptor:
            kernel32.LocalFree(descriptor)


def _key_file_is_private(key_file: Path) -> bool:
    """True when no account but the owner can read ``key_file``.

    POSIX checks the mode bits, the way the file was written. Windows has no
    mode bits, so the DACL is read instead (see
    :func:`_windows_key_file_is_private`)."""
    platform = sys.platform  # through a name: mypy would otherwise drop the other platform's branch
    if platform == "win32":
        return _windows_key_file_is_private(key_file)
    return stat.S_IMODE(key_file.stat().st_mode) & 0o077 == 0


def _truncate(value: Any, limit: int = 500) -> Any:
    if isinstance(value, str):
        return (
            value if len(value) <= limit else value[:limit] + f"... [+{len(value) - limit} chars]"
        )
    if isinstance(value, dict):
        return {k: _truncate(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v, limit) for v in value[:50]]
    return value


def channel_of(tool: str) -> str:
    """Which rung of the ladder a tool call is (docs/gui.md): ``gui`` for the phone's screen,
    ``browser`` for the in-app or Playwright browser, ``web`` for plain fetches and search,
    ``cli`` for shell and Python, ``device`` for the phone's own capabilities, ``api`` for MCP
    servers and connectors, ``local`` for everything that stays in the workspace and memory.
    Recorded with every ``tool_call`` so the Activity view can show how much of the work needed
    the screen."""
    if tool.startswith("phone_"):
        return "gui"
    if tool.startswith("browser"):
        return "browser"
    if tool in ("web_fetch", "web_search"):
        return "web"
    if tool in ("shell", "python_execute"):
        return "cli"
    if tool.startswith("device__"):
        return "device"
    if "__" in tool or tool in ("send_email", "read_emails", "calendar", "contacts"):
        return "api"
    return "local"


class AuditSigner(Protocol):
    """Signs audit entries. The key is the caller's: an injected signer (tests, embedding),
    the OS keychain, or the dedicated key file. Nothing here reads the vault key."""

    def sign(self, payload: bytes) -> str: ...

    def verify(self, payload: bytes, tag: str) -> bool: ...


@dataclass(frozen=True)
class HmacSigner:
    """HMAC-SHA256 over the canonical entry bytes."""

    key: bytes

    def sign(self, payload: bytes) -> str:
        return hmac.new(self.key, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, tag: str) -> bool:
        try:
            expected = hmac.new(self.key, payload, hashlib.sha256).hexdigest()
        except Exception:  # noqa: BLE001 - a bad key is a failed verification, not a crash
            return False
        return hmac.compare_digest(expected, tag)


@dataclass
class AuditReport:
    """What :meth:`AuditLog.verify` found. ``ok`` is False when any line is corrupt or
    broken; unsigned (pre-signing) lines do not fail verification."""

    ok: bool
    checked: int = 0
    unsigned: int = 0
    corrupt: list[dict[str, Any]] = field(default_factory=list)
    broken: list[dict[str, Any]] = field(default_factory=list)
    last_seq: int = 0


def _canonical(entry: dict[str, Any]) -> bytes:
    """The bytes a hash covers: every field but ``entry_hash`` itself, keys sorted,
    so the same entry always hashes the same way whatever order it was built in."""
    payload = {k: v for k, v in entry.items() if k != "entry_hash"}
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str
    ).encode("utf-8")


class AuditLog:
    def __init__(
        self,
        path: Path,
        session_id: str | None = None,
        signer: AuditSigner | None = None,
        key_id: str = "1",
    ):
        self.path = Path(path)
        self.session_id = session_id
        self.key_id = key_id
        self.key_source: str | None = "injected" if signer is not None else None
        self._signer = signer
        self._lock = threading.Lock()
        self._chain: tuple[int, str] | None = None

    # ------------------------------------------------------------------ key
    def _key_file(self) -> Path:
        return self.path.with_name("audit.key")

    def _read_key_file(self) -> bytes | None:
        key_file = self._key_file()
        if not key_file.exists():
            return None
        if not _key_file_is_private(key_file):
            raise PermissionError(
                f"audit signing key {key_file} is readable by others; "
                "tighten it to 0600 (POSIX) or restrict its access list "
                "(Windows) or move it to the OS keychain"
            )
        try:
            key = bytes.fromhex(key_file.read_text("utf-8").strip())
        except ValueError:
            raise ValueError(f"audit signing key {key_file} is not hex") from None
        if len(key) != 32:
            raise ValueError(f"audit signing key {key_file} must be 32 bytes")
        return key

    def _write_key_file(self, key: bytes) -> None:
        key_file = self._key_file()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return
        try:
            os.write(fd, key.hex().encode("ascii"))
        finally:
            os.close(fd)
        keep_private(key_file)

    def _resolve_signer(self, create: bool) -> AuditSigner | None:
        """The signing key, in priority order: injected, environment, OS keychain,
        dedicated key file. ``create`` allows a fresh key to be made (writing); verify
        never creates one, so checking a log on a machine without its key reports
        the key missing instead of silently minting a new one."""
        if self._signer is not None:
            return self._signer
        env_key = os.environ.get(_AUDIT_KEY_ENV)
        if env_key:
            try:
                key = bytes.fromhex(env_key.strip())
            except ValueError:
                raise ValueError(f"{_AUDIT_KEY_ENV} must be 64 hex characters") from None
            if len(key) != 32:
                raise ValueError(f"{_AUDIT_KEY_ENV} must be 64 hex characters")
            self._signer = HmacSigner(key)
            self.key_source = "env"
            return self._signer
        try:
            import keyring  # type: ignore[import-not-found]
        except ImportError:
            keyring = None  # type: ignore[assignment]
        if keyring is not None:
            try:
                stored = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
            except Exception:  # noqa: BLE001 - no keychain backend: fall through to the file
                stored = None
            if isinstance(stored, str) and stored:
                try:
                    key = bytes.fromhex(stored.strip())
                except ValueError:
                    key = b""
                if len(key) == 32:
                    self._signer = HmacSigner(key)
                    self.key_source = "keyring"
                    return self._signer
            elif create:
                key = os.urandom(32)
                try:
                    keyring.set_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT, key.hex())
                except Exception:  # noqa: BLE001 - fall through to the file
                    pass
                else:
                    self._signer = HmacSigner(key)
                    self.key_source = "keyring"
                    return self._signer
        file_key = self._read_key_file()
        if file_key is not None:
            self._signer = HmacSigner(file_key)
            self.key_source = "file"
            return self._signer
        if create:
            fresh = os.urandom(32)
            self._write_key_file(fresh)
            self._signer = HmacSigner(fresh)
            self.key_source = "file"
            return self._signer
        return None

    # ------------------------------------------------------------------ chain state
    def _scan_chain(self) -> tuple[int, str]:
        """The last signed entry's (seq, hash), from the file, read once per process.
        Unsigned lines do not move the chain: the sequence counts signed entries."""
        if self._chain is not None:
            return self._chain
        seq, prev = 0, _ZERO_HASH
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (
                        isinstance(entry, dict)
                        and isinstance(entry.get("entry_hash"), str)
                        and isinstance(entry.get("seq"), int)
                    ):
                        seq, prev = entry["seq"], entry["entry_hash"]
        self._chain = (seq, prev)
        return self._chain

    # ------------------------------------------------------------------ write / read
    def record(self, event: str, **fields: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "event": event,
        }
        if self.session_id:
            entry["session"] = self.session_id
        entry.update(_truncate(fields))
        with self._lock:
            seq, prev = self._scan_chain()
            signer = self._resolve_signer(create=True)
            assert signer is not None  # create=True always resolves or raises
            entry["seq"] = seq + 1
            entry["prev"] = prev
            entry["key_id"] = self.key_id
            entry["entry_hash"] = signer.sign(_canonical(entry))
            line = json.dumps(entry, ensure_ascii=False, default=str)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self._chain = (entry["seq"], entry["entry_hash"])
        return entry

    def tail(self, n: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as fh:
            lines = deque(fh, maxlen=n)
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def verify(self) -> AuditReport:
        """Check every line's hash-chain link. A line whose content, timestamp or hash
        was changed, a deleted middle line (the ``prev``/``seq`` link breaks) and a
        reordered pair are all reported as broken, with the line number. Deleting
        lines off the tail leaves no trace in the chain itself (the last ``seq`` is
        reported so a caller that knows how many entries there were can notice)."""
        if not self.path.exists():
            return AuditReport(ok=True)
        with self.path.open("r", encoding="utf-8") as fh:
            raw_lines = fh.readlines()
        parsed: list[tuple[dict[str, Any] | None, bool]] = []
        signed_present = False
        for line in raw_lines:
            line = line.strip()
            if not line:
                parsed.append((None, True))
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                parsed.append((None, False))
                continue
            if isinstance(entry, dict) and "entry_hash" in entry:
                signed_present = True
            parsed.append((entry if isinstance(entry, dict) else None, True))
        signer: AuditSigner | None = None
        if signed_present:
            signer = self._resolve_signer(create=False)
            if signer is None:
                raise RuntimeError(
                    "no audit signing key is available (injected signer, "
                    f"{_AUDIT_KEY_ENV}, OS keychain or {_key_file_name(self.path)}); "
                    "the signed entries cannot be checked on this machine"
                )
        report = AuditReport(ok=True)
        expected_prev = _ZERO_HASH
        expected_seq: int | None = None
        for number, (entry, is_json) in enumerate(parsed, start=1):
            if entry is None:
                if not is_json:
                    report.corrupt.append({"line": number, "reason": "not valid JSON"})
                elif raw_lines[number - 1].strip():
                    report.corrupt.append({"line": number, "reason": "not a JSON object"})
                continue
            if "entry_hash" not in entry:
                report.unsigned += 1
                continue
            report.checked += 1
            reasons: list[str] = []
            tag = entry.get("entry_hash")
            if not isinstance(tag, str):
                reasons.append("entry_hash must be a string")
            elif signer is not None and not signer.verify(_canonical(entry), tag):
                reasons.append("entry_hash does not match the entry")
            if entry.get("prev") != expected_prev:
                reasons.append("prev does not match the previous entry")
            seq = entry.get("seq")
            if not isinstance(seq, int) or isinstance(seq, bool):
                reasons.append("seq must be an integer")
            elif expected_seq is not None and seq != expected_seq:
                reasons.append(f"seq gap: expected {expected_seq}, found {seq}")
            if reasons:
                report.broken.append({"line": number, "reasons": reasons})
            if isinstance(tag, str):
                expected_prev = tag
            if isinstance(seq, int) and not isinstance(seq, bool):
                expected_seq = seq + 1
                report.last_seq = seq
        report.ok = not report.corrupt and not report.broken
        return report


def _key_file_name(path: Path) -> str:
    return str(path.with_name("audit.key"))


def _main(argv: list[str] | None = None) -> int:
    """``python -m nanomuse.sentinel.audit --verify <path>``: print the verification
    summary and exit non-zero when a line is corrupt or broken."""
    parser = argparse.ArgumentParser(prog="nanomuse.sentinel.audit")
    parser.add_argument("--verify", metavar="PATH", required=True, help="audit log to check")
    args = parser.parse_args(argv)
    log = AuditLog(Path(args.verify))
    try:
        report = log.verify()
    except (RuntimeError, PermissionError, ValueError) as exc:
        print(f"audit verify: {exc}")
        return 2
    print(
        f"audit verify: ok={report.ok} checked={report.checked} "
        f"unsigned={report.unsigned} corrupt={len(report.corrupt)} "
        f"broken={len(report.broken)} last_seq={report.last_seq}"
    )
    for item in report.corrupt:
        print(f"  corrupt line {item['line']}: {item['reason']}")
    for item in report.broken:
        print(f"  broken line {item['line']}: {'; '.join(item['reasons'])}")
    return 0 if report.ok else 1


__all__ = ["AuditLog", "AuditReport", "AuditSigner", "HmacSigner", "channel_of"]


if __name__ == "__main__":
    raise SystemExit(_main())
