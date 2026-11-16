"""Explicit, version-checked backup and deletion of a runtime's managed memory.

Chat timelines and audit logs have separate lifecycles. Remote session deletion
is limited to session IDs recorded by this runtime, never another application's.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from nanomuse.memory.hub import MemoryHub
from nanomuse.memory.learning import LearningQueue
from nanomuse.memory.openviking import OpenVikingMemory
from nanomuse.memory.personal import Proposal, utc_now
from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment


class SavedFact(BaseModel):
    key: str
    kind: Literal["profile", "preference", "project", "state", "experience"]
    value: str = Field(min_length=1, max_length=500)
    scope: list[str] = Field(default_factory=list, max_length=4)
    status: Literal["active", "candidate", "expired", "rejected", "superseded"]
    confidence: Literal["explicit", "inferred", "confirmed"]
    expires_at: datetime | None = None


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class MemoryArchive(BaseTool):
    name: str = "memory_archive"
    description: str = "Manage runtime memory spaces, backups and explicit restoration"
    risk: RiskLevel = RiskLevel.MODERATE
    reads_private_data: bool = True
    hub: MemoryHub
    space: str = "personal"

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        result = super().assess(args)
        action = args.get("action", "status")
        if action in ("clear", "restore"):
            result.risk = RiskLevel.SENSITIVE
        bridge = self.hub.bridge(self.space)
        if bridge is not None and action in ("export", "clear", "restore"):
            result.egress = True
            result.egress_target = urlparse(bridge.settings.url).hostname
            result.egress_configured = True
        return result

    def namespaces(self, bridge: OpenVikingMemory) -> list[str]:
        return [
            r[0]
            for r in bridge.db.execute(
                "SELECT namespace FROM memory_destinations WHERE profile = ?",
                (bridge.personal.namespace,),
            )
        ]

    async def snapshot(self, bridge: OpenVikingMemory) -> dict[str, Any]:
        root = await bridge.memory_root()
        files, paths = [], [root]
        # Fail closed rather than export an incomplete tree or clear unseen files.
        visited: set[str] = set()
        while paths:
            path = paths.pop()
            if path in visited:
                raise ValueError("409: Remote memory directory repeated")
            visited.add(path)
            offset = 0
            while True:
                page = await bridge.browse(path, offset=offset)
                for entry in page["items"]:
                    if entry["directory"]:
                        paths.append(entry["uri"])
                    else:
                        document = await bridge.read_memory(entry["uri"])
                        if len(document["content"]) > 32000:
                            raise ValueError(
                                "409: Remote memory exceeds the restorable 32000-character limit"
                            )
                        document["path"] = document["uri"][len(root) + 1 :]
                        files.append(document)
                if len(files) + len(visited) + len(paths) > 1000:
                    raise ValueError("409: Memory backup exceeds 1000 entries")
                if not page["has_more"]:
                    break
                if not page["items"]:
                    raise ValueError("409: Remote memory pagination did not advance")
                offset += 50
        db, namespace = bridge.db, bridge.personal.namespace
        facts = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT payload FROM personal_facts WHERE namespace = ? ORDER BY id", (namespace,)
            )
        ]
        rejections = [
            r[0]
            for r in db.execute(
                "SELECT digest FROM personal_rejections WHERE namespace = ? ORDER BY digest",
                (namespace,),
            )
        ]
        turns = [
            {"id": r[0], "messages": json.loads(r[1])}
            for r in db.execute(
                "SELECT id, messages FROM memory_turns WHERE profile = ? ORDER BY id", (namespace,)
            )
        ]
        pending, sessions = [], {t["id"] for t in turns}
        sessions.update(
            r[0] for r in db.execute("SELECT id FROM memory_tasks WHERE profile = ?", (namespace,))
        )
        for destination in self.namespaces(bridge):
            for sid, messages, stage in db.execute(
                "SELECT id, messages, stage FROM pending WHERE namespace = ? ORDER BY id",
                (destination,),
            ):
                pending.append({"id": sid, "messages": json.loads(messages), "stage": stage})
                sessions.add(sid)
            sessions.update(
                r[0]
                for r in db.execute("SELECT id FROM commits WHERE namespace = ?", (destination,))
            )
        LearningQueue(bridge.personal)
        learning = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT payload FROM learning_jobs WHERE namespace = ? ORDER BY id", (namespace,)
            )
        ]
        local = self.hub.local(self.space)
        result = {
            "format": 1,
            "owner": bridge.owner,
            "space": self.space,
            "facts": facts,
            "rejections": rejections,
            "local": [m.__dict__ for m in local.all()] if local else [],
            "remote": sorted(files, key=lambda f: f["path"]),
            "turns": turns,
            "session_ids": sorted(sessions),
            "pending": pending,
            "learning": learning,
            "capture": bridge.capture_enabled,
            "generation": bridge.personal.generation(),
        }
        if len(json.dumps(result).encode()) > 10_000_000:
            raise ValueError("409: Memory backup exceeds 10 MB")
        return {**result, "revision": digest(result)}

    async def clear(self, bridge: OpenVikingMemory, revision: str) -> dict[str, Any]:
        before = await self.snapshot(bridge)
        if not revision or before["revision"] != revision:
            raise ValueError("409: Memory changed. Export a new backup before clearing.")
        status = await bridge.status()
        if any(
            t["state"] in ("pending", "running", "cancelling", "unknown") for t in status["tasks"]
        ):
            raise ValueError("409: Wait for remote extraction before clearing memory.")
        for (task,) in bridge.db.execute(
            "SELECT task FROM memory_tasks WHERE profile = ?", (bridge.personal.namespace,)
        ):
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task):
                raise ValueError("409: Invalid remote extraction task")
            task_data = await bridge.request("GET", f"/api/v1/tasks/{task}")
            state = task_data.get("result", {}).get("status")
            if state not in ("completed", "done", "succeeded", "failed", "cancelled"):
                raise ValueError("409: Wait for remote extraction before clearing memory.")
        # Disable capture and invalidate queued extraction before remote mutations.
        bridge.set_capture(False)
        with bridge.db:
            bridge.personal.invalidate_learning()
        for sid in before["session_ids"]:
            if not re.fullmatch(r"nm-[a-f0-9]{40}", sid):
                raise ValueError("409: Invalid managed session identity")
            try:
                await bridge.request("DELETE", f"/api/v1/sessions/{sid}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
        for file in before["remote"]:
            result = await bridge.change_memory("delete", file["uri"], "", file["revision"])
            if result.get("conflict"):
                raise ValueError("409: Remote memory changed during deletion. Export again.")
        with bridge.db:
            for table in ("personal_facts", "personal_rejections", "learning_jobs"):
                bridge.db.execute(
                    f"DELETE FROM {table} WHERE namespace = ?", (bridge.personal.namespace,)
                )
            bridge.db.execute(
                "DELETE FROM memory_turns WHERE profile = ?", (bridge.personal.namespace,)
            )
            bridge.db.execute(
                "DELETE FROM memory_tasks WHERE profile = ?", (bridge.personal.namespace,)
            )
            for namespace in self.namespaces(bridge):
                bridge.db.execute("DELETE FROM pending WHERE namespace = ?", (namespace,))
                bridge.db.execute("DELETE FROM commits WHERE namespace = ?", (namespace,))
        local = self.hub.local(self.space)
        if local:
            local.erase()
        return {
            "ok": True,
            "capture": False,
            "remote_files": len(before["remote"]),
            "sessions": len(before["session_ids"]),
        }

    async def restore(self, bridge: OpenVikingMemory, data: dict[str, Any]) -> dict[str, Any]:
        if (
            data.get("format") != 1
            or data.get("owner") != bridge.owner
            or data.get("space") != self.space
        ):
            raise ValueError("400: Backup belongs to another owner or memory space")
        if len(json.dumps(data).encode()) > 10_000_000:
            raise ValueError("400: Memory backup exceeds 10 MB")
        if digest({k: v for k, v in data.items() if k != "revision"}) != data.get("revision"):
            raise ValueError("400: Memory backup checksum does not match")
        if any(
            not isinstance(data.get(field, []), list)
            for field in ("facts", "remote", "local", "rejections")
        ):
            raise ValueError("400: Invalid memory backup structure")
        facts = [SavedFact.model_validate(f) for f in data.get("facts", [])]
        for fact in facts:
            checked = Proposal(
                key=fact.key,
                kind=fact.kind,
                value=fact.value,
                scope=fact.scope,
                quote="Restored by owner",
            )
            fact.scope = checked.scope
            if fact.expires_at is not None and fact.expires_at.tzinfo is None:
                raise ValueError("400: Backup expiry requires a time zone")
        root = await bridge.memory_root()
        remote = []
        for file in data.get("remote", []):
            uri = root + "/" + file["path"]
            await bridge.checked_uri(uri, file=True)
            content = file["content"]
            if not isinstance(content, str) or not content.strip() or len(content) > 32000:
                raise ValueError("400: Backup remote text is too large or empty")
            try:
                current = await bridge.read_memory(uri)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                remote.append({"uri": uri, "content": content, "mode": "create", "if_absent": True})
            else:
                if current["content"] != content:
                    raise ValueError("409: Restoring would overwrite newer remote memory")
        local = self.hub.local(self.space)
        local_items = data.get("local", [])
        for item in local_items:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("content"), str)
                or not 1 <= len(item["content"]) <= 32000
            ):
                raise ValueError("400: Invalid local memory in backup")
        if remote:
            # OpenViking requires the batch root inside a memory type directory,
            # such as memories/entities, rather than at memories itself.
            groups: dict[str, list[dict[str, Any]]] = {}
            for operation in remote:
                parent = operation["uri"].rsplit("/", 1)[0]
                groups.setdefault(parent, []).append(operation)
            for parent, operations in groups.items():
                try:
                    await bridge.request("GET", "/api/v1/fs/stat", params={"uri": parent})
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        raise
                    await bridge.request("POST", "/api/v1/fs/mkdir", json={"uri": parent})
                await bridge.request(
                    "POST",
                    "/api/v1/content/batch-write",
                    json={"root_uri": parent, "wait": True, "operations": operations},
                )
        existing = [
            json.loads(row[0])
            for row in bridge.db.execute(
                "SELECT payload FROM personal_facts WHERE namespace = ?",
                (bridge.personal.namespace,),
            )
        ]
        protected = {(m["kind"], m["key"], tuple(m["scope"])) for m in bridge.personal.items()}
        with bridge.db:
            bridge.personal.invalidate_learning()
            for fact in facts:
                topic = hashlib.sha256(
                    json.dumps([fact.kind, fact.key, sorted(fact.scope)]).encode()
                ).hexdigest()
                # Restore is idempotent and never replaces a topic changed since backup.
                if (
                    fact.status in ("active", "candidate")
                    and (fact.kind, fact.key, tuple(fact.scope)) in protected
                ):
                    continue
                if any(
                    m["kind"] == fact.kind
                    and m["key"] == fact.key
                    and m["scope"] == fact.scope
                    and m["value"] == fact.value
                    and m["status"] == fact.status
                    for m in existing
                ):
                    continue
                now = utc_now().isoformat()
                bridge.personal._save(
                    {
                        **fact.model_dump(mode="json"),
                        "expires_at": fact.expires_at.astimezone(UTC).isoformat()
                        if fact.expires_at
                        else None,
                        "id": uuid.uuid4().hex,
                        "topic": topic,
                        "version": 1,
                        "created_at": now,
                        "updated_at": now,
                        "evidence": [
                            {
                                "quote": fact.value,
                                "turn": "",
                                "conversation": "backup-restore",
                                "at": now,
                            }
                        ],
                    }
                )
            for rejection in data.get("rejections", []):
                if isinstance(rejection, str) and re.fullmatch(r"[a-f0-9]{64}", rejection):
                    bridge.db.execute(
                        "INSERT OR IGNORE INTO personal_rejections VALUES (?, ?)",
                        (bridge.personal.namespace, rejection),
                    )
        if local:
            for item in local_items:
                local.add(item["content"], str(item.get("category", "general"))[:80], source="user")
        return {"ok": True, "remote_files": len(remote), "facts": len(facts)}

    async def execute(
        self,
        action: str = "status",
        label: str = "",
        new_space: str = "",
        revision: str = "",
        data: dict[str, Any] | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            bridge = self.hub.bridge(self.space)
            if action == "status":
                result: Any = {
                    "owner": bridge.owner if bridge else "",
                    "spaces": self.hub.spaces(),
                    "learning": LearningQueue(bridge.personal).status()
                    if bridge
                    else {"pending": 0, "failed": 0},
                }
            elif action == "create":
                self.hub.create(new_space, label)
                result = {"id": new_space, "spaces": self.hub.spaces()}
            elif bridge is None:
                raise ValueError("409: OpenViking memory is not enabled")
            elif action == "retry":
                LearningQueue(bridge.personal).retry()
                result = {"ok": True}
            else:
                if self.hub.busy():
                    raise ValueError("409: Wait for active conversations before managing backups.")
                async with self.hub.maintenance, asyncio.timeout(60):
                    if self.hub.busy():
                        raise ValueError(
                            "409: Wait for active conversations before managing backups."
                        )
                    self.hub.archiving = True
                    try:
                        if action == "export":
                            result = await self.snapshot(bridge)
                        elif action == "clear":
                            result = await self.clear(bridge, revision)
                        elif action == "restore":
                            result = await self.restore(bridge, data or {})
                        else:
                            raise ValueError("400: Unsupported memory archive action")
                    finally:
                        self.hub.archiving = False
            if action in ("create", "retry", "clear", "restore"):
                self.hub.changed()
            return ToolResult(output=json.dumps(result, ensure_ascii=False))
        except (ValueError, KeyError, TypeError) as exc:
            return ToolResult.fail(str(exc))
        except (httpx.HTTPError, TimeoutError):
            return ToolResult.fail(
                "503: Remote memory operation failed; capture may remain off. Export again before retrying."
            )
