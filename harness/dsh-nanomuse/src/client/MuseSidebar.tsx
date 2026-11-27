/**
 * The Muse-shaped left column in the harness's `sidebar` seat: an icon rail —
 * Chats, Search, the rooms (Feed, Ideas, Goals, Library), Devices, and a menu
 * in the corner for settings, shortcuts, the harness's Schedules and plugins
 * and reporting a problem — beside the chats column (search, the main chat,
 * the side chats). Collapsed, only the rail remains. The seven child seats the
 * stock sidebar declares are declared here too, so every occupant of them —
 * the brand mark, the panel glyphs, the browser, the settings shell, footer
 * actions — mounts exactly as before; only the frame around them is ours, and
 * the harness's workspace browser takes the column's place when the person
 * turns the Developer switch on.
 */
import { createElement as h, useEffect, useRef, useState, type ReactNode } from 'react'
import type { Translate } from './api.ts'
import { call, failureText } from './api.ts'
import { Avatar } from './Avatar.tsx'
import { Toast } from '@deepseek-ai/dsh-client-ui-primitives'
import { aboutBus } from './About.tsx'
import { bridge, openLink } from './bridge.ts'
import { IconBulb, IconCalendar, IconChat, IconClose, IconFeed, IconDoc, IconMenu, IconPanelLeft, IconPin, IconPlus, IconPuzzle, IconSearch, IconShapes, IconTarget, IconBug, IconDownload, IconInfo, IconKeyboard, IconSettings } from './icons.tsx'
import { openShortcutsReference, pressSettingsChord } from './keys.ts'
import { useLive } from './live.ts'
import { MuseChats, type ChatActions, type UseSessionList, type UseStatusMap, type UseWorkspaceList } from './MuseChats.tsx'
import { FEED_PANEL, GOALS_PANEL, IDEAS_PANEL, LIBRARY_PANEL, REPO_URL, ROOM_PANELS } from './panels.ts'
import { useRooms } from './rooms.ts'
import { usePrefs } from './prefs.ts'
import { useWin, win, type RecentDoc } from './win.ts'
import { useWindowsUpdates, updatePresentation, requestWindowsUpdate } from './windows-updates.ts'
import { DeviceChatStartDialog } from './DeviceChatStartDialog.tsx'
import { openDeviceConversation } from './DeviceConversationPanel.tsx'
import { DEVICES_PANEL } from './panels.ts'
import type { DeviceConversation } from '../device-conversations.ts'
import type { LiveDevice } from './live.ts'

const newChatListeners = new Set<() => void>()

/** Let the native title bar's new-chat button open the same destination picker. */
export function requestNewChatPicker(): void {
  for (const listener of newChatListeners) listener()
}

/** The id the harness's Schedules plugin registers its global panel under. */
const SCHEDULES_PANEL = 'schedules'
/** The id of the harness's plugin manager panel; it lives in the corner menu. */
const PLUGINS_PANEL = 'plugins'

const COLLAPSE_SETTLE_MS = 150
const RAIL = 66

export interface PanelMeta {
  id: string
  order: number
  label: string
}

export type RenderSlot = (name: string, props: Record<string, unknown>, options?: { only?: string; fallback?: ReactNode }) => ReactNode

export interface MuseSidebarProps {
  collapsed: boolean
  width: number
  t: Translate
  renderSlot: RenderSlot
  startSession(): void
  toggleSidebar(): void
  selectPanel(id: string | null): void
  /** Open the settings dialog when the shell exposes a way; the sidebar falls back to its trigger. */
  openSettings?: (() => boolean) | undefined
  /** Open the agent's profile drawer. */
  openProfile(): void
  /** Open the search modal (⌘K). */
  openSearch?: (() => void) | undefined
  /** Open one settings page by id. */
  openSection?: ((id: string) => void) | undefined
  issuesUrl: string
  chatActions: ChatActions
  usePanels<S>(selector: (panels: readonly PanelMeta[]) => S): S
  usePanelInfo<S>(selector: (info: { activePanelId: string | null }) => S): S
  useShortcuts<S>(selector: (rows: readonly { id: string; keys: readonly string[]; aria?: string }[]) => S): S
  useSessions?: UseSessionList | undefined
  useSessionStatus?: UseStatusMap | undefined
  useWorkspaces?: UseWorkspaceList | undefined
}

interface RailButtonProps {
  label: string
  active?: boolean | undefined
  expanded?: boolean | undefined
  dot?: boolean | undefined
  onClick(): void
  children?: ReactNode
  buttonRef?: ((el: HTMLButtonElement | null) => void) | undefined
}

function RailButton({ label, active, expanded, dot, onClick, children, buttonRef }: RailButtonProps): ReactNode {
  return h('button', {
    type: 'button',
    className: 'nm-rail-btn',
    title: label,
    'aria-label': label,
    'aria-current': active ? 'page' : undefined,
    'aria-expanded': expanded,
    onClick,
    ref: buttonRef,
  }, children, dot ? h('span', { className: 'nm-rail-dot', 'aria-hidden': true }) : null)
}

interface MenuItem {
  id: string
  label: string
  icon: ReactNode
  hint?: string | undefined
  /** A dot after the label: something new behind it (an update). */
  dot?: boolean | undefined
  disabled?: boolean | undefined
  onSelect(): void
}

/** A small anchored menu; closes on outside pointer, Escape, or a choice. */
function CornerMenu({ anchor, items, onClose }: { anchor: HTMLElement; items: (MenuItem | 'sep')[]; onClose(): void }): ReactNode {
  const menu = useRef<HTMLDivElement>(null)
  const rect = anchor.getBoundingClientRect()
  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node
      if (menu.current?.contains(target) || anchor.contains(target)) return
      onClose()
    }
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('pointerdown', onPointer, true)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer, true)
      document.removeEventListener('keydown', onKey)
    }
  }, [anchor, onClose])
  useEffect(() => { menu.current?.querySelector('button')?.focus() }, [])
  // Open upward from the corner button, flush with the rail's right edge.
  const style = { left: rect.right + 6, bottom: Math.max(8, window.innerHeight - rect.bottom) }
  return h('div', { ref: menu, className: 'nm-menu', role: 'menu', style },
    items.map((item, index) => item === 'sep'
      ? h('div', { key: `sep-${index}`, className: 'nm-menu-sep', role: 'separator' })
      : h('button', { key: item.id, type: 'button', role: 'menuitem', className: 'nm-menu-item', disabled: item.disabled, onClick: () => { onClose(); item.onSelect() } },
          item.icon,
          h('span', { className: 'nm-menu-item-label' }, item.label, item.dot ? h('span', { className: 'nm-menu-dot', 'aria-hidden': true }) : null),
          item.hint ? h('span', { className: 'nm-menu-hint' }, item.hint) : null)))
}

export function MuseSidebar(props: MuseSidebarProps): ReactNode {
  const { collapsed, width, t, renderSlot, toggleSidebar, selectPanel, openSettings: openSettingsHook, openProfile, openSearch, issuesUrl, chatActions, usePanels, usePanelInfo, useShortcuts, useSessions, useSessionStatus, useWorkspaces } = props
  const live = useLive()
  const update = useWindowsUpdates()
  const updateView = update ? updatePresentation(update, t) : null
  const updateDot = update === null ? Boolean(live.update?.newer) : updateView?.dot === true
  const prefs = usePrefs()
  const { recent, split } = useWin()
  const panels = usePanels((rows) => rows)
  const active = usePanelInfo((info) => info.activePanelId)
  const settingsShortcut = useShortcuts((rows) => rows.find((row) => row.id === 'settings.open'))
  const shortcutsShortcut = useShortcuts((rows) => rows.find((row) => row.id === 'shortcuts.open'))
  const searchShortcut = useShortcuts((rows) => rows.find((row) => row.id === 'session.search'))
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null)
  const [docMenu, setDocMenu] = useState<{ anchor: HTMLElement; doc: RecentDoc } | null>(null)
  const [notice, setNotice] = useState<{ id: number; text: string } | null>(null)
  const [newChatOpen, setNewChatOpen] = useState(false)
  const [newChatBusy, setNewChatBusy] = useState(false)
  const menuButton = useRef<HTMLButtonElement | null>(null)
  const column = useRef<HTMLDivElement>(null)
  const searchField = useRef<HTMLInputElement | null>(null)
  const settingsSeat = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const open = () => setNewChatOpen(true)
    newChatListeners.add(open)
    return () => { newChatListeners.delete(open) }
  }, [])

  const beginChat = () => setNewChatOpen(true)
  const startLocalChat = () => {
    setNewChatOpen(false)
    chatActions.startSession()
  }
  const startDeviceChat = (device: LiveDevice) => {
    setNewChatBusy(true)
    void call<DeviceConversation>('devices/conversations', { action: 'create', device: device.id })
      .then((chat) => {
        setNewChatOpen(false)
        openDeviceConversation(chat.id)
        selectPanel(DEVICES_PANEL)
      })
      .catch((error: unknown) => setNotice({ id: Date.now(), text: failureText(t, error) }))
      .finally(() => setNewChatBusy(false))
  }

  // Settings: the shell's own way when it offers one, else the trigger the
  // settings shell renders into its (visually hidden) seat, else the chord.
  const openSettings = () => {
    if (openSettingsHook?.()) return
    const trigger = settingsSeat.current?.querySelector<HTMLButtonElement>('button')
    if (trigger) { trigger.click(); return }
    pressSettingsChord()
  }
  const openShortcuts = () => { openShortcutsReference() }

  // The column stays mounted while the collapse animates (fading), then unmounts.
  const [settled, setSettled] = useState(collapsed)
  useEffect(() => {
    if (!collapsed) { setSettled(false); return undefined }
    const timer = window.setTimeout(() => setSettled(true), COLLAPSE_SETTLE_MS)
    return () => window.clearTimeout(timer)
  }, [collapsed])
  const wide = !collapsed || !settled
  const lastWideWidth = useRef(width)
  if (!collapsed) lastWideWidth.current = width

  const schedules = panels.find((p) => p.id === SCHEDULES_PANEL)
  const plugins = panels.find((p) => p.id === PLUGINS_PANEL)
  const others = panels.filter((p) => p.id !== SCHEDULES_PANEL && p.id !== PLUGINS_PANEL && !(ROOM_PANELS as readonly string[]).includes(p.id))
  const rooms = useRooms()
  const freshFeed = rooms.feed.posts.some((p) => p.at > rooms.feedSeenAt)

  const showChats = () => { selectPanel(null) }
  const search = () => {
    if (openSearch) { openSearch(); return }
    selectPanel(null)
    if (collapsed) toggleSidebar()
    window.setTimeout(() => {
      // Our search field, or the browser's own (the first text input in the column).
      const input = searchField.current ?? column.current?.querySelector<HTMLInputElement>('input[type="search"], input[type="text"], input:not([type])')
      input?.focus()
    }, collapsed ? COLLAPSE_SETTLE_MS + 50 : 0)
  }

  // Muse's corner menu: shortcuts, report a problem, settings; then what the
  // harness adds (Schedules, plugins, other panels, the column toggle).
  const menuItems: (MenuItem | 'sep')[] = [
    { id: 'shortcuts', label: t('menuShortcuts'), icon: h(IconKeyboard, { size: 16 }), hint: keysHint(shortcutsShortcut?.keys), onSelect: openShortcuts },
    { id: 'issue', label: t('menuReport'), icon: h(IconBug, { size: 16 }), onSelect: () => {
      // under the shell a screenshot of the window goes to Downloads and the issue page opens filled in; elsewhere just the issues page
      const report = bridge()?.reportBug
      if (!report) return openLink(issuesUrl)
      void report().then(({ screenshot }) => {
        const name = screenshot.split(/[\\/]/).pop() ?? ''
        setNotice({ id: Date.now(), text: name ? t('reportSaved', { name }) : t('reportOpened') })
      }).catch(() => openLink(issuesUrl))
    } },
    { id: 'settings', label: t('menuSettings'), icon: h(IconSettings, { size: 16 }), hint: keysHint(settingsShortcut?.keys), dot: updateDot, onSelect: openSettings },
    ...(updateView?.label ? [{ id: 'update', label: updateView.label, icon: h(IconDownload, { size: 16 }), disabled: updateView.action === null, dot: updateView.dot,
      onSelect: () => { if (updateView.action) requestWindowsUpdate(updateView.action) } }] : []),
    ...(update === null && live.update?.newer ? [{ id: 'update', label: t('menuUpdate', { version: live.update.latest }), icon: h(IconDownload, { size: 16 }), onSelect: () => openLink(live.update?.page ?? REPO_URL) }] : []),
    { id: 'about', label: t('menuAbout'), icon: h(IconInfo, { size: 16 }), onSelect: () => aboutBus.open?.() },
    'sep',
    ...(schedules ? [{ id: 'schedules', label: schedules.label, icon: h('span', { style: { display: 'inline-flex', width: 16, height: 16 } }, renderSlot('sidebar.panellist', { size: 16, active: false }, { only: SCHEDULES_PANEL, fallback: h(IconCalendar, { size: 16 }) })), onSelect: () => selectPanel(SCHEDULES_PANEL) }] : []),
    ...(plugins ? [{ id: 'plugins', label: plugins.label, icon: h(IconPuzzle, { size: 16 }), onSelect: () => selectPanel(PLUGINS_PANEL) }] : []),
    ...others.map((p) => ({ id: p.id, label: p.label, icon: h('span', { style: { display: 'inline-flex', width: 16, height: 16 } }, renderSlot('sidebar.panellist', { size: 16, active: false }, { only: p.id })), onSelect: () => selectPanel(p.id) })),
    { id: 'toggle', label: collapsed ? t('menuExpand') : t('menuCollapse'), icon: h(IconPanelLeft, { size: 16 }), onSelect: toggleSidebar },
  ]
  const docItems: (MenuItem | 'sep')[] = docMenu
    ? [
        { id: 'pin', label: docMenu.doc.pinned ? t('chUnpin') : t('chPin'), icon: h(IconPin, { size: 16 }), onSelect: () => win.pinRecent(docMenu.doc.key, !docMenu.doc.pinned) },
        { id: 'drop', label: t('recentRemove'), icon: h(IconClose, { size: 16 }), onSelect: () => win.dropRecent(docMenu.doc.key) },
      ]
    : []

  // Muse's rail starts with Chats (a dot while the agent works). The face sits at
  // the top of the rail whenever the header is not showing it: in a room, or with
  // the column collapsed. The brand mark stays mounted (hidden) for the accent and
  // keep-awake effects it carries. Devices moved to Settings → Devices.
  const busy = typeof useSessions === 'function' ? useSessions((state) => state.ids.some((id) => state.byId[id]?.running === true)) : false
  const faceOnRail = collapsed || active !== null
  const openRecent = (doc: RecentDoc) => {
    win.openDoc(doc.key.startsWith('own:') ? { kind: 'own', doc: doc.key.slice(4) as 'identity' | 'soul' | 'memory' } : { kind: 'library', id: doc.key.slice(4) })
    win.touchRecent(doc.key, doc.name)
  }
  const rail = h('nav', { className: 'nm-rail', 'aria-label': t('railLabel') },
    h('div', { className: 'nm-rail-top', 'data-window-drag': true }),
    h('div', { className: 'nm-hidden' }, renderSlot('sidebar.brand.mark', { size: 36 })),
    faceOnRail ? h(RailButton, { label: live.profile.name || t('railProfile'), onClick: openProfile }, h('span', { className: `nm-rail-face${busy ? ' nm-live' : ''}` }, h(Avatar, { size: 28, profile: live.profile, mood: busy ? 'working' : 'idle' }))) : null,
    h(RailButton, { label: t('railChats'), active: active === null, dot: busy, onClick: showChats }, h(IconChat, { size: 21 })),
    h(RailButton, { label: withKeys(t('railSearch'), searchShortcut?.keys), onClick: search }, h(IconSearch, { size: 21 })),
    // Muse's rooms, in Muse's order: Feed, Ideas, Goals, Library.
    h(RailButton, { label: t('railFeed'), active: active === FEED_PANEL, dot: freshFeed && active !== FEED_PANEL, onClick: () => selectPanel(FEED_PANEL) }, h(IconFeed, { size: 21 })),
    h(RailButton, { label: t('railIdeas'), active: active === IDEAS_PANEL, onClick: () => selectPanel(IDEAS_PANEL) }, h(IconBulb, { size: 21 })),
    h(RailButton, { label: t('railGoals'), active: active === GOALS_PANEL, onClick: () => selectPanel(GOALS_PANEL) }, h(IconTarget, { size: 21 })),
    h(RailButton, { label: t('railLibrary'), active: active === LIBRARY_PANEL, onClick: () => selectPanel(LIBRARY_PANEL) }, h(IconShapes, { size: 21 })),
    // Recent documents (IDENTITY.md, a Library text…): one glyph each, a menu on right-click.
    recent.length ? h('div', { className: 'nm-rail-recent', role: 'group', 'aria-label': t('recentDocs') },
      recent.map((doc) => h('button', {
        key: doc.key,
        type: 'button',
        className: `nm-rail-btn nm-rail-doc${doc.pinned ? ' nm-pinned' : ''}`,
        title: doc.name,
        'aria-label': doc.name,
        onClick: () => openRecent(doc),
        onContextMenu: (event: { preventDefault(): void; currentTarget: HTMLElement }) => { event.preventDefault(); setDocMenu({ anchor: event.currentTarget, doc }) },
      }, h(IconDoc, { size: 20 }), h('span', { className: 'nm-rail-doc-tag' }, docTag(doc.name))))) : null,
    h('div', { className: 'nm-rail-spacer' }),
    h(RailButton, { label: t('railNew'), onClick: beginChat }, h(IconPlus, { size: 21 })),
    h(RailButton, { label: t('railMore'), expanded: menuAnchor !== null, dot: updateDot, onClick: () => setMenuAnchor((current) => (current ? null : menuButton.current)), buttonRef: (el) => { menuButton.current = el } }, h(IconMenu, { size: 21 })),
    // The settings shell lives in this seat: its trigger is hidden here (the
    // menu opens it), but its dialog and the onboarding steps mount through it.
    h('div', { ref: settingsSeat, className: 'nm-hidden' }, renderSlot('sidebar.settings', { wide: false })),
    h('div', { className: 'nm-hidden' }, renderSlot('sidebar.toggle.badge', {})))

  const browser = prefs.showHarness || typeof useSessions !== 'function'
  // In a room (Feed, Ideas, Goals, Library…) Muse shows only the rail: the room has the
  // rest of the window, and its own top-left toggle brings the chat back beside it.
  const roomMode = (active !== null || split !== null) && !browser
  useEffect(() => {
    if (roomMode) document.documentElement.dataset['nmRoom'] = ''
    else delete document.documentElement.dataset['nmRoom']
    return () => { delete document.documentElement.dataset['nmRoom'] }
  }, [roomMode])
  const chats = wide && !roomMode
    ? h('div', { ref: column, className: `nm-col${collapsed ? ' nm-fading' : ''}`, style: { width: Math.max(0, (collapsed ? lastWideWidth.current : width) - RAIL) } },
        h('div', { className: 'nm-col-top', 'data-window-drag': true }),
        browser
          ? h('div', { className: 'nm-col-body' },
              h('div', { className: 'nm-col-head' },
                h('span', null, t('railChats')),
                h('div', { className: 'nm-col-head-actions' },
                  h('button', { type: 'button', className: 'nm-icon-btn', title: t('railNew'), 'aria-label': t('railNew'), onClick: beginChat }, h(IconPlus, { size: 18 })))),
              renderSlot('sidebar.workspaces', { wide: true, expandSidebar: () => { if (collapsed) toggleSidebar() } }))
          : h('div', { className: 'nm-col-body' },
              h(MuseChats, { t, useSessions, useSessionStatus, useWorkspaces, actions: chatActions, searchRef: (el) => { searchField.current = el } })),
        h('div', { className: 'nm-col-foot' }, renderSlot('sidebar.footer.action', { wide: true })))
    : null

  return h('div', { className: 'nm-sidebar', style: { width: wide && !roomMode ? (collapsed ? lastWideWidth.current : width) : RAIL } },
    rail,
    chats,
    newChatOpen ? h('div', {
      style: { position: 'fixed', inset: 0, zIndex: 70, display: 'grid', placeItems: 'center', background: 'rgba(0,0,0,.38)' },
      onClick: () => { if (!newChatBusy) setNewChatOpen(false) },
    }, h('div', { onClick: (event: { stopPropagation(): void }) => event.stopPropagation() },
      h(DeviceChatStartDialog, {
        t,
        busy: newChatBusy,
        devices: live.hub.devices.filter((device) => device.id !== live.hub.deviceId && device.kind !== 'web'),
        onLocal: startLocalChat,
        onDevice: startDeviceChat,
        onDismiss: () => setNewChatOpen(false),
      }))) : null,
    menuAnchor ? h(CornerMenu, { anchor: menuAnchor, items: menuItems, onClose: () => setMenuAnchor(null) }) : null,
    docMenu ? h(CornerMenu, { anchor: docMenu.anchor, items: docItems, onClose: () => setDocMenu(null) }) : null,
    notice ? h('div', { style: { position: 'fixed', top: 10, left: '50%', transform: 'translateX(-50%)', zIndex: 60, pointerEvents: 'none' } },
      h(Toast, { key: notice.id, text: notice.text, holdMs: 8000, onDone: () => setNotice(null) })) : null)
}

/** `⌘ ,` style hint from the catalog's key names; empty when unbound. */
function keysHint(keys: readonly string[] | undefined): string | undefined {
  if (!keys || keys.length === 0) return undefined
  return keys.join(' ')
}
/** "Search ⌘K" for a tooltip. */
function withKeys(label: string, keys: readonly string[] | undefined): string {
  const hint = keysHint(keys)
  return hint ? `${label} ${hint}` : label
}
/** The short tag under a recent document's glyph: the stem's first two letters ("ID" for IDENTITY.md, "So" for SOUL.md). */
function docTag(name: string): string {
  return name.replace(/\.[a-z0-9]+$/i, '').slice(0, 2)
}
