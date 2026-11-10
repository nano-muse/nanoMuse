/**
 * The Devices page in the harness's `main` seat (the rail's fourth icon) and under
 * Settings → Devices: the account's devices as a settings page. A line on what they are
 * for and a quiet count; **this computer** as a card — its glyph, its name (renamed in
 * place), the hub state and OS line, what it can do as chips, the remote-control switch and
 * the devices allowed without asking; then **the other devices** as a grid of the same cards
 * ("Online · just now" / "Last seen 2 h ago", an `@name` hint for the ones that take tasks,
 * *Forget* behind the dots); only this computer: a card on how to add one. The Computer-use
 * rows (the hands, their permissions) stay in Settings → Computer use. There is no "cloud
 * computer" section — we have none.
 */
import { Button, Input, Switch } from '@deepseek-ai/dsh-client-ui-primitives'
import { createElement as h, useState, type FormEvent, type ReactNode } from 'react'
import { call, errorStyle, type Translate, failureText } from './api.ts'
import { openLink } from './bridge.ts'
import { settingsBus } from './bus.ts'
import { CODING_SECTION, codingNav } from './CodingPanel.tsx'
import { IconDevices, IconGlobe, IconLaptop, IconPencil, IconPhone, IconRefresh } from './icons.tsx'
import { useLive, type LiveDevice } from './live.ts'
import { MoreButton } from './ui.tsx'
import { DeviceConversationPanel } from './DeviceConversationPanel.tsx'

const DOWNLOAD_URL = 'https://nanomuse.cn/dl/'

function ago(t: Translate, seconds: number): string {
  if (!seconds) return ''
  const delta = Math.max(0, Date.now() / 1000 - seconds)
  if (delta < 90) return t('justNow')
  if (delta < 3600) return t('minutesAgo', { n: Math.round(delta / 60) })
  if (delta < 86400) return t('hoursAgo', { n: Math.round(delta / 3600) })
  return t('daysAgo', { n: Math.round(delta / 86400) })
}

/** "Online · just now" / "Last seen 2 h ago" / "Offline". An online device's `last_seen` is its last hello, which may be hours old: it is shown only while fresh. */
function presence(t: Translate, d: Pick<LiveDevice, 'online' | 'last_seen'>): string {
  if (d.online) return d.last_seen && Date.now() / 1000 - d.last_seen < 120 ? `${t('deviceOnline')} · ${t('justNow')}` : t('deviceOnline')
  return d.last_seen ? t('deviceLastSeen', { when: ago(t, d.last_seen) }) : t('deviceOffline')
}

/** What a device can do, from the hub actions it announces — our names, in a fixed order. */
export function capabilities(t: Translate, actions: readonly string[]): string[] {
  const set = new Set(actions)
  const out: string[] = []
  if (set.has('task')) out.push(t('capTasks'))
  if (set.has('shell')) out.push(t('capCommands'))
  if (set.has('files') || set.has('file.get') || set.has('file.put')) out.push(t('capFiles'))
  if (set.has('screen')) out.push(t('capScreenshot'))
  if (set.has('open')) out.push(t('capOpen'))
  if ([...set].some((a) => a.startsWith('coding.'))) out.push(t('capCoding'))
  if (set.has('notify')) out.push(t('capNotify'))
  return out
}

/** The platform glyph on its tile: phone, computer, browser. */
function Glyph({ kind, online }: { kind: string; online: boolean }): ReactNode {
  const Icon = kind === 'phone' ? IconPhone : kind === 'web' ? IconGlobe : kind === 'computer' ? IconLaptop : IconDevices
  return h('span', { className: `nm-dv-glyph${online ? ' nm-on' : ''}`, 'aria-hidden': true }, h(Icon, { size: 22 }))
}

function Dot({ on }: { on: boolean }): ReactNode {
  return h('span', { className: `nm-status-dot${on ? ' nm-on' : ''}`, style: { display: 'inline-block', verticalAlign: 'middle' } })
}

/** The capability chips; the *Coding agents* one opens Settings → Coding agents on that computer (`onCoding`). */
function Chips({ items, coding, onCoding }: { items: string[]; coding?: string; onCoding?: () => void }): ReactNode {
  if (items.length === 0) return null
  return h('div', { className: 'nm-dv-chips' }, items.map((c) =>
    c === coding && onCoding
      ? h('button', { key: c, type: 'button', className: 'nm-dv-chip nm-dv-chip-button', onClick: onCoding }, c)
      : h('span', { key: c, className: 'nm-dv-chip' }, c)))
}

/** Settings → Coding agents, looking at `deviceId` ('' = this computer). */
function openCoding(deviceId: string): void {
  codingNav.device = deviceId || undefined
  settingsBus.openSection?.(CODING_SECTION)
}

/** OS · version, whichever the relay knows. */
function osLine(d: Pick<LiveDevice, 'os' | 'version'> | undefined): string {
  return d ? [d.os, d.version].filter(Boolean).join(' · ') : ''
}

export function makeDevicesPanel(t: Translate) {
  return function DevicesPanel(): ReactNode {
    const live = useLive()
    const hub = live.hub
    const [renaming, setRenaming] = useState(false)
    const [name, setName] = useState(hub.deviceName)
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState<string | undefined>()
    const self = hub.devices.find((d) => d.id === hub.deviceId)
    const others = hub.devices.filter((d) => d.id !== hub.deviceId && d.kind !== 'web')
    const signedIn = live.cloud.signedIn

    const run = (work: () => Promise<unknown>) => {
      setBusy(true)
      setError(undefined)
      work().catch((err: unknown) => setError(failureText(t, err))).finally(() => setBusy(false))
    }
    const rename = (event: FormEvent) => {
      event.preventDefault()
      run(() => call('devices/rename', { name }).then(() => setRenaming(false)))
    }

    const stateLine = !signedIn
      ? t('devicesSignedOut')
      : hub.connected ? t('deviceOnline') : (hub.lastError ? t('hubOffline', { reason: hub.lastError }) : t('hubConnecting'))
    // the count: this computer (once it is on the hub) and the others
    const total = others.length + (hub.connected ? 1 : 0)
    const online = others.filter((d) => d.online).length + (hub.connected ? 1 : 0)
    const ownActions = self?.actions ?? []

    return h('div', { className: 'nm-page nm-dv' },
      h('div', { className: 'nm-page-inner' },
        h('h1', null, t('railDevices')),
        h('div', { className: 'nm-dv-head' },
          h('p', { className: 'nm-lead' }, t('devicesLead')),
          signedIn && total > 0
            ? h('p', { className: 'nm-dv-count' }, total === 1 ? t('devicesCountOne', { online }) : t('devicesCount', { n: total, online }))
            : null),

        h('h2', null, t('thisComputer')),
        h('div', { className: 'nm-dv-card' },
          h('div', { className: 'nm-dv-top' },
            h(Glyph, { kind: 'computer', online: hub.connected }),
            h('div', { className: 'nm-dv-main' },
              renaming
                ? h('form', { className: 'nm-dv-rename', onSubmit: rename },
                    h(Input, { value: name, onChange: (e: FormEvent<HTMLInputElement>) => setName(e.currentTarget.value), maxLength: 60, autoFocus: true, 'aria-label': t('deviceName') }),
                    h(Button, { variant: 'primary', size: 'sm', type: 'submit', disabled: busy || !name.trim() }, t('save')),
                    h(Button, { variant: 'ghost', size: 'sm', type: 'button', onClick: () => setRenaming(false) }, t('cancel')))
                : h('div', { className: 'nm-dv-name-row' },
                    h('span', { className: 'nm-dv-name' }, hub.deviceName || t('thisComputer')),
                    h('button', { type: 'button', className: 'nm-icon-btn nm-icon-btn-sm', title: t('rename'), 'aria-label': t('rename'), onClick: () => { setName(hub.deviceName); setRenaming(true) } }, h(IconPencil, { size: 14 }))),
              h('span', { className: 'nm-dv-sub' }, h(Dot, { on: hub.connected }), ' ', [stateLine, osLine(self)].filter(Boolean).join(' · ')),
              h(Chips, { items: capabilities(t, ownActions), coding: t('capCoding'), onCoding: () => openCoding('') }))),
          h('div', { className: 'nm-dv-rows' },
            h('div', { className: 'nm-row' },
              h('div', { className: 'nm-row-main' },
                h('span', { className: 'nm-row-title' }, t('remoteControl')),
                h('span', { className: 'nm-row-sub nm-wrap' }, hub.remoteControl ? t('remoteControlOn') : t('remoteControlOff'))),
              h(Switch, { checked: hub.remoteControl, disabled: busy, label: t('remoteControl'), onChange: (on: boolean) => run(() => call('devices/remote-control', { on })) })),
            hub.remoteControl || hub.trusted.length === 0
              ? null
              : h('div', { className: 'nm-row', style: { flexDirection: 'column', alignItems: 'stretch', gap: 6 } },
                  h('span', { className: 'nm-row-sub' }, t('trustedDevices')),
                  ...hub.trusted.map((td) => h('div', { key: td.id, style: { display: 'flex', alignItems: 'center', gap: 8 } },
                    h('span', { className: 'nm-row-title', style: { flex: 1 } }, td.name),
                    h(Button, { variant: 'ghost', size: 'sm', disabled: busy, onClick: () => run(() => call('devices/trust', { device_id: td.id, on: false })) }, t('trustForget'))))))),

        h('h2', null, t('otherDevices')),
        others.length === 0
          ? h(EmptyDevices, { t, signedIn, connected: hub.connected })
          : h('div', { className: 'nm-dv-grid' },
              others.map((d) => h(DeviceCard, { key: d.id, t, device: d, busy, onForget: () => run(() => call('devices/forget', { device_id: d.id })) }))),
        signedIn ? h(DeviceConversationPanel, { key: live.cloud.hint, t, devices: others }) : null,
        error ? h('div', { style: errorStyle }, error) : null,
        h('p', { className: 'nm-lead', style: { fontSize: 13 } }, t('devicesHint')),
        h('div', null,
          h(Button, { variant: 'outline', size: 'sm', disabled: busy, onClick: () => run(() => call('refresh', {})) }, h(IconRefresh, { size: 14 }), ' ', t('refresh')))))
  }
}

/** One of the other devices: the same anatomy; *Forget* behind the dots. */
function DeviceCard({ t, device: d, busy, onForget }: { t: Translate; device: LiveDevice; busy: boolean; onForget(): void }): ReactNode {
  const chips = capabilities(t, d.actions)
  // the hub's own verdict on reach, kept as a chip when the device said nothing finer
  if (chips.length === 0 && d.online) chips.push(d.controllable ? t('deviceReachable') : t('deviceNotReachable'))
  const takesTasks = d.online && d.actions.includes('task')
  return h('div', { className: 'nm-dv-card' },
    h('div', { className: 'nm-dv-top' },
      h(Glyph, { kind: d.kind, online: d.online }),
      h('div', { className: 'nm-dv-main' },
        h('span', { className: 'nm-dv-name' }, d.name),
        // the glyph says phone or computer; the line says when and what it runs
        h('span', { className: 'nm-dv-sub', title: osLine(d) }, h(Dot, { on: d.online }), ' ', [presence(t, d), osLine(d)].filter(Boolean).join(' · ')),
        h(Chips, { items: chips, coding: t('capCoding'), ...(d.online && d.kind === 'computer' ? { onCoding: () => openCoding(d.id) } : {}) }),
        takesTasks ? h('span', { className: 'nm-dv-hint' }, t('deviceMentionHint', { name: d.name })) : null),
      h(MoreButton, { label: t('deviceMore', { name: d.name }), size: 28, items: [{ id: 'forget', label: t('forgetDevice'), danger: true, onSelect: () => { if (!busy) onForget() } }] })))
}

/** Only this computer: how to add a device; signed out or off the hub, why nothing is listed. */
function EmptyDevices({ t, signedIn, connected }: { t: Translate; signedIn: boolean; connected: boolean }): ReactNode {
  return h('div', { className: 'nm-dv-card' },
    h('div', { className: 'nm-dv-top' },
      h(Glyph, { kind: 'phone', online: false }),
      h('div', { className: 'nm-dv-main' },
        h('span', { className: 'nm-dv-name' }, signedIn && connected ? t('devicesAddTitle') : t('devicesNoneTitle')),
        h('span', { className: 'nm-dv-sub nm-wrap' }, signedIn ? (connected ? t('devicesNone') : t('hubConnecting')) : t('devicesSignedOut')),
        signedIn && connected
          ? h('div', null, h(Button, { variant: 'outline', size: 'sm', onClick: () => openLink(DOWNLOAD_URL) }, t('devicesGetApps')))
          : null)))
}
