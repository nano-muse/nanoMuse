"""Account-scoped background review of changes in sources selected by the person."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any

from nanomuse.llm.factory import llm_ready
from nanomuse.logger import logger
from nanomuse.private import keep_private
from nanomuse.server import context_review, context_sources
from nanomuse.server.events import MAIN_THREAD
from nanomuse.server.preparations import Source, fingerprint
from nanomuse.server.waiting import personal_message
from nanomuse.triggers import MailWatcher

if TYPE_CHECKING:
    from nanomuse.server.service import MuseService

INTERVAL = 600
REVIEWS_PER_DAY = 4


class ContextWatch:
    def __init__(self, service: MuseService):
        self.service = service
        self.task: asyncio.Task[None] | None = None
        self.next_poll = 0.0
        self.listed: dict[str, str] = {}
        self.listed_for: tuple[str, int] | None = None

    def _scope(self) -> str:
        svc = self.service
        if svc.hub.account_transition.locked():
            return ""
        scope = svc._chat_followup_scope()
        if svc.hub.signed_in:
            account = (svc.hub.data.get("cloud") or {}).get("account_id")
            if not account or scope != f"account:{account}":
                return ""
        main = svc.threads.get(MAIN_THREAD)
        owner = svc.sync.owner_of(MAIN_THREAD)
        if (
            not main
            or main.device
            or main.remote_from
            or not svc.sync.visible(main)
            or (owner and scope != f"account:{owner}")
            or (main.main_of and scope != f"account:{main.main_of}")
        ):
            return ""
        return scope

    def _file(self, scope: str) -> Path:
        return self.service.data_dir / ("context-watch-" + fingerprint(scope)[:24] + ".json")

    def _load(self, scope: str) -> dict[str, Any]:
        # A corrupt settings file must never implicitly grant access.
        if not scope:
            return {}
        try:
            raw = json.loads(self._file(scope).read_text("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self, scope: str, state: dict[str, Any]) -> None:
        path = self._file(scope)
        with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            tmp = Path(stream.name)
        try:
            keep_private(tmp)
            tmp.write_text(json.dumps(state, ensure_ascii=False), "utf-8")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)

    def _bindings(self) -> tuple[str, str]:
        svc = self.service
        email = svc.settings.connectors.email
        resolve = svc.app.vault.resolve
        mail = (
            fingerprint(email.imap_host, str(email.imap_port), resolve(email.address, strict=False))
            if email.enabled and email.imap_host
            else ""
        )
        cal = svc.app.calendar
        calendar = (
            fingerprint(
                *sorted(
                    fingerprint(f.name, resolve(f.url, strict=False)) for f in cal.settings.feeds
                )
            )
            if cal.configured
            else ""
        )
        return mail, calendar

    def view(self) -> dict[str, Any]:
        scope = self._scope()
        state = self._load(scope)
        mail, calendar = self._bindings()
        return {
            "revision": fingerprint(
                scope,
                str(self.service.hub.account_epoch),
                state.get("generation", ""),
                mail,
                calendar,
            ),
            "available_mail": bool(mail and scope),
            "available_calendar": bool(calendar and scope),
            "mail": bool(mail and state.get("mail") == mail),
            "calendar": bool(calendar and state.get("calendar") == calendar),
            "local_context": bool(state.get("local_context")),
            "local_goals": scope == "local" and not self.service.sync.account_id,
            "checked_at": state.get("checked_at"),
            "unavailable": bool(state.get("unavailable")),
            "resources": [{"id": k, "label": v} for k, v in state.get("resources", {}).items()],
        }

    async def resources(self) -> list[dict[str, str]]:
        scope = self._scope()
        if not scope:
            return []
        epoch = self.service.hub.account_epoch
        choices = await self.service.connections.context_resources()
        if self._scope() != scope or self.service.hub.account_epoch != epoch:
            return []
        self.listed_for = (scope, epoch)
        self.listed = {v["id"]: v["label"] for v in choices}
        return choices

    def configure(
        self, revision: str, mail: bool, calendar: bool, resources: list[str], local_context: bool
    ) -> dict[str, Any]:
        scope = self._scope()
        view = self.view()
        if not scope or revision != view["revision"]:
            raise ValueError("The active account or settings changed. Open the settings again.")
        mb, cb = self._bindings()
        if (mail and not mb) or (calendar and not cb):
            raise ValueError("Connect this source first.")
        state = self._load(scope)
        known = dict(state.get("resources", {}))
        if self.listed_for == (scope, self.service.hub.account_epoch):
            known.update(self.listed)
        if len(resources) > 6 or any(r not in known for r in resources):
            raise ValueError("Select up to six listed resources.")
        selected = {k: known[k] for k in resources}
        new_mail, new_cal = mb if mail else "", cb if calendar else ""
        if state.get("mail") != new_mail:
            state.pop("cursor", None)
        if state.get("calendar") != new_cal:
            state.pop("calendars_initialized", None)
            state["calendar_seen"] = {}
            state["calendar_facts"] = {}
        for field in ("mcp_seen", "mcp_facts"):
            state[field] = {k: v for k, v in state.get(field, {}).items() if k in selected}
        state.update(
            generation=uuid.uuid4().hex,
            resources=selected,
            local_context=local_context,
            mail=new_mail,
            calendar=new_cal,
        )
        state.pop("checked_at", None)
        state.pop("unavailable", None)
        self._save(scope, state)
        self.next_poll = 0.0
        self.service.wake()
        return self.view()

    def tick(self) -> None:
        if time.monotonic() < self.next_poll or self.task is not None and not self.task.done():
            return
        self.next_poll = time.monotonic() + INTERVAL
        self.task = asyncio.create_task(self._bounded_poll(), name="connected-context")

    async def _bounded_poll(self) -> None:
        try:
            async with asyncio.timeout(100):
                await self.poll()
        except Exception as exc:
            # Connector errors can contain credentials or private excerpts.
            logger.warning("Connected context check deferred ({})", type(exc).__name__)

    def _can_speak(self, now: datetime) -> bool:
        svc = self.service
        main = svc.threads[MAIN_THREAD]
        if (
            not svc.profile.proactive
            or not 9 <= now.hour < 20
            or svc.profile.in_quiet_hours(now)
            or main.busy
            or not main.inbox.empty()
        ):
            return False
        today = now.date().isoformat()
        for event in reversed(main.timeline.events):
            if event.get("type") in ("assistant", "user"):
                try:
                    stamp = datetime.fromisoformat(event["ts"]).astimezone()
                except (KeyError, ValueError, TypeError):
                    return False
                if now - stamp < timedelta(minutes=10):
                    return False
                break
        # The user may have replied to an earlier outreach today.
        return not any(e.get("outreach_day") == today for e in main.timeline.events)

    def _local(self, now: datetime) -> dict[str, Source]:
        svc = self.service
        records: list[Source] = []
        for event in reversed(svc.threads[MAIN_THREAD].timeline.events[-120:]):
            if not personal_message(event) or not event.get("text") or not event.get("ts"):
                continue
            try:
                age = now - datetime.fromisoformat(event["ts"]).astimezone()
            except (ValueError, TypeError):
                continue
            if timedelta(0) <= age <= timedelta(days=7):
                records.append(Source("conversation", event["id"], str(event["text"])[:450], False))
                if len(records) >= 5:
                    break
        # Runtime goals have no Cloud account owner. The device-local scope can use them;
        # an account-backed review can only use that account's main chat.
        if self._scope() == "local" and not svc.sync.account_id:
            for goal in svc.app.goals.list("active")[:5]:
                records.append(Source("goal", goal.id, goal.title[:240], False))
        return {
            fingerprint(s.kind, s.key): Source(s.kind, s.key, svc.app.vault.redact(s.text), False)
            for s in records
        }

    async def poll(self, now: datetime | None = None) -> None:
        """Only digests and the IMAP cursor survive a poll. A failed review retries its inputs."""
        svc = self.service
        scope = self._scope()
        state = self._load(scope)
        if (
            not scope
            or not svc.profile.proactive
            or not (state.get("mail") or state.get("calendar") or state.get("resources"))
        ):
            return

        def current_time() -> datetime:
            return now or datetime.now().astimezone()

        start = current_time()
        generation = state["generation"]
        epoch = svc.hub.account_epoch
        bindings = self._bindings()

        def current() -> bool:
            return (
                self._scope() == scope
                and svc.hub.account_epoch == epoch
                and self._load(scope).get("generation") == generation
                and self._bindings() == bindings
                and svc.profile.proactive
            )

        samples: list[context_sources.ContextSample] = []
        old_cursor = state.get("cursor", {})
        cursor = old_cursor
        mail_unavailable = False
        if state.get("mail") and state["mail"] == bindings[0]:
            try:
                new_mail, cursor = await context_sources.mail_samples(
                    MailWatcher(svc.settings.connectors.email, vault=svc.app.vault), old_cursor
                )
                samples.extend(new_mail)
            except (OSError, RuntimeError, TimeoutError):
                mail_unavailable = True
        if not current():
            return
        if state.get("resources"):
            try:
                samples.extend(
                    await svc.connections.context_resource_samples(
                        list(state["resources"]), allowed=current
                    )
                )
            except (OSError, RuntimeError, TimeoutError):
                pass
        if not current():
            return
        calendars = svc.app.calendar
        selected_feeds = (
            {feed.name for feed in calendars.settings.feeds}
            if (state.get("calendar") and state["calendar"] == bindings[1])
            else set()
        )
        fresh_feeds = {
            name
            for name in selected_feeds
            if (feed := calendars.states.get(name))
            and not feed.error
            and 0 <= start.timestamp() - feed.fetched_at <= calendars.settings.refresh_minutes * 60
        }
        initialized = set(state.get("calendars_initialized", []))
        if fresh_feeds:
            samples.extend(context_sources.calendar_samples(calendars, start))
        external: dict[str, Source] = {}
        changed = set()
        cal_seen = state.setdefault("calendar_seen", {})
        mcp_seen = state.setdefault("mcp_seen", {})
        facts = {kind: state.setdefault(kind + "_facts", {}) for kind in ("calendar", "mcp")}
        for s in samples:
            key = fingerprint(s.source, s.key)
            text = svc.app.vault.redact(s.text)
            if not text.strip():
                continue
            record = Source(s.source, s.key, text, True, recorded_at=s.recorded_at, label=s.label)
            external[key] = record
            if s.source == "calendar" and fingerprint(s.calendar) not in initialized:
                cal_seen[s.key] = record.revision
                facts[s.source][s.key] = context_review.fact_hashes(record)
            elif s.source == "mcp" and s.key not in mcp_seen:
                mcp_seen[s.key] = record.revision
                facts[s.source][s.key] = context_review.fact_hashes(record)
            elif s.source == "mail" or record.revision != (
                cal_seen if s.source == "calendar" else mcp_seen
            ).get(s.key):
                changed.add(key)
        if fresh_feeds:
            state["calendars_initialized"] = sorted(
                initialized | {fingerprint(n) for n in fresh_feeds}
            )
        state["checked_at"] = start.isoformat(timespec="minutes")
        state["unavailable"] = bool(
            mail_unavailable
            or (state.get("mail") and state["mail"] != bindings[0])
            or (state.get("calendar") and (not selected_feeds or selected_feeds != fresh_feeds))
            or set(state.get("resources", {})) - {s.key for s in samples if s.source == "mcp"}
        )
        if not old_cursor or not any(s.source == "mail" for s in samples):
            state["cursor"] = cursor
        self._save(scope, state)
        today = start.date().isoformat()
        if (
            not changed
            or not self._can_speak(start)
            or state.get("last_day") == today
            or (state.get("budget_day") == today and state.get("calls", 0) >= REVIEWS_PER_DAY)
            or not llm_ready(svc.settings.llm, svc.app.vault, svc.data_dir)
        ):
            return
        # The judge always has room for eight changes. Process the whole (at most eight)
        # IMAP batch before advancing its cursor. Unreviewed calendar/resources remain pending.
        changed = set([k for k in external if k in changed][:8])
        previous = {
            k: facts[src.kind].get(src.key, []) for k, src in external.items() if src.kind in facts
        }
        local = self._local(start) if state.get("local_context") else {}
        sources = {**external, **local}
        # The model cites short IDs. Stable source identities and their hashes stay local.
        keys = {f"R{n}": key for n, key in enumerate(sources, 1)}
        state["calls"] = 1 + (state.get("calls", 0) if state.get("budget_day") == today else 0)
        state["budget_day"] = today
        self._save(scope, state)
        model = svc.app.llm
        finding = await context_review.review(
            model,
            {label: sources[k] for label, k in keys.items()},
            {label for label, k in keys.items() if k in changed},
            now=start,
            language=svc.feed_language(),
            previous_facts={label: previous[k] for label, k in keys.items() if k in previous},
        )
        end = current_time()
        if (
            not current()
            or svc.app.llm is not model
            or end.date() != start.date()
            or not self._can_speak(end)
        ):
            return
        if finding:
            cited = [keys[label] for label in finding.source_ids]
            # A calendar refresh or local edit can finish while the model is reading.
            live = self._local(end) if local else {}
            if fresh_feeds:
                for sample in context_sources.calendar_samples(svc.app.calendar, end):
                    live[fingerprint(sample.source, sample.key)] = Source(
                        sample.source, sample.key, svc.app.vault.redact(sample.text), True
                    )
            referenced_mcp = [sources[k].key for k in cited if sources[k].kind == "mcp"]
            if referenced_mcp:
                for sample in await svc.connections.context_resource_samples(
                    referenced_mcp, allowed=current
                ):
                    live[fingerprint(sample.source, sample.key)] = Source(
                        sample.source, sample.key, svc.app.vault.redact(sample.text), True
                    )
            end = current_time()
            if (
                not current()
                or svc.app.llm is not model
                or end.date() != start.date()
                or not self._can_speak(end)
                or any(
                    sources[k].kind != "mail"
                    and (k not in live or live[k].revision != sources[k].revision)
                    for k in cited
                )
            ):
                return
            recent = state.get("sent", [])
            event_id = "ctx_" + fingerprint(scope, finding.fingerprint)[:32]
            if finding.fingerprint not in recent and not svc.threads[MAIN_THREAD].timeline.get(
                event_id
            ):
                svc._deliver_context_message(event_id, finding.text, end)
                state["last_day"] = today
                state["sent"] = [finding.fingerprint, *recent][:100]
        state["cursor"] = cursor
        for k in changed:
            record = external[k]
            if record.kind in ("calendar", "mcp"):
                (cal_seen if record.kind == "calendar" else mcp_seen)[record.key] = record.revision
                facts[record.kind][record.key] = context_review.fact_hashes(record)
        if len(cal_seen) > 256:
            state["calendar_seen"] = dict(list(cal_seen.items())[-256:])
            state["calendar_facts"] = {
                k: facts["calendar"][k] for k in state["calendar_seen"] if k in facts["calendar"]
            }
        self._save(scope, state)
