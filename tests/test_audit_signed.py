"""The audit log's hash chain: tampering, deletion and reordering are found.

Entries written before signing carry no hash fields and verify as ``unsigned``;
entries written with a key verify through :meth:`AuditLog.verify`. The signing key
is injected in most tests, so no keychain or key file is involved; the key-file
tests block the keychain import and the environment variable explicitly.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from nanomuse.sentinel.audit import AuditLog, HmacSigner, _main

KEY = bytes(range(32))
OTHER_KEY = bytes([255 - b for b in KEY])


@pytest.fixture()
def signed(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit.jsonl", signer=HmacSigner(KEY))


def _write(log: AuditLog, count: int) -> list[dict]:
    return [log.record("tool_call", tool="shell", summary=f"call {i}") for i in range(count)]


def _lines(path: Path) -> list[str]:
    return path.read_text("utf-8").splitlines()


def _rewrite(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_signed_entries_verify_and_chain(tmp_path: Path, signed: AuditLog) -> None:
    entries = _write(signed, 3)
    assert [e["seq"] for e in entries] == [1, 2, 3]
    assert entries[0]["prev"] == "0" * 64
    assert entries[1]["prev"] == entries[0]["entry_hash"]
    assert entries[2]["prev"] == entries[1]["entry_hash"]
    assert all(e["key_id"] == "1" for e in entries)
    report = signed.verify()
    assert report.ok and report.checked == 3 and report.unsigned == 0
    assert report.last_seq == 3
    assert signed.tail()[-1]["entry_hash"] == entries[-1]["entry_hash"]


def test_editing_an_entry_breaks_its_line(tmp_path: Path, signed: AuditLog) -> None:
    _write(signed, 3)
    lines = _lines(tmp_path / "audit.jsonl")
    edited = json.loads(lines[1])
    edited["summary"] = "a different call"
    lines[1] = json.dumps(edited)
    _rewrite(tmp_path / "audit.jsonl", lines)
    report = signed.verify()
    assert not report.ok
    assert [b["line"] for b in report.broken] == [2]
    assert any("does not match" in r for r in report.broken[0]["reasons"])


def test_editing_a_timestamp_breaks_its_line(tmp_path: Path, signed: AuditLog) -> None:
    _write(signed, 2)
    lines = _lines(tmp_path / "audit.jsonl")
    edited = json.loads(lines[0])
    edited["ts"] = "2030-01-01T00:00:00.000+00:00"
    lines[0] = json.dumps(edited)
    _rewrite(tmp_path / "audit.jsonl", lines)
    report = signed.verify()
    assert not report.ok
    assert report.broken[0]["line"] == 1


def test_editing_a_hash_breaks_its_line(tmp_path: Path, signed: AuditLog) -> None:
    _write(signed, 2)
    lines = _lines(tmp_path / "audit.jsonl")
    edited = json.loads(lines[0])
    edited["entry_hash"] = "0" * 64
    lines[0] = json.dumps(edited)
    _rewrite(tmp_path / "audit.jsonl", lines)
    report = signed.verify()
    assert not report.ok
    assert report.broken[0]["line"] == 1


def test_deleting_a_middle_line_breaks_the_chain(tmp_path: Path, signed: AuditLog) -> None:
    _write(signed, 3)
    lines = _lines(tmp_path / "audit.jsonl")
    _rewrite(tmp_path / "audit.jsonl", [lines[0], lines[2]])
    report = signed.verify()
    assert not report.ok
    assert report.broken[0]["line"] == 2
    assert any("prev" in r or "seq" in r for r in report.broken[0]["reasons"])


def test_deleting_tail_lines_is_visible_only_in_last_seq(tmp_path: Path, signed: AuditLog) -> None:
    # A hash chain cannot prove the tail was not cut: the remaining lines still link.
    # The last sequence number is reported so a caller that knows the count can tell.
    _write(signed, 3)
    lines = _lines(tmp_path / "audit.jsonl")
    _rewrite(tmp_path / "audit.jsonl", lines[:2])
    report = signed.verify()
    assert report.ok and report.checked == 2 and report.last_seq == 2


def test_reordering_two_lines_breaks_the_chain(tmp_path: Path, signed: AuditLog) -> None:
    _write(signed, 3)
    lines = _lines(tmp_path / "audit.jsonl")
    _rewrite(tmp_path / "audit.jsonl", [lines[1], lines[0], lines[2]])
    report = signed.verify()
    assert not report.ok
    assert report.broken


def test_unsigned_old_lines_verify_as_unsigned(tmp_path: Path, signed: AuditLog) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text(
        json.dumps({"ts": "2026-01-01T00:00:00.000+00:00", "event": "tool_call"}) + "\n",
        encoding="utf-8",
    )
    _write(signed, 2)
    report = signed.verify()
    assert report.ok and report.checked == 2 and report.unsigned == 1


def test_a_corrupt_line_is_reported_and_the_rest_still_checked(
    tmp_path: Path, signed: AuditLog
) -> None:
    _write(signed, 2)
    path = tmp_path / "audit.jsonl"
    path.write_text(path.read_text("utf-8") + "{not json\n", encoding="utf-8")
    report = signed.verify()
    assert not report.ok
    assert report.corrupt == [{"line": 3, "reason": "not valid JSON"}]
    assert report.checked == 2


def test_the_wrong_key_breaks_every_signed_line(tmp_path: Path, signed: AuditLog) -> None:
    _write(signed, 2)
    other = AuditLog(tmp_path / "audit.jsonl", signer=HmacSigner(OTHER_KEY))
    report = other.verify()
    assert not report.ok
    assert len(report.broken) == 2


def test_verify_without_any_key_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signed: AuditLog
) -> None:
    _write(signed, 1)
    monkeypatch.delenv("NANOMUSE_AUDIT_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "keyring", None)
    keyless = AuditLog(tmp_path / "audit.jsonl")
    with pytest.raises(RuntimeError, match="no audit signing key"):
        keyless.verify()


def test_an_unsigned_only_log_verifies_without_a_key(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text(
        json.dumps({"ts": "2026-01-01T00:00:00.000+00:00", "event": "tool_call"}) + "\n",
        encoding="utf-8",
    )
    log = AuditLog(path)
    report = log.verify()
    assert report.ok and report.checked == 0 and report.unsigned == 1
    assert not (tmp_path / "audit.key").exists()


def _no_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NANOMUSE_AUDIT_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "keyring", None)


def test_the_default_key_is_its_own_file_not_the_vault_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_keychain(monkeypatch)
    vault_key = tmp_path / "vault.key"
    vault_key.write_bytes(b"vault-secret")
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("tool_call", tool="shell")
    key_file = tmp_path / "audit.key"
    assert key_file.exists()
    assert key_file.read_bytes() != b"vault-secret"
    if sys.platform != "win32":
        # Windows has no mode bits: a file written 0600 still reports 0666.
        # The access list is checked instead (see _windows_key_file_is_private).
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert log.key_source == "file"
    fresh = AuditLog(tmp_path / "audit.jsonl")
    assert fresh.verify().ok
    assert fresh.key_source == "file"


@pytest.mark.skipif(sys.platform == "win32", reason="mode bits carry no meaning on Windows")
def test_a_key_file_readable_by_others_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_keychain(monkeypatch)
    key_file = tmp_path / "audit.key"
    key_file.write_text(KEY.hex(), encoding="utf-8")
    os.chmod(key_file, 0o644)
    log = AuditLog(tmp_path / "audit.jsonl")
    with pytest.raises(PermissionError, match="readable by others"):
        log.record("tool_call", tool="shell")


@pytest.mark.skipif(sys.platform == "win32", reason="mode bits carry no meaning on Windows")
def test_a_key_file_with_mode_0666_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 0666 is what every file reports on Windows, so it must still refuse here.
    _no_keychain(monkeypatch)
    key_file = tmp_path / "audit.key"
    key_file.write_text(KEY.hex(), encoding="utf-8")
    os.chmod(key_file, 0o666)
    log = AuditLog(tmp_path / "audit.jsonl")
    with pytest.raises(PermissionError, match="readable by others"):
        log.record("tool_call", tool="shell")


def _simulate_windows(monkeypatch: pytest.MonkeyPatch, acl_private: bool) -> None:
    """Run the key-file check down the Windows path, on any platform.

    The real DACL read needs Windows, so the checker itself is stubbed and
    only the dispatch and the accept/refuse behaviour are exercised here;
    Windows CI runs the real checker.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "nanomuse.sentinel.audit._windows_key_file_is_private",
        lambda path: acl_private,
    )


def test_a_key_file_with_loose_mode_bits_is_accepted_on_windows_when_the_acl_is_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_keychain(monkeypatch)
    _simulate_windows(monkeypatch, acl_private=True)
    key_file = tmp_path / "audit.key"
    key_file.write_text(KEY.hex(), encoding="utf-8")
    os.chmod(key_file, 0o666)
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("tool_call", tool="shell")
    assert log.key_source == "file"
    assert AuditLog(tmp_path / "audit.jsonl").verify().ok


def test_a_key_file_with_a_broad_acl_is_refused_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_keychain(monkeypatch)
    _simulate_windows(monkeypatch, acl_private=False)
    key_file = tmp_path / "audit.key"
    key_file.write_text(KEY.hex(), encoding="utf-8")
    os.chmod(key_file, 0o666)
    log = AuditLog(tmp_path / "audit.jsonl")
    with pytest.raises(PermissionError, match="readable by others"):
        log.record("tool_call", tool="shell")


def test_the_environment_key_is_used_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NANOMUSE_AUDIT_KEY", KEY.hex())
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("tool_call", tool="shell")
    assert log.key_source == "env"
    assert log.verify().ok
    assert not (tmp_path / "audit.key").exists()


def test_a_malformed_environment_key_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NANOMUSE_AUDIT_KEY", "not hex")
    log = AuditLog(tmp_path / "audit.jsonl")
    with pytest.raises(ValueError, match="64 hex"):
        log.record("tool_call", tool="shell")


def test_an_injected_signer_touches_no_key_file(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", signer=HmacSigner(KEY))
    log.record("tool_call", tool="shell")
    assert not (tmp_path / "audit.key").exists()
    assert log.verify().ok


def test_the_verify_command_reports_ok_and_broken(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The command resolves the key itself (here from the environment), like a real run.
    monkeypatch.setenv("NANOMUSE_AUDIT_KEY", KEY.hex())
    log = AuditLog(tmp_path / "audit.jsonl")
    _write(log, 2)
    assert _main(["--verify", str(tmp_path / "audit.jsonl")]) == 0
    out = capsys.readouterr().out
    assert "ok=True" in out and "checked=2" in out
    lines = _lines(tmp_path / "audit.jsonl")
    edited = json.loads(lines[0])
    edited["summary"] = "tampered"
    lines[0] = json.dumps(edited)
    _rewrite(tmp_path / "audit.jsonl", lines)
    assert _main(["--verify", str(tmp_path / "audit.jsonl")]) == 1
    assert "broken" in capsys.readouterr().out
