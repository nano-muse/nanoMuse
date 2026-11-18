from __future__ import annotations

import json
import shlex
import sys
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from test_memory_spaces import Remote

from nanomuse.config import Settings
from nanomuse.llm import MockLLM
from nanomuse.memory.openviking import OpenVikingMemory
from nanomuse.schema import Function, LLMResponse, ToolCall
from nanomuse.server import create_app
from nanomuse.server.service import MuseService
from nanomuse.workspaces import command_abi


@pytest.fixture()
def scoped(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> MuseService:
    cfg = settings.memory.openviking
    cfg.enabled, cfg.auth_mode, cfg.account, cfg.user = True, "trusted", "test-account", "test-user"
    settings.memory.embeddings = "off"
    settings.mcp.servers = []
    remote = Remote()
    monkeypatch.setattr(
        "nanomuse.app.OpenVikingMemory",
        lambda *a, **kw: OpenVikingMemory(*a, **kw, transport=httpx.MockTransport(remote.handle)),
    )
    svc = MuseService(settings, llm=MockLLM([]))
    svc.profile.proactivity = "off"
    return svc


@pytest.mark.asyncio()
async def test_files_spaces_traversal_symlinks_and_tool_registration(scoped: MuseService) -> None:
    hub = scoped.app.memory_hub
    personal, work = scoped.app.agent, scoped.create_thread("Work", "work").agent
    for agent, value in ((personal, "PERSONAL-FIXTURE"), (work, "WORK-FIXTURE")):
        assert (
            await agent.tools.execute(
                "files", {"action": "write", "path": "project.txt", "content": value}
            )
        ).ok
        assert (
            await agent.tools.execute("files", {"action": "read", "path": "project.txt"})
        ).output == value
    for agent, other in ((personal, work), (work, personal)):
        outside = other.workspace / "project.txt"
        assert not (await agent.tools.execute("files", {"action": "read", "path": str(outside)})).ok
        link = agent.workspace / "outside.txt"
        link.symlink_to(outside)
        assert not (
            await agent.tools.execute("files", {"action": "read", "path": "outside.txt"})
        ).ok
        assert "outside.txt" not in (await agent.tools.execute("files", {"action": "list"})).output
    assert not (
        await work.tools.execute(
            "files", {"action": "write", "path": "../escape.txt", "content": "no"}
        )
    ).ok
    assert "goals" not in work.tools and work.goals is None and work.skills is None
    assert personal.workspace == scoped.settings.agent.workspace.resolve()
    assert hub.workspace("work") == work.workspace


@pytest.mark.asyncio()
@pytest.mark.skipif(command_abi() < 3, reason="Linux Landlock ABI 3 is unavailable")
async def test_commands_cannot_read_other_space_or_data_even_indirectly(
    scoped: MuseService,
) -> None:
    personal, work = scoped.app.agent, scoped.create_thread("Work", "work").agent
    secret = scoped.settings.data_dir / "synthetic-private.txt"
    secret.write_text("PRIVATE-FIXTURE")
    for agent in (personal, work):
        agent.workspace.mkdir(parents=True, exist_ok=True)
        (agent.workspace / "own.txt").write_text("OWN-FIXTURE")
        shell = await agent.tools.execute(
            "shell", {"command": "cat own.txt; echo output > result.txt"}
        )
        assert shell.ok, shell.output
        python = await agent.tools.execute(
            "python_execute",
            {"code": "from pathlib import Path;print(Path('own.txt').read_text())"},
        )
        assert python.ok and "OWN-FIXTURE" in python.output, python.output
    for agent, outside in (
        (personal, work.workspace / "own.txt"),
        (work, personal.workspace / "own.txt"),
        (work, secret),
    ):
        for tool, args in (
            ("shell", {"command": "cat " + shlex.quote(str(outside))}),
            (
                "python_execute",
                {"code": f"from pathlib import Path;print(Path({str(outside)!r}).read_text())"},
            ),
            (
                "shell",
                {
                    "command": shlex.quote(sys.executable)
                    + " -c "
                    + shlex.quote(
                        f"import base64;print(open(base64.b64decode({__import__('base64').b64encode(str(outside).encode())!r})).read())"
                    )
                },
            ),
        ):
            result = await agent.tools.execute(tool, args)
            assert not result.ok and "FIXTURE" not in result.output, result.output


def test_upload_library_signed_paths_and_attachment_binding(scoped: MuseService) -> None:
    thread = scoped.create_thread("Work", "work")
    scoped.settings.server.auth = False
    with TestClient(
        create_app(scoped.settings, service=scoped),
        headers={"Authorization": "Bearer " + scoped.token},
    ) as client:
        personal = client.post("/api/files/upload?name=project.txt", content=b"PERSONAL-FIXTURE")
        work = client.post("/api/files/upload?name=project.txt&space=work", content=b"WORK-FIXTURE")
        assert personal.status_code == work.status_code == 200
        path = work.json()["path"]
        assert path.startswith("@spaces/work/")
        assert client.get("/api/files/" + path).text == "WORK-FIXTURE"
        listed = client.get("/api/files?space=work").json()
        assert [f["path"] for f in listed] == [path]
        assert all(not f["path"].startswith("@spaces/") for f in client.get("/api/files").json())
        with pytest.raises(ValueError, match="another space"):
            scoped.attachment(personal.json()["path"], "work")
        assert scoped.attachment(path, "work").path == path
        assert thread.agent.user_message("Look at this file", [scoped.attachment(path)]).content
        with pytest.raises(PermissionError, match="another space"):
            scoped.app.agent.user_message("Look at this file", [scoped.attachment(path)])


@pytest.mark.asyncio()
async def test_memory_off_tool_backstop_cannot_be_overridden_by_approval(
    scoped: MuseService,
) -> None:
    agent = scoped.app.agent
    scoped.settings.sentinel.always_allow_tools.append("files")
    await scoped.app.memory_hub.set_enabled("personal", False)
    llm: Any = scoped.app.llm
    call = ToolCall(
        function=Function(
            name="files",
            arguments=json.dumps(
                {"action": "write", "path": "remembered.txt", "content": "SHOULD-NOT-BE-SAVED"}
            ),
        )
    )
    llm.script = [LLMResponse(tool_calls=[call]), LLMResponse(content="Memory is disabled")]
    await agent.run("Let's keep this detail for another day")
    assert not (agent.workspace / "remembered.txt").exists()
    assert any("Sentinel blocked" in (m.content or "") for m in agent.messages)
    llm.script = [LLMResponse(tool_calls=[call]), LLMResponse(content="File created")]
    await agent.run("Create file remembered.txt for this task")
    assert (agent.workspace / "remembered.txt").read_text() == "SHOULD-NOT-BE-SAVED"


def test_scoped_files_persist_with_memory_backend_disabled(scoped: MuseService) -> None:
    hub = scoped.app.memory_hub
    thread = scoped.create_thread("Work", "work")
    root = thread.agent.workspace
    (root / "persisted.txt").write_text("WORK-FIXTURE")
    scoped.settings.memory.openviking.enabled = False
    rebuilt = MuseService(scoped.settings, llm=MockLLM([]))
    assert rebuilt.app.memory_hub.owner == hub.owner
    assert rebuilt.threads[thread.id].agent.workspace == root
    assert rebuilt.list_files(space="work")[0]["path"] == "@spaces/work/persisted.txt"
    with pytest.raises(ValueError, match="Unknown memory space"):
        rebuilt.workspace("unknown-space")


@pytest.mark.asyncio()
async def test_missing_command_backend_refuses_unconfined_execution(
    scoped: MuseService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanomuse.workspaces.command_abi", lambda: 0)
    agent = scoped.create_thread("Work", "work").agent
    result = await agent.tools.execute("shell", {"command": "echo unsafe > unconfined.txt"})
    assert not result.ok and "unavailable" in result.error
    assert not (agent.workspace / "unconfined.txt").exists()


def test_signed_file_link_is_bound_to_space(scoped: MuseService) -> None:
    from nanomuse.server import tickets

    scoped.save_upload("project.txt", b"PERSONAL-FIXTURE")
    scoped.save_upload("project.txt", b"WORK-FIXTURE", "work")
    path = "/api/files/" + scoped.list_files()[0]["path"]
    work_path = "/api/files/" + scoped.list_files(space="work")[0]["path"]
    expiry = tickets.expiry()
    signature = tickets.sign(scoped.token, path, expiry)
    query = {"exp": str(expiry), "sig": signature}
    with TestClient(create_app(scoped.settings, service=scoped)) as client:
        assert client.get(path, params=query).text == "PERSONAL-FIXTURE"
        assert client.get(work_path, params=query).status_code == 401
        assert client.get(path, params={**query, "space": "work"}).text == "PERSONAL-FIXTURE"


def test_personal_bridge_is_not_exposed_to_work_or_memory_off(scoped: MuseService) -> None:
    personal = scoped.create_thread("Personal").agent
    work = scoped.create_thread("Work", "work").agent
    assert personal.tools.get("shell").bridge is scoped.bridge
    assert work.tools.get("shell").bridge is None
    scoped.bridge.base_url = "http://127.0.0.1:12345"
    # Even an explicitly authorized code task cannot obtain an external-tool bridge
    # while memory is disabled, so a nested operation cannot bypass the restriction.
    with scoped.app.memory_hub.usage_db:
        scoped.app.memory_hub.usage_db.execute(
            "INSERT OR REPLACE INTO memory_usage VALUES (?, 'personal', 0)",
            (scoped.app.memory_hub.owner,),
        )
    assert scoped.bridge.env_for("synthetic", "shell", 10) is None


def test_attachment_image_retargeted_to_another_space_is_not_encoded(
    scoped: MuseService,
) -> None:
    from nanomuse.llm.vision import image_data_url

    personal = scoped.app.agent.workspace / "private.png"
    personal.write_bytes(b"PERSONAL-IMAGE-FIXTURE")
    work = scoped.create_thread("Work", "work").agent.workspace
    path = work / "attached.png"
    path.write_bytes(b"WORK-IMAGE-FIXTURE")
    attachment = scoped.attachment("@spaces/work/attached.png", "work")
    agent = scoped.create_thread("Work image", "work").agent
    message = agent.user_message("Read this image", [attachment])
    path.unlink()
    path.symlink_to(personal)
    assert message.images and image_data_url(message.images[0]) is None


@pytest.mark.asyncio()
async def test_default_personal_workspace_inside_data_remains_usable(settings: Settings) -> None:
    settings.agent.workspace = settings.data_dir / "workspace"
    settings.memory.embeddings = "off"
    settings.mcp.servers = []
    settings.ensure_dirs()
    svc = MuseService(settings, llm=MockLLM([]))
    result = await svc.app.agent.tools.execute(
        "files", {"action": "write", "path": "own.txt", "content": "OWN-FIXTURE"}
    )
    assert result.ok, result.error
    assert svc.resolve_workspace_path("own.txt").read_text() == "OWN-FIXTURE"
    uploaded = svc.save_upload("uploaded.txt", b"UPLOADED-FIXTURE")
    assert svc.attachment(uploaded.path).size == len(b"UPLOADED-FIXTURE")
    assert not (
        await svc.app.agent.tools.execute(
            "files", {"action": "read", "path": str(settings.data_dir / "server_token")}
        )
    ).ok


def test_upload_symlink_escape_returns_forbidden(scoped: MuseService) -> None:
    outside = scoped.settings.data_dir / "outside"
    outside.mkdir()
    (scoped.workspace("work") / "attachments").symlink_to(outside, target_is_directory=True)
    with TestClient(
        create_app(scoped.settings, service=scoped),
        headers={"Authorization": "Bearer " + scoped.token},
    ) as client:
        response = client.post("/api/files/upload?name=escape.txt&space=work", content=b"NO")
        assert response.status_code == 403
    assert not list(outside.iterdir())


@pytest.mark.asyncio()
async def test_single_space_keeps_configured_command_backend(settings: Settings) -> None:
    settings.memory.embeddings = "off"
    settings.mcp.servers = []
    settings.sandbox.mode = "off"
    svc = MuseService(settings, llm=MockLLM([]))
    assert svc.app.agent.tools.get("python_execute").sandbox is svc.app.sandbox
    result = await svc.app.agent.tools.execute(
        "python_execute", {"code": "print('COMPUTE-FIXTURE')"}
    )
    assert result.ok and "COMPUTE-FIXTURE" in result.output


@pytest.mark.parametrize(
    "task",
    [
        "我的测试项目叫 Synthetic River，以后按这个来",
        "My test project code is Synthetic River",
        "My favorite report format uses tables",
        "以后写报告都先给结论",
        "Let's keep my project code for another day",
    ],
)
def test_memory_off_nouns_do_not_authorize_storage(task: str) -> None:
    from nanomuse.memory.access import restriction

    assert restriction("files", task, memory_off=True)
    assert restriction("shell", task, memory_off=True)


@pytest.mark.parametrize(
    "task",
    [
        "请运行测试",
        "帮我修改 README.md",
        "读取工作区文件",
        "测试一下这个接口",
        "Create file remembered.txt for this task",
        "Please run the tests",
        "Read report.txt",
    ],
)
def test_memory_off_explicit_current_file_and_code_tasks_are_allowed(task: str) -> None:
    from nanomuse.memory.access import restriction

    assert restriction("files", task, memory_off=True) is None
