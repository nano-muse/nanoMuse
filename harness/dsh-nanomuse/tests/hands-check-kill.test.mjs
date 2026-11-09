import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { withMcp } from '../lib/hands-check.js'

/**
 * A runtime that starts a helper of its own and then never answers: the shape a stuck
 * `nanomuse mcp` has when its screenshot helper is outliving it. When the check gives up,
 * the helper has to go with the runtime - a plain kill() ends the runtime alone and the
 * helper keeps running with its stdio pipes gone.
 */

/** The grandchild helper: records its pid, then stays alive until something kills it. */
const GRANDCHILD = `require('node:fs').writeFileSync(process.argv[1], String(process.pid)); setInterval(() => {}, 1 << 30)`

async function silentRuntime(dir, pidFile) {
  const runtime = join(dir, 'runtime.mjs')
  await writeFile(
    runtime,
    `
import { spawn } from 'node:child_process'
let buffer = ''
process.stdin.setEncoding('utf8')
process.stdin.on('data', (chunk) => {
  buffer += chunk
  let nl
  while ((nl = buffer.indexOf('\\n')) >= 0) {
    const line = buffer.slice(0, nl)
    buffer = buffer.slice(nl + 1)
    if (!line.trim()) continue
    const msg = JSON.parse(line)
    if (typeof msg.id !== 'number') continue
    if (msg.method === 'initialize') {
      process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: msg.id, result: { protocolVersion: '2024-11-05', capabilities: {}, serverInfo: { name: 'stuck', version: '1' } } }) + '\\n')
    } else if (msg.method === 'tools/call') {
      // the helper this runtime would really have: started, then the call never answers.
      // On Windows the helper detaches at birth - a node-born child otherwise rides a
      // job that libuv closes (killing it) when its parent dies, which no real runtime's
      // helper does; on posix it stays in the runtime's process group, where a plain
      // kill() of the runtime alone must leave it behind.
      spawn(process.execPath, ['-e', ${JSON.stringify(GRANDCHILD)}, ${JSON.stringify(pidFile)}], { stdio: 'ignore', detached: process.platform === 'win32' })
    }
  }
})
`,
  )
  return runtime
}

/** Whether a pid is still alive; a pid never seen is "gone" for this test's purposes. */
function alive(pid) {
  if (!pid) return false
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

test('a hands check that times out takes the runtime tree with it', { timeout: 30_000 }, async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'hands-kill-'))
  const pidFile = join(dir, 'helper.pid')
  t.after(() => rm(dir, { recursive: true, force: true }))
  const runtime = await silentRuntime(dir, pidFile)

  await assert.rejects(
    withMcp({ command: process.execPath, args: [runtime], timeoutMs: 1500 }, (call) => call('tools/call', { name: 'stuck', arguments: {} })),
    /did not answer in time/,
  )

  // the helper got itself written down; keep the after-hook able to clean it up if the fix is absent
  let pid = 0
  for (let i = 0; i < 100 && !pid; i++) {
    try {
      pid = Number(await readFile(pidFile, 'utf8'))
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 50))
    }
  }
  assert.ok(pid, 'the helper recorded its pid')
  t.after(() => {
    try {
      process.kill(pid, 'SIGKILL')
    } catch {
      // already gone, or was never cleaned into this branch
    }
  })

  // the whole point: within a short window the helper is gone with the runtime
  for (let i = 0; i < 100 && alive(pid); i++) {
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  assert.equal(alive(pid), false, `helper ${pid} outlived the timed-out runtime`)
})
