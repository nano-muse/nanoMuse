"""One private, stateless desktop Feed operation on stdin/stdout, without a listening port."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from nanomuse.server.context_sources import connected_candidates
from nanomuse.server.preparations import fingerprint
from nanomuse.server.public_watches import add_candidates, edit_choices, observe_text, refresh_row
from nanomuse.server.watch_discovery import reference_watches

_LIMIT = 8 * 1024 * 1024


async def run(request: dict[str, Any]) -> dict[str, Any]:
    state = request["state"]
    if request.get("version") != 1 or not isinstance(state, dict):
        raise ValueError("Unsupported watch request.")
    rows = state.get("watches", {})
    if not isinstance(rows, dict) or len(rows) > 512:
        raise ValueError("Invalid watch state.")
    if request["op"] == "edit":
        args = request["edit"]
        if not isinstance(args, dict):
            raise ValueError("Invalid watch choice.")
        if set(args) == {"enabled"} and isinstance(args["enabled"], bool):
            edit_choices(state, enabled=args["enabled"])
        elif set(args) == {"share_public_updates"} and isinstance(
            args["share_public_updates"], bool
        ):
            edit_choices(state, share_public_updates=args["share_public_updates"])
        elif set(args) <= {"kind", "target", "action", "watch_id"} and all(
            isinstance(v, str) and len(v) <= 2048 for v in args.values()
        ):
            if not args.get("watch_id") and (args.get("action") or not args.get("kind")):
                raise ValueError("Invalid watch choice.")
            edit_choices(state, **args)
        else:
            raise ValueError("Invalid watch choice.")
    elif request["op"] in ("observe", "poll"):
        if state.get("enabled", True):
            messages = request.get("texts", [])
            if not isinstance(messages, list) or len(messages) > 16:
                raise ValueError("Invalid discovery batch.")
            now = datetime.now(UTC)
            for item in messages:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("text"), str)
                    or len(item["text"]) > 6000
                    or not isinstance(item.get("personal"), bool)
                    or not isinstance(item.get("turn"), str)
                    or len(item["turn"]) > 128
                    or not isinstance(item.get("at"), int)
                ):
                    raise ValueError("Invalid discovery input.")
                stamp = item["at"] / 1000
                if not (now - timedelta(days=30)).timestamp() <= stamp <= now.timestamp():
                    continue
                if item["personal"]:
                    if not item["turn"]:
                        raise ValueError("Missing turn.")
                    observe_text(
                        state,
                        item["text"],
                        turn=item["turn"],
                        now=datetime.fromtimestamp(stamp, UTC),
                    )
                else:
                    text = item["text"]
                    cutoff = max(state.get("discover_after", 0), now.timestamp() - 30 * 86400)
                    mentions = {
                        key for key, seen in state.get("mentions", {}).items() if seen[1] >= cutoff
                    }
                    candidates = list(connected_candidates(text))
                    candidates.extend(
                        c
                        for c in reference_watches(text)
                        if fingerprint(c.kind, c.target) in mentions
                    )
                    add_candidates(state, candidates, "connected")
            if request["op"] == "observe":
                return state
            due = sorted(
                (
                    r
                    for r in state.get("watches", {}).values()
                    if r["status"] == "active" and r.get("next", 0) <= now.timestamp()
                ),
                key=lambda r: r.get("next", 0),
            )[:3]
            await asyncio.gather(*(refresh_row(row, now) for row in due))
    else:
        raise ValueError("Unknown watch operation.")
    return state


def main() -> None:
    raw = sys.stdin.buffer.read(_LIMIT + 1)
    try:
        if len(raw) > _LIMIT:
            raise ValueError("Watch input is too large.")
        state = asyncio.run(run(json.loads(raw)))
        data = json.dumps({"version": 1, "state": state}, ensure_ascii=False).encode()
        if len(data) > _LIMIT:
            raise ValueError("Watch output is too large.")
    except (KeyError, ValueError, TypeError, AttributeError, RecursionError):
        # Source identifiers and excerpts are private. Never echo the request on a failure.
        data = b'{"version":1,"error":"invalid_watch_request"}'
    sys.stdout.buffer.write(data + b"\n")
