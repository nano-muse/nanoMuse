/**
 * The first run and the first conversation, the way the phone does them (C4), as
 * pure shapes and decisions. No Cordis, no files: `rooms.ts` keeps the state in
 * `$DSH_HOME/nanomuse/firstrun.json`, serves it under `/nanomuse/rooms/firstrun/*`
 * and calls into here; the browser half imports the same module for the copy the
 * app speaks on its own behalf, so both halves agree on every word.
 *
 * The setup pages (Welcome → Password → Which model answers → Choose models →
 * Permissions → Meet <name>) end with Start, which binds the main chat as the
 * first conversation. There the app speaks first — three scripted lines, zero
 * tokens, never in the model's history — and asks what to call the person. From
 * then on the model does the talking and reports what happened in a small
 * `nanomuse-naming` block at the end of its reply; the phase moves on that block
 * and on nothing else. A reply without one means the person talked about
 * something else, the model helped and steered back, and the phase stays.
 */
import { FENCE_NAMING, parseNamingBlock } from './fences.ts'

// ---- the phases ----------------------------------------------------------------------

export type Phase = 'none' | 'ask_user_name' | 'ask_agent_name' | 'named' | 'done'

export const PHASES: readonly Phase[] = ['none', 'ask_user_name', 'ask_agent_name', 'named', 'done']

/** Everything the first run remembers; one JSON file on the host, mirrored to the browser. */
export interface FirstRunState {
  version: 1
  /** Start was pressed: the setup pages are over for this install. */
  done: boolean
  /** The permissions page was shown (or skipped as not needed) once. */
  permissionsSeen: boolean
  /** Which model answers: the cloud account, or the person's own key; null until chosen. */
  sourceChosen: 'cloud' | 'own' | null
  /** The first conversation. */
  phase: Phase
  /** The session the first conversation is bound to; null until Start. */
  sessionId: string | null
  /** How the person asked to be addressed, when they said. */
  userAddress: string | null
  /** The model's name suggestions for itself, when it gave some. */
  suggestions: string[]
  /** The name the agent got in the first conversation, when it did. */
  chosen: string | null
  startedAt: number
  finishedAt: number
}

export const FIRST_RUN_EMPTY: FirstRunState = {
  version: 1,
  done: false,
  permissionsSeen: false,
  sourceChosen: null,
  phase: 'none',
  sessionId: null,
  userAddress: null,
  suggestions: [],
  chosen: null,
  startedAt: 0,
  finishedAt: 0,
}

/** A tolerant read of the file (or of an older shape): what is missing takes the empty value. */
export function readFirstRun(raw: unknown): FirstRunState {
  if (!raw || typeof raw !== 'object') return { ...FIRST_RUN_EMPTY, suggestions: [] }
  const r = raw as Record<string, unknown>
  const phase = typeof r.phase === 'string' && (PHASES as readonly string[]).includes(r.phase) ? (r.phase as Phase) : 'none'
  return {
    version: 1,
    done: r.done === true,
    permissionsSeen: r.permissionsSeen === true,
    sourceChosen: r.sourceChosen === 'cloud' || r.sourceChosen === 'own' ? r.sourceChosen : null,
    phase,
    sessionId: typeof r.sessionId === 'string' && r.sessionId ? r.sessionId : null,
    userAddress: typeof r.userAddress === 'string' && r.userAddress ? r.userAddress : null,
    suggestions: Array.isArray(r.suggestions) ? r.suggestions.filter((s): s is string => typeof s === 'string' && s.trim() !== '').slice(0, 3) : [],
    chosen: typeof r.chosen === 'string' && r.chosen ? r.chosen : null,
    startedAt: typeof r.startedAt === 'number' ? r.startedAt : 0,
    finishedAt: typeof r.finishedAt === 'number' ? r.finishedAt : 0,
  }
}

// ---- when the setup pages are due ----------------------------------------------------

export interface NeededInput {
  /** The cloud account is signed in. */
  signedIn: boolean
  /** A model can answer: the account's, or the person's own key configured in the harness. */
  hasModel: boolean
  /** Some chat already has messages (a side chat, a run, an older install). */
  hasSessions: boolean
  /** Start was pressed once. */
  done: boolean
}

/**
 * The phone's rule, word for word: `!signedIn || !hasProviders || (!hasSessions && !done)`.
 * A desktop with its own key and no account passes `signedIn` as "a model is ready" too —
 * being ready only skips the sign-in, source and models pages; the Welcome, Permissions and
 * Meet pages still show on a fresh install.
 */
export function firstRunNeeded(input: NeededInput): boolean {
  return !input.signedIn || !input.hasModel || (!input.hasSessions && !input.done)
}

export type Stage = 'welcome' | 'password' | 'source' | 'models' | 'permissions' | 'meet'

export interface StageInput {
  signedIn: boolean
  /** A model can answer (the account's, or a key of the person's own in the harness). */
  hasModel: boolean
  /** The account was created in this sign-in (the relay's `created`) and has no password yet. */
  freshAccount: boolean
  /** The password page was answered or skipped. */
  passwordSeen: boolean
  sourceChosen: 'cloud' | 'own' | null
  /** "Skip for now" on the models page, this run. */
  modelsSkipped: boolean
  /** The system gates permissions here (macOS). */
  gated: boolean
  permissionsSeen: boolean
}

/**
 * The page to show, in the phone's order: Welcome until the account (or, on a desktop, a
 * model of one's own) is there; a password for a fresh account; which model answers; the
 * models page for one's own key until one is configured or skipped; the permissions where
 * the system gates them; then Meet. Welcome's second door ("Use your own API key instead",
 * as on the phone) leads to the models page with no account; Skip there, with no key saved,
 * is Welcome again.
 */
export function stageOf(s: StageInput): Stage {
  if (!s.signedIn && !s.hasModel) return s.sourceChosen === 'own' && !s.modelsSkipped ? 'models' : 'welcome'
  if (s.signedIn && s.freshAccount && !s.passwordSeen) return 'password'
  if (s.sourceChosen === null) return 'source'
  if (s.sourceChosen === 'own' && !s.hasModel && !s.modelsSkipped) return 'models'
  if (s.gated && !s.permissionsSeen) return 'permissions'
  return 'meet'
}

/** Which of the three dots is lit for a page: the account pages share the first. */
export function dotOf(stage: Stage): number {
  return stage === 'permissions' ? 1 : stage === 'meet' ? 2 : 0
}

// ---- the opening the app speaks on its own behalf ------------------------------------

export function isZh(lang: string): boolean {
  return lang.toLowerCase().startsWith('zh')
}

/** The three opening paragraphs, in the person's language; the phone's words, with the computer in the phone's place. */
export function introLines(lang: string): [string, string, string] {
  if (isZh(lang)) {
    return [
      '你好，我是 nanoMuse，住在你电脑里的私人助理。让我替你分担几件事。',
      '先说说我怎么工作：\n\n- 我就在这台电脑上工作，能跑命令、打开网页、填表单。\n- 你指给我的文件和文件夹，我能读、能整理；提醒和定时任务也可以交给我。\n- 关键的一步之前，我会先问你。\n- 一切都在这台电脑上跑，对话只发给你自己配置的模型。',
      '开始之前，我该怎么称呼你？',
    ]
  }
  return [
    "Hi, I'm nanoMuse, the assistant that lives on your computer. Let me take a few things off your plate.",
    'A bit about how I work:\n\n- I work on this computer: I can run commands, open websites and fill in forms.\n- I can read and organise the files and folders you point me to, and take care of reminders and scheduled tasks.\n- Before any step that matters, I ask you first.\n- Everything runs on this computer; your messages go only to the model you configured.',
    'Before we start, what should I call you?',
  ]
}

// ---- name suggestions ----------------------------------------------------------------

export const NAME_POOL_EN = ['Pip', 'Wren', 'Juno', 'Remy', 'Tilly', 'Milo', 'Sol', 'Fig'] as const
export const NAME_POOL_ZH = ['豆丁', '小满', '团团', '叮叮', '小北', '一一', '小竹', '阿岳'] as const

/** Java's `String.hashCode`, so a seed shuffles the same way it does on the phone. */
export function hashCode(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0
  return h
}

/** Two names from the pool, shuffled by the session id so the same chat always offers the same two. */
export function builtInSuggestions(seed: string, lang: string): string[] {
  const pool = [...(isZh(lang) ? NAME_POOL_ZH : NAME_POOL_EN)]
  let x = (hashCode(seed) >>> 0) || 0x9e3779b9
  const next = () => {
    // xorshift32: small, deterministic, good enough to deal two names
    x ^= x << 13; x >>>= 0
    x ^= x >>> 17
    x ^= x << 5; x >>>= 0
    return x / 0x100000000
  }
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(next() * (i + 1))
    const a = pool[i]!
    pool[i] = pool[j]!
    pool[j] = a
  }
  return pool.slice(0, 2)
}

/** The model's suggestions when it gave some; otherwise two from the pool. */
export function currentSuggestions(state: FirstRunState, lang: string): string[] {
  if (state.suggestions.length) return state.suggestions
  return builtInSuggestions(state.sessionId ?? '', lang)
}

// ---- the phase machine ---------------------------------------------------------------

/** Bind the first conversation to `sessionId` and step into the opening when this is the start. */
export function startConversation(state: FirstRunState, sessionId: string, now = Date.now()): FirstRunState {
  const next: FirstRunState = { ...state, sessionId, done: true, finishedAt: state.finishedAt || now }
  if (next.phase === 'none') { next.phase = 'ask_user_name'; next.startedAt = now }
  return next
}

export interface TurnOutcome {
  state: FirstRunState
  /** The chooser belongs under this reply. */
  showCard: boolean
  /** The person said how to address them (null: they would rather not be addressed by anything). */
  addressGiven?: string | null
  /** The agent got its name in this turn. */
  named?: string
}

/**
 * The model's reply finished. Reads its `nanomuse-naming` block, if any, and moves the
 * phase; a reply without one leaves the phase where it is.
 */
export function afterTurn(state: FirstRunState, assistantText: string | null | undefined): TurnOutcome {
  const block = parseNamingBlock(assistantText)
  switch (state.phase) {
    case 'ask_user_name': {
      if (!block || !block.addressGiven) return { state, showCard: false }
      const next: FirstRunState = {
        ...state,
        phase: 'ask_agent_name',
        userAddress: block.userAddress ?? state.userAddress,
        suggestions: block.suggestions.length ? block.suggestions : state.suggestions,
      }
      return { state: next, showCard: true, addressGiven: block.userAddress }
    }
    case 'ask_agent_name': {
      const name = block?.agentName ?? null
      if (name) {
        // the model already replied as itself in this turn, so the ritual is over
        return { state: { ...state, phase: 'done', chosen: name }, showCard: false, named: name }
      }
      return { state, showCard: true }
    }
    case 'named':
      return { state: { ...state, phase: 'done' }, showCard: false }
    default:
      return { state, showCard: false }
  }
}

/** A chip was picked: the name is saved at once; the model's next reply is its first as itself. Null when no pick is due. */
export function pickName(state: FirstRunState, name: string): FirstRunState | null {
  if (state.phase !== 'ask_agent_name') return null
  return { ...state, phase: 'named', chosen: name }
}

/** The person moved on to something the app handles itself: the chooser goes, the ritual is over. */
export function dismissChooser(state: FirstRunState): FirstRunState {
  return state.phase === 'ask_agent_name' ? { ...state, phase: 'done' } : state
}

/** The first conversation is bound to this session and still running. */
export function boundTo(state: FirstRunState, sessionId: string | null): boolean {
  return sessionId !== null && state.sessionId === sessionId && state.phase !== 'none'
}

/** The intro and the card belong in `sessionId`'s transcript: it started there, or it is still there. */
export function showsIntro(state: FirstRunState, sessionId: string | null): boolean {
  return boundTo(state, sessionId)
}

/** The ritual counts as over for the purposes of the feed's first day and the star counter. */
export function conversationOver(state: FirstRunState): boolean {
  return state.phase === 'done'
}

// ---- what the model is told ----------------------------------------------------------

const TAKEN_NAMES = 'Siri, Alexa, Cortana, Jarvis, Muse, Gemini, Copilot, 小爱, 小度, 小艺, 天猫精灵, 豆包, 文心, 通义, 阿福'

const CAN_DO = 'running commands on this computer, opening websites and filling in forms, reading and organising the files and folders they point you to, setting reminders and scheduled tasks, searching the web'

/** The system-prompt addendum for the current phase; null once it is over. `agentName` is the name on file now. */
export function promptAddendum(state: FirstRunState, lang: string, agentName: string): string | null {
  const addressLine = state.userAddress ? ` The user goes by "${state.userAddress}" — address them that way.` : ''
  switch (state.phase) {
    case 'ask_user_name': {
      const lines = introLines(lang).map((line) => '  > ' + line.replace(/\n/g, '\n  > ')).join('\n')
      return [
        'First conversation. The app already showed the user this opening on your behalf:',
        lines,
        'They are now replying to the last line (what should I call you?). Decide from their message what they meant:',
        '(a) If it says how to address them — a name, a nickname, "just call me boss" — confirm it in one short sentence, ask in one sentence what they would like to call you, and end the reply with exactly this fenced block:',
        '```' + FENCE_NAMING,
        '{"user_address": "<how to address them>", "suggest": ["<name 1>", "<name 2>"]}',
        '```',
        '`suggest` holds two names for yourself the user could pick, in the language they write: two-character Chinese names in the spirit of 豆丁 or 小满 (warm, a little playful, easy to say) when they write Chinese; short English names like Pip or Wren otherwise. ' +
          `Never suggest the name of an existing assistant or product (${TAKEN_NAMES}), nor the user's own name. ` +
          'The app renders the block as a chooser under your reply, so do not list the names in your text.',
        '(b) If they say they would rather not be called anything in particular, do the same with "user_address": null.',
        '(c) If the message is about something else — a question, a task, small talk — help with it first, in full, and end with one light sentence bringing the question back (what should I call you?). No block in that case; the app keeps waiting.',
        "Reply in the user's language; keep it short.",
      ].join('\n')
    }
    case 'ask_agent_name': {
      const chips = currentSuggestions(state, lang)
      return [
        `First conversation. You asked what the user would like to call you; the app is showing a chooser under that question with ${chips.map((c) => `"${c}"`).join(', ')} and "something else". Decide from their message:`,
        `(a) If it gives you a name — typed on its own, "call you 豆丁", "the first one" (meaning "${chips[0] ?? ''}") — that is your name from now on. Reply as yourself: one short line about the name, then three bullets with the most useful things you can do for them right now on this computer (choose from: ${CAN_DO}), one concrete line each, no emoji; end by asking what they want to try first. Then end the reply with exactly this fenced block:`,
        '```' + FENCE_NAMING,
        '{"agent_name": "<the name>"}',
        '```',
        'The app saves the name from the block — no tool call is needed for it.',
        '(b) If the message is about something else, help with it first, in full, and end with one light sentence bringing the naming back; no block, the chooser stays.',
        "Reply in the user's language." + addressLine,
      ].join('\n')
    }
    case 'named':
      return `First conversation. The user just named you "${agentName}" — the app already saved it, so it is your name now; no tool call is needed for it. ` +
        `Reply in the user's language: one short line about the name, then three bullets with the most useful things you can do for them right now on this computer (choose from: ${CAN_DO}). One concrete line each, no emoji. End by asking what they want to try first.` + addressLine
    default:
      return null
  }
}

/** The memory line the phone writes under "## About the user" when the person said how to be addressed. */
export function addressMemory(current: string, address: string): string {
  const line = `- Call them: ${address}`
  const lines = current.split('\n')
  if (lines.some((l) => l.trim().startsWith('- Call them:'))) return lines.map((l) => (l.trim().startsWith('- Call them:') ? line : l)).join('\n')
  if (!current.trim()) return `## About the user\n${line}\n`
  return `${current.trimEnd()}\n\n## About the user\n${line}\n`
}
