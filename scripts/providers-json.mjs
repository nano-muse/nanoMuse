#!/usr/bin/env node
// Copies the own-key provider catalogue (nanomuse/llm/providers.json, the source of truth;
// contract C11) to the clients that cannot read the runtime's package data — the desktop
// plugin's assets, the Android app's assets, the iPhone app's bundle — and to the relay,
// which orders it per region for its "ways on" guidance. Run after editing the catalogue:
//
//   node scripts/providers-json.mjs          # write
//   node scripts/providers-json.mjs --check  # exit 1 when a copy is stale (CI)
//
// The file is `{version, updated, capabilities[], auth_kinds[], providers[]}`; each provider
// has `id`, `name`, `name_zh`, `protocol` (openai | openai-responses | anthropic | gemini),
// `base_url` (+ optional `base_url_global`), `key_url` (+ optional `key_url_global`,
// `key_hint`), `auth[]` (key | none | oauth-chatgpt | oauth-claude | oauth-openrouter |
// device-kimi), optional `auth_capabilities{auth: capabilities[]}` when a sign-in gives less
// than the key does, `regions[]` (cn | global), `capabilities[]` (chat | vision | image |
// video), `defaults{chat, hands, image, video}`, `note`/`note_zh`, `verified` (the month the
// facts were checked against the vendor's docs) and, for `custom`, `user_capabilities: true`.
// An optional `reasoning` hint says how the vendor takes a thinking level, as its docs state
// it: `doc` (the page checked), `wire` (reasoning_effort | thinking+reasoning_effort |
// reasoning.effort | output_config.effort), `rules[]` of `{models, levels[], default?}` where
// `models` is a regular expression over the model id (matched without regard to case, first
// match wins), `levels` are from minimal | low | medium | high | xhigh | max and `default` is
// one of them or `none` (the vendor thinks only when asked); `listed: true` when the endpoint's
// model list names each model's levels (OpenRouter). A provider without the hint shows no
// thinking control on the desktop; the phones ignore the field.
// An optional `session_header` names the request header in which the vendor's docs ask a client
// to send one stable id per conversation (OpenCode Go: `x-opencode-session`). The runtime sends
// it with its own user agent; the desktop writes such an entry as its model adapter's catalog
// route of the same id, which sends the header itself; the phones, which cannot send it yet,
// leave the entry out, and so does the relay's guidance, which the phones read.
// The copies are byte-identical to the source; the source is validated here so a typo never
// reaches a client.
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = resolve(root, 'nanomuse/llm/providers.json')
const targets = [
  resolve(root, 'harness/dsh-nanomuse/assets/providers.json'),
  resolve(root, 'android/src/android/app/src/main/assets/nanomuse/providers.json'),
  resolve(root, 'android/src/ios/NanoMuse/Resources/providers.json'),
  // the relay builds the "ways on" guidance from the same facts (cloud/nanomuse_cloud/providers.py)
  resolve(root, 'cloud/nanomuse_cloud/providers.json'),
]

const PROTOCOLS = new Set(['openai', 'openai-responses', 'anthropic', 'gemini'])
const REGIONS = new Set(['cn', 'global'])
const WIRES = new Set(['reasoning_effort', 'thinking+reasoning_effort', 'reasoning.effort', 'output_config.effort'])
const LEVELS = new Set(['minimal', 'low', 'medium', 'high', 'xhigh', 'max'])

/** The problems with a provider's `reasoning` hint, as lines; none for a well-formed hint. */
function reasoningProblems(where, protocol, hint) {
  const out = []
  if (typeof hint !== 'object' || hint === null || Array.isArray(hint)) return [`${where}: reasoning must be an object`]
  if (typeof hint.doc !== 'string' || !/^https?:\/\//.test(hint.doc)) out.push(`${where}: reasoning.doc must be the URL of the page checked`)
  if (!WIRES.has(hint.wire)) out.push(`${where}: unknown reasoning.wire ${hint.wire}`)
  const anthropic = hint.wire === 'output_config.effort'
  if (anthropic !== (protocol === 'anthropic')) out.push(`${where}: reasoning.wire ${hint.wire} does not ride the ${protocol} protocol`)
  if (hint.listed !== undefined && hint.listed !== true) out.push(`${where}: reasoning.listed may only be true`)
  if (!Array.isArray(hint.rules)) out.push(`${where}: reasoning.rules must be a list`)
  if (Array.isArray(hint.rules) && !hint.rules.length && hint.listed !== true) out.push(`${where}: reasoning needs rules or listed: true`)
  for (const [i, rule] of (Array.isArray(hint.rules) ? hint.rules : []).entries()) {
    const at = `${where}: reasoning.rules[${i}]`
    if (typeof rule !== 'object' || rule === null) { out.push(`${at} must be an object`); continue }
    if (typeof rule.models !== 'string' || !rule.models) out.push(`${at}.models must be a regular expression`)
    else try { new RegExp(rule.models, 'i') } catch { out.push(`${at}.models does not compile`) }
    if (!Array.isArray(rule.levels) || !rule.levels.length) out.push(`${at}.levels must be a non-empty list`)
    for (const level of Array.isArray(rule.levels) ? rule.levels : []) if (!LEVELS.has(level)) out.push(`${at}: unknown level ${level}`)
    if (rule.default !== undefined && rule.default !== 'none' && !(rule.levels ?? []).includes(rule.default)) out.push(`${at}.default must be one of its levels or none`)
    for (const k of Object.keys(rule)) if (!['models', 'levels', 'default'].includes(k)) out.push(`${at}: unknown field ${k}`)
  }
  for (const k of Object.keys(hint)) if (!['doc', 'wire', 'rules', 'listed'].includes(k)) out.push(`${where}: unknown reasoning field ${k}`)
  return out
}

const text = readFileSync(source, 'utf8')
const catalogue = JSON.parse(text)
const capabilities = new Set(catalogue.capabilities)
const authKinds = new Set(catalogue.auth_kinds)
const problems = []
const ids = new Set()
for (const p of catalogue.providers) {
  const where = `providers[${p.id ?? '?'}]`
  if (!/^[a-z][a-z0-9-]*$/.test(p.id ?? '')) problems.push(`${where}: bad id`)
  if (ids.has(p.id)) problems.push(`${where}: duplicate id`)
  ids.add(p.id)
  for (const k of ['name', 'name_zh', 'note', 'note_zh', 'verified']) {
    if (typeof p[k] !== 'string') problems.push(`${where}: ${k} must be a string`)
  }
  if (!/^\d{4}-\d{2}$/.test(p.verified ?? '')) problems.push(`${where}: verified must be YYYY-MM`)
  if (!PROTOCOLS.has(p.protocol)) problems.push(`${where}: unknown protocol ${p.protocol}`)
  if (typeof p.base_url !== 'string') problems.push(`${where}: base_url must be a string`)
  if (p.base_url && !/^https?:\/\//.test(p.base_url)) problems.push(`${where}: base_url must be a URL`)
  if (typeof p.key_url !== 'string') problems.push(`${where}: key_url must be a string`)
  if (!Array.isArray(p.auth) || !p.auth.length) problems.push(`${where}: auth must be a non-empty list`)
  for (const a of p.auth ?? []) if (!authKinds.has(a)) problems.push(`${where}: unknown auth ${a}`)
  for (const a of Object.keys(p.auth_capabilities ?? {})) {
    if (!(p.auth ?? []).includes(a)) problems.push(`${where}: auth_capabilities.${a} is not in auth`)
    for (const c of p.auth_capabilities[a]) if (!capabilities.has(c)) problems.push(`${where}: unknown capability ${c}`)
  }
  if (!Array.isArray(p.regions) || !p.regions.length) problems.push(`${where}: regions must be a non-empty list`)
  for (const r of p.regions ?? []) if (!REGIONS.has(r)) problems.push(`${where}: unknown region ${r}`)
  if (!Array.isArray(p.capabilities) || !p.capabilities.includes('chat')) problems.push(`${where}: capabilities must include chat`)
  for (const c of p.capabilities ?? []) if (!capabilities.has(c)) problems.push(`${where}: unknown capability ${c}`)
  for (const [lane, model] of Object.entries(p.defaults ?? {})) {
    const need = lane === 'hands' ? 'vision' : lane
    if (!capabilities.has(need)) problems.push(`${where}: defaults.${lane} is not a lane`)
    else if (!(p.capabilities ?? []).includes(need)) problems.push(`${where}: defaults.${lane} without the ${need} capability`)
    if (typeof model !== 'string' || !model) problems.push(`${where}: defaults.${lane} must be a model id`)
  }
  for (const c of p.capabilities ?? []) {
    if (c === 'vision' || p.id === 'custom' || p.auth.includes('none')) continue
    if (!(p.defaults ?? {})[c]) problems.push(`${where}: a ${c} capability needs defaults.${c}`)
  }
  if (p.reasoning !== undefined) problems.push(...reasoningProblems(where, p.protocol, p.reasoning))
  if (p.session_header !== undefined && !/^x-[a-z0-9-]+$/.test(p.session_header)) problems.push(`${where}: session_header must be a lowercase x- header name`)
}
if (problems.length) {
  for (const line of problems) console.error(line)
  process.exit(2)
}

let stale = false
for (const target of targets) {
  if (process.argv.includes('--check')) {
    let current = ''
    try { current = readFileSync(target, 'utf8') } catch { /* missing counts as stale */ }
    if (current !== text) { stale = true; console.error(`stale: ${target}`) }
  } else {
    writeFileSync(target, text)
    console.log(`${target}: ${catalogue.providers.length} providers`)
  }
}
if (stale) {
  console.error(`run \`node scripts/providers-json.mjs\` and commit the result`)
  process.exit(1)
}
