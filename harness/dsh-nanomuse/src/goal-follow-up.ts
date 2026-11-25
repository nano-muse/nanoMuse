import type { Goal } from './rooms.ts'

/** A saved date denotes a local calendar day, including across DST changes. */
export function validGoalDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(value + 'T00:00:00Z')
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}

export function localDateKey(now: number): string {
  const day = new Date(now)
  return [day.getFullYear(), String(day.getMonth() + 1).padStart(2, '0'), String(day.getDate()).padStart(2, '0')].join('-')
}

export type GoalFollowUpReason = 'today' | 'overdue' | 'tomorrow' | 'attention'
interface Candidate {
  goal: Goal
  reason: GoalFollowUpReason
  days: number
  stage: number
}

const priority: Record<GoalFollowUpReason, number> = { today: 0, overdue: 1, tomorrow: 2, attention: 3 }

/** Each dated goal can surface once per milestone. A live request for attention is a separate signal. */
export function nextGoalFollowUp(goals: readonly Goal[], day: string, now: number): Candidate | undefined {
  const midnight = Date.parse(day + 'T00:00:00Z')
  const candidates: Candidate[] = []
  for (const goal of goals) {
    if (goal.status !== 'tracking' || goal.feedMuted) continue
    const days = validGoalDate(goal.due) ? (Date.parse(goal.due + 'T00:00:00Z') - midnight) / 86_400_000 : Infinity
    const stage = days === 1 ? 1 : days === 0 ? 2 : days < 0 && days >= -7 ? 3 : 0
    const seen = goal.followUpSeen
    if (stage && !(seen?.due === goal.due && (seen?.stage ?? 0) >= stage)) {
      candidates.push({ goal, reason: stage === 2 ? 'today' : stage === 3 ? 'overdue' : 'tomorrow', days, stage })
    } else if (goal.attention && goal.summary && !seen?.attention && goal.updatedAt <= now && now - goal.updatedAt <= 7 * 86_400_000) {
      candidates.push({ goal, reason: 'attention', days: 0, stage: 0 })
    }
  }
  return candidates.sort((a, b) => priority[a.reason] - priority[b.reason] ||
    b.days - a.days || b.goal.updatedAt - a.goal.updatedAt || a.goal.id.localeCompare(b.goal.id))[0]
}

export function followUpText(goal: Goal, reason: GoalFollowUpReason, lang: string): string {
  const zh = lang.startsWith('zh')
  const date = validGoalDate(goal.due) ? new Date(goal.due + 'T12:00:00').toLocaleDateString(zh ? 'zh' : 'en', { year: 'numeric', month: 'short', day: 'numeric' }) : ''
  const reasons: Record<GoalFollowUpReason, string> = zh
    ? { today: `这项目标今天到期（${date}）。`, tomorrow: `这项目标明天到期（${date}）。`, overdue: `截止日期是${date}，目标仍在追踪中。`, attention: '最近一次目标检查有事需要你留意。' }
    : { today: `This goal is due today (${date}).`, tomorrow: `This goal is due tomorrow (${date}).`, overdue: `This goal is still open after its ${date} deadline.`, attention: 'The latest goal check flagged something for your attention.' }
  const detail = goal.nextStep ? (zh ? `计划的下一步：${goal.nextStep}` : `Planned next step: ${goal.nextStep}`) : ''
  return [reasons[reason], goal.summary, detail].filter(Boolean).join('\n\n')
}
