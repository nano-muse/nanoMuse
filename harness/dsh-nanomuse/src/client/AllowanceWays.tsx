/**
 * The ways on when the free allowance is spent or nearly (the phones' `AllowanceWaysCard`,
 * the web app's `AllowanceWays`): your own model key, a plan you already pay for, inviting a
 * friend — and, once, a star. Drawn from what the relay sends beside the refusal and under
 * `/v1/me.spend` (`guidance`, contract C11: the providers for the region, the plans, the
 * caveats), never from a list written here; where the relay is older, the bundled catalogue
 * stands in. Two places draw it: the chat, under a refused turn (`RefusalCard.tsx`), where the
 * key rows and the ChatGPT sign-in are inline; and Settings → nanoMuse Cloud, under the pool
 * bar, where the rows are already on the page above.
 */
import { createElement as h, Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { keyUrlFor, type Capability } from '../catalogue.ts'
import { mainland, markStarred, openStar, type AccountSheet } from './AccountPage.tsx'
import { call, muted, row, type Translate } from './api.ts'
import { openLink } from './bridge.ts'
import { settingsBus } from './bus.ts'
import { IconChevronRight, IconClose, IconCopy, IconGift, IconHeart, IconKey, IconSparkle, IconUser } from './icons.tsx'
import { useLive } from './live.ts'
import { ACCOUNT_SECTION, ChatGptRow, coverage, groupsOf, useProviders, WaysOnRows } from './OwnKey.tsx'
import { roomsCall, type NudgeAsk } from './rooms.ts'

/** `spend.guidance` (relay 0.21, contract C11): the own-key card as data. Every field optional: an older relay sends none of it. */
export interface Guidance {
  version?: number
  region?: string
  docs?: string
  providers?: GuidanceProvider[]
  plans?: Array<{ id?: string; provider?: string; name?: string; auth?: string; clients?: string[]; covers?: Capability[] }>
  local?: Array<{ id?: string; name?: string; name_zh?: string }>
  caveats?: { chatgpt?: string; chatgpt_zh?: string }
}
export interface GuidanceProvider {
  id: string
  name?: string
  name_zh?: string
  key_url?: string
  auth?: string[]
  covers?: Capability[]
  one_key?: boolean
  note?: string
  note_zh?: string
}

/** What the card needs of a refusal or the account sheet: the numbers and where the ways on lead. */
export interface AllowanceInfo {
  left?: number | null | undefined
  grant?: number | undefined
  inviteUrl?: string | undefined
  inviteBonusCny?: number | undefined
  ownKeyDocs?: string | undefined
  guidance?: Guidance | undefined
}

/** Where the guide for one's own key is when the relay did not say. */
export const OWN_KEY_DOCS = 'https://nanomuse.cn/own-key'

/** The card's numbers and links out of `/v1/me` (the sheet) with a refusal's figures first, when there is one. */
export function allowanceInfo(sheet: AccountSheet | undefined, refusal?: AllowanceInfo): AllowanceInfo {
  const s = sheet?.spend
  return {
    left: refusal?.left ?? s?.left,
    grant: refusal?.grant ?? s?.grant,
    inviteUrl: refusal?.inviteUrl || sheet?.invite?.url,
    inviteBonusCny: refusal?.inviteBonusCny ?? s?.invite_bonus_cny ?? sheet?.invite?.bonus_cny,
    ownKeyDocs: refusal?.ownKeyDocs || s?.own_key_docs,
    guidance: refusal?.guidance ?? s?.guidance,
  }
}

const nameOf = (t: Translate, p: GuidanceProvider): string => (t('langTag') === 'zh' ? p.name_zh || p.name : p.name || p.name_zh) || p.id

export interface AllowanceWaysProps {
  t: Translate
  info: AllowanceInfo
  /** The account sheet when one is at hand (where the person is, the invite code). */
  sheet?: AccountSheet
  /** true: the pool is spent (the card leads with that); false: the 80 % heads-up. */
  exhausted: boolean
  /** The lead sentence instead of the one `exhausted` picks (relay 0.22: the allowance paused, not spent). */
  lead?: string | undefined
  /** In Settings → nanoMuse Cloud the key rows and the sign-in are on the page already: the card points up instead of drawing them again. */
  inSettings?: boolean
  onChanged?(): void
}

/**
 * The 80 % heads-up, once per pool size: the host re-reads the account after a turn on the
 * account's model and sets `live.headsUp` while the relay says `warn`; one dismissible line
 * above the composer, leading to Settings → nanoMuse Cloud. Nothing while the pool is spent
 * (the card under the turn says that) or without limit.
 */
export function AllowanceHeadsUp({ t }: { t: Translate }): ReactNode {
  const live = useLive()
  const up = live.headsUp
  if (!up) return null
  const seen = () => { void call('allowance/seen', {}).catch(() => undefined) }
  return h('div', { className: 'nm-headsup', role: 'status', 'data-testid': 'nm-headsup' },
    h('span', { className: 'nm-headsup-icon' }, h(IconSparkle, { size: 14 })),
    h('span', { className: 'nm-headsup-text' },
      t('huText', { left: up.left.toFixed(2), grant: up.grant.toFixed(0), bonus: up.bonus.toFixed(0) }), ' ',
      h('button', { type: 'button', className: 'nm-ob-link nm-inline', onClick: () => { seen(); settingsBus.openSection?.(ACCOUNT_SECTION) } }, t('huSee'))),
    h('button', { type: 'button', className: 'nm-icon-btn nm-headsup-close', 'aria-label': t('huDismiss'), title: t('huDismiss'), onClick: seen }, h(IconClose, { size: 14 })))
}

/** The three ways on, and the star once. */
export function AllowanceWays({ t, info, sheet, exhausted, lead, inSettings = false, onChanged }: AllowanceWaysProps): ReactNode {
  const zh = t('langTag') === 'zh'
  const bonus = info.inviteBonusCny ?? 5
  const docs = info.ownKeyDocs || info.guidance?.docs || OWN_KEY_DOCS
  const link = info.inviteUrl || ''
  const guidance = info.guidance
  const [more, setMore] = useState(false)
  const [copied, setCopied] = useState(false)
  const { view } = useProviders(t)
  // the host decides whether the star row is due (C1 `exhausted`); asked once per card
  const [star, setStar] = useState(false)
  const asked = useRef(false)
  useEffect(() => {
    if (!exhausted || asked.current) return
    asked.current = true
    let alive = true
    roomsCall<{ ask: NudgeAsk | null }>('nudges/ask', { moment: 'exhausted' })
      .then((r) => { if (alive && r.ask) setStar(true) })
      .catch(() => undefined)
    return () => { alive = false }
  }, [exhausted])

  const cn = sheet ? mainland(t, sheet) : guidance?.region === 'cn' || (guidance?.region === undefined && zh)
  // the providers behind "more": the relay's list for the region when it sent one, else the
  // catalogue's; in the chat, less the ones drawn as rows just above
  const shown = new Set(view && !inSettings ? groupsOf(view.catalogue, view.region).first.map((p) => p.id) : [])
  const others: Array<{ id: string; name: string; keyUrl: string; covers: Capability[] }> = guidance?.providers?.length
    ? guidance.providers.filter((p) => !shown.has(p.id) && (p.auth ?? ['key']).includes('key')).map((p) => ({ id: p.id, name: nameOf(t, p), keyUrl: p.key_url ?? '', covers: p.covers ?? [] }))
    : view
      ? (inSettings ? [...groupsOf(view.catalogue, view.region).first, ...groupsOf(view.catalogue, view.region).rest] : groupsOf(view.catalogue, view.region).rest).map((p) => ({ id: p.id, name: zh ? p.name_zh : p.name, keyUrl: keyUrlFor(p, view.region), covers: p.capabilities }))
      : []
  const planNames = (guidance?.plans ?? []).map((p) => p.name ?? '').filter(Boolean)
  const caveat = zh ? guidance?.caveats?.chatgpt_zh || guidance?.caveats?.chatgpt : guidance?.caveats?.chatgpt
  const openRows = () => { settingsBus.openSection?.(ACCOUNT_SECTION) }
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      // the clipboard is not ours in this window: the link stays printed below
    }
  }
  const changed = () => onChanged?.()

  return h('div', { className: 'nm-ways nm-allowance', 'data-testid': 'nm-allowance-ways' },
    h('div', { className: 'nm-ways-lead' }, lead ?? (exhausted ? t('awExhausted') : t('awNearlyOut', { left: (info.left ?? 0).toFixed(2), grant: (info.grant ?? 0).toFixed(0) }))),
    h('div', { className: 'nm-way-sub nm-wrap', style: muted }, t('awThreeWays')),
    // 1. your own key
    h('div', { className: 'nm-way' },
      h('span', { className: 'nm-way-icon' }, h(IconKey, { size: 15 })),
      h('div', { className: 'nm-way-main' },
        h('div', { className: 'nm-way-title' }, t('awOwnKey')),
        h('div', { className: 'nm-way-sub nm-wrap' }, cn ? t('awOwnKeyCn') : t('awOwnKeyGlobal')),
        inSettings
          ? h('div', { style: row }, h('button', { type: 'button', className: 'nm-pill nm-pill-sm', onClick: openRows }, t('awRowsAbove')), h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => openLink(docs) }, t('awGuide')))
          : h(Fragment, null,
              view ? h(WaysOnRows, { t, view, groups: ['first'], signInRow: false, headings: false, onChanged: changed }) : h('div', { style: muted }, t('loading')),
              h('div', { style: row },
                h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: openRows }, t('awOpenSettings')),
                h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => openLink(docs) }, t('awGuide')))),
        others.length
          ? h('div', null,
              h('button', { type: 'button', className: 'nm-ob-link nm-inline nm-aw-more', 'aria-expanded': more, onClick: () => setMore(!more) }, h('span', { className: `nm-aw-chevron${more ? ' nm-aw-open' : ''}` }, h(IconChevronRight, { size: 13 })), ' ', t('awOtherProviders')),
              more
                ? h('ul', { className: 'nm-aw-list' }, others.map((p) =>
                    h('li', { key: p.id },
                      h('span', null, h('b', null, p.name), p.covers.length ? h('span', { style: muted }, ` · ${coverage(t, p.covers)}`) : null),
                      h('span', { className: 'nm-aw-list-actions' },
                        h('button', { type: 'button', className: 'nm-ob-link nm-inline', onClick: openRows }, t('awSetUp')),
                        p.keyUrl ? h('button', { type: 'button', className: 'nm-ob-link nm-inline', onClick: () => openLink(p.keyUrl) }, t('ownKeyGetKey')) : null))))
                : null)
          : null)),
    // 2. a plan you already pay for
    h('div', { className: 'nm-way' },
      h('span', { className: 'nm-way-icon' }, h(IconUser, { size: 15 })),
      h('div', { className: 'nm-way-main' },
        h('div', { className: 'nm-way-title' }, t('awPlan')),
        h('div', { className: 'nm-way-sub nm-wrap' }, planNames.length ? t('awPlanSub', { plans: planNames.join(zh ? '、' : ', ') }) : t('awPlanSubNoList')),
        caveat ? h('div', { className: 'nm-way-sub nm-wrap', style: muted }, caveat) : null,
        inSettings
          ? h('div', { style: row }, h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: openRows }, t('awRowsAbove')))
          : view ? h(ChatGptRow, { t, view, onChanged: changed }) : null)),
    // 3. invite a friend
    h('div', { className: 'nm-way' },
      h('span', { className: 'nm-way-icon' }, h(IconGift, { size: 15 })),
      h('div', { className: 'nm-way-main' },
        h('div', { className: 'nm-way-title' }, t('awInvite', { bonus: bonus.toFixed(0) })),
        link
          ? h('div', { style: row },
              h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => void copy() }, h(IconCopy, { size: 14 }), copied ? t('inviteCopied') : t('awCopyLink')),
              h('span', { className: 'nm-way-sub', style: { ...muted, wordBreak: 'break-all' } }, link))
          : h('div', { className: 'nm-way-sub nm-wrap' }, t('acWayInviteSub')))),
    // the star, once, when the policy says so
    exhausted && star
      ? h('div', { className: 'nm-way' },
          h('span', { className: 'nm-way-icon' }, h(IconHeart, { size: 15 })),
          h('div', { className: 'nm-way-main' },
            h('div', { className: 'nm-way-title' }, t('acWayStar')),
            h('div', { style: row },
              h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => { openStar(); setStar(false) } }, t('starAction')),
              h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => { markStarred(); setStar(false) } }, t('starDone')))))
      : null)
}
