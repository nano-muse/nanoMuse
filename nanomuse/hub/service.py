"""This computer on the hub: the Cloud account, the socket to the relay, what the other
devices may ask of it, and the side chats in which their tasks run.

Two directions (docs/every-device.md):

* **In.** Another device calls: a raw action (``shell``, ``files``, ``screen``…) runs at
  once (``hub/actions.py``); a ``task`` becomes a message in a side chat titled after the
  device that asked — visible here, so the person at this computer sees it run, can type
  into it and can stop it — and its progress, approvals and final answer travel back as
  hub events. An ``approve`` answers an approval card the run raised; ``stop`` ends it.
* **Out.** A side chat addressed to a device (``ask_device``) sends what is typed in it as a
  ``task`` to that device's Muse and shows the events that come back — tool chips, the
  approval cards (answered here, carried back as ``approve``), the final answer. The
  agent's own ``device_*`` and ``delegate`` tools go through :meth:`HubService.call`.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import re
import socket
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nanomuse.cloud import CLOUD_KEY, CloudClient, CloudError, model_url
from nanomuse.hub import actions
from nanomuse.hub.client import HubClient, HubError, IncomingCall
from nanomuse.hub.profile import ProfileSync
from nanomuse.logger import logger
from nanomuse.schema import RiskLevel
from nanomuse.sentinel.grants import grant_key, normalize_scope
from nanomuse.server.events import MAIN_THREAD, STOPPED_NOTICE, now_iso
from nanomuse.server.webui import current_thread
from nanomuse.ui import ApprovalRequest

if TYPE_CHECKING:
    from nanomuse.server.service import MuseService, Thread

TASK_TIMEOUT_S = 15 * 60
APPROVAL_TIMEOUT_S = 180
REMOTE_TASK_TIMEOUT_S = 10 * 60
_RISK_WORDS = {"safe": "safe", "low": "low", "moderate": "moderate", "sensitive": "sensitive"}
# Raw actions another device may ask of this computer that the person here agrees to first
# (once, or always for that device): what runs, reads or writes. ``info``, ``notify`` and the
# read-only looks at the coding agents' lists do not ask; a ``task`` runs in a side chat
# under this computer's own Sentinel.
GATED_ACTIONS = frozenset(
    {"shell", "files", "file.get", "file.put", "open", "screen", "coding.send", "coding.stop"}
)
REMOTE_CONTROL_TOOL = "remote_control"


class _RunStopped(Exception):
    """The run a `task` call was following was stopped before it answered."""


class HubService:
    def __init__(self, svc: MuseService):
        self.svc = svc
        self.client: HubClient | None = None
        self.cloud = CloudClient(self.settings.cloud.base_url, self._key())
        # the relay's last /v1/me (models with prices, usage)
        self.last_me: dict[str, Any] = {}
        # the account's chat models (ids), for the provider form; refreshed on sign-in and
        # whenever the form asks
        self.chat_models: list[str] = []
        # the account's hands models (ids), recommended first (contract C4)
        self.gui_models: list[str] = []
        # the relay's whole list as it came (chat, image and video models, with modalities)
        self.models: list[dict[str, Any]] = []
        # approval cards raised by *other* devices' runs, shown here: card id → (device id, approval id)
        self.remote_approvals: dict[str, tuple[str, str]] = {}
        # runs other devices asked for, by call id → the thread they run in
        self._incoming: dict[str, str] = {}
        # approval cards of those runs sent to the device that asked (approval id → device
        # id): the only cards a device may answer with ``approve``
        self._relayed_approvals: dict[str, str] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._pending_code: str = ""
        # the agent's name and look, shared with the account's other devices
        self.profile = ProfileSync(self)
        self._ensure_identity()

    # ------------------------------------------------------------------ settings & identity
    @property
    def settings(self):  # noqa: ANN201
        return self.svc.settings

    @property
    def data(self) -> dict[str, Any]:
        return self.svc.connections.data

    def _save(self) -> None:
        self.svc.connections._save()

    def _key(self) -> str:
        return self.svc.app.vault.get(CLOUD_KEY) or ""

    @property
    def signed_in(self) -> bool:
        return bool(self._key())

    def _ensure_identity(self) -> None:
        hub = dict(self.data.get("hub") or {})
        if not self.settings.hub.device_id:
            device_id = str(hub.get("device_id") or "") or "pc-" + uuid.uuid4().hex[:12]
            self.settings.hub.device_id = device_id
            if hub.get("device_id") != device_id:
                hub["device_id"] = device_id
                self.data["hub"] = hub
                self._save()

    @property
    def device_id(self) -> str:
        return self.settings.hub.device_id

    @property
    def device_name(self) -> str:
        return (self.settings.hub.name or socket.gethostname() or "computer")[:60]

    def _extra_actions(self) -> tuple[str, ...]:
        from nanomuse.coding.service import ACTIONS as CODING_ACTIONS

        return ("task", "stop", "approve", *CODING_ACTIONS)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        """Join the hub when the account is signed in and the hub is on."""
        await self._seed_from_env()
        if self.signed_in and self._model_has_no_key():
            # signed in, yet the model is still the bare default with no key (an account
            # from before sign-in set the model, a config reset): the relay is the model,
            # the same as the moment of signing in. Without this the first message ends in
            # the provider's "invalid api key".
            try:
                await self.use_as_model()
                logger.info("cloud account signed in and no model key set: the relay is the model")
            except Exception as exc:  # noqa: BLE001
                logger.warning("the relay could not be made the model: {}", exc)
        if self.signed_in:
            # the provider form's model list, without waiting for it: the relay may be slow
            # or away, and nothing else depends on the answer
            task = asyncio.ensure_future(self._refresh_chat_models_quietly())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        if self.signed_in and self.settings.hub.enabled:
            await self.join()
        if self.signed_in:
            # the look the account's other devices wear, when it moved while we were away
            self.profile.pull_soon()

    def _model_has_no_key(self) -> bool:
        """True when the configured model would be called with no key at all — not a local
        server (those take any key), not a vault reference, nothing typed in."""
        key = (
            self.settings.llm.api_key or (self.data.get("llm") or {}).get("api_key") or ""
        ).strip()
        if key:
            return False
        host = (
            (self.settings.llm.base_url or "")
            .split("://", 1)[-1]
            .split("/", 1)[0]
            .split(":", 1)[0]
            .lower()
        )
        return host not in (
            "localhost",
            "127.0.0.1",
            "::1",
            "0.0.0.0",
            "host.docker.internal",
        ) and not host.startswith(("192.168.", "10.", "172."))

    async def _refresh_chat_models_quietly(self) -> None:
        try:
            await self.refresh_chat_models()
        except Exception as exc:  # noqa: BLE001
            logger.debug("cloud models not listed: {}", exc)

    async def _seed_from_env(self) -> None:
        """A hosted runtime (nanoMuse Web) starts already signed in: the gateway that made the
        container passes the account key in ``NANOMUSE_CLOUD_KEY`` (``NANOMUSE_CLOUD_HINT`` /
        ``NANOMUSE_CLOUD_CHANNEL`` for the account page). The key goes into the vault like
        one typed in; the relay becomes the model when nothing else is configured; the first
        run is skipped, since the person signed in one page earlier. Nothing happens when the
        vault already holds a key."""
        key = os.environ.get("NANOMUSE_CLOUD_KEY", "").strip()
        if not key or self.signed_in:
            return
        self.svc.app.vault.set(CLOUD_KEY, key)
        self.data["cloud"] = {
            "base_url": self.cloud.base_url,
            "hint": os.environ.get("NANOMUSE_CLOUD_HINT", "").strip(),
            "channel": os.environ.get("NANOMUSE_CLOUD_CHANNEL", "").strip(),
            "signed_in_at": now_iso(),
        }
        if not (self.settings.llm.api_key or (self.data.get("llm") or {}).get("api_key")):
            with contextlib.suppress(CloudError, Exception):
                await self.use_as_model()
        if os.environ.get("NANOMUSE_ONBOARDED", "").strip().lower() in ("1", "true", "yes", "on"):
            self.data["onboarded"] = True
        self._save()
        logger.info("cloud account seeded from the environment")

    async def stop(self) -> None:
        """Leave the hub, end the profile's pending push or pull, then close the HTTP client —
        in that order, so that nothing is still talking to the relay when its client goes."""
        await self.leave()
        await self.profile.stop()
        await self.cloud.close()

    async def join(self) -> None:
        if not self.signed_in:
            return
        if self.client is not None and self.client.running:
            return
        self.cloud.api_key = self._key()
        self.client = HubClient(
            self.cloud.hub_url,
            self._key(),
            self.device_id,
            self.device_name,
            actions=[*actions.ACTIONS, *self._extra_actions()],
            kind="computer",
            on_call=self.on_call,
            on_devices=lambda _devices: self.publish(),
            on_state=lambda _state, _detail: self.publish(),
            on_profile=self.profile.on_frame,
            on_sync=self.svc.sync.on_frame,
        )
        self.client.start()
        self._sync_tools(True)
        self.publish()

    async def leave(self) -> None:
        client, self.client = self.client, None
        if client is not None:
            await client.stop()
        tasks = [t for t in self._tasks if not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            # the models refresh, the runs other devices asked for: ended, not left to finish
            # (and to reach for the relay) after this returns
            await asyncio.wait(tasks)
        self._sync_tools(False)
        self.publish()

    def _sync_tools(self, present: bool) -> None:
        """The `devices` / `device_*` / `delegate` tools exist while this computer is on the hub."""
        from nanomuse.tools.devices import DEVICE_TOOL_NAMES, device_tools

        tools = self.svc.app.tools
        if present and "devices" not in tools:
            tools.add(*device_tools(self, self.svc.ui, self.svc.workspace()))
        elif not present and "devices" in tools:
            for name in DEVICE_TOOL_NAMES:
                tools.remove(name)

    async def set_enabled(self, enabled: bool) -> None:
        self.settings.hub.enabled = bool(enabled)
        hub = dict(self.data.get("hub") or {})
        hub["enabled"] = bool(enabled)
        self.data["hub"] = hub
        self._save()
        if enabled:
            await self.join()
        else:
            await self.leave()

    def set_remote_control(self, on: bool) -> None:
        self.settings.hub.remote_control = bool(on)
        hub = dict(self.data.get("hub") or {})
        hub["remote_control"] = bool(on)
        self.data["hub"] = hub
        self._save()
        self.publish()

    async def rename(self, name: str) -> None:
        name = name.strip()[:60]
        if not name:
            raise ValueError("a name is required")
        self.settings.hub.name = name
        hub = dict(self.data.get("hub") or {})
        hub["name"] = name
        self.data["hub"] = hub
        self._save()
        if self.client is not None and self.client.connected.is_set():
            with contextlib.suppress(HubError):
                await self.client.rename(name)
        self.publish()

    async def forget(self, device_id: str) -> None:
        if self.client is None or not self.client.connected.is_set():
            raise HubError("disconnected", "not connected to the hub")
        await self.client.forget(device_id)

    # ------------------------------------------------------------------ the account
    async def request_code(self, identifier: str) -> None:
        identifier = identifier.strip()
        if not identifier:
            raise CloudError(400, "bad_identifier", "Enter a phone number or an e-mail address.")
        await self.cloud.request_code(identifier)
        self._pending_code = identifier

    async def verify(self, identifier: str, code: str, invite: str = "") -> dict[str, Any]:
        identifier = identifier.strip() or self._pending_code
        data = await self.cloud.verify(identifier, code.strip(), self.device_name, invite=invite)
        return await self._signed_in(data)

    async def login(self, identifier: str, password: str) -> dict[str, Any]:
        """Sign in with the account password instead of a code."""
        identifier = identifier.strip()
        if not identifier:
            raise CloudError(400, "bad_identifier", "Enter a phone number or an e-mail address.")
        if not password:
            raise CloudError(400, "password_required", "Enter the password.")
        data = await self.cloud.login(identifier, password, self.device_name)
        return await self._signed_in(data)

    async def _signed_in(self, data: dict[str, Any]) -> dict[str, Any]:
        key = str(data.get("api_key") or "")
        if not key:
            raise CloudError(502, "bad_key", "The relay returned no key.")
        self.last_me = {k: v for k, v in data.items() if k != "api_key"}
        self.svc.app.vault.set(CLOUD_KEY, key)
        account: dict[str, Any] = data["account"] if isinstance(data.get("account"), dict) else {}
        previous = self.svc.sync.account_id or str(
            (self.data.get("cloud") or {}).get("account_id") or ""
        )
        if previous and previous != str(account.get("id") or ""):
            # a different account (contract C10): the socket to the relay, its device list
            # and the account's models start over under the new key
            await self.leave()
            self.chat_models, self.gui_models, self.models = [], [], []
        self.data["cloud"] = {
            "base_url": self.cloud.base_url,
            "hint": str(account.get("hint") or ""),
            "channel": str(account.get("channel") or ""),
            "signed_in_at": now_iso(),
            "has_password": bool(account.get("has_password")),
            "account_id": str(account.get("id") or ""),
            "member": bool(account.get("member")),
            "any_model": bool(account.get("any_model")),
            # where the relay places the account ("cn" = mainland China; relay 0.17 says it
            # at the top of the sign-in answer, older relays not at all)
            "region": str(data.get("region") or account.get("region") or ""),
        }
        self._save()
        self._pending_code = ""
        self.cloud.api_key = key
        try:
            await self.refresh_chat_models()
        except CloudError:
            pass
        # The model client resolved its key when it was built. When the account's key is the
        # model's key (the Cloud preset), that client still holds the previous one — revoked,
        # or from a sign-in that ended — and every request would come back 401 until a
        # restart. Rebuild it with the fresh key; with no model configured at all, the account
        # becomes the model, as it does for a hosted runtime.
        if self._llm_is_cloud():
            self.svc.connections._swap_llm()
        elif self.settings.cloud.models and not (
            self.settings.llm.api_key or (self.data.get("llm") or {}).get("api_key")
        ):
            # not while the person switched the account's models off: a sign-in changes no slot
            with contextlib.suppress(CloudError, Exception):
                await self.use_as_model()
        if self.settings.hub.enabled:
            await self.join()
        self.svc.connections._publish()
        self.publish()
        # the account's name and look, if another device set them first
        self.profile.pull_soon()
        # the account's conversations (a different account starts from cursor 0)
        self.svc.sync.account_changed(str(account.get("id") or ""))
        # ``created`` rides along: a brand-new account is offered a password and the
        # model source right after (the clients' first-sign-in steps).
        return {**self.account_view(), "created": bool(data.get("created"))}

    def _llm_is_cloud(self) -> bool:
        """Whether the chat model is the account (the Cloud key from the vault, on the relay)."""
        llm = self.settings.llm
        key = str(llm.api_key or (self.data.get("llm") or {}).get("api_key") or "")
        if CLOUD_KEY in key:
            return True
        base = str(llm.base_url or "").rstrip("/")
        return bool(base) and base == model_url(self.cloud.base_url).rstrip("/")

    async def refresh_chat_models(self) -> list[str]:
        """The relay's chat models, recommended one first; the hands models alongside
        (``gui_models``), and the app told which model its hands take by default."""
        self.cloud.api_key = self._key()
        models = await self.cloud.models()
        self.models = models
        self.chat_models = self._ranked(models, "chat")
        self.gui_models = self._ranked(models, "gui")
        self.svc.app.cloud_gui_model = self.gui_models[0] if self.gui_models else ""
        return self.chat_models

    def _ranked(self, models: list[dict[str, Any]], purpose: str) -> list[str]:
        fitting = self.cloud.models_for(models, purpose)
        recommended = self.cloud.recommended_model(models, purpose)
        ids = [str(m["id"]) for m in fitting if m.get("id")]
        if recommended in ids:
            ids.remove(recommended)
            ids.insert(0, recommended)
        return ids

    async def set_password(self, password: str, current: str | None = None) -> dict[str, Any]:
        if not self.signed_in:
            raise CloudError(401, "bad_key", "Sign in first.")
        self.cloud.api_key = self._key()
        await self.cloud.set_password(password, current)
        cloud = dict(self.data.get("cloud") or {})
        cloud["has_password"] = bool(password)
        self.data["cloud"] = cloud
        self._save()
        self.publish()
        return self.account_view()

    async def sessions(self) -> list[dict[str, Any]]:
        if not self.signed_in:
            raise CloudError(401, "bad_key", "Not signed in.")
        self.cloud.api_key = self._key()
        return await self.cloud.sessions()

    async def set_contribute(self, on: bool) -> dict[str, Any]:
        if not self.signed_in:
            raise CloudError(401, "bad_key", "Not signed in.")
        self.cloud.api_key = self._key()
        return await self.cloud.set_contribute(on)

    async def delete_samples(self) -> int:
        if not self.signed_in:
            raise CloudError(401, "bad_key", "Not signed in.")
        self.cloud.api_key = self._key()
        return await self.cloud.delete_samples()

    async def revoke_session(self, prefix: str) -> None:
        if not self.signed_in:
            raise CloudError(401, "bad_key", "Not signed in.")
        self.cloud.api_key = self._key()
        await self.cloud.revoke_session(prefix)

    async def sign_out_all(self, everything: bool = False) -> int:
        """Every other device's sign-in revoked; with ``everything`` this one too."""
        if not self.signed_in:
            raise CloudError(401, "bad_key", "Not signed in.")
        self.cloud.api_key = self._key()
        n = await self.cloud.sign_out_all(everything)
        if everything:
            await self._forget_key()
        return n

    async def events(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.signed_in:
            raise CloudError(401, "bad_key", "Not signed in.")
        self.cloud.api_key = self._key()
        return await self.cloud.events(limit)

    async def delete_account(self) -> None:
        """The person's own request: the relay forgets everything about them."""
        if not self.signed_in:
            raise CloudError(401, "bad_key", "Not signed in.")
        await self.leave()
        self.cloud.api_key = self._key()
        try:
            await self.cloud.delete_account()
        finally:
            await self._forget_key()

    async def sign_out(self) -> None:
        await self.leave()
        with contextlib.suppress(CloudError):
            self.cloud.api_key = self._key()
            await self.cloud.sign_out()
        await self._forget_key()

    async def _forget_key(self) -> None:
        was_model = self._llm_is_cloud()
        self.svc.app.vault.delete(CLOUD_KEY)
        self.cloud.api_key = ""
        cloud = dict(self.data.get("cloud") or {})
        for key in ("hint", "channel", "signed_in_at", "has_password", "account_id", "region"):
            cloud.pop(key, None)
        self.data["cloud"] = cloud
        self.profile.forget()
        self.svc.sync.signed_out()
        self._save()
        if was_model:
            # the client would otherwise keep sending the revoked key
            self.svc.connections._swap_llm()
        self.svc.connections._publish()
        self.publish()

    async def me(self) -> dict[str, Any]:
        if not self.signed_in:
            raise CloudError(401, "bad_key", "Not signed in.")
        self.cloud.api_key = self._key()
        data = await self.cloud.me()
        self.last_me = data
        account = data.get("account") if isinstance(data.get("account"), dict) else {}
        if account:
            cloud = dict(self.data.get("cloud") or {})
            region = str(data.get("region") or account.get("region") or cloud.get("region") or "")
            fresh = {
                "has_password": bool(account.get("has_password")),
                # a member, and (the relay's any_model) free to name any model of the
                # provider's — the operator may grant or take back either between reads
                "member": bool(account.get("member")),
                "any_model": bool(account.get("any_model")),
                "region": region,
            }
            changed = any(cloud.get(k) != v for k, v in fresh.items())
            cloud.update(fresh)
            cloud["account_id"] = str(account.get("id") or cloud.get("account_id") or "")
            self.data["cloud"] = cloud
            if changed:
                self._save()
                self.publish()
            # the Web app reads the region with the account (the relay says it at the top)
            if region and not account.get("region"):
                account["region"] = region
        return data

    def account_view(self) -> dict[str, Any]:
        cloud = self.data.get("cloud") or {}
        llm = self.settings.llm
        return {
            "base_url": self.cloud.base_url,
            "signed_in": self.signed_in,
            "required": self.settings.cloud.required,
            # the apps' *Use nanoMuse Cloud models*: the account's models as a source
            "models": self.settings.cloud.models,
            "hint": str(cloud.get("hint") or ""),
            "channel": str(cloud.get("channel") or ""),
            "signed_in_at": cloud.get("signed_in_at"),
            "has_password": bool(cloud.get("has_password")),
            "account_id": str(cloud.get("account_id") or ""),
            "member": bool(cloud.get("member")),
            "any_model": bool(cloud.get("any_model")),
            "region": str(cloud.get("region") or ""),
            "is_model": bool(
                llm.base_url and llm.base_url.rstrip("/") == model_url(self.cloud.base_url)
            ),
        }

    def set_models(self, on: bool) -> dict[str, Any]:
        """Switch the account's models on or off as a source (``[cloud] models``, kept in
        app-settings). Off, the relay leaves the automatic order of the hands, pictures and
        clips and the providers' listing; the sign-in stays. The chat model is the one slot
        this cannot move: the runtime holds a single ``[llm]`` and no list of other keys, so
        while the chat model is the account's the switch is refused (``409 chat_on_cloud``)
        and the person picks another chat model first."""
        if not on and self._llm_is_cloud():
            raise CloudError(
                409,
                "chat_on_cloud",
                "Add a provider of your own first; with nanoMuse Cloud off, nothing else "
                "could answer.",
            )
        cloud = dict(self.data.get("cloud") or {})
        cloud["models"] = bool(on)
        self.data["cloud"] = cloud
        self.settings.cloud.models = bool(on)
        self._save()
        self.svc.connections._publish()
        self.publish()
        return self.account_view()

    async def use_as_model(self, model: str = "") -> dict[str, Any]:
        """Make the relay the model provider: the Cloud key from the vault, the recommended
        chat model unless one is named. The explicit ask of the Connections page, so it
        switches the account's models back on when they were off."""
        if not self.signed_in:
            raise CloudError(401, "bad_key", "Sign in first.")
        if not self.settings.cloud.models:
            cloud = dict(self.data.get("cloud") or {})
            cloud["models"] = True
            self.data["cloud"] = cloud
            self.settings.cloud.models = True
        self.cloud.api_key = self._key()
        if not model:
            try:
                model = self.cloud.recommended_model(await self.cloud.models())
            except CloudError:
                model = self.cloud.recommended_model([])
        connections = self.svc.connections
        llm = dict(self.data.get("llm") or {})
        llm.update(
            {
                "provider": "openai",
                "model": model,
                "base_url": model_url(self.cloud.base_url),
                "api_key": "{{vault:" + CLOUD_KEY + "}}",
                "tool_mode": "auto",
            }
        )
        self.data["llm"] = llm
        self._save()
        from nanomuse.config import apply_app_settings

        apply_app_settings(self.settings, {"llm": llm})
        connections._swap_llm()
        connections._publish()
        return connections.view()["llm"]

    # ------------------------------------------------------------------ the view
    def view(self) -> dict[str, Any]:
        client = self.client
        devices = [dict(d) for d in (client.devices if client else [])]
        for d in devices:
            d["this"] = d.get("id") == self.device_id
        return {
            "enabled": self.settings.hub.enabled,
            "remote_control": self.settings.hub.remote_control,
            "state": client.state if client else ("signed_out" if not self.signed_in else "off"),
            "detail": client.state_detail if client else "",
            "device": {
                "id": self.device_id,
                "name": self.device_name,
                "kind": "computer",
                "actions": [*actions.ACTIONS, *self._extra_actions()],
            },
            "devices": devices,
            "account": self.account_view(),
        }

    def publish(self) -> None:
        self.svc.bus.publish({"kind": "hub", "hub": self.view()})

    def others(self) -> list[dict[str, Any]]:
        return self.client.others() if self.client else []

    def find(self, query: str) -> dict[str, Any] | None:
        return self.client.find(query) if self.client else None

    def device(self, device_id: str) -> dict[str, Any] | None:
        for d in self.others():
            if d.get("id") == device_id:
                return d
        return None

    async def call(
        self,
        to: str,
        action: str,
        args: dict[str, Any] | None = None,
        timeout: float = 120.0,
        on_event: Any = None,
    ) -> dict[str, Any]:
        if self.client is None or not self.client.connected.is_set():
            raise HubError(
                "no_hub",
                "not connected to the hub"
                + ("" if self.signed_in else "; sign in to nanoMuse Cloud first"),
            )
        return await self.client.call(to, action, args, timeout=timeout, on_event=on_event)

    # ------------------------------------------------------------------ calls in
    async def on_call(self, call: IncomingCall) -> None:
        if call.action == "approve":
            approval_id = str(call.args.get("approval_id") or "")
            # a device answers the cards of its own runs here, no others (not the card that
            # asks the person at this computer whether that device may run something)
            if self._relayed_approvals.get(approval_id) != call.sender_id:
                await call.result({"ok": False})
                return
            ok = self.svc.decide(approval_id, bool(call.args.get("allow")), "once")
            await call.result({"ok": ok})
            return
        if not self.settings.hub.remote_control and call.action != "info":
            await call.fail(
                "not_allowed", f"{self.device_name} is set not to be operated from other devices"
            )
            return
        if call.action in GATED_ACTIONS and not await self._permitted(call):
            await call.fail(
                "not_allowed",
                f"the person at {self.device_name} did not allow {call.sender_name} to do that",
            )
            return
        if call.action == "info":
            await call.result(actions.info(self._extra_actions()))
            return
        if call.action == "task":
            await self._task(call)
            return
        if call.action == "stop":
            # only the device that asked may stop its task (docs/hub.md): a `call` id must be
            # one of the sender's own, a `conversation` one the sender's tasks run in
            tid = self._incoming.get(str(call.args.get("call") or ""))
            if tid is None or not self._asked_by(tid, call.sender_id):
                tid = self._thread_for(call.sender_id, str(call.args.get("conversation") or ""))
            stopped = bool(tid) and self.svc.stop_thread(tid or "")
            await call.result({"stopped": stopped})
            return
        if call.action.startswith("coding."):
            await self._coding_call(call)
            return
        if call.action in actions.ACTIONS:
            self.svc.app.audit.record(
                "hub_call",
                action=call.action,
                sender=call.sender_name,
                summary=self._brief(call),
            )
            try:
                result = await asyncio.to_thread(actions.run, call.action, call.args)
            except actions.ActionError as exc:
                await call.fail(exc.code, exc.message)
                return
            await call.result(result)
            return
        await call.fail("unknown_action", f"this computer does not do '{call.action}'")

    async def _coding_call(self, call: IncomingCall) -> None:
        """Another device looking at, or steering, the coding agents on this computer."""
        from nanomuse.coding.service import CodingError

        coding = self.svc.coding
        self.svc.app.audit.record(
            "hub_call", action=call.action, sender=call.sender_name, summary=self._brief(call)
        )
        try:
            if call.action == "coding.send":
                a = call.args
                queue = self.svc.bus.subscribe()
                try:
                    started = await coding.send(
                        str(a.get("agent") or ""),
                        str(a.get("text") or ""),
                        session_id=str(a.get("session_id") or ""),
                        workspace=str(a.get("workspace") or ""),
                    )
                    run_id = str(started.get("id") or "")
                    if not bool(a.get("wait", True)):
                        await call.result(started)
                        return
                    # follow the run on the bus; each step goes back as a task event
                    final: dict[str, Any] = started
                    while True:
                        msg = await asyncio.wait_for(queue.get(), timeout=1800)
                        if msg.get("kind") != "coding":
                            continue
                        run = msg.get("run") or {}
                        ev = msg.get("event") or {}
                        if run.get("id") != run_id and ev.get("run") != run_id:
                            continue
                        if ev.get("kind") in ("text", "tool", "started"):
                            # the run id rides along so the caller can `coding.stop` it
                            await call.event({"kind": "coding", "run": run_id, **ev})
                        if run.get("id") == run_id and run.get("status") in (
                            "done",
                            "failed",
                            "stopped",
                        ):
                            final = run
                            break
                    await call.result(final)
                finally:
                    self.svc.bus.unsubscribe(queue)
                return
            result = await asyncio.to_thread(coding.handle, call.action, call.args)
        except CodingError as exc:
            await call.fail(exc.code, exc.message)
            return
        except TimeoutError:
            await call.fail("timeout", "the coding agent took longer than the hub allows")
            return
        await call.result(result)

    @staticmethod
    def _brief(call: IncomingCall) -> str:
        a = call.args
        for k in ("command", "path", "url", "text"):
            if a.get(k):
                s = str(a[k]).replace("\n", " ")
                return s if len(s) < 100 else s[:99] + "…"
        return ""

    async def _permitted(self, call: IncomingCall) -> bool:
        """The person at this computer agrees before another device runs, reads or writes
        something here — once, or always for that device. The standing answer is a Sentinel
        grant (``remote_control:<device id>``), listed and revocable under Permissions like
        any other; the card goes to the device's side chat when there is one."""
        sentinel = self.svc.app.sentinel
        key = grant_key(REMOTE_CONTROL_TOOL, call.sender_id)
        if sentinel.grants.match(key) is not None:
            return True
        brief = self._brief(call)
        shown = {k: v for k, v in call.args.items() if k != "data"}
        request = ApprovalRequest(
            tool=REMOTE_CONTROL_TOOL,
            args={"device": call.sender_name, "action": call.action, **shown},
            summary=f"{call.sender_name} wants to run {call.action} on this computer"
            + (f": {brief}" if brief else ""),
            risk=RiskLevel.SENSITIVE,
            reasons=[f"asked by another device ({call.sender_name})"],
            purpose=f"{call.sender_name} asked for it",
            target=call.sender_id,
            grant_key=key,
            grant_options=["once", "always"],
        )
        token = current_thread.set(self._thread_for(call.sender_id, "") or MAIN_THREAD)
        try:
            decision = await self.svc.ui.ask_approval(request)
        finally:
            current_thread.reset(token)
        scope = normalize_scope(decision.scope) if decision.approved else "once"
        if decision.approved and scope == "always":
            sentinel.grants.add(REMOTE_CONTROL_TOOL, call.sender_id, "always")
        self.svc.app.audit.record(
            "hub_call",
            action=call.action,
            sender=call.sender_name,
            decision="allow" if decision.approved else "deny",
            scope=scope,
            summary=brief,
        )
        return decision.approved

    def _thread_for(self, sender_id: str, conversation: str) -> str | None:
        """The thread of ``sender_id``'s tasks in ``conversation`` (its own per-device one
        when it named none); never another device's."""
        key = conversation or sender_id
        for t in self.svc.threads.values():
            if (
                t.remote_from
                and t.remote_from.get("conversation") == key
                and t.remote_from.get("device") == sender_id
            ):
                return t.id
        return None

    def _asked_by(self, thread_id: str, sender_id: str) -> bool:
        thread = self.svc.threads.get(thread_id)
        return bool(thread and thread.remote_from and thread.remote_from.get("device") == sender_id)

    async def _task(self, call: IncomingCall) -> None:
        text = str(call.args.get("text") or "").strip()
        if not text:
            await call.fail("usage", "text is required")
            return
        conversation = str(call.args.get("conversation") or call.sender_id or "device")
        thread = self._incoming_thread(call, conversation)
        if thread.busy or thread.device:
            await call.fail("busy", "this conversation is already busy")
            return
        self._incoming[call.id] = thread.id
        queue = self.svc.bus.subscribe()
        try:
            # `language`: the asking device's UI language (optional, docs/hub.md); the
            # answer is written in it rather than guessed from the text
            self.svc.send(
                thread.id,
                text,
                source="device",
                label=call.sender_name,
                language=str(call.args.get("language") or "")[:20],
            )
            final = await asyncio.wait_for(
                self._relay_run(thread, call, queue), timeout=TASK_TIMEOUT_S
            )
        except TimeoutError:
            self.svc.stop_thread(thread.id)
            await call.fail("timeout", "the task took longer than the hub allows")
            return
        except _RunStopped:
            # stopped before it answered (by the asking device's `stop`, or the stop button
            # here): the call fails, it does not hand back an older reply as the answer
            await call.fail("cancelled", "the task was stopped before it answered")
            return
        finally:
            self.svc.bus.unsubscribe(queue)
            self._incoming.pop(call.id, None)
        await call.result(
            {
                "text": final,
                "conversation": conversation,
                "thread": thread.id,
                "device": self.device_name,
            }
        )

    def _incoming_thread(self, call: IncomingCall, conversation: str) -> Thread:
        for t in self.svc.threads.values():
            if t.remote_from and t.remote_from.get("conversation") == conversation:
                return t
        thread = self.svc.create_thread(f"From {call.sender_name}")
        thread.remote_from = {
            "device": call.sender_id,
            "name": call.sender_name,
            "kind": str(call.sender.get("kind") or ""),
            "conversation": conversation,
        }
        self.svc._save_index()
        self.svc.bus.publish({"kind": "thread", "thread": thread.meta()})
        return thread

    async def _relay_run(
        self, thread: Thread, call: IncomingCall, queue: asyncio.Queue[dict[str, Any]]
    ) -> str:
        """Follow the run in ``thread`` on the bus; send its steps to the caller; return
        the final answer once the thread is idle again."""
        started = False
        stopped = False
        final = ""
        while True:
            msg = await queue.get()
            kind = msg.get("kind")
            if kind in ("event", "update"):
                # "event": a new card; "update": one that changed (a tool finishing, an
                # approval answered). Both matter to the caller's view of the run.
                ev = msg.get("event") or {}
                if ev.get("thread") != thread.id:
                    continue
                if ev.get("type") == "assistant" and ev.get("text") and not ev.get("quiet"):
                    final = str(ev["text"])
                elif ev.get("type") == "notice" and ev.get("text") == STOPPED_NOTICE:
                    stopped = True
                await self._forward_event(call, ev, fresh=kind == "event")
            elif kind == "thread":
                meta = msg.get("thread") or {}
                if meta.get("id") != thread.id:
                    continue
                if meta.get("busy"):
                    started = True
                elif started and not meta.get("queued"):
                    break
        if stopped:
            raise _RunStopped
        return final or self.svc.ui.last_assistant_text.get(thread.id, "")

    async def _forward_event(
        self, call: IncomingCall, ev: dict[str, Any], *, fresh: bool = True
    ) -> None:
        """One card of the run, as a task event for the caller. ``fresh`` is a new card;
        otherwise a change to one already sent (a tool's result, an approval's answer)."""
        etype = ev.get("type")
        status = ev.get("status")
        if etype == "tool":
            if status == "running" and fresh:
                await call.event(
                    {
                        "stage": "tool",
                        "id": ev.get("id"),
                        "name": ev.get("tool"),
                        "summary": ev.get("summary", ""),
                    }
                )
            elif status in ("ok", "error", "blocked") and not fresh:
                await call.event(
                    {
                        "stage": "tool_result",
                        "id": ev.get("id"),
                        "name": ev.get("tool"),
                        "ok": status == "ok",
                        "summary": str(ev.get("output") or "")[:200],
                    }
                )
        elif etype == "approval":
            if status == "pending" and fresh:
                self._relayed_approvals[str(ev.get("id") or "")] = call.sender_id
                await call.event(
                    {
                        "stage": "approval",
                        "approval_id": ev.get("id"),
                        "preview": ev.get("summary", ""),
                        "risk": ev.get("risk", "moderate"),
                        "reason": "; ".join(ev.get("warnings") or ev.get("reasons") or []),
                        "device": self.device_name,
                        "timeout": int(self.settings.server.approval_timeout),
                    }
                )
            elif status in ("approved", "denied", "expired") and not fresh:
                # answered here (or timed out): the caller's card closes too
                self._relayed_approvals.pop(str(ev.get("id") or ""), None)
                await call.event(
                    {"stage": "approval_result", "approval_id": ev.get("id"), "status": status}
                )
        elif etype == "assistant" and fresh and ev.get("text") and not ev.get("final"):
            await call.event({"stage": "text", "text": ev["text"], "interim": True})
        elif etype == "artifact" and fresh and ev.get("path"):
            await self._forward_artifact(call, str(ev["path"]))

    async def _forward_artifact(self, call: IncomingCall, rel: str) -> None:
        try:
            path = self.svc.resolve_workspace_path(rel)
            if not path.is_file() or path.stat().st_size > actions.FILE_LIMIT:
                return
            mime = _mime(path.name)
            data = path.read_bytes() if mime.startswith("image/") else b""
        except (ValueError, OSError):
            return  # outside the workspace, unreadable, or gone between the event and now
        if mime.startswith("image/"):
            await call.event(
                {
                    "stage": "image",
                    "mime": mime,
                    "data": base64.b64encode(data).decode(),
                    "from": self.device_name,
                    "name": path.name,
                }
            )
        else:
            await call.event({"stage": "file", "name": path.name, "path": rel})

    # ------------------------------------------------------------------ calls out: a device's chat
    def ask_device(self, device_id: str) -> Thread:
        """The side chat addressed to ``device_id`` — one per device, created on demand."""
        for t in self.svc.threads.values():
            if t.device == device_id:
                return t
        d = self.device(device_id) or {"name": device_id, "kind": ""}
        thread = self.svc.create_thread(f"→ {d.get('name') or device_id}")
        thread.device = device_id
        thread.device_name = str(d.get("name") or device_id)
        self.svc._save_index()
        self.svc.bus.publish({"kind": "thread", "thread": thread.meta()})
        return thread

    def run_remote(self, thread: Thread, text: str) -> None:
        task = asyncio.create_task(self._run_remote(thread, text), name=f"remote-{thread.id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_remote(self, thread: Thread, text: str) -> None:
        ui = self.svc.ui
        tid = thread.id
        device_id = thread.device or ""
        name = thread.device_name or device_id
        thread.busy = True
        self.svc.bus.publish({"kind": "thread", "thread": thread.meta()})
        ui.set_status("working", f"Asking {name}…", tid)
        tool_events: dict[str, str] = {}

        async def on_event(body: dict[str, Any]) -> None:
            stage = body.get("stage")
            if stage == "tool":
                ev = ui.emit(
                    {
                        "type": "tool",
                        "thread": tid,
                        "tool": str(body.get("name") or "tool"),
                        "summary": str(body.get("summary") or ""),
                        "status": "running",
                        "device": name,
                    }
                )
                # keyed by the remote card id when the device sends one (a runtime),
                # by the tool name otherwise (the phone)
                tool_events[str(body.get("id") or body.get("name") or "")] = ev["id"]
                ui.set_status("working", f"{name}: {body.get('summary') or body.get('name')}", tid)
            elif stage == "tool_result":
                eid = tool_events.pop(str(body.get("id") or ""), None) or tool_events.pop(
                    str(body.get("name") or ""), None
                )
                if eid:
                    ui.patch(
                        tid,
                        eid,
                        status="ok" if body.get("ok", True) else "error",
                        output=str(body.get("summary") or ""),
                    )
            elif stage == "approval_result":
                # answered on the device itself (or expired there): close the card here
                approval_id = str(body.get("approval_id") or "")
                for cid, (dev, aid) in list(self.remote_approvals.items()):
                    if dev == device_id and aid == approval_id:
                        self.remote_approvals.pop(cid, None)
                        status = str(body.get("status") or "expired")
                        ui.patch(
                            tid, cid, status=status, scope="once" if status == "approved" else None
                        )
                if ui.status.get(tid, {}).get("state") == "waiting":
                    ui.set_status("working", f"Asking {name}…", tid)
            elif stage == "approval":
                approval_id = str(body.get("approval_id") or "")
                card = ui.emit(
                    {
                        "type": "approval",
                        "thread": tid,
                        "tool": "delegate",
                        "summary": str(body.get("preview") or ""),
                        "risk": _RISK_WORDS.get(str(body.get("risk") or ""), "moderate"),
                        "reasons": [str(body.get("reason") or "")] if body.get("reason") else [],
                        "warnings": [],
                        "egress_target": None,
                        "purpose": text[:200],
                        "target": name,
                        "grant_key": f"delegate:{name}",
                        "grant_options": ["once"],
                        "args": {"device": name, "preview": body.get("preview", "")},
                        "status": "pending",
                        "remote": {"device": device_id, "name": name, "approval_id": approval_id},
                    }
                )
                self.remote_approvals[card["id"]] = (device_id, approval_id)
                ui.set_status("waiting", f"{name} needs your approval", tid)
            elif stage == "image":
                self._save_image(tid, body, name)
            elif stage == "text" and body.get("interim") and body.get("text"):
                ui.emit(
                    {
                        "type": "notice",
                        "level": "info",
                        "text": str(body["text"]),
                        "source": name,
                        "thread": tid,
                    }
                )
            elif stage == "error":
                ui.emit(
                    {
                        "type": "notice",
                        "level": "error",
                        "text": str(body.get("message") or "error"),
                        "thread": tid,
                    }
                )

        args: dict[str, Any] = {"text": text, "from": self.device_name, "conversation": tid}
        if thread.agent.ui_language:
            # the person reads this chat in that language; the other device's runtime
            # answers in it (docs/hub.md, `task`)
            args["language"] = thread.agent.ui_language
        try:
            result = await self.call(
                device_id,
                "task",
                args,
                timeout=REMOTE_TASK_TIMEOUT_S,
                on_event=on_event,
            )
            answer = str(result.get("text") or result.get("answer") or "").strip()
            ui.emit(
                {
                    "type": "assistant",
                    "thread": tid,
                    "text": answer or f"({name} finished without an answer)",
                    "final": True,
                    "device": name,
                }
            )
            ui.last_assistant_text[tid] = answer
        except HubError as exc:
            ui.emit(
                {
                    "type": "notice",
                    "level": "error",
                    "text": f"{name}: {exc.message}",
                    "thread": tid,
                }
            )
        except asyncio.CancelledError:
            ui.emit({"type": "notice", "level": "info", "text": "Stopped.", "thread": tid})
            with contextlib.suppress(HubError):
                await self.call(device_id, "stop", {"conversation": tid}, timeout=15)
            raise
        finally:
            for eid in tool_events.values():
                ui.patch(tid, eid, status="error", output="interrupted")
            for cid, (dev, _aid) in list(self.remote_approvals.items()):
                if (
                    dev == device_id
                    and (ui.get_timeline(tid).get(cid) or {}).get("status") == "pending"
                ):
                    ui.patch(tid, cid, status="expired")
                    self.remote_approvals.pop(cid, None)
            thread.busy = False
            thread.updated_at = now_iso()
            ui.set_status("idle", "", tid)
            self.svc.bus.publish({"kind": "thread", "thread": thread.meta()})

    def _save_image(self, tid: str, body: dict[str, Any], name: str) -> None:
        data = body.get("data")
        if not isinstance(data, str) or not data:
            return
        ext = "jpg" if "jpeg" in str(body.get("mime") or "") else "png"
        folder = self.svc.workspace() / "screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.-]+", "_", name)[:40] or "device"
        path = (
            folder
            / f"{safe}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.{ext}"
        )
        try:
            path.write_bytes(base64.b64decode(data))
        except (OSError, ValueError):
            return
        rel = path.relative_to(self.svc.workspace()).as_posix()
        self.svc.ui.emit(
            {
                "type": "artifact",
                "path": rel,
                "name": path.name,
                "action": "write",
                "thread": tid,
                "device": name,
            }
        )

    async def stop_remote(self, thread: Thread) -> bool:
        for t in list(self._tasks):
            if t.get_name() == f"remote-{thread.id}" and not t.done():
                t.cancel()
                return True
        return False

    async def decide_remote(self, card_id: str, approved: bool) -> bool:
        """An approval card raised by another device's run, answered here."""
        entry = self.remote_approvals.pop(card_id, None)
        if entry is None:
            return False
        device_id, approval_id = entry
        for t in self.svc.threads.values():
            if t.timeline.get(card_id) is not None:
                self.svc.ui.patch(
                    t.id,
                    card_id,
                    status="approved" if approved else "denied",
                    scope="once" if approved else None,
                    decided_ts=now_iso(),
                )
                if self.svc.ui.status.get(t.id, {}).get("state") == "waiting":
                    self.svc.ui.set_status("working", f"Asking {t.device_name or device_id}…", t.id)
                break
        try:
            result = await self.call(
                device_id, "approve", {"approval_id": approval_id, "allow": approved}, timeout=30
            )
        except HubError as exc:
            logger.warning("approve to {} failed: {}", device_id, exc)
            return False
        return bool(result.get("ok", True))


def _mime(name: str) -> str:
    import mimetypes

    return mimetypes.guess_type(name)[0] or "application/octet-stream"


__all__ = ["HubService"]
