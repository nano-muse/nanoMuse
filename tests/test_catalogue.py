"""The provider catalogue (contract C11): the packaged file, who covers what, the sentences."""

from __future__ import annotations

from pathlib import Path

from nanomuse.config import LLMSettings, check_provider, resolve_provider
from nanomuse.llm import catalogue
from nanomuse.llm.factory import create_llm


def test_the_packaged_file_is_read_once_and_has_the_twenty_providers():
    cat = catalogue.load()
    assert cat.source.endswith("providers.json")
    assert len(cat.providers) == 20
    assert cat.get("bailian").capabilities == ["chat", "vision", "image", "video"]
    assert cat.get("nowhere") is None
    # the same object on every call
    assert catalogue.load() is cat


def test_providers_for_a_capability_in_a_region_keeps_the_catalogue_order():
    cat = catalogue.load()
    assert [p.id for p in cat.providers_for("image", "cn")] == [
        "bailian",
        "zhipu",
        "siliconflow",
        "volcengine",
    ]
    assert [p.id for p in cat.providers_for("video", "global")] == []
    # local servers and the custom row never stand in for a provider
    assert all(
        p.id not in ("ollama", "lm-studio", "vllm", "custom") for p in cat.providers_for("chat")
    )


def test_the_unavailable_sentence_in_english_and_chinese():
    cat = catalogue.load()
    assert cat.unavailable_sentence("image", "global", "en") == (
        "Pictures need a provider with image models: OpenRouter, OpenAI, Google Gemini or "
        "xAI Grok (how: docs/own-key.md)."
    )
    assert cat.unavailable_sentence("image", "cn", "zh") == (
        "生成图片需要有图像模型的服务商：阿里云百炼、智谱 GLM、硅基流动或火山方舟（豆包）"
        "（方法见 docs/own-key.md）。"
    )
    # one provider: no "or"
    assert cat.unavailable_sentence("video", "global", "en") == (
        "Clips need a provider with video models: Alibaba Cloud Bailian (how: docs/own-key.md)."
    )
    # a region with nobody falls back to every region rather than naming no one
    assert "Bailian" in cat.unavailable_sentence("video", "global", "en")
    # zh-CN, zh_TW and the like are Chinese
    assert cat.unavailable_sentence("vision", "", "zh-CN").startswith("手需要")


def test_by_base_url_finds_the_entry_for_a_host_or_nothing():
    cat = catalogue.load()
    assert cat.by_base_url("https://api.deepseek.com").id == "deepseek"
    assert cat.by_base_url("https://dashscope.aliyuncs.com/compatible-mode/v1").id == "bailian"
    assert cat.by_base_url("https://gateway.example.net/v1") is None
    assert cat.by_base_url("") is None
    # two editions on one host are told apart by the whole address, the host is only the fallback
    assert cat.by_base_url("https://opencode.ai/zen/v1").id == "opencode-zen"
    assert cat.by_base_url("https://opencode.ai/zen/go/v1").id == "opencode-go"
    assert cat.by_base_url("https://opencode.ai/zen/go/v1/").id == "opencode-go"


def test_the_chatgpt_sign_in_maps_to_the_chatgpt_provider_with_chat_and_vision(tmp_path: Path):
    cat = catalogue.load()
    openai = cat.get("openai")
    assert catalogue.CHATGPT_AUTH in openai.auth
    assert openai.capabilities_with(catalogue.CHATGPT_AUTH) == ["chat", "vision"]
    assert cat.capabilities([catalogue.CHATGPT_PROVIDER]) == {"chat", "vision"}
    assert cat.capabilities(["openai"]) == {"chat", "vision", "image"}
    # the config accepts it as a provider, with no endpoint of its own and Codex's model
    assert check_provider("chatgpt") == "chatgpt"
    assert resolve_provider("chatgpt", None) == ("chatgpt", None)
    settings = LLMSettings(provider="chatgpt")
    assert settings.base_url is None and settings.model == ""
    llm = create_llm(settings, data_dir=tmp_path)
    # tool_mode "auto" wraps the client in the prompt-tools adapter, as for every provider
    inner = getattr(llm, "inner", llm)
    assert type(inner).__name__ == "CodexLLM"
    assert inner.model == "gpt-5.6-sol"


def test_a_catalogue_id_as_provider_brings_its_protocol_and_endpoint():
    assert check_provider("bailian") == "bailian"
    assert resolve_provider("bailian", None) == (
        "openai",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    settings = LLMSettings(provider="bailian")
    assert settings.protocol == "openai"
    assert settings.endpoint == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings.model == catalogue.load().get("bailian").defaults["chat"]


def test_a_missing_file_falls_back_to_the_built_in_table(tmp_path: Path):
    cat = catalogue.load_file(tmp_path / "nothing.json")
    assert cat.source == "built-in"
    assert cat.get("bailian") is not None
    assert cat.get("openai").capabilities_with(catalogue.CHATGPT_AUTH) == ["chat", "vision"]
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert catalogue.load_file(broken).source == "built-in"
