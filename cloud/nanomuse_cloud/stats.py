"""0.22: the console's statistics — every metric defined once, here.

Each `Metric` says what it is called (English and 中文), *exactly how it is computed* (the
tooltip on the page), what shape it has (a series by UTC day, a table of groups, or a list
of facts) and which columns it carries; `Stats.build` fills it from the database and the
live objects (the hub, the collector). The JSON the page reads and the CSV the operator
downloads come from the same rows, so a number is never computed twice in two ways.

Days are UTC (`db.utc_day`); the page shows the operator's local time alongside. The
relay's own daily counters — API calls by group, accounts active by any call, errors by
code, sync volume — are kept in the `daily` table as the requests pass (api.py,
service.py), so they survive a restart.
"""

from __future__ import annotations

import csv
import io
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import __version__
from .db import utc_day
from .github_stats import GitHubCollector

if TYPE_CHECKING:
    from .hub import Hub
    from .service import Cloud
    from .sync import SyncStore

# the HTTP route groups the `api` counter keeps (api.py middleware)
API_GROUPS: tuple[tuple[str, str], ...] = (
    ("/v1/auth/", "auth"),
    ("/v1/me", "account"),
    ("/v1/chat/", "chat"),
    ("/v1/images/", "images"),
    ("/api/v1/", "video"),
    ("/v1/videos/", "video"),
    ("/v1/models", "models"),
    ("/v1/sync/", "sync"),
    ("/v1/devices", "devices"),
    ("/v1/estimate", "account"),
    ("/v1/config", "public"),
    ("/v1/nudges", "public"),
    ("/v1/admin/", "admin"),
    ("/healthz", "health"),
)


def api_group(path: str) -> str:
    for prefix, group in API_GROUPS:
        if path.startswith(prefix):
            return group
    return "other"


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    label_zh: str
    kind: str = "int"  # int | cny | str | ts | day | pct | bool

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "label": self.label, "label_zh": self.label_zh, "kind": self.kind}


@dataclass(frozen=True)
class Metric:
    id: str
    title: str
    title_zh: str
    how: str
    how_zh: str
    shape: str  # series | table | facts
    columns: tuple[Column, ...]
    build: Callable[[Stats, int], list[dict[str, Any]]]
    # a series' columns the chart draws (the rest are table-only); empty = every int column
    chart: tuple[str, ...] = field(default=())
    dynamic_columns: bool = False  # columns discovered from the rows (errors by code)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "title_zh": self.title_zh,
            "how": self.how,
            "how_zh": self.how_zh,
            "shape": self.shape,
            "columns": [c.as_dict() for c in self.columns],
            "chart": list(self.chart),
        }


DAY = Column("day", "Day (UTC)", "日期（UTC）", "day")


class Stats:
    def __init__(self, cloud: Cloud, sync_store: SyncStore, collector: GitHubCollector | None, hub_getter: Callable[[], Hub | None]):
        self.cloud = cloud
        # the metrics read through the read-only connection (Database.reader), off the loop
        # (api.py), so a slow one never holds the requests' lock; the one write, the health
        # probe, goes through cloud.db (see _relay)
        self.db = cloud.db.reader()
        self.sync_store = sync_store
        self.collector = collector
        self.hub_getter = hub_getter
        self.started_at = int(time.time())

    # -- the registry ------------------------------------------------------------------------

    def metrics(self) -> list[Metric]:
        return METRICS

    def metric(self, metric_id: str) -> Metric | None:
        return next((m for m in METRICS if m.id == metric_id), None)

    def build(self, metric: Metric, days: int) -> dict[str, Any]:
        rows = metric.build(self, days)
        out = metric.as_dict()
        if metric.dynamic_columns:
            keys: list[str] = []
            for r in rows:
                for k in r:
                    if k not in keys:
                        keys.append(k)
            out["columns"] = [DAY.as_dict() if k == "day" else Column(k, k, k, "int").as_dict() for k in keys]
        out["rows"] = rows
        return out

    def all(self, days: int) -> dict[str, Any]:
        t = int(time.time())
        return {
            "generated_at": t,
            "days": days,
            "since": utc_day(t) - 86400 * (days - 1),
            "metrics": [self.build(m, days) for m in METRICS],
        }

    def csv(self, metric: Metric, days: int) -> str:
        built = self.build(metric, days)
        cols = built["columns"]
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow([c["key"] for c in cols])
        for r in built["rows"]:
            w.writerow([_csv_cell(r.get(c["key"]), c["kind"]) for c in cols])
        return buf.getvalue()

    # -- helpers the builders share ---------------------------------------------------------------

    def window(self, days: int) -> tuple[int, int, list[int]]:
        """(since, today, [every UTC day of the window])"""
        today = utc_day(int(time.time()))
        since = today - 86400 * (days - 1)
        return since, today, [since + i * 86400 for i in range(days)]

    def identifier_of(self, account_id: str, enc: str) -> str:
        return self.cloud.crypto.decrypt(account_id, enc or "") or ""


def _csv_cell(v: Any, kind: str) -> Any:
    if v is None:
        return ""
    if kind in ("day", "ts"):
        return time.strftime("%Y-%m-%d" if kind == "day" else "%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(v)))
    if kind == "cny":
        return f"{float(v):.4f}"
    if kind == "bool":
        return 1 if v else 0
    return v


# -- the builders ----------------------------------------------------------------------------------


def _accounts_daily(s: Stats, days: int) -> list[dict[str, Any]]:
    since, _today, window = s.window(days)
    # the sign-ups of a day: the accounts still there plus those deleted since (a count per
    # sign-up day written at deletion; deletions before 0.29 left no such count)
    new = {int(r["day"]): int(r["n"]) for r in s.db.accounts_by_day(since, 0, s.cloud.review_hashes)}
    for r in s.db.daily_rows("accounts", since, "gone"):
        new[int(r["day"])] = new.get(int(r["day"]), 0) + int(r["value"])
    active_model = {int(r["day"]): int(r["n"]) for r in s.db.active_by_day(since, 0)}
    active_any = {int(r["day"]): int(r["n"]) for r in s.db.daily_distinct("active", since)}
    events: dict[int, dict[str, int]] = {}
    for r in s.db.events_by_day(since, 0):
        events.setdefault(int(r["day"]), {})[str(r["kind"])] = int(r["n"])
    total_now = s.db.account_counts()["total"]
    # the total at each day's end: today's count less what was created after that day, plus
    # what was deleted after it (the `account.deleted` line outlives the account)
    after = 0
    totals: dict[int, int] = {}
    for d in reversed(window):
        totals[d] = total_now - after
        after += new.get(d, 0) - events.get(d, {}).get("account.deleted", 0)
    rows = []
    for d in window:
        e = events.get(d, {})
        rows.append(
            {
                "day": d,
                "total": totals[d],
                "new": new.get(d, 0),
                "active_any": active_any.get(d, 0),
                "active_model": active_model.get(d, 0),
                "sign_ins": e.get("sign_in.code", 0) + e.get("sign_in.password", 0),
                "sign_in_failures": e.get("sign_in.failed", 0),
                "deleted": e.get("account.deleted", 0),
            }
        )
    return rows


def _accounts_by_method(s: Stats, days: int) -> list[dict[str, Any]]:
    return [
        {
            "method": str(r["channel"]),
            "accounts": int(r["accounts"] or 0),
            "with_password": int(r["with_password"] or 0),
            "members": int(r["members"] or 0),
            "disabled": int(r["disabled"] or 0),
            "contribute": int(r["contribute"] or 0),
            "sync_on": int(r["sync_on"] or 0),
        }
        for r in s.db.accounts_by_channel()
    ]


def _accounts_by_origin(s: Stats, days: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], int] = {}
    for a in s.db.list_accounts(limit=100_000):
        ident = s.identifier_of(a["id"], a["identifier_enc"])
        channel = str(a["channel"])
        if channel == "phone":
            origin = _country_code(ident) if ident else ("+86" if not str(a["hint"]).startswith("+") else "+?")
        else:
            origin = ident.rsplit("@", 1)[-1].lower() if "@" in ident else "?"
        groups[(channel, origin)] = groups.get((channel, origin), 0) + 1
    rows = [{"method": c, "origin": o, "accounts": n} for (c, o), n in groups.items()]
    rows.sort(key=lambda r: (-r["accounts"], r["origin"]))
    return rows


def _country_code(number: str) -> str:
    """+86 from +8613800138000: the one-digit codes (+1, +7), else two, with the few
    three-digit ones a relay is likely to see."""
    if not number.startswith("+"):
        return "+?"
    digits = number[1:]
    if digits[:1] in ("1", "7"):
        return "+" + digits[:1]
    three = (
        "852",
        "853",
        "886",
        "880",
        "855",
        "856",
        "960",
        "971",
        "972",
        "974",
        "966",
        "234",
        "254",
        "351",
        "353",
        "358",
        "380",
        "420",
        "421",
    )
    if digits[:3] in three:
        return "+" + digits[:3]
    return "+" + digits[:2]


def _devices_per_account(s: Stats, days: int) -> list[dict[str, Any]]:
    buckets: dict[str, int] = {"0": 0, "1": 0, "2": 0, "3": 0, "4+": 0}
    for r in s.db.devices_per_account():
        n = int(r["n"])
        buckets["4+" if n >= 4 else str(n)] += int(r["accounts"])
    return [{"devices": k, "accounts": v} for k, v in buckets.items()]


def _devices_by_platform(s: Stats, days: int) -> list[dict[str, Any]]:
    hub = s.hub_getter()
    online: dict[tuple[str, str], int] = {}
    if hub is not None:
        for conns in list(hub.online.values()):
            for conn in list(conns.values()):
                k = (str(conn.kind or ""), str(conn.os or ""))
                online[k] = online.get(k, 0) + 1
    return [
        {
            "kind": str(r["kind"]),
            "os": str(r["os"] or ""),
            "devices": int(r["n"]),
            "online": online.get((str(r["kind"]), str(r["os"] or "")), 0),
        }
        for r in s.db.devices_by_kind_os()
    ]


def _calls_daily(s: Stats, days: int) -> list[dict[str, Any]]:
    since, _today, window = s.window(days)
    by_day: dict[int, dict[str, Any]] = {}
    for r in s.db.usage_tokens_by_day(since, 0):
        d = by_day.setdefault(
            int(r["day"]),
            {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_uy": 0, "chat": 0, "image": 0, "video": 0, "realtime": 0},
        )
        d["requests"] += int(r["requests"] or 0)
        d["prompt_tokens"] += int(r["prompt_tokens"] or 0)
        d["completion_tokens"] += int(r["completion_tokens"] or 0)
        d["cost_uy"] += int(r["cost_uy"] or 0)
        d[str(r["kind"])] = d.get(str(r["kind"]), 0) + int(r["requests"] or 0)
    rows = []
    for d in window:
        v = by_day.get(d, {})
        rows.append(
            {
                "day": d,
                "requests": v.get("requests", 0),
                "prompt_tokens": v.get("prompt_tokens", 0),
                "completion_tokens": v.get("completion_tokens", 0),
                "tokens": v.get("prompt_tokens", 0) + v.get("completion_tokens", 0),
                "cost_cny": s.cloud.s.uy_to_cny(v.get("cost_uy", 0)),
                "chat": v.get("chat", 0),
                "image": v.get("image", 0),
                "video": v.get("video", 0),
                "realtime": v.get("realtime", 0),
            }
        )
    return rows


def _calls_by_model(s: Stats, days: int) -> list[dict[str, Any]]:
    since, _t, _w = s.window(days)
    return [
        {
            "model": str(r["model"]),
            "kind": str(r["kind"]),
            "requests": int(r["requests"] or 0),
            "prompt_tokens": int(r["prompt_tokens"] or 0),
            "completion_tokens": int(r["completion_tokens"] or 0),
            "cost_cny": s.cloud.s.uy_to_cny(int(r["cost_uy"] or 0)),
        }
        for r in s.db.usage_by_model(since)
    ]


def _top_accounts(s: Stats, days: int) -> list[dict[str, Any]]:
    since, _t, _w = s.window(days)
    rows = []
    for r in s.db.top_accounts_since(since, limit=20):
        a = s.db.account(r["account_id"])
        rows.append(
            {
                "identifier": s.identifier_of(r["account_id"], a["identifier_enc"]) if a is not None else "",
                "hint": str(a["hint"]) if a is not None else "",
                "account_id": str(r["account_id"]),
                "requests": int(r["requests"] or 0),
                "tokens": int(r["charged"] or 0),
                "cost_cny": s.cloud.s.uy_to_cny(int(r["cost_uy"] or 0)),
            }
        )
    return rows


ALLOWANCE_BUCKETS = (("0%", 0.0, 0.0), ("1–49%", 0.0, 0.5), ("50–79%", 0.5, 0.8), ("80–99%", 0.8, 1.0), ("100%", 1.0, 9e9))


def _allowance_distribution(s: Stats, days: int) -> list[dict[str, Any]]:
    counts = {name: 0 for name, _lo, _hi in ALLOWANCE_BUCKETS}
    counts["no limit"] = 0
    cloud = s.cloud
    for a in s.db.allowance_rows():
        member = bool(a["unlimited"]) or a["id_hash"] in cloud.member_hashes
        grant = int(a["grant_uy"] or 0)
        if member or cloud.s.allowance_cny <= 0 or grant <= 0:
            counts["no limit"] += 1
            continue
        frac = int(a["spent_uy"] or 0) / grant
        if frac <= 0:
            counts["0%"] += 1
        elif frac >= 1:
            counts["100%"] += 1
        else:
            for name, lo, hi in ALLOWANCE_BUCKETS[1:-1]:
                if lo <= frac < hi:
                    counts[name] += 1
                    break
    return [{"used": k, "accounts": v} for k, v in counts.items()]


def _sync_daily(s: Stats, days: int) -> list[dict[str, Any]]:
    since, _t, window = s.window(days)
    by_day: dict[int, dict[str, int]] = {}
    for r in s.db.daily_rows("sync", since):
        by_day.setdefault(int(r["day"]), {})[str(r["key"])] = int(r["value"])
    return [
        {"day": d, **{k: by_day.get(d, {}).get(k, 0) for k in ("pushes", "pulls", "messages_in", "accepted", "rejected")}} for d in window
    ]


def _errors_daily(s: Stats, days: int) -> list[dict[str, Any]]:
    since, _t, window = s.window(days)
    by_day: dict[int, dict[str, int]] = {}
    codes: dict[str, int] = {}
    for r in s.db.daily_rows("error", since):
        by_day.setdefault(int(r["day"]), {})[str(r["key"])] = int(r["value"])
        codes[str(r["key"])] = codes.get(str(r["key"]), 0) + int(r["value"])
    top = [c for c, _n in sorted(codes.items(), key=lambda kv: -kv[1])[:12]]
    rows = []
    for d in window:
        v = by_day.get(d, {})
        row: dict[str, Any] = {"day": d, "total": sum(v.values())}
        for c in top:
            row[c] = v.get(c, 0)
        other = sum(n for c, n in v.items() if c not in top)
        if len(codes) > len(top):
            row["other"] = other
        rows.append(row)
    return rows


def _api_daily(s: Stats, days: int) -> list[dict[str, Any]]:
    since, _t, window = s.window(days)
    by_day: dict[int, dict[str, int]] = {}
    for r in s.db.daily_rows("api", since):
        by_day.setdefault(int(r["day"]), {})[str(r["key"])] = int(r["value"])
    groups = ["auth", "account", "chat", "images", "video", "models", "sync", "devices", "public", "admin", "health", "other"]
    return [{"day": d, "total": sum(by_day.get(d, {}).values()), **{g: by_day.get(d, {}).get(g, 0) for g in groups}} for d in window]


def _github_daily(s: Stats, days: int) -> list[dict[str, Any]]:
    if s.collector is None:
        return []
    return [
        {
            k: r.get(k)
            for k in (
                "day",
                "snapshot",
                "stars",
                "new_stars",
                "forks",
                "new_forks",
                "watchers",
                "new_watchers",
                "issues",
                "downloads",
                "new_downloads",
            )
        }
        for r in s.collector.series(days)["days"]
    ]


def _github_assets(s: Stats, days: int) -> list[dict[str, Any]]:
    if s.collector is None:
        return []
    latest = s.collector.series(1)["latest"]
    return [{"asset": a["name"], "platform": a["platform"], "downloads": a["downloads"]} for a in latest["assets"]]


def _relay(s: Stats, days: int) -> list[dict[str, Any]]:
    t = int(time.time())
    hub = s.hub_getter()
    db = s.cloud.db.health()  # a write probe: the relay's own connection, not the read-only one
    paused = [k for k, v in s.cloud.controls.paused().items() if v]
    sync = s.sync_store.admin_totals()
    gh_ok = s.collector.last_ok if s.collector is not None else None
    return [
        {"fact": "version", "value": __version__},
        {"fact": "started_at", "value": _iso(s.started_at)},
        {"fact": "uptime", "value": _duration(t - s.started_at)},
        {"fact": "now_utc", "value": _iso(t)},
        {"fact": "day_offset_h", "value": str(s.cloud.s.day_offset_h)},
        {"fact": "db_bytes", "value": str(db["size_bytes"])},
        {"fact": "db_writable", "value": "yes" if db["writable"] else "NO"},
        {"fact": "hub_online", "value": str(hub.online_count() if hub is not None else 0)},
        {"fact": "paused", "value": ", ".join(paused) or "none"},
        {"fact": "sync_accounts_on", "value": str(sync.get("accounts_enabled", 0))},
        {"fact": "sync_bytes", "value": str(sync.get("bytes", 0))},
        {"fact": "github_last_ok", "value": _iso(gh_ok) if gh_ok else "never"},
    ]


def _iso(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts)))


def _duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    d, rem = divmod(seconds, 86400)
    hh, rem = divmod(rem, 3600)
    mm = rem // 60
    return f"{d}d {hh}h {mm}m" if d else f"{hh}h {mm}m"


N = "int"
METRICS: list[Metric] = [
    Metric(
        "accounts_daily",
        "Accounts by day",
        "账号 · 每日",
        "Per UTC day: total = accounts existing at the day's end (today's count minus those created later); new = accounts whose created_at falls in the day, the app store reviewer's (REVIEW_ADDRESSES) left out; "
        "active_any = distinct accounts that made at least one authenticated API call that day (counted in the `daily` table as requests pass); "
        "active_model = distinct accounts with at least one charged model request in the ledger; sign_ins = sign_in.code + sign_in.password events; "
        "sign_in_failures = sign_in.failed events.",
        "按 UTC 日：total = 当天结束时存在的账号数（今天的总数减去之后创建的）；new = created_at 落在当天的账号，不含应用商店审核员的账号（REVIEW_ADDRESSES）；active_any = 当天至少发过一次带密钥 API 请求的账号数（请求经过时记入 daily 表）；"
        "active_model = 账单里当天至少有一次计费模型请求的账号数；sign_ins = sign_in.code 与 sign_in.password 事件之和；sign_in_failures = sign_in.failed 事件。",
        "series",
        (
            DAY,
            Column("total", "Total", "累计", N),
            Column("new", "New", "新注册", N),
            Column("active_any", "Active (any call)", "活跃（任一请求）", N),
            Column("active_model", "Active (model call)", "活跃（模型请求）", N),
            Column("sign_ins", "Sign-ins", "登录", N),
            Column("sign_in_failures", "Failed sign-ins", "登录失败", N),
            Column("deleted", "Deleted", "注销", N),
        ),
        _accounts_daily,
        chart=("new", "active_any", "active_model"),
    ),
    Metric(
        "accounts_by_method",
        "Accounts by sign-in method",
        "账号 · 按登录方式",
        "Every account grouped by its channel (phone or e-mail); with_password = a password is set; members = flagged unlimited by the operator (the environment's list is not counted here); "
        "disabled, contribute (“help improve” on) and sync_on are the account flags as they stand now.",
        "全部账号按渠道（手机 / 邮箱）分组；with_password = 设了密码；members = 后台设为成员（环境变量白名单不计入）；disabled、contribute（开启「帮助改进」）、sync_on 为账号当前的开关状态。",
        "table",
        (
            Column("method", "Method", "方式", "str"),
            Column("accounts", "Accounts", "账号", N),
            Column("with_password", "With a password", "设了密码", N),
            Column("members", "Members", "成员", N),
            Column("disabled", "Disabled", "已停用", N),
            Column("contribute", "“Help improve” on", "开启「帮助改进」", N),
            Column("sync_on", "Sync on", "开启同步", N),
        ),
        _accounts_by_method,
    ),
    Metric(
        "accounts_by_origin",
        "Accounts by country code or e-mail domain",
        "账号 · 按国家码 / 邮箱域名",
        "Each account's stored identifier, decrypted for this view only: a phone number's country code (+86, +1, +852 …), an e-mail address's domain (after the @, lower case). "
        "Accounts from before the identifier was kept show +86 (a mainland hint) or ?.",
        "每个账号存储的标识符（仅此处解密）：手机号取国家码（+86、+1、+852…），邮箱取 @ 后的域名（小写）。保存标识符之前注册的账号显示 +86（大陆号码提示）或 ?。",
        "table",
        (
            Column("method", "Method", "方式", "str"),
            Column("origin", "Country code / domain", "国家码 / 域名", "str"),
            Column("accounts", "Accounts", "账号", N),
        ),
        _accounts_by_origin,
    ),
    Metric(
        "devices_per_account",
        "Devices per account",
        "每个账号的设备数",
        "How many accounts remember 0, 1, 2, 3 or 4+ devices on the hub (the `devices` table: a device is remembered when it first connects and until it is forgotten).",
        "设备通道上记住 0、1、2、3、4+ 台设备的账号各有多少（devices 表：设备首次连接时记住，直到被遗忘）。",
        "table",
        (Column("devices", "Devices", "设备数", "str"), Column("accounts", "Accounts", "账号", N)),
        _devices_per_account,
    ),
    Metric(
        "devices_by_platform",
        "Devices by platform",
        "设备 · 按平台",
        "Remembered devices grouped by kind (phone, computer, web) and operating system as the device announced it in its hub hello; online = sockets open right now for that group.",
        "记住的设备按类型（手机、电脑、网页）和设备在 hello 帧里报告的系统分组；online = 该组此刻在线的连接数。",
        "table",
        (
            Column("kind", "Kind", "类型", "str"),
            Column("os", "System", "系统", "str"),
            Column("devices", "Devices", "设备", N),
            Column("online", "Online now", "此刻在线", N),
        ),
        _devices_by_platform,
    ),
    Metric(
        "calls_daily",
        "Model calls by day",
        "模型请求 · 每日",
        "Per UTC day from the ledger (every charged chat, picture, clip and call): requests, tokens in (prompt) and out (completion), their sum, the cost at list prices in yuan, "
        "and the requests per kind. A request the provider refused costs nothing and is not here.",
        "按 UTC 日从账单统计（每次计费的对话、图片、视频、通话）：请求数、输入 / 输出 tokens 及其和、按标价估算的费用（元）、各类型请求数。被服务商拒绝的请求不计费、不在此列。",
        "series",
        (
            DAY,
            Column("requests", "Requests", "请求", N),
            Column("prompt_tokens", "Tokens in", "输入 tokens", N),
            Column("completion_tokens", "Tokens out", "输出 tokens", N),
            Column("tokens", "Tokens", "tokens 合计", N),
            Column("cost_cny", "Cost (¥)", "费用（¥）", "cny"),
            Column("chat", "Chat", "对话", N),
            Column("image", "Pictures", "图片", N),
            Column("video", "Clips", "视频", N),
            Column("realtime", "Calls", "通话", N),
        ),
        _calls_daily,
        chart=("requests",),
    ),
    Metric(
        "calls_by_model",
        "Model calls by model",
        "模型请求 · 按模型",
        "The period's ledger grouped by model id: requests, tokens in and out, cost at list prices. Unlisted models a member asked for by name are priced as the dearest menu model of their kind.",
        "本期账单按模型 id 分组：请求数、输入 / 输出 tokens、按标价估算的费用。成员按名字点的菜单外模型按同类最贵菜单模型计价。",
        "table",
        (
            Column("model", "Model", "模型", "str"),
            Column("kind", "Kind", "类型", "str"),
            Column("requests", "Requests", "请求", N),
            Column("prompt_tokens", "Tokens in", "输入 tokens", N),
            Column("completion_tokens", "Tokens out", "输出 tokens", N),
            Column("cost_cny", "Cost (¥)", "费用（¥）", "cny"),
        ),
        _calls_by_model,
    ),
    Metric(
        "top_accounts",
        "Top 20 accounts by cost",
        "花费最多的 20 个账号",
        "The period's ledger grouped by account, the twenty with the highest cost at list prices; tokens = charged tokens (after the model's multiplier). The identifier is decrypted for this view only.",
        "本期账单按账号分组，取按标价费用最高的 20 个；tokens = 计费 tokens（乘以模型系数后）。标识符仅此处解密。",
        "table",
        (
            Column("identifier", "Account", "账号", "str"),
            Column("account_id", "Id", "ID", "str"),
            Column("requests", "Requests", "请求", N),
            Column("tokens", "Tokens", "tokens", N),
            Column("cost_cny", "Cost (¥)", "费用（¥）", "cny"),
        ),
        _top_accounts,
    ),
    Metric(
        "allowance_distribution",
        "Allowance used",
        "免费额度使用分布",
        "Every limited account placed by spent ÷ pool (the ledger's lifetime cost ÷ grant_uy): exactly 0 %, under 50 %, 50–79 %, 80–99 % (the apps warn at 80 %), 100 % or more (refused). "
        "Members, and everyone when ALLOWANCE_CNY is 0, are “no limit”.",
        "每个受限账号按 已花费 ÷ 总额度（账单累计费用 ÷ grant_uy）归入：恰好 0%、不足 50%、50–79%、80–99%（客户端在 80% 提醒）、100% 及以上（被拒）。成员以及 ALLOWANCE_CNY=0 时的所有人为「不限」。",
        "table",
        (Column("used", "Used", "已用", "str"), Column("accounts", "Accounts", "账号", N)),
        _allowance_distribution,
    ),
    Metric(
        "sync_daily",
        "Conversation sync by day",
        "对话同步 · 每日",
        "Per UTC day, counted as the requests pass: pushes = POST /v1/sync/changes calls, pulls = GET /v1/sync/changes calls, messages_in = messages carried by the pushes, "
        "accepted = changes that took a seq, rejected = changes refused. Never a text.",
        "按 UTC 日，请求经过时计数：pushes = POST /v1/sync/changes 次数，pulls = GET /v1/sync/changes 次数，messages_in = 推送携带的消息数，accepted = 获得 seq 的变更数，rejected = 被拒的变更数。不含任何文字。",
        "series",
        (
            DAY,
            Column("pushes", "Pushes", "推送", N),
            Column("pulls", "Pulls", "拉取", N),
            Column("messages_in", "Messages sent", "发来的消息", N),
            Column("accepted", "Accepted", "接受", N),
            Column("rejected", "Rejected", "拒绝", N),
        ),
        _sync_daily,
        chart=("pushes", "pulls"),
    ),
    Metric(
        "errors_daily",
        "Errors by day and code",
        "错误 · 每日按代码",
        "Per UTC day: every error the relay answered, by its `code` (the relay's own refusals, such as bad_key, allowance_exhausted, rate_limited and service_paused, and the provider's, upstream_*), counted as they are sent. "
        "total = all codes; the twelve most frequent codes of the period get a column, the rest are “other”.",
        "按 UTC 日：中继返回的每个错误按 code 计数（中继自己的拒绝，如 bad_key、allowance_exhausted、rate_limited、service_paused，以及服务商的 upstream_*），发送时记入。total = 全部；本期最常见的 12 个 code 各一列，其余归入 other。",
        "series",
        (DAY, Column("total", "Total", "合计", N)),
        _errors_daily,
        chart=("total",),
        dynamic_columns=True,
    ),
    Metric(
        "api_daily",
        "API calls by day",
        "API 请求 · 每日",
        "Per UTC day: every HTTP request the relay answered, grouped by route: auth (/v1/auth/*), account (/v1/me*, /v1/estimate), chat, images, video (/api/v1/*), models, sync, devices, "
        "public (/v1/config, /v1/nudges), admin, health, other; counted in the middleware whatever the status. The console's own files (/app/*) and hub WebSocket frames are not API calls and are not here.",
        "按 UTC 日：中继应答的每个 HTTP 请求按路由分组（auth、account、chat、images、video、models、sync、devices、public、admin、health、other），在中间件里计数，不论状态码。控制台自身的文件（/app/*）和设备通道的 WebSocket 帧不是 API 请求，不在此列。",
        "series",
        (
            DAY,
            Column("total", "Total", "合计", N),
            Column("auth", "auth", "auth", N),
            Column("account", "account", "account", N),
            Column("chat", "chat", "chat", N),
            Column("images", "images", "images", N),
            Column("video", "video", "video", N),
            Column("models", "models", "models", N),
            Column("sync", "sync", "sync", N),
            Column("devices", "devices", "devices", N),
            Column("public", "public", "public", N),
            Column("admin", "admin", "admin", N),
            Column("health", "health", "health", N),
            Column("other", "other", "other", N),
        ),
        _api_daily,
        chart=("total",),
    ),
    Metric(
        "github_daily",
        "GitHub stars and downloads by day",
        "GitHub stars 与下载 · 每日",
        "One snapshot per UTC day from GitHub's API (GET /repos/{owner}/{repo}: stargazers_count, forks_count, subscribers_count as watchers, open_issues_count; GET /repos/{owner}/{repo}/releases: "
        "the sum of every asset's download_count). The last run of a day is the day's figure; new_* = the day's figure minus the previous snapshot's (a gap counts towards the next day with a snapshot). "
        "Empty = no snapshot that day.",
        "每个 UTC 日一份快照，来自 GitHub API（GET /repos/{owner}/{repo}：stargazers_count、forks_count、subscribers_count 作为 watchers、open_issues_count；GET /repos/{owner}/{repo}/releases：全部 asset 的 download_count 之和）。"
        "当天最后一次采集为当天数值；new_* = 当天数值减去上一份快照（中间缺的天数算到下一个有快照的日子）。空 = 当天没有快照。",
        "series",
        (
            DAY,
            Column("stars", "Stars", "Stars", N),
            Column("new_stars", "New stars", "新增 stars", N),
            Column("forks", "Forks", "Forks", N),
            Column("new_forks", "New forks", "新增 forks", N),
            Column("watchers", "Watchers", "Watchers", N),
            Column("new_watchers", "New watchers", "新增 watchers", N),
            Column("issues", "Open issues", "打开的 issue", N),
            Column("downloads", "Downloads", "下载", N),
            Column("new_downloads", "New downloads", "新增下载", N),
            Column("snapshot", "Snapshot", "有快照", "bool"),
        ),
        _github_daily,
        chart=("new_stars", "new_downloads"),
    ),
    Metric(
        "github_assets",
        "Release downloads by asset",
        "各发布文件的下载",
        "From the latest snapshot: every release asset on GitHub with its download_count, and the platform guessed from its name (apk → android, ipa → ios, dmg/pkg/mac → mac, exe/msi/win → windows, AppImage/deb/rpm/linux → linux, docker/tar → docker).",
        "来自最新快照：GitHub 上每个发布文件及其 download_count，平台由文件名推断（apk → android，ipa → ios，dmg/pkg/mac → mac，exe/msi/win → windows，AppImage/deb/rpm/linux → linux，docker/tar → docker）。",
        "table",
        (
            Column("asset", "Asset", "文件", "str"),
            Column("platform", "Platform", "平台", "str"),
            Column("downloads", "Downloads", "下载", N),
        ),
        _github_assets,
    ),
    Metric(
        "relay",
        "The relay",
        "中继本身",
        "Live facts: the package version, when this process started and how long it has run, the server's clock (UTC), DAY_OFFSET_H (the local day the older panels group by), the database file's size and whether a write goes through, "
        "hub sockets open, which switches are off, sync totals, and the GitHub collector's last successful run.",
        "实时事实：版本、本进程启动时间与运行时长、服务器时钟（UTC）、DAY_OFFSET_H（旧面板按此划分本地日）、数据库文件大小与是否可写、在线的设备通道连接数、关闭的开关、同步合计、GitHub 采集最近一次成功时间。",
        "facts",
        (Column("fact", "Fact", "项目", "str"), Column("value", "Value", "值", "str")),
        _relay,
    ),
]
