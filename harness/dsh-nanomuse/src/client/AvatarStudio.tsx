/**
 * The avatar studio, as Muse draws a new face: describe it, four candidates come
 * up in a 2×2 grid, pick one, the other poses are drawn from it, and the new look
 * is on — for every device of the account. The pictures come through the host
 * from the relay's image model (`/nanomuse/cloud/studio/*`); the browser does the
 * picture work (a square 512 px WebP of each still) so the host needs no image
 * library. The prompts are the runtime's (`nanomuse/avatar/studio.py`), kept in
 * step by hand, so a face drawn on any device comes out alike. Opened from the
 * profile panel's look editor, or by the agent (`draw_new_look`) when the person
 * asks for a new look in a chat.
 */
import { createElement as h, Fragment, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { StarNudgeOnce } from './AccountPage.tsx'
import { call, errorCode, type Translate, failureText } from './api.ts'
import { useLive } from './live.ts'
import type { Words } from './locales.ts'
import { UnavailableLine, useProviders } from './OwnKey.tsx'
import { useRooms } from './rooms.ts'
import { Sheet } from './ui.tsx'

export const STYLES: Record<string, string> = {
  muse: 'cute 3D character render in the style of a collectible vinyl toy, soft matte materials with subtle sheen, rounded simplified forms, big friendly eyes, soft studio lighting with gentle shadows, pastel accents',
  flat: 'flat vector illustration, soft pastel colours, clean simple shapes, subtle shading',
  clay: '3D clay render, soft studio lighting, matte rounded forms, gentle colours',
  watercolor: 'gentle watercolour painting, soft edges, light paper texture',
  pixel: 'crisp pixel art, limited palette, clean silhouette',
  line: 'minimal line drawing with two accent colours on cream, confident strokes',
  sticker: 'glossy sticker style, thick white outline, bold saturated colours',
}
const VARIATIONS = [
  'variation 1: the most typical, classic colouring',
  'variation 2: a different breed or colour pattern, lighter tones',
  'variation 3: a different breed or colour pattern, darker or warmer tones, a small accessory such as a scarf or glasses',
  'variation 4: a playful take — unusual colouring or a tiny outfit, slight head tilt',
]
export const KEEP = 'Keep this exact character — same face, colours, outfit, art style, proportions, framing, camera angle and pure white background. Change only the pose and props described. '
export const MOOD_INSTRUCTIONS: Record<string, string> = {
  working: 'It now wears over-ear headphones and sits typing on a small open laptop in front of it, focused and content, a faint glow from the screen on its face.',
  waiting: 'It now holds a small glowing crystal ball in both hands at chest height and gazes into it with wide curious eyes, waiting for an answer.',
  happy: 'It is now celebrating, hugging a big glowing yellow five-pointed star, eyes closed with a wide smile. Same white background; no confetti, no night sky, no extra decoration.',
  error: 'It now looks sheepish and apologetic, a small sweat drop beside its head, one hand behind its head, shoulders slightly raised.',
}
const MOODS = ['working', 'waiting', 'happy', 'error']
const STILL_PX = 512
const STILL_BYTES = 190 * 1024

export function buildPrompt(description: string, index: number, style: string): string {
  const subject = description.trim().replace(/[.。!！,，]+$/, '')
  const look = STYLES[style] ?? STYLES.muse
  return `A cute character based on: ${subject}. ${look}. Full body, standing, facing the viewer, centred, whole figure visible with margin on all sides, big head and small body, friendly expression, pure white background, soft ground shadow only. ${VARIATIONS[index % 4]}. Square composition. No text, no watermark, no border, no props other than what is described, one character only.`
}

/** The studio's open/close, shared with the look editor and the agent's request. */
export const studioBus: { open?: ((description?: string, style?: string) => void) | undefined } = {}

export interface Estimate {
  cny: number
  leftCny: number
  unlimited: boolean
  affordable: boolean
  imageModel: string
  /** The four clips of the new face, when the account would draw them (C3); 0 or absent otherwise. */
  clips?: number
  videoModel?: string
  /** Who draws (0.1.41): the account, or an own provider (nothing billed by the account). Absent on an older host. */
  source?: 'cloud' | 'provider'
  label?: string
}

type Stage = 'describe' | 'drawing' | 'posing' | 'done'

async function decode(b64: string): Promise<HTMLImageElement> {
  const img = new Image()
  img.src = `data:image/png;base64,${b64}`
  await img.decode()
  return img
}

function square(img: HTMLImageElement, px: number): HTMLCanvasElement {
  const side = Math.min(img.naturalWidth, img.naturalHeight)
  const canvas = document.createElement('canvas')
  canvas.width = px
  canvas.height = px
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, px, px)
  ctx.drawImage(img, (img.naturalWidth - side) / 2, (img.naturalHeight - side) / 2, side, side, 0, 0, px, px)
  return canvas
}

function blobOf(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob> {
  return new Promise((ok, no) => canvas.toBlob((b) => (b ? ok(b) : no(new Error('no picture'))), type, quality))
}

async function base64Of(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer())
  let s = ''
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(s)
}

/** A still as the account keeps it: square, 512 px, WebP under the relay's size cap. */
export async function still(b64: string): Promise<string> {
  const canvas = square(await decode(b64), STILL_PX)
  let quality = 0.88
  let blob = await blobOf(canvas, 'image/webp', quality)
  while (blob.size > STILL_BYTES && quality > 0.3) {
    quality -= 0.12
    blob = await blobOf(canvas, 'image/webp', quality)
  }
  return base64Of(blob)
}

/** The chosen candidate as a PNG for the edits (whatever the model handed back). */
export async function png(b64: string): Promise<string> {
  const img = await decode(b64)
  const canvas = square(img, Math.min(1024, Math.min(img.naturalWidth, img.naturalHeight)))
  return base64Of(await blobOf(canvas, 'image/png'))
}

export function AvatarStudioSheet({ t, initial, style: initialStyle, onClose }: { t: Translate; initial: string; style: string; onClose(): void }): ReactNode {
  const [stage, setStage] = useState<Stage>('describe')
  const [text, setText] = useState(initial)
  const [style, setStyle] = useState(initialStyle in STYLES ? initialStyle : 'muse')
  const [estimate, setEstimate] = useState<Estimate | undefined>()
  const [estimateError, setEstimateError] = useState<string | undefined>()
  const [candidates, setCandidates] = useState<(string | null)[]>([null, null, null, null])
  const [picked, setPicked] = useState<number | null>(null)
  const [moods, setMoods] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | undefined>()
  const [busy, setBusy] = useState(false)
  // *Use nanoMuse Cloud this time* (0.1.41): the round after an own provider failed draws through the account, the slot untouched
  const [viaCloud, setViaCloud] = useState(false)
  const live = useLive()
  const alive = useRef(true)
  const round = useRef(0)
  // what is configured and what it covers (C11): decides whether a failed estimate is "nobody draws pictures here"
  const providers = useProviders(t)
  useEffect(() => () => { alive.current = false }, [])
  useEffect(() => {
    call<Estimate>('studio/estimate').then((e) => { if (alive.current) setEstimate(e) }).catch((err: unknown) => { if (alive.current) setEstimateError(errorCode(err) === 'signed_out' ? t('stSignedOut') : failureText(t, err)) })
  }, [])

  const draw = (cloud = viaCloud) => {
    const description = text.trim()
    if (!description) return
    const mine = ++round.current
    setViaCloud(cloud)
    setStage('drawing')
    setBusy(true)
    setError(undefined)
    setPicked(null)
    setCandidates([null, null, null, null])
    let failures = 0
    const one = async (index: number) => {
      try {
        const r = await call<{ image: string }>('studio/draw', { prompt: buildPrompt(description, index, style), ...(cloud ? { cloud: true } : {}) })
        if (alive.current && round.current === mine) setCandidates((c) => c.map((v, i) => (i === index ? r.image : v)))
      } catch (err: unknown) {
        failures++
        if (alive.current && round.current === mine) setError(failureText(t, err))
      }
    }
    // two at a time, as the runtime does: the provider allows a couple of pictures in flight
    void (async () => {
      await Promise.all([one(0), one(1)])
      await Promise.all([one(2), one(3)])
      if (alive.current && round.current === mine) {
        setBusy(false)
        if (failures === 4) setStage('describe')
      }
    })()
  }

  const choose = async () => {
    if (picked === null || !candidates[picked]) return
    const chosen = candidates[picked]!
    setStage('posing')
    setBusy(true)
    setError(undefined)
    try {
      const idle = await still(chosen)
      const source = await png(chosen)
      const stills: Record<string, string> = { idle }
      setMoods({ idle })
      const one = async (mood: string) => {
        try {
          const r = await call<{ image: string }>('studio/pose', { image: source, prompt: KEEP + MOOD_INSTRUCTIONS[mood], ...(viaCloud ? { cloud: true } : {}) })
          stills[mood] = await still(r.image)
        } catch {
          stills[mood] = idle // a pose that failed shows the idle still, so the face is never blank
        }
        if (alive.current) setMoods({ ...stills })
      }
      await Promise.all([one('working'), one('waiting')])
      await Promise.all([one('happy'), one('error')])
      await call('studio/wear', { description: text.trim(), style, face: stills })
      if (alive.current) setStage('done')
    } catch (err: unknown) {
      if (alive.current) {
        setError(failureText(t, err))
        setStage('drawing')
      }
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  const styleChips = h('div', { className: 'nm-chips' }, Object.keys(STYLES).map((id) =>
    h('button', { key: id, type: 'button', className: `nm-chip${style === id ? ' nm-active' : ''}`, onClick: () => setStyle(id) }, t(`style_${id}` as Words))))

  let body: ReactNode
  let footer: ReactNode
  if (stage === 'describe') {
    const cannot = estimate && !estimate.affordable
    const noImage = Boolean(estimateError) && providers.view !== undefined && !providers.view.capabilities.includes('image')
    body = h('form', { id: 'nm-studio', className: 'nm-sheet-form', onSubmit: (e: FormEvent) => { e.preventDefault(); draw(false) } },
      h('p', { className: 'nm-sheet-lead' }, t('stLead')),
      h('textarea', { className: 'nm-textarea', rows: 3, value: text, placeholder: t('stPlaceholder'), maxLength: 200, onChange: (e: FormEvent<HTMLTextAreaElement>) => setText(e.currentTarget.value), 'data-modal-autofocus': true }),
      h('div', { className: 'nm-st-label' }, t('stStyle')),
      styleChips,
      // nothing configured draws pictures (C11): the gate's one sentence naming who could, never the host's error
      noImage ? h(UnavailableLine, { t, view: providers.view!, capability: 'image', link: true, className: 'nm-fine nm-wrap' }) : null,
      h('p', { className: 'nm-fine' },
        noImage ? null
          : estimateError ? t('stNoModel', { message: estimateError })
          : !estimate ? t('stEstimating')
          : estimate.source === 'provider' ? t('stDrawnWith', { label: estimate.label ?? '', model: estimate.imageModel })
          : estimate.unlimited ? (estimate.clips ? t('stCostUnlimitedClips', { n: 8, clips: estimate.clips }) : t('stCostUnlimited', { n: 8 }))
          : cannot ? t('stCannotAfford', { cost: estimate.cny.toFixed(2), left: estimate.leftCny.toFixed(2) })
          : estimate.clips ? t('stCostClips', { cost: estimate.cny.toFixed(2), left: estimate.leftCny.toFixed(2) })
          : t('stCost', { cost: estimate.cny.toFixed(2), left: estimate.leftCny.toFixed(2) })),
      error ? h('div', { className: 'nm-room-error' }, error) : null)
    footer = h('div', { className: 'nm-sheet-actions' },
      h('span', { style: { flex: 1 } }),
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: onClose }, t('cancel')),
      h('button', { type: 'submit', form: 'nm-studio', className: 'nm-pill nm-pill-sm', disabled: !text.trim() || Boolean(estimateError) || Boolean(cannot) }, t('stDraw')))
  } else if (stage === 'drawing') {
    body = h('div', { className: 'nm-sheet-form' },
      h('p', { className: 'nm-sheet-lead' }, busy ? t('stDrawing') : t('stPick')),
      h('div', { className: 'nm-st-grid', role: 'radiogroup' }, candidates.map((image, index) =>
        h('button', { key: index, type: 'button', role: 'radio', 'aria-checked': picked === index, disabled: !image, className: `nm-st-cell${picked === index ? ' nm-active' : ''}`, onClick: () => setPicked(index) },
          image ? h('img', { src: `data:image/png;base64,${image}`, alt: t('stOption', { n: index + 1 }) }) : h('span', { className: 'nm-st-wait' }, busy ? '…' : '—'),
          h('span', { className: 'nm-st-tag' }, t('stOption', { n: index + 1 }))))),
      error ? h('div', { className: 'nm-room-error' }, error) : null,
      // an own provider failed and the account could draw: this round through nanoMuse Cloud, the slot untouched
      error && !busy && !viaCloud && estimate?.source === 'provider' && live.cloud.signedIn
        ? h('div', { style: { marginTop: 6 } }, h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', 'data-testid': 'nm-st-cloud-once', onClick: () => draw(true) }, t('rfUseCloudOnce')))
        : null)
    footer = h('div', { className: 'nm-sheet-actions' },
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: busy, onClick: () => { setStage('describe'); setError(undefined); setViaCloud(false) } }, t('stChange')),
      h('span', { style: { flex: 1 } }),
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: busy, onClick: () => draw(false) }, t('stAgain')),
      h('button', { type: 'button', className: 'nm-pill nm-pill-sm', disabled: busy || picked === null || !candidates[picked], onClick: () => void choose() }, t('stThisOne')))
  } else if (stage === 'posing') {
    const done = Object.keys(moods).length
    body = h('div', { className: 'nm-sheet-form' },
      h('p', { className: 'nm-sheet-lead' }, t('stPosing', { done, total: 5 })),
      h('div', { className: 'nm-st-moods' }, ['idle', ...MOODS].map((mood) =>
        h('div', { key: mood, className: 'nm-st-mood' },
          moods[mood] ? h('img', { src: `data:image/webp;base64,${moods[mood]}`, alt: mood }) : h('span', { className: 'nm-st-wait' }, '…'),
          h('span', { className: 'nm-st-tag' }, t(`mood_${mood}` as Words))))))
    footer = h('div', { className: 'nm-sheet-actions' }, h('span', { style: { flex: 1 } }), h('span', { className: 'nm-fine' }, t('stKeepOpen')))
  } else {
    body = h('div', { className: 'nm-sheet-form' },
      h('div', { className: 'nm-st-moods' }, ['idle', ...MOODS].map((mood) =>
        h('div', { key: mood, className: 'nm-st-mood' }, moods[mood] ? h('img', { src: `data:image/webp;base64,${moods[mood]}`, alt: mood }) : null))),
      h('p', { className: 'nm-sheet-lead' }, t('stDone')),
      // the face is done: a moment of delight, and the one fair ask for a star here (once)
      h(StarNudgeOnce, { t, moment: 'new_look' }))
    footer = h('div', { className: 'nm-sheet-actions' }, h('span', { style: { flex: 1 } }), h('button', { type: 'button', className: 'nm-pill nm-pill-sm', onClick: onClose }, t('stFinish')))
  }
  return h(Sheet, { title: t('stTitle'), closeLabel: t('close'), onClose: stage === 'posing' ? () => undefined : onClose, footer, wide: stage !== 'describe' }, body)
}

/** The overlay entry: opens on the bus (the look editor) and on the agent's request (the rooms' `studio` field). */
export function makeAvatarStudio({ t }: { t: Translate }) {
  return function AvatarStudio(): ReactNode {
    const [open, setOpen] = useState<{ description: string; style: string; key: number } | null>(null)
    const rooms = useRooms()
    const seen = useRef(0)
    useEffect(() => {
      studioBus.open = (description = '', style = 'muse') => setOpen({ description, style, key: Date.now() })
      return () => { studioBus.open = undefined }
    }, [])
    useEffect(() => {
      const request = rooms.studio
      if (!request || !request.at || request.at <= seen.current) return
      if (seen.current === 0) { seen.current = request.at; return } // a request from before this window opened
      seen.current = request.at
      setOpen({ description: request.description, style: request.style, key: request.at })
    }, [rooms.studio])
    if (!open) return null
    return h(Fragment, null, h(AvatarStudioSheet, { key: open.key, t, initial: open.description, style: open.style, onClose: () => setOpen(null) }))
  }
}
