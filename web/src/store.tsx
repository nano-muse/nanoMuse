import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import { api, AuthError, connectWs, getToken } from "./api";
import { getLocale, t } from "./i18n";
import { liveWorking } from "./presence";
import { registerWorker, setAppBadge } from "./push";
import { useTheme } from "./theme";
import { readStorage, writeStorage } from "./util";
import type {
  ApprovalEvent,
  AttachmentInfo,
  CodingEvent,
  CodingRun,
  FirstRunView,
  Goal,
  HandsLive,
  HandsStatus,
  HoldEvent,
  HubView,
  Profile,
  SettingsView,
  StateSnapshot,
  StudioSession,
  Status,
  ThreadMeta,
  TimelineEvent,
  WorkingPresence,
  WsMessage,
} from "./types";

/** Tab bar: chat · feed · ideas · goals · library. Memory, devices, connections and settings live behind the avatar. */
export type Tab = "chat" | "feed" | "ideas" | "goals" | "library" | "memory" | "devices" | "connections" | "channels" | "skills" | "you" | "account" | "coding" | "avatar";
/**
 * The page this app is framed in (the showcase's simulated phone), when it can be named: the
 * ancestor's origin where the browser exposes it, else the referrer's. A message to the parent
 * goes to that origin only — never to whatever happens to hold the frame.
 */
function parentOrigin(): string | null {
  if (window.parent === window) return null;
  const ancestors = window.location.ancestorOrigins;
  if (ancestors && ancestors.length > 0 && ancestors[0] !== "null") return ancestors[0];
  if (document.referrer) {
    try {
      return new URL(document.referrer).origin;
    } catch {
      return null;
    }
  }
  return null;
}

function tellParent(message: { type: string; [k: string]: unknown }): void {
  const origin = parentOrigin();
  if (origin) window.parent.postMessage(message, origin);
}

const TAB_NAMES: Tab[] = ["chat", "feed", "ideas", "goals", "library", "memory", "devices", "connections", "channels", "skills", "you", "account", "coding", "avatar"];

/** A coding run being followed live: the run itself and the steps that arrived so far. */
export interface CodingLive {
  run: CodingRun;
  events: CodingEvent[];
  /** the text the agent is writing right now (partial deltas) */
  current: string;
}

const FEED_SEEN_KEY = "nanomuse_feed_seen";
/** The browser stepped past the sign-in door for a key of its own. */
const SIGN_IN_SKIPPED_KEY = "nanomuse_sign_in_skipped";

export interface Stream {
  id: string;
  text: string;
  ended: boolean;
}

export interface AppState {
  connected: boolean;
  loaded: boolean;
  authError: boolean;
  /** the runtime behind this page has ended (the gateway closed the socket for good) */
  gone: boolean;
  error: string | null;
  version: string;
  profile: Profile | null;
  status: Status;
  threads: ThreadMeta[];
  activeThread: string;
  events: Record<string, TimelineEvent[]>;
  hasMore: Record<string, boolean>;
  streams: Record<string, Stream | undefined>;
  goals: Goal[];
  settings: SettingsView | null;
  goalsVersion: number;
  memoryVersion: number;
  /** Bumped when a reminder or routine is set, fires or is cancelled. */
  remindersVersion: number;
  calendarVersion: number;
  /** Cards waiting for you, across every thread — the approvals queue. */
  pendingApprovals: ApprovalEvent[];
  /** Bumps whenever something lands in the Feed (background work, cards, artifacts). */
  feedVersion: number;
  /** ISO time of the newest Feed item you have looked at. */
  feedSeenAt: string;
  /** Path of the workspace file open in the viewer, if any. */
  viewer: string | null;
  /** Text to put in the chat composer next time it shows (e.g. "/weekly-review "). */
  draft: string | null;
  /** attachments handed over from outside (the phone's share sheet), already uploaded */
  draftFiles: AttachmentInfo[] | null;
  /** Bumps when a connection (model, email, browser, MCP) changes on the server. */
  connectionsVersion: number;
  /** Bumps when a skill is added, changed, switched or removed on the server. */
  skillsVersion: number;
  /** First-run setup dismissed for this session (the server remembers a finished one). */
  onboardingDismissed: boolean;
  /** The sign-in door stepped past for a key of one's own (kept in storage): the sign-in stays an invitation under Connections. */
  signInSkipped: boolean;
  tab: Tab;
  toast: string | null;
  /** The chats drawer (the phone's hamburger) is open. */
  drawer: boolean;
  /** When the agent last went from working to idle (ms since epoch; 0 = never). The face is pleased for a moment. */
  finishedAt: number;
  /** When a tool call last failed or was refused (ms since epoch; 0 = never). The face is worried for a moment. */
  mishapAt: number;
  /** This device on the hub and the other devices of the account (null until the first state). */
  hub: HubView | null;
  /** Coding runs followed live, newest last (kept for this page only). */
  codingLive: Record<string, CodingLive>;
  /** This computer's own screen and hands. */
  hands: HandsStatus | null;
  /** The holds that are on (contract C1): the person has the browser, the screen or the phone. */
  holds: HoldEvent[];
  /** The latest live step of the hands, for the stage; cleared when the task ends. */
  handsLive: HandsLive | null;
  /** The avatar studio's session as the runtime last reported it (null until one runs). */
  studio: StudioSession | null;
  /**
   * The other devices' turns under way on synced chats (contract C9), by thread: the line
   * "Pixel 8 is working…" under a message written there. Set by the `working` frames, cleared
   * when the reply arrives, when that device says done, or ten minutes after `at`.
   */
  working: Record<string, WorkingPresence | undefined>;
  /**
   * The first conversation (contract C4) as the runtime holds it: which thread it is bound
   * to, its phase, the chooser's names. From the hello snapshot and the `firstrun` frames;
   * null on an older runtime, and the chat then shows its plain greeting.
   */
  firstrun: FirstRunView | null;
  /**
   * `?ui=lite`: the app as it is shown inside the simulated phone of the showcase
   * (demo/mobilegym) — the phone layout with its tabs at any width, no sidebar, no first-run
   * setup and no desktop hints. Kept for the tab (sessionStorage) so a reload inside the frame
   * stays lite.
   */
  lite: boolean;
}

type Action =
  | { type: "hello"; state: StateSnapshot }
  | { type: "ws"; msg: WsMessage }
  | { type: "connection"; connected: boolean }
  | { type: "authError" }
  | { type: "gone" }
  | { type: "error"; error: string | null }
  | { type: "events"; thread: string; events: TimelineEvent[]; hasMore: boolean; prepend?: boolean }
  | { type: "eventsFailed"; thread: string }
  | { type: "activeThread"; thread: string }
  | { type: "goals"; goals: Goal[] }
  | { type: "settings"; settings: SettingsView }
  | { type: "tab"; tab: Tab }
  | { type: "drawer"; open: boolean }
  | { type: "feedSeen"; at: string }
  | { type: "viewer"; path: string | null }
  | { type: "draft"; text: string | null }
  | { type: "draftFiles"; files: AttachmentInfo[] | null }
  | { type: "onboardingDismissed" }
  | { type: "signInSkipped" }
  | { type: "toast"; toast: string | null };

const LITE_KEY = "nanomuse.ui.lite";

/** `?ui=lite` on this load, or remembered from an earlier one in this tab. */
function liteFromUrl(): boolean {
  try {
    const url = new URL(window.location.href);
    if (url.searchParams.get("ui") === "lite") {
      sessionStorage.setItem(LITE_KEY, "1");
      return true;
    }
    if (url.searchParams.get("ui") === "full") {
      sessionStorage.removeItem(LITE_KEY);
      return false;
    }
    return sessionStorage.getItem(LITE_KEY) === "1";
  } catch {
    return false;
  }
}

const initial: AppState = {
  connected: false,
  loaded: false,
  authError: false,
  gone: false,
  error: null,
  version: "",
  profile: null,
  status: { state: "idle", detail: "", thread: "main" },
  threads: [],
  activeThread: "main",
  events: {},
  hasMore: {},
  streams: {},
  goals: [],
  settings: null,
  goalsVersion: 0,
  memoryVersion: 0,
  remindersVersion: 0,
  calendarVersion: 0,
  pendingApprovals: [],
  feedVersion: 0,
  feedSeenAt: readStorage(FEED_SEEN_KEY) ?? "",
  viewer: null,
  draft: null,
  draftFiles: null,
  connectionsVersion: 0,
  skillsVersion: 0,
  onboardingDismissed: false,
  signInSkipped: readStorage(SIGN_IN_SKIPPED_KEY) === "1",
  tab: "chat",
  toast: null,
  drawer: false,
  finishedAt: 0,
  mishapAt: 0,
  hub: null,
  codingLive: {},
  lite: liteFromUrl(),
  hands: null,
  holds: [],
  handsLive: null,
  studio: null,
  working: {},
  firstrun: null,
};

function upsertApproval(list: ApprovalEvent[], ev: TimelineEvent): ApprovalEvent[] {
  if (ev.type !== "approval") return list;
  const rest = list.filter((a) => a.id !== ev.id);
  return ev.status === "pending" ? [...rest, ev] : rest;
}

/** Events that belong in the Feed: background work, cards waiting for you, artifacts. */
function isFeedWorthy(ev: TimelineEvent): boolean {
  if (ev.type === "approval" || ev.type === "question") return true;
  return ev.source === "background" || ev.source === "goal";
}

/**
 * Events as the chat keeps them. A `hold` event's `ts` is seconds since the epoch (contract
 * C1, shared with the native apps); everything else in the timeline is ISO, so it is made
 * ISO here and the dividers, the thread list and the cards read one kind of time.
 */
export function normalizeEvent<T extends TimelineEvent>(ev: T): T {
  const ts = ev.ts as unknown;
  if (typeof ts !== "number") return ev;
  return { ...ev, ts: new Date(ts * 1000).toISOString() };
}

function upsertEvent(list: TimelineEvent[] | undefined, ev: TimelineEvent): TimelineEvent[] {
  const events = list ?? [];
  const idx = events.findIndex((e) => e.id === ev.id);
  if (idx >= 0) {
    const next = events.slice();
    next[idx] = ev;
    return next;
  }
  // A row pulled from another device of the account (C8) may be older than what is on
  // screen: it goes where its time says, after anything written here in the same moment.
  // Everything else happens now and lands at the end.
  if (ev.synced && ev.ts && events.length > 0 && (events[events.length - 1]?.ts ?? "") > ev.ts) {
    let at = events.length;
    while (at > 0 && (events[at - 1]?.ts ?? "") > ev.ts) at -= 1;
    return [...events.slice(0, at), ev, ...events.slice(at)];
  }
  return [...events, ev];
}

/** The open holds: a hold that went off leaves the list, one that went on joins it. */
function upsertHold(list: HoldEvent[], ev: HoldEvent): HoldEvent[] {
  const rest = list.filter((h) => h.id !== ev.id);
  return ev.status === "on" ? [...rest, ev] : rest;
}

function upsertThread(list: ThreadMeta[], meta: ThreadMeta): ThreadMeta[] {
  const idx = list.findIndex((t) => t.id === meta.id);
  if (idx >= 0) {
    const next = list.slice();
    next[idx] = meta;
    return next;
  }
  return [...list, meta];
}

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "hello": {
      const s = action.state;
      // a fresh snapshot: what was streaming or working before the socket dropped is gone
      for (const k of Object.keys(perThread)) delete perThread[k];
      return {
        ...state,
        loaded: true,
        authError: false,
        version: s.version,
        profile: s.profile,
        status: s.status,
        streams: {},
        threads: s.threads,
        goals: s.goals,
        settings: s.settings,
        pendingApprovals: s.pending_approvals,
        feedVersion: state.feedVersion + 1,
        activeThread: s.threads.some((t) => t.id === state.activeThread) ? state.activeThread : "main",
        hub: s.hub ?? state.hub,
        hands: s.hands ?? state.hands,
        holds: (s.holds ?? []).map(normalizeEvent),
        working: liveWorking(s.working),
        firstrun: s.firstrun ?? state.firstrun,
      };
    }
    case "connection":
      return { ...state, connected: action.connected };
    case "authError":
      return { ...state, authError: true, connected: false };
    case "gone":
      return { ...state, gone: true, connected: false };
    case "error":
      return { ...state, error: action.error };
    case "events": {
      const existing = state.events[action.thread] ?? [];
      const incoming = action.events.map(normalizeEvent);
      const merged = action.prepend ? [...incoming, ...existing.filter((e) => !incoming.some((n) => n.id === e.id))] : incoming;
      return {
        ...state,
        events: { ...state.events, [action.thread]: merged },
        hasMore: { ...state.hasMore, [action.thread]: action.hasMore },
      };
    }
    case "eventsFailed":
      // the timeline could not be loaded: show the empty chat (with a toast) instead of nothing
      return {
        ...state,
        events: { ...state.events, [action.thread]: state.events[action.thread] ?? [] },
        toast: t("Could not load the conversation. Pull to retry."),
      };
    case "activeThread":
      return { ...state, activeThread: action.thread, tab: "chat" };
    case "goals":
      return { ...state, goals: action.goals };
    case "settings":
      return { ...state, settings: action.settings, profile: action.settings.profile };
    case "tab":
      return { ...state, tab: action.tab };
    case "drawer":
      return { ...state, drawer: action.open };
    case "feedSeen":
      writeStorage(FEED_SEEN_KEY, action.at);
      return { ...state, feedSeenAt: action.at };
    case "viewer":
      return { ...state, viewer: action.path };
    case "draft":
      return { ...state, draft: action.text };
    case "draftFiles":
      return { ...state, draftFiles: action.files };
    case "onboardingDismissed":
      return { ...state, onboardingDismissed: true };
    case "signInSkipped":
      return { ...state, signInSkipped: true };
    case "toast":
      return { ...state, toast: action.toast };
    case "ws":
      return applyWs(state, action.msg);
    default:
      return state;
  }
}

function applyWs(state: AppState, msg: WsMessage): AppState {
  switch (msg.kind) {
    case "hello":
      return reducer(state, { type: "hello", state: msg.state });
    case "event":
    case "update": {
      const ev = normalizeEvent(msg.event);
      const streams = { ...state.streams };
      const stream = streams[ev.thread];
      if (ev.type === "assistant" && stream && stream.id === ev.id) streams[ev.thread] = undefined;
      const threads = state.threads.map((t) =>
        t.id === ev.thread && msg.kind === "event" ? { ...t, updated_at: ev.ts } : t,
      );
      // Only threads whose history has been loaded get the event merged in; the rest are
      // fetched when opened. The approvals queue and the Feed follow every thread.
      const loaded = state.events[ev.thread] !== undefined;
      const mishap = (ev.type === "tool" && (ev.status === "error" || ev.status === "blocked")) || (ev.type === "notice" && ev.level === "error");
      // the reply from the device that was working arrived: its line goes (C9)
      let working = state.working;
      const line = working[ev.thread];
      if (line && ev.type === "assistant" && ev.synced && ev.via_device === line.device) {
        working = { ...working, [ev.thread]: undefined };
      }
      return {
        ...state,
        streams,
        threads,
        working,
        events: loaded ? { ...state.events, [ev.thread]: upsertEvent(state.events[ev.thread], ev) } : state.events,
        holds: ev.type === "hold" ? upsertHold(state.holds, ev) : state.holds,
        pendingApprovals: upsertApproval(state.pendingApprovals, ev),
        feedVersion: isFeedWorthy(ev) ? state.feedVersion + 1 : state.feedVersion,
        mishapAt: mishap ? Date.now() : state.mishapAt,
      };
    }
    case "stream_start":
      return {
        ...state,
        streams: { ...state.streams, [msg.thread]: { id: msg.id, text: "", ended: false } },
      };
    case "delta": {
      const current = state.streams[msg.thread];
      const stream: Stream =
        current && current.id === msg.id
          ? { ...current, text: current.text + msg.text }
          : { id: msg.id, text: msg.text, ended: false };
      return { ...state, streams: { ...state.streams, [msg.thread]: stream } };
    }
    case "stream_end": {
      const current = state.streams[msg.thread];
      if (!current || current.id !== msg.id) return state;
      // Keep it until the persisted assistant event replaces it (avoids flicker);
      // an empty stream, or one the server says was not a reply, can go right away.
      if (msg.discard || !current.text.trim()) return { ...state, streams: { ...state.streams, [msg.thread]: undefined } };
      return { ...state, streams: { ...state.streams, [msg.thread]: { ...current, ended: true } } };
    }
    case "status": {
      const st = msg.status;
      const streams = { ...state.streams };
      const s = streams[st.thread];
      if (s?.ended && st.state !== "working") streams[st.thread] = undefined;
      const overall = pickOverall(state.status, st);
      const finished = state.status.state === "working" && overall.state === "idle";
      return { ...state, status: overall, streams, finishedAt: finished ? Date.now() : state.finishedAt };
    }
    case "thread":
      return { ...state, threads: upsertThread(state.threads, msg.thread) };
    case "thread_deleted": {
      const events = { ...state.events };
      delete events[msg.thread];
      return {
        ...state,
        events,
        holds: state.holds.filter((h) => h.thread !== msg.thread),
        threads: state.threads.filter((t) => t.id !== msg.thread),
        pendingApprovals: state.pendingApprovals.filter((a) => a.thread !== msg.thread),
        activeThread: state.activeThread === msg.thread ? "main" : state.activeThread,
      };
    }
    case "thread_cleared":
      return {
        ...state,
        events: { ...state.events, [msg.thread]: [] },
        holds: state.holds.filter((h) => h.thread !== msg.thread),
        pendingApprovals: state.pendingApprovals.filter((a) => a.thread !== msg.thread),
      };
    case "event_removed": {
      const list = state.events[msg.thread];
      if (!list) return state;
      return { ...state, events: { ...state.events, [msg.thread]: list.filter((e) => e.id !== msg.id) } };
    }
    case "firstrun":
      // the first conversation moved on (contract C4): the chat redraws its chooser
      return { ...state, firstrun: msg.firstrun };
    case "working": {
      // another device started or finished a turn on a synced chat (C9); a `false` from a
      // device other than the one shown changes nothing
      const { kind: _kind, working: on, ...who } = msg;
      void _kind;
      const current = state.working[who.thread];
      if (on) return { ...state, working: { ...state.working, [who.thread]: who } };
      if (!current || current.device !== who.device) return state;
      return { ...state, working: { ...state.working, [who.thread]: undefined } };
    }
    case "goals":
      return { ...state, goalsVersion: state.goalsVersion + 1 };
    case "memory":
      return { ...state, memoryVersion: state.memoryVersion + 1 };
    case "reminders":
    case "triggers":
      return { ...state, remindersVersion: state.remindersVersion + 1 };
    case "calendar":
      return { ...state, calendarVersion: state.calendarVersion + 1 };
    case "feed_posts":
      return { ...state, feedVersion: state.feedVersion + 1 };
    case "profile":
      return {
        ...state,
        profile: msg.profile,
        settings: state.settings ? { ...state.settings, profile: msg.profile } : state.settings,
      };
    case "settings":
      return { ...state, settings: msg.settings, profile: msg.settings.profile };
    case "connections":
      return { ...state, connectionsVersion: state.connectionsVersion + 1 };
    case "hub":
      return { ...state, hub: msg.hub };
    case "coding": {
      const id = msg.run?.id ?? msg.event.run;
      if (!id) return state;
      const prev = state.codingLive[id];
      const run: CodingRun | undefined = msg.run ?? prev?.run;
      if (!run) return state;
      const events = msg.event.kind === "run" ? (prev?.events ?? []) : [...(prev?.events ?? []), msg.event].slice(-400);
      let current = prev?.current ?? "";
      if (msg.event.kind === "text") current = msg.event.partial ? current + (msg.event.text ?? "") : "";
      if (msg.event.kind === "done" || msg.event.kind === "error") current = "";
      const live = { ...state.codingLive, [id]: { run: { ...run, device: msg.device ?? run.device }, events, current } };
      // keep the last 20 runs on the page
      const ids = Object.keys(live);
      if (ids.length > 20) for (const old of ids.sort((a, b) => live[a].run.started_at - live[b].run.started_at).slice(0, ids.length - 20)) delete live[old];
      return { ...state, codingLive: live };
    }
    case "hands_state":
      return { ...state, hands: msg.hands };
    case "studio":
      return { ...state, studio: msg.current };
    case "hands": {
      const { kind: _kind, ...live } = msg;
      void _kind;
      const ended = live.event === "end" || live.event === "stop";
      return { ...state, handsLive: ended ? null : live };
    }
    case "skills":
      return { ...state, skillsVersion: state.skillsVersion + 1 };
    case "error":
      return { ...state, toast: t(msg.error) };
    case "pong":
      return { ...state, status: msg.status };
    default:
      return state;
  }
}

/** Per-thread statuses arrive one at a time; show the busiest one under the avatar. */
const perThread: Record<string, Status> = {};
function pickOverall(prev: Status, incoming: Status): Status {
  perThread[incoming.thread] = incoming;
  const working = Object.values(perThread).filter((s) => s.state !== "idle");
  if (!working.length) return { state: "idle", detail: "", thread: "main" };
  working.sort((a, b) => Number(a.thread !== "main") - Number(b.thread !== "main"));
  return working[0] ?? prev;
}

interface StoreValue {
  state: AppState;
  dispatch: (a: Action) => void;
  send: (thread: string, text: string, files?: string[]) => Promise<void>;
  /** *Use nanoMuse Cloud this time*: the words again, one turn on the account's model; rejects with the runtime's sentence */
  sendViaCloud: (thread: string, text: string, files?: string[]) => Promise<void>;
  decide: (id: string, approved: boolean, scope?: string) => Promise<void>;
  loadEvents: (thread: string, before?: string) => Promise<void>;
  refreshGoals: () => Promise<void>;
  refreshSettings: () => Promise<void>;
  refreshHub: () => Promise<void>;
  setTab: (tab: Tab) => void;
  /** Open or close the chats drawer (the phone's hamburger). */
  setDrawer: (open: boolean) => void;
  openThread: (thread: string) => void;
  markFeedSeen: (at: string) => void;
  openFile: (path: string | null) => void;
  /** Put text in the chat composer and switch to the chat (a skill's "Use", for one). */
  draft: (text: string | null) => void;
  draftFiles: (files: AttachmentInfo[] | null) => void;
  dismissOnboarding: () => void;
  /** Past the sign-in door with a key of one's own; remembered by this browser. */
  skipSignIn: () => void;
  /** A short message at the bottom of the page. */
  toast: (text: string) => void;
}

const StoreContext = createContext<StoreValue | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial);
  const wsRef = useRef<ReturnType<typeof connectWs> | null>(null);

  useEffect(() => {
    getToken();
    // Frames that arrive together are applied together: a first pull brings 300 rows as 300
    // `event` frames in a burst (C9 tail), and one render for the burst is smooth where one
    // per frame is not. Deltas of a streaming reply wait a few milliseconds at most.
    const queue: WsMessage[] = [];
    let flush = 0;
    const drain = () => {
      flush = 0;
      const batch = queue.splice(0);
      for (const m of batch) dispatch({ type: "ws", msg: m });
    };
    const ws = connectWs({
      onMessage: (msg) => {
        queue.push(msg);
        if (!flush) flush = window.setTimeout(drain, 0);
      },
      onOpen: () => dispatch({ type: "connection", connected: true }),
      onClose: () => dispatch({ type: "connection", connected: false }),
      onAuthError: () => dispatch({ type: "authError" }),
      onGone: () => dispatch({ type: "gone" }),
    });
    wsRef.current = ws;
    api.state()
      .then((s) => dispatch({ type: "hello", state: s }))
      .catch((e) => {
        if (e instanceof AuthError) dispatch({ type: "authError" });
        else dispatch({ type: "error", error: String(e.message ?? e) });
      });
    return () => {
      if (flush) window.clearTimeout(flush);
      ws.close();
    };
  }, []);

  const loadGeneration = useRef<Record<string, number>>({});
  const loadEvents = useCallback(async (thread: string, before?: string) => {
    // a fresh load (not a scroll-back) supersedes any earlier one still in flight for
    // the same thread: the older answer is dropped when it finally comes
    const generation = before ? undefined : (loadGeneration.current[thread] = (loadGeneration.current[thread] ?? 0) + 1);
    try {
      const data = await api.events(thread, 150, before);
      if (generation !== undefined && loadGeneration.current[thread] !== generation) return;
      dispatch({ type: "events", thread, events: data.events, hasMore: data.has_more, prepend: !!before });
    } catch (e) {
      if (e instanceof AuthError) dispatch({ type: "authError" });
      else dispatch({ type: "eventsFailed", thread });
    }
  }, []);

  // The account as the runtime sees it, fetched directly: after a sign-in the socket
  // usually brings it, but the gate must not depend on the socket being up.
  const refreshHub = useCallback(async () => {
    try {
      dispatch({ type: "ws", msg: { kind: "hub", hub: await api.hub() } });
    } catch {
      /* offline */
    }
  }, []);

  useEffect(() => {
    if (state.loaded) void loadEvents(state.activeThread);
  }, [state.loaded, state.activeThread, loadEvents]);

  // Reload the current thread after a reconnect so nothing is missed.
  const wasConnected = useRef(false);
  useEffect(() => {
    if (state.connected && wasConnected.current && state.loaded) void loadEvents(state.activeThread);
    wasConnected.current = state.connected;
  }, [state.connected, state.loaded, state.activeThread, loadEvents]);

  const refreshGoals = useCallback(async () => {
    try {
      dispatch({ type: "goals", goals: await api.goals() });
    } catch {
      /* offline */
    }
  }, []);

  useEffect(() => {
    if (state.loaded) void refreshGoals();
  }, [state.goalsVersion, state.loaded, refreshGoals]);

  const refreshSettings = useCallback(async () => {
    try {
      dispatch({ type: "settings", settings: await api.settings() });
    } catch {
      /* offline */
    }
  }, []);

  useEffect(() => {
    if (!state.toast) return;
    const t = window.setTimeout(() => dispatch({ type: "toast", toast: null }), 3500);
    return () => window.clearTimeout(t);
  }, [state.toast]);

  // The service worker (push + app badge) and where a notification tap should land.
  useEffect(() => {
    void registerWorker();
    // `?thread=<id>` opens a chat, `?tab=goals` (feed, ideas, library, connections) a tab —
    // used by notification taps and by links into the app.
    // `?draft=<text>&attach=<json>` puts text and already-uploaded files into the composer
    // without sending — how "Share to nanoMuse" from another app on the phone arrives.
    const openFromUrl = (href: string) => {
      const url = new URL(href, window.location.origin);
      const thread = url.searchParams.get("thread");
      const tab = url.searchParams.get("tab");
      if (thread) dispatch({ type: "activeThread", thread });
      if (tab && TAB_NAMES.includes(tab as Tab) && !thread) dispatch({ type: "tab", tab: tab as Tab });
      else dispatch({ type: "tab", tab: "chat" });
      const text = url.searchParams.get("draft");
      if (text) dispatch({ type: "draft", text });
      const attach = url.searchParams.get("attach");
      if (attach) {
        try {
          const files = JSON.parse(attach) as AttachmentInfo[];
          if (Array.isArray(files) && files.length) dispatch({ type: "draftFiles", files: files.filter((f) => f && typeof f.path === "string") });
        } catch {
          /* not ours */
        }
      }
    };
    const initial = new URL(window.location.href);
    if (["thread", "tab", "draft", "attach", "ui"].some((k) => initial.searchParams.has(k))) {
      openFromUrl(initial.href);
      for (const k of ["thread", "tab", "draft", "attach", "ui"]) initial.searchParams.delete(k);
      window.history.replaceState({}, "", initial.toString());
    }
    const onMessage = (ev: MessageEvent) => {
      if (ev.data && ev.data.type === "open") openFromUrl(String(ev.data.url || "/"));
    };
    navigator.serviceWorker?.addEventListener("message", onMessage);
    // Inside another page's frame (the simulated phone of the showcase), the page may hand
    // over a draft the same way a link does — `{type: "nanomuse:draft", text}` from the
    // parent window, and only from it. Text in the composer is all it can do; sending is a tap.
    const onParent = (ev: MessageEvent) => {
      if (window.parent === window || ev.source !== window.parent) return;
      const data = ev.data as { type?: unknown; text?: unknown } | null;
      if (!data || data.type !== "nanomuse:draft" || typeof data.text !== "string") return;
      dispatch({ type: "tab", tab: "chat" });
      dispatch({ type: "draft", text: data.text.slice(0, 4000) });
    };
    window.addEventListener("message", onParent);
    return () => {
      navigator.serviceWorker?.removeEventListener("message", onMessage);
      window.removeEventListener("message", onParent);
    };
  }, []);

  // The embedding page learns when the app is up (and which agent it shows), so it can hand
  // over a draft only once there is a composer to put it in — and which colour scheme the app
  // is in, so the frame around it can match (`nanomuse:theme` again whenever that changes).
  const theme = useTheme();
  useEffect(() => {
    if (!state.loaded) return;
    tellParent({ type: "nanomuse:ready", name: state.profile?.name ?? "", theme });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.loaded, state.profile?.name]);
  useEffect(() => {
    if (!state.loaded) return;
    tellParent({ type: "nanomuse:theme", theme });
  }, [state.loaded, theme]);

  // The number on the app icon: cards waiting for you.
  useEffect(() => {
    if (state.loaded) setAppBadge(state.pendingApprovals.length);
  }, [state.loaded, state.pendingApprovals.length]);

  const value = useMemo<StoreValue>(
    () => ({
      state,
      dispatch,
      send: async (thread, text, files = []) => {
        if (!text.trim() && files.length === 0) return;
        // the locale of these screens rides along: the agent answers in it rather than
        // guessing from the script of one message
        const language = getLocale();
        try {
          // attachments go over REST so a failure (a path gone, a full disk) comes back as an error
          if (files.length > 0 || !wsRef.current?.send({ kind: "send", thread, text, language })) {
            await api.send(thread, text, files, language);
          }
        } catch (e) {
          if (e instanceof AuthError) dispatch({ type: "authError" });
          throw e;
        }
      },
      sendViaCloud: async (thread, text, files = []) => {
        if (!text.trim() && files.length === 0) return;
        try {
          // over REST: a refusal (signed out, the relay down) comes back as an error with its sentence
          await api.send(thread, text, files, getLocale(), "cloud");
        } catch (e) {
          if (e instanceof AuthError) dispatch({ type: "authError" });
          throw e;
        }
      },
      decide: async (id, approved, scope = "once") => {
        try {
          if (!wsRef.current?.send({ kind: "approval", id, approved, scope })) {
            await api.decide(id, approved, scope);
          }
        } catch (e) {
          if (e instanceof AuthError) dispatch({ type: "authError" });
          throw e;
        }
      },
      loadEvents,
      refreshGoals,
      refreshSettings,
      refreshHub,
      setTab: (tab) => dispatch({ type: "tab", tab }),
      setDrawer: (open) => dispatch({ type: "drawer", open }),
      openThread: (thread) => dispatch({ type: "activeThread", thread }),
      markFeedSeen: (at) => dispatch({ type: "feedSeen", at }),
      openFile: (path) => dispatch({ type: "viewer", path }),
      draftFiles: (files) => dispatch({ type: "draftFiles", files }),
      draft: (text) => {
        dispatch({ type: "draft", text });
        if (text !== null) dispatch({ type: "tab", tab: "chat" });
      },
      dismissOnboarding: () => dispatch({ type: "onboardingDismissed" }),
      skipSignIn: () => {
        writeStorage(SIGN_IN_SKIPPED_KEY, "1");
        dispatch({ type: "signInSkipped" });
      },
      toast: (text) => dispatch({ type: "toast", toast: t(text) }),
    }),
    [state, loadEvents, refreshGoals, refreshSettings, refreshHub],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): StoreValue {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore outside provider");
  return ctx;
}
