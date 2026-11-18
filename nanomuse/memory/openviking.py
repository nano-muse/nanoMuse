"""OpenViking HTTP memory and a durable, identity-scoped outbox.

The internal tools are called by the agent through the Sentinel, not exposed to
the model. Each completed turn has its own external session and commit. Local
explicit memories remain in MemoryStore and are not migrated or overwritten.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from nanomuse.config import OpenVikingSettings
from nanomuse.memory.personal import PersonalMemory
from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment
from nanomuse.vault import PLACEHOLDER_RE, CredentialVault


class OpenVikingMemory:
    def __init__(
        self,
        settings: OpenVikingSettings,
        path: Path,
        *,
        api_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        space: str = "personal",
    ):
        self.settings = settings
        self.path, self.space = path, space
        self._api_key, self._transport = api_key, transport
        self.strict_scope = False
        self.usage_allowed: Callable[[], bool] = lambda: True
        self.text_allowed: Callable[[Any], bool] = lambda text: True
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if settings.auth_mode == "trusted":
            if not settings.account or not settings.user:
                raise ValueError("OpenViking trusted mode requires account and user")
            headers["X-OpenViking-Account"] = settings.account
            headers["X-OpenViking-User"] = settings.user
        if settings.peer_id:
            headers["X-OpenViking-Actor-Peer"] = settings.peer_id
        self.client = httpx.AsyncClient(
            base_url=settings.url,
            headers=headers,
            timeout=settings.timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        # Changing a server, credential or identity must not replay private queued
        # conversations to the new destination. Only the digest is persisted.
        self.namespace = hashlib.sha256(
            json.dumps(
                [
                    settings.url,
                    api_key,
                    settings.auth_mode,
                    settings.account,
                    settings.user,
                    settings.peer_id,
                ]
            ).encode()
        ).hexdigest()
        path.parent.mkdir(parents=True, exist_ok=True)
        # The server constructs the app before starting its event-loop thread.
        # Transactions contain no awaits, as in the other runtime stores.
        self.db = sqlite3.connect(path, check_same_thread=False)
        path.chmod(0o600)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS pending ("
            "id TEXT PRIMARY KEY, namespace TEXT NOT NULL, messages TEXT NOT NULL, "
            "stage INTEGER NOT NULL DEFAULT -1)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS preferences (namespace TEXT PRIMARY KEY, capture INTEGER)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS commits (id TEXT PRIMARY KEY, namespace TEXT NOT NULL, "
            "task TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending')"
        )
        self.db.commit()
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS memory_tasks (profile TEXT, id TEXT, task TEXT, PRIMARY KEY(profile, id))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS memory_owners (binding TEXT PRIMARY KEY, owner TEXT NOT NULL)"
        )
        binding = hashlib.sha256(
            json.dumps([settings.url, settings.auth_mode, settings.account, settings.user]).encode()
        ).hexdigest()
        row = self.db.execute(
            "SELECT owner FROM memory_owners WHERE binding = ?", (binding,)
        ).fetchone()
        self.owner = settings.profile_id or (row[0] if row else uuid.uuid4().hex)
        if row is None:
            self.db.execute("INSERT INTO memory_owners VALUES (?, ?)", (binding, self.owner))
        profile = hashlib.sha256(
            json.dumps([self.owner, space, settings.peer_id]).encode()
        ).hexdigest()
        self.personal = PersonalMemory(self.db, profile)
        # Only migrate this exact connection's old profile. Queued outbound writes
        # retain their credential-bound namespace and are never retargeted.
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO memory_tasks SELECT ?, id, task FROM commits WHERE namespace = ?",
                (profile, self.namespace),
            )
            for table in ("personal_facts", "personal_rejections"):
                self.db.execute(
                    f"UPDATE OR IGNORE {table} SET namespace = ? WHERE namespace = ?",
                    (profile, self.namespace),
                )
            self.db.execute(
                "INSERT OR IGNORE INTO preferences SELECT ?, capture FROM preferences WHERE namespace = ?",
                (profile, self.namespace),
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS memory_turns (profile TEXT, id TEXT, messages TEXT, PRIMARY KEY(profile, id))"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS memory_destinations (profile TEXT, namespace TEXT, PRIMARY KEY(profile, namespace))"
            )
            self.db.execute(
                "INSERT OR IGNORE INTO memory_destinations VALUES (?, ?)", (profile, self.namespace)
            )
        self.lock = asyncio.Lock()
        self.edit_lock = asyncio.Lock()
        self._root: str | None = None

    @property
    def capture_enabled(self) -> bool:
        row = self.db.execute(
            "SELECT capture FROM preferences WHERE namespace = ?", (self.personal.namespace,)
        ).fetchone()
        return bool(row[0]) if row else self.settings.capture_conversations

    def set_capture(self, enabled: bool) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO preferences VALUES (?, ?)",
                (self.personal.namespace, int(enabled)),
            )

    def pending_count(self) -> int:
        return int(
            self.db.execute(
                "SELECT count(*) FROM pending WHERE namespace = ?", (self.namespace,)
            ).fetchone()[0]
        )

    async def memory_root(self) -> str:
        if self._root is None:
            result = (await self.request("GET", "/api/v1/system/status"))["result"]
            user = result.get("user", "")
            if not isinstance(user, str) or not re.fullmatch(r"[\w-]+", user):
                raise ValueError("OpenViking returned an invalid user identity")
            if self.settings.auth_mode == "trusted" and user != self.settings.user:
                raise ValueError("OpenViking did not accept the configured user identity")
            peer = self.settings.peer_id
            if peer and not re.fullmatch(r"[\w-]+", peer):
                raise ValueError("OpenViking peer identity is invalid")
            self._root = f"viking://user/{user}/" + (f"peers/{peer}/" if peer else "") + "memories"
        return self._root

    async def checked_uri(self, uri: str, *, file: bool = False) -> str:
        root = await self.memory_root()
        if not uri:
            uri = root
        if uri.startswith("viking://~/memories") and not self.settings.peer_id:
            uri = root + uri[len("viking://~/memories") :]
        if (
            (uri != root and not uri.startswith(root + "/"))
            or any(char in uri for char in ("%", "\\", "?", "#"))
            or any(ord(char) < 32 or ord(char) == 127 for char in uri)
            or any(part.startswith(".") or not part for part in uri[len(root) :].split("/")[1:])
            or (file and (uri == root or not uri.endswith(".md")))
        ):
            raise ValueError("Only visible memory files in the configured user's space are allowed")
        return uri

    async def browse(self, uri: str = "", query: str = "", offset: int = 0) -> dict[str, Any]:
        root = await self.memory_root()
        uri = await self.checked_uri(uri)
        if query:
            data = await self.request(
                "POST",
                "/api/v1/search/find",
                json={
                    "query": query[: self.settings.max_chars],
                    "target_uri": root,
                    "limit": 50,
                },
            )
            entries = data.get("result", {}).get("memories", [])
        else:
            try:
                data = await self.request(
                    "GET",
                    "/api/v1/fs/ls",
                    params={
                        "uri": uri,
                        "output": "original",
                        "include_abstract": True,
                        "limit": 50,
                        "offset": offset,
                    },
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404 or uri != root:
                    raise
                data = {"result": [], "has_more": False}
            entries = data.get("result", [])
        items = []
        for entry in entries:
            name = str(entry.get("name", ""))
            target = entry.get("uri") or (uri + "/" + name if name else "")
            if not isinstance(target, str) or not target:
                continue
            try:
                target = await self.checked_uri(target)
            except ValueError:
                continue
            directory = bool(entry.get("isDir", entry.get("is_dir", entry.get("is_leaf") is False)))
            if not directory and not target.endswith(".md"):
                continue
            items.append(
                {
                    "uri": target,
                    "name": target.rsplit("/", 1)[-1],
                    "directory": directory,
                    "abstract": str(entry.get("abstract") or "")[:2000],
                }
            )
        return {
            "root": root,
            "uri": uri,
            "items": items,
            "has_more": bool(data.get("has_more", False)) if not query else False,
            "offset": offset,
        }

    async def read_memory(self, uri: str) -> dict[str, str]:
        uri = await self.checked_uri(uri, file=True)
        data = await self.request("GET", "/api/v1/content/read", params={"uri": uri, "raw": True})
        raw = data.get("result")
        if not isinstance(raw, str) or len(raw) > 256_000:
            raise ValueError("OpenViking memory is too large or is not text")
        content = re.sub(r"\n*<!--\s*MEMORY_FIELDS\s*\n.*?\n-->\s*\Z", "", raw, flags=re.S)
        return {
            "uri": uri,
            "content": content,
            "revision": hashlib.sha256(raw.encode()).hexdigest(),
        }

    async def change_memory(
        self,
        action: str,
        uri: str,
        content: str,
        revision: str,
    ) -> dict[str, Any]:
        uri = await self.checked_uri(uri, file=True)
        if not re.fullmatch(r"[a-f0-9]{64}", revision):
            raise ValueError("Read the memory before changing it and provide its revision")
        async with self.edit_lock:
            current = await self.read_memory(uri)
            if current["revision"] != revision:
                return {"conflict": True}
            if action == "delete":
                await self.request(
                    "DELETE",
                    "/api/v1/fs",
                    params={
                        "uri": uri,
                        "recursive": False,
                        "wait": True,
                    },
                )
            else:
                if not content.strip() or len(content) > 32000 or "<!-- MEMORY_FIELDS" in content:
                    raise ValueError("Memory content must contain 1 to 32000 characters of text")
                await self.request(
                    "POST",
                    "/api/v1/content/batch-write",
                    json={
                        "root_uri": uri.rsplit("/", 1)[0],
                        "wait": True,
                        "operations": [
                            {
                                "uri": uri,
                                "mode": "replace",
                                "content": content,
                                "expected_sha256": revision,
                            }
                        ],
                    },
                )
        return {"ok": True, "uri": uri}

    async def status(self) -> dict[str, Any]:
        rows = self.db.execute(
            "SELECT id, task, state FROM commits WHERE namespace = ? ORDER BY rowid DESC LIMIT 20",
            (self.namespace,),
        ).fetchall()
        tasks = []
        for sid, task, state in rows:
            if state not in ("completed", "failed", "cancelled", "expired"):
                try:
                    result = await self.request("GET", f"/api/v1/tasks/{task}")
                    state = str(result["result"]["status"])
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        raise
                    state = "expired"
                with self.db:
                    self.db.execute("UPDATE commits SET state = ? WHERE id = ?", (state, sid))
            tasks.append({"state": state})
        return {
            "enabled": True,
            "usage_enabled": self.usage_allowed(),
            "capture": self.capture_enabled,
            "pending": self.pending_count(),
            "tasks": tasks,
        }

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get("status") == "error":
            raise ValueError("OpenViking returned an unsuccessful response")
        return data

    async def recall(self, query: str) -> str:
        """Budgeted historical evidence, never instructions to execute."""
        if not self.usage_allowed():
            return ""
        if self.strict_scope:
            data = await self.request(
                "POST",
                "/api/v1/search/find",
                json={
                    "query": query[: self.settings.max_chars],
                    "target_uri": await self.memory_root(),
                    "limit": 8,
                    "score_threshold": 0.35,
                },
            )
            entries = data.get("result", {}).get("memories", [])
            valid = []
            for entry in entries:
                try:
                    await self.checked_uri(entry.get("uri", ""), file=True)
                except ValueError:
                    continue
                if self.text_allowed(entry):
                    valid.append({"uri": entry["uri"], "text": entry.get("abstract", "")})
            return json.dumps(valid, ensure_ascii=False)[: self.settings.max_chars]
        payload: dict[str, Any] = {
            "query": query[: self.settings.max_chars],
            "mode": "context",
            "context_type": "memory",
            "max_tokens": max(64, self.settings.max_chars // 4),
            "rewrite": False,
        }
        try:
            data = await self.request("POST", "/api/v1/search/search", json=payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (400, 404, 422):
                raise
            data = await self.request(
                "POST",
                "/api/v1/search/find",
                json={
                    "query": payload["query"],
                    "target_uri": "viking://~/memories",
                    "limit": 8,
                    "score_threshold": 0.35,
                },
            )
        result = data.get("result") or {}
        rendered = result.get("rendered")
        if isinstance(rendered, str):
            return rendered[: self.settings.max_chars] if self.text_allowed(rendered) else ""
        entries = result.get("entries") or result.get("memories") or []
        lines = [
            {
                "uri": str(item.get("uri", "")),
                "text": str(item.get("text") or item.get("abstract") or ""),
            }
            for item in entries
            if isinstance(item, dict) and self.text_allowed(item)
        ]
        return json.dumps(lines, ensure_ascii=False)[: self.settings.max_chars] if lines else ""

    def enqueue(self, turn_id: str, messages: list[dict[str, str]]) -> None:
        if not self.usage_allowed() or not self.text_allowed(messages):
            return
        sid = "nm-" + hashlib.sha256(f"{self.namespace}:{turn_id}".encode()).hexdigest()[:40]
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO memory_turns VALUES (?, ?, ?)",
                (self.personal.namespace, sid, json.dumps(messages, ensure_ascii=False)),
            )
            self.db.execute(
                "INSERT OR IGNORE INTO pending (id, namespace, messages) VALUES (?, ?, ?)",
                (sid, self.namespace, json.dumps(messages, ensure_ascii=False)),
            )

    def has_pending(self) -> bool:
        return (
            self.db.execute(
                "SELECT 1 FROM pending WHERE namespace = ? LIMIT 1", (self.namespace,)
            ).fetchone()
            is not None
        )

    async def flush(self) -> int:
        """Advance acknowledged writes; ambiguous network failures may repeat a message."""
        if not self.usage_allowed():
            return 0
        count = 0
        async with asyncio.timeout(self.settings.timeout), self.lock:
            rows = self.db.execute(
                "SELECT id, messages, stage FROM pending WHERE namespace = ? "
                "ORDER BY rowid LIMIT 3",
                (self.namespace,),
            ).fetchall()
            for sid, raw, stage in rows:
                messages = json.loads(raw)
                if not self.text_allowed(messages):
                    # Restored queues can contain text retired by an existing review.
                    # Remove it so a full batch cannot hold newer eligible turns back.
                    with self.db:
                        self.db.execute(
                            "DELETE FROM pending WHERE namespace = ? AND id = ?",
                            (self.namespace, sid),
                        )
                    continue
                if stage < 0:
                    peer = bool(self.settings.peer_id)
                    try:
                        await self.request(
                            "POST",
                            "/api/v1/sessions",
                            json={
                                "session_id": sid,
                                "auto_commit_policy": None,
                                "memory_policy": {
                                    "self": {"enabled": not peer},
                                    "peer": {"enabled": peer},
                                },
                            },
                        )
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 409:
                            raise
                if self.settings.peer_id:
                    # Session routes deliberately ignore Actor-Peer headers. Require
                    # peer-only extraction, including after a restart or a 409 from
                    # an older session, before sending or committing any messages.
                    session = await self.request("GET", f"/api/v1/sessions/{sid}")
                    policy = session.get("result", {}).get("memory_policy")
                    if (
                        not isinstance(policy, dict)
                        or policy.get("self") != {"enabled": False}
                        or policy.get("peer") != {"enabled": True}
                    ):
                        raise ValueError("OpenViking session memory policy is not peer-only")
                if stage < 0:
                    stage = 0
                    self._advance(sid, stage)
                for idx in range(stage, len(messages)):
                    message = {k: v for k, v in messages[idx].items() if k != "peer_id"}
                    if self.settings.peer_id and message.get("role") == "user":
                        message["peer_id"] = self.settings.peer_id
                    await self.request(
                        "POST",
                        f"/api/v1/sessions/{sid}/messages",
                        json=message,
                    )
                    self._advance(sid, idx + 1)
                # Commit archives synchronously; extraction continues asynchronously.
                committed = await self.request(
                    "POST",
                    f"/api/v1/sessions/{sid}/commit",
                    json={"keep_recent_count": 0},
                )
                with self.db:
                    task = committed.get("result", {}).get("task_id")
                    if isinstance(task, str) and task:
                        self.db.execute(
                            "INSERT OR REPLACE INTO commits (id, namespace, task) VALUES (?, ?, ?)",
                            (sid, self.namespace, task),
                        )
                    if isinstance(task, str) and task:
                        self.db.execute(
                            "INSERT OR REPLACE INTO memory_tasks VALUES (?, ?, ?)",
                            (self.personal.namespace, sid, task),
                        )
                        self.db.execute(
                            "DELETE FROM commits WHERE namespace = ? AND id NOT IN "
                            "(SELECT id FROM commits WHERE namespace = ? "
                            "ORDER BY rowid DESC LIMIT 100)",
                            (self.namespace, self.namespace),
                        )
                    self.db.execute("DELETE FROM pending WHERE id = ?", (sid,))
                count += 1
        return count

    def _advance(self, sid: str, stage: int) -> None:
        with self.db:
            self.db.execute("UPDATE pending SET stage = ? WHERE id = ?", (stage, sid))

    async def close(self) -> None:
        await self.client.aclose()
        self.db.close()


class OpenVikingTool(BaseTool):
    """A configured destination, with honest outbound risk and ordinary policy checks."""

    model_config = {"arbitrary_types_allowed": True}
    bridge: OpenVikingMemory
    risk: RiskLevel = RiskLevel.MODERATE
    egress: bool = True

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        result = super().assess(args)
        result.egress_target = urlparse(self.bridge.settings.url).hostname
        result.egress_configured = True
        result.summary = self.description
        return result


class OpenVikingRecall(OpenVikingTool):
    name: str = "openviking_recall"
    description: str = "Recall context from the configured OpenViking memory service"
    reads_private_data: bool = True

    async def execute(self, query: str = "", **_: Any) -> ToolResult:
        if not self.bridge.usage_allowed():
            return ToolResult.fail("Memory is disabled for this space")
        try:
            async with asyncio.timeout(self.bridge.settings.timeout):
                return ToolResult(output=await self.bridge.recall(query))
        except (httpx.HTTPError, ValueError, TimeoutError):
            return ToolResult.fail("OpenViking recall unavailable; using local context")


class OpenVikingSync(OpenVikingTool):
    name: str = "openviking_sync"
    description: str = "Save completed conversation turns to the configured OpenViking service"

    async def execute(
        self, turn_id: str = "", messages: list[dict[str, str]] | None = None, **_: Any
    ) -> ToolResult:
        if not self.bridge.usage_allowed():
            return ToolResult.fail("Memory is disabled for this space")
        if turn_id and messages:
            self.bridge.enqueue(turn_id, messages)
        try:
            count = await self.bridge.flush()
            return ToolResult(output=f"OpenViking accepted {count} turn(s) for extraction")
        except (httpx.HTTPError, ValueError, TimeoutError):
            return ToolResult.fail("OpenViking sync unavailable; pending turns retained locally")


class OpenVikingManage(OpenVikingTool):
    name: str = "openviking_memory"
    description: str = (
        "Manage the configured user's OpenViking long-term memories. Browse or search to find "
        "URIs, then read a file before updating or deleting it with its revision. Remember saves "
        "a short durable fact only when the user explicitly asks. Update and delete require "
        "the user's request. Deletion removes the extracted file, not archived conversations."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "read", "update", "delete", "remember", "status"],
            },
            "uri": {"type": "string"},
            "query": {"type": "string"},
            "content": {"type": "string"},
            "revision": {"type": "string"},
        },
        "required": ["action"],
    }
    reads_private_data: bool = True
    vault: CredentialVault | None = None
    controls: bool = False

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        result = super().assess(args)
        if args.get("action") in ("update", "delete"):
            result.risk = RiskLevel.SENSITIVE
        result.summary = f"OpenViking: {args.get('action', 'list')}"
        return result

    async def execute(
        self,
        action: str = "list",
        uri: str = "",
        query: str = "",
        content: str = "",
        revision: str = "",
        offset: int = 0,
        capture: bool | None = None,
        **_: Any,
    ) -> ToolResult:
        if not self.controls and not self.bridge.usage_allowed():
            return ToolResult.fail("Memory is disabled for this space")
        try:
            async with asyncio.timeout(self.bridge.settings.timeout):
                if content:
                    if self.vault is not None:
                        content = self.vault.redact(content)
                    content = PLACEHOLDER_RE.sub("[VAULT_REFERENCE]", content)
                if not self.controls and content and not self.bridge.text_allowed(content):
                    return ToolResult.fail("This text was retired by the owner")
                if action == "list":
                    result = await self.bridge.browse(uri, query, max(0, min(int(offset), 100000)))
                elif action == "read":
                    result = await self.bridge.read_memory(uri)
                elif action in ("update", "delete"):
                    result = await self.bridge.change_memory(action, uri, content, revision)
                    if result.get("conflict"):
                        return ToolResult.fail(
                            "409: Memory changed. Reload it before saving or deleting."
                        )
                elif action == "status":
                    result = await self.bridge.status()
                elif action == "capture" and self.controls and isinstance(capture, bool):
                    self.bridge.set_capture(capture)
                    result = {"ok": True}
                elif action == "retry" and self.controls:
                    result = {"accepted": await self.bridge.flush()}
                elif action == "remember":
                    if not content.strip() or len(content) > self.bridge.settings.max_chars:
                        raise ValueError("Provide a short durable fact to remember")
                    self.bridge.enqueue(uuid.uuid4().hex, [{"role": "user", "content": content}])
                    result = {
                        "accepted": await self.bridge.flush(),
                        "pending": self.bridge.pending_count(),
                    }
                else:
                    raise ValueError("Unsupported OpenViking memory action")
                if not self.controls:
                    if action == "list":
                        result["items"] = [
                            item for item in result["items"] if self.bridge.text_allowed(item)
                        ]
                    elif action == "read" and not self.bridge.text_allowed(result):
                        return ToolResult.fail("This record contains text retired by the owner")
                return ToolResult(output=json.dumps(result, ensure_ascii=False))
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            return ToolResult.fail(f"{code}: OpenViking memory request failed")
        except ValueError as exc:
            return ToolResult.fail(f"400: {exc}")
        except (httpx.HTTPError, TimeoutError):
            return ToolResult.fail("503: OpenViking is unavailable. Try again later.")
