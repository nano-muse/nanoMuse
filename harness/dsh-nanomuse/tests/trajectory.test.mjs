// The trajectory of a hands run (src/trajectory.ts): how the frames the model saw, the
// actions it took and the words it said become steps, and the caps that keep it light.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { MAX_RUNS, MAX_STEPS, MAX_WORDS, REST_MS, SCREEN_RUN_IDLE_MS, ScreenRuns, Trajectory } from '../lib/trajectory.js'
import { stageAction } from '../lib/cloud.js'

const act = (kind, extra = {}) => ({ kind, label: '', text: '', x: -1, y: -1, x2: -1, y2: -1, dy: 0, at: 1, ...extra })
const png = (n = 3) => Buffer.alloc(n, 1)

/** A clock the test moves. */
function clock(start = 1_000_000) {
  let t = start
  const now = () => t
  now.tick = (ms) => { t += ms }
  return now
}

test('a run: the frame is a step, the action lands on it, the words said before go with it', () => {
  const now = clock()
  const tr = new Trajectory({ now })
  assert.equal(tr.view().runs.length, 0)
  // the model talks, then looks: no step yet (nothing to look back at), the words wait
  tr.said('s1', 'I will  open the\n settings.')
  tr.began('s1', 'c1')
  tr.acted('s1', 'c1', act('look'))
  assert.equal(tr.view().runs.length, 1)
  assert.equal(tr.view().runs[0].steps.length, 0)
  const seq1 = tr.frame(png(), 'image/png', { sessionId: 's1', width: 1600, height: 900, title: 'Desktop', callId: 'c1' })
  assert.equal(seq1, 1)
  assert.equal(tr.latestSeq, 1)
  // the click goes on that frame with the words from before
  tr.acted('s1', 'c2', act('click', { x: 100, y: 200, label: 'Settings' }))
  const run = tr.view('s1').runs[0]
  assert.equal(run.steps.length, 1)
  assert.equal(run.steps[0].i, 1)
  assert.equal(run.steps[0].seq, 1)
  assert.equal(run.steps[0].title, 'Desktop')
  assert.deepEqual([run.steps[0].width, run.steps[0].height], [1600, 900])
  assert.equal(run.steps[0].action.kind, 'click')
  assert.equal(run.steps[0].words, 'I will open the settings.')
  assert.equal(run.steps[0].callId, 'c2')
  assert.equal(run.firstCall, 'c1')
  assert.equal(run.lastCall, 'c2')
  assert.equal(run.endedAt, 0)
  assert.equal(tr.running('s1'), true)
  // the screen after the click: step 2, no action yet; the words are spent
  tr.frame(png(), 'image/png', { sessionId: 's1', callId: 'c2' })
  const run2 = tr.view('s1').runs[0]
  assert.equal(run2.steps.length, 2)
  assert.equal(run2.steps[1].action, null)
  assert.equal(run2.steps[1].words, '')
  // frames are served by seq; 0 is the newest
  assert.equal(tr.frameOf(1).seq, 1)
  assert.equal(tr.frameOf(0).seq, 2)
  assert.equal(tr.frameOf(99), undefined)
  // the turn ends: the run closes and stays
  tr.turnEnded('s1')
  assert.equal(tr.running('s1'), false)
  assert.ok(tr.view('s1').runs[0].endedAt > 0)
  assert.equal(tr.view('s1').runs.length, 1)
  assert.equal(tr.view('other').runs.length, 0)
})

test('the model acts before it looks: a step without a picture', () => {
  const tr = new Trajectory({ now: clock() })
  tr.began('s', 'c1')
  tr.acted('s', 'c1', act('type', { text: 'hello' }))
  const run = tr.view().runs[0]
  assert.equal(run.steps.length, 1)
  assert.equal(run.steps[0].seq, 0)
  assert.equal(run.steps[0].action.text, 'hello')
  // a second action with no new frame is a new frameless step; a look in between is skipped
  tr.acted('s', 'c2', act('look'))
  tr.acted('s', 'c3', act('key', { text: 'enter' }))
  assert.equal(tr.view().runs[0].steps.length, 2)
  assert.equal(tr.view().runs[0].steps[1].i, 2)
})

test('a run that only looked is forgotten when the turn ends; a run that acted stays', () => {
  const tr = new Trajectory({ now: clock() })
  tr.began('s', 'c1')
  tr.frame(png(), 'image/jpeg', { sessionId: 's', callId: 'c1' })
  tr.acted('s', 'c2', act('look'))
  assert.equal(tr.view().runs.length, 1)
  tr.turnEnded('s')
  assert.equal(tr.view().runs.length, 0)
  assert.equal(tr.frameOf(1), undefined, 'its picture went with it')
  tr.began('s', 'c3')
  tr.frame(png(), 'image/jpeg', { sessionId: 's', callId: 'c3' })
  tr.acted('s', 'c4', act('click', { x: 1, y: 1 }))
  tr.turnEnded('s')
  assert.equal(tr.view().runs.length, 1)
})

test('the caps: MAX_STEPS per run with dropped counted, MAX_RUNS in all, the rest opens a new run', () => {
  const now = clock()
  const tr = new Trajectory({ now })
  tr.began('s', 'c0')
  for (let i = 0; i < MAX_STEPS + 5; i += 1) {
    tr.frame(png(), 'image/jpeg', { sessionId: 's', callId: `c${i}` })
    tr.acted('s', `c${i + 1}`, act('click', { x: i, y: i }))
  }
  let run = tr.view().runs[0]
  assert.equal(run.steps.length, MAX_STEPS)
  assert.equal(run.dropped, 5)
  assert.equal(run.steps[0].i, 6, 'numbering counts the dropped ones')
  assert.equal(run.steps[MAX_STEPS - 1].i, MAX_STEPS + 5)
  assert.equal(tr.frameOf(1), undefined, 'a dropped step takes its picture with it')
  assert.ok(tr.frameOf(6))
  tr.turnEnded('s')
  // more runs than kept: the oldest goes
  for (let r = 0; r < MAX_RUNS + 1; r += 1) {
    tr.began('s', `r${r}`)
    tr.frame(png(), 'image/jpeg', { sessionId: 's', callId: `r${r}` })
    tr.acted('s', `r${r}x`, act('click', { x: 1, y: 1 }))
    tr.turnEnded('s')
  }
  assert.equal(tr.view().runs.length, MAX_RUNS)
  assert.equal(tr.view().runs[0].firstCall, 'r1', 'the first run and r0 went')
  // a long rest between two calls of one turn: a new run
  tr.began('t', 'a')
  tr.frame(png(), 'image/jpeg', { sessionId: 't', callId: 'a' })
  tr.acted('t', 'b', act('click', { x: 1, y: 1 }))
  now.tick(REST_MS + 1)
  tr.began('t', 'c')
  run = tr.view('t').runs
  assert.equal(run.length, 2)
  assert.ok(run[0].endedAt > 0)
  assert.equal(run[1].endedAt, 0)
})

test('the pictures together stay under the byte cap: the oldest go first, their steps keep their words', () => {
  const tr = new Trajectory({ now: clock(), maxFrameBytes: 10 })
  tr.said('s', 'first')
  tr.began('s', 'c1')
  tr.frame(png(4), 'image/jpeg', { sessionId: 's', callId: 'c1' })
  tr.acted('s', 'c2', act('click', { x: 1, y: 1 }))
  tr.said('s', 'second')
  tr.frame(png(4), 'image/jpeg', { sessionId: 's', callId: 'c2' })
  tr.acted('s', 'c3', act('click', { x: 2, y: 2 }))
  tr.frame(png(4), 'image/jpeg', { sessionId: 's', callId: 'c3' })
  const steps = tr.view().runs[0].steps
  assert.equal(steps.length, 3)
  assert.equal(steps[0].seq, 0, 'the oldest picture went')
  assert.equal(steps[0].words, 'first')
  assert.equal(steps[1].seq, 2)
  assert.equal(steps[2].seq, 3)
  assert.equal(tr.frameOf(1), undefined)
  assert.ok(tr.frameOf(2))
  // the newest picture is never evicted
  const one = new Trajectory({ now: clock(), maxFrameBytes: 1 })
  one.frame(png(4), 'image/jpeg', { sessionId: 's' })
  assert.ok(one.frameOf(0))
  assert.equal(one.view().runs[0].steps[0].seq, 1)
})

test('words are tidied and capped; clear forgets everything; the view carries no bytes', () => {
  const tr = new Trajectory({ now: clock() })
  tr.said('s', `${'x'.repeat(MAX_WORDS + 50)}`)
  tr.began('s', 'c1')
  tr.frame(png(), 'image/jpeg', { sessionId: 's', device: 'Pixel', callId: 'c1' })
  tr.acted('s', 'c2', act('click', { x: 1, y: 1 }))
  const run = tr.view().runs[0]
  assert.equal(run.steps[0].words.length, MAX_WORDS)
  assert.ok(run.steps[0].words.endsWith('…'))
  assert.equal(run.source, 'device')
  assert.equal(run.device, 'Pixel')
  assert.equal(JSON.stringify(tr.view()).includes('bytes'), false)
  const rev = tr.view().rev
  tr.clear()
  assert.equal(tr.view().runs.length, 0)
  assert.equal(tr.frameOf(0), undefined)
  assert.ok(tr.view().rev > rev)
})

test('stageAction carries the far end of a drag and the way of a scroll, for the marks', () => {
  const drag = stageAction({ action: 'drag', x: 10, y: 20, x2: 300, y2: 400 })
  assert.deepEqual([drag.x, drag.y, drag.x2, drag.y2], [10, 20, 300, 400])
  const boxed = stageAction({ action: 'drag', box: [0, 0, 100, 50], box2: [200, 200, 300, 300] })
  assert.deepEqual([boxed.x, boxed.y, boxed.x2, boxed.y2], [50, 25, 250, 250])
  const down = stageAction({ action: 'scroll', x: 5, y: 6 })
  assert.equal(down.dy, 300, 'a scroll without an amount goes down')
  const up = stageAction({ action: 'scroll', x: 5, y: 6, dy: -400 })
  assert.equal(up.dy, -400)
  const click = stageAction({ action: 'click', x: 1, y: 2 })
  assert.deepEqual([click.x2, click.y2, click.dy], [-1, -1, 0])
})

// The screen runs (ScreenRuns): what the glow round the screen and the capsule outside the
// window follow. A run is on from a session's first computer call to its turn's end, so the
// model's thinking between two steps does not take them down.
test('a screen run opens at the first computer call and stays through the gaps between calls', () => {
  const runs = new ScreenRuns()
  assert.equal(runs.current(), null)
  // a Reach call or a connector's tool does not take this screen
  assert.equal(runs.began('s1', 'device_screen', 1000), false)
  assert.equal(runs.began('s1', 'mcp__nanomuse__read_emails', 1000), false)
  assert.equal(runs.current(), null)
  assert.equal(runs.began('s1', 'mcp__nanomuse__computer_screen', 1000), true)
  assert.deepEqual(runs.current(), { sessionId: 's1', since: 1000 })
  runs.ended('s1', 1800)
  // the model thinks: nothing in flight, the run is still on
  assert.deepEqual(runs.current(), { sessionId: 's1', since: 1000 })
  assert.equal(runs.began('s1', 'mcp__nanomuse__computer_act', 9000), false, 'the same run goes on')
  runs.ended('s1', 9700)
  assert.deepEqual(runs.current(), { sessionId: 's1', since: 1000 })
  // the turn ends: the screen is free
  assert.equal(runs.turnEnded('s1'), true)
  assert.equal(runs.turnEnded('s1'), false)
  assert.equal(runs.current(), null)
  assert.equal(runs.size, 0)
})

test('the newest of several sessions on the screen is the one shown, and the idle sweep is the safety net', () => {
  const runs = new ScreenRuns()
  runs.began('old', 'mcp__nanomuse__computer_screen', 1000)
  runs.ended('old', 1500)
  runs.began('new', 'mcp__nanomuse__computer_act', 2000)
  assert.deepEqual(runs.current(), { sessionId: 'new', since: 2000 })
  assert.equal(runs.size, 2)
  // not quiet for long enough: nothing closes
  assert.equal(runs.sweep(1500 + SCREEN_RUN_IDLE_MS - 1, () => false), false)
  assert.equal(runs.size, 2)
  // quiet for long enough, but a call of "new" is still in flight: only "old" closes
  assert.equal(runs.sweep(2000 + SCREEN_RUN_IDLE_MS, (id) => id === 'new'), true)
  assert.deepEqual(runs.current(), { sessionId: 'new', since: 2000 })
  runs.ended('new', 2000 + SCREEN_RUN_IDLE_MS)
  assert.equal(runs.sweep(2000 + 2 * SCREEN_RUN_IDLE_MS, () => false), true)
  assert.equal(runs.current(), null)
})
