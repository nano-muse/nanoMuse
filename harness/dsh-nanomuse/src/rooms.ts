/**
 * The rooms of the Muse desktop — Feed, Ideas, Goals, Library — as a host
 * service over the harness's own primitives, no second runtime:
 *
 * - **Feed** (动态): short posts the agent writes for the person — news on what
 *   they follow, a nudge on a goal, a plan for the day — a batch a day, written
 *   in a background dsh session (the agent's full tool set, so a post about
 *   today's news comes from `web_search`, with its source linked) that is
 *   archived once the batch is parsed. The person's "feed instructions" say what
 *   they want to read there.
 * - **Ideas** (点子): things the agent could do for the person right now,
 *   grouped by theme, each with what it includes and how it works; "start" opens
 *   a chat with the idea's request.
 * - **Goals** (目标): a goal lives in its own dsh session — the agent shapes it
 *   there, sets up recurring checks with the harness's Schedule (`schedule_create`;
 *   those are the goal's "automations"), and every turn in that session becomes
 *   an entry on the goal's activity timeline. `goals_room_update` lets the agent write
 *   the status line from any chat.
 * - **Library** (构件): the files the agent delivered — every `present` call in
 *   any session lands here, plus what `library_add` names — by kind: documents,
 *   web pages, images, videos, audio.
 *
 * Everything is one JSON file, `$DSH_HOME/nanomuse/rooms.json`; the browser
 * half mirrors it over `/nanomuse/rooms/events` and acts through the routes
 * under `/nanomuse/rooms/*`. The tools and the prompt context the agent sees
 * are the preset row `dsh-nanomuse/rooms-tools`.
 */
import { avatarFence, avatarMemoryLine } from './avatar-flow.ts'
import { FENCE_FEED, FENCE_GOAL, FENCE_GOAL_UPDATE, findFences, goalCategory, goalCheckPrompt, goalCreationNote, goalHomeNote, goalOpener, parseFeedDraft, parseGoalBlock, parseGoalUpdate, parseIdeas, type GoalBlock, type GoalUpdateBlock, type IdeaKind, type StaticIdea } from './fences.ts'
import { afterTurn, boundTo, currentSuggestions, dismissChooser, FIRST_RUN_EMPTY, pickName, promptAddendum, readFirstRun, startConversation, type FirstRunState } from './firstrun.ts'
import { DEFAULT_NUDGES, dueAsk, LEDGER_EMPTY, NUDGES_EVERY_MS, NUDGES_ORIGIN, NUDGES_TIMEOUT_MS, readLedger, readNudges, recordAsk, recordDay, recordStarred, recordTask, type Ask, type Moment, type NudgeLedger, type NudgesPolicy, type NudgesView } from './nudges.ts'
import { noteCommitment, draftDelivered, dueSoon, canCheckIn, commitmentText, type ChatCommitments } from './chat-commitments.ts'
import { asksForDraft, canPrepare, currentFeedGoals, contextKey, parsePreparation, preparationRequest, preparationSources, type Preparation, type Source } from './feed-preparation.ts'
import { followUpText, localDateKey, nextGoalFollowUp, validGoalDate, type GoalFollowUpReason } from './goal-follow-up.ts'
import { pendingChanges, runWatchWorker, watchView, type DiscoveryInput, type PublicLedger } from './public-watches.ts'
import { changeMessage, changeRequest, matchingGoals, privateLine, type ResourceChoice, type ResourceWatch } from './context-resource.ts'
import type { SessionLine } from './sync.ts'
import type {} from './connectors.ts'
import { homeDir, homeWorkspace } from './home.ts'
import { packageAssetsDir } from './profile.ts'
import { describeCall, ownWords, parseArgs } from './steps.ts'
import { createHash, randomBytes } from 'node:crypto'
import { createReadStream, readFileSync } from 'node:fs'
import { lstat, mkdir, open as openFile, readdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises'
import { deflateRawSync } from 'node:zlib'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { basename, extname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { Service, type Context } from '@deepseek-ai/cordis'
import type { Agent } from '@deepseek-ai/dsh-agent'
import { createUserMessage, type ContextFormed } from '@deepseek-ai/dsh-llm'
import type { SessionCreateRequest } from '@deepseek-ai/dsh-api-session-controller/types'
import type { Session, SessionEvent, SessionId } from '@deepseek-ai/dsh-session'

declare module '@deepseek-ai/dsh-llm' {
  interface MessageSourceMap {
    /** A message the rooms put in a chat for the agent (an idea picked, a goal begun): a compact notice row, not a bubble. */
    nanomuse: { kind: 'nanomuse' } & ContextFormed
  }
}
import type {} from '@deepseek-ai/dsh-api-session-controller'
import type {} from '@deepseek-ai/dsh-host-webserver'
import { mountGuarded } from './admit.ts'
import type {} from './cloud.ts'
import { dshHome, json, message, sameOrigin, send } from './cloud.ts'
import { RelayError } from './relay.ts'
import { textOf } from './task.ts'

export const API_PREFIX = '/nanomuse/rooms'

/** A background batch may run this long (web searches included). */
const RUN_TIMEOUT_MS = 8 * 60_000
/** The package's `assets/` (the curated ideas), found whichever file of `lib/` this code landed in. */
export const ASSETS_DIR = packageAssetsDir(import.meta.url)
/** A new feed batch is due this long after the last one. */
const FEED_EVERY_MS = 20 * 3600_000
/** A failed batch is not retried before this. */
const RETRY_AFTER_MS = 2 * 3600_000
const FEED_KEEP = 120
const ACTIVITY_KEEP = 60
const LIBRARY_KEEP = 500
const CHECK_EVERY_MS = 30 * 60_000
const FIRST_CHECK_MS = 90_000
// what one zip of the classic format holds (16-bit entry count, 32-bit offsets, with room)
export const EXPORT_MAX_FILES = 65_000
export const EXPORT_MAX_BYTES = 3 * 1024 * 1024 * 1024
// a single file larger than this is left out, as it always was (a stray video in the library)
export const EXPORT_MAX_FILE_BYTES = 64 * 1024 * 1024

export interface ExportSource {
  name: string
  path?: string
  data?: Buffer
  at: Date
}

export interface ExportBudget {
  files: number
  bytes: number
}

/** A proxy kept in desktop.json may contain credentials; exported settings never do. */
export function redactProxyUserinfo(data: Buffer): Buffer {
  try {
    const parsed: unknown = JSON.parse(data.toString('utf8'))
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return Buffer.from('{}\n')
    const raw = parsed as Record<string, unknown>
    if (typeof raw.proxy !== 'string') return data
    let proxy: URL
    try {
      proxy = new URL(raw.proxy)
    } catch {
      // A malformed old setting is not useful in a backup and must not make a
      // credential-shaped string escape in the export.
      delete raw.proxy
      return Buffer.from(`${JSON.stringify(raw, null, 2)}\n`)
    }
    if (!proxy.username && !proxy.password) return data
    proxy.username = ''
    proxy.password = ''
    raw.proxy = proxy.href.replace(/\/$/, '')
    return Buffer.from(`${JSON.stringify(raw, null, 2)}\n`)
  } catch {
    // Fail closed. A damaged settings file is recoverable from desktop.json.bak,
    // but its unparsed bytes cannot be proven free of proxy credentials.
    return Buffer.from('{}\n')
  }
}

/**
 * The files under one export root, by name, for the zip. Links and special files are
 * left out rather than followed (a link in the workspace must not pull another folder
 * into the export), so are files over `EXPORT_MAX_FILE_BYTES`; a root that is not there
 * is nothing. The count and size are what one zip holds; past them the export fails
 * rather than writes a zip no tool can open.
 */
export async function scanExportRoot(root: string, under: string, budget: ExportBudget, skip: (name: string) => boolean = () => false): Promise<ExportSource[]> {
  const base = resolve(root)
  const rootInfo = await lstat(base).catch(() => null)
  if (!rootInfo || rootInfo.isSymbolicLink() || !rootInfo.isDirectory()) return []
  const entries: ExportSource[] = []
  const add = async (folder: string, prefix: string): Promise<void> => {
    let names: string[]
    try {
      names = await readdir(folder)
    } catch {
      return
    }
    for (const name of names) {
      if (skip(name)) continue
      const full = resolve(folder, name)
      const rel = relative(base, full)
      if (!rel || rel === '..' || rel.startsWith(`..${sep}`) || isAbsolute(rel)) continue
      const info = await lstat(full).catch(() => null)
      if (!info || info.isSymbolicLink()) continue
      if (info.isDirectory()) {
        await add(full, `${prefix}${name}/`)
        continue
      }
      if (!info.isFile() || info.size > EXPORT_MAX_FILE_BYTES) continue
      budget.files += 1
      budget.bytes += info.size
      if (budget.files > EXPORT_MAX_FILES) throw new Error(`the export has more than ${EXPORT_MAX_FILES} files, more than one zip holds`)
      if (budget.bytes > EXPORT_MAX_BYTES) throw new Error(`the export is over ${EXPORT_MAX_BYTES} bytes, more than one zip holds`)
      entries.push({ name: `${prefix}${name}`, path: full, at: info.mtime })
    }
  }
  await add(base, under)
  return entries
}

export const AREAS = ['planning', 'research', 'goals', 'money', 'health', 'home', 'learning', 'people', 'files', 'fun', 'news'] as const
export type Area = (typeof AREAS)[number]
export const CATEGORIES = ['health', 'relationships', 'finance', 'career', 'hobbies', 'productivity', 'other'] as const
export type Category = (typeof CATEGORIES)[number]
export type GoalStatus = 'tracking' | 'done' | 'paused'
export type LibraryKind = 'document' | 'web' | 'image' | 'video' | 'audio' | 'file'

export interface FeedPost {
  id: string
  at: number
  title: string
  /** Markdown; links inline. */
  body: string
  area: string
  emoji: string
  /** A direct image URL the agent found with the story, or empty. */
  image: string
  /** A follow-up the person could send, or empty. */
  prompt: string
  liked: boolean
  /** A local follow-up opens the existing goal conversation without starting a turn. */
  goalId?: string
  goalReason?: GoalFollowUpReason
  goalExpiresAt?: number
  preparation?: Preparation
  /** The chat opened to discuss it, once there is one. */
  sessionId?: string
}

/**
 * One row of the Ideas room: the phone's curated list (`assets/ideas.<lang>.json`, the
 * same items), with what the person did with it here.
 */
export interface Idea {
  id: string
  at: number
  /** The section's title (Travel, Work, …). */
  group: string
  emoji: string
  title: string
  detail: string
  includes: string[]
  how: string
  prompt: string
  area: string
  /** What trying it does: a message in the chat, a daily routine, or a goal conversation. */
  kind: IdeaKind
  /** Routine default, `HH:MM`. */
  time?: string
  /** Goal default category. */
  category?: string
  /** The chat it was started in, once started. */
  started?: string
  dismissed?: boolean
}

export interface GoalActivity {
  at: number
  title: string
  text: string
}

export interface GoalAutomation {
  id: string
  title: string
  kind: string
  /** `daily@09:30`, `weekly 1,3@09:00`, `cron 0 9 * * 1-5`, `every 3600s`, or the one-shot instant. */
  rule: string
  next: string
}

export interface Goal {
  id: string
  title: string
  description: string
  category: Category
  status: GoalStatus
  /** The goal's chat. */
  sessionId: string
  createdAt: number
  updatedAt: number
  /** The agent's one-line status, as `goals_room_update` or a `nanomuse-goal-update` block last wrote it. */
  summary: string
  activity: GoalActivity[]
  /** The steps the agent set out when the goal was shaped in the chat (`nanomuse-goal`). */
  steps: string[]
  /** 0–100 as the agent last reported, -1 when it never said. */
  progress: number
  /** The agent's last update said the goal needs the person's attention. */
  attention: boolean
  due?: string
  nextStep?: string
  feedMuted?: boolean
  followUpSeen?: { due?: string; stage?: number; attention?: boolean }
}

export interface LibraryItem {
  id: string
  path: string
  name: string
  kind: LibraryKind
  description: string
  sessionId: string
  at: number
}

/** One thing the agent remembers about the person — a line, as on the phone's Memory screen. */
export interface MemoryItem {
  id: string
  at: number
  text: string
  /** Who wrote it: the agent in a chat, the person by hand, or an import. */
  prepOwner?: string | undefined
  source: 'agent' | 'person' | 'import'
}

/** One step of a task as the Activity tab and its detail view show it: a tool call, the answer, the start, the end. */
export interface ActivityStep {
  at: number
  kind: 'start' | 'tool' | 'answer' | 'end'
  /** The tool's name (`bash`, `mcp__nanomuse__computer_act`…), or empty. */
  name: string
  /** One line: what the step did, from the call's arguments. */
  title: string
  /** The call's arguments, pretty-printed and cut; the answer's text; the end's reason. */
  detail: string
  /** The tool's result, cut, once it is in. */
  result: string
  /** Pairs a tool step with its result. */
  callId: string
  ok?: boolean
}

/** What one chat did, turn by turn — the agent's own account of a task, for the profile panel. */
export interface ActivityRecord {
  sessionId: string
  startedAt: number
  updatedAt: number
  endedAt: number
  status: 'running' | 'done' | 'error' | 'stopped' | 'waiting'
  /** The person's first words in the latest turn (the task), cut. */
  request: string
  requestAt?: number
  requestOwner?: string
  /** Private Feed state scoped to this chat and account. */
  commitments?: ChatCommitments
  /** The agent's last words, cut. */
  words: string
  /** The tool step under way, for the status line under the face. */
  current: { name: string; title: string; at: number; own?: boolean } | null
  steps: ActivityStep[]
  /** How many turns the record covers. */
  turns: number
}

/** The agent's own documents: who it is, how it carries itself, and what it remembers. */
export type DocName = 'identity' | 'soul' | 'memory'

/** The feed's daily routine (C5): on by default, 08:00, ensured when the Feed is first opened. */
export interface FeedRoutine {
  on: boolean
  /** `HH:MM`, local time. */
  time: string
  /** When the Feed was first opened and the routine written; 0 until then. */
  ensuredAt: number
  reading?: boolean
  /** Scoped to the active account in the public view only. */
  chatCheckIns?: boolean
  checkInScope?: string
  newResourceOffer?: string
  contextResource?: ResourceWatch
}

interface ChatCheckIn {
  id: string
  sessionId: string
  at: number
  commitmentAt?: number
  external?: boolean
  /** Only a public-only review can create this distinct copy for another device. */
  publicShare?: { grant: string; watchId: string; text: string }
  text: string
  unread: boolean
}
interface CheckInMailbox {
  publicWatches?: PublicLedger
  publicReviews?: { day: string; count: number }
  allowNewResource?: boolean
  /** Missing follows the default, zero is an explicit opt-out. */
  enabledSince?: number
  lastDay: string
  messages: ChatCheckIn[]
  resource?: ResourceWatch & { seen: string[]; checkedAt: number }
}

interface Store {
  mailboxes: Record<string, CheckInMailbox>
  lang: string
  feed: { instructions: string; generatedAt: number; lastTry: number; posts: FeedPost[]; routine: FeedRoutine; lastGoalFollowUpDay?: string; preparation?: { context: string; day: string; seen: string[]; published?: { owner: string; subject: string; source: string }; revisedOn?: string } }
  /** `marks` is what the person did with each idea of the static list; `items` is the list as the browser sees it. */
  ideas: { generatedAt: number; lastTry: number; items: Idea[]; marks: Record<string, { started?: string; dismissed?: boolean }> }
  goals: Goal[]
  library: LibraryItem[]
  memory: MemoryItem[]
  /** IDENTITY.md and SOUL.md as the person last wrote them (empty = the template). */
  docs: { identity: string; soul: string; identityAt: number; soulAt: number }
  activity: ActivityRecord[]
  /** When the first-run introduction was posted, so it happens once. */
  introducedAt: number
  /**
   * The chats of the batches run so far (the feed's), newest first: a batch is the agent's
   * workbench, not a chat of the person's, so these are kept out of the conversation sync
   * (`NanomuseCloud`, through `isBatch`) and never reach the account's other devices.
   */
  batches: string[]
}

/** What the browser mirrors. */
export interface RoomsView extends Omit<Store, 'activity' | 'mailboxes'> {
  checkIns: Array<Pick<ChatCheckIn, 'id' | 'sessionId' | 'at' | 'unread'>>
  busy: { feed: boolean; ideas: boolean }
  /** The chats of the batches running right now (the feed's): the chats column leaves them out. */
  batches: string[]
  automations: Record<string, GoalAutomation[]>
  /** Whether a model is reachable, so the empty rooms can say why they are empty. */
  ready: boolean
  /** The agent asked for the avatar studio (draw_new_look): the words and when; the window opens it once. */
  studio: { description: string; style: string; at: number }
  /** The records without their steps' details (the detail view fetches one in full). */
  activity: ActivityRecord[]
  /** The first run and the first conversation (C4), with the chooser's names resolved. */
  firstRun: FirstRunState & { chips: string[] }
  /** The star nudges (C1): the policy, the ledger's figures and the ask on screen. */
  nudges: NudgesView
}

/** `dsh-permission-presets`' service, as much of it as we use. */
interface PresetsLike {
  readonly names: readonly string[]
  set(session: Session, name: string): void
}

/** The harness's Schedule service, the part of it the goals use (optional at runtime). */
interface ScheduleLike {
  create(sessionId: SessionId, request: { prompt: string; title: string; every_seconds?: number; daily?: { time: string; time_zone: string } }): Promise<{ id: string }>
  list(request: { sessionId: SessionId }): Promise<ScheduleRecordLike[]>
  delete(request: { sessionId: SessionId; id: string }): Promise<unknown>
}
export interface ScheduleRecordLike {
  id: string
  kind: string
  title: string
  scheduledAt: string
  time?: string
  weekdays?: number[]
  expression?: string
  everySeconds?: number
}
interface RegistryLike {
  readonly archivedSessionIds: readonly string[]
  archiveSession(sessionId: SessionId, options?: { stopActivity?: boolean }): Promise<void>
  /** The workspace owning `path`, created when there is none yet (idempotent by canonical path). */
  create(path: string, title?: string): Promise<{ id: string }>
}

interface Run {
  final: string
  resolve(text: string): void
  reject(error: Error): void
}

const EMPTY: Store = {
  mailboxes: {},
  lang: '',
  feed: { instructions: '', generatedAt: 0, lastTry: 0, posts: [], routine: { on: true, time: '08:00', ensuredAt: 0, reading: false } },
  ideas: { generatedAt: 0, lastTry: 0, items: [], marks: {} },
  goals: [],
  library: [],
  memory: [],
  docs: { identity: '', soul: '', identityAt: 0, soulAt: 0 },
  activity: [],
  introducedAt: 0,
  batches: [],
}
/** Batch chats remembered (one a day for the feed): enough for the archive's lifetime. */
const BATCHES_KEEP = 400
/** Activity records kept, steps per record, and how much of a step's text. */
const ACTIVITY_RECORDS = 80
const ACTIVITY_STEPS = 60
const STEP_TEXT = 1200
const DOC_MAX = 20_000
const STUDIO_STYLES: Record<string, true> = { muse: true, flat: true, clay: true, watercolor: true, pixel: true, line: true, sticker: true }
const MEMORY_MAX = 400
const MEMORY_LINE = 400

const KINDS: Record<string, LibraryKind> = {
  '.md': 'document', '.markdown': 'document', '.txt': 'document', '.rtf': 'document', '.doc': 'document', '.docx': 'document', '.pdf': 'document', '.pptx': 'document', '.xlsx': 'document', '.csv': 'document', '.json': 'document', '.tex': 'document',
  '.html': 'web', '.htm': 'web',
  '.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.webp': 'image', '.gif': 'image', '.svg': 'image',
  '.mp4': 'video', '.mov': 'video', '.webm': 'video', '.mkv': 'video',
  '.mp3': 'audio', '.m4a': 'audio', '.wav': 'audio', '.ogg': 'audio', '.flac': 'audio',
}
const MIME: Record<string, string> = {
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif', '.svg': 'image/svg+xml',
  '.mp4': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm',
  '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
  '.pdf': 'application/pdf', '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8',
}
const TEXT_KINDS = new Set(['.md', '.markdown', '.txt', '.html', '.htm', '.csv', '.json', '.tex', '.svg'])
/** What the Library takes in from disk for now: Markdown and plain text, which the editor shows and the agent reads as they are (#689). */
export const IMPORT_KINDS = new Set(['.md', '.markdown', '.txt'])
/** The most one imported file may hold — the editor's own reading limit. */
export const IMPORT_MAX_BYTES = 2 * 1024 * 1024
/** Characters no file system takes in a name, control characters, and the path separators (one segment only). */
const UNSAFE_IN_NAME = /[\u0000-\u001f<>:"/\\|?*]+/g
const NAME_MAX = 80

/** The stem of a file name a person typed or brought in, made safe for every file system: one path
 * segment, no reserved characters, trailing dots and spaces dropped (Windows), at most 80 characters;
 * `''` when nothing is left. */
export function safeStem(name: string): string {
  const base = name.replace(/\\/g, '/').split('/').filter(Boolean).pop() ?? ''
  const stem = base.replace(/\.[^.]*$/, '')
  return stem.replace(UNSAFE_IN_NAME, ' ').replace(/\s+/g, ' ').trim().replace(/[. ]+$/, '').slice(0, NAME_MAX).trim()
}

/** `stem.ext` under `folder`, or `stem (2).ext`, `stem (3).ext`… when that name is taken. */
export async function freePath(folder: string, stem: string, ext: string): Promise<string> {
  for (let n = 1; n < 1000; n++) {
    const candidate = join(folder, `${stem}${n > 1 ? ` (${n})` : ''}${ext}`)
    try {
      await lstat(candidate)
    } catch {
      return candidate
    }
  }
  throw new RelayError(409, 'exists', 'Too many files of that name')
}

declare module '@deepseek-ai/cordis' {
  interface Context {
    nanomuseRooms: NanomuseRooms
  }
}

export default class NanomuseRooms extends Service {
  static inject = ['nanomuseCloud']

  private store: Store = structuredClone(EMPTY)
  private readonly streams = new Set<ServerResponse>()
  private readonly runs = new Map<SessionId, Run>()
  /** Goal sessions → goal, and the last words the agent said in each (the next activity entry). */
  private readonly goalBySession = new Map<string, string>()
  private readonly lastWords = new Map<string, string>()
  /** The agent's last message in every chat, read for app fences when the turn ends. */
  private readonly fenceWords = new Map<string, string>()
  /** The phone's curated Ideas list, by language file. */
  private ideasCache: { file: string; items: StaticIdea[] } | undefined
  /** When the current turn's first words arrived, per goal session. */
  private readonly turnMarks = new Map<string, number>()
  private automations: Record<string, GoalAutomation[]> = {}
  /** The tools as the last agent saw them (the registry's views are per agent); the Connectors page reads it. */
  private toolCatalog: { name: string; description: string }[] = []
  private catalogAt = 0
  private busy = { feed: false, ideas: false }
  private ready = false
  private studio = { description: '', style: 'muse', at: 0 }
  private writing: Promise<void> = Promise.resolve()
  private followUpNeedsSave = false
  private unpublishedCheckIn: string | undefined
  private publishingCheckIn: Promise<void> | undefined
  private watchEpoch = randomBytes(12).toString('hex')
  private watchPoll: AbortController | undefined
  private watchEdit: AbortController | undefined
  private watchObservedAt = 0
  private watchInputs: Array<DiscoveryInput & { current: () => boolean }> = []
  private newResourceRevision = 0
  private resourceAbort: AbortController | undefined
  private resourceChoiceAbort: AbortController | undefined
  private prepAbort: AbortController | undefined
  private prepLastTry = 0
  private timer: NodeJS.Timeout | undefined
  /** A broadcast is due: coalesced, so a burst of tool calls is one frame. */
  private pendingFrame: NodeJS.Timeout | undefined
  private pendingSave: NodeJS.Timeout | undefined
  /** The first run (C4): its own file, so a reset of the rooms leaves it alone. */
  private firstRun: FirstRunState = { ...FIRST_RUN_EMPTY, suggestions: [] }
  private writingFirstRun: Promise<void> = Promise.resolve()
  /** Sessions whose current turn the person started (a `user/message` of theirs since `turn/start`). */
  private readonly personTurns = new Set<string>()
  /** The star nudges (C1): the relay's policy, when it was read, and this computer's ledger. */
  private nudges: { policy: NudgesPolicy; fetchedAt: number; ledger: NudgeLedger; current: Ask | null } = { policy: structuredClone(DEFAULT_NUDGES), fetchedAt: 0, ledger: structuredClone(LEDGER_EMPTY), current: null }
  private writingNudges: Promise<void> = Promise.resolve()
  private fetchingNudges = false

  constructor(ctx: Context) {
    super(ctx, 'nanomuseRooms')
  }

  async [Service.init](): Promise<void> {
    this.store = await this.read()
    this.firstRun = await this.readSmall(this.firstRunPath, readFirstRun)
    const nudges = await this.readSmall(this.nudgesPath, (raw) => raw)
    const saved = nudges && typeof nudges === 'object' ? (nudges as Record<string, unknown>) : {}
    this.nudges = { policy: readNudges(saved.policy) ?? structuredClone(DEFAULT_NUDGES), fetchedAt: typeof saved.fetchedAt === 'number' ? saved.fetchedAt : 0, ledger: readLedger(saved.ledger), current: null }
    // a record left running by a host that stopped is over
    for (const record of this.store.activity) {
      if (record.status === 'running' || record.status === 'waiting') {
        record.status = 'stopped'
        record.current = null
        record.endedAt = record.endedAt || record.updatedAt
      }
    }
    for (const goal of this.store.goals) this.goalBySession.set(goal.sessionId, goal.id)
    this.ctx.effect(() => this.ctx.on('session/event', (session: Session, event: SessionEvent) => this.onEvent(session, event)), 'nanomuse rooms: session events')
    this.ctx.effect(() => this.ctx.on('schedule/changed' as never, (() => void this.refreshAutomations()) as never), 'nanomuse rooms: schedule changes')
    let feedOwner = this.ctx.nanomuseCloud.feedOwner
    this.ctx.effect(() => this.ctx.nanomuseCloud.onChange(() => {
      const owner = this.ctx.nanomuseCloud.feedOwner
      if (owner !== feedOwner) {
        feedOwner = owner
        this.resetWatchWork()
        this.newResourceRevision++
        this.resourceAbort?.abort()
        this.resourceChoiceAbort?.abort()
        this.prepAbort?.abort()
        this.broadcast()
      }
      void this.syncReady().catch(() => undefined)
    }), 'nanomuse rooms: cloud changes')
    mountGuarded(this.ctx, API_PREFIX, this.handle, 'nanomuse rooms: api')
    this.timer = setInterval(() => void this.tick().catch((error: unknown) => this.warn('tick', error)), CHECK_EVERY_MS)
    const first = setTimeout(() => void this.tick().catch((error: unknown) => this.warn('tick', error)), FIRST_CHECK_MS)
    this.ctx.effect(() => () => {
      this.resetWatchWork()
      if (this.timer) clearInterval(this.timer)
      clearTimeout(first)
      this.resourceAbort?.abort()
      this.resourceChoiceAbort?.abort()
      if (this.pendingFrame) clearTimeout(this.pendingFrame)
      if (this.pendingSave) clearTimeout(this.pendingSave)
      for (const res of this.streams) res.end()
      this.prepAbort?.abort()
      this.streams.clear()
      for (const run of this.runs.values()) run.reject(new Error('nanomuse rooms: shutting down'))
    }, 'nanomuse rooms: stop')
    // the schedule service may come up after us: read the automations once it is there, and again on demand
    this.ctx.inject(['schedule' as never], () => void this.refreshAutomations().catch(() => undefined))
  }

  // ---- the view --------------------------------------------------------------------

  view(): RoomsView {
    // the records travel without their steps' texts; `/activity?session=` has one in full
    const activity = this.store.activity.filter((r) => !this.ctx.nanomuseCloud.isClearedSession(r.sessionId)).map(({ commitments: _private, requestOwner: _owner, ...r }) => ({ ...r, steps: r.steps.map((s) => ({ ...s, detail: '', result: '' })) }))
    const goals = this.goals
    const now = Date.now()
    const accessibleGoals = new Set(currentFeedGoals(goals, this.store.activity, this.ctx.nanomuseCloud.feedOwner, now).map(goal => goal.id))
    const prepSources = this.store.feed.posts.some(p => p.preparation) ? this.prepSources(now, this.store.feed.posts) : []
    const visible = this.store.feed.posts.filter(post => this.prepVisible(post, prepSources))
    const { preparation: _ledger, ...publicFeed } = this.store.feed
    const preparedGoals = new Set(visible.flatMap(post => post.preparation?.sources.map(s => s.goalId) ?? []))
    const posts = visible.filter(post => !post.goalId || (!preparedGoals.has(post.goalId) && (post.goalExpiresAt ?? 0) > now && accessibleGoals.has(post.goalId)))
    const { mailboxes: _private, ...publicStore } = this.store
    const box = this.checkInMailbox()
    const watched = box?.resource
    const contextResource = watched ? { connection: watched.connection, generation: watched.generation, key: watched.key, label: watched.label } : undefined
    return {
      ...publicStore,
      goals,
      checkIns: this.checkInMessages().map(({ id, sessionId, at, unread }) => ({ id, sessionId, at, unread })),
      feed: { ...publicFeed, posts, routine: { ...publicFeed.routine, chatCheckIns: Boolean(this.ctx.nanomuseCloud.feedOwner && box?.enabledSince !== 0), newResourceOffer: this.newResourceOffer(), ...(contextResource ? { contextResource } : {}), checkInScope: this.checkInScope() } },
      ideas: { ...this.store.ideas, items: this.ideaItems() },
      activity,
      busy: { ...this.busy },
      batches: [...this.runs.keys()],
      automations: this.automations,
      ready: this.ready,
      studio: this.studio,
      firstRun: { ...this.firstRun, chips: currentSuggestions(this.firstRun, this.lang) },
      nudges: this.nudgesView(),
    }
  }

  // ---- the first run and the first conversation (C4) -----------------------------------

  private get firstRunPath(): string {
    return join(dshHome(), 'nanomuse', 'firstrun.json')
  }

  firstRunState(): FirstRunState {
    return this.firstRun
  }

  /** What the model is told for the first conversation in `sessionId`; empty elsewhere and once it is over. */
  firstRunAddendum(sessionId: string | undefined): string {
    if (!sessionId || !boundTo(this.firstRun, sessionId)) return ''
    return promptAddendum(this.firstRun, this.lang, this.ctx.nanomuseCloud.profile.current().name) ?? ''
  }

  /** The setup pages' choices, as they are made. */
  async setFirstRun(patch: { sourceChosen?: 'cloud' | 'own' | null; permissionsSeen?: boolean }): Promise<FirstRunState> {
    if (patch.sourceChosen !== undefined) this.firstRun = { ...this.firstRun, sourceChosen: patch.sourceChosen }
    if (patch.permissionsSeen !== undefined) this.firstRun = { ...this.firstRun, permissionsSeen: patch.permissionsSeen }
    await this.saveFirstRun()
    return this.firstRun
  }

  /**
   * Start was pressed: the main chat, opened on the agent's own folder (`~/nanoMuse`,
   * registered as a workspace so the composer is live at once), bound as the first
   * conversation. The app speaks first there, from the browser, at no cost in tokens; the
   * model only hears from the person. A second Start lands in the same chat while it lives.
   */
  async startFirstConversation(): Promise<{ sessionId: string }> {
    const bound = this.firstRun.sessionId
    if (bound && this.firstRun.phase !== 'none' && (await this.alive(bound))) return { sessionId: bound }
    const sc = this.ctx.get('sessionController')
    if (!sc) throw new RelayError(503, 'no_sessions', 'Chats are not available yet')
    // One thread (C8): signed in before Start, the account's main conversation may already live in
    // a session here (pulled from the relay) — the first conversation is that session.
    const synced = this.ctx.nanomuseCloud.syncMainSession()
    if (synced && (await this.alive(synced))) {
      // A conversation already underway on another device of the account (its turns are here)
      // is not begun again: no opening, no name to choose — the thread simply continues.
      const underway = this.ctx.nanomuseCloud.syncRemoteLines(synced) > 0
      const base: FirstRunState = this.firstRun.phase === 'done' ? this.firstRun : { ...this.firstRun, phase: underway ? 'done' : 'none' }
      this.firstRun = startConversation(base, synced)
      await this.saveFirstRun()
      return { sessionId: synced }
    }
    const created = await sc.create(await homeWorkspace(this.ctx, (error) => this.warn('home workspace', error)))
    await sc.rename({ sessionId: created.sessionId, title: this.lang.startsWith('zh') ? '主要聊天' : 'Main chat' }).catch(() => undefined)
    // a conversation that already ran its course on an older chat stays over; a fresh install begins
    this.firstRun = startConversation(this.firstRun.phase === 'done' ? this.firstRun : { ...this.firstRun, phase: 'none' }, created.sessionId)
    await this.saveFirstRun()
    // the main chat from its first turn: pushed as the account's main conversation (C8)
    await this.ctx.nanomuseCloud.setSyncMain(String(created.sessionId)).catch((error: unknown) => this.warn('sync main', error))
    return { sessionId: created.sessionId }
  }

  /** The setup pages were finished without a chat (an older install, a window that could not open one). */
  async finishFirstRun(): Promise<void> {
    if (this.firstRun.done) return
    this.firstRun = { ...this.firstRun, done: true, finishedAt: Date.now() }
    await this.saveFirstRun()
  }

  /**
   * A chip was picked on the chooser: the name is on the header before the model has even
   * replied, then the name goes to the chat as the person's message so the model replies as
   * itself (the system addendum for `named` tells it what happened).
   */
  async pickFirstName(name: string): Promise<void> {
    const next = pickName(this.firstRun, name)
    if (!next) throw new RelayError(409, 'not_now', 'No name is being chosen right now')
    this.firstRun = next
    await this.saveFirstRun()
    await this.ctx.nanomuseCloud.writeProfile({ name })
    const sessionId = this.firstRun.sessionId
    if (sessionId) await this.say(sessionId as SessionId, name)
  }

  /** The person moved on to something the app handles itself: the chooser goes. */
  async dismissFirstChooser(): Promise<void> {
    const next = dismissChooser(this.firstRun)
    if (next === this.firstRun) return
    this.firstRun = next
    await this.saveFirstRun()
    this.onFirstConversationOver()
  }

  /** The model's reply in the first conversation ended: read its block, move the phase, keep what it said. */
  private async firstTurnEnded(words: string): Promise<void> {
    const outcome = afterTurn(this.firstRun, words)
    if (outcome.state === this.firstRun) return
    this.firstRun = outcome.state
    await this.saveFirstRun()
    if (outcome.addressGiven) {
      // the phone's "- Call them: X" under "About the user": one line in the memory, replaced when it changes
      for (const item of this.store.memory.filter((m) => /^call them:/i.test(m.text))) await this.forget(item.id)
      await this.remember(`Call them: ${outcome.addressGiven}`, 'agent')
    }
    if (outcome.named) await this.ctx.nanomuseCloud.writeProfile({ name: outcome.named }).catch((error: unknown) => this.warn('first name', error))
    if (this.firstRun.phase === 'done') this.onFirstConversationOver()
  }

  /** The first conversation reached its end: the feed's first day is written in the background, once. */
  private onFirstConversationOver(): void {
    if (!this.store.feed.routine.on || this.store.feed.posts.length || this.busy.feed) return
    if (!this.ready) return
    void this.prepareFeed().catch((error: unknown) => this.warn('first feed', error))
  }

  private saveFirstRun(): Promise<void> {
    const snapshot = JSON.stringify(this.firstRun, null, 2) + '\n'
    this.writingFirstRun = this.writingFirstRun.then(() => this.writeSmall(this.firstRunPath, snapshot)).catch((error: unknown) => this.warn('first run save', error))
    this.broadcast()
    return this.writingFirstRun
  }

  // ---- the star nudges (C1) ------------------------------------------------------------

  private get nudgesPath(): string {
    return join(dshHome(), 'nanomuse', 'nudges.json')
  }

  private nudgesView(): NudgesView {
    const { policy, fetchedAt, ledger, current } = this.nudges
    return { policy, tasks: ledger.tasks, days: ledger.days.length, asks: ledger.asks.length, starred: ledger.starred, fetchedAt, current }
  }

  /**
   * The one gate: is an ask due for this moment now? When it is, it is recorded before it is
   * answered — showing the card is the ask. The browser calls this for the moments it sees
   * (signed in, a new look, the allowance used up); the host calls it for the ones it counts.
   */
  async askNudge(moment: Moment, n?: number): Promise<Ask | null> {
    const ask = dueAsk(this.nudges.policy, this.nudges.ledger, moment, n)
    if (!ask) return null
    this.nudges.ledger = recordAsk(this.nudges.ledger, ask)
    this.nudges.current = ask
    await this.saveNudges()
    return ask
  }

  /** The person went to GitHub from a card: no more asks. */
  async starred(): Promise<void> {
    this.nudges.ledger = recordStarred(this.nudges.ledger)
    this.nudges.current = null
    await this.saveNudges()
  }

  /** "Not now", or the card timed out: the ask stays counted, the card goes. */
  async dismissNudge(): Promise<void> {
    if (!this.nudges.current) return
    this.nudges.current = null
    this.broadcast()
  }

  /** The app was opened today: the 7th and the 30th distinct day ask once each. */
  private async nudgeDay(): Promise<void> {
    const { ledger, newDay } = recordDay(this.nudges.ledger)
    if (!newDay) return
    this.nudges.ledger = ledger
    await this.saveNudges()
    await this.askNudge('days_used', ledger.days.length)
  }

  /** A person-started turn ended with a reply: one more task; the thresholds ask once each. */
  private async nudgeTask(): Promise<void> {
    this.nudges.ledger = recordTask(this.nudges.ledger)
    await this.saveNudges()
    await this.askNudge('tasks', this.nudges.ledger.tasks)
  }

  /** The policy, from the relay at most once a day; the last good copy stays when the network does not answer. */
  private async refreshNudges(force = false): Promise<void> {
    if (this.fetchingNudges) return
    if (!force && Date.now() - this.nudges.fetchedAt < NUDGES_EVERY_MS) return
    this.fetchingNudges = true
    try {
      const status = await this.ctx.nanomuseCloud.status().catch(() => undefined)
      const origin = (status?.baseURL || NUDGES_ORIGIN).replace(/\/+$/, '')
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), NUDGES_TIMEOUT_MS)
      try {
        const res = await fetch(`${origin}/v1/nudges`, { signal: controller.signal })
        if (res.ok) {
          const policy = readNudges(await res.json().catch(() => null))
          if (policy) this.nudges.policy = policy
        }
      } finally {
        clearTimeout(timer)
      }
      // a miss is remembered too: one try a day, quietly
      this.nudges.fetchedAt = Date.now()
      await this.saveNudges()
    } catch {
      this.nudges.fetchedAt = Date.now()
    } finally {
      this.fetchingNudges = false
    }
  }

  /** `/v1/me` carried a policy (the relay sends it with the account): adopt it when it differs from the one on file. */
  adoptNudges(raw: unknown): void {
    const policy = readNudges(raw)
    if (!policy) return
    const fresh = Date.now() - this.nudges.fetchedAt < NUDGES_EVERY_MS
    if (fresh && JSON.stringify(policy) === JSON.stringify(this.nudges.policy)) return
    this.nudges.policy = policy
    this.nudges.fetchedAt = Date.now()
    void this.saveNudges()
  }

  private saveNudges(): Promise<void> {
    const snapshot = JSON.stringify({ policy: this.nudges.policy, fetchedAt: this.nudges.fetchedAt, ledger: this.nudges.ledger }, null, 2) + '\n'
    this.writingNudges = this.writingNudges.then(() => this.writeSmall(this.nudgesPath, snapshot)).catch((error: unknown) => this.warn('nudges save', error))
    this.broadcast()
    return this.writingNudges
  }

  // ---- small files beside rooms.json -------------------------------------------------

  private async readSmall<T>(path: string, parse: (raw: unknown) => T): Promise<T> {
    try {
      return parse(JSON.parse(await readFile(path, 'utf8')) as unknown)
    } catch {
      return parse(undefined)
    }
  }

  private async writeSmall(path: string, snapshot: string): Promise<void> {
    await mkdir(join(dshHome(), 'nanomuse'), { recursive: true })
    const tmp = `${path}.${process.pid}.tmp`
    await writeFile(tmp, snapshot, { mode: 0o600 })
    await rename(tmp, path)
  }

  /** One task in full, for the detail view. */
  /** Remove task records once sync has durably blocked the corresponding sessions. */
  async clearActivity(ids: string[]): Promise<void> {
    const cleared = new Set(ids)
    this.watchPoll?.abort()
    this.store.activity = this.store.activity.filter((record) => !cleared.has(record.sessionId))
    for (const box of Object.values(this.store.mailboxes ?? {})) box.messages = box.messages.filter(m => !cleared.has(m.sessionId))
    const removedGoals = new Set(this.store.goals.filter((goal) => cleared.has(goal.sessionId)).map((goal) => goal.id))
    this.store.feed.posts = this.store.feed.posts.filter((post) => !post.goalId || !removedGoals.has(post.goalId))
    await this.save()
  }

  activityOf(sessionId: string): ActivityRecord | undefined {
    if (this.ctx.nanomuseCloud.isClearedSession(sessionId)) return undefined
    const record = this.store.activity.find((r) => r.sessionId === sessionId)
    if (!record) return
    const { commitments: _private, requestOwner: _owner, ...activity } = record
    return activity
  }

  // ---- the agent's documents: IDENTITY.md, SOUL.md, MEMORY.md -------------------------------

  /** The three documents as the editor shows them; the templates are ours, in the person's language. */
  docs(): Record<DocName, { text: string; updatedAt: number; template: boolean }> {
    const profile = this.ctx.nanomuseCloud.profile.current()
    const zh = this.lang.startsWith('zh')
    const identity = this.store.docs.identity || identityTemplate(profile.name, profile.description, zh)
    const soul = this.store.docs.soul || soulTemplate(profile.name, zh)
    const memoryAt = this.store.memory.reduce((max, m) => Math.max(max, m.at), 0)
    return {
      identity: { text: identity, updatedAt: this.store.docs.identityAt, template: !this.store.docs.identity },
      soul: { text: soul, updatedAt: this.store.docs.soulAt, template: !this.store.docs.soul },
      memory: { text: memoryDoc(this.store.memory, zh), updatedAt: memoryAt, template: this.store.memory.length === 0 },
    }
  }

  /** What the prompt carries of IDENTITY.md and SOUL.md once the person has written them (the templates say nothing new). */
  get persona(): string {
    const parts: string[] = []
    if (this.store.docs.identity.trim()) parts.push(stripDoc(this.store.docs.identity).slice(0, 1500))
    if (this.store.docs.soul.trim()) parts.push(stripDoc(this.store.docs.soul).slice(0, 2500))
    return parts.join('\n\n')
  }

  async writeDoc(doc: DocName, text: string): Promise<void> {
    const body = text.replace(/\r\n/g, '\n').slice(0, DOC_MAX)
    if (doc === 'memory') {
      await this.applyMemoryDoc(body)
      return
    }
    if (doc === 'identity') {
      this.store.docs.identity = body
      this.store.docs.identityAt = Date.now()
    } else {
      this.store.docs.soul = body
      this.store.docs.soulAt = Date.now()
    }
    await this.save()
  }

  /** MEMORY.md written back: every bullet is a memory; a bullet gone is forgotten, a new one is kept. */
  private async applyMemoryDoc(text: string): Promise<void> {
    const lines = text
      .split('\n')
      .map((l) => /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(l)?.[1]?.trim() ?? '')
      .map((l) => l.replace(/^\(?\d{4}-\d{2}-\d{2}\)?[:：]?\s*/, '').trim())
      .filter((l) => l.length > 1)
    const keep = new Set(lines.map(memoryKey))
    const before = this.store.memory.length
    this.store.memory = this.store.memory.filter((m) => keep.has(memoryKey(m.text)))
    const have = new Set(this.store.memory.map((m) => memoryKey(m.text)))
    for (const line of lines.slice(0, MEMORY_MAX)) {
      if (have.has(memoryKey(line))) continue
      have.add(memoryKey(line))
      this.store.memory.push({ id: newId('mem'), at: Date.now(), text: line.slice(0, MEMORY_LINE), source: 'person', prepOwner: this.ctx?.nanomuseCloud?.feedOwner })
    }
    if (this.store.memory.length !== before || lines.length) await this.save()
  }

  // ---- activity: what each chat did -------------------------------------------------------------

  private recordFor(sessionId: string, create: boolean): ActivityRecord | undefined {
    let record = this.store.activity.find((r) => r.sessionId === sessionId)
    if (!record && create) {
      const now = Date.now()
      record = { sessionId, startedAt: now, updatedAt: now, endedAt: 0, status: 'running', request: '', words: '', current: null, steps: [], turns: 0 }
      this.store.activity.unshift(record)
      if (this.store.activity.length > ACTIVITY_RECORDS) this.store.activity.length = ACTIVITY_RECORDS
    }
    return record
  }

  private pushStep(record: ActivityRecord, step: ActivityStep): void {
    record.steps.push(step)
    if (record.steps.length > ACTIVITY_STEPS) record.steps.splice(0, record.steps.length - ACTIVITY_STEPS)
  }

  /** The activity changed: one frame soon, one save a little later (tool bursts are many events). */
  private activityChanged(record: ActivityRecord, persist = false): void {
    record.updatedAt = Date.now()
    // newest first, so the panel's list is the array
    const index = this.store.activity.indexOf(record)
    if (index > 0) {
      this.store.activity.splice(index, 1)
      this.store.activity.unshift(record)
    }
    if (!this.pendingFrame) {
      this.pendingFrame = setTimeout(() => {
        this.pendingFrame = undefined
        this.broadcast()
      }, 250)
    }
    if (persist && !this.pendingSave) {
      this.pendingSave = setTimeout(() => {
        this.pendingSave = undefined
        void this.save()
      }, 1500)
    }
  }

  private commitmentOwner(record: ActivityRecord, goal: Goal | undefined): string | undefined {
    const owner = this.ctx.nanomuseCloud.feedOwner
    if (owner !== undefined && this.store.feed.routine.on && !this.isBatch(record.sessionId) &&
        (!goal || (!goal.feedMuted && goal.status === 'tracking')) &&
        this.ctx.nanomuseCloud.scheduleSessionAccess('nanomuse-feed')(record.sessionId)) return owner
  }

  private trackActivity(session: Session, event: SessionEvent): void {
    if (this.ctx.nanomuseCloud.isClearedSession(String(session.id))) return
    const type: string = event.type
    if (type === 'turn/start') {
      const record = this.recordFor(session.id, true)!
      // Migrate the previous human request before turn/start discards its answer.
      if (!record.commitments && record.status === 'done' && record.requestAt && record.request) {
        const goal = this.store.goals.find(g => g.sessionId === record.sessionId)
        const owner = this.commitmentOwner(record, goal)
        if (owner !== undefined && (record.requestOwner === undefined || record.requestOwner === owner)) {
          const state: ChatCommitments = { owner, items: [] }
          noteCommitment(state, record.request, record.requestAt, goal)
          const item = state.items[0]
          if (item && asksForDraft(item.request) && record.steps.some(s => s.kind === 'answer' && s.at >= item.at && draftDelivered(s.detail))) item.closed = true
          record.commitments = state
        }
      }
      record.status = 'running'
      record.current = null
      record.endedAt = 0
      record.turns += 1
      if (record.turns > 1) record.steps = []
      this.pushStep(record, { at: Date.now(), kind: 'start', name: '', title: '', detail: '', result: '', callId: '' })
      this.activityChanged(record)
      return
    }
    const record = this.recordFor(session.id, false)
    if (!record) return
    switch (event.type) {
      case 'user/message': {
        if (event.data.source.kind !== 'user') return
        const text = textOf(event.data.content).replace(/\s+/g, ' ').trim()
        if (text) {
          const at = Date.now()
          const goal = this.store.goals.find(g => g.sessionId === record.sessionId)
          const owner = this.commitmentOwner(record, goal)
          if (owner !== undefined && session.header?.origin !== 'subagent' && !session.header?.parentSession) {
            const state: ChatCommitments = record.commitments?.owner === owner ? record.commitments : { owner, items: [] }
            // A short reply such as “done” answers the question most recently shown in this chat.
            const last = this.checkInMessages(record.sessionId).at(-1)
            if (last && last.at > (record.requestAt ?? 0)) {
              const asked = state.items.find(item => item.at === last.commitmentAt)
              if (asked) state.focus = asked.request
            }
            if (record.sessionId === this.watchMainSession()) {
              const access = this.ctx.nanomuseCloud.scheduleSessionAccess(record.sessionId)
              this.queueWatchInput(textOf(event.data.content), true, createHash('sha256').update(JSON.stringify([record.sessionId, record.turns, record.startedAt])).digest('hex'), () =>
                owner === this.ctx.nanomuseCloud.feedOwner && record.sessionId === this.watchMainSession() && access(record.sessionId))
            }
            noteCommitment(state, text.slice(0, 200), at, goal)
            state.turn = record.turns
            record.commitments = state
          } else if (record.commitments) {
            // A turn we cannot track may have settled the open task.
            delete record.commitments
          }
          record.request = text.slice(0, 200)
          record.requestAt = at
          record.requestOwner = this.ctx.nanomuseCloud.feedOwner ?? ''
        }
        this.activityChanged(record, true)
        return
      }
      case 'tool/call': {
        const { name, arguments: raw, callId } = event.data
        const title = describeCall(name, raw)
        this.pushStep(record, { at: Date.now(), kind: 'tool', name, title, detail: prettyArgs(raw), result: '', callId: String(callId) })
        record.current = { name, title, at: Date.now(), own: ownWords(raw) !== '' }
        record.status = 'running'
        this.activityChanged(record)
        return
      }
      case 'tool/result': {
        const callId = String(event.data.message.toolCallId ?? '')
        const step = callId ? record.steps.find((s) => s.callId === callId) : undefined
        if (step) {
          step.ok = !event.data.message.isError
          const text = textOf(event.data.message.content as never).replace(/\r/g, '').trim()
          step.result = (event.data.error?.reason ? `${event.data.error.reason}\n` : '') + text.slice(0, STEP_TEXT)
        }
        if (record.current && (!step || step.name === record.current.name)) record.current = null
        this.activityChanged(record)
        return
      }
      case 'assistant/message': {
        const text = textOf(event.data.message.content)
        if (!text) return
        record.words = text.replace(/\s+/g, ' ').trim().slice(0, 300)
        const last = record.steps[record.steps.length - 1]
        if (last && last.kind === 'answer') {
          last.detail = text.slice(0, STEP_TEXT * 2)
          last.at = Date.now()
        } else this.pushStep(record, { at: Date.now(), kind: 'answer', name: '', title: '', detail: text.slice(0, STEP_TEXT * 2), result: '', callId: '' })
        this.activityChanged(record)
        return
      }
      case 'turn/end': {
        const reason = event.data.reason
        record.status = reason.kind === 'error' ? 'error' : reason.kind === 'completed' ? 'done' : 'stopped'
        record.current = null
        record.endedAt = Date.now()
        const state = record.commitments
        const focus = state?.owner === this.ctx.nanomuseCloud.feedOwner ? state?.items.find(i => i.request === state.focus) : undefined
        if (record.status === 'done' && state?.turn === record.turns && focus && !focus.closed && asksForDraft(focus.request) &&
            record.steps.some(s => s.kind === 'answer' && draftDelivered(s.detail))) {
          focus.closed = true
          focus.changedAt = record.endedAt
          focus.changed = true
        }
        this.pushStep(record, { at: Date.now(), kind: 'end', name: '', title: '', detail: reason.kind === 'error' ? String(reason.error.message ?? '') : reason.kind, result: '', callId: '' })
        this.activityChanged(record, true)
        if (this.watchInputs.length && record.sessionId === this.watchMainSession() && Date.now() - this.watchObservedAt >= 60_000) {
          this.watchObservedAt = Date.now()
          void this.checkPublicWatches(Date.now(), true).catch(() => this.warn('public source discovery', 'check deferred'))
        }
        return
      }
      default:
        return
    }
  }

  /** The person's language for what the agent writes here (`zh-CN`, `en`, …). */
  get lang(): string {
    return this.store.lang || Intl.DateTimeFormat().resolvedOptions().locale || 'en'
  }

  /** The goals, for the agent's prompt context. */
  get goals(): Goal[] {
    return this.store.goals.filter((goal) => !this.ctx.nanomuseCloud.isClearedSession(goal.sessionId))
  }

  /** The agent asks the window to open the avatar studio with these words (the person draws from there). */
  requestStudio(description: string, style: string): void {
    this.studio = { description: description.replace(/\s+/g, ' ').trim().slice(0, 200), style: style in STUDIO_STYLES ? style : 'muse', at: Date.now() }
    this.broadcast()
  }

  /** What the agent remembers about the person, newest last; for the prompt context and the Memory tab. */
  get memory(): readonly MemoryItem[] {
    return this.store.memory
  }

  /** Keep one line; a line already there (case and spacing aside) is refreshed, not doubled. */
  async remember(text: string, source: MemoryItem['source'] = 'agent'): Promise<MemoryItem | null> {
    const line = text.replace(/\s+/g, ' ').trim().slice(0, MEMORY_LINE)
    if (!line) return null
    const key = memoryKey(line)
    const existing = this.store.memory.find((m) => memoryKey(m.text) === key)
    if (existing) {
      existing.at = Date.now()
      if (source === 'person') { existing.prepOwner = this.ctx?.nanomuseCloud?.feedOwner; existing.source = source }
      await this.save()
      return existing
    }
    const item: MemoryItem = { id: newId('mem'), at: Date.now(), text: line, source, prepOwner: this.ctx?.nanomuseCloud?.feedOwner }
    this.store.memory.push(item)
    if (this.store.memory.length > MEMORY_MAX) this.store.memory.splice(0, this.store.memory.length - MEMORY_MAX)
    await this.save()
    return item
  }

  async forget(id: string): Promise<void> {
    const before = this.store.memory.length
    this.store.memory = this.store.memory.filter((m) => m.id !== id)
    if (this.store.memory.length !== before) await this.save()
  }

  /** Validate a whole import before changing memory; an import never evicts existing lines. */
  async importMemory(text: string): Promise<number> {
    const lines = text.split(/\r\n?|\n/).map((line) => line.replace(/^\s*(?:[-*•]|\d+[.)])(?:\s+|$)/, '').replace(/\s+/g, ' ').trim()).filter(Boolean)
    if (lines.length > 200) throw new RelayError(400, 'memory_import_lines', 'Import at most 200 lines at a time. Nothing was imported.')
    if (lines.some((line) => line.length > MEMORY_LINE)) throw new RelayError(400, 'memory_import_length', 'Each memory must fit within 400 characters. Nothing was imported.')
    const known = new Set(this.store.memory.map((item) => memoryKey(item.text)))
    const incoming: MemoryItem[] = []
    for (const line of lines) {
      const key = memoryKey(line)
      if (known.has(key)) continue
      known.add(key)
      incoming.push({ id: newId('mem'), at: Date.now(), text: line, source: 'import', prepOwner: this.ctx?.nanomuseCloud?.feedOwner })
    }
    if (this.store.memory.length + incoming.length > MEMORY_MAX) throw new RelayError(409, 'memory_import_capacity', 'Memory holds 400 entries. Remove unneeded entries or import fewer new lines. Nothing was imported.')
    if (lines.length) {
      this.store.memory.push(...incoming)
      try {
        // A retry must persist even when all its lines are already present in memory.
        await this.save(true)
      } catch {
        throw new RelayError(503, 'memory_import_save', 'Imported memories could not be saved. They are only in memory; check disk space and access, then retry before closing the app.')
      }
    }
    return incoming.length
  }

  /** Snapshot the catalogue through an agent's view; the registry shows nothing from the root. */
  private snapshotTools(agent: Agent): void {
    const tools = this.ctx.get('tools') as { schemas(scope?: object): { name: string; description: string }[] } | undefined
    if (!tools) return
    try {
      this.toolCatalog = tools.schemas(agent).map((tool) => ({ name: tool.name, description: tool.description }))
      this.catalogAt = Date.now()
    } catch (error: unknown) {
      this.warn('tool catalogue', error)
    }
  }

  /** The MCP servers behind the preset's tools (`mcp__<server>__<tool>`), and how many tools are the harness's own. */
  connectors(): { servers: { name: string; tools: { name: string; description: string }[] }[]; builtin: number; at: number } {
    const tools = this.toolCatalog
    const servers = new Map<string, { name: string; description: string }[]>()
    let builtin = 0
    for (const tool of tools) {
      const match = /^mcp__([^_]+(?:_[^_]+)*?)__(.+)$/.exec(tool.name)
      if (!match) {
        builtin++
        continue
      }
      const list = servers.get(match[1]!) ?? []
      list.push({ name: match[2]!, description: tool.description.split('\n')[0]!.slice(0, 160) })
      servers.set(match[1]!, list)
    }
    return { servers: [...servers].map(([name, list]) => ({ name, tools: list })), builtin, at: this.catalogAt }
  }

  // ---- data controls: the person's agent data, in a zip or gone ---------------------

  /**
   * Muse's "download your agent data": a zip in ~/Downloads with the account snapshot
   * (no token), the profile and faces, the rooms (feed, ideas, goals, library index,
   * memory) and the chats as dsh keeps them; the file manager shows it.
   */
  async exportData(): Promise<string> {
    const home = dshHome()
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const folder = await downloadsDir()
    const out = join(folder, `nanoMuse-data-${stamp}.zip`)
    await mkdir(folder, { recursive: true })
    const budget: ExportBudget = { files: 0, bytes: 0 }
    const entries: ExportSource[] = [
      ...await scanExportRoot(join(home, 'nanomuse'), 'nanomuse/', budget, (name) => name.endsWith('.tmp')),
      ...await scanExportRoot(join(home, 'sessions'), 'sessions/', budget),
    ]
    const prefs = join(home, 'desktop.json')
    const prefsInfo = await lstat(prefs).catch(() => null)
    if (prefsInfo?.isFile()) {
      // the proxy address may carry a password: the export never does
      entries.push({ name: 'desktop.json', data: redactProxyUserinfo(await readFile(prefs)), at: prefsInfo.mtime })
    }
    entries.push({ name: 'README.txt', at: new Date(), data: Buffer.from(['Your nanoMuse data, exported ' + new Date().toISOString(), '', 'nanomuse/cloud.json    the account snapshot (no sign-in token)', 'nanomuse/profile.json  the agent’s name and look; faces/ its pictures', 'nanomuse/rooms.json    feed, ideas, goals, the library index and memory', 'sessions/              the chats, as DeepSeek Harness keeps them (zstd-compressed JSON lines)', ''].join('\n'))})
    await writeZipFile(out, entries)
    const sc = this.ctx.get('sessionController')
    if (sc) await sc.openWorkspacePath({ path: out, action: 'reveal' }, new AbortController().signal).catch(() => undefined)
    return out
  }

  /** Muse's "reset": memory, rooms and the local profile go, the account signs out; the chats stay (dsh's). */
  async resetData(): Promise<void> {
    this.resetWatchWork()
    for (const goal of this.store.goals) this.goalBySession.delete(goal.sessionId)
    this.store = { ...structuredClone(EMPTY), lang: this.store.lang }
    this.automations = {}
    await this.save()
    await this.ctx.nanomuseCloud.signOut().catch(() => undefined)
    await rm(join(dshHome(), 'nanomuse', 'profile.json'), { force: true }).catch(() => undefined)
    await rm(join(dshHome(), 'nanomuse', 'faces'), { recursive: true, force: true }).catch(() => undefined)
  }

  get feedInstructions(): string {
    return this.store.feed.instructions
  }

  private broadcast(): void {
    const frame = `data: ${JSON.stringify(this.view())}\n\n`
    for (const res of this.streams) {
      try {
        res.write(frame)
      } catch {
        this.streams.delete(res)
      }
    }
  }

  // ---- feed ------------------------------------------------------------------------

  async setFeedInstructions(text: string): Promise<void> {
    this.store.feed.instructions = text.trim().slice(0, 2000)
    await this.save()
  }

  async likePost(id: string, on: boolean): Promise<void> {
    const post = this.store.feed.posts.find((p) => p.id === id)
    if (!post) throw new RelayError(404, 'not_found', 'No such post')
    post.liked = on
    await this.save()
  }

  async deletePost(id: string): Promise<void> {
    const post = this.store.feed.posts.find(p => p.id === id)
    if (post?.preparation?.sources.some(source => source.id === this.store.feed.preparation?.published?.source)) {
      delete this.store.feed.preparation!.published
    }
    const covered = new Set(post?.preparation?.sources.map(s => s.goalId))
    this.store.feed.posts = this.store.feed.posts.filter(p => p.id !== id && (!p.goalId || !covered.has(p.goalId)))
    await this.save()
  }

  /** A post the agent (or a tool) writes directly, newest first. */
  async addPost(input: { title: string; body: string; area?: string; emoji?: string; image?: string; prompt?: string }): Promise<FeedPost> {
    const post: FeedPost = {
      id: newId('post'),
      at: Date.now(),
      title: input.title.trim().slice(0, 120),
      body: input.body.trim().slice(0, 4000),
      area: area(input.area),
      emoji: oneEmoji(input.emoji),
      image: httpsUrl(input.image),
      prompt: (input.prompt ?? '').trim().slice(0, 500),
      liked: false,
    }
    this.store.feed.posts = [post, ...this.store.feed.posts].slice(0, FEED_KEEP)
    await this.save()
    return post
  }

  private prepSources(now: number, posts?: FeedPost[]): Source[] {
    const cloud = this.ctx.nanomuseCloud
    const owner = cloud.feedOwner
    if (owner === undefined) return []
    const accessible = cloud.scheduleSessionAccess('nanomuse-feed')
    return preparationSources({ owner, accessible: id => accessible(id) && !this.isBatch(id),
      goals: this.store.goals, files: this.store.library, memory: this.memory, activity: this.store.activity }, now,
      posts ? new Set(posts.flatMap(p => p.preparation?.sources.map(s => s.id) ?? [])) : undefined)
  }

  private prepVisible(post: FeedPost, sources: Source[]): boolean {
    const p = post.preparation
    return !p || (p.owner === this.ctx.nanomuseCloud.feedOwner && p.expiresAt > Date.now() && p.sources.every(ref => sources.some(s => s.id === ref.id)))
  }

  /** One read-only model call. Recheck the sources after the await: a goal may have finished
   * or the person may have forgotten a memory, muted a goal, or switched accounts meanwhile. */
  async prepareFeed(manual = false): Promise<'prepared' | 'quiet' | 'busy'> {
    const feed = this.store.feed
    const now = Date.now()
    const day = localDateKey(now)
    if (this.busy.feed) return 'busy'
    if (!manual && (!feed.routine.on || !routineDue(feed.routine.time, 0, now))) return 'quiet'
    const cloud = this.ctx.nanomuseCloud
    const owner = cloud.feedOwner
    if (owner === undefined) return 'quiet'
    const access = cloud.scheduleSessionAccess('nanomuse-feed')
    const replacement = !manual && feed.preparation?.day === day
    const published = feed.preparation?.published
    if (replacement && (!published || published.owner !== owner || feed.preparation?.revisedOn === day)) return 'quiet'
    const forReview = (at: number) => {
      const all = this.prepSources(at)
      if (!replacement || !published) return all
      const revised = all.find(s => s.commitment === published.subject && s.id !== published.source)
      return revised ? [revised, ...all.filter(s => !s.timing && s.origin !== revised.origin)] : []
    }
    const sources = forReview(now)
    if (!canPrepare(sources)) return 'quiet'
    const key = contextKey(sources, this.lang, feed.instructions, owner)
    if (!manual && key === feed.preparation?.context) return 'quiet'
    this.busy.feed = true
    this.prepLastTry = now
    const abort = new AbortController()
    this.prepAbort = abort
    const timeout = setTimeout(() => abort.abort(), 90_000)
    const lang = this.lang, instructions = feed.instructions
    this.broadcast()
    try {
      const request = preparationRequest(sources, instructions, lang, now)
      const answer = await cloud.prepareFeed(request.system, request.input, abort.signal)
      if (abort.signal.aborted || !access('nanomuse-feed') || cloud.feedOwner !== owner || this.store.feed !== feed ||
          this.lang !== lang || feed.instructions !== instructions || (!manual && !feed.routine.on)) return 'quiet'
      const current = forReview(Date.now())
      if (localDateKey(Date.now()) !== day || contextKey(current, lang, instructions, owner) !== key) return 'quiet'
      const result = parsePreparation(answer, sources, owner, now)
      const seen = feed.preparation?.seen ?? []
      const publish = result && !seen.includes(result.preparation.key)
      const prevState = feed.preparation
      const prevPosts = feed.posts
      let addedId = ''
      if (publish) {
        addedId = newId('post')
        feed.posts = [{ ...result, id: addedId, at: Date.now(), area: 'planning', image: '', prompt: '', emoji: '📝', liked: false }, ...feed.posts].slice(0, FEED_KEEP)
      }
      const anchor = publish ? sources.find(s => s.commitment && result.preparation.sources.some(ref => ref.id === s.id)) : undefined
      feed.preparation = { ...prevState, context: key, day: publish ? localDateKey(Date.now()) : prevState?.day ?? '',
        seen: publish ? [result.preparation.key, ...seen].slice(0, FEED_KEEP) : seen,
        ...(replacement ? { revisedOn: day } : {}),
      }
      if (publish && anchor?.commitment) feed.preparation.published = { owner, subject: anchor.commitment, source: anchor.id }
      else if (publish) delete feed.preparation.published
      try {
        await this.save(true, true)
      } catch (error) {
        // Only roll back our own rows; likes or new posts may have arrived during the write.
        if (addedId) {
          const unchanged = feed.posts[0]?.id === addedId && feed.posts.slice(1).every((p, i) => p.id === prevPosts[i]?.id)
          feed.posts = unchanged ? prevPosts : feed.posts.filter(post => post.id !== addedId)
        }
        if (prevState) feed.preparation = prevState
        else delete feed.preparation
        throw error
      }
      return publish ? 'prepared' : 'quiet'
    } finally {
      clearTimeout(timeout)
      this.prepAbort = undefined
      this.busy.feed = false
      this.broadcast()
    }
  }

  async refreshFeed(): Promise<void> {
    if (this.busy.feed) return
    this.busy.feed = true
    this.store.feed.lastTry = Date.now()
    this.broadcast()
    try {
      const before = this.store.feed.posts.length
      const zh = this.lang.startsWith('zh')
      const text = await this.run(zh ? '动态 · ' + today(this.lang) : 'Feed · ' + today(this.lang), this.feedPrompt(), zh ? '写今天的动态' : "Writing today's feed")
      const rows = parseArray(text)
      const now = Date.now()
      const posts: FeedPost[] = []
      // the agent may also have posted with `feed_post` as it went; the JSON then repeats those
      const seen = new Set(this.store.feed.posts.map((p) => titleKey(p.title)))
      for (const row of rows.slice(0, 8)) {
        const title = str(row.title).slice(0, 120)
        const body = str(row.body).slice(0, 4000)
        if (!title || !body || seen.has(titleKey(title))) continue
        seen.add(titleKey(title))
        posts.push({ id: newId('post'), at: now, title, body, area: area(str(row.area)), emoji: oneEmoji(str(row.emoji)), image: httpsUrl(str(row.image)), prompt: str(row.prompt).slice(0, 500), liked: false })
      }
      if (posts.length === 0 && this.store.feed.posts.length === before) throw new Error('the batch came back empty')
      this.store.feed.posts = [...posts, ...this.store.feed.posts].slice(0, FEED_KEEP)
      this.store.feed.generatedAt = now
      await this.save()
      this.ctx.logger.info('nanomuse rooms: %d feed posts written', posts.length)
    } finally {
      this.busy.feed = false
      this.broadcast()
    }
  }

  /** A chat about one post: the agent opens with what is worth knowing, then listens. */
  async discuss(id: string): Promise<string> {
    const post = this.store.feed.posts.find((p) => p.id === id)
    if (!post) throw new RelayError(404, 'not_found', 'No such post')
    if (post.preparation) {
      if (!this.prepVisible(post, this.prepSources(Date.now(), [post]))) throw new RelayError(404, 'not_found', 'This preparation is unavailable')
      return post.preparation.sessionId
    }
    if (post.goalId) {
      const goal = this.store.goals.find((g) => g.id === post.goalId)
      if (!goal || goal.feedMuted || goal.status !== 'tracking' || (post.goalExpiresAt ?? 0) <= Date.now() || this.ctx.nanomuseCloud.isClearedSession(goal.sessionId)) throw new RelayError(404, 'not_found', 'This goal is unavailable')
      return goal.sessionId
    }
    if (post.sessionId && (await this.alive(post.sessionId))) return post.sessionId
    const zh = this.lang.startsWith('zh')
    const framing = zh
      ? `[这是你之前写进这个人「动态」里的一条帖子，对方现在想聊聊它。先用一两句话说清楚最值得知道的，以及你接下来能帮上什么，然后听对方说。]`
      : `[A post you wrote for this person's feed earlier; they want to talk about it. Open with one or two sentences — what is worth knowing, what you could do next — and then listen.]`
    const sessionId = await this.open(post.title, `${framing}\n\n**${post.title}**\n\n${post.body}`, { notice: zh ? `讨论动态 · ${post.title}` : `Discuss · ${post.title}` })
    post.sessionId = sessionId
    await this.save()
    return sessionId
  }

  // ---- ideas -----------------------------------------------------------------------

  /** The curated list for the person's language (the phone's `Ideas.load`); zh-* reads the zh file. */
  private staticIdeas(): StaticIdea[] {
    const file = this.lang.toLowerCase().startsWith('zh') ? 'ideas.zh.json' : 'ideas.en.json'
    if (this.ideasCache?.file === file) return this.ideasCache.items
    let items: StaticIdea[] = []
    try {
      items = parseIdeas(readFileSync(join(ASSETS_DIR, file), 'utf8'))
    } catch (error: unknown) {
      this.warn('ideas list', error)
    }
    this.ideasCache = { file, items }
    return items
  }

  /** The list with the person's marks on it, as the room shows it. */
  private ideaItems(): Idea[] {
    const marks = this.store.ideas.marks
    return this.staticIdeas().map((idea) => {
      const mark = marks[idea.id]
      return {
        id: idea.id,
        at: 0,
        group: idea.sectionTitle,
        emoji: idea.emoji,
        title: idea.title,
        detail: idea.body,
        includes: [],
        how: '',
        prompt: idea.prompt,
        area: idea.section,
        kind: idea.kind,
        ...(idea.time ? { time: idea.time } : {}),
        ...(idea.category ? { category: idea.category } : {}),
        ...(mark?.started ? { started: mark.started } : {}),
        ...(mark?.dismissed ? { dismissed: true } : {}),
      }
    })
  }

  /** A chat opened from an idea (the person pressed Send to chat and the message went out there). */
  async markIdea(id: string, sessionId: string): Promise<void> {
    if (!this.staticIdeas().some((i) => i.id === id)) throw new RelayError(404, 'not_found', 'No such idea')
    this.store.ideas.marks[id] = { ...this.store.ideas.marks[id], started: sessionId }
    await this.save()
  }

  /**
   * Try an idea the way the phone does: a routine idea becomes a daily schedule (its
   * own chat, the idea's time, the idea's words); a goal idea opens the goal conversation
   * with the idea's words as the seed. Chat ideas are the browser's: it puts the words in
   * the composer. Answers with the chat to open.
   */
  async startIdea(id: string): Promise<{ sessionId: string; scheduleId?: string }> {
    const idea = this.staticIdeas().find((i) => i.id === id)
    if (!idea) throw new RelayError(404, 'not_found', 'No such idea')
    const mark = this.store.ideas.marks[id]
    if (mark?.started && (await this.alive(mark.started))) return { sessionId: mark.started }
    const zh = this.lang.startsWith('zh')
    let result: { sessionId: string; scheduleId?: string }
    if (idea.kind === 'goal') {
      result = await this.beginGoal(goalCategory(idea.category), idea.prompt)
    } else if (idea.kind === 'routine') {
      const schedule = this.ctx.get('schedule') as ScheduleLike | undefined
      if (!schedule) throw new RelayError(503, 'no_schedule', zh ? '例程还不可用' : 'Routines are not available yet')
      const time = idea.time ?? '09:00'
      const framing = zh
        ? `[对方从「点子」里选了这一条例程：「${idea.title}」。每天 ${time} 会在这个对话里收到下面这句话；收到时直接去做，不用问。现在先用一两句话说明你每天会做什么，不要开始做。]`
        : `[The person picked this routine from their Ideas room: "${idea.title}". Every day at ${time} this chat receives the line below; when it arrives, do it without asking. For now, say in a sentence or two what you will do each day; do not start yet.]`
      const sessionId = await this.open(idea.title.slice(0, 80), `${framing}\n\n${idea.prompt}`, { notice: zh ? `新例程 · ${idea.title.slice(0, 40)}` : `New routine · ${idea.title.slice(0, 40)}` })
      const created = await schedule.create(sessionId as SessionId, {
        prompt: idea.prompt,
        title: idea.title.slice(0, 120),
        daily: { time: `${time}:00`, time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' },
      })
      result = { sessionId, scheduleId: created.id }
    } else {
      const framing = zh
        ? `[对方从「点子」里选了这一条：「${idea.title}」。直接开始做；需要对方补充的信息，一次问清。]`
        : `[The person picked this from their Ideas room: "${idea.title}". Start on it; ask for what you need from them in one go.]`
      result = { sessionId: await this.open(idea.title.slice(0, 80), `${framing}\n\n${idea.prompt}`, { notice: zh ? `从「点子」开始 · ${idea.title.slice(0, 40)}` : `From Ideas · ${idea.title.slice(0, 40)}` }) }
    }
    this.store.ideas.marks[id] = { ...mark, started: result.sessionId }
    await this.save()
    return result
  }

  async dismissIdea(id: string): Promise<void> {
    if (!this.staticIdeas().some((i) => i.id === id)) return
    this.store.ideas.marks[id] = { ...this.store.ideas.marks[id], dismissed: true }
    await this.save()
  }

  // ---- goals -----------------------------------------------------------------------

  async createGoal(input: { title?: string | undefined; category?: string | undefined; text: string; due?: string | undefined }): Promise<Goal> {
    const text = input.text.trim()
    if (input.due && !validGoalDate(input.due)) throw new RelayError(400, 'invalid_due', 'Use a valid date for the deadline')
    if (!text) throw new RelayError(400, 'usage', 'Say what the goal is')
    const category = (CATEGORIES as readonly string[]).includes(input.category ?? '') ? (input.category as Category) : 'other'
    const title = (input.title ?? '').trim().slice(0, 80) || goalTitle(text)
    const id = newId('goal')
    const zh = this.lang.startsWith('zh')
    const framing = zh
      ? `[这是对方在「目标」里新建的一个目标（分类：${categoryLabel(category, true)}，id ${id}）。这个对话就是这个目标的家：先用几句话说清楚你打算怎么帮、需要对方给什么；如果定期检查有用（比如每天查一次价、每周回顾一次），就用 schedule_create 在这里建一个定时任务；第一轮就调用 goals_room_update（goal_id "${id}"）给目标起一个 12 字以内的短标题（title）和一句话 summary；之后每当有值得记下的进展，再调用 goals_room_update 加一条 activity。回复要短。]`
      : `[A goal the person set in their Goals room (category: ${categoryLabel(category, false)}, id ${id}). This chat is the goal's home: say in a few sentences how you will help and what you need from them; when a recurring check helps (a daily price check, a weekly review), set it up here with schedule_create; in this first turn call goals_room_update (goal_id "${id}") with a short title (eight words at most) and a one-line summary; and whenever something worth noting happens later, call goals_room_update again with an activity entry. Keep replies short.]`
    const sessionId = await this.open(title, `${framing}\n\n${text}`, { notice: zh ? `新目标 · ${title}` : `New goal · ${title}` })
    const now = Date.now()
    const goal: Goal = { id, title, description: text.slice(0, 2000), category, ...(input.due ? { due: input.due } : {}), status: 'tracking', sessionId, createdAt: now, updatedAt: now, summary: '', activity: [], steps: [], progress: -1, attention: false }
    this.store.goals = [goal, ...this.store.goals]
    this.goalBySession.set(sessionId, id)
    await this.save()
    return goal
  }

  /** From the room (status, title) or from the agent (`goals_room_update`: summary, activity). */
  async updateGoal(ref: string, patch: { title?: string; description?: string; status?: string; summary?: string; due?: string; nextStep?: string; feedMuted?: boolean; activity?: { title: string; text?: string } }): Promise<Goal> {
    const goal = this.findGoal(ref)
    if (!goal) throw new RelayError(404, 'not_found', `No goal "${ref}"`)
    if (patch.due !== undefined && patch.due !== '' && !validGoalDate(patch.due)) throw new RelayError(400, 'invalid_due', 'Use a valid date for the deadline')
    const dateChanged = typeof patch.due === 'string' && patch.due !== (goal.due ?? '')
    if (typeof patch.due === 'string') {
      if (patch.due) goal.due = patch.due
      else delete goal.due
    }
    if (typeof patch.nextStep === 'string') goal.nextStep = patch.nextStep.trim().slice(0, 240)
    if (typeof patch.feedMuted === 'boolean') goal.feedMuted = patch.feedMuted
    if (typeof patch.title === 'string' && patch.title.trim()) goal.title = patch.title.trim().slice(0, 80)
    if (typeof patch.description === 'string') goal.description = patch.description.trim().slice(0, 2000)
    const wasDone = goal.status === 'done'
    if (patch.status === 'tracking' || patch.status === 'done' || patch.status === 'paused') goal.status = patch.status
    if (goal.status === 'done' && !wasDone) void this.askNudge('goal_done').catch((error: unknown) => this.warn('nudges', error))
    if (typeof patch.summary === 'string') goal.summary = patch.summary.trim().slice(0, 240)
    if (patch.activity && typeof patch.activity.title === 'string' && patch.activity.title.trim()) {
      goal.activity = [{ at: Date.now(), title: patch.activity.title.trim().slice(0, 120), text: (patch.activity.text ?? '').trim().slice(0, 600) }, ...goal.activity].slice(0, ACTIVITY_KEEP)
    }
    goal.updatedAt = Date.now()
    this.refreshGoalPost(goal, dateChanged)
    await this.save()
    return goal
  }

  async deleteGoal(id: string): Promise<void> {
    const goal = this.store.goals.find((g) => g.id === id)
    if (!goal) return
    this.store.goals = this.store.goals.filter((g) => g.id !== id)
    this.goalBySession.delete(goal.sessionId)
    delete this.automations[id]
    this.store.feed.posts = this.store.feed.posts.filter((post) => post.goalId !== id)
    await this.save()
    // Its automations stop with it; the chat stays in the archive.
    const schedule = this.ctx.get('schedule') as ScheduleLike | undefined
    if (schedule) {
      const list = await schedule.list({ sessionId: goal.sessionId as SessionId }).catch(() => [])
      for (const record of list) await schedule.delete({ sessionId: goal.sessionId as SessionId, id: record.id }).catch(() => undefined)
    }
    await (this.ctx.get('workspaceRegistry') as RegistryLike | undefined)?.archiveSession(goal.sessionId as SessionId, { stopActivity: true }).catch(() => undefined)
  }

  /** "How is it going?" in the goal's chat; returns the chat to open. */
  async checkIn(id: string): Promise<string> {
    const goal = this.store.goals.find((g) => g.id === id)
    if (!goal) throw new RelayError(404, 'not_found', 'No such goal')
    const zh = this.lang.startsWith('zh')
    const prompt = zh
      ? `[来自「目标」的进度确认] 「${goal.title}」进展如何？简短说明上次之后有什么变化、下一步是什么，并用 goals_room_update 更新一句话 summary。`
      : `[A check-in from the Goals room] How is "${goal.title}" going? Briefly: what changed since last time and what is next; update the one-line summary with goals_room_update.`
    const notice = zh ? `进度确认 · ${goal.title}` : `Check-in · ${goal.title}`
    if (!(await this.alive(goal.sessionId))) {
      goal.sessionId = await this.open(goal.title, prompt, { notice })
      this.goalBySession.set(goal.sessionId, goal.id)
      await this.save()
      return goal.sessionId
    }
    await this.say(goal.sessionId as SessionId, prompt, undefined, notice)
    return goal.sessionId
  }

  async deleteAutomation(goalId: string, scheduleId: string): Promise<void> {
    const goal = this.store.goals.find((g) => g.id === goalId)
    const schedule = this.ctx.get('schedule') as ScheduleLike | undefined
    if (!goal || !schedule) return
    await schedule.delete({ sessionId: goal.sessionId as SessionId, id: scheduleId })
    await this.refreshAutomations()
  }

  private findGoal(ref: string): Goal | undefined {
    const key = ref.trim().toLowerCase()
    return this.store.goals.find((g) => g.id === ref) ?? this.store.goals.find((g) => g.title.toLowerCase() === key) ?? this.store.goals.find((g) => g.title.toLowerCase().includes(key) && key.length >= 4)
  }

  private async refreshAutomations(): Promise<void> {
    const schedule = this.ctx.get('schedule') as ScheduleLike | undefined
    if (!schedule) return
    const next: Record<string, GoalAutomation[]> = {}
    for (const goal of this.store.goals) {
      const list = await schedule.list({ sessionId: goal.sessionId as SessionId }).catch(() => [])
      if (list.length) next[goal.id] = list.map((r) => ({ id: r.id, title: r.title, kind: r.kind, rule: ruleOf(r), next: r.scheduledAt }))
    }
    if (JSON.stringify(next) === JSON.stringify(this.automations)) return
    this.automations = next
    this.broadcast()
  }

  // ---- library ---------------------------------------------------------------------

  /** A file the agent delivered (a `present` call, `library_add`, or the room's own creations). */
  async addToLibrary(path: string, description: string, sessionId: string, cwd?: string): Promise<LibraryItem | undefined> {
    const full = isAbsolute(path) ? path : resolve(cwd ?? process.cwd(), path)
    let info: Awaited<ReturnType<typeof stat>>
    try {
      info = await stat(full)
    } catch {
      return undefined
    }
    if (!info.isFile()) return undefined
    const ext = extname(full).toLowerCase()
    const existing = this.store.library.find((i) => i.path === full)
    const item: LibraryItem = existing ?? { id: newId('lib'), path: full, name: basename(full), kind: KINDS[ext] ?? 'file', description: '', sessionId, at: 0 }
    item.at = Date.now()
    if (description.trim()) item.description = description.trim().slice(0, 300)
    if (sessionId) item.sessionId = sessionId
    this.store.library = [item, ...this.store.library.filter((i) => i !== item)].slice(0, LIBRARY_KEEP)
    await this.save()
    return item
  }

  async removeFromLibrary(id: string): Promise<void> {
    this.store.library = this.store.library.filter((i) => i.id !== id)
    await this.save()
  }

  /**
   * A blank Markdown file in the Library folder, for the person to write in the editor
   * themselves (#689): `Untitled.md` (`未命名.md`), numbered when the name is taken.
   */
  async newDocument(name: string): Promise<LibraryItem> {
    const folder = this.libraryFolder()
    await mkdir(folder, { recursive: true })
    const stem = safeStem(name) || (this.lang.startsWith('zh') ? '未命名' : 'Untitled')
    const path = await freePath(folder, stem, '.md')
    await writeFile(path, '', { encoding: 'utf8', flag: 'wx' })
    const item = await this.addToLibrary(path, '', '')
    if (!item) throw new RelayError(500, 'internal', 'The file could not be listed')
    return item
  }

  /**
   * A file brought in from disk (#689): its text is written under the Library folder with the
   * name it had (numbered when taken) and listed on the Documents shelf, so the editor shows it
   * and a Library chat can read it. Markdown and plain text only for now; other formats will
   * come once there is a conversion to Markdown.
   */
  async importDocument(name: string, text: string): Promise<LibraryItem> {
    const ext = extname(name).toLowerCase()
    if (!IMPORT_KINDS.has(ext)) throw new RelayError(415, 'unsupported', 'Only Markdown and plain-text files can be imported for now')
    if (Buffer.byteLength(text, 'utf8') > IMPORT_MAX_BYTES) throw new RelayError(413, 'too_large', 'The file is too large to import')
    const folder = this.libraryFolder()
    await mkdir(folder, { recursive: true })
    const path = await freePath(folder, safeStem(name) || 'Document', ext)
    await writeFile(path, text, { encoding: 'utf8', flag: 'wx' })
    const item = await this.addToLibrary(path, '', '')
    if (!item) throw new RelayError(500, 'internal', 'The file could not be listed')
    return item
  }

  /** A new document / web page / video / podcast: a chat where the agent makes it and presents the file. */
  async createArtifact(kind: string, brief: string): Promise<string> {
    const text = brief.trim()
    if (!text) throw new RelayError(400, 'usage', 'Say what to make')
    const zh = this.lang.startsWith('zh')
    const folder = this.libraryFolder()
    const what: Record<string, [string, string]> = {
      document: ['a document (Markdown, `.md`, unless the person asks for another format)', '一份文档（默认 Markdown `.md`，除非对方要别的格式）'],
      web: ['a self-contained web page (`.html`, inline CSS/JS)', '一个独立的网页（`.html`，样式脚本内联）'],
      video: ['a short video (`.mp4`; e.g. ffmpeg over generated frames or slides — say so if the tools for it are missing)', '一段短视频（`.mp4`，比如用 ffmpeg 把生成的画面或幻灯片拼起来；缺工具就直说）'],
      audio: ['a short podcast episode (`.mp3`/`.m4a`; a script first, then speech with whatever text-to-speech is available — say so if none is)', '一期短播客（`.mp3`/`.m4a`：先写稿，再用可用的文字转语音生成；没有就直说）'],
    }
    const pair = what[kind] ?? what.document!
    const framing = zh
      ? `[对方在「资源库」里点了「创建」：请做${pair[1]}，保存到 ${folder}/（没有就创建），做完用 present 声明这个文件，让它出现在对方的资源库里。先做再说，简短汇报。]`
      : `[The person pressed "Create" in their Library: make ${pair[0]}, save it under ${folder}/ (create the folder if needed), and declare the file with present when done so it appears in their Library. Make it first, then report briefly.]`
    await mkdir(folder, { recursive: true })
    const title = firstLine(text).slice(0, 60)
    return this.open(title, `${framing}\n\n${text}`, { cwd: folder, preset: 'workspace-write', notice: zh ? `创建构件 · ${title}` : `Create · ${title}` })
  }

  /**
   * Muse's "+ 创建图片 / 视频 / 文档" opens a chat with the composer prefilled, so the
   * person says what they want in their own words: this is that chat, empty, in the
   * Library folder with the right permissions; the window prefills the composer.
   */
  async openCreationChat(kind: string): Promise<string> {
    const sc = this.ctx.get('sessionController')
    if (!sc) throw new RelayError(503, 'no_sessions', 'Chats are not available yet')
    const folder = this.libraryFolder()
    await mkdir(folder, { recursive: true })
    const zh = this.lang.startsWith('zh')
    const names: Record<string, [string, string]> = { document: ['New document', '新文档'], web: ['New web page', '新网页'], image: ['New image', '新图片'], video: ['New video', '新视频'], audio: ['New podcast', '新播客'] }
    const pair = names[kind] ?? names.document!
    // The chat belongs to the Library folder as a workspace: an empty chat whose
    // folder is only a cwd shows the client's "pick a workspace" state instead of
    // the composer, and the person is meant to type first here.
    let workspaceId: string | undefined
    try {
      workspaceId = (await (this.ctx.get('workspaceRegistry') as RegistryLike | undefined)?.create(folder, zh ? '资源库' : 'Library'))?.id
    } catch (error) {
      this.warn('library workspace', error)
    }
    const created = await sc.create(workspaceId ? { agentPreset: 'nanomuse', workspaceId: workspaceId as NonNullable<SessionCreateRequest['workspaceId']> } : { agentPreset: 'nanomuse', cwd: folder })
    await sc.rename({ sessionId: created.sessionId, title: zh ? pair[1] : pair[0] }).catch(() => undefined)
    const resolved = await sc.resolveAgent(created.sessionId)
    if (!('error' in resolved)) {
      const presets = this.ctx.get('permissionPresets') as PresetsLike | undefined
      if (presets?.names.includes('workspace-write')) {
        try {
          presets.set(resolved.agent.session, 'workspace-write')
        } catch (error) {
          this.warn('permission preset', error)
        }
      }
    }
    return created.sessionId
  }

  /** Where the room's own creations go: `~/nanoMuse/Library` (`~/nanoMuse/构件` in Chinese). */
  libraryFolder(): string {
    return join(homeDir(), 'nanoMuse', this.lang.startsWith('zh') ? '构件' : 'Library')
  }

  // ---- the agent's sessions -------------------------------------------------------------

  /**
   * A chat the person will see. It starts in the home workspace (`~/nanoMuse`, as the main
   * chat does; never the bare home folder, #705); a `preset` of `workspace-write` (used for
   * the Library's creations, whose cwd is the Library folder) lets the agent write there
   * without asking — everything outside still asks, as the deployment's presets say.
   */
  private async open(title: string, prompt: string, options: { cwd?: string; preset?: string; notice?: string } = {}): Promise<string> {
    const sc = this.ctx.get('sessionController')
    if (!sc) throw new RelayError(503, 'no_sessions', 'Chats are not available yet')
    const created = await sc.create(options.cwd ? { agentPreset: 'nanomuse', cwd: options.cwd } : await homeWorkspace(this.ctx, (error) => this.warn('home workspace', error)))
    await sc.rename({ sessionId: created.sessionId, title: title.slice(0, 80) }).catch(() => undefined)
    await this.say(created.sessionId, prompt, options.preset, options.notice ?? title)
    return created.sessionId
  }

  /**
   * Put words in a chat and let the agent answer. With a `notice`, the message is the
   * rooms' (a compact context row that reads as the notice, as the harness shows a
   * schedule's wake), not a bubble in the person's voice — an idea picked, a goal begun.
   */
  private async say(sessionId: SessionId, prompt: string, preset?: string, notice?: string): Promise<Agent> {
    const sc = this.ctx.get('sessionController')
    if (!sc) throw new RelayError(503, 'no_sessions', 'Chats are not available yet')
    const resolved = await sc.resolveAgent(sessionId)
    if ('error' in resolved) throw new RelayError(409, 'session', `The chat could not be opened: ${String(resolved.error)}`)
    if (resolved.agent.status !== 'idle') throw new RelayError(409, 'busy', 'That chat is busy right now')
    this.snapshotTools(resolved.agent)
    if (preset) {
      const presets = this.ctx.get('permissionPresets') as PresetsLike | undefined
      if (presets?.names.includes(preset)) {
        try {
          presets.set(resolved.agent.session, preset)
        } catch (error) {
          this.warn('permission preset', error)
        }
      }
    }
    const source = notice ? ({ kind: 'nanomuse', form: 'notice', summary: notice.slice(0, 120) } as const) : ({ kind: 'user' } as const)
    resolved.agent.followup(createUserMessage({ content: [{ type: 'text', text: prompt }], source }))
    return resolved.agent
  }

  /**
   * "Create goal › category" (the phone's `startGoal`): the opener goes into the chat the
   * person is in when that chat is free, otherwise into a fresh one; the agent asks at most
   * three questions and writes a `nanomuse-goal` block, which `applyFences` turns into the
   * goal, its chat and its checks. Answers with the chat to open.
   */
  async beginGoal(category: Category, seed?: string, sessionId?: string): Promise<{ sessionId: string }> {
    const zh = this.lang.startsWith('zh')
    const label = categoryLabel(category, zh)
    const opener = goalOpener(label, zh) + (seed?.trim() ? ` ${seed.trim()}` : '')
    const prompt = `${goalCreationNote(category, zh)}\n\n${opener}`
    const notice = zh ? `新目标 · ${label}` : `New goal · ${label}`
    if (sessionId && (await this.alive(sessionId))) {
      try {
        await this.say(sessionId as SessionId, prompt, undefined, notice)
        return { sessionId }
      } catch (error: unknown) {
        if (!(error instanceof RelayError && error.code === 'busy')) throw error
      }
    }
    return { sessionId: await this.open(zh ? `${label}目标` : `${label} goal`, prompt, { notice }) }
  }

  /**
   * The agent's message closed with app fences (the phone's `GoalFlow.afterTurn` and
   * `FeedFlow.afterTurn`): a `nanomuse-goal` block becomes a goal with its chat and its
   * checks, `nanomuse-goal-update` moves a goal along, `nanomuse-feed` posts to the Feed.
   */
  private async applyFences(sessionId: string, words: string): Promise<void> {
    for (const json of findFences(words, FENCE_GOAL)) {
      const block = parseGoalBlock(json)
      if (!block) continue
      // the model may repeat a block it wrote earlier; one goal per title
      if (this.store.goals.some((g) => g.title.toLowerCase() === block.title.toLowerCase())) continue
      await this.createGoalFromBlock(block, sessionId)
    }
    for (const json of findFences(words, FENCE_GOAL_UPDATE)) {
      const update = parseGoalUpdate(json)
      if (update) await this.applyGoalUpdate(update, sessionId)
    }
    const drafts = findFences(words, FENCE_FEED).map(parseFeedDraft)
    if (drafts.some(Boolean)) {
      const day = new Date().toDateString()
      const today = new Set(this.store.feed.posts.filter((p) => new Date(p.at).toDateString() === day).map((p) => titleKey(p.title)))
      for (const draft of drafts) {
        if (!draft || today.has(titleKey(draft.title))) continue
        today.add(titleKey(draft.title))
        await this.addPost({ title: draft.title, body: draft.body, area: draft.type, emoji: draft.emoji })
      }
    }
  }

  /** The goal a `nanomuse-goal` block describes: its home is the chat it was shaped in, unless that chat already has a goal. */
  private async createGoalFromBlock(block: GoalBlock, sessionId: string): Promise<Goal> {
    const zh = this.lang.startsWith('zh')
    const id = newId('goal')
    const home = this.goalBySession.has(sessionId) || !(await this.alive(sessionId))
      ? await this.open(block.title, goalHomeNote({ ...block, id }, zh), { notice: zh ? `新目标 · ${block.title}` : `New goal · ${block.title}` })
      : sessionId
    const now = Date.now()
    const description = [block.why, ...block.steps.map((step) => `- ${step}`)].filter(Boolean).join('\n')
    const goal: Goal = { id, title: block.title, description: description.slice(0, 2000), category: block.category, ...(block.due ? { due: block.due } : {}), ...(block.steps[0] ? { nextStep: block.steps[0].slice(0, 240) } : {}), status: 'tracking', sessionId: home, createdAt: now, updatedAt: now, summary: block.why.slice(0, 240), activity: [], steps: block.steps, progress: -1, attention: false }
    this.store.goals = [goal, ...this.store.goals]
    this.goalBySession.set(home, id)
    await this.save()
    const schedule = this.ctx.get('schedule') as ScheduleLike | undefined
    if (schedule) {
      // the check carries the goal's own note, so the chat knows the protocol whenever it wakes
      const prompt = `${goalCheckPrompt(block.title, zh, block.firstCheck || undefined)}\n\n${goalHomeNote({ ...block, id }, zh)}`
      const title = (zh ? `目标检查：${block.title}` : `Goal check: ${block.title}`).slice(0, 120)
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
      await schedule
        .create(home as SessionId, { prompt, title, ...(block.checkEveryHours > 0 ? { every_seconds: block.checkEveryHours * 3600 } : { daily: { time: `${block.checkTime}:00`, time_zone: tz } }) })
        .then(() => this.refreshAutomations())
        .catch((error: unknown) => this.warn('goal check', error))
    }
    this.ctx.logger.info('nanomuse rooms: goal "%s" from a %s block in %s', block.title, FENCE_GOAL, home)
    return goal
  }

  /** A `nanomuse-goal-update` block: progress, status and the note, as a line on the timeline. */
  private async applyGoalUpdate(update: GoalUpdateBlock, sessionId: string): Promise<void> {
    const goal = (update.goalId ? this.findGoal(update.goalId) : undefined) ?? this.store.goals.find((g) => g.id === this.goalBySession.get(sessionId))
    if (!goal) return
    if (update.nextStep !== undefined) goal.nextStep = update.nextStep
    else if (update.progress >= 0 && update.progress !== goal.progress) delete goal.nextStep
    if (update.progress >= 0) goal.progress = update.progress
    goal.attention = update.status === 'attention'
    if (!goal.attention && goal.followUpSeen) delete goal.followUpSeen.attention
    if (update.status === 'done') {
      if (goal.status !== 'done') void this.askNudge('goal_done').catch((error: unknown) => this.warn('nudges', error))
      goal.status = 'done'
      goal.progress = 100
    } else if (goal.status === 'done') goal.status = 'tracking'
    if (update.note) {
      goal.summary = update.note.slice(0, 240)
      const last = goal.activity[0]
      if (!(last && last.title === update.note && Date.now() - last.at < 60_000)) {
        goal.activity = [{ at: Date.now(), title: update.note.slice(0, 120), text: '' }, ...goal.activity].slice(0, ACTIVITY_KEEP)
      }
    }
    goal.updatedAt = Date.now()
    this.refreshGoalPost(goal)
    await this.save()
  }

  private async alive(sessionId: string): Promise<boolean> {
    const sc = this.ctx.get('sessionController')
    if (!sc) return false
    const resolved = await sc.resolveAgent(sessionId as SessionId).catch(() => undefined)
    return Boolean(resolved && 'agent' in resolved)
  }

  /** Whether a session is (or was) one of the batches' chats: the sync leaves those out. */
  isBatch(sessionId: string): boolean {
    return this.runs.has(sessionId as SessionId) || this.store.batches.includes(sessionId)
  }

  /**
   * A background batch: a chat of its own, the final answer returned, the chat archived. The
   * prompt is the rooms' own, not the person's words, so it goes out as a notice (`summary`, one
   * short line in the window should the chat ever be opened) and the chat stays out of the chats
   * column while it runs (`RoomsView.batches`).
   */
  private async run(title: string, prompt: string, summary: string): Promise<string> {
    const sc = this.ctx.get('sessionController')
    if (!sc) throw new Error('chats are not available yet')
    if (!(await this.ctx.nanomuseCloud.status()).ready) throw new Error('no model is set up')
    const created = await sc.create(await homeWorkspace(this.ctx, (error) => this.warn('home workspace', error)))
    // remembered before a word is said, so the sync never sees the chat as one of the person's
    this.store.batches = [String(created.sessionId), ...this.store.batches.filter((id) => id !== String(created.sessionId))].slice(0, BATCHES_KEEP)
    await this.save()
    await sc.rename({ sessionId: created.sessionId, title }).catch(() => undefined)
    const resolved = await sc.resolveAgent(created.sessionId)
    if ('error' in resolved) throw new Error(`the chat could not be opened: ${String(resolved.error)}`)
    const agent = resolved.agent
    let text = ''
    try {
      text = await new Promise<string>((resolve, reject) => {
        const timer = setTimeout(() => {
          agent.cancel({ kind: 'hook', reason: 'nanomuse rooms: the batch took too long' })
          fail(new Error('the batch took too long'))
        }, RUN_TIMEOUT_MS)
        const done = (value: string) => {
          clearTimeout(timer)
          this.runs.delete(created.sessionId)
          resolve(value)
        }
        const fail = (error: Error) => {
          clearTimeout(timer)
          this.runs.delete(created.sessionId)
          reject(error)
        }
        this.runs.set(created.sessionId, { final: '', resolve: done, reject: fail })
        this.broadcast()
        agent.followup(createUserMessage({ content: [{ type: 'text', text: prompt }], source: { kind: 'nanomuse', form: 'notice', summary: summary.slice(0, 120) } }))
      })
    } finally {
      // The batch is a means, not a chat: out of the list, kept in the archive.
      await (this.ctx.get('workspaceRegistry') as RegistryLike | undefined)?.archiveSession(created.sessionId, { stopActivity: true }).catch(() => undefined)
      this.broadcast()
    }
    return text
  }

  private onEvent(session: Session, event: SessionEvent): void {
    const run = this.runs.get(session.id)
    const goalId = this.goalBySession.get(session.id)
    const type: string = event.type
    // every chat the person can see keeps an account of itself (the batches are nobody's chats)
    if (!run) {
      try {
        this.trackActivity(session, event)
      } catch (error: unknown) {
        this.warn('activity', error)
      }
    }
    if (type === 'deliverables/presented') {
      const files = ((event as unknown as { data: { files?: { path: string; description?: string }[] } }).data.files ?? [])
      for (const file of files) void this.addToLibrary(file.path, file.description ?? '', session.id, session.header.cwd).catch((error: unknown) => this.warn('library', error))
      return
    }
    // any chat's first turn refreshes the tool catalogue the Connectors page shows (the view is per agent)
    if (type === 'turn/start' && Date.now() - this.catalogAt > 30_000) {
      const sc = this.ctx.get('sessionController')
      if (sc) void sc.resolveAgent(session.id).then((resolved) => { if (!('error' in resolved)) this.snapshotTools(resolved.agent) }).catch(() => undefined)
    }
    // the agent's last words in any of the person's chats are read for app fences when the turn ends
    if (!run) {
      if (type === 'turn/start') {
        this.personTurns.delete(session.id)
      } else if (event.type === 'user/message') {
        if (event.data.source.kind === 'user') this.personTurns.add(session.id)
      } else if (event.type === 'assistant/message') {
        const text = textOf(event.data.message.content)
        if (text) this.fenceWords.set(session.id, text)
      } else if (event.type === 'turn/end') {
        const words = this.fenceWords.get(session.id)
        this.fenceWords.delete(session.id)
        const person = this.personTurns.delete(session.id)
        const completed = event.data.reason.kind === 'completed'
        if (words && completed && words.includes('```nanomuse-')) {
          void this.applyFences(session.id, words).catch((error: unknown) => this.warn('fences', error))
        }
        const first = boundTo(this.firstRun, session.id) && this.firstRun.phase !== 'done'
        // the first conversation reads every reply of its chat (a reply without a block changes nothing)
        if (first && completed) void this.firstTurnEnded(words ?? '').catch((error: unknown) => this.warn('first conversation', error))
        // a task: the person asked, the model answered — never the first conversation's turns, never a schedule's wake or a run
        if (person && completed && !first) void this.nudgeTask().catch((error: unknown) => this.warn('nudges', error))
      }
    }
    if (!run && !goalId) return
    if (goalId && (type === 'turn/start' || type === 'user/message')) {
      this.turnMarks.set(session.id, Date.now())
      return
    }
    switch (event.type) {
      case 'assistant/message': {
        const text = textOf(event.data.message.content)
        if (!text) return
        if (run) run.final = text
        if (goalId) {
          if (!this.turnMarks.has(session.id)) this.turnMarks.set(session.id, Date.now())
          this.lastWords.set(session.id, text)
        }
        return
      }
      case 'turn/end': {
        const reason = event.data.reason
        if (run) {
          if (reason.kind === 'error') run.reject(new Error(String(reason.error.message ?? 'the model failed')))
          else run.resolve(run.final)
        }
        if (goalId) {
          const words = this.lastWords.get(session.id) ?? ''
          const since = this.turnMarks.get(session.id) ?? Date.now()
          this.lastWords.delete(session.id)
          this.turnMarks.delete(session.id)
          if (words && reason.kind !== 'error') void this.logGoalTurn(goalId, words, since).catch((error: unknown) => this.warn('goal activity', error))
        }
        return
      }
      default:
        return
    }
  }

  /** Every turn in a goal's chat is a line on its timeline — unless the agent wrote one itself with `goals_room_update`. */
  private async logGoalTurn(goalId: string, words: string, since: number): Promise<void> {
    const goal = this.store.goals.find((g) => g.id === goalId)
    if (!goal) return
    if (goal.activity.some((entry) => entry.at >= since - 1000)) return
    const plain = words.replace(/[*_`#>]/g, '').replace(/\r/g, '').trim()
    const title = firstLine(plain).slice(0, 120)
    const rest = plain.slice(plain.indexOf('\n') + 1).replace(/\s+/g, ' ').trim()
    if (!title) return
    const last = goal.activity[0]
    if (last && last.title === title && Date.now() - last.at < 60_000) return
    goal.activity = [{ at: Date.now(), title, text: plain.indexOf('\n') > 0 ? rest.slice(0, 600) : '' }, ...goal.activity].slice(0, ACTIVITY_KEEP)
    goal.updatedAt = Date.now()
    await this.save()
  }

  // ---- the batches' timing ------------------------------------------------------------

  /** Whether a model can answer right now (signed in, or another provider set up). */
  private async syncReady(): Promise<boolean> {
    const status = await this.ctx.nanomuseCloud.status().catch(() => undefined)
    const ready = status?.ready === true
    // the relay sends the nudge policy with the account (`/v1/me`): the same copy `/v1/nudges` would give
    if (status?.account?.nudges) this.adoptNudges(status.account.nudges)
    if (ready !== this.ready) {
      this.ready = ready
      this.broadcast()
    }
    return ready
  }

  /** A goal card reflects the current plan. Re-dating it invalidates its original reminder. */
  private refreshGoalPost(goal: Goal, dateChanged = false): void {
    this.store.feed.posts = this.store.feed.posts.flatMap((post) => {
      if (post.goalId !== goal.id) return [post]
      if (dateChanged || goal.feedMuted || goal.status !== 'tracking' || !post.goalReason ||
          (post.goalExpiresAt ?? 0) <= Date.now() || (post.goalReason === 'attention' && !goal.attention)) return []
      return [{ ...post, title: goal.title, body: followUpText(goal, post.goalReason, this.lang) }]
    })
  }

  private async writeGoalFollowUp(now: number): Promise<void> {
    const feed = this.store.feed
    const day = localDateKey(now)
    const previousCount = feed.posts.length
    feed.posts = feed.posts.filter((post) => !post.goalId || (feed.routine.on && (post.goalExpiresAt ?? 0) > now))
    const due = feed.routine.on && (!feed.lastGoalFollowUpDay || feed.lastGoalFollowUpDay < day) && routineDue(feed.routine.time, 0, now)
    const candidate = due ? nextGoalFollowUp(currentFeedGoals(this.goals, this.store.activity, this.ctx.nanomuseCloud.feedOwner, now), day, now) : undefined
    if (candidate) {
      const { goal, stage, reason } = candidate
      goal.followUpSeen ??= {}
      if (stage && goal.due) Object.assign(goal.followUpSeen, { due: goal.due, stage })
      if (goal.attention) goal.followUpSeen.attention = true
      feed.lastGoalFollowUpDay = day
      const tomorrow = new Date(now)
      tomorrow.setHours(24, 0, 0, 0)
      const post: FeedPost = {
        id: newId('post'), at: now, title: goal.title, body: followUpText(goal, reason, this.lang),
        area: 'goals', emoji: '📅', image: '', prompt: '', liked: false, goalId: goal.id,
        goalReason: reason, goalExpiresAt: tomorrow.getTime(),
      }
      feed.posts = [post, ...feed.posts].slice(0, FEED_KEEP)
    }
    if (!candidate && previousCount === feed.posts.length && !this.followUpNeedsSave) return
    // The card and both delivery markers reach disk together before the browser receives them.
    try {
      await this.save(true, true)
      this.followUpNeedsSave = false
    } catch (error) {
      this.followUpNeedsSave = true
      throw error
    }
  }

  private checkInScope(): string {
    const owner = this.ctx.nanomuseCloud.feedOwner
    return owner ? createHash('sha256').update(owner).digest('hex').slice(0, 24) : ''
  }

  private checkInMailbox(): CheckInMailbox | undefined {
    const owner = this.ctx.nanomuseCloud.feedOwner
    return owner ? this.store.mailboxes[owner] : undefined
  }

  private ensureMailbox(owner: string): CheckInMailbox {
    return this.store.mailboxes[owner] ??= { allowNewResource: true, lastDay: '', messages: [] }
  }

  private newResourceOffer(): string {
    const scope = this.checkInScope(), box = this.checkInMailbox()
    // A legacy mailbox without a current resource cannot tell us whether its owner removed one.
    if (!scope || !this.store.feed.routine.on || box && (box.resource || box.enabledSince === 0 || box.allowNewResource !== true)) return ''
    return scope + ':' + this.newResourceRevision
  }

  /** Text is available to the originating chat only. The rooms stream carries unread IDs. */
  checkInMessages(sessionId?: string): ChatCheckIn[] {
    const box = this.checkInMailbox()
    if (!box?.messages.length) return []
    const access = this.ctx.nanomuseCloud.scheduleSessionAccess('nanomuse-feed')
    return box.messages.filter(m => m.id !== this.unpublishedCheckIn && (!sessionId || m.sessionId === sessionId) && access(m.sessionId))
  }

  /** Supply a separate public-only wire message. No private check-in text or context is exported. */
  publicWatchSyncLines(session: string): SessionLine[] {
    const cloud = this.ctx.nanomuseCloud
    const box = this.checkInMailbox(), ledger = box?.publicWatches
    if (!box || !ledger?.share_generation || session !== cloud.syncMainSession() ||
        !cloud.publicWatchSyncAvailable(session)) return []
    const permitted = (msg: ChatCheckIn) => {
      const share = msg.publicShare, current = this.checkInMailbox()?.publicWatches
      return Boolean(!this.watchEdit && msg.id !== this.unpublishedCheckIn && share && box === this.checkInMailbox() &&
        msg.sessionId === session && current?.enabled !== false && current?.share_public_updates &&
        current.share_generation === share.grant && current.watches?.[share.watchId]?.status === 'active' &&
        cloud.publicWatchSyncAvailable(session) && cloud.scheduleSessionAccess('nanomuse-feed')(session))
    }
    return box.messages.flatMap(msg => msg.publicShare && permitted(msg)
      ? [{ id: msg.id, role: 'assistant' as const, text: msg.publicShare.text, at: msg.at, authorized: () => permitted(msg) }] : [])
  }

  private persistChatCheckIn(): Promise<void> {
    // A failed write can be retried without exposing two messages or losing the daily limit.
    return this.publishingCheckIn ??= this.save(true, true).then(() => {
      const msg = this.checkInMailbox()?.messages.find(m => m.id === this.unpublishedCheckIn)
      this.unpublishedCheckIn = undefined
      if (msg?.publicShare) this.ctx.nanomuseCloud.publicWatchReady(msg.sessionId)
      this.broadcast()
    }).finally(() => { this.publishingCheckIn = undefined })
  }

  private async writeChatCheckIn(now: number): Promise<void> {
    if (this.unpublishedCheckIn) return this.persistChatCheckIn()
    const cloud = this.ctx.nanomuseCloud
    const owner = cloud.feedOwner
    const box = this.checkInMailbox()
    const routine = this.store.feed.routine
    const day = localDateKey(now)
    const hour = new Date(now).getHours()
    if (!owner || box?.enabledSince === 0 || !routine.on || hour < 9 || hour >= 20 ||
        (box?.lastDay ?? '') >= day || !routineDue(routine.time, 0, now)) return
    const access = cloud.scheduleSessionAccess('nanomuse-feed')
    const registry = this.ctx.get('workspaceRegistry') as RegistryLike | undefined
    if (!registry) return
    for (const record of this.store.activity) {
      const sid = record.sessionId
      if (record.status !== 'done' || record.requestOwner !== owner || record.commitments?.owner !== owner ||
          record.endedAt > now - 15 * 60_000 || this.isBatch(sid) || !access(sid) ||
          registry.archivedSessionIds.includes(sid)) continue
      const goal = this.store.goals.find(g => g.sessionId === sid)
      if (goal && (goal.status !== 'tracking' || goal.feedMuted)) continue
      const heldAt = record.commitments.checkInHeldAt ?? 0
      const item = record.commitments.items.find(i => i.changedAt > heldAt && i.at >= (box?.enabledSince ?? 0) && canCheckIn(i) && i.due === day &&
        !cloud.hasRemoteReplySince(sid, i.changedAt) && dueSoon(i, now) && !box?.messages.some(m => m.sessionId === sid && m.commitmentAt === i.at))
      if (!item) continue
      const quote = commitmentText(item)
      const text = /^zh/i.test(this.lang)
        ? `你之前写过「${quote}」。这件事排在今天，需要我帮你准备下一步吗？`
        : `Earlier you wrote, “${quote}”

You planned this for today. Would you like help preparing the next step?`
      const msg: ChatCheckIn = { id: newId('checkin'), sessionId: sid, at: now, commitmentAt: item.at, text, unread: true }
      const mailbox = this.ensureMailbox(owner)
      mailbox.lastDay = day
      mailbox.messages.push(msg)
      this.unpublishedCheckIn = msg.id
      return this.persistChatCheckIn()
    }
  }

  resourceConnections(): { id: string; label: string; generation: number }[] {
    return this.ctx.get('nanomuseConnectors')?.resourceConnections() ?? []
  }

  async watchNewConnection(offer: string, connection: string, generation: number): Promise<void> {
    if (!offer || offer !== this.newResourceOffer() || this.resourceChoiceAbort) return
    await this.selectResource(this.checkInScope(), connection, generation, '', true, offer)
  }

  async selectResource(scope: string, connection: string, generation: number, key: string, save: boolean, offer?: string): Promise<ResourceChoice[]> {
    const owner = this.ctx.nanomuseCloud.feedOwner
    if (!owner || scope !== this.checkInScope()) throw new RelayError(409, 'account_changed', 'Reopen Feed settings.')
    const access = this.ctx.nanomuseCloud.scheduleSessionAccess('nanomuse-feed')
    if (save) {
      this.watchPoll?.abort()
      if (!offer) this.newResourceRevision++
      this.resourceAbort?.abort(); this.resourceChoiceAbort?.abort()
    }
    const abort = new AbortController()
    if (save) this.resourceChoiceAbort = abort
    const signal = AbortSignal.any([abort.signal, AbortSignal.timeout(18_000)])
    const current = () => !signal.aborted && scope === this.checkInScope() && (!offer || offer === this.newResourceOffer()) && access('nanomuse-feed')
    try {
      const connectors = this.ctx.get('nanomuseConnectors')
      if (connection && !connectors) throw new RelayError(409, 'no_connector', 'Connector is unavailable.')
      const result = connection ? await connectors!.inspectResource(connection, generation, signal, current, offer ? { single: true } : save ? key : undefined) : { choices: [] }
      if (!current()) throw new RelayError(409, 'account_changed', 'Reopen Feed settings.')
      if (!save) return result.choices
      if (offer && !result.sample) return []
      if (connection && (!result.sample || !result.choices[0])) throw new RelayError(409, 'no_resource', 'Choose a listed text resource.')
      const box = this.ensureMailbox(owner)
      const previous = box.resource
      if (!connection) box.allowNewResource = false
      if (result.sample && result.choices[0]) {
        box.resource = { connection, generation, ...result.choices[0], seen: result.sample.signatures, checkedAt: Date.now() }
      } else delete box.resource
      const next = box.resource
      try {
        await this.save(true, true)
      } catch (error) {
        if (next && box.resource === next) {
          if (previous) box.resource = previous
          else delete box.resource
        }
        throw error
      }
      return []
    } finally {
      if (this.resourceChoiceAbort === abort) this.resourceChoiceAbort = undefined
    }
  }

  private async checkResource(now: number): Promise<void> {
    const cloud = this.ctx.nanomuseCloud, box = this.checkInMailbox(), watch = box?.resource
    if (!watch || !box || this.resourceAbort || this.resourceChoiceAbort || this.unpublishedCheckIn) return
    const connectors = this.ctx.get('nanomuseConnectors')
    const day = localDateKey(now)
    const session = cloud.syncMainSession()
    const access = cloud.scheduleSessionAccess('nanomuse-feed')
    const awake = (at: number) => new Date(at).getHours() >= 9 && new Date(at).getHours() < 20
    const eligible = (at: number) => {
      const last = this.store.activity.find(r => r.sessionId === session)
      const registry = this.ctx.get('workspaceRegistry') as RegistryLike | undefined
      return awake(at) && localDateKey(at) === day && box.lastDay < day && cloud.syncMainSession() === session &&
        Boolean(session && registry && !registry.archivedSessionIds.includes(session)) && access(session) &&
        (!last || last.status !== 'running' && last.status !== 'waiting' && last.updatedAt <= at - 15 * 60_000) &&
        !cloud.hasRemoteReplySince(session, at - 15 * 60_000) && !box.messages.some(m => m.sessionId === session && m.unread)
    }
    if (!connectors || !eligible(now) || now - watch.checkedAt < 15 * 60_000) return
    const abort = new AbortController()
    this.resourceAbort = abort
    const signal = AbortSignal.any([abort.signal, AbortSignal.timeout(75_000)])
    const permitted = () => !signal.aborted && box === this.checkInMailbox() && watch === box.resource &&
      access(session) && this.resourceConnections().some(c => c.id === watch.connection && c.generation === watch.generation)
    const read = async () => (await connectors.inspectResource(watch.connection, watch.generation, signal, permitted, watch.key)).sample
    try {
      if (!permitted()) return
      const sample = await read()
      if (!sample || !permitted() || !eligible(Date.now())) return
      for (const text of sample.references ?? []) {
        this.queueWatchInput(text, false, '', () => box === this.checkInMailbox() && watch === box.resource &&
          this.resourceConnections().some(c => c.id === watch.connection && c.generation === watch.generation))
      }
      const seen = new Set(watch.seen)
      const freshLines = sample.lines.filter((_, i) => !seen.has(sample.signatures[i]!))
      const changed = freshLines.slice(0, 24)
      const goalsFor = () => matchingGoals(changed, this.prepSources(Date.now()).filter(s =>
        s.kind === 'goal' && this.store.activity.some(a => a.sessionId === s.origin && a.requestOwner === cloud.feedOwner)))
      let text: string | undefined
      if (changed.length) {
        const goals = goalsFor()
        const lang = this.lang
        const request = changeRequest(changed, goals, now)
        const answer = await cloud.prepareFeed(request.system, request.input, signal)
        if (!permitted() || !eligible(Date.now()) || lang !== this.lang || goals.map(g => g.id).join() !== goalsFor().map(g => g.id).join()) return
        text = changeMessage(answer, watch.label, changed, goals, /^zh/i.test(lang))
        if (text) {
          // A project update can be withdrawn while the model reads it.
          const fresh = await read()
          if (!fresh || !permitted() || !eligible(Date.now()) || goals.map(g => g.id).join() !== goalsFor().map(g => g.id).join() ||
              !changed.every(line => fresh.lines.includes(line))) return
        }
      }
      const at = Date.now()
      // Store fingerprints for a bounded history, including lines that disappeared and returned.
      const processed = new Set(changed)
      const remembered = sample.signatures.filter((hash, i) => seen.has(hash) || processed.has(sample.lines[i]!))
      watch.seen = [...new Set([...remembered, ...watch.seen])].slice(0, 1800)
      watch.checkedAt = at
      if (text) {
        const msg: ChatCheckIn = { id: newId('context'), sessionId: session, at, text, unread: true, external: true }
        box.lastDay = day
        box.messages.push(msg)
        this.unpublishedCheckIn = msg.id
        await this.persistChatCheckIn()
      } else await this.save(true, true)
    } finally {
      if (this.resourceAbort === abort) this.resourceAbort = undefined
    }
  }

  private resetWatchWork(): void {
    this.watchEpoch = randomBytes(12).toString('hex')
    this.watchPoll?.abort()
    this.watchEdit?.abort()
    this.watchInputs = []
  }

  private watchMainSession(): string {
    const cloud = this.ctx.nanomuseCloud
    return cloud.syncMainSession?.() || (cloud.feedOwner === 'local' ? this.firstRun.sessionId ?? '' : '')
  }

  private queueWatchInput(text: string, personal: boolean, turn: string, current: () => boolean): void {
    const box = this.checkInMailbox()
    if (!this.store.feed.routine.on || box?.enabledSince === 0 || box?.publicWatches?.enabled === false ||
        !current() || !text || !/https?:|github|openalex|orcid|scholar|research|papers?|10\.\d{4,}|长期|引用|研究|论文|订阅|学术/iu.test(text)) return
    // Preserve quoted blocks and whole sentences for the shared offline recogniser.
    if (text.length > 6000) text = text.slice(0, Math.max(0, text.lastIndexOf('\n', 6000)))
    if (!text.trim() || this.watchInputs.some(input => input.text === text && input.personal === personal && input.turn === turn && input.current())) return
    this.watchInputs.push({ text, personal, turn, at: Date.now(), current })
    this.watchInputs = this.watchInputs.slice(-16)
  }

  private async publicWatchSettings(body: Record<string, unknown>) {
    const scope = this.checkInScope()
    const cloud = this.ctx.nanomuseCloud, owner = cloud.feedOwner
    const stale = () => new RelayError(409, 'account_changed', 'Reopen Feed settings.')
    if (!owner || !scope || body.scope !== scope) throw stale()
    const box = this.ensureMailbox(owner)
    const state = box.publicWatches
    const view = watchView(state ?? {}, scope, this.watchEpoch, owner.startsWith('account:'))
    if (Object.keys(body).every(k => k === 'scope')) return view
    if (body.revision !== view.revision || this.watchEdit || (body.share_public_updates === true && !view.can_share)) throw stale()
    const edit: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(body)) {
      if (key === 'scope' || key === 'revision') continue
      if (!['enabled', 'share_public_updates', 'kind', 'target', 'action', 'id'].includes(key)) throw stale()
      edit[key === 'id' ? 'watch_id' : key] = value
    }
    this.watchPoll?.abort()
    const abort = new AbortController()
    this.watchEdit = abort
    const access = cloud.scheduleSessionAccess('nanomuse-feed')
    try {
      const next = await this.watchWorker(state ?? {}, { op: 'edit', edit }, abort.signal)
      if (abort.signal.aborted || box !== this.checkInMailbox() || state !== box.publicWatches || !access('nanomuse-feed')) throw stale()
      box.publicWatches = next
      if (typeof edit.enabled === 'boolean') this.watchInputs = []
      try { await this.save(true, true) } catch (error) {
        if (state) box.publicWatches = state
        else delete box.publicWatches
        throw error
      }
      if (abort.signal.aborted || box !== this.checkInMailbox() || !access('nanomuse-feed')) throw stale()
      return watchView(next, scope, this.watchEpoch, owner.startsWith('account:'))
    } finally { if (this.watchEdit === abort) this.watchEdit = undefined }
  }

  private watchWorker = runWatchWorker

  private async checkPublicWatches(now: number, observeOnly = false): Promise<void> {
    const cloud = this.ctx.nanomuseCloud, owner = cloud.feedOwner
    if (!owner || !this.store.feed.routine.on || this.watchPoll || this.watchEdit || this.unpublishedCheckIn) return
    const box = this.ensureMailbox(owner)
    const state = box.publicWatches
    if (state?.enabled === false || box.enabledSince === 0) return
    const inputs = this.watchInputs.filter(input => input.at >= now - 30 * 86_400_000 && input.at <= now && input.current())
    const due = !observeOnly && Object.values(state?.watches ?? {}).some(row => row.status === 'active' && (row.next ?? 0) * 1000 <= now)
    const existing = pendingChanges(state ?? {}, now)
    if (!inputs.length && !due && (observeOnly || !existing.length)) return
    const abort = new AbortController()
    this.watchPoll = abort
    const signal = AbortSignal.any([abort.signal, AbortSignal.timeout(105_000)])
    const access = cloud.scheduleSessionAccess('nanomuse-feed')
    const current = () => !signal.aborted && box === this.checkInMailbox() && this.store.feed.routine.on &&
      box.publicWatches?.enabled !== false && box.enabledSince !== 0 && access('nanomuse-feed')
    try {
      let next = state
      if (due || inputs.length) {
        next = await this.watchWorker(state ?? {}, { op: observeOnly ? 'observe' : 'poll', texts: inputs.map(({ text, personal, turn, at }) => ({ text, personal, turn, at })) }, signal)
        if (!current() || state !== box.publicWatches || !inputs.every(input => input.current())) return
        box.publicWatches = next
        try { await this.save(true, true) } catch (error) {
          if (box.publicWatches === next) {
            if (state) box.publicWatches = state
            else delete box.publicWatches
          }
          throw error
        }
        this.watchInputs = this.watchInputs.filter(input => !inputs.includes(input))
      }
      if (observeOnly || !next || !current()) return
      const day = localDateKey(now), session = this.watchMainSession()
      const eligible = (at: number) => {
        const hour = new Date(at).getHours()
        const last = this.store.activity.find(r => r.sessionId === session)
        const registry = this.ctx.get('workspaceRegistry') as RegistryLike | undefined
        return current() && box.publicWatches === next && hour >= 9 && hour < 20 && localDateKey(at) === day &&
          box.lastDay < day && session && this.watchMainSession() === session && registry &&
          !registry.archivedSessionIds.includes(session) && access(session) &&
          (!last || last.status !== 'running' && last.status !== 'waiting' && last.updatedAt <= at - 15 * 60_000) &&
          !cloud.hasRemoteReplySince(session, at - 15 * 60_000) && !box.messages.some(m => m.sessionId === session && m.unread)
      }
      if (!eligible(Date.now()) || box.publicReviews?.day === day && box.publicReviews.count >= 2) return
      const pending = pendingChanges(next, Date.now()).filter(item => !privateLine(item.change.text))
      const row = pending[0]?.row
      if (!row) return
      const group = pending.filter(item => item.row === row)
      const lines = group.map(item => item.change.text)
      const goalsFor = () => matchingGoals(lines, this.prepSources(Date.now()).filter(s => s.kind === 'goal' &&
        this.store.activity.some(a => a.sessionId === s.origin && a.requestOwner === owner)))
      const goals = goalsFor(), lang = this.lang
      box.publicReviews = { day, count: box.publicReviews?.day === day ? box.publicReviews.count + 1 : 1 }
      await this.save(true, true)
      if (!eligible(Date.now())) return
      const request = changeRequest(lines, goals, now, row)
      const answer = await cloud.prepareFeed(request.system, request.input, signal)
      if (!eligible(Date.now()) || lang !== this.lang || goals.map(g => g.id).join() !== goalsFor().map(g => g.id).join()) return
      const text = changeMessage(answer, row.label, lines, goals, /^zh/i.test(lang), true)
      const decision = JSON.parse(answer.trim().replace(/^\x60{3}(?:json)?\s*|\s*\x60{3}$/g, ''))
      if (decision.notify !== false && !text) return
      const selected = group[Number(decision.line) - 1]
      const url = selected?.change.url
      // Check consent and an active sync before making anything shareable. Changes
      // reviewed alongside a private goal keep only their existing local representation.
      const shared = text && url && !goals.length && next.share_public_updates && next.share_generation &&
        cloud.publicWatchSyncAvailable(session) && await cloud.publicWatchSyncActive(session)
      if (!eligible(Date.now()) || lang !== this.lang || goals.map(g => g.id).join() !== goalsFor().map(g => g.id).join()) return
      const reviewed = new Set(text && selected ? [selected.key] : group.map(item => item.key))
      for (const watched of Object.values(next.watches ?? {})) {
        for (const key of reviewed) if (watched.pending) delete watched.pending[key]
      }
      if (!text) { await this.save(true, true); return }
      const at = Date.now()
      const msg: ChatCheckIn = { id: newId('context'), sessionId: session, at, text: url ? text + '\n' + url : text, unread: true, external: true }
      if (shared && selected && next.share_generation) {
        // The selected reader supplied both fields. Never serialize account context,
        // the user's topic, the model output or the local message into the sync outbox.
        msg.publicShare = { grant: next.share_generation, watchId: row.id, text: selected.change.text.replace(/[\\*_`<>|[\]]/g, '\\$&') + '\n' + url }
      }
      box.lastDay = day
      box.messages.push(msg)
      this.unpublishedCheckIn = msg.id
      await this.persistChatCheckIn()
    } finally { if (this.watchPoll === abort) this.watchPoll = undefined }
  }

  private async tick(): Promise<void> {
    await this.checkResource(Date.now()).catch(() => this.warn('connected resource', 'check deferred'))
    await this.checkPublicWatches(Date.now()).catch(() => this.warn('public sources', 'check deferred'))
    await this.writeChatCheckIn(Date.now())
    await this.writeGoalFollowUp(Date.now())
    const ready = await this.syncReady()
    if (!ready) return
    const now = Date.now()
    const feed = this.store.feed
    if (!feed.routine.on || this.busy.feed) return
    if (routineDue(feed.routine.time, 0, now) && now - this.prepLastTry >= 15 * 60_000) {
      await this.prepareFeed().catch((error: unknown) => this.warn('preparation', error))
    }
    if (!this.store.feed.routine.on || !this.store.feed.routine.reading || now - feed.lastTry < RETRY_AFTER_MS) return
    // the daily routine (C5): once the Feed was opened, a batch every day at its hour
    if (feed.routine.ensuredAt) {
      if (routineDue(feed.routine.time, feed.generatedAt, now)) await this.refreshFeed().catch((error: unknown) => this.warn('feed', error))
      return
    }
    // before that, the older rhythm: when there is something to write from
    if (this.known() && now - feed.generatedAt > FEED_EVERY_MS) {
      await this.refreshFeed().catch((error: unknown) => this.warn('feed', error))
    }
  }

  /** The Feed was opened: the daily routine is written down once (08:00 unless the person changed it). */
  async ensureFeedRoutine(): Promise<FeedRoutine> {
    if (!this.store.feed.routine.ensuredAt) {
      this.store.feed.routine = { ...this.store.feed.routine, ensuredAt: Date.now() }
      await this.save()
    }
    await this.writeGoalFollowUp(Date.now())
    return this.store.feed.routine
  }

  /** The routine's switch and hour, from the Feed's settings sheet. */
  async setFeedRoutine(patch: { on?: boolean; time?: string; reading?: boolean; chatCheckIns?: boolean; checkInScope?: string }): Promise<FeedRoutine> {
    const routine = { ...this.store.feed.routine, ensuredAt: this.store.feed.routine.ensuredAt || Date.now() }
    if (typeof patch.chatCheckIns === 'boolean') {
      const owner = this.ctx.nanomuseCloud.feedOwner
      if (!owner || patch.checkInScope !== this.checkInScope()) throw new RelayError(409, 'account_changed', 'Reopen Feed settings for the current account.')
      const box = this.ensureMailbox(owner)
      this.newResourceRevision++
      if (!patch.chatCheckIns) { this.watchInputs = []; this.watchPoll?.abort() }
      box.enabledSince = patch.chatCheckIns ? box.enabledSince || Date.now() : 0
    }
    if (typeof patch.on === 'boolean' && routine.on !== patch.on) { routine.on = patch.on; this.newResourceRevision++ }
    if (typeof patch.reading === 'boolean') routine.reading = patch.reading
    if (!routine.on) { this.prepAbort?.abort(); this.watchPoll?.abort(); this.watchInputs = [] }
    if (typeof patch.time === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(patch.time)) routine.time = patch.time
    this.store.feed.routine = routine
    await this.save()
    await this.writeGoalFollowUp(Date.now())
    return routine
  }

  /** Something to write from: instructions, a goal, or a profile the person shaped. */
  private known(): boolean {
    const profile = this.ctx.nanomuseCloud.profile.current()
    return Boolean(this.store.feed.instructions || this.store.goals.length || profile.description || Object.values(this.store.ideas.marks).some((m) => m.started))
  }

  // ---- prompts ---------------------------------------------------------------------------

  private context(): string {
    const profile = this.ctx.nanomuseCloud.profile.current()
    const lines: string[] = []
    lines.push(`- the agent's name, as the person chose it: ${profile.name}`)
    if (profile.description) lines.push(`- the agent's look, as the person drew it: ${profile.description.slice(0, 200)}`)
    for (const goal of this.goals.filter((goal) => !goal.feedMuted).slice(0, 10)) {
      lines.push(`- goal (${goal.status}, ${goal.category}): ${goal.title}${goal.summary ? ` — ${goal.summary}` : ''}`)
    }
    const ideas = this.ideaItems()
    const started = ideas.filter((i) => i.started).slice(0, 8)
    if (started.length) lines.push(`- ideas the person started before: ${started.map((i) => i.title).join('; ')}`)
    const dismissed = ideas.filter((i) => i.dismissed).slice(0, 8)
    if (dismissed.length) lines.push(`- ideas the person dismissed (do not repeat): ${dismissed.map((i) => i.title).join('; ')}`)
    const readingPosts = this.store.feed.posts.filter((p) => !p.preparation)
    const liked = readingPosts.filter((p) => p.liked).slice(0, 8)
    if (liked.length) lines.push(`- feed posts the person liked: ${liked.map((p) => p.title).join('; ')}`)
    const recent = readingPosts.slice(0, 12)
    if (recent.length) lines.push(`- posts already written (do not repeat them): ${recent.map((p) => p.title).join('; ')}`)
    lines.push(`- today: ${today(this.lang)}`)
    return lines.join('\n')
  }

  private feedPrompt(): string {
    const n = 4
    // the phone's default preferences when the person has not written any
    const instructions = this.store.feed.instructions || (this.lang.startsWith('zh')
      ? '给我做一个关于我关心的事的动态。短一点、直接一点，扫一眼就能看完，别搞标题党。'
      : 'Build me a feed about what I care about. Keep it short and direct, easy to skim, no clickbait.')
    return [
      `[Background job from nanoMuse: write the person's feed. Nobody reads this chat; the app parses your final answer.]`,
      `You are the person's own agent, writing their personal feed: ${n} short posts made just for them, in ${languageName(this.lang)}. Think of a thoughtful friend who knows what they care about: news worth their attention on the topics they follow (use web_search for anything time-sensitive, and link the source inline in Markdown), a nudge on a goal, a small plan for the day, a question worth thinking about. Specific to this person; never generic filler. No greetings, no "as your agent". Do not call feed_post here — the JSON below is how this batch is delivered.`,
      ``,
      `What the person asked to read here:`,
      instructions,
      ``,
      `What you know:`,
      this.context(),
      ``,
      'Finish with ONE fenced ```json block and nothing after it: a JSON array of ' + n + ' objects, each {"title": "<max 12 words>", "body": "<60-160 words of Markdown, short paragraphs, links inline, no heading>", "area": "<one of ' + AREAS.join(', ') + '>", "emoji": "<one emoji that fits>", "image": "<a direct https image URL from a page you read, or empty>", "prompt": "<a follow-up the person could send you, or empty>"}.',
    ].join('\n')
  }

  // ---- storage ---------------------------------------------------------------------------

  private get path(): string {
    return join(dshHome(), 'nanomuse', 'rooms.json')
  }

  private async read(): Promise<Store> {
    try {
      const raw = JSON.parse(await readFile(this.path, 'utf8')) as Partial<Store>
      return {
        mailboxes: raw.mailboxes && typeof raw.mailboxes === 'object' ? raw.mailboxes : {},
        lang: typeof raw.lang === 'string' ? raw.lang : '',
        feed: { ...EMPTY.feed, ...(raw.feed ?? {}), posts: Array.isArray(raw.feed?.posts) ? raw.feed!.posts : [], routine: feedRoutine(raw.feed?.routine, Boolean(raw.feed?.instructions?.trim())) },
        ideas: { ...EMPTY.ideas, items: [], marks: raw.ideas?.marks && typeof raw.ideas.marks === 'object' ? raw.ideas.marks : {} },
        goals: Array.isArray(raw.goals) ? (raw.goals as Partial<Goal>[]).map((g) => ({ steps: [], progress: -1, attention: false, ...g }) as Goal) : [],
        library: Array.isArray(raw.library) ? raw.library : [],
        memory: Array.isArray(raw.memory) ? raw.memory : [],
        docs: { ...EMPTY.docs, ...(raw.docs && typeof raw.docs === 'object' ? raw.docs : {}) },
        activity: Array.isArray(raw.activity) ? raw.activity.filter((r) => r && typeof r === 'object' && Array.isArray(r.steps)) : [],
        introducedAt: typeof raw.introducedAt === 'number' ? raw.introducedAt : 0,
        batches: Array.isArray(raw.batches) ? raw.batches.filter((id): id is string => typeof id === 'string').slice(0, BATCHES_KEEP) : [],
      }
    } catch {
      return structuredClone(EMPTY)
    }
  }

  /** Serialised atomic writes; every save reaches the browser. */
  private save(propagateErrors = false, publishAfterWrite = false): Promise<void> {
    const posts = this.store.feed.posts
    if (posts.some(post => post.preparation)) {
      const owner = this.ctx.nanomuseCloud.feedOwner
      const sources = this.prepSources(Date.now(), posts)
      this.store.feed.posts = posts.filter(post => !post.preparation || (post.preparation.owner !== owner && post.preparation.expiresAt > Date.now()) || this.prepVisible(post, sources))
    }
    const snapshot = JSON.stringify(this.store, null, 2) + '\n'
    const writing = this.writing.then(async () => {
      const path = this.path
      await mkdir(join(dshHome(), 'nanomuse'), { recursive: true })
      const tmp = `${path}.${process.pid}.tmp`
      await writeFile(tmp, snapshot, { mode: 0o600 })
      await rename(tmp, path)
    })
    this.writing = writing.catch((error: unknown) => this.warn('save', error))
    if (publishAfterWrite) return writing.then(() => this.broadcast())
    this.broadcast()
    return propagateErrors ? writing : this.writing
  }

  private warn(what: string, error: unknown): void {
    this.ctx.logger.warn('nanomuse rooms: %s failed: %s', what, message(error))
  }

  // ---- the routes ----------------------------------------------------------------------

  private readonly handle = async (req: IncomingMessage, res: ServerResponse): Promise<void> => {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1')
    const route = url.pathname.slice(API_PREFIX.length) || '/'
    if (!sameOrigin(req)) return send(res, 403, { error: { code: 'forbidden', message: 'Same-origin requests only' } })
    try {
      if (req.method === 'GET' && route === '/state') {
        await Promise.all([this.syncReady(), this.refreshAutomations()])
        return send(res, 200, this.view())
      }
      if (req.method === 'GET' && route === '/events') {
        await Promise.all([this.syncReady(), this.refreshAutomations()])
        // a window opened: a day of use, and the policy's daily read, off the request's path
        void this.nudgeDay().catch((error: unknown) => this.warn('nudges day', error))
        void this.refreshNudges().catch(() => undefined)
        return this.stream(req, res)
      }
      if (req.method === 'GET' && route === '/connectors') return send(res, 200, this.connectors())
      if (req.method === 'GET' && route === '/activity') {
        const record = this.activityOf(url.searchParams.get('session') ?? '')
        return record ? send(res, 200, record) : send(res, 404, { error: { code: 'not_found', message: 'No record of that chat' } })
      }
      if (req.method === 'GET' && route === '/docs') return send(res, 200, this.docs())
      if (req.method === 'GET' && route === '/files') return send(res, 200, { home: homeDir(), library: this.libraryFolder(), downloads: await downloadsDir(), state: join(dshHome(), 'nanomuse') })
      if (req.method === 'GET' && route === '/library/file') return this.serveFile(res, url.searchParams.get('id') ?? '', url.searchParams.get('raw') === '1')
      if (req.method !== 'POST') return send(res, 404, { error: { code: 'not_found', message: `No ${req.method ?? ''} ${route}` } })
      // Imports need room for UTF-8 and JSON escaping, including a full batch of memory lines.
      const body = await json(req, route === '/library/import' ? IMPORT_MAX_BYTES * 2 + 4096 : route === '/memory/import' ? 512 * 1024 : undefined)
      switch (route) {
        case '/feed/public-watches':
          return send(res, 200, await this.publicWatchSettings(body))
        case '/feed/resource-connections':
          return send(res, 200, this.resourceConnections())
        case '/feed/resource-choices':
        case '/feed/resource-watch':
          return send(res, 200, await this.selectResource(String(body.scope ?? ''), String(body.connection ?? ''),
            Number(body.generation), String(body.key ?? ''), route.endsWith('-watch')))
        case '/lang': {
          const lang = String(body.lang ?? '').trim().slice(0, 20)
          if (lang && lang !== this.store.lang) {
            this.store.lang = lang
            await this.save()
          }
          return send(res, 204)
        }
        case '/feed/prepare':
          return send(res, 200, { status: await this.prepareFeed(true) })
        case '/feed/refresh':
          void this.refreshFeed().catch((error: unknown) => this.warn('feed', error))
          return send(res, 202, { started: true })
        case '/feed/instructions':
          await this.setFeedInstructions(String(body.text ?? ''))
          return send(res, 204)
        case '/feed/open':
          return send(res, 200, await this.ensureFeedRoutine())
        case '/checkins/read': {
          const msg = typeof body.sessionId === 'string' && body.sessionId ? this.checkInMessages(body.sessionId).find(m => m.id === body.id) : undefined
          if (msg?.unread) { msg.unread = false; await this.save(true, true) }
          return send(res, 204)
        }
        case '/feed/routine':
          return send(res, 200, await this.setFeedRoutine({ ...(typeof body.chatCheckIns === 'boolean' ? { chatCheckIns: body.chatCheckIns, checkInScope: String(body.checkInScope ?? '') } : {}), ...(typeof body.reading === 'boolean' ? { reading: body.reading } : {}), ...(typeof body.on === 'boolean' ? { on: body.on } : {}), ...(typeof body.time === 'string' ? { time: body.time } : {}) }))
        case '/feed/like':
          await this.likePost(String(body.id ?? ''), body.on !== false)
          return send(res, 204)
        case '/feed/delete':
          await this.deletePost(String(body.id ?? ''))
          return send(res, 204)
        case '/feed/discuss':
          return send(res, 200, { sessionId: await this.discuss(String(body.id ?? '')) })
        case '/ideas/refresh':
          // the list is the phone's curated one now; older windows may still ask
          return send(res, 204)
        case '/ideas/start':
          return send(res, 200, await this.startIdea(String(body.id ?? '')))
        case '/ideas/mark':
          await this.markIdea(String(body.id ?? ''), String(body.sessionId ?? ''))
          return send(res, 204)
        case '/ideas/dismiss':
          await this.dismissIdea(String(body.id ?? ''))
          return send(res, 204)
        case '/goals/create':
          return send(res, 200, await this.createGoal({ title: typeof body.title === 'string' ? body.title : undefined, category: typeof body.category === 'string' ? body.category : undefined, text: String(body.text ?? ''), due: typeof body.due === 'string' ? body.due : undefined }))
        case '/goals/begin':
          return send(res, 200, await this.beginGoal(goalCategory(body.category), typeof body.seed === 'string' ? body.seed : undefined, typeof body.sessionId === 'string' ? body.sessionId : undefined))
        case '/goals/update':
          return send(res, 200, await this.updateGoal(String(body.id ?? ''), body as Parameters<NanomuseRooms['updateGoal']>[1]))
        case '/docs/write': {
          const doc = String(body.doc ?? '')
          if (doc !== 'identity' && doc !== 'soul' && doc !== 'memory') return send(res, 400, { error: { code: 'bad_request', message: 'doc is identity, soul or memory' } })
          await this.writeDoc(doc, String(body.text ?? ''))
          return send(res, 200, this.docs()[doc])
        }
        case '/firstrun/set':
          return send(res, 200, await this.setFirstRun({
            ...(body.sourceChosen === 'cloud' || body.sourceChosen === 'own' || body.sourceChosen === null ? { sourceChosen: body.sourceChosen } : {}),
            ...(typeof body.permissionsSeen === 'boolean' ? { permissionsSeen: body.permissionsSeen } : {}),
          }))
        case '/firstrun/start':
          return send(res, 200, await this.startFirstConversation())
        case '/firstrun/finish':
          await this.finishFirstRun()
          return send(res, 204)
        case '/firstrun/pick': {
          const name = String(body.name ?? '').trim().slice(0, 16)
          if (!name) return send(res, 400, { error: { code: 'bad_request', message: 'name is required' } })
          await this.pickFirstName(name)
          return send(res, 204)
        }
        case '/firstrun/dismiss':
          await this.dismissFirstChooser()
          return send(res, 204)
        case '/nudges/ask': {
          const moment = String(body.moment ?? '')
          if (moment !== 'signed_in' && moment !== 'new_look' && moment !== 'exhausted' && moment !== 'goal_done') return send(res, 400, { error: { code: 'bad_request', message: 'that moment is counted by the host' } })
          return send(res, 200, { ask: await this.askNudge(moment) })
        }
        case '/nudges/starred':
          await this.starred()
          return send(res, 204)
        case '/nudges/dismiss':
          await this.dismissNudge()
          return send(res, 204)
        case '/nudges/refresh':
          await this.refreshNudges(true)
          return send(res, 200, this.nudgesView())
        case '/library/begin':
          return send(res, 200, { sessionId: await this.openCreationChat(String(body.kind ?? 'document')) })
        case '/goals/delete':
          await this.deleteGoal(String(body.id ?? ''))
          return send(res, 204)
        case '/goals/check-in':
          return send(res, 200, { sessionId: await this.checkIn(String(body.id ?? '')) })
        case '/goals/automation/delete':
          await this.deleteAutomation(String(body.id ?? ''), String(body.schedule_id ?? ''))
          return send(res, 204)
        case '/library/create':
          return send(res, 200, { sessionId: await this.createArtifact(String(body.kind ?? 'document'), String(body.text ?? '')) })
        case '/library/new':
          return send(res, 200, { item: await this.newDocument(String(body.name ?? '')) })
        case '/library/import':
          return send(res, 200, { item: await this.importDocument(String(body.name ?? ''), String(body.text ?? '')) })
        case '/library/delete':
          await this.removeFromLibrary(String(body.id ?? ''))
          return send(res, 204)
        case '/library/write': {
          const item = this.store.library.find((i) => i.id === String(body.id ?? ''))
          if (!item || !TEXT_KINDS.has(extname(item.path).toLowerCase())) return send(res, 404, { error: { code: 'not_found', message: 'No such text file' } })
          await writeFile(item.path, String(body.text ?? ''), 'utf8')
          item.at = Date.now()
          await this.save()
          return send(res, 204)
        }
        case '/files/reveal': {
          const sc = this.ctx.get('sessionController')
          if (!sc) return send(res, 503, { error: { code: 'no_sessions', message: 'Not available yet' } })
          const which = String(body.which ?? '')
          const folder = which === 'home' ? homeDir() : which === 'downloads' ? await downloadsDir() : which === 'state' ? join(dshHome(), 'nanomuse') : which === 'runtime' ? join(homeDir(), '.nanomuse') : this.libraryFolder()
          await mkdir(folder, { recursive: true })
          await sc.openWorkspacePath({ path: folder, action: 'reveal' }, new AbortController().signal)
          return send(res, 204)
        }
        case '/library/folder': {
          const sc = this.ctx.get('sessionController')
          if (!sc) return send(res, 503, { error: { code: 'no_sessions', message: 'Not available yet' } })
          const folder = this.libraryFolder()
          await mkdir(folder, { recursive: true })
          await sc.openWorkspacePath({ path: folder, action: 'reveal' }, new AbortController().signal)
          return send(res, 204)
        }
        case '/memory/add':
          return send(res, 200, { item: await this.remember(String(body.text ?? ''), 'person') })
        case '/avatar/adopted': {
          // A look changed from the chat (the phone's AvatarFlow, here src/client/AvatarChat.tsx): the same
          // memory line the phone leaves, and — when the chat is idle — the agent says so in its own words.
          const desc = String(body.desc ?? '').replace(/\s+/g, ' ').trim().slice(0, 200)
          if (!desc) return send(res, 400, { error: { code: 'bad_request', message: 'desc is required' } })
          await this.remember(avatarMemoryLine(desc))
          const sessionId = String(body.sessionId ?? '')
          const fence = avatarFence({ desc, chosen: Math.min(4, Math.max(1, Number(body.chosen ?? 1) || 1)), files: Array.isArray(body.files) ? body.files.map(String).slice(0, 5) : [] })
          if (sessionId) {
            const line = this.lang.startsWith('zh')
              ? `我的新形象刚刚换好了：${desc}。用一句话、以你自己的口吻告诉用户换好了（不要解释过程），然后另起一行原样写出这个代码块，不要改动它：\n${fence}`
              : `My new look was just adopted: ${desc}. Tell the person in one sentence, in your own voice, that the new look is on (no explanation of how), then write this code block on its own line exactly as it is:\n${fence}`
            await this.say(sessionId as SessionId, line, undefined, this.lang.startsWith('zh') ? '形象已更换' : 'Look changed').catch((error: unknown) => this.warn('avatar notice', error))
          }
          return send(res, 204)
        }
        case '/memory/delete':
          await this.forget(String(body.id ?? ''))
          return send(res, 204)
        case '/memory/import':
          return send(res, 200, { added: await this.importMemory(String(body.text ?? '')) })
        case '/data/export':
          return send(res, 200, { path: await this.exportData() })
        case '/data/reset':
          await this.resetData()
          return send(res, 204)
        case '/library/open': {
          const item = this.store.library.find((i) => i.id === String(body.id ?? ''))
          const sc = this.ctx.get('sessionController')
          if (!item || !sc) return send(res, 404, { error: { code: 'not_found', message: 'No such file' } })
          await sc.openWorkspacePath(body.reveal === true ? { path: item.path, action: 'reveal' } : { path: item.path }, new AbortController().signal)
          return send(res, 204)
        }
        default:
          return send(res, 404, { error: { code: 'not_found', message: `No ${req.method ?? ''} ${route}` } })
      }
    } catch (error: unknown) {
      if (error instanceof RelayError) return send(res, error.status >= 500 ? 502 : error.status, { error: { code: error.code, message: error.message } })
      this.warn(`${req.method ?? ''} ${route}`, error)
      return send(res, 500, { error: { code: 'internal', message: message(error) } })
    }
  }

  private stream(req: IncomingMessage, res: ServerResponse): void {
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store', connection: 'keep-alive', 'x-accel-buffering': 'no' })
    res.write(`retry: 2000\ndata: ${JSON.stringify(this.view())}\n\n`)
    this.streams.add(res)
    const beat = setInterval(() => {
      try {
        res.write(': beat\n\n')
      } catch {
        // closed below
      }
    }, 20_000)
    const done = () => {
      clearInterval(beat)
      this.streams.delete(res)
    }
    req.on('close', done)
    res.on('close', done)
  }

  /** The file behind a Library item: its text for the editor, or the bytes for a preview. */
  private async serveFile(res: ServerResponse, id: string, raw: boolean): Promise<void> {
    const item = this.store.library.find((i) => i.id === id)
    if (!item) return send(res, 404, { error: { code: 'not_found', message: 'No such file' } })
    const ext = extname(item.path).toLowerCase()
    let info: Awaited<ReturnType<typeof stat>>
    try {
      info = await stat(item.path)
    } catch {
      return send(res, 410, { error: { code: 'gone', message: 'The file is no longer there' } })
    }
    if (!raw) {
      if (!TEXT_KINDS.has(ext)) return send(res, 415, { error: { code: 'binary', message: 'Not a text file' } })
      if (info.size > 2 * 1024 * 1024) return send(res, 413, { error: { code: 'too_large', message: 'The file is too large to edit here' } })
      return send(res, 200, { text: await readFile(item.path, 'utf8'), bytes: info.size, mtime: Math.round(info.mtimeMs) })
    }
    res.writeHead(200, { 'content-type': MIME[ext] ?? 'application/octet-stream', 'content-length': info.size, 'cache-control': 'private, max-age=60' })
    createReadStream(item.path).pipe(res)
  }
}

// ---- small helpers ---------------------------------------------------------------------------

/** A routine as the file has it, or the default (on, 08:00, not yet ensured). */
function feedRoutine(raw: unknown, hadInstructions = false): FeedRoutine {
  const d = EMPTY.feed.routine
  if (!raw || typeof raw !== 'object') return { ...d }
  const r = raw as Record<string, unknown>
  return {
    on: typeof r.on === 'boolean' ? r.on : d.on,
    // A pre-upgrade scheduled reading with written instructions keeps its original schedule.
    reading: typeof r.reading === 'boolean' ? r.reading : Boolean(r.ensuredAt && hadInstructions),
    time: typeof r.time === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(r.time) ? r.time : d.time,
    ensuredAt: typeof r.ensuredAt === 'number' ? r.ensuredAt : 0,
  }
}

/**
 * The daily routine is due when today's hour has passed and the last batch was written
 * before it — so a missed morning (the computer was asleep) is caught up the moment the
 * app is back, and never twice in a day.
 */
export function routineDue(time: string, generatedAt: number, now = Date.now()): boolean {
  const [hh, mm] = time.split(':').map((n) => Number(n))
  const today = new Date(now)
  today.setHours(hh ?? 8, mm ?? 0, 0, 0)
  const slot = today.getTime()
  return now >= slot && generatedAt < slot
}

function newId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}${randomBytes(3).toString('hex')}`
}

function str(value: unknown): string {
  return typeof value === 'string' ? value.trim() : typeof value === 'number' ? String(value) : ''
}

function strList(value: unknown, max: number, each: number): string[] {
  if (!Array.isArray(value)) return []
  return value.map((v) => str(v).slice(0, each)).filter(Boolean).slice(0, max)
}

function area(value: string | undefined): string {
  return (AREAS as readonly string[]).includes(value ?? '') ? (value as string) : 'planning'
}

function oneEmoji(value: string | undefined): string {
  if (!value) return ''
  const first = [...value.trim()][0] ?? ''
  return /\p{Extended_Pictographic}/u.test(first) ? first : ''
}

function httpsUrl(value: string | undefined): string {
  if (!value) return ''
  try {
    const url = new URL(value.trim())
    return url.protocol === 'https:' ? url.href.slice(0, 1000) : ''
  } catch {
    return ''
  }
}

function firstLine(text: string): string {
  return text.split('\n').map((l) => l.trim()).find(Boolean) ?? ''
}

function today(lang: string): string {
  try {
    return new Date().toLocaleDateString(lang, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })
  } catch {
    return new Date().toDateString()
  }
}

export function languageName(lang: string): string {
  const base = lang.toLowerCase()
  if (base.startsWith('zh')) return base.includes('tw') || base.includes('hk') || base.includes('hant') ? 'Traditional Chinese' : 'Simplified Chinese'
  if (base.startsWith('ja')) return 'Japanese'
  if (base.startsWith('ko')) return 'Korean'
  if (base.startsWith('de')) return 'German'
  if (base.startsWith('fr')) return 'French'
  if (base.startsWith('es')) return 'Spanish'
  return 'English'
}

function categoryLabel(category: Category, zh: boolean): string {
  const labels: Record<Category, [string, string]> = {
    health: ['Health', '健康'],
    relationships: ['Relationships', '人际关系'],
    finance: ['Finance', '金融'],
    career: ['Career', '职业'],
    hobbies: ['Hobbies', '兴趣'],
    productivity: ['Productivity', '效率提升'],
    other: ['Other', '其他'],
  }
  return labels[category][zh ? 1 : 0]
}

export function ruleOf(r: ScheduleRecordLike): string {
  const hhmm = (t: string | undefined) => (t ?? '').slice(0, 5)
  switch (r.kind) {
    case 'daily':
      return `daily@${hhmm(r.time)}`
    case 'weekly':
      return `weekly ${(r.weekdays ?? []).join(',')}@${hhmm(r.time)}`
    case 'cron':
      return `cron ${r.expression ?? ''}`
    case 'every':
      return `every ${r.everySeconds ?? 0}s`
    default:
      return r.scheduledAt
  }
}

/** `~/Downloads`, or what the desktop calls it (`~/下载` on a Chinese Linux: user-dirs.dirs). */
async function downloadsDir(): Promise<string> {
  const home = homeDir()
  if (process.platform === 'linux') {
    try {
      const dirs = await readFile(join(process.env.XDG_CONFIG_HOME || join(home, '.config'), 'user-dirs.dirs'), 'utf8')
      const match = /^XDG_DOWNLOAD_DIR="?([^"\n]+)"?/m.exec(dirs)
      if (match?.[1]) return match[1].replace('$HOME', home)
    } catch {
      /* the default below */
    }
  }
  return join(home, 'Downloads')
}

/** A first title for a goal typed in one breath: the first clause, before the agent names it. */
export function goalTitle(text: string): string {
  const line = firstLine(text).trim()
  const cut = line.search(/[；;。！？!?\n]|，|, |: |：/)
  const clause = (cut > 3 ? line.slice(0, cut) : line).trim()
  return (clause || line).slice(0, 40)
}

/** Titles compared loosely, so a post the agent sent twice lands once. */
function titleKey(title: string): string {
  return title.toLowerCase().replace(/[\s\p{P}]+/gu, '')
}

/**
 * One memory line's comparison key: lower case with whitespace folded, punctuation kept.
 * Punctuation can carry meaning, such as a minus sign or a decimal point, so a correction
 * and the value it corrects are two lines; every path that writes memory compares this way.
 */
function memoryKey(line: string): string {
  return line.replace(/\s+/g, ' ').trim().toLowerCase()
}

// ---- the agent's documents -------------------------------------------------------------------

/** The day a memory line is stamped with is the day the person reads, at their wall clock. */
function isoDay(at = Date.now()): string {
  const d = new Date(at)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** IDENTITY.md as it reads before the person touches it: the name, the look, the voice. */
export function identityTemplate(name: string, look: string, zh: boolean): string {
  return zh
    ? [
        '# IDENTITY.md',
        '',
        `<!-- 这是 ${name} 的身份卡。改这里的字，${name} 的下一句话就会照着来。 -->`,
        '',
        `- **名字**：${name}`,
        `- **模样**：${look || '一条小龙（还没画过新形象）'}`,
        '- **说话**：简短、直接，用对方的语言；说做了什么，不说要做什么。',
        '- **住在**：这台电脑和登录同一账户的其他设备上。',
        '',
        '## 可以改的',
        '',
        '- 称呼、口吻、常用的表情和语气词。',
        '- 遇到拿不准的事先问还是先做。',
        '',
      ].join('\n')
    : [
        '# IDENTITY.md',
        '',
        `<!-- ${name}'s identity card. Change the words here and ${name}'s next line follows them. -->`,
        '',
        `- **Name**: ${name}`,
        `- **Look**: ${look || 'a small dragon (no new look drawn yet)'}`,
        '- **Voice**: short and plain, in your language; says what was done, not what will be.',
        '- **Lives on**: this computer and the other devices signed in to the same account.',
        '',
        '## Things you may change',
        '',
        '- How it addresses you, its tone, the emoji it reaches for.',
        '- Whether it asks first or acts first when unsure.',
        '',
      ].join('\n')
}

/** SOUL.md before the person writes it: what the agent holds to. */
export function soulTemplate(name: string, zh: boolean): string {
  return zh
    ? [
        '# SOUL.md',
        '',
        `<!-- ${name} 的性格和原则。这里写的会进入每一次对话。 -->`,
        '',
        '## 我是谁',
        '',
        `我是 ${name}，住在你自己的设备上的个人智能体。你的数据留在你的机器上，我只在你让我做事的时候动手。`,
        '',
        '## 我在意什么',
        '',
        '- 把事做成，而不是把话说漂亮。',
        '- 不确定就说不确定；没做成就说没做成。',
        '- 涉及钱、密码、删除、发送的事，先问你。',
        '',
        '## 我不做什么',
        '',
        '- 不替你做决定，不替你发出去任何东西。',
        '- 不把你的信息告诉别人。',
        '',
      ].join('\n')
    : [
        '# SOUL.md',
        '',
        `<!-- ${name}'s character and principles. What is written here goes into every chat. -->`,
        '',
        '## Who I am',
        '',
        `I am ${name}, a personal agent that lives on your own devices. Your data stays on your machines; I act only when you ask.`,
        '',
        '## What I care about',
        '',
        '- Getting things done rather than saying them well.',
        '- Saying so when I am unsure, and when something did not work.',
        '- Asking first when money, passwords, deleting or sending are involved.',
        '',
        '## What I do not do',
        '',
        '- Decide for you, or send anything out in your name.',
        '- Tell anyone else what I know about you.',
        '',
      ].join('\n')
}

/** MEMORY.md, rendered from the memory lines (one bullet each, dated); edits come back through applyMemoryDoc. */
export function memoryDoc(memory: readonly MemoryItem[], zh: boolean): string {
  const head = zh
    ? ['# MEMORY.md', '', '<!-- 我记住的关于你的事：一行一条。删掉一行就是忘掉；加一行就是记住。 -->', '']
    : ['# MEMORY.md', '', '<!-- What I remember about you, one line each. Delete a line to make me forget it; add one to make me remember. -->', '']
  if (!memory.length) return [...head, zh ? '_还没有记住什么。_' : '_Nothing remembered yet._', ''].join('\n')
  const groups: Record<string, MemoryItem[]> = {}
  for (const item of memory) (groups[item.source] ??= []).push(item)
  const names: Record<string, [string, string]> = { agent: ['From our chats', '聊天里记下的'], person: ['Written by you', '你写下的'], import: ['Imported', '导入的'] }
  const lines = [...head]
  for (const source of ['agent', 'person', 'import']) {
    const items = groups[source]
    if (!items?.length) continue
    lines.push(`## ${names[source]![zh ? 1 : 0]}`, '')
    for (const item of items) lines.push(`- (${isoDay(item.at)}) ${item.text}`)
    lines.push('')
  }
  return lines.join('\n')
}

/** A document without its title line and HTML comments, for the prompt. */
function stripDoc(text: string): string {
  return text.replace(/<!--[\s\S]*?-->/g, '').replace(/^#\s+\S+\.md\s*$/m, '').trim()
}

// ---- tool calls, in a line ---------------------------------------------------------------------

function prettyArgs(raw: string): string {
  const args = parseArgs(raw)
  if (!Object.keys(args).length) return raw.slice(0, STEP_TEXT)
  try {
    return JSON.stringify(args, null, 2).slice(0, STEP_TEXT)
  } catch {
    return raw.slice(0, STEP_TEXT)
  }
}

/** The JSON array in the agent's final answer: the last fenced block, else the outermost brackets. */
export function parseArray(text: string): Record<string, unknown>[] {
  const fenced = [...text.matchAll(/```(?:json)?\s*([\s\S]*?)```/g)].map((m) => m[1] ?? '')
  const candidates = fenced.length ? fenced.reverse() : []
  const start = text.indexOf('[')
  const end = text.lastIndexOf(']')
  if (start >= 0 && end > start) candidates.push(text.slice(start, end + 1))
  for (const candidate of candidates) {
    try {
      const parsed: unknown = JSON.parse(candidate.trim())
      const rows = Array.isArray(parsed) ? parsed : parsed && typeof parsed === 'object' ? Object.values(parsed as Record<string, unknown>).find(Array.isArray) : undefined
      if (Array.isArray(rows)) return rows.filter((r): r is Record<string, unknown> => Boolean(r) && typeof r === 'object')
    } catch {
      // the next candidate
    }
  }
  return []
}

// ---- a small zip writer (deflate, one pass; enough for an export) ------------------

interface ZipEntry {
  name: string
  data: Buffer
  at: Date
}

const CRC_TABLE = new Uint32Array(256).map((_, n) => {
  let c = n
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
  return c >>> 0
})

export function crc32(data: Uint8Array): number {
  let crc = 0xffffffff
  for (const byte of data) crc = CRC_TABLE[(crc ^ byte) & 0xff]! ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

function dosTime(at: Date): { time: number; date: number } {
  const year = Math.max(1980, at.getFullYear())
  return {
    time: (at.getHours() << 11) | (at.getMinutes() << 5) | (at.getSeconds() >> 1),
    date: ((year - 1980) << 9) | ((at.getMonth() + 1) << 5) | at.getDate(),
  }
}

/** The entries as one zip file (names UTF-8, deflated, no zip64 — exports are small). */
export function zip(entries: ZipEntry[]): Buffer {
  const parts: Buffer[] = []
  const central: Buffer[] = []
  let offset = 0
  for (const entry of entries) {
    const name = Buffer.from(entry.name, 'utf8')
    const packed = deflateRawSync(entry.data)
    const stored = packed.length < entry.data.length
    const body = stored ? packed : entry.data
    const method = stored ? 8 : 0
    const crc = crc32(entry.data)
    const { time, date } = dosTime(entry.at)
    const local = Buffer.alloc(30)
    local.writeUInt32LE(0x04034b50, 0)
    local.writeUInt16LE(20, 4)
    local.writeUInt16LE(0x0800, 6) // UTF-8 names
    local.writeUInt16LE(method, 8)
    local.writeUInt16LE(time, 10)
    local.writeUInt16LE(date, 12)
    local.writeUInt32LE(crc, 14)
    local.writeUInt32LE(body.length, 18)
    local.writeUInt32LE(entry.data.length, 22)
    local.writeUInt16LE(name.length, 26)
    local.writeUInt16LE(0, 28)
    parts.push(local, name, body)
    const dir = Buffer.alloc(46)
    dir.writeUInt32LE(0x02014b50, 0)
    dir.writeUInt16LE(20, 4)
    dir.writeUInt16LE(20, 6)
    dir.writeUInt16LE(0x0800, 8)
    dir.writeUInt16LE(method, 10)
    dir.writeUInt16LE(time, 12)
    dir.writeUInt16LE(date, 14)
    dir.writeUInt32LE(crc, 16)
    dir.writeUInt32LE(body.length, 20)
    dir.writeUInt32LE(entry.data.length, 24)
    dir.writeUInt16LE(name.length, 28)
    dir.writeUInt16LE(0, 30)
    dir.writeUInt16LE(0, 32)
    dir.writeUInt16LE(0, 34)
    dir.writeUInt16LE(0, 36)
    dir.writeUInt32LE(0, 38)
    dir.writeUInt32LE(offset, 42)
    central.push(dir, name)
    offset += local.length + name.length + body.length
  }
  const dirBytes = central.reduce((n, b) => n + b.length, 0)
  const end = Buffer.alloc(22)
  end.writeUInt32LE(0x06054b50, 0)
  end.writeUInt16LE(0, 4)
  end.writeUInt16LE(0, 6)
  end.writeUInt16LE(entries.length, 8)
  end.writeUInt16LE(entries.length, 10)
  end.writeUInt32LE(dirBytes, 12)
  end.writeUInt32LE(offset, 16)
  end.writeUInt16LE(0, 20)
  return Buffer.concat([...parts, ...central, end])
}

/**
 * Write an export one entry at a time. At most one bounded source file and its
 * compressed form are resident, rather than the complete export twice.
 */
export async function writeZipFile(path: string, entries: ExportSource[]): Promise<void> {
  await rm(path, { force: true }).catch(() => undefined)
  const file = await openFile(path, 'wx', 0o600)
  const central: Buffer[] = []
  let offset = 0
  let written = 0
  try {
    for (const entry of entries) {
      let data: Buffer
      if (entry.data) {
        data = entry.data
      } else if (entry.path) {
        // the file as it is now; one replaced by a link or grown since the scan is left out
        const info = await lstat(entry.path).catch(() => null)
        if (!info || info.isSymbolicLink() || !info.isFile() || info.size > EXPORT_MAX_FILE_BYTES) continue
        data = await readFile(entry.path)
      } else {
        throw new Error(`export entry has no source: ${entry.name}`)
      }
      const name = Buffer.from(entry.name, 'utf8')
      const packed = deflateRawSync(data)
      const stored = packed.length < data.length
      const body = stored ? packed : data
      const method = stored ? 8 : 0
      const crc = crc32(data)
      const { time, date } = dosTime(entry.at)
      const local = Buffer.alloc(30)
      local.writeUInt32LE(0x04034b50, 0)
      local.writeUInt16LE(20, 4)
      local.writeUInt16LE(0x0800, 6)
      local.writeUInt16LE(method, 8)
      local.writeUInt16LE(time, 10)
      local.writeUInt16LE(date, 12)
      local.writeUInt32LE(crc, 14)
      local.writeUInt32LE(body.length, 18)
      local.writeUInt32LE(data.length, 22)
      local.writeUInt16LE(name.length, 26)
      const dir = Buffer.alloc(46)
      dir.writeUInt32LE(0x02014b50, 0)
      dir.writeUInt16LE(20, 4)
      dir.writeUInt16LE(20, 6)
      dir.writeUInt16LE(0x0800, 8)
      dir.writeUInt16LE(method, 10)
      dir.writeUInt16LE(time, 12)
      dir.writeUInt16LE(date, 14)
      dir.writeUInt32LE(crc, 16)
      dir.writeUInt32LE(body.length, 20)
      dir.writeUInt32LE(data.length, 24)
      dir.writeUInt16LE(name.length, 28)
      dir.writeUInt32LE(offset, 42)
      await file.write(local)
      await file.write(name)
      await file.write(body)
      central.push(dir, name)
      offset += local.length + name.length + body.length
      written += 1
    }
    const directory = Buffer.concat(central)
    const end = Buffer.alloc(22)
    end.writeUInt32LE(0x06054b50, 0)
    end.writeUInt16LE(written, 8)
    end.writeUInt16LE(written, 10)
    end.writeUInt32LE(directory.length, 12)
    end.writeUInt32LE(offset, 16)
    await file.write(directory)
    await file.write(end)
    await file.sync()
  } catch (error) {
    await file.close()
    await rm(path, { force: true }).catch(() => undefined)
    throw error
  }
  await file.close()
}
