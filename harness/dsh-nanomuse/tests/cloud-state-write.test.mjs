// Account snapshots are replaced only after the complete temporary file is written.
// Concurrent saves preserve invocation order; failures preserve the previous file.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises'
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

async function make(state = {}) {
  const home = await mkdtemp(join(tmpdir(), 'nm-cloud-state-'))
  const statePath = join(home, 'cloud.json')
  await writeFile(statePath, JSON.stringify(state))
  const fake = fakeContext()
  await fake.ctx.credentials.set(TOKEN_REF, 'account-key')
  const svc = new NanomuseCloud(fake.ctx, { baseURL: 'https://relay.invalid', deviceName: 'test-desktop', statePath })
  svc.hub.start = () => undefined
  svc.refresh = async () => svc.status()
  await svc[Service.init]()
  return { svc, statePath, home, done: () => rm(home, { recursive: true, force: true }) }
}

test('the account snapshot is written whole and renamed over, leaving nothing behind', async () => {
  const { svc, statePath, home, done } = await make({ deviceName: 'first', deviceId: 'dev-1' })
  try {
    assert.equal(svc.state.deviceName, 'first')
    svc.state.deviceName = 'renamed-desktop'
    await svc.writeState()
    const names = (await readdir(home)).filter((n) => n !== 'cloud.json')
    assert.deepEqual(names, [], 'a temp file was left behind')
    const raw = JSON.parse(await readFile(statePath, 'utf8'))
    assert.equal(raw.deviceName, 'renamed-desktop')
    assert.equal(raw.deviceId, 'dev-1')
  } finally {
    await done()
  }
})

test('a state that cannot be serialized leaves the signed-in file as it was', async () => {
  const { svc, statePath, home, done } = await make({ deviceName: 'first' })
  try {
    svc.state.deviceName = { toJSON() { throw new Error('boom') } }
    await assert.rejects(() => svc.writeState(), /boom/)
    const raw = JSON.parse(await readFile(statePath, 'utf8'))
    assert.equal(raw.deviceName, 'first', 'the previous snapshot must survive a failed write')
  } finally {
    svc.state.deviceName = 'first'
    await done()
  }
})

test('concurrent snapshot requests finish in order without sharing a temporary file', async () => {
  const { svc, statePath, home, done } = await make({ deviceName: 'first' })
  try {
    const writes = []
    for (let i = 0; i < 24; i++) {
      svc.state.deviceName = `snapshot-${i}`
      writes.push(svc.writeState())
    }
    await Promise.all(writes)
    assert.equal(JSON.parse(await readFile(statePath, 'utf8')).deviceName, 'snapshot-23')
    assert.deepEqual(await readdir(home), ['cloud.json'])
    if (process.platform !== 'win32') assert.equal((await stat(statePath)).mode & 0o777, 0o600)
  } finally { await done() }
})

test('a failed replacement cleans its temporary file and does not block a later save', async () => {
  const { svc, statePath, home, done } = await make({ deviceName: 'first' })
  try {
    await rm(statePath)
    await mkdir(statePath)
    await assert.rejects(svc.writeState())
    assert.deepEqual(await readdir(home), ['cloud.json'])
    await rm(statePath, { recursive: true })
    svc.state.deviceName = 'recovered'
    await svc.writeState()
    assert.equal(JSON.parse(await readFile(statePath, 'utf8')).deviceName, 'recovered')
  } finally { await done() }
})
