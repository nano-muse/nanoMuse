import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'

let dir, bundle
const fetchBefore = globalThis.fetch
const bridgeBefore = globalThis.nanomuseHarness

before(async () => {
  dir = await mkdtemp(join(tmpdir(), 'nm-helper-relaunch-'))
  await build({
    stdin: {
      contents: `
        import { createElement as h } from 'react'
        import { renderToStaticMarkup } from 'react-dom/server'
        import { RelaunchButton, relaunchHands } from './src/client/RelaunchButton.tsx'
        export { relaunchHands }
        export { en, zh } from './src/client/locales.ts'
        export function render(t, label) { return renderToStaticMarkup(h(RelaunchButton, { t, label, relaunch: relaunchHands })) }
      `,
      resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'js',
    },
    outfile: join(dir, 'relaunch.mjs'), format: 'esm', platform: 'node', target: 'node22',
    bundle: true, logLevel: 'silent', define: { 'process.env.NODE_ENV': '"production"' },
    banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
  })
  bundle = await import(pathToFileURL(join(dir, 'relaunch.mjs')).href)
})

after(async () => {
  globalThis.fetch = fetchBefore
  if (bridgeBefore === undefined) delete globalThis.nanomuseHarness
  else globalThis.nanomuseHarness = bridgeBefore
  if (dir) await rm(dir, { recursive: true, force: true })
})

function desktop(relaunch) {
  globalThis.nanomuseHarness = { permissions: async () => ({}), relaunch }
  const clears = []
  globalThis.fetch = async (url, options) => {
    clears.push({ url, method: options.method })
    return new Response(null, { status: 204 })
  }
  return clears
}

test('the black-screen notice stays until the shell confirms the restart', async () => {
  let finish
  const pending = new Promise((resolve) => { finish = resolve })
  const clears = desktop(() => pending)
  const result = bundle.relaunchHands()
  await Promise.resolve()
  assert.deepEqual(clears, [])
  finish(true)
  assert.equal(await result, true)
  assert.deepEqual(clears, [{ url: 'nanomuse/cloud/hands/black-screen/clear', method: 'POST' }])
})

test('failed, unavailable and older shell restarts do not clear the notice', async () => {
  for (const answer of [false, undefined]) {
    const clears = desktop(async () => answer)
    assert.equal(await bundle.relaunchHands(), answer)
    assert.deepEqual(clears, [])
  }
  const clears = desktop(async () => { throw new Error('no port after 10 s') })
  await assert.rejects(bundle.relaunchHands(), /no port after 10 s/)
  assert.deepEqual(clears, [])
  delete globalThis.nanomuseHarness
  assert.equal(await bundle.relaunchHands(), false)
})

test('restart controls have English and Chinese labels with failure feedback strings', () => {
  for (const locale of ['en', 'zh']) {
    const words = bundle[locale]
    const html = bundle.render((key) => words[key], words.pmBlackRelaunchHelper)
    assert.ok(html.includes(words.pmBlackRelaunchHelper))
    assert.ok(words.pmRelaunchRunning)
    assert.ok(words.pmRelaunchFailed)
    assert.ok(words.pmRelaunchFailedReason.includes('{error}'))
  }
})
