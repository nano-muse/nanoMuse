// The wait for the Host's address (src/main.ts, startHost). dsh prints `dsh web: http://…`
// only once the whole Loader tree has settled: every plugin of the profile imported and
// mounted, ours included. On a fresh Windows install that is 20 000 files under
// resources/dsh/node_modules read for the first time, each one checked by the real-time
// scanner, so the first start can take minutes (issue #217: the address came six seconds
// after the shell had given up at 120 s). The shell therefore does not fail on time alone:
//
//   • up to SLOW_MS the loading page says "Starting";
//   • after SLOW_MS, with the Host still running, it says "Still starting" and shows the
//     Host's last lines (`onSlow`, again on every new line);
//   • after CAP_MS the shell asks the person (`onCap`): keep waiting, or quit, which is the
//     only point where a Host that is alive is stopped, and it is said so;
//   • the Host exiting, or failing to spawn, fails the start at once, as before.
//
// Nothing here touches Electron, so `npm test` can run it with fake timers.

/** After this long without the address the loading page says the start is slow, not failed. */
export const SLOW_MS = 120_000;
/** After this long the shell asks whether to keep waiting; another CAP_MS per "Keep waiting". */
export const CAP_MS = 10 * 60_000;
/** How many of the Host's last lines the loading page and the dialog show. */
export const TAIL_LINES = 8;
/** The line dsh-web-app prints once the web app is served (with the one-time token). */
export const ADDRESS = /dsh web: (http:\/\/127\.0\.0\.1:\d+\/\?token=\S+)/;

export type StartOutcome =
  | { kind: "ready"; url: string }
  | { kind: "exited"; code: number | null; signal: string | null }
  | { kind: "error"; error: Error };

/** What the slow state and the cap dialog show. */
export interface WaitState {
  /** Since the Host was started. */
  waitedMs: number;
  /** Since the Host last wrote a line; equal to waitedMs when it wrote nothing. */
  silentMs: number;
  /** The Host's last lines, stdout and stderr in order, tokens masked. */
  tail: string[];
}

type Timer = unknown;

export interface WatchOptions {
  slowMs?: number;
  capMs?: number;
  /** Fired once at slowMs and on every later line while the start is slow. */
  onSlow?: (state: WaitState) => void;
  /** Fired at capMs and again capMs after each `keepWaiting()`. */
  onCap?: (state: WaitState) => void;
  now?: () => number;
  setTimer?: (fn: () => void, ms: number) => Timer;
  clearTimer?: (timer: Timer) => void;
}

/** A token in a line never reaches the page, the log or the clipboard. */
export function maskToken(line: string): string {
  return line.replace(/token=\S+/g, "token=…");
}

export class HostStartWatch {
  /** Settles once: the address, the Host's exit, or a spawn error. */
  readonly done: Promise<StartOutcome>;
  private settle!: (outcome: StartOutcome) => void;
  private settled = false;
  private out = "";
  private readonly lines: string[] = [];
  private readonly startedAt: number;
  private lastLineAt: number;
  private slow = false;
  private slowTimer: Timer | undefined;
  private capTimer: Timer | undefined;
  private readonly slowMs: number;
  private readonly capMs: number;
  private readonly now: () => number;
  private readonly setTimer: (fn: () => void, ms: number) => Timer;
  private readonly clearTimer: (timer: Timer) => void;

  constructor(private readonly options: WatchOptions = {}) {
    this.slowMs = options.slowMs ?? SLOW_MS;
    this.capMs = options.capMs ?? CAP_MS;
    this.now = options.now ?? (() => Date.now());
    this.setTimer = options.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
    this.clearTimer = options.clearTimer ?? ((timer) => clearTimeout(timer as NodeJS.Timeout));
    this.startedAt = this.now();
    this.lastLineAt = this.startedAt;
    this.done = new Promise<StartOutcome>((resolve) => {
      this.settle = resolve;
    });
    this.slowTimer = this.setTimer(() => {
      this.slowTimer = undefined;
      if (this.settled) return;
      this.slow = true;
      this.options.onSlow?.(this.state());
    }, this.slowMs);
    this.armCap();
  }

  /** Whether the start has passed SLOW_MS without the address. */
  get isSlow(): boolean {
    return this.slow && !this.settled;
  }

  /** How long the shell has waited and what the Host said last. */
  state(): WaitState {
    const now = this.now();
    return { waitedMs: now - this.startedAt, silentMs: now - this.lastLineAt, tail: [...this.lines] };
  }

  /** A chunk of the Host's stdout: the address may arrive split across chunks. */
  stdout(chunk: string): void {
    this.remember(chunk, "");
    if (this.settled) return;
    this.out = (this.out + chunk).slice(-16_384);
    const m = ADDRESS.exec(this.out);
    if (m && m[1]) this.finish({ kind: "ready", url: m[1] });
  }

  /** A chunk of the Host's stderr; shown in the tail marked with `! `. */
  stderr(chunk: string): void {
    this.remember(chunk, "! ");
  }

  exited(code: number | null, signal: string | null): void {
    this.finish({ kind: "exited", code, signal });
  }

  error(error: Error): void {
    this.finish({ kind: "error", error });
  }

  /** The person chose to keep waiting at the cap: the next question comes capMs from now. */
  keepWaiting(): void {
    if (this.settled) return;
    this.armCap();
  }

  /** Stop the timers without settling (the app is quitting with the Host still starting). */
  dispose(): void {
    if (this.slowTimer !== undefined) this.clearTimer(this.slowTimer);
    if (this.capTimer !== undefined) this.clearTimer(this.capTimer);
    this.slowTimer = undefined;
    this.capTimer = undefined;
  }

  private armCap(): void {
    if (this.capTimer !== undefined) this.clearTimer(this.capTimer);
    this.capTimer = this.setTimer(() => {
      this.capTimer = undefined;
      if (this.settled) return;
      this.options.onCap?.(this.state());
    }, this.capMs);
  }

  private remember(chunk: string, prefix: string): void {
    const lines = chunk.split("\n").filter((line) => line.trim());
    if (!lines.length) return;
    this.lastLineAt = this.now();
    for (const line of lines) this.lines.push(prefix + maskToken(line.trim()).slice(0, 300));
    if (this.lines.length > TAIL_LINES) this.lines.splice(0, this.lines.length - TAIL_LINES);
    if (this.slow && !this.settled) this.options.onSlow?.(this.state());
  }

  private finish(outcome: StartOutcome): void {
    if (this.settled) return;
    this.settled = true;
    this.dispose();
    this.settle(outcome);
  }
}

/** `2 min`, `10 min`, `45 s`: the wait, for a sentence. */
export function waitedText(ms: number, zh: boolean): string {
  const minutes = Math.floor(ms / 60_000);
  if (minutes >= 1) return zh ? `${minutes} 分钟` : `${minutes} min`;
  return zh ? `${Math.floor(ms / 1000)} 秒` : `${Math.floor(ms / 1000)} s`;
}
