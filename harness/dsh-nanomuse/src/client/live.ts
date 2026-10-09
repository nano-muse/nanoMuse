/**
 * The host's live state in the browser: one `EventSource` on
 * `/nanomuse/cloud/events`, mirrored into a snapshot React reads with
 * `useSyncExternalStore`. The account, the agent's name and face, the hub and
 * its devices, the Hands/Reach calls in flight and the notices from other
 * devices all arrive on it; a dropped stream reconnects by itself.
 */
import { useSyncExternalStore } from 'react'
import type { Grant, Hold, PendingApproval, SharedConnector, UpdateInfo } from '../desk.ts'

export type { Grant, Hold, PendingApproval, SharedConnector, UpdateInfo }

export interface LiveProfile {
  rev: number
  name: string
  avatar: 'dragon' | 'emoji' | 'face'
  emoji: string
  color: string
  description: string
  style: string
  faceId: string
  /** The account's connections on every device (this one included), as the relay lists them. */
  connectors: SharedConnector[]
}

export interface LiveDevice {
  id: string
  name: string
  kind: string
  os: string
  version: string
  online: boolean
  last_seen: number
  controllable: boolean
  actions: string[]
}

export interface LiveCall {
  id: string
  name: string
  args: Record<string, string>
  sessionId: string
  since: number
}

/** The hands have this computer's screen: which session, since when (from its first `computer_*` call to its turn's end). */
export interface LiveScreenRun {
  sessionId: string
  since: number
}

export interface LiveNotice {
  id: number
  /** `notify`: words from another device; `call`: `action` ran here for `from`. */
  kind: 'notify' | 'call'
  from: string
  title: string
  text: string
  action?: string
  at: number
}

export interface LiveHub {
  connected: boolean
  deviceId: string
  deviceName: string
  /** On: every device may run things here without asking; off: each device asks on this screen. */
  remoteControl: boolean
  /** Devices allowed without asking. */
  trusted: LiveTrusted[]
  /** Questions from other devices waiting for an answer here. */
  asks: LiveAsk[]
  lastError?: string
  devices: LiveDevice[]
}

export interface LiveTrusted {
  id: string
  name: string
  at: number
}

export interface LiveAsk {
  id: string
  from: string
  fromId: string
  action: string
  text: string
  at: number
}

/** The last thing the hands did, for the capsule's caption, the glow's marker and the trajectory. */
export interface LiveStageAction {
  kind: string
  label: string
  text: string
  /** Pixels of the frame; -1 when the step had no point. */
  x: number
  y: number
  /** A drag's far end (0.1.40); -1 or absent otherwise. */
  x2?: number | undefined
  y2?: number | undefined
  /** A scroll's amount in pixels, negative = up (0.1.40); 0 or absent otherwise. */
  dy?: number | undefined
  at: number
}

/** The stage: the latest screenshot of a screen the agent is working on, and what it did on it. */
export interface LiveStage {
  /** 0 before any frame; grows with each new one (the frame URL's cache key). */
  seq: number
  at: number
  source: 'computer' | 'device'
  /** The other device's name; empty for this computer. */
  device: string
  width: number
  height: number
  /** What is in front on that screen. */
  title: string
  /** `window`: the hands drive one app's window and the pointer stays with the person. */
  mode?: 'screen' | 'window'
  action: LiveStageAction | null
  sessionId: string
}

export interface Live {
  cloud: { signedIn: boolean; hint: string }
  profile: LiveProfile
  hub: LiveHub
  /** The calls in flight, the step count, and the run that has this screen (`run`; absent on an older host, null between runs). */
  hands: { calls: LiveCall[]; steps: number; run?: LiveScreenRun | null }
  stage: LiveStage
  notices: LiveNotice[]
  /** Questions the agent asked before a step, open now; the stage answers them too. */
  approvals: PendingApproval[]
  /** Pauses of the hands that are on. */
  holds: Hold[]
  /** Standing "always allow" grants for the hands, per app. */
  grants: Grant[]
  /** The model the hands see the screen with; empty when the account has none. */
  handsModel: string
  /** The last update check, or null before one ran. */
  update: UpdateInfo | null
  /** The drawn face's clips and how their drawing goes (desk-b). */
  motion: LiveMotion
  /** When the hands last saw an all-black screen (macOS: Screen Recording missing or granted after launch); 0 when never. */
  blackScreenAt: number
  /** Conversation sync (C8): `rev` moves with every change; the session that is the account's main conversation. Absent on an older host. */
  sync?: { rev: number; mainSession: string } | undefined
  /** Own keys and the ChatGPT sign-in (C11): how many rows, what everything configured can do, where the sign-in stands. Absent on an older host. */
  ownKeys?: LiveOwnKeys | undefined
  /** The hands' trajectory (0.1.40): `rev` moves with every step; the sessions with a run to look back at. Absent on an older host. */
  trajectory?: { rev: number; sessions: string[] } | undefined
  /** The 80 % heads-up (C12) while it is due: what is left of the pool, the pool, what an invitation adds (yuan). Null or absent otherwise. */
  headsUp?: { left: number; grant: number; bonus: number } | null | undefined
  /** Whether the stream is open; false before the first snapshot and while reconnecting. */
  streaming: boolean
}

export type Capability = 'chat' | 'vision' | 'image' | 'video'

export interface LiveOwnKeys {
  count: number
  capabilities: Capability[]
  chatgpt: { signedIn: boolean; label: string; proxy: boolean; login: { status: 'idle' | 'waiting' | 'done' | 'error'; url: string; label: string; error: string } }
}

export type MotionMood = 'idle' | 'working' | 'waiting' | 'happy'

export interface LiveMotionProgress {
  done: number
  total: number
  failed: MotionMood[]
  running: boolean
  current?: MotionMood
  stage?: { kind: 'uploading' | 'submitted' | 'running' | 'downloading'; elapsedSec?: number }
  error?: string
  /** Where the run drew (0.1.41): `nanomuse` for the account, else an own row's id. Absent on an older host. */
  source?: string
}

export interface LiveMotion {
  progress: LiveMotionProgress | null
  /** The clips on disk, by mood: size in bytes and the mtime (`v`) the clip URL carries. */
  clips: Partial<Record<MotionMood, { size: number; v: number }>>
  /** The face the clips belong to; empty when there are none. */
  faceId: string
}

export const NO_MOTION: LiveMotion = { progress: null, clips: {}, faceId: '' }

export const DEFAULT_PROFILE: LiveProfile = { rev: 0, name: 'nanoMuse', avatar: 'dragon', emoji: '', color: '', description: '', style: '', faceId: '', connectors: [] }

const INITIAL: Live = {
  cloud: { signedIn: false, hint: '' },
  profile: DEFAULT_PROFILE,
  hub: { connected: false, deviceId: '', deviceName: '', remoteControl: false, trusted: [], asks: [], devices: [] },
  hands: { calls: [], steps: 0, run: null },
  stage: { seq: 0, at: 0, source: 'computer', device: '', width: 0, height: 0, title: '', action: null, sessionId: '' },
  notices: [],
  approvals: [],
  holds: [],
  grants: [],
  handsModel: '',
  update: null,
  motion: NO_MOTION,
  blackScreenAt: 0,
  streaming: false,
}

/** Document-relative, so it resolves under whatever mount served the page. */
export const EVENTS_URL = 'nanomuse/cloud/events'

let snapshot: Live = INITIAL
let source: EventSource | undefined
const listeners = new Set<() => void>()

function publish(next: Live): void {
  snapshot = next
  for (const listener of listeners) listener()
}

function open(): void {
  if (source || typeof EventSource === 'undefined') return
  const es = new EventSource(EVENTS_URL)
  source = es
  es.onmessage = (event: MessageEvent<string>) => {
    try {
      const data = JSON.parse(event.data) as Partial<Omit<Live, 'streaming'>>
      // An older host (0.1.33) sends no approvals/holds; keep the defaults rather than undefined.
      publish({ ...snapshot, ...data, profile: { ...DEFAULT_PROFILE, ...data.profile }, approvals: data.approvals ?? [], holds: data.holds ?? [], grants: data.grants ?? [], handsModel: data.handsModel ?? '', update: data.update ?? null, motion: data.motion ?? NO_MOTION, blackScreenAt: data.blackScreenAt ?? 0, streaming: true })
    } catch {
      // a malformed frame is skipped; the next snapshot replaces everything anyway
    }
  }
  es.onerror = () => {
    if (snapshot.streaming) publish({ ...snapshot, streaming: false })
    // EventSource reconnects on its own; a closed one (readyState 2) is reopened.
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

function getSnapshot(): Live {
  return snapshot
}

/** The host's live state; the stream opens with the first subscriber. */
export function useLive(): Live {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

/** The current snapshot outside React (e.g. a one-off check). */
export function peekLive(): Live {
  return snapshot
}

/** Hear every snapshot outside React; the stream opens with the first subscriber. */
export function subscribeLive(listener: (live: Live) => void): () => void {
  const off = subscribe(() => listener(snapshot))
  listener(snapshot)
  return off
}
