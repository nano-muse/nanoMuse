import { call, failureText } from './api.ts'
/**
 * The nanoMuse browser half: the Muse look on the harness's Web client. The
 * left column (an icon rail beside the harness's chats browser), the agent
 * pinned over the conversation with its status line, a Devices page, the
 * first-run welcome, the nanoMuse section in Settings and the toasts other
 * devices send. Everything here is a slot registration — the harness's client
 * stays the harness's; we occupy the seats it declares (and, for the sidebar,
 * take over the one seat whose stock occupant the bundle layer switches off,
 * declaring the same children so every other plugin's contribution still
 * lands where it did).
 */
import type { Context as ClientContext } from '@deepseek-ai/cordis'
import { resolveSlotLabel } from '@deepseek-ai/dsh-client-ui-slots'
import { closeTopModal } from '@deepseek-ai/dsh-client-ui-primitives'
import { createElement as h, useEffect, useRef, type ReactNode } from 'react'
import type { Translate } from './api.ts'
import { Avatar, BrandName, type Mood } from './Avatar.tsx'
import { makeAvatarStudio } from './AvatarStudio.tsx'
import { bridge } from './bridge.ts'
import { profileBus, settingsBus } from './bus.ts'
import { makeAboutSheet } from './About.tsx'
import { renderApprovalScopes } from './ApprovalScopes.ts'
import { syncOverlay } from './overlay.ts'
import { renderFenceCards } from './FenceCards.ts'
import { renderRemoteBubbles } from './RemoteBubbles.ts'
import { makeFirstRunIntro } from './FirstRun.tsx'
import { AllowanceHeadsUp } from './AllowanceWays.tsx'
import { WaitLine } from './WaitLine.tsx'
import { StopAsk, makeThumbs } from './Feedback.tsx'
import { interceptComposer, makeAvatarChat } from './AvatarChat.tsx'
import { makeCapsule } from './Capsule.tsx'
import { prefillComposer } from './composer.ts'
import { makeMicButton, makeQuoteAction } from './ComposerExtras.tsx'
import { makeDocEditor } from './DocEditor.tsx'
import { renderTrajectory } from './Trajectory.tsx'
import { makeCloudSection } from './CloudSection.tsx'
import { CODING_SECTION, makeCodingPanel } from './CodingPanel.tsx'
import { makeDevicesPanel } from './DevicesPanel.tsx'
import { makeFeedPanel } from './FeedPanel.tsx'
import { makeGoalsPanel } from './GoalsPanel.tsx'
import { makeIdeasPanel } from './IdeasPanel.tsx'
import { makeLibraryPanel } from './LibraryPanel.tsx'
import { IconPanelLeft, IconPlus } from './icons.tsx'
import { makeInviteButton } from './Invite.tsx'
import { useLive } from './live.ts'
import { en, zh } from './locales.ts'
import type { ChatActions } from './MuseChats.tsx'
import { MuseHeader, type UseSessionStatus } from './MuseHeader.tsx'
import { CONNECTORS_SECTION, makeConnectorsSection } from './Connectors.tsx'
import { SKILLS_SECTION, makeSkillsSection } from './Skills.tsx'
import { DICTATION_SECTION, FILES_SECTION, makeDictationSection, makeFilesSection, makePermissionsSection, PERMISSIONS_SECTION } from './Pages.tsx'
import { makeTurnError } from './RefusalCard.tsx'
import { CHANNELS_SECTION, COMPUTER_SECTION, createShellStore, DATA_SECTION, HARNESS_SECTION, HELP_SECTION, LEGAL_SECTION, makeGeneralSection, makeHarnessSection, MuseSettings, STORAGE_SECTION, WALLET_SECTION, type MuseSettingsProps, type OnboardingStep, type SectionRow } from './MuseSettings.tsx'
import { MuseSidebar, type MuseSidebarProps, type PanelMeta } from './MuseSidebar.tsx'
import { makeOnboarding, type OnboardingOwnerProps } from './Onboarding.tsx'
import { DEVICES_PANEL, FEED_PANEL, GOALS_PANEL, IDEAS_PANEL, ISSUES_URL, LIBRARY_PANEL } from './panels.ts'
import { getPrefs, recordApproval, subscribePrefs, usePrefs } from './prefs.ts'
import { makeProfileDrawer } from './ProfileDrawer.tsx'
import { nav as roomsNav, roomsCall } from './rooms.ts'
import { SearchModal } from './SearchModal.tsx'
import { makeChannelsSection, makeComputerSection, makeHelpSection, makeLegalSection, makeStorageSection, makeWalletSection } from './Sections.tsx'
import { makeMediaSection } from './MediaSection.tsx'
import { makeModelsSection, MODELS_SECTION } from './ModelsSection.tsx'
import { ensureStyles, setAccent, setMuseMode } from './styles.ts'
import { useWin, win } from './win.ts'

export const name = 'nanomuse-client'
/** Required services: slots, the locale table, the frame, the workspace UI's session actions, shortcuts. */
export const inject = ['slots', 'locale', 'layout', 'uiWorkspace', 'shortcuts']

/** The slot and locale faces we use, named here so the plugin reads plainly. */
interface SlotRegistrar {
  inject(name: string, body: () => unknown): unknown
  register(options: Record<string, unknown>, component: (props: never) => unknown): () => void
  entriesOfSlot(name: string): { options: { id?: string; order?: number; label?: unknown } }[]
  subscribe(name: string, listener: () => void): () => void
  getVersion(name: string): number
}
interface LocaleTable {
  register(ns: string, dicts: Record<string, Record<string, string>>): () => void
  bind(ns: string): (key: string, values?: Record<string, string | number>) => string
  subscribe(listener: () => void): () => void
  getSnapshot(): { revision: number }
}
interface LayoutService {
  toggleSidebar(): void
  selectPanel(id: string | null): void
}
interface WorkspaceNavigation {
  startSession(workspaceId?: string): void
  openSession(target: string): void
  openWorkspace(workspaceId: string): Promise<void>
  archiveSession(sessionId: string, options?: { stopActivity?: boolean }): Promise<void>
  unarchiveSession(sessionId: string): Promise<void>
  pinSession(sessionId: string): Promise<void>
  unpinSession(sessionId: string): Promise<void>
  pickDirectory(): Promise<string | null>
}
interface WorkspacesService {
  create(input: { path: string }): Promise<{ workspaceId: string }>
}
interface ShortcutsService {
  catalog: unknown
  register(command: Record<string, unknown>): () => void
}

interface SessionFace {
  cancel(): Promise<unknown>
  rename(title: string): Promise<{ ok: boolean; error?: { message: string } }>
  /** A prompt into the session, as the composer sends one. */
  prompt(blocks: { type: 'text'; text: string }[], mode: 'queue' | 'steer'): Promise<{ ok: boolean; error?: { message: string } } | undefined>
}
interface SessionsService {
  using<T>(target: string, options: { source: string }, operation: (reference: { ready: Promise<unknown>; binding: { session: SessionFace } }) => Promise<T>): Promise<T>
}

/** A minimal observable snapshot, the shape the slot host turns into a `useX` hook. */
function observable<T>(initial: T) {
  let value = initial
  const listeners = new Set<() => void>()
  return {
    getSnapshot: () => value,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } },
    set: (next: T) => { value = next; for (const l of listeners) l() },
  }
}

/** The agent's mood from what its sessions are doing: waiting beats working beats idle. */
function useMood(useSessionStatus: UseSessionStatus | undefined): Mood {
  if (typeof useSessionStatus !== 'function') return 'idle'
  return useSessionStatus((snapshot) => {
    let mood: Mood = 'idle'
    for (const status of snapshot.values()) {
      if (status.pendingInteraction !== undefined) return 'waiting'
      if (status.running === true) mood = 'working'
    }
    return mood
  })
}

export function apply(ctx: ClientContext): void {
  const raw = (ctx as unknown as { slots: SlotRegistrar }).slots
  // A seat that fails to register is reported and skipped, not fatal for the
  // whole plugin: the face, the column and the pages stay independent.
  const slots: SlotRegistrar = {
    ...raw,
    entriesOfSlot: (name) => raw.entriesOfSlot(name),
    subscribe: (name, listener) => raw.subscribe(name, listener),
    getVersion: (name) => raw.getVersion(name),
    register: (options, component) => raw.register(options, component),
    inject: (name, body) => raw.inject(name, () => {
      try {
        return body()
      } catch (error) {
        console.error(`[nanomuse] seat "${name}" did not register:`, error)
        return () => undefined
      }
    }),
  }
  const locale = (ctx as unknown as { locale: LocaleTable }).locale
  const layout = (ctx as unknown as { layout: LayoutService }).layout
  const workspaces = (ctx as unknown as { get(name: string): unknown }).get('uiWorkspace') as WorkspaceNavigation
  const shortcuts = (ctx as unknown as { shortcuts: ShortcutsService }).shortcuts
  const getService = (name: string): unknown => (ctx as unknown as { get(name: string): unknown }).get(name)
  const shell = createShellStore()

  ctx.effect(() => locale.register('nanomuse', { en, zh }), 'nanomuse: dictionaries')
  const t = locale.bind('nanomuse') as Translate
  ctx.effect(() => ensureStyles(), 'nanomuse: stylesheet')
  // The Muse composer and column unless the Developer switch asks for the harness's own.
  ctx.effect(() => {
    const apply = () => setMuseMode(!getPrefs().showHarness, t('cpPlaceholder'), getPrefs().showSteps)
    apply()
    return subscribePrefs(apply)
  }, 'nanomuse: muse mode')
  // The window's base colour follows the page's theme (no white flash on resize in the dark).
  ctx.effect(() => {
    const electron = bridge()
    if (!electron) return () => undefined
    const sync = () => { void electron.setTheme(document.body.hasAttribute('data-ds-dark-theme') ? 'dark' : 'light') }
    sync()
    const observer = new MutationObserver(sync)
    observer.observe(document.body, { attributes: true, attributeFilter: ['data-ds-dark-theme'] })
    return () => observer.disconnect()
  }, 'nanomuse: window theme')
  // Programmatic focus can scroll the frame sideways (the right sidebar waits off-canvas); keep it put.
  ctx.effect(() => {
    const guard = () => {
      for (const frame of document.querySelectorAll<HTMLElement>('[class*="_frame"]')) if (frame.scrollLeft !== 0) frame.scrollLeft = 0
    }
    document.addEventListener('focusin', guard, true)
    return () => document.removeEventListener('focusin', guard, true)
  }, 'nanomuse: frame guard')
  // What the person answered on approval cards, for the drawer's Approvals tab.
  ctx.effect(() => {
    const record = (card: Element, outcome: 'allowed' | 'rejected') => {
      const headline = card.querySelector('[data-approval-scroll] > :first-child')?.textContent?.trim() ?? ''
      recordApproval({ at: Date.now(), toolName: '', reason: headline, outcome })
    }
    const onClick = (event: MouseEvent) => {
      const button = (event.target as Element).closest('button')
      const card = button?.closest('[data-approval-key]')
      if (!button || !card || button.closest('[data-approval-scroll]')) return
      const actions = Array.from(card.querySelectorAll(':scope > div > :last-child button'))
      if (!actions.includes(button)) return
      // the harness renders Allow as its primary button and last in the DOM; either sign will do
      const primary = /_primary/.test(button.className) || actions.indexOf(button) === actions.length - 1
      record(card, primary ? 'allowed' : 'rejected')
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Enter' && event.key !== 'Escape') return
      const target = event.target as Element
      const card = target.closest('[data-approval-key]')
      if (!card || target.closest('input, textarea, button, [contenteditable]')) return
      record(card, event.key === 'Enter' ? 'allowed' : 'rejected')
    }
    document.addEventListener('click', onClick, true)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('click', onClick, true)
      document.removeEventListener('keydown', onKey, true)
    }
  }, 'nanomuse: approval records')

  // Settings opens through whatever shell occupies `sidebar.settings`: the
  // bus carries the opener our own shell registers; without one the sidebar
  // clicks the stock shell's trigger.
  const openSettings = (): boolean => settingsBus.open?.() ?? false

  // The brand seats: the account's face, with a mood, and the account's name.
  // The mark is always mounted, so it also keeps the accent colour current.
  slots.inject('sidebar.brand.mark', () =>
    slots.register({ name: 'sidebar.brand.mark' }, ({ size, useSessionStatus }: { size: number; useSessionStatus?: UseSessionStatus }) => {
      const live = useLive()
      const prefs = usePrefs()
      const mood = useMood(useSessionStatus)
      useEffect(() => { setAccent(live.profile.color) }, [live.profile.color])
      // The display stays awake while the agent works, when the person wants that.
      useEffect(() => { void bridge()?.keepAwake(prefs.keepAwake && mood === 'working') }, [prefs.keepAwake, mood])
      return h(Avatar, { size, profile: live.profile, mood, title: live.profile.name })
    }))
  slots.inject('sidebar.brand.name', () =>
    slots.register({ name: 'sidebar.brand.name' }, () => {
      const live = useLive()
      return h(BrandName, { text: live.profile.name || t('brand') })
    }))

  // The hero above a blank session: the agent, not a logo.
  slots.inject('conversation.hero.brand.mark', () =>
    slots.register({ name: 'conversation.hero.brand.mark' }, ({ size, className }: { size: number; className?: string | undefined }) => {
      const live = useLive()
      return h(Avatar, { size, className, profile: live.profile, title: live.profile.name })
    }))

  // The left column. The panel list mirrors the `sidebar.panellist` ledger the
  // way the stock sidebar's does, labels resolved per locale.
  const panels = observable<readonly PanelMeta[]>([])
  const syncPanels = (): void => {
    const next = slots.entriesOfSlot('sidebar.panellist')
      .map(({ options }) => ({ id: options.id ?? '', order: options.order ?? 0, label: resolveSlotLabel(options.label as never) ?? options.id ?? '' }))
      .sort((a, b) => a.order - b.order)
    const previous = panels.getSnapshot()
    if (previous.length === next.length && previous.every((p, i) => p.id === next[i]!.id && p.order === next[i]!.order && p.label === next[i]!.label)) return
    panels.set(next)
  }
  ctx.effect(() => slots.subscribe('sidebar.panellist', syncPanels), 'nanomuse: panel entries')
  ctx.effect(() => locale.subscribe(syncPanels), 'nanomuse: panel labels')
  const renameSession = async (sessionId: string, title: string): Promise<void> => {
    const sessions = getService('sessions') as SessionsService | undefined
    if (!sessions) return
    const result = await sessions.using(sessionId, { source: 'workspaceOperation' }, async (reference) => {
      await reference.ready
      return reference.binding.session.rename(title)
    })
    if (!result.ok) throw new Error(result.error?.message ?? 'rename failed')
  }
  const openChat = (id: string): void => {
    void call('sync/access', { sessionId: id }).then(() => workspaces.openSession(id))
      .catch((error: unknown) => { window.alert(failureText(t, error)) })
  }
  const chatActions: ChatActions = {
    openSession: openChat,
    startSession: () => { workspaces.startSession() },
    archiveSession: (id) => workspaces.archiveSession(id, { stopActivity: true }),
    pinSession: (id) => workspaces.pinSession(id),
    unpinSession: (id) => workspaces.unpinSession(id),
    renameSession,
    unarchiveSession: (id) => workspaces.unarchiveSession(id),
  }
  // A room opened from the rail fills the main area; the split (a room beside
  // the chat) ends with it.
  const selectPanel = (id: string | null): void => {
    win.split(null)
    layout.selectPanel(id)
  }
  const sidebarInjected = () => ({
    startSession: () => { workspaces.startSession() },
    toggleSidebar: () => { layout.toggleSidebar() },
    selectPanel,
    openSettings,
    openSection: (id: string) => { shell.openSection(id) },
    openProfile: () => { profileBus.toggle() },
    openSearch: () => { win.search(true) },
    issuesUrl: ISSUES_URL,
    chatActions,
    hooks: { panels, shortcuts: shortcuts.catalog },
  })
  slots.inject('sidebar', () => slots.register({
    name: 'sidebar',
    locale: 'nanomuse',
    children: {
      'sidebar.brand.mark': { kind: 'single', scope: 'root' },
      'sidebar.brand.name': { kind: 'single', scope: 'root' },
      'sidebar.toggle.badge': { kind: 'single', scope: 'root' },
      'sidebar.panellist': { kind: 'list', scope: 'root' },
      'sidebar.workspaces': { kind: 'single', scope: 'root' },
      'sidebar.settings': { kind: 'single', scope: 'root' },
      'sidebar.footer.action': { kind: 'list', scope: 'root' },
    },
    inject: sidebarInjected,
  }, (props: MuseSidebarProps) => h(MuseSidebar, props)))
  // macOS desktop hides the collapsed column entirely; the frame then mounts
  // this seat beside the traffic lights for reopening it and a new chat.
  slots.inject('shell.leading', () => slots.register({ name: 'shell.leading', locale: 'nanomuse', inject: sidebarInjected }, ({ toggleSidebar, startSession }: { toggleSidebar(): void; startSession(): void }) =>
    h('div', { style: { display: 'flex', gap: 2, padding: '0 4px' } },
      h('button', { type: 'button', className: 'nm-icon-btn', 'aria-label': t('menuExpand'), title: t('menuExpand'), onClick: toggleSidebar }, h(IconPanelLeft, { size: 18 })),
      h('button', { type: 'button', className: 'nm-icon-btn', 'aria-label': t('railNew'), title: t('railNew'), onClick: startSession }, h(IconPlus, { size: 18 })))))
  syncPanels()

  // The rooms behind the rail's icons — Feed, Ideas, Goals, Library — and the
  // Devices page. The rooms send the person to chats through `nav`.
  let activePanel: string | null = null
  roomsNav.openSession = openChat
  roomsNav.showChats = () => { selectPanel(null) }
  roomsNav.startSession = () => { workspaces.startSession() }
  roomsNav.activePanel = () => activePanel
  roomsNav.prefill = prefillComposer
  // The split: the chat takes the main area, the room docks at the right.
  roomsNav.split = (panel) => {
    if (panel) {
      layout.selectPanel(null)
      win.split(panel)
    } else {
      win.split(null)
    }
  }
  roomsNav.toggleSidebar = () => { layout.toggleSidebar() }
  const rooms: [string, () => ReactNode][] = [
    [FEED_PANEL, makeFeedPanel(t)],
    [IDEAS_PANEL, makeIdeasPanel(t)],
    [GOALS_PANEL, makeGoalsPanel(t)],
    [LIBRARY_PANEL, makeLibraryPanel(t)],
  ]
  for (const [key, Panel] of rooms) slots.inject('main', () => slots.register({ name: 'main', key, locale: 'nanomuse' }, Panel))
  const DevicesPanel = makeDevicesPanel(t)
  slots.inject('main', () => slots.register({ name: 'main', key: DEVICES_PANEL, locale: 'nanomuse' }, DevicesPanel))
  // The split pane itself, over the frame beside the chat; it keeps the active
  // panel mirrored for the rooms' `nav.activePanel`.
  slots.inject('shell.overlay', () =>
    slots.register({ name: 'shell.overlay', id: 'nanomuse.split', locale: 'nanomuse' }, ({ usePanelInfo }: { usePanelInfo?: <S>(selector: (info: { activePanelId: string | null }) => S) => S }) => {
      const active = typeof usePanelInfo === 'function' ? usePanelInfo((info) => info.activePanelId) : null
      activePanel = active
      const split = useWin().split
      const open = split !== null && active === null
      useEffect(() => {
        if (open) document.documentElement.dataset['nmSplit'] = ''
        else delete document.documentElement.dataset['nmSplit']
        return () => { delete document.documentElement.dataset['nmSplit'] }
      }, [open])
      if (!open) return null
      const Panel = rooms.find(([key]) => key === split)?.[1]
      if (!Panel) return null
      return h('aside', { className: 'nm-split', 'aria-label': t('splitPane') }, h(Panel as () => ReactNode, {}) as ReactNode)
    }))

  // The agent pinned over the conversation; Stop cancels the running turn(s).
  const stop = async (sessionId: string): Promise<void> => {
    const sessions = (ctx as unknown as { get(name: string): unknown }).get('sessions') as SessionsService | undefined
    if (!sessions || !sessionId) return
    await sessions.using(sessionId, { source: 'controllerOperation' }, async (reference) => {
      await reference.ready
      await reference.binding.session.cancel()
    })
  }
  slots.inject('conversation.header.leading', () =>
    slots.register({ name: 'conversation.header.leading', locale: 'nanomuse' }, ({ useSessionStatus }: { useSessionStatus?: UseSessionStatus }) =>
      h(MuseHeader, { t, stop, openProfile: () => { profileBus.toggle() }, useSessionStatus })))

  // Invite, at the top right of a chat; the profile drawer over the frame.
  const InviteButton = makeInviteButton(t)
  slots.inject('conversation.session.header.utilities', () =>
    slots.register({ name: 'conversation.session.header.utilities', id: 'nanomuse-invite', order: -20, locale: 'nanomuse' }, InviteButton))
  const ProfileDrawer = makeProfileDrawer(t, stop)
  slots.inject('shell.overlay', () =>
    slots.register({ name: 'shell.overlay', id: 'nanomuse.profile', locale: 'nanomuse', inject: () => ({ openSchedules: () => { selectPanel('schedules') } }) }, ProfileDrawer))
  // The look changed from the chat: "change your avatar to a fox" is taken on its way out of the composer.
  const AboutSheet = makeAboutSheet(t, process.env.NANOMUSE_VERSION ?? '')
  slots.inject('shell.overlay', () =>
    slots.register({ name: 'shell.overlay', id: 'nanomuse.about', locale: 'nanomuse' }, AboutSheet))
  // The first conversation's opening lines, drawn at the top of the main chat (C4).
  const FirstRunIntro = makeFirstRunIntro(t)
  slots.inject('shell.overlay', () =>
    slots.register({ name: 'shell.overlay', id: 'nanomuse.firstrun', locale: 'nanomuse' }, FirstRunIntro))
  const AvatarChat = makeAvatarChat(t)
  slots.inject('shell.overlay', () =>
    slots.register({ name: 'shell.overlay', id: 'nanomuse.avatar-chat', locale: 'nanomuse' }, AvatarChat))
  ctx.effect(() => interceptComposer(), 'nanomuse: avatar words')
  // The microphone at the right of the composer; "reply with a quote" beside Copy.
  const MicButton = makeMicButton(t, () => { shell.openSection(DICTATION_SECTION) })
  slots.inject('conversation.input.right', () =>
    slots.register({ name: 'conversation.input.right', id: 'nanomuse.mic', order: 10, locale: 'nanomuse' }, MicButton))
  const QuoteAction = makeQuoteAction(t)
  slots.inject('conversation.chat.assistant-actions', () =>
    slots.register({ name: 'conversation.chat.assistant-actions', id: 'nanomuse.quote', order: -10, locale: 'nanomuse' }, QuoteAction))
  // The thumbs beside a reply (0.31): a mark for the account's record, a word of why after a thumb down.
  const Thumbs = makeThumbs(t)
  slots.inject('conversation.chat.assistant-actions', () =>
    slots.register({ name: 'conversation.chat.assistant-actions', id: 'nanomuse.thumbs', order: -9, locale: 'nanomuse' }, Thumbs))
  // A turn the model did not finish, as a card (C12): the relay's refusals — the allowance used
  // up, a message too large, a sign-in that expired — in our words, with the ways on; any other
  // failure in one plain sentence. Shadows the harness's `turn-error` seat (the lowest priority renders).
  const resend = async (sessionId: string, text: string): Promise<void> => {
    const sessions = getService('sessions') as SessionsService | undefined
    if (!sessions) throw new Error('no sessions service')
    await sessions.using(sessionId, { source: 'controllerOperation' }, async (reference) => {
      await reference.ready
      const result = await reference.binding.session.prompt([{ type: 'text', text }], 'queue')
      if (result && result.ok === false) throw new Error(result.error?.message ?? 'prompt refused')
    })
  }
  const TurnError = makeTurnError(t, { retry: resend, newChat: () => { workspaces.startSession() } })
  slots.inject('conversation.chat.node', () =>
    slots.register({ name: 'conversation.chat.node', key: 'turn-error', priority: -1, locale: 'nanomuse' }, TurnError))
  // The 80 % heads-up above the composer, once per pool size (the phones' one-line heads-up in the chat).
  slots.inject('conversation.input.dock', () =>
    slots.register({ name: 'conversation.input.dock', id: 'nanomuse.headsup', order: -10, locale: 'nanomuse' }, () => h(AllowanceHeadsUp, { t })))
  // "The model is busy, 15 s so far" above the composer while the chat's turn has no first token (0.31; the phones' line under the dots).
  slots.inject('conversation.input.dock', () =>
    slots.register({ name: 'conversation.input.dock', id: 'nanomuse.wait', order: -9, locale: 'nanomuse', inject: (sessionId: string) => ({ sessionId }) },
      ({ sessionId }: { sessionId?: string }) => h(WaitLine, { t, sessionId, stop })))
  // The question after a Stop (0.31), in the wait line's place: why, five answers, Skip.
  slots.inject('conversation.input.dock', () =>
    slots.register({ name: 'conversation.input.dock', id: 'nanomuse.stopask', order: -8, locale: 'nanomuse', inject: (sessionId: string) => ({ sessionId }) },
      ({ sessionId }: { sessionId?: string }) => h(StopAsk, { t, sessionId })))
  // The document editor (IDENTITY / SOUL / MEMORY and Library texts) and ⌘K search, over the frame.
  const DocEditor = makeDocEditor(t, () => { layout.toggleSidebar() })
  slots.inject('shell.overlay', () =>
    slots.register({ name: 'shell.overlay', id: 'nanomuse.docs', locale: 'nanomuse' }, DocEditor))
  slots.inject('shell.overlay', () =>
    slots.register({ name: 'shell.overlay', id: 'nanomuse.search', locale: 'nanomuse' }, ({ useSessions }: { useSessions?: Parameters<typeof SearchModal>[0]['useSessions'] }) =>
      (typeof useSessions === 'function' ? h(SearchModal, { t, useSessions, actions: chatActions }) : null)))
  // ⌘K is the harness's `session.search`, which only its own browser answers; in
  // Muse mode the same key opens our search (the shortcuts reference lists it as
  // "search sessions", which is what it does).
  ctx.effect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.code !== 'KeyK' || event.altKey || event.shiftKey || getPrefs().showHarness) return
      const mac = /Mac|iPhone|iPad/.test(navigator.platform)
      if (!(mac ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey)) return
      event.preventDefault()
      event.stopPropagation()
      win.search(true)
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, 'nanomuse: search key')

  // The settings dialog, Muse-shaped, in the seat our sidebar declares; it
  // declares the settings seats in turn, and the General page declares the
  // rows seat. The ledger → nav-row projections are cached per ledger version
  // and locale revision, the way the stock shell's were.
  let rowsVersion = -1
  let rowsRevision = -1
  let rows: readonly SectionRow[] = []
  let stepsVersion = -1
  let steps: readonly OnboardingStep[] = []
  const sections = {
    getSnapshot: () => {
      const version = slots.getVersion('settings.section')
      const revision = locale.getSnapshot().revision
      if (version !== rowsVersion || revision !== rowsRevision) {
        rowsVersion = version
        rowsRevision = revision
        rows = slots.entriesOfSlot('settings.section')
          .map((e) => ({ id: e.options.id ?? '', order: e.options.order ?? 0, label: resolveSlotLabel(e.options.label as never) ?? '' }))
          .sort((a, b) => a.order - b.order)
      }
      return rows
    },
    subscribe: (listener: () => void) => {
      const offLedger = slots.subscribe('settings.section', listener)
      const offLocale = locale.subscribe(listener)
      return () => { offLedger(); offLocale() }
    },
  }
  const onboardingSteps = {
    getSnapshot: () => {
      const version = slots.getVersion('settings.onboarding')
      if (version !== stepsVersion) {
        stepsVersion = version
        steps = slots.entriesOfSlot('settings.onboarding')
          .map((e) => ({ id: e.options.id ?? '', order: e.options.order ?? 0 }))
          .sort((a, b) => a.order - b.order)
      }
      return steps
    },
    subscribe: (listener: () => void) => slots.subscribe('settings.onboarding', listener),
  }
  slots.inject('sidebar.settings', () => {
    const disposeCommand = shortcuts.register({
      id: 'settings.open',
      label: () => t('menuSettings'),
      aliases: ['settings', 'preferences'],
      defaults: {
        'desktop:macos': { code: 'Comma', modifiers: ['primary'] },
        'desktop:windows': { code: 'Comma', modifiers: ['primary'] },
        'desktop:linux': { code: 'Comma', modifiers: ['primary'] },
        'web:macos': { code: 'Comma', modifiers: ['primary', 'alt'] },
        'web:windows': { code: 'Comma', modifiers: ['primary', 'alt'] },
      },
      regions: ['page', 'editable', 'terminal'],
      modals: ['settings'],
      resolve: ({ modal }: { modal: string | null }) => {
        if (modal !== null && modal !== 'settings') return { status: 'blocked', reason: 'modal' }
        return { status: 'handled', run: () => { if (modal === 'settings') closeTopModal(document); else shell.open() } }
      },
    })
    const disposeSlot = slots.register({
      name: 'sidebar.settings',
      locale: 'nanomuse',
      children: {
        'settings.launcher': { kind: 'single', scope: 'root' },
        'settings.trigger': { kind: 'single', scope: 'root' },
        'settings.header': { kind: 'single', scope: 'root' },
        'settings.action': { kind: 'list', scope: 'root' },
        'settings.close': { kind: 'single', scope: 'root' },
        'settings.section': { kind: 'list', scope: 'root' },
        'settings.onboarding': { kind: 'list', scope: 'root' },
      },
      inject: () => ({ store: shell, hooks: { sections, onboardingSteps } }),
    }, (props: MuseSettingsProps) => h(MuseSettings, { ...props, t, store: shell }))
    return () => { disposeCommand(); disposeSlot() }
  })
  slots.inject('settings.trigger', () => slots.register({ name: 'settings.trigger', locale: 'nanomuse' }, () => t('menuSettings')))
  slots.inject('settings.header', () => slots.register({ name: 'settings.header', locale: 'nanomuse' }, () => t('menuSettings')))
  slots.inject('settings.close', () => slots.register({ name: 'settings.close', locale: 'nanomuse' }, () => t('close')))
  const GeneralSection = makeGeneralSection(t, process.env.NANOMUSE_VERSION ?? '')
  slots.inject('settings.section', () => slots.register({
    name: 'settings.section',
    id: 'general',
    order: 0,
    label: () => t('navGeneral'),
    locale: 'nanomuse',
    children: { 'settings.general.item': { kind: 'list', scope: 'root' } },
  }, GeneralSection))
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: DEVICES_PANEL, order: 25, label: () => t('railDevices'), locale: 'nanomuse' }, DevicesPanel))
  // Settings → Coding agents: this computer's Cursor / Codex / Claude Code chats and the other computers' (docs/coding-agents.md)
  const CodingPanel = makeCodingPanel(t)
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: CODING_SECTION, order: 25.5, label: () => t('capCoding'), locale: 'nanomuse' }, CodingPanel))

  // The first run: meet the agent, sign in or use your own key — in the shipped
  // step's seat, below its priority so ours renders whichever registers first.
  const Onboarding = makeOnboarding(t, {
    pickDirectory: () => workspaces.pickDirectory(),
    createWorkspace: (path) => (getService('workspaces') as WorkspacesService).create({ path }),
    openWorkspace: (id) => workspaces.openWorkspace(id),
  })
  slots.inject('settings.onboarding', () =>
    slots.register({ name: 'settings.onboarding', id: 'deepseek-official', order: 0, priority: -1 }, (props: OnboardingOwnerProps) => h(Onboarding, props)))
  // The harness's own preview notice stores its acknowledgement in the stock
  // General plugin's settings, which this bundle switches off; the About row
  // credits the harness instead, so the step passes straight through.
  const PassThrough = (props: OnboardingOwnerProps): null => {
    // the coordinator hands over a new `complete` closure on every render; call it once
    const done = useRef(false)
    const complete = useRef(props.complete)
    complete.current = props.complete
    useEffect(() => {
      if (done.current) return
      done.current = true
      complete.current()
    }, [])
    return null
  }
  slots.inject('settings.onboarding', () =>
    slots.register({ name: 'settings.onboarding', id: 'welcome-notice', order: -100, priority: -1 }, PassThrough))

  // Settings → nanoMuse, after Models (10) and Agents (20); and the pages Muse has.
  const CloudSection = makeCloudSection(t)
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: 'nanomuse-cloud', order: 30, label: () => t('nav') }, CloudSection))
  const ComputerSection = makeComputerSection(t)
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: COMPUTER_SECTION, order: 22, label: () => t('navComputer'), locale: 'nanomuse' }, ComputerSection))
  // Settings → Models (0.1.41): chat, hands, pictures and clips, one picker each.
  const ModelsSection = makeModelsSection(t)
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: MODELS_SECTION, order: 5, label: () => t('mlTitle'), locale: 'nanomuse' }, ModelsSection))
  // Settings → Media (desk-b): the image and video models, the face's clips.
  const MediaSection = makeMediaSection(t)
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: 'nanomuse-media', order: 29, label: () => t('mdMediaTitle'), locale: 'nanomuse' }, MediaSection))
  const DataSection = makeCloudSection(t, 'data')
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: DATA_SECTION, order: 32, label: () => t('navData'), locale: 'nanomuse' }, DataSection))
  const ConnectorsSection = makeConnectorsSection(t)
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: CONNECTORS_SECTION, order: 21, label: () => t('navConnectors'), locale: 'nanomuse' }, ConnectorsSection))
  const SkillsSection = makeSkillsSection(t)
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: SKILLS_SECTION, order: 21.5, label: () => t('navSkills'), locale: 'nanomuse' }, SkillsSection))
  const FilesSection = makeFilesSection(t)
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: FILES_SECTION, order: 23, label: () => t('navFiles'), locale: 'nanomuse' }, FilesSection))
  const DictationSection = makeDictationSection(t, (id) => layout.selectPanel(id))
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: DICTATION_SECTION, order: 24, label: () => t('navDictation'), locale: 'nanomuse' }, DictationSection))
  const PermissionsSection = makePermissionsSection(t)
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: PERMISSIONS_SECTION, order: 31, label: () => t('navPermissions'), locale: 'nanomuse' }, PermissionsSection))
  const HelpSection = makeHelpSection(t, process.env.NANOMUSE_VERSION ?? '')
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: HELP_SECTION, order: 40, label: () => t('navHelp'), locale: 'nanomuse' }, HelpSection))
  const LegalSection = makeLegalSection(t)
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: LEGAL_SECTION, order: 41, label: () => t('navLegal'), locale: 'nanomuse' }, LegalSection))
  // Muse's Wallet, Secure storage and Message channels pages, with what is true here
  const WalletSection = makeWalletSection(t, (id) => shell.openSection(id))
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: WALLET_SECTION, order: 26, label: () => t('navWallet'), locale: 'nanomuse' }, WalletSection))
  const StorageSection = makeStorageSection(t, () => roomsCall('files'), (which) => { void roomsCall('files/reveal', { which }).catch(() => undefined) })
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: STORAGE_SECTION, order: 27, label: () => t('navStorage'), locale: 'nanomuse' }, StorageSection))
  const ChannelsSection = makeChannelsSection(t, (id) => shell.openSection(id), DEVICES_PANEL)
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: CHANNELS_SECTION, order: 28, label: () => t('navChannels'), locale: 'nanomuse' }, ChannelsSection))
  const HarnessSection = makeHarnessSection(t)
  slots.inject('settings.section', () =>
    slots.register({ name: 'settings.section', id: HARNESS_SECTION, order: 60, label: () => t('navHarness'), locale: 'nanomuse' }, HarnessSection))

  // Toasts for what other devices did here, over the whole frame.
  const Capsule = makeCapsule({ t })
  slots.inject('shell.overlay', () =>
    slots.register({ name: 'shell.overlay', id: 'nanomuse.capsule' }, Capsule))
  // The quick-chat key (the shell's ⌥ Space): a fresh chat with the composer focused.
  const quickChatOff = bridge()?.onQuickChat?.(() => {
    layout.selectPanel(null)
    workspaces.startSession()
    window.setTimeout(() => (document.querySelector('[contenteditable="true"]') as HTMLElement | null)?.focus(), 200)
  })
  if (quickChatOff) ctx.effect(() => quickChatOff, 'nanomuse: quick chat')
  // The shell's overlays while the hands work: the glow and the capsule outside this window.
  ctx.effect(() => syncOverlay({ t, stop }), 'nanomuse: overlays')
  ctx.effect(() => renderApprovalScopes(t), 'nanomuse: approval scopes')
  // The agent's app fences (goal created, goal update, feed post, new look) as cards in the chat.
  ctx.effect(() => renderFenceCards(t), 'nanomuse: fence cards')
  // The turns written on the account's other devices, as bubbles in the thread (C8).
  ctx.effect(() => renderRemoteBubbles(t), 'nanomuse: remote bubbles')

  // The avatar studio: a sheet over the window, from the look editor or the agent's draw_new_look.
  const AvatarStudio = makeAvatarStudio({ t })
  slots.inject('shell.overlay', () =>
    slots.register({ name: 'shell.overlay', id: 'nanomuse.studio' }, AvatarStudio))

  // The trajectory of a hands run, as a card in the chat (0.1.40; the picture-in-picture Live stage is gone).
  ctx.effect(() => renderTrajectory(t, stop), 'nanomuse: trajectory')
}
