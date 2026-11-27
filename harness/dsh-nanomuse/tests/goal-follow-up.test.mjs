import assert from 'node:assert/strict'
import { mkdtemp, mkdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Readable } from 'node:stream'
import { test } from 'node:test'
import Rooms from '../lib/rooms.js'
import { parseGoalBlock, parseGoalUpdate } from '../lib/fences.js'

const noon = (day, hour = 12) => new Date(2026, 2, day, hour).getTime()
function goal(id, due, extra = {}) {
  return { id, title: id, description: '', category: 'other', status: 'tracking', sessionId: 'chat-' + id,
    createdAt: noon(1), updatedAt: noon(9), summary: '', activity: [], steps: [], progress: -1, attention: false, due, ...extra }
}
function host(goals = []) {
  const ctx = { reflect: { provide() {} }, logger: { warn() {} }, nanomuseCloud: { isClearedSession: id => id === 'chat-cleared' } }
  const rooms = new Rooms(ctx)
  rooms.store.goals = goals
  rooms.store.lang = 'en'
  rooms.broadcast = () => {}
  rooms.syncReady = async () => false
  return rooms
}
async function post(rooms, route, body = {}) {
  const req = Readable.from([Buffer.from(JSON.stringify(body))])
  Object.assign(req, { method: 'POST', url: '/nanomuse/rooms/' + route, headers: {} })
  const res = { writeHead(status) { this.status = status; return this }, end(raw) { this.body = raw ? JSON.parse(raw) : undefined } }
  await rooms.handle(req, res)
  return res
}
async function testHome(t) {
  const dir = await mkdtemp(join(tmpdir(), 'nm-goal-followup-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = dir
  t.after(async () => {
    if (previous === undefined) delete process.env.DSH_HOME
    else process.env.DSH_HOME = previous
    await rm(dir, { recursive: true, force: true })
  })
  return dir
}

test('upcoming, due and recently missed deadlines each surface once, in local calendar order', async () => {
  const source = [
    goal('cleared', '2026-03-09'), goal('muted', '2026-03-09', { feedMuted: true }), goal('paused', '2026-03-09', { status: 'paused' }),
    goal('done', '2026-03-09', { status: 'done' }), goal('tomorrow', '2026-03-10'), goal('old', '2026-03-01'),
    goal('last-week', '2026-03-02'), goal('yesterday', '2026-03-08'), goal('today', '2026-03-09'), goal('future', '2026-03-11'),
    goal('no-date', undefined), goal('bad-date', '2026-02-30'), goal('attention', undefined, { attention: true, summary: 'Choose a date.' }),
    goal('old-attention', undefined, { attention: true, summary: 'An old check.', updatedAt: noon(1) }),
  ]
  const ranks = []
  for (let i = 0; i < 6; i++) {
    const rooms = host(source)
    rooms.save = async () => {}
    await rooms.writeGoalFollowUp(noon(9))
    const post = rooms.store.feed.posts[0]
    if (post) ranks.push(post.goalId)
  }
  assert.deepEqual(ranks, ['today', 'yesterday', 'last-week', 'tomorrow', 'attention'])
  const rooms = host([goal('review', '2026-03-10', { steps: ['Completed plan item'] })])
  rooms.save = async () => {}
  for (const [day, reason] of [[9, /due tomorrow/], [10, /due today/], [11, /still open/], [12], [17], [18]]) {
    await rooms.writeGoalFollowUp(noon(day))
    assert.equal(rooms.store.feed.posts.length, reason ? 1 : 0)
    if (reason) {
      assert.match(rooms.store.feed.posts[0].body, reason)
      assert.ok(!rooms.store.feed.posts[0].body.includes('Completed plan item'))
    }
  }
})

test('the Feed route and timer share one durable offline card, including after a restart and dismissal', async t => {
  await testHome(t)
  t.mock.method(Date, 'now', () => noon(9))
  const rooms = host([goal('review', '2026-03-09', { nextStep: 'Proofread the draft' }), goal('other', '2026-03-08')])
  const [opening] = await Promise.all([post(rooms, 'feed/open'), rooms.tick(), rooms.tick()])
  assert.equal(opening.status, 200)
  const [card] = rooms.store.feed.posts
  assert.match(card.body, /Planned next step: Proofread the draft/)
  assert.deepEqual((await post(rooms, 'feed/discuss', { id: card.id })).body, { sessionId: 'chat-review' })
  const restarted = host()
  restarted.store = await restarted.read()
  await restarted.tick()
  assert.deepEqual(restarted.store.feed.posts, [card])
  await post(restarted, 'feed/delete', { id: card.id })
  await post(restarted, 'feed/open')
  assert.equal(restarted.store.feed.posts.length, 0)
  assert.equal((await restarted.read()).feed.lastGoalFollowUpDay, '2026-03-09')
})

test('a due date or mute edited in Goals changes the card and its availability from the Feed', async t => {
  await testHome(t)
  t.mock.method(Date, 'now', () => noon(9))
  const rooms = host([goal('proposal', undefined)])
  const invalid = await post(rooms, 'goals/update', { id: 'proposal', due: '2026-02-29', title: 'Invalid edit' })
  assert.equal(invalid.status, 400)
  assert.equal(rooms.store.goals[0].title, 'proposal')
  assert.equal((await post(rooms, 'goals/update', { id: 'proposal', due: '2026-03-09' })).status, 200)
  await rooms.tick()
  const reminder = rooms.store.feed.posts[0]
  assert.ok(reminder)
  assert.equal((await post(rooms, 'goals/update', { id: 'proposal', feedMuted: true })).status, 200)
  assert.equal((await post(rooms, 'feed/discuss', { id: reminder.id })).status, 404)
  await rooms.writeGoalFollowUp(noon(10))
  assert.deepEqual(rooms.store.feed.posts, [])
  assert.equal((await rooms.read()).goals[0].feedMuted, true)
})

test('routine time and off switch gate offline cards and automatic model batches', async t => {
  const rooms = host([goal('review', '2026-03-09')])
  rooms.save = async () => {}
  t.mock.method(Date, 'now', () => noon(9, 7))
  await post(rooms, 'feed/open')
  assert.deepEqual(rooms.store.feed.posts, [])
  rooms.syncReady = async () => true
  rooms.ready = true
  let batches = 0
  rooms.refreshFeed = async () => { batches++ }
  await post(rooms, 'feed/routine', { on: false, time: '06:00' })
  rooms.onFirstConversationOver()
  await rooms.tick()
  assert.equal(batches, 0)
  assert.equal(rooms.store.feed.posts.length, 0)
  await post(rooms, 'feed/routine', { on: true })
  assert.equal(rooms.store.feed.posts[0].goalId, 'review')
})

test('failed storage writes are retried before the local reminder is announced', async t => {
  const dir = await testHome(t)
  const file = join(dir, 'nanomuse', 'rooms.json')
  await mkdir(file, { recursive: true })
  const rooms = host([goal('review', '2026-03-09')])
  let published = 0
  rooms.broadcast = () => { published++ }
  await assert.rejects(rooms.writeGoalFollowUp(noon(9)))
  assert.equal(published, 0)
  await rm(file, { recursive: true })
  await rooms.writeGoalFollowUp(noon(9))
  assert.equal(published, 1)
  assert.equal((await rooms.read()).feed.posts.length, 1)
})

test('dated planning and check-in fences retain only the supplied date and current step', async () => {
  assert.equal(parseGoalBlock('{"title":"Trip","due":"2028-02-29"}').due, '2028-02-29')
  assert.equal(parseGoalBlock('{"title":"Trip","due":"2027-02-29"}').due, undefined)
  const rooms = host([goal('trip', undefined, { nextStep: 'Make the list' })])
  rooms.save = async () => {}
  await rooms.applyGoalUpdate(parseGoalUpdate('{"goal_id":"trip","progress":30,"note":"List ready."}'), 'chat-trip')
  assert.equal(rooms.store.goals[0].nextStep, undefined)
  await rooms.applyGoalUpdate(parseGoalUpdate('{"goal_id":"trip","progress":30,"next_step":"Gather documents"}'), 'chat-trip')
  assert.equal(rooms.store.goals[0].nextStep, 'Gather documents')
})

test('an open reminder updates with the plan, and expires on re-dating, completion, or local midnight', async t => {
  const rooms = host([goal('trip', '2026-03-09', { nextStep: 'Gather documents' })])
  rooms.save = async () => {}
  const clock = t.mock.method(Date, 'now', () => noon(9))
  await rooms.tick()
  const old = rooms.store.feed.posts[0]
  await rooms.applyGoalUpdate(parseGoalUpdate('{"goal_id":"trip","progress":60,"note":"Papers ready.","next_step":"Check the route"}'), 'chat-trip')
  assert.match(rooms.store.feed.posts[0].body, /Check the route/)
  assert.doesNotMatch(rooms.store.feed.posts[0].body, /Gather documents/)
  await rooms.updateGoal('trip', { due: '2026-03-12' })
  assert.equal(rooms.store.feed.posts.length, 0)
  assert.equal((await post(rooms, 'feed/discuss', { id: old.id })).status, 404)
  clock.mock.mockImplementation(() => noon(11))
  await rooms.tick()
  const next = rooms.store.feed.posts[0]
  clock.mock.mockImplementation(() => noon(12, 0))
  assert.equal((await post(rooms, 'feed/discuss', { id: next.id })).status, 404)
  await rooms.writeGoalFollowUp(Date.now())
  assert.equal(rooms.store.feed.posts.length, 0)
  clock.mock.mockImplementation(() => noon(12))
  await rooms.tick()
  rooms.askNudge = async () => {}
  await rooms.applyGoalUpdate(parseGoalUpdate('{"goal_id":"trip","progress":100,"status":"done"}'), 'chat-trip')
  assert.equal(rooms.store.feed.posts.length, 0)
})
