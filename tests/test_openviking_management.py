from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nanomuse.agent import MuseAgent
from nanomuse.config import Settings
from nanomuse.llm import MockLLM
from nanomuse.memory.openviking import OpenVikingManage, OpenVikingMemory
from nanomuse.schema import Function, LLMResponse, ToolCall
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.server import create_app
from nanomuse.server.service import MuseService
from nanomuse.tools import ToolCollection
from nanomuse.ui import HeadlessUI

ROOT = "viking://user/test-user/memories"
URI = ROOT + "/entities/project.md"
RAW = 'Project: Amber, code NM-7318.\n\n<!-- MEMORY_FIELDS\n{"type":"entity"}\n-->'


class MemoryBackend:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.files = {URI: RAW}
        self.task_state = "running"

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        body = json.loads(request.content) if request.content else {}
        path, params = request.url.path, request.url.params
        result: Any = {}
        extra: dict[str, Any] = {}
        if path == "/api/v1/system/status":
            result = {"user": "test-user"}
        elif path == "/api/v1/fs/ls":
            result = [
                {"uri": URI, "isDir": False, "abstract": "Project identifier"},
                {"uri": ROOT + "/.overview.md", "isDir": False},
                {"uri": "viking://user/other/memories/private.md", "isDir": False},
            ]
            extra["has_more"] = True
        elif path == "/api/v1/content/read":
            if params["uri"] not in self.files:
                return httpx.Response(404)
            result = self.files[params["uri"]]
        elif path == "/api/v1/content/batch-write":
            operation = body["operations"][0]
            assert body["wait"] and body["root_uri"] == ROOT + "/entities"
            assert (
                operation["expected_sha256"] == hashlib.sha256(self.files[URI].encode()).hexdigest()
            )
            self.files[URI] = operation["content"]
        elif path == "/api/v1/fs" and request.method == "DELETE":
            assert params["recursive"] == "false" and params["wait"] == "true"
            del self.files[params["uri"]]
        elif path == "/api/v1/search/find":
            assert body["target_uri"] == ROOT
            result = {"memories": [{"uri": URI, "abstract": "Project"}]}
        elif path == "/api/v1/search/search":
            result = {"rendered": ""}
        elif path == "/api/v1/sessions" or path.endswith("/messages"):
            pass
        elif path.endswith("/commit"):
            result = {"task_id": "test-task"}
        elif path == "/api/v1/tasks/test-task":
            result = {"status": self.task_state}
        else:
            raise AssertionError(f"Unexpected {request.method} {path}")
        return httpx.Response(200, json={"status": "ok", "result": result, **extra})


@pytest.fixture()
def remote(settings: Settings) -> Iterator[tuple[OpenVikingMemory, MemoryBackend]]:
    cfg = settings.memory.openviking
    cfg.enabled, cfg.auth_mode, cfg.account, cfg.user = True, "trusted", "test-account", "test-user"
    backend = MemoryBackend()
    memory = OpenVikingMemory(
        cfg, settings.data_dir / "outbox.db", transport=httpx.MockTransport(backend.handle)
    )
    # Each async test closes its client in the same event loop.
    yield memory, backend


@pytest.mark.parametrize(
    "uri",
    [
        ROOT + "/../secrets.md",
        ROOT + "/%2e%2e/secrets.md",
        ROOT + "/.overview.md",
        ROOT + "/x\\private.md",
        ROOT + "/x\tprivate.md",
        ROOT + "/x.md?raw=true",
        ROOT + "/nested//x.md",
        ROOT + "/entities",
        "viking://user/other/memories/private.md",
        "viking://~/sessions/archive.md",
        ROOT,
    ],
)
async def test_rejects_unsafe_memory_file_uris(
    remote: tuple[OpenVikingMemory, MemoryBackend], uri: str
) -> None:
    memory, backend = remote
    try:
        result = await OpenVikingManage(bridge=memory).execute(action="delete", uri=uri)
        assert not result.ok and result.error.startswith("400:")
        assert len(backend.calls) == 1  # identity discovery only
        assert backend.files == {URI: RAW}
    finally:
        await memory.close()


async def test_browse_search_and_read_preserve_raw_revision(
    remote: tuple[OpenVikingMemory, MemoryBackend],
) -> None:
    memory, backend = remote
    try:
        page = await memory.browse(offset=50)
        assert [item["uri"] for item in page["items"]] == [URI]
        assert page["has_more"] and page["offset"] == 50
        assert backend.calls[-1].url.params["offset"] == "50"
        assert (await memory.browse(query="project"))["items"][0]["uri"] == URI
        entry = await memory.read_memory("viking://~/memories/entities/project.md")
        assert entry["content"] == "Project: Amber, code NM-7318."
        assert entry["revision"] == hashlib.sha256(RAW.encode()).hexdigest()
    finally:
        await memory.close()


async def test_stale_edits_and_deletes_do_not_change_a_memory(
    remote: tuple[OpenVikingMemory, MemoryBackend],
) -> None:
    memory, backend = remote
    tool = OpenVikingManage(bridge=memory)
    try:
        entry = await memory.read_memory(URI)
        backend.files[URI] += "changed"
        for action in ("update", "delete"):
            result = await tool.execute(action=action, **entry)
            assert not result.ok and result.error.startswith("409:")
        assert not any(r.method in ("POST", "DELETE") for r in backend.calls)
        entry = await memory.read_memory(URI)
        assert (await tool.execute(action="update", **{**entry, "content": "New code"})).ok
        assert backend.files[URI] == "New code"
        entry = await memory.read_memory(URI)
        assert (await tool.execute(action="delete", **entry)).ok
        assert not backend.files
    finally:
        await memory.close()


async def test_capture_preference_persists_and_is_identity_scoped(
    settings: Settings, remote: tuple[OpenVikingMemory, MemoryBackend]
) -> None:
    memory, backend = remote
    memory.set_capture(False)
    await memory.close()
    reopened = OpenVikingMemory(
        settings.memory.openviking,
        settings.data_dir / "outbox.db",
        transport=httpx.MockTransport(backend.handle),
    )
    assert not reopened.capture_enabled
    await reopened.close()
    settings.memory.openviking.user = "another-user"
    other = OpenVikingMemory(settings.memory.openviking, settings.data_dir / "outbox.db")
    assert other.capture_enabled
    await other.close()


async def test_status_distinguishes_queue_from_async_extraction(
    remote: tuple[OpenVikingMemory, MemoryBackend],
) -> None:
    memory, backend = remote
    try:
        memory.enqueue("turn", [{"role": "user", "content": "Synthetic project fact"}])
        assert memory.pending_count() == 1
        assert await memory.flush() == 1
        assert (await memory.status()) == {
            "enabled": True,
            "capture": True,
            "pending": 0,
            "tasks": [{"state": "running"}],
        }
        backend.task_state = "failed"
        assert (await memory.status())["tasks"] == [{"state": "failed"}]
        calls = len(backend.calls)
        await memory.status()
        assert len(backend.calls) == calls  # terminal tasks do not poll forever
    finally:
        await memory.close()


async def test_model_cannot_toggle_capture_and_explicit_remember_works_when_capture_off(
    remote: tuple[OpenVikingMemory, MemoryBackend],
) -> None:
    memory, _ = remote
    tool = OpenVikingManage(bridge=memory)
    try:
        assert not (await tool.execute(action="capture", capture=False)).ok
        assert memory.capture_enabled
        memory.set_capture(False)
        assert (await tool.execute(action="remember", content="Synthetic durable fact")).ok
        assert not memory.capture_enabled
        assert len((await memory.status())["tasks"]) == 1
    finally:
        await memory.close()


async def test_capture_off_skips_normal_turns_and_a_midturn_switch(
    settings: Settings, remote: tuple[OpenVikingMemory, MemoryBackend]
) -> None:
    memory, backend = remote
    audit, ui = AuditLog(settings.audit_file), HeadlessUI()

    def switch_off(*_: Any) -> LLMResponse:
        memory.set_capture(False)
        return LLMResponse(content="Done")

    llm = MockLLM([LLMResponse(content="Reply"), switch_off])
    runner = MuseAgent(
        settings,
        llm,
        ToolCollection(),
        Sentinel(settings.sentinel, audit, ui),
        ui,
        audit,
        openviking=memory,
    )
    try:
        memory.set_capture(False)
        await runner.run("An ordinary conversation")
        memory.set_capture(True)
        await runner.run("Capture is switched off before this reply finishes")
        assert not any("/sessions" in str(r.url) for r in backend.calls)
    finally:
        await memory.close()


async def test_turn_capture_flag_blocks_model_memory_writes_and_resets_next_turn(
    settings: Settings, remote: tuple[OpenVikingMemory, MemoryBackend]
) -> None:
    memory, backend = remote
    call = ToolCall(
        function=Function(
            name="openviking_memory",
            arguments=json.dumps({"action": "remember", "content": "One-off"}),
        )
    )
    llm = MockLLM(
        [LLMResponse(tool_calls=[call]), LLMResponse(content="Done"), LLMResponse(content="Next")]
    )
    audit, ui = AuditLog(settings.audit_file), HeadlessUI()
    runner = MuseAgent(
        settings,
        llm,
        ToolCollection(OpenVikingManage(bridge=memory)),
        Sentinel(settings.sentinel, audit, ui),
        ui,
        audit,
        openviking=memory,
    )
    try:
        await runner.run("Run an automated report", capture_memory=False)
        assert not any("/sessions" in str(r.url) for r in backend.calls)
        assert any("Memory writes are disabled" in (m.content or "") for m in runner.messages)
        await runner.run("My synthetic project code is NM-7318")
        assert any(r.url.path.endswith("/commit") for r in backend.calls)
    finally:
        await memory.close()


def test_authenticated_controls_respect_deny_and_preserve_conflicts(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = MemoryBackend()
    settings.server.token = "synthetic-test-token"
    settings.sentinel.mode = "strict"
    cfg = settings.memory.openviking
    cfg.enabled, cfg.auth_mode, cfg.account, cfg.user = True, "trusted", "test-account", "test-user"

    def factory(*args: Any, **kwargs: Any) -> OpenVikingMemory:
        return OpenVikingMemory(*args, **kwargs, transport=httpx.MockTransport(backend.handle))

    monkeypatch.setattr("nanomuse.app.OpenVikingMemory", factory)
    service = MuseService(settings, llm=MockLLM([]))
    with TestClient(create_app(settings, service)) as client:
        path = "/api/memory/openviking"
        assert client.get(path + "/status").status_code == 401
        client.headers["Authorization"] = "Bearer synthetic-test-token"
        assert client.get(path + "/entries").status_code == 200
        entry = client.get(path + "/entry", params={"uri": URI}).json()
        backend.files[URI] += "updated"
        assert client.put(path + "/entry", json=entry).status_code == 409
        latest = client.get(path + "/entry", params={"uri": URI}).json()
        assert (
            client.put(path + "/entry", json={**latest, "content": "Corrected fact"}).status_code
            == 200
        )
        assert backend.files[URI] == "Corrected fact"
        assert client.put(path + "/capture", json={"enabled": False}).status_code == 200
        assert not client.get(path + "/status").json()["capture"]
        settings.sentinel.deny_tools = ["openviking_*"]
        count = len(backend.calls)
        assert client.request("DELETE", path + "/entry", json=entry).status_code == 403
        assert len(backend.calls) == count
