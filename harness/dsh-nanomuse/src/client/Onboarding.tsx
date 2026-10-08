/**
 * The first run, the way the phone does it (C4): the whole window, one page at a time,
 * three dots at the top and a gear to Settings. Welcome (the face, one line on what it is,
 * three feature rows, the free/open-source notice, "Sign in — free"); the sign-in itself
 * (a phone number or an e-mail, the six boxes of the code, or the password); a password
 * page for an account that was just created; "Which model answers?" (the Cloud model, or
 * a key of one's own); the own-key step (C11: the region's providers from the catalogue, a
 * key taken inline, the ChatGPT sign-in, *More ways*; Continue once one is in, Skip for now
 * until then); the two permissions the hands need (macOS only — elsewhere the page is skipped); and
 * "Meet <name>" with Start, which opens the main chat as the first conversation, where
 * the app speaks first (`FirstRun.tsx`).
 *
 * Registered as the `settings.onboarding` step with the shipped id, so the coordinator
 * shows ours in that turn. It completes itself only when the phone's rule says the pages
 * are not due — signed in (or a model of one's own), a model, and either a chat with
 * messages or a Start already pressed. A ready install that never saw the pages still
 * gets them: being ready only skips the account pages. What the pages decide lives on the
 * host (`$DSH_HOME/nanomuse/firstrun.json`), not in this browser.
 */
import { useModalLayer } from '@deepseek-ai/dsh-client-ui-primitives'
import { createElement as h, Fragment, useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { firstRunNeeded, stageOf, dotOf, type Stage } from '../firstrun.ts'
import { call, type CloudStatus, type Translate, failureText } from './api.ts'
import { useCloudConfig, type AccountSheet } from './AccountPage.tsx'
import { Avatar } from './Avatar.tsx'
import { BrandMark } from './BrandMark.tsx'
import { gatedPermissions, openLink, type PermissionKind } from './bridge.ts'
import { permissionSub, permissionTitle, usePermissions, type Permissions } from './permissions.ts'
import { BlackScreenNotice, HandsTryRows } from './HandsCheck.tsx'
import { IconCheck, IconHand, IconMessage, IconMonitor, IconSettings, IconUsers } from './icons.tsx'
import { useLive } from './live.ts'
import { setMainChatId } from './MuseChats.tsx'
import { OwnKeyStep } from './OwnKey.tsx'
import { nav, roomsCall, useRooms } from './rooms.ts'

/** The owner share the onboarding coordinator passes to a step. */
export interface OnboardingOwnerProps {
  stepId: string
  explicit?: boolean | undefined
  complete: () => void
  openSection: (id: string) => void
  /** Some chat already has messages (the phone's `hasSessions`); the settings shell passes it. */
  hasSessions?: boolean | undefined
  /** The workspace list, when the host passes its share. */
  useWorkspaces?: (<S>(selector: (snapshot: { items: readonly { workspaceId: string; path: string; title: string }[] }) => S) => S) | undefined
}

/** What the plugin lends the flow: the workspace actions (kept for the shell's signature). */
export interface OnboardingActions {
  pickDirectory(): Promise<string | null>
  createWorkspace(path: string): Promise<{ workspaceId: string }>
  openWorkspace(workspaceId: string): Promise<void>
}

/** The sign-in's own screens, shown over the Welcome stage. */
type SignInView = 'identifier' | 'code' | 'password'

/** How long Start may take to open the main chat before we stop waiting. */
const START_MS = 12_000
/** The privacy policy as every client links it (the relay, the web console and the phones agree). */
const PRIVACY_URL = 'https://nanomuse.cn/privacy/'
const HANDS_URL = 'https://github.com/nano-muse/nanoMuse/blob/main/docs/sentinel.md'

function Pill({ children, onClick, disabled, type = 'button', ghost = false, small = false, className = '' }: {
  children?: ReactNode
  onClick?: (() => void) | undefined
  disabled?: boolean | undefined
  type?: 'button' | 'submit'
  ghost?: boolean
  small?: boolean
  className?: string
}): ReactNode {
  return h('button', { type, disabled, onClick, className: `nm-pill${ghost ? ' nm-pill-ghost' : ''}${small ? ' nm-pill-sm' : ''} ${className}`.trim() }, children)
}

function Spinner(): ReactNode {
  return h('div', { className: 'nm-spinner', role: 'progressbar', 'aria-busy': true })
}

/** Six boxes over one real input, so paste, IME and autofill all land in the same place. */
function CodeBoxes({ value, onChange, disabled, label }: { value: string; onChange(next: string): void; disabled: boolean; label: string }): ReactNode {
  const input = useRef<HTMLInputElement>(null)
  // focus on mount, and again when a wrong code has been cleared (a disabled input loses focus)
  useEffect(() => { if (!disabled) input.current?.focus() }, [disabled])
  const digits = value.replace(/\D/g, '').slice(0, 6)
  return h('div', { className: 'nm-code', onClick: () => input.current?.focus() },
    h('input', {
      ref: input,
      className: 'nm-code-input',
      value: digits,
      inputMode: 'numeric',
      autoComplete: 'one-time-code',
      maxLength: 6,
      disabled,
      'aria-label': label,
      onChange: (e: FormEvent<HTMLInputElement>) => onChange(e.currentTarget.value.replace(/\D/g, '').slice(0, 6)),
    }),
    Array.from({ length: 6 }, (_, i) =>
      h('div', { key: i, className: `nm-code-box${i === Math.min(digits.length, 5) ? ' nm-code-caret' : ''}${digits[i] ? ' nm-code-filled' : ''}`, 'aria-hidden': true }, digits[i] ?? '')))
}

function link(url: string, label: string): ReactNode {
  return h('a', { href: url, onClick: (e: Event) => { e.preventDefault(); openLink(url) } }, label)
}

export function makeOnboarding(t: Translate, _actions: OnboardingActions) {
  return function NanomuseOnboarding(props: OnboardingOwnerProps): ReactNode {
    const { complete, openSection, explicit = false, hasSessions = false } = props
    const live = useLive()
    const rooms = useRooms()
    const [status, setStatus] = useState<CloudStatus | undefined>()
    const [decided, setDecided] = useState(false)
    const [signIn, setSignIn] = useState<SignInView | null>(null)
    const [identifier, setIdentifier] = useState('')
    const [code, setCode] = useState('')
    const [password, setPassword] = useState('')
    // A friend's invite code (optional, with the six digits): both get credit on a first sign-in.
    const [invite, setInvite] = useState('')
    const [inviteOpen, setInviteOpen] = useState(false)
    const config = useCloudConfig()
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState<string | undefined>()
    const [resent, setResent] = useState(false)
    // a sign-in that created the account owes the password page; answered (or skipped) once
    const [fresh, setFresh] = useState(false)
    const [passwordSeen, setPasswordSeen] = useState(false)
    const [modelsSkipped, setModelsSkipped] = useState(false)
    const [starting, setStarting] = useState(false)
    const [fading, setFading] = useState(false)
    const layer = useRef<HTMLDivElement>(null)
    useModalLayer(layer, decided, () => undefined)
    // The coordinator hands over a fresh `complete` closure on every render; the decision
    // below is made once, when the step mounts and the host has answered.
    const owner = useRef({ complete, explicit })
    owner.current = { complete, explicit }

    // The rooms' first snapshot carries the first run; the cloud's status says who is signed in.
    useEffect(() => {
      let alive = true
      call<CloudStatus>('status')
        .then((next) => { if (alive) setStatus(next) })
        .catch(() => { if (alive) owner.current.complete() }) // without the host half there is nothing to offer
      return () => { alive = false }
    }, [])
    useEffect(() => {
      if (decided || !status || !rooms.streaming) return
      setDecided(true)
      if (owner.current.explicit) return
      // "ready" (a model of one's own) stands for the account on a desktop: it skips the account pages
      const needed = firstRunNeeded({ signedIn: status.signedIn || status.ready, hasModel: status.ready, hasSessions, done: rooms.firstRun.done })
      if (!needed) owner.current.complete()
    }, [decided, status, rooms.streaming, rooms.firstRun.done, hasSessions])
    // a sign-in or sign-out elsewhere, or a key added in the model settings: ask the host again
    const seenSignedIn = useRef<boolean | undefined>(undefined)
    useEffect(() => {
      if (!live.streaming) return
      if (seenSignedIn.current !== undefined && seenSignedIn.current !== live.cloud.signedIn) {
        call<CloudStatus>('status').then((next) => setStatus(next)).catch(() => undefined)
      }
      seenSignedIn.current = live.cloud.signedIn
    }, [live.streaming, live.cloud.signedIn])
    const gated = gatedPermissions()
    const stage: Stage | null = status
      ? stageOf({
          signedIn: status.signedIn,
          hasModel: status.ready,
          freshAccount: fresh,
          passwordSeen,
          sourceChosen: rooms.firstRun.sourceChosen,
          modelsSkipped,
          gated,
          permissionsSeen: rooms.firstRun.permissionsSeen,
        })
      : null
    // the own-key step stays until Continue or Skip: a key saved there does not flip the page by itself

    const finish = useCallback(() => {
      setFading(true)
      window.setTimeout(() => owner.current.complete(), 260)
    }, [])
    // Start: the host opens the main chat and binds the first conversation to it; the window
    // goes there and the overlay fades. The app's opening lines appear in the chat itself.
    const start = useCallback(() => {
      setStarting(true)
      let done = false
      const settle = () => { if (!done) { done = true; finish() } }
      const timer = window.setTimeout(settle, START_MS)
      roomsCall<{ sessionId: string }>('firstrun/start', {})
        .then((result) => {
          setMainChatId(result.sessionId)
          nav.openSession(result.sessionId)
        })
        .catch(() => roomsCall('firstrun/finish', {}).catch(() => undefined))
        .finally(() => { window.clearTimeout(timer); settle() })
    }, [finish])

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
    const sendCode = (event?: FormEvent) => {
      event?.preventDefault()
      void run(async () => {
        await call('code', { identifier: identifier.trim() })
        setCode('')
        setSignIn('code')
      })
    }
    const resend = () => {
      void run(async () => {
        await call('code', { identifier: identifier.trim() })
        setResent(true)
        window.setTimeout(() => setResent(false), 4000)
      })
    }
    const signedIn = async (next: CloudStatus, byCode: boolean) => {
      // an account that has no password yet was (most likely) created just now: offer one
      if (byCode) {
        const sheet = await call<AccountSheet>('me').catch(() => undefined)
        setFresh(sheet?.account?.has_password === false)
      }
      setStatus(next)
      setSignIn(null)
    }
    const verify = (value: string) => {
      if (busy || value.length !== 6) return
      void run(async () => {
        try {
          const next = await call<CloudStatus>('verify', { identifier: identifier.trim(), code: value, invite: invite.trim().toUpperCase() })
          setCode('')
          await signedIn(next, true)
        } catch (err: unknown) {
          // a wrong code leaves empty boxes, not six digits to delete one by one
          setCode('')
          throw err
        }
      })
    }
    const login = (event: FormEvent) => {
      event.preventDefault()
      void run(async () => {
        const next = await call<CloudStatus>('login', { identifier: identifier.trim(), password })
        setPassword('')
        await signedIn(next, false)
      })
    }
    const setPasswordNow = (event: FormEvent) => {
      event.preventDefault()
      void run(async () => {
        await call('password', { password })
        setPassword('')
        setPasswordSeen(true)
      })
    }
    const choose = (source: 'cloud' | 'own') => {
      void roomsCall('firstrun/set', { sourceChosen: source }).catch(() => undefined)
    }
    // the own-key step (C11): done once a key is saved or the ChatGPT sign-in finished; Continue then, Skip for now until then
    const [ownDone, setOwnDone] = useState(false)
    const onOwnDone = useCallback((done: boolean) => setOwnDone(done), [])
    const leaveOwnKeyStep = () => {
      setModelsSkipped(true)
      // the host's `ready` follows the key just saved: read it again so the later pages and the completion rule see it
      call<CloudStatus>('status').then((next) => setStatus(next)).catch(() => undefined)
    }
    const permissionsDone = () => { void roomsCall('firstrun/set', { permissionsSeen: true }).catch(() => undefined) }

    if (!decided || !status || stage === null) return null

    const profile = live.streaming ? live.profile : status.profile
    const name = profile?.name || 'nanoMuse'

    let body: ReactNode
    if (starting) {
      body = h('div', { className: 'nm-ob-center' }, h(Spinner))
    } else if (signIn === 'identifier') {
      // the sign-in pages are the app's own, so the app's mark is their hero (the face comes later: the welcome and "Meet" pages)
      body = h('form', { className: 'nm-ob-center nm-ob-form', onSubmit: sendCode },
        h(BrandMark, { size: 72, className: 'nm-fr-hero-mark' }),
        h('h1', { className: 'nm-ob-title' }, t('obSignInTitle')),
        h('input', { className: 'nm-field', value: identifier, placeholder: t('obIdentifier'), autoComplete: 'username', autoFocus: true, 'aria-label': t('obIdentifier'), onChange: (e: FormEvent<HTMLInputElement>) => setIdentifier(e.currentTarget.value) }),
        // SMS codes reach mainland-China numbers only; everyone else gets an e-mail (the Settings sign-in says the same)
        h('p', { className: 'nm-ob-fine' }, t('identifierHint')),
        h('p', { className: 'nm-ob-fine' }, t('obTermsLead'), link(PRIVACY_URL, t('obPrivacy')), t('obTermsEnd')),
        error ? h('div', { className: 'nm-ob-error', role: 'alert' }, error) : null,
        h(Pill, { type: 'submit', disabled: busy || identifier.trim().length < 3, className: 'nm-ob-wide' }, busy ? t('sending') : t('obContinue')),
        h('button', { type: 'button', className: 'nm-ob-link', onClick: () => { setError(undefined); setSignIn(null) } }, t('obBack')))
    } else if (signIn === 'code') {
      body = h('div', { className: 'nm-ob-center nm-ob-form' },
        h(BrandMark, { size: 72, className: 'nm-fr-hero-mark' }),
        h('h1', { className: 'nm-ob-title' }, t('obCodeTitle')),
        h('p', { className: 'nm-ob-fine' },
          t('obCodeSent', { identifier: identifier.trim() }), ' ',
          h('button', { type: 'button', className: 'nm-ob-link nm-inline', disabled: busy, onClick: resend }, resent ? t('obResent') : t('obResend'))),
        h(CodeBoxes, { value: code, disabled: busy, label: t('code'), onChange: (next) => { setCode(next); if (next.length === 6) verify(next) } }),
        inviteOpen
          ? h('input', { className: 'nm-field', value: invite, placeholder: t('obInviteCode'), autoComplete: 'off', autoCapitalize: 'characters', 'aria-label': t('obInviteCode'), onChange: (e: FormEvent<HTMLInputElement>) => setInvite(e.currentTarget.value.replace(/[^0-9a-zA-Z-]/g, '').slice(0, 16)) })
          : h('button', { type: 'button', className: 'nm-ob-link nm-inline', disabled: busy, onClick: () => setInviteOpen(true) }, t('obHaveInvite')),
        inviteOpen ? h('p', { className: 'nm-ob-fine' }, t('obInviteHint', { bonus: config.invitee_bonus_cny ?? 5 })) : null,
        error ? h('div', { className: 'nm-ob-error', role: 'alert' }, error) : null,
        h(Pill, { disabled: busy || code.length !== 6, onClick: () => verify(code), className: 'nm-ob-wide' }, busy ? t('signingIn') : t('obNext')),
        h('div', { className: 'nm-ob-links' },
          h('button', { type: 'button', className: 'nm-ob-link', onClick: () => { setError(undefined); setSignIn('password') } }, t('obOtherWay')),
          h('span', { className: 'nm-ob-sep', 'aria-hidden': true }, '·'),
          h('button', { type: 'button', className: 'nm-ob-link', onClick: () => { setError(undefined); setCode(''); setSignIn('identifier') } }, t('obChangeIdentifier'))))
    } else if (signIn === 'password') {
      body = h('form', { className: 'nm-ob-center nm-ob-form', onSubmit: login },
        h(BrandMark, { size: 72, className: 'nm-fr-hero-mark' }),
        h('h1', { className: 'nm-ob-title' }, t('obPasswordTitle')),
        h('p', { className: 'nm-ob-fine' }, identifier.trim()),
        h('input', { className: 'nm-field', type: 'password', value: password, placeholder: t('obPassword'), autoComplete: 'current-password', autoFocus: true, 'aria-label': t('obPassword'), onChange: (e: FormEvent<HTMLInputElement>) => setPassword(e.currentTarget.value) }),
        error ? h('div', { className: 'nm-ob-error', role: 'alert' }, error) : null,
        h(Pill, { type: 'submit', disabled: busy || password.length === 0, className: 'nm-ob-wide' }, busy ? t('signingIn') : t('obSignIn')),
        h('div', { className: 'nm-ob-links' },
          h('button', { type: 'button', className: 'nm-ob-link', onClick: () => { setError(undefined); setSignIn('code') } }, t('obUseCode')),
          h('span', { className: 'nm-ob-sep', 'aria-hidden': true }, '·'),
          h('button', { type: 'button', className: 'nm-ob-link', onClick: () => { setError(undefined); setPassword(''); setSignIn('identifier') } }, t('obChangeIdentifier'))))
    } else if (stage === 'welcome') {
      // the app's mark, as on the phone (the face comes with the conversation, on the Meet page);
      // two doors: the account, or a key of one's own (the models page; the sign-in can come later)
      body = h(Page, {
        hero: h(BrandMark, { size: 104, className: 'nm-fr-hero-mark' }),
        title: t('frWelcomeTitle'),
        sub: t('frTagline'),
        primary: { label: t('frSignIn'), onClick: () => { setError(undefined); setSignIn('identifier') } },
        secondary: { label: t('frWelcomeOwnKey'), onClick: () => { setModelsSkipped(false); choose('own') } },
        fine: config.allowance_cny ? `${t('frWelcomeFine')} ${t('obFreeAmount', { allowance: config.allowance_cny })}` : t('frWelcomeFine'),
        learnMore: PRIVACY_URL,
        t,
      },
        h('div', { className: 'nm-fr-features' },
          h(FeatureRow, { icon: h(IconMessage, { size: 18 }), title: t('frFeatChat'), sub: t('frFeatChatSub') }),
          h(FeatureRow, { icon: h(IconHand, { size: 18 }), title: t('frFeatHands'), sub: t('frFeatHandsSub') }),
          h(FeatureRow, { icon: h(IconUsers, { size: 18 }), title: t('frFeatReach'), sub: t('frFeatReachSub') })),
        h('div', { className: 'nm-fr-notice' },
          h('div', { className: 'nm-fr-notice-title' }, t('frNoticeTitle')),
          h('p', null, t('frNotice')),
          h('p', { className: 'nm-fr-notice-closing' }, t('frNoticeClosing'))))
    } else if (stage === 'password') {
      body = h('form', { className: 'nm-ob-center nm-fr-page', onSubmit: setPasswordNow },
        h('h1', { className: 'nm-ob-title nm-ob-title-sm' }, t('frPasswordTitle')),
        h('p', { className: 'nm-ob-sub' }, t('frPasswordSub')),
        h('input', { className: 'nm-field', type: 'password', value: password, placeholder: t('obPassword'), autoComplete: 'new-password', autoFocus: true, 'aria-label': t('obPassword'), onChange: (e: FormEvent<HTMLInputElement>) => setPassword(e.currentTarget.value) }),
        error ? h('div', { className: 'nm-ob-error', role: 'alert' }, error) : null,
        h(Pill, { type: 'submit', disabled: busy || password.length < 6, className: 'nm-ob-wide nm-fr-primary' }, busy ? t('sending') : t('frPasswordSet')),
        h('button', { type: 'button', className: 'nm-ob-skip', onClick: () => { setPassword(''); setPasswordSeen(true) } }, t('frSkip')),
        h('p', { className: 'nm-ob-fine' }, t('frPasswordFine')))
    } else if (stage === 'source') {
      body = h(Page, {
        title: t('frSourceTitle'),
        sub: t('frSourceSub'),
        fine: t('frSourceFine'),
        t,
      },
        h('div', { className: 'nm-fr-choices' },
          h(ChoiceRow, { title: t('frSourceCloud'), sub: t('frSourceCloudSub'), disabled: !status.signedIn, onClick: () => choose('cloud') }),
          h(ChoiceRow, { title: t('frOwnKey'), sub: t('frSourceOwnSub'), onClick: () => choose('own') })))
    } else if (stage === 'models') {
      // the own-key step (C11): the region's first group with the ChatGPT row, more ways behind a link;
      // a saved key or a finished sign-in turns Skip for now into Continue
      body = h(Page, {
        title: t('frModelsTitle'),
        sub: t('ownKeyStepSub'),
        primary: ownDone ? { label: t('ownKeyStepDone'), onClick: leaveOwnKeyStep } : undefined,
        secondary: ownDone ? undefined : { label: t('frSkipModels'), onClick: leaveOwnKeyStep },
        fine: t('frModelsFine'),
        t,
      },
        h(OwnKeyStep, { t, onDone: onOwnDone }))
    } else if (stage === 'permissions') {
      body = h(PermissionsPage, { t, name, onDone: permissionsDone })
    } else {
      body = h(Page, {
        hero: h(Avatar, { size: 104, profile, mood: 'happy' }),
        title: t('frMeetTitle', { name }),
        sub: t('frMeetSub'),
        primary: { label: t('frStart'), onClick: start },
        fine: t('frMeetFine'),
        t,
      })
    }

    return createPortal(
      h('div', { ref: layer, tabIndex: -1, className: `nm-ob${fading ? ' nm-ob-fading' : ''}`, role: 'dialog', 'aria-modal': true, 'aria-label': t('frWelcomeTitle'), 'data-shortcut-modal': 'onboarding' },
        h('div', { className: 'nm-ob-drag', 'data-window-drag': true }),
        h('div', { className: 'nm-fr-top' },
          h(Dots, { count: 3, index: dotOf(stage) }),
          h('button', { type: 'button', className: 'nm-fr-gear', 'aria-label': t('frSettings'), title: t('frSettings'), onClick: () => { openSection('general'); finish() } }, h(IconSettings, { size: 18 }))),
        h('div', { className: 'nm-fr-scroll' }, body)),
      document.body)
  }
}

function Dots({ count, index }: { count: number; index: number }): ReactNode {
  return h('div', { className: 'nm-fr-dots', 'aria-hidden': true },
    Array.from({ length: count }, (_, i) => h('span', { key: i, className: `nm-fr-dot${i === index ? ' nm-on' : ''}` })))
}

/**
 * One page as the phone lays it out: a hero, a title, a line under it, the content, the
 * primary pill, a plain-text secondary, fine print, and "Learn more" when there is a page.
 */
function Page({ hero, title, sub, children, primary, secondary, fine, learnMore, t }: {
  hero?: ReactNode
  title: string
  sub: string
  children?: ReactNode
  primary?: { label: string; onClick(): void; disabled?: boolean } | undefined
  secondary?: { label: string; onClick(): void } | undefined
  fine?: string | undefined
  learnMore?: string | undefined
  t: Translate
}): ReactNode {
  return h('div', { className: 'nm-ob-center nm-fr-page' },
    hero ?? null,
    h('h1', { className: 'nm-ob-title nm-ob-title-sm' }, title),
    h('p', { className: 'nm-ob-sub' }, sub),
    children ?? null,
    primary ? h(Pill, { onClick: primary.onClick, disabled: primary.disabled, className: 'nm-ob-wide nm-fr-primary' }, primary.label) : null,
    secondary ? h('button', { type: 'button', className: 'nm-ob-skip', onClick: secondary.onClick }, secondary.label) : null,
    fine ? h('p', { className: 'nm-ob-fine' }, fine, learnMore ? h(Fragment, null, ' ', link(learnMore, t('frLearnMore'))) : null) : null)
}

function FeatureRow({ icon, title, sub }: { icon: ReactNode; title: string; sub: string }): ReactNode {
  return h('div', { className: 'nm-fr-feature' },
    h('span', { className: 'nm-ob-row-icon' }, icon),
    h('div', { className: 'nm-ob-row-main' },
      h('div', { className: 'nm-ob-row-title' }, title),
      h('div', { className: 'nm-ob-row-sub' }, sub)))
}

/** One of the two ways on the "Which model answers?" page: a card that is a button. */
function ChoiceRow({ title, sub, onClick, disabled = false }: { title: string; sub: string; onClick(): void; disabled?: boolean }): ReactNode {
  return h('button', { type: 'button', className: 'nm-fr-choice', onClick, disabled },
    h('div', { className: 'nm-ob-row-main' },
      h('div', { className: 'nm-ob-row-title' }, title),
      h('div', { className: 'nm-ob-row-sub' }, sub)))
}

function PermissionRow({ t, kind, icon, title, sub, perms }: { t: Translate; kind: PermissionKind; icon: ReactNode; title: string; sub: string; perms: Permissions }): ReactNode {
  const granted = perms.granted(kind)
  return h('div', { className: 'nm-ob-row' },
    h('span', { className: 'nm-ob-row-icon' }, icon),
    h('div', { className: 'nm-ob-row-main' },
      h('div', { className: 'nm-ob-row-title' }, title),
      h('div', { className: 'nm-ob-row-sub' }, sub)),
    granted
      ? h('span', { className: 'nm-fr-granted' }, h(IconCheck, { size: 15 }), h('span', null, t('frAllowed')))
      : perms.asked(kind) && gatedPermissions()
        // a second press cannot bring the system's dialog back: the pane is where the switch is
        ? h(Pill, { small: true, ghost: true, onClick: () => perms.settings(kind) }, t('frSetUp'))
        : h(Pill, { small: true, onClick: () => perms.allow(kind) }, t('frTurnOn')))
}

/** macOS applies Screen Recording only to processes started after the grant: the notice and the restart. */
export function RelaunchNotice({ t, perms }: { t: Translate; perms: Permissions }): ReactNode {
  if (!perms.needsRelaunch) return null
  return h('div', { className: 'nm-ob-relaunch', role: 'status' },
    h('span', null, t('obRelaunch')),
    h(Pill, { small: true, onClick: () => perms.relaunch() }, t('obRelaunchNow')))
}

/**
 * macOS: Accessibility for clicking and typing, Screen Recording for the screenshots the
 * hands look at. "Continue" once both are on, "Skip for now" until then; either way the page
 * is seen once. (Where nothing is gated the stage never comes up.)
 */
function PermissionsPage({ t, name, onDone }: { t: Translate; name: string; onDone(): void }): ReactNode {
  const perms = usePermissions(['accessibility', 'screen'])
  const done = perms.granted('accessibility') && perms.granted('screen')
  return h(Page, {
    // the app asks for the permissions, so the app's mark is the hero (the hand stays on the rows)
    hero: h(BrandMark, { size: 72, className: 'nm-fr-hero-mark' }),
    title: t('frHandsTitle'),
    sub: t('frHandsSub'),
    primary: done ? { label: t('frContinue'), onClick: onDone } : undefined,
    secondary: done ? undefined : { label: t('frSkip'), onClick: onDone },
    fine: t('frHandsFine'),
    learnMore: HANDS_URL,
    t,
  },
    h('div', { className: 'nm-ob-card' },
      h(PermissionRow, { t, kind: 'accessibility', icon: h(IconHand, { size: 18 }), title: permissionTitle(t, 'accessibility'), sub: permissionSub(t, 'accessibility', name), perms }),
      h(PermissionRow, { t, kind: 'screen', icon: h(IconMonitor, { size: 18 }), title: permissionTitle(t, 'screen'), sub: permissionSub(t, 'screen', name), perms })),
    h(RelaunchNotice, { t, perms }),
    // the two checks from Settings → Computer use: a test screenshot (black = Screen Recording
    // not in effect yet) and a small mouse move (fails without Accessibility)
    h(BlackScreenNotice, { t, perms, compact: true }),
    h('div', { className: 'nm-ob-card' }, h(HandsTryRows, { t, perms })))
}
