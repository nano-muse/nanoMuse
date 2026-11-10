// The host's half of own keys with capabilities (C11), through `NanomuseCloud` itself: the
// capability rule over the account, the rows and the ChatGPT sign-in; `GET /providers` for the
// "ways on" (grouped by region the way the browser half's `groupsOf` does); a key saved by name
// only; a removed row taking the choices that pointed at it. No Electron, no relay, no network:
// a cordis-shaped context with in-memory credentials and settings, a loopback server standing in
// for the provider's `/models`, and the runtime pointed at a path that does not exist.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Readable } from 'node:stream'
import { Service } from '@deepseek-ai/cordis'
import NanomuseCloud, { API_PREFIX, LLM_ROW, PROVIDER_ID, STOCK_DEFAULT_MODEL, TOKEN_REF } from '../lib/cloud.js'
import { CHATGPT_KEY_REF, CHATGPT_PROVIDER, waysOn } from '../lib/providers.js'

// no bundled runtime here: the ChatGPT row says so instead of spawning anything
process.env.NANOMUSE_PY = join(tmpdir(), 'nanomuse-runtime-that-does-not-exist')

/** The slice of a dsh Context the cloud service touches, kept in memory. */
function fakeContext({ defaultModel } = {}) {
  const credentials = new Map()
  const listeners = new Map()
  const settings = { [LLM_ROW]: { providers: {} } }
  const selection = { current: defaultModel ?? { provider: 'deepseek-official', model: 'deepseek-chat' } }
  const ctx = {
    reflect: { provide() {} },
    logger: { info() {}, warn() {}, debug() {}, error() {} },
    credentials: {
      async set(ref, value) { credentials.set(String(ref), value) },
      async resolve(ref) { return credentials.has(String(ref)) ? { value: credentials.get(String(ref)) } : undefined },
      async unset(ref) { credentials.delete(String(ref)) },
    },
    settings: {
      async update(ns, patch) {
        const row = settings[ns] ?? (settings[ns] = {})
        for (const [k, v] of Object.entries(patch)) row[k] = k === 'providers' ? { ...row.providers, ...v } : v
      },
      async mutate(ns, ops) {
        for (const op of ops) if (op.op === 'unset' && op.path[0] === 'providers') delete settings[ns].providers[op.path[1]]
      },
      describe() { return Object.entries(settings).map(([ns, value]) => ({ ns, value })) },
    },
    get(name) {
      if (name === 'agentDefaultModel') return { currentSelection: () => selection.current, saveSelection: async (next) => { selection.current = next } }
      if (name === 'llm') return { listProviders: () => Object.keys(settings[LLM_ROW].providers).map((id) => ({ id })) }
      return undefined
    },
    inject() { /* the session API, the web server, the connectors: not in these tests */ },
    effect(fn) { fn() },
    on(name, callback) {
      const callbacks = listeners.get(name) ?? new Set()
      callbacks.add(callback)
      listeners.set(name, callbacks)
      return () => callbacks.delete(callback)
    },
  }
  return { ctx, credentials, settings, selection, emit: (name, ...args) => { for (const callback of listeners.get(name) ?? []) callback(...args) } }
}

/** A provider's `/models`, OpenAI's shape, on the loopback. */
function modelsServer(ids) {
  const server = createServer((req, res) => {
    if (req.url?.endsWith('/models')) {
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ data: ids.map((id) => (typeof id === 'string' ? { id } : id)) }))
    } else {
      res.writeHead(404).end()
    }
  })
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve({ url: `http://127.0.0.1:${server.address().port}/v1`, close: () => new Promise((r) => server.close(r)) })))
}

const ACCOUNT_MODELS = [
  { id: 'deepseek-v4.1-flash', name: 'DeepSeek V4.1 Flash', kind: 'chat', for: ['chat'], recommended: true },
  { id: 'qwen3.8-27b', name: 'Qwen 3.8 27B', kind: 'chat', for: ['gui'] },
  { id: 'qwen-image-3.0', name: 'Qwen Image', kind: 'image' },
  { id: 'wan2.2-i2v-flash', name: 'Wan', kind: 'video' },
]

/** A cloud service in a fresh home; `signedIn` writes an account snapshot and its key first. */
async function cloud({ signedIn = false, defaultModel } = {}) {
  const home = await mkdtemp(join(tmpdir(), 'nm-cloud-'))
  const statePath = join(home, 'cloud.json')
  const fake = fakeContext({ defaultModel })
  // `update.checkedAt` of now: the daily update check (the network) is not due during the test
  if (signedIn) {
    await fake.ctx.credentials.set(TOKEN_REF, 'account-key')
    await writeFile(statePath, JSON.stringify({ account: { id: 'acct-1', channel: 'email', hint: 'a***@example.org', member: false, region: 'intl' }, models: ACCOUNT_MODELS, update: { checkedAt: Date.now() } }))
  } else {
    await writeFile(statePath, JSON.stringify({ update: { checkedAt: Date.now() } }))
  }
  const svc = new NanomuseCloud(fake.ctx, { baseURL: 'https://relay.invalid', deviceName: 'test-desktop', statePath })
  // the hub and the account refresh would reach the relay: not here
  svc.hub.start = () => undefined
  svc.refresh = async () => svc.status()
  await svc[Service.init]()
  const api = async (method, route, body) => {
    const req = Readable.from(body === undefined ? [] : [Buffer.from(JSON.stringify(body))])
    req.method = method
    req.url = `${API_PREFIX}${route}`
    req.headers = {}
    const res = { status: 0, body: undefined, writeHead(status) { res.status = status; return res }, end(text) { res.body = text ? JSON.parse(text) : undefined; return res } }
    await svc.handle(req, res)
    return res
  }
  const state = async () => JSON.parse(await readFile(statePath, 'utf8'))
  return { svc, api, state, statePath, home, ...fake, done: () => rm(home, { recursive: true, force: true }) }
}

test('the rule: nothing configured has nothing; the account brings what the relay lists; a row adds its coverage; the ChatGPT sign-in is chat and vision only', async () => {
  const out = await cloud()
  try {
    assert.deepEqual(out.svc.capabilities(), [])
    const view = await out.svc.providersView('en')
    assert.equal(view.cloud.signedIn, false)
    assert.deepEqual(view.configured, [])
    assert.equal(view.chatgpt.signedIn, false)
    assert.equal(view.chatgpt.runtime, false)
    // the ChatGPT proxy came up (the runtime's `ready`): a `chatgpt` row with chat and vision, never image or video
    await out.svc.chatGptReady('http://127.0.0.1:41235/v1', 'local-token', ['gpt-5.6-sol', 'gpt-5.4'])
    assert.deepEqual(out.svc.capabilities(), ['chat', 'vision'])
    const after = await out.svc.providersView('en')
    assert.equal(after.chatgpt.signedIn, true)
    assert.deepEqual(after.configured.map((p) => [p.provider, p.keyRef, p.capabilities]), [[CHATGPT_PROVIDER, CHATGPT_KEY_REF, ['chat', 'vision']]])
    assert.equal(out.credentials.get(CHATGPT_KEY_REF), 'local-token')
    assert.equal(out.settings[LLM_ROW].providers.chatgpt.apiKeyEnv, CHATGPT_KEY_REF)
    assert.ok(!JSON.stringify(out.settings).includes('local-token'))
    assert.ok(!(await readFile(out.statePath, 'utf8')).includes('local-token'))
    // the live state carries the sign-in for the row (and a host restart reads `chatgpt` back from cloud.json)
    const live = out.svc.live()
    assert.equal(live.ownKeys.chatgpt.signedIn, true)
    assert.equal(live.ownKeys.count, 1)
    assert.deepEqual(live.ownKeys.capabilities, ['chat', 'vision'])
    assert.equal((await out.state()).chatgpt.label, 'ChatGPT')
    // the hands may use it, new chats answer through it (the stock DeepSeek row had no key)
    assert.deepEqual(out.svc.handsOptions().map((o) => [o.provider, o.id]), [['chatgpt', 'gpt-5.6-sol'], ['chatgpt', 'gpt-5.4']])
    assert.equal(out.selection.current.provider, 'chatgpt')
    // pictures and clips: not through the sign-in
    const media = await out.svc.media()
    assert.equal(media.image.reason, 'no_image')
    assert.equal(media.video.reason, 'no_video')
  } finally {
    await out.done()
  }
})

test('signed in, the account counts: its chat, gui, image and video models are the four capabilities; the view says so and the pickers list the account first', async () => {
  const out = await cloud({ signedIn: true })
  try {
    assert.equal(out.svc.signedIn, true)
    assert.deepEqual(out.svc.capabilities(), ['chat', 'vision', 'image', 'video'])
    const view = await out.svc.providersView('zh')
    assert.equal(view.cloud.signedIn, true)
    assert.deepEqual(view.cloud.capabilities, ['chat', 'vision', 'image', 'video'])
    // the relay's word on the region wins over the UI language
    assert.equal(view.region, 'global')
    assert.deepEqual(view.hands, { provider: PROVIDER_ID, model: 'qwen3.8-27b' })
    assert.deepEqual(out.svc.chatOptions().map((o) => [o.provider, o.id]), [[PROVIDER_ID, 'deepseek-v4.1-flash']])
    assert.deepEqual(out.svc.handsOptions().map((o) => [o.provider, o.id]), [[PROVIDER_ID, 'qwen3.8-27b']])
    const media = await out.svc.media()
    assert.equal(media.image.source, 'cloud')
    assert.equal(media.video.source, 'cloud')
  } finally {
    await out.done()
  }
})

test('GET /providers: the catalogue grouped by region — Bailian first in mainland China, OpenRouter then OpenAI elsewhere — the same groups the browser half shows', async () => {
  const out = await cloud()
  try {
    const cn = await out.api('GET', '/providers?lang=zh')
    assert.equal(cn.status, 200)
    assert.equal(cn.body.region, 'cn')
    assert.ok(cn.body.catalogue.length >= 15)
    const cnGroups = waysOn(cn.body.catalogue, cn.body.region)
    assert.deepEqual(cnGroups.first.map((p) => p.id), ['bailian'])
    assert.deepEqual(cnGroups.local.map((p) => p.id), ['ollama', 'lm-studio', 'vllm'])
    assert.equal(cnGroups.custom.id, 'custom')
    const en = await out.api('GET', '/providers?lang=en')
    assert.equal(en.body.region, 'global')
    const enGroups = waysOn(en.body.catalogue, en.body.region)
    assert.deepEqual(enGroups.first.map((p) => p.id), ['openrouter', 'openai'])
    assert.ok(!enGroups.rest.some((p) => p.id === 'bailian'))
    // the view's shape, as the browser half reads it
    for (const key of ['region', 'catalogue', 'configured', 'capabilities', 'cloud', 'chatgpt', 'hands', 'chat']) assert.ok(key in en.body, key)
    assert.deepEqual(Object.keys(en.body.chatgpt).sort(), ['label', 'login', 'proxy', 'runtime', 'signedIn'])
    assert.deepEqual(en.body.chatgpt.login, { status: 'idle', url: '', label: '', error: '' })
    // the pickers' lists
    const models = await out.api('GET', '/providers/models?cap=vision')
    assert.deepEqual(models.body, { options: [] })
    assert.equal((await out.api('GET', '/providers/models?cap=nope')).status, 400)
    // the sign-in without a runtime: the row's error, not a crash
    const login = await out.api('POST', '/chatgpt/login', {})
    assert.equal(login.status, 500)
    assert.equal(login.body.error.message, 'no_runtime')
    assert.equal(out.svc.live().ownKeys.chatgpt.login.error, 'no_runtime')
  } finally {
    await out.done()
  }
})

test('POST /providers/save: the key goes to the credential store under its name; cloud.json and the model row carry the name only; the models the endpoint lists are sorted by kind', async () => {
  const out = await cloud()
  const server = await modelsServer(['qwen3.8-27b', 'deepseek-v4.1-flash', 'qwen-image-3.0', 'wan2.2-i2v-flash'])
  try {
    const bad = await out.api('POST', '/providers/save', { id: 'bailian', apiKey: '' })
    assert.equal(bad.status, 400)
    assert.equal(bad.body.error.code, 'no_key')
    assert.equal((await out.api('POST', '/providers/save', { id: 'nobody', apiKey: 'sk-x' })).status, 404)
    // an address with user:pass@ would be kept and shown as typed: refused with the reason, nothing written
    const userinfo = await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-x', baseURL: server.url.replace('://', '://user:pass@') })
    assert.equal(userinfo.status, 400)
    assert.equal(userinfo.body.error.code, 'url_userinfo')
    assert.match(userinfo.body.error.message, /user name or password/)
    const saved = await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-secret-1234', baseURL: server.url, lang: 'zh' })
    assert.equal(saved.status, 200)
    assert.equal(saved.body.provider, 'bailian')
    assert.equal(saved.body.keyRef, 'NANOMUSE_KEY_BAILIAN')
    assert.equal(saved.body.label, '阿里云百炼')
    assert.deepEqual(saved.body.capabilities, ['chat', 'vision', 'image', 'video'])
    assert.deepEqual(saved.body.models.map((m) => [m.id, m.kind, m.vision]), [['deepseek-v4.1-flash', 'chat', false], ['qwen-image-3.0', 'image', false], ['qwen3.8-27b', 'chat', true], ['wan2.2-i2v-flash', 'video', false]])
    assert.ok(!JSON.stringify(saved.body).includes('sk-secret'))
    // where the key is, and where it is not
    assert.equal(out.credentials.get('NANOMUSE_KEY_BAILIAN'), 'sk-secret-1234')
    const text = await readFile(out.statePath, 'utf8')
    assert.ok(!text.includes('sk-secret'))
    const state = await out.state()
    assert.equal(state.providers.bailian.keyRef, 'NANOMUSE_KEY_BAILIAN')
    assert.equal(state.providers.bailian.baseURL, server.url)
    const row = out.settings[LLM_ROW].providers.bailian
    assert.equal(row.apiKeyEnv, 'NANOMUSE_KEY_BAILIAN')
    assert.equal(row.apiKey, undefined)
    assert.deepEqual(row.models.map((m) => m.id), ['deepseek-v4.1-flash', 'qwen3.8-27b'])
    // the rule, now: everything, from one key
    assert.deepEqual(out.svc.capabilities(), ['chat', 'vision', 'image', 'video'])
    assert.equal((await out.svc.media()).image.source, 'provider')
    // the pickers: only the sighted model for the hands, both chat models for the chat
    assert.deepEqual(out.svc.handsOptions().map((o) => [o.provider, o.id]), [['bailian', 'qwen3.8-27b']])
    assert.deepEqual(out.svc.chatOptions().map((o) => o.id), ['deepseek-v4.1-flash', 'qwen3.8-27b'])
    // new chats answer through it (the stock DeepSeek default had no key); the catalogue's chat default is picked
    assert.deepEqual(out.selection.current, { provider: 'bailian', model: 'deepseek-v4.1-flash' })
    // the hands model from the row, by the route the picker uses; hands.json carries the row's key for the runtime
    const picked = await out.api('POST', '/hands-model', { model: 'qwen3.8-27b', provider: 'bailian' })
    assert.deepEqual(picked.body, { provider: 'bailian', model: 'qwen3.8-27b' })
    const hands = JSON.parse(await readFile(join(out.home, 'hands.json'), 'utf8'))
    assert.equal(hands.model, 'qwen3.8-27b')
    assert.equal(hands.base_url, server.url)
    assert.equal((await out.api('POST', '/hands-model', { model: 'deepseek-v4.1-flash', provider: 'bailian' })).status, 400)
    // a second save of the same provider replaces the row and the key, never doubles it
    const again = await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-second', baseURL: server.url })
    assert.equal(again.status, 200)
    assert.equal(out.credentials.get('NANOMUSE_KEY_BAILIAN'), 'sk-second')
    assert.equal(Object.keys((await out.state()).providers).length, 1)
  } finally {
    await server.close()
    await out.done()
  }
})

test('POST /providers/remove: the row, its credential and the choices that pointed at it go; the sign-in rows cannot be written with a key', async () => {
  const out = await cloud()
  const server = await modelsServer(['qwen3.8-27b', 'deepseek-v4.1-flash'])
  try {
    await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-secret', baseURL: server.url })
    await out.api('POST', '/hands-model', { model: 'qwen3.8-27b', provider: 'bailian' })
    assert.equal((await out.state()).handsProvider, 'bailian')
    assert.equal((await out.api('POST', '/providers/remove', { id: 'nobody' })).status, 404)
    const removed = await out.api('POST', '/providers/remove', { id: 'bailian' })
    assert.equal(removed.status, 200)
    assert.deepEqual(removed.body, { cloudModelsOn: false }, 'the account was never switched off, so nothing to say')
    const state = await out.state()
    assert.equal(state.providers.bailian, undefined)
    assert.equal(state.handsProvider, undefined)
    assert.equal(state.handsModel, undefined)
    assert.equal(out.credentials.has('NANOMUSE_KEY_BAILIAN'), false)
    assert.equal(out.settings[LLM_ROW].providers.bailian, undefined)
    assert.deepEqual(out.svc.handsChoice(), { provider: '', model: '' })
    assert.deepEqual(out.svc.capabilities(), [])
    await assert.rejects(readFile(join(out.home, 'hands.json')))
    // the `chatgpt` and `nanomuse` rows come from a sign-in, not from this route
    for (const id of [CHATGPT_PROVIDER, PROVIDER_ID]) {
      const refused = await out.api('POST', '/providers/save', { id, apiKey: 'sk-x' })
      assert.equal(refused.status, 400)
      assert.equal(refused.body.error.code, 'bad_provider')
    }
  } finally {
    await server.close()
    await out.done()
  }
})

test('the thinking level for an own key: the saved row declares the vendor’s documented levels per model, OpenRouter’s from its list; a row saved before the catalogue knew them gets them at the next start', async () => {
  const out = await cloud()
  const deepseek = await modelsServer(['deepseek-flash', 'deepseek-v4-pro'])
  const openrouter = await modelsServer([
    { id: 'z-ai/glm-5.3', reasoning: { default_effort: 'max', default_enabled: true, mandatory: true, supported_efforts: ['max', 'high', 'low'] } },
    { id: 'unbiased/pareto-26.10-preview' },
  ])
  try {
    await out.api('POST', '/providers/save', { id: 'deepseek', apiKey: 'sk-secret', baseURL: deepseek.url })
    const row = out.settings[LLM_ROW].providers.deepseek
    assert.deepEqual(row.models.map((m) => [m.id, m.reasoningEfforts, m.compat]), [
      ['deepseek-flash', { low: 'low', high: 'high', max: 'max' }, { thinkingFormat: 'deepseek', supportsReasoningEffort: true }],
      ['deepseek-v4-pro', { low: 'low', high: 'high', max: 'max' }, { thinkingFormat: 'deepseek', supportsReasoningEffort: true }],
    ])
    // never `off`: with no level picked nothing is sent, which is the vendor's default
    assert.ok(row.models.every((m) => !('off' in m.reasoningEfforts)))
    // OpenRouter: the levels its own list gives, kept in cloud.json so a restart can write them again
    await out.api('POST', '/providers/save', { id: 'openrouter', apiKey: 'sk-or', baseURL: openrouter.url, models: 'z-ai/glm-5.3' })
    const or = out.settings[LLM_ROW].providers.openrouter
    assert.deepEqual(or.models.map((m) => [m.id, m.reasoningEfforts, m.compat]), [
      ['z-ai/glm-5.3', { low: 'low', high: 'high', max: 'max' }, { thinkingFormat: 'openrouter' }],
      ['unbiased/pareto-26.10-preview', undefined, undefined],
    ])
    assert.deepEqual((await out.state()).providers.openrouter.models[0].reasoning, { levels: ['low', 'high', 'max'], default: 'max' })
    // a key saved by an older build: the adapter's row has no levels; the next start writes them
    const stale = JSON.parse(JSON.stringify(out.settings[LLM_ROW].providers))
    for (const p of Object.values(stale)) for (const m of p.models) { delete m.reasoningEfforts; delete m.compat }
    const fake = fakeContext()
    fake.settings[LLM_ROW].providers = stale
    const again = new NanomuseCloud(fake.ctx, { baseURL: 'https://relay.invalid', deviceName: 'test-desktop', statePath: out.statePath })
    again.hub.start = () => undefined
    again.refresh = async () => again.status()
    await again[Service.init]()
    await new Promise((r) => setTimeout(r, 20))
    assert.deepEqual(fake.settings[LLM_ROW].providers.deepseek.models[0].reasoningEfforts, { low: 'low', high: 'high', max: 'max' })
    assert.deepEqual(fake.settings[LLM_ROW].providers.openrouter.models[0].compat, { thinkingFormat: 'openrouter' })
    assert.equal(fake.settings[LLM_ROW].providers.openrouter.models[1].reasoningEfforts, undefined)
  } finally {
    await deepseek.close()
    await openrouter.close()
    await out.done()
  }
})

test('the chosen hands model falls back when its row goes: an own sighted model while signed out, the account’s gui model while signed in', async () => {
  const out = await cloud({ signedIn: true })
  const server = await modelsServer(['qwen3.8-27b'])
  try {
    await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-secret', baseURL: server.url })
    // the account's model stays the default; the own one is offered next to it
    assert.deepEqual(out.svc.handsOptions().map((o) => [o.provider, o.id]), [[PROVIDER_ID, 'qwen3.8-27b'], ['bailian', 'qwen3.8-27b']])
    await out.api('POST', '/hands-model', { model: 'qwen3.8-27b', provider: 'bailian' })
    assert.deepEqual(out.svc.handsChoice(), { provider: 'bailian', model: 'qwen3.8-27b' })
    await out.api('POST', '/providers/remove', { id: 'bailian' })
    assert.deepEqual(out.svc.handsChoice(), { provider: PROVIDER_ID, model: 'qwen3.8-27b' })
    // the account keeps the rule's four even with the row gone
    assert.deepEqual(out.svc.capabilities(), ['chat', 'vision', 'image', 'video'])
  } finally {
    await server.close()
    await out.done()
  }
})

test('a removed row never leaves the chat slot on its route (NO_ADAPTER): the slot goes to the account while signed in, else back to the stock default', async () => {
  // signed out: the custom row was the only chat model; removing it would have left new chats on
  // `custom`, a route no adapter serves (`no adapter registered for provider "custom"`)
  const alone = await cloud()
  const server = await modelsServer(['my-model'])
  try {
    await alone.api('POST', '/providers/save', { id: 'custom', apiKey: 'sk-secret', baseURL: server.url, label: 'Gateway', capabilities: ['chat'] })
    assert.deepEqual(alone.selection.current, { provider: 'custom', model: 'my-model' }, 'the first own key is adopted')
    assert.equal((await alone.api('POST', '/providers/remove', { id: 'custom' })).status, 200)
    assert.deepEqual(alone.selection.current, STOCK_DEFAULT_MODEL)
  } finally {
    await alone.done()
  }
  // signed in: the account's recommended chat model takes the slot
  const signed = await cloud({ signedIn: true, defaultModel: { provider: 'custom', model: 'my-model' } })
  try {
    await signed.api('POST', '/providers/save', { id: 'custom', apiKey: 'sk-secret', baseURL: server.url, label: 'Gateway', capabilities: ['chat'] })
    await signed.api('POST', '/providers/remove', { id: 'custom' })
    assert.deepEqual(signed.selection.current, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' })
  } finally {
    await server.close()
    await signed.done()
  }
})

test('signing out releases the account’s route the same way: to an own row when there is one, else to the stock default', async () => {
  const server = await modelsServer(['my-model'])
  const withRow = await cloud({ signedIn: true, defaultModel: { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' } })
  try {
    await withRow.api('POST', '/providers/save', { id: 'custom', apiKey: 'sk-secret', baseURL: server.url, label: 'Gateway', capabilities: ['chat'] })
    assert.deepEqual(withRow.selection.current, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' }, 'a signed-in slot is not moved by a new key')
    withRow.svc.relay.signOut = async () => undefined
    await withRow.svc.signOut()
    assert.deepEqual(withRow.selection.current, { provider: 'custom', model: 'my-model' })
  } finally {
    await server.close()
    await withRow.done()
  }
  const bare = await cloud({ signedIn: true, defaultModel: { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' } })
  try {
    bare.svc.relay.signOut = async () => undefined
    await bare.svc.signOut()
    assert.deepEqual(bare.selection.current, STOCK_DEFAULT_MODEL)
  } finally {
    await bare.done()
  }
})

test('an endpoint that lists no models: `no_models` with the key not stored, or the ids the person typed', async () => {
  const out = await cloud()
  const silent = await modelsServer([])
  try {
    const refused = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'sk-secret', baseURL: silent.url, label: 'Gateway', capabilities: ['chat'] })
    assert.equal(refused.status, 400)
    assert.equal(refused.body.error.code, 'no_models')
    assert.equal(out.credentials.has('NANOMUSE_KEY_CUSTOM'), false, 'nothing is written before the row can be served')
    assert.equal(out.settings[LLM_ROW].providers.custom, undefined)
    const saved = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'sk-secret', baseURL: silent.url, label: 'Gateway', capabilities: ['chat', 'vision'], models: 'glm-4.7, glm-4.7,  , kimi-k2.5\n' })
    assert.equal(saved.status, 200)
    assert.deepEqual(saved.body.models.map((m) => [m.id, m.kind, m.vision]), [['glm-4.7', 'chat', true], ['kimi-k2.5', 'chat', true]])
    assert.deepEqual(out.settings[LLM_ROW].providers.custom.models.map((m) => m.id), ['glm-4.7', 'kimi-k2.5'])
    assert.equal(out.credentials.get('NANOMUSE_KEY_CUSTOM'), 'sk-secret')
    // typed ids come first, the endpoint's after them (`row`: the same endpoint moved, not a second one)
    const listing = await modelsServer(['listed-a', 'glm-4.7'])
    try {
      const both = await out.api('POST', '/providers/save', { id: 'custom', row: 'custom', apiKey: 'sk-secret', baseURL: listing.url, label: 'Gateway', capabilities: ['chat'], models: ['glm-4.7'] })
      assert.equal(both.body.id, 'custom')
      assert.deepEqual(both.body.models.map((m) => m.id), ['glm-4.7', 'listed-a'])
    } finally {
      await listing.close()
    }
    // a key with a space in it is refused with its own code, not the sign-in's
    const spaced = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'sk se cret', baseURL: silent.url, models: 'm' })
    assert.equal(spaced.body.error.code, 'key_shape')
  } finally {
    await silent.close()
    await out.done()
  }
})

test('several hand-made endpoints at once (#294): each save without `row` adds a row with its own key; `row` changes one and keeps its key; rename and remove touch that row only', async () => {
  const out = await cloud()
  const first = await modelsServer(['gw-chat', 'gw-vl'])
  const second = await modelsServer(['local-chat'])
  try {
    // two endpoints: `custom`, then `custom-2`, each with its own credential; unnamed, each reads as its host
    const one = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'sk-one', baseURL: first.url, capabilities: ['chat', 'vision'] })
    assert.equal(one.status, 200)
    assert.equal(one.body.id, 'custom')
    assert.equal(one.body.keyRef, 'NANOMUSE_KEY_CUSTOM')
    assert.equal(one.body.label, new URL(first.url).host)
    const two = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'sk-two', baseURL: second.url, label: 'Local server', capabilities: ['chat'] })
    assert.equal(two.status, 200)
    assert.equal(two.body.id, 'custom-2')
    assert.equal(two.body.provider, 'custom')
    assert.equal(two.body.keyRef, 'NANOMUSE_KEY_CUSTOM_2')
    assert.equal(two.body.label, 'Local server')
    assert.deepEqual(two.body.offer, { chat: 'local-chat' }, 'the "Use it for" card offers the new row, not the first')
    assert.equal(out.credentials.get('NANOMUSE_KEY_CUSTOM'), 'sk-one')
    assert.equal(out.credentials.get('NANOMUSE_KEY_CUSTOM_2'), 'sk-two')
    const state = await out.state()
    assert.deepEqual(Object.keys(state.providers).sort(), ['custom', 'custom-2'])
    assert.equal(state.providers['custom-2'].id, 'custom-2')
    assert.equal(out.settings[LLM_ROW].providers['custom-2'].apiKeyEnv, 'NANOMUSE_KEY_CUSTOM_2')
    assert.equal(out.settings[LLM_ROW].providers['custom-2'].displayName, 'Local server')
    // both stand in GET /providers and in the pickers, told apart by name
    const view = (await out.api('GET', '/providers?lang=en')).body
    assert.deepEqual(view.configured.map((p) => [p.id, p.provider, p.label]).sort(), [['custom', 'custom', new URL(first.url).host], ['custom-2', 'custom', 'Local server']])
    assert.deepEqual(out.svc.chatOptions().map((o) => [o.provider, o.providerLabel, o.id]), [['custom', new URL(first.url).host, 'gw-chat'], ['custom', new URL(first.url).host, 'gw-vl'], ['custom-2', 'Local server', 'local-chat']])
    assert.deepEqual(out.svc.handsOptions().map((o) => [o.provider, o.id]), [['custom', 'gw-chat'], ['custom', 'gw-vl']])
    // new chats answer through the first endpoint; the second changed nothing there
    assert.deepEqual(out.selection.current, { provider: 'custom', model: 'gw-chat' })
    // a change of key on the first row: the second's key stays; an empty key keeps the first's own
    const rekeyed = await out.api('POST', '/providers/save', { id: 'custom', row: 'custom', apiKey: 'sk-one-b' })
    assert.equal(rekeyed.status, 200)
    assert.equal(rekeyed.body.id, 'custom')
    assert.equal(rekeyed.body.baseURL, first.url, 'the address stands when none is typed')
    assert.deepEqual(rekeyed.body.capabilities, ['chat', 'vision'], 'the capabilities stand when none are ticked again')
    assert.equal(out.credentials.get('NANOMUSE_KEY_CUSTOM'), 'sk-one-b')
    assert.equal(out.credentials.get('NANOMUSE_KEY_CUSTOM_2'), 'sk-two')
    const kept = await out.api('POST', '/providers/save', { id: 'custom', row: 'custom', apiKey: '', label: 'Gateway' })
    assert.equal(kept.status, 200)
    assert.equal(kept.body.label, 'Gateway')
    assert.equal(kept.body.keyRef, 'NANOMUSE_KEY_CUSTOM')
    assert.equal(out.credentials.get('NANOMUSE_KEY_CUSTOM'), 'sk-one-b')
    assert.equal(Object.keys((await out.state()).providers).length, 2, 'a change never doubles the row')
    // `row` must name a row of that entry
    assert.equal((await out.api('POST', '/providers/save', { id: 'custom', row: 'custom-9', apiKey: 'sk-x', baseURL: first.url })).status, 404)
    // rename: the pickers and the model adapter read the new name; empty goes back to the host
    const renamed = await out.api('POST', '/providers/rename', { id: 'custom-2', label: 'vLLM box' })
    assert.equal(renamed.status, 200)
    assert.equal(renamed.body.label, 'vLLM box')
    assert.equal(out.settings[LLM_ROW].providers['custom-2'].displayName, 'vLLM box')
    assert.equal((await out.state()).providers['custom-2'].label, 'vLLM box')
    assert.equal((await out.api('POST', '/providers/rename', { id: 'custom-2', label: '  ' })).body.label, new URL(second.url).host)
    assert.equal((await out.api('POST', '/providers/rename', { id: 'nobody', label: 'x' })).status, 404)
    // remove the first: the second and its key stay; the next endpoint takes the lowest free id again
    assert.equal((await out.api('POST', '/providers/remove', { id: 'custom' })).status, 200)
    assert.deepEqual(Object.keys((await out.state()).providers), ['custom-2'])
    assert.equal(out.credentials.has('NANOMUSE_KEY_CUSTOM'), false)
    assert.equal(out.credentials.get('NANOMUSE_KEY_CUSTOM_2'), 'sk-two')
    assert.equal(out.settings[LLM_ROW].providers.custom, undefined)
    assert.equal(out.settings[LLM_ROW].providers['custom-2'].apiKeyEnv, 'NANOMUSE_KEY_CUSTOM_2')
    const third = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'sk-three', baseURL: first.url, capabilities: ['chat'] })
    assert.equal(third.body.id, 'custom')
    assert.deepEqual(Object.keys((await out.state()).providers).sort(), ['custom', 'custom-2'])
    // a vendor's row is still one per vendor: saving its key again replaces it
    const vendor = await modelsServer(['deepseek-v4.1-flash'])
    try {
      await out.api('POST', '/providers/save', { id: 'deepseek', apiKey: 'sk-d1', baseURL: vendor.url })
      await out.api('POST', '/providers/save', { id: 'deepseek', apiKey: 'sk-d2', baseURL: vendor.url })
      assert.deepEqual(Object.keys((await out.state()).providers).sort(), ['custom', 'custom-2', 'deepseek'])
      assert.equal(out.credentials.get('NANOMUSE_KEY_DEEPSEEK'), 'sk-d2')
    } finally {
      await vendor.close()
    }
  } finally {
    await first.close()
    await second.close()
    await out.done()
  }
})

test('a row written before the endpoint list (#294) carries no id of its own: it is read back under its key, and the slot choices still find it', async () => {
  const home = await mkdtemp(join(tmpdir(), 'nm-cloud-'))
  const statePath = join(home, 'cloud.json')
  const fake = fakeContext()
  const row = { provider: 'custom', label: 'Gateway', protocol: 'openai', baseURL: 'http://127.0.0.1:9/v1', keyRef: 'NANOMUSE_KEY_CUSTOM', capabilities: ['chat', 'vision'], models: [{ id: 'gw-vl', name: 'gw-vl', vision: true, kind: 'chat' }], at: 1 }
  await writeFile(statePath, JSON.stringify({ providers: { custom: row }, handsProvider: 'custom', handsModel: 'gw-vl', update: { checkedAt: Date.now() } }))
  await fake.ctx.credentials.set('NANOMUSE_KEY_CUSTOM', 'sk-old')
  const svc = new NanomuseCloud(fake.ctx, { baseURL: 'https://relay.invalid', deviceName: 'test-desktop', statePath })
  svc.hub.start = () => undefined
  svc.refresh = async () => svc.status()
  try {
    await svc[Service.init]()
    const view = await svc.providersView('en')
    assert.deepEqual(view.configured.map((p) => [p.id, p.provider, p.label]), [['custom', 'custom', 'Gateway']])
    assert.deepEqual(svc.handsChoice(), { provider: 'custom', model: 'gw-vl' })
    assert.deepEqual(svc.handsOptions().map((o) => [o.provider, o.id]), [['custom', 'gw-vl']])
  } finally {
    await rm(home, { recursive: true, force: true })
  }
})

test('OpenCode Go is written as the adapter’s catalog route (no api, no base URL), with the models the adapter lists, and stays that route after a restart', async () => {
  const out = await cloud()
  // the adapter's catalog knows two Go models; a typed id it does not list is left out
  out.ctx.get = ((inner) => (name) => name === 'llm' ? { ...inner('llm'), discoverModels: async (ns, { provider }) => (ns === LLM_ROW && provider === 'opencode-go' ? [{ id: 'deepseek-v4.1-flash' }, { id: 'grok-4.7' }] : []) } : inner(name))(out.ctx.get)
  try {
    const saved = await out.api('POST', '/providers/save', { id: 'opencode-go', apiKey: 'sk-go-secret', models: 'grok-4.7, gpt-6-luna' })
    assert.equal(saved.status, 200)
    assert.equal(saved.body.catalogRoute, true)
    assert.deepEqual(saved.body.models.map((m) => m.id), ['grok-4.7', 'deepseek-v4.1-flash'])
    const written = out.settings[LLM_ROW].providers['opencode-go']
    assert.deepEqual(written, {
      displayName: 'OpenCode Go',
      apiKeyEnv: 'NANOMUSE_KEY_OPENCODE_GO',
      models: [{ id: 'grok-4.7', displayName: 'grok-4.7', input: ['text'] }, { id: 'deepseek-v4.1-flash', displayName: 'deepseek-v4.1-flash', input: ['text'] }],
    })
    assert.equal((await out.state()).providers['opencode-go'].catalogRoute, true)
    // a host restart reads the row back from cloud.json and compares it with the adapter's:
    // the catalog route must be what it reads, or the refresh would write a hand-declared route
    // (api + baseURL), which sends no session id
    const fake = fakeContext()
    fake.settings[LLM_ROW].providers = JSON.parse(JSON.stringify(out.settings[LLM_ROW].providers))
    const again = new NanomuseCloud(fake.ctx, { baseURL: 'https://relay.invalid', deviceName: 'test-desktop', statePath: out.statePath })
    again.hub.start = () => undefined
    again.refresh = async () => again.status()
    await again[Service.init]()
    await new Promise((r) => setTimeout(r, 20))
    assert.deepEqual(fake.settings[LLM_ROW].providers['opencode-go'], written)
    assert.equal((await again.providersView('en')).configured[0].catalogRoute, true)
  } finally {
    await out.done()
  }
})

test('a trimmed model catalog (#525): editing llm-pi-ai models or saving with catalogOnly keeps only the kept chat models across pickers, restarts and key updates', async () => {
  const out = await cloud()
  const bulk = Array.from({ length: 158 }, (_, i) => `extra-model-${String(i + 1).padStart(3, '0')}`)
  const server = await modelsServer(['glm-5.1', 'gpt-5.4', 'kimi-k2.5', 'qwen-image-3.0', ...bulk])
  try {
    // 1. Save a provider whose gateway lists 161 chat models + 1 image model
    const saved = await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-first', baseURL: server.url })
    assert.equal(saved.status, 200)
    assert.equal(out.svc.chatOptions().length, 161)
    assert.deepEqual(out.selection.current, { provider: 'bailian', model: 'extra-model-001' })

    // 2. Trim the model catalog in llm-pi-ai settings down to 3 models
    out.settings[LLM_ROW].providers.bailian.models = [
      { id: 'glm-5.1', displayName: 'glm-5.1', input: ['text'] },
      { id: 'gpt-5.4', displayName: 'gpt-5.4', input: ['text', 'image'] },
      { id: 'kimi-k2.5', displayName: 'kimi-k2.5', input: ['text', 'image'] },
    ]
    assert.deepEqual(out.svc.chatOptions().map((o) => o.id), ['glm-5.1', 'gpt-5.4', 'kimi-k2.5'])
    assert.deepEqual(out.svc.handsOptions().map((o) => o.id), ['gpt-5.4', 'kimi-k2.5'])
    assert.deepEqual(out.svc.imageOptions().map((o) => o.id), ['qwen-image-3.0'])
    const view = await out.svc.providersView('en')
    assert.deepEqual(view.configured[0].models.filter((m) => m.kind === 'chat').map((m) => m.id), ['glm-5.1', 'gpt-5.4', 'kimi-k2.5'])
    await new Promise((r) => setTimeout(r, 20))
    assert.deepEqual(out.selection.current, { provider: 'bailian', model: 'glm-5.1' }, 'default chat selection moves off a trimmed-out model')

    // 3. Restart the host: refreshOwnRows keeps the 3 trimmed models instead of restoring all 161
    const fake = fakeContext({ defaultModel: out.selection.current })
    fake.settings[LLM_ROW].providers = JSON.parse(JSON.stringify(out.settings[LLM_ROW].providers))
    const again = new NanomuseCloud(fake.ctx, { baseURL: 'https://relay.invalid', deviceName: 'test-desktop', statePath: out.statePath })
    again.hub.start = () => undefined
    again.refresh = async () => again.status()
    await again[Service.init]()
    await new Promise((r) => setTimeout(r, 20))
    assert.deepEqual(fake.settings[LLM_ROW].providers.bailian.models.map((m) => m.id), ['glm-5.1', 'gpt-5.4', 'kimi-k2.5'])
    assert.deepEqual(again.chatOptions().map((o) => o.id), ['glm-5.1', 'gpt-5.4', 'kimi-k2.5'])

    // 4. Re-saving the provider key without new models keeps the trimmed catalog
    const rekeyed = await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-second', baseURL: server.url })
    assert.equal(rekeyed.status, 200)
    assert.deepEqual(rekeyed.body.models.filter((m) => m.kind === 'chat').map((m) => m.id), ['glm-5.1', 'gpt-5.4', 'kimi-k2.5'])
    assert.deepEqual(out.settings[LLM_ROW].providers.bailian.models.map((m) => m.id), ['glm-5.1', 'gpt-5.4', 'kimi-k2.5'])

    // 5. Explicit catalogOnly on POST /providers/save saves only the typed chat models
    const customOnly = await out.api('POST', '/providers/save', {
      id: 'custom',
      apiKey: 'sk-custom',
      baseURL: server.url,
      label: 'Trimmed Gateway',
      capabilities: ['chat', 'vision'],
      models: 'glm-5.1, kimi-k2.5',
      catalogOnly: true,
    })
    assert.equal(customOnly.status, 200)
    assert.deepEqual(customOnly.body.models.map((m) => m.id), ['glm-5.1', 'kimi-k2.5'])
    assert.deepEqual(out.settings[LLM_ROW].providers.custom.models.map((m) => m.id), ['glm-5.1', 'kimi-k2.5'])
  } finally {
    await server.close()
    await out.done()
  }
})


async function restartForCatalog(out, { delayed = false } = {}) {
  const fake = fakeContext({ defaultModel: out.selection.current })
  if (!delayed) fake.settings[LLM_ROW].providers = structuredClone(out.settings[LLM_ROW].providers)
  const describe = fake.ctx.settings.describe
  let available = !delayed
  fake.ctx.settings.describe = () => available ? describe() : []
  const svc = new NanomuseCloud(fake.ctx, { baseURL: 'https://relay.invalid', deviceName: 'test-desktop', statePath: out.statePath })
  svc.hub.start = () => undefined
  svc.refresh = async () => svc.status()
  await svc[Service.init]()
  await svc.busy
  return { ...fake, svc, ready() { available = true } }
}

test('Advanced deletion of an observed own provider survives restart without touching other endpoints or keys (#889)', async () => {
  const out = await cloud()
  const server = await modelsServer(['first-model', 'second-model'])
  try {
    const first = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'first-key', baseURL: server.url, capabilities: ['chat', 'vision'] })
    const second = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'second-key', baseURL: server.url, capabilities: ['chat', 'vision'] })
    assert.equal(first.status, 200)
    assert.equal(second.status, 200)
    const firstId = first.body.id
    const secondId = second.body.id
    out.svc.chatOptions()
    out.svc.state.handsProvider = firstId
    out.svc.state.handsModel = 'first-model'
    out.svc.state.media = { imageProvider: firstId, imageModel: 'image-model', videoProvider: secondId, videoModel: 'video-model' }
    const survivor = structuredClone(out.settings[LLM_ROW].providers[secondId])
    const keys = new Map(out.credentials)
    delete out.settings[LLM_ROW].providers[firstId]
    out.emit('settings/document-updated', LLM_ROW, 1)
    await out.svc.busy
    assert.equal((await out.state()).providers[firstId], undefined)
    assert.equal((await out.state()).handsProvider, undefined)
    assert.equal((await out.state()).media.imageProvider, undefined)
    assert.equal((await out.state()).media.videoProvider, secondId)
    assert.equal(out.selection.current.provider, secondId)
    assert.deepEqual(out.settings[LLM_ROW].providers[secondId], survivor)
    assert.deepEqual(out.credentials, keys)
    const again = await restartForCatalog(out)
    assert.equal(again.settings[LLM_ROW].providers[firstId], undefined)
    assert.deepEqual(again.settings[LLM_ROW].providers[secondId], survivor)
  } finally {
    await server.close()
    await out.done()
  }
})

test('an explicitly empty chat catalog survives writes, restart and key updates while media remains (#889)', async () => {
  const out = await cloud()
  const server = await modelsServer(['first-model', 'second-model', 'qwen-image-3.0'])
  try {
    await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'first-key', baseURL: server.url, capabilities: ['chat', 'vision', 'image'] })
    const other = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'other-key', baseURL: server.url, capabilities: ['chat'] })
    out.svc.chatOptions()
    out.settings[LLM_ROW].providers.custom.models = []
    out.emit('settings/document-updated', LLM_ROW, 1)
    await out.svc.busy
    assert.equal(out.selection.current.provider, other.body.id)
    assert.deepEqual(out.svc.chatOptions().filter((m) => m.provider === 'custom'), [])
    assert.deepEqual(out.svc.imageOptions().filter((m) => m.provider === 'custom').map((m) => m.id), ['qwen-image-3.0'])
    const saved = await out.state()
    assert.equal(saved.providers.custom.customModels, true)
    assert.deepEqual(saved.providers.custom.models.filter((m) => m.kind === 'chat'), [])
    out.svc.refreshOwnRows()
    await out.svc.busy
    assert.deepEqual(out.settings[LLM_ROW].providers.custom.models, [])
    const again = await restartForCatalog(out)
    assert.deepEqual(again.settings[LLM_ROW].providers.custom.models, [])
    const rekeyed = await out.api('POST', '/providers/save', { id: 'custom', row: 'custom', apiKey: 'updated-key', baseURL: server.url })
    assert.equal(rekeyed.status, 200)
    assert.deepEqual(rekeyed.body.models.filter((m) => m.kind === 'chat'), [])
    assert.deepEqual(out.settings[LLM_ROW].providers.custom.models, [])
    await out.svc.busy
    await out.svc.stateWrites
  } finally {
    await server.close()
    await out.done()
  }
})

test('adapter startup gaps are not deletion and Cloud rows stay managed (#889)', async () => {
  const out = await cloud({ signedIn: true })
  const server = await modelsServer(['first-model'])
  try {
    await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'first-key', baseURL: server.url, capabilities: ['chat'] })
    const saved = await out.state()
    const again = await restartForCatalog(out, { delayed: true })
    again.emit('settings/document-updated', LLM_ROW, 1)
    assert.ok(again.svc.state.providers.custom)
    again.ready()
    again.emit('settings/document-updated', LLM_ROW, 2)
    again.svc.refreshOwnRows()
    await again.svc.busy
    await new Promise((r) => setTimeout(r, 20))
    assert.deepEqual(again.settings[LLM_ROW].providers.custom.models.map((m) => m.id), saved.providers.custom.models.map((m) => m.id))
    again.settings[LLM_ROW].providers[PROVIDER_ID] = { models: ACCOUNT_MODELS }
    again.svc.chatOptions()
    delete again.settings[LLM_ROW].providers[PROVIDER_ID]
    again.emit('settings/document-updated', LLM_ROW, 3)
    await again.svc.busy
    assert.ok(again.svc.state.account)
    assert.deepEqual(again.svc.state.models, ACCOUNT_MODELS)
  } finally {
    await server.close()
    await out.done()
  }
})


test('a delayed adapter refresh does not recreate a provider deleted while another row was being written (#889)', async () => {
  const out = await cloud()
  const server = await modelsServer(['first-model'])
  try {
    await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'first-key', baseURL: server.url, capabilities: ['chat'] })
    const second = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'second-key', baseURL: server.url, capabilities: ['chat'] })
    out.svc.chatOptions()
    out.settings[LLM_ROW].providers.custom.displayName = 'old label'
    const update = out.ctx.settings.update
    let release
    const gate = new Promise((resolve) => { release = resolve })
    out.ctx.settings.update = async (...args) => { await gate; return update(...args) }
    out.svc.refreshOwnRows()
    delete out.settings[LLM_ROW].providers[second.body.id]
    out.emit('settings/document-updated', LLM_ROW, 1)
    release()
    await out.svc.busy
    await new Promise((r) => setTimeout(r, 20))
    assert.equal(out.settings[LLM_ROW].providers[second.body.id], undefined)
    assert.equal((await out.state()).providers[second.body.id], undefined)
  } finally {
    await server.close()
    await out.done()
  }
})


test('a late refresh of a removed row is cleaned up without deleting a legitimate re-add of the same id (#889)', async () => {
  for (const readd of [false, true]) {
    const out = await cloud()
    const server = await modelsServer(['first-model'])
    try {
      await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'first-key', baseURL: server.url, capabilities: ['chat'] })
      out.svc.chatOptions()
      out.settings[LLM_ROW].providers.custom.displayName = 'old label'
      const update = out.ctx.settings.update
      let began, release
      const entered = new Promise((resolve) => { began = resolve })
      const gate = new Promise((resolve) => { release = resolve })
      let first = true
      out.ctx.settings.update = async (...args) => {
        if (first) { first = false; began(); await gate }
        return update(...args)
      }
      out.svc.refreshOwnRows()
      await entered
      delete out.settings[LLM_ROW].providers.custom
      out.emit('settings/document-updated', LLM_ROW, 1)
      const saved = readd ? out.api('POST', '/providers/save', { id: 'custom', apiKey: 'new-key', baseURL: server.url, label: 'New source', capabilities: ['chat'] }) : undefined
      release()
      await out.svc.busy
      if (saved) assert.equal((await saved).status, 200)
      await out.svc.busy
      const row = out.settings[LLM_ROW].providers.custom
      if (readd) {
        assert.equal(row.displayName, 'New source')
        assert.equal((await out.state()).providers.custom.label, 'New source')
      } else {
        assert.equal(row, undefined)
        assert.equal((await out.state()).providers.custom, undefined)
      }
    } finally {
      await server.close()
      await out.done()
    }
  }
})

test('an empty catalog-route model list keeps its override after key update and restart (#889)', async () => {
  const out = await cloud()
  const baseGet = out.ctx.get
  out.ctx.get = (name) => name === 'llm' ? { listProviders: () => [], discoverModels: async () => [{ id: 'go-model' }] } : baseGet(name)
  try {
    const saved = await out.api('POST', '/providers/save', { id: 'opencode-go', apiKey: 'first-key' })
    assert.equal(saved.status, 200)
    out.svc.chatOptions()
    out.settings[LLM_ROW].providers['opencode-go'].models = []
    out.emit('settings/document-updated', LLM_ROW, 1)
    await out.svc.busy
    const rekeyed = await out.api('POST', '/providers/save', { id: 'opencode-go', row: 'opencode-go', apiKey: 'next-key' })
    assert.equal(rekeyed.status, 200)
    assert.equal(rekeyed.body.customModels, true)
    assert.deepEqual(out.settings[LLM_ROW].providers['opencode-go'].models, [])
    const again = await restartForCatalog(out)
    assert.deepEqual(again.settings[LLM_ROW].providers['opencode-go'].models, [])
    await out.svc.busy
    await out.svc.stateWrites
  } finally {
    await out.done()
  }
})


test("a new custom endpoint never inherits another endpoint's empty catalog or saved key (#889)", async () => {
  const out = await cloud()
  const first = await modelsServer(['first-model'])
  const second = await modelsServer(['second-model'])
  try {
    await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'first-key', baseURL: first.url, capabilities: ['chat'] })
    out.svc.chatOptions()
    out.settings[LLM_ROW].providers.custom.models = []
    out.emit('settings/document-updated', LLM_ROW, 1)
    await out.svc.busy
    const added = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'second-key', baseURL: second.url, capabilities: ['chat'] })
    assert.equal(added.status, 200)
    assert.equal(added.body.id, 'custom-2')
    assert.deepEqual(added.body.models.map((m) => m.id), ['second-model'])
    assert.equal(added.body.baseURL, second.url)
    assert.notEqual(added.body.keyRef, (await out.state()).providers.custom.keyRef)
    assert.deepEqual(out.settings[LLM_ROW].providers.custom.models, [])
    await out.svc.busy
    await out.svc.stateWrites
  } finally {
    await first.close()
    await second.close()
    await out.done()
  }
})


test('removing and re-adding the same source does not reuse the previous adapter observation (#889)', async () => {
  const out = await cloud()
  const server = await modelsServer(['first-model'])
  try {
    await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'old-key', baseURL: server.url, capabilities: ['chat'] })
    out.svc.chatOptions()
    assert.equal((await out.api('POST', '/providers/remove', { id: 'custom' })).status, 200)
    const update = out.ctx.settings.update
    out.ctx.settings.update = async () => undefined // a newly loaded adapter has not exposed the saved row yet
    const added = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'new-key', baseURL: server.url, capabilities: ['chat'] })
    assert.equal(added.status, 200)
    out.emit('settings/document-updated', LLM_ROW, 1)
    await out.svc.busy
    assert.ok((await out.state()).providers.custom, "a missing new adapter row must not reuse the deleted generation's observation")
    out.ctx.settings.update = update
    out.svc.refreshOwnRows()
    await out.svc.busy
    out.svc.chatOptions()
    delete out.settings[LLM_ROW].providers.custom
    out.emit('settings/document-updated', LLM_ROW, 2)
    await out.svc.busy
    assert.equal((await out.state()).providers.custom, undefined)
  } finally {
    await server.close()
    await out.done()
  }
})
