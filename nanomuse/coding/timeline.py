"""Structured coding history shared by the hub's read-only detail actions.

The apply_patch conversion is adapted from Remodex's apply-patch-changes.js,
Copyright 2025-2026 Emanuele Di Pietro, Apache-2.0. nanoMuse modifications:
provider-neutral records, unknown line counts, bounded output and stable identities.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

TEXT_LIMIT = 262_144


def obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            str(v.get("text") or "")
            for v in value
            if isinstance(v, dict)
            and v.get("text")
            and v.get("type") in ("text", "input_text", "output_text")
        )
    return ""


def arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            return obj(json.loads(value))
        except ValueError:
            return {"raw": value}
    return obj(value)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]


def patch_files(patch: str) -> list[dict[str, Any]]:
    """Retain the actual patch body; absent hunk positions/counts stay unknown."""
    files: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    body: list[str] = []

    def flush() -> None:
        if not current:
            return
        current["diff"] = "\n".join(body)
        if current["action"] != "delete":
            current["additions"] = sum(line.startswith("+") for line in body)
            current["deletions"] = sum(line.startswith("-") for line in body)
        files.append(dict(current))

    for line in patch.splitlines():
        match = re.match(r"^\*\*\* (Add|Update|Delete) File: (.+)$", line)
        if match:
            flush()
            current = {
                "path": match[2],
                "action": {"Add": "add", "Update": "edit", "Delete": "delete"}[match[1]],
            }
            body = []
        elif line.startswith("*** Move to: ") and current:
            current["old_path"] = current["path"]
            current["path"] = line[13:]
            current["action"] = "rename"
        elif line == "*** End Patch":
            break
        elif not line.startswith("***") and current:
            body.append(line)
    flush()
    return files


class Timeline:
    """Fold provider history or exec events into stable, item-scoped records."""

    def __init__(self, clean: Callable[[str], str] = str.strip):
        self.clean = clean
        self.items: dict[str, dict[str, Any]] = {}
        self.turn = ""
        self.index = 0
        self.last_user = ""

    def put(self, key: str, **fields: Any) -> dict[str, Any]:
        previous = self.items.get(key)
        item = previous or {
            "id": key,
            "turn_id": self.turn,
            "sequence": self.index,
            "revision": 0,
            "role": "system",
            "kind": "tool",
            "text": "",
            "status": "completed",
        }
        item.update(fields)
        item["revision"] += 1
        self.items[key] = item
        return item

    def message(self, role: str, content: Any, key: str) -> None:
        value = text(content)
        value = self.clean(value) if role == "user" else value.strip()
        if not value or (role == "user" and value.startswith("<")):
            return
        if role == "user":
            self.turn = key
            self.last_user = key
        self.put(key, role=role, kind="message", text=value[:TEXT_LIMIT])

    def call(self, key: str, name: str, raw: Any, status: str = "running") -> None:
        args = arguments(raw)
        command = args.get("command") or args.get("cmd")
        kind = "command" if command else "tool"
        fields: dict[str, Any] = {
            "kind": kind,
            "text": name,
            "name": name,
            "input": json.dumps(args, ensure_ascii=False)[:TEXT_LIMIT],
            "status": status,
        }
        if command:
            fields["command"] = {
                "display_command": command if isinstance(command, str) else json.dumps(command),
                "cwd": str(args.get("workdir") or args.get("cwd") or ""),
            }
        patch = (
            raw
            if isinstance(raw, str)
            and raw.lstrip().startswith("*** Begin Patch")
            and name.endswith("apply_patch")
            else args.get("patch")
        )
        if isinstance(patch, str):
            files = patch_files(patch)
            if files:
                fields.update(kind="file_change", files=files, diff_scope="item")
        if name in ("Edit", "Write") and args.get("file_path"):
            old = args.get("old_string")
            new = args.get("new_string") if name == "Edit" else args.get("content")
            if isinstance(new, str):
                lines = ["@@"]
                if isinstance(old, str):
                    lines += ["-" + line for line in old.splitlines()]
                lines += ["+" + line for line in new.splitlines()]
                file: dict[str, Any] = {
                    "path": args["file_path"],
                    "action": "edit",
                    "diff": "\n".join(lines),
                }
                # Write does not record the previous file, so deletion count is unknown.
                if isinstance(old, str) and not args.get("replace_all"):
                    file["additions"] = len(new.splitlines())
                    file["deletions"] = len(old.splitlines())
                fields.update(kind="file_change", files=[file], diff_scope="item")
        self.put(key, **fields)

    def result(self, key: str, raw: Any, failed: bool = False) -> None:
        output = text(raw)
        if not output:
            output = json.dumps(raw, ensure_ascii=False) if raw is not None else ""
        item = self.put(key, output=output[:TEXT_LIMIT], status="failed" if failed else "completed")
        item["truncated"] = len(output) > TEXT_LIMIT
        metadata = arguments(raw)
        command = item.get("command")
        if isinstance(command, dict):
            for target, source in (("exit_code", "exit_code"), ("duration_ms", "duration_ms")):
                if isinstance(metadata.get(source), (int, float)):
                    command[target] = metadata[source]
            # Codex rollout outputs often prefix the body with terminal metadata.
            exit_match = re.search(r"Process exited with code (-?\d+)", output)
            duration_match = re.search(r"Wall time: ([\d.]+) seconds", output)
            if exit_match:
                command["exit_code"] = int(exit_match[1])
            if duration_match:
                command["duration_ms"] = round(float(duration_match[1]) * 1000)
            if command.get("exit_code", 0) != 0:
                item["status"] = "failed"

    def feed(self, agent: str, row: dict[str, Any]) -> None:
        self.index += 1
        kind = str(row.get("type") or "")
        payload = obj(row.get("payload"))
        fallback = f"line-{self.index}"
        if kind in ("turn_context", "event_msg"):
            tid = payload.get("turn_id")
            if tid:
                self.turn = str(tid)
            if payload.get("type") in ("task_complete", "turn_aborted"):
                self.turn = ""
        if agent == "codex" and kind == "response_item":
            key = str(payload.get("call_id") or payload.get("id") or fallback)
            ptype = payload.get("type")
            if ptype == "message" and payload.get("role") in ("user", "assistant"):
                self.message(str(payload["role"]), payload.get("content"), key)
            elif ptype in ("function_call", "custom_tool_call"):
                self.call(
                    key,
                    str(payload.get("name") or "tool"),
                    payload.get("arguments", payload.get("input")),
                )
            elif ptype in ("function_call_output", "custom_tool_call_output"):
                self.result(key, payload.get("output"))
            return
        if agent == "codex" and kind.startswith("item."):
            item = obj(row.get("item"))
            key = str(item.get("id") or fallback)
            phase = (
                "running" if kind != "item.completed" else str(item.get("status") or "completed")
            )
            itype = item.get("type")
            if itype == "agent_message":
                self.message("assistant", item.get("text"), key)
            elif itype == "command_execution":
                self.call(
                    key, "command", {"command": item.get("command"), "cwd": item.get("cwd")}, phase
                )
                if "aggregated_output" in item:
                    self.result(key, item["aggregated_output"])
                    self.items[key]["status"] = phase
                for field in ("exit_code", "duration_ms"):
                    if isinstance(item.get(field), (int, float)):
                        self.items[key]["command"][field] = item[field]
                if item.get("exit_code", 0) not in (0, None):
                    self.items[key]["status"] = "failed"
            elif itype == "file_change":
                files = [
                    {**obj(f), "action": obj(f).get("kind", "edit")}
                    for f in item.get("changes", [])
                    if isinstance(f, dict)
                ]
                self.put(key, kind="file_change", files=files, diff_scope="item", status=phase)
            elif itype in ("mcp_tool_call", "web_search"):
                self.call(key, str(item.get("tool") or itype), item.get("arguments", item), phase)
                if item.get("result") is not None:
                    self.result(key, item["result"], bool(item.get("error")))
            return
        if agent in ("claude", "cursor") and (
            row.get("role") in ("user", "assistant") or kind in ("user", "assistant")
        ):
            if row.get("isMeta"):
                return
            if agent == "cursor" and row.get("timestamp_ms") is not None:
                return
            role = str(row.get("role") or kind)
            msg = obj(row.get("message"))
            key = str(row.get("uuid") or msg.get("id") or fallback)
            content = msg.get("content")
            self.message(role, content, key)
            for i, block in enumerate(content if isinstance(content, list) else []):
                b = obj(block)
                bid = str(b.get("id") or b.get("tool_use_id") or f"{key}-{i}")
                if b.get("type") == "tool_use":
                    self.call(bid, str(b.get("name") or "tool"), b.get("input"))
                elif b.get("type") == "tool_result":
                    self.result(bid, b.get("content"), bool(b.get("is_error")))
            return
        if agent == "cursor" and kind == "tool_call":
            call = obj(row.get("tool_call"))
            name = next(iter(call), "tool")
            value = obj(call.get(name))
            key = str(row.get("call_id") or row.get("id") or value.get("id") or fallback)
            if key == fallback and row.get("subtype") == "completed":
                key = next(
                    (
                        i["id"]
                        for i in reversed(self.values())
                        if i.get("name") == name and i.get("status") == "running"
                    ),
                    key,
                )
            self.call(key, name, value.get("args", value), "running")
            if row.get("subtype") == "completed":
                self.result(key, value.get("result"))
            return
        if agent == "dsh":
            data = obj(row.get("data")) or row
            key = str(data.get("id") or data.get("callId") or fallback)
            if kind == "user/message" and obj(data.get("source")).get("kind") == "user":
                self.message("user", data.get("content"), key)
            elif kind == "assistant/message":
                self.message("assistant", obj(data.get("message")).get("content"), key)
            elif kind == "tool/call":
                self.call(
                    key,
                    str(data.get("name") or data.get("tool") or "tool"),
                    data.get("arguments", data.get("args")),
                )
            elif kind == "tool/result":
                self.result(
                    key, data.get("result", data.get("output")), data.get("status") == "failed"
                )
            elif kind in ("tool", "tool_call"):
                self.call(key, str(row.get("tool") or row.get("name") or "tool"), row.get("input"))
            elif kind == "tool_result":
                self.result(
                    key, row.get("result", row.get("output")), row.get("status") == "failed"
                )
            elif kind == "text":
                self.message("assistant", row.get("text"), fallback)

    def values(self) -> list[dict[str, Any]]:
        return list(self.items.values())


def history(
    agent: str, rows: list[dict[str, Any]], clean: Callable[[str], str]
) -> list[dict[str, Any]]:
    timeline = Timeline(clean)
    for row in rows:
        timeline.feed(agent, row)
    return timeline.values()
