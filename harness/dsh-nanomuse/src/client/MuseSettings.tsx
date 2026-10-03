/**
 * The settings dialog, shaped like the Muse desktop's: a grouped nav on the
 * left — the everyday pages first (General, Account, Models, Agents,
 * Devices), then an *Advanced* group with every page the harness's other
 * plugins add — and the page on the right. It occupies `sidebar.settings`
 * (declared by our sidebar) and declares the `settings.*` seats the stock
 * shell declared, so every plugin's section, header action and onboarding
 * step lands as before; the General page is ours too and declares
 * `settings.general.item`, so the harness's own rows (permissions, language,
 * appearance, shortcuts…) mount in it. The onboarding coordinator mounts one
 * step while the main session is blank, as the stock shell did.
 */
import { useModalLayer } from '@deepseek-ai/dsh-client-ui-primitives'
import { createElement as h, Fragment, useCallback, useEffect, useId, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { call, type CloudStatus, type Translate } from './api.ts'
import { Avatar } from './Avatar.tsx'
import { openLink } from './bridge.ts'
import { settingsBus } from './bus.ts'
import { IconArchive, IconChevronRight, IconClose, IconCpu, IconDatabase, IconDevices, IconFolder, IconHand, IconHelp, IconKey, IconLink, IconLogOut, IconMessage, IconMic, IconPuzzle, IconScale, IconSettings, IconShield, IconSliders, IconSparkle, IconUser, IconWallet } from './icons.tsx'
import { openShortcutsReference } from './keys.ts'
import { useLive } from './live.ts'
import type { RenderSlot } from './MuseSidebar.tsx'
import { AppBehaviorRows, DeveloperRows, HotkeyField } from './Sections.tsx'

const SITE_URL = 'https://nanomuse.cn/'
const RELEASES_URL = 'https://github.com/nano-muse/nanoMuse/releases'

/** The pages that make up the everyday group, in Muse's order; the rest are Advanced. */
export const COMPUTER_SECTION = 'nanomuse-computer'
export const DATA_SECTION = 'nanomuse-data'
export const HELP_SECTION = 'nanomuse-help'
export const LEGAL_SECTION = 'nanomuse-legal'
export const WALLET_SECTION = 'nanomuse-wallet'
export const STORAGE_SECTION = 'nanomuse-storage'
export const CHANNELS_SECTION = 'nanomuse-channels'
export const HARNESS_SECTION = 'nanomuse-harness'
/** Muse's nav, in its order; the account page, models and presets are Advanced (the account card on General opens the first). */
const PRIMARY: readonly string[] = ['general', 'nanomuse-connectors', COMPUTER_SECTION, 'nanomuse-files', 'nanomuse-dictation', WALLET_SECTION, STORAGE_SECTION, 'nanomuse-permissions', CHANNELS_SECTION, 'nanomuse-devices', DATA_SECTION, HELP_SECTION, LEGAL_SECTION]

export interface SectionRow {
  id: string
  order: number
  label: string
}
export interface OnboardingStep {
  id: string
  order: number
}

/** Shell state: whether the dialog is open and which page shows. */
export interface ShellState {
  open: boolean
  activeId: string | undefined
}
export function createShellStore() {
  let state: ShellState = { open: false, activeId: undefined }
  const listeners = new Set<() => void>()
  const set = (next: ShellState) => { state = next; for (const l of listeners) l() }
  return {
    getSnapshot: () => state,
    subscribe: (l: () => void) => { listeners.add(l); return () => { listeners.delete(l) } },
    open: () => set({ ...state, open: true }),
    close: () => set({ open: false, activeId: undefined }),
    select: (id: string) => set({ ...state, activeId: id }),
    openSection: (id: string) => set({ open: true, activeId: id }),
    toggle: () => (state.open ? set({ open: false, activeId: undefined }) : set({ ...state, open: true })),
  }
}
export type ShellStore = ReturnType<typeof createShellStore>

/** The id our onboarding step is registered under (the shipped one, so the coordinator shows ours in that turn). */
const ONBOARDING_STEP = 'deepseek-official'

export interface MuseSettingsProps {
  t: Translate
  store: ShellStore
  renderSlot: RenderSlot
  useSections<S>(selector: (rows: readonly SectionRow[]) => S): S
  useOnboardingSteps<S>(selector: (rows: readonly OnboardingStep[]) => S): S
  /** The sessions store share, when the host passes it; without it onboarding runs once at boot. */
  useSessions?: (<S>(selector: (state: { phase: string; byId: Record<string, { blank: boolean; retainedBy: { mainView?: number } }> }) => S) => S) | undefined
}

function navIcon(id: string): ReactNode {
  switch (id) {
    case 'general': return h(IconSliders, { size: 16 })
    case 'nanomuse-cloud': return h(IconUser, { size: 16 })
    case 'models': return h(IconDatabase, { size: 16 })
    case 'agent-presets': return h(IconSparkle, { size: 16 })
    case 'nanomuse-devices': return h(IconDevices, { size: 16 })
    case COMPUTER_SECTION: return h(IconHand, { size: 16 })
    case 'nanomuse-connectors': return h(IconLink, { size: 16 })
    case 'nanomuse-files': return h(IconFolder, { size: 16 })
    case 'nanomuse-dictation': return h(IconMic, { size: 16 })
    case 'nanomuse-permissions': return h(IconShield, { size: 16 })
    case DATA_SECTION: return h(IconShield, { size: 16 })
    case WALLET_SECTION: return h(IconWallet, { size: 16 })
    case STORAGE_SECTION: return h(IconKey, { size: 16 })
    case CHANNELS_SECTION: return h(IconMessage, { size: 16 })
    case HARNESS_SECTION: return h(IconSliders, { size: 16 })
    case HELP_SECTION: return h(IconHelp, { size: 16 })
    case LEGAL_SECTION: return h(IconScale, { size: 16 })
    case 'plugins': return h(IconPuzzle, { size: 16 })
    case 'archived-sessions': return h(IconArchive, { size: 16 })
    case 'account': return h(IconCpu, { size: 16 })
    default: return h(IconSettings, { size: 16 })
  }
}

interface PanelProps {
  t: Translate
  rows: readonly SectionRow[]
  renderSlot: RenderSlot
  activeId: string | undefined
  onSelect(id: string): void
  onClose(): void
}

function SettingsPanel({ t, rows, renderSlot, activeId, onSelect, onClose }: PanelProps): ReactNode {
  const live = useLive()
  const [signingOut, setSigningOut] = useState(false)
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  useModalLayer(panel, true, onClose)

  const active = rows.find((r) => r.id === activeId)?.id ?? rows[0]?.id
  const primary = PRIMARY.map((id) => rows.find((r) => r.id === id)).filter((r): r is SectionRow => r !== undefined)
  const advanced = rows.filter((r) => !PRIMARY.includes(r.id))

  const cell = (row: SectionRow) => h('button', {
    key: row.id,
    type: 'button',
    className: `nm-settings-cell${row.id === active ? ' nm-active' : ''}`,
    'aria-current': row.id === active ? 'true' : undefined,
    'data-modal-autofocus': row.id === active ? '' : undefined,
    onClick: () => onSelect(row.id),
  }, navIcon(row.id), h('span', { className: 'nm-settings-cell-label' }, row.id === 'nanomuse-cloud' ? t('navAccount') : row.label))

  const [signOutError, setSignOutError] = useState<string | undefined>()
  const signOut = () => {
    setSigningOut(true)
    setSignOutError(undefined)
    void call('sign-out', {})
      .then(() => onClose())
      .catch((err: unknown) => setSignOutError(t('failed', { message: (err as Error).message })))
      .finally(() => setSigningOut(false))
  }

  return createPortal(
    h('div', { className: 'nm-settings-overlay', role: 'presentation' },
      h('div', { className: 'nm-settings-mask', 'aria-hidden': true, onClick: onClose }),
      h('div', { ref: panel, tabIndex: -1, className: 'nm-settings', role: 'dialog', 'aria-modal': true, 'aria-labelledby': titleId, 'data-shortcut-modal': 'settings' },
        h('nav', { className: 'nm-settings-nav' },
          h('div', { className: 'nm-settings-title', id: titleId, tabIndex: -1 }, renderSlot('settings.header', {}, { fallback: t('menuSettings') })),
          primary.map(cell),
          advanced.length > 0 ? h('div', { className: 'nm-settings-group' }, t('navAdvanced')) : null,
          advanced.map(cell),
          live.cloud.signedIn
            ? h('div', { className: 'nm-settings-foot' },
                h('button', { type: 'button', className: 'nm-settings-cell', disabled: signingOut, onClick: signOut },
                  h(IconLogOut, { size: 16 }), h('span', { className: 'nm-settings-cell-label' }, signingOut ? t('signingOut') : t('signOut'))),
                signOutError ? h('div', { className: 'nm-ob-error', role: 'alert', style: { padding: '4px 12px' } }, signOutError) : null)
            : null),
        h('div', { className: 'nm-settings-content' },
          h('div', { className: 'nm-settings-head' },
            renderSlot('settings.action', {}),
            h('button', { type: 'button', className: 'nm-close', onClick: onClose },
              h(IconClose, { size: 14 }),
              h('span', { className: 'nm-hidden' }, renderSlot('settings.close', {}, { fallback: t('close') })))),
          h('div', { className: 'nm-settings-body', key: active },
            active !== undefined ? renderSlot('settings.section', { close: onClose }, { only: active }) : null)))),
    document.body)
}

export function MuseSettings(props: MuseSettingsProps): ReactNode {
  const { t, store, renderSlot, useSections, useOnboardingSteps, useSessions } = props
  const { open, activeId } = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)
  const rows = useSections((s) => s)
  const steps = useOnboardingSteps((s) => s)
  const [requested, setRequested] = useState<string | undefined>()
  const [completed, setCompleted] = useState<ReadonlySet<string>>(() => new Set())

  // While mounted, the rail's menu and the header's face open the dialog through the bus.
  useEffect(() => {
    settingsBus.open = () => { store.open(); return true }
    settingsBus.openSection = (id) => { store.openSection(id); return true }
    return () => { settingsBus.open = undefined; settingsBus.openSection = undefined }
  }, [store])

  // Onboarding runs while the main session is blank (first boot, or a fresh
  // blank chat with nothing done yet) — exactly the stock coordinator's fact.
  const sessionsBlank = typeof useSessions === 'function'
    ? useSessions((state) => {
        const main = Object.values(state.byId).find((s) => (s.retainedBy.mainView ?? 0) > 0)
        return state.phase === 'ready' && (main === undefined || main.blank)
      })
    : true
  const step = requested !== undefined
    ? steps.find((s) => s.id === requested)
    : sessionsBlank ? steps.find((s) => !completed.has(s.id)) : undefined
  useEffect(() => { if (!sessionsBlank) setCompleted(new Set()) }, [sessionsBlank])
  // Signing out puts the window back to the way it first opened — the welcome
  // screen with Sign in — the way the Muse desktop does; the person can still
  // leave it for a key of their own from there.
  const signedIn = useLive().cloud.signedIn
  const wasSignedIn = useRef(signedIn)
  useEffect(() => {
    if (wasSignedIn.current && !signedIn) {
      store.close()
      setCompleted(new Set())
      const ours = steps.find((s) => s.id === ONBOARDING_STEP) ?? steps[0]
      if (ours) setRequested(ours.id)
    }
    wasSignedIn.current = signedIn
  }, [signedIn, steps, store])
  const stepSeen = useRef(step)
  useEffect(() => {
    const appeared = stepSeen.current === undefined && step !== undefined
    stepSeen.current = step
    if (appeared && open) store.close()
  }, [step, open, store])
  const complete = useCallback((id: string) => {
    setRequested(undefined)
    setCompleted((previous) => (previous.has(id) ? previous : new Set([...previous, id])))
  }, [])
  // Help → "See the first run again" reopens the flow on purpose.
  useEffect(() => {
    settingsBus.openOnboarding = (id) => { store.close(); setRequested(id) }
    return () => { settingsBus.openOnboarding = undefined }
  }, [store])

  return h('div', { className: 'nm-settings-seat' },
    // A real trigger for anything that looks for one (the rail's fallback, assistive tech).
    h('button', { type: 'button', className: 'nm-hidden', 'aria-haspopup': 'dialog', 'aria-expanded': open, onClick: () => store.open() },
      renderSlot('settings.trigger', { wide: false }, { fallback: t('menuSettings') })),
    renderSlot('settings.launcher', {
      wide: false,
      settingsOpen: open,
      openSettings: () => store.open(),
      openOnboarding: (id: string) => { store.close(); setRequested(id) },
    }, { fallback: null }),
    open ? h(SettingsPanel, { t, rows, renderSlot, activeId, onSelect: (id) => store.select(id), onClose: () => store.close() }) : null,
    step !== undefined
      ? renderSlot('settings.onboarding', {
          stepId: step.id,
          explicit: requested !== undefined,
          complete: () => complete(step.id),
          openSection: (id: string) => store.openSection(id),
        }, { only: step.id })
      : null)
}

/** Muse's theme colours, in its order: blue first, then the pastels, grey and black. */
export const ACCENTS: readonly string[] = ['#0064d4', '#7fb4ff', '#9b8cf4', '#f28bb8', '#f6a46b', '#f0cc4a', '#5cb85c', '#55c9b5', '#8a8a8e', '#1c1c1e']

/**
 * The General page, laid out as Muse's: the account card, usage bars, language,
 * appearance (mode + theme colour), app behaviour, shortcuts, about. The harness's
 * other General rows live on the Advanced › Harness page.
 */
export function makeGeneralSection(t: Translate, version: string) {
  return function GeneralSection({ renderSlot }: { renderSlot: RenderSlot }): ReactNode {
    const live = useLive()
    const [status, setStatus] = useState<CloudStatus | undefined>()
    const [checked, setChecked] = useState<'idle' | 'checking' | 'latest'>('idle')
    useEffect(() => {
      let alive = true
      call<CloudStatus>('status').then((s) => { if (alive) setStatus(s) }).catch(() => undefined)
      return () => { alive = false }
    }, [live.cloud.signedIn])
    const account = status?.account
    const used = account && !account.tokens.unlimited && account.tokens.granted > 0 ? Math.min(100, Math.round((account.tokens.used / account.tokens.granted) * 100)) : 0
    const color = live.profile.color
    const pick = (next: string) => { void call('profile', { color: next }).catch(() => undefined) }
    const checkUpdates = () => {
      setChecked('checking')
      window.setTimeout(() => setChecked('latest'), 900)
      openLink(RELEASES_URL)
    }
    return h('div', { className: 'nm-general nm-section' },
      // the account card
      h('div', { className: 'nm-card' },
        h('button', { type: 'button', className: 'nm-row nm-row-button', onClick: () => { settingsBus.openSection?.('nanomuse-cloud') } },
          h('span', { className: 'nm-row-icon' }, h(Avatar, { size: 28, profile: live.profile, mood: 'idle' })),
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('gnAccount')),
            h('span', { className: 'nm-row-sub' }, live.cloud.signedIn ? t('gnAccountSub', { hint: live.cloud.hint }) : t('gnAccountSignIn'))),
          h('span', { className: 'nm-row-chevron' }, h(IconChevronRight, { size: 16 })))),
      // usage
      h('h2', null, t('gnUsage')),
      h('div', { className: 'nm-card nm-usage' },
        account
          ? h(Fragment, null,
              h('div', { className: 'nm-usage-row' },
                h('span', { className: 'nm-usage-plan' }, account.member ? t('gnPlanMember') : t('gnPlanFree')),
                h('span', { className: 'nm-usage-pct' }, account.tokens.unlimited ? t('gnUnlimited') : t('gnUsed', { n: used }))),
              account.tokens.unlimited ? null : h('div', { className: 'nm-usage-bar', role: 'progressbar', 'aria-valuenow': used, 'aria-valuemin': 0, 'aria-valuemax': 100 }, h('span', { style: { width: `${used}%` } })),
              h('div', { className: 'nm-usage-fine' }, account.tokens.unlimited ? t('gnUnlimitedSub') : t('gnRemaining', { n: account.tokens.remaining.toLocaleString() })),
              account.member ? null : h('a', { className: 'nm-usage-link', href: SITE_URL, target: '_blank', rel: 'noopener noreferrer', onClick: (e: { preventDefault(): void }) => { e.preventDefault(); openLink(SITE_URL) } }, t('gnUpgrade')))
          : h('div', { className: 'nm-usage-fine' }, live.cloud.signedIn ? t('loading') : t('gnUsageSignedOut'))),
      // language: the harness's own row
      h('div', { className: 'nm-card nm-harness-rows' }, renderSlot('settings.general.item', {}, { only: 'language' })),
      // appearance: mode (the harness's switch, which carries its own title) and the theme colour
      h('div', { className: 'nm-card nm-harness-rows' },
        renderSlot('settings.general.item', {}, { only: 'appearance' }),
        h('div', { className: 'nm-row' },
          h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('gnThemeColor'))),
          h('div', { className: 'nm-swatches', role: 'radiogroup', 'aria-label': t('gnThemeColor') },
            ACCENTS.map((c) => h('button', {
              key: c,
              type: 'button',
              role: 'radio',
              className: `nm-swatch${(color || ACCENTS[0]) === c ? ' nm-on' : ''}`,
              'aria-checked': (color || ACCENTS[0]) === c,
              'aria-label': c,
              title: c,
              style: { background: c },
              onClick: () => pick(c),
            }))))),
      h(AppBehaviorRows, { t }),
      // shortcuts
      h('h2', null, t('gnShortcuts')),
      h('div', { className: 'nm-card' },
        h('div', { className: 'nm-row' },
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('gnQuickChat')),
            h('span', { className: 'nm-row-sub' }, t('gnQuickChatSub'))),
          h(HotkeyField, { t })),
        h('button', { type: 'button', className: 'nm-row nm-row-button', onClick: () => openShortcutsReference() },
          h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('menuShortcuts'))),
          h('span', { className: 'nm-row-chevron' }, h(IconChevronRight, { size: 16 })))),
      // about
      h('h2', null, t('gnAbout')),
      h('div', { className: 'nm-card' },
        h('div', { className: 'nm-row' },
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('versionLine', { version: version || '—' })),
            h('span', { className: 'nm-row-sub' }, checked === 'latest' ? t('gnUpToDate') : t('gnUpdatesSub'))),
          h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: checked === 'checking', onClick: checkUpdates }, checked === 'checking' ? t('gnChecking') : t('gnCheckUpdates')))),
      h(DeveloperRows, { t }))
  }
}

/** Advanced › Harness: every General row the harness and its plugins add, none lost. */
export function makeHarnessSection(t: Translate) {
  return function HarnessSection({ renderSlot }: { renderSlot: RenderSlot }): ReactNode {
    return h('div', { className: 'nm-general nm-section' },
      h('p', null, t('hsLead')),
      h('div', { className: 'nm-card nm-harness-rows' }, renderSlot('settings.general.item', {})))
  }
}
