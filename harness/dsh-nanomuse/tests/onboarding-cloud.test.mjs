import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'

let dir, bundle
before(async () => {
  dir = await mkdtemp(join(tmpdir(), 'nm-onboarding-cloud-'))
  await build({
    stdin: {
      contents: `import { createElement as h } from 'react'
        import { renderToStaticMarkup } from 'react-dom/server'
        import { CloudChannelCard, WaysOnRows } from './src/client/OwnKey.tsx'
        import { en } from './src/client/locales.ts'
        import catalogue from './assets/providers.json'
        export { prefillEmptyComposer } from './src/client/composer.ts'
        export function render(signedIn) {
          return renderToStaticMarkup(h(CloudChannelCard, { t: key => en[key], signedIn, onSignIn() {}, onChoose() {} }))
        }
        export function renderProviders(groups) {
          const view = {
            region: 'global', catalogue: catalogue.providers, configured: [], capabilities: [],
            cloud: { signedIn: false, capabilities: [] },
            chatgpt: { signedIn: false, runtime: true, proxy: false, login: { status: 'idle' } },
            chat: {}, hands: {},
          }
          return renderToStaticMarkup(h(WaysOnRows, { t: key => en[key], view, groups, onChanged() {} }))
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

test('Cloud shows ready only when signed in', () => {
  const signedOut = bundle.render(false)
  assert.doesNotMatch(signedOut, /nm-channel-ready|nm-model-channel-ready-badge/)
  assert.match(signedOut, />Sign in</)
  const signedIn = bundle.render(true)
  assert.match(signedIn, /nm-model-channel-ready-badge/)
  assert.match(signedIn, />Use this</)
})

test('OpenAI API keys remain available alongside subscription sign-in and in the keys-only panel', () => {
  assert.match(bundle.renderProviders(undefined), />OpenAI</)
  assert.match(bundle.renderProviders(['first', 'rest', 'local', 'custom']), />OpenAI</)
})

test('first-run prefill waits for its chat and preserves drafts', (t) => {
  let target = false
  let text = 'old chat draft'
  let inserted = null
  const pending = []
  const editable = { get textContent() { return text }, focus() {} }
  t.mock.method(globalThis, 'setTimeout', (fn) => { pending.push(fn); return 1 })
  const previousWindow = globalThis.window
  const previousDocument = globalThis.document
  globalThis.window = { setTimeout: globalThis.setTimeout, getSelection: () => null }
  globalThis.document = {
    querySelector: () => editable,
    execCommand: (_command, _ui, value) => { inserted = value; return true },
  }
  t.after(() => { globalThis.window = previousWindow; globalThis.document = previousDocument })
  bundle.prefillEmptyComposer('selected task', () => target)
  assert.equal(inserted, null)
  assert.equal(pending.length, 1)
  target = true
  text = ''
  pending.shift()()
  assert.equal(inserted, 'selected task')
  inserted = null
  text = 'saved main chat draft'
  bundle.prefillEmptyComposer('another task', () => target)
  assert.equal(inserted, null)
  target = false
  bundle.prefillEmptyComposer('never navigated', () => target, 0)
  assert.equal(pending.length, 0)
})
