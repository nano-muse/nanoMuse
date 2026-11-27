import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'

let dir, render
before(async () => {
  dir = await mkdtemp(join(tmpdir(), 'nm-public-watch-ui-'))
  const file = join(dir, 'view.cjs')
  await build({
    stdin: {
      contents: [
        "import { createElement as h } from 'react'",
        "import { renderToStaticMarkup } from 'react-dom/server'",
        "import { PublicWatchRow } from './src/client/PublicWatchSettings.tsx'",
        "import { en } from './src/client/locales.ts'",
        "export const render = props => renderToStaticMarkup(h(PublicWatchRow, { t: k => en[k], ...props }))",
      ].join('\n'),
      resolveDir: fileURLToPath(new URL('..', import.meta.url)),
    },
    outfile: file, format: 'cjs', platform: 'node', bundle: true, logLevel: 'silent',
    define: { 'process.env.NODE_ENV': '"production"' },
    plugins: [{ name: 'host-primitives', setup(b) {
      b.onResolve({ filter: /^@deepseek-ai\/dsh-client-ui-primitives$/ },
        () => ({ path: 'modal', namespace: 'host' }))
      b.onLoad({ filter: /.*/, namespace: 'host' }, () => ({ contents: 'export const Modal = p => p.children' }))
    } }],
  })
  ;({ render } = (await import(pathToFileURL(file).href)).default)
})
after(async () => { if (dir) await rm(dir, { recursive: true, force: true }) })

const repo = { id: 'repo', kind: 'github_repo', target: 'example/project', status: 'suggested', origin: 'recurring' }

test('suggestions explain repeated references and stay dismissible when monitoring is off', () => {
  const html = render({ source: repo, off: true })
  assert.match(html, /separate messages/)
  assert.match(html, /Needs confirmation/)
  assert.match(html, /<button[^>]* disabled=""[^>]*>Follow source/)
  assert.match(html, /<button (?![^>]*disabled)[^>]*>Do not suggest again/)
})

test('a Scholar suggestion needs an identity, with only researcher or paper association available', () => {
  const html = render({ source: { ...repo, kind: 'scholar_profile', target: 'ABC123def456' }, linking: true })
  assert.match(html, /Open Scholar profile/)
  assert.match(html, /OpenAlex author ID or ORCID/)
  assert.match(html, /value="research_work"/)
  assert.doesNotMatch(html, /value="github_repo"|value="research_topic"/)
  assert.match(html, /<button[^>]*disabled=""[^>]*>Link and follow/)
})

test('a paused source can be resumed or removed and an unavailable source is visible', () => {
  const html = render({ source: { ...repo, status: 'paused', unavailable: true } })
  assert.match(html, />Resume</)
  assert.match(html, />Stop following</)
  assert.match(html, /last check could not read this source/)
  assert.doesNotMatch(html, />Follow source<|>Pause</)
})
