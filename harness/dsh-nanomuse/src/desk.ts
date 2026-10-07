/**
 * The desk behind the hands (0.1.34): the approvals and holds the chat's cards and
 * the capsule answer (shared contracts C1 and C2 of this release), what the account's
 * connectors look like to the other devices (C3), and the update check the
 * About row runs (nanomuse.cn/dl/index.json first, GitHub releases as the fallback).
 *
 * No Cordis here: `cloud.ts` owns the wiring, this file owns the shapes and
 * the decisions so the tests can drive them without a host.
 */
import type { ApprovalOutcome, ApprovalRequestEvent } from '@deepseek-ai/dsh-user-approval/types'

// ---- approvals (C2) ------------------------------------------------------------------

/** One question the agent asked before a step, as the chat's card and the capsule show it. */
export interface PendingApproval {
  id: string
  sessionId: string
  toolName: string
  /** What the agent wants to do, in the asker's words (English); `summaryZh` when it gave Chinese too. */
  summary: string
  summaryZh: string
  purpose: string
  status: 'pending'
  at: number
}

export type ApprovalScope = 'once' | 'conversation' | 'always'

/** A standing "always allow": the hands in one app (`computer_app:<app>`), given on a permission card, revocable on the Permissions page. */
export interface Grant {
  id: string
  /** `computer_app:Safari` — the kind and the app the card showed when it was given. */
  target: string
  at: number
}

/** The app of a window title as the hands report it (`Safari — Apple` → `Safari`). */
export function appOf(title: string): string {
  return title.split(/\s+[—–·|-]\s+/)[0]?.trim().slice(0, 60) ?? ''
}

// ---- standing grants, by risk tier (the Permissions page) ----------------------------

/**
 * The three tiers the phone's Permissions page groups remembered approvals under, in the
 * Sentinel's words: `highest` is what would otherwise ask every time (sensitive) and now runs
 * without asking; `confirm` is what was asked once on a card and remembered (moderate);
 * `notice` is what never asks and is told afterwards (safe). The desktop keeps nothing under
 * `notice` today; the tier is in the contract so a store that lands there has its place.
 */
export type GrantTier = 'highest' | 'confirm' | 'notice'

export const GRANT_TIERS: readonly GrantTier[] = ['highest', 'confirm', 'notice']

/**
 * One remembered permission on this computer, whatever store it lives in:
 * - `computer_app` — the hands in one app, from *Always in <app>* on a permission card (`Grant`);
 * - `device` — one device of the account may run things here without asking, from *always*
 *   on a remote-control card (the hub's trusted list);
 * - `remote_control` — the switch: every device of the account may, no questions asked.
 * `id` is what `POST /grants/revoke` takes for any of them.
 */
export interface StandingGrant {
  id: string
  kind: 'computer_app' | 'device' | 'remote_control'
  tier: GrantTier
  /** The app, the device's name, or '' for the switch. */
  target: string
  /** When it was given; 0 when the store does not say (the switch). */
  at: number
}

export const REMOTE_CONTROL_GRANT_ID = 'remote-control'
export const DEVICE_GRANT_PREFIX = 'device:'

/** Every remembered permission as one list: the hands' grants, the trusted devices, the remote-control switch. */
export function standingGrants(input: { grants?: readonly Grant[]; trusted?: readonly { id: string; name: string; at: number }[]; remoteControl?: boolean }): StandingGrant[] {
  const out: StandingGrant[] = []
  if (input.remoteControl === true) out.push({ id: REMOTE_CONTROL_GRANT_ID, kind: 'remote_control', tier: 'highest', target: '', at: 0 })
  for (const d of input.trusted ?? []) out.push({ id: `${DEVICE_GRANT_PREFIX}${d.id}`, kind: 'device', tier: 'confirm', target: d.name || d.id, at: d.at })
  for (const g of input.grants ?? []) out.push({ id: g.id, kind: 'computer_app', tier: 'confirm', target: g.target.replace(/^computer_app:/, ''), at: g.at })
  return out
}

/** The list by tier, highest first, newest first inside a tier; tiers with nothing in them are left out. */
export function groupGrants(list: readonly StandingGrant[]): { tier: GrantTier; grants: StandingGrant[] }[] {
  return GRANT_TIERS.map((tier) => ({ tier, grants: list.filter((g) => g.tier === tier).sort((a, b) => b.at - a.at) })).filter((group) => group.grants.length > 0)
}

/**
 * Give the listeners after us (the card in the chat, bridged to the client with the
 * request's `signal`) a signal the stage can abort: the request object is the asker's own
 * plain object, read by the bridge when the card is shown, so its `signal` is swapped for
 * the card's lifetime and put back after. The approval service read the asker's signal
 * before the waterfall began, so aborting the card's never turns the outcome into
 * `cancelled`. `undefined` when the request cannot be changed (then the card stays as before).
 */
export function cardSignal(req: ApprovalRequestEvent): { abort(reason: Error): void; release(): void } | undefined {
  const target = req as { signal?: AbortSignal }
  const own = Object.getOwnPropertyDescriptor(target, 'signal')
  if (Object.isFrozen(target) || (own && (!own.writable || !own.configurable))) return undefined
  const original = target.signal
  if (original?.aborted) return undefined
  const controller = new AbortController()
  const forward = () => controller.abort(original?.reason as Error | undefined)
  original?.addEventListener('abort', forward, { once: true })
  try {
    target.signal = controller.signal
  } catch {
    original?.removeEventListener('abort', forward)
    return undefined
  }
  return {
    abort: (reason) => controller.abort(reason),
    release: () => {
      original?.removeEventListener('abort', forward)
      if (original === undefined) delete target.signal
      else target.signal = original
    },
  }
}

/**
 * Approval requests pass the chat card *and* the stage: whichever answers first
 * wins, the other is let go. `handle` sits first in dsh's `approval/request`
 * waterfall; `next()` is the harness's own card in the chat.
 */
export class ApprovalDesk {
  private readonly pending = new Map<string, { row: PendingApproval; resolve(outcome: ApprovalOutcome): void }>()
  /** Session ids whose approvals belong elsewhere (a task from another device answers on that device). */
  private readonly skip = new Set<string>()

  /**
   * @param changed - called when the list moves.
   * @param granted - whether a standing grant covers the request (a hands step in an app allowed with "always").
   */
  constructor(
    private readonly changed: () => void,
    private readonly granted: (req: ApprovalRequestEvent) => boolean = () => false,
  ) {}

  list(): PendingApproval[] {
    return [...this.pending.values()].map((p) => p.row).sort((a, b) => a.at - b.at)
  }

  /** Approvals of this session are not the stage's business (the asker's device shows them). */
  exclude(sessionId: string, on = true): void {
    if (on) this.skip.add(sessionId)
    else this.skip.delete(sessionId)
  }

  async handle(req: ApprovalRequestEvent, next: () => Promise<ApprovalOutcome>): Promise<ApprovalOutcome> {
    const sessionId = req.agent.session.id
    if (this.skip.has(sessionId)) return next()
    if (this.granted(req)) return 'allowed-once'
    const id = String(req.callId ?? `ap-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`)
    const row: PendingApproval = {
      id,
      sessionId,
      toolName: req.toolName,
      summary: String(req.displayReason?.en ?? req.reason ?? '').trim().slice(0, 400),
      summaryZh: String(req.displayReason?.zh ?? req.displayReason?.['zh-CN'] ?? '').trim().slice(0, 400),
      purpose: String(req.reason ?? '').trim().slice(0, 400),
      status: 'pending',
      at: Date.now(),
    }
    let stageAnswered = false
    const fromStage = new Promise<ApprovalOutcome>((resolve) =>
      this.pending.set(id, {
        row,
        resolve: (outcome) => {
          stageAnswered = true
          resolve(outcome)
        },
      }),
    )
    const onAbort = () => this.settle(id, 'cancelled')
    req.signal?.addEventListener('abort', onAbort, { once: true })
    // The card in the chat follows a signal of its own: the stage's answer withdraws the card
    // (one decision, both surfaces), while the asker's signal still cancels both.
    const card = cardSignal(req)
    this.changed()
    try {
      return await Promise.race([next(), fromStage])
    } finally {
      req.signal?.removeEventListener('abort', onAbort)
      if (this.pending.delete(id)) this.changed()
      if (stageAnswered) card?.abort(new Error('answered on the stage'))
      card?.release()
    }
  }

  /** The stage's answer; false when the question is gone already. */
  decide(id: string, approved: boolean, _scope: ApprovalScope = 'once'): boolean {
    return this.settle(id, approved ? 'allowed-once' : 'rejected')
  }

  private settle(id: string, outcome: ApprovalOutcome): boolean {
    const p = this.pending.get(id)
    if (!p) return false
    this.pending.delete(id)
    p.resolve(outcome)
    this.changed()
    return true
  }
}

// ---- holds (C1) ---------------------------------------------------------------------

export type HoldTool = 'browser' | 'computer' | 'phone'

/** A pause of the hands: the person took over (`by: user`) or the agent asked them to (`by: agent`). */
export interface Hold {
  type: 'hold'
  id: string
  /** The session the hands belong to. */
  thread: string
  tool: HoldTool
  status: 'on' | 'off'
  by: 'user' | 'agent'
  reason: string
  ts: number
}

/** How long the hands wait for "Done" before they look at the screen anyway. */
export const HOLD_MAX_MS = 10 * 60_000

export class HoldDesk {
  private readonly holds = new Map<string, Hold>()
  private readonly waiters = new Map<string, Set<() => void>>()
  private seq = 0

  constructor(private readonly changed: () => void) {}

  /** The holds that are on, oldest first. */
  list(): Hold[] {
    return [...this.holds.values()].filter((h) => h.status === 'on').sort((a, b) => a.ts - b.ts)
  }

  /** The hold on `thread`, when there is one. */
  on(thread: string): Hold | undefined {
    return this.list().find((h) => h.thread === thread)
  }

  /** Start a hold; a second one on the same thread only refreshes the reason. */
  begin(thread: string, tool: HoldTool, by: Hold['by'], reason: string): Hold {
    const current = this.on(thread)
    if (current) {
      const next: Hold = { ...current, by, reason: reason || current.reason, ts: Date.now() }
      this.holds.set(next.id, next)
      this.changed()
      return next
    }
    const hold: Hold = { type: 'hold', id: `hold-${++this.seq}-${Date.now().toString(36)}`, thread, tool, status: 'on', by, reason: reason.slice(0, 200), ts: Date.now() }
    this.holds.set(hold.id, hold)
    this.changed()
    return hold
  }

  /** "Done": the hands may go on. False when no such hold is on. */
  done(id: string): boolean {
    const hold = this.holds.get(id)
    if (!hold || hold.status === 'off') return false
    this.holds.set(id, { ...hold, status: 'off', ts: Date.now() })
    const waiters = this.waiters.get(hold.thread)
    this.waiters.delete(hold.thread)
    for (const wake of waiters ?? []) wake()
    this.changed()
    // Off holds are kept a moment so a stage still showing them reads the status flip.
    setTimeout(() => {
      if (this.holds.get(id)?.status === 'off') this.holds.delete(id)
    }, 30_000).unref?.()
    return true
  }

  /**
   * Resolves once no hold is on for `thread`: at once when there is none, when the
   * person says Done, when `maxMs` pass, or when the call is aborted.
   */
  wait(thread: string, signal?: AbortSignal, maxMs = HOLD_MAX_MS): Promise<'clear' | 'done' | 'timeout' | 'aborted'> {
    if (!this.on(thread)) return Promise.resolve('clear')
    return new Promise((resolve) => {
      let timer: NodeJS.Timeout | undefined
      const finish = (how: 'done' | 'timeout' | 'aborted') => {
        if (timer) clearTimeout(timer)
        this.waiters.get(thread)?.delete(wake)
        signal?.removeEventListener('abort', onAbort)
        resolve(how)
      }
      const wake = () => finish('done')
      const onAbort = () => finish('aborted')
      const set = this.waiters.get(thread) ?? new Set<() => void>()
      set.add(wake)
      this.waiters.set(thread, set)
      signal?.addEventListener('abort', onAbort, { once: true })
      // Kept referenced on purpose: a waiting tool call must outlive an otherwise idle loop
      // (an unref'd timer let Node 22 end the loop with the promise still pending).
      timer = setTimeout(() => finish('timeout'), maxMs)
    })
  }
}

// ---- connectors shared across devices (C3) ------------------------------------------

/** A connection as the account's profile carries it: what it is and where, never how it signs in. */
export interface SharedConnector {
  id: string
  label: string
  url?: string
  auth: 'oauth' | 'key' | 'open'
  device: string
  device_id: string
  enabled: boolean
  /** ISO 8601. */
  at: string
}

/** Field names the relay refuses; kept here so a shape change is caught before the wire. */
const FORBIDDEN_FIELD = /token|secret|key|authorization|password/i

export const SHARED_CONNECTORS_CAP = 64

/** This device's connections as the profile should list them. */
export function sharedConnectors(
  connections: { service: string; id: string; label: string; url: string; auth: string; state: string; connectedAt: number; updatedAt: number }[],
  device: string,
  deviceId: string,
): SharedConnector[] {
  const rows = connections.slice(0, SHARED_CONNECTORS_CAP).map((c): SharedConnector => ({
    id: (c.service && c.service !== 'custom' ? c.service : c.id).slice(0, 64),
    label: c.label.slice(0, 80),
    ...(c.url ? { url: c.url.slice(0, 256) } : {}),
    auth: c.auth === 'oauth' ? 'oauth' : c.auth === 'none' ? 'open' : 'key',
    device: device.slice(0, 80),
    device_id: deviceId.slice(0, 80),
    enabled: c.state !== 'error',
    at: new Date(c.updatedAt || c.connectedAt || Date.now()).toISOString(),
  }))
  for (const row of rows) for (const field of Object.keys(row)) if (FORBIDDEN_FIELD.test(field)) throw new Error(`shared connector field "${field}" looks like a credential`)
  return rows
}

/** The relay's list as the browser should read it: well-formed rows only. */
export function readSharedConnectors(raw: unknown): SharedConnector[] {
  if (!Array.isArray(raw)) return []
  const out: SharedConnector[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const r = item as Record<string, unknown>
    const id = typeof r.id === 'string' ? r.id.slice(0, 64) : ''
    if (!id) continue
    const auth = r.auth === 'oauth' || r.auth === 'key' || r.auth === 'open' ? r.auth : 'open'
    out.push({
      id,
      label: typeof r.label === 'string' ? r.label.slice(0, 80) : id,
      ...(typeof r.url === 'string' && r.url ? { url: r.url.slice(0, 256) } : {}),
      auth,
      device: typeof r.device === 'string' ? r.device.slice(0, 80) : '',
      device_id: typeof r.device_id === 'string' ? r.device_id.slice(0, 80) : '',
      enabled: r.enabled !== false,
      at: typeof r.at === 'string' ? r.at : new Date(0).toISOString(),
    })
    if (out.length >= SHARED_CONNECTORS_CAP) break
  }
  return out
}

// ---- the update check (B5) ---------------------------------------------------------

export const RELEASES_API = 'https://api.github.com/repos/nano-muse/nanoMuse/releases/latest'
export const RELEASES_INDEX = 'https://nanomuse.cn/dl/index.json'
export const RELEASES_PAGE = 'https://github.com/nano-muse/nanoMuse/releases'

export interface ReleaseAsset {
  name: string
  url: string
  size: number
}

export interface UpdateInfo {
  /** What runs here. */
  current: string
  /** The newest release's version, `0.1.34`; empty when nothing could be read. */
  latest: string
  newer: boolean
  /** The release's page, for "What's new". */
  page: string
  assets: ReleaseAsset[]
  notes: string
  source: 'github' | 'nanomuse.cn' | 'none'
  checkedAt: number
  error?: string
}

/**
 * `-1`, `0` or `1` for `a` against `b`; `v` prefixes and pre-release tags (`-rc.1`) are read,
 * and so is a label in front of the number (`dsh-nanomuse 0.1.41`, `nanoMuse Desktop 0.1.41`):
 * the first dotted number in the string is the version.
 */
export function compareVersions(a: string, b: string): number {
  const parse = (v: string) => {
    const m = /(?:^|[^\d.])v?(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.-]+))?/.exec(v.trim())
    return { nums: (m?.[1] ?? '0').split('.').map((n) => Number(n) || 0), pre: m?.[2] ?? '' }
  }
  const x = parse(a)
  const y = parse(b)
  for (let i = 0; i < Math.max(x.nums.length, y.nums.length); i++) {
    const d = (x.nums[i] ?? 0) - (y.nums[i] ?? 0)
    if (d !== 0) return d < 0 ? -1 : 1
  }
  if (x.pre === y.pre) return 0
  if (!x.pre) return 1
  if (!y.pre) return -1
  return x.pre < y.pre ? -1 : 1
}

/** The desktop installer for this computer, when the release has one. */
export function pickAsset(assets: ReleaseAsset[], platform: string, arch: string): ReleaseAsset | undefined {
  const cpu = arch === 'arm64' ? 'arm64' : 'x64'
  const wanted: RegExp[] =
    platform === 'darwin'
      ? [new RegExp(`^nanoMuse-Desktop-.*-mac-${cpu}\\.dmg$`, 'i'), new RegExp(`^nanoMuse-Desktop-.*-mac-${cpu}\\.zip$`, 'i')]
      : platform === 'win32'
        ? [/^nanoMuse-Desktop-.*-win-x64\.exe$/i]
        : [new RegExp(`^nanoMuse-Desktop-.*-linux-${cpu}\\.AppImage$`, 'i'), new RegExp(`^nanoMuse-Desktop-.*-linux-${cpu}\\.deb$`, 'i')]
  for (const re of wanted) {
    const hit = assets.find((a) => re.test(a.name))
    if (hit) return hit
  }
  return undefined
}

type Fetch = (url: string, init?: { headers?: Record<string, string>; signal?: AbortSignal }) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>

/**
 * The latest release, from the mirror's index on nanomuse.cn first (reachable from the
 * mainland, no rate limit), then GitHub's API when the index does not answer. Each
 * request has 5 s (C2). Never throws: a failed check is an `UpdateInfo` with
 * `source: 'none'` and an `error`.
 */
export async function checkForUpdate(current: string, fetchImpl: Fetch = fetch as unknown as Fetch, timeoutMs = 5000): Promise<UpdateInfo> {
  const now = Date.now()
  const base: UpdateInfo = { current, latest: '', newer: false, page: RELEASES_PAGE, assets: [], notes: '', source: 'none', checkedAt: now }
  const errors: string[] = []
  const get = async (url: string): Promise<unknown> => {
    const ctl = new AbortController()
    const timer = setTimeout(() => ctl.abort(), timeoutMs)
    try {
      const res = await fetchImpl(url, { headers: { accept: 'application/json', 'user-agent': 'nanoMuse-Desktop' }, signal: ctl.signal })
      if (!res.ok) throw new Error(`${res.status}`)
      return await res.json()
    } finally {
      clearTimeout(timer)
    }
  }
  try {
    const index = (await get(RELEASES_INDEX)) as { repo?: string; releases?: { tag?: string; assets?: { name?: string; size?: number }[] }[] }
    const rel = (index.releases ?? []).find((r) => r.tag)
    const latest = String(rel?.tag ?? '').replace(/^v/, '')
    if (!rel || !latest) throw new Error('no release')
    const repo = index.repo || 'nano-muse/nanoMuse'
    return {
      ...base,
      latest,
      newer: compareVersions(latest, current) > 0,
      page: `https://github.com/${repo}/releases/tag/${rel.tag}`,
      assets: (rel.assets ?? []).flatMap((a) => (a.name ? [{ name: a.name, url: `https://github.com/${repo}/releases/download/${rel.tag}/${a.name}`, size: Number(a.size ?? 0) || 0 }] : [])),
      source: 'nanomuse.cn',
    }
  } catch (error: unknown) {
    errors.push(`nanomuse.cn: ${error instanceof Error ? error.message : String(error)}`)
  }
  try {
    const rel = (await get(RELEASES_API)) as { tag_name?: string; html_url?: string; body?: string; assets?: { name?: string; browser_download_url?: string; size?: number }[] }
    const latest = String(rel.tag_name ?? '').replace(/^v/, '')
    if (!latest) throw new Error('no tag')
    return {
      ...base,
      latest,
      newer: compareVersions(latest, current) > 0,
      page: rel.html_url || `${RELEASES_PAGE}/tag/v${latest}`,
      assets: (rel.assets ?? []).flatMap((a) => (a.name && a.browser_download_url ? [{ name: a.name, url: a.browser_download_url, size: Number(a.size ?? 0) || 0 }] : [])),
      notes: String(rel.body ?? '').slice(0, 4000),
      source: 'github',
    }
  } catch (error: unknown) {
    errors.push(`github: ${error instanceof Error ? error.message : String(error)}`)
  }
  return { ...base, error: errors.join('; ') }
}

// ---- models (C4) --------------------------------------------------------------------

/** What the relay says a model is for; absent on an older relay means chat. */
export function modelFor(m: { kind: string; for?: string[] }): ('chat' | 'gui')[] {
  const list = (m.for ?? []).filter((x): x is 'chat' | 'gui' => x === 'chat' || x === 'gui')
  return list.length ? list : m.kind === 'chat' ? ['chat'] : []
}

/** The chat model new sessions get: `deepseek-v4.1-flash` when the account has it, else the recommended one, else the first. */
export const DEFAULT_CHAT_MODEL = 'deepseek-v4.1-flash'
/** The model the hands see the screen with. */
export const DEFAULT_HANDS_MODEL = 'qwen3.8-27b'

export function pickChatModel<M extends { id: string; kind: string; for?: string[]; recommended?: boolean }>(models: M[]): M | undefined {
  const chat = models.filter((m) => modelFor(m).includes('chat'))
  return chat.find((m) => m.id === DEFAULT_CHAT_MODEL) ?? chat.find((m) => m.recommended) ?? chat[0]
}

export function pickHandsModel<M extends { id: string; kind: string; for?: string[]; recommended?: boolean }>(models: M[]): M | undefined {
  const gui = models.filter((m) => modelFor(m).includes('gui'))
  return gui.find((m) => m.id === DEFAULT_HANDS_MODEL) ?? gui.find((m) => m.recommended) ?? gui[0]
}

/**
 * Whether a chat model takes pictures. The relay's modalities decide, except for
 * DeepSeek: only the `v4.1`, `vision` and `ocr` ids are sighted, whatever the
 * list says (older relays marked every DeepSeek model as taking images).
 */
export function takesImages(m: { id: string; inputModalities?: string[] }): boolean {
  const id = m.id.toLowerCase()
  if (id.includes('deepseek')) return /v4\.1|vision|ocr/.test(id)
  return (m.inputModalities ?? []).includes('image')
}
