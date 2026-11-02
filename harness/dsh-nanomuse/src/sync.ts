/**
 * Conversations synced between the account's devices (contracts C7 and C8), the
 * desktop's half. The relay keeps the text of every conversation under `/v1/sync/*`;
 * this computer pushes the person's words the moment they are sent and the model's
 * final text when the turn ends, and pulls what the other devices pushed — on start,
 * on the hub's `sync` frame and every minute.
 *
 * **One thread** (C8). A conversation written on another device is not a mirror
 * beside the chats here: it *is* a chat here. The account's one main conversation
 * lives in the main chat of this computer (its id adopted from the relay when the
 * relay has one), and a side conversation pulled from the relay gets a dsh session
 * at once, with its title, so it continues here like any other chat and its turns
 * go up under the same conversation id. The turns written elsewhere are *kept* by the
 * host in a store of its own (`$DSH_HOME/nanomuse/sync-remote.json`) — never written
 * into the session's log: a `user/message` appended there outside a turn makes the log
 * unreadable once a turn runs, and the chat does not render such a row anyway — and the
 * browser half (`client/RemoteBubbles.ts`) shows them as the other device's bubbles,
 * "From Pixel 8" under each, placed by their time among the local turns. The model
 * hears them as context for its next step (`agent.inject`, a note per pull: "Meanwhile,
 * in this same conversation on another device…"), model-facing, never the person's
 * words, so never pushed back; a row from this device coming back on a pull is known
 * by its device and never kept twice.
 *
 * On sign-in and when the switch goes on the pull comes first (the relay's history
 * reaches the sessions here), then the whole eligible history of this computer goes
 * up, oldest first, 200 messages a POST.
 *
 * **Main first** (C9). Only the main conversation syncs unless this device's "Also sync
 * side chats" is on (`state.sideChats`): off, side chats are neither pushed nor pulled
 * (`scope=main`), and a side row that still arrives makes no session. The first pull of an
 * account asks for the newest 300 messages (`tail=300`); the switch going on pulls the
 * account's side chats the same way, once. While a turn runs here on a synced conversation
 * the relay is told (`POST /v1/sync/working`, best-effort), and the other devices' `working`
 * frames put a quiet "kwai is working…" line under their last prompt here (`workingOf`).
 *
 * **Whose conversations** (C10). Every mapping entry carries the `owner` — the `account.id` of
 * the account the session was first pushed to or pulled from; a conversation written while
 * signed out and never synced has none. Signed in as B, the column shows B's and the
 * ownerless (`view().foreign` names the rest, hidden, not deleted), the push loop takes B's
 * and the ownerless — which become B's on their first push — and never A's; a different
 * `account.id` than the last one starts the pull over (cursor 0) and drops what was pulled
 * for A (the relay's rows, the kept turns, presence), keeping A's mapping so switching back
 * works. Signed out, everything local is shown and nothing moves.
 *
 * Never a key in a log, never a file: attachments travel as names and sizes.
 */
import { createHash, randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { mkdir, rename, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'
import { RELAY_TIMEOUT_MS, RelayError, type TimedFetch, withTimeout } from './relay.ts'

declare module '@deepseek-ai/dsh-llm' {
  interface MessageSourceMap {
    /** A turn of this conversation written on another device of the account (C8). */
    'nanomuse-sync': { kind: 'nanomuse-sync'; role: 'user' | 'assistant'; mid: string; device: string; deviceName: string; at: number }
  }
}

/** The relay's limits (contract C7). */
export const MAX_POST_MESSAGES = 200
export const PUSH_DELAY_MS = 2000
/** The person's words go up this soon after they are sent (C8). */
export const SEND_DELAY_MS = 50
export const PULL_EVERY_MS = 60_000
export const PAGE = 500

const JSON_HEADERS = { 'content-type': 'application/json' }

export interface SyncRelayState {
  enabled: boolean
  cursor: number
  counts: { conversations: number; messages: number }
  /** Devices working on a conversation right now (C9), unexpired. */
  working: WireWorking[]
}

/** What a run is doing, as presence says it (relay 0.31): on a step, or parked on a card for the person. */
export type WorkingState = 'working' | 'waiting'

/** The hub's `working` frame and the rows of `/v1/sync/state`'s `working` (C9). */
export interface WireWorking {
  cid: string
  from: string
  device_name: string
  working: boolean
  /** Unix seconds, the relay's clock. */
  at: number
  /** On a `true`, since relay 0.31: what the run is doing; absent from older relays and devices. */
  state?: WorkingState
  /** The step's own words, at most `DETAIL_CAP` characters; '' when the run gave none. */
  detail?: string
}

/** The longest step presence carries (relay 0.31 cuts there too): one line under a bubble. */
export const DETAIL_CAP = 160
/** The quietest gap between two step posts of one run: a step that changes faster is told when the gap ends. */
export const STEP_GAP_MS = 2000

/** The newest messages a first pull asks for (C9): `since=0&tail=300`. */
export const TAIL = 300
/** A `working` presence is over this long after its `at` (C9). */
export const WORKING_TTL_MS = 10 * 60_000
/** The hub's `sync` frames arriving together become one pull. */
export const FRAME_COALESCE_MS = 1000

export interface WireConversation {
  cid: string
  kind: 'main' | 'side'
  title: string
  device: string
  device_name: string
  created_at: number
  updated_at: number
  deleted: boolean
  seq: number
}

export interface WireMessage {
  mid: string
  cid: string
  seq: number
  device: string
  device_name: string
  role: 'user' | 'assistant'
  text: string
  truncated: boolean
  created_at: number
  deleted: boolean
}

export interface SyncChanges {
  cursor: number
  more: boolean
  conversations: WireConversation[]
  messages: WireMessage[]
}

export interface PushResult {
  cursor: number
  accepted: number
  rejected: Array<{ cid?: string; mid?: string; reason: string; cid_main?: string }>
}

/** A message id stable across retries: the relay keeps a known mid out of the tables, so a line
 * whose answer was lost and is sent again must carry the mid it went up with, not a fresh one;
 * otherwise the same words land twice and every other device reads them twice. */
export function deriveMid(device: string, sessionId: string, lineId: string): string {
  return createHash('sha256').update(JSON.stringify([device, sessionId, lineId])).digest('hex').slice(0, 32)
}

/** Local line IDs can be reused by different session logs. */
export function lineKey(sessionId: string, lineId: string): string {
  return `line:${JSON.stringify([sessionId, lineId])}`
}

/** Relay calls have deadlines; tests supply a local fetch implementation. */
export class SyncRelay {
  readonly origin: string
  private readonly fetchImpl: TimedFetch

  constructor(origin: string, fetchImpl: typeof fetch = fetch, timeoutMs = RELAY_TIMEOUT_MS) {
    this.origin = origin.replace(/\/+$/, '')
    this.fetchImpl = withTimeout(fetchImpl, timeoutMs)
  }

  async state(apiKey: string): Promise<SyncRelayState> {
    const res = await this.fetchImpl(`${this.origin}/v1/sync/state`, { headers: this.auth(apiKey) })
    if (!res.ok) await fail(res)
    return toState(await res.json())
  }

  async setEnabled(apiKey: string, enabled: boolean): Promise<SyncRelayState> {
    const res = await this.fetchImpl(`${this.origin}/v1/sync/state`, { method: 'PUT', headers: { ...this.auth(apiKey), ...JSON_HEADERS }, body: JSON.stringify({ enabled }) })
    if (!res.ok) await fail(res)
    return toState(await res.json())
  }

  /**
   * The changes since a cursor (C7); `scope: 'main'` asks for the main conversation only, `tail`
   * (with `since=0`) for the newest `tail` messages of the scope and their conversations' rows (C9).
   */
  async changes(apiKey: string, since: number, limit = PAGE, scope: 'all' | 'main' = 'all', tail = 0): Promise<SyncChanges> {
    const query = `since=${since}&limit=${limit}${scope === 'main' ? '&scope=main' : ''}${tail > 0 && since === 0 ? `&tail=${tail}` : ''}`
    const res = await this.fetchImpl(`${this.origin}/v1/sync/changes?${query}`, { headers: this.auth(apiKey) })
    if (!res.ok) await fail(res)
    const body = (await res.json()) as Record<string, unknown>
    return {
      cursor: Number(body.cursor ?? since),
      more: body.more === true,
      conversations: Array.isArray(body.conversations) ? body.conversations.map(toConversation) : [],
      messages: Array.isArray(body.messages) ? body.messages.map(toMessage) : [],
    }
  }

  /**
   * Presence (C9): this device started or finished a turn on a conversation; a `true` may
   * say what the run is doing (`step`, relay 0.31: the state and the step's words — an older
   * relay ignores the two fields). Best-effort: the caller never retries.
   */
  async working(apiKey: string, device: string, cid: string, working: boolean, step?: { state: WorkingState; detail: string }): Promise<void> {
    const body: Record<string, unknown> = { cid, working, device }
    if (working && step) {
      body.state = step.state
      body.detail = step.detail.slice(0, DETAIL_CAP)
    }
    const res = await this.fetchImpl(`${this.origin}/v1/sync/working`, {
      method: 'POST',
      headers: { ...this.auth(apiKey), ...JSON_HEADERS },
      body: JSON.stringify(body),
    })
    if (!res.ok) await fail(res)
  }

  async push(apiKey: string, device: string, conversations: Record<string, unknown>[], messages: Record<string, unknown>[]): Promise<PushResult> {
    const res = await this.fetchImpl(`${this.origin}/v1/sync/changes`, {
      method: 'POST',
      headers: { ...this.auth(apiKey), ...JSON_HEADERS },
      body: JSON.stringify({ device, conversations, messages }),
    })
    if (!res.ok) await fail(res)
    const body = (await res.json()) as Record<string, unknown>
    return {
      cursor: Number(body.cursor ?? 0),
      accepted: Number(body.accepted ?? 0),
      rejected: Array.isArray(body.rejected) ? (body.rejected as PushResult['rejected']) : [],
    }
  }

  async deleteConversation(apiKey: string, cid: string, device: string): Promise<void> {
    const res = await this.fetchImpl(`${this.origin}/v1/sync/conversations/${encodeURIComponent(cid)}`, { method: 'DELETE', headers: { ...this.auth(apiKey), 'x-nanomuse-device': device } })
    if (!res.ok && res.status !== 404) await fail(res)
  }

  /** "Delete synced conversations": the store emptied, the switch kept. */
  async wipe(apiKey: string): Promise<SyncRelayState> {
    const res = await this.fetchImpl(`${this.origin}/v1/sync/changes`, { method: 'DELETE', headers: this.auth(apiKey) })
    if (!res.ok) await fail(res)
    return toState(await res.json())
  }

  private auth(apiKey: string): Record<string, string> {
    return { authorization: `Bearer ${apiKey}` }
  }
}

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

function toState(value: unknown): SyncRelayState {
  const b = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>
  const counts = (b.counts && typeof b.counts === 'object' ? b.counts : {}) as Record<string, unknown>
  return {
    enabled: b.enabled !== false,
    cursor: Number(b.cursor ?? 0),
    counts: { conversations: Number(counts.conversations ?? 0), messages: Number(counts.messages ?? 0) },
    working: Array.isArray(b.working) ? b.working.map((w) => toWorking(w, true)) : [],
  }
}

export function toWorking(value: unknown, working?: boolean): WireWorking {
  const w = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>
  const out: WireWorking = { cid: String(w.cid ?? ''), from: String(w.from ?? ''), device_name: String(w.device_name ?? ''), working: working ?? w.working === true, at: Number(w.at ?? 0) }
  // relay 0.31: what the run is doing; a frame without the two fields is plain working
  if (w.state === 'working' || w.state === 'waiting') out.state = w.state
  if (typeof w.detail === 'string' && w.detail) out.detail = w.detail.slice(0, DETAIL_CAP)
  return out
}

function toConversation(value: unknown): WireConversation {
  const c = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>
  return {
    cid: String(c.cid ?? ''),
    kind: c.kind === 'main' ? 'main' : 'side',
    title: String(c.title ?? ''),
    device: String(c.device ?? ''),
    device_name: String(c.device_name ?? ''),
    created_at: Number(c.created_at ?? 0),
    updated_at: Number(c.updated_at ?? 0),
    deleted: c.deleted === true,
    seq: Number(c.seq ?? 0),
  }
}

function toMessage(value: unknown): WireMessage {
  const m = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>
  return {
    mid: String(m.mid ?? ''),
    cid: String(m.cid ?? ''),
    seq: Number(m.seq ?? 0),
    device: String(m.device ?? ''),
    device_name: String(m.device_name ?? ''),
    role: m.role === 'assistant' ? 'assistant' : 'user',
    text: String(m.text ?? ''),
    truncated: m.truncated === true,
    created_at: Number(m.created_at ?? 0),
    deleted: m.deleted === true,
  }
}

// ---- the sessions, as the engine sees them -----------------------------------------------

/** One message of a dsh session the engine may sync: the person's prompt or the model's final text. */
export interface SessionLine {
  /** The dsh message id: stable, so a line is pushed once. */
  id: string
  role: 'user' | 'assistant'
  text: string
  /** Unix epoch milliseconds. */
  at: number
}

export interface SessionInfo {
  id: string
  title: string
  blank: boolean
  createdAt: number
  updatedAt: number
}

/** A turn of the conversation written on another device, as it goes into a session's log here (C8). */
export interface RemoteLine {
  mid: string
  role: 'user' | 'assistant'
  text: string
  /** Unix epoch milliseconds (the relay's `created_at`, in ms). */
  at: number
  /** Local wall-clock milliseconds when this computer kept the row, so skewed device clocks still anchor subsequent local prompts. */
  keptAt?: number
  device: string
  deviceName: string
}

/** The slice of the session API the engine uses; `cloud.ts` binds it to `ctx.sessionController`, tests fake it. */
export interface SyncSessions {
  list(): Promise<SessionInfo[]>
  /** The session's human prompts and final assistant texts, in order; [] for a session that cannot be read. */
  lines(sessionId: string): Promise<SessionLine[]>
  create(title: string): Promise<string>
  rename(sessionId: string, title: string): Promise<void>
  /**
   * A turn from another device, kept by the host for the transcript — in a store of its own,
   * never in the session's log: a surface message appended there outside a turn makes the log
   * unreadable once a turn runs ("system/message requires a protected first surface head").
   */
  keep(sessionId: string, line: RemoteLine): Promise<void>
  /** A kept turn deleted elsewhere. */
  forget(sessionId: string, mid: string): Promise<void>
  /** Every kept turn dropped (C10: another account signed in). */
  forgetAll?(): Promise<void>
  /** Model-facing context for the session's next step (`agent.inject`): what the other devices said; never shown as the person's words. */
  inject(sessionId: string, text: string): Promise<void>
}

/**
 * The other devices' turns, kept by session for the transcript: one JSON file, read once,
 * written whole after each change (coalesced, atomically — a temp file renamed over). A
 * line is kept once (by `mid`), in time order.
 */
export class RemoteStore {
  private lines = new Map<string, RemoteLine[]>()
  private loaded = false
  private timer: ReturnType<typeof setTimeout> | undefined
  private writing: Promise<void> = Promise.resolve()

  constructor(
    private readonly path: string,
    private readonly onError: (error: unknown) => void = () => undefined,
  ) {}

  private load(): void {
    if (this.loaded) return
    this.loaded = true
    try {
      const raw = JSON.parse(readFileSync(this.path, 'utf8')) as Record<string, RemoteLine[]>
      for (const [sessionId, lines] of Object.entries(raw)) if (Array.isArray(lines)) this.lines.set(sessionId, lines)
    } catch {
      // no store yet
    }
  }

  linesOf(sessionId: string): RemoteLine[] {
    this.load()
    return [...(this.lines.get(sessionId) ?? [])]
  }

  add(sessionId: string, line: RemoteLine): void {
    this.load()
    const list = this.lines.get(sessionId) ?? []
    if (list.some((l) => l.mid === line.mid)) return
    list.push(line.keptAt !== undefined ? line : { ...line, keptAt: Date.now() })
    list.sort((a, b) => a.at - b.at)
    this.lines.set(sessionId, list)
    this.saveSoon()
  }

  remove(sessionId: string, mid: string): void {
    this.load()
    const list = this.lines.get(sessionId)
    if (!list) return
    const next = list.filter((l) => l.mid !== mid)
    if (next.length === list.length) return
    if (next.length === 0) this.lines.delete(sessionId)
    else this.lines.set(sessionId, next)
    this.saveSoon()
  }

  private saveSoon(): void {
    if (this.timer) return
    this.timer = setTimeout(() => {
      this.timer = undefined
      this.writing = this.writing.then(() => this.write()).catch(this.onError)
    }, 200)
    this.timer.unref?.()
  }

  private async write(): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true })
    const tmp = `${this.path}.${process.pid}.tmp`
    await writeFile(tmp, JSON.stringify(Object.fromEntries(this.lines)) + '\n', { mode: 0o600 })
    await rename(tmp, this.path)
  }

  /** Everything forgotten (C10: another account signed in; its turns are pulled afresh). */
  clear(): void {
    this.load()
    if (this.lines.size === 0) return
    this.lines.clear()
    this.saveSoon()
  }

  /** Written now (the host stopping). */
  async flush(): Promise<void> {
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = undefined
      this.writing = this.writing.then(() => this.write()).catch(this.onError)
    }
    await this.writing
  }
}

/** The note that hands the model what the other devices added to a conversation that lives in a session here. */
export function meanwhileNote(lines: RemoteLine[]): string {
  const MAX_LINES = 40
  const MAX_CHARS = 12_000
  const recent = lines.slice(-MAX_LINES)
  const rows: string[] = []
  let size = 0
  for (const l of [...recent].reverse()) {
    const row = `${l.role === 'user' ? 'Person' : 'Muse'}${l.deviceName ? ` (on ${l.deviceName})` : ''}: ${l.text}`
    if (size + row.length > MAX_CHARS && rows.length > 0) break
    rows.unshift(row)
    size += row.length
  }
  const omitted = lines.length - rows.length
  return `[Meanwhile, in this same conversation on another device of the account${omitted > 0 ? ` (${omitted} earlier turn${omitted === 1 ? '' : 's'} not shown)` : ''}:]\n${rows.join('\n')}`
}

// ---- state --------------------------------------------------------------------------------

/** A conversation as the relay lists it, kept so a late session, a rename or a tombstone finds it. */
export interface KnownConversation {
  kind: 'main' | 'side'
  title: string
  device: string
  deviceName: string
  /** Unix seconds, the relay's clock. */
  createdAt: number
  updatedAt: number
}

export interface SyncState {
  /** The last signed-in account (`/v1/me` → `account.id`, opaque); kept through a sign-out so a change is known (C10). */
  accountId: string
  cursor: number
  enabled: boolean
  /** The session that is the main chat here: the account's one main conversation. */
  mainSession: string
  /** "Also sync side chats" (C9), per device, off by default: off → only the main conversation goes up and comes down. */
  sideChats: boolean
  /** dsh session id → conversation id. */
  cids: Record<string, string>
  /** dsh session id → the account it was first pushed to or pulled from (C10); absent = never synced. */
  owners: Record<string, string>
  /** Session-scoped local line key to uploaded mid; legacy bare message IDs remain readable. */
  mids: Record<string, string>
  /** session id → the title last pushed (or pulled: not pushed back). */
  titles: Record<string, string>
  /** cid → what the relay says of the conversation. */
  conversations: Record<string, KnownConversation>
  /** mid → the session it was appended to: a row goes into a log once. */
  pulled: Record<string, string>
  /** Rows deleted elsewhere after they were appended here: a log forgets nothing, the browser half hides them. */
  hidden: string[]
  /** Sessions whose conversation was deleted elsewhere: the browser half archives them (the host has no archive) and reports back. */
  toArchive: string[]
  /** 0.1.36 kept the other devices' chats as mirrors; a state that still has them is migrated (`migrate`). */
  mirrors?: Record<string, unknown>
}

export function emptyState(): SyncState {
  return { accountId: '', cursor: 0, enabled: true, mainSession: '', sideChats: false, cids: {}, owners: {}, mids: {}, titles: {}, conversations: {}, pulled: {}, hidden: [], toArchive: [] }
}

/**
 * A 0.1.36 state (mirrors, no `conversations`) starts the pull over from zero: what the
 * mirrors held becomes sessions and log rows on that pull; the ids of what this device
 * pushed stay, so nothing goes up twice, and our own rows coming back are known by device.
 * A 0.1.38 state (no `owners`) gives every mapped session to the account it was synced with
 * (C10): a mapping exists only because the session was pushed to or pulled from that account.
 */
export function migrate(state: SyncState | undefined): SyncState {
  if (!state) return emptyState()
  const next: SyncState = { ...emptyState(), ...state, sideChats: state.sideChats === true, owners: { ...(state.owners ?? {}) } }
  if ('mirrors' in next || !state.conversations) {
    delete next.mirrors
    next.cursor = 0
    next.conversations = {}
    next.pulled = {}
    next.hidden = []
    next.toArchive = []
  }
  if (!state.owners && state.accountId) {
    for (const sessionId of Object.keys(next.cids)) next.owners[sessionId] = state.accountId
  }
  return next
}

/**
 * The account-scoped part of a state, started over for another account (C10, rule 4): the
 * cursor at 0 (a fresh `tail=300` pull), the relay's rows and what was pulled forgotten, the
 * mapping — every account's — kept; a main chat that belongs to another account is no
 * longer the main chat here.
 */
export function forAccount(state: SyncState, accountId: string): SyncState {
  const next: SyncState = { ...state, accountId, cursor: 0, conversations: {}, pulled: {}, hidden: [], toArchive: [] }
  const mainOwner = state.owners[state.mainSession]
  if (mainOwner && mainOwner !== accountId) next.mainSession = ''
  return next
}

export interface SyncEngineOptions {
  relay: SyncRelay
  sessions: SyncSessions
  /** The account key when signed in; nothing when not. */
  token(): Promise<string | undefined>
  deviceId(): string
  /** Sessions that are another device's tasks (`task.ts`) are not synced: they are that device's conversation. */
  isTaskSession?(sessionId: string): boolean
  /** A chat the rooms ran for themselves (the feed's daily batch): the agent's workbench, never synced. */
  isBatchSession?(sessionId: string): boolean
  load(): SyncState | undefined
  save(state: SyncState): Promise<void>
  /** The view changed: tell the browser half. */
  onChange?(): void
  log?(level: 'info' | 'warn' | 'debug', text: string): void
  pushDelayMs?: number
  pullEveryMs?: number
  frameCoalesceMs?: number
  /** The quietest gap between two step posts of one run (0.31); `STEP_GAP_MS` unless a test shortens it. */
  stepGapMs?: number
}

/** What the browser half reads: Data controls, the chats column and the bubbles from elsewhere. */
export interface SyncView {
  enabled: boolean
  /** "Also sync side chats" (C9), this device's setting. */
  sideChats: boolean
  available: boolean
  paused: boolean
  cursor: number
  relay: SyncRelayState | null
  /** Grows with every change applied here; the browser half re-reads a session's remote rows when it moves. */
  rev: number
  /** The session that holds the account's main conversation ('' before the chats column named one). */
  mainSession: string
  /** Sessions that hold a synced conversation: listed in the chats column even before a turn ran here. */
  sessions: string[]
  /** Sessions that belong to another account than the one signed in (C10): hidden by the browser half, not deleted; empty when signed out. */
  foreign: string[]
  /** mids of rows deleted elsewhere: hidden in the transcript. */
  hidden: string[]
  /** Sessions whose conversation was deleted elsewhere: to be archived by the browser half. */
  toArchive: string[]
}

/** Another device working on a conversation that lives in a session here (C9), for the browser half's line. */
export interface WorkingPresence {
  from: string
  deviceName: string
  /** Unix epoch milliseconds. */
  at: number
  /** What its run is doing (relay 0.31): `working` when the frame did not say. */
  state: WorkingState
  /** The step's own words; '' when the run gave none (an older device, or the model writing its answer). */
  detail: string
}

/** The step a run here last told the relay, per session (0.31). */
interface StepPost {
  state: WorkingState
  detail: string
  /** `state\ndetail` as last posted; '' before the first post of the turn. */
  sent: string
  sentAt: number
  timer: ReturnType<typeof setTimeout> | undefined
}

export class SyncEngine {
  state: SyncState
  private paused = false
  private pushTimer: ReturnType<typeof setTimeout> | undefined
  private pullTimer: ReturnType<typeof setInterval> | undefined
  private frameTimer: ReturnType<typeof setTimeout> | undefined
  private workingTimer: ReturnType<typeof setTimeout> | undefined
  private readonly dirty = new Set<string>()
  /** Sessions whose turn started (true) or ended (false) here, told to the relay after the push (C9). */
  private readonly presence = new Map<string, boolean>()
  /** cid → the other device working on it (C9). */
  private readonly working = new Map<string, WorkingPresence>()
  /** Sessions whose turn is running here (a `true` went or is going up): the ones whose steps are told (0.31). */
  private readonly running = new Set<string>()
  /** The step last told per running session (0.31). */
  private readonly steps = new Map<string, StepPost>()
  private pulling: Promise<number> | undefined
  private pushing: Promise<void> | undefined
  private frameCursor = 0
  private frameNeedsPull = false
  private relayState: SyncRelayState | null = null
  private lastError = ''
  private rev = 0
  /** Signed in, as the host last said (`start` / `accountChanged` vs `signedOut`); decides whether another account's sessions are hidden (C10). */
  private signedIn = false

  constructor(private readonly options: SyncEngineOptions) {
    this.state = migrate(options.load())
  }

  get enabled(): boolean {
    return this.state.enabled
  }

  /** On, signed in, and the key not refused. */
  async active(): Promise<boolean> {
    return this.state.enabled && !this.paused && Boolean(await this.options.token())
  }

  view(): SyncView {
    return {
      enabled: this.state.enabled,
      sideChats: this.state.sideChats,
      available: !this.paused && Boolean(this.state.accountId),
      paused: this.paused,
      cursor: this.state.cursor,
      relay: this.relayState,
      rev: this.rev,
      mainSession: this.state.mainSession,
      sessions: Object.keys(this.state.cids).filter((sid) => this.owns(sid)),
      foreign: this.foreign(),
      hidden: [...this.state.hidden],
      toArchive: [...this.state.toArchive],
    }
  }

  /** The conversation id a session syncs under, when it has one. */
  cidOf(sessionId: string): string | undefined {
    return this.state.cids[sessionId]
  }

  /**
   * Whether a session is the signed-in account's or nobody's yet (C10): what is shown, pushed
   * and dressed with the other devices' turns. Signed out, every session is.
   */
  owns(sessionId: string): boolean {
    if (!this.signedIn || !this.state.accountId) return true
    const owner = this.state.owners[sessionId]
    return !owner || owner === this.state.accountId
  }

  /** The sessions another account owns, while signed in (C10): hidden, not deleted. */
  private foreign(): string[] {
    if (!this.signedIn || !this.state.accountId) return []
    return Object.entries(this.state.owners).filter(([, owner]) => owner !== this.state.accountId).map(([sid]) => sid)
  }

  /** The session joins the signed-in account (C10): on its first push, or when a pull gives it a conversation. */
  private adopt(sessionId: string): void {
    if (this.state.accountId && !this.state.owners[sessionId]) this.state.owners[sessionId] = this.state.accountId
  }

  // ---- lifecycle ----------------------------------------------------------------------------

  start(): void {
    this.signedIn = true
    this.pullTimer ??= setInterval(() => void this.pullQuietly(), this.options.pullEveryMs ?? PULL_EVERY_MS)
    // pull first: the relay's history reaches the sessions here before ours goes up
    void this.pullQuietly().then(() => this.pushAllSoon())
  }

  stop(): void {
    if (this.pullTimer) clearInterval(this.pullTimer)
    this.pullTimer = undefined
    if (this.pushTimer) clearTimeout(this.pushTimer)
    this.pushTimer = undefined
    if (this.frameTimer) clearTimeout(this.frameTimer)
    this.frameTimer = undefined
    if (this.workingTimer) clearTimeout(this.workingTimer)
    this.workingTimer = undefined
    for (const sid of this.steps.keys()) this.forgetStep(sid)
    this.running.clear()
  }

  /**
   * A sign-in (C10). A different account than the last one starts from cursor 0 — the
   * relay's rows, the kept turns and the presence of the last account are dropped, every
   * account's mapping is kept — and whatever this does to the view is told. The same
   * account again (or a first sign-in) changes nothing but the pull that follows.
   */
  async accountChanged(accountId: string): Promise<void> {
    this.paused = false
    this.signedIn = true
    // a different account than the one this device last synced with (the first sign-in ever is not a switch)
    const changed = Boolean(accountId) && Boolean(this.state.accountId) && accountId !== this.state.accountId
    if (changed) {
      this.state = forAccount(this.state, accountId)
      this.working.clear()
      this.presence.clear()
      this.relayState = null
      await this.options.sessions.forgetAll?.().catch(() => undefined)
      await this.save()
      this.log('info', 'nanomuse sync: another account signed in; its conversations are pulled afresh, the last account’s stay hidden')
    } else if (accountId && !this.state.accountId) {
      this.state.accountId = accountId
      await this.save()
    }
    if (changed) this.changed()
    // the pull from zero follows, on its own tick, so the reset state is what a caller sees first
    const timer = setTimeout(() => void this.pullQuietly().then(() => this.pushAllSoon()), 0)
    timer.unref?.()
  }

  /** A sign-out: nothing is dropped (the account is remembered, so a different one next is known); every local chat shows. */
  signedOut(): void {
    this.paused = false
    this.signedIn = false
    this.relayState = null
    this.working.clear()
    this.presence.clear()
    this.changed()
  }

  /**
   * The chats column's main chat. While the account's main conversation already lives in a
   * session here, that session stays the main chat (one thread, C8): the id of the one it
   * lives in comes back for the column to adopt. Otherwise the session becomes the main chat
   * and takes the relay's main conversation id when the relay has one. A session of another
   * account cannot become the main chat (C10).
   */
  async setMain(sessionId: string): Promise<string> {
    const current = this.state.mainSession
    if (!sessionId || current === sessionId) return current
    if (!this.owns(sessionId)) return current
    if (current && this.holdsMain(current)) return current
    this.state.mainSession = sessionId
    const mainCid = this.mainCid()
    if (mainCid && !this.state.cids[sessionId]) {
      this.state.cids[sessionId] = mainCid
      this.adopt(sessionId)
      this.state.titles[sessionId] = this.state.conversations[mainCid]?.title ?? ''
    } else {
      delete this.state.titles[sessionId]
    }
    await this.save()
    this.dirty.add(sessionId)
    this.pushSoon(200)
    this.changed()
    return sessionId
  }

  /** The browser half archived the sessions whose conversations were deleted elsewhere. */
  async archived(sessionIds: string[]): Promise<void> {
    const done = new Set(sessionIds)
    this.state.toArchive = this.state.toArchive.filter((id) => !done.has(id))
    await this.save()
    this.changed()
  }

  private holdsMain(sessionId: string): boolean {
    const cid = this.state.cids[sessionId]
    return Boolean(cid && this.state.conversations[cid]?.kind === 'main')
  }

  private mainCid(): string | undefined {
    for (const [cid, c] of Object.entries(this.state.conversations)) if (c.kind === 'main') return cid
    return undefined
  }

  // ---- the switch ---------------------------------------------------------------------------

  async setEnabled(enabled: boolean): Promise<SyncView> {
    const token = await this.options.token()
    if (token) {
      try {
        this.relayState = await this.options.relay.setEnabled(token, enabled)
      } catch (error: unknown) {
        this.noteError(error)
        throw error
      }
    }
    this.state.enabled = enabled
    if (enabled) {
      this.paused = false
      // on again: this device's conversations go up in full — the signed-in account's and the
      // ownerless; another account's lines keep their ids (its relay store was not emptied, C10)
      const keep = new Set<string>()
      for (const sid of this.foreign()) for (const line of await this.options.sessions.lines(sid).catch(() => [] as SessionLine[])) {
        keep.add(line.id) // Preserve mappings written by earlier versions.
        keep.add(lineKey(sid, line.id))
      }
      this.state.titles = Object.fromEntries(Object.entries(this.state.titles).filter(([sid]) => !this.owns(sid)))
      this.state.mids = Object.fromEntries(Object.entries(this.state.mids).filter(([id]) => keep.has(id)))
    }
    await this.save()
    if (enabled) void this.pullQuietly().then(() => this.pushAllSoon())
    this.changed()
    return this.view()
  }

  /**
   * "Also sync side chats" (C9), this device's setting. On: the side chats here go up (oldest
   * first, as the history did) after one pull of the account's newest side turns
   * (`since=0&scope=all&tail=300`, idempotent by mid and cid). Off: side chats stop going
   * up and coming down; what was synced stays where it is.
   */
  async setSideChats(on: boolean): Promise<SyncView> {
    if (on === this.state.sideChats) return this.view()
    this.state.sideChats = on
    await this.save()
    if (on) void this.pullTail().then(() => this.pushAllSoon())
    this.changed()
    return this.view()
  }

  async relayStatus(): Promise<SyncRelayState | null> {
    const token = await this.options.token()
    if (!token) return (this.relayState = null)
    try {
      this.relayState = await this.options.relay.state(token)
      for (const w of this.relayState.working) this.noteWorking(w, false)
      this.expireWorking()
    } catch (error: unknown) {
      this.noteError(error)
    }
    return this.relayState
  }

  // ---- presence (C9) ------------------------------------------------------------------------

  /** The hub's `working` frame: another device started or finished a turn on a conversation. */
  onWorking(frame: WireWorking): void {
    if (this.noteWorking(frame, true)) this.changed()
  }

  /** The other device working on the conversation that lives in a session here, if any (and not 10 minutes old); never for another account's session (C10). */
  workingOf(sessionId: string): WorkingPresence | null {
    this.expireWorking()
    if (!this.owns(sessionId)) return null
    const cid = this.state.cids[sessionId]
    return (cid && this.working.get(cid)) || null
  }

  /** Whether the line the browser half shows moved. */
  private noteWorking(w: WireWorking, tell: boolean): boolean {
    if (!w.cid || w.from === this.options.deviceId()) return false
    const at = w.at * 1000
    if (!w.working || Date.now() - at >= WORKING_TTL_MS) {
      // an end frame takes away only the line its own device put up, and only when it is
      // not older than the line: a late end of an earlier turn must not cut a newer one
      const known = this.working.get(w.cid)
      if (!known || known.from !== w.from || known.at > at) return false
      return this.working.delete(w.cid)
    }
    const state: WorkingState = w.state ?? 'working'
    const detail = w.detail ?? ''
    const known = this.working.get(w.cid)
    // the relay's clock is in seconds: two steps within one second are not the same frame
    if (known && known.from === w.from && (known.at > at || (known.at === at && known.state === state && known.detail === detail))) return false
    this.working.set(w.cid, { from: w.from, deviceName: w.device_name, at, state, detail })
    this.armWorkingTimer()
    return tell
  }

  /** Each line goes away by itself 10 minutes after its last `at`: the one timer is set for
   * the earliest of them, and re-armed for the next when it fires, so a line of one
   * conversation is not kept up by a later frame of another. */
  private armWorkingTimer(): void {
    if (this.workingTimer) clearTimeout(this.workingTimer)
    this.workingTimer = undefined
    let earliest = Infinity
    for (const w of this.working.values()) earliest = Math.min(earliest, w.at)
    if (earliest === Infinity) return
    this.workingTimer = setTimeout(() => {
      this.workingTimer = undefined
      if (this.expireWorking()) this.changed()
      this.armWorkingTimer()
    }, Math.max(0, earliest + WORKING_TTL_MS - Date.now()) + 50)
  }

  private expireWorking(): boolean {
    let dropped = false
    for (const [cid, w] of this.working) {
      if (Date.now() - w.at >= WORKING_TTL_MS) {
        this.working.delete(cid)
        dropped = true
      }
    }
    return dropped
  }

  /** Told to the relay after the push: best-effort, once, never blocking (C9). */
  private tellWorking(token: string, sessionId: string): void {
    const working = this.presence.get(sessionId)
    this.presence.delete(sessionId)
    if (working === undefined || !this.syncs(sessionId)) return
    const cid = this.state.cids[sessionId]
    if (cid) void this.options.relay.working(token, this.options.deviceId(), cid, working).catch(() => undefined)
  }

  /** "Delete synced conversations": the relay's store emptied; what it knew is forgotten here, the sessions stay. */
  async deleteRemote(): Promise<SyncView> {
    const token = await this.options.token()
    if (token) {
      this.relayState = await this.options.relay.wipe(token)
      this.state.cursor = this.relayState.cursor
    }
    this.state.conversations = {}
    this.state.mids = {}
    this.state.titles = {}
    await this.save()
    this.changed()
    return this.view()
  }

  // ---- hooks --------------------------------------------------------------------------------

  /** The person sent a message in a session here: it goes up now (C8), not when the turn ends. */
  messageSent(sessionId: string): void {
    if (!this.syncs(sessionId)) return
    this.dirty.add(sessionId)
    this.presence.set(sessionId, true)
    this.running.add(sessionId)
    this.forgetStep(sessionId)
    this.pushSoon(Math.min(SEND_DELAY_MS, this.options.pushDelayMs ?? PUSH_DELAY_MS))
    // a new prompt here is a new anchor for the other devices' bubbles: the browser half re-reads them
    if (this.kept(sessionId)) this.changed()
  }

  /** Whether a session shows turns from the other devices (a pulled row, or one hidden). */
  private kept(sessionId: string): boolean {
    return Object.values(this.state.pulled).includes(sessionId)
  }

  /** Whether a session's turns go up: not another device's task, not a batch of the rooms', not another account's (C10), and a side chat only when the switch is on (C9). */
  private syncs(sessionId: string): boolean {
    if (this.options.isTaskSession?.(sessionId)) return false
    if (this.options.isBatchSession?.(sessionId)) return false
    if (!this.owns(sessionId)) return false
    return this.state.sideChats || sessionId === this.state.mainSession
  }

  /** A turn ended in a session here: the model's final text goes up after the debounce. */
  turnEnded(sessionId: string): void {
    this.running.delete(sessionId)
    this.forgetStep(sessionId)
    if (!this.syncs(sessionId)) return
    this.dirty.add(sessionId)
    this.presence.set(sessionId, false)
    this.pushSoon(this.options.pushDelayMs ?? PUSH_DELAY_MS)
  }

  /**
   * The run's step moved (0.31): the other devices hear what it is doing — `working` with
   * the step's words (a tool call), `working` with none (the model writing), `waiting`
   * while a card holds the run for the person. Only for a turn running here in a synced
   * session; at most one post per `STEP_GAP_MS` per session, the latest change going when
   * the gap ends; the same state and words twice are told once. Best-effort, like the
   * start and the end.
   */
  step(sessionId: string, state: WorkingState, detail: string): void {
    if (!this.running.has(sessionId) || !this.syncs(sessionId)) return
    const words = detail.replace(/\s+/g, ' ').trim().slice(0, DETAIL_CAP)
    const post = this.steps.get(sessionId) ?? { state, detail: words, sent: '', sentAt: 0, timer: undefined }
    post.state = state
    post.detail = words
    this.steps.set(sessionId, post)
    if (post.sent === `${state}\n${words}`) return
    const wait = post.sentAt + (this.options.stepGapMs ?? STEP_GAP_MS) - Date.now()
    if (wait > 0) {
      if (!post.timer) {
        post.timer = setTimeout(() => {
          post.timer = undefined
          this.postStep(sessionId)
        }, wait)
      }
      return
    }
    this.postStep(sessionId)
  }

  private postStep(sessionId: string): void {
    const post = this.steps.get(sessionId)
    const cid = this.state.cids[sessionId]
    if (!post || !cid || !this.running.has(sessionId)) return
    const key = `${post.state}\n${post.detail}`
    if (post.sent === key) return
    post.sent = key
    post.sentAt = Date.now()
    void this.options
      .token()
      .then((token) => (token ? this.options.relay.working(token, this.options.deviceId(), cid, true, { state: post.state, detail: post.detail }) : undefined))
      .catch(() => undefined)
  }

  private forgetStep(sessionId: string): void {
    const post = this.steps.get(sessionId)
    if (post?.timer) clearTimeout(post.timer)
    this.steps.delete(sessionId)
  }

  sessionRenamed(sessionId: string): void {
    if (!this.syncs(sessionId)) return
    this.dirty.add(sessionId)
    this.pushSoon(200)
  }

  /** The relay's `sync` frame: another device pushed. Frames arriving together become one pull, and a frame arriving during an in-flight pull runs a follow-up pull when needed. */
  onFrame(frame: { cursor?: number; from?: string }): void {
    if (frame.from && frame.from === this.options.deviceId()) return
    if (typeof frame.cursor === 'number') {
      if (frame.cursor <= this.state.cursor) return
      if (frame.cursor > this.frameCursor) this.frameCursor = frame.cursor
    } else {
      this.frameNeedsPull = true
    }
    if (this.frameTimer) return
    this.frameTimer = setTimeout(() => {
      this.frameTimer = undefined
      this.drainFramePull()
    }, this.options.frameCoalesceMs ?? FRAME_COALESCE_MS)
  }

  private drainFramePull(): void {
    if (this.pulling) {
      void this.pulling.finally(() => {
        if (this.frameNeedsPull || this.frameCursor > this.state.cursor) {
          this.frameNeedsPull = false
          void this.pull().catch(() => 0)
        }
      })
      return
    }
    this.frameNeedsPull = false
    void this.pullQuietly()
  }

  // ---- push ---------------------------------------------------------------------------------

  private pushSoon(delayMs: number): void {
    if (this.pushTimer) clearTimeout(this.pushTimer)
    this.pushTimer = setTimeout(() => {
      this.pushTimer = undefined
      void this.push().catch(() => undefined)
    }, delayMs)
  }

  /** Every session that is not a task: on start and when the switch goes on. */
  private pushAllSoon(): void {
    void this.options.sessions
      .list()
      .then((sessions) => {
        for (const s of sessions) if (!s.blank && this.syncs(s.id)) this.dirty.add(s.id)
        this.pushSoon(this.options.pushDelayMs ?? PUSH_DELAY_MS)
      })
      .catch(() => undefined)
  }

  /** The dirty sessions' new lines to the relay, oldest session first, one POST of up to 200 messages at a time; one push at a time. */
  push(): Promise<void> {
    const run = (): Promise<void> => {
      const p = this.pushNow()
        .catch((error: unknown) => {
          this.noteError(error)
          throw error
        })
        .finally(() => {
          if (this.pushing === p) this.pushing = undefined
        })
      this.pushing = p
      return p
    }
    return this.pushing ? this.pushing.then(run, run) : run()
  }

  private async pushNow(): Promise<void> {
    if (!(await this.active())) return
    const token = await this.options.token()
    if (!token) return
    const device = this.options.deviceId()
    const sessions = new Map((await this.options.sessions.list()).map((s) => [s.id, s]))
    // oldest first: a history going up in full arrives in the order it was lived
    const ids = [...this.dirty].sort((a, b) => (sessions.get(a)?.createdAt ?? 0) - (sessions.get(b)?.createdAt ?? 0))
    this.dirty.clear()
    try {
      await this.pushRounds(token, device, sessions, ids)
    } finally {
      // what a failed round (the network, the relay) did not take stays dirty for the next push
      for (const sid of ids) this.dirty.add(sid)
    }
    if (ids.length > 0) {
      // a very long history: the rest goes after the next debounce
      this.pushSoon(this.options.pushDelayMs ?? PUSH_DELAY_MS)
    }
    // our rows come back on the next pull (known by device, no change) and the cursor catches up
    void this.pullQuietly()
  }

  /** The rounds of one push; `ids` is left holding the sessions that still have lines to send. */
  private async pushRounds(token: string, device: string, sessions: Map<string, SessionInfo>, ids: string[]): Promise<void> {
    // a round the relay refused as too large (413) is tried again with half the messages; a single
    // message it refuses is marked refused and not sent again
    let batch = MAX_POST_MESSAGES
    for (let round = 0; round < 50 && ids.length > 0; round++) {
      const conversations: Record<string, unknown>[] = []
      const messages: Record<string, unknown>[] = []
      const pending: Array<{ sessionId: string; line: SessionLine; mid: string }> = []
      const touched: string[] = []
      // sessions with more than 200 new lines and those the round did not reach go again
      const again = new Set(ids)
      for (const sessionId of ids) {
        again.delete(sessionId)
        const info = sessions.get(sessionId)
        if (!info || !this.syncs(sessionId)) continue
        const cid = this.cidFor(sessionId)
        const title = info.title || 'New chat'
        if (this.state.titles[sessionId] !== title) {
          conversations.push({ cid, kind: sessionId === this.state.mainSession ? 'main' : 'side', title, created_at: Math.floor(info.createdAt / 1000), updated_at: Math.floor(info.updatedAt / 1000) })
        }
        const lines = await this.options.sessions.lines(sessionId)
        for (const line of lines) {
          if (this.state.mids[lineKey(sessionId, line.id)] || this.state.mids[line.id]) continue
          if (messages.length >= batch) {
            again.add(sessionId)
            break
          }
          const mid = deriveMid(device, sessionId, line.id)
          messages.push({ mid, cid, role: line.role, text: line.text, created_at: Math.floor(line.at / 1000) })
          pending.push({ sessionId, line, mid })
        }
        touched.push(sessionId)
        if (messages.length >= batch) break
      }
      if (conversations.length === 0 && messages.length === 0) {
        // nothing new in these sessions: they are done, not dirty again
        for (const sid of touched) this.tellWorking(token, sid)
        ids.splice(0, ids.length, ...ids.filter((sid) => again.has(sid)))
        break
      }
      // The relay may accept this round even if its response is lost. Persist its
      // conversation mapping and account ownership before sending, including retries.
      for (const sid of touched) this.adopt(sid)
      await this.options.save(this.state)
      let out: PushResult
      try {
        out = await this.options.relay.push(token, device, conversations, messages)
      } catch (error: unknown) {
        if (!(error instanceof RelayError) || error.status !== 413) throw error
        if (messages.length > 1) {
          batch = Math.max(1, Math.floor(messages.length / 2))
          continue
        }
        for (const p of pending) this.state.mids[lineKey(p.sessionId, p.line.id)] = `refused:${error.code || 'too_large'}`
        await this.save()
        this.log('warn', `nanomuse sync: a message the relay refused as too large stays on this device (${error.code})`)
        continue
      }
      const redirect = new Map<string, string>()
      for (const r of out.rejected) if (r.reason === 'main_exists' && r.cid && r.cid_main) redirect.set(r.cid, r.cid_main)
      if (redirect.size > 0) {
        // the account's main chat has an id already: ours takes it; its lines go again next round
        for (const [sid, cid] of Object.entries(this.state.cids)) {
          const to = redirect.get(cid)
          if (to) {
            this.state.cids[sid] = to
            delete this.state.titles[sid]
            again.add(sid)
            this.log('info', 'nanomuse sync: the main chat adopts the account’s conversation id')
          }
        }
      }
      const refused = new Map(out.rejected.filter((r) => r.mid && r.reason !== 'main_exists').map((r) => [r.mid!, r.reason]))
      const redirected = new Set(out.rejected.filter((r) => r.mid && r.reason === 'main_exists').map((r) => r.mid!))
      for (const p of pending) {
        if (redirected.has(p.mid)) continue
        // a refused row stays refused: it is not sent again and again
        this.state.mids[lineKey(p.sessionId, p.line.id)] = refused.has(p.mid) ? `refused:${refused.get(p.mid)}` : p.mid
      }
      for (const c of conversations) {
        if (out.rejected.some((r) => r.cid === c.cid)) continue
        for (const [sid, cid] of Object.entries(this.state.cids)) if (cid === c.cid) this.state.titles[sid] = String(c.title)
        const known = this.state.conversations[String(c.cid)]
        this.state.conversations[String(c.cid)] = {
          kind: c.kind === 'main' ? 'main' : 'side',
          title: String(c.title),
          device: known?.device || device,
          deviceName: known?.deviceName ?? '',
          createdAt: known?.createdAt || Number(c.created_at),
          updatedAt: Math.max(known?.updatedAt ?? 0, Number(c.updated_at)),
        }
      }
      await this.save()
      // the turn's start or end told once the words are up (C9)
      for (const sid of touched) if (!again.has(sid)) this.tellWorking(token, sid)
      ids.splice(0, ids.length, ...ids.filter((sid) => again.has(sid)))
    }
  }

  private cidFor(sessionId: string): string {
    let cid = this.state.cids[sessionId]
    if (!cid) {
      // the main chat takes the account's main conversation id when the relay has one
      cid = (sessionId === this.state.mainSession ? this.mainCid() : undefined) ?? randomUUID()
      this.state.cids[sessionId] = cid
    }
    return cid
  }

  // ---- pull ---------------------------------------------------------------------------------

  /** A pull that joins the one in flight, and tells nobody when it fails (rule 7). */
  private pullQuietly(): Promise<number> {
    return (this.pulling ?? this.pull()).catch(() => 0)
  }

  /** What the other devices pushed since our cursor, applied in order; how many rows. One at a time. */
  pull(tail = false): Promise<number> {
    const run = (): Promise<number> => {
      const p = this.pullNow(tail)
        .catch((error: unknown) => {
          this.noteError(error)
          throw error
        })
        .finally(() => {
          if (this.pulling === p) this.pulling = undefined
        })
      this.pulling = p
      return p
    }
    return this.pulling ? this.pulling.then(run, run) : run()
  }

  /** The side-chat switch went on: the account's newest side turns, once, from the start (C9). */
  private pullTail(): Promise<number> {
    return this.pull(true).catch(() => 0)
  }

  private async pullNow(tail: boolean): Promise<number> {
    if (!(await this.active())) return 0
    const token = await this.options.token()
    if (!token) return 0
    let applied = 0
    // what the other devices added to conversations living in sessions here: context for the model, per session
    const notes = new Map<string, RemoteLine[]>()
    const scope = this.state.sideChats ? 'all' : 'main'
    for (let page = 0; page < 50; page++) {
      // the first pull after sign-in asks for the newest 300 of the scope (C9): the chat shows before the history
      const since = tail ? 0 : this.state.cursor
      const out = await this.options.relay.changes(token, since, PAGE, scope, since === 0 ? TAIL : 0)
      // The page's conversations first, then its messages, each in seq order: a rename puts
      // a conversation's seq above its messages, and the relay sends every message's
      // conversation along with the page so none of them is an orphan.
      for (const c of [...out.conversations].sort((a, b) => a.seq - b.seq)) {
        await this.applyConversation(c)
        applied += 1
      }
      for (const m of [...out.messages].sort((a, b) => a.seq - b.seq)) {
        await this.applyMessage(m, notes)
        applied += 1
      }
      this.state.cursor = Math.max(this.state.cursor, out.cursor)
      await this.save()
      if (!out.more || tail) break
    }
    this.lastError = ''
    for (const [sessionId, lines] of notes) {
      await this.options.sessions.inject(sessionId, meanwhileNote(lines)).catch((error: unknown) => this.log('warn', `nanomuse sync: context not injected: ${message(error)}`))
    }
    if (applied > 0) {
      this.log('info', `nanomuse sync: ${applied} change(s) from the account’s other devices`)
      this.changed()
    }
    return applied
  }

  private async applyConversation(c: WireConversation): Promise<void> {
    let sessionId = this.sessionOf(c.cid)
    if (c.deleted) {
      delete this.state.conversations[c.cid]
      if (sessionId) {
        // the harness has no delete: the session stops syncing under that id, and the chats column archives it
        delete this.state.cids[sessionId]
        delete this.state.titles[sessionId]
        if (sessionId !== this.state.mainSession && !this.state.toArchive.includes(sessionId)) this.state.toArchive.push(sessionId)
      }
      return
    }
    // side chats off (C9): a side conversation from elsewhere is not a chat here, and one that was stays as it is
    if (c.kind === 'side' && !this.state.sideChats) return
    const known = this.state.conversations[c.cid]
    this.state.conversations[c.cid] = {
      kind: c.kind,
      title: c.title || known?.title || '',
      device: known?.device || c.device,
      deviceName: known?.deviceName || c.device_name,
      createdAt: known?.createdAt || c.created_at,
      updatedAt: Math.max(known?.updatedAt ?? 0, c.updated_at),
    }
    if (!sessionId) {
      if (c.kind === 'main' && this.state.mainSession) {
        // Identifiers: the account's main conversation already exists — our main chat adopts its id
        // (ours was never accepted as main, or the relay would have refused theirs: its lines are
        // still unpushed and go up under the adopted id)
        sessionId = this.state.mainSession
        this.state.cids[sessionId] = c.cid
        this.adopt(sessionId)
        if (c.title) this.state.titles[sessionId] = c.title
        else delete this.state.titles[sessionId]
        this.dirty.add(sessionId)
        this.pushSoon(500)
        this.log('info', 'nanomuse sync: the main chat adopts the account’s conversation id')
      } else {
        // one thread (C8): a conversation from elsewhere is a chat here from the moment it is known
        const title = c.title || (c.kind === 'main' ? 'Main chat' : 'New chat')
        try {
          sessionId = await this.options.sessions.create(title)
        } catch (error: unknown) {
          this.log('warn', `nanomuse sync: no session for a synced conversation: ${message(error)}`)
          return
        }
        this.state.cids[sessionId] = c.cid
        this.adopt(sessionId)
        this.state.titles[sessionId] = title
        if (c.kind === 'main') this.state.mainSession = sessionId
      }
      return
    }
    if (c.title && known && known.title !== c.title && this.state.titles[sessionId] !== c.title) {
      // renamed elsewhere: renamed here, and not pushed back
      this.state.titles[sessionId] = c.title
      await this.options.sessions.rename(sessionId, c.title).catch(() => undefined)
    }
  }

  private async applyMessage(m: WireMessage, notes: Map<string, RemoteLine[]>): Promise<void> {
    if (m.deleted) {
      const kept = this.state.pulled[m.mid]
      if (kept) {
        if (!this.state.hidden.includes(m.mid)) this.state.hidden.push(m.mid)
        await this.options.sessions.forget(kept, m.mid).catch(() => undefined)
      }
      return
    }
    // once is enough: a row kept here already, or our own words coming back
    if (this.state.pulled[m.mid]) return
    if (m.device === this.options.deviceId()) return
    const sessionId = this.sessionOf(m.cid)
    // side chats off (C9): an explicitly side conversation stays where it was written. If
    // its cached metadata was cleared, the existing mapping still proves that this is the
    // main conversation; do not advance the cursor past its final reply.
    const kind = this.state.conversations[m.cid]?.kind
    if (!this.state.sideChats && (kind === 'side' || (kind !== 'main' && sessionId !== this.state.mainSession))) return
    // the reply arrived: its device is not working on it any more — another device's reply
    // must not take away a line that is still someone else's
    if (m.role === 'assistant') {
      const known = this.working.get(m.cid)
      if (known?.from === m.device) this.working.delete(m.cid)
    }
    if (!sessionId) return
    const line: RemoteLine = { mid: m.mid, role: m.role, text: m.text, at: m.created_at * 1000, device: m.device, deviceName: m.device_name }
    try {
      await this.options.sessions.keep(sessionId, line)
      this.state.pulled[m.mid] = sessionId
      notes.set(sessionId, [...(notes.get(sessionId) ?? []), line])
    } catch (error: unknown) {
      this.log('warn', `nanomuse sync: a turn from ${m.device_name || 'another device'} did not reach its chat: ${message(error)}`)
    }
  }

  /** The session a conversation lives in here — one of the signed-in account's or nobody's (C10), never another account's. */
  private sessionOf(cid: string): string | undefined {
    for (const [sid, c] of Object.entries(this.state.cids)) if (c === cid && this.owns(sid)) return sid
    return undefined
  }

  // ---- errors -------------------------------------------------------------------------------

  /** Rule 7: network errors are silent; `sync_off` flips the switch here; a refused key pauses until the next sign-in. */
  private noteError(error: unknown): void {
    if (error instanceof RelayError) {
      if (error.code === 'sync_off') {
        this.state.enabled = false
        void this.save()
        this.log('info', 'nanomuse sync: turned off on another device; off here too')
        this.changed()
        return
      }
      if (error.status === 401) {
        this.paused = true
        this.lastError = 'signed_out'
        this.changed()
        return
      }
      this.lastError = error.code
    } else {
      this.lastError = message(error)
    }
    this.log('debug', `nanomuse sync: ${this.lastError}`)
  }

  get error(): string {
    return this.lastError
  }

  private changed(): void {
    this.rev += 1
    this.options.onChange?.()
  }

  private async save(): Promise<void> {
    await this.options.save(this.state).catch((error: unknown) => this.log('warn', `nanomuse sync: state not written: ${message(error)}`))
  }

  private log(level: 'info' | 'warn' | 'debug', text: string): void {
    this.options.log?.(level, text)
  }
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
