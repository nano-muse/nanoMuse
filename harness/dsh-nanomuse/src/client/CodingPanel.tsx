/**
 * Settings → Coding agents: the Cursor, Codex and Claude Code chats on this computer and
 * on the account's other computers (`docs/coding-agents.md`). This computer's agents at
 * the top — name, version, how many are running — the other computers as chips after
 * them (each read over the hub by the host); pick an agent → its chats (title, workspace,
 * when, status) → a chat: the transcript, a composer, the run as it streams (the text as
 * it comes, the tools as they are called) and Stop. A chat the CLI cannot reopen (made in
 * the IDE) says so above the composer: the message goes out as a fresh chat in the same
 * workspace. No agent on this computer → an honest empty state.
 *
 * The host serves `nanomuse/cloud/coding/*` (see `src/coding.ts`) and streams every run
 * step on `nanomuse/cloud/coding/events`, the runtime's bus message, mirrored here into a
 * small store the way `live.ts` does for the rest.
 */
import { Button, Input } from '@deepseek-ai/dsh-client-ui-primitives'
import { createElement as h, Fragment, useCallback, useEffect, useRef, useState, useSyncExternalStore, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { call, errorStyle, failureText, type Translate } from './api.ts'
import { IconArrowUp, IconChevronLeft, IconChevronRight, IconCpu, IconFolder, IconLaptop, IconPlus, IconRefresh, IconSquare } from './icons.tsx'
import { composing } from './keys.ts'
import { useLive, type LiveDevice } from './live.ts'
import { ago, Markdown, Sheet } from './ui.tsx'

export const CODING_SECTION = 'nanomuse-coding'

/** A device the Devices page picked before opening this section (the *Coding agents* chip). */
export const codingNav: { device?: string | undefined } = {}

// ---- the shapes the host answers with (the runtime's `to_dict()`s) --------------------------

export interface CodingAgent {
  id: string
  name: string
  installed: boolean
  cli: string | null
  version: string
  sessions_root: string
  running: number
}

export interface CodingSession {
  agent: string
  id: string
  title: string
  workspace: string
  path: string
  created_at: number
  updated_at: number
  messages: number
  status: string
  last_user: string
  last_assistant: string
  source: string
  resumable: boolean
  transcript?: { role: string; text: string }[]
  runs?: CodingRun[]
  run?: string
}

export interface CodingRun {
  id: string
  agent: string
  session_id: string
  asked_session_id?: string
  workspace: string
  text: string
  started_at: number
  ended_at: number | null
  status: string
  output: string
  resumed: boolean
  error: string
  tools: number
  device?: string
}

export interface CodingEvent {
  kind: string
  text?: string
  partial?: boolean
  phase?: string
  run?: string
  session_id?: string
}

export interface CodingLive {
  run: CodingRun
  events: CodingEvent[]
  /** The text the agent is writing right now. */
  current: string
}

// ---- the host's routes ----------------------------------------------------------------

const q = (params: Record<string, string | number | undefined>) => {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') s.set(k, String(v))
  const text = s.toString()
  return text ? `?${text}` : ''
}

const api = {
  agents: (device: string) => call<{ agents: CodingAgent[]; runs: CodingRun[] }>(`coding${q({ device })}`),
  sessions: (device: string, agent: string, limit: number) => call<{ sessions: CodingSession[] }>(`coding/sessions${q({ device, agent, limit })}`),
  session: (device: string, agent: string, id: string) => call<CodingSession>(`coding/sessions/${agent}/${encodeURIComponent(id)}${q({ device })}`),
  send: (body: { agent: string; text: string; session_id?: string; workspace?: string; device?: string }) => call<CodingRun>('coding/send', body),
  stop: (runId: string, device: string) => call<{ stopped: boolean }>('coding/stop', { run_id: runId, device }),
}

// ---- the live runs ---------------------------------------------------------------------

const EVENTS_URL = 'nanomuse/cloud/coding/events'
let liveRuns: Record<string, CodingLive> = {}
let source: EventSource | undefined
const listeners = new Set<() => void>()

function take(raw: string): void {
  let msg: { kind?: string; event?: CodingEvent; agent?: string; session_id?: string; device?: string; run?: CodingRun | null }
  try {
    msg = JSON.parse(raw) as typeof msg
  } catch {
    return
  }
  if (msg.kind !== 'coding' || !msg.event) return
  const id = msg.run?.id ?? msg.event.run
  if (!id) return
  const prev = liveRuns[id]
  const run = msg.run ?? prev?.run
  if (!run) return
  const ev = msg.event
  const events = ev.kind === 'run' ? (prev?.events ?? []) : [...(prev?.events ?? []), ev].slice(-400)
  let current = prev?.current ?? ''
  if (ev.kind === 'text') current = ev.partial ? current + (ev.text ?? '') : (ev.text ?? '')
  if (ev.kind === 'done' || ev.kind === 'error' || ev.kind === 'run') current = ''
  const next = { ...liveRuns, [id]: { run: { ...run, ...(msg.device ? { device: msg.device } : {}) }, events, current } }
  const ids = Object.keys(next)
  if (ids.length > 20) for (const old of ids.sort((a, b) => (next[a]?.run.started_at ?? 0) - (next[b]?.run.started_at ?? 0)).slice(0, ids.length - 20)) delete next[old]
  liveRuns = next
  for (const listener of listeners) listener()
}

function openStream(): void {
  if (source || typeof EventSource === 'undefined') return
  const es = new EventSource(EVENTS_URL)
  source = es
  es.onmessage = (event: MessageEvent<string>) => take(event.data)
  es.onerror = () => {
    if (es.readyState === 2) {
      source = undefined
      // only while someone still listens: the last unsubscribe may land inside these 3 s
      setTimeout(() => {
        if (listeners.size > 0) openStream()
      }, 3000)
    }
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  openStream()
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0 && source) {
      source.close()
      source = undefined
    }
  }
}

/** Every run this page has seen since it opened, live. */
export function useCodingLive(): Record<string, CodingLive> {
  return useSyncExternalStore(subscribe, () => liveRuns, () => liveRuns)
}

// ---- small pieces ----------------------------------------------------------------------

const GLYPH: Record<string, string> = { cursor: 'C', codex: 'X', claude: 'A' }

function Glyph({ agent, size = 32 }: { agent: string; size?: number }): ReactNode {
  return h('span', { className: `nm-cd-glyph nm-cd-glyph-${agent}`, style: { width: size, height: size, fontSize: Math.round(size * 0.44) }, 'aria-hidden': true }, GLYPH[agent] ?? '·')
}

function base(path: string): string {
  const parts = path.replace(/[\\/]+$/, '').split(/[\\/]/)
  return parts[parts.length - 1] || path
}

function StatusPill({ t, status }: { t: Translate; status: string }): ReactNode {
  if (status !== 'running' && status !== 'active') return null
  return h('span', { className: `nm-cd-pill nm-cd-pill-${status}` }, status === 'running' ? t('cdStatusRunning') : t('cdStatusActive'))
}

function agentName(agents: CodingAgent[] | undefined, id: string): string {
  return agents?.find((a) => a.id === id)?.name ?? ({ cursor: 'Cursor', codex: 'Codex', claude: 'Claude Code' } as Record<string, string>)[id] ?? id
}

/** Live runs on one computer: the shadows carry the other computer's name; local ones none. */
function runsOn(live: Record<string, CodingLive>, deviceName: string): CodingLive[] {
  return Object.values(live).filter((l) => (l.run.device ?? '') === deviceName)
}

// ---- the page --------------------------------------------------------------------------

export function makeCodingPanel(t: Translate) {
  return function CodingPanel(): ReactNode {
    const live = useLive()
    const hub = live.hub
    const liveRuns = useCodingLive()
    const [device, setDevice] = useState(() => {
      const picked = codingNav.device ?? ''
      codingNav.device = undefined
      return picked
    })
    const [agents, setAgents] = useState<CodingAgent[] | undefined>()
    const [runs, setRuns] = useState<CodingRun[]>([])
    const [sessions, setSessions] = useState<CodingSession[] | undefined>()
    const [filter, setFilter] = useState('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | undefined>()
    const [open, setOpen] = useState<{ agent: string; id: string } | undefined>()
    const [fresh, setFresh] = useState<string | undefined>()
    const [toast, setToast] = useState<string | undefined>()

    const computers: LiveDevice[] = hub.devices.filter((d) => d.id !== hub.deviceId && d.kind !== 'web' && d.online && d.actions.includes('coding.sessions'))
    const picked = computers.find((d) => d.id === device)
    const deviceName = picked?.name ?? ''
    useEffect(() => {
      // the computer went offline or off the list: back to this one
      if (device && !picked && hub.connected) setDevice('')
    }, [device, picked, hub.connected])

    const load = useCallback(async () => {
      setLoading(true)
      setError(undefined)
      try {
        const [a, s] = await Promise.all([api.agents(device), api.sessions(device, '', 40)])
        setAgents(a.agents)
        setRuns(a.runs ?? [])
        setSessions(s.sessions)
      } catch (err: unknown) {
        setError(failureText(t, err))
        setAgents([])
        setSessions([])
      } finally {
        setLoading(false)
      }
    }, [device])
    useEffect(() => {
      void load()
    }, [load])

    // a finished run means a transcript on disk changed: refresh quietly
    const here = runsOn(liveRuns, deviceName)
    const finished = here.filter((l) => l.run.status !== 'running').length
    useEffect(() => {
      if (finished) void load()
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [finished])
    useEffect(() => {
      if (!toast) return
      const timer = setTimeout(() => setToast(undefined), 4000)
      return () => clearTimeout(timer)
    }, [toast])

    const installed = (agents ?? []).filter((a) => a.installed)
    const withCli = installed.filter((a) => a.cli)
    const running = here.filter((l) => l.run.status === 'running')
    const runningIds = new Set(running.map((l) => l.run.session_id || l.run.asked_session_id || ''))
    // empty chats (a window opened and closed) are noise unless something runs in them
    const shown = (sessions ?? []).filter((s) => (!filter || s.agent === filter) && (s.messages > 0 || s.status === 'running' || runningIds.has(s.id)))
    const past = runs.filter((r) => r.status !== 'running').slice(0, 8)

    if (open) {
      return h(SessionView, {
        t,
        device,
        deviceLabel: deviceName,
        agent: open.agent,
        id: open.id,
        agentLabel: agentName(agents, open.agent),
        onBack: () => {
          setOpen(undefined)
          void load()
        },
      })
    }

    const where = h('div', { className: 'nm-chips nm-cd-where' },
      h('button', { type: 'button', className: `nm-chip${device ? '' : ' nm-chip-on'}`, onClick: () => setDevice('') }, h(IconCpu, { size: 13 }), ' ', hub.deviceName ? `${t('thisComputer')} · ${hub.deviceName}` : t('thisComputer')),
      computers.length > 0 ? h('span', { className: 'nm-cd-where-label' }, t('cdOtherComputers')) : null,
      ...computers.map((d) => h('button', { key: d.id, type: 'button', className: `nm-chip${device === d.id ? ' nm-chip-on' : ''}`, onClick: () => setDevice(d.id) }, h(IconLaptop, { size: 13 }), ' ', d.name)))

    return h('div', { className: 'nm-page nm-cd' },
      h('div', { className: 'nm-page-inner' },
        h('h1', null, t('capCoding')),
        h('p', { className: 'nm-lead' }, t('cdLead')),
        where,
        h('h2', null, device ? deviceName : t('thisComputer')),
        agents === undefined
          ? h('p', { className: 'nm-fine' }, '…')
          : installed.length === 0 && !device
            ? h(EmptyAgents, { t, computers: computers.length, connected: hub.connected, signedIn: live.cloud.signedIn })
            : h('div', { className: 'nm-cd-agents' },
                agents.map((a) => h('button', {
                  key: a.id,
                  type: 'button',
                  className: `nm-cd-agent${filter === a.id ? ' nm-active' : ''}${a.installed ? '' : ' nm-cd-agent-off'}`,
                  disabled: !a.installed,
                  'aria-pressed': filter === a.id,
                  onClick: () => setFilter((f) => (f === a.id ? '' : a.id)),
                },
                  h('div', { className: 'nm-cd-agent-top' },
                    h(Glyph, { agent: a.id, size: 30 }),
                    a.running > 0 ? h('span', { className: 'nm-cd-running' }, h('span', { className: 'nm-status-dot nm-live' }), ' ', t('cdRunning', { n: a.running })) : null),
                  h('span', { className: 'nm-cd-agent-name' }, a.name),
                  h('span', { className: 'nm-cd-agent-sub' }, a.installed ? (a.cli ? a.version || t('cdInstalled') : t('cdChatsOnly')) : t('cdNotFound'))))),
        error ? h('div', { style: errorStyle }, error) : null,

        running.length > 0
          ? h(Fragment, null,
              h('h2', null, t('cdWorkingNow')),
              h('div', { className: 'nm-card' },
                running.map((l) => h(LiveRunRow, { key: l.run.id, t, live: l, agentLabel: agentName(agents, l.run.agent), onOpen: () => setOpen({ agent: l.run.agent, id: l.run.session_id || l.run.asked_session_id || '' }) }))))
          : null,

        h('div', { className: 'nm-cd-section-head' },
          h('h2', null, filter ? t('cdAgentChats', { agent: agentName(agents, filter) }) : t('cdRecent')),
          withCli.length > 0
            ? h('button', { type: 'button', className: 'nm-cd-link', onClick: () => setFresh((filter && withCli.some((a) => a.id === filter) ? filter : withCli[0]?.id) ?? undefined) }, h(IconPlus, { size: 14 }), ' ', t('cdNewChat'))
            : null),
        sessions === undefined
          ? h('p', { className: 'nm-fine' }, '…')
          : shown.length === 0
            ? h('p', { className: 'nm-fine' }, t('cdNoChats'))
            : h('div', { className: 'nm-card' },
                shown.map((s) => h('button', { key: `${s.agent}-${s.id}`, type: 'button', className: 'nm-row nm-row-button', onClick: () => setOpen({ agent: s.agent, id: s.id }) },
                  h(Glyph, { agent: s.agent, size: 32 }),
                  h('div', { className: 'nm-row-main' },
                    h('span', { className: 'nm-cd-row-title' }, h('span', { className: 'nm-row-title' }, s.title || t('cdUntitled')), h(StatusPill, { t, status: runningIds.has(s.id) ? 'running' : s.status })),
                    h('span', { className: 'nm-row-sub' }, [s.workspace ? base(s.workspace) : '', ago(t, s.updated_at * 1000), t('cdMessages', { n: s.messages })].filter(Boolean).join(' · '))),
                  h('span', { className: 'nm-row-chevron' }, h(IconChevronRight, { size: 16 }))))),

        past.length > 0
          ? h(Fragment, null,
              h('h2', null, t('cdSent')),
              h('div', { className: 'nm-card' },
                past.map((r) => h('div', { key: r.id, className: 'nm-row' },
                  h(Glyph, { agent: r.agent, size: 28 }),
                  h('div', { className: 'nm-row-main' },
                    h('span', { className: 'nm-row-title' }, r.text),
                    h('span', { className: 'nm-row-sub' }, [r.status === 'done' ? t('cdDone') : r.status === 'failed' ? t('cdFailed') : t('cdStopped'), ago(t, r.started_at * 1000), r.tools ? t('cdSteps', { n: r.tools }) : '', r.error].filter(Boolean).join(' · '))),
                  r.session_id ? h(Button, { variant: 'ghost', size: 'sm', onClick: () => setOpen({ agent: r.agent, id: r.session_id }) }, t('cdOpen')) : null))))
          : null,

        !hub.connected && live.cloud.signedIn ? h('p', { className: 'nm-fine' }, t('cdOffHub')) : null,
        toast ? h('p', { className: 'nm-fine' }, toast) : null,
        h('div', null,
          h(Button, { variant: 'outline', size: 'sm', disabled: loading, onClick: () => void load() }, h(IconRefresh, { size: 14 }), ' ', t('refresh')))),
      fresh
        ? h(NewChatSheet, {
            t,
            agent: fresh,
            agents: withCli,
            device,
            deviceLabel: deviceName,
            onClose: () => setFresh(undefined),
            onStarted: (run) => {
              setFresh(undefined)
              setToast(t('cdSentToast', { agent: agentName(agents, run.agent) }))
              setOpen({ agent: run.agent, id: run.session_id || run.asked_session_id || '' })
            },
          })
        : null)
  }
}

/** No agent on this computer: say so, and where else to look. */
function EmptyAgents({ t, computers, connected, signedIn }: { t: Translate; computers: number; connected: boolean; signedIn: boolean }): ReactNode {
  return h('div', { className: 'nm-dv-card' },
    h('div', { className: 'nm-dv-top' },
      h('span', { className: 'nm-dv-glyph', 'aria-hidden': true }, h(IconCpu, { size: 22 })),
      h('div', { className: 'nm-dv-main' },
        h('span', { className: 'nm-dv-name' }, t('cdNoneInstalled')),
        h('span', { className: 'nm-dv-sub nm-wrap' }, computers > 0 ? t('cdNoneInstalledSub') : signedIn && connected ? t('cdNoOtherComputers') : t('cdNoneInstalledSub')))))
}

function LiveRunRow({ t, live, agentLabel, onOpen }: { t: Translate; live: CodingLive; agentLabel: string; onOpen(): void }): ReactNode {
  const lastTool = [...live.events].reverse().find((e) => e.kind === 'tool')
  return h('button', { type: 'button', className: 'nm-row nm-row-button', onClick: onOpen },
    h(Glyph, { agent: live.run.agent, size: 32 }),
    h('div', { className: 'nm-row-main' },
      h('span', { className: 'nm-row-title' }, live.run.text),
      h('span', { className: 'nm-row-sub' }, h('span', { className: 'nm-status-dot nm-live', style: { display: 'inline-block', verticalAlign: 'middle', marginRight: 6 } }), live.current.slice(-80) || lastTool?.text || t('cdWorking', { agent: agentLabel }))),
    h('span', { className: 'nm-row-chevron' }, h(IconChevronRight, { size: 16 })))
}

// ---- one chat --------------------------------------------------------------------------

function SessionView({ t, device, deviceLabel, agent, id, agentLabel, onBack }: { t: Translate; device: string; deviceLabel: string; agent: string; id: string; agentLabel: string; onBack(): void }): ReactNode {
  const liveRuns = useCodingLive()
  const [session, setSession] = useState<CodingSession | undefined>()
  const [error, setError] = useState<string | undefined>()
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const listRef = useRef<HTMLDivElement | null>(null)

  const load = useCallback(async () => {
    if (!id) return
    try {
      setSession(await api.session(device, agent, id))
      setError(undefined)
    } catch (err: unknown) {
      setError(failureText(t, err))
    }
  }, [device, agent, id])
  useEffect(() => {
    void load()
  }, [load])

  // runs on this chat, live (a new chat: the run whose session the agent has not named yet)
  const live = runsOn(liveRuns, deviceLabel).filter((l) => l.run.agent === agent && (l.run.session_id === id || l.run.asked_session_id === id || (!id && !l.run.session_id)))
  const running = live.find((l) => l.run.status === 'running')
  const lastFinished = live.filter((l) => l.run.status !== 'running').length
  useEffect(() => {
    if (lastFinished) void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastFinished])
  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [session?.transcript?.length, running?.events.length, running?.current.length])

  const send = async () => {
    const msg = text.trim()
    if (!msg || sending) return
    setSending(true)
    try {
      await api.send({ agent, text: msg, session_id: id, workspace: session?.workspace ?? '', device })
      setText('')
      setError(undefined)
    } catch (err: unknown) {
      setError(failureText(t, err))
    } finally {
      setSending(false)
    }
  }

  const transcript = session?.transcript ?? []
  // any chat takes a message: the CLI reopens its own, and an IDE chat (not resumable) gets a
  // new one in the same workspace with the last exchange quoted
  const canSend = Boolean(session) || Boolean(running) || !id
  const continuesAsNew = Boolean(session) && !session?.resumable && !running
  const sub = [deviceLabel, session?.workspace ? base(session.workspace) : agentLabel, session?.source && session.source !== 'ide' && session.source !== 'cli' ? session.source : ''].filter(Boolean).join(' · ')

  return h('div', { className: 'nm-page nm-cd nm-cd-chat' },
    h('div', { className: 'nm-page-inner nm-cd-chat-inner' },
      h('div', { className: 'nm-cd-chat-head' },
        h('button', { type: 'button', className: 'nm-icon-btn', 'aria-label': t('cdBack'), title: t('cdBack'), onClick: onBack }, h(IconChevronLeft, { size: 18 })),
        h(Glyph, { agent, size: 30 }),
        h('div', { className: 'nm-row-main' },
          h('span', { className: 'nm-row-title' }, session?.title || agentLabel),
          h('span', { className: 'nm-row-sub' }, sub))),
      h('div', { className: 'nm-cd-thread', ref: listRef },
        error ? h('div', { style: errorStyle }, error) : null,
        !session && !error && id ? h('p', { className: 'nm-fine' }, '…') : null,
        transcript.map((m, i) => h(Bubble, { key: i, who: m.role === 'user' ? 'you' : 'agent' }, m.role === 'user' ? h('span', { className: 'nm-cd-pre' }, m.text) : h(Markdown, { text: m.text }))),
        live
          // once the agent's own store has the exchange, the transcript shows it
          .filter((l) => !(l.run.status === 'done' && (l.run.resumed || !l.run.asked_session_id) && transcript.some((m) => m.role === 'user' && m.text.trim() === l.run.text.trim())))
          .map((l) => h(LiveRun, { key: l.run.id, t, live: l, agentLabel, hideFinishedText: transcript.length > 0 && l.run.status === 'done' })),
        session && transcript.length === 0 && live.length === 0 ? h('p', { className: 'nm-fine', style: { textAlign: 'center' } }, t('cdNothingReadable')) : null),
      h('div', { className: 'nm-cd-composer' },
        continuesAsNew ? h('p', { className: 'nm-fine' }, t('cdNotResumable')) : null,
        h('form', { className: 'nm-cd-form', onSubmit: (e: FormEvent) => { e.preventDefault(); void send() } },
          h('textarea', {
            className: 'nm-cd-input',
            value: text,
            rows: 1,
            disabled: !canSend || Boolean(running),
            placeholder: running ? t('cdWorking', { agent: agentLabel }) : !session && id ? '…' : continuesAsNew ? t('cdContinueNew') : t('cdTell', { agent: agentLabel }),
            'aria-label': t('cdTell', { agent: agentLabel }),
            onChange: (e: FormEvent<HTMLTextAreaElement>) => setText(e.currentTarget.value),
            onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => {
              if (e.key === 'Enter' && !e.shiftKey && !composing(e)) {
                e.preventDefault()
                void send()
              }
            },
          }),
          running
            ? h('button', { type: 'button', className: 'nm-cd-send nm-cd-stop', 'aria-label': t('cdStop'), title: t('cdStop'), onClick: () => void api.stop(running.run.id, device).catch((err: unknown) => setError(failureText(t, err))) }, h(IconSquare, { size: 16 }))
            : h('button', { type: 'submit', className: 'nm-cd-send', disabled: !text.trim() || sending || !canSend, 'aria-label': t('cdSend'), title: t('cdSend') }, h(IconArrowUp, { size: 18 }))))))
}

function Bubble({ who, badge, children }: { who: 'you' | 'agent'; badge?: string; children?: ReactNode }): ReactNode {
  return h('div', { className: `nm-cd-msg nm-cd-from-${who}` },
    badge ? h('span', { className: 'nm-cd-badge' }, badge) : null,
    h('div', { className: 'nm-cd-bubble' }, children))
}

/** A run in a chat: what you sent, the steps, the text as it streams. */
function LiveRun({ t, live, agentLabel, hideFinishedText }: { t: Translate; live: CodingLive; agentLabel: string; hideFinishedText: boolean }): ReactNode {
  const { run, events, current } = live
  const tools = events.filter((e) => e.kind === 'tool')
  const isRunning = run.status === 'running'
  const body = isRunning ? (run.output ? `${run.output}\n\n` : '') + current : run.output
  return h(Fragment, null,
    h(Bubble, { who: 'you', badge: t('cdViaNanomuse') }, h('span', { className: 'nm-cd-pre' }, run.text)),
    tools.length > 0 || isRunning
      ? h('div', { className: 'nm-cd-steps' },
          h('div', { className: 'nm-cd-steps-head' },
            isRunning ? h('span', { className: 'nm-status-dot nm-live' }) : null,
            isRunning ? (tools.length === 0 && !current && !run.output ? t('cdStarting') : t('cdWorking', { agent: agentLabel })) : t('cdSteps', { n: tools.length }),
            run.device ? h('span', { className: 'nm-cd-steps-device' }, h(IconLaptop, { size: 11 }), ' ', run.device) : null),
          tools.length > 0 ? h('ul', { className: 'nm-cd-steps-list' }, tools.slice(-12).map((e, i) => h('li', { key: i }, e.text))) : null)
      : null,
    current || (run.output && !hideFinishedText)
      ? h(Bubble, { who: 'agent' }, h(Markdown, { text: body }), isRunning ? h('span', { className: 'nm-cd-caret' }) : null)
      : null,
    run.status === 'failed' ? h('div', { style: errorStyle }, run.error || t('cdFailed')) : null,
    run.status === 'stopped' ? h('p', { className: 'nm-fine', style: { textAlign: 'center' } }, t('cdStopped')) : null,
    !run.resumed && run.asked_session_id && run.status !== 'running' ? h('p', { className: 'nm-fine', style: { textAlign: 'center' } }, t('cdContinuedAsNew')) : null)
}

// ---- a new chat ------------------------------------------------------------------------

function NewChatSheet({ t, agent: initial, agents, device, deviceLabel, onClose, onStarted }: { t: Translate; agent: string; agents: CodingAgent[]; device: string; deviceLabel: string; onClose(): void; onStarted(run: CodingRun): void }): ReactNode {
  const [agent, setAgent] = useState(initial)
  const [workspace, setWorkspace] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const [recent, setRecent] = useState<string[]>([])
  useEffect(() => {
    api.sessions(device, agent, 30)
      .then((r) => setRecent([...new Set(r.sessions.map((s) => s.workspace).filter(Boolean))].slice(0, 6)))
      .catch(() => setRecent([]))
  }, [agent, device])
  const label = agents.find((a) => a.id === agent)?.name ?? agent

  const start = async () => {
    if (!text.trim() || busy) return
    setBusy(true)
    setError(undefined)
    try {
      onStarted(await api.send({ agent, text: text.trim(), workspace: workspace.trim(), device }))
    } catch (err: unknown) {
      setError(failureText(t, err))
    } finally {
      setBusy(false)
    }
  }

  return h(Sheet, {
    title: t('cdNewChatWith', { agent: label }),
    onClose,
    closeLabel: t('cancel'),
    footer: h('div', { className: 'nm-sheet-actions' },
      h(Button, { variant: 'ghost', size: 'sm', onClick: onClose }, t('cancel')),
      h('span', { style: { flex: 1 } }),
      h(Button, { variant: 'primary', size: 'sm', disabled: !text.trim() || busy, onClick: () => void start() }, t('cdSendTo', { agent: label }))),
  },
    h('div', { className: 'nm-sheet-form' },
      agents.length > 1
        ? h('div', { className: 'nm-seg', role: 'group' }, agents.map((a) => h('button', { key: a.id, type: 'button', className: `nm-seg-btn nm-seg-text${agent === a.id ? ' nm-active' : ''}`, 'aria-pressed': agent === a.id, onClick: () => setAgent(a.id) }, h(Glyph, { agent: a.id, size: 18 }), ' ', a.name)))
        : null,
      h('label', { className: 'nm-cd-label' }, t('cdFolder'),
        h(Input, { value: workspace, placeholder: '~/project', onChange: (e: FormEvent<HTMLInputElement>) => setWorkspace(e.currentTarget.value) })),
      recent.length > 0
        ? h('div', { className: 'nm-chips' }, recent.map((w) => h('button', { key: w, type: 'button', className: `nm-chip${workspace === w ? ' nm-chip-on' : ''}`, title: w, onClick: () => setWorkspace(w) }, h(IconFolder, { size: 12 }), ' ', base(w))))
        : null,
      h('label', { className: 'nm-cd-label' }, t('cdWhatToDo'),
        h('textarea', { className: 'nm-cd-input nm-cd-input-tall', value: text, rows: 4, autoFocus: true, placeholder: t('cdWhatToDoHint'), onChange: (e: FormEvent<HTMLTextAreaElement>) => setText(e.currentTarget.value) })),
      deviceLabel ? h('p', { className: 'nm-sheet-fine' }, t('cdRunsThere')) : null,
      error ? h('div', { style: errorStyle }, error) : null))
}
