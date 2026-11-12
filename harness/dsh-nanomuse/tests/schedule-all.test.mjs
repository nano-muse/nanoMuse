// Scheduled tasks are the person's, not one chat's: `schedule_list_all` reads every chat's
// active tasks, this chat's first, with the chat each runs in.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { scheduleRows } from '../lib/rooms-tools.js'

const entry = (id, sessionId, extra = {}) => ({ id, sessionId, status: 'active', kind: 'cron', title: `Task ${id}`, scheduledAt: '2026-11-12T02:00:00.000Z', expression: '*/15 10-11 * * *', timeZone: 'Asia/Shanghai', ...extra })

test('every chat’s active tasks, this chat’s first, with their chat', () => {
  const rows = scheduleRows(
    [entry('a', 'session-other'), entry('b', 'session-here'), entry('c', 'session-other', { status: 'inactive' })],
    'session-here',
    new Map([['session-other', 'Reminders'], ['session-here', 'Today']]),
  )
  assert.deepEqual(rows.map((r) => r.id), ['b', 'a'])
  assert.deepEqual(rows[1], { id: 'a', title: 'Task a', rule: 'cron */15 10-11 * * *', time_zone: 'Asia/Shanghai', next_run: '2026-11-12T02:00:00.000Z', chat_id: 'session-other', chat_title: 'Reminders', this_chat: false })
  assert.equal(rows[0].this_chat, true)
})

test('a chat whose title cannot be read still lists its tasks', () => {
  const rows = scheduleRows([entry('a', 'session-x', { kind: 'daily', time: '09:00:00.000', expression: undefined })], 'session-here', new Map())
  assert.equal(rows[0].chat_title, '')
  assert.equal(rows[0].rule, 'daily@09:00')
})

// Exercise the registered tools, including suspension points where the account or task changes.
import { apply } from '../lib/rooms-tools.js'
import NanomuseCloud from '../lib/cloud.js'

function fixture(entries = [entry('a', 'session-other')], options = {}) {
  const tools = new Map()
  const removed = []
  const requests = []
  const hidden = new Set(['session-hidden'])
  let active = true
  let rows = entries
  const ctx = {
    nanomuseRooms: {},
    nanomuseCloud: {
      scheduleSessionAccess: () => (id) => active && Boolean(id) && !hidden.has(id),
      async chatTitle(id) { await options.title?.(id); return `Chat ${id}` },
    },
    tools: { register(tool) { tools.set(tool.name, tool); return () => {} } },
    effect(fn) { return fn() },
    inject() {},
    get(name) {
      if (name === 'schedule') return {
        async catalog() { await options.catalog?.(); return rows },
        async delete(value) { removed.push(value); return { id: value.id, deleted: true } },
      }
      if (name === 'approval' && options.approval !== false) return {
        async request(value) { requests.push(value); return options.answer ? options.answer(value) : 'allowed-once' },
      }
    },
  }
  apply(ctx)
  const abort = new AbortController()
  const exec = { agent: { session: { id: 'session-here' } }, callId: 'schedule-call', signal: abort.signal }
  return {
    removed, requests, abort, hidden, exec,
    invalidate() { active = false },
    replace(next) { rows = next },
    run(name, args = {}) { return tools.get(name).execute(args, exec) },
  }
}

test('registered catalogue omits inaccessible and inactive tasks before reading titles', async () => {
  const read = []
  const f = fixture([entry('a', 'session-other'), entry('b', 'session-hidden'), entry('c', 'session-other', { status: 'inactive' })], { title: (id) => read.push(id) })
  assert.deepEqual((await f.run('schedule_list_all')).tasks.map((row) => row.id), ['a'])
  assert.deepEqual(read, ['session-other'])
})

test('catalogue read fails closed if the account changes while loading titles', async () => {
  const f = fixture(undefined, { title: () => f.invalidate() })
  await assert.rejects(f.run('schedule_list_all'), /no longer active/)
})

test('cross-chat deletion requests native approval and retains its original session', async () => {
  const f = fixture()
  assert.deepEqual(await f.run('schedule_delete_any', { id: 'a' }), { id: 'a', deleted: true, title: 'Task a' })
  assert.deepEqual(f.removed, [{ id: 'a', sessionId: 'session-other' }])
  assert.equal(f.requests.length, 1)
  assert.equal(f.requests[0].agent, f.exec.agent)
  assert.equal(f.requests[0].callId, 'schedule-call')
  assert.equal(f.requests[0].toolName, 'schedule_delete_any')
  assert.equal(f.requests[0].signal, f.exec.signal)
  assert.match(f.requests[0].reason, /Task a.*session-other/)
})

test('a denial or unavailable approval service cannot delete a task', async () => {
  for (const options of [{ answer: () => 'rejected' }, { answer: () => 'cancelled' }, { approval: false }]) {
    const f = fixture(undefined, options)
    await assert.rejects(f.run('schedule_delete_any', { id: 'a' }), /not approved|not available/)
    assert.deepEqual(f.removed, [])
  }
})

test('an inaccessible target reveals no title and does not request approval', async () => {
  const f = fixture([entry('a', 'session-hidden')])
  assert.deepEqual(await f.run('schedule_delete_any', { id: 'a' }), { id: 'a', deleted: false, title: '' })
  assert.deepEqual(f.requests, [])
  assert.deepEqual(f.removed, [])
})

test('account change, target clear and cancellation during approval all prevent deletion', async () => {
  for (const change of [(f) => f.invalidate(), (f) => f.hidden.add('session-other'), (f) => f.abort.abort()]) {
    const f = fixture(undefined, { answer: () => { change(f); return 'allowed-once' } })
    await assert.rejects(f.run('schedule_delete_any', { id: 'a' }), /no longer active/)
    assert.deepEqual(f.removed, [])
  }
})

test('changed or moved tasks need new approval, while next-run advancement does not', async () => {
  for (const changed of [{ title: 'Changed' }, { expression: '0 8 * * *' }, { prompt: 'Different instructions' }, { sessionId: 'session-new' }]) {
    const f = fixture(undefined, { answer: () => { f.replace([entry('a', 'session-other', changed)]); return 'allowed-once' } })
    const result = await f.run('schedule_delete_any', { id: 'a' }).catch((error) => error)
    assert.ok(result instanceof Error || result.deleted === false)
    assert.deepEqual(f.removed, [])
  }
  const f = fixture(undefined, { answer: () => { f.replace([entry('a', 'session-other', { scheduledAt: '2026-11-13T02:00:00.000Z' })]); return 'allowed-once' } })
  assert.equal((await f.run('schedule_delete_any', { id: 'a' })).deleted, true)
})

function cloudScope() {
  const cloud = Object.create(NanomuseCloud.prototype)
  cloud.accountEpoch = 1
  cloud.changingAccount = false
  cloud.sessionStateLoaded = true
  cloud.state = { account: { id: 'account-own' }, sync: { owners: { foreign: 'account-other', mine: 'account-own' }, cleared: { cleared: 1 } } }
  cloud.sessionCtx = { sessions: new Map([
    ['child', { header: { origin: 'subagent', parentSession: 'foreign' } }],
    ['cleared-child', { header: { origin: 'subagent', parentSession: 'cleared' } }],
  ]) }
  return cloud
}

test('real cloud scope blocks cleared and foreign sessions, including loaded descendants', () => {
  const cloud = cloudScope()
  const access = cloud.scheduleSessionAccess('mine')
  assert.equal(access('mine'), true)
  assert.equal(access('legacy'), true)
  for (const id of ['', 'foreign', 'cleared', 'child', 'cleared-child']) assert.equal(access(id), false, id)
  cloud.sessionStateLoaded = false
  assert.equal(access('mine'), false)
})

test('real cloud scope pins caller and account across sign-out, transitions and clears', () => {
  const changes = [
    (cloud) => cloud.accountEpoch++,
    (cloud) => { cloud.state.account = { id: 'account-other' } },
    (cloud) => { cloud.changingAccount = true },
    (cloud) => { cloud.state.accountTransition = {} },
    (cloud) => { cloud.state.sync.cleared.mine = 1 },
  ]
  for (const change of changes) {
    const cloud = cloudScope()
    const access = cloud.scheduleSessionAccess('mine')
    change(cloud)
    assert.equal(access('legacy'), false)
  }
})


test('signed-out chats do not expose tasks known to belong to an account', () => {
  const cloud = cloudScope()
  cloud.state.account = undefined
  const access = cloud.scheduleSessionAccess('local')
  assert.equal(access('legacy'), true)
  assert.equal(access('mine'), false)
  assert.equal(access('foreign'), false)
})
