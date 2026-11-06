/**
 * A loopback door to the relay's `/v1` for the harness's model adapter (relay 0.31).
 *
 * The adapter sends a provider's headers as they are written in its row, the same on every
 * request, and a call's provenance — the run, the turn, the step, the hands' trajectory —
 * changes with every call (docs/cloud.md "Provenance"). So the `nanomuse` provider row
 * points here, `http://127.0.0.1:<port>/v1`, and each request is sent on to the relay with
 * the headers the `llm/stream` hook announced for it (`Provenance.expect` / `claim`), the
 * device and the platform always, and the account's key as the adapter sent it. The reply
 * streams back byte for byte — the relay's queue notices, its SSE comment lines, its
 * refusals with their status and body — and the id the relay gave the turn
 * (`x-nanomuse-request`) is kept for the session.
 *
 * Nothing new can be done through this door: a request is forwarded only when it carries
 * the account's own key, which the adapter resolves from the credential store and no page
 * or other process on the computer can read; anything else is a 401 here, as it would be
 * at the relay. No deadline of its own: a turn is as long as the relay lets it be; a client
 * that goes away takes the upstream request with it.
 */

import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import type { AddressInfo } from 'node:net'
import { Readable } from 'node:stream'
import { timingSafeEqual } from 'node:crypto'
import { PLATFORM } from './provenance.ts'

/** Headers of the adapter's request that travel on; the rest (host, connection, length) are the hop's own. */
const FORWARDED = ['content-type', 'accept', 'accept-language', 'user-agent', 'x-stainless-retry-count', 'x-stainless-timeout']
/** Headers of the relay's reply that travel back; `content-encoding` does not, fetch undid it already. */
const RETURNED = ['content-type', 'cache-control', 'x-nanomuse-request', 'x-request-id', 'retry-after']
/** A request body past this is refused here, before the relay would (its cap is 16 MB). */
export const MAX_BODY = 24 * 1024 * 1024

export interface RelayProxyOptions {
  /** The relay's origin, `https://cloud.nanomuse.cn`. */
  origin: () => string
  /** The account's key right now; '' when signed out (every request is then a 401). */
  token: () => Promise<string | undefined>
  /** This computer's device id, `X-NanoMuse-Device`. */
  device: () => string
  /** The announced call this request is, with its headers; nothing when none matches. */
  claim: (body: unknown) => { sessionId: string; headers: Record<string, string> } | undefined
  /** The relay named the turn it kept for the session (`x-nanomuse-request`). */
  noteTurn?: (sessionId: string, requestId: string) => void
  fetchImpl?: typeof fetch
  log?: (level: 'info' | 'warn', text: string) => void
}

export class RelayProxy {
  private server: Server | undefined
  port = 0
  /** Requests forwarded since the start; the tests and the log read it. */
  forwarded = 0

  constructor(private readonly options: RelayProxyOptions) {}

  /** The OpenAI-compatible root the provider row is pointed at; '' before `listen`. */
  get openaiBase(): string {
    return this.port ? `http://127.0.0.1:${this.port}/v1` : ''
  }

  /**
   * Open the door — on `preferred` when that port is free (the one the last start had, so the
   * provider row written then still points here and nothing has to be rewritten), else on a
   * port of the system's choosing.
   */
  async listen(preferred = 0): Promise<void> {
    if (this.server) return
    const server = createServer((req, res) =>
      void this.handle(req, res).catch((error: unknown) => {
        this.options.log?.('warn', `nanomuse relay door: ${error instanceof Error ? error.message : String(error)}`)
        if (!res.headersSent) res.writeHead(502, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ error: { code: 'offline', message: error instanceof Error ? error.message : String(error) } }))
      }),
    )
    // a streamed turn can be quiet for minutes while the model thinks; the socket is not to be closed for it
    server.requestTimeout = 0
    server.headersTimeout = 60_000
    server.keepAliveTimeout = 65_000
    const bind = (port: number): Promise<void> =>
      new Promise<void>((resolve, reject) => {
        server.once('error', reject)
        server.listen(port, '127.0.0.1', () => {
          server.off('error', reject)
          resolve()
        })
      })
    try {
      await bind(Number.isInteger(preferred) && preferred > 0 && preferred < 65536 ? preferred : 0)
    } catch (error) {
      if (!preferred) throw error
      this.options.log?.('info', `nanomuse relay door: port ${preferred} is taken (${error instanceof Error ? error.message : String(error)}); another is used`)
      await bind(0)
    }
    // the door is a side of the plugin, not a reason for the process to stay up
    server.unref()
    this.server = server
    this.port = (server.address() as AddressInfo).port
  }

  async close(): Promise<void> {
    const server = this.server
    this.server = undefined
    this.port = 0
    if (!server) return
    await new Promise<void>((resolve) => {
      server.close(() => resolve())
      server.closeAllConnections?.()
    })
  }

  private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1')
    if (!url.pathname.startsWith('/v1/')) {
      res.writeHead(404, { 'content-type': 'text/plain' }).end('nanoMuse')
      return
    }
    const token = (await this.options.token()) ?? ''
    const given = /^Bearer\s+(.+)$/i.exec(String(req.headers.authorization ?? ''))?.[1]?.trim() ?? ''
    if (!token || given.length !== token.length || !timingSafeEqual(Buffer.from(given), Buffer.from(token))) {
      res.writeHead(401, { 'content-type': 'application/json' }).end(JSON.stringify({ error: { code: 'bad_key', message: 'Not this account.' } }))
      return
    }
    const method = req.method ?? 'GET'
    let body: Buffer | undefined
    if (method !== 'GET' && method !== 'HEAD') {
      const chunks: Buffer[] = []
      let size = 0
      for await (const chunk of req) {
        size += (chunk as Buffer).length
        if (size > MAX_BODY) {
          res.writeHead(413, { 'content-type': 'application/json' }).end(JSON.stringify({ error: { code: 'too_large', message: 'The request is too large.' } }))
          return
        }
        chunks.push(chunk as Buffer)
      }
      body = Buffer.concat(chunks)
    }
    const headers: Record<string, string> = {}
    for (const name of FORWARDED) {
      const value = req.headers[name]
      if (typeof value === 'string') headers[name] = value
    }
    headers.authorization = `Bearer ${token}`
    // the device and the platform on every request; the call's provenance when the hook announced it
    const device = this.options.device()
    if (device) headers['x-nanomuse-device'] = device
    headers['x-nanomuse-platform'] = PLATFORM
    let sessionId = ''
    if (body && url.pathname === '/v1/chat/completions') {
      let parsed: unknown
      try {
        parsed = JSON.parse(body.toString('utf8'))
      } catch {
        parsed = undefined
      }
      const claimed = this.options.claim(parsed)
      if (claimed) {
        sessionId = claimed.sessionId
        Object.assign(headers, claimed.headers)
      }
    }
    const controller = new AbortController()
    res.on('close', () => controller.abort())
    const fetchImpl = this.options.fetchImpl ?? fetch
    const upstream = await fetchImpl(`${this.options.origin()}${url.pathname}${url.search}`, {
      method,
      headers,
      ...(body ? { body: new Uint8Array(body) } : {}),
      redirect: 'manual',
      signal: controller.signal,
    })
    this.forwarded += 1
    const requestId = upstream.headers.get('x-nanomuse-request')
    if (requestId && sessionId) this.options.noteTurn?.(sessionId, requestId)
    const out: Record<string, string> = {}
    for (const name of RETURNED) {
      const value = upstream.headers.get(name)
      if (value) out[name] = value
    }
    res.writeHead(upstream.status, out)
    if (!upstream.body || method === 'HEAD') {
      res.end()
      return
    }
    res.flushHeaders()
    const stream = Readable.fromWeb(upstream.body as import('node:stream/web').ReadableStream)
    stream.on('error', () => res.destroy())
    res.on('close', () => stream.destroy())
    stream.pipe(res)
  }
}
