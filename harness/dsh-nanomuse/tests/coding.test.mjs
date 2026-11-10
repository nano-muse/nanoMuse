// The coding agents on this computer (`docs/coding-agents.md`): the three readers on
// fixture stores in the documented formats, the process-count parsers on canned `ps` /
// `tasklist` output, the runner's stream normaliser on canned stream-json lines, a run
// against a fake CLI, and the hub action shapes — the runtime's `to_dict()`s, so the
// phones and the web cannot tell the desktop from the Python runtime.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { zstdCompressSync } from 'node:zlib'
import { cliFor, clean, countProcesses, detect, ownDshEntry, parsePs, parseTasklist, readSession, sessions, sessionsRoot, slugToPath, title, which } from '../lib/coding-readers.js'
import { agentEnv, commandFor, continuation, isResumeLockError, normalise, Run, runFromView, startRun } from '../lib/coding-runner.js'
import { CODING_ACTIONS, CodingService, codingBrief, GATED_CODING_ACTIONS } from '../lib/coding.js'

const posix = process.platform !== 'win32'

/**
 * The fake CLIs are `#!/bin/sh` wrappers on posix and one-line `.cmd` wrappers around the same
 * node script on Windows - the shape npm's own global-bin shims have, which the runner starts
 * through `cliSpawnCommand`. A Windows wrapper stays one line because `cmd` ends an argument at
 * the first newline; the behaviour lives in the `.mjs` the wrapper points at.
 */

/** The agents' slug of a workspace on this OS: `/` as `-` on Unix; Cursor's `C-Users-…` on Windows. */
function slugOf(ws) {
  return posix ? ws.slice(1).replace(/\//g, '-') : ws.replace(/^([A-Za-z]):\\/, '$1-').replace(/\\/g, '-')
}

async function scratch(work) {
  const dir = await mkdtemp(join(tmpdir(), 'nanomuse-coding-'))
  try {
    return await work(dir)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

async function write(path, lines) {
  await mkdir(dirname(path), { recursive: true })
  await writeFile(path, lines.map((l) => (typeof l === 'string' ? l : JSON.stringify(l))).join('\n') + '\n')
}

/**
 * Write a dsh session file the way the harness does: one zstd frame per write. `groups` is a
 * list of frames, each a list of JSON objects; reading it back must decompress every frame,
 * not just the first.
 */
async function writeZstdFrames(path, groups) {
  await mkdir(dirname(path), { recursive: true })
  const frames = groups.map((lines) => zstdCompressSync(Buffer.from(lines.map((l) => JSON.stringify(l)).join('\n') + '\n')))
  await writeFile(path, Buffer.concat(frames))
}

/** A home with one chat of each agent, in the formats `agents.py` documents. */
async function fixtureHome(home) {
  const ws = join(home, 'work', 'api')
  await mkdir(ws, { recursive: true })
  const slug = slugOf(ws)
  // Cursor: an IDE chat (no CLI meta) and a CLI chat (meta.json with the cwd)
  await write(join(home, '.cursor', 'projects', slug, 'agent-transcripts', 'ide-1', 'ide-1.jsonl'), [
    { role: 'user', message: { content: [{ type: 'text', text: '<user_query>Fix the parser</user_query><attached_files>x</attached_files>' }] } },
    { role: 'assistant', message: { content: [{ type: 'text', text: 'Done: the parser now handles empty lines.' }] } },
    { type: 'turn_ended' },
    'not json at all',
  ])
  await write(join(home, '.cursor', 'projects', slug, 'agent-transcripts', 'cli-2', 'cli-2.jsonl'), [
    { role: 'user', message: { content: [{ type: 'text', text: 'Add a test' }] } },
    { role: 'assistant', message: { content: [{ type: 'tool_use', name: 'edit' }, { type: 'text', text: 'Added tests/test_parser.py.' }] } },
    { type: 'turn_ended' },
  ])
  await write(join(home, '.cursor', 'chats', 'abc', 'cli-2', 'meta.json'), [{ cwd: ws, createdAtMs: 1_700_000_000_000 }])
  // Codex: a rollout
  await write(join(home, '.codex', 'sessions', '2026', '01', '02', 'rollout-2026-01-02T10-00-00-0f9a7b6c-1111-2222-3333-444455556666.jsonl'), [
    { type: 'session_meta', payload: { id: '0f9a7b6c-1111-2222-3333-444455556666', cwd: ws, originator: 'codex_cli_rs', timestamp: '2026-01-02T10:00:00Z' } },
    { type: 'response_item', payload: { type: 'message', role: 'user', content: [{ type: 'input_text', text: 'Rename the module' }] } },
    { type: 'event_msg', payload: { type: 'task_started' } },
    { type: 'response_item', payload: { type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'Renamed parser.py to reader.py.' }] } },
    { type: 'event_msg', payload: { type: 'task_complete' } },
  ])
  // Claude Code
  await write(join(home, '.claude', 'projects', `-${slug}`, 'c1a2b3d4-aaaa-bbbb-cccc-ddddeeeeffff.jsonl'), [
    { type: 'user', message: { role: 'user', content: 'Explain the build' }, timestamp: '2026-01-03T09:00:00Z', cwd: ws, sessionId: 'c1a2b3d4-aaaa-bbbb-cccc-ddddeeeeffff' },
    { type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: 'The build runs esbuild twice.' }] }, timestamp: '2026-01-03T09:00:05Z', cwd: ws, sessionId: 'c1a2b3d4-aaaa-bbbb-cccc-ddddeeeeffff' },
    { type: 'user', message: { role: 'user', content: '<local-command-stdout>ignored</local-command-stdout>' }, isMeta: true, cwd: ws },
  ])
  // dsh: the harness's own store, one zstd frame per write (a long chat is many frames
  // appended, which is what a single zstdDecompressSync would stop at), with runtime context
  // and a subagent session that must not show up as chats the person had
  const dshDir = join(home, '.dsh', 'sessions', slugOf(ws), 'session-1111-2222-3333')
  await mkdir(dshDir, { recursive: true })
  await writeZstdFrames(join(dshDir, 'session.v4.jsonl.zstd'), [
    [{ type: 'session', version: 4, id: 'session-1111-2222-3333', createdAt: 1_700_000_000_000, cwd: ws }],
    [
      { type: 'user/message', seq: 1, data: { content: [{ type: 'text', text: 'Refactor the loader' }], source: { kind: 'user' }, role: 'user' } },
      { type: 'session/title', seq: 2, data: { title: 'Refactor the loader' } },
    ],
    [
      { type: 'user/message', seq: 3, data: { content: [{ type: 'text', text: 'Current DSH file policy: workspace-write' }], source: { kind: 'runtime-context' } } },
      { type: 'assistant/message', seq: 4, data: { message: { role: 'assistant', content: [{ type: 'reasoning', text: 'hmm' }, { type: 'text', text: 'The loader is now two functions.' }] } } },
      { type: 'turn/end', seq: 5, data: { turn: 1 } },
    ],
  ])
  const subDir = join(home, '.dsh', 'sessions', slugOf(ws), 'session-9999-8888-7777')
  await mkdir(subDir, { recursive: true })
  await writeZstdFrames(join(subDir, 'session.v4.jsonl.zstd'), [
    [{ type: 'session', version: 4, id: 'session-9999-8888-7777', cwd: ws, origin: 'subagent', parentSession: 'session-1111-2222-3333' }],
    [{ type: 'user/message', seq: 1, data: { content: [{ type: 'text', text: 'You are researching something' }], source: { kind: 'user' } } }],
  ])
  return { ws, slug }
}

const SESSION_KEYS = ['agent', 'id', 'title', 'workspace', 'path', 'created_at', 'updated_at', 'messages', 'status', 'last_user', 'last_assistant', 'source', 'resumable']

test('Codex uses the saved desktop name, then index, then real user message', async () => {
  await scratch(async (home) => {
    const root = join(home, '.codex')
    const sid = '0f9a7b6c-1111-2222-3333-444455556666'
    const path = join(root, 'sessions', `rollout-${sid}.jsonl`)
    await write(path, [
      { type: 'session_meta', payload: { id: sid } },
      { type: 'response_item', payload: { type: 'message', role: 'user', content: '# AGENTS.md instructions for /workspace\nInjected context' } },
      { type: 'response_item', payload: { type: 'message', role: 'user', content: 'Fix the parser' } },
    ])
    const env = { NANOMUSE_CODING_HOME: home }
    assert.equal((await sessions('codex', 10, undefined, env))[0].title, 'Fix the parser')
    await write(join(root, 'session_index.jsonl'), [
      { id: sid, thread_name: 'Old index name' }, 'invalid',
      { id: sid, thread_name: 'Indexed name' },
    ])
    assert.equal((await readSession('codex', sid, env)).title, 'Indexed name')
    const { DatabaseSync } = await import('node:sqlite')
    const db = new DatabaseSync(join(root, 'state_5.sqlite'))
    db.exec('CREATE TABLE threads (id TEXT, title TEXT, name TEXT)')
    db.prepare('INSERT INTO threads VALUES (?, ?, ?)').run(sid, 'Original prompt', 'Desktop renamed title')
    db.close()
    const detail = await readSession('codex', sid, env)
    assert.equal(detail.title, 'Desktop renamed title')
    assert.equal((await sessions('codex', 10, undefined, env))[0].title, detail.title)
    assert.deepEqual(detail.transcript.map((m) => m.text), ['Fix the parser'])
    assert.deepEqual(detail.timeline.map((m) => m.text), ['Fix the parser'])
    await writeFile(join(root, 'state_6.sqlite'), 'broken database')
    assert.equal((await readSession('codex', sid, env)).title, 'Desktop renamed title')
  })
})

test('readers: a fixture home gives one session per agent, in the runtime shape', async () => {
  await scratch(async (home) => {
    const { ws } = await fixtureHome(home)
    const env = { ...process.env, NANOMUSE_CODING_HOME: home }
    assert.equal(sessionsRoot('codex', env), join(home, '.codex', 'sessions'))
    const all = await sessions(undefined, 30, undefined, env)
    assert.equal(all.length, 5)
    for (const s of all) for (const k of SESSION_KEYS) assert.ok(k in s, `${s.agent} session carries ${k}`)
    assert.ok(all.every((s) => !('transcript' in s)), 'the list carries no transcripts')
    assert.ok(!all.some((s) => s.id === 'session-9999-8888-7777'), 'a subagent session is not one of the person’s chats')

    const ide = all.find((s) => s.id === 'ide-1')
    assert.equal(ide.agent, 'cursor')
    assert.equal(ide.title, 'Fix the parser')
    assert.equal(ide.workspace, ws)
    assert.equal(ide.source, 'ide')
    assert.equal(ide.resumable, false)
    assert.equal(ide.messages, 2)
    assert.equal(ide.status, 'active')
    assert.equal(ide.last_assistant, 'Done: the parser now handles empty lines.')

    const cli = all.find((s) => s.id === 'cli-2')
    assert.equal(cli.source, 'cli')
    assert.equal(cli.resumable, true)
    assert.equal(cli.created_at, 1_700_000_000)
    assert.equal(cli.last_assistant, '[tool: edit] Added tests/test_parser.py.', 'the one-line summary collapses whitespace, as the runtime does')

    const codex = all.find((s) => s.agent === 'codex')
    assert.equal(codex.id, '0f9a7b6c-1111-2222-3333-444455556666')
    assert.equal(codex.title, 'Rename the module')
    assert.equal(codex.workspace, ws)
    assert.equal(codex.source, 'codex_cli_rs')
    assert.equal(codex.created_at, Date.parse('2026-01-02T10:00:00Z') / 1000)
    assert.equal(codex.messages, 2)
    assert.equal(codex.resumable, true)

    const claude = all.find((s) => s.agent === 'claude')
    assert.equal(claude.id, 'c1a2b3d4-aaaa-bbbb-cccc-ddddeeeeffff')
    assert.equal(claude.title, 'Explain the build')
    assert.equal(claude.workspace, ws)
    assert.equal(claude.messages, 2, 'the meta line is skipped')
    assert.equal(claude.source, '')

    const dsh = all.find((s) => s.agent === 'dsh')
    assert.equal(dsh.id, 'session-1111-2222-3333')
    assert.equal(dsh.title, 'Refactor the loader')
    assert.equal(dsh.workspace, ws)
    assert.equal(dsh.created_at, 1_700_000_000)
    assert.equal(dsh.messages, 2, 'the runtime-context user message is not the person’s words')
    assert.equal(dsh.last_user, 'Refactor the loader')
    assert.equal(dsh.resumable, true)

    // by agent, by workspace, and the limit
    assert.equal((await sessions('cursor', 30, undefined, env)).length, 2)
    assert.equal((await sessions('dsh', 30, undefined, env)).length, 1)
    assert.equal((await sessions(undefined, 30, ws, env)).length, 5)
    assert.equal((await sessions(undefined, 30, join(home, 'elsewhere'), env)).length, 0)
    assert.equal((await sessions(undefined, 1, undefined, env)).length, 1)
  })
})

test('readers: one session comes with its transcript; a bad id is nothing', async () => {
  await scratch(async (home) => {
    await fixtureHome(home)
    const env = { ...process.env, NANOMUSE_CODING_HOME: home }
    const ide = await readSession('cursor', 'ide-1', env)
    assert.deepEqual(ide.transcript, [
      { role: 'user', text: 'Fix the parser' },
      { role: 'assistant', text: 'Done: the parser now handles empty lines.' },
    ])
    const codex = await readSession('codex', '0f9a7b6c-1111-2222-3333-444455556666', env)
    assert.equal(codex.transcript.length, 2)
    assert.equal(codex.transcript[1].text, 'Renamed parser.py to reader.py.')
    const claude = await readSession('claude', 'c1a2b3d4-aaaa-bbbb-cccc-ddddeeeeffff', env)
    assert.equal(claude.transcript.length, 2)
    // dsh: every zstd frame is decompressed, not only the first
    const dsh = await readSession('dsh', 'session-1111-2222-3333', env)
    assert.deepEqual(dsh.transcript, [
      { role: 'user', text: 'Refactor the loader' },
      { role: 'assistant', text: 'The loader is now two functions.' },
    ])
    assert.equal(await readSession('dsh', 'session-9999-8888-7777', env), undefined, 'a subagent session is not readable as a chat')
    assert.equal(await readSession('claude', 'nope', env), undefined)
    assert.equal(await readSession('cursor', '../ide-1', env), undefined)
    assert.equal(await readSession('cursor', '', env), undefined)
  })
})

test('readers: a missing home is every agent with no sessions', async () => {
  await scratch(async (home) => {
    const env = { ...process.env, NANOMUSE_CODING_HOME: join(home, 'nothing'), PATH: join(home, 'emptybin') }
    assert.deepEqual(await sessions(undefined, 30, undefined, env), [])
    const agents = await detect(false, env)
    assert.deepEqual(agents.map((a) => a.id), ['cursor', 'codex', 'claude', 'dsh'])
    for (const a of agents) {
      assert.deepEqual(Object.keys(a).sort(), ['cli', 'id', 'installed', 'name', 'running', 'sessions_root', 'version'])
      assert.equal(a.installed, false)
      assert.equal(a.cli, null)
      assert.equal(a.sessions_root, '')
      assert.equal(a.running, 0)
    }
  })
})

test('readers: detect sees a store without a CLI, and a CLI on PATH', async () => {
  await scratch(async (home) => {
    await fixtureHome(home)
    const bin = join(home, 'bin')
    await mkdir(bin)
    // posix gets the sh one-liner; Windows gets a node script behind a .cmd shim, the shape npm's bins have.
    // PATHEXT is pinned so `which` answers in the spelling this test can assert exactly.
    const cli = posix ? join(bin, 'codex') : join(bin, 'codex.cmd')
    if (posix) {
      await writeFile(cli, '#!/bin/sh\necho "codex-cli 0.42.0"\n')
      await chmod(cli, 0o755)
    } else {
      // the shape npm's shims have: a .cmd that launches a node script, which the shim resolution starts
      const script = join(bin, 'codex-version.mjs')
      await writeFile(script, "console.log('codex-cli 0.42.0')\n")
      await writeFile(cli, `@"${process.execPath}" "${script}" %*\r\n`)
    }
    const env = { ...process.env, NANOMUSE_CODING_HOME: home, PATH: bin, ...(posix ? {} : { PATHEXT: '.cmd' }) }
    assert.equal(which('codex', env), cli)
    assert.equal(which('claude', env), undefined)
    const agents = await detect(true, env)
    const codex = agents.find((a) => a.id === 'codex')
    assert.equal(codex.installed, true)
    assert.equal(codex.cli, cli)
    assert.equal(codex.version, 'codex-cli 0.42.0')
    assert.equal(codex.sessions_root, join(home, '.codex', 'sessions'))
    const claude = agents.find((a) => a.id === 'claude')
    assert.equal(claude.installed, true, 'a store on disk counts as installed')
    assert.equal(claude.cli, null)
    assert.equal(claude.version, '')
  })
})

test('readers: clean, title and slugToPath', async () => {
  assert.equal(clean('<user_query>Hello</user_query><system_reminder>x</system_reminder>'), 'Hello')
  assert.equal(clean('<timestamp>now</timestamp> plain <empty></empty> words'), 'plain  words')
  assert.equal(clean(''), '')
  assert.equal(title('  a   b  '), 'a b')
  assert.equal(title('x'.repeat(100)).length, 80)
  assert.ok(title('x'.repeat(100)).endsWith('…'))
  await scratch(async (dir) => {
    // the slug the way the agents make it on this OS: `/` (or the drive's `:\` and `\`) as `-`
    await mkdir(join(dir, 'my-project', 'sub'), { recursive: true })
    const want = join(dir, 'my-project', 'sub')
    const slug = slugOf(want)
    const same = (a, b) => assert.equal(posix ? a : a.toLowerCase(), posix ? b : b.toLowerCase())
    same(slugToPath(slug), want)
    if (!posix) same(slugToPath(slug.replace(/^([A-Za-z])-/, '$1--')), want) // Claude Code's shape
    assert.equal(slugToPath('no-such-root-anywhere-xyz'), 'no-such-root-anywhere-xyz')
  })
  // both OSes' shapes, on every OS, against a pretend disk
  const unix = new Set(['/ssd', '/ssd/code', '/ssd/code/my-app', '/ssd/code/my-app/sub'])
  const isUnix = (p) => unix.has(p)
  assert.equal(slugToPath('ssd-code-my-app-sub', 'linux', isUnix), '/ssd/code/my-app/sub')
  assert.equal(slugToPath('ssd-code-my-app-gone', 'linux', isUnix), '/ssd/code/my-app/gone')
  assert.equal(slugToPath('nope-code', 'linux', isUnix), 'nope-code')
  assert.equal(slugToPath('c-Users-me', 'linux', isUnix), 'c-Users-me') // no drives on Unix
  const win = new Set(['C:\\Users', 'C:\\Users\\me', 'C:\\Users\\me\\my-app', 'D:\\work'])
  const isWin = (p) => win.has(p)
  assert.equal(slugToPath('C-Users-me-my-app', 'win32', isWin), 'C:\\Users\\me\\my-app') // Cursor
  assert.equal(slugToPath('C--Users-me-my-app', 'win32', isWin), 'C:\\Users\\me\\my-app') // Claude Code
  assert.equal(slugToPath('c--Users-me-my-app', 'win32', isWin), 'C:\\Users\\me\\my-app')
  assert.equal(slugToPath('d-work-gone', 'win32', isWin), 'D:\\work\\gone')
  assert.equal(slugToPath('Z-nothing-here', 'win32', isWin), 'Z-nothing-here')
  assert.equal(slugToPath('Users-me', 'win32', isWin), 'Users-me')
})

test('processes: ps and tasklist parsers, and the count by agent', () => {
  const ps = parsePs(['bash /bin/bash --login', 'node /usr/bin/node /home/me/.local/bin/cursor-agent --server extra words', 'codex codex exec --json', 'claude claude -p', 'cursor-agent cursor-agent -p hi', 'Cursor.exe', ''].join('\n'))
  assert.deepEqual(ps[1], ['node', '/usr/bin/node /home/me/.local/bin/cursor-agent --server'])
  assert.deepEqual(ps[5], ['Cursor.exe', ''])
  assert.deepEqual(countProcesses(ps), { cursor: 3, codex: 1, claude: 1, dsh: 0 })

  const tl = parseTasklist(['"System Idle Process","0","Services","0","8 K"', '"node.exe","1234","Console","1","50,000 K"', '"node.exe","1235","Console","1","50,000 K"', '"codex.exe","99","Console","1","1 K"', '"Claude.exe","98","Console","1","1 K"'].join('\r\n'), ['"C:\\Program Files\\nodejs\\node.exe" C:\\Users\\me\\AppData\\cursor-agent\\index.js', '"C:\\Program Files\\nodejs\\node.exe" something-else.js'])
  assert.equal(tl.length, 5)
  assert.deepEqual(tl[1], ['node.exe', '"C:\\Program Files\\nodejs\\node.exe" C:\\Users\\me\\AppData\\cursor-agent\\index.js'])
  assert.deepEqual(tl[2], ['node.exe', '"C:\\Program Files\\nodejs\\node.exe" something-else.js'])
  assert.deepEqual(countProcesses(tl), { cursor: 1, codex: 1, claude: 1, dsh: 0 })
  // our own command line never matches: there is no `pgrep -f`, only names and node's argv
  assert.deepEqual(countProcesses([['python3', 'python3 -m nanomuse serve --coding cursor-agent']]), { cursor: 0, codex: 0, claude: 0, dsh: 0 })
})

test('runner: the command lines the docs give', () => {
  assert.deepEqual(commandFor('cursor', '/u/cursor-agent', 'abc', '/w', 'hi there', true), ['/u/cursor-agent', '-p', '--output-format', 'stream-json', '--stream-partial-output', '--force', '--resume', 'abc', '--workspace', '/w', 'hi there'])
  assert.deepEqual(commandFor('cursor', '/u/cursor-agent', 'abc', '', 'hi', false), ['/u/cursor-agent', '-p', '--output-format', 'stream-json', '--stream-partial-output', '--force', 'hi'])
  assert.deepEqual(commandFor('codex', 'codex', 'th1', '/w', 'go', true), ['codex', 'exec', 'resume', 'th1', '--json', '--skip-git-repo-check', '-c', 'sandbox_mode="workspace-write"', 'go'])
  assert.deepEqual(commandFor('codex', 'codex', '', '/w', 'go', false), ['codex', 'exec', '--json', '--skip-git-repo-check', '-c', 'sandbox_mode="workspace-write"', '-C', '/w', 'go'])
  assert.deepEqual(commandFor('claude', 'claude', 's1', '/w', 'go', true), ['claude', '-p', '--output-format', 'stream-json', '--verbose', '--permission-mode', 'acceptEdits', '--resume', 's1', 'go'])
  // dsh has no `-C`: it runs in the spawn's cwd, and adopting a session requires that cwd to match
  assert.deepEqual(commandFor('dsh', '/u/dsh', 'session-1', '/w', 'go', true), ['/u/dsh', '--profile', 'headless', '--json', '--session-id', 'session-1', 'go'])
  assert.deepEqual(commandFor('dsh', '/u/dsh', '', '/w', 'go', false), ['/u/dsh', '--profile', 'headless', '--json', 'go'])
  // the harness this plugin runs inside is a `bin.js` (its own `dsh` ships in the app
  // bundle, not on PATH), so node is what starts it
  assert.deepEqual(commandFor('dsh', '/app/dsh/lib/bin.js', '', '/w', 'go', false), [process.execPath, '/app/dsh/lib/bin.js', '--profile', 'headless', '--json', 'go'])
})

test('readers: the harness finds its own dsh entry, and dsh sends through it', async () => {
  // the desktop app starts `node …/dsh/lib/bin.js <profile>`, so the entry is in argv
  assert.equal(ownDshEntry(['/usr/bin/node', '/app/other/lib/bin.js']), undefined, 'not a dsh entry')
  assert.equal(ownDshEntry(['/usr/bin/node', '--expose-internals', '/nope/dsh/lib/bin.js']), undefined, 'a path that is not there')
  assert.equal(ownDshEntry([]), undefined)
  await scratch(async (dir) => {
    const entry = join(dir, 'dsh', 'lib', 'bin.js')
    await mkdir(dirname(entry), { recursive: true })
    await writeFile(entry, '// the harness\n')
    const argv = ['/usr/bin/node', '--expose-internals', entry, 'web']
    assert.equal(ownDshEntry(argv), entry)
    // no dsh on PATH: a run is sent through this harness's own entry, and only for dsh
    const env = { ...process.env, PATH: join(dir, 'emptybin') }
    assert.equal(cliFor('dsh', env, argv), entry)
    assert.equal(cliFor('codex', env, argv), undefined, 'another agent never falls back')
    // but the entry alone does not make dsh installed: that is PATH or ~/.dsh, as for the others
    assert.equal(which('dsh', env), undefined)
    const agents = await detect(false, { ...env, NANOMUSE_CODING_HOME: join(dir, 'nothing') })
    assert.equal(agents.find((a) => a.id === 'dsh').installed, false)
  })
})

test('runner: the CLI environment is scrubbed and keeps the agent’s own variables', () => {
  const source = { PATH: '/bin', HOME: '/home/me', NANOMUSE_TOKEN: 'x', OPENAI_API_KEY: 'k', ANTHROPIC_API_KEY: 'a', AWS_SECRET_ACCESS_KEY: 's', GITHUB_TOKEN: 'g', MY_PASSWORD: 'p', SSH_AUTH_SOCK: '/tmp/s', CURSOR_API_KEY: 'c', TERM: 'xterm' }
  const codex = agentEnv('codex', source)
  assert.equal(codex.OPENAI_API_KEY, 'k')
  assert.equal(codex.ANTHROPIC_API_KEY, undefined)
  assert.equal(codex.NANOMUSE_TOKEN, undefined)
  assert.equal(codex.GITHUB_TOKEN, undefined)
  assert.equal(codex.MY_PASSWORD, undefined)
  assert.equal(codex.SSH_AUTH_SOCK, undefined)
  assert.equal(codex.PATH, '/bin')
  assert.equal(codex.NO_COLOR, '1')
  assert.equal(codex.CI, '1')
  const claude = agentEnv('claude', source)
  assert.equal(claude.ANTHROPIC_API_KEY, 'a')
  assert.equal(claude.AWS_SECRET_ACCESS_KEY, undefined)
  const bedrock = agentEnv('claude', { ...source, CLAUDE_CODE_USE_BEDROCK: '1' })
  assert.equal(bedrock.AWS_SECRET_ACCESS_KEY, 's')
  assert.equal(agentEnv('cursor', source).CURSOR_API_KEY, 'c')
  // the desktop app points DSH_HOME at its own home; a dsh started from here works in the store
  // the readers list instead, so the session it adopts or starts is the one the phone sees
  const dsh = agentEnv('dsh', { ...source, DSH_HOME: '/app/home', NANOMUSE_CODING_HOME: '/h' })
  assert.equal(dsh.DSH_HOME, join('/h', '.dsh'))
  assert.equal(agentEnv('codex', { ...source, DSH_HOME: '/app/home' }).DSH_HOME, '/app/home', 'only dsh is redirected')
})

test('runner: Cursor stream-json → started, partial text then the whole message, tools, done', () => {
  const run = new Run('run_1', 'cursor', '', '', 'hi')
  const ev = (obj) => normalise('cursor', obj, run)
  assert.deepEqual(ev({ type: 'system', subtype: 'init', session_id: 'chat-9', model: 'gpt' }), [{ kind: 'started', text: '', session_id: 'chat-9', model: 'gpt' }])
  assert.equal(run.result_session_id, 'chat-9')
  assert.deepEqual(ev({ type: 'assistant', message: { content: [{ type: 'text', text: 'Hel' }] }, timestamp_ms: 1 }), [{ kind: 'text', text: 'Hel', partial: true }])
  assert.deepEqual(ev({ type: 'assistant', message: { content: [{ type: 'text', text: 'lo' }] }, timestamp_ms: 2 }), [{ kind: 'text', text: 'lo', partial: true }])
  assert.equal(run.current, 'Hello')
  assert.deepEqual(ev({ type: 'assistant', message: { content: [{ type: 'text', text: 'Hello' }] } }), [{ kind: 'text', text: 'Hello', partial: false }])
  assert.equal(run.output, 'Hello')
  assert.equal(run.current, '')
  const tool = ev({ type: 'tool_call', subtype: 'started', tool_call: { shellToolCall: { args: { command: 'ls -la' } } } })
  assert.deepEqual(tool, [{ kind: 'tool', text: 'shell: ls -la', phase: 'started' }])
  assert.equal(run.tools, 1)
  ev({ type: 'tool_call', subtype: 'completed', tool_call: { shellToolCall: { args: { command: 'ls -la' } } } })
  assert.equal(run.tools, 1, 'a completed tool is not counted twice')
  const done = ev({ type: 'result', subtype: 'success', result: 'Hello', session_id: 'chat-9', duration_ms: 12 })
  assert.deepEqual(done, [{ kind: 'done', text: 'Hello', session_id: 'chat-9', duration_ms: 12 }])
  assert.equal(run.output, 'Hello', 'the final text is not appended twice')
  const fail = normalise('cursor', { type: 'result', subtype: 'error', is_error: true, result: 'boom' }, new Run('r', 'cursor', '', '', 'x'))
  assert.equal(fail[0].kind, 'error')
})

test('runner: Codex --json → thread.started, items, turn.completed / failed', () => {
  const run = new Run('run_2', 'codex', '', '', 'hi')
  const ev = (obj) => normalise('codex', obj, run)
  assert.deepEqual(ev({ type: 'thread.started', thread_id: 'th-1' }), [{ kind: 'started', text: '', session_id: 'th-1' }])
  assert.deepEqual(ev({ type: 'item.started', item: { type: 'command_execution', command: 'pytest -q' } }), [{ kind: 'tool', text: 'shell: pytest -q', phase: 'started' }])
  assert.equal(run.tools, 0)
  assert.deepEqual(ev({ type: 'item.completed', item: { type: 'command_execution', command: 'pytest -q' } }), [{ kind: 'tool', text: 'shell: pytest -q', phase: 'completed' }])
  assert.equal(run.tools, 1)
  assert.deepEqual(ev({ type: 'item.completed', item: { type: 'file_change', changes: [{ path: 'a.py' }, { path: 'b.py' }] } }), [{ kind: 'tool', text: 'edit: a.py, b.py', phase: 'completed' }])
  assert.deepEqual(ev({ type: 'item.completed', item: { type: 'mcp_tool_call', server: 'gh', tool: 'issues' } }), [{ kind: 'tool', text: 'tool: gh/issues', phase: 'completed' }])
  assert.deepEqual(ev({ type: 'item.completed', item: { type: 'reasoning', text: 'thinking' } }), [])
  assert.deepEqual(ev({ type: 'item.completed', item: { type: 'agent_message', text: 'All green.' } }), [{ kind: 'text', text: 'All green.' }])
  assert.deepEqual(ev({ type: 'turn.completed', usage: { input_tokens: 1 } }), [{ kind: 'done', text: 'All green.', session_id: 'th-1', usage: { input_tokens: 1 } }])
  assert.deepEqual(ev({ type: 'turn.failed', error: { message: 'quota' } }), [{ kind: 'error', text: 'quota' }])
  assert.deepEqual(ev({ type: 'error', message: 'plain' }), [{ kind: 'error', text: 'plain' }])
})

test('runner: Claude stream-json → init, text and tool_use blocks, result', () => {
  const run = new Run('run_3', 'claude', '', '', 'hi')
  const ev = (obj) => normalise('claude', obj, run)
  assert.deepEqual(ev({ type: 'system', subtype: 'init', session_id: 'cs-1', model: 'claude-x' }), [{ kind: 'started', text: '', session_id: 'cs-1', model: 'claude-x' }])
  const mixed = ev({ type: 'assistant', message: { content: [{ type: 'text', text: 'Looking.' }, { type: 'tool_use', name: 'Read', input: { file_path: '/w/a.py' } }] } })
  assert.deepEqual(mixed, [
    { kind: 'text', text: 'Looking.' },
    { kind: 'tool', text: 'Read: /w/a.py', phase: 'started' },
  ])
  assert.equal(run.tools, 1)
  assert.deepEqual(ev({ type: 'result', result: 'Looking.\nDone.', session_id: 'cs-1', duration_ms: 5 }), [{ kind: 'done', text: 'Looking.\nDone.', session_id: 'cs-1', duration_ms: 5 }])
  assert.equal(run.output, 'Looking.\nLooking.\nDone.')
  assert.equal(normalise('claude', { type: 'result', is_error: true, result: 'nope' }, run)[0].kind, 'error')
  assert.deepEqual(normalise('claude', { type: 'rate_limit' }, run), [])
})

test('runner: dsh headless --json → session, text, tools, final, and the error it reports', () => {
  const run = new Run('run_dsh', 'dsh', '', '', 'hi')
  const ev = (obj) => normalise('dsh', obj, run)
  // the opening line `dsh --profile headless --json` writes first
  assert.deepEqual(ev({ type: 'session', sessionId: 'session-abc', cwd: '/w' }), [{ kind: 'started', text: '', session_id: 'session-abc', cwd: '/w' }])
  assert.equal(run.result_session_id, 'session-abc')
  // the status lines carry no words of their own
  assert.deepEqual(ev({ type: 'status', phase: 'turn_start', turn: 1 }), [])
  assert.deepEqual(ev({ type: 'status', phase: 'step_start', turn: 1, step: 1 }), [])
  assert.deepEqual(ev({ type: 'thinking', text: 'let me look' }), [], 'reasoning is not the agent’s answer')
  assert.deepEqual(ev({ type: 'text', text: 'Two files changed.' }), [{ kind: 'text', text: 'Two files changed.' }])
  assert.equal(run.output, 'Two files changed.')
  assert.deepEqual(ev({ type: 'tool_call', callId: 'c1', tool: 'bash', input: { command: 'ls -la' } }), [{ kind: 'tool', text: 'bash: ls -la', phase: 'started' }])
  assert.equal(run.tools, 1)
  assert.deepEqual(ev({ type: 'tool_result', callId: 'c1', status: 'completed', result: 'ok' }), [{ kind: 'tool', text: 'completed', phase: 'completed' }])
  const done = ev({ type: 'final', text: 'Two files changed.' })
  assert.equal(done[0].kind, 'done')
  assert.equal(done[0].session_id, 'session-abc')
  assert.equal(run.output, 'Two files changed.', 'the final text is not appended twice')
  // a failed turn is reported on its status line
  const failed = normalise('dsh', { type: 'status', phase: 'turn_end', turn: 1, reason: { kind: 'error', error: { code: 'MISSING_CREDENTIAL', message: 'no API key' } } }, new Run('r', 'dsh', '', '', 'x'))
  assert.deepEqual(failed, [{ kind: 'error', text: 'no API key' }])
})

test('runner: the run view, the saved shape read back, the continuation message', () => {
  const run = new Run('run_4', 'codex', 'asked', '/w', 'do it')
  run.result_session_id = 'got'
  run.current = 'streaming'
  const view = run.view()
  assert.deepEqual(Object.keys(view), ['id', 'agent', 'session_id', 'asked_session_id', 'workspace', 'text', 'started_at', 'ended_at', 'status', 'output', 'resumed', 'error', 'tools'])
  assert.equal(view.session_id, 'got')
  assert.equal(view.asked_session_id, 'asked')
  assert.equal(view.output, '\nstreaming')
  assert.equal(view.status, 'running')
  assert.equal(view.ended_at, null)
  run.device = 'Laptop'
  assert.equal(run.view().device, 'Laptop')

  const back = runFromView({ ...view, status: 'running' })
  assert.equal(back.status, 'stopped', 'a run still going at the last shutdown comes back as stopped')
  assert.ok(back.error)
  assert.equal(back.session_id, 'asked')
  assert.equal(back.result_session_id, 'got')
  assert.equal(runFromView({ id: 'x', agent: 'nope' }), undefined)

  const text = continuation({ title: 'Old chat', transcript: [{ role: 'user', text: 'a' }, { role: 'assistant', text: 'b' }, { role: 'user', text: 'c' }] }, 'now this')
  assert.ok(text.startsWith("Continuing an earlier chat titled 'Old chat'."))
  assert.ok(text.includes('assistant: b\nuser: c'))
  assert.ok(text.endsWith('Now: now this'))
})

/** A fake `claude` that prints stream-json, lingers a little past its result, and exits. */
async function fakeClaude(dir, { linger = '0', fail = false, failureExitCode = 1 } = {}) {
  const script = join(dir, 'fake-claude.mjs')
  await writeFile(
    script,
    `
const args = process.argv.slice(2)
const text = args[args.length - 1]
const resume = args.indexOf('--resume')
if (resume >= 0 && args[resume + 1] === 'ghost') { console.error('No conversation found with session ID: ghost'); process.exit(1) }
const out = (o) => process.stdout.write(JSON.stringify(o) + '\\n')
out({ type: 'system', subtype: 'init', session_id: 'fake-1', model: 'fake' })
out({ type: 'assistant', message: { content: [{ type: 'tool_use', name: 'Bash', input: { command: 'echo hi' } }] } })
out({ type: 'assistant', message: { content: [{ type: 'text', text: 'You said: ' + text }] } })
${fail ? "out({ type: 'result', is_error: true, result: 'the model refused' })" : "out({ type: 'result', result: 'You said: ' + text, session_id: 'fake-1', duration_ms: 3 })"}
process.stdout.write('garbage line\\n')
setTimeout(() => process.exit(${fail ? failureExitCode : 0}), ${linger})
`,
  )
  const bin = join(dir, 'bin')
  await mkdir(bin, { recursive: true })
  if (posix) {
    const cli = join(bin, 'claude')
    await writeFile(cli, `#!/bin/sh\nexec "${process.execPath}" "${script}" "$@"\n`)
    await chmod(cli, 0o755)
    return cli
  }
  const cli = join(bin, 'claude.cmd')
  await writeFile(cli, `@node "${script}" %*\r\n`)
  return cli
}

test('runner: stopping a run ends the whole tree on Windows', { skip: posix, timeout: 30_000 }, async (t) => {
  await scratch(async (dir) => {
    const marker = join(dir, 'helper.pid')
    // a fake CLI shaped like the real ones: it starts a helper (the header's `cursor-agent`
    // leaves a worker server behind) and then keeps running until somebody stops it
    const cli = spawn(process.execPath, ['-e', [
      `const { spawn } = require('node:child_process')`,
      `const { writeFileSync } = require('node:fs')`,
      `const helper = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore', detached: true })`,
      `helper.unref()`,
      `writeFileSync(${JSON.stringify(marker)}, String(helper.pid))`,
      `setInterval(() => {}, 1000)`,
    ].join('\n')], { stdio: 'ignore' })
    const run = new Run('run_tree', 'claude', '', '', 'hi')
    run.process = cli
    let helper = 0
    t.after(() => {
      try { cli.kill() } catch {}
      if (helper) { try { process.kill(helper) } catch {} }
    })
    const exited = new Promise((resolve) => cli.once('exit', resolve))
    for (let i = 0; i < 100 && !helper; i++) {
      try { helper = Number(await readFile(marker, 'utf8')) } catch { await new Promise((r) => setTimeout(r, 50)) }
    }
    assert.ok(helper, 'the CLI started its helper')
    assert.equal(run.stop(), true)
    await exited
    let gone = false
    for (let i = 0; i < 100 && !gone; i++) {
      try { process.kill(helper, 0) } catch { gone = true }
      if (!gone) await new Promise((r) => setTimeout(r, 50))
    }
    assert.ok(gone, 'the helper the CLI left behind is stopped with it')
  })
})

test('runner: a run against a fake CLI streams events and ends at the terminal event', async () => {
  await scratch(async (dir) => {
    const cli = await fakeClaude(dir, { linger: '200' })
    const events = []
    const run = await startRun({ agent: 'claude', text: 'hello', which: () => cli, onEvent: (e) => events.push(e), timeoutMs: 20_000, readerEnv: { NANOMUSE_CODING_HOME: join(dir, 'nohome') } })
    assert.equal(run.status, 'done', run.error)
    assert.equal(run.result_session_id, 'fake-1')
    assert.equal(run.tools, 1)
    assert.equal(run.output, 'You said: hello')
    assert.deepEqual(events.map((e) => e.kind), ['started', 'tool', 'text', 'done'])
    assert.ok(events.every((e) => e.run === run.id), 'every event carries the run id')
    assert.equal(run.view().session_id, 'fake-1')
    assert.equal(typeof run.ended_at, 'number')
  })
})

test('runner: a failed resume of an unknown session goes out again as a new chat', async () => {
  await scratch(async (dir) => {
    const cli = await fakeClaude(dir)
    const events = []
    const run = await startRun({ agent: 'claude', text: 'again', sessionId: 'ghost', which: () => cli, onEvent: (e) => events.push(e), timeoutMs: 20_000, readerEnv: { NANOMUSE_CODING_HOME: join(dir, 'nohome') } })
    assert.equal(run.status, 'done', run.error)
    assert.equal(run.resumed, false)
    assert.equal(run.session_id, 'ghost')
    assert.equal(run.view().session_id, 'fake-1')
    const note = events.find((e) => e.kind === 'tool' && e.phase === 'note')
    assert.ok(note, 'the apps are told the chat went out as a new one')
  })
})

/** A fake `cursor-agent`: a resume of a dead chat streams half a line before the CLI
 * admits it knows no such session; the fresh chat that follows answers from a delta. */
async function fakeCursorDeadDelta(dir) {
  const script = join(dir, 'fake-cursor-dead-delta.mjs')
  await writeFile(
    script,
    `
const args = process.argv.slice(2)
const text = args[args.length - 1]
const out = (o) => process.stdout.write(JSON.stringify(o) + '\\n')
if (args.includes('--resume')) {
  out({ type: 'assistant', message: { content: [{ type: 'text', text: 'half a sentence from the dead chat' }] }, timestamp_ms: 1 })
  console.error('No conversation found with session ID: ghost')
  process.exit(1)
}
out({ type: 'system', subtype: 'init', session_id: 'fresh-1', model: 'fake' })
out({ type: 'assistant', message: { content: [{ type: 'text', text: 'Fresh start: ' + text }] }, timestamp_ms: 2 })
out({ type: 'result', result: 'Fresh start: ' + text, session_id: 'fresh-1', duration_ms: 3 })
`,
  )
  const bin = join(dir, 'bin')
  await mkdir(bin, { recursive: true })
  if (posix) {
    const cli = join(bin, 'cursor-agent')
    await writeFile(cli, `#!/bin/sh\nexec "${process.execPath}" "${script}" "$@"\n`)
    await chmod(cli, 0o755)
    return cli
  }
  const cli = join(bin, 'cursor-agent.cmd')
  await writeFile(cli, `@node "${script}" %*\r\n`)
  return cli
}

test('runner: the retry after an unknown session does not splice in the dead chat\'s half line', async () => {
  await scratch(async (dir) => {
    const cli = await fakeCursorDeadDelta(dir)
    const events = []
    const run = await startRun({ agent: 'cursor', text: 'again', sessionId: 'ghost', which: () => cli, onEvent: (e) => events.push(e), timeoutMs: 20_000, readerEnv: { NANOMUSE_CODING_HOME: join(dir, 'nohome') } })
    assert.equal(run.status, 'done', run.error)
    assert.equal(run.view().output, 'Fresh start: again')
    assert.equal(run.view().session_id, 'fresh-1')
    assert.ok(events.some((e) => e.kind === 'tool' && e.phase === 'note'), 'the apps are told the chat went out as a new one')
  })
})

test('runner: an error result and a missing CLI are failed runs', async () => {
  await scratch(async (dir) => {
    const cli = await fakeClaude(dir, { fail: true })
    const run = await startRun({ agent: 'claude', text: 'x', which: () => cli, timeoutMs: 20_000, readerEnv: { NANOMUSE_CODING_HOME: join(dir, 'nohome') } })
    assert.equal(run.status, 'failed')
    assert.equal(run.error, 'the model refused')
    const none = await startRun({ agent: 'codex', text: 'x', which: () => undefined })
    assert.equal(none.status, 'failed')
    assert.match(none.error, /Codex is not installed/)
  })
})

test('runner: a terminal error stays failed even after text and a zero exit', { skip: !posix }, async () => {
  await scratch(async (dir) => {
    const cli = await fakeClaude(dir, { fail: true, failureExitCode: 0 })
    const run = await startRun({ agent: 'claude', text: 'test', which: () => cli, timeoutMs: 10_000, readerEnv: { NANOMUSE_CODING_HOME: join(dir, 'nohome') } })
    assert.equal(run.status, 'failed')
    assert.equal(run.error, 'the model refused')
  })
})

// ------------------------------------------------------------------ the service and the hub shapes

test('Codex writer conflicts require confirmation, not a silent fallback', { skip: !posix }, async () => {
  await scratch(async (dir) => {
    await fixtureHome(dir)
    const cli = join(dir, 'fake-codex')
    const calls = join(dir, 'calls')
    await writeFile(cli, `#!/bin/sh
echo call >> "${calls}"
if [ "$2" = "resume" ]; then
  echo 'Error: thread/resume: thread/resume failed: thread 0f9a7b6c-1111-2222-3333-444455556666 already has an active writer (code -32600)' >&2
  exit 1
fi
echo '{"type":"thread.started","thread_id":"new-thread"}'
echo '{"type":"item.completed","item":{"id":"a","type":"agent_message","text":"done"}}'
echo '{"type":"turn.completed"}'
`)
    await chmod(cli, 0o755)
    const env = { ...process.env, NANOMUSE_CODING_HOME: dir, CODEX_HOME: join(dir, '.codex') }
    const diagnostics = []
    const run = await startRun({ agent: 'codex', text: 'how many?', sessionId: '0f9a7b6c-1111-2222-3333-444455556666', which: () => cli, env, readerEnv: env, onDiagnostic: (entry) => diagnostics.push(entry) })
    assert.equal(run.status, 'failed')
    assert.ok(run.resume_conflict)
    assert.match(run.resume_conflict.continuation, /^Continuing an earlier chat/)
    assert.ok(run.resume_conflict.continuation.endsWith('Now: how many?'))
    assert.equal((await readFile(calls, 'utf8')).trim(), 'call')
    assert.deepEqual(runFromView(run.view()).resume_conflict, run.resume_conflict)
    const failed = diagnostics.find((entry) => entry.stage === 'attempt_failed')
    assert.equal(failed.lock_error, true)
    assert.equal(failed.exit_code, 1)
    assert.equal(diagnostics.filter((entry) => entry.stage === 'attempt').length, 1)
    assert.equal(diagnostics.at(-1).conflict, true)
    assert.ok(diagnostics.every((entry) => entry.revision === 'coding-resume-v2'))
    assert.equal(JSON.stringify(diagnostics).includes('how many?'), false)
    assert.equal(JSON.stringify(diagnostics).includes(dir), false)
    assert.equal(JSON.stringify(diagnostics).includes('failed to resume: thread writer'), false)
    const fresh = await startRun({ agent: 'codex', text: run.resume_conflict.continuation, workspace: run.workspace, which: () => cli, env, readerEnv: env })
    assert.equal(fresh.status, 'done')
    assert.equal(fresh.text, run.resume_conflict.continuation)
    assert.equal(fresh.resumed, false)
    assert.equal(fresh.result_session_id, 'new-thread')
    await writeFile(cli, `#!/bin/sh
echo call >> "${calls}"
echo '{"type":"turn.failed","error":{"message":"failed to resume: authentication expired"}}'
exit 1
`)
    const auth = await startRun({ agent: 'codex', text: 'test', sessionId: '0f9a7b6c-1111-2222-3333-444455556666', which: () => cli, env, readerEnv: env, onDiagnostic: () => { throw new Error('logger unavailable') } })
    assert.equal(auth.status, 'failed')
    assert.equal(auth.resume_conflict, undefined)
    assert.equal((await readFile(calls, 'utf8')).trim().split('\n').length, 3)
  })
})

test('runner: a provider failure after a tool does not repeat its effects in a new chat', async () => {
  await scratch(async (dir) => {
    const script = join(dir, 'fake-codex.mjs')
    const calls = join(dir, 'effects')
    const cli = join(dir, posix ? 'fake-codex' : 'fake-codex.cmd')
    await writeFile(cli, posix
      ? `#!/bin/sh\nexec "${process.execPath}" "${script}" "$@"\n`
      : `@"${process.execPath}" "${script}" %*\r\n`)
    await chmod(cli, 0o755)
    for (const phase of ['item.started', 'item.completed']) {
      const rows = [
        { type: 'thread.started', thread_id: 'existing-session' },
        { type: phase, item: { id: 'command-1', type: 'command_execution', command: 'record-effect', aggregated_output: 'effect recorded', exit_code: 0 } },
        { type: 'turn.failed', error: { message: 'response resource not found' } },
      ]
      await writeFile(calls, '')
      await writeFile(script, `import fs from 'node:fs';\nfs.appendFileSync(${JSON.stringify(calls)}, 'effect\\n');\nfor (const row of ${JSON.stringify(rows)}) console.log(JSON.stringify(row));\nprocess.exitCode = 1;\n`)
      const env = { ...process.env, NANOMUSE_CODING_HOME: join(dir, 'empty-home') }
      const run = await startRun({ agent: 'codex', text: 'act once', sessionId: 'existing-session', which: () => cli, env, readerEnv: env, timeoutMs: 10_000 })
      assert.equal(run.status, 'failed', phase)
      assert.equal(run.resumed, true, phase)
      assert.equal(run.error, 'response resource not found', phase)
      assert.equal((await readFile(calls, 'utf8')).trim(), 'effect', phase)
    }
  })
})

test('Codex lock recognition excludes authentication and filesystem failures', () => {
  assert.ok(isResumeLockError('Error: thread/resume: thread/resume failed: thread 0f9a7b6c-1111-2222-3333-444455556666 already has an active writer (code -32600)'))
  assert.ok(isResumeLockError('session already registered for process 123'))
  assert.ok(isResumeLockError('thread writer lock held by another Codex process'))
  assert.equal(isResumeLockError('resume failed: authentication expired'), false)
  assert.equal(isResumeLockError('failed to open thread writer lock: permission denied'), false)
})

function fakeHub(devices = []) {
  const calls = []
  return {
    deviceId: 'pc-self',
    devices,
    find: (ref) => devices.find((d) => d.id === ref || d.name.toLowerCase() === ref.toLowerCase()),
    calls,
    async call(to, action, args, options) {
      calls.push({ to, action, args })
      if (action === 'coding.send') {
        options?.onEvent?.({ kind: 'started', run: 'remote-run', session_id: 'rs-1' })
        options?.onEvent?.({ kind: 'text', run: 'remote-run', text: 'far away', partial: false })
        options?.onEvent?.({ kind: 'tool', run: 'remote-run', text: 'shell: ls', phase: 'started' })
        return { id: 'remote-run', agent: args.agent, session_id: 'rs-1', asked_session_id: '', workspace: '', text: args.text, started_at: 1, ended_at: 2, status: 'done', output: 'far away', resumed: false, error: '', tools: 1 }
      }
      if (action === 'coding.agents') return { agents: [] }
      if (action === 'coding.sessions') return { sessions: [] }
      return {}
    },
  }
}

test('service: the action names and the gate match the runtime', () => {
  assert.deepEqual([...CODING_ACTIONS], ['coding.agents', 'coding.sessions', 'coding.session', 'coding.send', 'coding.stop', 'coding.runs', 'coding.projects', 'coding.item', 'coding.diff', 'coding.watch', 'coding.project.validate'])
  assert.deepEqual([...GATED_CODING_ACTIONS].sort(), ['coding.send', 'coding.stop'])
  assert.equal(codingBrief('coding.send', { agent: 'codex', text: '  add   a test\nplease ' }), 'Codex: add a test please')
  assert.equal(codingBrief('coding.stop', { run: 'run_1' }), 'run_1')
  assert.equal(codingBrief('coding.agents', {}), '')
})

test('service: coding.agents / sessions / session / runs answer in the runtime shapes', async () => {
  await scratch(async (home) => {
    const { ws } = await fixtureHome(home)
    const env = { ...process.env, NANOMUSE_CODING_HOME: home, PATH: join(home, 'emptybin') }
    const svc = new CodingService({ hub: fakeHub(), env, storePath: join(home, 'state', 'runs.json') })
    const agents = await svc.handle('coding.agents', {})
    assert.equal(agents.agents.length, 4)
    assert.ok(agents.agents.every((a) => a.installed && a.cli === null), 'stores without CLIs')
    const list = await svc.handle('coding.sessions', { agent: 'cursor', limit: 10 })
    assert.equal(list.sessions.length, 2)
    const byWs = await svc.handle('coding.sessions', { workspace: ws })
    assert.equal(byWs.sessions.length, 5)
    const one = await svc.handle('coding.session', { agent: 'codex', session_id: '0f9a7b6c-1111-2222-3333-444455556666' })
    assert.equal(one.transcript.length, 2)
    assert.ok(!('runs' in one), 'no runs on it yet')
    await assert.rejects(svc.handle('coding.session', { agent: 'codex', session_id: 'missing' }), (e) => e.code === 'no_session')
    await assert.rejects(svc.handle('coding.sessions', { agent: 'emacs' }), (e) => e.code === 'unknown_agent')
    await assert.rejects(svc.handle('coding.send', { agent: 'codex', text: 'hi' }), (e) => e.code === 'not_installed')
    await assert.rejects(svc.handle('coding.send', { agent: 'codex', text: '' }), (e) => e.code === 'usage')
    await assert.rejects(svc.handle('coding.nope', {}), (e) => e.code === 'unknown_action')
    assert.deepEqual(await svc.handle('coding.runs', {}), { runs: [] })
    assert.deepEqual(await svc.handle('coding.stop', { run: 'none' }), { stopped: false })
  })
})

test('service: coding.send with wait streams event frames with the run id and answers with the run; the record survives', async () => {
  await scratch(async (dir) => {
    const cli = await fakeClaude(dir)
    const store = join(dir, 'state', 'coding', 'runs.json')
    const env = { ...process.env, NANOMUSE_CODING_HOME: join(dir, 'nohome') }
    const svc = new CodingService({ hub: fakeHub(), env, which: (a) => (a === 'claude' ? cli : undefined), storePath: store })
    const frames = []
    const bus = []
    svc.subscribe((m) => bus.push(m))
    const result = await svc.handle('coding.send', { agent: 'claude', text: 'ping' }, { id: 'c1', from: { id: 'ph', name: 'Phone', kind: 'phone' }, event: (b) => frames.push(b) })
    assert.equal(result.status, 'done', result.error)
    assert.equal(result.session_id, 'fake-1')
    assert.ok(result.id.startsWith('run_'))
    assert.deepEqual(frames.map((f) => f.kind), ['started', 'started', 'tool', 'text'], 'the start acknowledgement precedes CLI events; done is the result')
    assert.ok(frames.every((f) => f.run === result.id))
    assert.ok(bus.some((m) => m.kind === 'coding' && m.event.kind === 'run' && m.run?.status === 'done'), 'the bus hears the finished run')
    assert.equal((await svc.handle('coding.runs', {})).runs[0].id, result.id)
    const session = await svc.handle('coding.sessions', {})
    assert.deepEqual(session, { sessions: [] }, 'the fake left nothing on disk')

    // written to disk and read back by a fresh service
    const rows = JSON.parse(await readFile(store, 'utf8'))
    assert.equal(rows.length, 1)
    assert.equal(rows[0].id, result.id)
    const again = new CodingService({ hub: fakeHub(), env, storePath: store })
    assert.equal((await again.handle('coding.runs', {})).runs[0].output, 'You said: ping')

    // without wait: the run comes back at once, still running, then settles
    const quick = await svc.handle('coding.send', { agent: 'claude', text: 'pong', wait: false })
    assert.equal(quick.status, 'running')
    const startedWatch = await svc.handle('coding.watch', { agent: 'claude', session_id: '', run_id: quick.id })
    assert.equal(startedWatch.runs[0].id, quick.id)
    await new Promise((r) => setTimeout(r, 1500))
    assert.equal(svc.listRuns().find((r) => r.id === quick.id).status, 'done')
    const doneWatch = await svc.handle('coding.watch', { agent: 'claude', session_id: '', run_id: quick.id })
    assert.equal(doneWatch.status, 'done')
    assert.equal(doneWatch.runs[0].session_id, 'fake-1')
    assert.equal(doneWatch.runs[0].output, 'You said: pong')
  })
})

test('service: another computer’s agents through the hub, and a remote send followed as a shadow run', async () => {
  const hub = fakeHub([
    { id: 'pc-2', name: 'Studio', online: true, actions: [...CODING_ACTIONS] },
    { id: 'pc-old', name: 'Old', online: true, actions: ['info'] },
    { id: 'pc-off', name: 'Away', online: false, actions: [...CODING_ACTIONS] },
  ])
  const svc = new CodingService({ hub, env: { ...process.env, NANOMUSE_CODING_HOME: '/nonexistent/nanomuse-test' } })
  assert.deepEqual(await svc.remote('pc-2', 'coding.agents', {}), { agents: [] })
  assert.deepEqual(await svc.remote('studio', 'coding.sessions', { limit: 5 }), { sessions: [] })
  await assert.rejects(svc.remote('pc-old', 'coding.agents', {}), (e) => e.code === 'not_supported')
  await assert.rejects(svc.remote('pc-off', 'coding.agents', {}), (e) => e.code === 'device_offline')
  await assert.rejects(svc.remote('pc-none', 'coding.agents', {}), (e) => e.code === 'no_device')

  const bus = []
  svc.subscribe((m) => bus.push(m))
  const shadow = await svc.remoteSend('pc-2', { agent: 'codex', text: 'build it' })
  assert.equal(shadow.status, 'running')
  assert.equal(shadow.device, 'Studio')
  await new Promise((r) => setTimeout(r, 20))
  const done = svc.listRuns().find((r) => r.id === shadow.id)
  assert.equal(done.status, 'done')
  assert.equal(done.output, 'far away')
  assert.equal(done.session_id, 'rs-1')
  assert.equal(done.tools, 1)
  assert.equal(done.device, 'Studio')
  assert.ok(bus.every((m) => m.device === 'Studio'))
  assert.deepEqual(hub.calls[hub.calls.length - 1].args, { agent: 'codex', text: 'build it', wait: true })
})

test('remote: a tool call counts once whatever phases the CLI emits, and notes never', async () => {
  const svc = new CodingService({ hub: fakeHub(), env: { ...process.env, NANOMUSE_CODING_HOME: '/nonexistent/nanomuse-test' } })
  svc.remote = async (_device, _action, _args, onEvent) => {
    onEvent({ kind: 'tool', text: 'started a call', phase: 'started' })
    onEvent({ kind: 'tool', text: 'the call finished', phase: 'completed' })
    onEvent({ kind: 'tool', text: 'an IDE-only note', phase: 'note' })
    onEvent({ kind: 'text', text: 'done text' })
    return { id: 'run_x', agent: 'codex', session_id: 's1', asked_session_id: 's1', workspace: '', text: 'do it',
      started_at: 1, ended_at: 2, status: 'done', output: 'done text', resumed: false, error: '', tools: 1 }
  }
  const view = await svc.remoteSend('other-pc', { agent: 'codex', text: 'do it' })
  assert.equal(view.tools, 1, 'one tool call is one step, on whatever computer it ran')
})

test('remote: streamed tool counts match each runner before a final result arrives', async () => {
  const cases = {
    codex: [
      { type: 'item.started', item: { type: 'command_execution', command: 'test' } },
      { type: 'item.completed', item: { type: 'command_execution', command: 'test' } },
      { type: 'item.completed', item: { type: 'patch' } },
    ],
    dsh: [{ type: 'tool_call', tool: 'shell' }, { type: 'tool_result', status: 'completed' }],
    cursor: [{ type: 'tool_call', subtype: 'started' }, { type: 'tool_call', subtype: 'completed' }],
    claude: [{ type: 'assistant', message: { content: [{ type: 'tool_use', name: 'shell' }] } }],
  }
  for (const [agent, frames] of Object.entries(cases)) {
    const svc = new CodingService({ hub: fakeHub(), env: { ...process.env, NANOMUSE_CODING_HOME: '/nonexistent/nanomuse-test' } })
    const local = new Run('local', agent, '', '', 'test')
    let onEvent
    let reject
    svc.remote = (_device, _action, _args, callback) => {
      onEvent = callback
      return new Promise((_resolve, fail) => { reject = fail })
    }
    const shadow = await svc.remoteSend('other-pc', { agent, text: 'test' })
    for (const frame of frames) {
      for (const event of normalise(agent, frame, local)) onEvent(event)
      assert.equal(svc.listRuns().find((run) => run.id === shadow.id).tools, local.tools, agent)
    }
    onEvent({ kind: 'tool', phase: 'note', text: 'note' })
    reject(new Error('connection lost before the final result'))
    await new Promise((resolve) => setImmediate(resolve))
    const failed = svc.listRuns().find((run) => run.id === shadow.id)
    assert.equal(failed.status, 'failed')
    assert.equal(failed.tools, local.tools, 'a missing result must not change the count')
  }
})

test('remote: a final count reconciles missed events and ignores invalid values', async () => {
  for (const [tools, expected] of [[3, 3], [0, 0], [undefined, 1], [-1, 1], [NaN, 1], ['3', 1]]) {
    const svc = new CodingService({ hub: fakeHub(), env: { ...process.env, NANOMUSE_CODING_HOME: '/nonexistent/nanomuse-test' } })
    svc.remote = async (_device, _action, _args, onEvent) => {
      onEvent({ kind: 'tool', phase: 'completed' })
      return { status: 'done', tools }
    }
    const shadow = await svc.remoteSend('other-pc', { agent: 'codex', text: 'test' })
    await new Promise((resolve) => setImmediate(resolve))
    assert.equal(svc.listRuns().find((run) => run.id === shadow.id).tools, expected)
  }
})
