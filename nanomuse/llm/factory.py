"""Build the configured LLM."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from nanomuse.config import CHATGPT_PROVIDER, LLMSettings, resolve_provider
from nanomuse.llm.base import BaseLLM
from nanomuse.llm.openai_chat import OpenAIChatLLM
from nanomuse.llm.openai_responses import OpenAIResponsesLLM
from nanomuse.llm.prompt_tools import PromptToolAdapter

if TYPE_CHECKING:
    from nanomuse.vault.vault import CredentialVault


def create_llm(settings: LLMSettings, data_dir: Path | None = None) -> BaseLLM:
    """The client for a model slot. ``provider`` is a protocol (``openai``,
    ``openai_responses``), ``chatgpt`` (the sign-in; ``data_dir`` says where its token store
    is) or a catalogue id, which resolves to a protocol and the entry's endpoint."""
    protocol, base_url = resolve_provider(settings.provider, settings.base_url)
    if protocol == CHATGPT_PROVIDER:
        from nanomuse.llm.codex import CodexLLM

        llm: BaseLLM = CodexLLM(settings, data_dir=data_dir)
    else:
        if base_url != settings.base_url:
            settings = settings.model_copy(update={"base_url": base_url})
        header = session_header(settings.provider, settings.base_url)
        if protocol == "openai":
            llm = OpenAIChatLLM(settings, session_header=header)
        elif protocol == "openai_responses":
            llm = OpenAIResponsesLLM(settings, session_header=header)
        else:  # pragma: no cover - guarded by the provider validator
            raise ValueError(f"unknown llm provider: {settings.provider}")
    if settings.tool_mode == "prompt":
        llm = PromptToolAdapter(llm)
    elif settings.tool_mode == "auto":
        llm = PromptToolAdapter(llm, native_first=True)
    return llm


def session_header(provider: str, base_url: str | None) -> str:
    """The header the slot's vendor wants a conversation id in: the entry whose endpoint the
    slot's address is (an OpenAI-shaped slot pointed at OpenCode Go sends it too), else the
    entry the slot names; empty for every other vendor."""
    from nanomuse.llm import catalogue

    cat = catalogue.load()
    entry = cat.by_base_url(base_url) or cat.get(provider)
    return entry.session_header if entry is not None else ""


def is_local_endpoint(base_url: str | None) -> bool:
    """A model served on this machine (Ollama, vLLM, LM Studio) needs no key."""
    host = (urlparse(base_url or "").hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal")


def llm_ready(
    settings: LLMSettings, vault: CredentialVault | None = None, data_dir: Path | None = None
) -> bool:
    """Can the slot answer a request: a key is set (a ``{{vault:NAME}}`` placeholder counts
    when the vault has it), a ChatGPT sign-in is stored, or the endpoint is local.

    Every screen that says "add a model first" asks this one question, so the app's stored
    key, the Cloud key and a signed-in ChatGPT read as ready everywhere.
    """
    protocol, base_url = resolve_provider(settings.provider, settings.base_url)
    if protocol == CHATGPT_PROVIDER:
        from nanomuse.llm.chatgpt import TokenStore

        return data_dir is not None and TokenStore.in_dir(data_dir).load() is not None
    if is_local_endpoint(base_url):
        return True
    key = settings.api_key
    if not key:
        return False
    if vault is not None and vault.has_placeholders(key):
        from nanomuse.vault.vault import VaultError

        try:
            key = vault.resolve(key, strict=False)
        except VaultError:  # the vault cannot be read (wrong key file): not ready, not a crash
            return False
        return bool(key) and not vault.has_placeholders(key)
    return True


__all__ = ["create_llm", "is_local_endpoint", "llm_ready", "session_header"]
