/**
 * The relay's refusals, read out of a failed model call so the chat can show a card
 * instead of the wire (the phones' `AllowanceSignal` / `NanoMuseCloud.describe`):
 * `allowance_exhausted` with what is left and the ways on, a request too large for the
 * relay, a key the relay no longer knows, a relay that did not answer.
 *
 * The harness's model adapter turns a refused HTTP reply into one line of text —
 * `<status>: <json body>` for a JSON body, `<status> <text>` for a plain one, a transport
 * sentence when nothing came back — and a routing code (`RATE_LIMIT`, `SERVER`, …). The
 * host reads that line back here (`parseRelayFailure`), on the `llm/stream` waterfall, and
 * rewrites the finish chunk: the code becomes `nanomuse/<kind>`, which the client's chat
 * renders as the card and which the retry plugin does not retry (a spent allowance is not
 * a rate limit). Pure: no I/O, shared by the host and the browser half.
 */

/** What the relay said, in the words the cards are keyed by. */
export type RefusalKind =
  /** 429 `allowance_exhausted`, 402 `out_of_tokens`: the pool is spent. */
  | 'exhausted'
  /** 429 `allowance_exhausted` with `paused: true` (relay 0.22): the free allowance switched off by the operator, not spent — the same card, other words. */
  | 'allowance_paused'
  /** 413 (the relay's `too_large`, or the proxy's plain `Request too large`); a 400 about the context window. */
  | 'too_large'
  /** 400 `content_rejected`: the provider's content check declined the words (the relay's code, or a provider's own `DataInspectionFailed`). Final: change the words or start a new chat. */
  | 'content_rejected'
  /** 401: the key was retired elsewhere; sign in again. */
  | 'signed_out'
  /** 403: the account is disabled, or this relay does not take it. */
  | 'disabled'
  /** 429 `daily_cap`: today's share is spent (a relay that sets one). */
  | 'daily_cap'
  /** 429 otherwise: `rate_limited`, `too_many_in_flight`, `provider_busy`, `locked`. */
  | 'busy'
  /** 404 `model_not_offered`: the chosen model left the menu. */
  | 'model'
  /** 5xx: the relay, or the provider behind it, did not answer. */
  | 'relay_down'
  /** No HTTP answer at all: connection refused, DNS, timeout. */
  | 'unreachable'
  /** 503 `service_paused` (relay 0.22): the operator paused the relay; nothing is lost. */
  | 'service_paused'
  /** 503 `sync_paused` (relay 0.22): conversation sync is off for now; the devices work on their own. */
  | 'sync_paused'
  /** 503 `hub_paused` (relay 0.22): the device hub is off for now; each device works on its own. */
  | 'hub_paused'
  /** Not the relay: the host refused the call itself, because Cloud models are switched off (Settings › Models) and the chat still sits on one. */
  | 'cloud_off'
  /** Any other refusal: the relay's own sentence is shown. */
  | 'other'

export const REFUSAL_KINDS: readonly RefusalKind[] = ['exhausted', 'allowance_paused', 'too_large', 'content_rejected', 'signed_out', 'disabled', 'daily_cap', 'busy', 'model', 'relay_down', 'unreachable', 'service_paused', 'sync_paused', 'hub_paused', 'cloud_off', 'other']

/** The operator's switches (relay 0.22, `docs/cloud.md` → Controls): the code is the kind. */
const PAUSED_CODES: Record<string, RefusalKind> = { service_paused: 'service_paused', sync_paused: 'sync_paused', hub_paused: 'hub_paused' }

/** One refusal, read from the adapter's failure line. */
export interface RelayRefusal {
  kind: RefusalKind
  /** The HTTP status; 0 when no answer came. */
  status: number
  /** The relay's `code` (`allowance_exhausted`, `too_large`, …); `http_<status>` without one; `unreachable` with no answer. */
  code: string
  /** The relay's own sentence, English; '' when it sent none. */
  message: string
  /** `allowance_exhausted`: what is left and the pool, in yuan. */
  left?: number
  grant?: number
  /** `allowance_exhausted`: where the ways on lead (relay 0.17+). */
  inviteUrl?: string
  inviteBonusCny?: number
  ownKeyDocs?: string
  /** `allowance_exhausted`: the own-key card as data (relay 0.21, contract C11), as sent. */
  guidance?: Record<string, unknown>
  /** `retry_after` in seconds, when the relay said when to come back. */
  retryAfterMs?: number
  /** Relay 0.22: the refusal comes from one of the operator's switches, not from use (`paused: true`). */
  paused?: boolean
}

/** The failure codes the host writes; the client reads the kind back out of them. */
export const REFUSAL_PREFIX = 'nanomuse/'

export function refusalCode(kind: RefusalKind): string {
  return `${REFUSAL_PREFIX}${kind}`
}

/** The kind inside a failure code of ours, or undefined for any other code. */
export function refusalKindOf(code: string | undefined | null): RefusalKind | undefined {
  if (typeof code !== 'string' || !code.startsWith(REFUSAL_PREFIX)) return undefined
  const kind = code.slice(REFUSAL_PREFIX.length)
  return (REFUSAL_KINDS as readonly string[]).includes(kind) ? (kind as RefusalKind) : undefined
}

const TRANSPORT = /\b(?:timed?\s*out|timeout|connection error|fetch failed|network error|socket hang up|ECONN[A-Z]+|ENOTFOUND|EAI_AGAIN|other side closed|premature close|terminated)\b/i
const TIMEOUT = /\b(?:timed?\s*out|timeout)\b/i

/**
 * What a thrown error says about the wire, when it is about the wire: `timeout` for a
 * deadline that passed (`AbortSignal.timeout`'s TimeoutError, "timed out"), `unreachable`
 * for a connection that never came together (Node's `fetch failed` with its `cause`,
 * ECONNREFUSED, ENOTFOUND); undefined for anything else (the relay's own refusals, a bug).
 * The host's routes turn these into codes the browser half can put into words.
 */
export function transportFailure(error: unknown): 'timeout' | 'unreachable' | undefined {
  if (!error || typeof error !== 'object') return undefined
  const e = error as { name?: unknown; message?: unknown; cause?: unknown; code?: unknown }
  if (e.name === 'TimeoutError') return 'timeout'
  const texts = [e.message, e.code, (e.cause as { message?: unknown; code?: unknown } | undefined)?.message, (e.cause as { code?: unknown } | undefined)?.code]
    .filter((v): v is string => typeof v === 'string')
    .join(' ')
  if (!texts) return undefined
  if (e.name === 'AbortError' && TIMEOUT.test(texts)) return 'timeout'
  if (!TRANSPORT.test(texts)) return undefined
  return TIMEOUT.test(texts) ? 'timeout' : 'unreachable'
}

const CONTEXT = /\b(?:context (?:length|window)|too many tokens|maximum context|prompt is too long|content is too long|exceeds the model|token limit)\b/i

/**
 * How a provider's content check says no, in the relay's sentence or in the provider's own body:
 * the relay's code and its words, Bailian's `DataInspectionFailed` / `data_inspection_failed` with
 * its "inappropriate content" line (the relay keeps the same marks in `CONTENT_CHECK_MARKS`). The
 * phones match the same list. A miss leaves the error as any other provider error.
 */
const CONTENT_CHECK = /content_rejected|content check declined|data_inspection_failed|datainspectionfailed|inappropriate content|green net/i

/** True when `text` (an error body, or an error's own line) is a content check saying no. */
export function contentCheck(text: string | undefined | null): boolean {
  return typeof text === 'string' && CONTENT_CHECK.test(text)
}

const num = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)
const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '')

/** The relay's error object out of a body: `{error: {...}}` (OpenAI's shape) or the inner object itself. */
function errorObject(json: string): Record<string, unknown> | undefined {
  let value: unknown
  try {
    value = JSON.parse(json)
  } catch {
    // pi-ai may append a provider's raw metadata after a newline: the first line is the body
    const first = json.split('\n')[0] ?? ''
    try {
      value = JSON.parse(first)
    } catch {
      return undefined
    }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const o = value as Record<string, unknown>
  if (o.error && typeof o.error === 'object' && !Array.isArray(o.error)) return o.error as Record<string, unknown>
  return o
}

/** The kind for a status, a code and the relay's sentence. */
export function classifyRefusal(status: number, code: string, message: string, paused = false): RefusalKind {
  if (code === 'allowance_exhausted' && paused) return 'allowance_paused'
  if (code === 'allowance_exhausted' || code === 'out_of_tokens') return 'exhausted'
  if (PAUSED_CODES[code]) return PAUSED_CODES[code]
  if (status === 413 || code === 'too_large') return 'too_large'
  if (code === 'content_rejected' || (status === 400 && contentCheck(message))) return 'content_rejected'
  if (status === 400 && CONTEXT.test(message)) return 'too_large'
  if (status === 401) return 'signed_out'
  if (status === 403) return 'disabled'
  if (code === 'daily_cap') return 'daily_cap'
  if (status === 429) return 'busy'
  if (status === 404 && code === 'model_not_offered') return 'model'
  if (status >= 500) return 'relay_down'
  if (status === 0) return 'unreachable'
  return 'other'
}

/**
 * The refusal inside an adapter failure: `message` is what the adapter made of the reply
 * (`429: {"message":…,"code":"allowance_exhausted",…}`, `413 Request too large`,
 * `nanoMuse Cloud (502): …`, `Connection error.`), `code` its routing code. Null when the line
 * is not a refused HTTP reply or a transport failure — a model that answered and then said
 * nothing, say — so the caller leaves it as it was.
 */
export function parseRelayFailure(message: string, code?: string): RelayRefusal | null {
  const line = (message ?? '').trim()
  const m = /^(?:[^\n(]{0,80}\()?(\d{3})\)?(?::\s*|\s+)([\s\S]*)$/.exec(line)
  if (!m) {
    if (code === 'TIMEOUT' || code === 'TRANSPORT' || TRANSPORT.test(line)) {
      return { kind: 'unreachable', status: 0, code: 'unreachable', message: line }
    }
    return null
  }
  const status = Number(m[1])
  const rest = (m[2] ?? '').trim()
  const err = rest.startsWith('{') ? errorObject(rest) : undefined
  const relayCode = str(err?.code) || `http_${status}`
  const text = err ? str(err.message) : rest.replace(/^status code \(no body\)$/, '')
  const paused = err?.paused === true
  const refusal: RelayRefusal = { kind: classifyRefusal(status, relayCode, text, paused), status, code: relayCode, message: text }
  if (paused) refusal.paused = true
  if (err) {
    const left = num(err.left)
    const grant = num(err.grant)
    if (left !== undefined) refusal.left = left
    if (grant !== undefined) refusal.grant = grant
    const inviteUrl = str(err.invite_url)
    if (inviteUrl) refusal.inviteUrl = inviteUrl
    const bonus = num(err.invite_bonus_cny)
    if (bonus !== undefined) refusal.inviteBonusCny = bonus
    const docs = str(err.own_key_docs)
    if (docs) refusal.ownKeyDocs = docs
    if (err.guidance && typeof err.guidance === 'object' && !Array.isArray(err.guidance)) refusal.guidance = err.guidance as Record<string, unknown>
    const retry = num(err.retry_after)
    if (retry !== undefined && retry > 0) refusal.retryAfterMs = Math.round(retry * 1000)
  }
  return refusal
}

/** The one plain sentence the host writes for a kind — the log's and an older client's; the browser has its own words in every locale. */
export function refusalSentence(refusal: RelayRefusal): string {
  switch (refusal.kind) {
    case 'exhausted':
      return 'The free allowance is used up. Add a key of your own, sign in with a plan you already pay for, or invite a friend, all under Settings → nanoMuse Cloud. Your sign-in and your devices keep working.'
    case 'allowance_paused':
      return 'The free allowance is paused on this relay for now, not used up. Add a key of your own or sign in with a plan you already pay for, both under Settings → nanoMuse Cloud. Your sign-in, your devices and what is left stay as they are.'
    case 'too_large':
      return 'That message is too large for the model. Shorten it, leave out some attachments, or start a new chat.'
    case 'content_rejected':
      return "The model provider's content check declined this request. Try different words, or start a new chat if it keeps happening: the words it objects to can be earlier in the conversation."
    case 'signed_out':
      return 'This sign-in is no longer valid. Sign in again under Settings → nanoMuse Cloud.'
    case 'disabled':
      return refusal.message || 'This account cannot use nanoMuse Cloud right now.'
    case 'daily_cap':
      return refusal.message || "Today's share of the allowance is used up."
    case 'busy':
      return 'Too many requests at once. Wait a moment and try again.'
    case 'model':
      return 'nanoMuse Cloud does not offer that model any more. Pick another under Settings → nanoMuse Cloud.'
    case 'relay_down':
      return 'nanoMuse Cloud did not answer. Try again in a moment.'
    case 'unreachable':
      return 'Could not reach nanoMuse Cloud. Check the connection and try again.'
    case 'service_paused':
      return 'nanoMuse Cloud is paused by its operator for now; your sign-in and your data are kept. Try again later.'
    case 'sync_paused':
      return 'Conversation sync is paused on this relay for now; what is stored is kept and your devices keep working on their own.'
    case 'hub_paused':
      return 'The device hub is paused on this relay for now; each device keeps working on its own.'
    case 'cloud_off':
      return 'nanoMuse Cloud models are switched off under Settings → Models, and this chat still runs on one, so nothing was sent. Pick another model for the chat, start a new chat, or use nanoMuse Cloud this time.'
    case 'other':
      return refusal.message || 'nanoMuse Cloud could not complete the request.'
  }
}

/** The failure the host writes when it refuses a call itself because Cloud models are off: no HTTP status, our code, our sentence. */
export function cloudOffFailure(): FailureLike {
  const refusal: RelayRefusal = { kind: 'cloud_off', status: 0, code: 'cloud_off', message: '' }
  return { message: refusalSentence(refusal), code: refusalCode('cloud_off') }
}

/** The shape of a finish chunk's failure, as far as this module reads and writes it. */
export interface FailureLike {
  readonly message: string
  readonly code: string
  readonly status?: number
  readonly providerRetryAfterMs?: number
}

/** The harness's codes other plugins act on (compact and retry, offload images): left alone. */
const HANDLED_BY_DSH = new Set(['CONTEXT_WINDOW_EXCEEDED', 'IMAGE_OFFLOAD_REQUIRED'])

/**
 * The failure to put in the finish chunk instead of the adapter's: our code, our sentence, the
 * relay's status. Null when the failure is not a refusal (left as it was). A refusal is never
 * retried by the harness — `nanomuse/*` is not among its retryable codes — so a spent allowance
 * shows at once rather than after five back-offs of a "rate limit".
 */
export function relayFailure(failure: FailureLike): { failure: FailureLike; refusal: RelayRefusal } | null {
  if (HANDLED_BY_DSH.has(failure.code)) return null
  const refusal = parseRelayFailure(failure.message, failure.code)
  if (!refusal) return null
  const out: { message: string; code: string; status?: number; providerRetryAfterMs?: number } = {
    message: refusalSentence(refusal),
    code: refusalCode(refusal.kind),
  }
  if (refusal.status > 0) out.status = refusal.status
  if (refusal.retryAfterMs !== undefined) out.providerRetryAfterMs = refusal.retryAfterMs
  return { failure: out, refusal }
}

// ---- what the card shows, by kind (the browser draws it; tested here as data) --------------------

/** A button on a refusal card; `cloud-once` is *Use nanoMuse Cloud this time*, `models` opens Settings › Models. */
export type RefusalAction = 'ways' | 'sign-in' | 'retry' | 'new-chat' | 'settings' | 'cloud-once' | 'models'

/** The card for a kind: which actions it offers, in order, and whether the relay's own sentence is worth showing under ours. */
export function refusalCard(kind: RefusalKind): { actions: RefusalAction[]; showRelayText: boolean } {
  switch (kind) {
    case 'exhausted':
    case 'allowance_paused':
      return { actions: ['ways', 'retry'], showRelayText: false }
    case 'too_large':
      return { actions: ['new-chat'], showRelayText: false }
    case 'content_rejected':
      // the words are the matter: a new chat leaves them behind; *Try again* sends the same ones once more, by choice
      return { actions: ['new-chat', 'retry'], showRelayText: false }
    case 'signed_out':
      return { actions: ['sign-in'], showRelayText: false }
    case 'disabled':
      return { actions: ['settings'], showRelayText: true }
    case 'daily_cap':
      return { actions: ['ways', 'retry'], showRelayText: true }
    case 'busy':
      return { actions: ['retry'], showRelayText: false }
    case 'model':
      return { actions: ['settings'], showRelayText: false }
    case 'relay_down':
    case 'unreachable':
    case 'service_paused':
    case 'sync_paused':
    case 'hub_paused':
      return { actions: ['retry'], showRelayText: false }
    case 'cloud_off':
      return { actions: ['cloud-once', 'new-chat', 'models'], showRelayText: false }
    case 'other':
      return { actions: ['retry', 'settings'], showRelayText: true }
  }
}

/** The harness's own routing codes, read for a provider that is not the relay (an own key): what the generic card says. */
export type ProviderFailureKind = 'auth' | 'quota' | 'too_large' | 'content_rejected' | 'busy' | 'server' | 'unreachable' | 'other'

export function providerFailureKind(code: string | undefined, message: string): ProviderFailureKind {
  switch (code) {
    case 'AUTH':
    case 'INVALID_CREDENTIAL':
      return 'auth'
    case 'QUOTA':
    case 'ACCOUNT_QUOTA':
      return 'quota'
    case 'CONTEXT_WINDOW_EXCEEDED':
    case 'IMAGE_OFFLOAD_REQUIRED':
      return 'too_large'
    case 'RATE_LIMIT':
      return 'busy'
    case 'SERVER':
      return 'server'
    case 'TIMEOUT':
    case 'TRANSPORT':
      return 'unreachable'
    default:
      if (contentCheck(message)) return 'content_rejected'
      if (/\b413\b/.test(message) || CONTEXT.test(message)) return 'too_large'
      return 'other'
  }
}
