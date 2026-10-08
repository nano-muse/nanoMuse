// The first conversation's phase machine and its naming block, as the phone's tests drive them
// (FirstConversationTest.kt), plus the setup pages' rule for when they are due.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { cleanName, parseNamingBlock } from '../lib/fences.js'
import {
  addressMemory, afterTurn, boundTo, builtInSuggestions, currentSuggestions, dismissChooser, dotOf, FIRST_RUN_EMPTY, firstRunNeeded,
  introLines, pickName, promptAddendum, readFirstRun, stageOf, startConversation,
} from '../lib/firstrun.js'

// ---- the block (the phone's cases) ------------------------------------------------------

test('an address block carries the address and two suggestions', () => {
  const reply = '好的，Lin，记住了！那我呢——你想叫我什么？\n\n```nanomuse-naming\n{"user_address": "Lin", "suggest": ["豆丁", "小满"]}\n```'
  const b = parseNamingBlock(reply)
  assert.ok(b)
  assert.equal(b.addressGiven, true)
  assert.equal(b.userAddress, 'Lin')
  assert.deepEqual(b.suggestions, ['豆丁', '小满'])
  assert.equal(b.agentName, null)
})

test('no address wanted is still a step forward', () => {
  const b = parseNamingBlock('Fine — no name then. What would you like to call me?\n```nanomuse-naming\n{"user_address": null, "suggest": ["Pip", "Wren"]}\n```')
  assert.ok(b)
  assert.equal(b.addressGiven, true)
  assert.equal(b.userAddress, null)
  assert.deepEqual(b.suggestions, ['Pip', 'Wren'])
})

test('a detour has no block and changes nothing', () => {
  assert.equal(parseNamingBlock('今天上海多云，22 度左右。对了——我该怎么称呼你？'), null)
  assert.equal(parseNamingBlock(null), null)
  assert.equal(parseNamingBlock(undefined), null)
  assert.equal(parseNamingBlock('```nanomuse-naming\nnot json\n```'), null)
})

test('the agent name block names the agent', () => {
  const b = parseNamingBlock('豆丁，我喜欢这个名字。\n\n- …\n\n```nanomuse-naming\n{"agent_name": "豆丁"}\n```')
  assert.ok(b)
  assert.equal(b.addressGiven, false)
  assert.equal(b.agentName, '豆丁')
  assert.deepEqual(b.suggestions, [])
})

test('names are cleaned and bounded', () => {
  assert.equal(cleanName('「豆丁」。'), '豆丁')
  assert.equal(cleanName(' "Pip" '), 'Pip')
  assert.equal(cleanName(''), null)
  assert.equal(cleanName('a name that is far too long to be a name'), null)
  assert.equal(cleanName('two\nlines'), null)
  assert.equal(cleanName(42), null)
})

test('the last block wins and suggestions are capped', () => {
  const text = '```nanomuse-naming\n{"agent_name": "A"}\n```\nlater\n```nanomuse-naming\n{"user_address": "Kai", "suggest": ["a", "b", "c", "d", "a"]}\n```'
  const b = parseNamingBlock(text)
  assert.ok(b)
  assert.equal(b.userAddress, 'Kai')
  assert.deepEqual(b.suggestions, ['a', 'b', 'c'])
  assert.equal(b.agentName, null)
})

// ---- the phases --------------------------------------------------------------------------

const fresh = () => startConversation({ ...FIRST_RUN_EMPTY, suggestions: [] }, 'sess-1', 1000)

test('Start binds the chat, marks the setup done and opens with the question', () => {
  const s = fresh()
  assert.equal(s.phase, 'ask_user_name')
  assert.equal(s.sessionId, 'sess-1')
  assert.equal(s.done, true)
  assert.equal(s.startedAt, 1000)
  assert.ok(boundTo(s, 'sess-1'))
  assert.equal(boundTo(s, 'sess-2'), false)
  // a second Start keeps the phase
  const again = startConversation({ ...s, phase: 'ask_agent_name' }, 'sess-1')
  assert.equal(again.phase, 'ask_agent_name')
})

test('a reply without a block leaves the phase alone; the address moves it to the chooser', () => {
  const s = fresh()
  const detour = afterTurn(s, 'It is 22° in Shanghai. So — what should I call you?')
  assert.equal(detour.state, s)
  assert.equal(detour.showCard, false)
  const named = afterTurn(s, 'Lin it is. What would you like to call me?\n```nanomuse-naming\n{"user_address": "Lin", "suggest": ["Pip", "Wren"]}\n```')
  assert.equal(named.state.phase, 'ask_agent_name')
  assert.equal(named.state.userAddress, 'Lin')
  assert.deepEqual(named.state.suggestions, ['Pip', 'Wren'])
  assert.equal(named.showCard, true)
  assert.equal(named.addressGiven, 'Lin')
})

test('"no address" still moves on, with the built-in names when none were suggested', () => {
  const s = fresh()
  const out = afterTurn(s, 'Fine.\n```nanomuse-naming\n{"user_address": null}\n```')
  assert.equal(out.state.phase, 'ask_agent_name')
  assert.equal(out.state.userAddress, null)
  assert.equal(out.addressGiven, null)
  assert.equal(currentSuggestions(out.state, 'en').length, 2)
})

test('typing a name ends the ritual in the same turn; picking a chip goes through named', () => {
  const asking = afterTurn(fresh(), '```nanomuse-naming\n{"user_address": "Lin", "suggest": ["Pip", "Wren"]}\n```').state
  const typed = afterTurn(asking, 'Juno it is.\n```nanomuse-naming\n{"agent_name": "Juno"}\n```')
  assert.equal(typed.state.phase, 'done')
  assert.equal(typed.state.chosen, 'Juno')
  assert.equal(typed.named, 'Juno')
  assert.equal(typed.showCard, false)
  // a detour while the chooser is up keeps it up
  const still = afterTurn(asking, 'Sure, 2 + 2 is 4. And my name?')
  assert.equal(still.state.phase, 'ask_agent_name')
  assert.equal(still.showCard, true)
  // the chip
  const picked = pickName(asking, 'Wren')
  assert.ok(picked)
  assert.equal(picked.phase, 'named')
  assert.equal(picked.chosen, 'Wren')
  assert.equal(afterTurn(picked, 'Wren, then. Here is what I can do…').state.phase, 'done')
  // a pick outside the chooser is refused
  assert.equal(pickName(fresh(), 'Pip'), null)
  assert.equal(pickName(typed.state, 'Pip'), null)
})

test('dismissing the chooser ends the ritual; elsewhere it is a no-op', () => {
  const asking = afterTurn(fresh(), '```nanomuse-naming\n{"user_address": "Lin"}\n```').state
  assert.equal(dismissChooser(asking).phase, 'done')
  const s = fresh()
  assert.equal(dismissChooser(s), s)
})

test('the built-in names are two, from the pool of the language, the same for the same chat', () => {
  const a = builtInSuggestions('sess-1', 'en')
  const b = builtInSuggestions('sess-1', 'en-US')
  assert.deepEqual(a, b)
  assert.equal(a.length, 2)
  assert.notEqual(a[0], a[1])
  for (const n of a) assert.ok(['Pip', 'Wren', 'Juno', 'Remy', 'Tilly', 'Milo', 'Sol', 'Fig'].includes(n))
  for (const n of builtInSuggestions('sess-1', 'zh-CN')) assert.ok(['豆丁', '小满', '团团', '叮叮', '小北', '一一', '小竹', '阿岳'].includes(n))
  // a different chat may deal differently; over a few seeds both orders appear
  const seen = new Set(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map((seed) => builtInSuggestions(seed, 'en').join('/')))
  assert.ok(seen.size > 1)
})

test('the addendum follows the phase and quotes the opening; nothing once over', () => {
  const s = fresh()
  const ask = promptAddendum(s, 'en', 'nanoMuse')
  assert.ok(ask.startsWith('First conversation. The app already showed the user this opening'))
  for (const line of introLines('en')) assert.ok(ask.includes(line.split('\n')[0]))
  assert.ok(ask.includes('```nanomuse-naming'))
  assert.ok(ask.includes('"user_address"'))
  const asking = afterTurn(s, '```nanomuse-naming\n{"user_address": "Lin", "suggest": ["Pip", "Wren"]}\n```').state
  const chooser = promptAddendum(asking, 'en', 'nanoMuse')
  assert.ok(chooser.includes('"Pip", "Wren"'))
  assert.ok(chooser.includes('meaning "Pip"'))
  assert.ok(chooser.includes('The user goes by "Lin"'))
  assert.ok(chooser.includes('"agent_name"'))
  assert.ok(chooser.includes('on this computer'))
  assert.ok(!chooser.includes('Linux sandbox'))
  const named = promptAddendum(pickName(asking, 'Wren'), 'en', 'Wren')
  assert.ok(named.includes('The user just named you "Wren"'))
  assert.equal(promptAddendum({ ...asking, phase: 'done' }, 'en', 'Wren'), null)
  assert.equal(promptAddendum({ ...FIRST_RUN_EMPTY, suggestions: [] }, 'en', 'x'), null)
})

test('the opening speaks of the computer, in both languages', () => {
  const en = introLines('en')
  assert.equal(en.length, 3)
  assert.ok(en[0].includes('lives on your computer'))
  assert.ok(!en[1].includes('phone'))
  assert.ok(en[2].includes('what should I call you'))
  const zh = introLines('zh-CN')
  assert.ok(zh[0].includes('电脑'))
  assert.ok(!zh[1].includes('手机'))
})

test('the memory line is written once under About the user and replaced on a change', () => {
  assert.equal(addressMemory('', 'Lin'), '## About the user\n- Call them: Lin\n')
  const first = addressMemory('# Notes\n- likes tea\n', 'Lin')
  assert.ok(first.endsWith('## About the user\n- Call them: Lin\n'))
  assert.ok(first.startsWith('# Notes\n- likes tea'))
  const changed = addressMemory(first, 'Kai')
  assert.ok(changed.includes('- Call them: Kai'))
  assert.ok(!changed.includes('- Call them: Lin'))
  assert.equal(changed.split('About the user').length, 2)
})

// ---- when the pages are due ----------------------------------------------------------------

test('needed: the phone\'s rule — signed in, a model, and chats or Start', () => {
  assert.equal(firstRunNeeded({ signedIn: false, hasModel: false, hasSessions: false, done: false }), true)
  assert.equal(firstRunNeeded({ signedIn: true, hasModel: true, hasSessions: false, done: false }), true)
  assert.equal(firstRunNeeded({ signedIn: true, hasModel: true, hasSessions: true, done: false }), false)
  assert.equal(firstRunNeeded({ signedIn: true, hasModel: true, hasSessions: false, done: true }), false)
  // a ready install that never pressed Start still gets the pages ("ready" only skips the account pages)
  assert.equal(firstRunNeeded({ signedIn: true, hasModel: true, hasSessions: false, done: false }), true)
  assert.equal(firstRunNeeded({ signedIn: true, hasModel: false, hasSessions: true, done: true }), true)
})

test('the pages come in the phone\'s order and light the dots the same way', () => {
  const base = { signedIn: false, hasModel: false, freshAccount: false, passwordSeen: false, sourceChosen: null, modelsSkipped: false, gated: true, permissionsSeen: false }
  assert.equal(stageOf(base), 'welcome')
  // a fresh account owes the password page, once
  assert.equal(stageOf({ ...base, signedIn: true, hasModel: true, freshAccount: true }), 'password')
  assert.equal(stageOf({ ...base, signedIn: true, hasModel: true, freshAccount: true, passwordSeen: true }), 'source')
  // signed in: which model answers, then the permissions, then Meet
  assert.equal(stageOf({ ...base, signedIn: true, hasModel: true }), 'source')
  assert.equal(stageOf({ ...base, signedIn: true, hasModel: true, sourceChosen: 'cloud' }), 'permissions')
  assert.equal(stageOf({ ...base, signedIn: true, hasModel: true, sourceChosen: 'cloud', gated: false }), 'meet')
  assert.equal(stageOf({ ...base, signedIn: true, hasModel: true, sourceChosen: 'cloud', permissionsSeen: true }), 'meet')
  // one's own key: the models page until a model is there or it is skipped
  assert.equal(stageOf({ ...base, signedIn: true, hasModel: false, sourceChosen: 'own' }), 'models')
  assert.equal(stageOf({ ...base, signedIn: true, hasModel: false, sourceChosen: 'own', modelsSkipped: true }), 'permissions')
  assert.equal(stageOf({ ...base, signedIn: true, hasModel: true, sourceChosen: 'own' }), 'permissions')
  // a desktop with a key of its own and no account: "ready" skips the account pages
  assert.equal(stageOf({ ...base, hasModel: true }), 'source')
  assert.equal(stageOf({ ...base, hasModel: true, sourceChosen: 'own' }), 'permissions')
  // Welcome's second door, as on the phone: the models page with no account; Skip there with no key is Welcome again
  assert.equal(stageOf({ ...base, sourceChosen: 'own' }), 'models')
  assert.equal(stageOf({ ...base, sourceChosen: 'own', modelsSkipped: true }), 'welcome')
  assert.equal(stageOf({ ...base, sourceChosen: 'cloud' }), 'welcome')
  assert.deepEqual(['welcome', 'password', 'source', 'models', 'permissions', 'meet'].map(dotOf), [0, 0, 0, 0, 1, 2])
})

test('the file is read tolerantly', () => {
  const s = readFirstRun({ phase: 'ask_agent_name', sessionId: 'x', suggestions: ['A', '', 3, 'B', 'C', 'D'], done: 'yes', chosen: null })
  assert.equal(s.phase, 'ask_agent_name')
  assert.deepEqual(s.suggestions, ['A', 'B', 'C'])
  assert.equal(s.done, false)
  assert.equal(s.sessionId, 'x')
  assert.equal(readFirstRun({ phase: 'bogus' }).phase, 'none')
  assert.deepEqual(readFirstRun(undefined), { ...FIRST_RUN_EMPTY, suggestions: [] })
})
