/** Filter the public skill registry, covering every provider and runtime contribution. */
import type { Context } from '@deepseek-ai/cordis'
import type { Agent } from '@deepseek-ai/dsh-agent'
import { resolveDshHome } from '@deepseek-ai/dsh-home-paths'
import SkillRegistry, { type Config as RegistryConfig, type SkillViewOptions, type SkillSummary, type SkillProvider, type SkillProviderControl } from '@deepseek-ai/dsh-skill'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { join } from 'node:path'
import { mountGuarded } from './admit.ts'
import { json, sameOrigin, send } from './cloud.ts'
import { SkillPreferences, skillWorkspace, type SkillFlags, type SkillPreferenceChange } from './skills-policy.ts'
import { RelayError } from './relay.ts'

export const name = 'nanomuse-skills'
export const Config = SkillRegistry.Config
export const SKILLS_PREFIX = '/nanomuse/skills'
export interface ManagedSkill extends SkillFlags { name: string; description: string; source: string; provider: string; path?: string }
export interface SkillsCatalog { workspace: string | null; complete: boolean; managed: boolean; policyError?: string; skills: ManagedSkill[] }

export class NanoMuseSkills extends SkillRegistry {
  constructor(ctx: Context, readonly preferences: SkillPreferences, config: RegistryConfig = {}) {
    super(ctx, config)
    // This public provider lifecycle supplies invalidation without reaching into registry internals.
    this.registerProvider((control) => {
      ctx.effect(() => preferences.subscribe(control.invalidate), 'nanoMuse skill preferences')
      return { name: 'nanomuse-policy-revision', async list() { return [] }, async get() { return undefined } }
    })
  }

  override registerProvider(create: (control: SkillProviderControl) => SkillProvider): () => void {
    return super.registerProvider((control) => {
      const provider = create(control)
      return {
        name: provider.name,
        list: (options) => provider.list(options),
        get: async (candidate, options) => {
          const workspace = await this.workspace(options)
          if (!this.preferences.flags(candidate.name, workspace).enabled) return undefined
          const definition = await provider.get(candidate, options)
          options.signal?.throwIfAborted()
          return this.preferences.flags(candidate.name, workspace).enabled ? definition : undefined
        },
      }
    })
  }

  private async workspace(options: SkillViewOptions): Promise<string | undefined> {
    options.signal?.throwIfAborted()
    const workspace = options.cwd === undefined ? undefined : await skillWorkspace(options.cwd)
    options.signal?.throwIfAborted()
    return workspace
  }

  override async list(options: SkillViewOptions = {}): Promise<SkillSummary[]> {
    return (await this.snapshot(options)).skills
  }

  override async snapshot(options: SkillViewOptions = {}) {
    const workspace = await this.workspace(options)
    if (this.preferences.error) return { skills: [], complete: true }
    const result = await super.snapshot(options)
    options.signal?.throwIfAborted()
    return { ...result, skills: result.skills.filter((skill) => this.preferences.flags(skill.name, workspace).enabled) }
  }

  override async get(skill: string, options: SkillViewOptions = {}) {
    const workspace = await this.workspace(options)
    if (!this.preferences.flags(skill, workspace).enabled) return undefined
    const definition = await super.get(skill, options)
    options.signal?.throwIfAborted()
    // A settings write may complete during provider discovery or body loading.
    return this.preferences.flags(skill, workspace).enabled ? definition : undefined
  }

  /** Metadata for the person's settings page; never used by agent discovery or loaders. */
  async managementCatalog(options: SkillViewOptions = {}): Promise<SkillsCatalog> {
    let workspace: string | undefined
    try { workspace = await this.workspace(options) } catch {
      return { workspace: null, complete: false, managed: true, policyError: 'skills_workspace_unavailable', skills: [] }
    }
    const result = await super.snapshot(options)
    return {
      workspace: workspace ?? null, complete: result.complete, managed: true,
      ...(this.preferences.error ? { policyError: this.preferences.error } : {}),
      skills: result.skills.map((skill) => ({
        name: skill.name, description: skill.description, source: skill.source, provider: skill.provider,
        ...(skill.path === undefined ? {} : { path: skill.path }), ...this.preferences.flags(skill.name, workspace),
      })),
    }
  }
}

interface Observation { header: { cwd?: string }; projections?: { values: { agentPreset?: unknown } }; [Symbol.dispose](): void }
interface ScopeLease { key: NonNullable<SkillViewOptions['scope']>; [Symbol.asyncDispose](): Promise<void> }
interface Presets {
  acquireScope(preset?: string): Promise<ScopeLease>
  serviceFor(agent: Pick<Agent, 'ctx'>, service: 'skills'): SkillRegistry | undefined
}

/** Like the native catalog endpoint, inspect cold sessions without activating an Agent. */
export async function catalogForSession(ctx: Context, registry: NanoMuseSkills, sessionId?: string): Promise<SkillsCatalog> {
  let cwd: string | undefined
  let preset: string | undefined
  let live: Agent | undefined
  if (sessionId !== undefined) {
    const query = ctx.get('sessionQuery') as { observeSession(id: string): Promise<Observation> } | undefined
    if (!query) throw new Error('skills_session_unavailable')
    const observation = await query.observeSession(sessionId)
    try {
      cwd = observation.header.cwd
      const declared = observation.projections?.values.agentPreset
      if (declared != null && typeof declared !== 'string') throw new Error('skills_session_unavailable')
      preset = typeof declared === 'string' ? declared : undefined
    } finally { observation[Symbol.dispose]() }
    live = (ctx.get('agents') as { get(id: string): Agent | undefined } | undefined)?.get(sessionId)
  }
  const presets = ctx.get('agentPresets') as Presets | undefined
  let lease: ScopeLease | undefined
  try {
    if (!live && presets) {
      try { lease = await presets.acquireScope(preset) } catch { /* report an incomplete catalog */ }
    }
    const selected = (live ? presets?.serviceFor(live, 'skills') : undefined) ?? registry
    if (!(selected instanceof NanoMuseSkills) || selected.preferences !== registry.preferences) return { workspace: null, complete: false, managed: false, skills: [] }
    const scope = live ?? lease?.key
    const catalog = await selected.managementCatalog({ ...(cwd === undefined ? {} : { cwd }), ...(scope === undefined ? {} : { scope }) })
    // A cold lease identifies registry layers, not an isolated service instance. The SDK
    // only exposes serviceFor for live Agents, so never claim to govern a cold preset.
    const verifiedLive = live !== undefined && presets !== undefined
    return { ...catalog, managed: sessionId === undefined || verifiedLive, complete: catalog.complete && verifiedLive }
  } finally { await lease?.[Symbol.asyncDispose]() }
}

export function skillsHandler(ctx: Context, registry: NanoMuseSkills) {
  return async (req: IncomingMessage, res: ServerResponse): Promise<void> => {
    if (!sameOrigin(req)) { send(res, 403, { error: { code: 'forbidden', message: 'Request not allowed' } }); return }
    const url = new URL(req.url ?? '/', 'http://127.0.0.1')
    try {
      if (req.method === 'GET' && url.pathname === `${SKILLS_PREFIX}/catalog`) {
        const sessionId = url.searchParams.get('sessionId') || undefined
        if (sessionId && sessionId.length > 200) throw new Error('skills_bad_request')
        send(res, 200, await catalogForSession(ctx, registry, sessionId))
        return
      }
      if (req.method === 'POST' && url.pathname === `${SKILLS_PREFIX}/toggle`) {
        if (req.headers['x-nanomuse'] !== '1') { send(res, 403, { error: { code: 'forbidden', message: 'Request not allowed' } }); return }
        const body = await json(req, 16 * 1024)
        if (typeof body.name !== 'string' || typeof body.disabled !== 'boolean' || (body.scope !== 'global' && body.scope !== 'workspace') || (body.workspace !== undefined && typeof body.workspace !== 'string')) throw new Error('skills_bad_request')
        if (body.scope === 'workspace') {
          if (typeof body.sessionId !== 'string' || !body.sessionId || body.sessionId.length > 200) throw new Error('skills_bad_request')
          const catalog = await catalogForSession(ctx, registry, body.sessionId)
          if (!catalog.managed) throw new Error('skills_scope_unavailable')
          if (catalog.workspace === null || body.workspace !== catalog.workspace) throw new Error('skills_workspace_unavailable')
        }
        await registry.preferences.update(body as SkillPreferenceChange)
        send(res, 200, { ok: true })
        return
      }
      send(res, 404, { error: { code: 'not_found', message: 'Not found' } })
    } catch (error) {
      if (error instanceof RelayError && (error.code === 'bad_json' || error.code === 'too_large')) {
        send(res, error.status, { error: { code: error.code, message: 'Invalid skill preferences request' } })
        return
      }
      const codes = new Set(['skills_bad_request', 'skills_workspace_unavailable', 'skills_policy_unavailable', 'skills_policy_limit', 'skills_session_unavailable', 'skills_scope_unavailable'])
      const code = error instanceof Error && codes.has(error.message) ? error.message : 'skills_operation_failed'
      send(res, code === 'skills_bad_request' ? 400 : 503, { error: { code, message: 'Skill preferences could not be read or saved' } })
    }
  }
}

/** Replace the base profile's `skill` service before any providers or consumers mount. */
export async function apply(ctx: Context, config: RegistryConfig = {}): Promise<void> {
  const preferences = new SkillPreferences(join(resolveDshHome(), 'nanomuse', 'skills.json'))
  await preferences.load()
  const registry = new NanoMuseSkills(ctx, preferences, config)
  mountGuarded(ctx, SKILLS_PREFIX, skillsHandler(ctx, registry), 'nanoMuse skill settings')
}
