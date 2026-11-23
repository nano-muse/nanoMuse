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
  let clock = now
  t.mock.method(Date, 'now', () => clock)
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
  return { rooms, cloud, setClock: at => { clock = at }, restart: async () => { const r = host(); r.store = await r.read(); return r } }
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

function turn(rooms, words, answer = '', chat = 'visit-chat') {
  const session = { id: chat }
  rooms.trackActivity(session, { type: 'turn/start' })
  const content = [{ type: 'text', text: words }]
  rooms.trackActivity(session, { type: 'user/message', data: { content, source: { kind: 'user' } } })
  if (answer) rooms.trackActivity(session, { type: 'assistant/message', data: { message: { content: [{ type: 'text', text: answer }] } } })
  rooms.trackActivity(session, { type: 'turn/end', data: { reason: { kind: 'completed' } } })
}

function draftMuseum(cloud) {
  cloud.prepareFeed = async (_system, json) => {
    const data = JSON.parse(json); cloud.inputs.push(data)
    const chat = data.records.find(r => r.kind === 'conversation' && r.text.includes('museum'))
    const note = data.records.find(r => r.kind === 'memory')
    return JSON.stringify([{ title: 'Museum inquiry', kind: 'draft', why: 'You promised to send the booking inquiry.',
      body: 'Can our museum group use the step-free entrance?', sources: [
        { id: chat.id, quote: 'museum a booking inquiry' }, { id: note.id, quote: 'step-free entrance' },
      ] }])
  }
}

test('a user commitment survives another turn and restart; a short reschedule withdraws the stale card and can replace it once that day', async t => {
  const { rooms, cloud, restart } = await fixture(t)
  rooms.store.goals = []
  rooms.activityChanged = () => {}
  draftMuseum(cloud)
  turn(rooms, 'I promised to send the museum a booking inquiry tomorrow.')
  assert.equal(await rooms.prepareFeed(), 'prepared')
  const first = rooms.view().feed.posts[0]
  turn(rooms, 'Where is the nearest bakery?')
  assert.ok(rooms.view().feed.posts.some(p => p.id === first.id))
  turn(rooms, 'The bakery delivery was cancelled.')
  assert.ok(rooms.view().feed.posts.some(p => p.id === first.id))
  turn(rooms, 'The museum cafe lunch was cancelled.')
  assert.ok(rooms.view().feed.posts.some(p => p.id === first.id))
  assert.equal(await rooms.prepareFeed(), 'quiet')
  assert.equal(cloud.inputs.length, 1)
  await rooms.save()
  const restored = await restart()
  restored.activityChanged = () => {}
  assert.ok(restored.view().feed.posts.some(p => p.id === first.id))
  assert.ok(!('commitments' in restored.activityOf('visit-chat')))
  assert.ok(!('commitments' in restored.view().activity[0]))
  turn(restored, 'The museum booking inquiry moved to Friday.')
  assert.ok(!restored.view().feed.posts.some(p => p.id === first.id))
  await assert.rejects(restored.discuss(first.id))
  assert.equal(await restored.prepareFeed(), 'prepared')
  const source = cloud.inputs.at(-1).records.find(r => r.kind === 'conversation')
  assert.match(source.timing, /2026-11-27/)
  assert.match(source.text, /Friday/)
  assert.doesNotMatch(source.text, /tomorrow/i)
  turn(restored, 'Move it to Sunday instead.')
  assert.equal(restored.view().feed.posts.length, 0)
  assert.equal(await restored.prepareFeed(), 'quiet')
  assert.equal(cloud.inputs.length, 2)
})

test('same-chat Chinese references settle only the current commitment, and a new undertaking can reopen it', async t => {
  const { rooms, cloud } = await fixture(t)
  rooms.store.goals = []
  rooms.activityChanged = () => {}
  turn(rooms, '我答应明天给美术馆写一封预约邮件。')
  turn(rooms, '我答应明天给博物馆写一封咨询邮件。')
  turn(rooms, '改到周五')
  let texts = rooms.prepSources(now).filter(s => s.kind === 'conversation')
  assert.equal(texts.length, 2)
  assert.match(texts.find(s => s.text.includes('博物馆')).text, /改到周五/)
  assert.match(texts.find(s => s.text.includes('美术馆')).text, /明天/)
  turn(rooms, '已经发了')
  texts = rooms.prepSources(now).filter(s => s.kind === 'conversation')
  assert.equal(texts.length, 1)
  assert.match(texts[0].text, /美术馆/)
  turn(rooms, 'I already sent it.', '', 'another-chat')
  assert.match(rooms.prepSources(now).find(s => s.kind === 'conversation').text, /美术馆/)
  turn(rooms, '还是要发，改到周六')
  assert.equal(rooms.prepSources(now).filter(s => s.kind === 'conversation').length, 2)
  turn(rooms, '博物馆咨询邮件已经发了。')
  assert.equal(rooms.prepSources(now).filter(s => s.kind === 'conversation').length, 1)
  cloud.feedOwner = 'other'
  assert.equal(rooms.prepSources(now).length, 0)
})

test('a later complete draft settles its own chat commitment; uncertainty, tool turns and unrelated corrections cannot settle it', async t => {
  const { rooms, cloud } = await fixture(t)
  rooms.store.goals = []
  rooms.activityChanged = () => {}
  draftMuseum(cloud)
  const words = 'I promised to send the museum a booking inquiry tomorrow.'
  turn(rooms, words)
  assert.equal(await rooms.prepareFeed(), 'prepared')
  const id = rooms.view().feed.posts[0].id
  turn(rooms, 'The museum booking was not cancelled.')
  assert.ok(rooms.view().feed.posts.some(p => p.id === id))
  turn(rooms, 'If the museum booking is cancelled, what should I do?')
  assert.ok(rooms.view().feed.posts.some(p => p.id === id))
  turn(rooms, words, 'Subject: Booking inquiry\nDear museum team, which step-free entrance is available?')
  assert.ok(!rooms.view().feed.posts.some(p => p.id === id))
  assert.equal(await rooms.prepareFeed(true), 'quiet')
  assert.equal(cloud.inputs.length, 1)
})

test('a cancellation during writing cannot land a stale draft; dated goal cards defer to explicit corrections in their own chat', async t => {
  const { rooms, cloud } = await fixture(t)
  rooms.activityChanged = () => {}
  rooms.store.goals[0].title = 'Museum booking inquiry'
  const originalDue = rooms.store.goals[0].due
  turn(rooms, 'I promised to send the museum a booking inquiry tomorrow.')
  cloud.prepareFeed = async (_system, json) => {
    const { records } = JSON.parse(json)
    turn(rooms, 'The museum booking inquiry has been cancelled.')
    return JSON.stringify([result(records)])
  }
  assert.equal(await rooms.prepareFeed(true), 'quiet')
  assert.deepEqual(rooms.prepSources(now).map(s => s.kind), ['memory'])
  await rooms.tick()
  assert.deepEqual(rooms.view().feed.posts, [])
  assert.equal(rooms.store.goals[0].due, originalDue)
  assert.equal(rooms.store.goals[0].status, 'tracking')
  rooms.store.goals[0].updatedAt = now + 1
  assert.ok(rooms.prepSources(now + 2).some(s => s.kind === 'goal'))
})

test('a user can defer an item without a date, resume it, and drop the same-day refresh by deleting its card', async t => {
  const { rooms, cloud } = await fixture(t)
  rooms.store.goals = []
  rooms.activityChanged = () => {}
  draftMuseum(cloud)
  turn(rooms, 'I promised to send the museum a booking inquiry tomorrow.')
  assert.equal(await rooms.prepareFeed(), 'prepared')
  await rooms.deletePost(rooms.view().feed.posts[0].id)
  turn(rooms, 'Postpone it.')
  assert.equal(rooms.prepSources(now).some(s => s.kind === 'conversation'), false)
  turn(rooms, 'Move it to Friday instead.')
  assert.ok(rooms.prepSources(now).some(s => s.timing.includes('2026-11-27')))
  assert.equal(await rooms.prepareFeed(), 'quiet')
  assert.equal(cloud.inputs.length, 1)
})

test('restoring an older task record does not revive delivered work or carry a new account request across profiles', async t => {
  const { rooms, cloud } = await fixture(t)
  rooms.store.goals = []
  rooms.activityChanged = () => {}
  const words = 'I promised to send the museum a booking inquiry tomorrow.'
  turn(rooms, words, 'Subject: Booking inquiry\nDear museum team, which entrance is available?')
  const legacy = rooms.store.activity[0]
  delete legacy.commitments
  delete legacy.requestOwner
  turn(rooms, 'Where can I buy bread?')
  assert.deepEqual(rooms.prepSources(now).map(s => s.kind), ['memory'])
  rooms.store.feed.routine.on = false
  turn(rooms, words)
  cloud.feedOwner = 'other'
  rooms.store.feed.routine.on = true
  assert.equal(rooms.prepSources(now).length, 0)
  turn(rooms, 'Move it to Friday.')
  assert.equal(rooms.prepSources(now).length, 0)
})

test('alternative dates await a decision; next week is absolute and an unfocused done cannot choose between tasks', async t => {
  const { rooms } = await fixture(t)
  rooms.store.goals = []
  rooms.activityChanged = () => {}
  const records = () => rooms.prepSources(now).filter(s => s.kind === 'conversation')
  turn(rooms, '我答应明天给美术馆写一封预约邮件。')
  turn(rooms, '我答应明天给博物馆写一封咨询邮件。')
  turn(rooms, '附近有面包店吗？')
  turn(rooms, '办完了')
  assert.equal(records().length, 2)
  turn(rooms, '博物馆咨询邮件改到周三或周五。')
  assert.equal(records().length, 1)
  assert.match(records()[0].text, /美术馆/)
  turn(rooms, '就定在下周五')
  assert.equal(records().length, 1)
  const due = () => rooms.store.activity[0].commitments.items.find(s => s.request.includes('博物馆')).due
  assert.equal(due(), '2026-12-04')
  turn(rooms, 'Move it to next week on Friday instead.')
  assert.equal(due(), '2026-12-04')
  assert.equal(records().length, 1)
  turn(rooms, 'Move it to Friday or Saturday.')
  assert.equal(records().length, 1)
  turn(rooms, 'Move it from Saturday to Sunday.')
  assert.match(records().find(s => s.text.includes('博物馆')).timing, /2026-11-29/)
})

test('a promise from last Tuesday becomes eligible near next Friday, survives restart and midnight, and ends after the deadline', async t => {
  const { rooms, cloud, setClock, restart } = await fixture(t)
  rooms.store.goals = []
  rooms.activityChanged = () => {}
  draftMuseum(cloud)
  const day = n => new Date(2026, 10, n, 12).getTime()
  setClock(day(24))
  turn(rooms, 'I promised to send the museum a booking inquiry next week on Friday.')
  assert.equal(await rooms.prepareFeed(), 'quiet')
  assert.equal(cloud.inputs.length, 0)
  await rooms.save()
  const restored = await restart()
  restored.activityChanged = () => {}
  setClock(day(32)) // Dec 2: eight days since the person made the promise.
  turn(restored, 'Where is the nearest bakery?')
  assert.equal(await restored.prepareFeed(), 'prepared')
  assert.match(cloud.inputs[0].records.find(r => r.kind === 'conversation').timing, /2026-12-04/)
  const card = restored.view().feed.posts[0]
  setClock(day(34))
  assert.equal(restored.view().feed.posts[0].id, card.id)
  assert.equal(await restored.prepareFeed(), 'quiet')
  assert.equal(cloud.inputs.length, 1)
  setClock(day(35))
  assert.deepEqual(restored.view().feed.posts, [])
  await assert.rejects(restored.discuss(card.id))
})

test('distant and undated promises expire at their own limits without a new chat turn', async t => {
  const { rooms, setClock } = await fixture(t)
  rooms.store.goals = []
  rooms.activityChanged = () => {}
  const day = n => new Date(2026, 10, n, 12).getTime()
  setClock(day(23))
  turn(rooms, 'I promised to send the museum a booking inquiry on 2026-12-19.')
  turn(rooms, 'I promised to draft a report for the garden committee.')
  const read = at => rooms.prepSources(at).filter(s => s.kind === 'conversation')
  assert.deepEqual(read(day(29)).map(s => s.text), ['I promised to draft a report for the garden committee.'])
  assert.equal(read(day(31)).length, 0)
  assert.match(read(day(43))[0].text, /museum/)
  assert.equal(read(day(44)).length, 0) // 21 days, while the deadline is still in the future.
  setClock(day(44))
  turn(rooms, 'What do people eat there?')
  assert.deepEqual(rooms.store.activity[0].commitments.items, [])
})

test('next Friday always means the next calendar week in every supported English word order', async t => {
  const { rooms, setClock } = await fixture(t)
  rooms.store.goals = []
  rooms.activityChanged = () => {}
  setClock(new Date(2026, 10, 24, 12).getTime()) // Tuesday
  for (const date of ['Friday', 'next Friday', 'next week on Friday', 'Friday next week', '下周五']) {
    turn(rooms, 'I promised to send the museum a booking inquiry '+date+'.', '', 'date-'+date)
    const item = rooms.store.activity.find(a => a.sessionId === 'date-'+date).commitments.items[0]
    assert.equal(item.due, date === 'Friday' ? '2026-11-27' : '2026-12-04', date)
  }
})
