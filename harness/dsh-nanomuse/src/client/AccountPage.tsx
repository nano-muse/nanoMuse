/**
 * The account, as the phone and the web app show it: the pool in yuan with the two ways on
 * when it runs low (your own key, an invitation — and a star, once), the invite code, what was
 * used by kind and by model, the password, every device holding a key, the account's own
 * timeline, and the way out (this device, every device, the account itself). Everything here
 * is read from the relay through the host's pass-through routes (`/nanomuse/cloud/me`,
 * `/sessions`, `/account-events`, `/password`, …); nothing of it is kept on the computer.
 */
import { Button, Input } from '@deepseek-ai/dsh-client-ui-primitives'
import { createElement as h, Fragment, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { allowanceInfo, AllowanceWays, type Guidance } from './AllowanceWays.tsx'
import { call, errorStyle, muted, row, type CloudStatus, type Translate, failureText } from './api.ts'
import { openLink } from './bridge.ts'
import { settingsBus } from './bus.ts'
import { IconCopy, IconHeart } from './icons.tsx'
import { REPO_URL } from './panels.ts'
import { peekRooms, roomsCall, type NudgeAsk } from './rooms.ts'
import { starText } from '../nudges.ts'

/** `GET /v1/me`, the parts this page reads (every field optional: an older relay sends fewer). */
export interface AccountSheet {
  account?: { id?: string; channel?: string; hint?: string; member?: boolean; has_password?: boolean; sessions?: number; signed_in_via?: string; created_at?: number; region?: string }
  /** Where the account is, as the relay sees it (0.1.34): `cn` or `intl`. */
  region?: string
  spend?: { total?: number; grant?: number; left?: number | null; unlimited?: boolean; warn?: boolean; usd_cny?: number; invite_bonus_cny?: number; invitee_bonus_cny?: number; own_key_docs?: string; guidance?: Guidance }
  usage?: { today?: { by_kind?: UsageRow[] }; total?: { by_kind?: UsageRow[]; by_model?: UsageRow[] } }
  invite?: { code?: string; url?: string; invites?: number; bonus_cny?: number; invitee_bonus_cny?: number; earned_cny?: number }
}
export interface UsageRow { kind?: string; model?: string; requests?: number; prompt_tokens?: number; completion_tokens?: number; cost_cny?: number }
interface Session { prefix: string; device: string; via: string; created_at: number; last_used_at: number | null; current: boolean }
interface AccountEvent { ts: number; kind: string; detail: string }

/** `GET /v1/config` on the relay (0.15): the amounts a client prints before anyone signs in. */
export interface CloudConfig { version?: string; signup_open?: boolean; allowance_cny?: number; invite_bonus_cny?: number; invitee_bonus_cny?: number; star_url?: string }
let configCache: CloudConfig | undefined
let configPending: Promise<CloudConfig> | undefined
/** The relay's public config, fetched once per window; `{}` until it arrives or when the relay is older. */
export function useCloudConfig(): CloudConfig {
  const [config, setConfig] = useState<CloudConfig>(configCache ?? {})
  useEffect(() => {
    if (configCache) return
    configPending ??= call<CloudConfig>('config').then((c) => { configCache = c ?? {}; return configCache }).catch(() => ({} as CloudConfig))
    let alive = true
    void configPending.then((c) => { if (alive) setConfig(c) })
    return () => { alive = false }
  }, [])
  return config
}

const yuan = (n: number | undefined | null): string => (n === undefined || n === null ? '—' : `¥${n.toFixed(n % 1 === 0 ? 0 : 2)}`)
const when = (ts: number | null | undefined, locale: string): string => (ts ? new Date(ts * 1000).toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' }) : '—')

// ---- the star, asked for at the moments the policy names (C1) ----------------------------

/**
 * The host keeps the ledger and the gate (`nudges.json`, `src/nudges.ts`): how many tasks ran
 * to their end, the days the app was opened, how often a star was asked for and when. The
 * moments it cannot count itself — the account just signed in, a face just drawn, the
 * allowance used up, a goal reached — are asked for from here with `/nudges/ask`; the host
 * says yes once per cooldown and at most `max_asks` times, never after a star. The tone is a
 * thank-you, never a bill.
 */
export type StarMoment = 'signed_in' | 'new_look' | 'exhausted' | 'goal_done'
/** The app's own words for an ask the host granted, by its moment. */
function momentText(t: Translate, ask: NudgeAsk): string {
  switch (ask.moment) {
    case 'signed_in': return t('starSignedIn')
    case 'new_look': return t('starNewLook')
    case 'exhausted': return t('ndExhausted')
    case 'goal_done': return t('ndGoalDone')
    case 'tasks': return ask.n === 1 ? t('ndTasksOne') : t('ndTasks', { n: ask.n ?? 0 })
    case 'days_used': return ask.n === 7 ? t('ndWeek') : ask.n === 30 ? t('ndMonth') : t('ndDays', { n: ask.n ?? 0 })
  }
}
/**
 * The card's body sentence: the relay's, when its policy carries one (`star.text_zh` for a
 * Chinese UI, else `star.text`), else the app's own for the moment. The title and the buttons
 * are always the app's.
 */
export function nudgeText(t: Translate, ask: NudgeAsk): string {
  return starText(peekRooms().nudges.policy, t('langTag') === 'zh', momentText(t, ask))
}
/**
 * The star is done: the person went to GitHub from any "Star on GitHub" (a card or a Settings
 * row) or said "I already starred". The host writes `starred` and drops the current ask; no
 * ask comes back on this computer, whatever the cooldown and the asks left.
 */
export function markStarred(): void {
  void roomsCall('nudges/starred', {}).catch(() => undefined)
}
/** Off to GitHub (the policy's page), and no more asking anywhere. */
export function openStar(url?: string): void {
  markStarred()
  openLink(url || peekRooms().nudges.policy.star.url || REPO_URL)
}
/** "Not now": the host forgets the current ask. */
export function dismissStar(): void {
  void roomsCall('nudges/dismiss', {}).catch(() => undefined)
}

/** One card: the star, a line saying why, "Star on GitHub", "Not now" and "I already starred". */
export function StarNudge({ t, text, onDone }: { t: Translate; text: string; onDone(): void }): ReactNode {
  return h('div', { className: 'nm-star-card', role: 'note' },
    h('div', { className: 'nm-star-head' },
      h('span', { className: 'nm-star-icon' }, h(IconHeart, { size: 16 })),
      h('div', null,
        h('div', { className: 'nm-star-title' }, t('starTitle')),
        h('div', { className: 'nm-star-text' }, text))),
    h('div', { className: 'nm-star-actions' },
      h('button', { type: 'button', className: 'nm-pill nm-pill-sm', onClick: () => { openStar(); onDone() } }, t('starAction')),
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => { dismissStar(); onDone() } }, t('starLater')),
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => { markStarred(); onDone() } }, t('starDone'))))
}

/** The card for a moment, when the host grants the ask; asked once per mount, while `due`. */
export function StarNudgeOnce({ t, moment, text, due = true }: { t: Translate; moment: StarMoment; text?: string; due?: boolean }): ReactNode {
  const [ask, setAsk] = useState<NudgeAsk | null>(null)
  const asked = useRef(false)
  useEffect(() => {
    if (!due || asked.current) return
    asked.current = true
    let alive = true
    roomsCall<{ ask: NudgeAsk | null }>('nudges/ask', { moment })
      .then((r) => { if (alive && r.ask) setAsk(r.ask) })
      .catch(() => undefined)
    return () => { alive = false }
  }, [due, moment])
  if (!ask) return null
  // the relay's sentence first, then the caller's, then the moment's own
  return h(StarNudge, { t, text: starText(peekRooms().nudges.policy, t('langTag') === 'zh', text ?? momentText(t, ask)), onDone: () => setAsk(null) })
}

// ---- the page ------------------------------------------------------------------------------

interface AccountPageProps {
  t: Translate
  status: CloudStatus
  locale: string
  /** The host's status after a sign-out of every device or a deletion: the parent shows the sign-in again. */
  onEnded(status: CloudStatus): void
}

export function AccountPage({ t, status, locale, onEnded }: AccountPageProps): ReactNode {
  const [sheet, setSheet] = useState<AccountSheet | undefined>()
  const [sessions, setSessions] = useState<Session[] | undefined>()
  const [events, setEvents] = useState<AccountEvent[] | undefined>()
  const [error, setError] = useState<string | undefined>()
  const [tick, setTick] = useState(0)
  const reload = () => setTick((n) => n + 1)

  useEffect(() => {
    let alive = true
    setError(undefined)
    void Promise.all([
      call<AccountSheet>('me'),
      call<{ sessions?: Session[] }>('sessions').catch(() => ({ sessions: undefined })),
      call<{ events?: AccountEvent[] }>('account-events?limit=40').catch(() => ({ events: undefined })),
    ]).then(([me, s, e]) => {
      if (!alive) return
      setSheet(me)
      setSessions(s.sessions ?? [])
      setEvents(e.events ?? [])
    }).catch((err: unknown) => { if (alive) setError(failureText(t, err)) })
    return () => { alive = false }
  }, [tick, status.account?.id, t])

  const a = sheet?.account
  const member = Boolean(a?.member ?? status.account?.member)
  return h(Fragment, null,
    error ? h('div', { style: errorStyle, role: 'alert' }, error) : null,
    sheet ? h(StarNudgeOnce, { t, moment: 'signed_in' }) : null,
    h('h3', { style: heading }, t('acAllowance')),
    sheet ? h(Allowance, { t, sheet, member }) : h('div', { style: muted }, t('loading')),
    sheet?.invite?.code ? h(Fragment, null, h('h3', { style: heading }, t('acInvite')), h(InviteBlock, { t, invite: sheet.invite })) : null,
    h('h3', { style: heading }, t('acUsage')),
    sheet ? h(Usage, { t, sheet }) : null,
    h('h3', { style: heading }, t('acPassword')),
    h(Password, { t, has: Boolean(a?.has_password), onChanged: reload }),
    h('h3', { style: heading }, t('acSessions')),
    h(Sessions, { t, sessions, locale, onChanged: reload, onEnded }),
    events && events.length > 0 ? h(Fragment, null, h('h3', { style: heading }, t('acTimeline')), h(Timeline, { events, locale })) : null,
    h('h3', { style: heading }, t('acDanger')),
    h(Danger, { t, onEnded }))
}

const heading: Record<string, string | number> = { fontSize: 14, fontWeight: 600, margin: '8px 0 0' }

// ---- the pool, and the ways on ------------------------------------------------------------

function Allowance({ t, sheet, member }: { t: Translate; sheet: AccountSheet; member: boolean }): ReactNode {
  const s = sheet.spend
  if (!s || member || s.unlimited || s.grant === undefined) {
    return h('div', { style: muted }, member ? t('acMemberNoLimit') : t('acNoPool', { total: yuan(s?.total ?? 0) }))
  }
  const grant = s.grant
  const left = s.left ?? Math.max(0, grant - (s.total ?? 0))
  const pct = grant > 0 ? Math.min(100, Math.round(((s.total ?? 0) / grant) * 100)) : 0
  const exhausted = left <= 0
  const low = exhausted || Boolean(s.warn) || pct >= 80
  return h('div', { className: 'nm-card nm-usage' },
    h('div', { className: 'nm-usage-row' },
      h('span', { className: 'nm-usage-plan' }, t('gnPlanFree')),
      h('span', { className: 'nm-usage-pct' }, t('acLeftOf', { left: yuan(left), grant: yuan(grant) }))),
    h('div', { className: 'nm-usage-bar', role: 'progressbar', 'aria-valuenow': pct, 'aria-valuemin': 0, 'aria-valuemax': 100 }, h('span', { style: { width: `${pct}%` } })),
    h('div', { className: 'nm-usage-fine' }, s.usd_cny ? t('acSpentUsd', { total: yuan(s.total ?? 0), usd: ((s.total ?? 0) / s.usd_cny).toFixed(2) }) : t('acSpent', { total: yuan(s.total ?? 0) })),
    low ? h(WaysOn, { t, exhausted, sheet }) : null)
}

/** Mainland China when the UI is Chinese, the account signed in with a phone, or the relay says `cn` (C5). */
export function mainland(t: Translate, sheet: AccountSheet): boolean {
  const region = sheet.region ?? sheet.account?.region
  if (region === 'cn') return true
  if (region && region !== 'cn') return false
  return t('langTag') === 'zh' || sheet.account?.channel === 'phone'
}

/** When the pool is low or spent: the ways on, from what the relay sends (C11), under the pool bar. */
function WaysOn({ t, exhausted, sheet }: { t: Translate; exhausted: boolean; sheet: AccountSheet }): ReactNode {
  return h(AllowanceWays, { t, info: allowanceInfo(sheet), sheet, exhausted, inSettings: true })
}

// ---- the invite ----------------------------------------------------------------------------

function InviteBlock({ t, invite }: { t: Translate; invite: NonNullable<AccountSheet['invite']> }): ReactNode {
  const [copied, setCopied] = useState<'code' | 'link' | undefined>()
  const copy = (what: 'code' | 'link', text: string) => {
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(what)
      window.setTimeout(() => setCopied(undefined), 1800)
    }).catch(() => undefined)
  }
  const earned = invite.earned_cny ?? 0
  return h('div', { className: 'nm-card' },
    h('div', { className: 'nm-row' },
      h('div', { className: 'nm-row-main' },
        h('span', { className: 'nm-row-title' }, invite.code ?? ''),
        h('span', { className: 'nm-row-sub nm-wrap' }, t('inviteText', { bonus: invite.bonus_cny ?? 5 }))),
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => copy('code', invite.code ?? '') }, h(IconCopy, { size: 14 }), copied === 'code' ? t('inviteCopied') : t('inviteCopy'))),
    invite.url
      ? h('div', { className: 'nm-row' },
          h('div', { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title', style: { fontWeight: 400, fontSize: 13 } }, invite.url)),
          h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => copy('link', invite.url ?? '') }, h(IconCopy, { size: 14 }), copied === 'link' ? t('inviteCopied') : t('inviteCopy')))
      : null,
    h('div', { className: 'nm-row' }, h('span', { className: 'nm-row-sub' }, t('inviteStats', { n: invite.invites ?? 0, earned: earned.toFixed(earned % 1 === 0 ? 0 : 2) }))))
}

// ---- usage by kind and by model -----------------------------------------------------------

function Usage({ t, sheet }: { t: Translate; sheet: AccountSheet }): ReactNode {
  const [which, setWhich] = useState<'today' | 'total'>('total')
  const rows = (which === 'today' ? sheet.usage?.today?.by_kind : sheet.usage?.total?.by_kind) ?? []
  const models = sheet.usage?.total?.by_model ?? []
  const kindWord = (k: string | undefined) => (k === 'chat' ? t('acKindChat') : k === 'image' ? t('acKindImage') : k === 'video' ? t('acKindVideo') : k === 'realtime' ? t('acKindCalls') : (k ?? ''))
  const line = (r: UsageRow, label: string) =>
    h('div', { key: label, className: 'nm-row' },
      h('div', { className: 'nm-row-main' },
        h('span', { className: 'nm-row-title' }, label),
        h('span', { className: 'nm-row-sub' }, t('acUsageLine', { n: r.requests ?? 0, tokens: ((r.prompt_tokens ?? 0) + (r.completion_tokens ?? 0)).toLocaleString() }))),
      h('span', { className: 'nm-usage-pct' }, yuan(r.cost_cny ?? 0)))
  return h(Fragment, null,
    h('div', { className: 'nm-seg', role: 'tablist', style: { alignSelf: 'flex-start' } },
      (['today', 'total'] as const).map((w) => h('button', { key: w, type: 'button', role: 'tab', className: `nm-seg-btn${which === w ? ' nm-active' : ''}`, 'aria-selected': which === w, onClick: () => setWhich(w) }, t(w === 'today' ? 'acToday' : 'acTotal')))),
    h('div', { className: 'nm-card' },
      rows.length ? rows.map((r) => line(r, kindWord(r.kind))) : h('div', { className: 'nm-row' }, h('span', { className: 'nm-row-sub' }, t('acUsageNone')))),
    which === 'total' && models.length
      ? h('div', { className: 'nm-card' }, models.map((r) => line(r, r.model ?? '')))
      : null)
}

// ---- the password --------------------------------------------------------------------------

function Password({ t, has, onChanged }: { t: Translate; has: boolean; onChanged(): void }): ReactNode {
  const [open, setOpen] = useState(false)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const [done, setDone] = useState<string | undefined>()
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    void call('password', { password: next, ...(has ? { current } : {}) })
      .then(() => { setOpen(false); setCurrent(''); setNext(''); setDone(next ? t('acPasswordSaved') : t('acPasswordRemoved')); onChanged() })
      .catch((err: unknown) => setError(failureText(t, err)))
      .finally(() => setBusy(false))
  }
  if (!open) {
    return h('div', { className: 'nm-card' },
      h('div', { className: 'nm-row' },
        h('div', { className: 'nm-row-main' },
          h('span', { className: 'nm-row-title' }, has ? t('acPasswordSet') : t('acPasswordNone')),
          h('span', { className: 'nm-row-sub nm-wrap' }, done ?? t('acPasswordWhy'))),
        h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => { setDone(undefined); setOpen(true) } }, has ? t('acPasswordChange') : t('acPasswordAdd'))))
  }
  return h('form', { className: 'nm-card', style: { display: 'flex', flexDirection: 'column', gap: 8, padding: '12px 14px' }, onSubmit: submit },
    has ? h(Input, { value: current, type: 'password', onChange: (e: FormEvent<HTMLInputElement>) => setCurrent(e.currentTarget.value), placeholder: t('acPasswordCurrent'), autoComplete: 'current-password', 'aria-label': t('acPasswordCurrent') }) : null,
    h(Input, { value: next, type: 'password', onChange: (e: FormEvent<HTMLInputElement>) => setNext(e.currentTarget.value), placeholder: has ? t('acPasswordNew') : t('obPassword'), autoComplete: 'new-password', autoFocus: true, 'aria-label': t('acPasswordNew') }),
    h('div', { style: muted }, has ? t('acPasswordRemoveHint') : t('acPasswordRule')),
    error ? h('div', { style: errorStyle, role: 'alert' }, error) : null,
    h('div', { style: row },
      h(Button, { variant: 'primary', size: 'sm', type: 'submit', disabled: busy || (!has && next.length < 8) || (has && current.length === 0) || (next.length > 0 && next.length < 8) }, busy ? t('saving') : t('save')),
      h(Button, { variant: 'ghost', size: 'sm', type: 'button', disabled: busy, onClick: () => { setOpen(false); setError(undefined) } }, t('cancel'))))
}

// ---- the devices holding a key ------------------------------------------------------------

function Sessions({ t, sessions, locale, onChanged, onEnded }: { t: Translate; sessions: Session[] | undefined; locale: string; onChanged(): void; onEnded(status: CloudStatus): void }): ReactNode {
  const [busy, setBusy] = useState<string | undefined>()
  const revoke = (prefix: string) => {
    setBusy(prefix)
    void call('sessions/revoke', { prefix }).then(onChanged).catch(() => undefined).finally(() => setBusy(undefined))
  }
  const everywhere = () => {
    if (!window.confirm(t('acSignOutAllConfirm'))) return
    setBusy('*')
    void call<CloudStatus>('sign-out-all', {}).then(onEnded).catch(() => undefined).finally(() => setBusy(undefined))
  }
  if (!sessions) return h('div', { style: muted }, t('loading'))
  return h(Fragment, null,
    h('div', { className: 'nm-card' },
      sessions.length === 0
        ? h('div', { className: 'nm-row' }, h('span', { className: 'nm-row-sub' }, t('acSessionsNone')))
        : sessions.map((s) =>
            h('div', { key: s.prefix, className: 'nm-row' },
              h('div', { className: 'nm-row-main' },
                h('span', { className: 'nm-row-title' }, s.device || t('acSessionUnnamed'), s.current ? ` · ${t('acThisDevice')}` : ''),
                h('span', { className: 'nm-row-sub' }, t('acSessionLine', { via: s.via === 'password' ? t('acViaPassword') : t('acViaCode'), when: when(s.last_used_at ?? s.created_at, locale) }))),
              s.current ? null : h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: busy !== undefined, onClick: () => revoke(s.prefix) }, busy === s.prefix ? t('working') : t('acRevoke'))))),
    sessions.length > 1
      ? h('div', null, h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: busy !== undefined, onClick: everywhere }, t('acSignOutAll')))
      : null)
}

// ---- the timeline --------------------------------------------------------------------------

function Timeline({ events, locale }: { events: AccountEvent[]; locale: string }): ReactNode {
  return h('div', { className: 'nm-card' },
    events.slice(0, 40).map((e, i) =>
      h('div', { key: `${e.ts}-${i}`, className: 'nm-row' },
        h('div', { className: 'nm-row-main' },
          h('span', { className: 'nm-row-title' }, e.kind.replace(/[._]/g, ' ')),
          e.detail ? h('span', { className: 'nm-row-sub nm-wrap' }, e.detail) : null),
        h('span', { className: 'nm-row-sub' }, when(e.ts, locale)))))
}

// ---- the way out ---------------------------------------------------------------------------

function Danger({ t, onEnded }: { t: Translate; onEnded(status: CloudStatus): void }): ReactNode {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const remove = () => {
    if (!window.confirm(t('acDeleteConfirm'))) return
    if (!window.confirm(t('acDeleteConfirm2'))) return
    setBusy(true)
    setError(undefined)
    void call<CloudStatus>('delete-account', {}).then(onEnded).catch((err: unknown) => setError(failureText(t, err))).finally(() => setBusy(false))
  }
  return h('div', { className: 'nm-card' },
    h('div', { className: 'nm-row' },
      h('div', { className: 'nm-row-main' },
        h('span', { className: 'nm-row-title' }, t('acDelete')),
        h('span', { className: 'nm-row-sub nm-wrap' }, t('acDeleteSub'))),
      h('button', { type: 'button', className: 'nm-pill nm-pill-danger nm-pill-sm', disabled: busy, onClick: remove }, busy ? t('working') : t('acDelete'))),
    error ? h('div', { style: { ...errorStyle, padding: '0 0 10px' }, role: 'alert' }, error) : null)
}
