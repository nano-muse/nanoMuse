/**
 * The trajectory of a hands run (0.1.40): what the model saw at each step, what it did on
 * it and what it said just before — kept so the chat can show the run again afterwards,
 * the way UI-TARS-desktop's history does, instead of a picture-in-picture while it runs.
 *
 * A *run* is one burst of hands calls in one session: it opens with the first call and
 * closes when the session's turn ends (or when the hands rest for `REST_MS`). A *step* is a
 * frame the model was shown — `computer_screen` returns one, and `computer_act` returns
 * the screen after the action — with the action the model then took on that frame and the
 * words it wrote before acting. The newest step of a running run has no action yet.
 *
 * Kept light: `MAX_STEPS` steps per run (older ones drop off the front; `dropped` counts
 * them), `MAX_RUNS` runs in all (the oldest run goes), and the pictures themselves —
 * JPEGs the runtime already scaled for the model — under `MAX_FRAME_BYTES` together;
 * past that the oldest pictures go first and their steps keep their words (`seq` 0).
 * Nothing is written to disk; a restart forgets it. The browser half reads
 * `GET /trajectory?session=` and `GET /stage/frame?seq=`; `view()` carries no bytes.
 */

/** What the hands did on a frame, as the stage and the trajectory draw it. */
export interface StepAction {
  /** `click`, `double_click`, `right_click`, `middle_click`, `move`, `drag`, `scroll`, `type`, `key`, `open_app`, `wait`, `hand_over`, `look`… */
  kind: string
  /** The words of what was under the cursor, as the model wrote them. */
  label: string
  /** Typed text, the key chord (`ctrl+s`), the app name. */
  text: string
  /** Pixels of the frame the action was aimed at; -1 when it had no point. */
  x: number
  y: number
  /** A drag's far end, in the same pixels; -1 otherwise. */
  x2: number
  y2: number
  /** A scroll's amount in pixels (negative = up); 0 otherwise. */
  dy: number
  at: number
}

export interface TrajectoryStep {
  /** 1-based within the run, counting dropped steps too. */
  i: number
  /** The frame's key (`/stage/frame?seq=`); 0 when its picture is gone or never came. */
  seq: number
  at: number
  width: number
  height: number
  /** What was in front on that screen, as the hands reported it. */
  title: string
  /** What the model did on this frame; null while it has not acted yet. */
  action: StepAction | null
  /** What the model wrote just before this step, trimmed; '' when nothing. */
  words: string
  /** The call that acted on this frame; '' until it does. */
  callId: string
}

export interface TrajectoryRun {
  id: string
  sessionId: string
  source: 'computer' | 'device'
  /** The other device's name; '' for this computer. */
  device: string
  startedAt: number
  /** 0 while the run is on. */
  endedAt: number
  /** The hands calls of the run, first and last: the chat anchors the card under the last one's row. */
  firstCall: string
  lastCall: string
  /** Steps that fell off the front of the run for the cap. */
  dropped: number
  steps: TrajectoryStep[]
}

export interface TrajectoryView {
  /** Moves with every change; the browser half re-reads when it does. */
  rev: number
  runs: TrajectoryRun[]
}

/** Steps kept per run. */
export const MAX_STEPS = 40
/** Runs kept in all. */
export const MAX_RUNS = 4
/** Pictures kept, in bytes, across every run. */
export const MAX_FRAME_BYTES = 64 * 1024 * 1024
/** A hands call this long after the last one starts a new run even without a turn end. */
export const REST_MS = 10 * 60_000
/** How much of what the model said before a step is kept. */
export const MAX_WORDS = 400

interface Frame {
  seq: number
  bytes: Buffer
  mime: string
}

interface FrameMeta {
  sessionId: string
  device?: string | undefined
  width?: number | undefined
  height?: number | undefined
  title?: string | undefined
  /** The call whose result carried the frame; '' when it came another way (Reach). */
  callId?: string | undefined
}

export class Trajectory {
  private runs: TrajectoryRun[] = []
  private readonly frames = new Map<number, Frame>()
  private frameBytes = 0
  private seq = 0
  private rev = 0
  private runSeq = 0
  /** What the model last said in each session, waiting for its next step. */
  private readonly words = new Map<string, string>()
  private lastCallAt = 0

  private readonly now: () => number
  private readonly maxFrameBytes: number

  /** `now` and `maxFrameBytes` are for the tests; the app takes the clock and MAX_FRAME_BYTES. */
  constructor(opts: { now?: () => number; maxFrameBytes?: number } = {}) {
    this.now = opts.now ?? Date.now
    this.maxFrameBytes = opts.maxFrameBytes ?? MAX_FRAME_BYTES
  }

  /** The latest frame's key; 0 before any. */
  get latestSeq(): number {
    return this.seq
  }

  /** The picture behind a step; the newest when `seq` is 0; undefined when it is gone. */
  frameOf(seq: number): Frame | undefined {
    return this.frames.get(seq || this.seq)
  }

  /** The runs, newest last, without bytes; `sessionId` narrows to one session. */
  view(sessionId?: string): TrajectoryView {
    const runs = sessionId ? this.runs.filter((r) => r.sessionId === sessionId) : this.runs
    return { rev: this.rev, runs }
  }

  /** The model's words in a session (an assistant message): kept for the step that follows. */
  said(sessionId: string, text: string): void {
    const trimmed = text.replace(/\s+/g, ' ').trim()
    if (!trimmed) return
    this.words.set(sessionId, trimmed.length > MAX_WORDS ? `${trimmed.slice(0, MAX_WORDS - 1)}…` : trimmed)
  }

  /** A hands call starts in a session: the run it belongs to opens if none is on. */
  began(sessionId: string, callId: string): TrajectoryRun {
    const now = this.now()
    let run = this.openRun(sessionId)
    if (run && now - this.lastCallAt > REST_MS) {
      this.close(run, now)
      run = undefined
    }
    this.lastCallAt = now
    if (!run) {
      this.runSeq += 1
      run = { id: `run-${this.runSeq}`, sessionId, source: 'computer', device: '', startedAt: now, endedAt: 0, firstCall: callId, lastCall: callId, dropped: 0, steps: [] }
      this.runs.push(run)
      while (this.runs.length > MAX_RUNS) this.forget(this.runs.shift()!)
      this.bump()
    } else if (run.lastCall !== callId) {
      run.lastCall = callId
      this.bump()
    }
    return run
  }

  /**
   * The model acts on the frame it was last shown: the action goes on the newest step
   * without one (a step without a frame is made when the model acts before looking).
   */
  acted(sessionId: string, callId: string, action: StepAction): void {
    const run = this.began(sessionId, callId)
    let step = run.steps.length ? run.steps[run.steps.length - 1]! : undefined
    // a look with nothing to look back at (the run's first call) is not a step; its words wait for the next one
    if (action.kind === 'look' && (!step || step.action)) return
    const words = this.words.get(sessionId) ?? ''
    this.words.delete(sessionId)
    if (!step || step.action) {
      step = { i: run.dropped + run.steps.length + 1, seq: 0, at: action.at, width: 0, height: 0, title: step?.title ?? '', action: null, words: '', callId: '' }
      run.steps.push(step)
      this.trim(run)
    }
    step.action = action
    step.words = words
    step.callId = callId
    this.bump()
  }

  /** A frame the model is shown: a new step of the session's run (opened if need be). */
  frame(bytes: Buffer, mime: string, meta: FrameMeta): number {
    this.seq += 1
    const seq = this.seq
    this.frames.set(seq, { seq, bytes, mime })
    this.frameBytes += bytes.length
    const run = this.began(meta.sessionId, meta.callId ?? '')
    if (meta.device) {
      run.source = 'device'
      run.device = meta.device
    }
    run.steps.push({ i: run.dropped + run.steps.length + 1, seq, at: this.now(), width: meta.width ?? 0, height: meta.height ?? 0, title: (meta.title ?? '').slice(0, 120), action: null, words: '', callId: '' })
    this.trim(run)
    this.evict()
    this.bump()
    return seq
  }

  /** The session's turn ended: its run, if on, is over. */
  turnEnded(sessionId: string): void {
    const run = this.openRun(sessionId)
    if (!run) return
    this.close(run, this.now())
    this.words.delete(sessionId)
    this.bump()
  }

  /** Whether a run is on in that session. */
  running(sessionId: string): boolean {
    return this.openRun(sessionId) !== undefined
  }

  /** Everything goes (the person cleared the stage). */
  clear(): void {
    this.runs = []
    this.frames.clear()
    this.frameBytes = 0
    this.words.clear()
    this.bump()
  }

  private openRun(sessionId: string): TrajectoryRun | undefined {
    for (let i = this.runs.length - 1; i >= 0; i -= 1) {
      const run = this.runs[i]!
      if (run.sessionId === sessionId) return run.endedAt === 0 ? run : undefined
    }
    return undefined
  }

  private close(run: TrajectoryRun, at: number): void {
    run.endedAt = at
    // a run that only looked, or never got a frame, is not worth looking back at
    if (run.steps.length === 0 || run.steps.every((s) => !s.action || s.action.kind === 'look')) this.forget(run)
  }

  private forget(run: TrajectoryRun): void {
    this.runs = this.runs.filter((r) => r !== run)
    for (const step of run.steps) this.drop(step.seq)
  }

  private trim(run: TrajectoryRun): void {
    while (run.steps.length > MAX_STEPS) {
      const gone = run.steps.shift()!
      run.dropped += 1
      this.drop(gone.seq)
    }
  }

  private drop(seq: number): void {
    const frame = this.frames.get(seq)
    if (!frame) return
    this.frames.delete(seq)
    this.frameBytes -= frame.bytes.length
  }

  /** Over the byte cap: the oldest pictures go, their steps stay with `seq` 0. */
  private evict(): void {
    if (this.frameBytes <= this.maxFrameBytes) return
    for (const run of this.runs) {
      for (const step of run.steps) {
        if (this.frameBytes <= this.maxFrameBytes) return
        if (step.seq && step.seq !== this.seq && this.frames.has(step.seq)) {
          this.drop(step.seq)
          step.seq = 0
        }
      }
    }
  }

  private bump(): void {
    this.rev += 1
  }
}

/** A run that goes this long without a call closes on its own: the safety net for a turn whose end the host never saw. */
export const SCREEN_RUN_IDLE_MS = 5 * 60_000

/** The hands have this computer's screen: which session, since when. */
export interface ScreenRun {
  sessionId: string
  since: number
}

/**
 * Which sessions have this computer's screen, for the glow round the screen and the
 * capsule the shell draws outside the window. A session's run opens at its first
 * `computer_*` call and closes when its turn ends, so the glow and the capsule stay up
 * while the model thinks between two steps; they used to follow the calls in flight and
 * went dark between every two (1.0.0). Reach calls (`device_*`, `delegate`) and the
 * connectors' tools open nothing: they do not touch this screen. A run that stays quiet
 * for `SCREEN_RUN_IDLE_MS` with no call in flight closes in `sweep`.
 */
export class ScreenRuns {
  private readonly runs = new Map<string, { since: number; lastAt: number }>()

  /** A hands call began: a `computer_*` one opens the session's run or keeps it fresh. True when a run opened. */
  began(sessionId: string, name: string, now = Date.now()): boolean {
    if (!name.startsWith('mcp__nanomuse__computer_')) return false
    const run = this.runs.get(sessionId)
    if (run) {
      run.lastAt = now
      return false
    }
    this.runs.set(sessionId, { since: now, lastAt: now })
    return true
  }

  /** A call of that session ended: its run is fresh as of now. */
  ended(sessionId: string, now = Date.now()): void {
    const run = this.runs.get(sessionId)
    if (run) run.lastAt = now
  }

  /** The session's turn ended (or was stopped): its run closes. True when there was one. */
  turnEnded(sessionId: string): boolean {
    return this.runs.delete(sessionId)
  }

  /** Runs quiet for `SCREEN_RUN_IDLE_MS` with nothing of theirs in flight close. True when any did. */
  sweep(now: number, inFlight: (sessionId: string) => boolean): boolean {
    let changed = false
    for (const [sessionId, run] of this.runs) {
      if (now - run.lastAt >= SCREEN_RUN_IDLE_MS && !inFlight(sessionId)) {
        this.runs.delete(sessionId)
        changed = true
      }
    }
    return changed
  }

  /** The run on now; the newest when several sessions have the screen; null when none has. */
  current(): ScreenRun | null {
    let best: ScreenRun | null = null
    for (const [sessionId, run] of this.runs) {
      if (!best || run.since > best.since) best = { sessionId, since: run.since }
    }
    return best
  }

  get size(): number {
    return this.runs.size
  }
}
