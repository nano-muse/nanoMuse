import { randomUUID } from 'node:crypto'
import { HubError, type HubDevice } from './hub.ts'

export interface OutgoingTurn {
  id: string
  text: string
  state: string
  answer?: string
  error?: string
  /** A definite call rejection, before the target accepted this turn. */
  rejectedBeforeAcceptance?: boolean
  destination?: { id: string; name: string; conversation: string }
}

export interface DeviceConversation {
  id: string
  device: string
  name: string
  turns: OutgoingTurn[]
}

type Reply = Record<string, unknown>
type Call = (to: string, action: string, args: Reply, event?: (event: Reply) => void) => Promise<Reply>

/** Caller policy: a turn has one dispatch, and recovery is a read of the target journal. */
export class DeviceConversations {
  constructor(
    private readonly read: () => DeviceConversation[],
    private readonly write: (rows: DeviceConversation[]) => Promise<void>,
    private readonly devices: () => HubDevice[],
    private readonly call: Call,
  ) {}

  private pending: Promise<unknown> = Promise.resolve()

  list(): DeviceConversation[] {
    return this.read()
  }

  create(id: string): Promise<DeviceConversation> {
    const device = this.requireDevice(id)
    const chat: DeviceConversation = { id: randomUUID(), device: id, name: device.name, turns: [] }
    return this.update((rows) => [...rows, chat]).then(() => chat)
  }

  async send(id: string, text: string, event?: (event: Reply) => void): Promise<DeviceConversation> {
    const chat = this.find(id)
    const mention = this.mention(text)
    const destination = mention ? { id: mention.device.id, name: mention.device.name, conversation: randomUUID() } : undefined
    const device = destination?.id ?? chat.device
    this.requireDevice(device)
    const prompt = (mention?.text ?? text).trim()
    if (!prompt) throw new HubError('usage', 'Enter a message')
    const turn: OutgoingTurn = { id: randomUUID(), text: text.trim(), state: 'unknown', ...(destination ? { destination } : {}) }
    let first = false
    await this.update((rows) => rows.map((row) => {
      if (row.id !== id) return row
      if (row.turns.some((entry) => unsettled(entry.state))) throw new HubError('busy', 'Resolve the previous turn before sending another')
      if (!destination && row.turns.some((entry) => !entry.destination && entry.error === 'context_lost')) {
        throw new HubError('context_lost', 'Start a new conversation on this device')
      }
      first = !!destination || row.turns.every((entry) => entry.destination !== undefined || entry.rejectedBeforeAcceptance === true)
      return { ...row, turns: [...row.turns, turn] }
    }))
    try {
      const reply = await this.call(device, 'task', {
        text: prompt, conversation: destination?.conversation ?? id, turn_id: turn.id, new_conversation: first, stream: true,
      }, event)
      await this.reconcile(id, turn.id, reply)
    } catch (error) {
      // A timeout, close or transport error cannot tell us whether the executor ran.
      if (error instanceof HubError && ['not_allowed', 'denied', 'usage', 'no_model', 'not_ready', 'context_lost', 'busy'].includes(error.code)) {
        await this.reconcile(id, turn.id, { state: 'failed', error: error.code }, true)
      }
    }
    return this.find(id)
  }

  async refresh(id: string): Promise<{ chat: DeviceConversation; events: Reply[] }> {
    const chat = this.find(id)
    const turn = chat.turns.findLast((entry) => unsettled(entry.state))
    if (!turn) return { chat, events: [] }
    const device = turn.destination?.id ?? chat.device
    this.requireDevice(device)
    const result = await this.call(device, 'task.status', { conversation: turn.destination?.conversation ?? id, turn_id: turn.id })
    await this.reconcile(id, turn.id, result)
    return { chat: this.find(id), events: Array.isArray(result.events) ? result.events as Reply[] : [] }
  }

  async stop(id: string): Promise<boolean> {
    const chat = this.find(id)
    const turn = chat.turns.findLast((entry) => unsettled(entry.state))
    if (!turn) return false
    const result = await this.call(turn.destination?.id ?? chat.device, 'stop', { conversation: turn.destination?.conversation ?? id, turn_id: turn.id })
    return result.stopped === true
  }

  async approve(id: string, approvalId: string, allow: boolean): Promise<void> {
    const chat = this.find(id)
    const turn = chat.turns.findLast((entry) => unsettled(entry.state))
    if (turn) await this.call(turn.destination?.id ?? chat.device, 'approve', { approval_id: approvalId, allow })
  }

  private find(id: string): DeviceConversation {
    const chat = this.read().find((row) => row.id === id)
    if (!chat) throw new HubError('not_found', 'Conversation not found')
    return chat
  }

  private requireDevice(id: string): HubDevice {
    const device = this.devices().find((row) => row.id === id)
    if (!device?.online) throw new HubError('device_offline', 'The destination is offline')
    if (!device.actions.includes('task.status')) throw new HubError('unknown_action', 'The destination does not support persistent conversations')
    return device
  }

  private mention(text: string): { device: HubDevice; text: string } | undefined {
    const input = text.trimStart()
    if (!input.startsWith('@')) return undefined
    const candidates = this.devices().flatMap((device) =>
      [`@${device.name} [${device.id}]`, `@${device.name}`].flatMap((prefix) =>
        input.toLowerCase().startsWith(prefix.toLowerCase()) &&
        (input.length === prefix.length || /^\s/.test(input.slice(prefix.length)))
          ? [{ device, prefix }] : []))
      .sort((a, b) => b.prefix.length - a.prefix.length)
    const first = candidates[0]
    if (!first) return undefined
    if (candidates[1]?.prefix.length === first.prefix.length) {
      throw new HubError('usage', 'More than one device has that name. Include its device ID in brackets.')
    }
    return { device: first.device, text: input.slice(first.prefix.length).trim() }
  }

  private update(fn: (rows: DeviceConversation[]) => DeviceConversation[]): Promise<void> {
    const result = this.pending.then(() => this.write(fn(this.read())))
    this.pending = result.catch(() => undefined)
    return result
  }

  private reconcile(id: string, turn: string, reply: Reply, rejectedBeforeAcceptance = false): Promise<void> {
    const state = String(reply.state ?? '')
    if (!['unknown', 'accepted', 'completed', 'failed', 'cancelled', 'interrupted'].includes(state)) return Promise.resolve()
    return this.update((rows) => rows.map((row) => row.id !== id ? row : {
      ...row, turns: row.turns.map((entry) => entry.id !== turn || !unsettled(entry.state) ? entry : {
        ...entry, state, ...(rejectedBeforeAcceptance ? { rejectedBeforeAcceptance: true } : {}),
        ...(typeof reply.text === 'string' ? { answer: reply.text } : {}),
        ...(typeof reply.error === 'string' ? { error: reply.error } : {}),
      }),
    }))
  }
}

function unsettled(state: string): boolean {
  return state === 'unknown' || state === 'accepted'
}
