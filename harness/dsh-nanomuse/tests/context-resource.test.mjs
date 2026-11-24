// The resource server is a loopback fixture. No provider accounts or model credentials are needed.
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { test } from 'node:test'
import Connectors from '../lib/connectors.js'
import Rooms from '../lib/rooms.js'
import { apply as mountTools } from '../lib/rooms-tools.js'

async function fixture(t) {
  const prev = process.env.DSH_HOME
  const dir = await mkdtemp(join(tmpdir(), 'nm-resource-'))
  process.env.DSH_HOME = dir
  t.after(async () => { if (prev) process.env.DSH_HOME = prev; else delete process.env.DSH_HOME; await rm(dir, { recursive: true, force: true }) })
  const data = { text: 'Rehearsal planning is open.', calls: [], allowed: true, alias: false }
  const uri = 'project:rehearsal'
  const server = createServer(async (req, res) => {
    if (req.method === 'DELETE') { res.writeHead(204).end(); return }
    const chunks = []
    for await (const chunk of req) chunks.push(chunk)
    const { method, id, params } = JSON.parse(Buffer.concat(chunks))
    data.calls.push([method, params?.uri])
    assert.equal(req.headers['x-fixture'], 'authorized')
    let result = {}
    if (method === 'initialize') { res.setHeader('mcp-session-id', 'loopback'); result = { protocolVersion: '2025-06-18', capabilities: { resources: {} } } }
    else {
      assert.equal(req.headers['mcp-session-id'], 'loopback')
      if (method === 'notifications/initialized') { res.writeHead(202).end(); return }
      if (method === 'resources/list') result = params.cursor ? { resources: data.allowed ? [
        { name: 'Production notes', mimeType: 'text/plain', uri },
        ...(data.multiple ? [{ name: 'Other', mimeType: 'text/plain', uri: 'project:other' }] : []),
      ] : [], ...(data.more ? { nextCursor: 'unfinished' } : {}) }
        : { resources: [{ name: 'Poster', mimeType: 'image/png', uri: 'project:poster' }], nextCursor: 'second' }
      else if (method === 'resources/read') { assert.equal(params.uri, uri); result = { contents: [{ uri: data.alias ? 'project:other' : uri, text: data.text }] } }
      else assert.fail('A resource reader cannot call ' + method)
    }
    res.writeHead(200, { 'content-type': 'text/event-stream' })
    res.end('event: message\r\ndata: ' + JSON.stringify({ jsonrpc: '2.0', id, result }) + '\r\n\r\n')
  })
  await new Promise(r => server.listen(0, '127.0.0.1', r))
  t.after(() => { server.closeAllConnections(); server.close() })
  const connector = new Connectors({ reflect: { provide() {} } })
  connector.save = async () => {}
  const url = 'http://127.0.0.1:' + server.address().port + '?scope=fixture-query-key'
  const id = await connector.finish({ id: 'project', service: 'custom', label: 'Projects', serverName: 'projects', url, disabled: [] }, { kind: 'header', name: 'x-fixture', value: 'authorized' })
  const cloud = { feedOwner: 'local', syncMainSession: () => 'main', isClearedSession: () => false,
    scheduleSessionAccess: () => session => session !== 'foreign', hasRemoteReplySince: () => false }
  let model
  const asks = []
  cloud.prepareFeed = async (system, input, signal) => { assert.equal(signal.aborted, false); assert.match(system, /untrusted/); const records = JSON.parse(input); asks.push(records); return JSON.stringify(await model(records)) }
  const ctx = { reflect: { provide() {} }, logger: { warn() {} }, nanomuseCloud: cloud,
    get: key => key === 'workspaceRegistry' ? { archivedSessionIds: [] } : key === 'nanomuseConnectors' ? connector : undefined }
  const make = () => { const r = new Rooms(ctx); r.broadcast = () => {}; r.syncReady = async () => false; r.store.lang = 'en'; return r }
  const rooms = make()
  connector.ctx.get = key => key === 'nanomuseRooms' ? rooms : undefined
  let now = new Date(2026, 4, 5, 10).getTime()
  t.mock.method(Date, 'now', () => now)
  return { data, asks, dir, rooms, cloud, connector, ctx, make, id, url, model(fn) { model = fn }, advance(min) { now += min * 60_000 },
    async enable() { const choices = await rooms.selectResource(rooms.checkInScope(), id, 1, '', false); assert.deepEqual(choices.map(c => c.label), ['Production notes']); await rooms.selectResource(rooms.checkInScope(), id, 1, choices[0].key, true); return choices[0] } }
}

test('an unseen real MCP text change starts a main chat, stays out of the system prompt and can be read for a reply', async t => {
  const f = await fixture(t)
  const { rooms, data, asks } = f
  const watch = await f.enable()
  await rooms.tick()
  assert.equal(asks.length, 0)
  const baseline = await readFile(join(f.dir, 'nanomuse/rooms.json'), 'utf8')
  assert.ok(!baseline.includes(data.text) && !baseline.includes('project:rehearsal'))
  f.advance(30)
  const change = 'The rehearsal venue can no longer accommodate the full ensemble.'
  data.text += '\n' + change + '\napi_key: sample-private-value\nYour verification code is 000000.\n临时验证码\n000000'
  f.model(records => { assert.deepEqual(records.updates, [[1, change]]); return { notify: true, line: 1, quote: 'accommodate the full ensemble', offer: 'reschedule', goal: 0 } })
  // No chat prompt, goal, user activity, or explicit request to watch the ensemble.
  await Promise.all([rooms.tick(), rooms.tick()])
  const [note] = rooms.checkInMessages('main')
  assert.ok(note?.unread && note.external)
  assert.match(note.text, /Production notes.*no longer accommodate the full ensemble.*new plan/)
  assert.deepEqual(rooms.checkInMessages('foreign'), [])
  assert.equal(asks.length, 1)
  assert.equal(data.calls.some(([method]) => method.startsWith('tools/')), false)
  assert.deepEqual([...new Set(data.calls.filter(c => c[0] === 'resources/read').map(c => c[1]))], ['project:rehearsal'])
  const tools = []
  const sections = []
  mountTools({ nanomuseRooms: rooms, nanomuseCloud: f.cloud, effect(fn) { fn() }, tools: { register(tool) { tools.push(tool) } },
    inject(names, fn) { if (names.includes('systemPrompt')) fn({ systemPrompt: { context(s) { sections.push(s) } }, effect(fn) { fn() } }) } })
  const prompt = sections.find(s => s.name === 'nanomuse-rooms').text({ agent: { session: { id: 'main' } } })
  assert.match(prompt, /read_context_checkin/)
  assert.ok(!prompt.includes(change))
  const tool = tools.find(tool => tool.name === 'read_context_checkin')
  assert.deepEqual(await tool.execute({}, { agent: { session: { id: 'main' } } }), { displayed: note.text })
  assert.deepEqual(await tool.execute({}, { agent: { session: { id: 'foreign' } } }), { displayed: '' })
  const restart = f.make()
  restart.store = await restart.read()
  restart.store.mailboxes.local.messages[0].unread = false
  f.advance(24 * 60)
  await restart.tick()
  assert.deepEqual(restart.checkInMessages().map(n => n.id), [note.id])
  assert.equal(asks.length, 1)
  await assert.rejects(restart.selectResource(restart.checkInScope(), f.id, 1, 'not-a-listed-resource', true))
  assert.equal(restart.store.mailboxes.local.resource.key, watch.key)
})

test('partial reads, disconnected sources, quiet model decisions and revocation during review do not publish', async t => {
  const f = await fixture(t)
  const { rooms, data, asks } = f
  await f.enable()
  f.advance(30)
  data.text = 'The event requires a revised seating plan.'
  data.alias = true
  await assert.rejects(rooms.checkResource(Date.now()), /selected text/)
  data.alias = false; data.allowed = false
  await assert.rejects(rooms.checkResource(Date.now()), /no longer listed/)
  assert.equal(asks.length, 0)
  data.allowed = true
  f.model(() => ({ notify: false }))
  await rooms.tick()
  f.advance(30)
  await rooms.tick()
  assert.equal(asks.length, 1)
  f.advance(30)
  data.text += '\nThe coordinator asks the group to confirm the new seating plan.'
  let resolve, begin
  const started = new Promise(r => { begin = r })
  f.model(async () => { begin(); return new Promise(r => { resolve = r }) })
  const checking = rooms.tick()
  await started
  await rooms.selectResource(rooms.checkInScope(), '', 0, '', true)
  resolve({ notify: true, line: 1, quote: 'confirm the new seating plan', offer: 'reply', goal: 0 })
  await checking
  assert.deepEqual(rooms.checkInMessages(), [])
  assert.equal(rooms.store.mailboxes.local.resource, undefined)
})

test('an assigned goal can be linked to a change in a JSON inbox; unrelated statements and forged evidence stay quiet', async t => {
  const f = await fixture(t)
  const { rooms, data } = f
  const now = Date.now()
  rooms.store.activity.push({ sessionId: 'production', requestOwner: 'local', status: 'done', steps: [], updatedAt: now })
  rooms.store.goals.push({ id: 'my-goal', sessionId: 'production', title: 'Plan ensemble rehearsal', status: 'tracking', updatedAt: now, steps: [] })
  const row = { subject: 'The ensemble rehearsal needs a new room.', status: 'Venue unavailable', messageUrl: 'https://example.invalid/private' }
  data.text = JSON.stringify({ messages: [{ subject: 'Opening announcements' }] })
  await f.enable()
  data.text = JSON.stringify({ messages: [row] })
  f.advance(30)
  f.model(records => {
    assert.deepEqual(records.goals, [[1, 'Plan ensemble rehearsal']])
    assert.deepEqual(records.updates, [[1, 'subject: The ensemble rehearsal needs a new room. · status: Venue unavailable']])
    return { notify: true, line: 1, quote: 'The concert is cancelled.', offer: 'reschedule', goal: 1 }
  })
  await rooms.checkResource(Date.now())
  assert.deepEqual(rooms.checkInMessages(), [])
  data.text = JSON.stringify({ messages: [{ ...row, subject: 'The ensemble rehearsal needs a larger room.' }] })
  f.advance(30)
  f.model(() => ({ notify: true, line: 1, quote: 'The ensemble rehearsal needs a larger room.', offer: 'reschedule', goal: 1 }))
  await rooms.checkResource(Date.now())
  assert.match(rooms.checkInMessages()[0].text, /This may affect your goal “Plan ensemble rehearsal”/)
  f.cloud.feedOwner = 'another'
  assert.deepEqual(rooms.checkInMessages(), [])
  assert.deepEqual(rooms.view().feed.routine.contextResource, undefined)
})

test('structured data retains human-facing fields and redacts addresses and connector credentials before review', async t => {
  const f = await fixture(t)
  await f.enable()
  const account = ['guest', 'fixture.invalid'].join('@')
  f.data.text = JSON.stringify({ records: [{ privateNotes: 'Hidden detail' }, { refreshToken: 'hidden-token' },
    { subject: 'Your verification code', bodyPreview: '123456 expires soon' }] })
  f.advance(30)
  await f.rooms.tick()
  f.data.text = '{"privateNotes": "Unfinished private record"'
  f.advance(30)
  await f.rooms.tick()
  assert.equal(f.asks.length, 0)
  f.data.text = JSON.stringify({ records: [{ subject: 'A reply is needed', from: account, description: 'Use references authorized and fixture-query-key', privateNotes: 'Hidden detail' }] })
  f.model(records => {
    assert.deepEqual(records.updates, [[1, 'subject: A reply is needed · description: Use references [redacted] and [redacted] · from: [email]']])
    return { notify: false }
  })
  f.advance(30)
  await f.rooms.checkResource(Date.now())
  assert.equal(f.asks.length, 1)
})

test('new connections can follow a single text resource only with a current offer and a complete listing', async t => {
  const f = await fixture(t)
  const { rooms, connector, data, cloud } = f
  const offer = rooms.newResourceOffer()
  assert.ok(offer)
  let n = 0
  const connect = followOffer => connector.finish({ id: 'new-' + n++, service: 'custom', label: 'Fixtures', serverName: 'fixtures', url: f.url, disabled: [] }, { kind: 'header', name: 'x-fixture', value: 'authorized' }, followOffer)
  const reads = () => data.calls.filter(([method]) => method === 'resources/read').length
  await connect('')
  assert.equal(data.calls.some(([method]) => method === 'resources/list'), false)
  data.multiple = true
  await connect(offer)
  data.multiple = false; data.more = true
  await connect(offer)
  data.more = false
  cloud.feedOwner = 'account:another'
  await connect(offer)
  cloud.feedOwner = 'local'
  assert.equal(reads(), 0)
  const id = await connect(offer)
  assert.equal(reads(), 1)
  assert.equal(rooms.store.mailboxes.local.resource.connection, id)
  assert.equal(f.asks.length, 0)
  await connect(offer)  // never replace an existing resource
  assert.equal(reads(), 1)
  await rooms.selectResource(rooms.checkInScope(), '', 0, '', true)
  assert.equal(rooms.newResourceOffer(), '')
  const restarted = f.make()
  restarted.store = await restarted.read()
  assert.equal(restarted.newResourceOffer(), '')
  await connect(offer)
  assert.equal(reads(), 1)
})
