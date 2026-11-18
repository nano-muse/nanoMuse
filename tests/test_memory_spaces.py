from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nanomuse.config import Settings
from nanomuse.llm import MockLLM
from nanomuse.memory.archive import MemoryArchive, digest
from nanomuse.memory.learning import LearningQueue
from nanomuse.memory.openviking import OpenVikingMemory, OpenVikingSync
from nanomuse.memory.personal import PersonalMemory, Proposal
from nanomuse.schema import Function, LLMResponse, ToolCall
from nanomuse.server import create_app
from nanomuse.server.service import MuseService


class Remote:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.sessions: set[str] = set()
        self.session_policies: dict[str, dict[str, Any]] = {}
        self.session_messages: dict[str, list[dict[str, Any]]] = {}
        self.extract_captured_turns = False
        self.calls: list[httpx.Request] = []
        self.available = True
        self.inject_other_space = False
        self.task_state = "completed"

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if not self.available:
            return httpx.Response(503)
        path, params = request.url.path, request.url.params
        body = json.loads(request.content) if request.content else {}
        result: Any = {}
        if path.endswith("/system/status"):
            result = {"user": "test-user"}
        elif path.endswith("/fs/ls"):
            root = params["uri"]
            result = []
            directories: set[str] = set()
            for uri in self.files:
                if not uri.startswith(root + "/"):
                    continue
                tail = uri[len(root) + 1 :]
                if "/" in tail:
                    directory = root + "/" + tail.split("/")[0]
                    if directory not in directories:
                        result.append({"uri": directory, "isDir": True})
                        directories.add(directory)
                else:
                    result.append({"uri": uri, "isDir": False})
        elif path.endswith("/content/read"):
            if params["uri"] not in self.files:
                return httpx.Response(404)
            result = self.files[params["uri"]]
        elif path.endswith("/content/batch-write"):
            for op in body["operations"]:
                uri = op["uri"]
                if op.get("if_absent"):
                    assert uri not in self.files
                elif op.get("expected_sha256"):
                    assert (
                        op["expected_sha256"]
                        == hashlib.sha256(self.files[uri].encode()).hexdigest()
                    )
                self.files[uri] = op["content"]
        elif path.endswith("/fs/stat"):
            if not any(uri.startswith(params["uri"] + "/") for uri in self.files):
                return httpx.Response(404)
        elif path.endswith("/fs/mkdir"):
            pass
        elif path == "/api/v1/fs" and request.method == "DELETE":
            del self.files[params["uri"]]
        elif path.endswith("/search/find"):
            result = {
                "memories": [
                    {"uri": uri, "abstract": text}
                    for uri, text in self.files.items()
                    if uri.startswith(body["target_uri"] + "/") or self.inject_other_space
                ]
            }
        elif path == "/api/v1/sessions":
            sid = body["session_id"]
            if sid in self.sessions:
                return httpx.Response(409)
            self.sessions.add(sid)
            self.session_policies[sid] = body.get("memory_policy", {})
            self.session_messages[sid] = []
        elif path.startswith("/api/v1/sessions/") and request.method == "DELETE":
            sid = path.rsplit("/", 1)[1]
            if sid not in self.sessions:
                return httpx.Response(404)
            self.sessions.remove(sid)
        elif path.endswith("/messages"):
            self.session_messages[path.split("/")[-2]].append(body)
        elif path.endswith("/commit"):
            sid = path.split("/")[-2]
            if self.extract_captured_turns:
                # Session routes ignore Actor-Peer headers. Extraction follows the
                # session policy and the peer on each user message instead.
                policy = self.session_policies[sid]
                for message in self.session_messages[sid]:
                    if message["role"] != "user":
                        continue
                    peer = message.get("peer_id", "")
                    target = "peer" if peer else "self"
                    if not policy.get(target, {}).get("enabled", True):
                        continue
                    root = "viking://user/test-user/"
                    if peer:
                        root += f"peers/{peer}/"
                    self.files[root + "memories/" + sid + ".md"] = message["content"]
        elif path.startswith("/api/v1/sessions/") and request.method == "GET":
            result = {"memory_policy": self.session_policies[path.rsplit("/", 1)[1]]}
        elif path.startswith("/api/v1/tasks/"):
            result = {"status": self.task_state}
        else:
            raise AssertionError(f"Unexpected mock request: {request.method} {path}")
        return httpx.Response(200, json={"status": "ok", "result": result})


@pytest.fixture()
def service(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> tuple[MuseService, Remote]:
    cfg = settings.memory.openviking
    cfg.enabled, cfg.auth_mode = True, "trusted"
    cfg.account, cfg.user = "test-account", "test-user"
    settings.memory.embeddings = "off"
    settings.mcp.servers = []
    remote = Remote()
    monkeypatch.setattr(
        "nanomuse.app.OpenVikingMemory",
        lambda *a, **kw: OpenVikingMemory(*a, **kw, transport=httpx.MockTransport(remote.handle)),
    )
    return MuseService(settings, llm=MockLLM([])), remote


def fact(store: PersonalMemory, value: str = "I prefer concise answers") -> None:
    p = Proposal(key="reply.length", kind="preference", value=value, quote=value)
    assert store.apply(p, [value], "source-turn", "source-chat")


@pytest.mark.asyncio()
@pytest.mark.parametrize("space", ["personal", "work"])
async def test_memory_switch_blocks_existing_and_new_chat_reads_and_writes(
    service: tuple[MuseService, Remote], space: str
) -> None:
    svc, remote = service
    hub = svc.app.memory_hub
    agent = svc.create_thread("Existing chat", space).agent
    store = hub.local(space)
    assert store is not None
    saved = store.add("Synthetic CINDER-728 preference", "preference")
    external = bridge(svc, space)
    fact(external.personal, "Synthetic CINDER-728 preference")
    root = await external.memory_root()
    remote.files[root + "/fact.md"] = "Synthetic CINDER-728 preference"
    original_capture = external.capture_enabled
    await hub.set_enabled(space, False)
    assert external.capture_enabled == original_capture
    assert hub.is_enabled("work" if space == "personal" else "personal")
    calls_before = len(remote.calls)
    for target in (agent, svc.create_thread("New chat", space).agent):
        assert await target.recall_for("preference") is None
        for name, args in (
            ("recall", {"query": "preference"}),
            ("remember", {"content": "Must not be saved"}),
            ("forget", {"memory_id": saved.id}),
            ("openviking_memory", {"action": "read", "uri": root + "/fact.md"}),
        ):
            assert not (await target.tools.execute(name, args)).ok

        def response(messages: list[Any]) -> LLMResponse:
            assert "CINDER-728" not in messages[0].content
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        function=Function(
                            name="remember", arguments=json.dumps({"content": "Must not be saved"})
                        )
                    )
                ]
            )

        svc.app.llm.script = [response, LLMResponse(content="No saved preferences used")]
        assert await target.run("Help me plan a comparison") == "No saved preferences used"
        assert "disabled" in target.messages[-2].content
    assert store.count() == 1 and store.get(saved.id) is not None
    assert not external.has_pending()
    assert LearningQueue(external.personal).status()["pending"] == 0
    assert len(remote.calls) == calls_before
    await hub.set_enabled(space, True)
    assert "CINDER-728" in (await agent.tools.execute("recall", {"query": "preference"})).output
    assert "CINDER-728" in await agent._openviking_context("preference")


@pytest.mark.asyncio()
async def test_memory_switch_pauses_queued_sync_and_learning(
    service: tuple[MuseService, Remote],
) -> None:
    svc, remote = service
    hub, external = svc.app.memory_hub, bridge(svc)
    external.enqueue("queued-turn", [{"role": "user", "content": "Synthetic queued fact"}])
    queue = LearningQueue(external.personal)
    queue.enqueue(["Synthetic queued fact"], "queued-turn", "chat")
    async with external.lock:
        with pytest.raises(ValueError, match="Memory is busy"):
            await hub.set_enabled("personal", False)
    await hub.set_enabled("personal", False)
    before = len(remote.calls)
    assert not (await OpenVikingSync(bridge=external).execute()).ok
    assert await external.flush() == 0
    assert not await hub.run_once()
    assert external.pending_count() == 1 and queue.status()["pending"] == 1
    assert len(remote.calls) == before
    await hub.set_enabled("personal", True)
    assert await external.flush() == 1
    assert external.pending_count() == 0


def test_memory_switch_api_authentication_busy_guards_and_saved_controls(
    service: tuple[MuseService, Remote],
) -> None:
    svc, _ = service
    svc.token = "synthetic-memory-usage-token"
    external = bridge(svc)
    external.set_capture(False)
    with TestClient(create_app(svc.settings, svc)) as client:
        path = "/api/memory/spaces/personal/enabled"
        assert client.put(path, json={"enabled": False}).status_code == 401
        client.headers["Authorization"] = "Bearer synthetic-memory-usage-token"
        assert client.put(path, json={"enabled": False}).json() == {"enabled": False}
        assert not client.get("/api/memory/spaces").json()["enabled"]
        assert client.get("/api/memory/spaces?space=work").json()["enabled"]
        # Explicit owner controls still inspect and remove retained data.
        assert client.post("/api/memory", json={"content": "Owner-managed note"}).status_code == 200
        assert client.get("/api/memory").json()[0]["content"] == "Owner-managed note"
        assert client.get("/api/memory/openviking/profile").status_code == 200
        assert not client.get("/api/memory/openviking/status").json()["usage_enabled"]
        assert not external.capture_enabled
        svc._tidying = True
        assert client.put(path, json={"enabled": True}).status_code == 409
        svc._tidying = False
        assert (
            client.put("/api/memory/spaces/missing/enabled", json={"enabled": True}).status_code
            == 404
        )
        svc.app.memory_hub.space_busy = lambda space: space == "personal"
        assert client.put(path, json={"enabled": True}).status_code == 409
        assert not svc.app.memory_hub.is_enabled()
        svc.app.memory_hub.space_busy = lambda space: False
        svc.settings.sentinel.deny_tools = ["memory_usage"]
        assert client.put(path, json={"enabled": True}).status_code == 403
        assert not svc.app.memory_hub.is_enabled()


@pytest.mark.asyncio()
async def test_memory_switch_persists_without_openviking(settings: Settings) -> None:
    first = MuseService(settings, llm=MockLLM())
    assert first.app.memory_hub.is_enabled()
    await first.app.memory_hub.set_enabled("personal", False)
    await first.stop()
    second = MuseService(settings, llm=MockLLM())
    assert not second.app.memory_hub.is_enabled()
    assert not (await second.app.agent.tools.execute("remember", {"content": "Blocked"})).ok
    await second.app.memory_hub.set_enabled("personal", True)
    assert (await second.app.agent.tools.execute("remember", {"content": "Allowed"})).ok
    await second.stop()


@pytest.mark.asyncio()
async def test_memory_switch_excludes_saved_preferences_from_ideas_and_feed(
    service: tuple[MuseService, Remote],
) -> None:
    svc, _ = service
    assert svc.app.memory is not None
    for idx in range(svc.TIDY_MIN_LINES):
        svc.app.memory.add(f"Synthetic preference CINDER-{idx}")
    svc.threads["main"].timeline.events.append(
        {"type": "assistant", "text": "Previously recalled CINDER-728"}
    )
    assert "CINDER" in "\n".join(svc._feed_context())
    assert svc.memory_tidy_due()
    await svc.app.memory_hub.set_enabled("personal", False)
    assert "CINDER" not in "\n".join(svc._feed_context())
    assert not svc.memory_tidy_due()
    svc.settings.agent.user_profile = "Manually configured app instructions"

    def response(messages: list[Any]) -> LLMResponse:
        assert "CINDER" not in messages[0].content
        return LLMResponse(content='[{"title": "Fresh idea", "prompt": "Help me plan"}]')

    svc.app.llm.script = [response]
    assert (await svc.refresh_ideas())["source"] == "model"


def bridge(service: MuseService, space: str = "personal") -> OpenVikingMemory:
    result = service.app.memory_hub.bridge(space)
    assert result is not None
    return result


@pytest.mark.asyncio()
async def test_credential_rotation_keeps_profile_but_never_retargets_outbox(
    settings: Settings,
) -> None:
    cfg = settings.memory.openviking
    cfg.auth_mode, cfg.account, cfg.user = "trusted", "test-account", "test-user"
    path = settings.data_dir / "rotation.db"
    first = OpenVikingMemory(cfg, path, api_key="synthetic-first")
    fact(first.personal)
    first.set_capture(False)
    first.enqueue("turn", [{"role": "user", "content": "A synthetic fact"}])
    namespace, profile, owner = first.namespace, first.personal.namespace, first.owner
    await first.close()
    second = OpenVikingMemory(cfg, path, api_key="synthetic-second")
    assert second.namespace != namespace
    assert second.owner == owner and second.personal.namespace == profile
    assert second.personal.items() and not second.capture_enabled
    assert not second.has_pending()
    assert (
        second.db.execute(
            "SELECT count(*) FROM pending WHERE namespace = ?", (namespace,)
        ).fetchone()[0]
        == 1
    )
    await second.close()


@pytest.mark.asyncio()
async def test_only_current_connection_legacy_profile_is_migrated(settings: Settings) -> None:
    path = settings.data_dir / "legacy.db"
    first = OpenVikingMemory(settings.memory.openviking, path)
    fact(PersonalMemory(first.db, first.namespace))
    fact(PersonalMemory(first.db, "another-owner"), "Another owner's preference")
    await first.close()
    second = OpenVikingMemory(settings.memory.openviking, path)
    assert second.personal.items()[0]["value"] == "I prefer concise answers"
    assert PersonalMemory(second.db, "another-owner").items()
    await second.close()


@pytest.mark.asyncio()
async def test_spaces_bind_local_tools_profile_and_remote_recall(
    service: tuple[MuseService, Remote],
) -> None:
    svc, remote = service
    personal, work = bridge(svc), bridge(svc, "work")
    assert personal.owner == work.owner and personal.personal.namespace != work.personal.namespace
    fact(personal.personal)
    assert not work.personal.items()
    personal_uri = await personal.memory_root() + "/fact.md"
    work_uri = await work.memory_root() + "/fact.md"
    remote.files.update({personal_uri: "Personal-only fact", work_uri: "Work-only fact"})
    remote.inject_other_space = True
    assert "Personal-only" not in await work.recall("fact")
    assert "Work-only" not in await personal.recall("fact")
    thread = svc.create_thread("Work chat", "work")
    store = svc.app.memory_hub.local("work")
    assert store is not None
    result = await thread.agent.tools.execute("remember", {"content": "Work-only local fact"})
    assert result.ok and store.count() == 1
    assert svc.app.memory is not None and svc.app.memory.count() == 0
    assert thread.agent.tools.get("openviking_memory").bridge is work
    assert not svc.sync._eligible(thread)
    assert json.loads((svc.threads_dir / "index.json").read_text())[-1]["memory_space"] == "work"
    svc._move_thread(thread, "t_moved")
    assert svc.threads["t_moved"].memory_space == "work"


@pytest.mark.asyncio()
async def test_captured_work_turns_are_extracted_into_work_memory_only(
    service: tuple[MuseService, Remote],
) -> None:
    svc, remote = service
    remote.extract_captured_turns = True
    personal, work = bridge(svc), bridge(svc, "work")
    thread = svc.create_thread("Work test", "work")
    thread.agent.llm = MockLLM([LLMResponse(content="Noted")])
    await thread.agent.run("Work project code QUARTZ-742")
    assert "QUARTZ-742" in await work.recall("project code")
    assert "QUARTZ-742" not in await personal.recall("project code")
    sid = next(iter(remote.sessions))
    assert remote.session_policies[sid] == {
        "self": {"enabled": False},
        "peer": {"enabled": True},
    }
    assert remote.session_messages[sid][0]["peer_id"] == work.settings.peer_id
    assert "peer_id" not in remote.session_messages[sid][1]
    personal.enqueue("personal-turn", [{"role": "user", "content": "Personal code LIME-318"}])
    assert await personal.flush() == 1
    assert "LIME-318" in await personal.recall("code")
    assert "LIME-318" not in await work.recall("code")


@pytest.mark.asyncio()
@pytest.mark.parametrize("stage", [-1, 1])
async def test_peer_capture_refuses_existing_sessions_with_unscoped_policy(
    service: tuple[MuseService, Remote],
    stage: int,
) -> None:
    svc, remote = service
    work = bridge(svc, "work")
    work.enqueue("old-turn", [{"role": "user", "content": "Work-only synthetic fact"}])
    sid = work.db.execute(
        "SELECT id FROM pending WHERE namespace = ?", (work.namespace,)
    ).fetchone()[0]
    remote.sessions.add(sid)
    remote.session_policies[sid] = {}
    remote.session_messages[sid] = []
    if stage >= 0:
        work._advance(sid, stage)
    with pytest.raises(ValueError, match="session.*policy"):
        await work.flush()
    assert work.has_pending()
    assert not remote.session_messages[sid]
    assert not any(r.url.path.endswith("/commit") for r in remote.calls)


@pytest.mark.asyncio()
async def test_chat_queues_learning_and_finishes_before_the_extra_model_call(
    service: tuple[MuseService, Remote],
) -> None:
    svc, _ = service
    value = "I prefer concise answers"
    extraction = json.dumps(
        [{"key": "reply.length", "kind": "preference", "quote": value, "value": value}]
    )
    llm = MockLLM([LLMResponse(content="Understood"), LLMResponse(content=extraction)])
    svc.app.llm = svc.app.agent.llm = llm
    await svc.app.agent.run(value)
    queue = LearningQueue(bridge(svc).personal)
    assert len(llm.calls) == 1 and queue.status()["pending"] == 1
    assert not bridge(svc).personal.items()
    assert await svc.app.memory_hub.run_once()
    assert len(llm.calls) == 2 and bridge(svc).personal.items()
    assert queue.status()["pending"] == 0


@pytest.mark.asyncio()
async def test_learning_failure_is_durable_and_can_retry(
    service: tuple[MuseService, Remote],
) -> None:
    svc, _ = service
    store = bridge(svc).personal
    queue = LearningQueue(store)
    queue.enqueue(["I prefer concise answers"], "turn", "chat")
    svc.app.llm = MockLLM([LLMResponse(content="invalid JSON"), LLMResponse(content="[]")])
    assert await svc.app.memory_hub.run_once()
    assert queue.status()["pending"] == 1
    assert not await svc.app.memory_hub.run_once()
    queue.retry()
    assert await svc.app.memory_hub.run_once()
    assert queue.status() == {"pending": 0, "failed": 0}


@pytest.mark.asyncio()
async def test_manual_review_invalidates_older_queued_learning(
    service: tuple[MuseService, Remote],
) -> None:
    svc, _ = service
    store = bridge(svc).personal
    fact(store)
    queue = LearningQueue(store)
    queue.enqueue(["Outdated message"], "turn", "chat")
    item = store.items()[0]
    store.review(item["id"], item["version"], "edit", "An owner-corrected fact")
    svc.app.llm = MockLLM([])
    assert not await svc.app.memory_hub.run_once()
    assert not svc.app.llm.calls and queue.status()["pending"] == 0


@pytest.mark.asyncio()
async def test_capture_switch_pauses_jobs_and_denials_fail_after_bounded_retries(
    service: tuple[MuseService, Remote],
) -> None:
    svc, _ = service
    remote = bridge(svc)
    queue = LearningQueue(remote.personal)
    queue.enqueue(["Synthetic evidence"], "turn", "chat")
    remote.set_capture(False)
    assert not await svc.app.memory_hub.run_once()
    assert queue.status()["pending"] == 1
    remote.set_capture(True)
    svc.settings.sentinel.deny_tools = ["personal_memory_learn"]
    for _ in range(5):
        remote.db.execute("UPDATE learning_jobs SET due = 0")
        remote.db.commit()
        assert await svc.app.memory_hub.run_once()
    assert queue.status() == {"pending": 0, "failed": 1}
    assert not svc.app.llm.calls


@pytest.mark.asyncio()
async def test_export_clear_restore_preserves_other_spaces_and_never_replays_jobs(
    service: tuple[MuseService, Remote],
) -> None:
    svc, backend = service
    remote, other = bridge(svc), bridge(svc, "work")
    root, other_root = await remote.memory_root(), await other.memory_root()
    backend.files.update({root + "/fact.md": "Personal fact", other_root + "/fact.md": "Work fact"})
    backend.files[root + "/entities/nested.md"] = "Nested project fact"
    fact(remote.personal)
    fact(other.personal, "A work preference")
    assert svc.app.memory is not None
    svc.app.memory.add("A local fact")
    remote.enqueue("turn", [{"role": "user", "content": "Synthetic captured turn"}])
    LearningQueue(remote.personal).enqueue(["Unprocessed message"], "turn", "chat")
    archive = MemoryArchive(hub=svc.app.memory_hub)
    result = await archive.execute(action="export")
    assert result.ok
    backup = json.loads(result.output)
    assert backup["facts"] and backup["turns"] and backup["pending"] and backup["learning"]
    assert "api_key" not in result.output
    result = await archive.execute(action="clear", revision=backup["revision"])
    assert result.ok and not remote.capture_enabled
    assert not remote.personal.items(history=True) and svc.app.memory.count() == 0
    assert not remote.has_pending() and LearningQueue(remote.personal).status()["pending"] == 0
    assert root + "/fact.md" not in backend.files
    assert other.personal.items() and other_root + "/fact.md" in backend.files
    result = await archive.execute(action="restore", data=backup)
    assert result.ok and remote.personal.items() and svc.app.memory.count() == 1
    assert backend.files[root + "/fact.md"] == "Personal fact"
    assert backend.files[root + "/entities/nested.md"] == "Nested project fact"
    writes = [
        json.loads(r.content) for r in backend.calls if r.url.path.endswith("/content/batch-write")
    ]
    assert any(
        w["root_uri"] == root + "/entities"
        and w["operations"][0]["uri"] == root + "/entities/nested.md"
        for w in writes
    )
    assert not remote.has_pending() and LearningQueue(remote.personal).status()["pending"] == 0
    assert not remote.capture_enabled
    assert (await archive.execute(action="restore", data=backup)).ok
    assert len(remote.personal.items()) == 1


@pytest.mark.asyncio()
async def test_clear_refuses_stale_backup_and_unavailable_remote(
    service: tuple[MuseService, Remote],
) -> None:
    svc, backend = service
    remote = bridge(svc)
    fact(remote.personal)
    archive = MemoryArchive(hub=svc.app.memory_hub)
    backup = json.loads((await archive.execute(action="export")).output)
    item = remote.personal.items()[0]
    remote.personal.review(item["id"], item["version"], "edit", "Newer fact")
    result = await archive.execute(action="clear", revision=backup["revision"])
    assert not result.ok and result.error.startswith("409:")
    backend.available = False
    result = await archive.execute(action="clear", revision=backup["revision"])
    assert not result.ok and remote.personal.items() and remote.capture_enabled


@pytest.mark.asyncio()
async def test_restore_checks_owner_paths_checksum_and_newer_remote_content(
    service: tuple[MuseService, Remote],
) -> None:
    svc, backend = service
    remote = bridge(svc)
    root = await remote.memory_root()
    backend.files[root + "/fact.md"] = "Original fact"
    archive = MemoryArchive(hub=svc.app.memory_hub)
    backup = json.loads((await archive.execute(action="export")).output)
    wrong_owner = {**backup, "owner": "another-owner"}
    assert not (await archive.execute(action="restore", data=wrong_owner)).ok
    wrong_path = {**backup, "remote": [{"path": "../other.md", "content": "Untrusted"}]}
    wrong_path["revision"] = digest({k: v for k, v in wrong_path.items() if k != "revision"})
    assert not (await archive.execute(action="restore", data=wrong_path)).ok
    assert not (await archive.execute(action="restore", data={**backup, "capture": False})).ok
    backend.files[root + "/fact.md"] = "Newer fact"
    result = await archive.execute(action="restore", data=backup)
    assert not result.ok and result.error.startswith("409:")


def test_space_api_authentication_ownership_and_default_compatibility(
    service: tuple[MuseService, Remote],
) -> None:
    svc, _ = service
    svc.settings.server.token = "synthetic-spaces-token"
    svc.token = "synthetic-spaces-token"
    with TestClient(create_app(svc.settings, svc)) as client:
        assert client.get("/api/memory/spaces").status_code == 401
        client.headers["Authorization"] = "Bearer synthetic-spaces-token"
        assert client.get("/api/memory/spaces").json()["owner"] == bridge(svc).owner
        assert (
            client.post("/api/memory/spaces", json={"id": "../invalid", "label": "Bad"}).status_code
            == 422
        )
        assert (
            client.post(
                "/api/memory/spaces", json={"id": "project-a", "label": "Project A"}
            ).status_code
            == 200
        )
        generated = client.post("/api/memory/spaces", json={"label": "Generated project"})
        assert generated.status_code == 200
        assert generated.json()["id"].startswith("project-")
        assert any(
            space["id"] == generated.json()["id"]
            for space in client.get("/api/memory/spaces").json()["spaces"]
        )
        assert (
            client.post("/api/threads", json={"title": "Legacy client"}).json()["memory_space"]
            == "personal"
        )
        thread = client.post(
            "/api/threads", json={"title": "Project chat", "memory_space": "project-a"}
        ).json()
        assert thread["memory_space"] == "project-a"
        assert client.post("/api/threads", json={"memory_space": "missing"}).status_code == 400
        assert (
            client.post("/api/memory?space=work", json={"content": "Work note"}).status_code == 200
        )
        assert not client.get("/api/memory").json()
        assert client.get("/api/memory?space=work").json()[0]["content"] == "Work note"
        assert client.get("/api/memory?space=missing").status_code == 404
        svc.settings.sentinel.deny_tools = ["memory_archive"]
        assert (
            client.post("/api/memory/spaces", json={"id": "denied", "label": "Denied"}).status_code
            == 403
        )


@pytest.mark.asyncio()
async def test_cancellation_keeps_the_learning_job(service: tuple[MuseService, Remote]) -> None:
    svc, _ = service
    queue = LearningQueue(bridge(svc).personal)
    queue.enqueue(["A synthetic preference"], "turn", "chat")
    queue.enqueue(["A synthetic preference"], "turn", "chat")
    assert queue.status()["pending"] == 1

    class SlowLLM(MockLLM):
        async def ask(self, *args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(100)

    svc.app.llm = SlowLLM([])
    task = asyncio.create_task(svc.app.memory_hub.run_once())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert queue.status()["pending"] == 1


@pytest.mark.asyncio()
async def test_old_extraction_tasks_are_checked_even_outside_recent_status(
    service: tuple[MuseService, Remote],
) -> None:
    svc, backend = service
    remote = bridge(svc)
    backend.task_state = "running"
    sid = "nm-" + "a" * 40
    with remote.db:
        remote.db.execute(
            "INSERT INTO memory_tasks VALUES (?, ?, ?)",
            (remote.personal.namespace, sid, "old-task"),
        )
    archive = MemoryArchive(hub=svc.app.memory_hub)
    backup = json.loads((await archive.execute(action="export")).output)
    result = await archive.execute(action="clear", revision=backup["revision"])
    assert not result.ok and "extraction" in result.error and remote.capture_enabled
    backend.task_state = "completed"
    assert (await archive.execute(action="clear", revision=backup["revision"])).ok


@pytest.mark.asyncio()
async def test_backup_reads_do_not_publish_memory_change_events(
    service: tuple[MuseService, Remote],
) -> None:
    svc, _ = service
    events = []
    svc.app.memory_hub.changed = lambda: events.append(True)
    archive = MemoryArchive(hub=svc.app.memory_hub)
    assert (await archive.execute(action="status")).ok
    assert (await archive.execute(action="export")).ok
    assert not events


@pytest.mark.asyncio()
async def test_backups_refuse_active_chats_and_learning_pauses_while_busy(
    service: tuple[MuseService, Remote],
) -> None:
    svc, _ = service
    hub = svc.app.memory_hub
    hub.busy = lambda: True
    assert not await hub.run_once()
    assert not (await MemoryArchive(hub=hub).execute(action="export")).ok
    hub.archiving = True
    with pytest.raises(ValueError, match="progress"):
        await svc.send("main", "hello")


@pytest.mark.asyncio()
async def test_learning_queue_survives_connection_reopen(settings: Settings) -> None:
    path = settings.data_dir / "queue-reopen.db"
    first = OpenVikingMemory(settings.memory.openviking, path)
    LearningQueue(first.personal).enqueue(["User evidence"], "turn", "chat")
    await first.close()
    second = OpenVikingMemory(settings.memory.openviking, path)
    job = LearningQueue(second.personal).next()
    assert job is not None and job[1]["inputs"] == ["User evidence"]
    await second.close()


def test_disabling_openviking_keeps_scoped_threads_readable(
    service: tuple[MuseService, Remote],
) -> None:
    svc, _ = service
    thread = svc.create_thread("Work chat", "work")
    svc.settings.memory.openviking.enabled = False
    rebuilt = MuseService(svc.settings, llm=MockLLM([]))
    restored = rebuilt.threads[thread.id]
    assert restored.memory_space == "work" and restored.agent.memory is None
    assert restored.agent.openviking is None and "remember" not in restored.agent.tools


@pytest.mark.asyncio()
async def test_restore_keeps_newer_profile_corrections(service: tuple[MuseService, Remote]) -> None:
    svc, _ = service
    store = bridge(svc).personal
    fact(store)
    archive = MemoryArchive(hub=svc.app.memory_hub)
    backup = json.loads((await archive.execute(action="export")).output)
    item = store.items()[0]
    store.review(item["id"], item["version"], "edit", "A newer owner correction")
    assert (await archive.execute(action="restore", data=backup)).ok
    assert store.items()[0]["value"] == "A newer owner correction"


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "user_request",
    [
        "请把我的测试项目代号改成海盐-5831，并长期记住。",
        "Please remember that my synthetic fruit is Amber-5831.",
        "请忘掉我的测试项目代号。",
        "我的测试项目代号是什么？比较方案时我喜欢什么格式？",
        "我偏好的虚构水果叫什么？",
        "What is my project code?",
    ],
)
async def test_disabled_explicit_memory_requests_never_reach_model_or_tools(
    service: tuple[MuseService, Remote],
    user_request: str,
) -> None:
    svc, remote = service
    await svc.app.memory_hub.set_enabled("personal", False)
    agent = svc.create_thread("Disabled request").agent
    calls_before = len(svc.app.llm.calls), len(remote.calls)
    answer = await agent.run(user_request)
    assert "记忆已关闭" in answer or "memory is off" in answer
    assert (len(svc.app.llm.calls), len(remote.calls)) == calls_before
    assert not any(m.role.value == "tool" for m in agent.messages)
    svc.app.llm.script = [LLMResponse(content="Normal tasks still work")]
    assert await agent.run("Calculate 12 + 13") == "Normal tasks still work"
    svc.app.llm.script = [LLMResponse(content="Tests can still run")]
    assert await agent.run("Do not forget to run the tests") == "Tests can still run"


@pytest.mark.asyncio()
@pytest.mark.parametrize("space", ["personal", "work"])
@pytest.mark.parametrize("language", ["en", "zh-CN"])
async def test_excluded_write_ends_turn_without_capture_or_fallback_storage(
    service: tuple[MuseService, Remote], space: str, language: str
) -> None:
    svc, remote = service
    hub = svc.app.memory_hub
    hub.rules(space).add("4826")
    agent = svc.create_thread("Excluded write", space).agent
    external = bridge(svc, space)
    local = hub.local(space)
    assert local is not None
    agent.llm = MockLLM(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        function=Function(
                            name="remember",
                            arguments=json.dumps({"content": "My project is WILLOW-4826"}),
                        )
                    ),
                    ToolCall(
                        function=Function(
                            name="files",
                            arguments=json.dumps(
                                {"action": "write", "path": "fallback.txt", "content": "Willow"}
                            ),
                        )
                    ),
                ]
            ),
            LLMResponse(content="Should not reach the model again"),
        ]
    )
    answer = await agent.run("Remember my project is WILLOW-4826", language=language)
    assert ("查看停用规则" if language == "zh-CN" else "load the exclusions") in answer
    assert len(agent.llm.calls) == 1
    assert not local.all()
    assert not (agent.workspace / "fallback.txt").exists()
    assert agent._openviking_inputs is None and agent._personal_inputs is None
    assert not external.has_pending()
    assert not external.personal.items()
    assert LearningQueue(external.personal).status()["pending"] == 0
    assert all(
        request.method == "GET" or "/search/" in request.url.path for request in remote.calls
    )
    assert hub.rules(space).items() == [{"term": "4826", "replacement": ""}]
    assert not hub.rules("work" if space == "personal" else "personal").items()


@pytest.mark.asyncio()
@pytest.mark.parametrize("replacement", ["", "WILLOW-5831"])
async def test_fact_copies_reconcile_all_managed_stores_and_exclude_reintroduced_text(
    service: tuple[MuseService, Remote],
    replacement: str,
) -> None:
    from nanomuse.memory.facts import MemoryFacts

    svc, remote = service
    hub, external = svc.app.memory_hub, bridge(svc)
    local = hub.local()
    assert local is not None
    old = "CINDER-9274"
    saved = local.add(f"Synthetic project code is {old}")
    history_item = local.add(f"Historical code {old}")
    local.drop(history_item.id)
    fact(external.personal, f"My synthetic project code is {old}")
    other = bridge(svc, "work")
    fact(other.personal, f"My synthetic project code is {old}")
    work = hub.local("work")
    assert work is not None
    work.add(f"Work project code {old}")
    root = await external.memory_root()
    remote.files[root + "/fact.md"] = f"Project code {old}. Other fact stays when replacing."
    remote.files[root + "/unrelated.md"] = "Unrelated record"
    external.enqueue("turn", [{"role": "user", "content": f"Project code {old}"}])
    await external.flush()
    external.enqueue("pending", [{"role": "user", "content": f"Project code {old}"}])
    queue = LearningQueue(external.personal)
    queue.enqueue([f"Project code {old}"], "job", "conversation")
    tool = MemoryFacts(hub=hub)
    preview = await tool.execute(term=old, replacement=replacement)
    assert preview.ok
    data = json.loads(preview.output)
    assert {m["source"] for m in data["matches"]} == {
        "local",
        "facts",
        "remote",
        "turns",
        "pending",
        "learning",
        "history",
    }
    # Preview is read only, including its exclusion rules.
    assert local.get(saved.id) and not hub.rules().items()
    applied = await tool.execute(
        action="apply", term=old, replacement=replacement, revision=data["revision"]
    )
    assert applied.ok, applied.error
    assert not external.has_pending()
    assert queue.status()["pending"] == 0
    assert not local.history()
    assert not any(old in json.dumps(m) for m in external.personal.items(history=True))
    assert not any(old in json.dumps(m) for m in (await tool.state()).get("turns", []))
    assert not remote.sessions
    assert remote.files[root + "/unrelated.md"] == "Unrelated record"
    assert old in work.all()[0].content
    assert old in other.personal.items()[0]["value"]
    if replacement:
        assert replacement in local.get(saved.id).content
        assert replacement in remote.files[root + "/fact.md"]
        assert "Other fact stays" in remote.files[root + "/fact.md"]
        assert replacement in external.personal.context("project")["facts"][0]["value"]
        assert "Owner-confirmed current values" in svc.app.agent.build_system_prompt("code")
    else:
        assert local.get(saved.id) is None
        assert root + "/fact.md" not in remote.files
    # An old archive reprocessed by a different client cannot reintroduce this exact text.
    local.add(f"Reintroduced {old}")
    remote.files[root + "/reprocessed.md"] = f"Reintroduced {old}"
    assert old not in await external.recall("project")
    assert old not in svc.app.agent.build_system_prompt("project")
    assert old not in (await svc.app.agent.tools.execute("recall", {"query": "project"})).output
    assert not (
        await svc.app.agent.tools.execute("remember", {"content": f"Reintroduced {old}"})
    ).ok
    assert not (
        await svc.app.agent.tools.execute(
            "openviking_memory", {"action": "read", "uri": root + "/reprocessed.md"}
        )
    ).ok
    assert (
        old
        not in (await svc.app.agent.tools.execute("openviking_memory", {"action": "list"})).output
    )
    external.enqueue("retry", [{"role": "user", "content": f"Reintroduced {old}"}])
    assert not external.has_pending()
    proposal = Proposal(
        key="synthetic", kind="profile", value=f"Reintroduced {old}", quote=f"Reintroduced {old}"
    )
    assert not external.personal.apply(proposal, [proposal.quote], "retry", "chat")
    assert (await tool.execute(action="unblock", term=old)).ok
    assert old in (await svc.app.agent.tools.execute("recall", {"query": "Reintroduced"})).output


@pytest.mark.asyncio()
async def test_fact_reconciliation_rejects_stale_preview_busy_space_and_unfinished_extraction(
    service: tuple[MuseService, Remote],
) -> None:
    from nanomuse.memory.facts import MemoryFacts

    svc, remote = service
    hub, external = svc.app.memory_hub, bridge(svc)
    local = hub.local()
    assert local is not None
    local.add("Synthetic CINDER-9274")
    tool = MemoryFacts(hub=hub)
    first = json.loads((await tool.execute(term="CINDER-9274")).output)
    local.add("Changed after preview")
    result = await tool.execute(action="apply", term="CINDER-9274", revision=first["revision"])
    assert not result.ok and "409" in result.error
    assert not hub.rules().items()
    hub.space_busy = lambda _: True
    assert not (await tool.execute(term="CINDER-9274")).ok
    hub.space_busy = lambda _: False
    with external.db:
        external.db.execute(
            "INSERT INTO memory_tasks VALUES (?, ?, ?)",
            (external.personal.namespace, "nm-" + "a" * 40, "task-a"),
        )
    remote.task_state = "running"
    preview = json.loads((await tool.execute(term="CINDER-9274")).output)
    result = await tool.execute(action="apply", term="CINDER-9274", revision=preview["revision"])
    assert not result.ok and "extraction" in result.error
    assert not hub.rules().items() and local.count() == 2


def test_fact_copy_api_auth_denial_and_local_only_usage(settings: Settings) -> None:
    settings.server.auth = True
    settings.server.token = "synthetic-memory-controls"
    settings.memory.openviking.enabled = False
    svc = MuseService(settings, llm=MockLLM([]))
    headers = {"Authorization": "Bearer synthetic-memory-controls"}
    assert svc.app.memory is not None
    svc.app.memory.add("Synthetic CINDER-9274")
    with TestClient(create_app(settings, service=svc)) as client:
        route = "/api/memory/spaces/personal/facts"
        assert (
            client.post(route, json={"action": "preview", "term": "CINDER-9274"}).status_code == 401
        )
        assert (
            client.post(
                "/api/memory/spaces/unknown/facts", headers=headers, json={"action": "status"}
            ).status_code
            == 404
        )
        preview = client.post(
            route, headers=headers, json={"action": "preview", "term": "CINDER-9274"}
        )
        assert preview.status_code == 200 and len(preview.json()["matches"]) == 1
        svc.settings.sentinel.deny_tools.append("memory_facts")
        assert (
            client.post(
                route,
                headers=headers,
                json={
                    "action": "apply",
                    "term": "CINDER-9274",
                    "revision": preview.json()["revision"],
                },
            ).status_code
            == 403
        )
        svc.settings.sentinel.deny_tools.remove("memory_facts")
        applied = client.post(
            route,
            headers=headers,
            json={"action": "apply", "term": "CINDER-9274", "revision": preview.json()["revision"]},
        )
        assert applied.status_code == 200, applied.text
        assert svc.app.memory.count() == 0
        assert client.post(route, headers=headers, json={"action": "status"}).json()["rules"]


@pytest.mark.asyncio()
async def test_partial_remote_fact_failure_keeps_exclusion_and_retry_possible(
    service: tuple[MuseService, Remote],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nanomuse.memory.facts import MemoryFacts

    svc, remote = service
    hub, external = svc.app.memory_hub, bridge(svc)
    root = await external.memory_root()
    remote.files[root + "/fact.md"] = "Synthetic CINDER-9274"
    local = hub.local()
    assert local is not None
    local.add("Synthetic CINDER-9274")
    tool = MemoryFacts(hub=hub)
    preview = json.loads((await tool.execute(term="CINDER-9274")).output)
    original = external.change_memory

    async def fail(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise httpx.ConnectError("Synthetic remote interruption")

    monkeypatch.setattr(external, "change_memory", fail)
    result = await tool.execute(action="apply", term="CINDER-9274", revision=preview["revision"])
    assert not result.ok and "503" in result.error
    assert local.count() == 0
    assert remote.files[root + "/fact.md"]
    assert "CINDER-9274" not in await external.recall("synthetic")
    assert hub.rules().items() and not hub.archiving
    monkeypatch.setattr(external, "change_memory", original)
    again = json.loads((await tool.execute(term="CINDER-9274")).output)
    assert (await tool.execute(action="apply", term="CINDER-9274", revision=again["revision"])).ok
    assert not remote.files


@pytest.mark.asyncio()
async def test_exclusions_survive_restart_and_space_backup(
    service: tuple[MuseService, Remote],
) -> None:
    from nanomuse.memory.rules import MemoryRules

    svc, _ = service
    hub, external = svc.app.memory_hub, bridge(svc)
    hub.rules().add("CINDER-9274", "WILLOW-5831")
    archive = MemoryArchive(hub=hub)
    backup = await archive.snapshot(external)
    assert backup["rules"] == hub.rules().items()
    assert (await archive.execute(action="clear", revision=backup["revision"])).ok
    assert not hub.rules().items()
    assert (await archive.execute(action="restore", data=backup)).ok
    assert hub.rules().items() == backup["rules"]
    # A second handle reads the persisted rules without inheriting in-memory state.
    import sqlite3

    connection = sqlite3.connect(svc.settings.data_dir / "memory-usage.db")
    persisted = MemoryRules(connection, hub.owner, "personal")
    assert not persisted.allows("Returned cinder-9274")
    assert MemoryRules(connection, hub.owner, "work").allows("CINDER-9274")
    connection.close()


def test_fact_replacement_handles_unicode_casefold_and_literal_replacement() -> None:
    from nanomuse.memory.facts import contains, substitute

    assert contains("Straße and STRASSE", "strasse")
    assert substitute("Straße and STRASSE", "strasse", r"New\1") == r"New\1 and New\1"


@pytest.mark.asyncio()
async def test_quoted_fact_fragments_match_raw_records_and_block_remote_capture(
    service: tuple[MuseService, Remote],
) -> None:
    from nanomuse.memory.facts import MemoryFacts, contains

    svc, remote = service
    hub, external = svc.app.memory_hub, bridge(svc)
    old = 'Code "CINDER"\n9274'
    assert contains({"content": old}, old)
    assert not contains({old: "unrelated"}, old)
    local = hub.local()
    assert local is not None
    local.add(old)
    root = await external.memory_root()
    remote.files[root + "/quoted.md"] = old
    tool = MemoryFacts(hub=hub)
    preview = json.loads((await tool.execute(term=old)).output)
    assert {item["source"] for item in preview["matches"]} == {"local", "remote"}
    assert (await tool.execute(action="apply", term=old, revision=preview["revision"])).ok
    assert local.count() == 0 and not remote.files
    remote.files[root + "/returned.md"] = old
    assert json.loads(await external.recall("code")) == []
    assert not (
        await svc.app.agent.tools.execute(
            "openviking_memory", {"action": "read", "uri": root + "/returned.md"}
        )
    ).ok
    external.enqueue("quoted-turn", [{"role": "user", "content": old}])
    assert not external.has_pending()


@pytest.mark.asyncio()
async def test_retired_queued_turns_do_not_block_new_eligible_sync(
    service: tuple[MuseService, Remote],
) -> None:
    svc, remote = service
    external = bridge(svc)
    for index in range(3):
        external.enqueue(str(index), [{"role": "user", "content": "Old CINDER-9274"}])
    external.enqueue("current", [{"role": "user", "content": "Current WILLOW-5831"}])
    svc.app.memory_hub.rules().add("CINDER-9274", "WILLOW-5831")
    # A restore can enqueue old evidence while preserving an existing exclusion.
    await external.flush()
    await external.flush()
    assert not external.has_pending()
    assert len(remote.sessions) == 1
    assert "CINDER-9274" not in json.dumps(remote.session_messages)
    assert "WILLOW-5831" in json.dumps(remote.session_messages)


@pytest.mark.asyncio()
async def test_fact_aliases_and_profile_revisions_share_reviewed_identity(
    service: tuple[MuseService, Remote],
) -> None:
    from nanomuse.memory.facts import MemoryFacts

    svc, remote = service
    hub, external = svc.app.memory_hub, bridge(svc)
    fact(external.personal, "Synthetic CINDER-9274")
    first = external.personal.items()[0]
    # Keep an older version of the same field with different wording.
    external.personal._save(
        {
            **first,
            "id": "old-revision",
            "value": "Earlier wording",
            "status": "superseded",
            "evidence": [],
        }
    )
    external.personal._save(
        {
            **first,
            "id": "another-scope",
            "value": "Unrelated preference",
            "scope": ["coding"],
            "evidence": [],
        }
    )
    external.db.commit()
    root = await external.memory_root()
    remote.files[root + "/alias.md"] = "Synthetic Alternate Phrase"
    work = bridge(svc, "work")
    fact(work.personal, "Synthetic CINDER-9274")
    tool = MemoryFacts(hub=hub)
    args = {"term": "CINDER-9274", "aliases": ["Alternate Phrase"]}
    preview = json.loads((await tool.execute(**args)).output)
    assert {m["id"] for m in preview["matches"] if m["source"] == "facts"} == {
        first["id"],
        "old-revision",
    }
    assert any(m["linked"] for m in preview["matches"])
    # An alias edit requires inspection again, even if all records are unchanged.
    stale = await tool.execute(action="apply", term=args["term"], revision=preview["revision"])
    assert not stale.ok and "409" in stale.error
    applied = await tool.execute(action="apply", revision=preview["revision"], **args)
    assert applied.ok, applied.error
    assert [m["id"] for m in external.personal.items()] == ["another-scope"]
    assert not remote.files and work.personal.items()
    rules = hub.rules().items()
    assert {r["fact_id"] for r in rules} == {preview["fact_id"]}
    assert {r["term"] for r in rules} >= {"cinder-9274", "alternate phrase", "earlier wording"}
    assert json.loads(applied.output)["report"]["state"] == "completed"


@pytest.mark.asyncio()
async def test_partial_cleanup_report_survives_service_restart_and_retry(
    service: tuple[MuseService, Remote],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nanomuse.memory.facts import MemoryFacts

    svc, remote = service
    hub, external = svc.app.memory_hub, bridge(svc)
    local = hub.local()
    assert local is not None
    local.add("Synthetic CINDER-9274")
    root = await external.memory_root()
    remote.files[root + "/one.md"] = "Synthetic CINDER-9274"
    remote.files[root + "/two.md"] = "Synthetic CINDER-9274"
    original = external.change_memory
    count = 0

    async def fail_second(*a: Any, **kw: Any) -> dict[str, Any]:
        nonlocal count
        count += 1
        if count == 2:
            raise httpx.ConnectError("Synthetic interruption")
        return await original(*a, **kw)

    monkeypatch.setattr(external, "change_memory", fail_second)
    tool = MemoryFacts(hub=hub)
    preview = json.loads((await tool.execute(term="CINDER-9274")).output)
    result = await tool.execute(action="apply", term="CINDER-9274", revision=preview["revision"])
    assert not result.ok
    report = json.loads(result.output)["report"]
    assert report["state"] == "incomplete" and report["exclusions_active"]
    rows = {r["source"]: r for r in report["sources"]}
    assert rows["local"]["status"] == "completed" and rows["local"]["changed"] == 1
    assert rows["remote"]["status"] == "incomplete" and rows["remote"]["changed"] == 1
    rebuilt = MuseService(svc.settings, llm=MockLLM([]))
    recovered = MemoryFacts(hub=rebuilt.app.memory_hub)
    persisted = json.loads((await recovered.execute(action="status")).output)["report"]
    assert persisted == report
    preview = json.loads((await recovered.execute(term="CINDER-9274")).output)
    assert len(preview["matches"]) == 1
    assert preview["fact_id"] == report["fact_id"]
    assert (
        await recovered.execute(action="apply", term="CINDER-9274", revision=preview["revision"])
    ).ok
    assert not remote.files
    # Recover an operation interrupted between durable checkpoints.
    report["state"] = "in_progress"
    rebuilt.app.memory_hub.rules().save_report(report)
    status = json.loads((await recovered.execute(action="status")).output)["report"]
    assert status["state"] == "incomplete" and "interrupted" in status["error"]
