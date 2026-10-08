from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from nanomuse.vault import CredentialVault
from nanomuse.vault.vault import VaultError


def test_vault_roundtrip(tmp_path: Path):
    vault = CredentialVault(tmp_path / "vault.enc", tmp_path / "vault.key")
    vault.set("EMAIL_PASSWORD", "hunter2-secret")
    assert vault.get("EMAIL_PASSWORD") == "hunter2-secret"
    assert vault.names() == ["EMAIL_PASSWORD"]
    # file on disk is encrypted
    assert b"hunter2" not in (tmp_path / "vault.enc").read_bytes()
    if os.name != "nt":
        mode = stat.S_IMODE((tmp_path / "vault.key").stat().st_mode)
        assert mode == 0o600
    # fresh instance with same key can read it
    again = CredentialVault(tmp_path / "vault.enc", tmp_path / "vault.key")
    assert again.get("EMAIL_PASSWORD") == "hunter2-secret"
    assert again.delete("EMAIL_PASSWORD")
    assert again.get("EMAIL_PASSWORD") is None


def test_resolve_and_redact(tmp_path: Path):
    vault = CredentialVault(tmp_path / "v.enc", tmp_path / "v.key")
    vault.set("TOKEN", "tok-1234567890")
    resolved = vault.resolve(
        {"headers": {"Authorization": "Bearer {{vault:TOKEN}}"}, "list": ["{{ vault:TOKEN }}"]}
    )
    assert resolved["headers"]["Authorization"] == "Bearer tok-1234567890"
    assert resolved["list"] == ["tok-1234567890"]
    assert vault.redact("leak tok-1234567890 here") == "leak [REDACTED:TOKEN] here"
    with pytest.raises(VaultError):
        vault.resolve("{{vault:MISSING}}")
    assert vault.resolve("{{vault:MISSING}}", strict=False) == "{{vault:MISSING}}"


def test_redact_covers_short_secrets(tmp_path: Path):
    """A four-digit PIN is a secret too: the length floor let it through into the model's
    context and the audit log. Redacting a short one must not eat ordinary words either."""
    vault = CredentialVault(tmp_path / "v.enc", tmp_path / "v.key")
    vault.set("PIN", "1234")
    vault.set("CODE", "ok1")
    vault.set("SESSION", "abc123456")
    assert vault.redact("the pin is 1234 now") == "the pin is [REDACTED:PIN] now"
    # a short secret only goes as a whole token, so the text around it survives
    assert vault.redact("this hashing is fine") == "this hashing is fine"
    assert vault.redact("say ok1") == "say [REDACTED:CODE]"
    assert vault.redact("ok1.ok1-ok1 ok12") == "ok1.ok1-ok1 ok12"
    # the longer secret wins where one contains the other
    assert vault.redact("abc123456 and 1234") == "[REDACTED:SESSION] and [REDACTED:PIN]"


def test_redact_leaves_one_and_two_letter_values_alone(tmp_path: Path):
    """A value of one or two characters is a label stored by mistake, not a secret;
    masking it would blank every `a` or `ok` in every tool result the model sees."""
    vault = CredentialVault(tmp_path / "v.enc", tmp_path / "v.key")
    vault.set("A", "a")
    vault.set("OK", "ok")
    vault.set("EMPTY", "")
    text = "a reply that is ok, and a second one"
    assert vault.redact(text) == text
    # three characters is where redaction starts
    vault.set("PIN", "123")
    assert vault.redact("code 123 sent") == "code [REDACTED:PIN] sent"


def test_wrong_key_is_reported(tmp_path: Path):
    vault = CredentialVault(tmp_path / "v.enc", tmp_path / "k1.key")
    vault.set("A", "value-123456")
    other = CredentialVault(tmp_path / "v.enc", tmp_path / "k2.key")
    with pytest.raises(VaultError):
        other.get("A")
