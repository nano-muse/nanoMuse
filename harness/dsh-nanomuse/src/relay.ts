/**
 * The nanoMuse Cloud relay as a client: the handful of `/v1` calls the desktop
 * needs to sign in, learn who it is and which models the account's key may use.
 * Plain `fetch`, no Cordis — the service in `cloud.ts` owns state and wiring,
 * and the tests drive this against a fake relay.
 *
 * The relay speaks OpenAI Chat Completions under `/v1`, so the account's key is
 * handed to the harness's own model adapter (`dsh-llm-pi-ai`) rather than to
 * an adapter of ours; nothing here touches a model request.
 */

import { readSharedConnectors, type SharedConnector } from './desk.ts'

/** How long one relay call may take before it is given up: a connection that hangs must not stall a sign-in, a models list or the sync for good. */
export const RELAY_TIMEOUT_MS = 30_000
/** The budget for a picture made or edited through the relay: the model behind it takes its time. */
export const RELAY_IMAGE_TIMEOUT_MS = 180_000

/** A `fetch` init that may name its own budget; the wrapped fetch takes it off before the call. */
export type TimedInit = RequestInit & { timeoutMs?: number }
export type TimedFetch = (input: string | URL | Request, init?: TimedInit) => Promise<Response>

/**
 * `fetchImpl` with a deadline on every call: `init.timeoutMs`, else `defaultMs`. A signal
 * the caller passed still cancels; the deadline is added to it, not put in its place.
 */
export function withTimeout(fetchImpl: typeof fetch, defaultMs: number): TimedFetch {
  return (input, init) => {
    const { timeoutMs, ...rest } = init ?? {}
    const deadline = AbortSignal.timeout(timeoutMs ?? defaultMs)
    const signal = rest.signal ? AbortSignal.any([rest.signal, deadline]) : deadline
    return fetchImpl(input, { ...rest, signal })
  }
}

/** A relay error, with the relay's own code when it sent one. */
export class RelayError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = 'RelayError'
  }
}

/** The relay's view of the signed-in account (`GET /v1/me`, trimmed). */
export interface Account {
  /** Opaque account id — never the phone number or e-mail. */
  id: string
  /** `phone` or `email`. */
  channel: string
  /** Masked identifier the relay already prepared for display, e.g. `195****0404`. */
  hint: string
  member: boolean
  tokens: {
    unlimited: boolean
    granted: number
    used: number
    remaining: number
  }
  /** Data controls — "Help improve nanoMuse's AI models" (relay 0.9); absent on an older relay. */
  contribute?: DataControls
  /** The pool in yuan (relay 0.5+): what was granted, spent and is left, and the ways on. */
  spend?: Spend
  /** The star-nudge policy (C1), when the relay sends it with the account; the rooms read it. */
  nudges?: unknown
  /** The relay's word on where the person is (`cn`, `intl`, `unknown`; relay 0.1.34+), which orders the own-key "ways on" (C11). */
  region?: string
}

/** `GET /v1/me` → `spend`, trimmed: the lifetime pool in yuan, as the apps show it. */
export interface Spend {
  /** The pool for the account's lifetime, in yuan; absent for a member (no limit). */
  grant?: number
  /** Spent so far, in yuan. */
  total: number
  /** Left, in yuan; null = no limit. */
  left: number | null
  unlimited: boolean
  /** From 80 % on. */
  warn: boolean
  usdCny?: number
  inviteBonusCny?: number
  inviteeBonusCny?: number
  ownKeyDocs?: string
}

/** The switch over what the relay keeps of the account's chats, and what it holds so far. */
export interface DataControls {
  on: boolean
  samples: number
  /** How the relay starts new accounts; undefined when it did not say. */
  defaultOn?: boolean
  privacyUrl: string
  /** The record (relay 0.29): whether this relay keeps one and what it holds of the account; absent on an older relay. */
  record?: RecordView
}

/** `GET /v1/me` → `contribute.record`: the account's record in figures. */
export interface RecordView {
  on: boolean
  turns: number
  /** Turns the account's apps ran on keys of their own and sent up (1.0.7 on). */
  own: number
  files: number
  mediaBytes: number
  /** 0: kept until the person deletes it. */
  keepDays: number
}

/** Capacities share Android's signed 32-bit range; booleans and coercions are not counts. */
function positiveCapacity(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 && value <= 2147483647 ? value : undefined
}

/** One model the account may use, as `GET /v1/models` lists it. */
export interface RelayModel {
  id: string
  name: string
  /** `chat`, `image`, `video` — only `chat` models join the model picker. */
  kind: string
  recommended: boolean
  /** The lanes this model is the relay's first choice for. */
  recommendedFor?: string[]
  inputModalities: string[]
  /** What the relay says it is for (relay 0.1.34+): `chat`, `gui`, or both; absent on an older relay. */
  for?: string[]
  contextWindow?: number
  maxTokens?: number
}

export interface SignIn {
  apiKey: string
  created: boolean
  account: Account
}

/** The account's invite code and what it has brought (`GET /v1/me/invite`, trimmed: no friends' hints). */
export interface Invite {
  code: string
  url: string
  invites: number
  /** What a friend who signs up with the code gets, and what the inviter earns — the same figure. */
  bonusCny: number
  earnedCny: number
}

/** What the desktop may write to the account's profile: the name and the simple looks. */
export interface ProfileWrite {
  name: string
  avatar: 'dragon' | 'emoji' | 'face'
  emoji: string
  color: string
  style: string
  description: string
  /** A drawn face's stills, `{mood: base64 WebP}` — only when a face was drawn here. */
  face?: Record<string, string>
  /** This device's connections, for the other devices to see (never a credential); the relay keeps the other devices' rows. */
  connectors?: SharedConnector[]
  /** Which device's rows `connectors` replaces. */
  device_id?: string
  /** The drawn face's clips as files this account put up (relay 0.29); `null` clears them. Absent keeps what is stored. */
  clips?: Record<string, ProfileClip> | null
}

/** One clip of the drawn face in the account's profile: a file at `GET /v1/blobs/{sha256}`. */
export interface ProfileClip {
  sha256: string
  mime: string
  bytes: number
}

/** What a few pictures would cost next to what is left today (`GET /v1/estimate`). */
export interface Estimate {
  cny: number
  leftCny: number
  unlimited: boolean
  affordable: boolean
  imageModel: string
  /** How many clips the estimate counted (0 when the avatar is not animated on Cloud). */
  clips: number
  /** The video model the relay would use for them, when it counted any. */
  videoModel: string
  /** Who draws the pictures (0.1.41): the account, or an own row (nothing billed by the account). */
  source?: 'cloud' | 'provider'
  /** That source's label (`nanoMuse Cloud`, the row's label). */
  label?: string
}

/** The account's profile as the relay keeps it (`docs/hub.md`): the agent's name and look. */
export interface RelayProfile {
  /** 0 until a device has written one. */
  rev: number
  /** The device that wrote this rev. */
  device: string
  name: string
  /** `dragon`, `emoji`, `face` (one drawn in the avatar studio), or empty. */
  avatar: string
  emoji: string
  color: string
  style: string
  description: string
  hasFace: boolean
  /** The hash of the idle still — a device wearing these pictures keeps its copy. */
  faceId: string
  /** `mood -> base64 WebP`, when asked for. */
  face?: Record<string, string>
  /** The account's connections across devices, as the relay lists them (relay 0.1.34+). */
  connectors: SharedConnector[]
  /** The face's clips another device made (relay 0.29), by mood; absent when there are none. */
  clips?: Record<string, ProfileClip>
}

const JSON_HEADERS = { 'content-type': 'application/json' }

async function fail(res: Response): Promise<never> {
  let code = `http_${res.status}`
  let message = `${res.status} ${res.statusText}`.trim()
  try {
    const body = (await res.json()) as { error?: { code?: string; message?: string } }
    if (body.error?.code) code = body.error.code
    if (body.error?.message) message = body.error.message
  } catch {
    // not JSON — the status line is the message
  }
  throw new RelayError(res.status, code, message)
}

/** `{mood: {sha256, mime, bytes}}` as the relay sends it; entries that are not a hex SHA-256 are left out. */
export function readProfileClips(raw: unknown): Record<string, ProfileClip> | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const out: Record<string, ProfileClip> = {}
  for (const [mood, v] of Object.entries(raw as Record<string, unknown>)) {
    if (!v || typeof v !== 'object') continue
    const c = v as Record<string, unknown>
    const sha256 = String(c.sha256 ?? '').toLowerCase()
    if (!/^[0-9a-f]{64}$/.test(sha256)) continue
    out[mood] = { sha256, mime: String(c.mime ?? ''), bytes: typeof c.bytes === 'number' ? c.bytes : 0 }
  }
  return Object.keys(out).length ? out : undefined
}

function toDataControls(ct: unknown): DataControls | undefined {
  if (!ct || typeof ct !== 'object') return undefined
  const c = ct as Record<string, unknown>
  const record = toRecordView(c.record)
  return {
    on: Boolean(c.on),
    samples: Number(c.samples ?? 0),
    ...(typeof c.default_on === 'boolean' ? { defaultOn: c.default_on } : {}),
    privacyUrl: String(c.privacy_url ?? ''),
    ...(record ? { record } : {}),
  }
}

function toRecordView(raw: unknown): RecordView | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const r = raw as Record<string, unknown>
  const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
  return { on: Boolean(r.on), turns: num(r.turns), own: num(r.own), files: num(r.files), mediaBytes: num(r.media_bytes), keepDays: num(r.keep_days) }
}

function toSpend(raw: unknown): Spend | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const s = raw as Record<string, unknown>
  const num = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)
  const spend: Spend = {
    total: num(s.total) ?? 0,
    left: num(s.left) ?? null,
    unlimited: Boolean(s.unlimited),
    warn: Boolean(s.warn),
  }
  const grant = num(s.grant)
  if (grant !== undefined) spend.grant = grant
  const usdCny = num(s.usd_cny)
  if (usdCny !== undefined) spend.usdCny = usdCny
  const inviteBonusCny = num(s.invite_bonus_cny)
  if (inviteBonusCny !== undefined) spend.inviteBonusCny = inviteBonusCny
  const inviteeBonusCny = num(s.invitee_bonus_cny)
  if (inviteeBonusCny !== undefined) spend.inviteeBonusCny = inviteeBonusCny
  if (typeof s.own_key_docs === 'string' && s.own_key_docs) spend.ownKeyDocs = s.own_key_docs
  return spend
}

function toAccount(me: Record<string, unknown>): Account {
  const account = (me.account ?? {}) as Record<string, unknown>
  const tokens = (me.tokens ?? {}) as Record<string, unknown>
  const contribute = toDataControls(me.contribute)
  const spend = toSpend(me.spend)
  return {
    id: String(account.id ?? ''),
    channel: String(account.channel ?? ''),
    hint: String(account.hint ?? ''),
    member: Boolean(account.member),
    tokens: {
      unlimited: Boolean(tokens.unlimited),
      granted: Number(tokens.granted ?? 0),
      used: Number(tokens.used ?? 0),
      remaining: Number(tokens.remaining ?? 0),
    },
    ...(contribute ? { contribute } : {}),
    ...(spend ? { spend } : {}),
    ...(me.nudges && typeof me.nudges === 'object' ? { nudges: me.nudges } : {}),
    ...(typeof me.region === 'string' && me.region && me.region !== 'unknown' ? { region: me.region } : {}),
  }
}

/** A client for one relay origin, e.g. `https://cloud.nanomuse.cn`. */
export class Relay {
  readonly origin: string
  private readonly fetchImpl: TimedFetch

  constructor(origin: string, fetchImpl: typeof fetch = fetch, timeoutMs = RELAY_TIMEOUT_MS) {
    this.origin = origin.replace(/\/+$/, '')
    this.fetchImpl = withTimeout(fetchImpl, timeoutMs)
  }

  /** The OpenAI-compatible root the model adapter is pointed at. */
  get openaiBase(): string {
    return `${this.origin}/v1`
  }

  /** Ask for a six-digit code (SMS for a mainland number, e-mail otherwise). */
  async requestCode(identifier: string, signal?: AbortSignal): Promise<void> {
    const res = await this.fetchImpl(`${this.origin}/v1/auth/code`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ identifier }),
      signal: signal ?? null,
    })
    if (!res.ok) await fail(res)
  }

  /** Trade the code for this device's key. */
  async verify(identifier: string, code: string, device: string, signal?: AbortSignal, invite = ''): Promise<SignIn> {
    const res = await this.fetchImpl(`${this.origin}/v1/auth/verify`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ identifier, code: code.trim(), device: device.slice(0, 80), ...(invite.trim() ? { invite: invite.trim() } : {}) }),
      signal: signal ?? null,
    })
    if (!res.ok) await fail(res)
    const body = (await res.json()) as Record<string, unknown>
    return { apiKey: String(body.api_key ?? ''), created: Boolean(body.created), account: toAccount(body) }
  }

  /** The password way in, for people who set one (`POST /v1/auth/login`). */
  async login(identifier: string, password: string, device: string, signal?: AbortSignal): Promise<SignIn> {
    const res = await this.fetchImpl(`${this.origin}/v1/auth/login`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ identifier, password, device: device.slice(0, 80) }),
      signal: signal ?? null,
    })
    if (!res.ok) await fail(res)
    const body = (await res.json()) as Record<string, unknown>
    return { apiKey: String(body.api_key ?? ''), created: false, account: toAccount(body) }
  }

  /** The account's invite code and link, and what inviting has brought (`GET /v1/me/invite`). */
  async invite(apiKey: string, signal?: AbortSignal): Promise<Invite> {
    const res = await this.fetchImpl(`${this.origin}/v1/me/invite`, { headers: this.auth(apiKey), signal: signal ?? null })
    if (!res.ok) await fail(res)
    const body = (await res.json()) as Record<string, unknown>
    return {
      code: String(body.code ?? ''),
      url: String(body.url ?? ''),
      invites: Number(body.invites ?? 0),
      bonusCny: Number(body.bonus_cny ?? 0),
      earnedCny: Number(body.earned_cny ?? 0),
    }
  }

  /**
   * Write the agent's name and look for every device of the account
   * (`PUT /v1/me/profile`, last writer wins). A field left out keeps its stored
   * value (relay 0.25); the desktop sends the whole look, with `face` when one
   * was drawn in its studio.
   */
  async putProfile(apiKey: string, body: ProfileWrite, device: string, signal?: AbortSignal): Promise<number> {
    const res = await this.fetchImpl(`${this.origin}/v1/me/profile`, {
      method: 'PUT',
      headers: { ...this.auth(apiKey), ...JSON_HEADERS },
      body: JSON.stringify({ ...body, device: device.slice(0, 80) }),
      signal: signal ?? null,
    })
    if (!res.ok) await fail(res)
    const out = (await res.json().catch(() => ({}))) as { rev?: number }
    return Number(out.rev ?? 0)
  }

  /**
   * Name the face's clips in the account's profile alone (`PUT /v1/me/profile` with only `clips`,
   * relay 0.29): the look stays as it is; the other devices download these instead of drawing.
   */
  async putProfileClips(apiKey: string, clips: Record<string, ProfileClip>, device: string, signal?: AbortSignal): Promise<number> {
    const res = await this.fetchImpl(`${this.origin}/v1/me/profile`, {
      method: 'PUT',
      headers: { ...this.auth(apiKey), ...JSON_HEADERS },
      body: JSON.stringify({ clips, device: device.slice(0, 80) }),
      signal: signal ?? null,
    })
    if (!res.ok) await fail(res)
    const out = (await res.json().catch(() => ({}))) as { rev?: number }
    return Number(out.rev ?? 0)
  }

  /**
   * Write this device's connections alone (`PUT /v1/me/profile` with only `connectors`):
   * the relay replaces this device's rows, keeps the other devices' and leaves the
   * account's name and look untouched.
   */
  async putConnectors(apiKey: string, connectors: SharedConnector[], deviceId: string, device: string, signal?: AbortSignal): Promise<number> {
    const res = await this.fetchImpl(`${this.origin}/v1/me/profile`, {
      method: 'PUT',
      headers: { ...this.auth(apiKey), ...JSON_HEADERS },
      body: JSON.stringify({ connectors, device_id: deviceId.slice(0, 80), device: device.slice(0, 80) }),
      signal: signal ?? null,
    })
    if (!res.ok) await fail(res)
    const out = (await res.json().catch(() => ({}))) as { rev?: number }
    return Number(out.rev ?? 0)
  }

  /** What `images` pictures and `clips` short videos would cost today, and the models the relay would use (nothing charged). */
  async estimate(apiKey: string, images: number, clips = 0, signal?: AbortSignal): Promise<Estimate> {
    const n = Math.max(0, Math.floor(images))
    const c = Math.max(0, Math.floor(clips))
    const res = await this.fetchImpl(`${this.origin}/v1/estimate?images=${n}${c ? `&clips=${c}` : ''}`, { headers: this.auth(apiKey), signal: signal ?? null })
    if (!res.ok) await fail(res)
    const body = (await res.json()) as { cny?: number; left_cny?: number; unlimited?: boolean; affordable?: boolean; parts?: { kind?: string; model?: string }[] }
    return {
      cny: Number(body.cny ?? 0),
      leftCny: Number(body.left_cny ?? 0),
      unlimited: body.unlimited === true,
      affordable: body.affordable !== false,
      imageModel: String(body.parts?.find((p) => p.kind === 'image')?.model ?? ''),
      clips: c,
      videoModel: String(body.parts?.find((p) => p.kind === 'video' || p.kind === 'clip')?.model ?? ''),
    }
  }

  /** One picture from words (`POST /v1/images/generations`, OpenAI's shape); the bytes. */
  async generateImage(apiKey: string, model: string, prompt: string, signal?: AbortSignal): Promise<Buffer> {
    const res = await this.fetchImpl(`${this.origin}/v1/images/generations`, {
      method: 'POST',
      headers: { ...this.auth(apiKey), ...JSON_HEADERS },
      body: JSON.stringify({ model, prompt, n: 1, size: '1024x1024', response_format: 'b64_json' }),
      signal: signal ?? null,
      timeoutMs: RELAY_IMAGE_TIMEOUT_MS,
    })
    if (!res.ok) await fail(res)
    return this.imageOf(await res.json())
  }

  /** The same character in another pose (`POST /v1/images/edits`, multipart); the bytes. */
  async editImage(apiKey: string, model: string, image: Buffer, prompt: string, signal?: AbortSignal): Promise<Buffer> {
    const form = new FormData()
    form.set('model', model)
    form.set('prompt', prompt)
    form.set('n', '1')
    form.set('size', '1024x1024')
    form.set('response_format', 'b64_json')
    form.set('image', new Blob([new Uint8Array(image)], { type: 'image/png' }), 'idle.png')
    const res = await this.fetchImpl(`${this.origin}/v1/images/edits`, { method: 'POST', headers: this.auth(apiKey), body: form, signal: signal ?? null, timeoutMs: RELAY_IMAGE_TIMEOUT_MS })
    if (!res.ok) await fail(res)
    return this.imageOf(await res.json())
  }

  private async imageOf(body: unknown): Promise<Buffer> {
    const first = ((body as { data?: { b64_json?: string; url?: string }[] }).data ?? [])[0]
    if (first?.b64_json) return Buffer.from(first.b64_json, 'base64')
    if (first?.url) {
      const res = await this.fetchImpl(first.url)
      if (!res.ok) throw new RelayError(502, 'image', `The picture could not be fetched (${res.status})`)
      return Buffer.from(await res.arrayBuffer())
    }
    throw new RelayError(502, 'image', 'The model returned no picture')
  }

  /**
   * The relay's public figures (`GET /v1/config`, relay 0.15): the allowance a new account
   * gets, the invite bonus, whether sign-up is open, the repository to star. `{}` from an
   * older relay, which has no such route.
   */
  async config(signal?: AbortSignal): Promise<Record<string, unknown>> {
    const res = await this.fetchImpl(`${this.origin}/v1/config`, { signal: signal ?? null })
    if (!res.ok) return {}
    const body = (await res.json().catch(() => ({}))) as unknown
    return body && typeof body === 'object' ? (body as Record<string, unknown>) : {}
  }

  /** The whole account sheet (`GET /v1/me`), as the relay sends it: usage by kind and model, the pool, the invite, the password. */
  async meSheet(apiKey: string, signal?: AbortSignal): Promise<Record<string, unknown>> {
    const res = await this.fetchImpl(`${this.origin}/v1/me`, { headers: this.auth(apiKey), signal: signal ?? null })
    if (!res.ok) await fail(res)
    return (await res.json()) as Record<string, unknown>
  }

  /** Every device holding a key for the account (`GET /v1/me/sessions`). */
  async sessions(apiKey: string, signal?: AbortSignal): Promise<Record<string, unknown>> {
    const res = await this.fetchImpl(`${this.origin}/v1/me/sessions`, { headers: this.auth(apiKey), signal: signal ?? null })
    if (!res.ok) await fail(res)
    return (await res.json()) as Record<string, unknown>
  }

  /** Retire one device's key by its prefix (`DELETE /v1/me/sessions/{prefix}`). */
  async revokeSession(apiKey: string, prefix: string, signal?: AbortSignal): Promise<void> {
    const res = await this.fetchImpl(`${this.origin}/v1/me/sessions/${encodeURIComponent(prefix)}`, { method: 'DELETE', headers: this.auth(apiKey), signal: signal ?? null })
    if (!res.ok) await fail(res)
  }

  /** The account's recent events (`GET /v1/me/events?limit=`): sign-ins, refusals, grants. */
  async events(apiKey: string, limit = 40, signal?: AbortSignal): Promise<Record<string, unknown>> {
    const res = await this.fetchImpl(`${this.origin}/v1/me/events?limit=${Math.max(1, Math.min(200, Math.floor(limit)))}`, { headers: this.auth(apiKey), signal: signal ?? null })
    if (!res.ok) await fail(res)
    return (await res.json()) as Record<string, unknown>
  }

  /** Set or change the password (`POST /v1/auth/password`); `current` when one exists; an empty password with `current` removes it. */
  async setPassword(apiKey: string, password: string, current?: string, signal?: AbortSignal): Promise<void> {
    const res = await this.fetchImpl(`${this.origin}/v1/auth/password`, {
      method: 'POST',
      headers: { ...JSON_HEADERS, ...this.auth(apiKey) },
      body: JSON.stringify({ password, ...(current === undefined ? {} : { current }) }),
      signal: signal ?? null,
    })
    if (!res.ok) await fail(res)
  }

  /** Retire every key of the account, this device's too (`POST /v1/auth/sign-out-all`). */
  async signOutAll(apiKey: string, signal?: AbortSignal): Promise<void> {
    const res = await this.fetchImpl(`${this.origin}/v1/auth/sign-out-all`, { method: 'POST', headers: { ...this.auth(apiKey), 'content-type': 'application/json' }, body: JSON.stringify({ all: true }), signal: signal ?? null })
    if (!res.ok) await fail(res)
  }

  /** Delete the account, its keys, ledger and devices (`POST /v1/auth/delete`). */
  async deleteAccount(apiKey: string, signal?: AbortSignal): Promise<void> {
    const res = await this.fetchImpl(`${this.origin}/v1/auth/delete`, { method: 'POST', headers: this.auth(apiKey), signal: signal ?? null })
    if (!res.ok) await fail(res)
  }

  /** Who the key belongs to and what is left of the allowance. */
  async me(apiKey: string, signal?: AbortSignal): Promise<Account> {
    const res = await this.fetchImpl(`${this.origin}/v1/me`, { headers: this.auth(apiKey), signal: signal ?? null })
    if (!res.ok) await fail(res)
    return toAccount((await res.json()) as Record<string, unknown>)
  }

  /** The models the relay offers this key. */
  async models(apiKey: string, signal?: AbortSignal): Promise<RelayModel[]> {
    const res = await this.fetchImpl(`${this.origin}/v1/models`, { headers: this.auth(apiKey), signal: signal ?? null })
    if (!res.ok) await fail(res)
    const body = (await res.json()) as { data?: Record<string, unknown>[] }
    return (body.data ?? []).map((m) => {
      const arch = (m.architecture ?? {}) as Record<string, unknown>
      const extra = (m.nanomuse ?? {}) as Record<string, unknown>
      const contextWindow = positiveCapacity(m.context_length)
      const maxTokens = positiveCapacity(m.max_output_tokens)
      return {
        id: String(m.id ?? ''),
        name: String(m.name ?? m.id ?? ''),
        kind: String(extra.kind ?? 'chat'),
        recommended: Boolean(extra.recommended),
        ...(Array.isArray(extra.recommended_for) ? { recommendedFor: extra.recommended_for.map(String) } : {}),
        inputModalities: Array.isArray(arch.input_modalities) ? arch.input_modalities.map(String) : ['text'],
        ...(contextWindow === undefined ? {} : { contextWindow }),
        ...(maxTokens === undefined ? {} : { maxTokens }),
        ...(Array.isArray(extra.for) ? { for: extra.for.map(String) } : {}),
      }
    })
  }

  /** The hub socket for this relay (`ws://` for a dev relay on plain HTTP). */
  get hubURL(): string {
    return `${this.origin.replace(/^http/, 'ws')}/v1/hub`
  }

  /**
   * The account's name and look (`GET /v1/me/profile`). Without the face the
   * answer is small; with it, the five stills come along as base64 WebP.
   */
  async profile(apiKey: string, withFace: boolean, signal?: AbortSignal): Promise<RelayProfile> {
    const res = await this.fetchImpl(`${this.origin}/v1/me/profile?face=${withFace ? 'true' : 'false'}`, {
      headers: this.auth(apiKey),
      signal: signal ?? null,
    })
    if (!res.ok) await fail(res)
    const body = (await res.json()) as Record<string, unknown>
    const face = body.face && typeof body.face === 'object' ? (body.face as Record<string, unknown>) : undefined
    const clips = readProfileClips(body.clips)
    return {
      rev: Number(body.rev ?? 0),
      device: String(body.device ?? ''),
      name: String(body.name ?? ''),
      avatar: String(body.avatar ?? ''),
      emoji: String(body.emoji ?? ''),
      color: String(body.color ?? ''),
      style: String(body.style ?? ''),
      description: String(body.description ?? ''),
      hasFace: Boolean(body.has_face),
      faceId: String(body.face_id ?? ''),
      connectors: readSharedConnectors(body.connectors),
      ...(face ? { face: Object.fromEntries(Object.entries(face).filter(([, v]) => typeof v === 'string')) as Record<string, string> } : {}),
      ...(clips ? { clips } : {}),
    }
  }

  /** `GET /v1/blobs/{sha256}`: a file of the account's (a clip of the face, a picture of a turn), with its type. */
  async getBlob(apiKey: string, sha256: string, signal?: AbortSignal): Promise<{ data: Uint8Array; mime: string }> {
    const res = await this.fetchImpl(`${this.origin}/v1/blobs/${encodeURIComponent(sha256)}`, { headers: this.auth(apiKey), signal: signal ?? null, timeoutMs: RELAY_IMAGE_TIMEOUT_MS })
    if (!res.ok) await fail(res)
    return { data: new Uint8Array(await res.arrayBuffer()), mime: (res.headers.get('content-type') ?? '').split(';')[0]?.trim() ?? '' }
  }

  /**
   * Data controls: flip "Help improve nanoMuse's AI models". While on, the relay keeps the
   * account's chat turns (what was written, what was answered, the tool calls) for the
   * community's own model; the allowance is not touched.
   */
  async setContribute(apiKey: string, on: boolean, signal?: AbortSignal): Promise<DataControls> {
    const res = await this.fetchImpl(`${this.origin}/v1/me/contribute`, {
      method: 'POST',
      headers: { ...this.auth(apiKey), ...JSON_HEADERS },
      body: JSON.stringify({ on }),
      signal: signal ?? null,
    })
    if (!res.ok) await fail(res)
    return toDataControls(await res.json()) ?? { on, samples: 0, privacyUrl: '' }
  }

  /**
   * Delete every turn the relay kept from the account (the training turns, and from relay 0.29
   * the record with its files); how many training turns went.
   */
  async deleteSamples(apiKey: string, signal?: AbortSignal): Promise<number> {
    const res = await this.fetchImpl(`${this.origin}/v1/me/samples`, {
      method: 'DELETE',
      headers: this.auth(apiKey),
      signal: signal ?? null,
    })
    if (!res.ok) await fail(res)
    const body = (await res.json().catch(() => ({}))) as { deleted?: number }
    return Number(body.deleted ?? 0)
  }

  /** Retire this device's key on the relay; a key the relay no longer knows is fine. */
  async signOut(apiKey: string, signal?: AbortSignal): Promise<void> {
    const res = await this.fetchImpl(`${this.origin}/v1/auth/sign-out`, {
      method: 'POST',
      headers: this.auth(apiKey),
      signal: signal ?? null,
    })
    if (!res.ok && res.status !== 401) await fail(res)
  }

  /** `HEAD /v1/blobs/{sha256}`: whether the account can already read the file (so a device need not send what another one did). */
  async hasBlob(apiKey: string, sha256: string, signal?: AbortSignal): Promise<boolean> {
    const res = await this.fetchImpl(`${this.origin}/v1/blobs/${encodeURIComponent(sha256)}`, { method: 'HEAD', headers: this.auth(apiKey), signal: signal ?? null })
    if (res.ok) return true
    if (res.status === 404) return false
    return fail(res)
  }

  /** `PUT /v1/blobs/{sha256}`: a picture, audio clip or video, raw, named by its hash (the relay checks it). */
  async putBlob(apiKey: string, sha256: string, mime: string, data: Uint8Array, signal?: AbortSignal): Promise<void> {
    const res = await this.fetchImpl(`${this.origin}/v1/blobs/${encodeURIComponent(sha256)}`, {
      method: 'PUT',
      headers: { ...this.auth(apiKey), 'content-type': mime || 'application/octet-stream' },
      body: data as BodyInit,
      signal: signal ?? null,
      timeoutMs: RELAY_IMAGE_TIMEOUT_MS,
    })
    if (!res.ok) await fail(res)
  }

  /**
   * `POST /v1/turns` (relay 0.29): a turn this computer ran on a key of its own, in the shape
   * the relay keeps; `device` rides as `X-NanoMuse-Device` and the platform as
   * `X-NanoMuse-Platform` (relay 0.31: Node's user agent says nothing of it). A relay that
   * keeps no record answers 404, which the caller treats as "not now".
   */
  async postTurn(apiKey: string, turn: Record<string, unknown>, device: string, signal?: AbortSignal): Promise<void> {
    const res = await this.fetchImpl(`${this.origin}/v1/turns`, {
      method: 'POST',
      headers: { ...this.auth(apiKey), ...JSON_HEADERS, ...this.where(device) },
      body: JSON.stringify(turn),
      signal: signal ?? null,
    })
    if (!res.ok) await fail(res)
  }

  /**
   * `POST /v1/events` (relay 0.31): what happened around turns, as codes and numbers
   * (docs/cloud.md "Client events"); at most 100 a request. The relay answers 202 with what
   * it kept and dropped; a 429 says the account sent too many requests this minute.
   */
  async postEvents(apiKey: string, events: Record<string, unknown>[], device: string, signal?: AbortSignal): Promise<{ kept: number; dropped: number }> {
    const res = await this.fetchImpl(`${this.origin}/v1/events`, {
      method: 'POST',
      headers: { ...this.auth(apiKey), ...JSON_HEADERS, ...this.where(device) },
      body: JSON.stringify({ events }),
      signal: signal ?? null,
    })
    if (!res.ok) await fail(res)
    const data = (await res.json().catch(() => ({}))) as { kept?: number; dropped?: number }
    return { kept: Number(data.kept ?? 0), dropped: Number(data.dropped ?? 0) }
  }

  /** The device and the platform, on what this computer sends up of its own accord. */
  private where(device: string): Record<string, string> {
    return { ...(device ? { 'x-nanomuse-device': device } : {}), 'x-nanomuse-platform': 'desktop' }
  }

  private auth(apiKey: string): Record<string, string> {
    return { authorization: `Bearer ${apiKey}` }
  }
}
