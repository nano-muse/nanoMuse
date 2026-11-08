import { mkdir, open, readFile, rename, rm } from 'node:fs/promises'
import { dirname } from 'node:path'

export interface TurnOwner {
  account: string
  caller: string
  conversation: string
}

export type TerminalTurn =
  | { state: 'cancelled' | 'interrupted' }
  | { state: 'completed'; text: string }
  | { state: 'failed'; error: string; message: string }
export type TurnResult = { state: 'accepted' } | TerminalTurn

type Conversation = { session: string; turns: Record<string, TurnResult> }
type Journal = Record<string, Conversation>
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

function scopedKey(owner: TurnOwner, turn: string): string {
  if (!owner.account || !owner.caller || !uuid.test(owner.conversation) || !uuid.test(turn)) {
    throw Object.assign(new Error('A conversation UUID and turn UUID are required'), { code: 'usage' })
  }
  return JSON.stringify([owner.account, owner.caller, owner.conversation])
}

/** One journal per executor process. A published snapshot always follows its disk commit. */
export class PersistentTurns {
  private readonly live = new Set<string>()
  private queue: Promise<unknown> = Promise.resolve()
  private readonly file: string
  private journal: Journal

  private constructor(file: string, journal: Journal) {
    this.file = file
    this.journal = journal
  }

  static async open(file: string): Promise<PersistentTurns> {
    try {
      return new PersistentTurns(file, JSON.parse(await readFile(file, 'utf8')) as Journal)
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
      return new PersistentTurns(file, {})
    }
  }

  status(owner: TurnOwner, turn: string): TurnResult | undefined {
    const key = scopedKey(owner, turn)
    const result = this.journal[key]?.turns[turn]
    return result?.state === 'accepted' && !this.live.has(key + turn) ? { state: 'interrupted' } : result
  }

  accept(owner: TurnOwner, turn: string, create: () => Promise<string>) {
    return this.serial(async () => {
      const key = scopedKey(owner, turn)
      const prior = this.journal[key]
      const existing = this.status(owner, turn)
      if (existing) return { accepted: false, session: prior!.session, result: existing }
      if (Object.keys(prior?.turns ?? {}).some((id) => this.live.has(key + id))) {
        throw Object.assign(new Error('This conversation is already running a turn'), { code: 'busy' })
      }
      const session = prior?.session ?? await create()
      const result: TurnResult = { state: 'accepted' }
      await this.commit({ ...this.journal, [key]: { session, turns: { ...prior?.turns, [turn]: result } } })
      this.live.add(key + turn)
      return { accepted: true, session, result }
    })
  }

  finish(owner: TurnOwner, turn: string, result: TerminalTurn) {
    return this.serial(async () => {
      const key = scopedKey(owner, turn)
      const conversation = this.journal[key]
      if (!conversation || !this.live.has(key + turn)) return
      try {
        await this.commit({ ...this.journal, [key]: {
          ...conversation, turns: { ...conversation.turns, [turn]: result },
        } })
      } finally {
        this.live.delete(key + turn)
      }
    })
  }

  private serial<T>(action: () => Promise<T>): Promise<T> {
    const pending = this.queue.then(action)
    this.queue = pending.catch(() => undefined)
    return pending
  }

  private async commit(next: Journal): Promise<void> {
    await mkdir(dirname(this.file), { recursive: true })
    const temp = this.file + '.tmp'
    try {
      const handle = await open(temp, 'w', 0o600)
      try {
        await handle.writeFile(JSON.stringify(next))
        await handle.sync()
      } finally {
        await handle.close()
      }
      await rename(temp, this.file)
      this.journal = next
    } finally {
      await rm(temp, { force: true })
    }
  }
}
