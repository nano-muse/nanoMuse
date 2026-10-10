// Portions derived from UI-TARS-desktop (https://github.com/bytedance/UI-TARS-desktop),
// © 2025 Bytedance, Inc. and its affiliates, Apache-2.0: `NutJSOperator` and
// `NutJSElectronOperator` (the screenshot through desktopCapturer at the display's size, the
// action switch with moveStraightTo + sleep(100) + click, the hotkey map, the clipboard paste
// for typing), `getScreenSize` (logical × scaleFactor, 1 on macOS) and the marker shapes of
// `setOfMarks` (the point, the action's name beside it).
import { clipboard, desktopCapturer, nativeImage, screen as electronScreen } from "electron";
import type * as Nut from "@computer-use/nut-js";
import { describeAction, HELPER_NAME, HELPER_SCREEN_PERMISSION_TEXT, MacHelperError, type HelperWindow, type HelperWindowShot, type MacHelper } from "./mac-helper";

/**
 * The hands of nanoMuse Desktop: the mouse, the keyboard and the screenshot, done by this
 * process (Electron) rather than by the Python runtime it starts. Why here: the app bundle is
 * what macOS grants Accessibility and Screen Recording to, Electron knows the display's real
 * geometry, and UI-TARS-desktop has run this very operator on many desks already. The
 * runtime reaches it over loopback (operator-server.ts) and keeps the brain — the agent loop,
 * the Sentinel, the tools.
 *
 * Coordinates: everything in and out of here is in the *operator's screen pixels* — the space
 * libnut moves the pointer in. On Linux (X11) that is the root window's pixels, on Windows
 * physical pixels (the process is DPI-aware), on macOS points — which is why the scale factor
 * is taken as 1 there, as UI-TARS does. The screenshot is the primary display at exactly that
 * size (or scaled to the size the runtime asks for), so a pixel of the picture is a pixel the
 * pointer can be sent to; the runtime does the picture ↔ screen arithmetic.
 */

export interface ScreenSpace {
  /** The primary display's id (desktopCapturer's `display_id` is its string). */
  id: number;
  /** The operator's screen pixels: logical × scaleFactor (× 1 on macOS). */
  width: number;
  height: number;
  scaleFactor: number;
  logical: { width: number; height: number };
  /** The display's place in Electron's logical coordinates. */
  bounds: { x: number; y: number; width: number; height: number };
  /** The display's top-left in the operator's pixels (0,0 for the usual primary display). */
  originX: number;
  originY: number;
}

export interface OperatorInfo {
  available: boolean;
  reason: string;
  platform: NodeJS.Platform;
  display: { width: number; height: number; scaleFactor: number; logical: { width: number; height: number } };
  /**
   * macOS only: whether "nanoMuse Computer Use" is doing the capture and the input, or why
   * not. `present` is the bundle being there at all (the runtime's window mode lists and
   * captures windows through `/windows` and `/window` when it is); `capture` is the helper's
   * source ("ScreenCaptureKit" on macOS 14+).
   */
  helper?: { present: boolean; running: boolean; pid?: number; version?: string; capture?: string; reason: string };
}

export interface ScreenshotRequest {
  width?: number;
  height?: number;
  format?: "png" | "jpeg";
  quality?: number;
  /**
   * Without an explicit size: the most pixels the picture may have (aspect kept); 0 = the
   * screen's own size. Default DEFAULT_MAX_PIXELS — a 4K screen is 8 Mpx, and a model
   * request with a few of those in it passed the relay's body cap (413).
   */
  max_pixels?: number;
}

/** 2 Mpx (the shared brief's budget rule): 4K comes down to half its side, 1080p (2.07 Mpx) is trimmed a little, 1680×1050 and below pass untouched. */
export const DEFAULT_MAX_PIXELS = 2_000_000;

/** The picture's size for a `width`×`height` screen under `maxPixels` (0 = no cap); whole pixels, aspect kept. */
export function fitPixels(width: number, height: number, maxPixels: number): { width: number; height: number } {
  if (!(maxPixels > 0) || width * height <= maxPixels || width <= 0 || height <= 0) return { width, height };
  const k = Math.sqrt(maxPixels / (width * height));
  return { width: Math.max(1, Math.floor(width * k)), height: Math.max(1, Math.floor(height * k)) };
}

export interface Screenshot {
  base64: string;
  mime: "image/png" | "image/jpeg";
  /** The picture's size (the requested one, or the screen's). */
  width: number;
  height: number;
  /** The operator's screen pixels the picture stands for. */
  screen: { width: number; height: number };
  scaleFactor: number;
  display: { id: string; bounds: ScreenSpace["bounds"] };
}

export interface OperatorAction {
  action: string;
  x?: number;
  y?: number;
  x2?: number;
  y2?: number;
  dy?: number;
  text?: string;
  submit?: boolean;
  clear?: boolean;
  keys?: string[];
  seconds?: number;
}

/** What the overlay hears of each action: the point as fractions of the display, the words. */
export interface Marker {
  /** -1 when the action had no point (typing, a key). */
  fx: number;
  fy: number;
  /** For a drag: where it ended. */
  fx2?: number;
  fy2?: number;
  kind: string;
  text: string;
}

export interface OperatorOptions {
  /**
   * Each executed action, for the glow's marker — before the pointer moves. A promise is
   * awaited: on X11 the glow that comes up for the marker needs a moment to become
   * click-through again (main.ts), and a click that lands on the glow lands nowhere.
   */
  onAction?: (marker: Marker) => void | Promise<void>;
  /** After each executed action, done or failed: on Linux the glow that stepped aside for the pointer comes back (main.ts). */
  onActed?: () => void | Promise<void>;
  /** Around the capture: `before` hides what must not be in the picture, `after` shows it again. */
  onCapture?: (phase: "before" | "after") => void | Promise<void>;
  /** macOS: the permissions the hands need, as the app's own probes see them. */
  permissions?: () => { accessibility: boolean; screen: boolean };
  /**
   * macOS: "nanoMuse Computer Use", the helper app that holds the grants and does the capture
   * and the input (mac-helper.ts). When its bundle is there, every screenshot and action goes
   * through it — or fails with the helper's own reason (it did not start, its capture failed);
   * nothing falls through to desktopCapturer or libnut behind its back. Only without a bundle
   * at all (a build without it, another platform) do the paths below run.
   */
  helper?: MacHelper;
  log?: (line: string) => void;
}

export class OperatorError extends Error {
  constructor(
    message: string,
    readonly status = 400,
  ) {
    super(message);
    this.name = "OperatorError";
  }
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** What a Mac without Screen Recording is told — the one text, from `/info` and from a refused `/screenshot` alike. */
export const SCREEN_PERMISSION_TEXT = "macOS: switch on nanoMuse Desktop under System Settings → Privacy & Security → Screen Recording, then quit and reopen the app.";
/** A channel below this in every sampled pixel means a black picture (macOS without the permission). */
const BLACK_LEVEL = 8;

/** What a Wayland session is told, from `/info`, a refused `/screenshot` and a refused `/execute` alike (the runtime passes it on). */
export const WAYLAND_TEXT = "Wayland session: no global screen or cursor for a program to drive. Log in with Xorg (the session chooser on the login screen), or run the hands on another computer of the account.";

/**
 * Linux: whether this is a Wayland session. `XDG_SESSION_TYPE` is what the login manager
 * sets; a `WAYLAND_DISPLAY` without a `DISPLAY` is the same thing said by a compositor
 * started by hand. XWayland (both set, session type wayland) counts as Wayland: X11 input
 * reaches X windows only, and a grab of the X root shows none of the native windows.
 */
export function isWaylandSession(env: NodeJS.ProcessEnv = process.env): boolean {
  if ((env.XDG_SESSION_TYPE || "").toLowerCase() === "wayland") return true;
  return Boolean(env.WAYLAND_DISPLAY) && !env.DISPLAY;
}

/**
 * Whether a picture is black all over — what macOS hands a process without Screen Recording
 * (desktopCapturer's thumbnail, or libnut's grab, of the wallpaper-less void). Samples a grid
 * of the bitmap (about 4,096 points) rather than every pixel; true when no channel of any
 * sample reaches BLACK_LEVEL. An empty image counts as black.
 */
export function isBlackImage(image: Electron.NativeImage): boolean {
  const { width, height } = image.getSize();
  if (width <= 0 || height <= 0) return true;
  const bitmap = image.toBitmap(); // BGRA, 4 bytes a pixel
  if (bitmap.length < width * height * 4) return bitmap.length === 0;
  const step = Math.max(1, Math.floor(Math.sqrt((width * height) / 4096)));
  for (let y = 0; y < height; y += step) {
    for (let x = 0; x < width; x += step) {
      const i = (y * width + x) * 4;
      if ((bitmap[i] ?? 0) >= BLACK_LEVEL || (bitmap[i + 1] ?? 0) >= BLACK_LEVEL || (bitmap[i + 2] ?? 0) >= BLACK_LEVEL) return false;
    }
  }
  return true;
}

export class Operator {
  private nut: typeof Nut | null = null;
  private loadError = "";
  private loaded = false;
  private lastMarker: { fx: number; fy: number } | null = null;
  private busy: Promise<unknown> = Promise.resolve();

  constructor(private readonly options: OperatorOptions = {}) {}

  private log(line: string): void {
    this.options.log?.(`operator: ${line}`);
  }

  /** libnut is native: a build that cannot load it has no hands, not a crash. */
  private load(): typeof Nut | null {
    if (this.loaded) return this.nut;
    this.loaded = true;
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      this.nut = require("@computer-use/nut-js") as typeof Nut;
      this.nut.mouse.config.mouseSpeed = 3600;
      this.nut.mouse.config.autoDelayMs = 50;
      this.nut.keyboard.config.autoDelayMs = 20;
    } catch (exc) {
      this.loadError = String((exc as Error).message ?? exc);
      this.log(`nut.js did not load: ${this.loadError}`);
      this.nut = null;
    }
    return this.nut;
  }

  /** The primary display in the operator's pixels (UI-TARS's getScreenSize). */
  screenSpace(): ScreenSpace {
    const display = electronScreen.getPrimaryDisplay();
    const logical = display.size;
    // macOS: libnut moves in points, which is what Electron calls logical pixels there
    const scaleFactor = process.platform === "darwin" ? 1 : display.scaleFactor || 1;
    return {
      id: display.id,
      width: Math.round(logical.width * scaleFactor),
      height: Math.round(logical.height * scaleFactor),
      scaleFactor,
      logical: { width: logical.width, height: logical.height },
      bounds: { ...display.bounds },
      originX: Math.round(display.bounds.x * scaleFactor),
      originY: Math.round(display.bounds.y * scaleFactor),
    };
  }

  availability(): { available: boolean; reason: string } {
    if (process.platform === "linux" && isWaylandSession()) return { available: false, reason: WAYLAND_TEXT };
    // macOS with a helper bundle that was tried and did not start: that is the reason, not the
    // app's own grants (which nobody switched on — the panes name the helper)
    if (process.platform === "darwin" && this.options.helper?.present() && this.options.helper.failedToStart() && !this.options.helper.busy()) {
      return { available: false, reason: `${HELPER_NAME} did not start (${this.options.helper.failure()})` };
    }
    if (process.platform === "darwin" && this.options.permissions) {
      const p = this.options.permissions();
      const missing = [...(p.accessibility ? [] : ["Accessibility"]), ...(p.screen ? [] : ["Screen Recording"])];
      if (missing.length) {
        // with the helper the switch to flip is its row, and no app restart is involved
        const helper = this.options.helper?.running() === true;
        return {
          available: false,
          reason: p.accessibility
            ? helper
              ? HELPER_SCREEN_PERMISSION_TEXT
              : SCREEN_PERMISSION_TEXT
            : `macOS: switch on ${helper ? "nanoMuse Computer Use" : "nanoMuse Desktop"} under System Settings → Privacy & Security → ${missing.join(" and ")}${p.screen || helper ? "" : ", then quit and reopen the app"}.`,
        };
      }
    }
    // macOS with the helper running: it does the capture and the input, libnut is not needed
    if (process.platform === "darwin" && this.options.helper?.running()) return { available: true, reason: "" };
    if (!this.load()) return { available: false, reason: `the operator's native module did not load: ${this.loadError}` };
    return { available: true, reason: "" };
  }

  info(): OperatorInfo {
    const space = this.screenSpace();
    const helper = this.options.helper;
    const helperStatus = helper?.cachedStatus();
    return {
      ...this.availability(),
      platform: process.platform,
      display: { width: space.width, height: space.height, scaleFactor: space.scaleFactor, logical: space.logical },
      ...(process.platform === "darwin" && helper ? { helper: { present: helper.present(), running: helper.running(), ...(helperStatus?.pid !== undefined ? { pid: helperStatus.pid } : {}), ...(helperStatus?.version ? { version: helperStatus.version } : {}), ...(helperStatus?.capture ? { capture: helperStatus.capture } : {}), reason: helper.failure() } } : {}),
    };
  }

  /** The primary display, scaled to the requested size (the picture the model sees). */
  async screenshot(req: ScreenshotRequest = {}): Promise<Screenshot> {
    // Linux under Wayland: desktopCapturer would open the portal's screen picker — a system
    // dialog the person did not ask for — so the picture is refused with the same reason
    // /info gives, and the runtime says plainly that the hands are off here.
    if (process.platform === "linux" && isWaylandSession()) throw new OperatorError(`no screenshot: ${this.availability().reason}`, 503);
    const space = this.screenSpace();
    const maxPixels = isNum(req.max_pixels) ? Math.max(0, Math.round(req.max_pixels)) : DEFAULT_MAX_PIXELS;
    const want = isNum(req.width) && isNum(req.height) && req.width > 0 && req.height > 0 ? { width: Math.round(req.width), height: Math.round(req.height) } : fitPixels(space.width, space.height, maxPixels);
    const format = req.format === "png" ? "png" : "jpeg";
    const quality = isNum(req.quality) ? Math.max(30, Math.min(100, Math.round(req.quality))) : 80;
    // macOS with the helper bundle: its picture, already at the asked size and format
    // (mac-helper.ts) — or its reason, never desktopCapturer's picture in its place
    if (process.platform === "darwin" && this.options.helper?.present()) {
      if (!(await this.options.helper.ready())) throw new OperatorError(`no screenshot: ${HELPER_NAME} did not start (${this.options.helper.failure()})`, 503);
      return this.helperScreenshot(space, want, format, quality);
    }
    await this.options.onCapture?.("before");
    let image: Electron.NativeImage;
    try {
      image = await this.capture(space);
    } finally {
      await this.options.onCapture?.("after");
    }
    const size = image.getSize();
    if (size.width !== want.width || size.height !== want.height) image = image.resize({ width: want.width, height: want.height, quality: "best" });
    const buffer = format === "png" ? image.toPNG() : image.toJPEG(quality);
    return {
      base64: buffer.toString("base64"),
      mime: format === "png" ? "image/png" : "image/jpeg",
      width: want.width,
      height: want.height,
      screen: { width: space.width, height: space.height },
      scaleFactor: space.scaleFactor,
      display: { id: String(space.id), bounds: space.bounds },
    };
  }

  /**
   * The helper's screenshot, shaped like ours. Its 403 (Screen Recording off for the helper)
   * comes through with the helper's text, since the helper's row is the switch to flip and
   * the helper restarts by itself. Anything else — ScreenCaptureKit refused (`userDeclined`,
   * `noDisplayList`…), no image, the helper died or timed out — is logged and thrown with the
   * helper's own words, so the runtime's `computer_screen` says exactly what went wrong.
   * Until 0.1.39 this fell through to desktopCapturer, whose black or stale frame then
   * reached the model as if it were the screen, and nobody saw the real error.
   */
  private async helperScreenshot(space: ScreenSpace, want: { width: number; height: number }, format: "png" | "jpeg", quality: number): Promise<Screenshot> {
    const helper = this.options.helper;
    if (!helper) throw new OperatorError("no screenshot: no helper", 500);
    try {
      const shot = await helper.screenshot({ width: want.width, height: want.height, format, quality });
      if (typeof shot.base64 !== "string" || !shot.base64) throw new MacHelperError("the helper's picture is empty", 500, "empty");
      return {
        base64: shot.base64,
        mime: shot.mime === "image/png" ? "image/png" : "image/jpeg",
        width: isNum(shot.width) ? shot.width : want.width,
        height: isNum(shot.height) ? shot.height : want.height,
        screen: { width: space.width, height: space.height },
        scaleFactor: space.scaleFactor,
        display: { id: String(space.id), bounds: space.bounds },
      };
    } catch (exc) {
      if (exc instanceof MacHelperError && exc.status === 403) throw new OperatorError(`no screenshot: ${HELPER_SCREEN_PERMISSION_TEXT}`, 403);
      // the helper's own text already opens with "no screenshot:"; said once
      const why = String((exc as Error).message ?? exc).replace(/^no screenshot:\s*/, "");
      this.log(`helper screenshot failed (${why}) — not falling back to desktopCapturer`);
      // 503 when the helper itself is gone (the next call starts it again), 500 when it answered that the capture failed
      throw new OperatorError(`no screenshot: ${HELPER_NAME} could not take the picture: ${why}`, exc instanceof MacHelperError && exc.code === "not_running" ? 503 : 500);
    }
  }

  /**
   * The windows on screen, for the runtime's window mode — through the helper, whose grant
   * the listing needs (titles come only with Screen Recording). Off macOS, or without the
   * helper bundle, there is no window mode and the call says so (503).
   */
  async windows(): Promise<HelperWindow[]> {
    const helper = await this.helperForWindows("the windows on screen cannot be listed");
    try {
      return await helper.windows();
    } catch (exc) {
      throw this.windowError(exc, "the windows on screen could not be listed");
    }
  }

  /** One window's own pixels and its frame, through the helper (`POST /window`). */
  async windowShot(req: { id: number; max_pixels?: number; format?: "png" | "jpeg"; quality?: number }): Promise<HelperWindowShot> {
    if (!isNum(req.id) || req.id <= 0) throw new OperatorError("`id` must be a window id from /windows");
    const helper = await this.helperForWindows("a window cannot be captured");
    try {
      const shot = await helper.window({ id: Math.round(req.id), ...(isNum(req.max_pixels) ? { max_pixels: Math.max(0, Math.round(req.max_pixels)) } : {}), ...(req.format === "jpeg" ? { format: "jpeg" as const } : { format: "png" as const }), ...(isNum(req.quality) ? { quality: Math.max(30, Math.min(100, Math.round(req.quality))) } : {}) });
      if (typeof shot.base64 !== "string" || !shot.base64) throw new MacHelperError("the helper's picture is empty", 500, "empty");
      return shot;
    } catch (exc) {
      throw this.windowError(exc, `window ${req.id} could not be captured`);
    }
  }

  private async helperForWindows(what: string): Promise<MacHelper> {
    const helper = this.options.helper;
    if (process.platform !== "darwin" || !helper?.present()) throw new OperatorError(`${what}: window mode needs ${HELPER_NAME}, which this build does not have`, 503);
    if (!(await helper.ready())) throw new OperatorError(`${what}: ${HELPER_NAME} did not start (${helper.failure()})`, 503);
    return helper;
  }

  private windowError(exc: unknown, what: string): OperatorError {
    if (exc instanceof OperatorError) return exc;
    if (exc instanceof MacHelperError) {
      if (exc.status === 403) return new OperatorError(`${what}: ${HELPER_SCREEN_PERMISSION_TEXT}`, 403);
      if (exc.status === 404) return new OperatorError(`${what}: ${exc.message}`, 404);
      this.log(`helper window capture failed (${exc.message})`);
      return new OperatorError(`${what}: ${HELPER_NAME}: ${exc.message}`, exc.code === "not_running" ? 503 : exc.status);
    }
    return new OperatorError(`${what}: ${String((exc as Error).message ?? exc)}`, 500);
  }

  /**
   * The picture of the primary display through Electron — Linux, Windows, and a macOS build
   * without the helper bundle (never a Mac whose helper is there: `screenshot` above throws
   * the helper's reason instead). On macOS a process without Screen Recording gets no
   * picture, only a black one — and it gets it two ways: Electron ≥ 32 rejects
   * `getSources` outright (`TryPromptUserForScreenCapture` → `HandleFailure`), and libnut's
   * grab comes back all black. Either is answered with 403 and the permission text, never
   * with the black picture — one error, in the words the Computer-use page uses, instead of
   * a model told to act on a black screen.
   */
  private async capture(space: ScreenSpace): Promise<Electron.NativeImage> {
    const mac = process.platform === "darwin";
    try {
      const sources = await desktopCapturer.getSources({ types: ["screen"], thumbnailSize: { width: space.width, height: space.height } });
      const primary = sources.find((s) => s.display_id === String(space.id)) ?? sources[0];
      if (primary && !primary.thumbnail.isEmpty()) {
        if (mac && isBlackImage(primary.thumbnail)) throw new OperatorError(`no screenshot: the picture is black. ${SCREEN_PERMISSION_TEXT}`, 403);
        return primary.thumbnail;
      }
      this.log(`desktopCapturer: no picture of display ${space.id} (${sources.length} sources)`);
    } catch (exc) {
      if (exc instanceof OperatorError) throw exc;
      this.log(`desktopCapturer failed: ${String(exc)}`);
      if (mac) throw new OperatorError(`no screenshot: ${SCREEN_PERMISSION_TEXT}`, 403);
    }
    // the fallback UI-TARS's nut operator uses: libnut's own grab, scaled to the screen space
    const nut = this.load();
    if (!nut) throw new OperatorError(`no screenshot: ${this.loadError}`, 500);
    const grabbed = await nut.screen.grab();
    if (grabbed.channels !== 4) throw new OperatorError(`no screenshot: libnut returned ${grabbed.channels}-channel pixels`, 500);
    const bitmap = nativeImage.createFromBitmap(Buffer.from(grabbed.data), { width: grabbed.width, height: grabbed.height });
    if (bitmap.isEmpty()) throw new OperatorError("no screenshot: the capture came back empty", 500);
    if (mac && isBlackImage(bitmap)) throw new OperatorError(`no screenshot: the picture is black. ${SCREEN_PERMISSION_TEXT}`, 403);
    return bitmap;
  }

  /** One action, in the operator's pixels. Actions run one after another. */
  execute(action: OperatorAction): Promise<{ ok: true; note: string }> {
    const run = this.busy.then(() => this.run(action));
    const acted = run.then(
      () => this.options.onActed?.(),
      () => this.options.onActed?.(),
    );
    this.busy = acted.catch(() => undefined);
    return run;
  }

  private async run(action: OperatorAction): Promise<{ ok: true; note: string }> {
    // macOS with the helper bundle: CGEvent in the helper's process; this one clamps and marks
    // (mac-helper.ts). A helper that did not start is the reason, not a libnut move in its place.
    if (process.platform === "darwin" && this.options.helper?.present()) {
      if (!(await this.options.helper.ready())) throw new OperatorError(`the hands are not available: ${HELPER_NAME} did not start (${this.options.helper.failure()})`, 503);
      return this.runWithHelper(this.options.helper, action);
    }
    const nut = this.load();
    if (!nut) throw new OperatorError(`the hands are not available: ${this.loadError}`, 503);
    const { mouse, keyboard, Button, Key, Point, straightTo } = nut;
    const space = this.screenSpace();
    const kind = String(action.action ?? "");
    const point = (kx: "x" | "x2", ky: "y" | "y2"): { x: number; y: number } | null => {
      const x = action[kx];
      const y = action[ky];
      if (!isNum(x) || !isNum(y)) return null;
      // one pixel past the edge means the edge
      return {
        x: Math.round(Math.max(space.originX, Math.min(space.originX + space.width - 1, x))),
        y: Math.round(Math.max(space.originY, Math.min(space.originY + space.height - 1, y))),
      };
    };
    const start = point("x", "y");
    const end = point("x2", "y2");
    const moveStraightTo = async (p: { x: number; y: number } | null) => {
      if (!p) return;
      await mouse.move(straightTo(new Point(p.x, p.y)));
    };
    const needsPoint = () => {
      if (!start) throw new OperatorError(`${kind} needs x and y`);
      return start;
    };
    const fraction = (p: { x: number; y: number } | null) => (p ? { fx: Math.min(1, Math.max(0, (p.x - space.originX) / space.width)), fy: Math.min(1, Math.max(0, (p.y - space.originY) / space.height)) } : null);
    // the marker goes out before the pointer moves and is awaited: on X11 the glow steps
    // aside for a pointer action and must be click-through for any other (main.ts, glow.ts)
    const mark = async (text: string, p: { x: number; y: number } | null = start, p2: { x: number; y: number } | null = null) => {
      const f = fraction(p) ?? this.lastMarker ?? { fx: -1, fy: -1 };
      if (fraction(p)) this.lastMarker = f;
      const f2 = fraction(p2);
      await this.options.onAction?.({ ...f, ...(f2 ? { fx2: f2.fx, fy2: f2.fy } : {}), kind, text });
    };
    this.log(`${kind}${start ? ` at ${start.x},${start.y}` : ""}${end ? ` → ${end.x},${end.y}` : ""}`);
    // the names are UI-TARS-desktop's (its nut-js operator), plus the runtime's dialect
    switch (kind) {
      case "move":
      case "mouse_move":
      case "hover":
        await mark("move", needsPoint());
        await moveStraightTo(start);
        break;
      case "click":
      case "left_click":
      case "left_single": {
        await mark("click", needsPoint());
        await moveStraightTo(start);
        await sleep(100);
        await mouse.click(Button.LEFT);
        break;
      }
      case "double_click":
      case "left_double": {
        await mark("double click", needsPoint());
        await moveStraightTo(start);
        await sleep(100);
        await mouse.doubleClick(Button.LEFT);
        break;
      }
      case "right_click":
      case "right_single": {
        await mark("right click", needsPoint());
        await moveStraightTo(start);
        await sleep(100);
        await mouse.click(Button.RIGHT);
        break;
      }
      case "middle_click": {
        await mark("middle click", needsPoint());
        await moveStraightTo(start);
        await sleep(100);
        await mouse.click(Button.MIDDLE);
        break;
      }
      case "drag":
      case "left_click_drag":
      case "select": {
        needsPoint();
        if (!end) throw new OperatorError("drag needs x2 and y2");
        await mark("drag", start, end);
        await moveStraightTo(start);
        await sleep(100);
        await mouse.drag(straightTo(new Point(end.x, end.y)));
        break;
      }
      case "scroll": {
        // `dy` in screen pixels, positive = down (the runtime's dialect). libnut's unit is a
        // wheel click on X11 and Windows (×120, one notch) and a pixel on macOS.
        const dy = isNum(action.dy) ? action.dy : 300;
        const clicks = Math.max(1, Math.min(30, Math.round(Math.abs(dy) / 40) || 1));
        const amount = process.platform === "darwin" ? Math.min(3000, Math.max(1, Math.round(Math.abs(dy)))) : process.platform === "win32" ? clicks * 120 : clicks;
        await mark(dy >= 0 ? "scroll down" : "scroll up", start);
        if (start) await moveStraightTo(start);
        if (dy >= 0) await mouse.scrollDown(amount);
        else await mouse.scrollUp(amount);
        break;
      }
      case "type": {
        const raw = String(action.text ?? "");
        if (!raw) throw new OperatorError("type needs text");
        const submit = action.submit === true || /\\n$|\n$/.test(raw);
        const text = raw.replace(/\\n$/, "").replace(/\n$/, "");
        await mark(`typing “${text.length > 40 ? `${text.slice(0, 40)}…` : text}”`, null);
        if (action.clear === true) {
          await keyboard.pressKey(this.commandKey(Key), Key.A);
          await keyboard.releaseKey(this.commandKey(Key), Key.A);
          await sleep(50);
        }
        if (text) await this.typeText(nut, text);
        if (submit) {
          await keyboard.pressKey(Key.Enter);
          await keyboard.releaseKey(Key.Enter);
        }
        break;
      }
      case "key":
      case "hotkey": {
        const names = Array.isArray(action.keys) ? action.keys.map((k) => String(k)) : [];
        if (!names.length) throw new OperatorError("key needs keys");
        const keys = this.hotkeys(Key, names);
        await mark(`keys ${names.join(" + ")}`, null);
        await keyboard.pressKey(...keys);
        await keyboard.releaseKey(...keys);
        break;
      }
      // UI-TARS's press / release: a key held down across other actions (shift-click, a game)
      case "press":
      case "release": {
        const names = Array.isArray(action.keys) ? action.keys.map((k) => String(k)) : [];
        if (!names.length) throw new OperatorError(`${kind} needs keys`);
        const keys = this.hotkeys(Key, names);
        await mark(`${kind === "press" ? "holding" : "releasing"} ${names.join(" + ")}`, null);
        if (kind === "press") await keyboard.pressKey(...keys);
        else await keyboard.releaseKey(...keys);
        break;
      }
      case "wait": {
        const seconds = isNum(action.seconds) ? Math.max(0.2, Math.min(10, action.seconds)) : 1;
        await mark(`waiting ${seconds} s`, null);
        await sleep(seconds * 1000);
        break;
      }
      default:
        throw new OperatorError(`unknown action '${kind}'`);
    }
    return { ok: true, note: "" };
  }

  /**
   * One action through "nanoMuse Computer Use": the same clamping to the display and the
   * same marker for the glow as the libnut path, then the action as it came, with the
   * clamped points, to the helper's `/execute`. Its refusals come back as the operator's
   * errors (400 for a bad action, 403 without Accessibility, 503 when it is gone).
   */
  private async runWithHelper(helper: MacHelper, action: OperatorAction): Promise<{ ok: true; note: string }> {
    const space = this.screenSpace();
    // the UI-TARS aliases the X11/Windows route takes, in the names the helper knows
    const HELPER_ALIASES: Record<string, string> = { mouse_move: "move", left_single: "click", select: "drag" };
    const kind = HELPER_ALIASES[String(action.action ?? "")] ?? String(action.action ?? "");
    const point = (kx: "x" | "x2", ky: "y" | "y2"): { x: number; y: number } | null => {
      const x = action[kx];
      const y = action[ky];
      if (!isNum(x) || !isNum(y)) return null;
      return {
        x: Math.round(Math.max(space.originX, Math.min(space.originX + space.width - 1, x))),
        y: Math.round(Math.max(space.originY, Math.min(space.originY + space.height - 1, y))),
      };
    };
    const start = point("x", "y");
    const end = point("x2", "y2");
    const pointed = new Set(["move", "hover", "click", "left_click", "double_click", "left_double", "right_click", "right_single", "middle_click", "drag", "left_click_drag"]);
    if (pointed.has(kind) && !start) throw new OperatorError(`${kind} needs x and y`);
    // press / release (a key held across the actions that follow): the helper keeps it down until released
    if ((kind === "press" || kind === "release") && !(Array.isArray(action.keys) && action.keys.length)) throw new OperatorError(`${kind} needs keys`);
    if ((kind === "drag" || kind === "left_click_drag") && !end) throw new OperatorError("drag needs x2 and y2");
    if ((kind === "type" && !String(action.text ?? "")) || ((kind === "key" || kind === "hotkey") && !(Array.isArray(action.keys) && action.keys.length))) throw new OperatorError(kind === "type" ? "type needs text" : "key needs keys");
    const fraction = (p: { x: number; y: number } | null) => (p ? { fx: Math.min(1, Math.max(0, (p.x - space.originX) / space.width)), fy: Math.min(1, Math.max(0, (p.y - space.originY) / space.height)) } : null);
    const f = fraction(start) ?? this.lastMarker ?? { fx: -1, fy: -1 };
    if (fraction(start)) this.lastMarker = f;
    const f2 = fraction(end);
    this.options.onAction?.({ ...f, ...(f2 ? { fx2: f2.fx, fy2: f2.fy } : {}), kind, text: describeAction({ action: kind, dy: action.dy, text: action.text, keys: action.keys, seconds: action.seconds }) });
    this.log(`${kind}${start ? ` at ${start.x},${start.y}` : ""}${end ? ` → ${end.x},${end.y}` : ""} (helper)`);
    try {
      return await helper.execute({ ...action, action: kind, ...(start ? { x: start.x, y: start.y } : {}), ...(end ? { x2: end.x, y2: end.y } : {}) });
    } catch (exc) {
      if (exc instanceof MacHelperError) throw new OperatorError(exc.status === 403 ? `macOS: switch on nanoMuse Computer Use under System Settings → Privacy & Security → Accessibility.` : exc.message, exc.status === 403 ? 403 : exc.status >= 500 ? 503 : exc.status);
      throw exc;
    }
  }

  private commandKey(Key: typeof Nut.Key): Nut.Key {
    return process.platform === "darwin" ? Key.LeftCmd : Key.LeftControl;
  }

  /**
   * Typing: key codes have no 中文, so anything beyond ASCII goes through the clipboard and a
   * paste (UI-TARS does this on Windows for all text; here on every platform for text that
   * needs it), with the person's clipboard put back afterwards.
   */
  private async typeText(nut: typeof Nut, text: string): Promise<void> {
    const { keyboard, Key } = nut;
    // eslint-disable-next-line no-control-regex
    const ascii = /^[\x20-\x7e\t]*$/.test(text);
    if (ascii && process.platform !== "win32") {
      keyboard.config.autoDelayMs = 0;
      try {
        if (process.platform === "linux") await this.typeAsciiX11(nut, text);
        else await keyboard.type(text);
      } finally {
        keyboard.config.autoDelayMs = 20;
      }
      return;
    }
    const previous = await clipboard.readText().catch(() => "");
    await clipboard.writeText(text);
    await sleep(30);
    await keyboard.pressKey(this.commandKey(Key), Key.V);
    await sleep(50);
    await keyboard.releaseKey(this.commandKey(Key), Key.V);
    await sleep(120);
    await clipboard.writeText(previous).catch(() => undefined);
  }

  /**
   * ASCII on X11. libnut's `type` finds the key for a character but forgets Shift for the
   * symbols that need it — `*` came out as `8`, `!` as `1`, `_` as `-`, `"` as `'` (letters
   * are fine, it handles their case itself). So the shifted symbols of the US layout, which
   * is the layout libnut maps characters by, go as Shift + the key under them; everything
   * else in runs through `type`. Tab and the rest of the row are keys of their own.
   */
  private async typeAsciiX11(nut: typeof Nut, text: string): Promise<void> {
    const { keyboard, Key } = nut;
    const shifted: Record<string, Nut.Key> = {
      "~": Key.Grave,
      "!": Key.Num1,
      "@": Key.Num2,
      "#": Key.Num3,
      $: Key.Num4,
      "%": Key.Num5,
      "^": Key.Num6,
      "&": Key.Num7,
      "*": Key.Num8,
      "(": Key.Num9,
      ")": Key.Num0,
      _: Key.Minus,
      "+": Key.Equal,
      "{": Key.LeftBracket,
      "}": Key.RightBracket,
      "|": Key.Backslash,
      ":": Key.Semicolon,
      '"': Key.Quote,
      "<": Key.Comma,
      ">": Key.Period,
      "?": Key.Slash,
    };
    let run = "";
    const flush = async () => {
      if (run) await keyboard.type(run);
      run = "";
    };
    for (const ch of text) {
      const key = shifted[ch];
      if (key === undefined && ch !== "\t") {
        run += ch;
        continue;
      }
      await flush();
      if (ch === "\t") {
        await keyboard.pressKey(Key.Tab);
        await keyboard.releaseKey(Key.Tab);
        continue;
      }
      await keyboard.pressKey(Key.LeftShift, key as Nut.Key);
      await keyboard.releaseKey(Key.LeftShift, key as Nut.Key);
    }
    await flush();
  }

  /** The runtime's key names (`ctrl`, `command`, `enter`, `a`, `f5`, `page_down` …) → libnut keys. */
  private hotkeys(Key: typeof Nut.Key, names: string[]): Nut.Key[] {
    const command = this.commandKey(Key);
    // UI-TARS's map: `ctrl` is ⌘ on a Mac, where the model's ctrl+c means copy
    const table: Record<string, Nut.Key> = {
      return: Key.Enter,
      enter: Key.Enter,
      ctrl: command,
      control: Key.LeftControl,
      shift: Key.LeftShift,
      alt: Key.LeftAlt,
      option: Key.LeftAlt,
      meta: command,
      win: command,
      super: command,
      command: command,
      cmd: command,
      esc: Key.Escape,
      escape: Key.Escape,
      del: Key.Delete,
      delete: Key.Delete,
      backspace: Key.Backspace,
      tab: Key.Tab,
      space: Key.Space,
      "page down": Key.PageDown,
      pagedown: Key.PageDown,
      page_down: Key.PageDown,
      "page up": Key.PageUp,
      pageup: Key.PageUp,
      page_up: Key.PageUp,
      arrowup: Key.Up,
      arrowdown: Key.Down,
      arrowleft: Key.Left,
      arrowright: Key.Right,
      capslock: Key.CapsLock,
      printscreen: Key.Print,
      ",": Key.Comma,
      ".": Key.Period,
      "/": Key.Slash,
      ";": Key.Semicolon,
      "'": Key.Quote,
      "-": Key.Minus,
      "=": Key.Equal,
      "[": Key.LeftBracket,
      "]": Key.RightBracket,
      "\\": Key.Backslash,
      "`": Key.Grave,
    };
    const lowercase = Object.fromEntries(Object.entries(Key).filter(([, v]) => typeof v === "number").map(([k, v]) => [k.toLowerCase(), v as Nut.Key])) as Record<string, Nut.Key>;
    return names.map((raw) => {
      const name = raw.trim().toLowerCase();
      const key = table[name] ?? (/^[0-9]$/.test(name) ? lowercase[`num${name}`] : undefined) ?? lowercase[name];
      if (key === undefined) throw new OperatorError(`unknown key '${raw}'`);
      return key;
    });
  }
}
