"""0.28: what the console's new pages read — the live view of the model endpoint, the usage
matrix with its day drill-downs, the platforms side by side, the cohorts (the free pool and
what came after it, who runs a key of their own, retention), screen operation, the shape
and quality of the kept turns, and the clients that are not the apps.

Two sources feed it. The ledger and the events, as before, for money, tokens and accounts;
and two tables this version adds:

- `calls` (db.py) — one row per chat request with its timings (queued for a provider slot,
  to the first token, to the end), how it ended and its shape (messages, pictures, tools);
  `LiveMeter` keeps the last few thousand in memory as well, with the requests under way,
  so the live page answers without a query. Never a word of a request.
- `sample_stats` — one small row per kept turn (`samples`): how many messages, how long the
  person's message and the reply were, tools, pictures, the operator, a hash of the message
  for finding repeats. `sample_shape` writes it with the turn; `Analytics.backfill_step`
  fills it in for older turns a page at a time, so the quality page never reads the turns.

Everything here is aggregate or the operator's own view of an account the console already
shows; identifiers are decrypted only for the rows a page lists, as the other admin views do.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import provenance
from .client import PLATFORMS, client_version, is_app, platform_from, platform_of, ua_family
from .db import utc_day
from .record import unpack

if TYPE_CHECKING:
    from .hub import Hub
    from .service import Cloud

log = logging.getLogger("nanomuse_cloud.analytics")

# How a request ended, as `calls.status` keeps it.
STATUSES = ("ok", "upstream_error", "upstream_timeout", "content_rejected", "broken", "refused", "client_gone")
ERROR_STATUSES = frozenset({"upstream_error", "upstream_timeout", "broken"})

# The operator's tools — a phone or a computer being looked at and acted on. The phones'
# and the runtime's names, the desktop's MCP names, and the prefixes the hands modules use.
HANDS_TOOLS = frozenset(
    {
        "tap",
        "swipe",
        "click",
        "double_click",
        "right_click",
        "type_text",
        "type",
        "screenshot",
        "take_screenshot",
        "scroll",
        "long_press",
        "press_key",
        "key",
        "hotkey",
        "open_app",
        "launch_app",
        "back",
        "home",
        "move_mouse",
        "mouse_move",
        "drag",
        "computer",
        "computer_use",
        "screen",
        "screen_act",
        "screen_look",
        "device_screen",
        "device_act",
    }
)
HANDS_PREFIXES = (
    "android_",
    "phone_",
    "gui_",
    "computer_",
    "screen_",
    "mcp__nanomuse__computer",
    "mcp__nanomuse__phone",
    "mcp__nanomuse__screen",
    "operator_",
    "hands_",
)

# What a kept turn is when there is nothing to learn from it: a greeting, a test, one word.
TRIVIAL_MESSAGES = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "test",
        "testing",
        "ok",
        "okay",
        "yes",
        "no",
        "thanks",
        "thank you",
        "你好",
        "您好",
        "在吗",
        "在不在",
        "测试",
        "试试",
        "嗯",
        "好",
        "好的",
        "谢谢",
        "哈哈",
        "hello world",
        "1",
        "2",
        "a",
        "?",
        "？",
        "。",
        ".",
    }
)
TRIVIAL_CHARS = 8  # a person's message shorter than this, with no history, is a test
SHORT_REPLY_CHARS = 40

_WS = re.compile(r"\s+")


def is_hands_tool(name: str) -> bool:
    n = str(name or "").strip().lower()
    return n in HANDS_TOOLS or n.startswith(HANDS_PREFIXES)


def _text_of(content: Any) -> str:
    """The words of a message's content: a string, or the text parts of a list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _pictures_of(content: Any) -> int:
    """How many pictures (or clips, or audio) a message carries: the apps' `image_url` parts,
    and the markers a kept turn has in their place."""
    if not isinstance(content, list):
        return 0
    n = 0
    for p in content:
        if isinstance(p, dict) and (
            p.get("type") in ("image_url", "input_image", "image", "video_url", "video", "input_audio") or p.get("omitted")
        ):
            n += 1
    return n


def request_shape(body: dict) -> dict[str, Any]:
    """What a chat request looks like without reading it: how many messages, how many
    pictures, how many tool definitions the client offered and their names, and whether the
    operator's tools are among them (a screen-operation turn)."""
    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    images = sum(_pictures_of(m.get("content")) for m in messages if isinstance(m, dict))
    tools = body.get("tools") if isinstance(body.get("tools"), list) else []
    names: list[str] = []
    for t in tools:
        if isinstance(t, dict):
            fn = t.get("function") if isinstance(t.get("function"), dict) else t
            name = str(fn.get("name") or "")[:60]
            if name:
                names.append(name)
    # tool calls the conversation already carries (the model's earlier steps of this task)
    called: list[str] = []
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "assistant" and isinstance(m.get("tool_calls"), list):
            for tc in m["tool_calls"]:
                fn = tc.get("function") if isinstance(tc, dict) and isinstance(tc.get("function"), dict) else None
                if fn and fn.get("name"):
                    called.append(str(fn["name"])[:60])
    hands = any(is_hands_tool(n) for n in names) or any(is_hands_tool(n) for n in called)
    return {"messages": len(messages), "images": images, "tools": len(tools), "tool_names_offered": names, "hands": hands}


def reply_tool_names(obj: Any) -> list[str]:
    """The tools a non-streamed reply called (`choices[].message.tool_calls[].function.name`)."""
    out: list[str] = []
    if isinstance(obj, dict):
        for ch in obj.get("choices") or []:
            msg = ch.get("message") if isinstance(ch, dict) else None
            out.extend(_tool_call_names(msg))
    return out


def delta_tool_names(obj: dict) -> list[str]:
    """The tool names a stream chunk starts (`choices[].delta.tool_calls[].function.name`;
    a name arrives once, in the first chunk of each call)."""
    out: list[str] = []
    for ch in obj.get("choices") or []:
        out.extend(_tool_call_names(ch.get("delta") if isinstance(ch, dict) else None))
    return out


def _tool_call_names(message: Any) -> list[str]:
    """The function names of a message's (or a delta's) `tool_calls`."""
    if not isinstance(message, dict) or not isinstance(message.get("tool_calls"), list):
        return []
    out: list[str] = []
    for tc in message["tool_calls"]:
        fn = tc.get("function") if isinstance(tc, dict) and isinstance(tc.get("function"), dict) else None
        if fn and fn.get("name"):
            out.append(str(fn["name"])[:60])
    return out


def join_tool_names(names: Iterable[str], limit: int = 400) -> str:
    """Distinct names, in order, comma-joined and cut: the `calls.tool_names` column."""
    seen: list[str] = []
    for n in names:
        n = str(n or "").replace(",", " ").strip()
        if n and n not in seen:
            seen.append(n)
    return ",".join(seen)[:limit]


def normalise_message(text: str) -> str:
    return _WS.sub(" ", str(text or "")).strip().lower()


def sample_shape(
    sample_id: str,
    account_id: str,
    ts: int,
    model: str,
    request: str,
    response: str,
    meta: str,
    prompt_tokens: int = -1,
    completion_tokens: int = -1,
) -> dict[str, Any]:
    """The `sample_stats` row of one kept turn, from what `samples` holds. Reads the turn
    once, keeps nothing of its words but a hash of the person's last message. The tokens
    are -1 when the caller does not have them (a shape written late); the tokens backfill
    copies them from the turn."""
    try:
        messages = json.loads(request) if request else []
    except ValueError:
        messages = []
    if not isinstance(messages, list):
        messages = []
    try:
        m = json.loads(meta) if meta else {}
    except ValueError:
        m = {}
    if not isinstance(m, dict):
        m = {}
    last_user = ""
    pictures = 0
    tool_calls = 0
    hands = False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        pictures += _pictures_of(msg.get("content"))
        if msg.get("role") == "user":
            last_user = _text_of(msg.get("content"))
        elif msg.get("role") == "assistant" and isinstance(msg.get("tool_calls"), list):
            for tc in msg["tool_calls"]:
                fn = tc.get("function") if isinstance(tc, dict) and isinstance(tc.get("function"), dict) else None
                if fn is not None:
                    tool_calls += 1
                    if is_hands_tool(str(fn.get("name") or "")):
                        hands = True
    norm = normalise_message(last_user)
    user_turns = sum(1 for msg in messages if isinstance(msg, dict) and msg.get("role") == "user")
    trivial = (not norm) or norm in TRIVIAL_MESSAGES or (len(norm) < TRIVIAL_CHARS and user_turns <= 1 and pictures == 0)
    return {
        "sample_id": sample_id,
        "account_id": account_id,
        "ts": int(ts),
        "model": str(model or "")[:80],
        "platform": platform_from(m),
        "messages": len(messages),
        "user_chars": len(last_user),
        "reply_chars": len(response or ""),
        "tool_calls": tool_calls,
        "pictures": pictures,
        "hands": 1 if hands else 0,
        "trivial": 1 if trivial else 0,
        "user_hash": hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16] if norm else "",
        "bytes": len(request or "") + len(response or ""),
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        # 0.31: who started the turn, where it ran, and the record's id for it (provenance)
        "run": str(m.get("run") or "")[:24],
        "source": str(m.get("source") or "")[:8],
        "turn_id": str(m.get("turn_id") or "")[:96],
        # 0.31: one question, many calls — whether this call opened a turn, and where the
        # turn's key is looked up (the conversation and the app's turn number, when said)
        "conversation": str(m.get("conversation") or "")[:80],
        "turn_no": _index(m.get("turn")),
        "turn_start": 1 if provenance.turn_start(messages, _index(m.get("step"))) else 0,
    }


def _index(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _messages_of(request: Any) -> list:
    """A kept call's messages from the stored request: the training view's JSON list, or
    the record's packed body (record.unpack) with the list under ``messages``."""
    if isinstance(request, (bytes, memoryview)):
        body = unpack(bytes(request))
        found = body.get("messages") if isinstance(body, dict) else body
    else:
        try:
            found = json.loads(request) if request else []
        except ValueError:
            found = []
    return found if isinstance(found, list) else []


def _meta_of(meta: Any) -> dict:
    try:
        m = json.loads(meta) if meta else {}
    except ValueError:
        return {}
    return m if isinstance(m, dict) else {}


def percentile(values: list[int] | list[float], p: float) -> int:
    """The p-th percentile (0–1) of a list, nearest rank; 0 for an empty list."""
    if not values:
        return 0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
    return int(ordered[k])


# -- the live meter --------------------------------------------------------------------------


@dataclass
class InFlightCall:
    """A chat request between arrival and its end, as the live page shows it."""

    id: int
    ts: int  # arrival, wall clock
    started: float  # arrival, monotonic
    account_id: str
    model: str
    platform: str
    stream: bool
    phase: str = "waiting"  # waiting (for a provider slot) | upstream (sent, no token yet) | streaming
    slot_at: float | None = None
    first_at: float | None = None
    tokens_out: int = 0
    retries: int = 0
    family: str = ""  # the client software's family (client.ua_family), kept at arrival
    shape: dict[str, Any] = field(default_factory=dict)
    run: str = ""  # who started the turn (X-NanoMuse-Run, 0.31): person, schedule, feed, goal, hub, or ""

    def view(self, now_mono: float) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "account": self.account_id[:8],
            "model": self.model,
            "platform": self.platform,
            "stream": self.stream,
            "phase": self.phase,
            "age_ms": int((now_mono - self.started) * 1000),
            "wait_ms": int(((self.slot_at or now_mono) - self.started) * 1000),
            "ttft_ms": int((self.first_at - self.slot_at) * 1000) if self.first_at and self.slot_at else None,
            "tokens_out": self.tokens_out,
            "retries": self.retries,
            "images": int(self.shape.get("images", 0)),
            "hands": bool(self.shape.get("hands")),
        }


class LiveMeter:
    """The requests under way and the last few thousand that ended, in memory, for the live
    page: the gate's queue, who is waiting on what, per-minute throughput and latency for
    the last hour. Warmed from `calls` after a restart so the hour is not blank."""

    def __init__(self, keep: int = 6000):
        self.inflight: dict[int, InFlightCall] = {}
        self.finished: deque[dict[str, Any]] = deque(maxlen=keep)
        self._next = 1
        self.started_at = int(time.time())
        self.counts = {s: 0 for s in STATUSES}  # since start

    def start(self, account_id: str, model: str, platform: str, stream: bool, shape: dict[str, Any] | None = None) -> InFlightCall:
        call = InFlightCall(
            id=self._next,
            ts=int(time.time()),
            started=time.monotonic(),
            account_id=account_id,
            model=model,
            platform=platform,
            stream=stream,
            shape=dict(shape or {}),
        )
        self._next += 1
        self.inflight[call.id] = call
        return call

    def slot(self, call: InFlightCall) -> None:
        call.slot_at = time.monotonic()
        call.phase = "upstream"

    def first(self, call: InFlightCall) -> None:
        if call.first_at is None:
            call.first_at = time.monotonic()
            call.phase = "streaming"

    def finish(self, call: InFlightCall, row: dict[str, Any]) -> None:
        self.inflight.pop(call.id, None)
        self.counts[row.get("status", "ok")] = self.counts.get(row.get("status", "ok"), 0) + 1
        self.finished.append(row)

    def warm(self, rows: Iterable[Any]) -> int:
        n = 0
        for r in rows:
            self.finished.append({k: r[k] for k in r.keys()} if hasattr(r, "keys") else dict(r))
            n += 1
        return n

    def running(self) -> list[dict[str, Any]]:
        now_mono = time.monotonic()
        return sorted((c.view(now_mono) for c in self.inflight.values()), key=lambda v: -v["age_ms"])

    def window(self, since: int) -> list[dict[str, Any]]:
        return [r for r in self.finished if int(r.get("ts", 0)) >= since]

    def minutes(self, now_ts: int, count: int = 60) -> list[dict[str, Any]]:
        """One bucket per minute for the last `count` minutes, oldest first: requests that
        arrived, how they ended, latency percentiles of the ones that went through, tokens."""
        first = now_ts - now_ts % 60 - 60 * (count - 1)
        buckets: list[dict[str, Any]] = [
            {
                "t": first + 60 * i,
                "n": 0,
                "ok": 0,
                "errors": 0,
                "refused": 0,
                "timeouts": 0,
                "waited": 0,
                "tokens_out": 0,
                "tokens_in": 0,
                "_ttft": [],
                "_total": [],
                "_wait": [],
            }
            for i in range(count)
        ]
        for r in self.finished:
            ts = int(r.get("ts", 0))
            if ts < first:
                continue
            b = buckets[min(count - 1, (ts - first) // 60)]
            b["n"] += 1
            status = str(r.get("status", ""))
            if status == "ok":
                b["ok"] += 1
                b["_ttft"].append(int(r.get("ttft_ms", 0)))
                b["_total"].append(int(r.get("total_ms", 0)))
            elif status in ERROR_STATUSES:
                b["errors"] += 1
                if status == "upstream_timeout":
                    b["timeouts"] += 1
            elif status == "refused":
                b["refused"] += 1
            if int(r.get("wait_ms", 0)) > 50:
                b["waited"] += 1
            b["_wait"].append(int(r.get("wait_ms", 0)))
            b["tokens_out"] += int(r.get("completion_tokens", 0))
            b["tokens_in"] += int(r.get("prompt_tokens", 0))
        for b in buckets:
            b["p50_ttft"] = percentile(b.pop("_ttft"), 0.5)
            total = b.pop("_total")
            b["p50_total"] = percentile(total, 0.5)
            b["p95_total"] = percentile(total, 0.95)
            b["p95_wait"] = percentile(b.pop("_wait"), 0.95)
        return buckets

    def summary(self, since: int) -> dict[str, Any]:
        rows = self.window(since)
        ok = [r for r in rows if r.get("status") == "ok"]
        ttft = [int(r.get("ttft_ms", 0)) for r in ok]
        total = [int(r.get("total_ms", 0)) for r in ok]
        waits = [int(r.get("wait_ms", 0)) for r in rows]
        out_tokens = sum(int(r.get("completion_tokens", 0)) for r in ok)
        span = max(1, int(time.time()) - since)
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[str(r.get("status", ""))] = by_status.get(str(r.get("status", "")), 0) + 1
        return {
            "requests": len(rows),
            "ok": len(ok),
            "errors": sum(1 for r in rows if r.get("status") in ERROR_STATUSES),
            "refused": by_status.get("refused", 0),
            "by_status": by_status,
            "accounts": len({str(r.get("account_id", "")) for r in rows}),
            "p50_ttft_ms": percentile(ttft, 0.5),
            "p95_ttft_ms": percentile(ttft, 0.95),
            "p50_total_ms": percentile(total, 0.5),
            "p95_total_ms": percentile(total, 0.95),
            "p50_wait_ms": percentile(waits, 0.5),
            "p95_wait_ms": percentile(waits, 0.95),
            "waited_share": (sum(1 for w in waits if w > 50) / len(waits)) if waits else 0.0,
            "tokens_out": out_tokens,
            "tokens_out_per_s": round(out_tokens / span, 2),
            "hands": sum(1 for r in rows if int(r.get("hands", 0))),
            "with_images": sum(1 for r in rows if int(r.get("images", 0)) > 0),
            "stream_share": (sum(1 for r in rows if int(r.get("stream", 0))) / len(rows)) if rows else 0.0,
        }

    def recent(self, limit: int = 60) -> list[dict[str, Any]]:
        out = []
        for r in list(self.finished)[-limit:][::-1]:
            out.append(
                {
                    "ts": int(r.get("ts", 0)),
                    "account": str(r.get("account_id", ""))[:8],
                    "model": r.get("model", ""),
                    "platform": r.get("platform", ""),
                    "status": r.get("status", ""),
                    "detail": r.get("detail", ""),
                    "stream": bool(r.get("stream")),
                    "wait_ms": int(r.get("wait_ms", 0)),
                    "ttft_ms": int(r.get("ttft_ms", 0)),
                    "total_ms": int(r.get("total_ms", 0)),
                    "prompt_tokens": int(r.get("prompt_tokens", 0)),
                    "completion_tokens": int(r.get("completion_tokens", 0)),
                    "images": int(r.get("images", 0)),
                    "tools": int(r.get("tools", 0)),
                    "hands": bool(r.get("hands")),
                    "retries": int(r.get("retries", 0)),
                }
            )
        return out


# -- the aggregates --------------------------------------------------------------------------


def _fold_ua_rows(rows: Iterable[Any], key: Callable[[str], str]) -> dict[str, dict[str, Any]]:
    """Ledger rows grouped by user agent, folded into groups by `key(ua)`: requests, tokens,
    money summed; the user agents and versions listed."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        ua = str(r["ua"] or "")
        g = out.setdefault(
            key(ua),
            {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_uy": 0, "uas": 0, "versions": {}},
        )
        g["requests"] += int(r["requests"] or 0)
        g["prompt_tokens"] += int(r["prompt_tokens"] or 0)
        g["completion_tokens"] += int(r["completion_tokens"] or 0)
        g["cost_uy"] += int(r["cost_uy"] or 0)
        g["uas"] += 1
        v = client_version(ua)
        if v:
            g["versions"][v] = g["versions"].get(v, 0) + int(r["requests"] or 0)
    return out


def _week_of(ts: int) -> int:
    """The UNIX time of the Monday 00:00 UTC that starts the week `ts` falls in."""
    d = utc_day(ts)
    return d - ((d // 86400 + 3) % 7) * 86400


class Analytics:
    def __init__(self, cloud: Cloud, meter: LiveMeter, hub_getter: Callable[[], Hub | None], gate_getter: Callable[[], dict[str, int]]):
        self.cloud = cloud
        # the pages and the backfills' page reads go through the read-only connection
        # (Database.reader): seconds of reading never hold the lock the requests take;
        # the few writes (shape rows, cursors) go through the relay's own
        self.db = cloud.db.reader()
        self.store = cloud.db
        self.s = cloud.s
        self.meter = meter
        self.hub_getter = hub_getter
        self.gate_getter = gate_getter
        self.backfill_done = False
        self.backfill_rows = 0
        self.tokens_done = False
        self.tokens_rows = 0
        # 0.31: the turn keys of the rows kept before the relay told turns from calls
        self.keys_done = False
        self.keys_rows = 0
        # 0.31.1: the figures rows of the own turns kept before the relay wrote them
        self.figures_done = False
        self.figures_rows = 0

    # -- helpers ------------------------------------------------------------------------------

    @property
    def offset(self) -> int:
        return self.s.day_offset_h * 3600

    def _since(self, days: int) -> tuple[int, int, list[int]]:
        t = int(time.time())
        today = self.s.day_start(t)
        since = today - 86400 * max(0, days - 1)
        return since, today, [since + 86400 * i for i in range(days)]

    def _cny(self, uy: int | float | None) -> float:
        return self.s.uy_to_cny(int(uy or 0))

    def _label_rows(self, rows: list[dict[str, Any]], key: str = "account_id") -> list[dict[str, Any]]:
        hints, idents = self.cloud._labels([r[key] for r in rows if r.get(key)])
        for r in rows:
            r["hint"] = hints.get(r.get(key, ""), "")
            r["identifier"] = idents.get(r.get(key, ""), "")
        return rows

    # -- live ---------------------------------------------------------------------------------

    def live(self) -> dict[str, Any]:
        t = int(time.time())
        hub = self.hub_getter()
        in_flight = self.cloud.in_flight.snapshot()
        return {
            "time": t,
            "gate": self.gate_getter(),
            "in_flight": {"requests": sum(in_flight.values()), "accounts": len(in_flight), "limit": self.cloud.in_flight.limit},
            "running": self.meter.running(),
            "hub": hub.stats() if hub is not None else None,
            "minutes": self.meter.minutes(t, 60),
            "last_10m": self.meter.summary(t - 600),
            "last_hour": self.meter.summary(t - 3600),
            "recent": self.meter.recent(60),
            "since_start": {"started_at": self.meter.started_at, "counts": dict(self.meter.counts)},
            "models": [m.id for m in self.cloud.offered_models()],
            "settings": {
                "chat_concurrency": self.s.chat_concurrency,
                "max_in_flight": self.s.max_in_flight,
                "upstream_timeout_s": self.s.upstream_timeout_s,
                "chat_retries": self.s.chat_retries,
            },
        }

    # -- usage: the matrix and a day's drill-down ----------------------------------------------

    def usage(self, days: int) -> dict[str, Any]:
        """The day × model matrix from the ledger (requests, tokens, money, accounts), each
        model's totals, and the cache: how many of the prompt tokens the provider served from
        its cache, per day, per model and overall (`cached_tokens`; the share is theirs over
        the prompt tokens). `own_keys` says the same for the turns people ran on keys of their
        own and sent up, per provider and model."""
        since, _today, window = self._since(days)
        cells: dict[tuple[int, str], dict[str, Any]] = {}
        models: dict[str, dict[str, Any]] = {}
        counted = ("requests", "prompt_tokens", "completion_tokens", "cached_tokens", "cost_uy")
        for r in self.db.usage_by_day_model(since, self.offset):
            d, model = int(r["day"]), str(r["model"] or "?")
            c = cells.setdefault((d, model), {**dict.fromkeys(counted, 0), "accounts": 0, "kind": str(r["kind"])})
            m = models.setdefault(model, {"model": model, "kind": str(r["kind"]), **dict.fromkeys(counted, 0), "days": 0})
            for k in counted:
                c[k] += int(r[k] or 0)
                m[k] += int(r[k] or 0)
            c["accounts"] = max(c["accounts"], int(r["accounts"] or 0))
            m["days"] += 1
        active = {int(r["day"]): int(r["n"]) for r in self.db.active_by_day(since, self.offset)}
        rows = []
        for d in window:
            by_model = {}
            total = dict.fromkeys(counted, 0)
            for model in models:
                c = cells.get((d, model))
                if c is None:
                    continue
                by_model[model] = {
                    "requests": c["requests"],
                    "prompt_tokens": c["prompt_tokens"],
                    "completion_tokens": c["completion_tokens"],
                    "cached_tokens": c["cached_tokens"],
                    "cost_cny": self._cny(c["cost_uy"]),
                    "accounts": c["accounts"],
                }
                for k in total:
                    total[k] += c[k]
            rows.append(
                {
                    "day": d,
                    "requests": total["requests"],
                    "prompt_tokens": total["prompt_tokens"],
                    "completion_tokens": total["completion_tokens"],
                    "cached_tokens": total["cached_tokens"],
                    "cost_cny": self._cny(total["cost_uy"]),
                    "active_accounts": active.get(d, 0),
                    "models": by_model,
                }
            )
        model_rows = sorted(models.values(), key=lambda m: -m["cost_uy"])
        totals = {
            "requests": sum(m["requests"] for m in model_rows),
            "prompt_tokens": sum(m["prompt_tokens"] for m in model_rows),
            "completion_tokens": sum(m["completion_tokens"] for m in model_rows),
            "cached_tokens": sum(m["cached_tokens"] for m in model_rows),
            "cost_cny": self._cny(sum(m["cost_uy"] for m in model_rows)),
            "active_days": sum(1 for r in rows if r["requests"]),
        }
        for m in model_rows:
            m["cost_cny"] = self._cny(m.pop("cost_uy"))
        own_keys = [
            {
                "provider": str(r["provider"] or ""),
                "model": str(r["model"] or "?"),
                "turns": int(r["turns"] or 0),
                "accounts": int(r["accounts"] or 0),
                "prompt_tokens": int(r["prompt_tokens"] or 0),
                "completion_tokens": int(r["completion_tokens"] or 0),
                "cached_tokens": int(r["cached_tokens"] or 0),
            }
            for r in self.db.own_usage_by_provider(since)
        ]
        return {
            "generated_at": int(time.time()),
            "days": days,
            "day_offset_h": self.s.day_offset_h,
            "rows": rows,
            "models": model_rows,
            "totals": totals,
            "own_keys": own_keys,
            # 0.31.1: the own turns kept before this version join the table as the backfill
            # writes their figures rows; until then the table is short of them
            "own_keys_pending": not self.figures_done,
        }

    def day(self, day: int) -> dict[str, Any]:
        """One local day in full: by hour and model, by platform, by status and latency (from
        `calls`), the errors' reasons, the accounts that cost most."""
        start = self.s.day_start(int(day))
        end = start + 86400
        hours: dict[int, dict[str, Any]] = {h: {"hour": h, "requests": 0, "cost_cny": 0.0, "accounts": 0, "models": {}} for h in range(24)}
        for r in self.db.usage_by_hour_model(start, end, self.offset):
            h = hours[int(r["hour"]) % 24]
            h["requests"] += int(r["requests"] or 0)
            h["cost_cny"] = round(h["cost_cny"] + self._cny(r["cost_uy"]), 4)
            h["accounts"] = max(h["accounts"], int(r["accounts"] or 0))
            h["models"][str(r["model"] or "?")] = {
                "requests": int(r["requests"] or 0),
                "prompt_tokens": int(r["prompt_tokens"] or 0),
                "completion_tokens": int(r["completion_tokens"] or 0),
                "cost_cny": self._cny(r["cost_uy"]),
            }
        # platforms, accounts counted once per platform
        folded = _fold_ua_rows(self.db.usage_by_ua(start, end), platform_of)
        accounts_by_platform: dict[str, set[str]] = {}
        for p in self.db.account_ua_pairs(start, end):
            accounts_by_platform.setdefault(platform_of(str(p["ua"] or "")), set()).add(str(p["account_id"]))
        platforms = []
        for name, g in folded.items():
            n = g["requests"]
            platforms.append(
                {
                    "platform": name,
                    "requests": n,
                    "accounts": len(accounts_by_platform.get(name, ())),
                    "cost_cny": self._cny(g["cost_uy"]),
                    "avg_prompt_tokens": round(g["prompt_tokens"] / n) if n else 0,
                    "avg_completion_tokens": round(g["completion_tokens"] / n) if n else 0,
                }
            )
        platforms.sort(key=lambda p: -p["requests"])
        # how the calls went (telemetry rows; empty for days before this version was deployed)
        calls = self.db.calls_between(start, end)
        by_hour_lat: dict[int, dict[str, list[int]]] = {h: {"ttft": [], "total": [], "wait": []} for h in range(24)}
        by_status: dict[str, int] = {}
        by_model_status: dict[str, dict[str, int]] = {}
        hands = images = tools = 0
        for c in calls:
            st = str(c["status"])
            by_status[st] = by_status.get(st, 0) + 1
            ms = by_model_status.setdefault(str(c["model"] or "?"), {})
            ms[st] = ms.get(st, 0) + 1
            h = ((int(c["ts"]) + self.offset) % 86400) // 3600
            by_hour_lat[h]["wait"].append(int(c["wait_ms"]))
            if st == "ok":
                by_hour_lat[h]["ttft"].append(int(c["ttft_ms"]))
                by_hour_lat[h]["total"].append(int(c["total_ms"]))
            hands += int(c["hands"] or 0)
            images += 1 if int(c["images"] or 0) > 0 else 0
            tools += 1 if int(c["tools"] or 0) > 0 else 0
        latency = [
            {
                "hour": h,
                "n": len(v["wait"]),
                "p50_ttft": percentile(v["ttft"], 0.5),
                "p95_ttft": percentile(v["ttft"], 0.95),
                "p50_total": percentile(v["total"], 0.5),
                "p95_total": percentile(v["total"], 0.95),
                "p95_wait": percentile(v["wait"], 0.95),
            }
            for h, v in by_hour_lat.items()
        ]
        ok = [c for c in calls if c["status"] == "ok"]
        summary = {
            "calls": len(calls),
            "by_status": by_status,
            "hands": hands,
            "with_images": images,
            "with_tools": tools,
            "p50_ttft_ms": percentile([int(c["ttft_ms"]) for c in ok], 0.5),
            "p95_ttft_ms": percentile([int(c["ttft_ms"]) for c in ok], 0.95),
            "p50_total_ms": percentile([int(c["total_ms"]) for c in ok], 0.5),
            "p95_total_ms": percentile([int(c["total_ms"]) for c in ok], 0.95),
            "p95_wait_ms": percentile([int(c["wait_ms"]) for c in calls], 0.95),
            "waited_share": (sum(1 for c in calls if int(c["wait_ms"]) > 50) / len(calls)) if calls else 0.0,
        }
        errors = [{"detail": str(r["detail"]), "n": int(r["n"])} for r in self.db.event_details_between("upstream.error", start, end)]
        rejected = [
            {"detail": str(r["detail"]), "n": int(r["n"])} for r in self.db.event_details_between("content.rejected", start, end, 10)
        ]
        events_hour: dict[int, dict[str, int]] = {}
        for r in self.db.events_by_hour(start, end, self.offset):
            events_hour.setdefault(int(r["hour"]) % 24, {})[str(r["kind"])] = int(r["n"])
        for h in hours.values():
            e = events_hour.get(h["hour"], {})
            h["upstream_errors"] = e.get("upstream.error", 0)
            h["budget_refused"] = e.get("budget.refused", 0)
            h["content_rejected"] = e.get("content.rejected", 0)
            h["sign_ins"] = e.get("sign_in.code", 0) + e.get("sign_in.password", 0)
        top = [
            {
                "account_id": str(r["account_id"]),
                "requests": int(r["requests"] or 0),
                "charged": int(r["charged"] or 0),
                "prompt_tokens": int(r["prompt_tokens"] or 0),
                "completion_tokens": int(r["completion_tokens"] or 0),
                "cost_cny": self._cny(r["cost_uy"]),
                "platform": platform_of(str(r["ua"] or "")),
                "family": ua_family(str(r["ua"] or "")),
            }
            for r in self.db.top_accounts_between(start, end, 50)
        ]
        return {
            "day": start,
            "end": end,
            "day_offset_h": self.s.day_offset_h,
            "hours": [hours[h] for h in range(24)],
            "platforms": platforms,
            "calls": summary,
            "latency": latency,
            "by_model_status": by_model_status,
            "errors": errors,
            "content_rejected": rejected,
            "top_accounts": self._label_rows(top),
        }

    # -- platforms side by side --------------------------------------------------------------

    def platforms(self, days: int) -> dict[str, Any]:
        since, _today, _window = self._since(days)
        folded = _fold_ua_rows(self.db.usage_by_ua(since), platform_of)
        accounts_by_platform: dict[str, set[str]] = {}
        platforms_by_account: dict[str, set[str]] = {}
        for p in self.db.account_ua_pairs(since):
            name = platform_of(str(p["ua"] or ""))
            accounts_by_platform.setdefault(name, set()).add(str(p["account_id"]))
            platforms_by_account.setdefault(str(p["account_id"]), set()).add(name)
        # the telemetry's word on each platform, aggregated in SQLite: a season of calls is
        # hundreds of thousands of rows, and the relay should not hold them all at once
        until = int(time.time()) + 1
        tele: dict[str, dict[str, Any]] = {}
        for c in self.db.calls_by_platform(since, until):
            tele[str(c["platform"])] = {
                k: int(c[k] or 0) for k in ("n", "ok", "errors", "refused", "hands", "images", "tools", "stream", "messages")
            }
        for c in self.db.calls_latency_by_platform(since, until):
            t = tele.get(str(c["platform"]))
            if t is not None:
                for k in ("p50_ttft_ms", "p95_ttft_ms", "p50_total_ms", "p95_wait_ms"):
                    t[k] = int(c[k] or 0)
        rows = []
        for name in sorted(set(folded) | set(tele), key=lambda n: -(folded.get(n, {}).get("requests", 0))):
            g = folded.get(name, {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_uy": 0, "versions": {}})
            n = g["requests"]
            accounts = len(accounts_by_platform.get(name, ()))
            t = tele.get(name)
            versions = sorted(g["versions"].items(), key=lambda kv: -kv[1])[:6]
            rows.append(
                {
                    "platform": name,
                    "app": is_app(name),
                    "requests": n,
                    "accounts": accounts,
                    "requests_per_account": round(n / accounts, 1) if accounts else 0,
                    "cost_cny": self._cny(g["cost_uy"]),
                    "cost_per_account_cny": round(self._cny(g["cost_uy"]) / accounts, 4) if accounts else 0,
                    "avg_prompt_tokens": round(g["prompt_tokens"] / n) if n else 0,
                    "avg_completion_tokens": round(g["completion_tokens"] / n) if n else 0,
                    "versions": [{"version": v, "requests": c} for v, c in versions],
                    "calls": (
                        {
                            "n": t["n"],
                            "ok_share": t["ok"] / t["n"] if t["n"] else 0,
                            "error_share": t["errors"] / t["n"] if t["n"] else 0,
                            "refused": t["refused"],
                            "hands_share": t["hands"] / t["n"] if t["n"] else 0,
                            "images_share": t["images"] / t["n"] if t["n"] else 0,
                            "tools_share": t["tools"] / t["n"] if t["n"] else 0,
                            "stream_share": t["stream"] / t["n"] if t["n"] else 0,
                            "avg_messages": round(t["messages"] / t["n"], 1) if t["n"] else 0,
                            "p50_ttft_ms": t.get("p50_ttft_ms", 0),
                            "p95_ttft_ms": t.get("p95_ttft_ms", 0),
                            "p50_total_ms": t.get("p50_total_ms", 0),
                            "p95_wait_ms": t.get("p95_wait_ms", 0),
                        }
                        if t
                        else None
                    ),
                }
            )
        # the sets: how many accounts used one platform, two, which pairs
        combos: dict[str, int] = {}
        multi = 0
        for names in platforms_by_account.values():
            key = "+".join(sorted(names))
            combos[key] = combos.get(key, 0) + 1
            if len(names) > 1:
                multi += 1
        combo_rows = sorted(({"platforms": k, "accounts": v} for k, v in combos.items()), key=lambda r: -r["accounts"])[:15]
        # the devices the hub remembers, by kind and system, with the operator's reach and
        # what they said they run the model under
        devices: dict[tuple[str, str], dict[str, Any]] = {}
        llm: dict[str, dict[str, Any]] = {}
        seen_30d = int(time.time()) - 30 * 86400
        for d in self.db.devices_detail():
            k = (str(d["kind"]), str(d["os"] or ""))
            g = devices.setdefault(k, {"kind": k[0], "os": k[1], "devices": 0, "seen_30d": 0, "screen": 0, "versions": {}})
            g["devices"] += 1
            if int(d["last_seen"] or 0) >= seen_30d:
                g["seen_30d"] += 1
            try:
                actions = json.loads(d["actions"] or "[]")
            except ValueError:
                actions = []
            if isinstance(actions, list) and any(
                str(a) in ("screen", "screen.look", "screen.act") or str(a).startswith("screen") for a in actions
            ):
                g["screen"] += 1
            v = str(d["version"] or "")
            if v:
                g["versions"][v] = g["versions"].get(v, 0) + 1
            prov = str(d["llm_provider"] or "")
            if prov:
                e = llm.setdefault(prov, {"provider": prov, "devices": 0, "accounts": set(), "models": {}})
                e["devices"] += 1
                e["accounts"].add(str(d["account_id"]))
                model = str(d["llm_model"] or "")
                if model:
                    e["models"][model] = e["models"].get(model, 0) + 1
        device_rows = sorted(devices.values(), key=lambda g: -g["devices"])
        for g in device_rows:
            g["versions"] = [{"version": v, "devices": c} for v, c in sorted(g["versions"].items(), key=lambda kv: -kv[1])[:6]]
        llm_rows = sorted(llm.values(), key=lambda g: -g["devices"])
        for g in llm_rows:
            g["accounts"] = len(g["accounts"])
            g["models"] = [{"model": m, "devices": c} for m, c in sorted(g["models"].items(), key=lambda kv: -kv[1])[:10]]
        # every account's last client, as they stand now
        by_last: dict[str, dict[str, int]] = {}
        for r in self.db.account_versions():
            name = platform_of(str(r["last_ua"] or ""))
            g = by_last.setdefault(name, {"accounts": 0, "disabled": 0})
            g["accounts"] += int(r["n"])
            g["disabled"] += int(r["disabled"] or 0)
        # the hub's online sockets by kind and os, right now
        hub = self.hub_getter()
        online: dict[str, int] = {}
        if hub is not None:
            for conns in list(hub.online.values()):
                for conn in list(conns.values()):
                    k = f"{conn.kind}/{conn.os or '?'}"
                    online[k] = online.get(k, 0) + 1
        return {
            "generated_at": int(time.time()),
            "days": days,
            "platforms": rows,
            "accounts_by_last_client": [{"platform": k, **v} for k, v in sorted(by_last.items(), key=lambda kv: -kv[1]["accounts"])],
            "multi_platform_accounts": multi,
            "accounts_with_requests": len(platforms_by_account),
            "combinations": combo_rows,
            "devices": device_rows,
            "online": online,
            "own_models": llm_rows,
            "known_platforms": list(PLATFORMS),
        }

    # -- cohorts: the pool, what came after, who runs their own key, retention -----------------

    POOL_BUCKETS = (
        ("0%", 0.0, 0.0),
        ("1-24%", 0.0, 0.25),
        ("25-49%", 0.25, 0.5),
        ("50-79%", 0.5, 0.8),
        ("80-99%", 0.8, 1.0),
        ("100%", 1.0, 9e9),
    )
    EXHAUST_BUCKETS = (("<1d", 0, 1), ("1-3d", 1, 3), ("3-7d", 3, 7), ("7-14d", 7, 14), ("14d+", 14, 10**6))

    def cohorts(self, days: int) -> dict[str, Any]:
        t = int(time.time())
        window_since = t - 86400 * max(1, days)
        members = self.cloud.member_hashes
        rows = self.db.pool_cohort_rows()
        buckets = {name: 0 for name, _a, _b in self.POOL_BUCKETS}
        buckets["no limit"] = 0
        never_used = 0
        limited = 0
        exhaust_days: list[float] = []
        exhaust_buckets = {name: 0 for name, _a, _b in self.EXHAUST_BUCKETS}
        after = {"total": 0, "chatted_again": 0, "active_no_chat": 0, "gone": 0, "disabled": 0, "synced_assistant_after": 0}
        # the last assistant message each account's devices synced, ever — a model answered them somewhere
        synced_last = {str(r["account_id"]): int(r["last_at"] or 0) for r in self.db.sync_assistant_accounts(0)}
        spent_total_uy = 0
        grant_total_uy = 0
        for a in rows:
            member = bool(a["unlimited"]) or a["id_hash"] in members
            grant = int(a["grant_uy"] or 0)
            spent = int(a["spent_uy"] or 0)
            if member or self.s.allowance_cny <= 0 or grant <= 0:
                buckets["no limit"] += 1
                continue
            limited += 1
            grant_total_uy += grant
            spent_total_uy += min(spent, grant)
            frac = spent / grant
            refused_at = int(a["first_refused"] or 0)
            exhausted = frac >= 1.0 or refused_at > 0
            if int(a["chats"] or 0) == 0:
                never_used += 1
            if exhausted:
                buckets["100%"] += 1
            elif frac <= 0:
                buckets["0%"] += 1
            else:
                for name, lo, hi in self.POOL_BUCKETS[1:-1]:
                    if lo <= frac < hi:
                        buckets[name] += 1
                        break
            if refused_at:
                first_chat = int(a["first_chat"] or a["created_at"])
                d = max(0.0, (refused_at - first_chat) / 86400)
                exhaust_days.append(d)
                for name, lo, hi in self.EXHAUST_BUCKETS:
                    if lo <= d < hi:
                        exhaust_buckets[name] += 1
                        break
                if refused_at <= t - 2 * 86400:  # two days to see what they did next
                    after["total"] += 1
                    last_chat = int(a["last_chat"] or 0)
                    last_seen = int(a["last_seen_at"] or 0)
                    if a["disabled"]:
                        after["disabled"] += 1
                    elif last_chat > refused_at + 600:
                        after["chatted_again"] += 1
                    elif last_seen > refused_at + 2 * 86400:
                        after["active_no_chat"] += 1
                    else:
                        after["gone"] += 1
                    if synced_last.get(str(a["id"]), 0) > refused_at + 600:
                        after["synced_assistant_after"] += 1
        exhaust_days.sort()
        # who runs a key of their own: a model answered them (synced) without a relay chat
        synced_window = {str(r["account_id"]): int(r["n"]) for r in self.db.sync_assistant_accounts(window_since)}
        chatted = self.db.chat_accounts_since(window_since)
        device_seen = {str(r["account_id"]): str(r["kinds"] or "") for r in self.db.device_seen_accounts(window_since)}
        own_key = {a for a in synced_window if a not in chatted}
        both = {a for a in synced_window if a in chatted}
        cloud_only = chatted - set(synced_window)
        app_open_only = {a for a in device_seen if a not in synced_window and a not in chatted}
        own_key_rows = self._label_rows(
            sorted(
                ({"account_id": a, "synced_replies": synced_window[a], "devices": device_seen.get(a, "")} for a in own_key),
                key=lambda r: -r["synced_replies"],
            )[:50]
        )
        # weekly retention: sign-up week → used the relay's models / made any call in the weeks after
        weeks = min(12, max(2, days // 7 + 1))
        first_week = _week_of(t) - 604800 * (weeks - 1)
        chat_weeks: dict[str, set[int]] = {}
        for r in self.db.chat_days_by_account(first_week):
            chat_weeks.setdefault(str(r["account_id"]), set()).add(_week_of(int(r["day"])))
        any_weeks: dict[str, set[int]] = {}
        for r in self.db.active_days_by_account(first_week):
            any_weeks.setdefault(str(r["account_id"]), set()).add(_week_of(int(r["day"])))
        cohort: dict[int, dict[str, Any]] = {}
        for a in rows:
            created = int(a["created_at"])
            if created < first_week or a["id_hash"] in self.cloud.review_hashes:
                continue
            w = _week_of(created)
            c = cohort.setdefault(w, {"week": w, "signups": 0, "chat": [0] * 4, "any": [0] * 4})
            c["signups"] += 1
            cw = chat_weeks.get(str(a["id"]), set())
            aw = any_weeks.get(str(a["id"]), set())
            for i in range(4):
                wk = w + 604800 * i
                if wk > _week_of(t):
                    break
                if wk in cw:
                    c["chat"][i] += 1
                if wk in aw:
                    c["any"][i] += 1
        retention = []
        for w in sorted(cohort):
            c = cohort[w]
            elapsed = (_week_of(t) - w) // 604800 + 1  # weeks that have started since
            retention.append(
                {
                    "week": w,
                    "signups": c["signups"],
                    "chat": [c["chat"][i] if i < elapsed else None for i in range(4)],
                    "any": [c["any"][i] if i < elapsed else None for i in range(4)],
                }
            )
        return {
            "generated_at": t,
            "days": days,
            "allowance_cny": self.s.allowance_cny,
            "pool": {
                "limited": limited,
                "never_used": never_used,
                "buckets": [{"used": k, "accounts": v} for k, v in buckets.items()],
                "granted_cny": self._cny(grant_total_uy),
                "spent_cny": self._cny(spent_total_uy),
            },
            "exhaustion": {
                "accounts": len(exhaust_days),
                "median_days": round(exhaust_days[len(exhaust_days) // 2], 2) if exhaust_days else None,
                "p25_days": round(exhaust_days[len(exhaust_days) // 4], 2) if exhaust_days else None,
                "p75_days": round(exhaust_days[(3 * len(exhaust_days)) // 4], 2) if exhaust_days else None,
                "buckets": [{"days": k, "accounts": v} for k, v in exhaust_buckets.items()],
            },
            "after_exhaustion": after,
            "own_key": {
                "window_days": days,
                "own_key_likely": len(own_key),
                "both": len(both),
                "cloud_only": len(cloud_only),
                "app_open_no_model": len(app_open_only),
                "synced_any": len(synced_window),
                "accounts": own_key_rows,
            },
            "retention": retention,
        }

    # -- screen operation ---------------------------------------------------------------------

    def hands(self, days: int) -> dict[str, Any]:
        since, _today, window = self._since(days)
        by_day: dict[int, dict[str, Any]] = {
            d: {"day": d, "calls": 0, "hands": 0, "accounts": 0, "hands_accounts": 0, "platforms": {}} for d in window
        }
        by_platform: dict[str, dict[str, Any]] = {}
        for r in self.db.calls_by_day(since, self.offset):
            d = by_day.get(int(r["day"]))
            if d is None:
                continue
            d["calls"] += int(r["n"])
            d["hands"] += int(r["hands"] or 0)
            d["accounts"] += int(r["accounts"] or 0)
            d["hands_accounts"] += int(r["hands_accounts"] or 0)
            d["platforms"][str(r["platform"])] = int(r["hands"] or 0)
            p = by_platform.setdefault(
                str(r["platform"]), {"platform": str(r["platform"]), "calls": 0, "hands": 0, "ok": 0, "errors": 0, "with_images": 0}
            )
            p["calls"] += int(r["n"])
            p["hands"] += int(r["hands"] or 0)
            p["ok"] += int(r["ok"] or 0)
            p["errors"] += int(r["errors"] or 0)
            p["with_images"] += int(r["with_images"] or 0)
        tool_counts: dict[str, dict[str, Any]] = {}
        for r in self.db.calls_tool_names(since):
            for name in str(r["tool_names"]).split(","):
                if not name:
                    continue
                e = tool_counts.setdefault(name, {"tool": name, "calls": 0, "hands": is_hands_tool(name), "platforms": {}})
                e["calls"] += int(r["n"])
                e["platforms"][str(r["platform"])] = e["platforms"].get(str(r["platform"]), 0) + int(r["n"])
        tools = sorted(tool_counts.values(), key=lambda e: -e["calls"])[:40]
        accounts = self._label_rows(
            [
                {
                    "account_id": str(r["account_id"]),
                    "turns": int(r["n"]),
                    "ok": int(r["ok"] or 0),
                    "first_ts": int(r["first_ts"]),
                    "last_ts": int(r["last_ts"]),
                    "platforms": str(r["platforms"] or ""),
                }
                for r in self.db.calls_hands_accounts(since)[:50]
            ]
        )
        # the devices that can be operated: those that announce the screen action
        operable: dict[str, dict[str, int]] = {}
        accounts_operable: set[str] = set()
        seen_30d = int(time.time()) - 30 * 86400
        for d in self.db.devices_detail():
            try:
                actions = json.loads(d["actions"] or "[]")
            except ValueError:
                actions = []
            has_screen = isinstance(actions, list) and any(str(a) == "screen" or str(a).startswith("screen") for a in actions)
            g = operable.setdefault(str(d["kind"]), {"devices": 0, "screen": 0, "screen_seen_30d": 0})
            g["devices"] += 1
            if has_screen:
                g["screen"] += 1
                accounts_operable.add(str(d["account_id"]))
                if int(d["last_seen"] or 0) >= seen_30d:
                    g["screen_seen_30d"] += 1
        # the kept turns' word on it (contributing accounts only; from the shape rows)
        st = self.db.sample_stats_totals(since)
        sp = [
            {"platform": str(r["platform"]), "turns": int(r["n"]), "hands": int(r["hands"] or 0), "accounts": int(r["accounts"])}
            for r in self.db.sample_stats_by_platform(since)
        ]
        total_calls = sum(d["calls"] for d in by_day.values())
        total_hands = sum(d["hands"] for d in by_day.values())
        return {
            "generated_at": int(time.time()),
            "days": days,
            "summary": {
                "calls": total_calls,
                "hands": total_hands,
                "hands_share": total_hands / total_calls if total_calls else 0.0,
                "hands_accounts": len(self.db.calls_hands_accounts(since)),
                "accounts_with_operable_device": len(accounts_operable),
            },
            "days_series": [by_day[d] for d in window],
            "platforms": sorted(by_platform.values(), key=lambda p: -p["hands"]),
            "tools": tools,
            "accounts": accounts,
            "devices": [{"kind": k, **v} for k, v in operable.items()],
            "samples": {"turns": int(st["n"] or 0), "hands": int(st["hands"] or 0), "by_platform": sp},
            "hands_tools": sorted(HANDS_TOOLS),
            "hands_prefixes": list(HANDS_PREFIXES),
        }

    # -- the kept turns: shape and quality -----------------------------------------------------

    @staticmethod
    def score_account(
        n: int, trivial: int, short_replies: int, distinct: int, hands: int, with_tools: int, with_pictures: int
    ) -> tuple[int, str]:
        """0–100 and a tier. Useful turns are the ones that are neither trivial nor a short
        reply; repeats (the same message again and again) count once; depth rewards accounts
        with more turns, reaching full weight at thirty. A tier is high at 60 with ten turns,
        low under 25 or when half the turns repeat; medium between."""
        if n <= 0:
            return 0, "low"
        useful = max(0, n - trivial - short_replies)
        repeat_share = 1 - (distinct / n) if n else 0.0
        useful_share = useful / n
        if repeat_share > 0.5:
            useful_share *= 0.5
        depth = min(1.0, math.log1p(n) / math.log1p(30))
        richness = 1.0 + 0.1 * min(1.0, (hands + with_tools + with_pictures) / n)
        score = int(round(100 * useful_share * depth * richness))
        score = max(0, min(100, score))
        if score >= 60 and n >= 10:
            tier = "high"
        elif score < 25 or (n >= 10 and repeat_share >= 0.5):
            tier = "low"
        else:
            tier = "medium"
        return score, tier

    def quality(self, days: int) -> dict[str, Any]:
        since, _today, window = self._since(days)
        totals = self.db.sample_stats_totals(since)
        ever = self.db.sample_stats_totals(0)
        repeats = self.db.sample_stats_repeats(since)
        by_day = {int(r["day"]): r for r in self.db.sample_stats_by_day(since, self.offset)}
        series = []
        for d in window:
            r = by_day.get(d)
            series.append(
                {
                    "day": d,
                    "turns": int(r["n"]) if r else 0,
                    "accounts": int(r["accounts"]) if r else 0,
                    "trivial": int(r["trivial"] or 0) if r else 0,
                    "hands": int(r["hands"] or 0) if r else 0,
                    "with_tools": int(r["with_tools"] or 0) if r else 0,
                    "with_pictures": int(r["with_pictures"] or 0) if r else 0,
                    "bytes": int(r["bytes"] or 0) if r else 0,
                }
            )
        accounts = []
        tiers = {"high": 0, "medium": 0, "low": 0}
        tier_turns = {"high": 0, "medium": 0, "low": 0}
        for r in self.db.sample_stats_by_account(since):
            n = int(r["n"])
            score, tier = self.score_account(
                n,
                int(r["trivial"] or 0),
                int(r["short_replies"] or 0),
                int(r["distinct_messages"] or 0),
                int(r["hands"] or 0),
                int(r["with_tools"] or 0),
                int(r["with_pictures"] or 0),
            )
            tiers[tier] += 1
            tier_turns[tier] += n
            accounts.append(
                {
                    "account_id": str(r["account_id"]),
                    "hint": str(r["hint"]),
                    "channel": str(r["channel"]),
                    "contribute": bool(r["contribute"]),
                    "disabled": bool(r["disabled"]),
                    "created_at": int(r["created_at"]),
                    "platform": platform_of(str(r["last_ua"] or "")),
                    "turns": n,
                    "trivial": int(r["trivial"] or 0),
                    "short_replies": int(r["short_replies"] or 0),
                    "repeat_share": round(1 - int(r["distinct_messages"] or 0) / n, 3) if n else 0,
                    "hands": int(r["hands"] or 0),
                    "with_tools": int(r["with_tools"] or 0),
                    "with_pictures": int(r["with_pictures"] or 0),
                    "avg_user_chars": round(float(r["avg_user_chars"] or 0)),
                    "avg_reply_chars": round(float(r["avg_reply_chars"] or 0)),
                    "avg_messages": round(float(r["avg_messages"] or 0), 1),
                    "bytes": int(r["bytes"] or 0),
                    "first_ts": int(r["first_ts"]),
                    "last_ts": int(r["last_ts"]),
                    "platforms": str(r["platforms"] or ""),
                    "score": score,
                    "tier": tier,
                }
            )
        accounts.sort(key=lambda a: (-a["score"], -a["turns"]))
        top = accounts[:60]
        low = sorted((a for a in accounts if a["tier"] == "low" and a["turns"] >= 5), key=lambda a: -a["turns"])[:60]
        scripted = sorted((a for a in accounts if a["turns"] >= 20 and a["repeat_share"] >= 0.5), key=lambda a: -a["turns"])[:40]
        for lst in (top, low, scripted):
            self._label_rows(lst)
        n_period = int(totals["n"] or 0)
        samples_total = self.db.sample_count()
        stats_total = self.db.sample_stats_count()
        return {
            "generated_at": int(time.time()),
            "days": days,
            "coverage": {
                "samples": samples_total,
                "described": stats_total,
                "backfill_done": self.backfill_done or stats_total >= samples_total,
                "share": (stats_total / samples_total) if samples_total else 1.0,
            },
            "period": {
                "turns": n_period,
                "accounts": int(totals["accounts"] or 0),
                "trivial": int(totals["trivial"] or 0),
                "trivial_share": (int(totals["trivial"] or 0) / n_period) if n_period else 0.0,
                "short_replies": int(totals["short_replies"] or 0),
                "repeated_turns": int(repeats["turns"] or 0),
                "repeated_share": (int(repeats["turns"] or 0) / n_period) if n_period else 0.0,
                "repeated_messages": int(repeats["messages"] or 0),
                "hands": int(totals["hands"] or 0),
                "with_tools": int(totals["with_tools"] or 0),
                "with_pictures": int(totals["with_pictures"] or 0),
                "bytes": int(totals["bytes"] or 0),
                "avg_user_chars": round(float(totals["avg_user_chars"] or 0)),
                "avg_reply_chars": round(float(totals["avg_reply_chars"] or 0)),
                "avg_messages": round(float(totals["avg_messages"] or 0), 1),
            },
            "all_time": {
                "turns": int(ever["n"] or 0),
                "accounts": int(ever["accounts"] or 0),
                "bytes": int(ever["bytes"] or 0),
                "trivial": int(ever["trivial"] or 0),
            },
            "series": series,
            "tiers": [{"tier": k, "accounts": v, "turns": tier_turns[k]} for k, v in tiers.items()],
            "top_accounts": top,
            "low_accounts": low,
            "scripted_accounts": scripted,
            "top_repeats": [
                {"hash": str(r["user_hash"]), "turns": int(r["n"]), "accounts": int(r["accounts"]), "chars": int(r["user_chars"] or 0)}
                for r in self.db.sample_stats_top_repeats(since)
            ],
            "by_platform": [
                {
                    "platform": str(r["platform"]),
                    "turns": int(r["n"]),
                    "accounts": int(r["accounts"]),
                    "trivial": int(r["trivial"] or 0),
                    "hands": int(r["hands"] or 0),
                    "with_tools": int(r["with_tools"] or 0),
                    "with_pictures": int(r["with_pictures"] or 0),
                    "avg_user_chars": round(float(r["avg_user_chars"] or 0)),
                    "bytes": int(r["bytes"] or 0),
                }
                for r in self.db.sample_stats_by_platform(since)
            ],
            "scoring": {
                "trivial_chars": TRIVIAL_CHARS,
                "short_reply_chars": SHORT_REPLY_CHARS,
                "full_depth_turns": 30,
                "high": "score >= 60 and >= 10 turns",
                "low": "score < 25, or half the turns repeat one message",
            },
        }

    def backfill_step(self, batch: int = 200) -> int:
        """Describe the next `batch` older turns (newest first) that have no shape row yet;
        returns how many were written, 0 when caught up. The cursor lives in the settings
        table so a restart carries on where it stopped."""
        if self.backfill_done:
            return 0
        before_ts, before_rowid, done = self._cursor("sample_stats.cursor")
        if done:  # finished on an earlier run; the turns kept since carry their own row
            self.backfill_done = True
            return 0
        rows = self.db.samples_page_before(before_ts, before_rowid, batch)
        if not rows:
            self.backfill_done = True
            self.store.settings_put("sample_stats.cursor", [-1, -1])
            return 0
        stats = [
            sample_shape(
                str(r["id"]),
                str(r["account_id"]),
                int(r["ts"]),
                str(r["model"]),
                str(r["request"] or ""),
                str(r["response"] or ""),
                str(r["meta"] or ""),
            )
            for r in rows
        ]
        self.store.add_sample_stats(stats)
        last = rows[-1]
        self.store.settings_put("sample_stats.cursor", [int(last["ts"]), int(last["rowid"])])
        self.backfill_rows += len(rows)
        if len(rows) < batch:
            self.backfill_done = True
        return len(rows)

    def _cursor(self, key: str) -> tuple[int, int, bool]:
        """A backfill's (ts, rowid) position from the settings table: (0, 0) when it has not
        started, and `done` when an earlier run finished (written as [-1, -1])."""
        pos = self.db.settings_get(key)
        if pos is not None and isinstance(pos[0], list) and len(pos[0]) == 2:
            before_ts, before_rowid = int(pos[0][0]), int(pos[0][1])
            return before_ts, before_rowid, before_ts < 0
        return 0, 0, False

    def tokens_step(self, batch: int = 200) -> int:
        """0.30: copy the tokens of the next `batch` older turns (newest first) into their shape
        rows, so the Data view sums them there; returns how many were read, 0 when caught up.
        The cursor lives in the settings table like the shape backfill's. Each page reads its
        turns' rows (the tokens are stored past the conversation), off the loop and on the
        read-only connection; the update is the small write."""
        if self.tokens_done:
            return 0
        before_ts, before_rowid, done = self._cursor("sample_stats.tokens_cursor")
        if done:
            self.tokens_done = True
            return 0
        rows = self.db.samples_tokens_page(before_ts, before_rowid, batch)
        if not rows:
            self.tokens_done = True
            self.store.settings_put("sample_stats.tokens_cursor", [-1, -1])
            return 0
        self.store.set_sample_stats_tokens([(int(r["prompt_tokens"] or 0), int(r["completion_tokens"] or 0), str(r["id"])) for r in rows])
        last = rows[-1]
        self.store.settings_put("sample_stats.tokens_cursor", [int(last["ts"]), int(last["rowid"])])
        self.tokens_rows += len(rows)
        if len(rows) < batch:
            self.tokens_done = True
        return len(rows)

    #: the most rows of the record one turn-key step reads and rewrites (turn_keys_step)
    RECORD_KEYS_PAGE = 100

    def turn_keys_step(self, batch: int = 500) -> int:
        """0.31: tell the turns of the record and of the training view from their calls, for
        the rows kept before the relay did (``turn_start`` -1): the next ``batch`` rows of
        each table, oldest first — a row that continues a turn takes its opener's key, so
        the openers must be keyed before the rows after them. Returns how many rows were
        read, 0 when both tables are through. The cursors live in the settings table like
        the other backfills'. Each page reads its rows' messages on the read-only
        connection; the update is the small write — small in rows: the record's rows are
        rewritten body and all (``Database.set_turn_keys``), so its pages are at most
        ``RECORD_KEYS_PAGE`` rows, some ten megabytes read and written per step."""
        if self.keys_done:
            return 0
        read = 0
        through = True  # both tables' pages short: nothing left after this pass
        after_ts, after_rowid, done = self._cursor("turns.keys_cursor")
        if not done:
            page = min(batch, self.RECORD_KEYS_PAGE)
            rows = self.db.turns_unkeyed_page(after_ts, after_rowid, page)
            if rows:
                self.store.set_turn_keys(
                    "turns",
                    [
                        {
                            "rowid": int(r["rowid"]),
                            "id": str(r["id"]),
                            "account_id": str(r["account_id"]),
                            "ts": int(r["ts"]),
                            "conversation": str(r["conversation"] or ""),
                            "turn_no": int(r["turn_no"] or 0),
                            "start": provenance.turn_start(_messages_of(r["request"]), int(r["step"] or 0)),
                        }
                        for r in rows
                    ],
                )
                last = rows[-1]
                self.store.settings_put("turns.keys_cursor", [int(last["ts"]), int(last["rowid"])])
                read += len(rows)
            if len(rows) < page:
                self.store.settings_put("turns.keys_cursor", [-1, -1])
            else:
                through = False
        after_ts, after_rowid, done = self._cursor("sample_stats.keys_cursor")
        if not done:
            rows = self.db.sample_stats_unkeyed_page(after_ts, after_rowid, batch)
            if rows:
                described = []
                for r in rows:
                    meta = _meta_of(r["meta"])
                    described.append(
                        {
                            "rowid": int(r["rowid"]),
                            # the record's id for the call when the row names it, else the sample's own
                            "id": str(r["turn_id"] or r["id"]),
                            "account_id": str(r["account_id"]),
                            "ts": int(r["ts"]),
                            "conversation": str(meta.get("conversation") or "")[:80],
                            "turn_no": _index(meta.get("turn")),
                            "start": provenance.turn_start(_messages_of(r["request"]), _index(meta.get("step"))),
                        }
                    )
                self.store.set_turn_keys("sample_stats", described)
                last = rows[-1]
                self.store.settings_put("sample_stats.keys_cursor", [int(last["ts"]), int(last["rowid"])])
                read += len(rows)
            if len(rows) < batch:
                self.store.settings_put("sample_stats.keys_cursor", [-1, -1])
            else:
                through = False
        self.keys_rows += read
        if through:
            self.keys_done = True
        return read

    def own_figures_step(self, batch: int = 500) -> int:
        """0.31.1: the figures rows (own_figures) of the own turns kept before the relay wrote
        one with each turn, oldest first, a page at a time; returns how many turns were read,
        0 when through. The cursor lives in the settings table like the other backfills'.
        Each page reads its turns' rows on the read-only connection — the provider is in the
        meta and the cached count past the bodies, so this is the one pass that walks them,
        a page's worth at a time between the console's reads — and writes small rows."""
        if self.figures_done:
            return 0
        after_ts, after_rowid, done = self._cursor("own_figures.cursor")
        if done:
            self.figures_done = True
            return 0
        rows = self.db.own_unfigured_page(after_ts, after_rowid, batch)
        if not rows:
            self.figures_done = True
            self.store.settings_put("own_figures.cursor", [-1, -1])
            return 0
        self.store.add_own_figures(rows)
        last = rows[-1]
        self.store.settings_put("own_figures.cursor", [int(last["ts"]), int(last["rowid"])])
        self.figures_rows += len(rows)
        if len(rows) < batch:
            self.figures_done = True
            self.store.settings_put("own_figures.cursor", [-1, -1])
        return len(rows)

    #: how far back the daily repair looks for a kept turn without its shape row
    REPAIR_WINDOW_S = 3 * 86400

    def describe_missing(self, batch: int = 500) -> int:
        """Give a shape row to kept turns of the last days that have none: the turn and its
        row are two writes, and when the second failed (logged, the request unaffected) the
        turn stayed outside the quality figures for good. Returns how many were written; a
        daily pass, bounded to `REPAIR_WINDOW_S` so it never walks the whole table (older
        turns were described by the backfill, which pages)."""
        rows = self.db.samples_without_stats(batch, int(time.time()) - self.REPAIR_WINDOW_S)
        if not rows:
            return 0
        self.store.add_sample_stats(
            [
                sample_shape(
                    str(r["id"]),
                    str(r["account_id"]),
                    int(r["ts"]),
                    str(r["model"]),
                    str(r["request"] or ""),
                    str(r["response"] or ""),
                    str(r["meta"] or ""),
                )
                for r in rows
            ]
        )
        return len(rows)

    # -- clients that are not the apps ------------------------------------------------------------

    def abuse(self, days: int) -> dict[str, Any]:
        since, _today, _window = self._since(days)
        ua_rows = self.db.usage_by_ua(since)
        by_family = _fold_ua_rows(ua_rows, ua_family)
        accounts_by_family: dict[str, set[str]] = {}
        for p in self.db.account_ua_pairs(since):
            accounts_by_family.setdefault(ua_family(str(p["ua"] or "")), set()).add(str(p["account_id"]))
        total_requests = sum(g["requests"] for g in by_family.values()) or 1
        total_cost = sum(g["cost_uy"] for g in by_family.values()) or 1
        families = []
        for name, g in by_family.items():
            sample_ua = next((str(r["ua"]) for r in ua_rows if ua_family(str(r["ua"] or "")) == name), "")
            n = g["requests"]
            families.append(
                {
                    "family": name,
                    "platform": platform_of(sample_ua),
                    "app": is_app(platform_of(sample_ua)),
                    "requests": n,
                    "request_share": n / total_requests,
                    "accounts": len(accounts_by_family.get(name, ())),
                    "cost_cny": self._cny(g["cost_uy"]),
                    "cost_share": g["cost_uy"] / total_cost,
                    "avg_prompt_tokens": round(g["prompt_tokens"] / n) if n else 0,
                    "avg_completion_tokens": round(g["completion_tokens"] / n) if n else 0,
                    "distinct_uas": g["uas"],
                }
            )
        families.sort(key=lambda f: -f["requests"])
        non_app_requests = sum(f["requests"] for f in families if not f["app"])
        non_app_cost = sum(f["cost_cny"] for f in families if not f["app"])
        # sign-ins by client family in the window
        signins: dict[str, dict[str, int]] = {}
        for r in self.db.keys_by_ua(since):
            fam = ua_family(str(r["ua"] or ""))
            g = signins.setdefault(fam, {"sign_ins": 0, "accounts": 0, "app": is_app(platform_of(str(r["ua"] or "")))})
            g["sign_ins"] += int(r["n"])
            g["accounts"] += int(r["accounts"])
        signin_rows = sorted(({"family": k, **v} for k, v in signins.items()), key=lambda r: -r["sign_ins"])[:30]
        # every account's last client family: how many, how many already disabled
        last: dict[str, dict[str, int]] = {}
        for r in self.db.account_versions():
            fam = ua_family(str(r["last_ua"] or ""))
            g = last.setdefault(fam, {"accounts": 0, "disabled": 0})
            g["accounts"] += int(r["n"])
            g["disabled"] += int(r["disabled"] or 0)
        last_rows = sorted(
            (
                {"family": k, **v, "app": k.startswith(("nanoMuse-", "deepseek-harness", "Mozilla", "Minis")) or k == "nanoMuse"}
                for k, v in last.items()
            ),
            key=lambda r: -r["accounts"],
        )[:30]
        # the heaviest accounts whose client is not one of the apps
        suspects = []
        for r in self.db.account_ua_usage(since, 3000):
            ua = str(r["ua"] or "")
            if is_app(platform_of(ua)):
                continue
            suspects.append(
                {
                    "account_id": str(r["account_id"]),
                    "hint": str(r["hint"]),
                    "channel": str(r["channel"]),
                    "disabled": bool(r["disabled"]),
                    "member": bool(r["unlimited"]),
                    "created_at": int(r["created_at"]),
                    "family": ua_family(ua),
                    "ua": ua[:80],
                    "requests": int(r["requests"]),
                    "avg_prompt_tokens": round(int(r["prompt_tokens"] or 0) / int(r["requests"])) if int(r["requests"]) else 0,
                    "cost_cny": self._cny(r["cost_uy"]),
                    "last_ts": int(r["last_ts"] or 0),
                }
            )
            if len(suspects) >= 100:
                break
        self._label_rows(suspects)
        addresses = [
            {
                "ip": str(r["ip"]),
                "accounts": int(r["accounts"]),
                "disabled": int(r["disabled"] or 0),
                "first_at": int(r["first_at"]),
                "last_at": int(r["last_at"]),
            }
            for r in self.db.shared_first_addresses(5, 60)
        ]
        return {
            "generated_at": int(time.time()),
            "days": days,
            "summary": {
                "requests": total_requests if by_family else 0,
                "non_app_requests": non_app_requests,
                "non_app_request_share": non_app_requests / total_requests if by_family else 0.0,
                "non_app_cost_cny": round(non_app_cost, 4),
                "non_app_cost_share": (non_app_cost / self._cny(total_cost)) if by_family and total_cost > 1 else 0.0,
                "non_app_accounts": len(set().union(*(accounts_by_family.get(f["family"], set()) for f in families if not f["app"])))
                if families
                else 0,
                "families": len(families),
            },
            "families": families[:60],
            "sign_ins": signin_rows,
            "accounts_by_last_client": last_rows,
            "suspects": suspects,
            "shared_addresses": addresses,
            # 0.28: what the `apps_only` switch turned away; these never reach the ledger
            "apps_only": self.cloud.controls.on("apps_only"),
            "refused": [
                {
                    "family": str(r["family"]) or "(empty)",
                    "requests": int(r["n"]),
                    "accounts": int(r["accounts"]),
                    "last_ts": int(r["last_ts"] or 0),
                }
                for r in self.db.calls_refused_by_family(since)
            ],
        }
