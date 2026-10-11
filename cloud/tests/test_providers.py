"""The own-key guidance (relay 0.21, contract C11): the catalogue copy is the runtime's,
every provider is well-formed, and the ordering follows the person's region."""

from __future__ import annotations

import json
from pathlib import Path

from nanomuse_cloud import providers as pv

ROOT = Path(__file__).resolve().parents[2]
DOCS = "https://nanomuse.cn/own-key"


def test_catalogue_copy_is_the_runtimes():
    """`node scripts/providers-json.mjs` writes the relay's copy; it must be byte-identical
    to the source of truth (CI runs `--check`, this test says the same from Python)."""
    source = ROOT / "nanomuse" / "llm" / "providers.json"
    if not source.exists():  # the relay installed on its own, without the monorepo
        return
    assert pv.CATALOGUE.read_bytes() == source.read_bytes()


def test_catalogue_shape():
    cat = pv.catalogue()
    ids = [p["id"] for p in cat["providers"]]
    assert len(ids) == len(set(ids))
    for must in ("bailian", "openrouter", "openai", "anthropic", "gemini", "deepseek", "moonshot", "zhipu", "siliconflow", "volcengine", "minimax", "xai", "groq", "mistral", "ollama", "lm-studio", "vllm", "custom"):
        assert must in ids
    for p in cat["providers"]:
        assert "chat" in p["capabilities"]
        assert set(p["capabilities"]) <= set(pv.CAPABILITIES)
        assert set(p["regions"]) <= {"cn", "global"}
        assert p["protocol"] in ("openai", "openai-responses", "anthropic", "gemini")
        assert p["verified"] and p["name"] and p["name_zh"]
        for lane, model in p.get("defaults", {}).items():
            need = "vision" if lane == "hands" else lane
            assert need in p["capabilities"], (p["id"], lane)
            assert isinstance(model, str) and model
    # the ChatGPT sign-in gives less than the key: chat and vision only
    openai = pv.provider("openai")
    assert openai is not None
    assert openai["auth_capabilities"]["oauth-chatgpt"] == ["chat", "vision"]
    assert "image" in openai["capabilities"]
    # Bailian is the one key for all four; the local servers are chat until the model says more
    assert pv.provider("bailian")["capabilities"] == ["chat", "vision", "image", "video"]
    for pid in pv.LOCAL:
        assert pv.provider(pid)["capabilities"] == ["chat"]


def test_guidance_orders_by_region():
    cn = pv.guidance("cn", DOCS)
    assert cn["region"] == "cn" and cn["docs"] == DOCS
    ids = [p["id"] for p in cn["providers"]]
    assert ids[0] == "bailian" and cn["providers"][0]["one_key"] is True
    # the mainland list has only providers that sign up mainland accounts, no local servers, no "custom"
    assert "openai" not in ids and "anthropic" not in ids and "ollama" not in ids and "custom" not in ids
    assert "deepseek" in ids and "zhipu" in ids and "moonshot" in ids
    # the rest by how much the key covers: image providers before chat-only ones
    covers = [len(p["covers"]) for p in cn["providers"][1:]]
    assert covers == sorted(covers, reverse=True)
    # a two-edition provider names its mainland base URL and key page here
    moonshot = next(p for p in cn["providers"] if p["id"] == "moonshot")
    assert moonshot["base_url"] == "https://api.moonshot.cn/v1" and "moonshot.cn" in moonshot["key_url"]

    intl = pv.guidance("intl", DOCS)
    ids = [p["id"] for p in intl["providers"]]
    assert ids[:2] == ["openrouter", "openai"]
    assert "bailian" not in ids and "zhipu" not in ids and "siliconflow" not in ids and "volcengine" not in ids
    assert "anthropic" in ids and "gemini" in ids and "deepseek" in ids
    # OpenCode Go wants a session id per conversation: listed apart, so the apps that do not
    # send one (they read `providers` only) never offer it
    assert "opencode-zen" in ids and "opencode-go" not in ids
    assert [(p["id"], p["session_header"]) for p in intl["session_providers"]] == [("opencode-go", "x-opencode-session")]
    assert pv.guidance("cn", DOCS)["session_providers"] == []
    # …and its global edition elsewhere
    moonshot = next(p for p in intl["providers"] if p["id"] == "moonshot")
    assert moonshot["base_url"] == "https://api.moonshot.ai/v1" and "kimi.ai" in moonshot["key_url"]
    minimax = next(p for p in intl["providers"] if p["id"] == "minimax")
    assert minimax["base_url"] == "https://api.minimax.io/v1"

    unknown = pv.guidance("unknown", DOCS)
    ids = [p["id"] for p in unknown["providers"]]
    assert ids[:2] == ["openrouter", "bailian"]
    assert "openai" in ids and "zhipu" in ids
    # an unexpected region string is treated as unknown
    assert [p["id"] for p in pv.guidance("mars", DOCS)["providers"]] == ids


def test_guidance_plans_and_local():
    g = pv.guidance("intl", DOCS)
    plans = {p["id"]: p for p in g["plans"]}
    assert set(plans) == {"chatgpt", "claude", "kimi", "openrouter"}
    # the ChatGPT sign-in: every client, chat and vision only; the others are the phones'
    assert plans["chatgpt"]["covers"] == ["chat", "vision"] and plans["chatgpt"]["clients"] == ["android", "ios", "desktop", "web"]
    assert plans["claude"]["clients"] == ["android", "ios"] and plans["claude"]["covers"] == ["chat", "vision"]
    assert plans["kimi"]["auth"] == "device-kimi" and plans["openrouter"]["covers"] == ["chat", "vision", "image"]
    assert [p["id"] for p in g["local"]] == ["ollama", "lm-studio", "vllm"]
    assert "OpenCode" in g["caveats"]["chatgpt"] and "OpenCode" in g["caveats"]["chatgpt_zh"]
    # the same plans on the mainland (Kimi and the rest sign people up there too)
    assert {p["id"] for p in pv.guidance("cn", DOCS)["plans"]} == {"chatgpt", "claude", "kimi", "openrouter"}
    # the guidance is plain JSON
    json.dumps(g)


def test_exhausted_key_line():
    cn = pv.exhausted_key_line("cn")
    assert "阿里云百炼" in cn and "one key" in cn and "ChatGPT, Claude or Kimi" in cn and "OpenRouter" not in cn
    intl = pv.exhausted_key_line("intl")
    assert intl.startswith("add your own model key (OpenRouter") and "OpenAI first" in intl and "mainland China" in intl
    unknown = pv.exhausted_key_line("unknown")
    assert "OpenRouter or OpenAI outside mainland China, Alibaba Cloud Bailian inside" in unknown
    assert pv.exhausted_key_line("mars") == unknown
