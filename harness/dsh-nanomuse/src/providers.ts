/**
 * Own-key providers with capabilities (contract C11), the desktop's half.
 *
 * **One catalogue.** `nanomuse/llm/providers.json` is the source of truth; `scripts/providers-json.mjs`
 * copies it to `assets/providers.json` here (and to the phones). Each entry says what a provider
 * is (name, protocol, base URL, where the key is handed out), how one gets in (`key`, an OAuth
 * flow, a device code, nothing for a local server), where it works (`cn`, `global`) and what its
 * models can do — `chat`, `vision` (the hands see the screen), `image` (pictures), `video` (clips).
 *
 * **One rule.** What the person has configured — the own-key rows this plugin wrote into the
 * harness's model adapter, the ChatGPT sign-in, nanoMuse Cloud while the allowance lasts — decides
 * what the app offers: chat needs `chat`, the hands need `vision`, pictures `image`, clips `video`.
 * A capability nobody has is unavailable with one sentence (the browser half's words), never a raw
 * error; a model picker lists only the models of providers that have the capability.
 *
 * **The ChatGPT sign-in.** The runtime owns the flow (`nanomuse chatgpt login|status|logout|proxy`,
 * `~/.nm-dev/runtime-team/CONTRACT-chatgpt.md`): PKCE against OpenAI as the Codex CLI does it, a
 * token store of its own, and a loopback OpenAI-compatible server that translates chat completions
 * to the Codex Responses API. This module runs those commands: `login --json` prints the URL to
 * open and then `done`; `proxy --json` prints `ready` with the loopback URL and a token, and is kept
 * running as a managed child (restarted when it exits) so the harness talks to it as a provider row
 * (`chatgpt`, chat + vision — the Codex backend has no image or video endpoint).
 */
import { spawn as nodeSpawn, type ChildProcess } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { CAPABILITIES, type Auth, type Capability, type Protocol, type ProviderEntry, type Region } from './catalogue.ts'

// The shapes and the pure rules (the groups, the region, the gate) live in `catalogue.ts`, which the browser half imports too.
export * from './catalogue.ts'

/** The provider row id the ChatGPT sign-in writes. */
export const CHATGPT_PROVIDER = 'chatgpt'
/** The credential the `chatgpt` row names (the proxy's loopback token). */
export const CHATGPT_KEY_REF = 'NANOMUSE_KEY_CHATGPT'

/** The catalogue as read from `providers.json`: malformed rows dropped, fields defaulted. */
export function parseCatalogue(raw: unknown): ProviderEntry[] {
  const list = Array.isArray(raw) ? raw : raw && typeof raw === 'object' && Array.isArray((raw as { providers?: unknown }).providers) ? (raw as { providers: unknown[] }).providers : []
  const out: ProviderEntry[] = []
  for (const item of list) {
    if (!item || typeof item !== 'object') continue
    const r = item as Record<string, unknown>
    const id = typeof r.id === 'string' ? r.id.trim() : ''
    if (!id || !/^[a-z0-9][a-z0-9-]*$/.test(id)) continue
    const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])
    const protocol = (['openai', 'openai-responses', 'anthropic', 'gemini'] as const).find((p) => p === r.protocol) ?? 'openai'
    const defaults: ProviderEntry['defaults'] = {}
    if (r.defaults && typeof r.defaults === 'object') {
      for (const k of ['chat', 'hands', 'image', 'video'] as const) {
        const v = (r.defaults as Record<string, unknown>)[k]
        if (typeof v === 'string' && v) defaults[k] = v
      }
    }
    const isAuth = (a: string): a is Auth => ['key', 'oauth-chatgpt', 'oauth-claude', 'oauth-openrouter', 'device-kimi', 'none'].includes(a)
    const isCap = (x: string): x is Capability => (CAPABILITIES as readonly string[]).includes(x)
    const authCapabilities: ProviderEntry['auth_capabilities'] = {}
    if (r.auth_capabilities && typeof r.auth_capabilities === 'object') {
      for (const [a, caps] of Object.entries(r.auth_capabilities as Record<string, unknown>)) {
        if (isAuth(a)) authCapabilities[a] = strings(caps).filter(isCap)
      }
    }
    const url = (v: unknown): string => (typeof v === 'string' ? v.replace(/\/+$/, '') : '')
    const entry: ProviderEntry = {
      id,
      name: typeof r.name === 'string' && r.name ? r.name : id,
      name_zh: typeof r.name_zh === 'string' && r.name_zh ? r.name_zh : typeof r.name === 'string' && r.name ? r.name : id,
      protocol,
      base_url: url(r.base_url),
      key_url: typeof r.key_url === 'string' ? r.key_url : '',
      key_hint: typeof r.key_hint === 'string' ? r.key_hint : '',
      auth: strings(r.auth).filter(isAuth),
      auth_capabilities: authCapabilities,
      regions: strings(r.regions).filter((x): x is Region => x === 'cn' || x === 'global'),
      capabilities: strings(r.capabilities).filter(isCap),
      user_capabilities: r.user_capabilities === true,
      defaults,
      note: typeof r.note === 'string' ? r.note : '',
      note_zh: typeof r.note_zh === 'string' ? r.note_zh : '',
      verified: typeof r.verified === 'string' ? r.verified : '',
    }
    if (url(r.base_url_global)) entry.base_url_global = url(r.base_url_global)
    if (typeof r.key_url_global === 'string' && r.key_url_global) entry.key_url_global = r.key_url_global
    out.push(entry)
  }
  return out
}

/**
 * `assets/providers.json` of the package — next to `lib/` or `src/`; the bundle may put this
 * module in `lib/chunks/`, so the parent is tried too. An empty catalogue when it is not there.
 */
export async function loadCatalogue(path?: string | URL): Promise<ProviderEntry[]> {
  const candidates = path ? [path] : [new URL('../assets/providers.json', import.meta.url), new URL('../../assets/providers.json', import.meta.url)]
  for (const candidate of candidates) {
    try {
      return parseCatalogue(JSON.parse(await readFile(candidate, 'utf8')))
    } catch {
      // the next place
    }
  }
  return []
}

// ---- what is configured, and what it can do --------------------------------------------------

/** An own-key provider this plugin wrote into the harness's model adapter (`llm-pi-ai`), as kept in `cloud.json`. */
export interface OwnProvider {
  /** The catalogue entry it came from (`custom` for a hand-made endpoint, `chatgpt` for the sign-in). */
  provider: string
  label: string
  protocol: Protocol
  baseURL: string
  /** The credential the row names; empty for a server that wants no key. */
  keyRef: string
  capabilities: Capability[]
  /** The models the endpoint listed (or the catalogue's defaults), as the pickers show them. */
  models: OwnModel[]
  at: number
}

export interface OwnModel {
  id: string
  name: string
  /** Takes pictures: the hands may see the screen with it. */
  vision: boolean
  kind: 'chat' | 'image' | 'video'
}

/**
 * The model adapter's `api` for a catalogue protocol (pi-ai's names). Gemini's catalogue row points
 * at Google's OpenAI-compatible layer (`…/v1beta/openai`), which is spoken as OpenAI; the native
 * API only when the base URL is the native one.
 */
export function apiOf(protocol: Protocol, baseURL = ''): string {
  switch (protocol) {
    case 'anthropic': return 'anthropic-messages'
    case 'gemini': return /\/openai\/?$/.test(baseURL) ? 'openai-completions' : 'google-generative-ai'
    case 'openai-responses': return 'openai-responses'
    default: return 'openai-completions'
  }
}

/** Ids that name a sighted model, as far as a name says (the endpoint's list carries no modalities). */
const SIGHTED = /vl|vision|ocr|4o|gpt-5|\bo[34]\b|claude|gemini|grok|kimi|glm-4(\.\d)?v|pixtral|llama-?4|qwen3|minimax|mistral-medium|magistral|step-3|doubao-seed|ark/i

/** Whether a chat model of a provider with `vision` takes pictures, by its id (the catalogue's `hands` default always does). */
export function sighted(entry: Pick<ProviderEntry, 'capabilities' | 'defaults'>, modelId: string): boolean {
  if (!entry.capabilities.includes('vision')) return false
  if (entry.defaults.hands && entry.defaults.hands === modelId) return true
  return SIGHTED.test(modelId)
}

/** Ids that name an image or a video model rather than a chat one. */
const IMAGE_ID = /image|dall-e|imagen|flux|wanx|wan2?\.\d-t2i|qwen-image|cogview|seedream|stable-diffusion|sdxl|kolors|hunyuan-image/i
const VIDEO_ID = /video|wan2?\.\d-(i2v|t2v|kf2v)|veo|sora|cogvideo|seedance|hunyuan-video|kling/i

/** The kind a listed model id stands for. */
export function kindOf(modelId: string): OwnModel['kind'] {
  if (VIDEO_ID.test(modelId)) return 'video'
  if (IMAGE_ID.test(modelId)) return 'image'
  return 'chat'
}

/** The models of an entry as the pickers show them: the endpoint's list when it answered, else the catalogue's defaults. */
export function modelsOf(entry: ProviderEntry, listed: string[]): OwnModel[] {
  const ids = listed.length ? listed : Object.values(entry.defaults).filter((id): id is string => Boolean(id))
  const seen = new Set<string>()
  const out: OwnModel[] = []
  for (const id of ids) {
    if (!id || seen.has(id)) continue
    seen.add(id)
    let kind = kindOf(id)
    if (id === entry.defaults.image) kind = 'image'
    if (id === entry.defaults.video) kind = 'video'
    if (kind === 'image' && !entry.capabilities.includes('image')) continue
    if (kind === 'video' && !entry.capabilities.includes('video')) continue
    out.push({ id, name: id, vision: kind === 'chat' && sighted(entry, id), kind })
  }
  return out
}

/** The provider row for the harness's model adapter: the base URL, the credential by name, the chat models (never a key). */
export function ownProviderRow(p: OwnProvider): Record<string, unknown> {
  return {
    displayName: p.label,
    api: apiOf(p.protocol, p.baseURL),
    baseURL: p.baseURL,
    ...(p.keyRef ? { apiKeyEnv: p.keyRef } : {}),
    models: p.models.filter((m) => m.kind === 'chat').map((m) => ({ id: m.id, displayName: m.name, input: m.vision ? ['text', 'image'] : ['text'] })),
  }
}

/**
 * The model ids a person typed for an endpoint (a comma- or newline-separated field, or a
 * list): trimmed, without duplicates, at most 40 of up to 120 characters each.
 */
export function typedModelIds(input: unknown): string[] {
  const raw = Array.isArray(input) ? input.map(String) : typeof input === 'string' ? input.split(/[,\n]/) : []
  const out: string[] = []
  for (const piece of raw) {
    const id = piece.trim()
    if (!id || id.length > 120 || out.includes(id)) continue
    out.push(id)
    if (out.length === 40) break
  }
  return out
}

/** The credential name an own key is kept under. */
export function keyRefFor(providerId: string): string {
  return `NANOMUSE_KEY_${providerId.toUpperCase().replace(/[^A-Z0-9]/g, '_')}`
}

/**
 * The models an endpoint lists, by protocol: `GET /models` with the key (OpenAI's shape, which
 * the compatible providers speak), `/v1/models` with `x-api-key` for Anthropic, `/models?key=`
 * for Gemini. Empty when it does not answer in time — the catalogue's defaults stand in.
 */
export async function listModels(protocol: Protocol, baseURL: string, apiKey: string, fetchImpl: typeof fetch = fetch, timeoutMs = 8000): Promise<string[]> {
  const base = baseURL.replace(/\/+$/, '')
  const signal = AbortSignal.timeout(timeoutMs)
  let timer: ReturnType<typeof setTimeout> | undefined
  // the timer stays referenced: it is cleared in `finally`, and an unreferenced one lets Node 22
  // drain the event loop before it fires when nothing else is pending (the tests' hang case)
  const late = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error('timeout')), timeoutMs)
  })
  try {
    let request: Promise<Response>
    if (protocol === 'anthropic') {
      request = fetchImpl(`${base}/v1/models?limit=200`, { headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' }, signal })
    } else if (protocol === 'gemini' && apiOf(protocol, base) === 'google-generative-ai') {
      request = fetchImpl(`${base}/models?pageSize=200&key=${encodeURIComponent(apiKey)}`, { signal })
    } else {
      request = fetchImpl(`${base}/models`, { headers: apiKey ? { authorization: `Bearer ${apiKey}` } : {}, signal })
    }
    const res = await Promise.race([request, late])
    if (!res.ok) return []
    const body = (await Promise.race([res.json(), late])) as { data?: unknown; models?: unknown }
    const rows = Array.isArray(body.data) ? body.data : Array.isArray(body.models) ? body.models : []
    const ids: string[] = []
    for (const row of rows) {
      if (!row || typeof row !== 'object') continue
      const r = row as { id?: unknown; name?: unknown }
      const id = typeof r.id === 'string' ? r.id : typeof r.name === 'string' ? r.name.replace(/^models\//, '') : ''
      if (id) ids.push(id)
    }
    return ids.sort()
  } catch {
    return []
  } finally {
    if (timer) clearTimeout(timer)
  }
}

// ---- the ChatGPT sign-in ------------------------------------------------------------------------

/** What `cloud.json` keeps of the ChatGPT sign-in: never a token (the runtime's store has it). */
export interface ChatGptState {
  /** What the runtime called the plan ("ChatGPT Plus"). */
  label: string
  at: number
}

/** One line of the runtime's `--json` output. */
export interface RuntimeEvent {
  event: string
  [key: string]: unknown
}

/** NDJSON, a chunk at a time: whole lines become events, a partial last line waits for the next chunk. */
export class LineReader {
  private rest = ''

  push(chunk: string | Buffer): RuntimeEvent[] {
    this.rest += typeof chunk === 'string' ? chunk : chunk.toString('utf8')
    const lines = this.rest.split('\n')
    this.rest = lines.pop() ?? ''
    const out: RuntimeEvent[] = []
    for (const line of lines) {
      const text = line.trim()
      if (!text) continue
      try {
        const parsed: unknown = JSON.parse(text)
        if (parsed && typeof parsed === 'object' && typeof (parsed as { event?: unknown }).event === 'string') out.push(parsed as RuntimeEvent)
      } catch {
        // a line of the runtime's own logging: not an event
      }
    }
    return out
  }
}

export type SpawnLike = (command: string, args: string[], options: { stdio: ['ignore', 'pipe', 'pipe']; env: NodeJS.ProcessEnv; windowsHide: boolean }) => ChildProcess

export interface LoginView {
  status: 'idle' | 'waiting' | 'done' | 'error'
  /** The page to open in the person's browser, while `waiting`. */
  url: string
  label: string
  error: string
}

export interface ChatGptOptions {
  /** The runtime's executable, or nothing when there is none. */
  command(): Promise<string | undefined>
  spawn?: SpawnLike
  /** The proxy is up: the harness's provider row is (re)written with its URL, token and the models it listed. */
  onReady(url: string, token: string, models: string[]): Promise<void>
  /** The proxy went away (it is restarted unless stopped). */
  onDown?(): void
  /** The runtime says there is no sign-in any more (`not_signed_in`): the provider row should go. */
  onSignedOut?(): void
  onChange?(): void
  log?(level: 'info' | 'warn' | 'debug', text: string): void
  /** How long the login may wait for the person, and how long the proxy's `ready` may take. */
  loginTimeoutMs?: number
  readyTimeoutMs?: number
  /** The proxy's restart delay after an exit, and the cap it grows to. */
  restartMs?: number
  restartMaxMs?: number
}

/**
 * The ChatGPT sign-in and the proxy that serves it, over the runtime's `nanomuse chatgpt` commands.
 * The login is one child that ends by itself; the proxy is a managed child kept up for the host's
 * lifetime, restarted with a growing delay when it exits, stopped on `logout` and on shutdown.
 */
export class ChatGptDesk {
  private loginChild: ChildProcess | undefined
  private proxyChild: ChildProcess | undefined
  private proxyTimer: ReturnType<typeof setTimeout> | undefined
  private wanted = false
  private attempts = 0
  private view: LoginView = { status: 'idle', url: '', label: '', error: '' }
  private endpoint: { url: string; token: string } | undefined

  constructor(private readonly options: ChatGptOptions) {}

  get login(): LoginView {
    return { ...this.view }
  }

  /** The loopback URL and token while the proxy is up. */
  get ready(): { url: string; token: string } | undefined {
    return this.endpoint ? { ...this.endpoint } : undefined
  }

  get running(): boolean {
    return this.wanted
  }

  private spawn(): SpawnLike {
    return this.options.spawn ?? ((command, args, options) => nodeSpawn(command, args, options))
  }

  /**
   * `nanomuse chatgpt login --json`: resolves with the URL to open as soon as the runtime prints
   * it (the browser half opens it with the host's open-external bridge); `done` or an error
   * follows in `login`, and `done` starts the proxy.
   */
  async beginLogin(): Promise<string> {
    if (this.view.status === 'waiting' && this.view.url) return this.view.url
    const command = await this.options.command()
    if (!command) {
      this.set({ status: 'error', url: '', label: '', error: 'no_runtime' })
      throw new Error('no_runtime')
    }
    this.cancelLogin()
    this.set({ status: 'waiting', url: '', label: '', error: '' })
    const child = this.spawn()(command, ['chatgpt', 'login', '--json'], { stdio: ['ignore', 'pipe', 'pipe'], env: process.env, windowsHide: true })
    this.loginChild = child
    const reader = new LineReader()
    const stderr: string[] = []
    return new Promise<string>((resolve, reject) => {
      let gotUrl = false
      const timer = setTimeout(() => {
        if (this.loginChild === child) {
          this.log('warn', 'nanomuse chatgpt: the sign-in did not finish in time')
          child.kill()
        }
      }, this.options.loginTimeoutMs ?? 10 * 60_000)
      timer.unref?.()
      const fail = (error: string) => {
        clearTimeout(timer)
        if (this.loginChild === child) this.loginChild = undefined
        this.set({ status: 'error', url: '', label: '', error })
        if (!gotUrl) reject(new Error(error))
      }
      child.stderr?.on('data', (chunk: Buffer) => {
        stderr.push(chunk.toString('utf8'))
        if (stderr.length > 40) stderr.shift()
      })
      child.stdout?.on('data', (chunk: Buffer) => {
        for (const ev of reader.push(chunk)) {
          if (ev.event === 'url' && typeof ev.url === 'string') {
            gotUrl = true
            this.set({ ...this.view, status: 'waiting', url: ev.url })
            resolve(ev.url)
          } else if (ev.event === 'done') {
            clearTimeout(timer)
            if (ev.ok === false) {
              fail(typeof ev.error === 'string' && ev.error ? ev.error : 'refused')
              continue
            }
            const label = typeof ev.label === 'string' && ev.label ? ev.label : 'ChatGPT'
            this.set({ status: 'done', url: '', label, error: '' })
            if (this.loginChild === child) this.loginChild = undefined
            if (!gotUrl) {
              gotUrl = true
              resolve('')
            }
            this.start()
          } else if (ev.event === 'error') {
            fail(typeof ev.message === 'string' && ev.message ? ev.message : 'failed')
          }
        }
      })
      child.on('error', (error) => fail(error.message))
      child.on('exit', (code) => {
        if (this.loginChild !== child) return
        this.loginChild = undefined
        if (this.view.status === 'waiting') fail(code === 0 ? 'no_result' : (stderr.join('').trim().split('\n').pop() ?? `exit ${code}`).slice(0, 200))
      })
    })
  }

  /** The person gave up: the login child ends, the view goes back to idle. */
  cancelLogin(): void {
    const child = this.loginChild
    this.loginChild = undefined
    if (child) {
      child.kill()
      this.set({ status: 'idle', url: '', label: '', error: '' })
    }
  }

  /** Keep the proxy up from now on (a sign-in that was done, or the host starting with one on file). */
  start(): void {
    if (this.wanted) return
    this.wanted = true
    this.attempts = 0
    void this.runProxy()
  }

  /** Stop the proxy and keep it stopped (sign-out of ChatGPT, or the host shutting down). */
  stop(): void {
    this.wanted = false
    if (this.proxyTimer) clearTimeout(this.proxyTimer)
    this.proxyTimer = undefined
    const child = this.proxyChild
    this.proxyChild = undefined
    child?.kill()
    if (this.endpoint) {
      this.endpoint = undefined
      this.options.onDown?.()
    }
    this.options.onChange?.()
  }

  /** `nanomuse chatgpt status --json`: whether the runtime holds a sign-in, and what it calls the plan. Never touches the network. */
  async status(): Promise<{ signedIn: boolean; label: string } | undefined> {
    const command = await this.options.command()
    if (!command) return undefined
    return new Promise((resolve) => {
      const child = this.spawn()(command, ['chatgpt', 'status', '--json'], { stdio: ['ignore', 'pipe', 'pipe'], env: process.env, windowsHide: true })
      const timer = setTimeout(() => child.kill(), 15_000)
      timer.unref?.()
      let out = ''
      child.stdout?.on('data', (chunk: Buffer) => { out += chunk.toString('utf8') })
      child.on('error', () => resolve(undefined))
      child.on('exit', () => {
        clearTimeout(timer)
        const line = out.split('\n').map((l) => l.trim()).find((l) => l.startsWith('{'))
        if (!line) return resolve(undefined)
        try {
          const parsed = JSON.parse(line) as { signed_in?: unknown; label?: unknown }
          resolve({ signedIn: parsed.signed_in === true, label: typeof parsed.label === 'string' ? parsed.label : '' })
        } catch {
          resolve(undefined)
        }
      })
    })
  }

  /** `nanomuse chatgpt logout`: the runtime forgets the tokens; the proxy stops. */
  async logout(): Promise<void> {
    this.cancelLogin()
    this.stop()
    this.set({ status: 'idle', url: '', label: '', error: '' })
    const command = await this.options.command()
    if (!command) return
    await new Promise<void>((resolve) => {
      const child = this.spawn()(command, ['chatgpt', 'logout'], { stdio: ['ignore', 'pipe', 'pipe'], env: process.env, windowsHide: true })
      const timer = setTimeout(() => child.kill(), 15_000)
      timer.unref?.()
      child.on('error', () => resolve())
      child.on('exit', () => {
        clearTimeout(timer)
        resolve()
      })
    })
  }

  private async runProxy(): Promise<void> {
    if (!this.wanted || this.proxyChild) return
    const command = await this.options.command()
    if (!command) {
      this.log('warn', 'nanomuse chatgpt: no runtime to run the proxy with')
      this.scheduleRestart()
      return
    }
    const child = this.spawn()(command, ['chatgpt', 'proxy', '--json'], { stdio: ['ignore', 'pipe', 'pipe'], env: process.env, windowsHide: true })
    this.proxyChild = child
    const reader = new LineReader()
    let ready = false
    const readyTimer = setTimeout(() => {
      if (!ready && this.proxyChild === child) {
        this.log('warn', 'nanomuse chatgpt: the proxy did not come up in time')
        child.kill()
      }
    }, this.options.readyTimeoutMs ?? 60_000)
    readyTimer.unref?.()
    child.stdout?.on('data', (chunk: Buffer) => {
      for (const ev of reader.push(chunk)) {
        if (ev.event === 'ready' && typeof ev.url === 'string') {
          ready = true
          clearTimeout(readyTimer)
          this.attempts = 0
          const token = typeof ev.token === 'string' ? ev.token : ''
          this.endpoint = { url: ev.url.replace(/\/+$/, ''), token }
          if (typeof ev.label === 'string' && ev.label) this.view = { ...this.view, label: ev.label }
          const models = Array.isArray(ev.models) ? ev.models.filter((m): m is string => typeof m === 'string' && Boolean(m)) : []
          this.log('info', `nanomuse chatgpt: proxy up at ${this.endpoint.url}`)
          void this.options.onReady(this.endpoint.url, token, models).catch((error: unknown) => this.log('warn', `nanomuse chatgpt: provider row not written: ${error instanceof Error ? error.message : String(error)}`))
          this.options.onChange?.()
        } else if (ev.event === 'error') {
          this.log('warn', `nanomuse chatgpt: proxy: ${String(ev.message ?? '')}`)
          if (ev.code === 'not_signed_in') {
            // the store is gone (a refresh was refused, or a logout elsewhere): nothing to restart for
            this.wanted = false
            this.options.onSignedOut?.()
          }
        }
      }
    })
    child.stderr?.on('data', (chunk: Buffer) => this.log('debug', `nanomuse chatgpt: ${chunk.toString('utf8').trim()}`))
    child.on('error', (error) => this.log('warn', `nanomuse chatgpt: proxy not started: ${error.message}`))
    child.on('exit', (code) => {
      clearTimeout(readyTimer)
      if (this.proxyChild !== child) return
      this.proxyChild = undefined
      if (this.endpoint) {
        this.endpoint = undefined
        this.options.onDown?.()
      }
      this.options.onChange?.()
      if (this.wanted) {
        this.log('info', `nanomuse chatgpt: proxy exited (${code ?? 'signal'}); starting it again`)
        this.scheduleRestart()
      }
    })
  }

  private scheduleRestart(): void {
    if (!this.wanted || this.proxyTimer) return
    const base = this.options.restartMs ?? 2000
    const max = this.options.restartMaxMs ?? 60_000
    const delay = Math.min(max, base * 2 ** Math.min(this.attempts, 10))
    this.attempts += 1
    this.proxyTimer = setTimeout(() => {
      this.proxyTimer = undefined
      void this.runProxy()
    }, delay)
    this.proxyTimer.unref?.()
  }

  private set(view: LoginView): void {
    this.view = view
    this.options.onChange?.()
  }

  private log(level: 'info' | 'warn' | 'debug', text: string): void {
    this.options.log?.(level, text)
  }
}
