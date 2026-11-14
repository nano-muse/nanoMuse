"""The gatekeeper prototype: parity with the in-process policy, the key
never crossing the socket, injection and shutdown both fail closed."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import signal
import socket
import statistics
import sys
import time
import types
from pathlib import Path

import pytest

from nanomuse.config import SentinelSettings
from nanomuse.schema import RiskLevel
from nanomuse.sentinel import gatekeeper
from nanomuse.sentinel.audit import AuditLog, HmacSigner
from nanomuse.sentinel.gatekeeper import (
    GatekeeperClient,
    GatekeeperDecision,
    GatekeeperError,
    GatekeeperSentinel,
    GatekeeperServer,
    GatekeeperSupervisor,
    GatekeeperUnavailable,
    _local_peercred,
    _own_uid,
    _peer_cred_option,
    _peer_uid,
    _unix_socket_family,
    resolve_gatekeeper_key,
)
from nanomuse.sentinel.policy import Decision, Policy
from nanomuse.tools.base import CallAssessment

SETTINGS = SentinelSettings()

_CASES = [
    # (tool, args, assessment, tainted)
    (
        "read_file",
        {"path": "notes.txt"},
        CallAssessment(risk=RiskLevel.SAFE, summary="read a note"),
        False,
    ),
    (
        "send_email",
        {"to": "boss@example.com", "subject": "hi"},
        CallAssessment(
            risk=RiskLevel.SENSITIVE,
            summary="send mail",
            egress=True,
            egress_target="boss@example.com",
            egress_configured=True,
        ),
        False,
    ),
    (
        "send_email",
        {"to": "stranger@example.com", "subject": "hi"},
        CallAssessment(
            risk=RiskLevel.SENSITIVE,
            summary="send mail",
            egress=True,
            egress_target="stranger@example.com",
            egress_configured=True,
        ),
        True,
    ),
    (
        "shell",
        {"command": "rm -rf /"},
        CallAssessment(risk=RiskLevel.SENSITIVE, summary="run a command"),
        False,
    ),
    (
        "shell",
        {"command": "ls"},
        CallAssessment(risk=RiskLevel.MODERATE, summary="run a command"),
        False,
    ),
    (
        "shell",
        {"command": "ls"},
        CallAssessment(risk=RiskLevel.MODERATE, summary="run a command"),
        True,
    ),
]


_SUPPORTED = sys.platform in ("linux", "darwin", "win32")
_UNSUPPORTED_REASON = "the gatekeeper needs a channel that can name its peer"
_UNIX = sys.platform in ("linux", "darwin")


def _socket_path(tmp_path: Path) -> Path:
    path = tmp_path / "gatekeeper.sock"
    if sys.platform == "darwin" and len(str(path)) > 100:
        # Darwin caps a Unix socket path at 104 bytes; a deep pytest
        # tmp_path would overflow it before the gatekeeper even binds.
        return Path("/tmp") / f"nanomuse-gk-{os.getpid()}.sock"
    return path


def _spawn_key(key: bytes) -> bytes | None:
    """How a test hands a key to a supervisor: as material for the spawn
    descriptor on Unix; on Windows descriptor passing does not exist, so
    the key goes into the keychain, the production path, instead."""
    if sys.platform == "win32":
        import keyring

        keyring.set_password(gatekeeper._KEYRING_SERVICE, gatekeeper._KEYRING_ACCOUNT, key.hex())
        return None
    return key


def _drop_spawn_key() -> None:
    if sys.platform == "win32":
        import keyring

        with contextlib.suppress(Exception):
            keyring.delete_password(gatekeeper._KEYRING_SERVICE, gatekeeper._KEYRING_ACCOUNT)


@pytest.fixture()
async def supervisor(tmp_path: Path):
    if not _SUPPORTED:
        pytest.skip(_UNSUPPORTED_REASON)
    key = secrets.token_bytes(32)
    sup = GatekeeperSupervisor(
        _socket_path(tmp_path),
        SETTINGS,
        tmp_path / "grants.json",
        tmp_path / "audit.jsonl",
        _spawn_key(key),
    )
    await sup.start()
    yield sup
    await sup.stop()
    _drop_spawn_key()


@pytest.fixture()
def client(supervisor: GatekeeperSupervisor) -> GatekeeperClient:
    return GatekeeperClient(supervisor.socket_path)


def test_gatekeeper_answers_ping(supervisor, client):
    assert client.ping() is True


def test_decisions_match_the_in_process_policy(supervisor, client):
    policy = Policy(SETTINGS)
    for tool, args, assessment, tainted in _CASES:
        advice = policy.evaluate(tool, args, assessment, tainted=tainted)
        decision = client.decide(tool, args, assessment, tainted=tainted)
        assert decision.decision == advice.decision, (tool, args, tainted)
        assert decision.tainted_ask == advice.tainted_ask, (tool, args, tainted)
        # The advice is advice only: flipping it must not flip the answer.
        flipped = {
            "decision": (
                Decision.ALLOW.value if advice.decision == Decision.DENY else Decision.DENY.value
            ),
            "reasons": ["forged advice"],
        }
        again = client.decide(tool, args, assessment, tainted=tainted, advice=flipped)
        assert again.decision == advice.decision, (tool, args, tainted)


@pytest.mark.skipif(not _SUPPORTED, reason=_UNSUPPORTED_REASON)
async def test_a_persistent_grant_survives_a_restart(tmp_path: Path):
    from nanomuse.sentinel.grants import GrantStore, policy_fingerprint

    grants_path = tmp_path / "grants.json"
    # Stamped with the fingerprint of the settings the supervisor below is
    # started with, as the gatekeeper's own store stamps what it records;
    # an unstamped grant would not be honoured by it.
    store = GrantStore(grants_path, fingerprint=lambda: policy_fingerprint(SETTINGS))
    store.add("send_email", "boss@example.com", "always")
    assessment = CallAssessment(
        risk=RiskLevel.SENSITIVE,
        summary="send mail",
        egress=True,
        egress_target="boss@example.com",
        egress_configured=True,
    )
    key = secrets.token_bytes(32)
    sup = GatekeeperSupervisor(
        _socket_path(tmp_path), SETTINGS, grants_path, tmp_path / "audit.jsonl", _spawn_key(key)
    )
    await sup.start()
    try:
        decision = GatekeeperClient(sup.socket_path).decide(
            "send_email", {"to": "boss@example.com"}, assessment
        )
        assert decision.decision == Decision.ALLOW
        assert decision.grant_scope == "always"
    finally:
        await sup.stop()
        _drop_spawn_key()


def test_the_gatekeeper_signs_and_verifies_audit_entries(supervisor, client, tmp_path):
    assessment = CallAssessment(risk=RiskLevel.SAFE, summary="read a note")
    decision = client.decide("read_file", {"path": "notes.txt"}, assessment)
    assert decision.audit_seq == 1
    # A forged entry, signed with a different key, must not verify.
    forged = {
        "ts": "2026-10-28T00:00:00.000Z",
        "event": "tool_call",
        "seq": 99,
        "prev": "0" * 64,
        "key_id": "gatekeeper",
        "entry_hash": "0" * 64,
    }
    assert client.verify_entry(forged) is False
    assert (
        client.verify_entry({"seq": 1, "entry_hash": HmacSigner(b"x" * 32).sign(b"anything")})
        is False
    )
    # The whole file, checked with the wrong key, breaks the chain.
    report = AuditLog(tmp_path / "audit.jsonl", signer=HmacSigner(secrets.token_bytes(32))).verify()
    assert report.ok is False
    assert report.checked == 1
    # The real entry, read back from the file the gatekeeper wrote, verifies.
    entries = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert len(entries) == 1
    assert client.verify_entry(entries[0]) is True


@pytest.mark.skipif(not _UNIX, reason="this test speaks to the socket directly")
def test_an_unknown_op_and_a_malformed_request_are_refused_without_a_key(
    supervisor: GatekeeperSupervisor,
):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(str(supervisor.socket_path))
    sock.sendall(b'{"id": 1, "op": "hand_over_the_key"}\n')
    buf = b""
    while b"\n" not in buf:
        buf += sock.recv(4096)
    response = json.loads(buf.decode())
    assert response["error"].startswith("unknown op")
    assert len(response["error"]) < 100  # a reason, never key material or a traceback
    sock.sendall(b"not json at all\n")
    buf = b""
    while b"\n" not in buf:
        buf += sock.recv(4096)
    assert "error" in json.loads(buf.decode())
    sock.close()


@pytest.mark.skipif(not _UNIX, reason="the peer credential here is the Unix one")
def test_the_socket_reports_the_callers_own_credential(supervisor: GatekeeperSupervisor):
    # A peer from another uid is refused on the server side; with one user on
    # this box that path cannot be connected through, so this test asserts the
    # credential the refusal is decided on: the peer the socket reports.
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(str(supervisor.socket_path))
    assert _peer_uid(sock) == os.getuid()
    sock.close()


async def test_the_gatekeeper_fails_closed_without_a_key(tmp_path: Path):
    _drop_spawn_key()  # on Windows the keychain must really be empty for this
    sup = GatekeeperSupervisor(
        _socket_path(tmp_path),
        SETTINGS,
        tmp_path / "grants.json",
        tmp_path / "audit.jsonl",
        None,
    )
    with pytest.raises(GatekeeperUnavailable):
        await sup.start()
    assert sup.started is False


def test_resolve_gatekeeper_key_fails_closed_without_keyring_or_fd(monkeypatch):
    monkeypatch.setattr(sys, "modules", {**sys.modules, "keyring": None})
    with pytest.raises(GatekeeperUnavailable):
        resolve_gatekeeper_key(None)


def test_resolve_gatekeeper_key_reads_the_keychain_when_present(monkeypatch):
    key = secrets.token_bytes(32)
    fake = types.ModuleType("keyring")
    fake.get_password = lambda service, account: key.hex()  # noqa: ARG005
    monkeypatch.setitem(sys.modules, "keyring", fake)
    assert resolve_gatekeeper_key(None) == key


def test_provision_gatekeeper_key_writes_the_keychain(monkeypatch):
    stored: dict[tuple[str, str], str] = {}
    fake = types.ModuleType("keyring")
    fake.set_password = lambda service, account, value: stored.update(  # noqa: ARG005
        {(service, account): value}
    )
    monkeypatch.setitem(sys.modules, "keyring", fake)
    gatekeeper.provision_gatekeeper_key()
    assert list(stored) == [(gatekeeper._KEYRING_SERVICE, gatekeeper._KEYRING_ACCOUNT)]
    assert (
        len(bytes.fromhex(stored[(gatekeeper._KEYRING_SERVICE, gatekeeper._KEYRING_ACCOUNT)])) == 32
    )


def test_the_pipe_name_maps_an_address_to_one_pipe():
    mapped = gatekeeper._pipe_name(Path("some/data/gatekeeper.sock"))
    assert mapped.startswith("\\\\.\\pipe\\nanomuse-gatekeeper-")
    assert gatekeeper._pipe_name("x") == gatekeeper._pipe_name("x")
    assert gatekeeper._pipe_name("x") != gatekeeper._pipe_name("y")
    assert gatekeeper._pipe_name("\\\\.\\pipe\\custom") == "\\\\.\\pipe\\custom"


def test_a_dead_gatekeeper_is_a_refusal_not_a_silent_allow(
    supervisor: GatekeeperSupervisor, client: GatekeeperClient
):
    assert client.ping() is True
    proc = supervisor._proc
    assert proc is not None
    os.kill(proc.pid, signal.SIGTERM)
    deadline = time.time() + 5
    while client.ping() and time.time() < deadline:
        time.sleep(0.05)
    assert client.ping() is False
    assessment = CallAssessment(risk=RiskLevel.SAFE, summary="read a note")
    with pytest.raises(GatekeeperUnavailable):
        client.decide("read_file", {"path": "notes.txt"}, assessment)


def test_the_ipc_round_trip_is_fast_enough_for_a_local_decision(
    supervisor: GatekeeperSupervisor, client: GatekeeperClient
):
    assessment = CallAssessment(risk=RiskLevel.SAFE, summary="read a note")
    client.decide("read_file", {"path": "warmup.txt"}, assessment)
    samples = []
    for i in range(50):
        started = time.perf_counter()
        client.decide("read_file", {"path": f"notes-{i}.txt"}, assessment)
        samples.append((time.perf_counter() - started) * 1000)
    p95 = statistics.quantiles(samples, n=20)[18]
    median = statistics.median(samples)
    print(
        f"gatekeeper IPC round trip: n={len(samples)} median={median:.2f}ms "
        f"p95={p95:.2f}ms max={max(samples):.2f}ms"
    )
    assert p95 < 20, f"p95 {p95:.2f}ms exceeds the 20ms budget: {samples}"


@pytest.mark.skipif(not _SUPPORTED, reason=_UNSUPPORTED_REASON)
async def test_the_supervisor_restarts_a_crashed_gatekeeper(tmp_path: Path):
    key = secrets.token_bytes(32)
    sup = GatekeeperSupervisor(
        _socket_path(tmp_path),
        SETTINGS,
        tmp_path / "grants.json",
        tmp_path / "audit.jsonl",
        _spawn_key(key),
    )
    await sup.start()
    assert GatekeeperClient(sup.socket_path).ping() is True
    assert sup._proc is not None
    sup._proc.terminate()
    await sup._proc.wait()
    await sup.stop()
    await sup.start()
    assert GatekeeperClient(sup.socket_path).ping() is True
    await sup.stop()
    _drop_spawn_key()


def test_gatekeeper_sentinel_front_end_matches_policy(supervisor, client):
    front = GatekeeperSentinel(SETTINGS, client)
    policy = Policy(SETTINGS)
    for tool, args, assessment, tainted in _CASES:
        decision = front.decide(tool, args, assessment, tainted=tainted)
        assert isinstance(decision, GatekeeperDecision)
        assert (
            decision.decision == policy.evaluate(tool, args, assessment, tainted=tainted).decision
        )


@pytest.mark.skipif(not _UNIX, reason="these helpers are the Unix socket ones")
def test_the_platform_helpers_find_the_platform_apis():
    assert _unix_socket_family() == socket.AF_UNIX
    assert _own_uid() == os.getuid()
    if sys.platform == "linux":
        assert _peer_cred_option() == socket.SO_PEERCRED
    else:  # darwin: SOL_LOCAL / LOCAL_PEERCRED, by name or by ABI value
        level, option = _local_peercred()
        assert level == getattr(socket, "SOL_LOCAL", 0)
        assert option == getattr(socket, "LOCAL_PEERCRED", 1)


def test_the_platform_helpers_refuse_where_the_apis_do_not_exist(monkeypatch):
    monkeypatch.delattr(socket, "AF_UNIX", raising=False)
    with pytest.raises(GatekeeperUnavailable, match="Unix domain sockets"):
        _unix_socket_family()
    monkeypatch.setattr(gatekeeper, "_PLATFORM", "linux")
    monkeypatch.delattr(socket, "SO_PEERCRED", raising=False)
    with pytest.raises(GatekeeperError, match="SO_PEERCRED"):
        _peer_cred_option()
    monkeypatch.delattr(os, "getuid", raising=False)
    with pytest.raises(GatekeeperError, match="getuid"):
        _own_uid()


def test_the_peer_credential_check_refuses_without_a_platform_api(tmp_path: Path, monkeypatch):
    server = GatekeeperServer(
        tmp_path / "g.sock",
        SETTINGS,
        tmp_path / "grants.json",
        tmp_path / "audit.jsonl",
        secrets.token_bytes(32),
    )
    one, other = socket.socketpair()
    try:
        monkeypatch.setattr(gatekeeper, "_PLATFORM", "linux")
        monkeypatch.delattr(socket, "SO_PEERCRED", raising=False)
        with pytest.raises(GatekeeperError, match="SO_PEERCRED"):
            server._peer_uid(one)
        monkeypatch.setattr(gatekeeper, "_PLATFORM", "win32")
        with pytest.raises(GatekeeperError, match="no peer credential API"):
            server._peer_uid(one)
    finally:
        one.close()
        other.close()


@pytest.mark.skipif(not _UNIX, reason="the Windows client fails closed on the pipe instead")
def test_the_client_fails_closed_without_unix_sockets(tmp_path: Path, monkeypatch):
    def _no_unix_family() -> int:
        raise GatekeeperUnavailable("Unix domain sockets are unavailable on this platform")

    monkeypatch.setattr(gatekeeper, "_unix_socket_family", _no_unix_family)
    with pytest.raises(GatekeeperUnavailable, match="Unix domain sockets"):
        GatekeeperClient(tmp_path / "g.sock")._call({"id": "ping", "op": "ping"})
