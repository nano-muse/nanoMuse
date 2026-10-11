#!/usr/bin/env node
// Writes the connectors catalogue the desktop keeps in TypeScript
// (harness/dsh-nanomuse/src/connectors-catalogue.ts) as JSON for the clients that cannot
// import it — the Android app reads it from its assets, the iPhone app from its bundle.
// Run after editing the catalogue:
//
//   node scripts/connectors-json.mjs          # write
//   node scripts/connectors-json.mjs --check  # exit 1 when the JSON is stale (CI)
//
// Needs Node 22.6+ (type stripping); the catalogue file is types and data only.
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = resolve(root, 'harness/dsh-nanomuse/src/connectors-catalogue.ts')
const targets = [
  resolve(root, 'android/src/android/app/src/main/assets/nanomuse/connectors.json'),
  resolve(root, 'android/src/ios/NanoMuse/Resources/connectors.json'),
]

const { CATALOGUE, CATEGORY_ORDER } = await import(pathToFileURL(source).href)
const json = JSON.stringify({ categories: CATEGORY_ORDER, connectors: CATALOGUE }, null, 2) + '\n'

let stale = false
for (const target of targets) {
  if (process.argv.includes('--check')) {
    let current = ''
    try { current = readFileSync(target, 'utf8') } catch { /* missing counts as stale */ }
    if (current !== json) { stale = true; console.error(`stale: ${target}`) }
  } else {
    writeFileSync(target, json)
    console.log(`${target}: ${CATALOGUE.length} connectors`)
  }
}
if (stale) {
  console.error(`run \`node scripts/connectors-json.mjs\` and commit the result`)
  process.exit(1)
}
