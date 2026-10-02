"""The user's calendars, read from ``.ics`` feeds and kept in a small cache.

A feed is a URL (the private link every calendar app hands out) or a local file. Feeds
are fetched together, at most every ``refresh_minutes``; between fetches the cache
answers, so building a prompt or drawing the Feed costs nothing. The URL may be a
``{{vault:NAME}}`` placeholder — the link *is* the secret for most providers.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from nanomuse.calendar.google import GoogleCalendarClient, GoogleError
from nanomuse.calendar.ics import Event, Occurrence, day_bounds, expand, local_tz, parse_ics
from nanomuse.logger import logger

if TYPE_CHECKING:
    from nanomuse.config import CalendarSettings
    from nanomuse.vault import CredentialVault

MAX_FEED_BYTES = 8 * 1024 * 1024


@dataclass
class FeedState:
    name: str
    events: list[Event] = field(default_factory=list)
    fetched_at: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "events": len(self.events),
            "fetched_at": datetime.fromtimestamp(self.fetched_at)
            .astimezone()
            .isoformat(timespec="seconds")
            if self.fetched_at
            else None,
            "error": self.error,
        }


@dataclass
class Slot:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


class CalendarFeeds:
    def __init__(
        self,
        settings: CalendarSettings,
        vault: CredentialVault | None = None,
        cache_file: Path | None = None,
        tz: tzinfo | None = None,
    ):
        self.settings = settings
        self.vault = vault
        self.cache_file = cache_file
        self.tz: tzinfo = tz or local_tz()
        self.states: dict[str, FeedState] = {}
        # Google Calendar over the API: its own states, keyed by calendar id.
        self.google_states: dict[str, FeedState] = {}
        self.google = GoogleCalendarClient(settings.google, vault=vault, tz=self.tz)
        self._lock = asyncio.Lock()
        self._load_cache()

    # ------------------------------------------------------------------ cache
    def _load_cache(self) -> None:
        if self.cache_file is None or not self.cache_file.exists():
            return
        try:
            raw = json.loads(self.cache_file.read_text(encoding="utf-8"))
            for name, entry in raw.items():
                events = parse_ics(entry.get("ics", ""), self.tz, calendar=name)
                self.states[name] = FeedState(
                    name, events, float(entry.get("fetched_at", 0)), entry.get("error", "")
                )
        except (OSError, ValueError, AttributeError) as exc:  # a broken cache is just refetched
            logger.warning("calendar cache unreadable: {}", exc)

    def _save_cache(self, texts: dict[str, str]) -> None:
        if self.cache_file is None:
            return
        try:
            existing: dict[str, Any] = {}
            if self.cache_file.exists():
                existing = json.loads(self.cache_file.read_text(encoding="utf-8"))
            for name, state in self.states.items():
                entry = existing.get(name, {})
                if name in texts:
                    entry["ics"] = texts[name]
                entry["fetched_at"] = state.fetched_at
                entry["error"] = state.error
                existing[name] = entry
            for name in list(existing):
                if name not in self.states:
                    del existing[name]
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(existing), encoding="utf-8")
            self.cache_file.chmod(0o600)  # someone's whole calendar; keep it to this user
        except OSError as exc:
            logger.warning("calendar cache not written: {}", exc)

    # ------------------------------------------------------------------ fetching
    @property
    def google_enabled(self) -> bool:
        return bool(self.settings.google.enabled and self.google.configured)

    @property
    def configured(self) -> bool:
        return (self.settings.enabled and bool(self.settings.feeds)) or self.google.connected

    @property
    def fetched_at(self) -> float:
        return max(
            [s.fetched_at for s in self.states.values()]
            + [s.fetched_at for s in self.google_states.values()],
            default=0.0,
        )

    def stale(self) -> bool:
        return time.time() - self.fetched_at > self.settings.refresh_minutes * 60

    def _url(self, raw: str) -> str:
        url = raw
        if self.vault is not None:
            url = self.vault.resolve(raw, strict=False)
        if "{{" in url:
            raise ValueError("the link is a vault placeholder that is not set")
        url = url.strip()
        if url.lower().startswith("webcal://"):  # what iCloud and Outlook hand out
            url = "https://" + url[len("webcal://") :]
        return url

    async def _read(self, url: str) -> str:
        if url.startswith(("http://", "https://")):
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                async with client.stream(
                    "GET", url, headers={"User-Agent": "nanoMuse calendar"}
                ) as response:
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_FEED_BYTES:
                            raise ValueError("the feed is larger than 8 MB")
                        chunks.append(chunk)
                    return b"".join(chunks).decode("utf-8", errors="replace")
        if url.startswith("file://"):
            url = url[len("file://") :]
        return await asyncio.to_thread(Path(url).expanduser().read_text, "utf-8")

    async def refresh(self, force: bool = False) -> dict[str, Any]:
        """Fetch every feed (if stale or ``force``); each feed fails on its own."""
        async with self._lock:
            if not force and not self.stale():
                return self.status()
            if self.settings.enabled:
                await self._refresh_feeds()
            if self.google_enabled:
                await self._refresh_google()
            return self.status()

    async def _refresh_feeds(self) -> None:
        wanted = {f.name for f in self.settings.feeds}
        for name in list(self.states):
            if name not in wanted:
                del self.states[name]
        texts: dict[str, str] = {}
        for feed in self.settings.feeds:
            state = self.states.setdefault(feed.name, FeedState(feed.name))
            try:
                text = await self._read(self._url(feed.url))
                if "BEGIN:VCALENDAR" not in text[:2000]:
                    raise ValueError("not an iCalendar file (no BEGIN:VCALENDAR)")
                state.events = parse_ics(text, self.tz, calendar=feed.name)
                state.error = ""
                texts[feed.name] = text
            except (httpx.HTTPError, OSError, ValueError) as exc:
                state.error = f"{type(exc).__name__}: {exc}"[:200]
                logger.warning("calendar feed '{}' failed: {}", feed.name, state.error)
            state.fetched_at = time.time()
        self._save_cache(texts)

    async def _refresh_google(self) -> None:
        """Read every selected Google calendar over the API into ``google_states``."""
        g = self.settings.google
        try:
            calendars = await self.google.list_calendars()
        except GoogleError as exc:
            logger.warning("google calendar list failed: {}", exc)
            return
        wanted = [c for c in calendars if not g.calendar_ids or c.id in g.calendar_ids]
        # cover the whole search window (past 90 / next 180 days) so search never misses
        start = datetime.now(self.tz) - timedelta(days=90)
        end = datetime.now(self.tz) + timedelta(days=186)
        keep = {c.id for c in wanted}
        for cid in list(self.google_states):
            if cid not in keep:
                del self.google_states[cid]
        for calendar in wanted:
            state = self.google_states.setdefault(calendar.id, FeedState(calendar.name))
            state.name = calendar.name
            try:
                state.events = await self.google.list_events(calendar.id, start, end)
                state.error = ""
            except GoogleError as exc:
                state.error = str(exc)[:200]
                logger.warning("google calendar '{}' failed: {}", calendar.name, state.error)
            state.fetched_at = time.time()

    def status(self) -> dict[str, Any]:
        feeds = [self.states.get(f.name, FeedState(f.name)).to_dict() for f in self.settings.feeds]
        google = [s.to_dict() for s in self.google_states.values()]
        return {
            "enabled": self.settings.enabled or self.settings.google.enabled,
            "feeds": feeds + google,
            "ics_feeds": feeds,
            "google": {**self.google.status(), "calendars": google},
            "fetched_at": datetime.fromtimestamp(self.fetched_at)
            .astimezone()
            .isoformat(timespec="seconds")
            if self.fetched_at
            else None,
            "stale": self.stale(),
        }

    # ------------------------------------------------------------------ reading
    def events(self, start: datetime, end: datetime) -> list[Occurrence]:
        """Occurrences overlapping [start, end) across every feed and Google calendar."""
        all_events: list[Event] = []
        for state in self.states.values():
            all_events.extend(state.events)
        for state in self.google_states.values():
            all_events.extend(state.events)
        # in the user's zone, so the app and the model read the same clock as the user
        # (a Google feed hands out UTC; an all-day occurrence has no zone to convert)
        occurrences = [
            o
            if o.all_day
            else replace(o, start=o.start.astimezone(self.tz), end=o.end.astimezone(self.tz))
            for o in expand(all_events, start, end)
        ]
        return self._dedupe(occurrences)

    def _dedupe(self, items: list[Occurrence]) -> list[Occurrence]:
        """Drop one event that arrives twice, e.g. its private ``.ics`` link and the API.

        A Google event's ``.ics`` UID is ``<id>@google.com`` and the API id is ``<id>``, so
        normalising the UID catches the same event from both sources without touching two
        genuinely distinct events (they have distinct ids). With no UID, fall back to the
        exact shape. The Google-sourced copy wins, because only it carries a usable
        ``event_id`` for ``update`` / ``delete``.
        """
        order: list[tuple[Any, ...]] = []
        by_key: dict[tuple[Any, ...], Occurrence] = {}
        for o in items:
            if o.uid:
                key: tuple[Any, ...] = ("uid", o.uid.split("@")[0].lower(), o.start.isoformat())
            else:
                key = ("shape", o.summary.lower(), o.start.isoformat(), o.end.isoformat())
            existing = by_key.get(key)
            if existing is None:
                order.append(key)
                by_key[key] = o
            elif o.calendar in self.google_states and existing.calendar not in self.google_states:
                by_key[key] = o
        return [by_key[k] for k in order]

    def agenda(self, day: date, days: int = 1) -> list[Occurrence]:
        start, _ = day_bounds(day, self.tz)
        _, end = day_bounds(day + timedelta(days=days - 1), self.tz)
        return self.events(start, end)

    def search(
        self, query: str, around: date, days_back: int = 90, days_ahead: int = 180
    ) -> list[Occurrence]:
        start, _ = day_bounds(around - timedelta(days=days_back), self.tz)
        _, end = day_bounds(around + timedelta(days=days_ahead), self.tz)
        needle = query.strip().lower()
        return [
            o
            for o in self.events(start, end)
            if needle in o.summary.lower()
            or needle in o.location.lower()
            or needle in o.description.lower()
        ]

    def free_slots(
        self, day: date, min_minutes: int = 30, day_start: str = "09:00", day_end: str = "18:00"
    ) -> list[Slot]:
        """Gaps of at least ``min_minutes`` between timed events within the working hours."""
        h0, m0 = (int(p) for p in day_start.split(":"))
        h1, m1 = (int(p) for p in day_end.split(":"))
        base, _ = day_bounds(day, self.tz)
        cursor = base.replace(hour=h0, minute=m0)
        close = base.replace(hour=h1, minute=m1)
        busy = sorted(
            (o.start, o.end)
            for o in self.agenda(day)
            if not o.all_day and o.end > cursor and o.start < close
        )
        slots: list[Slot] = []
        for b_start, b_end in busy:
            if b_start - cursor >= timedelta(minutes=min_minutes):
                slots.append(Slot(cursor, min(b_start, close)))
            cursor = max(cursor, b_end)
        if close - cursor >= timedelta(minutes=min_minutes):
            slots.append(Slot(cursor, close))
        return slots

    def render(self, items: list[Occurrence], today: date | None = None) -> str:
        """The agenda as the model (and the CLI) read it: grouped by day, local times.

        A Google occurrence also carries its event id, because ``update`` and ``delete``
        address an event by id and this is the only place the model can learn one.
        """
        if not items:
            return "(no events)"
        today = today or datetime.now(self.tz).date()
        google_ids = {ev.uid for state in self.google_states.values() for ev in state.events}
        out: list[str] = []
        current: date | None = None
        for o in items:
            local = o.start.astimezone(self.tz)
            d = local.date()
            if d != current:
                current = d
                tag = (
                    " (today)"
                    if d == today
                    else " (tomorrow)"
                    if d == today + timedelta(days=1)
                    else ""
                )
                out.append(f"{d:%a %Y-%m-%d}{tag}")
            if o.all_day:
                span = (
                    "all day"
                    if (o.end - o.start) <= timedelta(days=1)
                    else f"all day → {(o.end - timedelta(days=1)).astimezone(self.tz):%m-%d}"
                )
            else:
                end_local = o.end.astimezone(self.tz)
                end_txt = (
                    f"{end_local:%H:%M}" if end_local.date() == d else f"{end_local:%m-%d %H:%M}"
                )
                span = f"{local:%H:%M}–{end_txt}"
            bits = [f"  {span:<14} {o.summary}"]
            if o.location:
                bits.append(f"@ {o.location}")
            if o.calendar and self._many_sources():
                bits.append(f"[{o.calendar}]")
            if o.uid in google_ids and o.uid:
                bits.append(f"(id: {o.uid})")
            out.append(" ".join(bits))
        return "\n".join(out)

    def _many_sources(self) -> bool:
        return (len(self.settings.feeds) + len(self.google_states)) > 1

    # ------------------------------------------------------------------ writing
    async def write_calendars(self) -> list[dict[str, Any]]:
        """The Google calendars the account can write to (for the app and the model)."""
        if not self.google.connected:
            return []
        try:
            calendars = await self.google.list_calendars()
        except GoogleError as exc:
            raise GoogleError(str(exc)) from exc
        return [c.to_dict() for c in calendars if c.writable]

    async def create_event(self, **kwargs: Any) -> dict[str, Any]:
        """Create an event on a Google calendar; the caller passes the event fields."""
        return await self.google.create_event(**kwargs)

    async def update_event(self, **kwargs: Any) -> dict[str, Any]:
        return await self.google.update_event(**kwargs)

    async def delete_event(self, **kwargs: Any) -> None:
        await self.google.delete_event(**kwargs)


__all__ = ["CalendarFeeds", "FeedState", "Slot"]
