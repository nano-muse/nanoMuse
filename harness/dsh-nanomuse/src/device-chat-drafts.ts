/** Current editor values and ordered writes for persistent device-chat drafts. */
export class DeviceChatDrafts {
  private values: Record<string, string> = {}
  private pending: Promise<unknown> = Promise.resolve()

  constructor(private readonly write: (id: string, text: string) => Promise<unknown>) {}

  hydrate(rows: readonly { id: string; draft?: string }[]): Record<string, string> {
    this.values = { ...Object.fromEntries(rows.map((row) => [row.id, row.draft ?? ''])), ...this.values }
    return { ...this.values }
  }

  get(id: string): string { return this.values[id] ?? '' }

  set(id: string, text: string): Record<string, string> {
    this.values = { ...this.values, [id]: text }
    return { ...this.values }
  }

  clearSent(id: string, sent: string): Record<string, string> | null {
    return this.get(id) === sent ? this.set(id, '') : null
  }

  save(id: string, text: string): Promise<unknown> {
    const saved = this.pending.then(() => this.write(id, text))
    this.pending = saved.catch(() => undefined)
    return saved
  }
}
