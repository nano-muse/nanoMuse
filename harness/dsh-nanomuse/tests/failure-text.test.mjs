/**
 * `failureText`: what a failed call to the host says to the person. The wire's and the
 * relay's common refusals become a plain sentence in the UI language; anything else keeps
 * the message as it came, behind "That did not work".
 */
import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { build } from 'esbuild'

const here = fileURLToPath(new URL('.', import.meta.url))
let dir
let failureText
let en
let zh

const ENTRY = `
export { failureText } from './src/client/api.ts'
export { en, zh } from './src/client/locales.ts'
`

/** The client's `t`: the dictionary's sentence with its holes filled. */
const translator = (words) => (key, vars = {}) => {
  const text = words[key]
  if (text === undefined) throw new Error(`no key ${key}`)
  return text.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? `{${name}}`))
}

before(async () => {
  dir = await mkdtemp(join(tmpdir(), 'nm-failure-text-'))
  await build({
    stdin: { contents: ENTRY, resolveDir: join(here, '..'), loader: 'js', sourcefile: 'entry.js' },
    outfile: join(dir, 'api.mjs'),
    format: 'esm',
    platform: 'node',
    target: 'node22',
    bundle: true,
    logLevel: 'silent',
  })
  ;({ failureText, en, zh } = await import(pathToFileURL(join(dir, 'api.mjs')).href))
})

after(async () => {
  await rm(dir, { recursive: true, force: true })
})

/** A failed `call`: the Error the client throws, with the relay-style code on it. */
const failed = (code, message = 'raw text from the wire') => Object.assign(new Error(message), { code })

test('memory import limits explain that nothing was imported in both languages', () => {
  for (const words of [en, zh]) {
    for (const [code, key] of [
      ['memory_import_lines', 'memImportTooMany'],
      ['memory_import_length', 'memImportTooLong'],
      ['memory_import_capacity', 'memImportFull'],
      ['memory_import_save', 'memImportSaveFailed'],
    ]) assert.equal(failureText(translator(words), failed(code)), words[key])
  }
})

test('the wire: the relay out of reach or past its deadline, in both languages', () => {
  const t = translator(en)
  assert.equal(failureText(t, failed('unreachable', 'fetch failed')), en.errUnreachable)
  assert.equal(failureText(t, failed('timeout', 'The operation was aborted due to timeout')), en.errTimeout)
  assert.equal(failureText(t, failed('504')), en.errTimeout)
  assert.equal(failureText(translator(zh), failed('unreachable', 'fetch failed')), zh.errUnreachable)
  assert.doesNotMatch(failureText(t, failed('unreachable', 'fetch failed')), /fetch failed/)
})

test("a body the wire refuses as too large reads in the person's language, not as a raw 413", () => {
  const t = translator(en)
  const z = translator(zh)
  assert.equal(failureText(t, failed('too_large', 'Request body too large')), en.errTooLarge)
  assert.equal(failureText(z, failed('too_large', 'Request body too large')), zh.errTooLarge)
  assert.doesNotMatch(failureText(t, failed('too_large', 'Request body too large')), /Request body too large/)
  // the same refusal spelled as a bare status lands on the same sentence
  assert.equal(failureText(t, failed('413', 'Request body too large')), en.errTooLarge)
  assert.ok(en.errTooLarge && zh.errTooLarge, 'errTooLarge in both languages')
})

test('the relay: too many requests, a sign-in no longer valid, a 5xx', () => {
  const t = translator(en)
  assert.equal(failureText(t, failed('rate_limited')), en.errBusy)
  assert.equal(failureText(t, failed('429')), en.errBusy)
  assert.equal(failureText(t, failed('signed_out')), en.errSignedOut)
  assert.equal(failureText(t, failed('401')), en.errSignedOut)
  assert.equal(failureText(t, failed('http_503')), 'nanoMuse Cloud ran into a problem (503). Try again in a minute.')
  assert.equal(failureText(t, failed('502')), 'nanoMuse Cloud ran into a problem (502). Try again in a minute.')
})

test("the relay's sign-in refusals read in the person's language, not as the wire's English", () => {
  const t = translator(en)
  const z = translator(zh)
  assert.equal(failureText(t, failed('code_wrong', 'That code is not right')), en.errCodeWrong)
  assert.equal(failureText(z, failed('code_wrong', 'That code is not right')), zh.errCodeWrong)
  assert.equal(failureText(t, failed('code_expired')), en.errCodeExpired)
  assert.equal(failureText(t, failed('send_failed')), en.errSendFailed)
  assert.equal(failureText(t, failed('bad_identifier', 'not a phone number or an e-mail address')), en.errBadIdentifier)
  assert.equal(failureText(t, failed('phone_region')), en.errPhoneRegion)
  assert.equal(failureText(t, failed('not_invited')), en.errNotInvited)
  assert.equal(failureText(t, failed('signup_closed')), en.errSignupClosed)
  assert.equal(failureText(t, failed('account_disabled')), en.errAccountDisabled)
  // a wrong password is a 401 and the carrier's limit a 429: the sign-in sentence, not the generic one
  assert.equal(failureText(t, failed('bad_credentials')), en.errBadCredentials)
  assert.equal(failureText(t, failed('locked')), en.errLocked)
  assert.equal(failureText(t, failed('code_too_often')), en.errCodeTooOften)
  assert.equal(failureText(z, failed('code_too_often')), zh.errCodeTooOften)
  for (const key of ['errCodeWrong', 'errCodeExpired', 'errCodeTooOften', 'errSendFailed', 'errBadIdentifier', 'errPhoneRegion', 'errNotInvited', 'errSignupClosed', 'errAccountDisabled', 'errBadCredentials', 'errLocked']) {
    assert.ok(en[key] && zh[key], `${key} in both languages`)
    assert.doesNotMatch(en[key] + zh[key], /[!！—–]/, `${key} has no exclamation mark or dash`)
  }
})

test('the host itself gone: fetch to loopback failed with no status and no code', () => {
  const t = translator(en)
  assert.equal(failureText(t, new TypeError('Failed to fetch')), en.errHostDown)
  assert.equal(failureText(t, new TypeError('NetworkError when attempting to fetch resource.')), en.errHostDown)
})

test('anything else keeps the message as it came, and an object with a code and a message works too', () => {
  const t = translator(en)
  assert.equal(failureText(t, failed('not_found', 'No such goal')), 'That did not work: No such goal')
  assert.equal(failureText(t, failed('internal', 'ENOENT: profile.json')), 'That did not work: ENOENT: profile.json')
  assert.equal(failureText(t, { code: 'bad_request', message: 'name is required' }), 'That did not work: name is required')
  assert.equal(failureText(t, new Error('plain')), 'That did not work: plain')
  assert.equal(failureText(t, 'a string'), 'That did not work: a string')
})
