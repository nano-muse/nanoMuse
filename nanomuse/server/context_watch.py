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
from nanomuse.server.public_watches import PublicWatches
from nanomuse.server.waiting import personal_message
from nanomuse.triggers import MailWatcher

if TYPE_CHECKING:
    from nanomuse.server.service import MuseService

INTERVAL = 600
REVIEWS_PER_DAY = 4


class ContextWatch:
    def __init__(self, service: MuseService):
        self.service = service
        self.watches = PublicWatches(self)
        self.task: asyncio.Task[None] | None = None
        self.next_poll = 0.0
        self.listed: dict[str, str] = {}
        self.listed_for: tuple[str, int] | None = None

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
        scope = self.service._chat_followup_scope()
        state = self._load(scope)
        mail, calendar = self._bindings()
        defaults = {"mcp": state.get("mcp_on_connect", True)}
        for kind, binding in (("mail", mail), ("calendar", calendar)):
            if binding:
                defaults[kind] = state.get(kind) == binding
            else:
                defaults[kind] = state.get(kind + "_preference", state.get(kind) != "")
        return {
            "revision": fingerprint(
                scope,
                str(self.service.hub.account_epoch),
                state.get("generation", ""),
                mail,
                calendar,
            ),
            "on_connect": defaults if scope else None,
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
        scope = self.service._chat_followup_scope()
        if not scope:
            return []
        epoch = self.service.hub.account_epoch
        choices = await self.service.connections.context_resources()
        if self.service._chat_followup_scope() != scope or self.service.hub.account_epoch != epoch:
            return []
        self.listed_for = (scope, epoch)
        self.listed = {v["id"]: v["label"] for v in choices}
        return choices

    def configure(
        self, revision: str, mail: bool, calendar: bool, resources: list[str], local_context: bool
    ) -> dict[str, Any]:
        scope = self.service._chat_followup_scope()
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
        if state.get("resources") and not selected:
            state["mcp_on_connect"] = False
        removed = set(state.get("removed_resources", ())) | set(state.get("resources", {}))
        state["removed_resources"] = sorted(removed.difference(selected))
        if mb or state.get("mail"):
            self._set_source(state, "mail", mb, mail)
        if cb or state.get("calendar"):
            self._set_source(state, "calendar", cb, calendar)
        for field in ("mcp_seen", "mcp_facts"):
            state[field] = {k: v for k, v in state.get(field, {}).items() if k in selected}
        state.update(resources=selected, local_context=local_context)
        self._save_choices(scope, state)
        return self.view()

    @staticmethod
    def _set_source(state: dict[str, Any], kind: str, binding: str, enabled: bool) -> None:
        new_binding = binding if enabled else ""
        if state.get(kind) != new_binding:
            if kind == "mail":
                state.pop("cursor", None)
            else:
                for field in ("calendars_initialized", "calendar_seen", "calendar_facts"):
                    state.pop(field, None)
        state[kind] = new_binding
        state[kind + "_preference"] = enabled

    def connection_saved(self, kind: str, enabled: bool) -> None:
        # The connection form displayed this choice and its revision was checked before saving.
        # Only rebind the changed source. In particular, never inherit another source's consent.
        scope = self.service._chat_followup_scope()
        if not scope:
            return
        mb, cb = self._bindings()
        state = self._load(scope)
        self._set_source(state, kind, mb if kind == "mail" else cb, enabled)
        self._save_choices(scope, state)

    def disconnect_mail(self) -> None:
        scope = self.service._chat_followup_scope()
        state = self._load(scope)
        if state.get("mail"):
            self._set_source(state, "mail", "", True)
            self._save_choices(scope, state)

    def mcp_connected(self, revision: str, enabled: bool, resource: tuple[str, str] | None) -> None:
        scope = self.service._chat_followup_scope()
        if not scope or revision != self.view()["revision"]:
            return
        state = self._load(scope)
        selected = state.setdefault("resources", {})
        previous = state.get("mcp_on_connect", True)
        state["mcp_on_connect"] = enabled
        if enabled and resource and len(selected) < 6:
            key, label = resource
            if key not in state.get("removed_resources", ()) and key not in selected:
                selected[key] = label
                self._save_choices(scope, state)
                return
        if enabled != previous:
            self._save_choices(scope, state)

    def _save_choices(self, scope: str, state: dict[str, Any]) -> None:
        state["generation"] = uuid.uuid4().hex
        state.pop("checked_at", None)
        state.pop("unavailable", None)
        self._save(scope, state)
        self.next_poll = 0.0
        self.service.wake()

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
        if self.service._chat_followup_scope() == "local" and not svc.sync.account_id:
            for goal in svc.app.goals.list("active")[:5]:
                records.append(Source("goal", goal.id, goal.title[:240], False))
        return {
            fingerprint(s.kind, s.key): Source(s.kind, s.key, svc.app.vault.redact(s.text), False)
            for s in records
        }

    async def poll(self, now: datetime | None = None) -> None:
        """Read changes, then use one shared review and chat budget for every source."""
        svc = self.service
        scope = self.service._chat_followup_scope()
        state = self._load(scope)
        if not scope or not svc.profile.proactive:
            return

        def current_time() -> datetime:
            return now or datetime.now().astimezone()

        start = current_time()
        self.watches.discover(scope, start)
        if not (
            state.get("mail")
            or state.get("calendar")
            or state.get("resources")
            or self.watches.has_active(scope)
        ):
            return
        generation = state.get("generation")
        watch_revision = self.watches.revision(scope)
        epoch = svc.hub.account_epoch
        bindings = self._bindings()

        def current() -> bool:
            return (
                self.service._chat_followup_scope() == scope
                and svc.hub.account_epoch == epoch
                and self._load(scope).get("generation") == generation
                and self._bindings() == bindings
                and self.watches.revision(scope) == watch_revision
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
        self.watches.observe_connected(scope, samples, start)
        watch_revision = self.watches.revision(scope)
        await self.watches.refresh(scope, start)
        if not current():
            return
        public = self.watches.pending(scope, start)
        external: dict[str, Source] = {}
        changed = set(public)
        cal_seen = state.setdefault("calendar_seen", {})
        mcp_seen = state.setdefault("mcp_seen", {})
        facts = {kind: state.setdefault(kind + "_facts", {}) for kind in ("calendar", "mcp")}
        for s in samples:
            key = fingerprint(s.source, s.key)
            text = svc.app.vault.redact(s.text)
            record = Source(s.source, s.key, text, True, recorded_at=s.recorded_at, label=s.label)
            if not text.strip():
                if s.source == "mcp":
                    # A successful read of an empty board is a baseline too. The first entry
                    # can then be a change, even if the board was empty when selected.
                    mcp_seen[s.key] = record.revision
                    facts["mcp"][s.key] = []
                continue
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
        # Keep the IMAP batch first so saving its cursor never skips an unseen message.
        external.update({key: entry[0] for key, entry in public.items()})
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
        # Keep private context outside the entire review that can produce a shared message.
        # A changed private source takes the normal local-only review, even if a public source
        # is ultimately the only citation. Never infer sharing permission from a model response.
        share_token = (
            self.watches.sharing_token(scope) if changed and changed <= public.keys() else ""
        )
        local = self._local(start) if state.get("local_context") and not share_token else {}
        sources = (
            {key: value[0] for key, value in public.items()}
            if share_token
            else {**external, **local}
        )
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
            live.update({key: entry[0] for key, entry in self.watches.pending(scope, end).items()})
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
                text = finding.text
                if cited and cited[0] in public and (url := public[cited[0]][1]):
                    # The adapter supplies the link. The model only selects an evidence ID.
                    text += "\n\n" + url
                shared = (
                    bool(share_token)
                    and share_token == self.watches.sharing_token(scope)
                    and bool(cited)
                    and all(k in public for k in cited)
                )
                svc._deliver_context_message(
                    event_id, text, end, share_token=share_token if shared else ""
                )
                state["last_day"] = today
                state["sent"] = [finding.fingerprint, *recent][:100]
        reviewed_public = set(cited) if finding else changed
        self.watches.consume(scope, {external[k].key for k in reviewed_public if k in public})
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
