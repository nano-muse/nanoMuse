/**
 * The agent's face where the harness shows a brand: the sidebar mark, the
 * sidebar name, the hero mark above a blank session, the capsule, the header.
 * The face is the account's — the dragon by default, an emoji on a colour, or
 * one drawn in the avatar studio on the phone whose stills the host pulled —
 * and its mood follows what the agent is doing, the way the Android app's
 * `AgentAvatarDisc` and the web app's `Avatar` do: idle, working, waiting (for
 * the person), happy, error.
 *
 * The dragon moves: a short looping clip per mood — a head shake at rest,
 * headphones and a laptop while working, a crystal ball while waiting, a star
 * when pleased — the same clips the phone and the web app play. The still
 * shows where a clip is not worth it or not wanted: small sizes, lists and
 * pickers, a person who prefers reduced motion, a clip that failed to load, the
 * error mood. A drawn face has stills only (the relay keeps no clips), so it
 * and the emoji move as a whole instead: breathe when idle, sway while working,
 * hop while waiting.
 */
import { createElement as h, useState, type CSSProperties, type ReactElement } from 'react'
import type { LiveProfile } from './live.ts'

export type Mood = 'idle' | 'working' | 'waiting' | 'happy' | 'error'

/** Below this the clip is not worth the bytes: the still shows. */
const CLIP_MIN_PX = 44
/** Clips that did not load (a drawn face without them): the still, and no second request. */
const noClip = new Set<string>()
const reducedMotion = typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Document-relative, so it resolves under whatever mount served the page. */
export function stillUrl(profile: LiveProfile | undefined, mood: Mood = 'idle'): string {
  if (profile?.avatar === 'face' && profile.faceId) return `nanomuse/assets/face/${profile.faceId}/${mood}.webp`
  return `nanomuse/assets/dragon-${mood}.webp`
}

/** The clip for a mood: none for the error pose (a still says it better) or the emoji. */
export function clipUrl(profile: LiveProfile | undefined, mood: Mood = 'idle'): string | null {
  if (mood === 'error' || profile?.avatar === 'emoji') return null
  if (profile?.avatar === 'face' && profile.faceId) return `nanomuse/assets/face/${profile.faceId}/${mood}.mp4`
  return `nanomuse/assets/dragon-${mood}.mp4`
}

export interface AvatarProps {
  size: number
  profile?: LiveProfile | undefined
  mood?: Mood
  className?: string | undefined
  title?: string
  /** No clip and no motion: lists, pickers, anything that should hold still. */
  still?: boolean
}

/** A round face of the agent at the requested size, moving when it may; an emoji face is drawn, not loaded. */
export function Avatar({ size, profile, mood = 'idle', className, title, still = false }: AvatarProps): ReactElement {
  const name = title ?? profile?.name ?? 'nanoMuse'
  const [, bump] = useState(0)
  const candidate = still || reducedMotion || size < CLIP_MIN_PX ? null : clipUrl(profile, mood)
  const clip = candidate && !noClip.has(candidate) ? candidate : null
  // the whole face moves when nothing inside it does
  const motion = still || clip || reducedMotion ? '' : mood === 'working' ? ' nm-avatar-working' : mood === 'waiting' ? ' nm-avatar-waiting' : mood === 'idle' ? ' nm-avatar-idle' : ''

  const box: CSSProperties = { width: size, height: size }
  const emoji = profile?.avatar === 'emoji'
  const inner = emoji
    ? h('span', { className: 'nm-avatar-emoji', style: { background: profile.color || '#0064d4', fontSize: Math.round(size * 0.58), lineHeight: `${size}px` } }, profile.emoji || '✨')
    : clip
      ? h('video', {
          key: clip,
          src: clip,
          poster: stillUrl(profile, mood),
          autoPlay: true,
          loop: true,
          muted: true,
          playsInline: true,
          disablePictureInPicture: true,
          'aria-hidden': true,
          onError: () => { noClip.add(clip); bump((n) => n + 1) },
        })
      : h('img', { src: stillUrl(profile, mood), alt: '', width: size, height: size, draggable: false })

  return h('span', {
    role: 'img',
    'aria-label': name,
    title,
    className: `nm-avatar${motion}${className ? ` ${className}` : ''}`,
    style: box,
  }, inner)
}

/** The wordmark beside the mark; plain text in the sidebar's own type. */
export function BrandName({ text }: { text: string }): ReactElement {
  return h('span', { style: { fontWeight: 600, letterSpacing: '-0.01em' } }, text)
}
