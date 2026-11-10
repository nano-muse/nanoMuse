import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { DeviceConversations } from '../lib/device-conversations.js'
import { HubError } from '../lib/hub.js'
import { PersistentTaskEndpoint } from '../lib/persistent-task-endpoint.js'
import { PersistentTurns } from '../lib/persistent-turns.js'

test('an ambiguous send is saved once and a reopened chat only queries the target', async () => {
  let rows = []
  const calls = []
  let savedAtDispatch
  const device = { id: 'phone-a', online: true, actions: ['task', 'task.status'], name: 'Phone' }
  const service = () => new DeviceConversations(
    () => rows, async (next) => { rows = structuredClone(next) }, () => [device],
    async (to, action, args) => {
      calls.push({ to, action, args })
      if (action === 'task') {
        savedAtDispatch = rows[0].turns[0]?.id
        throw new HubError('disconnected', 'the connection went away')
      }
      assert.equal(action, 'task.status')
      return { state: 'completed', text: 'reply from the target' }
    },
  )
  const chat = await service().create(device.id)
  const pending = await service().send(chat.id, 'do this once')
  assert.equal(pending.turns[0].state, 'unknown')
  await assert.rejects(service().send(chat.id, 'another prompt'), { code: 'busy' })
  device.name = 'Renamed phone'
  const recovered = await service().refresh(chat.id)
  assert.equal(recovered.chat.turns[0].answer, 'reply from the target')
  assert.equal(recovered.chat.turns.length, 1)
  await service().refresh(chat.id)
  assert.deepEqual(calls.map(({ action }) => action), ['task', 'task.status'])
  assert.equal(savedAtDispatch, calls[0].args.turn_id)
  assert.ok(calls.every(({ to, args }) => to === device.id && args.conversation === chat.id))
})

test('a qualified mention is a one-off, and follow-ups retain the bound device', async () => {
  let rows = []
  const devices = ['desk-a', 'desk-b', 'desk-c'].map((id) => ({
    id, online: true, actions: ['task', 'task.status'], name: id === 'desk-a' ? 'Main' : 'Other desk',
  }))
  const calls = []
  const service = new DeviceConversations(() => rows, async (next) => { rows = next }, () => devices,
    async (to, _action, args) => {
      calls.push({ to, args })
      return { state: 'completed', text: 'done' }
    })
  const chat = await service.create('desk-a')
  await assert.rejects(service.send(chat.id, '@Other desk check'), { code: 'usage' })
  await service.send(chat.id, '@Other desk [desk-b] check')
  await service.send(chat.id, 'first bound turn')
  await service.send(chat.id, 'bound follow-up')
  assert.deepEqual(calls.map(({ to }) => to), ['desk-b', 'desk-a', 'desk-a'])
  assert.notEqual(calls[0].args.conversation, chat.id)
  assert.equal(calls[0].args.text, 'check')
  assert.equal(calls[1].args.conversation, chat.id)
  assert.equal(calls[2].args.conversation, chat.id)
  assert.deepEqual(calls.map(({ args }) => args.new_conversation), [true, true, false])
})

test('offline or unsupported targets cannot reserve or dispatch a turn', async () => {
  let rows = []
  const device = { id: 'desk-a', online: true, actions: ['task', 'task.status'], name: 'Desk' }
  const service = new DeviceConversations(() => rows, async (next) => { rows = next }, () => [device],
    async () => assert.fail('the target cannot be called'))
  const chat = await service.create(device.id)
  device.online = false
  await assert.rejects(service.send(chat.id, 'keep this draft'), { code: 'device_offline' })
  device.online = true
  device.actions = ['task']
  await assert.rejects(service.send(chat.id, 'keep this draft'), { code: 'unknown_action' })
  assert.equal(service.list()[0].turns.length, 0)
})

test('caller and executor recover a turn across a dropped result and two store reopens', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'nm-device-recovery-'))
  t.after(() => rm(dir, { recursive: true, force: true }))
  const file = join(dir, 'target.json')
  let endpoint = new PersistentTaskEndpoint(await PersistentTurns.open(file))
  let rows = []
  let runs = 0
  let execution
  let finish
  const answer = new Promise((resolve) => { finish = resolve })
  const device = { id: 'target', online: true, actions: ['task', 'task.status'], name: 'Desk' }
  const reopen = () => new DeviceConversations(() => rows, async (next) => { rows = structuredClone(next) },
    () => [device], async (_to, action, args) => {
      const owner = { account: 'account-a', caller: 'initiator', conversation: args.conversation }
      if (action === 'task.status') return endpoint.status(owner, args.turn_id)
      let accepted
      const ack = new Promise((resolve) => { accepted = resolve })
      execution = endpoint.run(owner, args.turn_id, { id: 'socket-call', from: { id: owner.caller }, event: accepted },
        async () => 'saved-session', async () => { runs++; return answer })
      await ack
      throw new HubError('disconnected', 'the transport lost the call')
    })
  const chat = await reopen().create(device.id)
  assert.equal((await reopen().send(chat.id, 'run exactly once')).turns[0].state, 'unknown')
  assert.equal((await reopen().refresh(chat.id)).chat.turns[0].state, 'accepted')
  finish({ text: 'completed on the execution device' })
  await execution
  endpoint = new PersistentTaskEndpoint(await PersistentTurns.open(file))
  const restored = (await reopen().refresh(chat.id)).chat
  assert.equal(restored.turns.length, 1)
  assert.equal(restored.turns[0].answer, 'completed on the execution device')
  assert.equal(runs, 1)
})

for (const rejection of ['no_model', 'not_ready', 'denied', 'not_allowed', 'busy', 'usage']) {
  test(`a first turn rejected with ${rejection} can start after correction`, async (t) => {
    const dir = await mkdtemp(join(tmpdir(), 'nm-device-rejection-'))
    t.after(() => rm(dir, { recursive: true, force: true }))
    const endpoint = new PersistentTaskEndpoint(await PersistentTurns.open(join(dir, 'turns.json')))
    let rows = [], configured = false
    const calls = []
    const reopen = () => new DeviceConversations(() => rows, async (next) => { rows = structuredClone(next) },
      () => [{ id: 'target', name: 'Desk', online: true, actions: ['task.status'] }],
      async (device, action, args) => {
        calls.push(args)
        return endpoint.run({ account: 'account-a', caller: 'caller-a', conversation: args.conversation }, args.turn_id, { id: `c${calls.length}`, from: { id: 'caller-a' }, event() {} },
          async () => {
            if (!args.new_conversation) throw new HubError('context_lost', 'no context was created')
            if (!configured) throw new HubError(rejection, 'correct the setup first')
            return 'session-a'
          }, async () => ({ text: 'ready' }))
      })
    const chat = await reopen().create('target')
    assert.equal((await reopen().send(chat.id, 'first')).turns[0].error, rejection)
    configured = true
    const retry = await reopen().send(chat.id, 'try again')
    assert.equal(retry.turns[1].state, 'completed')
    assert.equal(retry.turns[1].answer, 'ready')
    assert.deepEqual(calls.map((args) => args.new_conversation), [true, true])
    assert.notEqual(calls[0].turn_id, calls[1].turn_id)
    assert.equal(calls[0].conversation, calls[1].conversation)
  })
}

for (const result of [
  { state: 'failed', error: 'no_model' },
  { state: 'failed', error: 'denied' },
  { state: 'interrupted' },
  { state: 'cancelled' },
]) {
  test(`an accepted ${result.state}/${result.error ?? ''} turn never allows a fresh context`, async () => {
    let rows = []
    const calls = []
    const service = new DeviceConversations(() => rows, async (next) => { rows = next },
      () => [{ id: 'target', name: 'Desk', online: true, actions: ['task.status'] }],
      async (_device, _action, args) => {
        calls.push(args)
        if (calls.length === 1) return result
        throw new HubError('context_lost', 'the saved context disappeared')
      })
    const chat = await service.create('target')
    await service.send(chat.id, 'first')
    assert.equal((await service.send(chat.id, 'follow up')).turns[1].error, 'context_lost')
    assert.deepEqual(calls.map((args) => args.new_conversation), [true, false])
    await assert.rejects(service.send(chat.id, 'another follow-up'), { code: 'context_lost' })
    assert.equal(calls.length, 2)
  })
}
