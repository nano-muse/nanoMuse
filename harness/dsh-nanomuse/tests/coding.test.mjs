// The coding agents on this computer (`docs/coding-agents.md`): the three readers on
// fixture stores in the documented formats, the process-count parsers on canned `ps` /
// `tasklist` output, the runner's stream normaliser on canned stream-json lines, a run
// against a fake CLI, and the hub action shapes — the runtime's `to_dict()`s, so the
// phones and the web cannot tell the desktop from the Python runtime.
import assert from 'node:assert/strict'
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { clean, countProcesses, detect, parsePs, parseTasklist, readSession, sessions, sessionsRoot, slugToPath, title, which } from '../lib/coding-readers.js'
import { agentEnv, commandFor, continuation, normalise, Run, runFromView, startRun } from '../lib/coding-runner.js'
import { CODING_ACTIONS, CodingService, codingBrief, GATED_CODING_ACTIONS } from '../lib/coding.js'

const posix = process.platform !== 'win32'

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
  return { ws, slug }
}

const SESSION_KEYS = ['agent', 'id', 'title', 'workspace', 'path', 'created_at', 'updated_at', 'messages', 'status', 'last_user', 'last_assistant', 'source', 'resumable']

test('readers: a fixture home gives one session per agent, in the runtime shape', { skip: !posix }, async () => {
  await scratch(async (home) => {
    const { ws } = await fixtureHome(home)
    const env = { ...process.env, NANOMUSE_CODING_HOME: home }
    assert.equal(sessionsRoot('codex', env), join(home, '.codex', 'sessions'))
    const all = await sessions(undefined, 30, undefined, env)
    assert.equal(all.length, 4)
    for (const s of all) for (const k of SESSION_KEYS) assert.ok(k in s, `${s.agent} session carries ${k}`)
    assert.ok(all.every((s) => !('transcript' in s)), 'the list carries no transcripts')

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

    // by agent, by workspace, and the limit
    assert.equal((await sessions('cursor', 30, undefined, env)).length, 2)
    assert.equal((await sessions(undefined, 30, ws, env)).length, 4)
    assert.equal((await sessions(undefined, 30, join(home, 'elsewhere'), env)).length, 0)
    assert.equal((await sessions(undefined, 1, undefined, env)).length, 1)
  })
})

test('readers: one session comes with its transcript; a bad id is nothing', { skip: !posix }, async () => {
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
    assert.equal(await readSession('claude', 'nope', env), undefined)
    assert.equal(await readSession('cursor', '../ide-1', env), undefined)
    assert.equal(await readSession('cursor', '', env), undefined)
  })
})

test('readers: a missing home is three agents with no sessions', async () => {
  await scratch(async (home) => {
    const env = { ...process.env, NANOMUSE_CODING_HOME: join(home, 'nothing'), PATH: join(home, 'emptybin') }
    assert.deepEqual(await sessions(undefined, 30, undefined, env), [])
    const agents = await detect(false, env)
    assert.deepEqual(agents.map((a) => a.id), ['cursor', 'codex', 'claude'])
    for (const a of agents) {
      assert.deepEqual(Object.keys(a).sort(), ['cli', 'id', 'installed', 'name', 'running', 'sessions_root', 'version'])
      assert.equal(a.installed, false)
      assert.equal(a.cli, null)
      assert.equal(a.sessions_root, '')
      assert.equal(a.running, 0)
    }
  })
})

test('readers: detect sees a store without a CLI, and a CLI on PATH', { skip: !posix }, async () => {
  await scratch(async (home) => {
    await fixtureHome(home)
    const bin = join(home, 'bin')
    await mkdir(bin)
    await writeFile(join(bin, 'codex'), '#!/bin/sh\necho "codex-cli 0.42.0"\n')
    await chmod(join(bin, 'codex'), 0o755)
    const env = { ...process.env, NANOMUSE_CODING_HOME: home, PATH: bin }
    assert.equal(which('codex', env), join(bin, 'codex'))
    assert.equal(which('claude', env), undefined)
    const agents = await detect(true, env)
    const codex = agents.find((a) => a.id === 'codex')
    assert.equal(codex.installed, true)
    assert.equal(codex.cli, join(bin, 'codex'))
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
  assert.deepEqual(countProcesses(ps), { cursor: 3, codex: 1, claude: 1 })

  const tl = parseTasklist(['"System Idle Process","0","Services","0","8 K"', '"node.exe","1234","Console","1","50,000 K"', '"node.exe","1235","Console","1","50,000 K"', '"codex.exe","99","Console","1","1 K"', '"Claude.exe","98","Console","1","1 K"'].join('\r\n'), ['"C:\\Program Files\\nodejs\\node.exe" C:\\Users\\me\\AppData\\cursor-agent\\index.js', '"C:\\Program Files\\nodejs\\node.exe" something-else.js'])
  assert.equal(tl.length, 5)
  assert.deepEqual(tl[1], ['node.exe', '"C:\\Program Files\\nodejs\\node.exe" C:\\Users\\me\\AppData\\cursor-agent\\index.js'])
  assert.deepEqual(tl[2], ['node.exe', '"C:\\Program Files\\nodejs\\node.exe" something-else.js'])
  assert.deepEqual(countProcesses(tl), { cursor: 1, codex: 1, claude: 1 })
  // our own command line never matches: there is no `pgrep -f`, only names and node's argv
  assert.deepEqual(countProcesses([['python3', 'python3 -m nanomuse serve --coding cursor-agent']]), { cursor: 0, codex: 0, claude: 0 })
})

test('runner: the command lines the docs give', () => {
  assert.deepEqual(commandFor('cursor', '/u/cursor-agent', 'abc', '/w', 'hi there', true), ['/u/cursor-agent', '-p', '--output-format', 'stream-json', '--stream-partial-output', '--force', '--resume', 'abc', '--workspace', '/w', 'hi there'])
  assert.deepEqual(commandFor('cursor', '/u/cursor-agent', 'abc', '', 'hi', false), ['/u/cursor-agent', '-p', '--output-format', 'stream-json', '--stream-partial-output', '--force', 'hi'])
  assert.deepEqual(commandFor('codex', 'codex', 'th1', '/w', 'go', true), ['codex', 'exec', 'resume', 'th1', '--json', '--skip-git-repo-check', '-c', 'sandbox_mode="workspace-write"', 'go'])
  assert.deepEqual(commandFor('codex', 'codex', '', '/w', 'go', false), ['codex', 'exec', '--json', '--skip-git-repo-check', '-c', 'sandbox_mode="workspace-write"', '-C', '/w', 'go'])
  assert.deepEqual(commandFor('claude', 'claude', 's1', '/w', 'go', true), ['claude', '-p', '--output-format', 'stream-json', '--verbose', '--permission-mode', 'acceptEdits', '--resume', 's1', 'go'])
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
async function fakeClaude(dir, { linger = '0', fail = false } = {}) {
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
setTimeout(() => process.exit(${fail ? 1 : 0}), ${linger})
`,
  )
  const bin = join(dir, 'bin')
  await mkdir(bin, { recursive: true })
  const cli = join(bin, 'claude')
  await writeFile(cli, `#!/bin/sh\nexec "${process.execPath}" "${script}" "$@"\n`)
  await chmod(cli, 0o755)
  return cli
}

test('runner: a run against a fake CLI streams events and ends at the terminal event', { skip: !posix }, async () => {
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

test('runner: a failed resume of an unknown session goes out again as a new chat', { skip: !posix }, async () => {
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

test('runner: an error result and a missing CLI are failed runs', { skip: !posix }, async () => {
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

// ------------------------------------------------------------------ the service and the hub shapes

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
  assert.deepEqual([...CODING_ACTIONS], ['coding.agents', 'coding.sessions', 'coding.session', 'coding.send', 'coding.stop', 'coding.runs'])
  assert.deepEqual([...GATED_CODING_ACTIONS].sort(), ['coding.send', 'coding.stop'])
  assert.equal(codingBrief('coding.send', { agent: 'codex', text: '  add   a test\nplease ' }), 'Codex: add a test please')
  assert.equal(codingBrief('coding.stop', { run: 'run_1' }), 'run_1')
  assert.equal(codingBrief('coding.agents', {}), '')
})

test('service: coding.agents / sessions / session / runs answer in the runtime shapes', { skip: !posix }, async () => {
  await scratch(async (home) => {
    const { ws } = await fixtureHome(home)
    const env = { ...process.env, NANOMUSE_CODING_HOME: home, PATH: join(home, 'emptybin') }
    const svc = new CodingService({ hub: fakeHub(), env, storePath: join(home, 'state', 'runs.json') })
    const agents = await svc.handle('coding.agents', {})
    assert.equal(agents.agents.length, 3)
    assert.ok(agents.agents.every((a) => a.installed && a.cli === null), 'stores without CLIs')
    const list = await svc.handle('coding.sessions', { agent: 'cursor', limit: 10 })
    assert.equal(list.sessions.length, 2)
    const byWs = await svc.handle('coding.sessions', { workspace: ws })
    assert.equal(byWs.sessions.length, 4)
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

test('service: coding.send with wait streams event frames with the run id and answers with the run; the record survives', { skip: !posix }, async () => {
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
    assert.deepEqual(frames.map((f) => f.kind), ['started', 'tool', 'text'], 'done is the result, not an event')
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
    await new Promise((r) => setTimeout(r, 1500))
    assert.equal(svc.listRuns().find((r) => r.id === quick.id).status, 'done')
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
