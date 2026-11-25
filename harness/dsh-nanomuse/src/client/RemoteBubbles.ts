/**
 * The turns of a conversation written on the account's other devices, in the chat here
 * (contract C8, one thread). The host keeps the remote turns in its sync store (see
 * `sync.ts`). Show the person's prompt on the right and the Muse's formatted reply
 * on the left, with the source device under each. Hide a matching legacy context row. A turn
 * older than a prompt typed here before it arrived is shown before that prompt (the host
 * says which: `before`), so the thread reads in time order whatever order the log has.
 *
 * While the other device works on its last prompt (contract C9, presence), a quiet line
 * stands under that bubble — "kwai is working…" — until its reply arrives, presence says
 * done, or ten minutes pass.
 *
 * Like `FenceCards.ts`: a MutationObserver over the document, idempotent sweeps, nothing
 * of React's touched but a `display` on the row; a bubble whose row is gone goes with it.
 * The sweeps are cheap where it matters: a session with no turn from elsewhere is left
 * alone (a long transcript streaming a reply mutates many times a second), mutations made
 * by the bubbles themselves are ignored, and the rest are coalesced over 100 ms.
 */
import { createElement as h } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { call, type Translate } from './api.ts'
import { subscribeLive } from './live.ts'
import { nav, peekRooms, roomsCall, subscribeRooms } from './rooms.ts'
import { Markdown } from './ui.tsx'

const DONE = 'data-nm-remote'
const KEY = 'data-nm-remote-key'

interface RemoteRow {
  /** The dsh message id: the row's `data-chat-node-key` is `13:input-message<id>`. */
  id: string
  mid: string
  role: 'user' | 'assistant'
  text: string
  at: number
  device: string
  deviceName: string
  localCheckIn?: boolean
  /** The node key of the local prompt this turn is older than, when it is. */
  before: string | null
}
/** Another device working on this conversation right now (C9). */
interface Working {
  from: string
  deviceName: string
  /** Unix epoch milliseconds. */
  at: number
  /** What its run is doing (relay 0.31); absent or `working` from an older relay or device. */
  state?: 'working' | 'waiting'
  /** The step's own words; '' or absent when the run gave none. */
  detail?: string
}
interface Remote {
  lines: RemoteRow[]
  prompts?: string[]
  hidden: string[]
  working: Working | null
}

/** A `working` presence is over this long after its `at` (C9). */
const WORKING_TTL_MS = 10 * 60_000
/** Mutations within this window become one sweep. */
const SWEEP_DELAY_MS = 100
/** Minimum interval between focus-triggered background pulls. */
const FOCUS_PULL_MS = 3_000

const nodeKey = (id: string): string => `13:input-message${id}`

function el(tag: string, className: string, text?: string): HTMLElement {
  const node = document.createElement(tag)
  node.className = className
  if (text !== undefined) node.textContent = text
  return node
}

function bubble(t: Translate, row: RemoteRow, markdownRoots: Map<HTMLElement, Root>): HTMLElement {
  const root = el('div', `nm-remote nm-remote-${row.role}`)
  if (row.localCheckIn) root.setAttribute('data-nm-checkin', '')
  root.setAttribute(KEY, nodeKey(row.id))
  root.setAttribute('data-nm-remote-mid', row.mid)
  const body = el('div', 'nm-remote-bubble')
  if (row.role === 'assistant' && !row.localCheckIn) {
    const markdown = createRoot(body)
    markdownRoots.set(body, markdown)
    markdown.render(h(Markdown, { text: row.text }))
  } else {
    body.textContent = row.text
  }
  root.append(body)
  const from = el('div', 'nm-remote-from', row.localCheckIn ? t('chatCheckIn') : t('chFrom', { device: row.deviceName || row.device || '?' }))
  if (row.at > 0) from.title = new Date(row.at).toLocaleString()
  root.append(from)
  return root
}

/** The element the chat lays out: the row itself, or the turn-process group it sits in. */
function flowItem(node: HTMLElement, content: HTMLElement): HTMLElement {
  let item = node
  while (
    item.parentElement &&
    item.parentElement !== content &&
    !item.parentElement.hasAttribute('data-chat-flow') &&
    item.parentElement.hasAttribute('data-chat-group-key')
  ) {
    item = item.parentElement
  }
  return item
}

function placeBefore(target: HTMLElement, node: HTMLElement): void {
  if (target.previousElementSibling !== node) target.insertAdjacentElement('beforebegin', node)
}

function placeAfter(target: HTMLElement, node: HTMLElement): void {
  if (target.nextElementSibling !== node) target.insertAdjacentElement('afterend', node)
}

/** Watch the document for the other devices' turns and show them as bubbles; returns the stop function. */
export function renderRemoteBubbles(t: Translate): () => void {
  const cache = new Map<string, Remote>()
  const markdownRoots = new Map<HTMLElement, Root>()
  const dressed = new WeakSet<HTMLElement>()
  const inflight = new Set<string>()
  const refreshNeeded = new Set<string>()
  const acknowledging = new Set<string>()
  let generation = 0
  let scheduled: ReturnType<typeof setTimeout> | undefined
  let expiry: ReturnType<typeof setTimeout> | undefined
  let lastFocusPull = 0
  let stopped = false

  const fetchFor = (sessionId: string) => {
    if (inflight.has(sessionId)) {
      refreshNeeded.add(sessionId)
      return
    }
    const version = generation
    inflight.add(sessionId)
    call<Remote>(`sync/remote?session=${encodeURIComponent(sessionId)}`)
      .then((remote) => {
        if (stopped || version !== generation) return
        cache.set(sessionId, {
          lines: remote.lines ?? [],
          prompts: remote.prompts ?? [],
          hidden: remote.hidden ?? [],
          working: remote.working ?? null,
        })
        schedule()
      })
      .catch(() => undefined)
      .finally(() => {
        inflight.delete(sessionId)
        if (!stopped && refreshNeeded.delete(sessionId)) fetchFor(sessionId)
      })
  }

  /** The line's words: the step the run reported, waiting on the person, or plain working (an older device, or the model writing). */
  const workingText = (w: Working | null, device: string): string => {
    if (w?.state === 'waiting') return t('chWorkingWait', { device })
    if (w?.detail) return t('chWorkingStep', { device, detail: w.detail })
    return t('chWorking', { device })
  }

  /** The bubble the working line belongs under: the other device's last line, when it is a prompt without a reply yet. */
  const workingLine = (remote: Remote): RemoteRow | undefined => {
    const w = remote.working
    if (!w || Date.now() - w.at >= WORKING_TTL_MS) return undefined
    const last = remote.lines.at(-1)
    return last && last.role === 'user' && (!w.from || last.device === w.from) ? last : undefined
  }

  const dress = (sessionId: string, content: HTMLElement, remote: Remote) => {
    const hidden = new Set(remote.hidden)
    const rows = new Map<string, HTMLElement>()
    for (const node of content.querySelectorAll<HTMLElement>('[data-chat-node-key]')) rows.set(node.getAttribute('data-chat-node-key') ?? '', node)
    const bubbles = new Map<string, HTMLElement>()
    for (const node of content.querySelectorAll<HTMLElement>('.nm-remote')) bubbles.set(node.getAttribute(KEY) ?? '', node)
    const knownPrompts = new Set(remote.prompts ?? [])
    for (const line of remote.lines) if (line.before) knownPrompts.add(line.before)
    let firstUnseenPrompt: HTMLElement | undefined
    for (const [k, node] of rows) {
      if (k.startsWith('13:input-message') && !knownPrompts.has(k)) {
        firstUnseenPrompt ??= node
      }
    }
    if (firstUnseenPrompt) fetchFor(sessionId)
    const flow = content.querySelector<HTMLElement>('[data-chat-flow]')
    const pendingTurn = flow?.querySelector<HTMLElement>('[data-submission-echo], [data-chat-running]') ?? null
    const knownRows = [...rows.entries()].filter(([k]) => !k.startsWith('13:input-message') || knownPrompts.has(k))
    let tail: HTMLElement | null = null
    const under = workingLine(remote)
    for (const line of remote.lines) {
      const key = nodeKey(line.id)
      const row = rows.get(key)
      if (row && row.getAttribute(DONE) !== 'done') {
        row.setAttribute(DONE, 'done')
        row.style.display = 'none'
      }
      let shown = bubbles.get(key)
      if (!shown) shown = bubble(t, line, markdownRoots)
      let anchor = line.before ? rows.get(line.before) : undefined
      if (!anchor && line.before && remote.prompts) {
        const idx = remote.prompts.indexOf(line.before)
        if (idx >= 0) {
          for (let i = idx + 1; i < remote.prompts.length; i++) {
            const later = rows.get(remote.prompts[i]!)
            if (later) {
              anchor = later
              break
            }
          }
        }
      }
      if (!anchor && !line.before && firstUnseenPrompt) anchor = firstUnseenPrompt
      if (anchor) {
        placeBefore(flowItem(anchor, content), shown)
      } else if (row) {
        placeAfter(flowItem(row, content), shown)
      } else if (tail) {
        placeAfter(tail, shown)
      } else if (line.before && remote.prompts && remote.prompts.includes(line.before) && rows.size > 0) {
        const firstRow = [...rows.values()][0]!
        placeBefore(flowItem(firstRow, content), shown)
      } else {
        const last = (firstUnseenPrompt ? knownRows.map(([, n]) => n) : [...rows.values()]).at(-1)
        if (last) {
          placeAfter(flowItem(last, content), shown)
        } else if (pendingTurn) {
          placeBefore(pendingTurn, shown)
        } else if (flow) {
          if (flow.firstElementChild && !flow.firstElementChild.classList.contains('nm-remote')) {
            placeBefore(flow.firstElementChild as HTMLElement, shown)
          } else if (shown.parentElement !== flow) {
            flow.append(shown)
          }
        } else {
          const seat = content.querySelector<HTMLElement>('[data-conversation-scroll] > [data-composer-seat]')
          if (seat) placeBefore(seat, shown)
          else if (shown.parentElement !== content) content.append(shown)
        }
      }
      if (!row && !line.before) tail = shown
      bubbles.delete(key)
      shown.style.display = hidden.has(line.mid) ? 'none' : ''
      if (line.localCheckIn && !document.hidden && document.hasFocus() &&
          peekRooms().checkIns.some(m => m.id === line.id && m.unread) && !acknowledging.has(line.id)) {
        const rect = shown.getBoundingClientRect()
        const clip = content.getBoundingClientRect()
        if (rect.height > 0 && rect.bottom > Math.max(clip.top, 0) && rect.top < Math.min(clip.bottom, window.innerHeight)) {
          acknowledging.add(line.id)
          void roomsCall('checkins/read', { sessionId, id: line.id }).catch(() => undefined).finally(() => acknowledging.delete(line.id))
        }
      }
      // the working line under the other device's last prompt (C9), and nowhere else; its
      // words follow the run's step (0.31)
      const working = shown.querySelector('.nm-remote-working')
      if (line === under) {
        const text = workingText(remote.working, remote.working?.deviceName || line.deviceName || line.device || '?')
        if (!working) shown.append(el('div', 'nm-remote-working', text))
        else if (working.textContent !== text) working.textContent = text
      } else working?.remove()
    }
    // a bubble whose row left the document (paged out, re-rendered elsewhere) goes; the next sweep brings it back
    for (const shown of bubbles.values()) shown.remove()
    if (under && remote.working && !expiry) {
      // the line goes away by itself ten minutes after the last `at`
      expiry = setTimeout(() => {
        expiry = undefined
        schedule()
      }, Math.max(0, remote.working.at + WORKING_TTL_MS - Date.now()) + 50)
    }
  }

  const sweep = () => {
    scheduled = undefined
    for (const content of document.querySelectorAll<HTMLElement>('[data-conversation-content][data-conversation-session]')) {
      const sessionId = content.getAttribute('data-conversation-session') ?? ''
      if (!sessionId) continue
      const remote = cache.get(sessionId)
      if (!remote) {
        fetchFor(sessionId)
        continue
      }
      // nothing from elsewhere in this chat: its rows are not read at all
      if (remote.lines.length === 0) {
        if (dressed.delete(content)) {
          for (const node of content.querySelectorAll('.nm-remote')) node.remove()
        }
        continue
      }
      dress(sessionId, content, remote)
      dressed.add(content)
    }
    // The host can remove a whole conversation without removing its bubbles individually.
    for (const [body, root] of markdownRoots) {
      if (!body.isConnected) {
        root.unmount()
        markdownRoots.delete(body)
      }
    }
  }
  const schedule = () => {
    if (scheduled || stopped) return
    scheduled = setTimeout(() => window.requestAnimationFrame(sweep), SWEEP_DELAY_MS)
  }
  /** Whether a mutation is one the bubbles made themselves: no sweep for those. */
  const ours = (m: MutationRecord): boolean => {
    const target = m.target instanceof Element ? m.target : m.target.parentElement
    if (target?.closest('.nm-remote')) return true
    const nodes = [...m.addedNodes, ...m.removedNodes]
    return nodes.length > 0 && nodes.every((n) => n instanceof Element && n.classList.contains('nm-remote'))
  }
  const observer = new MutationObserver((records) => {
    if (records.some((m) => !ours(m))) schedule()
  })
  observer.observe(document.body, { childList: true, subtree: true })
  // the host's sync revision moved (a pull, a tombstone): the sessions on screen are read again
  let rev = -1
  const offLive = subscribeLive((live) => {
    const next = live.sync?.rev ?? 0
    if (next === rev) return
    rev = next
    generation++
    cache.clear()
    schedule()
  })
  let previousStamp = ''
  let previousScope: string | undefined
  let latestId: string | undefined
  let notice: Notification | undefined
  const offRooms = subscribeRooms(() => {
    const { checkIns, feed } = peekRooms()
    const scope = feed.routine.checkInScope
    const latest = checkIns.at(-1)
    const stamp = JSON.stringify([scope, checkIns])
    if (stamp === previousStamp) return
    previousStamp = stamp
    if (scope !== previousScope) {
      notice?.close()
      for (const node of document.querySelectorAll('[data-nm-checkin]')) node.remove()
    } else if (latest && latest.id !== latestId && latest.unread && Date.now() - latest.at < 120_000 &&
        (!document.hasFocus() || document.hidden) && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      notice?.close()
      try {
        const n = new Notification('nanoMuse', { body: t('chatCheckIn'), tag: 'nanomuse-chat-checkin' })
        n.onclick = () => {
          if (peekRooms().feed.routine.checkInScope === scope && peekRooms().checkIns.some(m => m.id === latest.id)) {
            window.focus()
            nav.openSession(latest.sessionId)
          }
          n.close()
        }
        notice = n
      } catch { /* The unread chat remains available when the OS declines notifications. */ }
    }
    previousScope = scope
    latestId = latest?.id
    generation++
    cache.clear()
    schedule()
  })
  const pullOnFocus = () => {
    if (stopped || document.visibilityState === 'hidden') return
    schedule()
    const now = Date.now()
    if (now - lastFocusPull < FOCUS_PULL_MS) return
    lastFocusPull = now
    void call('sync/pull', {}).catch(() => undefined)
  }
  document.addEventListener('scroll', schedule, true)
  window.addEventListener('focus', pullOnFocus)
  document.addEventListener('visibilitychange', pullOnFocus)
  schedule()
  return () => {
    stopped = true
    observer.disconnect()
    offLive()
    offRooms()
    notice?.close()
    document.removeEventListener('scroll', schedule, true)
    window.removeEventListener('focus', pullOnFocus)
    document.removeEventListener('visibilitychange', pullOnFocus)
    if (scheduled) clearTimeout(scheduled)
    if (expiry) clearTimeout(expiry)
    for (const root of markdownRoots.values()) root.unmount()
    markdownRoots.clear()
    for (const node of document.querySelectorAll('.nm-remote')) node.remove()
    for (const row of document.querySelectorAll<HTMLElement>(`[${DONE}]`)) {
      row.removeAttribute(DONE)
      row.style.display = ''
    }
  }
}
