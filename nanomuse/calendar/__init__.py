"""Calendar connector: ``.ics`` feeds read, expanded and searched; events drafted as files.

Google Calendar over OAuth (the Calendar API) lives in :mod:`nanomuse.calendar.google` and
is read *and* written through the same :class:`CalendarFeeds` facade.
"""

from nanomuse.calendar.feeds import CalendarFeeds, FeedState, Slot
from nanomuse.calendar.google import (
    TOKENS_SECRET,
    GoogleCalendar,
    GoogleCalendarClient,
    GoogleError,
)
from nanomuse.calendar.ics import Event, Occurrence, expand, make_ics, parse_ics

__all__ = [
    "CalendarFeeds",
    "Event",
    "FeedState",
    "GoogleCalendar",
    "GoogleCalendarClient",
    "GoogleError",
    "Occurrence",
    "Slot",
    "TOKENS_SECRET",
    "expand",
    "make_ics",
    "parse_ics",
]
