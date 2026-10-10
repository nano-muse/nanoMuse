// The host's reading of the hands: a `computer_act` call as the capsule's words and the
// trajectory's marks need it, and the first line of what `computer_screen` says.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { AskDesk, screenHead, stageAction } from '../lib/cloud.js'

test('stageAction keeps the kind, the words and the point', () => {
  const a = stageAction({ action: 'click', x: 120.5, y: '300', label: '  Save\n  file ' })
  assert.equal(a.kind, 'click')
  assert.equal(a.label, 'Save file')
  assert.equal(a.x, 120.5)
  assert.equal(a.y, 300)
  assert.ok(a.at > 0)
  const k = stageAction({ action: 'key', keys: ['ctrl', 's'] })
  assert.equal(k.text, 'ctrl+s')
  assert.equal(k.x, -1)
  const o = stageAction({ action: 'open_app', app: 'Safari' })
  assert.equal(o.text, 'Safari')
  const t = stageAction({ action: 'type', text: 'hello '.repeat(40) })
  assert.equal(t.text.length, 80)
  assert.equal(stageAction(undefined).kind, 'act')
})

test('screenHead reads the window in front and the size', () => {
  assert.deepEqual(screenHead('Safari — Apple · 2560×1600 · keyboard hidden\nmore words'), { title: 'Safari — Apple', width: 2560, height: 1600, mode: 'screen' })
  assert.deepEqual(screenHead('\n  phone · home · 1080x2400 · keyboard shown'), { title: 'phone', width: 1080, height: 2400, mode: 'screen' })
  assert.deepEqual(screenHead('Numbers — Budget · 1440×900 · window'), { title: 'Numbers — Budget', width: 1440, height: 900, mode: 'window' })
  assert.deepEqual(screenHead(''), { title: '', width: 0, height: 0, mode: 'screen' })
  // `computer_act` answers "Done. Screen now:" first — the head is the line with the size, not the first line
  const act = 'Done. Screen now:\n\n计算器 (Gnome-calculator) · 1596×1204 · keyboard hidden\nCoordinates: pixels of this 1596×1204 picture, (0,0) top-left.'
  assert.deepEqual(screenHead(act), { title: '计算器 (Gnome-calculator)', width: 1596, height: 1204, mode: 'screen' })
  assert.deepEqual(screenHead('Done. Screen now:\n\nnothing with a size here'), { title: '', width: 0, height: 0, mode: 'screen' })
})

test('a grant 0.1.37 wrote for the mis-read head is dropped', async () => {
  const { MISREAD_GRANT } = await import('../lib/cloud.js')
  assert.equal(MISREAD_GRANT.test('computer_app:Done. Screen now:'), true)
  assert.equal(MISREAD_GRANT.test('computer_app:Done. Screen now'), true)
  assert.equal(MISREAD_GRANT.test('computer_app:计算器 (Gnome-calculator)'), false)
  assert.equal(MISREAD_GRANT.test('computer_app:Safari'), false)
})

test('a hands refusal is recognised and confirmed with the ticket the runtime checks', async () => {
  const { confirmTicket, confirmationOf, refusalOf } = await import('../lib/cloud.js')
  const refusal = { isError: true, error: { message: 'x' }, content: [{ type: 'text', text: 'Not done — press enter: Enter sends what is typed. The person has to agree to this step on their permission card first; the host asks them.' }] }
  assert.equal(refusalOf(refusal), 'press enter: Enter sends what is typed. The person has to agree to this step on their permission card first; the host asks them.')
  // since 1.0 the runtime writes the same refusal with a colon (its sentences carry no
  // dashes); the permission card has to come up for it just the same
  const todays = { isError: true, error: { message: 'x' }, content: [{ type: 'text', text: 'Not done: computer_act(action=key, keys=[enter]): Enter sends what is typed. The person has to agree to this step on their permission card first; the host asks them.' }] }
  assert.equal(refusalOf(todays), 'computer_act(action=key, keys=[enter]): Enter sends what is typed. The person has to agree to this step on their permission card first; the host asks them.')
  assert.equal(refusalOf({ isError: true, error: { message: 'timeout' }, content: [{ type: 'text', text: 'timeout' }] }), undefined)
  // the model's own word is a confirmation we recognise but never make; the ticket is bound to the arguments
  assert.equal(confirmationOf({ action: 'key', confirmed: true }), true)
  assert.equal(confirmationOf({ action: 'key' }), undefined)
  const enter = { action: 'key', keys: ['enter'] }
  const t = confirmTicket('s3cret', enter)
  assert.match(t, /^[0-9a-f]{32}$/)
  assert.equal(confirmTicket('s3cret', { keys: ['enter'], action: 'key', confirmed: 'junk' }), t)
  assert.notEqual(confirmTicket('s3cret', { action: 'type', text: 'hi', submit: true }), t)
  assert.notEqual(confirmTicket('other', enter), t)
  // parity with nanomuse/bridge/mcp_server.py: the same bytes, the same digest
  assert.equal(confirmTicket('s3cret', { action: 'type', text: '你好 "world"', submit: true, keys: ['enter'], n: 1.5, nested: { b: 2, a: [1, null] } }), 'a0304fd4d602086fbac512191ed08838')
})

test('a question from another device waits on this screen for once, always, no — or times out', async () => {
  let changes = 0
  const desk = new AskDesk(() => changes++)
  const phone = { id: 'phone-1', name: 'Pixel', kind: 'phone' }
  const p1 = desk.ask(phone, 'shell', 'ls -la')
  assert.equal(desk.list.length, 1)
  assert.equal(desk.list[0].from, 'Pixel')
  assert.equal(desk.list[0].action, 'shell')
  assert.equal(desk.list[0].text, 'ls -la')
  assert.equal(desk.answer('nope', 'once'), false)
  assert.equal(desk.answer(desk.list[0].id, 'once'), true)
  assert.equal(await p1, 'once')
  assert.equal(desk.list.length, 0)
  const p2 = desk.ask(phone, 'task', 'tidy the desktop')
  desk.answer(desk.list[0].id, 'always')
  assert.equal(await p2, 'always')
  const p3 = desk.ask({ id: 'x', name: '', kind: 'computer' }, 'screen', '', 30)
  assert.equal(desk.list[0].from, 'a device')
  assert.equal(await p3, 'timeout')
  assert.equal(desk.list.length, 0)
  assert.equal(changes, 6)
})
