/**
 * The one bridge between the harness's web client and the Electron shell. The
 * nanoMuse client bundle looks for `window.nanomuseHarness`; in a plain
 * browser (dsh on its own) it is absent and the bundle shows nothing that
 * needs it. Everything here is a request to the main process — the renderer
 * stays sandboxed with no Node access of its own.
 *
 * What goes through: the system permissions the hands need (macOS asks for
 * Accessibility and Screen Recording — the first-run flow shows them with an
 * Allow button, like the Muse desktop's), the System Settings panes, opening a
 * link in the person's browser, keeping the screen awake while the agent works,
 * and the window's base colour following the theme.
 */
import { contextBridge, ipcRenderer } from "electron";
import type { WindowsUpdateState } from "./windows-updates";

export type PermissionKind = "accessibility" | "screen" | "microphone";
export type PermissionState = "granted" | "denied" | "not-determined" | "not-needed";

const bridge = {
  /** `darwin`, `win32`, `linux`. */
  platform: process.platform,
  /** One Windows update state for the menu and settings; null in unsupported builds. */
  updates: {
    snapshot: (): Promise<WindowsUpdateState | null> => ipcRenderer.invoke("nanomuse:updates:snapshot"),
    check: (): Promise<WindowsUpdateState | null> => ipcRenderer.invoke("nanomuse:updates:check"),
    download: (): Promise<WindowsUpdateState | null> => ipcRenderer.invoke("nanomuse:updates:download"),
    restart: (): Promise<WindowsUpdateState | null> => ipcRenderer.invoke("nanomuse:updates:restart"),
    setAutoDownload: (enabled: boolean): Promise<WindowsUpdateState | null> => ipcRenderer.invoke("nanomuse:updates:auto-download", enabled),
    subscribe: (listener: (state: WindowsUpdateState) => void): (() => void) => {
      const handler = (_event: Electron.IpcRendererEvent, state: WindowsUpdateState) => listener(state);
      ipcRenderer.on("nanomuse:updates:state", handler);
      return () => ipcRenderer.off("nanomuse:updates:state", handler);
    },
  },
  /** The app's version, its platform and arch; `appImage` when the Linux build runs from an AppImage (so an update is offered as one). */
  info: (): Promise<{ version: string; platform: string; arch: string; appImage: boolean }> => ipcRenderer.invoke("nanomuse:info"),
  /** Where every permission the hands use stands right now; `helper` (0.1.38) when "nanoMuse Computer Use" holds them — the rows to switch on are its, and a grant needs no app restart. */
  permissions: (): Promise<Record<PermissionKind, PermissionState> & { helper?: boolean }> => ipcRenderer.invoke("nanomuse:permissions"),
  /** Ask the system for one permission (its own dialog, or the Settings pane); the new state. */
  requestPermission: (kind: PermissionKind): Promise<PermissionState> => ipcRenderer.invoke("nanomuse:permissions:request", kind),
  /** Open the System Settings pane for one permission (macOS); a no-op elsewhere. */
  openPermissionSettings: (kind: PermissionKind): Promise<void> => ipcRenderer.invoke("nanomuse:permissions:settings", kind),
  /** Quit and start again (after a permission macOS applies only to new processes). */
  relaunch: (): Promise<boolean> => ipcRenderer.invoke("nanomuse:relaunch"),
  /** Open an http(s) link in the default browser. */
  openExternal: (url: string): Promise<void> => ipcRenderer.invoke("nanomuse:open-external", url),
  /** Keep the display awake (while the agent works the computer). */
  keepAwake: (on: boolean): Promise<void> => ipcRenderer.invoke("nanomuse:keep-awake", on),
  /** Tell the window which theme the page shows, so its base colour matches on resize. */
  setTheme: (theme: "light" | "dark"): Promise<void> => ipcRenderer.invoke("nanomuse:theme", theme),
  /** App behaviour (open at login, menu bar icon, quick-chat key): the values, the key's name, what this platform can do. */
  prefs: (): Promise<DesktopPrefs> => ipcRenderer.invoke("nanomuse:prefs"),
  /** Change some of it; the shell applies it at once and answers with the whole. */
  setPrefs: (patch: Partial<Pick<DesktopPrefs, "openAtLogin" | "menuBar" | "quickChat" | "quickChatKey" | "proxy" | "relayHosts">>): Promise<DesktopPrefs> => ipcRenderer.invoke("nanomuse:prefs:set", patch),
  // since 0.1.41
  /** Stop the Host and start it again with the window up: the Network row's *Restart now*, so a proxy just set applies. */
  restartHost: (): Promise<void> => ipcRenderer.invoke("nanomuse:restart-host"),
  /** A screenshot of the window to Downloads and the issue page with the build's facts filled in. */
  reportBug: (): Promise<{ screenshot: string; url: string }> => ipcRenderer.invoke("nanomuse:report-bug"),
  /** Show a file in the system's file manager. */
  reveal: (path: string): Promise<void> => ipcRenderer.invoke("nanomuse:reveal", path),
  // since 0.1.34
  /** The macOS permissions, asked for in order with a word on why; answers with what is granted now. */
  guidePermissions: (): Promise<Record<PermissionKind, PermissionState>> => ipcRenderer.invoke("nanomuse:permissions:guide"),
  /** Keep this window out of screenshots while the hands work. */
  setContentProtection: (on: boolean): Promise<void> => ipcRenderer.invoke("nanomuse:content-protection", on),
  /** What the overlays show: the hands' pointer for the glow window; the step, its words, the face and the buttons for the capsule, with the cards. */
  setOverlay: (state: { hands: { active: boolean; held: boolean; x: number; y: number; kind: string; step: number; title: string; text: string; face: string; stop: string; take: string } | null; cards: { id: string; kind: "approval" | "hold"; title: string; text: string; actions: { id: string; label: string; tone?: "on" | "no" }[] }[] }): void => ipcRenderer.send("nanomuse:overlay", state),
  /** A button pressed on the capsule window. */
  onOverlayAction: (listener: (card: string, action: string) => void): (() => void) => {
    const handler = (_e: Electron.IpcRendererEvent, payload: { card: string; action: string }) => listener(payload.card, payload.action);
    ipcRenderer.on("nanomuse:overlay:action", handler);
    return () => ipcRenderer.off("nanomuse:overlay:action", handler);
  },
  /** The quick-chat key was pressed (or the menu bar's New chat): start a chat and focus the composer. */
  onQuickChat: (listener: () => void): (() => void) => {
    const handler = () => listener();
    ipcRenderer.on("nanomuse:quick-chat", handler);
    return () => ipcRenderer.off("nanomuse:quick-chat", handler);
  },
};

export interface DesktopPrefs {
  openAtLogin: boolean;
  menuBar: boolean;
  quickChat: boolean;
  /** The combination in force, an Electron accelerator (`Alt+Space`); set it to change, to "" for the default. */
  quickChatKey: string;
  quickChatDefault: string;
  /** Another app holds the combination, so nanoMuse did not get it. */
  quickChatTaken: boolean;
  // since 0.1.41: the proxy for the model providers
  /** The address as kept (`http://host:port`, `socks5://host:port`); "" for none. Set it to change, to "" to remove. */
  proxy: string;
  /** The same with `user:pass@` hidden, for the screen. */
  proxyMasked: string;
  /** The proxy the running Host was started with; differs from `proxy` until a restart. */
  proxyApplied: string;
  /** The relay hosts the plugin talks to (its `config.baseURL`): kept on NO_PROXY together with the default relay. */
  relayHosts?: string[];
  supports: { openAtLogin: boolean; menuBar: boolean; quickChat: boolean };
}

export type NanomuseHarnessBridge = typeof bridge;

contextBridge.exposeInMainWorld("nanomuseHarness", bridge);

// The window has no title bar on macOS (the traffic lights sit over the rail, as in
// Muse's window), so the page marks the platform on the document and the nanoMuse
// bundle adds the clearance and the drag regions; full screen drops the clearance.
// (The harness's own `data-platform` is not used: it would expect the harness's
// desktop keyboard bridge.)
const mark = () => {
  document.documentElement.dataset.nmPlatform = process.platform;
};
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mark, { once: true });
else mark();
ipcRenderer.on("nanomuse:fullscreen", (_event, on: boolean) => {
  if (on) document.documentElement.setAttribute("data-nm-fullscreen", "");
  else document.documentElement.removeAttribute("data-nm-fullscreen");
});
