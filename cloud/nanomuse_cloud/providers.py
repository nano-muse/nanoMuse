"""The own-key guidance (relay 0.21, contract C11): which providers a person can bring a key
from, what each one covers, and which paid plans an app can sign in with instead.

The facts come from the catalogue `providers.json` next to this file — a copy of the
runtime's `nanomuse/llm/providers.json`, written by `node scripts/providers-json.mjs` and
checked by CI, never edited here. The relay only orders it for the person's region and
adds the sign-in flows; the apps draw the card from it and the text is theirs (every
locale). The shape is additive next to the 0.17 `ways`, which keep their ids and fields.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOGUE = Path(__file__).with_name("providers.json")

# What each capability lets the app do, in the order the cards list them.
CAPABILITIES = ("chat", "vision", "image", "video")

# Who goes first when the allowance is spent: the mainland to Bailian (one key for all
# four), everyone else to OpenRouter or OpenAI; `unknown` leads with the two that work
# anywhere a card is accepted, Bailian next for a mainland reader.
FIRST = {"cn": ("bailian",), "intl": ("openrouter", "openai"), "unknown": ("openrouter", "bailian")}

# Providers that run on the person's own machine: listed apart, never "first".
LOCAL = ("ollama", "lm-studio", "vllm")

# A plan a person may already pay for, and which app can sign in with it (the phones carry
# OpenMinis' OAuth / device-code flows; the desktop and the web console get the ChatGPT
# sign-in through the runtime's `nanomuse chatgpt login` in 0.1.39). `covers` is what the
# sign-in gives — less than a key where the backend has fewer endpoints.
PLANS = (
    {"id": "chatgpt", "provider": "openai", "name": "ChatGPT", "auth": "oauth-chatgpt", "clients": ["android", "ios", "desktop", "web"]},
    {"id": "claude", "provider": "anthropic", "name": "Claude", "auth": "oauth-claude", "clients": ["android", "ios"]},
    {"id": "kimi", "provider": "moonshot", "name": "Kimi", "auth": "device-kimi", "clients": ["android", "ios"]},
    {"id": "openrouter", "provider": "openrouter", "name": "OpenRouter", "auth": "oauth-openrouter", "clients": ["android", "ios"]},
)

# The honest line about the ChatGPT sign-in, for the apps that have no copy of their own.
CHATGPT_CAVEAT = (
    "OpenAI's terms cover using a ChatGPT plan inside OpenAI's own Codex; other apps have had "
    "this access cut off before (OpenCode, January 2026). If it stops working, an API key does."
)
CHATGPT_CAVEAT_ZH = "OpenAI 的条款只允许在它自己的 Codex 里使用 ChatGPT 订阅；其他应用的这条路曾被切断过（OpenCode，2026 年 1 月）。如果哪天不能用了，API key 还能用。"


@lru_cache(maxsize=1)
def catalogue() -> dict[str, Any]:
    """The catalogue as shipped (`{version, updated, providers[]}`); read once."""
    return json.loads(CATALOGUE.read_text(encoding="utf-8"))


def provider(pid: str) -> dict[str, Any] | None:
    for p in catalogue()["providers"]:
        if p["id"] == pid:
            return p
    return None


def _public(p: dict[str, Any], region: str) -> dict[str, Any]:
    """One provider as the apps see it: the id, the names, where the key comes from, what
    the key covers, which sign-ins it has, where it signs people up. For a provider with
    two editions the region's base URL and key page are the ones named."""
    global_edition = region == "intl" and "global" in p["regions"] and p.get("base_url_global")
    return {
        "id": p["id"],
        "name": p["name"],
        "name_zh": p["name_zh"],
        "protocol": p["protocol"],
        "base_url": p["base_url_global"] if global_edition else p["base_url"],
        "key_url": p.get("key_url_global") or p["key_url"] if global_edition else p["key_url"],
        "auth": list(p["auth"]),
        "regions": list(p["regions"]),
        "covers": [c for c in CAPABILITIES if c in p["capabilities"]],
        "defaults": dict(p.get("defaults") or {}),
        "one_key": all(c in p["capabilities"] for c in CAPABILITIES),
        "note": p.get("note", ""),
        "note_zh": p.get("note_zh", ""),
    }


def _fits(p: dict[str, Any], region: str) -> bool:
    """Whether a provider signs people up where this person is: `cn` wants a mainland
    edition, `intl` one that takes anyone, `unknown` takes every provider."""
    if region == "cn":
        return "cn" in p["regions"]
    if region == "intl":
        return "global" in p["regions"]
    return True


def guidance(region: str, docs_url: str) -> dict[str, Any]:
    """The card's facts for one person: the region, the providers for it in order (the
    region's first picks, then the rest by how much they cover), the plans an app can sign
    in with, the local servers, the guide's URL and the ChatGPT caveat."""
    cat = catalogue()
    by_id = {p["id"]: p for p in cat["providers"]}
    first = [pid for pid in FIRST.get(region, FIRST["unknown"]) if pid in by_id and _fits(by_id[pid], region)]
    # a vendor that wants a session id per conversation (`session_header`, OpenCode Go) is left
    # out: the phones read this list, and their provider clients do not send one
    rest = [p for p in cat["providers"] if p["id"] not in first and p["id"] not in LOCAL and p["id"] != "custom" and not p.get("session_header") and _fits(p, region)]
    # the rest grouped by what they can do: the fuller key first, the catalogue's order within
    rest.sort(key=lambda p: -len(p["capabilities"]))
    providers = [_public(by_id[pid], region) for pid in first] + [_public(p, region) for p in rest]
    plans = []
    for plan in PLANS:
        p = by_id.get(plan["provider"])
        if p is None or plan["auth"] not in p["auth"]:
            continue
        covers = (p.get("auth_capabilities") or {}).get(plan["auth"]) or p["capabilities"]
        plans.append(
            {
                "id": plan["id"],
                "provider": plan["provider"],
                "name": plan["name"],
                "auth": plan["auth"],
                "clients": list(plan["clients"]),
                "covers": [c for c in CAPABILITIES if c in covers],
            }
        )
    return {
        "version": cat.get("version", 1),
        "updated": cat.get("updated", ""),
        "region": region,
        "docs": docs_url,
        "providers": providers,
        "plans": plans,
        "local": [_public(by_id[pid], region) for pid in LOCAL if pid in by_id],
        "caveats": {"chatgpt": CHATGPT_CAVEAT, "chatgpt_zh": CHATGPT_CAVEAT_ZH},
    }


def exhausted_key_line(region: str) -> str:
    """The "own key" half of the `allowance_exhausted` message, for the apps of before 0.1.39
    that print the relay's sentence as it is."""
    if region == "cn":
        return (
            "add your own model key (Alibaba Cloud Bailian, 阿里云百炼, covers chat, hands, pictures and clips "
            "with one key and has a free tier for mainland China accounts; DeepSeek, Kimi, Zhipu, SiliconFlow, "
            "Volcengine and MiniMax work too, for chat and hands, and some draw pictures), or sign in with a plan you "
            "already pay for (ChatGPT, Claude or Kimi, where the app has the sign-in)"
        )
    if region == "intl":
        return (
            "add your own model key (OpenRouter, with one account, one key and pay as you go, or OpenAI first; "
            "Anthropic, Gemini, xAI, Groq, Mistral, DeepSeek, Kimi and MiniMax work too, each covering what its "
            "models can do), or sign in with a plan you already pay for (ChatGPT, Claude or Kimi, where the app "
            "has the sign-in); Alibaba Cloud Bailian only signs up accounts from mainland China"
        )
    return (
        "add your own model key (OpenRouter or OpenAI outside mainland China, Alibaba Cloud Bailian inside, "
        "or any of the providers the app lists with what each covers), or sign in with a plan you already "
        "pay for (ChatGPT, Claude or Kimi, where the app has the sign-in)"
    )
