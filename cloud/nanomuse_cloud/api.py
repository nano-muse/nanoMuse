"""HTTP: the sign-up endpoints the app calls, and the OpenAI-shaped proxy.

    POST /v1/auth/code        {identifier}                      → 204 (400 phone_region: a number the SMS sender cannot reach)
    POST /v1/auth/verify      {identifier, code, device, invite?} → {api_key, base_url, account, tokens, models}
    POST /v1/auth/login       {identifier, password, device}    → the same, for accounts that set a password
    POST /v1/auth/password    {password, current?}              → 204 (set / change; "" + current removes)
    GET  /v1/me                                                 → account, tokens, spend (¥ spent / pool / left), invite, contribute, usage by kind, models, recent, nudges
    GET  /v1/nudges                                             → when the apps may ask for a star (0.18; public, cached an hour; the operator's policy over the defaults)
    GET  /v1/me/invite                                          → the invite code and link, who came with it, what they brought
    GET  /v1/estimate         ?images=5&clips=4                 → what that would cost next to what is left (nothing charged)
    GET  /v1/me/sessions                                        → live sign-ins (device, via, when; the current one marked)
    DELETE /v1/me/sessions/{prefix}                             → 204 (sign one device out)
    GET  /v1/me/events                                          → the account's own timeline (sign-ins, password changes…)
    POST /v1/me/contribute {on}                                 → Data controls: "help improve nanoMuse's AI models" — keep the text of my chat turns (the default for new accounts is IMPROVE_DEFAULT)
    DELETE /v1/me/samples                                       → delete every turn kept from me
    GET  /v1/sync/state                                         → 0.19: {enabled, cursor, counts, limits, working[]} — conversation sync between the account's devices
    PUT  /v1/sync/state       {enabled}                         → the switch; off deletes everything stored
    GET  /v1/sync/changes     ?since=&limit=&scope=&tail=       → conversations and messages after a cursor, in seq order (0.20: scope=all|main, tail=K with since=0)
    POST /v1/sync/changes     {device, conversations, messages} → {cursor, accepted, rejected}; the other devices hear a hub `sync` frame
    POST /v1/sync/working     {cid, working, device?}           → 0.20: 204; the other devices hear a hub `working` frame (presence, kept 10 min in memory)
    DELETE /v1/sync/changes                                     → the store emptied, the switch kept
    DELETE /v1/sync/conversations/{cid}                         → one chat tombstoned everywhere
    POST /v1/auth/sign-out                                      → 204 (revokes this key)
    POST /v1/auth/sign-out-all {all?}                           → {signed_out} (every other device; all=true takes this one too)
    POST /v1/auth/session-key {device?, ttl_s?}                 → {api_key, expires_at} (a key that lapses on its own; nanoMuse Web's containers)
    POST /v1/auth/delete                                        → 204 (the whole account, every key)
    GET  /v1/models                                             → OpenAI list, with modalities; for a member, the usable models under the operator's key after the menu (catalog: true)
    POST /v1/chat/completions                                   → forwarded; stream or not
    POST /v1/images/generations                                 → DashScope native, returned as b64_json
    POST /v1/images/edits     multipart                         → same, with the picture
    POST /api/v1/services/aigc/video-generation/video-synthesis → DashScope's async video API, relayed
    GET  /api/v1/tasks/{id}                                     → its task poll (own tasks only)
    GET  /api/v1/uploads?action=getPolicy&model=…               → its temporary-storage policy
    GET  /healthz
    WS   /v1/hub                                                → the devices of one account meet (hub.py)
    GET  /v1/devices                                            → remembered devices with presence
    DELETE /v1/devices/{id}                                     → forget an offline device
    GET  /app/                                                  → the web console (static)
    GET  /app/admin/                                            → the operator's page (static; asks for the admin token)
    POST /v1/admin/grant      X-Admin-Token  {account_id | identifier, tokens}
    POST /v1/admin/credit     X-Admin-Token  {account_id | identifier, cny, note?} → more into the account's pool (negative takes away, 0.16)
    POST /v1/admin/pool       X-Admin-Token  {account_id | identifier, left_cny | grant_cny | delta_cny, note?} → the pool set to any figure (0.16)
    POST /v1/admin/pool/batch X-Admin-Token  {account_ids | all, left_cny | grant_cny | delta_cny, note?} → the same for a set, or everyone limited (0.16)
    POST /v1/admin/disable    X-Admin-Token  {account_id | identifier, disabled}
    POST /v1/admin/unlimited  X-Admin-Token  {account_id | identifier, unlimited}  → a member: no limit
    POST /v1/admin/delete     X-Admin-Token  {account_id | identifier}
    GET  /v1/admin/nudges     X-Admin-Token                     → the nudges policy in force, the defaults, whether the page set it and when (0.18)
    PUT  /v1/admin/nudges     X-Admin-Token  {version?, star{…}} | {reset: true} → set the policy (version bumped by the server) or go back to the defaults
    GET  /v1/admin/accounts   X-Admin-Token                     → with identifiers in clear, tokens and money
    GET  /v1/admin/accounts/{id} X-Admin-Token ?days=30         → one account in full: usage by kind/model/day, sign-ins, devices, addresses, timeline
    GET  /v1/admin/accounts/{id}/ledger X-Admin-Token ?limit=&before= → the account's statement, every line, page by page (before = last id shown)
    GET  /v1/admin/accounts/{id}/events X-Admin-Token ?limit=&before= → the account's timeline, every entry, page by page
    GET  /v1/admin/address    X-Admin-Token  ?ip=…              → the accounts seen from one address
    GET  /v1/admin/usage      X-Admin-Token  ?days=14           → charged tokens and yuan per day and kind
    GET  /v1/admin/overview   X-Admin-Token  ?days=30           → the dashboard: accounts, today / week / period by kind and model, signals, events
    GET  /v1/admin/events     X-Admin-Token  ?limit=200&kind=…  → the timeline across accounts (never message content)
    GET  /v1/admin/series     X-Admin-Token  ?days=30           → by day: sign-ins, new / active accounts, invites, data switches turned on; devices by kind and OS; nanoMuse Web's counts
    GET  /v1/admin/traffic    X-Admin-Token  ?days=30           → the site: pages, visitors, downloads per file, referrers, GitHub stars and release downloads (TRAFFIC_DB)
    GET  /v1/admin/demo       X-Admin-Token  ?days=30           → the phone in the browser: visitors with addresses and browsers, every demo and what it used (WEB_ADMIN_URL)
    GET  /v1/admin/data       X-Admin-Token  ?days=30           → Data controls: accounts with the switch on, kept turns by day / model / app / account, switches on and off, the newest turns
    GET  /v1/admin/samples    X-Admin-Token  ?account_id=&limit=&since=&before=&before_id= → kept turns (accounts with the switch on only)
    GET  /v1/admin/samples/export X-Admin-Token ?since=&account_id= → the same as JSON lines, without account ids or addresses
    GET  /v1/admin/sync       X-Admin-Token                     → conversation sync in aggregate: accounts on / off, conversations, messages, bytes (never a text)

The video paths mirror the provider's own so the app's VideoGen, which
already speaks that API, only needs to point its host at the relay.

Errors are OpenAI-shaped: {"error": {"message", "type", "code"}} with the
status the app expects (401 bad key, 402 out of tokens, 429 rate limit).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, Request, Response, UploadFile, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import ClientDisconnect

from . import __version__
from . import client as client_info
from .catalog import Catalog
from .config import ModelSpec, Settings
from .controls import ControlError
from .geo import Geo, collect_ips, group_places
from .github_stats import GitHubCollector
from .hub import Hub
from .identifiers import BadIdentifier, parse
from .service import Caller, Cloud, CloudError, Usage, dumps, estimate_tokens, prompt_chars, usage_from_json
from .stats import Stats, api_group
from .sync import DEFAULT_PAGE, SyncStore

log = logging.getLogger("nanomuse_cloud.api")


def error_response(status: int, code: str, message: str, extra: dict | None = None) -> JSONResponse:
    """OpenAI's error shape, so the apps' clients parse it, plus whatever fields the app can
    act on (`allowance_exhausted` says what is left and where the three ways on lead)."""
    return JSONResponse(
        status_code=status, content={"error": {"message": message, "type": "nanomuse_cloud", "code": code, **(extra or {})}}
    )


def thinking_requested(body: dict) -> bool | None:
    """What a chat request says about reasoning, in any of the dialects the apps speak:
    True when it asks for it (`enable_thinking: true`, `thinking: {"type": "enabled"}`, a
    `reasoning_effort` other than `none`, a `thinking_budget`), False when it declines, None
    when it says nothing."""
    if "enable_thinking" in body:
        return bool(body["enable_thinking"])
    thinking = body.get("thinking")
    if isinstance(thinking, bool):
        return thinking
    if isinstance(thinking, dict) and thinking.get("type") in ("enabled", "disabled"):
        return thinking["type"] == "enabled"
    effort = body.get("reasoning_effort")
    if isinstance(effort, str) and effort.strip():
        return effort.strip().lower() != "none"
    if body.get("thinking_budget"):
        return True
    return None


def apply_chat_defaults(body: dict, defaults: dict) -> None:
    """The operator's defaults (CHAT_DEFAULTS, `{"enable_thinking": false}` as shipped) go
    in where the request is silent. Reasoning is one thing said in several ways, so the
    `enable_thinking` default follows what the request already said with `reasoning_effort`
    or `thinking` — Model Studio refuses `reasoning_effort: low` next to `enable_thinking:
    false` ("'reasoning_effort' must be 'none' when 'enable_thinking' is false"), which is
    exactly what an app's thinking-level badge plus the shipped default used to produce."""
    wants = thinking_requested(body)
    for k, v in defaults.items():
        if k == "enable_thinking" and wants is not None:
            body.setdefault("enable_thinking", wants)
            continue
        body.setdefault(k, v)
    effort = body.get("reasoning_effort")
    if body.get("enable_thinking") is False and isinstance(effort, str) and effort.strip().lower() != "none":
        body["reasoning_effort"] = "none"


def upstream_detail(kind: str, status: int, model: str, raw: bytes | str) -> str:
    """The line an `upstream.error` event keeps: the kind, the status, the model and the
    provider's own words (its `error.message`, one line, trimmed) — enough to see *why* a
    request failed from the admin page, never the request's content."""
    message = ""
    try:
        obj = json.loads(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
        err = obj.get("error") if isinstance(obj, dict) else None
        if isinstance(err, dict):
            message = str(err.get("message") or err.get("code") or "")
        elif isinstance(err, str):
            message = err
        elif isinstance(obj, dict):
            message = str(obj.get("message") or "")
    except (ValueError, AttributeError, UnicodeDecodeError):
        message = ""
    message = " ".join(message.split())
    line = f"{kind} {status} {model}".strip()
    return f"{line}: {message[:200]}" if message else line


# the provider's content check saying no — Bailian's native and OpenAI-compatible spellings
CONTENT_CHECK_MARKS = ("data_inspection_failed", "datainspectionfailed", "inappropriate content", "green net")


def content_check_refusal(raw: bytes | str) -> bool:
    """True when the provider refused because its content check rejected the words, not
    because anything was wrong with the request — the person needs different words, not a
    bug report."""
    text = (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw).lower()
    return any(mark in text for mark in CONTENT_CHECK_MARKS)


def relay_error_body(status: int, raw: bytes) -> dict:
    """What the app is told when the provider says no. A 400 is about the request and
    the provider's own words are the useful ones — except a content check, which gets a
    plain sentence; everything else is the relay's problem (its key, its quota, the
    provider's day) and is said in words that do not send the person hunting for an API
    key they never had. The provider's text rides along under ``upstream`` for the curious
    and for bug reports."""
    upstream = ""
    try:
        up = json.loads(raw)
        if isinstance(up, dict):
            e = up.get("error")
            if isinstance(e, dict) and e.get("message"):
                upstream = str(e["message"])[:300]
            elif up.get("message"):
                upstream = str(up["message"])[:300]
    except ValueError:
        pass
    if status == 400 and content_check_refusal(raw):
        message, code = "The model provider's content check declined this request; try different words", "content_rejected"
    elif status == 400:
        message, code = upstream or "The model provider refused the request", "upstream_400"
    elif status in (401, 403):
        message, code = "The relay's model provider refused its key; the operator has been told", "upstream_auth"
    elif status == 404:
        message, code = "The model provider does not know this model right now", "upstream_model"
    elif status == 429:
        message, code = "The model provider is busy; try again in a moment", "upstream_busy"
    else:
        message, code = "The model provider is having trouble; try again in a moment", f"upstream_{status}"
    err: dict = {"message": message, "type": "upstream", "code": code}
    if upstream and (status != 400 or code == "content_rejected"):
        err["upstream"] = upstream
    return {"error": err}


# where the provider keeps the pictures it makes: its own API host and Alibaba Cloud OSS buckets
PROVIDER_HOST_SUFFIXES = (".aliyuncs.com", ".alicdn.com")


def _provider_url_ok(url: object, own_hosts: tuple[str, ...] = ()) -> bool:
    """Only URLs on the provider's own hosts are fetched (the relay must not become an open proxy):
    the configured API hosts themselves, or https on Alibaba Cloud's storage domains."""
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if not host or parts.scheme not in ("http", "https"):
        return False
    if host in own_hosts:
        return True
    return parts.scheme == "https" and host.endswith(PROVIDER_HOST_SUFFIXES)


def create_app(
    settings: Settings | None = None,
    cloud: Cloud | None = None,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
    github_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings()
    cloud = cloud or Cloud(settings)

    http = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.upstream_timeout_s, connect=20.0),
        transport=upstream_transport,
        follow_redirects=False,
    )

    # where an address is (geo.py) — the file is fetched in the background on start
    geo = Geo(settings.geoip_path, settings.geoip_url, settings.geoip_v6_url, enabled=settings.geoip_enabled)

    # 0.22: the GitHub collector (stars, forks, release downloads once a day) and the
    # operator's threshold rules, both run from the server's own loop
    collector = GitHubCollector(cloud.db, settings.github_repo_path, settings.github_token, settings.github_api, transport=github_transport)

    async def _rules_loop() -> None:
        while True:
            await asyncio.sleep(60)
            # off the loop: a *notify* rule sends an e-mail, and SMTP may take its whole timeout
            await asyncio.to_thread(cloud.rules_tick)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        geo.ensure()
        if settings.github_collect:
            collector.start()
        rules_task = asyncio.create_task(_rules_loop(), name="control-rules")
        try:
            yield
        finally:
            rules_task.cancel()
            await collector.stop()
            await http.aclose()

    app = FastAPI(title="nanoMuse Cloud", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.cloud = cloud
    app.state.settings = settings
    app.state.http = http
    app.state.geo = geo
    app.state.collector = collector

    def with_places(out: dict) -> dict:
        """The admin page's answers carry addresses; this adds ``places`` — ``{ip: place}``
        for the ones the database knows — so every address is shown with where it is."""
        geo.ensure()  # a fetch that failed earlier is tried again after a while
        out["places"] = geo.places(collect_ips(out)) if geo.ready else {}
        return out

    @app.exception_handler(CloudError)
    async def _cloud_error(request: Request, e: CloudError) -> JSONResponse:
        request.state.error_code = e.code  # the middleware counts it under that name
        return error_response(e.status, e.code, e.message, e.extra)

    @app.exception_handler(ControlError)
    async def _control_error(request: Request, e: ControlError) -> JSONResponse:
        request.state.error_code = "bad_request"
        return error_response(400, "bad_request", str(e))

    # what still answers while the *Cloud service* switch is off: the health check, the
    # console and its API, and the public figures (which say the service is paused)
    OPEN_WHILE_PAUSED = ("/healthz", "/app", "/v1/admin/", "/v1/config")
    SERVICE_PAUSED_MESSAGE = "nanoMuse Cloud is paused by its operator for now; your sign-in and your data are kept. Try again later."

    def client_ip(request: Request) -> str:
        return client_info.visitor_ip(request.headers, request.client.host if request.client else None)

    def client_place(request: Request):
        """Where the request came from (geo.py), for the region in /v1/me and the "ways on"
        of a refusal; None when the database is not there or the address is unplaced."""
        return geo.place(client_ip(request)) if geo.ready else None

    @app.middleware("http")
    async def _remember_client(request: Request, call_next):
        # the address and the client software behind this request, for the rows the
        # database writes while it is handled (client.py)
        token = client_info.set_current(client_info.from_headers(request.headers, request.client.host if request.client else None))
        path = request.url.path
        request.state.error_code = ""
        try:
            if not cloud.controls.on("cloud_service") and not path.startswith(OPEN_WHILE_PAUSED):
                # 0.22: the operator switched the service off — a plain 503 for every API
                # call; the console, the health check and /v1/config keep answering
                response: Response = error_response(503, "service_paused", SERVICE_PAUSED_MESSAGE, {"paused": True})
                request.state.error_code = "service_paused"
            else:
                response = await call_next(request)
            # 0.22: the daily counters behind the console's statistics (stats.py) — the
            # call by route group, and an error by its code — written as the answer leaves
            if not path.startswith("/app"):  # the console's own files are not API calls
                code = getattr(request.state, "error_code", "")
                if code or response.status_code >= 400:
                    cloud.db.daily_add("error", code or f"http_{response.status_code}")
                cloud.db.daily_add("api", api_group(path))
            elif "cache-control" not in response.headers:
                # the console's script and page are revalidated on every load (an ETag answers
                # 304 when nothing changed), so a deploy reaches the next reload instead of
                # waiting out the browser's heuristic freshness — the likeliest way a fixed
                # console still looks broken for a day after its deploy
                response.headers["Cache-Control"] = "no-cache"
            return response
        finally:
            client_info.reset(token)

    def caller_dep(authorization: str | None = Header(default=None)) -> Caller:
        token = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        return cloud.authenticate(token)

    def upstream_headers() -> dict[str, str]:
        if not settings.upstream_key:
            raise CloudError(503, "upstream_unconfigured", "nanoMuse Cloud has no model key configured")
        return {"Authorization": f"Bearer {settings.upstream_key}", "Content-Type": "application/json"}

    # -- health ----------------------------------------------------------------

    @app.get("/healthz")
    async def healthz() -> dict:
        # `paused` (0.22): the operator's switches that are off — the process is fine either way
        return {
            "ok": True,
            "version": __version__,
            "models": [m.id for m in settings.models],
            "paused": [k for k, v in cloud.controls.paused().items() if v],
        }

    @app.get("/v1/config")
    async def public_config() -> Response:
        """The figures a client prints before anyone signs in — the allowance, the invite
        bonus, whether sign-up is open, the links — live from the operator's settings (0.15),
        so no app needs a release to show a new number. No secrets, no auth, a minute's cache."""
        return JSONResponse(cloud.public_config(), headers={"Cache-Control": "public, max-age=60"})

    # -- sign-up -----------------------------------------------------------------

    @app.post("/v1/auth/code", status_code=204)
    async def auth_code(request: Request) -> Response:
        body = await _json(request)
        try:
            ident = parse(str(body.get("identifier", "")))
        except BadIdentifier as e:
            raise CloudError(400, "bad_identifier", "Enter a mainland phone number or an e-mail address") from e
        await asyncio.to_thread(cloud.request_code, ident, client_ip(request))
        return Response(status_code=204)

    @app.post("/v1/auth/verify")
    async def auth_verify(request: Request) -> dict:
        body = await _json(request)
        try:
            ident = parse(str(body.get("identifier", "")))
        except BadIdentifier as e:
            raise CloudError(400, "bad_identifier", "Enter a mainland phone number or an e-mail address") from e
        code = str(body.get("code", "")).strip()
        if not code.isdigit() or len(code) != 6:
            raise CloudError(400, "code_wrong", "The code is six digits")
        device = str(body.get("device", ""))[:80]
        invite = str(body.get("invite", ""))[:32]
        key, caller, created = await asyncio.to_thread(cloud.verify_code, ident, code, device, invite)
        me = cloud.me(caller, client_place(request))
        return {"api_key": key, "created": created, **me}

    @app.post("/v1/auth/login")
    async def auth_login(request: Request) -> dict:
        """The password way in: no message to wait for, for people who set one."""
        body = await _json(request)
        try:
            ident = parse(str(body.get("identifier", "")))
        except BadIdentifier as e:
            raise CloudError(400, "bad_identifier", "Enter a mainland phone number or an e-mail address") from e
        password = str(body.get("password", ""))
        if not password:
            raise CloudError(400, "password_required", "Enter the password")
        device = str(body.get("device", ""))[:80]
        key, caller = await asyncio.to_thread(cloud.login_password, ident, password, device, client_ip(request))
        me = cloud.me(caller, client_place(request))
        return {"api_key": key, "created": False, **me}

    @app.post("/v1/auth/password", status_code=204)
    async def auth_password(request: Request, caller: Caller = Depends(caller_dep)) -> Response:
        """Set or change the password (`current` when one exists, unless this
        key came from a code sign-in just now); {"password": ""} with `current`
        removes it."""
        body = await _json(request)
        password = str(body.get("password", ""))
        current = body.get("current")
        current = str(current) if current is not None else None
        if password == "":
            if not current:
                raise CloudError(400, "password_required", "Enter the current password to remove it")
            await asyncio.to_thread(cloud.clear_password, caller, current)
        else:
            await asyncio.to_thread(cloud.set_password, caller, password, current)
        return Response(status_code=204)

    @app.get("/v1/nudges")
    async def public_nudges() -> Response:
        """When the apps may ask for a star on GitHub (0.18, nudges.py): the operator's policy
        over the defaults every client also carries. No key, an hour's cache; the same object
        rides along in /v1/me for a signed-in client."""
        return JSONResponse(cloud.nudges(), headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/v1/me")
    async def me(request: Request, caller: Caller = Depends(caller_dep)) -> dict:
        return cloud.me(caller, client_place(request))

    @app.get("/v1/me/invite")
    async def me_invite(caller: Caller = Depends(caller_dep)) -> dict:
        """The account's invite code and link, who came with it, the credit earned."""
        return cloud.invite_view(caller)

    @app.get("/v1/estimate")
    async def estimate(
        images: int = 0,
        clips: int = 0,
        image_model: str = "",
        video_model: str = "",
        size: str = "",
        caller: Caller = Depends(caller_dep),
    ) -> dict:
        """What `images` pictures and `clips` clips would cost, next to what is left
        today — the app asks before a new face. Nothing is charged."""
        return cloud.estimate(caller, images, clips, image_model, video_model, size or None)

    @app.post("/v1/me/contribute")
    async def me_contribute(request: Request, caller: Caller = Depends(caller_dep)) -> dict:
        """Opt in (or out of) contributing chat turns to the community's training set."""
        body = await _json(request)
        return cloud.set_contribute(caller, bool(body.get("on")))

    @app.get("/v1/me/profile")
    async def me_profile(face: bool = True, caller: Caller = Depends(caller_dep)) -> dict:
        """The agent's name and look, shared by the account's devices; ``?face=false`` leaves
        the pictures out (a device checks ``rev`` first and fetches them only when it moved)."""
        return cloud.profile(caller, with_face=face)

    @app.put("/v1/me/profile")
    async def me_put_profile(request: Request, caller: Caller = Depends(caller_dep)) -> dict:
        """A device wrote the name or the look (last writer wins), or its ``connectors``
        (0.17: merged by device — the writer's entries replaced, the others' kept; never a
        credential, 400 `no_secrets_in_profile`); every other device of the account hears
        ``{"type": "profile", "rev"}`` on the hub."""
        body = await _json(request)
        device = str(body.pop("device", "") or "")
        out = cloud.put_profile(caller, device, body)
        hub = getattr(app.state, "hub", None)
        if hub is not None:
            await hub.broadcast_profile(caller.account_id, int(out["rev"]), device[:80])
        return out

    @app.delete("/v1/me/profile", status_code=204)
    async def me_delete_profile(caller: Caller = Depends(caller_dep)) -> Response:
        cloud.delete_profile(caller)
        return Response(status_code=204)

    @app.delete("/v1/me/samples")
    async def me_delete_samples(caller: Caller = Depends(caller_dep)) -> dict:
        return {"deleted": cloud.delete_samples(caller)}

    @app.get("/v1/me/sessions")
    async def me_sessions(caller: Caller = Depends(caller_dep)) -> dict:
        return {"sessions": cloud.sessions(caller)}

    @app.delete("/v1/me/sessions/{prefix}", status_code=204)
    async def me_revoke_session(prefix: str, caller: Caller = Depends(caller_dep)) -> Response:
        cloud.revoke_session(caller, prefix)
        return Response(status_code=204)

    @app.get("/v1/me/events")
    async def me_events(limit: int = 50, caller: Caller = Depends(caller_dep)) -> dict:
        return {"events": cloud.events(caller, limit)}

    @app.post("/v1/auth/sign-out", status_code=204)
    async def sign_out(caller: Caller = Depends(caller_dep)) -> Response:
        cloud.sign_out(caller)
        return Response(status_code=204)

    @app.post("/v1/auth/session-key")
    async def session_key(request: Request, caller: Caller = Depends(caller_dep)) -> dict:
        """A key for this account that expires on its own: {"device", "ttl_s"} → {"api_key",
        "expires_at"}. nanoMuse Web starts a person's container with one and keeps no
        standing key of theirs (0.13)."""
        body = await _json(request)
        try:
            ttl_s = int(body.get("ttl_s") or 30 * 86400)
        except (TypeError, ValueError) as e:
            raise CloudError(400, "bad_request", "ttl_s must be a number of seconds") from e
        key, expires_at = cloud.session_key(caller, str(body.get("device") or "session"), ttl_s)
        return {"api_key": key, "expires_at": expires_at}

    @app.post("/v1/auth/sign-out-all")
    async def sign_out_all(request: Request, caller: Caller = Depends(caller_dep)) -> dict:
        """Every other device; {"all": true} takes this one too."""
        body = await _json(request)
        n = cloud.sign_out_all(caller, keep_current=not bool(body.get("all")))
        return {"signed_out": n}

    @app.post("/v1/auth/delete", status_code=204)
    async def delete_account(caller: Caller = Depends(caller_dep)) -> Response:
        hub = getattr(app.state, "hub", None)
        if hub is not None:
            await hub.drop_account(caller.account_id)
        # the live "working" notes of the account go with it — they are memory, not rows,
        # and `delete_account` below cannot reach them
        sync = getattr(app.state, "sync", None)
        if sync is not None:
            sync.presence.forget(caller.account_id)
        cloud.delete_account(caller)
        return Response(status_code=204)

    # -- conversation sync (0.19, sync.py): the same chats on every device of the account -----------

    sync_store = SyncStore(cloud.db)
    app.state.sync = sync_store

    def sync_dep(caller: Caller = Depends(caller_dep)) -> Caller:
        """0.22: every sync call but reading the state is refused with 503 `sync_paused`
        while the operator's *Conversation sync* switch is off; the stored texts stay."""
        if not cloud.controls.on("sync"):
            raise CloudError(
                503,
                "sync_paused",
                "Conversation sync is paused on this relay for now; what is stored is kept and your devices keep working on their own.",
                {"paused": True},
            )
        return caller

    @app.get("/v1/sync/state")
    async def sync_state(caller: Caller = Depends(caller_dep)) -> dict:
        out = sync_store.state(caller.account_id)
        out["paused"] = not cloud.controls.on("sync")
        return out

    @app.put("/v1/sync/state")
    async def sync_set_state(request: Request, caller: Caller = Depends(sync_dep)) -> dict:
        """{"enabled": false} turns sync off and deletes everything stored; true turns it on
        again with an empty store. The account's timeline notes the switch, never a text."""
        body = await _json(request)
        if "enabled" not in body:
            raise CloudError(400, "bad_request", "Say enabled: true or false")
        enabled = bool(body["enabled"])
        out = sync_store.state(caller.account_id)
        if out["enabled"] != enabled:
            out = sync_store.set_enabled(caller.account_id, enabled)
            cloud.note(caller.account_id, "sync.on" if enabled else "sync.off")
        return out

    @app.get("/v1/sync/changes")
    async def sync_changes(
        since: int = 0, limit: int = DEFAULT_PAGE, scope: str = "all", tail: int = 0, caller: Caller = Depends(sync_dep)
    ) -> dict:
        """0.20: `scope=main` for the main conversation only; `tail=K` with `since=0` for the
        newest K messages and their conversations (a fresh device's first pull)."""
        cloud.db.daily_add("sync", "pulls")
        return sync_store.changes(caller.account_id, since, limit, scope=scope, tail=tail)

    @app.post("/v1/sync/working", status_code=204)
    async def sync_working(request: Request, caller: Caller = Depends(sync_dep)) -> Response:
        """0.20: {cid, working, device?} — a turn started or ended on that conversation on the
        calling device (`device` as `push` carries it, else `X-Nanomuse-Device`). The
        account's other sockets hear a hub `working` frame; the relay remembers a `true` for
        ten minutes. Presence, not data: nothing is written."""
        body = await _json(request)
        cid = str(body.get("cid") or "")
        if not cid or "working" not in body:
            raise CloudError(400, "bad_request", "Say cid and working: true or false")
        device = str(body.get("device") or request.headers.get("x-nanomuse-device", ""))[:80]
        frame = sync_store.set_working(caller.account_id, cid, device, bool(body["working"]))
        hub = getattr(app.state, "hub", None)
        if hub is not None:
            await hub.notify_working(caller.account_id, frame)
        return Response(status_code=204)

    @app.post("/v1/sync/changes")
    async def sync_push(request: Request, caller: Caller = Depends(sync_dep)) -> dict:
        body = await _json(request)
        device = str(body.get("device") or "")[:80]
        messages = body.get("messages") or []
        out = sync_store.push(caller.account_id, device, body.get("conversations") or [], messages)
        # 0.22: the day's sync volume for the console — counts, never a text
        cloud.db.daily_add("sync", "pushes")
        cloud.db.daily_add("sync", "messages_in", len(messages) if isinstance(messages, list) else 0)
        cloud.db.daily_add("sync", "accepted", int(out.get("accepted") or 0))
        cloud.db.daily_add("sync", "rejected", len(out.get("rejected") or []))
        hub = getattr(app.state, "hub", None)
        if hub is not None and out["accepted"]:
            await hub.notify_sync(caller.account_id, int(out["cursor"]), device)
        return out

    @app.delete("/v1/sync/changes")
    async def sync_wipe(caller: Caller = Depends(sync_dep)) -> dict:
        out = sync_store.wipe(caller.account_id)
        cloud.note(caller.account_id, "sync.deleted")
        return out

    @app.delete("/v1/sync/conversations/{cid}")
    async def sync_delete_conversation(cid: str, request: Request, caller: Caller = Depends(sync_dep)) -> dict:
        out = sync_store.delete_conversation(caller.account_id, cid)
        hub = getattr(app.state, "hub", None)
        if hub is not None:
            await hub.notify_sync(caller.account_id, int(out["cursor"]), request.headers.get("x-nanomuse-device", "")[:80])
        return out

    # -- models ------------------------------------------------------------------------

    catalog = Catalog(
        ttl_s=settings.catalog_ttl_s,
        probe_ttl_s=settings.catalog_probe_ttl_s,
        store=cloud.db if settings.catalog_probe else None,
    )
    app.state.catalog = catalog

    @app.get("/v1/models")
    async def models(caller: Caller = Depends(caller_dep)) -> dict:
        """The menu — and, for a member who may name any model, the usable models under the
        operator's key after it (`listed: false`, `catalog: true`), so the apps' pickers
        offer them (catalog.py). The menu's entries come first, in the menu's order."""
        out = cloud.models_for(caller)
        if not (settings.catalog_enabled and out["nanomuse"].get("any_model")):
            return out
        entries = await catalog.get(app.state.http, settings.upstream_base, settings.upstream_key)
        menu = {m["id"] for m in out["data"]}
        added = 0
        for e in entries:
            if e.id in menu:
                continue
            spec = settings.unlisted_model(e.id, e.kind)
            if spec is None:
                continue
            pub = spec.to_public()
            pub["nanomuse"]["catalog"] = True
            pub["nanomuse"]["vision"] = e.vision
            pub["nanomuse"]["verified"] = e.verified  # the probe's word, not the name's
            if e.kind == "chat":
                pub["architecture"]["input_modalities"] = ["text", "image"] if e.vision else ["text"]
            out["data"].append(pub)
            added += 1
        # how many the key has beyond the menu, and why none if none (the provider's answer)
        out["nanomuse"]["catalog"] = {"models": added, "error": catalog.error, "probing": catalog.probing}
        return out

    @app.get("/v1/models/{model_id}")
    async def model(model_id: str, kind: str = "", caller: Caller = Depends(caller_dep)) -> dict:
        """One model: the menu's by id; for a member, also one the menu does not carry,
        given the `kind` it is for (`?kind=chat`) — how an app checks a typed id."""
        m = settings.model(model_id)
        if m is None and kind:
            m = cloud.model_for(model_id, kind, caller)
        if m is None:
            more = " on the menu; add ?kind=chat|image|video to ask for one beyond it" if cloud.any_model(caller) else ""
            raise CloudError(404, "model_not_offered", f"nanoMuse Cloud does not offer {model_id!r}{more}")
        return m.to_public()

    # -- chat -----------------------------------------------------------------------------

    @app.post("/v1/chat/completions")
    async def chat(request: Request, caller: Caller = Depends(caller_dep)) -> Response:
        body = await _json(request)
        spec = cloud.model_for(str(body.get("model", "")), "chat", caller)
        # a relay without a key answers before anything is held: a hold taken here and never
        # settled would count against the account's in-flight limit until it timed out
        headers = upstream_headers()
        request_id = uuid.uuid4().hex[:16]
        # held at a typical turn's price while it runs; settled when the reply is in
        cloud.check_budget(caller, request_id=request_id, hold_uy=cloud.chat_reserve_uy(spec), place=client_place(request))
        body["model"] = spec.upstream
        apply_chat_defaults(body, settings.chat_defaults)
        stream = bool(body.get("stream"))
        if stream:
            opts = body.get("stream_options") if isinstance(body.get("stream_options"), dict) else {}
            opts["include_usage"] = True
            body["stream_options"] = opts
        # Fields that would let a caller reach around the account: none of the
        # OpenAI request fields are dangerous, but `user` is ours to set so the
        # provider's abuse tooling can tell accounts apart without knowing them.
        body["user"] = caller.account_id[:32]
        url = settings.upstream_base.rstrip("/") + "/chat/completions"
        fallback_prompt_tokens = math.ceil(prompt_chars(body.get("messages") or []) / 3)
        # For an account that opted in, the turn is kept once it is answered (service.keep_sample)
        # with the platform and language hints from the headers and, since 0.10, the address
        # (the export for training drops the address along with the account id).
        sample_meta = (
            {
                "ua": (request.headers.get("user-agent") or "")[:120],
                "lang": (request.headers.get("accept-language") or "")[:40],
                "ip": client_ip(request),
            }
            if caller.contribute
            else None
        )
        sample_messages = body.get("messages") if caller.contribute and isinstance(body.get("messages"), list) else []

        if not stream:
            try:
                try:
                    r = await http.post(url, headers=headers, content=dumps(body).encode())
                except httpx.HTTPError as e:
                    log.warning("upstream error: %s", e)
                    raise CloudError(502, "upstream", "The model provider did not answer") from e
                if r.status_code >= 400:
                    cloud.note(caller.account_id, "upstream.error", upstream_detail("chat", r.status_code, spec.id, r.content))
                    return _relay_error(r, request)
                try:
                    obj = r.json()
                except ValueError as e:
                    raise CloudError(502, "upstream", "The model provider sent an unreadable reply") from e
                usage = usage_from_json(obj)
                text = _reply_text(obj)
                if usage is None:
                    usage = Usage(fallback_prompt_tokens, estimate_tokens(text))
                charged = cloud.charge_chat(caller, spec, usage.prompt, usage.completion, request_id, cached_tokens=usage.cached)
            finally:
                cloud.settle(caller, request_id)
            if sample_meta is not None:
                cloud.keep_sample(caller, spec.id, sample_messages, text, usage.prompt, usage.completion, sample_meta)
            if isinstance(obj, dict):
                obj["model"] = spec.id
                obj.setdefault("nanomuse", {})["charged"] = charged
            return JSONResponse(content=obj, headers={"x-nanomuse-charged": str(charged), "x-nanomuse-request": request_id})

        async def gen() -> AsyncIterator[bytes]:
            usage: Usage | None = None
            text_len = 0
            # the assistant's words: the estimate when the provider sends no usage, and the
            # kept turn of a contributing account
            reply: list[str] = []
            # A request the provider refused, or dropped before a single token, costs the
            # account nothing; a stream that broke off midway is charged for what arrived.
            failed = False
            try:
                async with http.stream("POST", url, headers=headers, content=dumps(body).encode()) as r:
                    if r.status_code >= 400:
                        raw = await r.aread()
                        cloud.note(caller.account_id, "upstream.error", upstream_detail("chat", r.status_code, spec.id, raw))
                        failed = True
                        err = relay_error_body(r.status_code, raw)
                        cloud.db.daily_add("error", str(err["error"]["code"]))  # the 200 has left; count it here
                        yield f"data: {dumps(err)}\n\n".encode()
                        yield b"data: [DONE]\n\n"
                        return
                    async for line in r.aiter_lines():
                        if line.startswith("data:"):
                            payload = line[5:].strip()
                            if payload and payload != "[DONE]":
                                try:
                                    obj = json.loads(payload)
                                except ValueError:
                                    obj = None
                                if isinstance(obj, dict):
                                    u = usage_from_json(obj)
                                    if u is not None:
                                        usage = u
                                    for ch in obj.get("choices") or []:
                                        d = ch.get("delta") if isinstance(ch, dict) else None
                                        if isinstance(d, dict) and isinstance(d.get("content"), str):
                                            text_len += len(d["content"])
                                            reply.append(d["content"])
                                    obj["model"] = spec.id
                                    payload = dumps(obj)
                            yield f"data: {payload}\n\n".encode()
                        elif line == "":
                            continue
                        else:
                            yield (line + "\n").encode()
            except httpx.HTTPError as e:
                log.warning("upstream stream error: %s %s", type(e).__name__, e)
                cloud.note(caller.account_id, "upstream.error", f"chat stream broke {spec.id}: {type(e).__name__}")
                failed = usage is None and text_len == 0
                err = {"error": {"message": "The model provider stopped answering", "type": "nanomuse_cloud", "code": "upstream"}}
                yield f"data: {dumps(err)}\n\n".encode()
                yield b"data: [DONE]\n\n"
            finally:
                if not failed:
                    if usage is None:
                        usage = Usage(fallback_prompt_tokens, estimate_tokens("".join(reply)))
                    cloud.charge_chat(caller, spec, usage.prompt, usage.completion, request_id, cached_tokens=usage.cached)
                    if sample_meta is not None:
                        cloud.keep_sample(caller, spec.id, sample_messages, "".join(reply), usage.prompt, usage.completion, sample_meta)
                cloud.settle(caller, request_id)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "x-nanomuse-request": request_id},
        )

    # -- images -------------------------------------------------------------------------------

    # the provider draws only a couple of pictures per account at a time: everyone's
    # requests pass through this gate, and a 429 behind it is waited out (see Settings)
    image_gate = asyncio.Semaphore(max(1, settings.image_concurrency))
    IMAGE_PAUSES = (2.0, 4.0, 8.0, 12.0, 15.0)

    async def _dashscope_post_image(url: str, payload: bytes) -> httpx.Response:
        """The upstream call, behind the gate, tried again on a 429 or a 5xx."""
        async with image_gate:
            attempt = 0
            while True:
                try:
                    r = await http.post(url, headers=upstream_headers(), content=payload)
                except httpx.HTTPError as e:
                    raise CloudError(502, "upstream", "The image provider did not answer") from e
                if r.status_code != 429 and r.status_code < 500:
                    return r
                if attempt >= settings.image_retries:
                    return r
                pause = IMAGE_PAUSES[min(attempt, len(IMAGE_PAUSES) - 1)]
                retry_after = r.headers.get("retry-after", "")
                if retry_after.isdigit():
                    pause = min(max(float(retry_after), 1.0), 30.0)
                log.info("dashscope image HTTP %s; again in %.0fs (%d/%d)", r.status_code, pause, attempt + 1, settings.image_retries)
                await asyncio.sleep(pause)
                attempt += 1

    async def _dashscope_image(model: str, content: list[dict], parameters: dict) -> bytes:
        host = settings.dashscope_base.rstrip("/")
        url = f"{host}/services/aigc/multimodal-generation/generation"
        payload = {"model": model, "input": {"messages": [{"role": "user", "content": content}]}, "parameters": parameters}
        r = await _dashscope_post_image(url, dumps(payload).encode())
        if r.status_code == 429:
            log.warning("dashscope image still 429 after %d retries", settings.image_retries)
            raise CloudError(429, "provider_busy", "The image provider is busy right now; try again in a moment", {"retry_after": 20})
        if r.status_code >= 400:
            msg = ""
            try:
                msg = r.json().get("message", "")
            except ValueError:
                pass
            log.warning("dashscope image HTTP %s: %s", r.status_code, r.text[:300])
            if r.status_code == 400 and content_check_refusal(r.content):
                raise CloudError(400, "content_rejected", "The image provider's content check declined this prompt; try different words")
            raise CloudError(502, "upstream", f"The image provider refused ({r.status_code}{': ' + msg if msg else ''})")
        try:
            image_url = r.json()["output"]["choices"][0]["message"]["content"][0]["image"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise CloudError(502, "upstream", "The image provider sent no picture") from e
        own_hosts = tuple((urlsplit(u).hostname or "").lower() for u in (settings.dashscope_base, settings.upstream_base))
        if not _provider_url_ok(image_url, own_hosts):
            log.warning("dashscope image URL off the provider's hosts: %s", str(image_url)[:120])
            raise CloudError(502, "upstream", "The image provider sent a picture from somewhere unexpected")
        try:
            img = await http.get(image_url)
        except httpx.HTTPError as e:
            raise CloudError(502, "upstream", "Could not fetch the picture") from e
        if img.status_code >= 400:
            raise CloudError(502, "upstream", "Could not fetch the picture")
        return img.content

    def _size_param(size: str | None) -> str:
        s = (size or "1024x1024").lower().replace("x", "*")
        return s if "*" in s else "1024*1024"

    @app.post("/v1/images/generations")
    async def images_generations(request: Request, caller: Caller = Depends(caller_dep)) -> Response:
        body = await _json(request)
        spec = cloud.model_for(str(body.get("model", "")), "image", caller)
        size = _size_param(body.get("size"))
        prompt = str(body.get("prompt", "")).strip()
        if not prompt:
            raise CloudError(400, "bad_request", "prompt is required")
        n = int(body.get("n") or 1)
        if n != 1:
            raise CloudError(400, "bad_request", "nanoMuse Cloud draws one picture per request")
        params = {"size": size, "watermark": False}
        if spec.upstream.startswith("qwen-image"):
            params["prompt_extend"] = False
        request_id = uuid.uuid4().hex[:16]
        cloud.check_budget(
            caller, minimum=spec.per_image, cost_uy=spec.image_cost_uy(size), request_id=request_id, place=client_place(request)
        )
        try:
            png = await _dashscope_image(spec.upstream, [{"text": prompt}], params)
            charged = cloud.charge_image(caller, spec, 1, request_id, size=size)
        finally:
            cloud.settle(caller, request_id)
        return JSONResponse(
            content={"created": int(time.time()), "data": [{"b64_json": base64.b64encode(png).decode()}], "nanomuse": {"charged": charged}},
            headers={"x-nanomuse-charged": str(charged)},
        )

    @app.post("/v1/images/edits")
    async def images_edits(
        request: Request,
        caller: Caller = Depends(caller_dep),
        model: str = Form(...),
        prompt: str = Form(...),
        n: int = Form(1),
        size: str | None = Form(None),
        image: UploadFile = File(...),
    ) -> Response:
        spec = cloud.model_for(model, "image", caller)
        if n != 1:
            raise CloudError(400, "bad_request", "nanoMuse Cloud draws one picture per request")
        # read one byte past the cap rather than the whole picture first: larger than the
        # limit is refused, so nothing beyond it is ever held
        data = await image.read(settings.max_request_bytes + 1)
        if len(data) > settings.max_request_bytes:
            raise CloudError(413, "too_large", "The picture is too large")
        mime = image.content_type or "image/png"
        # Same rules as the app's own DashScope path: qwen-image-3.x and wan take
        # the picture themselves; an older text-only qwen-image is posed by
        # qwen-image-edit-max.
        three_x = spec.upstream.startswith("qwen-image-3") or spec.upstream.startswith("wan")
        edit_model = spec.upstream if (three_x or "edit" in spec.upstream) else "qwen-image-edit-max"
        params = {"size": _size_param(size), "prompt_extend": False, "watermark": False} if three_x else {"n": 1, "watermark": False}
        content = [{"image": f"data:{mime};base64," + base64.b64encode(data).decode()}, {"text": prompt}]
        request_id = uuid.uuid4().hex[:16]
        # the picture sent in is billed too (price_image_in), on top of the one drawn
        cloud.check_budget(
            caller,
            minimum=spec.per_image,
            cost_uy=spec.image_cost_uy(_size_param(size), inputs=1),
            request_id=request_id,
            place=client_place(request),
        )
        try:
            png = await _dashscope_image(edit_model, content, params)
            charged = cloud.charge_image(caller, spec, 1, request_id, size=_size_param(size), inputs=1)
        finally:
            cloud.settle(caller, request_id)
        return JSONResponse(
            content={"created": int(time.time()), "data": [{"b64_json": base64.b64encode(png).decode()}], "nanomuse": {"charged": charged}},
            headers={"x-nanomuse-charged": str(charged)},
        )

    # -- video: the provider's asynchronous API, relayed under its own paths ------------------------
    #
    # The app's VideoGen submits a task, polls it, downloads the clip from the
    # URL the task ends with (the provider's storage, not us), and uploads a
    # first frame to the provider's temporary storage beforehand. Each call is
    # forwarded with the operator's key; the user's key never sees the provider.
    # Status codes come back as the provider sent them so the app's probe
    # (an empty task: accepted or 400 = the model exists, 404 = it does not)
    # keeps working; 401/403 from the provider are the operator's problem and
    # turn into 502. A clip is charged when its task is first seen SUCCEEDED —
    # a probe's task fails at once and costs nothing, here or upstream.

    VIDEO_PATH = "/services/aigc/video-generation/video-synthesis"

    def _dashscope_reply(r: httpx.Response) -> Response:
        if r.status_code in (401, 403):
            log.error("dashscope refused the relay's key: HTTP %s %s", r.status_code, r.text[:200])
            return JSONResponse(status_code=502, content={"code": "upstream", "message": "The video provider refused the relay's key"})
        media = r.headers.get("content-type", "application/json")
        return Response(status_code=r.status_code, content=r.content, media_type=media.split(";")[0])

    def _clip_seconds(body: dict, spec: ModelSpec) -> float:
        """The seconds the app asked for (`parameters.duration`), else the model's
        fixed or shortest length; the provider bills per output second."""
        params = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
        try:
            return float(params.get("duration") or spec.clip_seconds)
        except (TypeError, ValueError):
            return spec.clip_seconds

    def _clip_resolution(body: dict) -> str | None:
        """The resolution the app asked for — Wan's `parameters.resolution` ("480P"), else
        the tier a `parameters.size` ("1280*720") falls in; None when neither is said."""
        params = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
        res = params.get("resolution")
        if isinstance(res, str) and res.strip():
            return res.strip().upper()
        size = params.get("size")
        if isinstance(size, str) and size.strip():
            try:
                short = min(int(p) for p in size.lower().replace("*", "x").split("x")[:2])
            except ValueError:
                return None
            return "1080P" if short >= 1080 else "720P" if short >= 720 else "480P"
        return None

    @app.post("/api/v1" + VIDEO_PATH)
    async def video_synthesis(request: Request, caller: Caller = Depends(caller_dep)) -> Response:
        body = await _json(request)
        spec = cloud.model_for(str(body.get("model", "")), "video", caller)
        # A probe (no input) costs nothing upstream and is not priced here either.
        probe = not body.get("input")
        clip_cost = 0 if probe else spec.video_cost_uy(_clip_seconds(body, spec), _clip_resolution(body))
        # reserved while the submission runs; once accepted, the task row holds the clip's
        # price against the allowance (db.pending_video_cost) until the clip is charged
        headers = upstream_headers()  # before the hold, as for chat: no key, nothing held
        request_id = uuid.uuid4().hex[:16]
        cloud.check_budget(caller, minimum=spec.per_clip, cost_uy=clip_cost, request_id=request_id, place=client_place(request))
        body["model"] = spec.upstream
        headers["X-DashScope-Async"] = "enable"
        if request.headers.get("x-dashscope-ossresourceresolve"):
            headers["X-DashScope-OssResourceResolve"] = request.headers["x-dashscope-ossresourceresolve"]
        try:
            try:
                r = await http.post(settings.dashscope_base.rstrip("/") + VIDEO_PATH, headers=headers, content=dumps(body).encode())
            except httpx.HTTPError as e:
                log.warning("dashscope video error: %s", e)
                raise CloudError(502, "upstream", "The video provider did not answer") from e
            if r.status_code < 400:
                try:
                    task_id = str(r.json()["output"]["task_id"])
                except (ValueError, KeyError, TypeError):
                    task_id = ""
                if task_id:
                    cloud.db.insert_video_task(task_id, caller.account_id, spec.id, cost_uy=clip_cost, probe=probe)
                    log.info("video task %s for %s: %s%s", task_id[:12], caller.account_id[:8], spec.id, " (probe)" if probe else "")
            else:
                log.warning("dashscope video HTTP %s: %s", r.status_code, r.text[:300])
        finally:
            cloud.settle(caller, request_id)
        return _dashscope_reply(r)

    @app.get("/api/v1/tasks/{task_id}")
    async def video_task(task_id: str, caller: Caller = Depends(caller_dep)) -> Response:
        task = cloud.db.video_task(task_id)
        if task is None or task["account_id"] != caller.account_id:
            raise CloudError(404, "no_task", "No such task")
        try:
            r = await http.get(settings.dashscope_base.rstrip("/") + f"/tasks/{task_id}", headers=upstream_headers())
        except httpx.HTTPError as e:
            raise CloudError(502, "upstream", "The video provider did not answer") from e
        if r.status_code < 400:
            try:
                status = r.json().get("output", {}).get("task_status")
            except (ValueError, AttributeError):
                status = None
            if status and status != task["status"]:
                cloud.db.set_video_status(task_id, str(status))
            if status == "SUCCEEDED" and cloud.db.mark_video_charged(task_id):
                try:
                    spec = cloud.model_for(str(task["model"]), "video", caller)
                except CloudError:
                    spec = None  # a model gone from the menu since the task was submitted
                if spec is not None:
                    charged = cloud.charge_video(caller, spec, task_id[:16], cost_uy=int(task["cost_uy"] or 0))
                    log.info("video task %s done for %s: charged %d", task_id[:12], caller.account_id[:8], charged)
        return _dashscope_reply(r)

    @app.get("/api/v1/uploads")
    async def video_upload_policy(request: Request, caller: Caller = Depends(caller_dep)) -> Response:
        if request.query_params.get("action") != "getPolicy":
            raise CloudError(400, "bad_request", "action=getPolicy is the only upload call the relay makes")
        spec = cloud.model_for(request.query_params.get("model", ""), "video", caller)
        cloud.check_budget(caller, minimum=spec.per_clip, cost_uy=spec.video_cost_uy(spec.clip_seconds), place=client_place(request))
        try:
            r = await http.get(
                settings.dashscope_base.rstrip("/") + "/uploads",
                params={"action": "getPolicy", "model": spec.upstream},
                headers=upstream_headers(),
            )
        except httpx.HTTPError as e:
            raise CloudError(502, "upstream", "The video provider did not answer") from e
        return _dashscope_reply(r)

    # -- the hub: devices of one account, across networks ------------------------------------------

    if settings.hub_enabled:
        hub = Hub(cloud, frame_limit=settings.hub_frame_limit)
        app.state.hub = hub

        @app.websocket("/v1/hub")
        async def hub_socket(ws: WebSocket) -> None:
            # the socket's address and client, for the device rows written while it is open
            token = client_info.set_current(client_info.from_headers(ws.headers, ws.client.host if ws.client else None))
            try:
                if not (cloud.controls.on("hub") and cloud.controls.on("cloud_service")):
                    # 0.22: the operator's *Hub* (or *Cloud service*) switch is off — accept
                    # so the close code reaches the app, then 4003 `hub_paused` (docs/hub.md)
                    await ws.accept()
                    await ws.close(code=4003, reason="hub_paused")
                    return
                # Header auth for apps; browsers authenticate in the hello frame instead.
                caller: Caller | None = None
                auth = ws.headers.get("authorization")
                if auth and auth.lower().startswith("bearer "):
                    try:
                        caller = cloud.authenticate(auth[7:].strip())
                    except CloudError as e:
                        # accept first: a close before the handshake reaches the app as an HTTP
                        # 403 and looks like the network, not like the key (docs/hub.md says
                        # 4001). Then the error frame with the code, as the hello path does.
                        await ws.accept()
                        await ws.send_text(json.dumps({"type": "error", "code": e.code, "message": e.message}))
                        await ws.close(code=4001, reason=e.code)
                        return
                await hub.serve(ws, caller)
            finally:
                client_info.reset(token)

        def hub_dep(caller: Caller = Depends(caller_dep)) -> Caller:
            if not cloud.controls.on("hub"):
                raise CloudError(
                    503, "hub_paused", "The device hub is paused on this relay for now; each device keeps working on its own.", {"paused": True}
                )
            return caller

        @app.get("/v1/devices")
        async def devices(caller: Caller = Depends(hub_dep)) -> dict:
            return {"devices": hub.devices(caller.account_id)}

        @app.delete("/v1/devices/{device_id}", status_code=204)
        async def forget_device(device_id: str, caller: Caller = Depends(hub_dep)) -> Response:
            hub.forget(caller.account_id, device_id)
            await hub.broadcast_devices(caller.account_id)
            return Response(status_code=204)

        console_dir = Path(__file__).parent / "console"
        if console_dir.is_dir():
            app.mount("/app", StaticFiles(directory=str(console_dir), html=True), name="console")

    # -- admin ------------------------------------------------------------------------------------

    def admin_dep(x_admin_token: str | None = Header(default=None)) -> None:
        if not settings.admin_token or not secrets.compare_digest((x_admin_token or "").encode(), settings.admin_token.encode()):
            raise CloudError(401, "admin", "admin token required")

    @app.get("/v1/admin/accounts", dependencies=[Depends(admin_dep)])
    async def admin_accounts() -> dict:
        accounts = cloud.admin_accounts()
        hub = getattr(app.state, "hub", None)
        if hub is not None:
            for a in accounts:
                a["devices"] = [{k: d[k] for k in ("id", "name", "kind", "os", "online", "last_seen")} for d in hub.devices(a["id"])]
        return with_places({"accounts": accounts, "settings": {**cloud.admin_settings(), "version": __version__}})

    @app.get("/v1/admin/usage", dependencies=[Depends(admin_dep)])
    async def admin_usage(days: int = 14) -> dict:
        return {"days": cloud.admin_usage(max(1, min(days, 90)))}

    @app.get("/v1/admin/health", dependencies=[Depends(admin_dep)])
    async def admin_health() -> dict:
        """What the self-check timer reads (deploy/nanomuse-hk/selfcheck.sh): aggregates
        only — requests under way, the hub's counters, the last hour's refusals and upstream
        errors, the database — never an account. `ok` is false when something needs a look."""
        hub = getattr(app.state, "hub", None)
        t = int(time.time())
        hour = cloud.db.events_since(t - 3600)
        in_flight = cloud.in_flight.snapshot()
        upstream_errors = int(hour.get("upstream.error", 0))
        db_health = cloud.db.health()
        out: dict[str, Any] = {
            "ok": True,
            "version": __version__,
            "time": t,
            "in_flight": {"requests": sum(in_flight.values()), "accounts": len(in_flight), "limit": cloud.in_flight.limit},
            "hub": hub.stats() if hub is not None else None,
            "last_hour": {
                "requests": cloud.db.requests_since_all(t - 3600),
                "upstream_errors": upstream_errors,
                "budget_refused": int(hour.get("budget.refused", 0)),
                "sign_ins": int(hour.get("sign_in.code", 0)) + int(hour.get("sign_in.password", 0)),
                "sign_in_failures": int(hour.get("sign_in.failed", 0)),
            },
            "db": db_health,
            "upstream_key": bool(settings.upstream_key),
        }
        problems: list[str] = []
        if upstream_errors >= 20:
            problems.append(f"{upstream_errors} upstream errors in the last hour")
        if hub is not None and hub.flood_closes > 0:
            problems.append(f"{hub.flood_closes} hub sockets closed for flooding since start")
        if not db_health["writable"]:
            problems.append("the database is not writable")
        if not settings.upstream_key:
            problems.append("no upstream key")
        out["ok"] = not problems
        out["problems"] = problems
        return out

    @app.get("/v1/admin/overview", dependencies=[Depends(admin_dep)])
    async def admin_overview(days: int = 30) -> dict:
        out = cloud.admin_overview(max(1, min(days, 365)))
        hub = getattr(app.state, "hub", None)
        out["online_devices"] = hub.online_count() if hub is not None else 0
        out["version"] = __version__
        out["geo"] = geo.status()
        return with_places(out)

    @app.get("/v1/admin/series", dependencies=[Depends(admin_dep)])
    async def admin_series(days: int = 30) -> dict:
        out = cloud.admin_series(max(1, min(days, 365)))
        hub = getattr(app.state, "hub", None)
        out["online_devices"] = hub.online_count() if hub is not None else 0
        out["web"] = await web_info()
        return out

    async def web_info() -> dict | None:
        """nanoMuse Web's counts from the gateway next door (WEB_INFO_URL); None when it
        is not configured or does not answer — the panel then says so."""
        if not settings.web_info_url:
            return None
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(settings.web_info_url)
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    async def demo_admin(params: dict) -> dict | None:
        """The showcase's visitors from its gateway (WEB_ADMIN_URL with WEB_ADMIN_TOKEN):
        None when not configured or not answering."""
        if not settings.web_admin_url or not settings.web_admin_token:
            return None
        try:
            async with httpx.AsyncClient(timeout=4.0) as c:
                r = await c.get(settings.web_admin_url, params=params, headers={"X-Admin-Token": settings.web_admin_token})
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    @app.get("/v1/admin/demo", dependencies=[Depends(admin_dep)])
    async def admin_demo(days: int = 30) -> dict:
        """The phone in the browser: who tried it from where and with what, every demo and
        what it used (the showcase gateway's /api/demo/admin, passed through)."""
        data = await demo_admin({"days": max(1, min(days, 365))})
        return with_places({"available": data is not None, **(data or {})})

    @app.get("/v1/admin/traffic", dependencies=[Depends(admin_dep)])
    async def admin_traffic(days: int = 30) -> dict:
        return cloud.admin_traffic(max(1, min(days, 365)))

    @app.get("/v1/admin/places", dependencies=[Depends(admin_dep)])
    async def admin_places(days: int = 30) -> dict:
        """Where people are: accounts by their latest address, and the period's requests,
        sign-ins and new accounts by address — counted by country and province (ip2region);
        the showcase's visitors too when its gateway answers. `geo` says whether the
        database is there at all."""
        days = max(1, min(days, 365))
        geo.ensure()
        counts = cloud.db.address_counts(int(time.time()) - days * 86400)
        out: dict = {"days": days, "geo": geo.status()}
        for key, rows in counts.items():
            out[key] = group_places(rows, geo) if geo.ready else []
        demo = await demo_admin({"days": days})
        if demo is not None and geo.ready:
            by_ip: dict[str, int] = {}
            for v in demo.get("visitors") or []:
                ip = v.get("last_ip") or v.get("first_ip") or ""
                if ip:
                    by_ip[ip] = by_ip.get(ip, 0) + 1
            out["demo_visitors"] = group_places(list(by_ip.items()), geo)
        else:
            out["demo_visitors"] = None
        return out

    @app.get("/v1/admin/catalog", dependencies=[Depends(admin_dep)])
    async def admin_catalog() -> dict:
        """The models under the key beyond the menu, and what the probes found: which
        answer, which read pictures, which the provider refuses."""
        if settings.catalog_enabled:
            await catalog.get(app.state.http, settings.upstream_base, settings.upstream_key)
        return {"enabled": settings.catalog_enabled, "probe": settings.catalog_probe, **catalog.summary()}

    @app.get("/v1/admin/data", dependencies=[Depends(admin_dep)])
    async def admin_data(days: int = 30) -> dict:
        return cloud.admin_data(max(1, min(days, 365)))

    @app.get("/v1/admin/accounts/{account_id}", dependencies=[Depends(admin_dep)])
    async def admin_account(account_id: str, days: int = 30) -> dict:
        out = cloud.admin_account(account_id, max(1, min(days, 365)))
        hub = getattr(app.state, "hub", None)
        if hub is not None:
            out["devices"] = hub.devices(account_id)
        # the showcase's record of this person (the visitor id there is the account id here)
        out["demo"] = await demo_admin({"account": account_id})
        return with_places(out)

    @app.get("/v1/admin/accounts/{account_id}/ledger", dependencies=[Depends(admin_dep)])
    async def admin_account_ledger(account_id: str, limit: int = 200, before: int = 0) -> dict:
        """One page of the account's statement, newest first; `before` is the id of the
        last row shown. Every line is reachable this way."""
        if cloud.db.account(account_id) is None:
            raise CloudError(404, "no_account", "No such account")
        return with_places(cloud.ledger_page(account_id, max(1, min(limit, 1000)), max(0, before)))

    @app.get("/v1/admin/accounts/{account_id}/events", dependencies=[Depends(admin_dep)])
    async def admin_account_events(account_id: str, limit: int = 200, before: int = 0) -> dict:
        if cloud.db.account(account_id) is None:
            raise CloudError(404, "no_account", "No such account")
        return with_places(cloud.events_page(account_id, max(1, min(limit, 1000)), max(0, before)))

    @app.get("/v1/admin/address", dependencies=[Depends(admin_dep)])
    async def admin_address(ip: str = "") -> dict:
        """The accounts seen from one address, and where it is."""
        if not ip.strip():
            raise CloudError(400, "bad_request", "Say which address: ?ip=…")
        out = cloud.admin_address(ip)
        place = geo.place(ip.strip())
        out["place"] = place.as_dict() if place is not None else None
        return with_places(out)

    @app.get("/v1/admin/events", dependencies=[Depends(admin_dep)])
    async def admin_events(limit: int = 200, kind: str = "") -> dict:
        kinds = tuple(k.strip() for k in kind.split(",") if k.strip()) or None
        return with_places({"events": cloud.admin_events(limit, kinds)})

    @app.get("/v1/admin/samples", dependencies=[Depends(admin_dep)])
    async def admin_samples(account_id: str = "", limit: int = 100, since: int = 0, before: int = 0, before_id: str = "") -> dict:
        """Contributed chat turns — only from accounts that turned contribution on. Pages
        with `before` (the last row's ts) and `before_id` (its id), newest first."""
        return with_places(
            {
                "samples": cloud.admin_samples(account_id or None, since, limit, before, before_id[:64]),
                "total": cloud.db.sample_count(account_id or None),
            }
        )

    @app.get("/v1/admin/samples/export", dependencies=[Depends(admin_dep)])
    async def admin_samples_export(since: int = 0, account_id: str = "") -> Response:
        """The training set as JSON lines (one turn per line, no account ids, no addresses);
        with `account_id`, one account's turns. One whole response with its length, not a
        stream: the set is small, and a stream that stopped short — a proxy compressing it,
        the connection dropping — reached the browser as "Failed to fetch" with nothing to
        say why."""
        body = "".join(cloud.export_samples(since, account_id or None)).encode()
        name = f"nanomuse-samples-{account_id[:8]}-{since}" if account_id else f"nanomuse-samples-{since}"
        return Response(
            body,
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": f'attachment; filename="{name}.jsonl"',
                "Cache-Control": "no-store",
                "Content-Length": str(len(body)),
            },
        )

    @app.get("/v1/admin/sync", dependencies=[Depends(admin_dep)])
    async def admin_sync() -> dict:
        """Conversation sync in aggregate (0.19): accounts with it on and off, how many
        conversations and messages are stored and their size. Never a text, never an account."""
        return sync_store.admin_totals()

    @app.post("/v1/admin/grant", dependencies=[Depends(admin_dep)])
    async def admin_grant(request: Request) -> dict:
        body = await _json(request)
        account_id = cloud.admin_resolve(str(body.get("account_id", "")), str(body.get("identifier", "")))
        return cloud.admin_grant(account_id, int(body.get("tokens", 0)))

    @app.post("/v1/admin/credit", dependencies=[Depends(admin_dep)])
    async def admin_credit(request: Request) -> dict:
        """{account_id | identifier, cny, note?}: credit into the account's pool — for a
        merged pull request, a good bug report."""
        body = await _json(request)
        account_id = cloud.admin_resolve(str(body.get("account_id", "")), str(body.get("identifier", "")))
        try:
            cny = float(body.get("cny", 0))
        except (TypeError, ValueError) as e:
            raise CloudError(400, "bad_request", "cny is a number") from e
        return cloud.admin_credit(account_id, cny, str(body.get("note", ""))[:200])

    @app.post("/v1/admin/credit-all", dependencies=[Depends(admin_dep)])
    async def admin_credit_all(request: Request) -> dict:
        """{cny, note?}: the same credit into every limited account's pool (0.15)."""
        body = await _json(request)
        try:
            cny = float(body.get("cny", 0))
        except (TypeError, ValueError) as e:
            raise CloudError(400, "bad_request", "cny is a number") from e
        return cloud.admin_credit_all(cny, str(body.get("note", ""))[:200])

    @app.post("/v1/admin/pool", dependencies=[Depends(admin_dep)])
    async def admin_pool(request: Request) -> dict:
        """{account_id | identifier, left_cny | grant_cny | delta_cny, note?}: set one account's
        pool (0.16) — to what should be left now, to a lifetime total, or by a difference up or
        down. Never below zero."""
        body = await _json(request)
        account_id = cloud.admin_resolve(str(body.get("account_id", "")), str(body.get("identifier", "")))
        return cloud.admin_set_pool(account_id, body)

    @app.post("/v1/admin/pool/batch", dependencies=[Depends(admin_dep)])
    async def admin_pool_batch(request: Request) -> dict:
        """{account_ids: [...] | all: true, left_cny | grant_cny | delta_cny, note?}: the same
        change to a set of accounts, or to every limited one (0.16)."""
        return cloud.admin_set_pool_many(await _json(request))

    @app.get("/v1/admin/settings", dependencies=[Depends(admin_dep)])
    async def admin_settings_get() -> dict:
        """The settings the page may change (0.15): the value in force, the environment's,
        whether the page set it, and how many accounts a raised allowance would reach."""
        return cloud.runtime_settings()

    @app.post("/v1/admin/settings", dependencies=[Depends(admin_dep)])
    async def admin_settings_set(request: Request) -> dict:
        """{allowance_cny?, invite_bonus_cny?, signup_open?}: set (a value) or clear back to
        the environment (null). In force at once, kept across restarts."""
        return cloud.admin_update_settings(await _json(request))

    # -- 0.22: the Controls page — switches, thresholds, the audit log -------------------------

    def _actor(request: Request) -> str:
        """Who flipped it, for the audit line: the page sends `actor` (a name typed once), the
        CLI its user, else the word console."""
        return str(request.headers.get("x-admin-actor") or "console")[:80]

    @app.get("/v1/admin/controls", dependencies=[Depends(admin_dep)])
    async def admin_controls() -> dict:
        """Every switch with who set it and when, every threshold rule with when it last fired,
        the account count the rules are measured against, the last audit lines."""
        return cloud.controls.view(cloud.db.account_counts()["total"])

    @app.get("/v1/admin/controls/rules", dependencies=[Depends(admin_dep)])
    async def admin_rules() -> dict:
        return {"rules": cloud.controls.rules(), "accounts_total": cloud.db.account_counts()["total"]}

    @app.post("/v1/admin/controls/rules", dependencies=[Depends(admin_dep)])
    async def admin_rule_add(request: Request) -> dict:
        """{threshold: N, action: close_signups|pause_allowance|pause_sync|notify, enabled?, note?}.
        A rule fires once, when the account count reaches N (checked as an account is made and
        once a minute); `rearm` on PUT lets it fire again."""
        body = await _json(request)
        return cloud.controls.add_rule(body, str(body.get("actor") or _actor(request))[:80])

    @app.put("/v1/admin/controls/rules/{rule_id}", dependencies=[Depends(admin_dep)])
    async def admin_rule_update(rule_id: int, request: Request) -> dict:
        body = await _json(request)
        if cloud.db.rule(rule_id) is None:
            raise CloudError(404, "not_found", "No such rule")
        return cloud.controls.update_rule(rule_id, body, str(body.get("actor") or _actor(request))[:80])

    @app.delete("/v1/admin/controls/rules/{rule_id}", status_code=204, dependencies=[Depends(admin_dep)])
    async def admin_rule_delete(rule_id: int, request: Request) -> Response:
        if cloud.db.rule(rule_id) is None:
            raise CloudError(404, "not_found", "No such rule")
        cloud.controls.delete_rule(rule_id, _actor(request))
        return Response(status_code=204)

    @app.post("/v1/admin/controls/evaluate", dependencies=[Depends(admin_dep)])
    async def admin_rules_evaluate() -> dict:
        """Check the rules against the account count now (what the minute timer does)."""
        fired = await asyncio.to_thread(cloud.evaluate_thresholds)
        return {"fired": fired, "accounts_total": cloud.db.account_counts()["total"]}

    @app.post("/v1/admin/controls/notify-test", dependencies=[Depends(admin_dep)])
    async def admin_notify_test(request: Request) -> dict:
        """Send a test notice to ADMIN_EMAIL the way a *notify* rule would."""
        ok = await asyncio.to_thread(
            cloud.controls.notify,
            "test notice",
            ["This is a test from the console's Controls page.", "这是控制台「控制」页发出的测试邮件。"],
            _actor(request),
        )
        return {"sent": ok, "configured": cloud.controls.can_notify}

    @app.get("/v1/admin/controls/audit", dependencies=[Depends(admin_dep)])
    async def admin_controls_audit(limit: int = 200) -> dict:
        return {"audit": cloud.controls.audit(max(1, min(limit, 1000)))}

    @app.post("/v1/admin/controls/{key}", dependencies=[Depends(admin_dep)])
    async def admin_control_set(key: str, request: Request) -> dict:
        """{enabled: bool, actor?, note?}: flip one switch — free_allowance, signups,
        cloud_service, sync or hub. In force at once, kept across restarts, written to the
        audit log. Turning the hub or the service off closes every hub socket (4003)."""
        body = await _json(request)
        if "enabled" not in body:
            raise CloudError(400, "bad_request", "Say enabled: true or false")
        cloud.controls.set(key, bool(body["enabled"]), str(body.get("actor") or _actor(request))[:80], str(body.get("note") or "")[:200])
        hub = getattr(app.state, "hub", None)
        closed = 0
        if hub is not None and key in ("hub", "cloud_service") and not body["enabled"]:
            closed = await hub.drop_all("hub_paused")
        return {**cloud.controls.view(cloud.db.account_counts()["total"]), "sockets_closed": closed}

    # -- 0.22: GitHub and the statistics -----------------------------------------------------------

    stats = Stats(cloud, sync_store, collector, lambda: getattr(app.state, "hub", None))
    app.state.stats = stats

    @app.get("/v1/admin/github", dependencies=[Depends(admin_dep)])
    async def admin_github(days: int = 30) -> dict:
        """Stars, forks, watchers and release downloads per UTC day with what each day added,
        the latest figures per platform and per asset, and how the collector's last run went."""
        return collector.series(max(1, min(days, 365)))

    @app.post("/v1/admin/github/refresh", dependencies=[Depends(admin_dep)])
    async def admin_github_refresh() -> dict:
        """Read GitHub now and write today's snapshot (what the daily task does)."""
        out = await collector.collect()
        return {**out, "status": collector.status()}

    @app.get("/v1/admin/stats", dependencies=[Depends(admin_dep)])
    async def admin_stats(days: int = 30) -> dict:
        """Every metric of stats.py with its rows for the last `days` UTC days (1–365), its
        columns and how it is computed."""
        return stats.all(max(1, min(days, 365)))

    @app.get("/v1/admin/stats/{metric_id}.csv", dependencies=[Depends(admin_dep)])
    async def admin_stat_csv(metric_id: str, days: int = 30) -> Response:
        m = stats.metric(metric_id)
        if m is None:
            raise CloudError(404, "not_found", "No such metric")
        text = stats.csv(m, max(1, min(days, 365)))
        return Response(text, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{m.id}.csv"'})

    @app.get("/v1/admin/stats/{metric_id}", dependencies=[Depends(admin_dep)])
    async def admin_stat(metric_id: str, days: int = 30) -> dict:
        m = stats.metric(metric_id)
        if m is None:
            raise CloudError(404, "not_found", "No such metric")
        return stats.build(m, max(1, min(days, 365)))

    @app.get("/v1/admin/nudges", dependencies=[Depends(admin_dep)])
    async def admin_nudges_get() -> dict:
        """The nudges policy (0.18): what is served, the defaults beside it, whether the page
        set it and when."""
        return cloud.admin_nudges()

    @app.put("/v1/admin/nudges", dependencies=[Depends(admin_dep)])
    async def admin_nudges_put(request: Request) -> dict:
        """The whole policy (the shape of GET /v1/nudges; unknown keys dropped, values checked,
        400 with a plain message otherwise); `version` is bumped by the server. `{"reset":
        true}` goes back to the defaults. In force at once, kept across restarts."""
        return cloud.admin_put_nudges(await _json(request))

    @app.post("/v1/admin/allowance/apply", dependencies=[Depends(admin_dep)])
    async def admin_allowance_apply() -> dict:
        """Bring every account given a smaller allowance up to the current one (0.15)."""
        return cloud.admin_apply_allowance()

    @app.post("/v1/admin/disable", dependencies=[Depends(admin_dep)])
    async def admin_disable(request: Request) -> Response:
        body = await _json(request)
        account_id = cloud.admin_resolve(str(body.get("account_id", "")), str(body.get("identifier", "")))
        disabled = bool(body.get("disabled", True))
        cloud.admin_disable(account_id, disabled)
        hub = getattr(app.state, "hub", None)
        if disabled and hub is not None:
            await hub.drop_account(account_id)
        return Response(status_code=204)

    @app.post("/v1/admin/unlimited", dependencies=[Depends(admin_dep)])
    async def admin_unlimited(request: Request) -> Response:
        body = await _json(request)
        account_id = cloud.admin_resolve(str(body.get("account_id", "")), str(body.get("identifier", "")))
        cloud.admin_unlimited(account_id, bool(body.get("unlimited", True)))
        return Response(status_code=204)

    @app.post("/v1/admin/delete", dependencies=[Depends(admin_dep)])
    async def admin_delete(request: Request) -> Response:
        body = await _json(request)
        account_id = cloud.admin_resolve(str(body.get("account_id", "")), str(body.get("identifier", "")))
        hub = getattr(app.state, "hub", None)
        if hub is not None:
            await hub.drop_account(account_id)
        cloud.admin_delete(account_id)
        return Response(status_code=204)

    # -- helpers ------------------------------------------------------------------------------------

    def _too_large(size: int | None) -> CloudError:
        # a dozen screenshots in one chat request got here (0.19): name the two sizes so
        # the person, or the log, can tell at once which side has to give
        limit_mb = settings.max_request_bytes / 1048576
        said = f"Request body is {size / 1048576:.1f} MB" if size is not None else f"Request body is over {limit_mb:.0f} MB"
        return CloudError(413, "too_large", f"{said}; this relay accepts up to {limit_mb:.0f} MB")

    async def _json(request: Request) -> dict:
        """The body as a JSON object, read within MAX_REQUEST_BYTES: a declared length over
        it is refused before a byte is read, and a body that grows past it (chunked, or a
        length that lied) is refused as it arrives, so the relay never holds more than the
        limit for one request."""
        limit = settings.max_request_bytes
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise _too_large(int(declared))
        chunks: list[bytes] = []
        size = 0
        try:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise _too_large(int(declared) if declared.isdigit() else None)
                chunks.append(chunk)
        except ClientDisconnect as e:
            # the caller went away while its body was still arriving (a phone changing
            # networks, a tab closed mid-request): nobody is there to answer, and it is not
            # a server error worth a traceback in the log
            raise CloudError(400, "client_disconnected", "The request ended before its body") from e
        raw = b"".join(chunks)
        try:
            obj = json.loads(raw or b"{}")
        except ValueError as e:
            raise CloudError(400, "bad_request", "Body must be JSON") from e
        if not isinstance(obj, dict):
            raise CloudError(400, "bad_request", "Body must be a JSON object")
        return obj

    def _reply_text(obj: object) -> str:
        """The assistant's words in a non-streamed reply (choices[].message.content)."""
        text = ""
        if isinstance(obj, dict):
            for ch in obj.get("choices") or []:
                msg = ch.get("message") if isinstance(ch, dict) else None
                if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                    text += msg["content"]
        return text

    def _relay_error(r: httpx.Response, request: Request | None = None) -> JSONResponse:
        # The provider's own status codes would confuse the app (its 401 is not
        # the user's 401), so everything from upstream comes back as 502 except
        # 400s about the request itself, which are the caller's to see.
        status = 400 if r.status_code == 400 else 502
        log.warning("upstream HTTP %s: %s", r.status_code, r.text[:300])
        body = relay_error_body(r.status_code, r.content)
        if request is not None:
            request.state.error_code = str(body["error"]["code"])
        return JSONResponse(status_code=status, content=body)

    return app
