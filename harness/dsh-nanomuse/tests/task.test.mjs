// A task from another device run in a dsh session: the runner against a fake
// context — session creation and naming, the event frames it streams back in the
// runtime's vocabulary, approvals relayed to the asker and decided by `approve`,
// `stop {call}` cancelling the run, busy and timeout handling, the text of a message
// streamed while the model writes it when the asker asked for that.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { STREAM_INTERVAL_MS, TaskRunner, frame, grantKey, preview, textOf } from '../lib/task.js'

/** The slice of a dsh Context the runner touches. */
function fakeContext() {
  const listeners = { 'session/event': [], 'approval/request': [], 'agent/assistant-stream': [] }
  const sessions = new Map()
  const agents = new Map()
  const log = []
  // The workspace registry, as the chats column keeps it: a set of archived ids it can bring back.
  const registry = {
    archivedSessionIds: [],
    unarchived: [],
    async unarchiveSession(sessionId) {
      this.unarchived.push(sessionId)
      this.archivedSessionIds = this.archivedSessionIds.filter((id) => id !== sessionId)
    },
  }
  const ctx = {
    get(name) {
      return name === 'workspaceRegistry' ? registry : undefined
    },
    on(name, listener, prepend) {
      if (prepend) listeners[name].unshift(listener)
      else listeners[name].push(listener)
      return () => {
        const i = listeners[name].indexOf(listener)
        if (i >= 0) listeners[name].splice(i, 1)
      }
    },
    sessions: { get: (id) => sessions.get(id) },
    sessionController: {
      created: [],
      renamed: [],
      async create(request) {
        const sessionId = `session-${this.created.length + 1}`
        this.created.push(request)
        const session = { id: sessionId }
        sessions.set(sessionId, session)
        const agent = {
          id: sessionId,
          status: 'idle',
          session,
          sent: [],
          cancelled: [],
          followup(message) {
            this.sent.push(message)
            this.status = 'running'
          },
          cancel(cause) {
            this.cancelled.push(cause)
          },
        }
        agents.set(sessionId, agent)
        return { sessionId }
      },
      async rename(request) {
        this.renamed.push(request)
        return {}
      },
      async resolveAgent(sessionId) {
        const agent = agents.get(sessionId)
        return agent ? { agent } : { error: new Error('no such session') }
      },
    },
  }
  /** Append one event to a session, as the loop would. */
  const emit = (sessionId, type, data) => {
    for (const fn of [...listeners['session/event']]) fn(sessions.get(sessionId), { type, seq: 1, time: Date.now(), data })
  }
  /** Publish one live model-stream frame, as the agent loop would. */
  const stream = (sessionId, frame) => {
    for (const fn of [...listeners['agent/assistant-stream']]) fn({ agent: agents.get(sessionId), frame })
  }
  /** Ask the answerer chain, as the approval service would. */
  const ask = (sessionId, req) => {
    const chain = [...listeners['approval/request']]
    const run = (i) => (i < chain.length ? chain[i](Object.assign({ agent: agents.get(sessionId) }, req), () => run(i + 1)) : Promise.resolve('unavailable'))
    return run(0)
  }
  return { ctx, emit, ask, stream, agents, log, registry }
}

function fakeCall(id, from = { id: 'phone-1', name: 'Phone', kind: 'phone' }) {
  const events = []
  return { id, from, events, event: (body) => events.push(body) }
}

function runner(h, extra = {}) {
  const notices = []
  const r = new TaskRunner(h.ctx, { deviceName: () => 'Desk', log: (level, text) => h.log.push([level, text]), notice: (from, text) => notices.push([from, text]), ...extra })
  const off = r.attach()
  return { r, off, notices }
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** One text delta of attempt `a1`, as the agent loop publishes it. */
const delta = (index, text) => ({ type: 'chunk', attemptId: 'a1', revision: 1, index, time: Date.now(), chunk: { type: 'text-delta', index: 0, text } })

test('frame, textOf and preview', () => {
  assert.ok(frame('Phone', 'Desk', 'tidy up').startsWith('[Asked from Phone'))
  assert.ok(frame('Phone', 'Desk', 'tidy up').includes('the Muse on Desk'))
  assert.ok(frame('Phone', 'Desk', 'tidy up').endsWith('\ntidy up'))
  assert.equal(textOf([{ type: 'text', text: 'a' }, { type: 'image', data: 'x' }, { type: 'text', text: 'b' }]), 'a\nb')
  assert.equal(textOf(undefined), '')
  assert.equal(preview('bash', '{"command":"ls   -la\\n"}'), 'bash: ls -la')
  assert.equal(preview('read_file', '{"path":"/tmp/x"}'), 'read_file: /tmp/x')
  assert.equal(preview('think', 'not json'), 'think: not json')
  assert.equal(preview('noop', '{}'), 'noop')
  assert.equal(preview('bash', JSON.stringify({ command: 'x'.repeat(300) })).length, 'bash: '.length + 160)
  // the key a remembered answer is kept under: the whole argument, never the cut preview
  assert.equal(grantKey('bash', JSON.stringify({ command: 'x'.repeat(300) })), `bash: ${'x'.repeat(300)}`)
  assert.equal(grantKey('bash', '{"command":"ls   -la\\n"}'), 'bash: ls -la')
  assert.equal(grantKey('noop', '{}'), 'noop')
})

test('a task opens a named session, streams the run and resolves with the answer', async () => {
  const h = fakeContext()
  // the chat lives where the host says (the home workspace, #705), not in dsh's default folder
  const { r, off, notices } = runner(h, { home: async () => ({ agentPreset: 'nanomuse', workspaceId: 'ws-home' }) })
  const call = fakeCall('c1')
  const p = r.task({ text: 'what time is it' }, call)
  await tick()
  assert.deepEqual(h.ctx.sessionController.created, [{ agentPreset: 'nanomuse', workspaceId: 'ws-home' }])
  assert.deepEqual(h.ctx.sessionController.renamed, [{ sessionId: 'session-1', title: 'From Phone' }])
  const agent = h.agents.get('session-1')
  assert.equal(agent.sent.length, 1)
  assert.equal(agent.sent[0].role, 'user')
  assert.ok(agent.sent[0].content[0].text.endsWith('\nwhat time is it'))
  assert.equal(r.running, 1)
  assert.deepEqual(notices, [['Phone', 'what time is it']])

  h.emit('session-1', 'turn/start', { turn: 1 })
  h.emit('session-1', 'tool/call', { turn: 1, step: 1, callId: 't1', name: 'bash', arguments: '{"command":"date"}' })
  h.emit('session-1', 'tool/result', { turn: 1, step: 1, message: { role: 'tool', toolCallId: 't1', content: [{ type: 'text', text: 'Thu Oct 1 21:00' }], isError: false } })
  h.emit('session-1', 'assistant/message', { turn: 1, step: 2, message: { role: 'assistant', content: [{ type: 'text', text: 'It is 21:00.' }] }, stream: [] })
  h.emit('session-1', 'turn/end', { turn: 1, reason: { kind: 'completed' } })
  const result = await p
  assert.deepEqual(result, { text: 'It is 21:00.', conversation: 'phone-1', thread: 'session-1', device: 'Desk' })
  assert.deepEqual(call.events, [
    { stage: 'tool', id: 't1', name: 'bash', summary: 'date' },
    { stage: 'tool_result', id: 't1', name: 'bash', ok: true, summary: 'Thu Oct 1 21:00' },
    { stage: 'text', text: 'It is 21:00.', interim: true },
  ])
  assert.equal(r.running, 0)
  assert.equal(notices.length, 2)

  // the same place again reuses the session
  agent.status = 'idle'
  const p2 = r.task({ text: 'and now?' }, fakeCall('c2'))
  await tick()
  assert.equal(h.ctx.sessionController.created.length, 1)
  h.emit('session-1', 'turn/end', { turn: 2, reason: { kind: 'completed' } })
  assert.equal((await p2).text, '')
  off()
})

test('an approval goes to the asker and its approve decides; stop cancels the run', async () => {
  const h = fakeContext()
  const { r, off } = runner(h)
  const call = fakeCall('c1')
  const p = r.task({ text: 'delete the temp files' }, call)
  await tick()
  h.emit('session-1', 'tool/call', { turn: 1, step: 1, callId: 't9', name: 'bash', arguments: '{"command":"rm -rf /tmp/scratch"}' })
  const outcome = h.ask('session-1', { toolName: 'bash', callId: 't9', reason: 'destructive command' })
  await tick()
  const asked = call.events.find((e) => e.stage === 'approval')
  assert.ok(asked, 'approval relayed')
  assert.equal(asked.preview, 'bash: rm -rf /tmp/scratch')
  assert.equal(asked.reason, 'destructive command')
  assert.equal(asked.device, 'Desk')
  assert.deepEqual(await r.approve({ approval_id: 'nope', allow: true }), { ok: false })
  // another device cannot approve this run's card
  const foreignApprove = fakeCall('a2', { id: 'phone-2', name: 'Other', kind: 'phone' })
  assert.deepEqual(await r.approve({ approval_id: asked.approval_id, allow: true }, foreignApprove), { ok: false })
  assert.deepEqual(await r.approve({ approval_id: asked.approval_id, allow: true }, fakeCall('a1')), { ok: true })
  assert.equal(await outcome, 'allowed-once')
  assert.deepEqual(call.events.at(-1), { stage: 'approval_result', approval_id: asked.approval_id, status: 'approved' })

  const denied = h.ask('session-1', { toolName: 'bash', callId: 't9' })
  await tick()
  const asked2 = call.events.filter((e) => e.stage === 'approval').at(-1)
  await r.approve({ approval_id: asked2.approval_id, allow: false }, fakeCall('a1'))
  assert.equal(await denied, 'rejected')

  // another session's approval is not ours
  assert.equal(await h.ask('session-other', { toolName: 'bash' }), 'unavailable')

  // another device cannot stop this call
  const foreignStop = fakeCall('s_other', { id: 'phone-2', name: 'Other', kind: 'phone' })
  assert.deepEqual(await r.stop({ call: 'c1' }, foreignStop), { stopped: false })
  assert.equal(h.agents.get('session-1').cancelled.length, 0)

  // stop by call id cancels the agent; the aborted turn resolves with what was said
  assert.deepEqual(await r.stop({ call: 'c1' }, fakeCall('s1')), { stopped: true })
  assert.deepEqual(h.agents.get('session-1').cancelled, [{ kind: 'user' }])
  h.emit('session-1', 'assistant/message', { turn: 1, step: 1, message: { role: 'assistant', content: [{ type: 'text', text: 'half way' }] }, stream: [], interrupted: true })
  h.emit('session-1', 'turn/end', { turn: 1, reason: { kind: 'aborted', reason: { kind: 'user' } } })
  assert.equal((await p).text, 'half way')
  assert.deepEqual(await r.stop({ call: 'c1' }, fakeCall('s2')), { stopped: false })
  off()
})

test('a remembered conversation reuses its session after a restart; a vanished one is replaced', async () => {
  const h = fakeContext()
  const memory = new Map()
  const make = () => {
    const r = new TaskRunner(h.ctx, { deviceName: () => 'Desk', log: () => undefined, recall: (k) => memory.get(k), remember: (k, id) => memory.set(k, id) })
    return { r, off: r.attach() }
  }
  const first = make()
  const p1 = first.r.task({ text: 'one' }, fakeCall('c1'))
  await tick()
  h.emit('session-1', 'turn/end', { turn: 1, reason: { kind: 'completed' } })
  await p1
  first.off()
  assert.deepEqual([...memory.entries()], [['phone-1\nphone-1', 'session-1']])

  // "restart": a fresh runner, the same memory, the session still resumable
  h.agents.get('session-1').status = 'idle'
  const second = make()
  const p2 = second.r.task({ text: 'two' }, fakeCall('c2'))
  await tick()
  assert.equal(h.ctx.sessionController.created.length, 1)
  h.emit('session-1', 'turn/end', { turn: 2, reason: { kind: 'completed' } })
  assert.equal((await p2).thread, 'session-1')

  // the session is gone from disk: a new one, remembered in its place
  h.agents.delete('session-1')
  const p3 = second.r.task({ text: 'three' }, fakeCall('c3'))
  await tick()
  assert.equal(h.ctx.sessionController.created.length, 2)
  assert.equal(memory.get('phone-1\nphone-1'), 'session-2')
  h.emit('session-2', 'turn/end', { turn: 1, reason: { kind: 'completed' } })
  assert.equal((await p3).thread, 'session-2')
  second.off()
})

test('a chat archived since the last task is brought back, not delivered into a gate (#718)', async () => {
  const h = fakeContext()
  const memory = new Map()
  const make = () => {
    const r = new TaskRunner(h.ctx, { deviceName: () => 'Desk', log: () => undefined, recall: (k) => memory.get(k), remember: (k, id) => memory.set(k, id) })
    return { r, off: r.attach() }
  }
  const first = make()
  const p1 = first.r.task({ text: 'one' }, fakeCall('c1'))
  await tick()
  h.emit('session-1', 'turn/end', { turn: 1, reason: { kind: 'completed' } })
  await p1
  first.off()

  // somebody tidied the chats column while the runner remembered the conversation
  h.registry.archivedSessionIds = ['session-1']
  h.agents.get('session-1').status = 'idle'
  const second = make()
  const p2 = second.r.task({ text: 'two' }, fakeCall('c2'))
  await tick()
  assert.deepEqual(h.registry.unarchived, ['session-1'], 'the archived chat came back before the delivery')
  assert.deepEqual(h.registry.archivedSessionIds, [])
  assert.equal(h.ctx.sessionController.created.length, 1, 'the conversation stayed where it was')
  h.emit('session-1', 'turn/end', { turn: 2, reason: { kind: 'completed' } })
  assert.equal((await p2).thread, 'session-1')
  second.off()
})

test('a delivery a chat refused to start says it did not run, instead of an empty answer (#718)', async () => {
  const h = fakeContext()
  const { r, off } = runner(h)
  const call = fakeCall('c1')
  const p = r.task({ text: 'open the report' }, call)
  await tick()
  // the step was refused before the model was asked: no request, no answer, the turn ends blocked
  h.emit('session-1', 'turn/start', { turn: 1 })
  h.emit('session-1', 'turn/end', { turn: 1, reason: { kind: 'blocked' } })
  await assert.rejects(p, (e) => e.code === 'failed' && e.message === 'the step was refused before the model was asked')
  assert.deepEqual(call.events, [{ stage: 'error', message: 'the step was refused before the model was asked' }])
  off()
})

test('busy, usage, a model error and a pending approval cancelled with the run', async () => {
  const h = fakeContext()
  const { r, off } = runner(h)
  await assert.rejects(r.task({ text: '  ' }, fakeCall('c0')), (e) => e.code === 'usage')
  const call = fakeCall('c1')
  const p = r.task({ text: 'one' }, call)
  await tick()
  await assert.rejects(r.task({ text: 'two' }, fakeCall('c2')), (e) => e.code === 'busy')
  const pendingApproval = h.ask('session-1', { toolName: 'bash' })
  await tick()
  h.emit('session-1', 'turn/end', { turn: 1, reason: { kind: 'error', error: { message: 'provider down', code: 'upstream' } } })
  await assert.rejects(p, (e) => e.code === 'failed' && e.message === 'provider down')
  assert.equal(await pendingApproval, 'cancelled')
  assert.ok(call.events.some((e) => e.stage === 'error' && e.message === 'provider down'))
  off()
})

test('a closed gate refuses a task with the usual busy error, and opens again', async () => {
  const h = fakeContext()
  let closed = true
  const r = new TaskRunner(h.ctx, { deviceName: () => 'Desk', log: () => undefined, closed: () => closed })
  const off = r.attach()
  await assert.rejects(r.task({ text: 'hello' }, fakeCall('c1')), (e) => e.code === 'busy' && e.message === 'this computer is ending its work; ask again in a moment')
  assert.deepEqual(h.ctx.sessionController.created, [], 'nothing was opened for the refused task')
  closed = false
  const p = r.task({ text: 'hello' }, fakeCall('c2'))
  await tick()
  assert.equal(r.running, 1, 'the gate is open, the task runs')
  h.emit('session-1', 'turn/end', { turn: 1, reason: { kind: 'completed' } })
  await p
  off()
})

test('with stream asked, the text of a message goes out as it grows, then the message as before', async () => {
  const h = fakeContext()
  const { r, off } = runner(h)
  const call = fakeCall('c1')
  const p = r.task({ text: 'explain the project', stream: true }, call)
  await tick()
  h.stream('session-1', { type: 'start', attemptId: 'a1', revision: 1, turn: 1, step: 1 })
  h.stream('session-1', delta(0, 'It is '))
  // a stored event that does not end the message leaves its text running
  h.emit('session-1', 'llm/retry-started', { turn: 1, step: 1 })
  h.stream('session-1', delta(1, 'a todo '))
  // a burst within one interval goes out once, as the text so far
  assert.deepEqual(call.events, [])
  await wait(STREAM_INTERVAL_MS + 20)
  assert.deepEqual(call.events, [{ stage: 'text', text: 'It is a todo ', interim: true, partial: true }])
  // a reasoning delta is not the Muse's words
  h.stream('session-1', { type: 'chunk', attemptId: 'a1', revision: 1, index: 2, time: Date.now(), chunk: { type: 'reasoning-delta', index: 1, text: 'hmm' } })
  h.stream('session-1', delta(3, 'app.'))
  // the finished message overtakes the pending text: nothing partial lands after it
  h.emit('session-1', 'assistant/message', { turn: 1, step: 1, message: { role: 'assistant', content: [{ type: 'text', text: 'It is a todo app.' }] }, stream: [] })
  h.stream('session-1', { type: 'end', attemptId: 'a1', revision: 1, index: 4, outcome: { kind: 'committed', eventType: 'assistant/message', seq: 3 } })
  await wait(STREAM_INTERVAL_MS + 20)
  h.emit('session-1', 'turn/end', { turn: 1, reason: { kind: 'completed' } })
  assert.equal((await p).text, 'It is a todo app.')
  assert.deepEqual(call.events, [
    { stage: 'text', text: 'It is a todo ', interim: true, partial: true },
    { stage: 'text', text: 'It is a todo app.', interim: true },
  ])
  off()
})

test('a new attempt starts its text afresh, and a caller that did not ask gets no partial text', async () => {
  const h = fakeContext()
  const { r, off } = runner(h)
  const asked = fakeCall('c1')
  const p = r.task({ text: 'go', stream: true }, asked)
  await tick()
  h.stream('session-1', { type: 'start', attemptId: 'a1', revision: 1, turn: 1, step: 1 })
  h.stream('session-1', delta(0, 'first try'))
  h.stream('session-1', { type: 'end', attemptId: 'a1', revision: 1, index: 1, outcome: { kind: 'abandoned' } })
  h.stream('session-1', { type: 'start', attemptId: 'a2', revision: 2, turn: 1, step: 1 })
  h.stream('session-1', { ...delta(0, 'second'), attemptId: 'a2', revision: 2 })
  await wait(STREAM_INTERVAL_MS + 20)
  assert.deepEqual(asked.events, [{ stage: 'text', text: 'second', interim: true, partial: true }])
  h.emit('session-1', 'turn/end', { turn: 1, reason: { kind: 'completed' } })
  await p

  h.agents.get('session-1').status = 'idle'
  const plain = fakeCall('c2')
  const p2 = r.task({ text: 'again' }, plain)
  await tick()
  h.stream('session-1', { type: 'start', attemptId: 'a3', revision: 3, turn: 2, step: 1 })
  h.stream('session-1', { ...delta(0, 'words'), attemptId: 'a3', revision: 3 })
  await wait(STREAM_INTERVAL_MS + 20)
  assert.deepEqual(plain.events, [])
  h.emit('session-1', 'turn/end', { turn: 2, reason: { kind: 'completed' } })
  await p2
  off()
})
