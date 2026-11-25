"""The relay's rules: codes, keys, grants, budgets, and what a request costs.

Kept apart from the HTTP layer so the tests can drive it directly and so the
API module stays a thin translation of these calls into status codes.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import __version__, provenance, turnview
from .analytics import sample_shape
from .client import client_version, platform_from, platform_of
from .config import ModelSpec, Settings, menu_warnings
from .controls import Controls
from .crypto import IdentifierCrypto
from .db import SESSION_HUB_RESERVATION_PREFIX, Database, now
from .geo import Place
from .identifiers import BadIdentifier, Identifier, parse
from .nudges import BadNudges
from .nudges import defaults as nudges_defaults
from .nudges import merge as nudges_merge
from .nudges import validate as nudges_validate
from .providers import exhausted_key_line, guidance
from .providers import provider as catalogue_provider
from .record import BLOB_PREFIX, MediaStore, detach_media, inline_media_bytes, is_sha256, media_refs, pack, unpack
from .senders import CodeSender, LogSender, SendError, make_sender

log = logging.getLogger("nanomuse_cloud")

KEY_PREFIX = "nm_"
HUB_KINDS = ("phone", "computer", "web")
HUB_DEVICE_ID = re.compile(r"^[A-Za-z0-9._:-]{4,80}$")
# the settings-table key of the nudges policy (0.18, nudges.py)
NUDGES_KEY = "nudges"

# What one request kind is called in the apps' usage breakdown; the ledger
# keeps the short names.
USAGE_KINDS = ("chat", "image", "video", "realtime")

# Where the person is, as far as the relay can tell (0.17), for the "ways on" when the
# allowance is out: Alibaba Cloud Bailian only signs up accounts from mainland China, so
# the mainland is pointed there first and everyone else to OpenRouter first. `cn`: the
# account's identifier is a mainland phone number, or the request's address is placed in
# mainland China by ip2region; `intl`: the address is placed anywhere else (Hong Kong,
# Macau and Taiwan count as elsewhere — Bailian does not take them either); `unknown`:
# neither (an e-mail account on a local or unplaced address). The apps add their own
# rule on top — a zh-Hans interface counts as the mainland.
REGIONS = ("cn", "intl", "unknown")
_NOT_MAINLAND = ("香港", "澳门", "台湾", "Hong Kong", "Macao", "Macau", "Taiwan")


def region_of_place(place: Place | None) -> str:
    """`cn`, `intl` or `unknown` for where an address was placed (geo.py)."""
    if place is None or place.local or not place.country:
        return "unknown"
    if place.code in ("HK", "MO", "TW"):
        return "intl"
    if place.code == "CN" or place.country in ("中国", "China"):
        where = f"{place.province} {place.city}"
        return "intl" if any(w in where for w in _NOT_MAINLAND) else "cn"
    return "intl"


def hash_password(password: str) -> str:
    """scrypt with a random salt: `scrypt$<salt>$<hash>`, both base64. The
    parameters are the library's recommended interactive ones; a check takes
    a few tens of milliseconds, which is what a sign-in should cost."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def check_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, hash_b64 = stored.split("$", 2)
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=len(expected))
    return hmac.compare_digest(digest, expected)


class CloudError(Exception):
    """An error the app should show. `status` is the HTTP status, `code` a stable
    machine-readable name the app can switch on (it has strings for each)."""

    def __init__(self, status: int, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        # fields the app can act on beside the words (what is left, where to go next)
        self.extra = dict(extra or {})


def _strip_binary(messages: list) -> list:
    """Messages with pictures (data: URLs) replaced by a marker: the words are the sample."""
    out = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        m = dict(m)
        content = m.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") in ("image_url", "input_audio", "video_url", "video"):
                    parts.append({"type": part["type"], "omitted": True})
                elif isinstance(part, dict) and part.get("type") == "text":
                    parts.append({"type": "text", "text": str(part.get("text", ""))})
                else:
                    parts.append(part if isinstance(part, (str, int, float, bool)) else {"type": "other", "omitted": True})
            m["content"] = parts
        out.append(m)
    return out


# What a kept turn holds — the words the apps show under Data controls and the privacy
# policy repeats. _training_view enforces them: this is a promise, not a description.
SAMPLE_KEEPS = {
    "kept": [
        "what you wrote",
        "what the model answered",
        "the tool calls it chose",
        "model, token counts, app and language",
        "where the turn came from: a person or a routine, which turn and step, the relay's model or your own key",
    ],
    "not_kept": ["the system prompt (memory, SOUL, instructions)", "what tools returned", "pictures, audio and clips", "who you are"],
}


def _training_view(messages: list) -> list:
    """The turn as the community's model may learn from it: what the person wrote and what
    the model answered, with the tool calls the model chose — not the system prompt (the
    person's memory, SOUL and instructions), not what a tool returned (their files, their
    screen, what another app showed them), not a picture or a clip (a marker where one was)."""
    out: list[dict] = []
    for m in _strip_binary(messages):
        role = m.get("role")
        if role == "user":
            out.append({"role": "user", "content": m.get("content", "")})
        elif role == "assistant":
            kept: dict = {"role": "assistant", "content": m.get("content", "")}
            if m.get("tool_calls"):
                kept["tool_calls"] = m["tool_calls"]
            out.append(kept)
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": str(m.get("tool_call_id", "")), "content": "", "omitted": True})
        # system, developer and anything else: never kept
    return out


def _fit_messages(messages: list, max_chars: int) -> tuple[str, bool]:
    """The messages as JSON within ``max_chars`` — whole messages dropped from the middle
    (the first message and the last exchange kept), then the longest text cut — so that what
    is stored always parses. Returns the JSON and whether anything was left out. The caller
    passes the training view (``_training_view``), so the first message is the person's
    opening turn, not a system prompt."""
    text = json.dumps(messages, ensure_ascii=False)
    if len(text) <= max_chars:
        return text, False
    msgs = [dict(m) for m in messages if isinstance(m, dict)]
    # 1. drop from the middle, oldest first, keeping the first message and the last two
    while len(text) > max_chars and len(msgs) > 3:
        del msgs[1]
        text = json.dumps(msgs, ensure_ascii=False)
    # 2. cut the longest text until it fits (a single huge paste, a long system prompt)
    for _ in range(50):
        if len(text) <= max_chars:
            break
        longest, where = -1, None
        for i, m in enumerate(msgs):
            c = m.get("content")
            if isinstance(c, str) and len(c) > longest:
                longest, where = len(c), (i, None)
            elif isinstance(c, list):
                for j, part in enumerate(c):
                    if isinstance(part, dict) and isinstance(part.get("text"), str) and len(part["text"]) > longest:
                        longest, where = len(part["text"]), (i, j)
        if where is None or longest < 200:
            break
        over = len(text) - max_chars
        keep = max(100, longest - over - 40)
        i, j = where
        if j is None:
            msgs[i]["content"] = msgs[i]["content"][:keep] + " […]"
        else:
            parts = list(msgs[i]["content"])
            parts[j] = {**parts[j], "text": parts[j]["text"][:keep] + " […]"}
            msgs[i]["content"] = parts
        text = json.dumps(msgs, ensure_ascii=False)
    return text[:max_chars] if len(text) > max_chars else text, True


def _load_messages(text: str) -> tuple[list, bool]:
    """The stored request back as messages. Samples kept before 0.5.2 were cut at a character
    count and may end mid-string: the messages that are whole are returned and the cut is
    reported, rather than the row (and every export) failing on it."""
    if not text:
        return [], False
    try:
        value = json.loads(text)
        return (value if isinstance(value, list) else [value]), False
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    out: list = []
    i = text.find("[")
    if i < 0:
        return [], True
    i += 1
    while i < len(text):
        while i < len(text) and text[i] in " \n\r\t,":
            i += 1
        if i >= len(text) or text[i] == "]":
            break
        try:
            obj, i = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            break
        out.append(obj)
    return out, True


def _load_meta(text: str) -> dict:
    try:
        value = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class Caller:
    key_hash: str
    account_id: str
    channel: str
    hint: str
    granted: int
    used: int
    account_created_at: int
    # A member has no daily money cap: on the operator's list (ALLOWED_IDENTIFIERS,
    # matched by the identifier's hash) or flagged on the account by the operator.
    member: bool = False
    has_password: bool = False
    password_set_at: int | None = None
    # How and when this particular key was issued: a recent code sign-in may
    # set a password without knowing the old one (the reset path).
    via: str = "code"
    key_created_at: int = 0
    key_prefix: str = ""
    # 0.27: once set, this credential may announce only this Hub installation.
    # Empty is a legacy credential whose first accepted hello performs the binding.
    hub_device_id: str = ""
    hub_device_kind: str = ""
    # Invitations (0.4): the code this person hands out and how many came.
    invite_code: str = ""
    invites: int = 0
    # The lifetime pool (0.5), micro-yuan: the allowance, plus what invites and the operator
    # added (and, for accounts from before 0.9, the co-creation bonus of the time). What is
    # spent is the ledger's sum, read when needed.
    grant_uy: int = 0
    contribute_bonus_at: int | None = None
    # Data controls: "Help improve nanoMuse's AI models" is on for this account — only then
    # does the relay keep the text of what was said (service.keep_sample says exactly what).
    contribute: bool = False

    @property
    def remaining(self) -> int:
        return max(0, self.granted - self.used)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _code_hash(key: bytes, code: str) -> str:
    """A sign-in code is six digits, so hashing it plainly is a lookup table: whoever can read
    the database tries all 1,000,000 values in a moment and gets a live code back. Keying the
    hash with the relay's own secret (the same trick as an identifier hash) makes that need the
    secret too. An API key stays a plain hash: 240 random bits are nobody's lookup table.
    A code stored by an older relay does not verify, so one that was in the air when the relay
    updated has to be asked for again."""
    return hmac.new(key, code.encode(), hashlib.sha256).hexdigest()


class InFlight:
    """The requests an account has under way: how many (at most `limit`), and what each is
    expected to cost. The allowance check counts these reservations as spent, so several
    requests started together cannot each pass it and overshoot it together; a request's
    reservation goes when it settles (the ledger then has the real figure). In memory:
    the relay is one process, and a restart loses only the picture of the moment."""

    def __init__(self, limit: int, ttl_s: float = 300.0, clock=time.monotonic):
        self.limit = max(0, limit)
        self.ttl_s = ttl_s  # a request nobody settled (a client gone before its stream began) lapses
        self.clock = clock
        self._held: dict[str, dict[str, tuple[int, float]]] = {}

    def _live(self, account_id: str) -> dict[str, tuple[int, float]]:
        held = self._held.get(account_id)
        if not held:
            return {}
        t = self.clock()
        for rid in [rid for rid, (_, until) in held.items() if until <= t]:
            del held[rid]
        if not held:
            self._held.pop(account_id, None)
        return held

    def count(self, account_id: str) -> int:
        return len(self._live(account_id))

    def reserved(self, account_id: str) -> int:
        return sum(cost for cost, _ in self._live(account_id).values())

    def full(self, account_id: str) -> bool:
        return self.limit > 0 and self.count(account_id) >= self.limit

    def reserve(self, account_id: str, request_id: str, cost_uy: int) -> None:
        self._held.setdefault(account_id, {})[request_id] = (max(0, int(cost_uy)), self.clock() + self.ttl_s)

    def settle(self, account_id: str, request_id: str) -> None:
        held = self._held.get(account_id)
        if held is not None:
            held.pop(request_id, None)
            if not held:
                del self._held[account_id]

    def snapshot(self) -> dict[str, int]:
        """For the admin view: accounts with something under way, and how many requests."""
        return {account_id: len(self._live(account_id)) for account_id in list(self._held) if self._live(account_id)}


class Pace:
    """How many times a key may do a thing within a window: ``limit`` per ``window_s``,
    sliding. In memory, like InFlight; a key not seen for a window is forgotten, and the
    table is capped so a flood of keys cannot grow it without bound (0.30: the record's
    uploads, session keys, the hub's hellos)."""

    MAX_KEYS = 50_000

    def __init__(self, limit: int, window_s: float, clock=time.monotonic):
        self.limit = max(0, limit)
        self.window_s = window_s
        self.clock = clock
        self._seen: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        """Count one more for ``key``; False when it is over the limit (nothing counted then).
        A limit of 0 allows everything."""
        if self.limit <= 0:
            return True
        t = self.clock()
        edge = t - self.window_s
        hits = self._seen.get(key)
        if hits is None:
            if len(self._seen) >= self.MAX_KEYS:
                self._prune(edge)
            hits = self._seen[key] = []
        else:
            while hits and hits[0] <= edge:
                hits.pop(0)
        if len(hits) >= self.limit:
            return False
        hits.append(t)
        return True

    def _prune(self, edge: float) -> None:
        for key in [k for k, v in self._seen.items() if not v or v[-1] <= edge]:
            del self._seen[key]
        if len(self._seen) >= self.MAX_KEYS:  # all of them live: the oldest go
            for key in sorted(self._seen, key=lambda k: self._seen[k][-1])[: self.MAX_KEYS // 2]:
                del self._seen[key]


# What a chat is reserved at while it runs: a typical turn's worth of the model, priced
# like any other. The ledger gets the real figure once the reply is in.
CHAT_RESERVE_PROMPT_TOKENS = 6000
CHAT_RESERVE_COMPLETION_TOKENS = 1500


# What the operator may change from the page while the relay runs (0.15): the name, how a
# value is read, its bounds. Anything else stays with the environment and a restart.
RUNTIME_SETTINGS: dict[str, tuple[type, float, float]] = {
    "allowance_cny": (float, 0.0, 1000.0),
    "invite_bonus_cny": (float, 0.0, 100.0),
    "signup_open": (bool, 0.0, 1.0),
}


class Cloud:
    # The clock a charge is priced by (a model with idle hours); the tests pin it to a known
    # hour, so a suite run at night costs the same as one by day.
    clock: Callable[[], int] = staticmethod(now)

    def __init__(self, settings: Settings, db: Database | None = None, sender: CodeSender | None = None):
        self.env = settings  # what the environment said; `s` has the page's overrides on top
        self.db = db or Database(settings.database)
        self.s = self._with_overrides(settings, self.db.settings_all())
        settings = self.s
        self.in_flight = InFlight(settings.max_in_flight, ttl_s=settings.upstream_timeout_s + 120)
        self.sender = sender or make_sender(settings)
        if settings.dev_mode and not isinstance(self.sender, LogSender):
            # `hmac_key` falls back to a published development constant when CLOUD_SECRET is
            # absent, which is only safe while codes stay in the log: with a sender that really
            # sends, every identifier would be hashable — the member list readable, a live code
            # recoverable — by whoever holds the database alone. `__main__` exits on this for the
            # command line; a relay built here is refused for every other way of starting one.
            raise RuntimeError("CLOUD_SECRET is not set; a relay that sends codes (CODE_SENDER != log) must have one")
        self.crypto = IdentifierCrypto(settings.identifier_key)
        # 0.22: the operator's switches and thresholds (settings table, applied at once)
        self.controls = Controls(self.db, settings)
        # 0.29: the record's files — next to the database unless MEDIA_DIR says otherwise;
        # a relay on an in-memory database (the tests) writes them to a temporary directory
        media_dir = settings.media_dir
        if not media_dir and settings.database != ":memory:":
            media_dir = str(Path(settings.database).parent / "blobs")
        self.media = MediaStore(media_dir or None)
        # 0.30: how fast one account may feed the record (own-key turns and files together),
        # and how often one may mint session keys — each a credential with a hub identity
        self.upload_pace = Pace(settings.record_uploads_per_minute, 60.0)
        self.session_key_pace = Pace(self.SESSION_KEYS_PER_HOUR, 3600.0)
        # 0.31: how many reports around turns one account may send a minute (requests, each
        # of up to provenance.EVENTS_PER_REQUEST events)
        self.event_pace = Pace(self.EVENT_REQUESTS_PER_MINUTE, 60.0)
        self._login_failures: dict[str, list[int]] = {}
        if settings.dev_mode:
            log.warning("CLOUD_SECRET is not set: development mode, identifiers hashed with a fixed key")
        if settings.unlimited:
            log.warning("SIGNUP_TOKENS=0: no token ceiling, usage is metered only")
        for line in menu_warnings(settings.models):
            log.warning("CLOUD_MODELS: %s", line)
        # The members' identifiers, hashed once so a request can be matched
        # against the list without ever seeing the plaintext.
        self.member_hashes: frozenset[str] = frozenset(h for i in self._listed_identifiers() for h in i.hashes(settings.hmac_key))
        # The reviewer's addresses (REVIEW_ADDRESSES), hashed the same way; empty, and so
        # the whole feature off, unless REVIEW_CODE is six digits as well.
        self.review_hashes: frozenset[str] = frozenset(h for i in self._review_identifiers() for h in i.hashes(settings.hmac_key))
        if self.review_hashes:
            log.warning("review sign-in is on for %d address(es): a fixed code, nothing sent", len(self.review_hashes))
        if settings.signup_open:
            log.info(
                "sign-up is open: %d member(s) without a limit, everyone else ¥%.2f in all (+¥%.2f an invite, to both sides); "
                "new accounts start with 'help improve the models' %s",
                len(self.member_hashes),
                settings.allowance_cny,
                settings.invite_bonus_cny,
                "on" if settings.improve_default else "off",
            )
        else:
            log.warning("SIGNUP_OPEN=0: private relay, only the %d listed identifier(s) may sign in", len(self.member_hashes))
        if settings.allowance_uy > 0:
            # A database from before 0.5: every account without a pool that no 0.15+ relay has
            # seen starts the lifetime model with the allowance on top of what it has spent,
            # plus any 0.4 credit an invite had earned it. Idempotent, and it never touches an
            # account the operator set to zero: that one keeps its zero across a restart.
            n = self.db.seed_grants(settings.allowance_uy)
            if n:
                log.warning("0.5: %d account(s) moved to the lifetime allowance (¥%.2f + what was spent)", n, settings.allowance_cny)
        # 0.15: accounts from before the column remember the allowance of the day as theirs.
        n = self.db.seed_allowances(settings.allowance_uy)
        if n:
            log.info("0.15: %d account(s) marked as given the ¥%.2f allowance", n, settings.allowance_cny)

    @property
    def reads(self) -> Cloud:
        """0.30: the same service, its `db` the read-only connection (Database.reader): the
        console's pages, the statistics and the exports run through it, in a thread (api.py),
        so a query of seconds never holds the lock every request takes for its own few rows.
        The methods are the same; a write through it fails with sqlite3's "readonly database",
        which is the point. A fresh shallow copy each time, so a setting the operator changed
        (`s`) is the one the view reads; the connection behind it is opened once. On an
        in-memory database (the tests) the connection is the same one."""
        view = copy.copy(self)
        view.db = self.db.reader()
        return view

    # -- settings the operator changes while the relay runs (0.15) ------------------------------

    @staticmethod
    def _coerce_setting(key: str, value: Any) -> Any:
        """One override, checked: the right type, within bounds. ValueError says what is wrong."""
        kind, lo, hi = RUNTIME_SETTINGS[key]
        if kind is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)) and value in (0, 1):
                return bool(value)
            if isinstance(value, str) and value.strip().lower() in ("0", "1", "true", "false", "yes", "no", "on", "off"):
                return value.strip().lower() in ("1", "true", "yes", "on")
            raise ValueError(f"{key} is true or false")
        try:
            number = float(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"{key} is a number") from e
        if number != number or not lo <= number <= hi:  # NaN, or out of bounds
            raise ValueError(f"{key} is between {lo:g} and {hi:g}")
        return round(number, 4)

    @classmethod
    def _with_overrides(cls, settings: Settings, overrides: dict[str, Any]) -> Settings:
        """The environment's settings with the page's values on top — only the known keys,
        only values that still make sense (a bad row is ignored, not fatal)."""
        good: dict[str, Any] = {}
        for key, value in overrides.items():
            if key not in RUNTIME_SETTINGS:
                continue
            try:
                good[key] = cls._coerce_setting(key, value)
            except ValueError as e:
                log.warning("settings: ignoring the stored %s: %s", key, e)
        return replace(settings, **good) if good else settings

    def runtime_settings(self) -> dict:
        """For the page: each runtime setting with the value in force, what the environment
        says, and whether the page set it — plus how many accounts a raise would reach."""
        stored = self.db.settings_all()
        out: dict[str, Any] = {"values": {}, "env": {}, "overridden": {}}
        for key in RUNTIME_SETTINGS:
            out["values"][key] = getattr(self.s, key)
            out["env"][key] = getattr(self.env, key)
            out["overridden"][key] = key in stored
        out["below_allowance"] = self.db.below_allowance(self.s.allowance_uy, self.member_hashes) if self.s.allowance_cny > 0 else 0
        return out

    def admin_update_settings(self, body: dict, actor: str = "console") -> dict:
        """The page saved: each known key is set (a value), or cleared back to the environment
        (null). Takes effect at once (the next sign-up gets the new allowance, the next /v1/me
        shows the new figures) and survives a restart. Nothing is taken from anyone: a lower
        allowance only changes what new accounts get; a higher one reaches the existing
        accounts when the operator asks (admin_apply_allowance). The audit log says who."""
        changes: dict[str, Any] = {}
        for key in RUNTIME_SETTINGS:
            if key not in body:
                continue
            value = body[key]
            if value is None or value == "":
                changes[key] = None
                continue
            try:
                changes[key] = self._coerce_setting(key, value)
            except ValueError as e:
                raise CloudError(400, "bad_request", str(e)) from e
        if not changes:
            raise CloudError(400, "bad_request", "Nothing to set: " + ", ".join(RUNTIME_SETTINGS))
        for key, value in changes.items():
            self.db.settings_put(key, value)
        self.s = self._with_overrides(self.env, self.db.settings_all())
        said = ", ".join(f"{k}={'env' if v is None else v}" for k, v in changes.items())
        log.warning("settings changed from the page: %s", said)
        self.db.add_event("", "settings.changed", said[:200])
        self.db.audit_add(actor, "settings.changed", "", said)
        return self.runtime_settings()

    def admin_apply_allowance(self, actor: str = "console") -> dict:
        """Bring the accounts that were given less than the current allowance up to it."""
        if self.s.allowance_cny <= 0:
            raise CloudError(400, "bad_request", "There is no allowance to apply (0 = no limit)")
        n = self.db.raise_allowance(self.s.allowance_uy, self.member_hashes)
        log.warning("allowance ¥%.2f applied to %d existing account(s)", self.s.allowance_cny, n)
        self.db.add_event("", "allowance.applied", f"¥{self.s.allowance_cny:g} to {n}")
        self.db.audit_add(actor, "allowance.applied", "", f"¥{self.s.allowance_cny:g} to {n} account(s)")
        return {"accounts": n, "allowance_cny": self.s.allowance_cny}

    def admin_credit_all(self, cny: float, note: str = "", actor: str = "console") -> dict:
        """The same credit into every limited account's pool at once; negative takes the same
        away from each (0.16), never below zero."""
        if cny == 0 or not -100 <= cny <= 100:
            raise CloudError(400, "bad_request", "A credit for everyone is between -¥100 and ¥100, not 0")
        if cny < 0:
            return self.admin_set_pool_many({"all": True, "delta_cny": cny, "note": note}, actor=actor)
        n = self.db.credit_all(self.s.cny_to_uy(cny), note=note, exclude_hashes=self.member_hashes)
        log.warning("¥%.2f credited to %d account(s): %s", cny, n, note)
        self.db.add_event("", "credit.all", f"¥{cny:g} to {n}: {note}"[:200])
        self.db.audit_add(actor, "credit.all", "", f"¥{cny:g} to {n} account(s){' · ' + note if note else ''}")
        return {"accounts": n, "cny": cny}

    # The pool set by the operator (0.16): exactly one of these says how.
    POOL_MODES = ("left_cny", "grant_cny", "delta_cny")

    def _pool_change(self, body: dict) -> tuple[str, float]:
        """Which of left_cny / grant_cny / delta_cny the request carries, and the figure in
        yuan — one of them, a number, within reason (a pool is at most ¥10 000)."""
        given = [k for k in self.POOL_MODES if body.get(k) is not None and body.get(k) != ""]
        if len(given) != 1:
            raise CloudError(400, "bad_request", "Say one of left_cny, grant_cny or delta_cny")
        mode = given[0]
        try:
            value = float(body[mode])
        except (TypeError, ValueError) as e:
            raise CloudError(400, "bad_request", f"{mode} is a number") from e
        if value != value or value in (float("inf"), float("-inf")):
            raise CloudError(400, "bad_request", f"{mode} is a number")
        if mode == "delta_cny":
            if value == 0 or not -10_000 <= value <= 10_000:
                raise CloudError(400, "bad_request", "delta_cny is between -¥10000 and ¥10000, not 0")
        elif not 0 <= value <= 10_000:
            raise CloudError(400, "bad_request", f"{mode} is between ¥0 and ¥10000")
        return mode, value

    def _pool_words(self, mode: str, value: float) -> str:
        if mode == "left_cny":
            return f"¥{value:g} left"
        if mode == "grant_cny":
            return f"pool ¥{value:g}"
        return f"{'+' if value > 0 else '−'}¥{abs(value):g}"

    def admin_set_pool(self, account_id: str, body: dict, actor: str = "console") -> dict:
        """One account's pool set by the operator: to what is left, to a total, or by a
        difference up or down. The account's timeline says so and the audit log says who;
        the reply is the account with its pool fields, as /v1/admin/credit answers."""
        if self.db.account(account_id) is None:
            raise CloudError(404, "no_account", "No such account")
        mode, value = self._pool_change(body)
        note = str(body.get("note", ""))[:200]
        uy = self.s.cny_to_uy(abs(value)) * (-1 if value < 0 else 1)
        new = self.db.set_pool(account_id, **{mode.replace("_cny", "_uy"): uy}, note=note)
        words = self._pool_words(mode, value)
        log.warning("pool of %s set from the page: %s → ¥%.2f (%s)", account_id[:8], words, self.s.uy_to_cny(new or 0), note)
        self.db.add_event(account_id, "pool.set", f"{words}{' · ' + note if note else ''}"[:200])
        self.db.audit_add(actor, "pool.set", account_id[:8], f"{words}{' · ' + note if note else ''}")
        a = dict(self.db.account(account_id))  # type: ignore[arg-type]
        a["identifier"] = self.crypto.decrypt(account_id, a.pop("identifier_enc", "")) or ""
        a["member"] = bool(a.get("unlimited")) or a.pop("id_hash", None) in self.member_hashes
        a.pop("id_hash", None)
        a.pop("password_hash", None)
        a["spent_cny"] = self.s.uy_to_cny(self.db.spent_since(account_id, 0))
        self._pool_fields(a, spent_cny=a["spent_cny"])
        return a

    def admin_set_pool_many(self, body: dict, actor: str = "console") -> dict:
        """The same change to a set of accounts: the ids given (a filtered list on the
        page), or every limited account when `all` is set; members and disabled accounts are
        left out of `all`. Returns how many pools moved; the audit log says who."""
        mode, value = self._pool_change(body)
        note = str(body.get("note", ""))[:200]
        if body.get("all"):
            ids = self.db.limited_account_ids(exclude_hashes=self.member_hashes)
        else:
            raw = body.get("account_ids")
            if not isinstance(raw, list) or not raw:
                raise CloudError(400, "bad_request", "Give account_ids, or all: true")
            if len(raw) > 5000:
                raise CloudError(400, "bad_request", "At most 5000 accounts at a time")
            ids = [str(x) for x in raw if isinstance(x, str) and x]
        uy = self.s.cny_to_uy(abs(value)) * (-1 if value < 0 else 1)
        words = self._pool_words(mode, value)
        n = 0
        for account_id in ids:
            if self.db.set_pool(account_id, **{mode.replace("_cny", "_uy"): uy}, note=note) is None:
                continue
            self.db.add_event(account_id, "pool.set", f"{words}{' · ' + note if note else ''}"[:200])
            n += 1
        log.warning("pool of %d account(s) set from the page: %s (%s)", n, words, note)
        self.db.add_event("", "pool.set.many", f"{words} to {n}{' · ' + note if note else ''}"[:200])
        self.db.audit_add(actor, "pool.set.many", "", f"{words} to {n} account(s){' · ' + note if note else ''}")
        return {"accounts": n, mode: value}

    def public_config(self) -> dict:
        """What a client may know before anyone signs in — the figures the sign-in pages and
        the account screens print, so a change on the operator's page shows everywhere at
        once and no app carries a number of its own. Nothing here is a secret."""
        return {
            "version": __version__,
            "signup_open": self.s.signup_open and self.controls.on("signups"),
            # 0.22: which of the operator's switches are off, so a sign-in page can say so
            "paused": [k for k, v in self.controls.paused().items() if v],
            "allowance_cny": self.s.allowance_cny,
            "allowance_usd": self.s.cny_to_usd(self.s.allowance_cny),
            "invite_bonus_cny": self.s.invite_bonus_cny,
            "invitee_bonus_cny": self.s.invite_bonus_cny,
            "usd_cny": self.s.usd_cny,
            "invite_url": self.s.invite_url,
            "own_key_docs": self.s.own_key_docs,
            "openrouter_url": self.s.openrouter_url,
            "privacy_url": self.s.privacy_url,
            "repo_url": self.s.repo_url,
            "improve_default": self.s.improve_default,
            # how long a sign-in code is good for and the shortest password accepted, so the
            # sign-in and password forms print the relay's figures and not their own
            "code_ttl_s": self.s.code_ttl_s,
            "password_min_len": self.s.password_min_len,
        }

    # -- sign-up -------------------------------------------------------------------

    def _listed_identifiers(self) -> list[Identifier]:
        out = []
        for item in self.s.allowed_identifiers.split(","):
            if not item.strip():
                continue
            try:
                out.append(parse(item))
            except BadIdentifier:
                log.warning("ALLOWED_IDENTIFIERS has an entry that is neither a number nor an address; ignored")
        return out

    def _review_identifiers(self) -> list[Identifier]:
        """The reviewer's addresses (REVIEW_ADDRESSES) — only when REVIEW_CODE is six digits
        too; an entry that is not an e-mail address is ignored (a reviewer has no mainland
        number, and a fixed code on a number is not something to offer)."""
        code = self.s.review_code.strip()
        if not (len(code) == 6 and code.isdigit()):
            if self.s.review_addresses.strip():
                log.warning("REVIEW_ADDRESSES is set but REVIEW_CODE is not six digits; review sign-in is off")
            return []
        out = []
        for item in self.s.review_addresses.split(","):
            if not item.strip():
                continue
            try:
                ident = parse(item)
            except BadIdentifier:
                log.warning("REVIEW_ADDRESSES has an entry that is not an address; ignored")
                continue
            if ident.channel != "email":
                log.warning("REVIEW_ADDRESSES has a phone number; only e-mail addresses are taken")
                continue
            out.append(ident)
        return out

    def listed(self, ident: Identifier) -> bool:
        """On the operator's list (ALLOWED_IDENTIFIERS)."""
        return ident.hash(self.s.hmac_key) in self.member_hashes

    def is_review(self, ident: Identifier) -> bool:
        """The reviewer's address (REVIEW_ADDRESSES, with REVIEW_CODE set)."""
        return bool(self.review_hashes) and ident.hash(self.s.hmac_key) in self.review_hashes

    def allowed(self, ident: Identifier) -> bool:
        """May this identifier sign in? Anyone when sign-up is open; else members only — and
        the reviewer's address either way, since the operator named it."""
        return self.s.signup_open or self.listed(ident) or self.is_review(ident)

    def _account_for(self, ident: Identifier) -> sqlite3.Row | None:
        """Look up an account by ``ident``'s canonical hash, falling back to its
        legacy pre-canonical hash when present so existing dotted Gmail accounts
        keep matching."""
        return self.db.account_by_hashes(ident.hashes(self.s.hmac_key), shared=ident.merged_hash(self.s.hmac_key))

    def _refuse_if_signups_closed(self, ident: Identifier) -> None:
        """0.22: the *Sign-ups* switch is off; an identifier without an account is turned
        away (`signup_closed`); everyone who already has one carries on, and so does the
        reviewer's address (a review must not fail on a paused switch)."""
        if self.controls.on("signups") or self.is_review(ident) or self._account_for(ident) is not None:
            return
        raise CloudError(
            403,
            "signup_closed",
            "New sign-ups are paused on this relay for now; existing accounts keep working. Try again later.",
        )

    def _is_blocked_domain(self, domain: str) -> bool:
        """Whether ``domain`` or one of its parent domains is on the disposable-mail blocklist
        and not explicitly allowed in ``signup_domain_allow_set``."""
        if domain in self.s.signup_domain_allow_set:
            return False
        blocked = self.s.signup_domain_block_set
        if not blocked:
            return False
        if domain in blocked:
            return True
        return any(domain.endswith("." + b) for b in blocked)

    def _refuse_if_domain_limited(self, ident: Identifier) -> None:
        """At most SIGNUP_PER_DOMAIN_DAY new accounts per e-mail domain per rolling day, for
        domains that are not a well known provider or on the allow list: an address of such
        a domain without an account yet is turned away (`domain_limited`) once the day's
        count is reached, and domains on the disposable blocklist are refused for new
        sign-ups right away. An existing account always gets its code; phone numbers are
        never limited; the reviewer's address is never limited."""
        if ident.channel != "email" or self.is_review(ident):
            return
        domain = ident.value.rpartition("@")[2].lower()
        if not domain:
            return
        if self._is_blocked_domain(domain):
            if self._account_for(ident) is not None:
                return
            self.db.add_event("", "signup.domain_limited", domain[:200])
            raise CloudError(
                429,
                "domain_limited",
                "This address's domain has reached today's sign-up limit on this relay; try again tomorrow or use another address",
            )
        limit = self.s.signup_per_domain_day
        if limit <= 0 or domain in self.s.signup_domain_allow_set:
            return
        if self._account_for(ident) is not None:
            return
        if self.db.signups_from_domain_since(domain, now() - 86400) < limit:
            return
        self.db.add_event("", "signup.domain_limited", domain[:200])
        raise CloudError(
            429,
            "domain_limited",
            "This address's domain has reached today's sign-up limit on this relay; try again tomorrow or use another address",
        )

    def request_code(self, ident: Identifier, ip: str) -> None:
        review = self.is_review(ident)
        if not review and not self.sender.accepts(ident):
            # the honest answer up front: a Hong Kong or overseas number gets no SMS from
            # 号码认证, so the person should not wait for one; e-mail works everywhere
            if ident.channel == "phone" and not ident.value.startswith("+86"):
                raise CloudError(
                    400,
                    "phone_region",
                    "Codes reach mainland China numbers only for now; elsewhere, sign in with an e-mail address",
                )
            raise CloudError(
                400,
                "channel_unsupported",
                f"This relay does not send codes by {'SMS' if ident.channel == 'phone' else 'e-mail'}",
            )
        if not self.allowed(ident):
            raise CloudError(403, "not_invited", "This relay is private; that address is not on its list")
        self._refuse_if_signups_closed(ident)
        self._refuse_if_domain_limited(ident)
        account = self._account_for(ident)
        disabled = account is not None and bool(account["disabled"])
        # The reviewer's code is the fixed one and goes nowhere: the row is written like
        # anyone's, so the lifetime, the attempt limit and the rate limits are the same.
        code = self.s.review_code.strip() if review else f"{secrets.randbelow(1_000_000):06d}"
        limited = self.db.insert_code_limited(
            ident.hash(self.s.hmac_key),
            _code_hash(self.s.hmac_key, code),
            ip,
            self.s.code_ttl_s,
            self.s.code_per_identifier_10m,
            self.s.code_per_ip_hour,
        )
        if limited == "identifier":
            raise CloudError(429, "code_too_often", "Too many codes for this address; wait a few minutes")
        if limited == "ip":
            raise CloudError(429, "code_too_often", "Too many codes from this network; wait an hour")
        if review:
            log.info("review sign-in: a code request for the reviewer's address; nothing sent")
            return
        if disabled:
            # Refused quietly: the row above is written and the answer is the same 204 as
            # anyone's, so this route tells a stranger nothing about the number (not that it
            # has an account, not that the operator switched it off) and the per-identifier
            # and per-address limits behave exactly as they do for an enabled account. No
            # SMS or mail is paid for; the code itself goes nowhere, and whoever holds the
            # account hears `403 account_disabled` at /v1/auth/verify, as before.
            log.info("code request for a disabled account; nothing sent")
            return
        try:
            self.sender.send(ident, code)
        except SendError as e:
            if e.reason == "too_often":
                # the carrier's own limit for the number, tighter than ours: the same answer
                # as our limit, so the app says "wait" and not that the relay is broken
                raise CloudError(429, "code_too_often", "Too many codes for this number; wait a few minutes") from e
            raise CloudError(502, "send_failed", f"Could not send the code ({e})") from e

    def verify_code(
        self,
        ident: Identifier,
        code: str,
        device: str,
        invite: str = "",
        hub_device_id: str = "",
        hub_device_kind: str = "",
    ) -> tuple[str, Caller, bool]:
        """Returns (api_key, caller, created). The key is shown once. `invite` is
        a friend's code; it counts only when this sign-in creates the account."""
        if not self.allowed(ident):
            raise CloudError(403, "not_invited", "This relay is private; that address is not on its list")
        id_hash = ident.hash(self.s.hmac_key)
        result = self.db.check_code(id_hash, _code_hash(self.s.hmac_key, code.strip()), self.s.code_max_attempts)
        if result == "expired":
            raise CloudError(400, "code_expired", "The code has expired; ask for a new one")
        if result == "wrong":
            raise CloudError(400, "code_wrong", "That code is not right")
        return self.sign_in(ident, device, "code", invite, hub_device_id, hub_device_kind)

    def sign_in(
        self,
        ident: Identifier,
        device: str,
        via: str,
        invite: str = "",
        hub_device_id: str = "",
        hub_device_kind: str = "",
    ) -> tuple[str, Caller, bool]:
        """An identifier that has just been proven (a code, the carrier's word) becomes a
        signed-in device: the account is made on first sight, a key is issued.
        Returns (api_key, caller, created)."""
        if not self.allowed(ident):
            raise CloudError(403, "not_invited", "This relay is private; that address is not on its list")
        id_hash = ident.hash(self.s.hmac_key)
        account = self._account_for(ident)
        created = account is None
        if account is None:
            self._refuse_if_signups_closed(ident)
            self._refuse_if_domain_limited(ident)
            account_id = self.db.new_account_id()
            enc = self.crypto.encrypt(account_id, ident.value)
            domain = ident.value.rpartition("@")[2].lower() if ident.channel == "email" else ""
            domain_limit = (
                self.s.signup_per_domain_day if domain and not self.is_review(ident) and domain not in self.s.signup_domain_allow_set else 0
            )
            account, created = self.db.create_account_limited(
                id_hash,
                ident.channel,
                ident.hint,
                self.s.signup_tokens,
                enc,
                account_id,
                self.s.allowance_uy,
                domain=domain,
                domain_limit=domain_limit,
                domain_since=now() - 86400,
            )
            if account is None:
                self.db.add_event("", "signup.domain_limited", domain[:200])
                raise CloudError(
                    429,
                    "domain_limited",
                    "This address's domain has reached today's sign-up limit on this relay; try again tomorrow or use another address",
                )
            account_id = str(account["id"])
        else:
            account_id = str(account["id"])
        if created:
            self.db.add_event(account_id, "account.created", ident.channel)
            if self.s.improve_default:
                # the relay's default for a new account, said on its timeline as such (not as a
                # choice the person made); it is theirs to turn off under Data controls
                self.db.set_contribute(account_id, True)
                self.db.add_event(account_id, "contribute.default", "on")
            self._accept_invite(account_id, invite)
        elif account["disabled"]:
            raise CloudError(403, "account_disabled", "This account is disabled")

        key, caller = self._issue_key(
            account["id"],
            device,
            via=via,
            hub_device_id=hub_device_id,
            hub_device_kind=hub_device_kind,
            replace_hub_identity=bool(hub_device_id),
        )
        self.db.add_event(account["id"], f"sign_in.{via}", device)
        if created:
            # the switches flip now; a notify rule's e-mail goes on its own thread, so this
            # sign-in does not wait on SMTP
            self.evaluate_thresholds(defer_mail=True)
        return key, caller, created

    def evaluate_thresholds(self, *, defer_mail: bool = False) -> list[dict[str, Any]]:
        """0.22: the operator's "when accounts reach N" rules, against the count right now.
        Called after an account is made (``defer_mail``: the e-mail leaves on a thread of
        its own) and once a minute from the server; a failure here must not break a
        sign-in."""
        try:
            fired = self.controls.evaluate(self.db.account_counts()["total"], defer_mail=defer_mail)
            if defer_mail:
                self.controls.flush_notices_later()
            return fired
        except Exception as e:  # noqa: BLE001 — a rule misfiring must not cost a sign-in
            log.warning("thresholds: could not evaluate: %s", e)
            return []

    def rules_tick(self) -> list[dict[str, Any]]:
        """The minute timer's call: evaluate, then send any notice a sign-in queued whose
        thread did not get to it."""
        fired = self.evaluate_thresholds()
        try:
            self.controls.flush_notices()
        except Exception as e:  # noqa: BLE001
            log.warning("thresholds: could not send a queued notice: %s", e)
        return fired

    # -- invitations ------------------------------------------------------------------

    @staticmethod
    def normalize_invite(code: str) -> str:
        """Codes are eight letters and digits, shown in upper case; typed any way."""
        return re.sub(r"[^A-Z0-9]", "", (code or "").upper())[:8]

    def _accept_invite(self, new_account_id: str, invite: str) -> None:
        code = self.normalize_invite(invite)
        if not code:
            return
        inviter = self.db.account_by_invite_code(code)
        if inviter is None or inviter["id"] == new_account_id or inviter["disabled"]:
            # a wrong code is not an error: the person is signed in either way
            self.db.add_event(new_account_id, "invite.unknown")
            return
        # the link and the counter now; the bonus (the same to both sides, 0.9) when the
        # newcomer first uses the relay (settle_invite), so a sign-up alone pays nobody
        self.db.link_invite(inviter["id"], new_account_id)
        self.db.add_event(inviter["id"], "invite.accepted", new_account_id[:8])
        self.db.add_event(new_account_id, "invite.used", inviter["id"][:8])
        log.info("invite: %s brought %s (+¥%.2f each at first use)", inviter["id"][:8], new_account_id[:8], self.s.invite_bonus_cny)

    def settle_invite(self, account_id: str) -> bool:
        """Called after every charged request: when the account came through a code and its
        bonus is still unpaid, both pools grow by the bonus in force now and both timelines
        say so (`invite.settled`). One lookup by primary key on the common path; the
        settlement itself happens once per account. A failure here must not cost a request."""
        try:
            if not self.db.invite_pending(account_id):
                return False
            settled, inviter_id, inviter_paid = self.db.settle_invite(
                account_id,
                self.s.cny_to_uy(self.s.invite_bonus_cny),
                min_spent_uy=self.s.invite_settle_min_spent_uy,
                refuse_same_ip=True,
            )
        except sqlite3.Error as e:
            log.warning("invite: could not settle for %s: %s", account_id[:8], e)
            return False
        if not settled:
            return False
        self.db.add_event(account_id, "invite.settled", inviter_id[:8])
        if inviter_paid:
            self.db.add_event(inviter_id, "invite.settled", account_id[:8])
        log.info(
            "invite: %s used the relay, +¥%.2f to %s",
            account_id[:8],
            self.s.invite_bonus_cny,
            "both" if inviter_paid else "the newcomer only",
        )
        return True

    def invite_code_for(self, caller: Caller) -> str:
        """The account's code, made on first ask (no confusable letters)."""
        if caller.invite_code:
            return caller.invite_code
        alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
        for _ in range(20):
            code = "".join(secrets.choice(alphabet) for _ in range(8))
            if self.db.set_invite_code(caller.account_id, code):
                return code
            row = self.db.account(caller.account_id)
            if row is not None and row["invite_code"]:
                return str(row["invite_code"])
        raise CloudError(500, "invite_code", "Could not make an invite code; try again")

    def invite_view(self, caller: Caller) -> dict:
        code = self.invite_code_for(caller)
        # from the ledger, not invites × today's bonus: the bonus may have been another
        # figure when some of these friends signed up
        earned = self.s.uy_to_cny(self.db.invite_earned_uy(caller.account_id))
        friends = self.db.invitees(caller.account_id)
        settled = sum(1 for r in friends if r["invite_settled_at"] is not None)
        return {
            "code": code,
            "url": self.s.invite_url + code if self.s.invite_url else "",
            # sign-ups recorded with the code (the counter), as the apps have always read it
            "invites": caller.invites,
            "bonus_cny": self.s.invite_bonus_cny,
            # 0.9: the friend who signs up with the code gets the same
            "invitee_bonus_cny": self.s.invite_bonus_cny,
            # the bonus is paid to both sides at the friend's first charged request, not at
            # sign-up: how many friends have been paid for and how many are still to be
            "bonus_when": "first_use",
            "settled": settled,
            "pending": max(0, len(friends) - settled),
            "earned_cny": earned,
            # 0.4 names, one more version: the money invites brought (there is no separate
            # credit any more, it is all one pool) and no clips to count
            "credit_cny": earned,
            "credit_left_cny": earned,
            "clips_per_invite": 0,
            "friends": [
                {"hint": r["hint"], "joined_at": int(r["created_at"]), "settled": r["invite_settled_at"] is not None} for r in friends
            ],
        }

    @staticmethod
    def clips_view() -> dict:
        """0.5 counts no clips apart — a clip is just the most expensive thing on the one
        allowance. Kept in the shape 0.4 phones read so they show 「不限」."""
        return {"unlimited": True, "allowed": None, "used": 0, "left": None, "per_face": 4}

    @staticmethod
    def validate_hub_identity(device_id: str, kind: str, *, optional: bool = True) -> tuple[str, str]:
        """Validate the identity a new credential will own.

        Old clients omit both fields and bind at their first hello during the
        compatibility release. Supplying only one is never interpreted loosely.
        """
        device_id = str(device_id or "")
        kind = str(kind or "")
        if optional and not device_id and not kind:
            return "", ""
        if kind not in HUB_KINDS:
            raise CloudError(400, "bad_device", "device_kind must be phone, computer or web")
        if not HUB_DEVICE_ID.fullmatch(device_id):
            raise CloudError(400, "bad_device", "device_id must be 4–80 letters, digits, . _ : -")
        return device_id, kind

    def _issue_key(
        self,
        account_id: str,
        device: str,
        via: str,
        expires_at: int | None = None,
        hub_device_id: str = "",
        hub_device_kind: str = "",
        replace_hub_identity: bool = False,
    ) -> tuple[str, Caller]:
        hub_device_id, hub_device_kind = self.validate_hub_identity(hub_device_id, hub_device_kind)
        key = KEY_PREFIX + secrets.token_urlsafe(30)
        self.db.insert_key(
            _sha256(key),
            key[:10],
            account_id,
            device,
            via=via,
            expires_at=expires_at,
            hub_device_id=hub_device_id,
            hub_device_kind=hub_device_kind,
            replace_hub_identity=replace_hub_identity,
        )
        caller = self._caller(_sha256(key))
        assert caller is not None
        return key, caller

    SESSION_KEY_MAX_S = 90 * 86400
    #: session keys one account may mint an hour: a gateway starts a few containers a day,
    #: and each key is a short-lived computer Hub identity of its own (0.30)
    SESSION_KEYS_PER_HOUR = 30

    def session_key(self, caller: Caller, device: str, ttl_s: int) -> tuple[str, int]:
        """A key that stops working on its own after `ttl_s` (at most 90 days), for a place
        that should not hold a standing one. nanoMuse Web gets one at sign-in and the
        gateway keeps nothing. Issued to the account of the key making the request; the
        requesting key is untouched (the caller revokes it if it has no further use for it).
        A session key cannot mint another: otherwise a key that lapses in an hour could
        hand itself 90 more days, and a container that leaked one would hold the account
        for as long as it liked. It is issued with a server-generated computer reservation.
        The container runtime replaces that reservation with its own free computer id on
        first hello, then the credential is fixed to that installation."""
        if caller.via == "session":
            raise CloudError(403, "session_from_session", "A session key cannot issue another session key; use the device's own key")
        if not self.session_key_pace.allow(caller.account_id):
            raise CloudError(429, "rate_limited", f"At most {self.SESSION_KEYS_PER_HOUR} session keys an hour for one account")
        ttl = max(60, min(int(ttl_s), self.SESSION_KEY_MAX_S))
        expires_at = now() + ttl
        key, _ = self._issue_key(
            caller.account_id,
            device or "session",
            via="session",
            expires_at=expires_at,
            hub_device_id=SESSION_HUB_RESERVATION_PREFIX + secrets.token_hex(12),
            hub_device_kind="computer",
        )
        self.db.add_event(caller.account_id, "sign_in.session", (device or "session")[:60])
        return key, expires_at

    # -- passwords --------------------------------------------------------------------

    def _check_new_password(self, password: str, ident_value: str = "") -> None:
        if len(password) < self.s.password_min_len:
            raise CloudError(400, "password_short", f"Use at least {self.s.password_min_len} characters")
        if len(password) > 128:
            raise CloudError(400, "password_long", "That password is too long")
        if len(set(password)) < 3:
            raise CloudError(400, "password_weak", "Use a few different characters")
        if ident_value and password.strip().lower() == ident_value.strip().lower():
            raise CloudError(400, "password_weak", "The password cannot be the address itself")

    def set_password(self, caller: Caller, password: str, current: str | None = None) -> None:
        """Set or change the password. When one is already set, the old one is
        needed — unless this key came from a code sign-in a few minutes ago,
        which is the "forgot it" path (the code proved the phone or mailbox)."""
        account = self.db.account(caller.account_id)
        if account is None:
            raise CloudError(404, "no_account", "No such account")
        self._check_new_password(password, self.crypto.decrypt(caller.account_id, account["identifier_enc"] or "") or "")
        stored = account["password_hash"] or ""
        if stored:
            fresh_code = caller.via == "code" and now() - caller.key_created_at <= self.s.password_reset_window_s
            if not fresh_code:
                if not current:
                    raise CloudError(400, "password_required", "Enter the current password (or sign in with a code first)")
                if not check_password(current, stored):
                    left = self.db.login_failed(caller.account_id, self.s.password_max_attempts, self.s.lockout_s)
                    raise CloudError(
                        400,
                        "password_wrong",
                        f"That is not the current password ({left} tries left)"
                        if left
                        else "Too many wrong tries; sign in with a code to reset it",
                    )
        self.db.set_password(caller.account_id, hash_password(password))
        self.db.add_event(caller.account_id, "password.set" if not stored else "password.changed")

    def clear_password(self, caller: Caller, current: str) -> None:
        account = self.db.account(caller.account_id)
        if account is None or not account["password_hash"]:
            return
        if not check_password(current, account["password_hash"]):
            raise CloudError(400, "password_wrong", "That is not the current password")
        self.db.set_password(caller.account_id, "")
        self.db.add_event(caller.account_id, "password.cleared")

    def login_password(
        self,
        ident: Identifier,
        password: str,
        device: str,
        ip: str = "",
        hub_device_id: str = "",
        hub_device_kind: str = "",
    ) -> tuple[str, Caller]:
        """Sign in on a new device with the password instead of waiting for a code."""
        if ip and self._login_failures_from(ip) >= self.s.login_fail_per_ip_hour > 0:
            raise CloudError(429, "locked", "Too many wrong passwords from this network; wait a while or sign in with a code")
        if not self.allowed(ident):
            raise CloudError(403, "not_invited", "This relay is private; that address is not on its list")
        account = self._account_for(ident)
        if account is None:
            # Same answer as a wrong password: the sign-in form must not tell
            # whether a number has an account.
            hash_password("x")  # keep the timing alike
            self._note_login_failure(ip)
            self.db.add_event("", "sign_in.failed", ident.channel)
            raise CloudError(401, "bad_credentials", "That address and password do not match")
        locked_until = account["locked_until"]
        if locked_until and int(locked_until) > now():
            raise CloudError(429, "locked", "Too many wrong passwords; wait a while or sign in with a code")
        if not account["password_hash"]:
            hash_password("x")
            self._note_login_failure(ip)
            self.db.add_event(account["id"], "sign_in.failed", device)
            raise CloudError(401, "bad_credentials", "That address and password do not match")
        if not check_password(password, account["password_hash"]):
            left = self.db.login_failed(account["id"], self.s.password_max_attempts, self.s.lockout_s)
            self._note_login_failure(ip)
            self.db.add_event(account["id"], "sign_in.failed", device)
            if left == 0:
                raise CloudError(429, "locked", "Too many wrong passwords; wait a while or sign in with a code")
            raise CloudError(401, "bad_credentials", "That address and password do not match")
        if account["disabled"]:
            # Only the holder of the right password hears that the account is disabled; a
            # probe with a guessed password gets the same answer as for any wrong password.
            raise CloudError(403, "account_disabled", "This account is disabled")
        self.db.login_succeeded(account["id"])
        key, caller = self._issue_key(
            account["id"],
            device,
            via="password",
            hub_device_id=hub_device_id,
            hub_device_kind=hub_device_kind,
            replace_hub_identity=bool(hub_device_id),
        )
        self.db.add_event(account["id"], "sign_in.password", device)
        return key, caller

    def _login_failures_from(self, ip: str) -> int:
        """Wrong passwords this network address has sent in the last hour."""
        cutoff = now() - 3600
        stamps = [t for t in self._login_failures.get(ip, ()) if t >= cutoff]
        if stamps:
            self._login_failures[ip] = stamps
        else:
            self._login_failures.pop(ip, None)
        return len(stamps)

    def _note_login_failure(self, ip: str) -> None:
        if not ip:
            return
        if len(self._login_failures) >= 10_000 and ip not in self._login_failures:
            # a flood of addresses: forget the oldest rather than grow without bound
            cutoff = now() - 3600
            for stale in [k for k, v in self._login_failures.items() if not v or v[-1] < cutoff]:
                del self._login_failures[stale]
        self._login_failures.setdefault(ip, []).append(now())

    # -- keys -------------------------------------------------------------------------

    def _caller(self, key_hash: str) -> Caller | None:
        row = self.db.key(key_hash)
        if row is None or row["revoked_at"] is not None:
            return None
        if row["expires_at"] is not None and int(row["expires_at"]) <= now():
            return None  # a session key past its time (session_key)
        return (
            Caller(
                key_hash=key_hash,
                account_id=row["account_id"],
                channel=row["channel"],
                hint=row["hint"],
                granted=int(row["granted"]),
                used=int(row["used"]),
                account_created_at=int(row["account_created_at"]),
                member=bool(row["account_unlimited"]) or row["id_hash"] in self.member_hashes,
                has_password=bool(row["password_hash"]),
                password_set_at=int(row["password_set_at"]) if row["password_set_at"] else None,
                via=row["via"] or "code",
                key_created_at=int(row["created_at"]),
                key_prefix=row["prefix"],
                hub_device_id=row["hub_device_id"] or "",
                hub_device_kind=row["hub_device_kind"] or "",
                invite_code=row["invite_code"] or "",
                invites=int(row["invites"] or 0),
                grant_uy=int(row["grant_uy"] or 0),
                contribute_bonus_at=int(row["contribute_bonus_at"]) if row["contribute_bonus_at"] else None,
                contribute=bool(row["contribute"]),
            )
            if not row["account_disabled"]
            else None
        )

    def authenticate(self, bearer: str | None) -> Caller:
        if not bearer or not bearer.startswith(KEY_PREFIX):
            raise CloudError(401, "bad_key", "Sign in again in the app")
        key_hash = _sha256(bearer)
        caller = self._caller(key_hash)
        if caller is None:
            # 0.1.40: a key of an account that no longer exists is told apart from one that
            # was merely revoked or reset — the device keeps the account's data on `bad_key`
            # (contract C12) and may delete it only on `account_deleted`
            if self.db.key_deleted(key_hash):
                raise CloudError(401, "account_deleted", "This account was deleted; sign in again to start a new one")
            raise CloudError(401, "bad_key", "This key is no longer valid; sign in again in the app")
        self.db.touch_key(caller.key_hash, caller.account_id)
        # 0.22: "active today" = any authenticated call; one row per account and UTC day
        self.db.daily_add("active", caller.account_id)
        return caller

    def key_live(self, key_hash: str) -> bool:
        """Whether a key still opens: not revoked, not past its time. What the hub asks after
        a sign-out to find the sockets whose key just stopped working."""
        return self._caller(key_hash) is not None

    def sign_out(self, caller: Caller) -> None:
        self.db.revoke_key(caller.key_hash)
        self.db.add_event(caller.account_id, "sign_out")

    def sign_out_all(self, caller: Caller, keep_current: bool = True) -> int:
        """Every other device (or every device) signed out at once — what to do
        after losing a phone."""
        n = self.db.revoke_all_keys(caller.account_id, keep_hash=caller.key_hash if keep_current else None)
        self.db.add_event(caller.account_id, "sign_out.all", str(n))
        return n

    def revoke_session(self, caller: Caller, prefix: str) -> None:
        if not self.db.revoke_key_by_prefix(caller.account_id, prefix[:10]):
            raise CloudError(404, "no_session", "No such sign-in")
        self.db.add_event(caller.account_id, "sign_out", prefix[:10])

    def sessions(self, caller: Caller) -> list[dict]:
        """The live sign-ins of this account — one per device that has a key —
        with the one making the request marked."""
        out = []
        for k in self.db.keys_for(caller.account_id, live_only=True):
            out.append(
                {
                    "prefix": k["prefix"],
                    "device": k["device"],
                    "via": k["via"] or "code",
                    "created_at": int(k["created_at"]),
                    "last_used_at": int(k["last_used_at"]) if k["last_used_at"] else None,
                    "expires_at": int(k["expires_at"]) if k["expires_at"] else None,
                    "current": k["key_hash"] == caller.key_hash,
                }
            )
        out.sort(key=lambda s: (not s["current"], -(s["last_used_at"] or s["created_at"])))
        return out

    def events(self, caller: Caller, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.db.events_for(caller.account_id, max(1, min(limit, 200)))]

    def delete_account(self, caller: Caller) -> None:
        """The person's own request: every key stops working and nothing about them stays.
        The one line left is written across accounts (`account.deleted`, the id's first
        eight characters), which the statistics count as a deletion; it names nobody."""
        subject = self.subject_of(caller.account_id)
        self.purge_record(caller.account_id)
        self.db.delete_account(caller.account_id)
        self.db.add_deletion(subject, "account")
        self.db.add_event("", "account.deleted", f"{caller.account_id[:8]} by the person")

    def usage(self, account_id: str, day_start: int) -> dict:
        """The breakdown behind the totals: by kind (chat, pictures, clips,
        calls) today and overall, and by model overall."""

        def rows(rs) -> list[dict]:
            out = []
            for r in rs:
                d = dict(r)
                d["cost_cny"] = self.s.uy_to_cny(int(d.pop("cost_uy", 0) or 0))
                for k in ("requests", "prompt_tokens", "completion_tokens", "charged"):
                    d[k] = int(d.get(k) or 0)
                out.append(d)
            return out

        return {
            "today": {"by_kind": rows(self.db.usage_by_kind(day_start, account_id))},
            "total": {
                "by_kind": rows(self.db.usage_by_kind(0, account_id)),
                "by_model": rows(self.db.usage_by_model(0, account_id)),
            },
            "kinds": list(USAGE_KINDS),
        }

    # -- the allowance (0.5) ----------------------------------------------------------------
    #
    # One pool for the account's lifetime: `grant_uy` on the account, what was spent is the
    # ledger's sum. Members (the operator's list, or flagged) have no limit; so has everyone
    # when ALLOWANCE_CNY is 0.

    def limited(self, caller: Caller) -> bool:
        return not caller.member and self.s.allowance_cny > 0

    def allowance(self, caller: Caller, spent_uy: int | None = None) -> dict:
        """The numbers behind every allowance view: spent, the pool, what is left, and
        whether it is time for the 80 % heads-up."""
        if spent_uy is None:
            spent_uy = self.db.spent_since(caller.account_id, 0)
        limited = self.limited(caller)
        grant = caller.grant_uy if limited else 0
        left = max(0, grant - spent_uy) if limited else None
        return {
            "limited": limited,
            "spent_uy": spent_uy,
            "grant_uy": grant,
            "left_uy": left,
            "warn": bool(limited and grant > 0 and spent_uy * 5 >= grant * 4),
        }

    # -- where the person is, and the ways on when the allowance is out (0.17) ----------------

    def mainland_phone(self, caller: Caller) -> bool:
        """Whether the account was opened with a mainland China phone number."""
        if caller.channel != "phone":
            return False
        row = self.db.account(caller.account_id)
        value = self.crypto.decrypt(caller.account_id, (row["identifier_enc"] if row else "") or "")
        if value:
            return value.startswith("+86")
        # an account from before the number was kept: the hint of a mainland number has no "+"
        return not caller.hint.startswith("+")

    def region(self, caller: Caller, place: Place | None = None) -> str:
        """`cn` for a mainland phone account or a mainland address, `intl` for an address
        placed elsewhere, `unknown` otherwise (REGIONS)."""
        if self.mainland_phone(caller):
            return "cn"
        return region_of_place(place)

    def ways_on(self, caller: Caller, region: str) -> list[dict]:
        """Where to go when the allowance is out, in the order the apps should show them:
        the mainland to Bailian first, everyone else to OpenRouter first (Bailian only signs
        up mainland accounts), the invitation last. Each has an `id` the apps have copy for,
        a `url`, and the figures that belong to it. Since 0.21 the two key ways also carry
        the catalogue's facts (`name`, `key_url`, `covers`, `auth`), and the fuller list —
        every provider for the region, the plans an app can sign in with — is `guidance`
        (contract C11; providers.py) next to this list, so a client from before keeps its
        two rows and a new one draws the whole card."""
        bailian = {"id": "bailian", "url": self.s.own_key_docs, "mainland_only": True, **self._way_facts("bailian")}
        openrouter = {"id": "openrouter", "url": self.s.openrouter_url, "mainland_only": False, **self._way_facts("openrouter")}
        invite = {
            "id": "invite",
            "url": (self.s.invite_url + self.invite_code_for(caller)) if self.s.invite_url else "",
            "bonus_cny": self.s.invite_bonus_cny,
        }
        keys = [bailian, openrouter] if region == "cn" else [openrouter, bailian]
        return [*keys, invite]

    @staticmethod
    def _way_facts(pid: str) -> dict:
        """The catalogue's facts for one of the two 0.17 ways: additive fields only."""
        p = catalogue_provider(pid)
        if p is None:
            return {}
        return {
            "name": p["name"],
            "name_zh": p["name_zh"],
            "key_url": p["key_url"],
            "covers": list(p["capabilities"]),
            "auth": list(p["auth"]),
        }

    def guidance(self, region: str) -> dict:
        """The own-key guidance for this person (0.21, contract C11): the providers for the
        region in order with what each covers, the plans an app can sign in with, the
        local servers, the guide's URL and the ChatGPT caveat."""
        return guidance(region, self.s.own_key_docs)

    def _exhausted(self, caller: Caller, a: dict, region: str = "unknown") -> CloudError:
        grant = f"¥{self.s.uy_to_cny(a['grant_uy']):g}"
        bonus = f"+¥{self.s.invite_bonus_cny:g} for each of you"
        key = exhausted_key_line(region)
        message = (
            f"Your free allowance ({grant}) is used up. Three ways on: {key}, or invite a friend ({bonus}). "
            "Your sign-in and your devices keep working either way."
        )
        return CloudError(
            429,
            "allowance_exhausted",
            message,
            extra={
                "left": self.s.uy_to_cny(a["left_uy"] or 0),
                "grant": self.s.uy_to_cny(a["grant_uy"]),
                "region": region,
                "ways": self.ways_on(caller, region),
                # 0.21: every provider for the region with what each covers, the plans an
                # app can sign in with (contract C11)
                "guidance": self.guidance(region),
                "invite_url": (self.s.invite_url + self.invite_code_for(caller)) if self.s.invite_url else "",
                "invite_bonus_cny": self.s.invite_bonus_cny,
                "invitee_bonus_cny": self.s.invite_bonus_cny,
                # 0.5 names, kept for the apps of the time: there is no co-creation bonus any more
                "contribute_bonus_available": False,
                "contribute_bonus_cny": 0,
                "own_key_docs": self.s.own_key_docs,
                "openrouter_url": self.s.openrouter_url,
            },
        )

    def _paused_allowance(self, caller: Caller, a: dict, region: str = "unknown") -> CloudError:
        """0.22: the *Free allowance* switch is off. Built on `_exhausted` so the extra keys
        (ways, guidance, invite link) are the same ones; only the words and two flags differ."""
        err = self._exhausted(caller, a, region)
        key = exhausted_key_line(region)
        err.message = (
            f"The free allowance is paused on this relay for now, so the shared models are not answering. "
            f"To keep going: {key}. Your sign-in, your devices and anything you have left stay as they are."
        )
        err.extra = {**err.extra, "paused": True, "reason": "allowance_paused"}
        return err

    def me(self, caller: Caller, place: Place | None = None) -> dict:
        t = now()
        day_start = self.s.day_start(t)
        spent_today_uy = self.db.spent_since(caller.account_id, day_start)
        spent_uy = self.db.spent_since(caller.account_id, 0)
        a = self.allowance(caller, spent_uy)
        grant_cny = self.s.uy_to_cny(a["grant_uy"])
        left_cny = None if a["left_uy"] is None else self.s.uy_to_cny(a["left_uy"])
        region = self.region(caller, place)
        return {
            # 0.17: where the person seems to be — the apps order the "ways on" by it
            # (REGIONS: cn | intl | unknown) when the allowance runs low or out
            "region": region,
            # 0.22: the operator's switches that are off right now, by name — an app may say
            # so on the account page before a request is refused
            "paused": [k for k, v in self.controls.paused().items() if v],
            "account": {
                # an opaque id (not the identifier): what nanoMuse Web keys a person's kept
                # Muse to, so a sign-in from another browser lands in the same one
                "id": caller.account_id,
                "channel": caller.channel,
                "hint": caller.hint,
                "created_at": caller.account_created_at,
                "member": caller.member,
                # may name any model of the provider's for its kind (any_model_members)
                "any_model": self.any_model(caller),
                "has_password": caller.has_password,
                "password_set_at": caller.password_set_at,
                "sessions": len(self.db.keys_for(caller.account_id, live_only=True)),
                "signed_in_via": caller.via,
            },
            "usage": self.usage(caller.account_id, day_start),
            "tokens": {
                # `unlimited` first: when it is true the app shows 「不限」 and
                # ignores granted/remaining (kept so older builds still parse).
                "unlimited": self.s.unlimited,
                "granted": caller.granted,
                "used": caller.used,
                "remaining": caller.remaining,
                "used_today": self.db.used_since(caller.account_id, day_start),
                "daily_cap": self.s.daily_cap_tokens,
            },
            # Money, as the provider bills the operator: what the account has spent in all
            # against its pool (0 = no limit, which is what members get), what is left, and
            # the rate the apps use to show dollars next to yuan. `warn` turns on at 80 %.
            "spend": {
                "currency": "CNY",
                "total": self.s.uy_to_cny(spent_uy),
                "grant": grant_cny,
                "left": left_cny,
                "unlimited": not a["limited"],
                "warn": a["warn"],
                "usd_cny": self.s.usd_cny,
                "total_usd": self.s.cny_to_usd(self.s.uy_to_cny(spent_uy)),
                "grant_usd": self.s.cny_to_usd(grant_cny),
                "left_usd": None if left_cny is None else self.s.cny_to_usd(left_cny),
                "today": self.s.uy_to_cny(spent_today_uy),
                "today_usd": self.s.cny_to_usd(self.s.uy_to_cny(spent_today_uy)),
                # how the pool grows, for the account page
                "allowance_cny": self.s.allowance_cny,
                "invite_bonus_cny": self.s.invite_bonus_cny,
                "invitee_bonus_cny": self.s.invite_bonus_cny,
                # 0.5 names, kept for the apps of the time: there is no co-creation bonus any more
                "contribute_bonus_cny": 0,
                "contribute_bonus_available": False,
                "own_key_docs": self.s.own_key_docs,
                "openrouter_url": self.s.openrouter_url,
                # 0.17: the ways on, in the order for this person (region above) — what the
                # 80 % heads-up and the "used up" card list
                "ways": self.ways_on(caller, region),
                # 0.21: the whole own-key card — providers for the region with what each
                # covers, the plans an app can sign in with, the ChatGPT caveat (C11)
                "guidance": self.guidance(region),
                # 0.4 names, one more version: apps from before 0.5 draw a "today / cap" bar;
                # with the pool in `daily_cap` and the total in `today` that bar is the right
                # one, and with no `resets_at` they print no midnight.
                "daily_cap": grant_cny,
                "daily_cap_usd": self.s.cny_to_usd(grant_cny),
                "day_offset_h": self.s.day_offset_h,
                "resets_at": 0,
                "credit_left": 0,
                "left_today": left_cny,
            },
            "invite": self.invite_view(caller),
            "clips": self.clips_view(),
            # Data controls: the switch, what has been kept (counted even when the switch is
            # off now, so the person sees there is something to delete), the relay's default
            # for new accounts and what exactly a kept turn holds.
            "contribute": {
                "on": caller.contribute,
                "samples": self.db.sample_count(caller.account_id),
                "default_on": self.s.improve_default,
                "keeps": SAMPLE_KEEPS,
                "privacy_url": self.s.privacy_url,
                # 0.5 names: there is no bonus for the switch any more
                "bonus_cny": 0,
                "bonus_available": False,
                "bonus_at": caller.contribute_bonus_at,
                # 0.29: the record — every turn in full, whatever the switch says; the same
                # tap deletes both
                "record": self.record_view(caller),
            },
            "models": [m.to_public() for m in self.offered_models()],
            "base_url": self.s.public_base,
            "recent": [self._ledger_row(r) for r in self.db.recent_ledger(caller.account_id)],
            # 0.18: when the app may ask for a star (the same object as GET /v1/nudges), so a
            # signed-in client has today's policy without a second request
            "nudges": self.nudges(),
        }

    # -- 0.18: the nudges policy (when the apps ask for a star) ---------------------------------

    def nudges(self) -> dict:
        """The policy as served: what the operator stored, over the defaults."""
        row = self.db.settings_get(NUDGES_KEY)
        return nudges_merge(row[0] if row else None)

    def admin_nudges(self) -> dict:
        """For the page: the policy, whether it is the page's or the built-in one, and when
        it was last saved (``updated_at`` is null for the defaults)."""
        row = self.db.settings_get(NUDGES_KEY)
        return {
            "nudges": self.nudges(),
            "defaults": nudges_defaults(),
            "stored": row is not None,
            "updated_at": row[1] if row else None,
        }

    def admin_put_nudges(self, body: dict) -> dict:
        """The page saved a policy: checked (400 with a plain message when a value is not
        right), ``version`` bumped past the one in force so every client can tell the copies
        apart, kept across restarts, noted on the timeline. ``{"reset": true}`` removes the
        stored policy so the defaults are served again."""
        if body.get("reset") is True:
            self.db.settings_put(NUDGES_KEY, None)
            log.warning("nudges policy reset to the defaults from the page")
            self.db.add_event("", "nudges.changed", "reset to the defaults")
            return self.admin_nudges()
        try:
            policy = nudges_validate(body)
        except BadNudges as e:
            raise CloudError(400, "bad_request", str(e)) from e
        current = self.nudges()
        policy["version"] = int(current.get("version") or 0) + 1
        self.db.settings_put(NUDGES_KEY, policy)
        star = policy["star"]
        said = (
            f"v{policy['version']}: {'on' if star['enabled'] else 'off'}, tasks {star['moments']['tasks']}, "
            f"days {star['moments']['days_used']}, cooldown {star['cooldown_days']}d, max {star['max_asks']}"
        )
        texts = [name for name in ("text", "text_zh") if star.get(name)]
        if texts:
            said += ", card " + "/".join(texts)
        log.warning("nudges policy changed from the page: %s", said)
        self.db.add_event("", "nudges.changed", said[:200])
        return self.admin_nudges()

    def _ledger_row(self, r) -> dict:
        d = dict(r)
        d["cost_cny"] = self.s.uy_to_cny(int(d.pop("cost_uy", 0) or 0))
        extra = d.pop("extra", "") or ""
        if extra:
            try:
                d["detail"] = json.loads(extra)
            except ValueError:
                pass
        if "ua" in d:
            d["platform"] = platform_of(d.get("ua") or "")
        return d

    # -- budget -------------------------------------------------------------------------

    def any_model(self, caller: Caller | None) -> bool:
        """May this caller name any model of the provider's, not only the menu's?"""
        return bool(caller is not None and caller.member and self.s.any_model_members)

    def model_for(self, model_id: str, kind: str, caller: Caller | None = None) -> ModelSpec:
        """The model a request names, checked for `kind` (a chat model answers chat, an
        image model draws, a video model films — never across). The menu for everyone;
        for a member, with any_model_members on, any id shaped like one besides."""
        if kind in ("image", "video") and not self.s.media_enabled:
            noun = "pictures" if kind == "image" else "clips"
            raise CloudError(
                410,
                "hosted_media_retired",
                f"nanoMuse Cloud no longer generates {noun}. Add your own image or video "
                "provider and API key in Settings → Models, then try again.",
                {"kind": kind, "action": "configure_own_provider"},
            )
        m = self.s.model(model_id)
        if m is not None and m.kind == kind:
            return m
        if m is None and self.any_model(caller):
            unlisted = self.s.unlisted_model(model_id, kind)
            if unlisted is not None:
                return unlisted
        offered = ", ".join(x.id for x in self.s.models if x.kind == kind)
        if m is not None:
            raise CloudError(404, "model_not_offered", f"{model_id!r} is a {m.kind} model, not a {kind} one; choose one of: {offered}")
        more = ", or any model of the provider's by its id" if self.any_model(caller) else ""
        raise CloudError(404, "model_not_offered", f"nanoMuse Cloud does not offer {model_id!r}; choose one of: {offered}{more}")

    def offered_models(self) -> tuple[ModelSpec, ...]:
        """The configured menu after operator feature switches are applied."""
        return self.s.models if self.s.media_enabled else tuple(m for m in self.s.models if m.kind == "chat")

    def models_for(self, caller: Caller) -> dict:
        """The menu, and whether this account may name a model beyond it."""
        return {
            "object": "list",
            "data": [m.to_public() for m in self.offered_models()],
            "nanomuse": {"any_model": self.any_model(caller)},
        }

    def check_budget(
        self,
        caller: Caller,
        minimum: int = 1,
        cost_uy: int = 0,
        request_id: str | None = None,
        hold_uy: int | None = None,
        place: Place | None = None,
    ) -> None:
        """Each limit is off when its setting is 0; the per-minute one guards the
        operator's bill against a runaway loop even on an unlimited relay.
        `cost_uy` is what the request is known to cost up front (a picture, a
        clip) so it is refused before the money is spent rather than after. With
        `request_id` the request is also *reserved* until :meth:`settle`: it counts
        as one of the account's in-flight requests (at most MAX_IN_FLIGHT) and
        `hold_uy` (its price, or a chat's typical turn) is held against the
        allowance — so requests started together cannot each pass this check and
        together overshoot it. `place` is where the request came from (geo.py), for
        the refusal's "ways on" when the allowance is out."""
        try:
            self._check_budget(caller, minimum, cost_uy, place)
        except CloudError as e:
            if e.code in ("out_of_tokens", "daily_cap", "allowance_exhausted", "too_many_in_flight"):
                self.db.add_event(caller.account_id, "budget.refused", e.code)
            raise
        if request_id is not None:
            self.in_flight.reserve(caller.account_id, request_id, cost_uy if hold_uy is None else hold_uy)

    def settle(self, caller: Caller, request_id: str) -> None:
        """The request is over (charged, failed or dropped): its reservation goes."""
        self.in_flight.settle(caller.account_id, request_id)

    def _check_budget(self, caller: Caller, minimum: int, cost_uy: int, place: Place | None = None) -> None:
        if not self.s.unlimited and caller.remaining < minimum:
            raise CloudError(
                402,
                "out_of_tokens",
                "Your nanoMuse Cloud grant is used up. Add your own model key under Settings → Providers to keep going.",
            )
        t = now()
        if self.in_flight.full(caller.account_id):
            raise CloudError(
                429,
                "too_many_in_flight",
                f"{self.in_flight.limit} requests of yours are already under way; wait for one to finish",
                {"retry_after": 2},
            )
        if self.s.per_minute_requests > 0 and self.db.requests_since(caller.account_id, t - 60) >= self.s.per_minute_requests:
            raise CloudError(429, "rate_limited", "Too many requests; slow down a little")
        if self.s.daily_cap_tokens > 0 and self.db.used_since(caller.account_id, self.s.day_start(t)) >= self.s.daily_cap_tokens:
            raise CloudError(429, "daily_cap", "Today's share of the grant is used up; it resets at midnight")
        if self.limited(caller):
            a = self.allowance(caller)
            if not self.controls.on("free_allowance"):
                # 0.22: the operator paused the free allowance. The same shape as "used up"
                # (code `allowance_exhausted`, the ways on, the invite link) so every app of
                # today shows its usual screen; `paused: true` and `reason` tell a newer one
                # the difference, and the message says it in words.
                raise self._paused_allowance(caller, a, self.region(caller, place))
            # the one pool: what the ledger has, plus what the requests under way and the
            # clips still being made are expected to cost. A chat (priced after the fact)
            # starts while anything is left beyond that; a picture or a clip only when its
            # known price fits on top of it.
            spent, grant = a["spent_uy"], a["grant_uy"]
            held = self.in_flight.reserved(caller.account_id) + self.db.pending_video_cost(caller.account_id)
            if spent + held >= grant or (cost_uy > 0 and spent + held + cost_uy > grant):
                raise self._exhausted(caller, a, self.region(caller, place))

    def chat_reserve_uy(self, model: ModelSpec) -> int:
        """What a chat on `model` is held at while it runs."""
        return model.chat_cost_uy(CHAT_RESERVE_PROMPT_TOKENS, CHAT_RESERVE_COMPLETION_TOKENS)

    def charge_chat(
        self,
        caller: Caller,
        model: ModelSpec,
        prompt_tokens: int,
        completion_tokens: int,
        request_id: str,
        cached_tokens: int = 0,
        at: int | None = None,
    ) -> int:
        """One chat turn in the ledger: the tokens as the provider counted them, the money at
        the model's price in force when the reply came in (`at`, now by default) — the
        cached part of the prompt at its cached rate, the idle hours at the idle price. The
        ledger line's `extra` says when either applied, so a statement can be checked."""
        at = self.clock() if at is None else at
        charged = math.ceil(prompt_tokens * model.in_mult + completion_tokens * model.out_mult)
        cost = model.chat_cost_uy(prompt_tokens, completion_tokens, cached_tokens, at)
        detail: dict[str, Any] = {}
        if cached_tokens > 0:
            detail["cached_tokens"] = min(max(0, cached_tokens), max(0, prompt_tokens))
        if model.idle_at(at):
            detail["idle"] = True
        self.db.charge(
            caller.account_id,
            "chat",
            model.id,
            prompt_tokens,
            completion_tokens,
            charged,
            request_id,
            cost_uy=cost,
            extra=json.dumps(detail) if detail else "",
        )
        self.settle_invite(caller.account_id)
        return charged

    def charge_image(self, caller: Caller, model: ModelSpec, n: int, request_id: str, size: str | None = None, inputs: int = 0) -> int:
        """`n` pictures out at the tier `size` falls in; `inputs` pictures sent in (an edit)."""
        charged = model.per_image * max(1, n)
        cost = model.image_cost_uy(size, inputs) * max(1, n)
        self.db.charge(caller.account_id, "image", model.id, 0, 0, charged, request_id, cost_uy=cost)
        self.settle_invite(caller.account_id)
        return charged

    def settle_video_task(self, task: Any, status: str | None) -> int | None:
        """The provider's word on a clip, from the app's poll or from the relay's own check
        (0.24). One accepted task = one clip (`per_clip`), the money priced from the seconds
        asked for when the task was submitted. The row remembers the status, and the first SUCCEEDED charges the clip at the
        price fixed when it was submitted. Idempotent: `mark_video_charged` flips once, so a
        poll after the relay settled a task (or the other way round) charges nothing more.
        Returns what was charged (micro-yuan), 0 when a SUCCEEDED task's model is gone from
        the menu, None when nothing was charged."""
        task_id = str(task["task_id"])
        if status and status != task["status"]:
            self.db.set_video_status(task_id, str(status))
        if status != "SUCCEEDED" or not self.db.mark_video_charged(task_id):
            return None
        model_id = str(task["model"])
        spec = self.s.model(model_id)
        if spec is None or spec.kind != "video":
            spec = self.s.unlisted_model(model_id, "video")  # a member's own pick
        if spec is None:
            return 0  # a model gone from the menu since the task was submitted
        account_id = str(task["account_id"])
        self.db.charge(account_id, "video", spec.id, 0, 0, spec.per_clip, task_id[:16], cost_uy=int(task["cost_uy"] or 0))
        self.settle_invite(account_id)
        return spec.per_clip

    def note(self, account_id: str, kind: str, detail: str = "") -> None:
        """An event on the account's timeline (never message content)."""
        self.db.add_event(account_id, kind, detail)

    # -- data controls: "Help improve nanoMuse's AI models" ----------------------------------
    #
    # With the switch on, each chat request's conversation and the model's reply are kept
    # for the community's own model — nothing else changes, and the person can turn it off
    # and delete what was kept at any time (Settings → Data controls on every app). What a
    # kept turn holds is exactly SAMPLE_KEEPS below; keep_sample enforces it. Never the
    # person's identity: samples carry the account id only, and are exported without it.
    # The default for a new account is the relay's IMPROVE_DEFAULT (config.py).

    SAMPLE_MAX_CHARS = 200_000

    # -- the profile: the agent's name and look, the same on every device ----------------

    PROFILE_MOODS = ("idle", "working", "waiting", "happy", "error")
    PROFILE_AVATARS = ("dragon", "emoji", "face")
    # one still, and the five together, as stored bytes (512 px WebP stills run 20–60 KB)
    PROFILE_STILL_BYTES = 200 * 1024
    PROFILE_FACE_BYTES = 800 * 1024
    # 0.17: the connectors each device holds — which service it connected and how, so another
    # device can say "connected on your Mac — sign in here to use it here". The credential
    # never leaves the device: an entry carrying a key named like one is refused outright.
    CONNECTOR_AUTHS = ("oauth", "key", "open")
    CONNECTORS_MAX = 64
    _CONNECTOR_SECRET_KEY = re.compile(r"token|secret|key|authorization|password", re.IGNORECASE)
    _CONNECTOR_LIMITS = {"id": 64, "label": 80, "url": 256, "device": 80, "device_id": 80, "at": 40}

    def profile(self, caller: Caller, with_face: bool = True) -> dict:
        """What the account's devices wear: ``rev`` 0 and empty fields until one of them writes."""
        row = self.db.profile(caller.account_id)
        if row is None:
            return {
                "rev": 0,
                "updated_at": None,
                "device": "",
                "name": "",
                "avatar": "",
                "emoji": "",
                "color": "",
                "style": "",
                "description": "",
                "face": None,
                "clips": None,
                "connectors": [],
            }
        body = json.loads(row["body"] or "{}")
        out = {
            "rev": int(row["rev"]),
            "updated_at": int(row["updated_at"]),
            "device": str(row["device"]),
            "name": str(body.get("name") or ""),
            "avatar": str(body.get("avatar") or ""),
            "emoji": str(body.get("emoji") or ""),
            "color": str(body.get("color") or ""),
            "style": str(body.get("style") or ""),
            "description": str(body.get("description") or ""),
            "has_face": bool(row["face"]),
            # the hash of the idle still: a device that already wears these pictures keeps
            # its own copy (and the clips it made) instead of downloading them again
            "face_id": self._face_id(row["face"]),
            # 0.29: the face's clips as {mood: {sha256, mime, bytes}}, files at GET /v1/blobs/{sha256}
            "clips": body.get("clips") if isinstance(body.get("clips"), dict) and body.get("clips") else None,
            # every device's connectors together (0.17); the credentials stay on each device
            "connectors": self._load_connectors(row["connectors"]),
        }
        if with_face:
            out["face"] = json.loads(row["face"]) if row["face"] else None
        return out

    @staticmethod
    def _load_connectors(text: str | None) -> list[dict]:
        try:
            value = json.loads(text) if text else []
        except ValueError:
            return []
        return [c for c in value if isinstance(c, dict)] if isinstance(value, list) else []

    def _check_connector(self, raw: object, writer: str, at: str) -> dict:
        """One entry as a device sends it, checked and trimmed to the shape every client
        reads (contract C3). 400 `no_secrets_in_profile` the moment a key is named like a
        credential — the relay will not hold one even by accident."""
        if not isinstance(raw, dict):
            raise CloudError(400, "bad_request", "connectors is a list of objects")
        self._refuse_secrets(raw)
        out: dict = {}
        for field_name, cap in self._CONNECTOR_LIMITS.items():
            value = raw.get(field_name)
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise CloudError(400, "bad_request", f"connectors[].{field_name} is a string")
            value = value.strip()
            if len(value) > cap:
                raise CloudError(400, "bad_request", f"connectors[].{field_name} is at most {cap} characters")
            out[field_name] = value
        if not out["id"]:
            raise CloudError(400, "bad_request", "connectors[].id is required")
        if not out["label"]:
            out["label"] = out["id"]
        if out["url"]:
            if not re.match(r"^[a-z][a-z0-9+.-]*:", out["url"], re.IGNORECASE):
                raise CloudError(400, "bad_request", "connectors[].url is a URL (scheme:...)")
            # the public form only: a query (`?key=`), a user info (`user:secret@`) or a
            # fragment is where a credential rides, and the relay holds none of them
            parts = urlsplit(out["url"])
            if parts.query or parts.fragment or parts.username or parts.password:
                raise CloudError(
                    400,
                    "no_secrets_in_profile",
                    "connectors[].url carries a query, a fragment or a user info; send scheme://host/path only",
                )
        auth = str(raw.get("auth") or "").strip().lower()
        if auth not in self.CONNECTOR_AUTHS:
            raise CloudError(400, "bad_request", "connectors[].auth is oauth, key or open")
        out["auth"] = auth
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise CloudError(400, "bad_request", "connectors[].enabled is true or false")
        out["enabled"] = enabled
        # the writer's device: an entry without one is the writer's; one naming another
        # device is refused — a device publishes what *it* holds, never what another does
        if not out["device_id"]:
            out["device_id"] = writer
        elif out["device_id"] != writer:
            raise CloudError(400, "bad_request", "connectors[].device_id names another device; a device writes only its own")
        if not out["device"]:
            out["device"] = writer
        out["at"] = self._check_iso(out["at"]) or at
        return out

    def _refuse_secrets(self, obj: object) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if self._CONNECTOR_SECRET_KEY.search(str(k)):
                    raise CloudError(400, "no_secrets_in_profile", f"connectors carry no credentials; drop {str(k)[:40]!r}")
                self._refuse_secrets(v)
        elif isinstance(obj, list):
            for v in obj:
                self._refuse_secrets(v)

    @staticmethod
    def _check_iso(value: str) -> str:
        """An ISO-8601 moment as the device wrote it, or "" when it is not one."""
        if not value:
            return ""
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise CloudError(400, "bad_request", "connectors[].at is an ISO-8601 time") from None
        return value

    def merge_connectors(self, stored: list[dict], writer: str, mine: list[dict]) -> list[dict]:
        """The other devices' entries stay as they were; the writer's are replaced by what it
        sent (so an entry it no longer holds goes). Within the writer's list the last entry
        with an id wins. At most CONNECTORS_MAX in all."""
        others = [c for c in stored if str(c.get("device_id") or "") != writer]
        by_id: dict[str, dict] = {}
        for c in mine:
            by_id[c["id"]] = c
        merged = others + list(by_id.values())
        if len(merged) > self.CONNECTORS_MAX:
            raise CloudError(
                400, "too_many_connectors", f"At most {self.CONNECTORS_MAX} connectors on an account; this write would make {len(merged)}"
            )
        return merged

    @staticmethod
    def _face_id(face_json: str | None) -> str:
        if not face_json:
            return ""
        try:
            idle = json.loads(face_json).get("idle") or ""
            return hashlib.sha1(base64.b64decode(idle)).hexdigest()[:12] if idle else ""
        except (ValueError, binascii.Error, AttributeError):
            return ""

    def put_profile(self, caller: Caller, device: str, data: dict) -> dict:
        """Last writer wins for the look. Only the look is kept — never a key, a message or a
        setting that could reach the network. ``face`` absent keeps the stored pictures, null
        clears them, a {mood: base64 WebP} map replaces them (``avatar`` "face" needs one or
        the other). ``connectors`` (0.17) is merged by device: the writer's entries are
        replaced by what it sent, the other devices' stay. A write that carries only
        ``connectors`` leaves the look as it is."""
        device = device[:80]
        row = self.db.profile(caller.account_id)
        connectors: str | None = None
        if "connectors" in data:
            raw = data["connectors"]
            if raw is None:
                raw = []
            if not isinstance(raw, list):
                raise CloudError(400, "bad_request", "connectors is a list")
            if not device:
                raise CloudError(400, "bad_request", "connectors need the writing device's id in `device`")
            stamp = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
            mine = [self._check_connector(c, device, stamp) for c in raw]
            stored = self._load_connectors(row["connectors"]) if row is not None else []
            connectors = json.dumps(self.merge_connectors(stored, device, mine), ensure_ascii=False)
        look_keys = ("name", "avatar", "emoji", "color", "style", "description", "face")
        if connectors is not None and not any(k in data for k in look_keys):
            # connectors alone: the look stays whatever it was (possibly still empty)
            rev = self.db.put_profile(caller.account_id, device, None, None, connectors)
            self.note(caller.account_id, "profile.connectors", str(len(json.loads(connectors))))
            return {"rev": rev, "device": device}
        # 0.25: a write names only what changed on the device. A field that is absent (or
        # blank, for the name) keeps what is stored, so a phone that renamed the muse before
        # it ever pulled the account's face sends the name alone and the face stays; a 1.0.3
        # client that sends the whole look every time is read exactly as before.
        stored: dict = json.loads(row["body"] or "{}") if row is not None else {}

        def field(key: str, default: str = "") -> str:
            if key in data and data[key] is not None:
                return str(data[key]).strip()
            return str(stored.get(key) or default)

        name = field("name") or str(stored.get("name") or "")
        avatar = field("avatar", "dragon")
        emoji = field("emoji")
        color = field("color")
        style = field("style")
        description = field("description")
        if len(name) > 60:
            raise CloudError(400, "bad_request", "name is at most 60 characters")
        if avatar not in self.PROFILE_AVATARS:
            raise CloudError(400, "bad_request", "avatar is dragon, emoji or face")
        if len(emoji) > 16 or len(style) > 20 or len(description) > 200:
            raise CloudError(400, "bad_request", "emoji, style or description too long")
        if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise CloudError(400, "bad_request", "color is #rrggbb")
        face: str | None
        if "face" not in data:
            face = None
        elif data["face"] is None:
            face = ""
        else:
            face = self._check_face(data["face"])
        if avatar == "face" and not (face or (face is None and row is not None and row["face"])):
            raise CloudError(400, "bad_request", "a drawn face needs its pictures")
        if avatar != "face" and face is None and row is not None and row["face"]:
            # back to the dragon or an emoji without saying `face: null` (the Android app of
            # 1.0.3 and before): the pictures go with the look, so no device reads `has_face`
            # as a face still worn
            face = ""
        # 0.29: the clips a device made of the drawn face, as references to files it put up
        # (PUT /v1/blobs), so the other devices download them instead of rendering their
        # own. Absent keeps what is stored; null clears; they go with the face either way.
        clips: dict | None
        if "clips" in data:
            clips = self._check_clips(caller, data["clips"]) if data["clips"] is not None else None
        elif face:
            # new pictures without a word about clips: the stored clips were of the old
            # face and do not fit the new one (0.30; before, they stayed on)
            clips = None
        else:
            clips = stored.get("clips") if isinstance(stored.get("clips"), dict) else None
        if face == "" or avatar != "face":
            clips = None
        look = {"name": name, "avatar": avatar, "emoji": emoji, "color": color, "style": style, "description": description}
        if clips:
            look["clips"] = clips
        body = json.dumps(look, ensure_ascii=False)
        rev = self.db.put_profile(caller.account_id, device, body, face, connectors)
        self.db.set_blob_refs(caller.account_id, "profile", [c["sha256"] for c in (clips or {}).values()])
        self.note(caller.account_id, "profile.put", avatar)
        return {"rev": rev, "device": device}

    def _check_clips(self, caller: Caller, raw: object) -> dict:
        """``{mood: {sha256, mime, bytes}}`` — each a video the account put up itself."""
        if not isinstance(raw, dict):
            raise CloudError(400, "bad_request", "clips is a {mood: {sha256, mime, bytes}} map")
        out: dict[str, dict] = {}
        for mood, clip in raw.items():
            if mood not in self.PROFILE_MOODS:
                raise CloudError(400, "bad_request", f"clips has an unknown mood {str(mood)[:20]!r}")
            if not isinstance(clip, dict):
                raise CloudError(400, "bad_request", f"clips.{mood} is an object")
            sha = str(clip.get("sha256") or "").lower()
            if not is_sha256(sha):
                raise CloudError(400, "bad_request", f"clips.{mood}.sha256 is a hex SHA-256")
            if not self.db.blob_readable(caller.account_id, sha):
                raise CloudError(400, "unknown_blob", f"clips.{mood} names no file this account put up")
            row = self.db.blob(sha)
            mime = str(clip.get("mime") or (row["mime"] if row else "") or "")[:80]
            if not mime.startswith("video/"):
                raise CloudError(400, "bad_request", f"clips.{mood} is not a video")
            out[mood] = {"sha256": sha, "mime": mime, "bytes": int(row["bytes"]) if row else int(clip.get("bytes") or 0)}
        return out

    def _check_face(self, face: object) -> str:
        if not isinstance(face, dict) or not face:
            raise CloudError(400, "bad_request", "face is a {mood: base64} map")
        kept: dict[str, str] = {}
        total = 0
        for mood, pic in face.items():
            if mood not in self.PROFILE_MOODS or not isinstance(pic, str):
                raise CloudError(400, "bad_request", f"face has an unknown mood {mood!r}")
            try:
                raw = base64.b64decode(pic, validate=True)
            except (ValueError, binascii.Error):
                raise CloudError(400, "bad_request", f"face.{mood} is not base64") from None
            if not (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP") and not raw.startswith(b"\x89PNG"):
                raise CloudError(400, "bad_request", f"face.{mood} is not WebP or PNG")
            if len(raw) > self.PROFILE_STILL_BYTES:
                raise CloudError(413, "too_large", f"face.{mood} is over {self.PROFILE_STILL_BYTES // 1024} KB")
            total += len(raw)
            kept[mood] = pic
        if "idle" not in kept:
            raise CloudError(400, "bad_request", "face needs at least the idle still")
        if total > self.PROFILE_FACE_BYTES:
            raise CloudError(413, "too_large", f"the face is over {self.PROFILE_FACE_BYTES // 1024} KB in all")
        return json.dumps(kept)

    def delete_profile(self, caller: Caller) -> None:
        self.db.delete_profile(caller.account_id)
        self.db.set_blob_refs(caller.account_id, "profile", [])
        self.note(caller.account_id, "profile.clear")

    def set_contribute(self, caller: Caller, on: bool) -> dict:
        """The switch under Data controls. Turning it off keeps what was kept until the person
        deletes it (delete_samples) — the count stays visible so they know there is something
        to delete. Nothing is credited for it either way (the 0.5 bonus is gone)."""
        if on != caller.contribute:
            self.db.set_contribute(caller.account_id, on)
            self.note(caller.account_id, "contribute.on" if on else "contribute.off")
        return {
            "on": on,
            "samples": self.db.sample_count(caller.account_id),
            "default_on": self.s.improve_default,
            "keeps": SAMPLE_KEEPS,
            "privacy_url": self.s.privacy_url,
            # 0.5 names, for the apps of the time
            "bonus_cny": 0,
            "bonus_granted": False,
            "bonus_available": False,
            "bonus_at": caller.contribute_bonus_at,
            # 0.30: the record's figures too, so an app that redraws the page from this answer
            # alone (the desktop does) keeps them
            "record": self.record_view(caller),
        }

    def delete_samples(self, caller: Caller) -> dict:
        """The one tap under Data controls: the training turns and, since 0.29, the record
        with them — every turn kept of this account and every file only it referenced."""
        n = self.db.delete_samples(caller.account_id)
        turns, files = self.purge_record(caller.account_id)
        # 0.31: the deletions ledger names the export's pseudonym for this account, so a
        # training set built from an earlier export drops its lines (docs/cloud.md "Deletions")
        self.db.add_deletion(self.subject_of(caller.account_id), "samples")
        self.note(caller.account_id, "contribute.deleted", f"{n} conversations, {turns} turns, {files} files")
        return {"deleted": n, "turns": turns, "files": files}

    def subject_of(self, account_id: str) -> str:
        """The pseudonym the exports carry for an account (provenance.subject_of under the
        relay's secret): the same in every export, so one person's lines group and can be
        dropped together; meaningless without the secret."""
        return provenance.subject_of(self.s.hmac_key.decode("utf-8", "replace"), account_id)

    # -- 0.29: the record — every turn in full, its pictures as files -------------------------

    RECORD_SOURCES = ("cloud", "own")
    #: an uploaded turn's `messages` and `response` together, as JSON characters
    TURN_MAX_CHARS = 2_000_000
    #: what a device may hand the relay as a file: pictures, audio and the avatar's clips
    BLOB_MIMES = ("image/", "audio/", "video/")

    def record_turn(
        self,
        caller: Caller,
        model: str,
        body: dict,
        message: dict,
        usage: Usage | None,
        *,
        request_id: str,
        meta: dict | None,
        status: str = "ok",
        device: str = "",
        conversation: str = "",
        source: str = "cloud",
        ts: int | None = None,
        provenance_: dict | None = None,
    ) -> str | None:
        """The turn as it happened, written after it is answered (api.py hands it to a thread:
        the pictures are decoded, hashed and written to the store there). ``body`` is the
        request as the relay sent it to the provider, less the relay's own fields (`user`,
        `stream_options`) and with the model named as the app knows it; ``message`` is the
        assistant's message, whole or put together from the stream. A no-op with
        RECORD_TURNS=0. Answers the turn's id. ``provenance_`` is who started the turn
        and where it sits (provenance.clean), kept in the row's own columns (0.31)."""
        if not self.s.record_turns:
            return None
        req = {k: v for k, v in body.items() if k not in ("user", "stream_options")}
        req["model"] = model
        media: list[dict] = []
        if isinstance(req.get("messages"), list):
            req["messages"], media = detach_media(req["messages"], self.media)
            # files the client put up beforehand and named by reference (an own-key turn):
            # counted with the turn and referenced by it like the ones taken out just now
            known = {m["sha256"] for m in media}
            for sha in sorted(media_refs(req["messages"]) - known):
                row = self.db.blob(sha)
                if row is not None:
                    media.append({"sha256": sha, "mime": str(row["mime"]), "bytes": int(row["bytes"])})
        meta = dict(meta or {})
        if media:
            meta["media"] = media
        response = {"message": message}
        if usage is not None:
            response["usage"] = {"prompt_tokens": usage.prompt, "completion_tokens": usage.completion, "cached_tokens": usage.cached}
        where = provenance.clean(provenance_ or {})
        if where["platform"]:
            meta["platform"] = where["platform"]
        row = {
            "id": request_id,
            "account_id": caller.account_id,
            "ts": ts or now(),
            "model": model[:120],
            "platform": platform_from(meta),
            "device": device[:80],
            "conversation": conversation[:80],
            "source": source if source in self.RECORD_SOURCES else "cloud",
            "status": status,
            "request": pack(req),
            "response": pack(response),
            "prompt_tokens": usage.prompt if usage else 0,
            "completion_tokens": usage.completion if usage else 0,
            "cached_tokens": min(usage.cached, usage.prompt) if usage else 0,
            "meta": json.dumps(meta, ensure_ascii=False),
            "run": where["run"],
            "turn_no": where["turn"],
            "step": where["step"],
            "trajectory": where["trajectory"],
            "trajectory_step": where["trajectory_step"],
            "script": provenance.script_of(provenance.last_user_text(req.get("messages"))),
            # 0.31: whether this call opened a turn or continued one (the key is looked up as
            # the row is written)
            "turn_start": provenance.turn_start(req.get("messages"), where["step"]),
        }
        self.db.add_turn(row, media)
        return request_id

    #: the fields of an uploaded turn that are about the turn, not part of the request
    OWN_TURN_FIELDS = ("response", "provider", "ts", "conversation", "id", "device", "status", "ended", *provenance.FIELDS)

    def add_own_turn(self, caller: Caller, data: dict, *, meta: dict, device: str, headers: dict | None = None) -> dict:
        """A turn a client ran on a key of its own (1.0.7 on), sent up afterwards in the same
        shape the relay keeps: ``model``, ``messages`` (pictures inline as data URLs, or as
        ``blob:sha256:`` references to files put up with PUT /v1/blobs first), ``response``
        (the assistant's message and, when known, the usage), and ``provider``, ``ts``,
        ``conversation``, ``id`` as the client has them; since 0.31 also ``run``, ``turn``,
        ``step``, ``trajectory``, ``trajectory_step`` and ``platform`` (provenance.py; the
        request's X-NanoMuse headers fill in what the body leaves out). 400 for a shape the
        relay cannot keep; a reference to a file the account never put up is refused the
        same way. With the account's switch on, the turn's training view is kept too, as
        for a turn the relay answered itself: a turn is a turn whichever key ran it."""
        if not self.s.record_turns:
            raise CloudError(404, "not_found", "This relay keeps no record of turns (RECORD_TURNS=0)")
        self._upload_allowed(caller)
        model = str(data.get("model") or "").strip()
        messages = data.get("messages")
        response = data.get("response")
        if not model or len(model) > 120:
            raise CloudError(400, "bad_request", "model is required (at most 120 characters)")
        if not isinstance(messages, list) or not messages or not all(isinstance(m, dict) for m in messages):
            raise CloudError(400, "bad_request", "messages is a non-empty list of message objects")
        if not isinstance(response, dict) or not isinstance(response.get("message"), dict):
            raise CloudError(400, "bad_request", "response is an object with the assistant's `message`")
        if len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(response, ensure_ascii=False)) > self.TURN_MAX_CHARS:
            raise CloudError(413, "too_large", f"a turn is at most {self.TURN_MAX_CHARS} characters of JSON")
        for sha in media_refs(messages) | media_refs(response):
            if not self.db.blob_readable(caller.account_id, sha):
                raise CloudError(400, "unknown_blob", f"{BLOB_PREFIX}{sha} names no file this account put up")
        self._room_for(caller, inline_media_bytes(messages))
        turn_id = str(data.get("id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", turn_id):
            turn_id = secrets.token_hex(8)
        turn_id = f"own-{caller.account_id[:8]}-{turn_id}"[:96]
        ts = data.get("ts")
        t = int(ts) if isinstance(ts, (int, float)) and 0 < ts < 4_102_444_800 else now()
        usage_in = response.get("usage") if isinstance(response.get("usage"), dict) else None
        usage: Usage | None = None
        if usage_in is not None:
            usage = Usage(
                max(0, int(usage_in.get("prompt_tokens") or 0)),
                max(0, int(usage_in.get("completion_tokens") or 0)),
                max(0, int(usage_in.get("cached_tokens") or 0)),
            )
        body = {k: v for k, v in data.items() if k not in self.OWN_TURN_FIELDS}
        provider = str(data.get("provider") or "")[:60]
        meta = {**meta, "provider": provider} if provider else dict(meta)
        where = provenance.from_body(data, headers or {})
        status = "partial" if data.get("status") == "partial" else "ok"
        # 0.30: why a partial turn ended short, in the client's word (`aborted`: the person
        # stopped it; `error`: the stream broke; `abandoned`: it never finished) — the
        # operator reads the figure, as for the relay's own turns (api.py: `ended`)
        ended = data.get("ended")
        if status == "partial" and isinstance(ended, str) and re.fullmatch(r"[a-z_]{1,32}", ended):
            meta["ended"] = ended
        message = {k: v for k, v in response["message"].items() if k != "usage"}
        conversation = str(data.get("conversation") or "")[:80]
        self.record_turn(
            caller,
            model,
            body,
            message,
            usage,
            request_id=turn_id,
            meta=meta,
            status=status,
            device=device,
            conversation=conversation,
            source="own",
            ts=t,
            provenance_=where,
        )
        if caller.contribute and status == "ok":
            sample_meta = {k: v for k, v in meta.items() if k in ("ua", "lang", "ip", "provider")}
            sample_meta.update(self.sample_provenance("own", turn_id, where, messages, conversation=conversation))
            self.keep_sample(
                caller,
                model,
                messages,
                provenance.text_of(message.get("content")),
                usage.prompt if usage else -1,
                usage.completion if usage else -1,
                sample_meta,
                message=message,
            )
        return {"id": turn_id, "ts": t}

    @staticmethod
    def sample_provenance(source: str, turn_id: str, where: dict, messages: Any, *, conversation: str = "") -> dict:
        """What a kept turn's meta says about where it came from (0.31): its source (the
        relay's model or the client's own key), the record's id for it, who started it and
        where it sits, and the script of what the person wrote. Only what was said is kept."""
        out: dict[str, Any] = {"source": source, "turn_id": turn_id}
        if conversation:
            out["conversation"] = conversation
        out.update(provenance.said(where))
        script = provenance.script_of(provenance.last_user_text(messages))
        if script:
            out["script"] = script
        return out

    # -- 0.31: what the apps report around a turn (docs/cloud.md "Client events") -------------

    EVENT_REQUESTS_PER_MINUTE = 60

    def add_client_events(self, caller: Caller, events: Any, *, platform: str, device: str) -> dict:
        """The events of one POST /v1/events: each cleaned to codes and numbers
        (provenance.clean_event), stamped with the account, the device and the platform,
        and tied to the record's turn when the app named it (an own-key turn's id is the
        app's, so it is normalised to the record's `own-<account>-<id>` form). One the
        relay will not keep is dropped and counted, not refused. Answers {kept, dropped}."""
        if not isinstance(events, list):
            raise CloudError(400, "bad_request", "events is a list of {kind, ts?, turn?, conversation?, data}")
        if len(events) > provenance.EVENTS_PER_REQUEST:
            raise CloudError(413, "too_large", f"at most {provenance.EVENTS_PER_REQUEST} events in one request; send the rest in another")
        if not self.event_pace.allow(caller.account_id):
            raise CloudError(
                429, "rate_limited", f"At most {self.EVENT_REQUESTS_PER_MINUTE} reports a minute from one account; send the rest later"
            )
        t = now()
        own = f"own-{caller.account_id[:8]}-"
        rows: list[dict[str, Any]] = []
        dropped = 0
        for e in events:
            c = provenance.clean_event(e)
            if c is None:
                dropped += 1
                continue
            turn_id = c["turn_id"]
            if turn_id and len(turn_id) <= 64 and not turn_id.startswith("own-") and isinstance(e, dict) and e.get("source") == "own":
                turn_id = (own + turn_id)[:96]
            rows.append(
                {
                    "account_id": caller.account_id,
                    "ts": c["ts"] or t,
                    "device": device[:80],
                    "platform": platform[:16],
                    "kind": c["kind"],
                    "turn_id": turn_id,
                    "conversation": c["conversation"],
                    "data": json.dumps(c["data"], ensure_ascii=False, sort_keys=True),
                }
            )
        kept = self.db.add_client_events(rows)
        return {"kept": kept, "dropped": dropped}

    def _event_view(self, r: sqlite3.Row, *, subject: bool = False) -> dict:
        try:
            data = json.loads(r["data"]) if r["data"] else {}
        except ValueError:
            data = {}
        d: dict[str, Any] = {
            "id": int(r["id"]),
            "ts": int(r["ts"]),
            "device": r["device"],
            "platform": r["platform"],
            "kind": r["kind"],
            "turn_id": r["turn_id"],
            "conversation": r["conversation"],
            "data": data,
        }
        if subject:
            d["subject"] = self.subject_of(str(r["account_id"]))
        else:
            d["account_id"] = r["account_id"]
        return d

    def admin_client_events(
        self, account_id: str | None = None, kinds: tuple[str, ...] | None = None, since: int = 0, limit: int = 200, before: int = 0
    ) -> list[dict]:
        return [self._event_view(r) for r in self.db.client_events(account_id, list(kinds or ()), since, limit, before)]

    def export_client_events(self, since: int = 0, account_id: str | None = None):
        """The apps' reports as JSON lines with the `subject` pseudonym, oldest first within
        each page read newest first — a reader sorts by id if the order matters."""
        before = 0
        while True:
            rows = self.db.client_events(account_id, None, since, 1000, before)
            if not rows:
                return
            for r in rows:
                yield json.dumps(self._event_view(r, subject=True), ensure_ascii=False) + "\n"
            before = int(rows[-1]["id"])

    #: the `data` keys whose values the summary counts, per kind — codes, never free text
    EVENT_FACETS = {
        "sentinel.decision": ("decision", "risk"),
        "approval.result": ("allow", "scope", "by"),
        "turn.stopped": ("reason",),
        "turn.feedback": ("vote", "reason"),
        "turn.ended": ("ended",),
        "hands.step": ("outcome",),
    }

    def client_events_summary(self, days: int = 30) -> dict:
        """Figures over ``days``: reports per day and kind, accounts reporting, and the
        split of each kind's codes (what the Sentinel decided, how approvals went, why
        replies were stopped, how the thumbs fell). Reads the rows of the period in pages;
        never a message, there is none to read."""
        t = now()
        off = self.s.day_offset_h * 3600
        since = self.s.day_start(t) - 86400 * max(0, days - 1)
        by_day: dict[int, dict[str, int]] = {}
        kinds: dict[str, int] = {}
        for r in self.db.client_events_summary(since, off):
            day = int(r["day"])
            by_day.setdefault(day, {})[str(r["kind"])] = int(r["n"])
            kinds[str(r["kind"])] = kinds.get(str(r["kind"]), 0) + int(r["n"])
        facets: dict[str, dict[str, dict[str, int]]] = {}
        before = 0
        for _ in range(200):  # at most 200k rows read for the split; enough for a month
            rows = self.db.client_events(None, list(self.EVENT_FACETS), since, 1000, before)
            if not rows:
                break
            for r in rows:
                try:
                    data = json.loads(r["data"]) if r["data"] else {}
                except ValueError:
                    continue
                for key in self.EVENT_FACETS.get(str(r["kind"]), ()):
                    if key in data and data[key] is not None:
                        bucket = facets.setdefault(str(r["kind"]), {}).setdefault(key, {})
                        v = str(data[key]).lower()[:32]
                        bucket[v] = bucket.get(v, 0) + 1
            before = int(rows[-1]["id"])
        return {
            "period": {"days": days, "since": since},
            "total": sum(kinds.values()),
            "accounts": int(self.db.client_events_accounts(since)),
            "kinds": kinds,
            "days": [{"day": since + i * 86400, **by_day.get(since + i * 86400, {})} for i in range(days)],
            "facets": facets,
        }

    def deletions_since(self, since: int = 0) -> list[dict]:
        return [{"subject": r["subject"], "ts": int(r["ts"]), "scope": r["scope"]} for r in self.db.deletions(since)]

    def put_blob(self, caller: Caller, data: bytes, mime: str) -> dict:
        """A file a device puts up for a turn or the avatar's clips: stored once by its
        hash, readable by this account from now on. Answers the hash, the size and whether
        the file was already here (a device need not send what another one did)."""
        if not self.s.record_turns:
            raise CloudError(404, "not_found", "This relay keeps no files (RECORD_TURNS=0)")
        self._upload_allowed(caller)
        mime = (mime or "").split(";")[0].strip().lower()[:80]
        if not any(mime.startswith(p) for p in self.BLOB_MIMES):
            raise CloudError(400, "bad_request", "a file is a picture, an audio clip or a video (Content-Type image/*, audio/*, video/*)")
        if not data:
            raise CloudError(400, "bad_request", "an empty file")
        if len(data) > self.s.blob_max_bytes:
            raise CloudError(413, "too_large", f"a file is at most {self.s.blob_max_bytes // (1024 * 1024)} MB")
        sha = hashlib.sha256(data).hexdigest()
        if not self.db.blob_readable(caller.account_id, sha):  # a file the account already holds costs it nothing more
            self._room_for(caller, len(data))
        sha, new = self.media.put(data)
        self.db.add_blob(sha, mime, len(data), caller.account_id, "upload")
        return {"sha256": sha, "bytes": len(data), "mime": mime, "known": not new}

    def _upload_allowed(self, caller: Caller) -> None:
        """One more upload from this account this minute (RECORD_UPLOADS_PER_MINUTE), or 429."""
        if not self.upload_pace.allow(caller.account_id):
            raise CloudError(
                429,
                "rate_limited",
                f"At most {self.s.record_uploads_per_minute} turns and files a minute go up from one account; send the rest later",
            )

    def _room_for(self, caller: Caller, more: int) -> None:
        """Room for ``more`` bytes of files: under the account's cap (MEDIA_ACCOUNT_MAX_MB)
        and under the store's (MEDIA_MAX_GB), both checked before anything is written. The
        store's cap is what the hourly trim keeps to; here it stops a flood from filling
        the disk in the hour between two trims."""
        if more <= 0:
            return
        cap = int(self.s.media_max_gb * 1024**3)
        if cap > 0 and self.db.blobs_bytes() + more > cap:
            raise CloudError(507, "store_full", "The relay's file store is full for now; the file was not taken")
        account_cap = self.s.media_account_max_mb * 1024 * 1024
        if account_cap > 0 and self.db.account_blob_bytes(caller.account_id) + more > account_cap:
            raise CloudError(
                413,
                "quota_exceeded",
                f"This account's files would pass {self.s.media_account_max_mb} MB on the relay; delete the record or send fewer pictures",
            )

    def blob_for(self, sha: str, caller: Caller | None = None) -> tuple[Path, str] | None:
        """The file's path and type — for the account that holds a reference to it, or for
        the operator (no caller). None when it is unknown, unreadable to this account, or
        trimmed from the store."""
        if not is_sha256(sha):
            return None
        row = self.db.blob(sha)
        if row is None or not self.media.has(sha):
            return None
        if caller is not None and not self.db.blob_readable(caller.account_id, sha):
            return None
        return self.media.path(sha), str(row["mime"] or "application/octet-stream")

    def _turn_view(self, r: sqlite3.Row, with_hint: bool = False) -> dict:
        meta = _load_meta(r["meta"])
        d = {
            "id": r["id"],
            "account_id": r["account_id"],
            "ts": int(r["ts"]),
            "model": r["model"],
            "platform": r["platform"] or platform_of(str(meta.get("ua") or "")),
            "device": r["device"],
            "conversation": r["conversation"],
            "source": r["source"],
            "status": r["status"],
            "request": unpack(r["request"]),
            "response": unpack(r["response"]),
            "prompt_tokens": int(r["prompt_tokens"]),
            "completion_tokens": int(r["completion_tokens"]),
            "media": int(r["media"]),
            "media_bytes": int(r["media_bytes"]),
            "meta": meta,
        }
        # 0.31: where the turn came from, when the app said (the columns exist from the
        # migration on; a row from before reads "" and 0)
        keys = r.keys()
        for col, name in (
            ("run", "run"),
            ("turn_no", "turn"),
            ("step", "step"),
            ("trajectory", "trajectory"),
            ("trajectory_step", "trajectory_step"),
            ("script", "script"),
            ("turn_key", "turn_key"),
        ):
            if col in keys and r[col]:
                d[name] = r[col]
        # one question, many calls: whether this call opened the turn (absent until the
        # backfill has read a row kept before 0.31)
        if "turn_start" in keys and int(r["turn_start"]) >= 0:
            d["turn_start"] = bool(r["turn_start"])
        return d

    def my_turns(
        self, caller: Caller, since: int = 0, limit: int = 50, before: int = 0, before_id: str = "", conversation: str = ""
    ) -> list[dict]:
        """The account's own record, newest first, for a device reading it back; the
        address the operator sees is not part of it."""
        out = []
        for r in self.db.turns(caller.account_id, since, min(limit, 200), before, before_id, conversation[:80]):
            d = self._turn_view(r)
            d.pop("account_id", None)
            d["meta"].pop("ip", None)
            out.append(d)
        return out

    def my_turn(self, caller: Caller, turn_id: str) -> dict | None:
        r = self.db.turn(turn_id[:96])
        if r is None or r["account_id"] != caller.account_id:
            return None
        d = self._turn_view(r)
        d.pop("account_id", None)
        d["meta"].pop("ip", None)
        return d

    def record_view(self, caller: Caller) -> dict:
        """Data controls' second line: what the record holds of this account."""
        totals = self.db.record_totals(0, caller.account_id) if self.s.record_turns else {}
        return {
            "on": self.s.record_turns,
            "turns": int(totals.get("n") or 0),
            "own": int(totals.get("own") or 0),
            "files": int(totals.get("files") or 0),
            "media_bytes": int(totals.get("store_bytes") or 0),
            "keep_days": self.s.record_keep_days,
        }

    def admin_turns(
        self, account_id: str | None = None, since: int = 0, limit: int = 100, before: int = 0, before_id: str = "", conversation: str = ""
    ) -> list[dict]:
        return [self._turn_view(r) for r in self.db.turns(account_id, since, limit, before, before_id, conversation[:80])]

    def admin_turn(self, turn_id: str) -> dict | None:
        """One call of the record in full, with the account's hint, for the console."""
        r = self.db.turn(turn_id)
        if r is None:
            return None
        d = self._turn_view(r)
        hints, _ = self._labels([d["account_id"]], decrypt=False)
        d["hint"] = hints.get(d["account_id"], "?")
        return d

    def admin_turn_groups(
        self,
        since: int = 0,
        limit: int = 20,
        before: int = 0,
        before_key: str = "",
        *,
        account_id: str | None = None,
        conversation: str = "",
        platform: str = "",
        run: str = "",
        source: str = "",
        media: bool = False,
        hands: bool = False,
        script: str = "",
        model: str = "",
    ) -> dict:
        """The record one question at a time (0.31): the newest turns matching the filters,
        each with its figures and laid out as its steps (turnview.lay_out) — the person's
        message, what the model said and what came back at each call, the reply. Pages on
        the last call's time and the key. ``pending`` is how many calls the backfill has
        not yet told which turn they belong to; they are not shown here."""
        groups = self.db.turn_groups(
            since,
            limit,
            before,
            before_key,
            account_id=account_id,
            conversation=conversation[:80],
            platform=platform[:24],
            run=run[:24],
            source=source[:8],
            media=media,
            hands=hands,
            script=script[:8],
            model=model[:120],
        )
        keys = [str(g["turn_key"]) for g in groups]
        calls: dict[str, list[dict]] = {k: [] for k in keys}
        for r in self.db.turns_of(keys):
            calls[str(r["turn_key"])].append(self._turn_view(r))
        hints, _ = self._labels([str(g["account_id"]) for g in groups], decrypt=False)
        out = []
        for g in groups:
            key = str(g["turn_key"])
            rows = calls.get(key) or []
            first = rows[0] if rows else {}
            last = rows[-1] if rows else {}
            laid = turnview.lay_out(rows)
            out.append(
                {
                    "key": key,
                    "account_id": g["account_id"],
                    "hint": hints.get(str(g["account_id"]), "?"),
                    "ts0": int(g["ts0"]),
                    "ts1": int(g["ts1"]),
                    "calls": int(g["n"]),
                    "conversation": first.get("conversation", ""),
                    "device": first.get("device", ""),
                    "platform": first.get("platform", ""),
                    "run": first.get("run", ""),
                    "turn": first.get("turn", 0),
                    "source": first.get("source", "cloud"),
                    "sources": sorted({str(c.get("source") or "cloud") for c in rows}),
                    "models": sorted({str(c.get("model") or "") for c in rows if c.get("model")}),
                    "script": first.get("script", ""),
                    "trajectory": next((str(c["trajectory"]) for c in rows if c.get("trajectory")), ""),
                    "prompt_tokens": int(g["prompt_tokens"] or 0),
                    "completion_tokens": int(g["completion_tokens"] or 0),
                    "media": int(g["media"] or 0),
                    "partial": int(g["partial"] or 0),
                    "status": last.get("status", "ok"),
                    "ended": (last.get("meta") or {}).get("ended", "") if isinstance(last.get("meta"), dict) else "",
                    **laid,
                }
            )
        figures = self.db.turn_figures(since, account_id)
        return {"turns": out, "pending": figures["pending"], "total": figures["turns"]}

    def admin_record(self, days: int = 30) -> dict:
        """The operator's figures: turns and files in all and over ``days``, by day, and the
        store against its cap."""
        t = now()
        off = self.s.day_offset_h * 3600
        since = self.s.day_start(t) - 86400 * max(0, days - 1)
        by_day = {int(r["day"]): r for r in self.db.turns_by_day(since, off)}
        rows = []
        for i in range(days):
            d = since + i * 86400
            s = by_day.get(d)
            rows.append(
                {
                    "day": d,
                    # `turns` counted the rows before 0.31 and still does: it is the calls.
                    # `questions` is the turns the person asked (the rows that opened one).
                    "turns": int(s["n"]) if s else 0,
                    "questions": int(s["turns"] or 0) if s else 0,
                    "accounts": int(s["accounts"]) if s else 0,
                    "media": int(s["media"] or 0) if s else 0,
                    "media_bytes": int(s["media_bytes"] or 0) if s else 0,
                }
            )
        ever = self.db.record_totals(0)
        period = self.db.record_totals(since)
        figures = self.db.turn_figures(since)
        per_turn: dict[str, int] = {name: 0 for _lo, _hi, name in provenance.CALL_BUCKETS}
        calls_in_turns = 0
        turns_keyed = 0
        for n_calls, n_turns in self.db.calls_per_turn(since):
            per_turn[provenance.call_bucket(n_calls)] += n_turns
            calls_in_turns += n_calls * n_turns
            turns_keyed += n_turns
        return {
            "on": self.s.record_turns,
            "keep_days": self.s.record_keep_days,
            "media_dir": str(self.media.root),
            "media_cap_bytes": int(self.s.media_max_gb * 1024**3),
            "totals": {
                **{k: int(ever.get(k) or 0) for k in ("n", "accounts", "own", "partial", "media", "media_bytes", "files", "store_bytes")},
                "questions": int(ever.get("turns") or 0),
            },
            "period": {
                "days": days,
                **{k: int(period.get(k) or 0) for k in ("n", "accounts", "own", "partial", "media", "media_bytes")},
                "questions": int(period.get("turns") or 0),
            },
            # 0.31: the record counted by questions — one person's message and every model
            # call it took — beside the calls: how many questions, how many calls each took,
            # how many had a picture or ran the hands, and how many calls the backfill has
            # not yet told which question they belong to
            "questions": {
                "n": figures["turns"],
                "pending": figures["pending"],
                "with_media": figures["with_media"],
                "with_hands": figures["with_hands"],
                "calls_per_question": per_turn,
                "calls_mean": (calls_in_turns / turns_keyed) if turns_keyed else 0.0,
            },
            "days": rows,
        }

    def export_turns(self, since: int = 0, account_id: str | None = None):
        """The record as JSON lines, the operator reading it whole (account ids included:
        this is the account's data, not the training set — that export is export_samples).
        The files are fetched by hash from GET /v1/admin/blobs/{sha256}."""
        before, before_id = 0, ""
        while True:
            rows = self.db.turns(account_id, since, 500, before, before_id)
            if not rows:
                return
            for r in rows:
                d = self._turn_view(r)
                d["subject"] = self.subject_of(str(r["account_id"]))
                yield json.dumps(d, ensure_ascii=False) + "\n"
            before, before_id = int(rows[-1]["ts"]), str(rows[-1]["id"])

    def purge_record(self, account_id: str) -> tuple[int, int]:
        """The account's record gone: rows first, then the files whose last reference it held."""
        turns, orphans = self.db.delete_turns(account_id)
        removed = sum(1 for sha in orphans if self.media.delete(sha))
        return turns, removed

    def sweep_record(self) -> dict[str, int]:
        """Once an hour from the analytics loop: turns past RECORD_KEEP_DAYS (when set), then
        files past MEDIA_MAX_GB, least recently used first. Answers what went."""
        out = {"turns": 0, "files": 0, "trimmed": 0}
        if not self.s.record_turns:
            return out
        out["files"] += self.media.retry_deletes()  # what an earlier delete could not remove
        if self.s.record_keep_days > 0:
            before = now() - self.s.record_keep_days * 86400
            for _ in range(20):
                n, orphans = self.db.sweep_turns(before)
                out["turns"] += n
                out["files"] += sum(1 for sha in orphans if self.media.delete(sha))
                if n == 0 and not orphans:
                    break
        cap = int(self.s.media_max_gb * 1024**3)
        if cap > 0:
            for _ in range(50):
                gone = self.db.trim_blobs(cap)
                if not gone:
                    break
                out["trimmed"] += sum(1 for sha in gone if self.media.delete(sha))
        return out

    def admin_data(self, days: int = 30) -> dict:
        """The operator's view of Data controls: how many accounts have the switch on, how
        many turns were kept, by day, model and app, how often it is turned on and off —
        and the newest turns themselves (the account only as its masked hint)."""
        t = now()
        off = self.s.day_offset_h * 3600
        since = self.s.day_start(t) - 86400 * max(0, days - 1)
        by_day = {int(r["day"]): r for r in self.db.samples_by_day(since, off)}
        events: dict[int, dict[str, int]] = {}
        for r in self.db.events_by_day(since, off):
            events.setdefault(int(r["day"]), {})[str(r["kind"])] = int(r["n"])
        rows = []
        for i in range(days):
            d = since + i * 86400
            s = by_day.get(d)
            e = events.get(d, {})
            rows.append(
                {
                    "day": d,
                    "samples": int(s["n"]) if s else 0,
                    "turns": int(s["turns"] or 0) if s else 0,
                    "accounts": int(s["accounts"]) if s else 0,
                    "prompt_tokens": int(s["prompt_tokens"] or 0) if s else 0,
                    "completion_tokens": int(s["completion_tokens"] or 0) if s else 0,
                    "turned_on": e.get("contribute.on", 0),
                    "turned_off": e.get("contribute.off", 0),
                    "default_on": e.get("contribute.default", 0),
                    "deleted": e.get("contribute.deleted", 0),
                }
            )
        # each split counts the calls (`samples`) and the questions they belong to (`turns`,
        # 0.31: the calls that opened one)
        platforms = {str(r["platform"]) or "other": (int(r["n"]), int(r["turns"] or 0)) for r in self.db.samples_by_platform(since)}
        # 0.31: by who started the turn and by the key it ran on (the shape rows; a turn kept
        # before the apps said reads "" — shown as "not said")
        runs = {str(r["run"]): (int(r["n"]), int(r["turns"] or 0)) for r in self.db.samples_by_column("run", since)}
        sources = {str(r["source"]) or "cloud": (int(r["n"]), int(r["turns"] or 0)) for r in self.db.samples_by_column("source", since)}
        samples = self.admin_samples(None, 0, 30)
        hints, _ = self._labels([smp["account_id"] for smp in samples], decrypt=False)
        recent = [{**smp, "hint": hints.get(smp["account_id"], "?")} for smp in samples]
        # every account with turns kept, as the way in to each one's data (the drawer pages
        # through all of them)
        by_account = [
            {
                "account_id": r["account_id"],
                "hint": r["hint"],
                "channel": r["channel"],
                "contribute": bool(r["contribute"]),
                "created_at": int(r["created_at"]),
                "samples": int(r["n"]),
                "turns": int(r["turns"] or 0),
                "prompt_tokens": int(r["prompt_tokens"] or 0),
                "completion_tokens": int(r["completion_tokens"] or 0),
                "first_ts": int(r["first_ts"]),
                "last_ts": int(r["last_ts"]),
                "models": sorted(m for m in str(r["models"] or "").split(",") if m),
            }
            for r in self.db.samples_by_account()
        ]
        counts = self.db.account_counts()
        total = int(counts.get("total", 0) or 0)
        on = self.db.contributors()
        period = self.db.samples_totals(since)
        ever = self.db.samples_totals(0)
        return {
            "generated_at": t,
            "default_on": self.s.improve_default,
            "keeps": SAMPLE_KEEPS,
            # 0.30: shape rows still waiting for their tokens (the backfill after the upgrade);
            # the token figures below leave them out until it is through
            "tokens_pending": self.db.sample_stats_without_tokens(),
            "accounts": {
                "total": total,
                "on": on,
                "off": max(0, total - on),
                "share": (on / total) if total else 0.0,
                "turned_off_ever": self.db.event_accounts("contribute.off"),
                "with_samples": int(ever["accounts"] or 0),
            },
            # `samples` is the calls kept (one row each); `turns` the questions they belong
            # to (0.31: the calls that opened one); `turns_pending` the rows the backfill has
            # not read yet, counted in neither
            "totals": {
                "samples": int(ever["n"] or 0),
                "turns": int(ever["turns"] or 0),
                "turns_pending": int(ever["pending"] or 0),
                "prompt_tokens": int(ever["prompt_tokens"] or 0),
                "completion_tokens": int(ever["completion_tokens"] or 0),
            },
            "period": {
                "days": days,
                "samples": int(period["n"] or 0),
                "turns": int(period["turns"] or 0),
                "accounts": int(period["accounts"] or 0),
                "prompt_tokens": int(period["prompt_tokens"] or 0),
                "completion_tokens": int(period["completion_tokens"] or 0),
            },
            "days": rows,
            "by_model": [
                {
                    "model": r["model"],
                    "samples": int(r["n"]),
                    "turns": int(r["turns"] or 0),
                    "tokens": int(r["prompt_tokens"] or 0) + int(r["completion_tokens"] or 0),
                }
                for r in self.db.samples_by_model(since)
            ],
            "by_platform": sorted(
                ({"platform": k, "samples": v[0], "turns": v[1]} for k, v in platforms.items()), key=lambda x: -x["samples"]
            ),
            "by_run": sorted(({"run": k, "samples": v[0], "turns": v[1]} for k, v in runs.items()), key=lambda x: -x["samples"]),
            "by_source": sorted(({"source": k, "samples": v[0], "turns": v[1]} for k, v in sources.items()), key=lambda x: -x["samples"]),
            "by_account": by_account,
            "recent": recent,
        }

    def keep_sample(
        self,
        caller: Caller,
        model: str,
        messages: list,
        response: str,
        prompt_tokens: int,
        completion_tokens: int,
        meta: dict | None = None,
        message: dict | None = None,
    ) -> None:
        """Called after a chat turn for an account with the switch on; anything else is a
        no-op. Only the training view of the turn is written (_training_view). ``message``
        is the assistant's whole message when the caller has it: its tool calls are kept in
        the meta (0.31), since ``response`` is the text alone and a turn that only called
        a tool would otherwise read as an empty reply."""
        if not caller.contribute:
            return
        request, cut = _fit_messages(_training_view(messages), self.SAMPLE_MAX_CHARS)
        meta = dict(meta or {})
        if isinstance(message, dict) and isinstance(message.get("tool_calls"), list) and message["tool_calls"]:
            calls = _training_view([message])
            if calls and isinstance(calls[0], dict) and calls[0].get("tool_calls"):
                meta["tool_calls"] = calls[0]["tool_calls"]
        if cut or len(response) > self.SAMPLE_MAX_CHARS:
            meta["truncated"] = True
        meta_json = json.dumps(meta, ensure_ascii=False)
        response = response[: self.SAMPLE_MAX_CHARS]
        sid = self.db.add_sample(caller.account_id, model, request, response, prompt_tokens, completion_tokens, meta_json)
        # 0.28: the turn's shape beside it (analytics.py), so the quality page never reads the turn
        try:
            self.db.add_sample_stats(
                [sample_shape(sid, caller.account_id, now(), model, request, response, meta_json, prompt_tokens, completion_tokens)]
            )
        except Exception:  # the shape is a convenience; the turn is kept either way
            log.exception("sample_stats row")

    def admin_samples(
        self, account_id: str | None = None, since: int = 0, limit: int = 100, before: int = 0, before_id: str = ""
    ) -> list[dict]:
        out = []
        for r in self.db.samples(account_id, since, limit, before, before_id):
            d = dict(r)
            d["request"], cut = _load_messages(d["request"])
            d["meta"] = _load_meta(d["meta"])
            if cut:
                d["meta"]["truncated"] = True
            d["platform"] = platform_from(d["meta"])
            out.append(d)
        return out

    def export_samples(self, since: int = 0, account_id: str | None = None):
        """Every contributed conversation as JSON lines, without the account id: the
        training set is about what was said, not who said it. With ``account_id``, one
        account's turns only (the operator reading one person's data in full)."""
        before, before_id = 0, ""
        while True:
            # keyset paging on (ts, id): a page ending inside a busy second continues there
            rows = self.db.samples(account_id, since, 1000, before, before_id)
            if not rows:
                return
            for r in rows:
                messages, cut = _load_messages(r["request"])
                meta = _load_meta(r["meta"])
                meta.pop("ip", None)  # the training set says what was said, not from where
                if cut:
                    meta["truncated"] = True
                d = {
                    "id": r["id"],
                    # 0.31: the account's pseudonym, so one person's turns group across the
                    # export and go together when the deletions ledger names the subject
                    "subject": self.subject_of(str(r["account_id"])),
                    "ts": int(r["ts"]),
                    "model": r["model"],
                    "platform": platform_from(meta),
                    "messages": messages,
                    "response": r["response"],
                    "prompt_tokens": int(r["prompt_tokens"]),
                    "completion_tokens": int(r["completion_tokens"]),
                    "meta": meta,
                }
                yield json.dumps(d, ensure_ascii=False) + "\n"
            before, before_id = int(rows[-1]["ts"]), str(rows[-1]["id"])
            if len(rows) < 1000:
                return

    def estimate(
        self, caller: Caller, images: int = 0, clips: int = 0, image_model: str = "", video_model: str = "", size: str | None = None
    ) -> dict:
        """What a job would cost before it is started — the app asks before a new
        face (five pictures and, with video on, four clips) and shows the person
        the number next to what they have left today. Nothing is charged."""
        images = max(0, min(images, 50))
        clips = max(0, min(clips, 20))
        if (images or clips) and not self.s.media_enabled:
            kind = "image" if images else "video"
            noun = "pictures" if images else "clips"
            raise CloudError(
                410,
                "hosted_media_retired",
                f"nanoMuse Cloud no longer generates {noun}. Add your own {kind} provider "
                "and API key in Settings → Models to use this feature.",
                {"kind": kind, "action": "configure_own_provider"},
            )
        parts = []
        cost = 0
        if images:
            m = self.model_for(image_model, "image", caller) if image_model else next((x for x in self.s.models if x.kind == "image"), None)
            if m is None:
                raise CloudError(404, "model_not_offered", "nanoMuse Cloud offers no image model")
            c = m.image_cost_uy(size) * images
            cost += c
            parts.append({"kind": "image", "model": m.id, "count": images, "cny": self.s.uy_to_cny(c)})
        if clips:
            m = self.model_for(video_model, "video", caller) if video_model else next((x for x in self.s.models if x.kind == "video"), None)
            if m is None:
                raise CloudError(404, "model_not_offered", "nanoMuse Cloud offers no video model")
            c = m.video_cost_uy(m.clip_seconds) * clips
            cost += c
            parts.append({"kind": "video", "model": m.id, "count": clips, "seconds": m.clip_seconds, "cny": self.s.uy_to_cny(c)})
        a = self.allowance(caller)
        room = a["left_uy"]
        left_cny = None if room is None else self.s.uy_to_cny(room)
        grant_cny = self.s.uy_to_cny(a["grant_uy"])
        return {
            "cny": self.s.uy_to_cny(cost),
            "usd": self.s.cny_to_usd(self.s.uy_to_cny(cost)),
            "parts": parts,
            "left_cny": left_cny,
            "grant_cny": grant_cny,
            "unlimited": room is None,
            "affordable": room is None or cost <= room,
            # 0.4 names, one more version
            "left_today_cny": left_cny,
            "credit_left_cny": 0,
            "clips_ok": True,
            "clips": self.clips_view(),
            "daily_cap_cny": grant_cny,
        }

    # -- admin ------------------------------------------------------------------------------

    def admin_credit(self, account_id: str, cny: float, note: str = "", actor: str = "console") -> dict:
        """Credit from the operator: a merged pull request, a reported bug, a
        promised refund. It goes into the account's pool and never expires; the audit
        log says who gave it."""
        if self.db.account(account_id) is None:
            raise CloudError(404, "no_account", "No such account")
        if cny == 0 or not -1000 <= cny <= 1000:
            raise CloudError(400, "bad_request", "Credit is between -¥1000 and ¥1000, not 0")
        if cny < 0:  # 0.16: the operator may take back as well as give
            return self.admin_set_pool(account_id, {"delta_cny": cny, "note": note}, actor=actor)
        self.db.add_credit(account_id, self.s.cny_to_uy(cny), note=note)
        self.db.add_event(account_id, "credit.granted", f"¥{cny:g}")
        self.db.audit_add(actor, "credit", account_id[:8], f"¥{cny:g}{' · ' + note if note else ''}")
        a = dict(self.db.account(account_id))  # type: ignore[arg-type]
        a["identifier"] = self.crypto.decrypt(account_id, a.pop("identifier_enc", "")) or ""
        a["member"] = bool(a.get("unlimited")) or a.pop("id_hash", None) in self.member_hashes
        a.pop("id_hash", None)
        a.pop("password_hash", None)
        a["spent_cny"] = self.s.uy_to_cny(self.db.spent_since(account_id, 0))
        self._pool_fields(a, spent_cny=a["spent_cny"])
        return a

    def admin_resolve(self, account_id: str = "", identifier: str = "") -> str:
        """Operators may name an account by its id or by the phone/e-mail itself."""
        if identifier:
            try:
                ident = parse(identifier)
            except BadIdentifier as e:
                raise CloudError(400, "bad_identifier", str(e)) from e
            row = self._account_for(ident)
        else:
            row = self.db.account(account_id)
        if row is None:
            raise CloudError(404, "no_account", "No such account")
        return row["id"]

    def admin_grant(self, account_id: str, tokens: int, actor: str = "console") -> dict:
        """The older token grant, adjusted by the operator; the account's timeline and the
        audit log say by how much and who did it."""
        if self.db.account(account_id) is None:
            raise CloudError(404, "no_account", "No such account")
        self.db.grant(account_id, tokens, kind="adjust")
        self.db.add_event(account_id, "grant.tokens", f"{tokens:+d} tokens by {actor}"[:200])
        self.db.audit_add(actor, "grant.tokens", account_id[:8], f"{tokens:+d} tokens")
        a = dict(self.db.account(account_id))  # type: ignore[arg-type]
        a["identifier"] = self.crypto.decrypt(account_id, a.pop("identifier_enc", "")) or ""
        a.pop("id_hash", None)
        return a

    def admin_accounts(self) -> list[dict]:
        """With the identifier in clear (decrypted here, for the admin token
        only); the hash and ciphertext stay out of the reply. `member` says
        whether the account escapes the daily cap, and why."""
        t = now()
        out = []
        for r in self.db.admin_accounts(self.s.day_start(t), limit=100_000):
            d = dict(r)
            d["identifier"] = self.crypto.decrypt(d["id"], d.pop("identifier_enc", "")) or ""
            id_hash = d.pop("id_hash", None)
            d["has_password"] = bool(d.pop("password_hash", ""))
            d.pop("failed_logins", None)
            locked_until = d.pop("locked_until", None)
            d["locked"] = bool(locked_until and int(locked_until) > t)
            d["disabled"] = bool(d["disabled"])
            d["unlimited"] = bool(d.get("unlimited"))
            d["listed"] = id_hash in self.member_hashes
            d["member"] = d["unlimited"] or d["listed"]
            d["review"] = id_hash in self.review_hashes
            d["spent_today_cny"] = self.s.uy_to_cny(int(d.pop("spent_today_uy", 0) or 0))
            d["spent_cny"] = self.s.uy_to_cny(int(d.pop("spent_uy", 0) or 0))
            self._pool_fields(d, spent_cny=d["spent_cny"])
            d["contribute"] = bool(d.get("contribute"))
            d["last_platform"] = platform_of(d.get("last_ua") or "")
            d["last_version"] = client_version(d.get("last_ua") or "")
            d["last_seen_at"] = int(d["last_seen_at"]) if d.get("last_seen_at") else None
            out.append(d)
        return out

    def _pool_fields(self, d: dict, spent_cny: float) -> None:
        """The account's pool in yuan (`grant_cny`), what is left of it (`left_cny`, None for a
        member), the invites that fed it and whether the co-creation bonus was taken; the
        0.4 credit columns leave the reply."""
        for k in ("credit_uy", "credit_used_uy", "clips_bonus"):
            d.pop(k, None)
        grant = int(d.pop("grant_uy", 0) or 0)
        d["grant_cny"] = self.s.uy_to_cny(grant)
        member = bool(d.get("member"))
        d["left_cny"] = None if member or self.s.allowance_cny <= 0 else round(max(0.0, d["grant_cny"] - spent_cny), 4)
        d["invites"] = int(d.get("invites") or 0)
        d["contribute_bonus_at"] = int(d["contribute_bonus_at"]) if d.get("contribute_bonus_at") else None

    def admin_usage(self, days: int = 14) -> list[dict]:
        t = now()
        since = self.s.day_start(t) - 86400 * max(0, days - 1)
        out = []
        for r in self.db.usage_by_day(since, self.s.day_offset_h * 3600):
            d = dict(r)
            d["cost_cny"] = self.s.uy_to_cny(int(d.pop("cost_uy", 0) or 0))
            out.append(d)
        return out

    def _rows_cny(self, rs) -> list[dict]:
        out = []
        for r in rs:
            d = dict(r)
            d["cost_cny"] = self.s.uy_to_cny(int(d.pop("cost_uy", 0) or 0))
            for k in ("requests", "prompt_tokens", "completion_tokens", "charged"):
                if k in d:
                    d[k] = int(d.get(k) or 0)
            out.append(d)
        return out

    def admin_overview(self, days: int = 30) -> dict:
        """The operator's dashboard in one call: how many people, how active,
        what it costs — today, this week, over `days` — split by kind and by
        model, plus the last sign-ins and refusals. Since 0.22 the identifier comes in
        full beside the masked hint (the console is the operator's; logs and mail keep the hint)."""
        t = now()
        day_start = self.s.day_start(t)
        week_start = day_start - 6 * 86400
        since = day_start - 86400 * max(0, days - 1)

        def totals(s: int) -> dict:
            r = self.db.totals_since(s)
            return {
                "requests": int(r["requests"] or 0),
                "charged": int(r["charged"] or 0),
                "prompt_tokens": int(r["prompt_tokens"] or 0),
                "completion_tokens": int(r["completion_tokens"] or 0),
                "cost_cny": self.s.uy_to_cny(int(r["cost_uy"] or 0)),
                "active_accounts": self.db.active_accounts_since(s),
                "new_accounts": self.db.accounts_created_since(s, self.review_hashes),
                "by_kind": self._rows_cny(self.db.usage_by_kind(s)),
            }

        counts = self.db.event_counts(day_start)
        top_rows = self.db.top_accounts_since(since, limit=20)
        event_rows = self.db.events_recent(60)
        # 0.22: the console shows accounts in full (decrypted for the admin token only);
        # the hint stays beside it for anything that leaves the console. Only the accounts
        # on this page are read and decrypted, not every account the relay has.
        hints, idents = self._labels([r["account_id"] for r in top_rows] + [r["account_id"] for r in event_rows if r["account_id"]])
        top = []
        for r in top_rows:
            top.append(
                {
                    "account_id": r["account_id"],
                    "hint": hints.get(r["account_id"], "?"),
                    "identifier": idents.get(r["account_id"], ""),
                    "requests": int(r["requests"] or 0),
                    "charged": int(r["charged"] or 0),
                    "cost_cny": self.s.uy_to_cny(int(r["cost_uy"] or 0)),
                }
            )
        events = []
        for r in event_rows:
            d = dict(r)
            d["hint"] = hints.get(d["account_id"], "") if d["account_id"] else ""
            d["identifier"] = idents.get(d["account_id"], "") if d["account_id"] else ""
            events.append(d)
        return {
            "generated_at": t,
            "day_start": day_start,
            "accounts": self.db.account_counts(),
            "today": totals(day_start),
            "week": totals(week_start),
            "period": {"days": days, **totals(since), "by_model": self._rows_cny(self.db.usage_by_model(since))},
            "signals_today": {
                "sign_ins": counts.get("sign_in.code", 0) + counts.get("sign_in.password", 0),
                "sign_in_failures": counts.get("sign_in.failed", 0),
                "budget_refusals": counts.get("budget.refused", 0),
                "upstream_errors": counts.get("upstream.error", 0),
                "content_rejected": counts.get("content.rejected", 0),
                "calls": counts.get("call.ended", 0),
            },
            "top_accounts": top,
            "events": events,
            # what the community chose to give: how many accounts contribute, how many turns so far
            "contributions": {"accounts": self.db.contributors(), "samples": self.db.sample_count()},
            "settings": self.admin_settings(),
        }

    def admin_series(self, days: int = 30) -> dict:
        """The relay's own numbers by local day, for the operator's charts: sign-ins,
        new and active accounts, invites taken up, co-creation joins, calls, refusals —
        one row per day of the period, zeros where nothing happened — plus the devices
        by kind and system and the invite funnel as they stand now."""
        t = now()
        off = self.s.day_offset_h * 3600
        since = self.s.day_start(t) - 86400 * max(0, days - 1)
        by_day: dict[int, dict[str, int]] = {}
        for r in self.db.events_by_day(since, off):
            by_day.setdefault(int(r["day"]), {})[str(r["kind"])] = int(r["n"])
        new = {int(r["day"]): int(r["n"]) for r in self.db.accounts_by_day(since, off, self.review_hashes)}
        active = {int(r["day"]): int(r["n"]) for r in self.db.active_by_day(since, off)}
        rows = []
        for i in range(days):
            d = since + i * 86400
            e = by_day.get(d, {})
            rows.append(
                {
                    "day": d,
                    "sign_ins": e.get("sign_in.code", 0) + e.get("sign_in.password", 0),
                    "sign_in_failures": e.get("sign_in.failed", 0),
                    "new_accounts": new.get(d, 0),
                    "active_accounts": active.get(d, 0),
                    "invites_used": e.get("invite.used", 0),
                    "contribute_on": e.get("contribute.on", 0),
                    "calls": e.get("call.ended", 0),
                    "budget_refusals": e.get("budget.refused", 0),
                    "upstream_errors": e.get("upstream.error", 0),
                    "content_rejected": e.get("content.rejected", 0),
                }
            )
        devices = [{"kind": r["kind"], "os": r["os"] or "", "count": int(r["n"])} for r in self.db.devices_by_kind_os()]
        return {
            "generated_at": t,
            "days": rows,
            "devices": devices,
            "invites": self.db.invite_funnel(),
            "contributors": self.db.contributors(),
        }

    def admin_traffic(self, days: int = 30) -> dict:
        """The site's visits and downloads, read from the traffic database that
        demo/showcase/mirror/traffic.py keeps (TRAFFIC_DB, mounted read-only). Daily
        counts only — the script never wrote an address, so there is none to show."""
        path = self.s.traffic_db
        if not path or not os.path.exists(path):
            return {"available": False}
        off = self.s.day_offset_h * 3600
        first = now() + off - 86400 * max(0, days - 1)
        since = time.strftime("%Y-%m-%d", time.gmtime(first))
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        except sqlite3.Error:
            return {"available": False}
        conn.row_factory = sqlite3.Row
        with closing(conn):
            try:
                have = {r["day"]: dict(r) for r in conn.execute("SELECT * FROM days WHERE day>=? ORDER BY day", (since,))}
                # one row a day, zeros where the log had nothing, so the charts line up
                day_rows = []
                for i in range(days):
                    d = time.strftime("%Y-%m-%d", time.gmtime(first + i * 86400))
                    day_rows.append(
                        have.get(d) or {"day": d, "requests": 0, "pages": 0, "visitors": 0, "bots": 0, "downloads": 0, "bytes": 0}
                    )

                def top(table: str, col: str, limit: int = 15) -> list[dict]:
                    return [
                        {"name": r[col], "hits": int(r["hits"])}
                        for r in conn.execute(
                            f"SELECT {col}, SUM(hits) AS hits FROM {table} WHERE day>=? GROUP BY {col} ORDER BY hits DESC LIMIT ?",
                            (since, limit),
                        )
                    ]

                pages, referrers = top("pages", "path"), top("referrers", "host")
                downloads = [
                    {"name": r["file"], "hits": int(r["hits"]), "bytes": int(r["bytes"] or 0)}
                    for r in conn.execute(
                        "SELECT file, SUM(hits) AS hits, SUM(bytes) AS bytes FROM downloads WHERE day>=? GROUP BY file ORDER BY hits DESC LIMIT 40",
                        (since,),
                    )
                ]
                gh_days = [
                    {"day": r["day"], "stars": int(r["stars"]), "downloads": int(r["downloads"])}
                    for r in conn.execute("SELECT day, stars, downloads FROM github WHERE day>=? ORDER BY day", (since,))
                ]
                latest = conn.execute("SELECT * FROM github ORDER BY day DESC LIMIT 1").fetchone()
                last_run = conn.execute("SELECT value FROM state WHERE key='last_run'").fetchone()
            except sqlite3.Error:
                return {"available": False}
        github: dict = {"days": gh_days}
        if latest is not None:
            try:
                assets = json.loads(latest["assets"] or "{}")
            except ValueError:
                assets = {}
            github.update(
                {
                    "day": latest["day"],
                    "stars": int(latest["stars"]),
                    "forks": int(latest["forks"]),
                    "watchers": int(latest["watchers"]),
                    "downloads": int(latest["downloads"]),
                    "assets": assets,
                }
            )
        return {
            "available": True,
            "since": since,
            "updated_at": int(last_run["value"]) if last_run else 0,
            "days": day_rows,
            "pages": pages,
            "referrers": referrers,
            "downloads": downloads,
            "github": github,
        }

    def admin_account(self, account_id: str, days: int = 30) -> dict:
        """Everything the relay knows about one account, for the operator:
        the identifier in clear, spend by kind / model / day, the live
        sign-ins (device names only), the remembered devices, its timeline.
        What the person said to the model is not here — it was never kept."""
        row = self.db.account(account_id)
        if row is None:
            raise CloudError(404, "no_account", "No such account")
        t = now()
        day_start = self.s.day_start(t)
        since = day_start - 86400 * max(0, days - 1)
        a = dict(row)
        a["identifier"] = self.crypto.decrypt(account_id, a.pop("identifier_enc", "") or "") or ""
        id_hash = a.pop("id_hash", None)
        a.pop("password_hash", None)
        a["has_password"] = bool(row["password_hash"])
        a["disabled"] = bool(a["disabled"])
        a["unlimited"] = bool(a.get("unlimited"))
        a["listed"] = id_hash in self.member_hashes
        a["member"] = a["unlimited"] or a["listed"]
        a["review"] = id_hash in self.review_hashes
        a["locked"] = bool(row["locked_until"] and int(row["locked_until"]) > t)
        spent_total = self.db.spent_since(account_id, 0)
        self._pool_fields(a, spent_cny=self.s.uy_to_cny(spent_total))
        # who this account brought (the newest 500, with the count of all of them), and who
        # brought this account: the operator can follow an invite chain either way
        a["invited"] = [self._invitee_fields(r) for r in self.db.invitees(account_id, limit=500)]
        a["invited_total"] = self.db.invitee_count(account_id)
        a["inviter"] = self._account_label(str(a.get("invited_by") or ""))
        a["invite_earned_cny"] = self.s.uy_to_cny(self.db.invite_earned_uy(account_id))
        a["contribute"] = bool(a.get("contribute"))
        # turns kept while the switch was on stay until the person deletes them: count them
        # whether or not it is on now, so the operator sees what is there
        a["samples"] = self.db.sample_count(account_id)
        a["last_seen_at"] = int(a["last_seen_at"]) if a.get("last_seen_at") else None
        a["last_platform"] = platform_of(a.get("last_ua") or "")
        a["last_version"] = client_version(a.get("last_ua") or "")
        spent_today = self.db.spent_since(account_id, day_start)
        ledger = self.ledger_page(account_id, limit=60)
        events = self.events_page(account_id, limit=80)
        return {
            "account": a,
            # 0.10: where the account was seen from, over everything the relay recorded
            "addresses": [
                {
                    "ip": r["ip"],
                    "n": int(r["n"] or 0),
                    "first_seen": int(r["first_seen"] or 0),
                    "last_seen": int(r["last_seen"] or 0),
                    "platforms": sorted({platform_of(u) for u in str(r["uas"] or "").split(",") if u}),
                }
                for r in self.db.addresses_for(account_id)
            ],
            "ledger_total": ledger["total"],
            "events_total": events["total"],
            "spend": {
                "today_cny": self.s.uy_to_cny(spent_today),
                "total_cny": self.s.uy_to_cny(spent_total),
                "grant_cny": a["grant_cny"],
                "left_cny": a["left_cny"],
                "used_today": self.db.used_since(account_id, day_start),
                "requests_total": self.db.requests_since(account_id, 0),
            },
            "usage": {
                "today": {"by_kind": self._rows_cny(self.db.usage_by_kind(day_start, account_id))},
                "period": {
                    "days": days,
                    "by_kind": self._rows_cny(self.db.usage_by_kind(since, account_id)),
                    "by_model": self._rows_cny(self.db.usage_by_model(since, account_id)),
                    "by_day": self._rows_cny(self.db.usage_by_day_for(account_id, since, self.s.day_offset_h * 3600)),
                },
                "total": {"by_kind": self._rows_cny(self.db.usage_by_kind(0, account_id))},
            },
            "sessions": [
                {
                    "prefix": k["prefix"],
                    "device": k["device"],
                    "via": k["via"] or "code",
                    "created_at": int(k["created_at"]),
                    "last_used_at": int(k["last_used_at"]) if k["last_used_at"] else None,
                    "revoked_at": int(k["revoked_at"]) if k["revoked_at"] else None,
                    "ip": k["ip"] or "",
                    "ua": k["ua"] or "",
                    "platform": platform_of(k["ua"] or ""),
                    "version": client_version(k["ua"] or ""),
                }
                for k in self.db.keys_for(account_id)
            ],
            "devices": [dict(d) for d in self.db.devices_for(account_id)],
            "recent": ledger["rows"],
            "events": events["rows"],
            # 0.28: how this account's chats went in the period (the telemetry rows, never a word)
            "calls": self._calls_summary(account_id, since),
        }

    def _calls_summary(self, account_id: str, since: int) -> dict:
        r = self.db.calls_for_account(account_id, since)
        n = int(r["n"] or 0)
        return {
            "n": n,
            "ok": int(r["ok"] or 0),
            "errors": int(r["errors"] or 0),
            "refused": int(r["refused"] or 0),
            "hands": int(r["hands"] or 0),
            "images": int(r["images"] or 0),
            "with_tools": int(r["with_tools"] or 0),
            "avg_ttft_ms": round(float(r["avg_ttft_ms"] or 0)),
            "avg_total_ms": round(float(r["avg_total_ms"] or 0)),
            "avg_wait_ms": round(float(r["avg_wait_ms"] or 0)),
            "last_ts": int(r["last_ts"]) if r["last_ts"] else None,
        }

    def _account_label(self, account_id: str) -> dict | None:
        """`id`, `hint` and the identifier in clear for one account, or None when there is
        no such account (an inviter who has since deleted theirs, say)."""
        rows = self.db.accounts_brief([account_id]) if account_id else []
        if not rows:
            return None
        r = rows[0]
        return {"id": r["id"], "hint": r["hint"], "identifier": self.crypto.decrypt(r["id"], r["identifier_enc"] or "") or ""}

    def _invitee_fields(self, r: sqlite3.Row) -> dict:
        """One account that came through an invite, as the operator's page lists it."""
        return {
            "id": r["id"],
            "hint": r["hint"],
            "channel": r["channel"],
            "created_at": int(r["created_at"]),
            "disabled": bool(r["disabled"]),
            "first_ip": r["first_ip"] or "",
            "last_ip": r["last_ip"] or "",
            "last_seen_at": int(r["last_seen_at"]) if r["last_seen_at"] else None,
            "requests": int(r["requests"] or 0),
            "spent_cny": self.s.uy_to_cny(int(r["spent_uy"] or 0)),
            # whether the bonus for this one has been paid (at its first charged request)
            "settled": r["invite_settled_at"] is not None,
        }

    def admin_invites(self, limit: int = 200, per: int = 20) -> dict:
        """Who invited whom, for the operator: the funnel as it stands and the inviters in
        order of how many accounts their code brought, each with how many of those ever
        made a request, how many were seen from one of the inviter's own addresses, what
        they spent and what the inviter's pool got from them, and the newest `per` of the
        accounts themselves (the account page lists up to 500). An inviter with many
        sign-ups from one address and nobody using anything is a pool being farmed; one
        whose invitees go on to make requests brought people."""
        leaders = []
        for r in self.db.invite_leaders(limit):
            leaders.append(
                {
                    "invitees": [self._invitee_fields(i) for i in self.db.invitees(r["id"], limit=per)] if per > 0 else [],
                    "id": r["id"],
                    "hint": r["hint"],
                    "identifier": self.crypto.decrypt(r["id"], r["identifier_enc"] or "") or "",
                    "channel": r["channel"],
                    "created_at": int(r["created_at"]),
                    "disabled": bool(r["disabled"]),
                    "first_ip": r["first_ip"] or "",
                    "last_ip": r["last_ip"] or "",
                    "invites": int(r["invites"] or 0),
                    "invited": int(r["invited"] or 0),
                    "invited_active": int(r["invited_active"] or 0),
                    "invited_settled": int(r["invited_settled"] or 0),
                    "invited_pending": int(r["invited_pending"] or 0),
                    "invited_same_ip": int(r["invited_same_ip"] or 0),
                    "invited_spent_cny": self.s.uy_to_cny(int(r["invited_spent_uy"] or 0)),
                    # net of any clawback: what the invites put in that is still in the pool
                    "earned_cny": self.s.uy_to_cny(int(r["earned_uy"] or 0)),
                    "first_invite_at": int(r["first_invite_at"] or 0),
                    "last_invite_at": int(r["last_invite_at"] or 0),
                }
            )
        return {"generated_at": now(), "funnel": self.db.invite_funnel(), "leaders": leaders}

    def admin_invite_abuse(self, account_id: str, disable: bool = False, delete_unused: bool = False, actor: str = "console") -> dict:
        """One action against an inviter who farmed the bonus: the invite credit still in its
        pool is taken back (never below what it has spent, so `left` stays at zero or above;
        a second call reclaims nothing), the account is disabled when asked, and when asked
        every account it brought that never made a request and never spent anything is
        deleted, in batches, all of them; the ones that used the relay are kept. The
        inviter's timeline says what was done (`invite.clawback`) and the audit log who did
        it. Returns ``{reclaimed_cny, disabled, deleted, kept, deleted_ids}``; the caller
        (api.py) drops the deleted accounts' hub sockets and live notes by those ids and
        answers without them."""
        if self.db.account(account_id) is None:
            raise CloudError(404, "no_account", "No such account")
        reclaimed = self.db.clawback_invite(account_id, note=f"invite abuse ({actor})")
        if disable:
            self.db.set_disabled(account_id, True)
            self.db.add_event(account_id, "account.disabled", f"by {actor} (invite abuse)"[:200])
        deleted_ids: list[str] = []
        if delete_unused:
            while True:
                batch = self.db.unused_invitee_ids(account_id, limit=500)
                if not batch:
                    break
                for invitee_id in batch:
                    self.purge_record(invitee_id)
                    self.db.delete_account(invitee_id)
                    self.db.add_event("", "account.deleted", f"{invitee_id[:8]} by {actor} (invite abuse)"[:200])
                    deleted_ids.append(invitee_id)
        deleted = len(deleted_ids)
        kept = self.db.invitee_count(account_id)
        row = self.db.account(account_id)
        disabled = bool(row is not None and row["disabled"])
        reclaimed_cny = self.s.uy_to_cny(reclaimed)
        detail = (
            f"¥{reclaimed_cny:g} reclaimed"
            + (", disabled" if disable else "")
            + (f", {deleted} unused invitee(s) deleted, {kept} kept" if delete_unused else "")
        )
        self.db.add_event(account_id, "invite.clawback", detail[:200])
        self.db.audit_add(actor, "invite.abuse", account_id[:8], detail)
        log.warning("invite abuse: %s by %s: %s", account_id[:8], actor, detail)
        return {"reclaimed_cny": reclaimed_cny, "disabled": disabled, "deleted": deleted, "kept": kept, "deleted_ids": deleted_ids}

    # the health check's two invite alerts: more sign-ups than this through one code in a
    # day, and inviters this many of whose people (at this share or fewer) ever used anything
    INVITE_VELOCITY_PER_DAY = 10
    INVITE_UNUSED_MIN = 20
    INVITE_UNUSED_SHARE = 0.05

    def invite_alerts(self) -> list[dict]:
        """What the health check says about invites (two aggregates): `invite_velocity`, any
        inviter whose code brought more than ten accounts in the last 24 hours, and
        `invite_unused`, any inviter with at least twenty invitees of whom one in twenty or
        fewer ever made a request. Each carries a plain sentence, the inviters by the start
        of their id and by hint with the counts, and where to look (the Invites view)."""
        out: list[dict] = []
        fast = self.db.invite_velocity(now() - 86400, self.INVITE_VELOCITY_PER_DAY)
        if fast:
            names = ", ".join(f"{r['id'][:8]} ({int(r['n'])})" for r in fast[:5]) + (", …" if len(fast) > 5 else "")
            out.append(
                {
                    "kind": "invite_velocity",
                    "message": f"{len(fast)} inviter(s) brought more than {self.INVITE_VELOCITY_PER_DAY} accounts in the last 24 hours: {names}",
                    "hint": "open the Invites view of the admin page and check who they brought",
                    "inviters": [{"id": r["id"], "hint": r["hint"], "n": int(r["n"])} for r in fast],
                }
            )
        idle = self.db.invite_unused(self.INVITE_UNUSED_MIN, self.INVITE_UNUSED_SHARE)
        if idle:
            names = ", ".join(f"{r['id'][:8]} ({int(r['active'])}/{int(r['n'])})" for r in idle[:5]) + (", …" if len(idle) > 5 else "")
            out.append(
                {
                    "kind": "invite_unused",
                    "message": (
                        f"{len(idle)} inviter(s) with {self.INVITE_UNUSED_MIN} or more invitees of whom "
                        f"{self.INVITE_UNUSED_SHARE:.0%} or fewer ever made a request: {names}"
                    ),
                    "hint": "open the Invites view of the admin page; the abuse action reclaims the credit",
                    "inviters": [{"id": r["id"], "hint": r["hint"], "n": int(r["n"]), "active": int(r["active"])} for r in idle],
                }
            )
        return out

    def ledger_page(
        self,
        account_id: str,
        limit: int = 100,
        before_id: int = 0,
        kinds: tuple[str, ...] | None = None,
        q: str = "",
    ) -> dict:
        """One page of an account's statement, newest first, with the count of the whole
        — the operator's page reads it to the first line, page by page. `kinds` and `q`
        (0.26) are the page's filter; the count is of what matches, so the pager is honest."""
        rows = [self._ledger_row(r) for r in self.db.recent_ledger(account_id, limit, before_id, kinds, q)]
        return {"rows": rows, "total": self.db.ledger_count(account_id, kinds, q)}

    def events_page(
        self,
        account_id: str,
        limit: int = 100,
        before_id: int = 0,
        kinds: tuple[str, ...] | None = None,
        q: str = "",
    ) -> dict:
        rows = []
        for r in self.db.events_for(account_id, limit, before_id, kinds, q):
            d = dict(r)
            d["platform"] = platform_of(d.get("ua") or "")
            rows.append(d)
        return {"rows": rows, "total": self.db.event_count(account_id, kinds, q)}

    def admin_address(self, ip: str) -> dict:
        """One address: the accounts seen from it — for the operator checking whether two
        accounts are one person, or one address is many people."""
        ip = ip.strip()[:64]
        rows = [
            {
                "id": r["id"],
                "hint": r["hint"],
                "channel": r["channel"],
                "created_at": int(r["created_at"]),
                "n": int(r["n"] or 0),
                "last_seen": int(r["last_seen"] or 0),
            }
            for r in self.db.accounts_at_address(ip)
        ]
        return {"ip": ip, "accounts": rows}

    def admin_events(self, limit: int = 200, kinds: tuple[str, ...] | None = None, before_id: int = 0) -> list[dict]:
        rows = self.db.events_recent(max(1, min(limit, 1000)), kinds, max(0, before_id))
        hints, _ = self._labels([r["account_id"] for r in rows if r["account_id"]], decrypt=False)
        out = []
        for r in rows:
            d = dict(r)
            d["hint"] = hints.get(d["account_id"], "") if d["account_id"] else ""
            out.append(d)
        return out

    def _labels(self, ids: list[str], decrypt: bool = True) -> tuple[dict[str, str], dict[str, str]]:
        """`{id: hint}` and `{id: identifier}` for these accounts only (the identifier
        decrypted for the admin token; empty dict when `decrypt` is False). Reading the
        newest N accounts for this used to leave an older account's rows labelled `?`."""
        hints: dict[str, str] = {}
        idents: dict[str, str] = {}
        for r in self.db.accounts_brief(ids):
            hints[r["id"]] = r["hint"]
            if decrypt:
                idents[r["id"]] = self.crypto.decrypt(r["id"], r["identifier_enc"] or "") or ""
        return hints, idents

    def admin_settings(self) -> dict:
        return {
            # 0.15: what the page may change, with the environment's figure beside each
            "runtime": self.runtime_settings(),
            # 0.22: the switches (the Controls page has the rules and the audit log)
            "controls": self.controls.state(),
            "paused": [k for k, v in self.controls.paused().items() if v],
            "repo_url": self.s.repo_url,
            "unlimited": self.s.unlimited,
            "signup_tokens": self.s.signup_tokens,
            "daily_cap_tokens": self.s.daily_cap_tokens,
            "per_minute_requests": self.s.per_minute_requests,
            "signup_open": self.s.signup_open,
            "allowance_cny": self.s.allowance_cny,
            "allowance_usd": self.s.cny_to_usd(self.s.allowance_cny),
            "invite_bonus_cny": self.s.invite_bonus_cny,
            "invitee_bonus_cny": self.s.invite_bonus_cny,
            "contribute_bonus_cny": 0,
            "improve_default": self.s.improve_default,
            "usd_cny": self.s.usd_cny,
            "day_offset_h": self.s.day_offset_h,
            "invite_url": self.s.invite_url,
            "own_key_docs": self.s.own_key_docs,
            "openrouter_url": self.s.openrouter_url,
            "privacy_url": self.s.privacy_url,
            "contributors": self.db.contributors(),
            "allowed_identifiers": [s.strip() for s in self.s.allowed_identifiers.split(",") if s.strip()],
            "sender": self.s.sender,
            "password_min_len": self.s.password_min_len,
            # the per-domain sign-up limit (read-only here; the environment sets it)
            "signup_per_domain_day": self.s.signup_per_domain_day,
            "signup_domain_allow": [s.strip() for s in self.s.signup_domain_allow.split(",") if s.strip()],
            "models": [m.id for m in self.s.models],
            "model_kinds": {m.id: m.kind for m in self.s.models},
            # 0.17: what each chat model is for (chat, gui) and where it is the recommended one
            "model_lanes": {m.id: list(m.lanes) for m in self.s.models},
            "recommended_for": {m.id: list(m.recommended_lanes) for m in self.s.models if m.recommended_lanes},
            "prices": {m.id: m.to_public()["nanomuse"]["price_cny"] for m in self.s.models},
        }

    def admin_disable(self, account_id: str, disabled: bool, actor: str = "console") -> None:
        """Switch an account off (its keys stop opening, no code is sent to it) or back on.
        The account's timeline and the audit log say who did it."""
        if self.db.account(account_id) is None:
            raise CloudError(404, "no_account", "No such account")
        self.db.set_disabled(account_id, disabled)
        kind = "account.disabled" if disabled else "account.enabled"
        self.db.add_event(account_id, kind, f"by {actor}"[:200])
        self.db.audit_add(actor, kind, account_id[:8])

    def admin_unlimited(self, account_id: str, unlimited: bool, actor: str = "console") -> None:
        """Make an account a member (no spend limit) without touching the server's
        environment, the operator's way of letting one more person in fully; or take the
        membership back. The account's timeline and the audit log say who did it."""
        if self.db.account(account_id) is None:
            raise CloudError(404, "no_account", "No such account")
        self.db.set_unlimited(account_id, unlimited)
        kind = "member.set" if unlimited else "member.unset"
        self.db.add_event(account_id, kind, f"by {actor}"[:200])
        self.db.audit_add(actor, kind, account_id[:8])

    def admin_delete(self, account_id: str, actor: str = "console") -> None:
        """The operator removes an account: the same deletion as the person's own request
        (``Database.delete_account``). The account's own timeline goes with it, so the line
        that says so (`account.deleted`, the id's first eight characters and who did it) is
        written across accounts, where the activity page and the statistics read it."""
        if self.db.account(account_id) is None:
            raise CloudError(404, "no_account", "No such account")
        self.purge_record(account_id)
        self.db.delete_account(account_id)
        self.db.add_event("", "account.deleted", f"{account_id[:8]} by {actor}"[:200])
        self.db.audit_add(actor, "account.delete", account_id[:8])


def estimate_tokens(text: str) -> int:
    """When the upstream sends no usage: a rough count, erring high.
    CJK runs at about one token per character, English at about one per four."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk + math.ceil((len(text) - cjk) / 3.5)


def prompt_chars(messages: list) -> int:
    total = 0
    for m in messages or []:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            total += len(c)
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        total += len(part.get("text") or "")
                    elif part.get("type") == "image_url":
                        total += 4000  # one image ≈ a thousand tokens of context
    return total


@dataclass(frozen=True)
class Usage:
    """What a reply says it used: prompt and completion tokens (the reasoning counted as
    completion) and how many of the prompt tokens the provider served from its cache."""

    prompt: int
    completion: int
    cached: int = 0


def usage_from_json(obj: dict) -> Usage | None:
    """The tokens a reply says it used, or None when it says nothing usable (no `usage`, an
    empty one, a count that is not a number) — the caller then estimates. OpenAI's shape has
    the reasoning inside `completion_tokens` with the breakdown under
    `completion_tokens_details.reasoning_tokens` (DashScope's native name is
    `output_tokens_details`); a provider that counts the reasoning *apart* reports more
    reasoning than completion, and then the two are added, so a thinking model's turn is
    never billed for its answer alone. The cached part of the prompt is
    `prompt_tokens_details.cached_tokens` (a part of `prompt_tokens`, as the provider
    reports it); the Anthropic-shaped `cache_read_input_tokens` is counted *beside*
    `input_tokens` and is added to the prompt here."""
    u = obj.get("usage") if isinstance(obj, dict) else None
    if not isinstance(u, dict):
        return None
    try:
        prompt = int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
        completion = int(u.get("completion_tokens") or u.get("output_tokens") or 0)
        reasoning = 0
        for key in ("completion_tokens_details", "output_tokens_details"):
            details = u.get(key)
            if isinstance(details, dict) and details.get("reasoning_tokens") is not None:
                reasoning = max(reasoning, int(details.get("reasoning_tokens") or 0))
        cached = 0
        for key in ("prompt_tokens_details", "input_tokens_details"):
            details = u.get(key)
            if isinstance(details, dict) and details.get("cached_tokens") is not None:
                cached = max(cached, int(details.get("cached_tokens") or 0))
        if u.get("cache_read_input_tokens") is not None:
            read = int(u.get("cache_read_input_tokens") or 0)
            prompt += read
            cached = max(cached, read)
    except (TypeError, ValueError):
        return None
    if prompt <= 0 and completion <= 0:
        return None
    if reasoning > completion:
        completion += reasoning
    return Usage(max(0, prompt), max(0, completion), min(max(0, cached), max(0, prompt)))


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
