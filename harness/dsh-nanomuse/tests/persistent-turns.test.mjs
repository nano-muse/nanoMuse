import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { PersistentTurns } from '../lib/persistent-turns.js'
import { PersistentTaskEndpoint } from '../lib/persistent-task-endpoint.js'

const contract = JSON.parse(await readFile(new URL(
  '../../../android/src/android/app/src/test/resources/hub-turn-contract.json', import.meta.url,
), 'utf8'))
const { conversation, turn, other } = contract
const owner = { account: 'account-a', caller: 'phone-a', conversation }

async function fixture(t) {
  const dir = await mkdtemp(join(tmpdir(), 'nm-turns-'))
  t.after(() => rm(dir, { recursive: true, force: true }))
  const file = join(dir, 'turns.json')
  return { file, store: await PersistentTurns.open(file) }
}

test('acceptance is durable, and reconnect recovers a completed answer', async (t) => {
  const { file, store } = await fixture(t)
  await store.accept(owner, turn, async () => 'session-a')
  const recovered = await PersistentTurns.open(file)
  assert.deepEqual(recovered.status(owner, turn), contract.interrupted)
  await store.finish(owner, turn, contract.completed)
  assert.deepEqual((await PersistentTurns.open(file)).status(owner, turn), contract.completed)
})

test('concurrent duplicate acceptance creates only one session and one run', async (t) => {
  const { store } = await fixture(t)
  let created = 0
  const create = async () => { created++; return 'session-a' }
  const result = await Promise.all([store.accept(owner, turn, create), store.accept(owner, turn, create)])
  assert.equal(created, 1)
  assert.equal(result.filter((entry) => entry.accepted).length, 1)
  await assert.rejects(store.accept(owner, other, create), { code: 'busy' })
})

test('status and context are scoped to the authenticated caller and account', async (t) => {
  const { store } = await fixture(t)
  await store.accept(owner, turn, async () => 'session-a')
  assert.equal(store.status({ ...owner, caller: 'phone-b' }, turn), undefined)
  assert.equal(store.status({ ...owner, account: 'account-b' }, turn), undefined)
  await store.finish(owner, turn, { state: 'cancelled' })
  const next = await store.accept(owner, other, async () => assert.fail('context must be reused'))
  assert.equal(next.session, 'session-a')
})

test('failed acceptance cannot be acknowledged as durable', async (t) => {
  const { file, store } = await fixture(t)
  await rm(file, { force: true })
  const { mkdir } = await import('node:fs/promises')
  await mkdir(file)
  await assert.rejects(store.accept(owner, turn, async () => 'session-a'))
  assert.equal(store.status(owner, turn), undefined)
})

test('a dropped caller can recover the answer without replaying the executor', async (t) => {
  const { file, store } = await fixture(t)
  const endpoint = new PersistentTaskEndpoint(store)
  let runs = 0
  let complete
  const answer = new Promise((resolve) => { complete = resolve })
  let acknowledge
  const accepted = new Promise((resolve) => { acknowledge = resolve })
  const call = { id: 'original', from: { id: owner.caller }, event: acknowledge }
  const send = () => endpoint.run(owner, turn, call, async () => 'session-a', async () => {
    runs++
    return answer
  })
  const pending = send()
  assert.deepEqual(await accepted, { stage: 'accepted', turn_id: turn })
  assert.equal((await PersistentTurns.open(file)).status(owner, turn).state, 'interrupted')
  assert.equal((await send()).state, 'accepted')
  complete({ text: 'finished after disconnect' })
  await pending
  assert.equal((await send()).text, 'finished after disconnect')
  assert.equal(runs, 1)
})

test('status returns live progress and only unanswered approvals', async (t) => {
  const { store } = await fixture(t)
  const endpoint = new PersistentTaskEndpoint(store)
  const call = { id: 'original', from: { id: owner.caller }, event: () => {} }
  await endpoint.run(owner, turn, call, async () => 'session-a', async (_session, emit) => {
    emit({ stage: 'text', text: 'first', partial: true })
    emit({ stage: 'text', text: 'first and second', partial: true })
    emit({ stage: 'approval', approval_id: 'answered', timeout: 30 })
    emit({ stage: 'approval_result', approval_id: 'answered', status: 'approved' })
    emit({ stage: 'approval', approval_id: 'pending', timeout: 30 })
    const status = endpoint.status(owner, turn)
    assert.equal(status.state, 'accepted')
    assert.deepEqual(status.events.map((event) => event.text ?? event.approval_id), ['first and second', 'pending'])
    return { text: 'done' }
  })
  assert.deepEqual(endpoint.status(owner, turn), { state: 'completed', text: 'done' })
})
