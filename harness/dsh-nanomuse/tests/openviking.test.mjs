// Exercise the packaged bridge and pinned DSH message types against a local HTTP stub.
// This checks the integration contract, not OpenViking's extraction quality.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createServer } from 'node:http'
import { mkdtemp, rm, writeFile, readdir } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Session } from '@deepseek-ai/dsh-session'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import * as bridge from 'dsh-nanomuse/openviking'

function host(config) {
  const hooks = new Map()
  const effects = []
  const mounted = []
  const services = {}
  const ctx = {
    logger: { debug() {}, warn() {} },
    provide(name, value) { services[name] = value },
    effect(fn) { effects.push(fn()) },
    on(name, fn) { hooks.set(name, fn) },
    plugin(plugin, options) { mounted.push({ plugin, options }) },
  }
  bridge.apply(ctx, config)
  return {
    hooks, services, mounted,
    async close() { for (const dispose of effects.toReversed()) await dispose() },
  }
}

async function fixture(t) {
  const dir = await mkdtemp(join(tmpdir(), 'nm-openviking-'))
  const cli = join(dir, 'ovcli.conf')
  await writeFile(cli, '{}')
  // Never read the developer's credentials, replay their queue, or leave test memory behind.
  const values = {
    OPENVIKING_CLI_CONFIG_FILE: cli,
    OPENVIKING_CONFIG_FILE: join(dir, 'absent.conf'),
    OPENVIKING_CONFIG_SOURCE: 'env',
    OPENVIKING_STATE_DIR: join(dir, 'state'),
    OPENVIKING_PENDING_DIR: join(dir, 'pending'),
    OPENVIKING_RECALL_COMPRESS: 'off',
    OPENVIKING_WORKSPACE_PEER: '0',
    OPENVIKING_CAPTURE_TOOL_RESULTS: '0',
    OPENVIKING_MEMORY_ENABLED: '1',
    OPENVIKING_SYNC_TURNS: '1',
  }
  const before = Object.fromEntries(Object.keys(values).map(key => [key, process.env[key]]))
  Object.assign(process.env, values)
  let instance
  let server
  t.after(async () => {
    try {
      // Dispose while the isolated queue and HTTP server still exist.
      await instance?.close()
      if (server?.listening) await new Promise(resolve => server.close(resolve))
    } finally {
      for (const [key, value] of Object.entries(before)) {
        if (value === undefined) delete process.env[key]
        else process.env[key] = value
      }
      await rm(dir, { recursive: true, force: true })
    }
  })

  const requests = []
  const messages = new Map()
  let saved = ''
  let available = true
  server = createServer(async (req, res) => {
    let raw = ''
    for await (const chunk of req) raw += chunk
    const body = raw ? JSON.parse(raw) : undefined
    requests.push({ path: req.url, body, headers: req.headers })
    const answer = (result, status = 200) => {
      res.writeHead(status, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ status: status === 200 ? 'ok' : 'error', result }))
    }
    if (!available) return answer(null, 503)
    if (req.url === '/health') return answer({})
    if (req.url === '/api/v1/sessions') {
      messages.set(body.session_id, [])
      return answer({ session_id: body.session_id })
    }
    const match = req.url.match(/^\/api\/v1\/sessions\/([^/]+)\/(messages|commit)$/)
    if (match) {
      const turns = messages.get(match[1])
      if (match[2] === 'messages') turns.push(body)
      else saved = turns.map(turn => JSON.stringify(turn)).join('\n')
      return answer({})
    }
    if (req.url === '/api/v1/system/status') return answer({ user: 'test-user' })
    if (req.url === '/api/v1/search/search') {
      return answer({ rendered: saved, entries: [], stats: {} })
    }
    if (req.url.startsWith('/api/v1/fs/ls') || req.url.startsWith('/api/v1/skills')) return answer([])
    return answer(null, 404)
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const config = {
    endpoint: `http://127.0.0.1:${server.address().port}`,
    apiKey: '',
    account: 'test-account',
    user: 'test-user',
    authMode: 'trusted',
    captureToolResults: false,
    skillCatalog: false,
    peerSource: 'none',
  }
  instance = host(config)
  const agent = id => ({ session: Session.create(id), status: 'idle', ctx: { effect() {} } })
  const recall = async (target, text) => {
    const messages = [createUserMessage({ content: text, source: { kind: 'user' } })]
    return instance.hooks.get('agent/pre-step')(
      { agent: target, messages, signal: new AbortController().signal },
      async () => ({ kind: 'enter', messages }),
    )
  }
  return { ...instance, dir, agent, recall, requests, messages, setAvailable(value) { available = value } }
}

test('the packaged OpenViking bridge captures, commits and recalls across DSH sessions', async t => {
  const f = await fixture(t)
  const first = f.agent('memory-first')
  const input = createUserMessage({ content: 'I prefer jasmine tea.', source: { kind: 'user' } })
  const initial = await f.recall(first, 'Remember my tea preference')
  assert.equal(initial.messages.length, 1)
  f.hooks.get('session/event')(first.session, { type: 'user/message', data: input })
  f.hooks.get('session/event')(first.session, {
    type: 'user/message',
    data: createUserMessage({ content: 'Synthetic context', source: { kind: 'plugin:other' } }),
  })
  f.hooks.get('session/event')(first.session, {
    type: 'tool/result', data: { message: { role: 'user', source: { kind: 'tool' }, content: [{ type: 'text', text: 'Tool output' }] } },
  })
  await f.hooks.get('session/flush')(first.session)
  await f.services.openvikingMemory.dispose(first.session)
  const second = await f.recall(f.agent('memory-second'), 'Which tea do I prefer?')
  assert.match(JSON.stringify(second.messages.slice(1)), /jasmine tea/)
  assert.equal([...f.messages.values()].flat().length, 1)
  assert.ok(f.requests.some(req => req.path.endsWith('/commit')))
  assert.equal(f.messages.size, 2)
  assert.ok(f.mounted.some(row => row.options.serverName === 'openviking'))
  assert.ok(f.mounted.some(row => row.options.providerName === 'openviking'))
  const search = f.requests.find(req => req.path === '/api/v1/search/search')
  assert.equal(search.headers['x-openviking-account'], 'test-account')
  assert.equal(search.headers['x-openviking-user'], 'test-user')
})

test('an unavailable memory server leaves the turn usable and queues captured input', async t => {
  const f = await fixture(t)
  f.setAvailable(false)
  const target = f.agent('memory-unavailable')
  const result = await f.recall(target, 'Continue without the memory server')
  assert.equal(result.kind, 'enter')
  assert.equal(result.messages.length, 1)
  f.hooks.get('session/event')(target.session, {
    type: 'user/message',
    data: createUserMessage({ content: 'Save this after recovery.', source: { kind: 'user' } }),
  })
  await f.hooks.get('session/flush')(target.session)
  const queued = await readdir(join(f.dir, 'pending'))
  assert.ok(queued.some(name => name.endsWith('.json')))
})
