"""Contract C4: one model for the chat, one for the hands; what an id says about pictures."""

from __future__ import annotations

from pathlib import Path

from nanomuse.app import NanoMuseApp
from nanomuse.cloud import CLOUD_KEY, DEFAULT_CHAT_MODEL, DEFAULT_GUI_MODEL, model_url
from nanomuse.config import LLMSettings, Settings
from nanomuse.llm.mock import MockLLM
from nanomuse.llm.openai_chat import OpenAIChatLLM
from nanomuse.llm.vision import model_takes_images
from nanomuse.server.connections import PROVIDERS
from tests.test_phone import AutoApproveUI


def test_model_ids_say_whether_they_see():
    assert model_takes_images("deepseek-chat") is False
    assert model_takes_images("deepseek-reasoner") is False
    assert model_takes_images("deepseek-v4.1-flash") is True
    assert model_takes_images("deepseek/deepseek-v4.1-flash") is True
    # the Flash line is served by V4.1-Flash, which sees; Pro does not
    assert model_takes_images("deepseek-flash") is True
    assert model_takes_images("deepseek-v4-flash") is True
    assert model_takes_images("deepseek-v4-flash-vision-exp") is True
    assert model_takes_images("deepseek-v4-pro") is False
    assert (
        model_takes_images("deepseek-vision") is True and model_takes_images("deepseek-ocr") is True
    )
    assert model_takes_images("qwen3-vl-plus") is True
    assert (
        model_takes_images("qwen/qwen3.8-27b") is True
        and model_takes_images("qwen3.8-flash") is True
    )
    assert model_takes_images("qwen3.7-plus") is None  # not known from the id: the endpoint decides
    assert model_takes_images("gpt-5-mini") is None and model_takes_images("") is None


def test_chat_client_starts_with_what_the_id_says():
    blind = OpenAIChatLLM(LLMSettings(api_key="k", base_url="http://x/v1", model="deepseek-chat"))
    assert blind.vision_available is False
    sighted = OpenAIChatLLM(LLMSettings(api_key="k", base_url="http://x/v1", model="qwen3.8-27b"))
    assert sighted.vision_available is True
    unknown = OpenAIChatLLM(LLMSettings(api_key="k", base_url="http://x/v1", model="gpt-5-mini"))
    assert unknown.vision_available is None
    # the user's own word stands: "on" is tried even for a DeepSeek chat id
    forced = OpenAIChatLLM(
        LLMSettings(api_key="k", base_url="http://x/v1", model="deepseek-chat", vision="on")
    )
    assert forced.vision_available is None


def test_defaults_and_presets():
    assert DEFAULT_CHAT_MODEL == "deepseek-v4.1-flash-1017"
    assert DEFAULT_GUI_MODEL == "qwen3.5-397b-a17b"
    bailian, openrouter = PROVIDERS["qwen"], PROVIDERS["openrouter"]
    assert bailian["models"][0] == "deepseek-v4.1-flash" and bailian["gui_model"] == "qwen3.8-27b"
    assert bailian["region"] == "cn"
    assert openrouter["models"][0] == "deepseek/deepseek-v4.1-flash"
    assert openrouter["gui_model"] == "qwen/qwen3.8-27b"
    assert openrouter["key_url"] == "https://openrouter.ai/keys"
    assert openrouter["base_url"] == "https://openrouter.ai/api/v1"


def test_hands_model_follows_the_account(settings: Settings):
    app = NanoMuseApp(settings, ui=AutoApproveUI(), llm=MockLLM([]))  # type: ignore[arg-type]
    # own key, nothing under [gui]: the hands use the chat model
    assert not app.llm_is_cloud() and app.gui_model() == settings.llm.model
    # the account as the model: the relay's hands model, not the chat one
    settings.llm.base_url = model_url(settings.cloud.base_url)
    assert app.llm_is_cloud() and app.gui_model() == DEFAULT_GUI_MODEL
    app.cloud_gui_model = "qwen3.9-vl"  # what the relay's `for` field said
    assert app.gui_model() == "qwen3.9-vl"
    assert app.make_gui_llm().settings.model == "qwen3.9-vl"  # type: ignore[attr-defined]
    # [gui] model wins; default_only still says what it would be
    settings.gui.model = "my-vl"
    assert app.gui_model() == "my-vl" and app.gui_model(default_only=True) == "qwen3.9-vl"
    # the Cloud key in the vault marks the account too
    settings.llm.base_url = "https://elsewhere.example/v1"
    settings.llm.api_key = "{{vault:" + CLOUD_KEY + "}}"
    assert app.llm_is_cloud()


def test_hands_model_shares_the_chat_models_proxy(settings: Settings):
    settings.llm.proxy = "http://127.0.0.1:7890"
    app = NanoMuseApp(settings, ui=AutoApproveUI(), llm=MockLLM([]))  # type: ignore[arg-type]
    # same host as the chat model: reached the same way
    assert app.make_gui_llm().settings.proxy == "http://127.0.0.1:7890"  # type: ignore[attr-defined]
    # a [gui] model on its own host is not sent through the chat model's proxy
    settings.gui.model = "my-vl"
    settings.gui.base_url = "https://vision.example/v1"
    settings.gui.api_key = "k"
    assert app.make_gui_llm().settings.proxy == ""  # type: ignore[attr-defined]


def test_llm_ready_reads_the_vault_and_the_sign_in(settings: Settings, tmp_path: Path):
    from nanomuse.llm.chatgpt import Token, TokenStore
    from nanomuse.llm.factory import llm_ready
    from nanomuse.vault import CredentialVault

    vault = CredentialVault(tmp_path / "v.json", tmp_path / "v.key")
    llm = LLMSettings(api_key="")
    assert llm_ready(llm, vault, tmp_path) is False
    assert llm_ready(LLMSettings(api_key="sk-literal"), vault, tmp_path) is True
    # the app stores keys as placeholders: ready once the vault has the secret
    stored = LLMSettings(api_key="{{vault:LLM_API_KEY}}")
    assert llm_ready(stored, vault, tmp_path) is False
    vault.set("LLM_API_KEY", "sk-real")
    assert llm_ready(stored, vault, tmp_path) is True
    # a local server needs no key; a ChatGPT sign-in is a key of its own
    assert llm_ready(LLMSettings(base_url="http://localhost:11434/v1"), vault, tmp_path) is True
    assert llm_ready(LLMSettings(base_url="http://127.0.0.1:8000/v1"), vault, tmp_path) is True
    assert (
        llm_ready(LLMSettings(base_url="http://notlocalhost.example/v1"), vault, tmp_path) is False
    )
    chatgpt = LLMSettings(provider="chatgpt")
    assert llm_ready(chatgpt, vault, tmp_path) is False
    TokenStore.in_dir(tmp_path).save(Token(access="a", refresh="r", expires_at=0, account_id="x"))
    assert llm_ready(chatgpt, vault, tmp_path) is True
