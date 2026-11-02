#!/usr/bin/env node
// The runtime owns the shared authoring guide; clients ship identical copies.
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const root = new URL('../', import.meta.url)
const source = readFileSync(new URL('nanomuse/skills/builtin/skill-creator/SKILL.md', root))
const targets = [
  'harness/dsh-nanomuse/assets/skill-creator.md',
  'android/src/android/app/src/main/assets/nanomuse/skill-creator.md',
]
for (const target of targets) {
  const path = fileURLToPath(new URL(target, root))
  if (process.argv.includes('--check')) {
    let current
    try { current = readFileSync(path) } catch { current = Buffer.alloc(0) }
    if (!source.equals(current)) {
      console.error(`${target} is stale; run node scripts/bundled-skills.mjs`)
      process.exitCode = 1
    }
  } else writeFileSync(path, source)
}
