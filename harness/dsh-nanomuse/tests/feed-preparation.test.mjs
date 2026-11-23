import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import Cloud from '../lib/cloud.js'
import Rooms from '../lib/rooms.js'

const now = new Date(2026, 10, 23, 12).getTime()
const goal = { id: 'visit', sessionId: 'visit-chat', status: 'tracking', title: 'Plan the museum visit', due: '2026-11-24',
  nextStep: 'Prepare the museum booking request', updatedAt: now, summary: '', steps: [], activity: [] }
const memory = { id: 'access', prepOwner: 'local', source: 'person', at: 1, text: 'We need a step-free entrance for the museum visit.' }
function result(records) {
  const g = records.find(r => r.kind === 'goal')
  const m = records.find(r => r.kind === 'memory')
  return { title: 'A question for the museum', kind: 'draft', why: 'Your booking is due tomorrow and the entrance matters.',
    body: 'Hello, which step-free entrance should we use for our museum visit?',
    sources: [{ id: g.id, quote: 'museum booking request' }, { id: m.id, quote: 'step-free entrance' }] }
}
async function fixture(t) {
  t.mock.method(Date, 'now', () => now)
  const root = await mkdtemp(join(tmpdir(), 'nm-prep-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = root
  t.after(async () => {
    if (previous === undefined) delete process.env.DSH_HOME
    else process.env.DSH_HOME = previous
    await rm(root, { recursive: true, force: true })
  })
  const cloud = {
    feedOwner: 'local', blocked: new Set(),
    isClearedSession(id) { return this.blocked.has(id) },
    scheduleSessionAccess() {
      const owner = this.feedOwner
      return id => this.feedOwner === owner && !this.blocked.has(id)
    },
    inputs: [],
    async prepareFeed(system, json) {
      const data = JSON.parse(json)
      this.inputs.push(data)
      return JSON.stringify([result(data.records)])
    },
  }
  function host() {
    const rooms = new Rooms({ reflect: { provide() {} }, nanomuseCloud: cloud, logger: { warn() {} } })
    rooms.broadcast = () => {}
    rooms.syncReady = async () => true
    return rooms
  }
  const rooms = host()
  Object.assign(rooms.store, { lang: 'en', goals: [structuredClone(goal)], memory: [structuredClone(memory)] })
  rooms.store.feed.routine.time = '00:00'
  return { rooms, cloud, restart: async () => { const r = host(); r.store = await r.read(); return r } }
}

test('scheduled preparation produces usable text with host-resolved sources and never reruns the published evidence pair', async t => {
  const { rooms, cloud, restart } = await fixture(t)
  let research = 0
  rooms.refreshFeed = async () => { research++ }
  await rooms.tick()
  const card = rooms.store.feed.posts.find(p => p.preparation)
  assert.equal(card.preparation.kind, 'draft')
  assert.ok(!rooms.view().feed.posts.some(p => p.goalId === goal.id))
  assert.equal(card.preparation.sources[0].title, goal.title)
  assert.equal(card.preparation.sources[1].quote, 'step-free entrance')
  assert.ok(card.body.includes('which step-free entrance'))
  assert.equal(research, 0)
  assert.equal(cloud.inputs.length, 1)
  assert.equal(await rooms.prepareFeed(), 'quiet')
  await rooms.deletePost(card.id)
  assert.ok(!rooms.store.feed.posts.some(p => p.goalId === goal.id))
  const again = await restart()
  assert.equal(await again.prepareFeed(true), 'quiet')
  assert.ok(!again.store.feed.posts.some(p => p.preparation))
  again.store.goals[0].nextStep += ' by email'
  assert.equal(await again.prepareFeed(true), 'prepared')
})

test('candidate inventory selects a relevant older memory, omits restricted records and file contents', async t => {
  const { rooms, cloud } = await fixture(t)
  for (let i = 0; i < 20; i++) rooms.store.memory.push({ ...memory, id: 'other-' + i, text: 'Unrelated books ' + i, at: now - i })
  rooms.store.memory.push({ ...memory, id: 'agent', source: 'agent', text: 'Generated private speculation' },
    { ...memory, id: 'other', prepOwner: 'other', text: 'Another account private note' },
    { ...memory, id: 'unknown', prepOwner: undefined, text: 'Old unattributed memory' })
  rooms.store.goals.push({ ...goal, id: 'muted', sessionId: 'muted', feedMuted: true }, { ...goal, id: 'blocked', sessionId: 'blocked' })
  cloud.blocked.add('blocked')
  rooms.store.library.push({ id: 'file', name: 'Booking notes', at: now, description: 'The museum catalogue', sessionId: 'file-chat', path: '/never/read/this' })
  rooms.store.activity.push({ sessionId: 'muted', status: 'done', request: 'Muted conversation', requestAt: now },
    { sessionId: 'old', status: 'done', request: 'Old conversation', endedAt: now },
    { sessionId: 'new', status: 'done', request: 'Which gallery has an entrance?', requestAt: now, words: 'Private assistant reply' })
  await rooms.prepareFeed(true)
  const { records } = cloud.inputs[0]
  assert.equal(records.filter(r => r.kind === 'memory').length, 10)
  assert.ok(records.some(r => r.text === memory.text))
  assert.equal(records.filter(r => r.kind === 'goal').length, 1)
  assert.equal(records.filter(r => r.kind === 'conversation').length, 1)
  assert.doesNotMatch(JSON.stringify(records), /another account|speculation|unattributed|\/never|assistant reply|Muted conversation|Old conversation/i)
})

test('quiet decisions, unrelated generic output, fabricated citations and duplicated origins stay silent', async t => {
  const { rooms, cloud } = await fixture(t)
  let research = 0, calls = 0
  rooms.refreshFeed = async () => { research++ }
  cloud.prepareFeed = async () => { calls++; return '[]' }
  await rooms.tick()
  assert.equal(calls, 1)
  assert.equal(research, 0)
  assert.equal(await rooms.prepareFeed(), 'quiet')
  assert.equal(calls, 1)
  for (const edit of [
    r => { r.sources[1].id = 'made-up' }, r => { r.sources[0].quote = 'invented booking time' },
    r => { r.sources[1] = r.sources[0] },
    r => { r.body += ' We will bring 30 people.' }, r => { r.body += ' Fees are $24 per person.' },
    r => { r.body += ' We booked 09:30.' }, r => { r.body += ' 我们一行三十人。' },
    r => { r.body += ' We need thirty guests admitted.' }, r => { r.body = 'Perhaps now would be a good time to start. What do you think?' },
  ]) {
    cloud.prepareFeed = async (_system, json) => { const r = result(JSON.parse(json).records); edit(r); return JSON.stringify([r]) }
    assert.equal(await rooms.prepareFeed(true), 'quiet')
  }
  rooms.store.memory = []
  rooms.store.library = [{ id: 'same', name: 'Floor plan', description: 'Museum', sessionId: goal.sessionId, at: now }]
  assert.equal(await rooms.prepareFeed(true), 'quiet')
  await rooms.setFeedRoutine({ reading: true })
  await rooms.tick()
  assert.equal(research, 1)
})

test('forgetting a source, clearing its chat or switching accounts prevents stale publication and discussion', async t => {
  const { rooms, cloud } = await fixture(t)
  const generate = cloud.prepareFeed.bind(cloud)
  for (const change of [() => { rooms.store.goals[0].status = 'done' }, () => cloud.blocked.add(goal.sessionId), () => { cloud.feedOwner = 'other' }]) {
    cloud.prepareFeed = async (...args) => { change(); return generate(...args) }
    assert.equal(await rooms.prepareFeed(true), 'quiet')
    rooms.store.goals[0].status = 'tracking'; cloud.blocked.clear(); cloud.feedOwner = 'local'
  }
  cloud.prepareFeed = generate
  assert.equal(await rooms.prepareFeed(true), 'prepared')
  const card = rooms.store.feed.posts[0]
  cloud.feedOwner = 'other'
  assert.ok(!rooms.view().feed.posts.some(p => p.id === card.id))
  await assert.rejects(rooms.discuss(card.id))
  cloud.feedOwner = 'local'
  await rooms.forget(memory.id)
  assert.ok(!rooms.store.feed.posts.some(p => p.id === card.id))
  assert.ok(!(await rooms.read()).feed.posts.some(p => p.id === card.id))
})

test('background model stream uses the chosen provider without tools and discards tool or partial responses', async () => {
  const sessionIds = [], released = []
  let options, parts = [{ type: 'text-delta', text: '[]' }, { type: 'finish', reason: { kind: 'stop' } }]
  const ctx = { get: () => ({ async *stream(request) { options = request; yield* parts } }) }
  const cloud = { ctx, defaultModelService: () => ({ currentSelection: () => ({ provider: 'fixture', model: 'chosen' }) }),
    provenance: { setRun(id, origin) { assert.equal(origin, 'feed'); sessionIds.push(id) }, forget(id) { released.push(id) } } }
  const run = () => Cloud.prototype.prepareFeed.call(cloud, 'system', 'local evidence', new AbortController().signal)
  assert.equal(await run(), '[]')
  assert.deepEqual(options.tools, [])
  assert.equal(options.model, 'chosen')
  assert.equal(options.provider, 'fixture')
  parts = [{ type: 'text-delta', text: '[{"unfinished"' }, { type: 'finish', reason: { kind: 'length' } }]
  await assert.rejects(run())
  parts = [{ type: 'block-end', block: { type: 'tool-call' } }]
  await assert.rejects(run())
  assert.deepEqual(released, sessionIds)
})

test('a concrete conversation commitment can produce a checklist without a formal goal; a lone casual mention stays quiet', async t => {
  const { rooms, cloud } = await fixture(t)
  rooms.store.goals = []
  rooms.store.activity = [{ sessionId: 'visit-chat', request: 'I will call the museum tomorrow to book the group visit.',
    requestAt: now, status: 'done', steps: [], turns: 1 }]
  let calls = 0
  cloud.prepareFeed = async (_system, json) => {
    calls++
    const { records, today } = JSON.parse(json)
    assert.equal(today, '2026-11-23')
    assert.match(records[0].timing, /2026-11-23/)
    assert.deepEqual(records.map(r => r.kind), ['conversation', 'memory'])
    return JSON.stringify([{ kind: 'checklist', title: 'Two questions for tomorrow’s museum call',
      why: 'You plan to call tomorrow and your group needs a step-free entrance.',
      body: '1. Ask which step-free entrance the group should use.\n2. Ask whether the group visit requires a separate entrance booking.',
      sources: [{ id: records[0].id, quote: 'call the museum tomorrow' }, { id: records[1].id, quote: 'step-free entrance' }] }])
  }
  assert.equal(await rooms.prepareFeed(true), 'prepared')
  const [card] = rooms.store.feed.posts
  assert.equal(card.preparation.kind, 'checklist')
  assert.equal(await rooms.discuss(card.id), 'visit-chat')
  await rooms.deletePost(card.id)
  rooms.store.activity[0].request = 'I enjoyed seeing the museum.'
  rooms.store.memory = []
  assert.equal(await rooms.prepareFeed(true), 'quiet')
  assert.equal(calls, 1)
})

test('a headcount in the cited record can be used, while the day of month cannot supply a headcount', async t => {
  const { rooms, cloud } = await fixture(t)
  cloud.prepareFeed = async (_system, json) => {
    const row = result(JSON.parse(json).records)
    row.body = 'Can our 24 people use the step-free entrance?'
    return JSON.stringify([row])
  }
  assert.equal(await rooms.prepareFeed(true), 'quiet')
  rooms.store.memory[0].text += ' We are 24 people.'
  assert.equal(await rooms.prepareFeed(true), 'prepared')
  assert.match(rooms.store.feed.posts[0].body, /24 people/)
})

test('upgrading keeps old posts and explicit reading preferences, while untouched or paused routines stay quiet', async t => {
  const { rooms, restart } = await fixture(t)
  const legacyPost = { id: 'existing', title: 'A saved reading post', body: 'Related background.', at: 1, liked: true }
  rooms.store.feed.posts = [legacyPost]
  for (const [on, instructions, expected] of [[true, 'Weekly history reading', 1], [true, '', 0], [false, 'Weekly history reading', 0]]) {
    rooms.store.feed.routine = { on, time: '00:00', ensuredAt: 1 }
    rooms.store.feed.instructions = instructions
    await rooms.save()
    const next = await restart()
    let batches = 0
    next.refreshFeed = async () => { batches++ }
    await next.tick()
    assert.equal(batches, expected)
    assert.ok(next.view().feed.posts.some(p => p.id === legacyPost.id && p.liked))
  }
})

test('a commitment to send an inquiry needs a usable draft, and the automatic first conversation respects the selected hour', async t => {
  const { rooms, cloud } = await fixture(t)
  rooms.store.goals = []
  rooms.store.activity = [{ sessionId: 'visit-chat', status: 'done', requestAt: now, request: 'I promised to send the museum a booking inquiry tomorrow.' }]
  rooms.store.feed.routine.time = '20:00'
  rooms.ready = true
  let kind = 'checklist', calls = 0
  cloud.prepareFeed = async (_system, json) => {
    calls++
    const { records } = JSON.parse(json)
    assert.equal(records[0].deliverable, 'draft')
    return JSON.stringify([{ kind, title: 'Museum booking inquiry', why: 'Your booking inquiry is due tomorrow.',
      body: kind === 'draft' ? 'Hello, which step-free entrance should our museum group use?' : '1. Send the museum booking inquiry.\n2. Ask about the step-free entrance.',
      sources: [{ id: 'r1', quote: 'museum a booking inquiry' }, { id: 'r2', quote: 'step-free entrance' }] }])
  }
  rooms.onFirstConversationOver()
  assert.equal(calls, 0)
  assert.equal(await rooms.prepareFeed(true), 'quiet')
  kind = 'draft'
  assert.equal(await rooms.prepareFeed(true), 'prepared')
})

test('a draft already delivered in the same turn suppresses correspondence preparation locally', async t => {
  const { rooms, cloud } = await fixture(t)
  rooms.store.goals = []
  rooms.store.activity = [{ sessionId: 'visit-chat', status: 'done', requestAt: now, request: 'I promised to send the museum a booking inquiry tomorrow.',
    steps: [{ kind: 'answer', at: now, detail: 'Subject: Museum availability\nDear team, which step-free entrance can the group use?' }] }]
  assert.equal(await rooms.prepareFeed(true), 'quiet')
  assert.equal(cloud.inputs.length, 0)
})
