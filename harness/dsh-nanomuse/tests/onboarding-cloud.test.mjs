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
        import { CloudChannelCard } from './src/client/OwnKey.tsx'
        import { en } from './src/client/locales.ts'
        export function render(signedIn) {
          return renderToStaticMarkup(h(CloudChannelCard, { t: key => en[key], signedIn, onSignIn() {}, onChoose() {} }))
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
