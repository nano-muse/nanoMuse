"""SQLite storage: accounts, keys, codes, the token ledger.

One file, WAL mode, one connection guarded by a lock — the relay is I/O bound
on the upstream, not on SQLite. Identifiers (phone / e-mail) are stored as
their HMAC (the lookup key), a masked hint for the account page, and — so the
operator can tell who is who — encrypted with a key derived from the
deployment secret (`identifier_enc`, see crypto.py); a copied database file
shows none of them.
"""

from __future__ import annotations

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
    contribute_bonus_at INTEGER                -- 0.5: when the one-time co-creation bonus was granted
);
-- accounts_invite_code (unique, partial) is made in _migrate(): the column is
-- added there on databases from before 0.4, and an index in this script would
-- run first and fail on them.
CREATE TABLE IF NOT EXISTS api_keys (
    key_hash      TEXT PRIMARY KEY,
    prefix        TEXT NOT NULL,
    account_id    TEXT NOT NULL REFERENCES accounts(id),
    device        TEXT NOT NULL DEFAULT '',
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
"""

# How long a deleted account's key hashes are remembered. Long enough for every device of the
# account to come back online and hear the answer; short enough that a deletion is a deletion.
DELETED_KEYS_TTL_S = 90 * 24 * 3600


def utc_day(ts: int) -> int:
    """The UNIX time the UTC day of `ts` starts — the key of the `daily` table."""
    return ts - ts % 86400


def now() -> int:
    return int(time.time())


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        # columns this open added to an older file ("accounts.grant_uy"): the service seeds
        # what a column's default cannot know (see seed_grants)
        self.added: set[str] = set()
        with self._lock:
            # executescript commits on its own; keep it outside tx().
            self._conn.execute("PRAGMA journal_mode=WAL")
            # WAL with NORMAL: durable against a process crash, and an fsync per checkpoint
            # instead of per commit (the default FULL costs one per commit). A power cut
            # may lose the last commits, never the file's consistency.
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            self._migrate()

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
        self._conn.close()

    # -- codes -------------------------------------------------------------

    def codes_recent_for(self, id_hash: str, since: int) -> int:
        with self._lock:
            r = self._conn.execute("SELECT COUNT(*) FROM codes WHERE id_hash=? AND created_at>=?", (id_hash, since)).fetchone()
        return int(r[0])

    def codes_recent_for_ip(self, ip: str, since: int) -> int:
        with self._lock:
            r = self._conn.execute("SELECT COUNT(*) FROM codes WHERE ip=? AND created_at>=?", (ip, since)).fetchone()
        return int(r[0])

    def insert_code(self, id_hash: str, code_hash: str, ip: str, ttl_s: int) -> None:
        t = now()
        with self.tx() as c:
            # A new code supersedes the old ones for this identifier.
            c.execute("UPDATE codes SET used=1 WHERE id_hash=? AND used=0", (id_hash,))
            c.execute(
                "INSERT INTO codes(id_hash, code_hash, ip, created_at, expires_at) VALUES (?,?,?,?,?)",
                (id_hash, code_hash, ip, t, t + ttl_s),
            )
            c.execute("DELETE FROM codes WHERE expires_at < ?", (t - 86400,))

    def live_code(self, id_hash: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM codes WHERE id_hash=? AND used=0 AND expires_at>=? ORDER BY id DESC LIMIT 1",
                (id_hash, now()),
            ).fetchone()

    def bump_attempts(self, code_id: int) -> int:
        with self.tx() as c:
            c.execute("UPDATE codes SET attempts=attempts+1 WHERE id=?", (code_id,))
            r = c.execute("SELECT attempts FROM codes WHERE id=?", (code_id,)).fetchone()
        return int(r[0])

    def consume_code(self, code_id: int) -> None:
        with self.tx() as c:
            c.execute("UPDATE codes SET used=1 WHERE id=?", (code_id,))

    # -- accounts ------------------------------------------------------------

    def account_by_hash(self, id_hash: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM accounts WHERE id_hash=?", (id_hash,)).fetchone()

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

    def delete_account(self, account_id: str) -> None:
        """Everything about one person: keys, ledger, devices, pending codes, the row itself."""
        with self.tx() as c:
            row = c.execute("SELECT id_hash FROM accounts WHERE id=?", (account_id,)).fetchone()
            if row is None:
                return
            c.execute("DELETE FROM codes WHERE id_hash=?", (row["id_hash"],))
            c.execute("DELETE FROM samples WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM events WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM video_tasks WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM devices WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM profiles WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM sync_messages WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM sync_conversations WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM sync_cursors WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM ledger WHERE account_id=?", (account_id,))
            # the keys' hashes stay a while, so a device still holding one hears
            # `account_deleted` (0.1.40); the rows that named the account do not
            ts = now()
            c.execute("DELETE FROM deleted_keys WHERE deleted_at < ?", (ts - DELETED_KEYS_TTL_S,))
            c.execute(
                "INSERT OR REPLACE INTO deleted_keys(key_hash, deleted_at) "
                "SELECT key_hash, ? FROM api_keys WHERE account_id=?",
                (ts, account_id),
            )
            c.execute("DELETE FROM api_keys WHERE account_id=?", (account_id,))
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
        order is the order the turns happened in."""
        q = "SELECT * FROM samples WHERE ts>=?"
        args: list = [since]
        if account_id is not None:
            q += " AND account_id=?"
            args.append(account_id)
        if before and before_id:
            q += " AND (ts<? OR (ts=? AND rowid<(SELECT rowid FROM samples WHERE id=?)))"
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
            return c.execute("DELETE FROM samples WHERE account_id=?", (account_id,)).rowcount

    def contributors(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM accounts WHERE contribute=1").fetchone()[0])

    def samples_totals(self, since: int) -> sqlite3.Row:
        """How many turns were kept since ``since``, by how many accounts, and their tokens."""
        with self._lock:
            return self._conn.execute(
                """SELECT COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts,
                          SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens
                   FROM samples WHERE ts>=?""",
                (since,),
            ).fetchone()

    def samples_by_day(self, since: int, offset_s: int) -> list[sqlite3.Row]:
        """Kept turns per local day (``offset_s`` east of UTC): count, accounts, tokens."""
        with self._lock:
            return self._conn.execute(
                f"""SELECT {self._DAY} AS day, COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts,
                           SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens
                    FROM samples WHERE ts>=? GROUP BY day ORDER BY day""",
                (offset_s, offset_s, offset_s, since),
            ).fetchall()

    def samples_by_model(self, since: int) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """SELECT model, COUNT(*) AS n, SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens
                   FROM samples WHERE ts>=? GROUP BY model ORDER BY n DESC""",
                (since,),
            ).fetchall()

    def samples_by_account(self) -> list[sqlite3.Row]:
        """Every account that has turns kept, with how many, their tokens, the first and the
        last — the operator's way in to one person's data, newest activity first."""
        with self._lock:
            return self._conn.execute(
                """SELECT s.account_id, a.hint, a.channel, a.contribute, a.created_at,
                          COUNT(*) AS n, SUM(s.prompt_tokens) AS prompt_tokens, SUM(s.completion_tokens) AS completion_tokens,
                          MIN(s.ts) AS first_ts, MAX(s.ts) AS last_ts, GROUP_CONCAT(DISTINCT s.model) AS models
                   FROM samples s JOIN accounts a ON a.id=s.account_id
                   GROUP BY s.account_id ORDER BY last_ts DESC""",
            ).fetchall()

    def samples_meta(self, since: int) -> list[sqlite3.Row]:
        """The distinct meta strings of the period with their counts (the app and language
        behind each turn), for the operator to group — a few hundred rows at most."""
        with self._lock:
            return self._conn.execute(
                "SELECT meta, COUNT(*) AS n FROM samples WHERE ts>=? GROUP BY meta ORDER BY n DESC LIMIT 2000", (since,)
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

    def record_invite(self, inviter_id: str, invitee_id: str, bonus_uy: int) -> None:
        """A new account signed up with the inviter's code: both pools grow by the bonus —
        the inviter's (``from: invite``) and the newcomer's (``from: invited``)."""
        t = now()
        bonus_uy = max(0, int(bonus_uy))
        with self.tx() as c:
            c.execute("UPDATE accounts SET invited_by=? WHERE id=? AND invited_by=''", (inviter_id, invitee_id))
            c.execute("UPDATE accounts SET invites=invites+1, grant_uy=grant_uy+? WHERE id=?", (bonus_uy, inviter_id))
            c.execute("UPDATE accounts SET grant_uy=grant_uy+? WHERE id=?", (bonus_uy, invitee_id))
            c.execute(
                "INSERT INTO ledger(account_id, ts, kind, charged, extra) VALUES (?,?,?,?,?)",
                (inviter_id, t, "credit", 0, json.dumps({"credit_uy": bonus_uy, "from": "invite", "friend": invitee_id[:8]})),
            )
            c.execute(
                "INSERT INTO ledger(account_id, ts, kind, charged, extra) VALUES (?,?,?,?,?)",
                (invitee_id, t, "credit", 0, json.dumps({"credit_uy": bonus_uy, "from": "invited", "friend": inviter_id[:8]})),
            )

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
        ``record_invite`` wrote (``from: invite``), so the figure stays right when the bonus
        changes between one invite and the next."""
        with self._lock:
            r = self._conn.execute(
                "SELECT COALESCE(SUM(json_extract(extra, '$.credit_uy')), 0) FROM ledger "
                "WHERE account_id=? AND kind='credit' AND json_extract(extra, '$.from')='invite'",
                (inviter_id,),
            ).fetchone()
        return int(r[0] or 0)

    def invitees(self, inviter_id: str, limit: int = 50) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT id, hint, created_at FROM accounts WHERE invited_by=? ORDER BY created_at DESC LIMIT ?",
                (inviter_id, limit),
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
                out.extend(
                    self._conn.execute(f"SELECT id, hint, identifier_enc FROM accounts WHERE id IN ({marks})", chunk).fetchall()
                )
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
        self, key_hash: str, prefix: str, account_id: str, device: str, via: str = "code", expires_at: int | None = None
    ) -> None:
        who = _client.current()
        with self.tx() as c:
            c.execute(
                "INSERT INTO api_keys(key_hash, prefix, account_id, device, created_at, via, ip, ua, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (key_hash, prefix, account_id, device[:80], now(), via, who.ip, who.ua, expires_at),
            )

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

    def events_for(self, account_id: str, limit: int = 50, before_id: int = 0) -> list[sqlite3.Row]:
        """Newest first; ``before_id`` (an event id) pages further back."""
        with self._lock:
            q = "SELECT id, ts, kind, detail, ip, ua FROM events WHERE account_id=?"
            args: list = [account_id]
            if before_id:
                q += " AND id<?"
                args.append(before_id)
            args.append(max(1, min(limit, 1000)))
            return self._conn.execute(q + " ORDER BY id DESC LIMIT ?", args).fetchall()

    def event_count(self, account_id: str) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM events WHERE account_id=?", (account_id,)).fetchone()
        return int(row["n"]) if row else 0

    def events_recent(self, limit: int = 100, kinds: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
        with self._lock:
            if kinds:
                marks = ",".join("?" * len(kinds))
                return self._conn.execute(
                    f"SELECT account_id, ts, kind, detail, ip, ua FROM events WHERE kind IN ({marks}) ORDER BY id DESC LIMIT ?",
                    (*kinds, limit),
                ).fetchall()
            return self._conn.execute(
                "SELECT account_id, ts, kind, detail, ip, ua FROM events ORDER BY id DESC LIMIT ?", (limit,)
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

    def recent_ledger(self, account_id: str, limit: int = 30, before_id: int = 0) -> list[sqlite3.Row]:
        """Newest first; ``before_id`` (a ledger id) pages further back, to the first line."""
        with self._lock:
            q = "SELECT id, ts, kind, model, prompt_tokens, completion_tokens, charged, cost_uy, extra, ip, ua FROM ledger WHERE account_id=?"
            args: list = [account_id]
            if before_id:
                q += " AND id<?"
                args.append(before_id)
            args.append(max(1, min(limit, 1000)))
            return self._conn.execute(q + " ORDER BY id DESC LIMIT ?", args).fetchall()

    def ledger_count(self, account_id: str) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM ledger WHERE account_id=?", (account_id,)).fetchone()
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

    def upsert_device(self, account_id: str, device_id: str, name: str, kind: str, os: str, version: str, actions: str) -> None:
        t = now()
        ip = _client.current().ip
        with self.tx() as c:
            c.execute(
                """INSERT INTO devices(account_id, id, name, kind, os, version, actions, first_seen, last_seen, ip)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(account_id, id) DO UPDATE SET
                     name=excluded.name, kind=excluded.kind, os=excluded.os, version=excluded.version,
                     actions=excluded.actions, last_seen=excluded.last_seen,
                     ip=CASE WHEN excluded.ip<>'' THEN excluded.ip ELSE devices.ip END""",
                (account_id, device_id, name, kind, os, version, actions, t, t, ip),
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
