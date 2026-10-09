/**
 * A failed turn as a card, not a line of wire (C12). The harness draws a `turn-error` node
 * under a turn the model did not finish: "This turn failed", the adapter's message, the code.
 * For the account's model that message was the relay's reply verbatim — `429: {"message":…,
 * "code":"allowance_exhausted",…}` — where the phones show a card with the ways on. The
 * host already read the reply (`src/refusals.ts`, on the `llm/stream` waterfall) and left our
 * code in the node, `nanomuse/<kind>`; this seat shadows the harness's and draws the card:
 *
 * - `exhausted`: the allowance card (`AllowanceWays`), with the figures from `/me`, and *Try again*;
 *   `allowance_paused` (relay 0.22) the same card, saying the allowance is paused, not spent;
 * - `too_large`: one sentence and *New chat*; `content_rejected`: one sentence, *New chat* and *Try again*;
 * - `signed_out`: one sentence and *Sign in*; the others one sentence and *Try again*.
 *
 * Any other failure — an own key the provider refused, a model that timed out — gets a plain
 * sentence by the harness's routing code, with what came back folded under it, and, signed
 * in, *Use nanoMuse Cloud this time* (0.1.41): that one turn again through the account, the
 * chat slot untouched (`POST /retry-cloud`, then the same resend). Nothing falls back by itself.
 */
import { createElement as h, Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { providerFailureKind, refusalCard, refusalKindOf, type RefusalKind } from '../refusals.ts'
import { type AccountSheet } from './AccountPage.tsx'
import { allowanceInfo, AllowanceWays } from './AllowanceWays.tsx'
import { call, muted, row, type Translate, failureText } from './api.ts'
import { settingsBus } from './bus.ts'
import { focusComposer } from './composer.ts'
import { IconRefresh } from './icons.tsx'
import { useLive } from './live.ts'
import { ACCOUNT_SECTION, MODELS_SECTION } from './OwnKey.tsx'

/** The node the harness hands the seat: the failure's words and code, the turn it ended. */
export interface TurnErrorNode {
  kind: string
  key?: string
  seq?: number
  data: { message?: string; code?: string; turn?: number }
}

export interface RefusalDeps {
  /** Send the words of the turn that failed again, in the same session. */
  retry(sessionId: string, text: string): Promise<void>
  /** A fresh chat. */
  newChat(): void
}

/** The sentence for a relay refusal of a kind, in the person's language. */
export function refusalText(t: Translate, kind: RefusalKind, message: string, retryAfterMs?: number): string {
  switch (kind) {
    case 'exhausted':
      return t('awExhausted')
    case 'allowance_paused':
      return t('rfAllowancePaused')
    case 'too_large':
      return t('rfTooLarge')
    case 'content_rejected':
      return t('rfContentRejected')
    case 'signed_out':
      return t('rfSignedOut')
    case 'disabled':
      return t('rfDisabled')
    case 'daily_cap':
      return t('rfDailyCap')
    case 'busy':
      return retryAfterMs && retryAfterMs > 1000 ? t('rfBusyIn', { seconds: Math.ceil(retryAfterMs / 1000) }) : t('rfBusy')
    case 'model':
      return t('rfModel')
    case 'relay_down':
      return t('rfRelayDown')
    case 'unreachable':
      return t('rfUnreachable')
    case 'service_paused':
      return t('rfServicePaused')
    case 'sync_paused':
      return t('rfSyncPaused')
    case 'hub_paused':
      return t('rfHubPaused')
    case 'cloud_off':
      return t('rfCloudOff')
    case 'other':
      return message || t('rfOther')
  }
}

/** The sentence for any other provider's failure, by the harness's routing code. */
export function providerFailureText(t: Translate, code: string | undefined, message: string): string {
  switch (providerFailureKind(code, message)) {
    case 'auth':
      return t('rfGenAuth')
    case 'quota':
      return t('rfGenQuota')
    case 'too_large':
      return t('rfGenTooLarge')
    case 'content_rejected':
      return t('rfGenContentRejected')
    case 'busy':
      return t('rfGenBusy')
    case 'server':
      return t('rfGenServer')
    case 'unreachable':
      return t('rfGenUnreachable')
    case 'other':
      return t('rfGenOther')
  }
}

/** The words of the person's turn that failed: the user bubble of that turn, read off the chat. */
export function turnText(from: HTMLElement | null, turn: number | undefined): string {
  const column = from?.closest('[data-chat-flow-key]')?.parentElement ?? document
  if (turn !== undefined) {
    const same = column.querySelector<HTMLElement>(`[data-chat-flow-kind="user"][data-chat-turn="${turn}"]`)
    if (same?.textContent?.trim()) return same.textContent.trim()
  }
  // older harness: the last user bubble above the error
  let node: Element | null = from?.closest('[data-chat-flow-key]') ?? null
  while (node) {
    node = node.previousElementSibling
    if (node instanceof HTMLElement && node.dataset['chatFlowKind'] === 'user' && node.textContent?.trim()) return node.textContent.trim()
  }
  return ''
}

/** The seat for `conversation.chat.node` key `turn-error`, in place of the harness's. */
export function makeTurnError(t: Translate, deps: RefusalDeps) {
  return function TurnError({ node, sessionId }: { node: TurnErrorNode; sessionId?: string }): ReactNode {
    const data = node.data ?? {}
    const code = data.code ?? ''
    const message = data.message ?? ''
    const kind = refusalKindOf(code)
    const ref = useRef<HTMLDivElement>(null)
    const [busy, setBusy] = useState(false)
    const [cloudError, setCloudError] = useState<string | undefined>()
    const signedIn = useLive().cloud.signedIn
    const retry = () => {
      const text = turnText(ref.current, data.turn)
      if (!sessionId || !text) {
        focusComposer()
        return
      }
      setBusy(true)
      void deps.retry(sessionId, text).catch(() => focusComposer()).finally(() => setBusy(false))
    }
    // this one turn through the account: the host switches the session for a turn and puts it back when the turn ends
    const retryOnCloud = () => {
      const text = turnText(ref.current, data.turn)
      if (!sessionId || !text) {
        focusComposer()
        return
      }
      setBusy(true)
      setCloudError(undefined)
      void call('retry-cloud', { sessionId })
        .then(() => deps.retry(sessionId, text))
        .catch((err: unknown) => setCloudError(failureText(t, err)))
        .finally(() => setBusy(false))
    }
    const openSettings = () => { settingsBus.openSection?.(ACCOUNT_SECTION) }
    const button = (label: string, onClick: () => void, primary = false, icon?: ReactNode) =>
      h('button', { type: 'button', className: `nm-pill nm-pill-sm${primary ? '' : ' nm-pill-ghost'}`, disabled: busy, onClick }, icon ?? null, label)
    const actionsOf = (actions: ReturnType<typeof refusalCard>['actions']): ReactNode[] =>
      actions.map((a) => {
        switch (a) {
          case 'ways':
            return null // the card itself
          case 'retry':
            return button(t('rfRetry'), retry, false, h(IconRefresh, { size: 14 }))
          case 'new-chat':
            return button(t('rfNewChat'), () => deps.newChat(), true)
          case 'sign-in':
            return button(t('rfSignIn'), openSettings, true)
          case 'settings':
            return button(t('rfSettings'), openSettings)
          case 'models':
            return button(t('rfModels'), () => { settingsBus.openSection?.(MODELS_SECTION) })
          case 'cloud-once':
            return sessionId ? h('button', { type: 'button', className: 'nm-pill nm-pill-sm', 'data-testid': 'nm-rf-cloud-once', disabled: busy, onClick: retryOnCloud }, t('rfUseCloudOnce')) : null
        }
      })

    if (kind === 'exhausted' || kind === 'allowance_paused') {
      return h('div', { ref, className: 'nm-refusal nm-card', role: 'note', 'data-testid': 'nm-refusal', 'data-kind': kind },
        h(ExhaustedBody, { t, paused: kind === 'allowance_paused' }),
        h('div', { className: 'nm-refusal-actions', style: row }, actionsOf(refusalCard(kind).actions)))
    }
    if (kind) {
      const plan = refusalCard(kind)
      return h('div', { ref, className: 'nm-refusal nm-card', role: 'note', 'data-testid': 'nm-refusal', 'data-kind': kind },
        h('div', { className: 'nm-refusal-text' }, refusalText(t, kind, message)),
        plan.showRelayText && message && kind !== 'other' ? h('div', { className: 'nm-refusal-sub', style: muted }, t('rfRelaySaid', { message })) : null,
        cloudError ? h('div', { className: 'nm-refusal-sub', style: muted }, cloudError) : null,
        h('div', { className: 'nm-refusal-actions', style: row }, actionsOf(plan.actions)))
    }
    // not the relay: an own key's provider, a local model, the harness itself
    const generic = providerFailureKind(code, message)
    return h('div', { ref, className: 'nm-refusal nm-card', role: 'note', 'data-testid': 'nm-refusal', 'data-kind': `provider-${generic}` },
      h('div', { className: 'nm-refusal-text' }, providerFailureText(t, code, message)),
      message ? h('details', { className: 'nm-refusal-details' }, h('summary', { style: muted }, t('rfDetails')), h('pre', null, message, code ? `\n${code}` : '')) : null,
      cloudError ? h('div', { className: 'nm-refusal-sub', style: muted }, cloudError) : null,
      h('div', { className: 'nm-refusal-actions', style: row },
        button(t('rfRetry'), retry, false, h(IconRefresh, { size: 14 })),
        signedIn && sessionId ? h('button', { type: 'button', className: 'nm-pill nm-pill-sm nm-pill-ghost', 'data-testid': 'nm-rf-cloud-once', disabled: busy, onClick: retryOnCloud }, t('rfUseCloudOnce')) : null,
        generic === 'too_large' || generic === 'content_rejected' ? button(t('rfNewChat'), () => deps.newChat()) : null,
        generic === 'auth' || generic === 'quota' ? button(t('rfSettings'), openSettings) : null))
  }
}

/** The allowance card in the chat: the figures from `/me` (the host re-read the account on the refusal), then the ways on. */
function ExhaustedBody({ t, paused }: { t: Translate; paused: boolean }): ReactNode {
  const [sheet, setSheet] = useState<AccountSheet | undefined>()
  useEffect(() => {
    let alive = true
    call<AccountSheet>('me').then((me) => { if (alive) setSheet(me) }).catch(() => undefined)
    return () => { alive = false }
  }, [])
  return h(Fragment, null, h(AllowanceWays, { t, info: allowanceInfo(sheet), exhausted: true, ...(paused ? { lead: t('rfAllowancePaused') } : {}), ...(sheet ? { sheet } : {}) }))
}
