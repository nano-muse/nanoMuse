"""The HTTP surface.

Two kinds of host reach this process:

- ``<session-id>.<SESSION_DOMAIN>`` — the phone talking to its Muse. Everything on such a host
  is relayed to that session's container (HTTP and ``/ws``).
- ``<account-slug>.<SESSION_DOMAIN>`` — someone in the browser with their own, kept Muse
  (nanoMuse Web, accounts.py); relayed the same way, the container woken when it slept.
- everything else — the showcase itself: ``/api/demo/*`` to start and inspect sessions,
  ``/api/trial`` for the phone app's trial credentials, ``/llm/*`` for the containers' model
  calls (they reach us over the sessions network) and the trials' (they come from the
  internet, through Caddy), ``/web/`` and ``/api/web/*`` for nanoMuse Web's sign-in, and,
  in development, the built MobileGym as static files.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.responses import Response
from starlette.routing import Host, Route, Router, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import __version__, llm
from .accounts import AccountManager, AccountStore, Asleep
from .clips import Clips, is_clip_path
from .config import Settings
from .images import Pictures, is_image_path
from .logs import redact_tokens_in_logs
from .proxy import proxy_http, proxy_ws
from .runner import DockerRunner
from .sessions import Provider, Refused, SessionManager, resolve_provider
from .trials import TrialManager, TrialStore
from .visitors import VisitorBook, VisitorStore
from .wake import proof_from_http, proof_from_token, token_from_first_frame, wake_page
from .webpage import PAGE as WEB_PAGE

log = logging.getLogger("showcase")

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

# what a browser sees at the address of a session that is over
ENDED_PAGE = """<!doctype html><meta charset="utf-8"><title>nanoMuse</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<body style="margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font:15px/1.5 system-ui,sans-serif;color:#1b1730;background:#f4f3fa;text-align:center;padding:24px">
<div><div style="font-size:40px">🧸</div><p style="margin:12px 0 4px;font-weight:600">This Muse has ended.</p>
<p style="margin:0;color:#6b6880">Demo sessions last a while, then go — with everything in them.<br>
Open nanoMuse on the phone for a new one.</p></div></body>"""


class ProviderIn(BaseModel):
    base_url: str = Field(min_length=8, max_length=300)
    api_key: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=200)


class SessionIn(BaseModel):
    provider: ProviderIn | None = None
    # the visitor's time zone (an IANA name, what Intl gives the page), so the Muse's clock
    # is the visitor's: a reminder "in 2 minutes" lands in 2 minutes and says the right time.
    # Unset or unknown → the container's own (UTC).
    time_zone: str = Field("", max_length=64, pattern=r"^[A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+)*$")


class TrialIn(BaseModel):
    # a random id the app makes once and keeps; long enough that guessing one is not a plan
    device: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class WebCodeIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=120)


class WebVerifyIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=120)
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")
    # a friend's invite code (relay 0.4), passed on as typed; the relay decides what it is worth
    invite: str = Field(default="", max_length=32)


class WebLoginIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=200)


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _refused(exc: Refused) -> JSONResponse:
    return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status)


class Spa(StaticFiles):
    """Static files, and the app's ``index.html`` for any path that is not a file.

    Hashed assets (``/assets/*``) may be cached for good; everything else — the pages, the
    phone's page in its frame, ``page/*`` — is revalidated on every visit, so a new build is
    seen at once (the production Caddyfile does the same).
    """

    async def get_response(self, path: str, scope) -> Response:  # noqa: ANN001
        try:
            response = await super().get_response(path, scope)
        except Exception:  # noqa: BLE001 — StaticFiles raises HTTPException(404)
            if "." in path.rsplit("/", 1)[-1]:
                raise
            response = FileResponse(os.path.join(self.directory or ".", "index.html"))
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(
    settings: Settings,
    manager: SessionManager,
    client: httpx.AsyncClient | None = None,
    trials: TrialManager | None = None,
    accounts: AccountManager | None = None,
    visitors: VisitorBook | None = None,
) -> FastAPI:
    http = client or httpx.AsyncClient(
        timeout=httpx.Timeout(300, connect=10), follow_redirects=False
    )
    if trials is None:
        trials = TrialManager(
            settings,
            TrialStore(settings.trial_db if settings.trial_enabled else ":memory:"),
            clock=manager.clock,
        )
    if accounts is None:
        accounts = AccountManager(
            settings,
            manager.runner,
            AccountStore(settings.web_db if settings.web_enabled else ":memory:"),
            http=http,
            clock=manager.clock,
        )
    if visitors is None:
        visitors = VisitorBook(
            settings,
            VisitorStore(settings.visitor_db if settings.demo_signin_required else ":memory:"),
            http=http,
            clock=manager.clock,
        )
    pictures = Pictures(settings, http)
    clips = Clips(settings, http)
    manager.on_end = visitors.ended  # the visit row gets what the demo used

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        await manager.startup()
        await accounts.startup()
        reapers = [
            asyncio.create_task(manager.reap_forever()),
            asyncio.create_task(accounts.reap_forever()),
        ]
        try:
            yield
        finally:
            for task in reapers:
                task.cancel()
            await manager.shutdown()
            await http.aclose()

    app = FastAPI(title="nanoMuse showcase gateway", version=__version__, lifespan=lifespan)
    # the request lines (uvicorn's, and httpx's for what is relayed) never carry a session
    # token, whatever form a client still uses to send it (logs.py)
    redact_tokens_in_logs()

    # ------------------------------------------------------------- the phone → its Muse
    async def _behind(host_id: str, proves=None):
        """The session or the account behind ``<id>.<domain>``, or None. Waking a slept
        account's container happens here, so a first request may take a few seconds — and
        only for a request that proves the account's token (``proves``; ``Asleep`` otherwise:
        anyone can type the address, only the person has the token)."""
        sess = manager.get(host_id)
        if sess is not None:
            manager.touch(sess)
            return sess, lambda: manager.touch(sess)
        account = await accounts.for_host(host_id, proves)
        if account is None:
            return None, None
        return account, lambda: accounts.touch(account)

    signin_url = f"{settings.site_origin()}/web/"

    # The phone in the browser runs on the site's origin while its Muse answers on the
    # session's host, so what the nanoMuse app module posts from the phone itself — Allow
    # once / Deny on the capsule (POST /api/approvals/{id}), Done on a hold, the reply
    # language from the page's (PUT /api/settings) — is a cross-origin request with a JSON body and a bearer header: the browser asks first
    # (OPTIONS), and the runtime inside the container knows nothing of this origin and
    # answers 405, so the answer never leaves the phone. The gateway speaks for the sessions
    # here: the preflight is answered for the site's origin alone, and a relayed response
    # to a request from it is stamped so the browser hands it over. The web app in the frame
    # is on the session's own origin and needs none of this.
    site_origin = settings.site_origin()

    def cors_headers(request: Request) -> dict[str, str]:
        if request.headers.get("origin") != site_origin:
            return {}
        return {
            "Access-Control-Allow-Origin": site_origin,
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        }

    async def session_http(request: Request) -> Response:
        cors = cors_headers(request)
        if request.method == "OPTIONS" and cors:
            return Response(status_code=204, headers=cors)
        try:
            target, touch = await _behind(request.path_params["sid"], proof_from_http(request))
        except Asleep as exc:
            if "text/html" in request.headers.get("accept", ""):
                return HTMLResponse(wake_page(signin_url))
            return JSONResponse(
                {"error": exc.code, "message": exc.message},
                status_code=exc.status,
                headers={"Retry-After": "3", **cors},
            )
        except Refused as exc:
            # with the CORS headers too, so the phone's page reads the reason, not a bare failure
            response = _refused(exc)
            for name, value in cors.items():
                response.headers[name] = value
            return response
        if target is None:
            if "text/html" in request.headers.get("accept", ""):
                return HTMLResponse(ENDED_PAGE, status_code=404)
            return JSONResponse(
                {"error": "no_session", "message": "This demo session has ended."},
                status_code=404,
                headers=cors,
            )
        response = await proxy_http(request, http, target.http_base)
        for name, value in cors.items():
            response.headers[name] = value
        return response

    async def session_wake(request: Request) -> Response:
        """The wake page's request: the token in the header wakes the account's Muse (or
        it is already up); without the right token nothing starts."""
        try:
            target, _ = await _behind(request.path_params["sid"], proof_from_http(request))
        except Asleep:
            return JSONResponse(
                {"error": "token", "message": "That link is not yours to open."}, status_code=401
            )
        except Refused as exc:
            return _refused(exc)
        if target is None:
            return JSONResponse(
                {"error": "no_session", "message": "This demo session has ended."}, status_code=404
            )
        return Response(status_code=204)

    async def session_ws(ws: WebSocket) -> None:
        sid = ws.path_params["sid"]
        accepted = False
        first: str | None = None
        try:
            # the clients send the token as the first frame; a page or app still on the older
            # ?token= form is served this release, and the value is never logged (logs.py)
            target, touch = await _behind(sid, proof_from_token(ws.query_params.get("token")))
        except Asleep:
            # the token travels in the socket's first frame (the runtime's way since 0.1.31):
            # take the frame, prove the token with it, wake, and pass the frame on
            await ws.accept()
            accepted = True
            try:
                first = await asyncio.wait_for(ws.receive_text(), 10)
            except (TimeoutError, RuntimeError, WebSocketDisconnect):
                first = None
            try:
                target, touch = await _behind(sid, proof_from_token(token_from_first_frame(first)))
            except Refused:
                target, touch = None, None
        except Refused:
            target, touch = None, None
        if target is None:
            # accept first: a close before the handshake reaches the browser as a bare failure,
            # the code only travels on an open socket (the phone module and the web app read
            # 4404 as "gone" and stop reconnecting)
            if not accepted:
                await ws.accept()
            await ws.close(code=4404, reason="this session has ended")
            log.debug("ws %s: gone (4404)", sid)
            return
        url = f"{target.ws_base}{ws.url.path}"
        if ws.url.query:
            url += f"?{ws.url.query}"
        await proxy_ws(ws, url, touch, label=sid, first=first, accepted=accepted)

    session_router = Router(
        routes=[
            WebSocketRoute("/ws", session_ws),
            Route("/__wake", session_wake, methods=["POST"]),
            Route("/{path:path}", session_http, methods=_METHODS),
        ]
    )
    app.router.routes.insert(0, Host(f"{{sid}}.{settings.session_domain}", app=session_router))

    # ------------------------------------------------------------- the showcase API
    @app.get("/api/demo/info")
    async def info() -> dict[str, Any]:
        return {
            "version": __version__,
            "session_ttl_s": settings.session_ttl_s,
            "idle_ttl_s": settings.idle_ttl_s,
            "demo_model": settings.main.model if settings.main.configured else None,
            "gui_model": settings.gui.model if settings.gui.configured else None,
            "image_model": settings.image_model if pictures.enabled else None,
            "video_model": settings.video_model if pictures.enabled and clips.enabled else None,
            "byok": settings.byok_enabled,
            "byok_hosts": list(settings.byok_hosts) if settings.byok_enabled else [],
            "signin_required": visitors.required,
            "quota": {
                "requests": settings.session_requests,
                "tokens": settings.session_tokens,
                "pictures": settings.image_per_session if pictures.enabled else 0,
                "clips": settings.clips_per_session if pictures.enabled and clips.enabled else 0,
            },
            **manager.stats(),
            "trial": trials.stats(),
            "web": accounts.stats(),
            "signin": visitors.stats(),
        }

    # ------------------------------------------------------------- the visitor's sign-in
    @app.post("/api/demo/signin/code", status_code=204)
    async def signin_code(body: WebCodeIn, request: Request) -> Response:
        try:
            await visitors.request_code(
                body.identifier.strip(), client_ip(request, settings.trust_proxy)
            )
        except Refused as exc:
            return _refused(exc)
        return Response(status_code=204)

    @app.post("/api/demo/signin/verify")
    async def signin_verify(body: WebVerifyIn, request: Request) -> Response:
        try:
            ticket, visitor = await visitors.verify(
                body.identifier.strip(),
                body.code,
                client_ip(request, settings.trust_proxy),
                invite=body.invite.strip(),
                ua=request.headers.get("user-agent", ""),
            )
        except Refused as exc:
            return _refused(exc)
        return JSONResponse(
            {"ticket": ticket, "visitor": visitor.public()}, headers={"Cache-Control": "no-store"}
        )

    @app.post("/api/demo/signin/login")
    async def signin_login(body: WebLoginIn, request: Request) -> Response:
        try:
            ticket, visitor = await visitors.login(
                body.identifier.strip(),
                body.password,
                client_ip(request, settings.trust_proxy),
                ua=request.headers.get("user-agent", ""),
            )
        except Refused as exc:
            return _refused(exc)
        return JSONResponse(
            {"ticket": ticket, "visitor": visitor.public()}, headers={"Cache-Control": "no-store"}
        )

    @app.get("/api/demo/me")
    async def signin_me(request: Request) -> Response:
        try:
            visitor = visitors.check(llm.bearer(request))
        except Refused as exc:
            return _refused(exc)
        return JSONResponse({"visitor": visitor.public()}, headers={"Cache-Control": "no-store"})

    @app.post("/api/demo/signout", status_code=204)
    async def signin_out(request: Request) -> Response:
        visitors.sign_out(llm.bearer(request))
        return Response(status_code=204)

    # ------------------------------------------------------------- nanoMuse Web (accounts)
    @app.get("/web", include_in_schema=False)
    async def web_root() -> Response:
        return RedirectResponse("/web/", status_code=308)

    @app.get("/web/", include_in_schema=False)
    async def web_page() -> Response:
        # with the kept Muses switched off, the web entry is the phone in the browser — the
        # showcase site — wherever /web was reached (the project site proxies it here)
        if not settings.web_enabled:
            return RedirectResponse(settings.site_origin() + "/", status_code=302)
        return HTMLResponse(WEB_PAGE, headers={"Cache-Control": "no-store"})

    @app.get("/api/web/info")
    async def web_info() -> dict[str, Any]:
        return {"version": __version__, **accounts.stats()}

    @app.post("/api/web/code", status_code=204)
    async def web_code(body: WebCodeIn, request: Request) -> Response:
        try:
            await accounts.request_code(
                body.identifier.strip(), client_ip(request, settings.trust_proxy)
            )
        except Refused as exc:
            return _refused(exc)
        return Response(status_code=204)

    @app.post("/api/web/verify")
    async def web_verify(body: WebVerifyIn, request: Request) -> Response:
        try:
            account = await accounts.verify(
                body.identifier.strip(),
                body.code,
                client_ip(request, settings.trust_proxy),
                invite=body.invite.strip(),
            )
        except Refused as exc:
            return _refused(exc)
        return JSONResponse(account.public(settings), headers={"Cache-Control": "no-store"})

    @app.post("/api/web/login")
    async def web_login(body: WebLoginIn, request: Request) -> Response:
        try:
            account = await accounts.login(
                body.identifier.strip(), body.password, client_ip(request, settings.trust_proxy)
            )
        except Refused as exc:
            return _refused(exc)
        return JSONResponse(account.public(settings), headers={"Cache-Control": "no-store"})

    @app.post("/api/demo/session", status_code=201)
    async def start(body: SessionIn, request: Request) -> Response:
        byok = None
        try:
            # the ticket from the sign-in, when the showcase asks for one; a visitor who has
            # not signed in is sent to the sign-in by the page
            visitor = visitors.check(llm.bearer(request)) if visitors.required else None
            if body.provider is not None:
                base_url, host, addresses = resolve_provider(
                    body.provider.base_url, settings.byok_hosts, manager.resolve
                )
                byok = Provider(
                    base_url,
                    body.provider.api_key.strip(),
                    body.provider.model.strip(),
                    host=host,
                    addresses=addresses,
                )
            sess = await manager.create(
                client_ip(request, settings.trust_proxy),
                byok,
                account=visitor.id if visitor else "",
                hint=visitor.hint if visitor else "",
                time_zone=body.time_zone,
            )
        except Refused as exc:
            return _refused(exc)
        visitors.started(visitor, sess, request.headers.get("user-agent", ""))
        return JSONResponse(sess.public(settings, manager.clock()), status_code=201)

    @app.get("/api/demo/admin")
    async def demo_admin(request: Request, account: str = "", days: int = 30) -> Response:
        """The operator's view of the visitors — who signed in from where and with what, the
        demos started and what each used — for the relay's admin page (``WEB_ADMIN_URL``
        there, this ``SHOWCASE_ADMIN_TOKEN`` here). Without a token the route is not there."""
        if not settings.admin_token:
            return JSONResponse({"error": "not_found"}, status_code=404)
        given = request.headers.get("x-admin-token", "")
        if not given or not secrets.compare_digest(given.encode(), settings.admin_token.encode()):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        out = visitors.admin(account.strip()[:80], max(1, min(days, 365)))
        if not account:
            out["active"] = [
                {
                    "id": s_.id,
                    "visitor": s_.account,
                    "hint": s_.hint,
                    "ip": s_.ip,
                    "started": s_.created_at,
                    "requests": s_.requests,
                    "tokens": s_.tokens,
                    "pictures": s_.pictures,
                    "clips": s_.clips,
                    "byok": s_.byok is not None,
                }
                for s_ in manager.sessions.values()
                if not s_.ended
            ]
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    @app.get("/api/demo/session/{sid}")
    async def show(sid: str, request: Request) -> Response:
        try:
            sess = manager.authenticate(sid, llm.bearer(request))
        except Refused as exc:
            return _refused(exc)
        return JSONResponse(sess.public(settings, manager.clock()))

    @app.delete("/api/demo/session/{sid}", status_code=204)
    async def stop(sid: str, request: Request) -> Response:
        try:
            sess = manager.authenticate(sid, llm.bearer(request))
        except Refused as exc:
            return _refused(exc)
        await manager.end(sess.id, reason="ended by the visitor")
        return Response(status_code=204)

    # ------------------------------------------------------------- trial credentials
    @app.post("/api/trial", status_code=201)
    async def trial_issue(body: TrialIn, request: Request) -> Response:
        try:
            trial, key = trials.issue(body.device, client_ip(request, settings.trust_proxy))
        except Refused as exc:
            return _refused(exc)
        return JSONResponse(trial.public(settings, key), status_code=201)

    @app.get("/api/trial/{tid}")
    async def trial_show(tid: str, request: Request) -> Response:
        try:
            trial = trials.authenticate(tid, llm.bearer(request))
        except Refused as exc:
            return _refused(exc)
        return JSONResponse(trial.public(settings))

    @app.api_route("/llm/trial/{tid}/{lane}/{path:path}", methods=["GET", "POST"])
    async def trial_model(tid: str, lane: str, path: str, request: Request) -> Response:
        try:
            trial = trials.authenticate(tid, llm.bearer(request))
        except Refused as exc:
            return llm.refusal(exc)
        return await llm.relay(
            request,
            http,
            path,
            lambda: trials.lane(trial, lane),
            lambda used: trials.record(trial, used),
        )

    # ------------------------------------------------------------- the containers' model calls
    @app.api_route("/llm/{sid}/{lane}/{path:path}", methods=["GET", "POST"])
    async def model(sid: str, lane: str, path: str, request: Request) -> Response:
        sess = manager.get(sid)
        if sess is None:
            return llm.refusal(Refused(404, "no_session", "this session has ended"))
        if is_image_path(path):
            return await pictures.handle(request, manager, sess, path)
        if is_clip_path(path):
            return await clips.handle(request, manager, sess, path)
        return await llm.forward(request, manager, http, sess, lane, path)

    # ------------------------------------------------------------- the site (development)
    if settings.cdn_dir:
        app.mount("/cdn", StaticFiles(directory=settings.cdn_dir), name="cdn")
    if settings.site_dir:
        app.mount("/", Spa(directory=settings.site_dir, html=True), name="site")

    return app


def build() -> FastAPI:
    """Everything wired from the environment — what ``uvicorn showcase_gateway.app:build``
    and ``python -m showcase_gateway`` run."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    settings = Settings.from_env()
    manager = SessionManager(settings, DockerRunner(settings))
    return create_app(settings, manager)
