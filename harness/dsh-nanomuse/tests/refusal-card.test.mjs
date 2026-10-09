// The card under a refused turn, drawn from what the host left in the node (C12): the chat's
// `turn-error` seat bundled on the fly (the browser half's React, the harness's primitives
// stubbed) and rendered to markup, in English and in Chinese. No status, no JSON reaches the
// person; the actions are the ones the brief names.
import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { relayFailure } from '../lib/refusals.js'

const here = fileURLToPath(new URL('.', import.meta.url))
let dir
let bundle

/** The harness's primitives, as far as the card's imports reach: plain elements. */
const PRIMITIVES = `
import { createElement as h } from 'react'
export const Button = ({ children, ...p }) => h('button', { type: 'button', ...p }, children)
export const Input = (p) => h('input', p)
export const Switch = (p) => h('input', { type: 'checkbox', ...p })
`

/** One self-contained bundle: the seat, the dictionaries, React and its server renderer, so the markup comes from one React. */
const ENTRY = `
import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
export { en, zh, fill } from './src/client/locales.ts'
import { makeTurnError } from './src/client/RefusalCard.tsx'
export function renderCard(t, deps, node) {
  const TurnError = makeTurnError(t, deps)
  return renderToStaticMarkup(h(TurnError, { node, sessionId: 's1' }))
}
`

before(async () => {
  dir = await mkdtemp(join(tmpdir(), 'nm-refusal-card-'))
  await build({
    stdin: { contents: ENTRY, resolveDir: join(here, '..'), loader: 'js', sourcefile: 'card-entry.js' },
    outfile: join(dir, 'card.mjs'),
    format: 'esm',
    platform: 'node',
    target: 'node22',
    bundle: true,
    jsx: 'automatic',
    logLevel: 'silent',
    define: { 'process.env.NODE_ENV': '"production"' },
    // the server renderer requires Node built-ins by name; an ESM bundle needs a `require` for that
    banner: { js: "import { createRequire as __nmCreateRequire } from 'node:module'; const require = __nmCreateRequire(import.meta.url);" },
    plugins: [{
      name: 'stub-harness',
      setup(b) {
        b.onResolve({ filter: /^@deepseek-ai\// }, (args) => ({ path: args.path, namespace: 'stub' }))
        b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({ contents: PRIMITIVES, loader: 'js', resolveDir: join(here, '..') }))
      },
    }],
  })
  bundle = await import(pathToFileURL(join(dir, 'card.mjs')).href)
})

after(async () => {
  if (dir) await rm(dir, { recursive: true, force: true })
})

/** `t` as the harness binds it for our namespace, over one dictionary. */
function translator(lang) {
  const dict = bundle[lang]
  return (key, values) => {
    const text = dict[key]
    assert.ok(typeof text === 'string', `${lang}: no string for ${key}`)
    return values ? bundle.fill(text, values) : text
  }
}

/** The node the harness builds from the finish chunk the host rewrote. */
function nodeFor(status, inner, dshCode) {
  const line = `${status}: ${JSON.stringify(inner)}`
  const out = relayFailure({ message: line, code: dshCode, status })
  assert.ok(out, 'a refusal')
  return { kind: 'turn-error', key: 'turn-error:1', seq: 1, data: { message: out.failure.message, code: out.failure.code, turn: 1 } }
}

const deps = { retry: async () => undefined, newChat: () => undefined }

function render(lang, node) {
  return bundle.renderCard(translator(lang), deps, node)
}

const EXHAUSTED = { message: 'The free allowance (¥10) is used up.', type: 'nanomuse_cloud', code: 'allowance_exhausted', left: 0, grant: 10, guidance: { region: 'cn', providers: [], plans: [{ name: 'ChatGPT' }] }, invite_url: 'https://relay.example/i/X', invite_bonus_cny: 5 }

test('429 allowance_exhausted: the allowance card — lead, the three ways, Try again; no wire', () => {
  const en = render('en', nodeFor(429, EXHAUSTED, 'RATE_LIMIT'))
  assert.match(en, /data-kind="exhausted"/)
  assert.match(en, /The free allowance is used up\./)
  assert.match(en, /Three ways on/)
  assert.match(en, /Use your own model key/)
  assert.match(en, /Sign in with a plan you already pay for/)
  assert.match(en, /Invite a friend/)
  assert.match(en, /Open Settings → nanoMuse Cloud/)
  assert.match(en, /Step-by-step guide/)
  assert.match(en, />Try again</)
  assert.doesNotMatch(en, /429|allowance_exhausted|nanomuse_cloud|[{}]/)
  const zh = render('zh', nodeFor(429, EXHAUSTED, 'RATE_LIMIT'))
  assert.match(zh, /免费额度已用完。/)
  assert.match(zh, /三个办法继续用/)
  assert.match(zh, />再试一次</)
  assert.doesNotMatch(zh, /429|[{}]/)
})

test('413: one sentence and New chat, whether the relay sent JSON or the proxy plain text', () => {
  const json = render('en', nodeFor(413, { message: 'Request body is 12.4 MB; this relay accepts up to 8 MB.', code: 'too_large' }, 'INVALID_REQUEST'))
  assert.match(json, /data-kind="too_large"/)
  assert.match(json, /too large for the model’s window/)
  assert.match(json, />New chat</)
  assert.doesNotMatch(json, /413|12\.4 MB|Try again/)
  const plain = relayFailure({ message: '413 Request too large', code: 'INVALID_REQUEST' })
  const markup = render('zh', { kind: 'turn-error', data: { message: plain.failure.message, code: plain.failure.code, turn: 2 } })
  assert.match(markup, /超过了模型的窗口/)
  assert.match(markup, />新聊天</)
  assert.doesNotMatch(markup, /413/)
})

test('400 content_rejected: one sentence, New chat and Try again, the provider’s line kept out', () => {
  const relay = { message: "The model provider's content check declined this request; try different words", type: 'upstream', code: 'content_rejected', upstream: '<400> InternalError.Algo.DataInspectionFailed: Input data may contain inappropriate content.' }
  const en = render('en', nodeFor(400, relay, 'INVALID_REQUEST'))
  assert.match(en, /data-kind="content_rejected"/)
  assert.match(en, /content check declined this request/)
  assert.match(en, />New chat</)
  assert.match(en, />Try again</)
  assert.doesNotMatch(en, /400|DataInspectionFailed|[{}]/)
  const zh = render('zh', nodeFor(400, relay, 'INVALID_REQUEST'))
  assert.match(zh, /内容审核没有放行/)
  assert.match(zh, />新聊天</)
})

test('401: the sign-in expired — one sentence and Sign in; 5xx and a timeout: the relay did not answer — Try again', () => {
  const signedOut = render('en', nodeFor(401, { message: 'Unknown or revoked key.', code: 'bad_key' }, 'AUTH'))
  assert.match(signedOut, /This sign-in is no longer valid/)
  assert.match(signedOut, />Sign in</)
  assert.doesNotMatch(signedOut, /401|bad_key/)
  const down = render('en', nodeFor(502, { message: 'The model provider did not answer.', code: 'upstream' }, 'SERVER'))
  assert.match(down, /nanoMuse Cloud did not answer/)
  assert.match(down, />Try again</)
  const timeout = relayFailure({ message: 'No chunk received for 60 s (idle timeout).', code: 'TIMEOUT' })
  const unreachable = render('zh', { kind: 'turn-error', data: { message: timeout.failure.message, code: timeout.failure.code } })
  assert.match(unreachable, /连不上 nanoMuse Cloud/)
})

test('daily_cap and an account the relay disabled keep the relay’s own sentence under ours', () => {
  const cap = render('en', nodeFor(429, { message: "Today's allowance is used up. It resets at midnight UTC.", code: 'daily_cap' }, 'RATE_LIMIT'))
  assert.match(cap, /Today’s share of the allowance is used up/)
  assert.match(cap, /The relay said: Today&#x27;s allowance is used up\. It resets at midnight UTC\./)
  const disabled = render('en', nodeFor(403, { message: 'This account has been disabled.', code: 'account_disabled' }, 'AUTH'))
  assert.match(disabled, /This account cannot use nanoMuse Cloud right now/)
  assert.match(disabled, />Open Settings → nanoMuse Cloud</)
})

test('relay 0.22: the allowance paused by the operator — the same card, saying paused rather than used up; service, sync and hub paused — one sentence and Try again', () => {
  const paused = render('en', nodeFor(429, { ...EXHAUSTED, message: 'The free allowance is paused on this relay for now, so the shared models are not answering.', paused: true, reason: 'allowance_paused', left: 7.5 }, 'RATE_LIMIT'))
  assert.match(paused, /data-kind="allowance_paused"/)
  assert.match(paused, /The free allowance is paused on this relay for now, not used up\./)
  assert.doesNotMatch(paused, /The free allowance is used up\./)
  assert.match(paused, /Three ways on/)
  assert.match(paused, /Use your own model key/)
  assert.match(paused, />Try again</)
  assert.doesNotMatch(paused, /429|allowance_exhausted|reason|[{}]/)
  const pausedZh = render('zh', nodeFor(429, { ...EXHAUSTED, paused: true, reason: 'allowance_paused' }, 'RATE_LIMIT'))
  assert.match(pausedZh, /暂时停发了免费额度，不是用完了/)
  assert.doesNotMatch(pausedZh, /免费额度已用完。/)

  const service = render('en', nodeFor(503, { message: 'nanoMuse Cloud is paused by its operator for now; your sign-in and your data are kept. Try again later.', code: 'service_paused', paused: true }, 'SERVER'))
  assert.match(service, /data-kind="service_paused"/)
  assert.match(service, /nanoMuse Cloud is paused by its operator for now; your sign-in and your data are kept\./)
  assert.match(service, />Try again</)
  assert.doesNotMatch(service, /503|did not answer|The relay said/)
  const sync = render('zh', nodeFor(503, { message: 'Conversation sync is paused …', code: 'sync_paused', paused: true }, 'SERVER'))
  assert.match(sync, /暂时停止了对话同步/)
  assert.match(sync, />再试一次</)
  const hub = render('en', nodeFor(503, { message: 'The device hub is paused …', code: 'hub_paused', paused: true }, 'SERVER'))
  assert.match(hub, /The device hub is paused on this relay for now; each device keeps working on its own\./)
  assert.match(hub, />Try again</)
})

test('another provider’s failure (an own key): a plain sentence by the harness code, the raw text folded away', () => {
  const auth = render('en', { kind: 'turn-error', data: { message: '401: {"error":{"message":"Incorrect API key provided"}}', code: 'AUTH' } })
  assert.match(auth, /data-kind="provider-auth"/)
  assert.match(auth, /The provider did not accept the key/)
  assert.match(auth, /<details/)
  assert.match(auth, /<summary[^>]*>What came back</)
  assert.match(auth, />Open Settings → nanoMuse Cloud</)
  const quiet = render('zh', { kind: 'turn-error', data: { message: 'The model returned an empty response.', code: 'EMPTY_RESPONSE' } })
  assert.match(quiet, /模型这次没有回答。/)
  assert.match(quiet, />再试一次</)
  // *Use nanoMuse Cloud this time* (0.1.41) needs a signed-in account: the live state here says signed out, so no button; the strings exist in both dictionaries
  assert.doesNotMatch(auth, /nm-rf-cloud-once/)
  assert.equal(bundle.en.rfUseCloudOnce, 'Use nanoMuse Cloud this time')
  assert.equal(bundle.zh.rfUseCloudOnce, '这次改用 nanoMuse Cloud')
})

test('every key the card reads exists in both dictionaries', () => {
  const en = Object.keys(bundle.en)
  const zh = Object.keys(bundle.zh)
  assert.deepEqual(zh.filter((k) => !en.includes(k)), [])
  assert.deepEqual(en.filter((k) => !zh.includes(k)), [])
  for (const key of ['awExhausted', 'awThreeWays', 'rfTooLarge', 'rfSignedOut', 'rfRetry', 'rfNewChat', 'huText', 'huSee']) assert.ok(en.includes(key), key)
})
