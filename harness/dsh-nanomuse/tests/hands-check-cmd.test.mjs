import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { checkScreenshot, runtimeInfo } from '../lib/hands-check.js'

const win32 = process.platform === 'win32'

/** A fake `nanomuse mcp` behind an npm-style `.cmd` shim: node speaks MCP, cmd launches it. */
async function fakeCmdRuntime(dir) {
  const script = join(dir, 'nanomuse-mcp.mjs')
  await writeFile(
    script,
    `
let buf = ''
process.stdin.setEncoding('utf8')
process.stdin.on('data', (chunk) => {
  buf += chunk
  let nl
  while ((nl = buf.indexOf('\\n')) >= 0) {
    const line = buf.slice(0, nl)
    buf = buf.slice(nl + 1)
    if (!line.trim()) continue
    const msg = JSON.parse(line)
    if (typeof msg.id !== 'number') continue
    let result
    if (msg.method === 'initialize') {
      result = { protocolVersion: '2024-11-05', capabilities: {}, serverInfo: { name: 'fake-nanomuse', version: '9.9.9' } }
    } else if (msg.method === 'tools/call' && msg.params && msg.params.name === 'computer_screen') {
      result = { content: [{ type: 'text', text: 'Desktop · 800x600' }], isError: false }
    } else {
      result = { content: [{ type: 'text', text: 'Working in the window of Finder' }], isError: false }
    }
    process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: msg.id, result }) + '\\n')
  }
})
process.stdin.on('end', () => process.exit(0))
`,
  )
  const bin = join(dir, 'bin')
  await mkdir(bin, { recursive: true })
  await writeFile(join(bin, 'nanomuse.cmd'), `@"${process.execPath}" "${script}" %*\r\n`)
  return bin
}

test('the hands check reads a screenshot through a .cmd runtime', { skip: !win32, timeout: 30_000 }, async () => {
  const dir = await mkdtemp(join(tmpdir(), 'hands-cmd-'))
  const bin = await fakeCmdRuntime(dir)
  // the PATH lookup the Settings page's Computer use check makes: this is the runtime it picks
  const runtime = await runtimeInfo({ ...process.env, NANOMUSE_PY: '', PATH: bin })
  assert.equal(runtime.ok, true)
  assert.ok(runtime.path.endsWith('nanomuse.cmd'), runtime.path)
  // the same options handsCheck builds: command straight from the lookup, args ['mcp']
  const shot = await checkScreenshot({ command: runtime.path, args: ['mcp'], timeoutMs: 20_000 })
  assert.equal(shot.ok, true, shot.error)
  assert.equal(shot.width, 800)
  assert.equal(shot.height, 600)
  assert.equal(shot.title, 'Desktop')
})
