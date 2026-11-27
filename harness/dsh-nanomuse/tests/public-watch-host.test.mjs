// The desktop stores the ledger in the current owner's private mailbox; only selected
// public evidence can enter a local chat. The worker transport itself is exercised by pytest.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import Rooms from '../lib/rooms.js'

function fixture(t) {
  const now = new Date(2026, 3, 10, 11).getTime()
  t.mock.method(Date, 'now', () => now)
  const cloud = { feedOwner: 'local', syncMainSession: () => 'main', isClearedSession: () => false,
    scheduleSessionAccess() { const owner = this.feedOwner; return () => owner === this.feedOwner },
    hasRemoteReplySince: () => false,
    prepareFeed: async () => '{"notify":false}' }
  const ctx = { nanomuseCloud: cloud, reflect: { provide() {} }, logger: { warn() {} },
    get: key => key === 'workspaceRegistry' ? { archivedSessionIds: [] } : undefined }
  const rooms = new Rooms(ctx)
  rooms.save = async () => {}
  rooms.broadcast = () => {}
  rooms.prepSources = () => []
  rooms.store.lang = 'en'
  const box = rooms.ensureMailbox('local')
  const changes = Object.fromEntries(['first', 'second'].map(key =>
    [key, { text: key + ' paper changed its results', at: now / 1000, url: 'https://example.org/' + key }]))
  const ledger = { enabled: true, generation: 'g1', watches: { paper: { id: 'paper', target: 'topic', label: 'topic', kind: 'research_topic',
    status: 'active', next: now / 1000 + 1000, pending: changes } } }
  box.publicWatches = ledger
  return { now, cloud, rooms, box, ledger }
}

test('scoped native controls hide pending evidence and reject stale revisions', async t => {
  const { rooms, cloud } = fixture(t)
  const scope = rooms.checkInScope()
  const view = await rooms.publicWatchSettings({ scope })
  assert.equal(view.watches.length, 1)
  assert.equal(JSON.stringify(view).includes('changed its results'), false)
  let finish
  rooms.watchWorker = async (state, { edit }) => {
    assert.equal(edit.enabled, false)
    await new Promise(resolve => { finish = resolve })
    return { ...state, enabled: false, generation: 'g2' }
  }
  const edit = rooms.publicWatchSettings({ scope, revision: view.revision, enabled: false })
  await assert.rejects(rooms.publicWatchSettings({ scope, revision: view.revision, enabled: false }), /Reopen/)
  cloud.feedOwner = 'account:other'
  finish()
  await assert.rejects(edit, /Reopen/)
  assert.deepEqual((await rooms.publicWatchSettings({ scope: rooms.checkInScope() })).watches, [])
  cloud.feedOwner = 'local'
  assert.equal((await rooms.publicWatchSettings({ scope })).enabled, true)
})

test('offline polling cannot overwrite an account change or disabled watch', async t => {
  const { rooms, cloud, box, ledger, now } = fixture(t)
  ledger.watches.paper.next = 0
  let finish
  const pending = new Promise(resolve => { finish = resolve })
  rooms.watchWorker = async () => { await pending; return { enabled: true, generation: 'late', watches: {} } }
  const tick = rooms.checkPublicWatches(now)
  rooms.resetWatchWork()
  cloud.feedOwner = 'different'
  finish()
  await tick
  assert.equal(box.publicWatches.generation, 'g1')
  assert.equal(rooms.checkInMessages('main').length, 0)
  cloud.feedOwner = 'local'
  rooms.watchWorker = async () => { throw new Error('reader offline') }
  await assert.rejects(rooms.checkPublicWatches(now), /reader offline/)
  assert.equal(box.publicWatches, ledger)
  box.publicWatches.enabled = false
  await rooms.checkPublicWatches(now)
  assert.equal(box.messages.length, 0)
})

test('invalid findings remain pending, and a valid alert keeps the other changes for later review', async t => {
  const { rooms, cloud, box, ledger, now } = fixture(t)
  cloud.prepareFeed = async () => '{"notify":true,"line":9,"offer":"invented"}'
  await rooms.checkPublicWatches(now)
  assert.deepEqual(Object.keys(ledger.watches.paper.pending), ['first', 'second'])
  assert.equal(box.messages.length, 0)
  cloud.prepareFeed = async (system, input) => {
    assert.match(system, /untrusted/)
    assert.ok(!input.includes('https:'))
    return JSON.stringify({ notify: true, line: 2, quote: 'second paper changed', offer: 'prepare', goal: 0 })
  }
  await rooms.checkPublicWatches(now)
  assert.deepEqual(Object.keys(ledger.watches.paper.pending), ['first'])
  const [notice] = rooms.checkInMessages('main')
  assert.match(notice.text, /second paper changed its results/)
  assert.match(notice.text, /https:\/\/example.org\/second/)
  assert.equal(notice.external, true)
  assert.equal(box.publicReviews.count, 2)
  await rooms.checkPublicWatches(now)
  assert.equal(box.messages.length, 1)
})

test('a late review cannot publish or consume evidence after a main-chat or permission change', async t => {
  const { rooms, cloud, box, ledger, now } = fixture(t)
  cloud.prepareFeed = async () => {
    cloud.syncMainSession = () => 'new-main'
    return JSON.stringify({ notify: true, line: 1, quote: 'first paper changed', offer: 'prepare', goal: 0 })
  }
  await rooms.checkPublicWatches(now)
  assert.deepEqual(Object.keys(ledger.watches.paper.pending), ['first', 'second'])
  assert.equal(box.messages.length, 0)
})

test('only opted-in, exclusively public findings can be shared through the current main conversation', async t => {
  for (const mode of ['off', 'offline', 'private-goal', 'public']) {
    await t.test(mode, async t => {
      const { rooms, box, cloud, ledger, now } = fixture(t)
      cloud.feedOwner = 'account:tester'
      rooms.store.mailboxes[cloud.feedOwner] = box
      ledger.share_public_updates = mode !== 'off'
      ledger.share_generation = ledger.share_public_updates ? 'grant-1' : ''
      cloud.publicWatchSyncAvailable = sid => sid === 'main' && mode !== 'offline'
      cloud.publicWatchSyncActive = async sid => cloud.publicWatchSyncAvailable(sid)
      let ready = 0
      cloud.publicWatchReady = () => { ready++ }
      if (mode === 'private-goal') {
        rooms.store.activity = [{ sessionId: 'owned', requestOwner: cloud.feedOwner }]
        rooms.prepSources = () => [{ kind: 'goal', title: 'Review paper results', id: 'private-goal', origin: 'owned' }]
      }
      cloud.prepareFeed = async (system, input) => {
        assert.match(system, /paper citing/)
        const data = JSON.parse(input)
        assert.deepEqual(data.source, { kind: 'research_topic', target: 'topic' })
        assert.equal(data.goals.length, mode === 'private-goal' ? 1 : 0)
        return JSON.stringify({ notify: true, line: 1, quote: 'first paper changed', offer: 'read', goal: 0 })
      }
      await rooms.checkPublicWatches(now)
      const shared = rooms.publicWatchSyncLines('main')
      assert.equal(shared.length, mode === 'public' ? 1 : 0)
      assert.equal(ready, shared.length)
      if (shared.length) {
        assert.equal(shared[0].role, 'assistant')
        assert.equal(shared[0].text, 'first paper changed its results\nhttps://example.org/first')
        assert.equal(shared[0].id, box.messages[0].id)
        assert.equal(rooms.publicWatchSyncLines('other').length, 0)
        ledger.share_generation = 'grant-2'
        assert.equal(shared[0].authorized(), false)
        assert.equal(rooms.publicWatchSyncLines('main').length, 0)
      }
    })
  }
})
