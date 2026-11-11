"""Grant configuration fingerprints: a standing permission is bound to the
approval policy it was given under, not just to a tool and a target.

Everything runs on temporary files and settings objects; no network, no
real model. The Sentinel-level test mirrors the helpers in
tests/test_sentinel.py so the ask counting reads the same way there.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from nanomuse.config import SentinelRule, SentinelSettings
from nanomuse.schema import Function, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.sentinel.grants import GrantStore, policy_fingerprint
from nanomuse.tools.base import BaseTool
from nanomuse.ui import ApprovalDecision, ApprovalRequest, HeadlessUI


def call(name: str, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


class Echo(BaseTool):
    name: str = "echo"
    description: str = "echo"
    parameters: dict[str, Any] = {"type": "object", "properties": {"text": {"type": "string"}}}

    async def execute(self, text: str = "", **_: Any) -> ToolResult:
        return ToolResult(output=f"echo: {text}")


class ScopedUI(HeadlessUI):
    """Approves with a chosen scope and keeps the requests for inspection."""

    def __init__(self, scope: str = "once", approve: bool = True):
        super().__init__(approve=approve)
        self.scope = scope
        self.requests: list[ApprovalRequest] = []

    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        self._log("approval", request.summary)
        return ApprovalDecision(approved=self.approve, scope=self.scope)  # type: ignore[arg-type]


def asks(ui: HeadlessUI) -> int:
    return len([e for e in ui.events if e[0] == "approval"])


class LivePolicy:
    """A settings holder whose fingerprint provider reads the current settings,
    the way the Sentinel's provider reads its (mutable) settings object."""

    def __init__(self, settings: SentinelSettings | None = None):
        self.settings = settings if settings is not None else SentinelSettings()

    def provider(self) -> str:
        return policy_fingerprint(self.settings)


# ----------------------------------------------------------------------------- the fingerprint


def test_the_same_configuration_fingerprints_the_same():
    assert policy_fingerprint(SentinelSettings()) == policy_fingerprint(SentinelSettings())
    fingerprint = policy_fingerprint(SentinelSettings())
    assert len(fingerprint) == 64 and all(c in "0123456789abcdef" for c in fingerprint)


def test_every_policy_field_moves_the_fingerprint():
    base = policy_fingerprint(SentinelSettings())
    changed = [
        SentinelSettings(mode="strict"),
        SentinelSettings(always_ask_tools=["send_email"]),
        SentinelSettings(always_allow_tools=["echo"]),
        SentinelSettings(deny_tools=["echo"]),
        SentinelSettings(egress_allowlist=["example.com"]),
        SentinelSettings(rules=[SentinelRule(tool="shell", action="deny")]),
        SentinelSettings(taint_tracking=False),
    ]
    for settings in changed:
        assert policy_fingerprint(settings) != base, settings


def test_the_order_of_the_set_like_lists_does_not_move_the_fingerprint():
    one = SentinelSettings(
        always_ask_tools=["a_tool", "b_tool"],
        always_allow_tools=["c_tool", "d_tool"],
        deny_tools=["e_tool", "f_tool"],
        egress_allowlist=["a.example", "b.example"],
    )
    other = SentinelSettings(
        always_ask_tools=["b_tool", "a_tool"],
        always_allow_tools=["d_tool", "c_tool"],
        deny_tools=["f_tool", "e_tool"],
        egress_allowlist=["b.example", "a.example"],
    )
    assert policy_fingerprint(one) == policy_fingerprint(other)


def test_the_order_of_rules_moves_the_fingerprint():
    # The configuration reference says the first matching rule wins, so the
    # order of the rules is part of the policy they were granted under.
    allow_first = SentinelRule(tool="shell", action="allow")
    deny_rm = SentinelRule(tool="shell", match={"command": "*rm*"}, action="deny")
    assert policy_fingerprint(SentinelSettings(rules=[allow_first, deny_rm])) != policy_fingerprint(
        SentinelSettings(rules=[deny_rm, allow_first])
    )


def test_non_policy_fields_do_not_move_the_fingerprint(tmp_path: Path):
    plain = SentinelSettings()
    moved = SentinelSettings(
        audit_file=tmp_path / "audit.jsonl",
        gatekeeper=True,
        gatekeeper_socket=tmp_path / "gatekeeper.sock",
    )
    assert policy_fingerprint(plain) == policy_fingerprint(moved)


# ----------------------------------------------------------------------------- the store


def test_a_bound_store_stamps_grants_and_honours_them_under_the_same_policy():
    policy = LivePolicy()
    store = GrantStore(fingerprint=policy.provider)
    grant = store.add("web_fetch", "example.com", "always")
    assert grant is not None
    assert grant.config_fingerprint == policy_fingerprint(SentinelSettings())
    assert store.match("web_fetch:example.com") is not None
    assert [g.key for g in store.active()] == ["web_fetch:example.com"]


def test_a_configuration_change_pauses_a_grant_and_changing_back_revives_it():
    policy = LivePolicy()
    store = GrantStore(fingerprint=policy.provider)
    store.add("web_fetch", "example.com", "always")
    policy.settings = SentinelSettings(mode="strict")
    assert store.match("web_fetch:example.com") is None
    assert store.active() == [], "a paused grant is not listed either"
    policy.settings = SentinelSettings()
    assert store.match("web_fetch:example.com") is not None, "skipped, not deleted: it revives"
    assert [g.key for g in store.active()] == ["web_fetch:example.com"]


def test_the_stamp_is_persisted_and_judged_on_reload(tmp_path: Path):
    path = tmp_path / "approvals.json"
    GrantStore(path, fingerprint=lambda: policy_fingerprint(SentinelSettings())).add(
        "echo", None, "always"
    )
    data = json.loads(path.read_text("utf-8"))
    assert data["grants"][0]["config_fingerprint"] == policy_fingerprint(SentinelSettings())
    same = GrantStore(path, fingerprint=lambda: policy_fingerprint(SentinelSettings()))
    assert same.match("echo") is not None
    changed = GrantStore(
        path, fingerprint=lambda: policy_fingerprint(SentinelSettings(mode="strict"))
    )
    assert changed.match("echo") is None


def test_a_v2_file_without_stamps_is_not_honoured_by_a_bound_store(tmp_path: Path):
    # A grants file written before the binding existed: same v2 shape, no stamp.
    path = tmp_path / "approvals.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "grants": [
                    {
                        "key": "echo",
                        "tool": "echo",
                        "target": None,
                        "scope": "always",
                        "granted_at": time.time(),
                        "expires_at": None,
                    }
                ],
            }
        ),
        "utf-8",
    )
    bound = GrantStore(path, fingerprint=lambda: policy_fingerprint(SentinelSettings()))
    assert bound.match("echo") is None, "an unstamped grant has to be given once more"
    assert bound.active() == []
    bare = GrantStore(path)
    assert bare.match("echo") is not None, "a store with no provider behaves as before"


def test_a_v1_file_is_not_honoured_by_a_bound_store(tmp_path: Path):
    path = tmp_path / "approvals.json"
    path.write_text(json.dumps(["echo"]), "utf-8")
    bound = GrantStore(path, fingerprint=lambda: policy_fingerprint(SentinelSettings()))
    assert bound.match("echo") is None
    bare = GrantStore(path)
    assert bare.match("echo") is not None


def test_a_store_without_a_provider_stamps_nothing_and_honours_as_before():
    store = GrantStore()
    grant = store.add("echo", None, "session")
    assert grant is not None and grant.config_fingerprint is None
    assert store.match("echo") is not None
    assert [g.key for g in store.active()] == ["echo"]


# ----------------------------------------------------------------------------- the Sentinel


async def test_a_persisted_grant_stops_covering_when_the_configuration_changes(tmp_path: Path):
    path = tmp_path / "approvals.json"
    settings = SentinelSettings(always_ask_tools=["echo"])
    ui = ScopedUI(scope="always")
    gate = Sentinel(settings, AuditLog(tmp_path / "a.jsonl"), ui, persistent_approvals_file=path)
    await gate.guard(call("echo", text="1"), Echo())
    assert asks(ui) == 1
    (grant,) = gate.grants.active()
    assert grant.config_fingerprint == policy_fingerprint(settings), "the provider is wired in"

    # Only the mode changed: the standing permission no longer settles the
    # call, so the person is asked again (and answers for this once only).
    ui_changed = ScopedUI(scope="once")
    changed = Sentinel(
        SentinelSettings(always_ask_tools=["echo"], mode="strict"),
        AuditLog(tmp_path / "b.jsonl"),
        ui_changed,
        persistent_approvals_file=path,
    )
    await changed.guard(call("echo", text="2"), Echo())
    assert asks(ui_changed) == 1, "the configuration changed, so it asks again"

    # The configuration is back to what the grant was given under: the grant
    # was paused, not deleted, and it covers the call again.
    ui_back = ScopedUI(scope="once")
    back = Sentinel(
        settings, AuditLog(tmp_path / "c.jsonl"), ui_back, persistent_approvals_file=path
    )
    await back.guard(call("echo", text="3"), Echo())
    assert asks(ui_back) == 0, "the original configuration revives the grant"
