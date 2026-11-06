/**
 * Words for what a Hands or Reach call is doing, and the toasts for what other
 * devices did here. The status itself lives in the header pinned over the
 * conversation (`MuseHeader`); this file keeps the frame-wide overlay entry
 * that shows the notices (`notify`, and each remote `call` that ran here).
 */
import { relaunchHands } from './RelaunchButton.tsx'
import { Button, Toast } from '@deepseek-ai/dsh-client-ui-primitives'
import { createElement as h, useEffect, useState, type ReactNode } from 'react'
import type { Translate } from './api.ts'
import { call } from './api.ts'
import { useLive, type LiveAsk, type LiveCall, type LiveNotice } from './live.ts'
import type { Words } from './locales.ts'
import { bridge } from './bridge.ts'
import { BlackScreenNotice, type BlackScreenPerms } from './HandsCheck.tsx'

/** What a call is, in the person's words. */
export function describeCall(t: Translate, c: LiveCall): string {
  const a = c.args
  const device = a.device || t('otherDevice')
  if (c.name === 'mcp__nanomuse__computer_screen') return t('handsLooking')
  if (c.name === 'mcp__nanomuse__computer_act') {
    const action = (a.action ?? '').toLowerCase()
    if (action === 'click' || action === 'tap' || action === 'double_click' || action === 'right_click') return a.label ? t('handsClick', { label: a.label }) : t('handsClickSomewhere')
    if (action === 'type' || action === 'text') return t('handsType', { text: a.text ?? '' })
    if (action === 'scroll' || action === 'swipe') return t('handsScroll')
    if (action === 'key' || action === 'hotkey' || action === 'press') return t('handsKey', { text: a.text ?? a.label ?? '' })
    if (action === 'wait') return t('handsWait')
    return a.label ? t('handsClick', { label: a.label }) : t('handsAct', { action: a.action ?? '' })
  }
  if (c.name === 'device_screen') return t('reachScreen', { device })
  if (c.name === 'device_shell') return t('reachShell', { device, command: a.command ?? '' })
  if (c.name === 'device_files') return t('reachFiles', { device })
  if (c.name === 'device_open') return t('reachOpen', { device })
  if (c.name === 'device_notify') return t('reachNotify', { device })
  if (c.name === 'delegate') return t('reachDelegate', { device })
  if (c.name === 'devices') return t('reachDevices')
  return c.name
}

/** The toast line for something another device did here. */
function callKey(action: string | undefined): Words {
  switch (action) {
    case 'shell':
      return 'incomingShell'
    case 'file.get':
      return 'incomingFileGet'
    case 'file.put':
      return 'incomingFilePut'
    case 'open':
      return 'incomingOpen'
    case 'screen':
      return 'incomingScreen'
    case 'task':
      return 'incomingTask'
    default:
      return 'incomingOther'
  }
}

export interface CapsuleProps {
  t: Translate
}

/** The overlay entry: the newest notice from another device, once each, and the questions other devices are waiting on. */
export function makeCapsule({ t }: CapsuleProps) {
  return function Capsule(): ReactNode {
    const live = useLive()
    return h('div', { style: { position: 'fixed', top: 10, left: '50%', transform: 'translateX(-50%)', zIndex: 60, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, pointerEvents: 'none' } },
      h(BlackScreenCard, { t }),
      live.hub.asks.map((ask) => h(AskCard, { key: ask.id, t, ask })),
      h(Notices, { t, notices: live.notices }))
  }
}

/** The hands saw a black screen (desk-b): the one notice that must not be missed, with the relaunch right in it. Read from the live state, so nothing polls while all is well. */
function BlackScreenCard({ t }: { t: Translate }): ReactNode {
  const live = useLive()
  const shown = live.blackScreenAt > 0
  // whether the helper app holds the grants (macOS, 0.1.38): asked once per notice, so the
  // button says the helper is restarted rather than the whole app
  const [helper, setHelper] = useState(false)
  useEffect(() => {
    if (!shown) return undefined
    let on = true
    void bridge()?.permissions().then((p) => { if (on) setHelper(p.helper === true) }).catch(() => undefined)
    return () => { on = false }
  }, [shown])
  if (!shown) return null
  const perms: BlackScreenPerms = {
    blackScreen: true,
    helper,
    relaunch: relaunchHands,
    clearBlackScreen: () => void call('hands/black-screen/clear', {}).catch(() => undefined),
  }
  return h('div', { style: { pointerEvents: 'auto' } }, h(BlackScreenNotice, { t, perms }))
}

/** The words for what another device wants to do here. */
export function askKey(action: string): Words {
  switch (action) {
    case 'shell':
      return 'askShell'
    case 'files':
      return 'askFiles'
    case 'file.get':
      return 'askFileGet'
    case 'file.put':
      return 'askFilePut'
    case 'open':
      return 'askOpen'
    case 'screen':
      return 'askScreen'
    case 'task':
      return 'askTask'
    case 'coding.send':
      return 'cdAskSend'
    case 'coding.stop':
      return 'cdAskStop'
    default:
      return 'askOther'
  }
}

/** One question from another device: allow once, always for that device, or not now. */
function AskCard({ t, ask }: { t: Translate; ask: LiveAsk }): ReactNode {
  const [busy, setBusy] = useState(false)
  const answer = (a: 'once' | 'always' | 'deny') => {
    setBusy(true)
    void call('devices/answer', { id: ask.id, answer: a }).catch(() => undefined).finally(() => setBusy(false))
  }
  return h('div', { className: 'nm-ask', role: 'dialog', 'aria-live': 'assertive', style: { pointerEvents: 'auto' } },
    h('div', { className: 'nm-ask-title' }, t('askTitle', { from: ask.from })),
    h('div', { className: 'nm-ask-text' }, t(askKey(ask.action), { from: ask.from, what: ask.text })),
    h('div', { className: 'nm-ask-actions' },
      h(Button, { variant: 'primary', size: 'sm', disabled: busy, onClick: () => answer('once') }, t('askAllowOnce')),
      h(Button, { variant: 'outline', size: 'sm', disabled: busy, onClick: () => answer('always') }, t('askAlways', { from: ask.from })),
      h(Button, { variant: 'ghost', size: 'sm', disabled: busy, onClick: () => answer('deny') }, t('askDeny'))),
    h('div', { className: 'nm-ask-sub' }, t('askHint')))
}

function Notices({ t, notices }: { t: Translate; notices: LiveNotice[] }): ReactNode {
  const [seen, setSeen] = useState(0)
  const latest = notices[notices.length - 1]
  if (!latest || latest.id <= seen) return null
  const text =
    latest.kind === 'call'
      ? t(callKey(latest.action), { from: latest.from, what: latest.text })
      : `${latest.from}${latest.title ? ` · ${latest.title}` : ''}: ${latest.text}`
  return h(Toast, {
    key: latest.id,
    text,
    holdMs: 6000,
    onDone: () => {
      setSeen(latest.id)
      if (latest.id === notices[notices.length - 1]?.id) void call('notices/clear', {}).catch(() => undefined)
    },
  })
}
