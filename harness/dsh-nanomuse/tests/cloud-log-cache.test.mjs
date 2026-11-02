// The sync's session-log cache: an entry holds a session's whole decompressed
// transcript, read in full by `inspect`, so the cache keeps the account's newest
// few dozen chats — the ones the column and the sync actually touch — and gives
// the longest-untouched away, to be read again if ever asked for; not every chat
// the process has ever heard of, for the life of the process.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Service } from '@deepseek-ai/cordis'
import NanomuseCloud, { LLM_ROW, TOKEN_REF } from '../lib/cloud.js'

process.env.NANOMUSE_PY = join(tmpdir(), 'nanomuse-runtime-that-does-not-exist')

function fakeContext() {
  const credentials = new Map()
  const settings = { [LLM_ROW]: { providers: {} } }
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
        for (const [k, v] of Object.entries(patch)) row[k] = v
      },
      async mutate() {},
      describe() { return Object.entries(settings).map(([ns, value]) => ({ ns, value })) },
    },
    get(name) {
      if (name === 'agentDefaultModel') return { currentSelection: () => ({ provider: 'deepseek-official', model: 'deepseek-chat' }), saveSelection: async () => undefined }
      if (name === 'llm') return { listProviders: () => [] }
      return undefined
    },
    inject() {},
    effect(fn) { fn() },
    on() { return () => undefined },
  }
  return { ctx }
}

async function make() {
  const home = await mkdtemp(join(tmpdir(), 'nm-cloud-logcache-'))
  const statePath = join(home, 'cloud.json')
  await writeFile(statePath, JSON.stringify({}))
  const fake = fakeContext()
  await fake.ctx.credentials.set(TOKEN_REF, 'account-key')
  const svc = new NanomuseCloud(fake.ctx, { baseURL: 'https://relay.invalid', deviceName: 'test-desktop', statePath })
  svc.hub.start = () => undefined
  svc.refresh = async () => svc.status()
  await svc[Service.init]()
  return { svc, done: () => rm(home, { recursive: true, force: true }) }
}

test('the log cache keeps the newest chats and gives the oldest away', async () => {
  const { svc, done } = await make()
  try {
    for (let i = 0; i < 200; i++) svc.cached(`s-${i}`)
    assert.ok(svc.logCache.size <= 64, `cache grew unbounded: ${svc.logCache.size}`)
    assert.ok(svc.logCache.has('s-199'), 'the newest entry must stay')
    assert.ok(!svc.logCache.has('s-0'), 'the oldest entry must go')
    // a given-away entry comes back as a fresh one: it is read again, not stale
    const again = svc.cached('s-0')
    assert.deepEqual(again, {})
    assert.ok(svc.logCache.size <= 64)
  } finally {
    await done()
  }
})

test('reading a cached session refreshes its eviction order', async () => {
  const { svc, done } = await make()
  try {
    for (let i = 0; i < 64; i++) svc.cached(`s-${i}`)
    // Reading a quiet session refreshes it without requiring a new event.
    svc.cached('s-0')
    svc.cached('s-64')
    assert.ok(svc.logCache.has('s-0'), 'the session that just changed must not be the one given away')
    assert.ok(!svc.logCache.has('s-1'), 'the longest untouched must go instead')
    // the dropped-and-re-added entry starts fresh, not stale
    svc.logChanged('s-64')
    assert.ok(!svc.logCache.has('s-64'))
    assert.deepEqual(svc.cached('s-64'), {})
  } finally {
    await done()
  }
})
