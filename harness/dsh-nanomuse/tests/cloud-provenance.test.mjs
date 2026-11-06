// The service's half of provenance (relay 0.31): the `nanomuse` provider row points at the
// loopback door, a call the `llm/stream` hook lets through reaches the relay with the
// session's run, turn and step and the relay's turn id is kept for the session; the
// session's events become notes for the record (a decision, a stop, a hands run closing),
// and the browser half's thumbs and stop reasons arrive through `POST /nanomuse/cloud/feedback`.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Readable } from 'node:stream'
import { Service } from '@deepseek-ai/cordis'
import NanomuseCloud, { API_PREFIX, LLM_ROW, PROVIDER_ID, TOKEN_REF } from '../lib/cloud.js'

process.env.NANOMUSE_PY = join(tmpdir(), 'nanomuse-runtime-that-does-not-exist')

/** A relay that answers `/v1/chat/completions` with a short stream and keeps the notes it is sent. */
async function relay() {
  const r = { calls: [], events: [] }
  r.server = createServer((req, res) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      const body = Buffer.concat(chunks).toString('utf8')
      if (req.url === '/v1/chat/completions') {
        r.calls.push({ headers: req.headers, body: JSON.parse(body) })
        res.writeHead(200, { 'content-type': 'text/event-stream', 'x-nanomuse-request': `req-${r.calls.length}` })
        res.end('data: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n')
      } else if (req.url === '/v1/events') {
        r.events.push({ headers: req.headers, body: JSON.parse(body) })
        res.writeHead(202, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ kept: JSON.parse(body).events.length, dropped: 0 }))
      } else {
        res.writeHead(404).end()
      }
    })
  })
  await new Promise((resolve) => r.server.listen(0, '127.0.0.1', resolve))
  // a test that never comes back (an init that waits for the loader, #701) is reported, not sat out
  r.server.unref()
  r.origin = `http://127.0.0.1:${r.server.address().port}`
  r.close = () => new Promise((resolve) => r.server.close(resolve))
  return r
}

function fakeContext() {
  const credentials = new Map()
  const settings = { [LLM_ROW]: { providers: {} } }
  const hooks = {}
  const listeners = { 'session/event': [] }
  // The loader, as dsh has it: a settings write is applied only once the plugins are up, and
  // the plugins are up only once every `Service.init` returned. `loader.ready()` is that moment.
  const waiting = []
  let loaderReady = false
  const loader = {
    ready() {
      loaderReady = true
      for (const go of waiting.splice(0)) go()
    },
    writes: 0,
  }
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
        if (!loaderReady) await new Promise((resolve) => waiting.push(resolve))
        loader.writes += 1
        const row = settings[ns] ?? (settings[ns] = {})
        for (const [k, v] of Object.entries(patch)) row[k] = k === 'providers' ? { ...row.providers, ...v } : v
      },
      async mutate() {},
      describe() { return Object.entries(settings).map(([ns, value]) => ({ ns, value })) },
    },
    get(name) {
      if (name === 'agentDefaultModel') return { currentSelection: () => ({ provider: PROVIDER_ID, model: 'deepseek-v4.1-flash' }), saveSelection: async () => undefined }
      if (name === 'llm') return { listProviders: () => Object.keys(settings[LLM_ROW].providers).map((id) => ({ id })) }
      return undefined
    },
    inject(deps, fn) { if (deps.includes('llm')) fn({ on(name, handler) { hooks[name] = handler } }) },
    effect(fn) { fn() },
    on(name, fn) {
      if (listeners[name]) listeners[name].push(fn)
      return () => undefined
    },
  }
  const emit = (sessionId, type, data) => {
    for (const fn of listeners['session/event']) fn({ id: sessionId }, { type, seq: 1, time: Date.now(), data })
  }
  return { ctx, credentials, settings, hooks, emit, loader }
}

const ACCOUNT_MODELS = [{ id: 'deepseek-v4.1-flash', name: 'DeepSeek V4.1 Flash', kind: 'chat', for: ['chat'], recommended: true }]

/** Init must come back on its own, before any settings write could be applied (#701). */
async function initWithin(svc, ms = 5_000) {
  let timer
  const late = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Service.init did not return within ${ms} ms`)), ms) })
  try {
    await Promise.race([svc[Service.init](), late])
  } finally {
    clearTimeout(timer)
  }
}

/**
 * A service brought up the way dsh does it: init first, the loader ready after. `staleDoor`
 * plants a row from an earlier start on another port; `again` is an earlier `cloud()` whose
 * state file and rows this start inherits, as a restart of the host does.
 */
async function cloud(origin, { staleDoor = false, again } = {}) {
  const home = again?.home ?? (await mkdtemp(join(tmpdir(), 'nm-cloud-prov-')))
  const statePath = join(home, 'cloud.json')
  const fake = fakeContext()
  if (again) Object.assign(fake.settings, structuredClone(again.settings))
  await fake.ctx.credentials.set(TOKEN_REF, 'account-key')
  if (staleDoor) fake.settings[LLM_ROW].providers[PROVIDER_ID] = { displayName: 'nanoMuse Cloud', api: 'openai-completions', baseURL: 'http://127.0.0.1:1/v1', apiKeyEnv: 'x', models: [{ id: 'deepseek-v4.1-flash' }] }
  if (!again) await writeFile(statePath, JSON.stringify({ deviceId: 'pc-dsh-test01', account: { id: 'acct-1', channel: 'email', hint: 'a***@example.org', member: false, region: 'intl' }, models: ACCOUNT_MODELS, update: { checkedAt: Date.now() } }))
  const svc = new NanomuseCloud(fake.ctx, { baseURL: origin, deviceName: 'test-desktop', statePath })
  svc.hub.start = () => undefined
  svc.refresh = async () => svc.status()
  await initWithin(svc)
  fake.loader.ready()
  await svc.doorPointed
  const api = async (method, route, body) => {
    const req = Readable.from(body === undefined ? [] : [Buffer.from(JSON.stringify(body))])
    req.method = method
    req.url = `${API_PREFIX}${route}`
    req.headers = {}
    const res = { status: 0, body: undefined, writeHead(status) { res.status = status; return res }, end(text) { res.body = text ? JSON.parse(text) : undefined; return res } }
    await svc.handle(req, res)
    return res
  }
  return { svc, api, home, ...fake, done: async ({ keepHome = false } = {}) => { await svc.relayDoor.close(); if (!keepHome) await rm(home, { recursive: true, force: true }) } }
}

/** The hook as dsh runs it; `next` is the adapter: it sends the request to the provider row's base, as the adapter would. */
async function callThrough(out, options) {
  const base = out.settings[LLM_ROW].providers[PROVIDER_ID].baseURL
  const next = () => (async function* () {
    const res = await fetch(`${base}/chat/completions`, {
      method: 'POST',
      headers: { authorization: 'Bearer account-key', 'content-type': 'application/json' },
      body: JSON.stringify({ model: options.model, messages: options.messages.map((m) => ({ role: m.role, content: m.content.map((c) => c.text).join('') })), stream: true }),
    })
    yield { type: 'text-delta', index: 0, text: await res.text() }
    yield { type: 'finish', reason: { kind: 'stop' } }
  })()
  const chunks = []
  for await (const chunk of out.hooks['llm/stream'].call({}, options, next)) chunks.push(chunk)
  return chunks
}

const options = (sessionId, text, extra = {}) => ({ provider: PROVIDER_ID, model: 'deepseek-v4.1-flash', sessionId, messages: [{ role: 'user', content: [{ type: 'text', text }] }], ...extra })

test('the provider row points at the door, a stale row is pointed at today\'s; a call through the hook reaches the relay with its provenance and the turn id is kept', async () => {
  const r = await relay()
  const out = await cloud(r.origin, { staleDoor: true })
  try {
    const row = out.settings[LLM_ROW].providers[PROVIDER_ID]
    assert.equal(row.baseURL, out.svc.relayDoor.openaiBase, 'the stale port was replaced')
    assert.equal(row.displayName, 'nanoMuse Cloud', 'the rest of the row stayed')
    assert.match(row.baseURL, /^http:\/\/127\.0\.0\.1:\d+\/v1$/)
    assert.equal(out.loader.writes, 1, 'one write, once the loader was ready')

    out.emit('s1', 'user/message', { source: { kind: 'schedule' }, content: [{ type: 'text', text: 'tidy up' }] })
    out.emit('s1', 'turn/start', { turn: 2 })
    out.emit('s1', 'step/start', { turn: 2, step: 1 })
    const chunks = await callThrough(out, options('s1', 'tidy up'))
    assert.equal(chunks.at(-1).type, 'finish')
    assert.equal(r.calls.length, 1)
    const h = r.calls[0].headers
    assert.equal(h.authorization, 'Bearer account-key')
    assert.equal(h['x-nanomuse-device'], 'pc-dsh-test01')
    assert.equal(h['x-nanomuse-platform'], 'desktop')
    assert.equal(h['x-nanomuse-conversation'], 's1')
    assert.equal(h['x-nanomuse-run'], 'schedule')
    assert.equal(h['x-nanomuse-turn'], '2')
    assert.equal(h['x-nanomuse-step'], '1')
    assert.equal(h['x-nanomuse-trajectory'], undefined)
    assert.deepEqual(out.svc.provenance.lastTurn('s1'), { id: 'req-1', source: 'cloud' })
    assert.equal(out.svc.provenance.waiting, 0, 'nothing left announced')

    // a side call of the harness (a title) for a session: a person's run, the turn it is on
    out.emit('s1', 'user/message', { source: { kind: 'user' }, content: [{ type: 'text', text: 'and this' }] })
    out.emit('s1', 'turn/start', { turn: 3 })
    await callThrough(out, options('s1', 'name this chat', { purpose: 'title' }))
    assert.equal(r.calls[1].headers['x-nanomuse-run'], 'person')
    assert.equal(r.calls[1].headers['x-nanomuse-turn'], '3')
    assert.equal(r.calls[1].headers['x-nanomuse-step'], undefined)
  } finally {
    await out.done()
    await r.close()
  }
})

test('#701: init returns while a stale row still waits for the loader; the row is rewritten once the loader is through', async () => {
  const r = await relay()
  const home = await mkdtemp(join(tmpdir(), 'nm-cloud-prov-'))
  const fake = fakeContext()
  await fake.ctx.credentials.set(TOKEN_REF, 'account-key')
  // the row 1.0.7 wrote: the relay itself, no door
  fake.settings[LLM_ROW].providers[PROVIDER_ID] = { displayName: 'nanoMuse Cloud', api: 'openai-completions', baseURL: `${r.origin}/v1`, apiKeyEnv: 'x', models: [{ id: 'deepseek-v4.1-flash' }] }
  await writeFile(join(home, 'cloud.json'), JSON.stringify({ deviceId: 'pc-dsh-test01', account: { id: 'acct-1', channel: 'email', hint: 'a***@example.org', member: false, region: 'intl' }, models: ACCOUNT_MODELS, update: { checkedAt: Date.now() } }))
  const svc = new NanomuseCloud(fake.ctx, { baseURL: r.origin, deviceName: 'test-desktop', statePath: join(home, 'cloud.json') })
  svc.hub.start = () => undefined
  svc.refresh = async () => svc.status()
  try {
    await initWithin(svc)
    assert.equal(fake.loader.writes, 0, 'nothing was written yet: the loader is not through')
    assert.equal(fake.settings[LLM_ROW].providers[PROVIDER_ID].baseURL, `${r.origin}/v1`, 'the old row stands until then')
    fake.loader.ready()
    await svc.doorPointed
    assert.equal(fake.loader.writes, 1)
    assert.equal(fake.settings[LLM_ROW].providers[PROVIDER_ID].baseURL, svc.relayDoor.openaiBase, 'then it points at the door')
  } finally {
    await svc.relayDoor.close()
    await rm(home, { recursive: true, force: true })
    await r.close()
  }
})

test('the next start asks for the same door port, so the row is right as it is; a port that is taken gives way, and the row is rewritten', async () => {
  const r = await relay()
  const first = await cloud(r.origin, { staleDoor: true })
  const port = first.svc.relayDoor.port
  await first.done({ keepHome: true })
  // the same profile, the port free: no write
  const second = await cloud(r.origin, { again: first })
  try {
    assert.equal(second.svc.relayDoor.port, port, 'the door is on last start\'s port')
    assert.equal(second.settings[LLM_ROW].providers[PROVIDER_ID].baseURL, `http://127.0.0.1:${port}/v1`)
    assert.equal(second.loader.writes, 0, 'nothing to rewrite')
  } finally {
    await second.done({ keepHome: true })
  }
  // the port taken by something else: another port, and the row follows
  const squatter = createServer()
  await new Promise((resolve) => squatter.listen(port, '127.0.0.1', resolve))
  const third = await cloud(r.origin, { again: second })
  try {
    assert.notEqual(third.svc.relayDoor.port, port)
    assert.equal(third.settings[LLM_ROW].providers[PROVIDER_ID].baseURL, third.svc.relayDoor.openaiBase)
    assert.equal(third.loader.writes, 1)
    assert.equal(JSON.parse(await readFile(join(third.home, 'cloud.json'), 'utf8')).doorPort, third.svc.relayDoor.port, 'the new port is the one asked for next time')
  } finally {
    await third.done()
    await new Promise((resolve) => squatter.close(resolve))
    await r.close()
  }
})

test('the session\'s events become notes: a tool\'s result closes its decision, a stop and an error end the turn, and the notes go up in one batch with the turn they are about', async () => {
  const r = await relay()
  const out = await cloud(r.origin)
  try {
    out.svc.provenance.noteTurn('s1', 'req-9', 'cloud')
    out.emit('s1', 'turn/start', { turn: 5 })
    out.emit('s1', 'tool/call', { callId: 'c1', name: 'bash', arguments: {} })
    out.emit('s1', 'tool/result', { message: { role: 'tool', toolCallId: 'c1', isError: false, content: [] } })
    out.emit('s1', 'tool/call', { callId: 'c2', name: 'write_file', arguments: {} })
    out.emit('s1', 'tool/result', { message: { role: 'tool', toolCallId: 'c2', isError: true, content: [] } })
    out.emit('s1', 'turn/end', { turn: 5, reason: { kind: 'aborted', reason: { kind: 'user' } } })
    out.emit('s2', 'turn/end', { turn: 1, reason: { kind: 'error', error: { message: 'x', code: 'UNKNOWN' } } })
    out.emit('s3', 'turn/end', { turn: 1, reason: { kind: 'completed' } })
    out.emit('s4', 'turn/end', { turn: 1, reason: { kind: 'aborted', reason: { kind: 'hook', reason: 'handing over' } } })
    assert.equal(out.svc.events.pending, 4)
    await out.svc.events.flush()
    assert.equal(r.events.length, 1)
    assert.equal(r.events[0].headers['x-nanomuse-device'], 'pc-dsh-test01')
    assert.equal(r.events[0].headers['x-nanomuse-platform'], 'desktop')
    const notes = r.events[0].body.events
    assert.deepEqual(notes.map((n) => n.kind), ['sentinel.decision', 'sentinel.decision', 'turn.ended', 'turn.ended'])
    assert.deepEqual(notes[0].data, { tool: 'bash', policy: 'allow', decision: 'allow', by: 'policy', ok: true })
    assert.equal(notes[0].turn, 'req-9')
    assert.equal(notes[0].conversation, 's1')
    assert.deepEqual(notes[1].data, { tool: 'write_file', policy: 'allow', decision: 'allow', by: 'policy', ok: false })
    assert.deepEqual(notes[2].data, { ended: 'aborted', turn_no: 5 })
    assert.deepEqual(notes[3].data, { ended: 'error', turn_no: 1 })
    assert.equal(notes[3].conversation, 's2')
    assert.equal(notes[3].turn, undefined, 'no call of that session was seen')
  } finally {
    await out.done()
    await r.close()
  }
})

test('the browser half\'s thumb and stop reason: the relay\'s words only, the turn number of the session; anything else is a 400', async () => {
  const r = await relay()
  const out = await cloud(r.origin)
  try {
    out.svc.provenance.noteTurn('s1', 'dsh-1-ab', 'own')
    out.emit('s1', 'turn/start', { turn: 2 })
    assert.equal((await out.api('POST', '/feedback', { session: 's1', vote: 'down', reason: 'wrong' })).status, 204)
    assert.equal((await out.api('POST', '/feedback', { session: 's1', vote: '' })).status, 204)
    assert.equal((await out.api('POST', '/feedback', { session: 's1', stop_reason: 'changed_mind' })).status, 204)
    assert.equal((await out.api('POST', '/feedback', { session: 's1', stop_reason: 'skipped' })).status, 204)
    assert.equal((await out.api('POST', '/feedback', { session: 's1', vote: 'sideways' })).status, 400)
    assert.equal((await out.api('POST', '/feedback', { session: 's1', vote: 'up', reason: 'it was fine, really' })).status, 400)
    assert.equal((await out.api('POST', '/feedback', { session: 's1', stop_reason: 'because' })).status, 400)
    assert.equal((await out.api('POST', '/feedback', { vote: 'up' })).status, 400)
    await out.svc.events.flush()
    const notes = r.events[0].body.events
    assert.deepEqual(notes.map((n) => [n.kind, n.data]), [
      ['turn.feedback', { vote: 'down', reason: 'wrong', turn_no: 2 }],
      ['turn.feedback', { vote: 'none', turn_no: 2 }],
      ['turn.stopped', { reason: 'changed_mind', turn_no: 2 }],
      ['turn.stopped', { reason: 'skipped', turn_no: 2 }],
    ])
    assert.ok(notes.every((n) => n.turn === 'dsh-1-ab' && n.source === 'own' && n.conversation === 's1'))
  } finally {
    await out.done()
    await r.close()
  }
})

test('a thumb on an earlier reply names that turn\'s own call; a Stop puts the question up until it is answered or the next turn starts', async () => {
  const r = await relay()
  const out = await cloud(r.origin)
  try {
    out.emit('s1', 'turn/start', { turn: 1 })
    out.svc.provenance.noteTurn('s1', 'req-1', 'cloud')
    out.emit('s1', 'turn/start', { turn: 2 })
    out.svc.provenance.noteTurn('s1', 'req-2', 'cloud')
    assert.equal((await out.api('POST', '/feedback', { session: 's1', turn_no: 1, vote: 'up' })).status, 204)
    assert.equal((await out.api('POST', '/feedback', { session: 's1', turn_no: 2, vote: 'down' })).status, 204)
    assert.equal((await out.api('POST', '/feedback', { session: 's1', turn_no: 9, vote: 'up' })).status, 204, 'a turn never seen: the note still goes, without an id')
    // the question after a Stop
    assert.deepEqual(out.svc.live().stopped, [])
    out.emit('s1', 'turn/end', { turn: 2, reason: { kind: 'aborted', reason: { kind: 'user' } } })
    assert.deepEqual(out.svc.live().stopped.map((s) => [s.session, s.turn]), [['s1', 2]])
    assert.equal((await out.api('POST', '/feedback', { session: 's1', turn_no: 2, stop_reason: 'slow' })).status, 204)
    assert.deepEqual(out.svc.live().stopped, [], 'answered')
    out.emit('s1', 'turn/end', { turn: 2, reason: { kind: 'aborted', reason: { kind: 'user' } } })
    out.emit('s1', 'turn/start', { turn: 3 })
    assert.deepEqual(out.svc.live().stopped, [], 'the next turn withdrew it')
    await out.svc.events.flush()
    const notes = r.events[0].body.events.filter((n) => n.kind === 'turn.feedback' || n.kind === 'turn.stopped')
    assert.deepEqual(notes.map((n) => [n.kind, n.data.turn_no, n.turn]), [
      ['turn.feedback', 1, 'req-1'],
      ['turn.feedback', 2, 'req-2'],
      ['turn.feedback', 9, undefined],
      ['turn.stopped', 2, 'req-2'],
    ])
  } finally {
    await out.done()
    await r.close()
  }
})
