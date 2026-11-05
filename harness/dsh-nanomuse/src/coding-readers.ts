/**
 * What the coding agents leave on disk, read without asking them — a port of the
 * runtime's `nanomuse/coding/agents.py`, shapes and field names alike, so a phone
 * or the web app cannot tell the desktop from the Python runtime
 * (`docs/coding-agents.md`, "What is read").
 *
 * Cursor      `~/.cursor/projects/<slug>/agent-transcripts/<id>/<id>.jsonl`, one JSON
 *             object a line (`{role, message: {content: [{type: "text", …}]}}`,
 *             `{type: "turn_ended"}`); `<slug>` is the workspace path with `/` turned
 *             into `-`. CLI chats also have `~/.cursor/chats/<hash>/<id>/meta.json`.
 * Codex       `~/.codex/sessions/YYYY/MM/DD/rollout-<time>-<id>.jsonl`: a `session_meta`
 *             line, `response_item` messages, `event_msg` lines.
 * Claude Code `~/.claude/projects/<slug>/<id>.jsonl`: `{type: "user"|"assistant",
 *             message: {role, content}, timestamp, cwd, sessionId}`.
 * dsh         `~/.dsh/sessions/<slug>/<id>/session.v4.jsonl.zstd`: the harness's own
 *             store, one zstd-compressed JSON object a line. A `session` header
 *             (`{id, createdAt, cwd}`), `user/message` and `assistant/message` events
 *             (`{data: {content: […]}}` and `{data: {message: {content: […]}}}`), tools
 *             as `tool/call` + `tool/result`, and `<id>` is the session id itself.
 *
 * Everything is read-only and best effort: a line that does not parse is skipped, a
 * missing directory is an agent with no sessions. `~` is the user's home unless
 * `NANOMUSE_CODING_HOME` names another directory.
 */
import { execFile } from 'node:child_process'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { open, readdir, readFile, stat } from 'node:fs/promises'
import { homedir } from 'node:os'
import { basename, delimiter, dirname, join, resolve } from 'node:path'
import { zstdDecompressSync } from 'node:zlib'

export type AgentId = 'cursor' | 'codex' | 'claude' | 'dsh'

export interface AgentSpec {
  name: string
  /** Executables tried in order. */
  bins: readonly string[]
  /** Process names that count as the agent running. */
  process: readonly string[]
}

/** The agents nanoMuse knows how to read and drive. */
export const AGENTS: Record<AgentId, AgentSpec> = {
  cursor: { name: 'Cursor', bins: ['cursor-agent', 'agent'], process: ['cursor-agent', 'cursor'] },
  codex: { name: 'Codex', bins: ['codex'], process: ['codex'] },
  claude: { name: 'Claude Code', bins: ['claude'], process: ['claude'] },
  dsh: { name: 'DeepSeek Harness', bins: ['dsh'], process: ['dsh'] },
}

export const AGENT_IDS = Object.keys(AGENTS) as AgentId[]

export function isAgentId(value: unknown): value is AgentId {
  return typeof value === 'string' && value in AGENTS
}

/** `{id, name, installed, cli, version, sessions_root, running}` — the runtime's `AgentInfo.to_dict()`. */
export interface AgentInfo {
  id: AgentId
  name: string
  installed: boolean
  cli: string | null
  version: string
  sessions_root: string
  /** Processes alive right now. */
  running: number
}

export interface CodingMessage {
  role: string
  text: string
}

/** `Session.to_dict()`: a chat of an agent, as read from its store on disk. */
export interface CodingSession {
  agent: AgentId
  id: string
  title: string
  workspace: string
  path: string
  /** Unix seconds. */
  created_at: number
  updated_at: number
  messages: number
  status: 'idle' | 'active' | 'running'
  last_user: string
  last_assistant: string
  /** cursor: `ide` | `cli`; codex: the originator; claude: empty. */
  source: string
  resumable: boolean
  transcript?: CodingMessage[]
}

/** A session whose transcript changed this recently is "active"; newer than RUNNING_S × 4 with an open turn is "running". */
const ACTIVE_S = 180
const RUNNING_S = 45
const LINE_LIMIT_BYTES = 64 * 1024 * 1024
const TRANSCRIPT_KEEP = 400

const TAG_RE = /<(timestamp|system_reminder|system-reminder|attached_files|user_info|git_status|environment_context|app-context|multi_agent_role|permissions[^>]*)>[\s\S]*?<\/\1>/g
const USER_QUERY_RE = /<user_query>([\s\S]*?)<\/user_query>/
const EMPTY_TAG_RE = /<[a-z_-]+>\s*<\/[a-z_-]+>/g

// ------------------------------------------------------------------------- detection

/** `NANOMUSE_CODING_HOME`, or the user's home. */
export function home(env: NodeJS.ProcessEnv = process.env): string {
  return env.NANOMUSE_CODING_HOME || homedir()
}

export function sessionsRoot(agent: AgentId, env: NodeJS.ProcessEnv = process.env): string {
  const h = home(env)
  switch (agent) {
    case 'cursor':
      return join(h, '.cursor', 'projects')
    case 'codex':
      return join(h, '.codex', 'sessions')
    case 'claude':
      return join(h, '.claude', 'projects')
    case 'dsh':
      return join(h, '.dsh', 'sessions')
  }
}

/**
 * The harness's own entry script, when this plugin is running inside one: the desktop app
 * starts `node …/dsh/lib/bin.js <profile>`, and that copy is not on PATH, so a dsh session
 * could otherwise be read but never sent to. `process.argv` carries it.
 */
export function ownDshEntry(argv: readonly string[] = process.argv): string | undefined {
  for (const arg of argv.slice(1)) {
    if (!/[\\/]dsh[\\/]lib[\\/]bin\.js$/.test(arg)) continue
    try {
      if (statSync(arg).isFile()) return arg
    } catch {
      continue
    }
  }
  return undefined
}

/** The first of the agent's executables on PATH (PATHEXT on Windows), or undefined. */
export function which(agent: AgentId, env: NodeJS.ProcessEnv = process.env, platform: NodeJS.Platform = process.platform): string | undefined {
  const dirs = (env.PATH ?? env.Path ?? '').split(delimiter).filter(Boolean)
  const exts = platform === 'win32' ? (env.PATHEXT ?? '.EXE;.CMD;.BAT;.COM').split(';').filter(Boolean) : ['']
  for (const bin of AGENTS[agent].bins) {
    for (const dir of dirs) {
      for (const ext of [''].concat(platform === 'win32' ? exts : [])) {
        const candidate = join(dir, bin + ext)
        try {
          if (statSync(candidate).isFile()) return candidate
        } catch {
          continue
        }
      }
    }
  }
  return undefined
}

/**
 * The CLI a run starts: the one on PATH, or for dsh, whose CLI ships inside an app rather
 * than onto PATH, the harness this plugin is running in (`commandFor` starts it through
 * node). Only for sending: whether an agent is installed is still PATH or its store.
 */
export function cliFor(agent: AgentId, env: NodeJS.ProcessEnv = process.env, argv: readonly string[] = process.argv): string | undefined {
  return which(agent, env) ?? (agent === 'dsh' ? ownDshEntry(argv) : undefined)
}

/**
 * A `.cmd` or `.bat` cannot be started by node's bare `spawn`/`execFile` on Windows: since
 * the batch-file injection fixes (node 18.20, 20.12 and 21.7) it throws `EINVAL` before any
 * process exists, and npm's bins are exactly that shape. Routing through `cmd /c` starts it
 * but is no way to carry an argument: cmd re-reads everything after `/c` as shell syntax, so
 * a quote, a percent sign, a metacharacter or a newline in the argument is parsed as cmd's
 * own grammar (an `&` in a prompt can start another command, `%PATH%` expands on the way),
 * and the argument that arrives is not the one that was written. The shim is therefore read
 * for the node script it launches, npm's `"<node>" "<…>.js" %*` line, and that script is
 * started directly: node passes arguments verbatim, so every character survives and nothing
 * in the text can run. A batch file whose launcher cannot be read is refused outright with
 * an error naming it, because starting it through cmd would quietly return to the
 * interpretation bug. Anything that is not a batch file is passed through untouched.
 */
export function cliSpawnCommand(platform: NodeJS.Platform, file: string, args: readonly string[]): [string, string[]] {
  if (platform !== 'win32' || !/\.(cmd|bat)$/i.test(file)) return [file, [...args]]
  const target = batchShimTarget(file)
  if (!target) {
    throw new Error(`"${file}" is a batch file whose node launcher cannot be read; refusing to start it, because cmd would reinterpret its arguments`)
  }
  return [process.execPath, [target, ...args]]
}

/**
 * The node script a batch-file shim launches, when it names one that exists. Comment lines
 * (REM, ::) are skipped - a quoted path there is documentation, not the entry point - and
 * the last candidate wins: npm's shim ends with its invocation.
 */
function batchShimTarget(file: string): string | undefined {
  try {
    const text = readFileSync(file, 'utf8')
    let target: string | undefined
    for (const line of text.split(/\r?\n/)) {
      const trimmed = line.trim().replace(/^@/, '')
      if (/^(rem(\s|$)|::)/i.test(trimmed)) continue
      for (const match of line.matchAll(/"(%~?dp0%?\\)?([^"\r\n]*\.(?:mjs|cjs|js))"/gi)) {
        const rest = match[2]
        if (!rest) continue
        const candidate = match[1] ? join(dirname(file), rest) : resolve(rest)
        if (existsSync(candidate)) target = candidate
      }
    }
    return target
  } catch {
    return undefined
  }
}

/** The first line of `<cli> --version`, at most 60 characters; empty when it cannot be run. */
export function versionOf(cli: string, timeoutMs = 8000): Promise<string> {
  return new Promise((done) => {
    try {
      const [file, args] = cliSpawnCommand(process.platform, cli, ['--version'])
      execFile(file, args, { timeout: timeoutMs, windowsHide: true, maxBuffer: 64 * 1024 }, (error, stdout, stderr) => {
        const text = String(stdout || stderr || '').trim().split(/\r?\n/)[0] ?? ''
        done(error && !text ? '' : text.slice(0, 60))
      })
    } catch {
      done('')
    }
  })
}

// ------------------------------------------------------------------------- processes

/** (executable name, first arguments) of one process, as the platform reports it. */
export type ProcessRow = [comm: string, argv: string]

/** How many processes of each agent the rows hold; the node-bundled Cursor CLI counts through its argv. */
export function countProcesses(rows: readonly ProcessRow[]): Record<AgentId, number> {
  const counts: Record<AgentId, number> = { cursor: 0, codex: 0, claude: 0, dsh: 0 }
  for (const [comm, argv] of rows) {
    let base = basename(comm.trim()).toLowerCase()
    if (base.endsWith('.exe')) base = base.slice(0, -4)
    let matched = false
    for (const id of AGENT_IDS) {
      if (AGENTS[id].process.includes(base)) {
        counts[id] += 1
        matched = true
        break
      }
    }
    if (!matched && base === 'node' && argv.includes('cursor-agent')) counts.cursor += 1
  }
  return counts
}

/** `ps -axo comm=,args=` → rows (the command's first three words). */
export function parsePs(stdout: string): ProcessRow[] {
  const rows: ProcessRow[] = []
  for (const raw of stdout.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const space = line.search(/\s/)
    if (space < 0) {
      rows.push([line, ''])
      continue
    }
    const rest = line.slice(space).trim().split(/\s+/).slice(0, 3).join(' ')
    rows.push([line.slice(0, space), rest])
  }
  return rows
}

/** `tasklist /FO CSV /NH` → rows; `nodeLines` are the node.exe command lines, in the same order. */
export function parseTasklist(stdout: string, nodeLines: readonly string[] = []): ProcessRow[] {
  const rows: ProcessRow[] = []
  const nodes = [...nodeLines]
  for (const raw of stdout.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const name = (line.split('","', 1)[0] ?? '').replace(/^"+|"+$/g, '').trim()
    if (!name) continue
    let argv = ''
    if (name.toLowerCase() === 'node.exe') argv = nodes.shift() ?? ''
    rows.push([name, argv])
  }
  return rows
}

async function linuxRows(): Promise<ProcessRow[]> {
  const out: ProcessRow[] = []
  let names: string[]
  try {
    names = await readdir('/proc')
  } catch {
    return out
  }
  for (const name of names) {
    if (!/^\d+$/.test(name)) continue
    try {
      const comm = (await readFile(join('/proc', name, 'comm'), 'utf8')).trim()
      const cmdline = await readFile(join('/proc', name, 'cmdline'))
      const argv = cmdline.toString('utf8').split('\0').slice(0, 3).join(' ')
      out.push([comm, argv])
    } catch {
      continue
    }
  }
  return out
}

function runText(file: string, args: string[], timeoutMs: number): Promise<string> {
  return new Promise((done) => {
    try {
      execFile(file, args, { timeout: timeoutMs, windowsHide: true, maxBuffer: 16 * 1024 * 1024 }, (_error, stdout) => done(String(stdout ?? '')))
    } catch {
      done('')
    }
  })
}

/** The command lines of the node.exe processes (tasklist has none); one PowerShell call. */
async function windowsNodeCommandLines(): Promise<string[]> {
  const out = await runText('powershell', ['-NoProfile', '-Command', "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | ForEach-Object { $_.CommandLine }"], 15_000)
  return out.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
}

/** Every process, the platform's way: `/proc` on Linux, `ps` on macOS, `tasklist` on Windows. Never `pgrep -f`. */
export async function processRows(platform: NodeJS.Platform = process.platform): Promise<ProcessRow[]> {
  if (platform === 'linux') return linuxRows()
  if (platform === 'darwin') return parsePs(await runText('ps', ['-axo', 'comm=,args='], 8000))
  if (platform === 'win32') {
    const table = await runText('tasklist', ['/FO', 'CSV', '/NH'], 8000)
    const nodes = /node\.exe/i.test(table) ? await windowsNodeCommandLines() : []
    return parseTasklist(table, nodes)
  }
  return []
}

let processCache: { at: number; counts: Record<AgentId, number> } = { at: 0, counts: { cursor: 0, codex: 0, claude: 0, dsh: 0 } }

/** The process table, read once for all agents and kept two seconds (the apps ask about the three together). */
export async function runningProcesses(platform: NodeJS.Platform = process.platform): Promise<Record<AgentId, number>> {
  if (Date.now() - processCache.at < 2000) return processCache.counts
  const counts = countProcesses(await processRows(platform))
  processCache = { at: Date.now(), counts }
  return counts
}

async function isDir(path: string): Promise<boolean> {
  try {
    return (await stat(path)).isDirectory()
  } catch {
    return false
  }
}

/** The three agents: installed when the CLI is on PATH or the store on disk exists; `running` is live. */
export async function detect(withVersions = false, env: NodeJS.ProcessEnv = process.env): Promise<AgentInfo[]> {
  const out: AgentInfo[] = []
  let running: Record<AgentId, number> | undefined
  for (const id of AGENT_IDS) {
    const cli = which(id, env)
    const root = sessionsRoot(id, env)
    const hasData = await isDir(root)
    if ((cli || hasData) && !running) running = await runningProcesses()
    out.push({
      id,
      name: AGENTS[id].name,
      installed: Boolean(cli) || hasData,
      cli: cli ?? null,
      version: cli && withVersions ? await versionOf(cli) : '',
      sessions_root: hasData ? root : '',
      running: cli || hasData ? (running?.[id] ?? 0) : 0,
    })
  }
  return out
}

// ------------------------------------------------------------------------- transcripts

/** A user message as the person typed it: the IDE's wrapper tags stripped. */
export function clean(text: string): string {
  if (!text) return ''
  const m = USER_QUERY_RE.exec(text)
  if (m) text = m[1] ?? ''
  text = text.replace(TAG_RE, '')
  text = text.replace(EMPTY_TAG_RE, '')
  return text.trim()
}

export function title(text: string, limit = 80): string {
  const line = text.split(/\s+/).filter(Boolean).join(' ')
  return line.length <= limit ? line : `${line.slice(0, limit - 1)}…`
}

function isDirectory(path: string): boolean {
  try {
    return existsSync(path) && statSync(path).isDirectory()
  } catch {
    return false
  }
}

/**
 * `ssd-code-appagent-openmuse` → `/ssd/code/appagent/openmuse` when such a directory exists;
 * hyphenated names are tried as one component when the split does not exist. Falls back to
 * the slug itself.
 *
 * On Windows the slug starts with the drive: Cursor drops the colon (`C:\Users\me\app` →
 * `C-Users-me-app`), Claude Code turns it into a dash too (`C--Users-me-app`), and either
 * may lower-case the letter. Both read back as `C:\Users\me\app`.
 */
export function slugToPath(slug: string, platform: NodeJS.Platform = process.platform, isDir: (path: string) => boolean = isDirectory): string {
  const parts = slug.split('-')
  const sep = platform === 'win32' ? '\\' : '/'
  let path = ''
  let i = 0
  if (platform === 'win32' && /^[A-Za-z]$/.test(parts[0] ?? '') && parts.length > 1) {
    path = `${parts[0]!.toUpperCase()}:`
    i = parts[1] === '' ? 2 : 1
  }
  const start = i
  while (i < parts.length) {
    let chosen: [string, number] | undefined
    for (let j = parts.length; j > i; j--) {
      const candidate = `${path}${sep}${parts.slice(i, j).join('-')}`
      if (isDir(candidate)) {
        chosen = [candidate, j]
        break
      }
    }
    if (!chosen) return i > start ? `${path}${sep}${parts.slice(i).join('-')}` : slug
    ;[path, i] = chosen
  }
  return i > start ? path : slug
}

function status(updatedAt: number, openTurn: boolean, now = Date.now() / 1000): CodingSession['status'] {
  const age = now - updatedAt
  if (openTurn && age < RUNNING_S * 4) return 'running'
  if (age < ACTIVE_S) return 'active'
  return 'idle'
}

type Obj = Record<string, unknown>

function isObj(v: unknown): v is Obj {
  return Boolean(v) && typeof v === 'object' && !Array.isArray(v)
}

/** The JSON objects of a JSONL file; a line that does not parse is skipped, a huge file is empty. */
export async function readLines(path: string, limitBytes = LINE_LIMIT_BYTES): Promise<Obj[]> {
  const out: Obj[] = []
  let text: string
  try {
    const info = await stat(path)
    if (info.size > limitBytes) return out
    const fh = await open(path, 'r')
    try {
      text = (await fh.readFile()).toString('utf8')
    } finally {
      await fh.close()
    }
  } catch {
    return out
  }
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    try {
      const obj: unknown = JSON.parse(line)
      if (isObj(obj)) out.push(obj)
    } catch {
      continue
    }
  }
  return out
}

/** The words of a message's content: strings, text parts, `[tool: name]` for tool uses. */
export function textOf(content: unknown): string {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  const parts: string[] = []
  for (const c of content) {
    if (!isObj(c)) continue
    if ((c.type === 'text' || c.type === 'input_text' || c.type === 'output_text') && c.text) parts.push(String(c.text))
    else if (c.type === 'tool_use') parts.push(`[tool: ${String(c.name ?? '')}]`)
  }
  return parts.join('\n')
}

function isoToTs(s: unknown): number {
  if (typeof s !== 'string') return 0
  const ms = Date.parse(s)
  return Number.isFinite(ms) ? ms / 1000 : 0
}

interface FileStat {
  mtime: number
  ctime: number
}

async function statOf(path: string): Promise<FileStat | undefined> {
  try {
    const st = await stat(path)
    return { mtime: st.mtimeMs / 1000, ctime: st.ctimeMs / 1000 }
  } catch {
    return undefined
  }
}

// -- Cursor --------------------------------------------------------------------------------

type CursorMeta = Record<string, Obj>

/** CLI chats by id: their cwd and times (`~/.cursor/chats/<hash>/<id>/meta.json`). */
async function cursorCliMeta(env: NodeJS.ProcessEnv): Promise<CursorMeta> {
  const root = join(home(env), '.cursor', 'chats')
  const out: CursorMeta = {}
  if (!(await isDir(root))) return out
  for (const h of await readdir(root).catch(() => [] as string[])) {
    const hdir = join(root, h)
    if (!(await isDir(hdir))) continue
    for (const c of await readdir(hdir).catch(() => [] as string[])) {
      try {
        const meta: unknown = JSON.parse(await readFile(join(hdir, c, 'meta.json'), 'utf8'))
        if (isObj(meta)) out[c] = meta
      } catch {
        continue
      }
    }
  }
  return out
}

async function cursorSession(file: string, ws: string, cliMeta: CursorMeta, full: boolean): Promise<CodingSession | undefined> {
  const lines = await readLines(file)
  const sid = basename(file, '.jsonl')
  const st = await statOf(file)
  if (!st) return undefined
  const transcript: CodingMessage[] = []
  let firstUser = ''
  let lastUser = ''
  let lastAssistant = ''
  let openTurn = false
  let n = 0
  for (const obj of lines) {
    const role = obj.role
    if (role === 'user' || role === 'assistant') {
      const msg = obj.message
      let text = isObj(msg) ? textOf(msg.content) : ''
      if (role === 'user') {
        text = clean(text)
        if (!text) continue
        firstUser = firstUser || text
        lastUser = text
        openTurn = true
      } else {
        text = text.trim()
        if (!text) continue
        lastAssistant = text
      }
      n += 1
      if (full) transcript.push({ role, text })
    } else if (obj.type === 'turn_ended') {
      openTurn = false
    }
  }
  const meta = cliMeta[sid] ?? {}
  const createdMs = Number(meta.createdAtMs ?? 0) || 0
  const created = createdMs ? createdMs / 1000 : st.ctime
  const workspace = String(meta.cwd || ws)
  const session: CodingSession = {
    agent: 'cursor',
    id: sid,
    title: title(firstUser) || 'Untitled chat',
    workspace,
    path: file,
    created_at: created,
    updated_at: st.mtime,
    messages: n,
    status: status(st.mtime, openTurn),
    last_user: title(lastUser, 160),
    last_assistant: title(lastAssistant, 160),
    source: sid in cliMeta ? 'cli' : 'ide',
    // the CLI resumes its own chats by id; an IDE chat it cannot reopen (the runner starts a
    // fresh CLI chat in the same workspace with the last exchange quoted)
    resumable: sid in cliMeta,
  }
  if (full) session.transcript = transcript.slice(-TRANSCRIPT_KEEP)
  return session
}

function samePath(a: string, b: string): boolean {
  try {
    return resolve(a) === resolve(b)
  } catch {
    return a === b
  }
}

async function cursorSessions(limit: number, workspace: string | undefined, env: NodeJS.ProcessEnv): Promise<CodingSession[]> {
  const root = sessionsRoot('cursor', env)
  if (!(await isDir(root))) return []
  const files: [number, string, string][] = []
  for (const project of await readdir(root).catch(() => [] as string[])) {
    const tdir = join(root, project, 'agent-transcripts')
    if (!(await isDir(tdir))) continue
    const ws = slugToPath(project)
    if (workspace && !samePath(ws, workspace)) continue
    for (const sdir of await readdir(tdir).catch(() => [] as string[])) {
      const entry = join(tdir, sdir)
      const f = (await isDir(entry)) ? join(entry, `${sdir}.jsonl`) : entry
      if (!f.endsWith('.jsonl')) continue
      const st = await statOf(f)
      if (st) files.push([st.mtime, f, ws])
    }
  }
  files.sort((a, b) => b[0] - a[0])
  const cliMeta = await cursorCliMeta(env)
  const out: CodingSession[] = []
  for (const [, f, ws] of files.slice(0, limit)) {
    const s = await cursorSession(f, ws, cliMeta, false)
    if (s) out.push(s)
  }
  return out
}

// -- Codex -------------------------------------------------------------------------------

async function walk(dir: string, match: (name: string) => boolean, out: string[] = []): Promise<string[]> {
  for (const name of await readdir(dir).catch(() => [] as string[])) {
    const path = join(dir, name)
    if (await isDir(path)) await walk(path, match, out)
    else if (match(name)) out.push(path)
  }
  return out
}

async function codexFiles(limit: number, env: NodeJS.ProcessEnv): Promise<string[]> {
  const root = sessionsRoot('codex', env)
  if (!(await isDir(root))) return []
  const files: [number, string][] = []
  for (const f of await walk(root, (n) => n.startsWith('rollout-') && n.endsWith('.jsonl'))) {
    const st = await statOf(f)
    if (st) files.push([st.mtime, f])
  }
  files.sort((a, b) => b[0] - a[0])
  return files.slice(0, Math.max(limit * 3, 30)).map(([, f]) => f)
}

async function codexSession(file: string, full: boolean): Promise<CodingSession | undefined> {
  const lines = await readLines(file)
  const st = await statOf(file)
  if (!st) return undefined
  let sid = ''
  let cwd = ''
  let originator = ''
  let created = st.ctime
  let firstUser = ''
  let lastUser = ''
  let lastAssistant = ''
  let openTurn = false
  let n = 0
  const transcript: CodingMessage[] = []
  for (const obj of lines) {
    const t = obj.type
    const payload = isObj(obj.payload) ? obj.payload : {}
    if (t === 'session_meta') {
      sid = String(payload.id ?? payload.session_id ?? '')
      cwd = String(payload.cwd ?? '')
      originator = String(payload.originator ?? payload.source ?? '')
      created = isoToTs(payload.timestamp) || created
    } else if (t === 'response_item' && payload.type === 'message') {
      const role = payload.role
      let text = textOf(payload.content)
      if (role === 'user') {
        text = clean(text)
        if (!text || text.startsWith('<')) continue
        firstUser = firstUser || text
        lastUser = text
      } else if (role === 'assistant') {
        text = text.trim()
        if (!text) continue
        lastAssistant = text
      } else continue
      n += 1
      if (full) transcript.push({ role, text })
    } else if (t === 'event_msg') {
      const k = payload.type
      if (k === 'task_started') openTurn = true
      else if (k === 'task_complete' || k === 'turn_aborted' || k === 'error') openTurn = false
    }
  }
  if (!sid) {
    const m = /-([0-9a-f-]{36})\.jsonl$/.exec(basename(file))
    sid = m?.[1] ?? basename(file, '.jsonl')
  }
  const session: CodingSession = {
    agent: 'codex',
    id: sid,
    title: title(firstUser) || 'Untitled thread',
    workspace: cwd,
    path: file,
    created_at: created,
    updated_at: st.mtime,
    messages: n,
    status: status(st.mtime, openTurn),
    last_user: title(lastUser, 160),
    last_assistant: title(lastAssistant, 160),
    source: originator,
    resumable: true,
  }
  if (full) session.transcript = transcript.slice(-TRANSCRIPT_KEEP)
  return session
}

async function codexSessions(limit: number, workspace: string | undefined, env: NodeJS.ProcessEnv): Promise<CodingSession[]> {
  const out: CodingSession[] = []
  for (const f of await codexFiles(limit, env)) {
    const s = await codexSession(f, false)
    if (!s || (workspace && !samePath(s.workspace || '', workspace))) continue
    out.push(s)
    if (out.length >= limit) break
  }
  return out
}

// -- Claude Code ------------------------------------------------------------------------------

async function claudeSession(file: string, full: boolean): Promise<CodingSession | undefined> {
  const lines = await readLines(file)
  const st = await statOf(file)
  if (!st) return undefined
  let cwd = ''
  let sid = basename(file, '.jsonl')
  let firstUser = ''
  let lastUser = ''
  let lastAssistant = ''
  let created = st.ctime
  let n = 0
  let lastRole = ''
  const transcript: CodingMessage[] = []
  for (const obj of lines) {
    const t = obj.type
    if (t !== 'user' && t !== 'assistant') continue
    cwd = cwd || String(obj.cwd ?? '')
    sid = String(obj.sessionId || sid)
    const msg = obj.message
    let text = isObj(msg) ? textOf(msg.content) : ''
    if (t === 'user') {
      text = clean(text)
      if (!text || text.startsWith('<') || obj.isMeta) continue
      if (!firstUser) {
        firstUser = text
        created = isoToTs(obj.timestamp) || created
      }
      lastUser = text
    } else {
      text = text.trim()
      if (!text) continue
      lastAssistant = text
    }
    lastRole = t
    n += 1
    if (full) transcript.push({ role: t, text })
  }
  const session: CodingSession = {
    agent: 'claude',
    id: sid,
    title: title(firstUser) || 'Untitled session',
    workspace: cwd || slugToPath(basename(resolve(file, '..')).replace(/^-+/, '')),
    path: file,
    created_at: created,
    updated_at: st.mtime,
    messages: n,
    status: status(st.mtime, lastRole === 'user'),
    last_user: title(lastUser, 160),
    last_assistant: title(lastAssistant, 160),
    source: '',
    resumable: true,
  }
  if (full) session.transcript = transcript.slice(-TRANSCRIPT_KEEP)
  return session
}

async function claudeSessions(limit: number, workspace: string | undefined, env: NodeJS.ProcessEnv): Promise<CodingSession[]> {
  const root = sessionsRoot('claude', env)
  if (!(await isDir(root))) return []
  const files: [number, string][] = []
  for (const project of await readdir(root).catch(() => [] as string[])) {
    const pdir = join(root, project)
    if (!(await isDir(pdir))) continue
    for (const name of await readdir(pdir).catch(() => [] as string[])) {
      if (!name.endsWith('.jsonl')) continue
      const f = join(pdir, name)
      const st = await statOf(f)
      if (st) files.push([st.mtime, f])
    }
  }
  files.sort((a, b) => b[0] - a[0])
  const out: CodingSession[] = []
  for (const [, f] of files.slice(0, Math.max(limit * 2, 20))) {
    const s = await claudeSession(f, false)
    if (!s || (workspace && !samePath(s.workspace || '', workspace))) continue
    out.push(s)
    if (out.length >= limit) break
  }
  return out
}

// -- dsh -------------------------------------------------------------------------------------

const DSH_SESSION_FILE = 'session.v4.jsonl.zstd'

/** The zstd frame magic (RFC 8878): a dsh session is many frames appended as it is written. */
const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])

/**
 * Decompress a dsh session file. The store appends one zstd frame per write, and Node's
 * `zstdDecompressSync` stops at the first frame's end, so a long chat would lose everything
 * after its opening lines. So the frames are cut at the magic and decompressed one by one;
 * a frame that does not decompress is skipped rather than failing the whole read.
 */
function decompressZstdFrames(buf: Buffer): string {
  const starts: number[] = []
  let at = buf.indexOf(ZSTD_MAGIC)
  while (at !== -1) {
    starts.push(at)
    at = buf.indexOf(ZSTD_MAGIC, at + ZSTD_MAGIC.length)
  }
  if (starts.length === 0) return ''
  const parts: string[] = []
  for (let i = 0; i < starts.length; i++) {
    const end = i + 1 < starts.length ? starts[i + 1]! : buf.length
    try {
      parts.push(zstdDecompressSync(buf.subarray(starts[i]!, end)).toString('utf8'))
    } catch {
      continue
    }
  }
  return parts.join('')
}

/**
 * The JSON objects of a dsh session file: zstd-compressed JSONL, one object a line. A file
 * this Node cannot decompress is a session with nothing to show rather than an error.
 */
async function readZstdLines(path: string, limitBytes = LINE_LIMIT_BYTES): Promise<Obj[]> {
  const out: Obj[] = []
  let text: string
  try {
    const info = await stat(path)
    if (info.size > limitBytes) return out
    const fh = await open(path, 'r')
    try {
      text = decompressZstdFrames(await fh.readFile())
    } finally {
      await fh.close()
    }
  } catch {
    return out
  }
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    try {
      const obj: unknown = JSON.parse(line)
      if (isObj(obj)) out.push(obj)
    } catch {
      continue
    }
  }
  return out
}

/** The text of a dsh content array: `text` parts only (reasoning and tool calls are not words). */
function dshContentText(content: unknown): string {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  const parts: string[] = []
  for (const c of content) {
    if (isObj(c) && c.type === 'text' && c.text) parts.push(String(c.text))
  }
  return parts.join('\n')
}

async function dshSession(file: string, full: boolean): Promise<CodingSession | undefined> {
  const lines = await readZstdLines(file)
  const st = await statOf(file)
  if (!st) return undefined
  const dirId = basename(resolve(file, '..'))
  let sid = dirId
  let cwd = ''
  let created = st.ctime
  let storedTitle = ''
  let firstUser = ''
  let lastUser = ''
  let lastAssistant = ''
  let openTurn = false
  let n = 0
  const transcript: CodingMessage[] = []
  for (const obj of lines) {
    const t = obj.type
    const data = isObj(obj.data) ? obj.data : {}
    if (t === 'session') {
      // a subagent (or a forked session) is the harness's own working session, not a chat the
      // person had: it has no place in the apps' list
      if (String(obj.origin ?? '') === 'subagent' || obj.parentSession !== undefined) return undefined
      sid = String(obj.id ?? sid)
      cwd = cwd || String(obj.cwd ?? '')
      const ms = Number(obj.createdAt ?? 0) || 0
      if (ms) created = ms / 1000
    } else if (t === 'session/title') {
      storedTitle = storedTitle || String(data.title ?? '')
    } else if (t === 'user/message') {
      // only what the person typed: the store also carries runtime context, the skill
      // catalog and background-job notices as user messages, with `source.kind` naming them
      const source = isObj(data.source) ? data.source : {}
      if (String(source.kind ?? '') !== 'user') continue
      const text = clean(dshContentText(data.content))
      if (!text) continue
      firstUser = firstUser || text
      lastUser = text
      openTurn = true
      n += 1
      if (full) transcript.push({ role: 'user', text })
    } else if (t === 'assistant/message') {
      const msg = isObj(data.message) ? data.message : {}
      const text = dshContentText(msg.content).trim()
      if (!text) continue
      lastAssistant = text
      n += 1
      if (full) transcript.push({ role: 'assistant', text })
    } else if (t === 'turn/end') {
      openTurn = false
    }
  }
  const session: CodingSession = {
    agent: 'dsh',
    id: sid,
    title: title(storedTitle || firstUser) || 'Untitled session',
    workspace: cwd || slugToPath(basename(resolve(file, '..', '..')).replace(/^-+|-+$/g, '')),
    path: file,
    created_at: created,
    updated_at: st.mtime,
    messages: n,
    status: status(st.mtime, openTurn),
    last_user: title(lastUser, 160),
    last_assistant: title(lastAssistant, 160),
    source: '',
    // `dsh headless --session-id` adopts a session of this store, so a chat read here can be continued
    resumable: true,
  }
  if (full) session.transcript = transcript.slice(-TRANSCRIPT_KEEP)
  return session
}

async function dshSessions(limit: number, workspace: string | undefined, env: NodeJS.ProcessEnv): Promise<CodingSession[]> {
  const root = sessionsRoot('dsh', env)
  if (!(await isDir(root))) return []
  const files: [number, string][] = []
  for (const project of await readdir(root).catch(() => [] as string[])) {
    const pdir = join(root, project)
    if (!(await isDir(pdir))) continue
    for (const name of await readdir(pdir).catch(() => [] as string[])) {
      // a session directory holds session.v4.jsonl.zstd; older stores may keep session.jsonl
      const sdir = join(pdir, name)
      if (!(await isDir(sdir))) continue
      const f = join(sdir, DSH_SESSION_FILE)
      const st = (await statOf(f)) ?? (await statOf(join(sdir, 'session.jsonl')))
      if (st) files.push([st.mtime, (await statOf(f)) ? f : join(sdir, 'session.jsonl')])
    }
  }
  files.sort((a, b) => b[0] - a[0])
  const out: CodingSession[] = []
  for (const [, f] of files.slice(0, Math.max(limit * 2, 20))) {
    const s = await dshSession(f, false)
    if (!s || (workspace && !samePath(s.workspace || '', workspace))) continue
    out.push(s)
    if (out.length >= limit) break
  }
  return out
}

// ------------------------------------------------------------------------- the public readers

/** Newest first, across the agents asked for (all when `agent` is undefined). */
export async function sessions(agent?: AgentId, limit = 30, workspace?: string, env: NodeJS.ProcessEnv = process.env): Promise<CodingSession[]> {
  limit = Math.max(1, Math.min(limit, 200))
  const readers: Record<AgentId, (limit: number, workspace: string | undefined, env: NodeJS.ProcessEnv) => Promise<CodingSession[]>> = {
    cursor: cursorSessions,
    codex: codexSessions,
    claude: claudeSessions,
    dsh: dshSessions,
  }
  const picked = agent ? [agent] : AGENT_IDS
  const out: CodingSession[] = []
  for (const a of picked) out.push(...(await readers[a](limit, workspace || undefined, env)))
  out.sort((a, b) => b.updated_at - a.updated_at)
  return out.slice(0, limit)
}

/** One session with its transcript (the last 400 messages), or undefined. */
export async function readSession(agent: AgentId, sessionId: string, env: NodeJS.ProcessEnv = process.env): Promise<CodingSession | undefined> {
  sessionId = sessionId.trim()
  if (!sessionId || sessionId.includes('/') || sessionId.includes('\\') || sessionId.includes('..')) return undefined
  const root = sessionsRoot(agent, env)
  if (!(await isDir(root))) return undefined
  if (agent === 'cursor') {
    for (const project of await readdir(root).catch(() => [] as string[])) {
      const f = join(root, project, 'agent-transcripts', sessionId, `${sessionId}.jsonl`)
      if (await statOf(f)) return cursorSession(f, slugToPath(project), await cursorCliMeta(env), true)
    }
    return undefined
  }
  if (agent === 'codex') {
    const [f] = await walk(root, (n) => n.startsWith('rollout-') && n.endsWith(`${sessionId}.jsonl`))
    return f ? codexSession(f, true) : undefined
  }
  if (agent === 'dsh') {
    // the session's own directory is named after its id: <slug>/<id>/session.v4.jsonl.zstd
    for (const project of await readdir(root).catch(() => [] as string[])) {
      const sdir = join(root, project, sessionId)
      const f = join(sdir, DSH_SESSION_FILE)
      if (await statOf(f)) return dshSession(f, true)
      const legacy = join(sdir, 'session.jsonl')
      if (await statOf(legacy)) return dshSession(legacy, true)
    }
    return undefined
  }
  const [f] = await walk(root, (n) => n === `${sessionId}.jsonl`)
  return f ? claudeSession(f, true) : undefined
}
