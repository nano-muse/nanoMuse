// Run the actual pinned Harness methods after applying the staging compatibility patch.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import ts from 'typescript'
import { clearedSessionAccessSource, clearedFileUploadSource } from '../../desktop/scripts/cleared-session-access.mjs'
const original = readFileSync(createRequire(import.meta.url).resolve('@deepseek-ai/dsh-api-session-controller'), 'utf8')
const patched = clearedSessionAccessSource(original)
const ast = ts.createSourceFile('controller.js', patched, ts.ScriptTarget.Latest, true)
const classes = new Map(), helpers = []
function walk(n) {
  if (ts.isClassExpression(n) || ts.isClassDeclaration(n)) classes.set(n.name?.text ?? n.parent.name?.text, n)
  if (ts.isFunctionDeclaration(n) && n.name?.text.startsWith('nanomuseSession')) helpers.push(n.getText())
  ts.forEachChild(n, walk)
}
walk(ast)
const fromController = createRequire(createRequire(import.meta.url).resolve('@deepseek-ai/dsh-api-session-controller'))
const uploadSource = readFileSync(fromController.resolve('@deepseek-ai/dsh-client-file-upload'), 'utf8')
walk(ts.createSourceFile('upload.js', clearedFileUploadSource(uploadSource), ts.ScriptTarget.Latest, true))
function setup() {
  const ids = new Set(), listeners = new Set()
  const cloud = { isClearedSession: id => ids.has(id), onChange: f => { listeners.add(f); return () => listeners.delete(f) } }
  const ctx = { get: name => name === 'nanomuseCloud' ? cloud : undefined, sessions: { get: id => ({ id, header: {} }) } }
  const sandbox = vm.createContext({ AbortController, AbortSignal, Symbol, RemoteError: class extends Error { constructor(code, message) { super(message); this.code = code } }, hasApiSessionSubagentOwner: () => false })
  vm.runInContext(helpers.join('\n'), sandbox)
  const method = (name, owner = 'SessionController') => {
    const node = classes.get(owner).members.find(m => m.name?.getText() === name)
    assert.ok(node, `${owner}.${name}`)
    return vm.runInContext(`({${node.getText()}}).${name}`, sandbox)
  }
  return { ctx, listeners, method, clear: id => { ids.add(id); for (const f of listeners) f() } }
}
const denied = error => error.code === 'session/not-found'

test('patch is idempotent and refuses changed pinned access seams', () => {
  assert.equal(clearedSessionAccessSource(patched), patched)
  assert.throws(() => clearedSessionAccessSource(original.replace('return this.history.page(request, signal);', 'return unknownHistory(request);')), /seam changed/)
})
test('stale IDs cannot inspect, clone, read attachments, create, prompt or resume', async () => {
  const h = setup(); h.clear('gone')
  const self = { ctx: h.ctx, commands: new Proxy({}, { get() { throw new Error('must not execute') } }) }
  for (const name of ['create', 'selectModel', 'rename', 'fork', 'attachment', 'updateQueue', 'prompt']) assert.throws(() => h.method(name).call(self, { sessionId: 'gone' }, new AbortController().signal), denied, name)
  assert.throws(() => h.method('inspect').call(self, 'gone'), denied)
  for (const name of ['resolveAgent', 'ensureSession']) await assert.rejects(h.method(name, 'ApiSessionAgentController').call(self, 'gone'), denied)
  assert.throws(() => h.method('inspect').call({ ctx: { get: () => undefined } }, 'old'), denied)
})
test('in-flight history is rejected when its session or parent is cleared', async () => {
  for (const address of [{ kind: 'session', sessionId: 'gone' }, { kind: 'subagent', parentSessionId: 'gone', childSessionId: 'child' }]) {
    const h = setup(); let finish
    const pending = h.method('page').call({ ctx: h.ctx, history: { page: () => new Promise(resolve => { finish = resolve }) } }, { address }, new AbortController().signal)
    h.clear('gone'); finish({ records: ['old text'] })
    await assert.rejects(pending, denied)
  }
})
test('clearing during agent composition cannot start a late resume', async () => {
  for (const id of ['old', 'parent']) {
    const h = setup(); let finish; let resumes = 0
    const self = { ctx: { ...h.ctx, sessions: { get: () => undefined }, agents: { get: () => undefined, resume: async () => { resumes++; return { agent: {} } } } }, composeAgent: () => new Promise(resolve => { finish = resolve }), presetForObservation: () => undefined, agentOptions: () => ({}) }
    const pending = h.method('resumeObserved', 'ApiSessionAgentController').call(self, 'old', { header: { id: 'old', cwd: '.', parentSession: 'parent', origin: 'subagent' } })
    h.clear(id); finish({ setup: () => {} })
    await assert.rejects(pending, denied)
    assert.equal(resumes, 0)
  }
})
test('clear aborts a subscribed history stream and removes its listener', async () => {
  const h = setup(); let signal
  const self = { ctx: h.ctx, history: { async *follow(_request, s) { signal = s; yield { type: 'snapshot' }; await new Promise(resolve => s.addEventListener('abort', resolve, { once: true })); if (!s.aborted) yield { text: 'old text' } } } }
  const stream = h.method('follow').call(self, { address: { kind: 'session', sessionId: 'old' } }, new AbortController().signal)
  assert.equal((await stream.next()).value.type, 'snapshot')
  const pending = stream.next(); h.clear('old')
  assert.equal((await pending).done, true)
  assert.equal(signal.aborted, true)
  assert.equal(h.listeners.size, 0)
})
test('list, search and control keep unrelated sessions and omit cleared ones', async () => {
  const h = setup(); h.clear('gone')
  const self = { ctx: h.ctx, listState: { list: async () => [{ sessionId: 'gone' }, { sessionId: 'child', parentSessionId: 'gone', origin: 'subagent' }, { sessionId: 'kept' }], search: async () => ({ items: [{ sessionId: 'gone' }, { sessionId: 'kept' }], hasMore: false }) }, controlState: { async *control() { yield { type: 'baseline', value: { projections: { gone: {}, kept: {} } } }; yield { type: 'projection', sessionId: 'gone', value: 'old' }; yield { type: 'projection', sessionId: 'kept', value: 'ok' } } } }
  assert.deepEqual((await h.method('list').call(self, {}, new AbortController().signal)).items.map(x => x.sessionId), ['kept'])
  assert.deepEqual((await h.method('search').call(self, { query: 'topic' }, new AbortController().signal)).items.map(x => x.sessionId), ['kept'])
  const frames = []; for await (const frame of h.method('control').call(self, new AbortController().signal)) frames.push(frame)
  assert.deepEqual(Object.keys(frames[0].value.projections), ['kept'])
  assert.equal(frames.length, 2); assert.equal(frames[1].sessionId, 'kept')
})


test('an explicit saved fork stays readable after clearing its source', async () => {
  const h = setup(); h.clear('parent')
  const header = { id: 'saved-copy', cwd: '.', parentSession: 'parent', isSeeded: true }
  const self = { ctx: { ...h.ctx, sessions: { get: () => ({ header, inheritedEventCount: 1, snapshotEvents: () => ['saved copy'] }) } } }
  const result = await h.method('inspect').call(self, 'saved-copy')
  assert.deepEqual(result.events, ['saved copy'])
  header.origin = 'subagent'
  assert.throws(() => h.method('inspect').call(self, 'saved-copy'), denied)
})


test('resolveAgent cannot return a late live-agent fallback after a clear', async () => {
  const h = setup(); let finish
  const self = { ctx: h.ctx, resolve: () => new Promise(resolve => { finish = resolve }) }
  const pending = h.method('resolveAgent', 'ApiSessionAgentController').call(self, 'old')
  h.clear('old'); finish({ agent: { id: 'old' } })
  await assert.rejects(pending, denied)
})


test('bound live-agent uploads reject cleared sessions and late completions', async () => {
  const h = setup(); const agent = { id: 'old', session: { header: { id: 'old' } } }
  const self = { ctx: { ...h.ctx, agents: { get: () => agent } }, assertAgentScope: () => {} }
  h.clear('old')
  assert.throws(() => h.method('assertOrdinaryAgent', 'FileUploads').call(self, agent), denied)
  await assert.rejects(h.method('resolveAgent', 'FileUploads').call(self, 'old'), denied)
  const other = setup(); let finish
  const late = { ctx: { ...other.ctx, agents: { get: () => agent } }, assertOrdinaryAgent: () => {} }
  const pending = other.method('commit', 'FileUploads').call(late, agent, () => new Promise(resolve => { finish = resolve }))
  other.clear('old'); finish({ name: 'file.txt' })
  await assert.rejects(pending, denied)
})


test('control drops queued projections after their live session was disposed', async () => {
  const h = setup()
  const self = { ctx: { ...h.ctx, sessions: { get: () => undefined } }, controlState: { async *control() { yield { type: 'projection', sessionId: 'disposed-child', value: 'old words' } } } }
  const frames = []
  for await (const frame of h.method('control').call(self, new AbortController().signal)) frames.push(frame)
  assert.deepEqual(frames, [])
})
