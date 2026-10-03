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

export type PermissionKind = "accessibility" | "screen" | "microphone";
export type PermissionState = "granted" | "denied" | "not-determined" | "not-needed";

const bridge = {
  /** `darwin`, `win32`, `linux`. */
  platform: process.platform,
  /** The app's version, its platform and arch. */
  info: (): Promise<{ version: string; platform: string; arch: string }> => ipcRenderer.invoke("nanomuse:info"),
  /** Where every permission the hands use stands right now. */
  permissions: (): Promise<Record<PermissionKind, PermissionState>> => ipcRenderer.invoke("nanomuse:permissions"),
  /** Ask the system for one permission (its own dialog, or the Settings pane); the new state. */
  requestPermission: (kind: PermissionKind): Promise<PermissionState> => ipcRenderer.invoke("nanomuse:permissions:request", kind),
  /** Open the System Settings pane for one permission (macOS); a no-op elsewhere. */
  openPermissionSettings: (kind: PermissionKind): Promise<void> => ipcRenderer.invoke("nanomuse:permissions:settings", kind),
  /** Open an http(s) link in the default browser. */
  openExternal: (url: string): Promise<void> => ipcRenderer.invoke("nanomuse:open-external", url),
  /** Keep the display awake (while the agent works the computer). */
  keepAwake: (on: boolean): Promise<void> => ipcRenderer.invoke("nanomuse:keep-awake", on),
  /** Tell the window which theme the page shows, so its base colour matches on resize. */
  setTheme: (theme: "light" | "dark"): Promise<void> => ipcRenderer.invoke("nanomuse:theme", theme),
  /** App behaviour (open at login, menu bar icon, quick-chat key): the values, the key's name, what this platform can do. */
  prefs: (): Promise<DesktopPrefs> => ipcRenderer.invoke("nanomuse:prefs"),
  /** Change some of it; the shell applies it at once and answers with the whole. */
  setPrefs: (patch: Partial<Pick<DesktopPrefs, "openAtLogin" | "menuBar" | "quickChat" | "quickChatKey">>): Promise<DesktopPrefs> => ipcRenderer.invoke("nanomuse:prefs:set", patch),
  /** A screenshot of the window to Downloads and the issue page with the build's facts filled in. */
  reportBug: (): Promise<{ screenshot: string; url: string }> => ipcRenderer.invoke("nanomuse:report-bug"),
  /** Show a file in the system's file manager. */
  reveal: (path: string): Promise<void> => ipcRenderer.invoke("nanomuse:reveal", path),
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
