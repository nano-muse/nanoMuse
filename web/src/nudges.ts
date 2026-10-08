/**
 * When the app may ask for a star on GitHub (contract C1) — the policy and the ledger.
 *
 * The *policy* comes from the relay through the runtime (`GET /api/nudges`, read once a day;
 * the built-in defaults below are the relay's own). The *ledger* is this browser's: how many
 * tasks it saw through, how many days it was opened, which asks it showed and when, whether
 * the person went to GitHub. It lives in localStorage under `nm.star.*`. Nothing here draws
 * anything; `components/StarNudge.tsx` is the card. This file has no DOM in it so the gate
 * can be tested in plain node.
 */

export type StarMoment = "signed_in" | "tasks" | "new_look" | "exhausted" | "days_used" | "goal_done";

export interface StarPolicy {
  enabled: boolean;
  url: string;
  moments: {
    signed_in: boolean;
    tasks: number[];
    new_look: boolean;
    exhausted: boolean;
    days_used: number[];
    goal_done: boolean;
  };
  cooldown_days: number;
  max_asks: number;
  /** the card's sentence from the relay, English and Chinese; "" = the app's own words */
  text: string;
  text_zh: string;
}

export interface NudgesPolicy {
  version: number;
  star: StarPolicy;
}

export const DEFAULT_POLICY: NudgesPolicy = {
  version: 1,
  star: {
    enabled: true,
    url: "https://github.com/nano-muse/nanoMuse",
    moments: { signed_in: true, tasks: [3, 10, 30], new_look: true, exhausted: true, days_used: [7, 30], goal_done: true },
    cooldown_days: 7,
    max_asks: 4,
    text: "",
    text_zh: "",
  },
};

const DAY_MS = 24 * 3600 * 1000;

/** The longest sentence the relay may put on the card. */
export const TEXT_MAX = 200;

/** A relay sentence: trimmed, kept up to `TEXT_MAX` characters, otherwise "". */
function sentence(v: unknown): string {
  if (typeof v !== "string") return "";
  const s = v.trim();
  return s.length <= TEXT_MAX ? s : "";
}

/**
 * The sentence the star card shows: in a Chinese UI the relay's `text_zh`, else its `text`,
 * else `own` — the app's built-in words. Only the body sentence changes; the card's title
 * and buttons stay the app's.
 */
export function starSentence(policy: NudgesPolicy, zh: boolean, own: string): string {
  const { text, text_zh } = policy.star;
  if (zh && text_zh) return text_zh;
  if (text) return text;
  return own;
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const bool = (v: unknown, fallback: boolean) => (typeof v === "boolean" ? v : fallback);
const int = (v: unknown, low: number, high: number, fallback: number) =>
  typeof v === "number" && Number.isFinite(v) && Math.trunc(v) >= low && Math.trunc(v) <= high ? Math.trunc(v) : fallback;
function intList(v: unknown, fallback: number[]): number[] {
  if (!Array.isArray(v)) return fallback;
  const out = new Set<number>();
  for (const item of v) {
    if (typeof item !== "number" || !Number.isFinite(item) || Math.trunc(item) < 1) return fallback;
    out.add(Math.trunc(item));
  }
  return [...out].sort((a, b) => a - b);
}

/** The relay's answer as the app keeps it: its values where they make sense, the defaults where not. */
export function normalizePolicy(body: unknown): NudgesPolicy {
  const d = DEFAULT_POLICY.star;
  if (!isObj(body)) return structuredClone(DEFAULT_POLICY);
  const version = int(body.version, 1, 1_000_000_000, 1);
  const s = isObj(body.star) ? body.star : {};
  const m = isObj(s.moments) ? s.moments : {};
  const url = typeof s.url === "string" && /^https?:\/\//.test(s.url) && s.url.length <= 200 ? s.url : d.url;
  return {
    version,
    star: {
      enabled: bool(s.enabled, d.enabled),
      url,
      moments: {
        signed_in: bool(m.signed_in, d.moments.signed_in),
        tasks: intList(m.tasks, d.moments.tasks),
        new_look: bool(m.new_look, d.moments.new_look),
        exhausted: bool(m.exhausted, d.moments.exhausted),
        days_used: intList(m.days_used, d.moments.days_used),
        goal_done: bool(m.goal_done, d.moments.goal_done),
      },
      cooldown_days: int(s.cooldown_days, 0, 365, d.cooldown_days),
      max_asks: int(s.max_asks, 0, 50, d.max_asks),
      text: sentence(s.text),
      text_zh: sentence(s.text_zh),
    },
  };
}

// ----------------------------------------------------------------------------- the ledger

/** What localStorage offers; a test hands in a Map-backed one. */
export interface KV {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export const KEYS = {
  starred: "nm.star.starred",
  tasks: "nm.star.tasks",
  asks: "nm.star.asks",
  lastAsk: "nm.star.last_ask",
  shown: "nm.star.shown",
  days: "nm.star.days",
  lastDay: "nm.star.last_day",
  migrated: "nm.star.v2",
} as const;

/** The keys of the first version: one flag per moment. */
const LEGACY_MOMENTS = ["signed_in", "first_task", "tenth_task", "new_look"] as const;

export interface Ledger {
  /** The person went to GitHub from an ask: no more asks, ever. */
  starred: boolean;
  /** Tasks this browser saw through (person-started turns with a reply, after the first run). */
  tasks: number;
  /** Asks shown so far ("Not now" counts). */
  asks: number;
  /** When the last ask was shown (ms since the epoch), or null. */
  lastAsk: number | null;
  /** The asks shown, by id (`signed_in`, `tasks:3`, `days_used:7`, …). */
  shown: string[];
  /** Distinct calendar days the app was opened. */
  days: number;
  /** The last of those days, as `YYYY-MM-DD` (local). */
  lastDay: string;
}

const num = (v: string | null) => {
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? Math.trunc(n) : 0;
};

export function readLedger(kv: KV): Ledger {
  let shown: string[] = [];
  try {
    const raw = JSON.parse(kv.getItem(KEYS.shown) ?? "[]");
    if (Array.isArray(raw)) shown = raw.filter((x): x is string => typeof x === "string");
  } catch {
    shown = [];
  }
  const last = kv.getItem(KEYS.lastAsk);
  return {
    starred: kv.getItem(KEYS.starred) === "1",
    tasks: num(kv.getItem(KEYS.tasks)),
    asks: num(kv.getItem(KEYS.asks)),
    lastAsk: last ? num(last) || null : null,
    shown,
    days: num(kv.getItem(KEYS.days)),
    lastDay: kv.getItem(KEYS.lastDay) ?? "",
  };
}

export function writeLedger(kv: KV, l: Ledger): void {
  kv.setItem(KEYS.starred, l.starred ? "1" : "0");
  kv.setItem(KEYS.tasks, String(l.tasks));
  kv.setItem(KEYS.asks, String(l.asks));
  if (l.lastAsk) kv.setItem(KEYS.lastAsk, String(l.lastAsk));
  else kv.removeItem(KEYS.lastAsk);
  kv.setItem(KEYS.shown, JSON.stringify(l.shown));
  kv.setItem(KEYS.days, String(l.days));
  kv.setItem(KEYS.lastDay, l.lastDay);
}

/**
 * The first version kept one flag per moment and no count of asks. Those flags become
 * entries in `shown`, each one an ask already made (so the lifetime cap counts them); the
 * task counter carries over as it is. Runs once; later calls change nothing.
 */
export function migrateLedger(kv: KV): Ledger {
  const l = readLedger(kv);
  if (kv.getItem(KEYS.migrated) === "1") return l;
  for (const m of LEGACY_MOMENTS) {
    const key = `nm.star.${m}`;
    if (kv.getItem(key) === "1" && !l.shown.includes(m)) {
      l.shown.push(m);
      l.asks += 1;
    }
    kv.removeItem(key);
  }
  writeLedger(kv, l);
  kv.setItem(KEYS.migrated, "1");
  return l;
}

// ----------------------------------------------------------------------------- the gate

/** The id an ask is remembered under: the moment, with the number for the counted ones. */
export const askId = (moment: StarMoment, n?: number): string => (moment === "tasks" || moment === "days_used" ? `${moment}:${n ?? 0}` : moment);

/** Asks are allowed at all right now: on, not starred, under the cap, past the cooldown. */
export function canAsk(policy: NudgesPolicy, l: Ledger, now: number): boolean {
  const s = policy.star;
  if (!s.enabled || l.starred || l.asks >= s.max_asks) return false;
  return l.lastAsk === null || now - l.lastAsk >= s.cooldown_days * DAY_MS;
}

/**
 * Whether to ask at this moment. For `tasks` and `days_used`, `n` is the count just reached:
 * the ask is due when it is one of the policy's steps. Each id is asked once.
 */
export function askDue(moment: StarMoment, policy: NudgesPolicy, l: Ledger, now: number, n?: number): boolean {
  if (!canAsk(policy, l, now)) return false;
  const m = policy.star.moments;
  const on = moment === "tasks" || moment === "days_used" ? n !== undefined && m[moment].includes(n) : m[moment];
  return on && !l.shown.includes(askId(moment, n));
}

/** The card for `id` was drawn: one more ask, the cooldown starts now. */
export function recordAsk(kv: KV, id: string, now: number): Ledger {
  const l = readLedger(kv);
  if (!l.shown.includes(id)) {
    l.shown.push(id);
    l.asks += 1;
    l.lastAsk = now;
    writeLedger(kv, l);
  }
  return l;
}

/** Off to GitHub, or "I already starred": no more asks from any moment, whatever the cooldown and the asks left. */
export function recordStarred(kv: KV): void {
  const l = readLedger(kv);
  l.starred = true;
  writeLedger(kv, l);
}

/** One more task seen through; the count so far. */
export function recordTask(kv: KV): number {
  const l = readLedger(kv);
  l.tasks += 1;
  writeLedger(kv, l);
  return l.tasks;
}

export const dayStamp = (d: Date): string => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/**
 * The app was opened: a new calendar day counts once. Returns the day count, and whether
 * this open was the first of its day (the moment to consider a `days_used` ask).
 */
export function recordDay(kv: KV, today: Date): { days: number; fresh: boolean } {
  const l = readLedger(kv);
  const stamp = dayStamp(today);
  if (l.lastDay === stamp) return { days: l.days, fresh: false };
  l.days += 1;
  l.lastDay = stamp;
  writeLedger(kv, l);
  return { days: l.days, fresh: true };
}
