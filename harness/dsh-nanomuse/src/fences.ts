/**
 * The app-protocol fences the agent writes in a chat and the clients act on — the same
 * tags, keys and rules as the phone (`goals/GoalFlow.kt`, `feed/FeedFlow.kt`,
 * `ui/chat/NanoMuseBlock.kt`), so one agent behaves the same on every device:
 *
 *   ```nanomuse-goal         {"title","why","category","check_every_hours","check_time","steps","first_check"}
 *   ```nanomuse-goal-update  {"goal_id","progress","status":"on_track|attention|done","note"}
 *   ```nanomuse-feed         {"emoji","title","type","body","source"}
 *
 * Pure: parsing and the prompt lines; `rooms.ts` applies them. The static Ideas list
 * (`assets/ideas.{en,zh}.json`, byte-for-byte the phone's `assets/nanomuse/ideas.*.json`)
 * is read here too.
 */

import { validGoalDate } from './goal-follow-up.ts'

export const FENCE_GOAL = 'nanomuse-goal'
export const FENCE_GOAL_UPDATE = 'nanomuse-goal-update'
export const FENCE_FEED = 'nanomuse-feed'

/** Every complete fence tagged `tag` in `text`, inner text as written. */
export function findFences(text: string, tag: string): string[] {
  if (!text.includes('```' + tag)) return []
  const re = new RegExp('```' + tag.replace(/[-]/g, '\\-') + '[ \\t]*\\r?\\n([\\s\\S]*?)```', 'g')
  const out: string[] = []
  for (const m of text.matchAll(re)) out.push(m[1] ?? '')
  return out
}

function obj(json: string): Record<string, unknown> | undefined {
  try {
    const value: unknown = JSON.parse(json.trim())
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined
  } catch {
    return undefined
  }
}

const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : typeof v === 'number' ? String(v) : '')

export const GOAL_CATEGORIES = ['health', 'relationships', 'finance', 'career', 'hobbies', 'productivity', 'other'] as const
export type GoalCategoryKey = (typeof GOAL_CATEGORIES)[number]

/** The phone says `interests` where this side says `hobbies`; both are read. */
export function goalCategory(key: unknown): GoalCategoryKey {
  const k = str(key).toLowerCase()
  if (k === 'interests') return 'hobbies'
  return (GOAL_CATEGORIES as readonly string[]).includes(k) ? (k as GoalCategoryKey) : 'other'
}

export interface GoalBlock {
  title: string
  why: string
  category: GoalCategoryKey
  /** 0 means a daily check at `checkTime`. */
  checkEveryHours: number
  /** `HH:MM`. */
  checkTime: string
  steps: string[]
  due?: string
  firstCheck: string
}

/** `HH:MM` out of whatever the model wrote; 09:00 when there is none (the phone's parseTime). */
export function parseCheckTime(s: unknown): string {
  const m = /(\d{1,2}):(\d{2})/.exec(str(s))
  if (!m) return '09:00'
  const h = Math.min(23, Math.max(0, Number(m[1])))
  const min = Math.min(59, Math.max(0, Number(m[2])))
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`
}

export function parseGoalBlock(json: string): GoalBlock | undefined {
  const o = obj(json)
  if (!o) return undefined
  const title = str(o.title).slice(0, 60)
  if (!title) return undefined
  const hours = Number(o.check_every_hours ?? 0)
  const steps = Array.isArray(o.steps) ? o.steps.map(str).filter(Boolean).slice(0, 6) : []
  return {
    title,
    why: str(o.why).slice(0, 300),
    category: goalCategory(o.category),
    checkEveryHours: Number.isFinite(hours) ? Math.min(24 * 7, Math.max(0, Math.round(hours))) : 0,
    checkTime: parseCheckTime(o.check_time),
    steps,
    ...(validGoalDate(o.due) ? { due: o.due } : {}),
    firstCheck: str(o.first_check).slice(0, 300),
  }
}

export interface GoalUpdateBlock {
  goalId: string
  /** 0–100, or -1 when the block did not say. */
  progress: number
  status: 'on_track' | 'attention' | 'done'
  note: string
  nextStep?: string
}

export function parseGoalUpdate(json: string): GoalUpdateBlock | undefined {
  const o = obj(json)
  if (!o) return undefined
  const p = o.progress === undefined || o.progress === null ? -1 : Number(o.progress)
  const status = str(o.status)
  return {
    goalId: str(o.goal_id),
    progress: Number.isFinite(p) ? Math.min(100, Math.max(-1, Math.round(p))) : -1,
    status: status === 'done' || status === 'attention' ? status : 'on_track',
    note: str(o.note).slice(0, 300),
    ...(typeof o.next_step === 'string' ? { nextStep: o.next_step.trim().slice(0, 240) } : {}),
  }
}

// ---- the first conversation's naming block ------------------------------------------

export const FENCE_NAMING = 'nanomuse-naming'
/** A name is one line, at most this long. */
export const MAX_NAME = 16

/** What the model told the app in a `nanomuse-naming` block (the phone's `NamingBlock`). */
export interface NamingBlock {
  /** The block had a `user_address` key (a null value = the person wants no form of address). */
  addressGiven: boolean
  userAddress: string | null
  /** Names the model suggests for itself, cleaned, distinct, at most three. */
  suggestions: string[]
  /** The name the person gave the agent, when this block says so. */
  agentName: string | null
}

const QUOTES = /^[\s"'“”‘’「」『』]+|[\s"'“”‘’「」『』。，、！!？?.]+$/g

/** A usable name: one line, quotes and trailing punctuation gone, not absurdly long; null otherwise. */
export function cleanName(raw: unknown): string | null {
  if (typeof raw !== 'string') return null
  const t = raw.replace(QUOTES, '').trim()
  if (!t || t.includes('\n') || t.length > MAX_NAME) return null
  return t
}

/** The last `nanomuse-naming` block in `text`, or null when there is none or it is not JSON. */
export function parseNamingBlock(text: string | null | undefined): NamingBlock | null {
  if (!text) return null
  const fences = findFences(text, FENCE_NAMING)
  const json = fences[fences.length - 1]
  if (json === undefined) return null
  const o = obj(json)
  if (!o) return null
  const suggestions: string[] = []
  if (Array.isArray(o.suggest)) {
    for (const raw of o.suggest) {
      const name = cleanName(raw)
      if (name && !suggestions.includes(name)) suggestions.push(name)
      if (suggestions.length === 3) break
    }
  }
  return {
    addressGiven: 'user_address' in o,
    userAddress: o.user_address === null || o.user_address === undefined ? null : cleanName(o.user_address),
    suggestions,
    agentName: o.agent_name === null || o.agent_name === undefined ? null : cleanName(o.agent_name),
  }
}

export const FEED_TYPES = ['brief', 'reminder', 'idea', 'goal', 'memory', 'note'] as const

export interface FeedDraft {
  title: string
  body: string
  type: (typeof FEED_TYPES)[number]
  emoji: string
  source: string[]
}

export function parseFeedDraft(json: string): FeedDraft | undefined {
  const o = obj(json)
  if (!o) return undefined
  const title = str(o.title).slice(0, 80)
  const body = str(o.body)
  if (!title || !body) return undefined
  const type = str(o.type).toLowerCase()
  const source = Array.isArray(o.source)
    ? o.source.map(str).filter(Boolean)
    : typeof o.source === 'string' ? o.source.split(/[;,]/).map((s) => s.trim()).filter(Boolean) : []
  return {
    title,
    body,
    type: (FEED_TYPES as readonly string[]).includes(type) ? (type as FeedDraft['type']) : 'note',
    emoji: str(o.emoji).slice(0, 4),
    source: source.slice(0, 4),
  }
}

// ---- the words around a goal (the phone's GoalFlow strings, en and zh) ------------------------

/** "I'd like to create a Health goal." — what the person is shown to have said. */
export function goalOpener(categoryLabel: string, zh: boolean): string {
  return zh ? `我想创建一个${categoryLabel}目标。` : `I'd like to create a ${categoryLabel} goal.`
}

/** The shaping instructions that travel with the opener (the phone's `creationAddendum`). */
export function goalCreationNote(categoryKey: string, zh: boolean): string {
  const lines = zh
    ? [
        `[对方刚在「目标」里选择了创建一个「${categoryKey}」分类的目标。像 Muse 一样一起把它定下来：最多问三个简短的问题，一次一个——(1) 具体想达成什么，(2) 为什么重要、到什么时候，(3) 希望多久检查一次（每 N 小时，或每天某个时间）。每条两三句话；对方已经回答过的就跳过。`,
        `信息够了以后，先用一句温暖的话确认，然后写出恰好一个标记为 \`${FENCE_GOAL}\` 的代码块，内容是 JSON，键如下：`,
        `{"title": "不超过 40 字", "why": "一句话", "category": "${categoryKey}", "check_every_hours": <整数，0 表示每天检查一次>, "check_time": "HH:MM"（check_every_hours 为 0 时使用）, "steps": ["3 到 5 个你会做或跟进的简短步骤"], "first_check": "第一次检查时你会做什么"}`,
        `只有对方给出明确截止日期时才加上 due（本地日期，YYYY-MM-DD）。`,
        `不要描述这个代码块，也不要提 JSON——应用会把它渲染成卡片。代码块之后不要再说话。之后这个目标的检查会在它自己的对话里自动进行。]`,
      ]
    : [
        `[The person just chose to create a goal in the "${categoryKey}" category from their Goals room. Shape it together: ask at most three short questions, ONE message at a time, in the person's language: (1) what exactly they want to achieve, (2) why it matters and by when, (3) how often you should check in (every N hours, or daily at a time). Two or three sentences per message; if they already answered something, skip that question.`,
        `When you have enough, reply with one warm sentence of confirmation and then EXACTLY ONE fenced code block tagged \`${FENCE_GOAL}\` containing JSON with these keys:`,
        `{"title": "<= 40 chars", "why": "one sentence", "category": "${categoryKey}", "check_every_hours": <integer, 0 means a daily check>, "check_time": "HH:MM" (used when check_every_hours is 0), "steps": ["3 to 5 short steps you will take or track"], "first_check": "what you will do at the first check"}`,
        `Include due (local YYYY-MM-DD) only when the person has supplied a specific deadline.`,
        `Do not describe the block or mention JSON — the app renders it as a card. Say nothing after the block. Later, checks for this goal happen automatically in their own conversation.]`,
      ]
  return lines.join('\n')
}

/** The one-line message each scheduled check sends (the phone's `checkPrompt`). */
export function goalCheckPrompt(title: string, zh: boolean, firstCheck?: string): string {
  const head = zh ? `到点了，看看这个目标：${title}` : `Time to check on this goal: ${title}`
  if (!firstCheck) return head
  return `${head}\n${zh ? `第一次先：${firstCheck}` : `First time round: ${firstCheck}`}`
}

/** What a goal's chat is told about itself (the phone's `systemAddendum`), as a bracketed note. */
export function goalHomeNote(goal: { id: string; title: string; why: string; steps: string[]; checkEveryHours: number; checkTime: string }, zh: boolean): string {
  const cadence = goal.checkEveryHours > 0 ? `every ${goal.checkEveryHours} hour(s)` : `daily at ${goal.checkTime}`
  const steps = goal.steps.map((s, i) => `${i + 1}. ${s}`).join('\n') || '(none yet)'
  return [
    `[This conversation tracks a goal (nanoMuse). Goal: ${goal.title}${goal.why ? `. Why: ${goal.why}` : ''}`,
    `Steps:\n${steps}`,
    `Checks run ${cadence}.`,
    `When a message asks you to check on the goal: find out where it stands right now with your tools (shell, browser, connectors, memory) and take the next small step if it is safe and reversible. Never pay, send messages or delete anything without asking. Then write the person a short update in ${zh ? 'Chinese' : 'their language'} (at most six lines) and end with EXACTLY ONE fenced code block tagged \`${FENCE_GOAL_UPDATE}\` containing {"goal_id": "${goal.id}", "progress": <0-100>, "status": "on_track|attention|done", "note": "one line", "next_step": "the concrete next step, or empty"}. In ordinary conversation here, answer normally and add that block only when the goal's progress actually changed.]`,
  ].join('\n')
}

// ---- the Ideas list ----------------------------------------------------------------------------

export type IdeaKind = 'chat' | 'routine' | 'goal'

export interface StaticIdea {
  /** `<section>/<id>`, stable across versions of the list. */
  id: string
  section: string
  sectionTitle: string
  emoji: string
  title: string
  body: string
  kind: IdeaKind
  prompt: string
  /** Routine default, `HH:MM`. */
  time?: string
  /** Goal default category key (the phone's keys; `interests` is read as `hobbies`). */
  category?: string
}

/** The phone's `Ideas.load`: sections of ideas, unknown kinds read as chat. */
export function parseIdeas(json: string): StaticIdea[] {
  const root = obj(json)
  const sections = Array.isArray(root?.sections) ? root.sections : []
  const out: StaticIdea[] = []
  for (const s of sections as Record<string, unknown>[]) {
    const section = str(s.id)
    const sectionTitle = str(s.title)
    if (!section) continue
    for (const o of (Array.isArray(s.ideas) ? s.ideas : []) as Record<string, unknown>[]) {
      const id = str(o.id)
      const title = str(o.title)
      if (!id || !title) continue
      const kind = str(o.kind).toLowerCase()
      out.push({
        id: `${section}/${id}`,
        section,
        sectionTitle,
        emoji: str(o.emoji) || '✨',
        title,
        body: str(o.body),
        kind: kind === 'routine' || kind === 'goal' ? kind : 'chat',
        prompt: str(o.prompt) || title,
        ...(str(o.time) ? { time: parseCheckTime(o.time) } : {}),
        ...(str(o.category) ? { category: str(o.category) } : {}),
      })
    }
  }
  return out
}
