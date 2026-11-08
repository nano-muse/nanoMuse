/**
 * "Try it" for the hands: a test screenshot and a small mouse move, run the way the real
 * thing runs — a fresh `nanomuse mcp` started by this host, which the desktop app started.
 * On macOS that chain is what the permission panes grant: a check run any other way (a
 * terminal, a different binary) would pass or fail for the wrong process.
 *
 * The runtime speaks MCP over stdio (one JSON-RPC message per line); this is the small
 * client for two calls: `computer_screen` and `computer_act {action: "move"}`. The result
 * tells the settings page what the person needs to do next: a black capture means Screen
 * Recording for nanoMuse Desktop (and a relaunch), a refused move means Accessibility.
 */
import { spawn as nodeSpawn, spawnSync, type ChildProcess } from 'node:child_process'
import { access, constants } from 'node:fs/promises'
import { delimiter, extname, isAbsolute, join } from 'node:path'

const SIZE_PART = /^(\d{2,5})[×x](\d{2,5})$/

/**
 * The head line of what `computer_screen` / `computer_act` say: `<window in front> · <WxH> · …`
 * → title, size and whether the hands are in window mode. It is the line that carries the
 * size, wherever it stands: `computer_act` puts "Done. Screen now:" first, and 0.1.37 took
 * that for the window's title (so the stage was titled "Done. Screen now:" and an "always
 * allow" was kept for that "app"). The stage (cloud.ts) and the checks here share it.
 */
export function screenHead(text: string): { title: string; width: number; height: number; mode: 'screen' | 'window' } {
  const lines = text.split('\n').filter((l) => l.trim())
  const line = lines.find((l) => l.split(' · ').some((p) => SIZE_PART.test(p.trim()))) ?? ''
  const parts = line.split(' · ').map((p) => p.trim())
  let width = 0
  let height = 0
  let mode: 'screen' | 'window' = 'screen'
  const rest: string[] = []
  for (const part of parts) {
    const m = SIZE_PART.exec(part)
    if (m) {
      width = Number(m[1])
      height = Number(m[2])
    } else if (/^window(?: mode)?$/i.test(part)) mode = 'window'
    else if (!/^keyboard (shown|hidden)$/.test(part)) rest.push(part)
  }
  return { title: (rest[0] ?? '').slice(0, 120), width, height, mode }
}

/** Which binary the hands run, and whether it is really there. */
export interface RuntimeInfo {
  /** `NANOMUSE_PY` as set, or the `nanomuse` found on PATH, or empty. */
  path: string
  /** `env` when `NANOMUSE_PY` is set (the desktop app points it at its bundled runtime), `path` when found on PATH, `none`. */
  source: 'env' | 'path' | 'none'
  /** The file exists and is executable. */
  ok: boolean
  /** Why not, for the row in Settings. */
  problem?: 'missing' | 'not-executable' | 'not-found'
  /** Linux: the display session the hands would work on (absent elsewhere). */
  display?: DisplayInfo
}

/**
 * The sentence the desktop operator and the runtime (`nanomuse.computer.hands.WAYLAND_TEXT`)
 * both give for a Wayland login — the same words in Settings → Computer use, so the three
 * places agree.
 */
export const WAYLAND_TEXT = 'Wayland session: no global screen or cursor for a program to drive. Log in with Xorg (the session chooser on the login screen), or run the hands on another computer of the account.'

/** Linux: which kind of display session this is, and why the hands are off when they are. */
export interface DisplayInfo {
  session: 'x11' | 'wayland' | 'none'
  /** Empty on X11; the runtime's reason otherwise. */
  reason: string
}

/**
 * Read from the environment the way the operator and the runtime do: `XDG_SESSION_TYPE`
 * says `wayland`, or there is a `WAYLAND_DISPLAY` and no `DISPLAY` (a compositor started by
 * hand); an X11 session has a `DISPLAY`. `undefined` off Linux.
 */
export function displayInfo(env: NodeJS.ProcessEnv = process.env, platform: NodeJS.Platform = process.platform): DisplayInfo | undefined {
  if (platform !== 'linux') return undefined
  const type = (env.XDG_SESSION_TYPE ?? '').trim().toLowerCase()
  const x = (env.DISPLAY ?? '').trim()
  const wayland = (env.WAYLAND_DISPLAY ?? '').trim()
  if (type === 'wayland' || (wayland && !x)) return { session: 'wayland', reason: WAYLAND_TEXT }
  if (x) return { session: 'x11', reason: '' }
  return { session: 'none', reason: 'No display: DISPLAY is not set, so there is no screen for the hands to see.' }
}

export async function runtimeInfo(env: NodeJS.ProcessEnv = process.env): Promise<RuntimeInfo> {
  const configured = (env.NANOMUSE_PY ?? '').trim()
  if (configured) {
    const ok = await executable(configured)
    if (ok) return { path: configured, source: 'env', ok: true }
    const exists = await access(configured, constants.F_OK).then(
      () => true,
      () => false,
    )
    return { path: configured, source: 'env', ok: false, problem: exists ? 'not-executable' : 'missing' }
  }
  for (const dir of (env.PATH ?? '').split(delimiter)) {
    if (!dir) continue
    for (const name of process.platform === 'win32' ? ['nanomuse.exe', 'nanomuse.cmd', 'nanomuse'] : ['nanomuse']) {
      const candidate = join(dir, name)
      if (isAbsolute(candidate) && (await executable(candidate))) return { path: candidate, source: 'path', ok: true }
    }
  }
  return { path: '', source: 'none', ok: false, problem: 'not-found' }
}

/** Windows has no executable bit: what runs is decided by the extension. */
const WINDOWS_RUNNABLE = ['.exe', '.cmd', '.bat', '.com']

async function executable(path: string): Promise<boolean> {
  const present = await access(path, constants.X_OK).then(
    () => true,
    () => false,
  )
  if (!present) return false
  return process.platform !== 'win32' || WINDOWS_RUNNABLE.includes(extname(path).toLowerCase())
}

type Content = { type: string; text?: string; data?: string; mimeType?: string }
export interface ToolReply {
  content: Content[]
  isError: boolean
}

export interface McpOptions {
  command: string
  args?: string[]
  env?: NodeJS.ProcessEnv
  timeoutMs?: number
  spawn?: typeof nodeSpawn
}

export class HandsCheckError extends Error {
  constructor(
    message: string,
    readonly stderr = '',
  ) {
    super(message)
    this.name = 'HandsCheckError'
  }
}

/**
 * End the runtime and everything it started. A plain `kill()` ends the runtime alone: the
 * helpers it started (the screenshot helper, say) keep running orphaned with their stdio
 * pipes gone, so every timeout here takes the tree - `taskkill /T` walks the parentage on
 * Windows, and the runtime's own process group answers a negative pid on posix (the coding
 * runner's stop does the same). Falls back to `kill()` when the tree walk cannot run.
 */
function killTree(child: ChildProcess): void {
  try {
    if (process.platform !== 'win32') {
      if (child.pid) process.kill(-child.pid, 'SIGTERM')
      else child.kill()
    } else {
      // taskkill /T walks the tree by parentage; /F because the runtime is being given up on
      const killed = child.pid
        ? spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, timeout: 10_000 })
        : null
      if (!killed || killed.error || killed.status !== 0) child.kill()
    }
  } catch {
    child.kill()
  }
}

/**
 * One MCP session: initialize, the calls, exit. The child runs in a process group of its
 * own (posix) so that giving up on it can end the whole tree, not the runtime alone.
 */
export async function withMcp<T>(options: McpOptions, body: (call: (tool: string, args: Record<string, unknown>) => Promise<ToolReply>) => Promise<T>): Promise<T> {
  const spawnImpl = options.spawn ?? nodeSpawn
  const timeoutMs = options.timeoutMs ?? 60_000
  let child: ChildProcess
  try {
    child = spawnImpl(options.command, options.args ?? ['mcp'], { stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, ...options.env }, detached: process.platform !== 'win32' })
  } catch (error: unknown) {
    throw new HandsCheckError(`could not start the runtime: ${error instanceof Error ? error.message : String(error)}`)
  }
  let stderr = ''
  child.stderr?.setEncoding('utf8')
  child.stderr?.on('data', (chunk: string) => {
    stderr = (stderr + chunk).slice(-4000)
  })
  const pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>()
  let nextId = 1
  let buffer = ''
  const failAll = (error: Error): void => {
    for (const p of pending.values()) p.reject(error)
    pending.clear()
  }
  child.stdout?.setEncoding('utf8')
  child.stdout?.on('data', (chunk: string) => {
    buffer += chunk
    let nl: number
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trim()
      buffer = buffer.slice(nl + 1)
      if (!line) continue
      let msg: { id?: unknown; result?: unknown; error?: { message?: unknown } }
      try {
        msg = JSON.parse(line) as typeof msg
      } catch {
        continue
      }
      if (typeof msg.id !== 'number') continue
      const p = pending.get(msg.id)
      if (!p) continue
      pending.delete(msg.id)
      if (msg.error) p.reject(new HandsCheckError(typeof msg.error.message === 'string' ? msg.error.message : 'runtime error', stderr))
      else p.resolve(msg.result)
    }
  })
  const exited = new Promise<void>((resolve) => {
    child.once('exit', () => {
      failAll(new HandsCheckError(stderr.trim() ? `the runtime stopped: ${lastLine(stderr)}` : 'the runtime stopped', stderr))
      resolve()
    })
    // a command that cannot start never exits: `error` is all there is
    child.once('error', (error) => {
      failAll(new HandsCheckError(`could not start the runtime: ${error.message}`, stderr))
      resolve()
    })
  })
  child.stdin?.on('error', () => undefined)
  const timer = setTimeout(() => {
    failAll(new HandsCheckError('the runtime did not answer in time', stderr))
    killTree(child)
  }, timeoutMs)
  const request = (method: string, params: Record<string, unknown>): Promise<unknown> =>
    new Promise((resolve, reject) => {
      const id = nextId++
      pending.set(id, { resolve, reject })
      child.stdin?.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
    })
  const notify = (method: string, params: Record<string, unknown>): void => {
    child.stdin?.write(JSON.stringify({ jsonrpc: '2.0', method, params }) + '\n')
  }
  try {
    await request('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'nanomuse-hands-check', version: '1' } })
    notify('notifications/initialized', {})
    const call = async (tool: string, args: Record<string, unknown>): Promise<ToolReply> => {
      const result = (await request('tools/call', { name: tool, arguments: args })) as { content?: unknown; isError?: unknown }
      const content = Array.isArray(result.content) ? (result.content as Content[]) : []
      return { content, isError: result.isError === true }
    }
    return await body(call)
  } finally {
    clearTimeout(timer)
    try {
      child.stdin?.end()
    } catch {
      // already closed
    }
    const grace = setTimeout(() => killTree(child), 2000)
    await exited
    clearTimeout(grace)
  }
}

function lastLine(text: string): string {
  const lines = text
    .trim()
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
  return (lines[lines.length - 1] ?? '').slice(0, 300)
}

function textOf(reply: ToolReply): string {
  return reply.content
    .filter((c) => c.type === 'text' && typeof c.text === 'string')
    .map((c) => c.text as string)
    .join('\n')
}

export interface ScreenshotCheck {
  ok: boolean
  /** The capture came back all black: Screen Recording is missing for the app, or was granted after it started. */
  black: boolean
  /** A small JPEG/PNG as a data URL, when the capture worked. */
  thumbnail?: string
  width?: number
  height?: number
  title?: string
  /** Window mode (macOS): whether the hands can work inside one application's window, and the runtime's reason when not. */
  window?: { available: boolean; reason: string }
  error?: string
}

/** The runtime's reason in a `computer_target` note: `(…)` after the fixed wording. */
export function windowStatus(note: string): { available: boolean; reason: string } {
  const off = /Window mode is not available here \(([^)]*)\)/.exec(note)
  if (off) return { available: false, reason: off[1] ?? '' }
  const broke = /could not be worked in as a window \(([^)]*)\)/.exec(note)
  if (broke) return { available: true, reason: broke[1] ?? '' }
  if (/Working in the window of/.test(note)) return { available: true, reason: '' }
  return { available: false, reason: note.split('\n')[0]?.slice(0, 200) ?? '' }
}

/** Looks at the screen through the runtime: a thumbnail, or why not. Then asks for window mode, the way the agent would. */
export async function checkScreenshot(options: McpOptions): Promise<ScreenshotCheck> {
  try {
    return await withMcp(options, async (call) => {
      const reply = await call('computer_screen', {})
      const text = textOf(reply)
      if (reply.isError) return { ok: false, black: isBlack(text), error: text.slice(0, 500) }
      const image = reply.content.find((c) => c.type === 'image' && typeof c.data === 'string')
      const head = screenHead(text)
      const out: ScreenshotCheck = { ok: true, black: false }
      if (image?.data) out.thumbnail = `data:${image.mimeType ?? 'image/jpeg'};base64,${image.data}`
      if (head.width) out.width = head.width
      if (head.height) out.height = head.height
      if (head.title) out.title = head.title
      // window mode: the runtime says in its note whether it can, and why not (`hands.status.window.reason`)
      const target = await call('computer_act', { action: 'computer_target', app: 'Finder' }).catch(() => undefined)
      if (target) out.window = windowStatus(textOf(target))
      return out
    })
  } catch (error: unknown) {
    const text = error instanceof Error ? error.message : String(error)
    return { ok: false, black: isBlack(text), error: text }
  }
}

export interface MoveCheck {
  ok: boolean
  /** The move was refused for want of Accessibility (macOS) or a hands backend. */
  accessibility: boolean
  error?: string
}

/**
 * Moves the mouse 20 px to the right of the screen's centre and back. The tools do not say
 * where the pointer is, so the centre stands in for "where it was".
 */
export async function checkMove(options: McpOptions): Promise<MoveCheck> {
  try {
    return await withMcp(options, async (call) => {
      // the size of the screen, for a point that is surely on it
      const look = await call('computer_screen', {})
      const head = screenHead(textOf(look))
      const cx = head.width ? Math.floor(head.width / 2) : 400
      const cy = head.height ? Math.floor(head.height / 2) : 300
      const first = await call('computer_act', { action: 'move', x: cx + 20, y: cy })
      if (first.isError) {
        const text = textOf(first)
        return { ok: false, accessibility: needsAccessibility(text), error: text.slice(0, 500) }
      }
      const back = await call('computer_act', { action: 'move', x: cx, y: cy })
      if (back.isError) {
        const text = textOf(back)
        return { ok: false, accessibility: needsAccessibility(text), error: text.slice(0, 500) }
      }
      return { ok: true, accessibility: false }
    })
  } catch (error: unknown) {
    const text = error instanceof Error ? error.message : String(error)
    return { ok: false, accessibility: needsAccessibility(text), error: text }
  }
}

/** The runtime's own words for a black capture (`BLACK_SCREEN_HINT`) and the window layer's. */
export function isBlack(text: string): boolean {
  return /all black|came back black|came back empty|screen recording/i.test(text)
}

/** The hands could not act: no backend, or macOS has not trusted the app. */
export function needsAccessibility(text: string): boolean {
  return /accessibility|not trusted|no hands backend|hands.*(unavailable|not available)|AXIsProcessTrusted|CGEvent/i.test(text)
}
