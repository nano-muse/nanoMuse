import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Relay } from '../lib/relay.js'
import { inheritCloudCapacity } from '../lib/cloud-llm.js'
import { capacityDefaultsSource } from '../../desktop/scripts/capacity-defaults.mjs'
import { createRequire } from 'node:module'
import { readFile, writeFile, mkdtemp, rm, realpath } from 'node:fs/promises'
import { join, dirname, resolve, basename } from 'node:path'
import { pathToFileURL } from 'node:url'

test('relay capacities survive parsing and manual values win over defaults', async () => {
  const relay = new Relay('https://relay.invalid', async () => new Response(JSON.stringify({ data: [{
    id: 'test-chat', context_length: 98304, max_output_tokens: 4096,
  }] })))
  const models = await relay.models('test-key')
  assert.equal(models[0].contextWindow, 98304)
  assert.equal(models[0].maxTokens, 4096)
  const raw = { nanomuse: { models: [{ id: 'test-chat' }] }, own: { models: [{ id: 'test-chat' }] } }
  const effective = inheritCloudCapacity(raw, models)
  assert.equal(effective.nanomuse.models[0].contextWindow, 98304)
  assert.equal(effective.nanomuse.models[0].maxTokens, 4096)
  assert.equal(raw.nanomuse.models[0].contextWindow, undefined)
  assert.equal(effective.own, raw.own)
  const manual = { nanomuse: { models: [{ id: 'test-chat', contextWindow: 32000, maxTokens: 1024 }] } }
  assert.deepEqual(inheritCloudCapacity(manual, models).nanomuse.models, manual.nanomuse.models)
  const changed = [{ ...models[0], contextWindow: 65536, maxTokens: 8192 }]
  assert.equal(inheritCloudCapacity(raw, changed).nanomuse.models[0].contextWindow, 65536)
  assert.equal(inheritCloudCapacity(raw, changed).nanomuse.models[0].maxTokens, 8192)
  assert.equal(inheritCloudCapacity(raw, []).nanomuse.models[0].contextWindow, undefined)
})

test('the staged adapter uses live server defaults without changing editable settings', async (t) => {
  const require = createRequire(import.meta.url)
  const installed = await realpath(require.resolve('@deepseek-ai/dsh-llm-pi-ai'))
  // Keep Node's real peer-resolution ancestry, without modifying the installed module.
  const folder = await mkdtemp(join(dirname(installed), 'nanomuse-capacity-adapter-'))
  t.after(async () => {
    assert.equal(resolve(dirname(folder)), resolve(dirname(installed)))
    assert.ok(basename(folder).startsWith('nanomuse-capacity-adapter-'))
    await rm(folder, { recursive: true, force: true })
  })
  await writeFile(join(folder, 'index.mjs'), capacityDefaultsSource(await readFile(installed, 'utf8')))
  const { apply, Config } = await import(pathToFileURL(join(folder, 'index.mjs')).href)
  let models = [{ id: 'test-chat', contextWindow: 98304, maxTokens: 4096 }]
  let adapter
  let raw = { nanomuse: { api: 'openai-completions', baseURL: 'https://relay.invalid/v1', models: [{ id: 'test-chat' }] } }
  const ctx = {
    fiber: { entry: { options: { id: 'llm-pi-ai' } } },
    get: (key) => key === 'nanomuseCloud' ? { providerDefaults: (providers) => inheritCloudCapacity(providers, models) } : undefined,
    inject() {}, on() {},
    llm: {
      registerConfigurableProviders() { return { replace() {} } },
      registerModelDiscovery() {},
      registerAdapter(_routes, registered) { adapter = registered; return { replace() {} } },
    },
  }
  apply(ctx, { ...Config({ providers: raw }), providers: { get: () => raw } })
  let info = await adapter.resolveModel('nanomuse', 'test-chat')
  assert.equal(info.context.contextWindow, 98304)
  assert.equal(info.defaultMaxTokens, 4096)
  models = [{ ...models[0], contextWindow: 65536, maxTokens: 8192 }]
  info = await adapter.resolveModel('nanomuse', 'test-chat')
  assert.equal(info.context.contextWindow, 65536)
  assert.equal(info.defaultMaxTokens, 8192)
  raw = { nanomuse: { ...raw.nanomuse, models: [{ id: 'test-chat', contextWindow: 32000, maxTokens: 1024 }] } }
  info = await adapter.resolveModel('nanomuse', 'test-chat')
  assert.equal(info.context.contextWindow, 32000)
  assert.equal(info.defaultMaxTokens, 1024)
  raw = { nanomuse: { ...raw.nanomuse, models: [{ id: 'test-chat' }] } }
  assert.equal((await adapter.resolveModel('nanomuse', 'test-chat')).context.contextWindow, 65536)
  assert.equal(raw.nanomuse.models[0].contextWindow, undefined)
  models = []
  assert.equal((await adapter.resolveModel('nanomuse', 'test-chat')).context.contextWindow, 262144)
})

test('invalid and absent wire capacities leave the existing adapter fallback alone', async () => {
  for (const value of [undefined, null, true, 0, -1, 1.5, '8192', 2147483648]) {
    const relay = new Relay('https://relay.invalid', async () => new Response(JSON.stringify({
      data: [{ id: 'test-chat', context_length: value, max_output_tokens: value }],
    })))
    const [model] = await relay.models('test-key')
    assert.equal(model.contextWindow, undefined)
    assert.equal(model.maxTokens, undefined)
  }
})
