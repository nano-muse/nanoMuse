// Exercise the two desktop views with the same completed phone turn, including the
// observer which dresses synced rows in an already-open chat.
import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'

const browser = [process.env.CHROME_BIN, 'google-chrome', 'chromium', 'microsoft-edge']
  .filter(Boolean).find((name) => spawnSync(name, ['--version']).status === 0)
const plugin = fileURLToPath(new URL('..', import.meta.url))

function mount({ h, createRoot, renderRemoteBubbles, DeviceConversationPanel, openDeviceConversation }) {
  const prompt = '**按原样显示**'
  const answer = [
    '## 研究领域', '', '- **统计学**', '', '| 年份 | 方向 |', '| --- | --- |', '| 2020 | 优化 |',
    '', '---', '', '```', '## literal', '```', '', '<img alt="示例">',
  ].join('\n')
  const lines = ['user', 'assistant'].map((role, i) => ({
    id: String(i), mid: 'm' + i, role, text: i ? answer : prompt, device: 'phone',
    deviceName: '测试手机', at: 1 + i, before: null,
  }))
  lines.push({ mid: 'check', id: 'check', role: 'assistant', device: '', deviceName: '', at: 3,
    before: null, localCheckIn: true, text: 'Would you like help with <b>the museum</b>?' })
  const chat = { id: 'bound', device: 'phone', name: '测试手机', draft: '', turns: [
    { id: 'a', text: prompt, state: 'completed', answer },
  ] }
  window.fetch = async (url) => Response.json(String(url).includes('sync/remote') ? { lines, hidden: [] } : [chat])
  let roomsStream
  window.EventSource = class {
    constructor(url) { if (String(url).includes('/rooms/events')) roomsStream = this }
    close() {}
  }
  let notification
  window.Notification = class {
    static permission = 'granted'
    constructor(title, options) { notification = { title, body: options.body } }
    close() {}
  }
  document.hasFocus = () => false
  // Headless Chromium does not paint between ticks of its virtual clock.
  window.requestAnimationFrame = (fn) => setTimeout(fn, 0)
  const t = (key, values) => key === 'chFrom' ? '来自 ' + values.device : key
  const stop = renderRemoteBubbles(t)
  function emit(checkIns) {
    roomsStream.onmessage({ data: JSON.stringify({ feed: { routine: { on: true, checkInScope: 'local-fixture' } }, checkIns }) })
  }
  emit([])
  emit([{ id: 'check', sessionId: 'main', at: Date.now(), unread: true }])
  openDeviceConversation(chat.id)
  createRoot(document.getElementById('devices')).render(h(DeviceConversationPanel, { t, devices: [] }))

  setTimeout(() => {
    const assistant = document.querySelector('.nm-remote-assistant')
    const user = document.querySelector('.nm-remote-user .nm-remote-bubble')
    const bound = document.querySelector('#devices article')
    function elements(root) {
      const text = (selector) => root?.querySelector(selector)?.textContent
      return [text('h1,h2,h3,h4,h5,h6'), text('ul li strong'), text('tbody td:last-child'),
        text('pre code')?.trimEnd(), !!root?.querySelector('hr'), !!root?.querySelector('img')]
    }
    const result = {
      synced: elements(assistant?.querySelector('.nm-remote-bubble')),
      bound: elements(bound?.querySelector(':scope > div')),
      source: assistant?.querySelector('.nm-remote-from')?.textContent,
      notification,
      local: document.querySelector('[data-nm-checkin] .nm-remote-bubble')?.textContent,
      localLabel: document.querySelector('[data-nm-checkin] .nm-remote-from')?.textContent,
      literalPrompt: user?.textContent === prompt && !user.querySelector('strong'),
    }
    stop()
    result.cleanedUp = !document.querySelector('.nm-remote') && !assistant?.querySelector('table')
    document.body.dataset.testResult = encodeURIComponent(JSON.stringify(result))
  }, 1500)
}

test('phone replies render Markdown in synced and device-bound chats, while a typed prompt stays literal', {
  skip: !browser && 'Set CHROME_BIN to run the browser regression',
}, async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'nm-phone-markdown-'))
  t.after(() => rm(dir, { recursive: true, force: true }))
  await build({
    stdin: {
      resolveDir: plugin,
      contents: [
        "import { createElement as h } from 'react'",
        "import { createRoot } from 'react-dom/client'",
        "import { renderRemoteBubbles } from './src/client/RemoteBubbles.ts'",
        "import { DeviceConversationPanel, openDeviceConversation } from './src/client/DeviceConversationPanel.tsx'",
        '(' + mount.toString() + ')({h, createRoot, renderRemoteBubbles, DeviceConversationPanel, openDeviceConversation})',
      ].join('\n'),
    },
    outfile: join(dir, 'fixture.js'), bundle: true, minify: true, platform: 'browser',
    define: { 'process.env.NODE_ENV': '"production"' },
    plugins: [{ name: 'host-primitives', setup(b) {
      b.onResolve({ filter: /^@deepseek-ai\/dsh-client-ui-primitives$/ }, () => ({ path: 'ui', namespace: 'host' }))
      b.onLoad({ filter: /.*/, namespace: 'host' }, () => ({ contents: "export const Button = 'button', Modal = 'dialog'" }))
    } }],
  })
  const page = join(dir, 'fixture.html')
  await writeFile(page, '<meta charset="utf-8"><body><div data-conversation-content data-conversation-session="main"><div data-chat-flow></div></div><div id="devices"></div><script src="fixture.js"></script>')
  const output = execFileSync(browser, [
    '--headless', '--no-sandbox', '--disable-gpu', '--no-first-run', '--disable-dev-shm-usage',
    '--user-data-dir=' + join(dir, 'profile'), '--virtual-time-budget=3000', '--dump-dom', pathToFileURL(page).href,
  ], { encoding: 'utf8', timeout: 30_000, stdio: ['ignore', 'pipe', 'pipe'] })
  const captured = /data-test-result="([^"]+)"/.exec(output)
  assert.ok(captured, 'the browser fixture did not finish')
  const { synced, bound, source, literalPrompt, cleanedUp, local, localLabel, notification } = JSON.parse(decodeURIComponent(captured[1]))
  assert.equal(local, 'Would you like help with <b>the museum</b>?')
  assert.equal(localLabel, 'chatCheckIn')
  assert.deepEqual(notification, { title: 'nanoMuse', body: 'chatCheckIn' }, 'desktop alerts never contain the private commitment')
  assert.equal(source, '来自 测试手机')
  assert.equal(literalPrompt, true)
  const formatted = ['研究领域', '统计学', '优化', '## literal', true, false]
  assert.deepEqual(synced, formatted, 'synced assistant turn')
  assert.deepEqual(bound, formatted, 'saved device answer')
  assert.equal(cleanedUp, true, 'the observer removes its bubbles and unmounts their Markdown')
})
