// Background desktop follow-ups use local clock time; no model, Feed visit, or live account is needed.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import Rooms from '../lib/rooms.js'
import Cloud from '../lib/cloud.js'

const time = (day, hour) => new Date(2026, 2, day, hour).getTime()
function host() {
  const cloud = {
    feedOwner: 'local',
    scheduleSessionAccess: () => id => id !== 'cleared',
    isClearedSession: id => id === 'cleared',
    hasRemoteReplySince: id => id === 'remote-updated',
  }
  const ctx = { reflect: { provide() {} }, logger: { warn() {} }, nanomuseCloud: cloud,
    get: key => key === 'workspaceRegistry' ? { archivedSessionIds: ['archive'] } : undefined }
  const rooms = new Rooms(ctx)
  rooms.syncReady = async () => false
  rooms.broadcast = () => {}
  rooms.activityChanged = () => {}
  rooms.store.lang = 'en'
  return rooms
}
function say(rooms, sessionId, text) {
  const session = { id: sessionId, header: {} }
  rooms.trackActivity(session, { type: 'turn/start' })
  rooms.trackActivity(session, { type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text }] } })
  rooms.trackActivity(session, { type: 'turn/end', data: { reason: { kind: 'completed' } } })
}
function enable(rooms) {
  return rooms.setFeedRoutine({ chatCheckIns: true, checkInScope: rooms.checkInScope() })
}

test('an offline background tick delivers the due commitment in the original chat once, with replay, scoped access, and a short reply', async t => {
  const home = await mkdtemp(join(tmpdir(), 'nm-chat-checkins-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  t.after(async () => {
    if (previous === undefined) delete process.env.DSH_HOME
    else process.env.DSH_HOME = previous
    await rm(home, { recursive: true, force: true })
  })
  let now = time(7, 9)
  t.mock.method(Date, 'now', () => now)
  let rooms = host()
  say(rooms, 'older', 'I will call the gallery tomorrow.')
  await rooms.tick()
  assert.deepEqual(rooms.checkInMessages(), [])
  now += 1
  await enable(rooms)
  now = time(7, 12)
  say(rooms, 'museum', 'I promised to call the museum tomorrow.')
  now += 100
  say(rooms, 'museum', 'I will proofread a different document next Friday.')
  now = time(8, 8)
  await rooms.tick()
  assert.deepEqual(rooms.checkInMessages(), [])
  now = time(8, 9)
  await Promise.all([rooms.tick(), rooms.tick(), rooms.tick()])
  const [sent] = rooms.checkInMessages()
  assert.equal(sent.sessionId, 'museum')
  assert.match(sent.text, /call the museum tomorrow/)
  assert.ok(!sent.text.includes('Friday'))
  assert.equal(sent.unread, true)
  assert.equal(rooms.checkInMessages().length, 1)
  rooms = host()
  rooms.store = await rooms.read()
  await rooms.tick()
  assert.deepEqual(rooms.checkInMessages(), [sent])
  const pc = { get: key => key === 'nanomuseRooms' ? rooms : { inspect: async () => ({ events: [
    { type: 'user/message', time: now + 1, data: { source: { kind: 'user' }, id: 'reply' } },
  ] }) } }
  const projected = await Cloud.prototype.remoteLines.call({ cached: () => ({}) }, pc, 'museum', false)
  assert.equal(projected.lines[0].id, sent.id)
  assert.equal(projected.lines[0].before, '13:input-messagereply')
  assert.equal(projected.lines[0].localCheckIn, true)
  const firstScope = rooms.checkInScope()
  rooms.ctx.nanomuseCloud.feedOwner = 'account:test'
  assert.deepEqual(rooms.checkInMessages('museum'), [])
  await assert.rejects(rooms.setFeedRoutine({ chatCheckIns: true, checkInScope: firstScope }), /current account/)
  rooms.ctx.nanomuseCloud.feedOwner = 'local'
  now += 1
  say(rooms, 'museum', 'Done.')
  const state = rooms.store.activity.find(a => a.sessionId === 'museum').commitments
  assert.equal(state.items.find(i => i.request.includes('museum')).closed, true)
  assert.ok(!state.items.find(i => i.request.includes('different')).closed)
  await rooms.clearActivity(['museum'])
  assert.deepEqual(rooms.checkInMessages(), [])
  assert.equal(rooms.store.mailboxes.local.lastDay, '2026-03-08')
})

test('uncertain, closed, quiet, recent, muted, archived, cleared, or updated-on-another-device tasks stay quiet', async t => {
  const rooms = host()
  rooms.save = async () => {}
  let now = time(7, 10)
  t.mock.method(Date, 'now', () => now)
  await enable(rooms)
  now += 1
  for (const id of ['archive', 'cleared', 'remote-updated', 'closed', 'muted', 'busy']) say(rooms, id, 'I will call the gallery tomorrow.')
  say(rooms, 'closed', 'I already called it off.')
  say(rooms, 'uncertain', 'I will call the museum tomorrow or Friday.')
  say(rooms, 'changed-mind', 'I will call the museum tomorrow.')
  now += 1
  say(rooms, 'changed-mind', 'I will not call the museum after all.')
  say(rooms, 'negated', 'I will not call the gallery tomorrow.')
  say(rooms, 'unlikely', 'I will perhaps call the gallery tomorrow.')
  say(rooms, 'negative-cn', '我明天要处理的事里不需要联系博物馆。')
  say(rooms, 'question', 'Do you think I will remember to call the museum tomorrow?')
  rooms.store.goals.push({ id: 'muted', sessionId: 'muted', status: 'tracking', feedMuted: true })
  rooms.store.activity.find(a => a.sessionId === 'busy').status = 'running'
  now = time(8, 12)
  await rooms.writeChatCheckIn(now)
  assert.deepEqual(rooms.checkInMessages(), [])
  say(rooms, 'eligible', 'I will visit the museum today.')
  await rooms.writeChatCheckIn(now)
  assert.deepEqual(rooms.checkInMessages(), [])
  now = time(8, 20)
  await rooms.writeChatCheckIn(now)
  assert.deepEqual(rooms.checkInMessages(), [])
  now = time(8, 18)
  rooms.save = async () => { throw new Error('storage failed') }
  await assert.rejects(rooms.writeChatCheckIn(now), /storage failed/)
  assert.equal(rooms.checkInMessages().length, 0)
  rooms.save = async () => {}
  await rooms.writeChatCheckIn(now)
  assert.deepEqual(rooms.checkInMessages().map(m => m.sessionId), ['eligible'])
})
