"""Preview and reconcile literal fact copies in one owner's selected space."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import Field

from nanomuse.memory.archive import MemoryArchive, digest
from nanomuse.memory.hub import MemoryHub
from nanomuse.memory.personal import utc_now
from nanomuse.memory.rules import contains_text
from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment


def contains(value: Any, term: str) -> bool:
    return contains_text(value, term)


def substitute(text: str, term: str, replacement: str) -> str:
    # Keep replacement and discovery consistent even when case folding expands a
    # character, for example "Straße" matching "STRASSE".
    folded = text.casefold()
    needle = term.casefold()
    positions = [i for i, char in enumerate(text) for _ in char.casefold()]
    parts: list[str] = []
    cursor, offset = 0, 0
    while (index := folded.find(needle, offset)) >= 0:
        start, end = positions[index], positions[index + len(needle) - 1] + 1
        if start >= cursor:
            parts.extend((text[cursor:start], replacement))
            cursor = end
        offset = index + len(needle)
    parts.append(text[cursor:])
    return "".join(parts)


class MemoryFacts(BaseTool):
    name: str = "memory_facts"
    description: str = "Preview and reconcile copies of a fact in one memory space"
    risk: RiskLevel = RiskLevel.MODERATE
    reads_private_data: bool = True
    hub: MemoryHub
    space: str = "personal"
    aliases: list[str] = Field(default_factory=list)
    linked_fields: set[str] = Field(default_factory=set)
    report: dict[str, Any] = Field(default_factory=dict)

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        result = super().assess(args)
        bridge = self.hub.bridge(self.space)
        if bridge is not None and args.get("action") in ("preview", "apply"):
            result.egress = True
            result.egress_target = urlparse(bridge.settings.url).hostname
            result.egress_configured = True
        if args.get("action") in ("apply", "unblock"):
            result.risk = RiskLevel.SENSITIVE
        return result

    async def state(self) -> dict[str, Any]:
        bridge = self.hub.bridge(self.space)
        if bridge is not None:
            state = await MemoryArchive(hub=self.hub, space=self.space).snapshot(bridge)
            state.pop("revision", None)
        else:
            local = self.hub.local(self.space)
            state = {"local": [m.__dict__ for m in local.all(1001)] if local else []}
        local = self.hub.local(self.space)
        if len(state["local"]) > 1000 or (local is not None and local.count() > 1000):
            raise ValueError("409: Fact inspection exceeds 1000 local memories")
        history = [c.to_dict() for c in local.history(1001)] if local else []
        if len(history) > 1000:
            raise ValueError("409: Fact inspection exceeds 1000 history entries")
        state["history"] = history
        state["rules"] = self.hub.rules(self.space).items()
        if len(json.dumps(state).encode()) > 10_000_000:
            raise ValueError("409: Fact inspection exceeds 10 MB")
        return state

    @staticmethod
    def field_id(item: dict[str, Any]) -> str:
        return digest({k: item.get(k) for k in ("key", "kind", "scope")})

    def selected(self, item: Any, term: str, source: str = "") -> bool:
        return any(contains(item, value) for value in [term, *self.aliases]) or (
            source == "facts" and self.field_id(item) in self.linked_fields
        )

    def replace(self, text: str, term: str, replacement: str) -> str:
        for value in sorted([term, *self.aliases], key=len, reverse=True):
            text = substitute(text, value, replacement)
        return text

    def matches(self, state: dict[str, Any], term: str, replacement: str) -> list[dict[str, Any]]:
        self.linked_fields = {
            self.field_id(item) for item in state.get("facts", []) if self.selected(item, term)
        }
        entries = []
        for source, text_key, id_key in (
            ("local", "content", "id"),
            ("facts", "value", "id"),
            ("remote", "content", "uri"),
            ("turns", "messages", "id"),
            ("pending", "messages", "id"),
            ("learning", "inputs", "turn"),
            ("history", "before", "id"),
        ):
            for item in state.get(source, []):
                if not self.selected(item, term, source):
                    continue
                text = item if source in ("facts", "history") else item.get(text_key, item)
                before = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
                editable = source in ("local", "remote") or (
                    source == "facts" and item["status"] == "active"
                )
                if source == "facts" and editable:
                    before = item["value"]
                after = self.replace(before, term, replacement) if replacement and editable else ""
                if source == "facts" and editable and replacement and after == before:
                    after = replacement
                entries.append(
                    {
                        "source": source,
                        "id": str(item.get(id_key, "")),
                        "before": before,
                        "after": after,
                        "linked": source == "facts"
                        and not any(contains(item, t) for t in [term, *self.aliases]),
                    }
                )
        return entries

    def start_report(
        self, state: dict[str, Any], matches: list[dict[str, Any]], fact_id: str
    ) -> None:
        configured = self.hub.bridge(self.space) is not None
        self.report = {
            "id": uuid.uuid4().hex,
            "at": utc_now().isoformat(),
            "space": self.space,
            "fact_id": fact_id,
            "state": "preview",
            "exclusions_active": False,
            "sources": [
                {
                    "source": source,
                    "scanned": len(state.get(source, [])),
                    "matched": sum(m["source"] == source for m in matches),
                    "changed": 0,
                    "status": "checked"
                    if configured or source in ("local", "history")
                    else "not_configured",
                }
                for source in (
                    "local",
                    "facts",
                    "remote",
                    "turns",
                    "pending",
                    "learning",
                    "history",
                )
            ],
            "outside_scope": [
                "chat_history",
                "audit_logs",
                "untracked_archives",
                "workspace_files",
            ],
        }

    def checkpoint(self, sources: tuple[str, ...] = ()) -> None:
        for row in self.report["sources"]:
            if row["source"] in sources:
                row.update(status="completed", changed=row["matched"])
        self.hub.rules(self.space).save_report(self.report)

    async def reconcile(self, state: dict[str, Any], term: str, replacement: str) -> dict[str, Any]:
        bridge, local = self.hub.bridge(self.space), self.hub.local(self.space)
        matches = self.matches(state, term, replacement)
        # Validate all replacement sizes before changing any store.
        for item in matches:
            maximum = 500 if item["source"] == "facts" else 32000
            if len(item["after"]) > maximum:
                raise ValueError("400: Replacement makes a memory too large")
        if bridge is not None:
            for (task,) in bridge.db.execute(
                "SELECT task FROM memory_tasks WHERE profile = ?", (bridge.personal.namespace,)
            ).fetchall():
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task):
                    raise ValueError("409: Invalid remote extraction task")
                try:
                    data = await bridge.request("GET", f"/api/v1/tasks/{task}")
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        continue
                    raise
                if data.get("result", {}).get("status") not in (
                    "completed",
                    "done",
                    "succeeded",
                    "failed",
                    "cancelled",
                ):
                    raise ValueError("409: Wait for remote extraction before changing facts")
        # Persist the exclusion first. A partial network failure must not revive old facts.
        retired = {term, *self.aliases}
        retired.update(
            item["value"] for item in state.get("facts", []) if self.selected(item, term, "facts")
        )
        for value in retired:
            if replacement and contains(replacement, value):
                raise ValueError("400: Replacement must not contain the retired fragment")
        for value in retired:
            if 3 <= len(value) <= 500:
                self.hub.rules(self.space).add(value, replacement, self.report["fact_id"])
        self.report["exclusions_active"] = True
        self.checkpoint()
        if local is not None:
            for item in state["local"]:
                if self.selected(item, term):
                    if replacement:
                        local.update(item["id"], self.replace(item["content"], term, replacement))
                    else:
                        local.forget(item["id"])
                    with local._conn:
                        local._conn.execute(
                            "DELETE FROM memory_vectors WHERE memory_id = ?", (item["id"],)
                        )
            with local._conn:
                for item in state["history"]:
                    if self.selected(item, term):
                        local._conn.execute("DELETE FROM memory_log WHERE id = ?", (item["id"],))
        self.checkpoint(("local", "history"))
        if bridge is not None:
            db, namespace = bridge.db, bridge.personal.namespace
            with db:
                bridge.personal.invalidate_learning()
                for item in state["facts"]:
                    if not self.selected(item, term, "facts"):
                        continue
                    db.execute(
                        "DELETE FROM personal_facts WHERE namespace = ? AND id = ?",
                        (namespace, item["id"]),
                    )
                    if replacement and item["status"] == "active":
                        value = self.replace(item["value"], term, replacement)
                        if value == item["value"]:
                            value = replacement
                        now = utc_now().isoformat()
                        bridge.personal._save(
                            {
                                **item,
                                "id": uuid.uuid4().hex,
                                "value": value,
                                "confidence": "confirmed",
                                "version": 1,
                                "updated_at": now,
                                "evidence": [
                                    {
                                        "quote": value,
                                        "turn": "",
                                        "conversation": "fact-controls",
                                        "at": now,
                                    }
                                ],
                            }
                        )
                for job, payload in db.execute(
                    "SELECT id, payload FROM learning_jobs WHERE namespace = ?", (namespace,)
                ).fetchall():
                    if self.selected(json.loads(payload), term):
                        db.execute(
                            "DELETE FROM learning_jobs WHERE id = ? AND namespace = ?",
                            (job, namespace),
                        )
            self.checkpoint(("facts", "learning"))
            sessions = {
                t["id"]
                for field in ("turns", "pending")
                for t in state[field]
                if self.selected(t, term)
            }
            for sid in sorted(sessions):
                if not re.fullmatch(r"nm-[a-f0-9]{40}", sid):
                    raise ValueError("409: Invalid managed session identity")
                try:
                    await bridge.request("DELETE", f"/api/v1/sessions/{sid}")
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        raise
                with db:
                    db.execute(
                        "DELETE FROM memory_turns WHERE profile = ? AND id = ?", (namespace, sid)
                    )
                    db.execute(
                        "DELETE FROM memory_tasks WHERE profile = ? AND id = ?", (namespace, sid)
                    )
                    for destination in MemoryArchive(hub=self.hub, space=self.space).namespaces(
                        bridge
                    ):
                        for table in ("pending", "commits"):
                            db.execute(
                                f"DELETE FROM {table} WHERE namespace = ? AND id = ?",
                                (destination, sid),
                            )
                for row in self.report["sources"]:
                    if row["source"] in ("turns", "pending"):
                        row["changed"] += sum(
                            item["id"] == sid and self.selected(item, term)
                            for item in state[row["source"]]
                        )
                self.checkpoint()
            self.checkpoint(("turns", "pending"))
            for file in state["remote"]:
                if not self.selected(file, term):
                    continue
                content = self.replace(file["content"], term, replacement) if replacement else ""
                result = await bridge.change_memory(
                    "update" if content else "delete", file["uri"], content, file["revision"]
                )
                if result.get("conflict"):
                    raise ValueError(
                        "409: A remote copy changed. Inspect again. The exclusion remains active."
                    )
                row = next(row for row in self.report["sources"] if row["source"] == "remote")
                row["changed"] += 1
                self.checkpoint()
            self.checkpoint(("remote",))
        self.report["state"] = "completed"
        self.checkpoint()
        return {
            "ok": True,
            "changed": len(matches),
            "rules": self.hub.rules(self.space).items(),
            "report": self.report,
        }

    async def execute(
        self,
        action: str = "preview",
        term: str = "",
        replacement: str = "",
        revision: str = "",
        aliases: list[str] | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            self.hub.bridge(self.space)
            if action == "status":
                report = self.hub.rules(self.space).last_report()
                if report and report["state"] == "in_progress" and not self.hub.archiving:
                    self.report = report
                    self.failed_report("Operation was interrupted. Inspect remaining copies.")
                    report = self.report
                return ToolResult(
                    output=json.dumps(
                        {
                            "rules": self.hub.rules(self.space).items(),
                            "report": report,
                        }
                    )
                )
            self.aliases = list(dict.fromkeys(value.strip() for value in aliases or []))
            if len(self.aliases) > 20 or any(not 3 <= len(value) <= 500 for value in self.aliases):
                raise ValueError("400: Provide at most 20 aliases of 3 to 500 characters")
            term, replacement = term.strip(), replacement.strip()
            if not 3 <= len(term) <= 500 or len(replacement) > 500:
                raise ValueError("400: Provide an exact fragment of 3 to 500 characters")
            if replacement and any(contains(replacement, t) for t in [term, *self.aliases]):
                raise ValueError("400: Replacement must not contain the retired fragment")
            if replacement and not self.hub.rules(self.space).allows(replacement):
                raise ValueError("400: Replacement contains another retired fragment")
            if action not in ("preview", "apply", "unblock"):
                raise ValueError("400: Unsupported fact action")
            if self.hub.busy() or self.hub.space_busy(self.space):
                raise ValueError("409: Finish or stop conversations before changing facts")
            bridge = self.hub.bridge(self.space)
            if bridge is not None and bridge.lock.locked():
                raise ValueError("409: Wait for remote synchronization before changing facts")
            async with self.hub.maintenance, asyncio.timeout(60):
                if self.hub.busy() or self.hub.space_busy(self.space):
                    raise ValueError("409: Finish or stop conversations before changing facts")
                self.hub.archiving = True
                try:
                    if action == "unblock":
                        self.hub.rules(self.space).remove(term)
                        result: dict[str, Any] = {"rules": self.hub.rules(self.space).items()}
                    else:
                        state = await self.state()
                        expected = digest(
                            {
                                "space": self.space,
                                "state": state,
                                "term": term,
                                "replacement": replacement,
                                "aliases": self.aliases,
                            }
                        )
                        matches = self.matches(state, term, replacement)
                        known = {r["term"]: r.get("fact_id", "") for r in state["rules"]}
                        fact_id = next(
                            (
                                known[value.casefold()]
                                for value in [term, *self.aliases]
                                if known.get(value.casefold())
                            ),
                            digest({"space": self.space, "term": term.casefold()}),
                        )
                        self.start_report(state, matches, fact_id)
                        if action == "preview":
                            result = {
                                "revision": expected,
                                "matches": matches,
                                "report": self.report,
                                "fact_id": fact_id,
                            }
                        else:
                            if not revision or revision != expected:
                                raise ValueError(
                                    "409: Memory changed. Inspect copies again before applying."
                                )
                            self.report["state"] = "in_progress"
                            self.checkpoint()
                            result = await self.reconcile(state, term, replacement)
                finally:
                    self.hub.archiving = False
            if action in ("apply", "unblock"):
                self.hub.changed()
            return ToolResult(output=json.dumps(result, ensure_ascii=False))
        except (ValueError, TypeError, KeyError) as exc:
            self.failed_report(str(exc))
            return ToolResult(output=json.dumps({"report": self.report}), error=str(exc))
        except (httpx.HTTPError, TimeoutError):
            error = "503: Some remote changes may be incomplete. Inspect again; saved exclusions remain active."
            self.failed_report(error)
            return ToolResult(output=json.dumps({"report": self.report}), error=error)

    def failed_report(self, error: str) -> None:
        if not self.report or self.report["state"] != "in_progress":
            return
        self.report.update(state="incomplete", error=error.split(": ", 1)[-1])
        for row in self.report["sources"]:
            if row["status"] == "checked":
                row["status"] = "incomplete"
        self.checkpoint()
