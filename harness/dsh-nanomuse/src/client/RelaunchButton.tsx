import { createElement as h, Fragment, useRef, useState, type ReactNode } from 'react'
import { call, type Translate } from './api.ts'
import { bridge } from './bridge.ts'
import { IconRefresh } from './icons.tsx'

/** Old shells acknowledge before restarting, so only an explicit success clears the notice. */
export async function relaunchHands(): Promise<boolean | void> {
  const desktop = bridge()
  if (!desktop?.relaunch) return false
  const completed = await desktop.relaunch()
  if (completed === true) await call('hands/black-screen/clear', {}).catch(() => undefined)
  return completed
}

/** The same pending and failure feedback in settings, onboarding and the floating capsule. */
export function RelaunchButton({ t, relaunch, label }: {
  t: Translate
  relaunch(): Promise<boolean | void>
  label: string
}): ReactNode {
  const pending = useRef(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const [error, setError] = useState('')
  const restart = async () => {
    if (pending.current) return
    pending.current = true
    setBusy(true)
    setFailed(false)
    setError('')
    try {
      setFailed(await relaunch() === false)
    } catch (exc) {
      setFailed(true)
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      pending.current = false
      setBusy(false)
    }
  }
  return h(Fragment, null,
    h('button', { type: 'button', className: 'nm-pill nm-pill-sm', disabled: busy, onClick: () => void restart() },
      h(IconRefresh, { size: 14 }), ' ', busy ? t('pmRelaunchRunning') : label),
    failed ? h('span', { className: 'nm-hc-bad nm-wrap', role: 'alert' }, error ? t('pmRelaunchFailedReason', { error }) : t('pmRelaunchFailed')) : null)
}
