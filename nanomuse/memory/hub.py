"""One runtime owner's memory spaces and supervised background learning."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING

from nanomuse.memory import MemoryStore
from nanomuse.memory.learning import LearningQueue
from nanomuse.memory.openviking import OpenVikingManage, OpenVikingMemory
from nanomuse.memory.personal import PersonalLearn
from nanomuse.schema import Function, ToolCall
from nanomuse.sentinel import Sentinel
from nanomuse.tools import ToolCollection
from nanomuse.tools.memory_tools import Forget, Recall, Remember
from nanomuse.ui import HeadlessUI

if TYPE_CHECKING:
    from nanomuse.agent import MuseAgent
    from nanomuse.app import NanoMuseApp

SPACE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


def can_learn(bridge: OpenVikingMemory, generation: int) -> bool:
    return bridge.capture_enabled and generation == bridge.personal.generation()


class MemoryHub:
    def __init__(self, app: NanoMuseApp):
        self.app = app
        self.default = app.openviking
        self.bridges: dict[str, OpenVikingMemory] = {}
        self.locals: dict[str, MemoryStore] = {}
        self.task: asyncio.Task[None] | None = None
        self.busy: Callable[[], bool] = lambda: app.agent.state.value == "running"
        self.changed: Callable[[], None] = lambda: None
        self.maintenance = asyncio.Lock()
        self.archiving = False
        if self.default is not None:
            self.default.strict_scope = True
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

    def spaces(self) -> list[dict[str, str]]:
        if self.default is None:
            return [{"id": "personal", "label": "Personal"}]
        return [
            {"id": row[0], "label": row[1]}
            for row in self.default.db.execute(
                "SELECT id, label FROM memory_spaces WHERE owner = ? ORDER BY rowid",
                (self.default.owner,),
            )
        ]

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
        return self.bridges[space]

    def local(self, space: str = "personal") -> MemoryStore | None:
        if self.default is None and space != "personal":
            return None
        self.bridge(space)
        if space == "personal" or self.app.memory is None:
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
        return self.locals[space]

    def bind(self, agent: MuseAgent, space: str) -> None:
        agent.openviking = (
            self.bridge(space) if self.default is not None or space == "personal" else None
        )
        agent.memory = self.local(space)
        agent.memory_hub = self
        agent.memory_space = space
        if space != "personal":
            # Retain live non-memory tool registration, but replace all memory
            # tools with space-bound instances before every turn.
            excluded = {"remember", "recall", "forget", "openviking_memory"}
            agent.tools = ToolCollection(*(t for t in self.app.tools if t.name not in excluded))
            if agent.memory is not None:
                agent.tools.add(
                    Remember(store=agent.memory),
                    Recall(store=agent.memory),
                    Forget(store=agent.memory),
                )
            if agent.openviking is not None:
                agent.tools.add(OpenVikingManage(bridge=agent.openviking, vault=self.app.vault))

    async def run_once(self) -> bool:
        if self.busy():
            return False
        async with self.maintenance:
            for space in self.spaces():
                bridge = self.bridge(space["id"])
                if bridge is None:
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
