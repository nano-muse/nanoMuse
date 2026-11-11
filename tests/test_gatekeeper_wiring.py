"""The gatekeeper wired into the real guard: [sentinel] gatekeeper on means
every guard() call is consulted, its veto is final, its permissions settle,
approvals are mirrored to it, and a dead gatekeeper refuses calls."""

from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

import pytest

from nanomuse.config import SentinelRule, SentinelSettings, Settings
from nanomuse.schema import RiskLevel
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.sentinel.gatekeeper import GatekeeperClient, GatekeeperSupervisor
from nanomuse.sentinel.grants import GrantStore, policy_fingerprint
from nanomuse.tools.base import CallAssessment
from nanomuse.ui import ApprovalDecision, ApprovalRequest, HeadlessUI
from tests.test_gatekeeper import _drop_spawn_key, _spawn_key
from tests.test_sentinel import Echo, call

_SUPPORTED = sys.platform in ("linux", "darwin", "win32")
pytestmark = pytest.mark.skipif(not _SUPPORTED, reason="the gatekeeper serves Linux and macOS only")


def _socket_path(tmp_path: Path) -> Path:
    path = tmp_path / "gk.sock"
    if len(str(path)) > 100:  # Darwin's socket path limit
        import os

        return Path("/tmp") / f"nanomuse-gk-wiring-{os.getpid()}.sock"
    return path


class ScopedUI(HeadlessUI):
    """Approves (or not) with a chosen scope, mirroring test_sentinel's."""

    def __init__(self, scope: str = "once", approve: bool = True):
        super().__init__(approve=approve)
        self.scope = scope

    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self._log("approval", request.summary)
        return ApprovalDecision(approved=self.approve, scope=self.scope)  # type: ignore[arg-type]


async def _started(tmp_path: Path, gk_settings: SentinelSettings) -> GatekeeperSupervisor:
    sup = GatekeeperSupervisor(
        _socket_path(tmp_path),
        gk_settings,
        tmp_path / "approvals.json",
        tmp_path / "gatekeeper-audit.jsonl",
        _spawn_key(secrets.token_bytes(32)),
    )
    await sup.start()
    return sup


def _gate(
    tmp_path: Path,
    sup: GatekeeperSupervisor,
    settings: SentinelSettings,
    ui: HeadlessUI,
) -> Sentinel:
    return Sentinel(
        settings,
        AuditLog(tmp_path / "audit.jsonl"),
        ui,
        gatekeeper=GatekeeperClient(sup.socket_path),
    )


def test_gatekeeper_is_off_by_default():
    assert SentinelSettings().gatekeeper is False
    assert SentinelSettings().gatekeeper_socket is None


async def test_guard_consults_the_gatekeeper(tmp_path: Path):
    sup = await _started(tmp_path, SentinelSettings())
    try:
        gate = _gate(tmp_path, sup, SentinelSettings(), HeadlessUI())
        result = await gate.guard(call("echo", text="hi"), Echo())
        assert result.ok
        entries = (tmp_path / "gatekeeper-audit.jsonl").read_text("utf-8").strip().splitlines()
        assert entries, "the gatekeeper signed a decision for the call"
        assert json.loads(entries[-1])["tool"] == "echo"
    finally:
        await sup.stop()
        _drop_spawn_key()


async def test_gatekeeper_veto_is_final(tmp_path: Path):
    gk_settings = SentinelSettings(
        rules=[SentinelRule(tool="echo", action="deny", reason="the keeper says no")]
    )
    sup = await _started(tmp_path, gk_settings)
    try:
        # The local policy would let a SAFE call straight through; the veto stands.
        gate = _gate(tmp_path, sup, SentinelSettings(), HeadlessUI())
        result = await gate.guard(call("echo", text="hi"), Echo())
        assert not result.ok
        assert "the keeper says no" in (result.error or "")
    finally:
        await sup.stop()
        _drop_spawn_key()


async def test_gatekeeper_permission_settles_a_local_ask(tmp_path: Path):
    # A standing permission recorded in the gatekeeper's store before it started.
    # Both sides share the settings in production (the app hands the supervisor
    # the same [sentinel] section), so its policy asks too, and its permission
    # is what settles. The seed is stamped with those settings' fingerprint,
    # the way the gatekeeper's own store stamps what it records: a grant
    # stamped under another configuration, or by an older version that
    # stamped nothing, would not be honoured.
    keeper_settings = SentinelSettings(always_ask_tools=["echo"])
    GrantStore(
        tmp_path / "approvals.json", fingerprint=lambda: policy_fingerprint(keeper_settings)
    ).add("echo", None, "always", None)
    sup = await _started(tmp_path, keeper_settings)
    try:
        ui = ScopedUI(approve=False)  # a prompt would deny the call outright
        gate = _gate(tmp_path, sup, SentinelSettings(always_ask_tools=["echo"]), ui)
        result = await gate.guard(call("echo", text="hi"), Echo())
        assert result.ok, "the gatekeeper's permission settled the call"
        assert not [e for e in ui.events if e[0] == "approval"], "nobody was asked"
    finally:
        await sup.stop()
        _drop_spawn_key()


async def test_approval_is_mirrored_to_the_gatekeeper(tmp_path: Path):
    sup = await _started(tmp_path, SentinelSettings())
    try:
        ui = ScopedUI(scope="always")
        gate = _gate(tmp_path, sup, SentinelSettings(always_ask_tools=["echo"]), ui)
        result = await gate.guard(call("echo", text="hi"), Echo())
        assert result.ok
        client = GatekeeperClient(sup.socket_path)
        decision = client.decide(
            "echo",
            {"text": "again"},
            CallAssessment(risk=RiskLevel.SENSITIVE, summary="echo"),
        )
        assert decision.grant_scope == "always", "the gatekeeper can settle on it now"
        assert client.grant("echo", None, "once") is False, "a one-off stores nothing"
    finally:
        await sup.stop()
        _drop_spawn_key()


async def test_dead_gatekeeper_refuses_calls(tmp_path: Path):
    sup = await _started(tmp_path, SentinelSettings())
    gate = _gate(tmp_path, sup, SentinelSettings(), HeadlessUI())
    await sup.stop()
    _drop_spawn_key()
    result = await gate.guard(call("echo", text="hi"), Echo())
    assert not result.ok
    assert "gatekeeper is unavailable" in (result.error or "")


def _app(tmp_path: Path):
    import os

    from nanomuse.app import NanoMuseApp
    from nanomuse.llm import MockLLM

    # An explicit short socket path: pytest's own directories run past
    # Darwin's socket path limit, which is what gatekeeper_socket is for.
    settings = Settings(
        data_dir=tmp_path,
        sentinel=SentinelSettings(
            gatekeeper=True,
            gatekeeper_socket=Path("/tmp") / f"nanomuse-gk-app-{os.getpid()}.sock",
        ),
    )
    return NanoMuseApp(settings, HeadlessUI(), llm=MockLLM([]))


async def test_app_starts_and_stops_its_gatekeeper(tmp_path: Path):
    app = _app(tmp_path)
    try:
        assert app.sentinel.gatekeeper is not None
        assert app._gatekeeper_supervisor is not None
        # Production spawns read the key from the OS keychain; the test hands
        # the supervisor key material the way the prototype's tests do, or
        # provisions the keychain on Windows, where that is the only way in.
        if sys.platform == "win32":
            _spawn_key(secrets.token_bytes(32))
        else:
            app._gatekeeper_supervisor.key_material = secrets.token_bytes(32)
        await app.start()
        assert app.sentinel.gatekeeper.ping()
        await app.close()
        assert not app.sentinel.gatekeeper.ping()
    finally:
        sup = app._gatekeeper_supervisor
        if sup is not None and sup.started:
            await sup.stop()
        _drop_spawn_key()


async def test_app_without_a_key_refuses_to_start(tmp_path: Path):
    from nanomuse.sentinel.gatekeeper import GatekeeperUnavailable

    _drop_spawn_key()  # the keychain must really be empty for this
    app = _app(tmp_path)
    # No key in this environment's keychain and none handed over: the child
    # refuses, and the app fails closed instead of running ungated.
    with pytest.raises(GatekeeperUnavailable):
        await app.start()
