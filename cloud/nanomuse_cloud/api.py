"""HTTP: the sign-up endpoints the app calls, and the OpenAI-shaped proxy.

    GET  /healthz                                               → {ok, version, models, paused}
    GET  /v1/config                                             → the public figures the apps print (allowance, bonus, links, code_ttl_s, password_min_len); a minute's cache
    POST /v1/auth/code        {identifier}                      → 204 (400 phone_region: a number the SMS sender cannot reach; a disabled account gets the same 204 and no code is sent; 429 domain_limited: a new address of a domain at its day's sign-up limit)
    POST /v1/auth/verify      {identifier, code, device, invite?, device_id?, device_kind?} → {api_key, base_url, account, tokens, models}
    POST /v1/auth/login       {identifier, password, device, device_id?, device_kind?} → the same, for accounts that set a password
    POST /v1/auth/password    {password, current?}              → 204 (set / change; "" + current removes)
    GET  /v1/me                                                 → account, tokens, spend (¥ spent / pool / left), invite, contribute, usage by kind, models, recent, nudges
    GET  /v1/nudges                                             → when the apps may ask for a star (0.18; public, cached an hour; the operator's policy over the defaults)
    GET  /v1/me/invite                                          → the invite code and link, who came with it, what they brought
    GET  /v1/estimate         ?images=5&clips=4                 → what that would cost next to what is left (nothing charged)
    GET  /v1/me/sessions                                        → live sign-ins (device, via, when; the current one marked)
    DELETE /v1/me/sessions/{prefix}                             → 204 (sign one device out)
    GET  /v1/me/events                                          → the account's own timeline (sign-ins, password changes…)
    POST /v1/me/contribute {on}                                 → Data controls: "help improve nanoMuse's AI models" — keep the text of my chat turns (the default for new accounts is IMPROVE_DEFAULT)
    DELETE /v1/me/samples                                       → delete every turn kept from me: the training turns and (0.29) the record, files included → {deleted, turns, files}
    GET  /v1/turns            ?since=&limit=&before=&before_id=&conversation= → 0.29: the account's record — every turn in full, newest first (pictures as blob:sha256 references)
    GET  /v1/turns/{id}                                         → one turn
    POST /v1/turns            {model, messages, response{message, usage?}, provider?, ts?, conversation?, id?, run?, turn?, step?, trajectory?, trajectory_step?, platform?} → 201 {id, ts}: a turn run on the app's own key, kept beside the Cloud ones (and, with the switch on, in the training view)
    POST /v1/events           {events: [{kind, ts?, turn?, conversation?, data}]} → 202 {kept}: 0.31, what happened in the app around a turn — the Sentinel's decision, an approval's result, a stopped reply's reason, a thumb; codes only, never a message
    PUT  /v1/blobs/{sha256}   raw body + Content-Type           → {sha256, bytes, mime, known}: a picture, audio or clip, stored once by its hash (HEAD first saves the upload)
    HEAD /v1/blobs/{sha256}  /  GET /v1/blobs/{sha256}          → the file, for an account that holds a reference to it (a turn, the profile's clips, an upload of its own)
    GET  /v1/sync/state                                         → 0.19: {enabled, cursor, counts, limits, working[]} — conversation sync between the account's devices
    PUT  /v1/sync/state       {enabled}                         → the switch; off deletes everything stored
    GET  /v1/sync/changes     ?since=&limit=&scope=&tail=       → conversations and messages after a cursor, in seq order (0.20: scope=all|main, tail=K with since=0)
    POST /v1/sync/changes     {device, conversations, messages} → {cursor, accepted, rejected}; the other devices hear a hub `sync` frame
    POST /v1/sync/working     {cid, working, device?, state?, detail?} → 0.20: 204; the other devices hear a hub `working` frame (presence, kept 10 min in memory; 0.31: state and step ride along)
    DELETE /v1/sync/changes                                     → the store emptied, the switch kept
    DELETE /v1/sync/conversations/{cid}                         → one chat tombstoned everywhere
    POST /v1/auth/sign-out                                      → 204 (revokes this key)
    POST /v1/auth/sign-out-all {all?}                           → {signed_out} (every other device; all=true takes this one too)
    POST /v1/auth/session-key {device?, ttl_s?}                 → {api_key, expires_at} (a key that lapses on its own; nanoMuse Web's containers)
    POST /v1/auth/delete                                        → 204 (the whole account, every key)
    GET  /v1/me/profile       ?face=false                       → the agent's name, look and connectors, shared by the account's devices
    PUT  /v1/me/profile       {device, name?, avatar?, face?, clips?, connectors?} → {rev, device}; partial since 0.25; clips (0.29) name files put up with PUT /v1/blobs
    DELETE /v1/me/profile                                       → 204
    GET  /v1/models                                             → OpenAI list, with modalities; for a member, the usable models under the operator's key after the menu (catalog: true)
    GET  /v1/models/{id}      ?kind=chat                        → one model, or a member's typed id checked (listed, priced_as)
    POST /v1/chat/completions                                   → forwarded; stream or not
    POST /v1/images/generations                                 → 410 unless self-host media is enabled
    POST /v1/images/edits     multipart                         → 410 unless self-host media is enabled
    POST /api/v1/services/aigc/video-generation/video-synthesis → 410 unless self-host media is enabled
    GET  /api/v1/tasks/{id}                                     → its task poll (own tasks only)
    GET  /api/v1/uploads?action=getPolicy&model=…               → its temporary-storage policy
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
    GET  /v1/admin/invites    X-Admin-Token  ?limit=200&per=20  → who invited whom: the funnel and the inviters ranked by the accounts their code brought, with the newest `per` of them
    POST /v1/admin/invites/abuse X-Admin-Token {account_id | identifier, disable?, delete_unused?} → take back an inviter's invite credit, disable it, delete the invited accounts that never used anything; {reclaimed_cny, disabled, deleted, kept}
    GET  /v1/admin/usage      X-Admin-Token  ?days=14           → charged tokens and yuan per day and kind
    GET  /v1/admin/overview   X-Admin-Token  ?days=30           → the dashboard: accounts, today / week / period by kind and model, signals, events
    GET  /v1/admin/events     X-Admin-Token  ?limit=200&kind=…  → the timeline across accounts (never message content)
    GET  /v1/admin/series     X-Admin-Token  ?days=30           → by day: sign-ins, new / active accounts, invites, data switches turned on; devices by kind and OS; nanoMuse Web's counts
    GET  /v1/admin/traffic    X-Admin-Token  ?days=30           → the site: pages, visitors, downloads per file, referrers, GitHub stars and release downloads (TRAFFIC_DB)
    GET  /v1/admin/demo       X-Admin-Token  ?days=30           → the phone in the browser: visitors with addresses and browsers, every demo and what it used (WEB_ADMIN_URL)
    GET  /v1/admin/data       X-Admin-Token  ?days=30           → Data controls: accounts with the switch on, kept turns by day / model / app / account, switches on and off, the newest turns
    GET  /v1/admin/samples    X-Admin-Token  ?account_id=&limit=&since=&before=&before_id= → kept turns (accounts with the switch on only)
    GET  /v1/admin/samples/export X-Admin-Token ?since=&account_id= → the same as JSON lines, without account ids or addresses (each line carries the account's pseudonym, `subject`)
    GET  /v1/admin/turns      X-Admin-Token  ?account_id=&limit=&since=&before=&before_id=&conversation= → 0.29: the record, whole turns, newest first
    GET  /v1/admin/turns/export X-Admin-Token ?since=&account_id= → the record as JSON lines (account ids included: it is the account's data, not the training set)
    GET  /v1/admin/record     X-Admin-Token  ?days=30           → what the record holds: turns and files in all and per day, the store against MEDIA_MAX_GB
    GET  /v1/admin/blobs/{sha256} X-Admin-Token                 → one file of the record
    GET  /v1/admin/client-events X-Admin-Token ?account_id=&kind=&since=&limit=&before= → 0.31: what the apps reported around turns, newest first
    GET  /v1/admin/client-events/export X-Admin-Token ?since=&account_id= → the same as JSON lines, with the `subject` pseudonym and no account id
    GET  /v1/admin/client-events/summary X-Admin-Token ?days=30 → by day and kind: how many, from how many accounts; the Sentinel's and the thumbs' figures
    GET  /v1/admin/deletions  X-Admin-Token  ?since=            → 0.31: the deletions ledger — the `subject` of every account that deleted its data or itself since, to drop from a training set built earlier
    GET  /v1/admin/sync       X-Admin-Token                     → conversation sync in aggregate: accounts on / off, conversations, messages, bytes (never a text)
    GET  /v1/admin/health     X-Admin-Token                     → aggregates only: requests under way, the hub, the last hour, the database, problems (what selfcheck.sh reads)
    GET  /v1/admin/places     X-Admin-Token  ?days=30           → accounts, sign-ins, requests and demo visitors by country and province
    GET  /v1/admin/catalog    X-Admin-Token                     → the provider's models under the operator's key and what the probes found
    GET  /v1/admin/github     X-Admin-Token  ?days=30           → stars, forks, watchers, issues, release downloads by day;  POST …/github/refresh reads now
    GET  /v1/admin/stats      X-Admin-Token  ?days=30           → every figure of the Stats page;  GET …/stats/{id} one figure, …/stats/{id}.csv as CSV
    GET  /v1/admin/live       X-Admin-Token                     → 0.28: the model endpoint now — the provider gate, requests under way, the last hour by minute, latency percentiles, the newest calls
    GET  /v1/admin/analytics/usage     X-Admin-Token ?days=30   → 0.28: requests, tokens, money and accounts per local day and model (the matrix)
    GET  /v1/admin/analytics/day       X-Admin-Token ?day=<ts>  → one local day: by hour and model, by platform, how the calls went and how long they took, the errors' reasons, the top accounts
    GET  /v1/admin/analytics/platforms X-Admin-Token ?days=30   → the apps side by side: requests, accounts, money, latency, screen operation, versions, devices, reported own models
    GET  /v1/admin/analytics/cohorts   X-Admin-Token ?days=14   → the free pool and what came after it, who runs a key of their own, weekly retention
    GET  /v1/admin/analytics/hands     X-Admin-Token ?days=30   → screen operation: turns and accounts by day and platform, the tools called, operable devices
    GET  /v1/admin/analytics/quality   X-Admin-Token ?days=30   → the kept turns' shape and quality: trivial and repeated shares, accounts scored and tiered (never a text)
    GET  /v1/admin/analytics/abuse     X-Admin-Token ?days=30   → clients that are not the apps: user-agent families, sign-ins by client, the heaviest such accounts, shared addresses
    GET  /v1/admin/settings   X-Admin-Token                     → the runtime settings in force (0.15);  POST …/settings {allowance_cny?, invite_bonus_cny?, signup_open?} sets them
    POST /v1/admin/allowance/apply X-Admin-Token                → the raised allowance reaches the accounts below it
    POST /v1/admin/credit-all X-Admin-Token  {cny, note?}       → the same credit into every limited pool
    GET  /v1/admin/controls … X-Admin-Token                     → the switches, the threshold rules and the audit log (0.22; the routes are listed above their handlers)

    Every operator action on an account or on money writes a line in the audit log (who, from
    X-Admin-Actor or `console`; the account by the first eight characters of its id) and, where
    the account keeps a timeline, a line on it too. A deletion writes `account.deleted` across
    accounts, since the account's own timeline goes with it.

The video paths mirror the provider's own so the app's VideoGen, which
already speaks that API, only needs to point its host at the relay.

Errors are OpenAI-shaped: {"error": {"message", "type", "code"}} with the
status the app expects (401 bad key, 402 out of tokens, 429 rate limit).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
import os
import secrets
import tempfile
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, Request, Response, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from . import __version__, provenance
from . import client as client_info
from .analytics import (
    Analytics,
    InFlightCall,
    LiveMeter,
    delta_tool_names,
    is_hands_tool,
    join_tool_names,
    reply_tool_names,
    request_shape,
)
from .catalog import Catalog
from .config import ModelSpec, Settings
from .controls import ControlError
from .geo import Geo, collect_ips, group_places
from .github_stats import GitHubCollector
from .hub import Hub
from .identifiers import BadIdentifier, parse
from .record import StreamAssembler, is_sha256
from .service import Caller, Cloud, CloudError, Usage, dumps, estimate_tokens, prompt_chars, usage_from_json
from .stats import Stats, api_group
from .sync import DEFAULT_PAGE, SyncStore

log = logging.getLogger("nanomuse_cloud.api")


class UpstreamGate:
    """A process-wide provider slot limit, first come first served, with aggregate-only
    health figures. A request takes a `GateTicket` and waits for its slot in steps, so a
    stream can tell the app how many are ahead of it and keep the connection warm while it
    waits (0.31); `slot()` is the same wait in one piece."""

    def __init__(self, limit: int):
        self.limit = max(0, limit)
        self.active = 0
        self._queue: deque[asyncio.Future[None]] = deque()

    @property
    def waiting(self) -> int:
        return len(self._queue)

    def ticket(self) -> GateTicket:
        return GateTicket(self)

    def _hand_out(self) -> None:
        """Free slots to the queue's head; a waiter that left (its future cancelled) is skipped."""
        while self._queue and self.active < self.limit:
            fut = self._queue.popleft()
            if not fut.done():
                self.active += 1
                fut.set_result(None)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        ticket = self.ticket()
        try:
            await ticket.acquire(None)
            yield
        finally:
            ticket.release()

    def snapshot(self) -> dict[str, int]:
        return {"active": self.active, "waiting": self.waiting, "limit": self.limit}


class GateTicket:
    """One request's place at the gate: `acquire(timeout)` answers whether the slot is held
    yet and keeps the place in the queue across calls; `ahead` is how many wait in front;
    `release()` gives the slot back, or the place, whichever the ticket has."""

    def __init__(self, gate: UpstreamGate):
        self.gate = gate
        self.held = False
        self._fut: asyncio.Future[None] | None = None

    @property
    def ahead(self) -> int:
        if self._fut is None or self._fut.done():
            return 0
        try:
            return self.gate._queue.index(self._fut)
        except ValueError:
            return 0

    async def acquire(self, timeout: float | None) -> bool:
        if self.held:
            return True
        gate = self.gate
        if self._fut is None:
            if not gate.limit or (gate.active < gate.limit and not gate._queue):
                gate.active += 1
                self.held = True
                return True
            self._fut = asyncio.get_running_loop().create_future()
            gate._queue.append(self._fut)
        try:
            # shielded: a timeout here must not cancel the place in the queue
            await asyncio.wait_for(asyncio.shield(self._fut), timeout)
        except TimeoutError:
            return False
        self.held = True
        return True

    def release(self) -> None:
        gate = self.gate
        fut, self._fut = self._fut, None
        if self.held:
            self.held = False
            gate.active -= 1
            gate._hand_out()
        elif fut is not None:
            if fut.done() and not fut.cancelled():
                # granted after the waiter stopped waiting: the slot goes to the next in line
                gate.active -= 1
                gate._hand_out()
            else:
                try:
                    gate._queue.remove(fut)
                except ValueError:
                    pass
                fut.cancel()


#: how often a stream waiting for a provider slot says where it stands (and keeps warm)
STATUS_TICK = 5.0
#: how often a stream waiting for the provider's first bytes sends a comment line
KEEPALIVE_TICK = 10.0


def status_chunk(model: str, phase: str, started: float, *, ahead: int | None = None) -> bytes:
    """A chat chunk with no choices and a `nanomuse` field: where the turn stands before the
    model has said anything (0.31). `queued` carries how many requests are ahead at the
    relay's gate; `working` says the slot is taken and the model is being waited for.
    Parsers that know nothing of it see an empty chunk, as a usage-only chunk is."""
    status: dict[str, Any] = {"phase": phase, "waited_ms": max(0, int((time.monotonic() - started) * 1000))}
    if ahead is not None:
        status["ahead"] = ahead
    chunk = {"object": "chat.completion.chunk", "created": int(time.time()), "model": model, "choices": [], "nanomuse": status}
    return f"data: {dumps(chunk)}\n\n".encode()


async def _prepend(head: str | None, rest: AsyncIterator[str]) -> AsyncIterator[str]:
    """The line already taken from an iterator, then the iterator."""
    if head is not None:
        yield head
    async for line in rest:
        yield line


def _broken_status(e: httpx.HTTPError) -> str:
    """How a transport failure is kept in `calls`: a timeout of any kind apart from the rest
    (a connection refused, a stream cut), since the two point at different remedies."""
    return "upstream_timeout" if isinstance(e, httpx.TimeoutException) else "broken"


def error_response(status: int, code: str, message: str, extra: dict | None = None) -> JSONResponse:
    """OpenAI's error shape, so the apps' clients parse it, plus whatever fields the app can
    act on (`allowance_exhausted` says what is left and where the three ways on lead)."""
    return JSONResponse(
        status_code=status, content={"error": {"message": message, "type": "nanomuse_cloud", "code": code, **(extra or {})}}
    )


def thinking_requested(body: dict) -> bool | None:
    """What a chat request says about reasoning, in any of the dialects the apps speak:
    True when it asks for it (`enable_thinking: true`,
    `chat_template_kwargs.enable_thinking: true`, `thinking: {"type": "enabled"}`, a
    `reasoning_effort` other than `none`, a `thinking_budget`), False when it declines,
    None when it says nothing."""
    if "enable_thinking" in body:
        return bool(body["enable_thinking"])
    template = body.get("chat_template_kwargs")
    if isinstance(template, dict) and "enable_thinking" in template:
        return bool(template["enable_thinking"])
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
    """Merge operator defaults without contradicting the request's reasoning choice.

    Model Studio reads top-level ``enable_thinking``; vLLM's Qwen chat template reads
    ``chat_template_kwargs.enable_thinking``. Either default follows an explicit
    ``reasoning_effort`` or ``thinking`` choice from the app.
    """
    wants = thinking_requested(body)
    for k, v in defaults.items():
        if k == "enable_thinking" and wants is not None:
            body.setdefault("enable_thinking", wants)
            continue
        if k == "chat_template_kwargs" and isinstance(v, dict):
            default_template = dict(v)
            if "enable_thinking" in default_template and wants is not None:
                default_template["enable_thinking"] = wants
            current = body.get(k)
            if isinstance(current, dict):
                body[k] = {**default_template, **current}
            else:
                body.setdefault(k, default_template)
            continue
        body.setdefault(k, v)
    effort = body.get("reasoning_effort")
    if thinking_requested(body) is False and isinstance(effort, str) and effort.strip().lower() != "none":
        body["reasoning_effort"] = "none"


def upstream_body(raw: bytes | str) -> dict | None:
    """The object a provider's error body is about: the body itself when it is one, the
    first object of a list when the provider wraps it in one (Gemini's OpenAI-compatible
    endpoint answers a 400 with ``[{"error": {...}}]``), None for anything that is not
    JSON or neither of the two."""
    try:
        obj = json.loads(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(obj, list):
        obj = next((o for o in obj if isinstance(o, dict)), None)
    return obj if isinstance(obj, dict) else None


def upstream_detail(kind: str, status: int, model: str, raw: bytes | str) -> str:
    """The line an `upstream.error` event keeps: the kind, the status, the model and the
    provider's own words (its `error.message`, one line, trimmed) — enough to see *why* a
    request failed from the admin page, never the request's content."""
    message = ""
    obj = upstream_body(raw)
    err = obj.get("error") if obj else None
    if isinstance(err, dict):
        message = str(err.get("message") or err.get("code") or "")
    elif isinstance(err, str):
        message = err
    elif obj:
        message = str(obj.get("message") or "")
    message = " ".join(message.split())
    line = f"{kind} {status} {model}".strip()
    return f"{line}: {message[:200]}" if message else line


# the provider's content check saying no — Bailian's native and OpenAI-compatible spellings
CONTENT_CHECK_MARKS = ("data_inspection_failed", "datainspectionfailed", "inappropriate content", "green net")


def upstream_event_kind(status: int, raw: bytes | str) -> str:
    """The event a provider's refusal is kept as: `content.rejected` when its content check
    declined the words (the provider is fine; the request's words are the matter, and one long
    conversation can be declined hundreds of times as its client retries), `upstream.error`
    for everything else. The health page counts the two apart and only the second one is a
    problem."""
    return "content.rejected" if status == 400 and content_check_refusal(raw) else "upstream.error"


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
    up = upstream_body(raw)
    if up:
        e = up.get("error")
        if isinstance(e, dict) and e.get("message"):
            upstream = str(e["message"])[:300]
        elif isinstance(e, str) and e:
            upstream = e[:300]
        elif up.get("message"):
            upstream = str(up["message"])[:300]
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


def _unlink_quietly(path: str) -> None:
    """Remove a temporary file once its response has gone out; one already gone is no error."""
    try:
        os.unlink(path)
    except OSError:
        pass


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

    async def _video_loop() -> None:
        # 0.24: clips the app never polled to an end are settled by the relay itself
        # (settle_video_tasks, below, with the video routes); a bad tick must not end the loop
        while True:
            await asyncio.sleep(60)
            try:
                await settle_video_tasks()
            except Exception:
                log.exception("settle_video_tasks")

    async def _analytics_loop() -> None:
        # 0.28: the live meter's last hour is read back from `calls` after a restart; the
        # shape rows of older kept turns are filled in a page at a time (the turns are read
        # once, off the loop, in small batches so no request waits on the lock); rows past
        # CALLS_KEEP_DAYS are swept once an hour
        analytics = app.state.analytics
        try:
            warmed = await asyncio.to_thread(lambda: analytics.meter.warm(analytics.db.calls_since(int(time.time()) - 3600)))
            if warmed:
                log.info("analytics: %d calls of the last hour read back", warmed)
        except Exception:
            log.exception("analytics warm-up")
        # None, not 0.0: time.monotonic() counts from boot on Linux, so on a machine up for
        # less than an hour a zero start would hold the first sweep back until it is
        swept_at: float | None = None
        repaired_at: float | None = None
        optimized_at: float | None = None

        # A backfill pauses after each page for as long as the page took (half a second at
        # least): its reads and rewrites of rows that carry whole conversations get at most
        # half of the disk, and the pages people open keep their share.
        def pause(started: float, n: int) -> float:
            return max(0.5, time.monotonic() - started) if n else 60.0

        while True:
            try:
                if not analytics.backfill_done:
                    t0 = time.monotonic()
                    n = await asyncio.to_thread(analytics.backfill_step, 200)
                    if n and analytics.backfill_rows % 20000 < 200:
                        log.info("analytics: %d kept turns described so far", analytics.backfill_rows)
                    await asyncio.sleep(pause(t0, n))
                    continue
                if not analytics.tokens_done:
                    # 0.30: the tokens of older kept turns copied beside their shape, a page at a
                    # time (each page reads its turns' rows, so it is paced like the backfill)
                    t0 = time.monotonic()
                    n = await asyncio.to_thread(analytics.tokens_step, 200)
                    if n and analytics.tokens_rows % 20000 < 200:
                        log.info("analytics: tokens of %d kept turns copied so far", analytics.tokens_rows)
                    await asyncio.sleep(pause(t0, n))
                    continue
                if not analytics.keys_done:
                    # 0.31: the rows kept before the relay told a question from the calls it
                    # took get their turn keys, oldest first, a page of each table at a time
                    # (the record's pages are smaller still: Analytics.RECORD_KEYS_PAGE)
                    t0 = time.monotonic()
                    n = await asyncio.to_thread(analytics.turn_keys_step, 250)
                    if n and (analytics.keys_rows - n) // 20000 != analytics.keys_rows // 20000:
                        log.info("analytics: %d kept calls assigned to their turns so far", analytics.keys_rows)
                    await asyncio.sleep(pause(t0, n))
                    continue
                if not analytics.figures_done:
                    # 0.31.1: the figures rows of the own turns kept before the relay wrote
                    # them, a page at a time, paced like the other backfills
                    t0 = time.monotonic()
                    n = await asyncio.to_thread(analytics.own_figures_step, 200)
                    if n and (analytics.figures_rows - n) // 20000 != analytics.figures_rows // 20000:
                        log.info("analytics: figures of %d own turns written so far", analytics.figures_rows)
                    if analytics.figures_done:
                        log.info("analytics: the own turns' figures are complete (%d read this run)", analytics.figures_rows)
                    # through (a file with no own turns is through at once): on to the hourly work
                    await asyncio.sleep(0.5 if analytics.figures_done else pause(t0, n))
                    continue
                if optimized_at is None or time.monotonic() - optimized_at > 3600:
                    # the planner's statistics (Database.optimize): milliseconds, once an hour
                    optimized_at = time.monotonic()
                    await asyncio.to_thread(cloud.db.optimize)
                if repaired_at is None or time.monotonic() - repaired_at > 86400:
                    # once a day: the kept turns whose shape row never got written
                    repaired_at = time.monotonic()
                    fixed = await asyncio.to_thread(analytics.describe_missing, 500)
                    if fixed:
                        log.info("analytics: %d kept turns described late", fixed)
                if swept_at is None or time.monotonic() - swept_at > 3600:
                    swept_at = time.monotonic()
                    gone = await asyncio.to_thread(cloud.db.sweep_calls, int(time.time()) - max(1, settings.calls_keep_days) * 86400)
                    if gone:
                        log.info("analytics: %d call rows older than %d days swept", gone, settings.calls_keep_days)
                    gone = await asyncio.to_thread(cloud.db.sweep_events, int(time.time()) - max(1, settings.events_keep_days) * 86400)
                    if gone:
                        log.info("analytics: %d timeline lines older than %d days swept", gone, settings.events_keep_days)
                    # 0.29: the record's retention and the media store's cap
                    swept = await asyncio.to_thread(cloud.sweep_record)
                    if any(swept.values()):
                        log.info("record: %(turns)d turns swept, %(files)d files with them, %(trimmed)d trimmed over the cap", swept)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("analytics loop")
            await asyncio.sleep(60)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        geo.ensure()
        if settings.github_collect:
            collector.start()
        rules_task = asyncio.create_task(_rules_loop(), name="control-rules")
        video_task = asyncio.create_task(_video_loop(), name="video-settle")
        analytics_task = asyncio.create_task(_analytics_loop(), name="analytics")
        try:
            yield
        finally:
            rules_task.cancel()
            video_task.cancel()
            analytics_task.cancel()
            # waited for, so no cancellation lands after the database is closed
            await asyncio.gather(rules_task, video_task, analytics_task, return_exceptions=True)
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

    # whose X-Forwarded-For to believe: TRUSTED_PROXIES when set, else every non-global peer;
    # the same list uvicorn's proxy-headers middleware runs with (__main__.py)
    trusted_proxies = client_info.parse_trusted_proxies(settings.trusted_proxies)

    def client_ip(request: Request) -> str:
        return client_info.visitor_ip(request.headers, request.client.host if request.client else None, trusted_proxies)

    def client_place(request: Request):
        """Where the request came from (geo.py), for the region in /v1/me and the "ways on"
        of a refusal; None when the database is not there or the address is unplaced."""
        return geo.place(client_ip(request)) if geo.ready else None

    def count_request(error_code: str, group: str) -> None:
        # Keep both writes in one worker call if the waiting request is cancelled.
        if error_code:
            cloud.db.daily_add("error", error_code)
        cloud.db.daily_add("api", group)

    @app.middleware("http")
    async def _remember_client(request: Request, call_next):
        # the address and the client software behind this request, for the rows the
        # database writes while it is handled (client.py)
        token = client_info.set_current(
            client_info.from_headers(request.headers, request.client.host if request.client else None, trusted_proxies)
        )
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
                if not code and response.status_code >= 400:
                    code = f"http_{response.status_code}"
                await run_in_threadpool(count_request, code, api_group(path))
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

    def dashscope_headers() -> dict[str, str]:
        key = settings.dashscope_key or settings.upstream_key
        if not key:
            raise CloudError(503, "upstream_unconfigured", "nanoMuse Cloud has no media model key configured")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    # -- health ----------------------------------------------------------------

    @app.get("/healthz")
    async def healthz() -> dict:
        # `paused` (0.22): the operator's switches that are off — the process is fine either way
        return {
            "ok": True,
            "version": __version__,
            "models": [m.id for m in cloud.offered_models()],
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
        key, caller, created = await asyncio.to_thread(
            cloud.verify_code,
            ident,
            code,
            device,
            invite,
            str(body.get("device_id") or ""),
            str(body.get("device_kind") or ""),
        )
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
        key, caller = await asyncio.to_thread(
            cloud.login_password,
            ident,
            password,
            device,
            client_ip(request),
            str(body.get("device_id") or ""),
            str(body.get("device_kind") or ""),
        )
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
        """Data controls' delete: the training turns and (0.29) the record, files included."""
        return cloud.delete_samples(caller)

    # -- 0.29: the record and its files (docs/cloud.md, "The record") ------------------------

    def _turn_meta(request: Request) -> dict:
        meta = {
            "ua": (request.headers.get("user-agent") or "")[:120],
            "lang": (request.headers.get("accept-language") or "")[:40],
            "ip": client_ip(request),
        }
        # 0.31: the app's own word on its platform, when the user agent would not say
        # (the desktop's Node fetch, the runtime's SDK calls); client.platform_from reads it
        claim = provenance.platform_claim(request.headers.get("x-nanomuse-platform"))
        if claim:
            meta["platform"] = claim
        return meta

    @app.get("/v1/turns")
    async def my_turns(
        since: int = 0,
        limit: int = 50,
        before: int = 0,
        before_id: str = "",
        conversation: str = "",
        caller: Caller = Depends(caller_dep),
    ) -> dict:
        """The account's record, newest first, for a device reading it back: each turn's
        request (pictures as `blob:sha256:` references, files at GET /v1/blobs/{sha256})
        and the answer. Pages with `before` (the last row's ts) and `before_id` (its id)."""
        return {"turns": cloud.my_turns(caller, since, max(1, limit), max(0, before), before_id[:96], conversation)}

    @app.get("/v1/turns/{turn_id}")
    async def my_turn(turn_id: str, caller: Caller = Depends(caller_dep)) -> dict:
        turn = cloud.my_turn(caller, turn_id)
        if turn is None:
            raise CloudError(404, "not_found", "No such turn on this account")
        return turn

    @app.post("/v1/turns", status_code=201)
    async def post_turn(request: Request, caller: Caller = Depends(caller_dep)) -> dict:
        """A turn the app ran on a key of its own, kept beside the Cloud ones (1.0.7 on):
        `model`, `messages`, `response: {message, usage?}`, and `provider`, `ts`,
        `conversation`, `id` as the app has them. Files first: PUT /v1/blobs/{sha256}, then
        `blob:sha256:<hex>` where the picture was; or inline as data URLs within
        MAX_REQUEST_BYTES."""
        body = await _json(request)
        # off the loop: the pictures are decoded, hashed and written to disk, then the row
        return await asyncio.to_thread(
            cloud.add_own_turn,
            caller,
            body,
            meta=_turn_meta(request),
            device=(request.headers.get("x-nanomuse-device") or "")[:80],
            headers=dict(request.headers),
        )

    # -- 0.31: what the apps report around a turn (docs/cloud.md, "Client events") -----------

    @app.post("/v1/events", status_code=202)
    async def post_events(request: Request, caller: Caller = Depends(caller_dep)) -> dict:
        """Short records of what happened in the app around a turn, never a message: the
        Sentinel's decision on a tool call, an approval's result, why a reply was stopped,
        a thumb up or down (provenance.KNOWN_EVENTS). `{"events": [{kind, ts?, turn?,
        conversation?, data}]}`, at most 100 per request; `data` is a flat object of short
        codes, numbers and booleans. Answers how many were kept; one the relay will not
        keep is dropped, not refused, so an older app's list never fails whole."""
        body = await _json(request)
        who = client_info.current()
        return cloud.add_client_events(
            caller, body.get("events"), platform=who.platform, device=(request.headers.get("x-nanomuse-device") or "")[:80]
        )

    async def _raw(request: Request, limit: int) -> bytes:
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
            raise CloudError(400, "client_disconnected", "The request ended before its body") from e
        return b"".join(chunks)

    @app.put("/v1/blobs/{sha256}")
    async def put_blob(sha256: str, request: Request, caller: Caller = Depends(caller_dep)) -> dict:
        """A picture, an audio clip or a video, raw in the body with its `Content-Type`,
        named by its SHA-256 (checked). Stored once however many devices send it; answers
        `known: true` when it already was. HEAD first saves the upload."""
        if not is_sha256(sha256.lower()):
            raise CloudError(400, "bad_request", "the path is the file's hex SHA-256")
        data = await _raw(request, settings.blob_max_bytes)

        def store() -> dict:  # the hash of up to 32 MiB and the write, off the loop
            if hashlib.sha256(data).hexdigest() != sha256.lower():
                raise CloudError(400, "hash_mismatch", "the body's SHA-256 is not the one in the path")
            return cloud.put_blob(caller, data, request.headers.get("content-type") or "")

        return await asyncio.to_thread(store)

    @app.head("/v1/blobs/{sha256}")
    async def head_blob(sha256: str, caller: Caller = Depends(caller_dep)) -> Response:
        found = cloud.blob_for(sha256.lower(), caller)
        if found is None:
            raise CloudError(404, "not_found", "No such file on this account")
        path, mime = found
        return Response(status_code=200, media_type=mime, headers={"Content-Length": str(path.stat().st_size)})

    @app.get("/v1/blobs/{sha256}")
    async def get_blob(sha256: str, caller: Caller = Depends(caller_dep)) -> Response:
        """The file, for an account that holds a reference to it (one of its turns, its
        profile's clips, an upload of its own). Immutable: cache it for good."""
        found = cloud.blob_for(sha256.lower(), caller)
        if found is None:
            raise CloudError(404, "not_found", "No such file on this account")
        path, mime = found
        return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/v1/me/sessions")
    async def me_sessions(caller: Caller = Depends(caller_dep)) -> dict:
        return {"sessions": cloud.sessions(caller)}

    @app.delete("/v1/me/sessions/{prefix}", status_code=204)
    async def me_revoke_session(prefix: str, caller: Caller = Depends(caller_dep)) -> Response:
        cloud.revoke_session(caller, prefix)
        await _drop_signed_out(caller.account_id)
        return Response(status_code=204)

    @app.get("/v1/me/events")
    async def me_events(limit: int = 50, caller: Caller = Depends(caller_dep)) -> dict:
        return {"events": cloud.events(caller, limit)}

    @app.post("/v1/auth/sign-out", status_code=204)
    async def sign_out(caller: Caller = Depends(caller_dep)) -> Response:
        cloud.sign_out(caller)
        await _drop_signed_out(caller.account_id)
        return Response(status_code=204)

    async def _drop_signed_out(account_id: str) -> None:
        # a key that was just revoked may still hold a hub socket (the device signed out
        # from elsewhere); the hub closes it with 4001 now rather than at the next reconnect
        hub = getattr(app.state, "hub", None)
        if hub is not None:
            await hub.drop_signed_out(account_id)

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
        await _drop_signed_out(caller.account_id)
        return {"signed_out": n}

    async def _forget_account_live_state(account_id: str) -> None:
        """What a deletion must take with it besides the rows: the account's hub sockets
        (closed with 4001 `account_gone`) and its live "working" notes, which are memory,
        not rows, so `Database.delete_account` cannot reach them. The person's own
        deletion, the operator's and the invite-abuse clean-up all come through here."""
        hub = getattr(app.state, "hub", None)
        if hub is not None:
            await hub.drop_account(account_id)
        sync = getattr(app.state, "sync", None)
        if sync is not None:
            sync.presence.forget(account_id)

    @app.post("/v1/auth/delete", status_code=204)
    async def delete_account(caller: Caller = Depends(caller_dep)) -> Response:
        await _forget_account_live_state(caller.account_id)
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
        ten minutes. Presence, not data: nothing is written. 0.31: a `true` may say
        `state` (`working` | `waiting`) and `detail` — the step's own words, capped —
        which ride the frame to the other devices' screens."""
        body = await _json(request)
        cid = str(body.get("cid") or "")
        if not cid or "working" not in body:
            raise CloudError(400, "bad_request", "Say cid and working: true or false")
        device = str(body.get("device") or request.headers.get("x-nanomuse-device", ""))[:80]
        state = str(body.get("state") or "")
        detail = str(body.get("detail") or "")
        frame = sync_store.set_working(caller.account_id, cid, device, bool(body["working"]), state=state, detail=detail)
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
            # Hosted media is retired even for members: the provider catalogue may still
            # contain image models, but exposing one here would restore a billing bypass.
            if e.id in menu or (e.kind != "chat" and not settings.media_enabled):
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
        if m is not None and m.kind != "chat" and not settings.media_enabled:
            cloud.model_for(model_id, m.kind, caller)
        if m is None and kind:
            m = cloud.model_for(model_id, kind, caller)
        if m is None:
            more = " on the menu; add ?kind=chat|image|video to ask for one beyond it" if cloud.any_model(caller) else ""
            raise CloudError(404, "model_not_offered", f"nanoMuse Cloud does not offer {model_id!r}{more}")
        return m.to_public()

    # -- chat -----------------------------------------------------------------------------

    chat_gate = UpstreamGate(settings.chat_concurrency)
    chat_retry_limit = max(0, min(settings.chat_retries, 5))

    def chat_retryable(status: int) -> bool:
        return status == 429 or status >= 500

    async def chat_retry_pause(attempt: int, status: int) -> None:
        log.warning("chat upstream HTTP %s; retry %s/%s", status, attempt + 1, chat_retry_limit)
        await asyncio.sleep(max(0.0, settings.chat_retry_base_s) * (2**attempt))

    # 0.28: what each chat request looked like and how it went (analytics.py) — timings,
    # the way it ended, its shape; never its words. The live page reads the meter, the
    # drill-downs read the rows.
    meter = LiveMeter()
    analytics = Analytics(cloud, meter, lambda: getattr(app.state, "hub", None), chat_gate.snapshot)
    app.state.analytics = analytics
    app.state.meter = meter

    def record_call(
        call: InFlightCall,
        status: str,
        detail: str = "",
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
        called: list[str] | None = None,
        retries: int = 0,
        request_id: str = "",
    ) -> None:
        now_m = time.monotonic()
        slot_at = call.slot_at or now_m
        first_at = call.first_at or now_m
        shape = call.shape
        names = called or []
        row = {
            "ts": call.ts,
            "account_id": call.account_id,
            "model": call.model,
            "platform": call.platform,
            "family": call.family,
            "status": status,
            "detail": str(detail or "")[:120],
            "stream": 1 if call.stream else 0,
            "wait_ms": max(0, int((slot_at - call.started) * 1000)),
            "ttft_ms": max(0, int((first_at - slot_at) * 1000)) if call.slot_at else 0,
            "total_ms": max(0, int((now_m - call.started) * 1000)),
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "cached_tokens": min(max(0, int(cached_tokens or 0)), max(0, int(prompt_tokens or 0))),
            "messages": int(shape.get("messages", 0)),
            "images": int(shape.get("images", 0)),
            "tools": int(shape.get("tools", 0)),
            "tool_names": join_tool_names(names),
            "hands": 1 if (shape.get("hands") or any(is_hands_tool(n) for n in names)) else 0,
            "retries": int(retries or 0),
            "request_id": request_id,
            "run": call.run,
        }
        meter.finish(call, row)
        try:
            cloud.db.add_call(row)
        except Exception:  # telemetry must never fail a chat
            log.exception("calls row")

    # the record's writes in flight, held so the loop does not drop them half-way (and so
    # a test can wait for them: app.state.record_tasks)
    record_tasks: set[asyncio.Task] = set()
    app.state.record_tasks = record_tasks
    # the turn list reads newest first by (ts, rowid). ts is taken below, as the answer
    # leaves — a record written seconds later under load keeps the turn's own time — and
    # the writes are chained in that order, so a slow record (a picture still decoding)
    # cannot take a later rowid than a turn that answered after it and read as newer.
    record_prev: asyncio.Task | None = None

    def record_later(*args: Any, **kwargs: Any) -> None:
        """The turn's record (service.record_turn) written off the loop after the answer
        has left — the pictures are decoded, hashed and written to disk there, and the
        row after them. A failure is logged; it is never the person's problem."""
        nonlocal record_prev
        if not settings.record_turns:
            return
        kwargs.setdefault("ts", int(time.time()))
        prev = record_prev

        async def run() -> None:
            try:
                if prev is not None:
                    await prev  # its own run() swallows its failure; nothing propagates here
                await asyncio.to_thread(cloud.record_turn, *args, **kwargs)
            except Exception:
                log.exception("record turn")

        task = asyncio.create_task(run(), name="record-turn")
        record_tasks.add(task)
        record_prev = task
        task.add_done_callback(record_tasks.discard)

    async def chat_post(url: str, headers: dict[str, str], payload: bytes, call: InFlightCall) -> tuple[httpx.Response, int]:
        """One non-streaming turn, queued globally and retried before an answer exists;
        answers the response and how many times it was retried."""
        async with chat_gate.slot():
            meter.slot(call)
            attempt = 0
            while True:
                r = await http.post(url, headers=headers, content=payload)
                if not chat_retryable(r.status_code) or attempt >= chat_retry_limit:
                    return r, attempt
                await chat_retry_pause(attempt, r.status_code)
                attempt += 1

    @app.post("/v1/chat/completions")
    async def chat(request: Request, caller: Caller = Depends(caller_dep)) -> Response:
        body = await _json(request)
        spec = cloud.model_for(str(body.get("model", "")), "chat", caller)
        # a relay without a key answers before anything is held: a hold taken here and never
        # settled would count against the account's in-flight limit until it timed out
        headers = upstream_headers()
        request_id = uuid.uuid4().hex[:16]
        stream = bool(body.get("stream"))
        who = client_info.current()
        call = meter.start(caller.account_id, spec.id, who.platform, stream, request_shape(body))
        call.family = client_info.ua_family(who.ua)
        # 0.31: who started the turn and where it sits (provenance.py), from the app's headers
        where = provenance.from_headers(request.headers)
        call.run = where["run"]
        # 0.28 `apps_only`: the allowance is for nanoMuse; a pool worker, an SDK or another
        # app on a nanoMuse key is told where to go instead. Members are on the operator's
        # own bill by choice and may call from whatever they like.
        if cloud.controls.on("apps_only") and not caller.member and not client_info.is_nanomuse_client(who.platform):
            record_call(call, "refused", "client_not_supported", request_id=request_id)
            cloud.note(caller.account_id, "client.refused", call.family)
            raise CloudError(
                403,
                "client_not_supported",
                "nanoMuse Cloud answers the nanoMuse apps only. In other software, use a model key of your own; "
                "your sign-in and your allowance are kept for the apps.",
                {"client": call.family},
            )
        # held at a typical turn's price while it runs; settled when the reply is in
        try:
            cloud.check_budget(caller, request_id=request_id, hold_uy=cloud.chat_reserve_uy(spec), place=client_place(request))
        except CloudError as e:
            record_call(call, "refused", e.code, request_id=request_id)
            raise
        body["model"] = spec.upstream
        apply_chat_defaults(body, settings.chat_defaults)
        if stream:
            opts = body.get("stream_options") if isinstance(body.get("stream_options"), dict) else {}
            opts["include_usage"] = True
            body["stream_options"] = opts
        # Fields that would let a caller reach around the account: none of the
        # OpenAI request fields are dangerous, but `user` is ours to set so the
        # provider's abuse tooling can tell accounts apart without knowing them.
        body["user"] = caller.account_id[:32]
        body.pop("store", None)  # OpenAI-only field; some upstreams (e.g. Gemini openai-compat) reject unknown fields with 400
        url = settings.upstream_base.rstrip("/") + "/chat/completions"
        request_body = dumps(body).encode()
        fallback_prompt_tokens = math.ceil(prompt_chars(body.get("messages") or []) / 3)
        # For an account that opted in, the turn is kept once it is answered (service.keep_sample)
        # with the platform and language hints from the headers and, since 0.10, the address
        # (the export for training drops the address along with the account id).
        turn_meta = _turn_meta(request)
        # 0.29: the record keeps the whole turn once it is answered (service.record_turn, off
        # the loop); a 1.0.7 app names the device and the conversation the turn belongs to
        turn_where = {
            "device": (request.headers.get("x-nanomuse-device") or "")[:80],
            "conversation": (request.headers.get("x-nanomuse-conversation") or "")[:80],
            "provenance_": where,
        }
        sample_messages = body.get("messages") if caller.contribute and isinstance(body.get("messages"), list) else []
        sample_meta = None
        if caller.contribute:
            # 0.31: the kept turn says where it came from and names the record's turn, so the
            # app's later word on it (a thumb, why it was stopped) joins it
            sample_meta = dict(turn_meta)
            sample_meta.update(
                cloud.sample_provenance("cloud", request_id, where, sample_messages, conversation=turn_where["conversation"])
            )

        if not stream:
            retries = 0
            try:
                try:
                    r, retries = await chat_post(url, headers, request_body, call)
                except httpx.HTTPError as e:
                    log.warning("upstream error: %s", e)
                    record_call(call, _broken_status(e), type(e).__name__, retries=retries, request_id=request_id)
                    raise CloudError(502, "upstream", "The model provider did not answer") from e
                meter.first(call)
                if r.status_code >= 400:
                    event_kind = upstream_event_kind(r.status_code, r.content)
                    cloud.note(caller.account_id, event_kind, upstream_detail("chat", r.status_code, spec.id, r.content))
                    record_call(
                        call,
                        "content_rejected" if event_kind == "content.rejected" else "upstream_error",
                        str(r.status_code),
                        retries=retries,
                        request_id=request_id,
                    )
                    return _relay_error(r, request)
                try:
                    obj = r.json()
                except ValueError as e:
                    record_call(call, "broken", "unreadable reply", retries=retries, request_id=request_id)
                    raise CloudError(502, "upstream", "The model provider sent an unreadable reply") from e
                usage = usage_from_json(obj)
                text = _reply_text(obj)
                if usage is None:
                    usage = Usage(fallback_prompt_tokens, estimate_tokens(text))
                charged = cloud.charge_chat(caller, spec, usage.prompt, usage.completion, request_id, cached_tokens=usage.cached)
            finally:
                cloud.settle(caller, request_id)
            record_call(
                call,
                "ok",
                prompt_tokens=usage.prompt,
                completion_tokens=usage.completion,
                cached_tokens=usage.cached,
                called=reply_tool_names(obj),
                retries=retries,
                request_id=request_id,
            )
            if sample_meta is not None:
                cloud.keep_sample(
                    caller, spec.id, sample_messages, text, usage.prompt, usage.completion, sample_meta, message=_reply_message(obj)
                )
            record_later(caller, spec.id, body, _reply_message(obj), usage, request_id=request_id, meta=turn_meta, **turn_where)
            if isinstance(obj, dict):
                obj["model"] = spec.id
                obj.setdefault("nanomuse", {})["charged"] = charged
            return JSONResponse(content=obj, headers={"x-nanomuse-charged": str(charged), "x-nanomuse-request": request_id})

        async def gen() -> AsyncIterator[bytes]:
            usage: Usage | None = None
            text_len = 0
            # the assistant's words: the estimate when the provider sends no usage, and the
            # kept turn of a contributing account; the whole message, for the record
            reply: list[str] = []
            assembler = StreamAssembler()
            # A request the provider refused, or dropped before a single token, costs the
            # account nothing; a stream that broke off midway is charged for what arrived.
            failed = False
            accepted = False
            # how it ended, for the telemetry row: set at every exit; still None in `finally`
            # when the generator was closed under us, which is the client going away
            status: str | None = None
            detail = ""
            called: list[str] = []
            attempt = 0
            ticket = chat_gate.ticket()
            started = time.monotonic()
            try:
                # 0.31: while the request waits for a provider slot, the app hears how many are
                # ahead of it (a chunk with no choices, which every parser lets through, and a
                # `nanomuse` field the apps read), every STATUS_TICK seconds; the same chunks
                # keep the connection warm through NATs that drop a silent one
                queued = False
                while not await ticket.acquire(STATUS_TICK):
                    queued = True
                    yield status_chunk(spec.id, "queued", started, ahead=ticket.ahead)
                meter.slot(call)
                if queued:
                    # the turn's own: the app drops "ahead of you" and waits for the model
                    yield status_chunk(spec.id, "working", started)
                while True:
                    retry_status = 0
                    # the provider's first bytes, with a comment line (which every SSE parser
                    # skips) every KEEPALIVE_TICK seconds until they come: a busy endpoint takes
                    # a minute and more over a 12k-token prompt, longer than idle lines live
                    opening = asyncio.ensure_future(
                        http.send(http.build_request("POST", url, headers=headers, content=request_body), stream=True)
                    )
                    try:
                        while True:
                            done, _pending = await asyncio.wait({opening}, timeout=KEEPALIVE_TICK)
                            if done:
                                break
                            yield b": keepalive\n\n"
                    except BaseException:
                        opening.cancel()
                        raise
                    r = opening.result()
                    try:
                        if r.status_code >= 400:
                            raw = await r.aread()
                            if chat_retryable(r.status_code) and attempt < chat_retry_limit:
                                retry_status = r.status_code
                            else:
                                event_kind = upstream_event_kind(r.status_code, raw)
                                cloud.note(caller.account_id, event_kind, upstream_detail("chat", r.status_code, spec.id, raw))
                                failed = True
                                status = "content_rejected" if event_kind == "content.rejected" else "upstream_error"
                                detail = str(r.status_code)
                                err = relay_error_body(r.status_code, raw)
                                # The 200 has left; count the embedded stream error here.
                                cloud.db.daily_add("error", str(err["error"]["code"]))
                                yield f"data: {dumps(err)}\n\n".encode()
                                yield b"data: [DONE]\n\n"
                                return
                        else:
                            accepted = True
                            lines = r.aiter_lines()
                            # the first line the same way: the headers may come well before it
                            first = asyncio.ensure_future(anext(lines, None))
                            try:
                                while True:
                                    done, _pending = await asyncio.wait({first}, timeout=KEEPALIVE_TICK)
                                    if done:
                                        break
                                    yield b": keepalive\n\n"
                            except BaseException:
                                first.cancel()
                                raise
                            head = first.result()
                            async for line in _prepend(head, lines):
                                if line.startswith("data:"):
                                    payload = line[5:].strip()
                                    if payload and payload != "[DONE]":
                                        meter.first(call)
                                        try:
                                            obj = json.loads(payload)
                                        except ValueError:
                                            obj = None
                                        if isinstance(obj, dict):
                                            u = usage_from_json(obj)
                                            if u is not None:
                                                usage = u
                                            assembler.feed(obj)
                                            for ch in obj.get("choices") or []:
                                                d = ch.get("delta") if isinstance(ch, dict) else None
                                                if isinstance(d, dict) and isinstance(d.get("content"), str):
                                                    text_len += len(d["content"])
                                                    reply.append(d["content"])
                                                    call.tokens_out += 1
                                            called.extend(delta_tool_names(obj))
                                            obj["model"] = spec.id
                                            payload = dumps(obj)
                                    yield f"data: {payload}\n\n".encode()
                                elif line == "":
                                    continue
                                else:
                                    yield (line + "\n").encode()
                            status = "ok"
                            return
                    finally:
                        await r.aclose()
                    await chat_retry_pause(attempt, retry_status)
                    attempt += 1
                    call.retries = attempt
            except httpx.HTTPError as e:
                log.warning("upstream stream error: %s %s", type(e).__name__, e)
                cloud.note(caller.account_id, "upstream.error", f"chat stream broke {spec.id}: {type(e).__name__}")
                failed = usage is None and text_len == 0
                status, detail = _broken_status(e), type(e).__name__
                err = {"error": {"message": "The model provider stopped answering", "type": "nanomuse_cloud", "code": "upstream"}}
                yield f"data: {dumps(err)}\n\n".encode()
                yield b"data: [DONE]\n\n"
            finally:
                if accepted and not failed:
                    if usage is None:
                        usage = Usage(fallback_prompt_tokens, estimate_tokens("".join(reply)))
                    cloud.charge_chat(caller, spec, usage.prompt, usage.completion, request_id, cached_tokens=usage.cached)
                    if sample_meta is not None:
                        cloud.keep_sample(
                            caller,
                            spec.id,
                            sample_messages,
                            "".join(reply),
                            usage.prompt,
                            usage.completion,
                            sample_meta,
                            message=assembler.message(),
                        )
                    # a turn kept short says why (0.30): `client_gone` is the app closing the
                    # stream (the person stopped, or the app gave up waiting), `upstream_timeout`
                    # and `broken` are the provider's end — the same words as the telemetry row
                    record_later(
                        caller,
                        spec.id,
                        body,
                        assembler.message(),
                        usage,
                        request_id=request_id,
                        meta=turn_meta if status == "ok" else {**turn_meta, "ended": status or "client_gone"},
                        status="ok" if status == "ok" else "partial",
                        **turn_where,
                    )
                ticket.release()
                cloud.settle(caller, request_id)
                record_call(
                    call,
                    status or "client_gone",
                    detail,
                    prompt_tokens=usage.prompt if usage else 0,
                    completion_tokens=usage.completion if usage else 0,
                    cached_tokens=usage.cached if usage else 0,
                    called=called,
                    retries=attempt,
                    request_id=request_id,
                )

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
                    r = await http.post(url, headers=dashscope_headers(), content=payload)
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
        try:
            n = int(body.get("n") or 1)
        except (TypeError, ValueError) as e:
            raise CloudError(400, "bad_request", "n is a whole number") from e
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
        headers = dashscope_headers()  # before the hold, as for chat: no key, nothing held
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
        # Polling is a media route too: after hosted media is retired it must not reach the
        # provider or settle a pending charge left by an older client.
        if not settings.media_enabled:
            cloud.model_for("", "video", caller)
        task = cloud.db.video_task(task_id)
        if task is None or task["account_id"] != caller.account_id:
            raise CloudError(404, "no_task", "No such task")
        try:
            r = await http.get(settings.dashscope_base.rstrip("/") + f"/tasks/{task_id}", headers=dashscope_headers())
        except httpx.HTTPError as e:
            raise CloudError(502, "upstream", "The video provider did not answer") from e
        if r.status_code < 400:
            charged = cloud.settle_video_task(task, _task_status(r))
            if charged is not None:
                log.info("video task %s done for %s: charged %d", task_id[:12], caller.account_id[:8], charged)
        return _dashscope_reply(r)

    def _task_status(r: httpx.Response) -> str | None:
        try:
            status = r.json().get("output", {}).get("task_status")
        except (ValueError, AttributeError):
            return None
        return str(status) if status else None

    async def settle_video_tasks(limit: int = 5) -> int:
        """0.24: the relay asks the provider itself about clips the app never polled to an
        end: once shortly before the hour's hold on the allowance lapses, once more before
        the row is purged. A SUCCEEDED answer charges the clip exactly once (the same path
        as a poll); FAILED or CANCELED lets the hold go; a task the provider no longer knows
        is marked UNKNOWN. A handful per call. Returns how many tasks were asked about."""
        if not settings.media_enabled or not (settings.dashscope_key or settings.upstream_key):
            return 0
        done = 0
        for task in cloud.db.video_tasks_to_settle(limit):
            task_id = str(task["task_id"])
            try:
                r = await http.get(settings.dashscope_base.rstrip("/") + f"/tasks/{task_id}", headers=dashscope_headers())
            except httpx.HTTPError as e:
                log.warning("video task %s: the provider did not answer the relay's check: %s", task_id[:12], e)
                continue  # not counted as a check: the next tick asks again
            if r.status_code < 400:
                status = _task_status(r)
            elif r.status_code in (400, 404):
                status = "UNKNOWN"  # the provider keeps a task a day; gone means nothing to charge
            else:
                log.warning("video task %s: provider HTTP %s on the relay's check", task_id[:12], r.status_code)
                continue
            charged = cloud.settle_video_task(task, status)
            cloud.db.note_video_check(task_id)
            done += 1
            if charged is not None:
                log.info(
                    "video task %s settled by the relay for %s: %s, charged %d", task_id[:12], str(task["account_id"])[:8], status, charged
                )
        return done

    app.state.settle_video_tasks = settle_video_tasks  # the tests call it directly

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
                headers=dashscope_headers(),
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
            token = client_info.set_current(client_info.from_headers(ws.headers, ws.client.host if ws.client else None, trusted_proxies))
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
                    503,
                    "hub_paused",
                    "The device hub is paused on this relay for now; each device keeps working on its own.",
                    {"paused": True},
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

    # The console's pages read through `cloud.reads` (the read-only connection) in a thread:
    # a page that takes seconds on a large file (every account, a month of the ledger) then
    # costs the operator the wait and nobody else anything. The handlers that write stay on
    # the loop with the relay's own connection, as every request does for its few rows.

    @app.get("/v1/admin/accounts", dependencies=[Depends(admin_dep)])
    async def admin_accounts() -> dict:
        accounts = await asyncio.to_thread(cloud.reads.admin_accounts)
        hub = getattr(app.state, "hub", None)
        if hub is not None:
            for a in accounts:
                a["devices"] = [{k: d[k] for k in ("id", "name", "kind", "os", "online", "last_seen")} for d in hub.devices(a["id"])]
        return with_places({"accounts": accounts, "settings": {**cloud.admin_settings(), "version": __version__}})

    @app.get("/v1/admin/usage", dependencies=[Depends(admin_dep)])
    async def admin_usage(days: int = 14) -> dict:
        return {"days": await asyncio.to_thread(cloud.reads.admin_usage, max(1, min(days, 90)))}

    @app.get("/v1/admin/health", dependencies=[Depends(admin_dep)])
    async def admin_health() -> dict:
        """What the self-check timer reads (deploy/nanomuse-hk/selfcheck.sh): aggregates
        only — requests under way, the hub's counters, the last hour's refusals, upstream
        errors and content-check refusals, the database — never an account. `ok` is false
        when something needs a look; the provider's content check declining a request's
        words (`content_rejected`) is counted apart and is never one of the problems, since
        the provider is answering and only the words are the matter."""
        hub = getattr(app.state, "hub", None)
        t = int(time.time())
        reads = cloud.reads.db
        hour = await asyncio.to_thread(reads.events_since, t - 3600)
        requests_hour = await asyncio.to_thread(reads.requests_since_all, t - 3600)
        in_flight = cloud.in_flight.snapshot()
        upstream_errors = int(hour.get("upstream.error", 0))
        db_health = cloud.db.health()
        out: dict[str, Any] = {
            "ok": True,
            "version": __version__,
            "time": t,
            "in_flight": {"requests": sum(in_flight.values()), "accounts": len(in_flight), "limit": cloud.in_flight.limit},
            "chat_upstream": {**chat_gate.snapshot(), "retries": chat_retry_limit},
            "hub": hub.stats() if hub is not None else None,
            "last_hour": {
                "requests": requests_hour,
                "upstream_errors": upstream_errors,
                "content_rejected": int(hour.get("content.rejected", 0)),
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
        # invites being farmed: a code bringing many accounts in a day, or inviters whose
        # people never use anything; each alert is one sentence here and the detail below
        alerts = await asyncio.to_thread(cloud.reads.invite_alerts)
        for alert in alerts:
            problems.append(f"{alert['message']}; {alert['hint']}")
        out["alerts"] = alerts
        out["ok"] = not problems
        out["problems"] = problems
        return out

    @app.get("/v1/admin/overview", dependencies=[Depends(admin_dep)])
    async def admin_overview(days: int = 30) -> dict:
        out = await asyncio.to_thread(cloud.reads.admin_overview, max(1, min(days, 365)))
        hub = getattr(app.state, "hub", None)
        out["online_devices"] = hub.online_count() if hub is not None else 0
        out["version"] = __version__
        out["geo"] = geo.status()
        return with_places(out)

    @app.get("/v1/admin/series", dependencies=[Depends(admin_dep)])
    async def admin_series(days: int = 30) -> dict:
        out = await asyncio.to_thread(cloud.reads.admin_series, max(1, min(days, 365)))
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
        return await asyncio.to_thread(cloud.reads.admin_traffic, max(1, min(days, 365)))

    @app.get("/v1/admin/places", dependencies=[Depends(admin_dep)])
    async def admin_places(days: int = 30) -> dict:
        """Where people are: accounts by their latest address, and the period's requests,
        sign-ins and new accounts by address — counted by country and province (ip2region);
        the showcase's visitors too when its gateway answers. `geo` says whether the
        database is there at all."""
        days = max(1, min(days, 365))
        geo.ensure()
        counts = await asyncio.to_thread(cloud.reads.db.address_counts, int(time.time()) - days * 86400)
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
        return await asyncio.to_thread(cloud.reads.admin_data, max(1, min(days, 365)))

    @app.get("/v1/admin/accounts/{account_id}", dependencies=[Depends(admin_dep)])
    async def admin_account(account_id: str, days: int = 30) -> dict:
        out = await asyncio.to_thread(cloud.reads.admin_account, account_id, max(1, min(days, 365)))
        hub = getattr(app.state, "hub", None)
        if hub is not None:
            out["devices"] = hub.devices(account_id)
        # the showcase's record of this person (the visitor id there is the account id here)
        out["demo"] = await demo_admin({"account": account_id})
        return with_places(out)

    def _kinds(kind: str) -> tuple[str, ...] | None:
        """`?kind=a,b` as the tuple the database filters on; empty means every kind."""
        return tuple(k.strip() for k in kind.split(",") if k.strip())[:20] or None

    @app.get("/v1/admin/accounts/{account_id}/ledger", dependencies=[Depends(admin_dep)])
    async def admin_account_ledger(account_id: str, limit: int = 200, before: int = 0, kind: str = "", q: str = "") -> dict:
        """One page of the account's statement, newest first; `before` is the id of the
        last row shown. Every line is reachable this way. `kind` (0.26, a comma list) and
        `q` (a text the model name or the note contains) narrow the page and its `total`."""
        if cloud.db.account(account_id) is None:
            raise CloudError(404, "no_account", "No such account")
        page = await asyncio.to_thread(
            cloud.reads.ledger_page, account_id, max(1, min(limit, 1000)), max(0, before), _kinds(kind), q.strip()[:80]
        )
        return with_places(page)

    @app.get("/v1/admin/accounts/{account_id}/events", dependencies=[Depends(admin_dep)])
    async def admin_account_events(account_id: str, limit: int = 200, before: int = 0, kind: str = "", q: str = "") -> dict:
        """The account's timeline, newest first, paged with `before`; `kind` and `q` (0.26)
        narrow it the same way as the statement, `q` matching the kind name or the detail."""
        if cloud.db.account(account_id) is None:
            raise CloudError(404, "no_account", "No such account")
        page = await asyncio.to_thread(
            cloud.reads.events_page, account_id, max(1, min(limit, 1000)), max(0, before), _kinds(kind), q.strip()[:80]
        )
        return with_places(page)

    @app.get("/v1/admin/address", dependencies=[Depends(admin_dep)])
    async def admin_address(ip: str = "") -> dict:
        """The accounts seen from one address, and where it is."""
        if not ip.strip():
            raise CloudError(400, "bad_request", "Say which address: ?ip=…")
        out = await asyncio.to_thread(cloud.reads.admin_address, ip)
        place = geo.place(ip.strip())
        out["place"] = place.as_dict() if place is not None else None
        return with_places(out)

    @app.get("/v1/admin/invites", dependencies=[Depends(admin_dep)])
    async def admin_invites(limit: int = 200, per: int = 20) -> dict:
        """The inviters in order of how many accounts their code brought, with what those
        accounts did and the newest `per` of them, and the funnel; an account's detail
        page lists its invitees in full."""
        return with_places(await asyncio.to_thread(cloud.reads.admin_invites, max(1, min(limit, 1000)), max(0, min(per, 100))))

    @app.post("/v1/admin/invites/abuse", dependencies=[Depends(admin_dep)])
    async def admin_invite_abuse(request: Request) -> dict:
        """{account_id, disable?: bool, delete_unused?: bool}: take back the invite credit an
        inviter farmed (never below what it has spent), disable it when asked, and when asked
        delete every account it brought that never used the relay. Answers
        {reclaimed_cny, disabled, deleted, kept}; 404 no_account when unknown."""
        body = await _json(request)
        account_id = cloud.admin_resolve(str(body.get("account_id", "")), str(body.get("identifier", "")))
        disable = bool(body.get("disable", False))
        hub = getattr(app.state, "hub", None)
        if disable and hub is not None:
            await hub.drop_account(account_id)
        out = cloud.admin_invite_abuse(
            account_id, disable=disable, delete_unused=bool(body.get("delete_unused", False)), actor=_actor(request)
        )
        # the deleted invitees' sockets and live notes go with their rows, as on any deletion
        for invitee_id in out.pop("deleted_ids", []):
            await _forget_account_live_state(invitee_id)
        return out

    @app.get("/v1/admin/events", dependencies=[Depends(admin_dep)])
    async def admin_events(limit: int = 200, kind: str = "", before: int = 0) -> dict:
        """Everyone's timeline, newest first; `kind` is a comma list; `before` (0.26) is
        the id of the last row shown, so the page reads on past the first 200."""
        return with_places({"events": await asyncio.to_thread(cloud.reads.admin_events, limit, _kinds(kind), max(0, before))})

    @app.get("/v1/admin/samples", dependencies=[Depends(admin_dep)])
    async def admin_samples(account_id: str = "", limit: int = 100, since: int = 0, before: int = 0, before_id: str = "") -> dict:
        """Contributed chat turns — only from accounts that turned contribution on. Pages
        with `before` (the last row's ts) and `before_id` (its id), newest first."""
        reads = cloud.reads
        return with_places(
            {
                "samples": await asyncio.to_thread(reads.admin_samples, account_id or None, since, limit, before, before_id[:64]),
                "total": await asyncio.to_thread(reads.db.sample_count, account_id or None),
            }
        )

    @app.get("/v1/admin/turns", dependencies=[Depends(admin_dep)])
    async def admin_turns(
        account_id: str = "", limit: int = 50, since: int = 0, before: int = 0, before_id: str = "", conversation: str = ""
    ) -> dict:
        """The record (0.29): whole turns, newest first, with the same paging as samples."""
        reads = cloud.reads
        return with_places(
            {
                "turns": await asyncio.to_thread(reads.admin_turns, account_id or None, since, limit, before, before_id[:96], conversation),
                "total": await asyncio.to_thread(reads.db.turn_count, account_id or None),
            }
        )

    @app.get("/v1/admin/record/turns", dependencies=[Depends(admin_dep)])
    async def admin_record_turns(
        account_id: str = "",
        conversation: str = "",
        platform: str = "",
        run: str = "",
        source: str = "",
        model: str = "",
        script: str = "",
        media: int = 0,
        hands: int = 0,
        since: int = 0,
        limit: int = 20,
        before: int = 0,
        before_key: str = "",
    ) -> dict:
        """The record one question at a time (0.31): each turn with every model call it
        took, laid out as steps — the person's message, what the model said and what came
        back at each call, the reply; pictures as references into /v1/admin/blobs. Pages
        with `before` (the last turn's `ts1`) and `before_key`. `pending` counts the calls
        the backfill has not yet assigned to a turn."""
        return with_places(
            await asyncio.to_thread(
                lambda: cloud.reads.admin_turn_groups(
                    since,
                    max(1, min(limit, 100)),
                    before,
                    before_key[:96],
                    account_id=account_id or None,
                    conversation=conversation,
                    platform=platform,
                    run=run,
                    source=source,
                    media=bool(media),
                    hands=bool(hands),
                    script=script,
                    model=model,
                )
            )
        )

    @app.get("/v1/admin/turns/export", dependencies=[Depends(admin_dep)])
    async def admin_turns_export(since: int = 0, account_id: str = "") -> Response:
        """The record as JSON lines, account ids included (it is the account's data, not the
        training set); pictures stay references, fetched by hash from /v1/admin/blobs. A
        generator over the read-only connection: Starlette pulls each line in a thread."""
        name = f"nanomuse-turns-{account_id[:8]}-{since}" if account_id else f"nanomuse-turns-{since}"
        return StreamingResponse(
            cloud.reads.export_turns(since, account_id or None),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{name}.jsonl"', "Cache-Control": "no-store"},
        )

    @app.get("/v1/admin/turns/{turn_id}", dependencies=[Depends(admin_dep)])
    async def admin_turn_one(turn_id: str) -> dict:
        """One call of the record in full: the whole request as the model saw it (the system
        prompt, every message, the tools offered) and the answer."""
        found = await asyncio.to_thread(cloud.reads.admin_turn, turn_id[:96])
        if found is None:
            raise CloudError(404, "not_found", "No such turn")
        return with_places({"turn": found})

    @app.get("/v1/admin/record", dependencies=[Depends(admin_dep)])
    async def admin_record(days: int = 30) -> dict:
        """What the record holds: turns and files in all and per day, the store against its cap."""
        return await asyncio.to_thread(cloud.reads.admin_record, max(1, min(days, 365)))

    @app.get("/v1/admin/blobs/{sha256}", dependencies=[Depends(admin_dep)])
    async def admin_blob(sha256: str) -> Response:
        found = cloud.blob_for(sha256.lower())
        if found is None:
            raise CloudError(404, "not_found", "No such file")
        path, mime = found
        return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/v1/admin/samples/export", dependencies=[Depends(admin_dep)])
    async def admin_samples_export(since: int = 0, account_id: str = "") -> Response:
        """The training set as JSON lines (one turn per line, no account ids, no addresses);
        with `account_id`, one account's turns. One whole response with its length, not a
        stream: a stream that stopped short (a proxy compressing it, the connection dropping)
        reached the browser as "Failed to fetch" with nothing to say why. The lines are
        written to a temporary file in a thread, over the read-only connection, and the file
        is sent and removed: the set is hundreds of thousands of turns, far too many to
        build in memory, and far too slow a read to run on the loop."""
        name = f"nanomuse-samples-{account_id[:8]}-{since}" if account_id else f"nanomuse-samples-{since}"
        reads = cloud.reads

        def write() -> str:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", delete=False) as f:
                for line in reads.export_samples(since, account_id or None):
                    f.write(line)
                return f.name

        path = await asyncio.to_thread(write)
        return FileResponse(
            path,
            media_type="application/x-ndjson",
            filename=f"{name}.jsonl",
            headers={"Cache-Control": "no-store"},
            background=BackgroundTask(_unlink_quietly, path),
        )

    @app.get("/v1/admin/client-events", dependencies=[Depends(admin_dep)])
    async def admin_client_events(account_id: str = "", kind: str = "", since: int = 0, limit: int = 200, before: int = 0) -> dict:
        """What the apps reported around turns (0.31), newest first; `kind` is a comma list,
        `before` the id of the last row shown."""
        reads = cloud.reads
        return {
            "events": await asyncio.to_thread(reads.admin_client_events, account_id or None, _kinds(kind), since, limit, max(0, before)),
            "total": await asyncio.to_thread(reads.db.client_event_count, account_id or None),
            "kinds": list(provenance.KNOWN_EVENTS),
        }

    @app.get("/v1/admin/client-events/export", dependencies=[Depends(admin_dep)])
    async def admin_client_events_export(since: int = 0, account_id: str = "") -> Response:
        """The apps' reports as JSON lines, each with the account's `subject` pseudonym and
        the turn's id, so they join the training set's lines; no account id."""
        name = f"nanomuse-client-events-{account_id[:8]}-{since}" if account_id else f"nanomuse-client-events-{since}"
        return StreamingResponse(
            cloud.reads.export_client_events(since, account_id or None),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{name}.jsonl"', "Cache-Control": "no-store"},
        )

    @app.get("/v1/admin/client-events/summary", dependencies=[Depends(admin_dep)])
    async def admin_client_events_summary(days: int = 30) -> dict:
        """By day and kind: how many reports and from how many accounts, and what the
        Sentinel decided, how approvals went, why replies were stopped and how the thumbs
        fell over the period. Figures only."""
        return await asyncio.to_thread(cloud.reads.client_events_summary, max(1, min(days, 365)))

    @app.get("/v1/admin/deletions", dependencies=[Depends(admin_dep)])
    async def admin_deletions(since: int = 0) -> dict:
        """The deletions ledger (0.31): the `subject` pseudonym of every account that deleted
        its kept data (`samples`) or itself (`account`) since the time given, oldest first.
        A training set built from an export drops those subjects' lines in its next build."""
        return {"deletions": await asyncio.to_thread(cloud.reads.deletions_since, max(0, since))}

    @app.get("/v1/admin/sync", dependencies=[Depends(admin_dep)])
    async def admin_sync() -> dict:
        """Conversation sync in aggregate (0.19): accounts with it on and off, how many
        conversations and messages are stored and their size. Never a text, never an account."""
        return sync_store.admin_totals()

    @app.post("/v1/admin/grant", dependencies=[Depends(admin_dep)])
    async def admin_grant(request: Request) -> dict:
        body = await _json(request)
        account_id = cloud.admin_resolve(str(body.get("account_id", "")), str(body.get("identifier", "")))
        try:
            tokens = int(body.get("tokens", 0))
        except (TypeError, ValueError) as e:
            raise CloudError(400, "bad_request", "tokens is a whole number") from e
        return cloud.admin_grant(account_id, tokens, actor=_actor(request))

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
        return cloud.admin_credit(account_id, cny, str(body.get("note", ""))[:200], actor=_actor(request))

    @app.post("/v1/admin/credit-all", dependencies=[Depends(admin_dep)])
    async def admin_credit_all(request: Request) -> dict:
        """{cny, note?}: the same credit into every limited account's pool (0.15)."""
        body = await _json(request)
        try:
            cny = float(body.get("cny", 0))
        except (TypeError, ValueError) as e:
            raise CloudError(400, "bad_request", "cny is a number") from e
        return cloud.admin_credit_all(cny, str(body.get("note", ""))[:200], actor=_actor(request))

    @app.post("/v1/admin/pool", dependencies=[Depends(admin_dep)])
    async def admin_pool(request: Request) -> dict:
        """{account_id | identifier, left_cny | grant_cny | delta_cny, note?}: set one account's
        pool (0.16) — to what should be left now, to a lifetime total, or by a difference up or
        down. Never below zero."""
        body = await _json(request)
        account_id = cloud.admin_resolve(str(body.get("account_id", "")), str(body.get("identifier", "")))
        return cloud.admin_set_pool(account_id, body, actor=_actor(request))

    @app.post("/v1/admin/pool/batch", dependencies=[Depends(admin_dep)])
    async def admin_pool_batch(request: Request) -> dict:
        """{account_ids: [...] | all: true, left_cny | grant_cny | delta_cny, note?}: the same
        change to a set of accounts, or to every limited one (0.16)."""
        return cloud.admin_set_pool_many(await _json(request), actor=_actor(request))

    @app.get("/v1/admin/settings", dependencies=[Depends(admin_dep)])
    async def admin_settings_get() -> dict:
        """The settings the page may change (0.15): the value in force, the environment's,
        whether the page set it, and how many accounts a raised allowance would reach."""
        return cloud.runtime_settings()

    @app.post("/v1/admin/settings", dependencies=[Depends(admin_dep)])
    async def admin_settings_set(request: Request) -> dict:
        """{allowance_cny?, invite_bonus_cny?, signup_open?}: set (a value) or clear back to
        the environment (null). In force at once, kept across restarts."""
        return cloud.admin_update_settings(await _json(request), actor=_actor(request))

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
        return await asyncio.to_thread(stats.all, max(1, min(days, 365)))

    @app.get("/v1/admin/stats/{metric_id}.csv", dependencies=[Depends(admin_dep)])
    async def admin_stat_csv(metric_id: str, days: int = 30) -> Response:
        m = stats.metric(metric_id)
        if m is None:
            raise CloudError(404, "not_found", "No such metric")
        text = await asyncio.to_thread(stats.csv, m, max(1, min(days, 365)))
        return Response(text, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{m.id}.csv"'})

    @app.get("/v1/admin/stats/{metric_id}", dependencies=[Depends(admin_dep)])
    async def admin_stat(metric_id: str, days: int = 30) -> dict:
        m = stats.metric(metric_id)
        if m is None:
            raise CloudError(404, "not_found", "No such metric")
        return await asyncio.to_thread(stats.build, m, max(1, min(days, 365)))

    # -- 0.28: the live view and the analytics pages (analytics.py) --------------------------------

    @app.get("/v1/admin/live", dependencies=[Depends(admin_dep)])
    async def admin_live() -> dict:
        """The model endpoint right now: the provider gate (active, waiting, limit), the
        requests under way with their phase and age, the hub, per-minute throughput and
        latency for the last hour, the last ten minutes and the hour in summary, the newest
        calls. Memory only; the page polls it every few seconds."""
        return analytics.live()

    @app.get("/v1/admin/analytics/usage", dependencies=[Depends(admin_dep)])
    async def admin_analytics_usage(days: int = 30) -> dict:
        """Per local day and model: requests, tokens, money, accounts (the matrix)."""
        return await asyncio.to_thread(analytics.usage, max(1, min(days, 365)))

    @app.get("/v1/admin/analytics/day", dependencies=[Depends(admin_dep)])
    async def admin_analytics_day(day: int = 0) -> dict:
        """One local day in full (`day` is any UNIX time in it; now by default): by hour and
        model, by platform, how the calls went and how long they took, the errors' reasons,
        the accounts that cost most."""
        return await asyncio.to_thread(analytics.day, int(day) if day else int(time.time()))

    @app.get("/v1/admin/analytics/platforms", dependencies=[Depends(admin_dep)])
    async def admin_analytics_platforms(days: int = 30) -> dict:
        return await asyncio.to_thread(analytics.platforms, max(1, min(days, 365)))

    @app.get("/v1/admin/analytics/cohorts", dependencies=[Depends(admin_dep)])
    async def admin_analytics_cohorts(days: int = 14) -> dict:
        return await asyncio.to_thread(analytics.cohorts, max(1, min(days, 365)))

    @app.get("/v1/admin/analytics/hands", dependencies=[Depends(admin_dep)])
    async def admin_analytics_hands(days: int = 30) -> dict:
        return await asyncio.to_thread(analytics.hands, max(1, min(days, 365)))

    @app.get("/v1/admin/analytics/quality", dependencies=[Depends(admin_dep)])
    async def admin_analytics_quality(days: int = 30) -> dict:
        return await asyncio.to_thread(analytics.quality, max(1, min(days, 365)))

    @app.get("/v1/admin/analytics/abuse", dependencies=[Depends(admin_dep)])
    async def admin_analytics_abuse(days: int = 30) -> dict:
        return with_places(await asyncio.to_thread(analytics.abuse, max(1, min(days, 365))))

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
    async def admin_allowance_apply(request: Request) -> dict:
        """Bring every account given a smaller allowance up to the current one (0.15)."""
        return cloud.admin_apply_allowance(actor=_actor(request))

    @app.post("/v1/admin/disable", dependencies=[Depends(admin_dep)])
    async def admin_disable(request: Request) -> Response:
        body = await _json(request)
        account_id = cloud.admin_resolve(str(body.get("account_id", "")), str(body.get("identifier", "")))
        disabled = bool(body.get("disabled", True))
        cloud.admin_disable(account_id, disabled, actor=_actor(request))
        hub = getattr(app.state, "hub", None)
        if disabled and hub is not None:
            await hub.drop_account(account_id)
        return Response(status_code=204)

    @app.post("/v1/admin/unlimited", dependencies=[Depends(admin_dep)])
    async def admin_unlimited(request: Request) -> Response:
        body = await _json(request)
        account_id = cloud.admin_resolve(str(body.get("account_id", "")), str(body.get("identifier", "")))
        cloud.admin_unlimited(account_id, bool(body.get("unlimited", True)), actor=_actor(request))
        return Response(status_code=204)

    @app.post("/v1/admin/delete", dependencies=[Depends(admin_dep)])
    async def admin_delete(request: Request) -> Response:
        body = await _json(request)
        account_id = cloud.admin_resolve(str(body.get("account_id", "")), str(body.get("identifier", "")))
        await _forget_account_live_state(account_id)
        cloud.admin_delete(account_id, actor=_actor(request))
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

    def _reply_message(obj: object) -> dict:
        """The assistant's message of a non-streamed reply, whole (content, reasoning, tool
        calls, finish_reason) — what the record keeps."""
        if isinstance(obj, dict):
            for ch in obj.get("choices") or []:
                msg = ch.get("message") if isinstance(ch, dict) else None
                if isinstance(msg, dict):
                    out = dict(msg)
                    if ch.get("finish_reason"):
                        out["finish_reason"] = str(ch["finish_reason"])
                    return out
        return {"role": "assistant", "content": _reply_text(obj)}

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
