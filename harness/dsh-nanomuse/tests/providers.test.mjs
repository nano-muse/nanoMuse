// Own-key providers with capabilities (C11): the catalogue, the "ways on", the gate, the model
// adapter's row, and the ChatGPT sign-in driven over the runtime's `--json` events.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { readFileSync } from 'node:fs'
import {
  apiOf, baseUrlFor, capabilitiesForAuth, capabilitiesOf, ChatGptDesk, chatGptOnly, keyRefFor, kindOf, LineReader, listModels, loadCatalogue, modelsOf, ownKeyStepDone, ownProviderRow, parseCatalogue, providersWith, regionOf, sighted, typedModelIds, unavailableKey, waysOn,
} from '../lib/providers.js'

const catalogue = parseCatalogue(JSON.parse(readFileSync(new URL('../assets/providers.json', import.meta.url), 'utf8')))

test('the catalogue parses as shipped: every row has an id, a protocol, regions and chat; the extras survive', () => {
  assert.ok(catalogue.length >= 15)
  for (const p of catalogue) {
    assert.match(p.id, /^[a-z][a-z0-9-]*$/)
    assert.ok(p.regions.length >= 1, p.id)
    assert.ok(p.capabilities.includes('chat'), p.id)
  }
  const openai = catalogue.find((p) => p.id === 'openai')
  assert.deepEqual(capabilitiesForAuth(openai, 'oauth-chatgpt'), ['chat', 'vision'])
  assert.deepEqual(capabilitiesForAuth(openai, 'key'), ['chat', 'vision', 'image'])
  const moonshot = catalogue.find((p) => p.id === 'moonshot')
  assert.equal(baseUrlFor(moonshot, 'cn'), 'https://api.moonshot.cn/v1')
  assert.equal(baseUrlFor(moonshot, 'global'), 'https://api.moonshot.ai/v1')
  assert.equal(catalogue.find((p) => p.id === 'custom').user_capabilities, true)
  // malformed rows are dropped, not thrown on
  assert.deepEqual(parseCatalogue({ providers: [{ id: 'Bad Id' }, null, { id: 'ok', protocol: 'weird', capabilities: ['chat', 'nope'] }] }).map((p) => [p.id, p.protocol, p.capabilities]), [['ok', 'openai', ['chat']]])
  assert.deepEqual(parseCatalogue('nonsense'), [])
})

test('loadCatalogue reads the asset next to lib/ and gives an empty list for a missing file', async () => {
  assert.ok((await loadCatalogue()).length >= 15)
  assert.deepEqual(await loadCatalogue('/nonexistent/providers.json'), [])
})

test('ways on: the region first (Bailian in mainland China; OpenRouter then OpenAI elsewhere), a sign-in group, the rest by coverage, local servers, custom', () => {
  const cn = waysOn(catalogue, 'cn')
  assert.deepEqual(cn.first.map((p) => p.id), ['bailian'])
  assert.deepEqual(cn.signIn.map((p) => p.id), [])
  assert.ok(!cn.rest.some((p) => p.regions.length && !p.regions.includes('cn')))
  assert.ok(!cn.rest.some((p) => ['bailian', 'ollama', 'lm-studio', 'vllm', 'custom'].includes(p.id)))
  assert.deepEqual(cn.local.map((p) => p.id), ['ollama', 'lm-studio', 'vllm'])
  assert.equal(cn.custom.id, 'custom')
  // the ones that can do more first
  const coverage = cn.rest.map((p) => p.capabilities.length)
  assert.deepEqual(coverage, [...coverage].sort((a, b) => b - a))
  const global = waysOn(catalogue, 'global')
  assert.deepEqual(global.first.map((p) => p.id), ['openrouter', 'openai'])
  // OpenAI is already first, so the sign-in group does not repeat it; a client with the Claude flow would list Anthropic there
  assert.deepEqual(global.signIn.map((p) => p.id), [])
  assert.deepEqual(waysOn(catalogue, 'global', ['oauth-claude']).signIn.map((p) => p.id), ['anthropic'])
  assert.ok(!global.rest.some((p) => p.id === 'bailian'))
  // the region: the relay's word first, the UI language as the hint without one
  assert.equal(regionOf('cn', 'en'), 'cn')
  assert.equal(regionOf('intl', 'zh-CN'), 'global')
  assert.equal(regionOf(undefined, 'zh-CN'), 'cn')
  assert.equal(regionOf('', 'en-US'), 'global')
})

test('the gate: capabilities are the union of what is configured; the unavailable sentence names the catalogue’s providers for the region', () => {
  assert.deepEqual([...capabilitiesOf([])], [])
  assert.deepEqual([...capabilitiesOf([{ id: 'deepseek', label: 'DeepSeek', capabilities: ['chat', 'vision'] }, { id: 'chatgpt', label: 'ChatGPT', capabilities: ['chat', 'vision'] }])].sort(), ['chat', 'vision'])
  assert.ok(capabilitiesOf([{ id: 'bailian', label: 'Bailian', capabilities: ['chat', 'vision', 'image', 'video'] }]).has('video'))
  assert.deepEqual(providersWith(catalogue, 'video', 'cn').map((p) => p.id), ['bailian'])
  assert.deepEqual(providersWith(catalogue, 'video', 'global').map((p) => p.id), [])
  assert.ok(providersWith(catalogue, 'image', 'global').map((p) => p.id).includes('openrouter'))
  assert.ok(!providersWith(catalogue, 'image', 'global').map((p) => p.id).includes('custom'))
  // which sentence: nothing when something has it; the capability's own; with only the ChatGPT sign-in, pictures and clips are not covered by it
  const nothing = { capabilities: [], configured: [], cloud: { signedIn: false }, chatgpt: { signedIn: false } }
  assert.equal(unavailableKey(nothing, 'chat'), 'ownKeyNoChat')
  assert.equal(unavailableKey(nothing, 'vision'), 'ownKeyNoVision')
  assert.equal(unavailableKey(nothing, 'image'), 'ownKeyNoImage')
  assert.equal(unavailableKey(nothing, 'video'), 'ownKeyNoVideo')
  const onlyChatGpt = { capabilities: ['chat', 'vision'], configured: [{ provider: 'chatgpt' }], cloud: { signedIn: false }, chatgpt: { signedIn: true } }
  assert.equal(chatGptOnly(onlyChatGpt), true)
  assert.equal(unavailableKey(onlyChatGpt, 'image'), 'ownKeyChatGptNoMedia')
  assert.equal(unavailableKey(onlyChatGpt, 'video'), 'ownKeyChatGptNoMedia')
  assert.equal(unavailableKey(onlyChatGpt, 'vision'), null)
  // a DeepSeek key beside the sign-in: the plain sentence again; the account signed in: not "only"
  assert.equal(unavailableKey({ ...onlyChatGpt, configured: [{ provider: 'chatgpt' }, { provider: 'deepseek' }] }, 'image'), 'ownKeyNoImage')
  assert.equal(chatGptOnly({ ...onlyChatGpt, cloud: { signedIn: true } }), false)
  assert.equal(unavailableKey({ ...onlyChatGpt, capabilities: ['chat', 'vision', 'image', 'video'] }, 'video'), null)
  // the first run's own-key step: done with a key or a finished sign-in
  assert.equal(ownKeyStepDone(nothing), false)
  assert.equal(ownKeyStepDone(onlyChatGpt), true)
  assert.equal(ownKeyStepDone({ configured: [{ provider: 'bailian' }], chatgpt: { signedIn: false } }), true)
})

test('models: the endpoint’s list sorted into chat, image and video by id; sighted by name or the hands default; the row carries only chat models and never a key', () => {
  const bailian = catalogue.find((p) => p.id === 'bailian')
  assert.equal(kindOf('qwen-image-3.0'), 'image')
  assert.equal(kindOf('wan2.2-i2v-flash'), 'video')
  assert.equal(kindOf('deepseek-v4.1-flash'), 'chat')
  assert.equal(sighted(bailian, 'qwen3.8-27b'), true)
  assert.equal(sighted(bailian, 'qwen-vl-max'), true)
  assert.equal(sighted(bailian, 'deepseek-v4-pro'), false)
  assert.equal(sighted(catalogue.find((p) => p.id === 'ollama'), 'qwen3:8b'), false)
  const listed = modelsOf(bailian, ['deepseek-v4.1-flash', 'qwen3.8-27b', 'qwen-image-3.0', 'wan2.2-i2v-flash', 'qwen3.8-27b'])
  assert.deepEqual(listed.map((m) => [m.id, m.kind, m.vision]), [['deepseek-v4.1-flash', 'chat', false], ['qwen3.8-27b', 'chat', true], ['qwen-image-3.0', 'image', false], ['wan2.2-i2v-flash', 'video', false]])
  // no list from the endpoint: the catalogue's defaults stand in
  assert.deepEqual(modelsOf(bailian, []).map((m) => m.id), ['deepseek-v4.1-flash', 'qwen3.8-27b', 'qwen-image-3.0', 'wan2.2-i2v-flash'])
  // a provider without image capability does not get an image model from a list that names one
  const deepseek = catalogue.find((p) => p.id === 'deepseek')
  assert.deepEqual(modelsOf(deepseek, ['deepseek-flash', 'some-image-model']).map((m) => m.id), ['deepseek-flash'])
  const row = ownProviderRow({ provider: 'bailian', label: 'Alibaba Cloud Bailian', protocol: 'openai', baseURL: bailian.base_url, keyRef: keyRefFor('bailian'), capabilities: bailian.capabilities, models: listed, at: 1 })
  assert.equal(row.api, 'openai-completions')
  assert.equal(row.apiKeyEnv, 'NANOMUSE_KEY_BAILIAN')
  assert.equal(row.apiKey, undefined)
  assert.deepEqual(row.models.map((m) => [m.id, m.input]), [['deepseek-v4.1-flash', ['text']], ['qwen3.8-27b', ['text', 'image']]])
  // a local server without a key names no credential
  assert.equal('apiKeyEnv' in ownProviderRow({ provider: 'ollama', label: 'Ollama', protocol: 'openai', baseURL: 'http://127.0.0.1:11434/v1', keyRef: '', capabilities: ['chat'], models: [], at: 1 }), false)
  // protocols → pi-ai apis; Gemini's compatible layer is OpenAI's shape
  assert.equal(apiOf('anthropic'), 'anthropic-messages')
  assert.equal(apiOf('gemini', 'https://generativelanguage.googleapis.com/v1beta/openai'), 'openai-completions')
  assert.equal(apiOf('gemini', 'https://generativelanguage.googleapis.com/v1beta'), 'google-generative-ai')
  assert.equal(apiOf('openai-responses'), 'openai-responses')
  assert.equal(keyRefFor('lm-studio'), 'NANOMUSE_KEY_LM_STUDIO')
})

test('listModels: OpenAI’s shape with the bearer, Anthropic’s with x-api-key, Gemini’s native with ?key=; a refusal or a hang gives an empty list', async () => {
  const calls = []
  const fetchImpl = async (url, init) => {
    calls.push([url, init.headers ?? {}])
    if (url.includes('anthropic')) return new Response(JSON.stringify({ data: [{ id: 'claude-sonnet-5-5' }] }), { status: 200 })
    if (url.includes('googleapis.com/v1beta/models')) return new Response(JSON.stringify({ models: [{ name: 'models/gemini-3.8-flash' }] }), { status: 200 })
    if (url.includes('refuse')) return new Response('{"error":"no"}', { status: 401 })
    return new Response(JSON.stringify({ data: [{ id: 'b-model' }, { id: 'a-model' }] }), { status: 200 })
  }
  assert.deepEqual(await listModels('openai', 'https://api.deepseek.com/v1/', 'sk-x', fetchImpl), ['a-model', 'b-model'])
  assert.equal(calls[0][0], 'https://api.deepseek.com/v1/models')
  assert.equal(calls[0][1].authorization, 'Bearer sk-x')
  assert.deepEqual(await listModels('anthropic', 'https://api.anthropic.com', 'sk-ant', fetchImpl), ['claude-sonnet-5-5'])
  assert.equal(calls[1][1]['x-api-key'], 'sk-ant')
  assert.deepEqual(await listModels('gemini', 'https://generativelanguage.googleapis.com/v1beta', 'AIza', fetchImpl), ['gemini-3.8-flash'])
  assert.ok(calls[2][0].includes('key=AIza'))
  assert.deepEqual(await listModels('openai', 'https://refuse.example/v1', 'k', fetchImpl), [])
  assert.deepEqual(await listModels('openai', 'https://slow.example/v1', 'k', () => new Promise(() => undefined), 20), [])
})

test('LineReader: one event per line, a partial line waits, the runtime’s own logging between events is skipped', () => {
  const r = new LineReader()
  assert.deepEqual(r.push('{"event":"url","url":"https://a"}\nnot json\n{"event":"wai'), [{ event: 'url', url: 'https://a' }])
  assert.deepEqual(r.push('ting"}\n{"nope":1}\n'), [{ event: 'waiting' }])
  assert.deepEqual(r.push(Buffer.from('{"event":"done","ok":true}\n')), [{ event: 'done', ok: true }])
})

/** A child the tests drive: stdout/stderr emitters, an exit, a kill that exits. */
function fakeChild() {
  const child = new EventEmitter()
  child.stdout = new EventEmitter()
  child.stderr = new EventEmitter()
  child.killed = false
  child.kill = () => {
    child.killed = true
    setTimeout(() => child.emit('exit', null), 0)
    return true
  }
  child.say = (obj) => child.stdout.emit('data', Buffer.from(JSON.stringify(obj) + '\n'))
  return child
}

function desk(extra = {}) {
  const spawned = []
  const ready = []
  const changes = []
  const d = new ChatGptDesk({
    command: async () => extra.noRuntime ? undefined : '/opt/nanomuse',
    spawn: (command, args) => {
      const child = fakeChild()
      spawned.push({ command, args, child })
      return child
    },
    onReady: async (url, token, models) => { ready.push({ url, token, models }) },
    onSignedOut: () => changes.push('signed-out'),
    onChange: () => changes.push('change'),
    log: () => undefined,
    restartMs: 5,
    restartMaxMs: 20,
    readyTimeoutMs: 200,
    ...extra.options,
  })
  return { d, spawned, ready, changes }
}

const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms))

test('ChatGPT sign-in: login prints the URL, then done starts the proxy; ready writes the row; an exit restarts it; logout stops it and runs the runtime’s logout', async () => {
  const { d, spawned, ready } = desk()
  assert.equal(d.login.status, 'idle')
  const urlPromise = d.beginLogin()
  await tick()
  assert.deepEqual(spawned[0].args, ['chatgpt', 'login', '--json'])
  assert.equal(d.login.status, 'waiting')
  spawned[0].child.stderr.emit('data', Buffer.from('OpenAI’s terms cover…\n'))
  spawned[0].child.say({ event: 'url', url: 'https://auth.openai.com/oauth/authorize?x', callback: 'http://localhost:1455/auth/callback', expires_in: 600 })
  assert.equal(await urlPromise, 'https://auth.openai.com/oauth/authorize?x')
  assert.equal(d.login.url, 'https://auth.openai.com/oauth/authorize?x')
  // asking again while waiting gives the same URL, no second child
  assert.equal(await d.beginLogin(), 'https://auth.openai.com/oauth/authorize?x')
  assert.equal(spawned.length, 1)
  spawned[0].child.say({ event: 'waiting' })
  spawned[0].child.say({ event: 'done', ok: true, label: 'ChatGPT Plus', plan: 'plus', account_id: 'opaque', expires_at: 1760000000 })
  spawned[0].child.emit('exit', 0)
  await tick()
  assert.equal(d.login.status, 'done')
  assert.equal(d.login.label, 'ChatGPT Plus')
  assert.equal(d.running, true)
  assert.deepEqual(spawned[1].args, ['chatgpt', 'proxy', '--json'])
  spawned[1].child.say({ event: 'ready', url: 'http://127.0.0.1:41235/v1/', token: 'local-token', label: 'ChatGPT Plus', models: ['gpt-5.6-sol', 'gpt-5.4'] })
  await tick()
  assert.deepEqual(ready, [{ url: 'http://127.0.0.1:41235/v1', token: 'local-token', models: ['gpt-5.6-sol', 'gpt-5.4'] }])
  assert.deepEqual(d.ready, { url: 'http://127.0.0.1:41235/v1', token: 'local-token' })
  // the proxy dies: started again after the delay, the row rewritten with the new port
  spawned[1].child.say({ event: 'exit', reason: 'error', message: 'upstream closed' })
  spawned[1].child.emit('exit', 1)
  assert.equal(d.ready, undefined)
  await tick(15)
  assert.equal(spawned.length, 3)
  spawned[2].child.say({ event: 'ready', url: 'http://127.0.0.1:41299/v1', token: 't2', models: [] })
  await tick()
  assert.equal(ready.length, 2)
  assert.equal(ready[1].url, 'http://127.0.0.1:41299/v1')
  // logout: the proxy is killed and stays down; the runtime's logout runs
  const out = d.logout()
  await tick()
  assert.equal(spawned[2].child.killed, true)
  assert.deepEqual(spawned[3].args, ['chatgpt', 'logout'])
  spawned[3].child.emit('exit', 0)
  await out
  assert.equal(d.running, false)
  assert.equal(d.login.status, 'idle')
  await tick(30)
  assert.equal(spawned.length, 4)
})

test('ChatGPT sign-in: the runtime’s error ends the login with its code; no runtime is no_runtime; not_signed_in from the proxy gives up and says so', async () => {
  const { d, spawned } = desk()
  const p = d.beginLogin()
  await tick()
  spawned[0].child.say({ event: 'error', message: 'Port 1455 is busy', code: 'port_busy' })
  await assert.rejects(p, /Port 1455 is busy/)
  assert.equal(d.login.status, 'error')
  assert.equal(d.login.error, 'Port 1455 is busy')
  // a login that exits without a result
  const p2 = d.beginLogin()
  await tick()
  spawned[1].child.say({ event: 'url', url: 'https://auth' })
  await p2
  spawned[1].child.emit('exit', 1)
  await tick()
  assert.equal(d.login.status, 'error')
  // cancel from a waiting state
  const p3 = d.beginLogin()
  await tick()
  spawned[2].child.say({ event: 'url', url: 'https://auth' })
  await p3
  d.cancelLogin()
  assert.equal(d.login.status, 'idle')
  assert.equal(spawned[2].child.killed, true)
  // the proxy says the store is gone
  const gone = desk()
  gone.d.start()
  await tick()
  gone.spawned[0].child.say({ event: 'error', code: 'not_signed_in', message: 'run nanomuse chatgpt login' })
  gone.spawned[0].child.emit('exit', 1)
  await tick(30)
  assert.ok(gone.changes.includes('signed-out'))
  assert.equal(gone.d.running, false)
  assert.equal(gone.spawned.length, 1)
  // no runtime
  const none = desk({ noRuntime: true })
  await assert.rejects(none.d.beginLogin(), /no_runtime/)
  assert.equal(none.d.login.error, 'no_runtime')
  assert.equal(await none.d.status(), undefined)
})

test('ChatGPT status: the runtime’s one JSON line, read without the network', async () => {
  const { d, spawned } = desk()
  const p = d.status()
  await tick()
  assert.deepEqual(spawned[0].args, ['chatgpt', 'status', '--json'])
  spawned[0].child.stdout.emit('data', Buffer.from('{"signed_in":true,"label":"ChatGPT Pro","plan":"pro","models":["gpt-5.6-sol"]}\n'))
  spawned[0].child.emit('exit', 0)
  assert.deepEqual(await p, { signedIn: true, label: 'ChatGPT Pro' })
})

test('typedModelIds: a comma- or newline-separated field or a list, trimmed, without doubles, capped', () => {
  assert.deepEqual(typedModelIds('glm-4.7, kimi-k2.5\n glm-4.7 ,, '), ['glm-4.7', 'kimi-k2.5'])
  assert.deepEqual(typedModelIds(['a', ' b ', 'a', '']), ['a', 'b'])
  assert.deepEqual(typedModelIds(undefined), [])
  assert.deepEqual(typedModelIds(42), [])
  assert.deepEqual(typedModelIds('x'.repeat(121)), [])
  assert.equal(typedModelIds(Array.from({ length: 50 }, (_, i) => `m${i}`)).length, 40)
})
