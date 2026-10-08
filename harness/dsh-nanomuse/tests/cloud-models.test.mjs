// Settings → Models (0.1.41, "Choice"), the host's half, through `NanomuseCloud` itself: the
// resolution order of the four slots (the person's choice, then the chat provider's defaults,
// then nanoMuse Cloud, then the first own row that can), `GET /models` for the page, the
// "Use it for" card's offer and `POST /providers/adopt`, the hands' environment for the MCP
// client, and the own-provider image shapes with a fake fetch. No Electron, no relay, no
// network: the same in-memory context as cloud-providers.test.mjs.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Readable } from 'node:stream'
import { Service } from '@deepseek-ai/cordis'
import NanomuseCloud, { API_PREFIX, LLM_ROW, PROVIDER_ID, TOKEN_REF } from '../lib/cloud.js'
import { editImage, generateImage, imageShapeOf } from '../lib/images.js'
import { clientConfig } from '../lib/hands-tools.js'

process.env.NANOMUSE_PY = join(tmpdir(), 'nanomuse-runtime-that-does-not-exist')

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
    inject() {},
    effect(fn) { fn() },
    on() { return () => undefined },
  }
  return { ctx, credentials, settings, selection }
}

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
  { id: 'deepseek-v4.1', name: 'DeepSeek V4.1', kind: 'chat', for: ['chat'] },
  { id: 'qwen3.8-27b', name: 'Qwen 3.8 27B', kind: 'chat', for: ['gui'] },
  { id: 'qwen-image-3.0', name: 'Qwen Image', kind: 'image', recommended: true },
  { id: 'wan2.2-i2v-flash', name: 'Wan', kind: 'video' },
]

async function cloud({ signedIn = false, defaultModel } = {}) {
  const home = await mkdtemp(join(tmpdir(), 'nm-models-'))
  const statePath = join(home, 'cloud.json')
  const fake = fakeContext({ defaultModel })
  if (signedIn) {
    await fake.ctx.credentials.set(TOKEN_REF, 'account-key')
    await writeFile(statePath, JSON.stringify({ account: { id: 'acct-1', channel: 'email', hint: 'a***@example.org', member: false, region: 'intl' }, models: ACCOUNT_MODELS, update: { checkedAt: Date.now() } }))
  } else {
    await writeFile(statePath, JSON.stringify({ update: { checkedAt: Date.now() } }))
  }
  const svc = new NanomuseCloud(fake.ctx, { baseURL: 'https://relay.invalid', deviceName: 'test-desktop', statePath })
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

const BAILIAN_MODELS = ['deepseek-v4.1-flash', 'qwen3.8-27b', 'qwen3-vl-plus', 'qwen-image-3.0', 'wan2.2-i2v-flash']

test('GET /models: the four slots; signed in with nothing else, every row is the account and the recommended model is marked and first', async () => {
  const out = await cloud({ signedIn: true, defaultModel: { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' } })
  try {
    const res = await out.api('GET', '/models')
    assert.equal(res.status, 200)
    const view = res.body
    assert.equal(view.signedIn, true)
    assert.deepEqual(Object.keys(view.slots), ['chat', 'hands', 'image', 'video'])
    assert.deepEqual(view.handsExcluded, [])
    // the chat slot: the account's default, the recommended model first and marked, the other one after it
    assert.equal(view.slots.chat.provider, PROVIDER_ID)
    assert.equal(view.slots.chat.providerLabel, 'nanoMuse Cloud')
    assert.deepEqual(view.slots.chat.options.map((o) => [o.id, Boolean(o.recommended)]), [['deepseek-v4.1-flash', true], ['deepseek-v4.1', false]])
    assert.deepEqual(view.slots.hands.options.map((o) => [o.id, Boolean(o.recommended)]), [['qwen3.8-27b', true]])
    assert.equal(view.slots.hands.chosen, false)
    // pictures and clips: the account's models, the recommended image model marked
    assert.deepEqual(view.slots.image, { provider: PROVIDER_ID, providerLabel: 'nanoMuse Cloud', model: 'qwen-image-3.0', options: [{ provider: PROVIDER_ID, providerLabel: 'nanoMuse Cloud', id: 'qwen-image-3.0', name: 'Qwen Image', recommended: true }], chosen: false, auto: { provider: PROVIDER_ID, providerLabel: 'nanoMuse Cloud', model: 'qwen-image-3.0' } })
    assert.equal(view.slots.video.model, 'wan2.2-i2v-flash')
    assert.equal(view.slots.video.off, undefined)
  } finally {
    await out.done()
  }
})

test('signed out with nothing configured, every slot is empty and lists nothing; the gate speaks, not an error', async () => {
  const out = await cloud()
  try {
    const view = (await out.api('GET', '/models')).body
    assert.equal(view.signedIn, false)
    for (const slot of ['chat', 'hands', 'image', 'video']) {
      assert.deepEqual(view.slots[slot].options, [], slot)
      assert.equal(view.slots[slot].model, '', slot)
    }
    assert.equal(await out.svc.imageEndpoint(), undefined)
    assert.equal(await out.svc.videoEndpoint(), undefined)
    // the studio: `signed_out` only now, when nothing at all can draw
    const est = await out.api('GET', '/studio/estimate')
    assert.equal(est.status, 401)
    assert.equal(est.body.error.code, 'signed_out')
  } finally {
    await out.done()
  }
})

test('the hands order: the choice, else the chat provider’s defaults.hands when it sees pictures, else the account’s gui model, else the first own sighted model', async () => {
  const out = await cloud({ signedIn: true })
  const server = await modelsServer(BAILIAN_MODELS)
  try {
    // the stock DeepSeek row had no key, so the saved row became the chat default: the hands follow the chat provider
    await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-test', baseURL: server.url })
    assert.deepEqual(out.selection.current, { provider: 'bailian', model: 'deepseek-v4.1-flash' })
    assert.deepEqual(out.svc.handsChoice(), { provider: 'bailian', model: 'qwen3.8-27b' })
    // chat back to the account: the hands go back to the account's gui model (no explicit choice)
    await out.api('POST', '/chat-model', { model: 'deepseek-v4.1-flash', provider: PROVIDER_ID })
    assert.deepEqual(out.svc.handsChoice(), { provider: PROVIDER_ID, model: 'qwen3.8-27b' })
    // an explicit choice wins over both
    await out.api('POST', '/hands-model', { model: 'qwen3-vl-plus', provider: 'bailian' })
    assert.deepEqual(out.svc.handsChoice(), { provider: 'bailian', model: 'qwen3-vl-plus' })
    await out.api('POST', '/chat-model', { model: 'deepseek-v4.1-flash', provider: 'bailian' })
    assert.deepEqual(out.svc.handsChoice(), { provider: 'bailian', model: 'qwen3-vl-plus' })
    const view = (await out.api('GET', '/models')).body
    assert.equal(view.slots.hands.chosen, true)
    assert.deepEqual(view.slots.hands.options.map((o) => [o.provider, o.id]), [[PROVIDER_ID, 'qwen3.8-27b'], ['bailian', 'qwen3-vl-plus'], ['bailian', 'qwen3.8-27b']])
    // the hands' environment for the MCP client carries the row's base and key; the file next to cloud.json says the same
    const env = await out.svc.handsEnv()
    assert.equal(env.NANOMUSE_GUI_ENABLED, '1')
    assert.equal(env.NANOMUSE_GUI_PROVIDER, 'openai')
    assert.equal(env.NANOMUSE_GUI_MODEL, 'qwen3-vl-plus')
    assert.equal(env.NANOMUSE_GUI_BASE_URL, server.url)
    assert.equal(env.NANOMUSE_GUI_API_KEY, 'sk-test')
    assert.equal(JSON.parse(await readFile(join(out.home, 'hands.json'), 'utf8')).model, 'qwen3-vl-plus')
    const config = clientConfig(env, { NANOMUSE_PY: '/opt/nanomuse', HOME: '/home/someone', DISPLAY: ':0', NANOMUSE_OPERATOR_TOKEN: 'op-token' })
    assert.equal(config.command, '/opt/nanomuse')
    assert.deepEqual(config.args, ['mcp'])
    assert.equal(config.cwd, '/home/someone')
    assert.equal(config.env.DISPLAY, ':0')
    assert.equal(config.env.NANOMUSE_OPERATOR_TOKEN, 'op-token')
    assert.equal(config.env.NANOMUSE_GUI_MODEL, 'qwen3-vl-plus')
    assert.equal(config.failOnStartupError, false)
    assert.equal(out.svc.handsBusy(), false)
  } finally {
    await server.close()
    await out.done()
  }
})

test('signed out, the hands take the first own sighted model; a local server with no key is still exported', async () => {
  const out = await cloud()
  const server = await modelsServer(['qwen3-vl:8b', 'qwen3:8b'])
  try {
    // an OpenAI-compatible server on this computer, no key, the person says it sees pictures
    await out.api('POST', '/providers/save', { id: 'custom', apiKey: '', baseURL: server.url, label: 'My server', capabilities: ['chat', 'vision'] })
    assert.deepEqual(out.svc.handsChoice(), { provider: 'custom', model: 'qwen3-vl:8b' })
    const env = await out.svc.handsEnv()
    assert.equal(env.NANOMUSE_GUI_MODEL, 'qwen3-vl:8b')
    assert.equal(env.NANOMUSE_GUI_BASE_URL, server.url)
    assert.equal(env.NANOMUSE_GUI_API_KEY, '')
    assert.deepEqual(await out.svc.handsEnv().then((e) => Object.keys(e).sort()), ['NANOMUSE_GUI_API_KEY', 'NANOMUSE_GUI_BASE_URL', 'NANOMUSE_GUI_ENABLED', 'NANOMUSE_GUI_MODEL', 'NANOMUSE_GUI_PROVIDER'])
  } finally {
    await server.close()
    await out.done()
  }
})

test('the hands never list an Anthropic or native-Gemini row; the page names them in one sentence', async () => {
  const out = await cloud({ signedIn: true })
  const server = await modelsServer(['claude-sonnet-5-5'])
  try {
    await out.api('POST', '/providers/save', { id: 'anthropic', apiKey: 'sk-ant', baseURL: server.url })
    const view = (await out.api('GET', '/models')).body
    assert.deepEqual(view.slots.hands.options.map((o) => o.provider), [PROVIDER_ID])
    assert.deepEqual(view.handsExcluded, ['Anthropic Claude'])
    assert.deepEqual(out.svc.handsChoice(), { provider: PROVIDER_ID, model: 'qwen3.8-27b' })
  } finally {
    await server.close()
    await out.done()
  }
})

test('the image order: the choice, else the chat provider’s defaults.image, else the account, else the first own image row; a removed row drops the choice', async () => {
  const out = await cloud({ signedIn: true })
  const server = await modelsServer(BAILIAN_MODELS)
  try {
    await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-test', baseURL: server.url })
    // chat is bailian now (the stock default had no key): pictures follow it, DashScope's shape
    let ep = await out.svc.imageEndpoint()
    assert.deepEqual([ep.instanceId, ep.model, ep.shape, ep.label], ['bailian', 'qwen-image-3.0', 'dashscope', 'Alibaba Cloud Bailian'])
    assert.equal(ep.apiKey, 'sk-test')
    // chat back to the account: pictures through the account
    await out.api('POST', '/chat-model', { model: 'deepseek-v4.1-flash', provider: PROVIDER_ID })
    ep = await out.svc.imageEndpoint()
    assert.deepEqual([ep.instanceId, ep.model, ep.shape], [PROVIDER_ID, 'qwen-image-3.0', 'cloud'])
    assert.equal(ep.apiKey, 'account-key')
    // an explicit choice wins; `cloud: true` asks for the account whatever the choice
    const set = await out.api('POST', '/image-model', { model: 'qwen-image-3.0', provider: 'bailian' })
    assert.equal(set.status, 200)
    assert.equal(set.body.chosen, true)
    assert.equal(set.body.provider, 'bailian')
    assert.deepEqual((await out.state()).media, { imageModel: 'qwen-image-3.0', imageProvider: 'bailian' })
    assert.equal((await out.svc.imageEndpoint()).instanceId, 'bailian')
    assert.equal((await out.svc.imageEndpoint({ cloud: true })).instanceId, PROVIDER_ID)
    // the Media page and the studio's estimate say who draws and that the account bills nothing
    const media = await out.svc.media()
    assert.deepEqual(media.image, { source: 'provider', label: 'Alibaba Cloud Bailian', model: 'qwen-image-3.0', reason: '' })
    const est = (await out.api('GET', '/studio/estimate')).body
    assert.equal(est.source, 'provider')
    assert.equal(est.label, 'Alibaba Cloud Bailian')
    assert.equal(est.unlimited, true)
    assert.equal(est.affordable, true)
    assert.equal((await out.api('POST', '/image-model', { model: 'nope', provider: 'bailian' })).status, 400)
    // the row goes: the choice with it, back to the account
    await out.api('POST', '/providers/remove', { id: 'bailian' })
    assert.deepEqual((await out.state()).media, {})
    assert.equal((await out.svc.imageEndpoint()).instanceId, PROVIDER_ID)
  } finally {
    await server.close()
    await out.done()
  }
})

test('signed out, an own image row draws without an account: the studio does not ask to sign in', async () => {
  const out = await cloud()
  const server = await modelsServer(['gpt-5.4', 'gpt-image-2.5-flare'])
  try {
    await out.api('POST', '/providers/save', { id: 'openai', apiKey: 'sk-openai', baseURL: server.url })
    const ep = await out.svc.imageEndpoint()
    assert.deepEqual([ep.instanceId, ep.model, ep.shape], ['openai', 'gpt-image-2.5-flare', 'openai'])
    const est = await out.api('GET', '/studio/estimate')
    assert.equal(est.status, 200)
    assert.equal(est.body.source, 'provider')
    assert.equal(est.body.imageModel, 'gpt-image-2.5-flare')
    // nothing to fall back to: `cloud: true` has no account
    assert.equal(await out.svc.imageEndpoint({ cloud: true }), undefined)
    const retry = await out.api('POST', '/retry-cloud', { sessionId: 's1' })
    assert.equal(retry.status, 401)
    assert.equal(retry.body.error.code, 'signed_out')
  } finally {
    await server.close()
    await out.done()
  }
})

test('the video order: the choice, else the chat provider, else the account, else the first own Model Studio key; `off` keeps the face still; an old choice without a source still works', async () => {
  const out = await cloud({ signedIn: true })
  const server = await modelsServer(BAILIAN_MODELS)
  try {
    assert.equal((await out.svc.videoEndpoint()).instanceId, PROVIDER_ID)
    await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-test', baseURL: server.url })
    // chat is bailian: clips follow it, the catalogue's default on the row's host
    let ep = await out.svc.videoEndpoint()
    assert.deepEqual([ep.instanceId, ep.model], ['bailian', 'wan2.2-i2v-flash'])
    assert.ok(ep.host.startsWith('http://127.0.0.1:'))
    assert.equal(ep.apiKey, 'sk-test')
    await out.api('POST', '/chat-model', { model: 'deepseek-v4.1-flash', provider: PROVIDER_ID })
    assert.equal((await out.svc.videoEndpoint()).instanceId, PROVIDER_ID)
    // the choice: the account's model by name, the own row by name, off
    const options = (await out.api('GET', '/providers/models?cap=video')).body.options
    assert.deepEqual(options.slice(0, 1), [{ provider: PROVIDER_ID, providerLabel: 'nanoMuse Cloud', id: 'wan2.2-i2v-flash', name: 'Wan', recommended: true }])
    assert.ok(options.some((o) => o.provider === 'bailian' && o.id === 'wan2.2-i2v-flash'))
    const set = await out.api('POST', '/video-model', { model: 'wan2.2-i2v-flash', provider: 'bailian' })
    assert.equal(set.status, 200)
    assert.equal(set.body.provider, 'bailian')
    assert.equal((await out.svc.videoEndpoint()).instanceId, 'bailian')
    assert.equal((await out.svc.videoEndpoint({ cloud: true })).instanceId, PROVIDER_ID)
    await out.api('POST', '/video-model', { model: 'off' })
    assert.equal(await out.svc.videoEndpoint(), undefined)
    assert.equal((await out.api('GET', '/models')).body.slots.video.off, true)
    assert.equal((await out.svc.media()).video.off, true)
    // 0.1.40's Media page sends the id alone: whichever source lists it
    await out.api('POST', '/media', { videoModel: 'wan2.2-i2v-flash' })
    assert.equal((await out.svc.videoEndpoint()).instanceId, PROVIDER_ID)
    assert.equal((await out.api('POST', '/video-model', { model: 'nope', provider: 'nobody' })).status, 400)
  } finally {
    await server.close()
    await out.done()
  }
})

test('Automatic: an empty model drops the stored choice and the slot follows the order again; the view says what the order gives while a choice is in force', async () => {
  const out = await cloud({ signedIn: true })
  const server = await modelsServer(BAILIAN_MODELS)
  try {
    await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-test', baseURL: server.url })
    await out.api('POST', '/chat-model', { model: 'deepseek-v4.1-flash', provider: PROVIDER_ID })
    // nothing stored: every dependent row is automatic and `auto` is the row's own value
    let view = (await out.api('GET', '/models')).body
    for (const slot of ['hands', 'image', 'video']) {
      assert.equal(view.slots[slot].chosen, false, slot)
      assert.deepEqual(view.slots[slot].auto, { provider: PROVIDER_ID, providerLabel: 'nanoMuse Cloud', model: view.slots[slot].model }, slot)
    }
    // explicit choices on the own row; `auto` still names what the order would give (the account)
    await out.api('POST', '/hands-model', { model: 'qwen3-vl-plus', provider: 'bailian' })
    await out.api('POST', '/image-model', { model: 'qwen-image-3.0', provider: 'bailian' })
    await out.api('POST', '/video-model', { model: 'wan2.2-i2v-flash', provider: 'bailian' })
    view = (await out.api('GET', '/models')).body
    for (const slot of ['hands', 'image', 'video']) {
      assert.equal(view.slots[slot].chosen, true, slot)
      assert.equal(view.slots[slot].provider, 'bailian', slot)
      assert.equal(view.slots[slot].auto.provider, PROVIDER_ID, slot)
    }
    assert.equal(view.slots.hands.auto.model, 'qwen3.8-27b')
    assert.equal(JSON.parse(await readFile(join(out.home, 'hands.json'), 'utf8')).model, 'qwen3-vl-plus')
    // the Automatic entry: an empty model, the same routes; chat and the other rows stay as they were
    assert.equal((await out.api('POST', '/hands-model', { model: '' })).status, 200)
    assert.deepEqual(out.svc.handsChoice(), { provider: PROVIDER_ID, model: 'qwen3.8-27b' })
    assert.equal(JSON.parse(await readFile(join(out.home, 'hands.json'), 'utf8')).model, 'qwen3.8-27b')
    assert.equal((await out.svc.imageEndpoint()).instanceId, 'bailian')
    assert.equal((await out.api('POST', '/image-model', { model: '' })).status, 200)
    assert.equal((await out.svc.imageEndpoint()).instanceId, PROVIDER_ID)
    assert.equal((await out.api('POST', '/media', { videoModel: '' })).status, 200)
    assert.equal((await out.svc.videoEndpoint()).instanceId, PROVIDER_ID)
    view = (await out.api('GET', '/models')).body
    assert.deepEqual(out.selection.current, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' })
    for (const slot of ['hands', 'image', 'video']) assert.equal(view.slots[slot].chosen, false, slot)
    assert.equal(out.state().handsModel, undefined)
    assert.equal(out.state().media?.imageModel, undefined)
    assert.equal(out.state().media?.videoModel, undefined)
    // the order moves with chat again: chat to the own row, the three follow it
    await out.api('POST', '/chat-model', { model: 'deepseek-v4.1-flash', provider: 'bailian' })
    assert.equal(out.svc.handsChoice().provider, 'bailian')
    assert.equal((await out.svc.imageEndpoint()).instanceId, 'bailian')
    assert.equal((await out.svc.videoEndpoint()).instanceId, 'bailian')
  } finally {
    await server.close()
    await out.done()
  }
})

test('the "Use it for" card: the offer names the slots the row can take and the model each gets; Use it switches the ticked ones through the same setters, the rest stays', async () => {
  const out = await cloud({ signedIn: true, defaultModel: { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' } })
  const server = await modelsServer(BAILIAN_MODELS)
  try {
    const saved = await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-test', baseURL: server.url })
    assert.deepEqual(saved.body.offer, { chat: 'deepseek-v4.1-flash', hands: 'qwen3.8-27b', image: 'qwen-image-3.0', video: 'wan2.2-i2v-flash' })
    // the account had a default already: nothing moved by the save itself
    assert.deepEqual(out.selection.current, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' })
    assert.deepEqual(out.svc.handsChoice(), { provider: PROVIDER_ID, model: 'qwen3.8-27b' })
    // Not now is the browser doing nothing; Use it with hands and image ticked
    const adopted = await out.api('POST', '/providers/adopt', { id: 'bailian', slots: ['hands', 'image', 'nope'] })
    assert.equal(adopted.status, 200)
    assert.deepEqual(adopted.body.done, { hands: 'qwen3.8-27b', image: 'qwen-image-3.0' })
    assert.deepEqual(out.selection.current, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' })
    assert.deepEqual(out.svc.handsChoice(), { provider: 'bailian', model: 'qwen3.8-27b' })
    assert.equal((await out.svc.imageEndpoint()).instanceId, 'bailian')
    assert.equal((await out.svc.videoEndpoint()).instanceId, PROVIDER_ID)
    // all four
    await out.api('POST', '/providers/adopt', { id: 'bailian', slots: ['chat', 'hands', 'image', 'video'] })
    assert.deepEqual(out.selection.current, { provider: 'bailian', model: 'deepseek-v4.1-flash' })
    assert.equal((await out.svc.videoEndpoint()).instanceId, 'bailian')
    assert.equal((await out.api('POST', '/providers/adopt', { id: 'nobody', slots: ['chat'] })).status, 404)
  } finally {
    await server.close()
    await out.done()
  }
})

test('the offer of a chat-only row is chat alone; a row with vision but no listed image model offers no image', async () => {
  const out = await cloud()
  const server = await modelsServer(['deepseek-flash', 'deepseek-reasoner'])
  try {
    const saved = await out.api('POST', '/providers/save', { id: 'deepseek', apiKey: 'sk-ds', baseURL: server.url })
    // deepseek-flash is the catalogue's hands default too: chat and hands, never image or video
    assert.deepEqual(saved.body.offer, { chat: 'deepseek-flash', hands: 'deepseek-flash' })
    assert.deepEqual(out.svc.slotOffer('nobody'), {})
  } finally {
    await server.close()
    await out.done()
  }
})

// ---- the own-provider image shapes, with a fake fetch -------------------------------------------

const PNG = Buffer.from('89504e470d0a1a0a', 'hex')

function fakeFetch(handler) {
  const calls = []
  const impl = async (url, init = {}) => {
    const call = { url: String(url), method: init.method ?? 'GET', headers: init.headers ?? {}, body: init.body }
    calls.push(call)
    const reply = await handler(call)
    if (reply instanceof Buffer) return new Response(reply, { status: 200 })
    return new Response(JSON.stringify(reply.body ?? reply), { status: reply.status ?? 200, headers: { 'content-type': 'application/json' } })
  }
  return { impl, calls }
}

test('imageShapeOf: OpenRouter and Model Studio by id or host, everything else OpenAI’s shape', () => {
  assert.equal(imageShapeOf('openrouter', 'https://openrouter.ai/api/v1'), 'openrouter')
  assert.equal(imageShapeOf('custom', 'https://openrouter.ai/api/v1'), 'openrouter')
  assert.equal(imageShapeOf('bailian', 'https://dashscope.aliyuncs.com/compatible-mode/v1'), 'dashscope')
  assert.equal(imageShapeOf('custom', 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'), 'dashscope')
  for (const id of ['openai', 'zhipu', 'siliconflow', 'volcengine', 'xai', 'gemini']) assert.equal(imageShapeOf(id, 'https://example.invalid/v1'), 'openai', id)
})

test('OpenAI shape: /images/generations with b64_json, /images/edits as a form; x.ai takes no size, gpt-image no response_format', async () => {
  const openai = fakeFetch(() => ({ data: [{ b64_json: PNG.toString('base64') }] }))
  const ep = { shape: 'openai', baseURL: 'https://api.openai.com/v1', apiKey: 'sk-1', model: 'dall-e-3', label: 'OpenAI', instanceId: 'openai' }
  assert.deepEqual(await generateImage(ep, 'a fox', openai.impl), PNG)
  assert.equal(openai.calls[0].url, 'https://api.openai.com/v1/images/generations')
  assert.equal(openai.calls[0].headers.authorization, 'Bearer sk-1')
  assert.deepEqual(JSON.parse(openai.calls[0].body), { model: 'dall-e-3', prompt: 'a fox', n: 1, size: '1024x1024', response_format: 'b64_json' })
  await editImage(ep, PNG, 'smile', openai.impl)
  assert.equal(openai.calls[1].url, 'https://api.openai.com/v1/images/edits')
  assert.ok(openai.calls[1].body instanceof FormData)
  assert.equal(openai.calls[1].body.get('model'), 'dall-e-3')
  assert.equal(openai.calls[1].body.get('prompt'), 'smile')
  assert.ok(openai.calls[1].body.get('image') instanceof Blob)
  // gpt-image-*: no response_format (they answer inline); x.ai: no size
  const gpt = fakeFetch(() => ({ data: [{ b64_json: PNG.toString('base64') }] }))
  await generateImage({ ...ep, model: 'gpt-image-2.5-flare' }, 'a fox', gpt.impl)
  assert.equal('response_format' in JSON.parse(gpt.calls[0].body), false)
  const xai = fakeFetch(() => ({ data: [{ url: 'https://cdn.x.ai/pic.png' }] }))
  xai.impl2 = xai.impl
  const bytes = await generateImage({ ...ep, baseURL: 'https://api.x.ai/v1', model: 'grok-imagine-image-2.0' }, 'a fox', async (url, init) => (String(url).endsWith('pic.png') ? new Response(PNG) : xai.impl(url, init)))
  assert.deepEqual(bytes, PNG)
  assert.equal('size' in JSON.parse(xai.calls[0].body), false)
  // a refusal is the provider's sentence, not a stack
  const refused = fakeFetch(() => ({ status: 402, body: { error: { message: 'Insufficient balance', code: 'insufficient_quota' } } }))
  await assert.rejects(generateImage(ep, 'a fox', refused.impl), (err) => err.status === 402 && err.code === 'insufficient_quota' && err.message === 'Insufficient balance')
})

test('Model Studio shape: the native multimodal-generation route on the row’s host, the picture fetched from the URL; poses go through qwen-image-edit when the model cannot take a picture', async () => {
  const ds = fakeFetch((call) => (call.url.endsWith('/out.png') ? PNG : { output: { choices: [{ message: { content: [{ image: 'https://oss.example.invalid/out.png' }] } }] } }))
  const ep = { shape: 'dashscope', baseURL: 'https://dashscope.aliyuncs.com/compatible-mode/v1', apiKey: 'sk-ds', model: 'qwen-image-3.0', label: 'Model Studio', instanceId: 'bailian' }
  assert.deepEqual(await generateImage(ep, 'a fox', ds.impl), PNG)
  assert.equal(ds.calls[0].url, 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation')
  const body = JSON.parse(ds.calls[0].body)
  assert.equal(body.model, 'qwen-image-3.0')
  assert.deepEqual(body.input.messages[0].content, [{ text: 'a fox' }])
  assert.deepEqual(body.parameters, { size: '1024*1024', watermark: false, prompt_extend: false })
  assert.equal(ds.calls[1].url, 'https://oss.example.invalid/out.png')
  await editImage(ep, PNG, 'smile', ds.impl)
  const pose = JSON.parse(ds.calls[2].body)
  assert.equal(pose.model, 'qwen-image-3.0')
  assert.equal(pose.input.messages[0].content.length, 2)
  assert.ok(pose.input.messages[0].content[0].image.startsWith('data:image/png;base64,'))
  await editImage({ ...ep, model: 'qwen-image' }, PNG, 'smile', ds.impl)
  assert.equal(JSON.parse(ds.calls[4].body).model, 'qwen-image-edit-max')
})

test('OpenRouter shape: POST {base}/images with output_format png; a pose carries the picture as an input reference', async () => {
  const or = fakeFetch(() => ({ data: [{ b64_json: PNG.toString('base64') }] }))
  const ep = { shape: 'openrouter', baseURL: 'https://openrouter.ai/api/v1', apiKey: 'sk-or', model: 'openai/gpt-image-2', label: 'OpenRouter', instanceId: 'openrouter' }
  assert.deepEqual(await generateImage(ep, 'a fox', or.impl), PNG)
  assert.equal(or.calls[0].url, 'https://openrouter.ai/api/v1/images')
  assert.deepEqual(JSON.parse(or.calls[0].body), { model: 'openai/gpt-image-2', prompt: 'a fox', n: 1, size: '1024x1024', output_format: 'png' })
  await editImage(ep, PNG, 'smile', or.impl)
  const pose = JSON.parse(or.calls[1].body)
  assert.equal(pose.input_references[0].type, 'image_url')
  assert.ok(pose.input_references[0].image_url.url.startsWith('data:image/png;base64,'))
})

test('the hands row says why: the mount’s outcome reaches hands/runtime, with the cause behind a colon', async () => {
  const { mountError, apply } = await import('../lib/hands-tools.js')
  assert.equal(mountError(new Error('mcp-client(nanomuse): initial connection or tool synchronization failed', { cause: new Error('spawn /opt/nanomuse ENOENT') })), 'initial connection or tool synchronization failed: spawn /opt/nanomuse ENOENT')
  assert.equal(mountError(new Error('bad config')), 'bad config')
  assert.equal(mountError('a string'), 'a string')
  assert.equal(mountError(new Error('')), 'the hands did not mount')

  const out = await cloud()
  try {
    // before any mount: nothing known to be wrong
    assert.deepEqual(out.svc.handsStatus(), { at: 0, ok: true, reason: '' })
    // a fake agent scope: the plugin's client is a fiber whose start fails the way the MCP client reports it
    let plugins = 0
    const effects = []
    const ctx = {
      nanomuseCloud: out.svc,
      logger: { info() {}, warn() {}, debug() {}, error() {} },
      plugin() {
        plugins++
        return { await: () => Promise.reject(new Error('mcp-client(nanomuse): initial connection or tool synchronization failed', { cause: new Error('spawn /opt/nanomuse ENOENT') })), dispose: async () => undefined }
      },
      effect(fn) { effects.push(fn) },
    }
    apply(ctx)
    await new Promise((r) => setTimeout(r, 50))
    assert.equal(plugins, 1)
    const status = out.svc.handsStatus()
    assert.equal(status.ok, false)
    assert.equal(status.reason, 'initial connection or tool synchronization failed: spawn /opt/nanomuse ENOENT')
    assert.ok(status.at > 0)
    const runtime = (await out.api('GET', '/hands/runtime')).body
    assert.equal(runtime.ok, false)
    assert.equal(runtime.problem, 'missing')
    assert.deepEqual(runtime.mount, status)
    // a mount that goes well clears it
    out.svc.handsMounted({ ok: true })
    assert.deepEqual(out.svc.handsStatus().reason, '')
    assert.equal(out.svc.handsStatus().ok, true)
    for (const fn of effects) { const off = fn(); if (typeof off === 'function') off() }
  } finally {
    await out.done()
  }
})

// The main chat follows the chat slot (the phones' rule, 1.0.0): a pick on the Models page or
// the "Use it for" card moves the one conversation the Chat tab always shows; side chats keep
// theirs; a session that already says so is not written again.
function fakeSessions(selections) {
  const moved = []
  const sessionController = {
    async resolveAgent(sessionId) {
      const config = selections[sessionId]
      return config ? { agent: { session: { id: sessionId, requestHeader: () => ({ config }) } } } : { error: 'no such session' }
    },
    async selectModel({ sessionId, provider, model }) {
      moved.push({ sessionId, provider, model })
      selections[sessionId] = { provider, model }
    },
  }
  return { moved, ctx: { sessionController, get() { return undefined } } }
}

test('picking the chat model moves the main chat and only it; the same pick twice writes nothing; without a main chat nothing moves', async () => {
  const out = await cloud({ signedIn: true })
  try {
    const sessions = fakeSessions({ 's-main': { provider: PROVIDER_ID, model: 'deepseek-v4.1' }, 's-side': { provider: PROVIDER_ID, model: 'deepseek-v4.1' } })
    out.svc.sessionCtx = sessions.ctx
    // no main chat known yet: the slot moves, no session does
    assert.equal((await out.api('POST', '/chat-model', { model: 'deepseek-v4.1-flash', provider: PROVIDER_ID })).status, 200)
    assert.deepEqual(sessions.moved, [])
    out.svc.sync = { state: { mainSession: 's-main' } }
    assert.equal((await out.api('POST', '/chat-model', { model: 'deepseek-v4.1', provider: PROVIDER_ID })).status, 200)
    // the main chat already answers through deepseek-v4.1: nothing written
    assert.deepEqual(sessions.moved, [])
    assert.equal((await out.api('POST', '/chat-model', { model: 'deepseek-v4.1-flash', provider: PROVIDER_ID })).status, 200)
    assert.deepEqual(sessions.moved, [{ sessionId: 's-main', provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' }])
    assert.deepEqual(out.selection.current, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' })
    // the side chat is where it was
    assert.deepEqual((await sessions.ctx.sessionController.resolveAgent('s-side')).agent.session.requestHeader().config, { provider: PROVIDER_ID, model: 'deepseek-v4.1' })
    // the same pick again: the equality guard, no second write
    assert.equal((await out.api('POST', '/chat-model', { model: 'deepseek-v4.1-flash', provider: PROVIDER_ID })).status, 200)
    assert.equal(sessions.moved.length, 1)
  } finally {
    await out.done()
  }
})

test('the "Use it for" card moves the main chat to the own key too; a main chat on Cloud for one turn comes back to the pick instead', async () => {
  const out = await cloud({ signedIn: true, defaultModel: { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' } })
  const server = await modelsServer(BAILIAN_MODELS)
  try {
    const sessions = fakeSessions({ 's-main': { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' } })
    out.svc.sessionCtx = sessions.ctx
    out.svc.sync = { state: { mainSession: 's-main' } }
    await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-own', baseURL: server.url })
    assert.deepEqual(sessions.moved, [])
    const adopted = await out.api('POST', '/providers/adopt', { id: 'bailian', slots: ['chat'] })
    assert.equal(adopted.status, 200)
    assert.equal(sessions.moved.length, 1)
    assert.equal(sessions.moved[0].sessionId, 's-main')
    assert.equal(sessions.moved[0].provider, 'bailian')
    // held on the account for one turn: the hold's way back becomes the new pick, the session is not touched mid-turn
    out.svc.cloudOnce.set('s-main', { provider: 'bailian', model: sessions.moved[0].model, at: 1 })
    assert.equal((await out.api('POST', '/chat-model', { model: 'deepseek-v4.1', provider: PROVIDER_ID })).status, 200)
    assert.equal(sessions.moved.length, 1)
    assert.deepEqual(out.svc.cloudOnce.get('s-main'), { provider: PROVIDER_ID, model: 'deepseek-v4.1', at: 1 })
  } finally {
    await server.close()
    await out.done()
  }
})
