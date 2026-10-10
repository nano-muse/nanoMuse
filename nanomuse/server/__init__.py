"""nanoMuse app server: the always-on agent behind the mobile-first web app.

    nanomuse serve                     # http://127.0.0.1:8787
    nanomuse serve --host 0.0.0.0      # reachable from your phone on the same Wi-Fi

Everything the CLI can do, the app can do — plus background work while the app
is closed, approval cards, side chats, goals, ideas, memory you can edit, and an
activity log behind the avatar.
"""

from __future__ import annotations

import contextlib
import os
import socket
import sys
import threading
import traceback

from nanomuse import __version__, loopback
from nanomuse.certs import ensure_ca_bundle
from nanomuse.config import Settings
from nanomuse.server.api import STATIC_DIR, create_app
from nanomuse.server.service import MuseService

__all__ = ["MuseService", "STATIC_DIR", "bridge_url", "create_app", "lan_ip", "port_taken", "serve"]


def bridge_url(host: str, port: int) -> str:
    """Where a command on this machine reaches the server: the loopback when the server
    listens on every address or on it, the one address it listens on otherwise."""
    if host in ("", "0.0.0.0", "127.0.0.1", "localhost"):
        return f"http://127.0.0.1:{port}"
    if host in ("::", "::1"):
        return f"http://[::1]:{port}"
    return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"


def lan_ip() -> str | None:
    """Best-effort LAN address (no packets are actually sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def port_taken(host: str, port: int, timeout: float = 0.5) -> str | None:
    """What already answers on ``host:port``, if anything: ``"nanoMuse <version>"`` when it
    is one of ours (its ``/api/health`` says so), ``"another program"`` otherwise, ``None``
    when nothing listens there. A connect, not a bind: a bind would mistake the previous
    run's closing connections for a listener."""
    probe_host = {"": "127.0.0.1", "0.0.0.0": "127.0.0.1", "localhost": "127.0.0.1", "::": "::1"}
    where = probe_host.get(host, host)
    try:
        with socket.create_connection((where, port), timeout=timeout):
            pass
    except OSError:
        return None
    import json
    import urllib.request

    base = f"http://[{where}]:{port}" if ":" in where else f"http://{where}:{port}"
    try:
        with urllib.request.urlopen(f"{base}/api/health", timeout=timeout * 4) as response:  # noqa: S310
            health = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - not HTTP, not JSON, not answering: not ours
        return "another program"
    if isinstance(health, dict) and health.get("ok") is True and health.get("version"):
        return f"nanoMuse {health['version']}"
    return "another program"


def serve(
    settings: Settings,
    host: str | None = None,
    port: int | None = None,
    print_qr: bool = True,
    log_level: str = "warning",
) -> None:
    """Run the app server (blocking). Prints the URL and a QR code for your phone."""
    import uvicorn

    _utf8_console()
    ensure_ca_bundle()
    # Windows: asyncio's self-pipe is a loopback connection; on a machine that intercepts
    # those the loop would never start. Say so and stop, rather than listen on nothing.
    loopback.install()
    problem = loopback.check()
    if problem:
        print(f"nanoMuse: {problem}", file=sys.stderr, flush=True)
        raise SystemExit(78)
    host = host or settings.server.host
    port = port or settings.server.port
    taken = port_taken(host, port)
    if taken:
        # before the service starts: a second `nanomuse serve` used to open the data directory,
        # announce itself as ready, link included, and only then die on uvicorn's bind error
        advice = (
            "That one keeps running: open it in the browser, or stop it before starting another."
            if taken.startswith("nanoMuse")
            else "Stop it, or choose another port with --port."
        )
        print(
            f"nanoMuse: port {port} on {host} is already in use by {taken}. {advice}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(98)
    service = MuseService(settings)
    service.bridge.base_url = bridge_url(host, port)
    app = create_app(settings, service)

    shown_host = host
    if host in ("0.0.0.0", "::", ""):
        shown_host = lan_ip() or "127.0.0.1"
    url = f"http://[{shown_host}]:{port}/" if ":" in shown_host else f"http://{shown_host}:{port}/"
    if service.token:
        # in the fragment: the browser keeps it to itself, so it is in no access log
        url += f"#token={service.token}"
    # the banner once the socket is about to open (a desktop shell reads the log when the
    # app takes long to answer); the services may still be coming up behind it, and
    # /api/health says which one
    print(f"nanoMuse {__version__} starting on {host}:{port} (pid {os.getpid()})", flush=True)
    serving = threading.Event()

    def on_ready() -> None:
        serving.set()
        _print_banner(url, service, print_qr)

    app.state.on_ready = on_ready
    _watch_startup(serving)
    # The standard loop, not uvloop: uvloop leaves extra copies of a child's stdout/stderr
    # open in the child, so anything it leaves running in the background (Cursor's CLI keeps a
    # worker alive, `nohup … &` in the shell tool) holds our pipes and the read never ends.
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
        loop="asyncio",
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )


def _watch_startup(serving: threading.Event, after: tuple[float, ...] = (20, 40)) -> None:
    """A daemon thread that, should the socket still not be open 20 s and then 60 s after
    the banner, writes where every thread is to stderr. A machine on which the runtime
    starts and then says nothing (a Windows box whose security software holds the
    loopback, a stalled import) is then diagnosable from the desktop shell's log."""

    def watch() -> None:
        waited = 0.0
        for delay in after:
            if serving.wait(delay):
                return
            waited += delay
            _dump_threads(f"still not serving after {waited:.0f} s")

    threading.Thread(target=watch, name="startup-watchdog", daemon=True).start()


def _dump_threads(why: str) -> None:
    lines = [f"nanoMuse: {why}; where every thread is:"]
    names = {t.ident: t.name for t in threading.enumerate()}
    for ident, frame in sys._current_frames().items():
        lines.append(f"--- thread {names.get(ident, '?')} ({ident})")
        lines.extend(line.rstrip() for line in traceback.format_stack(frame))
    with contextlib.suppress(Exception):
        print("\n".join(lines), file=sys.stderr, flush=True)


def _utf8_console() -> None:
    """UTF-8 on stdout/stderr, line-buffered, whatever the console's code page: the frozen
    runtime does not read ``PYTHONUTF8``/``PYTHONUNBUFFERED``, and a Windows log in GBK
    with the banner's dashes mangled is what the desktop shell showed otherwise."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _print_banner(url: str, service: MuseService, print_qr: bool) -> None:
    from rich.console import Console

    console = Console()
    name = (service.profile.name or "").strip()
    # "nanoMuse · Lumi is ready."; before the agent has a name of its own, "nanoMuse is ready."
    who = f" · [bold]{name}[/bold]" if name and name != "nanoMuse" else ""
    console.print(f"[bold magenta]nanoMuse[/bold magenta]{who} is ready.")
    if not STATIC_DIR.is_dir():
        console.print(
            "[yellow]web app not built[/yellow]: run `cd web && npm install && npm run build`"
        )
    console.print(f"Open on this device or your phone:  [bold cyan]{url}[/bold cyan]")
    if service.token:
        console.print(
            "[dim]The link includes your access token; share it only with your own devices.[/dim]"
        )
    if print_qr:
        try:
            import qrcode

            qr = qrcode.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except Exception:  # noqa: BLE001  pragma: no cover
            pass
    console.print(
        "[dim]Press Ctrl+C to stop. Your nanoMuse keeps working in the background while it runs.[/dim]"
    )
