// Conversations synced between the account's devices (contracts C7 and C8) on the desktop: the
// engine against a fake relay and fake sessions — the person's words pushed when sent and the
// model's at the turn's end, the whole history backfilled oldest first, the main chat as the
// account's one main conversation (adopted, merged in time order, our echo never twice), the
// other devices' chats as sessions here from the moment they are pulled, tombstones, the
// switch and the refusals. Contract C9: the side-chat switch (scope), the first pull's tail,
// the working presence both ways, and the host doing no work while nothing changes.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { SyncEngine, SyncRelay, MAX_POST_MESSAGES, TAIL, emptyState, migrate, RemoteStore, meanwhileNote, toWorking, lineKey } from '../lib/sync.js'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { RelayError } from '../lib/relay.js'

const tick = (ms = 5) => new Promise((resolve) => setTimeout(resolve, ms))
async function until(pred, ms = 2000) {
  const end = Date.now() + ms
  while (Date.now() < end) {
    if (pred()) return
    await tick()
  }
  assert.fail('condition not met in time')
}

/** The relay's /v1/sync/* with the contract's rules, behind a fetch. */
function fakeRelay() {
  const r = { enabled: true, seq: 0, convs: new Map(), msgs: new Map(), pushes: [], calls: [], gets: [], refuse: null, refusePush: null, refuseAll413: 0, working: [], refuseWorking: false, presence: new Map() }
  const next = () => ++r.seq
  const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
  const state = () => ({ enabled: r.enabled, cursor: r.seq, counts: { conversations: [...r.convs.values()].filter((c) => !c.deleted).length, messages: r.msgs.size }, limits: {}, working: [...r.presence.values()] })
  r.add = (cid, kind, title, device = 'phone-1', name = 'Pixel 8') => {
    r.convs.set(cid, { cid, kind, title, device, device_name: name, created_at: 1738000000, updated_at: 1738000000, deleted: false, seq: next() })
  }
  r.say = (cid, role, text, device = 'phone-1', name = 'Pixel 8', at = 1738000050) => {
    const mid = `m-${r.seq + 1}`
    r.msgs.set(mid, { mid, cid, seq: next(), device, device_name: name, role, text, truncated: false, attachments: [], created_at: at, deleted: false })
    return mid
  }
  r.tombstone = (cid) => {
    const c = r.convs.get(cid)
    Object.assign(c, { deleted: true, title: '', seq: next() })
    for (const [mid, m] of r.msgs) if (m.cid === cid) r.msgs.delete(mid)
  }
  r.fetch = async (url, init = {}) => {
    const u = new URL(url)
    const method = init.method ?? 'GET'
    const path = u.pathname
    r.calls.push(`${method} ${path}`)
    if (r.refuse) {
      const { status, code } = r.refuse
      r.refuse = null
      return json(status, { error: { code, message: code } })
    }
    if (!init.headers?.authorization) return json(401, { error: { code: 'bad_key', message: 'no key' } })
    if (path === '/v1/sync/state' && method === 'GET') return json(200, state())
    if (path === '/v1/sync/state' && method === 'PUT') {
      r.enabled = JSON.parse(init.body).enabled !== false
      if (!r.enabled) { r.convs.clear(); r.msgs.clear() }
      return json(200, state())
    }
    if (!r.enabled) return json(409, { error: { code: 'sync_off', message: 'off' } })
    if (path === '/v1/sync/changes' && method === 'GET') {
      const since = Number(u.searchParams.get('since') ?? 0)
      const limit = Number(u.searchParams.get('limit') ?? 500)
      // C9: scope=main is the main conversation alone; tail=K (with since=0) the newest K messages of the scope and their conversations
      const scope = u.searchParams.get('scope') ?? 'all'
      const tail = since === 0 ? Number(u.searchParams.get('tail') ?? 0) : 0
      r.gets.push({ since, limit, scope, tail })
      const inScope = (cid) => scope !== 'main' || r.convs.get(cid)?.kind === 'main'
      const convs = [...r.convs.values()].filter((c) => inScope(c.cid))
      const msgs = [...r.msgs.values()].filter((m) => inScope(m.cid))
      if (tail > 0) {
        const newest = msgs.sort((a, b) => a.seq - b.seq).slice(-tail)
        const cids = new Set(newest.map((m) => m.cid))
        return json(200, { cursor: r.seq, more: false, skipped: msgs.length - newest.length, conversations: convs.filter((c) => cids.has(c.cid)), messages: newest })
      }
      const rows = [...convs.map((c) => ['c', c]), ...msgs.map((m) => ['m', m])].filter(([, x]) => x.seq > since).sort((a, b) => a[1].seq - b[1].seq)
      const more = rows.length > limit
      const page = rows.slice(0, limit)
      return json(200, { cursor: more ? page[page.length - 1][1].seq : r.seq, more, conversations: page.filter(([k]) => k === 'c').map(([, x]) => x), messages: page.filter(([k]) => k === 'm').map(([, x]) => x) })
    }
    if (path === '/v1/sync/working' && method === 'POST') {
      if (r.refuseWorking) return json(500, { error: { code: 'boom', message: 'no' } })
      const body = JSON.parse(init.body)
      r.working.push(body)
      if (body.working) r.presence.set(body.cid, { cid: body.cid, from: body.device, device_name: 'Desk', at: Math.floor(Date.now() / 1000) })
      else r.presence.delete(body.cid)
      return new Response(null, { status: 204 })
    }
    if (path === '/v1/sync/changes' && method === 'POST') {
      const body = JSON.parse(init.body)
      r.pushes.push(body)
      if (r.refusePush) {
        const { status, code } = r.refusePush
        r.refusePush = null
        return json(status, { error: { code, message: code } })
      }
      if (r.refuseAll413 && (body.messages ?? []).some((m) => m.text === 'x'.repeat(10))) return json(413, { error: { code: 'too_large', message: 'too large' } })
      let accepted = 0
      const rejected = []
      const redirected = new Map()
      for (const c of body.conversations ?? []) {
        if (!r.convs.has(c.cid)) {
          if (c.kind === 'main') {
            const main = [...r.convs.values()].find((x) => x.kind === 'main' && !x.deleted)
            if (main) { redirected.set(c.cid, main.cid); rejected.push({ cid: c.cid, reason: 'main_exists', cid_main: main.cid }); continue }
          }
          r.convs.set(c.cid, { cid: c.cid, kind: c.kind ?? 'side', title: c.title ?? '', device: body.device, device_name: 'Desk', created_at: c.created_at ?? 0, updated_at: c.updated_at ?? 0, deleted: false, seq: next() })
          accepted++
        } else if (c.title !== r.convs.get(c.cid).title) {
          Object.assign(r.convs.get(c.cid), { title: c.title, seq: next() })
          accepted++
        }
      }
      for (const m of body.messages ?? []) {
        if (redirected.has(m.cid)) { rejected.push({ mid: m.mid, reason: 'main_exists', cid_main: redirected.get(m.cid) }); continue }
        if (r.msgs.has(m.mid)) continue
        if (!r.convs.has(m.cid)) { rejected.push({ mid: m.mid, reason: 'unknown_cid' }); continue }
        r.msgs.set(m.mid, { mid: m.mid, cid: m.cid, seq: next(), device: body.device, device_name: 'Desk', role: m.role, text: m.text, truncated: false, attachments: [], created_at: m.created_at ?? 0, deleted: false })
        accepted++
      }
      return json(200, { cursor: r.seq, accepted, rejected })
    }
    if (path === '/v1/sync/changes' && method === 'DELETE') {
      r.convs.clear()
      r.msgs.clear()
      return json(200, state())
    }
    if (path.startsWith('/v1/sync/conversations/') && method === 'DELETE') {
      const cid = decodeURIComponent(path.split('/').pop())
      if (!r.convs.has(cid)) return json(404, { error: { code: 'no_conversation', message: 'none' } })
      r.tombstone(cid)
      return json(200, { cursor: r.seq, deleted: true })
    }
    return json(404, { error: { code: 'not_found', message: path } })
  }
  return r
}

/** The sessions as the engine sees them: titles, lines, creation, the rows kept from elsewhere, the notes to the model. */
function fakeSessions() {
  const s = { rows: new Map(), lines: new Map(), appended: [], forgotten: [], injected: [], renamed: [], created: 0, listCalls: 0, lineCalls: 0 }
  s.add = (id, title, lines = [], createdAt = 1738000000000) => {
    s.rows.set(id, { id, title, blank: lines.length === 0, createdAt, updatedAt: createdAt })
    s.lines.set(id, lines)
  }
  s.api = {
    list: async () => { s.listCalls += 1; return [...s.rows.values()] },
    lines: async (id) => { s.lineCalls += 1; return s.lines.get(id) ?? [] },
    create: async (title) => {
      const id = `session-${++s.created}`
      s.add(id, title, [], Date.now())
      return id
    },
    rename: async (id, title) => { s.renamed.push([id, title]); if (s.rows.has(id)) s.rows.get(id).title = title },
    keep: async (id, line) => { s.appended.push([id, line]) },
    forget: async (id, mid) => { s.forgotten.push([id, mid]) },
    forgetAll: async () => { s.forgotAll += 1 },
    inject: async (id, text) => { s.injected.push([id, text]) },
  }
  s.forgotAll = 0
  /** What one session shows from elsewhere, in the order it was kept. */
  s.remote = (id) => s.appended.filter(([sid]) => sid === id).map(([, line]) => line)
  return s
}

/** The C7/C8 tests ran with every chat syncing; C9's default (main only) is tested on its own below. */
function engine(relay, sessions, extra = {}) {
  let saved
  let changes = 0
  const e = new SyncEngine({
    relay: new SyncRelay('https://relay.test', relay.fetch),
    sessions: sessions.api,
    token: async () => (extra.signedOut ? undefined : 'key'),
    deviceId: () => 'pc-1',
    isTaskSession: (id) => id.startsWith('task-'),
    isBatchSession: (id) => id.startsWith('batch-'),
    load: () => extra.state ?? { ...emptyState(), sideChats: extra.sideChats ?? true },
    save: async (state) => { saved = JSON.parse(JSON.stringify(state)) },
    onChange: () => { changes += 1 },
    log: () => undefined,
    pushDelayMs: 5,
    pullEveryMs: 60_000,
    frameCoalesceMs: 5,
    ...extra.options,
  })
  return { engine: e, saved: () => saved, changes: () => changes }
}

test('the person’s words go up when sent, the model’s at the turn’s end; the main chat is the account’s main conversation', async () => {
  const relay = fakeRelay()
  const sessions = fakeSessions()
  sessions.add('s-main', 'Hello there', [{ id: 'u1', role: 'user', text: 'hi there', at: 1738000000000 }])
  sessions.add('task-1', 'From Pixel 8', [{ id: 'u9', role: 'user', text: 'a task from the phone', at: 1738000002000 }])
  const { engine: e, saved } = engine(relay, sessions)
  assert.equal(await e.setMain('s-main'), 's-main')
  // push at send: the prompt is on the relay while the turn still runs
  e.messageSent('s-main')
  await until(() => relay.msgs.size === 1)
  assert.deepEqual([...relay.msgs.values()].map((m) => [m.role, m.text]), [['user', 'hi there']])
  const main = [...relay.convs.values()].find((c) => c.kind === 'main')
  assert.equal(main.title, 'Hello there')
  assert.equal(main.device, 'pc-1')
  // the turn ends: the final text follows
  sessions.lines.get('s-main').push({ id: 'a1', role: 'assistant', text: 'Hello from the desk', at: 1738000001000 })
  e.turnEnded('s-main')
  e.turnEnded('task-1')
  await until(() => relay.msgs.size === 2)
  assert.deepEqual([...relay.msgs.values()].map((m) => [m.role, m.text]), [['user', 'hi there'], ['assistant', 'Hello from the desk']])
  // the task session is another device's conversation: not synced
  assert.equal([...relay.convs.values()].length, 1)
  // idempotent: the lines are remembered by their dsh ids, the next push sends nothing
  const pushes = relay.pushes.length
  e.turnEnded('s-main')
  await tick(30)
  assert.equal(relay.pushes.length, pushes)
  assert.equal(saved().cids['s-main'], main.cid)
  assert.equal(Object.keys(saved().mids).length, 2)
  // the cursor caught up on the pull after the push, and our own rows came back without being appended
  await until(() => e.state.cursor === relay.seq)
  assert.deepEqual(sessions.appended, [])
  // a rename goes up on its own
  sessions.rows.get('s-main').title = 'Greetings'
  e.sessionRenamed('s-main')
  await until(() => relay.convs.get(main.cid).title === 'Greetings')
  e.stop()
})

test('sign-in backfills the whole history, oldest first, 200 messages a POST', async () => {
  const relay = fakeRelay()
  const sessions = fakeSessions()
  const lines = (prefix, n, from) => Array.from({ length: n }, (_, i) => ({ id: `${prefix}${i}`, role: i % 2 ? 'assistant' : 'user', text: `${prefix}${i}`, at: from + i * 1000 }))
  sessions.add('s-new', 'Newer', lines('n', 10, 1738100000000), 1738100000000)
  sessions.add('s-old', 'Older', lines('o', 250, 1738000000000), 1738000000000)
  const { engine: e } = engine(relay, sessions)
  await e.setMain('s-old')
  await e.accountChanged('acct-1')
  await until(() => relay.msgs.size === 260)
  // the oldest session's lines first, in the order they were lived, 200 at a time
  const first = relay.pushes.find((p) => p.messages.length > 0)
  assert.equal(first.messages.length, MAX_POST_MESSAGES)
  assert.deepEqual(first.messages.slice(0, 4).map((m) => m.text), ['o0', 'o1', 'o2', 'o3'])
  const order = relay.pushes.flatMap((p) => p.messages.map((m) => m.text))
  assert.deepEqual(order.slice(0, 250), lines('o', 250, 0).map((l) => l.text))
  assert.deepEqual(order.slice(250), lines('n', 10, 0).map((l) => l.text))
  assert.ok(relay.pushes.every((p) => p.messages.length <= MAX_POST_MESSAGES))
  // pulled back: nothing of ours is appended to a session
  await until(() => e.state.cursor === relay.seq)
  assert.deepEqual(sessions.appended, [])
  e.stop()
})

test('the second main adopts the account’s id (pull first); the phone’s turns are in the thread, in time order, never twice', async () => {
  const relay = fakeRelay()
  relay.add('their-main', 'main', 'Main chat')
  relay.say('their-main', 'user', 'earlier, on the phone', 'phone-1', 'Pixel 8', 1737990000)
  relay.say('their-main', 'assistant', 'the phone’s answer', 'phone-1', 'Pixel 8', 1737990005)
  const sessions = fakeSessions()
  sessions.add('s-main', 'Desk chat', [
    { id: 'u1', role: 'user', text: 'desk question', at: 1738000000000 },
    { id: 'a1', role: 'assistant', text: 'desk answer', at: 1738000001000 },
  ])
  const { engine: e } = engine(relay, sessions)
  await e.setMain('s-main')
  await e.accountChanged('acct-1')
  await until(() => [...relay.msgs.values()].some((m) => m.text === 'desk answer'))
  assert.equal([...relay.convs.values()].filter((c) => c.kind === 'main').length, 1)
  assert.equal(e.state.cids['s-main'], 'their-main')
  assert.deepEqual(new Set([...relay.msgs.values()].map((m) => m.cid)), new Set(['their-main']))
  // the phone's turns are rows of the main chat here, with where they came from and when
  assert.deepEqual(sessions.remote('s-main').map((l) => [l.role, l.text, l.deviceName, l.at]), [
    ['user', 'earlier, on the phone', 'Pixel 8', 1737990000000],
    ['assistant', 'the phone’s answer', 'Pixel 8', 1737990005000],
  ])
  assert.ok(sessions.remote('s-main').every((l) => l.mid && l.device === 'phone-1'))
  // later on the phone: appended as it arrives
  relay.say('their-main', 'user', 'later, on the phone', 'phone-1', 'Pixel 8', 1738000060)
  await e.pull()
  assert.equal(sessions.remote('s-main').at(-1).text, 'later, on the phone')
  // a second pull, even from zero, appends nothing again: not our echo, not the phone's rows
  await until(() => e.state.cursor === relay.seq)
  const count = sessions.appended.length
  e.state.cursor = 0
  await e.pull()
  assert.equal(sessions.appended.length, count)
  assert.ok(!sessions.appended.some(([, l]) => l.device === 'pc-1'))
  // one thread: the column may not move the main chat away from the account's conversation
  sessions.add('s-other', 'Other', [{ id: 'u5', role: 'user', text: 'x', at: 1 }])
  assert.equal(await e.setMain('s-other'), 's-main')
  assert.equal(e.state.mainSession, 's-main')
  assert.deepEqual(e.view().sessions, ['s-main'])
  assert.equal(e.view().mainSession, 's-main')
  e.stop()
})

test('a conversation from elsewhere is a chat here at once; it continues under the same id; tombstones and renames', async () => {
  const relay = fakeRelay()
  relay.add('c1', 'side', 'Dinner plans')
  relay.say('c1', 'user', 'book a table')
  relay.say('c1', 'assistant', 'Booked for 7', 'phone-1', 'Pixel 8', 1738000060)
  const sessions = fakeSessions()
  const { engine: e } = engine(relay, sessions)
  assert.equal(await e.pull(), 3)
  // eager: a session with the title, mapped, the two turns appended in order, listed by the column
  assert.equal(sessions.created, 1)
  const sid = [...sessions.rows.keys()][0]
  assert.equal(sessions.rows.get(sid).title, 'Dinner plans')
  assert.equal(e.state.cids[sid], 'c1')
  assert.deepEqual(sessions.remote(sid).map((l) => [l.role, l.text]), [['user', 'book a table'], ['assistant', 'Booked for 7']])
  assert.deepEqual(e.view().sessions, [sid])
  // the title it came with is not pushed back
  await tick(30)
  assert.equal(relay.pushes.filter((p) => p.conversations.length > 0).length, 0)
  // a turn here syncs into the same conversation: the prompt at once, the answer at the end
  sessions.lines.set(sid, [{ id: 'u2', role: 'user', text: 'make it 8', at: 1738000070000 }])
  sessions.rows.get(sid).blank = false
  e.messageSent(sid)
  await until(() => [...relay.msgs.values()].some((m) => m.text === 'make it 8'))
  sessions.lines.get(sid).push({ id: 'a2', role: 'assistant', text: 'Changed to 8', at: 1738000071000 })
  e.turnEnded(sid)
  await until(() => [...relay.msgs.values()].some((m) => m.text === 'Changed to 8'))
  assert.deepEqual(new Set([...relay.msgs.values()].map((m) => m.cid)), new Set(['c1']))
  // a message tombstoned elsewhere is hidden here (a log forgets nothing)
  const mid = [...relay.msgs.values()].find((m) => m.text === 'book a table').mid
  Object.assign(relay.msgs.get(mid), { deleted: true, text: '', seq: ++relay.seq })
  await e.pull()
  assert.deepEqual(e.view().hidden, [mid])
  // the chat deleted elsewhere: unmapped, handed to the column to archive, which reports back
  relay.tombstone('c1')
  await e.pull()
  assert.equal(e.state.cids[sid], undefined)
  assert.deepEqual(e.view().toArchive, [sid])
  await e.archived([sid])
  assert.deepEqual(e.view().toArchive, [])
  // a renamed chat elsewhere renames the session here, without pushing the title back
  relay.add('c2', 'side', 'Old name')
  await e.pull()
  const sid2 = [...sessions.rows.keys()].find((id) => sessions.rows.get(id).title === 'Old name')
  Object.assign(relay.convs.get('c2'), { title: 'New name', seq: ++relay.seq })
  await e.pull()
  assert.deepEqual(sessions.renamed.at(-1), [sid2, 'New name'])
  // the main from the relay, when no main chat exists here yet, becomes the main chat
  relay.add('their-main', 'main', 'Main chat')
  relay.say('their-main', 'user', 'from the phone')
  await e.pull()
  const mainSid = e.state.mainSession
  assert.ok(mainSid && sessions.rows.get(mainSid).title === 'Main chat')
  assert.equal(e.state.cids[mainSid], 'their-main')
  assert.deepEqual(sessions.remote(mainSid).map((l) => l.text), ['from the phone'])
  assert.equal(await e.setMain(sid2), mainSid)
  e.stop()
})

test('the hub frame pulls, our own echo does not; the switch and the refusals', async () => {
  const relay = fakeRelay()
  const sessions = fakeSessions()
  const { engine: e } = engine(relay, sessions)
  relay.add('c1', 'side', 'Elsewhere')
  // (a first pull is a tail pull: it carries the conversations of the newest messages, so the chat needs one)
  relay.say('c1', 'user', 'hello')
  e.onFrame({ cursor: relay.seq, from: 'pc-1' })
  await tick(20)
  assert.equal(relay.calls.filter((c) => c.startsWith('GET /v1/sync/changes')).length, 0)
  e.onFrame({ cursor: relay.seq, from: 'phone-1' })
  await until(() => e.state.conversations.c1 !== undefined)
  // off: the relay deletes, nothing more moves
  const off = await e.setEnabled(false)
  assert.equal(off.enabled, false)
  assert.equal(relay.enabled, false)
  assert.equal(relay.convs.size, 0)
  sessions.add('s1', 'Quiet', [{ id: 'u1', role: 'user', text: 'x', at: 1 }])
  const calls = relay.calls.length
  e.turnEnded('s1')
  e.messageSent('s1')
  await tick(30)
  assert.equal(relay.calls.length, calls)
  // on again: pull first, then this device's conversations go up in full
  await e.setEnabled(true)
  await until(() => [...relay.convs.values()].some((c) => c.title === 'Quiet'))
  assert.ok(relay.calls.indexOf('GET /v1/sync/changes') < relay.calls.indexOf('POST /v1/sync/changes'))
  // "Delete synced conversations": the relay emptied, the switch kept, the sessions kept
  const after = await e.deleteRemote()
  assert.equal(relay.convs.size, 0)
  assert.equal(after.enabled, true)
  assert.equal(relay.enabled, true)
  assert.ok(sessions.rows.has('s1'))
  assert.deepEqual(e.state.conversations, {})
  // sync_off from the relay (turned off on another device) flips the switch here
  relay.enabled = false
  await e.pull().catch(() => undefined)
  assert.equal(e.enabled, false)
  relay.enabled = true
  await e.setEnabled(true)
  // a refused key pauses until the next sign-in
  relay.refuse = { status: 401, code: 'bad_key' }
  await e.pull().catch(() => undefined)
  assert.equal(await e.active(), false)
  assert.equal(e.view().paused, true)
  await e.accountChanged('acct-1')
  assert.equal(await e.active(), true)
  // a different account starts from zero; the mapping stays, owned by the last account (C10)
  e.state.cursor = 9
  e.state.cids.x = 'y'
  e.state.owners.x = 'acct-1'
  e.state.conversations.y = { kind: 'side', title: 't', device: 'd', deviceName: 'D', createdAt: 1, updatedAt: 1 }
  await e.accountChanged('acct-2')
  assert.equal(e.state.cursor, 0)
  assert.equal(e.state.cids.x, 'y')
  assert.deepEqual(e.state.conversations, {})
  assert.equal(e.state.accountId, 'acct-2')
  assert.ok(e.view().foreign.includes('x'))
  e.stop()
})

test('signed out, nothing moves; a 0.1.36 state with mirrors pulls again from zero; the relay’s errors keep their code', async () => {
  const relay = fakeRelay()
  const sessions = fakeSessions()
  sessions.add('s1', 'Local only', [{ id: 'u1', role: 'user', text: 'x', at: 1 }])
  const { engine: e } = engine(relay, sessions, { signedOut: true })
  e.turnEnded('s1')
  e.messageSent('s1')
  assert.equal(await e.pull(), 0)
  await tick(20)
  assert.deepEqual(relay.calls, [])
  assert.equal(e.view().available, false)
  // the mirrors of 0.1.36 become sessions and rows on the next pull: the cursor starts over, the pushed ids stay
  const old = migrate({ accountId: 'a', cursor: 42, enabled: true, mainSession: 's1', cids: { s1: 'c-main' }, mids: { u1: 'm1' }, titles: { s1: 'T' }, mirrors: { c1: { cid: 'c1', messages: [] } } })
  assert.equal(old.cursor, 0)
  assert.equal(old.mirrors, undefined)
  assert.deepEqual([old.cids, old.mids, old.conversations, old.pulled], [{ s1: 'c-main' }, { u1: 'm1' }, {}, {}])
  const kept = migrate({ ...old, cursor: 7, conversations: { c1: { kind: 'side', title: 't', device: 'd', deviceName: 'D', createdAt: 1, updatedAt: 1 } } })
  assert.equal(kept.cursor, 7)
  // the relay's errors keep their code
  const r = new SyncRelay('https://relay.test', async () => new Response(JSON.stringify({ error: { code: 'sync_off', message: 'off' } }), { status: 409 }))
  await assert.rejects(r.changes('k', 0), (err) => err instanceof RelayError && err.code === 'sync_off' && err.status === 409)
})

test('a push the relay or the network refused keeps its lines for the next push; a round refused as too large goes up in halves, a single message so refused stays here', async () => {
  const relay = fakeRelay()
  const sessions = fakeSessions()
  sessions.add('s-main', 'Hello there', [{ id: 'u1', role: 'user', text: 'hi there', at: 1738000000000 }])
  const { engine: e, saved } = engine(relay, sessions)
  assert.equal(await e.setMain('s-main'), 's-main')
  // the relay is down for the first push: nothing is lost, the next push carries the line
  relay.refusePush = { status: 503, code: 'down' }
  e.messageSent('s-main')
  await until(() => relay.pushes.length === 1)
  await tick(30)
  assert.equal(relay.msgs.size, 0)
  assert.equal(relay.pushes.length, 1)
  sessions.lines.get('s-main').push({ id: 'a1', role: 'assistant', text: 'Hello from the desk', at: 1738000001000 })
  e.turnEnded('s-main')
  await until(() => relay.msgs.size === 2)
  assert.deepEqual([...relay.msgs.values()].map((m) => [m.role, m.text]), [['user', 'hi there'], ['assistant', 'Hello from the desk']])
  // four new lines refused as one round: the engine halves the round until the relay takes it
  for (let i = 0; i < 4; i++) sessions.lines.get('s-main').push({ id: `b${i}`, role: 'user', text: `line ${i}`, at: 1738000002000 + i })
  const before = relay.pushes.length
  relay.refusePush = { status: 413, code: 'too_large' }
  e.turnEnded('s-main')
  await until(() => relay.msgs.size === 6)
  assert.equal(relay.pushes[before].messages.length, 4)
  assert.equal(relay.pushes[before + 1].messages.length, 2)
  // one message the relay will not take at any size is marked refused, not sent again and again
  sessions.lines.get('s-main').push({ id: 'huge', role: 'user', text: 'x'.repeat(10), at: 1738000010000 })
  relay.refuseAll413 = 1
  e.turnEnded('s-main')
  await until(() => saved().mids[lineKey('s-main', 'huge')] === 'refused:too_large')
  assert.equal(relay.msgs.size, 6)
  const pushes = relay.pushes.length
  e.turnEnded('s-main')
  await tick(30)
  assert.equal(relay.pushes.length, pushes)
  e.stop()
})

test('the other devices’ turns live in the host’s own store, not the session log: kept once, in time order, written whole, forgotten on a tombstone; the note to the model is bounded', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'nm-remote-'))
  const path = join(dir, 'sync-remote.json')
  try {
    const store = new RemoteStore(path)
    store.add('s1', { mid: 'm2', role: 'assistant', text: 'second', at: 2000, device: 'p', deviceName: 'Pixel 8' })
    store.add('s1', { mid: 'm1', role: 'user', text: 'first', at: 1000, device: 'p', deviceName: 'Pixel 8' })
    store.add('s1', { mid: 'm1', role: 'user', text: 'first again', at: 1000, device: 'p', deviceName: 'Pixel 8' })
    assert.deepEqual(store.linesOf('s1').map((l) => l.mid), ['m1', 'm2'])
    assert.deepEqual(store.linesOf('s2'), [])
    await store.flush()
    const onDisk = JSON.parse(readFileSync(path, 'utf8'))
    assert.deepEqual(Object.keys(onDisk), ['s1'])
    assert.equal(onDisk.s1.length, 2)
    // read again by a fresh store, as after a restart
    const again = new RemoteStore(path)
    assert.deepEqual(again.linesOf('s1').map((l) => l.text), ['first', 'second'])
    again.remove('s1', 'm1')
    await again.flush()
    assert.deepEqual(JSON.parse(readFileSync(path, 'utf8')).s1.map((l) => l.mid), ['m2'])
    // the note: the most recent lines, capped
    const many = Array.from({ length: 60 }, (_, i) => ({ mid: `m${i}`, role: i % 2 ? 'assistant' : 'user', text: `line ${i}`, at: i, device: 'p', deviceName: 'Pixel 8' }))
    const note = meanwhileNote(many)
    assert.ok(note.startsWith('[Meanwhile, in this same conversation on another device of the account (20 earlier turns not shown):]'))
    assert.ok(note.includes('Person (on Pixel 8): line 20') && note.includes('Muse (on Pixel 8): line 59') && !note.includes('line 19\n'))
    const big = meanwhileNote([{ mid: 'a', role: 'user', text: 'x'.repeat(20_000), at: 1, device: 'p', deviceName: 'P' }, { mid: 'b', role: 'assistant', text: 'short', at: 2, device: 'p', deviceName: 'P' }])
    assert.ok(big.includes('(1 earlier turn not shown)') && big.endsWith('Muse (on P): short'))
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('a pull keeps the other devices’ rows for the transcript and hands the model one note per session; a tombstone forgets the row', async () => {
  const relay = fakeRelay()
  const sessions = fakeSessions()
  const { engine: e } = engine(relay, sessions)
  relay.add('c-side', 'side', 'Dinner plans', 'pixel', 'Pixel 8')
  relay.say('c-side', 'user', 'Pasta tonight?', 'pixel', 'Pixel 8', 10)
  const p2 = relay.say('c-side', 'assistant', 'Sure, for how many?', 'pixel', 'Pixel 8', 11)
  await e.pull()
  const sid = Object.keys(e.state.cids).find((id) => e.state.cids[id] === 'c-side')
  assert.ok(sid)
  assert.deepEqual(sessions.remote(sid).map((l) => [l.role, l.text, l.deviceName]), [['user', 'Pasta tonight?', 'Pixel 8'], ['assistant', 'Sure, for how many?', 'Pixel 8']])
  assert.equal(sessions.injected.length, 1)
  assert.equal(sessions.injected[0][0], sid)
  assert.ok(sessions.injected[0][1].startsWith('[Meanwhile, in this same conversation on another device of the account:]\nPerson (on Pixel 8): Pasta tonight?\nMuse (on Pixel 8): Sure, for how many?'))
  // deleted on the phone: hidden here and forgotten by the store; nothing injected for a tombstone
  Object.assign(relay.msgs.get(p2), { deleted: true, text: '', seq: ++relay.seq })
  await e.pull()
  assert.deepEqual(sessions.forgotten, [[sid, p2]])
  assert.ok(e.view().hidden.includes(p2))
  assert.equal(sessions.injected.length, 1)
  e.stop()
})

// ---- contract C9: main first ------------------------------------------------------------------

test('C9: side chats stay local by default — only the main conversation goes up, the pull asks for scope=main, a side row makes no session; the switch turns both on and off', async () => {
  const relay = fakeRelay()
  relay.add('their-side', 'side', 'Dinner plans')
  relay.say('their-side', 'user', 'book a table')
  const sessions = fakeSessions()
  sessions.add('s-main', 'Main here', [{ id: 'u1', role: 'user', text: 'main question', at: 1738000000000 }], 1738000000000)
  sessions.add('s-side', 'Side here', [{ id: 'u2', role: 'user', text: 'side question', at: 1738000001000 }], 1738000001000)
  const { engine: e, saved } = engine(relay, sessions, { sideChats: false })
  assert.equal(e.view().sideChats, false)
  await e.setMain('s-main')
  await e.accountChanged('acct-1')
  await until(() => [...relay.msgs.values()].some((m) => m.text === 'main question'))
  await tick(30)
  // the main alone went up; the side chat here was neither listed nor read
  assert.deepEqual([...relay.convs.values()].filter((c) => c.device === 'pc-1').map((c) => c.kind), ['main'])
  assert.ok(!relay.pushes.some((p) => p.messages.some((m) => m.text === 'side question')))
  // every pull asked for the main conversation alone; the first one for the tail
  assert.ok(relay.gets.length > 0 && relay.gets.every((g) => g.scope === 'main'))
  assert.deepEqual(relay.gets[0], { since: 0, limit: 500, scope: 'main', tail: TAIL })
  // the relay's side conversation is not a chat here
  assert.equal(sessions.created, 0)
  assert.equal(e.state.conversations['their-side'], undefined)
  assert.deepEqual(sessions.appended, [])
  // a side row that still arrives (a relay without scope) is ignored: no session, nothing kept
  relay.fetch2 = relay.fetch
  const unscoped = relay.fetch
  relay.fetch = (url, init) => unscoped(String(url).replace('&scope=main', ''), init)
  relay.say('their-side', 'assistant', 'Booked for 7')
  await e.pull()
  assert.equal(sessions.created, 0)
  assert.deepEqual(sessions.appended, [])
  relay.fetch = unscoped
  // a turn in the side chat here stays here
  const pushes = relay.pushes.length
  e.messageSent('s-side')
  e.turnEnded('s-side')
  await tick(30)
  assert.equal(relay.pushes.length, pushes)
  // on: one pull from zero for the newest side turns, then this device's side chats go up oldest first
  relay.gets.length = 0
  const on = await e.setSideChats(true)
  assert.equal(on.sideChats, true)
  assert.equal(saved().sideChats, true)
  await until(() => [...relay.msgs.values()].some((m) => m.text === 'side question'))
  assert.deepEqual(relay.gets[0], { since: 0, limit: 500, scope: 'all', tail: TAIL })
  assert.equal(sessions.created, 1)
  const sid = [...sessions.rows.keys()].find((id) => sessions.rows.get(id).title === 'Dinner plans')
  assert.deepEqual(sessions.remote(sid).map((l) => l.text), ['book a table', 'Booked for 7'])
  assert.equal([...relay.convs.values()].find((c) => c.title === 'Side here')?.kind, 'side')
  // the feed's daily batch is a chat of the rooms', not the person's: with side chats on it
  // still goes nowhere, at its turn's end or in the bulk push the switch began (#713)
  sessions.add('batch-1', 'Feed · 29 Oct', [{ id: 'u3', role: 'user', text: 'write today’s feed', at: 1738000002000 }], 1738000002000)
  const beforeBatch = relay.pushes.length
  e.messageSent('batch-1')
  e.turnEnded('batch-1')
  await e.setSideChats(false)
  await e.setSideChats(true)
  await until(() => e.state.cursor === relay.seq)
  await tick(30)
  assert.ok(!relay.pushes.slice(beforeBatch).some((p) => p.messages.some((m) => m.text === 'write today’s feed')))
  assert.ok(![...relay.convs.values()].some((c) => c.title === 'Feed · 29 Oct'))
  // off again: nothing is deleted, side turns stop moving either way, the main still syncs
  await until(() => e.state.cursor === relay.seq)
  const off = await e.setSideChats(false)
  assert.equal(off.sideChats, false)
  assert.ok(relay.convs.has('their-side') && sessions.rows.has(sid))
  relay.say('their-side', 'user', 'make it 8')
  const kept = sessions.appended.length
  await e.pull()
  assert.equal(sessions.appended.length, kept)
  sessions.lines.get('s-side').push({ id: 'a2', role: 'assistant', text: 'side answer', at: 1738000002000 })
  sessions.lines.get('s-main').push({ id: 'a1', role: 'assistant', text: 'main answer', at: 1738000002000 })
  e.turnEnded('s-side')
  e.turnEnded('s-main')
  await until(() => [...relay.msgs.values()].some((m) => m.text === 'main answer'))
  await tick(30)
  assert.ok(![...relay.msgs.values()].some((m) => m.text === 'side answer'))
  // the setting survives a sign-in to another account; a 0.1.37 state reads as off
  await e.accountChanged('acct-2')
  assert.equal(e.state.sideChats, false)
  assert.equal(migrate({ accountId: 'a', cursor: 1, enabled: true, mainSession: '', cids: {}, mids: {}, titles: {}, conversations: {}, pulled: {}, hidden: [], toArchive: [] }).sideChats, false)
  e.stop()
})

test('C9: a mapped main chat keeps a final reply when its conversation metadata was cleared', async () => {
  const relay = fakeRelay()
  relay.add('c-main', 'main', 'Main chat')
  const cursor = relay.seq
  const sessions = fakeSessions()
  sessions.add('s-main', 'Main here')
  const state = {
    ...emptyState(),
    accountId: 'acct-1',
    cursor,
    mainSession: 's-main',
    sideChats: false,
    cids: { 's-main': 'c-main' },
    owners: { 's-main': 'acct-1' },
  }
  const { engine: e } = engine(relay, sessions, { state })

  const mid = relay.say('c-main', 'assistant', 'final answer from the phone')
  await e.pull()

  assert.deepEqual(sessions.remote('s-main').map((line) => line.text), ['final answer from the phone'])
  assert.equal(e.state.pulled[mid], 's-main')
  e.stop()
})

test('C9: the first pull takes the newest 300 messages and their conversations, the cursor is the account’s latest; later pulls continue from it', async () => {
  const relay = fakeRelay()
  relay.add('their-main', 'main', 'Main chat')
  relay.add('old-side', 'side', 'Old side chat')
  relay.say('old-side', 'user', 'long ago')
  for (let i = 0; i < 400; i++) relay.say('their-main', i % 2 ? 'assistant' : 'user', `turn ${i}`, 'phone-1', 'Pixel 8', 1738000000 + i)
  const sessions = fakeSessions()
  const { engine: e } = engine(relay, sessions)
  await e.start()
  await until(() => e.state.cursor === relay.seq)
  assert.deepEqual(relay.gets[0], { since: 0, limit: 500, scope: 'all', tail: TAIL })
  // the main chat exists here with the newest 300 turns; the old side chat, none of whose rows were in the tail, is not here
  const mainSid = e.state.mainSession
  assert.ok(mainSid)
  assert.equal(sessions.remote(mainSid).length, TAIL)
  assert.equal(sessions.remote(mainSid)[0].text, 'turn 100')
  assert.equal(sessions.created, 1)
  // the next pull continues from the cursor: one new row, no page from zero
  relay.say('their-main', 'user', 'turn 400')
  assert.equal(await e.pull(), 1)
  assert.equal(relay.gets.at(-1).since, relay.seq - 1)
  assert.equal(relay.gets.at(-1).tail, 0)
  e.stop()
})

test('C9: presence — the turn’s start and end are told after the push, once, best-effort; the other device’s working line comes and goes', async () => {
  const relay = fakeRelay()
  relay.add('their-main', 'main', 'Main chat')
  const sessions = fakeSessions()
  sessions.add('s-main', 'Main here', [{ id: 'u1', role: 'user', text: 'desk question', at: 1738000000000 }])
  const { engine: e, changes } = engine(relay, sessions)
  await e.setMain('s-main')
  await e.accountChanged('acct-1')
  await until(() => e.state.cids['s-main'] === 'their-main')
  // the person sends: the prompt goes up, then working:true for the conversation
  relay.working.length = 0
  sessions.lines.get('s-main').push({ id: 'u2', role: 'user', text: 'another', at: 1738000010000 })
  e.messageSent('s-main')
  await until(() => relay.working.length === 1)
  assert.deepEqual(relay.working, [{ cid: 'their-main', working: true, device: 'pc-1' }])
  assert.ok(relay.calls.lastIndexOf('POST /v1/sync/changes') < relay.calls.lastIndexOf('POST /v1/sync/working'))
  // the turn ends: the text goes up, then working:false — and the relay refusing it changes nothing, no retry
  relay.refuseWorking = true
  sessions.lines.get('s-main').push({ id: 'a2', role: 'assistant', text: 'answer', at: 1738000011000 })
  e.turnEnded('s-main')
  await until(() => [...relay.msgs.values()].some((m) => m.text === 'answer'))
  await tick(30)
  assert.equal(relay.calls.filter((c) => c === 'POST /v1/sync/working').length, 2)
  assert.equal(e.error, '')
  relay.refuseWorking = false
  // a session that does not sync tells nothing
  sessions.add('task-1', 'Task', [{ id: 'u9', role: 'user', text: 'x', at: 1 }])
  e.messageSent('task-1')
  await tick(30)
  assert.equal(relay.calls.filter((c) => c === 'POST /v1/sync/working').length, 2)
  // the phone works on the main conversation: the line under its last prompt, the view moved
  const now = Math.floor(Date.now() / 1000)
  const before = changes()
  e.onWorking({ cid: 'their-main', from: 'phone-1', device_name: 'Pixel 8', working: true, at: now })
  assert.deepEqual(e.workingOf('s-main'), { from: 'phone-1', deviceName: 'Pixel 8', at: now * 1000, state: 'working', detail: '' })
  assert.equal(changes(), before + 1)
  // the same frame again moves nothing; our own echo is ignored
  e.onWorking({ cid: 'their-main', from: 'phone-1', device_name: 'Pixel 8', working: true, at: now })
  e.onWorking({ cid: 'their-main', from: 'pc-1', device_name: 'Desk', working: true, at: now + 1 })
  assert.equal(changes(), before + 1)
  // 0.31: the frame says what the run is doing — a step within the same second still moves the line
  e.onWorking({ cid: 'their-main', from: 'phone-1', device_name: 'Pixel 8', working: true, at: now, state: 'working', detail: '打开携程网站' })
  assert.deepEqual(e.workingOf('s-main'), { from: 'phone-1', deviceName: 'Pixel 8', at: now * 1000, state: 'working', detail: '打开携程网站' })
  assert.equal(changes(), before + 2)
  e.onWorking({ cid: 'their-main', from: 'phone-1', device_name: 'Pixel 8', working: true, at: now, state: 'waiting', detail: 'Needs your approval' })
  assert.equal(e.workingOf('s-main')?.state, 'waiting')
  assert.equal(changes(), before + 3)
  // the reply arriving clears it
  relay.say('their-main', 'assistant', 'the phone’s answer', 'phone-1', 'Pixel 8', now)
  await e.pull()
  assert.equal(e.workingOf('s-main'), null)
  // working:false clears it too
  e.onWorking({ cid: 'their-main', from: 'phone-1', device_name: 'Pixel 8', working: true, at: now })
  assert.ok(e.workingOf('s-main'))
  e.onWorking({ cid: 'their-main', from: 'phone-1', device_name: 'Pixel 8', working: false, at: now })
  assert.equal(e.workingOf('s-main'), null)
  // an old presence (10 minutes) is over; an unknown conversation has none
  e.onWorking({ cid: 'their-main', from: 'phone-1', device_name: 'Pixel 8', working: true, at: now - 601 })
  assert.equal(e.workingOf('s-main'), null)
  assert.equal(e.workingOf('nowhere'), null)
  // the relay's state seeds it after a restart
  relay.presence.set('their-main', { cid: 'their-main', from: 'phone-1', device_name: 'Pixel 8', at: now })
  await e.relayStatus()
  assert.equal(e.workingOf('s-main')?.deviceName, 'Pixel 8')
  e.stop()
})

test('C9: an end takes away only the line its own device put up', async () => {
  const relay = fakeRelay()
  relay.add('their-main', 'main', 'Main chat')
  const sessions = fakeSessions()
  sessions.add('s-main', 'Main here', [{ id: 'u1', role: 'user', text: 'desk question', at: 1738000000000 }])
  const { engine: e } = engine(relay, sessions)
  await e.setMain('s-main')
  await e.accountChanged('acct-1')
  await until(() => e.state.cids['s-main'] === 'their-main')
  const now = Math.floor(Date.now() / 1000)
  // the phone is working on the conversation
  e.onWorking({ cid: 'their-main', from: 'phone-1', device_name: 'Pixel 8', working: true, at: now })
  assert.equal(e.workingOf('s-main')?.from, 'phone-1')
  // the tablet finishes its own turn: its end frame leaves the phone's line alone
  e.onWorking({ cid: 'their-main', from: 'tablet-9', device_name: 'iPad', working: false, at: now + 1 })
  assert.equal(e.workingOf('s-main')?.from, 'phone-1')
  // the tablet's reply arriving leaves it alone too
  relay.say('their-main', 'assistant', 'the tablet’s answer', 'tablet-9', 'iPad', now + 1)
  await e.pull()
  assert.equal(e.workingOf('s-main')?.from, 'phone-1')
  // an end older than the line it names does not take it away either
  e.onWorking({ cid: 'their-main', from: 'phone-1', device_name: 'Pixel 8', working: false, at: now - 1 })
  assert.equal(e.workingOf('s-main')?.from, 'phone-1')
  // the phone's own end, at or after its line, does
  e.onWorking({ cid: 'their-main', from: 'phone-1', device_name: 'Pixel 8', working: false, at: now + 2 })
  assert.equal(e.workingOf('s-main'), null)
  e.stop()
})

test('the host is quiet while nothing changes: no listing or reading of sessions after the push, one read per session per push, frames coalesced', async () => {
  const relay = fakeRelay()
  const sessions = fakeSessions()
  sessions.add('s1', 'One', [{ id: 'u1', role: 'user', text: 'a', at: 1 }], 1)
  sessions.add('s2', 'Two', [{ id: 'u2', role: 'user', text: 'b', at: 2 }], 2)
  sessions.add('s3', 'Three', [{ id: 'u3', role: 'user', text: 'c', at: 3 }], 3)
  const { engine: e } = engine(relay, sessions)
  await e.accountChanged('acct-1')
  await until(() => relay.msgs.size === 3)
  await until(() => e.state.cursor === relay.seq)
  await tick(30)
  // one round: each session's lines read once (no second pass to see what is left)
  assert.equal(sessions.lineCalls, 3)
  const lists = sessions.listCalls
  // idle for many push delays: the sessions are not listed or read again
  await tick(60)
  assert.equal(sessions.listCalls, lists)
  assert.equal(sessions.lineCalls, 3)
  // a turn that adds nothing new is one listing and one read, then quiet again
  e.turnEnded('s1')
  await tick(40)
  assert.equal(sessions.listCalls, lists + 1)
  assert.equal(sessions.lineCalls, 4)
  await tick(40)
  assert.equal(sessions.listCalls, lists + 1)
  // five frames within the window: one pull
  const gets = relay.gets.length
  relay.add('c1', 'side', 'Elsewhere')
  for (let i = 0; i < 5; i++) e.onFrame({ cursor: relay.seq, from: 'phone-1' })
  await until(() => e.state.conversations.c1 !== undefined)
  await tick(20)
  assert.equal(relay.gets.length, gets + 1)
  e.stop()
})

test('SyncRelay: the query carries scope and tail only when asked; working posts the conversation and the flag', async () => {
  const urls = []
  const r = new SyncRelay('https://relay.test/', async (url, init) => {
    urls.push([String(url), init?.method ?? 'GET', init?.body])
    return url.endsWith('/working') ? new Response(null, { status: 204 }) : new Response(JSON.stringify({ cursor: 0, more: false, conversations: [], messages: [] }), { status: 200 })
  })
  await r.changes('k', 0)
  await r.changes('k', 0, 500, 'main', 300)
  await r.changes('k', 42, 500, 'all', 300)
  await r.working('k', 'pc-1', 'c1', true)
  await r.working('k', 'pc-1', 'c1', true, { state: 'working', detail: 'x'.repeat(200) })
  await r.working('k', 'pc-1', 'c1', false, { state: 'working', detail: 'ignored on a false' })
  assert.deepEqual(urls.map((u) => u[0].slice('https://relay.test'.length)), [
    '/v1/sync/changes?since=0&limit=500',
    '/v1/sync/changes?since=0&limit=500&scope=main&tail=300',
    '/v1/sync/changes?since=42&limit=500',
    '/v1/sync/working',
    '/v1/sync/working',
    '/v1/sync/working',
  ])
  assert.deepEqual(JSON.parse(urls[3][2]), { cid: 'c1', working: true, device: 'pc-1' })
  // 0.31: the step rides along on a true, cut to the relay's cap; a false never carries one
  assert.deepEqual(JSON.parse(urls[4][2]), { cid: 'c1', working: true, device: 'pc-1', state: 'working', detail: 'x'.repeat(160) })
  assert.deepEqual(JSON.parse(urls[5][2]), { cid: 'c1', working: false, device: 'pc-1' })
  // the wire row keeps the two fields when they are there and sound, and nothing else
  assert.deepEqual(toWorking({ cid: 'c1', from: 'd', device_name: 'D', working: true, at: 5, state: 'waiting', detail: 'a card' }), { cid: 'c1', from: 'd', device_name: 'D', working: true, at: 5, state: 'waiting', detail: 'a card' })
  assert.deepEqual(toWorking({ cid: 'c1', from: 'd', device_name: 'D', working: true, at: 5, state: 'odd', detail: 7 }), { cid: 'c1', from: 'd', device_name: 'D', working: true, at: 5 })
})

test('0.31: the steps of a turn running here are told, once each, at most one per gap, and not after the turn', async () => {
  const relay = fakeRelay()
  relay.add('their-main', 'main', 'Main chat')
  const sessions = fakeSessions()
  sessions.add('s-main', 'Main here', [{ id: 'u1', role: 'user', text: 'desk question', at: 1738000000000 }])
  const { engine: e } = engine(relay, sessions, { options: { stepGapMs: 40 } })
  await e.setMain('s-main')
  await e.accountChanged('acct-1')
  await until(() => e.state.cids['s-main'] === 'their-main')
  // a step before any turn runs here says nothing
  e.step('s-main', 'working', 'too early')
  await tick(10)
  assert.equal(relay.working.length, 0)
  sessions.lines.get('s-main').push({ id: 'u2', role: 'user', text: 'book it', at: 1738000010000 })
  e.messageSent('s-main')
  await until(() => relay.working.length === 1)
  // the first step goes at once; the same step again is not repeated
  e.step('s-main', 'working', '  打开\n携程网站 ')
  e.step('s-main', 'working', '打开 携程网站')
  await tick(10)
  assert.deepEqual(relay.working.at(-1), { cid: 'their-main', working: true, device: 'pc-1', state: 'working', detail: '打开 携程网站' })
  assert.equal(relay.working.length, 2)
  // two changes inside the gap: the latest one goes when the gap ends
  e.step('s-main', 'working', 'second')
  e.step('s-main', 'waiting', 'Needs your approval: run the booking')
  await tick(10)
  assert.equal(relay.working.length, 2)
  await until(() => relay.working.length === 3)
  assert.deepEqual(relay.working.at(-1), { cid: 'their-main', working: true, device: 'pc-1', state: 'waiting', detail: 'Needs your approval: run the booking' })
  // the words are cut to the relay's cap
  await tick(50)
  e.step('s-main', 'working', 'y'.repeat(300))
  await until(() => relay.working.length === 4)
  assert.equal(relay.working.at(-1).detail.length, 160)
  // after the turn ends nothing more is told but the end itself
  sessions.lines.get('s-main').push({ id: 'a2', role: 'assistant', text: 'done', at: 1738000011000 })
  e.turnEnded('s-main')
  e.step('s-main', 'working', 'late')
  await until(() => relay.working.some((w) => w.working === false))
  await tick(60)
  assert.deepEqual(relay.working.at(-1), { cid: 'their-main', working: false, device: 'pc-1' })
  assert.equal(relay.working.length, 5)
  // a session that does not sync tells nothing
  sessions.add('task-1', 'Task', [{ id: 'u9', role: 'user', text: 'x', at: 1 }])
  e.messageSent('task-1')
  e.step('task-1', 'working', 'no')
  await tick(30)
  assert.equal(relay.working.length, 5)
  e.stop()
})

// ---- contract C10: a device shows and syncs the current account's conversations only ---------

test('C10: a session joins the account on its first push or pull; another account hides it, never pushes it, pulls afresh; switching back shows it again', async () => {
  const relay = fakeRelay()
  const relayB = fakeRelay()
  // the same engine; the relay underneath swaps with the key, as a new account's key points it at another store
  const relays = { current: relay }
  const sessions = fakeSessions()
  sessions.add('s-a', 'A’s chat', [{ id: 'ua1', role: 'user', text: 'from a', at: 1738000000000 }], 1738000000000)
  sessions.add('s-local', 'Never synced', [{ id: 'ul1', role: 'user', text: 'offline words', at: 1738000001000 }], 1738000001000)
  sessions.add('task-1', 'Task', [{ id: 'ut1', role: 'user', text: 'x', at: 1 }], 1)
  const { engine: e, changes } = engine({ fetch: (url, init) => relays.current.fetch(url, init) }, sessions)
  // signed out (never signed in): everything shows, nothing is owned, nothing moves
  assert.deepEqual(e.view().foreign, [])
  assert.equal(e.owns('s-a'), true)
  // A signs in: the main chat is pushed and becomes A's; the side chat that never synced has no owner yet
  await e.setMain('s-a')
  await e.accountChanged('acct-a')
  await until(() => [...relay.msgs.values()].some((m) => m.text === 'from a'))
  await until(() => e.state.cursor === relay.seq)
  assert.equal(e.state.owners['s-a'], 'acct-a')
  await tick(30)
  // s-local is a side chat and side chats sync here (the test engine's default), so it went up too and is A's
  assert.equal(e.state.owners['s-local'], 'acct-a')
  // a conversation pulled from A's relay is a session here, owned by A
  relay.add('c-a', 'side', 'Pulled for A', 'phone-1', 'Pixel 8')
  relay.say('c-a', 'user', 'hello from the phone')
  await e.pull()
  const pulledSid = Object.keys(e.state.cids).find((sid) => e.state.cids[sid] === 'c-a')
  assert.ok(pulledSid)
  assert.equal(e.state.owners[pulledSid], 'acct-a')
  assert.deepEqual(e.view().foreign, [])
  assert.deepEqual(new Set(e.view().sessions), new Set(['s-a', 's-local', pulledSid]))
  const aCids = { ...e.state.cids }
  const aMids = { ...e.state.mids }
  // the phone works on A's conversation: a working line
  e.onWorking({ cid: 'c-a', from: 'phone-1', device_name: 'Pixel 8', working: true, at: Math.floor(Date.now() / 1000) })
  assert.ok(e.workingOf(pulledSid))

  // A signs out, B signs in on the same computer: a different account.id
  e.signedOut()
  assert.deepEqual(e.view().foreign, [])
  const before = changes()
  relays.current = relayB
  await e.accountChanged('acct-b')
  assert.ok(changes() > before)
  // the account-scoped state started over: cursor 0, no relay rows, nothing pulled, presence gone, the kept turns dropped once
  assert.equal(e.state.accountId, 'acct-b')
  assert.equal(e.state.cursor, 0)
  assert.deepEqual(e.state.conversations, {})
  assert.deepEqual(e.state.pulled, {})
  assert.equal(sessions.forgotAll, 1)
  assert.equal(e.workingOf(pulledSid), null)
  // A's mapping is kept, so switching back works; A's main chat is no longer the main chat here
  assert.deepEqual(e.state.cids, aCids)
  assert.deepEqual(e.state.mids, aMids)
  assert.equal(e.state.mainSession, '')
  // A's sessions are hidden, not deleted; B owns nothing yet
  assert.deepEqual(new Set(e.view().foreign), new Set(['s-a', 's-local', pulledSid]))
  assert.deepEqual(e.view().sessions, [])
  assert.equal(e.owns('s-a'), false)
  assert.equal(await e.setMain('s-a'), '')
  // nothing of A's goes to B: a turn in A's chat pushes nothing
  await until(() => e.state.cursor === relayB.seq)
  sessions.lines.get('s-a').push({ id: 'aa2', role: 'assistant', text: 'a’s answer', at: 1738000005000 })
  e.turnEnded('s-a')
  e.messageSent('s-a')
  await tick(40)
  assert.equal(relayB.pushes.length, 0)
  assert.ok(![...relayB.msgs.values()].some((m) => m.text === 'from a' || m.text === 'offline words'))
  // a chat written now, before B ever synced it, has no owner: it is listed and goes up to B, and becomes B's
  sessions.add('s-b', 'B’s chat', [{ id: 'ub1', role: 'user', text: 'from b', at: 1738000010000 }], 1738000010000)
  assert.equal(e.owns('s-b'), true)
  await e.setMain('s-b')
  e.messageSent('s-b')
  await until(() => [...relayB.msgs.values()].some((m) => m.text === 'from b'))
  assert.equal(e.state.owners['s-b'], 'acct-b')
  assert.ok(relayB.pushes.every((p) => p.messages.every((m) => m.text === 'from b')))
  // signed out again: every local chat shows, A's and B's alike, and nothing moves
  e.signedOut()
  assert.deepEqual(e.view().foreign, [])
  assert.equal(e.owns('s-a'), true)
  // A back: A's chats return, B's hide; the pull starts over for A
  relays.current = relay
  const keptBefore = sessions.remote(pulledSid).filter((l) => l.text === 'hello from the phone').length
  await e.accountChanged('acct-a')
  assert.equal(e.state.cursor, 0)
  assert.deepEqual(e.view().foreign, ['s-b'])
  assert.ok(e.owns('s-a') && e.owns(pulledSid))
  assert.equal(sessions.forgotAll, 2)
  // A's rows come back on the fresh pull and are kept again (the kept store was emptied with the switch)
  await until(() => e.state.cursor === relay.seq)
  assert.ok(sessions.remote(pulledSid).filter((l) => l.text === 'hello from the phone').length > keptBefore)
  e.stop()
})

test('C10: the same account again changes nothing; a 0.1.38 state gives its mapping to the account it synced with; the switch on again re-sends only this account’s chats', async () => {
  // the same account signing in again: the cursor and the rows stay
  const relay = fakeRelay()
  const sessions = fakeSessions()
  sessions.add('s1', 'One', [{ id: 'u1', role: 'user', text: 'a', at: 1 }], 1)
  const { engine: e } = engine(relay, sessions)
  await e.accountChanged('acct-1')
  await until(() => relay.msgs.size === 1)
  await until(() => e.state.cursor === relay.seq)
  const cursor = e.state.cursor
  await e.accountChanged('acct-1')
  assert.equal(e.state.cursor, cursor)
  assert.equal(sessions.forgotAll, 0)
  // a 0.1.38 state: no owners; every mapped session belongs to the account it was synced with
  const old = migrate({ accountId: 'acct-old', cursor: 5, enabled: true, mainSession: 's1', sideChats: true, cids: { s1: 'c1', s2: 'c2' }, mids: {}, titles: {}, conversations: {}, pulled: {}, hidden: [], toArchive: [] })
  assert.deepEqual(old.owners, { s1: 'acct-old', s2: 'acct-old' })
  assert.equal(old.cursor, 5)
  // a state that never signed in has no owners to give
  assert.deepEqual(migrate({ ...emptyState(), cids: { s1: 'c1' } }).owners, {})
  // the switch off and on again as B: A's lines keep their pushed ids, B's and the ownerless are re-sent
  sessions.add('s-a', 'A’s', [{ id: 'ua', role: 'user', text: 'a-words', at: 2 }], 2)
  e.state.owners['s-a'] = 'acct-other'
  e.state.cids['s-a'] = 'c-other'
  e.state.mids.ua = 'pushed-under-a'
  e.state.titles['s-a'] = 'A’s'
  await e.setEnabled(false)
  await e.setEnabled(true)
  assert.equal(e.state.mids.ua, 'pushed-under-a')
  assert.equal(e.state.titles['s-a'], 'A’s')
  assert.equal(e.state.mids.u1, undefined)
  await until(() => relay.msgs.size === 1)
  await tick(30)
  assert.ok(![...relay.msgs.values()].some((m) => m.text === 'a-words'))
  e.stop()
})

test('a sync frame arriving while a pull is in flight triggers a follow-up pull, and RemoteStore records keptAt for clock-skewed anchors', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'nm-remote-skew-'))
  try {
    const store = new RemoteStore(join(dir, 'sync-remote.json'))
    const beforeKeep = Date.now()
    // Remote device clock is 8 hours ahead of this computer, as in a misconfigured cross-timezone setup (#395)
    store.add('s1', { mid: 'm-skew', role: 'assistant', text: 'from Mac mini', at: beforeKeep + 8 * 3600_000, device: 'mini', deviceName: 'Mac mini' })
    const kept = store.linesOf('s1')[0]
    assert.ok(typeof kept.keptAt === 'number' && kept.keptAt >= beforeKeep)
    // A local prompt typed on this computer after the remote line was kept is recognized as younger despite the skewed remote `at`
    const localPromptTime = kept.keptAt + 10
    const seenAt = Math.min(kept.at, kept.keptAt)
    assert.ok(localPromptTime > seenAt || localPromptTime >= kept.keptAt)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }

  // While pull #1 is awaiting `inject`, the other device pushes its assistant reply and a second hub `sync` frame arrives
  const relay = fakeRelay()
  relay.add('c-main', 'main', 'Main chat', 'mini', 'Mac mini')
  relay.say('c-main', 'user', 'question on mini', 'mini', 'Mac mini', 1738000010)
  let releaseInject
  const injectGate = new Promise((resolve) => {
    releaseInject = resolve
  })
  const sessions = fakeSessions()
  const origInject = sessions.api.inject
  let firstInject = true
  sessions.api.inject = async (id, text) => {
    if (firstInject) {
      firstInject = false
      await injectGate
    }
    return origInject(id, text)
  }
  const { engine: e } = engine(relay, sessions)
  const firstPull = e.pull()
  await until(() => !firstInject)
  // Second message lands on the relay and its hub frame arrives while the first pull is still in flight
  relay.say('c-main', 'assistant', 'answer on mini', 'mini', 'Mac mini', 1738000012)
  e.onFrame({ cursor: relay.seq, from: 'mini' })
  await tick(15)
  releaseInject()
  await firstPull
  await until(() => e.state.cursor === relay.seq)
  const mainSid = e.state.mainSession
  assert.deepEqual(
    sessions.remote(mainSid).map((l) => l.text),
    ['question on mini', 'answer on mini'],
  )
  e.stop()
})


test('a line the relay took but answered nothing about is sent again as itself, not as a twin', async (t) => {
  const relay = fakeRelay()
  const sessions = fakeSessions()
  sessions.add('s-main', 'Hello there', [{ id: 'u1', role: 'user', text: 'hi there', at: 1738000000000 }])
  // the relay's answer dies on the way back: the POST reached it (the message is in), the client sees an error
  const realFetch = relay.fetch
  let dropFirst = true
  relay.fetch = async (url, init) => {
    const r = await realFetch(url, init)
    if (dropFirst && String(url).endsWith('/v1/sync/changes') && r.ok) {
      dropFirst = false
      throw new Error('the network died after the relay took the round')
    }
    return r
  }
  const { engine: e } = engine(relay, sessions)
  t.after(() => e.stop())
  await e.setMain('s-main')
  e.messageSent('s-main')
  await until(() => relay.pushes.length >= 1 && (relay.pushes[0].messages ?? []).length > 0)
  await tick(20)
  // the failed round left the session dirty; the next event in it sends it again
  e.messageSent('s-main')
  await until(() => relay.pushes.length >= 2 && relay.pushes.every((p) => (p.messages ?? []).length > 0))
  const midsFor = (p) => (p.messages ?? []).filter((m) => m.text === 'hi there').map((m) => m.mid)
  const first = midsFor(relay.pushes[0])
  const second = midsFor(relay.pushes[1])
  assert.equal(first.length, 1)
  assert.equal(second.length, 1)
  // the retry carries the same mid, so the relay's per-mid idempotence turns it away
  assert.equal(second[0], first[0])
  assert.equal([...relay.msgs.values()].filter((m) => m.text === 'hi there').length, 1)
})

test('a message id is derived, not minted: same device and line, same id; anything else differs', async () => {
  const { deriveMid } = await import('../lib/sync.js')
  const id = /^[a-z0-9][a-z0-9._:-]{3,63}$/
  const a = deriveMid('pc-1', 's-main', 'u1')
  assert.ok(id.test(a))
  assert.equal(deriveMid('pc-1', 's-main', 'u1'), a)
  assert.notEqual(deriveMid('pc-1', 's-side', 'u1'), a)
  assert.notEqual(deriveMid('a:b', 'c', 'd'), deriveMid('a', 'b:c', 'd'))
  assert.notEqual(deriveMid('pc-1', 's-main', 'u2'), a)
  assert.notEqual(deriveMid('pc-2', 's-main', 'u1'), a)
})

test('separate sessions with the same local line ID both upload, including later rounds', async (t) => {
  const relay = fakeRelay()
  const sessions = fakeSessions()
  sessions.add('s-main', 'Main', [{ id: 'u1', role: 'user', text: 'first session', at: 1738000000000 }])
  sessions.add('s-side', 'Side', [{ id: 'u1', role: 'user', text: 'second session', at: 1738000000001 }])
  const { engine: e } = engine(relay, sessions)
  t.after(() => e.stop())
  e.state.sideChats = true
  await e.setMain('s-main')
  e.dirty.add('s-main')
  await e.push()
  e.dirty.add('s-side')
  await e.push()
  const rows = [...relay.msgs.values()]
  assert.deepEqual(rows.map((m) => m.text), ['first session', 'second session'])
  assert.equal(new Set(rows.map((m) => m.mid)).size, 2)
  assert.equal(Object.keys(e.state.mids).length, 2)
})

test('saved random message IDs from an earlier desktop remain recognized', async (t) => {
  const relay = fakeRelay()
  const sessions = fakeSessions()
  sessions.add('s-main', 'Main', [{ id: 'old-line', role: 'user', text: 'already uploaded', at: 1738000000000 }])
  const { engine: e } = engine(relay, sessions)
  t.after(() => e.stop())
  e.state.mids['old-line'] = 'legacy-random-id'
  await e.setMain('s-main')
  await e.push()
  assert.equal([...relay.msgs.values()].length, 0)
  assert.equal(e.state.mids['old-line'], 'legacy-random-id')
})

test('a lost upload response followed by restart keeps both the conversation and message IDs', async (t) => {
  const relay = fakeRelay()
  const sessions = fakeSessions()
  sessions.add('s-side', 'Side', [{ id: 'u1', role: 'user', text: 'survives restart', at: 1738000000000 }])
  const fetch = relay.fetch
  let loseResponse = true
  relay.fetch = async (url, init) => {
    const result = await fetch(url, init)
    if (loseResponse && init?.method === 'POST' && String(url).endsWith('/v1/sync/changes')) {
      loseResponse = false
      throw new Error('lost upload response')
    }
    return result
  }
  const first = engine(relay, sessions, { state: { ...emptyState(), accountId: 'account-a', sideChats: true } })
  t.after(() => first.engine.stop())
  first.engine.dirty.add('s-side')
  await assert.rejects(first.engine.push(), /lost upload response/)
  first.engine.stop()
  const saved = first.saved()
  assert.ok(saved?.cids['s-side'], 'the conversation mapping was saved before uploading')
  assert.equal(saved.owners['s-side'], 'account-a', 'a lost response does not leave the uploaded chat ownerless')
  const next = engine(relay, sessions, { state: saved })
  t.after(() => next.engine.stop())
  next.engine.dirty.add('s-side')
  await next.engine.push()
  assert.equal(relay.convs.size, 1)
  assert.equal(relay.msgs.size, 1)
  assert.equal(relay.pushes[0].messages[0].mid, relay.pushes[1].messages[0].mid)
  assert.equal(relay.pushes[0].messages[0].cid, relay.pushes[1].messages[0].cid)
})

test('a failed local mapping save prevents upload and the next attempt can recover', async (t) => {
  const relay = fakeRelay()
  const sessions = fakeSessions()
  sessions.add('s-side', 'Side', [{ id: 'u1', role: 'user', text: 'save before upload', at: 1738000000000 }])
  let failSave = true
  const { engine: e } = engine(relay, sessions, { options: {
    save: async () => { if (failSave) throw new Error('local save failed') },
  } })
  t.after(() => e.stop())
  e.dirty.add('s-side')
  await assert.rejects(e.push(), /local save failed/)
  assert.equal(relay.pushes.length, 0)
  failSave = false
  await e.push()
  assert.equal(relay.msgs.size, 1)
})
