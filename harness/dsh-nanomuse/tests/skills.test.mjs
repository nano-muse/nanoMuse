import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import { Readable } from 'node:stream'
import { pathToFileURL } from 'node:url'
import { Context } from '@deepseek-ai/cordis'
import SkillRegistry from '@deepseek-ai/dsh-skill'
import { NanoMuseSkills, catalogForSession, skillsHandler } from '../lib/skills.js'
import { SkillPreferences, skillWorkspace } from '../lib/skills-policy.js'

const require = createRequire(import.meta.url)
const { createScope } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-scope', { paths: [require.resolve('@deepseek-ai/dsh-skill')] })).href)

async function fixture(t, writer) {
  const directory = await mkdtemp(join(tmpdir(), 'nanomuse-skills-'))
  const preferences = new SkillPreferences(join(directory, 'skills.json'), writer)
  await preferences.load()
  const ctx = new Context()
  await ctx.plugin({ apply: (host) => { new NanoMuseSkills(host, preferences) } })
  t.after(async () => { await ctx.fiber.dispose(); await rm(directory, { recursive: true, force: true }) })
  return { directory, preferences, ctx, registry: ctx.skills }
}

function provider(name, skill = 'shared-skill', rank = 100, body = async () => 'Synthetic skill body') {
  const summary = { name: skill, description: 'Synthetic routing description', source: 'custom', provider: name, invocation: { modelInvocable: true, userInvocable: true } }
  return { name, async list() { return [{ ...summary, rank, locator: skill }] }, async get() { return { ...summary, content: await body() } } }
}

test('global disable covers list/snapshot/get, runtime and same-name fallback without changing shared files', async (t) => {
  const { directory, preferences, ctx, registry } = await fixture(t)
  const shared = join(directory, 'SKILL.md')
  await writeFile(shared, 'Unchanged shared instructions')
  const winning = ctx.skills.registerProvider(() => provider('project-provider', 'shared-skill', 1, () => readFile(shared, 'utf8')))
  ctx.skills.registerProvider(() => provider('user-provider', 'shared-skill', 200))
  ctx.skills.register({ name: 'runtime-skill', description: 'Runtime', source: 'runtime', content: 'Synthetic runtime body' })
  assert.equal((await registry.get('shared-skill')).content, 'Unchanged shared instructions')
  assert.equal((await registry.snapshot()).skills.length, 2)
  await preferences.update({ name: 'shared-skill', scope: 'global', disabled: true })
  await preferences.update({ name: 'runtime-skill', scope: 'global', disabled: true })
  assert.deepEqual(await registry.list(), [])
  assert.deepEqual((await registry.snapshot()).skills, [])
  assert.equal(await registry.get('shared-skill'), undefined)
  assert.equal(await registry.get('runtime-skill'), undefined)
  await winning()
  assert.equal(await registry.get('shared-skill'), undefined)
  const catalog = await registry.managementCatalog()
  assert.equal(catalog.skills.length, 2)
  assert.ok(catalog.skills.every((item) => !item.enabled && item.globalDisabled))
  await preferences.update({ name: 'shared-skill', scope: 'global', disabled: false })
  assert.equal((await registry.get('shared-skill')).provider, 'user-provider')
  assert.equal(await readFile(shared, 'utf8'), 'Unchanged shared instructions')
})

test('workspace aliases and Git subdirectories share a rule; unrelated and absent cwd do not', async (t) => {
  const { directory, preferences, ctx, registry } = await fixture(t)
  const project = join(directory, 'project'), child = join(project, 'child'), other = join(directory, 'other'), alias = join(directory, 'alias')
  await mkdir(child, { recursive: true }); await mkdir(join(project, '.git')); await mkdir(other)
  await symlink(project, alias, process.platform === 'win32' ? 'junction' : 'dir')
  ctx.skills.registerProvider(() => provider('filesystem'))
  assert.equal(await skillWorkspace(join(alias, 'child')), await skillWorkspace(project))
  await preferences.update({ name: 'shared-skill', scope: 'workspace', workspace: child, disabled: true })
  for (const cwd of [project, child, alias]) {
    assert.equal(await registry.get('shared-skill', { cwd }), undefined)
    assert.deepEqual(await registry.list({ cwd }), [])
  }
  assert.ok(await registry.get('shared-skill', { cwd: other }))
  assert.ok(await registry.get('shared-skill'))
  await preferences.update({ name: 'shared-skill', scope: 'global', disabled: true })
  await preferences.update({ name: 'shared-skill', scope: 'workspace', workspace: child, disabled: false })
  assert.equal(await registry.get('shared-skill', { cwd: child }), undefined)
  assert.equal(await registry.get('shared-skill'), undefined)
  assert.equal(await registry.get('shared-skill', { cwd: other }), undefined)
})

test('scoped preset providers and newly registered providers are governed by the same preferences', async (t) => {
  const { preferences, ctx, registry } = await fixture(t)
  const scope = {}, other = {}, mount = createScope(ctx, scope)
  t.after(() => mount.dispose())
  await mount.ctx.plugin({ inject: ['skills'], apply(host) { host.skills.registerProvider(() => provider('preset-provider')) } })
  assert.deepEqual(await registry.list({ scope: other }), [])
  assert.equal((await registry.list({ scope })).length, 1)
  await preferences.update({ name: 'shared-skill', scope: 'global', disabled: true })
  assert.deepEqual(await registry.list({ scope }), [])
  assert.equal(await registry.get('shared-skill', { scope }), undefined)
  ctx.skills.registerProvider(() => provider('late-provider', 'shared-skill'))
  assert.equal(await registry.get('shared-skill', { scope }), undefined)
})

test('disabling during discovery prevents provider body loading', async (t) => {
  const { preferences, ctx, registry } = await fixture(t)
  let release, enter, loads = 0
  const entered = new Promise((r) => { enter = r }), gate = new Promise((r) => { release = r })
  const source = provider('delayed-provider', 'shared-skill', 1, async () => { loads++; return 'Must not load' })
  const list = source.list
  source.list = async () => { enter(); await gate; return list() }
  ctx.skills.registerProvider(() => source)
  const pending = registry.get('shared-skill')
  await entered
  await preferences.update({ name: 'shared-skill', scope: 'global', disabled: true })
  release()
  assert.equal(await pending, undefined)
  assert.equal(loads, 0)
})

test('disabling during body loading prevents the completed body from escaping', async (t) => {
  const { preferences, ctx, registry } = await fixture(t)
  let release, enter
  const entered = new Promise((r) => { enter = r }), gate = new Promise((r) => { release = r })
  ctx.skills.registerProvider(() => provider('delayed-provider', 'shared-skill', 1, async () => { enter(); await gate; return 'Must not escape' }))
  const pending = registry.get('shared-skill')
  await entered
  await preferences.update({ name: 'shared-skill', scope: 'global', disabled: true })
  release()
  assert.equal(await pending, undefined)
})

test('preferences invalidate warm provider catalogs and signal consumers', async (t) => {
  const { preferences, ctx, registry } = await fixture(t)
  let lists = 0, events = 0
  const source = provider('counted-provider'), list = source.list
  source.list = async () => { lists++; return list() }
  ctx.skills.registerProvider(() => source)
  ctx.on('skills/change', () => { events++ })
  await registry.list(); await registry.list()
  assert.equal(lists, 1)
  await preferences.update({ name: 'shared-skill', scope: 'global', disabled: true })
  assert.ok(events > 0)
  await registry.list()
  assert.equal(lists, 2)
})

test('corrupt, oversized and non-regular preferences fail closed and cannot be overwritten by toggles', async (t) => {
  for (const contents of ['not json', JSON.stringify({ version: 1, global: 'wrong', workspaces: {} }), ' '.repeat(1024 * 1024 + 1)]) {
    const { preferences, ctx, registry } = await fixture(t)
    await writeFile(preferences.path, contents)
    await preferences.load()
    ctx.skills.registerProvider(() => provider('filesystem'))
    assert.equal(preferences.error, 'skills_policy_unavailable')
    assert.deepEqual(await registry.list(), [])
    assert.equal(await registry.get('shared-skill'), undefined)
    assert.equal((await registry.managementCatalog()).policyError, 'skills_policy_unavailable')
    await assert.rejects(preferences.update({ name: 'shared-skill', scope: 'global', disabled: false }))
    assert.equal(await readFile(preferences.path, 'utf8'), contents)
  }
  const { preferences } = await fixture(t)
  await mkdir(preferences.path)
  await preferences.load()
  assert.equal(preferences.error, 'skills_policy_unavailable')
})

test('failed writes leave prior state unchanged and later concurrent updates retain every change', async (t) => {
  let fail = false
  const { directory, preferences, ctx, registry } = await fixture(t, async (path, data) => {
    if (fail) throw new Error('Synthetic private disk error')
    await writeFile(path, data)
  })
  ctx.skills.registerProvider(() => provider('filesystem'))
  await preferences.update({ name: 'shared-skill', scope: 'global', disabled: true })
  const before = await readFile(preferences.path, 'utf8')
  fail = true
  await assert.rejects(preferences.update({ name: 'shared-skill', scope: 'global', disabled: false }))
  assert.equal(await registry.get('shared-skill'), undefined)
  assert.equal(await readFile(preferences.path, 'utf8'), before)
  fail = false
  await Promise.all([
    preferences.update({ name: 'another-skill', scope: 'global', disabled: true }),
    preferences.update({ name: 'local-skill', scope: 'workspace', workspace: directory, disabled: true }),
  ])
  const restored = new SkillPreferences(preferences.path)
  await restored.load()
  assert.equal(restored.flags('shared-skill').enabled, false)
  assert.equal(restored.flags('another-skill').enabled, false)
  assert.equal(restored.flags('local-skill', await skillWorkspace(directory)).enabled, false)
})

test('updates cannot write beyond the startup reader collection limits', async (t) => {
  const { preferences, directory } = await fixture(t)
  const full = { version: 1, global: Array.from({ length: 10_000 }, (_, n) => `skill-${n}`), workspaces: {} }
  await writeFile(preferences.path, JSON.stringify(full))
  await preferences.load()
  await assert.rejects(preferences.update({ name: 'overflow', scope: 'global', disabled: true }), /skills_policy_limit/)
  assert.equal(preferences.flags('overflow').enabled, true)
  full.global = []
  full.workspaces = Object.fromEntries(Array.from({ length: 1000 }, (_, n) => [join(directory, `project-${n}`), ['shared-skill']]))
  await writeFile(preferences.path, JSON.stringify(full))
  await preferences.load()
  await assert.rejects(preferences.update({ name: 'shared-skill', scope: 'workspace', workspace: directory, disabled: true }), /skills_policy_limit/)
  assert.deepEqual(JSON.parse(await readFile(preferences.path, 'utf8')), full)
})

test('cancellation and unavailable workspaces never return an otherwise allowed skill', async (t) => {
  const { registry, ctx, directory } = await fixture(t)
  ctx.skills.registerProvider(() => provider('filesystem'))
  await assert.rejects(registry.get('shared-skill', { signal: AbortSignal.abort() }))
  await assert.rejects(registry.list({ signal: AbortSignal.abort() }))
  await assert.rejects(registry.get('shared-skill', { cwd: join(directory, 'missing') }))
  assert.equal((await registry.managementCatalog({ cwd: join(directory, 'missing') })).policyError, 'skills_workspace_unavailable')
})

test('management catalog leases the cold/default preset without starting an agent', async (t) => {
  const { directory, ctx, registry } = await fixture(t)
  const scope = {}, mount = createScope(ctx, scope)
  t.after(() => mount.dispose())
  await mount.ctx.plugin({ inject: ['skills'], apply(host) { host.skills.registerProvider(() => provider('preset-provider')) } })
  let released = 0, observed = 0, leases = 0
  const host = { get(name) {
    if (name === 'sessionQuery') return { async observeSession() { observed++; return { header: { cwd: directory }, projections: { values: { agentPreset: 'nanomuse' } }, [Symbol.dispose]() {} } } }
    if (name === 'agentPresets') return { async acquireScope() { leases++; return { key: scope, async [Symbol.asyncDispose]() { released++ } } } }
    if (name === 'agents') return { get: () => undefined }
  } }
  const initial = await catalogForSession(host, registry)
  assert.equal(initial.workspace, null)
  assert.equal(initial.complete, false)
  assert.equal(initial.managed, true)
  assert.equal(initial.skills.length, 1)
  const cold = await catalogForSession(host, registry, 'synthetic-session')
  assert.equal(cold.workspace, await skillWorkspace(directory))
  assert.equal(cold.complete, false)
  assert.equal(cold.managed, false)
  assert.equal(observed, 1)
  assert.equal(leases, 2)
  assert.equal(released, 2)
  assert.equal((await catalogForSession({ get: () => undefined }, registry)).complete, false)
})

test('a cold isolated preset cannot claim its session is managed through a root-registry lease', async (t) => {
  const { registry, directory } = await fixture(t)
  let resumed = 0
  const host = { get(name) {
    if (name === 'sessionQuery') return { async observeSession() { return { header: { cwd: directory }, projections: { values: { agentPreset: 'custom-isolated' } }, [Symbol.dispose]() {} } } }
    if (name === 'agentPresets') return { async acquireScope() { return { key: {}, async [Symbol.asyncDispose]() {} } }, serviceFor() { assert.fail('cold scope is not an Agent') } }
    if (name === 'agents') return { get: () => undefined }
    if (name === 'sessionController') return { resolveAgent() { resumed++; assert.fail('must not activate an Agent') } }
  } }
  const result = await catalogForSession(host, registry, 'synthetic-session')
  assert.equal(result.managed, false)
  assert.equal(result.complete, false)
  assert.equal(resumed, 0)
})

test('a live session is managed only after its actual preset service is resolved', async (t) => {
  const { registry, directory } = await fixture(t)
  const agent = {}
  let checked = 0
  const host = { get(name) {
    if (name === 'sessionQuery') return { async observeSession() { return { header: { cwd: directory }, [Symbol.dispose]() {} } } }
    if (name === 'agents') return { get: () => agent }
    if (name === 'agentPresets') return { serviceFor(actual, service) { assert.equal(actual, agent); assert.equal(service, 'skills'); checked++; return registry } }
  } }
  const result = await catalogForSession(host, registry, 'synthetic-session')
  assert.equal(result.managed, true)
  assert.equal(result.complete, true)
  assert.equal(checked, 1)
})

test('null preset projections select the default for both cold and live sessions', async (t) => {
  const { registry, directory } = await fixture(t)
  for (const live of [undefined, {}]) {
    const host = { get(name) {
      if (name === 'sessionQuery') return { async observeSession() { return { header: { cwd: directory }, projections: { values: { agentPreset: null } }, [Symbol.dispose]() {} } } }
      if (name === 'agents') return { get: () => live }
      if (name === 'agentPresets') return { serviceFor: () => registry, async acquireScope(preset) { assert.equal(preset, undefined); return { key: {}, async [Symbol.asyncDispose]() {} } } }
    } }
    const result = await catalogForSession(host, registry, 'synthetic-session')
    assert.equal(result.workspace, await skillWorkspace(directory))
    assert.equal(result.managed, live !== undefined)
  }
})

test('management refuses an unmanaged isolated registry', async (t) => {
  const { ctx, registry } = await fixture(t)
  const separate = new Context()
  await separate.plugin(SkillRegistry)
  t.after(() => separate.fiber.dispose())
  const host = { get(name) {
    if (name === 'sessionQuery') return { async observeSession() { return { header: {}, [Symbol.dispose]() {} } } }
    if (name === 'agents') return { get: () => ({}) }
    if (name === 'agentPresets') return { serviceFor: () => separate.skills }
  } }
  assert.equal((await catalogForSession(host, registry, 'synthetic-session')).managed, false)
  assert.ok(ctx.skills instanceof NanoMuseSkills)
})

test('management refuses another managed registry with a different preference owner', async (t) => {
  const { registry } = await fixture(t)
  const other = await fixture(t)
  const host = { get(name) {
    if (name === 'sessionQuery') return { async observeSession() { return { header: {}, [Symbol.dispose]() {} } } }
    if (name === 'agents') return { get: () => ({}) }
    if (name === 'agentPresets') return { serviceFor: () => other.registry }
  } }
  assert.equal((await catalogForSession(host, registry, 'synthetic-session')).managed, false)
})

async function request(handler, method, path, body, headers = {}) {
  const req = Readable.from(body === undefined ? [] : [Buffer.from(JSON.stringify(body))])
  Object.assign(req, { method, url: path, headers: { host: 'localhost', 'x-nanomuse': '1', ...headers } })
  const result = {}
  const res = { writeHead(status) { result.status = status; return res }, end(text) { result.body = text ? JSON.parse(text) : undefined; return res } }
  await handler(req, res)
  return result
}

test('host routes reject cross-origin writes and sanitize persistence failures', async (t) => {
  const { registry } = await fixture(t, async () => { throw new Error('/private/path with secret') })
  const handler = skillsHandler({ get: () => undefined }, registry)
  const body = { name: 'shared-skill', scope: 'global', disabled: true }
  const denied = await request(handler, 'POST', '/nanomuse/skills/toggle', body, { origin: 'https://example.invalid' })
  assert.equal(denied.status, 403)
  const failed = await request(handler, 'POST', '/nanomuse/skills/toggle', body)
  assert.equal(failed.status, 503)
  assert.equal(failed.body.error.code, 'skills_operation_failed')
  assert.doesNotMatch(JSON.stringify(failed.body), /private|secret/)
  assert.equal((await request(handler, 'POST', '/nanomuse/skills/toggle', { ...body, disabled: 'false' })).status, 400)
  assert.equal((await request(handler, 'POST', '/nanomuse/skills/toggle', body, { 'x-nanomuse': undefined })).status, 403)
})

test('workspace writes require a verified live registry and its actual canonical workspace', async (t) => {
  const { registry, directory, preferences } = await fixture(t)
  let live
  const host = { get(name) {
    if (name === 'sessionQuery') return { async observeSession() { return { header: { cwd: directory }, [Symbol.dispose]() {} } } }
    if (name === 'agents') return { get: () => live }
    if (name === 'agentPresets') return { async acquireScope() { return { key: {}, async [Symbol.asyncDispose]() {} } }, serviceFor: () => registry }
  } }
  const handler = skillsHandler(host, registry)
  const body = { name: 'shared-skill', scope: 'workspace', disabled: true, workspace: await skillWorkspace(directory) }
  assert.equal((await request(handler, 'POST', '/nanomuse/skills/toggle', body)).status, 400)
  const cold = await request(handler, 'POST', '/nanomuse/skills/toggle', { ...body, sessionId: 'synthetic-session' })
  assert.equal(cold.status, 503)
  assert.equal(cold.body.error.code, 'skills_scope_unavailable')
  assert.equal(preferences.flags(body.name, body.workspace).enabled, true)
  live = {}
  assert.equal((await request(handler, 'POST', '/nanomuse/skills/toggle', { ...body, sessionId: 'synthetic-session', workspace: join(directory, 'another') })).status, 503)
  assert.equal((await request(handler, 'POST', '/nanomuse/skills/toggle', { ...body, sessionId: 'synthetic-session' })).status, 200)
  assert.equal(preferences.flags(body.name, body.workspace).enabled, false)
})
