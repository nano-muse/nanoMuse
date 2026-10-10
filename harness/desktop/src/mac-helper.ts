import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

/**
 * The client of "nanoMuse Computer Use.app" (mac/computer-use/), the small native app that
 * holds the hands' two macOS permissions and does the capture and the input.
 *
 * Why a separate app: macOS attributes a TCC request to the *responsible process* — the
 * process LaunchServices started, with everything it spawned. A child process of the Electron
 * app is the app, as far as the Screen Recording and Accessibility panes are concerned; an
 * app bundle launched through `open` (LaunchServices → launchd) is responsible for itself
 * and has its own row, named for what it does. (Qt's "The Curious Case of the Responsible
 * Process", qt.io/blog, walks through the attribution and the `open` route; the private
 * `responsibility_spawnattrs_setdisclaim` spawn attribute LLDB and Chromium use is the other
 * way, and Node cannot set it — so: `open`, never `spawn` of the binary.) Codex's "Codex
 * Computer Use.app" is the same arrangement.
 *
 * What that buys: the panes list *nanoMuse Computer Use*, granted and revoked on its own;
 * Screen Recording — which reaches freshly started processes only — takes effect after the
 * helper restarts, not the whole app; the picture comes from ScreenCaptureKit on macOS 14+
 * (CGDisplayCreateImage before — on macOS 26/27 that call returns nil even with the grant,
 * which was 0.1.39's "no screenshot: noImage") and the input from CGEvent, not from
 * Chromium's desktopCapturer and libnut (the black and absent screenshots of 0.1.36 were the
 * Chromium path). When the helper is there and its picture fails, the operator reports the
 * helper's own error and never falls back to desktopCapturer (operator.ts).
 *
 * One thing has to happen before the first launch of an installed copy: the quarantine flag
 * the download left on the helper comes off (`clearQuarantine`), or LaunchServices starts
 * the helper from a translocated copy whose path changes every time — which is why 0.1.38's
 * helper ran, held Accessibility and never appeared in the Screen Recording pane.
 *
 * Protocol (one JSON object each way, a bearer token the shell writes to a 0600 file before
 * the launch, the port written back by the helper):
 *
 *   GET  /status      → { screen: "granted"|"denied"|"unknown", screen_detail, capture, accessibility, pid, version, display }
 *   POST /request     { what: "screen"|"accessibility", pane? }   → the status afterwards
 *   POST /screenshot  { width?, height?, max_pixels?, format?, quality? } → { base64, mime, width, height, screen, scale }
 *   GET  /windows     → { windows: [{ id, pid, app, bundle_id, title, bounds, layer, on_screen }] }
 *   POST /window      { id, max_pixels?, format?, quality? }      → { base64, mime, width, height, window: { id, x, y, width, height }, scale }
 *   POST /execute     { action, … }                                → { ok: true, note }
 *   POST /quit        → { ok: true }
 *
 * Nothing here needs Electron: main.ts passes the paths in, and tests run it under Node.
 */

export const HELPER_NAME = "nanoMuse Computer Use";
export const HELPER_BUNDLE_ID = "io.github.nanomuse.desktop.computer-use";
/** The permission text when the helper is the one that needs the switch (no app restart involved). */
export const HELPER_SCREEN_PERMISSION_TEXT = "macOS: switch on nanoMuse Computer Use under System Settings → Privacy & Security → Screen Recording. The helper restarts by itself; the app does not need to.";

export type HelperScreenState = "granted" | "denied" | "unknown";

export interface HelperStatus {
  screen: HelperScreenState;
  /** Why the screen is `unknown` or `denied` beyond the preflight (ScreenCaptureKit's words), "" otherwise. */
  screenDetail?: string;
  /** What takes the picture in this helper: "ScreenCaptureKit" (macOS 14+) or "CoreGraphics". */
  capture?: string;
  accessibility: boolean;
  pid?: number;
  version?: string;
  display?: { width: number; height: number; scale: number };
}

/** One window on screen as the helper lists it (`GET /windows`); the runtime's window mode reads this shape. */
export interface HelperWindow {
  id: number;
  pid: number;
  app: string;
  bundle_id: string;
  title: string;
  /** Points, top-left origin: x, y, width, height. */
  bounds: [number, number, number, number];
  layer: number;
  on_screen: boolean;
}

export interface HelperWindowRequest {
  id: number;
  max_pixels?: number;
  format?: "png" | "jpeg";
  quality?: number;
}

export interface HelperWindowShot {
  base64: string;
  mime: "image/png" | "image/jpeg";
  width: number;
  height: number;
  /** The window's frame in points, so a pixel of the picture maps to a point on the screen. */
  window: { id: number; x: number; y: number; width: number; height: number };
  scale: number;
}

export interface HelperScreenshotRequest {
  width?: number;
  height?: number;
  max_pixels?: number;
  format?: "png" | "jpeg";
  quality?: number;
}

export interface HelperScreenshot {
  base64: string;
  mime: "image/png" | "image/jpeg";
  width: number;
  height: number;
  screen: { width: number; height: number };
  scale: number;
}

export interface MacHelperOptions {
  /** The .app bundle; undefined or missing → the helper is off and every call falls back. */
  appPath: string | undefined;
  /** Where the token and port files live (made 0700). */
  dataDir: string;
  log?: (line: string) => void;
  /** The launch; the default is `open -n -g -a <app> --args …`. Tests put a fake here. */
  launch?: (appPath: string, args: string[]) => Promise<void>;
  /** The quarantine check before a launch (default `clearQuarantine`). Tests put a fake here. */
  quarantine?: (appPath: string) => QuarantineOutcome;
  /** How long to wait for the port file (default 10 s). */
  startTimeoutMs?: number;
  /** How long after a failed start before another is tried (default 30 s). */
  retryAfterMs?: number;
  fetch?: typeof fetch;
}

/** What became of `com.apple.quarantine` on the helper bundle before a launch (`clearQuarantine`). */
export interface QuarantineOutcome {
  /** `none`: the bundle carried no flag; `removed`: it did, and does not now; `kept`: it does, and could not be changed. */
  result: "none" | "removed" | "kept";
  /** For `kept`: the first line of what `xattr` said. */
  detail: string;
}

/** The text of a flag that could not be removed — the one case where the person has to act. */
export const QUARANTINE_KEPT_TEXT = "the helper bundle carries macOS's quarantine flag and it could not be removed; move nanoMuse to the Applications folder and open it again";

/** A path under Gatekeeper's App Translocation: a read-only copy with a random name, different on every launch. */
export function translocated(path: string): boolean {
  return path.includes("/AppTranslocation/");
}

/**
 * The quarantine flag on the helper, removed before the first launch — from the helper alone.
 *
 * An app copied out of a downloaded disk image carries `com.apple.quarantine` on every file,
 * the helper included. The person settles the app's own flag by opening it (Gatekeeper's
 * dialog, *Open Anyway*); nothing settles the helper's, which LaunchServices starts as a
 * bundle of its own. Quarantined and unapproved, it starts from a translocated copy
 * (`/private/var/folders/…/AppTranslocation/<random>/d/…`): a path that is different each
 * launch, which is how the 0.1.38 helper could run, hold Accessibility and still have no row
 * in the Screen Recording pane — and on a fresh install Gatekeeper's own dialog comes up for
 * the helper too, with the port file never written. `xattr -dr` on the bundle takes the flag
 * off (the bundle is the person's copy in Applications, writable); a flag that stays — the app
 * run from the disk image or from Downloads, a read-only install — is reported, and the
 * caller says what to do.
 */
export function clearQuarantine(appPath: string, run: typeof spawnSync = spawnSync, platform: NodeJS.Platform = process.platform): QuarantineOutcome {
  if (platform !== "darwin") return { result: "none", detail: "" };
  const flagged = () => {
    const probe = run("xattr", ["-p", "com.apple.quarantine", appPath], { encoding: "utf8" });
    return !probe.error && probe.status === 0;
  };
  if (!flagged()) return { result: "none", detail: "" };
  const strip = run("xattr", ["-dr", "com.apple.quarantine", appPath], { encoding: "utf8" });
  if (!flagged()) return { result: "removed", detail: "" };
  const said = (strip.error?.message ?? strip.stderr ?? "").toString().trim().split("\n")[0] ?? "";
  return { result: "kept", detail: said };
}

export class MacHelperError extends Error {
  constructor(
    message: string,
    readonly status = 500,
    readonly code = "",
  ) {
    super(message);
    this.name = "MacHelperError";
  }
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** `open -n -g -a <app> --args …`: LaunchServices starts it, so TCC attributes it to the helper, not to us. */
function openApp(appPath: string, args: string[]): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn("open", ["-n", "-g", "-a", appPath, "--args", ...args], { stdio: "ignore" });
    child.once("error", reject);
    child.once("exit", (code) => (code === 0 ? resolve() : reject(new Error(`open exited with ${code}`))));
  });
}

/**
 * Where the helper bundle is: `NANOMUSE_COMPUTER_USE_APP` when set; inside the packaged app at
 * Contents/Helpers; in development, what mac/computer-use/build.sh built.
 */
export function defaultHelperPath(execPath: string, packaged: boolean, projectDir: string, env: NodeJS.ProcessEnv = process.env): string {
  if (env.NANOMUSE_COMPUTER_USE_APP) return env.NANOMUSE_COMPUTER_USE_APP;
  if (packaged) return join(execPath, "..", "..", "Helpers", `${HELPER_NAME}.app`);
  return join(projectDir, "mac", "computer-use", "build", `${HELPER_NAME}.app`);
}

/** The glow's words for an action the helper carries out (the operator's own wording, operator.ts). */
export function describeAction(action: { action: string; dy?: number; text?: string; keys?: string[]; seconds?: number }): string {
  switch (action.action) {
    case "move":
    case "hover":
      return "move";
    case "click":
    case "left_click":
      return "click";
    case "double_click":
    case "left_double":
      return "double click";
    case "right_click":
    case "right_single":
      return "right click";
    case "middle_click":
      return "middle click";
    case "drag":
    case "left_click_drag":
      return "drag";
    case "scroll":
      return (typeof action.dy === "number" ? action.dy : 300) >= 0 ? "scroll down" : "scroll up";
    case "type": {
      const text = String(action.text ?? "").replace(/\\n$/, "").replace(/\n$/, "");
      return `typing “${text.length > 40 ? `${text.slice(0, 40)}…` : text}”`;
    }
    case "key":
    case "hotkey":
      return `keys ${(Array.isArray(action.keys) ? action.keys : []).map(String).join(" + ")}`;
    case "wait": {
      const seconds = typeof action.seconds === "number" && Number.isFinite(action.seconds) ? Math.max(0.2, Math.min(10, action.seconds)) : 1;
      return `waiting ${seconds} s`;
    }
    default:
      return action.action;
  }
}

export class MacHelper {
  private base: string | null = null;
  private token = "";
  private starting: Promise<boolean> | null = null;
  private restarting: Promise<boolean> | null = null;
  private lastStatus: HelperStatus | null = null;
  /** The last status of any process of the helper, kept across a restart (see `lastKnownStatus`). */
  private knownStatus: HelperStatus | null = null;
  private lastFailure = "";
  private lastFailureAt = 0;
  private statusTimer: NodeJS.Timeout | null = null;

  constructor(private readonly options: MacHelperOptions) {}

  private log(line: string): void {
    this.options.log?.(`helper: ${line}`);
  }

  /** Whether there is a bundle to launch at all. */
  present(): boolean {
    return Boolean(this.options.appPath && existsSync(this.options.appPath));
  }

  /** Started and answering as of the last call. */
  running(): boolean {
    return this.base !== null;
  }

  /**
   * Between two processes: a start or a restart under way. Readers that would otherwise take
   * "not running" for "the helper is not in use" (and name the app's own rows, or restart the
   * whole app) wait this out instead.
   */
  busy(): boolean {
    return this.starting !== null || this.restarting !== null;
  }

  /** Why the helper is not in use ("" when it is). */
  failure(): string {
    return this.base ? "" : this.lastFailure || (this.present() ? "not started" : "no helper bundle");
  }

  /** A start was tried and failed, and nothing has succeeded since (the operator refuses with `failure()` meanwhile). */
  failedToStart(): boolean {
    return this.base === null && this.lastFailureAt > 0;
  }

  /** The last `/status` the helper gave (for callers that cannot wait); null before the first. */
  cachedStatus(): HelperStatus | null {
    return this.base ? this.lastStatus : null;
  }

  /** The last status any process of the helper gave, restart or not; null before the first ever. */
  lastKnownStatus(): HelperStatus | null {
    return this.knownStatus;
  }

  /**
   * Running, or started now. False when there is no bundle, or when it failed to start — in
   * which case the next try waits `retryAfterMs`, so a broken helper does not stall every
   * screenshot. With a bundle present the operator refuses on false, with `failure()` as the
   * reason; only without a bundle at all does it use the Electron path.
   */
  ready(): Promise<boolean> {
    if (this.base) return Promise.resolve(true);
    if (this.starting) return this.starting;
    if (!this.present()) return Promise.resolve(false);
    if (this.lastFailureAt && Date.now() - this.lastFailureAt < (this.options.retryAfterMs ?? 30_000)) return Promise.resolve(false);
    this.starting = this.start().finally(() => {
      this.starting = null;
    });
    return this.starting;
  }

  private async start(): Promise<boolean> {
    const appPath = this.options.appPath;
    if (!appPath || !existsSync(appPath)) return false;
    const dir = this.options.dataDir;
    const tokenFile = join(dir, "token");
    const portFile = join(dir, "port");
    try {
      // the app itself under App Translocation: the helper inside it is read-only and
      // quarantined too, and would start translocated in turn — grants to a path that changes
      // every launch are no grants; better the plain reason than a helper that half works
      if (translocated(appPath)) throw new Error("nanoMuse is running from a temporary copy macOS made of it (App Translocation); move it to the Applications folder and open it again");
      const quarantine = (this.options.quarantine ?? clearQuarantine)(appPath);
      if (quarantine.result === "removed") this.log("removed the quarantine flag from the bundled helper, so macOS starts it in place and the privacy panes list it");
      else if (quarantine.result === "kept") throw new Error(`${QUARANTINE_KEPT_TEXT}${quarantine.detail ? ` (${quarantine.detail})` : ""}`);
      mkdirSync(dir, { recursive: true, mode: 0o700 });
      await this.quitStale(portFile, tokenFile);
      rmSync(portFile, { force: true });
      const token = randomBytes(24).toString("hex");
      writeFileSync(tokenFile, token, { mode: 0o600 });
      const launch = this.options.launch ?? openApp;
      await launch(appPath, ["--token-file", tokenFile, "--port-file", portFile, "--parent-pid", String(process.pid)]);
      const deadline = Date.now() + (this.options.startTimeoutMs ?? 10_000);
      let port = 0;
      while (Date.now() < deadline) {
        port = this.readPort(portFile);
        if (port) break;
        await sleep(100);
      }
      if (!port) throw new Error(`no port after ${Math.round((this.options.startTimeoutMs ?? 10_000) / 1000)} s`);
      this.base = `http://127.0.0.1:${port}`;
      this.token = token;
      // the token file stays (0600, in the app's own data dir) until stop(): a shell that
      // dies without /quit leaves it for the next launch's quitStale()
      const status = await this.status();
      this.log(`${HELPER_NAME} ${status.version ?? "?"} (pid ${status.pid ?? "?"}) at ${this.base} — screen ${status.screen}${status.screenDetail ? ` (${status.screenDetail})` : ""}, accessibility ${status.accessibility}, capture ${status.capture ?? "?"}`);
      this.lastFailure = "";
      this.lastFailureAt = 0;
      this.watchStatus();
      return true;
    } catch (exc) {
      this.base = null;
      this.token = "";
      this.lastStatus = null;
      this.lastFailure = String((exc as Error).message ?? exc);
      this.lastFailureAt = Date.now();
      this.log(`${HELPER_NAME} did not start (${this.lastFailure}) — screenshots and actions are refused with this reason until it does`);
      return false;
    }
  }

  private readPort(portFile: string): number {
    if (!existsSync(portFile)) return 0;
    try {
      const parsed = JSON.parse(readFileSync(portFile, "utf8")) as { port?: unknown };
      return typeof parsed.port === "number" && parsed.port > 0 ? parsed.port : 0;
    } catch {
      return 0;
    }
  }

  /** A helper left from a shell that died without `/quit`: ask it to go, if its token is still around. */
  private async quitStale(portFile: string, tokenFile: string): Promise<void> {
    const port = this.readPort(portFile);
    if (!port || !existsSync(tokenFile)) return;
    try {
      const token = readFileSync(tokenFile, "utf8").trim();
      const doFetch = this.options.fetch ?? fetch;
      await doFetch(`http://127.0.0.1:${port}/quit`, { method: "POST", headers: { authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(1500) });
      await sleep(300);
    } catch {
      /* gone already, or someone else's port */
    }
  }

  /** The status every 2 s while running, so the synchronous readers see a grant flip within a moment. */
  private watchStatus(): void {
    if (this.statusTimer) clearInterval(this.statusTimer);
    this.statusTimer = setInterval(() => {
      if (!this.base) {
        if (this.statusTimer) clearInterval(this.statusTimer);
        this.statusTimer = null;
        return;
      }
      void this.status().catch(() => undefined);
    }, 2000);
    this.statusTimer.unref?.();
  }

  private async call<T>(method: "GET" | "POST", path: string, body?: unknown, timeoutMs = 15_000): Promise<T> {
    if (!this.base) throw new MacHelperError("the helper is not running", 503, "not_running");
    const doFetch = this.options.fetch ?? fetch;
    let res: Response;
    try {
      res = await doFetch(this.base + path, {
        method,
        headers: { authorization: `Bearer ${this.token}`, "content-type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (exc) {
      // refused or timed out: the process is gone (or hung); the next ready() starts it again
      this.log(`${method} ${path}: ${String((exc as Error).message ?? exc)} — treating the helper as gone`);
      this.base = null;
      this.token = "";
      this.lastStatus = null;
      throw new MacHelperError("the helper is not answering", 503, "not_running");
    }
    const json = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    if (!res.ok) throw new MacHelperError(String(json.message ?? json.error ?? `HTTP ${res.status}`), res.status, String(json.error ?? ""));
    return json as T;
  }

  async status(): Promise<HelperStatus> {
    const raw = await this.call<Record<string, unknown>>("GET", "/status");
    const screen = raw.screen === "granted" || raw.screen === "denied" ? raw.screen : "unknown";
    const display = raw.display && typeof raw.display === "object" ? (raw.display as HelperStatus["display"]) : undefined;
    const status: HelperStatus = {
      screen,
      ...(typeof raw.screen_detail === "string" && raw.screen_detail ? { screenDetail: raw.screen_detail } : {}),
      ...(typeof raw.capture === "string" ? { capture: raw.capture } : {}),
      accessibility: raw.accessibility === true,
      ...(typeof raw.pid === "number" ? { pid: raw.pid } : {}),
      ...(typeof raw.version === "string" ? { version: raw.version } : {}),
      ...(display ? { display } : {}),
    };
    this.lastStatus = status;
    this.knownStatus = status;
    return status;
  }

  /** The system's dialog for one permission (and the pane, when asked); the status afterwards. */
  async request(what: "screen" | "accessibility", pane = false): Promise<HelperStatus> {
    const raw = await this.call<Record<string, unknown>>("POST", "/request", { what, pane });
    const screen = raw.screen === "granted" || raw.screen === "denied" ? raw.screen : "unknown";
    const status: HelperStatus = { screen, accessibility: raw.accessibility === true };
    this.lastStatus = { ...(this.lastStatus ?? {}), ...status };
    this.knownStatus = this.lastStatus;
    return status;
  }

  screenshot(req: HelperScreenshotRequest = {}): Promise<HelperScreenshot> {
    return this.call<HelperScreenshot>("POST", "/screenshot", req, 20_000);
  }

  /** The windows on screen, front to back (for the runtime's window mode). */
  async windows(): Promise<HelperWindow[]> {
    const raw = await this.call<{ windows?: unknown }>("GET", "/windows", undefined, 20_000);
    return Array.isArray(raw.windows) ? (raw.windows as HelperWindow[]) : [];
  }

  /** One window's own pixels and its frame (`POST /window`); 404 `no_window` when it is gone. */
  window(req: HelperWindowRequest): Promise<HelperWindowShot> {
    return this.call<HelperWindowShot>("POST", "/window", req, 20_000);
  }

  execute(action: Record<string, unknown> & { action: string }): Promise<{ ok: true; note: string }> {
    return this.call<{ ok: true; note: string }>("POST", "/execute", action, 30_000);
  }

  /**
   * `/quit`, then a fresh launch: what a Screen Recording grant needs (it reaches new processes
   * only). Two restarts asked for at once are one — the second caller gets the first's promise.
   * In 0.1.38 a second click on the restart button landed while the helper was between
   * processes, read as "not in use", and relaunched the whole app twice.
   */
  restart(): Promise<boolean> {
    if (this.restarting) return this.restarting;
    this.restarting = (async () => {
      this.log("restarting");
      await this.stop();
      this.lastFailureAt = 0;
      return this.ready();
    })().finally(() => {
      this.restarting = null;
    });
    return this.restarting;
  }

  /** `/quit`; quiet when it is already gone. */
  async stop(): Promise<void> {
    if (this.statusTimer) clearInterval(this.statusTimer);
    this.statusTimer = null;
    if (!this.base) return;
    try {
      await this.call("POST", "/quit", undefined, 2000);
    } catch {
      /* already gone */
    }
    this.base = null;
    this.token = "";
    this.lastStatus = null;
    rmSync(join(this.options.dataDir, "port"), { force: true });
    rmSync(join(this.options.dataDir, "token"), { force: true });
  }
}
