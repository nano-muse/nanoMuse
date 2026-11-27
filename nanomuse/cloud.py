"""nanoMuse Cloud from the runtime: sign in with a code, look at the account, the models
the relay offers, and the hub's address.

The relay (``cloud/`` in this repository, ``docs/cloud.md``) is one more OpenAI-compatible
provider to the agent — ``<base_url>/v1`` with the account key — so signing in here is the
same first step the phone offers: *Sign in — free*, with a phone number or an e-mail. The key is kept in the
vault under :data:`CLOUD_KEY`; nothing here ever shows it to the model.
"""

from __future__ import annotations

import platform
from typing import Any
from urllib.parse import urlencode

import httpx

from nanomuse import __version__

CLOUD_KEY = "NANOMUSE_CLOUD_KEY"
# Offline fallbacks until the signed-in relay supplies its own recommended lanes.
DEFAULT_CHAT_MODEL = "deepseek-v4.1-flash-1017"
DEFAULT_GUI_MODEL = "qwen3.5-397b-a17b"
DEFAULT_MODEL = DEFAULT_CHAT_MODEL

MESSAGES = {
    "bad_identifier": "Enter a mainland phone number or an e-mail address.",
    "phone_region": "Codes reach mainland China numbers only for now; elsewhere, sign in with an e-mail address.",
    "code_wrong": "That code is not right.",
    "code_expired": "That code has expired; ask for a new one.",
    "code_too_often": "Too many codes were sent; wait a few minutes.",
    "not_invited": "This relay is private; that address is not on its list.",
    "domain_limited": "Today's sign-up limit for addresses at that domain is reached on this relay. Try again tomorrow, or use another address.",
    "channel_unsupported": "This relay does not send codes to that kind of address. Use the other kind (e-mail or phone number), or sign in with a password.",
    "send_failed": "The code could not be sent; try again in a moment.",
    "bad_key": "Sign in again.",
    "out_of_tokens": "This account has used its tokens.",
    "account_disabled": "This account is disabled.",
    "model_not_offered": "That model is not offered here.",
    "hosted_media_retired": "This relay has disabled image and video generation. Add your own image or video provider and API key under Models.",
    "rate_limited": "Too many requests; slow down a little.",
    "allowance_exhausted": "The free allowance is used up. Invite a friend (the relay adds to both your allowances) or add your own model key; your sign-in and your devices keep working either way.",
    "daily_cap": "Today's token quota is used up; it comes back tomorrow.",
    "upstream": "The model provider did not answer.",
    "upstream_unconfigured": "nanoMuse Cloud has no model key configured.",
    "offline": "nanoMuse Cloud cannot be reached.",
    "bad_credentials": "That address and password do not match.",
    "no_password": "This account has no password yet; sign in with a code and set one under Account.",
    "locked": "Too many wrong passwords; wait a while or sign in with a code.",
    "password_short": "Use at least 8 characters.",
    "password_weak": "Choose a stronger password.",
    "password_wrong": "That is not the current password.",
    "password_required": "Enter the current password.",
    "no_session": "That sign-in is already gone.",
}


class CloudError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        # what the relay said beside the words (an ``allowance_exhausted`` carries what is
        # left, the invite link, the own-key guide)
        self.extra: dict[str, Any] = dict(extra or {})

    def describe(self) -> str:
        return MESSAGES.get(self.code, self.message or self.code)


def hub_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/v1/hub"


def model_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/v1"


class CloudClient:
    """The relay's account API. One instance per relay; the key may change (sign in/out)."""

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": f"nanoMuse/{__version__} ({platform.system()})",
                "Accept": "application/json",
            },
        )

    @property
    def hub_url(self) -> str:
        return hub_url(self.base_url)

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = dict(headers or {})
        tok = self.api_key if token is None else token
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        try:
            response = await self._client.request(
                method, self.base_url + path, json=body, headers=headers
            )
        except httpx.TimeoutException:
            raise CloudError(0, "timeout", f"{self.base_url} did not answer in time") from None
        except httpx.HTTPError as exc:
            raise CloudError(0, "offline", f"Cannot reach {self.base_url}: {exc}") from None
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            err = body.get("error") if isinstance(body, dict) else None
            if not isinstance(err, dict):
                err = {}
            raise CloudError(
                response.status_code,
                str(err.get("code") or f"http_{response.status_code}"),
                str(err.get("message") or response.text[:200]),
                extra={k: v for k, v in err.items() if k not in ("code", "message", "type")},
            )
        if not response.content.strip():
            return {}
        try:
            data = response.json()
        except ValueError:
            raise CloudError(
                response.status_code, "bad_response", f"{self.base_url} did not answer with JSON"
            ) from None
        return data if isinstance(data, dict) else {"data": data}

    # ------------------------------------------------------------------ account
    async def request_code(self, identifier: str) -> None:
        await self._request("POST", "/v1/auth/code", {"identifier": identifier}, token="")

    async def verify(
        self, identifier: str, code: str, device: str, invite: str = ""
    ) -> dict[str, Any]:
        """→ ``{api_key, account{channel,hint}, tokens{…}, models[…]}``; the key is kept on
        this client from then on. ``invite`` is a friend's code; it counts for a new account
        only and the relay ignores it otherwise."""
        body: dict[str, Any] = {"identifier": identifier, "code": code, "device": device}
        if invite.strip():
            body["invite"] = invite.strip()
        data = await self._request("POST", "/v1/auth/verify", body, token="")
        key = str(data.get("api_key") or "")
        if key:
            self.api_key = key
        return data

    async def login(self, identifier: str, password: str, device: str) -> dict[str, Any]:
        """The password way in, for accounts that set one; same reply as ``verify``."""
        data = await self._request(
            "POST",
            "/v1/auth/login",
            {"identifier": identifier, "password": password, "device": device},
            token="",
        )
        key = str(data.get("api_key") or "")
        if key:
            self.api_key = key
        return data

    async def set_password(self, password: str, current: str | None = None) -> None:
        """Set or change the account password (``current`` when one exists, unless this key
        came from a code sign-in just now); an empty password with ``current`` removes it."""
        body: dict[str, Any] = {"password": password}
        if current is not None:
            body["current"] = current
        await self._request("POST", "/v1/auth/password", body)

    async def me(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/me")

    async def config(self) -> dict[str, Any]:
        """The relay's public figures (relay 0.15, ``GET /v1/config``): the allowance a new
        account gets, the invite bonus, whether sign-up is open, the links. No key needed;
        an older relay answers 404, which comes back as a :class:`CloudError`."""
        return await self._request("GET", "/v1/config", token="")

    async def nudges(self) -> dict[str, Any]:
        """When the app may ask for a star on GitHub (relay 0.18, ``GET /v1/nudges``, contract
        C1): the policy the operator set, or the relay's defaults. No key needed; an older
        relay answers 404, which comes back as a :class:`CloudError`. The runtime keeps a
        copy through :class:`nanomuse.nudges.NudgesPolicy`, which reads once a day."""
        return await self._request("GET", "/v1/nudges", token="")

    async def profile(self, with_face: bool = True) -> dict[str, Any]:
        """The agent's name and look as the account's devices share it (``rev`` 0 = none yet);
        without the face's pictures when ``with_face`` is false."""
        return await self._request("GET", "/v1/me/profile" + ("" if with_face else "?face=false"))

    async def put_profile(self, body: dict[str, Any]) -> dict[str, Any]:
        """This device's name and look for the account (last writer wins); the new ``rev``."""
        return await self._request("PUT", "/v1/me/profile", body)

    async def set_contribute(self, on: bool) -> dict[str, Any]:
        """Keep (or stop keeping) this account's chat turns for the community's model."""
        return await self._request("POST", "/v1/me/contribute", {"on": on})

    async def delete_samples(self) -> int:
        data = await self._request("DELETE", "/v1/me/samples")
        return int(data.get("deleted") or 0)

    # ---------------------------------------------------------- the record (relay 0.29–0.31)
    async def post_turn(
        self, turn: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """A turn this runtime ran on a key of the person's own, kept beside the Cloud ones
        (``POST /v1/turns``; docs/cloud.md "The record"). ``headers`` are the
        ``X-NanoMuse-*`` of the call (the device; the platform the user agent would not say)."""
        return await self._request("POST", "/v1/turns", turn, headers=headers)

    async def post_events(
        self, events: list[dict[str, Any]], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """What happened around turns, as codes and numbers (``POST /v1/events``, relay 0.31;
        docs/cloud.md "Client events")."""
        return await self._request("POST", "/v1/events", {"events": events}, headers=headers)

    async def has_blob(self, sha256: str) -> bool:
        """Whether the relay already holds this file (``HEAD /v1/blobs/{sha256}``)."""
        try:
            response = await self._client.head(
                f"{self.base_url}/v1/blobs/{sha256}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except httpx.HTTPError as exc:
            raise CloudError(0, "offline", f"Cannot reach {self.base_url}: {exc}") from None
        return response.status_code == 200

    async def put_blob(self, sha256: str, mime: str, data: bytes) -> dict[str, Any]:
        """A picture, audio or clip of a turn, stored once by its hash (``PUT /v1/blobs/{sha256}``)."""
        try:
            response = await self._client.put(
                f"{self.base_url}/v1/blobs/{sha256}",
                content=data,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": mime},
            )
        except httpx.TimeoutException:
            raise CloudError(0, "timeout", f"{self.base_url} did not answer in time") from None
        except httpx.HTTPError as exc:
            raise CloudError(0, "offline", f"Cannot reach {self.base_url}: {exc}") from None
        if response.status_code >= 400:
            try:
                err = (response.json() or {}).get("error") or {}
            except ValueError:
                err = {}
            raise CloudError(
                response.status_code,
                str(err.get("code") or f"http_{response.status_code}"),
                str(err.get("message") or response.text[:200]),
            )
        try:
            out = response.json()
        except ValueError:
            out = {}
        return out if isinstance(out, dict) else {}

    async def sessions(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/v1/me/sessions")
        sessions = data.get("sessions")
        return sessions if isinstance(sessions, list) else []

    async def revoke_session(self, prefix: str) -> None:
        await self._request("DELETE", f"/v1/me/sessions/{prefix}")

    async def sign_out_all(self, everything: bool = False) -> int:
        data = await self._request("POST", "/v1/auth/sign-out-all", {"all": everything})
        if everything:
            self.api_key = ""
        return int(data.get("signed_out") or 0)

    async def events(self, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._request("GET", f"/v1/me/events?limit={int(limit)}")
        events = data.get("events")
        return events if isinstance(events, list) else []

    async def sign_out(self) -> None:
        try:
            await self._request("POST", "/v1/auth/sign-out", {})
        finally:
            self.api_key = ""

    async def delete_account(self) -> None:
        try:
            await self._request("POST", "/v1/auth/delete", {})
        finally:
            self.api_key = ""

    async def devices(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/v1/devices")
        devices = data.get("devices")
        return devices if isinstance(devices, list) else []

    async def models(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/v1/models")
        models = data.get("data")
        return models if isinstance(models, list) else []

    async def estimate(
        self,
        images: int = 0,
        image_model: str = "",
        size: str = "",
        clips: int = 0,
        video_model: str = "",
    ) -> dict[str, Any]:
        """What ``images`` pictures and ``clips`` short videos would cost against the pool
        (``cny``, ``left_cny``, ``affordable``, ``unlimited``); nothing is charged."""
        params: dict[str, str] = {"images": str(int(images))}
        if image_model:
            params["image_model"] = image_model
        if size:
            params["size"] = size
        if clips:
            params["clips"] = str(int(clips))
            if video_model:
                params["video_model"] = video_model
        # model ids and sizes are typed by people and relayed by the app: encoded, so an
        # "&" or a space in one cannot change the question asked
        return await self._request("GET", "/v1/estimate?" + urlencode(params))

    @staticmethod
    def models_for(models: list[dict[str, Any]], purpose: str = "chat") -> list[dict[str, Any]]:
        """The relay's models meant for ``purpose`` — ``chat`` or ``gui`` (contract C4).

        A model that carries ``"for": ["chat"]`` / ``["gui"]`` / ``["chat", "gui"]`` (under
        ``nanomuse``, where the relay keeps its flags, or at the top) is taken at its word.
        A relay that does not say yet gets the old reading: every text-out model is a chat
        model, and a chat model whose id says it sees (``qwen*-vl``, ``qwen3.8-*``) is a
        hands model too."""
        from nanomuse.llm.vision import model_takes_images

        out = []
        for m in models:
            uses = CloudClient._lanes(m)
            if uses is not None:
                # said — `[]` is a picture or video model, in no picker
                if purpose in uses:
                    out.append(m)
                continue
            text_out = (m.get("architecture") or {}).get("output_modalities", ["text"]) == ["text"]
            if not text_out:
                continue
            if purpose == "chat" or model_takes_images(str(m.get("id") or "")):
                out.append(m)
        return out

    @staticmethod
    def _lanes(m: dict[str, Any]) -> list[str] | None:
        """The lanes a menu entry is for — ``nanomuse.for`` first, a top-level ``for`` as
        the fallback; ``None`` when the relay did not say (``[]`` is "none": a picture or
        video model)."""
        flags = m.get("nanomuse") or {}
        uses = flags.get("for")
        if uses is None:
            uses = m.get("for")
        if isinstance(uses, str):
            uses = [uses]
        return [str(u) for u in uses] if isinstance(uses, list) else None

    @staticmethod
    def recommended_model(models: list[dict[str, Any]], purpose: str = "chat") -> str:
        """The relay's recommended model for ``purpose`` (``nanomuse.recommended_for``, or
        ``recommended`` on a relay that does not split the lanes), else the default when it
        is offered, else the first one meant for it, else the default anyway."""
        fitting = CloudClient.models_for(models, purpose)
        default = DEFAULT_GUI_MODEL if purpose == "gui" else DEFAULT_CHAT_MODEL
        for m in fitting:
            flags = m.get("nanomuse") or {}
            rec_for = flags.get("recommended_for")
            if isinstance(rec_for, str):
                rec_for = [rec_for]
            if isinstance(rec_for, list):
                if purpose in rec_for:
                    return str(m["id"])
                continue
            if flags.get("recommended") and (purpose == "chat" or not CloudClient._lanes(m)):
                return str(m["id"])
        if any(m.get("id") == default for m in fitting):
            return default
        return str(fitting[0]["id"]) if fitting else default


__all__ = [
    "CLOUD_KEY",
    "DEFAULT_CHAT_MODEL",
    "DEFAULT_GUI_MODEL",
    "DEFAULT_MODEL",
    "MESSAGES",
    "CloudClient",
    "CloudError",
    "hub_url",
    "model_url",
]
