/** nanoMuse-only skill preferences. Shared skill files are never changed. */
import { randomBytes } from 'node:crypto'
import { access, lstat, mkdir, open, readFile, realpath, rename, rm, stat } from 'node:fs/promises'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { isSkillName } from '@deepseek-ai/dsh-skill'

const MAX_BYTES = 1024 * 1024
interface Preferences { version: 1; global: string[]; workspaces: Record<string, string[]> }
export interface SkillFlags { globalDisabled: boolean; workspaceDisabled: boolean; enabled: boolean }
export type SkillPreferenceChange = { name: string; scope: 'global' | 'workspace'; disabled: boolean; workspace?: string }
type Writer = (path: string, data: string) => Promise<void>

/** Match the filesystem provider's nearest Git root, with aliases resolved first. */
export async function skillWorkspace(cwd: string): Promise<string> {
  if (!isAbsolute(cwd)) throw new Error('skills_workspace_unavailable')
  const canonical = await realpath(resolve(cwd))
  if (!(await stat(canonical)).isDirectory()) throw new Error('skills_workspace_unavailable')
  let current = canonical
  while (true) {
    try { await access(join(current, '.git')); return current } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw new Error('skills_workspace_unavailable')
    }
    const parent = dirname(current)
    if (parent === current) return canonical
    current = parent
  }
}

function parsePreferences(value: unknown): Preferences {
  const validNames = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 10_000 && v.every((name) => typeof name === 'string' && isSkillName(name))
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('skills_policy_unavailable')
  const row = value as Record<string, unknown>
  if (row.version !== 1 || !validNames(row.global) || !row.workspaces || typeof row.workspaces !== 'object' || Array.isArray(row.workspaces)) throw new Error('skills_policy_unavailable')
  const workspaces = Object.entries(row.workspaces)
  if (workspaces.length > 1000 || !workspaces.every(([path, names]) => isAbsolute(path) && validNames(names))) throw new Error('skills_policy_unavailable')
  return { version: 1, global: [...new Set(row.global)], workspaces: Object.fromEntries(workspaces.map(([path, names]) => [path, [...new Set(names as string[])]])) }
}

async function persist(path: string, data: string): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 })
  const temporary = `${path}.${randomBytes(12).toString('hex')}.tmp`
  try {
    const file = await open(temporary, 'wx', 0o600)
    try { await file.writeFile(data, 'utf8'); await file.sync() } finally { await file.close() }
    await rename(temporary, path)
  } finally { await rm(temporary, { force: true }).catch(() => undefined) }
}

export class SkillPreferences {
  private value: Preferences = { version: 1, global: [], workspaces: {} }
  private queue: Promise<void> = Promise.resolve()
  private listeners = new Set<() => void>()
  error: string | undefined

  constructor(readonly path: string, private readonly write: Writer = persist) {}

  async load(): Promise<void> {
    let found = false
    try {
      const info = await lstat(this.path)
      found = true
      if (!info.isFile() || info.size > MAX_BYTES) throw new Error('skills_policy_unavailable')
      const raw = await readFile(this.path, 'utf8')
      if (Buffer.byteLength(raw) > MAX_BYTES) throw new Error('skills_policy_unavailable')
      this.value = parsePreferences(JSON.parse(raw))
      this.error = undefined
    } catch (error) {
      // Only a missing preferences file means first run. An unreadable or corrupt file denies skills.
      this.error = !found && (error as NodeJS.ErrnoException).code === 'ENOENT' ? undefined : 'skills_policy_unavailable'
    }
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  flags(name: string, workspace?: string): SkillFlags {
    const globalDisabled = this.error !== undefined || this.value.global.includes(name)
    const workspaceDisabled = workspace !== undefined && (this.value.workspaces[workspace]?.includes(name) ?? false)
    return { globalDisabled, workspaceDisabled, enabled: !globalDisabled && !workspaceDisabled }
  }

  update(change: SkillPreferenceChange): Promise<void> {
    const operation = this.queue.then(async () => {
      if (this.error) throw new Error(this.error)
      if (!isSkillName(change.name) || typeof change.disabled !== 'boolean' || !['global', 'workspace'].includes(change.scope)) throw new Error('skills_bad_request')
      if (change.scope === 'workspace' && !change.workspace) throw new Error('skills_workspace_unavailable')
      const workspace = change.scope === 'workspace' ? await skillWorkspace(change.workspace!) : undefined
      const next = structuredClone(this.value)
      const before = workspace === undefined ? next.global : next.workspaces[workspace] ?? []
      const names = new Set(before)
      if (change.disabled) names.add(change.name)
      else names.delete(change.name)
      if (workspace === undefined) next.global = [...names].sort()
      else if (names.size) next.workspaces[workspace] = [...names].sort()
      else delete next.workspaces[workspace]
      // Never persist a state that the bounded startup reader would reject.
      try { parsePreferences(next) } catch { throw new Error('skills_policy_limit') }
      const encoded = `${JSON.stringify(next, null, 2)}\n`
      if (Buffer.byteLength(encoded) > MAX_BYTES) throw new Error('skills_policy_limit')
      await this.write(this.path, encoded)
      this.value = next
      // Listeners cannot turn a completed disk write into an apparent failure.
      for (const listener of this.listeners) { try { listener() } catch { /* isolated subscriber */ } }
    })
    this.queue = operation.catch(() => undefined)
    return operation
  }
}
