"""Settings, all from the environment (or a `.env` you source before starting).

Every value has a development default so `python -m nanomuse_cloud` runs on a
laptop with nothing set: codes go to the log, the database is ./data/cloud.db,
and the upstream is whatever UPSTREAM_BASE / UPSTREAM_KEY say (without a key
the proxy answers 503, but sign-up still works, which is what the app tests
need).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field, replace

# What a chat model is for (0.17): the conversation ("chat") or the hands — the GUI model
# that reads screenshots and drives a phone or a computer ("gui"). A model may do both.
# The apps keep two settings, a chat model and a hands model, and read `for` to fill
# each picker; `recommended_for` says which lane a recommended model is recommended in.
LANES = ("chat", "gui")


def _lanes(value: object, what: str) -> tuple[str, ...]:
    """A lane list from JSON or code, checked: known names, no repeats, in menu order."""
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{what} is a list of lanes ({', '.join(LANES)})")
    out: list[str] = []
    for lane in value:
        if lane not in LANES:
            raise ValueError(f"{what}: unknown lane {lane!r} (one of {', '.join(LANES)})")
        if lane not in out:
            out.append(str(lane))
    return tuple(out)


def positive_capacity(value: object) -> int | None:
    """A wire capacity fits each client within a signed 32-bit token count."""
    return value if type(value) is int and 0 < value <= 2**31 - 1 else None


@dataclass(frozen=True)
class ModelSpec:
    """One model the relay offers. `id` is what the app sees and asks for;
    `upstream` is what the provider is asked for (usually the same)."""

    id: str
    name: str
    upstream: str
    kind: str = "chat"  # chat | image | video
    input_modalities: tuple[str, ...] = ("text",)
    output_modalities: tuple[str, ...] = ("text",)
    context_length: int | None = None
    max_output_tokens: int | None = None
    # The lanes a chat model serves, serialised as `for`: ("chat",), ("gui",) or both;
    # empty means "chat" for a chat model and nothing for a picture or a clip model
    # (their `kind` says what they do). `recommended_for` names the lane(s) a model
    # marked `recommended` is recommended in — one chat model and one gui model on the
    # shipped menu — so a client keeps its two defaults apart.
    for_: tuple[str, ...] = ()
    recommended_for: tuple[str, ...] = ()
    # Charged tokens = prompt × in_mult + completion × out_mult. Multipliers let
    # a cheap model stretch the grant further than an expensive one without the
    # account holder seeing money.
    in_mult: float = 1.0
    out_mult: float = 1.0
    # Images have no token count; each one costs this many tokens of grant.
    per_image: int = 0
    # Nor do clips: each accepted video task costs this many (billed per output
    # second upstream, so this is set for the short clips the app makes).
    per_clip: int = 0
    recommended: bool = False
    # What the provider bills the operator, in yuan — the list price of the
    # Beijing region unless CLOUD_MODELS says otherwise. Chat: per million
    # tokens in and out (one yuan per million tokens is one micro-yuan per
    # token, which is how the ledger stores money). Images: per picture, the
    # 2k tier for anything wider than 1k. Video: per output second.
    price_in: float = 0.0
    price_out: float = 0.0
    # A model priced by the hour (DeepSeek on Model Studio): what a token costs in the
    # idle hours, `idle_hours` (start, end) in Beijing time, the provider's clock — 0 means
    # the day price all day. A request is priced at the hour it is charged (the reply in).
    price_in_idle: float = 0.0
    price_out_idle: float = 0.0
    idle_hours: tuple[int, int] = (22, 8)
    # What an input token the provider served from its cache costs, as a share of a fresh
    # one (`usage.prompt_tokens_details.cached_tokens`, a part of prompt_tokens). Model
    # Studio's implicit cache is on for every model and cannot be turned off: 0.2 for the
    # Qwen models, 0.1 for deepseek-v4.1-flash; 1 = no discount, cached tokens at full price.
    cached_in_rate: float = 1.0
    price_image: float = 0.0
    price_image_2k: float = 0.0
    # What the provider charges for a picture sent *in* (an edit's source picture).
    price_image_in: float = 0.0
    price_second: float = 0.0
    # Per output second at the resolutions above the base one, by the provider's name for
    # them (("720P", 0.2), ("1080P", 0.48); a JSON object in CLOUD_MODELS); `price_second`
    # is the base, the resolution the apps ask for (480P).
    price_second_res: tuple[tuple[str, float], ...] = ()
    # The clip length when the app does not say (`parameters.duration` absent):
    # Wan 2.2 always makes five seconds, MiniMax four at the least.
    clip_seconds: float = 4.0
    # On the menu (the list every account gets), or asked for by name by a member
    # (Settings.unlisted_model): then `priced_as` names the menu model whose prices
    # stand in for the unknown ones in the ledger.
    listed: bool = True
    priced_as: str = ""

    def __post_init__(self) -> None:
        for capacity_key in ("context_length", "max_output_tokens"):
            value = getattr(self, capacity_key)
            if value is not None and positive_capacity(value) is None:
                raise ValueError(f"{self.id}: {capacity_key} must be a positive 32-bit integer")
        # a lane list from CLOUD_MODELS may arrive as a list; keep tuples, and only known lanes
        object.__setattr__(self, "for_", _lanes(self.for_, f"{self.id}: for"))
        object.__setattr__(self, "recommended_for", _lanes(self.recommended_for, f"{self.id}: recommended_for"))
        if self.kind != "chat" and (self.for_ or self.recommended_for):
            raise ValueError(f"{self.id}: lanes are for chat models; a {self.kind} model has none")
        if self.recommended_for and not self.recommended:
            raise ValueError(f"{self.id}: recommended_for needs recommended: true")
        if any(lane not in self.lanes for lane in self.recommended_for):
            raise ValueError(f"{self.id}: recommended_for names a lane the model is not for")
        # the prices by resolution may arrive as a JSON object; keep a tuple (the spec is hashable)
        res = self.price_second_res
        if isinstance(res, dict):
            res = tuple(res.items())
        object.__setattr__(self, "price_second_res", tuple((str(k).upper(), float(v)) for k, v in res))
        hours = tuple(int(h) for h in self.idle_hours)
        if len(hours) != 2 or not all(0 <= h <= 24 for h in hours):
            raise ValueError(f"{self.id}: idle_hours is [start, end] in hours of the day, Beijing time")
        object.__setattr__(self, "idle_hours", hours)
        if not 0 <= self.cached_in_rate <= 1:
            raise ValueError(f"{self.id}: cached_in_rate is a share of the input price, between 0 and 1")

    @property
    def lanes(self) -> tuple[str, ...]:
        """What the model is for: `for_` as given, else chat for a chat model, nothing else."""
        if self.for_:
            return self.for_
        return ("chat",) if self.kind == "chat" else ()

    @property
    def recommended_lanes(self) -> tuple[str, ...]:
        """The lane(s) the model is recommended in: `recommended_for` as given, else every
        lane of a recommended chat model, nothing for the rest."""
        if self.recommended_for:
            return self.recommended_for
        return self.lanes if self.recommended else ()

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "object": "model",
            "name": self.name,
            "owned_by": "nanomuse-cloud",
            **{key: getattr(self, key) for key in ("context_length", "max_output_tokens") if getattr(self, key) is not None},
            "architecture": {
                "input_modalities": list(self.input_modalities),
                "output_modalities": list(self.output_modalities),
            },
            "nanomuse": {
                "kind": self.kind,
                "for": list(self.lanes),
                "listed": self.listed,
                "priced_as": self.priced_as,
                "recommended": self.recommended,
                "recommended_for": list(self.recommended_lanes),
                "in_mult": self.in_mult,
                "out_mult": self.out_mult,
                "per_image": self.per_image,
                "per_clip": self.per_clip,
                "clip_seconds": self.clip_seconds,
                "price_cny": {
                    "per_m_input": self.price_in,
                    "per_m_output": self.price_out,
                    "per_m_input_idle": self.price_in_idle,
                    "per_m_output_idle": self.price_out_idle,
                    "idle_hours": list(self.idle_hours),
                    "per_m_cached_input": round(self.price_in * self.cached_in_rate, 6),
                    "per_image": self.price_image,
                    "per_image_2k": self.price_image_2k,
                    "per_image_in": self.price_image_in,
                    "per_second": self.price_second,
                    "per_second_res": dict(self.price_second_res),
                },
            },
        }

    # -- what one request costs, in micro-yuan (1e-6 CNY; integers in the ledger) --

    def idle_at(self, t: int | float) -> bool:
        """Whether the UNIX time `t` falls in the model's idle hours (Beijing time), when it
        has an idle price at all."""
        if not (self.price_in_idle or self.price_out_idle):
            return False
        start, end = self.idle_hours
        hour = (int(t) + BEIJING_OFFSET_S) // 3600 % 24
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def chat_prices(self, at: int | float | None = None) -> tuple[float, float]:
        """The input and output price per million tokens at `at` (None: the day price)."""
        if at is not None and self.idle_at(at):
            return self.price_in_idle or self.price_in, self.price_out_idle or self.price_out
        return self.price_in, self.price_out

    def chat_cost_uy(self, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0, at: int | float | None = None) -> int:
        """Prompt tokens at the input price — the cached part of them (a part of
        prompt_tokens, as the provider reports it) at `cached_in_rate` of it — and completion
        tokens (the reasoning included) at the output price, both as in force at `at`."""
        prompt = max(0, prompt_tokens)
        cached = min(prompt, max(0, cached_tokens))
        price_in, price_out = self.chat_prices(at)
        fresh = (prompt - cached) * price_in + cached * price_in * self.cached_in_rate
        return round(fresh + max(0, completion_tokens) * price_out)

    def image_cost_uy(self, size: str | None = None, inputs: int = 0) -> int:
        """One picture out at the tier `size` falls in, plus `inputs` pictures sent in."""
        price = self.price_image
        if self.price_image_2k and size and _max_side(size) > 1400:
            price = self.price_image_2k
        return round((price + max(0, inputs) * self.price_image_in) * 1_000_000)

    def video_cost_uy(self, seconds: float, resolution: str | None = None) -> int:
        """`seconds` of output at `resolution` ("480P", "720P", "1080P"; None or an unknown
        one: the base price)."""
        price = dict(self.price_second_res).get((resolution or "").upper(), self.price_second)
        return round(max(0.0, seconds) * price * 1_000_000)


# The provider's clock for by-the-hour prices (DeepSeek's idle hours are Beijing time).
BEIJING_OFFSET_S = 8 * 3600


def _max_side(size: str) -> int:
    """The longer side of "1024x1024" / "1664*928"; 0 when unreadable."""
    try:
        parts = [int(p) for p in size.lower().replace("*", "x").split("x")[:2]]
    except ValueError:
        return 0
    return max(parts) if parts else 0


# The hosted menu is deliberately chat-only. The one Qwen model reads image input and
# serves both the conversation and GUI lanes; image/video generation belongs to providers
# and API keys configured by the person on their device.
DEFAULT_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="Qwen/Qwen3.6-27B-FP8",
        name="Qwen 3.6 27B FP8",
        upstream="Qwen/Qwen3.6-27B-FP8",
        input_modalities=("text", "image"),
        for_=("chat", "gui"),
        recommended=True,
        recommended_for=("chat", "gui"),
        price_in=3.0,
        price_out=12.0,
        cached_in_rate=0.2,
    ),
)


# Ids older app builds still send, and what answers them now. Video is not
# aliased: a MiniMax-shaped request body does not fit Wan, and the app's probe
# simply finds the old model gone and stops animating.
LEGACY_MODEL_IDS: dict[str, str] = {"qwen-image-3.0-pro": "qwen-image-3.0"}

# What a model id may look like when a member types one (the provider's ids:
# letters, digits, dots, dashes, underscores, a slash or a colon for namespaced ones).
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$")

# What each kind of request can carry in and give back, for a model the menu does
# not describe: the widest shape, and the provider says no when a model is narrower.
_UNLISTED_MODALITIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "chat": (("text", "image"), ("text",)),
    "image": (("text", "image"), ("image",)),
    "video": (("text", "image"), ("video",)),
}


# Where a reverse proxy in front of the relay can be: loopback, the private ranges, the
# shared range carrier-grade NAT and tailnets use, link-local. uvicorn believes
# X-Forwarded-For from these peers only (TRUSTED_PROXIES replaces the list).
NON_GLOBAL_NETWORKS: tuple[str, ...] = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "100.64.0.0/10",
    "169.254.0.0/16",
    "fc00::/7",
    "fe80::/10",
)


# Mail providers whose domains are never under the per-domain sign-up limit: anyone can
# have an address there, so many sign-ups from one of them say nothing about one person.
WELL_KNOWN_MAIL_DOMAINS: frozenset[str] = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "yahoo.co.jp",
        "ymail.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "qq.com",
        "foxmail.com",
        "163.com",
        "126.com",
        "yeah.net",
        "sina.com",
        "sina.cn",
        "sohu.com",
        "aliyun.com",
        "protonmail.com",
        "proton.me",
        "pm.me",
        "zoho.com",
        "gmx.com",
        "gmx.de",
        "gmx.net",
        "web.de",
        "mail.ru",
        "yandex.ru",
        "yandex.com",
        "naver.com",
        "daum.net",
        "139.com",
        "189.cn",
        "wo.cn",
    }
)

# Disposable and throwaway mail domains blocked from opening new accounts by default;
# SIGNUP_DOMAIN_BLOCK adds more, and SIGNUP_DOMAIN_ALLOW can override an entry here.
DEFAULT_SIGNUP_DOMAIN_BLOCK: tuple[str, ...] = (
    "duckmail.sbs",
    "fexbox.org",
    "fexpost.com",
    "gmeenramy.com",
    "guerrillamail.biz",
    "guerrillamail.com",
    "guerrillamail.de",
    "guerrillamail.net",
    "guerrillamail.org",
    "guerrillamailblock.com",
    "lnovic.com",
    "mailinator.com",
    "mailto.plus",
    "markaihub.shop",
    "maxxspace.com",
    "mydefipet.live",
    "olipii.com",
    "ooynib.com",
    "pokemail.net",
    "psnator.com",
    "ruutukf.com",
    "sharklasers.com",
    "smartnator.com",
    "spam4.me",
    "tanpony.com",
    "temp-mail.lol",
    "tempmail.com",
    "tmpmailtor.com",
    "trashmail.com",
    "yopmail.com",
    "yzcalo.com",
)


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return default if v is None or v == "" else v


def _int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _models_from_env() -> tuple[ModelSpec, ...]:
    raw = _env("CLOUD_MODELS")
    if not raw:
        return DEFAULT_MODELS
    out = []
    for item in json.loads(raw):
        item = dict(item)
        if "for" in item:  # the JSON name; `for` is a keyword in Python
            item["for_"] = item.pop("for")
        for k in ("input_modalities", "output_modalities", "for_", "recommended_for"):
            if k in item:
                item[k] = tuple(item[k])
        out.append(ModelSpec(**item))
    return tuple(out)


def _model_aliases_from_env() -> dict[str, str]:
    raw = _env("CLOUD_MODEL_ALIASES")
    if not raw:
        return dict(LEGACY_MODEL_IDS)
    aliases = json.loads(raw)
    if not isinstance(aliases, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in aliases.items()):
        raise ValueError("CLOUD_MODEL_ALIASES must be a JSON object of model ids")
    return {**LEGACY_MODEL_IDS, **aliases}


def menu_warnings(models: tuple[ModelSpec, ...]) -> list[str]:
    """What is odd about a menu — for the log at start, not an error: the clients pick the
    recommended model of each lane as a default, so there should be exactly one."""
    out = []
    for lane in LANES:
        picks = [m.id for m in models if m.kind == "chat" and lane in m.recommended_lanes]
        if len(picks) != 1:
            out.append(f"{len(picks)} chat models recommended for {lane} ({', '.join(picks) or 'none'}); the apps expect one")
    return out


@dataclass(frozen=True)
class Settings:
    database: str = field(default_factory=lambda: _env("CLOUD_DB", "./data/cloud.db"))
    # HMAC key for hashing phone numbers / e-mail addresses. Required outside
    # development: without it identifiers are hashed with a fixed string and
    # a leaked database would be trivially reversible for phone numbers.
    secret: str = field(default_factory=lambda: _env("CLOUD_SECRET"))
    admin_token: str = field(default_factory=lambda: _env("CLOUD_ADMIN_TOKEN"))
    # What the app should put in the provider's base URL, without /v1.
    public_base: str = field(default_factory=lambda: _env("PUBLIC_BASE", "http://127.0.0.1:8787"))

    upstream_base: str = field(default_factory=lambda: _env("UPSTREAM_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    upstream_key: str = field(default_factory=lambda: _env("UPSTREAM_KEY"))
    # DashScope's native host, for drawing (its OpenAI-compatible host has no
    # images endpoint). Empty keeps using UPSTREAM_KEY for backwards compatibility.
    dashscope_base: str = field(default_factory=lambda: _env("DASHSCOPE_BASE", "https://dashscope.aliyuncs.com/api/v1"))
    dashscope_key: str = field(default_factory=lambda: _env("DASHSCOPE_KEY"))
    upstream_timeout_s: float = field(default_factory=lambda: float(_env("UPSTREAM_TIMEOUT_S", "180")))
    # Chat requests share one provider account. Keep a bounded number at the provider and
    # queue the rest in the relay; retry only a refusal received before any answer starts.
    # Zero disables either guard for an operator whose upstream already queues for itself.
    chat_concurrency: int = field(default_factory=lambda: _int("CHAT_CONCURRENCY", 12))
    chat_retries: int = field(default_factory=lambda: _int("CHAT_RETRIES", 2))
    chat_retry_base_s: float = field(default_factory=lambda: float(_env("CHAT_RETRY_BASE_S", "0.5")))
    # 0.28: how long the per-request telemetry rows (`calls`: timings, how a request ended,
    # its shape — never its words) are kept for the console's live page and drill-downs.
    calls_keep_days: int = field(default_factory=lambda: _int("CALLS_KEEP_DAYS", 90))
    # how long the timelines' lines (`events`: sign-ins, devices joining, errors, refusals;
    # never content) are kept; the `account.deleted` lines stay, the statistics count them.
    # The ledger is the account's money and is never swept.
    events_keep_days: int = field(default_factory=lambda: _int("EVENTS_KEEP_DAYS", 365))
    # 0.29: the record (record.py) — every chat turn in full, with its pictures as files
    # under MEDIA_DIR (next to the database when unset). RECORD_TURNS=0 keeps none of it;
    # RECORD_KEEP_DAYS=0 keeps a turn until the person deletes it; past MEDIA_MAX_GB the
    # files least recently used go first and their turns keep a reference to nothing.
    # BLOB_MAX_BYTES caps one file a client puts up (PUT /v1/blobs: a clip, a picture).
    record_turns: bool = field(default_factory=lambda: _env("RECORD_TURNS", "1") in ("1", "true", "yes"))
    record_keep_days: int = field(default_factory=lambda: _int("RECORD_KEEP_DAYS", 0))
    media_dir: str = field(default_factory=lambda: _env("MEDIA_DIR", ""))
    media_max_gb: float = field(default_factory=lambda: float(_env("MEDIA_MAX_GB", "50")))
    blob_max_bytes: int = field(default_factory=lambda: _int("BLOB_MAX_BYTES", 32 * 1024 * 1024))
    # 0.30: what one account may put up — files referenced by its turns, profile and
    # uploads together (MEDIA_ACCOUNT_MAX_MB; 0 = no cap short of MEDIA_MAX_GB), and how
    # many own-key turns and files a minute (RECORD_UPLOADS_PER_MINUTE; 0 = no limit). A
    # device catching up after a day offline sends a few hundred turns; a script filling
    # the disk sends thousands. Past the store's cap nothing more is taken until the
    # hourly trim has run, whoever asks.
    media_account_max_mb: int = field(default_factory=lambda: _int("MEDIA_ACCOUNT_MAX_MB", 2048))
    record_uploads_per_minute: int = field(default_factory=lambda: _int("RECORD_UPLOADS_PER_MINUTE", 120))
    # Pictures: DashScope allows an account only a couple of image tasks at a time and
    # answers 429 past that, so the relay draws at most IMAGE_CONCURRENCY pictures at once
    # for everyone together (the rest queue) and, on a 429 or 5xx, tries again up to
    # IMAGE_RETRIES times with growing pauses before telling the app the provider is busy.
    image_concurrency: int = field(default_factory=lambda: _int("IMAGE_CONCURRENCY", 2))
    image_retries: int = field(default_factory=lambda: _int("IMAGE_RETRIES", 4))
    # JSON object merged into every chat request for fields the app did not set.
    # Qwen 3.x models think by default and a one-line answer can cost a
    # thousand reasoning tokens, so the shipped default turns that off; the app
    # can still ask for it explicitly.
    chat_defaults: dict = field(default_factory=lambda: json.loads(_env("CHAT_DEFAULTS", '{"enable_thinking": false}')))

    # The token grant, the older allowance. SIGNUP_TOKENS=0 (the default since
    # the money cap below took over) means no token ceiling: usage is still
    # metered and shown, nothing is refused for lack of tokens. DAILY_CAP_TOKENS=0
    # and PER_MINUTE_REQUESTS=0 likewise switch those two checks off.
    signup_tokens: int = field(default_factory=lambda: _int("SIGNUP_TOKENS", 0))
    daily_cap_tokens: int = field(default_factory=lambda: _int("DAILY_CAP_TOKENS", 0))
    per_minute_requests: int = field(default_factory=lambda: _int("PER_MINUTE_REQUESTS", 30))
    # The largest JSON body (a chat request with its pictures, a sync push, a profile). 16 MiB
    # since 0.20: a computer-use turn carries a few screenshots, and the apps now keep at most
    # four and scale them down, so a body that still passes this is a bug on their side.
    max_request_bytes: int = field(default_factory=lambda: _int("MAX_REQUEST_BYTES", 16 * 1024 * 1024))
    # Whose X-Forwarded-For to believe: the proxy in front (Caddy on the same box or network,
    # a tailnet). Comma-separated addresses or networks; empty = every loopback, private,
    # link-local and shared (100.64/10) address. A relay reached straight from the internet
    # then ignores the header, so a request cannot name its own address.
    trusted_proxies: str = field(default_factory=lambda: _env("TRUSTED_PROXIES"))
    # Requests under way for one account at the same time (0 = no cap). Each holds a
    # reservation against the allowance while it runs — a picture's or a clip's known price,
    # a chat's typical one — so several requests cannot each pass the check and together
    # overshoot it (service.py InFlight).
    max_in_flight: int = field(default_factory=lambda: _int("MAX_IN_FLIGHT", 4))

    # The hub (multi-device): one WebSocket frame may carry a file or a
    # screenshot, base64-encoded; uvicorn's own cap (--ws-max-size) must be at
    # least this. HUB_ENABLED=0 turns the hub and the console off.
    hub_enabled: bool = field(default_factory=lambda: _env("HUB_ENABLED", "1") not in ("0", "false", "no"))
    hub_frame_limit: int = field(default_factory=lambda: _int("HUB_FRAME_LIMIT", 16 * 1024 * 1024))

    # Money (0.5). Every account has one allowance for its lifetime, not a day:
    # ALLOWANCE_CNY yuan of the operator's provider bill (0 = no limit), counted
    # at the list prices above across chat, pictures and clips alike — a clip is
    # not counted apart, it just costs more. The pool grows by INVITE_BONUS_CNY
    # for each friend who signs up with the account's code — the friend's pool
    # grows by the same (0.9) — and by whatever the operator credits. The
    # members below (ALLOWED_IDENTIFIERS, or flagged by the operator) have no
    # limit. DAY_OFFSET_H only groups the operator's reports by local day
    # (8 = Beijing). USD_CNY is for display: the apps show both currencies.
    #
    # Since 0.15 the allowance, the invite bonus and SIGNUP_OPEN can also be set
    # from the operator's page while the relay runs (POST /v1/admin/settings);
    # a value set there is kept in the database and wins over the environment
    # until it is cleared — what is here is the starting point.
    allowance_cny: float = field(default_factory=lambda: float(_env("ALLOWANCE_CNY", "10")))
    invite_bonus_cny: float = field(default_factory=lambda: float(_env("INVITE_BONUS_CNY", "5")))
    # Minimum cumulative successful provider spend (in micro-yuan) by an invited account
    # before its invite bonus is settled; default 200 micro-yuan refuses single-line
    # scripted probes while settling normal chat turns.
    invite_settle_min_spent_uy: int = field(default_factory=lambda: _int("INVITE_SETTLE_MIN_SPENT_UY", 200))
    day_offset_h: int = field(default_factory=lambda: _int("DAY_OFFSET_H", 8))
    # Data controls (0.9): "Help improve nanoMuse's AI models" keeps the text of an
    # account's chat turns — what the person wrote and what the model answered, the
    # model's tool calls, never the system prompt, a tool's result or a picture — for
    # the community's own model. IMPROVE_DEFAULT is what an account *created from now
    # on* starts with (1 = on until the person turns it off under Settings → Data
    # controls; 0 = off until they turn it on). Accounts from before keep their own
    # setting either way. State the default in the relay's privacy policy.
    improve_default: bool = field(default_factory=lambda: _env("IMPROVE_DEFAULT", "0") in ("1", "true", "yes"))
    usd_cny: float = field(default_factory=lambda: float(_env("USD_CNY", "7.1")))
    # INVITE_URL is the link the apps offer to share; the code is appended.
    # OWN_KEY_DOCS is the guide the apps open when the allowance is used up and
    # the person wants to bring their own model key.
    invite_url: str = field(default_factory=lambda: _env("INVITE_URL", "https://nanomuse.cn/web/?invite="))
    own_key_docs: str = field(default_factory=lambda: _env("OWN_KEY_DOCS", "https://nanomuse.cn/own-key"))
    # OPENROUTER_URL is where someone outside mainland China gets a key (0.17): Alibaba
    # Cloud Bailian only signs up accounts from the mainland, so the "ways on" the relay
    # sends put OpenRouter first for everyone else (service.region).
    openrouter_url: str = field(default_factory=lambda: _env("OPENROUTER_URL", "https://openrouter.ai/keys"))
    # PRIVACY_URL is the policy the apps link from Data controls and the sign-in
    # pages — the one that states what this relay keeps and its default above.
    privacy_url: str = field(default_factory=lambda: _env("PRIVACY_URL", "https://nanomuse.cn/privacy/"))
    # REPO_URL is the project's repository, which the apps point to when they ask for a
    # star — at the first sign-in, when the allowance is used up, after the first task.
    repo_url: str = field(default_factory=lambda: _env("REPO_URL", "https://github.com/nano-muse/nanoMuse"))

    code_ttl_s: int = field(default_factory=lambda: _int("CODE_TTL_S", 600))
    code_per_identifier_10m: int = field(default_factory=lambda: _int("CODE_PER_IDENTIFIER_10M", 3))
    # Passwords are optional on top of the code: someone who set one may sign
    # in with it on a new device without waiting for a message. After this
    # many wrong tries in a row the password is locked for LOCKOUT_S seconds
    # (a code still works, and setting a new password clears the lock).
    password_min_len: int = field(default_factory=lambda: _int("PASSWORD_MIN_LEN", 8))
    password_max_attempts: int = field(default_factory=lambda: _int("PASSWORD_MAX_ATTEMPTS", 5))
    lockout_s: int = field(default_factory=lambda: _int("LOCKOUT_S", 900))
    # Wrong passwords from one network address across all accounts per hour; the
    # per-account lockout above does not stop a list of numbers tried once each.
    login_fail_per_ip_hour: int = field(default_factory=lambda: _int("LOGIN_FAIL_PER_IP_HOUR", 30))
    # How long after a code sign-in a password may be set without the old one
    # (the "forgot my password" path: sign in with a code, set a new one).
    password_reset_window_s: int = field(default_factory=lambda: _int("PASSWORD_RESET_WINDOW_S", 1800))
    # Members: phone numbers / e-mail addresses (comma-separated) that have no
    # daily cap — the operator and friends. Normalised like the identifiers
    # themselves, so "139 0000 1111" works. With SIGNUP_OPEN=0 the relay is
    # private and only members may sign in at all (the pre-release behaviour).
    allowed_identifiers: str = field(default_factory=lambda: _env("ALLOWED_IDENTIFIERS"))
    signup_open: bool = field(default_factory=lambda: _env("SIGNUP_OPEN", "1") not in ("0", "false", "no"))
    # A sign-in for an app store's reviewer, who cannot receive our codes: for the
    # e-mail addresses in REVIEW_ADDRESSES (comma-separated) a code request sends nothing and
    # answers as if it had, and /v1/auth/verify accepts exactly REVIEW_CODE (six digits) —
    # within the same code lifetime, attempt and rate limits as anyone's. The account is an
    # ordinary one, tagged `review` on the operator's page and left out of its sign-up counts.
    # Either value empty = off, nothing changes.
    review_addresses: str = field(default_factory=lambda: _env("REVIEW_ADDRESSES"))
    review_code: str = field(default_factory=lambda: _env("REVIEW_CODE"))
    code_per_ip_hour: int = field(default_factory=lambda: _int("CODE_PER_IP_HOUR", 10))
    code_max_attempts: int = field(default_factory=lambda: _int("CODE_MAX_ATTEMPTS", 5))
    # New accounts per e-mail domain per rolling 24 hours, for domains that are not a well
    # known mail provider (WELL_KNOWN_MAIL_DOMAINS) and not in SIGNUP_DOMAIN_ALLOW (comma
    # separated): past the limit a code request for a new address of that domain is answered
    # `429 domain_limited`; an existing account always gets its code. 0 = off. A catch-all
    # domain of one's own, or a bought list of mailboxes, is how a pool is farmed.
    # Domains in DEFAULT_SIGNUP_DOMAIN_BLOCK or SIGNUP_DOMAIN_BLOCK are refused for new
    # sign-ups right away with the same `429 domain_limited`.
    signup_per_domain_day: int = field(default_factory=lambda: _int("SIGNUP_PER_DOMAIN_DAY", 5))
    signup_domain_allow: str = field(default_factory=lambda: _env("SIGNUP_DOMAIN_ALLOW"))
    signup_domain_block: str = field(default_factory=lambda: _env("SIGNUP_DOMAIN_BLOCK"))
    # One phone/e-mail = one grant; a second device signing in with the same
    # identifier shares the account and gets a second key, not a second grant.

    sender: str = field(default_factory=lambda: _env("CODE_SENDER", "log"))  # log | smtp | aliyun | both
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: _int("SMTP_PORT", 465))
    smtp_user: str = field(default_factory=lambda: _env("SMTP_USER"))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD"))
    smtp_from: str = field(default_factory=lambda: _env("SMTP_FROM"))
    aliyun_access_key_id: str = field(default_factory=lambda: _env("ALIYUN_ACCESS_KEY_ID"))
    aliyun_access_key_secret: str = field(default_factory=lambda: _env("ALIYUN_ACCESS_KEY_SECRET"))
    aliyun_sms_sign: str = field(default_factory=lambda: _env("ALIYUN_SMS_SIGN"))
    aliyun_sms_template: str = field(default_factory=lambda: _env("ALIYUN_SMS_TEMPLATE"))
    # dypns = 号码认证服务 SendSmsVerifyCode (default), dysms = 短信服务 SendSms
    aliyun_sms_api: str = field(default_factory=lambda: _env("ALIYUN_SMS_API", "dypns"))

    models: tuple[ModelSpec, ...] = field(default_factory=_models_from_env)
    # Self-hosted relays may deliberately keep the historical native media proxy. The
    # project-hosted default is off; with it off every media route returns an actionable
    # retirement error before an upstream request or charge.
    media_enabled: bool = field(default_factory=lambda: _env("CLOUD_MEDIA_ENABLED", "0") in ("1", "true", "yes"))
    # Old clients can keep a saved model id while an operator changes provider.
    # This JSON object is merged over the aliases built into the relay.
    model_aliases: dict[str, str] = field(default_factory=_model_aliases_from_env)
    # Members (the operator's list, or flagged on the account) may ask for any model the
    # provider has under the operator's key, by its id, as long as it is used for what it
    # is — a chat model for chat, an image model for pictures, a video model for clips.
    # The menu stays the menu for everyone else. Off with CLOUD_ANY_MODEL_MEMBERS=0.
    any_model_members: bool = field(default_factory=lambda: _env("CLOUD_ANY_MODEL_MEMBERS", "1") not in ("0", "false", "no"))
    # 0.10: the models under the operator's key, read from the provider's own /models and
    # listed for members after the menu (catalog.py), so they pick instead of typing.
    # CLOUD_CATALOG=0 switches it off; the list is re-read every CLOUD_CATALOG_TTL_S.
    catalog_enabled: bool = field(default_factory=lambda: _env("CLOUD_CATALOG", "1") not in ("0", "false", "no"))
    catalog_ttl_s: int = field(default_factory=lambda: int(_env("CLOUD_CATALOG_TTL_S", "3600")))
    # 0.11: each chat model on the list is asked once whether it answers and whether it
    # reads a picture (two one-word requests on the operator's key, in the background);
    # the answers stand for CLOUD_CATALOG_PROBE_TTL_S. CLOUD_CATALOG_PROBE=0: names only.
    catalog_probe: bool = field(default_factory=lambda: _env("CLOUD_CATALOG_PROBE", "1") not in ("0", "false", "no"))
    catalog_probe_ttl_s: int = field(default_factory=lambda: int(_env("CLOUD_CATALOG_PROBE_TTL_S", str(7 * 86400))))
    # -- the operator's page, beyond the relay's own numbers ------------------------------
    # the site's traffic database (demo/showcase/mirror/traffic.py), mounted read-only into
    # the container; empty = the "visits and downloads" panel says so and shows nothing
    traffic_db: str = field(default_factory=lambda: _env("TRAFFIC_DB"))
    # nanoMuse Web's gateway on the same docker network (http://gateway:8000/api/web/info):
    # how many kept accounts and running sessions; empty = not asked
    web_info_url: str = field(default_factory=lambda: _env("WEB_INFO_URL"))
    # the showcase's visitors (demo.nanomuse.dev/api/demo/admin, its SHOWCASE_ADMIN_TOKEN):
    # who tried the phone in the browser from where and with what, every demo and what it
    # used — shown on the admin page and in the account drawer; empty = not asked
    web_admin_url: str = field(default_factory=lambda: _env("WEB_ADMIN_URL"))
    web_admin_token: str = field(default_factory=lambda: _env("WEB_ADMIN_TOKEN"))
    # 0.11: where an address is — country, province, city — from ip2region's database
    # (Apache-2.0), fetched once into the data directory and read in memory; no third party
    # is asked. CLOUD_GEOIP=0 switches it off; CLOUD_GEOIP_DB names the file (default: next
    # to the database); CLOUD_GEOIP_URL where to fetch it; CLOUD_GEOIP_V6_URL adds the IPv6
    # file (37 MB) for relays reached over IPv6 — empty = IPv4 only.
    geoip_enabled: bool = field(default_factory=lambda: _env("CLOUD_GEOIP", "1") not in ("0", "false", "no"))
    geoip_db: str = field(default_factory=lambda: _env("CLOUD_GEOIP_DB"))
    geoip_url: str = field(
        default_factory=lambda: _env(
            "CLOUD_GEOIP_URL", "https://raw.githubusercontent.com/lionsoul2014/ip2region/master/data/ip2region_v4.xdb"
        )
    )
    geoip_v6_url: str = field(default_factory=lambda: _env("CLOUD_GEOIP_V6_URL"))
    # 0.22: the GitHub collector (github_stats.py) — a reading every six hours (the UTC day's
    # row keeps the latest), and on demand from the operator's page: stars, forks, watchers
    # and every release asset's download count. GITHUB_REPO names the repository (owner/name; derived from REPO_URL when
    # empty); GITHUB_TOKEN is optional (60 requests an hour without one, which is plenty);
    # GITHUB_COLLECT=0 turns the collector off (tests, a relay with no network).
    github_repo: str = field(default_factory=lambda: _env("GITHUB_REPO"))
    github_token: str = field(default_factory=lambda: _env("GITHUB_TOKEN"))
    github_collect: bool = field(default_factory=lambda: _env("GITHUB_COLLECT", "1") not in ("0", "false", "no"))
    github_api: str = field(default_factory=lambda: _env("GITHUB_API", "https://api.github.com"))
    # 0.22: where a threshold rule's *notify* goes (controls.py), through the SMTP settings
    # above; empty = the rule writes its audit line and the log says there was nobody to tell.
    admin_email: str = field(default_factory=lambda: _env("ADMIN_EMAIL"))

    @property
    def trusted_proxy_list(self) -> list[str]:
        """TRUSTED_PROXIES as a list, else the non-global networks (client.py agrees)."""
        given = [x.strip() for x in self.trusted_proxies.split(",") if x.strip()]
        return given or list(NON_GLOBAL_NETWORKS)

    @property
    def signup_domain_allow_set(self) -> frozenset[str]:
        """The domains never under the per-domain sign-up limit: the well known providers
        plus SIGNUP_DOMAIN_ALLOW, lower-cased, without a leading ``@``."""
        given = {x.strip().lower().lstrip("@") for x in self.signup_domain_allow.split(",") if x.strip()}
        return WELL_KNOWN_MAIL_DOMAINS | frozenset(given)

    @property
    def signup_domain_block_set(self) -> frozenset[str]:
        """Disposable mail domains blocked from opening new accounts: the default list plus
        SIGNUP_DOMAIN_BLOCK, minus anything explicitly listed in SIGNUP_DOMAIN_ALLOW."""
        explicit_allow = {x.strip().lower().lstrip("@") for x in self.signup_domain_allow.split(",") if x.strip()}
        given = {x.strip().lower().lstrip("@") for x in self.signup_domain_block.split(",") if x.strip()}
        return (frozenset(DEFAULT_SIGNUP_DOMAIN_BLOCK) | frozenset(given)) - explicit_allow

    @property
    def github_repo_path(self) -> str:
        """`owner/name`: GITHUB_REPO, else read off REPO_URL (https://github.com/owner/name)."""
        if self.github_repo:
            return self.github_repo.strip().strip("/")
        m = re.match(r"^https?://github\.com/([^/\s]+)/([^/\s#?]+)", self.repo_url.strip())
        return f"{m.group(1)}/{m.group(2).removesuffix('.git')}" if m else ""

    @property
    def geoip_path(self) -> str:
        """The IPv4 file: CLOUD_GEOIP_DB, else ``ip2region_v4.xdb`` beside the database
        (nothing for an in-memory database, so tests ask no network)."""
        if not self.geoip_enabled:
            return ""
        if self.geoip_db:
            return self.geoip_db
        if self.database == ":memory:" or self.database.startswith("file:"):
            return ""
        import os.path

        return os.path.join(os.path.dirname(self.database) or ".", "ip2region_v4.xdb")

    def model(self, model_id: str) -> ModelSpec | None:
        for m in self.models:
            if m.id == model_id:
                return m
        # Phones from before 0.4 still ask for the model the menu used to carry;
        # operators may also keep saved ids working after changing provider.
        alias = self.model_aliases.get(model_id)
        if alias and alias != model_id:
            return next((m for m in self.models if m.id == alias), None)
        return None

    def unlisted_model(self, model_id: str, kind: str) -> ModelSpec | None:
        """A model the menu does not carry, asked for by name for `kind` — what a
        member may do (any_model_members). Its id goes upstream as it is; the ledger
        prices it as the dearest menu model of its kind (`priced_as`), so the
        operator's page errs on the high side rather than showing nothing. None when
        the id is not shaped like one, or the kind is unknown."""
        model_id = model_id.strip()
        if kind not in _UNLISTED_MODALITIES or not MODEL_ID_RE.match(model_id):
            return None
        inputs, outputs = _UNLISTED_MODALITIES[kind]
        spec = ModelSpec(
            id=model_id,
            name=model_id,
            upstream=model_id,
            kind=kind,
            input_modalities=inputs,
            output_modalities=outputs,
            listed=False,
        )
        dearest = max(
            (m for m in self.models if m.kind == kind),
            key=lambda m: (m.price_in + m.price_out, m.price_image + m.price_image_2k, m.price_second),
            default=None,
        )
        if dearest is None:
            return spec
        return replace(
            spec,
            priced_as=dearest.id,
            in_mult=dearest.in_mult,
            out_mult=dearest.out_mult,
            per_image=dearest.per_image,
            per_clip=dearest.per_clip,
            # the dearest's day prices and surcharges, none of its discounts (idle hours,
            # cached input): an unknown model is priced high, not low
            price_in=dearest.price_in,
            price_out=dearest.price_out,
            price_image=dearest.price_image,
            price_image_2k=dearest.price_image_2k,
            price_image_in=dearest.price_image_in,
            price_second=dearest.price_second,
            price_second_res=dearest.price_second_res,
            clip_seconds=dearest.clip_seconds,
        )

    @property
    def unlimited(self) -> bool:
        return self.signup_tokens <= 0

    def day_start(self, t: int) -> int:
        """The start (as a UNIX time) of the local day `t` falls in."""
        off = self.day_offset_h * 3600
        return t - ((t + off) % 86400)

    def uy_to_cny(self, uy: int) -> float:
        return round(uy / 1_000_000, 4)

    @staticmethod
    def cny_to_uy(cny: float) -> int:
        return round(cny * 1_000_000)

    @property
    def allowance_uy(self) -> int:
        return self.cny_to_uy(self.allowance_cny)

    def cny_to_usd(self, cny: float) -> float:
        return round(cny / self.usd_cny, 4) if self.usd_cny > 0 else 0.0

    @property
    def dev_mode(self) -> bool:
        return not self.secret

    @property
    def hmac_key(self) -> bytes:
        return (self.secret or "nanomuse-cloud-dev-not-secret").encode()

    @property
    def identifier_key(self) -> bytes:
        """32 bytes for AES-GCM over the stored phone numbers / addresses,
        derived from the same secret so one value keeps the whole database."""
        return hashlib.sha256(b"nanomuse-cloud/identifier:" + self.hmac_key).digest()
