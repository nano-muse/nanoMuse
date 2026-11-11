from __future__ import annotations

import os
import socket
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nanomuse.config import Settings

# The address every ``.example`` host resolves to in the tests. It has to count as public for
# the SSRF guard, and Python's ``ipaddress`` files the documentation ranges (TEST-NET-1 to 3,
# ``2001:db8::/32``) under ``is_private``, so this is the address ``example.com`` answered for
# years. Nothing is ever sent to it: every fetch in the tests goes through a mocked transport.
EXAMPLE_HOST_ADDRESS = "93.184.216.34"


def _is_example_host(host: bytes | str | None) -> bool:
    if not isinstance(host, str):
        return False
    h = host.lower()
    return (
        h == "example"
        or h.endswith(".example")
        or h == "example.com"
        or h.endswith(".example.com")
        or h == "example.org"
        or h.endswith(".example.org")
        or h == "example.net"
        or h.endswith(".example.net")
    )


@pytest.fixture(autouse=True)
def _example_hosts_resolve_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """``.example`` hosts answer a fixed public address without asking the resolver.

    The web tools run ``_is_private_host`` (``socket.getaddrinfo``) on a host before the
    mocked transport sees the request. The reserved ``.example`` TLD is NXDOMAIN on most
    resolvers, which the guard treats as "not private", but a resolver that sinkholes
    unknown names to ``127.0.0.1`` or ``0.0.0.0`` made the guard refuse ``shop.example``
    and three tests failed on that machine only (#339). Every other host, numeric
    literals included, still goes to the real function.
    """
    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(
        host: bytes | str | None, port: bytes | str | int | None, *args: Any, **kwargs: Any
    ) -> Any:
        if _is_example_host(host):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (EXAMPLE_HOST_ADDRESS, port or 0))]
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture(autouse=True)
def _own_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The developer's shell does not reach the tests.

    ``load_settings`` honours ``NANOMUSE_*`` and the provider key variables over the
    config file, so a ``NANOMUSE_DATA_DIR`` exported for a trial run sent a test's skills
    into that data directory, and an exported ``OPENAI_API_KEY`` shows a "no key" test a
    key. Each test starts without them; one that needs a variable sets it itself.
    """
    for name in list(os.environ):
        if name.startswith("NANOMUSE_") or name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def dead_proxy(monkeypatch: pytest.MonkeyPatch) -> str:
    """A proxy nothing answers on, in the variables a proxy client reads.

    The requests these tests make are to ``127.0.0.1``, and a client that consults the
    environment's proxy sends them there instead: with this one every such call fails, so a
    test that passes proves the call went straight to the loopback. ``NO_PROXY`` is cleared
    first, since a developer's shell may carry one that would hide the bug again.
    """
    names = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    return "http://127.0.0.1:9"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.data_dir = tmp_path / "data"
    s.agent.workspace = tmp_path / "workspace"
    s.llm.api_key = "test"
    s.llm.stream = False
    s.ensure_dirs()
    return s


@pytest.fixture(autouse=True)
def _close_sqlite_connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Close every SQLite connection a test opened and left behind.

    The runtime closes its stores on ``close()``; a test that builds a store, an app or a
    service and never stops it would otherwise leave the connection to the garbage
    collector, which reports it as an unclosed-database ResourceWarning in some later,
    unrelated test. Closing an already closed connection is a no-op, so the runtime's own
    closes are unaffected.
    """
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect)
    yield
    for conn in opened:
        try:
            conn.close()
        except sqlite3.ProgrammingError:  # pragma: no cover - closed from another thread
            pass
