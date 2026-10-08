from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from nanomuse.config import SentinelRule, SentinelSettings
from nanomuse.schema import Function, RiskLevel, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Decision, Policy, Sentinel, host_allowed
from nanomuse.sentinel import grants as grants_module
from nanomuse.sentinel.grants import GrantStore
from nanomuse.tools.base import BaseTool, CallAssessment
from nanomuse.tools.shell import programs_of
from nanomuse.ui import ApprovalDecision, ApprovalRequest, HeadlessUI
from nanomuse.vault import CredentialVault


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

    async def execute(self, host: str = "", token: str = "", **_: Any) -> ToolResult:
        return ToolResult(output=f"sent to {host} with {token}")


class Reader(BaseTool):
    name: str = "reader"
    description: str = "reads private data"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    reads_private_data: bool = True

    async def execute(self, **_: Any) -> ToolResult:
        return ToolResult(output="private stuff")


def call(name: str, **args: Any) -> ToolCall:
    import json

    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


# ----------------------------------------------------------------------------- policy
def test_host_allowed():
    allow = ["duckduckgo.com", "*.wikipedia.org"]
    assert host_allowed("duckduckgo.com", allow)
    assert host_allowed("html.duckduckgo.com", allow)
    assert host_allowed("en.wikipedia.org", allow)
    assert not host_allowed("wikipedia.org", allow)  # pattern requires a subdomain
    assert not host_allowed("evil.com", allow)
    assert not host_allowed(None, allow)
    assert host_allowed("anything", ["*"])


@pytest.mark.parametrize(
    ("mode", "risk", "expected"),
    [
        ("ask", RiskLevel.SAFE, Decision.ALLOW),
        ("ask", RiskLevel.MODERATE, Decision.ALLOW),
        ("ask", RiskLevel.SENSITIVE, Decision.ASK),
        ("strict", RiskLevel.MODERATE, Decision.ASK),
        ("strict", RiskLevel.SAFE, Decision.ALLOW),
        ("auto", RiskLevel.SENSITIVE, Decision.ALLOW),
    ],
)
def test_risk_mode_matrix(mode: str, risk: RiskLevel, expected: Decision):
    policy = Policy(SentinelSettings(mode=mode, always_ask_tools=[]))
    result = policy.evaluate("x", {}, CallAssessment(risk=risk))
    assert result.decision == expected


def test_rules_and_overrides():
    settings = SentinelSettings(
        deny_tools=["nuke"],
        always_allow_tools=["python_*"],
        rules=[
            SentinelRule(tool="shell", match={"command": "*rm -rf*"}, action="deny", reason="no")
        ],
    )
    policy = Policy(settings)
    assert policy.evaluate("nuke", {}, CallAssessment()).decision == Decision.DENY
    assert (
        policy.evaluate(
            "shell", {"command": "rm -rf /"}, CallAssessment(risk=RiskLevel.SENSITIVE)
        ).decision
        == Decision.DENY
    )
    assert (
        policy.evaluate(
            "shell", {"command": "ls"}, CallAssessment(risk=RiskLevel.SENSITIVE)
        ).decision
        == Decision.ASK
    )
    assert (
        policy.evaluate("python_execute", {}, CallAssessment(risk=RiskLevel.SENSITIVE)).decision
        == Decision.ALLOW
    )


def test_warnings_escalate_even_in_auto_mode_unless_a_rule_allows():
    dangerous = CallAssessment(risk=RiskLevel.SENSITIVE, warnings=["command looks dangerous: sudo"])
    # hands-off mode still stops for a dangerous call…
    auto = Policy(SentinelSettings(mode="auto"))
    result = auto.evaluate("shell", {"command": "sudo ls"}, dangerous)
    assert result.decision == Decision.ASK and "sudo" in result.reasons[-1]
    # …and so does always_allow_tools
    allowed = Policy(SentinelSettings(mode="ask", always_allow_tools=["shell"]))
    assert allowed.evaluate("shell", {"command": "sudo ls"}, dangerous).decision == Decision.ASK
    assert (
        allowed.evaluate(
            "shell", {"command": "ls"}, CallAssessment(risk=RiskLevel.SENSITIVE)
        ).decision
        == Decision.ALLOW
    )
    # only an explicit rule speaks for the user here
    ruled = Policy(
        SentinelSettings(
            mode="auto",
            rules=[SentinelRule(tool="shell", match={"command": "sudo apt*"}, action="allow")],
        )
    )
    assert (
        ruled.evaluate("shell", {"command": "sudo apt update"}, dangerous).decision
        == Decision.ALLOW
    )


def test_taint_escalates_egress():
    policy = Policy(SentinelSettings(egress_allowlist=["*.wikipedia.org"]))
    clean = policy.evaluate(
        "web_fetch", {}, CallAssessment(egress=True, egress_target="evil.com"), tainted=False
    )
    assert clean.decision == Decision.ALLOW
    tainted = policy.evaluate(
        "web_fetch", {}, CallAssessment(egress=True, egress_target="evil.com"), tainted=True
    )
    assert tainted.decision == Decision.ASK
    ok = policy.evaluate(
        "web_fetch", {}, CallAssessment(egress=True, egress_target="en.wikipedia.org"), tainted=True
    )
    assert ok.decision == Decision.ALLOW
    unknown = policy.evaluate(
        "shell", {}, CallAssessment(risk=RiskLevel.SAFE, egress=True), tainted=True
    )
    assert unknown.decision == Decision.ASK
    # a destination the owner set in the settings (the search provider) is not one the model
    # picked: it counts like the allowlist
    configured = policy.evaluate(
        "web_search",
        {},
        CallAssessment(egress=True, egress_target="api.search.brave.com", egress_configured=True),
        tainted=True,
    )
    assert configured.decision == Decision.ALLOW


# ----------------------------------------------------------------------------- gate
async def test_gate_allows_safe_and_audits(tmp_path: Path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    gate = Sentinel(SentinelSettings(), audit, HeadlessUI())
    result = await gate.guard(call("echo", text="hi"), Echo())
    assert result.output == "echo: hi"
    entries = audit.tail()
    assert entries[-1]["event"] == "tool_call" and entries[-1]["decision"] == "allow"
    # every tool call names its rung, so the Activity view can count the screen steps
    assert entries[-1]["channel"] == "local"


async def test_gate_denies_when_user_declines(tmp_path: Path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    gate = Sentinel(SentinelSettings(always_ask_tools=["echo"]), audit, HeadlessUI(approve=False))
    result = await gate.guard(call("echo", text="hi"), Echo())
    assert result.error and "Sentinel blocked" in result.error
    assert audit.tail()[-1]["decision"] == "deny" and audit.tail()[-1]["channel"] == "local"


async def test_gate_does_not_ask_about_arguments_that_never_parsed(tmp_path: Path):
    ui = HeadlessUI(approve=True)
    gate = Sentinel(SentinelSettings(always_ask_tools=["echo"]), AuditLog(tmp_path / "a.jsonl"), ui)
    cut_off = ToolCall(
        function=Function(name="echo", arguments='{"text": "a long page' + "x" * 1200)
    )
    result = await gate.guard(cut_off, Echo())
    assert result.error and "not valid JSON" in result.error and "cut off" in result.error
    assert not [e for e in ui.events if e[0] == "approval"], "nothing to approve: it cannot run"


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


async def test_gate_session_grant_covers_later_calls(tmp_path: Path):
    ui = ScopedUI(scope="session")
    gate = Sentinel(SentinelSettings(always_ask_tools=["echo"]), AuditLog(tmp_path / "a.jsonl"), ui)
    await gate.guard(call("echo", text="1"), Echo())
    assert asks(ui) == 1
    await gate.guard(call("echo", text="2"), Echo())
    assert asks(ui) == 1, "the session grant covers the second call"
    assert [g.key for g in gate.active_grants()] == ["echo"]
    assert gate.revoke("echo")
    await gate.guard(call("echo", text="3"), Echo())
    assert asks(ui) == 2, "revoked: asks again"


async def test_gate_grant_is_bound_to_target(tmp_path: Path):
    ui = ScopedUI(scope="always")
    gate = Sentinel(
        SentinelSettings(always_ask_tools=["sender"]),
        AuditLog(tmp_path / "a.jsonl"),
        ui,
        persistent_approvals_file=tmp_path / "approvals.json",
    )
    await gate.guard(call("sender", host="a.example"), Sender())
    assert ui.requests[-1].grant_key == "sender:a.example"
    assert "always" in ui.requests[-1].grant_options
    await gate.guard(call("sender", host="a.example"), Sender())
    assert asks(ui) == 1
    await gate.guard(call("sender", host="b.example"), Sender())
    assert asks(ui) == 2, "a different destination is a different capability"
    # "always" survives a restart
    again = Sentinel(
        SentinelSettings(always_ask_tools=["sender"]),
        AuditLog(tmp_path / "a.jsonl"),
        ScopedUI(),
        persistent_approvals_file=tmp_path / "approvals.json",
    )
    assert {g.key for g in again.active_grants()} == {"sender:a.example", "sender:b.example"}


async def test_gate_conversation_grant_lasts_the_conversation(tmp_path: Path):
    ui = ScopedUI(scope="conversation")
    gate = Sentinel(SentinelSettings(always_ask_tools=["echo"]), AuditLog(tmp_path / "a.jsonl"), ui)
    # a run outside any conversation stands in for one: its grants end with it
    token = gate.begin_task("book the tickets")
    await gate.guard(call("echo", text="1"), Echo())
    assert ui.requests[-1].purpose == "book the tickets"
    assert ui.requests[-1].grant_options[:2] == ["once", "conversation"]
    await gate.guard(call("echo", text="2"), Echo())
    assert asks(ui) == 1
    gate.end_task(token)
    token = gate.begin_task("something else")
    await gate.guard(call("echo", text="3"), Echo())
    assert asks(ui) == 2, "grants of a stand-alone run do not leak into the next"
    gate.end_task(token)

    # inside a conversation the grant outlives the run and ends with the conversation
    token = gate.begin_task("first turn", conversation="thread-1")
    await gate.guard(call("echo", text="4"), Echo())
    assert asks(ui) == 3
    gate.end_task(token)
    token = gate.begin_task("second turn", conversation="thread-1")
    await gate.guard(call("echo", text="5"), Echo())
    assert asks(ui) == 3, "the next turn of the same conversation is covered"
    gate.end_task(token)
    token = gate.begin_task("elsewhere", conversation="thread-2")
    await gate.guard(call("echo", text="6"), Echo())
    assert asks(ui) == 4, "another conversation is not"
    gate.end_task(token)
    gate.end_conversation("thread-1")
    token = gate.begin_task("third turn", conversation="thread-1")
    await gate.guard(call("echo", text="7"), Echo())
    assert asks(ui) == 5, "a deleted conversation takes its grants with it"
    gate.end_task(token)

    # the old client word for the scope still means the conversation (the server
    # normalizes it before the decision is built)
    assert grants_module.normalize_scope("task") == "conversation"
    assert grants_module.normalize_scope("conversation") == "conversation"
    assert grants_module.normalize_scope("whatever") == "once"
    assert grants_module.normalize_scope(None) == "once"


class Programs(BaseTool):
    """Shell-like: the grant target is the list of programs, not a destination."""

    name: str = "programs"
    description: str = "runs programs"
    parameters: dict[str, Any] = {"type": "object", "properties": {"command": {"type": "string"}}}
    risk: RiskLevel = RiskLevel.SENSITIVE
    egress: bool = True

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=self.risk,
            egress=True,
            egress_target=None,
            target=programs_of(str(args.get("command", ""))),
            summary="programs",
        )

    async def execute(self, command: str = "", **_: Any) -> ToolResult:
        return ToolResult(output=command)


async def test_conversation_grant_covers_the_whole_tool_when_targets_are_programs(
    tmp_path: Path,
):
    ui = ScopedUI(scope="conversation")
    gate = Sentinel(SentinelSettings(), AuditLog(tmp_path / "a.jsonl"), ui)
    token = gate.begin_task("count the lines")
    await gate.guard(call("programs", command="git clone x"), Programs())
    assert ui.requests[-1].grant_key == "programs:git"
    await gate.guard(call("programs", command="find . -name '*.py' | wc -l"), Programs())
    assert asks(ui) == 1, "'for this conversation' covers later commands with other programs"
    assert [g.key for g in gate.active_grants()] == ["programs"]
    gate.end_task(token)
    token = gate.begin_task("another job")
    await gate.guard(call("programs", command="ls"), Programs())
    assert asks(ui) == 2, "and ends with the stand-alone run"
    gate.end_task(token)

    # a destination-bound tool keeps its target even for this conversation
    ui2 = ScopedUI(scope="conversation")
    gate2 = Sentinel(SentinelSettings(always_ask_tools=["sender"]), AuditLog(tmp_path / "b"), ui2)
    token = gate2.begin_task("mail people")
    await gate2.guard(call("sender", host="a.example"), Sender())
    await gate2.guard(call("sender", host="b.example"), Sender())
    assert asks(ui2) == 2, "another recipient is another approval, even within the conversation"
    gate2.end_task(token)


async def test_gate_warnings_are_never_covered_by_grants(tmp_path: Path):
    class Risky(Echo):
        def assess(self, args: dict[str, Any]) -> CallAssessment:
            return CallAssessment(
                risk=RiskLevel.SENSITIVE, summary="risky", warnings=["looks dangerous"]
            )

    ui = ScopedUI(scope="always")
    gate = Sentinel(SentinelSettings(), AuditLog(tmp_path / "a.jsonl"), ui)
    gate.grants.add("echo", None, "session")
    await gate.guard(call("echo", text="1"), Risky())
    assert asks(ui) == 1, "a standing grant does not cover a call with warnings"
    assert ui.requests[-1].grant_options == ["once"]
    # the UI answered "always" although only "once" was offered: downgraded, asks again
    await gate.guard(call("echo", text="2"), Risky())
    assert asks(ui) == 2


async def test_gate_auto_mode_still_asks_on_warnings(tmp_path: Path):
    """Policy step 6 keeps a call with a warning an ASK in auto mode; the gate used to
    turn every ASK into ALLOW there, so `rm -rf` ran unattended."""

    class Risky(Echo):
        def assess(self, args: dict[str, Any]) -> CallAssessment:
            return CallAssessment(
                risk=RiskLevel.SENSITIVE, summary="risky", warnings=["looks dangerous"]
            )

    ui = ScopedUI(scope="once")
    gate = Sentinel(SentinelSettings(mode="auto"), AuditLog(tmp_path / "a.jsonl"), ui)
    # a call without a warning runs without a question
    await gate.guard(call("echo", text="plain"), Echo())
    assert asks(ui) == 0
    # a call with a warning asks, auto mode or not
    result = await gate.guard(call("echo", text="rm -rf"), Risky())
    assert asks(ui) == 1 and result.ok
    # and a declined one does not run
    ui.approve = False
    result = await gate.guard(call("echo", text="rm -rf /"), Risky())
    assert asks(ui) == 2 and not result.ok


async def test_gate_auto_mode_still_asks_on_tainted_egress(tmp_path: Path):
    """Policy step 5 keeps an egress to an unlisted host an ASK once this conversation read
    private data. The gate turned every ASK into ALLOW in auto mode, so the hands-off mode
    that background passes run in was the one way to walk straight through the taint rule:
    read a private file, then send it out, with nothing asked."""
    ui = ScopedUI(scope="once")
    gate = Sentinel(SentinelSettings(mode="auto"), AuditLog(tmp_path / "a.jsonl"), ui)
    # nothing private was read yet, so a moderate call to an unknown host just runs
    await gate.guard(call("sender", host="evil.com"), Sender())
    assert asks(ui) == 0
    # after private data entered the conversation, the same destination asks
    await gate.guard(call("reader"), Reader())
    result = await gate.guard(call("sender", host="evil.com"), Sender())
    assert asks(ui) == 1 and result.ok
    # declined, it does not run
    ui.approve = False
    result = await gate.guard(call("sender", host="evil.com"), Sender())
    assert asks(ui) == 2 and not result.ok


def test_grant_options_follow_muse_rules():
    sensitive_known = CallAssessment(risk=RiskLevel.SENSITIVE, egress=True, egress_target="x")
    assert Sentinel.grant_options(sensitive_known, "x") == [
        "once",
        "conversation",
        "session",
        "24h",
        "always",
    ]
    sensitive_unknown = CallAssessment(risk=RiskLevel.SENSITIVE, egress=True)
    assert Sentinel.grant_options(sensitive_unknown, None) == ["once", "conversation"]
    safe_toolwide = CallAssessment(risk=RiskLevel.SAFE)
    assert "always" in Sentinel.grant_options(safe_toolwide, None)
    with_warning = CallAssessment(risk=RiskLevel.SAFE, warnings=["w"])
    assert Sentinel.grant_options(with_warning, "x") == ["once"]


def test_grant_store_expiry_and_legacy_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    legacy = tmp_path / "approvals.json"
    legacy.write_text('["shell"]', "utf-8")
    store = GrantStore(legacy)
    assert store.match("shell") is not None and store.match("shell").scope == "always"
    # a 24h grant given two days ago
    real_time = time.time
    monkeypatch.setattr(grants_module.time, "time", lambda: real_time() - 2 * grants_module.DAY)
    day = store.add("web_fetch", "example.com", "24h")
    monkeypatch.undo()
    assert day is not None and day.expires_at is not None
    assert store.match("web_fetch:example.com") is None
    assert store.add("echo", None, "once") is None, "once is never stored"
    assert store.add("echo", None, "conversation", conversation_id=None) is None, (
        "the conversation scope needs a conversation"
    )
    assert store.add("echo", None, "task", conversation_id="c").scope == "conversation", (  # type: ignore[union-attr]
        "the old name is understood"
    )
    reloaded = GrantStore(legacy)
    assert [g.key for g in reloaded.active()] == ["shell"], "expired grants are dropped on load"


def test_grants_compose_over_several_targets():
    store = GrantStore()
    store.add("shell", "git,head", "session")
    assert {g.key for g in store.active()} == {"shell:git", "shell:head"}
    assert store.match("shell:git") is not None, "approving a pipeline covers its programs"
    assert store.match("shell:head,git") is not None
    assert store.match("shell:git,curl") is None, "every program needs a grant"
    store.add("shell", None, "session")
    assert store.match("shell:curl") is not None, "a tool-wide grant covers every target"


def test_shell_programs_are_the_grant_target():
    assert programs_of("git status") == "git"
    assert programs_of("cd web && npm run build") == "npm"
    assert programs_of("FOO=1 env python3 x.py | grep y") == "grep,python3"
    # what runs inside a substitution is bound too: a grant for `echo` is not one for `curl`
    assert programs_of("echo $(curl -s https://example.com)") == "curl,echo"
    assert programs_of("ls `date`") == "date,ls"
    assert programs_of("diff <(sort a) <(sort b)") == "diff,sort"
    assert programs_of("/usr/bin/curl https://x") == "curl"
    assert programs_of("echo hi") == "echo"
    assert programs_of("cd /tmp") is None


async def test_gate_taint_then_egress_asks(tmp_path: Path):
    ui = HeadlessUI(approve=False)
    gate = Sentinel(SentinelSettings(), AuditLog(tmp_path / "a.jsonl"), ui)
    assert not gate.tainted
    await gate.guard(call("reader"), Reader())
    assert gate.tainted
    blocked = await gate.guard(call("sender", host="evil.com"), Sender())
    assert blocked.error and "not on sentinel.egress_allowlist" in blocked.error
    allowed = await gate.guard(call("sender", host="api.github.com"), Sender())
    assert allowed.ok


async def test_taint_is_one_conversation_and_not_the_chat_beside_it(tmp_path: Path):
    """One Sentinel serves every thread of the app: what one chat read must not taint
    another, and clearing one chat must not un-taint the chat running beside it."""
    ui = HeadlessUI(approve=False)
    gate = Sentinel(SentinelSettings(), AuditLog(tmp_path / "a.jsonl"), ui)

    first = gate.begin_task("chat a", conversation="a")
    await gate.guard(call("reader"), Reader())
    assert gate.tainted
    gate.end_task(first)

    # a second conversation that never read anything private is not asked
    second = gate.begin_task("chat b", conversation="b")
    assert not gate.tainted
    result = await gate.guard(call("sender", host="evil.com"), Sender())
    assert result.ok
    gate.end_task(second)

    # ending a conversation drops its own taint and keeps the other's
    third = gate.begin_task("chat c", conversation="c")
    await gate.guard(call("reader"), Reader())
    gate.end_task(third)
    assert gate.tainted_for("a") and gate.tainted_for("c")
    gate.end_conversation("c")
    assert not gate.tainted_for("c")
    assert gate.tainted_for("a")


async def test_gate_resolves_secrets_and_redacts(tmp_path: Path):
    vault = CredentialVault(tmp_path / "v.enc", tmp_path / "v.key")
    vault.set("API_TOKEN", "super-secret-token")
    gate = Sentinel(SentinelSettings(), AuditLog(tmp_path / "a.jsonl"), HeadlessUI(), vault=vault)
    result = await gate.guard(
        call("sender", host="github.com", token="{{vault:API_TOKEN}}"), Sender()
    )
    # the tool received the real secret, but the model sees a redacted output
    assert result.output == "sent to github.com with [REDACTED:API_TOKEN]"
    # a tool that does not accept secrets is not run with the literal placeholder: the
    # call is refused with the reason (and never saw the value)
    result2 = await gate.guard(call("echo", text="{{vault:API_TOKEN}}"), Echo())
    assert not result2.ok and result2.error and "does not take {{vault:NAME}}" in result2.error
    assert "super-secret-token" not in (result2.error or "")
