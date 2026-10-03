/**
 * The Electron shell's bridge, when the page runs inside nanoMuse Desktop
 * (`harness/desktop/src/preload.ts` puts it on `window`). In a browser, or in
 * dsh's own desktop, it is absent and every caller here falls back to what a
 * web page can do: nothing for the system permissions, `window.open` for links.
 */

export type PermissionKind = 'accessibility' | 'screen' | 'microphone'
export type PermissionState = 'granted' | 'denied' | 'not-determined' | 'not-needed'

/** App behaviour, as the shell keeps it: the values, the quick-chat key's name, what this platform can do. */
export interface DesktopPrefs {
  openAtLogin: boolean
  menuBar: boolean
  quickChat: boolean
  /** The combination in force, an Electron accelerator (`Alt+Space`). */
  quickChatKey: string
  // since 0.1.32 — absent in older shells, which take no key of the person's
  quickChatDefault?: string
  /** Another app holds the combination, so nanoMuse did not get it. */
  quickChatTaken?: boolean
  supports: { openAtLogin: boolean; menuBar: boolean; quickChat: boolean }
}

export interface HarnessBridge {
  platform: string
  info(): Promise<{ version: string; platform: string; arch: string }>
  permissions(): Promise<Record<PermissionKind, PermissionState>>
  requestPermission(kind: PermissionKind): Promise<PermissionState>
  openPermissionSettings(kind: PermissionKind | 'files'): Promise<void>
  openExternal(url: string): Promise<void>
  keepAwake(on: boolean): Promise<void>
  setTheme(theme: 'light' | 'dark'): Promise<void>
  // since 0.1.30 — absent in older shells
  prefs?(): Promise<DesktopPrefs>
  setPrefs?(patch: Partial<Pick<DesktopPrefs, 'openAtLogin' | 'menuBar' | 'quickChat' | 'quickChatKey'>>): Promise<DesktopPrefs>
  reportBug?(): Promise<{ screenshot: string; url: string }>
  reveal?(path: string): Promise<void>
  onQuickChat?(listener: () => void): () => void
}

export function bridge(): HarnessBridge | undefined {
  const candidate = (globalThis as { nanomuseHarness?: HarnessBridge }).nanomuseHarness
  return candidate && typeof candidate.permissions === 'function' ? candidate : undefined
}

/** Whether the system gates the hands' permissions here (macOS under the Electron shell). */
export function gatedPermissions(): boolean {
  return bridge()?.platform === 'darwin'
}

/** Open a link the way the shell prefers: the person's browser, never a window of ours. */
export function openLink(url: string): void {
  const b = bridge()
  if (b) void b.openExternal(url)
  else window.open(url, '_blank', 'noopener')
}

/**
 * The Electron accelerator a key press stands for, or nothing when it cannot be one: a
 * modifier alone, a key without a modifier (function keys excepted), a key we do not name.
 */
export function acceleratorOf(e: { code: string; key: string; ctrlKey: boolean; altKey: boolean; shiftKey: boolean; metaKey: boolean }, platform = bridge()?.platform ?? ''): string | undefined {
  const mods: string[] = []
  if (e.ctrlKey) mods.push('Ctrl')
  if (e.altKey) mods.push('Alt')
  if (e.shiftKey) mods.push('Shift')
  if (e.metaKey) mods.push(platform === 'darwin' ? 'Cmd' : 'Super')
  const named: Record<string, string> = { Space: 'Space', Tab: 'Tab', Backspace: 'Backspace', Delete: 'Delete', Insert: 'Insert', Enter: 'Return', NumpadEnter: 'Return', ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left', ArrowRight: 'Right', Home: 'Home', End: 'End', PageUp: 'PageUp', PageDown: 'PageDown', Comma: ',', Period: '.', Slash: '/', Semicolon: ';', Quote: "'", BracketLeft: '[', BracketRight: ']', Backslash: '\\', Minus: '-', Equal: '=', Backquote: '`' }
  const code = e.code
  const key = /^Key[A-Z]$/.test(code) ? code.slice(3) : /^Digit[0-9]$/.test(code) ? code.slice(5) : /^F([1-9]|1[0-9]|2[0-4])$/.test(code) ? code : named[code]
  if (!key) return undefined
  if (!mods.length && !/^F\d+$/.test(key)) return undefined
  return [...mods, key].join('+')
}

/** `⌥ Space`-style words for an Electron accelerator. */
export function keyLabel(accelerator: string, platform = bridge()?.platform ?? ''): string {
  const mac = platform === 'darwin'
  const names: Record<string, string> = { Alt: mac ? '⌥' : 'Alt', Ctrl: mac ? '⌃' : 'Ctrl', Control: mac ? '⌃' : 'Ctrl', Shift: mac ? '⇧' : 'Shift', Cmd: '⌘', Command: '⌘', CmdOrCtrl: mac ? '⌘' : 'Ctrl', Super: mac ? '⌘' : 'Win', Space: mac ? 'Space' : 'Space' }
  return accelerator.split('+').map((k) => names[k] ?? k).join(mac ? ' ' : '+')
}
