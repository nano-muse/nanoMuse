/**
 * Structured coding history, identical to nanomuse/coding/timeline.py.
 * apply_patch conversion adapted from Remodex's apply-patch-changes.js,
 * Copyright 2025-2026 Emanuele Di Pietro, Apache-2.0. nanoMuse modifications:
 * provider-neutral records, unknown counts, bounded output and stable identities.
 */
import { createHash } from 'node:crypto'

export type Obj = Record<string, unknown>
export interface TimelineItem extends Obj {
  id: string
  turn_id: string
  sequence: number
  revision: number
  role: string
  kind: string
  text: string
  status: string
}
export const TEXT_LIMIT = 262_144
export const object = (value: unknown): Obj => value && typeof value === 'object' && !Array.isArray(value) ? value as Obj : {}
export function contentText(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(object).filter((v) => v.text && ['text', 'input_text', 'output_text'].includes(String(v.type))).map((v) => String(v.text)).join('\n')
  return ''
}
export function argumentsOf(value: unknown): Obj {
  if (typeof value === 'string') {
    try { return object(JSON.parse(value)) } catch { return { raw: value } }
  }
  return object(value)
}
export function fingerprint(value: unknown): string {
  const canonical = (v: unknown): unknown => Array.isArray(v) ? v.map(canonical) : v && typeof v === 'object'
    ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, canonical((v as Obj)[k])])) : v
  return createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex').slice(0, 24)
}
export function patchFiles(patch: string): Obj[] {
  const files: Obj[] = []
  let current: Obj = {}
  let body: string[] = []
  const flush = () => {
    if (!current.path) return
    current.diff = body.join('\n')
    if (current.action !== 'delete') {
      current.additions = body.filter((l) => l.startsWith('+')).length
      current.deletions = body.filter((l) => l.startsWith('-')).length
    }
    files.push({ ...current })
  }
  for (const line of patch.split(/\r?\n/)) {
    const match = /^\*\*\* (Add|Update|Delete) File: (.+)$/.exec(line)
    if (match) {
      flush()
      current = { path: match[2], action: ({ Add: 'add', Update: 'edit', Delete: 'delete' } as Record<string, string>)[match[1]!] }
      body = []
    } else if (line.startsWith('*** Move to: ') && current.path) {
      current.old_path = current.path
      current.path = line.slice(13)
      current.action = 'rename'
    } else if (line === '*** End Patch') break
    else if (!line.startsWith('***') && current.path) body.push(line)
  }
  // split() includes a trailing empty line, unlike Python splitlines().
  if (body.at(-1) === '') body.pop()
  flush()
  return files
}
export class Timeline {
  readonly items = new Map<string, TimelineItem>()
  turn = ''
  index = 0
  constructor(private readonly clean: (text: string) => string = (s) => s.trim()) {}

  put(key: string, fields: Obj): TimelineItem {
    const item = this.items.get(key) ?? { id: key, turn_id: this.turn, sequence: this.index, revision: 0, role: 'system', kind: 'tool', text: '', status: 'completed' }
    Object.assign(item, fields)
    item.revision += 1
    this.items.set(key, item)
    return item
  }
  message(role: string, content: unknown, key: string): void {
    const raw = contentText(content)
    const value = role === 'user' ? this.clean(raw) : raw.trim()
    if (!value || (role === 'user' && value.startsWith('<'))) return
    if (role === 'user') this.turn = key
    this.put(key, { role, kind: 'message', text: value.slice(0, TEXT_LIMIT) })
  }
  call(key: string, name: string, raw: unknown, status = 'running'): void {
    const args = argumentsOf(raw)
    const command = args.command || args.cmd
    const fields: Obj = { kind: command ? 'command' : 'tool', text: name, name, input: JSON.stringify(args).slice(0, TEXT_LIMIT), status }
    if (command) fields.command = { display_command: typeof command === 'string' ? command : JSON.stringify(command), cwd: String(args.workdir || args.cwd || '') }
    const patch = typeof raw === 'string' && raw.trimStart().startsWith('*** Begin Patch') && name.endsWith('apply_patch') ? raw : args.patch
    if (typeof patch === 'string') {
      const files = patchFiles(patch)
      if (files.length) Object.assign(fields, { kind: 'file_change', files, diff_scope: 'item' })
    }
    if ((name === 'Edit' || name === 'Write') && args.file_path) {
      const old = args.old_string
      const next = name === 'Edit' ? args.new_string : args.content
      const lines = (value: string) => value === '' ? [] : value.replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n')
      if (typeof next === 'string') {
        const body = ['@@', ...(typeof old === 'string' ? lines(old).map((s) => `-${s}`) : []), ...lines(next).map((s) => `+${s}`)]
        const file: Obj = { path: args.file_path, action: 'edit', diff: body.join('\n') }
        if (typeof old === 'string' && !args.replace_all) Object.assign(file, { additions: lines(next).length, deletions: lines(old).length })
        Object.assign(fields, { kind: 'file_change', files: [file], diff_scope: 'item' })
      }
    }
    this.put(key, fields)
  }
  result(key: string, raw: unknown, failed = false): void {
    const output = contentText(raw) || (raw == null ? '' : JSON.stringify(raw))
    const item = this.put(key, { output: output.slice(0, TEXT_LIMIT), status: failed ? 'failed' : 'completed', truncated: output.length > TEXT_LIMIT })
    const metadata = argumentsOf(raw)
    if (item.command) {
      const command = object(item.command)
      for (const field of ['exit_code', 'duration_ms']) if (typeof metadata[field] === 'number') command[field] = metadata[field]
      const exit = /Process exited with code (-?\d+)/.exec(output)
      const duration = /Wall time: ([\d.]+) seconds/.exec(output)
      if (exit) command.exit_code = Number(exit[1])
      if (duration) command.duration_ms = Math.round(Number(duration[1]) * 1000)
      if (typeof command.exit_code === 'number' && command.exit_code !== 0) item.status = 'failed'
    }
  }
  feed(agent: string, row: Obj): void {
    this.index += 1
    const kind = String(row.type || '')
    const payload = object(row.payload)
    const fallback = `line-${this.index}`
    if (kind === 'turn_context' || kind === 'event_msg') {
      if (payload.turn_id) this.turn = String(payload.turn_id)
      if (payload.type === 'task_complete' || payload.type === 'turn_aborted') this.turn = ''
    }
    if (agent === 'codex' && kind === 'response_item') {
      const key = String(payload.call_id || payload.id || fallback)
      const type = payload.type
      if (type === 'message' && (payload.role === 'user' || payload.role === 'assistant')) this.message(payload.role, payload.content, key)
      else if (type === 'function_call' || type === 'custom_tool_call') this.call(key, String(payload.name || 'tool'), payload.arguments ?? payload.input)
      else if (type === 'function_call_output' || type === 'custom_tool_call_output') this.result(key, payload.output)
      return
    }
    if (agent === 'codex' && kind.startsWith('item.')) {
      const item = object(row.item)
      const key = String(item.id || fallback)
      const phase = kind !== 'item.completed' ? 'running' : String(item.status || 'completed')
      if (item.type === 'agent_message') this.message('assistant', item.text, key)
      else if (item.type === 'command_execution') {
        this.call(key, 'command', { command: item.command, cwd: item.cwd }, phase)
        if ('aggregated_output' in item) {
          this.result(key, item.aggregated_output)
          this.items.get(key)!.status = phase
        }
        const command = object(this.items.get(key)!.command)
        for (const field of ['exit_code', 'duration_ms']) if (typeof item[field] === 'number') command[field] = item[field]
        if (typeof item.exit_code === 'number' && item.exit_code !== 0) this.items.get(key)!.status = 'failed'
      } else if (item.type === 'file_change') {
        const files = Array.isArray(item.changes) ? item.changes.map(object).map((f) => ({ ...f, action: f.kind || 'edit' })) : []
        this.put(key, { kind: 'file_change', files, diff_scope: 'item', status: phase })
      } else if (item.type === 'mcp_tool_call' || item.type === 'web_search') {
        this.call(key, String(item.tool || item.type), item.arguments ?? item, phase)
        if (item.result != null) this.result(key, item.result, Boolean(item.error))
      }
      return
    }
    if ((agent === 'claude' || agent === 'cursor') && (row.role === 'user' || row.role === 'assistant' || kind === 'user' || kind === 'assistant')) {
      if (row.isMeta) return
      if (agent === 'cursor' && row.timestamp_ms != null) return
      const role = String(row.role || kind)
      const msg = object(row.message)
      const key = String(row.uuid || msg.id || fallback)
      this.message(role, msg.content, key)
      for (const [i, block] of (Array.isArray(msg.content) ? msg.content : []).entries()) {
        const b = object(block)
        const id = String(b.id || b.tool_use_id || `${key}-${i}`)
        if (b.type === 'tool_use') this.call(id, String(b.name || 'tool'), b.input)
        else if (b.type === 'tool_result') this.result(id, b.content, Boolean(b.is_error))
      }
      return
    }
    if (agent === 'cursor' && kind === 'tool_call') {
      const call = object(row.tool_call)
      const name = Object.keys(call)[0] || 'tool'
      const value = object(call[name])
      let key = String(row.call_id || row.id || value.id || fallback)
      if (key === fallback && row.subtype === 'completed') key = this.values().reverse().find((i) => i.name === name && i.status === 'running')?.id ?? key
      this.call(key, name, value.args ?? value)
      if (row.subtype === 'completed') this.result(key, value.result)
      return
    }
    if (agent === 'dsh') {
      const data = Object.keys(object(row.data)).length ? object(row.data) : row
      const key = String(data.id || data.callId || fallback)
      if (kind === 'user/message' && object(data.source).kind === 'user') this.message('user', data.content, key)
      else if (kind === 'assistant/message') this.message('assistant', object(data.message).content, key)
      else if (kind === 'tool/call') this.call(key, String(data.name || data.tool || 'tool'), data.arguments ?? data.args)
      else if (kind === 'tool/result') this.result(key, data.result ?? data.output, data.status === 'failed')
      else if (kind === 'tool' || kind === 'tool_call') this.call(key, String(row.tool || row.name || 'tool'), row.input)
      else if (kind === 'tool_result') this.result(key, row.result ?? row.output, row.status === 'failed')
      else if (kind === 'text') this.message('assistant', row.text, fallback)
    }
  }
  values(): TimelineItem[] { return [...this.items.values()] }
}
export function history(agent: string, rows: Obj[], clean: (text: string) => string): TimelineItem[] {
  const timeline = new Timeline(clean)
  for (const row of rows) timeline.feed(agent, row)
  return timeline.values()
}
