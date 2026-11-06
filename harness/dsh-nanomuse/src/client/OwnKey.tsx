/**
 * Own keys with capabilities (contract C11), the browser half.
 *
 * One catalogue (`assets/providers.json`, read through the host's `GET /providers`) drives
 * three places: the onboarding's own-key step, Settings → Account's "ways on", and the model
 * pickers on Settings → Models (`ModelsSection.tsx`). Rows are grouped — the person's region first (mainland China: Bailian, one key for
 * chat, hands, pictures and clips; elsewhere: OpenRouter, then OpenAI), then the subscriptions
 * one can sign in with, then the rest ordered by how much they cover, then servers on this
 * computer, then any OpenAI-compatible endpoint by hand. Each row says what it covers (`chat ·
 * screen operation · pictures · clips`), links to where the key is handed out, and takes the
 * key inline; *Sign in with ChatGPT* runs the runtime's flow through the host.
 *
 * The gate: the pickers list only models of providers that have the capability; a
 * capability nobody has is one sentence naming the catalogue's providers for the region
 * (`ownKeyNoImage`, `ownKeyNoVideo`, `ownKeyNoVision`; with only the ChatGPT sign-in,
 * `ownKeyChatGptNoMedia`), never a raw error. After a key is saved, the "Use it for" card
 * (0.1.41) offers the slots the row could take. Mounted in `CloudSection.tsx` (Settings →
 * Account, signed in or out), `Onboarding.tsx` (the own-key step), `AvatarStudio.tsx` and
 * `MediaSection.tsx` (the sentences for pictures and clips).
 */
import { createElement as h, Fragment, useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { baseUrlFor, isLocal, keyUrlFor, ownKeyStepDone, providersWith, unavailableKey, waysOn, type Capability, type ProviderEntry, type Region, type WaysOn } from '../catalogue.ts'
import { call, errorCode, errorStyle, muted, row, type Translate, failureText } from './api.ts'
import { openLink } from './bridge.ts'
import { settingsBus } from './bus.ts'
import { IconCheck, IconExternal, IconGlobe, IconHand, IconImage, IconKey, IconMessage, IconUser, IconVideo } from './icons.tsx'
import { useLive } from './live.ts'

export type { Capability, ProviderEntry, Region }

/** The settings section the "ways on" live in (Settings → Account). */
export const ACCOUNT_SECTION = 'nanomuse-cloud'

/** An own-key row as the host keeps it in `cloud.json` (`src/providers.ts` `OwnProvider`): never a key. */
export interface OwnProvider {
  /** The row's own id: the catalogue id for a vendor; `custom`, `custom-2`, ... for hand-made endpoints, several at once (#294). */
  id: string
  provider: string
  label: string
  protocol: string
  baseURL: string
  keyRef: string
  capabilities: Capability[]
  models: { id: string; name: string; vision: boolean; kind: 'chat' | 'image' | 'video' }[]
  at: number
}

export interface LoginView { status: 'idle' | 'waiting' | 'done' | 'error'; url: string; label: string; error: string }

/** `GET /providers`. */
export interface ProvidersView {
  region: Region
  catalogue: ProviderEntry[]
  configured: OwnProvider[]
  capabilities: Capability[]
  cloud: { signedIn: boolean; capabilities: Capability[] }
  chatgpt: { signedIn: boolean; label: string; proxy: boolean; login: LoginView; runtime: boolean }
  hands: { provider: string; model: string }
  chat: { provider: string; model: string }
}

export interface ModelOption { provider: string; providerLabel: string; id: string; name: string; /** The relay's recommended one for that lane. */ recommended?: boolean }

const CAPS: Capability[] = ['chat', 'vision', 'image', 'video']

/** Keep API-key entries visible even when the same provider also offers subscription sign-in. */
export function groupsOf(catalogue: ProviderEntry[], region: Region): WaysOn {
  const groups = waysOn(catalogue, region)
  return {
    ...groups,
    signIn: groups.signIn.filter((entry) => !entry.auth.includes('key')),
    rest: [...groups.signIn.filter((entry) => entry.auth.includes('key')), ...groups.rest],
  }
}

/** `GET /providers`, again whenever the host's live state says the rows or the sign-in moved. */
export function useProviders(t: Translate): { view: ProvidersView | undefined; error: string | undefined; reload(): void } {
  const live = useLive()
  const [view, setView] = useState<ProvidersView | undefined>()
  const [error, setError] = useState<string | undefined>()
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((n) => n + 1), [])
  const own = live.ownKeys
  const key = own ? `${own.count}|${own.chatgpt.signedIn}|${own.chatgpt.proxy}|${own.chatgpt.login.status}|${own.capabilities.join(',')}` : ''
  const signedIn = live.cloud.signedIn
  useEffect(() => {
    let alive = true
    call<ProvidersView>(`providers?lang=${encodeURIComponent(t('langTag'))}`)
      .then((v) => { if (alive) { setView(v); setError(undefined) } })
      .catch((err: unknown) => { if (alive) setError(failureText(t, err)) })
    return () => { alive = false }
  }, [t, tick, key, signedIn])
  return { view, error, reload }
}

const nameOf = (t: Translate, p: ProviderEntry): string => (t('langTag') === 'zh' ? p.name_zh : p.name)
const noteOf = (t: Translate, p: ProviderEntry): string => (t('langTag') === 'zh' ? p.note_zh : p.note)

/** `chat · screen operation · pictures · clips`, the ones a row covers. */
export function coverage(t: Translate, caps: Capability[]): string {
  const word: Record<Capability, string> = { chat: t('ownKeyCovChat'), vision: t('ownKeyCovVision'), image: t('ownKeyCovImage'), video: t('ownKeyCovVideo') }
  return CAPS.filter((c) => caps.includes(c)).map((c) => word[c]).join(' · ')
}

/** The providers of the catalogue that have a capability where the person is, named in one list. */
export function providersNamed(t: Translate, view: Pick<ProvidersView, 'catalogue' | 'region'>, capability: Capability): string {
  const names = providersWith(view.catalogue, capability, view.region).map((p) => nameOf(t, p))
  return names.length ? names.join(t('langTag') === 'zh' ? '、' : ', ') : t('ownKeyNone')
}

/**
 * The one sentence for a capability nothing configured has (C11): who could, where the person
 * is; with only the ChatGPT sign-in, that pictures and clips are not covered by it (the key is
 * `unavailableKey`'s, in `src/catalogue.ts`). Nothing when something configured has the
 * capability. `link` adds the way to Settings → Account's rows.
 */
export function unavailableText(t: Translate, view: Pick<ProvidersView, 'catalogue' | 'region' | 'capabilities' | 'configured' | 'cloud' | 'chatgpt'>, capability: Capability): string | null {
  const key = unavailableKey(view, capability)
  return key === null ? null : t(key, { providers: providersNamed(t, view, capability) })
}

export function UnavailableLine({ t, view, capability, link = false, className = 'nm-way-sub nm-wrap', tag = 'div' }: { t: Translate; view: ProvidersView; capability: Capability; link?: boolean; className?: string; tag?: 'div' | 'span' }): ReactNode {
  const text = unavailableText(t, view, capability)
  if (text === null) return null
  return h(tag, { className, style: muted, 'data-testid': `nm-unavailable-${capability}` },
    text,
    link ? h(Fragment, null, ' ', h('button', { type: 'button', className: 'nm-ob-link nm-inline', onClick: () => { settingsBus.openSection?.(ACCOUNT_SECTION) } }, t('ownKeyOpenWays'))) : null)
}

// ---- one row -----------------------------------------------------------------------------------

function KeyForm({ t, entry, region, configured, onSaved, onCancel }: { t: Translate; entry: ProviderEntry; region: Region; configured: OwnProvider | undefined; onSaved(said: string, got: { id: string; label: string; offer: SlotOffer }): void; onCancel(): void }): ReactNode {
  const base = baseUrlFor(entry, region)
  const [apiKey, setApiKey] = useState('')
  const [baseURL, setBaseURL] = useState(configured?.baseURL ?? base)
  const [label, setLabel] = useState(configured?.label ?? '')
  const [caps, setCaps] = useState<Capability[]>(configured?.capabilities ?? ['chat'])
  // the model ids typed for an endpoint that does not list its own (`no_models` from the host asks for them)
  const [models, setModels] = useState('')
  const [askModels, setAskModels] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const needsKey = !entry.auth.includes('none')
  const editable = entry.user_capabilities || isLocal(entry) || !entry.base_url
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    const body: Record<string, unknown> = { id: entry.id, apiKey, lang: t('langTag') }
    // a hand-made endpoint changed stays the row it is; without `row` the host adds another (#294)
    if (configured && entry.user_capabilities) body.row = configured.id
    if (editable) body.baseURL = baseURL
    if (entry.user_capabilities) { body.capabilities = caps; body.label = label }
    if (entry.user_capabilities && models.trim()) body.models = models
    call<OwnProvider & { offer?: SlotOffer }>('providers/save', body)
      .then((saved) => onSaved(saved.models.length ? t('ownKeySaved', { n: saved.models.length }) : t('ownKeySavedNone'), { id: saved.id || entry.id, label: saved.label, offer: saved.offer ?? {} }))
      .catch((err: unknown) => {
        if (errorCode(err) === 'no_models') { setAskModels(true); setError(t('ownKeyNoModels')); return }
        setError(failureText(t, err))
      })
      .finally(() => setBusy(false))
  }
  const capWord: Record<Capability, string> = { chat: t('ownKeyCovChat'), vision: t('ownKeyCovVision'), image: t('ownKeyCovImage'), video: t('ownKeyCovVideo') }
  return h('form', { className: 'nm-ownkey-form', style: { display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }, onSubmit: submit },
    editable
      ? h('input', { className: 'nm-field', value: baseURL, placeholder: t('ownKeyBaseField'), 'aria-label': t('ownKeyBaseField'), autoComplete: 'off', spellCheck: false, onChange: (e: FormEvent<HTMLInputElement>) => setBaseURL(e.currentTarget.value) })
      : null,
    entry.user_capabilities
      ? h('input', { className: 'nm-field', value: label, placeholder: t('ownKeyLabelField'), 'aria-label': t('ownKeyLabelField'), onChange: (e: FormEvent<HTMLInputElement>) => setLabel(e.currentTarget.value) })
      : null,
    h('input', { className: 'nm-field', type: 'password', value: apiKey, placeholder: entry.key_hint || t('ownKeyKeyField'), 'aria-label': t('ownKeyKeyField'), autoComplete: 'off', spellCheck: false, autoFocus: true, onChange: (e: FormEvent<HTMLInputElement>) => setApiKey(e.currentTarget.value) }),
    entry.user_capabilities && (askModels || models)
      ? h('input', { className: 'nm-field', value: models, placeholder: t('ownKeyModelsField'), 'aria-label': t('ownKeyModelsField'), autoComplete: 'off', spellCheck: false, 'data-testid': 'nm-ownkey-models', onChange: (e: FormEvent<HTMLInputElement>) => setModels(e.currentTarget.value) })
      : null,
    entry.user_capabilities
      ? h('div', { style: row },
          h('span', { style: muted }, t('ownKeyCapsField')),
          CAPS.map((c) => h('label', { key: c, style: { display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: 13 } },
            h('input', { type: 'checkbox', checked: caps.includes(c), disabled: c === 'chat', onChange: () => setCaps((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c])) }),
            capWord[c])))
      : null,
    error ? h('div', { style: errorStyle }, error) : null,
    h('div', { style: row },
      h('button', { type: 'submit', className: 'nm-pill nm-pill-sm', disabled: busy || (needsKey && !apiKey.trim()) || (editable && !/^https?:\/\//.test(baseURL.trim())) }, busy ? t('sending') : configured ? t('ownKeyChange') : needsKey ? t('ownKeyAdd') : t('ownKeyConnect')),
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: busy, onClick: onCancel }, t('cancel'))))
}

/** The ChatGPT sign-in: the row under OpenAI (or on its own in the sign-in group), with the honesty line. */
export function ChatGptRow({ t, view, onChanged }: { t: Translate; view: ProvidersView; onChanged(said?: string): void }): ReactNode {
  const live = useLive()
  const cg = live.ownKeys?.chatgpt ?? view.chatgpt
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const signIn = () => {
    setBusy(true)
    setError(undefined)
    call<{ url: string }>('chatgpt/login', {})
      .then((r) => { if (r.url) openLink(r.url) })
      // `no_runtime` reaches the row through the live state's `login.error` already
      .catch((err: unknown) => { if ((err as Error).message !== 'no_runtime') setError(failureText(t, err)) })
      .finally(() => setBusy(false))
  }
  const signOut = () => {
    setBusy(true)
    call('chatgpt/logout', {}).then(() => onChanged()).catch((err: unknown) => setError(failureText(t, err))).finally(() => setBusy(false))
  }
  const cancel = () => { void call('chatgpt/cancel', {}).catch(() => undefined) }
  const login = cg.login
  let state: ReactNode
  if (cg.signedIn) {
    state = h('div', { className: 'nm-way-sub', style: { color: 'var(--nm-green, #10b981)' } }, h(IconCheck, { size: 13 }), ' ', cg.proxy ? t('ownKeyChatGptDone', { label: cg.label || 'ChatGPT' }) : t('ownKeyChatGptProxyDown', { label: cg.label || 'ChatGPT' }))
  } else if (login.status === 'waiting') {
    state = h('div', { className: 'nm-way-sub nm-wrap' }, t('ownKeyChatGptWaiting'))
  } else if (login.status === 'error') {
    state = h('div', { style: errorStyle }, chatGptLoginError(t, login.error))
  } else if (!view.chatgpt.runtime) {
    state = h('div', { className: 'nm-way-sub nm-wrap' }, t('ownKeyNoRuntime'))
  }
  return h('div', { className: `nm-way nm-way-card${cg.signedIn ? ' nm-way-ready' : ''}${error || login.status === 'error' ? ' nm-way-error' : ''}` },
    h('span', { className: 'nm-way-icon', style: cg.signedIn ? { color: 'var(--nm-green, #10b981)', background: 'color-mix(in srgb, #10b981 12%, transparent)' } : undefined }, cg.signedIn ? h(IconCheck, { size: 15 }) : h(IconUser, { size: 15 })),
    h('div', { className: 'nm-way-main', style: { flex: 1, minWidth: 0 } },
      h('div', { className: 'nm-way-title', style: { display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '4px 8px' } },
        h('span', { style: { fontWeight: 600 } }, t('ownKeyChatGptRow')),
        h('span', { style: { ...muted, fontSize: 12 } }, coverage(t, ['chat', 'vision'])),
        cg.signedIn ? h('span', { style: { fontSize: 11, padding: '1px 6px', borderRadius: 4, background: 'color-mix(in srgb, #10b981 15%, transparent)', color: 'var(--nm-green, #10b981)' } }, t('ownKeyConfigured')) : null
      ),
      h('div', { className: 'nm-way-sub nm-wrap' }, t('ownKeyChatGptSub')),
      h('div', { className: 'nm-way-sub nm-wrap', style: { ...muted, fontSize: 12 } }, t('ownKeyChatGptHonesty')),
      state,
      error ? h('div', { style: errorStyle }, error) : null),
    h('div', { className: 'nm-way-actions' },
      cg.signedIn
        ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: busy, onClick: signOut }, t('ownKeySignOut'))
        : login.status === 'waiting'
          ? h(Fragment, null,
              login.url ? h('button', { type: 'button', className: 'nm-pill nm-pill-sm', onClick: () => openLink(login.url) }, t('ownKeyChatGptOpen')) : null,
              h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: cancel }, t('ownKeyChatGptCancel')))
          : h('button', { type: 'button', className: 'nm-pill nm-pill-sm', disabled: busy || !view.chatgpt.runtime, onClick: signIn }, t('ownKeySignIn'))))
}

// ---- the "Use it for" card ------------------------------------------------------------------------

export type Slot = 'chat' | 'hands' | 'image' | 'video'
const SLOTS: readonly Slot[] = ['chat', 'hands', 'image', 'video']
/** What a saved row could take and the model each slot would get (`POST /providers/save` → `offer`). */
export type SlotOffer = Partial<Record<Slot, string>>

/**
 * After a key is saved (contract section 2): one toggle per slot the row has a model for, all
 * on; *Use it* switches the ticked slots to the row through the Models page's own setters
 * (`POST /providers/adopt`), *Not now* leaves everything as it is. The footnote says where to
 * change it later. Unticked slots stay exactly as they were.
 */
export function UseItCard({ t, id, label, offer, signedIn, onDone }: { t: Translate; id: string; label: string; offer: SlotOffer; signedIn: boolean; onDone(said?: string): void }): ReactNode {
  const slots = SLOTS.filter((s) => offer[s])
  const [ticked, setTicked] = useState<Slot[]>(slots)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const title = (s: Slot) => (s === 'chat' ? t('mlChat') : s === 'hands' ? t('mlHands') : s === 'image' ? t('mlImage') : t('mlVideo'))
  const use = () => {
    setBusy(true)
    setError(undefined)
    call<{ done: SlotOffer }>('providers/adopt', { id, slots: ticked })
      .then((r) => onDone(Object.keys(r.done).length ? t('useItDone', { label }) : undefined))
      .catch((err: unknown) => setError(failureText(t, err)))
      .finally(() => setBusy(false))
  }
  if (!slots.length) return null
  return h('div', { className: 'nm-card nm-useit', 'data-testid': 'nm-useit', style: { marginTop: 8, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 } },
    h('div', { style: { fontWeight: 600 } }, t('useItTitle')),
    h('div', { className: 'nm-wrap', style: muted }, signedIn ? t('useItBody') : t('useItBodyOut')),
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
      slots.map((s) => h('label', { key: s, style: { display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 } },
        h('input', { type: 'checkbox', 'data-testid': `nm-useit-${s}`, checked: ticked.includes(s), disabled: busy, onChange: () => setTicked((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s])) }),
        h('span', null, title(s)),
        h('span', { style: muted }, `${label} · ${offer[s]}`)))),
    error ? h('div', { style: errorStyle }, error) : null,
    h('div', { style: row },
      h('button', { type: 'button', className: 'nm-pill nm-pill-sm', disabled: busy || !ticked.length, onClick: use }, busy ? t('sending') : t('useItUse')),
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: busy, onClick: () => onDone() }, t('useItNotNow'))),
    h('div', { className: 'nm-wrap', style: { ...muted, fontSize: 12 } }, t('useItFoot')))
}

/**
 * One catalogue entry's row: the vendor's name, what it covers, the key form. `own` names the
 * saved row it stands for; by default the one whose `provider` is the entry. A hand-made
 * endpoint is one row per saved endpoint (#294): each with its own name over its host, a
 * *Rename* beside *Change key* and *Remove*; `own: null` is the row that adds another.
 */
export function ProviderRow({ t, entry, view, own, onChanged }: { t: Translate; entry: ProviderEntry; view: ProvidersView; own?: OwnProvider | null; onChanged(said?: string): void }): ReactNode {
  const configured = own === null ? undefined : (own ?? view.configured.find((p) => p.provider === entry.id))
  const rowId = configured?.id ?? entry.id
  const [open, setOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [label, setLabel] = useState(configured?.label ?? '')
  const [said, setSaid] = useState<string | undefined>()
  const [offer, setOffer] = useState<{ id: string; label: string; offer: SlotOffer } | undefined>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const keyUrl = keyUrlFor(entry, view.region)
  const needsKey = !entry.auth.includes('none')
  // a hand-made endpoint: the row reads as its name (or host); the adding row as the entry
  const several = Boolean(entry.user_capabilities)
  const title = several && configured ? configured.label || hostOf(configured.baseURL) : nameOf(t, entry)
  const remove = () => {
    setBusy(true)
    setError(undefined)
    call<{ cloudModelsOn?: boolean } | undefined>('providers/remove', { id: rowId })
      // the row was the last chat source while the account's models were off: they are on again, said once here
      .then((r) => { setSaid(r?.cloudModelsOn ? t('ownKeyRemovedCloudOn') : undefined); setOffer(undefined); onChanged() })
      .catch((err: unknown) => setError(failureText(t, err))).finally(() => setBusy(false))
  }
  const rename = (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    call<OwnProvider>('providers/rename', { id: rowId, label, lang: t('langTag') })
      .then((r) => { setRenaming(false); setLabel(r.label); onChanged() })
      .catch((err: unknown) => setError(failureText(t, err))).finally(() => setBusy(false))
  }
  return h('div', { className: `nm-way nm-way-card${configured ? ' nm-way-ready' : ''}${error ? ' nm-way-error' : ''}`, 'data-testid': several && configured ? `nm-way-${rowId}` : undefined },
    h('span', { className: 'nm-way-icon', style: configured ? { color: 'var(--nm-green, #10b981)', background: 'color-mix(in srgb, #10b981 12%, transparent)' } : undefined }, configured ? h(IconCheck, { size: 15 }) : h(IconKey, { size: 15 })),
    h('div', { className: 'nm-way-main', style: { flex: 1, minWidth: 0 } },
      h('div', { className: 'nm-way-title', style: { display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '4px 8px' } },
        h('span', { style: { fontWeight: 600 } }, title),
        h('span', { style: { ...muted, fontSize: 12 } }, coverage(t, configured?.capabilities ?? entry.capabilities)),
        configured ? h('span', { style: { fontSize: 11, padding: '1px 6px', borderRadius: 4, background: 'color-mix(in srgb, #10b981 15%, transparent)', color: 'var(--nm-green, #10b981)' } }, `${t('ownKeyConfigured')}${configured.models.length ? ` · ${configured.models.length}` : ''}`) : null
      ),
      several && configured ? h('div', { className: 'nm-way-sub nm-wrap', style: muted }, hostOf(configured.baseURL)) : null,
      open ? h('div', { className: 'nm-way-sub nm-wrap', style: muted }, noteOf(t, entry), entry.verified ? ` · ${t('ownKeyVerified', { month: entry.verified })}` : '') : null,
      said ? h('div', { className: 'nm-way-sub' }, said) : null,
      offer
        ? h(UseItCard, { t, id: offer.id, label: offer.label || nameOf(t, entry), offer: offer.offer, signedIn: view.cloud.signedIn, onDone: (text) => { setOffer(undefined); if (text) setSaid(text); onChanged(text) } })
        : null,
      error ? h('div', { style: errorStyle }, error) : null,
      renaming
        ? h('form', { style: { ...row, marginTop: 8 }, onSubmit: rename },
            h('input', { className: 'nm-field', value: label, placeholder: hostOf(configured?.baseURL ?? ''), 'aria-label': t('ownKeyLabelField'), autoFocus: true, onChange: (e: FormEvent<HTMLInputElement>) => setLabel(e.currentTarget.value) }),
            h('button', { type: 'submit', className: 'nm-pill nm-pill-sm', disabled: busy }, busy ? t('sending') : t('save')),
            h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: busy, onClick: () => { setRenaming(false); setLabel(configured?.label ?? '') } }, t('cancel')))
        : open
        ? h(KeyForm, { t, entry, region: view.region, configured, onSaved: (text, got) => { setOpen(false); setSaid(text); setOffer(Object.keys(got.offer).length ? got : undefined); onChanged(text) }, onCancel: () => setOpen(false) })
        : null),
    !open && !renaming
      ? h('div', { className: 'nm-way-actions' },
          h('button', { type: 'button', className: `nm-pill nm-pill-sm${configured ? ' nm-pill-ghost' : ''}`, disabled: busy, onClick: () => setOpen(true) }, configured ? t('ownKeyChange') : several ? t('ownKeyAddEndpoint') : needsKey ? t('ownKeyAdd') : t('ownKeyConnect')),
          keyUrl && needsKey ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm nm-pill-icon', title: t('ownKeyGetKey'), 'aria-label': t('ownKeyGetKey'), onClick: () => openLink(keyUrl) }, h(IconExternal, { size: 14 })) : null,
          several && configured ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: busy, onClick: () => setRenaming(true) }, t('ownKeyRename')) : null,
          configured ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: busy, onClick: remove }, t('ownKeyRemove')) : null)
      : null)
}

function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

// ---- the groups ----------------------------------------------------------------------------------

export type Group = 'signIn' | 'account' | 'first' | 'rest' | 'local' | 'custom'
export const ALL_GROUPS: Group[] = ['signIn', 'account', 'first', 'rest', 'local', 'custom']

/** The account's row, first while signed in: what nanoMuse Cloud covers right now (the relay's model list). */
function AccountRow({ t, view }: { t: Translate; view: ProvidersView }): ReactNode {
  return h('div', { className: 'nm-way nm-way-card nm-way-ready', 'data-testid': 'nm-way-account' },
    h('span', { className: 'nm-way-icon', style: { color: 'var(--nm-green, #10b981)', background: 'color-mix(in srgb, #10b981 12%, transparent)' } }, h(IconGlobe, { size: 15 })),
    h('div', { className: 'nm-way-main', style: { flex: 1, minWidth: 0 } },
      h('div', { className: 'nm-way-title', style: { display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '4px 8px' } },
        h('span', { style: { fontWeight: 600 } }, 'nanoMuse Cloud'),
        h('span', { style: { ...muted, fontSize: 12 } }, coverage(t, view.cloud.capabilities)),
        h('span', { style: { fontSize: 11, padding: '1px 6px', borderRadius: 4, background: 'color-mix(in srgb, #10b981 15%, transparent)', color: 'var(--nm-green, #10b981)' } }, t('ownKeyConfigured'))
      ),
      h('div', { className: 'nm-way-sub nm-wrap' }, t('ownKeyAccountSub'))))
}

/**
 * The rows, grouped. `groups` picks which to show: Settings → Account shows them all, the
 * account's row first while signed in; the own-key step shows the region's first group and the
 * sign-in row, the rest behind *More ways*.
 */
export function WaysOnRows({ t, view, groups = ALL_GROUPS, signInRow = true, headings = true, onChanged }: { t: Translate; view: ProvidersView; groups?: Group[]; /** false leaves the ChatGPT sign-in row out (the allowance card draws it under its own heading) */ signInRow?: boolean; headings?: boolean; onChanged(said?: string): void }): ReactNode {
  const [selectedCap, setSelectedCap] = useState<Capability | 'all'>('all')
  const g = useMemo(() => groupsOf(view.catalogue, view.region), [view.catalogue, view.region])
  const rowOf = (entry: ProviderEntry) => h(ProviderRow, { key: entry.id, t, entry, view, onChanged })
  const heading = (text: string) => (headings ? h('div', { className: 'nm-ways-lead', style: { marginTop: 10, marginBottom: 4 } }, text) : null)

  const filterPills = h('div', { className: 'nm-seg', style: { marginBottom: 12, flexWrap: 'wrap' } },
    h('button', {
      type: 'button',
      className: `nm-seg-btn${selectedCap === 'all' ? ' nm-active' : ''}`,
      onClick: () => setSelectedCap('all')
    }, t('ownKeyFilterAll')),
    (['chat', 'vision', 'image', 'video'] as const).map((cap) => {
      const icon = cap === 'chat' ? h(IconMessage, { size: 14 }) : cap === 'vision' ? h(IconHand, { size: 14 }) : cap === 'image' ? h(IconImage, { size: 14 }) : h(IconVideo, { size: 14 })
      const labelKey = cap === 'chat' ? 'ownKeyFilterChat' : cap === 'vision' ? 'ownKeyFilterVision' : cap === 'image' ? 'ownKeyFilterImage' : 'ownKeyFilterVideo'
      return h('button', {
        key: cap,
        type: 'button',
        className: `nm-seg-btn${selectedCap === cap ? ' nm-active' : ''}`,
        onClick: () => setSelectedCap(cap)
      }, h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 6 } }, icon, t(labelKey)))
    })
  )

  const chatgptEntry = signInRow ? view.catalogue.find((p) => p.auth.includes('oauth-chatgpt')) : undefined
  const out: ReactNode[] = [filterPills]

  if (selectedCap === 'all') {
    if (groups.includes('signIn') && (g.signIn.length || chatgptEntry)) {
      out.push(heading(t('ownKeySignInGroup')))
      if (chatgptEntry) out.push(h(ChatGptRow, { key: 'chatgpt', t, view, onChanged }))
      for (const p of g.signIn) if (!chatgptEntry || p.id !== chatgptEntry.id) out.push(rowOf(p))
    }
    if (groups.includes('account') && view.cloud.signedIn) {
      out.push(heading(t('ownKeyAccountGroup')))
      out.push(h(AccountRow, { key: 'account', t, view }))
    }
    if (groups.includes('first') && g.first.length) {
      const firstProviders = g.first
      if (firstProviders.length > 0) {
        out.push(heading(view.region === 'cn' ? t('ownKeyRegionCn') : t('ownKeyRegionGlobal')))
        for (const p of firstProviders) out.push(rowOf(p))
      }
    }
    if (groups.includes('rest') && g.rest.length) {
      const restProviders = g.rest
      if (restProviders.length > 0) {
        out.push(heading(t('ownKeyRestGroup')))
        for (const p of restProviders) out.push(rowOf(p))
      }
    }
    if (groups.includes('local') && g.local.length) {
      out.push(heading(t('ownKeyLocalGroup')))
      for (const p of g.local) out.push(rowOf(p))
    }
    if (groups.includes('custom') && g.custom) {
      const custom = g.custom
      out.push(heading(t('ownKeyCustomGroup')))
      for (const own of view.configured.filter((p) => p.provider === custom.id)) out.push(h(ProviderRow, { key: `custom:${own.id}`, t, entry: custom, view, own, onChanged }))
      out.push(h(ProviderRow, { key: 'custom:add', t, entry: custom, view, own: null, onChanged }))
    }
  } else {
    // Capability filter active
    const visible = [
      ...(groups.includes('first') ? g.first : []),
      ...(groups.includes('rest') ? g.rest : []),
      ...(groups.includes('local') ? g.local : []),
      ...(groups.includes('signIn') ? g.signIn : []),
    ]
    const matches = visible.filter((p) => p.capabilities.includes(selectedCap))
    const capTitle = t(selectedCap === 'chat' ? 'ownKeyFilterChat' : selectedCap === 'vision' ? 'ownKeyFilterVision' : selectedCap === 'image' ? 'ownKeyFilterImage' : 'ownKeyFilterVideo')
    if ((selectedCap === 'chat' || selectedCap === 'vision') && chatgptEntry && groups.includes('signIn')) {
      out.push(heading(t('ownKeySignInGroup')))
      out.push(h(ChatGptRow, { key: 'chatgpt', t, view, onChanged }))
    }
    const keyMatches = matches
    if (keyMatches.length > 0) {
      out.push(heading(`${capTitle} (${keyMatches.length})`))
      for (const p of keyMatches) out.push(rowOf(p))
    } else if (!((selectedCap === 'chat' || selectedCap === 'vision') && chatgptEntry && groups.includes('signIn'))) {
      out.push(h('div', { key: 'none', style: { ...muted, padding: '12px 0' } }, t('ownKeyNone')))
    }
  }
  return h('div', { className: 'nm-ways' }, out)
}

// ---- the link to Settings → Models ---------------------------------------------------------------

/** The settings section the four model slots live in (0.1.41), as `ModelsSection.tsx` registers it. */
export const MODELS_SECTION = 'nanomuse-models'

/**
 * Where the pickers went (0.1.41): one line on the Account page that opens Settings → Models,
 * with what new chats answer through and what the hands see with, in `<provider> · <model>`.
 */
export function ModelsLink({ t, view }: { t: Translate; view: ProvidersView }): ReactNode {
  // the slot names the row's id (`custom-2` for a second hand-made endpoint), which is the catalogue id for a vendor
  const labelOf = (provider: string) => (provider === 'nanomuse' ? 'nanoMuse Cloud' : (view.configured.find((p) => p.id === provider) ?? view.configured.find((p) => p.provider === provider))?.label || provider)
  const line = (slot: { provider: string; model: string }) => (slot.model ? `${labelOf(slot.provider)} · ${slot.model}` : t('mdPick'))
  return h('div', { className: 'nm-card', style: { marginTop: 4 } },
    h('button', { type: 'button', className: 'nm-row nm-row-button', 'data-testid': 'nm-models-link', onClick: () => { settingsBus.openSection?.(MODELS_SECTION) } },
      h('div', { className: 'nm-row-main' },
        h('span', { className: 'nm-row-title' }, t('mlTitle')),
        h('span', { className: 'nm-row-sub nm-wrap' }, `${t('mlChat')}: ${line(view.chat)} · ${t('mlHands')}: ${line(view.hands)}`)),
      h('span', { className: 'nm-row-chevron', 'aria-hidden': true }, '›')))
}

const heading: Record<string, string | number> = { fontSize: 14, fontWeight: 600, margin: '8px 0 0' }

/**
 * Settings → Account: *Ways on* — the account's row first while signed in, then the catalogue
 * in its groups — and one line that opens Settings → Models, where the four pickers live
 * (0.1.41), with the gate's sentences for what nothing covers yet.
 */
export function OwnKeyPanel({ t, onChanged }: { t: Translate; onChanged?(): void }): ReactNode {
  const { view, error, reload } = useProviders(t)
  const changed = useCallback(() => { reload(); onChanged?.() }, [reload, onChanged])
  if (error) return h('div', { style: errorStyle }, error)
  if (!view) return h('div', { style: muted }, t('loading'))
  return h('div', { 'data-testid': 'nm-ownkey-panel', style: { display: 'flex', flexDirection: 'column', gap: 12 } },
    h(ModelsLink, { t, view }),
    h(UnavailableLine, { t, view, capability: 'image' }),
    h(UnavailableLine, { t, view, capability: 'video' }),
    h('h3', { style: heading }, t('ownKeyWaysTitle')),
    h('div', { style: muted }, t('ownKeySub')),
    h(WaysOnRows, { t, view, onChanged: changed }))
}

/**
 * The first run's own-key step (step 4, *Choose models*): the region's first group with the
 * ChatGPT row, *More ways* for the rest; the caller draws *Continue* once `onDone` says the
 * step is done and keeps *Skip for now* until then.
 */
export function OwnKeyStep({ t, onDone }: { t: Translate; onDone(done: boolean): void }): ReactNode {
  const { view, error, reload } = useProviders(t)
  const [more, setMore] = useState(false)
  const done = view ? ownKeyStepDone(view) : false
  useEffect(() => { onDone(done) }, [done, onDone])
  if (error) return h('div', { style: errorStyle }, error)
  if (!view) return h('div', { style: muted }, t('loading'))
  const groups: Group[] = more ? ['signIn', 'first', 'rest', 'local', 'custom'] : ['signIn', 'first']
  return h('div', { className: 'nm-ob-card nm-ownkey-step', 'data-testid': 'nm-ownkey-step', style: { textAlign: 'left', width: '100%', padding: '4px 14px 12px' } },
    h(WaysOnRows, { t, view, groups, onChanged: reload }),
    more ? null : h('div', { style: { marginTop: 10 } }, h('button', { type: 'button', className: 'nm-ob-link nm-inline', onClick: () => setMore(true) }, t('ownKeyMoreWays'))))
}

/** The ChatGPT sign-in's failure in the person's words: the runtime's codes are worded here, its own messages kept. */
export function chatGptLoginError(t: Translate, error: string): string {
  if (error === 'no_result' || error === 'exited') return t('ownKeyChatGptIncomplete')
  return t('ownKeyChatGptFailed', { error: error === 'no_runtime' ? t('ownKeyNoRuntime') : error })
}

/** Cloud sign-in state is supplied by the account, never by a local selection. */
export function CloudChannelCard({ t, signedIn, onSignIn, onChoose }: { t: Translate; signedIn: boolean; onSignIn(): void; onChoose(): void }): ReactNode {
  return h('div', { className: `nm-model-channel-card${signedIn ? ' nm-channel-ready' : ''}` },
      h('span', { className: 'nm-model-channel-icon' }, h(IconGlobe, { size: 22 })),
      h('div', { className: 'nm-model-channel-main' },
        h('div', { className: 'nm-model-channel-title-row' },
          h('span', { className: 'nm-model-channel-title' }, 'nanoMuse Cloud'),
          h('span', { className: 'nm-model-channel-tag nm-model-channel-tag-blue' }, t('frChannelCloudTag'))),
        h('span', { className: 'nm-model-channel-sub' }, t('frChannelCloudDesc'))),
      h('div', { className: 'nm-model-channel-side' },
        signedIn ? h('span', { className: 'nm-model-channel-ready-badge' }, h(IconCheck, { size: 13 }), ' ', t('frChannelConnected')) : null,
        h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: signedIn ? onChoose : onSignIn }, signedIn ? t('frChannelCloudSelect') : t('ownKeySignIn'))))
}

/**
 * Clean 3-tier model channel picker for onboarding Step 2.
 * Offers ChatGPT (subscription direct login), nanoMuse Cloud (official relay),
 * and third-party API Keys (expandable).
 */
export function ModelChannelsStep({
  t,
  onDone, statusReady, cloudSignedIn, onCloudSignIn, onCloudChoose,
}: {
  t: Translate
  onDone(done: boolean): void
  statusReady: boolean
  cloudSignedIn: boolean
  onCloudSignIn(): void
  onCloudChoose(): void
}): ReactNode {
  const live = useLive()
  const { view, error, reload } = useProviders(t)
  const [expandedKeys, setExpandedKeys] = useState(false)
  const [cgBusy, setCgBusy] = useState(false)
  const [cgError, setCgError] = useState<string | undefined>()

  const cg = live.ownKeys?.chatgpt ?? view?.chatgpt
  const cgSignedIn = Boolean(cg?.signedIn)
  const cloudActive = Boolean(cloudSignedIn || live.cloud.signedIn)
  const configuredCount = view?.configured.length ?? 0
  const hasKeys = configuredCount > 0

  const hasAny = statusReady || cgSignedIn || cloudActive || hasKeys
  useEffect(() => {
    onDone(hasAny)
  }, [hasAny, onDone])

  if (error) return h('div', { style: errorStyle }, error)
  if (!view) return h('div', { style: muted }, t('loading'))

  const signInChatGpt = () => {
    setCgBusy(true)
    setCgError(undefined)
    call<{ url: string }>('chatgpt/login', {})
      .then((r) => { if (r.url) openLink(r.url) })
      .catch((err: unknown) => { if ((err as Error).message !== 'no_runtime') setCgError(failureText(t, err)) })
      .finally(() => setCgBusy(false))
  }
  const signOutChatGpt = () => {
    setCgBusy(true)
    call('chatgpt/logout', {}).then(() => reload()).catch((err: unknown) => setCgError(failureText(t, err))).finally(() => setCgBusy(false))
  }
  const cancelChatGpt = () => { void call('chatgpt/cancel', {}).catch(() => undefined) }

  return h('div', { className: 'nm-model-channels', style: { width: '100%' } },
    statusReady && !cgSignedIn && !cloudActive && !hasKeys
      ? h('div', { className: 'nm-model-channel-ready-badge' }, t('frModelReady')) : null,
    // 1. ChatGPT
    h('div', { className: `nm-model-channel-card${cgSignedIn ? ' nm-channel-ready' : ''}` },
      h('span', { className: 'nm-model-channel-icon' }, h(IconUser, { size: 22 })),
      h('div', { className: 'nm-model-channel-main' },
        h('div', { className: 'nm-model-channel-title-row' },
          h('span', { className: 'nm-model-channel-title' }, 'ChatGPT'),
          h('span', { className: 'nm-model-channel-tag nm-model-channel-tag-blue' }, t('frChannelChatGptTag')),
          h('span', { className: 'nm-model-channel-tag nm-model-channel-tag-gray' }, t('frChannelChatGptCaps'))),
        h('span', { className: 'nm-model-channel-sub' }, t('frChannelChatGptDesc')),
        h('span', { className: 'nm-model-channel-sub' }, t('ownKeyChatGptHonesty')),
        cg?.login.status === 'waiting'
          ? h('div', { className: 'nm-way-sub nm-wrap', style: { marginTop: 4, color: 'var(--nm-blue)' } }, t('ownKeyChatGptWaiting'))
          : null,
        cgError || cg?.login.status === 'error'
          ? h('div', { style: { ...errorStyle, marginTop: 4 } }, cgError || chatGptLoginError(t, cg?.login.error ?? ''))
          : null),
      h('div', { className: 'nm-model-channel-side' },
        cgSignedIn
          ? h(Fragment, null,
              h('span', { className: 'nm-model-channel-ready-badge' }, h(IconCheck, { size: 13 }), ' ', t('frChannelConnected')),
              h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: cgBusy, onClick: signOutChatGpt }, t('ownKeySignOut')))
          : cg?.login.status === 'waiting'
            ? h(Fragment, null,
                cg.login.url ? h('button', { type: 'button', className: 'nm-pill nm-pill-sm', onClick: () => openLink(cg.login.url) }, t('ownKeyChatGptOpen')) : null,
                h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: cancelChatGpt }, t('ownKeyChatGptCancel')))
            : h('button', { type: 'button', className: 'nm-pill nm-pill-sm', disabled: cgBusy || !view.chatgpt.runtime, onClick: signInChatGpt }, t('ownKeySignIn')))),

    h(CloudChannelCard, { t, signedIn: cloudActive, onSignIn: onCloudSignIn, onChoose: onCloudChoose }),

    // 3. Third-party provider API keys
    h('div', { className: `nm-model-channel-card${hasKeys ? ' nm-channel-ready' : ''}` },
      h('span', { className: 'nm-model-channel-icon' }, h(IconKey, { size: 22 })),
      h('div', { className: 'nm-model-channel-main' },
        h('div', { className: 'nm-model-channel-title-row' },
          h('span', { className: 'nm-model-channel-title' }, t('frChannelKey'))),
        h('span', { className: 'nm-model-channel-sub' }, t('frChannelKeyDesc'))),
      h('div', { className: 'nm-model-channel-side' },
        hasKeys
          ? h('span', { className: 'nm-model-channel-ready-badge' }, h(IconCheck, { size: 13 }), ' ', `${t('frChannelConnected')} (${configuredCount})`)
          : null,
        h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => setExpandedKeys(!expandedKeys) },
          expandedKeys ? t('frChannelKeyCollapse') : t('frChannelKeyConfig')))),

    // Expanded keys list
    expandedKeys
      ? h('div', { className: 'nm-model-expanded-keys' },
          h(WaysOnRows, { t, view, groups: ['first', 'rest', 'local', 'custom'], onChanged: reload }))
      : null)
}
