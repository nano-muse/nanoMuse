// The stage's desk: approvals raced against the chat card, holds of the hands, the
// update check, what the other devices see of the connectors, the model rules.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { BUNDLE_VERSION } from '../lib/cloud.js'
import { ApprovalDesk, HoldDesk, checkForUpdate, compareVersions, pickAsset, pickChatModel, pickHandsModel, readSharedConnectors, sharedConnectors, takesImages } from '../lib/desk.js'

const req = (callId, sessionId = 's1') => ({ agent: { id: 'a1', session: { id: sessionId } }, toolName: 'bash', callId, reason: 'rm -rf build', displayReason: { en: 'Remove the build folder', zh: '删除 build 目录' } })

test('an approval the stage answers first wins; the chat card is let go', async () => {
  let changes = 0
  const desk = new ApprovalDesk(() => changes++)
  let chatResolve
  const chat = () => new Promise((resolve) => { chatResolve = resolve })
  const outcome = desk.handle(req('c1'), chat)
  await new Promise((r) => setImmediate(r))
  assert.equal(desk.list().length, 1)
  assert.equal(desk.list()[0].summary, 'Remove the build folder')
  assert.equal(desk.list()[0].summaryZh, '删除 build 目录')
  assert.equal(desk.decide('c1', false), true)
  assert.equal(await outcome, 'rejected')
  assert.equal(desk.list().length, 0)
  assert.equal(desk.decide('c1', true), false)
  chatResolve('allowed-once')
  assert.ok(changes >= 2)
})

test('the stage\'s answer withdraws the chat card through a signal of its own; the asker\'s signal still cancels both', async () => {
  const desk = new ApprovalDesk(() => undefined)
  const asker = new AbortController()
  const request = { ...req('c1b'), signal: asker.signal }
  // the chat card, as the bridge shows it: it reads the request's signal when it is shown and ends with it
  let cardSignal
  const chat = () => new Promise((resolve, reject) => {
    cardSignal = request.signal
    cardSignal.addEventListener('abort', () => reject(cardSignal.reason), { once: true })
  })
  const outcome = desk.handle(request, chat)
  await new Promise((r) => setImmediate(r))
  assert.notEqual(cardSignal, asker.signal, 'the card follows a signal of its own')
  assert.equal(desk.decide('c1b', true), true)
  assert.equal(await outcome, 'allowed-once')
  assert.equal(cardSignal.aborted, true, 'the card is taken down')
  assert.equal(asker.signal.aborted, false, 'the tool call itself is not cancelled')
  assert.equal(request.signal, asker.signal, 'the request is put back as it came')

  // the asker gives up (the turn is stopped): stage and card both end
  const asker2 = new AbortController()
  const request2 = { ...req('c1c'), signal: asker2.signal }
  let card2
  const chat2 = () => new Promise((_resolve, reject) => {
    card2 = request2.signal
    card2.addEventListener('abort', () => reject(card2.reason), { once: true })
  })
  const outcome2 = desk.handle(request2, chat2)
  await new Promise((r) => setImmediate(r))
  asker2.abort(new Error('stopped'))
  assert.equal(await outcome2, 'cancelled')
  assert.equal(card2.aborted, true)
  assert.equal(desk.list().length, 0)
})

test('an approval the chat answers first clears the stage', async () => {
  const desk = new ApprovalDesk(() => undefined)
  const outcome = await desk.handle(req('c2'), async () => 'allowed-once')
  assert.equal(outcome, 'allowed-once')
  assert.equal(desk.list().length, 0)
})

test('approvals of an excluded session go straight to the next answerer', async () => {
  const desk = new ApprovalDesk(() => undefined)
  desk.exclude('task-session')
  let listed = -1
  const outcome = await desk.handle(req('c3', 'task-session'), async () => { listed = desk.list().length; return 'rejected' })
  assert.equal(outcome, 'rejected')
  assert.equal(listed, 0)
})

test('a hold pauses the hands until Done, and a second take-over only refreshes it', async () => {
  const desk = new HoldDesk(() => undefined)
  assert.equal(await desk.wait('s1'), 'clear')
  const hold = desk.begin('s1', 'computer', 'agent', 'type the password')
  assert.equal(hold.status, 'on')
  assert.equal(hold.type, 'hold')
  const again = desk.begin('s1', 'computer', 'user', '')
  assert.equal(again.id, hold.id)
  assert.equal(again.by, 'user')
  assert.equal(again.reason, 'type the password')
  assert.equal(desk.list().length, 1)
  const waiting = desk.wait('s1')
  setTimeout(() => desk.done(hold.id), 10)
  assert.equal(await waiting, 'done')
  assert.equal(desk.list().length, 0)
  assert.equal(desk.done(hold.id), false)
  assert.equal(await desk.wait('s1', undefined, 5), 'clear')
  const h2 = desk.begin('s2', 'browser', 'user', 'x')
  assert.equal(await desk.wait('s2', undefined, 5), 'timeout')
  desk.done(h2.id)
})

test('versions compare numerically, with pre-releases below the release', () => {
  assert.equal(compareVersions('0.1.34', '0.1.33'), 1)
  assert.equal(compareVersions('v0.1.33', '0.1.33'), 0)
  assert.equal(compareVersions('0.1.9', '0.1.10'), -1)
  assert.equal(compareVersions('0.2.0-rc.2', '0.2.0'), -1)
  assert.equal(compareVersions('0.1.34', '0.1.34-rc.1'), 1)
  // a labelled version reads as its number: 0.1.40 compared "dsh-nanomuse 0.1.40" as 0 and
  // offered the installed release as an update
  assert.equal(compareVersions('0.1.40', 'dsh-nanomuse 0.1.40'), 0)
  assert.equal(compareVersions('dsh-nanomuse 0.1.41', 'v0.1.40'), 1)
  assert.equal(compareVersions('nanoMuse-Desktop-0.1.40', '0.1.41'), -1)
})

test('the update check compares the bare bundle version, so the installed release is not offered again', async () => {
  const mirror = { repo: 'nano-muse/nanoMuse', releases: [{ tag: 'v0.1.40', assets: [] }] }
  const fetchMirror = async () => ({ ok: true, status: 200, json: async () => mirror })
  const same = await checkForUpdate(BUNDLE_VERSION, fetchMirror)
  assert.equal(same.current, BUNDLE_VERSION)
  assert.match(BUNDLE_VERSION, /^\d+\.\d+\.\d+/)
  assert.equal(same.newer, compareVersions('0.1.40', BUNDLE_VERSION) > 0)
  const installed = await checkForUpdate('0.1.40', fetchMirror)
  assert.equal(installed.newer, false)
  const labelled = await checkForUpdate('dsh-nanomuse 0.1.40', fetchMirror)
  assert.equal(labelled.newer, false)
})

test('the installer for this computer is picked from the release', () => {
  const assets = ['nanoMuse-Desktop-0.1.34-linux-x64.AppImage', 'nanoMuse-Desktop-0.1.34-linux-x64.deb', 'nanoMuse-Desktop-0.1.34-mac-arm64.dmg', 'nanoMuse-Desktop-0.1.34-mac-x64.zip', 'nanoMuse-Desktop-0.1.34-win-x64.exe', 'nanoMuse-0.1.34-arm64.apk'].map((name) => ({ name, url: `https://x/${name}`, size: 1 }))
  assert.equal(pickAsset(assets, 'darwin', 'arm64')?.name, 'nanoMuse-Desktop-0.1.34-mac-arm64.dmg')
  assert.equal(pickAsset(assets, 'darwin', 'x64')?.name, 'nanoMuse-Desktop-0.1.34-mac-x64.zip')
  assert.equal(pickAsset(assets, 'win32', 'x64')?.name, 'nanoMuse-Desktop-0.1.34-win-x64.exe')
  assert.equal(pickAsset(assets, 'linux', 'x64')?.name, 'nanoMuse-Desktop-0.1.34-linux-x64.AppImage')
  assert.equal(pickAsset(assets, 'linux', 'arm64'), undefined)
})

test('the update check reads the nanomuse.cn index first, GitHub second, and never throws (C2)', async () => {
  const github = { tag_name: 'v0.1.34', html_url: 'https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.34', body: 'notes', assets: [{ name: 'nanoMuse-Desktop-0.1.34-win-x64.exe', browser_download_url: 'https://dl/x.exe', size: 5 }] }
  const mirror = { repo: 'nano-muse/nanoMuse', releases: [{ tag: 'v0.1.33', assets: [{ name: 'nanoMuse-Desktop-0.1.33-linux-x64.AppImage', size: 3 }] }] }
  // both answer: the index wins, and GitHub is not asked at all
  const asked = []
  const both = async (url) => { asked.push(url); return { ok: true, status: 200, json: async () => (url.includes('github') ? github : mirror) } }
  const a = await checkForUpdate('0.1.33', both)
  assert.equal(a.source, 'nanomuse.cn')
  assert.equal(a.latest, '0.1.33')
  assert.equal(a.newer, false)
  assert.equal(a.assets[0].url, 'https://github.com/nano-muse/nanoMuse/releases/download/v0.1.33/nanoMuse-Desktop-0.1.33-linux-x64.AppImage')
  assert.deepEqual(asked, ['https://nanomuse.cn/dl/index.json'])

  // the index does not answer: GitHub
  const b = await checkForUpdate('0.1.33', async (url) => (url.includes('nanomuse.cn') ? { ok: false, status: 502, json: async () => ({}) } : { ok: true, status: 200, json: async () => github }))
  assert.equal(b.source, 'github')
  assert.equal(b.latest, '0.1.34')
  assert.equal(b.newer, true)
  assert.equal(b.assets[0].url, 'https://dl/x.exe')

  const c = await checkForUpdate('0.1.33', async () => { throw new Error('offline') })
  assert.equal(c.source, 'none')
  assert.equal(c.latest, '')
  assert.match(c.error, /nanomuse\.cn: offline; github: offline/)
})

test('each update request gives up after the timeout (5 s by default)', async () => {
  // a fetch that never resolves until aborted
  const hang = (url, init) => new Promise((_, reject) => { init.signal.addEventListener('abort', () => reject(new Error('aborted'))) })
  const started = Date.now()
  const info = await checkForUpdate('0.1.33', hang, 30)
  assert.equal(info.source, 'none')
  assert.match(info.error, /aborted/)
  assert.ok(Date.now() - started < 2000)
})

test('shared connectors carry what and where, never how', () => {
  const rows = sharedConnectors([
    { service: 'notion', id: 'cn_1', label: 'Notion', url: 'https://mcp.notion.com/mcp', auth: 'oauth', state: 'ok', connectedAt: 1, updatedAt: 2 },
    { service: 'custom', id: 'cn_2', label: 'My server', url: 'https://x.example/mcp', auth: 'header', state: 'error', connectedAt: 3, updatedAt: 0 },
  ], 'Office PC', 'pc-dsh-abc')
  assert.equal(rows.length, 2)
  assert.equal(rows[0].id, 'notion')
  assert.equal(rows[0].auth, 'oauth')
  assert.equal(rows[0].enabled, true)
  assert.equal(rows[1].id, 'cn_2')
  assert.equal(rows[1].auth, 'key')
  assert.equal(rows[1].enabled, false)
  assert.equal(rows[1].device_id, 'pc-dsh-abc')
  for (const row of rows) for (const field of Object.keys(row)) assert.doesNotMatch(field, /token|secret|key|authorization|password/i)
  const back = readSharedConnectors([...rows, { nope: true }, { id: 'x', auth: 'weird' }])
  assert.equal(back.length, 3)
  assert.equal(back[2].auth, 'open')
})

test('the chat and hands defaults follow the relay\'s `for`, with the 0.1.34 names first', () => {
  const models = [
    { id: 'deepseek-v4.1-flash', kind: 'chat', recommended: false, inputModalities: ['text', 'image'], for: ['chat'] },
    { id: 'deepseek-v4', kind: 'chat', recommended: true, inputModalities: ['text', 'image'], for: ['chat'] },
    { id: 'qwen3.8-27b', kind: 'chat', recommended: false, inputModalities: ['text', 'image'], for: ['gui'] },
    { id: 'qwen3-vl', kind: 'chat', recommended: true, inputModalities: ['text', 'image'], for: ['chat', 'gui'] },
  ]
  assert.equal(pickChatModel(models)?.id, 'deepseek-v4.1-flash')
  assert.equal(pickHandsModel(models)?.id, 'qwen3.8-27b')
  assert.equal(pickChatModel([{ id: 'old', kind: 'chat', recommended: true, inputModalities: ['text'] }])?.id, 'old')
  assert.equal(pickHandsModel([{ id: 'old', kind: 'chat', recommended: true, inputModalities: ['text'] }]), undefined)
  assert.equal(takesImages({ id: 'deepseek-v4', inputModalities: ['text', 'image'] }), false)
  assert.equal(takesImages({ id: 'deepseek-v4.1-flash', inputModalities: ['text'] }), true)
  assert.equal(takesImages({ id: 'deepseek-ocr', inputModalities: [] }), true)
  assert.equal(takesImages({ id: 'qwen3-vl', inputModalities: ['text', 'image'] }), true)
})

test('the provider row carries the image budget of a request through the relay (413 too_large): 5 MiB of base64 images, 2 Mpx a picture, the per-image byte cap left to dsh', async () => {
  const { providerRowFor, IMAGE_BUDGET } = await import('../lib/cloud.js')
  const row = providerRowFor('https://relay.test/v1', [
    { id: 'deepseek-v4.1', name: 'DeepSeek V4.1', kind: 'chat', recommended: true, inputModalities: ['text', 'image'], for: ['chat'] },
    { id: 'qwen3.8-27b', name: 'Qwen', kind: 'chat', recommended: false, inputModalities: ['text', 'image'], for: ['gui'] },
    { id: 'wan-video', name: 'Wan', kind: 'video', recommended: false, inputModalities: ['text'], for: ['video'] },
  ])
  assert.equal(row.api, 'openai-completions')
  assert.equal(row.baseURL, 'https://relay.test/v1')
  assert.equal(row.maxRequestImageBytes, 5 * 1024 * 1024)
  assert.equal(row.requestImagePixelBudget, 2 * 1024 * 1024)
  assert.equal(row.requestImageMaxBytes, undefined)
  assert.deepEqual(IMAGE_BUDGET, { maxRequestImageBytes: 5 * 1024 * 1024, requestImagePixelBudget: 2 * 1024 * 1024 })
  // under the relay's 6 MiB cap with room for the text
  assert.ok(row.maxRequestImageBytes < 6 * 1024 * 1024)
  assert.deepEqual(row.models.map((m) => m.id), ['deepseek-v4.1'])
  assert.deepEqual(row.models[0].input, ['text', 'image'])
})
