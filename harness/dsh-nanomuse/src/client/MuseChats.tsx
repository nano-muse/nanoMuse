/**
 * The chats column, the way the Muse desktop lays it out: a search field with
 * a small menu beside it, **Main chat** — the one long conversation with the
 * agent — and **Side chats** with a + for the things that do not belong in it.
 * Behind the names are the harness's sessions: the main chat is the session
 * this computer remembers as such (the oldest one until the person picks
 * another), the side chats are every other top-level session that is not
 * archived; subagent sessions stay inside their parents. A row carries a dot
 * while its turn runs and a mark when it waits for the person; its menu makes
 * it the main chat, pins, renames or archives it. The harness's own workspace
 * browser is one switch away (Settings → General → Developer) for people who
 * want workspaces as folders.
 *
 * Signed in, the chats are the account's (C8, one thread): the main chat is the
 * session the account's main conversation lives in, a conversation from another
 * device is a chat here from the moment it is pulled, and nothing in the column
 * says where a chat was written — the bubbles do (`RemoteBubbles.ts`).
 */
import { createElement as h, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { call, type Translate } from './api.ts'
import { IconMore, IconPlus, IconSearch } from './icons.tsx'
import { composing } from './keys.ts'
import { useLive } from './live.ts'
import { useRooms } from './rooms.ts'

const MAIN_KEY = 'nanomuse.mainChat'

/**
 * Conversation sync as the chats column needs it (contract C8, one thread): the session the
 * account's main conversation lives in, the sessions that hold a synced conversation (listed
 * though no turn ran here yet), and the sessions whose conversation was deleted on another
 * device, which the column archives (the host has no archive) and reports back.
 */
interface SyncList {
  enabled: boolean
  mainSession: string
  sessions: Set<string>
  /** Sessions of another account than the one signed in (C10): not listed, not searched; empty when signed out. */
  foreign: Set<string>
  toArchive: string[]
  cleared: Set<string>
}
const NO_SYNC: SyncList = { enabled: true, mainSession: '', sessions: new Set(), foreign: new Set(), toArchive: [], cleared: new Set() }

/** The host's sync view; read again whenever the host's sync revision moves. */
export function useSyncList(): SyncList {
  const rev = useLive().sync?.rev ?? 0
  const [list, setList] = useState<SyncList>(NO_SYNC)
  useEffect(() => {
    let alive = true
    call<{ enabled: boolean; mainSession?: string; sessions?: string[]; foreign?: string[]; toArchive?: string[]; cleared?: string[] }>('sync/state')
      .then((v) => { if (alive) setList({ enabled: v.enabled, mainSession: v.mainSession ?? '', sessions: new Set(v.sessions ?? []), foreign: new Set(v.foreign ?? []), toArchive: v.toArchive ?? [], cleared: new Set(v.cleared ?? []) }) })
      .catch(() => undefined)
    return () => { alive = false }
  }, [rev])
  return list
}

export interface ChatSummary {
  id: string
  displayTitle: string
  parentId?: string | undefined
  origin?: 'subagent' | undefined
  running: boolean
  retainedBy: { mainView?: number | undefined }
  blank: boolean
  updatedAt: number
}
export interface ChatListState {
  ids: string[]
  byId: Record<string, ChatSummary>
  phase: string
}
export interface ChatStatus {
  running?: boolean | undefined
  pendingInteraction?: unknown
  completionUnread?: boolean | undefined
}
export type UseSessionList = <S>(selector: (state: ChatListState) => S) => S
export type UseStatusMap = <S>(selector: (snapshot: ReadonlyMap<string, ChatStatus>) => S) => S
export type UseWorkspaceList = <S>(selector: (snapshot: { archivedSessionIds: readonly string[]; pinnedSessionIds: readonly string[] }) => S) => S

export interface ChatActions {
  openSession(id: string): void
  startSession(): void
  archiveSession(id: string): Promise<void>
  pinSession(id: string): Promise<void>
  unpinSession(id: string): Promise<void>
  renameSession(id: string, title: string): Promise<void>
  openArchived(): void
}

export interface MuseChatsProps {
  t: Translate
  useSessions: UseSessionList
  useSessionStatus?: UseStatusMap | undefined
  useWorkspaces?: UseWorkspaceList | undefined
  actions: ChatActions
  /** The search field is focused from outside (the rail's Search). */
  searchRef?: ((el: HTMLInputElement | null) => void) | undefined
}

function readMain(): string | undefined {
  try {
    return window.localStorage.getItem(MAIN_KEY) ?? undefined
  } catch {
    return undefined
  }
}
/** The session this computer treats as the main chat, if it has picked one. */
export function mainChatId(): string | undefined {
  return readMain()
}
const mainListeners = new Set<() => void>()
/** The first run names the main chat before the list has seen it; the list is told. */
export function setMainChatId(id: string): void {
  writeMain(id)
  for (const listener of mainListeners) listener()
}
function writeMain(id: string | undefined): void {
  try {
    if (id) window.localStorage.setItem(MAIN_KEY, id)
    else window.localStorage.removeItem(MAIN_KEY)
  } catch {
    // private mode: the oldest session stays the main chat
  }
}

interface MenuItem { id: string; label: string; onSelect(): void }

/** The row's small menu, anchored under its button. */
function RowMenu({ anchor, items, onClose }: { anchor: HTMLElement; items: MenuItem[]; onClose(): void }): ReactNode {
  const menu = useRef<HTMLDivElement>(null)
  const rect = anchor.getBoundingClientRect()
  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node
      if (menu.current?.contains(target) || anchor.contains(target)) return
      onClose()
    }
    const onKey = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('pointerdown', onPointer, true)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer, true)
      document.removeEventListener('keydown', onKey)
    }
  }, [anchor, onClose])
  useEffect(() => { menu.current?.querySelector('button')?.focus() }, [])
  const below = rect.bottom + 180 < window.innerHeight
  const style = below ? { left: rect.left, top: rect.bottom + 4 } : { left: rect.left, bottom: window.innerHeight - rect.top + 4 }
  return h('div', { ref: menu, className: 'nm-menu', role: 'menu', style },
    items.map((item) => h('button', { key: item.id, type: 'button', role: 'menuitem', className: 'nm-menu-item', onClick: () => { onClose(); item.onSelect() } },
      h('span', { className: 'nm-menu-item-label' }, item.label))))
}

interface RowProps {
  t: Translate
  chat: ChatSummary
  label: string
  main: boolean
  pinned: boolean
  selected: boolean
  useSessionStatus: UseStatusMap | undefined
  actions: ChatActions
  onMakeMain(): void
}

function ChatRow({ t, chat, label, main, pinned, selected, useSessionStatus, actions, onMakeMain }: RowProps): ReactNode {
  const status = typeof useSessionStatus === 'function' ? useSessionStatus((map) => map.get(chat.id)) : undefined
  const running = status?.running ?? chat.running
  const waiting = status?.pendingInteraction !== undefined
  const unread = status?.completionUnread === true
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(label)
  const more = useRef<HTMLButtonElement | null>(null)

  // One outcome per edit: Enter commits (the blur that follows must not commit again), Escape
  // discards (the blur that follows must not commit at all); an IME's Enter picks a candidate.
  const settled = useRef(false)
  const begin = () => { settled.current = false; setDraft(label); setEditing(true) }
  const commit = () => {
    if (settled.current) return
    settled.current = true
    const title = draft.trim()
    setEditing(false)
    if (title && title !== label) void actions.renameSession(chat.id, title).catch(() => undefined)
  }
  const cancel = () => {
    settled.current = true
    setEditing(false)
  }
  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' && !composing(event)) { event.preventDefault(); commit() }
    if (event.key === 'Escape') { event.preventDefault(); cancel() }
  }
  // Muse's row menu: pin, rename, archive (Muse says delete; the harness keeps
  // archived chats under the column's menu) — and ours: make this the main chat.
  const items: MenuItem[] = [
    ...(main ? [] : [{ id: 'pin', label: pinned ? t('chUnpin') : t('chPin'), onSelect: () => { void (pinned ? actions.unpinSession(chat.id) : actions.pinSession(chat.id)).catch(() => undefined) } }]),
    { id: 'rename', label: t('chRename'), onSelect: begin },
    ...(main ? [] : [{ id: 'archive', label: t('chArchive'), onSelect: () => { void actions.archiveSession(chat.id).catch(() => undefined) } }]),
    ...(main ? [] : [{ id: 'main', label: t('chMakeMain'), onSelect: onMakeMain }]),
  ]

  return h('div', { className: `nm-chat-row${selected ? ' nm-selected' : ''}${main ? ' nm-main' : ''}`, 'data-session-id': chat.id },
    editing
      ? h('input', { className: 'nm-chat-edit', value: draft, autoFocus: true, 'aria-label': t('chRename'), onChange: (e: FormEvent<HTMLInputElement>) => setDraft(e.currentTarget.value), onBlur: commit, onKeyDown: onKey })
      : h('button', { type: 'button', className: 'nm-chat-open', 'aria-current': selected ? 'page' : undefined, onClick: () => actions.openSession(chat.id), onDoubleClick: begin },
          h('span', { className: 'nm-chat-title' }, label),
          waiting
            ? h('span', { className: 'nm-chat-mark nm-wait', title: t('chWaiting'), 'aria-label': t('chWaiting') }, 'ℹ')
            : running
              ? h('span', { className: 'nm-chat-dot nm-live', title: t('chRunning'), 'aria-label': t('chRunning') })
              : unread ? h('span', { className: 'nm-chat-dot', 'aria-hidden': true }) : null),
    editing ? null : h('button', { type: 'button', className: 'nm-chat-more', 'aria-label': t('chMore'), 'aria-haspopup': 'menu', 'aria-expanded': menuAnchor !== null, ref: (el: HTMLButtonElement | null): void => { more.current = el }, onClick: () => setMenuAnchor((current) => (current ? null : more.current)) }, h(IconMore, { size: 16 })),
    menuAnchor ? h(RowMenu, { anchor: menuAnchor, items, onClose: () => setMenuAnchor(null) }) : null)
}

export function MuseChats({ t, useSessions, useSessionStatus, useWorkspaces, actions, searchRef }: MuseChatsProps): ReactNode {
  const state = useSessions((s) => s)
  const archived = typeof useWorkspaces === 'function' ? useWorkspaces((w) => w.archivedSessionIds) : []
  const pinned = typeof useWorkspaces === 'function' ? useWorkspaces((w) => w.pinnedSessionIds) : []
  const [query, setQuery] = useState('')
  const [mainStored, setMainStored] = useState<string | undefined>(readMain)
  useEffect(() => {
    const listener = () => setMainStored(readMain())
    mainListeners.add(listener)
    return () => { mainListeners.delete(listener) }
  }, [])
  const [headMenu, setHeadMenu] = useState<HTMLElement | null>(null)
  const headMore = useRef<HTMLButtonElement | null>(null)

  const archivedSet = new Set(archived)
  const pinnedSet = new Set(pinned)
  const sync = useSyncList()
  // the rooms' running batches (the feed being written) are the agent's work, not chats of the person's
  const batches = new Set(useRooms().batches)
  // signed in, the column shows this account's chats and the ones never synced (C10); another account's stay, hidden
  const visible = state.ids
    .map((id) => state.byId[id])
    .filter((s): s is ChatSummary => s !== undefined && s.origin !== 'subagent' && !s.parentId && !archivedSet.has(s.id) && !sync.cleared.has(s.id) && !sync.foreign.has(s.id) && !batches.has(s.id))
  const current = Object.values(state.byId).find((s) => (s.retainedBy.mainView ?? 0) > 0)?.id

  // The main chat: the one the account's main conversation lives in (C8) while it exists, else
  // the remembered one, else the oldest, else the one on screen (a first session being created
  // becomes the main chat).
  let mainId = sync.mainSession && visible.some((s) => s.id === sync.mainSession) ? sync.mainSession : undefined
  if (!mainId) mainId = mainStored && visible.some((s) => s.id === mainStored) ? mainStored : undefined
  if (!mainId && visible.length > 0) {
    const candidates = visible.filter((s) => !s.blank || s.id === current || sync.sessions.has(s.id))
    mainId = [...candidates].sort((a, b) => a.updatedAt - b.updatedAt)[0]?.id ?? visible[0]!.id
  }
  useEffect(() => {
    if (state.phase !== 'ready') return
    if (mainId !== mainStored) { writeMain(mainId); setMainStored(mainId) }
  }, [mainId, mainStored, state.phase])
  // The host syncs the main chat as the account's one main conversation (C7, C8): it is told
  // which session that is, and answers with the one the conversation already lives in.
  useEffect(() => {
    if (state.phase !== 'ready' || !mainId) return
    void call<{ sessionId?: string } | undefined>('sync/main', { sessionId: mainId })
      .then((r) => { if (r?.sessionId && r.sessionId !== mainId) { writeMain(r.sessionId); setMainStored(r.sessionId) } })
      .catch(() => undefined)
  }, [mainId, state.phase])
  // A chat deleted on another device goes to the archive here, and the host is told.
  const archiving = useRef(new Set<string>())
  useEffect(() => {
    const due = sync.toArchive.filter((id) => !archiving.current.has(id))
    if (due.length === 0) return
    for (const id of due) archiving.current.add(id)
    void Promise.all(due.map((id) => (archivedSet.has(id) || !state.byId[id] ? Promise.resolve() : actions.archiveSession(id).catch(() => undefined))))
      .then(() => call('sync/archived', { sessionIds: due }))
      .catch(() => undefined)
      .finally(() => { for (const id of due) archiving.current.delete(id) })
  }, [sync.toArchive])

  const previousCurrent = useRef<string | undefined>(current)
  const awaitingMain = useRef<string | undefined>()
  useEffect(() => {
    const old = current ?? previousCurrent.current
    if (old && sync.cleared.has(old)) awaitingMain.current = old
    else if (current) awaitingMain.current = undefined
    previousCurrent.current = current
    // Archiving clears the old selection. Wait for the host's replacement instead
    // of creating extra blank sessions while the sync state is being saved.
    if (awaitingMain.current && sync.mainSession && !sync.cleared.has(sync.mainSession)) {
      awaitingMain.current = undefined
      previousCurrent.current = undefined
      actions.openSession(sync.mainSession)
    }
  }, [current, sync.cleared, sync.mainSession])

  const main = visible.find((s) => s.id === mainId)
  const q = query.trim().toLowerCase()
  // a synced chat is listed from the moment it exists here, though no turn ran here yet
  const side = visible
    .filter((s) => s.id !== mainId && (!s.blank || s.id === current || sync.sessions.has(s.id)))
    .filter((s) => q === '' || s.displayTitle.toLowerCase().includes(q))
    .sort((a, b) => {
      const pa = pinnedSet.has(a.id) ? 1 : 0
      const pb = pinnedSet.has(b.id) ? 1 : 0
      if (pa !== pb) return pb - pa
      return b.updatedAt - a.updatedAt
    })
  const mainMatches = q === '' || t('chMain').toLowerCase().includes(q) || (main?.displayTitle.toLowerCase().includes(q) ?? false)

  const openMain = () => {
    if (main) actions.openSession(main.id)
    else actions.startSession()
  }
  const headItems: MenuItem[] = [
    { id: 'archived', label: t('chArchived'), onSelect: actions.openArchived },
  ]

  return h('div', { className: 'nm-chats' },
    h('div', { className: 'nm-chats-head' },
      h('label', { className: 'nm-chats-search' },
        h(IconSearch, { size: 15 }),
        h('input', { ref: searchRef, type: 'search', value: query, placeholder: t('chSearch'), 'aria-label': t('chSearch'), onChange: (e: FormEvent<HTMLInputElement>) => setQuery(e.currentTarget.value) })),
      h('button', { type: 'button', className: 'nm-icon-btn', 'aria-label': t('chMore'), 'aria-haspopup': 'menu', 'aria-expanded': headMenu !== null, ref: (el: HTMLButtonElement | null): void => { headMore.current = el }, onClick: () => setHeadMenu((c) => (c ? null : headMore.current)) }, h(IconMore, { size: 18 })),
      headMenu ? h(RowMenu, { anchor: headMenu, items: headItems, onClose: () => setHeadMenu(null) }) : null),
    h('div', { className: 'nm-chats-list' },
      mainMatches
        ? (main
            ? h(ChatRow, { t, chat: main, label: t('chMain'), main: true, pinned: false, selected: current === main.id, useSessionStatus, actions, onMakeMain: () => undefined })
            : h('div', { className: 'nm-chat-row nm-main' },
                h('button', { type: 'button', className: 'nm-chat-open', onClick: openMain }, h('span', { className: 'nm-chat-title' }, t('chMain')))))
        : null,
      h('div', { className: 'nm-chats-section' },
        h('span', null, t('chSide')),
        h('button', { type: 'button', className: 'nm-icon-btn nm-icon-btn-sm', 'aria-label': t('chNewSide'), title: t('chNewSide'), onClick: actions.startSession }, h(IconPlus, { size: 16 }))),
      side.length === 0
        ? h('div', { className: 'nm-chats-empty' }, q === '' ? t('chEmpty') : t('chNoMatch'))
        : side.map((chat) => h(ChatRow, {
            key: chat.id,
            t,
            chat,
            label: chat.blank && !sync.sessions.has(chat.id) ? t('chBlank') : chat.displayTitle || t('chBlank'),
            main: false,
            pinned: pinnedSet.has(chat.id),
            selected: current === chat.id,
            useSessionStatus,
            actions,
            // the host has the last word: while the account's main conversation lives in a session, that one stays the main chat
            onMakeMain: () => {
              void call<{ sessionId?: string } | undefined>('sync/main', { sessionId: chat.id })
                .then((r) => { const id = r?.sessionId || chat.id; writeMain(id); setMainStored(id) })
                .catch(() => { writeMain(chat.id); setMainStored(chat.id) })
            },
          }))))
}
