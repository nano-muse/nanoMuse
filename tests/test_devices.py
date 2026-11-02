"""The ``device_*`` tools: how the pictures a device sends are kept."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from nanomuse.tools.devices import DeviceScreen


class _FakeHub:
    """Answers every call with the next payload: one screen picture per call."""

    def __init__(self, payloads: list[dict[str, Any]]):
        self._payloads: Iterator[dict[str, Any]] = iter(payloads)

    def find(self, query: str) -> dict[str, Any]:
        return {"id": "d1", "name": "Pixel", "online": True}

    async def call(
        self, device_id: str, action: str, args: dict[str, Any], timeout: float = 120
    ) -> dict[str, Any]:
        return next(self._payloads)


def _screen(data: bytes) -> dict[str, Any]:
    return {"data": base64.b64encode(data).decode(), "mime": "image/jpeg"}


async def test_two_screens_in_the_same_second_are_two_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from nanomuse.tools import devices as devices_module

    hub = _FakeHub([_screen(b"before"), _screen(b"after")])
    tool = DeviceScreen(hub=hub, workspace=tmp_path)

    class _FrozenNow(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return datetime(2026, 1, 1, 12, 0, 0)

    monkeypatch.setattr(devices_module, "datetime", _FrozenNow)
    first = await tool.execute(device="Pixel")
    second = await tool.execute(device="Pixel")
    assert first.ok and second.ok
    # the "before" picture survives the "after" one: look, act, then look again
    assert Path(first.images[0]) != Path(second.images[0])
    assert Path(first.images[0]).read_bytes() == b"before"
    assert Path(second.images[0]).read_bytes() == b"after"
