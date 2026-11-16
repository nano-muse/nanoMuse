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
from nanomuse.memory.openviking import OpenVikingMemory
from nanomuse.memory.personal import PersonalMemory, Proposal
from nanomuse.schema import LLMResponse
from nanomuse.server import create_app
from nanomuse.server.service import MuseService


class Remote:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.sessions: set[str] = set()
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
            self.sessions.add(body["session_id"])
        elif path.startswith("/api/v1/sessions/") and request.method == "DELETE":
            sid = path.rsplit("/", 1)[1]
            if sid not in self.sessions:
                return httpx.Response(404)
            self.sessions.remove(sid)
        elif path.endswith("/messages") or path.endswith("/commit"):
            pass
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
