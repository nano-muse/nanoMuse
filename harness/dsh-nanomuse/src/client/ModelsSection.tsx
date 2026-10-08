/**
 * Settings → Models (0.1.41, "Choice"): the four things a model does for the person, one
 * row each — Chat, Operating the screen, Making pictures, Making clips — with a picker per
 * row. Every picker lists nanoMuse Cloud first while signed in (its recommended model
 * marked), then one group per own provider the person added, each group filtered to the
 * models that can do the row's job (the host's `GET /models`). A row nothing configured can
 * do shows the gate's one sentence and *Add a provider*; the page ends with *Add a provider*
 * too, which opens the own-key rows on Settings → Account. The pickers used to sit on the
 * Account page (`OwnKey.tsx` `ModelPickers`); that page now links here.
 */
import { createElement as h, Fragment, useCallback, useEffect, useState, type ReactNode } from 'react'
import type { ProviderEntry } from '../catalogue.ts'
import { call, errorCode, errorStyle, muted, type Translate, failureText } from './api.ts'
import { settingsBus } from './bus.ts'
import { IconHand, IconImage, IconMessage, IconVideo } from './icons.tsx'
import { useLive } from './live.ts'
import type { ModelGroup } from './model-list.ts'
import { ModelPicker, type PickerHead } from './ModelPicker.tsx'
import { ACCOUNT_SECTION, MODELS_SECTION, providersNamed, useProviders, type ModelOption } from './OwnKey.tsx'

export { MODELS_SECTION }

export type Slot = 'chat' | 'hands' | 'image' | 'video'
export const SLOTS: readonly Slot[] = ['chat', 'hands', 'image', 'video']

export interface SlotView {
  provider: string
  providerLabel: string
  model: string
  options: ModelOption[]
  chosen: boolean
  /** The clips are switched off (the video slot only). */
  off?: boolean
  /** What *Automatic* resolves to right now (the three dependent slots); `model` '' when nothing can. Absent on an older host. */
  auto?: { provider: string; providerLabel: string; model: string }
}

/** The slots that follow the order unless the person chose: everything but chat, the anchor. */
export const DEPENDENT: readonly Slot[] = ['hands', 'image', 'video']

/** `<provider> · <model>`, as the page writes a value. */
export function valueText(provider: string, providerLabel: string, model: string): string {
  return `${providerLabel || provider} · ${model}`
}

/** `GET /models`. */
export interface ModelsView {
  signedIn: boolean
  /** *Use nanoMuse Cloud models*: signed in and not switched off. */
  cloudModels: boolean
  slots: Record<Slot, SlotView>
  handsExcluded: string[]
}

const ROUTE: Record<Slot, string> = { chat: 'chat-model', hands: 'hands-model', image: 'image-model', video: 'video-model' }
/** The capability the gate's sentence names providers for. */
const CAPABILITY: Record<Slot, 'chat' | 'vision' | 'image' | 'video'> = { chat: 'chat', hands: 'vision', image: 'image', video: 'video' }

export function slotTitle(t: Translate, slot: Slot): string {
  return slot === 'chat' ? t('mlChat') : slot === 'hands' ? t('mlHands') : slot === 'image' ? t('mlImage') : t('mlVideo')
}

function slotSub(t: Translate, slot: Slot): string {
  return slot === 'chat' ? t('mlChatSub') : slot === 'hands' ? t('mlHandsSub') : slot === 'image' ? t('mlImageSub') : t('mlVideoSub')
}

function slotIcon(slot: Slot): ReactNode {
  return slot === 'chat' ? h(IconMessage, { size: 18 }) : slot === 'hands' ? h(IconHand, { size: 18 }) : slot === 'image' ? h(IconImage, { size: 18 }) : h(IconVideo, { size: 18 })
}

/** `GET /models`, again whenever the host's live state says the rows, the sign-in or a choice moved. */
export function useModels(t: Translate): { view: ModelsView | undefined; error: string | undefined; reload(): void; setView(view: ModelsView): void } {
  const live = useLive()
  const [view, setView] = useState<ModelsView | undefined>()
  const [error, setError] = useState<string | undefined>()
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((n) => n + 1), [])
  const own = live.ownKeys
  const key = `${own?.count ?? 0}|${own?.chatgpt.signedIn ?? false}|${own?.capabilities.join(',') ?? ''}|${live.cloud.signedIn}|${live.handsModel}`
  useEffect(() => {
    let alive = true
    call<ModelsView>('models')
      .then((v) => { if (alive) { setView(v); setError(undefined) } })
      .catch((err: unknown) => { if (alive) setError(failureText(t, err)) })
    return () => { alive = false }
  }, [tick, key])
  return { view, error, reload, setView }
}

/**
 * The groups of one picker: `nanoMuse Cloud` first (its recommended model marked and first),
 * then one group per own provider in the order the options came, each keyed by the
 * provider's id and carrying the provider's catalogue default for the slot, which the
 * folded view shows first (`model-list.ts`).
 */
export function slotGroups(slot: Slot, options: readonly ModelOption[], catalogue: readonly Pick<ProviderEntry, 'id' | 'defaults'>[] = []): ModelGroup<ModelOption>[] {
  const groups: ModelGroup<ModelOption>[] = []
  for (const o of options) {
    let group = groups.find((g) => g.key === o.provider)
    if (!group) {
      const preset = catalogue.find((p) => p.id === o.provider)?.defaults[slot]
      group = { key: o.provider, label: o.providerLabel, rows: [], ...(preset ? { default: preset } : {}) }
      groups.push(group)
    }
    group.rows.push(o)
  }
  return groups
}

/**
 * One picker (`ModelPicker.tsx`): the button reads what the slot uses, `<provider> · <model>`;
 * the panel has *Automatic* first on the three dependent slots (selected when no choice is
 * stored; picking it drops the stored choice, `onPick('', 'auto')`, so the slot follows the
 * order again), the video slot's *Off* under it, then `nanoMuse Cloud` and one group per own
 * provider, each folded past a few rows, with a search once the lists are long. A current
 * model the list does not carry (an older choice, a model the provider stopped listing)
 * still reads on the button, so the picker never looks empty.
 */
export function SlotPicker({ t, slot, view, disabled, catalogue, onPick }: { t: Translate; slot: Slot; view: SlotView; disabled: boolean; catalogue?: readonly Pick<ProviderEntry, 'id' | 'defaults'>[]; onPick(provider: string, model: string): void }): ReactNode {
  const automatic = DEPENDENT.includes(slot)
  const onHead = view.off ? 'off' : automatic && !view.chosen ? 'auto' : ''
  const text = onHead === 'off' ? t('mdVideoOff') : onHead === 'auto' ? t('mlAutomatic') : view.model ? valueText(view.provider, view.providerLabel, view.model) : t('mdPick')
  const heads: PickerHead[] = [
    ...(automatic ? [{ value: 'auto', label: t('mlAutomatic') }] : []),
    ...(slot === 'video' ? [{ value: 'off', label: t('mdVideoOff') }] : []),
  ]
  return h(ModelPicker<ModelOption>, {
    t,
    label: slotTitle(t, slot),
    text,
    heads,
    headValue: onHead,
    groups: slotGroups(slot, view.options, catalogue),
    ...(onHead || !view.model ? {} : { current: { group: view.provider, id: view.model } }),
    disabled,
    testId: `nm-ml-${slot}`,
    onHead: (value) => onPick('', value),
    onPick: (provider, row) => onPick(provider, row.id),
    rowText: (o) => (o.recommended ? `${o.name} · ${t('mlRecommended')}` : o.name),
  })
}

export function openAccountWays(): void {
  settingsBus.openSection?.(ACCOUNT_SECTION)
}

export function makeModelsSection(t: Translate) {
  return function ModelsSection(): ReactNode {
    const { view, error, reload, setView } = useModels(t)
    const providers = useProviders(t)
    const [busy, setBusy] = useState<Slot | null>(null)
    const [said, setSaid] = useState<Partial<Record<Slot, string>>>({})
    const [failed, setFailed] = useState<string | undefined>()
    const [switching, setSwitching] = useState(false)
    // the host refused the switch (`409 chat_on_cloud`: the chat slot is the account's and nothing of
    // one's own could answer); one sentence under the switch, which stays on
    const [switchNote, setSwitchNote] = useState<string | undefined>()
    // Signed in: the one switch for the account as a model source. Off, nanoMuse Cloud leaves every
    // row's list and order and no side call runs on it; the sign-in stays (sync, the devices).
    const setCloudModels = (on: boolean) => {
      setSwitching(true)
      setFailed(undefined)
      setSwitchNote(undefined)
      call<ModelsView>('cloud-models', { on })
        .then((next) => { setView(next); setSaid({}); reload() })
        .catch((err: unknown) => { if (errorCode(err) !== 'chat_on_cloud') throw err; setSwitchNote(t('mlChatOnCloud')) })
        .catch((err: unknown) => setFailed(failureText(t, err)))
        .finally(() => setSwitching(false))
    }
    const pick = (slot: Slot, provider: string, model: string) => {
      setBusy(slot)
      setFailed(undefined)
      // `auto` drops the stored choice (`model: ''`), nothing else; the row then says what the order gives
      call<SlotView>(ROUTE[slot], model === 'off' ? { model: 'off' } : model === 'auto' ? { model: '' } : { model, provider })
        .then((row) => {
          if (view && (slot === 'image' || slot === 'video') && row && 'options' in row) setView({ ...view, slots: { ...view.slots, [slot]: row } })
          setSaid((prev) => ({ ...prev, [slot]: model === 'auto' ? undefined : slot === 'chat' ? t('mlAppliesNew') : slot === 'hands' ? t('mlHandsLive') : t('mlSaved') }))
          reload()
        })
        .catch((err: unknown) => setFailed(failureText(t, err)))
        .finally(() => setBusy(null))
    }
    if (error) return h('div', { className: 'nm-section' }, h('div', { style: errorStyle }, error))
    if (!view) return h('div', { className: 'nm-section' }, h('p', null, t('mlLead')), h('div', { style: muted }, t('loading')))
    const gate = providers.view
    const addLink = h('button', { type: 'button', className: 'nm-ob-link nm-inline', onClick: openAccountWays }, t('mlAddProvider'))
    const rows = SLOTS.map((slot) => {
      const row = view.slots[slot]
      const empty = row.options.length === 0 && !row.model && !row.off
      let sub: ReactNode
      if (empty) {
        // the gate's sentence: who could, where the person is; the harness's stock DeepSeek without a key counts as nothing
        const sentence = gate ? t(slot === 'chat' ? 'ownKeyNoChat' : slot === 'hands' ? 'ownKeyNoVision' : slot === 'image' ? 'ownKeyNoImage' : 'ownKeyNoVideo', { providers: providersNamed(t, gate, CAPABILITY[slot]) }) : ''
        sub = h(Fragment, null, sentence, sentence ? ' ' : null, addLink)
      } else if (said[slot]) sub = said[slot]
      else if (DEPENDENT.includes(slot) && !row.chosen && !row.off && row.auto?.model) {
        // on *Automatic*: what the order gives right now, under the row's sentence
        sub = `${slotSub(t, slot)} ${t('mlCurrently', { model: valueText(row.auto.provider, row.auto.providerLabel, row.auto.model) })}`
      } else sub = slotSub(t, slot)
      return h('div', { key: slot, className: 'nm-row', 'data-testid': `nm-ml-row-${slot}` },
        h('span', { className: 'nm-row-icon' }, slotIcon(slot)),
        h('div', { className: 'nm-row-main' },
          h('span', { className: 'nm-row-title' }, slotTitle(t, slot)),
          h('span', { className: 'nm-row-sub nm-wrap' }, sub),
          slot === 'hands' && view.handsExcluded.length ? h('span', { className: 'nm-row-sub nm-wrap', style: muted }, t('mlHandsExcluded', { providers: view.handsExcluded.join(t('langTag') === 'zh' ? '、' : ', ') })) : null),
        empty ? null : h(SlotPicker, { t, slot, view: row, disabled: busy !== null, ...(gate ? { catalogue: gate.catalogue } : {}), onPick: (provider, model) => pick(slot, provider, model) }))
    })
    const cloudRow = view.signedIn
      ? h('div', { className: 'nm-card', style: { marginBottom: 10 } },
          h('div', { className: 'nm-row', 'data-testid': 'nm-ml-cloud-row' },
            h('div', { className: 'nm-row-main' },
              h('span', { className: 'nm-row-title' }, t('mlCloudModels')),
              h('span', { className: 'nm-row-sub nm-wrap' }, view.cloudModels ? t('mlCloudModelsOn') : t('mlCloudModelsOff')),
              switchNote ? h('span', { className: 'nm-row-sub nm-wrap', role: 'alert', style: errorStyle, 'data-testid': 'nm-ml-cloud-note' }, switchNote) : null),
            h('button', { type: 'button', role: 'switch', className: 'nm-switch', 'aria-checked': view.cloudModels, 'aria-label': t('mlCloudModels'), 'data-testid': 'nm-ml-cloud-switch', disabled: switching || busy !== null, onClick: () => setCloudModels(!view.cloudModels) })))
      : null
    return h('div', { className: 'nm-section', 'data-testid': 'nm-models-section' },
      h('p', null, t('mlLead')),
      cloudRow,
      h('div', { className: 'nm-card' }, rows),
      failed ? h('div', { style: errorStyle }, failed) : null,
      h('div', { style: { marginTop: 10 } }, h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: openAccountWays }, t('mlAddProvider'))))
  }
}
