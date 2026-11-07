import test from 'node:test'
import assert from 'node:assert/strict'
import { access, mkdtemp, mkdir, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { cliSpawnCommand, versionOf } from '../lib/coding-readers.js'
import { startRun } from '../lib/coding-runner.js'

const win32 = process.platform === 'win32'

/** The JSON-lines CLI the fakes speak: the version line, and a result that echoes the last argument. */
const FAKE_CLI = `
const args = process.argv.slice(2)
if (args[0] === '--version') { console.log('fake-claude 9.9.9'); process.exit(0) }
const text = args[args.length - 1]
const out = (o) => process.stdout.write(JSON.stringify(o) + '\\n')
out({ type: 'system', subtype: 'init', session_id: 'fake-1', model: 'fake' })
out({ type: 'assistant', message: { content: [{ type: 'tool_use', name: 'Bash', input: { command: 'echo hi' } }] } })
out({ type: 'assistant', message: { content: [{ type: 'text', text: 'You said: ' + text }] } })
out({ type: 'result', result: 'You said: ' + text, session_id: 'fake-1', duration_ms: 3 })
`

/** A fake `claude` behind the one-line shim the tests write themselves. */
async function fakeCmdClaude(dir) {
  const script = join(dir, 'fake-claude.mjs')
  await writeFile(script, FAKE_CLI)
  const bin = join(dir, 'bin')
  await mkdir(bin, { recursive: true })
  const cli = join(bin, 'claude.cmd')
  await writeFile(cli, `@"${process.execPath}" "${script}" %*\r\n`)
  return cli
}

/** The text npm's cmd-shim writes, pointed at a fake CLI under `node_modules`. */
async function npmShimClaude(dir) {
  const target = join(dir, 'node_modules', '@scope', 'agent', 'bin.js')
  await mkdir(dirname(target), { recursive: true })
  await writeFile(target, FAKE_CLI)
  const cli = join(dir, 'claude.cmd')
  await writeFile(cli, [
    '@ECHO off',
    'GOTO start',
    ':find_dp0',
    'SET dp0=%~dp0',
    'EXIT /b',
    ':start',
    'SETLOCAL',
    'CALL :find_dp0',
    '',
    'IF EXIST "%dp0%\\node.exe" (',
    '  SET "_prog=%dp0%\\node.exe"',
    ') ELSE (',
    '  SET "_prog=node"',
    '  SET PATHEXT=%PATHEXT:;.JS;=;%',
    ')',
    '',
    'endLocal & goto #_undefined_# & goto #_undefined_# & "%_prog%"  "%dp0%\\node_modules\\@scope\\agent\\bin.js" %*',
    '',
  ].join('\r\n'))
  return { cli, target }
}

test('cliSpawnCommand starts the script the shim names; anything else passes through or falls back to cmd', async () => {
  // a plain executable or a script node starts itself: passed through byte for byte
  assert.deepEqual(cliSpawnCommand('linux', '/usr/bin/claude', ['-p', 'hi']), ['/usr/bin/claude', ['-p', 'hi']])
  assert.deepEqual(cliSpawnCommand('win32', 'C:\\tools\\agent.exe', ['-p', 'hi']), ['C:\\tools\\agent.exe', ['-p', 'hi']])
  assert.deepEqual(cliSpawnCommand('win32', 'C\\dsh\\lib\\bin.js', ['-x']), ['C\\dsh\\lib\\bin.js', ['-x']])
  // a batch file that names no script (nothing of that shape exists here) still goes through cmd
  const [file, args] = cliSpawnCommand('win32', 'C:\\npm\\claude.cmd', ['-p', 'hello world'])
  assert.equal(file, process.env.ComSpec || 'cmd.exe')
  assert.deepEqual(args, ['/d', '/s', '/c', 'C:\\npm\\claude.cmd', '-p', 'hello world'])
})

test('cliSpawnCommand reads a real npm shim and starts the script it names', { skip: !win32 }, async () => {
  const dir = await mkdtemp(join(tmpdir(), 'cli-shim-'))
  const { cli, target } = await npmShimClaude(dir)
  const [file, args] = cliSpawnCommand('win32', cli, ['-p', 'hello world'])
  assert.equal(file, process.execPath)
  assert.deepEqual(args, [target, '-p', 'hello world'])
})

test('runner: a run against a .cmd CLI streams events and ends done', { skip: !win32, timeout: 30_000 }, async () => {
  const dir = await mkdtemp(join(tmpdir(), 'cli-spawn-'))
  const cli = await fakeCmdClaude(dir)
  const events = []
  const run = await startRun({
    agent: 'claude',
    text: 'hello world',
    which: () => cli,
    onEvent: (e) => events.push(e),
    timeoutMs: 20_000,
    readerEnv: { NANOMUSE_CODING_HOME: join(dir, 'nohome') },
  })
  assert.equal(run.status, 'done', run.error)
  assert.equal(run.result_session_id, 'fake-1')
  assert.equal(run.tools, 1)
  assert.equal(run.output, 'You said: hello world')
  assert.deepEqual(events.map((e) => e.kind), ['started', 'tool', 'text', 'done'])
})

test('runner: a .cmd CLI receives the argument exactly as written, and nothing in it runs', { skip: !win32, timeout: 30_000 }, async () => {
  const dir = await mkdtemp(join(tmpdir(), 'cli-exact-'))
  const { cli } = await npmShimClaude(dir)
  // every character cmd would have taken as its own grammar: an ampersand that would run a
  // second command writing a marker, quotes, percent signs, a caret, and two kinds of newline
  const marker = join(dir, 'pwned')
  const text = `first & echo pwned> "${marker}"\r\na "quoted" word, a %PATH% percent, a ^ caret\na bare-newline line`
  const run = await startRun({
    agent: 'claude',
    text,
    which: () => cli,
    onEvent: () => {},
    timeoutMs: 20_000,
    readerEnv: { NANOMUSE_CODING_HOME: join(dir, 'nohome') },
  })
  assert.equal(run.status, 'done', run.error)
  assert.equal(run.output, 'You said: ' + text)
  await assert.rejects(access(marker))
})

test('versionOf reads the version a .cmd CLI prints', { skip: !win32, timeout: 20_000 }, async () => {
  const dir = await mkdtemp(join(tmpdir(), 'cli-ver-'))
  const cli = await fakeCmdClaude(dir)
  assert.equal(await versionOf(cli), 'fake-claude 9.9.9')
})
