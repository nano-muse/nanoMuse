// Settings → Models → *Use nanoMuse Cloud models* switched off: the account's models leave
// every slot's list and order while the sign-in stays; the `llm/stream` hook refuses a chat
// that still sits on a Cloud model with a card of its own, sends the harness's side calls (a
// title, a compaction) to the chat slot's own model, and lets a session under *Use nanoMuse
// Cloud this time* through. The same in-memory context as cloud-models.test.mjs, plus an
// `inject` that keeps the hook so the test can call it. The switch itself is refused (`409
// chat_on_cloud`) while the chat slot is the account's and no own chat model could take it.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Readable } from 'node:stream'
import { Service } from '@deepseek-ai/cordis'
import NanomuseCloud, { API_PREFIX, CHAT_ON_CLOUD_MESSAGE, LLM_ROW, PROVIDER_ID, TOKEN_REF } from '../lib/cloud.js'
import { cloudOffFailure, refusalCard, refusalKindOf } from '../lib/refusals.js'

process.env.NANOMUSE_PY = join(tmpdir(), 'nanomuse-runtime-that-does-not-exist')

function fakeContext({ defaultModel } = {}) {
  const credentials = new Map()
  const settings = { [LLM_ROW]: { providers: {} } }
  const selection = { current: defaultModel ?? { provider: 'deepseek-official', model: 'deepseek-chat' } }
  const hooks = {}
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
    // the `llm` injection: keep the waterfall hook so the test can run it
    inject(deps, fn) { if (deps.includes('llm')) fn({ on(name, handler) { hooks[name] = handler } }) },
    effect(fn) { fn() },
    on() { return () => undefined },
  }
  return { ctx, credentials, settings, selection, hooks }
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
  { id: 'qwen3.8-27b', name: 'Qwen 3.8 27B', kind: 'chat', for: ['gui'] },
  { id: 'qwen-image-3.0', name: 'Qwen Image', kind: 'image', recommended: true },
  { id: 'wan2.2-i2v-flash', name: 'Wan', kind: 'video' },
]

async function cloud({ defaultModel, off = false } = {}) {
  const home = await mkdtemp(join(tmpdir(), 'nm-cloud-off-'))
  const statePath = join(home, 'cloud.json')
  const fake = fakeContext({ defaultModel })
  await fake.ctx.credentials.set(TOKEN_REF, 'account-key')
  await writeFile(statePath, JSON.stringify({ account: { id: 'acct-1', channel: 'email', hint: 'a***@example.org', member: false, region: 'intl' }, models: ACCOUNT_MODELS, update: { checkedAt: Date.now() }, ...(off ? { cloudModelsOff: true } : {}) }))
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
  return { svc, api, state, home, ...fake, done: () => rm(home, { recursive: true, force: true }) }
}

/** Run the `llm/stream` hook as dsh would: `this` is a runtime whose `stream` records the call, `next` the relay's stream. */
async function runHook(hooks, options, relayChunks = [{ type: 'finish', reason: { kind: 'stop' } }]) {
  const sent = []
  const runtime = { stream(opts) { sent.push(opts); return (async function* () { yield { type: 'finish', reason: { kind: 'stop' } } })() } }
  let relayCalled = false
  const next = () => { relayCalled = true; return (async function* () { for (const c of relayChunks) yield c })() }
  const chunks = []
  for await (const chunk of hooks['llm/stream'].call(runtime, options, next)) chunks.push(chunk)
  return { chunks, sent, relayCalled }
}

const BAILIAN_MODELS = ['deepseek-v4.1-flash', 'qwen3.8-27b', 'qwen3-vl-plus', 'qwen-image-3.0', 'wan2.2-i2v-flash']

test('the switch: off, the account leaves every slot and the chat default moves to the first own chat model; the sign-in stays; on again, it is back', async () => {
  const out = await cloud({ defaultModel: { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' } })
  const server = await modelsServer(BAILIAN_MODELS)
  try {
    await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-test', baseURL: server.url })
    // the chat default was the account's already, so saving the row did not move it
    assert.deepEqual(out.selection.current, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' })
    let view = (await out.api('GET', '/models')).body
    assert.equal(view.cloudModels, true)
    assert.ok(view.slots.chat.options.some((o) => o.provider === PROVIDER_ID))

    const res = await out.api('POST', '/cloud-models', { on: false })
    assert.equal(res.status, 200)
    view = res.body
    assert.equal(view.signedIn, true, 'still signed in')
    assert.equal(view.cloudModels, false)
    assert.equal((await out.state()).cloudModelsOff, true)
    assert.equal((await out.state()).account.id, 'acct-1', 'the account is kept')
    // new chats answer through the own row's catalogue default
    assert.deepEqual(out.selection.current, { provider: 'bailian', model: 'deepseek-v4.1-flash' })
    for (const slot of ['chat', 'hands', 'image', 'video']) {
      assert.ok(view.slots[slot].options.every((o) => o.provider !== PROVIDER_ID), `${slot} lists no account model`)
      assert.equal(view.slots[slot].provider, 'bailian', slot)
    }
    assert.deepEqual(out.svc.handsChoice(), { provider: 'bailian', model: 'qwen3.8-27b' })
    assert.equal((await out.svc.imageEndpoint()).instanceId, 'bailian')
    assert.equal((await out.svc.videoEndpoint()).instanceId, 'bailian')
    // the explicit one-time ask still reaches the account
    assert.equal((await out.svc.imageEndpoint({ cloud: true })).instanceId, PROVIDER_ID)
    assert.equal((await out.svc.videoEndpoint({ cloud: true })).instanceId, PROVIDER_ID)
    // the hands' environment follows
    assert.equal((await out.svc.handsEnv()).NANOMUSE_GUI_BASE_URL, server.url)
    // the Media page says the pictures come from the provider, not the account
    const media = (await out.api('GET', '/media')).body
    assert.equal(media.image.source, 'provider')
    assert.equal(media.video.source, 'provider')

    view = (await out.api('POST', '/cloud-models', { on: true })).body
    assert.equal(view.cloudModels, true)
    assert.equal((await out.state()).cloudModelsOff, undefined)
    assert.ok(view.slots.chat.options.some((o) => o.provider === PROVIDER_ID))
    // the chat default is not moved back by itself: the person's choice stands
    assert.deepEqual(out.selection.current, { provider: 'bailian', model: 'deepseek-v4.1-flash' })
  } finally {
    await server.close()
    await out.done()
  }
})

test('the switch is refused while the chat slot is the account’s and nothing of one’s own could answer: 409 chat_on_cloud, nothing changes', async () => {
  const out = await cloud({ defaultModel: { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' } })
  try {
    const res = await out.api('POST', '/cloud-models', { on: false })
    assert.equal(res.status, 409)
    assert.equal(res.body.error.code, 'chat_on_cloud')
    assert.equal(res.body.error.message, CHAT_ON_CLOUD_MESSAGE)
    assert.doesNotMatch(res.body.error.message, /[—–!]/, 'one plain sentence')
    // the state did not move: the switch is still on, the account answers, the chat slot is where it was
    assert.equal((await out.state()).cloudModelsOff, undefined)
    assert.equal(out.svc.cloudModels(), true)
    const view = (await out.api('GET', '/models')).body
    assert.equal(view.cloudModels, true)
    assert.ok(view.slots.chat.options.some((o) => o.provider === PROVIDER_ID))
    assert.deepEqual(out.selection.current, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' })
    // off → on is never refused
    assert.equal((await out.api('POST', '/cloud-models', { on: true })).status, 200)
  } finally {
    await out.done()
  }
})

test('the switch goes off when an own chat model exists: the chat slot moves there; a chat slot already on an own row is left alone', async () => {
  const out = await cloud({ defaultModel: { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' } })
  const server = await modelsServer(BAILIAN_MODELS)
  try {
    await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-test', baseURL: server.url })
    const res = await out.api('POST', '/cloud-models', { on: false })
    assert.equal(res.status, 200)
    assert.equal(res.body.cloudModels, false)
    assert.equal((await out.state()).cloudModelsOff, true)
    assert.deepEqual(out.selection.current, { provider: 'bailian', model: 'deepseek-v4.1-flash' })
    // on again, then the person picks an own model for chat: switching off touches nothing
    await out.api('POST', '/cloud-models', { on: true })
    out.selection.current = { provider: 'bailian', model: 'qwen3.8-27b' }
    assert.equal((await out.api('POST', '/cloud-models', { on: false })).status, 200)
    assert.deepEqual(out.selection.current, { provider: 'bailian', model: 'qwen3.8-27b' })
  } finally {
    await server.close()
    await out.done()
  }
})

test('off with nothing of one’s own: every slot is empty, the chat default stays where it is, and the studio says no image model rather than sign in', async () => {
  const out = await cloud({ defaultModel: { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' }, off: true })
  try {
    const view = (await out.api('GET', '/models')).body
    assert.equal(view.signedIn, true)
    assert.equal(view.cloudModels, false)
    for (const slot of ['chat', 'hands', 'image', 'video']) assert.deepEqual(view.slots[slot].options, [], slot)
    assert.deepEqual(out.svc.handsChoice(), { provider: '', model: '' })
    assert.deepEqual(await out.svc.handsEnv(), {})
    assert.equal(await out.svc.imageEndpoint(), undefined)
    assert.deepEqual(out.selection.current, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' })
    const est = await out.api('GET', '/studio/estimate')
    assert.equal(est.status, 409)
    assert.equal(est.body.error.code, 'no_image_model')
    // a sign-in (the account's models re-read) does not make the account the default while the switch is off
    const fresh = await cloud({ defaultModel: { provider: 'deepseek-official', model: 'deepseek-chat' }, off: true })
    try {
      await fresh.svc.adoptDefaultModel(ACCOUNT_MODELS)
      assert.deepEqual(fresh.selection.current, { provider: 'deepseek-official', model: 'deepseek-chat' })
    } finally {
      await fresh.done()
    }
  } finally {
    await out.done()
  }
})

test('the llm/stream hook: on, the relay is called; off, a turn is refused with the cloud_off card, a side call goes to the own chat model, and a held session goes through', async () => {
  const out = await cloud({ defaultModel: { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' } })
  const server = await modelsServer(BAILIAN_MODELS)
  try {
    assert.equal(typeof out.hooks['llm/stream'], 'function')
    // another provider: never ours to touch
    let run = await runHook(out.hooks, { provider: 'bailian', model: 'deepseek-v4.1-flash', sessionId: 's1' })
    assert.equal(run.relayCalled, true)
    // the account, switch on: the relay answers
    run = await runHook(out.hooks, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash', sessionId: 's1' })
    assert.equal(run.relayCalled, true)
    assert.deepEqual(run.chunks, [{ type: 'finish', reason: { kind: 'stop' } }])

    await out.api('POST', '/providers/save', { id: 'bailian', apiKey: 'sk-test', baseURL: server.url })
    await out.api('POST', '/cloud-models', { on: false })
    // a turn of a chat still on the account: refused here, nothing sent, the card's code
    run = await runHook(out.hooks, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash', sessionId: 's1' })
    assert.equal(run.relayCalled, false)
    assert.equal(run.sent.length, 0)
    assert.equal(run.chunks.length, 1)
    assert.equal(run.chunks[0].reason.kind, 'error')
    assert.equal(run.chunks[0].reason.failure.code, 'nanomuse/cloud_off')
    assert.equal(refusalKindOf(run.chunks[0].reason.failure.code), 'cloud_off')
    assert.deepEqual(run.chunks[0].reason.failure, cloudOffFailure())
    assert.match(run.chunks[0].reason.failure.message, /switched off/)
    assert.deepEqual(refusalCard('cloud_off').actions, ['cloud-once', 'new-chat', 'models'])
    // a side call of the harness: the chat slot's own model answers instead
    run = await runHook(out.hooks, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash', sessionId: 's1', purpose: 'session-title' })
    assert.equal(run.relayCalled, false)
    assert.equal(run.sent.length, 1)
    assert.equal(run.sent[0].provider, 'bailian')
    assert.equal(run.sent[0].model, 'deepseek-v4.1-flash')
    assert.equal(run.sent[0].purpose, 'session-title')
    // *Use nanoMuse Cloud this time* holds the session: that one goes through
    out.svc.cloudOnce.set('s1', { provider: 'bailian', model: 'deepseek-v4.1-flash', at: Date.now() })
    run = await runHook(out.hooks, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash', sessionId: 's1' })
    assert.equal(run.relayCalled, true)
    // another session is still refused
    run = await runHook(out.hooks, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash', sessionId: 's2' })
    assert.equal(run.relayCalled, false)
    // on again: through
    await out.api('POST', '/cloud-models', { on: true })
    run = await runHook(out.hooks, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash', sessionId: 's2' })
    assert.equal(run.relayCalled, true)
  } finally {
    await server.close()
    await out.done()
  }
})

test('off without any own chat model, a side call is refused too, not sent to the relay', async () => {
  const out = await cloud({ defaultModel: { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' }, off: true })
  try {
    const run = await runHook(out.hooks, { provider: PROVIDER_ID, model: 'deepseek-v4.1-flash', purpose: 'compaction' })
    assert.equal(run.relayCalled, false)
    assert.equal(run.sent.length, 0)
    assert.equal(run.chunks[0].reason.failure.code, 'nanomuse/cloud_off')
  } finally {
    await out.done()
  }
})
