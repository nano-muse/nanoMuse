// Account snapshots are flushed before replacement and keep one complete private backup.
// Concurrent saves preserve invocation order; failures preserve the previous recoverable state.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
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

async function service(statePath) {
  const fake = fakeContext()
  await fake.ctx.credentials.set(TOKEN_REF, 'account-key')
  const svc = new NanomuseCloud(fake.ctx, { baseURL: 'https://relay.invalid', deviceName: 'test-desktop', statePath })
  svc.hub.start = () => undefined
  svc.refresh = async () => svc.status()
  return svc
}

async function make(state = {}) {
  const home = await mkdtemp(join(tmpdir(), 'nm-cloud-state-'))
  const statePath = join(home, 'cloud.json')
  await writeFile(statePath, JSON.stringify(state), { mode: 0o600 })
  const svc = await service(statePath)
  svc.state = await svc.readState()
  return {
    svc,
    statePath,
    backupPath: `${statePath}.bak`,
    home,
    done: () => rm(home, { recursive: true, force: true }),
  }
}

test('the account snapshot is replaced whole and keeps the previous private backup', async () => {
  const { svc, statePath, backupPath, home, done } = await make({ deviceName: 'first', deviceId: 'dev-1' })
  try {
    assert.equal(svc.state.deviceName, 'first')
    svc.state.deviceName = 'renamed-desktop'
    await svc.writeState()
    const raw = JSON.parse(await readFile(statePath, 'utf8'))
    assert.equal(raw.deviceName, 'renamed-desktop')
    assert.equal(raw.deviceId, 'dev-1')
    assert.equal(JSON.parse(await readFile(backupPath, 'utf8')).deviceName, 'first')
    assert.deepEqual((await readdir(home)).sort(), ['cloud.json', 'cloud.json.bak'])
    if (process.platform !== 'win32') {
      assert.equal((await stat(statePath)).mode & 0o777, 0o600)
      assert.equal((await stat(backupPath)).mode & 0o777, 0o600)
    }
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

test('concurrent snapshot requests finish in order and leave the penultimate backup', async () => {
  const { svc, statePath, backupPath, home, done } = await make({ deviceName: 'first' })
  try {
    const writes = []
    for (let i = 0; i < 24; i++) {
      svc.state.deviceName = `snapshot-${i}`
      writes.push(svc.writeState())
    }
    await Promise.all(writes)
    assert.equal(JSON.parse(await readFile(statePath, 'utf8')).deviceName, 'snapshot-23')
    assert.equal(JSON.parse(await readFile(backupPath, 'utf8')).deviceName, 'snapshot-22')
    assert.deepEqual((await readdir(home)).sort(), ['cloud.json', 'cloud.json.bak'])
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

const SAVED_STATE = {
  account: { id: 'acct-1', channel: 'email', hint: 'saved account', member: false },
  deviceId: 'dev-saved',
  remoteControl: true,
  trusted: { 'dev-friend': { name: 'Other computer', at: 123 } },
  grants: [{ id: 'grant-1', target: 'computer_app:Editor', at: 456 }],
  sync: {
    accountId: 'acct-1',
    cleared: { 'session-cleared': 'conversation-cleared' },
    legacyShape: { accepted: true },
  },
  deviceConversations: { 'acct-1': [{ legacyShape: true }] },
  providers: { incompleteLegacyRow: { label: 'Old row' } },
}

test('a damaged primary is restored from a cleaned, backward-compatible backup', async () => {
  const home = await mkdtemp(join(tmpdir(), 'nm-cloud-state-'))
  const statePath = join(home, 'cloud.json')
  const backupPath = `${statePath}.bak`
  try {
    await writeFile(backupPath, JSON.stringify({ ...SAVED_STATE, ignored: 'old-field' }), { mode: 0o644 })
    await writeFile(statePath, '{"account":', { mode: 0o644 })
    const svc = await service(statePath)
    const recovered = await svc.readState()
    assert.equal(recovered.account.id, 'acct-1')
    assert.equal(recovered.remoteControl, true)
    assert.deepEqual(recovered.grants, SAVED_STATE.grants)
    assert.deepEqual(recovered.sync, SAVED_STATE.sync)
    assert.deepEqual(recovered.deviceConversations, SAVED_STATE.deviceConversations)
    assert.deepEqual(recovered.providers, {})
    const restored = JSON.parse(await readFile(statePath, 'utf8'))
    assert.equal(restored.ignored, undefined)
    assert.deepEqual((await readdir(home)).sort(), ['cloud.json', 'cloud.json.bak'])
    if (process.platform !== 'win32') {
      assert.equal((await stat(statePath)).mode & 0o777, 0o600)
      assert.equal((await stat(backupPath)).mode & 0o777, 0o600)
    }
  } finally {
    await rm(home, { recursive: true, force: true })
  }
})

test('a missing primary is restored without leaving a temporary file', async () => {
  const home = await mkdtemp(join(tmpdir(), 'nm-cloud-state-'))
  const statePath = join(home, 'cloud.json')
  try {
    await writeFile(`${statePath}.bak`, JSON.stringify(SAVED_STATE), { mode: 0o600 })
    const recovered = await (await service(statePath)).readState()
    assert.equal(recovered.deviceId, 'dev-saved')
    assert.equal(JSON.parse(await readFile(statePath, 'utf8')).deviceId, 'dev-saved')
    assert.deepEqual((await readdir(home)).sort(), ['cloud.json', 'cloud.json.bak'])
  } finally {
    await rm(home, { recursive: true, force: true })
  }
})

test('an invalid backup cannot silently erase account or authorization state', async () => {
  const home = await mkdtemp(join(tmpdir(), 'nm-cloud-state-'))
  const statePath = join(home, 'cloud.json')
  try {
    await writeFile(statePath, '{broken')
    await writeFile(`${statePath}.bak`, JSON.stringify({ account: { id: 42 }, grants: SAVED_STATE.grants }))
    const svc = await service(statePath)
    await assert.rejects(svc.readState(), /refusing to discard saved conversation access rules/)
    assert.equal(await readFile(statePath, 'utf8'), '{broken')
  } finally {
    await rm(home, { recursive: true, force: true })
  }
})
