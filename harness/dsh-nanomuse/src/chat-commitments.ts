import { localDateKey, validGoalDate } from './goal-follow-up.ts'

// Only explicit undertakings and their latest revision are kept. Ordinary conversation,
// tool output and the assistant's answers do not become a second transcript.
const DAY = 86_400_000
const LIMIT = 8
export interface ChatCommitment {
  request: string
  at: number
  changedAt: number
  revision?: string
  changed?: boolean
  closed?: boolean
  goalId?: string
  due?: string
}
export interface ChatCommitments {
  owner: string
  items: ChatCommitment[]
  turn?: number
  focus?: string
}

const undertaking = /\b(?:i(?:['’]ll| will| need to| have to| must| promised to| agreed to)|we(?:['’]ll| will| need to| promised to)|remind me to|help me (?:draft|prepare|write)|(?:please )?(?:draft|write|prepare) (?:an? |the |my ))\b|我(?:答应|答應|承诺|承諾|打算|得|要|会|會)|(?:明[早天晚]|后天|後天|下周.|周[一二三四五六日天])[^。！？]{0,12}(?:要|得|联系|聯絡|发|發|写|寫|参观|參觀|开会|開會)|(?:帮我|幫我|请帮|請幫)(?:起草|写|寫|整理|联系|聯絡)/iu
const negated = /\b(?:if|whether|hypothetically|not (?:yet |already )?(?:sent|done|cancelled|canceled|finished)|do(?:es)?n['’]t|haven['’]t|isn['’]t|wasn['’]t)\b|如果|假如|是否|还没|還沒|没有取消|沒有取消|尚未|未取消|并未|並未/iu
const closed = /^(?:please )?cancel\b|\b(?:cancelled|canceled|called (?:it |that )?off|already (?:sent|done|finished|handled|booked)|(?:i|we)(?:['’]ve| have)? (?:just |already )?(?:sent|finished|booked|handled|completed)|(?:is|was|all) (?:done|settled|off)|no (?:longer )?need to)\b|^(?:done|sent|handled|sorted|finished)[.!\s]*$|(?:已(?:经|經)?|刚|剛)(?:经|經)?(?:办完|辦完|处理|處理|发出|發出|发了|發了|发送|發送|完成|取消|搞定)|取消了?|办(?:好|完)了|辦(?:好|完)了|发完了|發完了|发过了|發過了|搞定了|不用(?:再)?(?:发|發|准备|準備|联系|聯絡|跟进|跟進)/iu
const moved = /\b(?:reschedul(?:ed|e)|postpon(?:ed|e)|mov(?:e|ed) (?:it |that |the .{1,55}? )?(?:from|to|until)|push(?:ed)? (?:it |that )?(?:to|back)|instead (?:of|on))\b|改(?:到|在|成|期)|(?:就定在|确定在|確定在|定在)|推迟|推遲|推到|延期|延到|换到|換到/iu
const reopened = /\b(?:back on|reopen(?:ed)?|on again)\b|恢复(?:了|原计划|安排)|恢復(?:了|安排)|重新(?:开始|開始|安排|约|約)|还是要|還是要/iu
const relative = /\b(?:today|tomorrow|tonight|yesterday|(?:(?:next|this|on)\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b|(?:今天|明天|明早|明晚|后天|後天|今晚|(?:(?:下|本|这|這)(?:个|個)?)?(?:星期|周|週)[一二三四五六日天])|\b\d{4}-\d{2}-\d{2}\b/giu
const timePart = /\b(?:at\s+)?\d{1,2}(?::\d{2}(?:\s*[ap]m)?|\s*[ap]m)\b|(?:上午|下午|傍晚|晚上|早上)?[零一二三四五六七八九十两兩\d]{1,3}[点點时時](?:半|[一二三四五六七八九十\d]{1,3}分?)?/giu

function uncertainTime(text: string): boolean {
  const dates = [...text.matchAll(relative)]
  if (!dates.length) return false
  return /\b(?:maybe|possibly|either|undecided)\b|还没定|還沒定|可能|待定|二选一|二選一/iu.test(text) ||
    (dates.length > 1 && /\b(?:or|between)\b|或|还是|還是|、/iu.test(text))
}

function targetDay(text: string, at: number): string | undefined {
  // Both "Friday instead of Tuesday" and "from Tuesday to Friday" are revisions.
  const first = text.split(/\binstead of\b|而不是|而非/iu, 1)[0] ?? text
  const relevant = first.replace(/^.*(?:\bfrom\b.+?\bto\b|(?:原定|从|從).+?(?:改到|改为|改為|推到))/iu, '')
  const tokens = [...relevant.matchAll(relative)]
  if (tokens.length !== 1 || uncertainTime(relevant)) return
  const token = tokens[0]![0].toLowerCase()
  if (/^\d{4}-/u.test(token)) return validGoalDate(token) ? token : undefined
  const ref = new Date(at)
  const en = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'].findIndex(d => token.endsWith(d))
  const cn = /[日天一二三四五六]$/.test(token) && /周|週|星期/.test(token) ? '日一二三四五六'.indexOf(token.at(-1)!.replace('天', '日')) : -1
  const weekday = Math.max(en, cn)
  let days = 0
  if (weekday >= 0) {
    days = (weekday - ref.getDay() + 7) % 7
    if (/^下/.test(token) || /\bnext week\b/iu.test(relevant)) {
      days = 7 - (ref.getDay() + 6) % 7 + (weekday + 6) % 7
    }
    else if (!days && token.startsWith('next ')) days = 7
  } else if (/tomorrow|^明/.test(token)) days = 1
  else if (/^[后後]天/.test(token)) days = 2
  else if (token === 'yesterday') days = -1
  ref.setDate(ref.getDate() + days)
  return localDateKey(ref.getTime())
}

export function draftDelivered(answer: string): boolean {
  return /(?:^|\n)\s*(?:subject\s*:|主题[：:]|主旨[：:]|dear [^,\n]{1,60},|尊敬的[^：:\n]{1,30}[：:])/iu.test(answer)
    || (answer.trim().length >= 40 && /(?:^|\n)(?:hello|hi|各位|您好|大家好|你好)[^\n.!?。！？]{0,40}[,，：:。!！\n]/iu.test(answer))
}

const segmenter = new Intl.Segmenter(undefined, { granularity: 'word' })
const stop = new Set('already the and for that this have has was were our your them they tomorrow send sent draft promised need will that its with group meeting about please should moved move rescheduled postponed cancelled canceled finished done booked instead until changed now back again then plan was actually has been just despite shifted 正在 已经 已經 取消 改期 改到 推迟 周五 这件事 那件事 那个 那個 我们 我們 明天 我会 我會 需要 打算 答应 答應 联系 联络 安排'.split(' '))
function topics(text: string): Set<string> {
  const cleaned = text.replace(relative, ' ').replace(timePart, ' ').normalize('NFKC').toLowerCase()
  return new Set([...segmenter.segment(cleaned)].map(w => w.segment).filter(w => !stop.has(w) && !/^\d+$/u.test(w) && /\p{L}/u.test(w)
    && w.length >= (/[\p{Script=Han}\p{Script=Katakana}\p{Script=Hiragana}]/u.test(w) ? 2 : 3)))
}
function matchSubject(text: string, items: ChatCommitment[]): ChatCommitment | undefined {
  const words = topics(text)
  if (!words.size) return
  const ranked = items.map(item => { const t = topics(item.request); return { item, n: [...words].filter(w => t.has(w)).length } }).sort((a,b) => b.n - a.n)
  const best = ranked[0]
  if (best && best.n > (ranked[1]?.n ?? 0) && (best.n === words.size || (best.n >= 3 && best.n / words.size >= 0.8))) return best.item
}

function refersToFocus(text: string): boolean {
  const rest = text.toLowerCase().replace(/['’]ve\b/gu, '').replace(relative, ' ').replace(timePart, ' ')
    .replace(/(?:就定在|确定在|確定在|定在|改到|改期|改成|推迟|推遲|延到|延期|推到|取消|发了|發了|发完|發完|发过|發過|办完|辦完|办好|辦好|搞定|完成|处理|處理|恢复|恢復|重新安排|还是要|還是要|这个|這個|或是|或者|或|那个|那個|这件事|這件事|那件事|那封|这封|还是|還是|要发|要發|发|發|邮件|郵件|消息|已经|已經|刚刚|剛剛|现在|現在|了|我|就|吧|已)/gu, '')
    .replace(/\b(?:i|we|it|that|this|the|one|or|either|from|next|week|that['’]s|is|was|to|on|until|at|just|have|already|all|been|instead|move[ds]?|reschedule[ds]?|postpone[ds]?|cancel(?:led|ed)?|done|completed|sent|finished|handled|sorted|booked|back|again|message|email)\b/gu, '')
  return !/[\p{L}\p{N}]/u.test(rest)
}
export function statusUpdate(text: string): boolean {
  return closed.test(text) || moved.test(text) || reopened.test(text)
}

/** Fold one human turn into the commitments of this chat. An unqualified "done" has a
 * target only immediately after discussion of a single known item. */
export function noteCommitment(state: ChatCommitments, text: string, at: number, goal?: { id: string; title: string }): void {
  state.items = state.items.filter(i => at - i.changedAt <= 7 * DAY)
  const oldFocus = state.items.find(i => i.request === state.focus)
  delete state.focus
  const update = statusUpdate(text)
  if (update && !negated.test(text) && !/[?？]\s*$/u.test(text)) {
    // A goal is eligible only in its own chat and when the words identify it.
    const other: ChatCommitment[] = goal && !state.items.some(i => i.goalId === goal.id)
      ? [{ request: goal.title, at, changedAt: at, goalId: goal.id }] : []
    let item = matchSubject(text, state.items)
    if (!item && other.length && matchSubject(text, other)) { item = other[0]; state.items.push(item!) }
    if (!item && refersToFocus(text)) item = oldFocus
    if (item) {
      const day = targetDay(text, at)
      const rescheduled = moved.test(text) || reopened.test(text)
      item.changedAt = at; item.changed = true
      item.revision = text
      if (rescheduled && (day || (reopened.test(text) && !uncertainTime(text)))) {
        delete item.closed
        if (day) item.due = day
        else delete item.due
      } else item.closed = true
      state.focus = item.request
    }
  } else if (!update && undertaking.test(text) && !negated.test(text)) {
    let item = state.items.find(i => i.request === text)
    if (!item) { item = { request: text, at, changedAt: at }; state.items.push(item) }
    else if (item.closed) { item.changed = true; item.changedAt = at; delete item.closed; delete item.revision }
    const due = targetDay(text, at)
    if (due) item.due = due
    if (uncertainTime(text)) item.closed = true
    if (goal && matchSubject(goal.title, [item])) item.goalId = goal.id
    state.focus = text
  } else if (!update) {
    const mentioned = matchSubject(text, state.items.filter(i => !i.closed))
    if (mentioned) state.focus = mentioned.request
  }
  state.items = state.items.slice(-LIMIT)
}

export function commitmentText(item: ChatCommitment): string {
  if (!item.revision) return item.request
  // Keep old dates out of the model's input. Both excerpts remain the person's words.
  const subject = item.request.replace(relative, '…').replace(timePart, '…')
  return subject + '\n' + item.revision
}
