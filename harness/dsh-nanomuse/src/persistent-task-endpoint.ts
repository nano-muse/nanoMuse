import { HubError, type IncomingCall } from './hub.ts'
import type { PersistentTurns, TerminalTurn, TurnOwner } from './persistent-turns.ts'

type Event = Record<string, unknown>

class LiveTurn {
  readonly callId: string
  private readonly recent: Event[] = []
  private readonly approvals = new Map<string, { event: Event; expiry: number }>()

  constructor(callId: string) {
    this.callId = callId
  }

  record(event: Event): void {
    if (JSON.stringify(event).length > 4000) return
    if (event.stage === 'approval' && typeof event.approval_id === 'string') {
      const seconds = Number(event.timeout)
      if (seconds > 0 && Number.isFinite(seconds)) {
        this.approvals.set(event.approval_id, { event, expiry: Date.now() + seconds * 1000 })
      }
    } else if (event.stage === 'approval_result') {
      this.approvals.delete(String(event.approval_id))
    } else if (['thinking', 'tool', 'tool_result', 'text'].includes(String(event.stage))) {
      if (event.stage === 'text' && this.recent.at(-1)?.partial === true) this.recent.pop()
      this.recent.push(event)
      if (this.recent.length > 8) this.recent.shift()
    }
  }

  events(): Event[] {
    const now = Date.now()
    const approvals = [...this.approvals.values()]
      .filter(({ expiry }) => expiry > now)
      .slice(-4)
      .map(({ event, expiry }) => ({ ...event, timeout: Math.ceil((expiry - now) / 1000) }))
    return [...this.recent, ...approvals]
  }
}

/** Transport IDs are live routing handles. The journal owns the durable turn identity. */
export class PersistentTaskEndpoint {
  private readonly journal: PersistentTurns
  private readonly calls = new Map<string, LiveTurn>()

  constructor(journal: PersistentTurns) {
    this.journal = journal
  }

  status(owner: TurnOwner, turn: string): Record<string, unknown> {
    const result = this.journal.status(owner, turn)
    const live = this.calls.get(this.key(owner, turn))
    return result?.state === 'accepted' && live ? { ...result, events: live.events() } : result ?? { state: 'unknown' }
  }

  callId(owner: TurnOwner, turn: string): string | undefined {
    if (this.journal.status(owner, turn)?.state !== 'accepted') return undefined
    return this.calls.get(this.key(owner, turn))?.callId
  }

  async run(
    owner: TurnOwner,
    turn: string,
    call: IncomingCall,
    create: () => Promise<string>,
    execute: (session: string, emit: (event: Event) => void) => Promise<Record<string, unknown>>,
  ): Promise<Record<string, unknown>> {
    let reservation
    try {
      reservation = await this.journal.accept(owner, turn, create)
    } catch (error) {
      if (error instanceof HubError) throw error
      const code = (error as { code?: string }).code
      if (code === 'usage' || code === 'busy') throw new HubError(code, (error as Error).message)
      throw new HubError('failed', 'Could not persist acceptance on the execution device')
    }
    if (!reservation.accepted) return reservation.result

    const key = this.key(owner, turn)
    const live = new LiveTurn(call.id)
    this.calls.set(key, live)
    const emit = (event: Event) => {
      live.record(event)
      // Delivery is opportunistic. A vanished socket must not change the executor outcome.
      try { call.event(event) } catch { /* The caller can query the retained state. */ }
    }
    try {
      let result: TerminalTurn
      try {
        emit({ stage: 'accepted', turn_id: turn })
        const answer = await execute(reservation.session, emit)
        result = { state: 'completed', text: String(answer.text ?? '') }
      } catch (error) {
        const failure = error instanceof HubError ? error : new HubError('failed', 'The execution device could not finish the turn')
        result = failure.code === 'cancelled'
          ? { state: 'cancelled' }
          : { state: 'failed', error: failure.code, message: failure.message }
      }
      await this.journal.finish(owner, turn, result)
      return result
    } finally {
      this.calls.delete(key)
    }
  }

  private key(owner: TurnOwner, turn: string): string {
    return JSON.stringify([owner.account, owner.caller, owner.conversation, turn])
  }
}
