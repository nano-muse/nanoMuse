// The star nudges' one gate (C1): the policy's switches, the thresholds, the cooldown, the
// lifetime cap, and what starring does — plus the policy and ledger read from the relay and the file.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { routineDue } from '../lib/rooms.js'
import { askKey, dayKey, DEFAULT_NUDGES, dueAsk, LEDGER_EMPTY, mergeNudges, readLedger, readNudges, recordAsk, recordDay, recordStarred, recordTask, STAR_TEXT_MAX, starSentence, starText } from '../lib/nudges.js'

const DAY = 86_400_000
const T0 = Date.UTC(2026, 9, 5, 12)
const empty = () => ({ ...LEDGER_EMPTY, days: [], asks: [] })

test('the defaults are the shared contract', () => {
  assert.deepEqual(DEFAULT_NUDGES, {
    version: 1,
    star: {
      enabled: true,
      url: 'https://github.com/nano-muse/nanoMuse',
      moments: { signed_in: true, tasks: [3, 10, 30], new_look: true, exhausted: true, days_used: [7, 30], goal_done: true },
      cooldown_days: 7,
      max_asks: 4,
      text: '',
      text_zh: '',
    },
  })
})

test('the relay may say the card\'s sentence: trimmed, at most 200 characters, else the app\'s own', () => {
  assert.equal(STAR_TEXT_MAX, 200)
  // read: trimmed; over the cap dropped, not cut; anything that is not a string is nothing
  assert.equal(starSentence('  A star helps.  '), 'A star helps.')
  assert.equal(starSentence('x'.repeat(200)), 'x'.repeat(200))
  assert.equal(starSentence('x'.repeat(201)), '')
  assert.equal(starSentence(`${' '.repeat(5)}${'y'.repeat(200)}${' '.repeat(5)}`), 'y'.repeat(200), 'the cap is measured after trimming')
  assert.equal(starSentence(''), '')
  assert.equal(starSentence(42), '')
  assert.equal(starSentence(null), '')
  // merged: a policy without the fields keeps the empty defaults; one with them keeps them; a bad one is dropped
  assert.equal(mergeNudges({ star: {} }).star.text, '')
  const p = mergeNudges({ star: { text: ' Thanks for running it. ', text_zh: '谢谢你用它。', max_asks: 2 } })
  assert.equal(p.star.text, 'Thanks for running it.')
  assert.equal(p.star.text_zh, '谢谢你用它。')
  assert.equal(p.star.max_asks, 2)
  assert.equal(mergeNudges({ star: { text: 'z'.repeat(300), text_zh: '好'.repeat(201) } }).star.text, '')
  assert.equal(mergeNudges({ star: { text: 'z'.repeat(300), text_zh: '好'.repeat(201) } }).star.text_zh, '')
  // /v1/me carries it under `nudges` too
  assert.equal(readNudges({ nudges: { star: { text_zh: '一颗 Star。' } } }).star.text_zh, '一颗 Star。')
  // chosen: a Chinese UI takes text_zh, else text, else the app's own; an English UI never takes text_zh
  const own = 'the app’s own sentence'
  assert.equal(starText(DEFAULT_NUDGES, false, own), own)
  assert.equal(starText(DEFAULT_NUDGES, true, own), own)
  assert.equal(starText(p, false, own), 'Thanks for running it.')
  assert.equal(starText(p, true, own), '谢谢你用它。')
  const enOnly = mergeNudges({ star: { text: 'English only.' } })
  assert.equal(starText(enOnly, true, own), 'English only.')
  assert.equal(starText(enOnly, false, own), 'English only.')
  const zhOnly = mergeNudges({ star: { text_zh: '只有中文。' } })
  assert.equal(starText(zhOnly, true, own), '只有中文。')
  assert.equal(starText(zhOnly, false, own), own)
})

test('a relay policy fills the gaps from the defaults and cannot break the shape', () => {
  const p = mergeNudges({ version: 2, star: { enabled: false, moments: { tasks: [5, 'x', 5, 1], goal_done: 0 }, cooldown_days: -1, url: 'http://evil' } })
  assert.equal(p.version, 2)
  assert.equal(p.star.enabled, false)
  assert.deepEqual(p.star.moments.tasks, [1, 5])
  assert.equal(p.star.moments.goal_done, true)
  assert.equal(p.star.cooldown_days, 7)
  assert.equal(p.star.url, DEFAULT_NUDGES.star.url)
  assert.deepEqual(mergeNudges(null), DEFAULT_NUDGES)
  // /v1/me carries it under `nudges`; a body that is neither is not a policy
  assert.equal(readNudges({ account: {} }), null)
  assert.equal(readNudges({ nudges: { star: { max_asks: 1 } } }).star.max_asks, 1)
  assert.equal(readNudges({ star: {} }).star.max_asks, 4)
})

test('tasks ask at each threshold once; the counter persists in the ledger', () => {
  let ledger = empty()
  const asks = []
  let now = T0
  for (let i = 0; i < 12; i++) {
    ledger = recordTask(ledger)
    const ask = dueAsk(DEFAULT_NUDGES, ledger, 'tasks', ledger.tasks, now)
    if (ask) { asks.push(ask); ledger = recordAsk(ledger, ask) }
    now += 2 * DAY
  }
  assert.equal(ledger.tasks, 12)
  assert.deepEqual(asks.map((a) => a.n), [3, 10])
  // the third threshold would be the 30th; asking for 3 again is refused
  assert.equal(dueAsk(DEFAULT_NUDGES, ledger, 'tasks', 3, now + 30 * DAY), null)
  assert.equal(dueAsk(DEFAULT_NUDGES, ledger, 'tasks', 30, now + 30 * DAY)?.key, 'tasks:30')
  // a number off the list never asks
  assert.equal(dueAsk(DEFAULT_NUDGES, empty(), 'tasks', 4, T0), null)
  assert.equal(dueAsk(DEFAULT_NUDGES, empty(), 'tasks', undefined, T0), null)
})

test('the cooldown holds between any two asks, whatever their moments', () => {
  let ledger = empty()
  const first = dueAsk(DEFAULT_NUDGES, ledger, 'signed_in', undefined, T0)
  assert.ok(first)
  ledger = recordAsk(ledger, first)
  assert.equal(dueAsk(DEFAULT_NUDGES, ledger, 'new_look', undefined, T0 + 3 * DAY), null)
  assert.equal(dueAsk(DEFAULT_NUDGES, ledger, 'goal_done', undefined, T0 + 6.9 * DAY), null)
  assert.ok(dueAsk(DEFAULT_NUDGES, ledger, 'new_look', undefined, T0 + 7 * DAY))
  // a second signed_in never
  assert.equal(dueAsk(DEFAULT_NUDGES, ledger, 'signed_in', undefined, T0 + 30 * DAY), null)
})

test('max_asks is a lifetime cap and "Not now" counts', () => {
  let ledger = empty()
  let now = T0
  for (const moment of ['signed_in', 'new_look', 'goal_done', 'exhausted']) {
    const ask = dueAsk(DEFAULT_NUDGES, ledger, moment, undefined, now)
    assert.ok(ask, moment)
    ledger = recordAsk(ledger, ask) // shown, dismissed with "Not now" — still an ask
    now += 8 * DAY
  }
  assert.equal(ledger.asks.length, 4)
  ledger = recordTask(recordTask(recordTask(ledger)))
  assert.equal(dueAsk(DEFAULT_NUDGES, ledger, 'tasks', 3, now), null)
})

test('starring ends every ask; enabled:false asks nothing', () => {
  const starred = recordStarred(empty())
  assert.equal(dueAsk(DEFAULT_NUDGES, starred, 'signed_in', undefined, T0), null)
  // "I already starred" with no ask ever shown: no cooldown, every ask left, still nothing
  const generous = mergeNudges({ star: { cooldown_days: 0, max_asks: 50 } })
  for (const [moment, n] of [['signed_in'], ['tasks', 3], ['new_look'], ['exhausted'], ['days_used', 7], ['goal_done']]) {
    assert.equal(dueAsk(generous, starred, moment, n, T0 + 365 * DAY), null, moment)
  }
  assert.equal(recordStarred(starred), starred, 'saying it twice changes nothing')
  assert.equal(dueAsk(mergeNudges({ star: { enabled: false } }), empty(), 'signed_in', undefined, T0), null)
  // a moment switched off
  assert.equal(dueAsk(mergeNudges({ star: { moments: { new_look: false } } }), empty(), 'new_look', undefined, T0), null)
})

test('days of use count distinct local days and ask on the 7th and 30th', () => {
  let ledger = empty()
  let asked = []
  for (let d = 0; d < 31; d++) {
    const at = T0 + d * DAY
    const r1 = recordDay(ledger, at)
    const r2 = recordDay(r1.ledger, at + 3600_000) // the app opened twice the same day
    assert.equal(r1.newDay, true)
    assert.equal(r2.newDay, false)
    ledger = r2.ledger
    const ask = dueAsk(DEFAULT_NUDGES, ledger, 'days_used', ledger.days.length, at)
    if (ask) { asked.push(ask.n); ledger = recordAsk(ledger, ask) }
  }
  assert.equal(ledger.days.length, 31)
  assert.deepEqual(asked, [7, 30])
  assert.equal(dayKey(T0).length, 10)
  assert.equal(askKey('days_used', 7), 'days_used:7')
  assert.equal(askKey('signed_in'), 'signed_in')
})

test('the ledger is read tolerantly', () => {
  const l = readLedger({ tasks: 4.7, days: ['2026-10-01', 'nope', 7], asks: [{ moment: 'tasks', n: 3, key: 'tasks:3', at: 1 }, { moment: 'bogus', key: 'x', at: 1 }, null], starred: 'yes' })
  assert.equal(l.tasks, 4)
  assert.deepEqual(l.days, ['2026-10-01'])
  assert.equal(l.asks.length, 1)
  assert.equal(l.asks[0].n, 3)
  assert.equal(l.starred, false)
  assert.deepEqual(readLedger(undefined), LEDGER_EMPTY)
})

test('the feed routine is due once the hour has passed and the last batch predates it', () => {
  const now = new Date(2026, 9, 5, 9, 30).getTime()
  const slot = new Date(2026, 9, 5, 8, 0).getTime()
  assert.equal(routineDue('08:00', 0, now), true)
  assert.equal(routineDue('08:00', slot - 3600_000, now), true)
  assert.equal(routineDue('08:00', slot + 60_000, now), false)
  assert.equal(routineDue('10:00', 0, now), false)
})
