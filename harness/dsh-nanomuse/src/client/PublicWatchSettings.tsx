import { createElement as h, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { failureText, type Translate } from './api.ts'
import { openLink } from './bridge.ts'
import type { Words } from './locales.ts'
import { roomsCall } from './rooms.ts'
import { Sheet } from './ui.tsx'

const kinds = {
  github_repo: ['watchRepository', 'watchRepositoryField'],
  github_user: ['watchAccount', 'watchAccountField'],
  research_work: ['watchCitations', 'watchDoiField'],
  research_author: ['watchResearcher', 'watchAuthorField'],
  research_topic: ['watchTopic', 'watchTopicField'],
  feed: ['watchFeed', 'watchFeedField'],
} as const

type Kind = keyof typeof kinds
type Source = {
  id: string; kind: Kind | 'scholar_profile'; target: string; label: string
  origin?: 'chat' | 'recurring' | 'connected' | 'manual'
  status: 'active' | 'suggested' | 'paused'; last_checked: string | null; unavailable: boolean
}
type View = { enabled: boolean; share_public_updates?: boolean; can_share?: boolean; revision: string; watches: Source[] }
type Edit = { enabled: boolean } | { share_public_updates: boolean } | { kind: Kind; target: string } |
  { id: string; action: 'confirm' | 'dismiss' | 'pause' | 'resume'; kind?: Kind; target?: string }

function action(t: Translate, key: Words, click: () => void, disabled = false) {
  return h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled, onClick: click }, t(key))
}

function TargetForm({ t, scholar, disabled, onSave, onCancel }: {
  t: Translate; scholar: boolean; disabled: boolean; onSave(kind: Kind, target: string): void; onCancel(): void
}): ReactNode {
  const options: Kind[] = scholar ? ['research_author', 'research_work'] : Object.keys(kinds) as Kind[]
  const [kind, setKind] = useState<Kind>(scholar ? 'research_author' : 'github_repo')
  const [target, setTarget] = useState('')
  return h('form', { className: 'nm-sheet-form', onSubmit: (e: FormEvent) => {
    e.preventDefault()
    if (!disabled && target.trim()) onSave(kind, target.trim())
  } },
    scholar ? h('p', { className: 'nm-sheet-fine' }, t('watchLinkHelp')) : null,
    h('label', null, t('watchKind'),
      h('select', { className: 'nm-field', value: kind, disabled, onChange: (e: FormEvent<HTMLSelectElement>) => {
        setKind(e.currentTarget.value as Kind); setTarget('')
      } }, options.map(k => h('option', { key: k, value: k }, t(kinds[k][0]))))),
    h('label', null, t(kinds[kind][1]),
      h('input', { className: 'nm-field', value: target, disabled, required: true, maxLength: 512,
        autoCapitalize: 'none', spellCheck: false, autoComplete: 'off',
        onChange: (e: FormEvent<HTMLInputElement>) => setTarget(e.currentTarget.value) })),
    h('div', { className: 'nm-sheet-actions' }, action(t, 'cancel', onCancel, disabled),
      h('button', { className: 'nm-pill nm-pill-sm', type: 'submit', disabled: disabled || !target.trim() },
        t(scholar ? 'watchLinkFollow' : 'watchFollow'))))
}

export function PublicWatchRow({ t, source, off, busy, linking, onLink, onCancel, save }: {
  t: Translate; source: Source; off: boolean; busy: boolean; linking: boolean
  onLink(): void; onCancel(): void; save(edit: Edit): void
}): ReactNode {
  const suggested = source.status === 'suggested'
  const paused = source.status === 'paused'
  const scholar = source.kind === 'scholar_profile'
  const follow = () => {
    if (scholar) onLink()
    else void save({ id: source.id, action: 'confirm' })
  }
  // The identifier is provided by the local worker. Never navigate to an arbitrary
  // URL supplied by a source or contact Scholar until the person opens its profile.
  const scholarUrl = scholar && /^[A-Za-z0-9_-]{8,32}$/.test(source.target)
    ? 'https://scholar.google.com/citations?user=' + encodeURIComponent(source.target) : ''
  return h('section', { className: 'nm-sheet-form', key: source.id, 'aria-label': source.label || source.target },
    h('strong', { style: { overflowWrap: 'anywhere' } }, source.label || source.target),
    h('p', { className: 'nm-sheet-fine' },
      t(source.kind === 'scholar_profile' ? 'watchScholar' : kinds[source.kind][0]), ' · ',
      t(suggested ? 'watchSuggested' : paused || off ? 'watchPaused' : 'watchFollowing')),
    source.origin ? h('p', { className: 'nm-sheet-fine' },
      t(({ chat: 'watchFromChat', recurring: 'watchFromRecurring', connected: 'watchFromConnected', manual: 'watchFromManual' } as const)[source.origin])) : null,
    source.last_checked ? h('p', { className: 'nm-sheet-fine' }, t('watchLast', { time: new Date(source.last_checked).toLocaleString() })) : null,
    source.unavailable ? h('p', { className: 'nm-sheet-fine' }, t('watchUnavailable')) : null,
    h('div', { className: 'nm-sheet-actions', style: { flexWrap: 'wrap' } },
      scholarUrl ? action(t, 'watchOpenScholar', () => openLink(scholarUrl)) : null,
      suggested
        ? action(t, scholar ? 'watchLink' : 'watchFollow', follow, busy || off)
        : action(t, paused ? 'watchResume' : 'watchPause', () => void save({ id: source.id, action: paused ? 'resume' : 'pause' }), busy || (off && paused)),
      action(t, suggested ? 'watchDismiss' : 'watchStop', () => void save({ id: source.id, action: 'dismiss' }), busy)),
    scholar && suggested && linking
      ? h(TargetForm, { key: source.id, t, scholar: true, disabled: busy || off, onCancel,
          onSave: (kind, target) => void save({ id: source.id, action: 'confirm', kind, target }) })
      : null)
}

export function PublicWatchSettings({ t, scope, checksOn, onClose }: {
  t: Translate; scope: string; checksOn: boolean; onClose(): void
}): ReactNode {
  const [view, setView] = useState<View | null>(null)
  const [reload, setReload] = useState(0)
  const [error, setError] = useState('')
  const [writing, setWriting] = useState(false)
  const [stale, setStale] = useState(false)
  const busy = writing || stale
  const [form, setForm] = useState<string | null>(null)
  const saving = useRef(false)
  const live = useRef(false)
  const route = 'feed/public-watches'
  useEffect(() => {
    live.current = true
    let current = true
    roomsCall<View>(route, { scope })
      .then(data => { if (current) { setView(data); setStale(false) } })
      .catch(e => { if (current) setError(failureText(t, e)) })
    return () => { current = false; live.current = false }
  }, [scope, reload])
  const save = async (edit: Edit) => {
    if (!view || stale || saving.current) return
    saving.current = true
    setWriting(true)
    setError('')
    try {
      const updated = await roomsCall<View>(route, { ...edit, revision: view.revision, scope })
      if (live.current) { setView(updated); setForm(null) }
    } catch (e) {
      if (live.current) {
        // A lost response or a concurrent edit can invalidate the previous revision.
        setError(failureText(t, e)); setStale(true); setReload(n => n + 1)
      }
    } finally {
      saving.current = false
      if (live.current) setWriting(false)
    }
  }
  return h(Sheet, { title: t('watchTitle'), closeLabel: t('close'), onClose },
    h('div', { className: 'nm-sheet-form' },
      error ? h('div', { className: 'nm-room-error', role: 'alert' }, error, !view || stale
        ? action(t, 'refresh', () => { setError(''); setReload(n => n + 1) }) : null) : null,
      view
        ? h('label', { className: 'nm-feed-routine' },
            h('input', { type: 'checkbox', checked: view.enabled, disabled: busy,
              onChange: (e: FormEvent<HTMLInputElement>) => void save({ enabled: e.currentTarget.checked }) }),
            h('span', null, t('watchEnabled')))
        : !error ? h('p', { className: 'nm-sheet-fine', role: 'status' }, t('loading')) : null,
      view ? h('p', { className: 'nm-sheet-fine' }, t(!checksOn && view.enabled ? 'watchChecksOff' : 'watchAbout')) : null,
      typeof view?.share_public_updates === 'boolean'
        ? h('label', { className: 'nm-feed-routine' },
            h('input', { type: 'checkbox', checked: view.share_public_updates, disabled: busy || !view.can_share,
              onChange: (e: FormEvent<HTMLInputElement>) => void save({ share_public_updates: e.currentTarget.checked }) }),
            h('span', null, t('watchShare'))) : null,
      typeof view?.share_public_updates === 'boolean' ? h('p', { className: 'nm-sheet-fine' }, t(view.can_share ? 'watchShareHint' : 'watchShareSignIn')) : null,
      view?.watches.map(source => h(PublicWatchRow, { key: source.id, t, source, off: !view.enabled, busy,
        linking: form === source.id, onLink: () => setForm(source.id), onCancel: () => setForm(null), save })),
      view?.enabled && (form === 'new'
        ? h(TargetForm, { t, scholar: false, disabled: busy, onCancel: () => setForm(null),
            onSave: (kind, target) => void save({ kind, target }) })
        : action(t, 'watchAdd', () => setForm('new'), busy))))
}
