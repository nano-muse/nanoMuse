/**
 * Reach: the account's other devices as tools of this computer's Muse.
 *
 * The phone (and any other computer signed in to the account) is on the hub;
 * this plugin gives the agent the same tools the Python runtime has in
 * `nanomuse/tools/devices.py` — `devices`, `device_screen`, `device_shell`,
 * `device_files`, `device_open`, `device_notify` and `delegate`, a whole job in
 * words for the other device's own Muse — speaking the frames in `docs/hub.md`
 * through `ctx.nanomuseCloud.hub`. Commands are judged where they are typed: a
 * `device_shell` or `device_open` asks the person here first through the
 * harness's own approval card, and when the remote Muse hits something that
 * needs approval while it works on a `delegate`, that question travels back as
 * an `approval` event and is answered here too, never by the other Muse.
 *
 * A screenshot comes back as a durable image the model can look at, the way the
 * MCP client admits images: saved through the attachment store once the current
 * model is known to take image input; otherwise the text says what was seen.
 *
 * The plugin also tells the agent who it is: a system-prompt context with the
 * account's name for it and the devices on the hub, refreshed per assembly.
 */
import type { Context } from '@deepseek-ai/cordis'
import type { ContentBlock } from '@deepseek-ai/dsh-llm'
import type { JsonValue } from '@deepseek-ai/dsh-util-values'
import { defineTool, type ToolExecution, type ToolExecutionResult, type ToolRunContext } from '@deepseek-ai/dsh-tools'
import type { ImageMediaType } from '@deepseek-ai/dsh-attachment'
import type {} from '@deepseek-ai/dsh-user-approval'
import type {} from '@deepseek-ai/dsh-system-prompt'
import type {} from '@deepseek-ai/dsh-llm'
import type {} from '@deepseek-ai/dsh-attachment'
import type {} from './cloud.ts'
import { HubError, type HubDevice } from './hub.ts'

export const name = 'nanomuse-reach'
/** The tool registry and the account; approval, attachments, llm and the system prompt are used when present. */
export const inject = ['tools', 'nanomuseCloud']

const DEVICE = {
  type: 'string',
  description: 'Which device: its name as listed by `devices` (e.g. "Phone", "Xiaomi"), its id, or "phone" for the only phone. Empty picks the only other device.',
} as const

const IMAGE_TYPES = new Set<string>(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])

export function apply(ctx: Context): void {
  const cloud = ctx.nanomuseCloud
  const hub = cloud.hub

  const describe = (d: HubDevice) =>
    `${d.name} (${d.kind}${d.os ? `, ${d.os}` : ''}; id ${d.id}; ${d.online ? 'online' : 'offline'}${d.controllable ? '' : '; cannot be asked to do things'})`

  const offline = () => new Error(cloud.signedIn ? 'This computer is not connected to the hub right now; try again in a moment.' : 'Not signed in to nanoMuse Cloud: Settings → nanoMuse Cloud.')

  const target = (ref: string | undefined): HubDevice => {
    if (!hub.connected) throw offline()
    const d = hub.find(ref ?? '')
    if (!d) {
      const others = hub.devices.filter((x) => x.id !== hub.deviceId && x.kind !== 'web')
      throw new Error(others.length ? `No device matches "${ref ?? ''}". Devices: ${others.map((x) => x.name).join(', ')}.` : 'No other device is signed in to this account yet.')
    }
    if (!d.online) throw new Error(`${d.name} is offline.`)
    return d
  }

  /** Ask the person here, through the harness's approval card; without the service, the policy is to refuse. */
  const approve = async (exec: ToolRunContext, toolName: string, reason: string, zh: string): Promise<void> => {
    const approval = ctx.get('approval')
    if (!approval || !exec.agent) throw new Error('Approval is not available in this session; the request was not sent.')
    const outcome = await approval.request({ agent: exec.agent, toolName, callId: exec.callId, reason, displayReason: { en: reason, zh }, signal: exec.signal })
    if (outcome !== 'allowed-once') throw new Error(`The person did not approve: ${reason} (${outcome}).`)
  }

  const fail = (error: unknown): never => {
    if (error instanceof HubError) throw new Error(`${error.code}: ${error.message}`)
    throw error
  }

  // -- devices -------------------------------------------------------------------------

  ctx.effect(
    () =>
      ctx.tools.register(
        defineTool({
          name: 'devices',
          description: "The person's other devices on nanoMuse Cloud (phone, other computers): names, kinds, online or not. Call before the device_* tools when unsure which device is which.",
          parameters: {},
          output: {
            schema: {
              type: 'object',
              properties: {
                connected: { type: 'boolean' },
                this: { type: 'string' },
                devices: { type: 'array', items: { type: 'json' } },
              },
              additionalProperties: false,
            },
            render: (_args, value) => {
              const list = (value.devices ?? []) as unknown as HubDevice[]
              if (!value.connected) return [{ type: 'text', text: cloud.signedIn ? 'Not connected to the hub right now.' : 'Not signed in to nanoMuse Cloud.' }]
              if (list.length === 0) return [{ type: 'text', text: 'No other device is signed in to this account.' }]
              return [{ type: 'text', text: list.map((d) => `- ${describe(d)}`).join('\n') }]
            },
          },
          isConcurrencySafe: () => true,
          async execute() {
            const list = hub.devices.filter((d) => d.id !== hub.deviceId && d.kind !== 'web')
            return { connected: hub.connected, this: hub.deviceId ?? '', devices: list.map((d) => ({ ...d })) as unknown as JsonValue[] }
          },
          presentCall: () => ({ card: 'generic', title: 'Devices on the account', kind: 'other', rawInput: {} }),
        }),
      ),
    'nanomuse reach: devices',
  )

  // -- device_screen -------------------------------------------------------------------

  const projections = new WeakMap<ToolExecution, ContentBlock[]>()
  ctx.effect(
    () =>
      ctx.tools.register(
        defineTool({
          name: 'device_screen',
          description: "A screenshot of another device's screen right now (the phone's, or another computer's). Look, then decide; this does not touch the device.",
          parameters: { device: DEVICE },
          output: {
            schema: {
              type: 'object',
              properties: { device: { type: 'string' }, width: { type: 'integer' }, height: { type: 'integer' }, mime: { type: 'string' }, bytes: { type: 'integer' } },
              additionalProperties: false,
            },
            render: (_args, value) => [{ type: 'text', text: `Screenshot of ${value.device} (${value.width}×${value.height}, ${value.mime}, ${value.bytes} bytes).` }],
          },
          timeoutMs: 60_000,
          async execute(args, exec) {
            const d = target(args.device)
            const body = await hub.call(d.id, 'screen', {}, { signal: exec.signal, timeoutMs: 45_000 }).catch(fail)
            const mime = String(body.mime ?? 'image/png')
            const data = typeof body.data === 'string' ? body.data : ''
            const value = { device: d.name, width: Number(body.width ?? 0), height: Number(body.height ?? 0), mime, bytes: data ? Buffer.byteLength(data, 'base64') : 0 }
            if (data) {
              // the Live stage shows the person what the agent is looking at on that device
              cloud.stageFrame(Buffer.from(data, 'base64'), mime, { device: d.name, width: value.width, height: value.height, sessionId: exec.agent?.session.id ?? '' })
              const image = await admitImage(ctx, exec, data, mime, `${d.name} screen`)
              projections.set(exec, [...(image ? [image] : []), { type: 'text', text: image ? `Screenshot of ${d.name} (${value.width}×${value.height}).` : `Screenshot of ${d.name} taken (${value.width}×${value.height}), but the current model cannot look at images.` }])
            }
            return value
          },
          projectContent(exec, result) {
            const content = projections.get(exec)
            projections.delete(exec)
            return result.isError ? undefined : content
          },
          presentCall: (args) => ({ card: 'generic', title: `Screenshot of ${args.device || 'the other device'}`, kind: 'other', rawInput: args }),
        }),
      ),
    'nanomuse reach: device_screen',
  )

  // -- device_shell --------------------------------------------------------------------

  ctx.effect(
    () =>
      ctx.tools.register(
        defineTool({
          name: 'device_shell',
          description: "Run a shell command on another device of the person's (its sandbox on a phone, the real shell on a computer). The person approves it here first. Prefer reads and builds; never anything that deletes, sends or pays without being asked to.",
          parameters: {
            device: DEVICE,
            command: { type: 'string', required: true, description: 'The command line.' },
            cwd: { type: 'string', description: 'Working directory on that device.' },
            timeout: { type: 'integer', description: 'Seconds to wait; default 120.' },
          },
          output: {
            schema: {
              type: 'object',
              properties: { device: { type: 'string' }, exit_code: { type: 'integer' }, stdout: { type: 'string' }, stderr: { type: 'string' }, timed_out: { type: 'boolean' }, duration_ms: { type: 'integer' } },
              additionalProperties: false,
            },
            render: (_args, value) => {
              const parts = [`[${value.device}] exit ${value.exit_code}${value.timed_out ? ' (timed out)' : ''} in ${value.duration_ms} ms`]
              if (value.stdout) parts.push(value.stdout)
              if (value.stderr) parts.push(`stderr:\n${value.stderr}`)
              return [{ type: 'text', text: parts.join('\n') }]
            },
          },
          timeoutMs: 300_000,
          async execute(args, exec) {
            const d = target(args.device)
            await approve(exec, 'device_shell', `Run on ${d.name}: ${args.command}`, `在 ${d.name} 上运行：${args.command}`)
            const timeout = Math.min(Math.max(args.timeout ?? 120, 1), 240)
            const body = await hub
              .call(d.id, 'shell', { command: args.command, ...(args.cwd ? { cwd: args.cwd } : {}), timeout }, { signal: exec.signal, timeoutMs: (timeout + 30) * 1000 })
              .catch(fail)
            return {
              device: d.name,
              exit_code: Number(body.exit_code ?? 0),
              stdout: String(body.stdout ?? '').slice(0, 60_000),
              stderr: String(body.stderr ?? '').slice(0, 20_000),
              timed_out: Boolean(body.timed_out),
              duration_ms: Number(body.duration_ms ?? 0),
            }
          },
          presentCall: (args) => ({ card: 'terminal', title: `On ${args.device || 'the other device'}`, kind: 'execute', command: args.command, rawInput: args }),
        }),
      ),
    'nanomuse reach: device_shell',
  )

  // -- device_files --------------------------------------------------------------------

  ctx.effect(
    () =>
      ctx.tools.register(
        defineTool({
          name: 'device_files',
          description: "List a folder on another device (its home folder when no path is given). Read-only; the person is asked first.",
          parameters: { device: DEVICE, path: { type: 'string', description: 'Folder path on that device; ~ is its home.' } },
          output: {
            schema: {
              type: 'object',
              properties: { device: { type: 'string' }, path: { type: 'string' }, entries: { type: 'array', items: { type: 'json' } } },
              additionalProperties: false,
            },
            render: (_args, value) => {
              const entries = (value.entries ?? []) as { name?: string; type?: string; size?: number }[]
              const lines = entries.slice(0, 200).map((e) => `${e.type === 'dir' ? 'd ' : '  '}${e.name ?? ''}${e.type === 'dir' ? '/' : e.size !== undefined ? `  ${e.size}` : ''}`)
              return [{ type: 'text', text: `[${value.device}] ${value.path}\n${lines.join('\n') || '(empty)'}${entries.length > 200 ? `\n… ${entries.length - 200} more` : ''}` }]
            },
          },
          timeoutMs: 60_000,
          isConcurrencySafe: () => true,
          async execute(args, exec) {
            const d = target(args.device)
            // their folders are their private data: the person says yes before a listing leaves that device
            const where = args.path || '~'
            await approve(exec, 'device_files', `List ${where} on ${d.name}`, `列出 ${d.name} 上的 ${where}`)
            const body = await hub.call(d.id, 'files', args.path ? { path: args.path } : {}, { signal: exec.signal, timeoutMs: 45_000 }).catch(fail)
            return { device: d.name, path: String(body.path ?? args.path ?? '~'), entries: Array.isArray(body.entries) ? body.entries : [] }
          },
          presentCall: (args) => ({ card: 'generic', title: `Files on ${args.device || 'the other device'}`, kind: 'read', rawInput: args }),
        }),
      ),
    'nanomuse reach: device_files',
  )

  // -- device_open ---------------------------------------------------------------------

  ctx.effect(
    () =>
      ctx.tools.register(
        defineTool({
          name: 'device_open',
          description: 'Open a URL (or a file path on that device) on another device, in its default app or browser. The person approves it here first.',
          parameters: { device: DEVICE, url: { type: 'string', required: true, description: 'https://…, or a path on that device.' } },
          output: {
            schema: { type: 'object', properties: { device: { type: 'string' }, ok: { type: 'boolean' }, url: { type: 'string' } }, additionalProperties: false },
            render: (_args, value) => [{ type: 'text', text: value.ok ? `Opened on ${value.device}: ${value.url}` : `${value.device} could not open ${value.url}` }],
          },
          timeoutMs: 60_000,
          async execute(args, exec) {
            const d = target(args.device)
            await approve(exec, 'device_open', `Open on ${d.name}: ${args.url}`, `在 ${d.name} 上打开：${args.url}`)
            const body = await hub.call(d.id, 'open', { url: args.url }, { signal: exec.signal, timeoutMs: 30_000 }).catch(fail)
            return { device: d.name, ok: body.ok !== false, url: String(body.url ?? args.url) }
          },
          presentCall: (args) => ({ card: 'generic', title: `Open on ${args.device || 'the other device'}`, kind: 'other', rawInput: args }),
        }),
      ),
    'nanomuse reach: device_open',
  )

  // -- device_notify -------------------------------------------------------------------

  ctx.effect(
    () =>
      ctx.tools.register(
        defineTool({
          name: 'device_notify',
          description: 'Show a notification on another device (e.g. a reminder on the phone).',
          parameters: { device: DEVICE, text: { type: 'string', required: true }, title: { type: 'string' } },
          output: {
            schema: { type: 'object', properties: { device: { type: 'string' }, shown: { type: 'boolean' } }, additionalProperties: false },
            render: (_args, value) => [{ type: 'text', text: value.shown ? `Shown on ${value.device}.` : `${value.device} took it but may not have shown it.` }],
          },
          timeoutMs: 60_000,
          async execute(args, exec) {
            const d = target(args.device)
            const body = await hub.call(d.id, 'notify', { text: args.text, ...(args.title ? { title: args.title } : {}) }, { signal: exec.signal, timeoutMs: 30_000 }).catch(fail)
            return { device: d.name, shown: body.shown !== false }
          },
          presentCall: (args) => ({ card: 'generic', title: `Notify ${args.device || 'the other device'}`, kind: 'other', rawInput: args }),
        }),
      ),
    'nanomuse reach: device_notify',
  )

  // -- delegate ------------------------------------------------------------------------

  ctx.effect(
    () =>
      ctx.tools.register(
        defineTool({
          name: 'delegate',
          description:
            "Give another device's own Muse a whole job in words — e.g. on the phone: read the last notification, find an order number in an app, send a message with its Hands. It may take minutes; progress and any approval the phone asks for show here. Returns its answer.",
          parameters: { device: DEVICE, task: { type: 'string', required: true, description: 'The job, in plain words, with everything it needs to know.' } },
          output: {
            schema: {
              type: 'object',
              properties: { device: { type: 'string' }, answer: { type: 'string' }, steps: { type: 'array', items: { type: 'string' } } },
              additionalProperties: false,
            },
            render: (_args, value) => {
              const steps = (value.steps ?? []) as string[]
              return [{ type: 'text', text: `${value.device} answered:\n${value.answer}${steps.length ? `\n\n(steps: ${steps.join('; ')})` : ''}` }]
            },
          },
          timeoutMs: 660_000,
          async execute(args, exec) {
            const d = target(args.device)
            const steps: string[] = []
            const pending = new Set<Promise<void>>()
            const onEvent = (body: Record<string, unknown>) => {
              const stage = String(body.stage ?? '')
              if (stage === 'approval') {
                const approvalId = String(body.approval_id ?? '')
                const preview = String(body.preview ?? '')
                const p = approve(exec, 'delegate', `${d.name} asks: ${preview}`, `${d.name} 请求：${preview}`)
                  .then(() => true, () => false)
                  .then((allow) => hub.call(d.id, 'approve', { approval_id: approvalId, allow }, { timeoutMs: 30_000 }).then(() => undefined, () => undefined))
                pending.add(p)
                void p.finally(() => pending.delete(p))
              } else if (stage === 'tool') {
                steps.push(`${body.name ?? 'tool'}${body.summary ? `: ${String(body.summary).slice(0, 120)}` : ''}`)
              } else if (stage === 'text' && body.interim !== true && typeof body.text === 'string' && body.text) {
                steps.push(`said: ${body.text.slice(0, 160)}`)
              } else if (stage === 'error') {
                steps.push(`error: ${String(body.message ?? 'error').slice(0, 160)}`)
              }
            }
            // Stopping the turn here stops the job there too: the runtime's `stop {call}` ends
            // the thread it opened for this call (`docs/hub.md`), so its approval does not hang.
            const callId = hub.nextId()
            const onAbort = () =>
              void hub
                .call(d.id, 'stop', { call: callId }, { timeoutMs: 10_000 })
                .then((r) => ctx.logger.info('nanomuse reach: stop on %s: %s', d.name, r.stopped ? 'stopped' : 'nothing running'))
                .catch((e: unknown) => ctx.logger.warn('nanomuse reach: stop on %s failed: %s', d.name, e instanceof Error ? e.message : String(e)))
            exec.signal.addEventListener('abort', onAbort, { once: true })
            let body: Record<string, unknown>
            try {
              // `language` (runtime 1.0.0, `docs/hub.md`): the other end answers in this screen's language; an older runtime ignores the field
              body = await hub.call(d.id, 'task', { text: args.task, from: cloud.hub.devices.find((x) => x.id === hub.deviceId)?.name ?? 'computer', language: uiLanguage(ctx) }, { id: callId, signal: exec.signal, timeoutMs: 600_000, onEvent }).catch(fail)
            } finally {
              exec.signal.removeEventListener('abort', onAbort)
            }
            await Promise.allSettled([...pending])
            const answer = String(body.text ?? body.answer ?? '').trim() || '(no answer)'
            return { device: d.name, answer, steps: steps.slice(-12) }
          },
          presentCall: (args) => ({ card: 'generic', title: `Ask ${args.device || 'the other device'}`, kind: 'other', rawInput: args }),
        }),
      ),
    'nanomuse reach: delegate',
  )

  // -- who the agent is, and who is around ---------------------------------------------

  ctx.inject(['systemPrompt'], (ctx) => {
    ctx.effect(
      () =>
        ctx.systemPrompt.context({
          name: 'nanomuse-reach',
          order: 50,
          text: () => {
            const profile = cloud.profile.current()
            const lines = [`The person calls you ${profile.name}; answer to that name.`]
            if (profile.description) lines.push(`Your look, as the person drew it: ${profile.description.slice(0, 200)}.`)
            if (hub.connected) {
              const others = hub.devices.filter((d) => d.id !== hub.deviceId && d.kind !== 'web')
              lines.push(
                others.length
                  ? `The person's other devices on nanoMuse Cloud, reachable with the devices/device_*/delegate tools: ${others.map((d) => `${d.name} (${d.kind}, ${d.online ? 'online' : 'offline'})`).join('; ')}.`
                  : 'No other device of the person is signed in to nanoMuse Cloud right now.',
              )
            }
            return lines.join('\n')
          },
        }),
      'nanomuse reach: prompt context',
    )
  })
}

/** Save one screenshot as a durable image for the model, when the model can look at it. */
async function admitImage(ctx: Context, exec: ToolRunContext, base64: string, mime: string, name: string): Promise<ContentBlock | undefined> {
  const attachments = ctx.get('attachments')
  const llm = ctx.get('llm')
  if (!attachments || !llm || !IMAGE_TYPES.has(mime)) return undefined
  const routed = exec.agent?.session.requestHeader()?.config
  const provider = routed?.provider ?? exec.agent?.options.provider
  const model = routed?.model ?? exec.agent?.options.model
  if (!provider || !model) return undefined
  try {
    const info = await llm.resolveModelInfo(provider, model, exec.signal)
    if (!info.inputModalities?.includes('image')) return undefined
    const [ref] = await attachments.saveImages([{ data: new Uint8Array(Buffer.from(base64, 'base64')), mediaType: mime as ImageMediaType, name }])
    return ref ? { type: 'image', attachment: ref } : undefined
  } catch {
    return undefined
  }
}

/** The BCP-47 tag of this computer's screens: what the client last said (`navigator.language`), else the process locale. */
export function uiLanguage(ctx: Context): string {
  const said = (ctx.get('nanomuseRooms') as { lang?: string } | undefined)?.lang
  return said || Intl.DateTimeFormat().resolvedOptions().locale || 'en'
}
