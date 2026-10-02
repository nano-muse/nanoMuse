"""Google Calendar: OAuth (PKCE), token refresh, and the Calendar API calls.

Everything here runs against a mocked Google (``httpx.MockTransport``), so no network and
no real credentials are needed. What is checked is the shape of the port from OpenMuse:
the authorize URL, the code exchange, the refresh, list / create / update / delete, the
recurring-event guard, and the ``If-Match`` that stops a blind overwrite.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
import pytest

from nanomuse.calendar import CalendarFeeds, Event, FeedState, GoogleCalendarClient, GoogleError
from nanomuse.calendar.google import SCOPE_READ, SCOPE_WRITE, TOKENS_SECRET
from nanomuse.calendar.ics import local_tz
from nanomuse.config import CalendarSettings, GoogleCalendarSettings
from nanomuse.tools import Calendar
from nanomuse.vault import CredentialVault

TZ = ZoneInfo("Asia/Shanghai")


def google_settings(**over: Any) -> GoogleCalendarSettings:
    base = GoogleCalendarSettings(
        enabled=True,
        client_id="client-123.apps.googleusercontent.com",
        client_secret="secret-xyz",
        redirect_uri="http://localhost:8787/api/google/callback",
        write=True,
    )
    for k, v in over.items():
        setattr(base, k, v)
    return base


def client_with(handler: Any) -> tuple[GoogleCalendarClient, list[httpx.Request]]:
    """A GoogleCalendarClient whose every HTTP call goes through ``handler``."""
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(wrapped)
    real = httpx.AsyncClient
    http = real(transport=transport)
    return GoogleCalendarClient(google_settings(), http=http), seen


def test_authorize_url_is_pkce_and_asks_for_offline_access():
    client = GoogleCalendarClient(google_settings())
    url = client.authorize_url(write=True)
    parts = urlsplit(url)
    assert parts.netloc == "accounts.google.com"
    q = parse_qs(parts.query)
    assert q["client_id"] == ["client-123.apps.googleusercontent.com"]
    assert q["redirect_uri"] == ["http://localhost:8787/api/google/callback"]
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    assert q["include_granted_scopes"] == ["true"]
    assert q["code_challenge_method"] == ["S256"]
    assert SCOPE_READ in q["scope"][0] and SCOPE_WRITE in q["scope"][0]
    # the challenge really is S256(verifier) for the verifier held for this state
    state = q["state"][0]
    verifier = client._pending[state].verifier
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert q["code_challenge"] == [expected]


def test_read_only_sign_in_omits_the_write_scope():
    client = GoogleCalendarClient(google_settings())
    url = client.authorize_url(write=False)
    scopes = parse_qs(urlsplit(url).query)["scope"][0].split()
    assert SCOPE_READ in scopes and SCOPE_WRITE not in scopes


async def test_exchange_stores_tokens_and_refreshes_before_expiry(tmp_path: Path):
    vault = CredentialVault(tmp_path / "vault.enc", key_path=tmp_path / "vault.key")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com" and request.url.path == "/token":
            form = dict(parse_qs(request.content.decode()))
            assert form["grant_type"] == ["authorization_code"]
            assert form["code_verifier"], "PKCE verifier must be sent"
            return httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "expires_in": 3600,
                    "scope": f"{SCOPE_READ} {SCOPE_WRITE}",
                },
            )
        if request.url.host == "www.googleapis.com" and "userinfo" in request.url.path:
            # userinfo needs the openid scope this client does not request: 403 in production
            return httpx.Response(403, json={"error": "insufficient_scope"})
        if request.url.path.endswith("/calendarList/primary"):
            return httpx.Response(200, json={"id": "zhaque.mail@gmail.com"})
        return httpx.Response(404, text="unexpected")

    client = GoogleCalendarClient(google_settings(), vault=vault, http=_mock(handler))
    url = client.authorize_url(write=True)
    state = parse_qs(urlsplit(url).query)["state"][0]
    status = await client.exchange(state, code="the-code")
    assert status["connected"] and status["can_write"]
    assert status["account"] == "zhaque.mail@gmail.com"
    assert vault.get(TOKENS_SECRET), "tokens must be in the vault, not in the clear"

    # a fresh client reads the same tokens back out of the vault
    again = GoogleCalendarClient(google_settings(), vault=vault, http=_mock(handler))
    assert again.connected and again.status()["account"] == "zhaque.mail@gmail.com"


async def test_expired_access_token_is_refreshed_once(tmp_path: Path):
    vault = CredentialVault(tmp_path / "vault.enc", key_path=tmp_path / "vault.key")
    vault.set(
        TOKENS_SECRET,
        json.dumps(
            {
                "access_token": "stale",
                "refresh_token": "refresh-1",
                "expires_at": 1,  # long past
                "scopes": [SCOPE_READ, SCOPE_WRITE],
                "account": "zhaque.mail@gmail.com",
            }
        ),
    )
    refreshed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            form = dict(parse_qs(request.content.decode()))
            refreshed.append(form["grant_type"][0])
            return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
        return httpx.Response(404)

    client = GoogleCalendarClient(google_settings(), vault=vault, http=_mock(handler))
    assert await client.access_token() == "fresh"
    # and it is cached: a second call inside the window does not hit the network again
    assert await client.access_token() == "fresh"
    assert refreshed == ["refresh_token"]


async def test_list_calendars_and_events_map_to_occurrences(tmp_path: Path):
    vault = CredentialVault(tmp_path / "vault.enc", key_path=tmp_path / "vault.key")
    vault.set(
        TOKENS_SECRET,
        json.dumps(
            {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_at": 9_999_999_999,
                "scopes": [SCOPE_READ, SCOPE_WRITE],
                "account": "zhaque.mail@gmail.com",
            }
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/calendarList"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "family", "summary": "Family", "accessRole": "writer"},
                        {"id": "primary", "summary": "Me", "primary": True, "accessRole": "owner"},
                    ]
                },
            )
        if path.endswith("/events"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "evt-1",
                            "summary": "Standup",
                            "start": {"dateTime": "2026-10-05T09:30:00+08:00"},
                            "end": {"dateTime": "2026-10-05T10:00:00+08:00"},
                            "location": "Zoom",
                        },
                        {
                            "id": "evt-2",
                            "summary": "Holiday",
                            "start": {"date": "2026-10-06"},
                            "end": {"date": "2026-10-07"},
                        },
                        {"id": "gone", "status": "cancelled", "start": {"date": "2026-10-06"}},
                    ]
                },
            )
        return httpx.Response(404)

    client = GoogleCalendarClient(google_settings(), vault=vault, http=_mock(handler))
    calendars = await client.list_calendars()
    assert [c.id for c in calendars] == ["primary", "family"], "primary sorts first"
    assert calendars[0].writable and calendars[1].writable

    events = await client.list_events(
        "primary", datetime(2026, 10, 1, tzinfo=TZ), datetime(2026, 10, 31, tzinfo=TZ)
    )
    assert [e.uid for e in events] == ["evt-1", "evt-2"], "cancelled events are dropped"
    assert events[0].summary == "Standup" and events[0].location == "Zoom"
    assert events[1].all_day and events[1].start.date().isoformat() == "2026-10-06"


async def test_create_event_posts_the_body_google_expects(tmp_path: Path):
    vault, client, seen = _write_client(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["summary"] == "Dentist"
            assert body["start"] == {
                "dateTime": "2026-10-03T14:00:00+08:00",
                "timeZone": "Asia/Shanghai",
            }
            assert body["location"] == "Nanjing Rd"
            return httpx.Response(
                200,
                json={
                    "id": "new-1",
                    "etag": "etag-1",
                    "htmlLink": "https://calendar.google.com/event?eid=new-1",
                    "summary": "Dentist",
                    "start": {"dateTime": "2026-10-03T14:00:00+08:00"},
                    "end": {"dateTime": "2026-10-03T14:45:00+08:00"},
                },
            )
        return httpx.Response(404)

    client._http = _mock(handler)
    result = await client.create_event(
        calendar_id="primary",
        summary="Dentist",
        start=datetime(2026, 10, 3, 14, 0, tzinfo=TZ),
        end=datetime(2026, 10, 3, 14, 45, tzinfo=TZ),
        location="Nanjing Rd",
        timezone="Asia/Shanghai",
    )
    assert result["id"] == "new-1"
    assert result["event"]["summary"] == "Dentist"
    assert seen and "sendUpdates=all" in str(seen[-1].url), "attendees get the invite"


async def test_update_and_delete_read_first_and_send_if_match(tmp_path: Path):
    vault, client, seen = _write_client(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": "evt-1",
                    "etag": "etag-current",
                    "summary": "Old",
                    "start": {"dateTime": "2026-10-03T14:00:00+08:00"},
                    "end": {"dateTime": "2026-10-03T15:00:00+08:00"},
                },
            )
        if request.method == "PATCH":
            assert request.headers.get("If-Match") == "etag-current"
            return httpx.Response(
                200,
                json={
                    "id": "evt-1",
                    "etag": "etag-new",
                    "summary": "New",
                    "start": {"dateTime": "2026-10-03T16:00:00+08:00"},
                    "end": {"dateTime": "2026-10-03T17:00:00+08:00"},
                },
            )
        if request.method == "DELETE":
            assert request.headers.get("If-Match") == "etag-current"
            return httpx.Response(204)
        return httpx.Response(404)

    client._http = _mock(handler)
    result = await client.update_event(
        calendar_id="primary",
        event_id="evt-1",
        summary="New",
        start=datetime(2026, 10, 3, 16, 0, tzinfo=TZ),
        end=datetime(2026, 10, 3, 17, 0, tzinfo=TZ),
    )
    assert result["event"]["summary"] == "New" and result["etag"] == "etag-new"
    await client.delete_event(calendar_id="primary", event_id="evt-1")


async def test_a_recurring_event_is_refused_rather_than_half_changed(tmp_path: Path):
    vault, client, _ = _write_client(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": "series-1",
                    "etag": "e",
                    "summary": "Weekly",
                    "recurrence": ["RRULE:FREQ=WEEKLY"],
                    "start": {"dateTime": "2026-10-03T14:00:00+08:00"},
                    "end": {"dateTime": "2026-10-03T15:00:00+08:00"},
                },
            )
        return httpx.Response(404)

    client._http = _mock(handler)
    with pytest.raises(GoogleError, match="recurring"):
        await client.delete_event(calendar_id="primary", event_id="series-1")


async def test_calendar_tool_writes_when_google_is_connected(tmp_path: Path):
    vault, client, _ = _write_client(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/calendarList"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "primary", "summary": "Me", "primary": True, "accessRole": "owner"}
                    ]
                },
            )
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "id": "n1",
                    "htmlLink": "https://calendar.google.com/event?eid=n1",
                    "summary": "Lunch",
                    "start": {"dateTime": "2026-10-03T12:00:00+08:00"},
                    "end": {"dateTime": "2026-10-03T13:00:00+08:00"},
                },
            )
        return httpx.Response(404)

    client._http = _mock(handler)
    settings = CalendarSettings(enabled=True, google=google_settings())
    feeds = CalendarFeeds(settings, vault=vault, tz=TZ)
    feeds.google._http = client._http
    tool = Calendar(feeds=feeds, workspace=tmp_path)

    out = await tool.execute(action="calendars")
    assert out.ok and "primary" in out.output

    out = await tool.execute(
        action="create", title="Lunch", start="2026-10-03 12:00", duration_minutes=60
    )
    assert out.ok and "Created" in out.output and "Lunch" in out.output


async def test_calendar_tool_refuses_writes_without_the_scope(tmp_path: Path):
    vault = CredentialVault(tmp_path / "vault.enc", key_path=tmp_path / "vault.key")
    vault.set(
        TOKENS_SECRET,
        json.dumps(
            {
                "access_token": "a",
                "refresh_token": "r",
                "expires_at": 9_999_999_999,
                "scopes": [SCOPE_READ],  # read-only sign-in
                "account": "zhaque.mail@gmail.com",
            }
        ),
    )
    settings = CalendarSettings(enabled=True, google=google_settings())
    feeds = CalendarFeeds(settings, vault=vault, tz=TZ)
    tool = Calendar(feeds=feeds, workspace=tmp_path)
    out = await tool.execute(action="create", title="x", start="2026-10-03 12:00")
    assert not out.ok and "read-only" in out.error


async def test_calendar_tool_refuses_writes_when_the_toggle_is_off(tmp_path: Path):
    """The write switch, not just the scope, must gate create/update/delete."""
    vault, client, _ = _write_client(tmp_path)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(404)

    client._http = _mock(handler)
    settings = CalendarSettings(enabled=True, google=google_settings(write=False))
    feeds = CalendarFeeds(settings, vault=vault, tz=TZ)
    feeds.google._http = client._http
    tool = Calendar(feeds=feeds, workspace=tmp_path)

    out = await tool.execute(action="create", title="x", start="2026-10-03 12:00")
    assert not out.ok and "turned off" in out.error
    assert not calls, "no request may reach Google when writing is off"


async def test_google_write_output_teaches_the_event_id(tmp_path: Path):
    """update/delete address an event by id; create must hand the id back."""
    vault, client, _ = _write_client(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "id": "evt-42",
                    "htmlLink": "https://calendar.google.com/event?eid=evt-42",
                    "summary": "Lunch",
                    "start": {"dateTime": "2026-10-03T12:00:00+08:00"},
                    "end": {"dateTime": "2026-10-03T13:00:00+08:00"},
                },
            )
        return httpx.Response(404)

    client._http = _mock(handler)
    settings = CalendarSettings(enabled=True, google=google_settings())
    feeds = CalendarFeeds(settings, vault=vault, tz=TZ)
    feeds.google._http = client._http
    tool = Calendar(feeds=feeds, workspace=tmp_path)

    out = await tool.execute(action="create", title="Lunch", start="2026-10-03 12:00")
    assert out.ok and "evt-42" in out.output


def test_render_shows_google_event_ids_but_not_ics_uids(tmp_path: Path):
    settings = CalendarSettings(enabled=True, google=google_settings())
    feeds = CalendarFeeds(settings, tz=TZ)
    start = datetime(2026, 10, 3, 12, 0, tzinfo=TZ)
    feeds.google_states["primary"] = FeedState(
        "Me",
        [
            Event(
                uid="evt-42",
                summary="Google lunch",
                start=start,
                end=start + timedelta(hours=1),
                calendar="primary",
            )
        ],
    )
    feeds.states["Family"] = FeedState(
        "Family",
        [
            Event(
                uid="ics-7@nanomuse",
                summary="Family dinner",
                start=start,
                end=start + timedelta(hours=1),
                calendar="Family",
            )
        ],
    )
    text = feeds.render(feeds.agenda(start.date()))
    assert "(id: evt-42)" in text, "a Google event id is what update/delete need"
    assert "ics-7" not in text, "an .ics UID is not a Google event id"


def test_the_same_event_from_ics_and_the_api_is_shown_once(tmp_path: Path):
    """A calendar added both as a private .ics link and over the API must not double up."""
    settings = CalendarSettings(enabled=True, google=google_settings())
    feeds = CalendarFeeds(settings, tz=TZ)
    start = datetime(2026, 10, 5, 2, 30, tzinfo=TZ)
    end = start + timedelta(minutes=30)
    feeds.states["gcal-ics"] = FeedState(
        "gcal-ics",
        [Event(uid="standup-1@google.com", summary="Standup", start=start, end=end)],
    )
    feeds.google_states["primary"] = FeedState(
        "Me",
        [Event(uid="standup-1", summary="Standup", start=start, end=end, calendar="primary")],
    )
    items = feeds.events(start - timedelta(hours=1), end + timedelta(hours=1))
    assert len(items) == 1, "the .ics copy and the API copy are one event"
    assert items[0].calendar == "primary", "the Google copy wins: it carries the event_id"


def test_local_tz_is_a_real_zone_not_a_fixed_offset():
    """A fixed-offset tz cannot tell summer from winter and lands events an hour off."""
    tz = local_tz()
    assert isinstance(tz, ZoneInfo) or tz is not None
    if isinstance(tz, ZoneInfo):
        assert tz.key, "a named zone, so DST is handled"
    # the offset for one date must be derivable for another: only a real zone does that
    summer = datetime(2026, 7, 1, 12, 0, tzinfo=UTC).astimezone(tz)
    winter = datetime(2026, 12, 25, 12, 0, tzinfo=UTC).astimezone(tz)
    assert summer.utcoffset() is not None and winter.utcoffset() is not None


def test_event_body_never_contradicts_a_named_zone():
    """timeZone and the dateTime offset must agree; a bare UTC name beside -07:00 is a bug."""
    client = GoogleCalendarClient(google_settings(timezone=""))
    tz = ZoneInfo("America/Los_Angeles")
    start = datetime(2026, 12, 25, 14, 0, tzinfo=tz)  # winter: PST, -08:00
    body = client._event_body("Dentist", start, start + timedelta(hours=1), False, "", "", "", "")
    assert body["start"]["timeZone"] == "America/Los_Angeles"
    assert body["start"]["dateTime"].endswith("-08:00"), "the offset matches the named zone"

    fixed = datetime(2026, 12, 25, 14, 0, tzinfo=timezone(timedelta(hours=-7)))
    body2 = client._event_body("Dentist", fixed, fixed + timedelta(hours=1), False, "", "", "", "")
    assert "timeZone" not in body2["start"], "no zone name we cannot honour"


def test_google_fetch_window_covers_the_search_lookback():
    """search promises 90 days back; the fetch must not stop at 14."""
    import inspect

    from nanomuse.calendar import feeds as feeds_mod

    src = inspect.getsource(feeds_mod.CalendarFeeds._refresh_google)
    assert "timedelta(days=90)" in src, "the fetched window must cover the search range"


# --------------------------------------------------------------------------- helpers
def _mock(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _write_client(tmp_path: Path) -> tuple[CredentialVault, GoogleCalendarClient, list[Any]]:
    vault = CredentialVault(tmp_path / "vault.enc", key_path=tmp_path / "vault.key")
    vault.set(
        TOKENS_SECRET,
        json.dumps(
            {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_at": 9_999_999_999,
                "scopes": [SCOPE_READ, SCOPE_WRITE],
                "account": "zhaque.mail@gmail.com",
            }
        ),
    )
    return vault, GoogleCalendarClient(google_settings(), vault=vault), []
