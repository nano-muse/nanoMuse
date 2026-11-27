/**
 * Short clips through Alibaba Cloud Model Studio's asynchronous video API — Wan 2.2 Flash
 * by default, or whichever Wan or MiniMax model the person picked. A port of the phone's
 * `media/VideoGen.kt`, step for step, so a clip made here comes out like one made there:
 *
 *  1. the first frame goes to Model Studio's free 48-hour temporary storage
 *     (`GET {host}/api/v1/uploads?action=getPolicy&model=…`, then a multipart POST to OSS)
 *     and comes back as an `oss://` URL — the video API takes URLs, not inline data;
 *  2. `POST {host}/api/v1/services/aigc/video-generation/video-synthesis` with
 *     `X-DashScope-Async: enable` (and `X-DashScope-OssResourceResolve: enable` for the OSS
 *     input) returns a task;
 *  3. `GET {host}/api/v1/tasks/{id}` is polled every ten seconds, twelve minutes at most;
 *  4. the MP4 is downloaded from the `video_url` the task ends with.
 *
 * `host` is Model Studio itself (`https://dashscope.aliyuncs.com`) with the person's own
 * key, or a self-hosted relay whose live menu explicitly advertises video generation.
 *
 * The model families take different bodies: MiniMax wants `media[first_frame]`,
 * `resolution`, `ratio` and `duration`; Wan up to 2.6 wants `img_url`, `resolution`/`size`
 * and — on wan2.6 and 2.5 — a `duration`; Wan 2.7 speaks Model Studio's newer protocol,
 * `media[first_frame]` with `resolution` for a picture and `resolution` with `ratio` for
 * words, `duration` 2–15 on both. Wan also splits text-to-video and image-to-video into
 * sibling models; whichever was picked, the sibling is used for the other job.
 *
 * Billing is per output second, so callers keep `seconds` at the minimum that reads well
 * (4 for an avatar loop). No Node-only API here beyond `fetch`, `FormData` and `Blob`; the
 * tests pass a fake `fetch`.
 */

export const POLL_MS = 10_000
export const MAX_WAIT_MS = 12 * 60_000
export const DEFAULT_VIDEO_MODEL = 'wan2.2-i2v-flash'

/** One video model on one host: what `imageToVideo` needs and nothing more. */
export interface VideoEndpoint {
  /** A Model Studio or explicitly media-enabled relay origin, without an API path. */
  host: string
  apiKey: string
  model: string
  /** Where the key is from, for the settings row: `nanoMuse Cloud`, a provider's name. */
  label: string
  /** The provider the key belongs to (`nanomuse` for the account). */
  instanceId: string
}

/** This model takes a user's portrait, storyboard and voice, outside the Wan protocol. */
export function wizshotStudio(ep: VideoEndpoint): string | undefined {
  return ep.instanceId === 'nanomuse' && ep.model === 'ernie-wizshot-me' ? new URL('/app/?video=wizshot', ep.host).href : undefined
}

function requireClipInputs(ep: VideoEndpoint): void {
  const url = wizshotStudio(ep)
  if (url) throw new VideoGenError(`Add your portrait, storyboard and WAV voice reference at ${url}`)
}

export class VideoGenError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'VideoGenError'
  }
}

export type VideoProgress = { kind: 'uploading' } | { kind: 'submitted' } | { kind: 'running'; elapsedSec: number } | { kind: 'downloading' }

export interface VideoOptions {
  fetch?: typeof fetch
  /** Waits between polls; the tests pass one that does not. */
  sleep?: (ms: number) => Promise<void>
  pollMs?: number
  maxWaitMs?: number
  onProgress?: (p: VideoProgress) => void
  signal?: AbortSignal
  /** The clock, for the tests. */
  now?: () => number
}

/** The first frame as bytes: a PNG or WebP, 256–5760 px a side, aspect within [0.4, 2.5] — a face still is a 512 px square. */
export interface Frame {
  bytes: Uint8Array
  mime: string
  name: string
}

/**
 * The host of a provider's base URL: `https://….maas.aliyuncs.com`, `https://dashscope.aliyuncs.com`
 * or the relay, with `/compatible-mode/v1`, `/api/v1` and a trailing `/v1` taken off.
 */
export function hostOf(baseUrl: string): string {
  let host = baseUrl.trim()
  const compat = host.indexOf('/compatible-mode')
  if (compat >= 0) host = host.slice(0, compat)
  const api = host.indexOf('/api/v1')
  if (api >= 0) host = host.slice(0, api)
  host = host.replace(/\/+$/, '')
  if (host.endsWith('/v1')) host = host.slice(0, -3)
  return host.replace(/\/+$/, '')
}

export function speaksDashScope(baseUrl: string): boolean {
  return baseUrl.includes('aliyuncs.com') || baseUrl.includes('dashscope')
}

/**
 * The video models Model Studio serves through this API, as of this build. Its `/models`
 * list does not mention them (that list is the chat side), so these are the candidates
 * `probe` checks against the person's key; the first is the recommended one.
 */
export const KNOWN_DASHSCOPE_MODELS = ['wan2.2-i2v-flash', 'wan2.7-i2v', 'wan2.7-t2v', 'MiniMax/MiniMax-H3', 'wan2.6-i2v', 'wan2.6-t2v', 'wan2.5-i2v-preview', 'wan2.5-t2v-preview', 'wan2.2-i2v-plus', 'wan2.2-t2v-plus']

/** Names that mean "video" in a provider's model list. */
export function looksLikeVideoModel(id: string): boolean {
  const s = id.toLowerCase()
  return ['t2v', 'i2v', 'video', 'minimax-h', 'hailuo', 'kling', 'veo', 'seedance', 'sora'].some((w) => s.includes(w))
}

function isWan(model: string): boolean {
  return model.toLowerCase().startsWith('wan')
}

/** Wan 2.7 (`wan2.7-i2v`, `wan2.7-t2v`, their dated snapshots): the newer protocol. */
export function isWan27(model: string): boolean {
  return model.toLowerCase().startsWith('wan2.7')
}

/**
 * The Wan sibling for the job: `…-i2v…` when starting from a picture, `…-t2v…` from words.
 * Wan 2.2 has no text-to-video Flash: its Plus is the sibling there. Wan 2.7's dated
 * snapshots differ between the two (`wan2.7-t2v-2026-06-12`, `wan2.7-i2v-2026-04-25`), so
 * the sibling there is the undated id, which Model Studio keeps current.
 */
export function modelFor(model: string, fromImage: boolean): string {
  if (!isWan(model)) return model
  if (isWan27(model)) {
    const kind = fromImage ? 'i2v' : 't2v'
    return model.toLowerCase().includes(kind) ? model : `wan2.7-${kind}`
  }
  if (fromImage) return model.replace('t2v', 'i2v')
  if (model.startsWith('wan2.2')) return 'wan2.2-t2v-plus'
  return model.replace('i2v', 't2v')
}

/** Wan 2.2 is priced by resolution (480P is half of 720P) and the avatar's clips are small; the newer Wans start at 720P. */
export function wanResolution(model: string): string {
  return model.startsWith('wan2.2') ? '480P' : '720P'
}

/** Wan 2.2 has a fixed length; 2.5 takes 5 or 10; 2.6 anything from 2 to 15. MiniMax 4–15. */
export function durationFor(model: string, seconds: number): number | undefined {
  if (model.startsWith('wan2.2')) return undefined
  if (model.startsWith('wan2.5')) return seconds <= 7 ? 5 : 10
  if (isWan(model)) return Math.min(15, Math.max(2, seconds))
  return Math.min(15, Math.max(4, seconds))
}

/** Wan text-to-video takes a pixel size instead of a ratio; 720p-class frames for each ratio. */
export function wanSize(ratio: string): string {
  switch (ratio) {
    case '16:9':
      return '1280*720'
    case '9:16':
      return '720*1280'
    case '4:3':
      return '960*720'
    case '3:4':
      return '720*960'
    case '21:9':
      return '1680*720'
    default:
      return '960*960'
  }
}

/** The body of an image-to-video task, as the two families want it. */
export function imageToVideoBody(model: string, ossUrl: string, prompt: string, seconds: number): Record<string, unknown> {
  const input: Record<string, unknown> = { prompt }
  const parameters: Record<string, unknown> = { watermark: false }
  if (isWan27(model)) {
    input.media = [{ type: 'first_frame', url: ossUrl }]
    parameters.resolution = '720P'
  } else if (isWan(model)) {
    input.img_url = ossUrl
    parameters.resolution = wanResolution(model)
  } else {
    input.media = [{ type: 'first_frame', url: ossUrl }]
    parameters.resolution = '768P'
  }
  const duration = durationFor(model, seconds)
  if (duration !== undefined) parameters.duration = duration
  return { model, input, parameters }
}

/** The body of a text-to-video task. */
export function textToVideoBody(model: string, prompt: string, seconds: number, ratio: string): Record<string, unknown> {
  const parameters: Record<string, unknown> = { watermark: false }
  if (isWan27(model)) {
    parameters.resolution = '720P'
    parameters.ratio = ratio === '21:9' ? '16:9' : ratio // 2.7 has 16:9, 9:16, 1:1, 4:3, 3:4
  } else if (isWan(model)) parameters.size = wanSize(ratio)
  else {
    parameters.resolution = '768P'
    parameters.ratio = ratio
  }
  const duration = durationFor(model, seconds)
  if (duration !== undefined) parameters.duration = duration
  return { model, input: { prompt }, parameters }
}

/** How long the probe waits for Model Studio before it answers "could not be asked". */
const PROBE_TIMEOUT_MS = 15_000

/**
 * Whether `model` exists for this key, without making a video: an empty task is submitted
 * and Model Studio answers 404 "Model not exist" for an unknown name, or accepts the task
 * (which then fails at once on the missing prompt — nothing is billed). `undefined` when
 * the host could not be asked (offline, a refused key).
 */
export async function probe(host: string, apiKey: string, model: string, fetchImpl: typeof fetch = fetch, timeoutMs = PROBE_TIMEOUT_MS): Promise<boolean | undefined> {
  try {
    const res = await fetchImpl(`${host}/api/v1/services/aigc/video-generation/video-synthesis`, {
      method: 'POST',
      headers: { authorization: `Bearer ${apiKey}`, 'content-type': 'application/json', 'X-DashScope-Async': 'enable' },
      body: JSON.stringify({ model, input: {}, parameters: {} }),
      signal: AbortSignal.timeout(timeoutMs),
    })
    const text = await res.text().catch(() => '')
    if (res.ok) return true
    if (res.status === 404 || /model not exist/i.test(text)) return false
    if (res.status === 401 || res.status === 403) return undefined
    // Accepted the model name but not the empty body: the model is there.
    if (res.status === 400) return true
    return undefined
  } catch {
    return undefined
  }
}

/** A clip that starts from `frame`. Returns the MP4 bytes. */
export async function imageToVideo(ep: VideoEndpoint, frame: Frame, prompt: string, seconds = 4, options: VideoOptions = {}): Promise<Uint8Array> {
  requireClipInputs(ep)
  const progress = options.onProgress ?? (() => undefined)
  progress({ kind: 'uploading' })
  const model = modelFor(ep.model, true)
  const ossUrl = await uploadTemp({ ...ep, model }, frame, options.fetch ?? fetch, options.signal)
  const task = await createTask(ep, imageToVideoBody(model, ossUrl, prompt, seconds), true, options.fetch ?? fetch, options.signal)
  progress({ kind: 'submitted' })
  const url = await poll(ep, task, options)
  progress({ kind: 'downloading' })
  return download(url, options.fetch ?? fetch, options.signal)
}

/** A clip from words alone. `ratio` is one of 16:9, 9:16, 1:1, 4:3, 3:4, 21:9. */
export async function textToVideo(ep: VideoEndpoint, prompt: string, seconds = 4, ratio = '1:1', options: VideoOptions = {}): Promise<Uint8Array> {
  requireClipInputs(ep)
  const progress = options.onProgress ?? (() => undefined)
  const model = modelFor(ep.model, false)
  const task = await createTask(ep, textToVideoBody(model, prompt, seconds, ratio), false, options.fetch ?? fetch, options.signal)
  progress({ kind: 'submitted' })
  const url = await poll(ep, task, options)
  progress({ kind: 'downloading' })
  return download(url, options.fetch ?? fetch, options.signal)
}

// ── the protocol ──────────────────────────────────────────────────────

/** Model Studio's temporary storage: a signed OSS policy, then a multipart POST. Returns the `oss://` URL. */
export async function uploadTemp(ep: VideoEndpoint, frame: Frame, fetchImpl: typeof fetch = fetch, signal?: AbortSignal): Promise<string> {
  const policyRes = await fetchImpl(`${ep.host}/api/v1/uploads?action=getPolicy&model=${encodeURIComponent(ep.model)}`, {
    headers: { authorization: `Bearer ${ep.apiKey}` },
    signal: signal ?? null,
  })
  const policyText = await policyRes.text().catch(() => '')
  if (!policyRes.ok) throw new VideoGenError(`Upload policy failed (HTTP ${policyRes.status})${apiMessage(policyText)}`)
  let policy: Record<string, string>
  try {
    const data = (JSON.parse(policyText) as { data?: Record<string, string> }).data
    if (!data || typeof data !== 'object') throw new Error('no data')
    policy = data
  } catch {
    throw new VideoGenError('Upload policy: no data')
  }
  const key = `${policy.upload_dir ?? ''}/${frame.name}`
  const form = new FormData()
  form.set('OSSAccessKeyId', policy.oss_access_key_id ?? '')
  form.set('Signature', policy.signature ?? '')
  form.set('policy', policy.policy ?? '')
  form.set('x-oss-object-acl', policy.x_oss_object_acl || 'private')
  form.set('x-oss-forbid-overwrite', policy.x_oss_forbid_overwrite || 'true')
  form.set('key', key)
  form.set('file', new Blob([frame.bytes as BlobPart], { type: frame.mime }), frame.name)
  const res = await fetchImpl(policy.upload_host ?? '', { method: 'POST', body: form, signal: signal ?? null })
  if (!res.ok) throw new VideoGenError(`Upload failed (HTTP ${res.status})`)
  return `oss://${key}`
}

async function createTask(ep: VideoEndpoint, body: Record<string, unknown>, ossInput: boolean, fetchImpl: typeof fetch, signal?: AbortSignal): Promise<string> {
  const headers: Record<string, string> = { authorization: `Bearer ${ep.apiKey}`, 'content-type': 'application/json', 'X-DashScope-Async': 'enable' }
  if (ossInput) headers['X-DashScope-OssResourceResolve'] = 'enable'
  const res = await fetchImpl(`${ep.host}/api/v1/services/aigc/video-generation/video-synthesis`, { method: 'POST', headers, body: JSON.stringify(body), signal: signal ?? null })
  const text = await res.text().catch(() => '')
  if (!res.ok) throw new VideoGenError(`HTTP ${res.status}${apiMessage(text)}`)
  let json: { output?: { task_id?: unknown }; message?: unknown }
  try {
    json = JSON.parse(text) as typeof json
  } catch {
    throw new VideoGenError('Unreadable response')
  }
  const id = typeof json.output?.task_id === 'string' ? json.output.task_id.trim() : ''
  if (!id) throw new VideoGenError(typeof json.message === 'string' && json.message.trim() ? json.message : 'No task id')
  return id
}

async function poll(ep: VideoEndpoint, taskId: string, options: VideoOptions): Promise<string> {
  const fetchImpl = options.fetch ?? fetch
  const sleep = options.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)))
  const now = options.now ?? Date.now
  const pollMs = options.pollMs ?? POLL_MS
  const maxWait = options.maxWaitMs ?? MAX_WAIT_MS
  const progress = options.onProgress ?? (() => undefined)
  const started = now()
  for (;;) {
    await sleep(pollMs)
    if (options.signal?.aborted) throw new VideoGenError('Cancelled')
    const res = await fetchImpl(`${ep.host}/api/v1/tasks/${encodeURIComponent(taskId)}`, { headers: { authorization: `Bearer ${ep.apiKey}` }, signal: options.signal ?? null })
    const text = await res.text().catch(() => '')
    if (!res.ok) throw new VideoGenError(`Task query failed (HTTP ${res.status})${apiMessage(text)}`)
    let json: { output?: Record<string, unknown> }
    try {
      json = JSON.parse(text) as typeof json
    } catch {
      throw new VideoGenError('Unreadable task')
    }
    const out = json.output ?? {}
    const status = String(out.task_status ?? '')
    if (status === 'SUCCEEDED') {
      const url = typeof out.video_url === 'string' ? out.video_url.trim() : ''
      if (!url) throw new VideoGenError('No video URL')
      return url
    }
    if (status === 'FAILED' || status === 'CANCELED' || status === 'UNKNOWN') throw new VideoGenError(failureMessage(out))
    const elapsed = Math.floor((now() - started) / 1000)
    progress({ kind: 'running', elapsedSec: elapsed })
    if (now() - started > maxWait) throw new VideoGenError(`Timed out after ${Math.floor(elapsed / 60)} min`)
  }
}

async function download(url: string, fetchImpl: typeof fetch, signal?: AbortSignal): Promise<Uint8Array> {
  const res = await fetchImpl(url, { signal: signal ?? null })
  if (!res.ok) throw new VideoGenError(`Video download failed (${res.status})`)
  const bytes = new Uint8Array(await res.arrayBuffer())
  if (!bytes.length) throw new VideoGenError('Empty video')
  return bytes
}

/** The person-facing reason from a failed task; the activation message gets a plainer wording. */
export function failureMessage(output: Record<string, unknown>): string {
  const code = typeof output.code === 'string' ? output.code : ''
  const message = typeof output.message === 'string' ? output.message : ''
  if (/not activated/i.test(message)) return "The video model is not activated on this account: open the model's card in the Model Studio console and activate it"
  if (message.trim()) return code ? `${code}: ${message}` : message
  if (code) return code
  const status = typeof output.task_status === 'string' && output.task_status ? output.task_status : 'failed'
  return `Video task ${status}`
}

/** DashScope puts the message at the top; the nanoMuse relay answers OpenAI-shaped (`error.message`, e.g. the clip allowance). */
export function apiMessage(text: string): string {
  try {
    const json = JSON.parse(text) as { message?: unknown; error?: { message?: unknown } }
    const top = typeof json.message === 'string' ? json.message : ''
    const nested = typeof json.error?.message === 'string' ? json.error.message : ''
    const m = top || nested
    return m ? `: ${m}` : ''
  } catch {
    return ''
  }
}
