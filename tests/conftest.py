from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nanomuse.config import Settings


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
