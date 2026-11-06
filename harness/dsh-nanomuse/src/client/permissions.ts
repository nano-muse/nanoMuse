/**
 * One reading of the system permissions the hands use, shared by the onboarding
 * slides, the Computer-use page, the Permissions summary and the Dictation page,
 * so that every place says the same thing at the same moment.
 *
 * The system's word is re-read on a timer, when the window gets focus and when
 * the page becomes visible again — the person flips a switch in System Settings
 * and comes back, and the row must already show the check. Where nothing is
 * gated (Linux, Windows) every permission reads `not-needed`, which the rows
 * show as granted, and no Allow button is offered.
 *
 * Two things the system does not tell and the hook remembers for the copy:
 * which permissions the person already asked for in this session (the button
 * then says "Open System Settings" — a second press cannot bring the dialog
 * back), and whether Screen Recording was granted while the app ran: macOS
 * applies that one only to freshly started processes, so the runtime that takes
 * the screenshots has to be started again (`needsRelaunch`).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { call, type Translate } from './api.ts'
import { bridge, gatedPermissions, type PermissionKind, type PermissionState } from './bridge.ts'
import { useLive } from './live.ts'
import { relaunchHands } from './RelaunchButton.tsx'

export type PermissionStates = Partial<Record<PermissionKind, PermissionState>>

export interface Permissions {
  states: PermissionStates
  /** Ask the system (its own dialog, or the Settings pane). */
  allow(kind: PermissionKind): void
  /** Open the System Settings pane for one permission (macOS). */
  settings(kind: PermissionKind): void
  /** Granted here or not gated on this system. */
  granted(kind: PermissionKind): boolean
  /** Asked for during this session (and still not granted): the button offers the pane. */
  asked(kind: PermissionKind): boolean
  /** Screen Recording was granted while the app ran; the runtime must start again to see it. */
  needsRelaunch: boolean
  /** Quit and start again (the desktop shell — the helper alone when it is in use), or nothing elsewhere. */
  relaunch(): Promise<boolean | void>
  /**
   * The shell's helper app, "nanoMuse Computer Use", holds the grants (macOS, 0.1.38+): the
   * panes list it, not nanoMuse Desktop, and the shell restarts it by itself when Screen
   * Recording lands — so `needsRelaunch` stays false.
   */
  helper: boolean
  /** When the system was last asked (ms); 0 before the first reading. The rows can say the status is live. */
  lastCheck: number
  /**
   * The hands saw an all-black screen (the host noticed it on a `computer_*` call or a test
   * screenshot): Screen Recording is missing for the app, or was granted after it started.
   * A relaunch is what fixes the second case; the notice stays until one or `clearBlackScreen`.
   */
  blackScreen: boolean
  clearBlackScreen(): void
}

const POLL_MS = 1500

export function isGranted(state: PermissionState | undefined): boolean {
  return state === 'granted' || state === 'not-needed'
}

/**
 * What the two hands rows are called: macOS's grants where the system gates them
 * (Accessibility, Screen Recording); elsewhere there is nothing to grant and the rows stand
 * for what they are — the screen, and the mouse and keyboard.
 */
export function permissionTitle(t: Translate, kind: 'accessibility' | 'screen', gated = gatedPermissions()): string {
  if (gated) return t(kind === 'screen' ? 'obScreen' : 'obAccessibility')
  return t(kind === 'screen' ? 'cuScreenRow' : 'cuInputRow')
}

export function permissionSub(t: Translate, kind: 'accessibility' | 'screen', name: string, gated = gatedPermissions()): string {
  if (gated) return t(kind === 'screen' ? 'obScreenSub' : 'obAccessibilitySub', { name })
  return t(kind === 'screen' ? 'cuScreenRowSub' : 'cuInputRowSub', { name })
}

export function usePermissions(kinds: PermissionKind[]): Permissions {
  const gated = gatedPermissions()
  const [states, setStates] = useState<PermissionStates>(() =>
    gated ? {} : Object.fromEntries(kinds.filter((k) => k !== 'microphone' || bridge() !== undefined).map((k) => [k, 'not-needed' as PermissionState])))
  const [askedKinds, setAskedKinds] = useState<PermissionKind[]>([])
  const [needsRelaunch, setNeedsRelaunch] = useState(false)
  const [helper, setHelper] = useState(false)
  const [lastCheck, setLastCheck] = useState(0)
  const live = useLive()
  // the first reading of Screen Recording in this session: only a later change to granted
  // means the running processes missed it
  const firstScreen = useRef<PermissionState | undefined>()
  const refresh = useCallback(() => {
    if (!gated) return
    void bridge()?.permissions().then((next) => {
      const { helper: viaHelper, ...rest } = next
      if (firstScreen.current === undefined) firstScreen.current = next.screen
      // with the helper the shell restarts it by itself; nothing for the person to do
      else if (firstScreen.current !== 'granted' && next.screen === 'granted' && viaHelper !== true) setNeedsRelaunch(true)
      setHelper(viaHelper === true)
      setStates(rest)
      setLastCheck(Date.now())
    }).catch(() => undefined)
  }, [gated])
  const clearBlackScreen = useCallback(() => {
    void call('hands/black-screen/clear', {}).catch(() => undefined)
  }, [])
  useEffect(() => {
    refresh()
    if (!gated) return undefined
    const timer = window.setInterval(refresh, POLL_MS)
    const onFocus = () => refresh()
    const onVisible = () => { if (document.visibilityState === 'visible') refresh() }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [gated, refresh])
  const allow = useCallback((kind: PermissionKind) => {
    const b = bridge()
    setAskedKinds((s) => (s.includes(kind) ? s : [...s, kind]))
    if (b) {
      void b.requestPermission(kind).then((state) => setStates((s) => ({ ...s, [kind]: state }))).catch(() => undefined)
    } else if (kind === 'microphone' && navigator.mediaDevices?.getUserMedia) {
      // the browser: the page's own prompt
      navigator.mediaDevices.getUserMedia({ audio: true })
        .then((stream) => { stream.getTracks().forEach((track) => track.stop()); setStates((s) => ({ ...s, microphone: 'granted' })) })
        .catch(() => setStates((s) => ({ ...s, microphone: 'denied' })))
    }
  }, [])
  const settings = useCallback((kind: PermissionKind) => { void bridge()?.openPermissionSettings(kind) }, [])
  const relaunch = useCallback(async () => {
    const completed = await relaunchHands()
    if (completed === true) {
      setNeedsRelaunch(false)
      refresh()
    }
    return completed
  }, [refresh])
  return {
    states,
    allow,
    settings,
    granted: (kind) => isGranted(states[kind]),
    asked: (kind) => askedKinds.includes(kind) && !isGranted(states[kind]),
    needsRelaunch,
    relaunch,
    helper,
    lastCheck,
    blackScreen: live.blackScreenAt > 0,
    clearBlackScreen,
  }
}
