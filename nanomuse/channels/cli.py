"""``nanomuse channels`` — the chat apps from a terminal.

    nanomuse channels status            what is on, connected, waiting
    nanomuse channels pending           pairing codes people were shown
    nanomuse channels approve <code>    let that person talk to the Muse
    nanomuse channels deny <code>
    nanomuse channels login feishu      create the Feishu bot from a QR code
    nanomuse channels test <name>       send a test message (or check the credentials)

When ``nanomuse serve`` is running, the commands go through its API so the change takes
effect at once. Otherwise they work on the files under ``<data_dir>/channels/`` and the
server picks them up when it starts.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from nanomuse.channels.base import json_object
from nanomuse.config import Settings, find_config_file, load_settings

channels_app = typer.Typer(
    help="Chat apps: Feishu, DingTalk, WeCom, Telegram.", no_args_is_help=True
)
console = Console()

ConfigOpt = Annotated[Path | None, typer.Option("--config", "-c", help="Path to config.toml")]

STATE_WORDS = {
    "off": "off",
    "unconfigured": "needs settings",
    "missing_sdk": "SDK not installed",
    "connecting": "connecting…",
    "connected": "connected",
    "error": "error",
}


def _settings(config: Path | None) -> Settings:
    try:
        settings = load_settings(config)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    except tomllib.TOMLDecodeError as exc:
        console.print(
            f"[red]config.toml is not valid TOML[/red] ({find_config_file(config)}): {exc}"
        )
        raise typer.Exit(1) from exc
    except ValidationError as exc:
        console.print(
            f"[red]config.toml has settings nanoMuse does not understand[/red] ({find_config_file(config)})"
        )
        raise typer.Exit(1) from exc
    settings.ensure_dirs()
    return settings


class _Server:
    """The running server's API, when there is one."""

    def __init__(self, settings: Settings):
        host = settings.server.host
        if host in ("0.0.0.0", "", "::"):
            host = "127.0.0.1"
        self.base = f"http://{host}:{settings.server.port}"
        token = settings.server.token
        if settings.server.auth and not token:
            path = settings.data_dir / "server_token"
            if path.exists():
                token = path.read_text("utf-8").strip()
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def call(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """``None`` when no server answers; raises with the server's words on an error."""
        import httpx

        try:
            response = httpx.request(
                method, self.base + path, json=body, headers=self.headers, timeout=15
            )
        except httpx.ConnectError:
            return None
        except httpx.HTTPError as exc:
            raise RuntimeError(str(exc)) from exc
        if response.status_code == 401:
            raise RuntimeError("the server refused the token (server.token in config.toml?)")
        if response.status_code >= 400:
            detail = str(json_object(response).get("detail") or "")
            raise RuntimeError(detail or f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError(
                f"HTTP {response.status_code}: the server did not answer with JSON"
            ) from None
        return data if isinstance(data, dict) else {"result": data}


def _stores(settings: Settings) -> tuple[Any, Any]:
    from nanomuse.channels.store import ChannelSettingsStore, PairingStore
    from nanomuse.vault.vault import CredentialVault

    vault = CredentialVault(settings.vault_file, settings.vault_key_file)
    return ChannelSettingsStore(settings.data_dir, vault, settings.source), PairingStore(
        settings.data_dir
    )


def _offline_view(settings: Settings) -> dict[str, Any]:
    from nanomuse.channels.manager import CHANNEL_TYPES

    store, pairing = _stores(settings)
    channels = []
    for cls in CHANNEL_TYPES:
        cfg = store.config(cls.name)
        if not cfg.enabled:
            state, detail = "off", ""
        elif not cls.sdk_available():
            state, detail = "missing_sdk", cls.install_hint()
        elif cls.missing(cfg.settings):
            state, detail = "unconfigured", ", ".join(cls.missing(cfg.settings))
        else:
            state, detail = "off", "server not running"
        channels.append(
            {
                "name": cls.name,
                "label": cls.label,
                "enabled": cfg.enabled,
                "status": {"state": state, "detail": detail},
                "paired": [
                    {"sender_id": sid, **entry} for sid, entry in pairing.approved(cls.name).items()
                ],
            }
        )
    return {"channels": channels, "pending": pairing.pending(), "offline": True}


def _fail(exc: BaseException) -> None:
    console.print(f"[bold red]error:[/bold red] {exc}")
    raise typer.Exit(1) from None


@channels_app.command("status")
def status(
    config: ConfigOpt = None,
    as_json: Annotated[bool, typer.Option("--json", help="The same as JSON, for scripts")] = False,
) -> None:
    """What is switched on, connected, and who is paired."""
    settings = _settings(config)
    try:
        view = _Server(settings).call("GET", "/api/channels")
    except RuntimeError as exc:
        _fail(exc)
    if view is None:
        view = _offline_view(settings)
    if as_json:
        console.print_json(json.dumps(view, ensure_ascii=False))
        return
    table = Table(title="Chat apps")
    table.add_column("channel")
    table.add_column("state")
    table.add_column("paired", justify="right")
    table.add_column("deliver here", justify="right")
    table.add_column("detail")
    for item in view.get("channels", []):
        status = item.get("status") or {}
        paired = item.get("paired") or []
        table.add_row(
            item.get("label", item.get("name")),
            STATE_WORDS.get(status.get("state", ""), status.get("state", "")),
            str(len(paired)),
            str(sum(1 for p in paired if p.get("deliver"))),
            str(status.get("detail") or ""),
        )
    console.print(table)
    if view.get("offline"):
        console.print("[dim]nanomuse serve is not running; this is what is on disk.[/dim]")
    pending = view.get("pending") or []
    if pending:
        console.print(f"{len(pending)} pairing code(s) waiting: `nanomuse channels pending`.")


@channels_app.command("pending")
def pending(config: ConfigOpt = None) -> None:
    """Pairing codes people were shown and that wait for a yes."""
    settings = _settings(config)
    try:
        view = _Server(settings).call("GET", "/api/channels")
    except RuntimeError as exc:
        _fail(exc)
    if view is None:
        view = _offline_view(settings)
    items = view.get("pending") or []
    if not items:
        console.print("No pairing codes waiting.")
        return
    table = Table()
    table.add_column("code")
    table.add_column("channel")
    table.add_column("who")
    for item in items:
        who = item.get("sender_name") or item.get("sender_id", "")
        table.add_row(item.get("code", ""), item.get("channel", ""), str(who))
    console.print(table)
    console.print("Approve one with `nanomuse channels approve <code>`.")


@channels_app.command("approve")
def approve(code: str, config: ConfigOpt = None) -> None:
    """Let the person who got this code talk to the Muse."""
    settings = _settings(config)
    code = code.strip().upper()
    try:
        result = _Server(settings).call("POST", f"/api/channels/pairing/{code}/approve")
    except RuntimeError as exc:
        _fail(exc)
    if result is None:
        _, pairing = _stores(settings)
        entry = pairing.approve(code)
        if entry is None:
            _fail(RuntimeError("no pairing with that code (codes last 10 minutes)"))
            return
        who = entry.get("sender_name") or entry["sender_id"]
        console.print(f"Paired {who} on {entry['channel']}. The server will see it when it runs.")
        return
    paired = result.get("paired") or {}
    who = paired.get("sender_name") or paired.get("sender_id", "")
    console.print(f"Paired {who} on {paired.get('channel', '')}.")


@channels_app.command("deny")
def deny(code: str, config: ConfigOpt = None) -> None:
    """Throw a pairing code away."""
    settings = _settings(config)
    code = code.strip().upper()
    try:
        result = _Server(settings).call("POST", f"/api/channels/pairing/{code}/deny")
    except RuntimeError as exc:
        _fail(exc)
    if result is None:
        _, pairing = _stores(settings)
        if pairing.deny(code) is None:
            _fail(RuntimeError("no pairing with that code"))
            return
    console.print("Denied.")


@channels_app.command("login")
def login(
    name: str = typer.Argument("feishu", help="Only feishu has a scan-to-create login"),
    lark: bool = typer.Option(False, "--lark", help="Lark (international) instead of 飞书"),
    config: ConfigOpt = None,
) -> None:
    """Create the Feishu bot by scanning a QR code; the id and secret are saved for you."""
    if name != "feishu":
        _fail(
            RuntimeError(
                "only `login feishu` exists; the others take an id and a secret in the app"
            )
        )
    settings = _settings(config)
    domain = "lark" if lark else "feishu"
    from nanomuse.channels import feishu

    def show(url: str) -> None:
        console.print("Scan this with Feishu (or open the link) and confirm the new bot:")
        try:
            import qrcode

            qr = qrcode.QRCode(border=1)
            qr.add_data(url)
            qr.print_ascii(out=sys.stdout, invert=True)
        except Exception:  # noqa: BLE001
            pass
        console.print(url)

    try:
        result = feishu.wait_for_login(domain, settings.agent.name or "nanoMuse", show)
    except Exception as exc:  # noqa: BLE001
        _fail(exc)
        return
    if result.get("status") != "succeeded":
        _fail(RuntimeError(f"login did not finish ({result.get('error') or 'declined'})"))
        return
    from nanomuse.channels.feishu import FeishuChannel

    store, _ = _stores(settings)
    store.update(
        FeishuChannel,
        enabled=True,
        values={
            "app_id": result["app_id"],
            "app_secret": result["app_secret"],
            "domain": result.get("domain") or domain,
        },
    )
    console.print(f"Feishu bot created (App ID {result['app_id']}); the secret is in the vault.")
    try:
        reloaded = _Server(settings).call("POST", "/api/channels/reload")
    except RuntimeError as exc:
        console.print(f"[yellow]saved, but the running server did not reload: {exc}[/yellow]")
        return
    if reloaded is None:
        console.print("Start `nanomuse serve` (or restart it) and send the bot a message.")
    else:
        console.print("The server is connecting. Send the bot a message in Feishu to pair.")


@channels_app.command("test")
def test(
    name: str,
    chat: str = typer.Option("", "--chat", help="A chat id; default: the first paired chat"),
    config: ConfigOpt = None,
) -> None:
    """Send a test message through a channel (or check its credentials)."""
    settings = _settings(config)
    try:
        result = _Server(settings).call("POST", f"/api/channels/{name}/test", {"chat_id": chat})
    except RuntimeError as exc:
        _fail(exc)
    if result is None:
        _fail(RuntimeError("nanomuse serve is not running; the test goes through it"))
        return
    console.print(result.get("detail") or "OK")


__all__ = ["channels_app"]
