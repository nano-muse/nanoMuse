/**
 * The Network row on the nanoMuse Cloud page: one proxy for the model providers, kept by the
 * Electron shell (its `desktop.json`, next to *open at login*) and put on the dsh Host's
 * environment at the next start, where Node's fetch and the hands' runtime read it. Only the
 * providers go through it. The shell derives NO_PROXY from its trusted launch configuration,
 * never from this renderer. Outside the shell, or under a shell older than 0.1.41, the row is
 * not drawn.
 */
import { createElement as h, useState, type FormEvent, type ReactNode } from 'react'
import type { Translate } from './api.ts'
import { bridge } from './bridge.ts'
import { IconGlobe } from './icons.tsx'
import { useDesktopPrefs } from './Sections.tsx'

/** The schemes the shell takes (harness/desktop/src/proxy.ts has the same list and the same rule). */
const SCHEMES = ['http', 'https', 'socks5', 'socks5h']

/** The address the shell would keep for `text`, or undefined when it would refuse it: one of the four schemes, a host, nothing else. */
export function proxyAddress(text: string): string | undefined {
  const raw = text.trim()
  if (!raw) return undefined
  let url: URL
  try {
    url = new URL(raw)
  } catch {
    return undefined
  }
  const scheme = url.protocol.replace(/:$/, '')
  if (!SCHEMES.includes(scheme) || !url.hostname) return undefined
  if (url.search || url.hash || (url.pathname && url.pathname !== '/')) return undefined
  return url.href.replace(/\/+$/, '')
}

export function NetworkRows({ t }: { t: Translate }): ReactNode {
  const b = bridge()
  const { prefs, set } = useDesktopPrefs()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [bad, setBad] = useState(false)
  const proxy = prefs?.proxy
  if (!b?.prefs || !prefs || proxy === undefined) return null
  const pending = prefs.proxyApplied !== undefined && prefs.proxyApplied !== proxy
  const begin = () => { setDraft(proxy); setBad(false); setEditing(true) }
  const save = (e?: FormEvent) => {
    e?.preventDefault()
    const url = proxyAddress(draft)
    if (!url && draft.trim()) { setBad(true); return }
    set({ proxy: url ?? '' })
    setEditing(false)
  }
  const remove = () => { set({ proxy: '' }); setEditing(false) }
  return h('div', { className: 'nm-section nm-section-inline' },
    h('h2', null, t('nwTitle')),
    h('div', { className: 'nm-card' },
      editing
        ? h('form', { className: 'nm-row', style: { flexDirection: 'column', alignItems: 'stretch', gap: 8 }, onSubmit: save },
            h('span', { className: 'nm-row-title' }, t('nwProxy')),
            h('input', { className: 'nm-field', type: 'text', value: draft, placeholder: t('nwProxyPlaceholder'), autoFocus: true, spellCheck: false, autoCapitalize: 'off', autoCorrect: 'off', 'aria-label': t('nwProxy'), 'aria-invalid': bad, onChange: (e: FormEvent<HTMLInputElement>) => { setDraft(e.currentTarget.value); setBad(false) } }),
            bad ? h('span', { className: 'nm-row-sub nm-wrap nm-cn-warn', role: 'alert' }, t('nwProxyBad')) : null,
            h('div', { style: { display: 'flex', gap: 8 } },
              h('button', { type: 'submit', className: 'nm-pill nm-pill-sm' }, t('save')),
              h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => { setEditing(false); setBad(false) } }, t('cancel'))))
        : h('div', { className: 'nm-row' },
            h('span', { className: 'nm-row-icon' }, h(IconGlobe, { size: 18 })),
            h('div', { className: 'nm-row-main' },
              h('span', { className: 'nm-row-title' }, t('nwProxy')),
              // the address as kept, `user:pass@` hidden — a screenshot of this page carries no password
              h('span', { className: 'nm-row-sub nm-wrap' }, proxy ? h('code', null, prefs.proxyMasked || proxy) : t('nwProxyNone'))),
            h('div', { style: { display: 'flex', gap: 8, flexShrink: 0 } },
              h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: begin }, t('nwProxyChange')),
              proxy ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: remove }, t('nwProxyRemove')) : null)),
      pending
        ? h('div', { className: 'nm-row' },
            h('span', { className: 'nm-row-sub nm-wrap', role: 'status' }, t('nwProxyPending')),
            b.restartHost ? h('button', { type: 'button', className: 'nm-pill nm-pill-sm', style: { flexShrink: 0 }, onClick: () => { void b.restartHost?.() } }, t('nwProxyRestart')) : null)
        : null,
      h('div', { className: 'nm-row' }, h('span', { className: 'nm-row-sub nm-wrap' }, t('nwProxyHelp')))))
}
