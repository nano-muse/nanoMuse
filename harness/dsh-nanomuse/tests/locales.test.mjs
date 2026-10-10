// The two dictionaries, side by side: every `{hole}` an English string has, its Chinese twin
// has too (the client fills them by name); a Chinese entry reads the same as the English one
// only when it is a name (nanoMuse, Harness, a URL); quotation marks in Chinese are 「」, not
// the English pair. Each of these was a slip once ('kwai is working…', 'online', “始终允许”).
import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readdir, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { build } from 'esbuild'

const here = fileURLToPath(new URL('.', import.meta.url))
let dir
let en
let zh

/** Entries whose Chinese is, on purpose, the English: names, a URL, a field label the vendors use. */
const SAME_ON_PURPOSE = new Set([
  'title',
  'nav',
  'brand',
  'railLabel',
  'navHarness',
  'handsAct',
  'cnCustomUrl',
  'fsMacTitle',
  'style_muse',
  'abVersionBundle',
  'ownKeyKeyField',
  'ownKeyChatGptRow',
  'nwProxyPlaceholder',
])

const holes = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(',')

before(async () => {
  dir = await mkdtemp(join(tmpdir(), 'nm-locales-'))
  await build({
    entryPoints: [join(here, '..', 'src', 'client', 'locales.ts')],
    bundle: true,
    format: 'esm',
    platform: 'node',
    outfile: join(dir, 'locales.mjs'),
    logLevel: 'silent',
  })
  ;({ en, zh } = await import(pathToFileURL(join(dir, 'locales.mjs')).href))
})

after(async () => {
  await rm(dir, { recursive: true, force: true })
})

test('en and zh have the same keys', () => {
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort())
})

test('every {hole} of an English string is in its Chinese twin', () => {
  const off = Object.keys(en).filter((k) => holes(en[k]) !== holes(zh[k]))
  assert.deepEqual(off, [])
})

test('a Chinese entry equals the English only when it is a name', () => {
  const same = Object.keys(en).filter((k) => en[k] === zh[k] && !SAME_ON_PURPOSE.has(k))
  assert.deepEqual(same, [], 'English left in the Chinese dictionary')
  const gone = [...SAME_ON_PURPOSE].filter((k) => en[k] !== zh[k])
  assert.deepEqual(gone, [], 'drop these from SAME_ON_PURPOSE')
})

test('Chinese quotes are 「」', () => {
  const off = Object.keys(zh).filter((k) => /["“”]/.test(zh[k]))
  assert.deepEqual(off, [])
})

test('no string names this computer', () => {
  // the presence line once read 'kwai is working…' — a developer's host name baked into both dictionaries
  for (const [k, v] of Object.entries(en)) assert.ok(!/\bkwai\b/i.test(v), `${k}: ${v}`)
  for (const [k, v] of Object.entries(zh)) assert.ok(!/\bkwai\b/i.test(v), `${k}: ${v}`)
})

test('house style: no em or en dashes, no exclamation marks, in either language', () => {
  // the voice rule (AGENTS.md): plain sentences with commas, colons and full stops; the
  // 0.1.41 dictionaries carried 66 English and 49 Chinese strings with a dash
  const dashed = (dict) => Object.keys(dict).filter((k) => /[—–]/.test(dict[k]))
  const loud = (dict) => Object.keys(dict).filter((k) => /[!！]/.test(dict[k]))
  assert.deepEqual(dashed(en), [], 'English strings with a dash')
  assert.deepEqual(dashed(zh), [], 'Chinese strings with a dash')
  assert.deepEqual(loud(en), [], 'English strings with an exclamation mark')
  assert.deepEqual(loud(zh), [], 'Chinese strings with an exclamation mark')
})

/** Keys built at run time from a prefix (`t(\`style_${id}\`)`, `t(\`mood_${mood}\`)`). */
const COMPUTED_PREFIXES = ['style_', 'mood_']

test('every key is used somewhere in the client or the host', async () => {
  // 102 keys of 0.1.41 were used nowhere (old onboarding slides, the first profile drawer, the
  // first About); a key nobody reads is a string nobody reviews
  const src = join(here, '..', 'src')
  let text = ''
  const walk = async (d) => {
    for (const entry of await readdir(d, { withFileTypes: true })) {
      const p = join(d, entry.name)
      if (entry.isDirectory()) await walk(p)
      else if (/\.(ts|tsx)$/.test(entry.name) && !p.endsWith(join('client', 'locales.ts'))) text += (await readFile(p, 'utf8')) + '\n'
    }
  }
  await walk(src)
  const dead = Object.keys(en).filter((k) => !COMPUTED_PREFIXES.some((p) => k.startsWith(p)) && !new RegExp(`\\b${k}\\b`).test(text))
  assert.deepEqual(dead, [], 'locale keys nothing reads')
})
