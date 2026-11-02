"""Thread handovers remain quiet and release coroutines during shutdown."""

from __future__ import annotations

import asyncio
import inspect
from concurrent.futures import Future
from typing import Any

import pytest

from nanomuse.channels.dingtalk import DingTalkChannel
from nanomuse.channels.feishu import FeishuChannel


@pytest.mark.parametrize("channel", [DingTalkChannel, FeishuChannel])
def test_cancelled_handover_does_not_raise(channel: Any) -> None:
    future: Future[None] = Future()
    future.cancel()
    channel._log_failed_handover(future)


def test_stopped_dingtalk_closes_the_unscheduled_coroutine() -> None:
    channel = DingTalkChannel({})
    coro = channel._handle({})
    channel.hand_over(coro)
    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED


@pytest.mark.parametrize("kind", ["dingtalk", "feishu"])
async def test_loop_closing_during_handover_releases_coroutine(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []

    def stopped(coro: Any, loop: Any) -> None:
        seen.append(coro)
        raise RuntimeError("Event loop is closed")

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", stopped)
    if kind == "dingtalk":
        ding = DingTalkChannel({})
        ding._loop = asyncio.get_running_loop()
        ding.hand_over(ding._handle({}))
    else:
        feishu = FeishuChannel({})
        feishu._loop = asyncio.get_running_loop()
        feishu._on_message_event({})
    assert len(seen) == 1
    assert inspect.getcoroutinestate(seen[0]) == inspect.CORO_CLOSED
