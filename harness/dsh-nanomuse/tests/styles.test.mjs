// The stylesheet is one string; a few rules are load-bearing for the window chrome and are
// checked here as text, so that a later restyle cannot quietly bring the macOS bug back where
// the header face over the drag region stopped taking clicks.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const css = readFileSync(fileURLToPath(new URL('../src/client/styles.ts', import.meta.url)), 'utf8')

/** The declarations of the first rule whose selector list is exactly `selector`. */
function rule(selector) {
  const lines = css.split('\n')
  const prefix = `${selector} {`
  const line = lines.find((l) => l.startsWith(prefix))
  assert.ok(line, `no rule for ${selector}`)
  return line.slice(prefix.length)
}

test('the header block is centred without a transform and without pointer-events tricks', () => {
  const header = rule('.nm-header')
  assert.doesNotMatch(header, /transform\s*:/)
  assert.doesNotMatch(header, /pointer-events\s*:/)
  assert.match(header, /left:\s*0;/)
  assert.match(header, /right:\s*0;/)
  assert.match(header, /margin:\s*0 auto/)
  assert.match(header, /width:\s*fit-content/)
  // the old escape hatch is gone with the wrapper's pointer-events:none
  assert.doesNotMatch(css, /^\.nm-header > \* \{ pointer-events: auto; \}/m)
})

test('the face, the header block and the rail face are no-drag islands on macOS and Windows', () => {
  const noDrag = css.split('\n').filter((l) => l.includes('-webkit-app-region: no-drag') && l.includes("[data-nm-platform='darwin']") && l.includes("[data-nm-platform='win32']"))
  const covers = (sel) => noDrag.some((l) => l.includes(sel))
  assert.ok(covers('.nm-header'), '.nm-header')
  assert.ok(covers('.nm-header-face'), '.nm-header-face')
  assert.ok(covers('.nm-rail-face'), '.nm-rail-face')
  // the chat header stays a drag handle
  assert.match(css, /\[data-nm-platform='win32'\]\) \[data-window-drag\][^\n]*-webkit-app-region: drag/)
})

test('on Windows the top bars clear the caption buttons by the title bar area, out of full screen only', () => {
  const scope = "html[data-nm-platform='win32']:not([data-nm-fullscreen])"
  const lines = css.split('\n')
  // one width, defined once, read from the window's title bar area rather than a fixed number
  const defs = lines.filter((l) => l.includes('--nm-caption-inset:'))
  assert.equal(defs.length, 1)
  assert.ok(defs[0].startsWith(`${scope} {`), defs[0])
  assert.match(defs[0], /env\(titlebar-area-x, 0px\)/)
  assert.match(defs[0], /env\(titlebar-area-width, 100vw\)/)
  assert.doesNotMatch(defs[0], /[1-9]\d*px/)
  // and their height, the same way, for the one bar that moves down instead
  const heightDefs = lines.filter((l) => l.includes('--nm-caption-height:'))
  assert.equal(heightDefs.length, 1)
  assert.ok(heightDefs[0].startsWith(`${scope} {`), heightDefs[0])
  assert.match(heightDefs[0], /--nm-caption-height: env\(titlebar-area-height, 0px\);/)
  // every use in the same scope: anywhere else the variable is undefined and the padding would drop to 0
  const uses = lines.filter((l) => l.includes('var(--nm-caption-inset)'))
  assert.ok(uses.length >= 9)
  const heightUses = lines.filter((l) => l.includes('var(--nm-caption-height)'))
  assert.ok(heightUses.length >= 1)
  for (const l of [...uses, ...heightUses]) assert.ok(l.startsWith(`${scope} `), l)
  // a task's detail is a narrow column: it moves down rather than giving up the width, and the
  // Schedules title row clears the corner only while no detail takes it
  assert.ok(heightUses.some((l) => l.includes('[data-detail-tab]')))
  assert.ok(!uses.some((l) => l.includes('[data-detail-tab]')))
  assert.ok(uses.some((l) => l.includes('task-manager-page"]:not(:has(> aside))')))
  // the harness's bars by its markers; a class name only by its stem (_pageHeading), never a full
  // hashed CSS module class
  for (const marker of ['[data-plugin-panel]', 'task-manager-page', '[data-dockkit-strip-chrome]']) {
    assert.ok(uses.some((l) => l.includes(marker)), marker)
  }
  for (const l of [...uses, ...heightUses]) assert.doesNotMatch(l, /\.[\w-]*_/, l)
  // the split pane's bars sit below its own top strip and get nothing
  for (const l of uses.filter((l) => /\.nm-(room-head|view-bar)/.test(l))) assert.match(l, /:not\(\.nm-split \*\)/, l)
})

test('the desk-a additions sit at the end of the sheet, under their marker', () => {
  const marker = css.indexOf('/* desk-a */')
  assert.ok(marker > 0)
  assert.ok(css.indexOf('.nm-rail-face, button:has(> .nm-rail-face)') > marker)
})

test('the lights breathe: nothing runs round, sweeps across or flows in the stylesheet', () => {
  // the phone's rhythm — 2.4 s in, 2.4 s out — on every light that says "working"
  for (const sel of ['.nm-chat-dot.nm-live', '.nm-status-dot.nm-live', '.nm-traj-live', '.nm-mic.nm-live', '.nm-remote-working::before']) {
    const r = rule(sel)
    assert.match(r, /animation:\s*nm-(pulse 2\.4s|breathe-light 4\.8s|mic-pulse 4\.8s) ease-in-out infinite/, sel)
  }
  assert.match(rule('html[data-nm-muse] [data-chat-running]::after'), /nm-breathe-light 4\.8s ease-in-out infinite/)
  // no marquee, no shimmer, no running border, no flowing gradient
  assert.doesNotMatch(css, /conic-gradient/)
  assert.doesNotMatch(css, /background-position/)
  assert.doesNotMatch(css, /@keyframes nm-(dots|ripple|stage-pulse|flow|sweep|shimmer|marquee)\b/)
  assert.doesNotMatch(css, /\.nm-stage/)
  // the breathing keyframes go between a dim and a full light, no travel
  assert.match(css, /@keyframes nm-breathe-light \{ 0%, 100% \{ opacity: 0\.3; \} 50% \{ opacity: 1; \} \}/)
})

test('a thread from other devices in the hero layout is bottom-aligned by an auto margin, so it scrolls (#261)', () => {
  const scroll = '[data-conversation-content][data-content-phase="hero"] > [data-conversation-scroll]'
  // the bubbles and the run card in the scrolling body: the alignment of the column itself stays at
  // the start, since a column aligned to its end or centred puts its overflow above the top edge,
  // where no scroll reaches it
  assert.match(rule(`${scroll}:has(.nm-remote, .nm-traj)`), /justify-content:\s*flex-start/)
  for (const line of css.split('\n').filter((l) => l.startsWith(scroll))) {
    assert.doesNotMatch(line, /justify-content:\s*(flex-end|end|center|safe)/, line)
  }
  // the first of them takes the free space above it while there is some
  const first = rule(`${scroll} > :is(.nm-remote, .nm-traj):not(:is(.nm-remote, .nm-traj) ~ :is(.nm-remote, .nm-traj))`)
  assert.match(first, /margin-top:\s*auto/)
  // and the old first-child margin, which did nothing once the bubbles overflowed, is gone
  assert.doesNotMatch(css, /\.nm-remote:first-child \{ margin-top: 16px/)
})

test('under prefers-reduced-motion every breathing light is steady', () => {
  const reduced = css.split('\n').filter((l) => l.startsWith('@media (prefers-reduced-motion: reduce)'))
  assert.ok(reduced.length >= 2)
  const steady = reduced.find((l) => l.includes('.nm-traj-live'))
  assert.ok(steady, 'the trajectory light is covered')
  for (const sel of ['.nm-chat-dot.nm-live', '.nm-status-dot.nm-live', '.nm-remote-working::before', '.nm-mic.nm-live', 'html[data-nm-muse] [data-chat-running]::after']) assert.ok(steady.includes(sel), sel)
  assert.match(steady, /animation: none; opacity: 1;/)
})
