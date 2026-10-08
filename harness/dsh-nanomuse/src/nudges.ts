/**
 * The star nudges (C1): when it is fair to ask for a star on GitHub, decided by one gate
 * from a policy the relay publishes (`GET /v1/nudges`, also carried on `/v1/me`) and a
 * ledger of what this computer already asked. Pure shapes and decisions; `rooms.ts` keeps
 * both in `$DSH_HOME/nanomuse/nudges.json`, fetches the policy at most once a day, and
 * answers the browser's questions under `/nanomuse/rooms/nudges/*`.
 *
 * Semantics, as every app agrees them:
 * - `enabled: false` → no asks at all (the Star rows that are always there stay).
 * - a task is a person-started model turn that ended with a reply; the first conversation's
 *   turns and background runs never count; the counter is per computer and persists.
 * - each `tasks` threshold asks once; `days_used` asks on the 7th and the 30th distinct
 *   calendar day the app was opened; `goal_done` when a goal is marked done; `signed_in`
 *   once on the Account page; `new_look` after a face was drawn; `exhausted` in the
 *   allowance card.
 * - `cooldown_days` between any two asks; `max_asks` is a lifetime cap — showing a card is an
 *   ask, "Not now" included; going to GitHub from any card or Settings row, or "I already
 *   starred" on a card, sets `starred` and ends them all, whatever the cooldown and the asks left.
 * - `text` and `text_zh` (optional, ≤ 200 characters each, empty by default): the
 *   card's body sentence, when the relay wants to say it in its own words. Trimmed; a value
 *   over the cap is dropped. A Chinese UI takes `text_zh`, else `text`, else the app's own
 *   sentence for the moment; the title and the buttons stay the app's (`starText`).
 */

// ---- the policy ----------------------------------------------------------------------

export interface NudgeMoments {
  signed_in: boolean
  tasks: number[]
  new_look: boolean
  exhausted: boolean
  days_used: number[]
  goal_done: boolean
}

export interface NudgesPolicy {
  version: number
  star: {
    enabled: boolean
    url: string
    moments: NudgeMoments
    cooldown_days: number
    max_asks: number
    /** The card's body sentence in the relay's words; '' means the app's own. */
    text: string
    text_zh: string
  }
}

export const DEFAULT_NUDGES: NudgesPolicy = {
  version: 1,
  star: {
    enabled: true,
    url: 'https://github.com/nano-muse/nanoMuse',
    moments: { signed_in: true, tasks: [3, 10, 30], new_look: true, exhausted: true, days_used: [7, 30], goal_done: true },
    cooldown_days: 7,
    max_asks: 4,
    text: '',
    text_zh: '',
  },
}

/** The longest body sentence a relay may put on the card; anything longer is dropped, not cut. */
export const STAR_TEXT_MAX = 200

/** A relay's sentence as the card may show it: trimmed; '' when it is not a string, empty, or over STAR_TEXT_MAX. */
export function starSentence(value: unknown): string {
  if (typeof value !== 'string') return ''
  const text = value.trim()
  return text.length > 0 && text.length <= STAR_TEXT_MAX ? text : ''
}

/**
 * The card's body: the relay's Chinese sentence for a Chinese UI, else its English one, else
 * the app's own words for the moment (`fallback`). Only the body changes; the title and the
 * buttons are always the app's.
 */
export function starText(policy: Pick<NudgesPolicy, 'star'>, zh: boolean, fallback: string): string {
  const s = policy.star
  return (zh && s.text_zh) || s.text || fallback
}

/** The policy is fetched at most this often. */
export const NUDGES_EVERY_MS = 24 * 3600_000
/** Where own-key installs (no relay account) read the policy from. */
export const NUDGES_ORIGIN = 'https://cloud.nanomuse.cn'
export const NUDGES_TIMEOUT_MS = 5000

function numbers(value: unknown, fallback: number[]): number[] {
  if (!Array.isArray(value)) return fallback
  const out = value.filter((n): n is number => typeof n === 'number' && Number.isInteger(n) && n > 0).sort((a, b) => a - b)
  return out.length ? [...new Set(out)] : fallback
}

function flag(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

/** A relay's policy over the defaults: every key it omits keeps the default; nothing it sends can break the shape. */
export function mergeNudges(raw: unknown): NudgesPolicy {
  if (!raw || typeof raw !== 'object') return structuredClone(DEFAULT_NUDGES)
  const r = raw as Record<string, unknown>
  const star = r.star && typeof r.star === 'object' ? (r.star as Record<string, unknown>) : {}
  const m = star.moments && typeof star.moments === 'object' ? (star.moments as Record<string, unknown>) : {}
  const d = DEFAULT_NUDGES.star
  return {
    version: typeof r.version === 'number' ? r.version : DEFAULT_NUDGES.version,
    star: {
      enabled: flag(star.enabled, d.enabled),
      url: typeof star.url === 'string' && /^https:\/\//.test(star.url) ? star.url : d.url,
      moments: {
        signed_in: flag(m.signed_in, d.moments.signed_in),
        tasks: numbers(m.tasks, d.moments.tasks),
        new_look: flag(m.new_look, d.moments.new_look),
        exhausted: flag(m.exhausted, d.moments.exhausted),
        days_used: numbers(m.days_used, d.moments.days_used),
        goal_done: flag(m.goal_done, d.moments.goal_done),
      },
      cooldown_days: typeof star.cooldown_days === 'number' && star.cooldown_days >= 0 ? star.cooldown_days : d.cooldown_days,
      max_asks: typeof star.max_asks === 'number' && star.max_asks >= 0 ? star.max_asks : d.max_asks,
      text: starSentence(star.text),
      text_zh: starSentence(star.text_zh),
    },
  }
}

/** The policy inside a relay answer: the body itself, or its `nudges` field (as `/v1/me` carries it); null when neither is one. */
export function readNudges(raw: unknown): NudgesPolicy | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  if (r.star && typeof r.star === 'object') return mergeNudges(r)
  if (r.nudges && typeof r.nudges === 'object') return readNudges(r.nudges)
  return null
}

// ---- the ledger ----------------------------------------------------------------------

export type Moment = keyof NudgeMoments

export const MOMENTS: readonly Moment[] = ['signed_in', 'tasks', 'new_look', 'exhausted', 'days_used', 'goal_done']

/** One ask that was shown (or is due to be): the moment, its number for the counted ones, and the key the ledger keeps it under. */
export interface Ask {
  moment: Moment
  /** The count for `tasks` and `days_used`. */
  n?: number
  key: string
  at: number
}

export interface NudgeLedger {
  /** Person-started turns that ended with a reply, on this computer. */
  tasks: number
  /** Distinct calendar days (local `YYYY-MM-DD`) the app was opened, oldest first; capped. */
  days: string[]
  /** Every ask shown, oldest first. */
  asks: Ask[]
  /** The person went to GitHub from a card: no more asks, ever. */
  starred: boolean
}

export const LEDGER_EMPTY: NudgeLedger = { tasks: 0, days: [], asks: [], starred: false }

const DAYS_KEEP = 400

export function readLedger(raw: unknown): NudgeLedger {
  if (!raw || typeof raw !== 'object') return structuredClone(LEDGER_EMPTY)
  const r = raw as Record<string, unknown>
  return {
    tasks: typeof r.tasks === 'number' && r.tasks >= 0 ? Math.floor(r.tasks) : 0,
    days: Array.isArray(r.days) ? r.days.filter((d): d is string => typeof d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(d)).slice(-DAYS_KEEP) : [],
    asks: Array.isArray(r.asks)
      ? r.asks
          .filter((a): a is Record<string, unknown> => Boolean(a) && typeof a === 'object')
          .map((a) => ({ moment: a.moment as Moment, key: String(a.key ?? ''), at: typeof a.at === 'number' ? a.at : 0, ...(typeof a.n === 'number' ? { n: a.n } : {}) }))
          .filter((a) => (MOMENTS as readonly string[]).includes(a.moment) && a.key !== '')
      : [],
    starred: r.starred === true,
  }
}

/** The local calendar day of `at`, as the ledger writes it. */
export function dayKey(at = Date.now()): string {
  const d = new Date(at)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

export function askKey(moment: Moment, n?: number): string {
  return n === undefined ? moment : `${moment}:${n}`
}

// ---- the one gate --------------------------------------------------------------------

/**
 * Whether an ask is due for `moment` now: the policy allows it, the moment is on, this exact
 * moment (with its number) was not asked before, the cooldown since the last ask has passed,
 * the lifetime cap is not reached, and the person has not starred already. Returns the ask to
 * record and show, or null.
 */
export function dueAsk(policy: NudgesPolicy, ledger: NudgeLedger, moment: Moment, n?: number, now = Date.now()): Ask | null {
  const star = policy.star
  if (!star.enabled || ledger.starred) return null
  const on = star.moments[moment]
  if (Array.isArray(on)) {
    if (n === undefined || !on.includes(n)) return null
  } else if (!on) return null
  if (ledger.asks.length >= star.max_asks) return null
  const key = askKey(moment, n)
  if (ledger.asks.some((a) => a.key === key)) return null
  const last = ledger.asks[ledger.asks.length - 1]
  if (last && now - last.at < star.cooldown_days * 86_400_000) return null
  return { moment, key, at: now, ...(n === undefined ? {} : { n }) }
}

/** Showing a card is an ask: written before it is drawn. */
export function recordAsk(ledger: NudgeLedger, ask: Ask): NudgeLedger {
  if (ledger.asks.some((a) => a.key === ask.key)) return ledger
  return { ...ledger, asks: [...ledger.asks, ask] }
}

/** One more task ran to its end. */
export function recordTask(ledger: NudgeLedger): NudgeLedger {
  return { ...ledger, tasks: ledger.tasks + 1 }
}

/** The app was opened: a new calendar day is added once; tells whether this one was new. */
export function recordDay(ledger: NudgeLedger, now = Date.now()): { ledger: NudgeLedger; newDay: boolean } {
  const key = dayKey(now)
  if (ledger.days.includes(key)) return { ledger, newDay: false }
  return { ledger: { ...ledger, days: [...ledger.days, key].slice(-DAYS_KEEP) }, newDay: true }
}

/** The person went to GitHub, or said they already starred: the end of all asks. */
export function recordStarred(ledger: NudgeLedger): NudgeLedger {
  return ledger.starred ? ledger : { ...ledger, starred: true }
}

/** What the browser mirrors: the policy, the ledger's figures, and the ask it should be showing now, if any. */
export interface NudgesView {
  policy: NudgesPolicy
  tasks: number
  days: number
  asks: number
  starred: boolean
  fetchedAt: number
  /** The latest ask the host granted; the browser shows it while it is fresh or until dismissed. */
  current: Ask | null
}
