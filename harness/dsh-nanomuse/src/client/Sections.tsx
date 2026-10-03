/**
 * The settings pages the Muse desktop has and the harness does not: Computer
 * use (the system permissions the hands need, with the way to the System
 * Settings panes, and the screen-awake switch), Help & support (the places to
 * read and to report) and Legal (the licences, the Meta disclaimer, the
 * acknowledgements, the policies). Plus the Developer rows the General page
 * ends with: the switch that brings the harness's own controls back.
 */
import { createElement as h, Fragment, useCallback, useEffect, useState, type ReactNode } from 'react'
import type { Translate } from './api.ts'
import { acceleratorOf, bridge, gatedPermissions, keyLabel, openLink, type DesktopPrefs, type PermissionKind, type PermissionState } from './bridge.ts'
import { settingsBus } from './bus.ts'
import { IconBug, IconCheck, IconChevronRight, IconFile, IconLink, IconPlay, IconScale, IconShield } from './icons.tsx'
import { useLive } from './live.ts'
import { ISSUES_URL } from './panels.ts'
import { setPrefs, usePrefs } from './prefs.ts'

const SITE_URL = 'https://nanomuse.cn/'
const DOCS_URL = 'https://github.com/nano-muse/nanoMuse/blob/main/docs/harness.md'
const DISCUSS_URL = 'https://github.com/nano-muse/nanoMuse/discussions'
const PRIVACY_URL = 'https://github.com/nano-muse/nanoMuse/blob/main/docs/privacy.md'
const TERMS_URL = 'https://github.com/nano-muse/nanoMuse/blob/main/docs/terms.md'
const LICENSE_URL = 'https://github.com/nano-muse/nanoMuse/blob/main/LICENSE'

function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange(next: boolean): void; label: string; disabled?: boolean }): ReactNode {
  return h('button', { type: 'button', role: 'switch', className: 'nm-switch', 'aria-checked': checked, 'aria-label': label, disabled, onClick: () => onChange(!checked) })
}

function LinkRow({ icon, title, sub, onClick }: { icon: ReactNode; title: string; sub?: string; onClick(): void }): ReactNode {
  return h('button', { type: 'button', className: 'nm-row-link', onClick },
    h('span', { className: 'nm-row-icon' }, icon),
    h('span', { className: 'nm-row-main' },
      h('span', { className: 'nm-row-title' }, title),
      sub ? h('span', { className: 'nm-row-sub' }, sub) : null),
    h(IconChevronRight, { size: 16, className: 'nm-row-chevron' }))
}

export function makeComputerSection(t: Translate) {
  return function ComputerSection(): ReactNode {
    const live = useLive()
    const prefs = usePrefs()
    const name = live.profile.name || t('brand')
    const gated = gatedPermissions()
    const [states, setStates] = useState<Partial<Record<PermissionKind, PermissionState>>>({})
    const refresh = useCallback(() => {
      void bridge()?.permissions().then(setStates).catch(() => undefined)
    }, [])
    useEffect(() => {
      if (!gated) return undefined
      refresh()
      const timer = window.setInterval(refresh, 2000)
      return () => window.clearInterval(timer)
    }, [gated, refresh])
    const row = (kind: PermissionKind, title: string, sub: string) => {
      const granted = states[kind] === 'granted'
      return h('div', { key: kind, className: 'nm-row' },
        h('div', { className: 'nm-row-main' },
          h('span', { className: 'nm-row-title' }, title),
          h('span', { className: 'nm-row-sub' }, sub)),
        granted
          ? h('span', { className: 'nm-ob-granted', 'aria-label': t('obAllowed') }, h(IconCheck, { size: 16 }))
          : h('button', { type: 'button', className: 'nm-pill nm-pill-sm', onClick: () => { void bridge()?.requestPermission(kind).then(() => refresh()) } }, t('obAllow')))
    }
    return h('div', { className: 'nm-section' },
      h('p', null, t('cuLead', { name })),
      h('h2', null, t('cuPermissions')),
      gated
        ? h('div', { className: 'nm-card' },
            row('accessibility', t('obAccessibility'), t('obAccessibilitySub')),
            row('screen', t('obScreen'), t('obScreenSub')),
            h('div', { className: 'nm-row', style: { gap: 12, flexWrap: 'wrap' } },
              h('button', { type: 'button', className: 'nm-ob-link', style: { padding: 0 }, onClick: () => { void bridge()?.openPermissionSettings('accessibility') } }, t('cuOpenSettingsAccessibility')),
              h('button', { type: 'button', className: 'nm-ob-link', style: { padding: 0 }, onClick: () => { void bridge()?.openPermissionSettings('screen') } }, t('cuOpenSettingsScreen'))))
        : h('p', null, t('cuNotGated')),
      h('div', { className: 'nm-card' },
        h('div', { className: 'nm-row' },
          h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cuAwake'))),
          h(Switch, { checked: prefs.keepAwake, label: t('cuAwake'), disabled: bridge() === undefined, onChange: (next) => setPrefs({ keepAwake: next }) })),
        h('div', { className: 'nm-row' },
          h('span', { className: 'nm-row-icon' }, h(IconShield, { size: 18 })),
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('cuRisk')),
            h('span', { className: 'nm-row-sub nm-wrap' }, t('cuRiskNote'))))))
  }
}

export function makeHelpSection(t: Translate, version: string) {
  return function HelpSection(): ReactNode {
    return h('div', { className: 'nm-section' },
      h('div', { className: 'nm-card' },
        h(LinkRow, { icon: h(IconFile, { size: 18 }), title: t('helpDocs'), onClick: () => openLink(DOCS_URL) }),
        h(LinkRow, { icon: h(IconLink, { size: 18 }), title: t('helpSite'), sub: 'nanomuse.cn', onClick: () => openLink(SITE_URL) }),
        h(LinkRow, { icon: h(IconLink, { size: 18 }), title: t('helpDiscuss'), onClick: () => openLink(DISCUSS_URL) }),
        h(LinkRow, { icon: h(IconBug, { size: 18 }), title: t('helpIssue'), onClick: () => openLink(ISSUES_URL) })),
      h('div', { className: 'nm-card' },
        h(LinkRow, { icon: h(IconPlay, { size: 18 }), title: t('helpFirstRun'), sub: t('helpFirstRunSub'), onClick: () => { settingsBus.openOnboarding?.('deepseek-official') } }),
        h('div', { className: 'nm-row' },
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('helpVersion')),
            h('span', { className: 'nm-row-sub' }, t('versionLine', { version }))))))
  }
}

export function makeLegalSection(t: Translate) {
  return function LegalSection(): ReactNode {
    return h('div', { className: 'nm-section' },
      h('div', { className: 'nm-card' },
        h('div', { className: 'nm-row' },
          h('span', { className: 'nm-row-icon' }, h(IconScale, { size: 18 })),
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('legalLicense')),
            h('span', { className: 'nm-row-sub nm-wrap' }, t('legalLicenseText')))),
        h('div', { className: 'nm-row' },
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('legalMeta')),
            h('span', { className: 'nm-row-sub nm-wrap' }, t('legalMetaText')))),
        h('div', { className: 'nm-row' },
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('legalThanks')),
            h('span', { className: 'nm-row-sub nm-wrap' }, t('legalThanksText'))))),
      h('div', { className: 'nm-card' },
        h(LinkRow, { icon: h(IconFile, { size: 18 }), title: t('legalPrivacy'), onClick: () => openLink(PRIVACY_URL) }),
        h(LinkRow, { icon: h(IconFile, { size: 18 }), title: t('legalTerms'), onClick: () => openLink(TERMS_URL) }),
        h(LinkRow, { icon: h(IconScale, { size: 18 }), title: 'GPL-3.0-or-later', onClick: () => openLink(LICENSE_URL) })))
  }
}

/** The Developer rows at the end of General: the harness's own controls, on request. */
export function DeveloperRows({ t }: { t: Translate }): ReactNode {
  const prefs = usePrefs()
  return h('div', { className: 'nm-card', style: { marginTop: 14 } },
    h('div', { className: 'nm-row' },
      h('div', { className: 'nm-row-main' },
        h('span', { className: 'nm-row-title' }, t('stDeveloper')),
        h('span', { className: 'nm-row-sub nm-wrap' }, t('stShowHarness'))),
      h(Switch, { checked: prefs.showHarness, label: t('stShowHarness'), onChange: (next) => setPrefs({ showHarness: next }) })))
}

/** The shell's app-behaviour values, shared by every row that shows them; nothing outside the shell. */
let desktopPrefsCache: DesktopPrefs | undefined
const desktopPrefsListeners = new Set<(p: DesktopPrefs) => void>()
function publishDesktopPrefs(p: DesktopPrefs): void {
  desktopPrefsCache = p
  for (const l of desktopPrefsListeners) l(p)
}
export function useDesktopPrefs(): { prefs: DesktopPrefs | undefined; set: (patch: Partial<Pick<DesktopPrefs, 'openAtLogin' | 'menuBar' | 'quickChat' | 'quickChatKey'>>) => void } {
  const b = bridge()
  const [prefs, setLocal] = useState<DesktopPrefs | undefined>(desktopPrefsCache)
  useEffect(() => {
    desktopPrefsListeners.add(setLocal)
    void b?.prefs?.().then(publishDesktopPrefs).catch(() => undefined)
    return () => { desktopPrefsListeners.delete(setLocal) }
  }, [b])
  const set = useCallback((patch: Partial<Pick<DesktopPrefs, 'openAtLogin' | 'menuBar' | 'quickChat' | 'quickChatKey'>>) => {
    if (desktopPrefsCache) publishDesktopPrefs({ ...desktopPrefsCache, ...patch })
    void b?.setPrefs?.(patch).then(publishDesktopPrefs).catch(() => undefined)
  }, [b])
  return { prefs: b?.prefs ? prefs : undefined, set }
}

/**
 * The quick-chat combination, as Muse's Shortcuts page has it: the keys, *Change* (press the
 * new combination, Esc to cancel), *Default* when it is the person's own, and a word when
 * another app holds it. Outside the shell, the platform's default as plain text.
 */
export function HotkeyField({ t }: { t: Translate }): ReactNode {
  const b = bridge()
  const { prefs, set } = useDesktopPrefs()
  const [recording, setRecording] = useState(false)
  const [hint, setHint] = useState<string | undefined>()
  const platform = b?.platform ?? ''
  const fallback = platform === 'darwin' ? 'Alt+Space' : 'Ctrl+Alt+Space'
  const key = prefs?.quickChatKey ?? fallback
  const canChange = Boolean(prefs && prefs.quickChatDefault !== undefined)
  const onKeyDown = (e: { code: string; key: string; ctrlKey: boolean; altKey: boolean; shiftKey: boolean; metaKey: boolean; preventDefault(): void; stopPropagation(): void }) => {
    if (!recording) return
    e.preventDefault()
    e.stopPropagation()
    if (e.key === 'Escape') { setRecording(false); setHint(undefined); return }
    if (['Control', 'Alt', 'Shift', 'Meta', 'AltGraph', 'OS'].includes(e.key)) return
    const next = acceleratorOf(e, platform)
    if (!next) { setHint(t('gnHotkeyNeedsModifier')); return }
    set({ quickChatKey: next })
    setRecording(false)
    setHint(undefined)
  }
  return h('div', { className: 'nm-hotkey' },
    h('div', { className: 'nm-hotkey-row' },
      recording
        ? h('button', { type: 'button', className: 'nm-kbd nm-hotkey-recording', autoFocus: true, onKeyDown, onBlur: () => { setRecording(false); setHint(undefined) }, 'aria-live': 'polite' }, t('gnHotkeyRecording'))
        : h('span', { className: 'nm-kbd' }, keyLabel(key, platform)),
      canChange && !recording ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => setRecording(true) }, t('gnHotkeyChange')) : null,
      canChange && !recording && prefs && prefs.quickChatDefault && key !== prefs.quickChatDefault ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => set({ quickChatKey: '' }) }, t('gnHotkeyReset')) : null),
    hint ? h('span', { className: 'nm-hotkey-hint' }, hint) : prefs?.quickChatTaken && prefs.quickChat ? h('span', { className: 'nm-hotkey-hint nm-cn-warn' }, t('gnHotkeyTaken')) : null)
}

/** Muse's App behavior: open at login, the menu bar icon, the quick-chat key — the shell's switches, when there is a shell. */
export function AppBehaviorRows({ t }: { t: Translate }): ReactNode {
  const b = bridge()
  const { prefs, set } = useDesktopPrefs()
  if (!b?.prefs || !prefs) return null
  const row = (key: 'openAtLogin' | 'menuBar' | 'quickChat', title: string, sub: string) =>
    prefs.supports[key]
      ? h('div', { key, className: 'nm-row' },
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, title),
            h('span', { className: 'nm-row-sub nm-wrap' }, sub)),
          h(Switch, { checked: prefs[key], label: title, onChange: (next) => set({ [key]: next }) }))
      : null
  return h('div', { className: 'nm-section nm-section-inline' },
    h('h2', null, t('abTitle')),
    h('div', { className: 'nm-card' },
    row('openAtLogin', t('abOpenAtLogin'), t('abOpenAtLoginSub')),
    row('menuBar', b.platform === 'darwin' ? t('abMenuBar') : t('abTray'), t('abMenuBarSub')),
    row('quickChat', t('abQuickChat', { key: keyLabel(prefs.quickChatKey, b.platform) }), t('abQuickChatSub'))))
}

// ---- Wallet, Secure storage, Channels: Muse's pages, with what is true here ----------

/**
 * Wallet. Muse keeps payment methods here; nanoMuse pays for nothing on the person's
 * behalf, and says so — the page explains what happens when something costs money, and
 * points at the usage quota that *is* an account balance of sorts.
 */
export function makeWalletSection(t: Translate, openSection: (id: string) => void) {
  return function WalletSection(): ReactNode {
    return h('div', { className: 'nm-section' },
      h('p', null, t('wlLead')),
      h('h2', null, t('wlMethods')),
      h('div', { className: 'nm-card' },
        h('div', { className: 'nm-row' },
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('wlNone')),
            h('span', { className: 'nm-row-sub nm-wrap' }, t('wlNoneSub'))))),
      h('h2', null, t('wlHow')),
      h('div', { className: 'nm-card' },
        h('div', { className: 'nm-row' },
          h('span', { className: 'nm-row-icon' }, h(IconShield, { size: 18 })),
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('wlAsks')),
            h('span', { className: 'nm-row-sub nm-wrap' }, t('wlAsksSub')))),
        h(LinkRow, { icon: h(IconLink, { size: 18 }), title: t('wlUsage'), sub: t('wlUsageSub'), onClick: () => openSection('general') })),
      h('p', { className: 'nm-fine' }, t('wlFine')))
  }
}

interface Folders { home: string; library: string; downloads: string; state: string }

/**
 * Secure storage: what nanoMuse keeps that is secret or personal, and where — files on this
 * machine readable by this user alone (mode 0600), nothing in the system keychain. Each row
 * says what it is; the folder opens in the file manager.
 */
export function makeStorageSection(t: Translate, loadFolders: () => Promise<Folders>, reveal: (which: keyof Folders) => void) {
  return function StorageSection(): ReactNode {
    const live = useLive()
    const [folders, setFolders] = useState<Folders | undefined>()
    useEffect(() => { void loadFolders().then(setFolders).catch(() => undefined) }, [])
    const entry = (title: string, sub: string, file: string) =>
      h('div', { className: 'nm-row' },
        h('span', { className: 'nm-row-icon' }, h(IconFile, { size: 18 })),
        h('div', { className: 'nm-row-main' },
          h('span', { className: 'nm-row-title' }, title),
          h('span', { className: 'nm-row-sub nm-wrap' }, sub, folders ? h('span', { className: 'nm-path' }, `${folders.state}/${file}`) : null)))
    return h('div', { className: 'nm-section' },
      h('p', null, t('ssLead')),
      h('h2', null, t('ssKept')),
      h('div', { className: 'nm-card' },
        entry(t('ssAccount'), live.cloud.signedIn ? t('ssAccountSub', { hint: live.cloud.hint }) : t('ssAccountOut'), 'cloud.json'),
        entry(t('ssProfile'), t('ssProfileSub'), 'profile.json'),
        entry(t('ssRooms'), t('ssRoomsSub'), 'rooms.json'),
        entry(t('ssFaces'), t('ssFacesSub'), 'faces/')),
      h('div', { className: 'nm-card' },
        h(LinkRow, { icon: h(IconLink, { size: 18 }), title: t('ssReveal'), sub: folders?.state ?? '', onClick: () => reveal('state') })),
      h('h2', null, t('ssNotKept')),
      h('div', { className: 'nm-card' },
        h('div', { className: 'nm-row' },
          h('span', { className: 'nm-row-icon' }, h(IconShield, { size: 18 })),
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('ssKeychain')),
            h('span', { className: 'nm-row-sub nm-wrap' }, t('ssKeychainSub')))),
        h('div', { className: 'nm-row' },
          h('span', { className: 'nm-row-icon' }, h(IconShield, { size: 18 })),
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('ssPasswords')),
            h('span', { className: 'nm-row-sub nm-wrap' }, t('ssPasswordsSub'))))),
      h('p', { className: 'nm-fine' }, t('ssFine')))
  }
}

/**
 * Message channels: the ways to reach the agent. Here that is this window, the invite
 * link (the chat from a phone's browser, signed in to the same account) and the other
 * devices on the account — no third-party messengers, and the page says so.
 */
export function makeChannelsSection(t: Translate, openSection: (id: string) => void, devicesSection: string) {
  return function ChannelsSection(): ReactNode {
    const live = useLive()
    const others = live.hub.devices.filter((d) => d.kind !== 'web')
    const b = bridge()
    return h('div', { className: 'nm-section' },
      h('p', null, t('mcLead')),
      h('h2', null, t('mcConnected')),
      h('div', { className: 'nm-card' },
        h('div', { className: 'nm-row' },
          h('span', { className: 'nm-row-icon' }, h(IconCheck, { size: 18 })),
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, b ? t('mcDesktop') : t('mcBrowser')),
            h('span', { className: 'nm-row-sub nm-wrap' }, t('mcDesktopSub'))),
          h('span', { className: 'nm-state nm-state-on' }, t('cnOn'))),
        h('div', { className: 'nm-row' },
          h('span', { className: 'nm-row-icon' }, h(IconLink, { size: 18 })),
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('mcInvite')),
            h('span', { className: 'nm-row-sub nm-wrap' }, live.cloud.signedIn ? t('mcInviteSub') : t('mcInviteOut'))),
          h('span', { className: live.cloud.signedIn ? 'nm-state nm-state-on' : 'nm-state' }, live.cloud.signedIn ? t('cnOn') : t('cnOff'))),
        h(LinkRow, { icon: h(IconLink, { size: 18 }), title: t('mcDevices'), sub: others.length ? t('mcDevicesSub', { n: others.length }) : t('mcDevicesNone'), onClick: () => openSection(devicesSection) })),
      h('h2', null, t('mcOthers')),
      h('div', { className: 'nm-card' },
        h('div', { className: 'nm-row' },
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('mcNoThirdParty')),
            h('span', { className: 'nm-row-sub nm-wrap' }, t('mcNoThirdPartySub'))))),
      h('p', { className: 'nm-fine' }, t('mcFine')))
  }
}
