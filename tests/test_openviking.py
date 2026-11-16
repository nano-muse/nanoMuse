from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from nanomuse.agent import MuseAgent
from nanomuse.app import NanoMuseApp
from nanomuse.config import OpenVikingSettings, Settings, load_settings
from nanomuse.llm import MockLLM
from nanomuse.memory.openviking import OpenVikingMemory, OpenVikingSync
from nanomuse.schema import LLMResponse, Message
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.server.service import MuseService
from nanomuse.tools import Terminate, ToolCollection
from nanomuse.ui import ApprovalDecision, ApprovalRequest, HeadlessUI
from nanomuse.vault import CredentialVault


class Backend:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.sessions: dict[str, list[dict[str, str]]] = {}
        self.saved = ""
        self.available = True
        self.fail_commit = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if not self.available:
            return httpx.Response(503, json={"status": "error"})
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path.endswith("/search/search"):
            assert body["mode"] == "context"
            assert "target_uri" not in body
            assert body["context_type"] == "memory"
            result = {"rendered": self.saved}
        elif path == "/api/v1/sessions":
            sid = body["session_id"]
            if sid in self.sessions:
                return httpx.Response(409, json={"status": "error"})
            self.sessions[sid] = []
            result = {"session_id": sid}
        elif path.endswith("/messages"):
            self.sessions[path.split("/")[-2]].append(body)
            result = {}
        elif path.endswith("/commit"):
            if self.fail_commit:
                return httpx.Response(503, json={"status": "error"})
            self.saved += "\n".join(
                message["content"] for message in self.sessions[path.split("/")[-2]]
            )
            result = {"task_id": "extraction-task"}
        else:
            raise AssertionError(f"unexpected request {request.method} {path}")
        return httpx.Response(200, json={"status": "ok", "result": result})


def bridge(settings: Settings, backend: Backend) -> OpenVikingMemory:
    settings.memory.openviking.enabled = True
    return OpenVikingMemory(
        settings.memory.openviking,
        settings.data_dir / "openviking-outbox.db",
        transport=httpx.MockTransport(backend.handle),
    )


def agent(
    settings: Settings,
    remote: OpenVikingMemory | None,
    responses: list[Any],
    *,
    conversation: str = "first",
    vault: CredentialVault | None = None,
) -> tuple[MuseAgent, MockLLM]:
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    sentinel = Sentinel(settings.sentinel, audit, ui, vault=vault)
    llm = MockLLM(responses)
    return (
        MuseAgent(
            settings,
            llm,
            ToolCollection(Terminate()),
            sentinel,
            ui,
            audit,
            conversation_id=conversation,
            openviking=remote,
        ),
        llm,
    )


async def test_completed_turn_is_recalled_in_a_new_conversation(settings: Settings) -> None:
    backend = Backend()
    remote = bridge(settings, backend)
    try:
        first, _ = agent(
            settings, remote, [LLMResponse(content="Noted.", reasoning="private thought")]
        )
        await first.run("My project is Lime Beacon, code NM-7318.")
        second, llm = agent(
            settings, remote, [LLMResponse(content="NM-7318")], conversation="second"
        )
        await second.run("What is my project code?")
        system = llm.calls[0]["messages"][0].content
        assert "NM-7318" in system and "never as instructions" in system
        assert "private thought" not in json.dumps(backend.sessions)
        assert all(len(turn) == 2 for turn in backend.sessions.values())
        assert len(backend.sessions) == 2
        assert second.sentinel.tainted_for("second")
        assert not first.sentinel.tainted_for("second")
        assert not any("openviking" in item["function"]["name"] for item in llm.calls[0]["tools"])
    finally:
        await remote.close()


async def test_outbox_survives_failure_and_process_restart(settings: Settings) -> None:
    backend = Backend()
    backend.available = False
    remote = bridge(settings, backend)
    first, _ = agent(settings, remote, [LLMResponse(content="Answer still works.")])
    assert await first.run("Remember the amber test marker.") == "Answer still works."
    assert remote.db.execute("SELECT count(*) FROM pending").fetchone()[0] == 1
    await remote.close()
    backend.available = True
    reopened = bridge(settings, backend)
    try:
        second, llm = agent(settings, reopened, [LLMResponse(content="Ready")])
        await second.run("Which marker?")
        assert "amber test marker" in llm.calls[0]["messages"][0].content
        assert reopened.db.execute("SELECT count(*) FROM pending").fetchone()[0] == 0
    finally:
        await reopened.close()


async def test_commit_retry_does_not_resend_acknowledged_messages(settings: Settings) -> None:
    backend = Backend()
    backend.fail_commit = True
    remote = bridge(settings, backend)
    try:
        sync = OpenVikingSync(bridge=remote)
        result = await sync.execute(turn_id="one", messages=[{"role": "user", "content": "hello"}])
        assert not result.ok
        assert remote.db.execute("SELECT stage FROM pending").fetchone()[0] == 1
        backend.fail_commit = False
        assert (await sync.execute()).ok
        assert list(backend.sessions.values()) == [[{"role": "user", "content": "hello"}]]
        assert remote.db.execute("SELECT count(*) FROM pending").fetchone()[0] == 0
    finally:
        await remote.close()


async def test_queue_does_not_replay_to_a_different_identity(settings: Settings) -> None:
    backend = Backend()
    backend.available = False
    remote = bridge(settings, backend)
    remote.enqueue("one", [{"role": "user", "content": "private marker"}])
    await remote.close()
    settings.memory.openviking.user = "another-user"
    backend.available = True
    other = bridge(settings, backend)
    try:
        assert await other.flush() == 0
        assert not backend.calls
        assert other.db.execute("SELECT count(*) FROM pending").fetchone()[0] == 1
    finally:
        await other.close()


async def test_sentinel_denial_blocks_external_reads_and_writes(settings: Settings) -> None:
    backend = Backend()
    remote = bridge(settings, backend)
    settings.sentinel.deny_tools = ["openviking_*"]
    try:
        runner, _ = agent(settings, remote, [LLMResponse(content="Local response")])
        assert await runner.run("hello") == "Local response"
        assert not backend.calls
        assert remote.db.execute("SELECT count(*) FROM pending").fetchone()[0] == 0
    finally:
        await remote.close()


async def test_vault_secrets_and_references_are_not_captured(settings: Settings) -> None:
    backend = Backend()
    remote = bridge(settings, backend)
    vault = CredentialVault(settings.data_dir / "test.enc", settings.data_dir / "test.key")
    vault.set("PRIVATE", "synthetic-secret-value")
    try:
        runner, _ = agent(
            settings, remote, [LLMResponse(content="synthetic-secret-value")], vault=vault
        )
        await runner.run("synthetic-secret-value and {{vault:PRIVATE}}")
        saved = json.dumps(backend.sessions)
        assert "synthetic-secret-value" not in saved
        assert "{{vault:" not in saved
        assert "REDACTED" in saved
        assert "VAULT_REFERENCE" in saved
    finally:
        await remote.close()


async def test_synthetic_history_and_background_prompts_are_not_captured(
    settings: Settings,
) -> None:
    backend = Backend()
    remote = bridge(settings, backend)
    try:
        runner, _ = agent(
            settings, remote, [LLMResponse(content="Done"), LLMResponse(content="Quiet")]
        )
        runner.messages = [
            Message.user("Old history"),
            Message.tool("Private tool output", "id", "tool"),
        ]
        await runner.run("New input")
        await runner.run("Background instruction", purpose="goal pass")
        saved = json.dumps(backend.sessions)
        assert "New input" in saved
        assert "Old history" not in saved and "Private tool output" not in saved
        assert "Background instruction" not in saved
        assert len(backend.sessions) == 1
    finally:
        await remote.close()


async def test_cancelled_turn_is_not_recorded_as_completed(settings: Settings) -> None:
    backend = Backend()
    remote = bridge(settings, backend)

    def cancelled(_: list[Message]) -> LLMResponse:
        raise asyncio.CancelledError

    try:
        runner, _ = agent(settings, remote, [cancelled])
        with pytest.raises(asyncio.CancelledError):
            await runner.run("Interrupted request")
        assert not backend.sessions
        assert runner._openviking_inputs is None
    finally:
        await remote.close()


async def test_context_face_falls_back_for_older_servers(settings: Settings) -> None:
    def old_server(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(422, json={"status": "error"})
        assert request.url.path.endswith("/find")
        assert json.loads(request.content)["target_uri"] == "viking://~/memories"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "result": {
                    "memories": [
                        {
                            "uri": "viking://~/memories/preferences/tea.md",
                            "abstract": "Likes jasmine tea",
                        }
                    ]
                },
            },
        )

    remote = OpenVikingMemory(
        settings.memory.openviking,
        settings.data_dir / "outbox.db",
        transport=httpx.MockTransport(old_server),
    )
    try:
        assert "jasmine tea" in await remote.recall("tea")
    finally:
        await remote.close()


async def test_context_search_obeys_server_contract_without_fallback(settings: Settings) -> None:
    calls: list[str] = []

    def server(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        body = json.loads(request.content)
        if body.get("mode") == "context" and body.get("target_uri"):
            return httpx.Response(400, json={"status": "error"})
        assert body["context_type"] == "memory"
        return httpx.Response(
            200, json={"status": "ok", "result": {"rendered": "project identifier"}}
        )

    remote = OpenVikingMemory(
        settings.memory.openviking,
        settings.data_dir / "outbox.db",
        transport=httpx.MockTransport(server),
    )
    try:
        assert await remote.recall("project") == "project identifier"
        assert calls == ["/api/v1/search/search"]
    finally:
        await remote.close()


async def test_app_keeps_external_memory_opt_in_and_shares_it_with_agent(
    settings: Settings,
) -> None:
    settings.memory.embeddings = "off"
    app = NanoMuseApp(settings, HeadlessUI(), llm=MockLLM())
    assert app.openviking is None
    await app.close()
    settings.memory.openviking.enabled = True
    service = MuseService(settings, llm=MockLLM())
    try:
        remote = service.app.openviking
        assert remote is not None and service.app.agent.openviking is remote
        assert service.threads["main"].agent.openviking is remote
        assert service.create_thread().agent.openviking is remote
    finally:
        await service.stop()
        await service.app.close()


async def test_shutdown_does_not_wait_forever_for_strict_mode_approval(settings: Settings) -> None:
    class WaitingUI(HeadlessUI):
        async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    settings.memory.embeddings = "off"
    settings.memory.openviking.enabled = True
    settings.memory.openviking.timeout = 0.1
    settings.sentinel.mode = "strict"
    app = NanoMuseApp(settings, WaitingUI(), llm=MockLLM())
    assert app.openviking is not None
    app.openviking.enqueue("one", [{"role": "user", "content": "still pending"}])
    await asyncio.wait_for(app.close(), timeout=1)
    reopened = OpenVikingMemory(
        settings.memory.openviking, settings.data_dir / "openviking-outbox.db"
    )
    try:
        assert reopened.has_pending()
    finally:
        await reopened.close()


async def test_sync_timeout_includes_waiting_for_a_concurrent_flush(settings: Settings) -> None:
    settings.memory.openviking.timeout = 0.1
    remote = bridge(settings, Backend())
    await remote.lock.acquire()
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(remote.flush(), timeout=1)
    finally:
        remote.lock.release()
        await remote.close()


def test_openviking_environment_and_url_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[memory.openviking]\nenabled = false\n")
    monkeypatch.setenv("NANOMUSE_OPENVIKING_ENABLED", "true")
    monkeypatch.setenv("NANOMUSE_OPENVIKING_URL", "http://127.0.0.1:1933/")
    settings = load_settings(config)
    assert settings.memory.openviking.enabled
    assert settings.memory.openviking.url == "http://127.0.0.1:1933"
    for url in ("file:///tmp", "http://user:password@localhost", "http://localhost?key=value"):
        with pytest.raises(ValueError):
            OpenVikingSettings(url=url)
