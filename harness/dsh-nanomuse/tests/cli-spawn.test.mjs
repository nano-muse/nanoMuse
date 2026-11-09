import test from 'node:test'
import assert from 'node:assert/strict'
import { access, mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
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
    'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\node_modules\\@scope\\agent\\bin.js" %*',
    '',
  ].join('\r\n'))
  return { cli, target }
}

test('cliSpawnCommand starts the script the shim names; anything that is not a batch file passes through', () => {
  // a plain executable or a script node starts itself: passed through byte for byte
  assert.deepEqual(cliSpawnCommand('linux', '/usr/bin/claude', ['-p', 'hi']), ['/usr/bin/claude', ['-p', 'hi']])
  assert.deepEqual(cliSpawnCommand('win32', 'C:\\tools\\agent.exe', ['-p', 'hi']), ['C:\\tools\\agent.exe', ['-p', 'hi']])
  assert.deepEqual(cliSpawnCommand('win32', 'C\\dsh\\lib\\bin.js', ['-x']), ['C\\dsh\\lib\\bin.js', ['-x']])
  // a batch file that names no launcher (nothing of that shape exists here) is refused, not routed through cmd
  assert.throws(() => cliSpawnCommand('win32', 'C:\\npm\\claude.cmd', ['-p', 'hello world']), /batch file/)
})

test('cliSpawnCommand reads a real npm shim and starts the script it names', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'cli-shim-'))
  t.after(() => rm(dir, { recursive: true, force: true }))
  const { cli, target } = await npmShimClaude(dir)
  const [file, args] = cliSpawnCommand('win32', cli, ['-p', 'hello world'])
  assert.equal(file, process.execPath)
  assert.deepEqual(args, [target, '-p', 'hello world'])
  // Also accept the double-goto variant used by other installed launchers.
  const current = await readFile(cli, 'utf8')
  await writeFile(cli, current.replace('2>NUL || title %COMSPEC%', '& goto #_undefined_#'))
  assert.deepEqual(cliSpawnCommand('win32', cli, ['-p', 'hello world']), [file, args])
})

test('cliSpawnCommand skips a quoted path in a REM comment and takes the invocation', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'cli-rem-'))
  t.after(() => rm(dir, { recursive: true, force: true }))
  const target = join(dir, 'node_modules', 'agent', 'cli.mjs')
  await mkdir(dirname(target), { recursive: true })
  await writeFile(target, '')
  // a quoted script path that exists, named in a comment before the entry point: documentation, not the launcher
  const decoy = join(dir, 'docs', 'decoy.js')
  await mkdir(dirname(decoy), { recursive: true })
  await writeFile(decoy, '')
  const cli = join(dir, 'agent.cmd')
  await writeFile(cli, [
    `rem the old entry point was "${decoy}"`,
    `@"${process.execPath}" "${target}" %*`,
    '',
  ].join('\r\n'))
  const [file, args] = cliSpawnCommand('win32', cli, ['-p', 'hi'])
  assert.equal(file, process.execPath)
  assert.deepEqual(args, [target, '-p', 'hi'])
})

test('cliSpawnCommand refuses batch code that merely mentions a script or changes its invocation', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'cli-batch-meaning-'))
  t.after(() => rm(dir, { recursive: true, force: true }))
  const target = join(dir, 'actual.mjs')
  const decoy = join(dir, 'decoy.js')
  const cli = join(dir, 'agent.cmd')
  await writeFile(target, '')
  await writeFile(decoy, '')
  const invoke = `@"${process.execPath}" "${target}" %*`
  for (const [name, body] of [
    ['echo only', `@echo "${decoy}"`],
    ['echo after a launcher', `${invoke}\n@echo "${decoy}"`],
    ['two launchers', `${invoke}\n@node "${decoy}" %*`],
    ['script assigned to a variable', `set SCRIPT="${decoy}"`],
    ['a different interpreter', `@python "${target}" %*`],
    ['additional arguments', `@node "${target}" --changed %*`],
    ['redirected output', `${invoke} >nul`],
    ['a conditional launcher', `if exist missing (\n${invoke}\n)`],
    ['environment changes', `set NODE_OPTIONS=--inspect\n${invoke}`],
    ['an uninitialized directory variable', '@node "%dp0%\\actual.mjs" %*'],
  ]) {
    await writeFile(cli, body + '\r\n')
    assert.throws(() => cliSpawnCommand('win32', cli, ['prompt']), /batch file/, name)
  }
})

test('cliSpawnCommand rejects a changed npm prelude and a directory named like a script', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'cli-npm-meaning-'))
  t.after(() => rm(dir, { recursive: true, force: true }))
  const { cli, target } = await npmShimClaude(dir)
  const original = await readFile(cli, 'utf8')
  await writeFile(cli, original.replace('SET "_prog=node"', 'SET "_prog=python"'))
  assert.throws(() => cliSpawnCommand('win32', cli, ['prompt']), /batch file/)
  await writeFile(cli, original)
  await rm(target)
  await mkdir(target)
  assert.throws(() => cliSpawnCommand('win32', cli, ['prompt']), /batch file/)
})

test('runner: a run against a .cmd that names no launcher fails, and nothing runs', { skip: !win32, timeout: 30_000 }, async () => {
  const dir = await mkdtemp(join(tmpdir(), 'cli-refuse-'))
  // a batch program that is not an npm shim: starting it through cmd would reinterpret the argument
  const marker = join(dir, 'ran')
  const cli = join(dir, 'tool.cmd')
  await writeFile(cli, `@echo off\r\necho ran> "${marker}"\r\n`)
  const run = await startRun({
    agent: 'claude',
    text: 'hello',
    which: () => cli,
    onEvent: () => {},
    timeoutMs: 20_000,
    readerEnv: { NANOMUSE_CODING_HOME: join(dir, 'nohome') },
  })
  assert.equal(run.status, 'failed')
  assert.match(run.error ?? '', /batch file/)
  await assert.rejects(access(marker))
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
