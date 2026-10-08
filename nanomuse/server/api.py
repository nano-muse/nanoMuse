"""HTTP + WebSocket API for the nanoMuse app (and anything else that wants to talk to your nanoMuse).

    GET  /api/state                      snapshot: profile, status, threads, goals, settings
    GET  /api/threads                    list threads          POST /api/threads {title}
    GET  /api/threads/{id}/events        timeline (?limit&before)
    POST /api/threads/{id}/send {text}   queue a message (non-blocking)
    POST /api/approvals/{id} {approved, scope, reason}
    DELETE /api/approvals                 forget every granted permission
    DELETE /api/approvals/grants/{key}    revoke one (key = "tool" or "tool:target")
    GET  /api/goals  POST /api/goals  GET|PATCH|DELETE /api/goals/{id}  POST /api/goals/{id}/advance|steps|check-in
    POST /api/goals/{id}/proposal/accept  DELETE /api/goals/{id}/proposal   the agent's plan change
    GET  /api/memory  POST /api/memory  DELETE /api/memory/{id}
    POST /api/memory/tidy (?dry_run=1)   GET /api/memory/changes   POST /api/memory/changes/{id}/restore
    GET  /api/ideas (?refresh=1)
    GET  /api/activity                   audit tail + approvals granted
    GET  /api/feed                        what happened without you asking
    GET  /api/feed/posts                  posts written for you, and your feed instructions
    PUT  /api/feed/instructions           what you want to read there
    POST /api/feed/posts/refresh          write a new batch now
    GET  /api/upcoming                    next background pass and the goals in line
    POST /api/tick                        run the scheduler's pass now (the phone's alarm)
    GET  /api/calendar (?days&refresh=1)  today's and tomorrow's events from the calendar feeds
    GET  /api/files  GET /api/files/{path}  POST /api/files/upload?name=  (body: the bytes)
    GET|PUT /api/settings
    GET  /api/connections                 model, email, browser, MCP servers, vault names
    PUT  /api/connections/llm|embeddings|email|browser|calendar   POST /api/connections/llm|embeddings|email|calendar/test
    PUT  /api/connections/gui             the hands' model (a protocol or a catalogue id, as for llm)   POST /api/connections/gui/test
    GET|PUT /api/connections/image|video  where pictures and clips come from: provider (a catalogue id), model, base_url, api_key
    POST /api/llm/models                 the models an endpoint offers (live /models, else the catalogue)
    GET  /api/providers (?lang=en|zh&region=cn|global)  the provider catalogue, which slots use which, what that covers
    POST /api/chatgpt/login  GET /api/chatgpt/status  GET /api/chatgpt/usage
    POST /api/chatgpt/callback {url}  POST /api/chatgpt/logout
    POST /api/connections/calendar/feeds {name,url}  DELETE /api/connections/calendar/feeds/{name}
    PUT  /api/connections/contacts {enabled}  POST /api/connections/contacts/sources {name,url}
    POST /api/connections/contacts/import?name= (body: the .vcf text)  DELETE /api/connections/contacts/sources/{name}
    POST /api/connections/contacts/test      GET /api/contacts?q=&limit=   look people up
    GET  /api/skills  GET /api/skills/{name}  PUT /api/skills/{name} {content}  DELETE /api/skills/{name}
    POST /api/skills/{name}/enabled {enabled}  POST /api/skills/import {url}
    POST /api/connections/mcp  DELETE /api/connections/mcp/{name}
    GET  /api/vault  PUT|DELETE /api/vault/{name}   (names only ever come back)
    POST /api/onboarded
    GET  /api/firstrun (?lang=en|zh)      the first conversation: phase, chips, the three opening lines
    POST /api/firstrun/start {lang}  POST /api/firstrun/pick {name}  POST /api/firstrun/dismiss
    GET  /api/nudges (?refresh=1)         when the app may ask for a star: the relay's policy, read once a day
    GET|PUT /api/sync/state {enabled}     conversations synced between the account's devices: the switch, the cursor, the relay's counts
    POST /api/sync/delete                 delete what the relay stores for the account (the switch stays)
    POST /api/sync/pull                   pull the other devices' changes now
    GET  /api/update (?refresh=1)         installed and latest release (nanomuse.cn/dl first, GitHub second; a day's cache)
    GET  /api/avatar                      the avatar studio: can a face be drawn, the session under way
    POST /api/avatar/begin {description, style?}  a session: the card with the cost in the chat
    POST /api/avatar/start|choose|cancel {session, index?}   draw (or redraw) the four, pick one, stop
    POST /api/avatar/moods                the poses of the current face drawn again
    WS   /ws                              live events; the first frame is {"kind": "auth", "token": …}

All endpoints require ``Authorization: Bearer <token>`` unless ``server.auth = false``.
The token is printed (with a QR code, in the link's ``#fragment``) by ``nanomuse serve``.
The bytes the app shows inline — ``/api/files/*`` and the browser frames — also open with
a link the client signed with its token (``?exp=&sig=``, :mod:`nanomuse.server.tickets`),
so no token travels in a URL. ``?token=`` is no longer accepted (0.1.33): a request that
still carries one gets a 401 with a message saying where the token goes now.
"""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from nanomuse.avatar.studio import StudioError
from nanomuse.bridge.server import BridgeError
from nanomuse.cloud import CloudError
from nanomuse.coding.service import CodingError
from nanomuse.config import Settings
from nanomuse.fences import MAX_NAME
from nanomuse.hub.client import HubError
from nanomuse.llm.chatgpt import ChatGPTError
from nanomuse.logger import logger
from nanomuse.server import tickets
from nanomuse.server.channels_api import install_channels
from nanomuse.server.events import MAIN_THREAD
from nanomuse.server.service import MuseService, goal_to_dict
from nanomuse.server.update import UpdateCheck

STATIC_DIR = Path(__file__).parent / "static"
# Said to a client that still puts the token in the URL (taken until 0.1.32).
LEGACY_TOKEN_MESSAGE = (
    "the token no longer travels in the URL: send it as 'Authorization: Bearer …' "
    "(or as the socket's first frame); update the app, or pair again with a #token= link"
)


# ----------------------------------------------------------------------------- request models
class SendBody(BaseModel):
    text: str = Field("", max_length=20_000)
    # workspace paths from POST /api/files/upload; a message may be attachments alone
    files: list[str] = Field(default_factory=list, max_length=10)
    # the language of the client's screens (a BCP-47 tag such as "en" or "zh-CN"); the reply
    # is written in it unless Settings fixes one. Optional: without it the message's script decides.
    language: str = Field("", max_length=20)
    # "cloud": *Use nanoMuse Cloud this time*; this one turn runs on the account's recommended
    # chat model, the next is back on the configured model. 401 `signed_out` when signed out.
    via: str = Field("", max_length=20)


class ThreadBody(BaseModel):
    title: str = ""


class FeedInstructionsBody(BaseModel):
    """The feed's preferences; only the fields given change (``daily``/``time`` are the
    daily routine, see ``MuseService.feed_posts``)."""

    instructions: str | None = None
    daily: bool | None = None
    time: str | None = None


class ApprovalBody(BaseModel):
    approved: bool
    scope: str = "once"
    reason: str = ""


class GoalBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    steps: list[str] = Field(default_factory=list)
    category: str = ""
    due: str = ""
    check_in: str = ""


class GoalPatch(BaseModel):
    status: str | None = None
    note: str | None = None
    step_index: int | None = None
    step_status: str | None = None
    step_note: str | None = None
    # the goal's own fields; "" clears due / check_in
    title: str | None = Field(default=None, max_length=200)
    description: str | None = None
    category: str | None = None
    due: str | None = None
    check_in: str | None = None


class StepBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class ReminderBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: str = "remind"
    at: str = ""
    repeat: str = ""
    thread: str = ""


class TriggerBody(BaseModel):
    kind: str = Field(pattern="^(mail|event|hook)$")
    text: str = Field(min_length=1, max_length=2000)
    match: str = Field(default="", max_length=200)
    lead_minutes: int = Field(default=30, ge=0, le=1440)
    thread: str = ""


class MemoryBody(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    category: str = "profile"


class SettingsBody(BaseModel):
    profile: dict[str, Any] | None = None
    sentinel_mode: str | None = None
    show_thinking: bool | None = None
    language: str | None = None


class LLMBody(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    tool_mode: str | None = None
    # a new key goes straight into the vault; "" removes the key; None keeps it
    api_key: str | None = None
    # `[llm] proxy`: http(s):// or socks5(h):// for this slot's requests only; "" clears it
    proxy: str | None = None


class MediaBody(BaseModel):
    """One of the ``image`` / ``video`` slots. ``provider`` is a catalogue id, or ``openai``
    / ``openai_responses`` with a ``base_url``; ``model`` empty means the catalogue's default;
    ``api_key`` goes into the vault, "" removes it, None keeps it. All four "" clears the
    slot: pictures (clips) come from the chat provider again, or the account."""

    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class LLMModelsBody(BaseModel):
    preset: str = ""
    base_url: str = ""
    api_key: str = ""


class ChatGptCallbackBody(BaseModel):
    # the full address the browser landed on: http://localhost:1455/auth/callback?code=…&state=…
    url: str = Field(min_length=1, max_length=4000)


class EmbeddingsBody(BaseModel):
    mode: str | None = None  # auto | on | off
    model: str | None = None  # "" → the default for the endpoint
    base_url: str | None = None  # "" → the model's endpoint
    api_key: str | None = None  # into the vault; "" → the model's key; None keeps it


class SearchBody(BaseModel):
    provider: str | None = None  # duckduckgo | brave | tavily | searxng
    api_key: str | None = None  # into the vault; "" removes it; None keeps it
    base_url: str | None = None  # SearXNG instance


class EmailBody(BaseModel):
    enabled: bool | None = None
    address: str | None = None
    password: str | None = None
    imap_host: str | None = None
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_starttls: bool | None = None


class BrowserBody(BaseModel):
    enabled: bool


class CalendarFeedBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=1, max_length=2000)


class ContactsSourceBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=1, max_length=2000)


class ContactsBody(BaseModel):
    enabled: bool | None = None


class SkillBody(BaseModel):
    content: str = Field(max_length=70_000)  # the SKILL.md text


class SkillEnabledBody(BaseModel):
    enabled: bool


class SkillImportBody(BaseModel):
    url: str = Field(max_length=2000)


class CalendarBody(BaseModel):
    enabled: bool | None = None
    refresh_minutes: int | None = Field(default=None, ge=5, le=1440)
    day_start: str | None = None
    day_end: str | None = None


class MCPBody(BaseModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    risk: str = "moderate"
    egress: bool = True
    reads_private_data: bool = False


class SecretBody(BaseModel):
    value: str = Field(min_length=1, max_length=10_000)


class OnboardedBody(BaseModel):
    done: bool = True


class FirstRunStartBody(BaseModel):
    # the language the opening is shown in ("en" or "zh"); the agent's reply language when empty
    lang: str = Field("", max_length=10)


class FirstRunPickBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class BrowserControlBody(BaseModel):
    """The user drives the agent's browser. ``x``/``y`` are fractions of the frame."""

    action: str
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    text: str | None = Field(default=None, max_length=4000)
    key: str | None = Field(default=None, max_length=40)
    dy: float | None = Field(default=None, ge=-5000, le=5000)
    url: str | None = Field(default=None, max_length=2000)


class HoldBody(BaseModel):
    """The user takes the browser, the computer or the phone over for a chat (contract C1)."""

    thread: str = Field(default=MAIN_THREAD, max_length=64)
    tool: str = Field(pattern="^(browser|computer|phone)$")
    reason: str | None = Field(default=None, max_length=300)


class PushSubscribeBody(BaseModel):
    # the PushSubscription.toJSON() of the browser: {endpoint, expirationTime, keys{p256dh, auth}}
    subscription: dict[str, Any]


class PushUnsubscribeBody(BaseModel):
    endpoint: str


class CloudCodeBody(BaseModel):
    identifier: str = Field(min_length=3, max_length=200)


class CloudVerifyBody(BaseModel):
    identifier: str = Field(default="", max_length=200)
    code: str = Field(min_length=4, max_length=12)
    invite: str = Field(default="", max_length=32)


class CloudModelBody(BaseModel):
    model: str = Field(default="", max_length=120)


class AvatarBeginBody(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    # the chat the card goes to; "" from the studio screen, which has no card
    thread: str = MAIN_THREAD
    # one of the studio's STYLES (the phone's list); Muse's 3D toy look when left out
    style: str = Field(default="muse", max_length=20)


class AvatarSessionBody(BaseModel):
    session: str
    index: int | None = None


class CloudModelsBody(BaseModel):
    """``POST /api/cloud/models``: the account's models as a source, on or off."""

    on: bool = True


class CloudContributeBody(BaseModel):
    on: bool = False


class SyncStateBody(BaseModel):
    enabled: bool | None = None
    # C9: this device's side chats too (per device, default off)
    side_chats: bool | None = None


class CloudLoginBody(BaseModel):
    identifier: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=128)


class CloudPasswordBody(BaseModel):
    password: str = Field(default="", max_length=128)
    current: str | None = Field(default=None, max_length=128)


class CloudSignOutAllBody(BaseModel):
    all: bool = False


class CodingSendBody(BaseModel):
    agent: str = Field(min_length=1, max_length=20)
    text: str = Field(min_length=1, max_length=20000)
    session_id: str = Field(default="", max_length=120)
    workspace: str = Field(default="", max_length=1000)
    device: str = Field(default="", max_length=120)


class CodingStopBody(BaseModel):
    run: str = Field(min_length=1, max_length=40)
    device: str = Field(default="", max_length=120)


class HubBody(BaseModel):
    enabled: bool | None = None
    remote_control: bool | None = None
    name: str | None = Field(default=None, max_length=60)


class AskDeviceBody(BaseModel):
    device: str = Field(min_length=1, max_length=120)
    text: str = Field(default="", max_length=20_000)


# ----------------------------------------------------------------------------- app factory
def create_app(settings: Settings, service: MuseService | None = None) -> FastAPI:
    svc = service or MuseService(settings)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The services get a few seconds to come up before the socket opens; past that the
        # app answers (and /api/health names the step still running) rather than leaving
        # a desktop shell staring at a closed port while an MCP server or a relay behind a
        # broken proxy takes its time.
        starting = asyncio.create_task(svc.start(), name="services-start")
        await asyncio.wait({starting}, timeout=settings.server.start_grace)
        on_ready = getattr(app.state, "on_ready", None)
        if callable(on_ready):
            on_ready()
        try:
            yield
        finally:
            if not starting.done():
                starting.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await starting
            await svc.stop()

    app = FastAPI(
        title="nanoMuse",
        version=svc.settings_view()["version"],
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.service = svc

    if settings.server.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.server.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ------------------------------------------------------------------ auth
    def _check_token(token: str | None) -> None:
        if not svc.token:
            return
        if not token or not secrets.compare_digest(token.encode(), svc.token.encode()):
            raise HTTPException(status_code=401, detail="invalid or missing token")

    def auth(request: Request) -> None:
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else None
        if token is None and "token" in request.query_params:
            # ``?token=`` lands in access logs; it was taken until 0.1.32 and is refused now.
            raise HTTPException(status_code=401, detail=LEGACY_TOKEN_MESSAGE)
        _check_token(token)

    def auth_or_signed(request: Request) -> None:
        """A header as everywhere — or, for the bytes an ``<img>``/``<video>``/``<iframe>``
        fetches, a link the client signed with its token (:mod:`nanomuse.server.tickets`)."""
        query = request.query_params
        if svc.token and "sig" in query and "authorization" not in request.headers:
            if tickets.check(svc.token, request.scope["path"], query.get("exp"), query.get("sig")):
                return
            raise HTTPException(status_code=401, detail="this link has expired")
        auth(request)

    dep = [Depends(auth)]
    dep_or_signed = [Depends(auth_or_signed)]

    def _thread_or_404(thread_id: str):  # noqa: ANN202
        thread = svc.threads.get(thread_id)
        if thread is None:
            raise HTTPException(404, "no such thread")
        return thread

    def _goal_or_404(goal_id: str):  # noqa: ANN202
        goal = svc.app.goals.get(goal_id)
        if goal is None:
            raise HTTPException(404, "no such goal")
        return goal

    # ------------------------------------------------------------------ state
    @app.get("/api/state", dependencies=dep)
    async def get_state() -> dict[str, Any]:
        return svc.state()

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        out = {"ok": True, "version": svc.settings_view()["version"], "auth": bool(svc.token)}
        if svc.starting:
            out["starting"] = svc.starting
        return out

    update_check = UpdateCheck(svc.settings.server.update_check)

    @app.get("/api/update", dependencies=dep)
    async def update_status(refresh: bool = False) -> dict[str, Any]:
        """The installed and the latest release (nanomuse.cn/dl first, GitHub second; a day's
        cache, ``?refresh=1`` asks now; see ``server.update_check``)."""
        return await update_check.view(force=refresh)

    # ------------------------------------------------------------------ threads & chat
    @app.get("/api/threads", dependencies=dep)
    async def list_threads() -> list[dict[str, Any]]:
        """The current account's conversations and the ones no account has (contract C10);
        every local one when signed out."""
        return [t.meta() for t in svc.visible_threads()]

    @app.post("/api/threads", dependencies=dep)
    async def create_thread(body: ThreadBody) -> dict[str, Any]:
        return svc.create_thread(body.title).meta()

    @app.patch("/api/threads/{thread_id}", dependencies=dep)
    async def rename_thread(thread_id: str, body: ThreadBody) -> dict[str, Any]:
        thread = svc.rename_thread(thread_id, body.title)
        if thread is None:
            raise HTTPException(404, "no such thread")
        return thread.meta()

    @app.delete("/api/threads/{thread_id}", dependencies=dep)
    async def delete_thread(thread_id: str) -> dict[str, Any]:
        if thread_id == MAIN_THREAD:
            raise HTTPException(400, "the main chat cannot be deleted")
        if not svc.delete_thread(thread_id):
            raise HTTPException(404, "no such thread")
        return {"ok": True}

    @app.post("/api/threads/{thread_id}/stop", dependencies=dep)
    async def stop_thread(thread_id: str) -> dict[str, Any]:
        _thread_or_404(thread_id)
        return {"ok": svc.stop_thread(thread_id)}

    @app.post("/api/threads/{thread_id}/clear", dependencies=dep)
    async def clear_thread(thread_id: str) -> dict[str, Any]:
        _thread_or_404(thread_id)
        if not svc.clear_thread(thread_id):
            raise HTTPException(409, "thread is busy")
        return {"ok": True}

    @app.get("/api/threads/{thread_id}/events", dependencies=dep)
    async def thread_events(
        thread_id: str, limit: int = Query(200, ge=1, le=1000), before: str | None = None
    ) -> dict[str, Any]:
        thread = _thread_or_404(thread_id)
        events = thread.timeline.tail(limit, before)
        return {
            "thread": thread.meta(),
            "events": events,
            "has_more": len(thread.timeline.events) > len(events),
        }

    @app.post("/api/threads/{thread_id}/send", dependencies=dep)
    async def send_message(thread_id: str, body: SendBody) -> dict[str, Any]:
        thread = _thread_or_404(thread_id)
        try:
            event = svc.send(
                thread.id, body.text, files=body.files, language=body.language, via=body.via
            )
        except (ValueError, PermissionError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except CloudError as exc:
            raise _cloud_http(exc) from exc
        return {"event": event, "thread": thread.meta()}

    # ------------------------------------------------------------------ approvals
    @app.post("/api/approvals/{approval_id}", dependencies=dep)
    async def decide_approval(approval_id: str, body: ApprovalBody) -> dict[str, Any]:
        if approval_id in svc.hub.remote_approvals:
            # a card raised by another device's run, shown in its side chat here
            if not await svc.hub.decide_remote(approval_id, body.approved):
                raise HTTPException(502, "the device did not take the answer")
            return {"ok": True}
        if not svc.decide(approval_id, body.approved, body.scope, body.reason):
            raise HTTPException(404, "no pending approval with that id")
        return {"ok": True}

    @app.delete("/api/approvals", dependencies=dep)
    async def reset_approvals() -> dict[str, Any]:
        svc.forget_approvals()
        return {"ok": True}

    @app.delete("/api/approvals/grants/{key:path}", dependencies=dep)
    async def revoke_grant(key: str) -> dict[str, Any]:
        if not svc.revoke_grant(key):
            raise HTTPException(404, "no such permission")
        return {"ok": True}

    # ------------------------------------------------------------------ goals
    @app.get("/api/goals", dependencies=dep)
    async def list_goals(
        status: str | None = None, category: str | None = None
    ) -> list[dict[str, Any]]:
        return [goal_to_dict(g) for g in svc.app.goals.list(status, category)]

    @app.post("/api/goals", dependencies=dep)
    async def create_goal(body: GoalBody) -> dict[str, Any]:
        try:
            goal = svc.app.goals.create(
                body.title,
                body.description,
                [s for s in body.steps if s.strip()],
                category=body.category,
                due=body.due,
                check_in=body.check_in,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        svc.bus.publish({"kind": "goals"})
        return goal_to_dict(goal)

    @app.get("/api/goals/{goal_id}", dependencies=dep)
    async def get_goal(goal_id: str) -> dict[str, Any]:
        return goal_to_dict(_goal_or_404(goal_id))

    @app.patch("/api/goals/{goal_id}", dependencies=dep)
    async def patch_goal(goal_id: str, body: GoalPatch) -> dict[str, Any]:
        _goal_or_404(goal_id)
        store = svc.app.goals
        try:
            if body.status:
                store.set_status(goal_id, body.status)
            if body.note:
                store.append_note(goal_id, body.note)
            if body.step_index is not None and (body.step_status or body.step_note is not None):
                store.update_step(goal_id, body.step_index, body.step_status, body.step_note)
            if any(
                v is not None
                for v in (body.title, body.description, body.category, body.due, body.check_in)
            ):
                store.update(
                    goal_id,
                    title=body.title,
                    description=body.description,
                    category=body.category,
                    due=body.due,
                    check_in=body.check_in,
                )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        svc.bus.publish({"kind": "goals"})
        return goal_to_dict(_goal_or_404(goal_id))

    @app.post("/api/goals/{goal_id}/check-in", dependencies=dep)
    async def check_in_goal(goal_id: str) -> dict[str, Any]:
        """Send this goal's reminder now."""
        try:
            goal = svc.check_in(goal_id)
        except KeyError as exc:
            raise HTTPException(404, "no such goal") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return goal_to_dict(goal)

    @app.post("/api/goals/{goal_id}/proposal/accept", dependencies=dep)
    async def accept_proposal(goal_id: str) -> dict[str, Any]:
        goal = _goal_or_404(goal_id)
        if not goal.proposal:
            raise HTTPException(409, "nothing proposed")
        svc.app.goals.accept_proposal(goal_id)
        svc.bus.publish({"kind": "goals"})
        return goal_to_dict(_goal_or_404(goal_id))

    @app.delete("/api/goals/{goal_id}/proposal", dependencies=dep)
    async def dismiss_proposal(goal_id: str) -> dict[str, Any]:
        goal = _goal_or_404(goal_id)
        if not goal.proposal:
            raise HTTPException(409, "nothing proposed")
        svc.app.goals.dismiss_proposal(goal_id)
        svc.bus.publish({"kind": "goals"})
        return goal_to_dict(_goal_or_404(goal_id))

    @app.post("/api/goals/{goal_id}/steps", dependencies=dep)
    async def add_step(goal_id: str, body: StepBody) -> dict[str, Any]:
        _goal_or_404(goal_id)
        svc.app.goals.add_step(goal_id, body.title)
        svc.bus.publish({"kind": "goals"})
        return goal_to_dict(_goal_or_404(goal_id))

    @app.post("/api/goals/{goal_id}/advance", dependencies=dep)
    async def advance_goal(goal_id: str) -> dict[str, Any]:
        try:
            goal = svc.advance_goal(goal_id)
        except KeyError as exc:
            raise HTTPException(404, "no such goal") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return goal_to_dict(goal)

    @app.delete("/api/goals/{goal_id}", dependencies=dep)
    async def delete_goal(goal_id: str) -> dict[str, Any]:
        if not svc.app.goals.delete(goal_id):
            raise HTTPException(404, "no such goal")
        svc.bus.publish({"kind": "goals"})
        return {"ok": True}

    # ------------------------------------------------------------------ reminders
    @app.get("/api/reminders", dependencies=dep)
    async def list_reminders(all: bool = False) -> list[dict[str, Any]]:  # noqa: A002
        """Active reminders and routines, soonest first; ``?all=1`` adds recently finished ones."""
        return [r.to_dict() for r in svc.app.reminders.list(None if all else "active")]

    @app.post("/api/reminders", dependencies=dep)
    async def create_reminder(body: ReminderBody) -> dict[str, Any]:
        try:
            item = svc.create_reminder(
                body.text, at=body.at, repeat=body.repeat, kind=body.kind, thread=body.thread
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return item.to_dict()

    @app.post("/api/reminders/{reminder_id}/fire", dependencies=dep)
    async def fire_reminder(reminder_id: str) -> dict[str, Any]:
        """Deliver it now instead of waiting for its time."""
        try:
            return svc.fire_reminder(reminder_id).to_dict()
        except KeyError as exc:
            raise HTTPException(404, "no such reminder") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.delete("/api/reminders/{reminder_id}", dependencies=dep)
    async def cancel_reminder(reminder_id: str) -> dict[str, Any]:
        item = svc.cancel_reminder(reminder_id)
        if item is None:
            if svc.app.reminders.get(reminder_id) is None:
                raise HTTPException(404, "no such reminder")
            raise HTTPException(409, "already finished")
        return item.to_dict()

    # ------------------------------------------------------------------ triggers
    @app.get("/api/triggers", dependencies=dep)
    async def list_triggers() -> dict[str, Any]:
        """Triggers (active and cancelled), which kinds have their connector, and how the
        inbox watch is doing."""
        return svc.triggers_view()

    @app.post("/api/triggers", dependencies=dep)
    async def create_trigger(body: TriggerBody) -> dict[str, Any]:
        try:
            item = svc.create_trigger(
                body.kind,
                body.text,
                match=body.match,
                lead_minutes=body.lead_minutes,
                thread=body.thread,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        out = item.to_dict()
        if item.kind == "hook":
            out["url"] = svc.hook_url(item)
        return out

    @app.post("/api/triggers/{trigger_id}/fire", dependencies=dep)
    async def fire_trigger(trigger_id: str) -> dict[str, Any]:
        """Run it now with a sample occurrence, to see what it does."""
        item = svc.app.triggers.get(trigger_id)
        if item is None:
            raise HTTPException(404, "no such trigger")
        what = {
            "mail": "A test: you pressed Run now, as if a matching mail had just arrived (none did)",
            "event": "A test: you pressed Run now, as if a matching event were about to start",
            "hook": "A test: you pressed Run now, as if the webhook had been called (empty body)",
        }[item.kind]
        try:
            fired = svc.fire_trigger(
                trigger_id, what=what, key=f"test:{secrets.token_hex(4)}", title="test run"
            )
        except KeyError as exc:
            raise HTTPException(404, "no such trigger") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return (fired or item).to_dict()

    @app.delete("/api/triggers/{trigger_id}", dependencies=dep)
    async def cancel_trigger(trigger_id: str) -> dict[str, Any]:
        item = svc.cancel_trigger(trigger_id)
        if item is None:
            if svc.app.triggers.get(trigger_id) is None:
                raise HTTPException(404, "no such trigger")
            raise HTTPException(409, "already cancelled")
        return item.to_dict()

    @app.post("/api/hooks/{trigger_id}")
    async def deliver_hook(trigger_id: str, request: Request) -> dict[str, Any]:
        """A trigger's webhook. No app token: the key in the URL is the credential, and a
        wrong id or key is a 404 either way. The body (up to 64 KB, JSON or text) is what
        the agent gets as context."""
        key = request.query_params.get("key") or request.headers.get("x-hook-key") or ""
        limit = 64 * 1024
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise HTTPException(413, "body too large (64 KB max)")
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > limit:
                raise HTTPException(413, "body too large (64 KB max)")
            chunks.append(chunk)
        body = b"".join(chunks).decode("utf-8", errors="replace")
        try:
            item = svc.deliver_hook(trigger_id, key, body, request.headers.get("content-type", ""))
        except KeyError as exc:
            raise HTTPException(404, "not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(429, str(exc)) from exc
        return {"ok": True, "trigger": item.id, "fired": item.fired}

    # ------------------------------------------------------------------ memory
    @app.get("/api/memory", dependencies=dep)
    async def list_memory() -> list[dict[str, Any]]:
        if svc.app.memory is None:
            return []
        return [m.__dict__ for m in svc.app.memory.all()]

    @app.post("/api/memory", dependencies=dep)
    async def add_memory(body: MemoryBody) -> dict[str, Any]:
        if svc.app.memory is None:
            raise HTTPException(400, "memory is disabled")
        item = svc.app.memory.add(body.content, body.category or "profile", source="user")
        svc.bus.publish({"kind": "memory"})
        return item.__dict__

    @app.delete("/api/memory/{memory_id}", dependencies=dep)
    async def forget_memory(memory_id: str) -> dict[str, Any]:
        if svc.app.memory is None or not svc.app.memory.forget(memory_id):
            raise HTTPException(404, "no such memory")
        svc.bus.publish({"kind": "memory"})
        return {"ok": True}

    @app.post("/api/memory/tidy", dependencies=dep)
    async def tidy_memory(dry_run: bool = False) -> dict[str, Any]:
        """One tidy-up pass now (merge duplicates, drop non-facts); ``dry_run`` only plans."""
        try:
            return await svc.tidy_memory(dry_run=dry_run)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/memory/changes", dependencies=dep)
    async def memory_changes(limit: int = Query(30, ge=1, le=200)) -> list[dict[str, Any]]:
        """What tidy-ups and updates changed, newest first; each entry can be restored."""
        if svc.app.memory is None:
            return []
        return [c.to_dict() for c in svc.app.memory.history(limit)]

    @app.post("/api/memory/changes/{change_id}/restore", dependencies=dep)
    async def restore_memory_change(change_id: str) -> dict[str, Any]:
        if svc.app.memory is None:
            raise HTTPException(400, "memory is disabled")
        change = svc.app.memory.restore(change_id)
        if change is None:
            raise HTTPException(404, "no such change")
        svc.bus.publish({"kind": "memory"})
        return change.to_dict()

    # ------------------------------------------------------------------ ideas
    @app.get("/api/ideas", dependencies=dep)
    async def ideas(refresh: bool = False) -> dict[str, Any]:
        if refresh:
            try:
                return await svc.refresh_ideas()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ideas refresh failed: {}", exc)
                data = svc.cached_ideas()
                data["error"] = f"{type(exc).__name__}: {exc}"
                return data
        return svc.cached_ideas()

    # ------------------------------------------------------------------ activity / settings
    @app.get("/api/activity", dependencies=dep)
    async def activity(n: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
        return svc.activity(n)

    @app.get("/api/settings", dependencies=dep)
    async def get_settings() -> dict[str, Any]:
        return svc.settings_view()

    @app.put("/api/settings", dependencies=dep)
    async def put_settings(body: SettingsBody) -> dict[str, Any]:
        return svc.update_settings(body.model_dump(exclude_none=True))

    # ------------------------------------------------------------------ files
    # ------------------------------------------------------------------ connections
    conn = svc.connections

    @app.get("/api/connections", dependencies=dep)
    async def get_connections() -> dict[str, Any]:
        return conn.view()

    @app.put("/api/connections/llm", dependencies=dep)
    async def put_llm(body: LLMBody) -> dict[str, Any]:
        try:
            return conn.set_llm(body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connections/llm/test", dependencies=dep)
    async def test_llm() -> dict[str, Any]:
        return await conn.test_llm()

    @app.post("/api/llm/models", dependencies=dep)
    async def llm_models(body: LLMModelsBody) -> dict[str, Any]:
        """The models an endpoint offers (its /models, else the preset's catalogue); saves nothing."""
        return await conn.llm_models(body.model_dump())

    # ------------------------------------------------------------------ providers (contract C11)
    @app.get("/api/providers", dependencies=dep)
    async def providers(
        lang: str = Query("", max_length=10), region: str = Query("", max_length=10)
    ) -> dict[str, Any]:
        """The catalogue with what each slot uses, the union of what that covers, and one
        sentence per capability nothing covers (``lang``: en|zh; ``region``: cn|global)."""
        return svc.providers.view(lang=lang.strip().lower(), region=region.strip().lower())

    # ------------------------------------------------------------------ the ChatGPT sign-in
    def _chatgpt_http(exc: ChatGPTError) -> HTTPException:
        status = {"state_mismatch": 400, "bad_callback": 400, "no_login": 409}.get(exc.code, 502)
        return HTTPException(status, f"{exc.message} ({exc.code})")

    @app.post("/api/chatgpt/login", dependencies=dep)
    async def chatgpt_login() -> dict[str, Any]:
        """Start the Codex sign-in (the flow of ``nanomuse chatgpt login``) in the background:
        the page to open, where the callback is expected; the one under way when there is."""
        return await svc.chatgpt.login()

    @app.get("/api/chatgpt/status", dependencies=dep)
    async def chatgpt_status() -> dict[str, Any]:
        """The token store without the tokens; ``pending`` and ``url`` while a sign-in waits;
        ``error`` after one failed, until the next login."""
        return svc.chatgpt.status()

    @app.get("/api/chatgpt/usage", dependencies=dep)
    async def chatgpt_usage() -> dict[str, Any]:
        """What is left of the plan's usage windows, as OpenAI reports it (one request to
        chatgpt.com at most once a minute; ``limits`` null when it reports nothing)."""
        return await svc.chatgpt.usage()

    @app.post("/api/chatgpt/callback", dependencies=dep)
    async def chatgpt_callback(body: ChatGptCallbackBody) -> dict[str, Any]:
        """The callback address pasted from the browser's address bar, for a runtime the
        browser cannot reach on port 1455; a ``state`` that is not the pending login's is 400."""
        try:
            return svc.chatgpt.callback(body.url)
        except ChatGPTError as exc:
            raise _chatgpt_http(exc) from exc

    @app.post("/api/chatgpt/logout", dependencies=dep)
    async def chatgpt_logout() -> dict[str, Any]:
        """Forget the sign-in (and stop one under way); nothing is revoked upstream."""
        return await svc.chatgpt.logout()

    @app.put("/api/connections/embeddings", dependencies=dep)
    async def put_embeddings(body: EmbeddingsBody) -> dict[str, Any]:
        try:
            return conn.set_embeddings(body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connections/embeddings/test", dependencies=dep)
    async def test_embeddings() -> dict[str, Any]:
        return await conn.test_embeddings()

    @app.put("/api/connections/search", dependencies=dep)
    async def put_search(body: SearchBody) -> dict[str, Any]:
        try:
            return conn.set_search(body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connections/search/test", dependencies=dep)
    async def test_search() -> dict[str, Any]:
        return await conn.test_search()

    @app.put("/api/connections/email", dependencies=dep)
    async def put_email(body: EmailBody) -> dict[str, Any]:
        return conn.set_email(body.model_dump(exclude_none=True))

    @app.delete("/api/connections/email", dependencies=dep)
    async def delete_email() -> dict[str, Any]:
        return conn.disconnect_email()

    @app.post("/api/connections/email/test", dependencies=dep)
    async def test_email() -> dict[str, Any]:
        return await conn.test_email()

    @app.put("/api/connections/gui", dependencies=dep)
    async def set_gui(body: dict[str, Any]) -> dict[str, Any]:
        try:
            return svc.connections.set_gui(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connections/gui/test", dependencies=dep)
    async def test_gui() -> dict[str, Any]:
        return await svc.connections.test_gui()

    @app.get("/api/connections/image", dependencies=dep)
    async def get_image() -> dict[str, Any]:
        return conn.media_view("image")

    @app.put("/api/connections/image", dependencies=dep)
    async def put_image(body: MediaBody) -> dict[str, Any]:
        try:
            return conn.set_media("image", body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/connections/video", dependencies=dep)
    async def get_video() -> dict[str, Any]:
        return conn.media_view("video")

    @app.put("/api/connections/video", dependencies=dep)
    async def put_video(body: MediaBody) -> dict[str, Any]:
        try:
            return conn.set_media("video", body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/hands", dependencies=dep)
    async def hands_status() -> dict[str, Any]:
        return svc.hands_view()

    @app.put("/api/connections/hands", dependencies=dep)
    async def set_hands(body: dict[str, Any]) -> dict[str, Any]:
        try:
            return svc.connections.set_hands(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/hands/stop", dependencies=dep)
    async def stop_hands() -> dict[str, Any]:
        return {"stopped": svc.stop_hands()}

    # ------------------------------------------------------------------ holds (C1)
    @app.get("/api/holds", dependencies=dep)
    async def holds_list() -> list[dict[str, Any]]:
        """The holds that are on: the person has the browser, the screen or the phone."""
        return svc.holds_view()

    @app.post("/api/holds", dependencies=dep)
    async def hold_open(body: HoldBody) -> dict[str, Any]:
        """Take over: the agent's actions of that kind in that chat wait for Done."""
        try:
            return svc.open_hold(body.thread, body.tool, body.reason or "")
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/holds/{hold_id}/done", dependencies=dep)
    async def hold_done(hold_id: str) -> dict[str, Any]:
        """Done: the hold goes off; the waiting tool looks again and continues."""
        try:
            return svc.done_hold(hold_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    # ------------------------------------------------------------------ the avatar studio
    def _studio_http(exc: StudioError) -> HTTPException:
        return HTTPException(409, str(exc))

    @app.get("/api/avatar", dependencies=dep)
    async def avatar_view() -> dict[str, Any]:
        """Whether a face can be drawn (an image model on the chat model's host), and the
        session under way if any."""
        return svc.avatar.view()

    @app.post("/api/avatar/estimate", dependencies=dep)
    async def avatar_estimate() -> dict[str, Any]:
        try:
            return await svc.avatar.estimate()
        except StudioError as exc:
            raise _studio_http(exc) from exc

    @app.post("/api/avatar/begin", dependencies=dep)
    async def avatar_begin(body: AvatarBeginBody) -> dict[str, Any]:
        """A new session from a description: the card with the cost appears in the chat."""
        return await svc.avatar.begin(body.thread, body.description.strip(), body.style)

    @app.post("/api/avatar/start", dependencies=dep)
    async def avatar_start(body: AvatarSessionBody) -> dict[str, Any]:
        """The tap on *Draw*: four candidates (also *redraw*)."""
        try:
            return await svc.avatar.start(body.session)
        except StudioError as exc:
            raise _studio_http(exc) from exc

    @app.post("/api/avatar/choose", dependencies=dep)
    async def avatar_choose(body: AvatarSessionBody) -> dict[str, Any]:
        if body.index is None:
            raise HTTPException(422, "index is required")
        try:
            return await svc.avatar.choose(body.session, body.index)
        except StudioError as exc:
            raise _studio_http(exc) from exc

    @app.post("/api/avatar/cancel", dependencies=dep)
    async def avatar_cancel(body: AvatarSessionBody) -> dict[str, Any]:
        try:
            return svc.avatar.cancel(body.session)
        except StudioError as exc:
            raise _studio_http(exc) from exc

    @app.post("/api/avatar/moods", dependencies=dep)
    async def avatar_moods() -> dict[str, Any]:
        """*Redraw the poses* of the face the profile wears, from its idle still (and the
        clips, where the endpoint has a video model)."""
        try:
            return await svc.avatar.redraw_moods()
        except StudioError as exc:
            raise _studio_http(exc) from exc

    @app.get("/api/phone", dependencies=dep)
    async def phone_status() -> dict[str, Any]:
        view = svc.phone_view()
        if svc.phone.last_screen is not None:
            view["screen"] = svc.phone.last_screen.to_dict()
        return view

    # ------------------------------------------------------------------ cloud account & hub
    def _cloud_http(exc: CloudError) -> HTTPException:
        """A relay refusal as the app sees it: the sentence from :data:`nanomuse.cloud.MESSAGES`
        (the web app translates it) and the relay's code in a header, for apps that act on it."""
        return HTTPException(
            exc.status if exc.status >= 400 else 502,
            exc.describe(),
            headers={"X-Nanomuse-Code": exc.code or "error"},
        )

    @app.get("/api/cloud", dependencies=dep)
    async def cloud_status() -> dict[str, Any]:
        return svc.hub.account_view()

    @app.get("/api/cloud/config", dependencies=dep)
    async def cloud_config() -> dict[str, Any]:
        """The relay's public figures — the allowance a new account gets, the invite bonus,
        whether sign-up is open, the repository to star — so the app prints the relay's
        numbers, not its own (relay 0.15). An older relay or no relay: ``{}``."""
        try:
            return await svc.hub.cloud.config()
        except CloudError:
            return {}

    @app.post("/api/cloud/code", dependencies=dep)
    async def cloud_code(body: CloudCodeBody) -> dict[str, Any]:
        try:
            await svc.hub.request_code(body.identifier)
        except CloudError as exc:
            raise _cloud_http(exc) from exc
        return {"ok": True}

    def _with_nudges(data: dict[str, Any]) -> dict[str, Any]:
        """A sign-in or an account read answers with the relay's ``/v1/me``, which carries
        the nudges policy (contract C1): that copy is today's, no separate fetch needed."""
        svc.nudges.take(data.get("nudges"))
        return data

    @app.post("/api/cloud/verify", dependencies=dep)
    async def cloud_verify(body: CloudVerifyBody) -> dict[str, Any]:
        try:
            return _with_nudges(
                await svc.hub.verify(body.identifier, body.code, invite=body.invite)
            )
        except CloudError as exc:
            raise _cloud_http(exc) from exc

    @app.post("/api/cloud/login", dependencies=dep)
    async def cloud_login(body: CloudLoginBody) -> dict[str, Any]:
        try:
            return _with_nudges(await svc.hub.login(body.identifier, body.password))
        except CloudError as exc:
            raise _cloud_http(exc) from exc

    @app.get("/api/nudges", dependencies=dep)
    async def nudges(refresh: bool = False) -> dict[str, Any]:
        """When the app may ask for a star on GitHub (contract C1): the relay's policy, read
        at most once a day (``?refresh=1`` asks now), the last good copy or the built-in
        defaults otherwise. The web keeps its own ledger of asks shown."""
        return await svc.nudges.refresh(force=refresh)

    @app.post("/api/cloud/password", dependencies=dep)
    async def cloud_password(body: CloudPasswordBody) -> dict[str, Any]:
        try:
            return await svc.hub.set_password(body.password, body.current)
        except CloudError as exc:
            raise _cloud_http(exc) from exc

    @app.get("/api/cloud/sessions", dependencies=dep)
    async def cloud_sessions() -> dict[str, Any]:
        try:
            return {"sessions": await svc.hub.sessions()}
        except CloudError as exc:
            raise _cloud_http(exc) from exc

    @app.delete("/api/cloud/sessions/{prefix}", dependencies=dep)
    async def cloud_revoke_session(prefix: str) -> dict[str, Any]:
        try:
            await svc.hub.revoke_session(prefix)
            return {"sessions": await svc.hub.sessions()}
        except CloudError as exc:
            raise _cloud_http(exc) from exc

    @app.post("/api/cloud/sign-out-all", dependencies=dep)
    async def cloud_sign_out_all(body: CloudSignOutAllBody) -> dict[str, Any]:
        try:
            n = await svc.hub.sign_out_all(body.all)
        except CloudError as exc:
            raise _cloud_http(exc) from exc
        return {"signed_out": n, **svc.hub.account_view()}

    @app.get("/api/cloud/events", dependencies=dep)
    async def cloud_events(limit: int = 50) -> dict[str, Any]:
        try:
            return {"events": await svc.hub.events(limit)}
        except CloudError as exc:
            raise _cloud_http(exc) from exc

    @app.post("/api/cloud/delete", dependencies=dep)
    async def cloud_delete_account() -> dict[str, Any]:
        try:
            await svc.hub.delete_account()
        except CloudError as exc:
            raise _cloud_http(exc) from exc
        return svc.hub.account_view()

    @app.post("/api/cloud/sign-out", dependencies=dep)
    async def cloud_sign_out() -> dict[str, Any]:
        await svc.hub.sign_out()
        return svc.hub.account_view()

    @app.get("/api/cloud/me", dependencies=dep)
    async def cloud_me() -> dict[str, Any]:
        try:
            return _with_nudges(await svc.hub.me())
        except CloudError as exc:
            raise _cloud_http(exc) from exc

    @app.post("/api/cloud/models", dependencies=dep)
    async def cloud_models(body: CloudModelsBody) -> dict[str, Any]:
        """*Use nanoMuse Cloud models*: off, the account's models leave the automatic order
        of the hands, pictures and clips and the providers' listing; the sign-in stays.
        ``409 chat_on_cloud`` while the chat model is the account's."""
        try:
            return svc.hub.set_models(body.on)
        except CloudError as exc:
            raise _cloud_http(exc) from exc

    @app.post("/api/cloud/contribute", dependencies=dep)
    async def cloud_contribute(body: CloudContributeBody) -> dict[str, Any]:
        """Data controls: turn "Help improve nanoMuse's AI models" on or off for the account
        (the relay keeps the text of chat turns only while it is on)."""
        try:
            return await svc.hub.set_contribute(body.on)
        except CloudError as exc:
            raise _cloud_http(exc) from exc

    @app.delete("/api/cloud/samples", dependencies=dep)
    async def cloud_delete_samples() -> dict[str, Any]:
        try:
            return {"deleted": await svc.hub.delete_samples()}
        except CloudError as exc:
            raise _cloud_http(exc) from exc

    # ------------------------------------------------------------------ conversation sync (contract C7)
    async def _sync_view() -> dict[str, Any]:
        return {**svc.sync.view(), "relay": await svc.sync.relay_state()}

    @app.get("/api/sync/state", dependencies=dep)
    async def sync_state() -> dict[str, Any]:
        """Data controls: the switch here, whether the account is signed in (``available``),
        the cursor, and the relay's own counts under ``relay`` (null when it cannot be asked)."""
        return await _sync_view()

    @app.put("/api/sync/state", dependencies=dep)
    async def sync_set_state(body: SyncStateBody) -> dict[str, Any]:
        """``{enabled}``: off tells the relay, which deletes everything stored for the account;
        on re-pushes this device's chats and pulls the others'. ``{side_chats}`` (C9, per
        device): on sends this device's side chats too and pulls the other devices' once
        from the start; off stops both and leaves what was synced where it is."""
        if body.enabled is None and body.side_chats is None:
            raise HTTPException(400, "say enabled or side_chats")
        try:
            if body.enabled is not None:
                await svc.sync.set_enabled(body.enabled)
            if body.side_chats is not None:
                svc.sync.set_side_chats(body.side_chats)
        except CloudError as exc:
            raise _cloud_http(exc) from exc
        return await _sync_view()

    @app.post("/api/sync/delete", dependencies=dep)
    async def sync_delete() -> dict[str, Any]:
        """“Delete synced conversations”: the relay's store emptied; the switch and the local
        chats stay."""
        try:
            await svc.sync.delete_remote()
        except CloudError as exc:
            raise _cloud_http(exc) from exc
        return await _sync_view()

    @app.post("/api/sync/pull", dependencies=dep)
    async def sync_pull() -> dict[str, Any]:
        try:
            applied = await svc.sync.pull()
        except CloudError as exc:
            raise _cloud_http(exc) from exc
        return {"applied": applied, **svc.sync.view()}

    @app.post("/api/cloud/use-as-model", dependencies=dep)
    async def cloud_use_as_model(body: CloudModelBody) -> dict[str, Any]:
        try:
            return await svc.hub.use_as_model(body.model)
        except CloudError as exc:
            raise _cloud_http(exc) from exc

    # ------------------------------------------------------------------ coding agents
    def _coding_error(exc: CodingError) -> HTTPException:
        status = {
            "unknown_agent": 404,
            "no_session": 404,
            "no_device": 404,
            "device_offline": 409,
            "busy": 409,
            "not_installed": 412,
            "not_supported": 412,
            "usage": 400,
            "unknown_action": 400,
        }.get(exc.code, 502)
        return HTTPException(status, f"{exc.message} ({exc.code})")

    @app.get("/api/coding", dependencies=dep)
    async def coding_status(device: str = "") -> dict[str, Any]:
        """Installed agents and recent runs — here, or on another computer of the account."""
        try:
            if device:
                remote = await svc.coding.remote(device, "coding.agents", {})
                runs = await svc.coding.remote(device, "coding.runs", {})
                return {"device": device, **remote, **runs}
            # detection shells out to each CLI and walks its session folders: off the loop
            return {
                "agents": await asyncio.to_thread(svc.coding.agents),
                "runs": svc.coding.list_runs(),
            }
        except CodingError as exc:
            raise _coding_error(exc) from exc

    @app.get("/api/coding/sessions", dependencies=dep)
    async def coding_sessions(
        agent: str = "", limit: int = 30, workspace: str = "", device: str = ""
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 200))
        args: dict[str, Any] = {"agent": agent, "limit": limit, "workspace": workspace}
        try:
            if device:
                return await svc.coding.remote(device, "coding.sessions", args)
            return {
                "sessions": await asyncio.to_thread(
                    svc.coding.sessions, agent or None, limit, workspace or None
                )
            }
        except CodingError as exc:
            raise _coding_error(exc) from exc

    @app.get("/api/coding/sessions/{agent}/{session_id}", dependencies=dep)
    async def coding_session(agent: str, session_id: str, device: str = "") -> dict[str, Any]:
        try:
            if device:
                return await svc.coding.remote(
                    device, "coding.session", {"agent": agent, "session_id": session_id}
                )
            return await asyncio.to_thread(svc.coding.session, agent, session_id)
        except CodingError as exc:
            raise _coding_error(exc) from exc

    @app.post("/api/coding/send", dependencies=dep)
    async def coding_send(body: CodingSendBody) -> dict[str, Any]:
        """A message into a coding agent's session; returns the run at once — follow it on
        the WebSocket (``kind: "coding"``) or poll ``/api/coding``."""
        try:
            if body.device:
                return await svc.coding.remote_send(
                    body.device,
                    {
                        "agent": body.agent,
                        "text": body.text,
                        "session_id": body.session_id,
                        "workspace": body.workspace,
                    },
                )
            return await svc.coding.send(
                body.agent, body.text, session_id=body.session_id, workspace=body.workspace
            )
        except CodingError as exc:
            raise _coding_error(exc) from exc

    @app.post("/api/coding/stop", dependencies=dep)
    async def coding_stop(body: CodingStopBody) -> dict[str, Any]:
        try:
            if body.device:
                return await svc.coding.remote(body.device, "coding.stop", {"run": body.run})
            return {"stopped": svc.coding.stop(body.run)}
        except CodingError as exc:
            raise _coding_error(exc) from exc

    @app.get("/api/hub", dependencies=dep)
    async def hub_status() -> dict[str, Any]:
        return svc.hub.view()

    @app.put("/api/hub", dependencies=dep)
    async def hub_update(body: HubBody) -> dict[str, Any]:
        try:
            if body.name is not None:
                await svc.hub.rename(body.name)
            if body.remote_control is not None:
                svc.hub.set_remote_control(body.remote_control)
            if body.enabled is not None:
                await svc.hub.set_enabled(body.enabled)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return svc.hub.view()

    @app.post("/api/hub/join", dependencies=dep)
    async def hub_join() -> dict[str, Any]:
        if not svc.hub.signed_in:
            raise HTTPException(401, "Sign in to nanoMuse Cloud first.")
        await svc.hub.set_enabled(True)
        return svc.hub.view()

    @app.post("/api/hub/leave", dependencies=dep)
    async def hub_leave() -> dict[str, Any]:
        await svc.hub.set_enabled(False)
        return svc.hub.view()

    @app.post("/api/hub/refresh", dependencies=dep)
    async def hub_refresh() -> dict[str, Any]:
        if svc.hub.client is not None and svc.hub.client.connected.is_set():
            await svc.hub.client.request_devices()
        return svc.hub.view()

    @app.delete("/api/hub/devices/{device_id}", dependencies=dep)
    async def hub_forget(device_id: str) -> dict[str, Any]:
        try:
            await svc.hub.forget(device_id)
        except HubError as exc:
            raise HTTPException(502, exc.message) from exc
        return svc.hub.view()

    @app.post("/api/hub/ask", dependencies=dep)
    async def hub_ask(body: AskDeviceBody) -> dict[str, Any]:
        """The side chat addressed to a device (created if needed); with ``text``, the first
        message in it, which runs on that device."""
        device = svc.hub.device(body.device) or svc.hub.find(body.device)
        if device is None:
            raise HTTPException(404, f"no device matches '{body.device}'")
        thread = svc.hub.ask_device(str(device["id"]))
        event = None
        if body.text.strip():
            try:
                event = svc.send(thread.id, body.text)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        return {"thread": thread.meta(), "event": event}

    @app.put("/api/connections/browser", dependencies=dep)
    async def put_browser(body: BrowserBody) -> dict[str, Any]:
        return conn.set_browser(body.enabled)

    @app.put("/api/connections/calendar", dependencies=dep)
    async def put_calendar(body: CalendarBody) -> dict[str, Any]:
        try:
            return conn.set_calendar(body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connections/calendar/feeds", dependencies=dep)
    async def add_calendar_feed(body: CalendarFeedBody) -> dict[str, Any]:
        try:
            return await conn.add_calendar_feed(body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/connections/calendar/feeds/{name}", dependencies=dep)
    async def delete_calendar_feed(name: str) -> dict[str, Any]:
        if not conn.remove_calendar_feed(name):
            raise HTTPException(404, "no such calendar (feeds from config.toml are removed there)")
        return conn.view()["calendar"]

    @app.post("/api/connections/calendar/test", dependencies=dep)
    async def test_calendar() -> dict[str, Any]:
        return await conn.test_calendar()

    @app.get("/api/calendar", dependencies=dep)
    async def calendar(days: int = Query(2, ge=1, le=31), refresh: int = 0) -> dict[str, Any]:
        if refresh:
            await svc.app.calendar.refresh(force=True)
        else:
            await svc.app.calendar.refresh()
        return svc.calendar_view(days)

    @app.put("/api/connections/contacts", dependencies=dep)
    async def put_contacts(body: ContactsBody) -> dict[str, Any]:
        return conn.set_contacts(body.model_dump(exclude_none=True))

    @app.post("/api/connections/contacts/sources", dependencies=dep)
    async def add_contacts_source(body: ContactsSourceBody) -> dict[str, Any]:
        try:
            return await conn.add_contacts_source(body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connections/contacts/import", dependencies=dep)
    async def import_contacts(
        request: Request, name: str = Query("", max_length=40)
    ) -> dict[str, Any]:
        """The text of a ``.vcf`` file as the request body (no multipart needed; 16 MB max)."""
        raw = await request.body()
        if len(raw) > 16 * 1024 * 1024:
            raise HTTPException(413, "the file is larger than 16 MB")
        try:
            return await conn.import_contacts(name, raw.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/connections/contacts/sources/{name}", dependencies=dep)
    async def delete_contacts_source(name: str) -> dict[str, Any]:
        if not conn.remove_contacts_source(name):
            raise HTTPException(
                404, "no such address book (sources from config.toml are removed there)"
            )
        return conn.view()["contacts"]

    @app.post("/api/connections/contacts/test", dependencies=dep)
    async def test_contacts() -> dict[str, Any]:
        return await conn.test_contacts()

    @app.get("/api/contacts", dependencies=dep)
    async def contacts(
        q: str = Query("", max_length=200), limit: int = Query(8, ge=1, le=50)
    ) -> dict[str, Any]:
        """Look people up as the agent does (``q`` empty: the first people alphabetically)."""
        book = svc.app.contacts
        people = (
            book.search(q, limit=limit)
            if q.strip()
            else sorted(book.contacts, key=lambda c: c.name.lower())[:limit]
        )
        return {"count": len(book), "people": [c.to_dict() for c in people]}

    # ------------------------------------------------------------------ skills
    @app.get("/api/skills", dependencies=dep)
    async def skills() -> dict[str, Any]:
        return svc.skills_view()

    @app.get("/api/skills/{name}", dependencies=dep)
    async def skill(name: str) -> dict[str, Any]:
        view = svc.skill_view(name)
        if view is None:
            raise HTTPException(404, "no such skill")
        return view

    @app.put("/api/skills/{name}", dependencies=dep)
    async def put_skill(name: str, body: SkillBody) -> dict[str, Any]:
        """Write one of your skills from the text of its SKILL.md (a built-in of the same
        name is replaced by it)."""
        try:
            return svc.save_skill(body.content, name=name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"could not write the skill: {exc}") from exc

    @app.delete("/api/skills/{name}", dependencies=dep)
    async def delete_skill(name: str) -> dict[str, Any]:
        if not svc.remove_skill(name):
            raise HTTPException(
                404, "no such skill of yours (built-in skills are switched off, not removed)"
            )
        return svc.skills_view()

    @app.post("/api/skills/{name}/enabled", dependencies=dep)
    async def skill_enabled(name: str, body: SkillEnabledBody) -> dict[str, Any]:
        view = svc.set_skill_enabled(name, body.enabled)
        if view is None:
            raise HTTPException(404, "no such skill")
        return view

    @app.post("/api/skills/import", dependencies=dep)
    async def import_skill(body: SkillImportBody) -> dict[str, Any]:
        try:
            return await svc.import_skill(body.url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — a network error, reported as such
            raise HTTPException(502, f"could not fetch the skill: {exc}") from exc

    @app.post("/api/connections/mcp", dependencies=dep)
    async def add_mcp(body: MCPBody) -> dict[str, Any]:
        try:
            return await conn.add_mcp(body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.delete("/api/connections/mcp/{name}", dependencies=dep)
    async def remove_mcp(name: str) -> dict[str, Any]:
        if not await conn.remove_mcp(name):
            raise HTTPException(404, "no such server (servers from config.toml are removed there)")
        return {"ok": True}

    @app.get("/api/vault", dependencies=dep)
    async def vault_names() -> list[str]:
        return svc.app.vault.names()

    @app.put("/api/vault/{name}", dependencies=dep)
    async def vault_set(name: str, body: SecretBody) -> list[str]:
        try:
            return conn.set_secret(name, body.value)
        except Exception as exc:  # noqa: BLE001 - VaultError on a bad name
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/vault/{name}", dependencies=dep)
    async def vault_delete(name: str) -> dict[str, Any]:
        if not conn.delete_secret(name):
            raise HTTPException(404, "no such secret")
        return {"ok": True}

    @app.post("/api/onboarded", dependencies=dep)
    async def onboarded(body: OnboardedBody) -> dict[str, Any]:
        """The first run is complete. With a model there, the first feed day is written in
        the background right away (contract C5); ``feed_started`` says whether it was."""
        conn.set_onboarded(body.done)
        started = svc.first_feed_day() if body.done else False
        return {"onboarded": body.done, "feed_started": started}

    # ------------------------------------------------------------------ the first conversation (C4)
    @app.get("/api/firstrun", dependencies=dep)
    async def firstrun_state(lang: str = Query("", max_length=10)) -> dict[str, Any]:
        """Where the first conversation stands, the chips for the chooser, and the three
        lines the app speaks first in ``lang`` (``en`` or ``zh``; the opening's own language
        when empty)."""
        return svc.firstrun_view(lang, intro=True)

    @app.post("/api/firstrun/start", dependencies=dep)
    async def firstrun_start(body: FirstRunStartBody) -> dict[str, Any]:
        """Start was pressed: the main chat is bound as the first conversation and the
        setup counts as finished (as ``POST /api/onboarded`` does)."""
        return svc.start_first_conversation(body.lang)

    @app.post("/api/firstrun/pick", dependencies=dep)
    async def firstrun_pick(body: FirstRunPickBody) -> dict[str, Any]:
        """A chip was picked: the name is saved now; the web sends it as the person's
        message next, and the model's reply is its first as itself."""
        name = " ".join(body.name.split())[:MAX_NAME].strip()
        if not name:
            raise HTTPException(400, "name is required")
        try:
            return svc.pick_first_name(name)
        except LookupError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/firstrun/dismiss", dependencies=dep)
    async def firstrun_dismiss() -> dict[str, Any]:
        """The person moved on: the chooser goes, the first conversation counts as over."""
        return svc.dismiss_first_chooser()

    # ------------------------------------------------------------------ browser view
    @app.get("/api/browser/{thread_id}/frames/{frame_id}.jpg", dependencies=dep_or_signed)
    async def browser_frame(thread_id: str, frame_id: str) -> Response:
        jpeg = svc.ui.browser_frame(thread_id, frame_id)
        if jpeg is None:
            raise HTTPException(404, "that frame is gone")
        return Response(
            content=jpeg,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=86400, immutable"},
        )

    @app.post("/api/browser/{thread_id}/control", dependencies=dep)
    async def browser_control(thread_id: str, body: BrowserControlBody) -> dict[str, Any]:
        _thread_or_404(thread_id)
        try:
            return await svc.browser_control(thread_id, body.model_dump(exclude_none=True))
        except LookupError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - playwright raises many error types
            raise HTTPException(502, f"browser error: {str(exc).splitlines()[0][:200]}") from exc

    # ------------------------------------------------------------------ the CLI bridge
    # Not behind the app token: a command the agent runs holds a call token instead, minted
    # for it alone by the shell tool and good while it runs (nanomuse.bridge).
    def _bridge_token(request: Request) -> str | None:
        return request.headers.get("x-nanomuse-bridge") or None

    @app.get("/api/bridge/tools")
    async def bridge_tools(request: Request) -> dict[str, Any]:
        if svc.bridge.tokens.get(_bridge_token(request)) is None:
            raise HTTPException(401, "the call token is missing, unknown or expired")
        return {"ok": True, "tools": svc.bridge.device_tools()}

    @app.post("/api/bridge/{kind}")
    async def bridge_call(kind: str, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(400, "the request body must be JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(400, "the request body must be a JSON object")
        try:
            return await svc.bridge.handle(_bridge_token(request), kind, body)
        except BridgeError as exc:
            raise HTTPException(exc.status, exc.message) from exc

    # ------------------------------------------------------------------ push
    @app.get("/api/push", dependencies=dep)
    async def push_view() -> dict[str, Any]:
        return svc.push.view()

    @app.post("/api/push/subscribe", dependencies=dep)
    async def push_subscribe(body: PushSubscribeBody, request: Request) -> dict[str, Any]:
        try:
            svc.push.subscribe(body.subscription, ua=request.headers.get("user-agent", ""))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return svc.push.view()

    @app.post("/api/push/unsubscribe", dependencies=dep)
    async def push_unsubscribe(body: PushUnsubscribeBody) -> dict[str, Any]:
        svc.push.unsubscribe(body.endpoint)
        return svc.push.view()

    @app.post("/api/push/test", dependencies=dep)
    async def push_test() -> dict[str, Any]:
        return await svc.push.test(svc.profile.name)

    @app.get("/api/feed", dependencies=dep)
    async def feed(limit: int = Query(60, ge=1, le=500)) -> list[dict[str, Any]]:
        return svc.feed(limit)

    @app.get("/api/feed/posts", dependencies=dep)
    async def feed_posts() -> dict[str, Any]:
        return svc.feed_posts()

    @app.put("/api/feed/instructions", dependencies=dep)
    async def feed_instructions(body: FeedInstructionsBody) -> dict[str, Any]:
        try:
            return svc.set_feed_instructions(body.instructions, daily=body.daily, time=body.time)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/feed/posts/refresh", dependencies=dep)
    async def feed_refresh() -> dict[str, Any]:
        try:
            return await svc.write_feed_posts()
        except Exception as exc:  # noqa: BLE001 — the model may be down; the app shows why
            data = svc.feed_posts()
            data["error"] = f"{type(exc).__name__}: {exc}"
            return data

    @app.delete("/api/feed/posts/{post_id}", dependencies=dep)
    async def feed_delete(post_id: str) -> dict[str, Any]:
        if not svc.delete_feed_post(post_id):
            raise HTTPException(404, "no such post")
        return {"ok": True}

    @app.post("/api/tick", dependencies=dep)
    async def tick() -> dict[str, Any]:
        """Run the scheduler's pass now — the phone's alarm calls this when the process was
        asleep — and say when the next wake is due."""
        svc.wake()
        await asyncio.sleep(0)
        when = svc.next_wake_at()
        return {"ok": True, "next_wake_at": when.isoformat(timespec="seconds") if when else None}

    @app.get("/api/upcoming", dependencies=dep)
    async def upcoming() -> dict[str, Any]:
        return svc.upcoming()

    @app.get("/api/files", dependencies=dep)
    async def list_files(limit: int = Query(200, ge=1, le=2000)) -> list[dict[str, Any]]:
        return svc.list_files(limit)

    @app.post("/api/files/upload", dependencies=dep)
    async def upload_file(
        request: Request, name: str = Query(..., min_length=1, max_length=255)
    ) -> dict[str, Any]:
        """A file to attach to a message: the bytes as the request body (no multipart),
        the file name in ``name``. Lands in ``attachments/<date>/`` in the workspace;
        the reply is what to put in ``files`` when sending."""
        limit = svc.settings.server.max_upload_mb * 1024 * 1024
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            raise HTTPException(
                413, f"the file is larger than {svc.settings.server.max_upload_mb} MB"
            )
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > limit:
                raise HTTPException(
                    413, f"the file is larger than {svc.settings.server.max_upload_mb} MB"
                )
            chunks.append(chunk)
        if total == 0:
            raise HTTPException(400, "empty file")
        try:
            return svc.save_upload(name, b"".join(chunks)).model_dump()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/files/{path:path}", dependencies=dep_or_signed)
    async def get_file(path: str, download: bool = False) -> Response:
        try:
            target = svc.resolve_workspace_path(path)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        if not target.is_file():
            raise HTTPException(404, "no such file")
        media, _ = mimetypes.guess_type(str(target))
        if media is None or target.suffix.lower() in (
            ".md",
            ".txt",
            ".log",
            ".csv",
            ".json",
            ".py",
        ):
            media = (
                "text/plain; charset=utf-8"
                if target.suffix.lower() != ".json"
                else "application/json"
            )
        headers: dict[str, str] = {}
        if media.startswith("text/html") or media == "image/svg+xml":
            # Files the agent wrote never run with the app's origin: no token, no API.
            headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups"
        # ``filename=`` lets Starlette write the Content-Disposition header itself, which
        # encodes a name that is not ASCII (报告.txt) instead of failing on it.
        return FileResponse(
            target, media_type=media, headers=headers, filename=target.name if download else None
        )

    # ------------------------------------------------------------------ websocket
    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
        if "token" in ws.query_params:
            # ``?token=`` lands in access logs: taken until 0.1.32, refused now. The socket is
            # accepted for a moment so the client reads why (an older app sees 4401 either way).
            await ws.accept()
            await ws.send_json(
                {"kind": "error", "code": "legacy_token", "message": LEGACY_TOKEN_MESSAGE}
            )
            await ws.close(code=4401, reason="legacy_token")
            return
        await ws.accept()
        if svc.token and not await _ws_first_frame_auth(ws, svc.token):
            await ws.close(code=4401)
            return
        queue = svc.bus.subscribe()
        await ws.send_json({"kind": "hello", "state": svc.state()})
        conn_id = f"ws-{uuid.uuid4().hex[:8]}"
        # one writer for this socket: the pump and the device requests share it
        lock = asyncio.Lock()

        async def send(msg: dict[str, Any]) -> None:
            async with lock:
                await ws.send_json(msg)

        async def pump() -> None:
            while True:
                msg = await queue.get()
                await send(msg)

        pump_task = asyncio.create_task(pump())
        try:
            while True:
                data = await ws.receive_json()
                await _handle_ws_message(svc, ws, data, conn_id=conn_id, send=send)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("websocket closed: {}", exc)
        finally:
            pump_task.cancel()
            svc.bus.unsubscribe(queue)
            svc.phone.detach(conn_id)

    # ------------------------------------------------------------------ static SPA
    if STATIC_DIR.is_dir():
        from fastapi.staticfiles import StaticFiles

        # nanoMuse: the avatars are WebP; older Python mimetypes tables do not know it
        mimetypes.add_type("image/webp", ".webp")

        assets = STATIC_DIR / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> Response:
            if full_path.startswith("api/"):
                # a wrong API path is an error, not the app's HTML with a 200 — clients
                # (and people with curl) see what happened
                raise HTTPException(404, f"no such endpoint: /{full_path}")
            candidate = (STATIC_DIR / full_path).resolve() if full_path else None
            if candidate and STATIC_DIR.resolve() in candidate.parents and candidate.is_file():
                if candidate.name == "sw.js":
                    # the service worker: always revalidated, so a new build reaches phones
                    return FileResponse(
                        candidate,
                        media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"},
                    )
                return FileResponse(candidate)
            index = STATIC_DIR / "index.html"
            if index.is_file():
                return FileResponse(index, headers={"Cache-Control": "no-cache"})
            raise HTTPException(404)

    else:

        @app.get("/", include_in_schema=False)
        async def no_frontend() -> Response:
            return JSONResponse(
                {
                    "message": "nanoMuse API is running, but the web app is not built. "
                    "Run `cd web && npm install && npm run build` or use the CLI (`nanomuse chat`).",
                }
            )

    install_channels(app, svc, dep)  # /api/channels — Feishu, DingTalk, WeCom, Telegram
    return app


WS_AUTH_TIMEOUT_S = 10.0
"""How long a fresh socket has to send ``{"kind": "auth", "token": …}`` before it is closed."""


async def _ws_first_frame_auth(ws: WebSocket, token: str) -> bool:
    """The first frame on a socket opened without ``?token=`` carries the token, so it never
    appears in a URL. Anything else, a wrong token or silence closes the socket with 4401."""
    try:
        data = await asyncio.wait_for(ws.receive_json(), WS_AUTH_TIMEOUT_S)
    except (TimeoutError, ValueError, WebSocketDisconnect, RuntimeError):
        return False
    if not isinstance(data, dict) or data.get("kind") != "auth":
        return False
    given = str(data.get("token") or "")
    return bool(given) and secrets.compare_digest(given.encode(), token.encode())


async def _handle_ws_message(
    svc: MuseService,
    ws: WebSocket,
    data: dict[str, Any],
    conn_id: str = "",
    send: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> None:
    kind = data.get("kind") or data.get("type")
    reply = send or ws.send_json  # one writer per socket when the pump shares it
    try:
        if kind == "device":
            # a phone announcing itself: from now on the server may ask it for its screen
            svc.phone.attach(conn_id, data, reply)
            await reply({"kind": "device_ack", "phone": svc.phone_view()})
        elif kind == "device_result":
            if not svc.phone.resolve(data):
                logger.debug("device result for no pending request: {}", data.get("id"))
        elif kind == "send":
            files = data.get("files")
            svc.send(
                str(data.get("thread") or MAIN_THREAD),
                str(data.get("text", ""))[:20_000],
                files=[str(f) for f in files][:10] if isinstance(files, list) else None,
                language=str(data.get("language") or "")[:20],
                via=str(data.get("via") or "")[:20],
            )
        elif kind == "approval":
            approval_id = str(data.get("id", ""))
            if approval_id in svc.hub.remote_approvals:
                # nanoMuse: a card raised by another device's run — the answer goes back over the hub
                ok = await svc.hub.decide_remote(approval_id, bool(data.get("approved")))
                if not ok:
                    await reply({"kind": "error", "error": "the device did not take the answer"})
                return
            ok = svc.decide(
                approval_id,
                bool(data.get("approved")),
                str(data.get("scope", "once")),
                str(data.get("reason", "")),
            )
            if not ok:
                await reply({"kind": "error", "error": "no pending approval with that id"})
        elif kind == "ping":
            await reply({"kind": "pong", "status": svc.ui.overall_status()})
        elif kind == "auth":
            pass  # a client that sends its token first even though the runtime has none
        else:
            await reply({"kind": "error", "error": f"unknown message kind: {kind}"})
    except (ValueError, PermissionError) as exc:
        await reply({"kind": "error", "error": str(exc)})
    except CloudError as exc:
        await reply({"kind": "error", "error": exc.describe(), "code": exc.code})


__all__ = ["STATIC_DIR", "create_app"]
