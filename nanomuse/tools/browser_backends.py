"""Where the browser tool's pages actually render: a Playwright Chromium on the computer, or
the app's own WebView on the phone.

The tool (:mod:`nanomuse.tools.browser`) speaks to one :class:`BrowserBackend` and never to
Playwright or the phone directly, so the page summary, the numbered elements, the frames the
user watches and the Sentinel's view of an action are the same on both.

Two backends:

* :class:`PlaywrightBackend` — Chromium through Playwright, with a **persistent profile**
  under the workspace, so a login made once (by the user taking over) is still there after
  a restart.
* :class:`DeviceBackend` — the Android app's offscreen WebView, reached through the phone
  link (``browser`` requests over the app's WebSocket). Its cookies are the phone's: what
  the user is signed in to on the phone, the agent is too.

Both take a :class:`BrowserProfile` — user agent and viewport — with ``mobile`` and
``desktop`` presets, and can ``fetch`` a URL with the page's cookies (rung two of the ladder:
a signed-in request without driving the screen).
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import socket
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanomuse.background import spawn
from nanomuse.logger import logger

if TYPE_CHECKING:
    from nanomuse.phone.link import PhoneLink


# ---------------------------------------------------------------------- profiles
@dataclass(frozen=True)
class BrowserProfile:
    """How the browser presents itself: user agent and viewport."""

    name: str
    width: int
    height: int
    user_agent: str = ""  # empty: the backend's own default
    mobile: bool = False
    scale: float = 1.0

    @property
    def viewport(self) -> dict[str, int]:
        return {"width": self.width, "height": self.height}


DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Mobile Safari/537.36"
)

PROFILES: dict[str, BrowserProfile] = {
    "desktop": BrowserProfile("desktop", 1280, 900, DESKTOP_UA, mobile=False),
    "mobile": BrowserProfile("mobile", 412, 915, MOBILE_UA, mobile=True, scale=2.0),
}


def profile_named(
    name: str = "",
    user_agent: str | None = None,
    width: int | None = None,
    height: int | None = None,
    base: BrowserProfile | None = None,
) -> BrowserProfile:
    """A preset by name, optionally with fields overridden (that makes it ``custom``)."""
    prof = PROFILES.get(name) or base or PROFILES["desktop"]
    changes: dict[str, Any] = {}
    if user_agent:
        changes["user_agent"] = user_agent
    if width:
        changes["width"] = max(320, min(int(width), 3840))
    if height:
        changes["height"] = max(320, min(int(height), 4320))
    if changes:
        prof = replace(prof, name="custom", **changes)
    return prof


# ---------------------------------------------------------------------- the interface
class BrowserBackend(ABC):
    """One browser page, wherever it renders. All coordinates are CSS pixels of the viewport."""

    kind: str = ""
    profile: BrowserProfile = PROFILES["desktop"]

    @property
    @abstractmethod
    def open(self) -> bool:
        """A page exists right now."""

    @abstractmethod
    async def ensure(self) -> None:
        """Open the browser and a page if there is none."""

    @abstractmethod
    async def goto(self, url: str) -> None: ...

    async def set_url_guard(self, guard: Callable[[str], Awaitable[bool]]) -> None:
        """Install a last-moment network URL guard when the backend supports interception."""
        return None

    @abstractmethod
    async def evaluate(self, js: str, arg: Any = None) -> Any:
        """Run ``(js)(arg)`` in the page and return its JSON-able result."""

    @abstractmethod
    async def click_at(self, x: float, y: float) -> None: ...

    @abstractmethod
    async def type_text(self, text: str) -> None:
        """Type into whatever has the focus."""

    @abstractmethod
    async def press(self, key: str) -> None: ...

    @abstractmethod
    async def scroll(self, dy: float) -> None: ...

    @abstractmethod
    async def back(self) -> None: ...

    @abstractmethod
    async def screenshot(self, quality: int = 55) -> bytes:
        """The viewport as JPEG."""

    @abstractmethod
    async def url(self) -> str: ...

    @abstractmethod
    async def title(self) -> str: ...

    @abstractmethod
    async def settle(self, timeout_ms: int) -> None:
        """Wait for a navigation that an action may have started."""

    @abstractmethod
    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        """A request with the page's cookies. ``{"status", "headers", "body", "url"}``."""

    @abstractmethod
    async def set_profile(self, profile: BrowserProfile) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    # ------------------------------------------------------------------ shared behaviour
    async def click_element(self, index: int) -> None:
        """Click a numbered element: scroll it into view, then click its centre."""
        rect = await self.evaluate(_CENTER_JS, int(index))
        if not rect:
            raise LookupError(f"element [{index}] is no longer on the page")
        await self.click_at(float(rect["x"]), float(rect["y"]))

    async def fill_element(self, index: int, text: str) -> None:
        """Put ``text`` into a numbered field the way a framework notices (native setter +
        input events); falls back to typing when the element is not a plain field."""
        ok = await self.evaluate(_FILL_JS, {"index": int(index), "text": text})
        if not ok:
            await self.click_element(index)
            await self.type_text(text)


# The centre of element [i] in viewport CSS pixels, after scrolling it into view.
_CENTER_JS = """
(i) => {
  const e = document.querySelector('[data-om-idx="' + i + '"]');
  if (!e) return null;
  e.scrollIntoView({block: 'center', inline: 'center'});
  const r = e.getBoundingClientRect();
  return {x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height};
}
"""

# Fill a field so React/Vue/Angular see it: focus, set through the prototype's own setter,
# then fire input + change. Returns false for anything that is not a field (a contenteditable
# gets execCommand, which most editors listen to).
_FILL_JS = """
({index, text}) => {
  const e = document.querySelector('[data-om-idx="' + index + '"]');
  if (!e) return false;
  e.scrollIntoView({block: 'center', inline: 'center'});
  e.focus();
  const tag = e.tagName.toLowerCase();
  if (tag === 'input' || tag === 'textarea') {
    const proto = tag === 'input' ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(e, text);
    e.dispatchEvent(new Event('input', {bubbles: true}));
    e.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  }
  if (tag === 'select') {
    const opt = Array.from(e.options).find(o => o.value === text || o.text.trim() === text);
    if (!opt) return false;
    e.value = opt.value;
    e.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  }
  if (e.isContentEditable) {
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, text);
    return true;
  }
  return false;
}
"""


class _PinnedPublicSocksProxy:
    """A loopback SOCKS5 proxy that connects only to the public address it validated.

    Chromium normally resolves a name after a route handler has approved it. A DNS answer
    can change between those two steps. The proxy resolves once, rejects the whole answer
    set if any address is not globally routable, then gives ``open_connection`` the numeric
    address with ``AI_NUMERICHOST``. TLS still runs end to end in Chromium, with the original
    host name and certificate checks intact.
    """

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self.blocked_target = ""

    @property
    def url(self) -> str:
        sockets = self._server.sockets if self._server is not None else None
        if not sockets:
            raise RuntimeError("browser network proxy is not running")
        port = int(sockets[0].getsockname()[1])
        return f"socks5://127.0.0.1:{port}"

    async def start(self) -> None:
        if self._server is None:
            self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self.blocked_target = ""

    async def _open_public(
        self, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        normalized = host.rstrip(".").lower()
        if normalized == "localhost" or normalized.endswith((".local", ".internal", ".localhost")):
            raise PermissionError(f"private or local address: {host}")

        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        endpoints: list[tuple[socket.AddressFamily, str]] = []
        for family, _kind, _proto, _name, sockaddr in infos:
            address = str(sockaddr[0]).split("%", 1)[0]
            ip = ipaddress.ip_address(address)
            if (
                not ip.is_global
                or ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                raise PermissionError(f"private or local address: {host}")
            endpoint = (family, str(ip))
            if endpoint not in endpoints:
                endpoints.append(endpoint)
        if not endpoints:
            raise OSError(f"no address for {host}")

        last_error: OSError | None = None
        for family, address in endpoints:
            try:
                return await asyncio.open_connection(
                    address,
                    port,
                    family=family,
                    flags=socket.AI_NUMERICHOST,
                )
            except OSError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    @staticmethod
    async def _reply(writer: asyncio.StreamWriter, status: int) -> None:
        writer.write(b"\x05" + bytes([status]) + b"\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()

    @staticmethod
    async def _relay(
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        remote_reader: asyncio.StreamReader,
        remote_writer: asyncio.StreamWriter,
    ) -> None:
        async def copy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            while data := await reader.read(64 * 1024):
                writer.write(data)
                await writer.drain()

        tasks = {
            asyncio.create_task(copy(client_reader, remote_writer)),
            asyncio.create_task(copy(remote_reader, client_writer)),
        }
        _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        remote_writer: asyncio.StreamWriter | None = None
        try:
            version, method_count = await asyncio.wait_for(reader.readexactly(2), timeout=10)
            methods = await asyncio.wait_for(reader.readexactly(method_count), timeout=10)
            if version != 5 or 0 not in methods:
                writer.write(b"\x05\xff")
                await writer.drain()
                return
            writer.write(b"\x05\x00")
            await writer.drain()

            version, command, _reserved, address_kind = await asyncio.wait_for(
                reader.readexactly(4), timeout=10
            )
            if version != 5 or command != 1:
                await self._reply(writer, 7)
                return
            if address_kind == 1:
                host = str(ipaddress.ip_address(await reader.readexactly(4)))
            elif address_kind == 3:
                size = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(size)).decode("idna")
            elif address_kind == 4:
                host = str(ipaddress.ip_address(await reader.readexactly(16)))
            else:
                await self._reply(writer, 8)
                return
            port = int.from_bytes(await reader.readexactly(2), "big")
            if not host or not port:
                await self._reply(writer, 8)
                return

            try:
                remote_reader, remote_writer = await self._open_public(host, port)
            except PermissionError:
                self.blocked_target = f"{host}:{port}"
                await self._reply(writer, 2)
                return
            except OSError:
                await self._reply(writer, 4)
                return
            await self._reply(writer, 0)
            await self._relay(reader, writer, remote_reader, remote_writer)
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError, UnicodeError):
            return
        finally:
            if remote_writer is not None:
                remote_writer.close()
                try:
                    await remote_writer.wait_closed()
                except OSError:
                    pass
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


# ---------------------------------------------------------------------- playwright
class PlaywrightBackend(BrowserBackend):
    """Chromium through Playwright, with a persistent profile so logins survive restarts."""

    kind = "playwright"

    def __init__(
        self,
        profile_dir: Path,
        headless: bool = True,
        timeout_ms: int = 30_000,
        profile: BrowserProfile | None = None,
    ):
        self.profile_dir = profile_dir
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.profile = profile or PROFILES["desktop"]
        # where a file the page offers ends up: <workspace>/downloads next to the profile
        self.downloads_dir = profile_dir.parent / "downloads"
        self._pw: Any = None
        self._context: Any = None
        self._page: Any = None
        self._url_guard: Callable[[str], Awaitable[bool]] | None = None
        self._guard_installed = False
        self._blocked_url = ""
        self._network_proxy = _PinnedPublicSocksProxy()

    @staticmethod
    def available() -> bool:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def open(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    async def ensure(self) -> None:
        if self.open:
            return
        from playwright.async_api import async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()
        if self._context is None:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            await self._network_proxy.start()
            try:
                self._context = await self._pw.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    headless=self.headless,
                    viewport=self.profile.viewport,
                    user_agent=self.profile.user_agent or None,
                    is_mobile=self.profile.mobile,
                    has_touch=self.profile.mobile,
                    device_scale_factor=self.profile.scale,
                    locale=None,
                    proxy={"server": self._network_proxy.url, "bypass": "<-loopback>"},
                )
            except Exception:
                await self._network_proxy.close()
                raise
            self._context.set_default_timeout(self.timeout_ms)
            await self._install_url_guard()
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        self._page.on("download", self._on_download)

    def _on_download(self, download: Any) -> None:
        async def save() -> None:
            try:
                self.downloads_dir.mkdir(parents=True, exist_ok=True)
                name = Path(download.suggested_filename or "download").name or "download"
                await download.save_as(str(self.downloads_dir / name))
                logger.info("browser: downloaded {} into the workspace", name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser: download failed: {}", exc)

        spawn(save(), "saving a browser download")

    async def set_url_guard(self, guard: Callable[[str], Awaitable[bool]]) -> None:
        self._url_guard = guard
        await self._install_url_guard()

    async def _install_url_guard(self) -> None:
        guard = self._url_guard
        if self._context is None or guard is None or self._guard_installed:
            return

        async def check(route: Any) -> None:
            url = str(route.request.url)
            if await guard(url):
                await route.continue_()
                return
            self._blocked_url = url
            await route.abort("blockedbyclient")

        await self._context.route("**/*", check)
        self._guard_installed = True

    async def goto(self, url: str) -> None:
        self._blocked_url = ""
        self._network_proxy.blocked_target = ""
        try:
            await self._page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            blocked = self._blocked_url or self._network_proxy.blocked_target
            if blocked:
                self._blocked_url = ""
                self._network_proxy.blocked_target = ""
                raise PermissionError(
                    f"refusing to navigate to a private or local address: {blocked}"
                ) from exc
            raise

    async def evaluate(self, js: str, arg: Any = None) -> Any:
        return await self._page.evaluate(js, arg)

    async def click_at(self, x: float, y: float) -> None:
        await self._page.mouse.click(x, y)

    async def type_text(self, text: str) -> None:
        await self._page.keyboard.type(text, delay=20)

    async def press(self, key: str) -> None:
        await self._page.keyboard.press(key)

    async def scroll(self, dy: float) -> None:
        await self._page.mouse.wheel(0, dy)
        await self._page.wait_for_timeout(300)

    async def back(self) -> None:
        await self._page.go_back(wait_until="domcontentloaded")

    async def screenshot(self, quality: int = 55) -> bytes:
        return await self._page.screenshot(type="jpeg", quality=quality, scale="css")

    async def url(self) -> str:
        return str(self._page.url)

    async def title(self) -> str:
        return str(await self._page.title())

    async def settle(self, timeout_ms: int) -> None:
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception as exc:  # noqa: BLE001
            # a slow page is still worth reading; a note in the log says why the read was early
            logger.debug("browser: page not settled after {} ms: {}", timeout_ms, exc)
        await self._page.wait_for_timeout(400)

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        await self.ensure()
        # the context's request API shares its cookie jar: a signed-in request
        # redirects come back to the caller, which checks where they point before following
        resp = await self._context.request.fetch(
            url, method=method.upper(), headers=headers or None, data=body, max_redirects=0
        )
        text = await resp.text()
        return {"status": resp.status, "headers": dict(resp.headers), "body": text, "url": resp.url}

    async def set_profile(self, profile: BrowserProfile) -> None:
        """A new user agent needs a new context; the profile directory (the logins) stays."""
        if profile == self.profile:
            return
        self.profile = profile
        if self._context is not None:
            url = await self.url() if self.open else ""
            await self._context.close()
            self._context = self._page = None
            self._guard_installed = False
            await self.ensure()
            if url and url != "about:blank":
                await self.goto(url)

    async def close(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
            if self._pw is not None:
                await self._pw.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("browser cleanup: {}", exc)
        finally:
            self._context = self._page = self._pw = None
            self._guard_installed = False
            await self._network_proxy.close()


# ---------------------------------------------------------------------- the phone's WebView
class DeviceBackend(BrowserBackend):
    """The app's offscreen WebView on the phone, over the phone link.

    Requests (``op`` and its params) and what comes back — the protocol the Android app
    implements in ``DeviceBrowser.kt``::

        open      {}                              → {url, title}
        navigate  {url}                           → {url, title}
        evaluate  {js, arg}                       → {value}          runs (js)(arg), JSON result
        tap       {x, y}                          → {}               CSS px of the viewport
        type      {text}                          → {}               into the focused element
        key       {key}                           → {}               "Enter", "Tab", "Backspace" …
        scroll    {dy}                            → {}
        back      {}                              → {url, title}
        screenshot {quality}                      → {jpeg: base64, width, height}
        state     {}                              → {url, title, width, height}
        fetch     {url, method, headers, body}    → {status, headers, body, url}   with the WebView's cookies
        profile   {user_agent, width, height, mobile} → {}
        close     {}                              → {}
    """

    kind = "device"

    def __init__(
        self, link: PhoneLink, timeout_s: float = 30.0, profile: BrowserProfile | None = None
    ):
        self.link = link
        self.timeout_s = timeout_s
        # the phone's own WebView is mobile by nature; "" leaves its user agent alone
        self.profile = profile or replace(PROFILES["mobile"], user_agent="")
        self._open = False
        self._size: tuple[int, int] | None = None
        self._device: Any = None  # the phone the page was opened on

    @property
    def open(self) -> bool:
        # a phone that reconnected (app restarted) comes back with no page: open again
        device = self.link.browser_device
        return self._open and device is not None and device is self._device

    async def _req(self, op: str, **params: Any) -> dict[str, Any]:
        return await self.link.browser(op, params, timeout=self.timeout_s)

    async def ensure(self) -> None:
        if self.open:
            return
        result = await self._req(
            "open",
            user_agent=self.profile.user_agent,
            width=self.profile.width,
            height=self.profile.height,
            mobile=self.profile.mobile,
        )
        self._open = True
        self._device = self.link.browser_device
        if result.get("width") and result.get("height"):
            self._size = (int(result["width"]), int(result["height"]))

    async def goto(self, url: str) -> None:
        await self._req("navigate", url=url)

    async def evaluate(self, js: str, arg: Any = None) -> Any:
        result = await self._req("evaluate", js=js, arg=arg)
        value = result.get("value")
        if isinstance(value, str) and result.get("encoded") == "json":
            try:
                return json.loads(value)
            except ValueError:
                return value
        return value

    async def click_at(self, x: float, y: float) -> None:
        await self._req("tap", x=x, y=y)

    async def type_text(self, text: str) -> None:
        await self._req("type", text=text)

    async def press(self, key: str) -> None:
        await self._req("key", key=key)

    async def scroll(self, dy: float) -> None:
        await self._req("scroll", dy=dy)

    async def back(self) -> None:
        await self._req("back")

    async def screenshot(self, quality: int = 55) -> bytes:
        result = await self._req("screenshot", quality=quality)
        data = result.get("jpeg") or ""
        return base64.b64decode(data) if data else b""

    async def url(self) -> str:
        return str((await self._req("state")).get("url") or "")

    async def title(self) -> str:
        return str((await self._req("state")).get("title") or "")

    async def settle(self, timeout_ms: int) -> None:
        # the phone waits for its own page-finished callback inside navigate/tap; a short
        # pause covers scripts that navigate after the fact
        await self._req("settle", timeout_ms=min(timeout_ms, 8_000))

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        await self.ensure()
        result = await self._req(
            "fetch", url=url, method=method.upper(), headers=headers or {}, body=body
        )
        return {
            "status": int(result.get("status") or 0),
            "headers": dict(result.get("headers") or {}),
            "body": str(result.get("body") or ""),
            "url": str(result.get("url") or url),
        }

    async def set_profile(self, profile: BrowserProfile) -> None:
        self.profile = profile
        if self.open:
            await self._req(
                "profile",
                user_agent=profile.user_agent,
                width=profile.width,
                height=profile.height,
                mobile=profile.mobile,
            )

    async def close(self) -> None:
        if self._open:
            try:
                await self._req("close")
            except Exception as exc:  # noqa: BLE001
                logger.debug("device browser close: {}", exc)
        self._open = False


__all__ = [
    "DESKTOP_UA",
    "MOBILE_UA",
    "PROFILES",
    "BrowserBackend",
    "BrowserProfile",
    "DeviceBackend",
    "PlaywrightBackend",
    "profile_named",
]
