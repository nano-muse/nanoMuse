// A task from another device run in a dsh session: the runner against a fake
// context — session creation and naming, the event frames it streams back in the
// runtime's vocabulary, approvals relayed to the asker and decided by `approve`,
// `stop {call}` cancelling the run, busy and timeout handling.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { getEventListeners } from 'node:events'
import { TaskRunner, frame, preview, textOf } from '../lib/task.js'
import { apply as applyReach } from '../lib/reach.js'
import { HubError } from '../lib/hub.js'

/** The slice of a dsh Context the runner touches. */
function fakeContext() {
  const listeners = { 'session/event': [], 'approval/request': [] }
  const sessions = new Map()
  const agents = new Map()
  const log = []
  const hooks = { followup() {} }
  const ctx = {
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
            hooks.followup(this)
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
  /** Ask the answerer chain, as the approval service would. */
  const ask = (sessionId, req) => {
    const chain = [...listeners['approval/request']]
    const run = (i) => (i < chain.length ? chain[i](Object.assign({ agent: agents.get(sessionId) }, req), () => run(i + 1)) : Promise.resolve('unavailable'))
    return run(0)
  }
  return { ctx, emit, ask, agents, log, hooks }
}

function fakeCall(id, from = { id: 'phone-1', name: 'Phone', kind: 'phone' }) {
  const events = []
  return { id, from, events, event: (body) => events.push(body) }
}

function runner(h) {
  const notices = []
  const r = new TaskRunner(h.ctx, { deviceName: () => 'Desk', log: (level, text) => h.log.push([level, text]), notice: (from, text) => notices.push([from, text]) })
  const off = r.attach()
  return { r, off, notices }
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

/** Exercise the registered sender tool and the receiving runner together. */
function delegation(h, r, language = 'en') {
  const tools = new Map()
  const calls = []
  const replies = []
  const destination = { id: 'desk', name: 'Desk', kind: 'computer', online: true }
  h.hooks.followup = (agent) => queueMicrotask(() => {
    agent.status = 'idle'
    h.emit(agent.id, 'turn/end', { reason: { kind: 'completed' } })
  })
  const hub = {
    connected: true,
    deviceId: 'source-1',
    devices: [destination],
    find: () => destination,
    nextId: () => `call-${calls.length + 1}`,
    async call(to, action, args, options) {
      assert.equal(to, destination.id)
      assert.equal(action, 'task')
      calls.push({ to, action, args })
      const reply = await r.task(args, fakeCall(options.id, { id: this.deviceId, name: 'Source', kind: 'computer' }))
      replies.push(reply)
      return reply
    },
  }
  applyReach({
    nanomuseCloud: { hub, signedIn: true },
    tools: { register(tool) { tools.set(tool.name, tool); return () => {} } },
    effect(fn) { fn() },
    inject() {},
    get(name) { return name === 'nanomuseRooms' ? { lang: language } : undefined },
    logger: { info() {}, warn() {} },
  })
  const send = (sessionId, task, execution = {}) => tools.get('delegate').execute(
    { device: 'Desk', task },
    { agent: sessionId === undefined ? undefined : { session: { id: sessionId } }, signal: new AbortController().signal, ...execution },
  )
  return { hub, calls, replies, send }
}

test('desktop delegation isolates chats and devices while continuing the same chat', { timeout: 5000 }, async (t) => {
  const h = fakeContext()
  const { r, off } = runner(h)
  t.after(off)
  const d = delegation(h, r)
  await d.send('chat-a', 'first task in A')
  await d.send('chat-b', 'first task in B')
  await d.send('  chat-a  ', 'continue A')
  d.hub.deviceId = 'source-2'
  await d.send('chat-a', 'A on another device')

  assert.deepEqual(d.replies.map((reply) => reply.thread), ['session-1', 'session-2', 'session-1', 'session-3'])
  assert.deepEqual(d.calls.map((call) => call.args.conversation), ['chat-a', 'chat-b', 'chat-a', 'chat-a'])
  assert.equal(h.ctx.sessionController.created.length, 3)
  assert.deepEqual([...h.agents.values()].map((agent) => agent.sent.map((msg) => msg.content[0].text.split('\n').at(-1))), [
    ['first task in A', 'continue A'], ['first task in B'], ['A on another device'],
  ])
})

test('desktop delegation without a source chat refuses before sending a task', async (t) => {
  const h = fakeContext()
  const { r, off } = runner(h)
  t.after(off)
  const d = delegation(h, r)
  for (const sessionId of [undefined, '', '   ', null, 42, {}]) {
    await assert.rejects(d.send(sessionId, 'a task'), /source conversation/)
  }
  await assert.rejects(d.send('ignored', 'a task', { agent: {} }), /source conversation/)
  assert.equal(d.calls.length, 0)
  assert.equal(h.ctx.sessionController.created.length, 0)
})

test('desktop delegation reports missing conversations in Chinese', async (t) => {
  const h = fakeContext()
  const { r, off } = runner(h)
  t.after(off)
  const d = delegation(h, r, 'zh-CN')
  await assert.rejects(d.send(undefined, 'a task'), /无法确定来源对话/)
  assert.equal(d.calls.length, 0)
})

test('desktop delegations from different chats can run and finish independently', { timeout: 5000 }, async (t) => {
  const h = fakeContext()
  const { r, off } = runner(h)
  t.after(off)
  const d = delegation(h, r)
  const started = []
  let ready
  const bothStarted = new Promise((resolve) => { ready = resolve })
  h.hooks.followup = (agent) => {
    started.push(agent)
    if (started.length === 2) ready()
  }
  const pending = Promise.all([d.send('chat-a', 'task A'), d.send('chat-b', 'task B')])
  await Promise.race([bothStarted, pending.then(() => { throw new Error('tasks finished before completion events') })])
  assert.equal(r.running, 2)
  assert.notEqual(started[0].id, started[1].id)
  for (const agent of started.reverse()) {
    const answer = agent.sent[0].content[0].text.split('\n').at(-1)
    h.emit(agent.id, 'assistant/message', { message: { content: [{ type: 'text', text: answer }] } })
    agent.status = 'idle'
    h.emit(agent.id, 'turn/end', { reason: { kind: 'completed' } })
  }
  const results = await pending
  assert.deepEqual(results.map((result) => result.answer), ['task A', 'task B'])
  assert.equal(r.running, 0)
})

test('desktop delegation releases its abort listener after success and remote failure', { timeout: 5000 }, async (t) => {
  const h = fakeContext()
  const { r, off } = runner(h)
  t.after(off)
  const d = delegation(h, r)
  const success = new AbortController()
  await d.send('chat-a', 'a task', { signal: success.signal })
  assert.equal(getEventListeners(success.signal, 'abort').length, 0)
  success.abort()
  assert.equal(d.calls.length, 1)

  let requests = 0
  d.hub.call = async () => { requests++; throw new HubError('offline', 'Target disconnected') }
  const failure = new AbortController()
  await assert.rejects(d.send('chat-a', 'a task', { signal: failure.signal }), /offline: Target disconnected/)
  assert.equal(getEventListeners(failure.signal, 'abort').length, 0)
  failure.abort()
  assert.equal(requests, 1)
})

test('cancelling a desktop delegation stops its own remote call', async (t) => {
  const h = fakeContext()
  const { r, off } = runner(h)
  t.after(off)
  const d = delegation(h, r)
  const controller = new AbortController()
  const requests = []
  d.hub.call = (to, action, args, options) => {
    requests.push({ to, action, args, options })
    if (action === 'stop') return Promise.resolve({ stopped: true })
    assert.equal(action, 'task')
    return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new HubError('aborted', 'The call was stopped')), { once: true })
    })
  }
  const pending = d.send('chat-a', 'a task', { signal: controller.signal })
  assert.equal(requests.length, 1)
  controller.abort()
  await assert.rejects(pending, /aborted: The call was stopped/)
  assert.deepEqual(requests.map(({ to, action }) => ({ to, action })), [
    { to: 'desk', action: 'task' }, { to: 'desk', action: 'stop' },
  ])
  assert.equal(requests[0].args.conversation, 'chat-a')
  assert.deepEqual(requests[1].args, { call: requests[0].options.id })
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0)
})

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
})

test('a task opens a named session, streams the run and resolves with the answer', async () => {
  const h = fakeContext()
  const { r, off, notices } = runner(h)
  const call = fakeCall('c1')
  const p = r.task({ text: 'what time is it' }, call)
  await tick()
  assert.deepEqual(h.ctx.sessionController.created, [{ agentPreset: 'nanomuse' }])
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
  assert.deepEqual(await r.approve({ approval_id: asked.approval_id, allow: true }), { ok: true })
  assert.equal(await outcome, 'allowed-once')
  assert.deepEqual(call.events.at(-1), { stage: 'approval_result', approval_id: asked.approval_id, status: 'approved' })

  const denied = h.ask('session-1', { toolName: 'bash', callId: 't9' })
  await tick()
  const asked2 = call.events.filter((e) => e.stage === 'approval').at(-1)
  await r.approve({ approval_id: asked2.approval_id, allow: false })
  assert.equal(await denied, 'rejected')

  // another session's approval is not ours
  assert.equal(await h.ask('session-other', { toolName: 'bash' }), 'unavailable')

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
