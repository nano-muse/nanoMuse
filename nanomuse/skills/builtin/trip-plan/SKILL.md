---
name: trip-plan
description: Draft a trip itinerary as a page in the workspace, adding packing and budget files when requested. Use when the user wants a trip plan, itinerary or packing list.
channel: mixed
metadata:
  author: nanoMuse
  version: "1"
---

# Trip plan

Put the itinerary in `trips/<place>-<yyyy-mm>/itinerary.html` when the month is known, or `trips/<place>-draft/itinerary.html` otherwise. Add `packing.html` only when requested, and `budget.csv` when a budget is requested or money is discussed. A simple itinerary request does not need extra files or a saved goal.

## Before anything

- For an itinerary draft, a destination and duration are enough to start. Use Day 1, Day 2 and Day 3 when dates are unknown, omit unrequested flights and exact fares, and state assumptions about pace or budget. Do not block a draft to collect dates, departure city, party size or trip purpose unless the requested result actually depends on them. Ask only for essential unresolved information, in one `ask_user` call after independent preparation.
- Use applicable confirmed preferences already supplied in context. Call `recall` only for missing relevant preferences when memory is enabled and the tool is available in this space. Do not ask again for known preferences, search other spaces or read files as a substitute for disabled memory.
- Check calendar conflicts only when dates are known and the user requests a conflict check, or an actual confirmed commitment is already relevant. Use `calendar` only if available and authorized. Other draft itineraries or goals are not confirmed bookings; mention possible overlap without forcing the user to choose dates before drafting.

## Research

- `web_search` for: how to get there and around, the weather in that season, opening days of the two or three things worth seeing, and anything that must be booked ahead. Two or three searches, then stop; `web_fetch` a page only when the search result is not enough.
- Prices and times only from pages you actually read. If you did not find something, say "check" next to it rather than inventing a figure.
- Rough dates are enough for a draft. Do not spend the trip-planning turn finding exact flights, fares or every transfer timetable. If searches fail, stop after the small research pass and create the itinerary with unverified details marked "check". Keep the reply about this trip, not unrelated goals or old tasks.
- Trains in China: real options come from the `12306__*` tools (the 12306 MCP server; the `train-tickets` skill says how; search only, no booking); the times and prices go into the itinerary and the budget. Without the server, the 12306 app on a connected phone the same way; without either, "check 12306" in the plan.
- Places and distances in China: when the `amap__maps_*` tools are there (the 高德 MCP server, see the `amap` skill), use them for the travel time between the day's places, the route to the station, and the forecast for the dates; the itinerary's "travel time between places" then comes from a map, not a guess.

## Itinerary (`itinerary.html`)

- One card per day: date and weekday, the area of town, morning / afternoon / evening, travel time between places, one alternative for bad weather.
- The first day is arrival and settling in; the last day ends when the transport leaves. Do not overfill: two anchors a day and free time.
- A "Before you go" box: bookings, documents, connections to arrange, with dates.
- Self-contained HTML, inline CSS, readable on a phone; no external resources.

## Packing list (`packing.html`)

- Grouped (documents, clothes for the weather you found, tech, toiletries, for the kids…), each item a checkbox that stays ticked when the page is reopened (localStorage).
- Sized to the trip: the number of days, the weather, laundry or not.

## Budget (`budget.csv`, when asked or when the user mentioned money)

- Columns: item, when, estimated, currency, booked (yes/no), note. One row per transport leg, night, and day of food; totals the user can change.

## Finish

- Reply with the shape of the trip in three or four lines and the file names; point out the calendar conflicts and the two things to book first.
- Offer, in one line, to make a goal from the "Before you go" list so the bookings get done and checked in on; if the user agrees, `goals` action=create with those steps and the departure date as the target.
- Never book, pay or send anything yourself; drafting an event with `calendar` action=draft for the departure is fine.
