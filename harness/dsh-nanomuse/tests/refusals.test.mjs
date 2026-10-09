// The relay's refusals, read out of the harness adapter's failure line and turned into the
// card the chat draws (C12): the allowance used up with its guidance, a request too large
// (the relay's JSON and the proxy's plain text), a retired key, a relay that did not answer —
// and what is left alone (another provider's words, the codes the harness itself acts on).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { classifyRefusal, parseRelayFailure, providerFailureKind, refusalCard, refusalCode, refusalKindOf, refusalSentence, relayFailure, transportFailure, REFUSAL_KINDS, REFUSAL_PREFIX } from '../lib/refusals.js'

/** The relay's `error_response(...)` body, as `pi-ai` prints it: `<status>: <inner error object>`. */
function relayLine(status, inner) {
  return `${status}: ${JSON.stringify(inner)}`
}

const GUIDANCE = {
  version: 1,
  region: 'cn',
  docs: 'https://docs.example/own-key',
  providers: [{ id: 'bailian', name: 'Alibaba Cloud Bailian', name_zh: '阿里云百炼', key_url: 'https://bailian.example/keys', auth: ['key'], covers: ['chat', 'vision', 'image', 'video'] }],
  plans: [{ id: 'chatgpt', provider: 'openai', name: 'ChatGPT', auth: 'oauth-chatgpt', clients: ['desktop', 'android', 'ios'], covers: ['chat', 'vision'] }],
  caveats: { chatgpt: 'OpenAI’s terms…', chatgpt_zh: 'OpenAI 的条款…' },
}

const EXHAUSTED = {
  message: 'The free allowance (¥10) is used up. Three ways on…',
  type: 'nanomuse_cloud',
  code: 'allowance_exhausted',
  left: 0,
  grant: 10,
  region: 'cn',
  ways: [],
  guidance: GUIDANCE,
  invite_url: 'https://relay.example/i/ABCDEF',
  invite_bonus_cny: 5,
  invitee_bonus_cny: 5,
  own_key_docs: 'https://docs.example/own-key',
  openrouter_url: 'https://openrouter.example/keys',
}

test('429 allowance_exhausted: the kind, the figures and the guidance as the relay sent it', () => {
  const r = parseRelayFailure(relayLine(429, EXHAUSTED), 'RATE_LIMIT')
  assert.ok(r)
  assert.equal(r.kind, 'exhausted')
  assert.equal(r.status, 429)
  assert.equal(r.code, 'allowance_exhausted')
  assert.equal(r.left, 0)
  assert.equal(r.grant, 10)
  assert.equal(r.inviteUrl, 'https://relay.example/i/ABCDEF')
  assert.equal(r.inviteBonusCny, 5)
  assert.equal(r.ownKeyDocs, 'https://docs.example/own-key')
  assert.deepEqual(r.guidance, GUIDANCE)
  assert.equal(r.message, EXHAUSTED.message)
})

test('the OpenAI envelope `{error: {...}}` and a trailing provider dump are read the same', () => {
  const wrapped = `429: ${JSON.stringify({ error: EXHAUSTED })}`
  assert.equal(parseRelayFailure(wrapped)?.kind, 'exhausted')
  const dumped = `${relayLine(429, EXHAUSTED)}\n{"raw":"provider metadata"}`
  assert.equal(parseRelayFailure(dumped)?.grant, 10)
  // a prefixed line, as `formatProviderError` prints it
  assert.equal(parseRelayFailure(`nanoMuse Cloud (429): ${JSON.stringify(EXHAUSTED)}`)?.kind, 'exhausted')
})

test('402 out_of_tokens (older relay) is the same card', () => {
  const r = parseRelayFailure(relayLine(402, { message: 'Out of tokens.', type: 'nanomuse_cloud', code: 'out_of_tokens' }), 'QUOTA')
  assert.equal(r?.kind, 'exhausted')
  assert.equal(r?.status, 402)
})

test('413: the relay’s too_large JSON and the proxy’s plain text both say "too large"', () => {
  const json = parseRelayFailure(relayLine(413, { message: 'Request body is 12.4 MB; this relay accepts up to 8 MB.', type: 'nanomuse_cloud', code: 'too_large' }), 'INVALID_REQUEST')
  assert.equal(json?.kind, 'too_large')
  assert.equal(json?.code, 'too_large')
  assert.match(json?.message ?? '', /12\.4 MB/)
  const plain = parseRelayFailure('413 Request too large', 'INVALID_REQUEST')
  assert.equal(plain?.kind, 'too_large')
  assert.equal(plain?.status, 413)
  assert.equal(plain?.code, 'http_413')
  assert.equal(plain?.message, 'Request too large')
  // the upstream's own words about the window, relayed as a 400
  assert.equal(classifyRefusal(400, 'upstream', "This model's maximum context length is 128000 tokens."), 'too_large')
})

test('400 content_rejected: the provider’s content check said no, as the relay’s code, as the provider’s own words on an own key, and as an older relay’s upstream_400', () => {
  const relay = { message: "The model provider's content check declined this request; try different words", type: 'upstream', code: 'content_rejected', upstream: '<400> InternalError.Algo.DataInspectionFailed: Input data may contain inappropriate content.' }
  const r = parseRelayFailure(relayLine(400, relay), 'INVALID_REQUEST')
  assert.equal(r?.kind, 'content_rejected')
  assert.equal(r?.code, 'content_rejected')
  // the stream's shape: pi-ai prints the inline error without a status; the host still rewrites the finish by the code
  assert.equal(classifyRefusal(0, 'content_rejected', relay.message), 'content_rejected')
  // an older relay passing Bailian's own line through as upstream_400
  assert.equal(classifyRefusal(400, 'upstream_400', '<400> InternalError.Algo.DataInspectionFailed: Input data may contain inappropriate content.'), 'content_rejected')
  // the same words on a key of one's own: the generic card says the same thing
  assert.equal(providerFailureKind('INVALID_REQUEST', '400 {"error":{"code":"data_inspection_failed","message":"Input data may contain inappropriate content."}}'), 'content_rejected')
  assert.equal(providerFailureKind('INVALID_REQUEST', '400 {"error":{"code":"invalid_parameter_error","message":"Model not exist."}}'), 'other')
  // the finish chunk: our code (never retried by the harness), our sentence, no JSON
  const out = relayFailure({ message: relayLine(400, relay), code: 'INVALID_REQUEST' })
  assert.equal(out?.failure.code, 'nanomuse/content_rejected')
  assert.equal(out?.failure.status, 400)
  assert.match(out?.failure.message ?? '', /content check declined/)
  assert.doesNotMatch(out?.failure.message ?? '', /[{}"]/)
  // the card: a new chat leaves the words behind; Try again is there, by choice
  assert.deepEqual(refusalCard('content_rejected').actions, ['new-chat', 'retry'])
  assert.equal(refusalCard('content_rejected').showRelayText, false)
})

test('401 bad_key: signed out; 403: disabled; 404 model_not_offered: model', () => {
  assert.equal(parseRelayFailure(relayLine(401, { message: 'Unknown or revoked key.', type: 'nanomuse_cloud', code: 'bad_key' }), 'AUTH')?.kind, 'signed_out')
  assert.equal(parseRelayFailure('401 Unauthorized', 'AUTH')?.kind, 'signed_out')
  assert.equal(parseRelayFailure(relayLine(403, { message: 'This account has been disabled.', code: 'account_disabled' }), 'AUTH')?.kind, 'disabled')
  assert.equal(parseRelayFailure(relayLine(404, { message: 'Model not offered.', code: 'model_not_offered' }))?.kind, 'model')
})

test('429 without the allowance code is "busy", with retry_after in milliseconds; daily_cap keeps its own card', () => {
  const r = parseRelayFailure(relayLine(429, { message: 'Too many requests in flight.', code: 'too_many_in_flight', retry_after: 2.5 }), 'RATE_LIMIT')
  assert.equal(r?.kind, 'busy')
  assert.equal(r?.retryAfterMs, 2500)
  assert.equal(parseRelayFailure(relayLine(429, { message: 'Rate limited.', code: 'rate_limited' }))?.kind, 'busy')
  assert.equal(parseRelayFailure(relayLine(429, { message: "Today's allowance is used up.", code: 'daily_cap' }))?.kind, 'daily_cap')
})

test('5xx: the relay (or its upstream) did not answer; a connection failure or timeout: unreachable', () => {
  assert.equal(parseRelayFailure(relayLine(502, { message: 'The model provider did not answer.', code: 'upstream' }), 'SERVER')?.kind, 'relay_down')
  assert.equal(parseRelayFailure('503 Service Unavailable', 'SERVER')?.kind, 'relay_down')
  assert.equal(parseRelayFailure('500 status code (no body)', 'SERVER')?.message, '')
  const timeout = parseRelayFailure('No chunk received for 60 s (idle timeout).', 'TIMEOUT')
  assert.equal(timeout?.kind, 'unreachable')
  assert.equal(timeout?.status, 0)
  assert.equal(parseRelayFailure('Connection error.', 'TRANSPORT')?.kind, 'unreachable')
  assert.equal(parseRelayFailure('fetch failed')?.kind, 'unreachable')
})

test('not a refusal: a model that answered and then said nothing, a code the harness handles itself', () => {
  assert.equal(parseRelayFailure('The model returned an empty response.', 'EMPTY_RESPONSE'), null)
  assert.equal(parseRelayFailure(''), null)
  assert.equal(relayFailure({ message: '413 Request too large', code: 'CONTEXT_WINDOW_EXCEEDED' }), null, 'compaction runs on CONTEXT_WINDOW_EXCEEDED first')
  assert.equal(relayFailure({ message: 'offload', code: 'IMAGE_OFFLOAD_REQUIRED' }), null)
})

test('the rewritten failure: our code (never retried), our sentence, the relay’s status and retry-after', () => {
  const out = relayFailure({ message: relayLine(429, EXHAUSTED), code: 'RATE_LIMIT', status: 429 })
  assert.ok(out)
  assert.equal(out.failure.code, 'nanomuse/exhausted')
  assert.equal(out.failure.status, 429)
  assert.doesNotMatch(out.failure.message, /[{}"]/, 'no JSON in the sentence')
  assert.match(out.failure.message, /allowance is used up/)
  assert.equal(out.refusal.kind, 'exhausted')
  // the harness retries EMPTY_RESPONSE, RATE_LIMIT, SERVER, TIMEOUT and TRANSPORT; ours is none of them
  for (const kind of ['exhausted', 'too_large', 'signed_out', 'busy', 'relay_down', 'unreachable']) {
    assert.ok(refusalCode(kind).startsWith(REFUSAL_PREFIX))
    assert.ok(!['EMPTY_RESPONSE', 'RATE_LIMIT', 'SERVER', 'TIMEOUT', 'TRANSPORT'].includes(refusalCode(kind)))
  }
  const busy = relayFailure({ message: relayLine(429, { message: 'Busy.', code: 'provider_busy', retry_after: 3 }), code: 'RATE_LIMIT' })
  assert.equal(busy?.failure.providerRetryAfterMs, 3000)
  const down = relayFailure({ message: 'Connection error.', code: 'TRANSPORT' })
  assert.equal(down?.failure.code, 'nanomuse/unreachable')
  assert.equal(down?.failure.status, undefined)
})

test('relay 0.22: the operator’s switches — the allowance paused (not spent) keeps the card, says paused, is not retried; service, sync and hub paused are one sentence each', () => {
  // the Free allowance switch: the exhausted shape plus two flags; what is left is not zero
  const paused = parseRelayFailure(relayLine(429, { ...EXHAUSTED, message: 'The free allowance is paused on this relay for now, so the shared models are not answering. …', paused: true, reason: 'allowance_paused', left: 7.5 }), 'RATE_LIMIT')
  assert.equal(paused.kind, 'allowance_paused')
  assert.equal(paused.paused, true)
  assert.equal(paused.left, 7.5)
  assert.deepEqual(paused.guidance, GUIDANCE)
  assert.match(refusalSentence(paused), /paused on this relay for now, not used up/)
  assert.doesNotMatch(refusalSentence(paused), /^The free allowance is used up/)
  assert.deepEqual(refusalCard('allowance_paused').actions, ['ways', 'retry'])
  const seen = relayFailure({ message: relayLine(429, { ...EXHAUSTED, paused: true, reason: 'allowance_paused' }), code: 'RATE_LIMIT' })
  assert.equal(seen.failure.code, 'nanomuse/allowance_paused')
  assert.equal(refusalKindOf(seen.failure.code), 'allowance_paused')
  // `paused: false` (or absent) is the spent pool as before
  assert.equal(parseRelayFailure(relayLine(429, { ...EXHAUSTED, paused: false }), 'RATE_LIMIT').kind, 'exhausted')
  assert.equal(classifyRefusal(429, 'allowance_exhausted', '', false), 'exhausted')

  // the Cloud service, Conversation sync and Device hub switches: 503 with the code, not "relay down"
  const service = parseRelayFailure(relayLine(503, { message: 'nanoMuse Cloud is paused by its operator for now; your sign-in and your data are kept. Try again later.', code: 'service_paused', paused: true }), 'SERVER')
  assert.equal(service.kind, 'service_paused')
  assert.equal(service.paused, true)
  assert.match(refusalSentence(service), /paused by its operator for now; your sign-in and your data are kept/)
  const sync = parseRelayFailure(relayLine(503, { message: 'Conversation sync is paused on this relay for now; …', code: 'sync_paused', paused: true }), 'SERVER')
  assert.equal(sync.kind, 'sync_paused')
  assert.match(refusalSentence(sync), /^Conversation sync is paused on this relay for now/)
  const hub = parseRelayFailure(relayLine(503, { message: 'The device hub is paused on this relay for now; each device keeps working on its own.', code: 'hub_paused', paused: true }), 'SERVER')
  assert.equal(hub.kind, 'hub_paused')
  assert.match(refusalSentence(hub), /^The device hub is paused on this relay for now/)
  for (const kind of ['service_paused', 'sync_paused', 'hub_paused']) {
    assert.deepEqual(refusalCard(kind), { actions: ['retry'], showRelayText: false }, kind)
    const rewritten = relayFailure({ message: relayLine(503, { message: 'x', code: kind, paused: true }), code: 'SERVER' })
    assert.equal(rewritten.failure.code, `nanomuse/${kind}`, kind) // not SERVER: the harness does not retry it
    assert.equal(rewritten.failure.status, 503)
  }
  // a 503 without one of those codes is still "the relay did not answer"
  assert.equal(parseRelayFailure(relayLine(503, { message: 'x', code: 'upstream_unconfigured' }), 'SERVER').kind, 'relay_down')
  // sign-ups closed (403 at sign-in) is read as a 403 with the relay's own sentence shown
  const closed = parseRelayFailure(relayLine(403, { message: 'New sign-ups are paused on this relay for now; existing accounts keep working. Try again later.', code: 'signup_closed' }), 'AUTH')
  assert.equal(closed.kind, 'disabled')
  assert.equal(refusalSentence(closed), 'New sign-ups are paused on this relay for now; existing accounts keep working. Try again later.')
})

test('the code round-trips to the kind for the client; anything else is not ours', () => {
  assert.equal(refusalKindOf('nanomuse/too_large'), 'too_large')
  assert.equal(refusalKindOf('nanomuse/nope'), undefined)
  assert.equal(refusalKindOf('RATE_LIMIT'), undefined)
  assert.equal(refusalKindOf(undefined), undefined)
})

test('each kind has one plain sentence — no status, no JSON — and the relay’s own words where they add', () => {
  for (const kind of REFUSAL_KINDS) {
    const text = refusalSentence({ kind, status: 429, code: 'x', message: '' })
    assert.ok(text.length > 10, kind)
    assert.doesNotMatch(text, /\b(?:401|413|429|5\d\d)\b|[{}]/, kind)
  }
  assert.equal(refusalSentence({ kind: 'disabled', status: 403, code: 'account_disabled', message: 'This account has been disabled.' }), 'This account has been disabled.')
  assert.equal(refusalSentence({ kind: 'other', status: 418, code: 'teapot', message: 'Short and stout.' }), 'Short and stout.')
})

test('the card plan: the ways on for the allowance, a new chat for too large, sign in for a retired key', () => {
  assert.deepEqual(refusalCard('exhausted').actions, ['ways', 'retry'])
  assert.deepEqual(refusalCard('too_large').actions, ['new-chat'])
  assert.deepEqual(refusalCard('signed_out').actions, ['sign-in'])
  assert.deepEqual(refusalCard('relay_down').actions, ['retry'])
  assert.equal(refusalCard('daily_cap').showRelayText, true)
  assert.equal(refusalCard('exhausted').showRelayText, false)
})

test('another provider’s failure (an own key): the harness’s routing code picks the sentence', () => {
  assert.equal(providerFailureKind('AUTH', ''), 'auth')
  assert.equal(providerFailureKind('QUOTA', ''), 'quota')
  assert.equal(providerFailureKind('CONTEXT_WINDOW_EXCEEDED', ''), 'too_large')
  assert.equal(providerFailureKind('INVALID_REQUEST', '413 Payload Too Large'), 'too_large')
  assert.equal(providerFailureKind('RATE_LIMIT', ''), 'busy')
  assert.equal(providerFailureKind('SERVER', ''), 'server')
  assert.equal(providerFailureKind('TIMEOUT', ''), 'unreachable')
  assert.equal(providerFailureKind('PI_AI_ERROR', 'something else'), 'other')
})

test('the wire, not a refusal: a deadline passed is a timeout, a connection that never came together is unreachable', () => {
  const timeout = Object.assign(new Error('The operation was aborted due to timeout'), { name: 'TimeoutError' })
  assert.equal(transportFailure(timeout), 'timeout')
  const refused = Object.assign(new TypeError('fetch failed'), { cause: Object.assign(new Error('connect ECONNREFUSED 127.0.0.1:443'), { code: 'ECONNREFUSED' }) })
  assert.equal(transportFailure(refused), 'unreachable')
  const dns = Object.assign(new TypeError('fetch failed'), { cause: { code: 'ENOTFOUND' } })
  assert.equal(transportFailure(dns), 'unreachable')
  assert.equal(transportFailure(new Error('socket hang up')), 'unreachable')
  assert.equal(transportFailure(new Error('request timed out after 30s')), 'timeout')
  assert.equal(transportFailure(new Error('ENOENT: no such file')), undefined)
  assert.equal(transportFailure(new Error('model not found')), undefined)
  assert.equal(transportFailure(undefined), undefined)
  assert.equal(transportFailure('fetch failed'), undefined)
})
