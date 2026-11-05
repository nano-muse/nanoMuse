// Exercise real Cloud lifecycle methods with in-memory credentials and relay doubles.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import NanomuseCloud, { TOKEN_REF } from '../lib/cloud.js'
import { emptyState, SyncEngine } from '../lib/sync.js'

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const account = (id) => ({ id, hint: 'test account', channel: 'email' })
const signIn = (id) => ({ account: account(id), apiKey: `test-key-${id}` })

async function fixture(t) {
  const dir = await mkdtemp(join(tmpdir(), 'nm-cloud-transition-'))
  const statePath = join(dir, 'cloud.json')
  const credentials = new Map([[String(TOKEN_REF), 'test-key-A']])
  const ctx = {
    reflect: { provide() {} }, logger: { info() {}, warn() {}, debug() {}, error() {} },
    credentials: {
      async set(ref, value) { credentials.set(String(ref), value) },
      async resolve(ref) { const value = credentials.get(String(ref)); return value ? { value } : undefined },
      async unset(ref) { credentials.delete(String(ref)) },
    },
    settings: { async update() {}, async mutate() {}, describe: () => [] },
    get() {}, inject() {}, effect() {}, on() { return () => undefined },
  }
  const svc = new NanomuseCloud(ctx, { baseURL: 'https://relay.invalid', statePath })
  svc.state = { account: account('A'), sync: { ...emptyState(), accountId: 'A', cursor: 7, mainSession: 'chat-A', owners: { 'chat-A': 'A' }, cids: { 'chat-A': 'cid-A' } } }
  const calls = { pulls: [], pushes: [], starts: 0, keptClears: 0 }
  const engines = []
  const relay = {
    async changes(token) { calls.pulls.push(token); return { conversations: [], messages: [], cursor: 0, more: false } },
    async push(token, device, conversations, messages) { calls.pushes.push({ token, conversations, messages }); return { cursor: 0, accepted: 0, rejected: [] } },
    async working() {},
  }
  const attach = () => {
    const sync = new SyncEngine({
      relay,
      sessions: { list: async () => [], lines: async () => [], create: async () => 'new-chat', rename: async () => {}, keep: async () => {}, forget: async () => {}, forgetAll: async () => {}, inject: async () => {} },
      token: () => svc.token(), deviceId: () => 'desktop-test', load: () => svc.state.sync,
      save: async (state) => { svc.state.sync = state; await svc.writeState() },
    })
    svc.sync = sync
    engines.push(sync)
    return sync
  }
  svc.hub.stop = () => {}
  svc.hub.start = () => { calls.starts += 1 }
  svc.relay.models = async () => []
  for (const name of ['writeProvider', 'adoptDefaultModel', 'writeHands', 'publishConnectors', 'releaseChatRoute']) svc[name] = async () => {}
  svc.profile.pull = async () => {}
  svc.profile.reset = async () => {}
  svc.events.forget = () => {}
  svc.broadcast = () => {}
  svc.status = async () => ({ signedIn: Boolean(await svc.token()) && Boolean(svc.state.account) })
  svc.kept = { clear() { calls.keptClears += 1 }, async flush() {} }
  t.after(async () => { engines.forEach((sync) => sync.stop()); await svc.stateWrites; await rm(dir, { recursive: true, force: true }) })
  await svc.writeState()
  return { svc, ctx, credentials, calls, attach, saved: async () => JSON.parse(await readFile(statePath, 'utf8')) }
}

test('adopt stops the old generation before a deferred credential replacement', async (t) => {
  const { svc, ctx, attach, calls, saved } = await fixture(t)
  const sync = attach(), set = ctx.credentials.set
  const entered = deferred(), proceed = deferred()
  ctx.credentials.set = async (...args) => { entered.resolve(); await proceed.promise; await set(...args) }
  const adopting = svc.adopt(signIn('B'))
  await entered.promise
  assert.equal((await saved()).accountTransition, true)
  assert.equal(await svc.token(), undefined)
  await sync.pull(); await sync.push()
  assert.deepEqual(calls.pulls, []); assert.deepEqual(calls.pushes, [])
  proceed.resolve(); await adopting
  assert.equal(sync.state.accountId, 'B'); assert.equal(sync.state.mainSession, '')
  assert.equal((await saved()).accountTransition, undefined)
  assert.equal(await svc.token(), 'test-key-B')
  assert.ok(calls.pulls.every((key) => key === 'test-key-B'))
})

test('failure after writing a new credential remains suspended after reading state on restart', async (t) => {
  const { svc, credentials, attach, calls, saved } = await fixture(t)
  attach()
  svc.relay.models = async () => { throw new Error('catalogue unavailable') }
  await assert.rejects(svc.adopt(signIn('B')), /catalogue unavailable/)
  assert.equal(credentials.get(String(TOKEN_REF)), 'test-key-B')
  assert.equal((await saved()).account.id, 'A'); assert.equal((await saved()).accountTransition, true)
  svc.state = await svc.readState(); svc.changingAccount = false
  const restarted = attach()
  await svc.startAccountSync(restarted); await restarted.pull(); await restarted.push()
  assert.equal(await svc.token(), undefined)
  assert.deepEqual(calls.pulls, []); assert.deepEqual(calls.pushes, [])
  assert.equal(calls.starts, 0)
})

test('a failed initial state write leaves credentials untouched and sync suspended', async (t) => {
  const { svc, credentials, attach, calls } = await fixture(t)
  const sync = attach()
  svc.writeState = async () => { throw new Error('disk full') }
  await assert.rejects(svc.adopt(signIn('B')), /disk full/)
  assert.equal(credentials.get(String(TOKEN_REF)), 'test-key-A')
  await sync.pull()
  assert.deepEqual(calls.pulls, []); assert.equal(await svc.token(), undefined)
})

test('forget invalidates the current generation before a deferred credential deletion', async (t) => {
  const { svc, ctx, attach, calls, saved } = await fixture(t)
  const sync = attach(), unset = ctx.credentials.unset
  const entered = deferred(), proceed = deferred()
  ctx.credentials.unset = async (...args) => { entered.resolve(); await proceed.promise; await unset(...args) }
  const forgetting = svc.forget()
  await entered.promise
  assert.equal((await saved()).accountTransition, true)
  await sync.pull(); await sync.push()
  assert.equal(await svc.token(), undefined)
  assert.deepEqual(calls.pulls, []); assert.deepEqual(calls.pushes, [])
  proceed.resolve(); await forgetting
  assert.equal(svc.state.account, undefined)
  assert.equal((await saved()).accountTransition, undefined); assert.equal(sync.state.accountId, 'A')
})

test('a failed credential deletion stays paused, including after restart', async (t) => {
  const { svc, ctx, attach, saved } = await fixture(t)
  attach()
  ctx.credentials.unset = async () => { throw new Error('credential store busy') }
  await assert.rejects(svc.forget(), /credential store busy/)
  assert.equal((await saved()).accountTransition, true)
  svc.state = await svc.readState(); svc.changingAccount = false
  await svc.startAccountSync(attach())
  assert.equal(await svc.token(), undefined)
})

test('a sync service arriving during credential replacement waits until the account is committed', async (t) => {
  const { svc, ctx, attach, calls } = await fixture(t)
  const set = ctx.credentials.set, entered = deferred(), proceed = deferred()
  ctx.credentials.set = async (...args) => { entered.resolve(); await proceed.promise; await set(...args) }
  const adopting = svc.adopt(signIn('B'))
  await entered.promise
  const late = attach()
  await svc.startAccountSync(late); await late.pull()
  assert.deepEqual(calls.pulls, [])
  proceed.resolve(); await adopting
  assert.equal(late.state.accountId, 'B'); assert.equal(late.state.mainSession, '')
  assert.ok(calls.pulls.every((key) => key === 'test-key-B'))
})

test('sign-in before a session service binds its persisted cursor and owners', async (t) => {
  const { svc, attach, calls, saved } = await fixture(t)
  await svc.adopt(signIn('B'))
  assert.equal((await saved()).sync.accountId, 'B'); assert.equal((await saved()).sync.cursor, 0)
  assert.equal((await saved()).sync.mainSession, ''); assert.equal((await saved()).sync.owners['chat-A'], 'A')
  assert.equal(calls.keptClears, 1)
  const sync = attach()
  await svc.startAccountSync(sync)
  assert.equal(sync.state.accountId, 'B')
  assert.ok(calls.pulls.every((key) => key === 'test-key-B'))
})

test('the final state write completes before a late sync service or token reader resumes', async (t) => {
  const { svc, attach, calls } = await fixture(t)
  const write = svc.writeState.bind(svc), entered = deferred(), proceed = deferred()
  svc.writeState = async () => {
    if (!svc.state.accountTransition && svc.state.account?.id === 'B' && svc.changingAccount) { entered.resolve(); await proceed.promise }
    await write()
  }
  const adopting = svc.adopt(signIn('B'))
  await entered.promise
  const sync = attach()
  await svc.startAccountSync(sync); await sync.pull()
  assert.equal(await svc.token(), undefined); assert.deepEqual(calls.pulls, [])
  proceed.resolve(); await adopting
  assert.equal(await svc.token(), 'test-key-B'); assert.equal(sync.state.accountId, 'B')
})

test('failed final persistence keeps the pause durable and a later sign-in recovers', async (t) => {
  const { svc, attach, saved } = await fixture(t)
  const sync = attach(), write = svc.writeState.bind(svc)
  let fail = true
  svc.writeState = async () => { if (fail && !svc.state.accountTransition) throw new Error('final save failed'); await write() }
  await assert.rejects(svc.adopt(signIn('B')), /final save failed/)
  assert.equal((await saved()).accountTransition, true); assert.equal(await svc.token(), undefined)
  fail = false
  await svc.adopt(signIn('B'))
  assert.equal((await saved()).accountTransition, undefined)
  assert.equal(await svc.token(), 'test-key-B'); assert.equal(sync.state.accountId, 'B')
})

test('a credential read before sign-out cannot revive after signing into the same account', async (t) => {
  const { svc, ctx, attach } = await fixture(t)
  attach()
  const resolve = ctx.credentials.resolve, pending = deferred()
  let first = true
  ctx.credentials.resolve = (...args) => { if (first) { first = false; return pending.promise }; return resolve(...args) }
  const oldRead = svc.token()
  await svc.forget(); await svc.adopt(signIn('A'))
  pending.resolve({ value: 'retired-test-key-A' })
  assert.equal(await oldRead, undefined); assert.equal(await svc.token(), 'test-key-A')
})

test('context resolved after an account switch is never injected into the model', async (t) => {
  const { svc } = await fixture(t)
  const pending = deferred(), messages = []
  let current = true
  const ctx = { sessionController: { resolveAgent: () => pending.promise } }
  const injection = svc.injectSyncedContext(ctx, 'chat-A', 'old account context', () => current)
  current = false
  pending.resolve({ agent: { inject: (message) => messages.push(message) } })
  await injection
  assert.deepEqual(messages, [])
  current = true
  await svc.injectSyncedContext(ctx, 'chat-A', 'current account context', () => current)
  assert.equal(messages.length, 1); assert.equal(messages[0].source.kind, 'nanomuse-sync')
})

test('sync reserves the host session ID before creation can publish it or await a rename', async (t) => {
  const { svc, attach, saved, calls } = await fixture(t)
  const sync = attach(), entered = deferred(), proceed = deferred()
  let requested
  const ctx = {
    get: (name) => name === 'workspaceRegistry' ? { create: async () => ({ id: 'workspace-test' }) } : undefined,
    sessionController: {
      create: async (request) => {
        requested = request
        assert.equal((await saved()).sync.owners[request.sessionId], 'A', 'ownership must be durable before the host exposes the ID')
        entered.resolve()
        await proceed.promise
        return { sessionId: request.sessionId }
      },
      rename: async () => {},
    },
  }
  sync.options.sessions.create = (title, id) => svc.createSyncedSession(ctx, title, id)
  const creating = sync.createForAccount('Old account chat', sync.accountScope())
  await entered.promise
  assert.equal(requested.workspaceId, 'workspace-test')
  assert.equal(requested.agentPreset, 'nanomuse')
  assert.match(requested.sessionId, /^session-/)
  await svc.adopt(signIn('B'))
  assert.notEqual(await sync.setMain(requested.sessionId), requested.sessionId)
  assert.equal(sync.state.owners[requested.sessionId], 'A')
  await sync.push()
  assert.deepEqual(calls.pushes, [])
  proceed.resolve()
  assert.equal(await creating, undefined)
  assert.notEqual(sync.state.mainSession, requested.sessionId)
})
