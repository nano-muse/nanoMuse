// The relay client against a fake relay: the wire shapes the desktop depends on.
// Run with `pnpm test` after `pnpm build` (the test imports the built lib/).
import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'

import { Relay, RelayError } from '../lib/relay.js'

/** A relay that remembers what it was asked and answers like the real one. */
function fakeRelay() {
  const seen = []
  const server = createServer(async (req, res) => {
    const chunks = []
    for await (const chunk of req) chunks.push(chunk)
    const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : null
    seen.push({ method: req.method, url: req.url, auth: req.headers.authorization ?? null, body })
    const json = (status, payload) => {
      res.writeHead(status, { 'content-type': 'application/json' })
      res.end(payload === undefined ? '' : JSON.stringify(payload))
    }
    if (req.url === '/v1/auth/code') return json(204)
    if (req.url === '/v1/auth/verify') {
      if (body.code !== '123456') return json(400, { error: { code: 'bad_code', message: 'That code is not right.' } })
      return json(200, {
        api_key: 'sk-test-device-key',
        created: true,
        account: { id: 'acc_1', channel: 'email', hint: 'de***@example.com', member: false },
        tokens: { unlimited: false, granted: 1000, used: 10, remaining: 990 },
      })
    }
    if (req.url === '/v1/me') {
      if (req.headers.authorization !== 'Bearer sk-test-device-key') return json(401, { error: { code: 'unauthorized', message: 'no' } })
      return json(200, {
        account: { id: 'acc_1', channel: 'email', hint: 'de***@example.com', member: true },
        tokens: { unlimited: true, granted: 0, used: 30605, remaining: 0 },
        contribute: { on: true, samples: 2, default_on: true, privacy_url: 'https://nanomuse.cn/privacy/' },
      })
    }
    if (req.url === '/v1/me/contribute') return json(200, { on: body.on, samples: 2, default_on: true, privacy_url: 'https://nanomuse.cn/privacy/' })
    if (req.url === '/v1/me/samples' && req.method === 'DELETE') return json(200, { deleted: 2 })
    if (req.url === '/v1/models') {
      return json(200, {
        data: [
          { id: 'qwen-a', name: 'Qwen A', architecture: { input_modalities: ['text', 'image'] }, nanomuse: { kind: 'chat', recommended: true, recommended_for: ['chat', 'gui'] } },
          { id: 'wan-v', name: 'Wan (video)', architecture: { input_modalities: ['text'] }, nanomuse: { kind: 'video', recommended: false } },
          { id: 'bare' },
        ],
      })
    }
    if (req.url === '/v1/auth/sign-out') return json(401, { error: { code: 'unauthorized', message: 'already gone' } })
    if (req.url === '/v1/auth/login') {
      if (body.password !== 'correct horse') return json(401, { error: { code: 'password_wrong', message: 'That password is not right.' } })
      return json(200, {
        api_key: 'sk-test-device-key',
        account: { id: 'acc_1', channel: 'phone', hint: '138****0000', member: false },
        tokens: { unlimited: false, granted: 1000, used: 10, remaining: 990 },
      })
    }
    if (req.url === '/v1/me/invite') {
      if (req.headers.authorization !== 'Bearer sk-test-device-key') return json(401, { error: { code: 'unauthorized', message: 'no' } })
      return json(200, { code: 'ABCD12', url: 'https://nanomuse.cn/i/ABCD12', invites: 2, bonus_cny: 5, earned_cny: 10 })
    }
    if (req.url?.startsWith('/v1/me/profile')) {
      if (req.headers.authorization !== 'Bearer sk-test-device-key') return json(401, { error: { code: 'unauthorized', message: 'no' } })
      return json(200, { rev: 3, device: 'desk', name: '豆沙包', avatar: 'dragon', emoji: '', color: '#2F6DB5', style: '', description: '', has_face: false, face_id: '' })
    }
    json(404, { error: { code: 'not_found', message: 'nothing here' } })
  })
  return { server, seen }
}

let relay
let seen
let server

before(async () => {
  ;({ server, seen } = fakeRelay())
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  relay = new Relay(`http://127.0.0.1:${server.address().port}/`)
})

after(() => server.close())

test('origin is normalised and the OpenAI root hangs off it', () => {
  assert.equal(relay.origin.endsWith('/'), false)
  assert.equal(relay.openaiBase, `${relay.origin}/v1`)
})

test('requestCode posts the identifier and accepts 204', async () => {
  await relay.requestCode('dev-a@example.com')
  const last = seen.at(-1)
  assert.equal(last.method, 'POST')
  assert.equal(last.url, '/v1/auth/code')
  assert.deepEqual(last.body, { identifier: 'dev-a@example.com' })
})

test('verify trims the code, caps the device name and maps the key', async () => {
  const signIn = await relay.verify('dev-a@example.com', ' 123456 ', 'x'.repeat(120))
  assert.equal(signIn.apiKey, 'sk-test-device-key')
  assert.equal(signIn.created, true)
  assert.equal(signIn.account.hint, 'de***@example.com')
  assert.equal(signIn.account.tokens.remaining, 990)
  const last = seen.at(-1)
  assert.equal(last.body.code, '123456')
  assert.equal(last.body.device.length, 80)
})

test('a relay error carries the relay code and message', async () => {
  await assert.rejects(relay.verify('dev-a@example.com', '000000', 'desk'), (err) => {
    assert.ok(err instanceof RelayError)
    assert.equal(err.status, 400)
    assert.equal(err.code, 'bad_code')
    assert.equal(err.message, 'That code is not right.')
    return true
  })
})

test('me sends the bearer key and reads the allowance', async () => {
  const account = await relay.me('sk-test-device-key')
  assert.equal(seen.at(-1).auth, 'Bearer sk-test-device-key')
  assert.equal(account.member, true)
  assert.equal(account.tokens.unlimited, true)
  await assert.rejects(relay.me('sk-wrong'), (err) => err instanceof RelayError && err.status === 401)
})

test('models keeps kind, recommendation and modalities, with defaults', async () => {
  const models = await relay.models('sk-test-device-key')
  assert.deepEqual(
    models.map((m) => [m.id, m.kind, m.recommended, m.inputModalities]),
    [
      ['qwen-a', 'chat', true, ['text', 'image']],
      ['wan-v', 'video', false, ['text']],
      ['bare', 'chat', false, ['text']],
    ],
  )
  assert.deepEqual(models[0].recommendedFor, ['chat', 'gui'])
  assert.equal(models[2].name, 'bare')
})

test('signOut tolerates a key the relay no longer knows', async () => {
  await relay.signOut('sk-test-device-key')
  assert.equal(seen.at(-1).url, '/v1/auth/sign-out')
})

test('data controls: me carries the switch, setContribute and deleteSamples speak relay 0.9', async () => {
  const account = await relay.me('sk-test-device-key')
  assert.deepEqual(account.contribute, { on: true, samples: 2, defaultOn: true, privacyUrl: 'https://nanomuse.cn/privacy/' })
  const off = await relay.setContribute('sk-test-device-key', false)
  assert.equal(seen.at(-1).url, '/v1/me/contribute')
  assert.deepEqual(seen.at(-1).body, { on: false })
  assert.equal(off.on, false)
  assert.equal(off.samples, 2)
  assert.equal(await relay.deleteSamples('sk-test-device-key'), 2)
  assert.equal(seen.at(-1).method, 'DELETE')
  assert.equal(seen.at(-1).url, '/v1/me/samples')
})

test('login posts the password and maps the key; a wrong one carries the relay code', async () => {
  const signIn = await relay.login('13800138000', 'correct horse', 'desk')
  assert.equal(signIn.apiKey, 'sk-test-device-key')
  assert.equal(signIn.created, false)
  assert.equal(signIn.account.hint, '138****0000')
  const last = seen.at(-1)
  assert.equal(last.method, 'POST')
  assert.equal(last.url, '/v1/auth/login')
  assert.deepEqual(last.body, { identifier: '13800138000', password: 'correct horse', device: 'desk' })
  await assert.rejects(relay.login('13800138000', 'wrong', 'desk'), (err) => err instanceof RelayError && err.status === 401 && err.code === 'password_wrong')
})

test('invite is a GET with the bearer key and reads code, link and bonus', async () => {
  const invite = await relay.invite('sk-test-device-key')
  const last = seen.at(-1)
  assert.equal(last.method, 'GET')
  assert.equal(last.url, '/v1/me/invite')
  assert.equal(last.auth, 'Bearer sk-test-device-key')
  assert.deepEqual(invite, { code: 'ABCD12', url: 'https://nanomuse.cn/i/ABCD12', invites: 2, bonusCny: 5, earnedCny: 10 })
  await assert.rejects(relay.invite('sk-wrong'), (err) => err instanceof RelayError && err.status === 401)
})

test('profile asks for the face only when told and maps the account\'s look', async () => {
  const small = await relay.profile('sk-test-device-key', false)
  assert.equal(seen.at(-1).url, '/v1/me/profile?face=false')
  assert.equal(small.name, '豆沙包')
  assert.equal(small.avatar, 'dragon')
  assert.equal(small.rev, 3)
  assert.equal(small.hasFace, false)
  assert.equal('face' in small, false)
  await relay.profile('sk-test-device-key', true)
  assert.equal(seen.at(-1).url, '/v1/me/profile?face=true')
})

test('putConnectors writes this device’s connections alone — never the look it happens to wear', async () => {
  const rows = [{ id: 'gh', label: 'GitHub', url: 'https://mcp.example/gh', auth: 'key', device: 'Desk', device_id: 'desk-1', enabled: true, at: '2026-10-05T00:00:00Z' }]
  const rev = await relay.putConnectors('sk-test-device-key', rows, 'desk-1', 'desk-1')
  const last = seen.at(-1)
  assert.equal(rev, 3)
  assert.equal(last.method, 'PUT')
  assert.equal(last.url, '/v1/me/profile')
  assert.deepEqual(Object.keys(last.body).sort(), ['connectors', 'device', 'device_id'])
  assert.deepEqual(last.body.connectors, rows)
  assert.equal('name' in last.body, false)
  assert.equal('avatar' in last.body, false)
})

test('every call has a deadline: a relay that never answers is given up; a caller signal still cancels; the images get the long budget', async () => {
  const seen = []
  const hang = (url, init) =>
    new Promise((_resolve, reject) => {
      seen.push(init)
      init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true })
    })
  const relay = new Relay('https://relay.test', hang, 20)
  const started = Date.now()
  await assert.rejects(relay.config(), { name: 'TimeoutError', message: 'Relay.config timed out after 20 ms' })
  assert.ok(Date.now() - started < 2000)

  const controller = new AbortController()
  const pending = relay.meSheet('nm_key', controller.signal)
  controller.abort(new Error('stopped'))
  await assert.rejects(pending, /stopped/)

  // the image routes carry their own, longer budget: with the default at 20 ms a hang is still there after 60 ms
  const image = relay.generateImage('nm_key', 'm', 'a cat')
  let settled = false
  image.then(() => (settled = true), () => (settled = true))
  await new Promise((r) => setTimeout(r, 60))
  assert.equal(settled, false)
  assert.equal(seen.at(-1).timeoutMs, undefined, 'the budget is taken off the init before fetch sees it')
  assert.equal('operation' in seen[0], false)
})
