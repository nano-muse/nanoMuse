// Scheduled tasks are the person's, not one chat's: `schedule_list_all` reads every chat's
// active tasks, this chat's first, with the chat each runs in.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { scheduleRows } from '../lib/rooms-tools.js'

const entry = (id, sessionId, extra = {}) => ({ id, sessionId, status: 'active', kind: 'cron', title: `Task ${id}`, scheduledAt: '2026-11-12T02:00:00.000Z', expression: '*/15 10-11 * * *', timeZone: 'Asia/Shanghai', ...extra })

test('every chat’s active tasks, this chat’s first, with their chat', () => {
  const rows = scheduleRows(
    [entry('a', 'session-other'), entry('b', 'session-here'), entry('c', 'session-other', { status: 'inactive' })],
    'session-here',
    new Map([['session-other', 'Reminders'], ['session-here', 'Today']]),
  )
  assert.deepEqual(rows.map((r) => r.id), ['b', 'a'])
  assert.deepEqual(rows[1], { id: 'a', title: 'Task a', rule: 'cron */15 10-11 * * *', time_zone: 'Asia/Shanghai', next_run: '2026-11-12T02:00:00.000Z', chat_id: 'session-other', chat_title: 'Reminders', this_chat: false })
  assert.equal(rows[0].this_chat, true)
})

test('a chat whose title cannot be read still lists its tasks', () => {
  const rows = scheduleRows([entry('a', 'session-x', { kind: 'daily', time: '09:00:00.000', expression: undefined })], 'session-here', new Map())
  assert.equal(rows[0].chat_title, '')
  assert.equal(rows[0].rule, 'daily@09:00')
})
