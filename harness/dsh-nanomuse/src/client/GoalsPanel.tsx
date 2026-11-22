/**
 * Goals (目标): what the person is tracking, each a checkbox row with the
 * agent's one-line status under the title; a row opens the goal's card — its
 * description, the automations running for it (the harness's schedules in the
 * goal's chat) and the activity timeline, day by day — with Check in, Open the
 * chat, Done, Delete. Below the list, "Create a goal" by category opens a
 * sheet with examples; the goal then lives in a chat of its own.
 */
import { failureText } from './api.ts'
import { createElement as h, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import type { Translate } from './api.ts'
import { IconAlarm, IconBriefcase, IconCheck, IconCheckCircle, IconChevronRight, IconCircleDot, IconDollar, IconHeartLine, IconMonitor, IconPalette, IconSquare, IconTarget, IconUsers } from './icons.tsx'
import { GOALS_PANEL } from './panels.ts'
import { nav, roomsCall, useRooms, type Category, type Goal, type GoalAutomation } from './rooms.ts'
import { peekWin } from './win.ts'
import { dayLabel, Empty, MoreButton, RoomToggle, Sheet } from './ui.tsx'
import type { Words } from './locales.ts'

const CATEGORIES: { id: Category; label: Words; icon: (p: { size: number }) => ReactNode; examples: Words[] }[] = [
  { id: 'health', label: 'catHealth', icon: IconHeartLine, examples: ['exHealth1', 'exHealth2', 'exHealth3'] },
  { id: 'relationships', label: 'catRelationships', icon: IconUsers, examples: ['exRel1', 'exRel2', 'exRel3'] },
  { id: 'finance', label: 'catFinance', icon: IconDollar, examples: ['exFin1', 'exFin2', 'exFin3'] },
  { id: 'career', label: 'catCareer', icon: IconBriefcase, examples: ['exCareer1', 'exCareer2', 'exCareer3'] },
  { id: 'hobbies', label: 'catHobbies', icon: IconPalette, examples: ['exHobby1', 'exHobby2', 'exHobby3'] },
  { id: 'productivity', label: 'catProductivity', icon: IconMonitor, examples: ['exProd1', 'exProd2', 'exProd3'] },
  { id: 'other', label: 'catOther', icon: IconCircleDot, examples: [] },
]

export function makeGoalsPanel(t: Translate) {
  return function GoalsPanel(): ReactNode {
    const rooms = useRooms()
    const [openId, setOpenId] = useState<string | undefined>()
    const [creating, setCreating] = useState<Category | undefined>()
    const [beginning, setBeginning] = useState<Category | undefined>()
    const [showDone, setShowDone] = useState(false)
    const [error, setError] = useState<string | undefined>()
    const open = rooms.goals.find((g) => g.id === openId)
    const tracking = rooms.goals.filter((g) => g.status !== 'done')
    const done = rooms.goals.filter((g) => g.status === 'done')

    const fail = (err: unknown) => setError(failureText(t, err))
    const setStatus = (goal: Goal, status: Goal['status']) => { roomsCall('goals/update', { id: goal.id, status }).catch(fail) }
    const remove = (goal: Goal) => {
      if (!window.confirm(t('goalDeleteConfirm', { title: goal.title }))) return
      setOpenId(undefined)
      roomsCall('goals/delete', { id: goal.id }).catch(fail)
    }
    // a goal's chat opens beside the room, the way Muse splits the window for goals
    const beside = (sessionId: string) => { nav.openSession(sessionId); nav.split(GOALS_PANEL) }
    const checkIn = (goal: Goal) => {
      roomsCall<{ sessionId: string }>('goals/check-in', { id: goal.id }).then(({ sessionId }) => { setOpenId(undefined); beside(sessionId) }).catch(fail)
    }
    const openChat = (goal: Goal) => { setOpenId(undefined); beside(goal.sessionId) }
    // a category row begins the planning chat (the phone's flow): "I'd like to create a … goal"
    // goes into the chat the person is in, the agent asks up to three questions and writes
    // the goal block, which becomes the goal; typing it out stays one step away in the menu
    const begin = (category: Category) => {
      if (beginning) return
      setBeginning(category)
      setError(undefined)
      roomsCall<{ sessionId: string }>('goals/begin', { category, sessionId: peekWin().current ?? '' }).then(({ sessionId }) => beside(sessionId)).catch(fail).finally(() => setBeginning(undefined))
    }

    return h('div', { className: 'nm-room' },
      h('div', { className: 'nm-room-top', 'data-window-drag': true }),
      h('div', { className: 'nm-room-head' },
        h(RoomToggle, { t, panel: GOALS_PANEL }),
        h('h1', { className: 'nm-room-title' }, t('railGoals')),
        h('div', { className: 'nm-room-actions' },
          h(MoreButton, { label: t('more'), size: 36, items: [
            { id: 'done', label: showDone ? t('goalsHideDone') : t('goalsShowDone', { n: done.length }), onSelect: () => setShowDone((v) => !v) },
            { id: 'typed', label: t('goalTypeOut'), onSelect: () => setCreating('other') },
          ] }))),
      h('div', { className: 'nm-room-body' },
        h('div', { className: 'nm-room-inner nm-goals' },
          error ? h('div', { className: 'nm-room-error' }, error) : null,
          tracking.length === 0 && !showDone
            ? h(Empty, { icon: h(IconTarget, { size: 28 }), text: t('goalsEmptyTitle') }, h('p', { className: 'nm-empty-sub' }, t('goalsEmptyBody')))
            : h('section', null,
                h('div', { className: 'nm-goals-label' }, h('span', { className: 'nm-status-dot nm-on' }), t('goalsTracking')),
                tracking.map((goal) => h(GoalRow, { key: goal.id, t, goal, onOpen: () => setOpenId(goal.id), onToggle: () => setStatus(goal, 'done'), onCheckIn: () => checkIn(goal), onChat: () => openChat(goal), onDelete: () => remove(goal) })),
                showDone && done.length
                  ? h('div', null,
                      h('div', { className: 'nm-goals-label nm-muted' }, t('goalsDone')),
                      done.map((goal) => h(GoalRow, { key: goal.id, t, goal, onOpen: () => setOpenId(goal.id), onToggle: () => setStatus(goal, 'tracking'), onCheckIn: () => checkIn(goal), onChat: () => openChat(goal), onDelete: () => remove(goal) })))
                  : null),
          h('section', { className: 'nm-goals-create' },
            h('h2', { className: 'nm-room-h2' }, t('goalsCreate')),
            CATEGORIES.map((c) => h('button', { key: c.id, type: 'button', className: 'nm-cat-row', disabled: beginning !== undefined, 'aria-busy': beginning === c.id, onClick: () => begin(c.id) },
              h('span', { className: 'nm-cat-icon' }, h(c.icon, { size: 19 })),
              h('span', { className: 'nm-cat-label' }, t(c.label)),
              beginning === c.id ? h('span', { className: 'nm-spinner nm-spinner-sm' }) : h(IconChevronRight, { size: 16, className: 'nm-row-chevron' })))))),
      open ? h(GoalCard, { t, goal: open, automations: rooms.automations[open.id] ?? [], lang: rooms.lang, onClose: () => setOpenId(undefined), onCheckIn: () => checkIn(open), onChat: () => openChat(open), onDone: () => setStatus(open, open.status === 'done' ? 'tracking' : 'done'), onDelete: () => remove(open), onFail: fail }) : null,
      creating ? h(CreateGoal, { t, category: creating, onClose: () => setCreating(undefined), onCreated: (goal) => { setCreating(undefined); beside(goal.sessionId) } }) : null)
  }
}

function GoalRow({ t, goal, onOpen, onToggle, onCheckIn, onChat, onDelete }: { t: Translate; goal: Goal; onOpen(): void; onToggle(): void; onCheckIn(): void; onChat(): void; onDelete(): void }): ReactNode {
  const done = goal.status === 'done'
  const sub = goal.summary || goal.description.split('\n')[0] || ''
  const progress = typeof goal.progress === 'number' && goal.progress >= 0 ? Math.min(100, goal.progress) : -1
  return h('div', { className: `nm-goal${done ? ' nm-done' : ''}${goal.attention ? ' nm-attention' : ''}`, role: 'button', tabIndex: 0, 'aria-label': goal.title, onClick: onOpen, onKeyDown: (e: KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } } },
    h('button', { type: 'button', role: 'checkbox', 'aria-checked': done, className: `nm-check${done ? ' nm-on' : ''}`, 'aria-label': done ? t('goalReopen') : t('goalMarkDone'), onClick: (e: MouseEvent) => { e.stopPropagation(); onToggle() } }, done ? h(IconCheck, { size: 13, stroke: 2.5 }) : null),
    h('div', { className: 'nm-goal-main' },
      h('div', { className: 'nm-goal-title' }, goal.title, goal.attention && !done ? h('span', { className: 'nm-goal-flag' }, t('goalAttention')) : null),
      sub ? h('div', { className: 'nm-goal-sub' }, sub) : null,
      progress >= 0 && !done ? h('div', { className: 'nm-goal-bar', role: 'progressbar', 'aria-valuenow': progress, 'aria-valuemin': 0, 'aria-valuemax': 100 }, h('span', { style: { width: `${progress}%` } })) : null),
    h(MoreButton, { label: t('more'), quiet: true, size: 28, items: [
      { id: 'checkin', label: t('goalCheckIn'), onSelect: onCheckIn },
      { id: 'chat', label: t('goalOpenChat'), onSelect: onChat },
      { id: 'toggle', label: done ? t('goalReopen') : t('goalMarkDone'), onSelect: onToggle },
      'sep',
      { id: 'delete', label: t('goalDelete'), danger: true, onSelect: onDelete },
    ] }))
}

function ruleLabel(t: Translate, a: GoalAutomation): string {
  const [kind, rest = ''] = a.rule.split(/[@ ]/, 2) as [string, string?]
  if (kind === 'daily') return t('autoDaily', { time: a.rule.slice(6) })
  if (kind === 'weekly') return t('autoWeekly')
  if (kind === 'cron') return t('autoCron')
  if (kind === 'every') return t('autoEvery', { n: Math.max(1, Math.round(Number.parseInt(rest || '0', 10) / 60)) })
  return t('autoOnce')
}

function GoalCard({ t, goal, automations, lang, onClose, onCheckIn, onChat, onDone, onDelete, onFail }: { t: Translate; goal: Goal; automations: GoalAutomation[]; lang: string; onClose(): void; onCheckIn(): void; onChat(): void; onDone(): void; onDelete(): void; onFail(err: unknown): void }): ReactNode {
  const days = useMemo(() => {
    const groups: { label: string; items: Goal['activity'] }[] = []
    for (const entry of goal.activity) {
      const label = dayLabel(t, entry.at, lang)
      const last = groups[groups.length - 1]
      if (last && last.label === label) last.items.push(entry)
      else groups.push({ label, items: [entry] })
    }
    return groups
  }, [goal.activity, lang, t])
  const removeAutomation = (a: GoalAutomation) => { roomsCall('goals/automation/delete', { id: goal.id, schedule_id: a.id }).catch(onFail) }
  return h(Sheet, { title: goal.title, closeLabel: t('close'), onClose, wide: true,
    header: h(MoreButton, { label: t('more'), size: 30, items: [
      { id: 'checkin', label: t('goalCheckIn'), onSelect: onCheckIn },
      { id: 'chat', label: t('goalOpenChat'), onSelect: onChat },
      { id: 'done', label: goal.status === 'done' ? t('goalReopen') : t('goalMarkDone'), onSelect: () => { onDone(); onClose() } },
      'sep',
      { id: 'delete', label: t('goalDelete'), danger: true, onSelect: onDelete },
    ] }) },
    h('div', { className: 'nm-goal-card' },
      goal.description ? h('p', { className: 'nm-sheet-lead' }, goal.steps?.length ? goal.description.split('\n')[0] : goal.description) : null,
      goal.steps?.length
        ? h('ul', { className: 'nm-goal-steps' }, goal.steps.map((step, i) => h('li', { key: i }, h(IconSquare, { size: 14 }), h('span', null, step))))
        : null,
      typeof goal.progress === 'number' && goal.progress >= 0
        ? h('div', { className: 'nm-goal-progress' },
            h('div', { className: `nm-goal-bar${goal.attention ? ' nm-attention' : ''}`, role: 'progressbar', 'aria-valuenow': goal.progress, 'aria-valuemin': 0, 'aria-valuemax': 100 }, h('span', { style: { width: `${Math.min(100, goal.progress)}%` } })),
            h('span', { className: 'nm-goal-pct' }, `${Math.min(100, goal.progress)}%`, goal.attention ? ` · ${t('goalAttention')}` : ''))
        : null,
      goal.summary ? h('p', { className: 'nm-goal-summary' }, goal.summary) : null,
      h(GoalFeedSettings, { key: goal.id, t, goal }),
      h('div', { className: 'nm-auto-card' },
        h('div', { className: 'nm-auto-head' }, t('goalRunning')),
        automations.length === 0
          ? h('div', { className: 'nm-auto-empty' }, t('goalNoAutomations'))
          : automations.map((a) => h('div', { key: a.id, className: 'nm-auto-row' },
              h('span', { className: 'nm-auto-icon' }, h(IconAlarm, { size: 18 })),
              h('div', { className: 'nm-auto-main' },
                h('div', { className: 'nm-auto-title' }, a.title),
                h('div', { className: 'nm-auto-sub' }, ruleLabel(t, a))),
              h(MoreButton, { label: t('more'), size: 26, items: [{ id: 'stop', label: t('autoStop'), danger: true, onSelect: () => removeAutomation(a) }] })))),
      h('h3', { className: 'nm-goal-h3' }, t('goalActivity')),
      days.length === 0
        ? h('p', { className: 'nm-sheet-fine' }, t('goalNoActivity'))
        : days.map((day) => h('section', { key: day.label, className: 'nm-day' },
            h('div', { className: 'nm-day-label' }, day.label.toUpperCase()),
            day.items.map((entry, i) => h('div', { key: `${entry.at}-${i}`, className: 'nm-act' },
              h('span', { className: 'nm-act-icon' }, h(IconCheckCircle, { size: 16 })),
              h('div', { className: 'nm-act-main' },
                h('div', { className: 'nm-act-title' }, entry.title),
                entry.text ? h('div', { className: 'nm-act-text' }, entry.text) : null)))))))
}

function GoalFeedSettings({ t, goal }: { t: Translate; goal: Goal }): ReactNode {
  const [due, setDue] = useState<string>()
  const [muted, setMuted] = useState<boolean>()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string>()
  const date = due ?? goal.due ?? ''
  const enabled = !(muted ?? goal.feedMuted)
  const changedDate = date !== (goal.due ?? '')
  const changedMute = !enabled !== Boolean(goal.feedMuted)
  const save = (event: FormEvent) => {
    event.preventDefault()
    if (saving || !(changedDate || changedMute)) return
    setSaving(true)
    setError(undefined)
    roomsCall('goals/update', { id: goal.id, ...(changedDate ? { due: date } : {}), ...(changedMute ? { feedMuted: !enabled } : {}) })
      .then(() => { setDue(undefined); setMuted(undefined) })
      .catch((err: unknown) => setError(failureText(t, err)))
      .finally(() => setSaving(false))
  }
  return h('details', { className: 'nm-auto-card' },
    h('summary', { className: 'nm-auto-head' }, t('goalFeedSettings')),
    h('form', { className: 'nm-sheet-form', onSubmit: save },
      h('label', null, t('goalDueDate'), ' ', h('input', { className: 'nm-field', type: 'date', value: date, disabled: saving, onChange: (e: FormEvent<HTMLInputElement>) => setDue(e.currentTarget.value) })),
      h('label', { className: 'nm-feed-routine' }, h('input', { type: 'checkbox', checked: enabled, disabled: saving, onChange: (e: FormEvent<HTMLInputElement>) => setMuted(!e.currentTarget.checked) }), t('goalFeedEnabled')),
      error ? h('p', { className: 'nm-room-error' }, error) : null,
      h('button', { type: 'submit', className: 'nm-pill nm-pill-sm', disabled: saving || !(changedDate || changedMute) }, t('save'))))
}

function CreateGoal({ t, category, onClose, onCreated }: { t: Translate; category: Category; onClose(): void; onCreated(goal: Goal): void }): ReactNode {
  const meta = CATEGORIES.find((c) => c.id === category) ?? CATEGORIES[0]!
  const [text, setText] = useState('')
  const [due, setDue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!text.trim()) return
    setBusy(true)
    setError(undefined)
    roomsCall<Goal>('goals/create', { category, text: text.trim(), ...(due ? { due } : {}) }).then(onCreated).catch((err: unknown) => setError(failureText(t, err))).finally(() => setBusy(false))
  }
  return h(Sheet, { title: `${t('goalsCreate')} · ${t(meta.label)}`, closeLabel: t('close'), onClose,
    footer: h('div', { className: 'nm-sheet-actions' },
      h('span', { style: { flex: 1 } }),
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: onClose }, t('cancel')),
      h('button', { type: 'submit', form: 'nm-goal-create', className: 'nm-pill nm-pill-sm', disabled: busy || !text.trim() }, busy ? t('goalCreating') : t('goalCreate'))) },
    h('form', { id: 'nm-goal-create', className: 'nm-sheet-form', onSubmit: submit },
      h('p', { className: 'nm-sheet-lead' }, t('goalCreateLead')),
      h('textarea', { className: 'nm-textarea', rows: 4, value: text, placeholder: t('goalPlaceholder'), maxLength: 2000, onChange: (e: FormEvent<HTMLTextAreaElement>) => setText(e.currentTarget.value), 'data-modal-autofocus': true }),
      h('label', null, t('goalDueDate'), ' ', h('input', { className: 'nm-field', type: 'date', value: due, onChange: (e: FormEvent<HTMLInputElement>) => setDue(e.currentTarget.value) })),
      h('div', { className: 'nm-chips' }, meta.examples.map((key) => h('button', { key, type: 'button', className: 'nm-chip', onClick: () => setText(t(key)) }, t(key)))),
      error ? h('div', { className: 'nm-room-error' }, error) : null))
}
