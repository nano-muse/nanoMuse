/**
 * The rooms, from inside a chat: the tools that let the agent write into the
 * person's Goals, Feed and Library (`goals_room_update`, `feed_post`, `library_add`),
 * and the prompt context that tells it what the goals are, so "how is my
 * flight-price goal doing?" needs no room open. A preset row, like Reach; it
 * needs the rooms service (`dsh-nanomuse/rooms`) and does nothing without it.
 */
import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type {} from '@deepseek-ai/dsh-system-prompt'
import type {} from './cloud.ts'
import type {} from './rooms.ts'
import { AREAS, languageName } from './rooms.ts'

export const name = 'nanomuse-rooms-tools'
export const inject = ['tools', 'nanomuseRooms', 'nanomuseCloud']

export function apply(ctx: Context): void {
  const rooms = ctx.nanomuseRooms

  ctx.effect(
    () =>
      ctx.tools.register(
        defineTool({
          name: 'goals_room_update',
          description: "Update one of the person's goals in their Goals room (nanoMuse's room, not this session's own goal — that is update_goal): the one-line status, a timeline entry, the title, or mark it done/paused/tracking. Call it whenever something happens on a goal worth noting — a check done, a price seen, a step finished. The goals and their ids are in your context.",
          parameters: {
            goal_id: { type: 'string', required: true, description: 'The goal id from your context, or its exact title.' },
            summary: { type: 'string', description: "The goal's status in one line, as it should read under the title (e.g. 'Lowest fare today USD 879.90, still above the ¥4,000 line')." },
            activity_title: { type: 'string', description: 'A timeline entry, one line (what happened).' },
            activity_text: { type: 'string', description: 'The entry’s detail, one or two sentences.' },
            title: { type: 'string', description: 'A better title for the goal.' },
            status: { type: 'string', description: 'tracking, done or paused.' },
          },
          output: {
            schema: { type: 'object', properties: { goal_id: { type: 'string' }, title: { type: 'string' }, status: { type: 'string' } }, additionalProperties: false },
            render: (_args, value) => [{ type: 'text', text: `Goal "${value.title}" updated (${value.status}).` }],
          },
          async execute(args) {
            const goal = await rooms.updateGoal(args.goal_id, {
              ...(args.summary ? { summary: args.summary } : {}),
              ...(args.title ? { title: args.title } : {}),
              ...(args.status ? { status: args.status } : {}),
              ...(args.activity_title ? { activity: { title: args.activity_title, text: args.activity_text ?? '' } } : {}),
            })
            return { goal_id: goal.id, title: goal.title, status: goal.status }
          },
          presentCall: (args) => ({ card: 'generic', title: `Update goal ${args.goal_id || ''}`, kind: 'other', rawInput: args }),
        }),
      ),
    'nanomuse rooms: goals_room_update',
  )

  ctx.effect(
    () =>
      ctx.tools.register(
        defineTool({
          name: 'feed_post',
          description: "Write a post into the person's Feed (their 动态 room): something they asked you to put there, a digest you made, a finding worth keeping. Markdown body, links inline. Not for ordinary replies.",
          parameters: {
            title: { type: 'string', required: true, description: 'At most 12 words.' },
            body: { type: 'string', required: true, description: '60-200 words of Markdown; no heading.' },
            area: { type: 'string', description: `One of ${AREAS.join(', ')}.` },
            emoji: { type: 'string', description: 'One emoji that fits.' },
            image: { type: 'string', description: 'A direct https image URL to show with it, if there is one.' },
          },
          output: {
            schema: { type: 'object', properties: { id: { type: 'string' }, title: { type: 'string' } }, additionalProperties: false },
            render: (_args, value) => [{ type: 'text', text: `Posted to the feed: ${value.title}` }],
          },
          async execute(args) {
            const post = await rooms.addPost({ title: args.title, body: args.body, ...(args.area ? { area: args.area } : {}), ...(args.emoji ? { emoji: args.emoji } : {}), ...(args.image ? { image: args.image } : {}) })
            return { id: post.id, title: post.title }
          },
          presentCall: (args) => ({ card: 'generic', title: `Post to the feed: ${args.title || ''}`, kind: 'other', rawInput: args }),
        }),
      ),
    'nanomuse rooms: feed_post',
  )

  ctx.effect(
    () =>
      ctx.tools.register(
        defineTool({
          name: 'library_add',
          description: "Put a file into the person's Library (their 资源库 room): a document, a web page, an image, a video or audio you made or found for them. `present` does this too for files you deliver at the end of a task; use this for files you want listed without delivering them.",
          parameters: {
            path: { type: 'string', required: true, description: 'Absolute path, or relative to the working directory.' },
            description: { type: 'string', description: 'What it is, in a few words.' },
          },
          output: {
            schema: { type: 'object', properties: { id: { type: 'string' }, name: { type: 'string' }, kind: { type: 'string' } }, additionalProperties: false },
            render: (_args, value) => [{ type: 'text', text: `In the Library: ${value.name} (${value.kind}).` }],
          },
          async execute(args, exec) {
            const item = await rooms.addToLibrary(args.path, args.description ?? '', exec.agent?.session.id ?? '', exec.agent?.session.header.cwd)
            if (!item) throw new Error(`No file at ${args.path}.`)
            return { id: item.id, name: item.name, kind: item.kind }
          },
          presentCall: (args) => ({ card: 'generic', title: `Add to the Library: ${args.path || ''}`, kind: 'other', rawInput: args }),
        }),
      ),
    'nanomuse rooms: library_add',
  )

  ctx.effect(
    () =>
      ctx.tools.register(
        defineTool({
          name: 'remember',
          description: "Keep one fact about the person for every later chat (their Memory): a preference, a name, a routine, a decision they made. One line, in their words' language. Use it when they tell you something they will expect you to know next time; not for the task at hand.",
          parameters: {
            text: { type: 'string', required: true, description: 'The fact, one line, at most 400 characters.' },
          },
          output: {
            schema: { type: 'object', properties: { id: { type: 'string' }, text: { type: 'string' } }, additionalProperties: false },
            render: (_args, value) => [{ type: 'text', text: `Remembered: ${value.text}` }],
          },
          async execute(args) {
            const item = await rooms.remember(args.text, 'agent')
            if (!item) throw new Error('Nothing to remember.')
            return { id: item.id, text: item.text }
          },
          presentCall: (args) => ({ card: 'generic', title: `Remember: ${(args.text || '').slice(0, 60)}`, kind: 'other', rawInput: args }),
        }),
      ),
    'nanomuse rooms: remember',
  )

  ctx.effect(
    () =>
      ctx.tools.register(
        defineTool({
          name: 'draw_new_look',
          description: "Open the avatar studio on the person's screen with a description of the new look they asked for (\"change your avatar to an orange cat with a scarf\"). Four candidates are drawn there and they pick one; you do not draw the pictures yourself. Call it only when they ask for a new look.",
          parameters: {
            description: { type: 'string', required: true, description: 'The character, in a few words, in the language they used.' },
            style: { type: 'string', description: 'muse (default), flat, clay, watercolor, pixel, line or sticker — only when they named one.' },
          },
          output: {
            schema: { type: 'object', properties: { opened: { type: 'boolean' } }, additionalProperties: false },
            render: () => [{ type: 'text', text: 'The avatar studio is open on their screen; they pick one of four candidates there.' }],
          },
          async execute(args) {
            rooms.requestStudio(args.description, args.style ?? 'muse')
            return { opened: true }
          },
          presentCall: (args) => ({ card: 'generic', title: `New look: ${(args.description || '').slice(0, 60)}`, kind: 'other', rawInput: args }),
        }),
      ),
    'nanomuse rooms: draw_new_look',
  )

  ctx.inject(['systemPrompt'], (ctx) => {
    // The first conversation (C4): what the model is told for the chat it is bound to, by
    // phase — nothing anywhere else, nothing once it is over. The assembly names its agent.
    ctx.effect(
      () =>
        ctx.systemPrompt.context({
          name: 'nanomuse-firstrun',
          order: 56,
          text: (context) => rooms.firstRunAddendum((context as { agent?: { session?: { id?: string } } }).agent?.session?.id),
        }),
      'nanomuse rooms: first conversation context',
    )
    ctx.effect(
      () =>
        ctx.systemPrompt.context({
          name: 'nanomuse-rooms',
          order: 55,
          text: () => {
            const goals = rooms.goals
            const lines: string[] = []
            const persona = rooms.persona
            if (persona) lines.push('Who you are, as the person wrote it in your IDENTITY.md and SOUL.md (follow it):', persona, '')
            if (goals.length) {
              lines.push("The person's goals (their Goals room; update them with goals_room_update, or end a check with one fenced block tagged `nanomuse-goal-update` holding {\"goal_id\", \"progress\": 0-100, \"status\": \"on_track|attention|done\", \"note\"} — the app turns it into a card):")
              for (const goal of goals.slice(0, 12)) lines.push(`- ${goal.id} · ${goal.title} (${goal.category}, ${goal.status}${goal.progress >= 0 ? `, ${goal.progress}%` : ''})${goal.summary ? `: ${goal.summary}` : ''}`)
            } else {
              lines.push('The person has no goals in their Goals room yet; when they state a long-term aim, offer to track it there. They create one from the room ("Create goal › category"), or you can, when they agree: ask what, why and by when, how often to check, then write EXACTLY ONE fenced block tagged `nanomuse-goal` with {"title", "why", "category", "check_every_hours" (0 = daily), "check_time": "HH:MM", "steps": [...], "first_check"} — the app makes the goal, its chat and its checks from it, and shows it as a card. Do not describe the block.')
            }
            if (rooms.feedInstructions) lines.push(`What the person wants in their Feed: ${rooms.feedInstructions.slice(0, 300)}`)
            const memory = rooms.memory
            if (memory.length) {
              lines.push('', 'What you remember about the person (their Memory; add to it with remember):')
              for (const item of memory.slice(-60)) lines.push(`- ${item.text}`)
            } else {
              lines.push('', 'You remember nothing about the person yet; when they tell you something they will expect you to know next time, keep it with remember.')
            }
            // the words under the face: the person watches the step's own description there
            lines.push('', `Where a tool takes a \`description\` or \`step\` argument (bash, pwsh, run_code, the computer_* tools), write there what the step does for the person, in ${languageName(rooms.lang)}, in a few words ("打开携程网站", "Check the login page") — it is shown under your face while the tool runs. Fill it in on every such call.`)
            return lines.join('\n')
          },
        }),
      'nanomuse rooms: prompt context',
    )
  })
}
