"""``nanomuse chatgpt`` — the ChatGPT sign-in from a terminal.

    nanomuse chatgpt login     sign in with a ChatGPT plan (the browser opens; PKCE)
    nanomuse chatgpt status    who is signed in, when the token expires
    nanomuse chatgpt usage     what is left of the plan's windows, as OpenAI reports it
    nanomuse chatgpt logout    forget the sign-in
    nanomuse chatgpt proxy     a loopback OpenAI-compatible server over the sign-in

``[llm] proxy`` in config.toml (or ``--proxy``) sends every request to chatgpt.com through an
HTTP(S) or SOCKS proxy, for a machine whose network cannot reach it directly.

With ``--json`` stdout carries one JSON object per line and nothing else; progress and the
honesty line go to stderr. The shapes are in the runtime team's ``CONTRACT-chatgpt.md``.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
import sys
import threading
import tomllib
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from rich.console import Console

from nanomuse.config import Settings, find_config_file, load_settings
from nanomuse.llm.chatgpt import (
    BUILTIN_MODELS,
    HONESTY_LINE,
    LOGIN_TIMEOUT_S,
    REDIRECT_PORT,
    ChatGPTError,
    LoginFlow,
    TokenStore,
)

chatgpt_app = typer.Typer(
    help="Sign in with a ChatGPT plan and use it for chat and the hands.", no_args_is_help=True
)
#: everything a person reads goes to stderr, so `--json` leaves stdout to the events
err = Console(stderr=True)

ConfigOpt = Annotated[Path | None, typer.Option("--config", "-c", help="Path to config.toml")]
JsonOpt = Annotated[bool, typer.Option("--json", help="One JSON object per line on stdout.")]


def _settings(config: Path | None) -> Settings:
    try:
        return load_settings(config)
    except FileNotFoundError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    except tomllib.TOMLDecodeError as exc:
        err.print(f"[red]config.toml is not valid TOML[/red] ({find_config_file(config)}): {exc}")
        raise typer.Exit(1) from exc
    except ValidationError as exc:
        err.print(
            f"[red]config.toml has {exc.error_count()} setting(s) nanoMuse does not understand[/red] "
            f"({find_config_file(config)}):"
        )
        for e in exc.errors():
            err.print(f"  [bold]{'.'.join(str(x) for x in e['loc'])}[/bold]: {e['msg']}")
        raise typer.Exit(1) from exc


def _store(config: Path | None) -> TokenStore:
    return TokenStore.in_dir(_settings(config).data_dir)


def _proxy(config: Path | None, given: str | None) -> str | None:
    """``--proxy`` when given, else the `[llm] proxy` of the config, else none."""
    if given is not None:
        return given.strip() or None
    return _settings(config).llm.proxy.strip() or None


ProxyOpt = Annotated[
    str | None,
    typer.Option(
        "--proxy", help="An HTTP(S) or SOCKS proxy for chatgpt.com; default: \\[llm] proxy."
    ),
]


def _emit(as_json: bool, event: dict[str, Any], text: str = "") -> None:
    if as_json:
        sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    elif text:
        print(text)


def _fail(as_json: bool, code: str, message: str) -> None:
    _emit(as_json, {"event": "error", "code": code, "message": message})
    if not as_json:
        err.print(f"[red]{message}[/red]")
    raise typer.Exit(1)


def _open_browser(url: str) -> bool:
    if not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ) and sys.platform.startswith("linux"):
        return False
    try:
        import webbrowser

        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001
        return False


async def _read_stdin_line() -> str | None:
    """One line from stdin without blocking the loop; None when stdin closes. A daemon
    thread does the reading, so a client that never writes does not hold the exit."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str | None] = loop.create_future()

    def reader() -> None:
        try:
            line = sys.stdin.readline()
        except (OSError, ValueError):
            line = ""

        def deliver() -> None:
            if not future.done():
                future.set_result(line.strip() or None)

        if not loop.is_closed():
            loop.call_soon_threadsafe(deliver)

    threading.Thread(target=reader, name="chatgpt-login-stdin", daemon=True).start()
    return await future


# --------------------------------------------------------------------------- login
@chatgpt_app.command("login")
def login(
    config: ConfigOpt = None,
    as_json: JsonOpt = False,
    no_browser: Annotated[bool, typer.Option("--no-browser", help="Print the URL only.")] = False,
    port: Annotated[
        int, typer.Option("--port", help="Port to listen on for the callback.")
    ] = REDIRECT_PORT,
    timeout: Annotated[float, typer.Option("--timeout", help="Seconds to wait.")] = LOGIN_TIMEOUT_S,
) -> None:
    """Sign in with a ChatGPT plan.

    The browser opens OpenAI's sign-in page; when it comes back, the tokens are stored under the data directory (mode 0600).
    """
    store = _store(config)
    err.print(f"[dim]{HONESTY_LINE}[/dim]")

    async def run() -> None:
        flow = LoginFlow(store, port=port)
        bound = await flow.listen()
        _emit(
            as_json,
            {
                "event": "url",
                "url": flow.url,
                "callback": flow.callback_url,
                "expires_in": int(timeout),
            },
            f"Open this address to sign in:\n\n  {flow.url}\n",
        )
        if not no_browser and not as_json:
            if _open_browser(flow.url):
                err.print("[dim]the browser was opened[/dim]")
        if not bound:
            err.print(
                f"[yellow]port {port} is in use[/yellow]; when the sign-in finishes, paste the "
                "address the browser lands on (http://localhost:…/auth/callback?code=…) here:"
            )
        elif not as_json:
            err.print(
                "[dim]waiting for the sign-in to come back… (or paste the callback address)[/dim]"
            )
        _emit(as_json, {"event": "waiting"})
        # a pasted callback address: always under --json (the client's stdin), otherwise
        # when the port could not be bound or stdin is a pipe
        paste = _read_stdin_line if (as_json or not bound or not sys.stdin.isatty()) else None
        try:
            result = await flow.wait(timeout, paste=paste)
            token = await flow.finish(result)
        except ChatGPTError as exc:
            code = "port_busy" if exc.code == "port_busy" else exc.code
            _fail(as_json, code, exc.message)
            return
        _emit(
            as_json,
            {"event": "done", "ok": True, **token.public()},
            f"Signed in: {token.label} (token good for {token.expires_in // 60} min; "
            "renewed on its own).",
        )

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        _emit(as_json, {"event": "error", "code": "cancelled", "message": "interrupted"})
        raise typer.Exit(130) from None


# --------------------------------------------------------------------------- status
@chatgpt_app.command("status")
def status(config: ConfigOpt = None, as_json: JsonOpt = False) -> None:
    """Who is signed in and until when. Never touches the network."""
    store = _store(config)
    token = store.load()
    view: dict[str, Any] = {
        "signed_in": token is not None,
        "label": token.label if token else "",
        "plan": token.plan if token else "",
        "account_id": token.account_id if token else "",
        "expires_at": token.expires_at if token else 0,
        "expires_in": token.expires_in if token else 0,
        "path": str(store.path),
        "models": list(BUILTIN_MODELS),
    }
    if as_json:
        _emit(True, view)
        return
    if token is None:
        print(f"not signed in (run `nanomuse chatgpt login`); store: {store.path}")
        return
    when = (
        f"expires in {token.expires_in // 60} min (renewed on use)"
        if token.expires_in
        else "expired; renewed on the next request"
    )
    print(f"{token.label} · {when}\nstore: {store.path}")


# --------------------------------------------------------------------------- usage
@chatgpt_app.command("usage")
def usage(config: ConfigOpt = None, as_json: JsonOpt = False, proxy: ProxyOpt = None) -> None:
    """What is left of the plan's usage windows, as OpenAI reports it.

    One request to chatgpt.com; the token is refreshed first when it is about to expire."""
    from nanomuse.llm.chatgpt import Auth, fetch_usage, http_client

    store = _store(config)
    if store.load() is None:
        _fail(as_json, "not_signed_in", "not signed in; run `nanomuse chatgpt login`")
        raise typer.Exit(1)
    via = _proxy(config, proxy)

    async def run() -> dict[str, Any]:
        import httpx

        auth = Auth(store, proxy=via)
        http = http_client(httpx.Timeout(15.0, connect=10.0), via)
        try:
            token = await auth.token()
            limits = await fetch_usage(token, http)
        finally:
            await http.aclose()
            await auth.close()
        return {"label": token.label, "plan": token.plan, "limits": limits.public()}

    try:
        view = asyncio.run(run())
    except ChatGPTError as exc:
        _fail(as_json, exc.code, exc.message)
        if not as_json:
            err.print(f"[red]{exc.message}[/red]")
        raise typer.Exit(1) from None
    if as_json:
        _emit(True, view)
        return
    limits = view["limits"]
    lines = [view["label"]]
    for name, window in (
        ("5-hour window", limits["primary"]),
        ("weekly window", limits["secondary"]),
    ):
        if window:
            hours, rest = divmod(int(window["resets_in_s"]), 3600)
            lines.append(
                f"{name}: {window['used_percent']}% used, resets in {hours} h {rest // 60} min"
            )
    if limits["primary"] is None and limits["secondary"] is None:
        lines.append("OpenAI reported no usage windows for this plan")
    print("\n".join(lines))


# --------------------------------------------------------------------------- logout
@chatgpt_app.command("logout")
def logout(config: ConfigOpt = None, as_json: JsonOpt = False) -> None:
    """Forget the sign-in (nothing is revoked upstream)."""
    was = _store(config).clear()
    _emit(as_json, {"ok": True, "was_signed_in": was}, "signed out" if was else "was not signed in")


# --------------------------------------------------------------------------- proxy
@chatgpt_app.command("proxy")
def proxy(
    config: ConfigOpt = None,
    as_json: JsonOpt = False,
    port: Annotated[int, typer.Option("--port", help="0 = the OS picks one.")] = 0,
    host: Annotated[
        str, typer.Option("--host", help="Bind address; keep it on the loopback interface.")
    ] = "127.0.0.1",
    token: Annotated[str | None, typer.Option("--token", help="The local bearer token.")] = None,
    proxy: ProxyOpt = None,
) -> None:
    """An OpenAI-compatible server on the loopback interface, answering with the ChatGPT sign-in.

    GET /v1/models, POST /v1/chat/completions. Every request wants `Authorization: Bearer <local token>`.
    """
    import uvicorn

    from nanomuse.llm.chatgpt_proxy import make_app

    store = _store(config)
    stored = store.load()
    if stored is None:
        _fail(as_json, "not_signed_in", "not signed in; run `nanomuse chatgpt login`")
        return
    local_token = token or secrets.token_urlsafe(24)
    app = make_app(store, local_token, proxy=_proxy(config, proxy))
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))

    async def run() -> None:
        loop = asyncio.get_running_loop()
        serve = loop.create_task(server.serve())
        while not server.started and not serve.done():
            await asyncio.sleep(0.05)
        if serve.done():
            exc = serve.exception()
            _emit(
                as_json,
                {"event": "error", "code": "port_busy", "message": str(exc or "did not start")},
            )
            raise typer.Exit(1)
        bound = next((s.getsockname() for s in server.servers[0].sockets), (host, port))
        url = f"http://{bound[0]}:{bound[1]}/v1"
        _emit(
            as_json,
            {
                "event": "ready",
                "url": url,
                "token": local_token,
                "label": stored.label,
                "models": list(BUILTIN_MODELS),
            },
            f"ChatGPT proxy at {url}\nAuthorization: Bearer {local_token}\n(Ctrl-C stops it)",
        )
        stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):  # Windows, or not the main thread
                pass
        waiter = loop.create_task(stop.wait())
        await asyncio.wait({serve, waiter}, return_when=asyncio.FIRST_COMPLETED)
        reason = "signal" if stop.is_set() else "error"
        server.should_exit = True
        await serve
        _emit(as_json, {"event": "exit", "reason": reason, "message": ""})

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        _emit(as_json, {"event": "exit", "reason": "signal", "message": ""})
        raise typer.Exit(130) from None


__all__ = ["chatgpt_app"]
