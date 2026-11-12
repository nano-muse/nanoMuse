import { createElement as h, useEffect, useRef, useState, type ChangeEvent, type ReactNode } from 'react'
import { Button } from '@deepseek-ai/dsh-client-ui-primitives'
import type { DeviceConversation } from '../device-conversations.ts'
import { call, failureText, type Translate } from './api.ts'
import type { LiveDevice } from './live.ts'
import { canStartBoundDeviceChat, deviceChatAccent, deviceChatLabel } from '../device-chat.ts'
import { DeviceChatDrafts } from '../device-chat-drafts.ts'

const openListeners = new Set<(id: string) => void>()
let queuedConversationId: string | null = null

/** Open a newly created conversation after the Devices panel mounts. */
export function openDeviceConversation(id: string): void {
  queuedConversationId = id
  for (const listener of openListeners) listener(id)
  if (openListeners.size) queuedConversationId = null
}

type Event = Record<string, unknown>
const api = <T,>(action: string, fields: Event = {}) =>
  call<T>('devices/conversations', { action, ...fields })

export function DeviceConversationPanel({ t, devices }: { t: Translate; devices: LiveDevice[] }): ReactNode {
  const [chats, setChats] = useState<DeviceConversation[]>([])
  const [selected, select] = useState('')
  const [destination, choose] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [events, setEvents] = useState<Event[]>([])
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const currentDrafts = useRef(new DeviceChatDrafts((id, text) => api<DeviceConversation>('draft', { id, text })))
  const pendingDrafts = useRef(new Map<string, string>())
  const draftTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const chat = chats.find((row) => row.id === selected)
  const active = chat?.turns.at(-1)
  const pending = active?.state === 'accepted' || active?.state === 'unknown'
  const target = devices.find((device) => device.id === chat?.device)
  const activeTarget = devices.find((device) => device.id === (active?.destination?.id ?? chat?.device))
  const label = (id: string, name: string) => {
    const current = devices.find((device) => device.id === id)
    return current ? deviceChatLabel(current) : `${name} · ${id.slice(-6)}`
  }
  const color = deviceChatAccent
  const save = (row: DeviceConversation) => setChats((old) =>
    old.some((entry) => entry.id === row.id) ? old.map((entry) => entry.id === row.id ? row : entry) : [...old, row])
  const flushDraft = (showError = true) => {
    const pending = [...pendingDrafts.current]
    pendingDrafts.current.clear()
    if (draftTimer.current) clearTimeout(draftTimer.current)
    draftTimer.current = null
    if (pending.length) void Promise.all(pending.map(([id, text]) => currentDrafts.current.save(id, text)))
      .catch((err: unknown) => { if (showError) setError(failureText(t, err)) })
  }
  const queueDraft = (id: string, text: string) => {
    pendingDrafts.current.set(id, text)
    if (draftTimer.current) clearTimeout(draftTimer.current)
    draftTimer.current = setTimeout(() => flushDraft(), 250)
  }

  useEffect(() => {
    let active = true
    void api<DeviceConversation[]>('list').then((rows) => {
      if (active) {
        setChats(rows)
        setDrafts(currentDrafts.current.hydrate(rows))
      }
    })
      .catch((err: unknown) => { if (active) setError(failureText(t, err)) })
    return () => { active = false }
  }, [t])
  useEffect(() => () => flushDraft(false), [])
  useEffect(() => {
    const onOpen = (id: string) => select(id)
    openListeners.add(onOpen)
    if (queuedConversationId) {
      onOpen(queuedConversationId)
      queuedConversationId = null
    }
    return () => { openListeners.delete(onOpen) }
  }, [])
  useEffect(() => {
    setEvents([])
    if (!selected || !activeTarget?.online) return
    let active = true
    let busy = false
    const refresh = async () => {
      if (busy) return
      busy = true
      try {
        const result = await api<{ chat: DeviceConversation; events: Event[] }>('refresh', { id: selected })
        if (active) { save(result.chat); setEvents(result.events) }
      } catch (err) {
        if (active) setError(failureText(t, err))
      } finally { busy = false }
    }
    void refresh()
    const timer = setInterval(() => { void refresh() }, 2500)
    return () => { active = false; clearInterval(timer) }
  }, [selected, activeTarget?.online, t])

  const run = (work: Promise<unknown>) => {
    setError('')
    void work.catch((err: unknown) => setError(failureText(t, err)))
  }
  const send = (id: string) => {
    const text = currentDrafts.current.get(id)
    setSending(true)
    run(currentDrafts.current.save(id, text).then(() => api<DeviceConversation>('send', { id, text })).then((row) => {
      save(row)
      const cleared = currentDrafts.current.clearSent(id, text)
      if (cleared) {
        setDrafts(cleared)
        queueDraft(id, '')
      }
    }).finally(() => setSending(false)))
  }
  const stateText = (state: string) => state === 'unknown' ? t('deviceChatUnknown')
    : state === 'accepted' ? t('deviceChatRunning')
    : state === 'interrupted' ? t('deviceChatInterrupted')
    : state === 'cancelled' ? t('deviceChatCancelled')
    : state === 'failed' ? t('deviceChatFailed') : ''
  return h('section', null,
    h('h2', null, t('deviceChats')),
    h('select', { value: destination, 'aria-label': t('otherDevices'), onChange: (e: ChangeEvent<HTMLSelectElement>) => choose(e.currentTarget.value) },
      h('option', { value: '' }, t('otherDevices')),
      ...devices.filter((device) => device.kind !== 'web').map((device) => h('option', { key: device.id, value: device.id }, label(device.id, device.name)))),
    h(Button, { disabled: !devices.some((device) => device.id === destination && canStartBoundDeviceChat(device)), onClick: () =>
      run(api<DeviceConversation>('create', { device: destination }).then((row) => { save(row); select(row.id) })) }, t('deviceChatStart')),
    h('ul', null, ...chats.map((row) => h('li', { key: row.id },
      h('button', { onClick: () => select(row.id), 'aria-pressed': row.id === selected, style: { borderInlineStart: `3px solid ${color(row.device)}` } },
        `${label(row.device, row.name)} · ${row.turns[0]?.text.slice(0, 48) ?? row.id.slice(0, 8)}`)))),
    chat ? h('article', null,
      h('h3', { style: { borderInlineStart: `3px solid ${color(chat.device)}`, paddingInlineStart: 8 } }, label(chat.device, chat.name)),
      h('p', null, t(!target?.online ? 'deviceOffline' : canStartBoundDeviceChat(target) ? 'deviceOnline' : 'deviceNotReachable')),
      ...chat.turns.map((turn) => h('div', { key: turn.id },
        turn.destination ? h('small', null, label(turn.destination.id, turn.destination.name)) : null,
        h('p', null, turn.text),
        h('p', { style: { whiteSpace: 'pre-wrap' } }, turn.answer ?? stateText(turn.state)),
        turn.error ? h('small', null, turn.error) : null)),
      ...(pending ? events.map((event, index) => event.stage === 'approval'
        ? h('div', { key: String(event.approval_id) }, String(event.preview ?? ''),
          ...[true, false].map((allow) => h(Button, { key: String(allow), onClick: () =>
            run(api('approve', { id: chat.id, approval_id: event.approval_id, allow })) }, t(allow ? 'deviceChatAllow' : 'deviceChatDeny'))))
        : h('p', { key: index }, String(event.text ?? event.summary ?? event.name ?? ''))) : []),
      h('textarea', { value: drafts[chat.id] ?? '', 'aria-label': t('deviceChatSend'),
        onChange: (e: ChangeEvent<HTMLTextAreaElement>) => {
          const value = e.currentTarget.value
          setDrafts(currentDrafts.current.set(chat.id, value))
          queueDraft(chat.id, value)
        } }),
      h(Button, { disabled: sending || pending || !drafts[chat.id]?.trim()
        || (!drafts[chat.id]?.trimStart().startsWith('@') && (!target || !canStartBoundDeviceChat(target)
        || chat.turns.some((turn) => !turn.destination && turn.error === 'context_lost'))), onClick: () => send(chat.id) }, t('deviceChatSend')),
      pending ? h(Button, { disabled: !activeTarget?.online, onClick: () => run(api('stop', { id: chat.id })) }, t('deviceChatStop')) : null) : null,
    error ? h('p', { role: 'alert' }, error) : null)
}
