"""Google Calendar, over the Calendar API v3 with OAuth 2.0.

The ``.ics`` connector (``feeds.py``) reads a calendar through a private link and never
writes. This module is the other half: the user signs in with Google once, and the agent
reads *and* changes their calendars through the API — list calendars, list events, and
create / update / delete an event. It is the same shape OpenMuse uses.

Tokens live in the credential vault as one JSON blob (``GOOGLE_CALENDAR_TOKENS``); the
model only ever sees the placeholder. The OAuth dance is PKCE, with a loopback redirect
back into this same server (``/api/google/callback``), which is what Google allows for a
desktop app without a client secret leak.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from datetime import time as dtime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import httpx

from nanomuse.calendar.ics import Event, local_tz
from nanomuse.logger import logger

if TYPE_CHECKING:
    import asyncio

    from nanomuse.config import GoogleCalendarSettings
    from nanomuse.vault import CredentialVault

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"

# Read the calendar list and events; write events. ``calendar.events`` is the narrow write
# scope (it can change events, not the calendar itself or its ACLs).
SCOPE_READ = "https://www.googleapis.com/auth/calendar.events.readonly"
SCOPE_LIST = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
SCOPE_WRITE = "https://www.googleapis.com/auth/calendar.events"

TOKENS_SECRET = "GOOGLE_CALENDAR_TOKENS"
STATE_TTL = 10 * 60  # seconds a pending sign-in is valid
MAX_EVENTS = 2500  # a single window will not return more than this, however many pages
MAX_PAGES = 25  # …or more than this many pages, whichever comes first


class GoogleError(RuntimeError):
    """Something Google refused, or the network did. The message is shown to the user."""


def _now() -> float:
    return time.time()


@dataclass
class GoogleCalendar:
    id: str
    name: str
    primary: bool = False
    timezone: str = ""
    access_role: str = ""

    @property
    def writable(self) -> bool:
        return self.access_role in ("owner", "writer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "primary": self.primary,
            "timezone": self.timezone,
            "access_role": self.access_role,
            "writable": self.writable,
        }


@dataclass
class _Pending:
    verifier: str
    scopes: list[str]
    write: bool
    expires_at: float


class GoogleCalendarClient:
    """The signed-in Google Calendar session: tokens, refresh, and the API calls.

    One instance is created per app run (``CalendarFeeds`` holds it) and is cheap to keep:
    the access token is cached in memory and refreshed only when it is about to expire.
    """

    def __init__(
        self,
        settings: GoogleCalendarSettings,
        vault: CredentialVault | None = None,
        tz: tzinfo | None = None,
        http: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        self.vault = vault
        self.tz: tzinfo = tz or local_tz()
        self._http = http
        self._tokens: dict[str, Any] | None = None
        self._pending: dict[str, _Pending] = {}
        self._lock: asyncio.Lock | None = None  # made lazily so import needs no event loop

    # ------------------------------------------------------------------ plumbing
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _asyncio_lock(self):  # noqa: ANN202
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        return self._lock

    @property
    def configured(self) -> bool:
        """Whether a client id/secret and a redirect are set — sign-in is possible."""
        return bool(self.settings.client_id and self._secret() and self.settings.redirect_uri)

    def _secret(self) -> str:
        """The client secret, resolving a ``{{vault:…}}`` placeholder from the vault."""
        value = self.settings.client_secret
        if self.vault is not None and self.vault.has_placeholders(value):
            try:
                return str(self.vault.resolve(value))
            except Exception:  # noqa: BLE001 - a missing secret means "not configured"
                return ""
        return value

    @property
    def connected(self) -> bool:
        return bool(self.tokens())

    def tokens(self) -> dict[str, Any] | None:
        if self._tokens is None and self.vault is not None:
            raw = self.vault.get(TOKENS_SECRET)
            if raw:
                try:
                    self._tokens = json.loads(raw)
                except ValueError:
                    logger.warning("google calendar tokens are unreadable; sign in again")
                    self._tokens = {}
        return self._tokens or None

    def _save_tokens(self, tokens: dict[str, Any]) -> None:
        self._tokens = tokens
        if self.vault is not None:
            self.vault.set(TOKENS_SECRET, json.dumps(tokens))

    def status(self) -> dict[str, Any]:
        t = self.tokens()
        return {
            "configured": self.configured,
            "connected": bool(t),
            "account": (t or {}).get("account", ""),
            "scopes": (t or {}).get("scopes", []),
            "can_write": bool(t) and SCOPE_WRITE in (t or {}).get("scopes", []),
        }

    # ------------------------------------------------------------------ OAuth
    def _scopes(self, write: bool) -> list[str]:
        scopes = [SCOPE_READ, SCOPE_LIST]
        if write:
            scopes.append(SCOPE_WRITE)
        return scopes

    def authorize_url(self, write: bool = False) -> str:
        """A URL the user opens to grant access; the callback finishes the sign-in."""
        if not self.configured:
            raise GoogleError(
                "Google sign-in is not set up yet: add the client id and secret first."
            )
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        state = secrets.token_urlsafe(24)
        scopes = self._scopes(write)
        self._pending[state] = _Pending(verifier, scopes, write, _now() + STATE_TTL)
        # drop anything long past its window
        for key in [k for k, p in self._pending.items() if p.expires_at < _now()]:
            self._pending.pop(key, None)
        params = {
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def exchange(self, state: str, code: str) -> dict[str, Any]:
        """Finish a sign-in: check ``state``, swap ``code`` for tokens, store them."""
        pending = self._pending.pop(state, None)
        if pending is None or pending.expires_at < _now():
            raise GoogleError("This sign-in link expired or was already used. Start again.")
        if not code:
            raise GoogleError("Google did not return an authorization code.")
        data = {
            "client_id": self.settings.client_id,
            "client_secret": self._secret(),
            "redirect_uri": self.settings.redirect_uri,
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": pending.verifier,
        }
        try:
            response = await self._client().post(
                TOKEN_URL, data=data, headers={"Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise GoogleError(f"Could not reach Google: {exc}") from exc
        if response.status_code != 200:
            raise GoogleError("Google refused the sign-in. Try connecting again.")
        token = response.json()
        access = str(token.get("access_token") or "")
        if not access:
            raise GoogleError("Google returned no access token.")
        scopes = str(token.get("scope") or " ".join(pending.scopes)).split()
        account = await self._account_email(access)
        if not account:
            # userinfo needs the openid scope, which this client does not ask for; the primary
            # calendar's id is the account's e-mail, so it is a free fallback.
            account = await self._primary_email(access)
        previous = self.tokens() or {}
        refresh = token.get("refresh_token")
        if not refresh and account and previous.get("account") == account:
            refresh = previous.get("refresh_token")
        self._save_tokens(
            {
                "access_token": access,
                "refresh_token": refresh or "",
                "expires_at": _now() + float(token.get("expires_in") or 3600),
                "scopes": scopes,
                "account": account,
            }
        )
        logger.info("google calendar connected for {}", account or "(unknown account)")
        return self.status()

    async def _account_email(self, access_token: str) -> str:
        """The signed-in address, from the OpenID userinfo endpoint (best effort)."""
        try:
            response = await self._client().get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if response.status_code == 200:
                return str(response.json().get("email") or "")
        except (httpx.HTTPError, ValueError):
            pass
        return ""

    async def _primary_email(self, access_token: str) -> str:
        """The address behind the token, read from the primary calendar's id (best effort)."""
        try:
            response = await self._client().get(
                f"{CALENDAR_API}/users/me/calendarList/primary",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if response.status_code == 200:
                return str(response.json().get("id") or "")
        except (httpx.HTTPError, ValueError):
            pass
        return ""

    async def ensure_account(self) -> str:
        """Backfill the signed-in address once, when a sign-in could not resolve it."""
        tokens = self.tokens()
        if not tokens:
            return ""
        if tokens.get("account"):
            return str(tokens["account"])
        try:
            account = await self._primary_email(await self.access_token())
        except GoogleError:
            return ""
        if account:
            tokens["account"] = account
            self._save_tokens(tokens)
            logger.info("google calendar account resolved as {}", account)
        return account

    async def access_token(self) -> str:
        """A valid access token, refreshed when it is within a minute of expiring."""
        async with self._asyncio_lock():
            tokens = self.tokens()
            if not tokens:
                raise GoogleError("Google Calendar is not connected. Sign in first.")
            if float(tokens.get("expires_at") or 0) - 60 > _now():
                return str(tokens["access_token"])
            refresh = tokens.get("refresh_token")
            if not refresh:
                raise GoogleError("The Google session expired. Connect again.")
            data = {
                "client_id": self.settings.client_id,
                "client_secret": self._secret(),
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            }
            try:
                response = await self._client().post(
                    TOKEN_URL, data=data, headers={"Accept": "application/json"}
                )
            except httpx.HTTPError as exc:
                raise GoogleError(f"Could not reach Google: {exc}") from exc
            if response.status_code != 200:
                # a revoked or expired refresh token: make the user sign in again
                raise GoogleError("The Google session expired. Connect again.")
            fresh = response.json()
            tokens["access_token"] = fresh.get("access_token", "")
            tokens["expires_at"] = _now() + float(fresh.get("expires_in") or 3600)
            if fresh.get("scope"):
                tokens["scopes"] = str(fresh["scope"]).split()
            self._save_tokens(tokens)
            return str(tokens["access_token"])

    async def disconnect(self) -> None:
        tokens = self.tokens()
        if tokens and tokens.get("access_token"):
            try:  # best effort: revoke at Google, then forget locally either way
                await self._client().post(
                    REVOKE_URL,
                    data={"token": tokens.get("refresh_token") or tokens["access_token"]},
                )
            except httpx.HTTPError:
                pass
        self._tokens = {}
        if self.vault is not None:
            self.vault.delete(TOKENS_SECRET)

    # ------------------------------------------------------------------ requests
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        token = await self.access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        url = path if path.startswith("http") else f"{CALENDAR_API}{path}"
        try:
            response = await self._client().request(
                method, url, params=params, json=body, headers=headers
            )
        except httpx.HTTPError as exc:
            raise GoogleError(f"Could not reach Google: {exc}") from exc
        if response.status_code == 401:
            raise GoogleError("The Google session expired. Connect again.")
        if response.status_code == 404:
            raise GoogleError("That calendar or event no longer exists.")
        if response.status_code == 412:
            raise GoogleError("That event changed since it was read. Look it up again and retry.")
        if response.status_code >= 400:
            detail = ""
            try:
                detail = str(response.json().get("error", {}).get("message", ""))[:200]
            except (ValueError, AttributeError):
                detail = response.text[:200]
            raise GoogleError(f"Google refused the request ({response.status_code}): {detail}")
        if method == "DELETE" or response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise GoogleError("Google returned an unreadable response.") from exc

    # ------------------------------------------------------------------ reading
    async def list_calendars(self) -> list[GoogleCalendar]:
        out: list[GoogleCalendar] = []
        page: str | None = None
        for _ in range(10):
            params: dict[str, Any] = {"maxResults": 250}
            if page:
                params["pageToken"] = page
            data = await self._request("GET", "/users/me/calendarList", params=params)
            for item in data.get("items", []):
                out.append(
                    GoogleCalendar(
                        id=str(item.get("id", "")),
                        name=str(item.get("summaryOverride") or item.get("summary") or "Calendar"),
                        primary=bool(item.get("primary")),
                        timezone=str(item.get("timeZone") or ""),
                        access_role=str(item.get("accessRole") or ""),
                    )
                )
            page = data.get("nextPageToken")
            if not page:
                break
        # the primary calendar first, then by name
        out.sort(key=lambda c: (not c.primary, c.name.lower()))
        return out

    async def list_events(
        self, calendar_id: str, time_min: datetime, time_max: datetime
    ) -> list[Event]:
        """Every event in the window, recurring rules already expanded by Google."""
        params = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 2500,
            "timeMin": time_min.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "timeMax": time_max.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        events: list[Event] = []
        page: str | None = None
        for _ in range(MAX_PAGES):
            if page:
                params["pageToken"] = page
            data = await self._request(
                "GET", f"/calendars/{_quote(calendar_id)}/events", params=params
            )
            for item in data.get("items", []):
                parsed = self._to_event(item, calendar_id)
                if parsed is not None:
                    events.append(parsed)
                if len(events) >= MAX_EVENTS:
                    return events
            page = data.get("nextPageToken")
            if not page:
                break
        return events

    def _to_event(self, item: dict[str, Any], calendar_id: str) -> Event | None:
        if str(item.get("status") or "") == "cancelled":
            return None
        start_raw = item.get("start") or {}
        end_raw = item.get("end") or {}
        all_day = "date" in start_raw
        try:
            start = self._parse_when(start_raw, all_day)
            end = self._parse_when(end_raw, all_day)
        except (ValueError, TypeError):
            return None
        if start is None:
            return None
        if end is None:
            end = start + (timedelta(days=1) if all_day else timedelta(hours=1))
        return Event(
            uid=str(item.get("id") or item.get("iCalUID") or ""),
            summary=str(item.get("summary") or "(no title)"),
            start=start,
            end=end,
            all_day=all_day,
            location=str(item.get("location") or ""),
            description=str(item.get("description") or ""),
            calendar=calendar_id,
        )

    def _parse_when(self, raw: dict[str, Any], all_day: bool) -> datetime | None:
        if all_day:
            value = raw.get("date")
            if not value:
                return None
            return datetime.combine(date.fromisoformat(value), dtime.min, tzinfo=self.tz)
        value = raw.get("dateTime")
        if not value:
            return None
        text = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=self.tz)

    # ------------------------------------------------------------------ writing
    async def create_event(
        self,
        *,
        calendar_id: str,
        summary: str,
        start: datetime,
        end: datetime,
        all_day: bool = False,
        location: str | None = None,
        description: str | None = None,
        timezone: str = "",
        recurrence: str = "",
    ) -> dict[str, Any]:
        body = self._event_body(
            summary, start, end, all_day, location, description, timezone, recurrence
        )
        data = await self._request(
            "POST",
            f"/calendars/{_quote(calendar_id)}/events",
            params={"sendUpdates": "all"},
            body=body,
        )
        return self._result(data, calendar_id)

    async def update_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        summary: str,
        start: datetime,
        end: datetime,
        all_day: bool = False,
        location: str = "",
        description: str = "",
        timezone: str = "",
        expected_etag: str = "",
    ) -> dict[str, Any]:
        current = await self._read_single(calendar_id, event_id)
        if not expected_etag:
            expected_etag = str(current.get("etag") or "")
        body = self._event_body(
            summary, start, end, all_day, location, description, timezone, "", patch=True
        )
        data = await self._request(
            "PATCH",
            f"/calendars/{_quote(calendar_id)}/events/{_quote(event_id)}",
            params={"sendUpdates": "all"},
            body=body,
            extra_headers={"If-Match": expected_etag} if expected_etag else None,
        )
        return self._result(data, calendar_id)

    async def delete_event(
        self, *, calendar_id: str, event_id: str, expected_etag: str = ""
    ) -> None:
        current = await self._read_single(calendar_id, event_id)
        if not expected_etag:
            expected_etag = str(current.get("etag") or "")
        await self._request(
            "DELETE",
            f"/calendars/{_quote(calendar_id)}/events/{_quote(event_id)}",
            params={"sendUpdates": "all"},
            extra_headers={"If-Match": expected_etag} if expected_etag else None,
        )

    async def _read_single(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        """One event as it stands now; refuses a recurring series (change one occurrence)."""
        data = await self._request(
            "GET", f"/calendars/{_quote(calendar_id)}/events/{_quote(event_id)}"
        )
        if not isinstance(data, dict):
            raise GoogleError("That event no longer exists.")
        if data.get("recurrence") is not None or data.get("recurringEventId") is not None:
            raise GoogleError(
                "That is a recurring event. Open Google Calendar to change one occurrence "
                "or the whole series."
            )
        return data

    def _event_body(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        all_day: bool,
        location: str | None,
        description: str | None,
        timezone: str,
        recurrence: str,
        patch: bool = False,
    ) -> dict[str, Any]:
        tz_name = timezone or getattr(start.tzinfo, "key", "") or self.settings.timezone
        if all_day:
            # on a patch the other shape is nulled, so all-day ↔ timed can be switched
            body: dict[str, Any] = {
                "start": {
                    "date": start.date().isoformat(),
                    **({"dateTime": None} if patch else {}),
                },
                "end": {"date": end.date().isoformat(), **({"dateTime": None} if patch else {})},
            }
        else:
            body = {
                "start": {
                    "dateTime": start.isoformat(),
                    **({"date": None} if patch else {}),
                },
                "end": {
                    "dateTime": end.isoformat(),
                    **({"date": None} if patch else {}),
                },
            }
            # Only name a zone we actually know: a "UTC" name beside a "-07:00" offset makes
            # Google read the event an hour off. With no name the offset in dateTime stands.
            if tz_name:
                body["start"]["timeZone"] = tz_name
                body["end"]["timeZone"] = tz_name
        body["summary"] = summary
        if location:
            body["location"] = location
        elif patch and location is not None:
            body["location"] = ""  # an explicit empty clears it; absent leaves it alone
        if description:
            body["description"] = description
        elif patch and description is not None:
            body["description"] = ""
        if recurrence:
            body["recurrence"] = [recurrence]
        return body

    def _result(self, data: dict[str, Any], calendar_id: str) -> dict[str, Any]:
        parsed = self._to_event(data, calendar_id)
        event: dict[str, Any] = {}
        if parsed is not None:
            event = {
                "uid": parsed.uid,
                "summary": parsed.summary,
                "start": parsed.start.isoformat(timespec="minutes"),
                "end": parsed.end.isoformat(timespec="minutes"),
                "all_day": parsed.all_day,
                "location": parsed.location,
                "description": parsed.description,
                "calendar": parsed.calendar,
            }
        return {
            "id": str(data.get("id") or ""),
            "etag": str(data.get("etag") or ""),
            "htmlLink": str(data.get("htmlLink") or ""),
            "event": event,
        }


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


__all__ = [
    "GoogleCalendar",
    "GoogleCalendarClient",
    "GoogleError",
    "SCOPE_LIST",
    "SCOPE_READ",
    "SCOPE_WRITE",
    "TOKENS_SECRET",
]
