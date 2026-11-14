"""Privilege separation: the gatekeeper holds the keys.

One process, the gatekeeper, holds three things the agent process must never
touch: the Sentinel rules (as a settings snapshot loaded once at start), the
persistent grants file, and the audit signing key. The agent side computes
the policy's advice exactly as the in-process Sentinel would, then asks the
gatekeeper for the final decision; the gatekeeper re-evaluates with its own
copy of the rules, checks its own grants, signs the audit entry, and
answers. The key never crosses the channel, in either direction.

The channel is a Unix socket on Linux and macOS, where the peer is named by
its uid (SO_PEERCRED, LOCAL_PEERCRED), and a named pipe on Windows, where
the pipe's DACL names only the owner's SID and the client's SID is read
from its process token before anything is served. A platform with neither
is refused rather than served unauthenticated.

The key reaches the gatekeeper one of two ways, and no other: it is passed
on a file descriptor at spawn (Unix only; the launcher's job), or it is read
from the OS keychain (provisioned by `nanomuse gatekeeper-keygen`). There
is deliberately no file fallback: when neither is available the gatekeeper
refuses to start, and the agent side refuses to run a call (fail closed),
rather than quietly running without a gate.

The gatekeeper joins the running agent only when [sentinel] gatekeeper is
on (nanomuse/sentinel/gate.py); the in-process Sentinel stays the default.
Its limits, stated plainly: the peer check trusts the same user (a
deployment that separates users would check more), and the rules snapshot
is loaded once, so editing the rules afterwards changes nothing until the
gatekeeper restarts.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import secrets
import socket
import struct
import sys
import time
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nanomuse.config import SentinelSettings
from nanomuse.logger import logger
from nanomuse.sentinel.audit import AuditLog, HmacSigner, _canonical
from nanomuse.sentinel.grants import GrantStore, grant_key, normalize_scope
from nanomuse.sentinel.policy import Decision, Policy
from nanomuse.tools.base import CallAssessment

_KEYRING_SERVICE = "nanomuse-gatekeeper"
_KEYRING_ACCOUNT = "audit-signing"
_SOCKET_TIMEOUT_S = 30.0

_SECRET_KEYS = re.compile(
    r"(pass(word|wd|phrase)?|secret|token|api[_-]?key|auth|credential|cookie|otp|code|pin)",
    re.IGNORECASE,
)


class GatekeeperUnavailable(RuntimeError):
    """The gatekeeper cannot be reached, or cannot start: the caller must refuse
    the call and say why, never run it without a decision."""


class GatekeeperError(RuntimeError):
    pass


# ------------------------------------------- platform prerequisites
# The gatekeeper runs where the channel can name its peer: Linux
# (SO_PEERCRED) and macOS (LOCAL_PEERCRED) over a Unix socket, Windows
# over a named pipe checked by SID.  Anywhere else it refuses to start
# rather than serve a channel it cannot authenticate.
_PLATFORM = sys.platform
_IS_WINDOWS = _PLATFORM == "win32"


def _pipe_name(address: Path | str) -> str:
    """The Windows named pipe a gatekeeper address maps to.

    The configuration speaks of a socket path on every platform; the pipe
    namespace is flat, so an address already in pipe form is used as given
    and any other address names a pipe after a hash of itself: one pipe
    per data directory, stable across restarts."""
    text = str(address)
    if text.startswith("\\\\.\\pipe\\"):
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"\\\\.\\pipe\\nanomuse-gatekeeper-{digest}"


def _unix_socket_family() -> int:
    """The Unix domain socket family, or a refusal where it does not exist.

    Resolved through getattr: the attribute is absent from the stubs on
    platforms without Unix sockets, so naming it directly fails mypy there."""

    family = getattr(socket, "AF_UNIX", None)
    if family is None:
        raise GatekeeperUnavailable("Unix domain sockets are unavailable on this platform")
    return family


def _peer_cred_option() -> int:
    """The Linux socket option that reads a Unix peer's credentials, or a refusal."""

    option = getattr(socket, "SO_PEERCRED", None)
    if option is None:
        raise GatekeeperError("SO_PEERCRED is unavailable on this platform")
    return option


def _local_peercred() -> tuple[int, int]:
    """The macOS (level, option) pair that reads a Unix peer's credentials.

    SOL_LOCAL and LOCAL_PEERCRED are stable Darwin ABI constants (0 and
    1); the socket module does not promise to name them, so they are
    resolved through getattr with the ABI values as the fallback."""

    level = getattr(socket, "SOL_LOCAL", 0)
    option = getattr(socket, "LOCAL_PEERCRED", 1)
    return level, option


# struct xucred: version (u_short, offset 0), uid (uid_t, offset 4),
# then the group list; 76 bytes in all.
_XUCRED_SIZE = 76
_XUCRED_UID_OFFSET = 4


def _peer_uid(conn: socket.socket) -> int:
    """The uid of the process on the other end of a Unix socket.

    Linux answers SO_PEERCRED with a ucred (pid, uid, gid); macOS
    answers LOCAL_PEERCRED with an xucred whose uid sits at offset 4.
    A platform with neither is refused: an unauthenticated socket is
    worse than no gatekeeper."""

    try:
        if _PLATFORM == "darwin":
            level, option = _local_peercred()
            raw = conn.getsockopt(level, option, _XUCRED_SIZE)
            if len(raw) < _XUCRED_UID_OFFSET + 4:
                raise GatekeeperError("the peer credential answer was truncated")
            return struct.unpack_from("=I", raw, _XUCRED_UID_OFFSET)[0]
        if _PLATFORM.startswith("linux"):
            raw = conn.getsockopt(socket.SOL_SOCKET, _peer_cred_option(), struct.calcsize("3i"))
            _pid, uid, _gid = struct.unpack("3i", raw)
            return uid
    except OSError as exc:
        raise GatekeeperError(f"cannot read the peer credential: {exc}") from exc
    raise GatekeeperError(f"no peer credential API on this platform ({_PLATFORM})")


def _own_uid() -> int:
    """This process's user id, or a refusal where the platform has none."""

    getuid = getattr(os, "getuid", None)
    if getuid is None:
        raise GatekeeperError("os.getuid is unavailable on this platform")
    return getuid()


# ------------------------------------------------------- Windows named pipes
# The Windows shape of the same separation: a named pipe whose DACL names
# only the owner's SID, and the client's SID read from its process token
# before anything is served. ctypes only, built lazily by _win32() and only
# ever called on win32: nothing in this section runs on Linux or macOS.

_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_PIPE_ACCESS_DUPLEX = 0x00000003
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_READMODE_BYTE = 0x00000000
_PIPE_WAIT = 0x00000000
_PIPE_NOWAIT = 0x00000001
_PIPE_UNLIMITED_INSTANCES = 255
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PIPE_BUSY = 231
_ERROR_NO_DATA = 232
_ERROR_PIPE_CONNECTED = 535

_win32_cache: Any = None


def _win32() -> Any:
    """The Win32 entry points the pipe transport needs, with signatures.

    Cached: building this loads kernel32 and advapi32, which only exist
    on Windows, so it happens on first use and never at import."""
    global _win32_cache
    if _win32_cache is not None:
        return _win32_cache
    import ctypes
    from ctypes import wintypes

    windll = getattr(ctypes, "WinDLL", None)
    if windll is None:  # unreachable: _win32() is only called on win32
        raise GatekeeperError("Win32 is unavailable on this platform")
    kernel32 = windll("kernel32", use_last_error=True)
    advapi32 = windll("advapi32", use_last_error=True)

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("n_length", wintypes.DWORD),
            ("security_descriptor", ctypes.c_void_p),
            ("inherit_handle", wintypes.BOOL),
        ]

    def sig(fn: Any, restype: Any, *argtypes: Any) -> Any:
        fn.restype = restype
        fn.argtypes = list(argtypes)
        return fn

    api = types.SimpleNamespace(
        ctypes=ctypes,
        wintypes=wintypes,
        SecurityAttributes=SecurityAttributes,
        CreateNamedPipeW=sig(
            kernel32.CreateNamedPipeW,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
        ),
        ConnectNamedPipe=sig(
            kernel32.ConnectNamedPipe, wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p
        ),
        DisconnectNamedPipe=sig(kernel32.DisconnectNamedPipe, wintypes.BOOL, ctypes.c_void_p),
        SetNamedPipeHandleState=sig(
            kernel32.SetNamedPipeHandleState,
            wintypes.BOOL,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ),
        GetNamedPipeClientProcessId=sig(
            kernel32.GetNamedPipeClientProcessId,
            wintypes.BOOL,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
        ),
        CreateFileW=sig(
            kernel32.CreateFileW,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
        ),
        WaitNamedPipeW=sig(
            kernel32.WaitNamedPipeW, wintypes.BOOL, ctypes.c_wchar_p, wintypes.DWORD
        ),
        ReadFile=sig(
            kernel32.ReadFile,
            wintypes.BOOL,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ),
        WriteFile=sig(
            kernel32.WriteFile,
            wintypes.BOOL,
            ctypes.c_void_p,
            ctypes.c_char_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ),
        FlushFileBuffers=sig(kernel32.FlushFileBuffers, wintypes.BOOL, ctypes.c_void_p),
        CloseHandle=sig(kernel32.CloseHandle, wintypes.BOOL, ctypes.c_void_p),
        GetCurrentProcess=sig(kernel32.GetCurrentProcess, ctypes.c_void_p),
        OpenProcess=sig(
            kernel32.OpenProcess,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ),
        LocalFree=sig(kernel32.LocalFree, ctypes.c_void_p, ctypes.c_void_p),
        OpenProcessToken=sig(
            advapi32.OpenProcessToken,
            wintypes.BOOL,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ),
        GetTokenInformation=sig(
            advapi32.GetTokenInformation,
            wintypes.BOOL,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ),
        ConvertSidToStringSidW=sig(
            advapi32.ConvertSidToStringSidW,
            wintypes.BOOL,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p),
        ),
        ConvertStringSecurityDescriptorToSecurityDescriptorW=sig(
            advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW,
            wintypes.BOOL,
            ctypes.c_wchar_p,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        ),
    )
    _win32_cache = api
    return api


def _invalid_handle(handle: Any) -> bool:
    return handle is None or handle == 0xFFFFFFFFFFFFFFFF


def _token_user_sid(api: Any, token: Any) -> str:
    """The SID string of a token's user (TokenUser: a PSID, then attributes)."""
    ctypes, wintypes = api.ctypes, api.wintypes
    needed = wintypes.DWORD(0)
    api.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(needed))
    buffer = ctypes.create_string_buffer(needed.value)
    if not api.GetTokenInformation(token, _TOKEN_USER, buffer, needed.value, ctypes.byref(needed)):
        raise GatekeeperError("cannot read the token's user")
    sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
    text = ctypes.c_wchar_p()
    if not api.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise GatekeeperError("cannot render the token's SID")
    try:
        return str(text.value)
    finally:
        api.LocalFree(text)


def _own_sid() -> str:
    """This process's user SID, the pipe's one allowed peer."""
    api = _win32()
    token = api.ctypes.c_void_p()
    if not api.OpenProcessToken(api.GetCurrentProcess(), _TOKEN_QUERY, api.ctypes.byref(token)):
        raise GatekeeperError("cannot open this process's token")
    try:
        return _token_user_sid(api, token)
    finally:
        api.CloseHandle(token)


def _pipe_peer_sid(api: Any, handle: Any) -> str:
    """The SID of the process on the other end of the pipe."""
    ctypes, wintypes = api.ctypes, api.wintypes
    pid = wintypes.DWORD(0)
    if not api.GetNamedPipeClientProcessId(handle, ctypes.byref(pid)):
        raise GatekeeperError("cannot name the pipe's client process")
    process = api.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if _invalid_handle(process):
        raise GatekeeperError("cannot open the pipe's client process")
    token = ctypes.c_void_p()
    try:
        if not api.OpenProcessToken(process, _TOKEN_QUERY, ctypes.byref(token)):
            raise GatekeeperError("cannot open the pipe client's token")
        try:
            return _token_user_sid(api, token)
        finally:
            api.CloseHandle(token)
    finally:
        api.CloseHandle(process)


def _pipe_security(api: Any, sid: str) -> tuple[Any, Any]:
    """Security attributes whose DACL grants only ``sid`` full access, and
    the descriptor behind them. The caller keeps both alive for as long as
    the pipe exists: the attributes point into the descriptor."""
    descriptor = api.ctypes.c_void_p()
    sddl = f"D:P(A;;GA;;;{sid})"
    if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, api.ctypes.byref(descriptor), None
    ):
        raise GatekeeperError("cannot build the pipe's security descriptor")
    attrs = api.SecurityAttributes()
    attrs.n_length = api.ctypes.sizeof(attrs)
    attrs.security_descriptor = descriptor
    attrs.inherit_handle = False
    return attrs, descriptor


def _pipe_write_all(api: Any, handle: Any, data: bytes) -> bool:
    written = api.wintypes.DWORD(0)
    view = data
    while view:
        if not api.WriteFile(handle, view, len(view), api.ctypes.byref(written), None):
            return False
        view = view[written.value :]
    return True


# ------------------------------------------------------------------ the key
def _read_key_from_fd(fd: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total < 32:
        chunk = os.read(fd, 32 - total)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    key = b"".join(chunks)
    if len(key) != 32:
        raise GatekeeperUnavailable(f"the key passed at spawn must be 32 bytes, got {len(key)}")
    return key


def resolve_gatekeeper_key(key_fd: int | None) -> bytes:
    """The gatekeeper's signing key: from the spawn file descriptor, else from
    the OS keychain. Nothing else: no file, no environment, no fallback."""
    if key_fd is not None:
        try:
            return _read_key_from_fd(key_fd)
        finally:
            os.close(key_fd)
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        keyring = None  # type: ignore[assignment]
    if keyring is not None:
        try:
            stored = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
        except Exception:  # noqa: BLE001 - no keychain backend: unavailable, not fatal
            stored = None
        if isinstance(stored, str) and stored:
            try:
                key = bytes.fromhex(stored.strip())
            except ValueError:
                key = b""
            if len(key) == 32:
                return key
    raise GatekeeperUnavailable(
        "no gatekeeper key is available: pass one on a file descriptor at spawn, "
        "or store one in the OS keychain; refusing to fall back to a file"
    )


def provision_gatekeeper_key() -> None:
    """Create a fresh gatekeeper signing key in the OS keychain, replacing
    any stored one. The one provisioning path (`nanomuse gatekeeper-keygen`):
    the gatekeeper itself only ever reads the keychain, never writes it, and
    rotating the key starts the gatekeeper's audit chain over."""
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        keyring = None  # type: ignore[assignment]
    if keyring is None:
        raise GatekeeperUnavailable("the keyring package is not installed")
    try:
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT, secrets.token_bytes(32).hex())
    except Exception as exc:  # noqa: BLE001 - no backend, a locked keychain: say so
        raise GatekeeperUnavailable(f"the keychain would not take the key: {exc}") from exc


# ------------------------------------------------------------------ the server
def _shape(value: Any, depth: int = 0) -> Any:
    """What of a call's arguments the audit line may say: shapes, never values."""
    if isinstance(value, dict):
        if depth >= 2:
            return {"keys": len(value)}
        return {
            str(k): "***" if _SECRET_KEYS.search(str(k)) else _shape(v, depth + 1)
            for k, v in list(value.items())[:12]
        }
    if isinstance(value, str):
        return f"str[{len(value)}]"
    if isinstance(value, (list, tuple)):
        return f"list[{len(value)}]"
    return value


class GatekeeperServer:
    """The decision side. One connection at a time, in arrival order: the audit
    chain is written in the order decisions are made."""

    def __init__(
        self,
        socket_path: Path,
        settings: SentinelSettings,
        grants_path: Path | None,
        audit_path: Path,
        key: bytes,
    ):
        self.socket_path = Path(socket_path)
        self.policy = Policy(settings)
        self.grants = GrantStore(grants_path)
        self.audit = AuditLog(audit_path, signer=HmacSigner(key), key_id="gatekeeper")
        self._stop = False

    # ------------------------------------------------------------------ socket
    def _peer_uid(self, conn: socket.socket) -> int:
        return _peer_uid(conn)

    def serve_forever(self) -> None:
        if _IS_WINDOWS:
            self._serve_windows()
            return
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        server = socket.socket(_unix_socket_family(), socket.SOCK_STREAM)
        try:
            server.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o600)
            server.listen(8)
            server.settimeout(0.5)
            print("READY", flush=True)
            while not self._stop:
                try:
                    conn, _ = server.accept()
                except TimeoutError:
                    continue
                try:
                    self._serve_connection(conn)
                except Exception as exc:  # noqa: BLE001 - one bad peer ends one connection
                    logger.warning("gatekeeper: connection failed: {}", exc)
                finally:
                    conn.close()
        finally:
            server.close()
            if self.socket_path.exists():
                self.socket_path.unlink()

    # ------------------------------------------------------------- Windows
    def _serve_windows(self) -> None:
        """The named-pipe shape of serve_forever: one connection at a time,
        the peer's SID checked before anything is served, the same newline
        JSON protocol as the socket. The supervisor stops this process by
        terminating it, so the blocking connect needs no stop check."""
        api = _win32()
        ctypes, wintypes = api.ctypes, api.wintypes
        name = _pipe_name(self.socket_path)
        sid = _own_sid()
        attrs, descriptor = _pipe_security(api, sid)
        self._pipe_security = (attrs, descriptor)  # kept alive for the process
        announced = False
        while not self._stop:
            handle = api.CreateNamedPipeW(
                name,
                _PIPE_ACCESS_DUPLEX,
                _PIPE_TYPE_BYTE | _PIPE_READMODE_BYTE | _PIPE_WAIT,
                _PIPE_UNLIMITED_INSTANCES,
                65536,
                65536,
                0,
                ctypes.byref(attrs),
            )
            if _invalid_handle(handle):
                raise GatekeeperError(
                    f"cannot create the gatekeeper pipe (win32 error {ctypes.get_last_error()})"
                )
            try:
                if not announced:
                    print("READY", flush=True)
                    announced = True
                connected = api.ConnectNamedPipe(handle, None) or (
                    ctypes.get_last_error() == _ERROR_PIPE_CONNECTED
                )
                if not connected:
                    continue
                try:
                    peer = _pipe_peer_sid(api, handle)
                except GatekeeperError as exc:
                    logger.warning("gatekeeper: {}", exc)
                    continue
                if peer != sid:
                    logger.warning("gatekeeper: refusing a pipe peer from another user")
                    continue
                mode = wintypes.DWORD(_PIPE_READMODE_BYTE | _PIPE_NOWAIT)
                api.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None)
                self._serve_pipe(api, handle)
            finally:
                api.DisconnectNamedPipe(handle)
                api.CloseHandle(handle)

    def _serve_pipe(self, api: Any, handle: Any) -> None:
        """Requests until the peer goes away or stays silent past the same
        idle timeout the socket side uses."""
        ctypes, wintypes = api.ctypes, api.wintypes
        buffer = ctypes.create_string_buffer(65536)
        read = wintypes.DWORD(0)
        pending = b""
        idle_since = time.monotonic()
        while not self._stop:
            if not api.ReadFile(handle, buffer, 65536, ctypes.byref(read), None):
                if ctypes.get_last_error() == _ERROR_NO_DATA:
                    if time.monotonic() - idle_since > _SOCKET_TIMEOUT_S:
                        return
                    # A short poll: the round trip is budgeted at 20 ms, and a
                    # 20 ms sleep here would spend nearly all of it waiting for
                    # the request to be noticed. The loop only spins while a
                    # connection is open, and connections are one-shot.
                    time.sleep(0.001)
                    continue
                return  # the peer closed, or the pipe broke
            if read.value == 0:
                return
            idle_since = time.monotonic()
            pending += buffer.raw[: read.value]
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                if line.strip():
                    response = self._handle(line)
                    payload = json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n"
                    if not _pipe_write_all(api, handle, payload):
                        return
                    api.FlushFileBuffers(handle)

    def _serve_connection(self, conn: socket.socket) -> None:
        if self._peer_uid(conn) != _own_uid():
            logger.warning("gatekeeper: refusing a peer from another user")
            return
        conn.settimeout(_SOCKET_TIMEOUT_S)
        buf = b""
        while not self._stop:
            try:
                chunk = conn.recv(65536)
            except TimeoutError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    response = self._handle(line)
                    conn.sendall(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")

    # ------------------------------------------------------------------ requests
    def _handle(self, line: bytes) -> dict[str, Any]:
        try:
            request = json.loads(line.decode("utf-8"))
        except ValueError:
            return {"id": None, "error": "request is not JSON"}
        if not isinstance(request, dict):
            return {"id": None, "error": "request is not an object"}
        op = request.get("op")
        req_id = request.get("id")
        try:
            if op == "ping":
                return {"id": req_id, "ok": True}
            if op == "decide":
                return self._decide(req_id, request)
            if op == "grant":
                return self._grant(req_id, request)
            if op == "verify":
                return self._verify(req_id, request)
            return {"id": req_id, "error": f"unknown op {str(op)[:40]!r}"}
        except Exception as exc:  # noqa: BLE001 - the peer gets a reason, never a traceback
            return {"id": req_id, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    def _decide(self, req_id: Any, request: dict[str, Any]) -> dict[str, Any]:
        tool = str(request.get("tool") or "")
        args = request.get("args") or {}
        if not isinstance(args, dict):
            raise GatekeeperError("args must be an object")
        assessment = CallAssessment.model_validate(request.get("assessment") or {})
        tainted = bool(request.get("tainted", False))
        conversation = request.get("conversation")
        result = self.policy.evaluate(tool, args, assessment, tainted=tainted)
        decision, reasons = result.decision, list(result.reasons)
        scope: str | None = None
        if decision == Decision.ASK:
            key = grant_key(tool, assessment.target or assessment.egress_target)
            grant = self.grants.match(key, conversation)
            if grant is not None:
                decision = Decision.ALLOW
                scope = grant.scope
                reasons.append(f"covered by your '{grant.scope}' permission for {grant.key}")
        advice = request.get("advice") or {}
        entry = self.audit.record(
            "tool_call",
            tool=tool,
            channel="gatekeeper",
            args=_shape(args),
            summary=assessment.summary,
            risk=assessment.risk.value,
            decision=decision.value,
            advice_decision=str(advice.get("decision") or ""),
            reasons=reasons,
            tainted=tainted,
            egress_target=assessment.egress_target,
            grant_scope=scope,
        )
        return {
            "id": req_id,
            "decision": decision.value,
            "reasons": reasons,
            "tainted_ask": result.tainted_ask,
            "grant_scope": scope,
            "audit_seq": entry["seq"],
        }

    def _grant(self, req_id: Any, request: dict[str, Any]) -> dict[str, Any]:
        """Record a standing permission the person just gave at the prompt.

        The prompt itself happens on the agent side, which owns the UI; the
        grant belongs here, with the key, so the next decide can settle on it.
        A one-off approval stores nothing, exactly like the local store."""
        tool = str(request.get("tool") or "")
        if not tool:
            raise GatekeeperError("a grant needs a tool")
        scope = normalize_scope(request.get("scope"))
        if scope == "once":
            return {"id": req_id, "ok": True, "stored": False}
        target = request.get("target")
        target = str(target)[:300] if target else None
        conversation = request.get("conversation")
        conversation = str(conversation)[:200] if conversation else None
        self.grants.add(tool, target, scope, conversation)
        return {"id": req_id, "ok": True, "stored": True, "key": grant_key(tool, target)}

    def _verify(self, req_id: Any, request: dict[str, Any]) -> dict[str, Any]:
        entry = request.get("entry")
        if not isinstance(entry, dict):
            raise GatekeeperError("entry must be an object")
        tag = entry.get("entry_hash")
        signer = self.audit._signer
        valid = (
            isinstance(tag, str) and signer is not None and signer.verify(_canonical(entry), tag)
        )
        return {"id": req_id, "valid": valid}


# ------------------------------------------------------------------ the client
@dataclass(frozen=True)
class GatekeeperDecision:
    decision: Decision
    reasons: list[str] = field(default_factory=list)
    tainted_ask: bool = False
    grant_scope: str | None = None
    audit_seq: int | None = None


class GatekeeperClient:
    """The agent side: one request per connection, so a dead gatekeeper is
    noticed on the next call instead of carried as a stale socket."""

    def __init__(self, socket_path: Path | str, timeout: float = 5.0):
        self.socket_path = str(socket_path)
        self.timeout = timeout

    def _call(self, payload: dict[str, Any]) -> dict[str, Any]:
        line = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        buf = self._call_windows(line) if _IS_WINDOWS else self._call_unix(line)
        try:
            response = json.loads(buf.decode("utf-8"))
        except ValueError as exc:
            raise GatekeeperUnavailable("the gatekeeper answered with bad JSON") from exc
        if isinstance(response, dict) and response.get("error"):
            raise GatekeeperUnavailable(f"the gatekeeper refused the request: {response['error']}")
        return response

    def _call_unix(self, line: bytes) -> bytes:
        sock = socket.socket(_unix_socket_family(), socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect(self.socket_path)
            sock.sendall(line)
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    raise GatekeeperUnavailable("the gatekeeper closed the connection")
                buf += chunk
            return buf
        except GatekeeperUnavailable:
            raise
        except (TimeoutError, OSError) as exc:
            raise GatekeeperUnavailable(f"the gatekeeper cannot be reached: {exc}") from exc
        finally:
            with contextlib.suppress(Exception):
                sock.close()

    def _call_windows(self, line: bytes) -> bytes:
        api = _win32()
        ctypes, wintypes = api.ctypes, api.wintypes
        name = _pipe_name(self.socket_path)
        deadline = time.monotonic() + self.timeout
        handle: Any = None
        while handle is None:
            api.WaitNamedPipeW(name, max(1, int(self.timeout * 1000)))
            candidate = api.CreateFileW(
                name, _GENERIC_READ | _GENERIC_WRITE, 0, None, _OPEN_EXISTING, 0, None
            )
            if not _invalid_handle(candidate):
                handle = candidate
                break
            err = ctypes.get_last_error()
            # Busy means every instance is taken; file not found means the
            # server is between instances, having just closed the previous
            # connection and not yet created the next. Both clear within a
            # few milliseconds, so both are retried rather than reported, on
            # a short sleep: a long one would spend the round-trip budget on
            # every retry.
            if err in (_ERROR_PIPE_BUSY, _ERROR_FILE_NOT_FOUND) and time.monotonic() < deadline:
                time.sleep(0.002)
                continue
            raise GatekeeperUnavailable(f"the gatekeeper cannot be reached (win32 error {err})")
        try:
            if not _pipe_write_all(api, handle, line):
                raise GatekeeperUnavailable("the gatekeeper closed the connection")
            buffer = ctypes.create_string_buffer(65536)
            read = wintypes.DWORD(0)
            buf = b""
            while b"\n" not in buf:
                if not api.ReadFile(handle, buffer, 65536, ctypes.byref(read), None):
                    raise GatekeeperUnavailable("the gatekeeper closed the connection")
                if read.value == 0:
                    raise GatekeeperUnavailable("the gatekeeper closed the connection")
                buf += buffer.raw[: read.value]
            return buf
        finally:
            api.CloseHandle(handle)

    def ping(self) -> bool:
        try:
            return bool(self._call({"id": "ping", "op": "ping"}).get("ok"))
        except GatekeeperUnavailable:
            return False

    def decide(
        self,
        tool: str,
        args: dict[str, Any],
        assessment: CallAssessment,
        tainted: bool = False,
        conversation: str | None = None,
        advice: dict[str, Any] | None = None,
    ) -> GatekeeperDecision:
        response = self._call(
            {
                "id": f"decide-{time.monotonic_ns()}",
                "op": "decide",
                "tool": tool,
                "args": args,
                "assessment": assessment.model_dump(mode="json"),
                "tainted": tainted,
                "conversation": conversation,
                "advice": advice or {},
            }
        )
        return GatekeeperDecision(
            decision=Decision(str(response["decision"])),
            reasons=list(response.get("reasons") or []),
            tainted_ask=bool(response.get("tainted_ask")),
            grant_scope=response.get("grant_scope"),
            audit_seq=response.get("audit_seq"),
        )

    def grant(
        self,
        tool: str,
        target: str | None,
        scope: str,
        conversation: str | None = None,
    ) -> bool:
        """Hand a standing permission the person just gave to the gatekeeper,
        whose grant store is the one its decisions settle on. Returns whether
        anything was stored (a one-off approval stores nothing)."""
        response = self._call(
            {
                "id": f"grant-{time.monotonic_ns()}",
                "op": "grant",
                "tool": tool,
                "target": target,
                "scope": scope,
                "conversation": conversation,
            }
        )
        return bool(response.get("stored"))

    def verify_entry(self, entry: dict[str, Any]) -> bool:
        response = self._call({"id": "verify", "op": "verify", "entry": entry})
        return bool(response.get("valid"))


class GatekeeperSentinel:
    """A Sentinel-shaped front end over the gatekeeper: the policy runs here
    for the advice, the decision comes back from the other process."""

    def __init__(self, settings: SentinelSettings, client: GatekeeperClient):
        self.settings = settings
        self.policy = Policy(settings)
        self.client = client

    def decide(
        self,
        tool: str,
        args: dict[str, Any],
        assessment: CallAssessment,
        tainted: bool = False,
        conversation: str | None = None,
    ) -> GatekeeperDecision:
        advice = self.policy.evaluate(tool, args, assessment, tainted=tainted)
        return self.client.decide(
            tool,
            args,
            assessment,
            tainted=tainted,
            conversation=conversation,
            advice={"decision": advice.decision.value, "reasons": advice.reasons},
        )


# ------------------------------------------------------------------ supervisor
class GatekeeperSupervisor:
    """Spawn the gatekeeper, hand it the key on a file descriptor, watch it die.

    The supervisor holds the key material only to pass it at spawn; the agent
    process that uses the client never sees it. ``key_material`` of None means
    the child must find the key in the OS keychain, or refuse to start."""

    def __init__(
        self,
        socket_path: Path,
        settings: SentinelSettings,
        grants_path: Path | None,
        audit_path: Path,
        key_material: bytes | None,
        python: str = sys.executable,
    ):
        self.socket_path = Path(socket_path)
        self.settings = settings
        self.grants_path = grants_path
        self.audit_path = Path(audit_path)
        self.key_material = key_material
        self._python = python
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr: asyncio.Task[None] | None = None
        self.stderr_lines: list[str] = []
        self.started = False

    async def start(self) -> None:
        if self.started:
            return
        if self.key_material is not None and _IS_WINDOWS:
            # Descriptor passing is Unix-only; on Windows the child takes the
            # key from the keychain, provisioned by `nanomuse gatekeeper-keygen`.
            raise GatekeeperUnavailable(
                "on Windows the gatekeeper takes its key from the keychain only; "
                "run `nanomuse gatekeeper-keygen` first"
            )
        # The settings file needs a real directory: beside the audit log on
        # Windows, where the address names a pipe rather than a file.
        workdir = self.audit_path.parent if _IS_WINDOWS else self.socket_path.parent
        workdir.mkdir(parents=True, exist_ok=True)
        settings_path = workdir / "gatekeeper-settings.json"
        settings_path.write_text(
            json.dumps(self.settings.model_dump(mode="json"), ensure_ascii=False), "utf-8"
        )
        args = [
            self._python,
            "-m",
            "nanomuse.sentinel.gatekeeper",
            "--socket",
            str(self.socket_path),
            "--settings",
            str(settings_path),
            "--audit",
            str(self.audit_path),
        ]
        if self.grants_path is not None:
            args += ["--grants", str(self.grants_path)]
        pass_fds: tuple[int, ...] = ()
        read_fd: int | None = None
        write_fd: int | None = None
        if self.key_material is not None:
            read_fd, write_fd = os.pipe()
            args += ["--key-fd", str(read_fd)]
            pass_fds = (read_fd,)
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            pass_fds=pass_fds,
            close_fds=True,
        )
        try:
            if read_fd is not None and write_fd is not None:
                os.close(read_fd)
                os.write(write_fd, self.key_material or b"")
                os.close(write_fd)
            assert self._proc.stdout is not None
            line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=15)
            if line.strip() != b"READY":
                err = b""
                if self._proc.stderr is not None:
                    with contextlib.suppress(asyncio.TimeoutError):
                        err = await asyncio.wait_for(self._proc.stderr.read(), timeout=2)
                code = await self._proc.wait()
                raise GatekeeperUnavailable(
                    f"the gatekeeper did not start (exit {code}): {err.decode(errors='replace')[-500:]}"
                )
        except Exception:
            await self.stop()
            raise
        assert self._proc.stderr is not None
        self._stderr = asyncio.create_task(self._drain_stderr())
        self.started = True

    async def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        try:
            async for raw in self._proc.stderr:
                self.stderr_lines.append(raw.decode("utf-8", errors="replace").rstrip())
        except asyncio.CancelledError:
            return

    async def stop(self) -> None:
        self.started = False
        proc, self._proc = self._proc, None
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except TimeoutError:
                proc.kill()
                await proc.wait()
        if self._stderr is not None:
            self._stderr.cancel()
            self._stderr = None
        if not _IS_WINDOWS and self.socket_path.exists():
            with contextlib.suppress(OSError):
                self.socket_path.unlink()

    async def __aenter__(self) -> GatekeeperSupervisor:
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()


# ------------------------------------------------------------------ entry point
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The Sentinel gatekeeper process.")
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--grants", type=Path, default=None)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--key-fd", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        settings = SentinelSettings.model_validate(json.loads(args.settings.read_text("utf-8")))
        key = resolve_gatekeeper_key(args.key_fd)
    except (GatekeeperUnavailable, ValueError, OSError) as exc:
        print(f"gatekeeper: {exc}", file=sys.stderr)
        return 1
    server = GatekeeperServer(args.socket, settings, args.grants, args.audit, key)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GatekeeperClient",
    "GatekeeperDecision",
    "GatekeeperError",
    "GatekeeperSentinel",
    "GatekeeperServer",
    "GatekeeperSupervisor",
    "GatekeeperUnavailable",
    "provision_gatekeeper_key",
    "resolve_gatekeeper_key",
]
