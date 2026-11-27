/** The desktop owns its local ledger. The bundled runtime supplies the same readers,
 * offline discovery, first-read baseline and preference transitions as the standalone app. */
import { execFile } from 'node:child_process'
import { createHash } from 'node:crypto'
import { cliSpawnCommand } from './coding-readers.ts'

export interface PublicChange { text: string; at: number; url: string }
export interface PublicRow {
  id: string; kind: string; target: string; label: string
  status: 'suggested' | 'paused' | 'active' | 'dismissed'
  origin?: string
  failures?: number; last_checked?: string; next?: number
  pending?: Record<string, PublicChange>
}
export interface PublicLedger { enabled?: boolean; generation?: string; share_public_updates?: boolean; share_generation?: string; watches?: Record<string, PublicRow> }
export interface DiscoveryInput { text: string; personal: boolean; turn: string; at: number }
export type WatchOperation = { op: 'edit'; edit: Record<string, unknown> } | { op: 'poll' | 'observe'; texts: DiscoveryInput[] }

export function watchView(state: PublicLedger, scope: string, epoch: string, canShare: boolean) {
  return {
    revision: createHash('sha256').update(JSON.stringify([scope, epoch, state.generation ?? ''])).digest('hex'),
    enabled: Boolean(scope && state.enabled !== false),
    can_share: canShare, share_public_updates: canShare && state.share_public_updates === true,
    watches: Object.values(state.watches ?? {}).filter(r => r.status !== 'dismissed')
      .map(({ id, kind, target, label, status, origin, last_checked, failures }) =>
        ({ id, kind, target, label, status, origin, last_checked: last_checked ?? null, unavailable: Boolean(failures) })),
  }
}

export function pendingChanges(state: PublicLedger, at: number) {
  const seen = new Set<string>()
  const fresh: Array<{ key: string; row: PublicRow; change: PublicChange }> = []
  for (const row of Object.values(state.watches ?? {})) {
    if (row.status !== 'active') continue
    for (const [key, change] of Object.entries(row.pending ?? {})) {
      if (!change.text || seen.has(key) || at - change.at * 1000 > 7 * 86_400_000 || change.at * 1000 > at) continue
      seen.add(key)
      fresh.push({ key, row, change })
    }
  }
  return fresh.sort((a, b) => b.change.at - a.change.at).slice(0, 24)
}

export function runWatchWorker(state: PublicLedger, operation: WatchOperation, signal: AbortSignal): Promise<PublicLedger> {
  const input = JSON.stringify({ version: 1, state, ...operation })
  const maxBuffer = 8 * 1024 * 1024
  if (Buffer.byteLength(input) > maxBuffer) return Promise.reject(new Error('Public watch data is too large.'))
  // The worker needs no connector credentials, model keys or operator tokens. Python
  // reads public sources anonymously and never opens the desktop or standalone profile.
  const env: NodeJS.ProcessEnv = {}
  for (const name of ['PATH', 'Path', 'HOME', 'USERPROFILE', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'VIRTUAL_ENV']) {
    if (process.env[name]) env[name] = process.env[name]
  }
  env.PYTHONUTF8 = '1'
  return new Promise((resolve, reject) => {
    const [command, args] = cliSpawnCommand(process.platform, process.env.NANOMUSE_PY || 'nanomuse', ['watch-stdio'])
    const child = execFile(command, args, {
      env, signal, timeout: 45_000, maxBuffer, encoding: 'utf8', windowsHide: true,
    }, (error, stdout) => {
      if (error) return reject(new Error('The public source reader is unavailable.'))
      try {
        const result = JSON.parse(stdout)
        if (result?.version !== 1 || !result.state || typeof result.state !== 'object' || Array.isArray(result.state)) {
          throw new Error('Invalid public source or watch choice.')
        }
        resolve(result.state as PublicLedger)
      } catch { reject(new Error('Invalid public source or watch choice.')) }
    })
    child.stdin?.on('error', () => { /* execFile reports early exits */ })
    child.stdin?.end(input)
  })
}
