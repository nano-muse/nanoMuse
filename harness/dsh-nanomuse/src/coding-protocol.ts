/** Protocol 2 pages expose recorded items, never arbitrary filesystem contents. */
import { isAbsolute, join, relative } from 'node:path'
import { HubError } from './hub.ts'
import { fingerprint, object, type Obj } from './coding-timeline.ts'

export const PROTOCOL_VERSION = 2
export const CAPABILITIES = {
  timeline: true, item: true, diff: true, watch: true, projects: true,
  stop_owned_run: true, control_external_run: false, approve: false, file: false,
}

export function page<T extends unknown[] | string>(values: T, args: Obj, fallback = 60): Obj {
  const version = fingerprint(values)
  const backward = args.tail === true
  let start = backward ? values.length : 0
  if (args.cursor) {
    let token: Obj
    try {
      token = object(JSON.parse(Buffer.from(String(args.cursor), 'base64url').toString('utf8')))
      if (!Number.isInteger(token.offset) || Number(token.offset) < 0 || Number(token.offset) > values.length) throw new Error()
      if (Boolean(token.tail) !== backward) throw new Error()
    } catch {
      throw new HubError('invalid_cursor', 'reload this content from the beginning')
    }
    if (token.version !== version) throw new HubError('stale_cursor', 'the content changed; reload it from the beginning')
    start = Number(token.offset)
  }
  const maximum = typeof values === 'string' ? 32768 : 200
  const number = Number(args.limit) || fallback
  const limit = Math.min(maximum, Math.max(1, Number.isFinite(number) ? Math.trunc(number) : fallback))
  const end = backward ? start : Math.min(values.length, start + limit)
  const begin = backward ? Math.max(0, start - limit) : start
  const offset = backward ? begin : end
  return {
    data: values.slice(begin, end), version, offset: begin, total: values.length,
    next_cursor: (backward ? begin > 0 : end < values.length) ? Buffer.from(JSON.stringify({ version, offset, tail: backward })).toString('base64url') : null,
  }
}

export function sessionMetadata(row: Obj, home: string): Obj {
  const workspace = String(row.workspace || '')
  const roots = [join(home, '.codex', 'threads'), join(home, 'Documents', 'Codex'), join(home, 'Documents', 'nanoMuse', 'Chats')]
  const rootless = !workspace || roots.some((root) => {
    const path = relative(root, workspace)
    return path === '' || (!path.startsWith('..') && !isAbsolute(path))
  })
  return { ...row, scope: rootless ? 'chats' : 'projects', project_id: rootless ? '' : fingerprint(workspace) }
}

export function preview(item: Obj): Obj {
  const { output, input, files, ...rest } = item
  const body = String(output || '')
  return {
    ...rest, text: String(item.text || '').slice(0, 8000), text_truncated: String(item.text || '').length > 8000,
    output_preview: body.slice(-2000), input_preview: String(input || '').slice(0, 2000),
    truncated: Boolean(item.truncated) || body.length > 2000,
    files: (Array.isArray(files) ? files : []).map(object).map((f, index) => {
      const { diff, ...metadata } = f
      return { ...metadata, diff_reference: diff ? `${String(item.id)}:${index}` : null }
    }),
  }
}
