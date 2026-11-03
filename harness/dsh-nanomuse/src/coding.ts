/**
 * The coding agents as a service of the desktop: one place the page, the hub and — through
 * the hub — the account's other devices go through, a port of the runtime's
 * `nanomuse/coding/service.py` (`docs/coding-agents.md`).
 *
 * Local calls read the disk and start CLI runs here (`coding-readers.ts`,
 * `coding-runner.ts`); `device` names another computer of the account and the same
 * request travels over the hub as `coding.*` actions. Incoming `coding.*` calls from the
 * other devices are answered by `handle()`; the cloud service gates `coding.send` and
 * `coding.stop` behind the person's say-so the way it gates `shell` (`docs/hub.md`).
 *
 * Runs publish on a small bus as `{kind: "coding", event, agent, session_id, run, device?}`
 * — the runtime's bus message, so the page follows a run live over `GET coding/events`;
 * the finished ones are kept (the last 50) in memory and in `<dir>/coding/runs.json`, so a
 * restart of the app does not lose what was asked and answered.
 */
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { dirname } from 'node:path'
import { AGENTS, cliFor, detect, isAgentId, readSession, sessions as readSessions, type AgentId, type AgentInfo, type CodingSession } from './coding-readers.ts'
import { Run, runFromView, startRun, type RunView } from './coding-runner.ts'
import { HubError, type IncomingCall } from './hub.ts'

/** The hub actions this computer answers, in the runtime's order. */
export const CODING_ACTIONS = ['coding.agents', 'coding.sessions', 'coding.session', 'coding.send', 'coding.stop', 'coding.runs'] as const
export type CodingAction = (typeof CODING_ACTIONS)[number]
/** The two that do something *to* this computer: the person here agrees first unless remote control is on. */
export const GATED_CODING_ACTIONS: ReadonlySet<string> = new Set(['coding.send', 'coding.stop'])

export const KEEP_RUNS = 50
const DETECT_TTL_MS = 60_000

export type Args = Record<string, unknown>
export type Result = Record<string, unknown>

/** What a run publishes while it goes: the runtime's `{"kind": "coding", …}` bus message. */
export interface CodingMessage {
  kind: 'coding'
  event: Record<string, unknown>
  agent: string
  session_id: string
  device?: string
  run: RunView | null
}

/** The slice of the hub client the service needs; the tests pass a fake. */
export interface HubLike {
  deviceId: string | undefined
  devices: readonly { id: string; name: string; online: boolean; actions: readonly string[] }[]
  find(ref: string): { id: string; name: string; online: boolean; actions: readonly string[] } | undefined
  call(to: string, action: string, args: Args, options?: { timeoutMs?: number | undefined; onEvent?: ((body: Result) => void) | undefined }): Promise<Result>
}

export interface CodingServiceOptions {
  /** `<dir>/coding/runs.json`; nothing is kept on disk without it. */
  storePath?: string | undefined
  hub: HubLike
  log?: ((level: 'info' | 'warn' | 'debug', text: string) => void) | undefined
  /** Platform and environment, for tests. */
  env?: NodeJS.ProcessEnv | undefined
  which?: ((agent: AgentId) => string | undefined) | undefined
}

/** A short line for the ask card and the log: which agent, what was said. */
export function codingBrief(action: string, args: Args): string {
  const agent = isAgentId(args.agent) ? AGENTS[args.agent].name : String(args.agent ?? '')
  if (action === 'coding.send') {
    const text = typeof args.text === 'string' ? args.text.replace(/\s+/g, ' ').trim().slice(0, 80) : ''
    return [agent, text].filter(Boolean).join(': ')
  }
  if (action === 'coding.stop') return String(args.run ?? '')
  return agent
}

export class CodingService {
  readonly runs = new Map<string, Run>()
  private readonly tasks = new Map<string, Promise<Run>>()
  private detected: AgentInfo[] = []
  private detectedAt = 0
  private readonly listeners = new Set<(message: CodingMessage) => void>()
  private readonly streams = new Set<ServerResponse>()
  private loaded: Promise<void> | undefined

  constructor(private readonly options: CodingServiceOptions) {}

  private get env(): NodeJS.ProcessEnv {
    return this.options.env ?? process.env
  }

  private log(level: 'info' | 'warn' | 'debug', text: string): void {
    this.options.log?.(level, text)
  }

  // ------------------------------------------------------------------ the record

  /** The finished runs of earlier sessions of the app, newest kept; once. */
  load(): Promise<void> {
    this.loaded ??= this.read()
    return this.loaded
  }

  private async read(): Promise<void> {
    const path = this.options.storePath
    if (!path) return
    let rows: unknown
    try {
      rows = JSON.parse(await readFile(path, 'utf8'))
    } catch (error: unknown) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') this.log('warn', `coding: could not read ${path}: ${message(error)}`)
      return
    }
    if (!Array.isArray(rows)) return
    for (const row of rows.slice(-KEEP_RUNS)) {
      if (!row || typeof row !== 'object') continue
      const run = runFromView(row as Record<string, unknown>)
      if (run) this.runs.set(run.id, run)
    }
  }

  /** Every run that is not still going, oldest first, replaced atomically. */
  private async save(): Promise<void> {
    const path = this.options.storePath
    if (!path) return
    const rows = [...this.runs.values()]
      .filter((r) => r.status !== 'running')
      .sort((a, b) => a.started_at - b.started_at)
      .slice(-KEEP_RUNS)
      .map((r) => r.view())
    try {
      await mkdir(dirname(path), { recursive: true })
      const tmp = `${path}.tmp`
      await writeFile(tmp, JSON.stringify(rows), 'utf8')
      await rename(tmp, path)
    } catch (error: unknown) {
      this.log('warn', `coding: could not write ${path}: ${message(error)}`)
    }
  }

  private trim(): void {
    if (this.runs.size <= KEEP_RUNS) return
    const finished = [...this.runs.values()].filter((r) => r.status !== 'running').sort((a, b) => a.started_at - b.started_at)
    for (const r of finished.slice(0, this.runs.size - KEEP_RUNS)) this.runs.delete(r.id)
  }

  // ------------------------------------------------------------------ the bus

  /** Hear every run step (the page's stream, the tests). */
  subscribe(listener: (message: CodingMessage) => void): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  private publish(msg: CodingMessage): void {
    for (const listener of this.listeners) {
      try {
        listener(msg)
      } catch {
        // a listener's problem is not ours
      }
    }
    if (this.streams.size === 0) return
    const data = `data: ${JSON.stringify(msg)}\n\n`
    for (const res of this.streams) {
      try {
        res.write(data)
      } catch {
        this.streams.delete(res)
      }
    }
  }

  // ------------------------------------------------------------------ local

  /** Installed agents with versions (cached a minute; `running` is always live). */
  async agents(fresh = false): Promise<AgentInfo[]> {
    if (fresh || Date.now() - this.detectedAt > DETECT_TTL_MS) {
      this.detected = await detect(true, this.env)
      this.detectedAt = Date.now()
    } else {
      const live = new Map((await detect(false, this.env)).map((a) => [a.id, a.running]))
      for (const a of this.detected) a.running = live.get(a.id) ?? 0
    }
    return this.detected
  }

  /** Whether any of them is on this computer (CLI or store). */
  async anyInstalled(): Promise<boolean> {
    return (await this.agents()).some((a) => a.installed)
  }

  async sessions(agent?: string, limit = 30, workspace?: string): Promise<(CodingSession & { run?: string })[]> {
    if (agent && !isAgentId(agent)) throw new HubError('unknown_agent', `no coding agent called '${agent}'`)
    const out: (CodingSession & { run?: string })[] = await readSessions(isAgentId(agent) ? agent : undefined, limit, workspace || undefined, this.env)
    // a run in progress marks its session as running even before the agent writes
    for (const r of this.runs.values()) {
      if (r.status !== 'running') continue
      const sid = r.result_session_id || r.session_id
      for (const s of out) {
        if (s.agent === r.agent && s.id === sid) {
          s.status = 'running'
          s.run = r.id
        }
      }
    }
    return out
  }

  async session(agent: string, sessionId: string): Promise<Result> {
    if (!isAgentId(agent)) throw new HubError('unknown_agent', `no coding agent called '${agent}'`)
    const s = await readSession(agent, sessionId, this.env)
    if (!s) throw new HubError('no_session', 'that session is not on this computer')
    const d: Result = { ...s, transcript: s.transcript ?? [] }
    const runs = [...this.runs.values()].filter((r) => r.agent === agent && (r.result_session_id || r.session_id) === sessionId).map((r) => r.view())
    if (runs.length) d.runs = runs
    return d
  }

  /** Start a run; resolves at once with the run (or, with `wait`, when it ends). */
  async send(agent: string, text: string, sessionId = '', workspace = '', wait = false): Promise<RunView> {
    if (!isAgentId(agent)) throw new HubError('unknown_agent', `no coding agent called '${agent}'`)
    if (!text.trim()) throw new HubError('usage', 'text is required')
    const find = this.options.which ?? ((a: AgentId) => cliFor(a, this.env))
    if (!find(agent)) throw new HubError('not_installed', `${AGENTS[agent].name} is not installed on this computer`)
    if (sessionId && [...this.runs.values()].some((r) => r.status === 'running' && r.agent === agent && (r.result_session_id || r.session_id) === sessionId)) {
      throw new HubError('busy', 'that session already has a message running')
    }
    this.log('info', `coding: ${AGENTS[agent].name}${sessionId ? ` (${sessionId.slice(0, 12)})` : ''}: ${text.slice(0, 100).replace(/\s+/g, ' ')}`)
    const runId = `run_${Math.random().toString(16).slice(2, 10).padEnd(8, '0')}`
    let registered: Run | undefined
    const task = startRun({
      agent,
      text,
      sessionId,
      workspace,
      runId,
      env: this.env,
      readerEnv: this.env,
      which: find,
      register: (run) => {
        registered = run
        this.runs.set(runId, run)
      },
      onEvent: (ev) => {
        const run = this.runs.get(runId)
        const kind = String(ev.kind ?? '')
        this.publish({
          kind: 'coding',
          event: ev,
          agent,
          session_id: (run?.result_session_id || '') || sessionId,
          run: run && (kind === 'started' || kind === 'done' || kind === 'error') ? run.view() : null,
        })
      },
    })
    this.tasks.set(runId, task)
    const settled = task
      .then((run) => {
        this.runs.set(runId, run)
        return run
      })
      .catch((error: unknown) => {
        const run = this.runs.get(runId) ?? new Run(runId, agent, sessionId, workspace, text)
        this.runs.set(runId, run)
        if (run.status === 'running') {
          run.status = 'failed'
          run.error = message(error).slice(0, 300)
          run.ended_at = Date.now() / 1000
        }
        return run
      })
      .then(async (run) => {
        this.tasks.delete(runId)
        this.publish({ kind: 'coding', event: { kind: 'run' }, agent, session_id: run.result_session_id || sessionId, run: run.view() })
        this.trim()
        await this.save()
        return run
      })
    this.tasks.set(runId, settled)
    if (wait) return (await settled).view()
    // the Run is registered synchronously inside startRun before its first await
    await Promise.resolve()
    const run = registered ?? this.runs.get(runId)
    return run
      ? run.view()
      : { id: runId, agent, session_id: sessionId, asked_session_id: sessionId, workspace, text, started_at: Date.now() / 1000, ended_at: null, status: 'running', output: '', resumed: Boolean(sessionId), error: '', tools: 0 }
  }

  stop(runId: string): boolean {
    const run = this.runs.get(runId)
    return run ? run.stop() : false
  }

  stopAll(): number {
    let n = 0
    for (const id of this.runs.keys()) if (this.stop(id)) n += 1
    return n
  }

  listRuns(limit = 20): RunView[] {
    return [...this.runs.values()]
      .sort((a, b) => b.started_at - a.started_at)
      .slice(0, limit)
      .map((r) => r.view())
  }

  // ------------------------------------------------------------------ over the hub, inbound

  /**
   * A `coding.*` action asked by another device. `coding.send` with `wait` (the default) follows
   * the run and forwards each step as an `event` frame whose body carries the run id, so the
   * caller can `coding.stop` it; the `result` is the finished run.
   */
  async handle(action: string, args: Args, call?: IncomingCall): Promise<Result> {
    await this.load()
    switch (action) {
      case 'coding.agents':
        return { agents: await this.agents(Boolean(args.fresh)) }
      case 'coding.sessions':
        return { sessions: await this.sessions(String(args.agent ?? ''), Number(args.limit) || 30, String(args.workspace ?? '')) }
      case 'coding.session':
        return this.session(String(args.agent ?? ''), String(args.session_id ?? ''))
      case 'coding.stop':
        return { stopped: this.stop(String(args.run ?? '')) }
      case 'coding.runs':
        return { runs: this.listRuns(Number(args.limit) || 20) }
      case 'coding.send': {
        const agent = String(args.agent ?? '')
        const text = String(args.text ?? '')
        const sessionId = String(args.session_id ?? '')
        const workspace = String(args.workspace ?? '')
        const wait = args.wait === undefined ? true : Boolean(args.wait)
        if (!wait || !call) return { ...(await this.send(agent, text, sessionId, workspace, false)) }
        let runId = ''
        const off = this.subscribe((msg) => {
          if (!runId) return
          const ev = msg.event
          if (msg.run?.id !== runId && ev.run !== runId) return
          const kind = String(ev.kind ?? '')
          if (kind === 'text' || kind === 'tool' || kind === 'started') call.event({ kind: 'coding', ...ev, run: runId })
        })
        try {
          const started = await this.send(agent, text, sessionId, workspace, false)
          runId = started.id
          const task = this.tasks.get(runId)
          return { ...(task ? (await task).view() : started) }
        } finally {
          off()
        }
      }
      default:
        throw new HubError('unknown_action', `this computer does not do '${action}'`)
    }
  }

  // ------------------------------------------------------------------ over the hub, outbound

  /** The same request on another computer of the account, through the hub. */
  async remote(device: string, action: CodingAction, args: Args, onEvent?: (body: Result) => void): Promise<Result> {
    const hub = this.options.hub
    const dev = hub.devices.find((d) => d.id === device) ?? hub.find(device)
    if (!dev) throw new HubError('no_device', `no device matches '${device}'`)
    if (!dev.online) throw new HubError('device_offline', `${dev.name || device} is offline`)
    if (!dev.actions.includes(action)) throw new HubError('not_supported', `${dev.name || device} runs an older nanoMuse without coding agents`)
    return hub.call(dev.id, action, args, { timeoutMs: action === 'coding.send' ? 1_800_000 : 60_000, onEvent })
  }

  /**
   * `coding.send` on another computer, followed from here: its steps are re-published on this
   * bus (with `device`) and the run is kept in `runs` like a local one.
   */
  async remoteSend(device: string, args: Args): Promise<RunView> {
    await this.load()
    const hub = this.options.hub
    const dev = hub.devices.find((d) => d.id === device) ?? hub.find(device)
    const agent = String(args.agent ?? '')
    if (!isAgentId(agent)) throw new HubError('unknown_agent', `no coding agent called '${agent}'`)
    const runId = `run_${Math.random().toString(16).slice(2, 10).padEnd(8, '0')}`
    const shadow = new Run(runId, agent, String(args.session_id ?? ''), String(args.workspace ?? ''), String(args.text ?? ''))
    shadow.device = dev?.name || device
    this.runs.set(runId, shadow)
    const publish = (ev: Record<string, unknown>, run: RunView | null = null) => {
      const msg: CodingMessage = { kind: 'coding', event: { ...ev, run: runId }, agent, session_id: shadow.result_session_id || shadow.session_id, device: shadow.device, run }
      this.publish(msg)
    }
    const go = async (): Promise<Run> => {
      try {
        const result = await this.remote(device, 'coding.send', { ...args, wait: true }, (body) => {
          const kind = String(body.kind ?? '')
          if (kind === 'text') {
            if (body.partial) shadow.current += String(body.text ?? '')
            else {
              shadow.current = String(body.text ?? '')
              shadow.commit()
            }
          } else if (kind === 'tool' && String(body.phase ?? 'started') === 'started') shadow.tools += 1
          else if (kind === 'started' && body.session_id) shadow.result_session_id = String(body.session_id)
          publish(body)
        })
        const status = String(result.status ?? 'done')
        shadow.status = status === 'failed' || status === 'stopped' ? status : 'done'
        shadow.output = String(result.output ?? shadow.output)
        shadow.result_session_id = String(result.session_id ?? shadow.result_session_id)
        shadow.tools = Number(result.tools ?? shadow.tools)
        shadow.error = String(result.error ?? '')
        shadow.resumed = Boolean(result.resumed)
      } catch (error: unknown) {
        shadow.status = 'failed'
        shadow.error = error instanceof HubError ? `${error.message} (${error.code})` : message(error).slice(0, 300)
      } finally {
        shadow.ended_at = Date.now() / 1000
        this.tasks.delete(runId)
        publish({ kind: 'run' }, shadow.view())
        this.trim()
        void this.save()
      }
      return shadow
    }
    this.tasks.set(runId, go())
    publish({ kind: 'run' }, shadow.view())
    return shadow.view()
  }

  // ------------------------------------------------------------------ the page's API

  /**
   * The routes under `…/cloud/coding`: `GET /coding?device=`, `GET /coding/sessions`,
   * `GET /coding/sessions/<agent>/<id>`, `POST /coding/send`, `POST /coding/stop`,
   * `GET /coding/events` (the bus as SSE). Resolves false when the route is not one of these.
   */
  async http(route: string, req: IncomingMessage, res: ServerResponse, url: URL, body: () => Promise<Args>, reply: (res: ServerResponse, status: number, body?: unknown) => void): Promise<boolean> {
    await this.load()
    const device = url.searchParams.get('device') ?? ''
    try {
      if (req.method === 'GET' && route === '') {
        if (device) {
          const [a, r] = await Promise.all([this.remote(device, 'coding.agents', {}), this.remote(device, 'coding.runs', { limit: 20 }).catch(() => ({ runs: [] }))])
          reply(res, 200, { agents: a.agents ?? [], runs: r.runs ?? [] })
        } else reply(res, 200, { agents: await this.agents(url.searchParams.get('fresh') === '1'), runs: this.listRuns() })
        return true
      }
      if (req.method === 'GET' && route === '/sessions') {
        const agent = url.searchParams.get('agent') ?? ''
        const limit = Number(url.searchParams.get('limit') ?? 30) || 30
        const workspace = url.searchParams.get('workspace') ?? ''
        if (device) reply(res, 200, await this.remote(device, 'coding.sessions', { agent, limit, workspace }))
        else reply(res, 200, { sessions: await this.sessions(agent, limit, workspace) })
        return true
      }
      const one = /^\/sessions\/([a-z]+)\/([^/]+)$/.exec(route)
      if (req.method === 'GET' && one) {
        const agent = one[1] ?? ''
        const id = decodeURIComponent(one[2] ?? '')
        if (device) reply(res, 200, await this.remote(device, 'coding.session', { agent, session_id: id }))
        else reply(res, 200, await this.session(agent, id))
        return true
      }
      if (req.method === 'POST' && route === '/send') {
        const b = await body()
        const args = { agent: String(b.agent ?? ''), text: String(b.text ?? ''), session_id: String(b.session_id ?? ''), workspace: String(b.workspace ?? '') }
        const to = String(b.device ?? '')
        if (to) reply(res, 200, await this.remoteSend(to, args))
        else reply(res, 200, await this.send(args.agent, args.text, args.session_id, args.workspace, b.wait === true))
        return true
      }
      if (req.method === 'POST' && route === '/stop') {
        const b = await body()
        const to = String(b.device ?? '')
        const runId = String(b.run_id ?? b.run ?? '')
        if (to) reply(res, 200, await this.remote(to, 'coding.stop', { run: runId }))
        else reply(res, 200, { stopped: this.stop(runId) })
        return true
      }
      if (req.method === 'GET' && route === '/events') {
        this.stream(req, res)
        return true
      }
    } catch (error: unknown) {
      if (error instanceof HubError) {
        const status = error.code === 'no_session' || error.code === 'no_device' ? 404 : error.code === 'usage' || error.code === 'unknown_agent' ? 400 : error.code === 'busy' ? 409 : 502
        reply(res, status, { error: { code: error.code, message: error.message } })
        return true
      }
      throw error
    }
    return false
  }

  private stream(req: IncomingMessage, res: ServerResponse): void {
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store', connection: 'keep-alive', 'x-accel-buffering': 'no' })
    res.write('retry: 2000\n: open\n\n')
    this.streams.add(res)
    const beat = setInterval(() => {
      try {
        res.write(': beat\n\n')
      } catch {
        // closed below
      }
    }, 20_000)
    const done = () => {
      clearInterval(beat)
      this.streams.delete(res)
    }
    req.on('close', done)
    res.on('close', done)
  }

  /** On the way out: end every run still going. */
  close(): void {
    try {
      this.stopAll()
    } catch {
      // nothing to stop
    }
    for (const res of this.streams) {
      try {
        res.end()
      } catch {
        // already gone
      }
    }
    this.streams.clear()
  }
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
