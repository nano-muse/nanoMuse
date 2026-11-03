// A pipe delivers whatever bytes have arrived: a multi-byte character straddling
// two reads must still arrive whole in its line, the way a decoded stream would.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { LineQueue } from '../lib/coding-runner.js'

test('a multi-byte character straddling two pipe reads arrives whole', async () => {
  const q = new LineQueue()
  const text = '{"type":"message","text":"你好，世界"}'
  const bytes = Buffer.from(text + '\n', 'utf8')
  const inside = text.indexOf('你')
  const split = Buffer.byteLength(text.slice(0, inside), 'utf8') + 1 // one byte into it
  q.push(bytes.subarray(0, split))
  q.push(bytes.subarray(split))
  const line = await q.next()
  assert.equal(line, text)
})

test('lines split across reads and a final line without a newline', async () => {
  const q = new LineQueue()
  q.push(Buffer.from('first half', 'utf8'))
  q.push(Buffer.from('-second\nthird', 'utf8'))
  q.end()
  assert.equal(await q.next(), 'first half-second')
  assert.equal(await q.next(), 'third')
  assert.equal(await q.next(), null)
})
