import assert from 'node:assert/strict'
import { test } from 'node:test'
import { DeviceChatDrafts } from '../lib/device-chat-drafts.js'

test('a send acknowledgement preserves text edited while its request was pending', async () => {
  const writes = []
  const drafts = new DeviceChatDrafts(async (id, text) => { writes.push({ id, text }) })
  drafts.set('chat-a', 'first message')
  const sent = drafts.get('chat-a')
  await drafts.save('chat-a', sent)
  drafts.set('chat-a', 'next message')
  await drafts.save('chat-a', drafts.get('chat-a'))
  assert.equal(drafts.clearSent('chat-a', sent), null)
  assert.equal(drafts.get('chat-a'), 'next message')
  assert.deepEqual(writes.map((row) => row.text), ['first message', 'next message'])
})

test('an unchanged sent draft clears without touching another conversation', () => {
  const drafts = new DeviceChatDrafts(async () => undefined)
  drafts.set('chat-a', 'sent')
  drafts.set('chat-b', 'still writing')
  assert.deepEqual(drafts.clearSent('chat-a', 'sent'), { 'chat-a': '', 'chat-b': 'still writing' })
  assert.equal(drafts.get('chat-b'), 'still writing')
})

test('loading saved drafts does not overwrite text already edited in the mounted panel', () => {
  const drafts = new DeviceChatDrafts(async () => undefined)
  drafts.set('chat-a', 'typing while the list loads')
  assert.deepEqual(drafts.hydrate([{ id: 'chat-a', draft: 'old saved text' }, { id: 'chat-b', draft: 'saved elsewhere' }]), {
    'chat-a': 'typing while the list loads', 'chat-b': 'saved elsewhere',
  })
})

test('automatic and send-time saves dispatch in editor order', async () => {
  let finishFirst
  const firstResponse = new Promise((resolve) => { finishFirst = resolve })
  const calls = []
  const drafts = new DeviceChatDrafts(async (_id, text) => {
    calls.push(text)
    if (text === 'older') await firstResponse
  })
  const first = drafts.save('chat-a', 'older')
  const second = drafts.save('chat-a', 'newer')
  await new Promise(setImmediate)
  assert.deepEqual(calls, ['older'])
  finishFirst()
  await Promise.all([first, second])
  assert.deepEqual(calls, ['older', 'newer'])
})

test('a failed write keeps the editor text and does not poison the next save', async () => {
  let failed = false
  const drafts = new DeviceChatDrafts(async () => {
    if (!failed) { failed = true; throw new Error('local persistence unavailable') }
  })
  drafts.set('chat-a', 'unsaved text')
  await assert.rejects(drafts.save('chat-a', drafts.get('chat-a')), /unavailable/)
  assert.equal(drafts.get('chat-a'), 'unsaved text')
  await drafts.save('chat-a', drafts.get('chat-a'))
  assert.equal(drafts.get('chat-a'), 'unsaved text')
})
