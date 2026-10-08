import type {
  ActivityData,
  AttachmentInfo,
  CalendarData,
  ChatGptLogin,
  ChatGptStatus,
  CloudAccount,
  CloudEvent,
  CloudConfig,
  CloudMe,
  CloudSession,
  CodingAgent,
  CodingRun,
  CodingSession,
  ConnectionsData,
  Contact,
  FeedItem,
  FeedPostsData,
  FileInfo,
  FirstRunView,
  Goal,
  HandsStatus,
  HoldEvent,
  HubView,
  IdeasData,
  MediaSlotData,
  MemoryChange,
  MemoryItem,
  NudgesView,
  ProvidersView,
  PushInfo,
  Reminder,
  ReminderKind,
  SettingsView,
  SkillDetail,
  SkillInfo,
  SkillsData,
  StateSnapshot,
  StudioSession,
  StudioView,
  SyncState,
  TestResult,
  ThreadMeta,
  TidyReport,
  TimelineEvent,
  Trigger,
  TriggerKind,
  TriggersData,
  UpcomingData,
  UpdateView,
  WsMessage,
} from "./types";
import { signedParams } from "./ticket";
import { readStorage, writeStorage } from "./util";

const TOKEN_KEY = "nanomuse_token";

export class AuthError extends Error {
  constructor() {
    super("unauthorized");
  }
}

/** The token in a link the runtime printed: `#token=…` (the fragment never reaches a
 *  server, so it is in no access log) or, from older links, `?token=…`. Taken off the
 *  address once read. */
export function tokenFromLink(url: URL): string | null {
  const parts = url.hash.replace(/^#/, "").split("&").filter(Boolean);
  const index = parts.findIndex((p) => p.startsWith("token="));
  if (index >= 0) {
    const token = decodeURIComponent(parts[index].slice("token=".length));
    parts.splice(index, 1);
    url.hash = parts.length ? `#${parts.join("&")}` : "";
    return token || null;
  }
  const query = url.searchParams.get("token");
  if (query) {
    url.searchParams.delete("token");
    return query;
  }
  return null;
}

/** Read the token from the link (first visit via QR code) or localStorage. */
export function getToken(): string {
  const url = new URL(window.location.href);
  const fromUrl = tokenFromLink(url);
  if (fromUrl) {
    writeStorage(TOKEN_KEY, fromUrl);
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }
  return readStorage(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  writeStorage(TOKEN_KEY, token || null);
}

/** A workspace file for an `<img>`, `<video>`, `<iframe>` or a download link: signed with
 *  the token rather than carrying it (ticket.ts) — the link opens this path for a few hours
 *  and nothing else, should it end up in a log. */
export function fileUrl(path: string, download = false): string {
  const token = getToken();
  const params = token ? signedParams(token, `/api/files/${path}`) : new URLSearchParams();
  if (download) params.set("download", "1");
  const q = params.toString();
  return `/api/files/${path.split("/").map(encodeURIComponent).join("/")}${q ? `?${q}` : ""}`;
}

/** A browser frame (JPEG) kept in memory on the server for the current run. */
export function frameUrl(thread: string, frame: string): string {
  const token = getToken();
  const q = token ? `?${signedParams(token, `/api/browser/${thread}/frames/${frame}.jpg`)}` : "";
  return `/api/browser/${encodeURIComponent(thread)}/frames/${encodeURIComponent(frame)}.jpg${q}`;
}

export interface BrowserControl {
  action: "click" | "type" | "key" | "scroll" | "navigate" | "look" | "take_over" | "back" | "handed_back";
  x?: number;
  y?: number;
  text?: string;
  key?: string;
  dy?: number;
  url?: string;
}

/** One call to the runtime: the bearer token, JSON in and out, 401 as `AuthError`, the
 *  server's `detail` as the error's text. `channels-api.ts` shares it. */
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (init.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch {
    // the browser's "Failed to fetch": the runtime is down or the network is
    throw new Error("Cannot reach your nanoMuse right now.");
  }
  if (res.status === 401) throw new AuthError();
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const data = await res.json();
      detail = data.detail ?? JSON.stringify(data);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  state: () => request<StateSnapshot>("/api/state"),
  // ---- nanoMuse Cloud (the account) and the hub (the other devices)
  cloud: () => request<CloudAccount>("/api/cloud"),
  cloudCode: (identifier: string) => request<{ ok: boolean }>("/api/cloud/code", json({ identifier })),
  cloudVerify: (identifier: string, code: string, invite = "") =>
    request<CloudAccount>("/api/cloud/verify", json(invite ? { identifier, code, invite } : { identifier, code })),
  cloudSignOut: () => request<CloudAccount>("/api/cloud/sign-out", json({})),
  /** *Use nanoMuse Cloud models*: the account's models as a source, on or off; `409 chat_on_cloud` while the chat model is the account's */
  cloudModels: (on: boolean) => request<CloudAccount>("/api/cloud/models", json({ on })),
  cloudLogin: (identifier: string, password: string) => request<CloudAccount>("/api/cloud/login", json({ identifier, password })),
  /** set or change the password; "" with the current one removes it */
  cloudPassword: (password: string, current?: string) => request<CloudAccount>("/api/cloud/password", json({ password, current: current ?? null })),
  cloudSessions: () => request<{ sessions: CloudSession[] }>("/api/cloud/sessions"),
  cloudRevokeSession: (prefix: string) => request<{ sessions: CloudSession[] }>(`/api/cloud/sessions/${encodeURIComponent(prefix)}`, { method: "DELETE" }),
  cloudSignOutAll: (all = false) => request<{ signed_out: number } & CloudAccount>("/api/cloud/sign-out-all", json({ all })),
  cloudEvents: (limit = 50) => request<{ events: CloudEvent[] }>(`/api/cloud/events?limit=${limit}`),
  cloudDelete: () => request<CloudAccount>("/api/cloud/delete", json({})),
  cloudMe: () => request<CloudMe>("/api/cloud/me"),
  /** The relay's public figures (relay 0.15); {} from an older relay. */
  cloudConfig: () => request<CloudConfig>("/api/cloud/config"),
  cloudContribute: (on: boolean) => request<{ on: boolean; samples: number; default_on?: boolean; privacy_url?: string }>("/api/cloud/contribute", json({ on })),
  cloudDeleteSamples: () => request<{ deleted: number }>("/api/cloud/samples", { method: "DELETE" }),
  cloudUseAsModel: (model = "") => request<Record<string, unknown>>("/api/cloud/use-as-model", json({ model })),
  // ---- conversations synced between the account's devices (contract C7)
  syncState: () => request<SyncState>("/api/sync/state"),
  /** off tells the relay, which deletes what it stores; on pushes this device's chats again */
  syncSetState: (enabled: boolean) => request<SyncState>("/api/sync/state", { method: "PUT", body: JSON.stringify({ enabled }) }),
  /** C9: "Also sync side chats" — per device; on pulls the other devices' side chats once from the start */
  syncSetSideChats: (side_chats: boolean) => request<SyncState>("/api/sync/state", { method: "PUT", body: JSON.stringify({ side_chats }) }),
  /** "Delete synced conversations": the relay's store emptied, the switch and the local chats kept */
  syncDelete: () => request<SyncState>("/api/sync/delete", json({})),
  syncPull: () => request<SyncState & { applied: number }>("/api/sync/pull", json({})),
  /** the avatar studio: whether a face can be drawn, and the session under way */
  avatarView: () => request<StudioView>("/api/avatar"),
  /** a session; `thread` "" runs it from the studio screen, without a card in the chat */
  avatarBegin: (description: string, thread = "main", style = "muse") =>
    request<StudioSession & { available?: boolean; message?: string }>("/api/avatar/begin", json({ description, thread, style })),
  avatarStart: (session: string) => request<StudioSession>("/api/avatar/start", json({ session })),
  avatarChoose: (session: string, index: number) => request<StudioSession>("/api/avatar/choose", json({ session, index })),
  avatarCancel: (session: string) => request<StudioSession>("/api/avatar/cancel", json({ session })),
  /** the poses (and clips) of the face the profile wears, drawn again from its idle still */
  avatarMoods: () => request<StudioSession>("/api/avatar/moods", json({})),
  // ---- coding agents, here or on another computer of yours
  coding: (device = "") => request<{ agents: CodingAgent[]; runs: CodingRun[]; device?: string }>(`/api/coding${device ? `?device=${encodeURIComponent(device)}` : ""}`),
  codingSessions: (q: { agent?: string; limit?: number; workspace?: string; device?: string } = {}) => {
    const params = new URLSearchParams();
    if (q.agent) params.set("agent", q.agent);
    if (q.limit) params.set("limit", String(q.limit));
    if (q.workspace) params.set("workspace", q.workspace);
    if (q.device) params.set("device", q.device);
    const qs = params.toString();
    return request<{ sessions: CodingSession[] }>(`/api/coding/sessions${qs ? `?${qs}` : ""}`);
  },
  codingSession: (agent: string, id: string, device = "") =>
    request<CodingSession>(`/api/coding/sessions/${encodeURIComponent(agent)}/${encodeURIComponent(id)}${device ? `?device=${encodeURIComponent(device)}` : ""}`),
  codingSend: (body: { agent: string; text: string; session_id?: string; workspace?: string; device?: string }) => request<CodingRun>("/api/coding/send", json(body)),
  codingStop: (run: string, device = "") => request<{ stopped: boolean }>("/api/coding/stop", json({ run, device })),
  hub: () => request<HubView>("/api/hub"),
  updateHub: (body: { enabled?: boolean; remote_control?: boolean; name?: string }) =>
    request<HubView>("/api/hub", { method: "PUT", body: JSON.stringify(body) }),
  joinHub: () => request<HubView>("/api/hub/join", json({})),
  leaveHub: () => request<HubView>("/api/hub/leave", json({})),
  refreshHub: () => request<HubView>("/api/hub/refresh", json({})),
  forgetDevice: (id: string) => request<HubView>(`/api/hub/devices/${encodeURIComponent(id)}`, { method: "DELETE" }),
  askDevice: (device: string, text = "") => request<{ thread: ThreadMeta; event: TimelineEvent | null }>("/api/hub/ask", json({ device, text })),
  // ---- this computer's screen and hands
  hands: () => request<HandsStatus>("/api/hands"),
  setHands: (body: { enabled?: boolean; backend?: string; mode?: string }) =>
    request<HandsStatus>("/api/connections/hands", { method: "PUT", body: JSON.stringify(body) }),
  stopHands: () => request<{ stopped: boolean }>("/api/hands/stop", json({})),
  // holds (contract C1): take the browser, the screen or the phone over; Done gives it back
  holds: () => request<HoldEvent[]>("/api/holds"),
  openHold: (thread: string, tool: "browser" | "computer" | "phone", reason = "") =>
    request<HoldEvent>("/api/holds", json({ thread, tool, reason })),
  doneHold: (id: string) => request<HoldEvent>(`/api/holds/${encodeURIComponent(id)}/done`, json({})),
  health: () => request<{ ok: boolean; version: string; auth: boolean }>("/api/health"),
  threads: () => request<ThreadMeta[]>("/api/threads"),
  createThread: (title: string) => request<ThreadMeta>("/api/threads", json({ title })),
  renameThread: (id: string, title: string) =>
    request<ThreadMeta>(`/api/threads/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  deleteThread: (id: string) => request<{ ok: boolean }>(`/api/threads/${id}`, { method: "DELETE" }),
  clearThread: (id: string) => request<{ ok: boolean }>(`/api/threads/${id}/clear`, { method: "POST" }),
  stopThread: (id: string) => request<{ ok: boolean }>(`/api/threads/${id}/stop`, { method: "POST" }),
  events: (thread: string, limit = 200, before?: string) =>
    request<{ thread: ThreadMeta; events: TimelineEvent[]; has_more: boolean }>(
      `/api/threads/${thread}/events?limit=${limit}${before ? `&before=${encodeURIComponent(before)}` : ""}`,
    ),
  /** `language` is the locale of this console's screens; the reply is written in it. `via: "cloud"` is
   * *Use nanoMuse Cloud this time*: this one turn on the account's model (401 `signed_out` when signed out). */
  send: (thread: string, text: string, files: string[] = [], language = "", via = "") =>
    request<{ event: TimelineEvent; thread: ThreadMeta }>(`/api/threads/${thread}/send`, json(via ? { text, files, language, via } : { text, files, language })),
  /** A file to attach: the bytes as the body, the name in the query. */
  upload: (file: File) =>
    request<AttachmentInfo>(`/api/files/upload?name=${encodeURIComponent(file.name || "photo.jpg")}`, {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    }),
  decide: (id: string, approved: boolean, scope = "once", reason = "") =>
    request<{ ok: boolean }>(`/api/approvals/${id}`, json({ approved, scope, reason })),
  resetApprovals: () => request<{ ok: boolean }>("/api/approvals", { method: "DELETE" }),
  revokeGrant: (key: string) =>
    request<{ ok: boolean }>(`/api/approvals/grants/${encodeURIComponent(key)}`, { method: "DELETE" }),
  goals: () => request<Goal[]>("/api/goals"),
  createGoal: (body: { title: string; description?: string; steps?: string[]; category?: string; due?: string; check_in?: string }) =>
    request<Goal>("/api/goals", json(body)),
  patchGoal: (id: string, patch: Record<string, unknown>) =>
    request<Goal>(`/api/goals/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  addStep: (id: string, title: string) => request<Goal>(`/api/goals/${id}/steps`, json({ title })),
  advanceGoal: (id: string) => request<Goal>(`/api/goals/${id}/advance`, { method: "POST" }),
  checkInGoal: (id: string) => request<Goal>(`/api/goals/${id}/check-in`, { method: "POST" }),
  acceptProposal: (id: string) => request<Goal>(`/api/goals/${id}/proposal/accept`, { method: "POST" }),
  dismissProposal: (id: string) => request<Goal>(`/api/goals/${id}/proposal`, { method: "DELETE" }),
  deleteGoal: (id: string) => request<{ ok: boolean }>(`/api/goals/${id}`, { method: "DELETE" }),
  memory: () => request<MemoryItem[]>("/api/memory"),
  addMemory: (content: string, category: string) =>
    request<MemoryItem>("/api/memory", json({ content, category })),
  forgetMemory: (id: string) => request<{ ok: boolean }>(`/api/memory/${id}`, { method: "DELETE" }),
  tidyMemory: () => request<TidyReport>("/api/memory/tidy", { method: "POST" }),
  memoryChanges: (limit = 30) => request<MemoryChange[]>(`/api/memory/changes?limit=${limit}`),
  restoreMemoryChange: (id: string) =>
    request<MemoryChange>(`/api/memory/changes/${id}/restore`, { method: "POST" }),
  ideas: (refresh = false) => request<IdeasData>(`/api/ideas${refresh ? "?refresh=1" : ""}`),
  activity: (n = 150) => request<ActivityData>(`/api/activity?n=${n}`),
  feed: (limit = 60) => request<FeedItem[]>(`/api/feed?limit=${limit}`),
  feedPosts: () => request<FeedPostsData>("/api/feed/posts"),
  /** The feed's preferences; only the fields given change (`daily`/`time` are the 08:00 routine). */
  setFeedInstructions: (body: { instructions?: string; daily?: boolean; time?: string }) =>
    request<FeedPostsData>("/api/feed/instructions", { method: "PUT", body: JSON.stringify(body) }),
  refreshFeedPosts: () => request<FeedPostsData>("/api/feed/posts/refresh", { method: "POST" }),
  deleteFeedPost: (id: string) => request<{ ok: boolean }>(`/api/feed/posts/${id}`, { method: "DELETE" }),
  upcoming: () => request<UpcomingData>("/api/upcoming"),
  reminders: (all = false) => request<Reminder[]>(`/api/reminders${all ? "?all=1" : ""}`),
  createReminder: (body: { text: string; kind?: ReminderKind; at?: string; repeat?: string; thread?: string }) =>
    request<Reminder>("/api/reminders", { method: "POST", body: JSON.stringify(body) }),
  fireReminder: (id: string) => request<Reminder>(`/api/reminders/${id}/fire`, { method: "POST" }),
  cancelReminder: (id: string) => request<Reminder>(`/api/reminders/${id}`, { method: "DELETE" }),
  triggers: () => request<TriggersData>("/api/triggers"),
  createTrigger: (body: { kind: TriggerKind; text: string; match?: string; lead_minutes?: number; thread?: string }) =>
    request<Trigger>("/api/triggers", { method: "POST", body: JSON.stringify(body) }),
  fireTrigger: (id: string) => request<Trigger>(`/api/triggers/${id}/fire`, { method: "POST" }),
  cancelTrigger: (id: string) => request<Trigger>(`/api/triggers/${id}`, { method: "DELETE" }),
  files: (limit = 300) => request<FileInfo[]>(`/api/files?limit=${limit}`),
  /** Raw contents of a workspace file, fetched with the token in a header (never in a URL). */
  fileText: async (path: string): Promise<string> => {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`/api/files/${path.split("/").map(encodeURIComponent).join("/")}`, { headers });
    if (res.status === 401) throw new AuthError();
    if (!res.ok) throw new Error(res.statusText || `HTTP ${res.status}`);
    return res.text();
  },
  settings: () => request<SettingsView>("/api/settings"),
  /** Installed and latest release (a day's cache on the runtime; `refresh` asks now). */
  update: (refresh = false) => request<UpdateView>(`/api/update${refresh ? "?refresh=1" : ""}`),
  /** When the app may ask for a star (contract C1): the relay's policy, through the runtime. */
  nudges: () => request<NudgesView>("/api/nudges"),
  updateSettings: (body: Record<string, unknown>) =>
    request<SettingsView>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  // connections: secrets go into the vault on the server; only names ever come back
  connections: () => request<ConnectionsData>("/api/connections"),
  /** the own-key catalogue with what is configured and what that covers (contract C11) */
  providers: (region?: string) => request<ProvidersView>(`/api/providers${region ? `?region=${encodeURIComponent(region)}` : ""}`),
  /**
   * The ChatGPT sign-in through the runtime (the Codex OAuth): `login` starts the PKCE flow
   * and returns the page to open; `status` is polled until it is done; `logout` deletes the
   * token store. The routes follow the shared brief; the runtime's CONTRACT-chatgpt.md
   * fixes the CLI and `/api/providers` — a runtime without these routes answers 404, and
   * the card then names the CLI (`nanomuse chatgpt login`).
   */
  chatgptLogin: () => request<ChatGptLogin>("/api/chatgpt/login", json({})),
  chatgptStatus: () => request<ChatGptStatus>("/api/chatgpt/status"),
  /** The address the browser landed on, pasted by hand when the runtime could not take the callback itself. */
  chatgptCallback: (url: string) => request<{ ok: boolean }>("/api/chatgpt/callback", json({ url })),
  chatgptLogout: () => request<{ ok: boolean; was_signed_in?: boolean }>("/api/chatgpt/logout", json({})),
  setLLM: (body: Record<string, unknown>) =>
    request<ConnectionsData["llm"]>("/api/connections/llm", { method: "PUT", body: JSON.stringify(body) }),
  testLLM: () => request<TestResult>("/api/connections/llm/test", { method: "POST" }),
  /** the models an endpoint offers: its own /models when it answers, else the preset's catalogue */
  llmModels: (body: { preset?: string; base_url?: string; api_key?: string }) =>
    request<{
      models: string[];
      image_models?: string[];
      video_models?: string[];
      // nanoMuse Cloud, relay 0.10: the chat models on the menu and the other usable ones under
      // the operator's key (a member's list), likewise for pictures / clips; which chat models read pictures
      menu?: string[];
      catalog?: string[];
      image_catalog?: string[];
      video_catalog?: string[];
      vision?: string[];
      /** contract C4: the relay's hands models, recommended first; the two recommendations */
      gui?: string[];
      gui_recommended?: string;
      chat_recommended?: string;
      source: "live" | "catalogue";
      error?: string;
    }>(
      "/api/llm/models",
      json(body),
    ),
  setEmbeddings: (body: Record<string, unknown>) =>
    request<ConnectionsData["embeddings"]>("/api/connections/embeddings", { method: "PUT", body: JSON.stringify(body) }),
  testEmbeddings: () => request<TestResult>("/api/connections/embeddings/test", { method: "POST" }),
  setSearch: (body: Record<string, unknown>) =>
    request<ConnectionsData["search"]>("/api/connections/search", { method: "PUT", body: JSON.stringify(body) }),
  testSearch: () => request<TestResult>("/api/connections/search/test", { method: "POST" }),
  setEmail: (body: Record<string, unknown>) =>
    request<ConnectionsData["email"]>("/api/connections/email", { method: "PUT", body: JSON.stringify(body) }),
  disconnectEmail: () => request<ConnectionsData["email"]>("/api/connections/email", { method: "DELETE" }),
  testEmail: () => request<TestResult>("/api/connections/email/test", { method: "POST" }),
  calendar: () => request<CalendarData>("/api/calendar"),
  setCalendar: (body: Record<string, unknown>) =>
    request<ConnectionsData["calendar"]>("/api/connections/calendar", { method: "PUT", body: JSON.stringify(body) }),
  addCalendarFeed: (name: string, url: string) =>
    request<ConnectionsData["calendar"] & { error?: string }>("/api/connections/calendar/feeds", json({ name, url })),
  removeCalendarFeed: (name: string) =>
    request<ConnectionsData["calendar"]>(`/api/connections/calendar/feeds/${encodeURIComponent(name)}`, { method: "DELETE" }),
  testCalendar: () => request<TestResult>("/api/connections/calendar/test", { method: "POST" }),
  contacts: (q = "", limit = 8) =>
    request<{ count: number; people: Contact[] }>(`/api/contacts?q=${encodeURIComponent(q)}&limit=${limit}`),
  setContacts: (body: Record<string, unknown>) =>
    request<ConnectionsData["contacts"]>("/api/connections/contacts", { method: "PUT", body: JSON.stringify(body) }),
  addContactsSource: (name: string, url: string) =>
    request<ConnectionsData["contacts"] & { error?: string }>("/api/connections/contacts/sources", json({ name, url })),
  importContacts: (name: string, text: string) =>
    request<ConnectionsData["contacts"] & { error?: string }>(`/api/connections/contacts/import?name=${encodeURIComponent(name)}`, {
      method: "POST",
      headers: { "Content-Type": "text/vcard; charset=utf-8" },
      body: text,
    }),
  removeContactsSource: (name: string) =>
    request<ConnectionsData["contacts"]>(`/api/connections/contacts/sources/${encodeURIComponent(name)}`, { method: "DELETE" }),
  testContacts: () => request<TestResult>("/api/connections/contacts/test", { method: "POST" }),
  // skills
  skills: () => request<SkillsData>("/api/skills"),
  skill: (name: string) => request<SkillDetail>(`/api/skills/${encodeURIComponent(name)}`),
  saveSkill: (name: string, content: string) =>
    request<SkillDetail>(`/api/skills/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify({ content }) }),
  deleteSkill: (name: string) => request<SkillsData>(`/api/skills/${encodeURIComponent(name)}`, { method: "DELETE" }),
  setSkillEnabled: (name: string, enabled: boolean) =>
    request<SkillInfo>(`/api/skills/${encodeURIComponent(name)}/enabled`, json({ enabled })),
  importSkill: (url: string) => request<SkillDetail>("/api/skills/import", json({ url })),
  setGui: (body: Record<string, unknown>) => request<ConnectionsData["gui"]>("/api/connections/gui", { method: "PUT", body: JSON.stringify(body) }),
  testGui: () => request<TestResult & { model?: string }>("/api/connections/gui/test", { method: "POST" }),
  /** where pictures (`image`) or clips (`video`) come from: the slot as set and what it resolves to (0.1.41) */
  media: (slot: "image" | "video") => request<MediaSlotData>(`/api/connections/${slot}`),
  /** provider (a catalogue id), model, base_url, api_key; all "" clears the slot */
  setMedia: (slot: "image" | "video", body: Record<string, unknown>) =>
    request<MediaSlotData>(`/api/connections/${slot}`, { method: "PUT", body: JSON.stringify(body) }),
  setBrowser: (enabled: boolean) =>
    request<ConnectionsData["browser"]>("/api/connections/browser", { method: "PUT", body: JSON.stringify({ enabled }) }),
  addMCP: (body: Record<string, unknown>) => request<ConnectionsData>("/api/connections/mcp", json(body)),
  removeMCP: (name: string) =>
    request<{ ok: boolean }>(`/api/connections/mcp/${encodeURIComponent(name)}`, { method: "DELETE" }),
  vaultSet: (name: string, value: string) =>
    request<string[]>(`/api/vault/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify({ value }) }),
  vaultDelete: (name: string) => request<{ ok: boolean }>(`/api/vault/${encodeURIComponent(name)}`, { method: "DELETE" }),
  onboarded: (done = true) => request<{ onboarded: boolean; feed_started?: boolean }>("/api/onboarded", json({ done })),
  // ---- the first conversation (contract C4): the runtime owns the state, the browser draws it
  firstrun: (lang: string) => request<FirstRunView>(`/api/firstrun?lang=${encodeURIComponent(lang)}`),
  firstrunStart: (lang: string) => request<FirstRunView>("/api/firstrun/start", json({ lang })),
  firstrunPick: (name: string) => request<FirstRunView>("/api/firstrun/pick", json({ name })),
  firstrunDismiss: () => request<FirstRunView>("/api/firstrun/dismiss", json({})),
  // browser view
  browserControl: (thread: string, body: BrowserControl) =>
    request<{ url: string; title: string; hold?: HoldEvent | null }>(`/api/browser/${encodeURIComponent(thread)}/control`, json(body)),
  // push
  push: () => request<PushInfo>("/api/push"),
  pushSubscribe: (subscription: Record<string, unknown>) => request<PushInfo>("/api/push/subscribe", json({ subscription })),
  pushUnsubscribe: (endpoint: string) => request<PushInfo>("/api/push/unsubscribe", json({ endpoint })),
  pushTest: () => request<TestResult & { sent?: number }>("/api/push/test", { method: "POST" }),
};

/** The runtime behind this page is gone for good — the showcase gateway closes a socket with
 *  this code when the demo session has ended or was never there (no point reconnecting). */
export const WS_GONE = 4404;
/** The token is not right: a sign-in is needed, not a retry. */
export const WS_UNAUTHORIZED = 4401;

/** Which way a closed socket goes: `retry` with backoff, `auth` (ask for the token), or
 *  `gone` (stop — the runtime behind the page has ended). Pure, for the tests. */
export function closeOutcome(code: number): "retry" | "auth" | "gone" {
  if (code === WS_UNAUTHORIZED) return "auth";
  if (code === WS_GONE) return "gone";
  return "retry";
}

/** WebSocket with automatic reconnect. Returns a disposer. */
export function connectWs(handlers: {
  onMessage: (msg: WsMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onAuthError?: () => void;
  /** the runtime has ended (gateway close 4404): no more retries */
  onGone?: () => void;
}): { send: (msg: unknown) => boolean; close: () => void } {
  let ws: WebSocket | null = null;
  let closed = false;
  let attempt = 0;
  let timer: number | undefined;

  const open = () => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    // the token goes in the first frame, never in the address (which proxies log)
    ws = new WebSocket(`${proto}://${window.location.host}/ws`);
    ws.onopen = () => {
      const token = getToken();
      if (token) ws?.send(JSON.stringify({ kind: "auth", token }));
      attempt = 0;
      handlers.onOpen?.();
    };
    ws.onmessage = (ev) => {
      try {
        handlers.onMessage(JSON.parse(ev.data) as WsMessage);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = (ev) => {
      handlers.onClose?.();
      const outcome = closeOutcome(ev.code);
      if (outcome === "auth") {
        handlers.onAuthError?.();
        return;
      }
      if (outcome === "gone") {
        // the gateway says the session behind this page is over: a page that kept
        // reconnecting every few seconds for hours was what the production logs showed
        closed = true;
        handlers.onGone?.();
        return;
      }
      if (closed) return;
      const delay = Math.min(15000, 500 * 2 ** attempt++);
      timer = window.setTimeout(open, delay);
    };
    ws.onerror = () => ws?.close();
  };
  open();

  return {
    send: (msg) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg));
        return true;
      }
      return false;
    },
    close: () => {
      closed = true;
      if (timer) window.clearTimeout(timer);
      ws?.close();
    },
  };
}
