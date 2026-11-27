import assert from 'node:assert/strict'
import { test } from 'node:test'
import { canStartBoundDeviceChat, deviceChatAccent, deviceChatLabel } from '../lib/device-chat.js'

test('device labels disambiguate duplicate names with a stable identity', () => {
  const first = { id: 'desk-a1b2c3', name: 'Office', kind: 'computer', online: true, actions: ['task.status'] }
  const second = { ...first, id: 'desk-d4e5f6' }
  assert.notEqual(deviceChatLabel(first), deviceChatLabel(second))
  assert.match(deviceChatLabel(first), /a1b2c3$/)
})

test('persistent chat availability requires an online task.status destination', () => {
  assert.equal(canStartBoundDeviceChat({ id: 'desk', name: 'Desk', kind: 'computer', online: true, actions: ['task', 'task.status'] }), true)
  assert.equal(canStartBoundDeviceChat({ id: 'desk', name: 'Desk', kind: 'computer', online: false, actions: ['task.status'] }), false)
  assert.equal(canStartBoundDeviceChat({ id: 'desk', name: 'Desk', kind: 'computer', online: true, actions: ['task'] }), false)
})

test('device color is deterministic from stable identity', () => {
  assert.equal(deviceChatAccent('desk-a'), deviceChatAccent('desk-a'))
  assert.notEqual(deviceChatAccent('desk-a'), deviceChatAccent('desk-b'))
})
