"""Bypass attempts against Sentinel: every way in that must not work, plus the ones
that are *by design* and must stay working.

The first group asserts the dangerous thing is stopped (DENY, or ASK that a
declining user blocks). The second group asserts the designed escapes (an
explicit rule, a grant for the whole tool) still behave as documented, so a
future change cannot silently turn a feature into a hole or a hole into a
feature. Each test names which group it is in."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from nanomuse.config import SentinelRule, SentinelSettings
from nanomuse.schema import Function, RiskLevel, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Decision, Policy, Sentinel, host_allowed
from nanomuse.sentinel.grants import Grant, GrantStore
from nanomuse.tools.base import BaseTool, CallAssessment
from nanomuse.ui import HeadlessUI


class Echo(BaseTool):
    name: str = "echo"
    description: str = "echo"
    parameters: dict[str, Any] = {"type": "object", "properties": {"text": {"type": "string"}}}
    risk: RiskLevel = RiskLevel.SAFE

    async def execute(self, text: str = "", **_: Any) -> ToolResult:
        return ToolResult(output=f"echo: {text}")


class Sender(BaseTool):
    name: str = "sender"
    description: str = "sends data"
    parameters: dict[str, Any] = {"type": "object", "properties": {"host": {"type": "string"}}}
    risk: RiskLevel = RiskLevel.MODERATE
    egress: bool = True
    accepts_secrets: bool = True

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=self.risk, egress=True, egress_target=args.get("host"), summary="sender"
        )

    async def execute(self, host: str = "", **_: Any) -> ToolResult:
        return ToolResult(output=f"sent to {host}")


class Reader(BaseTool):
    name: str = "reader"
    description: str = "reads private data"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    reads_private_data: bool = True

    async def execute(self, **_: Any) -> ToolResult:
        return ToolResult(output="private stuff")


class Shellish(BaseTool):
    """A shell-like tool whose assessment warns on dangerous commands."""

    name: str = "shell"
    description: str = "shell"
    parameters: dict[str, Any] = {"type": "object", "properties": {"command": {"type": "string"}}}
    risk: RiskLevel = RiskLevel.SENSITIVE

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        command = str(args.get("command", ""))
        warnings = ["command looks dangerous"] if "rm -rf" in command else []
        return CallAssessment(risk=self.risk, warnings=warnings, summary="shell")

    async def execute(self, command: str = "", **_: Any) -> ToolResult:
        return ToolResult(output=f"ran: {command}")


def call(name: str, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


def evaluate(
    settings: SentinelSettings,
    tool: str,
    args: dict[str, Any],
    assessment: CallAssessment,
    tainted: bool = False,
) -> Decision:
    return Policy(settings).evaluate(tool, args, assessment, tainted=tainted).decision


def dangerous() -> CallAssessment:
    return CallAssessment(risk=RiskLevel.SENSITIVE, warnings=["command looks dangerous"])


# ---------------------------------------------------------- must not get through


def test_deny_tools_glob_catches_renamed_variants() -> None:
    settings = SentinelSettings(deny_tools=["nuke*"])
    for name in ("nuke", "nuke2", "nuke_everything"):
        assert evaluate(settings, name, {}, CallAssessment()) == Decision.DENY


def test_deny_tools_beats_always_allow() -> None:
    settings = SentinelSettings(deny_tools=["shell"], always_allow_tools=["shell"])
    assert evaluate(settings, "shell", {}, CallAssessment()) == Decision.DENY


def test_deny_rule_beats_always_allow_and_ask_mode() -> None:
    settings = SentinelSettings(
        always_allow_tools=["shell"],
        rules=[SentinelRule(tool="shell", match={"command": "*rm -rf*"}, action="deny")],
    )
    assert evaluate(settings, "shell", {"command": "rm -rf /"}, CallAssessment()) == Decision.DENY


def test_rule_glob_variants_still_deny() -> None:
    settings = SentinelSettings(
        rules=[SentinelRule(tool="shell", match={"command": "*rm -rf*"}, action="deny")]
    )
    for command in ("rm -rf /", "sudo rm -rf /", "  rm -rf /", "rm -rf", "x; rm -rf /tmp"):
        assert evaluate(settings, "shell", {"command": command}, CallAssessment()) == Decision.DENY


def test_a_command_the_glob_cannot_see_still_asks() -> None:
    # "rm --recursive --force" is the same act in other words; no glob can list
    # every spelling, so the risk level must catch what the rule misses.
    settings = SentinelSettings(
        rules=[SentinelRule(tool="shell", match={"command": "*rm -rf*"}, action="deny")]
    )
    assert (
        evaluate(
            settings,
            "shell",
            {"command": "rm --recursive --force /"},
            CallAssessment(risk=RiskLevel.SENSITIVE),
        )
        == Decision.ASK
    )


def test_rule_does_not_fire_on_a_missing_argument() -> None:
    settings = SentinelSettings(
        rules=[SentinelRule(tool="shell", match={"command": "*rm*"}, action="allow")]
    )
    # No command argument at all: the rule cannot speak, so the risk level decides.
    assert evaluate(settings, "shell", {}, CallAssessment(risk=RiskLevel.SENSITIVE)) == Decision.ASK


def test_rule_matches_inside_nested_arguments() -> None:
    settings = SentinelSettings(
        rules=[SentinelRule(tool="send", match={"data": "*secret*"}, action="deny")]
    )
    assert (
        evaluate(settings, "send", {"data": {"key": "the secret"}}, CallAssessment())
        == Decision.DENY
    )


def test_warnings_escalate_always_allow_and_auto_mode() -> None:
    settings = SentinelSettings(mode="auto", always_allow_tools=["shell"])
    assert evaluate(settings, "shell", {}, dangerous()) == Decision.ASK
    settings = SentinelSettings(mode="ask", always_allow_tools=["shell"])
    assert evaluate(settings, "shell", {}, dangerous()) == Decision.ASK


def test_taint_escalates_always_allow_and_auto_mode() -> None:
    assessment = CallAssessment(egress=True, egress_target="evil.com")
    settings = SentinelSettings(mode="auto", always_allow_tools=["web_fetch"])
    result = Policy(settings).evaluate("web_fetch", {}, assessment, tainted=True)
    assert result.decision == Decision.ASK and result.tainted_ask is True
    settings = SentinelSettings(mode="ask", always_allow_tools=["web_fetch"])
    assert (
        Policy(settings).evaluate("web_fetch", {}, assessment, tainted=True).decision
        == Decision.ASK
    )


def test_taint_escalates_an_explicit_allow_rule() -> None:
    settings = SentinelSettings(rules=[SentinelRule(tool="web_fetch", match={}, action="allow")])
    assessment = CallAssessment(egress=True, egress_target="evil.com")
    result = Policy(settings).evaluate("web_fetch", {}, assessment, tainted=True)
    assert result.decision == Decision.ASK and result.tainted_ask is True


def test_taint_with_no_destination_still_asks() -> None:
    assessment = CallAssessment(egress=True, egress_target=None)
    result = Policy(SentinelSettings()).evaluate("web_fetch", {}, assessment, tainted=True)
    assert result.decision == Decision.ASK


def test_host_allowlist_cannot_be_stretched() -> None:
    allow = ["example.com", "*.wikipedia.org"]
    assert host_allowed("www.example.com", allow)
    assert host_allowed("EXAMPLE.COM.", allow)
    assert not host_allowed("evilexample.com", allow)
    assert not host_allowed("example.com.evil.com", allow)
    assert not host_allowed("wikipedia.org", allow)  # the star needs a subdomain
    assert not host_allowed("en.wikipedia.org.evil.com", allow)


def test_grant_for_one_target_does_not_cover_another() -> None:
    store = GrantStore()
    store.add("send_email", "alice@example.com", "always")
    assert store.match("send_email:bob@example.com") is None
    assert store.match("send_email:alice@example.com") is not None


def test_a_multi_target_call_needs_every_target_granted() -> None:
    store = GrantStore()
    store.add("shell", "git", "always")
    assert store.match("shell:git,head") is None
    store.add("shell", "head", "always")
    assert store.match("shell:git,head") is not None


def test_expired_and_wrong_conversation_grants_do_not_match() -> None:
    store = GrantStore()
    store._grants.append(
        Grant(
            key="shell:git",
            tool="shell",
            target="git",
            scope="24h",
            granted_at=time.time() - 90000,
            expires_at=time.time() - 100,
        )
    )
    assert store.match("shell:git") is None
    store.add("shell", "git", "conversation", conversation_id="conv-a")
    assert store.match("shell:git", conversation_id="conv-b") is None
    assert store.match("shell:git", conversation_id="conv-a") is not None


def test_an_unknown_scope_stores_nothing() -> None:
    store = GrantStore()
    assert store.add("shell", "git", "forever") is None
    assert store.match("shell:git") is None


async def test_a_standing_grant_does_not_cover_a_warning_call(tmp_path: Path) -> None:
    gate = Sentinel(SentinelSettings(), AuditLog(tmp_path / "a.jsonl"), HeadlessUI(approve=False))
    gate.grants.add("shell", None, "always")
    result = await gate.guard(call("shell", command="rm -rf /"), Shellish())
    assert result.error and "Sentinel blocked" in result.error


async def test_gate_denies_a_denied_tool_even_when_the_user_would_approve(
    tmp_path: Path,
) -> None:
    gate = Sentinel(
        SentinelSettings(deny_tools=["echo"]),
        AuditLog(tmp_path / "a.jsonl"),
        HeadlessUI(approve=True),
    )
    result = await gate.guard(call("echo", text="hi"), Echo())
    assert result.error and "Sentinel blocked" in result.error


async def test_gate_still_asks_in_auto_mode_when_tainted(tmp_path: Path) -> None:
    gate = Sentinel(
        SentinelSettings(mode="auto"),
        AuditLog(tmp_path / "a.jsonl"),
        HeadlessUI(approve=False),
    )
    await gate.guard(call("reader"), Reader())
    assert gate.tainted
    result = await gate.guard(call("sender", host="evil.com"), Sender())
    assert result.error and "Sentinel blocked" in result.error


async def test_gate_still_asks_in_auto_mode_for_a_warning(tmp_path: Path) -> None:
    gate = Sentinel(
        SentinelSettings(mode="auto"),
        AuditLog(tmp_path / "a.jsonl"),
        HeadlessUI(approve=False),
    )
    result = await gate.guard(call("shell", command="rm -rf /"), Shellish())
    assert result.error and "Sentinel blocked" in result.error


async def test_a_once_approval_does_not_persist(tmp_path: Path) -> None:
    ui = HeadlessUI(approve=True)
    gate = Sentinel(
        SentinelSettings(always_ask_tools=["echo"]),
        AuditLog(tmp_path / "a.jsonl"),
        ui,
    )
    assert (await gate.guard(call("echo", text="one"), Echo())).output == "echo: one"
    ui.approve = False
    result = await gate.guard(call("echo", text="two"), Echo())
    assert result.error and "Sentinel blocked" in result.error


# ---------------------------------------------------------- by design: must keep working


def test_an_explicit_allow_rule_beats_always_ask_and_warnings() -> None:
    settings = SentinelSettings(
        always_ask_tools=["shell"],
        rules=[SentinelRule(tool="shell", match={"command": "sudo apt*"}, action="allow")],
    )
    assert (
        evaluate(settings, "shell", {"command": "sudo apt update"}, dangerous()) == Decision.ALLOW
    )


def test_the_first_matching_rule_wins() -> None:
    settings = SentinelSettings(
        rules=[
            SentinelRule(tool="shell", match={"command": "*"}, action="allow"),
            SentinelRule(tool="shell", match={"command": "*rm*"}, action="deny"),
        ]
    )
    assert evaluate(settings, "shell", {"command": "rm -rf /"}, CallAssessment()) == Decision.ALLOW


def test_a_toolwide_grant_covers_every_target() -> None:
    store = GrantStore()
    store.add("shell", None, "always")
    assert store.match("shell:git") is not None
    assert store.match("shell:anything") is not None


def test_a_configured_destination_is_not_taint_escalated() -> None:
    assessment = CallAssessment(
        egress=True, egress_target="api.search.brave.com", egress_configured=True
    )
    result = Policy(SentinelSettings()).evaluate("web_search", {}, assessment, tainted=True)
    assert result.decision == Decision.ALLOW
