"""SQLite storage: accounts, keys, codes, the token ledger.

One file, WAL mode, one connection guarded by a lock — the relay is I/O bound
on the upstream, not on SQLite. Identifiers (phone / e-mail) are stored as
their HMAC (the lookup key), a masked hint for the account page, and — so the
operator can tell who is who — encrypted with a key derived from the
deployment secret (`identifier_enc`, see crypto.py); a copied database file
shows none of them.
"""

from __future__ import annotations

import hmac
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import client as _client
from .catalog import Probe

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            TEXT PRIMARY KEY,
    id_hash       TEXT NOT NULL UNIQUE,
    channel       TEXT NOT NULL,          -- phone | email
    hint          TEXT NOT NULL,          -- 138****1234 / a***@example.com
    created_at    INTEGER NOT NULL,
    granted       INTEGER NOT NULL DEFAULT 0,
    used          INTEGER NOT NULL DEFAULT 0,
    disabled      INTEGER NOT NULL DEFAULT 0,
    identifier_enc TEXT NOT NULL DEFAULT '',  -- AES-GCM of the phone / address, base64
    unlimited     INTEGER NOT NULL DEFAULT 0,  -- a member: no daily money cap (set by the operator)
    password_hash TEXT NOT NULL DEFAULT '',    -- scrypt$salt$hash, empty = no password (codes only)
    password_set_at INTEGER,
    failed_logins INTEGER NOT NULL DEFAULT 0,  -- wrong passwords in a row
    locked_until  INTEGER,                     -- password sign-in refused until then
    invite_code   TEXT NOT NULL DEFAULT '',    -- what this person gives to friends (made on first ask)
    invited_by    TEXT NOT NULL DEFAULT '',    -- the account whose code was used at sign-up
    invites       INTEGER NOT NULL DEFAULT 0,  -- people who signed up with this account's code
    credit_uy     INTEGER NOT NULL DEFAULT 0,  -- 0.4, unused since 0.5 (credit beyond a daily cap)
    credit_used_uy INTEGER NOT NULL DEFAULT 0, -- 0.4, unused since 0.5
    clips_bonus   INTEGER NOT NULL DEFAULT 0,  -- 0.4, unused since 0.5 (clips are not counted apart)
    grant_uy      INTEGER NOT NULL DEFAULT 0,  -- 0.5: the lifetime pool, micro-yuan (allowance + invites + co-creation + operator)
    contribute_bonus_at INTEGER,               -- 0.5: when the one-time co-creation bonus was granted
    invite_settled_at INTEGER                  -- when the invite bonus was paid to both sides (NULL: not yet, paid at the first charged request)
);
-- accounts_invite_code (unique, partial) is made in _migrate(): the column is
-- added there on databases from before 0.4, and an index in this script would
-- run first and fail on them.
CREATE TABLE IF NOT EXISTS api_keys (
    key_hash      TEXT PRIMARY KEY,
    prefix        TEXT NOT NULL,
    account_id    TEXT NOT NULL REFERENCES accounts(id),
    device        TEXT NOT NULL DEFAULT '',
    hub_device_id TEXT NOT NULL DEFAULT '', -- 0.27: the Hub installation this credential owns
    hub_device_kind TEXT NOT NULL DEFAULT '', -- phone | computer | web; empty is a legacy key
    created_at    INTEGER NOT NULL,
    last_used_at  INTEGER,
    revoked_at    INTEGER,
    via           TEXT NOT NULL DEFAULT 'code' -- how this sign-in happened: code | password
);
CREATE INDEX IF NOT EXISTS api_keys_account ON api_keys(account_id);
CREATE TABLE IF NOT EXISTS codes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    id_hash       TEXT NOT NULL,
    code_hash     TEXT NOT NULL,
    ip            TEXT NOT NULL DEFAULT '',
    created_at    INTEGER NOT NULL,
    expires_at    INTEGER NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0,
    used          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS codes_id_hash ON codes(id_hash, created_at);
CREATE INDEX IF NOT EXISTS codes_ip ON codes(ip, created_at);
CREATE TABLE IF NOT EXISTS ledger (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    TEXT NOT NULL REFERENCES accounts(id),
    ts            INTEGER NOT NULL,
    kind          TEXT NOT NULL,          -- grant | chat | image | video | realtime | adjust
    model         TEXT NOT NULL DEFAULT '',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    charged       INTEGER NOT NULL,       -- positive = spent, negative = granted
    request_id    TEXT NOT NULL DEFAULT '',
    cost_uy       INTEGER NOT NULL DEFAULT 0,  -- what the provider bills for it, in micro-yuan
    extra         TEXT NOT NULL DEFAULT ''     -- JSON: the token split of a call (text/audio/image), seconds…
);
CREATE INDEX IF NOT EXISTS ledger_account_ts ON ledger(account_id, ts);
CREATE INDEX IF NOT EXISTS ledger_ts ON ledger(ts);
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    TEXT NOT NULL DEFAULT '',   -- '' for events before an account exists (a failed sign-in)
    ts            INTEGER NOT NULL,
    kind          TEXT NOT NULL,              -- sign_in.code | sign_in.password | sign_in.session | sign_in.failed | sign_out |
                                              -- sign_out.all | password.set | account.created | account.deleted |
                                              -- device.joined | upstream.error | content.rejected | budget.refused | call.ended
    detail        TEXT NOT NULL DEFAULT ''    -- a device name, a model, an error code: never message content
);
CREATE INDEX IF NOT EXISTS events_account_ts ON events(account_id, ts);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
-- the console's timeline filtered by kind, newest first; and "accounts with any X event"
CREATE INDEX IF NOT EXISTS events_kind_id ON events(kind, id);
CREATE TABLE IF NOT EXISTS devices (
    account_id    TEXT NOT NULL REFERENCES accounts(id),
    id            TEXT NOT NULL,           -- chosen by the device, stable across restarts
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL,           -- phone | computer
    os            TEXT NOT NULL DEFAULT '',
    version       TEXT NOT NULL DEFAULT '',
    actions       TEXT NOT NULL DEFAULT '[]',
    first_seen    INTEGER NOT NULL,
    last_seen     INTEGER NOT NULL,
    PRIMARY KEY (account_id, id)
);
CREATE TABLE IF NOT EXISTS video_tasks (
    task_id       TEXT PRIMARY KEY,        -- the provider's id; polled by its owner only
    account_id    TEXT NOT NULL REFERENCES accounts(id),
    model         TEXT NOT NULL DEFAULT '',
    created_at    INTEGER NOT NULL,
    charged       INTEGER NOT NULL DEFAULT 0,  -- set when the task was first seen SUCCEEDED
    cost_uy       INTEGER NOT NULL DEFAULT 0,  -- priced at submission from the seconds asked for
    probe         INTEGER NOT NULL DEFAULT 0,  -- an empty task the app sent to see if the model exists
    status        TEXT NOT NULL DEFAULT '',    -- the provider's last word: SUCCEEDED / FAILED / ...
    checks        INTEGER NOT NULL DEFAULT 0   -- 0.24: times the relay itself asked the provider (settle_video_tasks)
);
-- 0.4: conversations an account chose to contribute (accounts.contribute=1). The only
-- place message content ever lands; empty for everyone else, and deleted with the account
-- or on request.
CREATE TABLE IF NOT EXISTS samples (
    id            TEXT PRIMARY KEY,
    account_id    TEXT NOT NULL REFERENCES accounts(id),
    ts            INTEGER NOT NULL,
    model         TEXT NOT NULL DEFAULT '',
    request       TEXT NOT NULL,               -- the messages sent, as JSON (pictures replaced by a marker)
    response      TEXT NOT NULL DEFAULT '',    -- the assistant's reply text
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    meta          TEXT NOT NULL DEFAULT '{}'   -- platform / language hints from the request headers
);
CREATE INDEX IF NOT EXISTS samples_account ON samples(account_id, ts);
CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);
-- 0.7: the agent's name and look, so every device of an account wears the same one.
-- Never a key or a message: a name, which face (the dragon, an emoji on a colour, or
-- one drawn in the studio) and, for a drawn face, its five stills as WebP.
CREATE TABLE IF NOT EXISTS profiles (
    account_id    TEXT PRIMARY KEY REFERENCES accounts(id),
    rev           INTEGER NOT NULL DEFAULT 0,  -- grows with every PUT; devices compare it
    updated_at    INTEGER NOT NULL,
    device        TEXT NOT NULL DEFAULT '',    -- the device that wrote it (it skips its own echo)
    body          TEXT NOT NULL DEFAULT '{}',  -- name, avatar, emoji, color, style, description
    face          TEXT NOT NULL DEFAULT '',    -- JSON {mood: base64 WebP} when avatar = "face"
    connectors    TEXT NOT NULL DEFAULT '[]'   -- 0.17: which device connected which service (never a credential)
);
-- 0.11: what each chat model under the operator's key answered when asked (catalog.py):
-- whether it answers at all, whether it saw the magenta square. Operator data, no person's.
CREATE TABLE IF NOT EXISTS model_probes (
    model_id      TEXT PRIMARY KEY,
    works         INTEGER NOT NULL,            -- 0: the provider refused the one-word request (4xx)
    vision        INTEGER NOT NULL,            -- 1: it named the colour of the picture
    checked_at    INTEGER NOT NULL,
    note          TEXT NOT NULL DEFAULT ''     -- the refusal, or the answer, trimmed
);
-- 0.15: what the operator set from the page while the relay ran — the allowance, the
-- invite bonus, whether sign-up is open. A key here wins over the environment; a key
-- removed falls back to it. Read at start and on every change; nothing else lives here.
CREATE TABLE IF NOT EXISTS settings (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL,               -- JSON
    updated_at    INTEGER NOT NULL
);
-- 0.19: the text of an account's conversations, so every device of it shows the same
-- chats (sync.py). Only user and assistant texts and attachment names; never a file or a
-- picture. Deleted with the account, on request, or when the person turns sync off.
CREATE TABLE IF NOT EXISTS sync_conversations (
    account_id    TEXT NOT NULL REFERENCES accounts(id),
    cid           TEXT NOT NULL,              -- minted by the device that started it
    kind          TEXT NOT NULL,              -- main | side (one main per account)
    title         TEXT NOT NULL DEFAULT '',
    device        TEXT NOT NULL DEFAULT '',   -- the device that started it (devices.id)
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    deleted       INTEGER NOT NULL DEFAULT 0,
    deleted_at    INTEGER,                    -- tombstones are swept after 30 days
    seq           INTEGER NOT NULL,           -- the account's change counter when last written
    PRIMARY KEY (account_id, cid)
);
CREATE INDEX IF NOT EXISTS sync_conversations_seq ON sync_conversations(account_id, seq);
-- the sweep on every push looks only at tombstones; without this it reads the table
CREATE INDEX IF NOT EXISTS sync_conversations_tombstones ON sync_conversations(deleted_at) WHERE deleted=1;
CREATE TABLE IF NOT EXISTS sync_messages (
    account_id    TEXT NOT NULL REFERENCES accounts(id),
    mid           TEXT NOT NULL,              -- minted by the device that wrote it
    cid           TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    device        TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL,              -- user | assistant
    text          TEXT NOT NULL DEFAULT '',
    truncated     INTEGER NOT NULL DEFAULT 0, -- cut at 16 KB
    attachments   TEXT NOT NULL DEFAULT '[]', -- JSON [{name, mime, size}] — names and sizes only
    created_at    INTEGER NOT NULL,
    deleted       INTEGER NOT NULL DEFAULT 0,
    deleted_at    INTEGER,
    PRIMARY KEY (account_id, mid)
);
CREATE INDEX IF NOT EXISTS sync_messages_seq ON sync_messages(account_id, seq);
CREATE INDEX IF NOT EXISTS sync_messages_cid ON sync_messages(account_id, cid);
CREATE INDEX IF NOT EXISTS sync_messages_tombstones ON sync_messages(deleted_at) WHERE deleted=1;
CREATE TABLE IF NOT EXISTS sync_cursors (
    account_id    TEXT PRIMARY KEY REFERENCES accounts(id),
    seq           INTEGER NOT NULL DEFAULT 0  -- one counter per account; cursor = its value
);
-- 0.22: one number per UTC day, metric and key — the GitHub snapshots the collector takes
-- (stars, forks, watchers, downloads per asset), the relay's own daily counters (API calls
-- by group, accounts active by any call, errors by code, sync volume). Counters survive a
-- restart because they live here and nowhere else (stats.py, github_stats.py).
CREATE TABLE IF NOT EXISTS daily (
    day           INTEGER NOT NULL,           -- the UNIX time the UTC day starts
    metric        TEXT NOT NULL,              -- gh.stars | gh.downloads | api | active | error | sync …
    key           TEXT NOT NULL DEFAULT '',   -- an asset name, a route group, an account id, an error code
    value         INTEGER NOT NULL DEFAULT 0,
    updated_at    INTEGER NOT NULL,
    PRIMARY KEY (day, metric, key)
);
CREATE INDEX IF NOT EXISTS daily_metric_day ON daily(metric, day);
-- 0.22: the operator's switches (controls.py): free allowance, sign-ups, the service, sync,
-- the hub. A row is written when a switch is flipped; no row = on. Read into memory at
-- start; every change goes through the API so the running relay applies it at once.
CREATE TABLE IF NOT EXISTS controls (
    key           TEXT PRIMARY KEY,
    enabled       INTEGER NOT NULL DEFAULT 1,
    updated_at    INTEGER NOT NULL,
    actor         TEXT NOT NULL DEFAULT '',   -- console | cli | rule:<id> | …
    note          TEXT NOT NULL DEFAULT ''
);
-- 0.22: "when the number of accounts reaches N, do X" — several rules, each fires once
-- (last_fired_at set) until the operator re-arms it.
CREATE TABLE IF NOT EXISTS control_rules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    threshold     INTEGER NOT NULL,
    action        TEXT NOT NULL,              -- close_signups | pause_allowance | pause_sync | notify
    enabled       INTEGER NOT NULL DEFAULT 1,
    note          TEXT NOT NULL DEFAULT '',
    created_at    INTEGER NOT NULL,
    last_fired_at INTEGER,
    fired_accounts INTEGER                    -- the count that tripped it
);
-- 0.22: who flipped what, when — the controls page shows it. Never an identifier.
CREATE TABLE IF NOT EXISTS control_audit (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            INTEGER NOT NULL,
    actor         TEXT NOT NULL DEFAULT '',
    ip            TEXT NOT NULL DEFAULT '',
    action        TEXT NOT NULL,              -- switch | rule.add | rule.update | rule.delete | rule.fired | notify
    target        TEXT NOT NULL DEFAULT '',   -- the switch's key or the rule's id
    detail        TEXT NOT NULL DEFAULT ''
);
-- 0.1.40: the hashes of the keys a deleted account had, for DELETED_KEYS_TTL_S, so a device
-- that still holds one hears `account_deleted` rather than `bad_key` and knows there is
-- nothing to come back to. A hash of a dead key names nobody; no account id is kept with it.
CREATE TABLE IF NOT EXISTS deleted_keys (
    key_hash      TEXT PRIMARY KEY,
    deleted_at    INTEGER NOT NULL
);
-- 0.28: one row per chat request the relay handled (analytics.py): how long it queued for a
-- provider slot, how long the provider took to the first token and to the end, how it
-- ended, what shape the request had (messages, pictures, tools) — never a word of it. The
-- console's live page and the usage drill-downs read this; rows older than CALLS_KEEP_DAYS
-- are swept. A refusal the relay made itself (over budget, too many in flight) is a row
-- too, so demand can be told from what was served.
CREATE TABLE IF NOT EXISTS calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            INTEGER NOT NULL,              -- when the request arrived
    account_id    TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    platform      TEXT NOT NULL DEFAULT '',      -- client.platform_of
    family        TEXT NOT NULL DEFAULT '',      -- client.ua_family
    status        TEXT NOT NULL,                 -- ok | upstream_error | upstream_timeout | content_rejected | broken | refused | client_gone
    detail        TEXT NOT NULL DEFAULT '',      -- the provider's status, the refusal's code, the exception's name
    stream        INTEGER NOT NULL DEFAULT 0,
    wait_ms       INTEGER NOT NULL DEFAULT 0,    -- queued for a provider slot
    ttft_ms       INTEGER NOT NULL DEFAULT 0,    -- slot taken → first token (a stream) or the whole reply
    total_ms      INTEGER NOT NULL DEFAULT 0,    -- arrival → done
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,    -- 0.31: of the prompt, served from the provider's cache
    messages      INTEGER NOT NULL DEFAULT 0,    -- messages in the request
    images        INTEGER NOT NULL DEFAULT 0,    -- pictures in the request
    tools         INTEGER NOT NULL DEFAULT 0,    -- tool definitions the client offered
    tool_names    TEXT NOT NULL DEFAULT '',      -- the tools the reply called, names only, comma-joined
    hands         INTEGER NOT NULL DEFAULT 0,    -- a screen-operation turn: the operator's tools offered or called
    retries       INTEGER NOT NULL DEFAULT 0,
    request_id    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS calls_ts ON calls(ts);
CREATE INDEX IF NOT EXISTS calls_account_ts ON calls(account_id, ts);
-- 0.28: the shape of every kept turn (samples), one small row each, so the data quality
-- page never reads the turns themselves: how many messages, how long the person's last
-- message and the reply were, whether tools were called, pictures sent, the operator used,
-- and a hash of the person's message for finding repeats. Written with the turn; older
-- turns are filled in by the backfill task after start. Deleted with the turn.
CREATE TABLE IF NOT EXISTS sample_stats (
    sample_id     TEXT PRIMARY KEY,
    account_id    TEXT NOT NULL,
    ts            INTEGER NOT NULL,
    model         TEXT NOT NULL DEFAULT '',
    platform      TEXT NOT NULL DEFAULT '',
    messages      INTEGER NOT NULL DEFAULT 0,
    user_chars    INTEGER NOT NULL DEFAULT 0,    -- the person's last message
    reply_chars   INTEGER NOT NULL DEFAULT 0,
    tool_calls    INTEGER NOT NULL DEFAULT 0,
    pictures      INTEGER NOT NULL DEFAULT 0,
    hands         INTEGER NOT NULL DEFAULT 0,
    trivial       INTEGER NOT NULL DEFAULT 0,    -- a greeting, a test, one word: nothing to learn from
    user_hash     TEXT NOT NULL DEFAULT '',      -- of the person's last message, normalised
    bytes         INTEGER NOT NULL DEFAULT 0,    -- request + response, as stored
    prompt_tokens INTEGER NOT NULL DEFAULT -1,   -- 0.30: the turn's usage, as `samples` has it; -1 = not copied yet
    completion_tokens INTEGER NOT NULL DEFAULT -1
);
CREATE INDEX IF NOT EXISTS sample_stats_account ON sample_stats(account_id, ts);
CREATE INDEX IF NOT EXISTS sample_stats_ts ON sample_stats(ts);
CREATE INDEX IF NOT EXISTS sample_stats_hash ON sample_stats(user_hash);
-- 0.29: the record (record.py) — every chat turn the relay answered, in full: the request as
-- the app sent it (the system prompt, the tools' results, every message; pictures, audio and
-- clips as blob:sha256 references into `blobs`) and the answer as the model gave it. A turn
-- a client ran on a key of its own and sent up afterwards (POST /v1/turns) is a row too,
-- with source 'own'. The person's own data: read back by their devices, deleted from Data
-- controls or with the account, swept after RECORD_KEEP_DAYS when the operator set one.
CREATE TABLE IF NOT EXISTS turns (
    id            TEXT PRIMARY KEY,            -- the request id the app saw (x-nanomuse-request)
    account_id    TEXT NOT NULL,
    ts            INTEGER NOT NULL,
    model         TEXT NOT NULL DEFAULT '',
    platform      TEXT NOT NULL DEFAULT '',    -- client.platform_of
    device        TEXT NOT NULL DEFAULT '',    -- X-NanoMuse-Device when the app sent one
    conversation  TEXT NOT NULL DEFAULT '',    -- X-NanoMuse-Conversation when the app sent one
    source        TEXT NOT NULL DEFAULT 'cloud', -- cloud | own
    status        TEXT NOT NULL DEFAULT 'ok',  -- ok | partial (the stream broke off; what arrived is kept)
    request       BLOB NOT NULL,               -- record.pack: the request body, media detached
    response      BLOB NOT NULL,               -- record.pack: {message, usage, finish_reason}
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,  -- 0.31: of the prompt, from the provider's cache (0 before)
    media         INTEGER NOT NULL DEFAULT 0,  -- distinct pictures / clips referenced
    media_bytes   INTEGER NOT NULL DEFAULT 0,
    meta          TEXT NOT NULL DEFAULT '{}'   -- ua, lang, ip, provider (own), media [{sha256, mime, bytes}]
);
CREATE INDEX IF NOT EXISTS turns_account ON turns(account_id, ts);
CREATE INDEX IF NOT EXISTS turns_ts ON turns(ts);
CREATE INDEX IF NOT EXISTS turns_conversation ON turns(account_id, conversation, ts);
-- 0.31.1: the figures of a turn run on a key of the person's own (source 'own'), one small
-- row each, so the Usage page's table by provider and model never reads the turns
-- themselves: the provider sits in `meta` and the cached count in a column added after the
-- bodies, and summing them over a week of turns walked every body (a 40 GB file took
-- minutes a call and held the console's reads behind it). Written with the turn; older own
-- turns are filled in by the backfill after start. Deleted with the turn.
CREATE TABLE IF NOT EXISTS own_figures (
    turn_id       TEXT PRIMARY KEY,
    account_id    TEXT NOT NULL,
    ts            INTEGER NOT NULL,
    provider      TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS own_figures_ts ON own_figures(ts);
CREATE INDEX IF NOT EXISTS own_figures_account ON own_figures(account_id);
-- 0.29: the files under MEDIA_DIR, one row each, and who may read which. A file is
-- removed when its last reference goes (the account deleted its record) or when the
-- store is over MEDIA_MAX_GB, oldest use first; the turn then keeps a reference to nothing.
CREATE TABLE IF NOT EXISTS blobs (
    sha256        TEXT PRIMARY KEY,
    mime          TEXT NOT NULL DEFAULT '',
    bytes         INTEGER NOT NULL,
    created_at    INTEGER NOT NULL,
    last_used_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS blobs_used ON blobs(last_used_at);
CREATE TABLE IF NOT EXISTS blob_refs (
    sha256        TEXT NOT NULL,
    account_id    TEXT NOT NULL,
    owner         TEXT NOT NULL,                -- turn | profile | upload: one row per account and kind,
                                                -- however many turns name the file (the turn's meta lists its own)
    PRIMARY KEY (sha256, account_id, owner)
);
CREATE INDEX IF NOT EXISTS blob_refs_account ON blob_refs(account_id, sha256);
-- 0.31: what the apps report around a turn (provenance.py, docs/cloud.md "Client events"):
-- the Sentinel's decision on a tool call, an approval's result, why a reply was stopped, a
-- thumb up or down. Codes and numbers only, never a message; tied to the turn's id when the
-- app knows it. Deleted with the account and with Data controls' delete, like the turns.
CREATE TABLE IF NOT EXISTS client_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    TEXT NOT NULL,
    ts            INTEGER NOT NULL,              -- when it happened, as the app says; else arrival
    device        TEXT NOT NULL DEFAULT '',      -- X-NanoMuse-Device
    platform      TEXT NOT NULL DEFAULT '',
    kind          TEXT NOT NULL,                 -- sentinel.decision | approval.result | turn.stopped | turn.feedback | …
    turn_id       TEXT NOT NULL DEFAULT '',      -- the record's id for the turn (x-nanomuse-request, or an own-… id)
    conversation  TEXT NOT NULL DEFAULT '',
    data          TEXT NOT NULL DEFAULT '{}'     -- a flat JSON object of codes, numbers and booleans
);
CREATE INDEX IF NOT EXISTS client_events_account ON client_events(account_id, ts);
CREATE INDEX IF NOT EXISTS client_events_ts ON client_events(ts);
CREATE INDEX IF NOT EXISTS client_events_turn ON client_events(turn_id) WHERE turn_id<>'';
-- 0.31: the deletions ledger (docs/cloud.md "Deletions"): when an account deletes what the
-- relay kept of it, or the account itself, the export's pseudonym for it (provenance.subject_of)
-- is written here with the time, so a training set built from an earlier export can drop that
-- subject's lines. The pseudonym names nobody without the relay's secret; the row outlives
-- the account on purpose, and is all that does.
CREATE TABLE IF NOT EXISTS deletions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject       TEXT NOT NULL,
    ts            INTEGER NOT NULL,
    scope         TEXT NOT NULL                  -- samples (Data controls' delete) | account
);
CREATE INDEX IF NOT EXISTS deletions_ts ON deletions(ts);
"""

# How long a deleted account's key hashes are remembered. Long enough for every device of the
# account to come back online and hear the answer; short enough that a deletion is a deletion.
DELETED_KEYS_TTL_S = 90 * 24 * 3600

# What `invited_by` says once the inviter's account is deleted and the bonus was still unpaid:
# the invitee was invited (its own half is still due) but by nobody that can be named.
INVITER_GONE = "deleted"

# How long a write waits for another process's lock on the file before it fails (sqlite3's
# `timeout` and PRAGMA busy_timeout). Five seconds covers a backup's read transaction or a
# checkpoint; a request held longer than that is better refused than queued for good.
BUSY_TIMEOUT_S = 5.0

# How many entries of each index `PRAGMA optimize` may read for its statistics (see optimize()).
ANALYSIS_LIMIT = 1000

# How many rows the turn-key backfill writes per transaction (set_turn_keys): a turn's row is
# rewritten whole, some hundred kilobytes with its request, so this many is a few megabytes
# and the lock is held for a moment, not for a page.
KEY_ROWS_PER_TX = 25

# The per-account figures the invite views join in, requests made and money spent, in one
# pass over the ledger (the same set of kinds as admin_accounts counts). For every account at
# once (the ranking); a view of one inviter's people uses USAGE_OF_ACCOUNT instead, a lookup
# per invitee over the ledger's (account_id, ts) index, since this pass costs most of a second
# on a ledger of half a million lines and a page used to run it once per inviter listed.
USAGE_BY_ACCOUNT = """(SELECT account_id,
                              SUM(CASE WHEN kind IN ('chat','image','video','realtime') THEN 1 ELSE 0 END) AS requests,
                              SUM(CASE WHEN cost_uy>0 THEN cost_uy ELSE 0 END) AS spent_uy
                       FROM ledger GROUP BY account_id)"""
USAGE_OF_ACCOUNT = """(SELECT COALESCE(SUM(CASE WHEN kind IN ('chat','image','video','realtime') THEN 1 ELSE 0 END), 0) FROM ledger WHERE account_id=i.id) AS requests,
                      (SELECT COALESCE(SUM(CASE WHEN cost_uy>0 THEN cost_uy ELSE 0 END), 0) FROM ledger WHERE account_id=i.id) AS spent_uy"""


def utc_day(ts: int) -> int:
    """The UNIX time the UTC day of `ts` starts — the key of the `daily` table."""
    return ts - ts % 86400


def now() -> int:
    return int(time.time())


def _like(text: str) -> str:
    """`text` as a LIKE pattern that matches it anywhere, its own wildcards escaped (ESCAPE '\\')."""
    t = text.strip()[:80].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{t}%"


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # One connection behind one lock serialises the relay's own writes; the busy timeout
        # is for the other writers that open the same file (a backup taken with the backup
        # API, the admin CLI, a checkpoint by another process). Python's `timeout` already
        # defaults to five seconds; the SQLite library's own default is 0, so the PRAGMA
        # below says the same figure in one place for both, and a change here is the whole
        # change.
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=BUSY_TIMEOUT_S)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._reader: Database | None = None
        self.read_only = False
        # columns this open added to an older file ("accounts.grant_uy"): the service seeds
        # what a column's default cannot know (see seed_grants)
        self.added: set[str] = set()
        with self._lock:
            # executescript commits on its own; keep it outside tx().
            self._conn.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_S * 1000)}")
            self._conn.execute("PRAGMA journal_mode=WAL")
            # WAL with NORMAL: durable against a process crash, and an fsync per checkpoint
            # instead of per commit (the default FULL costs one per commit). A power cut
            # may lose the last commits, never the file's consistency.
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            # what `optimize()` lets ANALYZE read of each index, so the planner's statistics
            # cost milliseconds under the lock, never a pass over a table
            self._conn.execute(f"PRAGMA analysis_limit={ANALYSIS_LIMIT}")
            self._conn.executescript(SCHEMA)
            self._migrate()

    def reader(self) -> Database:
        """The same file for the long reads that run off the event loop: the console's pages,
        the analytics, the exports, the backfills' page reads. A second connection, read-only,
        behind a lock of its own, so a query that takes seconds never holds `_lock` and the
        requests behind it (every handler takes that lock for its own few rows). WAL gives it
        a consistent snapshot while the first connection writes; a write through it fails
        with "attempt to write a readonly database", which is the point. An in-memory
        database (the tests) has one connection to share, so there it is the database itself."""
        if self.path == ":memory:":
            return self
        if self._reader is None:
            r = Database.__new__(Database)
            r.path = self.path
            uri = Path(self.path).resolve().as_uri() + "?mode=ro"  # as_uri() escapes what a path may hold
            r._conn = sqlite3.connect(uri, uri=True, check_same_thread=False, isolation_level=None, timeout=BUSY_TIMEOUT_S)
            r._conn.row_factory = sqlite3.Row
            r._conn.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_S * 1000)}")
            r._lock = threading.RLock()
            r._reader = r
            r.read_only = True
            r.added = set()
            self._reader = r
        return self._reader

    def optimize(self) -> None:
        """`PRAGMA optimize`: statistics for the planner on the tables this connection has
        queried and that have none yet (or grew far past them), each from at most
        ANALYSIS_LIMIT index entries. Without them the planner guessed, and on a large file
        it chose a pass over the whole of an index where a range of a few hundred rows was
        there (events by kind for the last hour, say). The analytics loop runs it once an hour."""
        with self._lock:
            self._conn.execute("PRAGMA optimize")

    def _migrate(self) -> None:
        """Columns added after the first release; CREATE TABLE IF NOT EXISTS leaves old files alone."""

        def cols(table: str) -> set[str]:
            return {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}

        def add(table: str, col: str, ddl: str) -> None:
            if col not in cols(table):
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                self.added.add(f"{table}.{col}")

        if "identifier_enc" not in cols("accounts"):
            self._conn.execute("ALTER TABLE accounts ADD COLUMN identifier_enc TEXT NOT NULL DEFAULT ''")
        if "unlimited" not in cols("accounts"):
            self._conn.execute("ALTER TABLE accounts ADD COLUMN unlimited INTEGER NOT NULL DEFAULT 0")
        if "charged" not in cols("video_tasks"):
            self._conn.execute("ALTER TABLE video_tasks ADD COLUMN charged INTEGER NOT NULL DEFAULT 0")
        if "cost_uy" not in cols("video_tasks"):
            self._conn.execute("ALTER TABLE video_tasks ADD COLUMN cost_uy INTEGER NOT NULL DEFAULT 0")
        if "cost_uy" not in cols("ledger"):
            self._conn.execute("ALTER TABLE ledger ADD COLUMN cost_uy INTEGER NOT NULL DEFAULT 0")
        if "expires_at" not in cols("api_keys"):
            # 0.13: a session key (nanoMuse Web's containers) stops working at this time
            self._conn.execute("ALTER TABLE api_keys ADD COLUMN expires_at INTEGER")
        if "extra" not in cols("ledger"):
            self._conn.execute("ALTER TABLE ledger ADD COLUMN extra TEXT NOT NULL DEFAULT ''")
        for col, ddl in (
            ("password_hash", "TEXT NOT NULL DEFAULT ''"),
            ("password_set_at", "INTEGER"),
            ("failed_logins", "INTEGER NOT NULL DEFAULT 0"),
            ("locked_until", "INTEGER"),
        ):
            if col not in cols("accounts"):
                self._conn.execute(f"ALTER TABLE accounts ADD COLUMN {col} {ddl}")
        if "via" not in cols("api_keys"):
            self._conn.execute("ALTER TABLE api_keys ADD COLUMN via TEXT NOT NULL DEFAULT 'code'")
        # 0.27: a Hub credential owns one installation identity. Empty rows are keys
        # issued by an older relay (or by an old client during the one-release migration);
        # their first accepted hello fills both columns atomically. Only live keys hold
        # an identity: a revoked one keeps its row for the sign-ins list and nothing more.
        add("api_keys", "hub_device_id", "TEXT NOT NULL DEFAULT ''")
        add("api_keys", "hub_device_kind", "TEXT NOT NULL DEFAULT ''")
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS api_keys_hub_device ON api_keys(account_id, hub_device_id) "
            "WHERE hub_device_id<>'' AND revoked_at IS NULL"
        )
        # 0.4: invitations, credit and the clip allowance
        for col, ddl in (
            ("invite_code", "TEXT NOT NULL DEFAULT ''"),
            ("invited_by", "TEXT NOT NULL DEFAULT ''"),
            ("invites", "INTEGER NOT NULL DEFAULT 0"),
            ("credit_uy", "INTEGER NOT NULL DEFAULT 0"),
            ("credit_used_uy", "INTEGER NOT NULL DEFAULT 0"),
            ("clips_bonus", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in cols("accounts"):
                self._conn.execute(f"ALTER TABLE accounts ADD COLUMN {col} {ddl}")
        self._conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS accounts_invite_code ON accounts(invite_code) WHERE invite_code<>''")
        for col, ddl in (
            ("probe", "INTEGER NOT NULL DEFAULT 0"),
            ("status", "TEXT NOT NULL DEFAULT ''"),
            ("checks", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in cols("video_tasks"):
                self._conn.execute(f"ALTER TABLE video_tasks ADD COLUMN {col} {ddl}")
        if "contribute" not in cols("accounts"):
            self._conn.execute("ALTER TABLE accounts ADD COLUMN contribute INTEGER NOT NULL DEFAULT 0")
        # 0.5: one lifetime pool instead of a daily cap; the co-creation bonus, once
        add("accounts", "grant_uy", "INTEGER NOT NULL DEFAULT 0")
        add("accounts", "contribute_bonus_at", "INTEGER")
        # 0.10: the address and the client software behind sign-ins, requests, events and
        # devices (client.py) — the operator's page reads them; nothing else does
        for col, ddl in (
            ("first_ip", "TEXT NOT NULL DEFAULT ''"),
            ("last_ip", "TEXT NOT NULL DEFAULT ''"),
            ("last_ua", "TEXT NOT NULL DEFAULT ''"),
            ("last_seen_at", "INTEGER"),
        ):
            add("accounts", col, ddl)
        for table in ("api_keys", "events", "ledger"):
            add(table, "ip", "TEXT NOT NULL DEFAULT ''")
            add(table, "ua", "TEXT NOT NULL DEFAULT ''")
        add("devices", "ip", "TEXT NOT NULL DEFAULT ''")
        self._conn.execute("CREATE INDEX IF NOT EXISTS ledger_ip ON ledger(ip) WHERE ip<>''")
        self._conn.execute("CREATE INDEX IF NOT EXISTS api_keys_ip ON api_keys(ip) WHERE ip<>''")
        # events is the largest of the three and accounts_at_address reads it by ip as well
        self._conn.execute("CREATE INDEX IF NOT EXISTS events_ip ON events(ip) WHERE ip<>''")
        # 0.15: the allowance each account was given (the part of grant_uy that is neither
        # an invite nor the operator's credit), so a raised allowance can be applied to the
        # accounts that got less. -1 = from before the column; the service fills it with
        # the allowance of the day (seed_allowances), the one they got for all we know.
        add("accounts", "allowance_uy", "INTEGER NOT NULL DEFAULT -1")
        # 0.17: the connectors each device of the account holds — a label and a sign-in kind
        # per service, never a credential — merged by the device that wrote them
        add("profiles", "connectors", "TEXT NOT NULL DEFAULT '[]'")
        # 0.19: conversation sync is on unless the person turned it off (sync.py)
        add("accounts", "sync_enabled", "INTEGER NOT NULL DEFAULT 1")
        # the invite bonus is paid at the invitee's first charged request, not at sign-up;
        # the column says when. Every invited account from before was paid at sign-up, so
        # it is marked settled once, when the column is added, and nobody is paid twice.
        add("accounts", "invite_settled_at", "INTEGER")
        if "accounts.invite_settled_at" in self.added:
            self._conn.execute("UPDATE accounts SET invite_settled_at=created_at WHERE invited_by<>'' AND invite_settled_at IS NULL")
        # who an account brought (invitees, the ranking, the health check's two invite
        # aggregates) and the sign-ups of the last day (the per-domain limit), without a scan
        self._conn.execute("CREATE INDEX IF NOT EXISTS accounts_invited_by ON accounts(invited_by) WHERE invited_by<>''")
        self._conn.execute("CREATE INDEX IF NOT EXISTS accounts_created_at ON accounts(created_at)")
        # 0.28: the model a device runs under a key of its own, as its hub hello may say
        # (docs/hub.md: `device.llm`); a provider id and a model id, never a key
        add("devices", "llm_provider", "TEXT NOT NULL DEFAULT ''")
        add("devices", "llm_model", "TEXT NOT NULL DEFAULT ''")
        # 0.30: the turn's tokens beside its shape, so the Data view sums them here and never
        # over `samples` (whose rows carry the conversation: a sum there read the whole table,
        # minutes on a file of tens of gigabytes). Older rows are filled in by the analytics
        # loop a page at a time (Analytics.tokens_step); -1 marks one not filled in yet.
        add("sample_stats", "prompt_tokens", "INTEGER NOT NULL DEFAULT -1")
        add("sample_stats", "completion_tokens", "INTEGER NOT NULL DEFAULT -1")
        # 0.31: how much of a prompt the provider served from its cache, beside the call's
        # tokens and the turn's, so the Usage page says how well the cache works for the
        # hosted models and for the keys people use themselves. Older rows read 0 (the
        # ledger's `extra` has the hosted figure back to the first version that billed it).
        add("calls", "cached_tokens", "INTEGER NOT NULL DEFAULT 0")
        add("turns", "cached_tokens", "INTEGER NOT NULL DEFAULT 0")
        # 0.31: where a turn came from (provenance.py): who started it (`run`: person,
        # schedule, feed, goal, hub; "" for an app from before the header), its turn and
        # step in the conversation, the screen-operation task and step it belongs to, and
        # the script of what the person wrote. The call's row says who started it too; the
        # training view's shape carries the same, its source (cloud or own key) and the
        # record's id for the turn, so feedback and the Sentinel's decisions join it.
        for col, ddl in (
            ("run", "TEXT NOT NULL DEFAULT ''"),
            ("turn_no", "INTEGER NOT NULL DEFAULT 0"),
            ("step", "INTEGER NOT NULL DEFAULT 0"),
            ("trajectory", "TEXT NOT NULL DEFAULT ''"),
            ("trajectory_step", "INTEGER NOT NULL DEFAULT 0"),
            ("script", "TEXT NOT NULL DEFAULT ''"),
        ):
            add("turns", col, ddl)
        add("calls", "run", "TEXT NOT NULL DEFAULT ''")
        for col, ddl in (
            ("run", "TEXT NOT NULL DEFAULT ''"),
            ("source", "TEXT NOT NULL DEFAULT ''"),
            ("turn_id", "TEXT NOT NULL DEFAULT ''"),
        ):
            add("sample_stats", col, ddl)
        self._conn.execute("CREATE INDEX IF NOT EXISTS sample_stats_turn ON sample_stats(turn_id) WHERE turn_id<>''")
        self._conn.execute("CREATE INDEX IF NOT EXISTS turns_trajectory ON turns(account_id, trajectory, ts) WHERE trajectory<>''")
        # 0.31: one question, many calls (provenance.turn_start). `turn_start` is 1 for the
        # row that opens a turn, 0 for one that continues it, -1 until the backfill has read
        # the row; `turn_key` is the id of the row that opened the turn (its own, for the
        # opener), so the rows of one question group and the figures count turns as well as
        # calls. The training view's shape gets the same, and the conversation its turn's
        # key is looked up in.
        for col, ddl in (("turn_start", "INTEGER NOT NULL DEFAULT -1"), ("turn_key", "TEXT NOT NULL DEFAULT ''")):
            add("turns", col, ddl)
            add("sample_stats", col, ddl)
        add("sample_stats", "conversation", "TEXT NOT NULL DEFAULT ''")
        add("sample_stats", "turn_no", "INTEGER NOT NULL DEFAULT 0")
        self._conn.execute("CREATE INDEX IF NOT EXISTS turns_key ON turns(turn_key) WHERE turn_key<>''")
        self._conn.execute("CREATE INDEX IF NOT EXISTS sample_stats_key ON sample_stats(turn_key) WHERE turn_key<>''")
        self._conn.execute("CREATE INDEX IF NOT EXISTS sample_stats_conversation ON sample_stats(account_id, conversation, ts)")
        # 0.31: the record's figures beside its rows, never through them. A turn's row carries
        # its request (tens to hundreds of kilobytes), and the columns the figures sum —
        # `media`, the tokens, `turn_start` — come after it, so reading one of them walks
        # the body's overflow pages: a sum over a week of turns read gigabytes (half a
        # minute on a 30 GB file, more with the cache cold). This index holds what the
        # figures and the question-by-question view read and filter on, a few hundred
        # bytes a row; their queries name it (INDEXED BY) so the planner never trades it
        # for the key or account index and a look-up per row.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS turns_figures ON turns(ts, account_id, turn_start, turn_key, media, media_bytes, "
            "source, status, prompt_tokens, completion_tokens, trajectory, conversation, script, platform, run, model)"
        )

    # -- 0.15: settings the operator changes while the relay runs ------------------------------

    def settings_all(self) -> dict[str, Any]:
        """Every override the page set, decoded; empty when the environment is all there is."""
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        out: dict[str, Any] = {}
        for r in rows:
            try:
                out[r["key"]] = json.loads(r["value"])
            except ValueError:
                continue
        return out

    def settings_get(self, key: str) -> tuple[Any, int] | None:
        """One stored setting with when it was written (``(value, updated_at)``), or None
        when nothing is stored under the key or the row does not parse."""
        with self._lock:
            row = self._conn.execute("SELECT value, updated_at FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["value"]), int(row["updated_at"])
        except (ValueError, TypeError):
            return None

    def settings_put(self, key: str, value: Any) -> None:
        """Set an override, or remove it (value None) so the environment's value is back."""
        with self.tx() as c:
            if value is None:
                c.execute("DELETE FROM settings WHERE key=?", (key,))
            else:
                c.execute(
                    "INSERT INTO settings(key, value, updated_at) VALUES (?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, json.dumps(value), now()),
                )

    # -- 0.22: one number per UTC day, metric and key (stats.py, github_stats.py) ---------------

    def daily_add(self, metric: str, key: str, n: int = 1, ts: int | None = None) -> None:
        """Add `n` to the day's counter — an API call, an error, a sync push."""
        t = now() if ts is None else ts
        with self.tx() as c:
            c.execute(
                "INSERT INTO daily(day, metric, key, value, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(day, metric, key) DO UPDATE SET value=value+excluded.value, updated_at=excluded.updated_at",
                (utc_day(t), metric, key or "", int(n), t),
            )

    def daily_set(self, day: int, metric: str, key: str, value: int, ts: int | None = None) -> None:
        """Set the day's figure — a snapshot (stars as of today), replacing an earlier one."""
        t = now() if ts is None else ts
        with self.tx() as c:
            c.execute(
                "INSERT INTO daily(day, metric, key, value, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(day, metric, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (utc_day(day), metric, key or "", int(value), t),
            )

    def daily_rows(self, metric: str, since: int = 0, key: str | None = None) -> list[sqlite3.Row]:
        """Every (day, key, value) of one metric since `since`, oldest first."""
        with self._lock:
            if key is None:
                return self._conn.execute(
                    "SELECT day, key, value, updated_at FROM daily WHERE metric=? AND day>=? ORDER BY day, key", (metric, since)
                ).fetchall()
            return self._conn.execute(
                "SELECT day, key, value, updated_at FROM daily WHERE metric=? AND key=? AND day>=? ORDER BY day", (metric, key, since)
            ).fetchall()

    def daily_distinct(self, metric: str, since: int = 0) -> list[sqlite3.Row]:
        """How many distinct keys the metric saw per day (accounts active by any call)."""
        with self._lock:
            return self._conn.execute(
                "SELECT day, COUNT(*) AS n, SUM(value) AS total FROM daily WHERE metric=? AND day>=? GROUP BY day ORDER BY day",
                (metric, since),
            ).fetchall()

    def daily_latest(self, metric: str) -> list[sqlite3.Row]:
        """The newest day's rows of one metric (every key), or nothing."""
        with self._lock:
            return self._conn.execute(
                "SELECT day, key, value, updated_at FROM daily WHERE metric=? AND day=(SELECT MAX(day) FROM daily WHERE metric=?) ORDER BY key",
                (metric, metric),
            ).fetchall()

    # -- 0.22: the operator's switches, rules and their audit (controls.py) --------------------

    def controls_all(self) -> dict[str, sqlite3.Row]:
        with self._lock:
            return {str(r["key"]): r for r in self._conn.execute("SELECT * FROM controls").fetchall()}

    def control_put(self, key: str, enabled: bool, actor: str, note: str = "") -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO controls(key, enabled, updated_at, actor, note) VALUES (?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at, actor=excluded.actor, note=excluded.note",
                (key, 1 if enabled else 0, now(), actor[:80], note[:200]),
            )

    def rules_all(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute("SELECT * FROM control_rules ORDER BY threshold, id").fetchall()

    def rule(self, rule_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM control_rules WHERE id=?", (rule_id,)).fetchone()

    def rule_add(self, threshold: int, action: str, enabled: bool, note: str) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO control_rules(threshold, action, enabled, note, created_at) VALUES (?,?,?,?,?)",
                (int(threshold), action, 1 if enabled else 0, note[:200], now()),
            )
            return int(cur.lastrowid or 0)

    def rule_update(self, rule_id: int, **fields: Any) -> bool:
        allowed = {"threshold", "action", "enabled", "note", "last_fired_at", "fired_accounts"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return False
        with self.tx() as c:
            cur = c.execute(
                f"UPDATE control_rules SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                (*sets.values(), rule_id),
            )
            return cur.rowcount > 0

    def rule_delete(self, rule_id: int) -> bool:
        with self.tx() as c:
            return c.execute("DELETE FROM control_rules WHERE id=?", (rule_id,)).rowcount > 0

    def audit_add(self, actor: str, action: str, target: str = "", detail: str = "") -> None:
        who = _client.current()
        with self.tx() as c:
            c.execute(
                "INSERT INTO control_audit(ts, actor, ip, action, target, detail) VALUES (?,?,?,?,?,?)",
                (now(), actor[:80], who.ip, action, target[:80], (detail or "")[:300]),
            )

    def audit_recent(self, limit: int = 200) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute("SELECT * FROM control_audit ORDER BY id DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()

    def seed_allowances(self, allowance_uy: int) -> int:
        """Accounts from before the allowance_uy column: the allowance of the day is what
        they got, as far as anyone knows. Idempotent — only the unset rows (-1) are touched."""
        with self.tx() as c:
            cur = c.execute("UPDATE accounts SET allowance_uy=? WHERE allowance_uy<0", (max(0, int(allowance_uy)),))
            return int(cur.rowcount or 0)

    def below_allowance(self, allowance_uy: int, exclude_hashes: frozenset[str] = frozenset()) -> int:
        """How many accounts got a smaller allowance than the current one — the ones a raise
        would reach. Members (flagged, or on the operator's list) do not count: no limit."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id_hash FROM accounts WHERE unlimited=0 AND allowance_uy>=0 AND allowance_uy<?", (int(allowance_uy),)
            ).fetchall()
        return sum(1 for r in rows if r["id_hash"] not in exclude_hashes)

    def raise_allowance(self, allowance_uy: int, exclude_hashes: frozenset[str] = frozenset()) -> int:
        """Bring every account that got a smaller allowance up to this one: the difference
        goes into its pool, with a ledger line saying so, and the account remembers the new
        figure so a second run adds nothing. Returns how many accounts it reached. Lowering
        the allowance never takes anything back — it only changes what the next sign-ups get."""
        allowance_uy = max(0, int(allowance_uy))
        t = now()
        n = 0
        with self.tx() as c:
            rows = c.execute(
                "SELECT id, id_hash, allowance_uy FROM accounts WHERE unlimited=0 AND allowance_uy>=0 AND allowance_uy<?",
                (allowance_uy,),
            ).fetchall()
            for r in rows:
                if r["id_hash"] in exclude_hashes:
                    continue
                diff = allowance_uy - int(r["allowance_uy"])
                c.execute("UPDATE accounts SET grant_uy=grant_uy+?, allowance_uy=? WHERE id=?", (diff, allowance_uy, r["id"]))
                c.execute(
                    "INSERT INTO ledger(account_id, ts, kind, charged, extra) VALUES (?,?,?,?,?)",
                    (r["id"], t, "credit", 0, json.dumps({"credit_uy": diff, "from": "allowance"})),
                )
                n += 1
        return n

    def credit_all(self, credit_uy: int, note: str = "", exclude_hashes: frozenset[str] = frozenset()) -> int:
        """The same credit into every limited account's pool at once — a holiday, an apology
        for a bad day. Members are left out (nothing to add to no limit). Returns the count."""
        credit_uy = max(0, int(credit_uy))
        t = now()
        n = 0
        with self.tx() as c:
            rows = c.execute("SELECT id, id_hash FROM accounts WHERE unlimited=0 AND disabled=0").fetchall()
            for r in rows:
                if r["id_hash"] in exclude_hashes:
                    continue
                c.execute("UPDATE accounts SET grant_uy=grant_uy+? WHERE id=?", (credit_uy, r["id"]))
                c.execute(
                    "INSERT INTO ledger(account_id, ts, kind, charged, extra) VALUES (?,?,?,?,?)",
                    (r["id"], t, "credit", 0, json.dumps({"credit_uy": credit_uy, "from": "operator", "note": note[:200], "all": True})),
                )
                n += 1
        return n

    def set_pool(
        self,
        account_id: str,
        *,
        grant_uy: int | None = None,
        left_uy: int | None = None,
        delta_uy: int | None = None,
        note: str = "",
    ) -> int | None:
        """The operator sets an account's pool (0.16) — to a lifetime total (`grant_uy`), to
        what should be left right now (`left_uy`: what is spent plus that), or by a difference
        (`delta_uy`, negative takes away). The pool never goes below zero; what is spent stays
        spent, so a total under it leaves nothing. One ledger line says what moved and the new
        total. Returns the new pool, or None when there is no such account."""
        t = now()
        with self.tx() as c:
            row = c.execute("SELECT grant_uy FROM accounts WHERE id=?", (account_id,)).fetchone()
            if row is None:
                return None
            old = int(row["grant_uy"] or 0)
            if left_uy is not None:
                spent = c.execute("SELECT COALESCE(SUM(cost_uy),0) FROM ledger WHERE account_id=? AND cost_uy>0", (account_id,)).fetchone()[
                    0
                ]
                new = int(spent) + max(0, int(left_uy))
            elif grant_uy is not None:
                new = max(0, int(grant_uy))
            else:
                new = max(0, old + int(delta_uy or 0))
            if new != old:
                c.execute("UPDATE accounts SET grant_uy=? WHERE id=?", (new, account_id))
                c.execute(
                    "INSERT INTO ledger(account_id, ts, kind, charged, extra) VALUES (?,?,?,?,?)",
                    (account_id, t, "credit", 0, json.dumps({"credit_uy": new - old, "from": "operator", "note": note[:200], "set": new})),
                )
            return new

    def limited_account_ids(self, exclude_hashes: frozenset[str] = frozenset()) -> list[str]:
        """Every account under a limit — not a member, not disabled — for a change made to all."""
        with self._lock:
            rows = self._conn.execute("SELECT id, id_hash FROM accounts WHERE unlimited=0 AND disabled=0").fetchall()
        return [str(r["id"]) for r in rows if r["id_hash"] not in exclude_hashes]

    def seed_grants(self, allowance_uy: int) -> int:
        """Accounts from before 0.5 start the new model with what they have spent so far plus
        the allowance, and keep any 0.4 credit they had not used — nobody wakes up in debt or
        loses what an invite earned. Returns how many accounts were seeded.

        Only accounts no 0.15+ relay has seen (``allowance_uy`` still -1) qualify: an account
        whose pool the operator set to zero (0.16) has ``allowance_uy`` >= 0 and must stay at
        zero across a restart, and one made under ``ALLOWANCE_CNY=0`` is reached by
        ``raise_allowance`` when the allowance goes up, with a ledger line saying so."""
        with self.tx() as c:
            cur = c.execute(
                """UPDATE accounts SET grant_uy = ? + MAX(0, credit_uy - credit_used_uy)
                     + (SELECT COALESCE(SUM(l.cost_uy),0) FROM ledger l WHERE l.account_id=accounts.id AND l.cost_uy>0)
                   WHERE grant_uy = 0 AND allowance_uy < 0""",
                (max(0, int(allowance_uy)),),
            )
            return int(cur.rowcount or 0)

    @contextmanager
    def tx(self):
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def close(self) -> None:
        """Close the connection(s) once whatever holds the lock is done: a transaction on
        another thread (the notices' flush, a backfill page) must not have the connection
        closed under it, which sqlite answers with a crash rather than an error."""
        reader = self._reader if self._reader is not self else None
        if reader is not None:
            with reader._lock:
                reader._conn.close()
            self._reader = None
        with self._lock:
            self._conn.close()

    # -- codes -------------------------------------------------------------

    def codes_recent_for(self, id_hash: str, since: int) -> int:
        """Read-only count used by diagnostics and tests, never to authorize an insert."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM codes WHERE id_hash=? AND created_at>=?",
                (id_hash, since),
            ).fetchone()
        return int(row[0])

    def live_code(self, id_hash: str) -> sqlite3.Row | None:
        """Read the current code for diagnostics and tests; verification uses ``check_code``."""
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM codes WHERE id_hash=? AND used=0 AND expires_at>=? ORDER BY id DESC LIMIT 1",
                (id_hash, now()),
            ).fetchone()

    def insert_code_limited(
        self,
        id_hash: str,
        code_hash: str,
        ip: str,
        ttl_s: int,
        identifier_limit: int,
        ip_limit: int,
    ) -> str:
        """Insert one code while holding the same transaction as both window counts.

        Returns ``identifier`` or ``ip`` when that window is already full, otherwise
        ``""``. Keeping the counts and insert together prevents simultaneous requests
        from all observing the last free slot.
        """
        t = now()
        with self.tx() as c:
            if identifier_limit > 0:
                count = c.execute(
                    "SELECT COUNT(*) FROM codes WHERE id_hash=? AND created_at>=?",
                    (id_hash, t - 600),
                ).fetchone()
                if int(count[0]) >= identifier_limit:
                    return "identifier"
            if ip and ip_limit > 0:
                count = c.execute(
                    "SELECT COUNT(*) FROM codes WHERE ip=? AND created_at>=?",
                    (ip, t - 3600),
                ).fetchone()
                if int(count[0]) >= ip_limit:
                    return "ip"
            # A new code supersedes the old ones for this identifier.
            c.execute("UPDATE codes SET used=1 WHERE id_hash=? AND used=0", (id_hash,))
            c.execute(
                "INSERT INTO codes(id_hash, code_hash, ip, created_at, expires_at) VALUES (?,?,?,?,?)",
                (id_hash, code_hash, ip, t, t + ttl_s),
            )
            c.execute("DELETE FROM codes WHERE expires_at < ?", (t - 86400,))
        return ""

    def check_code(self, id_hash: str, code_hash: str, max_attempts: int) -> str:
        """Atomically count one attempt and consume a matching live code.

        Returns ``ok``, ``wrong`` or ``expired``. A successful conditional update
        changes ``used`` in the same transaction, so concurrent verification can
        never consume one code twice.
        """
        t = now()
        with self.tx() as c:
            row = c.execute(
                "SELECT * FROM codes WHERE id_hash=? AND used=0 AND expires_at>=? ORDER BY id DESC LIMIT 1",
                (id_hash, t),
            ).fetchone()
            if row is None:
                return "expired"
            code_id = int(row["id"])
            attempts = int(row["attempts"]) + 1
            if attempts > max_attempts:
                c.execute("UPDATE codes SET attempts=?, used=1 WHERE id=? AND used=0", (attempts, code_id))
                return "expired"
            if not hmac.compare_digest(str(row["code_hash"]), code_hash):
                c.execute("UPDATE codes SET attempts=? WHERE id=? AND used=0", (attempts, code_id))
                return "wrong"
            claimed = c.execute(
                "UPDATE codes SET attempts=?, used=1 WHERE id=? AND used=0 AND expires_at>=?",
                (attempts, code_id, t),
            )
            return "ok" if claimed.rowcount == 1 else "expired"

    # -- accounts ------------------------------------------------------------

    def account_by_hash(self, id_hash: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM accounts WHERE id_hash=?", (id_hash,)).fetchone()

    def account_by_hashes(self, id_hashes: tuple[str, ...], shared: str | None = None) -> sqlite3.Row | None:
        """Look up an account by its canonical hash first, then by any legacy
        hash (such as a dotted Gmail address created before canonicalisation).
        When matched on a legacy hash and the canonical hash is not taken,
        ``id_hash`` is updated in place so subsequent lookups match directly.
        ``shared`` is a hash the identifier reaches but never adopts (the
        ``+tag``-stripped form relay 0.26 merged every address into)."""
        if not id_hashes:
            return None
        primary = id_hashes[0]
        row = self.account_by_hash(primary)
        if row is not None:
            return row
        for legacy in id_hashes[1:]:
            row = self.account_by_hash(legacy)
            if row is not None:
                with self.tx() as c:
                    taken = c.execute("SELECT 1 FROM accounts WHERE id_hash=?", (primary,)).fetchone()
                    if taken is None:
                        c.execute("UPDATE accounts SET id_hash=? WHERE id=?", (primary, row["id"]))
                return self.account(str(row["id"]))
        if shared and shared != primary:
            return self.account_by_hash(shared)
        return None

    def account(self, account_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()

    @staticmethod
    def new_account_id() -> str:
        return str(uuid.uuid4())

    def create_account(
        self,
        id_hash: str,
        channel: str,
        hint: str,
        grant: int,
        identifier_enc: str = "",
        account_id: str | None = None,
        grant_uy: int = 0,
    ) -> sqlite3.Row:
        """`grant` is the token grant of old (0 = none); `grant_uy` the money the account
        starts with (0.5), written to the ledger as the first line of its statement."""
        account_id = account_id or self.new_account_id()
        t = now()
        grant_uy = max(0, int(grant_uy))
        who = _client.current()
        with self.tx() as c:
            c.execute(
                "INSERT INTO accounts(id, id_hash, channel, hint, created_at, granted, identifier_enc, grant_uy, allowance_uy, "
                "first_ip, last_ip, last_ua, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (account_id, id_hash, channel, hint, t, grant, identifier_enc, grant_uy, grant_uy, who.ip, who.ip, who.ua, t),
            )
            if grant:
                c.execute(
                    "INSERT INTO ledger(account_id, ts, kind, charged) VALUES (?,?,?,?)",
                    (account_id, t, "grant", -grant),
                )
            if grant_uy:
                c.execute(
                    "INSERT INTO ledger(account_id, ts, kind, charged, extra) VALUES (?,?,?,?,?)",
                    (account_id, t, "credit", 0, json.dumps({"credit_uy": grant_uy, "from": "signup"})),
                )
        return self.account(account_id)  # type: ignore[return-value]

    def create_account_limited(
        self,
        id_hash: str,
        channel: str,
        hint: str,
        grant: int,
        identifier_enc: str,
        account_id: str,
        grant_uy: int,
        *,
        domain: str = "",
        domain_limit: int = 0,
        domain_since: int = 0,
    ) -> tuple[sqlite3.Row | None, bool]:
        """Create an account unless it exists or its domain has filled today's quota.

        The existing-account check, domain count and insert share one transaction.
        ``(None, False)`` means the domain is full; otherwise the boolean says whether
        this call inserted the returned account.
        """
        t = now()
        grant_uy = max(0, int(grant_uy))
        who = _client.current()
        with self.tx() as c:
            existing = c.execute("SELECT * FROM accounts WHERE id_hash=?", (id_hash,)).fetchone()
            if existing is not None:
                return existing, False
            if channel == "email" and domain and domain_limit > 0:
                tail = "@" + domain.lower()
                count = c.execute(
                    """SELECT COUNT(*) FROM accounts
                       WHERE created_at>=? AND channel='email'
                         AND SUBSTR(hint, -LENGTH(?))=?""",
                    (domain_since, tail, tail),
                ).fetchone()
                if int(count[0]) >= domain_limit:
                    return None, False
            c.execute(
                "INSERT INTO accounts(id, id_hash, channel, hint, created_at, granted, identifier_enc, grant_uy, allowance_uy, "
                "first_ip, last_ip, last_ua, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (account_id, id_hash, channel, hint, t, grant, identifier_enc, grant_uy, grant_uy, who.ip, who.ip, who.ua, t),
            )
            if grant:
                c.execute(
                    "INSERT INTO ledger(account_id, ts, kind, charged) VALUES (?,?,?,?)",
                    (account_id, t, "grant", -grant),
                )
            if grant_uy:
                c.execute(
                    "INSERT INTO ledger(account_id, ts, kind, charged, extra) VALUES (?,?,?,?,?)",
                    (account_id, t, "credit", 0, json.dumps({"credit_uy": grant_uy, "from": "signup"})),
                )
            created = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            return created, True

    def delete_account(self, account_id: str) -> None:
        """Everything about one person: keys, ledger, devices, pending codes, the row itself."""
        with self.tx() as c:
            row = c.execute("SELECT id_hash, created_at FROM accounts WHERE id=?", (account_id,)).fetchone()
            if row is None:
                return
            c.execute("DELETE FROM codes WHERE id_hash=?", (row["id_hash"],))
            # one more account of its sign-up day is gone: the statistics' sign-ups per day
            # and the total at each day's end stay right (stats._accounts_daily); a count per
            # UTC day, nothing of the account
            ts = now()
            c.execute(
                "INSERT INTO daily(day, metric, key, value, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(day, metric, key) DO UPDATE SET value=value+excluded.value, updated_at=excluded.updated_at",
                (utc_day(int(row["created_at"] or ts)), "accounts", "gone", 1, ts),
            )
            c.execute("DELETE FROM samples WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM sample_stats WHERE account_id=?", (account_id,))
            # the record's rows go here; the files whose last reference this was are removed
            # by the service (Cloud.delete_account → purge_record) before it gets here
            c.execute("DELETE FROM turns WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM own_figures WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM blob_refs WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM client_events WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM calls WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM events WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM video_tasks WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM devices WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM profiles WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM sync_messages WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM sync_conversations WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM sync_cursors WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM ledger WHERE account_id=?", (account_id,))
            # the daily counters keyed by the account (`active`: one row per UTC day it made
            # a call); the other metrics are keyed by route group, error code or asset
            c.execute("DELETE FROM daily WHERE metric='active' AND key=?", (account_id,))
            # the keys' hashes stay a while, so a device still holding one hears
            # `account_deleted` (0.1.40); the rows that named the account do not
            c.execute("DELETE FROM deleted_keys WHERE deleted_at < ?", (ts - DELETED_KEYS_TTL_S,))
            c.execute(
                "INSERT OR REPLACE INTO deleted_keys(key_hash, deleted_at) SELECT key_hash, ? FROM api_keys WHERE account_id=?",
                (ts, account_id),
            )
            c.execute("DELETE FROM api_keys WHERE account_id=?", (account_id,))
            # the accounts that signed up with this one's code no longer name it. A settled
            # one keeps nothing; one whose bonus is still unpaid keeps the mark of having
            # been invited (settle_invite then credits that side alone, as for any inviter
            # that is gone). A code is only ever accepted at sign-up, so nothing reopens.
            c.execute(
                "UPDATE accounts SET invited_by='' WHERE invited_by=? AND invite_settled_at IS NOT NULL",
                (account_id,),
            )
            c.execute("UPDATE accounts SET invited_by=? WHERE invited_by=?", (INVITER_GONE, account_id))
            c.execute("DELETE FROM accounts WHERE id=?", (account_id,))

    def key_deleted(self, key_hash: str) -> bool:
        """Whether this key belonged to an account that was deleted (within the tombstones' time)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM deleted_keys WHERE key_hash=? AND deleted_at >= ?",
                (key_hash, now() - DELETED_KEYS_TTL_S),
            ).fetchone()
        return row is not None

    def grant(self, account_id: str, tokens: int, kind: str = "grant") -> None:
        with self.tx() as c:
            c.execute("UPDATE accounts SET granted=granted+? WHERE id=?", (tokens, account_id))
            c.execute(
                "INSERT INTO ledger(account_id, ts, kind, charged) VALUES (?,?,?,?)",
                (account_id, now(), kind, -tokens),
            )

    # -- contributed conversations -------------------------------------------------------------

    def set_contribute(self, account_id: str, on: bool) -> None:
        with self.tx() as c:
            c.execute("UPDATE accounts SET contribute=? WHERE id=?", (1 if on else 0, account_id))

    def add_sample(
        self,
        account_id: str,
        model: str,
        request: str,
        response: str,
        prompt_tokens: int,
        completion_tokens: int,
        meta: str = "{}",
    ) -> str:
        sid = uuid.uuid4().hex
        with self.tx() as c:
            c.execute(
                "INSERT INTO samples(id, account_id, ts, model, request, response, prompt_tokens, completion_tokens, meta) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, account_id, now(), model, request, response, prompt_tokens, completion_tokens, meta),
            )
        return sid

    def sample_count(self, account_id: str | None = None) -> int:
        with self._lock:
            if account_id is None:
                return int(self._conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0])
            return int(self._conn.execute("SELECT COUNT(*) FROM samples WHERE account_id=?", (account_id,)).fetchone()[0])

    def samples(
        self, account_id: str | None = None, since: int = 0, limit: int = 100, before: int = 0, before_id: str = ""
    ) -> list[sqlite3.Row]:
        """Newest first (ties in ``ts`` by insertion order); ``before`` (a ts) pages further
        back. With ``before_id`` (the id of the last row seen, at that ts) the page continues
        inside the same second, so rows that share a ts are not skipped; without it the page
        starts at the second before. The tie-break is the rowid, not the random id, so the
        order is the order the turns happened in. The explicit ts upper bound lets SQLite
        seek past newer seconds before applying the rowid tie-break."""
        q = "SELECT * FROM samples WHERE ts>=?"
        args: list = [since]
        if account_id is not None:
            q += " AND account_id=?"
            args.append(account_id)
        if before and before_id:
            q += " AND ts<=? AND (ts<? OR rowid<(SELECT rowid FROM samples WHERE id=?))"
            args.extend([before, before, before_id])
        elif before:
            q += " AND ts<?"
            args.append(before)
        q += " ORDER BY ts DESC, rowid DESC LIMIT ?"
        args.append(max(1, min(limit, 1000)))
        with self._lock:
            return self._conn.execute(q, args).fetchall()

    def delete_samples(self, account_id: str) -> int:
        with self.tx() as c:
            c.execute("DELETE FROM sample_stats WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM client_events WHERE account_id=?", (account_id,))
            return c.execute("DELETE FROM samples WHERE account_id=?", (account_id,)).rowcount

    # -- 0.31: what the apps report around a turn, and the deletions ledger ------------------

    CLIENT_EVENT_COLUMNS = ("account_id", "ts", "device", "platform", "kind", "turn_id", "conversation", "data")

    def add_client_events(self, rows: list[dict[str, Any]]) -> int:
        """The events of one request, each already cleaned (provenance.clean_event) and
        carrying the account, device and platform the caller added."""
        if not rows:
            return 0
        cols = self.CLIENT_EVENT_COLUMNS
        with self.tx() as c:
            c.executemany(
                f"INSERT INTO client_events({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [[r.get(k, "") for k in cols] for r in rows],
            )
        return len(rows)

    def client_events(
        self, account_id: str | None = None, kinds: list[str] | None = None, since: int = 0, limit: int = 200, before: int = 0
    ) -> list[sqlite3.Row]:
        """Newest first; ``before`` is the id of the last row seen (ids grow with time)."""
        q = "SELECT * FROM client_events WHERE ts>=?"
        args: list = [since]
        if account_id is not None:
            q += " AND account_id=?"
            args.append(account_id)
        if kinds:
            q += f" AND kind IN ({','.join('?' * len(kinds))})"
            args.extend(kinds)
        if before:
            q += " AND id<?"
            args.append(before)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, min(limit, 1000)))
        with self._lock:
            return self._conn.execute(q, args).fetchall()

    def client_events_for_turns(self, turn_ids: list[str]) -> list[sqlite3.Row]:
        """The events the apps reported about the turns named (``turn_id<>''`` is the partial
        index's own term, client_events_turn; see turns_of)."""
        if not turn_ids:
            return []
        with self._lock:
            return self._conn.execute(
                f"SELECT * FROM client_events WHERE turn_id<>'' AND turn_id IN ({','.join('?' * len(turn_ids))}) ORDER BY id",
                turn_ids,
            ).fetchall()

    def client_events_summary(self, since: int, day_offset_s: int = 0) -> list[sqlite3.Row]:
        """Events per day and kind since ``since``: the operator's figure, no row read whole."""
        with self._lock:
            return self._conn.execute(
                "SELECT ((ts + ?) / 86400) * 86400 - ? AS day, kind, COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts "
                "FROM client_events WHERE ts>=? GROUP BY day, kind ORDER BY day, kind",
                (day_offset_s, day_offset_s, since),
            ).fetchall()

    def client_events_accounts(self, since: int) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(DISTINCT account_id) FROM client_events WHERE ts>=?", (since,)).fetchone()[0])

    def client_event_count(self, account_id: str | None = None) -> int:
        with self._lock:
            if account_id is None:
                return int(self._conn.execute("SELECT COUNT(*) FROM client_events").fetchone()[0])
            return int(self._conn.execute("SELECT COUNT(*) FROM client_events WHERE account_id=?", (account_id,)).fetchone()[0])

    def add_deletion(self, subject: str, scope: str, ts: int | None = None) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO deletions(subject, ts, scope) VALUES (?,?,?)", (subject, ts or now(), scope))

    def deletions(self, since: int = 0, limit: int = 10_000) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT subject, ts, scope FROM deletions WHERE ts>=? ORDER BY ts, id LIMIT ?", (since, max(1, min(limit, 100_000)))
            ).fetchall()

    # -- 0.29: the record (turns, blobs, blob_refs) -------------------------------------------

    def add_turn(self, row: dict[str, Any], media: list[dict[str, Any]]) -> None:
        """One turn and the files it references: a file's row is made on first sight and its
        ``last_used_at`` moved on every later one (the sweep and the trim go by it); the
        account's reference to it is written once, whether or not the file was known."""
        t = int(row.get("ts") or now())
        start = row.get("turn_start")
        with self.tx() as c:
            # 0.31: the turn's key — its own id for the row that opens a turn, the opener's
            # for one that continues it (turn_key_for, in the same transaction)
            key = ""
            if start is not None:
                key = (
                    row["id"]
                    if start
                    else self._turn_key_for(c, "turns", row["account_id"], row.get("conversation", ""), int(row.get("turn_no") or 0), t)
                )
            c.execute(
                "INSERT OR REPLACE INTO turns(id, account_id, ts, model, platform, device, conversation, source, status, "
                "request, response, prompt_tokens, completion_tokens, cached_tokens, media, media_bytes, meta, "
                "run, turn_no, step, trajectory, trajectory_step, script, turn_start, turn_key) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row["id"],
                    row["account_id"],
                    t,
                    row.get("model", ""),
                    row.get("platform", ""),
                    row.get("device", ""),
                    row.get("conversation", ""),
                    row.get("source", "cloud"),
                    row.get("status", "ok"),
                    row["request"],
                    row["response"],
                    int(row.get("prompt_tokens") or 0),
                    int(row.get("completion_tokens") or 0),
                    int(row.get("cached_tokens") or 0),
                    len(media),
                    sum(int(m.get("bytes") or 0) for m in media),
                    row.get("meta", "{}"),
                    str(row.get("run") or "")[:24],
                    int(row.get("turn_no") or 0),
                    int(row.get("step") or 0),
                    str(row.get("trajectory") or "")[:80],
                    int(row.get("trajectory_step") or 0),
                    str(row.get("script") or "")[:8],
                    -1 if start is None else (1 if start else 0),
                    key,
                ),
            )
            # the figures row of an own turn (own_figures), replaced with the turn
            c.execute("DELETE FROM own_figures WHERE turn_id=?", (row["id"],))
            if row.get("source", "cloud") == "own":
                self._add_own_figures(
                    c,
                    [
                        {
                            "id": row["id"],
                            "account_id": row["account_id"],
                            "ts": t,
                            "model": row.get("model", ""),
                            "prompt_tokens": int(row.get("prompt_tokens") or 0),
                            "completion_tokens": int(row.get("completion_tokens") or 0),
                            "cached_tokens": int(row.get("cached_tokens") or 0),
                            "meta": row.get("meta", "{}"),
                        }
                    ],
                )
            for m in media:
                self._reference_blob(c, m, row["account_id"], "turn", t)

    @staticmethod
    def _add_own_figures(c: sqlite3.Cursor, rows: list[dict[str, Any]]) -> int:
        """The figures rows of own turns, one each: the provider read from the turn's meta
        (``{"provider": …}``), the rest as the turn has it. A row that is there already stays."""
        n = 0
        for r in rows:
            try:
                meta = json.loads(r.get("meta") or "{}")
            except ValueError:
                meta = {}
            provider = str(meta.get("provider") or "")[:40] if isinstance(meta, dict) else ""
            n += c.execute(
                "INSERT OR IGNORE INTO own_figures(turn_id, account_id, ts, provider, model, prompt_tokens, completion_tokens, cached_tokens) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(r["id"]),
                    str(r["account_id"]),
                    int(r["ts"]),
                    provider,
                    str(r.get("model") or "")[:80],
                    int(r.get("prompt_tokens") or 0),
                    int(r.get("completion_tokens") or 0),
                    int(r.get("cached_tokens") or 0),
                ),
            ).rowcount
        return n

    def own_unfigured_page(self, after_ts: int, after_rowid: int, limit: int) -> list[sqlite3.Row]:
        """The next own turns of the record, oldest first, for the backfill that writes their
        figures rows (0.31.1): the turns that are not own are told apart in the figures
        index, so only an own turn's row — its meta and cached count sit past the bodies —
        is read."""
        with self._lock:
            return self._conn.execute(
                "SELECT rowid, id, account_id, ts, model, prompt_tokens, completion_tokens, cached_tokens, meta "
                "FROM turns INDEXED BY turns_figures WHERE ts>=? AND source='own' AND (ts>? OR rowid>?) "
                "ORDER BY ts, rowid LIMIT ?",
                (after_ts, after_ts, after_rowid, max(1, limit)),
            ).fetchall()

    def add_own_figures(self, rows: list[sqlite3.Row] | list[dict[str, Any]]) -> int:
        """The figures rows of own turns the backfill read (own_unfigured_page); answers how
        many were new."""
        with self.tx() as c:
            return self._add_own_figures(c, [dict(r) for r in rows])

    def own_figures_count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM own_figures").fetchone()[0])

    # -- 0.31: one question, many calls (provenance.turn_start) -------------------------------

    @staticmethod
    def _turn_key_for(
        c: sqlite3.Cursor,
        table: str,
        account_id: str,
        conversation: str,
        turn_no: int,
        ts: int,
        before_rowid: int | None = None,
    ) -> str:
        """The key of the turn a row that continues one belongs to. When the app numbered
        the turn (``turn_no``) and named the conversation, the opener is the first row of
        that number in that conversation; otherwise it is whatever turn the latest earlier
        row of the same conversation belongs to (a conversation's calls come one after the
        other). ``before_rowid`` leaves a row that is already in the table out of its own
        look-up (the backfill). "" when nothing earlier is known."""
        if table not in ("turns", "sample_stats"):
            raise ValueError(table)
        if turn_no and conversation:
            r = c.execute(
                f"SELECT turn_key FROM {table} WHERE account_id=? AND conversation=? AND turn_no=? AND turn_key<>'' "
                "ORDER BY ts, rowid LIMIT 1",
                (account_id, conversation, turn_no),
            ).fetchone()
            if r is not None:
                return str(r[0])
        q = f"SELECT turn_key FROM {table} WHERE account_id=? AND conversation=? AND turn_key<>''"
        args: list[Any] = [account_id, conversation]
        if before_rowid is None:
            q += " AND ts<=?"
            args.append(ts)
        else:
            q += " AND (ts<? OR (ts=? AND rowid<?))"
            args.extend([ts, ts, before_rowid])
        r = c.execute(q + " ORDER BY ts DESC, rowid DESC LIMIT 1", args).fetchone()
        return str(r[0]) if r is not None else ""

    def turns_unkeyed_page(self, after_ts: int, after_rowid: int, limit: int) -> list[sqlite3.Row]:
        """The next rows of the record the backfill has not read, oldest first (the key of a
        row that continues a turn is its opener's, so the openers must be keyed first)."""
        with self._lock:
            return self._conn.execute(
                "SELECT rowid, id, account_id, ts, conversation, turn_no, step, request FROM turns "
                "WHERE (ts>? OR (ts=? AND rowid>?)) ORDER BY ts, rowid LIMIT ?",
                (after_ts, after_ts, after_rowid, max(1, limit)),
            ).fetchall()

    def set_turn_keys(self, table: str, rows: list[dict[str, Any]]) -> int:
        """``turn_start`` and ``turn_key`` written to rows the backfill described: each row is
        ``{rowid, account_id, conversation, turn_no, ts, start, id}``; the key of one that
        continues a turn is looked up as it is written, after the rows before it, so a
        page's openers key the rows after them. The page goes in transactions of
        ``KEY_ROWS_PER_TX``: an update rewrites the row whole, body and all (a turn's row
        carries its request), and one transaction over a page held the lock every request
        takes for seconds."""
        if table not in ("turns", "sample_stats"):
            raise ValueError(table)
        n = 0
        for i in range(0, len(rows), KEY_ROWS_PER_TX):
            with self.tx() as c:
                for r in rows[i : i + KEY_ROWS_PER_TX]:
                    start = bool(r["start"])
                    key = (
                        str(r["id"])
                        if start
                        else self._turn_key_for(
                            c,
                            table,
                            str(r["account_id"]),
                            str(r.get("conversation") or ""),
                            int(r.get("turn_no") or 0),
                            int(r["ts"]),
                            int(r["rowid"]),
                        )
                    )
                    sets = "turn_start=?, turn_key=?"
                    args: list[Any] = [1 if start else 0, key]
                    if table == "sample_stats" and "conversation" in r:
                        sets += ", conversation=?, turn_no=?"
                        args.extend([str(r.get("conversation") or "")[:80], int(r.get("turn_no") or 0)])
                    args.append(int(r["rowid"]))
                    n += c.execute(f"UPDATE {table} SET {sets} WHERE rowid=?", args).rowcount
        return n

    def sample_stats_unkeyed_page(self, after_ts: int, after_rowid: int, limit: int) -> list[sqlite3.Row]:
        """The next shape rows the backfill has not read, oldest first, with the kept turn's
        messages and meta beside them (the request's last message says whether the call
        opened a turn; the meta names the conversation)."""
        with self._lock:
            return self._conn.execute(
                "SELECT st.rowid AS rowid, st.sample_id AS id, st.account_id, st.ts, st.turn_id, s.request, s.meta "
                "FROM sample_stats st JOIN samples s ON s.id=st.sample_id "
                "WHERE (st.ts>? OR (st.ts=? AND st.rowid>?)) ORDER BY st.ts, st.rowid LIMIT ?",
                (after_ts, after_ts, after_rowid, max(1, limit)),
            ).fetchall()

    def turn_groups(
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
    ) -> list[sqlite3.Row]:
        """The record one question at a time: the turns (``turn_key`` groups) matching the
        filters, newest last call first, with the group's figures. Keyset paging on (last
        call's ts, key). Each filter narrows to turns with at least one call that matches
        (``media``: a picture or clip in some call; ``hands``: a screen-operation task)."""
        where = ["turn_key<>''", "ts>=?"]
        args: list[Any] = [since]
        if account_id is not None:
            where.append("account_id=?")
            args.append(account_id)
        if conversation:
            where.append("conversation=?")
            args.append(conversation)
        having = []
        if platform:
            having.append("SUM(CASE WHEN platform=? THEN 1 ELSE 0 END)>0")
            args.append(platform)
        if run:
            having.append("SUM(CASE WHEN run=? THEN 1 ELSE 0 END)>0")
            args.append(run)
        if source:
            having.append("SUM(CASE WHEN source=? THEN 1 ELSE 0 END)>0")
            args.append(source)
        if model:
            having.append("SUM(CASE WHEN model=? THEN 1 ELSE 0 END)>0")
            args.append(model)
        if script:
            having.append("SUM(CASE WHEN script=? THEN 1 ELSE 0 END)>0")
            args.append(script)
        if media:
            having.append("SUM(media)>0")
        if hands:
            having.append("SUM(CASE WHEN trajectory<>'' THEN 1 ELSE 0 END)>0")
        if before:
            having.append("(MAX(ts)<? OR (MAX(ts)=? AND turn_key<?))")
            args.extend([before, before, before_key])
        q = (
            "SELECT turn_key, COUNT(*) AS n, MIN(ts) AS ts0, MAX(ts) AS ts1, MIN(account_id) AS account_id, "
            "SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens, SUM(media) AS media, "
            "SUM(CASE WHEN trajectory<>'' THEN 1 ELSE 0 END) AS hands, SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END) AS partial "
            f"FROM turns INDEXED BY turns_figures WHERE {' AND '.join(where)} GROUP BY turn_key"
        )
        if having:
            q += " HAVING " + " AND ".join(having)
        q += " ORDER BY ts1 DESC, turn_key DESC LIMIT ?"
        args.append(max(1, min(limit, 200)))
        with self._lock:
            return self._conn.execute(q, args).fetchall()

    def turns_of(self, keys: list[str]) -> list[sqlite3.Row]:
        """Every call of the turns named, oldest first, so the caller can lay each turn out.
        ``turn_key<>''`` repeats the partial index's own term (turns_key): a partial index
        serves a query only when its WHERE says what the index's does, and ``IN`` alone does
        not — without it, this was a scan of the record, every body read."""
        if not keys:
            return []
        with self._lock:
            return self._conn.execute(
                f"SELECT * FROM turns WHERE turn_key<>'' AND turn_key IN ({','.join('?' * len(keys))}) ORDER BY ts, rowid", keys
            ).fetchall()

    def calls_per_turn(self, since: int = 0, account_id: str | None = None) -> list[tuple[int, int]]:
        """How many turns took how many calls, since ``since``: ``(calls, turns)`` pairs."""
        q = "SELECT n, COUNT(*) AS turns FROM (SELECT COUNT(*) AS n FROM turns INDEXED BY turns_figures WHERE turn_key<>'' AND ts>=?"
        args: list[Any] = [since]
        if account_id is not None:
            q += " AND account_id=?"
            args.append(account_id)
        q += " GROUP BY turn_key) GROUP BY n ORDER BY n"
        with self._lock:
            return [(int(r["n"]), int(r["turns"])) for r in self._conn.execute(q, args).fetchall()]

    def turn_figures(self, since: int = 0, account_id: str | None = None) -> dict[str, int]:
        """The record counted by turns (0.31): how many questions, how many of them had a
        picture or a clip, how many ran the hands, and how many calls still wait for the
        backfill to tell which turn they belong to."""
        q = (
            "SELECT SUM(CASE WHEN turn_start=1 THEN 1 ELSE 0 END) AS turns, "
            "SUM(CASE WHEN turn_start<0 THEN 1 ELSE 0 END) AS pending, "
            "COUNT(DISTINCT CASE WHEN media>0 AND turn_key<>'' THEN turn_key END) AS with_media, "
            "COUNT(DISTINCT CASE WHEN trajectory<>'' AND turn_key<>'' THEN turn_key END) AS with_hands "
            "FROM turns INDEXED BY turns_figures WHERE ts>=?"
        )
        args: list[Any] = [since]
        if account_id is not None:
            q += " AND account_id=?"
            args.append(account_id)
        with self._lock:
            r = self._conn.execute(q, args).fetchone()
            return {k: int(r[k] or 0) for k in r.keys()}

    @staticmethod
    def _reference_blob(c: sqlite3.Cursor, m: dict[str, Any], account_id: str, owner: str, t: int) -> None:
        c.execute(
            "INSERT INTO blobs(sha256, mime, bytes, created_at, last_used_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(sha256) DO UPDATE SET last_used_at=MAX(last_used_at, excluded.last_used_at)",
            (m["sha256"], str(m.get("mime") or ""), int(m.get("bytes") or 0), t, t),
        )
        c.execute("INSERT OR IGNORE INTO blob_refs(sha256, account_id, owner) VALUES (?,?,?)", (m["sha256"], account_id, owner))

    def add_blob(self, sha256: str, mime: str, size: int, account_id: str, owner: str = "upload") -> None:
        """A file a client put up on its own (PUT /v1/blobs), before the turn or profile
        that names it: the account may read it back from now on."""
        with self.tx() as c:
            self._reference_blob(c, {"sha256": sha256, "mime": mime, "bytes": size}, account_id, owner, now())

    def set_blob_refs(self, account_id: str, owner: str, shas: list[str]) -> None:
        """The account's references under one owner (``profile``) replaced by ``shas``."""
        with self.tx() as c:
            c.execute("DELETE FROM blob_refs WHERE account_id=? AND owner=?", (account_id, owner))
            for sha in shas:
                c.execute("INSERT OR IGNORE INTO blob_refs(sha256, account_id, owner) VALUES (?,?,?)", (sha, account_id, owner))

    def blob(self, sha256: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM blobs WHERE sha256=?", (sha256,)).fetchone()

    def blob_readable(self, account_id: str, sha256: str) -> bool:
        """Whether the account holds a reference to the file: one of its turns, its profile
        or an upload of its own names it. A hash alone opens nothing."""
        with self._lock:
            r = self._conn.execute("SELECT 1 FROM blob_refs WHERE account_id=? AND sha256=? LIMIT 1", (account_id, sha256)).fetchone()
            return r is not None

    def turn(self, turn_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()

    def turns(
        self,
        account_id: str | None = None,
        since: int = 0,
        limit: int = 100,
        before: int = 0,
        before_id: str = "",
        conversation: str = "",
    ) -> list[sqlite3.Row]:
        """Newest first; keyset paging on (ts, rowid) as ``samples`` does, so a page that ends
        inside a busy second continues there. ``conversation`` narrows to one chat."""
        q = "SELECT * FROM turns WHERE ts>=?"
        args: list = [since]
        if account_id is not None:
            q += " AND account_id=?"
            args.append(account_id)
        if conversation:
            q += " AND conversation=?"
            args.append(conversation)
        if before and before_id:
            q += " AND ts<=? AND (ts<? OR rowid<(SELECT rowid FROM turns WHERE id=?))"
            args.extend([before, before, before_id])
        elif before:
            q += " AND ts<?"
            args.append(before)
        q += " ORDER BY ts DESC, rowid DESC LIMIT ?"
        args.append(max(1, min(limit, 1000)))
        with self._lock:
            return self._conn.execute(q, args).fetchall()

    def turn_count(self, account_id: str | None = None) -> int:
        with self._lock:
            if account_id is None:
                return int(self._conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0])
            return int(self._conn.execute("SELECT COUNT(*) FROM turns WHERE account_id=?", (account_id,)).fetchone()[0])

    def record_totals(self, since: int = 0, account_id: str | None = None) -> dict[str, int]:
        """Turns, accounts, tokens and referenced media since ``since``, and the store's size
        (every file once, whoever references it) — for Data controls and the operator's page."""
        q = (
            "SELECT COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts, SUM(prompt_tokens) AS prompt_tokens, "
            "SUM(completion_tokens) AS completion_tokens, SUM(media) AS media, SUM(media_bytes) AS media_bytes, "
            "SUM(CASE WHEN source='own' THEN 1 ELSE 0 END) AS own, "
            f"SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END) AS partial, {self._TURNS} "
            "FROM turns INDEXED BY turns_figures WHERE ts>=?"
        )
        args: list = [since]
        if account_id is not None:
            q += " AND account_id=?"
            args.append(account_id)
        with self._lock:
            r = self._conn.execute(q, args).fetchone()
            out = {k: int(r[k] or 0) for k in r.keys()}
            if account_id is None:
                s = self._conn.execute("SELECT COUNT(*) AS files, SUM(bytes) AS bytes FROM blobs").fetchone()
            else:
                s = self._conn.execute(
                    "SELECT COUNT(*) AS files, SUM(b.bytes) AS bytes FROM blobs b "
                    "WHERE EXISTS (SELECT 1 FROM blob_refs r WHERE r.sha256=b.sha256 AND r.account_id=?)",
                    (account_id,),
                ).fetchone()
            out["files"] = int(s["files"] or 0)
            out["store_bytes"] = int(s["bytes"] or 0)
            return out

    def turns_by_day(self, since: int, offset_s: int) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                f"""SELECT {self._DAY} AS day, COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts,
                           SUM(media) AS media, SUM(media_bytes) AS media_bytes, {self._TURNS}
                    FROM turns INDEXED BY turns_figures WHERE ts>=? GROUP BY day ORDER BY day""",
                (offset_s, offset_s, offset_s, since),
            ).fetchall()

    def delete_turns(self, account_id: str) -> tuple[int, list[str]]:
        """The account's whole record: its turns and every reference it holds. Answers how
        many turns went and the files nobody references any more (their rows are gone; the
        caller removes the files)."""
        with self.tx() as c:
            held = [r[0] for r in c.execute("SELECT DISTINCT sha256 FROM blob_refs WHERE account_id=?", (account_id,)).fetchall()]
            n = c.execute("DELETE FROM turns WHERE account_id=?", (account_id,)).rowcount
            c.execute("DELETE FROM own_figures WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM blob_refs WHERE account_id=?", (account_id,))
            return n, self._drop_orphans(c, held)

    def sweep_turns(self, before: int, limit: int = 5000) -> tuple[int, list[str]]:
        """Turns older than ``before`` (RECORD_KEEP_DAYS), a page at a time; then the files
        no turn younger than that names — a file's ``last_used_at`` moves with every turn
        that names it, so one last used before ``before`` is referenced by swept turns only
        — unless a profile wears it (the face's clips). Answers the turns gone and the
        files to remove."""
        with self.tx() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM turns WHERE ts<? ORDER BY ts LIMIT ?", (before, limit)).fetchall()]
            n = 0
            for i in range(0, len(ids), 500):
                page = ids[i : i + 500]
                n += c.execute(f"DELETE FROM turns WHERE id IN ({','.join('?' * len(page))})", page).rowcount
                c.execute(f"DELETE FROM own_figures WHERE turn_id IN ({','.join('?' * len(page))})", page)
            if len(ids) >= limit:
                return n, []  # more turns to go first; the files follow on the last page
            gone = [
                r[0]
                for r in c.execute(
                    "SELECT sha256 FROM blobs b WHERE last_used_at<? "
                    "AND NOT EXISTS (SELECT 1 FROM blob_refs r WHERE r.sha256=b.sha256 AND r.owner='profile') LIMIT ?",
                    (before, limit),
                ).fetchall()
            ]
            for i in range(0, len(gone), 500):
                page = gone[i : i + 500]
                marks = ",".join("?" * len(page))
                c.execute(f"DELETE FROM blob_refs WHERE sha256 IN ({marks})", page)
                c.execute(f"DELETE FROM blobs WHERE sha256 IN ({marks})", page)
            return n, gone

    @staticmethod
    def _drop_orphans(c: sqlite3.Cursor, candidates: list[str]) -> list[str]:
        """Of ``candidates``, the files nobody references any more: their rows removed, the
        hashes answered so the caller can remove the files."""
        gone: list[str] = []
        for i in range(0, len(candidates), 500):
            page = candidates[i : i + 500]
            marks = ",".join("?" * len(page))
            gone += [
                r[0]
                for r in c.execute(
                    f"SELECT sha256 FROM blobs b WHERE sha256 IN ({marks}) "
                    "AND NOT EXISTS (SELECT 1 FROM blob_refs r WHERE r.sha256=b.sha256)",
                    page,
                ).fetchall()
            ]
        for i in range(0, len(gone), 500):
            page = gone[i : i + 500]
            c.execute(f"DELETE FROM blobs WHERE sha256 IN ({','.join('?' * len(page))})", page)
        return gone

    def blobs_bytes(self) -> int:
        """The store's size as the rows have it (every file once)."""
        with self._lock:
            return int(self._conn.execute("SELECT COALESCE(SUM(bytes),0) FROM blobs").fetchone()[0])

    def account_blob_bytes(self, account_id: str) -> int:
        """The bytes of every file the account holds a reference to, for its cap."""
        with self._lock:
            return int(
                self._conn.execute(
                    "SELECT COALESCE(SUM(b.bytes),0) FROM blobs b "
                    "WHERE EXISTS (SELECT 1 FROM blob_refs r WHERE r.sha256=b.sha256 AND r.account_id=?)",
                    (account_id,),
                ).fetchone()[0]
            )

    def trim_blobs(self, max_bytes: int, limit: int = 2000) -> list[str]:
        """Files beyond ``max_bytes`` in all, oldest use first, their rows and references
        removed; the caller removes the files. At most ``limit`` per call. A file a
        profile wears (the face's clips, ``owner='profile'``) is never trimmed: the
        profile would go on naming it and every other device would fetch a 404."""
        with self.tx() as c:
            total = int(c.execute("SELECT COALESCE(SUM(bytes),0) FROM blobs").fetchone()[0])
            if total <= max_bytes:
                return []
            gone: list[str] = []
            for sha, size in c.execute(
                "SELECT sha256, bytes FROM blobs b "
                "WHERE NOT EXISTS (SELECT 1 FROM blob_refs r WHERE r.sha256=b.sha256 AND r.owner='profile') "
                "ORDER BY last_used_at, rowid LIMIT ?",
                (limit,),
            ).fetchall():
                if total <= max_bytes:
                    break
                gone.append(sha)
                total -= int(size)
            for i in range(0, len(gone), 500):
                page = gone[i : i + 500]
                marks = ",".join("?" * len(page))
                c.execute(f"DELETE FROM blob_refs WHERE sha256 IN ({marks})", page)
                c.execute(f"DELETE FROM blobs WHERE sha256 IN ({marks})", page)
            return gone

    def contributors(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM accounts WHERE contribute=1").fetchone()[0])

    # The Data view's sums are read from `sample_stats` (one short row per kept turn), never
    # from `samples`: a sample row carries the conversation, tens of kilobytes on average, and
    # a SUM over a column stored after it walked every row's overflow pages, which on a file
    # of tens of gigabytes took minutes with the lock held. A token count of -1 is a row the
    # analytics loop has not copied yet (Analytics.tokens_step); it counts as nothing.

    _TOKENS = "SUM(MAX(prompt_tokens, 0)) AS prompt_tokens, SUM(MAX(completion_tokens, 0)) AS completion_tokens"
    #: 0.31: the rows that opened a turn — the figures count questions beside calls
    _TURNS = "SUM(CASE WHEN turn_start=1 THEN 1 ELSE 0 END) AS turns"

    def samples_totals(self, since: int) -> sqlite3.Row:
        """How many turns were kept since ``since``, by how many accounts, and their tokens."""
        with self._lock:
            return self._conn.execute(
                f"SELECT COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts, {self._TOKENS}, {self._TURNS}, "
                "SUM(CASE WHEN turn_start<0 THEN 1 ELSE 0 END) AS pending FROM sample_stats WHERE ts>=?",
                (since,),
            ).fetchone()

    def samples_by_day(self, since: int, offset_s: int) -> list[sqlite3.Row]:
        """Kept turns per local day (``offset_s`` east of UTC): count, accounts, tokens."""
        with self._lock:
            return self._conn.execute(
                f"""SELECT {self._DAY} AS day, COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts, {self._TOKENS}, {self._TURNS}
                    FROM sample_stats WHERE ts>=? GROUP BY day ORDER BY day""",
                (offset_s, offset_s, offset_s, since),
            ).fetchall()

    def samples_by_model(self, since: int) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                f"SELECT model, COUNT(*) AS n, {self._TOKENS}, {self._TURNS} FROM sample_stats WHERE ts>=? GROUP BY model ORDER BY n DESC",
                (since,),
            ).fetchall()

    def samples_by_account(self) -> list[sqlite3.Row]:
        """Every account that has turns kept, with how many, their tokens, the first and the
        last — the operator's way in to one person's data, newest activity first."""
        with self._lock:
            return self._conn.execute(
                """SELECT s.account_id, a.hint, a.channel, a.contribute, a.created_at,
                          COUNT(*) AS n, SUM(MAX(s.prompt_tokens, 0)) AS prompt_tokens, SUM(MAX(s.completion_tokens, 0)) AS completion_tokens,
                          SUM(CASE WHEN s.turn_start=1 THEN 1 ELSE 0 END) AS turns,
                          MIN(s.ts) AS first_ts, MAX(s.ts) AS last_ts, GROUP_CONCAT(DISTINCT s.model) AS models
                   FROM sample_stats s JOIN accounts a ON a.id=s.account_id
                   GROUP BY s.account_id ORDER BY last_ts DESC""",
            ).fetchall()

    def samples_by_platform(self, since: int) -> list[sqlite3.Row]:
        """Kept turns of the period by the app behind them (client.platform_of, kept with the shape)."""
        with self._lock:
            return self._conn.execute(
                f"SELECT platform, COUNT(*) AS n, {self._TURNS} FROM sample_stats WHERE ts>=? GROUP BY platform ORDER BY n DESC", (since,)
            ).fetchall()

    def samples_by_column(self, column: str, since: int) -> list[sqlite3.Row]:
        """Kept turns of the period grouped by one of the shape's short columns (0.31:
        ``run``, ``source``); the column name is the caller's constant, never input."""
        if column not in ("run", "source", "platform", "model"):
            raise ValueError(column)
        with self._lock:
            return self._conn.execute(
                f"SELECT {column}, COUNT(*) AS n, {self._TURNS} FROM sample_stats WHERE ts>=? GROUP BY {column} ORDER BY n DESC", (since,)
            ).fetchall()

    def event_accounts(self, kind: str) -> int:
        """How many distinct accounts ever had an event of this kind on their timeline."""
        with self._lock:
            return int(
                self._conn.execute("SELECT COUNT(DISTINCT account_id) FROM events WHERE kind=? AND account_id<>''", (kind,)).fetchone()[0]
            )

    def set_disabled(self, account_id: str, disabled: bool) -> None:
        with self.tx() as c:
            c.execute("UPDATE accounts SET disabled=? WHERE id=?", (1 if disabled else 0, account_id))

    def set_unlimited(self, account_id: str, unlimited: bool) -> None:
        with self.tx() as c:
            c.execute("UPDATE accounts SET unlimited=? WHERE id=?", (1 if unlimited else 0, account_id))

    # -- invitations and credit -----------------------------------------------------

    def account_by_invite_code(self, code: str) -> sqlite3.Row | None:
        if not code:
            return None
        with self._lock:
            return self._conn.execute("SELECT * FROM accounts WHERE invite_code=?", (code,)).fetchone()

    def set_invite_code(self, account_id: str, code: str) -> bool:
        """Give the account its code, once; False when another account already holds that code."""
        with self.tx() as c:
            try:
                cur = c.execute("UPDATE accounts SET invite_code=? WHERE id=? AND invite_code=''", (code, account_id))
            except sqlite3.IntegrityError:
                return False
            return cur.rowcount == 1

    def link_invite(self, inviter_id: str, invitee_id: str) -> None:
        """A new account signed up with the inviter's code: the link is written and the
        inviter's counter grows (``invites`` keeps meaning sign-ups). Nothing is credited
        here; the bonus is paid by ``settle_invite`` at the newcomer's first charged request."""
        with self.tx() as c:
            c.execute("UPDATE accounts SET invited_by=? WHERE id=? AND invited_by=''", (inviter_id, invitee_id))
            c.execute("UPDATE accounts SET invites=invites+1 WHERE id=?", (inviter_id,))

    def invite_pending(self, account_id: str) -> bool:
        """Whether this account came through a code and its bonus is still unpaid; one lookup
        by primary key, made after every charged request."""
        with self._lock:
            r = self._conn.execute(
                "SELECT 1 FROM accounts WHERE id=? AND invited_by<>'' AND invite_settled_at IS NULL", (account_id,)
            ).fetchone()
        return r is not None

    def settle_invite(
        self,
        invitee_id: str,
        bonus_uy: int,
        min_spent_uy: int = 0,
        refuse_same_ip: bool = False,
    ) -> tuple[bool, str, bool]:
        """The invitee made its first charged request: both pools grow by the bonus, the
        inviter's (``from: invite``, with the friend's id) and the invitee's (``from:
        invited``), and the account is marked settled. A no-op when the account was not
        invited or was settled already. When the inviter's account is gone, or disabled,
        the invitee alone is credited and the account is still marked settled, so the
        question is never asked again. When ``refuse_same_ip`` is true and both accounts
        share the same non-local ``first_ip``, or when ``min_spent_uy`` is positive and the
        invitee has not spent at least ``min_spent_uy``, settlement is deferred and
        ``(False, inviter_id, False)`` is returned. Returns ``(settled, inviter_id,
        inviter_paid)``."""
        t = now()
        bonus_uy = max(0, int(bonus_uy))
        min_spent_uy = max(0, int(min_spent_uy))
        with self.tx() as c:
            row = c.execute(
                "SELECT invited_by, invite_settled_at, first_ip FROM accounts WHERE id=?",
                (invitee_id,),
            ).fetchone()
            if row is None or not row["invited_by"] or row["invite_settled_at"] is not None:
                return False, str(row["invited_by"]) if row is not None else "", False
            inviter_id = str(row["invited_by"])
            inviter = c.execute("SELECT id, disabled, first_ip FROM accounts WHERE id=?", (inviter_id,)).fetchone()
            if refuse_same_ip and inviter is not None:
                invitee_ip = (row["first_ip"] or "").strip()
                inviter_ip = (inviter["first_ip"] or "").strip()
                if invitee_ip and invitee_ip == inviter_ip and invitee_ip not in ("127.0.0.1", "::1", "testclient"):
                    return False, inviter_id, False
            if min_spent_uy > 0:
                spent = int(
                    c.execute(
                        "SELECT COALESCE(SUM(cost_uy), 0) FROM ledger WHERE account_id=? AND cost_uy>0",
                        (invitee_id,),
                    ).fetchone()[0]
                    or 0
                )
                if spent < min_spent_uy:
                    return False, inviter_id, False
            inviter_paid = inviter is not None and not inviter["disabled"]
            if inviter_paid:
                c.execute("UPDATE accounts SET grant_uy=grant_uy+? WHERE id=?", (bonus_uy, inviter_id))
                c.execute(
                    "INSERT INTO ledger(account_id, ts, kind, charged, extra) VALUES (?,?,?,?,?)",
                    (inviter_id, t, "credit", 0, json.dumps({"credit_uy": bonus_uy, "from": "invite", "friend": invitee_id[:8]})),
                )
            c.execute("UPDATE accounts SET grant_uy=grant_uy+?, invite_settled_at=? WHERE id=?", (bonus_uy, t, invitee_id))
            c.execute(
                "INSERT INTO ledger(account_id, ts, kind, charged, extra) VALUES (?,?,?,?,?)",
                (invitee_id, t, "credit", 0, json.dumps({"credit_uy": bonus_uy, "from": "invited", "friend": inviter_id[:8]})),
            )
        return True, inviter_id, inviter_paid

    @staticmethod
    def _invite_net_uy(c: sqlite3.Connection, inviter_id: str) -> int:
        """The ``from: invite`` lines minus the ``from: clawback`` lines (which are negative)."""
        r = c.execute(
            "SELECT COALESCE(SUM(json_extract(extra, '$.credit_uy')), 0) FROM ledger "
            "WHERE account_id=? AND kind='credit' AND json_extract(extra, '$.from') IN ('invite', 'clawback')",
            (inviter_id,),
        ).fetchone()
        return max(0, int(r[0] or 0))

    def invite_reclaimable_uy(self, inviter_id: str) -> int:
        """What this account's invites put into its pool and has not been taken back yet."""
        with self._lock:
            return self._invite_net_uy(self._conn, inviter_id)

    def clawback_invite(self, inviter_id: str, note: str = "") -> int:
        """The operator takes the invite credit back (abuse): the pool is lowered by what
        the invites put in and was not reclaimed before, but never below what the account
        has spent, so what is left never goes negative. One ledger line of kind ``credit``
        says so (``from: clawback``, a negative figure). Returns the micro-yuan reclaimed,
        0 when there is nothing to take or no such account."""
        t = now()
        with self.tx() as c:
            row = c.execute("SELECT grant_uy FROM accounts WHERE id=?", (inviter_id,)).fetchone()
            if row is None:
                return 0
            earned = self._invite_net_uy(c, inviter_id)
            spent = c.execute("SELECT COALESCE(SUM(cost_uy),0) FROM ledger WHERE account_id=? AND cost_uy>0", (inviter_id,)).fetchone()[0]
            grant = int(row["grant_uy"] or 0)
            amount = min(earned, max(0, grant - int(spent or 0)))
            if amount <= 0:
                return 0
            c.execute("UPDATE accounts SET grant_uy=grant_uy-? WHERE id=?", (amount, inviter_id))
            c.execute(
                "INSERT INTO ledger(account_id, ts, kind, charged, extra) VALUES (?,?,?,?,?)",
                (inviter_id, t, "credit", 0, json.dumps({"credit_uy": -amount, "from": "clawback", "note": note[:200]})),
            )
        return amount

    def unused_invitee_ids(self, inviter_id: str, limit: int = 500) -> list[str]:
        """The accounts this one brought that never made a charged request and never spent
        anything, oldest first, `limit` at a time (the caller loops until none are left)."""
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT id FROM (SELECT i.id, i.created_at, i.rowid AS rid, {USAGE_OF_ACCOUNT} FROM accounts i WHERE i.invited_by=?)
                    WHERE requests=0 AND spent_uy=0
                    ORDER BY created_at, rid LIMIT ?""",
                (inviter_id, max(1, int(limit))),
            ).fetchall()
        return [str(r["id"]) for r in rows]

    def invite_velocity(self, since: int, more_than: int = 10) -> list[sqlite3.Row]:
        """The inviters whose code brought more than `more_than` accounts since `since`
        (``id``, ``hint``, ``n``), the most first; one aggregate over the sign-ups of the period."""
        with self._lock:
            return self._conn.execute(
                """SELECT a.id, a.hint, x.n FROM (
                       SELECT invited_by, COUNT(*) AS n FROM accounts WHERE created_at>=? AND invited_by<>''
                       GROUP BY invited_by HAVING COUNT(*)>?
                   ) x JOIN accounts a ON a.id=x.invited_by ORDER BY x.n DESC""",
                (since, int(more_than)),
            ).fetchall()

    def invite_unused(self, at_least: int = 20, active_share: float = 0.05) -> list[sqlite3.Row]:
        """The inviters with at least `at_least` invitees of whom `active_share` or fewer ever
        made a request (``id``, ``hint``, ``n``, ``active``), the most invitees first."""
        with self._lock:
            # Probe ledger_account_ts once per invitee. Grouping the whole ledger here made
            # the ten-minute health check block the relay once the statement grew large.
            return self._conn.execute(
                """SELECT a.id, a.hint, x.n, x.active FROM (
                        SELECT i.invited_by, COUNT(*) AS n,
                               SUM(CASE WHEN EXISTS (
                                   SELECT 1 FROM ledger l
                                   WHERE l.account_id=i.id
                                     AND l.kind IN ('chat','image','video','realtime')
                                   LIMIT 1
                               ) THEN 1 ELSE 0 END) AS active
                        FROM accounts i
                        WHERE i.invited_by<>'' GROUP BY i.invited_by
                    ) x JOIN accounts a ON a.id=x.invited_by
                    WHERE x.n>=? AND x.active <= x.n * ?
                    ORDER BY x.n DESC""",
                (int(at_least), float(active_share)),
            ).fetchall()

    def signups_from_domain_since(self, domain: str, since: int) -> int:
        """How many e-mail accounts whose address ends in ``@domain`` were made since `since`.
        The hint (``so***@example.com``) carries the domain in clear, so nothing is decrypted."""
        tail = "@" + domain.lower()
        with self._lock:
            r = self._conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE created_at>=? AND channel='email' AND SUBSTR(hint, -LENGTH(?))=?",
                (since, tail, tail),
            ).fetchone()
        return int(r[0] or 0)

    def add_credit(self, account_id: str, credit_uy: int, note: str = "") -> None:
        """Credit from the operator — a merged pull request, a good issue, a hand at a bad day."""
        credit_uy = max(0, int(credit_uy))
        with self.tx() as c:
            c.execute("UPDATE accounts SET grant_uy=grant_uy+? WHERE id=?", (credit_uy, account_id))
            c.execute(
                "INSERT INTO ledger(account_id, ts, kind, charged, extra) VALUES (?,?,?,?,?)",
                (account_id, now(), "credit", 0, json.dumps({"credit_uy": credit_uy, "from": "operator", "note": note[:200]})),
            )

    def invite_earned_uy(self, inviter_id: str) -> int:
        """What invites have put into this account's pool, summed from the ledger lines
        ``settle_invite`` wrote (``from: invite``), so the figure stays right when the bonus
        changes between one invite and the next; net of what the operator took back
        (``from: clawback``)."""
        return self.invite_reclaimable_uy(inviter_id)

    def invitees(self, inviter_id: str, limit: int = 50) -> list[sqlite3.Row]:
        """The accounts that signed up with this one's code, newest first, each with when it
        came, whether it ever made a request and what it spent, where it was seen from and
        when it was last seen. The person's own view keeps the hint and the date of these;
        the operator's page shows the rest."""
        with self._lock:
            return self._conn.execute(
                f"""SELECT i.id, i.hint, i.channel, i.created_at, i.disabled, i.first_ip, i.last_ip, i.last_seen_at, i.invite_settled_at,
                           {USAGE_OF_ACCOUNT}
                    FROM accounts i
                    WHERE i.invited_by=? ORDER BY i.created_at DESC, i.rowid DESC LIMIT ?""",
                (inviter_id, limit),
            ).fetchall()

    def invitee_count(self, inviter_id: str) -> int:
        """How many accounts here now signed up with this one's code (the ``invites`` column
        is the counter as it was recorded; an invitee who deleted their account leaves it)."""
        with self._lock:
            r = self._conn.execute("SELECT COUNT(*) FROM accounts WHERE invited_by=?", (inviter_id,)).fetchone()
        return int(r[0] or 0)

    def invite_leaders(self, limit: int = 200) -> list[sqlite3.Row]:
        """The accounts whose code brought someone, the ones that brought most first: how
        many came (``invited``, the accounts here now; ``invites`` is the recorded counter),
        how many of those ever made a request, how many were paid for and how many are still
        pending, how many were seen from one of the inviter's own addresses, what they spent,
        what the inviter's pool got from them, and when the first and the last of them
        signed up."""
        with self._lock:
            return self._conn.execute(
                f"""SELECT a.id, a.hint, a.channel, a.created_at, a.disabled, a.invites, a.first_ip, a.last_ip, a.identifier_enc,
                           COUNT(i.id) AS invited,
                           SUM(CASE WHEN COALESCE(l.requests, 0) > 0 THEN 1 ELSE 0 END) AS invited_active,
                           SUM(CASE WHEN i.invite_settled_at IS NOT NULL THEN 1 ELSE 0 END) AS invited_settled,
                           SUM(CASE WHEN i.invite_settled_at IS NULL THEN 1 ELSE 0 END) AS invited_pending,
                           SUM(CASE WHEN (i.first_ip<>'' AND i.first_ip IN (a.first_ip, a.last_ip))
                                      OR (i.last_ip<>'' AND i.last_ip IN (a.first_ip, a.last_ip)) THEN 1 ELSE 0 END) AS invited_same_ip,
                           COALESCE(SUM(l.spent_uy), 0) AS invited_spent_uy,
                           COALESCE(e.earned_uy, 0) AS earned_uy,
                           MIN(i.created_at) AS first_invite_at,
                           MAX(i.created_at) AS last_invite_at
                    FROM accounts a
                    JOIN accounts i ON i.invited_by=a.id
                    LEFT JOIN {USAGE_BY_ACCOUNT} l ON l.account_id=i.id
                    LEFT JOIN (SELECT account_id, SUM(json_extract(extra, '$.credit_uy')) AS earned_uy
                               FROM ledger WHERE kind='credit' AND json_extract(extra, '$.from') IN ('invite', 'clawback')
                               GROUP BY account_id) e ON e.account_id=a.id
                    GROUP BY a.id
                    ORDER BY invited DESC, last_invite_at DESC
                    LIMIT ?""",
                (limit,),
            ).fetchall()

    # -- passwords -----------------------------------------------------------------

    def set_password(self, account_id: str, password_hash: str) -> None:
        """Also clears any lock: a new password is a fresh start."""
        with self.tx() as c:
            c.execute(
                "UPDATE accounts SET password_hash=?, password_set_at=?, failed_logins=0, locked_until=NULL WHERE id=?",
                (password_hash, now() if password_hash else None, account_id),
            )

    def login_failed(self, account_id: str, max_attempts: int, lockout_s: int) -> int:
        """Counts a wrong password; locks the account for `lockout_s` at the
        limit. Returns how many tries are left (0 = locked now)."""
        with self.tx() as c:
            c.execute("UPDATE accounts SET failed_logins=failed_logins+1 WHERE id=?", (account_id,))
            r = c.execute("SELECT failed_logins FROM accounts WHERE id=?", (account_id,)).fetchone()
            failed = int(r[0]) if r else 0
            if failed >= max_attempts:
                c.execute("UPDATE accounts SET locked_until=?, failed_logins=0 WHERE id=?", (now() + lockout_s, account_id))
                return 0
        return max(0, max_attempts - failed)

    def login_succeeded(self, account_id: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE accounts SET failed_logins=0, locked_until=NULL WHERE id=?", (account_id,))

    def list_accounts(self, limit: int = 200) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute("SELECT * FROM accounts ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()

    def admin_accounts(self, day_start: int, limit: int = 500) -> list[sqlite3.Row]:
        """The operator's view: each account with today's spend (tokens and
        money), when it was last seen, how many keys (sign-ins) are live and
        how many devices it remembers."""
        # one pass over each table, grouped by account, instead of seven correlated
        # subqueries per account row (the old form was seconds at ten thousand accounts)
        with self._lock:
            return self._conn.execute(
                """SELECT a.*,
                          COALESCE(l.used_today, 0) AS used_today,
                          COALESCE(l.spent_today_uy, 0) AS spent_today_uy,
                          COALESCE(l.spent_uy, 0) AS spent_uy,
                          COALESCE(l.requests, 0) AS requests,
                          k.last_active_at,
                          COALESCE(k.live_keys, 0) AS live_keys,
                          COALESCE(d.device_count, 0) AS device_count
                   FROM accounts a
                   LEFT JOIN (SELECT account_id,
                                     SUM(CASE WHEN ts>=? AND charged>0 THEN charged ELSE 0 END) AS used_today,
                                     SUM(CASE WHEN ts>=? AND cost_uy>0 THEN cost_uy ELSE 0 END) AS spent_today_uy,
                                     SUM(CASE WHEN cost_uy>0 THEN cost_uy ELSE 0 END) AS spent_uy,
                                     SUM(CASE WHEN kind IN ('chat','image','video','realtime') THEN 1 ELSE 0 END) AS requests
                              FROM ledger GROUP BY account_id) l ON l.account_id=a.id
                   LEFT JOIN (SELECT account_id, MAX(last_used_at) AS last_active_at,
                                     SUM(CASE WHEN revoked_at IS NULL THEN 1 ELSE 0 END) AS live_keys
                              FROM api_keys GROUP BY account_id) k ON k.account_id=a.id
                   LEFT JOIN (SELECT account_id, COUNT(*) AS device_count
                              FROM devices GROUP BY account_id) d ON d.account_id=a.id
                   ORDER BY a.created_at DESC LIMIT ?""",
                (day_start, day_start, limit),
            ).fetchall()

    def accounts_brief(self, ids: Iterable[str]) -> list[sqlite3.Row]:
        """`id`, `hint`, `identifier_enc` for exactly these accounts: the labels a page of
        events or a top list needs, without reading (and decrypting) every account."""
        wanted = sorted({str(i) for i in ids if i})
        if not wanted:
            return []
        out: list[sqlite3.Row] = []
        with self._lock:
            for i in range(0, len(wanted), 500):
                chunk = wanted[i : i + 500]
                marks = ",".join("?" * len(chunk))
                out.extend(self._conn.execute(f"SELECT id, hint, identifier_enc FROM accounts WHERE id IN ({marks})", chunk).fetchall())
        return out

    def allowance_rows(self) -> list[sqlite3.Row]:
        """Per account, what the allowance distribution needs and nothing else: `id_hash`,
        `unlimited`, `grant_uy` and the money spent at list prices (stats.py)."""
        with self._lock:
            return self._conn.execute(
                """SELECT a.id_hash, a.unlimited, a.grant_uy, COALESCE(l.spent_uy, 0) AS spent_uy
                   FROM accounts a
                   LEFT JOIN (SELECT account_id, SUM(CASE WHEN cost_uy>0 THEN cost_uy ELSE 0 END) AS spent_uy
                              FROM ledger GROUP BY account_id) l ON l.account_id=a.id"""
            ).fetchall()

    def usage_by_day(self, since: int, day_offset_s: int = 0) -> list[sqlite3.Row]:
        """Charged tokens and money per local day and kind, for the admin page's
        totals. `day` is the UNIX time the local day starts."""
        with self._lock:
            return self._conn.execute(
                """SELECT ((ts + ?) - (ts + ?) % 86400 - ?) AS day, kind, COUNT(*) AS requests,
                          SUM(charged) AS charged, SUM(cost_uy) AS cost_uy
                   FROM ledger WHERE ts>=? AND charged>0 GROUP BY day, kind ORDER BY day DESC""",
                (day_offset_s, day_offset_s, day_offset_s, since),
            ).fetchall()

    def usage_tokens_by_day(self, since: int, day_offset_s: int = 0) -> list[sqlite3.Row]:
        """0.22: requests, tokens in and out and money per day and kind (stats.py; offset 0 = UTC days)."""
        with self._lock:
            return self._conn.execute(
                f"""SELECT {self._DAY} AS day, kind, COUNT(*) AS requests, SUM(prompt_tokens) AS prompt_tokens,
                           SUM(completion_tokens) AS completion_tokens, SUM(charged) AS charged, SUM(cost_uy) AS cost_uy
                    FROM ledger WHERE ts>=? AND charged>=0 AND kind IN ('chat','image','video','realtime')
                    GROUP BY day, kind ORDER BY day""",
                (day_offset_s, day_offset_s, day_offset_s, since),
            ).fetchall()

    def devices_per_account(self) -> list[sqlite3.Row]:
        """0.22: how many devices each account remembers — for the distribution (stats.py)."""
        with self._lock:
            return self._conn.execute(
                """SELECT n, COUNT(*) AS accounts FROM (
                       SELECT a.id, (SELECT COUNT(*) FROM devices d WHERE d.account_id=a.id) AS n FROM accounts a
                   ) GROUP BY n ORDER BY n"""
            ).fetchall()

    def accounts_by_channel(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """SELECT channel, COUNT(*) AS accounts, SUM(CASE WHEN password_hash<>'' THEN 1 ELSE 0 END) AS with_password,
                          SUM(unlimited) AS members, SUM(disabled) AS disabled, SUM(contribute) AS contribute, SUM(sync_enabled) AS sync_on
                   FROM accounts GROUP BY channel ORDER BY accounts DESC"""
            ).fetchall()

    # -- keys ----------------------------------------------------------------

    def insert_key(
        self,
        key_hash: str,
        prefix: str,
        account_id: str,
        device: str,
        via: str = "code",
        expires_at: int | None = None,
        hub_device_id: str = "",
        hub_device_kind: str = "",
        replace_hub_identity: bool = False,
    ) -> None:
        who = _client.current()
        with self.tx() as c:
            if hub_device_id and replace_hub_identity:
                # A fresh code/password sign-in proves the account again and may rotate
                # the credential of the same installation. The old key remains a valid
                # account key, but no longer owns this Hub identity.
                c.execute(
                    "UPDATE api_keys SET hub_device_id='', hub_device_kind='' WHERE account_id=? AND hub_device_id=?",
                    (account_id, hub_device_id),
                )
            c.execute(
                "INSERT INTO api_keys(key_hash, prefix, account_id, device, hub_device_id, "
                "hub_device_kind, created_at, via, ip, ua, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    key_hash,
                    prefix,
                    account_id,
                    device[:80],
                    hub_device_id,
                    hub_device_kind,
                    now(),
                    via,
                    who.ip,
                    who.ua,
                    expires_at,
                ),
            )

    def bind_key_to_hub_device(self, key_hash: str, account_id: str, device_id: str, kind: str) -> bool:
        """Bind an unbound credential to its first Hub identity.

        False means this key already names another identity, or a live key of the
        account owns this device id and this key may not take it over. A revoked or
        lapsed owner releases its id. A key from a later code or password sign-in on
        the same installation (the phone signed in again without signing out first,
        the runtime's vault was reset, the old sign-out never reached the relay) takes
        the id over, since that sign-in proved the account again; the older key stays a
        valid account key but no longer speaks for the device. A session key never
        takes over: it may only register an id nobody holds. The unique index makes two
        simultaneous first hellos choose one owner rather than both succeeding.
        """
        t = now()
        with self.tx() as c:
            row = c.execute(
                "SELECT rowid, hub_device_id, hub_device_kind, via, created_at FROM api_keys WHERE key_hash=? AND account_id=?",
                (key_hash, account_id),
            ).fetchone()
            if row is None:
                return False
            bound_id = str(row["hub_device_id"] or "")
            bound_kind = str(row["hub_device_kind"] or "")
            if bound_id:
                return bound_id == device_id and bound_kind == kind
            # what no longer opens releases its identity
            c.execute(
                "UPDATE api_keys SET hub_device_id='', hub_device_kind='' WHERE account_id=? AND hub_device_id=? "
                "AND (revoked_at IS NOT NULL OR (expires_at IS NOT NULL AND expires_at <= ?))",
                (account_id, device_id, t),
            )
            owner = c.execute(
                "SELECT rowid, key_hash, created_at FROM api_keys WHERE account_id=? AND hub_device_id=? LIMIT 1",
                (account_id, device_id),
            ).fetchone()
            if owner is not None:
                proven = str(row["via"] or "code") in ("code", "password")
                # issue order: the second, then the row, since two keys can share a second
                later = (int(row["created_at"]), int(row["rowid"])) > (int(owner["created_at"]), int(owner["rowid"]))
                if not proven or not later:
                    return False
                c.execute(
                    "UPDATE api_keys SET hub_device_id='', hub_device_kind='' WHERE key_hash=?",
                    (owner["key_hash"],),
                )
            try:
                cur = c.execute(
                    "UPDATE api_keys SET hub_device_id=?, hub_device_kind=? WHERE key_hash=? AND account_id=? AND hub_device_id=''",
                    (device_id, kind, key_hash, account_id),
                )
            except sqlite3.IntegrityError:
                return False
            return cur.rowcount == 1

    def key(self, key_hash: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT k.*, a.disabled AS account_disabled, a.granted, a.used, a.channel, a.hint, a.created_at AS account_created_at, "
                "a.id_hash, a.unlimited AS account_unlimited, a.password_hash, a.password_set_at, "
                "a.invite_code, a.invites, a.grant_uy, a.contribute_bonus_at, a.contribute "
                "FROM api_keys k JOIN accounts a ON a.id=k.account_id WHERE k.key_hash=?",
                (key_hash,),
            ).fetchone()

    def touch_key(self, key_hash: str, account_id: str = "") -> None:
        """A request with this key: when it was last used, and — with the account known —
        where the account was last seen from and with what."""
        t = now()
        who = _client.current()
        with self.tx() as c:
            c.execute("UPDATE api_keys SET last_used_at=? WHERE key_hash=?", (t, key_hash))
            if account_id and (who.ip or who.ua):
                c.execute(
                    "UPDATE accounts SET last_ip=?, last_ua=?, last_seen_at=?, first_ip=CASE WHEN first_ip='' THEN ? ELSE first_ip END WHERE id=?",
                    (who.ip, who.ua, t, who.ip, account_id),
                )

    def revoke_key(self, key_hash: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE api_keys SET revoked_at=? WHERE key_hash=? AND revoked_at IS NULL", (now(), key_hash))

    def revoke_key_by_prefix(self, account_id: str, prefix: str) -> bool:
        """Sign one device out from another; the prefix is what the account page shows."""
        with self.tx() as c:
            cur = c.execute(
                "UPDATE api_keys SET revoked_at=? WHERE account_id=? AND prefix=? AND revoked_at IS NULL",
                (now(), account_id, prefix),
            )
            return cur.rowcount > 0

    def revoke_all_keys(self, account_id: str, keep_hash: str | None = None) -> int:
        with self.tx() as c:
            if keep_hash:
                cur = c.execute(
                    "UPDATE api_keys SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL AND key_hash<>?",
                    (now(), account_id, keep_hash),
                )
            else:
                cur = c.execute("UPDATE api_keys SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL", (now(), account_id))
            return cur.rowcount

    def keys_for(self, account_id: str, live_only: bool = False) -> list[sqlite3.Row]:
        with self._lock:
            sql = "SELECT * FROM api_keys WHERE account_id=?"
            args: list = [account_id]
            if live_only:
                sql += " AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > ?)"
                args.append(now())
            return self._conn.execute(sql + " ORDER BY created_at", args).fetchall()

    # -- events (the account's own history; the operator's audit) -------------------

    def add_event(self, account_id: str, kind: str, detail: str = "") -> None:
        who = _client.current()
        with self.tx() as c:
            c.execute(
                "INSERT INTO events(account_id, ts, kind, detail, ip, ua) VALUES (?,?,?,?,?,?)",
                (account_id or "", now(), kind, (detail or "")[:200], who.ip, who.ua),
            )

    @staticmethod
    def _event_where(kinds: tuple[str, ...] | None, q: str) -> tuple[str, list]:
        """The operator's filter on a timeline: these kinds (any of them) and a text that the
        kind name or the detail contains. Empty means everything."""
        where, args = "", []
        if kinds:
            where += f" AND kind IN ({','.join('?' * len(kinds))})"
            args.extend(kinds)
        if q:
            where += " AND (kind LIKE ? ESCAPE '\\' OR detail LIKE ? ESCAPE '\\')"
            args.extend([_like(q), _like(q)])
        return where, args

    def events_for(
        self,
        account_id: str,
        limit: int = 50,
        before_id: int = 0,
        kinds: tuple[str, ...] | None = None,
        q: str = "",
    ) -> list[sqlite3.Row]:
        """Newest first; ``before_id`` (an event id) pages further back; ``kinds`` and ``q``
        (0.26) narrow it the way the operator's page does, so a filter holds across pages."""
        with self._lock:
            where, fargs = self._event_where(kinds, q)
            sql = "SELECT id, ts, kind, detail, ip, ua FROM events WHERE account_id=?" + where
            args: list = [account_id, *fargs]
            if before_id:
                sql += " AND id<?"
                args.append(before_id)
            args.append(max(1, min(limit, 1000)))
            return self._conn.execute(sql + " ORDER BY id DESC LIMIT ?", args).fetchall()

    def event_count(self, account_id: str, kinds: tuple[str, ...] | None = None, q: str = "") -> int:
        with self._lock:
            where, fargs = self._event_where(kinds, q)
            row = self._conn.execute("SELECT COUNT(*) AS n FROM events WHERE account_id=?" + where, (account_id, *fargs)).fetchone()
        return int(row["n"]) if row else 0

    def events_recent(self, limit: int = 100, kinds: tuple[str, ...] | None = None, before_id: int = 0) -> list[sqlite3.Row]:
        """Everyone's timeline, newest first; ``before_id`` (0.26) reads on past the last row shown."""
        with self._lock:
            where, args = self._event_where(kinds, "")
            if before_id:
                where += " AND id<?"
                args.append(before_id)
            return self._conn.execute(
                f"SELECT id, account_id, ts, kind, detail, ip, ua FROM events WHERE 1=1{where} ORDER BY id DESC LIMIT ?",
                (*args, limit),
            ).fetchall()

    def event_counts(self, since: int) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT kind, COUNT(*) AS n FROM events WHERE ts>=? GROUP BY kind", (since,)).fetchall()
        return {r["kind"]: int(r["n"]) for r in rows}

    def delete_events(self, account_id: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM events WHERE account_id=?", (account_id,))

    # -- usage -----------------------------------------------------------------

    def charge(
        self,
        account_id: str,
        kind: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        charged: int,
        request_id: str,
        cost_uy: int = 0,
        extra: str = "",
    ) -> None:
        """Record one request: the tokens on the account, the line in the ledger. What the
        account has spent is always the ledger's sum, so there is nothing else to keep."""
        charged = max(0, int(charged))
        cost_uy = max(0, int(cost_uy))
        who = _client.current()
        with self.tx() as c:
            c.execute("UPDATE accounts SET used=used+? WHERE id=?", (charged, account_id))
            c.execute(
                "INSERT INTO ledger(account_id, ts, kind, model, prompt_tokens, completion_tokens, charged, request_id, cost_uy, extra, ip, ua) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    account_id,
                    now(),
                    kind,
                    model,
                    prompt_tokens,
                    completion_tokens,
                    charged,
                    request_id,
                    cost_uy,
                    extra or "",
                    who.ip,
                    who.ua,
                ),
            )

    USAGE_KINDS = ("chat", "image", "video", "realtime")

    def usage_by_kind(self, since: int, account_id: str | None = None) -> list[sqlite3.Row]:
        """Requests, tokens and money per kind since `since` — one account or everyone."""
        with self._lock:
            where = "ts>=? AND charged>=0 AND kind IN ('chat','image','video','realtime')"
            args: tuple = (since,)
            if account_id is not None:
                where += " AND account_id=?"
                args = (since, account_id)
            return self._conn.execute(
                f"""SELECT kind, COUNT(*) AS requests, SUM(prompt_tokens) AS prompt_tokens,
                           SUM(completion_tokens) AS completion_tokens, SUM(charged) AS charged, SUM(cost_uy) AS cost_uy
                    FROM ledger WHERE {where} GROUP BY kind ORDER BY cost_uy DESC""",
                args,
            ).fetchall()

    def usage_by_model(self, since: int, account_id: str | None = None) -> list[sqlite3.Row]:
        with self._lock:
            where = "ts>=? AND charged>=0 AND kind IN ('chat','image','video','realtime')"
            args: tuple = (since,)
            if account_id is not None:
                where += " AND account_id=?"
                args = (since, account_id)
            return self._conn.execute(
                f"""SELECT model, kind, COUNT(*) AS requests, SUM(prompt_tokens) AS prompt_tokens,
                           SUM(completion_tokens) AS completion_tokens, SUM(charged) AS charged, SUM(cost_uy) AS cost_uy
                    FROM ledger WHERE {where} GROUP BY model, kind ORDER BY cost_uy DESC""",
                args,
            ).fetchall()

    def usage_by_day_for(self, account_id: str, since: int, day_offset_s: int = 0) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """SELECT ((ts + ?) - (ts + ?) % 86400 - ?) AS day, kind, COUNT(*) AS requests,
                          SUM(charged) AS charged, SUM(cost_uy) AS cost_uy
                   FROM ledger WHERE account_id=? AND ts>=? AND charged>=0 AND kind IN ('chat','image','video','realtime')
                   GROUP BY day, kind ORDER BY day DESC""",
                (day_offset_s, day_offset_s, day_offset_s, account_id, since),
            ).fetchall()

    def active_accounts_since(self, since: int) -> int:
        with self._lock:
            r = self._conn.execute(
                "SELECT COUNT(DISTINCT account_id) FROM ledger WHERE ts>=? AND kind IN ('chat','image','video','realtime')",
                (since,),
            ).fetchone()
        return int(r[0])

    @staticmethod
    def _not_hashes(exclude_hashes: frozenset[str]) -> tuple[str, list[str]]:
        """An `AND id_hash NOT IN (...)` clause and its parameters — empty for no set. The
        reviewer's accounts (service.review_hashes) are left out of the sign-up counts."""
        if not exclude_hashes:
            return "", []
        hashes = sorted(exclude_hashes)
        return f" AND id_hash NOT IN ({','.join('?' * len(hashes))})", hashes

    def accounts_created_since(self, since: int, exclude_hashes: frozenset[str] = frozenset()) -> int:
        clause, params = self._not_hashes(exclude_hashes)
        with self._lock:
            r = self._conn.execute(f"SELECT COUNT(*) FROM accounts WHERE created_at>=?{clause}", [since, *params]).fetchone()
        return int(r[0])

    # -- the operator's time series ----------------------------------------------------

    _DAY = "((ts + ?) - (ts + ?) % 86400 - ?)"

    def events_by_day(self, since: int, day_offset_s: int = 0) -> list[sqlite3.Row]:
        """How many events of each kind per local day since `since`."""
        with self._lock:
            return self._conn.execute(
                f"SELECT {self._DAY} AS day, kind, COUNT(*) AS n FROM events WHERE ts>=? GROUP BY day, kind",
                (day_offset_s, day_offset_s, day_offset_s, since),
            ).fetchall()

    def accounts_by_day(self, since: int, day_offset_s: int = 0, exclude_hashes: frozenset[str] = frozenset()) -> list[sqlite3.Row]:
        clause, params = self._not_hashes(exclude_hashes)
        with self._lock:
            return self._conn.execute(
                f"SELECT {self._DAY.replace('ts', 'created_at')} AS day, COUNT(*) AS n FROM accounts WHERE created_at>=?{clause} GROUP BY day",
                [day_offset_s, day_offset_s, day_offset_s, since, *params],
            ).fetchall()

    def active_by_day(self, since: int, day_offset_s: int = 0) -> list[sqlite3.Row]:
        """Accounts that made at least one charged call, per local day."""
        with self._lock:
            return self._conn.execute(
                f"""SELECT {self._DAY} AS day, COUNT(DISTINCT account_id) AS n FROM ledger
                    WHERE ts>=? AND kind IN ('chat','image','video','realtime') GROUP BY day""",
                (day_offset_s, day_offset_s, day_offset_s, since),
            ).fetchall()

    def devices_by_kind_os(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute("SELECT kind, os, COUNT(*) AS n FROM devices GROUP BY kind, os ORDER BY n DESC").fetchall()

    def invite_funnel(self) -> dict[str, int]:
        """Who asked for a code, whose code brought someone, who came through one."""
        with self._lock:
            r = self._conn.execute(
                """SELECT SUM(CASE WHEN invite_code<>'' THEN 1 ELSE 0 END) AS with_code,
                          SUM(CASE WHEN invites>0 THEN 1 ELSE 0 END) AS inviters,
                          SUM(CASE WHEN invited_by<>'' THEN 1 ELSE 0 END) AS invited,
                          SUM(CASE WHEN contribute_bonus_at IS NOT NULL THEN 1 ELSE 0 END) AS contribute_bonuses
                   FROM accounts"""
            ).fetchone()
        return {k: int(r[k] or 0) for k in ("with_code", "inviters", "invited", "contribute_bonuses")}

    def account_counts(self) -> dict[str, int]:
        with self._lock:
            r = self._conn.execute(
                """SELECT COUNT(*) AS total, SUM(disabled) AS disabled, SUM(unlimited) AS unlimited,
                          SUM(CASE WHEN password_hash<>'' THEN 1 ELSE 0 END) AS with_password
                   FROM accounts"""
            ).fetchone()
            keys = self._conn.execute("SELECT COUNT(*) FROM api_keys WHERE revoked_at IS NULL").fetchone()
            devices = self._conn.execute("SELECT COUNT(*) FROM devices").fetchone()
        return {
            "total": int(r["total"] or 0),
            "disabled": int(r["disabled"] or 0),
            "unlimited": int(r["unlimited"] or 0),
            "with_password": int(r["with_password"] or 0),
            "live_keys": int(keys[0]),
            "devices": int(devices[0]),
        }

    def totals_since(self, since: int) -> sqlite3.Row:
        with self._lock:
            return self._conn.execute(
                """SELECT COUNT(*) AS requests, COALESCE(SUM(charged),0) AS charged, COALESCE(SUM(cost_uy),0) AS cost_uy,
                          COALESCE(SUM(prompt_tokens),0) AS prompt_tokens, COALESCE(SUM(completion_tokens),0) AS completion_tokens
                   FROM ledger WHERE ts>=? AND kind IN ('chat','image','video','realtime')""",
                (since,),
            ).fetchone()

    def top_accounts_since(self, since: int, limit: int = 10) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """SELECT account_id, COUNT(*) AS requests, SUM(cost_uy) AS cost_uy, SUM(charged) AS charged
                   FROM ledger WHERE ts>=? AND kind IN ('chat','image','video','realtime')
                   GROUP BY account_id ORDER BY cost_uy DESC LIMIT ?""",
                (since, limit),
            ).fetchall()

    def used_since(self, account_id: str, since: int) -> int:
        with self._lock:
            r = self._conn.execute(
                "SELECT COALESCE(SUM(charged),0) FROM ledger WHERE account_id=? AND ts>=? AND charged>0",
                (account_id, since),
            ).fetchone()
        return int(r[0])

    def pending_video_cost(self, account_id: str) -> int:
        """Money (micro-yuan) the account's clips still being made will cost: tasks the
        provider has not finished, so not yet in the ledger — held against the allowance."""
        with self._lock:
            r = self._conn.execute(
                "SELECT COALESCE(SUM(cost_uy),0) FROM video_tasks WHERE account_id=? AND charged=0 "
                "AND probe=0 AND status NOT IN ('FAILED','CANCELED','UNKNOWN') AND created_at >= ?",
                (account_id, now() - self.VIDEO_HOLD_S),
            ).fetchone()
        return int(r[0])

    def spent_since(self, account_id: str, since: int) -> int:
        """Money (micro-yuan) the account cost the operator since `since`."""
        with self._lock:
            r = self._conn.execute(
                "SELECT COALESCE(SUM(cost_uy),0) FROM ledger WHERE account_id=? AND ts>=? AND cost_uy>0",
                (account_id, since),
            ).fetchone()
        return int(r[0])

    def events_since(self, since: int) -> dict[str, int]:
        """How many events of each kind since `since`, across every account (the self-check)."""
        with self._lock:
            rows = self._conn.execute("SELECT kind, COUNT(*) AS n FROM events WHERE ts>=? GROUP BY kind", (since,)).fetchall()
        return {str(r["kind"]): int(r["n"]) for r in rows}

    def requests_since_all(self, since: int) -> int:
        """Model requests since `since`, across every account (the self-check)."""
        with self._lock:
            r = self._conn.execute(
                "SELECT COUNT(*) FROM ledger WHERE ts>=? AND kind IN ('chat','image','video','realtime')", (since,)
            ).fetchone()
        return int(r[0])

    def health(self) -> dict:
        """The file: its size, and whether a write goes through right now."""
        size = 0
        try:
            size = Path(self.path).stat().st_size if self.path != ":memory:" else 0
        except OSError:
            pass
        writable = True
        try:
            with self.tx() as c:
                c.execute("CREATE TABLE IF NOT EXISTS health_probe (ts INTEGER)")
                c.execute("DELETE FROM health_probe")
                c.execute("INSERT INTO health_probe(ts) VALUES (?)", (now(),))
        except sqlite3.Error:
            writable = False
        return {"size_bytes": size, "writable": writable}

    def requests_since(self, account_id: str, since: int) -> int:
        with self._lock:
            r = self._conn.execute(
                "SELECT COUNT(*) FROM ledger WHERE account_id=? AND ts>=? AND kind IN ('chat','image','video','realtime')",
                (account_id, since),
            ).fetchone()
        return int(r[0])

    @staticmethod
    def _ledger_where(kinds: tuple[str, ...] | None, q: str) -> tuple[str, list]:
        """The operator's filter on a statement: these kinds (any of them) and a text the model
        name or the line's note contains. Empty means every line."""
        where, args = "", []
        if kinds:
            where += f" AND kind IN ({','.join('?' * len(kinds))})"
            args.extend(kinds)
        if q:
            where += " AND (model LIKE ? ESCAPE '\\' OR extra LIKE ? ESCAPE '\\')"
            args.extend([_like(q), _like(q)])
        return where, args

    def recent_ledger(
        self,
        account_id: str,
        limit: int = 30,
        before_id: int = 0,
        kinds: tuple[str, ...] | None = None,
        q: str = "",
    ) -> list[sqlite3.Row]:
        """Newest first; ``before_id`` (a ledger id) pages further back, to the first line;
        ``kinds`` and ``q`` (0.26) narrow it so a filter holds across pages."""
        with self._lock:
            where, fargs = self._ledger_where(kinds, q)
            sql = (
                "SELECT id, ts, kind, model, prompt_tokens, completion_tokens, charged, cost_uy, extra, ip, ua "
                "FROM ledger WHERE account_id=?" + where
            )
            args: list = [account_id, *fargs]
            if before_id:
                sql += " AND id<?"
                args.append(before_id)
            args.append(max(1, min(limit, 1000)))
            return self._conn.execute(sql + " ORDER BY id DESC LIMIT ?", args).fetchall()

    def ledger_count(self, account_id: str, kinds: tuple[str, ...] | None = None, q: str = "") -> int:
        with self._lock:
            where, fargs = self._ledger_where(kinds, q)
            row = self._conn.execute("SELECT COUNT(*) AS n FROM ledger WHERE account_id=?" + where, (account_id, *fargs)).fetchone()
        return int(row["n"]) if row else 0

    def addresses_for(self, account_id: str) -> list[sqlite3.Row]:
        """Every address the account was seen from, across sign-ins, requests and events:
        how often, first and last — the operator's view of where an account lives."""
        with self._lock:
            return self._conn.execute(
                """SELECT ip, SUM(n) AS n, MIN(first) AS first_seen, MAX(last) AS last_seen,
                          GROUP_CONCAT(DISTINCT ua) AS uas
                   FROM (
                     SELECT ip, COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last, ua FROM ledger WHERE account_id=? AND ip<>'' GROUP BY ip, ua
                     UNION ALL
                     SELECT ip, COUNT(*) AS n, MIN(created_at) AS first, MAX(created_at) AS last, ua FROM api_keys WHERE account_id=? AND ip<>'' GROUP BY ip, ua
                     UNION ALL
                     SELECT ip, COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last, ua FROM events WHERE account_id=? AND ip<>'' GROUP BY ip, ua
                   ) GROUP BY ip ORDER BY last_seen DESC""",
                (account_id, account_id, account_id),
            ).fetchall()

    def address_counts(self, since: int) -> dict[str, list[tuple[str, int]]]:
        """``(ip, n)`` rows for the "where from" table: accounts by their latest address,
        the period's requests by address (the ledger), its sign-ins by address (the keys)
        and its new accounts by first address."""
        with self._lock:
            accounts = self._conn.execute("SELECT last_ip AS ip, COUNT(*) AS n FROM accounts WHERE last_ip<>'' GROUP BY last_ip").fetchall()
            requests = self._conn.execute("SELECT ip, COUNT(*) AS n FROM ledger WHERE ts>=? AND ip<>'' GROUP BY ip", (since,)).fetchall()
            signins = self._conn.execute(
                "SELECT ip, COUNT(*) AS n FROM api_keys WHERE created_at>=? AND ip<>'' GROUP BY ip", (since,)
            ).fetchall()
            new = self._conn.execute(
                "SELECT first_ip AS ip, COUNT(*) AS n FROM accounts WHERE created_at>=? AND first_ip<>'' GROUP BY first_ip", (since,)
            ).fetchall()
        return {
            "accounts": [(r["ip"], int(r["n"])) for r in accounts],
            "requests": [(r["ip"], int(r["n"])) for r in requests],
            "signins": [(r["ip"], int(r["n"])) for r in signins],
            "new_accounts": [(r["ip"], int(r["n"])) for r in new],
        }

    def accounts_at_address(self, ip: str) -> list[sqlite3.Row]:
        """The accounts seen from one address (sign-ins, requests, events): the same person
        on two accounts, or a household — the operator decides which."""
        with self._lock:
            return self._conn.execute(
                """SELECT a.id, a.hint, a.channel, a.created_at, SUM(x.n) AS n, MAX(x.last) AS last_seen
                   FROM (
                     SELECT account_id, COUNT(*) AS n, MAX(ts) AS last FROM ledger WHERE ip=? GROUP BY account_id
                     UNION ALL
                     SELECT account_id, COUNT(*) AS n, MAX(created_at) AS last FROM api_keys WHERE ip=? GROUP BY account_id
                     UNION ALL
                     SELECT account_id, COUNT(*) AS n, MAX(ts) AS last FROM events WHERE ip=? AND account_id<>'' GROUP BY account_id
                   ) x JOIN accounts a ON a.id=x.account_id
                   GROUP BY a.id ORDER BY last_seen DESC""",
                (ip, ip, ip),
            ).fetchall()

    # -- devices (the hub) ---------------------------------------------------------

    def upsert_device(
        self,
        account_id: str,
        device_id: str,
        name: str,
        kind: str,
        os: str,
        version: str,
        actions: str,
        llm_provider: str = "",
        llm_model: str = "",
    ) -> None:
        """A device's hello. `llm_provider` / `llm_model` (0.28) are what it said it runs
        the model under, kept as said; empty keeps what an earlier hello said (an older
        client that does not send them must not erase a newer one's word)."""
        t = now()
        ip = _client.current().ip
        with self.tx() as c:
            c.execute(
                """INSERT INTO devices(account_id, id, name, kind, os, version, actions, first_seen, last_seen, ip, llm_provider, llm_model)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(account_id, id) DO UPDATE SET
                     name=excluded.name, kind=excluded.kind, os=excluded.os, version=excluded.version,
                     actions=excluded.actions, last_seen=excluded.last_seen,
                     ip=CASE WHEN excluded.ip<>'' THEN excluded.ip ELSE devices.ip END,
                     llm_provider=CASE WHEN excluded.llm_provider<>'' THEN excluded.llm_provider ELSE devices.llm_provider END,
                     llm_model=CASE WHEN excluded.llm_model<>'' THEN excluded.llm_model ELSE devices.llm_model END""",
                (account_id, device_id, name, kind, os, version, actions, t, t, ip, llm_provider[:60], llm_model[:80]),
            )

    def touch_device(self, account_id: str, device_id: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE devices SET last_seen=? WHERE account_id=? AND id=?", (now(), account_id, device_id))

    def devices_for(self, account_id: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT id, name, kind, os, version, actions, first_seen, last_seen, ip FROM devices WHERE account_id=? ORDER BY last_seen DESC",
                (account_id,),
            ).fetchall()

    def forget_device(self, account_id: str, device_id: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM devices WHERE account_id=? AND id=?", (account_id, device_id))

    # -- the profile (name and look shared by the account's devices) -----------------

    def profile(self, account_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT rev, updated_at, device, body, face, connectors FROM profiles WHERE account_id=?", (account_id,)
            ).fetchone()

    def put_profile(self, account_id: str, device: str, body: str | None, face: str | None, connectors: str | None = None) -> int:
        """Store the profile and return its new rev. ``face`` None keeps the stored face
        (a rename should not cost the pictures a round trip); "" clears it. ``body`` None
        keeps the stored look (a device writing only its connectors); ``connectors`` None
        keeps the stored list — the service merges by device before it gets here (0.17)."""
        with self.tx() as c:
            row = c.execute("SELECT rev, body, face, connectors FROM profiles WHERE account_id=?", (account_id,)).fetchone()
            rev = (int(row["rev"]) if row else 0) + 1
            kept_face = face if face is not None else (str(row["face"]) if row else "")
            kept_body = body if body is not None else (str(row["body"]) if row else "{}")
            kept_conn = connectors if connectors is not None else (str(row["connectors"]) if row else "[]")
            c.execute(
                """INSERT INTO profiles(account_id, rev, updated_at, device, body, face, connectors) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(account_id) DO UPDATE SET
                     rev=excluded.rev, updated_at=excluded.updated_at, device=excluded.device,
                     body=excluded.body, face=excluded.face, connectors=excluded.connectors""",
                (account_id, rev, now(), device, kept_body, kept_face, kept_conn),
            )
            return rev

    def delete_profile(self, account_id: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM profiles WHERE account_id=?", (account_id,))

    # -- video tasks (the provider's async API, relayed) --------------------------

    def insert_video_task(self, task_id: str, account_id: str, model: str, cost_uy: int = 0, probe: bool = False) -> None:
        t = now()
        with self.tx() as c:
            # a second insert for the same task (a retried poll) must not forget that it was charged
            c.execute(
                "INSERT INTO video_tasks(task_id, account_id, model, created_at, cost_uy, probe) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET model=excluded.model, cost_uy=excluded.cost_uy",
                (task_id, account_id, model, t, max(0, int(cost_uy)), 1 if probe else 0),
            )
            c.execute("DELETE FROM video_tasks WHERE created_at < ?", (t - self.VIDEO_KEEP_S,))

    def video_task(self, task_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM video_tasks WHERE task_id=?", (task_id,)).fetchone()

    def set_video_status(self, task_id: str, status: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE video_tasks SET status=? WHERE task_id=?", (status[:20], task_id))

    def mark_video_charged(self, task_id: str) -> bool:
        """True the first time only, so a clip is charged once however often it is polled."""
        with self.tx() as c:
            cur = c.execute("UPDATE video_tasks SET charged=1 WHERE task_id=? AND charged=0", (task_id,))
            return cur.rowcount == 1

    VIDEO_HOLD_S = 3600  # how long a task's price is held against the allowance (pending_video_cost)
    VIDEO_KEEP_S = 3 * 86400  # how long a task row is kept (insert_video_task purges older ones)

    def video_tasks_to_settle(self, limit: int = 5, first_after_s: int = 3000) -> list[sqlite3.Row]:
        """Tasks the relay should ask the provider about itself (0.24): still unsettled and
        never polled to an end by the app, once shortly before the hold lapses
        (`first_after_s` after submission) and once more shortly before the row is purged.
        A handful per call, oldest first; a task answered FAILED/CANCELED/UNKNOWN, charged,
        or a probe is not asked about."""
        t = now()
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM video_tasks WHERE charged=0 AND probe=0 "
                "AND status NOT IN ('FAILED','CANCELED','UNKNOWN') "
                "AND ((checks=0 AND created_at <= ?) OR (checks=1 AND created_at <= ?)) "
                "ORDER BY created_at LIMIT ?",
                (t - first_after_s, t - (self.VIDEO_KEEP_S - self.VIDEO_HOLD_S), max(1, int(limit))),
            ).fetchall()
        return list(rows)

    def note_video_check(self, task_id: str) -> None:
        """The relay asked the provider about this task and got an answer."""
        with self.tx() as c:
            c.execute("UPDATE video_tasks SET checks=checks+1 WHERE task_id=?", (task_id,))

    # -- 0.28: chat call telemetry (analytics.py) ------------------------------------------------

    CALL_COLUMNS = (
        "ts",
        "account_id",
        "model",
        "platform",
        "family",
        "status",
        "detail",
        "stream",
        "wait_ms",
        "ttft_ms",
        "total_ms",
        "prompt_tokens",
        "completion_tokens",
        "cached_tokens",
        "messages",
        "images",
        "tools",
        "tool_names",
        "hands",
        "retries",
        "request_id",
        "run",
    )

    def add_call(self, row: dict[str, Any]) -> int:
        """One handled chat request (the columns of `calls`; missing ones take their defaults)."""
        cols = [c for c in self.CALL_COLUMNS if c in row]
        with self.tx() as c:
            cur = c.execute(
                f"INSERT INTO calls({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [row[k] for k in cols],
            )
            return int(cur.lastrowid or 0)

    def sweep_calls(self, before: int) -> int:
        with self.tx() as c:
            return c.execute("DELETE FROM calls WHERE ts<?", (before,)).rowcount

    def sweep_events(self, before: int) -> int:
        """The timelines' lines older than `before` go, except the `account.deleted` ones (the
        statistics' only trace of a deletion) and the operator's `control_audit`, which is
        kept whole. The leftovers of the retired media proxy (`video_tasks`, otherwise only
        purged when a new task is written) go with them."""
        with self.tx() as c:
            n = c.execute("DELETE FROM events WHERE ts<? AND kind<>'account.deleted'", (before,)).rowcount
            c.execute("DELETE FROM video_tasks WHERE created_at<?", (now() - self.VIDEO_KEEP_S,))
            return n

    def calls_since(self, since: int, limit: int = 20000) -> list[sqlite3.Row]:
        """Every call since `since`, oldest first (the live meter's warm-up after a restart).
        Over ``limit`` rows it is the newest that are kept, so a busy hour's latest minutes
        are the ones the live page shows."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM calls WHERE ts>=? ORDER BY id DESC LIMIT ?", (since, limit)).fetchall()
            rows.reverse()
            return rows

    def calls_between(self, since: int, until: int) -> list[sqlite3.Row]:
        """The figures of every call of a window, without the ids: what the drill-downs and
        the platform comparison compute percentiles from (a day is tens of thousands of rows)."""
        with self._lock:
            return self._conn.execute(
                """SELECT ts, account_id, model, platform, family, status, stream, wait_ms, ttft_ms, total_ms,
                          prompt_tokens, completion_tokens, messages, images, tools, hands, retries
                   FROM calls WHERE ts>=? AND ts<?""",
                (since, until),
            ).fetchall()

    def calls_by_platform(self, since: int, until: int) -> list[sqlite3.Row]:
        """Per platform over a window: how many calls, how they ended, what they carried; the
        aggregation stays in SQLite (a season is hundreds of thousands of rows)."""
        with self._lock:
            return self._conn.execute(
                """SELECT platform, COUNT(*) AS n, SUM(status='ok') AS ok,
                          SUM(status IN ('upstream_error','upstream_timeout','broken')) AS errors,
                          SUM(status='refused') AS refused, SUM(COALESCE(hands, 0)) AS hands,
                          SUM(COALESCE(images, 0)>0) AS images, SUM(COALESCE(tools, 0)>0) AS tools,
                          SUM(COALESCE(stream, 0)) AS stream, SUM(COALESCE(messages, 0)) AS messages
                   FROM calls WHERE ts>=? AND ts<? GROUP BY platform""",
                (since, until),
            ).fetchall()

    def calls_latency_by_platform(self, since: int, until: int) -> list[sqlite3.Row]:
        """Per platform over a window: the nearest-rank percentiles of the waits (every call)
        and of the time to the first token and the total (the calls that went well), the
        same figures `analytics.percentile` gives, ranked by SQLite's window functions."""
        with self._lock:
            return self._conn.execute(
                """WITH w AS (
                       SELECT platform, status='ok' AS ok, wait_ms, ttft_ms, total_ms,
                              ROW_NUMBER() OVER (PARTITION BY platform ORDER BY wait_ms) AS r_wait,
                              COUNT(*) OVER (PARTITION BY platform) AS n_all,
                              ROW_NUMBER() OVER (PARTITION BY platform, status='ok' ORDER BY ttft_ms) AS r_ttft,
                              ROW_NUMBER() OVER (PARTITION BY platform, status='ok' ORDER BY total_ms) AS r_total,
                              COUNT(*) OVER (PARTITION BY platform, status='ok') AS n_ok
                       FROM calls WHERE ts>=? AND ts<?)
                   SELECT platform,
                          MAX(CASE WHEN r_wait=(95*n_all+99)/100 THEN wait_ms END) AS p95_wait_ms,
                          MAX(CASE WHEN ok AND r_ttft=(n_ok+1)/2 THEN ttft_ms END) AS p50_ttft_ms,
                          MAX(CASE WHEN ok AND r_ttft=(95*n_ok+99)/100 THEN ttft_ms END) AS p95_ttft_ms,
                          MAX(CASE WHEN ok AND r_total=(n_ok+1)/2 THEN total_ms END) AS p50_total_ms
                   FROM w GROUP BY platform""",
                (since, until),
            ).fetchall()

    def calls_by_day(self, since: int, day_offset_s: int = 0) -> list[sqlite3.Row]:
        """Per local day and platform: calls, how they ended, screen-operation turns, pictures,
        tools offered, accounts — the hands page and the platform series."""
        with self._lock:
            return self._conn.execute(
                f"""SELECT {self._DAY} AS day, platform, COUNT(*) AS n,
                           SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok,
                           SUM(CASE WHEN status IN ('upstream_error','upstream_timeout','broken') THEN 1 ELSE 0 END) AS errors,
                           SUM(CASE WHEN status='refused' THEN 1 ELSE 0 END) AS refused,
                           SUM(hands) AS hands, SUM(CASE WHEN images>0 THEN 1 ELSE 0 END) AS with_images,
                           SUM(CASE WHEN tools>0 THEN 1 ELSE 0 END) AS with_tools,
                           COUNT(DISTINCT account_id) AS accounts,
                           COUNT(DISTINCT CASE WHEN hands=1 THEN account_id END) AS hands_accounts
                    FROM calls WHERE ts>=? GROUP BY day, platform ORDER BY day""",
                (day_offset_s, day_offset_s, day_offset_s, since),
            ).fetchall()

    def calls_tool_names(self, since: int, limit: int = 2000) -> list[sqlite3.Row]:
        """The distinct tool-name strings of the window with their counts, for the hands page
        to split and rank (a few hundred distinct strings; the names are the clients' own)."""
        with self._lock:
            return self._conn.execute(
                "SELECT tool_names, platform, COUNT(*) AS n FROM calls WHERE ts>=? AND tool_names<>'' GROUP BY tool_names, platform ORDER BY n DESC LIMIT ?",
                (since, limit),
            ).fetchall()

    def calls_hands_accounts(self, since: int) -> list[sqlite3.Row]:
        """The accounts that ran a screen-operation turn in the window: how many, when first and last, on what."""
        with self._lock:
            return self._conn.execute(
                """SELECT account_id, COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts,
                          GROUP_CONCAT(DISTINCT platform) AS platforms,
                          SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok
                   FROM calls WHERE ts>=? AND hands=1 GROUP BY account_id ORDER BY n DESC LIMIT 500""",
                (since,),
            ).fetchall()

    def calls_refused_by_family(self, since: int, limit: int = 30) -> list[sqlite3.Row]:
        """The clients the `apps_only` switch turned away in the window, by family: calls,
        accounts, the last one (what the Non-app traffic page shows once the switch is on and
        the ledger no longer sees them)."""
        with self._lock:
            return self._conn.execute(
                """SELECT family, COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts, MAX(ts) AS last_ts
                   FROM calls WHERE ts>=? AND status='refused' AND detail='client_not_supported'
                   GROUP BY family ORDER BY n DESC LIMIT ?""",
                (since, limit),
            ).fetchall()

    def calls_for_account(self, account_id: str, since: int) -> sqlite3.Row:
        """One account's calls in the window: how many, how they ended, how long they took."""
        with self._lock:
            return self._conn.execute(
                """SELECT COUNT(*) AS n, SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok,
                          SUM(CASE WHEN status IN ('upstream_error','upstream_timeout','broken') THEN 1 ELSE 0 END) AS errors,
                          SUM(CASE WHEN status='refused' THEN 1 ELSE 0 END) AS refused,
                          SUM(hands) AS hands, SUM(images) AS images, SUM(CASE WHEN tools>0 THEN 1 ELSE 0 END) AS with_tools,
                          AVG(CASE WHEN status='ok' THEN ttft_ms END) AS avg_ttft_ms,
                          AVG(CASE WHEN status='ok' THEN total_ms END) AS avg_total_ms,
                          AVG(wait_ms) AS avg_wait_ms, MAX(ts) AS last_ts
                   FROM calls WHERE account_id=? AND ts>=?""",
                (account_id, since),
            ).fetchone()

    def calls_count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0])

    # -- 0.28: the usage matrix and its drill-downs (analytics.py) --------------------------

    #: a chat line's cached prompt tokens, as charge_chat wrote them into `extra` (JSON when
    #: anything applied, '' otherwise; json_extract would fail on the empty string)
    _LEDGER_CACHED = "CASE WHEN extra LIKE '{%' THEN COALESCE(json_extract(extra, '$.cached_tokens'), 0) ELSE 0 END"

    def usage_by_day_model(self, since: int, day_offset_s: int = 0) -> list[sqlite3.Row]:
        """Per local day and model: requests, tokens (and how many of the prompt's the provider
        served from its cache), money, accounts (the usage matrix)."""
        with self._lock:
            return self._conn.execute(
                f"""SELECT {self._DAY} AS day, model, kind, COUNT(*) AS requests, SUM(prompt_tokens) AS prompt_tokens,
                           SUM(completion_tokens) AS completion_tokens, SUM({self._LEDGER_CACHED}) AS cached_tokens,
                           SUM(cost_uy) AS cost_uy, COUNT(DISTINCT account_id) AS accounts
                    FROM ledger WHERE ts>=? AND charged>=0 AND kind IN ('chat','image','video','realtime')
                    GROUP BY day, model, kind ORDER BY day""",
                (day_offset_s, day_offset_s, day_offset_s, since),
            ).fetchall()

    def own_usage_by_provider(self, since: int) -> list[sqlite3.Row]:
        """The turns people ran on keys of their own and sent up (source 'own'), per provider
        and model: turns, accounts, tokens and the cached part of the prompts (0.31 on; older
        turns count 0 cached). From the figures rows (own_figures), never the turns: a turn's
        provider sits in its meta and its cached count past the bodies, and reading them for a
        week of own turns walked every body (0.31.0 did, and a call took minutes on a large
        file). Own turns kept before 0.31.1 count once the backfill has written their rows."""
        with self._lock:
            return self._conn.execute(
                """SELECT provider, model, COUNT(*) AS turns, COUNT(DISTINCT account_id) AS accounts,
                          SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens,
                          SUM(cached_tokens) AS cached_tokens
                   FROM own_figures WHERE ts>=? GROUP BY provider, model ORDER BY turns DESC""",
                (since,),
            ).fetchall()

    def usage_by_hour_model(self, since: int, until: int, day_offset_s: int = 0) -> list[sqlite3.Row]:
        """Per local hour and model inside one window (a day's drill-down)."""
        with self._lock:
            return self._conn.execute(
                """SELECT ((ts + ?) % 86400) / 3600 AS hour, model, COUNT(*) AS requests, SUM(prompt_tokens) AS prompt_tokens,
                          SUM(completion_tokens) AS completion_tokens, SUM(cost_uy) AS cost_uy, COUNT(DISTINCT account_id) AS accounts
                   FROM ledger WHERE ts>=? AND ts<? AND charged>=0 AND kind IN ('chat','image','video','realtime')
                   GROUP BY hour, model ORDER BY hour""",
                (day_offset_s, since, until),
            ).fetchall()

    def usage_by_ua(self, since: int, until: int | None = None) -> list[sqlite3.Row]:
        """Per user agent string in the window: requests, tokens, money and the accounts
        behind it — a few thousand rows at most; the caller folds them into platforms and
        families (client.py) and counts accounts once per group from `account_ua_pairs`."""
        with self._lock:
            until_clause = " AND ts<?" if until is not None else ""
            args: tuple = (since, until) if until is not None else (since,)
            return self._conn.execute(
                f"""SELECT ua, COUNT(*) AS requests, SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens,
                           SUM(cost_uy) AS cost_uy, COUNT(DISTINCT account_id) AS accounts
                    FROM ledger WHERE ts>=?{until_clause} AND charged>=0 AND kind IN ('chat','image','video','realtime')
                    GROUP BY ua ORDER BY requests DESC""",
                args,
            ).fetchall()

    def account_ua_pairs(self, since: int, until: int | None = None) -> list[sqlite3.Row]:
        """The distinct (account, user agent) pairs of the window with the requests of each,
        so accounts can be counted once per platform and the accounts on two platforms found."""
        with self._lock:
            until_clause = " AND ts<?" if until is not None else ""
            args: tuple = (since, until) if until is not None else (since,)
            return self._conn.execute(
                f"""SELECT account_id, ua, COUNT(*) AS requests FROM ledger
                    WHERE ts>=?{until_clause} AND charged>=0 AND kind IN ('chat','image','video','realtime')
                    GROUP BY account_id, ua""",
                args,
            ).fetchall()

    def top_accounts_between(self, since: int, until: int, limit: int = 50) -> list[sqlite3.Row]:
        """The accounts that cost most inside one window, with the client they last used."""
        with self._lock:
            return self._conn.execute(
                """SELECT account_id, COUNT(*) AS requests, SUM(charged) AS charged, SUM(cost_uy) AS cost_uy,
                          SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens, MAX(ua) AS ua
                   FROM ledger WHERE ts>=? AND ts<? AND charged>=0 AND kind IN ('chat','image','video','realtime')
                   GROUP BY account_id ORDER BY cost_uy DESC LIMIT ?""",
                (since, until, limit),
            ).fetchall()

    def event_details_between(self, kind: str, since: int, until: int, limit: int = 30) -> list[sqlite3.Row]:
        """The most frequent `detail` lines of one event kind in a window (why requests failed)."""
        with self._lock:
            return self._conn.execute(
                "SELECT detail, COUNT(*) AS n FROM events WHERE kind=? AND ts>=? AND ts<? GROUP BY detail ORDER BY n DESC LIMIT ?",
                (kind, since, until, limit),
            ).fetchall()

    def events_by_hour(self, since: int, until: int, day_offset_s: int = 0) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT ((ts + ?) % 86400) / 3600 AS hour, kind, COUNT(*) AS n FROM events WHERE ts>=? AND ts<? GROUP BY hour, kind",
                (day_offset_s, since, until),
            ).fetchall()

    def account_versions(self) -> list[sqlite3.Row]:
        """Every account's last user agent with how many share it: the platform and version
        mix of the people as they stand now (client.py folds the strings)."""
        with self._lock:
            return self._conn.execute(
                "SELECT last_ua, COUNT(*) AS n, SUM(disabled) AS disabled, MAX(last_seen_at) AS last_seen_at FROM accounts GROUP BY last_ua"
            ).fetchall()

    def keys_by_ua(self, since: int) -> list[sqlite3.Row]:
        """Sign-ins (keys issued) since `since` per user agent: which clients people sign in from."""
        with self._lock:
            return self._conn.execute(
                "SELECT ua, COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts FROM api_keys WHERE created_at>=? GROUP BY ua ORDER BY n DESC",
                (since,),
            ).fetchall()

    def shared_first_addresses(self, at_least: int = 5, limit: int = 100) -> list[sqlite3.Row]:
        """Addresses that signed up `at_least` accounts: a household, a campus, or one person many times."""
        with self._lock:
            return self._conn.execute(
                """SELECT first_ip AS ip, COUNT(*) AS accounts, SUM(disabled) AS disabled, MIN(created_at) AS first_at, MAX(created_at) AS last_at
                   FROM accounts WHERE first_ip<>'' GROUP BY first_ip HAVING COUNT(*)>=? ORDER BY accounts DESC LIMIT ?""",
                (at_least, limit),
            ).fetchall()

    def account_ua_usage(self, since: int, limit: int = 3000) -> list[sqlite3.Row]:
        """Per account and user agent in the window, the heaviest first: the abuse page's
        suspects are the ones whose client is not one of the apps."""
        with self._lock:
            return self._conn.execute(
                """SELECT l.account_id, l.ua, COUNT(*) AS requests, SUM(l.prompt_tokens) AS prompt_tokens,
                          SUM(l.completion_tokens) AS completion_tokens, SUM(l.cost_uy) AS cost_uy, MAX(l.ts) AS last_ts,
                          a.hint, a.channel, a.disabled, a.created_at, a.unlimited
                   FROM ledger l JOIN accounts a ON a.id=l.account_id
                   WHERE l.ts>=? AND l.charged>=0 AND l.kind IN ('chat','image','video','realtime')
                   GROUP BY l.account_id, l.ua ORDER BY requests DESC LIMIT ?""",
                (since, limit),
            ).fetchall()

    # -- 0.28: cohorts — the pool, what came after it, retention (analytics.py) ------------------

    def pool_cohort_rows(self) -> list[sqlite3.Row]:
        """Per account: when it came, its pool and what it spent, its first and last charged
        chat, its first refusal for budget, when it was last seen at all — the funnel from
        sign-up through the free allowance to what came after."""
        with self._lock:
            return self._conn.execute(
                """SELECT a.id, a.id_hash, a.created_at, a.unlimited, a.disabled, a.grant_uy, a.last_seen_at, a.last_ua, a.invited_by,
                          COALESCE(l.spent_uy, 0) AS spent_uy, COALESCE(l.chats, 0) AS chats, l.first_chat, l.last_chat,
                          r.first_refused, r.refusals
                   FROM accounts a
                   LEFT JOIN (SELECT account_id, SUM(CASE WHEN cost_uy>0 THEN cost_uy ELSE 0 END) AS spent_uy,
                                     SUM(CASE WHEN kind IN ('chat','image','video','realtime') THEN 1 ELSE 0 END) AS chats,
                                     MIN(CASE WHEN kind IN ('chat','image','video','realtime') THEN ts END) AS first_chat,
                                     MAX(CASE WHEN kind IN ('chat','image','video','realtime') THEN ts END) AS last_chat
                              FROM ledger GROUP BY account_id) l ON l.account_id=a.id
                   LEFT JOIN (SELECT account_id, MIN(ts) AS first_refused, COUNT(*) AS refusals
                              FROM events WHERE kind='budget.refused' GROUP BY account_id) r ON r.account_id=a.id"""
            ).fetchall()

    def active_days_by_account(self, since: int) -> list[sqlite3.Row]:
        """The UTC days each account made any authenticated call (the `daily` table's
        `active` rows), since `since` — retention by any use, not only model use."""
        with self._lock:
            return self._conn.execute(
                "SELECT key AS account_id, day FROM daily WHERE metric='active' AND day>=? AND key<>''", (since,)
            ).fetchall()

    def chat_days_by_account(self, since: int) -> list[sqlite3.Row]:
        """The UTC days each account made a charged model request, since `since`."""
        with self._lock:
            return self._conn.execute(
                """SELECT account_id, (ts - ts % 86400) AS day FROM ledger
                   WHERE ts>=? AND kind IN ('chat','image','video','realtime') GROUP BY account_id, day""",
                (since,),
            ).fetchall()

    def sync_assistant_accounts(self, since: int) -> list[sqlite3.Row]:
        """Accounts whose devices synced an assistant message written since `since`, with how
        many: a model answered them somewhere — on the relay, or under a key of their own."""
        with self._lock:
            return self._conn.execute(
                """SELECT account_id, COUNT(*) AS n, MAX(created_at) AS last_at FROM sync_messages
                   WHERE role='assistant' AND deleted=0 AND created_at>=? GROUP BY account_id""",
                (since,),
            ).fetchall()

    def chat_accounts_since(self, since: int) -> set[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT account_id FROM ledger WHERE ts>=? AND kind IN ('chat','image','video','realtime')", (since,)
            ).fetchall()
        return {str(r[0]) for r in rows}

    def device_seen_accounts(self, since: int) -> list[sqlite3.Row]:
        """Accounts with a hub device seen since `since`, by kind: the app was open."""
        with self._lock:
            return self._conn.execute(
                "SELECT account_id, GROUP_CONCAT(DISTINCT kind) AS kinds, MAX(last_seen) AS last_seen FROM devices WHERE last_seen>=? GROUP BY account_id",
                (since,),
            ).fetchall()

    def devices_detail(self) -> list[sqlite3.Row]:
        """Every remembered device's kind, system, version, actions and reported model, for
        the platform and hands pages to fold (one row per device; tens of thousands at most)."""
        with self._lock:
            return self._conn.execute(
                "SELECT account_id, kind, os, version, actions, llm_provider, llm_model, last_seen FROM devices"
            ).fetchall()

    # -- 0.28: the shape of kept turns (analytics.py) -------------------------------------------

    SAMPLE_STAT_COLUMNS = (
        "sample_id",
        "account_id",
        "ts",
        "model",
        "platform",
        "messages",
        "user_chars",
        "reply_chars",
        "tool_calls",
        "pictures",
        "hands",
        "trivial",
        "user_hash",
        "bytes",
        "prompt_tokens",
        "completion_tokens",
        "run",
        "source",
        "turn_id",
        "conversation",
        "turn_no",
        "turn_start",
        "turn_key",
    )

    def add_sample_stats(self, rows: list[dict[str, Any]]) -> int:
        """The shape rows of kept turns (one per call); a call already described is left alone.
        A row without its tokens gets -1 for them (not copied yet), not 0. A row that says
        whether its call opened a turn (``turn_start``, 0.31) gets the turn's key as it is
        written: the record's id for the call when the row names it (``turn_id``), else the
        sample's own, for an opener; the opener's key for one that continues a turn."""
        if not rows:
            return 0
        cols = self.SAMPLE_STAT_COLUMNS
        text = ("sample_id", "account_id", "model", "platform", "user_hash", "run", "source", "turn_id", "conversation", "turn_key")
        tokens = ("prompt_tokens", "completion_tokens", "turn_start")
        with self.tx() as c:
            for r in rows:
                r = dict(r)
                start = r.get("turn_start")
                if start is None or start < 0:
                    r["turn_start"], r["turn_key"] = -1, ""
                elif start:
                    r["turn_start"], r["turn_key"] = 1, str(r.get("turn_id") or r["sample_id"])
                else:
                    r["turn_start"] = 0
                    r["turn_key"] = self._turn_key_for(
                        c, "sample_stats", str(r["account_id"]), str(r.get("conversation") or ""), int(r.get("turn_no") or 0), int(r["ts"])
                    )
                c.execute(
                    f"INSERT OR IGNORE INTO sample_stats({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    [r.get(k, "" if k in text else -1 if k in tokens else 0) for k in cols],
                )
        return len(rows)

    def samples_tokens_page(self, before_ts: int, before_rowid: int, limit: int) -> list[sqlite3.Row]:
        """The next page of kept turns going back from a (ts, rowid) position with their
        tokens only (the tokens backfill's cursor, Analytics.tokens_step). Reads the turn's
        row, as any read of a column past the conversation must; in pages, off the loop."""
        with self._lock:
            if before_ts <= 0:
                return self._conn.execute(
                    "SELECT rowid, id, ts, prompt_tokens, completion_tokens FROM samples ORDER BY ts DESC, rowid DESC LIMIT ?", (limit,)
                ).fetchall()
            return self._conn.execute(
                """SELECT rowid, id, ts, prompt_tokens, completion_tokens FROM samples
                   WHERE ts<? OR (ts=? AND rowid<?) ORDER BY ts DESC, rowid DESC LIMIT ?""",
                (before_ts, before_ts, before_rowid, limit),
            ).fetchall()

    def set_sample_stats_tokens(self, rows: list[tuple[int, int, str]]) -> int:
        """``(prompt_tokens, completion_tokens, sample_id)`` for shape rows not yet carrying
        them; a row that already has its tokens is left as it is."""
        if not rows:
            return 0
        with self.tx() as c:
            c.executemany("UPDATE sample_stats SET prompt_tokens=?, completion_tokens=? WHERE sample_id=? AND prompt_tokens<0", rows)
        return len(rows)

    def sample_stats_without_tokens(self) -> int:
        """How many shape rows still wait for their tokens (the Data view says so while they do)."""
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM sample_stats WHERE prompt_tokens<0").fetchone()[0])

    def samples_without_stats(self, limit: int, since: int) -> list[sqlite3.Row]:
        """Kept turns since `since` that have no shape row (the row's write failed once, after
        the turn was kept): the newest first. The window matters: the walk is a lookup per
        turn, and over every turn ever kept it ran for a minute and a half on a cold page cache
        with the database lock held, which froze the relay (every handler waits on that lock).
        A missing row is at most a day old when the daily pass looks, so a few days suffice."""
        with self._lock:
            return self._conn.execute(
                """SELECT s.rowid, s.id, s.account_id, s.ts, s.model, s.request, s.response, s.meta FROM samples s
                   LEFT JOIN sample_stats t ON t.sample_id=s.id WHERE s.ts>=? AND t.sample_id IS NULL
                   ORDER BY s.ts DESC LIMIT ?""",
                (since, limit),
            ).fetchall()

    def samples_page_before(self, before_ts: int, before_rowid: int, limit: int) -> list[sqlite3.Row]:
        """The next page of turns going back in time from a (ts, rowid) position — the
        backfill's cursor; newest first, so recent turns are described first."""
        with self._lock:
            if before_ts <= 0:
                return self._conn.execute(
                    "SELECT rowid, id, account_id, ts, model, request, response, meta FROM samples ORDER BY ts DESC, rowid DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return self._conn.execute(
                """SELECT rowid, id, account_id, ts, model, request, response, meta FROM samples
                   WHERE ts<=? AND (ts<? OR rowid<?) ORDER BY ts DESC, rowid DESC LIMIT ?""",
                (before_ts, before_ts, before_rowid, limit),
            ).fetchall()

    def sample_stats_count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM sample_stats").fetchone()[0])

    def sample_stats_totals(self, since: int) -> sqlite3.Row:
        with self._lock:
            return self._conn.execute(
                """SELECT COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts, SUM(trivial) AS trivial, SUM(hands) AS hands,
                          SUM(CASE WHEN tool_calls>0 THEN 1 ELSE 0 END) AS with_tools,
                          SUM(CASE WHEN pictures>0 THEN 1 ELSE 0 END) AS with_pictures,
                          SUM(bytes) AS bytes, AVG(user_chars) AS avg_user_chars, AVG(reply_chars) AS avg_reply_chars,
                          AVG(messages) AS avg_messages,
                          SUM(CASE WHEN reply_chars<40 THEN 1 ELSE 0 END) AS short_replies
                   FROM sample_stats WHERE ts>=?""",
                (since,),
            ).fetchone()

    def sample_stats_repeats(self, since: int, at_least: int = 3) -> sqlite3.Row:
        """How many turns of the window repeat a person's message seen `at_least` times in it
        (scripts, tests, the same opening line), and how many distinct such messages."""
        with self._lock:
            return self._conn.execute(
                """SELECT COALESCE(SUM(n), 0) AS turns, COUNT(*) AS messages, COALESCE(SUM(accounts), 0) AS account_rows FROM (
                       SELECT user_hash, COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts FROM sample_stats
                       WHERE ts>=? AND user_hash<>'' GROUP BY user_hash HAVING COUNT(*)>=?)""",
                (since, at_least),
            ).fetchone()

    def sample_stats_top_repeats(self, since: int, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """SELECT user_hash, COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts, MIN(user_chars) AS user_chars
                   FROM sample_stats WHERE ts>=? AND user_hash<>'' GROUP BY user_hash HAVING COUNT(*)>=3 ORDER BY n DESC LIMIT ?""",
                (since, limit),
            ).fetchall()

    def sample_stats_by_day(self, since: int, day_offset_s: int = 0) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                f"""SELECT {self._DAY} AS day, COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts, SUM(trivial) AS trivial,
                           SUM(hands) AS hands, SUM(CASE WHEN tool_calls>0 THEN 1 ELSE 0 END) AS with_tools,
                           SUM(CASE WHEN pictures>0 THEN 1 ELSE 0 END) AS with_pictures, SUM(bytes) AS bytes
                    FROM sample_stats WHERE ts>=? GROUP BY day ORDER BY day""",
                (day_offset_s, day_offset_s, day_offset_s, since),
            ).fetchall()

    def sample_stats_by_account(self, since: int) -> list[sqlite3.Row]:
        """Per contributing account in the window: the figures the quality score is made of."""
        with self._lock:
            return self._conn.execute(
                """SELECT s.account_id, a.hint, a.channel, a.contribute, a.disabled, a.created_at, a.last_ua,
                          COUNT(*) AS n, SUM(s.trivial) AS trivial, SUM(s.hands) AS hands,
                          SUM(CASE WHEN s.tool_calls>0 THEN 1 ELSE 0 END) AS with_tools,
                          SUM(CASE WHEN s.pictures>0 THEN 1 ELSE 0 END) AS with_pictures,
                          SUM(CASE WHEN s.reply_chars<40 THEN 1 ELSE 0 END) AS short_replies,
                          COUNT(DISTINCT s.user_hash) AS distinct_messages,
                          AVG(s.user_chars) AS avg_user_chars, AVG(s.reply_chars) AS avg_reply_chars, AVG(s.messages) AS avg_messages,
                          SUM(s.bytes) AS bytes, MIN(s.ts) AS first_ts, MAX(s.ts) AS last_ts,
                          GROUP_CONCAT(DISTINCT s.platform) AS platforms
                   FROM sample_stats s JOIN accounts a ON a.id=s.account_id
                   WHERE s.ts>=? GROUP BY s.account_id ORDER BY n DESC""",
                (since,),
            ).fetchall()

    def sample_stats_by_platform(self, since: int) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """SELECT platform, COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts, SUM(trivial) AS trivial, SUM(hands) AS hands,
                          SUM(CASE WHEN tool_calls>0 THEN 1 ELSE 0 END) AS with_tools, SUM(CASE WHEN pictures>0 THEN 1 ELSE 0 END) AS with_pictures,
                          AVG(user_chars) AS avg_user_chars, SUM(bytes) AS bytes
                   FROM sample_stats WHERE ts>=? GROUP BY platform ORDER BY n DESC""",
                (since,),
            ).fetchall()

    # -- the catalog's probes (catalog.py) ----------------------------------------

    def probes(self) -> list[Probe]:
        with self._lock:
            rows = self._conn.execute("SELECT model_id, works, vision, checked_at, note FROM model_probes").fetchall()
        return [
            Probe(
                model_id=r["model_id"],
                works=bool(r["works"]),
                vision=bool(r["vision"]),
                checked_at=int(r["checked_at"]),
                note=r["note"] or "",
            )
            for r in rows
        ]

    def save_probe(self, probe: Probe) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO model_probes(model_id, works, vision, checked_at, note) VALUES (?,?,?,?,?) "
                "ON CONFLICT(model_id) DO UPDATE SET works=excluded.works, vision=excluded.vision, "
                "checked_at=excluded.checked_at, note=excluded.note",
                (probe.model_id, 1 if probe.works else 0, 1 if probe.vision else 0, int(probe.checked_at), probe.note[:200]),
            )
