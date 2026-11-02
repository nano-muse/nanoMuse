"""A Windows process table that is not pure ASCII must not break the coding agent list.

``tasklist`` and ``powershell`` write their output in the console's OEM code page; on an
English Windows that is cp437, while ``text=True`` decodes with the ANSI code page (cp1252).
The two differ exactly on the bytes an accented process name or command line produces, and
``UnicodeDecodeError`` was never in the table reader's except list."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from typing import Any

import pytest

from nanomuse import stdio
from nanomuse.coding import agents

# cp437, the OEM code page of an English Windows console: 'ü' is b'\x81'. cp1252, the ANSI
# code page text=True decodes with, has no mapping for that byte.
_TASKLIST = (
    b'"node.exe","1234","Console","1","10,000 K"\r\n'
    b'"\x81nicorn.exe","5678","Console","1","1,000 K"\r\n'
)
_NODE_LINES = b"c:\\tools\\\x81tool\\server.js\r\n"


def _english_windows_run(cmd: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """What ``subprocess.run`` itself does on an English Windows, kept out of the real one."""
    raw = _NODE_LINES if "powershell" in cmd else _TASKLIST
    stdout: bytes | str = raw
    if kwargs.get("text"):
        stdout = raw.decode("cp1252")  # UnicodeDecodeError for b'\x81', as on the real thing
    return subprocess.CompletedProcess(args=list(cmd), returncode=0, stdout=stdout, stderr=b"")


def test_the_windows_process_table_survives_an_accented_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(stdio, "console_encoding", lambda: "cp437")
    monkeypatch.setattr(agents.subprocess, "run", _english_windows_run)
    rows = agents._processes()
    assert [name for name, _ in rows] == ["node.exe", "ünicorn.exe"]


def test_the_node_command_lines_survive_an_accented_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(stdio, "console_encoding", lambda: "cp437")
    monkeypatch.setattr(agents.subprocess, "run", _english_windows_run)
    lines = agents._windows_node_command_lines()
    assert lines == [r"c:\tools\ütool\server.js"]
