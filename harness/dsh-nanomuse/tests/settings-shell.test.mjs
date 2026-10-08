// The settings dialog's shell store: a link from one page to another remembers where it
// came from so the head can offer the way back; a pick in the sidebar, closing, or opening
// from outside the dialog starts fresh. Built from the TypeScript source with esbuild.
import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { build } from 'esbuild'

const here = fileURLToPath(new URL('.', import.meta.url))
let dir
let m

before(async () => {
  dir = await mkdtemp(join(tmpdir(), 'nm-settings-shell-'))
  await build({
    entryPoints: [join(here, '..', 'src', 'client', 'settings-shell.ts')],
    bundle: true,
    format: 'esm',
    platform: 'node',
    outfile: join(dir, 'settings-shell.mjs'),
    logLevel: 'silent',
  })
  m = await import(pathToFileURL(join(dir, 'settings-shell.mjs')).href)
})

after(async () => {
  await rm(dir, { recursive: true, force: true })
})

test('a link from one open page to another keeps the page it came from; back returns there once', () => {
  const store = m.createShellStore()
  assert.deepEqual(store.getSnapshot(), { open: false, activeId: undefined, from: undefined })
  store.openSection('nanomuse-models')
  // opened from outside the dialog (the chat, the rail): nothing to go back to
  assert.deepEqual(store.getSnapshot(), { open: true, activeId: 'nanomuse-models', from: undefined })
  store.openSection('nanomuse-cloud')
  assert.deepEqual(store.getSnapshot(), { open: true, activeId: 'nanomuse-cloud', from: 'nanomuse-models' })
  store.back()
  assert.deepEqual(store.getSnapshot(), { open: true, activeId: 'nanomuse-models', from: undefined })
  // a second back is a no-op
  store.back()
  assert.deepEqual(store.getSnapshot(), { open: true, activeId: 'nanomuse-models', from: undefined })
})

test('the sidebar, the same page again, and closing all start fresh', () => {
  const store = m.createShellStore()
  store.openSection('general')
  store.openSection('nanomuse-cloud')
  assert.equal(store.getSnapshot().from, 'general')
  store.select('nanomuse-files')
  assert.deepEqual(store.getSnapshot(), { open: true, activeId: 'nanomuse-files', from: undefined })
  store.openSection('nanomuse-files')
  assert.equal(store.getSnapshot().from, undefined, 'the page it is already on is not a way back')
  store.openSection('agent-presets')
  assert.equal(store.getSnapshot().from, 'nanomuse-files')
  store.close()
  assert.deepEqual(store.getSnapshot(), { open: false, activeId: undefined, from: undefined })
  store.open()
  store.toggle()
  assert.deepEqual(store.getSnapshot(), { open: false, activeId: undefined, from: undefined })
})

test('listeners hear every change and can leave', () => {
  const store = m.createShellStore()
  let heard = 0
  const off = store.subscribe(() => { heard += 1 })
  store.openSection('general')
  store.openSection('nanomuse-cloud')
  store.back()
  assert.equal(heard, 3)
  off()
  store.close()
  assert.equal(heard, 3)
})
