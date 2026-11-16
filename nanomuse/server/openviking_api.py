"""Authenticated memory controls. A button press is approval for that one action.

These requests use the same Sentinel policy and audit as agent tools. The user's
explicit authenticated action answers any approval question once; deny rules
still win. They never create standing grants for a model or a conversation.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from nanomuse.memory.archive import MemoryArchive
from nanomuse.memory.openviking import OpenVikingManage
from nanomuse.memory.personal import PersonalControls
from nanomuse.schema import Function, ToolCall
from nanomuse.sentinel import Sentinel
from nanomuse.ui import ApprovalDecision, ApprovalRequest, HeadlessUI

if TYPE_CHECKING:
    from nanomuse.server.service import MuseService


class MemoryEdit(BaseModel):
    uri: str = Field(min_length=1, max_length=2000)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    content: str = Field(default="", max_length=32000)


class CaptureBody(BaseModel):
    enabled: bool


class ProfileReview(BaseModel):
    version: int = Field(ge=1)
    action: str = Field(pattern=r"^(confirm|reject|edit)$")
    value: str = Field(default="", max_length=500)


class SpaceBody(BaseModel):
    id: str = Field(default="", pattern=r"^(?:[a-z][a-z0-9_-]{0,47})?$")
    label: str = Field(min_length=1, max_length=80)


class ArchiveBody(BaseModel):
    revision: str = ""
    data: dict[str, Any] | None = None


class MemoryControlsUI(HeadlessUI):
    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(
            approved=True, reason="Requested from authenticated memory controls", scope="once"
        )


def install_openviking(app: FastAPI, svc: MuseService, dependencies: list[Any]) -> None:
    async def operate(
        action: str,
        *,
        personal: bool = False,
        space: str = "personal",
        archive: bool = False,
        **args: Any,
    ) -> dict[str, Any]:
        try:
            bridge = svc.app.memory_hub.bridge(space)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        if bridge is None or not svc.settings.memory.enabled:
            raise HTTPException(409, "OpenViking memory is not enabled")
        gate = Sentinel(
            svc.settings.sentinel, svc.app.audit, MemoryControlsUI(), vault=svc.app.vault
        )
        token = gate.begin_task("Manage OpenViking memory", conversation="memory-controls")
        try:
            call = ToolCall(
                function=Function(
                    name="memory_archive"
                    if archive
                    else "personal_memory"
                    if personal
                    else "openviking_memory",
                    arguments=json.dumps({"action": action, **args}),
                )
            )
            if archive:
                result = await gate.guard(call, MemoryArchive(hub=svc.app.memory_hub, space=space))
            elif personal:
                result = await gate.guard(
                    call, PersonalControls(store=bridge.personal, vault=svc.app.vault)
                )
            else:
                result = await gate.guard(
                    call, OpenVikingManage(bridge=bridge, vault=svc.app.vault, controls=True)
                )
        finally:
            gate.end_task(token)
        if not result.ok:
            error = result.error or "OpenViking request failed"
            prefix = error.split(":", 1)[0]
            code = int(prefix) if prefix.isdigit() else 403
            if code not in (400, 403, 404, 409, 422, 503):
                code = 502
            raise HTTPException(code, error.split(": ", 1)[-1] if prefix.isdigit() else error)
        if action in ("update", "delete", "capture", "retry", "confirm", "reject", "edit"):
            svc.bus.publish({"kind": "memory"})
        return json.loads(result.output)

    @app.get("/api/memory/openviking/profile", dependencies=dependencies)
    async def profile(history: bool = False, space: str = "personal") -> dict[str, Any]:
        result = await operate("list", personal=True, history=history, space=space)
        result["learning_enabled"] = svc.settings.memory.openviking.personalization
        return result

    @app.post("/api/memory/openviking/profile/{item_id}", dependencies=dependencies)
    async def review_profile(
        item_id: str, body: ProfileReview, space: str = "personal"
    ) -> dict[str, Any]:
        return await operate(personal=True, item_id=item_id, space=space, **body.model_dump())

    @app.get("/api/memory/openviking/status", dependencies=dependencies)
    async def status(space: str = "personal") -> dict[str, Any]:
        if svc.app.openviking is None or not svc.settings.memory.enabled:
            return {"enabled": False, "capture": False, "pending": 0, "tasks": []}
        return await operate("status", space=space)

    @app.put("/api/memory/openviking/capture", dependencies=dependencies)
    async def set_capture(body: CaptureBody, space: str = "personal") -> dict[str, Any]:
        return await operate("capture", capture=body.enabled, space=space)

    @app.post("/api/memory/openviking/retry", dependencies=dependencies)
    async def retry(space: str = "personal") -> dict[str, Any]:
        return await operate("retry", space=space)

    @app.get("/api/memory/openviking/entries", dependencies=dependencies)
    async def entries(
        uri: str = Query("", max_length=2000),
        query: str = Query("", max_length=8000),
        offset: int = Query(0, ge=0, le=100000),
        space: str = "personal",
    ) -> dict[str, Any]:
        return await operate("list", uri=uri, query=query, offset=offset, space=space)

    @app.get("/api/memory/openviking/entry", dependencies=dependencies)
    async def read(
        uri: str = Query(..., min_length=1, max_length=2000), space: str = "personal"
    ) -> dict[str, Any]:
        return await operate("read", uri=uri, space=space)

    @app.put("/api/memory/openviking/entry", dependencies=dependencies)
    async def update(body: MemoryEdit, space: str = "personal") -> dict[str, Any]:
        return await operate("update", space=space, **body.model_dump())

    @app.delete("/api/memory/openviking/entry", dependencies=dependencies)
    async def delete(body: MemoryEdit, space: str = "personal") -> dict[str, Any]:
        return await operate("delete", uri=body.uri, revision=body.revision, space=space)

    @app.get("/api/memory/spaces", dependencies=dependencies)
    async def spaces(space: str = "personal") -> dict[str, Any]:
        if svc.app.openviking is None:
            return {
                "owner": "",
                "spaces": svc.app.memory_hub.spaces(),
                "learning": {"pending": 0, "failed": 0},
            }
        return await operate("status", archive=True, space=space)

    @app.post("/api/memory/spaces", dependencies=dependencies)
    async def create_space(body: SpaceBody) -> dict[str, Any]:
        return await operate(
            "create",
            archive=True,
            new_space=body.id or "project-" + uuid.uuid4().hex[:16],
            label=body.label,
        )

    @app.post("/api/memory/spaces/{space}/retry", dependencies=dependencies)
    async def retry_learning(space: str) -> dict[str, Any]:
        return await operate("retry", archive=True, space=space)

    @app.get("/api/memory/spaces/{space}/export", dependencies=dependencies)
    async def export_space(space: str) -> dict[str, Any]:
        return await operate("export", archive=True, space=space)

    @app.post("/api/memory/spaces/{space}/clear", dependencies=dependencies)
    async def clear_space(space: str, body: ArchiveBody) -> dict[str, Any]:
        return await operate("clear", archive=True, space=space, revision=body.revision)

    @app.post("/api/memory/spaces/{space}/restore", dependencies=dependencies)
    async def restore_space(space: str, body: ArchiveBody) -> dict[str, Any]:
        return await operate("restore", archive=True, space=space, data=body.data)
