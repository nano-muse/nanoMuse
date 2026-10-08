/**
 * About nanoMuse and the version (C2). The installed line reads
 * "nanoMuse Desktop <app> · harness <bundle>": the app's number from the Electron
 * shell (`nanomuse:info`), the bundle's from package.json at build time. The host
 * reads the latest release from nanomuse.cn's index (GitHub when the index is out of
 * reach), compares, and the second line says "0.1.x is out" with Update — the
 * installer for this computer — or "Latest 0.1.x — you have it". The host checks once
 * a day by itself; the result puts a dot on ••• and an "Update to 0.1.x" row in the menu.
 */
import { createElement as h, Fragment, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { pickAsset } from '../desk.ts'
import { call, type Translate } from './api.ts'
import { bridge, openLink } from './bridge.ts'
import { useLive, type UpdateInfo } from './live.ts'
import { openStar } from './AccountPage.tsx'
import { DOCS_URL, ISSUES_URL, REPO_URL } from './panels.ts'
import { Sheet } from './ui.tsx'

export const RELEASES_URL = 'https://github.com/nano-muse/nanoMuse/releases'

interface AppInfo {
  version: string
  platform: string
  arch: string
  /** The Linux build runs from an AppImage (shell 0.1.42); absent from older shells. */
  appImage?: boolean
}

let appInfo: AppInfo | undefined
let appInfoAsked = false
const infoListeners = new Set<() => void>()

/** The shell's version, platform and arch; undefined in a plain browser or until the shell answers. */
export function useAppInfo(): AppInfo | undefined {
  return useSyncExternalStore(
    (l) => {
      infoListeners.add(l)
      if (!appInfoAsked) {
        appInfoAsked = true
        void bridge()?.info().then((i) => { appInfo = i; for (const x of infoListeners) x() }).catch(() => undefined)
      }
      return () => infoListeners.delete(l)
    },
    () => appInfo,
    () => appInfo,
  )
}

/** "nanoMuse Desktop 0.1.34 · harness 0.1.34" under the shell; the bundle alone in a browser. */
export function versionLine(t: Translate, bundle: string, app: AppInfo | undefined): string {
  return app ? t('abVersionLine', { app: app.version || '—', bundle: bundle || '—' }) : t('abVersionBundle', { bundle: bundle || '—' })
}

/** The About sheet's open/close, for the ••• menu. */
export const aboutBus: { open?: (() => void) | undefined } = {}

export function useUpdateCheck(): { info: UpdateInfo | null; checking: boolean; check(): void } {
  const live = useLive()
  const [checking, setChecking] = useState(false)
  const [fresh, setFresh] = useState<UpdateInfo | null>(null)
  const check = () => {
    setChecking(true)
    call<UpdateInfo>('update?force=1').then(setFresh).catch(() => undefined).finally(() => setChecking(false))
  }
  return { info: fresh ?? live.update, checking, check }
}

/**
 * The version (C2), two lines that are always there: what is installed
 * ("nanoMuse Desktop 0.1.34 · harness 0.1.34"), and what the check found — "Checking…",
 * "Latest 0.1.35 — you have it", "0.1.35 is out" with Update, or "Could not check — Check
 * now". A check runs when the rows appear and nothing is known yet.
 */
let autoChecked = false

export function UpdateRow({ t, bundle }: { t: Translate; bundle: string }): ReactNode {
  const app = useAppInfo()
  const { info, checking, check } = useUpdateCheck()
  const asset = info && app ? pickAsset(info.assets, app.platform, app.arch, app.appImage === true) : undefined
  // nothing known yet (the host's daily check has not run): one check per window, on sight
  useEffect(() => { if (!info && !checking && !autoChecked) { autoChecked = true; check() } }, [info === null])
  const installed = app ? t('vrInstalled', { app: app.version || '—', bundle: bundle || '—' }) : t('abVersionBundle', { bundle: bundle || '—' })
  let found: ReactNode
  let action: ReactNode = null
  if (checking || !info) {
    found = t('vrChecking')
  } else if (info.source === 'none') {
    found = h(Fragment, null, t('vrFailed'), ' · ', h('button', { type: 'button', className: 'nm-ob-link nm-inline', onClick: check }, t('vrCheckNow')))
  } else if (info.newer) {
    found = t('vrOut', { version: info.latest })
    action = h('button', { type: 'button', className: 'nm-pill nm-pill-sm', onClick: () => openLink(asset?.url ?? info.page) }, t('vrUpdate'))
  } else {
    found = t('vrHave', { version: info.latest })
  }
  return h('div', { className: 'nm-row nm-version-row' },
    h('div', { className: 'nm-row-main' },
      h('span', { className: 'nm-row-title' }, t('vrTitle')),
      h('span', { className: 'nm-row-sub nm-version-line' }, installed),
      h('span', { className: 'nm-row-sub nm-version-line' }, found)),
    action)
}

export function makeAboutSheet(t: Translate, bundle: string) {
  return function AboutSheet(): ReactNode {
    const [open, setOpen] = useState(false)
    useEffect(() => {
      aboutBus.open = () => setOpen(true)
      return () => { aboutBus.open = undefined }
    }, [])
    if (!open) return null
    return h(Sheet, { title: t('aboutTitle'), onClose: () => setOpen(false), closeLabel: t('close') },
      h('p', { className: 'nm-fine' }, t('abLead')),
      h('div', { className: 'nm-card' },
        h(UpdateRow, { t, bundle }),
        h('div', { className: 'nm-row' },
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, t('legalLicense')),
            h('span', { className: 'nm-row-sub nm-wrap' }, t('legalLicenseText'))))),
      h('div', { className: 'nm-card' },
        // going to GitHub from here counts as the star being done: the asks stop (C1)
        link(t('gnStar'), REPO_URL, () => openStar(REPO_URL)),
        link(t('abReleases'), RELEASES_URL),
        link(t('abDocs'), DOCS_URL),
        link(t('abIssues'), ISSUES_URL)))
  }
}

function link(label: string, url: string, onClick: () => void = () => openLink(url)): ReactNode {
  return h('button', { type: 'button', className: 'nm-row nm-row-button', onClick },
    h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, label), h('span', { className: 'nm-row-sub' }, url.replace(/^https:\/\//, ''))))
}
