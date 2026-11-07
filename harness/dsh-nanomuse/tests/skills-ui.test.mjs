import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'

let dir, bundle
before(async () => {
  dir = await mkdtemp(join(tmpdir(), 'nm-skills-ui-'))
  await build({
    stdin: {
      contents: `import { createElement as h } from 'react'
        import { renderToStaticMarkup } from 'react-dom/server'
        import { SkillsPanel, skillsFailure } from './src/client/Skills.tsx'
        import { en, zh } from './src/client/locales.ts'
        export function failure(code, language = 'en') {
          const words = language === 'zh' ? zh : en
          return skillsFailure(key => words[key], { code, message: 'private diagnostic details' })
        }
        export function render(props, language = 'en') {
          const words = language === 'zh' ? zh : en
          const t = (key, values = {}) => words[key].replace(/\\{(\\w+)\\}/g, (_, name) => String(values[name] ?? ''))
          return renderToStaticMarkup(h(SkillsPanel, {
            t, hasSession: true, scope: 'workspace', query: '', loading: false, saving: null, error: null,
            onScope() {}, onQuery() {}, onRefresh() {}, onToggle() {}, ...props,
          }))
        }`,
      resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'js',
    },
    outfile: join(dir, 'test.mjs'), format: 'esm', platform: 'node', bundle: true,
    logLevel: 'silent', define: { 'process.env.NODE_ENV': '"production"' },
    banner: { js: "import { createRequire as __nmCreateRequire } from 'node:module'; const require = __nmCreateRequire(import.meta.url);" },
  })
  bundle = await import(pathToFileURL(join(dir, 'test.mjs')).href)
})
after(async () => { if (dir) await rm(dir, { recursive: true, force: true }) })

function catalog(skill = {}, context = {}) {
  return {
    workspace: '/workspace/example', complete: true, managed: true,
    skills: [{ name: 'draft-notes', description: 'Prepare meeting notes.', source: 'project-agents', provider: 'filesystem', globalDisabled: false, workspaceDisabled: false, enabled: true, ...skill }],
    ...context,
  }
}
const control = (html) => html.match(/<button[^>]+role="switch"[^>]*>/)?.[0] ?? ''

test('global disabling blocks the workspace switch but can be changed globally', () => {
  const view = catalog({ globalDisabled: true, enabled: false })
  const local = bundle.render({ catalog: view })
  assert.match(control(local), /aria-checked="false"/)
  assert.match(control(local), /disabled/)
  assert.match(local, /Enable this skill in All workspaces/)
  const global = bundle.render({ catalog: view, scope: 'global' })
  assert.match(control(global), /aria-checked="false"/)
  assert.doesNotMatch(control(global), /disabled/)
})

test('a workspace disable stays visible when the global setting is enabled', () => {
  const view = catalog({ workspaceDisabled: true, enabled: false })
  const global = bundle.render({ catalog: view, scope: 'global' })
  assert.match(control(global), /aria-checked="true"/)
  assert.match(global, /Disabled in this workspace/)
  const local = bundle.render({ catalog: view })
  assert.match(control(local), /aria-checked="false"/)
  assert.doesNotMatch(control(local), /disabled/)
})

test('without a workspace the page exposes global scope only', () => {
  const html = bundle.render({ catalog: catalog({}, { workspace: null }), hasSession: false })
  assert.match(html, /<option value="global" selected/)
  assert.match(html, /<option value="workspace" disabled/)
  assert.match(control(html), /Allow draft-notes in all workspaces/)
  assert.match(html, /No chat is selected/)
})

test('failed policy reads, unsupported chats and unconfirmed changes cannot change availability', () => {
  for (const props of [
    { catalog: catalog({}, { policyError: 'private failure details' }) },
    { catalog: catalog({}, { managed: false }) },
    { catalog: catalog(), saving: 'draft-notes' },
    { catalog: catalog(), error: 'Could not save.' },
    { catalog: catalog(), loading: true },
  ]) {
    assert.match(control(bundle.render(props)), /disabled/)
  }
  const html = bundle.render({ catalog: catalog({}, { policyError: 'private failure details' }) })
  assert.match(html, /Availability could not be determined/)
  assert.doesNotMatch(html, /private failure details/)
})

test('disabled entries remain inspectable as escaped text without file or remote content links', () => {
  const html = bundle.render({ catalog: catalog({
    globalDisabled: true, enabled: false,
    description: '<img src="https://example.com/pixel" onerror="alert(1)">',
    path: '/workspace/example/.agents/skills/draft-notes/SKILL.md',
  }) })
  assert.match(html, /draft-notes/)
  assert.match(html, /&lt;img/)
  assert.match(html, /SKILL.md/)
  assert.doesNotMatch(html, /<img|<a\s|<iframe|<script/)
})

test('search keeps metadata filtering local and partial catalogs are clearly marked in both languages', () => {
  const view = catalog({}, { complete: false })
  assert.match(bundle.render({ catalog: view, query: 'meeting' }), /role="switch"/)
  assert.doesNotMatch(bundle.render({ catalog: view, query: 'absent' }), /role="switch"/)
  assert.match(bundle.render({ catalog: view }), /Some skills could not be listed/)
  assert.match(bundle.render({ catalog: view }, 'zh'), /部分技能未能列出/)
})


test('skill API failures use localized messages instead of provider diagnostics', () => {
  for (const code of ['skills_policy_unavailable', 'skills_workspace_unavailable', 'skills_policy_limit',
    'skills_session_unavailable', 'skills_scope_unavailable', 'skills_bad_request', 'skills_operation_failed']) {
    const en = bundle.failure(code)
    const zh = bundle.failure(code, 'zh')
    assert.notEqual(en, zh)
    assert.doesNotMatch(en + zh, /private diagnostic details/)
  }
})


test('a cold chat remains in workspace scope and can switch to global management', () => {
  const html = bundle.render({ catalog: catalog({}, { managed: false, complete: false, workspace: null, skills: [] }), hasSession: true })
  assert.match(html, /<option value="workspace" selected/)
  assert.doesNotMatch(html, /<option value="workspace" disabled/)
  assert.doesNotMatch(html, /role="switch"|No skills were found/)
  assert.match(html, /Use All workspaces/)
  const global = bundle.render({ catalog: catalog({}, { workspace: null, complete: false }), hasSession: true, scope: 'global' })
  assert.doesNotMatch(control(global), /disabled/)
  assert.match(global, /Global settings still apply by skill name/)
})
