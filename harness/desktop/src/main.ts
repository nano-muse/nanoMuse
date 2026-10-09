import { pathToFileURL } from "node:url";
import { app, BrowserWindow, clipboard, desktopCapturer, dialog, globalShortcut, ipcMain, Menu, nativeImage, nativeTheme, powerSaveBlocker, screen, shell, systemPreferences, Tray } from "electron";
import { randomBytes } from "node:crypto";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { homedir } from "node:os";
import { join } from "node:path";
import { GLOW_HIDE_MS, GLOW_SETTLE_MS, type Leak, LeakLog, leakIsEvidence, leakIsReal, pointerAction, REARM_DELAYS_MS, staleInstance } from "./glow";
import { defaultHelperPath, HELPER_NAME, MacHelper } from "./mac-helper";
import * as macPermissions from "./mac-permissions";
import { Operator, SCREEN_PERMISSION_TEXT, type Marker } from "./operator";
import { startOperatorServer, type OperatorServer } from "./operator-server";
import { EXTERNAL_URL, navigationVerdict, sameOrigin } from "./navigation";
import { relink } from "./profile-link";
import { maskProxyUrl, proxyEnv, validProxyUrl } from "./proxy";
import { HostStartWatch, maskToken, waitedText, type WaitState } from "./host-start";

/**
 * nanoMuse Desktop — the nanoMuse desktop, built on DeepSeek Harness.
 *
 * The window shows the harness's own web app, served by a dsh Host this shell starts as a
 * child process: the Electron binary in Node mode (`ELECTRON_RUN_AS_NODE`, as the harness's
 * own desktop does), running the `dsh` that ships under `resources/dsh` with the nanoMuse
 * bundle (`harness/dsh-nanomuse`) installed next to it. The profile the Host boots lives
 * under `~/.nanomuse/desktop` and names the bundle; nothing is installed at first run and
 * no Node or pnpm is needed on the machine. When the runtime for the hands is bundled
 * (`resources/runtime`, the PyInstaller build the other desktop app carries too), the
 * preset's `nanomuse mcp` points at it, so the hands work out of the box.
 *
 * What the shell adds is small on purpose: a loading page with the face, the Host's URL
 * loaded once it is ready, external links in the browser, a menu with About and the
 * places to report a problem, and a clear dialog — with the log's tail on the clipboard —
 * when the Host does not come up. Everything else is the harness's and the bundle's
 * (docs/desktop.md, docs/harness.md).
 */

const PROFILE = "nanomuse";
// The composition: the harness's base and Web app, its Schedule (the goals' automations and
// the agent's reminders — an optional bundle of the harness, on by default here), then ours.
const BUNDLES = ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app", "@deepseek-ai/dsh-experimental-schedule-bundle", "dsh-nanomuse"];
const BUNDLE = "dsh-nanomuse";
const RELEASES_PAGE = "https://github.com/nano-muse/nanoMuse/releases/latest";
const ISSUES_PAGE = "https://github.com/nano-muse/nanoMuse/issues";
const DOCS_PAGE = "https://nanomuse.cn/docs/desktop";
const HARNESS_PAGE = "https://github.com/deepseek-ai/deepseek-harness";

const zh = (app.getLocale() || "").toLowerCase().startsWith("zh");
const T = {
  starting: zh ? "正在启动…" : "Starting…",
  notReady: zh ? "nanoMuse 没能启动" : "nanoMuse could not start",
  stopped: zh ? "nanoMuse 的后台停止了" : "nanoMuse's host stopped",
  stillStarting: zh ? "nanoMuse 还在启动" : "nanoMuse is still starting",
  stillStartingDetail: (waited: string) =>
    zh
      ? `后台已经启动了 ${waited}，进程还在运行。装好之后的第一次启动可能要好几分钟：系统会把应用的每个文件检查一遍（Windows 上是实时防护在扫描），磁盘慢的话更久；之后再启动就快了。可以继续等，也可以退出（退出会停掉还在启动的后台）。`
      : `The host has been starting for ${waited} and its process is still running. The first start after an install can take several minutes: the system checks each of the app's files once (on Windows that is the real-time scanner), and a slow disk adds to it; later starts are quicker. Keep waiting, or quit (quitting stops the host that is still starting).`,
  keepWaiting: zh ? "继续等" : "Keep waiting",
  restart: zh ? "重新启动" : "Restart",
  quit: zh ? "退出" : "Quit",
  copyDetails: zh ? "复制详情" : "Copy details",
  copied: zh ? "已复制。到 GitHub 发一个 issue 时贴上即可。" : "Copied. Paste it into a GitHub issue.",
  openLogFolder: zh ? "打开日志文件夹" : "Open the log folder",
  reportHint: zh ? "「复制详情」会把这段话和日志末尾复制下来，发 issue 时贴上：" : "Copy details puts this and the end of the log on the clipboard for an issue at",
  about: zh ? "关于 nanoMuse" : "About nanoMuse",
  website: zh ? "nanoMuse 官网" : "nanoMuse website",
  docs: zh ? "这个桌面版的说明" : "About this desktop",
  issue: zh ? "报告问题" : "Report an issue",
  builtOn: zh ? "基于 DeepSeek Harness（MIT）" : "Built on DeepSeek Harness (MIT)",
  releases: zh ? "下载页（检查新版本）" : "Downloads (check for a newer version)",
  reload: zh ? "重新加载" : "Reload",
  devtools: zh ? "开发者工具" : "Developer tools",
  view: zh ? "视图" : "View",
  window: zh ? "窗口" : "Window",
  help: zh ? "帮助" : "Help",
  edit: zh ? "编辑" : "Edit",
  open: zh ? "打开 nanoMuse" : "Open nanoMuse",
  newChat: zh ? "新聊天" : "New chat",
  quickChat: zh ? "快速唤起" : "Quick chat",
};

/** dev flag: `--screenshot=/tmp/x.png` writes the window once the web app is up, then quits (a headless check) */
const screenshotFlag = process.argv.find((a) => a.startsWith("--screenshot="))?.slice("--screenshot=".length);
/**
 * check flag: `--operator-check=/tmp/x.json` starts the operator alone (no host, no window),
 * asks it over its own HTTP for /info and a small /screenshot — and, with `--operator-move`,
 * moves the pointer to the display's centre — writes the answers to the file and quits. What
 * scripts/smoke.mjs runs against a packaged build to see that libnut loaded there.
 */
const operatorCheckFlag = process.argv.find((a) => a.startsWith("--operator-check="))?.slice("--operator-check=".length);

if (process.platform === "darwin") {
  // electron/electron#44504: since 29.1 Chromium takes desktopCapturer's thumbnails through
  // ScreenCaptureKit on macOS, and that path drops frames non-deterministically (an empty or
  // stale picture for the hands). These features off, the thumbnails come from CGWindowList
  // as before — the same switch UI-TARS-desktop and the issue's workaround use. Before ready.
  app.commandLine.appendSwitch("disable-features", "ThumbnailCapturerMac:capture_mode/sc_screenshot_manager,ScreenCaptureKitPickerScreen,ScreenCaptureKitStreamPickerSonoma");
}

const logs: string[] = [];
let hostStderr = "";
let child: ChildProcess | null = null;
let mainWindow: BrowserWindow | null = null;
let hostUrl: string | null = null;
let quitting = false;
let restarts = 0;
/** The proxy the running Host was started with ("" for none): the Network row offers a restart while it differs from the setting. */
let hostProxy = "";

/**
 * `~/.nanomuse/desktop`, the harness home of this app alone — the CLI's `~/.dsh` is left alone.
 * `NANOMUSE_DESKTOP_HOME` moves it (`NANOMUSE_HARNESS_HOME`, the 0.1.28–0.1.29 name, still
 * counts). A home the app kept as nanoMuse Harness under `~/.nanomuse/harness` is taken over
 * once, so the account and the chats of those two versions carry on.
 */
let resolvedHome: string | undefined;
function harnessHome(): string {
  if (resolvedHome) return resolvedHome;
  const fromEnv = process.env.NANOMUSE_DESKTOP_HOME || process.env.NANOMUSE_HARNESS_HOME;
  if (fromEnv) return (resolvedHome = fromEnv);
  const home = join(homedir(), ".nanomuse", "desktop");
  const previous = join(homedir(), ".nanomuse", "harness");
  if (!existsSync(home) && existsSync(join(previous, "profiles"))) {
    try {
      renameSync(previous, home);
    } catch {
      return (resolvedHome = previous);
    }
  }
  return (resolvedHome = home);
}

/** Where dsh/ and runtime/ are: next to app.asar when packaged, the project dir in development. */
function resourcesDir(): string {
  return app.isPackaged ? process.resourcesPath : join(__dirname, "..");
}

/** The app's own files (icons, the loading page): inside app.asar when packaged. */
function ownResources(): string {
  return join(app.getAppPath(), "resources");
}

function log(line: string): void {
  const stamped = `${new Date().toISOString().slice(11, 19)} ${line}`;
  logs.push(stamped);
  if (logs.length > 200) logs.shift();
  console.log(`[nanomuse-desktop] ${line}`);
  try {
    mkdirSync(harnessHome(), { recursive: true });
    appendFileSync(join(harnessHome(), "desktop.log"), `${stamped}\n`);
  } catch {
    /* the line is still in memory for the dialog */
  }
}

type Shipped = { dsh?: string; bundle?: string; platform?: string; arch?: string };

/** What scripts/prepare-dsh.mjs wrote next to the staged dsh: the versions for About. */
function shipped(): Shipped {
  try {
    return JSON.parse(readFileSync(join(resourcesDir(), "dsh", "dsh.json"), "utf8")) as Shipped;
  } catch {
    return {};
  }
}

/** The bundled runtime's executable (`nanomuse mcp` serves the hands), when it was built in. */
function bundledRuntime(): string | undefined {
  const exe = join(resourcesDir(), "runtime", process.platform === "win32" ? "nanomuse.exe" : "nanomuse");
  return existsSync(exe) ? exe : undefined;
}

/**
 * The profile the Host boots: `~/.nanomuse/desktop/profiles/nanomuse`. Three small files the
 * harness reads (the manifest with the bundle list, the empty root, the person's own patch
 * layer, which dsh writes settings into) and one link: `node_modules/dsh-nanomuse` → the copy
 * under resources, which is how the Loader finds a bundle that is not among the harness's own
 * packages. The link is refreshed every start, so moving the app or updating it is enough.
 */
function ensureProfile(dshDir: string): string {
  const dir = join(harnessHome(), "profiles", PROFILE);
  mkdirSync(join(dir, "node_modules"), { recursive: true });
  const manifestPath = join(dir, "package.json");
  let manifest: Record<string, unknown> = {};
  if (existsSync(manifestPath)) {
    try {
      manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, unknown>;
    } catch (exc) {
      log(`profile manifest unreadable, rewriting: ${String(exc)}`);
    }
  }
  const deps = (manifest.dependencies as Record<string, string> | undefined) ?? {};
  const dsh = (manifest.dsh as { profile?: { bundles?: string[] } } | undefined) ?? {};
  const bundles = dsh.profile?.bundles ?? [];
  const same = bundles.length === BUNDLES.length && bundles.every((b, i) => b === BUNDLES[i]);
  if (!same || deps[BUNDLE] !== "*" || manifest.name !== `dsh-profile-${PROFILE}`) {
    const next = {
      ...manifest,
      name: `dsh-profile-${PROFILE}`,
      private: true,
      dependencies: { ...deps, [BUNDLE]: "*" },
      dsh: { ...dsh, profile: { ...dsh.profile, bundles: [...BUNDLES] } },
    };
    writeFileSync(manifestPath, `${JSON.stringify(next, null, 2)}\n`);
  }
  if (!existsSync(join(dir, "cordis.yml"))) {
    writeFileSync(
      join(dir, "cordis.yml"),
      "# dsh profile root — an empty entry list. The tree is composed as patches:\n# each bundle in package.json's dsh.profile.bundles, then cordis.patch.yml.\n# Edit cordis.patch.yml, not this file.\n[]\n",
    );
  }
  if (!existsSync(join(dir, "cordis.patch.yml"))) {
    writeFileSync(
      join(dir, "cordis.patch.yml"),
      "# Your patch layer for this dsh profile, applied after every bundle layer:\n# a top-level YAML array of loader patch entries. nanoMuse Desktop and dsh\n# write settings here; you may edit it too.\n[]\n",
    );
  }
  const link = join(dir, "node_modules", BUNDLE);
  const target = join(dshDir, "node_modules", BUNDLE);
  if (relink(link, target)) log(`profile: ${BUNDLE} → ${target}`);
  return dir;
}

/** Try to bind one loopback port (0 = any); the port bound, or 0 when it is taken. */
function tryPort(port: number): Promise<number> {
  return new Promise((resolve) => {
    const srv = createServer();
    srv.unref();
    srv.on("error", () => resolve(0));
    srv.listen(port, "127.0.0.1", () => {
      const address = srv.address();
      const bound = typeof address === "object" && address ? address.port : 0;
      srv.close(() => resolve(bound));
    });
  });
}

/** The port tried first on a fresh install (the connectors' loopback is 38417). */
const HOST_PORT_DEFAULT = 38421;

/**
 * The host's port, kept across launches. The window's origin is `127.0.0.1:<port>`, and
 * the origin is the browser's storage key — the preferences, the star asks' memory, the
 * live stage's place, the harness's own settings all live in that origin's localStorage —
 * so a port that changed on every launch meant an app that forgot everything on every
 * launch. The port used last time is tried first (it is written to `<home>/port`), then
 * the default, then any free one.
 */
async function hostPort(home: string): Promise<number> {
  const file = join(home, "port");
  let last = 0;
  try {
    last = Number.parseInt(readFileSync(file, "utf8").trim(), 10) || 0;
  } catch {
    last = 0;
  }
  const candidates = last > 0 ? [last, HOST_PORT_DEFAULT, 0] : [HOST_PORT_DEFAULT, 0];
  for (const candidate of candidates) {
    const port = await tryPort(candidate);
    if (port > 0) {
      try {
        writeFileSync(file, `${port}\n`);
      } catch (exc) {
        log(`port: could not remember ${port}: ${String(exc)}`);
      }
      return port;
    }
  }
  throw new Error("no free loopback port for the host");
}

/**
 * A GUI launch on macOS and Linux inherits the session's environment, not the shell's, so
 * the agent's bash and `nanomuse` on PATH would miss Homebrew and the like. Ask the login
 * shell once for its PATH, as the harness's own desktop does; anything else is left as is.
 */
function loginShellPath(): string | undefined {
  if (process.platform === "win32") return undefined;
  const sh = process.env.SHELL || "/bin/sh";
  try {
    const out = spawnSync(sh, ["-ilc", 'printf "%s" "$PATH"'], {
      encoding: "utf8",
      timeout: 8000,
      stdio: ["ignore", "pipe", "ignore"],
      env: { ...process.env, DISABLE_AUTO_UPDATE: "true", ZSH_TMUX_AUTOSTART: "false" },
    });
    const path = (out.stdout || "").trim();
    return out.status === 0 && path.includes("/") ? path : undefined;
  } catch {
    return undefined;
  }
}

/** Start the Host and resolve with the web app's URL (its one-time token included). */
function startHost(): Promise<string> {
  const dshDir = join(resourcesDir(), "dsh");
  const bin = join(dshDir, "node_modules", "@deepseek-ai", "dsh", "lib", "bin.js");
  if (!existsSync(bin)) {
    return Promise.reject(new Error(`the harness is not bundled: ${bin} is missing (run scripts/prepare-dsh.mjs)`));
  }
  const home = harnessHome();
  mkdirSync(home, { recursive: true });
  ensureProfile(dshDir);
  return new Promise<string>((resolve, reject) => {
    Promise.all([hostPort(home), ensureOperator()])
      .then(([port, operatorServer]) => {
        const env: NodeJS.ProcessEnv = {
          ...process.env,
          ELECTRON_RUN_AS_NODE: "1",
          DSH_HOME: home,
          // One secret per launch, shared by the bundle and the runtime's `nanomuse mcp`
          // server: a hands step the person must agree to is confirmed with a ticket only
          // the bundle can make (after the permission card), never by the model's own word.
          NANOMUSE_MCP_CONFIRM: randomBytes(24).toString("hex"),
        };
        if (operatorServer) {
          // The hands themselves: the runtime's `nanomuse mcp` (a child of the host, which
          // inherits this environment) finds the operator here and moves the mouse, types
          // and takes the screenshot through this process (src/operator.ts).
          env.NANOMUSE_OPERATOR_URL = operatorServer.url;
          env.NANOMUSE_OPERATOR_TOKEN = operatorServer.token;
        }
        const shellPath = loginShellPath();
        if (shellPath) env.PATH = shellPath;
        // The proxy for the model providers (the Cloud page's Network row): on the Host's
        // environment, which Node's fetch reads with NODE_USE_ENV_PROXY and the runtime's
        // httpx reads as it is; the relay and loopback are on NO_PROXY (src/proxy.ts).
        const proxied = proxyEnv(prefs.proxy, prefs.relayHosts ?? []);
        Object.assign(env, proxied);
        hostProxy = proxied.HTTPS_PROXY ?? "";
        if (hostProxy) log(`proxy: providers through ${maskProxyUrl(hostProxy)}; never for ${proxied.NO_PROXY}`);
        const runtime = bundledRuntime();
        if (!env.NANOMUSE_PY && runtime) env.NANOMUSE_PY = runtime;
        // Loud when the hands have nothing to run: a packaged build without its runtime, or
        // NANOMUSE_PY (from the login shell) pointing at a file that is not there. The
        // Computer-use page shows the same with the fix; this is for the log people send in.
        if (env.NANOMUSE_PY && !existsSync(env.NANOMUSE_PY)) {
          log(`runtime: NANOMUSE_PY=${env.NANOMUSE_PY} does not exist — the hands are off until it is fixed or unset`);
        } else if (!env.NANOMUSE_PY && app.isPackaged) {
          log(`runtime: no bundled runtime at ${join(resourcesDir(), "runtime")} and NANOMUSE_PY is not set — the hands are off (rebuild with the runtime, or install nanomuse and set NANOMUSE_PY)`);
        }
        const args = ["--expose-internals", bin, PROFILE, "--no-open", "--port", String(port)];
        log(`host: ${process.execPath} ${args.join(" ")} (DSH_HOME=${home}${env.NANOMUSE_PY ? `, NANOMUSE_PY=${env.NANOMUSE_PY}` : ""})`);
        const proc = spawn(process.execPath, args, { cwd: homedir(), env, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
        child = proc;
        hostStderr = "";
        // The wait (src/host-start.ts): no deadline while the Host runs. After two minutes the
        // loading page says the start is slow and shows the Host's last lines; after ten the
        // person is asked whether to keep waiting. Only the Host's exit fails the start.
        const watch = new HostStartWatch({
          onSlow: (state) => showSlowStart(state),
          onCap: (state) => void askKeepWaiting(watch, state),
        });
        startWatch = watch;
        let ready = false;
        proc.stdout?.setEncoding("utf8");
        proc.stdout?.on("data", (chunk: string) => {
          watch.stdout(chunk);
          for (const line of chunk.split("\n")) if (line.trim()) log(`dsh: ${maskToken(line)}`);
        });
        proc.stderr?.setEncoding("utf8");
        proc.stderr?.on("data", (chunk: string) => {
          const lines = chunk.split("\n").filter((line) => line.trim());
          const kept = process.platform === "linux" ? lines.filter((line) => !glibCritical(line)) : lines;
          if (kept.length) {
            hostStderr = (hostStderr + kept.join("\n") + "\n").slice(-65_536);
            watch.stderr(kept.join("\n"));
          }
          for (const line of kept) log(`dsh! ${line}`);
        });
        proc.on("error", (exc) => watch.error(exc));
        proc.on("exit", (code, signal) => {
          log(`host exited: code=${code} signal=${signal}${glibCriticals ? ` (${glibCriticals} GLib-GObject-CRITICAL lines from sharp's libvips not logged)` : ""}`);
          glibCriticals = 0;
          child = null;
          watch.exited(code, signal);
          if (ready && !quitting && !restartingHost) void hostStopped();
        });
        void watch.done.then((outcome) => {
          if (startWatch === watch) startWatch = null;
          if (outcome.kind === "ready") {
            ready = true;
            const waited = watch.state().waitedMs;
            if (waited > 30_000) log(`host: ready after ${waitedText(waited, false)}`);
            resolve(outcome.url);
          } else if (outcome.kind === "exited") {
            const { code, signal } = outcome;
            reject(new Error(`the host exited before it was ready (code ${code ?? signal})`));
          } else reject(outcome.error);
        });
      })
      .catch(reject);
  });
}

/** The wait for the Host's address under way, so the cap dialog and the quit know about it. */
let startWatch: HostStartWatch | null = null;

/** The loading page: "Still starting", with the Host's last lines (resources/loading.html, `__slow`). */
function showSlowStart(state: WaitState): void {
  const win = mainWindow;
  if (!win || win.isDestroyed() || hostUrl) return;
  if (state.tail.length === 0 && state.silentMs === state.waitedMs) log(`host: no output after ${waitedText(state.waitedMs, false)}; still waiting`);
  void win.webContents.executeJavaScript(`window.__slow && window.__slow(${JSON.stringify(state.tail)})`).catch(() => undefined);
}

/**
 * The cap: the Host has run for CAP_MS without its address. The person decides; a Host
 * that is alive is never stopped behind their back. "Keep waiting" asks again CAP_MS later;
 * "Quit" ends the app, which stops the Host (before-quit), and the log says so.
 */
async function askKeepWaiting(watch: HostStartWatch, state: WaitState): Promise<void> {
  if (quitting || startWatch !== watch) return;
  const waited = waitedText(state.waitedMs, zh);
  log(`host: still starting after ${waitedText(state.waitedMs, false)} (process alive, last line ${waitedText(state.silentMs, false)} ago); asking whether to keep waiting`);
  for (;;) {
    const { response } = await dialog.showMessageBox({
      type: "warning",
      title: T.stillStarting,
      message: T.stillStarting,
      detail: `${T.stillStartingDetail(waited)}${state.tail.length ? `\n\n${state.tail.slice(-4).join("\n")}` : ""}`,
      buttons: [T.keepWaiting, T.copyDetails, T.quit],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
    if (quitting || startWatch !== watch) return;
    if (response === 1) {
      clipboard.writeText(details(`${T.stillStarting} (${waited})`));
      await dialog.showMessageBox({ type: "info", title: "nanoMuse", message: T.copied, buttons: ["OK"] });
      continue;
    }
    if (response === 2) {
      log(`host: still starting after ${waitedText(state.waitedMs, false)}; quitting at the person's request, which stops the host process`);
      app.quit();
      return;
    }
    log("host: keeping on waiting at the person's request");
    watch.keepWaiting();
    return;
  }
}

/** How many `GLib-GObject-CRITICAL` lines the Host's stderr carried this launch (Linux; see glibCritical). */
let glibCriticals = 0;
const GLIB_CRITICAL = /GLib-GObject-CRITICAL \*\*: .*g_object_(un)?ref: assertion 'G_IS_OBJECT \(object\)' failed/;

/**
 * Linux: whether a Host stderr line is the GLib assertion that sharp's libvips raises on
 * every picture it touches inside Electron — the harness resizes the hands' screenshots
 * with sharp, whose prebuilt libvips carries its own GLib, while Electron's binary links
 * the system's and leaks its symbols into the process (electron/electron#46323; sharp's
 * install notes, "Electron and Linux"). Harmless to the picture, 65 000 lines a session
 * in the log. The first one is logged with this explanation; the rest are counted.
 */
function glibCritical(line: string): boolean {
  if (!GLIB_CRITICAL.test(line)) return false;
  glibCriticals += 1;
  if (glibCriticals === 1) log(`dsh! ${line.trim()} — sharp's libvips and Electron's GLib in one process (electron/electron#46323); further lines of this kind are counted, not logged`);
  return true;
}

function stopHost(): Promise<void> {
  const proc = child;
  if (!proc || proc.exitCode !== null) return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => resolve();
    proc.once("exit", done);
    if (process.platform === "win32" && proc.pid) {
      // the Host's own children (shells, the runtime for the hands) go with it
      spawnSync("taskkill", ["/pid", String(proc.pid), "/T", "/F"], { stdio: "ignore" });
    } else {
      proc.kill("SIGTERM");
      setTimeout(() => {
        if (proc.exitCode === null) proc.kill("SIGKILL");
      }, 3000).unref();
    }
    setTimeout(done, 5000).unref();
  });
}

/** A host restart the person asked for is under way: the exit handler must not treat it as a crash. */
let restartingHost = false;

/**
 * Stop the Host and start it again, the window staying up: what *Restart now* under the
 * Network row does, so a proxy just set reaches the provider calls without quitting the app.
 * The operator server and the helper stay; the page reloads under the Host's new token.
 */
async function restartHost(): Promise<void> {
  if (restartingHost || quitting || !hostUrl) return;
  restartingHost = true;
  log("host: restarting at the person's request");
  try {
    await stopHost();
    restarts = 0;
    await boot();
  } catch (exc) {
    log(`restart failed: ${String(exc)}`);
    await reportStartupFailure(exc);
  } finally {
    restartingHost = false;
  }
}

function details(message: string): string {
  const s = shipped();
  return [
    message,
    "",
    `nanoMuse Desktop ${app.getVersion()} · dsh ${s.dsh ?? "?"} · ${BUNDLE} ${s.bundle ?? "?"}`,
    `Electron ${process.versions.electron} · ${process.platform} ${process.arch}`,
    `home: ${harnessHome()}`,
    "",
    "--- shell ---",
    logs.slice(-30).join("\n"),
    "",
    "--- host stderr ---",
    hostStderr.slice(-4000),
  ].join("\n");
}

async function reportStartupFailure(exc: unknown): Promise<void> {
  const message = String((exc as Error).message ?? exc);
  for (;;) {
    const { response } = await dialog.showMessageBox({
      type: "error",
      title: T.notReady,
      message: T.notReady,
      detail: `${message}\n\n${T.reportHint} ${ISSUES_PAGE}`,
      buttons: [T.copyDetails, T.openLogFolder, T.quit],
      defaultId: 0,
      cancelId: 2,
      noLink: true,
    });
    if (response === 0) {
      clipboard.writeText(details(message));
      await dialog.showMessageBox({ type: "info", title: "nanoMuse", message: T.copied, buttons: ["OK"] });
      continue;
    }
    if (response === 1) {
      shell.showItemInFolder(join(harnessHome(), "desktop.log"));
      continue;
    }
    return;
  }
}

/** The Host died under a running window: offer a restart (once by itself, then by hand). */
async function hostStopped(): Promise<void> {
  if (quitting) return;
  if (restarts === 0) {
    restarts += 1;
    log("host stopped; starting it again");
    try {
      await boot();
      return;
    } catch (exc) {
      log(`restart failed: ${String(exc)}`);
    }
  }
  const { response } = await dialog.showMessageBox({
    type: "error",
    title: T.stopped,
    message: T.stopped,
    detail: hostStderr.slice(-1500),
    buttons: [T.restart, T.copyDetails, T.quit],
    defaultId: 0,
    cancelId: 2,
    noLink: true,
  });
  if (response === 0) {
    restarts = 0;
    try {
      await boot();
    } catch (exc) {
      await reportStartupFailure(exc);
      app.quit();
    }
  } else if (response === 1) {
    clipboard.writeText(details(T.stopped));
    void hostStopped();
  } else {
    app.quit();
  }
}

function iconPath(): string {
  return join(ownResources(), "app-icon.png");
}

/** The Muse window colours: near-black in the dark, paper in the light (the bundle's stylesheet agrees). */
const BASE_DARK = "#171717";
const BASE_LIGHT = "#f9f9f9";
/** The height of the Windows caption-button overlay; the page's top clearance matches it. */
const OVERLAY_HEIGHT = 40;

/** The Windows caption buttons: transparent over the page, symbols in the scheme's ink. */
function overlayColors(dark = nativeTheme.shouldUseDarkColors): Electron.TitleBarOverlay {
  return { color: dark ? BASE_DARK : BASE_LIGHT, symbolColor: dark ? "#e5e5e5" : "#262626", height: OVERLAY_HEIGHT };
}

type PermissionKind = "accessibility" | "screen" | "microphone";
type PermissionState = "granted" | "denied" | "not-determined" | "not-needed";

/**
 * Where one permission the hands use stands; only macOS gates them. TCC's own answer through
 * the native module when it loaded (src/mac-permissions.ts); Electron's `systemPreferences`
 * probes otherwise, as before.
 */
function permissionState(kind: PermissionKind): PermissionState {
  if (process.platform !== "darwin") return "not-needed";
  if (kind !== "microphone") {
    const native = macPermissions.status(kind);
    if (native === "authorized") return "granted";
    if (native === "not determined") return "not-determined";
    if (native !== null) return "denied";
  }
  if (kind === "accessibility") return systemPreferences.isTrustedAccessibilityClient(false) ? "granted" : "denied";
  const status = systemPreferences.getMediaAccessStatus(kind);
  if (status === "granted") return "granted";
  if (status === "not-determined") return "not-determined";
  return "denied";
}

const PERMISSION_PANES: Record<PermissionKind | "files", string> = {
  accessibility: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
  screen: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
  microphone: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
  // Full Disk Access: the Files page points here when the agent cannot read a protected folder
  files: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
};

// ---- macOS: "nanoMuse Computer Use", the helper that holds the hands' permissions ----------
//
// The grants go to the responsible process, so a separate app bundle started through `open`
// has its own rows in the Screen Recording and Accessibility panes and can be restarted on
// its own when a grant lands (src/mac-helper.ts has the why and the protocol). The operator
// sends it every screenshot and action; mac-permissions.ts reads its grants. Without the
// bundle (a development run without build.sh, an older build) everything works as before.

let macHelper: MacHelper | null = null;

/** The helper client, made once on macOS; null elsewhere. Starting it is `helperReady()`. */
function helper(): MacHelper | null {
  if (process.platform !== "darwin") return null;
  if (!macHelper) {
    macHelper = new MacHelper({
      appPath: defaultHelperPath(process.execPath, app.isPackaged, join(__dirname, ".."), process.env),
      dataDir: join(app.getPath("userData"), "computer-use"),
      log,
    });
    macPermissions.useHelper(macHelper);
  }
  return macHelper;
}

/** The helper running (started now if need be); false where there is none or it failed to start. */
async function helperReady(): Promise<boolean> {
  const h = helper();
  return h ? h.ready() : false;
}

/** What the permission dialogs name as the switch to flip. */
function permissionTarget(): string {
  return macPermissions.helperInUse() ? HELPER_NAME : "nanoMuse Desktop";
}

let awakeBlocker: number | null = null;

function releaseAwake(): void {
  if (awakeBlocker !== null) {
    powerSaveBlocker.stop(awakeBlocker);
    awakeBlocker = null;
  }
}

// ---- app behaviour: the General page's switches ------------------------------------------

/** What Muse's General page calls App behavior: start with the system, live in the menu bar, the quick-chat key. */
interface Prefs {
  openAtLogin: boolean;
  menuBar: boolean;
  quickChat: boolean;
  /** The person's own quick-chat combination (an Electron accelerator); absent means the platform's default. */
  quickChatKey?: string;
  /** The proxy for the model providers (`http://host:port`, `socks5://host:port`); absent means none. */
  proxy?: string;
  /** The relay hosts the plugin reported (its `config.baseURL`), kept on NO_PROXY with the default relay. */
  relayHosts?: string[];
}
const PREFS_DEFAULT: Prefs = { openAtLogin: false, menuBar: true, quickChat: true };
/** ⌥ Space on macOS as in Muse; Ctrl+Alt+Space where Alt+Space is the window menu. */
const QUICK_CHAT_DEFAULT = process.platform === "darwin" ? "Alt+Space" : "Ctrl+Alt+Space";
/** One or more modifiers and a key, in Electron's accelerator words; a function key may stand alone. */
const ACCELERATOR = /^((?:(?:CommandOrControl|CmdOrCtrl|Command|Cmd|Control|Ctrl|Alt|Option|Shift|Super|Meta)\+)*)(Space|Tab|Backspace|Delete|Insert|Return|Enter|Up|Down|Left|Right|Home|End|PageUp|PageDown|F(?:[1-9]|1[0-9]|2[0-4])|[A-Z0-9]|[`\-=\[\]\\;',.\/])$/;
let prefs: Prefs = PREFS_DEFAULT;
let tray: Tray | null = null;
/** Whether the last registration failed because another app holds the combination. */
let quickChatTaken = false;

function validAccelerator(text: string): boolean {
  const m = ACCELERATOR.exec(text);
  return Boolean(m) && (Boolean(m?.[1]) || /^F\d+$/.test(m?.[2] ?? ""));
}

/** The combination in force: the person's, when it parses, else the platform's default. */
function quickChatKey(): string {
  return prefs.quickChatKey && validAccelerator(prefs.quickChatKey) ? prefs.quickChatKey : QUICK_CHAT_DEFAULT;
}

function prefsPath(): string {
  return join(harnessHome(), "desktop.json");
}

function readPrefs(): Prefs {
  try {
    const raw = JSON.parse(readFileSync(prefsPath(), "utf8")) as Partial<Prefs>;
    return { ...PREFS_DEFAULT, ...(typeof raw === "object" && raw ? raw : {}) };
  } catch {
    return PREFS_DEFAULT;
  }
}

function writePrefs(): void {
  try {
    mkdirSync(harnessHome(), { recursive: true });
    writeFileSync(prefsPath(), `${JSON.stringify(prefs, null, 2)}\n`);
  } catch (exc) {
    log(`prefs: could not save: ${String(exc)}`);
  }
}

/** Bring the window up (make one if it was closed) and focus it. */
function showWindow(): BrowserWindow | null {
  if (!mainWindow && hostUrl) {
    mainWindow = createWindow();
    void mainWindow.loadURL(hostUrl);
  }
  if (!mainWindow) return null;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
  return mainWindow;
}

/** The quick-chat key: the window comes up with a fresh chat and the composer focused; pressed while it is in front, it steps aside. */
function quickChat(): void {
  if (mainWindow && mainWindow.isFocused() && mainWindow.isVisible()) {
    if (process.platform === "darwin") app.hide();
    else mainWindow.minimize();
    return;
  }
  const win = showWindow();
  win?.webContents.send("nanomuse:quick-chat");
}

function applyQuickChat(): void {
  globalShortcut.unregisterAll();
  quickChatTaken = false;
  if (!prefs.quickChat) return;
  const key = quickChatKey();
  let ok = false;
  try {
    ok = globalShortcut.register(key, quickChat);
  } catch (exc) {
    log(`quick chat: ${key}: ${String(exc)}`);
  }
  quickChatTaken = !ok;
  if (!ok) log(`quick chat: ${key} is taken by another app`);
}

function applyMenuBar(): void {
  if (!prefs.menuBar) {
    tray?.destroy();
    tray = null;
    return;
  }
  if (tray) return;
  let icon = nativeImage.createFromPath(iconPath());
  if (!icon.isEmpty()) icon = icon.resize({ width: process.platform === "darwin" ? 18 : 22, height: process.platform === "darwin" ? 18 : 22 });
  try {
    tray = new Tray(icon);
  } catch (exc) {
    log(`menu bar: ${String(exc)}`);
    return;
  }
  tray.setToolTip("nanoMuse");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: T.open, click: () => void showWindow() },
      { label: T.newChat, accelerator: prefs.quickChat ? quickChatKey() : undefined, click: () => showWindow()?.webContents.send("nanomuse:quick-chat") },
      { type: "separator" },
      { label: T.quit, click: () => app.quit() },
    ]),
  );
  if (process.platform !== "darwin") tray.on("click", () => void showWindow());
}

function applyOpenAtLogin(): void {
  if (process.platform === "linux") {
    // freedesktop autostart: a .desktop entry pointing at this executable (the AppImage or the installed binary)
    const dir = join(process.env.XDG_CONFIG_HOME || join(homedir(), ".config"), "autostart");
    const file = join(dir, "nanomuse-desktop.desktop");
    try {
      if (prefs.openAtLogin) {
        mkdirSync(dir, { recursive: true });
        const exe = process.env.APPIMAGE || process.execPath;
        writeFileSync(file, `[Desktop Entry]\nType=Application\nName=nanoMuse\nExec="${exe}"\nIcon=nanomuse-desktop\nX-GNOME-Autostart-enabled=true\nTerminal=false\n`);
      } else rmSync(file, { force: true });
    } catch (exc) {
      log(`open at login: ${String(exc)}`);
    }
    return;
  }
  if (!app.isPackaged) return; // a dev checkout should not register itself
  app.setLoginItemSettings({ openAtLogin: prefs.openAtLogin, ...(process.platform === "darwin" ? { openAsHidden: true } : {}) });
}

function applyPrefs(): void {
  applyMenuBar();
  applyQuickChat();
  applyOpenAtLogin();
}

/** What the General page shows: the values, the key in force and the default, whether another app holds it, and which of the three this platform can do; the Network row's proxy, as kept and as shown. */
function prefsView(): Prefs & { quickChatKey: string; quickChatDefault: string; quickChatTaken: boolean; proxy: string; proxyMasked: string; proxyApplied: string; supports: { openAtLogin: boolean; menuBar: boolean; quickChat: boolean } } {
  const proxy = validProxyUrl(prefs.proxy ?? "") ?? "";
  return { ...prefs, quickChatKey: quickChatKey(), quickChatDefault: QUICK_CHAT_DEFAULT, quickChatTaken, proxy, proxyMasked: maskProxyUrl(proxy), proxyApplied: hostProxy, supports: { openAtLogin: process.platform !== "linux" || Boolean(process.env.APPIMAGE) || app.isPackaged, menuBar: true, quickChat: true } };
}

/**
 * Report a bug the way Muse does: a screenshot of the window goes to Downloads, the
 * issue page opens with the build's facts filled in; the person drags the picture in.
 */
async function reportBug(): Promise<{ screenshot: string; url: string }> {
  const s = shipped();
  const facts = [
    `nanoMuse Desktop ${app.getVersion()} · ${process.platform} ${process.arch}`,
    `DeepSeek Harness ${s.dsh ?? "?"} · dsh-nanomuse ${s.bundle ?? "?"} · Electron ${process.versions.electron}`,
  ];
  let screenshot = "";
  if (mainWindow) {
    try {
      const image = await mainWindow.webContents.capturePage();
      const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      screenshot = join(app.getPath("downloads"), `nanoMuse-${stamp}.png`);
      writeFileSync(screenshot, image.toPNG());
    } catch (exc) {
      log(`report: no screenshot: ${String(exc)}`);
      screenshot = "";
    }
  }
  // The issue form's fields, by id (.github/ISSUE_TEMPLATE/bug_report.yml): a bare `body`
  // would be dropped on the way to the form.
  const params = new URLSearchParams({
    template: "bug_report.yml",
    labels: "bug,desktop",
    surface: "Desktop app",
    version: app.getVersion(),
    os: facts.join(" · "),
    what: screenshot ? `\n\n(Drag the screenshot nanoMuse saved to Downloads — ${screenshot.split(/[\\/]/).pop()} — in here.)` : "",
  });
  const url = `${ISSUES_PAGE}/new?${params.toString()}`;
  void shell.openExternal(url);
  return { screenshot, url };
}

/** The requests the preload bridge forwards from the web client (see preload.ts). */
function registerBridge(): void {
  // appImage: the Linux build runs from an AppImage (the runtime sets APPIMAGE), so About offers the AppImage of a newer version, not the .deb
  ipcMain.handle("nanomuse:info", () => ({ version: app.getVersion(), platform: process.platform, arch: process.arch, appImage: Boolean(process.env.APPIMAGE) }));
  ipcMain.handle("nanomuse:permissions", async () => {
    // the helper's grants, fresh, when it runs — started again when it went away (the
    // "Quit & Reopen" the Screen Recording switch offers ends it); `helper` tells the page
    // which rows to name
    if (macHelper?.present() && (await helperReady())) await macHelper.status().catch(() => undefined);
    return {
      accessibility: permissionState("accessibility"),
      screen: permissionState("screen"),
      microphone: permissionState("microphone"),
      helper: macPermissions.helperInUse(),
    };
  });
  ipcMain.handle("nanomuse:permissions:request", async (_e, kind: PermissionKind) => {
    if (process.platform !== "darwin") return "not-needed" satisfies PermissionState;
    if (!(kind in PERMISSION_PANES)) return "denied" satisfies PermissionState;
    if (kind === "accessibility") requestAccessibility();
    else if (kind === "microphone") await systemPreferences.askForMediaAccess("microphone").catch(() => false);
    else await requestScreenRecording();
    return permissionState(kind);
  });
  // macOS applies Screen Recording only to freshly started processes: after granting it, the
  // process that takes the screenshots has to start again — the helper when it is in use,
  // the whole app otherwise.
  ipcMain.handle("nanomuse:relaunch", () => {
    relaunchNow();
  });
  ipcMain.handle("nanomuse:permissions:settings", (_e, kind: PermissionKind | "files") => {
    if (process.platform === "darwin" && typeof kind === "string" && kind in PERMISSION_PANES) void shell.openExternal(PERMISSION_PANES[kind]);
  });
  ipcMain.handle("nanomuse:open-external", (_e, url: string) => {
    if (typeof url === "string" && EXTERNAL_URL.test(url)) void shell.openExternal(url);
  });
  ipcMain.handle("nanomuse:keep-awake", (_e, on: boolean) => {
    if (on === true && awakeBlocker === null) awakeBlocker = powerSaveBlocker.start("prevent-display-sleep");
    else if (on !== true) releaseAwake();
  });
  ipcMain.handle("nanomuse:theme", (_e, theme: string) => {
    mainWindow?.setBackgroundColor(theme === "dark" ? BASE_DARK : BASE_LIGHT);
    // the Windows caption buttons follow the page's colour scheme
    if (process.platform === "win32") mainWindow?.setTitleBarOverlay?.(overlayColors(theme === "dark"));
  });
  ipcMain.handle("nanomuse:prefs", () => prefsView());
  ipcMain.handle("nanomuse:prefs:set", (_e, patch: Partial<Prefs>) => {
    if (patch && typeof patch === "object") {
      for (const key of ["openAtLogin", "menuBar", "quickChat"] as const) if (typeof patch[key] === "boolean") prefs = { ...prefs, [key]: patch[key] };
      if (typeof patch.quickChatKey === "string") {
        // the person's combination; an empty string or the default puts the default back
        const key = patch.quickChatKey.trim();
        const { quickChatKey: _drop, ...rest } = prefs;
        prefs = !key || key === QUICK_CHAT_DEFAULT ? rest : validAccelerator(key) ? { ...rest, quickChatKey: key } : prefs;
      }
      if (typeof patch.proxy === "string") {
        // the proxy for the providers: an empty string removes it; an address that is not one is ignored
        const { proxy: _drop, ...rest } = prefs;
        const url = validProxyUrl(patch.proxy);
        prefs = !patch.proxy.trim() ? rest : url ? { ...rest, proxy: url } : prefs;
      }
      if (Array.isArray(patch.relayHosts)) {
        // the relay the plugin talks to, so a self-hosted one is on NO_PROXY as well
        prefs = { ...prefs, relayHosts: patch.relayHosts.filter((h): h is string => typeof h === "string" && h.trim() !== "").slice(0, 8) };
      }
      writePrefs();
      applyPrefs();
    }
    return prefsView();
  });
  // the Network row's *Restart now*: the Host again with the proxy just set, the window staying
  ipcMain.handle("nanomuse:restart-host", () => restartHost());
  ipcMain.handle("nanomuse:report-bug", () => reportBug());
  ipcMain.handle("nanomuse:permissions:guide", () => guidePermissions());
  ipcMain.handle("nanomuse:content-protection", (e, on: boolean) => {
    // The main window too, while the hands work: the agent should not read its own chat off the screen.
    if (e.sender === mainWindow?.webContents) mainWindow?.setContentProtection(on === true);
  });
  ipcMain.handle("nanomuse:reveal", (_e, path: string) => {
    if (typeof path === "string" && path && existsSync(path)) shell.showItemInFolder(path);
  });
}

// ---- the overlays while the hands work (0.1.34) ---------------------------------------------
//
// Two windows the web client drives over IPC, both with content protection on so neither is
// ever in a screenshot the hands take (UI-TARS does the same with its ScreenMarker). They are
// the phone's HandsStage and HandsCapsule, drawn for a desktop (resources/glow.html,
// resources/capsule.html):
//   • the glow — transparent, click-through, always on top, over the whole display: a light
//     breathing along the four edges says "the agent has the hands" (blue; amber while they
//     wait for the person), and at the point of each action the marker — ring, arc, dot, the
//     action's name — locks on and ripples; a drag draws its path;
//   • the capsule — a small always-on-top pill at the top of the screen with the agent's face,
//     "Step N" and what the hands are doing, Stop and "I'll take it", and under it the
//     question the agent asked before a step (Allow once / Deny) or the hold ("Your turn —
//     Done"); shown when the main window is not the one in front, so the person can see and
//     answer from wherever they are. It moves out of the way when the hands act under it.
// Both stay up for the whole run: the web client keeps `active` from the first computer call
// of a turn to the turn's end (the host's `hands.run`), so the model's thinking between two
// steps does not take the glow and the capsule down and put them back (they blinked, 1.0.0).

interface OverlayCard {
  id: string;
  kind: "approval" | "hold";
  title: string;
  text: string;
  actions: { id: string; label: string; tone?: "on" | "no" }[];
}

interface OverlayHands {
  /** The hands have this screen: a run is on, from its first computer call to its turn's end. */
  active: boolean;
  held: boolean;
  x: number;
  y: number;
  kind: string;
  /** The step the hands are on, from 1; 0 before the first. */
  step: number;
  /** The capsule's first line ("Step 3", "Your turn") and its second (what the hands do, the hold's reason). */
  title: string;
  text: string;
  face: string;
  /** The capsule's buttons, in the client's words; empty when not offered. */
  stop: string;
  take: string;
}

interface OverlayState {
  hands: OverlayHands | null;
  cards: OverlayCard[];
}

let glowWindow: BrowserWindow | null = null;
let capsuleWindow: BrowserWindow | null = null;
let overlayState: OverlayState = { hands: null, cards: [] };
let glowHideTimer: NodeJS.Timeout | null = null;
let capsuleHideTimer: NodeJS.Timeout | null = null;
/** The capsule's width and its margin from the top of the work area; it sits top-centre like the phone's, and at the bottom when it has dodged. */
const CAPSULE_WIDTH = 420;
const CAPSULE_MARGIN = 12;
/** Whether the capsule has moved to the bottom of the work area to get out from under the hands. */
let capsuleDodged = false;
/** How far from the capsule a pointer action is still "under" it. */
const CAPSULE_DODGE_PX = 8;
/** How long the capsule is given to be out of the way before the pointer moves. */
const CAPSULE_DODGE_MS = 120;
/** Linux: the capsule is off the screen for a capture (no content protection there). */
let capsuleAside = false;
/** The display bounds the glow was last given (JSON), so applyOverlay does not set them again and again. */
let glowBounds = "";
/** The last action the operator carried out, for the glow's marker (UI-TARS's prediction marker): fractions of the display, the words, when. */
let overlayMarker: (Marker & { at: number }) | null = null;
let markerTimer: NodeJS.Timeout | null = null;
/** How long a marker stays after its action; the glow stays up with it even before the web client has caught up. */
const MARKER_MS = 2200;
/**
 * Linux: why the glow is off the screen for a moment — `capture` between the operator's
 * "before" and "after" hooks (it must not be in the picture), `action` while a pointer
 * action runs (an unmapped window takes no input, whatever its X11 input shape — see
 * src/glow.ts for what goes wrong with the shape). applyOverlay does not bring it back
 * meanwhile.
 */
let glowAside: "" | "capture" | "action" = "";
/**
 * Settles once the glow, last shown, is click-through again: on X11 Chromium clears the
 * input shape Electron's setIgnoreMouseEvents set on every bounds change (creation, first
 * map, setBounds — src/glow.ts), so it is set again after each of those, and the operator
 * waits for the settled one before it moves the pointer with the glow up (operator.ts,
 * onAction).
 */
let glowClickThrough: Promise<void> = Promise.resolve();
let glowRearmTimers: NodeJS.Timeout[] = [];
/** The watchdog's count of repairs (Linux): the glow's page saw the pointer, which a click-through window never does. */
const glowLeaks = new LeakLog();
/** Linux: when the glow was last shown, resized or moved — Chromium makes up an enter and a move right after (glow.ts, LEAK_GRACE_MS). */
let glowShownAt = 0;
/** Linux: when this process last set the glow's bounds itself, so a resize of the window manager's doing is told apart in the log. */
let glowOwnBoundsAt = 0;

/** Linux: the glow's input shape, set now (one X request; a no-op elsewhere). */
function setGlowClickThrough(): void {
  const win = glowWindow;
  if (!win || win.isDestroyed() || process.platform !== "linux") return;
  win.setIgnoreMouseEvents(true, { forward: true });
}

/**
 * Linux: sets the glow's input shape again at REARM_DELAYS_MS — right after the native
 * call that cleared it (setImmediate), when the X server's ConfigureNotify for it has been
 * handled, and once more late. Every show, resize and move of the glow arms this, and so
 * does every action with the glow up. The promise settles with the GLOW_SETTLE_MS one.
 */
function armGlowClickThrough(): void {
  const win = glowWindow;
  if (!win || win.isDestroyed() || process.platform !== "linux") return;
  glowShownAt = Date.now();
  for (const timer of glowRearmTimers) clearTimeout(timer);
  glowRearmTimers = [];
  setImmediate(setGlowClickThrough);
  glowClickThrough = new Promise<void>((resolve) => {
    for (const delay of REARM_DELAYS_MS) {
      if (delay <= 0) continue;
      glowRearmTimers.push(
        setTimeout(() => {
          setGlowClickThrough();
          if (delay === GLOW_SETTLE_MS) resolve();
        }, delay),
      );
    }
  });
}

/**
 * Linux: the glow's page reported a pointer event. A click-through glow gets none (its
 * input shape is one pixel at (0,0)), so this is the X server telling us the shape is
 * gone — set it again at once, and say so in the log once per episode, so a log someone
 * sends in shows when and where it happened. The enter and move Chromium makes up right
 * after a show are not evidence and are let pass (glow.ts, leakIsEvidence).
 */
function repairGlowShape(leak: Leak): void {
  const now = Date.now();
  if (!leakIsEvidence(leak, now - glowShownAt)) return;
  setGlowClickThrough();
  armGlowClickThrough();
  if (glowLeaks.record(now)) log(`glow: the pointer reached the glow (${leak.type} at ${Math.round(leak.x)},${Math.round(leak.y)}) — its X11 input shape was lost; set again (repair ${glowLeaks.repairs})`);
}

/**
 * Linux: the glow's X window was resized or moved. Chromium has just cleared its input
 * shape for that (glow.ts), so it is set again; when the change was not this process's
 * own `setBounds`, the log says who-knows-what did it, once per such change.
 */
function glowReBounded(what: "resize" | "move"): void {
  const win = glowWindow;
  if (!win || win.isDestroyed()) return;
  if (Date.now() - glowOwnBoundsAt > 1000) {
    const b = win.getBounds();
    log(`glow: ${what}d from outside to ${b.width}×${b.height} at ${b.x},${b.y}; its X11 input shape is set again`);
  }
  armGlowClickThrough();
}

/** Shows the glow (never taking focus) and, on Linux, makes it click-through again once it is up. */
function showGlow(): void {
  const win = glowWindow;
  if (!win || win.isDestroyed()) return;
  win.showInactive();
  armGlowClickThrough();
}

/**
 * Linux: the glow steps aside for a pointer action — hidden before the pointer moves,
 * back right after the action with the marker fresh, so the ring and the action's name
 * appear where the click just landed. Resolves once the X server has the window unmapped.
 */
async function glowStepAside(): Promise<void> {
  const win = glowWindow;
  if (!win || win.isDestroyed() || !win.isVisible()) return;
  glowAside = "action";
  win.hide();
  await new Promise((r) => setTimeout(r, GLOW_HIDE_MS));
}

/** The operator's last action becomes the marker, shown for MARKER_MS; the glow follows it (applyOverlay). */
function setMarker(marker: Marker): void {
  overlayMarker = { ...marker, at: Date.now() };
  if (markerTimer) clearTimeout(markerTimer);
  markerTimer = setTimeout(() => {
    markerTimer = null;
    applyOverlay();
  }, MARKER_MS + 50);
  applyOverlay();
}

/** Linux: after the action — the glow comes back (if it is still wanted) with the marker drawn anew, timed from now. */
function glowStepBack(): void {
  if (glowAside !== "action") return;
  glowAside = "";
  if (overlayMarker) setMarker(overlayMarker);
  else applyOverlay();
}

// ---- the operator: the hands of this computer, run by this process -------------------------

let operator: Operator | null = null;
let operatorServer: OperatorServer | null = null;
let operatorStarting: Promise<OperatorServer | null> | null = null;

/** The operator and its loopback server, started once; null when the server could not bind (the runtime then uses its own backends). */
function ensureOperator(): Promise<OperatorServer | null> {
  if (operatorServer) return Promise.resolve(operatorServer);
  if (operatorStarting) return operatorStarting;
  operator ??= new Operator({
    log,
    permissions: () => ({ accessibility: permissionState("accessibility") !== "denied", screen: permissionState("screen") === "granted" || permissionState("screen") === "not-needed" }),
    // macOS: "nanoMuse Computer Use" takes the screenshots and moves the mouse when it is there (src/mac-helper.ts)
    helper: helper() ?? undefined,
    onAction: async (marker) => {
      setMarker(marker);
      await capsuleDodge(marker);
      if (process.platform !== "linux") return;
      // Linux: a pointer action must not land on the glow. It steps aside (unmapped, so it
      // takes no input whatever its X11 shape) and comes back in onActed; for the other
      // actions the glow stays up and is made click-through again before the operator goes on.
      if (pointerAction(marker.kind)) return glowStepAside();
      if (glowWindow && !glowWindow.isDestroyed() && glowWindow.isVisible()) armGlowClickThrough();
      return glowClickThrough;
    },
    onActed: process.platform === "linux" ? () => glowStepBack() : undefined,
    // Linux has no content protection: the glow would be in the picture, so it steps out of
    // the way for the capture (one frame) and comes back; macOS and Windows exclude it anyway.
    onCapture:
      process.platform === "linux"
        ? async (phase) => {
            if (!glowWindow || glowWindow.isDestroyed()) {
              glowAside = phase === "before" ? "capture" : "";
              capsuleAside = phase === "before";
              if (capsuleAside && capsuleWindow && !capsuleWindow.isDestroyed() && capsuleWindow.isVisible()) {
                capsuleWindow.hide();
                await new Promise((r) => setTimeout(r, 70));
              } else if (!capsuleAside) applyOverlay();
              return;
            }
            if (phase === "before") {
              capsuleAside = true;
              const capsuleWasUp = Boolean(capsuleWindow && !capsuleWindow.isDestroyed() && capsuleWindow.isVisible());
              if (capsuleWasUp) capsuleWindow?.hide();
              if (glowAside === "action") {
                if (capsuleWasUp) await new Promise((r) => setTimeout(r, 70));
                return; // the glow is already off the screen for the action
              }
              glowAside = "capture";
              if (glowWindow.isVisible() || capsuleWasUp) {
                glowWindow.hide();
                await new Promise((r) => setTimeout(r, 70));
              }
            } else {
              capsuleAside = false;
              if (glowAside === "capture") {
                glowAside = "";
                if (overlayUp()) showGlow();
              }
              applyOverlay();
            }
          }
        : undefined,
  });
  operatorStarting = startOperatorServer(operator, log)
    .then((server) => {
      operatorServer = server;
      const status = () => {
        const info = operator?.info();
        log(`operator: ${info?.available ? "available" : `not available (${info?.reason ?? "?"})`} · display ${info?.display.width}×${info?.display.height} (scale ${info?.display.scaleFactor})`);
      };
      // macOS: the line is about the helper's grants once it runs — written after it is up
      // (or has failed), not before, when it would name nanoMuse Desktop's own rows
      if (process.platform === "darwin" && helper()?.present()) void helperReady().then(status, status);
      else status();
      return server;
    })
    .catch((exc: unknown) => {
      log(`operator: could not start its server: ${String(exc)} — the runtime uses its own backends`);
      return null;
    })
    .finally(() => {
      operatorStarting = null;
    });
  return operatorStarting;
}

async function stopOperator(): Promise<void> {
  const server = operatorServer;
  operatorServer = null;
  if (server) await server.close().catch(() => undefined);
  // macOS: the helper goes with us (it would notice on its own within two seconds)
  if (macHelper) await macHelper.stop().catch(() => undefined);
}

/** The `--operator-check` run: the operator alone, asked over its own HTTP, the answers to a file. */
async function operatorCheck(file: string): Promise<void> {
  const out: Record<string, unknown> = { platform: process.platform, electron: process.versions.electron };
  try {
    const server = await ensureOperator();
    if (!server) throw new Error("the operator server did not start");
    const call = async (method: string, path: string, body?: unknown) => {
      const res = await fetch(server.url + path, { method, headers: { authorization: `Bearer ${server.token}`, "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
      return { status: res.status, body: (await res.json()) as Record<string, unknown> };
    };
    const info = await call("GET", "/info");
    out.info = info.body;
    const unauthorised = await fetch(server.url + "/info");
    out.unauthorised = unauthorised.status;
    const shot = await call("POST", "/screenshot", { width: 320, height: 180, format: "png" });
    const png = typeof shot.body.base64 === "string" ? Buffer.from(shot.body.base64, "base64") : Buffer.alloc(0);
    out.screenshot = { status: shot.status, width: shot.body.width, height: shot.body.height, screen: shot.body.screen, mime: shot.body.mime, bytes: png.length, png: png.subarray(0, 8).equals(Buffer.from("89504e470d0a1a0a", "hex")), error: shot.body.error };
    if (process.argv.includes("--operator-move")) {
      const display = (info.body.display ?? {}) as { width?: number; height?: number };
      const x = Math.floor((display.width ?? 2) / 2);
      const y = Math.floor((display.height ?? 2) / 2);
      out.move = { x, y, ...(await call("POST", "/execute", { action: "move", x, y })) };
    }
    out.ok = Boolean((info.body as { available?: boolean }).available) && shot.status === 200;
  } catch (exc) {
    out.ok = false;
    out.error = String((exc as Error).message ?? exc);
  }
  writeFileSync(file, `${JSON.stringify(out, null, 2)}\n`);
  log(`operator check: ${out.ok ? "ok" : "failed"} → ${file}`);
  await stopOperator();
  app.exit(out.ok ? 0 : 1);
}

const OVERLAY_PREFS = { contextIsolation: true, nodeIntegration: false, sandbox: true, spellcheck: false, preload: join(__dirname, "overlay-preload.js") };

function overlayWindow(kind: "glow" | "capsule"): BrowserWindow {
  const display = screen.getPrimaryDisplay();
  const glow = kind === "glow";
  const win = new BrowserWindow({
    show: false,
    frame: false,
    transparent: true,
    hasShadow: false,
    resizable: false,
    movable: !glow,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    focusable: false,
    alwaysOnTop: true,
    ...(glow ? { x: display.bounds.x, y: display.bounds.y, width: display.bounds.width, height: display.bounds.height } : { ...capsulePlace(60), width: CAPSULE_WIDTH + 16, height: 60 }),
    webPreferences: OVERLAY_PREFS,
  });
  // Never in a screenshot: the hands must not see our own marks on the screen.
  win.setContentProtection(true);
  win.setAlwaysOnTop(true, "screen-saver");
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  if (glow) win.setIgnoreMouseEvents(true, { forward: true });
  if (glow && process.platform === "linux") {
    // Chromium clamps a new window to the work area (under GNOME Shell: the display less
    // its dock and top bar), so the glow would stop short of two edges; the display's
    // bounds, asked for again, take. Every bounds change — this one, the first map, a
    // later setBounds — costs the window its input shape (src/glow.ts): set it again.
    const b = win.getBounds();
    glowOwnBoundsAt = Date.now();
    if (b.width !== display.bounds.width || b.height !== display.bounds.height || b.x !== display.bounds.x || b.y !== display.bounds.y) {
      log(`glow: made ${b.width}×${b.height} at ${b.x},${b.y} (the work area); set to the display's ${display.bounds.width}×${display.bounds.height}`);
      win.setBounds(display.bounds);
    }
    win.on("show", () => armGlowClickThrough());
    win.on("resize", () => glowReBounded("resize"));
    win.on("move", () => glowReBounded("move"));
  }
  win.on("page-title-updated", (e) => e.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  void win.loadFile(join(ownResources(), `${kind}.html`));
  return win;
}

/** Where the capsule sits: top-centre of the primary display's work area, or bottom-centre once it has dodged the hands. */
function capsulePlace(height: number): { x: number; y: number } {
  const area = screen.getPrimaryDisplay().workArea;
  const x = Math.round(area.x + (area.width - (CAPSULE_WIDTH + 16)) / 2);
  const y = capsuleDodged ? area.y + area.height - height - CAPSULE_MARGIN : area.y + CAPSULE_MARGIN;
  return { x, y };
}

/**
 * The hands are about to act at the marker's point (fractions of the display): when that is
 * under the capsule, the capsule moves to the other edge of the work area first and the
 * operator waits CAPSULE_DODGE_MS so the pointer never lands on it. The phone's capsule dodges
 * the finger the same way.
 */
async function capsuleDodge(marker: Marker): Promise<void> {
  const win = capsuleWindow;
  if (!win || win.isDestroyed() || !win.isVisible() || !pointerAction(marker.kind)) return;
  const display = screen.getPrimaryDisplay();
  const b = win.getBounds();
  const under = (fx: number, fy: number) => {
    const px = display.bounds.x + fx * display.bounds.width;
    const py = display.bounds.y + fy * display.bounds.height;
    return px >= b.x - CAPSULE_DODGE_PX && px <= b.x + b.width + CAPSULE_DODGE_PX && py >= b.y - CAPSULE_DODGE_PX && py <= b.y + b.height + CAPSULE_DODGE_PX;
  };
  if (!under(marker.fx, marker.fy) && !(marker.fx2 !== undefined && marker.fy2 !== undefined && under(marker.fx2, marker.fy2))) return;
  capsuleDodged = !capsuleDodged;
  win.setBounds({ ...b, ...capsulePlace(b.height) });
  await new Promise((r) => setTimeout(r, CAPSULE_DODGE_MS));
}

function sendOverlay(win: BrowserWindow | null, state: unknown): void {
  if (win && !win.isDestroyed()) win.webContents.send("nanomuse:overlay:state", state);
}

/** The marker still worth showing: the operator's last action, less than MARKER_MS ago. */
function freshMarker(): (Marker & { at: number }) | null {
  return overlayMarker && Date.now() - overlayMarker.at < MARKER_MS ? overlayMarker : null;
}

/** Whether the glow should be on the screen: the web client says the hands are busy or held, or the operator just acted. */
function overlayUp(): boolean {
  const hands = overlayState.hands;
  return Boolean((hands && (hands.active || hands.held)) || freshMarker());
}

/** Nothing on the hands yet: the shape the pages expect. */
const NO_HANDS: OverlayHands = { active: false, held: false, x: -1, y: -1, kind: "", step: 0, title: "", text: "", face: "", stop: "", take: "" };

/** What the glow draws: the web client's state (the hands' own point, the action's kind) and the operator's marker (the exact point of the last action). */
function glowState(): Record<string, unknown> {
  const hands = overlayState.hands ?? NO_HANDS;
  const marker = freshMarker();
  return { ...hands, active: true, marker: marker ? { x: marker.fx, y: marker.fy, x2: marker.fx2 ?? -1, y2: marker.fy2 ?? -1, kind: marker.kind, text: marker.text, at: marker.at } : null };
}

function applyOverlay(): void {
  // the glow: up while the hands are active (or held) or the operator just acted, down a moment after
  if (overlayUp()) {
    if (glowHideTimer) { clearTimeout(glowHideTimer); glowHideTimer = null; }
    const display = screen.getPrimaryDisplay();
    const bounds = JSON.stringify(display.bounds);
    if (!glowWindow || glowWindow.isDestroyed()) {
      glowWindow = overlayWindow("glow"); // made at the display's bounds
      glowBounds = bounds;
    }
    // only when the display changed: on X11 every configure of the window costs it its input shape
    if (bounds !== glowBounds) {
      glowBounds = bounds;
      glowOwnBoundsAt = Date.now();
      glowWindow.setBounds(display.bounds);
    }
    if (!glowWindow.isVisible() && !glowAside) showGlow();
    sendOverlay(glowWindow, glowState());
  } else if (glowWindow && !glowWindow.isDestroyed() && glowWindow.isVisible()) {
    sendOverlay(glowWindow, { active: false });
    if (!glowHideTimer) glowHideTimer = setTimeout(() => { glowHideTimer = null; glowWindow?.hide(); }, 400);
  }
  // the capsule: the hands' pill and the cards, but only when the main window is not in front
  // (the chat shows the run and the cards itself then), and never while a capture is on (Linux)
  const mainInFront = Boolean(mainWindow && !mainWindow.isDestroyed() && mainWindow.isFocused() && mainWindow.isVisible());
  const hands = overlayState.hands && (overlayState.hands.active || overlayState.hands.held) ? overlayState.hands : null;
  const cards = mainInFront ? [] : overlayState.cards;
  const capsuleUp = !mainInFront && !capsuleAside && (Boolean(hands) || cards.length > 0);
  if (capsuleUp) {
    if (capsuleHideTimer) { clearTimeout(capsuleHideTimer); capsuleHideTimer = null; }
    if (!capsuleWindow || capsuleWindow.isDestroyed()) {
      capsuleDodged = false;
      capsuleWindow = overlayWindow("capsule");
    }
    capsuleWindow.setFocusable(true);
    if (!capsuleWindow.isVisible()) {
      capsuleDodged = false;
      capsuleWindow.setBounds({ ...capsuleWindow.getBounds(), ...capsulePlace(capsuleWindow.getBounds().height) });
      capsuleWindow.showInactive();
    }
    sendOverlay(capsuleWindow, { hands, cards });
  } else if (capsuleWindow && !capsuleWindow.isDestroyed() && capsuleWindow.isVisible()) {
    if (capsuleAside) {
      capsuleWindow.hide();
      return;
    }
    // a moment, so a step's end and the next step's start do not blink the capsule
    if (!capsuleHideTimer) {
      capsuleHideTimer = setTimeout(() => {
        capsuleHideTimer = null;
        sendOverlay(capsuleWindow, { hands: null, cards: [] });
        capsuleWindow?.hide();
      }, 220);
    }
  }
}

function registerOverlays(): void {
  ipcMain.on("nanomuse:overlay", (e, state: OverlayState) => {
    if (e.sender !== mainWindow?.webContents || !state || typeof state !== "object") return;
    const hands = state.hands && typeof state.hands === "object" ? state.hands : null;
    overlayState = {
      hands: hands
        ? {
            active: hands.active === true,
            held: hands.held === true,
            x: typeof hands.x === "number" ? hands.x : -1,
            y: typeof hands.y === "number" ? hands.y : -1,
            kind: String(hands.kind ?? "").slice(0, 32),
            step: typeof hands.step === "number" && hands.step > 0 ? Math.min(9999, Math.floor(hands.step)) : 0,
            title: String(hands.title ?? "").slice(0, 60),
            text: String(hands.text ?? "").slice(0, 160),
            face: typeof hands.face === "string" && /^(data:image\/[a-z+]+;base64,|https?:\/\/127\.0\.0\.1|https?:\/\/localhost)/.test(hands.face) ? hands.face.slice(0, 400_000) : "",
            stop: String(hands.stop ?? "").slice(0, 40),
            take: String(hands.take ?? "").slice(0, 40),
          }
        : null,
      cards: Array.isArray(state.cards)
        ? state.cards.slice(0, 3).map((c) => ({
            id: String(c.id ?? "").slice(0, 80),
            kind: c.kind === "hold" ? "hold" : "approval",
            title: String(c.title ?? "").slice(0, 60),
            text: String(c.text ?? "").slice(0, 400),
            actions: (Array.isArray(c.actions) ? c.actions : []).slice(0, 4).map((a) => ({ id: String(a.id ?? "").slice(0, 32), label: String(a.label ?? "").slice(0, 40), ...(a.tone === "on" || a.tone === "no" ? { tone: a.tone } : {}) })),
          }))
        : [],
    };
    applyOverlay();
  });
  ipcMain.on("nanomuse:overlay:ready", (e) => {
    if (e.sender === glowWindow?.webContents) sendOverlay(glowWindow, overlayState.hands ? { ...overlayState.hands } : { active: false });
    if (e.sender === capsuleWindow?.webContents) sendOverlay(capsuleWindow, { hands: overlayState.hands && (overlayState.hands.active || overlayState.hands.held) ? overlayState.hands : null, cards: overlayState.cards });
  });
  ipcMain.on("nanomuse:overlay:act", (e, payload: { card?: string; action?: string }) => {
    if (e.sender !== capsuleWindow?.webContents || !payload) return;
    mainWindow?.webContents.send("nanomuse:overlay:action", { card: String(payload.card ?? ""), action: String(payload.action ?? "") });
  });
  ipcMain.on("nanomuse:overlay:leak", (e, leak: unknown) => {
    // Linux: the glow's page saw the pointer — only possible when its input shape is gone
    if (process.platform !== "linux" || e.sender !== glowWindow?.webContents || !leakIsReal(leak)) return;
    repairGlowShape(leak);
  });
  ipcMain.on("nanomuse:overlay:resize", (e, height: number) => {
    if (e.sender !== capsuleWindow?.webContents || typeof height !== "number") return;
    const h = Math.max(48, Math.min(480, Math.round(height)));
    const b = capsuleWindow.getBounds();
    if (b.height !== h) capsuleWindow.setBounds({ ...b, height: h, ...capsulePlace(h) });
  });
  app.on("browser-window-focus", applyOverlay);
  app.on("browser-window-blur", applyOverlay);
}

/**
 * The first time the hands are about to be used on macOS: the two system permissions, asked
 * for in order with a word on why (Codex does the same), the panel live-updating as they are
 * granted. Returns what is granted now; the page decides whether to go on.
 */
async function guidePermissions(): Promise<Record<PermissionKind, PermissionState>> {
  const state = () => ({ accessibility: permissionState("accessibility"), screen: permissionState("screen"), microphone: permissionState("microphone") });
  if (process.platform !== "darwin") return state();
  // the helper first, so the dialogs name its rows and its grants are the ones read
  await helperReady();
  const viaHelper = macPermissions.helperInUse();
  const target = permissionTarget();
  if (permissionState("accessibility") !== "granted") {
    const { response } = await dialog.showMessageBox({
      type: "info",
      message: zh ? "nanoMuse 需要「辅助功能」权限" : "nanoMuse needs Accessibility",
      detail: zh
        ? viaHelper
          ? `动手操作电脑要靠它移动鼠标和输入。系统会弹出请求；在「系统设置 → 隐私与安全性 → 辅助功能」里打开 ${target} 即可——这是 nanoMuse 自带的一个小程序，专门负责截图和操作，权限只给它。`
          : "动手操作电脑要靠它移动鼠标和输入。系统会弹出请求；在「系统设置 → 隐私与安全性 → 辅助功能」里打开 nanoMuse Desktop 即可——它附带的运行时作为应用的一部分运行，不会单独出现在列表里。"
        : viaHelper
          ? `The hands move the mouse and type through it. The system asks next; in System Settings → Privacy & Security → Accessibility, switch on ${target} — the small program nanoMuse brings along for the screenshots and the input. Only it needs the permission.`
          : "The hands move the mouse and type through it. The system asks next; in System Settings → Privacy & Security → Accessibility, switch on nanoMuse Desktop. The runtime it bundles runs as part of the app and does not appear separately.",
      buttons: [zh ? "继续" : "Continue", zh ? "以后再说" : "Later"],
      defaultId: 0,
      cancelId: 1,
    });
    if (response === 0) requestAccessibility();
  }
  if (permissionState("screen") !== "granted") {
    const { response } = await dialog.showMessageBox({
      type: "info",
      message: zh ? "nanoMuse 需要「屏幕录制」权限" : "nanoMuse needs Screen Recording",
      detail: zh
        ? viaHelper
          ? `它靠截图看到屏幕上有什么。点「继续」后系统会询问一次；在「屏幕录制」面板里打开 ${target}（只需要这一项）。打开后它会自己重新启动，应用本身不用重启。`
          : "它靠截图看到屏幕上有什么。点「继续」后系统会询问一次；在「屏幕录制」面板里打开 nanoMuse Desktop（只需要这一项），然后重新启动应用——macOS 的这项权限只对重新启动后的应用生效。"
        : viaHelper
          ? `It sees the screen through screenshots. After Continue the system asks once; switch on ${target} in the Screen Recording pane (that one entry is all). It restarts by itself once the switch is on; the app does not need to.`
          : "It sees the screen through screenshots. After Continue the system asks once; switch on nanoMuse Desktop in the Screen Recording pane (that one entry is all), then relaunch the app — macOS applies this permission to freshly started apps only.",
      buttons: [zh ? "继续" : "Continue", zh ? "以后再说" : "Later"],
      defaultId: 0,
      cancelId: 1,
    });
    if (response === 0) await requestScreenRecording();
  }
  return state();
}

/**
 * Ask macOS for Screen Recording the way the system does it: `CGRequestScreenCaptureAccess`
 * through the native module — the system's dialog the first time, and the app on the pane's
 * list. Without the module, a 1×1 `desktopCapturer` probe, which is what listed the app
 * before 0.1.37. Then the pane, where the switch is, and the watch for the grant.
 */
async function requestScreenRecording(openPane = true): Promise<void> {
  if (await helperReady()) {
    // the helper's own request: its row appears in the pane; it opens the pane itself when asked
    await macHelper?.request("screen", openPane).catch(() => undefined);
    watchScreenGrant();
    return;
  }
  if (!macPermissions.askScreen()) {
    try {
      await desktopCapturer.getSources({ types: ["screen"], thumbnailSize: { width: 1, height: 1 } });
    } catch {
      /* no sources without the permission — that attempt was the point */
    }
  }
  if (openPane) void shell.openExternal(PERMISSION_PANES.screen);
  watchScreenGrant();
}

/** The Accessibility dialog (`AXIsProcessTrustedWithOptions` with the prompt — it also lists the app in the pane), then the pane when it is still off. */
function requestAccessibility(openPane = true): void {
  if (macPermissions.helperInUse()) {
    // the helper's dialog and row; the pane when its grant is still off
    void macHelper?.request("accessibility", openPane && permissionState("accessibility") !== "granted").catch(() => undefined);
    return;
  }
  const asked = macPermissions.askAccessibility();
  const trusted = systemPreferences.isTrustedAccessibilityClient(!asked);
  if (!trusted && openPane) void shell.openExternal(PERMISSION_PANES.accessibility);
}

/**
 * At launch on macOS (UI-TARS-desktop's `ensurePermissions`): when either permission the
 * hands need is not granted, the system's own dialogs — Screen Recording first, then
 * Accessibility — and the Screen Recording pane opened once per launch, so the person
 * finds the switch without hunting for it; `watchScreenGrant()` then offers the relaunch
 * the grant needs. Nothing is asked when both are already on, nor under `--operator-check`
 * / `--screenshot` (the checks must not block on a dialog). The status goes to the log.
 */
async function ensureMacPermissionsAtLaunch(): Promise<void> {
  if (process.platform !== "darwin") return;
  // the helper first: when it runs, its grants are the ones that count and the ones asked for
  await helperReady();
  const accessibility = permissionState("accessibility");
  const screen = permissionState("screen");
  const status = macHelper?.cachedStatus();
  // the helper's word on the screen (ScreenCaptureKit on macOS 14+) goes next to the TCC state: `screen=granted (capture ScreenCaptureKit)` is the line to look for when a screenshot is in doubt
  const source = macPermissions.helperInUse() ? `${HELPER_NAME} ${status?.version ?? ""}${status?.capture ? `, capture ${status.capture}` : ""}${status?.screenDetail ? `, ${status.screenDetail}` : ""}`.trim() : macPermissions.loaded() ? "native" : `systemPreferences — ${macPermissions.loadError()}`;
  log(`permissions: accessibility=${accessibility} screen=${screen} (${source}${!macPermissions.helperInUse() && macHelper ? `; helper: ${macHelper.failure()}` : ""})`);
  if (accessibility === "granted" && screen === "granted") return;
  if (screen !== "granted") void requestScreenRecording(true);
  if (accessibility !== "granted") requestAccessibility(false);
}

/** `app.relaunch()` asked for once; a second call before the quit would start two copies (0.1.38 did). */
let relaunching = false;

/**
 * Start the process that takes the screenshots again, so a Screen Recording grant takes
 * effect. With the helper in use that is the helper alone — `/quit` and a fresh `open`, the
 * app and the conversation untouched. Otherwise the whole app: through `app.quit()`, not
 * `app.exit()`, so `before-quit` stops the host and the operator server first and the old
 * `nanomuse mcp` — started before the permission was granted, and so still without it —
 * does not outlive the relaunch.
 */
function relaunchNow(): void {
  // with a helper bundle the helper is what restarts — also while it is between two processes
  // or failed to start (then this is the retry); in 0.1.38 a restart that found the helper
  // "not running" fell through here and relaunched the whole app, twice when clicked twice
  if (helper()?.present()) {
    log("permissions: restarting the helper for the new grant");
    void macHelper?.restart();
    return;
  }
  if (relaunching) return;
  relaunching = true;
  app.relaunch();
  app.quit();
}

let screenGrantWatch: NodeJS.Timeout | null = null;

/**
 * After the Screen Recording pane was opened for the person: watch for the switch to flip
 * (the system has no event for it) and, when it does, say the one thing the pane does not —
 * that the grant reaches only freshly started apps — with the restart button right there.
 * Gives up quietly after five minutes; the Computer-use page keeps its own notice.
 */
function watchScreenGrant(): void {
  if (process.platform !== "darwin" || screenGrantWatch) return;
  if (permissionState("screen") === "granted") return;
  const started = Date.now();
  screenGrantWatch = setInterval(() => {
    // the helper gone meanwhile (the switch's "Quit & Reopen" ends it): back, so its grant is what is read
    if (macHelper?.present() && !macHelper.running() && !macHelper.busy()) void macHelper.ready();
    if (permissionState("screen") !== "granted") {
      if (Date.now() - started > 5 * 60_000 && screenGrantWatch) {
        clearInterval(screenGrantWatch);
        screenGrantWatch = null;
      }
      return;
    }
    if (screenGrantWatch) clearInterval(screenGrantWatch);
    screenGrantWatch = null;
    if (macPermissions.helperInUse()) {
      // the grant is the helper's: a quiet restart of that one process, nothing to ask
      log("permissions: Screen Recording granted to the helper while running — restarting it");
      void macHelper?.restart();
      return;
    }
    log("permissions: Screen Recording granted while running — offering a relaunch");
    void dialog
      .showMessageBox({
        type: "info",
        message: zh ? "屏幕录制已允许，重新启动后生效" : "Screen Recording is on; it takes effect after a restart",
        detail: zh
          ? "macOS 只对重新启动后的应用应用这项权限。现在重新启动 nanoMuse，手就能看到屏幕；否则截图仍是一片黑。"
          : "macOS applies this permission to freshly started apps only. Restart nanoMuse now and the hands see the screen; until then screenshots come back black.",
        buttons: [zh ? "立即重启" : "Restart now", zh ? "稍后" : "Later"],
        defaultId: 0,
        cancelId: 1,
      })
      .then(({ response }) => {
        if (response === 0) relaunchNow();
      })
      .catch(() => undefined);
  }, 1500);
}

/**
 * The main window closed. On macOS the app stays in the Dock, as apps there do. On Linux
 * and Windows it stays only when there is a tray to come back from (the menu-bar switch on,
 * and `new Tray` worked): the tray's click, *Open* and the launcher all bring the window
 * back. Without a tray the app quits — before 0.1.37 it lived on headless: the glow and the
 * capsule are BrowserWindows too, so `window-all-closed` never fired once the hands had been
 * used, and every later launcher click was a second instance that found no window to show.
 */
function mainWindowClosed(): void {
  mainWindow = null;
  if (process.platform === "darwin" || quitting) return;
  if (tray) {
    log("window closed; the app stays in the tray (Open, or the launcher, brings it back)");
    return;
  }
  log("window closed; no tray — quitting");
  app.quit();
}

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 620,
    title: "nanoMuse",
    icon: process.platform === "darwin" ? undefined : nativeImage.createFromPath(iconPath()),
    backgroundColor: nativeTheme.shouldUseDarkColors ? BASE_DARK : BASE_LIGHT,
    show: false,
    autoHideMenuBar: process.platform !== "darwin",
    // macOS: no title bar, the traffic lights sit over the rail (Muse's window); the
    // web app marks its drag regions once the preload tells it the platform.
    ...(process.platform === "darwin" ? { titleBarStyle: "hiddenInset" as const, trafficLightPosition: { x: 16, y: 18 } } : {}),
    // Windows: the same window, with the system's own caption buttons drawn over the top
    // right corner (the overlay); the page leaves them room. Linux keeps its system bar —
    // every desktop draws it differently and the overlay is not available there.
    ...(process.platform === "win32" ? { titleBarStyle: "hidden" as const, titleBarOverlay: overlayColors() } : {}),
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, spellcheck: false, preload: join(__dirname, "preload.js") },
  });
  win.once("ready-to-show", () => win.show());
  win.on("enter-full-screen", () => win.webContents.send("nanomuse:fullscreen", true));
  win.on("leave-full-screen", () => win.webContents.send("nanomuse:fullscreen", false));
  // the harness names its document after itself; the window keeps ours
  win.on("page-title-updated", (e) => e.preventDefault());
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (EXTERNAL_URL.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    // the Host's origin (compared as parsed URLs, not a prefix) and our own pages from disk
    // (the loading page) stay in the window; http(s) goes to the browser; the rest is dropped
    const verdict = navigationVerdict(url, hostUrl, pathToFileURL(ownResources()).href);
    if (verdict === "allow") return;
    e.preventDefault();
    if (verdict === "external") void shell.openExternal(url);
  });
  win.webContents.session.setPermissionRequestHandler((_wc, permission, callback, details) => {
    // the microphone for voice input, for the Host's page alone; nothing else is asked for
    callback(permission === "media" && sameOrigin(details.requestingUrl, hostUrl));
  });
  win.on("closed", mainWindowClosed);
  // the splash: the logo in a loading ring and the wordmark (resources/loading.html) — no face
  void win.loadFile(join(ownResources(), "loading.html"), { query: { lang: zh ? "zh" : "en" } });
  return win;
}

async function boot(): Promise<void> {
  if (!mainWindow) mainWindow = createWindow();
  try {
    hostUrl = await startHost();
  } catch (exc) {
    log(`start failed: ${String(exc)}`);
    await mainWindow?.webContents.executeJavaScript(`window.__failed && window.__failed(${JSON.stringify(String((exc as Error).message ?? exc))})`).catch(() => undefined);
    throw exc;
  }
  log(`ready: ${hostUrl.replace(/token=\S+/, "token=…")}`);
  await mainWindow?.loadURL(hostUrl);
  if (screenshotFlag && mainWindow) {
    // the web app loads its plugins after the document; give it a moment
    await new Promise((r) => setTimeout(r, 8000));
    // `--screenshot-click=<aria-label>[,<aria-label>…]`: press buttons first (a rail room, a row…)
    const clicks = process.argv.find((a) => a.startsWith("--screenshot-click="))?.slice("--screenshot-click=".length);
    for (const label of clicks ? clicks.split(",") : []) {
      await mainWindow.webContents
        .executeJavaScript(`(() => { const b = document.querySelector('[aria-label=' + ${JSON.stringify(JSON.stringify(label))} + ']'); if (b) b.click(); return !!b })()`)
        .then((hit) => log(`screenshot: click ${label} → ${hit ? "ok" : "not found"}`))
        .catch(() => undefined);
      await new Promise((r) => setTimeout(r, 2500));
    }
    // `--screenshot-js=<file>`: run a script in the page (dev: drive the composer, open a sheet…);
    // `--screenshot-delay=<ms>`: wait that long before capturing (the agent's turn, an animation)
    const script = process.argv.find((a) => a.startsWith("--screenshot-js="))?.slice("--screenshot-js=".length);
    if (script) {
      const { readFileSync } = await import("node:fs");
      await mainWindow.webContents
        .executeJavaScript(readFileSync(script, "utf8"))
        .then((value) => log(`screenshot: script → ${String(value).slice(0, 200)}`))
        .catch((exc) => log(`screenshot: script failed: ${String(exc)}`));
    }
    const delay = Number(process.argv.find((a) => a.startsWith("--screenshot-delay="))?.slice("--screenshot-delay=".length) ?? 0);
    if (delay > 0) await new Promise((r) => setTimeout(r, delay));
    const image = await mainWindow.webContents.capturePage();
    writeFileSync(screenshotFlag, image.toPNG());
    log(`screenshot: ${screenshotFlag}`);
    app.quit();
  }
}

function about(): void {
  const s = shipped();
  const lines = [
    // the same version line as the web client's About (About.tsx `versionLine`)
    `nanoMuse Desktop ${app.getVersion()} · harness ${s.bundle ?? "?"}`,
    zh ? "一个开源的个人智能体，装在你的每一台设备上。" : "An open-source personal agent for every device you own.",
    "",
    `DeepSeek Harness ${s.dsh ?? "?"} (MIT) · ${BUNDLE} ${s.bundle ?? "?"} (GPL-3.0-or-later)`,
    `Electron ${process.versions.electron} · Chromium ${process.versions.chrome}`,
    "",
    zh
      ? "nanoMuse 是社区项目，与 Meta 无关；Muse 是 Meta 的商标。基于 DeepSeek Harness 构建，DeepSeek Harness 是 DeepSeek 的名称。"
      : "nanoMuse is a community project with no affiliation to Meta; Muse is a trademark of Meta. Built on DeepSeek Harness, a name of DeepSeek's.",
  ];
  void dialog.showMessageBox({
    type: "info",
    title: T.about,
    message: "nanoMuse",
    detail: lines.join("\n"),
    buttons: ["OK"],
    icon: nativeImage.createFromPath(iconPath()),
  });
}

function buildMenu(): void {
  const help: Electron.MenuItemConstructorOptions[] = [
    { label: T.website, click: () => void shell.openExternal("https://nanomuse.cn/") },
    { label: T.docs, click: () => void shell.openExternal(DOCS_PAGE) },
    { label: T.releases, click: () => void shell.openExternal(RELEASES_PAGE) },
    { label: T.issue, click: () => void shell.openExternal(ISSUES_PAGE) },
    { type: "separator" },
    { label: T.builtOn, click: () => void shell.openExternal(HARNESS_PAGE) },
    { label: T.openLogFolder, click: () => shell.showItemInFolder(join(harnessHome(), "desktop.log")) },
  ];
  // Linux and Windows: About, and a Quit with Ctrl+Q — the one way out that needs no tray.
  // With the menu-bar switch on, closing the window keeps the app in the tray, and on a
  // GNOME whose appindicator extension does not take Electron 44's registration (Ubuntu
  // 20.04: "org.freedesktop.StatusNotifierItem-<pid>-1/StatusNotifierItem/1" is not a bus
  // name to it) the tray icon never appears, so its Quit cannot be reached.
  if (process.platform !== "darwin") help.push({ type: "separator" }, { label: T.about, click: about }, { type: "separator" }, { label: T.quit, role: "quit", accelerator: "CmdOrCtrl+Q" });
  const template: Electron.MenuItemConstructorOptions[] = [
    ...(process.platform === "darwin"
      ? [
          {
            label: "nanoMuse",
            submenu: [
              { label: T.about, click: about },
              { type: "separator" },
              { role: "hide" },
              { role: "hideOthers" },
              { role: "unhide" },
              { type: "separator" },
              { role: "quit" },
            ],
          } as Electron.MenuItemConstructorOptions,
        ]
      : []),
    {
      label: T.edit,
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        { role: "selectAll" },
      ],
    },
    {
      label: T.view,
      submenu: [
        { label: T.reload, accelerator: "CmdOrCtrl+R", click: () => mainWindow?.webContents.reload() },
        { label: T.devtools, accelerator: process.platform === "darwin" ? "Alt+Cmd+I" : "Ctrl+Shift+I", click: () => mainWindow?.webContents.toggleDevTools() },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    { label: T.window, role: "windowMenu" },
    { label: T.help, submenu: help },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

if (!app.requestSingleInstanceLock({ version: app.getVersion() })) {
  app.quit();
} else {
  app.on("second-instance", (_e, _argv, _cwd, data) => {
    // the launcher clicked while this instance runs — with its window closed, too (the
    // tray case): showWindow() makes the window again when it is gone
    if (process.platform === "linux" && staleInstance(app.getVersion(), data)) {
      // Linux: a package upgrade (.deb) leaves the old copy running in the tray; the
      // launcher then starts the new binary, which only wakes the old one. Hand over.
      log(`second instance is ${(data as { version: string }).version}, this is ${app.getVersion()}: relaunching into the installed version`);
      app.relaunch();
      app.quit();
      return;
    }
    log(`second instance: ${mainWindow ? "focusing the window" : hostUrl ? "opening the window again" : "still starting"}`);
    showWindow();
  });
  app.setAboutPanelOptions({
    applicationName: "nanoMuse",
    applicationVersion: app.getVersion(),
    copyright: "GPL-3.0-or-later · the nanoMuse community · built on DeepSeek Harness (MIT)",
    website: "https://nanomuse.cn/",
  });
  app.whenReady().then(async () => {
    registerBridge();
    registerOverlays();
    buildMenu();
    prefs = readPrefs();
    applyPrefs();
    log(`nanoMuse Desktop ${app.getVersion()} starting (${process.platform} ${process.arch}, packaged=${app.isPackaged})`);
    if (operatorCheckFlag) {
      await operatorCheck(operatorCheckFlag);
      return;
    }
    if (!screenshotFlag) void ensureMacPermissionsAtLaunch().catch((exc: unknown) => log(`permissions: ${String(exc)}`));
    try {
      await boot();
    } catch (exc) {
      await reportStartupFailure(exc);
      app.quit();
    }
  });
  app.on("activate", () => {
    // the Dock icon on macOS: the window again when it was closed
    showWindow();
  });
  app.on("window-all-closed", () => {
    // The main window's own `closed` decides (mainWindowClosed): the Host keeps running on
    // macOS while the app is in the Dock, and on Linux and Windows while there is a tray.
    // This fires only when the overlays are gone too; the same rule applies.
    if (process.platform !== "darwin" && !tray) app.quit();
  });
  app.on("before-quit", (e) => {
    releaseAwake();
    globalShortcut.unregisterAll();
    if (quitting) return;
    quitting = true;
    if (startWatch) {
      // a Host still starting goes with the app; the log says it was alive
      log("quit: the host was still starting; stopping it");
      startWatch.dispose();
      startWatch = null;
    }
    if (child || operatorServer || macHelper?.running()) {
      e.preventDefault();
      void Promise.all([stopHost(), stopOperator()]).then(() => app.quit());
    }
  });
}
