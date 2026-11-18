"""One runtime owner's memory spaces and supervised background learning."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from nanomuse.memory import MemoryStore
from nanomuse.memory.learning import LearningQueue
from nanomuse.memory.openviking import OpenVikingManage, OpenVikingMemory
from nanomuse.memory.personal import PersonalLearn
from nanomuse.memory.rules import MemoryRules
from nanomuse.schema import Function, RiskLevel, ToolCall, ToolResult
from nanomuse.sentinel import Sentinel
from nanomuse.tools import ToolCollection
from nanomuse.tools.base import BaseTool
from nanomuse.tools.files import Files
from nanomuse.tools.memory_tools import Forget, Recall, Remember
from nanomuse.tools.shell import PythonExecute, Shell
from nanomuse.ui import HeadlessUI
from nanomuse.workspaces import WorkspaceSandbox, space_directory

if TYPE_CHECKING:
    from nanomuse.agent import MuseAgent
    from nanomuse.app import NanoMuseApp

SPACE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


def can_learn(bridge: OpenVikingMemory, generation: int) -> bool:
    return (
        bridge.usage_allowed()
        and bridge.capture_enabled
        and generation == bridge.personal.generation()
    )


class MemoryHub:
    def __init__(self, app: NanoMuseApp):
        self.app = app
        self.default = app.openviking
        path = app.settings.data_dir / "memory-usage.db"
        self.usage_db = sqlite3.connect(path, check_same_thread=False)
        path.chmod(0o600)
        self.usage_db.execute(
            "CREATE TABLE IF NOT EXISTS memory_usage (owner TEXT, space TEXT, enabled INTEGER, "
            "PRIMARY KEY(owner, space))"
        )
        self.usage_db.commit()
        self.owner = self.default.owner if self.default is not None else "local"
        self.offline_spaces = [{"id": "personal", "label": "Personal"}]
        if self.default is None:
            self.load_offline_spaces()
        self.closed = False
        self._rules: dict[str, MemoryRules] = {}
        self.rules()
        self.bridges: dict[str, OpenVikingMemory] = {}
        self.locals: dict[str, MemoryStore] = {}
        self.workspace_tools: dict[str, tuple[Files, Shell, PythonExecute]] = {}
        self.task: asyncio.Task[None] | None = None
        self.busy: Callable[[], bool] = lambda: app.agent.state.value == "running"
        self.space_busy: Callable[[str], bool] = lambda space: (
            app.agent.memory_space == space and app.agent.state.value == "running"
        )
        self.changed: Callable[[], None] = lambda: None
        self.maintenance = asyncio.Lock()
        self.archiving = False
        if self.default is not None:
            self.default.strict_scope = True
            self.default.text_allowed = self.rules("personal").allows
            self.default.personal.text_allowed = self.rules("personal").allows
            self.default.usage_allowed = partial(self.is_enabled, "personal")
            self.bridges["personal"] = self.default
            db = self.default.db
            db.execute(
                "CREATE TABLE IF NOT EXISTS memory_spaces (owner TEXT, id TEXT, label TEXT, PRIMARY KEY(owner, id))"
            )
            with db:
                for space, label in (("personal", "Personal"), ("work", "Work")):
                    db.execute(
                        "INSERT OR IGNORE INTO memory_spaces VALUES (?, ?, ?)",
                        (self.default.owner, space, label),
                    )

    def rules(self, space: str = "personal") -> MemoryRules:
        if space not in self._rules:
            self._rules[space] = MemoryRules(self.usage_db, self.owner, space)
        return self._rules[space]

    def is_enabled(self, space: str = "personal") -> bool:
        if self.closed:
            return False
        row = self.usage_db.execute(
            "SELECT enabled FROM memory_usage WHERE owner = ? AND space = ?", (self.owner, space)
        ).fetchone()
        return self.app.settings.memory.enabled and (bool(row[0]) if row else True)

    async def set_enabled(self, space: str, enabled: bool) -> None:
        bridge = self.bridge(space)
        if enabled and not self.app.settings.memory.enabled:
            raise ValueError("409: Memory is disabled in the runtime configuration")
        if (
            self.maintenance.locked()
            or self.space_busy(space)
            or (bridge is not None and bridge.lock.locked())
        ):
            raise ValueError("409: Memory is busy. Finish or stop the conversation and try again.")
        async with self.maintenance:
            with self.usage_db:
                self.usage_db.execute(
                    "INSERT OR REPLACE INTO memory_usage VALUES (?, ?, ?)",
                    (self.owner, space, int(enabled)),
                )
        self.changed()

    def spaces(self) -> list[dict[str, str]]:
        if self.default is None:
            return self.offline_spaces
        return [
            {"id": row[0], "label": row[1]}
            for row in self.default.db.execute(
                "SELECT id, label FROM memory_spaces WHERE owner = ? ORDER BY rowid",
                (self.default.owner,),
            )
        ]

    def load_offline_spaces(self) -> None:
        """Keep existing file roots stable when remote memory is switched off."""
        path = self.app.settings.data_dir / "openviking-outbox.db"
        if not path.is_file():
            return
        cfg = self.app.settings.memory.openviking
        binding = hashlib.sha256(
            json.dumps([cfg.url, cfg.auth_mode, cfg.account, cfg.user]).encode()
        ).hexdigest()
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
            if not {"memory_owners", "memory_spaces"} <= tables:
                return
            row = db.execute(
                "SELECT owner FROM memory_owners WHERE binding = ?", (binding,)
            ).fetchone()
            owner = cfg.profile_id or (row[0] if row else None)
            if owner is None:
                return
            spaces = [
                {"id": row[0], "label": row[1]}
                for row in db.execute(
                    "SELECT id, label FROM memory_spaces WHERE owner = ? ORDER BY rowid", (owner,)
                )
            ]
            if spaces:
                self.owner, self.offline_spaces = owner, spaces
        finally:
            db.close()

    def create(self, space: str, label: str) -> None:
        if self.default is None:
            raise ValueError("OpenViking memory is not enabled")
        if not SPACE_RE.fullmatch(space) or not label.strip() or len(label) > 80:
            raise ValueError("Invalid memory space")
        if len(self.spaces()) >= 100:
            raise ValueError("Memory space limit reached")
        with self.default.db:
            self.default.db.execute(
                "INSERT OR IGNORE INTO memory_spaces VALUES (?, ?, ?)",
                (self.default.owner, space, label.strip()),
            )

    def bridge(self, space: str = "personal") -> OpenVikingMemory | None:
        if space not in {s["id"] for s in self.spaces()}:
            raise ValueError("Unknown memory space")
        if self.default is None:
            return None
        if space not in self.bridges:
            cfg = self.default.settings.model_copy(
                update={
                    "profile_id": self.default.owner,
                    "peer_id": "nmspace-"
                    + hashlib.sha256((self.default.owner + space).encode()).hexdigest()[:24],
                }
            )
            self.bridges[space] = OpenVikingMemory(
                cfg,
                self.default.path,
                api_key=self.default._api_key,
                transport=self.default._transport,
                space=space,
            )
            self.bridges[space].strict_scope = True
            self.bridges[space].text_allowed = self.rules(space).allows
            self.bridges[space].personal.text_allowed = self.rules(space).allows
            self.bridges[space].usage_allowed = partial(self.is_enabled, space)
        return self.bridges[space]

    def local(self, space: str = "personal") -> MemoryStore | None:
        if self.default is None and space != "personal":
            return None
        self.bridge(space)
        if space == "personal" or self.app.memory is None:
            if self.app.memory is not None:
                self.app.memory.text_allowed = self.rules(space).allows
            return self.app.memory
        if space not in self.locals:
            directory = (
                self.app.settings.data_dir
                / "memory-spaces"
                / str(self.default.owner if self.default else "")
            )
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / (space + ".db")
            self.locals[space] = MemoryStore(path)
            path.chmod(0o600)
        self.locals[space].text_allowed = self.rules(space).allows
        return self.locals[space]

    def bind(self, agent: MuseAgent, space: str) -> None:
        agent.openviking = (
            self.bridge(space) if self.default is not None or space == "personal" else None
        )
        agent.memory = self.local(space)
        agent.memory_hub = self
        agent.memory_space = space
        agent.workspace = self.workspace(space)
        if space not in self.workspace_tools:
            sandbox = (
                WorkspaceSandbox(
                    agent.workspace, self.app.settings.data_dir, outer=self.app.sandbox
                )
                if self.default is not None or len(self.spaces()) > 1
                else self.app.sandbox
            )
            self.workspace_tools[space] = (
                Files(
                    workspace=agent.workspace,
                    denied_roots=[self.app.settings.data_dir]
                    if space == "personal"
                    and self.app.settings.data_dir.resolve().is_relative_to(agent.workspace)
                    else [],
                ),
                Shell(workspace=agent.workspace, sandbox=sandbox),
                PythonExecute(workspace=agent.workspace, sandbox=sandbox),
            )
        excluded = {
            "files",
            "shell",
            "python_execute",
            "remember",
            "recall",
            "forget",
            "openviking_memory",
        }
        # External connectors and personal stores have no space contract. They stay
        # in Personal until a connector explicitly supports a separate identity.
        common = {"terminate", "ask_user", "web_search", "web_fetch"}
        agent.tools = ToolCollection(
            *(
                t
                for t in self.app.tools
                if t.name not in excluded and (space == "personal" or t.name in common)
            )
        )
        agent.tools.add(*self.workspace_tools[space])
        raw_shell = self.app.tools.get("shell")
        for tool in self.workspace_tools[space][1:]:
            tool.bridge = getattr(raw_shell, "bridge", None) if space == "personal" else None
        if agent.memory is not None:
            agent.tools.add(
                Remember(store=agent.memory, enabled=partial(self.is_enabled, space)),
                Recall(store=agent.memory, enabled=partial(self.is_enabled, space)),
                Forget(store=agent.memory, enabled=partial(self.is_enabled, space)),
            )
        if agent.openviking is not None:
            agent.tools.add(OpenVikingManage(bridge=agent.openviking, vault=self.app.vault))
        agent.goals = self.app.goals if space == "personal" else None
        agent.calendar = self.app.calendar if space == "personal" else None
        agent.contacts = self.app.contacts if space == "personal" else None
        agent.skills = self.app.skills if space == "personal" else None

    def workspace(self, space: str = "personal") -> Path:
        if not SPACE_RE.fullmatch(space):
            raise ValueError("Unknown memory space")
        self.bridge(space)
        if space == "personal":
            return self.app.settings.agent.workspace.resolve()
        return space_directory(self.app.settings.data_dir, self.owner, space)

    async def run_once(self) -> bool:
        if self.busy():
            return False
        async with self.maintenance:
            for space in self.spaces():
                bridge = self.bridge(space["id"])
                if bridge is None or not self.is_enabled(space["id"]):
                    continue
                queue = LearningQueue(bridge.personal)
                job = queue.next()
                if job is None or not bridge.capture_enabled or not bridge.settings.personalization:
                    continue
                job_id, payload, generation = job
                if generation != bridge.personal.generation():
                    queue.finish(job_id, True)
                    continue
                gate = Sentinel(
                    self.app.settings.sentinel, self.app.audit, HeadlessUI(), vault=self.app.vault
                )
                token = gate.begin_task(
                    "Learn personal profile", conversation=payload["conversation"]
                )
                try:
                    tool = PersonalLearn(
                        store=bridge.personal,
                        llm=self.app.llm,
                        base_url=getattr(
                            getattr(self.app.llm, "settings", None),
                            "base_url",
                            self.app.settings.llm.base_url,
                        )
                        or "",
                        timeout=bridge.settings.personalization_timeout,
                        vault=self.app.vault,
                        capture_allowed=partial(can_learn, bridge, generation),
                    )
                    call = ToolCall(
                        function=Function(name=tool.name, arguments=json.dumps(payload))
                    )
                    result = await gate.guard(call, tool)
                    queue.finish(job_id, result.ok)
                    self.changed()
                finally:
                    gate.end_task(token)
                return True
        return False

    async def _worker(self) -> None:
        while True:
            try:
                if await self.run_once():
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - durable job survives the worker failure
                pass
            await asyncio.sleep(1)

    def start(self) -> None:
        if self.task is None and self.default is not None:
            self.task = asyncio.create_task(self._worker(), name="personal-memory-learning")

    async def close(self) -> None:
        if self.closed:
            return
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        for space, bridge in self.bridges.items():
            if space != "personal":
                await bridge.close()
        for store in self.locals.values():
            store.close()
        self.usage_db.close()
        self.closed = True


class MemoryUsage(BaseTool):
    name: str = "memory_usage"
    description: str = "Enable or disable a memory space from authenticated memory controls"
    risk: RiskLevel = RiskLevel.SENSITIVE
    hub: MemoryHub
    space: str = "personal"

    async def execute(self, enabled: bool = False, **_: object) -> ToolResult:
        try:
            await self.hub.set_enabled(self.space, enabled)
            return ToolResult(output=json.dumps({"enabled": self.hub.is_enabled(self.space)}))
        except ValueError as exc:
            return ToolResult.fail(str(exc))
