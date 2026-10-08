export type RiskLevel = "safe" | "moderate" | "sensitive";

interface BaseEvent {
  id: string;
  ts: string;
  thread: string;
  updated_ts?: string;
  /** "user" for things you said; "goal" / "background" for work your nanoMuse did on its own. */
  source?: string;
  /** For background events: the short label of the work being done. */
  about?: string;
  /** The device a message came from; "call": said on a voice call in 0.1.20–0.1.21. */
  via?: "call" | string;
  /** on the relay (contract C7): pushed from here, or pulled from another device of the account */
  synced?: boolean;
  mid?: string;
}

/** A file attached to a message: in the workspace under attachments/. */
export interface AttachmentInfo {
  path: string;
  name: string;
  size: number;
  kind: "image" | "pdf" | "data" | "text" | "other";
  mime: string;
}

export interface UserEvent extends BaseEvent {
  type: "user";
  text: string;
  files?: AttachmentInfo[];
  /** the name of the device this was asked from, when another device opened this chat over the hub */
  via?: string;
  /** `@<device>` in front of the message: the device the turn was handed to (contract C7 rule 8) */
  to_device?: string;
  to_device_name?: string;
  /** a synced message written on another device of the account */
  via_device?: string;
  via_device_name?: string;
}

export interface AssistantEvent extends BaseEvent {
  type: "assistant";
  text: string;
  reasoning?: string;
  /** A background pass that found nothing worth interrupting you for. */
  quiet?: boolean;
  /** the device whose Muse said this (a chat addressed to a device) */
  device?: string;
  /** a synced reply written on another device of the account */
  via_device?: string;
  via_device_name?: string;
}

export interface ToolEvent extends BaseEvent {
  type: "tool";
  tool: string;
  summary: string;
  /** the model's own words for the step ("打开携程网站"), when it gave them (0.1.33) */
  title?: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error" | "blocked";
  output?: string;
  /** the device the step ran on, when it was not this one */
  device?: string;
}

export interface ApprovalEvent extends BaseEvent {
  type: "approval";
  tool: string;
  summary: string;
  risk: RiskLevel;
  reasons: string[];
  warnings: string[];
  egress_target?: string | null;
  /** What the user asked for — why this action is happening. */
  purpose?: string;
  /** What a standing permission would be bound to (host, recipient, program). */
  target?: string | null;
  grant_key?: string;
  /** Scopes the Sentinel offers for this call, in display order. */
  grant_options?: GrantScope[];
  args: Record<string, unknown>;
  status: "pending" | "approved" | "denied" | "expired";
  scope?: string | null;
  /** raised by another device's Muse (a chat addressed to it); answered here, carried back over the hub */
  remote?: { device: string; name: string; approval_id: string };
}

export type GrantScope = "once" | "conversation" | "session" | "24h" | "always";

export interface Grant {
  key: string;
  tool: string;
  target: string | null;
  scope: GrantScope;
  granted_at: string;
  expires_at: string | null;
  task_id?: string | null;
}

export interface QuestionEvent extends BaseEvent {
  type: "question";
  text: string;
  status: "pending" | "answered" | "expired";
  answer?: string;
}

export interface NoticeEvent extends BaseEvent {
  type: "notice";
  level: "info" | "warn" | "error";
  /** an English sentence; the runtime's failure sentences are keys in the dictionary */
  text: string;
  /** a short reason for a failed run: allowance, key, network, timeout, too_long … */
  code?: string;
  /** the raw exception, for bug reports */
  detail?: string;
  /** values for the {placeholders} in `text` */
  vars?: Record<string, string | number>;
  source?: string;
  /** code "allowance": what the relay said — what is left, the pool, and the three ways on */
  allowance?: {
    left?: number | null;
    grant?: number;
    invite_url?: string;
    invite_bonus_cny?: number;
    invitee_bonus_cny?: number;
    own_key_docs?: string;
    /** relay 0.21: the region's providers and what each covers */
    guidance?: Guidance;
  };
}

export interface ArtifactEvent extends BaseEvent {
  type: "artifact";
  path: string;
  name: string;
  action: string;
}

/** The phone that is connected for GUI operation (the Android app or the MobileGym module). */
export interface PhoneStatus {
  connected: boolean;
  device: {
    id: string;
    name: string;
    platform: string;
    /** whether the phone can be operated through its screen (the accessibility service is on) */
    gui: boolean;
    /** whether the phone shows the step capsule with a Stop button while it is operated */
    capsule?: boolean;
    apps: number;
    width: number;
    height: number;
  } | null;
  last_screen: { app: string; app_name: string; route: string; elements: number; image: string | null; taken_at: number } | null;
}

/** The browser as the agent sees it: one card per run, updated frame after frame. */
export interface BrowserEvent extends BaseEvent {
  type: "browser";
  url: string;
  title: string;
  /** caption of the last action: "Opened example.com", "Clicked 'Sign in'", "You typed" */
  action: string;
  /** id of the latest frame; fetch with frameUrl() — frames live in memory on the server */
  frame: string;
  frames: number;
  status: "live" | "done";
  by_user?: boolean;
  updated_ts?: string;
  /** which browser drew the frame: the phone's own WebView ("device") or Playwright on the server */
  backend?: "device" | "playwright" | string;
  /** frame size in CSS pixels — taps are mapped onto this */
  width?: number;
  height?: number;
}

/** The hands on this computer: one card per task on its screen, updated step by step. */
export interface HandsEvent extends BaseEvent {
  type: "hands";
  /** the goal of the task ("" for a single computer_act) */
  text: string;
  status: "live" | "done" | "stopped";
  steps: number;
  /** the last action: what, the words under the cursor, where (fractions of the screen) */
  last?: { action?: string; label?: string; fx?: number; fy?: number; fx2?: number; fy2?: number; text?: string; keys?: string[] };
  /** the window in front when the last action ran */
  app?: string;
  title?: string;
  /** what the operator wanted the person to know when it stopped to ask */
  notice?: string;
}

/**
 * A hold (contract C1): the person has the browser, this computer's screen or the phone for
 * a while — they took it over, or the agent asked them to (a sign-in, a code). The agent's
 * actions of that kind wait until Done takes the hold off. `ts` arrives as seconds since the
 * epoch and is made ISO by the store like every other event's.
 */
export interface HoldEvent extends BaseEvent {
  type: "hold";
  tool: "browser" | "computer" | "phone" | string;
  status: "on" | "off";
  by: "user" | "agent" | string;
  reason: string;
  done_ts?: number;
  /** the agent waited ten minutes and went on without the person */
  timed_out?: boolean;
  /** found "on" after a restart: nothing waits on it any more */
  stale?: boolean;
}

/** The avatar studio's card: a new face from a description, drawn in the chat (nanomuse/avatar). */
export interface AvatarEvent extends BaseEvent {
  type: "avatar";
  session: string;
  /** estimate (waiting for the tap) · drawing · choose (four wait) · posing · animating (the face is on, clips coming) · done · cancelled · failed */
  stage: "estimate" | "drawing" | "choose" | "posing" | "animating" | "done" | "cancelled" | "failed" | string;
  description: string;
  /** workspace path of a picture attached to the request: the candidates are drawn from it */
  reference?: string;
  /** what it costs: the relay's figure when the account draws; the counts alone with one's own key */
  cost?: { pictures?: number; clips?: number; model?: string; clip_model?: string; cloud?: boolean; cny?: number | null; left_cny?: number | null; unlimited?: boolean; affordable?: boolean; error?: string };
  /** workspace paths of the four candidates (null while one is still being drawn) */
  candidates?: Array<string | null>;
  errors?: string[];
  chosen?: number | null;
  /** the face id once one was picked; the profile's avatar when done */
  face?: string | null;
  /** mood → workspace path, filled as the poses land */
  moods?: Record<string, string>;
  /** mood → workspace path of the clip, filled as they land (idle · working · waiting · happy) */
  clips?: Record<string, string>;
  message?: string;
}

/** The avatar studio's session as `GET /api/avatar` and the "studio" messages carry it. */
export type StudioSession = Omit<AvatarEvent, keyof BaseEvent | "type">;

/** The face the profile wears when the studio drew it (`avatar/<face>/face.json`). */
export interface StudioFace {
  id: string;
  description: string | null;
  style: string | null;
  model: string | null;
  created: number | null;
}

export interface StudioView {
  available: boolean;
  image_model: string;
  video_model: string;
  cloud: boolean;
  host: string;
  current: StudioSession | null;
  face: StudioFace | null;
}

export type TimelineEvent =
  | UserEvent
  | AssistantEvent
  | ToolEvent
  | ApprovalEvent
  | QuestionEvent
  | NoticeEvent
  | ArtifactEvent
  | BrowserEvent
  | HandsEvent
  | HoldEvent
  | AvatarEvent;

export interface ThreadMeta {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  busy: boolean;
  queued: number;
  events: number;
  /** a chat addressed to another device of the account: what is typed here runs there */
  device?: string;
  device_name?: string;
  /** a chat another device opened here with a task over the hub */
  remote_from?: { device: string; name: string; kind: string; conversation: string };
  /** a synced chat that was started on another device of the account ("From Pixel 8") */
  origin_device?: string;
  origin_device_name?: string;
}

/** GET /api/sync/state: conversations synced between the account's devices (contract C7). */
export interface SyncState {
  /** the switch on this device */
  enabled: boolean;
  /** C9: this device's side chats too (per device, default off); off = the main chat only */
  side_chats?: boolean;
  /** C9: the other devices' turns under way on synced chats */
  working?: WorkingPresence[];
  /** signed in to nanoMuse Cloud, so syncing can happen at all */
  available: boolean;
  /** the relay refused the key: nothing moves until the next sign-in */
  paused: boolean;
  cursor: number;
  last_pull_at: string | null;
  last_push_at: string | null;
  error: string;
  /** the relay's own view; null when it could not be asked */
  relay: { enabled: boolean; cursor: number; counts: { conversations: number; messages: number }; limits: { messages: number; text_bytes: number } } | null;
}

/**
 * Another device of the account is working on a synced chat (contract C9): the hub's
 * `working` frame as the runtime keeps it. `at` is Unix seconds; a line older than ten
 * minutes is stale and not shown.
 */
export interface WorkingPresence {
  thread: string;
  cid: string;
  device: string;
  device_name: string;
  at: number;
}

/** A device of the account on the hub (docs/hub.md). */
export interface HubDevice {
  id: string;
  name: string;
  kind: "phone" | "computer" | "web" | string;
  os?: string;
  version?: string;
  online: boolean;
  actions?: string[];
  last_seen?: string;
  /** this very device */
  this?: boolean;
}

export interface CloudAccount {
  base_url: string;
  signed_in: boolean;
  /** the masked identifier: "1**********11", "s***@example.com" */
  hint: string;
  channel: "sms" | "email" | string;
  signed_in_at?: string | null;
  /** the relay is the model provider right now */
  is_model: boolean;
  /** this runtime insists on an account (self-hosters may turn it off) */
  required?: boolean;
  /** the account's models as a source (*Use nanoMuse Cloud models*); false leaves them out of the automatic order and the listings */
  models?: boolean;
  has_password?: boolean;
  /** on the operator's list: no spend limit */
  member?: boolean;
  /** may name any model of the provider's for its kind (chat, picture, clip), not only the menu's */
  any_model?: boolean;
  /** on the answer to a code sign-in: the account was created by it (first sign-in ever) */
  created?: boolean;
  /** the opaque account id, never the identifier */
  account_id?: string;
  /** where the relay places the account ("cn" = mainland China); older relays do not say */
  region?: string;
}

/** One sign-in of the account (a key), as the relay lists them. */
export interface CloudSession {
  prefix: string;
  device: string;
  via: "code" | "password" | string;
  created_at: number;
  last_used_at: number | null;
  current: boolean;
}

/** A line of the account's own timeline: sign-ins, calls, refusals — never message content. */
export interface CloudEvent {
  ts: number;
  kind: string;
  detail: string;
}

/** Requests, tokens and money for one kind (or one model) of use. */
export interface UsageRow {
  kind: "chat" | "image" | "video" | "realtime" | string;
  model?: string;
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  charged: number;
  cost_cny: number;
}

/** GET /v1/config on the relay (0.15): what a client prints before anyone signs in. */
export interface CloudConfig {
  version?: string;
  signup_open?: boolean;
  allowance_cny?: number;
  allowance_usd?: number;
  invite_bonus_cny?: number;
  invitee_bonus_cny?: number;
  usd_cny?: number;
  invite_url?: string;
  own_key_docs?: string;
  privacy_url?: string;
  repo_url?: string;
  improve_default?: boolean;
}

/** `/api/cloud/me`: the account as the relay sees it. */
export interface CloudMe {
  account: {
    id: string;
    channel: string;
    hint: string;
    created_at: number;
    member: boolean;
    any_model?: boolean;
    has_password: boolean;
    password_set_at: number | null;
    sessions: number;
    signed_in_via: string;
    /** "cn" for a mainland account; older relays do not say */
    region?: string;
  };
  usage: {
    today: { by_kind: UsageRow[] };
    total: { by_kind: UsageRow[]; by_model: UsageRow[] };
    kinds: string[];
  };
  tokens: { unlimited: boolean; granted: number; used: number; remaining: number; used_today: number; daily_cap: number };
  /**
   * Relay 0.5: one pool for the account's lifetime — `total` spent against `grant`, `left`
   * (null = no limit), `warn` from 80 %. `usd_cny` converts for display. The 0.4 names
   * (`today`, `daily_cap`, …) are still sent for one version.
   */
  spend: {
    currency: string;
    today: number;
    total: number;
    grant?: number;
    left?: number | null;
    unlimited: boolean;
    warn?: boolean;
    usd_cny?: number;
    allowance_cny?: number;
    invite_bonus_cny?: number;
    /** relay 0.9: the friend who signs up with the code gets the same */
    invitee_bonus_cny?: number;
    own_key_docs?: string;
    /** relay 0.21 (contract C11): the whole own-key card for this person's region */
    guidance?: Guidance;
    daily_cap: number;
    credit_left?: number;
    left_today?: number | null;
  };
  /** relay 0.17: where the relay places the person */
  region?: "cn" | "intl" | "unknown" | string;
  /** Relay 0.4/0.5: the account's invite code and what came of it (`earned_cny` since 0.5). */
  invite?: { code: string; url: string; invites: number; bonus_cny: number; invitee_bonus_cny?: number; earned_cny?: number; friends: Array<{ hint: string; joined_at: number }> };
  /**
   * Data controls: whether "Help improve nanoMuse's AI models" is on for this account, how many
   * turns the relay keeps, what the relay's default for new accounts is (0.9), what a kept turn
   * holds and where its privacy policy is.
   */
  contribute?: { on: boolean; samples: number; default_on?: boolean; keeps?: { kept: string[]; not_kept: string[] }; privacy_url?: string };
  /** Relay 0.4 counted clips; 0.5 no longer does (always unlimited here). */
  clips?: { unlimited: boolean; allowed: number | null; used: number; left: number | null; per_face: number };
  models?: Array<{ id: string; name?: string; nanomuse?: { kind?: string; recommended?: boolean } }>;
}

// ------------------------------------------------------------------ own-key providers (C11)

export type Capability = "chat" | "vision" | "image" | "video";

/** One entry of `nanomuse/llm/providers.json`, the own-key catalogue every client reads. */
export interface CatalogueProvider {
  id: string;
  name: string;
  name_zh: string;
  protocol: "openai" | "openai-responses" | "anthropic" | "gemini" | string;
  base_url: string;
  base_url_global?: string;
  key_url: string;
  key_url_global?: string;
  key_hint?: string;
  auth: string[];
  /** a sign-in that gives less than the key does (the ChatGPT one: chat and vision) */
  auth_capabilities?: Record<string, Capability[]>;
  regions: Array<"cn" | "global">;
  capabilities: Capability[];
  defaults: Partial<Record<"chat" | "hands" | "image" | "video", string>>;
  /** "custom": the person says what the endpoint can do */
  user_capabilities?: boolean;
  note: string;
  note_zh: string;
  verified: string;
  /** from the runtime: the slots using this provider today */
  configured?: string[];
  /** from the runtime: the ChatGPT store holds tokens (on `openai`) */
  signed_in?: boolean;
}

/** `GET /api/providers` on the runtime (team Runtime's CONTRACT-chatgpt.md, §3). */
export interface ProvidersView {
  providers: CatalogueProvider[];
  region: "cn" | "global" | "";
  configured: Partial<Record<"chat" | "hands" | "image" | "video", { provider: string; model: string; protocol?: string; source?: string } | null>>;
  capabilities: Capability[];
  unavailable: Partial<Record<Capability, string>>;
  chatgpt?: { signed_in: boolean; label?: string; capabilities?: Capability[] };
}

/** The relay's own-key guidance (relay 0.21, `spend.guidance` and the refusal's). */
export interface Guidance {
  version?: number;
  region: "cn" | "intl" | "unknown" | string;
  docs: string;
  providers: Array<{
    id: string;
    name: string;
    name_zh: string;
    protocol?: string;
    base_url?: string;
    key_url: string;
    auth: string[];
    regions?: string[];
    covers: Capability[];
    defaults?: Record<string, string>;
    one_key?: boolean;
    note?: string;
    note_zh?: string;
  }>;
  plans: Array<{ id: string; provider: string; name: string; auth: string; clients: string[]; covers: Capability[] }>;
  local?: Array<{ id: string; name: string; name_zh: string }>;
  caveats?: { chatgpt?: string; chatgpt_zh?: string };
}

/** `POST /api/chatgpt/login`: the page to open; the runtime waits for the callback. */
export interface ChatGptLogin {
  url: string;
  callback?: string;
  expires_in?: number;
  /** false when the runtime could not listen on port 1455: the callback address has to be pasted (`POST /api/chatgpt/callback`) */
  port_bound?: boolean;
}

/** `GET /api/chatgpt/status`: the token store, never the tokens. */
export interface ChatGptStatus {
  signed_in: boolean;
  label?: string;
  plan?: string;
  account_id?: string;
  expires_at?: number;
  expires_in?: number;
  /** a sign-in started and not finished yet */
  pending?: boolean;
  /** the page of a pending sign-in, for a second tab */
  url?: string;
  /** while pending: whether the runtime listens for the callback itself */
  port_bound?: boolean;
  /** while pending: seconds until the login is given up */
  login_expires_in?: number;
  error?: string;
  /** `cancelled`, `timeout`, `state_mismatch`, `exchange_failed`, … */
  error_code?: string;
  models?: string[];
}

/** A coding agent on a computer: Cursor, Codex, Claude Code. */
export interface CodingAgent {
  id: "cursor" | "codex" | "claude" | string;
  name: string;
  installed: boolean;
  cli: string | null;
  version: string;
  sessions_root: string;
  running: number;
}

export interface CodingMessage {
  role: "user" | "assistant" | string;
  text: string;
  ts?: number;
}

/** One chat of a coding agent, as read from its store on disk. */
export interface CodingSession {
  agent: string;
  id: string;
  title: string;
  workspace: string;
  path: string;
  created_at: number;
  updated_at: number;
  messages: number;
  status: "idle" | "active" | "running" | string;
  last_user: string;
  last_assistant: string;
  source: string;
  resumable: boolean;
  transcript?: CodingMessage[];
  runs?: CodingRun[];
}

/** A message sent into a coding agent through nanoMuse, and how it went. */
export interface CodingRun {
  id: string;
  agent: string;
  session_id: string;
  asked_session_id?: string;
  workspace: string;
  text: string;
  started_at: number;
  ended_at: number | null;
  status: "running" | "done" | "failed" | "stopped" | string;
  output: string;
  resumed: boolean;
  error: string;
  tools: number;
  /** set when the run is on another computer */
  device?: string;
}

export interface CodingEvent {
  kind: "started" | "text" | "tool" | "done" | "error" | "run" | string;
  text?: string;
  partial?: boolean;
  run?: string;
  session_id?: string;
  model?: string;
}

/** This device on the hub, and the other devices of the account. */
export interface HubView {
  enabled: boolean;
  remote_control: boolean;
  state: "connected" | "connecting" | "disconnected" | "refused" | "stopped" | "signed_out" | "off" | string;
  detail: string;
  device: { id: string; name: string; kind: string; actions: string[] };
  devices: HubDevice[];
  account: CloudAccount;
}

/** This computer's own screen and hands. */
export interface HandsStatus {
  enabled: boolean;
  available: boolean;
  backend?: string | null;
  reason?: string;
  /** where the hands work: the whole screen, one app's window (macOS), or auto */
  mode?: "auto" | "screen" | "window" | string;
  /** window mode: whether it can run here and what it is working in */
  window?: {
    available: boolean;
    reason?: string;
    active: boolean;
    app?: string;
    title?: string;
    frame?: { id: number; pid: number; app: string; bundle_id: string; title: string; bounds: number[] } | null;
  };
  device?: { id: string; name: string; platform: string; width: number; height: number };
  task_active?: boolean;
  task_text?: string;
  last_screen?: { app: string; app_name: string; route: string; elements: number; image: string | null; taken_at: number } | null;
}

/** A live step of the hands, for the stage overlay (not persisted). */
export interface HandsLive {
  event: "begin" | "act" | "end" | "stop" | "notice" | string;
  thread: string;
  text?: string;
  action?: string;
  label?: string;
  fx?: number;
  fy?: number;
  fx2?: number;
  fy2?: number;
  /** the point in screen pixels (for a cursor sprite); window mode maps the model's window pixels here */
  x?: number;
  y?: number;
  x2?: number;
  y2?: number;
  mode?: "screen" | "window" | string;
  window?: { id: number; pid: number; app: string; bundle_id: string; title: string; bounds: number[] };
  app?: string;
  title?: string;
  ts: number;
}

export interface Status {
  state: "idle" | "working" | "waiting";
  detail: string;
  thread: string;
  ts?: string;
}

export interface Profile {
  name: string;
  /** "dragon", the id of a face drawn in the avatar studio (see avatars.ts), or "" for the emoji on a colour. */
  avatar: string;
  emoji: string;
  color: string;
  /** one line under the name */
  tagline: string;
  /** how it talks: "" | formal | casual | playful | concise */
  tone: string;
  /** how much and in what shape: "" | short | detailed | bullets */
  communication: string;
  /** free text about its personality, in the user's words */
  style: string;
  /** What you want to be called. */
  user_name: string;
  /** How eagerly background work runs and reaches out. */
  proactivity: Proactivity;
  /** `proactivity !== "off"`, kept for older clients. */
  proactive: boolean;
  goal_interval_minutes: number;
  /** "22:00-08:00" in the server's local time, or "" for none. */
  quiet_hours: string;
}

export type Proactivity = "off" | "low" | "default" | "high";

export interface GoalStep {
  idx: number;
  title: string;
  status: "pending" | "in_progress" | "done" | "blocked" | "skipped";
  note: string;
  updated_at: string;
}

export type GoalCategory =
  | ""
  | "health"
  | "finance"
  | "career"
  | "learning"
  | "relationships"
  | "family"
  | "home"
  | "travel"
  | "creative"
  | "other";

/** A plan change the agent suggested; the user accepts or dismisses it. */
export interface GoalProposal {
  reason: string;
  steps: string[];
  created_at: string;
}

export interface Goal {
  id: string;
  title: string;
  description: string;
  status: "active" | "paused" | "done" | "cancelled";
  notes: string;
  category: GoalCategory;
  /** Target date, YYYY-MM-DD, or "". */
  due: string;
  overdue: boolean;
  /** Reminder cadence such as "daily 08:00" or "weekly mon 09:00", or "". */
  check_in: string;
  next_check_in: string | null;
  proposal: GoalProposal | null;
  created_at: string;
  updated_at: string;
  progress: { done: number; total: number };
  next_step: string | null;
  steps: GoalStep[];
}

export interface MemoryItem {
  id: string;
  content: string;
  category: string;
  created_at: string;
  source: string;
  /** set when the line was rewritten or is the result of a merge */
  updated_at?: string;
}

/** One entry of the memory log: a tidy-up merge or drop, or an update the agent made. Undoable. */
export interface MemoryChange {
  id: string;
  at: string;
  action: "merge" | "rewrite" | "drop";
  before: MemoryItem[];
  after: MemoryItem | null;
  reason: string;
  restored: boolean;
}

export interface TidyReport {
  considered: number;
  changed: number;
  merged: MemoryChange[];
  dropped: MemoryChange[];
  skipped: string[];
  planned: { op: string; before: string[]; content?: string; reason?: string }[];
  lines: string[];
}

export interface Idea {
  title: string;
  detail: string;
  prompt: string;
  /** planning | goals | research | money | health | home | learning | people | files | fun */
  area?: string;
  /** what tapping it does: chat (a message in the main chat, the default) · routine (a daily
   *  repeating reminder with the prompt) · goal (a goal conversation in the chat) */
  kind?: "chat" | "routine" | "goal" | string;
  /** routines: the time of day, "HH:MM" */
  time?: string;
  /** goals: the category key (health, finance, … other) */
  category?: string;
}

export interface FeedPost {
  id: string;
  ts: string;
  title: string;
  /** Markdown, a short read. */
  body: string;
  area: string;
  /** A follow-up the user could send, or "". */
  prompt: string;
}

export interface FeedPostsData {
  instructions: string;
  generated_at: string | null;
  posts: FeedPost[];
  /** The daily routine (contract C5): on by default, at `time` (`HH:MM`, local; 08:00). */
  daily: boolean;
  time: string;
  error?: string;
}

export interface IdeasData {
  generated_at: string | null;
  source: string;
  ideas: Idea[];
  error?: string;
}

export interface ToolInfo {
  name: string;
  risk: RiskLevel;
  description: string;
}

/** `GET /api/update`: the installed and the latest release (contract C2). */
export interface UpdateView {
  current: string;
  enabled: boolean;
  latest: string | null;
  newer: boolean;
  /** The release page of the latest. */
  url: string;
  /** The download page (nanomuse.cn/dl). */
  download_url?: string;
  /** When the runtime last asked (ISO, UTC), or null before the first check. */
  checked_at?: string | null;
  /** Where the answer came from: `nanomuse.cn`, `github`, or null. */
  source?: string | null;
  error?: string | null;
}

/** `GET /api/nudges`: the star-ask policy (contract C1) as the runtime holds it. */
export interface NudgesView {
  policy: unknown;
  fetched_at: number | null;
  source: "default" | "relay" | "me" | string;
  stale: boolean;
  error: string | null;
}

export interface SettingsView {
  version: string;
  profile: Profile;
  sentinel: {
    mode: "ask" | "strict" | "auto";
    always_ask_tools: string[];
    always_allow_tools: string[];
    deny_tools: string[];
    taint_tracking: boolean;
    egress_allowlist: string[];
  };
  /** Each shell / python call in its own bubblewrap namespace (Linux); status says why not. */
  sandbox: { mode: "auto" | "bwrap" | "off"; active: boolean; status: string };
  llm: { provider: string; model: string; stream: boolean; cloud?: boolean };
  agent: { language: string; max_steps: number; show_thinking: boolean; workspace: string };
  connectors: { email: boolean; calendar: boolean; contacts: boolean; browser: boolean; gui: boolean; mcp: string[] };
  phone: PhoneStatus & { gui_enabled: boolean };
  tools: ToolInfo[];
  memory_enabled: boolean;
  /** Skills: recipes for jobs (SKILL.md folders); count = the ones switched on. */
  skills: { enabled: boolean; count: number; yours: number };
  data_dir: string;
  started_at: string;
  /** First-run setup finished (or skipped) in the app. */
  onboarded: boolean;
  /** A model is configured with a key (or a local endpoint that needs none). */
  llm_ready: boolean;
}

// ----------------------------------------------------------------------------- skills
/** A skill: how a job is done, written down as a SKILL.md folder. */
export interface SkillInfo {
  name: string;
  description: string;
  /** "built-in" ships with the app; "yours" lives in <data_dir>/skills (and replaces a built-in of the same name). */
  source: "built-in" | "yours";
  enabled: boolean;
  path: string;
  /** scripts/, references/, assets/ that come with it. */
  files: string[];
  allowed_tools: string[];
  metadata: Record<string, string>;
  updated_at: string | null;
}

export interface SkillDetail extends SkillInfo {
  /** The instructions (Markdown after the front matter). */
  body: string;
  /** The whole SKILL.md, for editing. */
  content: string;
}

export interface SkillsData {
  count: number;
  built_in: number;
  yours: number;
  dir: string;
  errors: Record<string, string>;
  skills: SkillInfo[];
}

// ----------------------------------------------------------------------------- connections
export interface ProviderPreset {
  label: string;
  /** who is behind it, or what protocol: "Moonshot AI · 月之暗面", "Responses API" */
  subtitle?: string;
  /** how the form groups them: "cloud" (the account), "openai" (Chat Completions), "responses", "local" */
  group?: "cloud" | "openai" | "responses" | "local" | string;
  provider: "openai" | "openai_responses" | string;
  base_url: string;
  /** the fallback catalogue; the live list comes from /api/llm/models */
  models?: string[];
  no_key?: boolean;
  /** the nanoMuse Cloud account as the provider: the account key is the key, saved through /api/cloud/use-as-model */
  cloud?: boolean;
  /** a key may be left empty (a gateway or local server without one) */
  key_optional?: boolean;
  /** where a key comes from */
  key_url?: string;
  /** what a key looks like there, as the field's placeholder */
  key_hint?: string;
  /** the hands model the preset suggests beside its chat model (contract C4): one that sees */
  gui_model?: string;
  /** the account's hands models, recommended first (the nanoMuse Cloud preset) */
  gui_models?: string[];
  /** "cn": the vendor only signs up accounts from mainland China (contract C5) */
  region?: string;
}

/** One of the `image` / `video` slots: as set, and what it resolves to today. */
export interface MediaSlotData {
  /** a catalogue id, or `openai` / `openai_responses` with a `base_url`; "" when not set */
  provider: string;
  /** the catalogue entry that means, by id or by the URL's host; "" when unlisted or not set */
  provider_id: string;
  /** "" = the catalogue's default for the provider */
  model: string;
  base_url: string;
  key_source: "none" | "vault" | "config" | "missing";
  /** something is set here (an explicit choice) */
  configured: boolean;
  from_app: boolean;
  /** what the slot resolves to: a catalogue id, `nanomuse_cloud`, `custom`; "" when nothing draws */
  effective_provider: string;
  effective_model: string;
  /** `app` / `config` for a choice, `chat` for the chat provider's own model, `cloud` for the relay, "" for none */
  effective_source: "app" | "config" | "chat" | "cloud" | "";
}

export interface ConnectionsData {
  llm: {
    provider: string;
    model: string;
    base_url: string;
    tool_mode: string;
    stream: boolean;
    /** vault = key entered in the app; config = from config.toml / env; missing = referenced but not set. */
    key_source: "vault" | "config" | "missing" | "none";
    from_app: boolean;
    /** the model is the nanoMuse Cloud account's */
    cloud?: boolean;
    /** the avatar studio's picture model at the same host; "" = the runtime's pick */
    image_model?: string;
    /** the clip model at the same host; "" = the runtime's pick */
    video_model?: string;
    /** `[llm] proxy` for this slot's requests; credentials masked; "" = none (older runtimes: absent) */
    proxy?: string;
  };
  providers: Record<string, ProviderPreset>;
  /** Recall by meaning: memories embedded through an OpenAI-compatible /embeddings endpoint. */
  embeddings: {
    mode: "auto" | "on" | "off";
    /** "" → default_model */
    model: string;
    default_model: string;
    /** "" → the model's endpoint */
    base_url: string;
    effective_base_url: string;
    /** model = the model's own key on its endpoint; vault/config/missing = a key of its own */
    key_source: "model" | "vault" | "config" | "missing";
    from_app: boolean;
    memory_enabled: boolean;
    /** null until the first call of this run */
    available: boolean | null;
    reason: string;
    dims: number;
    indexed: number;
    total: number;
    status: string;
  };
  search: {
    provider: "duckduckgo" | "brave" | "tavily" | "searxng";
    /** SearXNG instance */
    base_url: string;
    key_source: "none" | "vault" | "config" | "missing";
    /** what the provider needs is there (a key, or an instance URL) */
    configured: boolean;
    from_app: boolean;
    providers: Array<{ id: string; label: string; needs_key: boolean; keys_url: string }>;
  };
  email: {
    enabled: boolean;
    configured: boolean;
    address: string;
    imap_host: string;
    imap_port: number;
    smtp_host: string;
    smtp_port: number;
    smtp_starttls: boolean;
    password_set: boolean;
  };
  browser: { enabled: boolean; available: boolean };
  /** Operating the phone through its screen (the GUI agent) and the operator's model. */
  gui: {
    enabled: boolean;
    /** a protocol (`openai` / `openai_responses`) or a catalogue id, as for the chat model */
    provider: string;
    /** the catalogue entry `provider` means, by id or by the URL's host; "" when unlisted (0.1.41) */
    provider_id?: string;
    model: string;
    /** the model the hands use right now: `model`, else the default below */
    effective_model?: string;
    /** where that comes from: `gui` (set here), `chat` (the chat provider's hands model), `cloud` (the relay's) */
    effective_source?: "gui" | "chat" | "cloud";
    /** what the hands use when `model` is empty: the relay's hands model with the account, the chat model otherwise */
    default_model?: string;
    /** the chat model is the account (the relay) */
    cloud?: boolean;
    base_url: string;
    key_source: "none" | "vault" | "config" | "missing";
    max_steps: number;
    phone: PhoneStatus;
  };
  /** Where pictures come from (`[image]`); absent on a runtime before 0.1.41. */
  image?: MediaSlotData;
  /** Where clips come from (`[video]`); absent on a runtime before 0.1.41. */
  video?: MediaSlotData;
  calendar: {
    enabled: boolean;
    configured: boolean;
    refresh_minutes: number;
    /** Working hours, "HH:MM", for "when am I free". */
    day_start: string;
    day_end: string;
    feeds: CalendarFeed[];
  };
  contacts: {
    enabled: boolean;
    /** Anyone to look up: a source, or people the agent was told about. */
    configured: boolean;
    count: number;
    /** People in the agent's own book ("My contacts"). */
    own: number;
    sources: ContactSource[];
  };
  mcp: Array<{
    name: string;
    command: string | null;
    args: string[];
    url: string | null;
    risk: string;
    tools: number;
    connected: boolean;
    from_app: boolean;
    /** the phone's own capabilities (local build): always there, cannot be removed */
    builtin?: boolean;
  }>;
  /**
   * Connections the account's other devices hold (contract C3): a name, an address and how
   * it signs in — never a key. ``here`` when a server of that name is connected on this one.
   * Older runtimes leave it out.
   */
  shared?: SharedConnector[];
  vault: string[];
  onboarded: boolean;
}

/** One connection another device of the account reports. */
export interface SharedConnector {
  id: string;
  label: string;
  url: string;
  auth: "oauth" | "key" | "open" | string;
  /** the device's human label and the hub id behind it */
  device: string;
  device_id: string;
  enabled: boolean;
  /** ISO-8601 */
  at: string;
  here: boolean;
}

/** One connected calendar: a private .ics link (kept in the vault) or a file. */
export interface CalendarFeed {
  name: string;
  from_app: boolean;
  events: number;
  fetched_at: string | null;
  error: string;
}

/** One connected address book: a .vcf file (uploaded or on disk) or a link kept in the vault. */
export interface ContactSource {
  name: string;
  from_app: boolean;
  file: boolean;
  contacts: number;
  fetched_at: string | null;
  error: string;
}

/** One person, as GET /api/contacts returns them. */
export interface Contact {
  id: string;
  name: string;
  first: string;
  last: string;
  nickname: string;
  /** "alice@example.com" or "alice@example.com (work)". */
  emails: string[];
  phones: string[];
  org: string;
  title: string;
  birthday: string;
  addresses: string[];
  urls: string[];
  note: string;
  source: string;
}

export interface CalendarEvent {
  uid: string;
  summary: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string;
  description: string;
  calendar: string;
}

/** GET /api/calendar: today's and tomorrow's events with the feeds' status. */
export interface CalendarData {
  enabled: boolean;
  configured: boolean;
  today: string;
  events: CalendarEvent[];
  feeds: Array<{ name: string; events: number; fetched_at: string | null; error: string }>;
  fetched_at: string | null;
  stale: boolean;
}

export interface TestResult {
  ok: boolean;
  /** what went wrong, as the sentence a chat turn would show (a dictionary key) */
  error?: string;
  /** a model test: the error's own words, one tap away for bug reports */
  detail?: string;
  code?: string;
  reply?: string;
  ms?: number;
  inbox?: number | null;
  /** calendar test: events across the feeds */
  events?: number;
  feeds?: number;
  /** contacts test: people across the sources */
  contacts?: number;
  sources?: number;
  /** embeddings test */
  model?: string;
  dims?: number;
  indexed?: number;
  /** search test */
  provider?: string;
  results?: number;
  first?: string;
}

export interface StateSnapshot {
  version: string;
  profile: Profile;
  status: Status;
  threads: ThreadMeta[];
  pending_approvals: ApprovalEvent[];
  goals: Goal[];
  settings: SettingsView;
  hub?: HubView;
  hands?: HandsStatus;
  /** the holds that are on (contract C1), as `hold` events */
  holds?: HoldEvent[];
  /** the other devices' turns under way on synced chats (contract C9) */
  working?: WorkingPresence[];
  /** the first conversation (contract C4); absent on an older runtime */
  firstrun?: FirstRunView;
}

/** The first conversation's phases: `none → ask_user_name → ask_agent_name → named → done`. */
export type FirstRunPhase = "none" | "ask_user_name" | "ask_agent_name" | "named" | "done";

/** `GET /api/firstrun` and the `firstrun` frame: where the first conversation stands (contract C4). */
export interface FirstRunView {
  phase: FirstRunPhase;
  /** the thread it is bound to; null until Start */
  session_id: string | null;
  user_address: string | null;
  /** the model's name suggestions for itself, when it gave some */
  suggestions: string[];
  /** what the chooser offers: the suggestions, or two from the built-in pool */
  chips: string[];
  chosen: string | null;
  /** the language the opening was shown in: "en", "zh", or "" */
  lang: string;
  /** started and not over: its turns are never tasks */
  running: boolean;
  started_at: number;
  finished_at: number;
  /** the three lines the app speaks first, in the language asked for (GET only) */
  intro?: string[];
}

export interface AuditEntry {
  ts: string;
  event: string;
  session?: string;
  tool?: string;
  /** which rung the call was: gui (the phone's screen), browser, web, cli, device, api, local */
  channel?: string;
  summary?: string;
  risk?: string;
  decision?: string;
  approved?: boolean | null;
  approval_scope?: string | null;
  reasons?: string[];
  ok?: boolean;
  error?: string | null;
  duration_ms?: number;
  content?: string;
  tool_calls?: string[];
  [key: string]: unknown;
}

export interface ActivityData {
  audit: AuditEntry[];
  grants: Grant[];
  tainted: boolean;
}

/** One entry of the Feed: something that happened without you asking. */
export interface FeedItem {
  id: string;
  ts: string;
  kind: "background" | "artifact" | "approval" | "question";
  title: string;
  text: string;
  thread: string;
  thread_title: string;
  path?: string | null;
  quiet?: boolean;
}

export interface UpcomingData {
  proactive: boolean;
  proactivity: Proactivity;
  interval_minutes: number;
  /** The interval after the level's stretch/shrink. */
  effective_interval_minutes: number;
  quiet_hours: string;
  /** End of the current quiet window, if we are in one. */
  quiet_until: string | null;
  next_pass_at: string | null;
  queue: Array<{
    goal_id: string;
    title: string;
    category: GoalCategory;
    due: string | null;
    overdue: boolean;
    next_step: string | null;
    progress: { done: number; total: number };
  }>;
  /** Goal check-ins, soonest first. */
  check_ins: Array<{ goal_id: string; title: string; at: string; cadence: string }>;
  /** Reminders and routines: active ones soonest first, then recently finished. */
  reminders: Reminder[];
  /** Triggers: work that starts when something happens. */
  triggers: TriggersData;
  busy: boolean;
}

export type TriggerKind = "mail" | "event" | "hook";
export type TriggerStatus = "active" | "cancelled";

export interface Trigger {
  id: string;
  kind: TriggerKind;
  /** Words that must all appear in the sender/subject (mail) or title/place (event); a hook's name. */
  match: string;
  /** What to do when it fires. */
  text: string;
  thread: string;
  status: TriggerStatus;
  /** event: how long before the start. */
  lead_minutes: number;
  /** hook: the key in the URL ("" for other kinds). */
  secret: string;
  /** hook: the full URL to call ("" once cancelled). */
  url?: string;
  created_at: string;
  last_fired_at: string | null;
  fired: number;
}

export interface TriggersData {
  items: Trigger[];
  /** Which kinds have their connector: mail needs the mailbox, event the calendar. */
  available: Record<TriggerKind, boolean>;
  /** When the inbox was last looked at for mail triggers (ISO), and the last error if any. */
  mail_checked_at: string | null;
  mail_error: string;
  mail_poll_minutes: number;
}

export type ReminderKind = "remind" | "task";
export type ReminderStatus = "active" | "done" | "cancelled";

export interface Reminder {
  id: string;
  text: string;
  kind: ReminderKind;
  thread: string;
  status: ReminderStatus;
  /** Next time it fires (ISO); null once a one-off has fired. */
  next_at: string | null;
  /** "" for a one-off, else a cadence such as "daily 08:00". */
  repeat: string;
  created_at: string;
  last_fired_at: string | null;
  fired: number;
}

export interface PushInfo {
  /** pywebpush is installed on the server. */
  available: boolean;
  /** VAPID public key (base64url) the browser subscribes with. */
  public_key: string;
  subscriptions: number;
  devices: Array<{ endpoint: string; created_at: string | null; ua: string }>;
}

export interface FileInfo {
  path: string;
  name: string;
  size: number;
  modified: string;
}

export type WsMessage =
  | { kind: "hello"; state: StateSnapshot }
  | { kind: "event"; event: TimelineEvent }
  | { kind: "update"; event: TimelineEvent }
  | { kind: "stream_start"; thread: string; id: string; ts: string }
  | { kind: "delta"; thread: string; id: string; text: string }
  | { kind: "stream_end"; thread: string; id: string; discard?: boolean }
  | { kind: "status"; status: Status }
  | { kind: "thread"; thread: ThreadMeta }
  | { kind: "thread_deleted"; thread: string }
  | { kind: "thread_cleared"; thread: string }
  /** a synced message deleted on another device (contract C7 tombstone) */
  | { kind: "event_removed"; thread: string; id: string }
  /** another device started (`working: true`) or finished a turn on a synced chat (contract C9) */
  | ({ kind: "working"; working: boolean } & WorkingPresence)
  | { kind: "goals" }
  | { kind: "memory" }
  | { kind: "reminders" }
  | { kind: "triggers" }
  | { kind: "calendar"; calendar: CalendarData }
  | { kind: "feed_posts" }
  | { kind: "ideas"; ideas: IdeasData }
  | { kind: "profile"; profile: Profile }
  | { kind: "settings"; settings: SettingsView }
  | { kind: "phone"; phone: PhoneStatus & { gui_enabled: boolean } }
  | { kind: "hub"; hub: HubView }
  | { kind: "hands_state"; hands: HandsStatus }
  | ({ kind: "hands" } & HandsLive)
  /** the avatar studio's session, every time it changes (the studio screen watches this; the chat has its card) */
  | { kind: "studio"; current: StudioSession | null }
  | { kind: "connections"; connections: ConnectionsData }
  /** the first conversation moved on (Start, the model's block, a pick) */
  | { kind: "firstrun"; firstrun: FirstRunView }
  | { kind: "skills"; skills: SkillsData }
  | { kind: "approvals_reset" }
  | { kind: "coding"; event: CodingEvent; agent: string; session_id: string; device?: string; run: CodingRun | null }
  | { kind: "error"; error: string }
  | { kind: "pong"; status: Status };
