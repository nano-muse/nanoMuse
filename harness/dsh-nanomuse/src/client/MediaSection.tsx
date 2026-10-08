/**
 * Settings → Media: the models that draw the face and its clips, after the phone's
 * `MediaModelsScreen`. The image and video rows are the same pickers as Settings → Models'
 * *Making pictures* and *Making clips* (0.1.41): nanoMuse Cloud first while signed in, then
 * each own provider's models that can do the job; the video picker also has *Off*. OpenRouter
 * and the like have no video API, so the face keeps still with one line saying why. Below:
 * the switch that animates a new face by itself (default on), "Make the clips now / Redo
 * clips" with the host's progress ("Animating 2/4…", the stage of the current clip), and
 * the clips on this computer with their sizes. Clips are per device; the account keeps
 * stills only.
 */
import { createElement as h, useCallback, useEffect, useState, type ReactNode } from 'react'
import { call, errorStyle, type Translate } from './api.ts'
import { motionStatus } from './Avatar.tsx'
import { IconCheck, IconImage, IconVideo } from './icons.tsx'
import { useLive, type LiveMotion, type MotionMood } from './live.ts'
import { SlotPicker, useModels } from './ModelsSection.tsx'
import { UnavailableLine, useProviders } from './OwnKey.tsx'

export interface MediaView {
  imageModel: string
  /** Pictures (C11): the account, an own row with image models, or nowhere (`reason` `no_image`). Absent on an older host. */
  image?: { source: 'cloud' | 'provider' | 'none'; label: string; model: string; reason: string }
  video: { source: 'cloud' | 'provider' | 'none'; label: string; model: string; models: { id: string; name: string }[]; off: boolean; reason: string }
  animate: boolean
  motion: LiveMotion
}

const MOODS: MotionMood[] = ['idle', 'working', 'waiting', 'happy']
const SECONDS = 4

function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange(next: boolean): void; label: string; disabled?: boolean }): ReactNode {
  return h('button', { type: 'button', role: 'switch', className: 'nm-switch', 'aria-checked': checked, 'aria-label': label, disabled, onClick: () => onChange(!checked) })
}

function sizeOf(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

export function makeMediaSection(t: Translate) {
  return function MediaSection(): ReactNode {
    const live = useLive()
    const providers = useProviders(t)
    const models = useModels(t)
    const [view, setView] = useState<MediaView | null>(null)
    const [busy, setBusy] = useState<'model' | 'image' | 'animate' | 'clips' | 'check' | null>(null)
    const [error, setError] = useState('')
    const [checked, setChecked] = useState<number | null>(null)
    const reload = useCallback(() => {
      void call<MediaView>('media')
        .then(setView)
        .catch((err: unknown) => setError((err as Error).message))
    }, [])
    useEffect(() => reload(), [reload])
    // the model list and the source follow the account and the own keys: re-read when sign-in, a key row or the face changes
    const ownCount = live.ownKeys?.count ?? 0
    useEffect(() => reload(), [live.cloud.signedIn, live.profile.faceId, ownCount, reload])

    const motion = live.motion
    const progress = motion.progress
    const face = live.profile.avatar === 'face' && live.profile.faceId ? live.profile.faceId : ''
    const haveClips = MOODS.filter((m) => motion.clips[m] && motion.faceId === face)

    const setModel = (provider: string, id: string) => {
      setBusy('model')
      setError('')
      // `auto` drops the stored choice (an empty model); the slot follows the order again
      void call<MediaView>('media', id === 'off' ? { videoModel: 'off' } : id === 'auto' ? { videoModel: '' } : { videoModel: id, videoProvider: provider })
        .then((v) => { setView(v); models.reload() })
        .catch((err: unknown) => setError((err as Error).message))
        .finally(() => setBusy(null))
    }
    const setImage = (provider: string, id: string) => {
      setBusy('image')
      setError('')
      void call('image-model', id === 'auto' ? { model: '' } : { model: id, provider })
        .then(() => { reload(); models.reload() })
        .catch((err: unknown) => setError((err as Error).message))
        .finally(() => setBusy(null))
    }
    const setAnimate = (on: boolean) => {
      setBusy('animate')
      void call<MediaView>('media', { animate: on })
        .then(setView)
        .catch((err: unknown) => setError((err as Error).message))
        .finally(() => setBusy(null))
    }
    const animate = (force: boolean, cloud = false) => {
      setBusy('clips')
      setError('')
      void call('media/animate', cloud ? { force, cloud: true } : { force })
        .catch((err: unknown) => setError((err as Error).message))
        .finally(() => setBusy(null))
    }
    const check = () => {
      setBusy('check')
      setError('')
      void call<{ models: string[] }>('media/check')
        .then((r) => {
          setChecked(r.models.length)
          reload()
        })
        .catch((err: unknown) => setError((err as Error).message))
        .finally(() => setBusy(null))
    }

    if (!view) return h('div', { className: 'nm-section' }, h('p', null, t('mdMediaLead')), error ? h('div', { style: errorStyle }, error) : null)

    const video = view.video
    const videoOn = !video.off && video.source !== 'none'
    // the gate's sentences (C11): nothing configured has image / video models → who could, where the person is
    const gate = providers.view
    const noImage = gate && !gate.capabilities.includes('image') && !view.imageModel && view.image?.source !== 'provider'
    const noVideo = gate && !gate.capabilities.includes('video') && video.source === 'none'
    // the image row: the slot's source and model, as Settings → Models resolves them (`<provider> · <model>`)
    const imageSub = view.image && view.image.source !== 'none'
      ? `${t('mdImageModelSub')} · ${view.image.label}${view.image.model ? ` · ${view.image.model}` : ''}`
      : view.imageModel
        ? `${t('mdImageModelSub')} · nanoMuse Cloud · ${view.imageModel}`
        : noImage
          ? h(UnavailableLine, { t, view: gate, capability: 'image', link: true, className: 'nm-wrap', tag: 'span' })
          : t('mdImageNone')
    const slots = models.view?.slots
    const videoSelect =
      video.source === 'none' && !slots?.video.options.length
        ? null
        : slots
          ? h(SlotPicker, { t, slot: 'video', view: slots.video, disabled: busy !== null, ...(gate ? { catalogue: gate.catalogue } : {}), onPick: setModel })
          : h(
              'select',
              {
                className: 'nm-field nm-select',
                value: video.off ? 'off' : video.model || '',
                disabled: busy !== null,
                'aria-label': t('mdVideoModel'),
                onChange: (e: { currentTarget: HTMLSelectElement }) => setModel('', e.currentTarget.value),
              },
              h('option', { value: 'off' }, t('mdVideoOff')),
              !video.off && !video.models.some((m) => m.id === video.model) && video.model ? h('option', { value: video.model }, video.model) : null,
              video.models.map((m) => h('option', { key: m.id, value: m.id }, m.name)),
            )
    const imageSelect = slots && slots.image.options.length ? h(SlotPicker, { t, slot: 'image', view: slots.image, disabled: busy !== null, ...(gate ? { catalogue: gate.catalogue } : {}), onPick: setImage }) : null
    const videoSub: ReactNode = video.source === 'none'
      ? (noVideo ? h(UnavailableLine, { t, view: gate, capability: 'video', link: true, className: 'nm-wrap', tag: 'span' }) : t('mdVideoNone'))
      : video.off ? t('mdVideoModelSub') : video.reason === 'unchecked' ? t('mdVideoUnchecked') : `${t('mdVideoModelSub')} · ${video.label}`

    const stage = progress?.stage
    const stageText = !stage ? '' : stage.kind === 'uploading' ? t('moStageUploading') : stage.kind === 'submitted' ? t('moStageSubmitted') : stage.kind === 'running' ? t('moStageRunning', { s: stage.elapsedSec ?? 0 }) : t('moStageDownloading')
    const moodName = (m: MotionMood) => (m === 'idle' ? t('moMoodIdle') : m === 'working' ? t('moMoodWorking') : m === 'waiting' ? t('moMoodWaiting') : t('moMoodHappy'))

    return h(
      'div',
      { className: 'nm-section' },
      h('p', null, t('mdMediaLead')),
      h(
        'div',
        { className: 'nm-card' },
        h(
          'div',
          { className: 'nm-row' },
          h('span', { className: 'nm-row-icon' }, h(IconImage, { size: 18 })),
          h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('mdImageModel')), h('span', { className: 'nm-row-sub nm-wrap' }, imageSub)),
          imageSelect,
        ),
        h(
          'div',
          { className: 'nm-row' },
          h('span', { className: 'nm-row-icon' }, h(IconVideo, { size: 18 })),
          h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('mdVideoModel')), h('span', { className: 'nm-row-sub nm-wrap' }, videoSub)),
          videoSelect,
        ),
        video.source === 'provider'
          ? h(
              'div',
              { className: 'nm-row' },
              h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-sub nm-wrap' }, checked === null ? '' : checked ? t('mdVideoChecked', { n: checked }) : t('mdVideoCheckNone'))),
              h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: busy !== null, onClick: check }, busy === 'check' ? t('mdVideoChecking') : t('mdVideoCheck')),
            )
          : null,
      ),
      h(
        'div',
        { className: 'nm-card' },
        h(
          'div',
          { className: 'nm-row' },
          h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, t('mdAnimate')), h('span', { className: 'nm-row-sub nm-wrap' }, t('mdAnimateSub'))),
          h(Switch, { checked: view.animate, label: t('mdAnimate'), disabled: busy !== null, onChange: setAnimate }),
        ),
        h(
          'div',
          { className: 'nm-row' },
          h(
            'div',
            { className: 'nm-row-main' },
            h('span', { className: 'nm-row-title' }, progress?.running ? motionStatus(live, t) : haveClips.length ? t('mdClipsDone', { n: haveClips.length, total: MOODS.length }) : t('mdClipsList')),
            h(
              'span',
              { className: 'nm-row-sub nm-wrap' },
              progress?.running
                ? `${progress.current ? moodName(progress.current) : ''}${stageText ? ` · ${stageText}` : ''}`
                : !face
                  ? t('mdClipsNoFace')
                  : !videoOn
                    ? t('mdClipsNoVideo')
                    : t('mdClipsCost', { s: SECONDS, model: video.model }),
            ),
          ),
          progress?.running
            ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => void call('media/cancel', {}).catch(() => undefined) }, t('mdStopClips'))
            : h('button', { type: 'button', className: 'nm-pill nm-pill-sm', disabled: busy !== null || !face || !videoOn, onClick: () => animate(haveClips.length > 0) }, haveClips.length ? t('mdRedoClips') : t('mdMakeClips')),
        ),
        progress && !progress.running && progress.failed.length
          ? h('div', { className: 'nm-row' },
              h('span', { className: 'nm-row-sub nm-wrap nm-md-failed' }, t('mdClipsFailed', { moods: progress.failed.map(moodName).join(', ') }), progress.error ? ` ${t('mdClipsError', { error: progress.error })}` : ''),
              // an own provider's run failed and the account could draw them: this once, the slot untouched
              progress.source && progress.source !== 'nanomuse' && live.cloud.signedIn
                ? h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', 'data-testid': 'nm-md-cloud-once', disabled: busy !== null || !face, onClick: () => animate(true, true) }, t('rfUseCloudOnce'))
                : null)
          : null,
        progress?.running
          ? h('div', { className: 'nm-md-bar', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': progress.total, 'aria-valuenow': progress.done }, h('span', { style: { width: `${Math.round((progress.done / Math.max(1, progress.total)) * 100)}%` } }))
          : null,
      ),
      h('h2', null, t('mdClipsList')),
      h(
        'div',
        { className: 'nm-card' },
        MOODS.map((m) => {
          const clip = motion.faceId === face && face ? motion.clips[m] : undefined
          return h(
            'div',
            { key: m, className: 'nm-row' },
            clip ? h('video', { className: 'nm-md-clip', src: `nanomuse/avatar/motion/${m}.mp4?v=${clip.v}`, muted: true, loop: true, playsInline: true, autoPlay: true, 'aria-hidden': true }) : h('span', { className: 'nm-md-clip nm-md-clip-none', 'aria-hidden': true }),
            h('div', { className: 'nm-row-main' }, h('span', { className: 'nm-row-title' }, moodName(m)), h('span', { className: 'nm-row-sub' }, clip ? sizeOf(clip.size) : progress?.running && progress.current === m ? stageText || t('moStageSubmitted') : '—')),
            clip ? h('span', { className: 'nm-ob-granted' }, h(IconCheck, { size: 16 })) : null,
          )
        }),
        h('div', { className: 'nm-row' }, h('span', { className: 'nm-row-sub nm-wrap' }, t('mdClipsPerDevice'))),
      ),
      error ? h('div', { style: errorStyle }, error) : null,
    )
  }
}
