"""The provider catalogue (contract C11): which own-key providers exist, what each can do.

The source of truth is ``nanomuse/llm/providers.json`` next to this module — team Cloud writes
it, the phone and desktop apps carry copies, the runtime reads it here. Each entry says where
the endpoint is, how a person gets a key, which regions it serves and which of the four
capabilities it has: ``chat`` (talking), ``vision`` (the hands read screens), ``image``
(pictures), ``video`` (clips). The rule every client follows: a feature whose capability no
configured provider has is unavailable *with one sentence*, never a raw error — that sentence
is :meth:`Catalogue.unavailable_sentence`.

Without the file (a trimmed install, an old checkout) a built-in copy of the draft table
stands in, so gating still works; one log line says so.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from loguru import logger

CATALOGUE_FILE = Path(__file__).with_name("providers.json")

CAPABILITIES: tuple[str, ...] = ("chat", "vision", "image", "video")
#: the catalogue's wire protocols → the runtime's ``provider`` setting that speaks them;
#: ``gemini`` is Google's OpenAI-compatible layer, so the chat client does; ``anthropic`` is
#: the Messages API, which the runtime does not speak (OpenRouter carries Claude in the
#: OpenAI shape)
PROTOCOL_PROVIDERS: dict[str, str] = {
    "openai": "openai",
    "openai-responses": "openai_responses",
    "gemini": "openai",
}
#: the ChatGPT sign-in: ``auth`` kind in the catalogue, ``provider`` value in the config
CHATGPT_AUTH = "oauth-chatgpt"
CHATGPT_PROVIDER = "chatgpt"
#: what the account's model is called when it stands in a provider list
CLOUD_PROVIDER = "nanomuse_cloud"

# What the sentence calls each capability, and the verb phrase after it
_NOUNS = {
    "en": {
        "chat": ("Chat", "a provider with chat models"),
        "vision": ("Hands", "a provider with models that read pictures"),
        "image": ("Pictures", "a provider with image models"),
        "video": ("Clips", "a provider with video models"),
    },
    "zh": {
        "chat": ("对话", "有对话模型的服务商"),
        "vision": ("手", "有能看图的模型的服务商"),
        "image": ("生成图片", "有图像模型的服务商"),
        "video": ("生成视频", "有视频模型的服务商"),
    },
}
_HOW = {"en": "how: docs/own-key.md", "zh": "方法见 docs/own-key.md"}
#: how many providers a sentence names before it stops
_NAMED = 4


@dataclass
class Provider:
    """One catalogue entry; the fields mirror the JSON."""

    id: str
    name: str
    name_zh: str = ""
    protocol: str = "openai"
    base_url: str = ""
    base_url_global: str = ""
    key_url: str = ""
    key_url_global: str = ""
    key_hint: str = ""
    auth: list[str] = field(default_factory=lambda: ["key"])
    #: capabilities an auth kind narrows the provider to (the ChatGPT sign-in: chat + vision)
    auth_capabilities: dict[str, list[str]] = field(default_factory=dict)
    regions: list[str] = field(default_factory=lambda: ["cn", "global"])
    capabilities: list[str] = field(default_factory=lambda: ["chat"])
    defaults: dict[str, str] = field(default_factory=dict)
    note: str = ""
    note_zh: str = ""
    verified: str = ""
    #: the person says what the endpoint can do (the `custom` row)
    user_capabilities: bool = False
    #: the header the vendor's docs want one stable id per conversation in (OpenCode Go:
    #: ``x-opencode-session``); empty for the vendors that ask for none
    session_header: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Provider | None:
        pid = str(raw.get("id") or "").strip()
        if not pid:
            return None
        known = {f for f in cls.__dataclass_fields__}
        data: dict[str, Any] = {}
        for key, value in raw.items():
            if key not in known or value is None:
                continue
            if isinstance(value, list):
                data[key] = [str(v) for v in value]
            elif isinstance(value, dict):
                data[key] = {
                    str(k): [str(x) for x in v] if isinstance(v, list) else str(v)
                    for k, v in value.items()
                }
            elif isinstance(value, bool):
                data[key] = value
            else:
                data[key] = str(value)
        data["id"] = pid
        data.setdefault("name", pid)
        return cls(**data)

    def label(self, lang: str = "en") -> str:
        return (self.name_zh or self.name) if lang == "zh" else self.name

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    def serves(self, region: str) -> bool:
        return not region or region in self.regions

    def capabilities_with(self, auth: str) -> list[str]:
        """The capabilities under one auth kind: the entry's, narrowed where the JSON says."""
        narrowed = self.auth_capabilities.get(auth)
        return list(narrowed) if narrowed is not None else list(self.capabilities)

    def hosts(self) -> set[str]:
        out = set()
        for url in (self.base_url, self.base_url_global):
            host = (urlparse(url).hostname or "").lower() if url else ""
            if host:
                out.add(host)
        return out

    def urls(self) -> set[str]:
        out = set()
        for url in (self.base_url, self.base_url_global):
            if url:
                out.add(url.rstrip("/"))
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "name_zh": self.name_zh,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "base_url_global": self.base_url_global,
            "key_url": self.key_url,
            "key_url_global": self.key_url_global,
            "key_hint": self.key_hint,
            "auth": list(self.auth),
            "auth_capabilities": {k: list(v) for k, v in self.auth_capabilities.items()},
            "regions": list(self.regions),
            "capabilities": list(self.capabilities),
            "defaults": dict(self.defaults),
            "note": self.note,
            "note_zh": self.note_zh,
            "verified": self.verified,
            "user_capabilities": self.user_capabilities,
            "session_header": self.session_header,
        }


@dataclass
class Catalogue:
    providers: list[Provider]
    version: int = 1
    updated: str = ""
    #: where it came from: the file's path, or "built-in" for the fallback table
    source: str = ""

    def get(self, provider_id: str) -> Provider | None:
        for p in self.providers:
            if p.id == provider_id:
                return p
        return None

    def ids(self) -> list[str]:
        return [p.id for p in self.providers]

    def by_base_url(self, base_url: str | None) -> Provider | None:
        """The entry whose endpoint is the address (either edition); the host alone when the
        address is not one, so a key pasted with or without ``/v1`` still finds its vendor;
        None for a host nobody lists — a gateway, a relay, a server of one's own. Two
        entries on one host are told apart by the whole address."""
        url = (base_url or "").strip().rstrip("/")
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return None
        for p in self.providers:
            if url in p.urls():
                return p
        for p in self.providers:
            if host in p.hosts():
                return p
        # a subdomain of a listed host (regional endpoints such as dashscope-intl)
        for p in self.providers:
            if any(host.endswith("." + h.split(".", 1)[-1]) for h in p.hosts() if "." in h):
                return p
        return None

    def providers_for(self, capability: str, region: str = "") -> list[Provider]:
        """The entries with the capability that serve the region (all regions when empty),
        in catalogue order; local servers and the custom row are left out — they only have
        what the person installs."""
        return [
            p
            for p in self.providers
            if p.has(capability)
            and p.serves(region)
            and not p.user_capabilities
            and p.hosts()
            and not p.hosts() & {"127.0.0.1", "localhost"}
        ]

    def capabilities(self, provider_ids: Iterable[str]) -> set[str]:
        """The union of what the named providers can do. ``chatgpt`` is the ChatGPT sign-in
        (chat and vision); ``nanomuse_cloud`` is the account (everything the relay serves,
        counted by the caller); ids the catalogue does not know add nothing."""
        out: set[str] = set()
        for pid in provider_ids:
            if pid == CHATGPT_PROVIDER:
                openai = self.get("openai")
                out |= set(openai.capabilities_with(CHATGPT_AUTH)) if openai else {"chat", "vision"}
                continue
            p = self.get(pid)
            if p is not None:
                out |= set(p.capabilities)
        return out

    def unavailable_sentence(self, capability: str, region: str = "", lang: str = "en") -> str:
        """The one sentence a client shows for a feature nobody configured can do, e.g.
        *Pictures need a provider with image models: OpenRouter, OpenAI, Google Gemini or
        xAI Grok (how: docs/own-key.md).*"""
        lang = "zh" if str(lang).lower().startswith("zh") else "en"
        noun, need = _NOUNS[lang].get(capability) or (capability, _NOUNS[lang]["chat"][1])
        names = [p.label(lang) for p in self.providers_for(capability, region)]
        if not names and region:
            names = [p.label(lang) for p in self.providers_for(capability)]
        shown = names[:_NAMED]
        if lang == "zh":
            if not shown:
                return f"{noun}需要{need}，目前没有可用的（{_HOW['zh']}）。"
            listed = "、".join(shown[:-1]) + ("或" if len(shown) > 1 else "") + shown[-1]
            return f"{noun}需要{need}：{listed}（{_HOW['zh']}）。"
        if not shown:
            return f"{noun} need {need}; none is available ({_HOW['en']})."
        listed = ", ".join(shown[:-1]) + (" or " if len(shown) > 1 else "") + shown[-1]
        verb = "needs" if noun == "Chat" else "need"
        return f"{noun} {verb} {need}: {listed} ({_HOW['en']})."

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated": self.updated,
            "capabilities": list(CAPABILITIES),
            "providers": [p.to_dict() for p in self.providers],
        }


# The draft table from the shared brief: enough to gate and to name providers when the
# JSON is not there. The file, when present, wins in every detail.
_FALLBACK: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    # id, name, name_zh, base_url, regions, capabilities, protocol
    ("bailian", "Alibaba Cloud Bailian", "阿里云百炼", "https://dashscope.aliyuncs.com/compatible-mode/v1", "cn", "chat vision image video", "openai"),
    ("deepseek", "DeepSeek", "DeepSeek", "https://api.deepseek.com/v1", "cn global", "chat vision", "openai"),
    ("moonshot", "Kimi (Moonshot AI)", "Kimi（月之暗面）", "https://api.moonshot.cn/v1", "cn global", "chat vision", "openai"),
    ("zhipu", "Zhipu GLM", "智谱 GLM", "https://open.bigmodel.cn/api/paas/v4", "cn", "chat vision image", "openai"),
    ("siliconflow", "SiliconFlow", "硅基流动", "https://api.siliconflow.cn/v1", "cn", "chat vision image", "openai"),
    ("volcengine", "Volcengine Ark (Doubao)", "火山方舟（豆包）", "https://ark.cn-beijing.volces.com/api/v3", "cn", "chat vision image", "openai"),
    ("minimax", "MiniMax", "MiniMax", "https://api.minimaxi.com/v1", "cn global", "chat vision", "openai"),
    ("openrouter", "OpenRouter", "OpenRouter", "https://openrouter.ai/api/v1", "global", "chat vision image", "openai"),
    ("openai", "OpenAI", "OpenAI", "https://api.openai.com/v1", "global", "chat vision image", "openai"),
    ("anthropic", "Anthropic Claude", "Anthropic Claude", "https://api.anthropic.com", "global", "chat vision", "anthropic"),
    ("gemini", "Google Gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "global", "chat vision image", "gemini"),
    ("xai", "xAI Grok", "xAI Grok", "https://api.x.ai/v1", "global", "chat vision image", "openai"),
    ("groq", "Groq", "Groq", "https://api.groq.com/openai/v1", "global", "chat vision", "openai"),
    ("mistral", "Mistral AI", "Mistral AI", "https://api.mistral.ai/v1", "global", "chat vision", "openai"),
)  # fmt: skip


def _fallback() -> Catalogue:
    providers = [
        Provider(
            id=pid,
            name=name,
            name_zh=name_zh,
            protocol=protocol,
            base_url=base_url,
            regions=regions.split(),
            capabilities=caps.split(),
            auth=["key", CHATGPT_AUTH] if pid == "openai" else ["key"],
            auth_capabilities={CHATGPT_AUTH: ["chat", "vision"]} if pid == "openai" else {},
        )
        for pid, name, name_zh, base_url, regions, caps, protocol in _FALLBACK
    ]
    for local in ("ollama", "lm-studio", "vllm"):
        providers.append(
            Provider(id=local, name=local, protocol="openai", auth=["none"], capabilities=["chat"])
        )
    providers.append(
        Provider(
            id="custom",
            name="Any OpenAI-compatible endpoint",
            name_zh="任何 OpenAI 兼容接口",
            auth=["key", "none"],
            capabilities=["chat"],
            user_capabilities=True,
        )
    )
    return Catalogue(providers=providers, source="built-in")


def parse(data: dict[str, Any], source: str = "") -> Catalogue:
    providers = []
    for raw in data.get("providers") or []:
        if isinstance(raw, dict) and (p := Provider.from_dict(raw)) is not None:
            providers.append(p)
    if not providers:
        raise ValueError("no providers")
    return Catalogue(
        providers=providers,
        version=int(data.get("version") or 1),
        updated=str(data.get("updated") or ""),
        source=source,
    )


def load_file(path: Path) -> Catalogue:
    """The catalogue at ``path``; the built-in table (with one log line) when the file is
    missing or unreadable."""
    try:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return parse(data, source=str(path))
    except FileNotFoundError:
        logger.info("provider catalogue {} not found; using the built-in table", path)
    except (OSError, ValueError) as exc:
        logger.warning("provider catalogue {} unreadable ({}); using the built-in table", path, exc)
    return _fallback()


@lru_cache(maxsize=1)
def load() -> Catalogue:
    """The packaged catalogue, read once per process."""
    return load_file(CATALOGUE_FILE)


def protocol_provider(protocol: str) -> str | None:
    """The runtime's ``provider`` value for a catalogue protocol; None when the runtime does
    not speak it."""
    return PROTOCOL_PROVIDERS.get(protocol)


__all__ = [
    "CAPABILITIES",
    "CATALOGUE_FILE",
    "CHATGPT_AUTH",
    "CHATGPT_PROVIDER",
    "CLOUD_PROVIDER",
    "Catalogue",
    "Provider",
    "load",
    "load_file",
    "parse",
    "protocol_provider",
]
