"""A file kept to its owner (nanomuse/private.py)."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from nanomuse import private
from nanomuse.private import keep_private


@pytest.mark.skipif(sys.platform == "win32", reason="the mode is the POSIX side's test")
def test_posix_takes_the_mode(tmp_path: Path) -> None:
    # the calendars and address books carry a life; the mode says whose
    f = tmp_path / "secret.txt"
    f.write_text("x", encoding="utf-8")
    keep_private(f)
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform != "win32", reason="the ACL is the Windows side's test")
def test_windows_takes_the_acl(tmp_path: Path) -> None:
    # chmod clears a read-only flag there and nothing else; the rules handed down to a
    # file went, and the one account that made it kept it alone
    f = tmp_path / "secret.tmp"
    target = tmp_path / "secret.txt"
    f.write_text("x", encoding="utf-8")
    keep_private(f)
    # the current user must still be able to read, write and atomically replace the file
    # (passing a bare USERNAME when USERDOMAIN == USERNAME locks the owner out)
    assert f.read_text(encoding="utf-8") == "x"
    f.write_text("y", encoding="utf-8")
    f.replace(target)
    assert target.read_text(encoding="utf-8") == "y"
    # icacls speaks the console's code page; the first line is the rule, the rest a status
    rules = subprocess.run(["icacls", str(target)], capture_output=True).stdout.decode("mbcs")
    line = rules.splitlines()[0]
    user = os.environ.get("USERNAME", "")
    assert user and user in line
    assert "Everyone" not in line
    assert "BUILTIN" not in line


def test_windows_grants_by_token_sid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    f = tmp_path / "vault.tmp"
    monkeypatch.setattr(private.sys, "platform", "win32")
    monkeypatch.setattr(private, "_windows_user_sid", lambda: "S-1-5-21-123-456-789-1001")
    monkeypatch.setenv("USERNAME", "admin")
    monkeypatch.setenv("USERDOMAIN", "admin")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **_: calls.append(cmd))

    keep_private(f)

    assert calls == [
        [
            "icacls",
            os.fspath(f),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-21-123-456-789-1001:(F)",
        ]
    ]


def test_windows_falls_back_to_domain_qualified_username(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    f = tmp_path / "vault.tmp"
    monkeypatch.setattr(private.sys, "platform", "win32")
    monkeypatch.setattr(private, "_windows_user_sid", lambda: None)
    monkeypatch.setenv("USERNAME", "admin")
    monkeypatch.setenv("USERDOMAIN", "admin")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **_: calls.append(cmd))

    keep_private(f)

    assert calls == [["icacls", os.fspath(f), "/inheritance:r", "/grant:r", r"admin\admin:(F)"]]


def test_windows_falls_back_to_username_without_domain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    f = tmp_path / "vault.tmp"
    monkeypatch.setattr(private.sys, "platform", "win32")
    monkeypatch.setattr(private, "_windows_user_sid", lambda: None)
    monkeypatch.setenv("USERNAME", "alice")
    monkeypatch.delenv("USERDOMAIN", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **_: calls.append(cmd))

    keep_private(f)

    assert calls == [["icacls", os.fspath(f), "/inheritance:r", "/grant:r", "alice:(F)"]]
