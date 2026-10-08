"""Connections: the model, email, the browser and MCP servers, set up from the app.

Muse's Connections screen is where you plug things in and take them out again. Here that
means: non-secret settings go to ``<data_dir>/app-settings.json`` (layered over
``config.toml`` on every start, for the app and the CLI alike); secrets go straight into
the encrypted vault and are referred to as ``{{vault:NAME}}``. Nothing here is ever shown
to the model — it only gets the tools that result.
"""

from __future__ import annotations

import asyncio
import imaplib
import re
import smtplib
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from nanomuse.background import keep_task
from nanomuse.cloud import DEFAULT_CHAT_MODEL as DEFAULT_CLOUD_MODEL
from nanomuse.cloud import DEFAULT_GUI_MODEL as DEFAULT_CLOUD_GUI_MODEL
from nanomuse.cloud import model_url
from nanomuse.config import (
    CHATGPT_PROVIDER,
    PROTOCOLS,
    CalendarFeedSettings,
    ContactSourceSettings,
    MCPServerSettings,
    apply_app_settings,
    check_provider,
    load_app_settings,
    save_app_settings,
)
from nanomuse.contacts import OWN
from nanomuse.llm.chatgpt import DEFAULT_MODEL as CHATGPT_DEFAULT_MODEL
from nanomuse.logger import logger
from nanomuse.schema import Message
from nanomuse.search import WebSearchProvider
from nanomuse.server.failures import describe_failure
from nanomuse.tools import (
    Calendar,
    Contacts,
    MCPManager,
    ReadEmails,
    SendEmail,
    WebSearch,
    playwright_available,
)
from nanomuse.vault.vault import VaultError

if TYPE_CHECKING:
    from nanomuse.server.service import MuseService

LLM_KEY = "LLM_API_KEY"
EMBEDDINGS_KEY = "EMBEDDINGS_API_KEY"
SEARCH_KEY = "SEARCH_API_KEY"
GUI_KEY = "GUI_API_KEY"
IMAGE_KEY = "IMAGE_API_KEY"
VIDEO_KEY = "VIDEO_API_KEY"
#: the vault entry each media slot's key goes to
_MEDIA_KEYS: dict[str, str] = {"image": IMAGE_KEY, "video": VIDEO_KEY}
#: what a slot needs of a provider, for the sentence that refuses one without it
_SLOT_NOUNS: dict[str, str] = {
    "vision": "models that read pictures",
    "image": "image models",
    "video": "video models",
}
EMAIL_ADDRESS = "EMAIL_ADDRESS"
EMAIL_PASSWORD = "EMAIL_PASSWORD"

# The provider presets the app offers. `models` is the fallback catalogue for when the
# endpoint's own /models cannot be reached (see `llm_models`); names move fast, the live list
# is the truth. `key_url` is where a key comes from; `key_hint` what one looks like there.
# `group` sorts the form: what protocol the endpoint speaks. `gui_model` is the hands model
# the preset suggests next to its chat model (contract C4): one that sees pictures.
PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "label": "DeepSeek",
        "subtitle": "深度求索",
        "group": "openai",
        "provider": "openai",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-flash", "deepseek-chat", "deepseek-reasoner"],
        "key_url": "https://platform.deepseek.com/api_keys",
        "key_hint": "sk-…",
    },
    "kimi": {
        "label": "Kimi",
        "subtitle": "Moonshot AI · 月之暗面",
        "group": "openai",
        "provider": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["kimi-k2.6", "kimi-k2.7-code"],
        "key_url": "https://platform.moonshot.cn/console/api-keys",
        "key_hint": "sk-…",
    },
    "qwen": {
        "label": "Alibaba Cloud Bailian",
        "subtitle": "阿里云百炼 · DashScope · DeepSeek and Qwen, one key",
        "group": "openai",
        "provider": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["deepseek-v4.1-flash", "qwen3.8-27b", "qwen3.7-plus", "qwen3.7-max"],
        "gui_model": "qwen3.8-27b",
        "key_url": "https://bailian.console.aliyun.com/?apiKey=1",
        "key_hint": "sk-…",
        # the console only signs up accounts from mainland China (contract C5)
        "region": "cn",
    },
    "glm": {
        "label": "GLM",
        "subtitle": "智谱 AI",
        "group": "openai",
        "provider": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-5.2", "glm-5"],
        "key_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "key_hint": "xxxxxxxx.xxxxxxxx",
    },
    "doubao": {
        "label": "豆包",
        "subtitle": "火山方舟 · Volcengine Ark",
        "group": "openai",
        "provider": "openai",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        # Ark models are versioned deployments; the live list has the exact ids
        "models": ["doubao-seed-2-0-pro-260215", "doubao-seed-2-0-lite-260428"],
        "key_url": "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
        "key_hint": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    },
    "minimax": {
        "label": "MiniMax",
        "subtitle": "MiniMax · 稀宇科技",
        "group": "openai",
        "provider": "openai",
        "base_url": "https://api.minimaxi.com/v1",
        "models": ["MiniMax-M3", "MiniMax-M2.7"],
        "key_url": "https://platform.minimaxi.com/user-center/basic-information/interface-key",
        "key_hint": "eyJ…",
    },
    "openai": {
        "label": "OpenAI",
        "subtitle": "Chat Completions",
        "group": "openai",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-5-mini", "gpt-5", "gpt-4.1"],
        "key_url": "https://platform.openai.com/api-keys",
        "key_hint": "sk-proj-…",
    },
    "openai_responses": {
        "label": "OpenAI",
        "subtitle": "Responses API",
        "group": "responses",
        "provider": "openai_responses",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-5-mini", "gpt-5", "gpt-4.1"],
        "key_url": "https://platform.openai.com/api-keys",
        "key_hint": "sk-proj-…",
    },
    "openrouter": {
        "label": "OpenRouter",
        "subtitle": "one account, one key, pay as you go",
        "group": "openai",
        "provider": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            "deepseek/deepseek-v4.1-flash",
            "qwen/qwen3.8-27b",
            "anthropic/claude-sonnet-4",
            "openai/gpt-5-mini",
        ],
        "gui_model": "qwen/qwen3.8-27b",
        "key_url": "https://openrouter.ai/keys",
        "key_hint": "sk-or-v1-…",
    },
    "ollama": {
        "label": "Ollama",
        "subtitle": "on this machine, no key",
        "group": "local",
        "provider": "openai",
        "base_url": "http://127.0.0.1:11434/v1",
        "models": ["qwen3:8b", "llama3.1:8b"],
        "no_key": True,
    },
    "custom": {
        "label": "Other OpenAI-compatible endpoint",
        "subtitle": "vLLM, LM Studio, a gateway, anything with /v1",
        "group": "local",
        "provider": "openai",
        "base_url": "",
        "key_optional": True,
    },
}


def _modality(model: dict[str, Any]) -> str:
    """What a relay model does — "image", "video" or "chat" — from its `nanomuse.kind` or
    the OpenRouter-style `architecture.output_modalities`."""
    kind = str((model.get("nanomuse") or {}).get("kind") or "")
    if kind in ("image", "video"):
        return kind
    out = (model.get("architecture") or {}).get("output_modalities") or ["text"]
    if out == ["image"]:
        return "image"
    if out == ["video"]:
        return "video"
    return "chat"


_NOT_IMAGE = ("embedding", "-vl", "vision", "caption", "edit")
_IMAGE_WORDS = (
    "image",
    "dall-e",
    "flux",
    "stable-diffusion",
    "sdxl",
    "sd3",
    "seedream",
    "kolors",
    "imagen",
    "ideogram",
    "recraft",
    "hidream",
    "cogview",
)
_VIDEO_WORDS = ("i2v", "t2v", "video", "sora", "veo", "kling", "hailuo", "seedance")


def looks_like_image_model(model_id: str) -> bool:
    """Names that mean "text to image" across the providers nanoMuse meets (the phone's
    ImageGen.looksLikeImageModel); edit-only models are left out — they need a picture."""
    s = model_id.lower()
    if any(w in s for w in _NOT_IMAGE) or looks_like_video_model(s):
        return False
    return any(w in s for w in _IMAGE_WORDS)


def looks_like_video_model(model_id: str) -> bool:
    s = model_id.lower()
    return any(w in s for w in _VIDEO_WORDS)


def normalize_base_url(url: str) -> str:
    """Trim, drop a trailing slash and add ``/v1`` when the URL names a host and nothing else.

    An OpenAI-compatible server listens under ``/v1``; people paste the host. Anything with a
    path of its own (``/api/paas/v4``, ``/compatible-mode/v1``) is left alone.
    """
    url = url.strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    # a preset's own host is left exactly as the preset has it (DeepSeek listens at the root)
    if any(url == str(p.get("base_url", "")).rstrip("/") for p in PROVIDERS.values()):
        return url
    if not urlsplit(url).path.rstrip("/"):
        return url + "/v1"
    return url


PROXY_SCHEMES = ("http", "https", "socks5", "socks5h")


def normalize_proxy(value: str) -> str:
    """``[llm] proxy`` as typed in the app: trimmed; empty clears; otherwise an
    ``http(s)://`` or ``socks5(h)://`` URL with a host, or :class:`ValueError`."""
    value = value.strip()
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.scheme.lower() not in PROXY_SCHEMES or not parts.hostname:
        raise ValueError("proxy must be http://host:port, https://host:port or socks5://host:port")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("proxy is a host and a port, without a path")
    if parts.scheme.lower().startswith("socks") and not _socks_available():
        raise ValueError(
            "a SOCKS proxy needs the socksio package on the runtime: pip install 'httpx[socks]'"
        )
    return value.rstrip("/")


def _socks_available() -> bool:
    try:
        import socksio  # noqa: F401
    except ImportError:
        return False
    return True


def mask_proxy(value: str) -> str:
    """The proxy as the app shows it: credentials, when it carries any, replaced by dots."""
    value = (value or "").strip()
    if "@" not in value:
        return value
    parts = urlsplit(value)
    if not parts.hostname:
        return value
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    user = parts.username or ""
    cred = f"{user}:••••" if parts.password is not None else user
    return f"{parts.scheme}://{cred}@{host}{parts.path}"


def _vault_name(feed_name: str, prefix: str = "CALENDAR_") -> str:
    return prefix + (re.sub(r"[^A-Z0-9]+", "_", feed_name.upper()).strip("_") or "FEED")


def _link_or_path(url: str) -> bool:
    """An http(s)/file link, or a path: absolute, ``~``, or a Windows drive letter."""
    return url.startswith(("http://", "https://", "file://", "/", "~")) or bool(
        re.match(r"^[A-Za-z]:[\\/]", url)
    )


def _test_failed(exc: BaseException) -> dict[str, Any]:
    """A model test that failed: the sentence a chat turn would show for the same error
    (the apps translate it), the error's own words one tap away as ``detail``."""
    code, text = describe_failure(exc)
    return {
        "ok": False,
        "code": code,
        "error": text,
        "detail": f"{type(exc).__name__}: {str(exc).strip()[:400]}",
    }


class Connections:
    def __init__(self, svc: MuseService):
        self.svc = svc
        self.data = load_app_settings(svc.data_dir)
        # MCP servers added from the app, connected on demand: name -> manager
        self._mcp: dict[str, MCPManager] = {}
        # calendar feeds that come from config.toml (the app cannot delete those, only its own)
        app_feeds = {f.get("name") for f in (self.data.get("calendar") or {}).get("feeds") or []}
        self._toml_feeds = [
            f for f in svc.settings.connectors.calendar.feeds if f.name not in app_feeds
        ]
        app_sources = {
            c.get("name") for c in (self.data.get("contacts") or {}).get("sources") or []
        }
        self._toml_sources = [
            c for c in svc.settings.connectors.contacts.sources if c.name not in app_sources
        ]

    # ------------------------------------------------------------------ helpers
    @property
    def settings(self):  # noqa: ANN201
        return self.svc.settings

    @property
    def vault(self):  # noqa: ANN201
        return self.svc.app.vault

    def _save(self) -> None:
        save_app_settings(self.svc.data_dir, self.data)

    def _publish(self) -> None:
        self.svc.bus.publish({"kind": "connections", "connections": self.view()})
        self.svc.bus.publish({"kind": "settings", "settings": self.svc.settings_view()})

    # ------------------------------------------------------------------ view
    CLOUD_PRESET = "nanomuse_cloud"

    def _providers(self) -> dict[str, dict[str, Any]]:
        """The catalogue, plus nanoMuse Cloud as a provider of its own while the account is
        signed in: the account's chat models, no key to paste (the account key is the key),
        so the form says "nanoMuse Cloud" rather than a bare URL under "other endpoint"."""
        hub = getattr(self.svc, "hub", None)
        if hub is None or not hub.signed_in or not self.settings.cloud.models:
            # signed out, or the account's models switched off (``[cloud] models``)
            return PROVIDERS
        return {
            self.CLOUD_PRESET: {
                "label": "nanoMuse Cloud",
                "subtitle": "your account's model, with a free allowance",
                "group": "cloud",
                "provider": "openai",
                "base_url": model_url(hub.cloud.base_url),
                "models": hub.chat_models or [DEFAULT_CLOUD_MODEL],
                "gui_model": hub.gui_models[0] if hub.gui_models else DEFAULT_CLOUD_GUI_MODEL,
                "gui_models": hub.gui_models or [DEFAULT_CLOUD_GUI_MODEL],
                "no_key": True,
                "cloud": True,
            },
            **PROVIDERS,
        }

    def view(self) -> dict[str, Any]:
        s = self.settings
        key = s.llm.api_key
        if not key:
            key_source = "none"
        elif self.vault.has_placeholders(key):
            # nanoMuse: whichever vault entry the placeholder names (LLM_API_KEY for a key
            # pasted here, NANOMUSE_CLOUD_KEY when the Cloud relay is the model)
            try:
                key_source = "vault" if self.vault.resolve(key) else "missing"
            except VaultError:
                key_source = "missing"
        else:
            key_source = "config"
        email = s.connectors.email
        address = self.vault.get(EMAIL_ADDRESS) or ""
        configured = bool(
            email.imap_host and email.smtp_host and address and self.vault.get(EMAIL_PASSWORD)
        )
        app_mcp = {m["name"] for m in (self.data.get("mcp") or {}).get("servers") or []}
        live_tools: dict[str, int] = {}
        for t in self.svc.app.tools:
            server = getattr(t, "server", None)
            if server:
                live_tools[server] = live_tools.get(server, 0) + 1
        return {
            "llm": {
                "provider": s.llm.provider,
                "model": s.llm.model,
                "base_url": s.llm.base_url or "",
                "tool_mode": s.llm.tool_mode,
                "stream": s.llm.stream,
                # the avatar studio's models on the same host; "" = the automatic choice
                "image_model": s.llm.image_model,
                "video_model": s.llm.video_model,
                # the slot's proxy, its credentials hidden; "" when there is none
                "proxy": mask_proxy(s.llm.proxy),
                "key_source": key_source,
                "from_app": bool(self.data.get("llm")),
                # the model is the nanoMuse Cloud account's (the form says so instead of a URL)
                "cloud": bool(
                    s.llm.base_url
                    and getattr(self.svc, "hub", None) is not None
                    and s.llm.base_url.rstrip("/") == model_url(self.svc.hub.cloud.base_url)
                ),
            },
            "providers": self._providers(),
            "embeddings": self._embeddings_view(),
            "search": self._search_view(),
            "email": {
                "enabled": email.enabled,
                "configured": configured,
                "address": address,
                "imap_host": email.imap_host,
                "imap_port": email.imap_port,
                "smtp_host": email.smtp_host,
                "smtp_port": email.smtp_port,
                "smtp_starttls": email.smtp_starttls,
                "password_set": bool(self.vault.get(EMAIL_PASSWORD)),
            },
            "calendar": self._calendar_view(),
            "contacts": self._contacts_view(),
            "browser": {
                "enabled": s.browser.enabled,
                # a browser can render somewhere: Playwright here, or the phone's WebView
                "available": playwright_available() or self.svc.phone.browser_device is not None,
                "backend": self.svc.browser_backend(),
            },
            "gui": self._gui_view(),
            "hands": self.hands_view(),
            # where pictures and clips come from (the Models contract): the slot as set
            # and what it resolves to
            "image": self.media_view("image"),
            "video": self.media_view("video"),
            "mcp": [
                {
                    "name": m.name,
                    "command": m.command,
                    "args": m.args,
                    "url": m.url,
                    "risk": m.risk.value,
                    "tools": live_tools.get(m.name, 0),
                    "connected": m.name in live_tools,
                    "from_app": m.name in app_mcp,
                    "builtin": False,
                }
                for m in s.mcp.servers
            ]
            + self._device_mcp_view(live_tools),
            # connections the account's other devices hold (contract C3): a name and a
            # kind, never a key; ``here`` when a server of that name is connected on this one
            "shared": self._shared_view(),
            "vault": self.vault.names(),
            "onboarded": bool(self.data.get("onboarded")),
        }

    def _shared_view(self) -> list[dict[str, Any]]:
        hub = getattr(self.svc, "hub", None)
        if hub is None or not hub.signed_in:
            return []
        local_names = {m.name for m in self.settings.mcp.servers}
        local_urls = {(m.url or "").split("?", 1)[0] for m in self.settings.mcp.servers if m.url}
        return [
            {**e, "here": e["id"] in local_names or (bool(e["url"]) and e["url"] in local_urls)}
            for e in hub.profile.shared_connectors
        ]

    def _share_connectors(self) -> None:
        """What this device connected changed: the account hears a moment later."""
        hub = getattr(self.svc, "hub", None)
        if hub is not None:
            hub.profile.changed()

    def _calendar_view(self) -> dict[str, Any]:
        cal = self.settings.connectors.calendar
        status = {f["name"]: f for f in self.svc.app.calendar.status()["feeds"]}
        app_names = {f.get("name") for f in self._calendar_data().get("feeds") or []}
        return {
            "enabled": cal.enabled,
            "configured": cal.enabled and bool(cal.feeds),
            "refresh_minutes": cal.refresh_minutes,
            "day_start": cal.day_start,
            "day_end": cal.day_end,
            "feeds": [
                {
                    "name": f.name,
                    "from_app": f.name in app_names,
                    "events": status.get(f.name, {}).get("events", 0),
                    "fetched_at": status.get(f.name, {}).get("fetched_at"),
                    "error": status.get(f.name, {}).get("error", ""),
                }
                for f in cal.feeds
            ],
        }

    def _contacts_view(self) -> dict[str, Any]:
        settings = self.settings.connectors.contacts
        book = self.svc.app.contacts
        status = {s["name"]: s for s in book.status()["sources"]}
        app_names = {c.get("name") for c in self._contacts_data().get("sources") or []}
        return {
            "enabled": settings.enabled,
            "configured": settings.enabled and book.configured,
            "count": len(book) if settings.enabled else 0,
            "own": len(book.own),
            "sources": [
                {
                    "name": c.name,
                    "from_app": c.name in app_names,
                    "file": not c.url.startswith(("http://", "https://", "{{")),
                    "contacts": status.get(c.name, {}).get("contacts", 0),
                    "fetched_at": status.get(c.name, {}).get("fetched_at"),
                    "error": status.get(c.name, {}).get("error", ""),
                }
                for c in settings.sources
            ],
        }

    # ------------------------------------------------------------------ model
    def set_llm(self, body: dict[str, Any]) -> dict[str, Any]:
        llm = dict(self.data.get("llm") or {})
        for key in ("provider", "model", "base_url", "tool_mode", "image_model", "video_model"):
            if body.get(key) is not None:
                llm[key] = str(body[key]).strip()
        if body.get("base_url") is not None:
            llm["base_url"] = normalize_base_url(llm["base_url"])
        if llm.get("provider") not in (None, ""):
            # a protocol, "chatgpt", or a catalogue id (nanomuse/llm/providers.json)
            llm["provider"] = check_provider(str(llm["provider"]))
        if llm.get("provider") == CHATGPT_PROVIDER:
            # the sign-in has no endpoint and no key of its own; an empty model is Codex's default
            if body.get("provider") is not None and not llm.get("model"):
                llm["model"] = CHATGPT_DEFAULT_MODEL
            if llm.get("base_url"):
                logger.warning('provider = "chatgpt" ignores base_url; dropped from the slot')
            llm["base_url"] = ""
        if llm.get("tool_mode") not in (None, "", "auto", "native", "prompt"):
            raise ValueError("tool_mode must be 'auto', 'native' or 'prompt'")
        if body.get("proxy") is not None:
            # this provider's requests through one proxy, never nanoMuse Cloud; "" clears
            llm["proxy"] = normalize_proxy(str(body["proxy"]))
        api_key = body.get("api_key")
        if api_key:
            self.vault.set(LLM_KEY, str(api_key).strip())
            llm["api_key"] = "{{vault:" + LLM_KEY + "}}"
        elif api_key == "":
            # an explicitly empty key: no key at all (local models)
            self.vault.delete(LLM_KEY)
            llm["api_key"] = ""
        self.data["llm"] = llm
        self._save()
        apply_app_settings(self.settings, {"llm": llm})
        if llm.get("api_key") == "":
            self.settings.llm.api_key = ""
        if llm.get("provider") == CHATGPT_PROVIDER:
            self.settings.llm.base_url = None
        self._swap_llm()
        self._publish()
        return self.view()["llm"]

    def _swap_llm(self) -> None:
        """The model changed: a new client for the app and for every idle thread. A thread in
        the middle of a turn keeps the client it started on and finishes the turn there (a
        request in flight on a closed client is a RuntimeError in the person's face); its
        worker moves it to the new client and closes the old one when the run ends
        (``MuseService._release_llm``). The old client is closed here only when no turn
        holds it."""
        old = self.svc.app.llm
        new = self.svc.app.make_llm()
        self.svc.app.llm = new
        for t in self.svc.threads.values():
            if not t.busy:
                t.agent.llm = new
        if not any(t.busy and t.agent.llm is old for t in self.svc.threads.values()):
            keep_task(asyncio.get_running_loop().create_task(old.close()))
        logger.info(
            "model switched to {} @ {}", self.settings.llm.model, self.settings.llm.base_url
        )
        # embeddings that ride on the model's endpoint follow it
        if not self.settings.memory.embedding_base_url:
            self.svc.app.attach_embedder()

    # ------------------------------------------------------------------ embeddings
    def _embeddings_view(self) -> dict[str, Any]:
        from nanomuse.memory.embeddings import default_model

        m = self.settings.memory
        app_ = self.svc.app
        key = m.embedding_api_key
        if not key:
            key_source = "model"  # the model's key, on the model's endpoint
        elif self.vault.has_placeholders(key):
            key_source = (
                "vault"
                if not self.vault.has_placeholders(self.vault.resolve(key, strict=False))
                else "missing"
            )
        else:
            key_source = "config"
        base_url = m.embedding_base_url or self.settings.llm.base_url or ""
        status = app_.memory.index.status() if app_.memory and app_.memory.index else None
        return {
            "mode": m.embeddings,
            "model": m.embedding_model,
            "default_model": default_model(base_url),
            "base_url": m.embedding_base_url,
            "effective_base_url": base_url,
            "key_source": key_source,
            "from_app": bool(self.data.get("embeddings")),
            "memory_enabled": app_.memory is not None,
            "available": status["available"] if status else None,
            "reason": status["reason"] if status else "",
            "dims": status["dims"] if status else 0,
            "indexed": status["indexed"] if status else 0,
            "total": status["total"] if status else (app_.memory.count() if app_.memory else 0),
            "status": status["status"] if status else "off",
        }

    def _search_view(self) -> dict[str, Any]:
        from nanomuse.search import PROVIDERS as SEARCH_PROVIDERS

        web = self.settings.connectors.search
        key = web.api_key
        if not key:
            key_source = "none"
        elif self.vault.has_placeholders(key):
            key_source = "vault" if self.vault.get(SEARCH_KEY) else "missing"
        else:
            key_source = "config"
        provider = self._search_provider()
        return {
            "provider": web.provider,
            "base_url": web.base_url,
            "key_source": key_source,
            "configured": provider.configured if provider else True,
            "from_app": bool(self.data.get("search")),
            "providers": [
                {
                    "id": pid,
                    "label": p["label"],
                    "needs_key": p["needs_key"],
                    "keys_url": p.get("keys_url", ""),
                }
                for pid, p in SEARCH_PROVIDERS.items()
            ],
        }

    def _search_provider(self) -> WebSearchProvider | None:
        tool = self.svc.app.tools.get("web_search")
        return tool.provider if isinstance(tool, WebSearch) else None

    def set_search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Who answers web searches: DuckDuckGo (nothing to set), Brave or Tavily with a
        key, or a SearXNG instance by URL."""
        from nanomuse.search import PROVIDERS as SEARCH_PROVIDERS

        web = dict(self.data.get("search") or {})
        if body.get("provider") is not None:
            if body["provider"] not in SEARCH_PROVIDERS:
                raise ValueError("provider must be one of " + ", ".join(SEARCH_PROVIDERS))
            web["provider"] = body["provider"]
        if body.get("base_url") is not None:
            web["base_url"] = str(body["base_url"]).strip().rstrip("/")
            if web["base_url"] and not re.match(r"^https?://", web["base_url"]):
                raise ValueError("base_url must start with http:// or https://")
        api_key = body.get("api_key")
        if api_key:
            self.vault.set(SEARCH_KEY, str(api_key).strip())
            web["api_key"] = "{{vault:" + SEARCH_KEY + "}}"
        elif api_key == "":
            self.vault.delete(SEARCH_KEY)
            web["api_key"] = ""
        self.data["search"] = web
        self._save()
        apply_app_settings(self.settings, {"search": web})
        self._publish()
        return self._search_view()

    async def test_search(self) -> dict[str, Any]:
        """One search against the configured provider, no fallback."""
        provider = self._search_provider() or WebSearchProvider(
            self.settings.connectors.search, vault=self.vault
        )
        if not provider.configured:
            what = "an API key" if provider.name in ("brave", "tavily") else "the instance URL"
            return {"ok": False, "error": f"{provider.label} needs {what} first"}
        return await provider.probe()

    def set_embeddings(self, body: dict[str, Any]) -> dict[str, Any]:
        """Recall by meaning: the mode, and where the vectors come from — the model's own
        endpoint (the default) or another one, Ollama next to DeepSeek for one."""
        emb = dict(self.data.get("embeddings") or {})
        if body.get("mode") is not None:
            if body["mode"] not in ("auto", "on", "off"):
                raise ValueError("mode must be 'auto', 'on' or 'off'")
            emb["mode"] = body["mode"]
        for key in ("model", "base_url"):
            if body.get(key) is not None:
                emb[key] = str(body[key]).strip()
        if emb.get("base_url") and not re.match(r"^https?://", emb["base_url"]):
            raise ValueError("base_url must start with http:// or https://")
        api_key = body.get("api_key")
        if api_key:
            self.vault.set(EMBEDDINGS_KEY, str(api_key).strip())
            emb["api_key"] = "{{vault:" + EMBEDDINGS_KEY + "}}"
        elif api_key == "":
            self.vault.delete(EMBEDDINGS_KEY)
            emb["api_key"] = ""
        self.data["embeddings"] = emb
        self._save()
        apply_app_settings(self.settings, {"embeddings": emb})
        self.svc.app.attach_embedder()
        self._publish()
        return self._embeddings_view()

    async def test_embeddings(self) -> dict[str, Any]:
        """One embeddings call; on success every memory is indexed right away."""
        app_ = self.svc.app
        emb = app_.embedder
        if app_.memory is None:
            return {"ok": False, "error": "memory is off"}
        if emb is None or not emb.enabled:
            return {"ok": False, "error": "recall by meaning is off"}
        loop = asyncio.get_running_loop()
        started = loop.time()
        emb.reset()  # a test always tries
        vectors = await emb.embed(["a short probe"])
        if vectors is None:
            return {"ok": False, "error": emb.reason[:400]}
        indexed = 0
        if app_.memory.index is not None and await app_.memory.index.ensure(app_.memory.all()):
            indexed = app_.memory.index.status()["indexed"]
        self._publish()
        return {
            "ok": True,
            "model": emb.model,
            "dims": emb.dims,
            "indexed": indexed,
            "ms": int((loop.time() - started) * 1000),
        }

    async def llm_models(self, body: dict[str, Any]) -> dict[str, Any]:
        """The models an endpoint offers: its own ``/models`` when it answers, else the catalogue.

        ``body``: ``base_url`` (or ``preset``), and ``api_key`` when the user has typed one
        that is not saved yet; otherwise the vault key is used when the endpoint is the
        configured one. Never touches settings — what the user typed in the form stays.

        For nanoMuse Cloud the answer also says which chat models are on the relay's menu
        and which are the other usable models under the operator's key (``menu`` /
        ``catalog``, likewise ``image_catalog`` / ``video_catalog``), and which chat models
        read pictures (``vision``), so the pickers show a member the whole list in groups.
        """
        preset_id = str(body.get("preset") or "")
        if preset_id == self.CLOUD_PRESET:
            hub = self.svc.hub
            if not hub.signed_in:
                return {
                    "models": [DEFAULT_CLOUD_MODEL],
                    "source": "catalogue",
                    "error": "signed out",
                }
            try:
                chat = await hub.refresh_chat_models()
            except Exception as exc:  # noqa: BLE001
                return {
                    "models": hub.chat_models or [DEFAULT_CLOUD_MODEL],
                    "source": "catalogue",
                    "error": f"{type(exc).__name__}",
                }
            # the relay says what each model does; the studio's pickers take it from here
            image = [str(m["id"]) for m in hub.models if _modality(m) == "image"]
            video = [str(m["id"]) for m in hub.models if _modality(m) == "video"]
            # relay 0.10: a member's list carries, after the menu, the usable models under the
            # operator's key (`nanomuse.catalog`); the pickers show them as a second group
            listed = {
                str(m["id"]) for m in hub.models if (m.get("nanomuse") or {}).get("listed", True)
            }
            vision = [
                str(m["id"])
                for m in hub.models
                if _modality(m) == "chat"
                and "image" in ((m.get("architecture") or {}).get("input_modalities") or [])
            ]
            return {
                "models": chat,
                "image_models": image,
                "video_models": video,
                "source": "live",
                "menu": [i for i in chat if i in listed],
                "catalog": [i for i in chat if i not in listed],
                "image_catalog": [i for i in image if i not in listed],
                "video_catalog": [i for i in video if i not in listed],
                "vision": vision,
                # contract C4: the relay says which models are for the hands; recommended first
                "gui": hub.gui_models,
                "gui_recommended": hub.gui_models[0] if hub.gui_models else "",
                "chat_recommended": chat[0] if chat else "",
            }
        preset = PROVIDERS.get(preset_id) or {}
        base_url = normalize_base_url(str(body.get("base_url") or preset.get("base_url") or ""))
        catalogue: list[str] = list(preset.get("models") or [])
        if not base_url:
            return {"models": catalogue, "source": "catalogue"}
        key = str(body.get("api_key") or "").strip()
        if not key and normalize_base_url(self.settings.llm.base_url or "") == base_url:
            key = self.vault.resolve(self.settings.llm.api_key or "", strict=False)
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        candidates = [f"{base_url}/models"]
        if not re.search(r"/v\d+$", base_url):
            candidates.append(f"{base_url}/v1/models")
        error = ""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                for url in candidates:
                    try:
                        r = await client.get(url, headers=headers)
                    except httpx.HTTPError as exc:
                        error = f"{type(exc).__name__}"
                        continue
                    if r.status_code == 404:
                        error = "404"
                        continue
                    if r.status_code >= 400:
                        error = f"HTTP {r.status_code}"
                        break
                    data = r.json()
                    rows = data.get("data") if isinstance(data, dict) else data
                    ids = sorted(
                        {
                            str(row.get("id") if isinstance(row, dict) else row)
                            for row in (rows or [])
                            if (row.get("id") if isinstance(row, dict) else row)
                        }
                    )
                    if ids:
                        return {
                            "models": ids,
                            "image_models": [i for i in ids if looks_like_image_model(i)],
                            "video_models": [i for i in ids if looks_like_video_model(i)],
                            "source": "live",
                        }
                    error = "empty list"
                    break
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}"
        return {"models": catalogue, "source": "catalogue", "error": error}

    async def test_llm(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            response = await asyncio.wait_for(
                self.svc.app.llm.ask([Message.user("Reply with the single word OK.")], tools=None),
                timeout=45,
            )
        except Exception as exc:  # noqa: BLE001
            return _test_failed(exc)
        return {
            "ok": True,
            "reply": (response.content or "").strip()[:200],
            "ms": int((loop.time() - started) * 1000),
        }

    # ------------------------------------------------------------------ email
    def set_email(self, body: dict[str, Any]) -> dict[str, Any]:
        email = dict(self.data.get("email") or {})
        for key in ("imap_host", "smtp_host"):
            if body.get(key) is not None:
                email[key] = str(body[key]).strip()
        for key in ("imap_port", "smtp_port"):
            if body.get(key) is not None:
                email[key] = int(body[key])
        if body.get("smtp_starttls") is not None:
            email["smtp_starttls"] = bool(body["smtp_starttls"])
        if body.get("address") is not None:
            self.vault.set(EMAIL_ADDRESS, str(body["address"]).strip())
        if body.get("password"):
            self.vault.set(EMAIL_PASSWORD, str(body["password"]))
        if body.get("enabled") is not None:
            email["enabled"] = bool(body["enabled"])
        elif (
            email.get("imap_host")
            and email.get("smtp_host")
            and self.vault.get(EMAIL_ADDRESS)
            and self.vault.get(EMAIL_PASSWORD)
        ):
            # everything needed is there: connecting is what saving it means
            email["enabled"] = True
        self.data["email"] = email
        self._save()
        apply_app_settings(self.settings, {"email": email})
        self._sync_email_tools()
        self._publish()
        return self.view()["email"]

    def disconnect_email(self) -> dict[str, Any]:
        self.vault.delete(EMAIL_PASSWORD)
        self.vault.delete(EMAIL_ADDRESS)
        self.data["email"] = {**(self.data.get("email") or {}), "enabled": False}
        self._save()
        self.settings.connectors.email.enabled = False
        self._sync_email_tools()
        self._publish()
        return self.view()["email"]

    def _sync_email_tools(self) -> None:
        tools = self.svc.app.tools
        enabled = self.settings.connectors.email.enabled
        if enabled and "read_emails" not in tools:
            tools.add(
                ReadEmails(settings=self.settings.connectors.email, vault=self.vault),
                SendEmail(
                    settings=self.settings.connectors.email,
                    vault=self.vault,
                    book=self.svc.app.contacts,
                ),
            )
        elif not enabled:
            tools.remove("read_emails")
            tools.remove("send_email")
        for t in tools:
            if t.name in ("read_emails", "send_email"):
                t.settings = self.settings.connectors.email  # type: ignore[attr-defined]

    async def test_email(self) -> dict[str, Any]:
        email = self.settings.connectors.email
        address = self.vault.get(EMAIL_ADDRESS) or ""
        password = self.vault.get(EMAIL_PASSWORD) or ""
        if not (email.imap_host and email.smtp_host and address and password):
            return {"ok": False, "error": "fill in the servers, the address and the password first"}

        def probe() -> dict[str, Any]:
            out: dict[str, Any] = {"ok": True}
            try:
                imap = imaplib.IMAP4_SSL(email.imap_host, email.imap_port, timeout=15)
                imap.login(address, password)
                status, data = imap.select("INBOX", readonly=True)
                out["inbox"] = int(data[0]) if status == "OK" and data and data[0] else None
                imap.logout()
            except (imaplib.IMAP4.error, OSError) as exc:
                return {"ok": False, "error": f"IMAP: {exc}"[:300]}
            try:
                smtp = smtplib.SMTP(email.smtp_host, email.smtp_port, timeout=15)
                if email.smtp_starttls:
                    smtp.starttls()
                smtp.login(address, password)
                smtp.quit()
            except (smtplib.SMTPException, OSError) as exc:
                return {"ok": False, "error": f"SMTP: {exc}"[:300]}
            return out

        return await asyncio.to_thread(probe)

    # ------------------------------------------------------------------ calendar
    def _calendar_data(self) -> dict[str, Any]:
        return dict(self.data.get("calendar") or {})

    def _apply_calendar(self, calendar: dict[str, Any]) -> None:
        self.data["calendar"] = calendar
        self._save()
        settings = self.settings.connectors.calendar
        # feeds from config.toml stay; the app's feeds come after them and win on a name clash
        app_feeds = [CalendarFeedSettings.model_validate(f) for f in calendar.get("feeds") or []]
        app_names = {f.name for f in app_feeds}
        settings.feeds = [f for f in self._toml_feeds if f.name not in app_names] + app_feeds
        settings.enabled = bool(calendar.get("enabled", bool(settings.feeds)))
        for key in ("refresh_minutes", "day_start", "day_end"):
            if calendar.get(key) not in (None, ""):
                setattr(settings, key, calendar[key])
        self._sync_calendar_tool()
        self._publish()

    def _sync_calendar_tool(self) -> None:
        tools = self.svc.app.tools
        enabled = self.settings.connectors.calendar.enabled
        if enabled and "calendar" not in tools:
            tools.add(
                Calendar(feeds=self.svc.app.calendar, workspace=self.settings.agent.workspace)
            )
        elif not enabled:
            tools.remove("calendar")

    async def add_calendar_feed(self, body: dict[str, Any]) -> dict[str, Any]:
        """Add (or replace) a feed; the link goes to the vault, the settings keep a placeholder."""
        name = str(body.get("name") or "").strip()
        url = str(body.get("url") or "").strip()
        if not name:
            raise ValueError("the calendar needs a name")
        if not url:
            raise ValueError("paste the calendar's .ics link (or a path to an .ics file)")
        if not _link_or_path(url):
            raise ValueError("the link must start with https:// (or be a path to an .ics file)")
        secret = _vault_name(name)
        self.vault.set(secret, url)
        calendar = self._calendar_data()
        feeds = [f for f in calendar.get("feeds") or [] if f.get("name") != name]
        feeds.append({"name": name, "url": f"{{{{vault:{secret}}}}}"})
        calendar["feeds"] = feeds
        calendar["enabled"] = True
        self._apply_calendar(calendar)
        status = await self.svc.app.calendar.refresh(force=True)
        state = next((f for f in status["feeds"] if f["name"] == name), None)
        if state and state.get("error"):
            # keep it (the user can fix the link) but say what went wrong
            return {**self.view()["calendar"], "error": state["error"]}
        self.svc.bus.publish({"kind": "calendar", "calendar": self.svc.calendar_view()})
        return self.view()["calendar"]

    def remove_calendar_feed(self, name: str) -> bool:
        calendar = self._calendar_data()
        feeds = calendar.get("feeds") or []
        if not any(f.get("name") == name for f in feeds):
            # a feed from config.toml: it can be switched off, not deleted from here
            return False
        calendar["feeds"] = [f for f in feeds if f.get("name") != name]
        self.vault.delete(_vault_name(name))
        if not calendar["feeds"] and not self._toml_feeds:
            calendar["enabled"] = False
        self._apply_calendar(calendar)
        self.svc.app.calendar.states.pop(name, None)
        self.svc.bus.publish({"kind": "calendar", "calendar": self.svc.calendar_view()})
        return True

    def set_calendar(self, body: dict[str, Any]) -> dict[str, Any]:
        """Working hours, refresh interval, on/off."""
        calendar = self._calendar_data()
        if body.get("enabled") is not None:
            calendar["enabled"] = bool(body["enabled"])
        if body.get("refresh_minutes") is not None:
            calendar["refresh_minutes"] = max(5, int(body["refresh_minutes"]))
        for key in ("day_start", "day_end"):
            if body.get(key):
                value = str(body[key]).strip()
                if not re.fullmatch(r"\d{2}:\d{2}", value):
                    raise ValueError(f"{key} must be HH:MM")
                calendar[key] = value
        self._apply_calendar(calendar)
        return self.view()["calendar"]

    async def test_calendar(self) -> dict[str, Any]:
        cal = self.svc.app.calendar
        if not cal.configured:
            return {"ok": False, "error": "add a calendar link first"}
        status = await cal.refresh(force=True)
        broken = [f for f in status["feeds"] if f["error"]]
        if broken:
            return {"ok": False, "error": "; ".join(f"{f['name']}: {f['error']}" for f in broken)}
        self.svc.bus.publish({"kind": "calendar", "calendar": self.svc.calendar_view()})
        return {
            "ok": True,
            "events": sum(f["events"] for f in status["feeds"]),
            "feeds": len(status["feeds"]),
        }

    # ------------------------------------------------------------------ contacts
    def _contacts_data(self) -> dict[str, Any]:
        return dict(self.data.get("contacts") or {})

    def _apply_contacts(self, contacts: dict[str, Any]) -> None:
        self.data["contacts"] = contacts
        self._save()
        settings = self.settings.connectors.contacts
        app_sources = [
            ContactSourceSettings.model_validate(c) for c in contacts.get("sources") or []
        ]
        app_names = {c.name for c in app_sources}
        settings.sources = [c for c in self._toml_sources if c.name not in app_names] + app_sources
        if contacts.get("enabled") is not None:
            settings.enabled = bool(contacts["enabled"])
        self.svc.app.contacts.read_files()
        self._sync_contacts_tool()
        self._publish()

    def _sync_contacts_tool(self) -> None:
        tools = self.svc.app.tools
        enabled = self.settings.connectors.contacts.enabled
        if enabled and "contacts" not in tools:
            tools.add(Contacts(book=self.svc.app.contacts))
        elif not enabled:
            tools.remove("contacts")

    async def add_contacts_source(self, body: dict[str, Any]) -> dict[str, Any]:
        """A ``.vcf`` link or path. A link goes to the vault (it may be a private URL)."""
        name = str(body.get("name") or "").strip()
        url = str(body.get("url") or "").strip()
        if not name:
            raise ValueError("the address book needs a name")
        if name == OWN:
            raise ValueError(f"{OWN!r} is the agent's own book; pick another name")
        if not url:
            raise ValueError("paste a link to the .vcf file, or a path to one")
        if not _link_or_path(url):
            raise ValueError("the link must start with https:// (or be a path to a .vcf file)")
        if url.startswith(("http://", "https://")):
            secret = _vault_name(name, "CONTACTS_")
            self.vault.set(secret, url)
            url = f"{{{{vault:{secret}}}}}"
        contacts = self._contacts_data()
        sources = [c for c in contacts.get("sources") or [] if c.get("name") != name]
        sources.append({"name": name, "url": url})
        contacts["sources"] = sources
        contacts["enabled"] = True
        self._apply_contacts(contacts)
        status = await self.svc.app.contacts.refresh(only=name)
        state = next((c for c in status["sources"] if c["name"] == name), None)
        self._publish()
        if state and state.get("error"):
            return {**self.view()["contacts"], "error": state["error"]}
        return self.view()["contacts"]

    async def import_contacts(self, name: str, text: str) -> dict[str, Any]:
        """A ``.vcf`` file uploaded from the phone: kept under ``<data_dir>/contacts/`` and
        added as a source."""
        name = name.strip() or "Imported"
        if name == OWN:
            raise ValueError(f"{OWN!r} is the agent's own book; pick another name")
        if "BEGIN:VCARD" not in text.upper():
            raise ValueError("that is not a vCard (.vcf) file")
        folder = self.settings.contacts_dir
        folder.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9\u3400-\u9fff_-]+", "-", name).strip("-") or "contacts"
        path = folder / f"{stem}.vcf"
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
        return await self.add_contacts_source({"name": name, "url": str(path)})

    def remove_contacts_source(self, name: str) -> bool:
        contacts = self._contacts_data()
        sources = contacts.get("sources") or []
        hit = next((c for c in sources if c.get("name") == name), None)
        if hit is None:
            return False  # from config.toml: switched off there, not here
        contacts["sources"] = [c for c in sources if c.get("name") != name]
        self.vault.delete(_vault_name(name, "CONTACTS_"))
        url = str(hit.get("url") or "")
        try:
            uploaded = self.settings.contacts_dir.resolve()
            path = Path(url).resolve()
            if path.is_relative_to(uploaded) and path.is_file():
                path.unlink()  # an upload of ours: gone with the source
        except (OSError, ValueError):
            pass
        self._apply_contacts(contacts)
        self.svc.app.contacts.states.pop(name, None)
        self._publish()
        return True

    def set_contacts(self, body: dict[str, Any]) -> dict[str, Any]:
        contacts = self._contacts_data()
        if body.get("enabled") is not None:
            contacts["enabled"] = bool(body["enabled"])
        self._apply_contacts(contacts)
        return self.view()["contacts"]

    async def test_contacts(self) -> dict[str, Any]:
        book = self.svc.app.contacts
        status = await book.refresh()
        self._publish()
        broken = [c for c in status["sources"] if c["error"]]
        if broken:
            return {
                "ok": False,
                "error": "; ".join(f"{c['name']}: {c['error']}" for c in broken),
            }
        return {"ok": True, "contacts": status["count"], "sources": len(status["sources"])}

    # ------------------------------------------------------------------ phone (GUI)
    def _device_mcp_view(self, live_tools: dict[str, int]) -> list[dict[str, Any]]:
        """On the phone, the app's own capabilities are an MCP server too (`device`), not
        in the config file: shown with the others, without a remove button."""
        from nanomuse.runtime import DEVICE_SERVER

        dev = getattr(self.svc.app, "device", None)
        if dev is None or not dev.has_host:
            return []
        return [
            {
                "name": DEVICE_SERVER,
                "command": None,
                "args": [],
                "url": dev.host_url + "/mcp",
                "risk": "moderate",
                "tools": live_tools.get(DEVICE_SERVER, 0),
                "connected": DEVICE_SERVER in live_tools,
                "from_app": False,
                "builtin": True,
            }
        ]

    def _key_source(self, key: str) -> str:
        """Where a slot's key comes from: ``none`` (the chat model's is used), ``vault``,
        ``missing`` (a vault reference nothing answers) or ``config``."""
        if not key:
            return "none"
        if self.vault.has_placeholders(key):
            resolved = self.vault.resolve(key, strict=False)
            return "missing" if not resolved or self.vault.has_placeholders(resolved) else "vault"
        return "config"

    def _catalogue_id(self, provider: str, base_url: str | None) -> str:
        """The catalogue id a slot's provider means: the id it names, else the entry whose
        host the URL is; "" when the catalogue lists neither."""
        from nanomuse.llm import catalogue

        cat = catalogue.load()
        if provider and provider not in PROTOCOLS and cat.get(provider) is not None:
            return provider
        entry = cat.by_base_url(base_url)
        return entry.id if entry is not None else ""

    def _gui_view(self) -> dict[str, Any]:
        gui = self.settings.gui
        where, model = self.svc.app.hands_choice()
        return {
            "enabled": gui.enabled,
            # the provider as set: a protocol (`openai` / `openai_responses`) or a catalogue id
            "provider": gui.provider,
            # the catalogue entry that means, by id or by host; "" for an unlisted host
            "provider_id": self._catalogue_id(gui.provider, gui.endpoint) if gui.model else "",
            "model": gui.model,
            # the model the hands use when none is set here, and where it comes from
            # (contract C4 and the Models contract §3): `gui` for a model set here, `chat`
            # for the chat provider's hands model, `cloud` for the relay's
            "effective_model": model,
            "effective_source": where,
            "default_model": self.svc.app.gui_model(default_only=True),
            "cloud": self.svc.app.llm_is_cloud(),
            "base_url": gui.base_url or "",
            "key_source": self._key_source(gui.api_key),
            "max_steps": gui.max_steps,
            "phone": self.svc.phone.status(),
        }

    def set_gui(self, body: dict[str, Any]) -> dict[str, Any]:
        """The switch for operating the phone, and the operator's model.

        ``enabled`` adds or removes the ``phone_*`` tools on the spot; the model fields are
        optional and default to the main model's endpoint and key. ``provider`` is a
        protocol (``openai`` / ``openai_responses``) or a catalogue id, as for the chat
        model; a catalogue id brings its endpoint along and must have models that see.
        """
        gui = dict(self.data.get("gui") or {})
        if body.get("enabled") is not None:
            gui["enabled"] = bool(body["enabled"])
        for key in ("provider", "model", "base_url"):
            if body.get(key) is not None:
                gui[key] = str(body[key]).strip()
        if gui.get("base_url"):
            gui["base_url"] = normalize_base_url(gui["base_url"])
        if gui.get("provider") not in (None, ""):
            gui["provider"] = self._check_slot_provider(
                str(gui["provider"]), gui.get("base_url") or "", "vision"
            )
        api_key = body.get("api_key")
        if api_key:
            self.vault.set(GUI_KEY, str(api_key).strip())
            gui["api_key"] = "{{vault:" + GUI_KEY + "}}"
        elif api_key == "":
            self.vault.delete(GUI_KEY)
            gui["api_key"] = ""
        self.data["gui"] = gui
        self._save()
        apply_app_settings(self.settings, {"gui": gui})
        if "enabled" in gui:
            self.svc.app.set_gui_enabled(bool(gui["enabled"]))
        operator = getattr(self.svc.app, "phone_operator", None)
        if operator is not None:
            operator.reset_llm()
        self._publish()
        self.svc.publish_phone()
        return self._gui_view()

    @staticmethod
    def _check_slot_provider(provider: str, base_url: str, capability: str) -> str:
        """``provider`` as the chat model takes it — a protocol, a catalogue id, the ChatGPT
        sign-in — checked against the catalogue for one slot: the entry it names, or the
        one whose host ``base_url`` is, must have ``capability``. A local server and the
        custom row have whatever the person installed, so they pass."""
        from nanomuse.llm import catalogue

        provider = check_provider(provider)
        noun = _SLOT_NOUNS[capability]
        if provider == CHATGPT_PROVIDER:
            if capability == "vision":
                return provider  # the sign-in reads pictures
            raise ValueError(f"the ChatGPT sign-in has no {noun}")
        cat = catalogue.load()
        entry = cat.get(provider) if provider not in PROTOCOLS else cat.by_base_url(base_url)
        if (
            entry is not None
            and not entry.user_capabilities
            and not entry.hosts() & {"127.0.0.1", "localhost"}
            and not entry.has(capability)
        ):
            raise ValueError(f"{entry.name} has no {noun}; {cat.unavailable_sentence(capability)}")
        return provider

    # ------------------------------------------------------------------ pictures and clips
    def media_view(self, slot: str) -> dict[str, Any]:
        """The ``[image]`` / ``[video]`` slot as set, and what the slot resolves to today
        (the Models contract §3): the provider id and model in use and where that answer
        came from — ``app`` / ``config`` for a choice, ``chat`` for the chat provider's own
        model, ``cloud`` for the relay."""
        media = getattr(self.settings, slot)
        providers = getattr(self.svc, "providers", None)  # not there while the service starts
        resolved = providers.slots().get(slot) if providers is not None else None
        if resolved is None:
            source = ""
        elif resolved["provider"] == self.CLOUD_PRESET:
            source = "cloud"
        elif media.configured:
            source = "app" if self.data.get(slot) else "config"
        else:
            source = "chat"
        return {
            "provider": media.provider,
            "provider_id": self._catalogue_id(media.provider, media.endpoint),
            "model": media.model,
            "base_url": media.base_url or "",
            "key_source": self._key_source(media.api_key),
            "configured": media.configured,
            "from_app": bool(self.data.get(slot)),
            "effective_provider": resolved["provider"] if resolved else "",
            "effective_model": resolved["model"] if resolved else "",
            "effective_source": source,
        }

    def set_media(self, slot: str, body: dict[str, Any]) -> dict[str, Any]:
        """Where pictures (``image``) or clips (``video``) come from, chosen in the app:
        ``provider`` (a catalogue id, or ``openai`` / ``openai_responses`` with a
        ``base_url``), ``model`` (empty: the catalogue's default), ``base_url`` (for a host
        the catalogue does not list) and ``api_key`` (into the vault; empty: the chat
        model's key when the host is the same). All four empty clears the slot: the chat
        provider's own model again, or the account's."""
        if slot not in _MEDIA_KEYS:
            raise ValueError("slot must be 'image' or 'video'")
        media = dict(self.data.get(slot) or {})
        for key in ("provider", "model", "base_url"):
            if body.get(key) is not None:
                media[key] = str(body[key]).strip()
        if media.get("base_url"):
            media["base_url"] = normalize_base_url(media["base_url"])
        if media.get("provider"):
            media["provider"] = self._check_slot_provider(
                media["provider"], media.get("base_url") or "", slot
            )
        elif media.get("base_url"):
            # a bare URL: the host must not be one the catalogue knows cannot do this
            self._check_slot_provider("openai", media["base_url"], slot)
        vault_name = _MEDIA_KEYS[slot]
        api_key = body.get("api_key")
        if api_key and self.vault.has_placeholders(str(api_key)):
            # a reference to a key already in the vault (the account's, say): kept as written
            media["api_key"] = str(api_key).strip()
        elif api_key:
            self.vault.set(vault_name, str(api_key).strip())
            media["api_key"] = "{{vault:" + vault_name + "}}"
        elif api_key == "":
            self.vault.delete(vault_name)
            media["api_key"] = ""
        if any(media.get(k) for k in ("provider", "model", "base_url", "api_key")):
            self.data[slot] = media
        else:
            self.data.pop(slot, None)
            media = {"provider": "", "model": "", "base_url": "", "api_key": ""}
        self._save()
        apply_app_settings(self.settings, {slot: media})
        self._publish()
        return self.media_view(slot)

    def set_hands(self, body: dict[str, Any]) -> dict[str, Any]:
        """The switch for this computer's own screen and hands, and which backend drives them."""
        hands = dict(self.data.get("hands") or {})
        if body.get("enabled") is not None:
            hands["enabled"] = bool(body["enabled"])
        if body.get("backend") is not None:
            backend = str(body["backend"]).strip().lower() or "auto"
            if backend not in ("auto", "desktop", "pyautogui", "xdotool"):
                raise ValueError("backend must be 'auto', 'desktop', 'pyautogui' or 'xdotool'")
            hands["backend"] = backend
        if body.get("mode") is not None:
            mode = str(body["mode"]).strip().lower() or "auto"
            if mode not in ("auto", "screen", "window"):
                raise ValueError("mode must be 'auto', 'screen' or 'window'")
            hands["mode"] = mode
        self.data["hands"] = hands
        self._save()
        apply_app_settings(self.settings, {"hands": hands})
        computer = self.svc.app.computer
        if computer is not None and "backend" in hands:
            computer.reset_backend()  # picked again on the next action
        if "enabled" in hands:
            self.svc.app.set_hands_enabled(bool(hands["enabled"]))
        operator = getattr(self.svc.app, "computer_operator", None)
        if operator is not None:
            operator.reset_llm()
        self._publish()
        self.svc.publish_hands()
        return self.hands_view()

    def hands_view(self) -> dict[str, Any]:
        computer = self.svc.app.computer
        if computer is None:
            return {"enabled": False, "available": False, "reason": "this runs on a phone"}
        return computer.status()

    async def test_gui(self) -> dict[str, Any]:
        """One tiny call to the operator's model, so a wrong key or model shows up here."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        llm = self.svc.app.make_gui_llm()
        try:
            response = await asyncio.wait_for(
                llm.ask([Message.user("Reply with the single word OK.")], tools=None), timeout=45
            )
        except Exception as exc:  # noqa: BLE001
            return _test_failed(exc)
        finally:
            await llm.close()
        return {
            "ok": True,
            "reply": (response.content or "").strip()[:200],
            "model": self.svc.app.gui_model(),
            "ms": int((loop.time() - started) * 1000),
        }

    # ------------------------------------------------------------------ browser
    def set_browser(self, enabled: bool) -> dict[str, Any]:
        self.data["browser"] = {"enabled": bool(enabled)}
        self._save()
        self.settings.browser.enabled = bool(enabled)
        tools = self.svc.app.tools
        if enabled and "browser" not in tools:
            tools.add(self.svc.app.browser_tool())
            self.svc.watch_browser()
        elif not enabled:
            tools.remove("browser")
        self._publish()
        return self.view()["browser"]

    # ------------------------------------------------------------------ mcp
    async def add_mcp(self, body: dict[str, Any]) -> dict[str, Any]:
        cfg = MCPServerSettings.model_validate(
            {
                k: v
                for k, v in body.items()
                if k
                in ("name", "command", "args", "env", "url", "risk", "egress", "reads_private_data")
            }
        )
        if not cfg.name.strip():
            raise ValueError("the server needs a name")
        if not (cfg.command or cfg.url):
            raise ValueError("give either a command to run or a URL to connect to")
        await self.remove_mcp(cfg.name, save=False)
        servers = [
            m
            for m in (self.data.get("mcp") or {}).get("servers") or []
            if m.get("name") != cfg.name
        ]
        servers.append(cfg.model_dump(mode="json"))
        self.data["mcp"] = {"servers": servers}
        self._save()
        apply_app_settings(self.settings, {"mcp": {"servers": [cfg.model_dump(mode="json")]}})
        manager = MCPManager([cfg])
        tools = await manager.connect()
        if not tools:
            await manager.close()
            self._publish()
            raise RuntimeError(f"could not connect to '{cfg.name}' (see the server log)")
        self._mcp[cfg.name] = manager
        self.svc.app.tools.add(*tools)
        self._publish()
        if cfg.url:
            self._share_connectors()
        return self.view()

    async def remove_mcp(self, name: str, save: bool = True) -> bool:
        servers = (self.data.get("mcp") or {}).get("servers") or []
        known = any(m.get("name") == name for m in servers)
        if save and not known:
            return False
        for t in [t for t in self.svc.app.tools if getattr(t, "server", None) == name]:
            self.svc.app.tools.remove(t.name)
        manager = self._mcp.pop(name, None)
        if manager is not None:
            await manager.close()
        self.settings.mcp.servers = [m for m in self.settings.mcp.servers if m.name != name]
        if save:
            self.data["mcp"] = {"servers": [m for m in servers if m.get("name") != name]}
            self._save()
            self._publish()
            self._share_connectors()
        return True

    async def close(self) -> None:
        for manager in self._mcp.values():
            await manager.close()

    # ------------------------------------------------------------------ vault / onboarding
    def set_secret(self, name: str, value: str) -> list[str]:
        self.vault.set(name, value)
        self._publish()
        return self.vault.names()

    def delete_secret(self, name: str) -> bool:
        ok = self.vault.delete(name)
        if ok:
            self._publish()
        return ok

    def set_onboarded(self, done: bool = True) -> None:
        self.data["onboarded"] = bool(done)
        self._save()
        self._publish()


__all__ = [
    "EMAIL_ADDRESS",
    "EMAIL_PASSWORD",
    "GUI_KEY",
    "IMAGE_KEY",
    "LLM_KEY",
    "PROVIDERS",
    "VIDEO_KEY",
    "Connections",
]
