import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import { history, patchFiles, Timeline } from '../lib/coding-timeline.js'
import { page, preview, sessionMetadata } from '../lib/coding-protocol.js'
import { CodingService } from '../lib/coding.js'

const fixtures = JSON.parse(await readFile(new URL('../../../tests/fixtures/coding-timeline.json', import.meta.url), 'utf8'))

test('Codex raw and JSON-wrapped apply_patch calls retain retrievable diffs', () => {
  const patch = '*** Begin Patch\n*** Update File: a.py\n@@\n-old\n+new\n*** End Patch'
  for (const raw of [patch, JSON.stringify({ patch }), { patch }]) {
    const timeline = new Timeline()
    timeline.call('patch-1', 'functions.apply_patch', raw)
    timeline.result('patch-1', 'Success')
    const item = timeline.values()[0]
    assert.equal(item.kind, 'file_change')
    assert.equal(item.files[0].diff, '@@\n-old\n+new')
    assert.equal(preview(item).files[0].diff_reference, 'patch-1:0')
    assert.equal(preview(item).files[0].additions, 1)
  }
})

for (const fixture of fixtures) {
  test(`${fixture.agent}: structured history pairs actual calls and results`, () => {
    const items = history(fixture.agent, fixture.rows, (s) => s.trim())
    assert.deepEqual(items, history(fixture.agent, fixture.rows, (s) => s.trim()))
    assert.deepEqual(items.filter((i) => i.kind === 'message').map((i) => i.text), ['Fix tests', '**Done**'])
    const call = items.find((i) => i.id === fixture.tool)
    assert.equal(call.kind, 'command')
    assert.equal(call.command.display_command, 'pytest -q')
    assert.equal(call.status, 'failed')
    assert.equal(items.filter((i) => i.kind === 'command').length, 1)
    assert.match(call.output, /FAILED/)
    if (fixture.patch) {
      const item = items.find((i) => i.id === fixture.patch)
      assert.equal(item.files[0].additions, 1)
      assert.equal(item.files[0].deletions, 1)
      assert.equal(preview(item).files[0].diff, undefined)
    }
  })
}

test('pages reject stale, malformed and negative cursors, and bound large output', () => {
  const values = ['a', 'b', 'c']
  const first = page(values, { limit: 2 })
  assert.deepEqual(page(values, { cursor: first.next_cursor }).data, ['c'])
  const tail = page(values, { tail: true, limit: 2 })
  assert.deepEqual(tail.data, ['b', 'c'])
  assert.deepEqual(page(values, { tail: true, cursor: tail.next_cursor }).data, ['a'])
  assert.throws(() => page([...values, 'd'], { cursor: first.next_cursor }), (e) => e.code === 'stale_cursor')
  for (const cursor of ['?', Buffer.from('[]').toString('base64url'), Buffer.from('{"offset":-1}').toString('base64url')]) {
    assert.throws(() => page(values, { cursor }), (e) => e.code === 'invalid_cursor')
  }
  assert.equal(page('x'.repeat(100000), { limit: 999999 }).data.length, 32768)
})

test('rootless scopes have directory boundaries; deleted patch counts stay unknown', () => {
  assert.equal(sessionMetadata({ workspace: '/home/Documents/nanoMuse/Chats/a' }, '/home').scope, 'chats')
  assert.equal(sessionMetadata({ workspace: '/home/Documents/nanoMuse/Chats-extra' }, '/home').scope, 'projects')
  assert.equal(patchFiles('*** Begin Patch\n*** Delete File: a.py\n*** End Patch')[0].deletions, undefined)
})

test('live revisions replace an item and read-only detail stays within an owned run', async () => {
  const timeline = new Timeline()
  for (const type of ['item.started', 'item.updated', 'item.completed']) {
    timeline.feed('codex', { type, item: { id: 'c1', type: 'command_execution', command: 'pwd', aggregated_output: '/workspace', exit_code: 0 } })
  }
  assert.equal(timeline.values().length, 1)
  assert.equal(timeline.values()[0].status, 'completed')
  const { Run } = await import('../lib/coding-runner.js')
  const run = new Run('r1', 'codex', 's1', '/workspace', 'test')
  run.timeline.feed('codex', fixtures[0].rows[3])
  const service = new CodingService({ hub: { devices: [] } })
  service.runs.set(run.id, run)
  const args = { agent: 'codex', session_id: 's1', run_id: 'r1', diff_reference: 'p1:0' }
  assert.equal((await service.handle('coding.diff', args)).data, '@@\n-old\n+new')
  await assert.rejects(service.handle('coding.diff', { ...args, session_id: 'other' }), (e) => e.code === 'no_session')
})

test('duplicate sends share their in-flight request and reject different prompts', async () => {
  const service = new CodingService({ hub: { devices: [] } })
  let count = 0
  service.start = async () => {
    count += 1
    await new Promise((resolve) => setTimeout(resolve, 10))
    return { id: 'r1', status: 'done' }
  }
  const results = await Promise.all([
    service.send('codex', 'test', '', '', false, 'request-1'),
    service.send('codex', 'test', '', '', false, 'request-1'),
  ])
  assert.equal(results[0].id, results[1].id)
  assert.equal(count, 1)
  await assert.rejects(service.send('codex', 'other', '', '', false, 'request-1'), (e) => e.code === 'request_conflict')
})
