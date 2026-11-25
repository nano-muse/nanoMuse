/**
 * Settings → nanoMuse Cloud: sign in with a code, see the account, the look it
 * gives the agent, this computer and the other devices on the hub, sign out.
 * Talks to the host half over the loopback API (`/nanomuse/cloud/*`) and reads
 * the live state the host streams.
 */
import { Button, Input, StateDot, Switch } from '@deepseek-ai/dsh-client-ui-primitives'
import { createElement as h, useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { call, column, errorStyle, muted, row, type CloudStatus, type Translate, failureText } from './api.ts'
import { AccountPage } from './AccountPage.tsx'
import { Avatar } from './Avatar.tsx'
import { settingsBus } from './bus.ts'
import { useLive, type LiveHub } from './live.ts'
import { DATA_SECTION, DEVICES_PANEL } from './panels.ts'
import { DataRows } from './Memory.tsx'
import { NetworkRows } from './Network.tsx'
import { OwnKeyPanel } from './OwnKey.tsx'
import { useRooms } from './rooms.ts'
import { SignIn } from './SignIn.tsx'

type Phase = 'loading' | 'signedOut' | 'signedIn'

/** Where the privacy policy is when the relay did not name one. */
const PRIVACY_URL = 'https://nanomuse.cn/privacy/'

/** `GET nanomuse/cloud/sync/state`: the switch, the relay's counts, the main chat and the synced sessions (see `sync.ts`). */
export interface SyncView {
  enabled: boolean
  /** "Also sync side chats" (contract C9), this device's setting. */
  sideChats: boolean
  available: boolean
  paused: boolean
  cursor: number
  relay: { enabled: boolean; cursor: number; counts: { conversations: number; messages: number } } | null
  rev: number
  mainSession: string
  sessions: string[]
  hidden: string[]
  toArchive: string[]
}

/**
 * Data controls, the first card (contract C7): *Sync conversations between my devices*, on by
 * default while signed in. Off tells the relay, which deletes what it stores; *Delete synced
 * conversations* empties the store and keeps the switch and the chats on every device. Under
 * it, *Also sync side chats* (C9): this device's own switch, off by default — off, only the
 * main conversation goes up and comes down.
 */
export function SyncControls({ t }: { t: Translate }): ReactNode {
  const [view, setView] = useState<SyncView | undefined>()
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | undefined>()
  const [error, setError] = useState<string | undefined>()
  useEffect(() => {
    let alive = true
    call<SyncView>('sync/state').then((v) => { if (alive) setView(v) }).catch(() => { if (alive) setError(t('syncNotReady')) })
    return () => { alive = false }
  }, [t])
  const run = async (work: () => Promise<SyncView>, said?: string) => {
    setBusy(true)
    setError(undefined)
    setNotice(undefined)
    try {
      setView(await work())
      if (said) setNotice(said)
    } catch (err: unknown) {
      setError(failureText(t, err))
    } finally {
      setBusy(false)
    }
  }
  const counts = view?.relay?.counts ?? { conversations: 0, messages: 0 }
  const stored = counts.conversations > 0 || counts.messages > 0
  const flip = (on: boolean) => {
    if (!on && stored && !window.confirm(t('syncOffConfirm'))) return
    void run(() => call<SyncView>('sync/state', { enabled: on }))
  }
  const flipSide = (on: boolean) => {
    void run(() => call<SyncView>('sync/state', { sideChats: on }))
  }
  const wipe = () => {
    if (!window.confirm(t('syncDeleteConfirm'))) return
    void run(() => call<SyncView>('sync/delete', {}), t('syncDeleted'))
  }
  return h('div', { 'data-testid': 'nm-sync-controls' },
    h('div', { style: { ...row, justifyContent: 'space-between' } },
      h('span', null, t('syncSwitch')),
      h(Switch, { checked: view?.enabled === true, onChange: flip, disabled: busy || !view, label: t('syncSwitch') })),
    h('div', { style: muted }, t('syncWhy'), ' ', view?.paused ? t('syncPaused') : stored ? t('syncKept', { c: counts.conversations, m: counts.messages }) : ''),
    h('div', { style: { ...row, justifyContent: 'space-between', marginTop: 8 }, 'data-testid': 'nm-sync-side' },
      h('span', null, t('syncSide')),
      h(Switch, { checked: view?.sideChats === true, onChange: flipSide, disabled: busy || !view || view.enabled !== true, label: t('syncSide') })),
    h('div', { style: muted }, t('syncSideWhy')),
    stored ? h('div', { style: { marginTop: 6 } }, h(Button, { variant: 'outline', size: 'sm', disabled: busy, onClick: wipe }, t('syncDelete'))) : null,
    notice ? h('div', { style: muted }, notice) : null,
    error ? h('div', { style: errorStyle }, error) : null)
}

/** Build the section component around the translator the plugin bound. */
/**
 * @param part - `account`: the account page (who is signed in, the models, the look, the
 * devices); `data`: the Data controls page alone — Muse keeps the two apart in its nav.
 */
export function makeCloudSection(t: Translate, part: 'account' | 'data' = 'account') {
  return function CloudSection(): ReactNode {
    const live = useLive()
    const rooms = useRooms()
    const [phase, setPhase] = useState<Phase>('loading')
    const [status, setStatus] = useState<CloudStatus | undefined>()
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState<string | undefined>()

    const apply = useCallback((next: CloudStatus) => {
      setStatus(next)
      setPhase(next.signedIn ? 'signedIn' : 'signedOut')
      setError(next.error ? failureText(t, next.error) : undefined)
    }, [])

    useEffect(() => {
      let alive = true
      call<CloudStatus>('status')
        .then((next) => { if (alive) apply(next) })
        .catch((err: unknown) => { if (alive) { setPhase('signedOut'); setError(failureText(t, err)) } })
      return () => { alive = false }
    }, [apply])

    const run = async (work: () => Promise<void>) => {
      setBusy(true)
      setError(undefined)
      try {
        await work()
      } catch (err: unknown) {
        setError(failureText(t, err))
      } finally {
        setBusy(false)
      }
    }
    const signOut = () => void run(async () => apply(await call<CloudStatus>('sign-out', {})))
    const refresh = () => void run(async () => apply(await call<CloudStatus>('refresh', {})))
    // a key saved or removed, a model picked: the status (ready, the models) is read again, quietly
    const refreshStatus = useCallback(() => { void call<CloudStatus>('status').then(apply).catch(() => undefined) }, [apply])
    const [notice, setNotice] = useState<string | undefined>()
    const setContribute = (on: boolean) => void run(async () => { setNotice(undefined); apply(await call<CloudStatus>('data/contribute', { on })) })
    const deleteSamples = () => {
      if (!window.confirm(t('dataDeleteConfirm'))) return
      void run(async () => {
        const next = await call<CloudStatus & { deleted: number }>('data/delete-samples', {})
        apply(next)
        setNotice(t('dataDeleted', { n: next.deleted }))
      })
    }

    const profile = live.streaming ? live.profile : status?.profile
    const header = h('div', { style: row },
      h(Avatar, { size: 44, profile, mood: phase === 'signedIn' ? 'happy' : 'idle' }),
      h('div', null,
        h('div', { style: { fontWeight: 600 } }, t('title')),
        h('div', { style: muted }, t('intro'))))

    if (phase === 'loading') {
      return h('section', { style: column }, header, h('div', { style: muted }, t('loading')))
    }

    if (phase === 'signedIn' && status?.account) {
      const a = status.account
      const look = profile ?? status.profile
      const lookWord = look.avatar === 'face' ? t('lookFace') : look.avatar === 'emoji' ? t('lookEmoji', { emoji: look.emoji }) : t('lookDragon')
      const dataControls = a.contribute
        ? h('div', null,
            h('div', { style: { ...row, justifyContent: 'space-between' } },
              h('span', null, t('dataImprove')),
              h(Switch, { checked: a.contribute.on, onChange: setContribute, disabled: busy, label: t('dataImprove') })),
            h('div', { style: muted },
              t('dataWhy'), ' ',
              a.contribute.defaultOn === undefined ? '' : t(a.contribute.defaultOn ? 'dataDefaultOn' : 'dataDefaultOff'), ' ',
              a.contribute.samples > 0 ? t('dataKept', { n: a.contribute.samples }) : '', ' ',
              h('a', { href: a.contribute.privacyUrl || PRIVACY_URL, target: '_blank', rel: 'noopener noreferrer' }, t('dataPrivacy'))),
            // the record's figures (relay 0.29): what is held of this account, own-key turns among it
            a.contribute.record?.on
              ? h('div', { style: muted }, a.contribute.record.turns > 0
                  ? t('dataRecordHeld', { n: a.contribute.record.turns, own: a.contribute.record.own, files: a.contribute.record.files })
                  : t('dataRecordEmpty'), ' ',
                  a.contribute.record.keepDays > 0 ? t('dataRecordKeepDays', { days: a.contribute.record.keepDays }) : t('dataRecordKeepForever'))
              : null,
            // the record (relay 0.29) is kept whether or not any training turn is: the delete is always there
            h('div', { style: { marginTop: 6 } }, h(Button, { variant: 'outline', size: 'sm', disabled: busy, onClick: deleteSamples }, t('dataDelete'))),
            notice ? h('div', { style: muted }, notice) : null)
        : h('div', { style: muted }, t('dataOlderRelay'))
      if (part === 'data') {
        return h('section', { style: { ...column, maxWidth: 560 } },
          h('div', { className: 'nm-card', style: { padding: '14px 16px' } },
            h('div', { style: { fontWeight: 600, marginBottom: 4 } }, t('dataPrivacyTitle')),
            h('div', { style: muted }, t('dataPrivacyText'), ' ',
              h('a', { href: a.contribute?.privacyUrl || PRIVACY_URL, target: '_blank', rel: 'noopener noreferrer' }, t('dataPrivacy')))),
          h(SyncControls, { t }),
          dataControls,
          error ? h('div', { style: errorStyle }, error) : null,
          h('h3', { style: heading }, t('dataLocalTitle')),
          h(DataRows, { t }))
      }
      return h('section', { style: { ...column, maxWidth: 560 } },
        header,
        h('div', null, t('signedInAs', { hint: a.hint, channel: t(a.channel === 'phone' ? 'phone' : 'email') }), a.member ? ` · ${t('member')}` : ''),
        // The pickers and the "ways on" (C11): the account's models and each own row's in one
        // chooser, the account's row first, then the catalogue grouped for the region.
        h(OwnKeyPanel, { t, onChanged: refreshStatus }),
        // The proxy for the providers (the shell's setting; drawn inside nanoMuse Desktop only).
        h(NetworkRows, { t }),
        // The account as the phone shows it — the pool in yuan, the ways on, invite, usage,
        // password, devices holding a key, the timeline, deletion — read live from the relay.
        h(AccountPage, { t, status, locale: rooms.lang, onEnded: apply }),
        h('h3', { style: heading }, t('lookTitle')),
        h('div', { style: muted }, look.rev > 0 ? t('lookFrom', { name: look.name, look: lookWord }) : t('lookDefault')),
        h('h3', { style: heading }, t('devicesTitle')),
        h('div', { style: muted }, t('devicesSummary', { n: (live.streaming ? live.hub : status.hub).devices.filter((d) => d.kind !== 'web').length }), ' ',
          h(Button, { variant: 'ghost', size: 'sm', onClick: () => { settingsBus.openSection?.(DEVICES_PANEL) } }, t('devicesOpen'))),
        // Data controls live on their own page (the Help-improve switch is there and nowhere
        // else); the account page only points at it.
        h('h3', { style: heading }, t('dataTitle')),
        h('div', { style: muted }, t('dataOnAccount'), ' ',
          h(Button, { variant: 'ghost', size: 'sm', onClick: () => { settingsBus.openSection?.(DATA_SECTION) } }, t('dataOpen'))),
        error ? h('div', { style: errorStyle }, error) : null,
        h('div', { style: row },
          h(Button, { variant: 'outline', size: 'sm', disabled: busy, onClick: refresh }, t('refresh')),
          h(Button, { variant: 'ghost', size: 'sm', disabled: busy, onClick: signOut }, busy ? t('signingOut') : t('signOut'))),
        h('div', { style: muted }, t('relay', { baseURL: status.baseURL })))
    }

    if (part === 'data') return h('section', { style: { ...column, maxWidth: 560 } }, h('div', { style: muted }, t('dataSignedOut')), h('h3', { style: heading }, t('dataLocalTitle')), h(DataRows, { t }))
    return h('section', { style: { ...column, maxWidth: 560 } },
      header,
      error ? h('div', { style: errorStyle }, error) : null,
      h(SignIn, { t, onSignedIn: apply, footer: status ? h('div', { style: muted }, t('relay', { baseURL: status.baseURL })) : null }),
      // Signed out, the own keys are still the person's (C11): the same pickers and rows, so a key
      // can be changed or the ChatGPT sign-in redone without an account.
      h(OwnKeyPanel, { t, onChanged: refreshStatus }),
      h(NetworkRows, { t }))
  }
}

const heading: Record<string, string | number> = { fontSize: 14, fontWeight: 600, margin: '8px 0 0' }
const deviceRow: Record<string, string | number> = { display: 'flex', gap: 10, alignItems: 'center', padding: '6px 0', fontSize: 13 }

interface DevicesProps {
  t: Translate
  hub: LiveHub
}

/** This computer on the account, and the others, with online dots. */
export function Devices({ t, hub }: DevicesProps): ReactNode {
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(hub.deviceName)
  const [switching, setSwitching] = useState(false)
  const others = hub.devices.filter((d) => d.id !== hub.deviceId && d.kind !== 'web')

  const rename = (event: FormEvent) => {
    event.preventDefault()
    void call('devices/rename', { name }).then(() => setRenaming(false)).catch(() => undefined)
  }
  const setRemote = (on: boolean) => {
    setSwitching(true)
    void call('devices/remote-control', { on }).catch(() => undefined).finally(() => setSwitching(false))
  }

  return h('div', null,
    h('div', { style: deviceRow },
      h(StateDot, { state: hub.connected ? 'done' : 'idle', size: 10 }),
      renaming
        ? h('form', { style: { ...row, flex: 1 }, onSubmit: rename },
            h(Input, { value: name, onChange: (e: FormEvent<HTMLInputElement>) => setName(e.currentTarget.value), maxLength: 60, autoFocus: true, 'aria-label': t('deviceName') }),
            h(Button, { variant: 'primary', size: 'sm', type: 'submit', disabled: !name.trim() }, t('save')),
            h(Button, { variant: 'ghost', size: 'sm', type: 'button', onClick: () => setRenaming(false) }, t('cancel')))
        : h('span', { style: { flex: 1 } }, h('strong', null, hub.deviceName), ' · ', t('thisComputer'), ' · ', hub.connected ? t('hubConnected') : (hub.lastError ? t('hubOffline', { reason: hub.lastError }) : t('hubConnecting'))),
      renaming ? null : h(Button, { variant: 'ghost', size: 'sm', onClick: () => { setName(hub.deviceName); setRenaming(true) } }, t('rename'))),
    h('div', { style: { ...deviceRow, paddingLeft: 20 } },
      h('span', { style: { flex: 1 } },
        h('div', null, t('remoteControl')),
        h('div', { style: muted }, hub.remoteControl ? t('remoteControlOn') : t('remoteControlOff'))),
      h(Switch, { checked: hub.remoteControl, onChange: setRemote, disabled: switching, label: t('remoteControl') })),
    others.length === 0
      ? h('div', { style: muted }, t('devicesNone'))
      : others.map((d) =>
          h('div', { key: d.id, style: deviceRow },
            h(StateDot, { state: d.online ? 'done' : 'idle', size: 10 }),
            h('span', { style: { flex: 1 } }, h('strong', null, d.name), ' · ', t(d.kind === 'phone' ? 'kindPhone' : 'kindComputer'), d.os ? ` · ${d.os}` : '', ' · ', d.online ? t('online') : t('offline')),
            d.online ? null : h(Button, { variant: 'ghost', size: 'sm', onClick: () => void call('devices/forget', { device_id: d.id }).catch(() => undefined) }, t('forget')))),
    h('div', { style: { ...muted, marginTop: 6 } }, t('devicesHint')))
}

