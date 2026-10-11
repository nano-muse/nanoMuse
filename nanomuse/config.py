"""Configuration loading.

Search order for the TOML config file:

1. explicit path (``--config`` / :func:`load_settings(path)`)
2. ``$NANOMUSE_CONFIG``
3. ``./config/config.toml``
4. ``~/.nanomuse/config.toml``

String values may reference environment variables with ``${VAR}`` or
``${VAR:-default}`` so that secrets never have to live in the file itself.
A handful of ``NANOMUSE_*`` environment variables override the most common
settings (see :func:`_apply_env_overrides`). Whatever was changed from the app
(``<data_dir>/app-settings.json``: model, connectors, MCP servers) is layered on
top; secrets it refers to live in the vault as ``{{vault:NAME}}``.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from nanomuse.logger import logger
from nanomuse.schema import RiskLevel

DEFAULT_DATA_DIR = Path.home() / ".nanomuse"
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


# ----------------------------------------------------------------------------- models
#: the wire protocols the runtime speaks, as ``provider`` values; besides these, ``provider``
#: may name a catalogue entry (``nanomuse/llm/providers.json``: ``bailian``, ``openai``,
#: ``openrouter``, …), which fills in the protocol and the endpoint, or ``chatgpt`` — the
#: ChatGPT sign-in (``nanomuse chatgpt login``), which needs no key and no URL
PROTOCOLS: tuple[str, ...] = ("openai", "openai_responses")
CHATGPT_PROVIDER = "chatgpt"


def check_provider(value: str) -> str:
    from nanomuse.llm import catalogue

    v = str(value or "").strip()
    if not v:
        return "openai"
    if v in PROTOCOLS or v == CHATGPT_PROVIDER:
        return v
    entry = catalogue.load().get(v)
    if entry is None:
        choices = ", ".join((*PROTOCOLS, CHATGPT_PROVIDER, *catalogue.load().ids()))
        raise ValueError(f"unknown provider {v!r}; one of: {choices}")
    if catalogue.protocol_provider(entry.protocol) is None:
        raise ValueError(
            f"provider {v!r} speaks {entry.protocol}, which the runtime does not; "
            "OpenRouter carries the same models in the OpenAI shape"
        )
    return v


def resolve_provider(provider: str, base_url: str | None) -> tuple[str, str | None]:
    """What a ``provider`` setting means on the wire: the protocol (``openai`` /
    ``openai_responses`` / ``chatgpt``) and the base URL — the catalogue's when the slot
    names an entry and leaves ``base_url`` empty."""
    if provider in PROTOCOLS or provider == CHATGPT_PROVIDER:
        return provider, base_url
    from nanomuse.llm import catalogue

    entry = catalogue.load().get(provider)
    if entry is None:
        return "openai", base_url
    protocol = catalogue.protocol_provider(entry.protocol) or "openai"
    return protocol, (base_url or entry.base_url or None)


class LLMSettings(BaseModel):
    provider: str = "openai"
    model: str = "deepseek-flash"
    base_url: str | None = "https://api.deepseek.com"
    api_key: str = ""
    max_tokens: int = 4096
    temperature: float = 0.3
    timeout: float = 180.0
    max_retries: int = 5
    stream: bool = True
    # "auto":   the provider's function-calling API; if the endpoint rejects the `tools`
    #           field (Ollama for a model without a tool template, vLLM without a tool
    #           parser) switch to prompt mode for the rest of the run.
    # "native": always the function-calling API.
    # "prompt": describe tools in the prompt and parse <tool_call> blocks — works with
    #           any chat model, including endpoints that silently ignore `tools`.
    tool_mode: Literal["auto", "native", "prompt"] = "auto"
    # Pictures the user attaches in chat go to the model as images.
    # "auto": send them; if the endpoint rejects image content (DeepSeek, most text-only
    #         models) send the text only from then on and tell the user once.
    # "on":   always send them (the call fails when the model cannot take images).
    # "off":  never — the model gets the file names and can read text files with `files`.
    vision: Literal["auto", "on", "off"] = "auto"
    # Send `reasoning_content` back with assistant messages (DeepSeek thinking-mode
    # tool calling wants this on some endpoints).
    pass_reasoning: bool = False
    # The models that draw and animate the agent's face (the avatar studio), on the same
    # host and key as the chat model. Empty: the relay's image model when the account is the
    # provider, qwen-image-3.0 on Alibaba Cloud Model Studio, none elsewhere.
    image_model: str = ""
    video_model: str = ""
    # Where the asynchronous video API (`/api/v1/uploads`, `…/video-synthesis`, `/api/v1/tasks`)
    # lives when it is not at the chat model's host — a relaying host, such as the showcase
    # gateway, tells its runtimes this way. Empty: the chat host's root, on hosts that have it.
    video_base_url: str = ""
    # An HTTP(S) or SOCKS proxy for this slot's requests only (`http://host:port`,
    # `http://user:pass@host:port`, `socks5://host:port`), for a provider that this machine's
    # network cannot reach directly. Empty: the environment's HTTPS_PROXY / NO_PROXY apply as
    # usual. Honoured by the ChatGPT sign-in (`provider = "chatgpt"`): the Codex endpoint, the
    # token refresh and the usage check all go through it; never nanoMuse Cloud.
    proxy: str = ""
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, v: str) -> str:
        return check_provider(v)

    @field_validator("base_url")
    @classmethod
    def _strip_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else v

    @model_validator(mode="after")
    def _provider_defaults(self) -> LLMSettings:
        """The DeepSeek defaults for ``model`` and ``base_url`` belong to the plain
        ``openai`` protocol; a slot that names the ChatGPT sign-in or a catalogue entry and
        leaves them out gets that provider's own."""
        if self.provider in PROTOCOLS:
            return self
        if "base_url" not in self.model_fields_set:
            self.base_url = None
        if "model" not in self.model_fields_set:
            if self.provider == CHATGPT_PROVIDER:
                self.model = ""
            else:
                from nanomuse.llm import catalogue

                entry = catalogue.load().get(self.provider)
                self.model = (entry.defaults.get("chat") if entry else "") or ""
        return self

    @property
    def protocol(self) -> str:
        """``openai`` / ``openai_responses`` / ``chatgpt`` — what ``provider`` speaks."""
        return resolve_provider(self.provider, self.base_url)[0]

    @property
    def endpoint(self) -> str | None:
        """``base_url``, or the catalogue entry's when ``provider`` names one."""
        return resolve_provider(self.provider, self.base_url)[1]


class MediaSettings(BaseModel):
    """One of the ``[image]`` / ``[video]`` slots: where pictures or clips come from when it
    is not the chat model's host. ``provider`` is a catalogue id (``bailian``, ``openai``,
    ``gemini``, …) or empty; ``base_url`` fills in from the catalogue when empty; ``api_key``
    falls back to the chat model's key when the host is the same. All empty (the default):
    pictures and clips come from the chat model's host as before — the account's model, or
    Alibaba Cloud Model Studio's — and ``[llm] image_model`` / ``video_model`` still work."""

    provider: str = ""
    model: str = ""
    base_url: str | None = None
    api_key: str = ""

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, v: str) -> str:
        return check_provider(v) if str(v or "").strip() else ""

    @field_validator("base_url")
    @classmethod
    def _strip_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else v

    @property
    def configured(self) -> bool:
        return bool(self.provider or self.model or self.base_url)

    @property
    def endpoint(self) -> str | None:
        """``base_url``; or the catalogue's for ``provider`` (the plain protocol names
        ``openai`` / ``openai_responses`` mean OpenAI's own endpoint here)."""
        if self.base_url or not self.provider:
            return self.base_url
        from nanomuse.llm import catalogue

        entry = catalogue.load().get("openai" if self.provider in PROTOCOLS else self.provider)
        return (entry.base_url or None) if entry else None


class AgentSettings(BaseModel):
    name: str = "nanoMuse"
    max_steps: int = 30
    # Where the agent's files live. A relative path is relative to the current directory, which is
    # what a terminal user expects. When nothing is configured, Settings resolves it: a `workspace/`
    # in the current directory when there is one, otherwise `<data_dir>/workspace` — so a runtime
    # started from a read-only place (the desktop shell from /Applications or Program Files, whose
    # working directory may even be /) never tries to create a folder where it cannot.
    workspace: Path = Path("./workspace")
    # Directories outside the workspace the files tool may read and write (e.g. "~/Documents").
    extra_roots: list[Path] = Field(default_factory=list)
    # "auto" → answer in the user's language; or force e.g. "zh" / "en".
    language: str = "auto"
    max_context_messages: int = 80
    # How many of the newest image-bearing messages keep their pictures in a model request.
    # A computer- or phone-hands session adds a screenshot or two per step, and the whole
    # conversation goes up again on every step: a dozen 4K screenshots passed the relay's
    # body limit (0.1.37, 413 too_large). Older ones are replaced by a short note so the
    # model still knows a screenshot was there. 0 = keep every picture.
    max_context_images: int = 4
    show_thinking: bool = False
    # Optional free-text profile injected into the system prompt.
    user_profile: str = ""
    # Extra instructions appended to the system prompt.
    instructions: str = ""


class SentinelRule(BaseModel):
    tool: str = "*"
    # argument name -> glob pattern matched against str(value)
    match: dict[str, str] = Field(default_factory=dict)
    action: Literal["allow", "ask", "deny"] = "ask"
    reason: str = ""


class SentinelSettings(BaseModel):
    # ask    : safe/moderate run freely, sensitive actions need approval (default)
    # strict : moderate *and* sensitive actions need approval
    # auto   : approve everything except explicit deny rules (unattended runs / CI)
    mode: Literal["ask", "strict", "auto"] = "ask"
    always_ask_tools: list[str] = Field(default_factory=lambda: ["send_email", "shell"])
    always_allow_tools: list[str] = Field(default_factory=list)
    deny_tools: list[str] = Field(default_factory=list)
    # Domains the agent may reach *without* approval even after it has read private
    # data (mirrors Muse's "short list of pre-approved destinations").
    egress_allowlist: list[str] = Field(
        default_factory=lambda: [
            "duckduckgo.com",
            "*.duckduckgo.com",
            "wikipedia.org",
            "*.wikipedia.org",
            "github.com",
            "*.github.com",
            "*.githubusercontent.com",
            "pypi.org",
            "*.pypi.org",
        ]
    )
    rules: list[SentinelRule] = Field(default_factory=list)
    audit_file: Path | None = None
    # Enable taint tracking: once the agent has read private data, network egress to
    # non-allowlisted destinations requires approval.
    taint_tracking: bool = True


class MemorySettings(BaseModel):
    enabled: bool = True
    max_inject: int = 20
    # Recall by meaning. Memories are embedded once and a message finds the ones that mean
    # the same thing, in any language ("写邮件给房东" finds "the landlord is Bob Li"); the
    # keyword recall stays and the two rankings are fused.
    #   auto: use the endpoint's /embeddings when it has one (OpenAI, Ollama, most gateways;
    #         DeepSeek has none) and fall back to keyword recall when it does not
    #   on:   insist — recall stays by keyword when the call fails, and `doctor` says so
    #   off:  keyword recall only
    embeddings: Literal["auto", "on", "off"] = "auto"
    # Empty → a default for the endpoint: text-embedding-3-small on OpenAI and most
    # gateways, qwen3-embedding:0.6b on Ollama.
    embedding_model: str = ""
    # Empty → the model's endpoint and key (llm.base_url / llm.api_key). Set these to use a
    # different service for embeddings than for chat — Ollama next to DeepSeek, say.
    embedding_base_url: str = ""
    embedding_api_key: str = ""

    @field_validator("embedding_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")


class EmailSettings(BaseModel):
    enabled: bool = False
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_starttls: bool = True
    # Values may be vault placeholders such as "{{vault:EMAIL_PASSWORD}}" — the model
    # never sees them; the Sentinel resolves them right before the connector runs.
    address: str = "{{vault:EMAIL_ADDRESS}}"
    password: str = "{{vault:EMAIL_PASSWORD}}"
    # Strip one-time passcodes / password-reset links before the model reads a mail.
    scrub_secrets: bool = True


class CalendarFeedSettings(BaseModel):
    name: str
    # A private .ics link (Google, Outlook, iCloud, Fastmail, Nextcloud all have one) or a
    # local file. The link is usually the secret, so "{{vault:CALENDAR_WORK}}" works here.
    url: str


class CalendarSettings(BaseModel):
    enabled: bool = False
    feeds: list[CalendarFeedSettings] = Field(default_factory=list)
    refresh_minutes: int = 30
    # Working hours, for "when am I free" — local time.
    day_start: str = "09:00"
    day_end: str = "18:00"


class ContactSourceSettings(BaseModel):
    """A ``.vcf`` export or link: Google Contacts, iCloud, Outlook, Nextcloud … all export one."""

    name: str
    # a path, or a URL — a "{{vault:NAME}}" placeholder when the link is a secret
    url: str


class ContactsSettings(BaseModel):
    # On by default: even without a source the agent keeps its own book of the people
    # you tell it about ("Alice's address is …"), in <data_dir>/contacts.vcf.
    enabled: bool = True
    sources: list[ContactSourceSettings] = Field(default_factory=list)


class SearchSettings(BaseModel):
    """Who answers ``web_search``. DuckDuckGo needs nothing and is the default; Brave and
    Tavily want a key, SearXNG wants the URL of an instance. A failed search falls back
    to DuckDuckGo once, with a note, so a lapsed key does not stop a task."""

    provider: Literal["duckduckgo", "brave", "tavily", "searxng"] = "duckduckgo"
    # Brave / Tavily. May be a vault placeholder — the app stores it as {{vault:SEARCH_API_KEY}}.
    api_key: str = ""
    # SearXNG: your instance, e.g. "http://127.0.0.1:8080".
    base_url: str = ""
    # False: a failed search fails, instead of going to DuckDuckGo's host as well.
    fallback: bool = True


class ConnectorSettings(BaseModel):
    email: EmailSettings = Field(default_factory=EmailSettings)
    calendar: CalendarSettings = Field(default_factory=CalendarSettings)
    contacts: ContactsSettings = Field(default_factory=ContactsSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)


class SkillsSettings(BaseModel):
    """Skills: recipes for jobs, as ``SKILL.md`` folders (the Agent Skills format)."""

    enabled: bool = True
    # Where your own skills live; one folder per skill with a SKILL.md inside. Empty →
    # <data_dir>/skills. A skill here with the same name as a built-in one replaces it.
    dir: Path | None = None
    # Built-in skills to leave out (by name).
    disabled: list[str] = Field(default_factory=list)

    @field_validator("dir", mode="before")
    @classmethod
    def _empty_is_unset(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v


class SandboxSettings(BaseModel):
    """Each ``shell`` / ``python_execute`` call in its own bubblewrap namespace (Linux)."""

    # "auto": bubblewrap when it is installed and works here; "bwrap": insist (a startup
    # error otherwise); "off": commands run unboxed, with the scrubbed environment only.
    mode: Literal["auto", "bwrap", "off"] = "auto"
    # Directories from outside the box that commands may use — the home directory as a
    # whole stays out. `share_read_only` for the programs (a CLI under ~/.nvm), `share`
    # for state a tool must also write (its login, a token it refreshes). Both are bound
    # where they are and, when under the home directory, at the same place under the
    # box's own home, so a tool that looks in $HOME finds them.
    share: list[Path] = Field(default_factory=list)
    share_read_only: list[Path] = Field(default_factory=list)


class TriggerSettings(BaseModel):
    """Triggers start work from the world: new mail, an event about to start, a webhook."""

    # How often the inbox is looked at while a mail trigger is active.
    mail_poll_minutes: int = 5
    # Deliveries to one webhook closer together than this are refused (HTTP 429).
    hook_min_seconds: int = 10


class BrowserSettings(BaseModel):
    """The browser tool. On the phone (the app's local runtime) it is on by default and uses
    the app's own WebView; elsewhere it needs Playwright and is off until turned on."""

    enabled: bool = False
    headless: bool = True
    timeout_ms: int = 30_000
    # "auto": Playwright when installed, else the phone's WebView; or "playwright" / "device"
    backend: Literal["auto", "playwright", "device"] = "auto"
    # the starting user agent + viewport: "desktop", "mobile", or "" for the backend's own
    profile: Literal["", "desktop", "mobile"] = ""


class GUISettings(BaseModel):
    """Operating the apps on the user's phone through their screens (the GUI agent).

    Off by default. When on, and a phone (the Android app with its accessibility service,
    or the MobileGym module) is connected, the agent gets the ``phone_screen``,
    ``phone_act`` and ``phone_task`` tools. ``phone_task`` runs a step loop with its own
    model — a smaller, faster one that takes images is the usual choice (``model``); when
    left empty the main model does it. ``base_url`` / ``api_key`` default to the main
    model's, so one provider (e.g. 阿里云百炼) can serve both.
    """

    enabled: bool = False
    provider: str = "openai"
    model: str = ""
    base_url: str | None = None
    api_key: str = ""

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, v: str) -> str:
        return check_provider(v)

    @property
    def endpoint(self) -> str | None:
        """``base_url``, or the catalogue entry's when ``provider`` names one and ``model``
        is set (an unset model means the main model's settings do the hands)."""
        if not self.model:
            return self.base_url
        return resolve_provider(self.provider, self.base_url)[1]

    # Steps one ``phone_task`` may take on the screen before it has to report back;
    # 0 (the default) is no cap — the task ends when it is done, asks, or is stopped.
    max_steps: int = 0
    # How long to wait for the phone to answer one request (screen or action).
    device_timeout_s: float = 20.0
    # How long a running task waits for a phone whose connection dropped to come back
    # (the Android app and the phone module reconnect within seconds; a page in a browser
    # that was switched away may take longer) before the task is given up. 0 = not at all.
    reconnect_grace_s: float = 30.0
    # Words on a screen (or a target element) that make an action *sensitive*: paying,
    # transferring money, sending, deleting, placing an order. Approval is asked every
    # time; no standing grant covers them. Kept specific on purpose — "支付" alone would
    # match the app name 支付宝 — and an element that is an app's name never counts.
    sensitive_words: list[str] = Field(
        default_factory=lambda: [
            "确认支付",
            "立即支付",
            "确认付款",
            "立即付款",
            "付款",
            "转账",
            "确认订单",
            "提交订单",
            "立即购买",
            "确认下单",
            "发送",
            "删除",
            "注销",
            "解绑",
            "pay now",
            "confirm payment",
            "purchase",
            "transfer",
            "send",
            "delete",
            "confirm order",
            "place order",
        ]
    )


class MCPToolPolicy(BaseModel):
    """What the Sentinel assumes about one tool of an MCP server, when the server's own
    defaults are too coarse::

        [mcp.servers.tools.delete_file]
        risk = "sensitive"

    A field left out keeps the server's value.
    """

    risk: RiskLevel | None = None
    egress: bool | None = None
    reads_private_data: bool | None = None


class MCPServerSettings(BaseModel):
    name: str
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None  # Streamable-HTTP / SSE endpoint
    risk: RiskLevel = RiskLevel.MODERATE
    egress: bool = False
    reads_private_data: bool = False
    # per-tool overrides, by the tool's own name on the server
    tools: dict[str, MCPToolPolicy] = Field(default_factory=dict)


class MCPSettings(BaseModel):
    servers: list[MCPServerSettings] = Field(default_factory=list)


class HandsSettings(BaseModel):
    """Hands on *this* computer's screen — the GUI operator with the machine it runs on
    under it (``computer_screen``, ``computer_act``, ``computer_task``). Off by default;
    the switch is Settings → Hands in the app. The model, the step cap and the sensitive
    words are shared with ``[gui]`` — one vision model serves the phone and the computer.
    """

    enabled: bool = False
    # "auto": the desktop app's operator when it started this runtime, else pyautogui when
    # installed, else xdotool on X11; or "desktop" / "pyautogui" / "xdotool"
    backend: Literal["auto", "desktop", "pyautogui", "xdotool"] = "auto"
    # How the model gives points: "pixels" of the picture it was shown (Qwen2.5-VL and the
    # computer_use dialect), or "norm1000" — a 0–1000 grid over the picture (Qwen3-VL's
    # default, UI-TARS). Boxes ([x1, y1, x2, y2]) are taken either way; their centre counts.
    coords: Literal["pixels", "norm1000"] = "pixels"
    # Where the hands work: "screen" — the whole screen and the system mouse; "window" —
    # one application's window on macOS, events delivered to that process, the person's
    # cursor untouched (nanomuse.computer.mac_window); "auto" — window on macOS as soon as
    # a target application is known, screen everywhere else.
    mode: Literal["auto", "screen", "window"] = "auto"
    # Widest picture handed to the model (the screen itself is operated at full size).
    max_image_width: int = 1600
    # A pause after each action before the next screenshot, so the screen has settled.
    settle_s: float = 0.6


class CloudSettings(BaseModel):
    """nanoMuse Cloud: the relay the phone signs in to with a phone-number or e-mail code. The
    account key lives in the vault (``NANOMUSE_CLOUD_KEY``); ``base_url`` is the relay.
    Signed in, the relay can be the model provider and the hub is reachable."""

    base_url: str = "https://cloud.nanomuse.cn"
    # Sign-in is part of setting up: the first-run flow does not finish without
    # an account (with it, the relay can be the model and the devices meet).
    # Self-hosters who run without a relay set this to false.
    required: bool = True
    # The account's models as a source (the apps' *Use nanoMuse Cloud models* switch). Off,
    # the relay leaves the automatic order of the hands, pictures and clips, and the hub's
    # listing; the sign-in itself stays (sync, the devices). Only the explicit "use nanoMuse
    # Cloud this time" button reaches it then.
    models: bool = True
    # Conversations synced between the account's devices (docs/every-device.md): the text
    # of the chats on the relay, so every device shows the same ones. The person's switch
    # in Settings → Data controls is what counts once set; this is the default for it.
    sync: bool = True


class SyncSettings(BaseModel):
    """Conversation sync, what this device sends and takes (contract C9). The account-wide
    switch is ``[cloud] sync``; these are per device."""

    # Off: only the main conversation is pushed and pulled (``scope=main``); side chats stay
    # on the device that wrote them — they are often device-bound work, a run on this
    # computer's screen, and most people do not want every one of them on every device.
    # On: this device's side chats go to the account and the other devices' come here.
    # *Settings → Data controls → Also sync side chats*; the person's switch, once set, is
    # kept in ``sync.json`` and this is only its default.
    side_chats: bool = False


class HubSettings(BaseModel):
    """The hub: this computer as one of the account's devices (see docs/hub.md).

    ``enabled`` joins the hub whenever the Cloud account is signed in. ``remote_control``
    off answers other devices with ``info`` and nothing else. ``name`` is what the other
    devices call this one (empty: the host name). ``device_id`` is per installation and
    normally left to the app.
    """

    enabled: bool = True
    remote_control: bool = True
    name: str = ""
    device_id: str = ""


class ServerSettings(BaseModel):
    """``nanomuse serve`` — the always-on agent behind the mobile-first web app."""

    host: str = "127.0.0.1"  # use 0.0.0.0 to reach it from your phone on the same network
    port: int = 8787
    # Require an access token (printed with a QR code on start). Never disable on a shared network.
    auth: bool = True
    token: str = ""  # empty → generated once and stored in <data_dir>/server_token
    # How long an approval card / question may wait for you before it is treated as "deny".
    approval_timeout: float = 3600.0
    # Extra origins allowed to call the API (only needed for the Vite dev server).
    cors_origins: list[str] = Field(default_factory=list)
    # Largest file the app may attach to a message (photos from a phone run 3–12 MB).
    max_upload_mb: int = 25
    # Ask GitHub Releases (at most every six hours) whether a newer nanoMuse is out, and say so
    # under Settings → About. Nothing is downloaded or reported. NANOMUSE_NO_UPDATE_CHECK=1 also turns it off.
    update_check: bool = True
    # How long the services (tools, MCP servers, the cloud account) may take before the
    # socket opens anyway; past it the app answers and /api/health names the step still running.
    start_grace: float = 4.0


class Settings(BaseModel):
    data_dir: Path = DEFAULT_DATA_DIR
    log_level: str = "INFO"
    llm: LLMSettings = Field(default_factory=LLMSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    sentinel: SentinelSettings = Field(default_factory=SentinelSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    connectors: ConnectorSettings = Field(default_factory=ConnectorSettings)
    triggers: TriggerSettings = Field(default_factory=TriggerSettings)
    skills: SkillsSettings = Field(default_factory=SkillsSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    gui: GUISettings = Field(default_factory=GUISettings)
    image: MediaSettings = Field(default_factory=MediaSettings)
    video: MediaSettings = Field(default_factory=MediaSettings)
    hands: HandsSettings = Field(default_factory=HandsSettings)
    cloud: CloudSettings = Field(default_factory=CloudSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)
    hub: HubSettings = Field(default_factory=HubSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    # Where the settings came from (informational).
    source: str | None = None

    @model_validator(mode="after")
    def _default_workspace(self) -> Settings:
        """No ``agent.workspace`` configured: ``./workspace`` when the current directory has one
        (the terminal user's convention), otherwise ``<data_dir>/workspace``."""
        if "workspace" not in self.agent.model_fields_set and not Path("./workspace").is_dir():
            self.agent.workspace = self.data_dir.expanduser() / "workspace"
        return self

    @property
    def audit_file(self) -> Path:
        return self.sentinel.audit_file or (self.data_dir / "audit.jsonl")

    @property
    def memory_db(self) -> Path:
        return self.data_dir / "memory.db"

    @property
    def goals_db(self) -> Path:
        return self.data_dir / "goals.db"

    @property
    def reminders_db(self) -> Path:
        return self.data_dir / "reminders.db"

    @property
    def triggers_db(self) -> Path:
        return self.data_dir / "triggers.db"

    @property
    def calendar_cache(self) -> Path:
        return self.data_dir / "calendar-cache.json"

    @property
    def contacts_file(self) -> Path:
        """The agent's own address book (the only contacts source it writes to)."""
        return self.data_dir / "contacts.vcf"

    @property
    def contacts_cache(self) -> Path:
        return self.data_dir / "contacts-cache.json"

    @property
    def contacts_dir(self) -> Path:
        """Where ``.vcf`` files uploaded in the app are kept."""
        return self.data_dir / "contacts"

    @property
    def skills_dir(self) -> Path:
        """Your own skills, one folder each."""
        return (self.skills.dir or (self.data_dir / "skills")).expanduser()

    @property
    def vault_file(self) -> Path:
        return self.data_dir / "vault.enc"

    @property
    def vault_key_file(self) -> Path:
        return self.data_dir / "vault.key"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.agent.workspace.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------- loading
def _expand_env(value: Any) -> Any:
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            var, default = m.group(1), m.group(2)
            return os.environ.get(var, default if default is not None else "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def find_config_file(explicit: str | Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"config file not found: {explicit}")
        return path
    if env_path := os.environ.get("NANOMUSE_CONFIG"):
        candidates.append(Path(env_path).expanduser())
    candidates.append(Path("config/config.toml"))
    candidates.append(DEFAULT_DATA_DIR / "config.toml")
    for path in candidates:
        if path.is_file():
            return path
    return None


def _provider_key_vars(base_url: str) -> tuple[str, ...]:
    """The environment variables that may stand in for a missing ``llm.api_key``.

    A key belongs to one provider: DeepSeek's key is only tried for ``api.deepseek.com``
    and OpenAI's only for ``api.openai.com``, so a config pointed at one provider never
    sends the other's key. Any other OpenAI-compatible host (a gateway, vLLM, OpenRouter)
    gets ``OPENAI_API_KEY`` alone — the convention such endpoints share.
    """
    host = (urlparse(base_url).hostname or "").lower()
    if host == "deepseek.com" or host.endswith(".deepseek.com"):
        return ("DEEPSEEK_API_KEY",)
    return ("OPENAI_API_KEY",)


def _apply_env_overrides(raw: dict[str, Any]) -> None:
    llm = raw.setdefault("llm", {})
    mapping = {
        "NANOMUSE_LLM_PROVIDER": "provider",
        "NANOMUSE_LLM_MODEL": "model",
        "NANOMUSE_LLM_BASE_URL": "base_url",
        "NANOMUSE_LLM_API_KEY": "api_key",
        "NANOMUSE_LLM_TOOL_MODE": "tool_mode",
        "NANOMUSE_LLM_VISION": "vision",
        # the avatar studio's models on the chat model's host (docs/avatar.md); a hosted
        # runtime is told them this way, the showcase gateway for one
        "NANOMUSE_LLM_IMAGE_MODEL": "image_model",
        "NANOMUSE_LLM_VIDEO_MODEL": "video_model",
        "NANOMUSE_LLM_VIDEO_BASE_URL": "video_base_url",
    }
    for env, key in mapping.items():
        if (val := os.environ.get(env)) not in (None, ""):
            llm[key] = val
    if not llm.get("api_key"):
        # the endpoint the slot will talk to: the catalogue's when `provider` names an entry
        provider = str(llm.get("provider") or LLMSettings.model_fields["provider"].default)
        base_url = llm.get("base_url") or None
        if provider in PROTOCOLS:
            base_url = base_url or LLMSettings.model_fields["base_url"].default
        else:
            base_url = resolve_provider(provider, base_url)[1]
        for env in _provider_key_vars(str(base_url or "")):
            if val := os.environ.get(env):
                llm["api_key"] = val
                break
    if val := os.environ.get("NANOMUSE_DATA_DIR"):
        raw["data_dir"] = val
    if val := os.environ.get("NANOMUSE_WORKSPACE"):
        raw.setdefault("agent", {})["workspace"] = val
    if val := os.environ.get("NANOMUSE_SENTINEL_MODE"):
        raw.setdefault("sentinel", {})["mode"] = val
    if val := os.environ.get("NANOMUSE_LOG_LEVEL"):
        raw["log_level"] = val
    for env, key in (
        ("NANOMUSE_SEARCH_PROVIDER", "provider"),
        ("NANOMUSE_SEARCH_API_KEY", "api_key"),
        ("NANOMUSE_SEARCH_BASE_URL", "base_url"),
    ):
        if val := os.environ.get(env):
            raw.setdefault("connectors", {}).setdefault("search", {})[key] = val
    server = raw.setdefault("server", {})
    if val := os.environ.get("NANOMUSE_SERVER_HOST"):
        server["host"] = val
    if val := os.environ.get("NANOMUSE_SERVER_PORT"):
        if val.strip().isdigit():
            server["port"] = int(val)
        else:
            logger.warning("NANOMUSE_SERVER_PORT={!r} is not a port number; ignored", val)
    if val := os.environ.get("NANOMUSE_SERVER_TOKEN"):
        server["token"] = val
    # turns the browser tool on (the browser Docker image sets it); it never turns it off, so a
    # mounted config.toml keeps the last word otherwise
    if os.environ.get("NANOMUSE_BROWSER_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"):
        raw.setdefault("browser", {})["enabled"] = True
    # on the phone the app's WebView is always there: the browser is on unless turned off
    if os.environ.get("NANOMUSE_DEVICE", "").strip().lower() == "android":
        raw.setdefault("browser", {}).setdefault("enabled", True)
    if val := os.environ.get("NANOMUSE_BROWSER_BACKEND"):
        raw.setdefault("browser", {})["backend"] = val
    # a hosted runtime (nanoMuse Web) is told where its relay is and what to call itself
    if val := os.environ.get("NANOMUSE_CLOUD_BASE_URL"):
        raw.setdefault("cloud", {})["base_url"] = val.rstrip("/")
    if val := os.environ.get("NANOMUSE_CLOUD_REQUIRED"):
        raw.setdefault("cloud", {})["required"] = val.strip().lower() in ("1", "true", "yes", "on")
    if val := os.environ.get("NANOMUSE_CLOUD_SYNC"):
        raw.setdefault("cloud", {})["sync"] = val.strip().lower() in ("1", "true", "yes", "on")
    if val := os.environ.get("NANOMUSE_HUB_NAME"):
        raw.setdefault("hub", {})["name"] = val[:60]
    gui = raw.setdefault("gui", {})
    if os.environ.get("NANOMUSE_GUI_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"):
        gui["enabled"] = True
    for env, key in (
        ("NANOMUSE_GUI_PROVIDER", "provider"),
        ("NANOMUSE_GUI_MODEL", "model"),
        ("NANOMUSE_GUI_BASE_URL", "base_url"),
        ("NANOMUSE_GUI_API_KEY", "api_key"),
    ):
        if (val := os.environ.get(env)) not in (None, ""):
            gui[key] = val
    # the picture and clip slots (docs/configuration.md)
    for slot in ("image", "video"):
        for key in ("provider", "model", "base_url", "api_key"):
            if (val := os.environ.get(f"NANOMUSE_{slot.upper()}_{key.upper()}")) not in (None, ""):
                raw.setdefault(slot, {})[key] = val


APP_SETTINGS_FILE = "app-settings.json"


def load_app_settings(data_dir: Path) -> dict[str, Any]:
    """Settings changed from the app (model, connectors, MCP servers, onboarding state).

    They live in ``<data_dir>/app-settings.json`` and are layered over ``config.toml`` so a
    phone-only setup works without ever editing a file. Secrets are not in here: the app
    stores them in the vault and this file only holds ``{{vault:NAME}}`` references.
    """
    path = data_dir / APP_SETTINGS_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_app_settings(data_dir: Path, data: dict[str, Any]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / APP_SETTINGS_FILE
    path.write_text(json.dumps({"version": 1, **data}, ensure_ascii=False, indent=1), "utf-8")
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover
        pass


def apply_app_settings(settings: Settings, data: dict[str, Any]) -> None:
    """Layer app-managed settings over ``settings`` in place."""
    if llm := data.get("llm"):
        for key in ("provider", "model", "base_url", "api_key", "tool_mode", "vision"):
            if key in llm and llm[key] not in (None, ""):
                if key == "provider":
                    try:
                        settings.llm.provider = check_provider(str(llm[key]))
                    except ValueError:
                        pass
                    continue
                if key == "tool_mode" and llm[key] not in ("auto", "native", "prompt"):
                    continue  # a value the app never writes; the config's stays
                if key == "vision" and llm[key] not in ("auto", "on", "off"):
                    continue
                setattr(settings.llm, key, llm[key])
        if settings.llm.provider == CHATGPT_PROVIDER:
            # the sign-in has no endpoint of its own; an empty model there means Codex's default
            if not llm.get("base_url"):
                settings.llm.base_url = None
            if "model" in llm and not llm.get("model"):
                from nanomuse.llm.chatgpt import DEFAULT_MODEL

                settings.llm.model = DEFAULT_MODEL
        for key in ("image_model", "video_model", "proxy"):
            # "" is meaningful here: back to the automatic choice (the models), no proxy
            if key in llm and llm[key] is not None:
                setattr(settings.llm, key, str(llm[key]).strip())
        if settings.llm.base_url:
            settings.llm.base_url = settings.llm.base_url.rstrip("/")
    if emb := data.get("embeddings"):
        m = settings.memory
        if emb.get("mode") in ("auto", "on", "off"):
            m.embeddings = emb["mode"]
        for key in ("model", "base_url", "api_key"):
            # "" is meaningful here: back to the default (the model's endpoint and key)
            if key in emb and emb[key] is not None:
                setattr(m, f"embedding_{key}", str(emb[key]).strip().rstrip("/"))
    if search := data.get("search"):
        web = settings.connectors.search
        if search.get("provider") in ("duckduckgo", "brave", "tavily", "searxng"):
            web.provider = search["provider"]
        for key in ("api_key", "base_url"):
            if key in search and search[key] is not None:
                setattr(web, key, str(search[key]).strip().rstrip("/"))
    if email := data.get("email"):
        for key in ("enabled", "imap_host", "imap_port", "smtp_host", "smtp_port", "smtp_starttls"):
            if key in email and email[key] is not None:
                setattr(settings.connectors.email, key, email[key])
    if calendar := data.get("calendar"):
        cal = settings.connectors.calendar
        if "enabled" in calendar and calendar["enabled"] is not None:
            cal.enabled = bool(calendar["enabled"])
        for key in ("refresh_minutes", "day_start", "day_end"):
            if calendar.get(key) not in (None, ""):
                setattr(cal, key, calendar[key])
        if isinstance(calendar.get("feeds"), list):
            feeds = []
            for raw_feed in calendar["feeds"]:
                try:
                    feeds.append(CalendarFeedSettings.model_validate(raw_feed))
                except ValueError:
                    continue
            # feeds added in the app come after the ones in config.toml; same name → app wins
            names = {f.name for f in feeds}
            cal.feeds = [f for f in cal.feeds if f.name not in names] + feeds
    if contacts := data.get("contacts"):
        book = settings.connectors.contacts
        if "enabled" in contacts and contacts["enabled"] is not None:
            book.enabled = bool(contacts["enabled"])
        if isinstance(contacts.get("sources"), list):
            sources = []
            for raw_source in contacts["sources"]:
                try:
                    sources.append(ContactSourceSettings.model_validate(raw_source))
                except ValueError:
                    continue
            names = {c.name for c in sources}
            book.sources = [c for c in book.sources if c.name not in names] + sources
    if skills := data.get("skills"):
        if isinstance(skills.get("disabled"), list):
            off = {str(n) for n in skills["disabled"]}
            settings.skills.disabled = sorted(set(settings.skills.disabled) | off)
    if browser := data.get("browser"):
        if "enabled" in browser:
            settings.browser.enabled = bool(browser["enabled"])
    if gui := data.get("gui"):
        if "enabled" in gui:
            settings.gui.enabled = bool(gui["enabled"])
        if gui.get("provider"):
            try:
                settings.gui.provider = check_provider(str(gui["provider"]))
            except ValueError:
                pass
        for key in ("model", "base_url", "api_key"):
            # "" is meaningful: back to the main model's endpoint and key
            if key in gui and gui[key] is not None:
                value = str(gui[key]).strip().rstrip("/")
                setattr(settings.gui, key, value if value or key != "base_url" else None)
    for slot in ("image", "video"):
        if media := data.get(slot):
            target: MediaSettings = getattr(settings, slot)
            for key in ("provider", "model", "base_url", "api_key"):
                # "" is meaningful: back to the chat model's host
                if key in media and media[key] is not None:
                    value = str(media[key]).strip().rstrip("/")
                    if key == "provider" and value:
                        try:
                            value = check_provider(value)
                        except ValueError:
                            continue
                    setattr(target, key, value if value or key != "base_url" else None)
    if hands := data.get("hands"):
        if "enabled" in hands:
            settings.hands.enabled = bool(hands["enabled"])
        if hands.get("backend") in ("auto", "desktop", "pyautogui", "xdotool"):
            settings.hands.backend = hands["backend"]
        if hands.get("coords") in ("pixels", "norm1000"):
            settings.hands.coords = hands["coords"]
    if cloud := data.get("cloud"):
        if cloud.get("base_url"):
            settings.cloud.base_url = str(cloud["base_url"]).strip().rstrip("/")
        if "required" in cloud and cloud["required"] is not None:
            settings.cloud.required = bool(cloud["required"])
        if "models" in cloud and cloud["models"] is not None:
            settings.cloud.models = bool(cloud["models"])
    if hub := data.get("hub"):
        for key in ("enabled", "remote_control"):
            if key in hub and hub[key] is not None:
                setattr(settings.hub, key, bool(hub[key]))
        for key in ("name", "device_id"):
            if hub.get(key):
                setattr(settings.hub, key, str(hub[key]).strip()[:60])
    for raw_server in (data.get("mcp") or {}).get("servers") or []:
        try:
            server = MCPServerSettings.model_validate(raw_server)
        except ValueError:
            continue
        settings.mcp.servers = [s for s in settings.mcp.servers if s.name != server.name]
        settings.mcp.servers.append(server)


# top-level tables of config.toml that are not settings fields: ``nanomuse.channels.store``
# reads ``[channels.<name>]`` itself (docs/channels.md)
_TABLES_READ_ELSEWHERE = frozenset({"channels"})


def _field_models(annotation: Any) -> tuple[type[BaseModel] | None, str]:
    """The settings model a field's values are validated as, and how it holds them: ``"one"``,
    ``"list"`` (``list[Model]``) or ``"dict"`` (``dict[str, Model]``). ``None`` for a scalar, a
    free-form ``dict`` or a list of scalars."""
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        for arg in get_args(annotation):
            if arg is not type(None):
                found = _field_models(arg)
                if found[0] is not None:
                    return found
        return None, "one"
    if origin is list:
        (item,) = get_args(annotation) or (Any,)
        return _field_models(item)[0], "list"
    if origin is dict:
        args = get_args(annotation)
        return (_field_models(args[1])[0] if len(args) == 2 else None), "dict"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, "one"
    return None, "one"


def unknown_keys(
    raw: Mapping[str, Any], model: type[BaseModel] = Settings, prefix: str = ""
) -> list[str]:
    """Dotted paths of the keys in ``raw`` that no settings model has a field for.

    Pydantic drops unknown keys without a word, so a misspelt ``[llm] modle`` or a key from
    another version is read as "not set" and the default applies. Free-form tables
    (``llm.extra_headers``, an MCP server's ``env``) take any key, and so do the top-level
    tables other modules read from the same file (``[channels.<name>]``).
    """
    fields = model.model_fields
    by_alias = {f.alias: name for name, f in fields.items() if isinstance(f.alias, str)}
    out: list[str] = []
    for key, value in raw.items():
        if not prefix and key in _TABLES_READ_ELSEWHERE:
            continue
        path = f"{prefix}{key}"
        name = key if key in fields else by_alias.get(key)
        if name is None:
            out.append(path)
            continue
        sub_model, shape = _field_models(fields[name].annotation)
        if sub_model is None:
            continue
        if shape == "list" and isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, Mapping):
                    out.extend(unknown_keys(item, sub_model, f"{path}[{i}]."))
        elif shape == "dict" and isinstance(value, Mapping):
            for sub_key, item in value.items():
                if isinstance(item, Mapping):
                    out.extend(unknown_keys(item, sub_model, f"{path}.{sub_key}."))
        elif shape == "one" and isinstance(value, Mapping):
            out.extend(unknown_keys(value, sub_model, f"{path}."))
    return out


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings from TOML (if found) + environment + what was changed in the app."""
    config_file = find_config_file(path)
    raw: dict[str, Any] = {}
    if config_file is not None:
        with config_file.open("rb") as fh:
            raw = tomllib.load(fh)
        for key in unknown_keys(raw):
            logger.warning("{}: unknown key {} is ignored (a typo?)", config_file, key)
    raw = _expand_env(raw)
    _apply_env_overrides(raw)
    settings = Settings.model_validate(raw)
    settings.source = str(config_file) if config_file else "defaults+env"
    settings.data_dir = settings.data_dir.expanduser()
    settings.agent.workspace = settings.agent.workspace.expanduser()
    settings.agent.extra_roots = [p.expanduser() for p in settings.agent.extra_roots]
    settings.sandbox.share = [p.expanduser() for p in settings.sandbox.share]
    settings.sandbox.share_read_only = [p.expanduser() for p in settings.sandbox.share_read_only]
    apply_app_settings(settings, load_app_settings(settings.data_dir))
    return settings


__all__ = [
    "APP_SETTINGS_FILE",
    "AgentSettings",
    "BrowserSettings",
    "CalendarFeedSettings",
    "CalendarSettings",
    "CloudSettings",
    "ContactSourceSettings",
    "ContactsSettings",
    "ConnectorSettings",
    "DEFAULT_DATA_DIR",
    "EmailSettings",
    "HandsSettings",
    "HubSettings",
    "LLMSettings",
    "MCPServerSettings",
    "MCPSettings",
    "MemorySettings",
    "SandboxSettings",
    "SentinelRule",
    "SentinelSettings",
    "ServerSettings",
    "Settings",
    "SkillsSettings",
    "TriggerSettings",
    "apply_app_settings",
    "find_config_file",
    "load_app_settings",
    "load_settings",
    "save_app_settings",
    "unknown_keys",
]
