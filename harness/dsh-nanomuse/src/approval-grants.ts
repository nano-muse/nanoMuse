import { createHash } from 'node:crypto'

export interface GrantTarget {
  version: 1
  tool: string
  resource: string
  action: string
}

/** The full main argument, for the preview and the legacy 1.0.6 grant key. */
export function mainArgument(args: string): string {
  let shown = args.trim()
  try {
    const parsed: unknown = JSON.parse(args)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const o = parsed as Record<string, unknown>
      const main = o.command ?? o.cmd ?? o.path ?? o.file_path ?? o.url ?? o.query ?? o.pattern ?? o.task ?? o.prompt
      const first = Object.values(o).find((value) => typeof value === 'string')
      shown = typeof main === 'string' ? main : typeof first === 'string' ? first : Object.keys(o).length ? JSON.stringify(o) : ''
    }
  } catch {
    // A model can ask while an argument is still raw text. Keep the complete text.
  }
  return shown.replace(/\s+/g, ' ').trim()
}

/** Compatibility for callers before structured grant targets. */
export function grantKey(name: string, args: string): string {
  const shown = mainArgument(args)
  return shown ? `${name}: ${shown}` : name
}

/** A stable, bounded identity for what a remembered answer would cover. */
export function grantTarget(name: string, args: string): GrantTarget {
  const parsed = parsedArguments(args)
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) delete (parsed as Record<string, unknown>).step
  const canonical = parsed === undefined ? args.trim() : stableJSON(parsed)
  const action = createHash('sha256').update(`${name}\0${canonical}`, 'utf8').digest('hex')
  return {
    version: 1,
    tool: name,
    resource: mainArgument(args),
    action: `sha256:${action}`,
  }
}

/** Only the current complete shape may create or select a remembered grant. */
export function parseGrantTarget(value: unknown): GrantTarget | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const target = value as Record<string, unknown>
  const tool = typeof target.tool === 'string' ? target.tool.trim() : ''
  const resource = target.resource
  const action = target.action
  if (target.version !== 1 || !tool || tool.length > 200) return undefined
  if (typeof resource !== 'string' || resource.length > 4096) return undefined
  if (typeof action !== 'string' || !/^sha256:[0-9a-f]{64}$/.test(action)) return undefined
  return { version: 1, tool, resource, action }
}

/**
 * The desktop card identity. A structured event is isolated by device, risk and chat; a
 * legacy event gets a one-card id only and therefore cannot select or create a standing grant.
 */
export function remoteApprovalCallId(
  baseCallId: string,
  deviceId: string,
  risk: string,
  sessionId: string,
  body: Record<string, unknown>,
): string {
  const target = parseGrantTarget(body.grant_target)
  if (!target) return `${baseCallId}:remote:${String(body.approval_id ?? '')}`
  const identity = stableJSON({
    approvalId: String(body.approval_id ?? ''),
    deviceId,
    risk,
    sessionId,
    target,
  })
  return `${baseCallId}:remote:${createHash('sha256').update(identity, 'utf8').digest('hex')}`
}

function parsedArguments(args: string): unknown | undefined {
  try {
    return JSON.parse(args) as unknown
  } catch {
    return undefined
  }
}

function stableJSON(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJSON).join(',')}]`
  if (value && typeof value === 'object') {
    const object = value as Record<string, unknown>
    return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${stableJSON(object[key])}`).join(',')}}`
  }
  return JSON.stringify(value) ?? 'null'
}
