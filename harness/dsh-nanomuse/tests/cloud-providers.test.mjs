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
    on() { return () => undefined },
  }
  return { ctx, credentials, settings, selection }
}

/** A provider's `/models`, OpenAI's shape, on the loopback. */
function modelsServer(ids) {
  const server = createServer((req, res) => {
    if (req.url?.endsWith('/models')) {
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ data: ids.map((id) => ({ id })) }))
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
    assert.equal(removed.status, 204)
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
    assert.equal((await alone.api('POST', '/providers/remove', { id: 'custom' })).status, 204)
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
    // typed ids come first, the endpoint's after them
    const listing = await modelsServer(['listed-a', 'glm-4.7'])
    try {
      const both = await out.api('POST', '/providers/save', { id: 'custom', apiKey: 'sk-secret', baseURL: listing.url, label: 'Gateway', capabilities: ['chat'], models: ['glm-4.7'] })
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
