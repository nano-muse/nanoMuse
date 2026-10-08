"""The sentence a failed run leaves in the chat (nanomuse/server/failures.py)."""

from __future__ import annotations

import httpx
import openai

from nanomuse.server.failures import describe_failure, failure_notice


def _status_error(cls, status: int, body: dict):
    request = httpx.Request("POST", "https://relay.test/v1/chat/completions")
    response = httpx.Response(status, request=request, json={"error": body})
    return cls(body.get("message", "no"), response=response, body=body)


def test_relay_refusals_are_named_by_code():
    exc = _status_error(
        openai.RateLimitError, 429, {"code": "daily_cap", "message": "Today's share …"}
    )
    code, text = describe_failure(exc)
    assert code == "allowance" and "Connections" in text and "tomorrow" in text

    exc = _status_error(
        openai.PermissionDeniedError, 402, {"code": "out_of_tokens", "message": "…"}
    )
    assert describe_failure(exc)[0] == "allowance"

    # the streaming path: openai.APIError with the relay's body and no HTTP status
    exc = openai.APIError(
        "The relay's model provider refused its key", request=None, body={"code": "upstream_auth"}
    )  # type: ignore[arg-type]
    code, text = describe_failure(exc)
    assert code == "relay" and "operator" in text

    exc = openai.APIError("busy", request=None, body={"code": "upstream_503", "message": "x"})  # type: ignore[arg-type]
    assert describe_failure(exc)[0] == "provider"


def test_an_exhausted_allowance_carries_the_ways_on():
    """relay 0.9: ``429 allowance_exhausted`` says what is left and where an invitation
    (+¥5 for both sides) and one's own key lead; the notice passes that on for the card.
    The 0.5 co-creation fields ride along as the relay still sends them (false / 0)."""
    body = {
        "code": "allowance_exhausted",
        "message": "Your free allowance (¥10) is used up. …",
        "left": 0,
        "grant": 10,
        "invite_url": "https://nanomuse.cn/web/?invite=ABCD2345",
        "invite_bonus_cny": 5,
        "invitee_bonus_cny": 5,
        "contribute_bonus_available": False,
        "contribute_bonus_cny": 0,
        "own_key_docs": "https://nanomuse.cn/own-key",
        "type": "nanomuse_cloud",
    }
    exc = _status_error(openai.RateLimitError, 429, body)
    code, text = describe_failure(exc)
    assert (
        code == "allowance"
        and "Invite a friend" in text
        and "co-creation" not in text
        and "keep working" in text
    )
    notice = failure_notice(exc, "t1")
    assert notice["code"] == "allowance" and notice["allowance"] == {
        "left": 0,
        "grant": 10,
        "invite_url": "https://nanomuse.cn/web/?invite=ABCD2345",
        "invite_bonus_cny": 5,
        "invitee_bonus_cny": 5,
        "contribute_bonus_available": False,
        "contribute_bonus_cny": 0,
        "own_key_docs": "https://nanomuse.cn/own-key",
    }
    # any other failure carries no such block
    other = _status_error(openai.RateLimitError, 429, {"code": "rate_limited", "message": "slow"})
    assert "allowance" not in failure_notice(other, "t1")


def test_the_remaining_relay_refusals_are_sentences():
    """413 and the 429s beside the allowance (parity item 35) are named, never
    ``The model provider answered with an error: …`` with the body behind it."""
    exc = _status_error(
        openai.APIStatusError, 413, {"code": "too_large", "message": '{"error": {"big": 1}}'}
    )
    code, text = describe_failure(exc)
    assert code == "too_long" and "new chat" in text and "{" not in text and "413" not in text

    exc = _status_error(
        openai.RateLimitError, 429, {"code": "too_many_in_flight", "message": "in flight"}
    )
    code, text = describe_failure(exc)
    assert code == "busy" and "at once" in text and "in flight" not in text

    exc = _status_error(openai.RateLimitError, 429, {"code": "provider_busy", "message": "x"})
    assert describe_failure(exc) == ("busy", "The model provider is busy; try again in a moment.")

    exc = _status_error(openai.PermissionDeniedError, 403, {"code": "not_invited", "message": "x"})
    code, text = describe_failure(exc)
    assert code == "account" and "invite code" in text


def test_the_operators_switches_say_paused_not_broken():
    """relay 0.22: the five switches (docs/cloud.md, Controls) — each one plain sentence that
    says *paused for now* and that nothing is lost; ``allowance_exhausted`` with ``paused``
    keeps the allowance code (the apps draw the same card) but says paused, not used up."""
    exc = _status_error(
        openai.InternalServerError,
        503,
        {"code": "service_paused", "message": "down", "paused": True},
    )
    code, text = describe_failure(exc)
    assert code == "relay" and "paused" in text and "kept" in text and "down" not in text

    exc = _status_error(
        openai.InternalServerError, 503, {"code": "sync_paused", "message": "x", "paused": True}
    )
    code, text = describe_failure(exc)
    assert code == "relay" and text.startswith("Conversation sync is paused")

    exc = _status_error(
        openai.InternalServerError, 503, {"code": "hub_paused", "message": "x", "paused": True}
    )
    code, text = describe_failure(exc)
    assert code == "relay" and text.startswith("The device hub is paused")

    exc = _status_error(
        openai.PermissionDeniedError, 403, {"code": "signup_closed", "message": "x"}
    )
    code, text = describe_failure(exc)
    assert code == "account" and "sign-ups are paused" in text and "existing accounts" in text

    body = {
        "code": "allowance_exhausted",
        "message": "The free allowance is paused on this relay for now …",
        "paused": True,
        "reason": "allowance_paused",
        "left": 7,
        "grant": 10,
        "invite_url": "https://nanomuse.cn/web/?invite=ABCD2345",
        "invite_bonus_cny": 5,
    }
    exc = _status_error(openai.RateLimitError, 429, body)
    code, text = describe_failure(exc)
    assert code == "allowance" and "paused" in text and "not used up" in text
    assert not text.startswith("The free allowance is used up.")
    notice = failure_notice(exc, "t1")
    assert notice["allowance"]["paused"] is True and notice["allowance"]["left"] == 7
    # without the flag the spent-pool sentence is unchanged
    spent = _status_error(openai.RateLimitError, 429, {**body, "paused": False})
    assert describe_failure(spent)[1].startswith("The free allowance is used up.")
    assert "paused" in failure_notice(spent, "t1")["allowance"]


def test_own_key_failures():
    exc = _status_error(openai.AuthenticationError, 401, {"message": "Incorrect API key provided"})
    code, text = describe_failure(exc)
    assert code == "key" and "Incorrect API key" not in text

    exc = _status_error(
        openai.BadRequestError,
        400,
        {"message": "This model's maximum context length is 32768 tokens"},
    )
    assert describe_failure(exc)[0] == "too_long"

    exc = _status_error(openai.BadRequestError, 400, {"message": "unknown parameter foo"})
    code, text = describe_failure(exc)
    assert code == "request" and "unknown parameter foo" in text

    assert (
        describe_failure(openai.APITimeoutError(httpx.Request("POST", "https://x")))[0] == "timeout"
    )
    assert (
        describe_failure(openai.APIConnectionError(request=httpx.Request("POST", "https://x")))[0]
        == "network"
    )
    assert (
        describe_failure(_status_error(openai.NotFoundError, 404, {"message": "model not found"}))[
            0
        ]
        == "model"
    )


def test_unknown_failures_keep_the_type_and_first_line():
    code, text = describe_failure(ValueError("first line\nsecond line"))
    assert code == "unknown" and text == "Something went wrong: ValueError: first line"
    notice = failure_notice(ValueError("boom"), "t1")
    assert notice["type"] == "notice" and notice["level"] == "error" and notice["thread"] == "t1"
    assert notice["code"] == "unknown" and notice["detail"] == "ValueError: boom"


def test_timeline_writes_are_coalesced_on_a_loop_and_immediate_off_one(tmp_path):
    import asyncio
    import json

    from nanomuse.server.events import Timeline

    path = tmp_path / "t.json"
    off = Timeline("t", path)
    off.add({"type": "user", "text": "now"})
    assert json.loads(path.read_text("utf-8"))["events"][0]["text"] == "now"

    def written() -> list[str]:
        # the texts on disk, not a substring of the file: an event id is random hex and can
        # contain "e19" by chance, which made the first version of this test flaky
        return [e["text"] for e in json.loads(path.read_text("utf-8"))["events"]]

    async def burst() -> None:
        tl = Timeline("t", path)
        for i in range(20):
            tl.add({"type": "user", "text": f"e{i}"})
        # nothing written yet: the burst is still being coalesced
        assert "e19" not in written()
        await asyncio.sleep(0.8)
        assert "e19" in written()
        tl.add({"type": "user", "text": "last"})
        tl.flush()  # shutdown path: written at once, the scheduled write dropped
        assert "last" in written()

    asyncio.run(burst())


# ----------------------------------------------------------------------------- update check
def test_update_check_versions_and_opt_out(monkeypatch):
    from nanomuse.server import update

    assert update.parse_version("v0.1.21") == (0, 1, 21)
    assert update.parse_version("0.2.0-rc1") == (0, 2, 0)
    assert update.parse_version("nightly") == ()
    assert update.newer_than("0.1.21", "0.1.20") and not update.newer_than("0.1.20", "0.1.20")
    assert not update.newer_than("nightly", "0.1.20")
    monkeypatch.delenv("NANOMUSE_CLOUD_KEY", raising=False)
    monkeypatch.delenv("NANOMUSE_NO_UPDATE_CHECK", raising=False)
    assert update.enabled(True) and not update.enabled(False)
    monkeypatch.setenv("NANOMUSE_NO_UPDATE_CHECK", "1")
    assert not update.enabled(True)
    monkeypatch.delenv("NANOMUSE_NO_UPDATE_CHECK")
    monkeypatch.setenv(
        "NANOMUSE_CLOUD_KEY", "nm_hosted"
    )  # a hosted web session: the operator updates
    assert not update.enabled(True)


def test_update_check_caches_and_survives_failures(monkeypatch):
    import asyncio
    import time

    from nanomuse.server import update

    monkeypatch.delenv("NANOMUSE_CLOUD_KEY", raising=False)
    monkeypatch.delenv("NANOMUSE_NO_UPDATE_CHECK", raising=False)
    calls = 0
    real_check = update.UpdateCheck._check

    async def fake_check(self: update.UpdateCheck) -> None:
        nonlocal calls
        calls += 1
        self.checked_at = time.monotonic()
        self.latest = "0.1.21"
        self.url = "https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.21"

    monkeypatch.setattr(update.UpdateCheck, "_check", fake_check)
    check = update.UpdateCheck(True, current="0.1.20")
    first = asyncio.run(check.view())
    assert first["newer"] is True and first["latest"] == "0.1.21" and first["enabled"] is True
    asyncio.run(check.view())
    assert calls == 1  # the second look is answered from the cache

    monkeypatch.setattr(
        update.UpdateCheck, "_check", real_check
    )  # the real one, with a client that fails

    class Boom:
        def __init__(self, *a, **k): ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise update.httpx.ConnectError("no network")

    monkeypatch.setattr(update.httpx, "AsyncClient", Boom)
    check = update.UpdateCheck(True, current="0.1.20")
    view = asyncio.run(check.view())
    assert view["newer"] is False and view["latest"] is None and view["error"] == "ConnectError"
    assert not asyncio.run(update.UpdateCheck(False, current="0.1.20").view())["enabled"]
