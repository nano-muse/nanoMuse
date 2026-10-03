// The connectors' conversation with a remote MCP server: what a server's first
// answer means (open, a key, the authorization flow), the tool list it gives,
// and the switches applied to a `tools/list` answer in either framing.
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { test } from 'node:test'
import { filterToolsList, listTools, parseChallenge, probeAuth, slug } from '../lib/connectors.js'

/** A throwaway MCP server: `mode` says how it lets a client in. */
async function serve(mode) {
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1')
    const base = `http://127.0.0.1:${server.address().port}`
    const json = (status, body, headers = {}) => { res.writeHead(status, { 'content-type': 'application/json', ...headers }); res.end(JSON.stringify(body)) }
    // only the OAuth server publishes metadata; the probe falls back to the well-known paths when the challenge names none
    if (mode === 'oauth' && url.pathname === '/.well-known/oauth-protected-resource/mcp') return json(200, { resource: `${base}/mcp`, authorization_servers: [base], scopes_supported: ['mcp:tools'] })
    if (mode === 'oauth' && url.pathname === '/.well-known/oauth-authorization-server') return json(200, { issuer: base, authorization_endpoint: `${base}/authorize`, token_endpoint: `${base}/token`, registration_endpoint: `${base}/register`, code_challenge_methods_supported: ['S256'] })
    if (url.pathname !== '/mcp') return json(404, {})
    if (mode === 'oauth' && !req.headers.authorization) { res.writeHead(401, { 'www-authenticate': `Bearer resource_metadata="${base}/.well-known/oauth-protected-resource/mcp"` }); return res.end() }
    if (mode === 'key' && req.headers.authorization !== 'Bearer k') { res.writeHead(401, { 'www-authenticate': 'Bearer error="invalid_token", error_description="Bring a key"' }); return res.end() }
    if (req.method === 'DELETE') { res.writeHead(200); return res.end() }
    const chunks = []
    for await (const c of req) chunks.push(c)
    const msg = JSON.parse(Buffer.concat(chunks).toString() || '{}')
    if (msg.method === 'notifications/initialized') { res.writeHead(202); return res.end() }
    if (msg.method === 'initialize') return json(200, { jsonrpc: '2.0', id: msg.id, result: { protocolVersion: '2025-06-18', capabilities: { tools: {} }, serverInfo: { name: 't', version: '0' } } }, { 'mcp-session-id': 's1' })
    if (msg.method === 'tools/list') {
      // the second page comes as SSE, to cover both framings
      if (msg.params?.cursor === 'two') { res.writeHead(200, { 'content-type': 'text/event-stream' }); return res.end(`event: message\ndata: ${JSON.stringify({ jsonrpc: '2.0', id: msg.id, result: { tools: [{ name: 'c', description: 'third' }] } })}\n\n`) }
      return json(200, { jsonrpc: '2.0', id: msg.id, result: { tools: [{ name: 'a', description: 'first' }, { name: 'b', description: 'second' }], nextCursor: 'two' } })
    }
    return json(200, { jsonrpc: '2.0', id: msg.id, error: { code: -32601, message: 'no' } })
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  return { url: `http://127.0.0.1:${server.address().port}/mcp`, close: () => new Promise((r) => server.close(r)) }
}

test('parseChallenge: the Bearer parameters, case-insensitively', () => {
  const p = parseChallenge('Bearer realm="x", Resource_Metadata="https://a/.well-known/oauth-protected-resource", scope="read write"')
  assert.equal(p.resource_metadata, 'https://a/.well-known/oauth-protected-resource')
  assert.equal(p.scope, 'read write')
  assert.deepEqual(parseChallenge(''), {})
})

test('slug: a tool namespace out of a host or a label', () => {
  assert.equal(slug('mcp.notion.com'), 'mcp-notion-com')
  assert.equal(slug('Mock OAuth'), 'mock-oauth')
  assert.equal(slug('!!!'), 'server')
  assert.ok(slug('x'.repeat(50)).length <= 32)
})

test('filterToolsList: the switched-off tools leave, JSON or SSE, anything else passes untouched', () => {
  const answer = JSON.stringify({ jsonrpc: '2.0', id: 3, result: { tools: [{ name: 'keep' }, { name: 'hide' }] } })
  const off = new Set(['hide'])
  assert.deepEqual(JSON.parse(filterToolsList(answer, 'application/json', off)).result.tools, [{ name: 'keep' }])
  const sse = `event: message\ndata: ${answer}\n\n`
  const filtered = filterToolsList(sse, 'text/event-stream', off)
  assert.ok(filtered.startsWith('event: message\ndata: '))
  assert.deepEqual(JSON.parse(filtered.split('\n')[1].slice(6)).result.tools, [{ name: 'keep' }])
  assert.equal(filterToolsList('not json', 'application/json', off), 'not json')
  const other = JSON.stringify({ jsonrpc: '2.0', id: 4, result: { content: [] } })
  assert.equal(filterToolsList(other, 'application/json', off), other)
})

test('probeAuth: an open server, one that wants the authorization flow, one that wants a key', async () => {
  const open = await serve('open')
  const oauth = await serve('oauth')
  const key = await serve('key')
  try {
    assert.deepEqual(await probeAuth(open.url), { kind: 'open' })
    const flow = await probeAuth(oauth.url)
    assert.equal(flow.kind, 'oauth')
    assert.equal(flow.resource, oauth.url)
    assert.equal(flow.scope, 'mcp:tools')
    assert.ok(flow.as.registration_endpoint.endsWith('/register'))
    assert.ok(flow.as.token_endpoint.endsWith('/token'))
    const wantsKey = await probeAuth(key.url)
    assert.equal(wantsKey.kind, 'key')
    assert.equal(wantsKey.hint, 'Bring a key')
  } finally {
    await Promise.all([open.close(), oauth.close(), key.close()])
  }
})

test('listTools: initialize, initialized, every page of tools/list, and the session let go', async () => {
  const s = await serve('key')
  try {
    const tools = await listTools(s.url, { authorization: 'Bearer k' })
    assert.deepEqual(tools.map((t) => t.name), ['a', 'b', 'c'])
    assert.equal(tools[2].description, 'third')
    await assert.rejects(listTools(s.url, {}), /did not accept the credential/)
  } finally {
    await s.close()
  }
})
