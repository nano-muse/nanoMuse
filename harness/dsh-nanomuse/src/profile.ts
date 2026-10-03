/**
 * The agent's name and look, the same on every device of the account.
 *
 * The relay keeps one profile per account (`GET /v1/me/profile`: the name, which
 * face — the dragon, an emoji on a colour, or one drawn in the avatar studio on
 * the phone — and, for a drawn face, its five stills as WebP) and tells the other
 * devices over the hub when it changes. Here the desktop *pulls*: on sign-in, on
 * start and on that `profile` frame, when the relay's `rev` is newer than the one
 * last worn. A drawn face's stills land under `$DSH_HOME/nanomuse/faces/<id>/`
 * and the host serves them at `/nanomuse/assets/face/<id>/<mood>.webp`, so the
 * browser half shows the same face the phone does. Nothing is pushed yet: the
 * desktop has no avatar studio of its own, and renaming here comes later.
 *
 * Never a key, never a message: the fields are the name, the face kind, the
 * emoji and its colour, the description and style, and the pictures.
 */
import { mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { Relay, RelayProfile } from './relay.ts'

export const MOODS = ['idle', 'working', 'waiting', 'happy', 'error'] as const
export type Mood = (typeof MOODS)[number]

/** What the browser half needs to draw the agent. */
export interface Profile {
  rev: number
  /** What the person calls the agent; `nanoMuse` until the account says otherwise. */
  name: string
  /** `dragon` (the default), `emoji`, or `face`. */
  avatar: 'dragon' | 'emoji' | 'face'
  emoji: string
  color: string
  description: string
  style: string
  /** The folder under `faces/` when `avatar` is `face`. */
  faceId: string
}

export const DEFAULT_PROFILE: Profile = { rev: 0, name: 'nanoMuse', avatar: 'dragon', emoji: '', color: '', description: '', style: '', faceId: '' }

const FACE_ID = /^[a-f0-9]{6,40}$/

export class ProfileStore {
  private profile: Profile = DEFAULT_PROFILE
  private readonly listeners = new Set<() => void>()

  /** @param dir - `$DSH_HOME/nanomuse`; the profile file and the `faces/` folder live under it. */
  constructor(
    private readonly dir: string,
    private readonly relay: Relay,
  ) {}

  current(): Profile {
    return this.profile
  }

  onChange(listener: () => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  /** Where a still (or a clip, if a face ever has them) of the worn face is on disk, or nothing for the dragon and the emoji. */
  stillPath(faceId: string, mood: string, ext: 'webp' | 'mp4' = 'webp'): string | undefined {
    if (!FACE_ID.test(faceId) || !(MOODS as readonly string[]).includes(mood)) return undefined
    return join(this.dir, 'faces', faceId, `${mood}.${ext}`)
  }

  async load(): Promise<void> {
    try {
      const raw = JSON.parse(await readFile(join(this.dir, 'profile.json'), 'utf8')) as Partial<Profile>
      this.profile = normalize(raw)
    } catch {
      this.profile = DEFAULT_PROFILE
    }
  }

  /**
   * Fetch the relay's profile and wear it when it is newer (or when `force`).
   * @returns true when something changed.
   */
  async pull(apiKey: string, force = false): Promise<boolean> {
    const light = await this.relay.profile(apiKey, false)
    if (light.rev === 0) {
      // The relay has nothing for this account yet; the phone (or the runtime) seeds it.
      if (this.profile.rev === 0) return false
      await this.wear(DEFAULT_PROFILE)
      return true
    }
    if (!force && light.rev <= this.profile.rev) return false
    const next: Profile = {
      rev: light.rev,
      name: light.name.trim() || 'nanoMuse',
      avatar: 'dragon',
      emoji: '',
      color: '',
      description: light.description,
      style: light.style,
      faceId: '',
    }
    if (light.avatar === 'emoji') {
      next.avatar = 'emoji'
      next.emoji = light.emoji || '✨'
      next.color = light.color || '#0064d4'
    } else if (light.avatar === 'face' && light.hasFace) {
      const faceId = await this.storeFace(apiKey, light)
      if (faceId) {
        next.avatar = 'face'
        next.faceId = faceId
      }
    }
    await this.wear(next)
    return true
  }

  /** Forget the account's look (sign-out): back to the dragon, the pictures stay on disk. */
  async reset(): Promise<void> {
    await this.wear(DEFAULT_PROFILE)
  }

  /**
   * Wear a look written here (a rename, an emoji face) without a pull: for a
   * desktop with no account, or while the relay is unreachable. A drawn face
   * keeps its pictures only while `avatar` stays `face`.
   */
  async wearLocal(next: Partial<Profile>): Promise<void> {
    await this.wear(normalize({ ...this.profile, ...next }))
  }

  private async storeFace(apiKey: string, light: RelayProfile): Promise<string | undefined> {
    const faceId = light.faceId
    if (!FACE_ID.test(faceId)) return undefined
    const folder = join(this.dir, 'faces', faceId)
    if (await exists(join(folder, 'idle.webp'))) return faceId
    const full = await this.relay.profile(apiKey, true)
    const face = full.face ?? {}
    const idle = decode(face.idle)
    if (!idle) return undefined
    await mkdir(folder, { recursive: true })
    for (const mood of MOODS) {
      const raw = decode(face[mood]) ?? idle
      await writeFile(join(folder, `${mood}.webp`), raw)
    }
    await writeFile(join(folder, 'face.json'), JSON.stringify({ description: light.description, style: light.style, from: 'account' }, null, 2) + '\n')
    // Older pulled faces are not worn any more.
    try {
      for (const other of await readdir(join(this.dir, 'faces'))) {
        if (other !== faceId) await rm(join(this.dir, 'faces', other), { recursive: true, force: true })
      }
    } catch {
      // nothing to tidy
    }
    return faceId
  }

  private async wear(next: Profile): Promise<void> {
    this.profile = next
    await mkdir(this.dir, { recursive: true })
    await writeFile(join(this.dir, 'profile.json'), JSON.stringify(next, null, 2) + '\n', { mode: 0o600 })
    for (const listener of this.listeners) listener()
  }
}

function normalize(raw: Partial<Profile>): Profile {
  const avatar = raw.avatar === 'emoji' || raw.avatar === 'face' ? raw.avatar : 'dragon'
  return {
    rev: Number(raw.rev ?? 0) || 0,
    name: String(raw.name ?? '').trim() || 'nanoMuse',
    avatar,
    emoji: String(raw.emoji ?? ''),
    color: String(raw.color ?? ''),
    description: String(raw.description ?? ''),
    style: String(raw.style ?? ''),
    faceId: avatar === 'face' && FACE_ID.test(String(raw.faceId ?? '')) ? String(raw.faceId) : '',
  }
}

function decode(value: string | undefined): Buffer | undefined {
  if (!value) return undefined
  try {
    const raw = Buffer.from(value, 'base64')
    return raw.length > 0 ? raw : undefined
  } catch {
    return undefined
  }
}

async function exists(path: string): Promise<boolean> {
  try {
    await readFile(path)
    return true
  } catch {
    return false
  }
}
