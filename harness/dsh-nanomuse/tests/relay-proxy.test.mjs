// The loopback door to the relay (src/relay-proxy.ts, relay 0.31): the model adapter's
// request is sent on with the headers the hook announced for it, the device and the
// platform always, and the account's key; the relay's reply streams back as it came, with
// the id it gave the turn; anything without the account's own key is a 401 here.
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { test } from 'node:test'
import { RelayProxy } from '../lib/relay-proxy.js'

/** A relay that remembers what it was asked and answers as told. */
async function upstream() {
  const u = { requests: [], answer: undefined }
  u.server = createServer((req, res) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      u.requests.push({ method: req.method, url: req.url, headers: req.headers, body: Buffer.concat(chunks).toString('utf8') })
      const answer = u.answer ?? { status: 200, headers: { 'content-type': 'application/json' }, body: '{"ok":true}' }
      res.writeHead(answer.status, { 'x-nanomuse-request': 'req-7', ...answer.headers })
      if (answer.sse) {
        res.flushHeaders()
        let i = 0
        const tick = setInterval(() => {
          res.write(answer.sse[i])
          i += 1
          if (i >= answer.sse.length) {
            clearInterval(tick)
            res.end()
          }
        }, 5)
        return
      }
      res.end(answer.body)
    })
  })
  await new Promise((resolve) => u.server.listen(0, '127.0.0.1', resolve))
  u.origin = `http://127.0.0.1:${u.server.address().port}`
  u.close = () => new Promise((resolve) => u.server.close(resolve))
  return u
}

async function door(u, { token = 'nm_live_key', claim = () => undefined, noteTurn = () => undefined } = {}) {
  const logs = []
  const proxy = new RelayProxy({
    origin: () => u.origin,
    token: async () => token,
    device: () => 'pc-dsh-0001',
    claim,
    noteTurn,
    log: (level, text) => logs.push(`${level}: ${text}`),
  })
  await proxy.listen()
  return { proxy, logs }
}

const body = JSON.stringify({ model: 'nanomuse-chat', messages: [{ role: 'user', content: 'hello' }], stream: true })

test('a request with the account\'s key is sent on with the device, the platform and the announced provenance; the reply comes back with the turn\'s id', async () => {
  const u = await upstream()
  const noted = []
  const claimed = []
  const { proxy } = await door(u, {
    claim: (b) => {
      claimed.push(b)
      return { sessionId: 'sess-1', headers: { 'x-nanomuse-conversation': 'sess-1', 'x-nanomuse-run': 'schedule', 'x-nanomuse-turn': '4', 'x-nanomuse-step': '2' } }
    },
    noteTurn: (sessionId, id) => noted.push([sessionId, id]),
  })
  try {
    assert.match(proxy.openaiBase, /^http:\/\/127\.0\.0\.1:\d+\/v1$/)
    const res = await fetch(`${proxy.openaiBase}/chat/completions`, {
      method: 'POST',
      headers: { authorization: 'Bearer nm_live_key', 'content-type': 'application/json', 'x-stainless-retry-count': '0', 'x-secret': 'not forwarded' },
      body,
    })
    assert.equal(res.status, 200)
    assert.equal(res.headers.get('x-nanomuse-request'), 'req-7')
    assert.deepEqual(await res.json(), { ok: true })
    assert.equal(u.requests.length, 1)
    const sent = u.requests[0]
    assert.equal(sent.method, 'POST')
    assert.equal(sent.url, '/v1/chat/completions')
    assert.equal(sent.body, body)
    assert.equal(sent.headers.authorization, 'Bearer nm_live_key')
    assert.equal(sent.headers['x-nanomuse-device'], 'pc-dsh-0001')
    assert.equal(sent.headers['x-nanomuse-platform'], 'desktop')
    assert.equal(sent.headers['x-nanomuse-conversation'], 'sess-1')
    assert.equal(sent.headers['x-nanomuse-run'], 'schedule')
    assert.equal(sent.headers['x-nanomuse-turn'], '4')
    assert.equal(sent.headers['x-nanomuse-step'], '2')
    assert.equal(sent.headers['x-stainless-retry-count'], '0')
    assert.equal(sent.headers['x-secret'], undefined)
    assert.equal(claimed[0].model, 'nanomuse-chat')
    assert.deepEqual(noted, [['sess-1', 'req-7']])
    assert.equal(proxy.forwarded, 1)
  } finally {
    await proxy.close()
    await u.close()
  }
})

test('a streamed reply comes back chunk by chunk, with the relay\'s own headers', async () => {
  const u = await upstream()
  u.answer = { status: 200, headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' }, sse: [': queue 2\n\n', 'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n', 'data: [DONE]\n\n'] }
  const { proxy } = await door(u)
  try {
    const res = await fetch(`${proxy.openaiBase}/chat/completions`, { method: 'POST', headers: { authorization: 'Bearer nm_live_key', 'content-type': 'application/json' }, body })
    assert.equal(res.status, 200)
    assert.equal(res.headers.get('content-type'), 'text/event-stream')
    assert.equal(res.headers.get('cache-control'), 'no-cache')
    const seen = []
    for await (const chunk of res.body) seen.push(Buffer.from(chunk).toString('utf8'))
    assert.ok(seen.length >= 2, 'arrived in more than one piece')
    assert.equal(seen.join(''), ': queue 2\n\ndata: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n')
  } finally {
    await proxy.close()
    await u.close()
  }
})

test('the relay\'s refusal comes back with its status and body; a request nothing claimed goes out with the device and the platform only', async () => {
  const u = await upstream()
  u.answer = { status: 402, headers: { 'content-type': 'application/json', 'retry-after': '30' }, body: '{"error":{"code":"allowance_spent","message":"Nothing left today."}}' }
  const { proxy } = await door(u)
  try {
    const res = await fetch(`${proxy.openaiBase}/chat/completions`, { method: 'POST', headers: { authorization: 'Bearer nm_live_key', 'content-type': 'application/json' }, body })
    assert.equal(res.status, 402)
    assert.equal(res.headers.get('retry-after'), '30')
    assert.equal((await res.json()).error.code, 'allowance_spent')
    const sent = u.requests[0]
    assert.equal(sent.headers['x-nanomuse-device'], 'pc-dsh-0001')
    assert.equal(sent.headers['x-nanomuse-platform'], 'desktop')
    assert.equal(sent.headers['x-nanomuse-run'], undefined)
    assert.equal(sent.headers['x-nanomuse-conversation'], undefined)
  } finally {
    await proxy.close()
    await u.close()
  }
})

test('without the account\'s own key nothing goes through: another key, no key, signed out; and nothing outside /v1', async () => {
  const u = await upstream()
  const { proxy } = await door(u)
  try {
    const other = await fetch(`${proxy.openaiBase}/chat/completions`, { method: 'POST', headers: { authorization: 'Bearer nm_live_kez', 'content-type': 'application/json' }, body })
    assert.equal(other.status, 401)
    assert.equal((await other.json()).error.code, 'bad_key')
    const none = await fetch(`${proxy.openaiBase}/models`)
    assert.equal(none.status, 401)
    const elsewhere = await fetch(`http://127.0.0.1:${proxy.port}/`, { headers: { authorization: 'Bearer nm_live_key' } })
    assert.equal(elsewhere.status, 404)
    assert.equal(u.requests.length, 0)
  } finally {
    await proxy.close()
  }
  const out = await door(u, { token: '' })
  try {
    const res = await fetch(`${out.proxy.openaiBase}/models`, { headers: { authorization: 'Bearer nm_live_key' } })
    assert.equal(res.status, 401)
  } finally {
    await out.proxy.close()
    await u.close()
  }
})

test('a GET is sent on without a body; a relay that is away is a 502 with the offline code, not a hang', async () => {
  const u = await upstream()
  const { proxy, logs } = await door(u)
  try {
    const res = await fetch(`${proxy.openaiBase}/models`, { headers: { authorization: 'Bearer nm_live_key' } })
    assert.equal(res.status, 200)
    assert.equal(u.requests[0].method, 'GET')
    assert.equal(u.requests[0].body, '')
    await u.close()
    const gone = await fetch(`${proxy.openaiBase}/models`, { headers: { authorization: 'Bearer nm_live_key' } })
    assert.equal(gone.status, 502)
    assert.equal((await gone.json()).error.code, 'offline')
    assert.ok(logs.some((l) => l.startsWith('warn: nanomuse relay door')))
  } finally {
    await proxy.close()
  }
  assert.equal(proxy.openaiBase, '')
})

test('listen(preferred) opens on last start\'s port when it is free and gives way, with a note in the log, when it is not', async () => {
  const u = await upstream()
  const first = await door(u)
  const port = first.proxy.port
  await first.proxy.close()
  const again = new RelayProxy({ origin: () => u.origin, token: async () => 'k', device: () => 'd', claim: () => undefined })
  await again.listen(port)
  try {
    assert.equal(again.port, port)
  } finally {
    await again.close()
  }
  const squatter = createServer()
  await new Promise((resolve) => squatter.listen(port, '127.0.0.1', resolve))
  const logs = []
  const other = new RelayProxy({ origin: () => u.origin, token: async () => 'k', device: () => 'd', claim: () => undefined, log: (level, text) => logs.push(`${level}: ${text}`) })
  try {
    await other.listen(port)
    assert.ok(other.port > 0 && other.port !== port)
    assert.ok(logs.some((l) => l.startsWith(`info: nanomuse relay door: port ${port} is taken`)))
    const res = await fetch(`${other.openaiBase}/models`, { headers: { authorization: 'Bearer k' } })
    assert.equal(res.status, 200, 'the door works on the other port')
  } finally {
    await other.close()
    await new Promise((resolve) => squatter.close(resolve))
    await u.close()
  }
})
