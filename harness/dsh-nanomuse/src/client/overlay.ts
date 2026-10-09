/**
 * What the Electron shell draws outside this window while the hands work — the phone's
 * two pieces (harness/desktop/src/main.ts, `registerOverlays`): the glow breathing along
 * the screen's edges with the marker where the hands act, and the capsule at the top of
 * the screen with the face, the step and what is being done, *Stop* and *I'll take it*,
 * which grows into the question the agent asked or the hold. This side reads the host's
 * live state and sends the shell only what it needs — fractions of the screen for the
 * pointer, words for the capsule — and turns the capsule's answers into the same calls
 * the chat makes. Content protection on this window follows the hands too.
 *
 * Both pieces stay up for the whole run: from the first `computer_*` call of a turn to the
 * turn's end (`live.hands.run`, the host's word), not only while a call is in flight. Between
 * two steps the model thinks for seconds, and the glow and the capsule used to go dark for
 * each of those gaps (1.0.0). While it thinks the capsule says what the hands last did.
 */
import { call, type Translate } from './api.ts'
import { stillUrl } from './Avatar.tsx'
import { bridge } from './bridge.ts'
import { subscribeLive, type Live } from './live.ts'
import { describeStep, POINTED } from './steps.ts'

export interface OverlayOptions {
  t: Translate
  /** Stop: the session's turn is cancelled. */
  stop(sessionId: string): Promise<void>
}

export function syncOverlay({ t, stop }: OverlayOptions): () => void {
  const b = bridge()
  if (!b?.setOverlay) return () => undefined
  let lastKey = ''
  let protectedOn = false
  let sessionId = ''
  const push = (live: Live) => {
    const calls = live.hands.calls
    const busy = calls.length > 0
    // the hands have this screen: the host's run, or (an older host) a `computer_*` call in flight
    const run = live.hands.run ?? null
    const onScreen = Boolean(run) || calls.some((c) => c.name.startsWith('mcp__nanomuse__computer_'))
    const stage = live.stage
    const hold = live.holds[0]
    const action = stage.action
    const pointed = action && action.x >= 0 && action.y >= 0 && stage.width > 0 && stage.height > 0 && (POINTED.has(action.kind) || action.kind === 'type')
    sessionId = run?.sessionId || stage.sessionId || calls[0]?.sessionId || ''
    const hands = onScreen || busy || hold
      ? {
          active: onScreen,
          held: Boolean(hold),
          x: pointed ? Math.min(1, Math.max(0, action.x / stage.width)) : -1,
          y: pointed ? Math.min(1, Math.max(0, action.y / stage.height)) : -1,
          kind: action?.kind ?? '',
          step: live.hands.steps,
          title: hold ? t('stageYourTurn') : t('capsuleStepTitle', { n: live.hands.steps }),
          // what is being done while a call runs; what was just done while the model thinks
          text: hold ? hold.reason : action ? describeStep(t, action, busy) : t('stageLooking'),
          face: new URL(stillUrl(live.profile, hold ? 'waiting' : 'working'), document.baseURI).href,
          stop: (onScreen || busy) && sessionId ? t('capsuleStop') : '',
          take: onScreen && !hold && sessionId ? t('stageTakeIt') : '',
        }
      : null
    const zh = t('langTag') === 'zh'
    const cards = [
      ...live.holds.map((h) => ({ id: `hold:${h.id}`, kind: 'hold' as const, title: t('stageYourTurn'), text: h.reason || t('stageYourTurnDetail'), actions: [{ id: 'done', label: t('stageDoneBtn'), tone: 'on' as const }] })),
      ...live.approvals.map((a) => ({ id: `ap:${a.id}`, kind: 'approval' as const, title: t('statusNeedsApproval'), text: (zh && a.summaryZh) || a.summary || a.purpose || a.toolName, actions: [{ id: 'allow', label: t('stageAllowOnce'), tone: 'on' as const }, { id: 'deny', label: t('stageDeny'), tone: 'no' as const }] })),
    ]
    const key = JSON.stringify({ hands, cards })
    if (key === lastKey) return
    lastKey = key
    b.setOverlay?.({ hands, cards })
    const wantProtected = Boolean(hands?.active)
    if (wantProtected !== protectedOn) {
      protectedOn = wantProtected
      void b.setContentProtection?.(wantProtected)
    }
  }
  const offLive = subscribeLive(push)
  const offAct = b.onOverlayAction?.((card, action) => {
    if (card.startsWith('hold:') && action === 'done') void call(`holds/${encodeURIComponent(card.slice(5))}/done`, {}).catch(() => undefined)
    else if (card.startsWith('ap:')) void call(`approvals/${encodeURIComponent(card.slice(3))}`, { approved: action === 'allow', scope: 'once', reason: '' }).catch(() => undefined)
    else if (card === 'hands' && action === 'stop' && sessionId) void stop(sessionId).catch(() => undefined)
    // "I'll take it": a hold (C1) — the hands wait for Done rather than stop
    else if (card === 'hands' && action === 'take' && sessionId) void call('holds', { thread: sessionId, tool: 'computer', reason: '' }).catch(() => undefined)
  })
  return () => {
    offLive()
    offAct?.()
    b.setOverlay?.({ hands: null, cards: [] })
    if (protectedOn) void b.setContentProtection?.(false)
  }
}
