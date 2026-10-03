/**
 * Connectors: third-party services the agent reaches over MCP (Streamable HTTP),
 * connected from Settings → Connectors the way a person connects a service in
 * Muse — one button, the browser, done — without pretending more than there is:
 *
 * - **OAuth** where the service's MCP server speaks the MCP authorization flow:
 *   the server's protected-resource metadata names its authorization server, we
 *   register nanoMuse there as a client (dynamic client registration, RFC 7591),
 *   send the person to the authorization page with PKCE, and take the code back
 *   on a loopback port of this host. Notion, Linear, GitHub, Slack, Stripe,
 *   Figma, Canva, Sentry, Vercel, Supabase … — the catalogue in
 *   connectors-catalogue.ts, checked against the live endpoints.
 * - **A key** where the server wants one (Apify, Heroku, 高德): the person pastes
 *   it; it goes out as the header or query parameter the vendor documents.
 * - **Nothing** where the server is open (Microsoft Learn, DeepWiki, Exa).
 * - **Any other** Streamable HTTP server by URL, and the MCP registry's listing
 *   searched from the page.
 *
 * Tokens and keys live in `$DSH_HOME/nanomuse/connectors.json` (mode 0600) and
 * nowhere else: the agent's MCP client (the preset row `dsh-nanomuse/connectors-tools`
 * mounts one `@deepseek-ai/dsh-mcp-client` per connection) talks to a loopback
 * proxy of this service, which adds the credential on the way out, refreshes an
 * expired token, filters the tools the person switched off, and answers for a
 * connection that needs signing in again. No credential ever enters the harness
 * configuration or a session.
 */
import { createHash, randomBytes, timingSafeEqual } from 'node:crypto'
import { chmod, mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import type { AddressInfo } from 'node:net'
import { join } from 'node:path'
import { Readable } from 'node:stream'
import { Service, type Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-host-webserver'
import { dshHome, json, message, sameOrigin, send } from './cloud.ts'
import { CATALOGUE, catalogueEntry, type CatalogueAuth } from './connectors-catalogue.ts'
import { RelayError } from './relay.ts'

export const API_PREFIX = '/nanomuse/connectors'
/** The loopback port tried first (so OAuth clients registered once keep their redirect URI); any free one otherwise. */
const PROXY_PORT = 38417
const FLOW_TTL_MS = 10 * 60_000
/** Refresh a token this long before it expires. */
const REFRESH_SKEW_MS = 60_000
const CLIENT_NAME = 'nanoMuse'
const CLIENT_URI = 'https://nanomuse.cn'
const PROTOCOL = '2025-06-18'
const REGISTRY = 'https://registry.modelcontextprotocol.io/v0/servers'
const SERVER_NAME = /^[A-Za-z0-9_-]{1,32}$/
const PROBE_TIMEOUT_MS = 15_000

export type Auth =
  | { kind: 'none' }
  | { kind: 'header'; name: string; value: string }
  | { kind: 'query'; name: string; value: string }
  | {
      kind: 'oauth'
      issuer: string
      tokenEndpoint: string
      clientId: string
      clientSecret?: string
      authMethod: 'none' | 'client_secret_post' | 'client_secret_basic'
      accessToken: string
      refreshToken?: string
      /** Epoch ms; absent when the server said nothing. */
      expiresAt?: number
      /** Seconds the server gave the token, so a short-lived one is not refreshed on every call. */
      expiresIn?: number
      scope?: string
      resource: string
    }

export interface Tool {
  name: string
  description: string
}

export interface Connection {
  id: string
  /** The catalogue id, or `custom`. */
  service: string
  label: string
  url: string
  /** The namespace of its tools: `mcp__<serverName>__<tool>`. */
  serverName: string
  auth: Auth
  connectedAt: number
  updatedAt: number
  /** Bumped when the agent side has to reconnect (credential, URL, tool switches). */
  version: number
  /** Tools switched off on the Connectors page; the agent never sees them. */
  disabled: string[]
  tools: Tool[]
  /** `ok`; `reauth` once a token could not be refreshed; `error` with the message otherwise. */
  state: 'ok' | 'reauth' | 'error'
  error: string
}

/** What the browser sees: no credential. */
export interface ConnectionView {
  id: string
  service: string
  label: string
  url: string
  serverName: string
  auth: Auth['kind']
  connectedAt: number
  updatedAt: number
  disabled: string[]
  tools: Tool[]
  state: Connection['state']
  error: string
}

interface Registration {
  clientId: string
  clientSecret?: string
  authMethod: 'none' | 'client_secret_post' | 'client_secret_basic'
  redirectUri: string
  at: number
  /** Epoch ms when the server said the registration lapses; absent for never or unsaid. */
  expiresAt?: number
}

interface Store {
  connections: Connection[]
  /** OAuth clients registered at an authorization server, by `issuer|redirectUri`. */
  registrations: Record<string, Registration>
}

interface AsMeta {
  issuer: string
  authorization_endpoint: string
  token_endpoint: string
  registration_endpoint?: string
  code_challenge_methods_supported?: string[]
  scopes_supported?: string[]
}

interface Flow {
  id: string
  state: string
  verifier: string
  /** The connection being (re)made. */
  base: Pick<Connection, 'id' | 'service' | 'label' | 'url' | 'serverName' | 'disabled'>
  as: AsMeta
  client: Registration
  resource: string
  scope: string | undefined
  redirectUri: string
  createdAt: number
  status: 'pending' | 'done' | 'failed'
  error: string
}

export interface FlowView {
  id: string
  status: Flow['status']
  error: string
  connectionId: string
  service: string
}

export interface ConnectorsView {
  connections: ConnectionView[]
  flows: FlowView[]
  /** The loopback proxy's port; 0 while it is not up. */
  proxy: number
}

/** A row from the MCP registry, the parts the page shows. */
export interface RegistryHit {
  name: string
  title: string
  description: string
  url: string
  website: string
}

/** The MCP client config one connection becomes on the agent's side. */
export interface ClientConfig {
  transport: 'streamable-http'
  serverName: string
  url: string
  headers: Record<string, string>
  toolCallTimeoutMs: number
  failOnStartupError: boolean
}

const EMPTY: Store = { connections: [], registrations: {} }

declare module '@deepseek-ai/cordis' {
  interface Context {
    nanomuseConnectors: NanomuseConnectors
  }
}

export default class NanomuseConnectors extends Service {
  private store: Store = structuredClone(EMPTY)
  private readonly flows = new Map<string, Flow>()
  private readonly listeners = new Set<() => void>()
  /** Single-flight token refreshes, by connection id. */
  private readonly refreshing = new Map<string, Promise<void>>()
  private readonly secret = randomBytes(24).toString('base64url')
  private server: Server | undefined
  private port = 0
  private writing: Promise<void> = Promise.resolve()
  private registryCache: { q: string; at: number; hits: RegistryHit[] } | undefined

  constructor(ctx: Context) {
    super(ctx, 'nanomuseConnectors')
  }

  async [Service.init](): Promise<void> {
    this.store = await this.read()
    await this.listen()
    this.ctx.inject(['webServer'], (ctx) => {
      ctx.effect(() => ctx.webServer.register({ kind: 'prefix', path: API_PREFIX, handler: this.handle }), 'nanomuse connectors: api')
    })
    this.ctx.effect(() => () => {
      this.server?.close()
      this.server = undefined
      this.port = 0
    }, 'nanomuse connectors: stop')
  }

  // ---- what the agent side mounts -------------------------------------------------------

  /** The connections an agent should have tools from right now. */
  live(): Connection[] {
    return this.store.connections.filter((c) => c.state !== 'error' && this.port > 0)
  }

  /** One connection as an `@deepseek-ai/dsh-mcp-client` row: the proxy's URL, this process's secret. */
  clientConfig(connection: Connection): ClientConfig {
    return {
      transport: 'streamable-http',
      serverName: connection.serverName,
      url: `http://127.0.0.1:${this.port}/c/${connection.id}/mcp`,
      headers: { 'x-nanomuse-proxy': this.secret },
      toolCallTimeoutMs: 120_000,
      failOnStartupError: false,
    }
  }

  onChange(listener: () => void): () => void {
    this.listeners.add(listener)
    return () => void this.listeners.delete(listener)
  }

  view(): ConnectorsView {
    return {
      connections: this.store.connections.map(publicView),
      flows: [...this.flows.values()].map((f) => ({ id: f.id, status: f.status, error: f.error, connectionId: f.base.id, service: f.base.service })),
      proxy: this.port,
    }
  }

  // ---- connecting ----------------------------------------------------------------------

  /**
   * Begin connecting a catalogue service or a custom URL. Answers with what the
   * page should do next: open the authorization URL, ask for a key, or show the
   * connection that is already there.
   */
  async connect(input: { service?: string; url?: string; label?: string; serverName?: string; key?: string; clientId?: string; clientSecret?: string; reconnect?: string; fresh?: boolean }): Promise<
    { kind: 'authorize'; url: string; flow: string } | { kind: 'key'; service: string; where: string } | { kind: 'connected'; id: string }
  > {
    const existing = input.reconnect ? this.store.connections.find((c) => c.id === input.reconnect) : undefined
    const entry = catalogueEntry(existing?.service ?? input.service ?? '')
    const url = existing?.url ?? entry?.url ?? String(input.url ?? '').trim()
    if (!/^https:\/\/[^\s/]+/.test(url) && !/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?/.test(url)) throw new RelayError(400, 'bad_url', 'The server address has to be an https URL')
    const label = existing?.label ?? entry?.name ?? (String(input.label ?? '').trim() || hostOf(url))
    // the tools are named mcp__<serverName>__<tool> in a chat: the catalogue id, else the label, else the host
    const serverName = existing?.serverName ?? this.uniqueServerName(entry?.id ?? input.serverName ?? slug(String(input.label ?? '').trim() || hostOf(url).replace(/:\d+$/, '')), existing?.id)
    const base = { id: existing?.id ?? randomBytes(6).toString('hex'), service: entry?.id ?? 'custom', label, url, serverName, disabled: existing?.disabled ?? [] }
    const wants: CatalogueAuth = entry?.auth ?? { kind: 'auto' }

    if (wants.kind === 'key' || (input.key && wants.kind === 'auto')) {
      const spec = wants.kind === 'key' ? wants : undefined
      if (!input.key) return { kind: 'key', service: base.service, where: spec?.where ?? '' }
      const header = spec?.header ?? 'Authorization'
      const prefix = spec?.prefix ?? (header === 'Authorization' ? 'Bearer ' : '')
      const auth: Auth = spec?.query ? { kind: 'query', name: spec.query, value: input.key } : { kind: 'header', name: header, value: `${prefix}${input.key}` }
      return { kind: 'connected', id: await this.finish(base, auth) }
    }
    if (wants.kind === 'none') return { kind: 'connected', id: await this.finish(base, { kind: 'none' }) }

    // OAuth, or find out
    const probe = await probeAuth(url)
    if (probe.kind === 'open') return { kind: 'connected', id: await this.finish(base, { kind: 'none' }) }
    if (probe.kind === 'key') return { kind: 'key', service: base.service, where: probe.hint }
    const as = probe.as
    const redirectUri = `http://127.0.0.1:${this.port}/oauth/callback`
    const regKey = `${as.issuer}|${redirectUri}`
    // a stored registration is reused — one "nanoMuse" in the person's list of authorized apps,
    // not one per sign-in — unless it has lapsed or the person asked to start over (`fresh`)
    const stored = this.store.registrations[regKey]
    if (stored && (input.fresh || (stored.expiresAt && stored.expiresAt < Date.now()))) delete this.store.registrations[regKey]
    let client = input.clientId ? { clientId: input.clientId, authMethod: input.clientSecret ? ('client_secret_post' as const) : ('none' as const), redirectUri, at: Date.now(), ...(input.clientSecret ? { clientSecret: input.clientSecret } : {}) } : this.store.registrations[regKey]
    if (!client) {
      if (!as.registration_endpoint) throw new RelayError(409, 'no_registration', 'This service does not register new clients by itself; it needs an OAuth client id from its developer settings')
      client = await register(as, redirectUri, probe.scope)
      this.store.registrations[regKey] = client
      await this.save()
    }
    const flow: Flow = {
      id: randomBytes(8).toString('hex'),
      state: randomBytes(16).toString('base64url'),
      verifier: randomBytes(32).toString('base64url'),
      base,
      as,
      client,
      resource: probe.resource,
      scope: probe.scope,
      redirectUri,
      createdAt: Date.now(),
      status: 'pending',
      error: '',
    }
    for (const [id, old] of this.flows) if (Date.now() - old.createdAt > FLOW_TTL_MS) this.flows.delete(id)
    this.flows.set(flow.id, flow)
    const authorize = new URL(as.authorization_endpoint)
    authorize.searchParams.set('response_type', 'code')
    authorize.searchParams.set('client_id', client.clientId)
    authorize.searchParams.set('redirect_uri', redirectUri)
    authorize.searchParams.set('code_challenge', createHash('sha256').update(flow.verifier).digest('base64url'))
    authorize.searchParams.set('code_challenge_method', 'S256')
    authorize.searchParams.set('state', flow.state)
    authorize.searchParams.set('resource', probe.resource)
    if (probe.scope) authorize.searchParams.set('scope', probe.scope)
    return { kind: 'authorize', url: authorize.toString(), flow: flow.id }
  }

  flow(id: string): FlowView | undefined {
    const f = this.flows.get(id)
    return f ? { id: f.id, status: f.status, error: f.error, connectionId: f.base.id, service: f.base.service } : undefined
  }

  async disconnect(id: string): Promise<void> {
    const before = this.store.connections.length
    this.store.connections = this.store.connections.filter((c) => c.id !== id)
    if (this.store.connections.length === before) throw new RelayError(404, 'not_found', 'No such connection')
    await this.save()
    this.changed()
  }

  async setTool(id: string, name: string, enabled: boolean): Promise<ConnectionView> {
    const c = this.must(id)
    const set = new Set(c.disabled)
    if (enabled) set.delete(name)
    else set.add(name)
    c.disabled = [...set].sort()
    c.version += 1
    c.updatedAt = Date.now()
    await this.save()
    this.changed()
    return publicView(c)
  }

  /** Ask the server for its tools again (and find out whether the credential still works). */
  async retry(id: string): Promise<ConnectionView> {
    const c = this.must(id)
    try {
      c.tools = await listTools(this.upstream(c), await this.authorization(c))
      c.state = 'ok'
      c.error = ''
    } catch (error) {
      if (error instanceof UpstreamUnauthorized && c.auth.kind === 'oauth') c.state = 'reauth'
      else c.state = 'error'
      c.error = message(error)
    }
    c.version += 1
    c.updatedAt = Date.now()
    await this.save()
    this.changed()
    return publicView(c)
  }

  /** Search the MCP registry for servers reachable over Streamable HTTP. */
  async registry(q: string): Promise<RegistryHit[]> {
    const query = q.trim().slice(0, 80)
    if (this.registryCache && this.registryCache.q === query && Date.now() - this.registryCache.at < 5 * 60_000) return this.registryCache.hits
    const url = new URL(REGISTRY)
    url.searchParams.set('limit', '50')
    url.searchParams.set('version', 'latest')
    if (query) url.searchParams.set('search', query)
    const res = await fetch(url, { headers: { accept: 'application/json' }, signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) })
    if (!res.ok) throw new RelayError(502, 'registry', `The registry answered ${res.status}`)
    const body = (await res.json()) as { servers?: { server?: { name?: string; title?: string; description?: string; websiteUrl?: string; remotes?: { type?: string; url?: string }[] } }[] }
    const hits: RegistryHit[] = []
    for (const row of body.servers ?? []) {
      const s = row.server
      const remote = s?.remotes?.find((r) => r.type === 'streamable-http' && typeof r.url === 'string' && /^https:\/\//.test(r.url) && !/\{[a-z_]+\}/i.test(r.url))
      if (!s?.name || !remote?.url) continue
      hits.push({ name: s.name, title: s.title ?? '', description: s.description ?? '', url: remote.url, website: s.websiteUrl ?? '' })
    }
    this.registryCache = { q: query, at: Date.now(), hits }
    return hits
  }

  // ---- the pieces ----------------------------------------------------------------------

  private must(id: string): Connection {
    const c = this.store.connections.find((x) => x.id === id)
    if (!c) throw new RelayError(404, 'not_found', 'No such connection')
    return c
  }

  private uniqueServerName(base: string, keepId?: string): string {
    let name = slug(base)
    if (name === 'nanomuse') name = 'nanomuse-2'
    const taken = new Set(this.store.connections.filter((c) => c.id !== keepId).map((c) => c.serverName))
    let candidate = name
    for (let i = 2; taken.has(candidate); i += 1) candidate = `${name.slice(0, 29)}-${i}`
    return candidate
  }

  /** Store a connection once its credential is in hand: list its tools, keep it, tell the agent side. */
  private async finish(base: Flow['base'], auth: Auth): Promise<string> {
    const now = Date.now()
    const existing = this.store.connections.find((c) => c.id === base.id)
    const c: Connection = existing ?? { ...base, auth, connectedAt: now, updatedAt: now, version: 0, tools: [], state: 'ok', error: '' }
    c.auth = auth
    c.label = base.label
    c.url = base.url
    c.serverName = base.serverName
    c.updatedAt = now
    c.version += 1
    try {
      c.tools = await listTools(this.upstream(c), await this.authorization(c))
      c.state = 'ok'
      c.error = ''
    } catch (error) {
      c.state = 'error'
      c.error = message(error)
    }
    if (!existing) this.store.connections.push(c)
    await this.save()
    this.changed()
    return c.id
  }

  /** The URL the credential-bearing request goes to (a key in the query string rides here). */
  private upstream(c: Connection): string {
    if (c.auth.kind !== 'query') return c.url
    const url = new URL(c.url)
    url.searchParams.set(c.auth.name, c.auth.value)
    return url.toString()
  }

  /** The headers that carry the credential, refreshing an OAuth token that is about to expire. */
  private async authorization(c: Connection): Promise<Record<string, string>> {
    if (c.auth.kind === 'header') return { [c.auth.name]: c.auth.value }
    if (c.auth.kind !== 'oauth') return {}
    const skew = Math.min(REFRESH_SKEW_MS, ((c.auth.expiresIn ?? 3600) * 1000) / 2)
    if (c.auth.expiresAt && c.auth.refreshToken && Date.now() > c.auth.expiresAt - skew) await this.refresh(c)
    return { authorization: `Bearer ${c.auth.accessToken}` }
  }

  private refresh(c: Connection): Promise<void> {
    const running = this.refreshing.get(c.id)
    if (running) return running
    const run = (async () => {
      if (c.auth.kind !== 'oauth' || !c.auth.refreshToken) return
      const form = new URLSearchParams({ grant_type: 'refresh_token', refresh_token: c.auth.refreshToken, client_id: c.auth.clientId, resource: c.auth.resource })
      if (c.auth.scope) form.set('scope', c.auth.scope)
      let tokens: TokenResponse
      try {
        tokens = await tokenRequest(c.auth.tokenEndpoint, form, c.auth)
      } catch (error) {
        // the server turning the grant down means a new sign-in; a network failure does not
        if (!(error instanceof RelayError && error.code === 'token_refused')) throw error
        c.state = 'reauth'
        c.error = message(error)
        c.updatedAt = Date.now()
        await this.save()
        this.changed()
        throw new UpstreamUnauthorized(c.error)
      }
      c.auth = {
        ...c.auth,
        accessToken: tokens.access_token,
        ...(tokens.refresh_token ? { refreshToken: tokens.refresh_token } : {}),
        ...(tokens.expires_in ? { expiresAt: Date.now() + tokens.expires_in * 1000, expiresIn: tokens.expires_in } : {}),
        ...(tokens.scope ? { scope: tokens.scope } : {}),
      }
      c.updatedAt = Date.now()
      await this.save()
    })().finally(() => this.refreshing.delete(c.id))
    this.refreshing.set(c.id, run)
    return run
  }

  private changed(): void {
    for (const listener of this.listeners) {
      try {
        listener()
      } catch (error) {
        this.warn('listener', error)
      }
    }
  }

  // ---- the loopback server: the OAuth callback and the proxy ------------------------------

  private async listen(): Promise<void> {
    const server = createServer((req, res) => void this.loopback(req, res).catch((error: unknown) => {
      this.warn('loopback', error)
      if (!res.headersSent) res.writeHead(500, { 'content-type': 'text/plain' })
      res.end('nanoMuse: ' + message(error))
    }))
    server.on('error', (error) => this.warn('server', error))
    const tryPort = (port: number) => new Promise<boolean>((resolve) => {
      const onError = () => { server.off('listening', onListening); resolve(false) }
      const onListening = () => { server.off('error', onError); resolve(true) }
      server.once('error', onError)
      server.once('listening', onListening)
      server.listen(port, '127.0.0.1')
    })
    if (!(await tryPort(PROXY_PORT)) && !(await tryPort(0))) throw new Error('nanomuse connectors: no loopback port')
    this.server = server
    this.port = (server.address() as AddressInfo).port
  }

  private async loopback(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', `http://127.0.0.1:${this.port}`)
    if (url.pathname === '/oauth/callback') return this.callback(url, res)
    const proxied = /^\/c\/([a-f0-9]{12})\/mcp$/.exec(url.pathname)
    if (proxied) return this.proxy(proxied[1]!, req, res)
    res.writeHead(404, { 'content-type': 'text/plain' }).end('nanoMuse')
  }

  private async callback(url: URL, res: ServerResponse): Promise<void> {
    const state = url.searchParams.get('state') ?? ''
    const flow = [...this.flows.values()].find((f) => f.state === state && f.status === 'pending')
    const zh = (this.ctx.get('nanomuseRooms') as { lang?: string } | undefined)?.lang?.startsWith('zh') ?? true
    if (!flow || Date.now() - flow.createdAt > FLOW_TTL_MS) {
      return page(res, 400, zh ? '这次授权已经过期' : 'This authorization has expired', zh ? '回到 nanoMuse，再点一次「连接」。' : 'Go back to nanoMuse and press Connect again.')
    }
    const error = url.searchParams.get('error')
    if (error) {
      flow.status = 'failed'
      flow.error = `${error}: ${url.searchParams.get('error_description') ?? ''}`.trim()
      this.changed()
      return page(res, 400, zh ? '没有授权' : 'Not authorized', flow.error)
    }
    const code = url.searchParams.get('code') ?? ''
    try {
      const form = new URLSearchParams({ grant_type: 'authorization_code', code, redirect_uri: flow.redirectUri, client_id: flow.client.clientId, code_verifier: flow.verifier, resource: flow.resource })
      const tokens = await tokenRequest(flow.as.token_endpoint, form, flow.client)
      const auth: Auth = {
        kind: 'oauth',
        issuer: flow.as.issuer,
        tokenEndpoint: flow.as.token_endpoint,
        clientId: flow.client.clientId,
        ...(flow.client.clientSecret ? { clientSecret: flow.client.clientSecret } : {}),
        authMethod: flow.client.authMethod,
        accessToken: tokens.access_token,
        ...(tokens.refresh_token ? { refreshToken: tokens.refresh_token } : {}),
        ...(tokens.expires_in ? { expiresAt: Date.now() + tokens.expires_in * 1000, expiresIn: tokens.expires_in } : {}),
        ...(tokens.scope ?? flow.scope ? { scope: tokens.scope ?? flow.scope! } : {}),
        resource: flow.resource,
      }
      await this.finish(flow.base, auth)
      flow.status = 'done'
      this.changed()
      return page(res, 200, zh ? `${flow.base.label} 已连接` : `${flow.base.label} is connected`, zh ? '可以关掉这一页，回到 nanoMuse 了。' : 'You can close this page and go back to nanoMuse.')
    } catch (error) {
      flow.status = 'failed'
      flow.error = message(error)
      if (/invalid_client/.test(flow.error)) {
        // the authorization server no longer knows the client it registered for us; the next attempt registers again
        delete this.store.registrations[`${flow.as.issuer}|${flow.redirectUri}`]
        await this.save()
      }
      this.changed()
      return page(res, 502, zh ? '没有连上' : 'Could not connect', flow.error)
    }
  }

  /** One MCP request on to the service, with the credential; `tools/list` and `tools/call` see the switches. */
  private async proxy(id: string, req: IncomingMessage, res: ServerResponse): Promise<void> {
    const given = String(req.headers['x-nanomuse-proxy'] ?? '')
    if (given.length !== this.secret.length || !timingSafeEqual(Buffer.from(given), Buffer.from(this.secret))) {
      res.writeHead(403, { 'content-type': 'text/plain' }).end('nanoMuse: not for you')
      return
    }
    const c = this.store.connections.find((x) => x.id === id)
    if (!c) {
      res.writeHead(404, { 'content-type': 'text/plain' }).end('nanoMuse: no such connection')
      return
    }
    const method = req.method ?? 'GET'
    let body: Buffer | undefined
    let rpc: { id?: unknown; method?: string; params?: { name?: string } } | undefined
    if (method === 'POST') {
      const chunks: Buffer[] = []
      for await (const chunk of req) chunks.push(chunk as Buffer)
      body = Buffer.concat(chunks)
      try {
        const parsed: unknown = JSON.parse(body.toString('utf8'))
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) rpc = parsed as typeof rpc
      } catch {
        // not JSON-RPC we understand; passed through as is
      }
    }
    if (rpc?.method === 'tools/call' && rpc.params?.name && c.disabled.includes(rpc.params.name)) {
      res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ jsonrpc: '2.0', id: rpc.id ?? null, result: { content: [{ type: 'text', text: `The tool "${rpc.params.name}" is switched off in nanoMuse's connector settings for ${c.label}.` }], isError: true } }))
      return
    }
    // read through a call: the refresh below may change it after the narrowing above
    const stateNow = (): Connection['state'] => c.state
    if (stateNow() === 'reauth') {
      res.writeHead(503, { 'content-type': 'application/json' }).end(JSON.stringify({ error: `${c.label} needs signing in again (Settings → Connectors)` }))
      return
    }
    const forward = async (retry: boolean): Promise<Response> => {
      const headers: Record<string, string> = {}
      for (const name of ['content-type', 'accept', 'mcp-session-id', 'mcp-protocol-version', 'last-event-id']) {
        const value = req.headers[name]
        if (typeof value === 'string') headers[name] = value
      }
      Object.assign(headers, await this.authorization(c))
      // a GET is the server's notification stream and may stay open; a POST is one call, two minutes at most
      const upstream = await fetch(this.upstream(c), { method, headers, ...(body ? { body: new Uint8Array(body) } : {}), redirect: 'manual', ...(method === 'GET' ? {} : { signal: AbortSignal.timeout(130_000) }) })
      if (upstream.status === 401 && c.auth.kind === 'oauth' && !retry && c.auth.refreshToken) {
        await this.refresh(c).catch(() => undefined)
        if (stateNow() !== 'reauth') return forward(true)
      }
      return upstream
    }
    let upstream: Response
    try {
      upstream = await forward(false)
    } catch (error) {
      res.writeHead(502, { 'content-type': 'application/json' }).end(JSON.stringify({ error: message(error) }))
      return
    }
    if (upstream.status === 401 && c.auth.kind === 'oauth' && stateNow() !== 'reauth') {
      c.state = 'reauth'
      c.error = 'The service no longer accepts the token'
      c.updatedAt = Date.now()
      await this.save()
      this.changed()
    }
    const out: Record<string, string> = { 'cache-control': 'no-store' }
    for (const name of ['content-type', 'mcp-session-id', 'mcp-protocol-version']) {
      const value = upstream.headers.get(name)
      if (value) out[name] = value
    }
    if (rpc?.method === 'tools/list' && c.disabled.length && upstream.ok) {
      const text = await upstream.text()
      const filtered = filterToolsList(text, upstream.headers.get('content-type') ?? '', new Set(c.disabled))
      res.writeHead(upstream.status, out).end(filtered)
      return
    }
    res.writeHead(upstream.status, out)
    if (!upstream.body) {
      res.end()
      return
    }
    const stream = Readable.fromWeb(upstream.body as import('node:stream/web').ReadableStream)
    stream.on('error', () => res.destroy())
    res.on('close', () => stream.destroy())
    stream.pipe(res)
  }

  // ---- the web routes --------------------------------------------------------------------

  private readonly handle = async (req: IncomingMessage, res: ServerResponse): Promise<void> => {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1')
    const route = url.pathname.slice(API_PREFIX.length) || '/'
    if (!sameOrigin(req)) return send(res, 403, { error: { code: 'forbidden', message: 'Same-origin requests only' } })
    try {
      if (req.method === 'GET' && route === '/state') return send(res, 200, this.view())
      if (req.method === 'GET' && route === '/flow') {
        const flow = this.flow(url.searchParams.get('id') ?? '')
        return flow ? send(res, 200, flow) : send(res, 404, { error: { code: 'not_found', message: 'No such flow' } })
      }
      if (req.method === 'GET' && route === '/registry') return send(res, 200, { hits: await this.registry(url.searchParams.get('q') ?? '') })
      if (req.method === 'GET' && route === '/catalogue') return send(res, 200, { entries: CATALOGUE })
      if (req.method !== 'POST') return send(res, 404, { error: { code: 'not_found', message: `No ${req.method ?? ''} ${route}` } })
      const body = await json(req)
      switch (route) {
        case '/connect':
          return send(res, 200, await this.connect({
            ...(typeof body.service === 'string' ? { service: body.service } : {}),
            ...(typeof body.url === 'string' ? { url: body.url } : {}),
            ...(typeof body.label === 'string' ? { label: body.label } : {}),
            ...(typeof body.serverName === 'string' ? { serverName: body.serverName } : {}),
            ...(typeof body.key === 'string' && body.key.trim() ? { key: body.key.trim() } : {}),
            ...(typeof body.clientId === 'string' && body.clientId.trim() ? { clientId: body.clientId.trim() } : {}),
            ...(typeof body.clientSecret === 'string' && body.clientSecret.trim() ? { clientSecret: body.clientSecret.trim() } : {}),
            ...(typeof body.reconnect === 'string' ? { reconnect: body.reconnect } : {}),
            ...(body.fresh === true ? { fresh: true } : {}),
          }))
        case '/disconnect':
          await this.disconnect(String(body.id ?? ''))
          return send(res, 204)
        case '/tool':
          return send(res, 200, await this.setTool(String(body.id ?? ''), String(body.name ?? ''), body.enabled !== false))
        case '/retry':
          return send(res, 200, await this.retry(String(body.id ?? '')))
        default:
          return send(res, 404, { error: { code: 'not_found', message: `No POST ${route}` } })
      }
    } catch (error) {
      if (error instanceof RelayError) return send(res, error.status, { error: { code: error.code, message: error.message } })
      this.warn(route, error)
      return send(res, 500, { error: { code: 'internal', message: message(error) } })
    }
  }

  // ---- the file ---------------------------------------------------------------------------

  private get file(): string {
    return join(dshHome(), 'nanomuse', 'connectors.json')
  }

  private async read(): Promise<Store> {
    try {
      const parsed = JSON.parse(await readFile(this.file, 'utf8')) as Partial<Store>
      return { connections: Array.isArray(parsed.connections) ? parsed.connections : [], registrations: parsed.registrations && typeof parsed.registrations === 'object' ? parsed.registrations : {} }
    } catch {
      return structuredClone(EMPTY)
    }
  }

  private save(): Promise<void> {
    this.writing = this.writing.then(async () => {
      await mkdir(join(dshHome(), 'nanomuse'), { recursive: true })
      const tmp = `${this.file}.${process.pid}.tmp`
      await writeFile(tmp, JSON.stringify(this.store, null, 2), { mode: 0o600 })
      await rename(tmp, this.file)
      await chmod(this.file, 0o600).catch(() => undefined)
    })
    return this.writing
  }

  private warn(what: string, error: unknown): void {
    this.ctx.logger.warn('nanomuse connectors: %s failed: %s', what, message(error))
  }
}

// ---- OAuth: discovery, registration, tokens -------------------------------------------------

class UpstreamUnauthorized extends Error {}

interface TokenResponse {
  access_token: string
  token_type?: string
  expires_in?: number
  refresh_token?: string
  scope?: string
}

type Probe = { kind: 'open' } | { kind: 'key'; hint: string } | { kind: 'oauth'; as: AsMeta; resource: string; scope: string | undefined }

const INITIALIZE = JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: PROTOCOL, capabilities: {}, clientInfo: { name: CLIENT_NAME, version: '0.1' } } })

/** What the server wants: nothing, a key, or the MCP authorization flow (and where its authorization server is). */
async function probeAuth(url: string): Promise<Probe> {
  const res = await fetch(url, { method: 'POST', headers: mcpHeaders(), body: INITIALIZE, redirect: 'manual', signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) })
  await res.body?.cancel().catch(() => undefined)
  if (res.ok) return { kind: 'open' }
  if (res.status !== 401) throw new RelayError(502, 'probe', `The server answered ${res.status} to initialize`)
  const challenge = parseChallenge(res.headers.get('www-authenticate') ?? '')
  const target = new URL(url)
  const candidates = [challenge.resource_metadata, challenge.resource_metadata_uri, `${target.origin}/.well-known/oauth-protected-resource${target.pathname === '/' ? '' : target.pathname.replace(/\/$/, '')}`, `${target.origin}/.well-known/oauth-protected-resource`].filter((u): u is string => Boolean(u))
  let prm: { resource?: string; authorization_servers?: string[]; scopes_supported?: string[] } | undefined
  for (const candidate of candidates) {
    prm = await getJson<typeof prm>(candidate).catch(() => undefined)
    if (prm?.authorization_servers?.length) break
    prm = undefined
  }
  const asBase = prm?.authorization_servers?.[0] ?? target.origin
  const as = await asMetadata(asBase)
  if (!as) return { kind: 'key', hint: challenge.error_description ?? '' }
  const scope = challenge.scope ?? (prm?.scopes_supported?.length ? prm.scopes_supported.join(' ') : undefined)
  return { kind: 'oauth', as, resource: prm?.resource ?? url, scope }
}

/** The authorization server's metadata, by the well-known paths RFC 8414 and OpenID give it. */
async function asMetadata(base: string): Promise<AsMeta | undefined> {
  const u = new URL(base)
  const path = u.pathname === '/' ? '' : u.pathname.replace(/\/$/, '')
  const candidates = [`${u.origin}/.well-known/oauth-authorization-server${path}`, `${u.origin}/.well-known/openid-configuration${path}`, ...(path ? [`${u.origin}${path}/.well-known/openid-configuration`, `${u.origin}${path}/.well-known/oauth-authorization-server`] : [])]
  for (const candidate of candidates) {
    const meta = await getJson<Partial<AsMeta>>(candidate).catch(() => undefined)
    if (meta?.authorization_endpoint && meta.token_endpoint) {
      return { ...meta, issuer: meta.issuer ?? u.origin, authorization_endpoint: meta.authorization_endpoint, token_endpoint: meta.token_endpoint }
    }
  }
  return undefined
}

/** Register nanoMuse at the authorization server (RFC 7591); a public client first, whatever it answers otherwise. */
async function register(as: AsMeta, redirectUri: string, scope: string | undefined): Promise<Registration> {
  const body: Record<string, unknown> = {
    client_name: CLIENT_NAME,
    client_uri: CLIENT_URI,
    redirect_uris: [redirectUri],
    grant_types: ['authorization_code', 'refresh_token'],
    response_types: ['code'],
    token_endpoint_auth_method: 'none',
    ...(scope ? { scope } : {}),
  }
  let res = await fetch(as.registration_endpoint!, { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) })
  if (!res.ok) {
    // some servers insist on a confidential client
    delete body.token_endpoint_auth_method
    res = await fetch(as.registration_endpoint!, { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) })
  }
  const text = await res.text()
  if (!res.ok) throw new RelayError(502, 'registration', `The authorization server refused to register nanoMuse (${res.status}): ${text.slice(0, 200)}`)
  const reg = JSON.parse(text) as { client_id?: string; client_secret?: string; token_endpoint_auth_method?: string; client_secret_expires_at?: number; client_id_expires_at?: number }
  if (!reg.client_id) throw new RelayError(502, 'registration', 'The authorization server returned no client id')
  const method = reg.token_endpoint_auth_method === 'client_secret_basic' ? 'client_secret_basic' : reg.client_secret ? 'client_secret_post' : 'none'
  // RFC 7591: seconds since the epoch, 0 for never
  const lapse = [reg.client_secret_expires_at, reg.client_id_expires_at].filter((v): v is number => typeof v === 'number' && v > 0)
  return { clientId: reg.client_id, ...(reg.client_secret ? { clientSecret: reg.client_secret } : {}), authMethod: method, redirectUri, at: Date.now(), ...(lapse.length ? { expiresAt: Math.min(...lapse) * 1000 } : {}) }
}

async function tokenRequest(endpoint: string, form: URLSearchParams, client: { clientId: string; clientSecret?: string; authMethod: Registration['authMethod'] }): Promise<TokenResponse> {
  const headers: Record<string, string> = { 'content-type': 'application/x-www-form-urlencoded', accept: 'application/json' }
  if (client.clientSecret && client.authMethod === 'client_secret_basic') {
    headers.authorization = `Basic ${Buffer.from(`${encodeURIComponent(client.clientId)}:${encodeURIComponent(client.clientSecret)}`).toString('base64')}`
  } else if (client.clientSecret) {
    form.set('client_secret', client.clientSecret)
  }
  const res = await fetch(endpoint, { method: 'POST', headers, body: form.toString(), signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) })
  const text = await res.text()
  // 400/401 is the server refusing the grant or the client (invalid_grant, invalid_client); anything else is its trouble
  if (!res.ok) throw new RelayError(502, res.status === 400 || res.status === 401 ? 'token_refused' : 'token', `The token endpoint answered ${res.status}: ${text.slice(0, 200)}`)
  const tokens = JSON.parse(text) as TokenResponse
  if (!tokens.access_token) throw new RelayError(502, 'token', 'The token endpoint returned no access token')
  return tokens
}

/** `Bearer realm="x", resource_metadata="…", scope="a b"` → its parameters. */
function parseChallenge(header: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const match of header.matchAll(/([a-z_]+)="([^"]*)"/gi)) out[match[1]!.toLowerCase()] = match[2]!
  return out
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { accept: 'application/json' }, signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) })
  if (!res.ok) throw new Error(`${res.status}`)
  return (await res.json()) as T
}

function mcpHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return { 'content-type': 'application/json', accept: 'application/json, text/event-stream', 'mcp-protocol-version': PROTOCOL, ...extra }
}

// ---- a minimal MCP client, for the host's own look at a server --------------------------------

/** One JSON-RPC response out of a Streamable HTTP answer, JSON or SSE. */
function firstMessage(text: string, contentType: string): { result?: unknown; error?: { message?: string } } | undefined {
  if (contentType.includes('text/event-stream')) {
    for (const block of text.split(/\n\n/)) {
      const data = block.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim()).join('\n')
      if (!data) continue
      try {
        const parsed = JSON.parse(data) as { id?: unknown; result?: unknown; error?: { message?: string } }
        if (parsed.id !== undefined) return parsed
      } catch {
        // a keep-alive or a notification
      }
    }
    return undefined
  }
  try {
    return JSON.parse(text) as { result?: unknown; error?: { message?: string } }
  } catch {
    return undefined
  }
}

/** `initialize`, `notifications/initialized`, `tools/list` — the tools, or why not. */
async function listTools(url: string, auth: Record<string, string>): Promise<Tool[]> {
  const first = await fetch(url, { method: 'POST', headers: mcpHeaders(auth), body: INITIALIZE, redirect: 'manual', signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) })
  if (first.status === 401 || first.status === 403) {
    await first.body?.cancel().catch(() => undefined)
    throw new UpstreamUnauthorized(`The service did not accept the credential (${first.status})`)
  }
  const initText = await first.text()
  if (!first.ok) throw new Error(`initialize answered ${first.status}: ${initText.slice(0, 200)}`)
  const init = firstMessage(initText, first.headers.get('content-type') ?? '')
  if (init?.error) throw new Error(`initialize failed: ${init.error.message ?? 'unknown error'}`)
  const session = first.headers.get('mcp-session-id')
  const sessionHeaders = session ? { 'mcp-session-id': session } : {}
  await fetch(url, { method: 'POST', headers: mcpHeaders({ ...auth, ...sessionHeaders }), body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }), redirect: 'manual', signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) }).then((r) => r.body?.cancel()).catch(() => undefined)
  // every page: a server with many tools hands them out a cursor at a time
  const tools: { name?: string; description?: string }[] = []
  let cursor: string | undefined
  for (let page = 0, id = 2; page < 20; page++, id++) {
    const list = await fetch(url, { method: 'POST', headers: mcpHeaders({ ...auth, ...sessionHeaders }), body: JSON.stringify({ jsonrpc: '2.0', id, method: 'tools/list', params: cursor ? { cursor } : {} }), redirect: 'manual', signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) })
    const listText = await list.text()
    if (!list.ok) throw new Error(`tools/list answered ${list.status}: ${listText.slice(0, 200)}`)
    const parsed = firstMessage(listText, list.headers.get('content-type') ?? '')
    if (parsed?.error) throw new Error(`tools/list failed: ${parsed.error.message ?? 'unknown error'}`)
    const result = parsed?.result as { tools?: { name?: string; description?: string }[]; nextCursor?: string } | undefined
    tools.push(...(result?.tools ?? []))
    cursor = typeof result?.nextCursor === 'string' && result.nextCursor ? result.nextCursor : undefined
    if (!cursor) break
  }
  if (session) void fetch(url, { method: 'DELETE', headers: mcpHeaders({ ...auth, ...sessionHeaders }), signal: AbortSignal.timeout(5000) }).then((r) => r.body?.cancel()).catch(() => undefined)
  return tools.filter((t): t is { name: string; description?: string } => typeof t.name === 'string').map((t) => ({ name: t.name, description: (t.description ?? '').slice(0, 400) }))
}

/** A `tools/list` answer without the switched-off tools, in whichever framing it came. */
function filterToolsList(text: string, contentType: string, disabled: Set<string>): string {
  const strip = (data: string): string => {
    try {
      const parsed = JSON.parse(data) as { result?: { tools?: { name?: string }[] } }
      if (parsed?.result?.tools) {
        parsed.result.tools = parsed.result.tools.filter((t) => !t.name || !disabled.has(t.name))
        return JSON.stringify(parsed)
      }
    } catch {
      // leave it
    }
    return data
  }
  if (!contentType.includes('text/event-stream')) return strip(text)
  return text.split('\n').map((line) => (line.startsWith('data:') ? `data: ${strip(line.slice(5).trim())}` : line)).join('\n')
}

// ---- small things ---------------------------------------------------------------------------------

function publicView(c: Connection): ConnectionView {
  return { id: c.id, service: c.service, label: c.label, url: c.url, serverName: c.serverName, auth: c.auth.kind, connectedAt: c.connectedAt, updatedAt: c.updatedAt, disabled: c.disabled, tools: c.tools, state: c.state, error: c.error }
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return 'server'
  }
}

/** A tool namespace out of a name: `mcp.notion.com` → `mcp-notion-com`. */
function slug(text: string): string {
  const s = text.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 32)
  return SERVER_NAME.test(s) ? s : 'server'
}

function page(res: ServerResponse, status: number, title: string, text: string): void {
  const esc = (s: string) => s.replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch]!)
  res.writeHead(status, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' }).end(
    `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>${esc(title)} · nanoMuse</title>` +
      `<style>body{font:16px/1.5 -apple-system,system-ui,sans-serif;color:#1d1d1f;background:#f5f4f0;display:grid;place-items:center;min-height:100vh;margin:0}main{background:#fff;border-radius:16px;padding:32px 36px;max-width:420px;box-shadow:0 8px 30px rgba(0,0,0,.06)}h1{font-size:20px;margin:0 0 8px}p{margin:0;color:#555}</style>` +
      `<main><h1>${esc(title)}</h1><p>${esc(text)}</p></main><script>setTimeout(function(){try{window.close()}catch(e){}},1500)</script>`,
  )
}

// for the tests: the pieces that talk to a server, without the service around them
export { filterToolsList, listTools, parseChallenge, probeAuth, slug }
