/**
 * Sending a message into a coding agent's session through its command line, and reading
 * the stream of what it does — a port of the runtime's `nanomuse/coding/runner.py`.
 *
 *     cursor-agent -p --output-format stream-json --stream-partial-output --force [--resume <id>] [--workspace <dir>] <text>
 *     codex exec [resume <id>] --json --skip-git-repo-check -c sandbox_mode="workspace-write" [-C <dir>] <text>
 *     claude -p --output-format stream-json --verbose --permission-mode acceptEdits [--resume <id>] <text>
 *     dsh --profile headless --json [--session-id <id>] <text>
 *
 * Each prints one JSON object a line; the shapes differ, so `normalise` turns them into
 * the few kinds the apps show: `started`, `text` (the agent's words), `tool` (something it
 * did), `done` (with the final text and the session id to resume next time), `error`.
 * A run is one process; the runner stops reading at the agent's terminal event, not at
 * pipe EOF (`cursor-agent` leaves a worker server behind that would hold the pipe open),
 * then waits for the process and kills it after a grace period. `Run.stop()` ends the
 * process group.
 */
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { stat } from 'node:fs/promises'
import { join } from 'node:path'
import { AGENTS, cliFor, home, readSession, type AgentId, type CodingSession } from './coding-readers.ts'

export const RUN_TIMEOUT_MS = 20 * 60 * 1000
/** Characters of agent text kept per run. */
export const OUTPUT_LIMIT = 200_000

/** `Run.to_dict()` of the runtime: what the apps and the hub see. */
export interface RunView {
  id: string
  agent: AgentId
  session_id: string
  asked_session_id: string
  workspace: string
  text: string
  started_at: number
  ended_at: number | null
  status: RunStatus
  output: string
  resumed: boolean
  error: string
  tools: number
  /** The other computer this ran on, when it did. */
  device?: string
}

export type RunStatus = 'running' | 'done' | 'failed' | 'stopped'

export interface RunEvent {
  kind: 'started' | 'text' | 'tool' | 'done' | 'error'
  text: string
  [extra: string]: unknown
}

export type OnEvent = (event: Record<string, unknown>) => void | Promise<void>

/** One message sent into an agent and how it went; `process` while it runs. */
export class Run {
  started_at = Date.now() / 1000
  ended_at: number | null = null
  status: RunStatus = 'running'
  output = ''
  result_session_id = ''
  resumed = false
  error = ''
  tools = 0
  device = ''
  process: ChildProcess | undefined
  /** The message being streamed (Cursor sends deltas, then the whole message). */
  current = ''

  constructor(
    readonly id: string,
    readonly agent: AgentId,
    /** What was asked for ("" = new). */
    readonly session_id: string,
    public workspace: string,
    readonly text: string,
  ) {}

  commit(): void {
    if (this.current) {
      this.output = append(this.output, (this.output ? '\n' : '') + this.current)
      this.current = ''
    }
  }

  view(): RunView {
    const view: RunView = {
      id: this.id,
      agent: this.agent,
      session_id: this.result_session_id || this.session_id,
      asked_session_id: this.session_id,
      workspace: this.workspace,
      text: this.text,
      started_at: this.started_at,
      ended_at: this.ended_at,
      status: this.status,
      output: (this.output + (this.current ? `\n${this.current}` : '')).slice(-OUTPUT_LIMIT),
      resumed: this.resumed,
      error: this.error,
      tools: this.tools,
    }
    if (this.device) view.device = this.device
    return view
  }

  /** End the process and everything it forked; false when nothing was running. */
  stop(): boolean {
    const p = this.process
    if (!p || p.exitCode !== null || p.signalCode !== null || !p.pid) return false
    try {
      if (process.platform !== 'win32') process.kill(-p.pid, 'SIGTERM')
      else {
        // taskkill /T walks the tree by parentage, as the runtime's own kill_tree does: a
        // plain kill() ends the CLI alone, and the helpers it detached from its job (the
        // header's `cursor-agent` worker server) keep running with their parent gone
        const killed = spawnSync('taskkill', ['/PID', String(p.pid), '/T', '/F'], { windowsHide: true, timeout: 10_000 })
        if (killed.error || killed.status !== 0) {
          if (!p.kill()) return false
        }
      }
    } catch {
      return false
    }
    this.status = 'stopped'
    return true
  }
}

/** A `Run` from a saved view (the record of earlier runs). */
export function runFromView(row: Record<string, unknown>): Run | undefined {
  const id = String(row.id ?? '')
  const agent = String(row.agent ?? '')
  if (!id || !(agent in AGENTS)) return undefined
  const run = new Run(id, agent as AgentId, String(row.asked_session_id ?? ''), String(row.workspace ?? ''), String(row.text ?? ''))
  run.started_at = Number(row.started_at ?? 0) || 0
  run.ended_at = typeof row.ended_at === 'number' ? row.ended_at : null
  const status = String(row.status ?? 'done')
  run.status = status === 'running' || status === 'failed' || status === 'stopped' ? status : 'done'
  run.output = String(row.output ?? '')
  run.result_session_id = String(row.session_id ?? '')
  run.resumed = Boolean(row.resumed)
  run.error = String(row.error ?? '')
  run.tools = Number(row.tools ?? 0) || 0
  run.device = String(row.device ?? '')
  if (run.status === 'running') {
    // it was going when the app stopped; the process went with it
    run.status = 'stopped'
    run.ended_at = run.ended_at ?? run.started_at
    run.error = run.error || 'the desktop app restarted while this was running'
  }
  return run
}

// ------------------------------------------------------------------------- the environment

const SECRET_ENV = /(KEY|TOKEN|SECRET|PASSW|PASSPHRASE|CREDENTIAL|_AUTH|AUTH_|COOKIE|SESSION)/i
const SECRET_ENV_PREFIXES = ['NANOMUSE_', 'AWS_', 'AZURE_', 'GOOGLE_', 'GH_', 'GITHUB_', 'NPM_']
const ALWAYS_DROP = new Set(['SSH_AUTH_SOCK', 'GPG_AGENT_INFO'])
const AGENT_ENV_PREFIXES: Record<AgentId, string[]> = {
  cursor: ['CURSOR_'],
  codex: ['OPENAI_', 'CODEX_'],
  claude: ['ANTHROPIC_', 'CLAUDE_'],
  dsh: ['DSH_', 'DEEPSEEK_'],
}
const CLAUDE_CLOUD: Record<string, string[]> = {
  CLAUDE_CODE_USE_BEDROCK: ['AWS_'],
  CLAUDE_CODE_USE_VERTEX: ['GOOGLE_', 'CLOUD_ML_REGION', 'GCLOUD_'],
}

/**
 * The environment a coding CLI runs with: the parent's minus anything that looks like a
 * credential (the runtime's shell tool's rule), plus the variables the agent itself needs —
 * its own account or key variables by prefix, and for Claude Code the cloud credentials
 * when `CLAUDE_CODE_USE_BEDROCK` / `_VERTEX` says so.
 */
export function agentEnv(agent: AgentId, source: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {}
  const allowed = [...AGENT_ENV_PREFIXES[agent]]
  if (agent === 'claude') {
    for (const [sw, prefixes] of Object.entries(CLAUDE_CLOUD)) {
      if (['1', 'true', 'yes'].includes((source[sw] ?? '').trim().toLowerCase())) allowed.push(...prefixes)
    }
  }
  for (const [name, value] of Object.entries(source)) {
    if (value === undefined) continue
    const upper = name.toUpperCase()
    if (allowed.some((p) => upper.startsWith(p))) {
      env[name] = value
      continue
    }
    if (ALWAYS_DROP.has(name) || SECRET_ENV.test(upper) || SECRET_ENV_PREFIXES.some((p) => upper.startsWith(p))) continue
    env[name] = value
  }
  // dsh's store is wherever DSH_HOME points, and the desktop app sets it to its own home for
  // the harness this plugin runs in; a dsh started from here works in the store the readers
  // list (`~/.dsh`, where dsh web and DeepSeek's desktop app keep their chats), so a chat read
  // here is the one `--session-id` finds and a new one shows up in the list
  if (agent === 'dsh') env.DSH_HOME = join(home(source), '.dsh')
  env.NO_COLOR = '1'
  env.CI = '1'
  return env
}

// ------------------------------------------------------------------------- the command

/** The CLI invocation for `agent`; `cli` is its executable. */
export function commandFor(agent: AgentId, cli: string, sessionId: string, workspace: string, text: string, resume: boolean): string[] {
  if (agent === 'cursor') {
    const cmd = [cli, '-p', '--output-format', 'stream-json', '--stream-partial-output', '--force']
    if (resume && sessionId) cmd.push('--resume', sessionId)
    if (workspace) cmd.push('--workspace', workspace)
    cmd.push(text)
    return cmd
  }
  if (agent === 'codex') {
    const cmd = [cli, 'exec']
    if (resume && sessionId) cmd.push('resume', sessionId)
    // edits inside the workspace without asking; `exec` never prompts anyway
    cmd.push('--json', '--skip-git-repo-check', '-c', 'sandbox_mode="workspace-write"')
    if (workspace && !(resume && sessionId)) cmd.push('-C', workspace)
    cmd.push(text)
    return cmd
  }
  if (agent === 'dsh') {
    // the harness's own one-shot runner: `dsh headless "<task>" --json` prints one projected
    // JSON object a line; `--session-id` adopts an existing session (the runner's cwd is the
    // workspace, so the spawn's cwd is what makes a resumed session match its recorded one)
    // a `dsh` on PATH runs itself; the harness this plugin runs inside is a `bin.js`, started
    // through node (Electron, with ELECTRON_RUN_AS_NODE, which the environment already carries)
    const cmd = cli.endsWith('.js') ? [process.execPath, cli] : [cli]
    cmd.push('--profile', 'headless', '--json')
    if (resume && sessionId) cmd.push('--session-id', sessionId)
    cmd.push(text)
    return cmd
  }
  const cmd = [cli, '-p', '--output-format', 'stream-json', '--verbose', '--permission-mode', 'acceptEdits']
  if (resume && sessionId) cmd.push('--resume', sessionId)
  cmd.push(text)
  return cmd
}

// ------------------------------------------------------------------------- the stream

type Obj = Record<string, unknown>

function isObj(v: unknown): v is Obj {
  return Boolean(v) && typeof v === 'object' && !Array.isArray(v)
}

function append(current: string, more: string): string {
  const s = current + more
  return s.length <= OUTPUT_LIMIT ? s : s.slice(-OUTPUT_LIMIT)
}

function contentText(content: unknown): string {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content.map((c) => (isObj(c) && c.type === 'text' ? String(c.text ?? '') : '')).join('')
}

function briefTool(name: string, call: unknown): string {
  let detail = ''
  if (isObj(call)) {
    const inner = name in call ? call[name] : call
    if (isObj(inner)) {
      const args = isObj(inner.args) ? inner.args : inner
      for (const k of ['command', 'path', 'file_path', 'pattern', 'query', 'url']) {
        if (args[k]) {
          detail = String(args[k])
          break
        }
      }
    }
  }
  const label = name.replace('ToolCall', '').replace(/_/g, ' ').trim() || 'tool'
  return detail ? `${label}: ${detail.slice(0, 120)}` : label
}

function codexTool(item: Obj): string {
  const it = String(item.type ?? '')
  if (it === 'command_execution') return `shell: ${String(item.command ?? '').slice(0, 120)}`
  if (it === 'file_change') {
    const changes = Array.isArray(item.changes) ? item.changes : []
    const paths = changes
      .map((c) => (isObj(c) ? String(c.path ?? '') : ''))
      .join(', ')
      .slice(0, 120)
    return paths ? `edit: ${paths}` : 'edit'
  }
  if (it === 'mcp_tool_call') return `tool: ${String(item.server ?? '')}/${String(item.tool ?? '')}`
  if (it === 'web_search') return `search: ${String(item.query ?? '').slice(0, 120)}`
  return it
}

const CODEX_TOOL_ITEMS = ['command_execution', 'file_change', 'mcp_tool_call', 'web_search']

/** One line of the agent's stream → zero or more events for the apps; updates `run` on the way. */
export function normalise(agent: AgentId, obj: Obj, run: Run): RunEvent[] {
  const t = String(obj.type ?? '')
  const out: RunEvent[] = []
  if (agent === 'cursor') {
    if (t === 'system' && obj.subtype === 'init') {
      const sid = String(obj.session_id ?? obj.chat_id ?? '')
      if (sid) run.result_session_id = sid
      out.push({ kind: 'started', text: '', session_id: sid, model: obj.model ?? '' })
    } else if (t === 'assistant') {
      const msg = isObj(obj.message) ? obj.message : {}
      const text = contentText(msg.content)
      if (text) {
        // with --stream-partial-output the deltas carry `timestamp_ms`; the whole message
        // comes once more without it and replaces what the deltas built
        if (obj.timestamp_ms !== undefined && obj.timestamp_ms !== null) {
          run.current = append(run.current, text)
          out.push({ kind: 'text', text, partial: true })
        } else {
          run.current = text
          run.commit()
          out.push({ kind: 'text', text, partial: false })
        }
      }
    } else if (t === 'tool_call') {
      const sub = String(obj.subtype ?? '')
      const call = isObj(obj.tool_call) ? obj.tool_call : {}
      const name = Object.keys(call)[0] ?? ''
      if (sub === 'started') run.tools += 1
      out.push({ kind: 'tool', text: briefTool(name, call), phase: sub })
    } else if (t === 'result') {
      run.commit()
      const sid = String(obj.session_id ?? run.result_session_id)
      run.result_session_id = sid || run.result_session_id
      const final = String(obj.result ?? '')
      if (final && !run.output.includes(final)) run.output = append(run.output, (run.output ? '\n' : '') + final)
      const ok = (obj.subtype === undefined || obj.subtype === null || obj.subtype === 'success') && !obj.is_error
      out.push({ kind: ok ? 'done' : 'error', text: final, session_id: sid, duration_ms: obj.duration_ms ?? null })
    }
  } else if (agent === 'codex') {
    if (t === 'thread.started') {
      const sid = String(obj.thread_id ?? '')
      if (sid) run.result_session_id = sid
      out.push({ kind: 'started', text: '', session_id: sid })
    } else if (t === 'item.completed') {
      const item = isObj(obj.item) ? obj.item : {}
      const it = String(item.type ?? '')
      if (it === 'agent_message') {
        const text = String(item.text ?? '')
        if (text) {
          run.output = append(run.output, (run.output ? '\n' : '') + text)
          out.push({ kind: 'text', text })
        }
      } else if (CODEX_TOOL_ITEMS.includes(it) || it === 'patch') {
        run.tools += 1
        out.push({ kind: 'tool', text: codexTool(item), phase: 'completed' })
      }
    } else if (t === 'item.started') {
      const item = isObj(obj.item) ? obj.item : {}
      if (CODEX_TOOL_ITEMS.includes(String(item.type ?? ''))) out.push({ kind: 'tool', text: codexTool(item), phase: 'started' })
    } else if (t === 'turn.completed') {
      out.push({ kind: 'done', text: run.output, session_id: run.result_session_id, usage: obj.usage ?? null })
    } else if (t === 'turn.failed' || t === 'error') {
      let msg: unknown = obj.error ?? obj.message ?? ''
      if (isObj(msg)) msg = msg.message ?? ''
      out.push({ kind: 'error', text: String(msg) })
    }
  } else if (agent === 'dsh') {
    // `dsh headless --json`: `session` opens, `status` marks the turns and steps, `text` and
    // `thinking` come from committed messages, `tool_call`/`tool_result` are the tools, and
    // the terminal `final` carries the answer (the last line, never bounded).
    if (t === 'session') {
      const sid = String(obj.sessionId ?? '')
      if (sid) run.result_session_id = sid
      out.push({ kind: 'started', text: '', session_id: sid, cwd: obj.cwd ?? '' })
    } else if (t === 'text') {
      const text = String(obj.text ?? '')
      if (text) {
        run.output = append(run.output, (run.output ? '\n' : '') + text)
        out.push({ kind: 'text', text })
      }
    } else if (t === 'tool_call') {
      run.tools += 1
      out.push({ kind: 'tool', text: briefTool(String(obj.tool ?? ''), obj.input ?? {}), phase: 'started' })
    } else if (t === 'tool_result') {
      out.push({ kind: 'tool', text: String(obj.status ?? 'completed'), phase: 'completed' })
    } else if (t === 'final') {
      run.commit()
      const final = String(obj.text ?? '')
      if (final && !run.output.includes(final)) run.output = append(run.output, (run.output ? '\n' : '') + final)
      out.push({ kind: 'done', text: final || run.output, session_id: run.result_session_id })
    } else if (t === 'status' && isObj(obj.reason)) {
      const reason = obj.reason
      if (String(reason.kind ?? '') === 'error') {
        const err = isObj(reason.error) ? reason.error : {}
        out.push({ kind: 'error', text: String(err.message ?? '') })
      }
    }
  } else {
    if (t === 'system' && obj.subtype === 'init') {
      const sid = String(obj.session_id ?? '')
      if (sid) run.result_session_id = sid
      out.push({ kind: 'started', text: '', session_id: sid, model: obj.model ?? '' })
    } else if (t === 'assistant') {
      const msg = isObj(obj.message) ? obj.message : {}
      if (Array.isArray(msg.content)) {
        for (const c of msg.content) {
          if (!isObj(c)) continue
          if (c.type === 'text' && c.text) {
            run.output = append(run.output, (run.output ? '\n' : '') + String(c.text))
            out.push({ kind: 'text', text: String(c.text) })
          } else if (c.type === 'tool_use') {
            run.tools += 1
            out.push({ kind: 'tool', text: briefTool(String(c.name ?? ''), c.input ?? {}), phase: 'started' })
          }
        }
      }
    } else if (t === 'result') {
      const sid = String(obj.session_id ?? run.result_session_id)
      run.result_session_id = sid || run.result_session_id
      const final = String(obj.result ?? '')
      if (final && !run.output.includes(final)) run.output = append(run.output, (run.output ? '\n' : '') + final)
      out.push({ kind: obj.is_error ? 'error' : 'done', text: final, session_id: sid, duration_ms: obj.duration_ms ?? null })
    }
  }
  return out
}

// ------------------------------------------------------------------------- the run

/** Lines from a stream, taken one at a time with an optional patience. */
class LineQueue {
  private readonly lines: (string | null)[] = []
  private waiter: ((line: string | null) => void) | undefined
  private rest = ''

  push(chunk: Buffer | string): void {
    this.rest += chunk.toString()
    let at: number
    while ((at = this.rest.indexOf('\n')) >= 0) {
      this.deliver(this.rest.slice(0, at))
      this.rest = this.rest.slice(at + 1)
    }
  }

  end(): void {
    if (this.rest) this.deliver(this.rest)
    this.rest = ''
    this.deliver(null)
  }

  private deliver(line: string | null): void {
    if (this.waiter) {
      const w = this.waiter
      this.waiter = undefined
      w(line)
    } else this.lines.push(line)
  }

  /** The next line; `null` at the end; `undefined` when `patienceMs` passed without one. */
  next(patienceMs?: number): Promise<string | null | undefined> {
    if (this.lines.length) return Promise.resolve(this.lines.shift())
    return new Promise((resolve) => {
      let timer: ReturnType<typeof setTimeout> | undefined
      this.waiter = (line) => {
        if (timer) clearTimeout(timer)
        resolve(line)
      }
      if (patienceMs !== undefined) {
        timer = setTimeout(() => {
          this.waiter = undefined
          resolve(undefined)
        }, patienceMs)
      }
    })
  }
}

export interface StartOptions {
  agent: AgentId
  text: string
  sessionId?: string
  workspace?: string
  onEvent?: OnEvent
  timeoutMs?: number
  runId?: string
  /** Sees the `Run` as soon as it exists, before the process starts. */
  register?: (run: Run) => void
  /** Where the CLI is; defaults to PATH. Tests point it at a fake. */
  which?: (agent: AgentId) => string | undefined
  env?: NodeJS.ProcessEnv
  /** The transcripts' home (tests); defaults to the process environment's. */
  readerEnv?: NodeJS.ProcessEnv
}

const UNKNOWN_SESSION_WORDS = ['not found', 'no such', 'unknown chat', 'could not find', 'does not exist', 'no conversation', 'invalid chat', 'no session', 'failed to resume', 'resume']

function looksLikeUnknownSession(text: string): boolean {
  return UNKNOWN_SESSION_WORDS.some((k) => text.includes(k))
}

/** The message for a fresh chat that carries on an old one: its title, the last exchange. */
export function continuation(prior: CodingSession, text: string): string {
  const last = (prior.transcript ?? []).slice(-2)
  const context = last.map((m) => `${m.role}: ${m.text.slice(0, 800)}`).join('\n')
  return `Continuing an earlier chat titled '${prior.title}'.\n\nLast exchange:\n${context}\n\nNow: ${text}`
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

function exited(p: ChildProcess): boolean {
  return p.exitCode !== null || p.signalCode !== null
}

/**
 * Wait for the CLI to exit without depending on its pipes reaching EOF (a background helper it
 * leaves behind may hold them); kill it if it is still around after `graceMs`.
 */
async function waitExit(p: ChildProcess, graceMs: number): Promise<void> {
  let deadline = Date.now() + graceMs
  while (!exited(p) && Date.now() < deadline) await sleep(100)
  if (!exited(p)) {
    try {
      if (process.platform !== 'win32' && p.pid) process.kill(-p.pid, 'SIGKILL')
      else p.kill('SIGKILL')
    } catch {
      // already gone
    }
    deadline = Date.now() + 5000
    while (!exited(p) && Date.now() < deadline) await sleep(100)
  }
  // release our ends of the pipes now; an inheritor would otherwise keep them
  p.stdout?.destroy()
  p.stderr?.destroy()
}

/**
 * Send `text` into `sessionId` of `agent` (a new session when empty) and follow it to the
 * end. Resolves with the finished `Run`; `onEvent` sees each step as it happens, as
 * `{run, kind, text, …}`.
 *
 * A Cursor IDE chat cannot be continued by the CLI: for one (`resumable` false) the message
 * goes straight out as a new CLI chat in the same workspace with the last exchange quoted,
 * and the run says `resumed: false`; the same happens when a chat the store said was
 * resumable turns out unknown to the CLI.
 */
export async function startRun(options: StartOptions): Promise<Run> {
  const { agent } = options
  const text = options.text.trim()
  if (!(agent in AGENTS)) throw new Error(`unknown agent '${String(agent)}'`)
  if (!text) throw new Error('text is required')
  const sessionId = options.sessionId ?? ''
  const run = new Run(options.runId || `run_${Math.random().toString(16).slice(2, 10).padEnd(8, '0')}`, agent, sessionId, options.workspace ?? '', text)
  options.register?.(run)
  const find = options.which ?? ((a: AgentId) => cliFor(a, options.env ?? process.env))
  const prior = sessionId ? await readSession(agent, sessionId, options.readerEnv ?? process.env) : undefined
  if (prior && !run.workspace) run.workspace = prior.workspace
  if (run.workspace) {
    const ok = await stat(run.workspace).then((s) => s.isDirectory()).catch(() => false)
    if (!ok) run.workspace = ''
  }
  const emit = async (ev: RunEvent) => {
    if (!options.onEvent) return
    try {
      await options.onEvent({ run: run.id, ...ev })
    } catch {
      // a listener's problem is not the run's
    }
  }
  const finish = (status: RunStatus, error = '') => {
    run.status = status
    run.error = error
    run.ended_at = Date.now() / 1000
  }

  let resume = Boolean(sessionId)
  let attemptText = text
  if (prior && !prior.resumable) {
    resume = false
    attemptText = continuation(prior, text)
    await emit({ kind: 'tool', text: 'that chat was made in the IDE and cannot be reopened from the command line; starting a new one in the same workspace', phase: 'note' })
  }
  const timeoutMs = options.timeoutMs ?? RUN_TIMEOUT_MS

  for (const attempt of [1, 2]) {
    const cli = find(agent)
    if (!cli) {
      finish('failed', `${AGENTS[agent].name} is not installed on this computer`)
      await emit({ kind: 'error', text: run.error })
      return run
    }
    const [file, ...args] = commandFor(agent, cli, sessionId, run.workspace, attemptText, resume)
    let proc: ChildProcess
    try {
      proc = spawn(file as string, args, {
        cwd: run.workspace || undefined,
        stdio: ['ignore', 'pipe', 'pipe'],
        detached: process.platform !== 'win32',
        env: agentEnv(agent, options.env ?? process.env),
        windowsHide: true,
      })
    } catch (error: unknown) {
      finish('failed', error instanceof Error ? error.message : String(error))
      await emit({ kind: 'error', text: run.error })
      return run
    }
    run.process = proc
    run.resumed = resume
    let sawDone = false
    let stderrTail = ''
    let lastError = ''
    const lines = new LineQueue()
    const spawnFailed = new Promise<Error>((resolve) => proc.on('error', resolve))
    proc.stdout?.on('data', (chunk: Buffer) => lines.push(chunk))
    proc.stdout?.on('end', () => lines.end())
    proc.stdout?.on('close', () => lines.end())
    proc.stderr?.on('data', (chunk: Buffer) => {
      const t = chunk.toString().trim()
      if (t) stderrTail = `${stderrTail}\n${t}`.slice(-2000)
    })
    const deadline = Date.now() + timeoutMs
    let timedOut = false
    let failedToStart: Error | undefined
    void spawnFailed.then((e) => {
      failedToStart = e
      lines.end()
    })

    while (true) {
      const left = deadline - Date.now()
      if (left <= 0) {
        timedOut = true
        break
      }
      // After the agent's final message we stop waiting for EOF: a helper the CLI leaves
      // running in the background may keep our pipe open forever.
      const patience = sawDone ? (exited(proc) ? 500 : 5000) : left
      const raw = await lines.next(patience)
      if (raw === undefined) {
        if (sawDone) break
        timedOut = true
        break
      }
      if (raw === null) break
      const line = raw.trim()
      if (!line.startsWith('{')) continue
      let obj: unknown
      try {
        obj = JSON.parse(line)
      } catch {
        continue
      }
      if (!isObj(obj)) continue
      for (const ev of normalise(agent, obj, run)) {
        if (ev.kind === 'done') sawDone = true
        else if (ev.kind === 'error' && ev.text) lastError = ev.text
        await emit(ev)
      }
    }
    if (timedOut) {
      run.stop()
      finish('failed', 'the agent took too long')
      await emit({ kind: 'error', text: run.error })
      return run
    }
    if (failedToStart) {
      finish('failed', failedToStart.message)
      await emit({ kind: 'error', text: run.error })
      return run
    }
    await waitExit(proc, sawDone ? 15_000 : 60_000)
    if (run.status === 'stopped') {
      run.ended_at = Date.now() / 1000
      await emit({ kind: 'error', text: 'stopped', stopped: true })
      return run
    }
    const rc = proc.exitCode ?? 0
    if (rc === 0 && (sawDone || run.output)) {
      finish('done')
      if (!sawDone) await emit({ kind: 'done', text: run.output, session_id: run.result_session_id })
      return run
    }
    // A failed resume of a chat the CLI does not know: try once more as a new chat.
    const lower = `${stderrTail} ${run.output}`.toLowerCase()
    if (attempt === 1 && resume && looksLikeUnknownSession(lower)) {
      attemptText = prior ? continuation(prior, text) : text
      resume = false
      run.output = ''
      await emit({ kind: 'tool', text: 'that chat cannot be resumed from the command line; starting a new one in the same workspace', phase: 'note' })
      continue
    }
    const tail = stderrTail.trim().split('\n').filter(Boolean)
    finish('failed', (lastError || tail[tail.length - 1] || `exit ${rc}`).slice(0, 300))
    await emit({ kind: 'error', text: run.error, final: true })
    return run
  }
  return run
}
