import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Context, Service } from '@deepseek-ai/cordis'
import { isAgentLoopRequest, LlmAdapter, LlmRuntime, markAgentLoopRequest } from '@deepseek-ai/dsh-llm'
import NanomuseCloud, { LLM_ROW, PROVIDER_ID } from '../lib/cloud.js'

async function within(promise) {
  let timer
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('startup did not settle')), 2000)
    })])
  } finally {
    clearTimeout(timer)
  }
}

async function collect(stream) {
  const chunks = []
  for await (const chunk of stream) chunks.push(chunk)
  return chunks
}

async function fixture(context, { holdWrites = false, writeError, empty = false } = {}) {
  const home = await mkdtemp(join(tmpdir(), 'nm-cloud-startup-'))
  const staleServer = createServer((request, response) => {
    staleRequests += 1
    response.end('stale')
  })
  let staleRequests = 0
  await new Promise(resolve => staleServer.listen(0, '127.0.0.1', resolve))
  const staleBase = `http://127.0.0.1:${staleServer.address().port}/v1`
  const original = { displayName: 'nanoMuse Cloud', baseURL: staleBase, apiKeyEnv: 'NANOMUSE_TEST_UNUSED', models: [{ id: 'test-model' }] }
  const custom = { baseURL: staleBase, models: [{ id: 'custom-model' }] }
  const settings = { [LLM_ROW]: { providers: { ...(empty ? {} : { [PROVIDER_ID]: original }), custom } } }
  const loader = Promise.withResolvers()
  const writing = Promise.withResolvers()
  const writesAllowed = Promise.withResolvers()
  if (!holdWrites) writesAllowed.resolve()
  const disposers = []
  const warnings = []
  const sent = []
  const runtimeContext = new Context()
  const runtime = new LlmRuntime(runtimeContext)
  let writes = 0
  class Adapter extends LlmAdapter {
    providerInfo(provider) { return { id: provider, name: provider } }
    prepareCall(provider, model) {
      const base = settings[LLM_ROW].providers[provider].baseURL
      return Promise.resolve({
        model: { provider, id: model, name: model },
        stream: async function* (options) {
          sent.push({ base, options })
          if (provider === PROVIDER_ID) await fetch(`${base}/probe`, { signal: options.signal })
          yield { type: 'finish', reason: { kind: 'stop' } }
        },
      })
    }
    async *stream() { throw new Error('use the prepared adapter call') }
  }
  runtime.registerAdapter([PROVIDER_ID, 'custom'], new Adapter())
  const ctx = {
    reflect: { provide() {} },
    logger: { info() {}, warn(...args) { warnings.push(args) }, debug() {}, error() {} },
    credentials: { async resolve() { return undefined } },
    settings: {
      describe: () => Object.entries(settings).map(([ns, value]) => ({ ns, value })),
      async update(ns, patch) {
        writes += 1
        writing.resolve()
        await loader.promise
        await writesAllowed.promise
        if (writeError) throw writeError
        settings[ns].providers = { ...settings[ns].providers, ...patch.providers }
      },
    },
    get(name) {
      if (name === 'loader') return { await: () => loader.promise }
      if (name === 'llm') return runtime
      return undefined
    },
    inject(deps, fn) { if (deps.includes('llm')) fn(runtimeContext) },
    effect(fn) { const dispose = fn(); if (typeof dispose === 'function') disposers.push(dispose) },
    on() { return () => undefined },
  }
  const statePath = join(home, 'cloud.json')
  await writeFile(statePath, JSON.stringify({ deviceId: 'pc-dsh-test', update: { checkedAt: Date.now() } }))
  const service = new NanomuseCloud(ctx, { baseURL: staleBase.replace('/v1', ''), statePath })
  service.cloudModels = () => true
  const dispose = () => { for (const release of disposers.splice(0)) release() }
  context.after(async () => {
    dispose()
    loader.resolve()
    writesAllowed.resolve()
    await runtimeContext.fiber.dispose()
    await service.relayDoor.close()
    await new Promise(resolve => staleServer.close(resolve))
    await rm(home, { recursive: true, force: true })
  })
  const init = service[Service.init]()
  const options = { provider: PROVIDER_ID, model: 'test-model', messages: [], sessionId: 'test-session' }
  return { service, runtime, runtimeContext, settings, original, custom, loader, writing, writesAllowed, init, options, sent, warnings, dispose, writes: () => writes, staleRequests: () => staleRequests }
}

test('initialization finishes before Loader settles, and saved providers are updated once without losing other settings', async context => {
  const state = await fixture(context)
  await within(state.init)
  assert.equal(state.writes(), 0)
  state.loader.resolve()
  await within(state.service.providerReady)
  assert.equal(state.writes(), 1)
  assert.deepEqual(state.settings[LLM_ROW].providers[PROVIDER_ID], { ...state.original, baseURL: state.service.relayDoor.openaiBase })
  assert.deepEqual(state.settings[LLM_ROW].providers.custom, state.custom)
})

test('prepared calls wait for startup and rebind even when dispatched after the update has finished', async context => {
  const state = await fixture(context, { holdWrites: true })
  await within(state.init)
  const expected = context.mock.method(state.service.provenance, 'expect')
  const early = await state.runtime.prepareCall(state.options)
  const late = await state.runtime.prepareCall(state.options)
  const waiting = collect(early.stream(state.options))
  state.loader.resolve()
  await within(state.writing.promise)
  assert.equal(state.sent.length, 0)
  state.writesAllowed.resolve()
  await within(waiting)
  await within(collect(late.stream(state.options)))
  assert.equal(state.sent.length, 2)
  assert.ok(state.sent.every(call => call.base === state.service.relayDoor.openaiBase))
  assert.equal(state.staleRequests(), 0)
  assert.equal(state.writes(), 1)
  assert.equal(expected.mock.callCount(), 2)
  assert.equal(state.service.provenance.waiting, 0)
})

test('a loop-built request keeps its identity and frozen envelope through the rebind', async context => {
  const state = await fixture(context)
  await within(state.init)
  state.loader.resolve()
  await within(state.service.providerReady)
  const seen = []
  state.runtimeContext.on('llm/stream', (options, next) => {
    if (options.provider === PROVIDER_ID) seen.push({ marked: isAgentLoopRequest(options), frozen: Object.isFrozen(options) })
    return next()
  }, { prepend: true })
  const options = markAgentLoopRequest(Object.freeze({ ...state.options, messages: Object.freeze([]) }))
  await within(collect(state.runtime.stream(options)))
  assert.deepEqual(seen, [
    { marked: true, frozen: true },
    { marked: true, frozen: true },
  ])
})

test('concurrent Cloud calls share startup while custom providers are not blocked', async context => {
  const state = await fixture(context, { holdWrites: true })
  await within(state.init)
  const pending = [collect(state.runtime.stream(state.options)), collect(state.runtime.stream(state.options))]
  await within(collect(state.runtime.stream({ ...state.options, provider: 'custom', model: 'custom-model' })))
  assert.equal(state.sent.length, 1)
  state.loader.resolve()
  await within(state.writing.promise)
  state.writesAllowed.resolve()
  await within(Promise.all(pending))
  assert.equal(state.writes(), 1)
  assert.equal(state.sent.length, 3)
  assert.equal(state.staleRequests(), 0)
})

test('canceling a waiting call does not cancel startup or send that call', async context => {
  const state = await fixture(context)
  await within(state.init)
  const controller = new AbortController()
  const waiting = collect(state.runtime.stream({ ...state.options, signal: controller.signal }))
  controller.abort()
  const chunks = await within(waiting)
  assert.equal(chunks.at(-1).reason.kind, 'aborted')
  assert.equal(state.sent.length, 0)
  state.loader.resolve()
  await within(collect(state.runtime.stream(state.options)))
  assert.equal(state.sent.length, 1)
  assert.equal(state.staleRequests(), 0)
})

test('a failed startup update fails Cloud calls without dispatching to the old port', async context => {
  const state = await fixture(context, { writeError: new Error('test write failed') })
  await within(state.init)
  const waiting = collect(state.runtime.stream(state.options))
  state.loader.resolve()
  const chunks = await within(waiting)
  assert.equal(chunks.at(-1).reason.kind, 'error')
  assert.equal(chunks.at(-1).reason.failure.code, 'NANOMUSE_CLOUD_STARTUP_FAILED')
  assert.equal(state.sent.length, 0)
  assert.equal(state.staleRequests(), 0)
  assert.equal(state.warnings.length, 1)
})

test('disposing before Loader settles cancels waiters and does not write the profile later', async context => {
  const state = await fixture(context)
  await within(state.init)
  const waiting = collect(state.runtime.stream(state.options))
  state.dispose()
  assert.equal((await within(waiting)).at(-1).reason.kind, 'aborted')
  state.loader.resolve()
  await state.service.providerReady.catch(() => undefined)
  assert.equal(state.writes(), 0)
  assert.equal(state.sent.length, 0)
})

test('disposing during an in-flight settings update does not release a waiting request', async context => {
  const state = await fixture(context, { holdWrites: true })
  await within(state.init)
  const waiting = collect(state.runtime.stream(state.options))
  state.loader.resolve()
  await within(state.writing.promise)
  state.dispose()
  assert.equal((await within(waiting)).at(-1).reason.kind, 'aborted')
  state.writesAllowed.resolve()
  await within(state.service.providerReady)
  assert.equal(state.writes(), 1)
  assert.equal(state.sent.length, 0)
  assert.equal(state.staleRequests(), 0)
})

test('Cloud-off policy still refuses without waiting for startup or sending a request', async context => {
  const state = await fixture(context)
  await within(state.init)
  state.service.cloudModels = () => false
  const chunks = await within(collect(state.runtime.stream(state.options)))
  assert.equal(chunks.at(-1).reason.failure.code, 'nanomuse/cloud_off')
  assert.equal(state.writes(), 0)
  assert.equal(state.sent.length, 0)
})

test('a fresh profile does not create a Cloud provider or overwrite a custom provider', async context => {
  const state = await fixture(context, { empty: true })
  await within(state.init)
  state.loader.resolve()
  await within(state.service.providerReady)
  assert.equal(state.writes(), 0)
  assert.deepEqual(state.settings[LLM_ROW].providers, { custom: state.custom })
})
