/**
 * Settings → Connectors, the way Muse lays it out: a search field, the connected
 * ones, the available ones by kind with a "Connect" at the end of each row, and
 * a detail view per connector (what it can do, what gates it). Two inventories
 * meet here. The built-in ones are what this agent reaches on its own — the
 * harness's tools, the runtime's hands and the connectors its config.toml turns
 * on (mailbox, calendar, address book), the account's other devices, the rooms,
 * any MCP server in the preset. The services are third parties with a remote
 * MCP server (src/connectors-catalogue.ts): "Connect" signs in to the service
 * in the browser (the MCP authorization flow) or asks for a key, and from then
 * on every chat has the service's tools, each one with a switch of its own.
 * Anything else with a URL — a hit in the MCP registry, a server of your own —
 * goes through the same door.
 */
import { createElement as h, Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { CATALOGUE, CATEGORY_ORDER, catalogueEntry, type CatalogueEntry, type Category } from '../connectors-catalogue.ts'
import type { ConnectionView, ConnectorsView, FlowView, RegistryHit } from '../connectors.ts'
import type { Translate } from './api.ts'
import { MARKS } from './brand-marks.ts'
import { openLink } from './bridge.ts'
import { settingsBus } from './bus.ts'
import {
  IconCalendar, IconCheck, IconChevronLeft, IconChevronRight, IconCode, IconCopy, IconDevices, IconExternal, IconFeed, IconFolder, IconGlobe, IconHand, IconLink, IconMail, IconPuzzle, IconRefresh, IconSearch, IconShield, IconUsers,
} from './icons.tsx'
import { useLive } from './live.ts'
import { DEVICES_PANEL } from './panels.ts'
import { roomsCall, useRooms } from './rooms.ts'
import { Sheet } from './ui.tsx'

export const CONNECTORS_SECTION = 'nanomuse-connectors'
const COMPUTER_SECTION = 'nanomuse-computer'
const PERMISSIONS_SECTION = 'nanomuse-permissions'
const FILES_SECTION = 'nanomuse-files'
const HARNESS_MCP_DOCS = 'https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/mcp.md'
const RUNTIME_DOCS = 'https://github.com/nano-muse/nanoMuse/blob/main/docs/configuration.md#connectors'
const REGISTRY_SITE = 'https://registry.modelcontextprotocol.io/'
const API = '/nanomuse/connectors'

// ---- the host ------------------------------------------------------------------------

/** GET when there is no body, POST with one; 204 resolves to undefined. */
async function connectorsCall<T = undefined>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}/${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'content-type': 'application/json', 'x-nanomuse': '1' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  if (res.status === 204) return undefined as T
  const json = (await res.json().catch(() => ({}))) as { error?: { message?: string } }
  if (!res.ok) throw new Error(json.error?.message ?? `${res.status}`)
  return json as T
}

type ConnectResult = { kind: 'authorize'; url: string; flow: string } | { kind: 'key'; service: string; where: string } | { kind: 'connected'; id: string }

const NO_CONNECTIONS: ConnectorsView = { connections: [], flows: [], proxy: 0 }

/** The connected services, polled; `refresh` after anything that changes them. */
export function useConnections(): { view: ConnectorsView; refresh(): Promise<void> } {
  const [view, setView] = useState<ConnectorsView>(NO_CONNECTIONS)
  const refresh = useCallback(() => connectorsCall<ConnectorsView>('state').then(setView).catch(() => undefined), [])
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 8_000)
    return () => window.clearInterval(timer)
  }, [refresh])
  return { view, refresh }
}

// ---- the inventory the chats report ---------------------------------------------------

interface Catalogue {
  servers: { name: string; tools: { name: string; description: string }[] }[]
  builtin: number
  /** When the catalogue was last read through a chat; 0 before any chat ran. */
  at: number
}

export function useConnectors(): Catalogue | undefined {
  const [value, setValue] = useState<Catalogue | undefined>()
  useEffect(() => {
    let alive = true
    const load = () => roomsCall<Catalogue>('connectors').then((v) => { if (alive) setValue(v) }).catch(() => undefined)
    void load()
    const timer = window.setInterval(() => void load(), 15_000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [])
  return value
}

// ---- the rows -----------------------------------------------------------------------

type Group = Category | 'builtin' | 'preset'

/** One connector as the page knows it. */
interface Entry {
  id: string
  mark: ReactNode
  title: string
  sub: string
  about: string
  on: boolean
  group: Group
  /** The tools behind it, when known. */
  tools: { name: string; description: string }[]
  /** Where "Connect" leads when it is off: a settings page, the vault steps, or the service's own sign-in. */
  connect?: { section: string } | { steps: Step[] } | { service: CatalogueEntry }
  /** Where the detail's "settings" row leads, when there is a page of its own. */
  page?: string
  /** A third-party service, connected: the row the host keeps. */
  connection?: ConnectionView
  /** The catalogue entry, for a service connected or not. */
  service?: CatalogueEntry
}

interface Step { text: string; command?: string }

/** What the page is in the middle of: a sign-in in the browser, a key to paste, a URL to add, the vault steps. */
type Pending =
  | { kind: 'authorize'; entry: Entry; url: string; flow: string; status: FlowView['status']; error: string }
  | { kind: 'key'; entry: Entry; where: string; error: string; busy: boolean }
  | { kind: 'custom'; url: string; label: string; error: string; busy: boolean }
  | { kind: 'steps'; entry: Entry }

/** The service's brand mark on a white tile, or its initial on a tile of its colour. */
function Mark({ icon, color, name, size = 18 }: { icon?: string | undefined; color: string; name: string; size?: number }): ReactNode {
  const mark = icon ? MARKS[icon] : undefined
  const box = { width: size + 16, height: size + 16 }
  if (mark) {
    return h('span', { className: 'nm-cn-mark', style: box, 'aria-hidden': true },
      h('svg', { viewBox: '0 0 24 24', width: size, height: size }, h('path', { d: mark.d, fill: mark.hex })))
  }
  return h('span', { className: 'nm-cn-mark nm-cn-mark-letter', style: { ...box, background: color, fontSize: Math.round(size * 0.78) }, 'aria-hidden': true }, (name.trim()[0] ?? '?').toUpperCase())
}

function builtinMark(Icon: (p: { size?: number }) => ReactNode, size = 18): ReactNode {
  return h('span', { className: 'nm-row-icon nm-cn-builtin-mark', style: { width: size + 16, height: size + 16 } }, h(Icon, { size }))
}

function groupLabel(t: Translate, group: Group): string {
  switch (group) {
    case 'builtin': return t('cnBuiltIn')
    case 'preset': return t('cnMcp')
    case 'work': return t('cnCatWork')
    case 'talk': return t('cnCatTalk')
    case 'files': return t('cnCatFiles')
    case 'dev': return t('cnCatDev')
    case 'data': return t('cnCatData')
    case 'design': return t('cnCatDesign')
    case 'money': return t('cnCatMoney')
    case 'search': return t('cnCatSearch')
    case 'infra': return t('cnCatInfra')
    case 'misc': return t('cnCatMisc')
  }
}

const GROUP_ORDER: Group[] = ['builtin', 'preset', ...CATEGORY_ORDER, 'infra']

export function makeConnectorsSection(t: Translate) {
  const lang = t('langTag') === 'zh' ? 'zh' : 'en'
  const about = (service: CatalogueEntry) => service.about[lang]

  return function ConnectorsSection(): ReactNode {
    const catalogue = useConnectors()
    const live = useLive()
    const rooms = useRooms()
    const { view, refresh } = useConnections()
    const [query, setQuery] = useState('')
    const [group, setGroup] = useState<Group | 'all'>('all')
    const [open, setOpen] = useState<string | null>(null)
    const [pending, setPending] = useState<Pending | null>(null)
    const [hits, setHits] = useState<{ q: string; items: RegistryHit[]; busy: boolean; error: string } | null>(null)
    const seen = (catalogue?.at ?? 0) > 0
    const runtime = catalogue?.servers.find((s) => s.name === 'nanomuse')
    const runtimeTools = new Map((runtime?.tools ?? []).map((tool) => [tool.name, tool]))
    const has = (...names: string[]) => names.some((n) => runtimeTools.has(n))
    const pick = (...names: string[]) => names.flatMap((n) => { const tool = runtimeTools.get(n); return tool ? [tool] : [] })
    const devices = live.hub.devices.filter((d) => d.kind !== 'web').length
    const connectedNames = new Set(view.connections.map((c) => c.serverName))
    const others = (catalogue?.servers ?? []).filter((s) => s.name !== 'nanomuse' && !connectedNames.has(s.name))

    const builtin: Entry[] = [
      { id: 'hands', mark: builtinMark(IconHand), title: t('cnHands'), sub: has('computer_act') ? t('cnHandsOn') : seen ? t('cnHandsOff') : t('cnNotYet'), about: t('cnHandsAbout'), on: has('computer_act'), group: 'builtin', tools: pick('computer_screen', 'computer_act'), connect: { section: COMPUTER_SECTION }, page: COMPUTER_SECTION },
      { id: 'email', mark: builtinMark(IconMail), title: t('cnEmail'), sub: has('read_emails') ? t('cnEmailOn') : t('cnEmailOff'), about: t('cnEmailAbout'), on: has('read_emails', 'send_email'), group: 'builtin', tools: pick('read_emails', 'send_email'), connect: { steps: [
        { text: t('cnStepAddress'), command: 'nanomuse vault set EMAIL_ADDRESS' },
        { text: t('cnStepPassword'), command: 'nanomuse vault set EMAIL_PASSWORD' },
        { text: t('cnStepConfig', { file: '~/.nanomuse/config.toml' }), command: '[connectors.email]\nenabled = true\nimap_host = "imap.gmail.com"\nsmtp_host = "smtp.gmail.com"' },
        { text: t('cnStepRestart') },
      ] } },
      { id: 'calendar', mark: builtinMark(IconCalendar), title: t('cnCalendar'), sub: has('calendar') ? t('cnCalendarOn') : t('cnCalendarOff'), about: t('cnCalendarAbout'), on: has('calendar'), group: 'builtin', tools: pick('calendar'), connect: { steps: [
        { text: t('cnStepFeed'), command: 'nanomuse vault set CALENDAR_WORK' },
        { text: t('cnStepConfig', { file: '~/.nanomuse/config.toml' }), command: '[connectors.calendar]\nenabled = true\n[[connectors.calendar.feeds]]\nname = "Work"\nurl = "{{vault:CALENDAR_WORK}}"' },
        { text: t('cnStepRestart') },
      ] } },
      { id: 'contacts', mark: builtinMark(IconUsers), title: t('cnContacts'), sub: has('contacts') ? t('cnContactsOn') : t('cnContactsOff'), about: t('cnContactsAbout'), on: has('contacts'), group: 'builtin', tools: pick('contacts'), connect: { steps: [
        { text: t('cnStepVcf'), command: '[connectors.contacts]\nenabled = true\n[[connectors.contacts.sources]]\nname = "Google"\nurl = "~/Downloads/contacts.vcf"' },
        { text: t('cnStepRestart') },
      ] } },
      { id: 'reach', mark: builtinMark(IconDevices), title: t('cnReach'), sub: devices ? t('cnReachOn', { n: devices }) : t('cnReachOff'), about: t('cnReachAbout'), on: devices > 0, group: 'builtin', tools: [], connect: { section: DEVICES_PANEL }, page: DEVICES_PANEL },
      { id: 'web', mark: builtinMark(IconGlobe), title: t('cnWeb'), sub: t('cnWebSub'), about: t('cnWebAbout'), on: true, group: 'builtin', tools: [] },
      { id: 'files', mark: builtinMark(IconFolder), title: t('cnFiles'), sub: t('cnFilesSub'), about: t('cnFilesAbout'), on: true, group: 'builtin', tools: [], page: FILES_SECTION },
      { id: 'shell', mark: builtinMark(IconCode), title: t('cnShell'), sub: t('cnShellSub'), about: t('cnShellAbout'), on: true, group: 'builtin', tools: [] },
      { id: 'rooms', mark: builtinMark(IconFeed), title: t('cnRooms'), sub: t('cnRoomsSub', { goals: rooms.goals.length, items: rooms.library.length }), about: t('cnRoomsAbout'), on: true, group: 'builtin', tools: [] },
      { id: 'schedule', mark: builtinMark(IconCalendar), title: t('cnSchedule'), sub: t('cnScheduleSub'), about: t('cnScheduleAbout'), on: true, group: 'builtin', tools: [] },
      ...others.map((server): Entry => ({ id: `mcp:${server.name}`, mark: builtinMark(IconLink), title: server.name, sub: t('cnTools', { n: server.tools.length }), about: t('cnMcpAbout'), on: true, group: 'preset', tools: server.tools })),
    ]

    const connectionSub = (c: ConnectionView): string => {
      if (c.state === 'reauth') return t('cnReauthSub')
      if (c.state === 'error') return c.error || t('cnErrorSub')
      const off = c.disabled.filter((name) => c.tools.some((tool) => tool.name === name)).length
      return off ? t('cnToolsSome', { n: c.tools.length - off, total: c.tools.length }) : t('cnTools', { n: c.tools.length })
    }
    const connections: Entry[] = view.connections.map((c): Entry => {
      const service = catalogueEntry(c.service)
      const mark = service ? h(Mark, { icon: service.icon, color: service.color, name: service.name }) : h(Mark, { color: '#64748b', name: c.label })
      return { id: `conn:${c.id}`, mark, title: c.label, sub: connectionSub(c), about: service ? about(service) : t('cnCustomAbout', { host: hostOf(c.url) }), on: true, group: service?.category ?? 'misc', tools: c.tools, connection: c, ...(service ? { service } : {}) }
    })
    const connectedServices = new Set(view.connections.map((c) => c.service))
    const services: Entry[] = CATALOGUE.filter((s) => !connectedServices.has(s.id)).map((s): Entry => ({
      id: `svc:${s.id}`, mark: h(Mark, { icon: s.icon, color: s.color, name: s.name }), title: s.name, sub: about(s), about: about(s), on: false, group: s.category, tools: [], connect: { service: s }, service: s,
    }))
    const entries = [...builtin, ...connections, ...services]

    const q = query.trim().toLowerCase()
    const matches = (e: Entry) => (!q || `${e.title} ${e.sub} ${e.service?.id ?? ''} ${e.service?.url ?? ''}`.toLowerCase().includes(q)) && (group === 'all' || e.group === group)
    const shown = entries.filter(matches)
    const connected = shown.filter((e) => e.on)
    const available = shown.filter((e) => !e.on)
    const groups = GROUP_ORDER.filter((g) => available.some((e) => e.group === g))
    const current = open ? entries.find((e) => e.id === open) : undefined

    // ---- the connect flows

    const handle = async (entry: Entry, result: ConnectResult) => {
      if (result.kind === 'authorize') {
        openLink(result.url)
        setPending({ kind: 'authorize', entry, url: result.url, flow: result.flow, status: 'pending', error: '' })
      } else if (result.kind === 'key') {
        setPending({ kind: 'key', entry, where: result.where, error: '', busy: false })
      } else {
        await refresh()
        setPending(null)
        setOpen(`conn:${result.id}`)
      }
    }
    const fail = (entry: Entry | null, error: unknown) => {
      const text = error instanceof Error ? error.message : String(error)
      setPending((p) => {
        if (!p) return entry ? { kind: 'authorize', entry, url: '', flow: '', status: 'failed', error: text } : null
        if (p.kind === 'authorize') return { ...p, status: 'failed', error: text }
        if (p.kind === 'steps') return p
        return { ...p, error: text, busy: false }
      })
    }
    // `fresh`: start over with a new client registration at the service (its sign-in page said it no longer knows ours)
    const beginConnect = (entry: Entry, fresh = false) => {
      if (!entry.connect) return
      if ('section' in entry.connect) { settingsBus.openSection?.(entry.connect.section); return }
      if ('steps' in entry.connect) { setPending({ kind: 'steps', entry }); return }
      const service = entry.connect.service
      if (service.auth.kind === 'key') { setPending({ kind: 'key', entry, where: service.auth.where, error: '', busy: false }); return }
      setPending({ kind: 'authorize', entry, url: '', flow: '', status: 'pending', error: '' })
      connectorsCall<ConnectResult>('connect', { service: service.id, ...(fresh ? { fresh } : {}) }).then((r) => handle(entry, r)).catch((e: unknown) => fail(entry, e))
    }
    const reconnect = (entry: Entry, fresh = false) => {
      const c = entry.connection
      if (!c) return
      setPending({ kind: 'authorize', entry, url: '', flow: '', status: 'pending', error: '' })
      const body = { ...(entry.service ? { service: entry.service.id } : { url: c.url, label: c.label }), reconnect: c.id, ...(fresh ? { fresh } : {}) }
      connectorsCall<ConnectResult>('connect', body).then((r) => handle(entry, r)).catch((e: unknown) => fail(entry, e))
    }
    const again = (fresh: boolean) => {
      const e = pending?.kind === 'authorize' ? pending.entry : null
      if (e) (e.connection ? reconnect : beginConnect)(e, fresh)
    }
    const submitKey = (key: string) => {
      if (!pending || pending.kind !== 'key') return
      const entry = pending.entry
      setPending({ ...pending, busy: true, error: '' })
      const body = entry.service ? { service: entry.service.id, key, ...(entry.connection ? { reconnect: entry.connection.id } : {}) } : { url: entry.connection?.url, label: entry.title, key, ...(entry.connection ? { reconnect: entry.connection.id } : {}) }
      connectorsCall<ConnectResult>('connect', body).then((r) => handle(entry, r)).catch((e: unknown) => fail(null, e))
    }
    const submitCustom = (url: string, label: string, key: string, clientId: string, clientSecret: string) => {
      if (!pending || pending.kind !== 'custom') return
      setPending({ ...pending, url, label, busy: true, error: '' })
      const entry: Entry = { id: 'custom', mark: h(Mark, { color: '#64748b', name: label || hostOf(url) }), title: label || hostOf(url), sub: url, about: t('cnCustomAbout', { host: hostOf(url) }), on: false, group: 'misc', tools: [] }
      connectorsCall<ConnectResult>('connect', { url, label, ...(key ? { key } : {}), ...(clientId ? { clientId } : {}), ...(clientSecret ? { clientSecret } : {}) }).then((r) => handle(entry, r)).catch((e: unknown) => fail(null, e))
    }
    const disconnect = (entry: Entry) => {
      if (!entry.connection) return
      connectorsCall('disconnect', { id: entry.connection.id }).then(refresh).then(() => setOpen(null)).catch(() => undefined)
    }
    const setTool = (entry: Entry, name: string, enabled: boolean) => {
      if (!entry.connection) return
      connectorsCall('tool', { id: entry.connection.id, name, enabled }).then(refresh).catch(() => undefined)
    }
    const retry = (entry: Entry) => {
      if (!entry.connection) return
      connectorsCall('retry', { id: entry.connection.id }).then(refresh).catch(() => undefined)
    }
    const searchRegistry = (text: string) => {
      setHits({ q: text, items: [], busy: true, error: '' })
      connectorsCall<{ hits: RegistryHit[] }>(`registry?q=${encodeURIComponent(text)}`)
        .then((r) => setHits({ q: text, items: r.hits, busy: false, error: '' }))
        .catch((e: unknown) => setHits({ q: text, items: [], busy: false, error: e instanceof Error ? e.message : String(e) }))
    }
    const connectHit = (hit: RegistryHit) => {
      setPending({ kind: 'custom', url: hit.url, label: hit.title || hit.name, error: '', busy: false })
    }

    // the sign-in in the browser: follow the flow until the service answers
    const flowId = pending?.kind === 'authorize' && pending.status === 'pending' ? pending.flow : ''
    useEffect(() => {
      if (!flowId) return
      let alive = true
      const tick = () => connectorsCall<FlowView>(`flow?id=${encodeURIComponent(flowId)}`).then((f) => {
        if (!alive || f.status === 'pending') return
        if (f.status === 'done') {
          void refresh().then(() => { if (!alive) return; setPending(null); setOpen(`conn:${f.connectionId}`) })
        } else {
          setPending((p) => (p && p.kind === 'authorize' ? { ...p, status: 'failed', error: f.error } : p))
        }
      }).catch(() => undefined)
      const timer = window.setInterval(() => void tick(), 1500)
      return () => { alive = false; window.clearInterval(timer) }
    }, [flowId, refresh])

    // ---- the views

    if (current) {
      return h(Fragment, null,
        h(Detail, { t, entry: current, onBack: () => setOpen(null), onConnect: () => beginConnect(current), onReconnect: () => reconnect(current), onDisconnect: () => disconnect(current), onRetry: () => retry(current), onTool: (name: string, enabled: boolean) => setTool(current, name, enabled) }),
        pending ? h(PendingSheet, { t, pending, onClose: () => setPending(null), onKey: submitKey, onCustom: submitCustom, onRetry: again }) : null)
    }

    const chips: (Group | 'all')[] = ['all', 'builtin', ...(others.length ? ['preset' as const] : []), ...CATEGORY_ORDER, ...(entries.some((e) => e.group === 'infra') ? ['infra' as const] : [])]

    return h('div', { className: 'nm-section nm-connectors' },
      h('p', null, t('cnLead')),
      h('label', { className: 'nm-lib-search nm-cn-search' },
        h(IconSearch, { size: 16 }),
        h('input', { type: 'search', value: query, placeholder: t('cnSearch'), 'aria-label': t('cnSearch'), onChange: (e: { currentTarget: HTMLInputElement }) => { setQuery(e.currentTarget.value); setHits(null) } })),
      h('div', { className: 'nm-chips nm-cn-chips' }, chips.map((g) => h('button', { key: g, type: 'button', className: `nm-chip${group === g ? ' nm-chip-on' : ''}`, 'aria-pressed': group === g, onClick: () => setGroup(g) }, g === 'all' ? t('cnAll') : groupLabel(t, g)))),
      connected.length ? h(Fragment, null,
        h('h2', null, t('cnConnected')),
        h('div', { className: 'nm-card' }, connected.map((entry) => h(ConnectorRow, { key: entry.id, t, entry, onOpen: () => setOpen(entry.id) })))) : null,
      groups.map((g) => h(Fragment, { key: g },
        h('h2', null, groups.length === 1 && group !== 'all' ? t('cnAvailable') : groupLabel(t, g)),
        h('div', { className: 'nm-card' }, available.filter((e) => e.group === g).map((entry) => h(ConnectorRow, { key: entry.id, t, entry, onOpen: () => setOpen(entry.id), onConnect: () => beginConnect(entry) }))))),
      q && !shown.length ? h('p', { className: 'nm-fine' }, t('cnNoMatch')) : null,
      q.length >= 2 ? h('div', { className: 'nm-card nm-cn-registry' },
        h('button', { type: 'button', className: 'nm-row nm-row-button', onClick: () => searchRegistry(query.trim()), disabled: hits?.busy },
          h('span', { className: 'nm-row-icon' }, h(IconSearch, { size: 18 })),
          h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnRegistrySearch', { q: query.trim() })), h('span', { className: 'nm-row-sub nm-wrap' }, t('cnRegistrySub'))),
          hits?.busy ? h('span', { className: 'nm-spinner nm-spinner-sm' }) : h('span', { className: 'nm-row-chevron' }, h(IconChevronRight, { size: 16 }))),
        hits && !hits.busy && hits.q === query.trim() ? (hits.error ? h('p', { className: 'nm-fine nm-cn-registry-note' }, hits.error) : hits.items.length ? hits.items.map((hit) => h('div', { key: hit.name, className: 'nm-row nm-cn-row' },
          h('div', { className: 'nm-cn-main nm-cn-static' },
            h(Mark, { color: '#64748b', name: hit.title || hit.name }),
            h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, hit.title || hit.name), h('span', { className: 'nm-row-sub nm-wrap' }, hit.description || hostOf(hit.url)))),
          h('button', { type: 'button', className: 'nm-cn-connect', onClick: () => connectHit(hit) }, t('cnConnect')))) : h('p', { className: 'nm-fine nm-cn-registry-note' }, t('cnRegistryNone'))) : null) : null,
      !q && group === 'all' ? h('div', { className: 'nm-card' },
        h('button', { type: 'button', className: 'nm-row nm-row-button', onClick: () => setPending({ kind: 'custom', url: '', label: '', error: '', busy: false }) },
          h('span', { className: 'nm-row-icon' }, h(IconLink, { size: 18 })),
          h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnAddUrl')), h('span', { className: 'nm-row-sub nm-wrap' }, t('cnAddUrlSub'))),
          h('span', { className: 'nm-row-chevron' }, h(IconChevronRight, { size: 16 }))),
        h('button', { type: 'button', className: 'nm-row nm-row-button', onClick: () => { settingsBus.openSection?.('agent-presets') } },
          h('span', { className: 'nm-row-icon' }, h(IconPuzzle, { size: 18 })),
          h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnAdd')), h('span', { className: 'nm-row-sub nm-wrap' }, t('cnAddSub'))),
          h('span', { className: 'nm-row-chevron' }, h(IconChevronRight, { size: 16 })))) : null,
      h('p', { className: 'nm-fine' },
        seen && catalogue ? `${t('cnBuiltinCount', { n: catalogue.builtin })} ` : '',
        t('cnServicesFine', { n: CATALOGUE.length }), ' ',
        h('a', { href: HARNESS_MCP_DOCS, onClick: (e: Event) => { e.preventDefault(); openLink(HARNESS_MCP_DOCS) } }, t('cnDocs'))),
      pending ? h(PendingSheet, { t, pending, onClose: () => setPending(null), onKey: submitKey, onCustom: submitCustom, onRetry: again }) : null)
  }
}

function hostOf(url: string): string {
  try { return new URL(url).host } catch { return url }
}

function ConnectorRow({ t, entry, onOpen, onConnect }: { t: Translate; entry: Entry; onOpen(): void; onConnect?: () => void }): ReactNode {
  const state = entry.connection?.state
  return h('div', { className: 'nm-row nm-cn-row' },
    h('button', { type: 'button', className: 'nm-cn-main', onClick: onOpen },
      entry.mark,
      h('div', { className: 'nm-row-main' },
        h('span', { className: 'nm-row-title' }, entry.title),
        h('span', { className: `nm-row-sub nm-wrap${state && state !== 'ok' ? ' nm-cn-sub-warn' : ''}` }, entry.sub))),
    entry.on
      ? h('span', { className: 'nm-row-chevron', 'aria-hidden': true }, h(IconChevronRight, { size: 16 }))
      : entry.connect
        ? h('button', { type: 'button', className: 'nm-cn-connect', onClick: onConnect }, t('cnConnect'))
        : null)
}

function Switch({ checked, onChange, label }: { checked: boolean; onChange(next: boolean): void; label: string }): ReactNode {
  return h('button', { type: 'button', role: 'switch', className: 'nm-switch', 'aria-checked': checked, 'aria-label': label, onClick: () => onChange(!checked) })
}

function Detail({ t, entry, onBack, onConnect, onReconnect, onDisconnect, onRetry, onTool }: { t: Translate; entry: Entry; onBack(): void; onConnect(): void; onReconnect(): void; onDisconnect(): void; onRetry(): void; onTool(name: string, enabled: boolean): void }): ReactNode {
  const c = entry.connection
  const service = entry.service
  const [armed, setArmed] = useState(false)
  const armTimer = useRef(0)
  useEffect(() => () => window.clearTimeout(armTimer.current), [])
  const askDisconnect = () => {
    if (armed) { setArmed(false); onDisconnect(); return }
    setArmed(true)
    armTimer.current = window.setTimeout(() => setArmed(false), 6000)
  }
  const docs = service?.docs
  const authNote = service ? (service.auth.kind === 'oauth' ? t('cnAuthOauth') : service.auth.kind === 'key' ? t('cnAuthKey') : service.auth.kind === 'none' ? t('cnAuthNone') : t('cnAuthAuto')) : c ? (c.auth === 'oauth' ? t('cnAuthOauth') : c.auth === 'none' ? t('cnAuthNone') : t('cnAuthKey')) : ''

  return h('div', { className: 'nm-section nm-cn-detail' },
    h('button', { type: 'button', className: 'nm-cn-back', onClick: onBack }, h(IconChevronLeft, { size: 16 }), t('navConnectors')),
    h('div', { className: 'nm-cn-hero' },
      h('span', { className: 'nm-cn-hero-mark' }, service ? h(Mark, { icon: service.icon, color: service.color, name: service.name, size: 28 }) : c ? h(Mark, { color: '#64748b', name: c.label, size: 28 }) : entry.mark),
      h('div', { className: 'nm-cn-hero-main' },
        h('h3', null, entry.title),
        h('p', null, entry.about),
        c && c.state !== 'ok' ? h('p', { className: 'nm-cn-warn' }, c.state === 'reauth' ? t('cnReauthLong') : c.error || t('cnErrorSub')) : null),
      entry.on && !c
        ? h('span', { className: 'nm-state nm-state-on nm-cn-state' }, h(IconCheck, { size: 14 }), ' ', t('cnConnectedOne'))
        : !entry.on && entry.connect ? h('button', { type: 'button', className: 'nm-cn-connect nm-cn-connect-big', onClick: onConnect }, t('cnConnect')) : null),
    c ? h('div', { className: 'nm-cn-actions' },
      c.state === 'ok' ? h('span', { className: 'nm-state nm-state-on' }, h(IconCheck, { size: 14 }), ' ', t('cnConnectedSince', { date: new Date(c.connectedAt).toLocaleDateString() })) : null,
      c.state === 'error' ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-cn-pill', onClick: onRetry }, h(IconRefresh, { size: 14 }), t('cnRetry')) : null,
      c.auth === 'oauth' || c.state === 'reauth' ? h('button', { type: 'button', className: `nm-pill nm-cn-pill${c.state === 'reauth' ? '' : ' nm-pill-ghost'}`, onClick: onReconnect }, t(c.state === 'reauth' ? 'cnSignInAgain' : 'cnReconnect')) : null,
      c.auth === 'header' || c.auth === 'query' ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-cn-pill', onClick: onReconnect }, t('cnNewKey')) : null,
      h('button', { type: 'button', className: `nm-pill nm-pill-ghost nm-cn-pill${armed ? ' nm-cn-pill-danger' : ''}`, onClick: askDisconnect }, armed ? t('cnDisconnectSure') : t('cnDisconnect'))) : null,
    entry.tools.length ? h(Fragment, null,
      h('h2', null, c ? t('cnToolsTitle') : t('cnCanDo')),
      c ? h('p', { className: 'nm-fine nm-cn-tools-lead' }, t('cnToolsLead', { prefix: `mcp__${c.serverName}__` })) : null,
      h('div', { className: 'nm-card' }, entry.tools.map((tool) => {
        const enabled = !c || !c.disabled.includes(tool.name)
        return h('div', { key: tool.name, className: `nm-row${enabled ? '' : ' nm-cn-tool-off'}` },
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, h('code', null, tool.name)),
            tool.description ? h('span', { className: 'nm-row-sub nm-wrap' }, tool.description) : null),
          c ? h(Switch, { checked: enabled, label: tool.name, onChange: (next: boolean) => onTool(tool.name, next) }) : null)
      }))) : c && c.state === 'ok' ? h('p', { className: 'nm-fine' }, t('cnNoTools')) : null,
    h('h2', null, t('cnGates')),
    h('div', { className: 'nm-card' },
      h('button', { type: 'button', className: 'nm-row nm-row-button', onClick: () => { settingsBus.openSection?.(PERMISSIONS_SECTION) } },
        h('span', { className: 'nm-row-icon' }, h(IconShield, { size: 18 })),
        h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnGatePolicy')), h('span', { className: 'nm-row-sub nm-wrap' }, t('cnGatePolicySub'))),
        h('span', { className: 'nm-row-chevron' }, h(IconChevronRight, { size: 16 }))),
      entry.id === 'hands' || entry.id === 'email' ? h('div', { className: 'nm-row' },
        h('span', { className: 'nm-row-icon' }, h(IconHand, { size: 18 })),
        h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnGateSentinel')), h('span', { className: 'nm-row-sub nm-wrap' }, entry.id === 'email' ? t('cnGateSentinelMail') : t('cnGateSentinelHands')))) : null,
      c || service ? h('div', { className: 'nm-row' },
        h('span', { className: 'nm-row-icon' }, h(IconLink, { size: 18 })),
        h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnGateCreds')), h('span', { className: 'nm-row-sub nm-wrap' }, authNote))) : null,
      entry.page ? h('button', { type: 'button', className: 'nm-row nm-row-button', onClick: () => { settingsBus.openSection?.(entry.page!) } },
        h('span', { className: 'nm-row-icon' }, h(IconLink, { size: 18 })),
        h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnOwnPage'))),
        h('span', { className: 'nm-row-chevron' }, h(IconChevronRight, { size: 16 }))) : null,
      docs ? h('button', { type: 'button', className: 'nm-row nm-row-button', onClick: () => openLink(docs) },
        h('span', { className: 'nm-row-icon' }, h(IconExternal, { size: 18 })),
        h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnVendorDocs', { name: service?.name ?? '' })), h('span', { className: 'nm-row-sub nm-wrap' }, hostOf(docs))),
        h('span', { className: 'nm-row-chevron' }, h(IconChevronRight, { size: 16 }))) : null),
    c || service ? h('p', { className: 'nm-fine nm-cn-url' }, h('code', null, c?.url ?? service?.url ?? '')) : null,
    h('p', { className: 'nm-fine' }, t('cnDetailFine')))
}

function PendingSheet({ t, pending, onClose, onKey, onCustom, onRetry }: { t: Translate; pending: Pending; onClose(): void; onKey(key: string): void; onCustom(url: string, label: string, key: string, clientId: string, clientSecret: string): void; onRetry(fresh: boolean): void }): ReactNode {
  switch (pending.kind) {
    case 'steps': return h(StepsSheet, { t, entry: pending.entry, onClose })
    case 'authorize': return h(AuthorizeSheet, { t, pending, onClose, onRetry })
    case 'key': return h(KeySheet, { t, pending, onClose, onKey })
    case 'custom': return h(CustomSheet, { t, pending, onClose, onCustom })
  }
}

function AuthorizeSheet({ t, pending, onClose, onRetry }: { t: Translate; pending: Extract<Pending, { kind: 'authorize' }>; onClose(): void; onRetry(fresh: boolean): void }): ReactNode {
  const { entry, status, url, error } = pending
  return h(Sheet, { title: t('cnConnectTitle', { name: entry.title }), onClose, closeLabel: t('close'), footer: h(Fragment, null,
    status === 'failed' ? h('button', { type: 'button', className: 'nm-pill', onClick: () => onRetry(/invalid_client/.test(error)) }, t('cnTryAgain')) : null,
    url && status === 'pending' ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost', onClick: () => openLink(url) }, t('cnOpenAgain')) : null,
    url && status === 'pending' ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost', title: t('cnStartOverSub'), onClick: () => onRetry(true) }, t('cnStartOver')) : null,
    h('button', { type: 'button', className: 'nm-pill nm-pill-ghost', onClick: onClose }, t(status === 'failed' ? 'close' : 'cancel'))) },
    h('div', { className: 'nm-cn-consent' },
      h('span', { className: 'nm-cn-hero-mark' }, entry.mark),
      h('p', { className: 'nm-cn-consent-lead' }, entry.about)),
    status === 'failed'
      ? h('div', { className: 'nm-cn-wait nm-cn-wait-failed' }, h('strong', null, t('cnFailed')), h('span', null, error || t('cnFailedSub')))
      : h('div', { className: 'nm-cn-wait' }, h('span', { className: 'nm-spinner nm-spinner-sm' }), h('span', null, url ? t('cnWaiting', { name: entry.title }) : t('cnPreparing'))),
    h('div', { className: 'nm-card' },
      h('div', { className: 'nm-row' }, h('span', { className: 'nm-row-icon' }, h(IconCheck, { size: 18 })), h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnConsentGets')), h('span', { className: 'nm-row-sub nm-wrap' }, t('cnOauthGets')))),
      h('div', { className: 'nm-row' }, h('span', { className: 'nm-row-icon' }, h(IconShield, { size: 18 })), h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnConsentYou')), h('span', { className: 'nm-row-sub nm-wrap' }, t('cnOauthYou')))),
      h('div', { className: 'nm-row' }, h('span', { className: 'nm-row-icon' }, h(IconFolder, { size: 18 })), h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnConsentWhere')), h('span', { className: 'nm-row-sub nm-wrap' }, t('cnOauthWhere'))))))
}

function KeySheet({ t, pending, onClose, onKey }: { t: Translate; pending: Extract<Pending, { kind: 'key' }>; onClose(): void; onKey(key: string): void }): ReactNode {
  const { entry, where, error, busy } = pending
  const [key, setKey] = useState('')
  const docs = entry.service?.docs
  const submit = () => { if (key.trim() && !busy) onKey(key.trim()) }
  return h(Sheet, { title: t('cnConnectTitle', { name: entry.title }), onClose, closeLabel: t('close'), footer: h(Fragment, null,
    h('button', { type: 'button', className: 'nm-pill nm-pill-ghost', onClick: onClose }, t('cancel')),
    h('button', { type: 'button', className: 'nm-pill', disabled: !key.trim() || busy, onClick: submit }, busy ? h('span', { className: 'nm-spinner nm-spinner-sm nm-cn-pill-spin' }) : null, t('cnConnect'))) },
    h('div', { className: 'nm-cn-consent' },
      h('span', { className: 'nm-cn-hero-mark' }, entry.mark),
      h('p', { className: 'nm-cn-consent-lead' }, entry.about)),
    h('p', { className: 'nm-cn-key-where' }, where || t('cnKeyWhereGeneric'), docs ? h(Fragment, null, ' ', h('a', { href: docs, onClick: (e: Event) => { e.preventDefault(); openLink(docs) } }, t('cnVendorDocs', { name: entry.title }))) : null),
    h('input', { className: 'nm-field nm-cn-key', type: 'password', autoComplete: 'off', spellCheck: false, value: key, placeholder: t('cnKeyPlaceholder'), 'aria-label': t('cnKeyPlaceholder'), onChange: (e: { currentTarget: HTMLInputElement }) => setKey(e.currentTarget.value), onKeyDown: (e: KeyboardEvent) => { if (e.key === 'Enter') submit() } }),
    error ? h('p', { className: 'nm-cn-warn' }, error) : null,
    h('p', { className: 'nm-fine' }, t('cnKeyFine')))
}

function CustomSheet({ t, pending, onClose, onCustom }: { t: Translate; pending: Extract<Pending, { kind: 'custom' }>; onClose(): void; onCustom(url: string, label: string, key: string, clientId: string, clientSecret: string): void }): ReactNode {
  const [url, setUrl] = useState(pending.url)
  const [label, setLabel] = useState(pending.label)
  const [key, setKey] = useState('')
  const [more, setMore] = useState(false)
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const valid = /^https?:\/\/\S+$/i.test(url.trim())
  const submit = () => { if (valid && !pending.busy) onCustom(url.trim(), label.trim(), key.trim(), clientId.trim(), clientSecret.trim()) }
  const field = (value: string, set: (v: string) => void, placeholder: string, type = 'text') =>
    h('input', { className: 'nm-field nm-cn-field', type, autoComplete: 'off', spellCheck: false, value, placeholder, 'aria-label': placeholder, onChange: (e: { currentTarget: HTMLInputElement }) => set(e.currentTarget.value), onKeyDown: (e: KeyboardEvent) => { if (e.key === 'Enter') submit() } })
  return h(Sheet, { title: t('cnCustomTitle'), onClose, closeLabel: t('close'), footer: h(Fragment, null,
    h('button', { type: 'button', className: 'nm-pill nm-pill-ghost', onClick: onClose }, t('cancel')),
    h('button', { type: 'button', className: 'nm-pill', disabled: !valid || pending.busy, onClick: submit }, pending.busy ? h('span', { className: 'nm-spinner nm-spinner-sm nm-cn-pill-spin' }) : null, t('cnConnect'))) },
    h('p', { className: 'nm-cn-consent-lead nm-cn-custom-lead' }, t('cnCustomLead')),
    field(url, setUrl, t('cnCustomUrl'), 'url'),
    field(label, setLabel, t('cnCustomLabel')),
    field(key, setKey, t('cnCustomKey'), 'password'),
    h('button', { type: 'button', className: 'nm-cn-more', 'aria-expanded': more, onClick: () => setMore(!more) }, more ? t('cnLessOptions') : t('cnMoreOptions')),
    more ? h(Fragment, null,
      h('p', { className: 'nm-fine' }, t('cnClientFine')),
      field(clientId, setClientId, t('cnClientId')),
      field(clientSecret, setClientSecret, t('cnClientSecret'), 'password')) : null,
    pending.error ? h('p', { className: 'nm-cn-warn' }, pending.error) : null,
    h('p', { className: 'nm-fine' }, t('cnCustomFine'), ' ', h('a', { href: REGISTRY_SITE, onClick: (e: Event) => { e.preventDefault(); openLink(REGISTRY_SITE) } }, t('cnRegistrySite'))))
}

function StepsSheet({ t, entry, onClose }: { t: Translate; entry: Entry; onClose(): void }): ReactNode {
  const steps = entry.connect && 'steps' in entry.connect ? entry.connect.steps : []
  const [copied, setCopied] = useState<number | null>(null)
  const copy = (i: number, text: string) => {
    void navigator.clipboard?.writeText(text).then(() => { setCopied(i); window.setTimeout(() => setCopied((c) => (c === i ? null : c)), 1500) }).catch(() => undefined)
  }
  return h(Sheet, { title: t('cnConnectTitle', { name: entry.title }), onClose, closeLabel: t('close'), footer: h(Fragment, null,
    h('button', { type: 'button', className: 'nm-pill nm-pill-ghost', onClick: () => { void roomsCall('files/reveal', { which: 'runtime' }).catch(() => undefined) } }, t('cnOpenConfig')),
    h('button', { type: 'button', className: 'nm-pill', onClick: onClose }, t('cnDone'))) },
    h('div', { className: 'nm-cn-consent' },
      h('span', { className: 'nm-cn-hero-mark' }, entry.mark),
      h('p', { className: 'nm-cn-consent-lead' }, entry.about)),
    h('div', { className: 'nm-card' },
      h('div', { className: 'nm-row' }, h('span', { className: 'nm-row-icon' }, h(IconCheck, { size: 18 })), h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnConsentGets')), h('span', { className: 'nm-row-sub nm-wrap' }, t('cnConsentGetsSub')))),
      h('div', { className: 'nm-row' }, h('span', { className: 'nm-row-icon' }, h(IconShield, { size: 18 })), h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnConsentYou')), h('span', { className: 'nm-row-sub nm-wrap' }, t('cnConsentYouSub')))),
      h('div', { className: 'nm-row' }, h('span', { className: 'nm-row-icon' }, h(IconFolder, { size: 18 })), h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('cnConsentWhere')), h('span', { className: 'nm-row-sub nm-wrap' }, t('cnConsentWhereSub'))))),
    h('h2', null, t('cnHowTo')),
    h('ol', { className: 'nm-cn-steps' }, steps.map((step, i) => h('li', { key: i },
      h('span', null, step.text),
      step.command ? h('div', { className: 'nm-cn-command' },
        h('pre', null, step.command),
        h('button', { type: 'button', className: 'nm-cn-copy', 'aria-label': t('edCopy'), title: t('edCopy'), onClick: () => copy(i, step.command!) }, copied === i ? h(IconCheck, { size: 14 }) : h(IconCopy, { size: 14 }))) : null))),
    h('p', { className: 'nm-fine' }, t('cnHowToFine'), ' ', h('a', { href: RUNTIME_DOCS, onClick: (e: Event) => { e.preventDefault(); openLink(RUNTIME_DOCS) } }, t('cnRuntimeDocs'))))
}
