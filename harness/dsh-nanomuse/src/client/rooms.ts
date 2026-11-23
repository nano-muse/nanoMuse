/**
 * The rooms' state in the browser — Feed, Ideas, Goals, Library — one
 * `EventSource` on `/nanomuse/rooms/events` mirrored into a snapshot React
 * reads with `useSyncExternalStore` (the same shape `live.ts` gives the
 * account), and the calls the rooms make. Types mirror `src/rooms.ts`.
 */
import type { Preparation } from '../feed-preparation.ts'
import { useSyncExternalStore } from 'react'

export interface FeedPost {
  id: string
  at: number
  title: string
  body: string
  area: string
  emoji: string
  image: string
  prompt: string
  liked: boolean
  preparation?: Preparation
  goalId?: string
  goalExpiresAt?: number
  sessionId?: string
}

export type IdeaKind = 'chat' | 'routine' | 'goal'

export interface Idea {
  id: string
  at: number
  group: string
  emoji: string
  title: string
  detail: string
  includes: string[]
  how: string
  prompt: string
  area: string
  /** What trying it does: words in the chat, a daily routine, or a goal conversation. */
  kind?: IdeaKind
  time?: string
  category?: string
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
  rule: string
  next: string
}

export type Category = 'health' | 'relationships' | 'finance' | 'career' | 'hobbies' | 'productivity' | 'other'
export type GoalStatus = 'tracking' | 'done' | 'paused'

export interface Goal {
  id: string
  title: string
  description: string
  category: Category
  status: GoalStatus
  sessionId: string
  createdAt: number
  updatedAt: number
  summary: string
  activity: GoalActivity[]
  steps?: string[]
  /** 0–100 as the agent last reported, -1 or absent when it never said. */
  progress?: number
  attention?: boolean
  due?: string
  nextStep?: string
  feedMuted?: boolean
}

export type LibraryKind = 'document' | 'web' | 'image' | 'video' | 'audio' | 'file'

export interface LibraryItem {
  id: string
  path: string
  name: string
  kind: LibraryKind
  description: string
  sessionId: string
  at: number
}

export interface MemoryItem {
  id: string
  at: number
  text: string
  source: 'agent' | 'person' | 'import'
}

/** One step of a task, as `src/rooms.ts` records it. */
export interface ActivityStep {
  at: number
  kind: 'start' | 'tool' | 'answer' | 'end'
  name: string
  title: string
  detail: string
  result: string
  callId: string
  ok?: boolean
}

/** What one chat did; the stream carries the records without the steps' texts. */
export interface ActivityRecord {
  sessionId: string
  startedAt: number
  updatedAt: number
  endedAt: number
  status: 'running' | 'done' | 'error' | 'stopped' | 'waiting'
  request: string
  words: string
  current: { name: string; title: string; at: number; own?: boolean } | null
  steps: ActivityStep[]
  turns: number
}

export type DocName = 'identity' | 'soul' | 'memory'
export interface DocText {
  text: string
  updatedAt: number
  template: boolean
}

/** The feed's daily routine (C5), as the host keeps it. */
export interface FeedRoutine {
  reading?: boolean
  on: boolean
  time: string
  ensuredAt: number
}

/** The first run (C4), as `src/firstrun.ts` shapes it, plus the chooser's names. */
export interface FirstRun {
  version: 1
  done: boolean
  permissionsSeen: boolean
  sourceChosen: 'cloud' | 'own' | null
  phase: 'none' | 'ask_user_name' | 'ask_agent_name' | 'named' | 'done'
  sessionId: string | null
  userAddress: string | null
  suggestions: string[]
  chosen: string | null
  startedAt: number
  finishedAt: number
  chips: string[]
}

export const FIRST_RUN_INITIAL: FirstRun = { version: 1, done: false, permissionsSeen: false, sourceChosen: null, phase: 'none', sessionId: null, userAddress: null, suggestions: [], chosen: null, startedAt: 0, finishedAt: 0, chips: [] }

/** The star nudges (C1), as `src/nudges.ts` shapes them. */
export type NudgeMoment = 'signed_in' | 'tasks' | 'new_look' | 'exhausted' | 'days_used' | 'goal_done'
export interface NudgeAsk {
  moment: NudgeMoment
  n?: number
  key: string
  at: number
}
export interface Nudges {
  policy: { version: number; star: { enabled: boolean; url: string; moments: { signed_in: boolean; tasks: number[]; new_look: boolean; exhausted: boolean; days_used: number[]; goal_done: boolean }; cooldown_days: number; max_asks: number; text: string; text_zh: string } }
  tasks: number
  days: number
  asks: number
  starred: boolean
  fetchedAt: number
  current: NudgeAsk | null
}

export const NUDGES_INITIAL: Nudges = {
  policy: { version: 1, star: { enabled: true, url: 'https://github.com/nano-muse/nanoMuse', moments: { signed_in: true, tasks: [3, 10, 30], new_look: true, exhausted: true, days_used: [7, 30], goal_done: true }, cooldown_days: 7, max_asks: 4, text: '', text_zh: '' } },
  tasks: 0,
  days: 0,
  asks: 0,
  starred: false,
  fetchedAt: 0,
  current: null,
}

export interface Rooms {
  lang: string
  feed: { instructions: string; generatedAt: number; lastTry: number; posts: FeedPost[]; routine: FeedRoutine }
  ideas: { generatedAt: number; lastTry: number; items: Idea[] }
  goals: Goal[]
  library: LibraryItem[]
  memory: MemoryItem[]
  docs: { identity: string; soul: string; identityAt: number; soulAt: number }
  activity: ActivityRecord[]
  introducedAt: number
  busy: { feed: boolean; ideas: boolean }
  /** The chats of the batches running right now (the feed's): not listed, not searched. */
  batches: string[]
  automations: Record<string, GoalAutomation[]>
  ready: boolean
  studio: { description: string; style: string; at: number }
  firstRun: FirstRun
  nudges: Nudges
  /** Whether the stream is open; false before the first snapshot and while reconnecting. */
  streaming: boolean
  /** When the person last had the Feed open (this browser); the rail's dot marks newer posts. */
  feedSeenAt: number
}

const SEEN_KEY = 'nanomuse.feedSeenAt'

const INITIAL: Rooms = {
  lang: '',
  feed: { instructions: '', generatedAt: 0, lastTry: 0, posts: [], routine: { on: true, time: '08:00', ensuredAt: 0 } },
  ideas: { generatedAt: 0, lastTry: 0, items: [] },
  goals: [],
  library: [],
  memory: [],
  docs: { identity: '', soul: '', identityAt: 0, soulAt: 0 },
  activity: [],
  introducedAt: 0,
  busy: { feed: false, ideas: false },
  batches: [],
  automations: {},
  ready: false,
  studio: { description: '', style: 'muse', at: 0 },
  firstRun: FIRST_RUN_INITIAL,
  nudges: NUDGES_INITIAL,
  streaming: false,
  feedSeenAt: Number(globalThis.localStorage?.getItem(SEEN_KEY) ?? 0) || 0,
}

const API = 'nanomuse/rooms'
export const EVENTS_URL = `${API}/events`

let snapshot: Rooms = INITIAL
let source: EventSource | undefined
let langSent = false
const listeners = new Set<() => void>()

function publish(next: Rooms): void {
  snapshot = next
  for (const listener of listeners) listener()
}

function open(): void {
  if (source || typeof EventSource === 'undefined') return
  const es = new EventSource(EVENTS_URL)
  source = es
  es.onmessage = (event: MessageEvent<string>) => {
    try {
      const data = JSON.parse(event.data) as Omit<Rooms, 'streaming'>
      // an older host sends no first run, nudges, routine or batches: the defaults stand in
      publish({ ...snapshot, ...data, feed: { ...INITIAL.feed, ...data.feed, routine: data.feed?.routine ?? INITIAL.feed.routine }, firstRun: data.firstRun ?? FIRST_RUN_INITIAL, nudges: data.nudges ?? NUDGES_INITIAL, batches: data.batches ?? [], streaming: true })
      // The host writes the rooms in the person's language; tell it once which that is.
      if (!langSent && typeof navigator !== 'undefined' && navigator.language && data.lang !== navigator.language) {
        langSent = true
        void roomsCall('lang', { lang: navigator.language }).catch(() => undefined)
      } else {
        langSent = true
      }
    } catch {
      // a malformed frame is skipped; the next snapshot replaces everything anyway
    }
  }
  es.onerror = () => {
    if (snapshot.streaming) publish({ ...snapshot, streaming: false })
    if (es.readyState === 2) {
      source = undefined
      // only while someone still listens: the last unsubscribe may land inside these 3 s
      setTimeout(() => {
        if (listeners.size > 0) open()
      }, 3000)
    }
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  open()
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0 && source) {
      source.close()
      source = undefined
    }
  }
}

function getSnapshot(): Rooms {
  return snapshot
}

/** The rooms' state right now, outside React. */
export function peekRooms(): Rooms {
  return snapshot
}

/** The rooms' state; the stream opens with the first subscriber. */
export function useRooms(): Rooms {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

/** The Feed is open: its posts count as seen. */
export function markFeedSeen(): void {
  const at = Date.now()
  try {
    globalThis.localStorage?.setItem(SEEN_KEY, String(at))
  } catch {
    // private mode; the dot comes back next launch, no harm
  }
  publish({ ...snapshot, feedSeenAt: at })
}

/** GET when there is no body, POST with one; 204 resolves to undefined. */
export async function roomsCall<T = undefined>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}/${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'content-type': 'application/json', 'x-nanomuse': '1' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  if (res.status === 204) return undefined as T
  const json = (await res.json().catch(() => ({}))) as { error?: { message?: string } }
  if (!res.ok) throw new Error(json.error?.message ?? `${res.status}`)
  return json as T
}

/** The URL of a Library file's bytes (previews) — `raw=1` — or its text. */
export function fileUrl(id: string, raw = true): string {
  return `${API}/library/file?id=${encodeURIComponent(id)}${raw ? '&raw=1' : ''}`
}

/** Where the rooms send the person next: set by the plugin entry, read by the panels. */
export const nav: {
  openSession(id: string): void
  showChats(): void
  startSession(): void
  /** Show a room beside the chat (Muse's split: chat on the left, the room on the right), or close the split. */
  split(panel: string | null): void
  /** Put words in the composer for the person to finish (Muse's "I want to create an image of …"). */
  prefill(text: string): void
  /** Which panel the frame shows now (null = the chats). */
  activePanel(): string | null
  /** The frame's left column, from a room's top-left button. */
  toggleSidebar(): void
} = {
  openSession: () => undefined,
  showChats: () => undefined,
  startSession: () => undefined,
  split: () => undefined,
  prefill: () => undefined,
  activePanel: () => null,
  toggleSidebar: () => undefined,
}

/** The record of one chat, from the stream's snapshot. */
export function activityOf(rooms: Rooms, sessionId: string | null | undefined): ActivityRecord | undefined {
  return sessionId ? rooms.activity.find((r) => r.sessionId === sessionId) : undefined
}
