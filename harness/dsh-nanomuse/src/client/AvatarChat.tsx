/**
 * The look changed from the chat, as on the phone (android …/avatar/AvatarFlow.kt,
 * ui/avatar/AvatarChatCards.kt): "change your avatar to a red fox" never reaches the
 * model. The composer's words are read on their way out (src/avatar-flow.ts has the
 * patterns), the cost is shown first when the account meters pictures, four
 * candidates come from the image model, the person picks one by clicking or by
 * words ("the second one", "左下", "3"), the poses are drawn, the face is worn on the
 * account, and the agent says so in the chat. The card sits above the composer,
 * in the chat column, and goes away with Escape or "Keep current".
 */
import { createElement as h, useEffect, useSyncExternalStore, type ReactNode } from 'react'
import { parseAvatarChoice, parseAvatarRequest } from '../avatar-flow.ts'
import { call, errorCode, failureText, type Translate } from './api.ts'
import { buildPrompt, KEEP, MOOD_INSTRUCTIONS, png, still, type Estimate } from './AvatarStudio.tsx'
import { AvatarShareSheet } from './AvatarShare.tsx'
import { composerCard, composerEditable } from './composer.ts'
import { IconClose, IconSpinner } from './icons.tsx'
import { useLive } from './live.ts'
import { peekWin } from './win.ts'

type Phase = 'idle' | 'cost' | 'drawing' | 'pick' | 'finalizing' | 'done' | 'failed'

interface FlowState {
  phase: Phase
  desc: string
  lang: 'zh' | 'en'
  sessionId: string
  estimate?: Estimate | undefined
  estimateError?: string | undefined
  /** Four slots: a PNG as base64, `null` while drawing, `''` when that one failed. */
  candidates: (string | null)[]
  picked: number | null
  /** The failed `call` as it came; the view words it with `failureText` in the UI language. */
  error?: unknown
  share: boolean
}

const IDLE: FlowState = { phase: 'idle', desc: '', lang: 'en', sessionId: '', candidates: [null, null, null, null], picked: null, share: false }
const FACE_PICTURES = 8

let state: FlowState = IDLE
let round = 0
const listeners = new Set<() => void>()

function set(patch: Partial<FlowState>): void {
  state = { ...state, ...patch }
  for (const l of listeners) l()
}

export function useAvatarChat(): FlowState {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l) }, () => state, () => state)
}

/** The flow, as other parts start it: the profile's "Change avatar" lands words in the composer; this takes them. */
export const avatarChat = {
  /** Begin for a description; shows the cost first when the account meters pictures. */
  begin(desc: string, lang: 'zh' | 'en'): void {
    round++
    set({ ...IDLE, phase: 'cost', desc, lang, sessionId: peekWin().current ?? '' })
    const mine = round
    call<Estimate>('studio/estimate')
      .then((estimate) => {
        if (round !== mine) return
        if (estimate.unlimited) avatarChat.draw()
        else set({ estimate })
      })
      .catch((err: unknown) => {
        if (round !== mine) return
        set({ estimateError: errorCode(err) === 'signed_out' ? 'signed_out' : (err as Error).message })
      })
  },
  draw(): void {
    const mine = ++round
    const { desc } = state
    set({ phase: 'drawing', candidates: [null, null, null, null], picked: null, error: undefined })
    let failures = 0
    const one = async (index: number) => {
      try {
        const r = await call<{ image: string }>('studio/draw', { prompt: buildPrompt(desc, index, 'muse') })
        if (round === mine) set({ candidates: state.candidates.map((v, i) => (i === index ? r.image : v)) })
      } catch (err: unknown) {
        failures++
        if (round === mine) set({ candidates: state.candidates.map((v, i) => (i === index ? '' : v)), error: err })
      }
    }
    void (async () => {
      await Promise.all([one(0), one(1)])
      await Promise.all([one(2), one(3)])
      if (round !== mine) return
      set({ phase: failures === 4 ? 'failed' : 'pick' })
    })()
  },
  /** Draw one slot again (its tile said Retry). */
  retry(index: number): void {
    const mine = round
    set({ candidates: state.candidates.map((v, i) => (i === index ? null : v)) })
    call<{ image: string }>('studio/draw', { prompt: buildPrompt(state.desc, index, 'muse') })
      .then((r) => { if (round === mine) set({ candidates: state.candidates.map((v, i) => (i === index ? r.image : v)) }) })
      .catch((err: unknown) => { if (round === mine) set({ candidates: state.candidates.map((v, i) => (i === index ? '' : v)), error: err }) })
  },
  /** Keep candidate `index` (0-based): the poses, the account, the agent's word. */
  async choose(index: number): Promise<void> {
    const chosen = state.candidates[index]
    if (!chosen || state.phase !== 'pick') return
    const mine = round
    set({ phase: 'finalizing', picked: index, error: undefined })
    try {
      const idle = await still(chosen)
      const source = await png(chosen)
      const stills: Record<string, string> = { idle }
      const pose = async (mood: string) => {
        try {
          const r = await call<{ image: string }>('studio/pose', { image: source, prompt: KEEP + MOOD_INSTRUCTIONS[mood] })
          stills[mood] = await still(r.image)
        } catch {
          stills[mood] = idle
        }
      }
      await Promise.all([pose('working'), pose('waiting')])
      await Promise.all([pose('happy'), pose('error')])
      if (round !== mine) return
      await call('studio/wear', { description: state.desc, style: 'muse', face: stills })
      if (round !== mine) return
      set({ phase: 'done' })
      void fetch('nanomuse/rooms/avatar/adopted', { method: 'POST', headers: { 'content-type': 'application/json', 'x-nanomuse': '1' }, body: JSON.stringify({ desc: state.desc, chosen: index + 1, files: Object.keys(stills).map((m) => `${m}.webp`), sessionId: state.sessionId }) }).catch(() => undefined)
    } catch (err: unknown) {
      if (round === mine) set({ phase: 'pick', picked: null, error: err })
    }
  },
  close(): void {
    round++
    set(IDLE)
  },
  /** Words typed while candidates are shown: a pick, a new set, or nothing (the words go to the agent). */
  words(text: string): boolean {
    if (state.phase !== 'pick' && state.phase !== 'failed') return false
    const choice = parseAvatarChoice(text)
    if (choice.kind === 'regenerate') { avatarChat.draw(); return true }
    if (choice.kind === 'pick' && state.phase === 'pick') { void avatarChat.choose(choice.index - 1); return true }
    return false
  },
}

/**
 * Read the composer's words on their way out. Enter without Shift and the send
 * button are the two ways out; an avatar request (or a pick while candidates are
 * shown) is taken here and never sent.
 */
export function interceptComposer(): () => void {
  const take = (event: Event): boolean => {
    const editable = composerEditable()
    if (!editable) return false
    const text = (editable.innerText || editable.textContent || '').trim()
    if (!text) return false
    if (avatarChat.words(text)) { clear(editable); event.preventDefault(); event.stopPropagation(); return true }
    const request = parseAvatarRequest(text)
    if (!request) return false
    clear(editable)
    event.preventDefault()
    event.stopPropagation()
    avatarChat.begin(request.desc, request.lang)
    return true
  }
  const onKey = (event: KeyboardEvent) => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.defaultPrevented) return
    const editable = composerEditable()
    if (!editable || !(event.target instanceof Node) || !editable.contains(event.target)) return
    take(event)
  }
  const onClick = (event: MouseEvent) => {
    const card = composerCard()
    if (!card || !(event.target instanceof Element)) return
    const button = event.target.closest('button')
    if (!button || !card.contains(button) || !/_primary|send/i.test(button.className + ' ' + (button.getAttribute('aria-label') ?? ''))) return
    take(event)
  }
  document.addEventListener('keydown', onKey, true)
  document.addEventListener('click', onClick, true)
  return () => {
    document.removeEventListener('keydown', onKey, true)
    document.removeEventListener('click', onClick, true)
  }
}

function clear(editable: HTMLElement): void {
  editable.focus()
  const selection = window.getSelection()
  if (selection) {
    const range = document.createRange()
    range.selectNodeContents(editable)
    selection.removeAllRanges()
    selection.addRange(range)
  }
  if (!document.execCommand('delete')) {
    editable.textContent = ''
    editable.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward' }))
  }
}

export function makeAvatarChat(t: Translate) {
  return function AvatarChat(): ReactNode {
    const flow = useAvatarChat()
    const live = useLive()
    useEffect(() => {
      if (flow.phase === 'idle') return
      const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !e.defaultPrevented && flow.phase !== 'finalizing') avatarChat.close() }
      document.addEventListener('keydown', onKey)
      return () => document.removeEventListener('keydown', onKey)
    }, [flow.phase])
    if (flow.phase === 'idle') return null
    const name = live.profile.name || t('brand')
    const quoted = `“${flow.desc}”`
    let body: ReactNode
    if (flow.phase === 'cost') body = h(Cost, { t, flow })
    else if (flow.phase === 'drawing' || flow.phase === 'pick' || flow.phase === 'failed') body = h(Options, { t, flow, quoted })
    else if (flow.phase === 'finalizing') body = h('div', { className: 'nm-ac-final' },
      flow.picked !== null && flow.candidates[flow.picked] ? h('img', { className: 'nm-ac-final-img', src: `data:image/png;base64,${flow.candidates[flow.picked]}`, alt: '' }) : null,
      h('div', { className: 'nm-ac-status nm-live' }, h(IconSpinner, { size: 14 }), t('acFinalizing')))
    else body = h('div', { className: 'nm-ac-done' },
      h('p', null, t('acAdopted', { desc: flow.desc })),
      h('div', { className: 'nm-ac-actions' },
        h('button', { type: 'button', className: 'nm-pill nm-pill-sm', onClick: () => set({ share: true }) }, t('acShare')),
        h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: avatarChat.close }, t('acLater'))))
    return h('div', { className: 'nm-ac', role: 'dialog', 'aria-label': t('acTitle') },
      h('div', { className: 'nm-ac-head' },
        h('span', { className: 'nm-ac-title' }, flow.phase === 'cost' ? t('fcTitle') : flow.phase === 'done' ? t('acTitle') : flow.phase === 'finalizing' ? t('acFinalizing') : t('acOptions')),
        flow.phase !== 'finalizing' ? h('button', { type: 'button', className: 'nm-icon-btn', 'aria-label': t('close'), onClick: avatarChat.close }, h(IconClose, { size: 14 })) : null),
      body,
      flow.share ? h(AvatarShareSheet, { t, name, onClose: () => set({ share: false }) }) : null)
  }
}

function Cost({ t, flow }: { t: Translate; flow: FlowState }): ReactNode {
  const e = flow.estimate
  // the clips count when the account would draw them after the face (C3)
  const what = e?.clips ? t('fcWhatClips', { n: FACE_PICTURES, clips: e.clips }) : t('fcWhat', { n: FACE_PICTURES })
  let line: ReactNode
  if (flow.estimateError === 'signed_out') line = h('p', { className: 'nm-ac-err' }, t('stSignedOut'))
  else if (flow.estimateError) line = h('p', null, t('fcUnknown', { what }))
  else if (!e) line = h('p', { className: 'nm-ac-status nm-live' }, h(IconSpinner, { size: 14 }), t('fcChecking'))
  else line = h('div', null,
    h('p', null, t('fcAbout', { what, cny: e.cny.toFixed(2) })),
    e.leftCny !== null && e.leftCny !== undefined ? h('p', null, e.affordable ? t('fcLeft', { cny: e.leftCny.toFixed(2) }) : t('fcShort')) : null)
  const can = flow.estimateError !== 'signed_out'
  return h('div', { className: 'nm-ac-cost' },
    h('p', { className: 'nm-ac-desc' }, `“${flow.desc}”`),
    line,
    h('div', { className: 'nm-ac-actions' },
      can ? h('button', { type: 'button', className: 'nm-pill nm-pill-sm', disabled: !e && !flow.estimateError, onClick: avatarChat.draw }, e && !e.affordable ? t('fcAnyway') : t('fcGo')) : null,
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: avatarChat.close }, t('fcNotNow'))))
}

function Options({ t, flow, quoted }: { t: Translate; flow: FlowState; quoted: string }): ReactNode {
  const drawing = flow.phase === 'drawing'
  return h('div', { className: 'nm-ac-options' },
    h('p', { className: 'nm-ac-desc' }, drawing ? t('acDrawing', { desc: flow.desc }) : flow.phase === 'failed' ? t('acFailed') : t('acReady', { desc: flow.desc })),
    h('div', { className: 'nm-ac-grid' }, flow.candidates.map((c, i) => c
      ? h('button', { key: i, type: 'button', className: 'nm-ac-tile', disabled: drawing, 'aria-label': t('acOption', { n: i + 1 }), onClick: () => void avatarChat.choose(i) },
          h('img', { src: `data:image/png;base64,${c}`, alt: quoted }),
          h('span', { className: 'nm-ac-n' }, String(i + 1)))
      : c === ''
        ? h('button', { key: i, type: 'button', className: 'nm-ac-tile nm-ac-tile-retry', disabled: drawing, onClick: () => avatarChat.retry(i) }, t('acRetry'))
        : h('div', { key: i, className: 'nm-ac-tile nm-ac-tile-wait' }, h(IconSpinner, { size: 18 })))),
    drawing ? h('div', { className: 'nm-ac-status nm-live' }, h(IconSpinner, { size: 14 }), t('acGenerating')) : h('p', { className: 'nm-ac-hint' }, t('acPickHint')),
    flow.error && !drawing ? h('p', { className: 'nm-ac-err' }, failureText(t, flow.error)) : null,
    h('div', { className: 'nm-ac-actions' },
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: drawing, onClick: avatarChat.draw }, t('acAgain')),
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: avatarChat.close }, t('acKeep'))))
}
