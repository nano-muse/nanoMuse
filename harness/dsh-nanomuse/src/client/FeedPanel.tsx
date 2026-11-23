/**
 * The Feed (动态): the posts the agent wrote for the person, newest first — an
 * emoji mark, the title and when, the body with its links, a picture when
 * the story had one, and under each a heart and "Discuss", which opens a chat
 * about it. The sliders at the top right hold the feed's instructions (what
 * the person wants to read here) and a "write a batch now".
 */
import { failureText } from './api.ts'
import { createElement as h, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import type { Translate } from './api.ts'
import { IconComment, IconCopy, IconFeed, IconHeart, IconRefresh, IconSliders } from './icons.tsx'
import { FEED_PANEL } from './panels.ts'
import { setPrefs, usePrefs } from './prefs.ts'
import { markFeedSeen, nav, roomsCall, useRooms, type FeedPost, type FeedRoutine } from './rooms.ts'
import { ago, Empty, Markdown, MoreButton, RoomToggle, Sheet } from './ui.tsx'

export function makeFeedPanel(t: Translate) {
  return function FeedPanel(): ReactNode {
    const rooms = useRooms()
    const prefs = usePrefs()
    const [quiet, setQuiet] = useState(false)
    const [settings, setSettings] = useState(false)
    const [error, setError] = useState<string | undefined>()
    // An open window drops date-sensitive cards at the host's local midnight, even offline.
    const [, setExpiryTick] = useState(0)
    const now = Date.now()
    const posts = rooms.feed.posts.filter((post) => (!post.preparation || post.preparation.expiresAt > now) && (!post.goalId || (post.goalExpiresAt ?? 0) > now))
    const newest = posts[0]?.at ?? 0
    const reminder = posts.find((post) => post.goalId)
    const expiry = posts.map(p => p.preparation?.expiresAt ?? p.goalExpiresAt).filter((at): at is number => at !== undefined).sort((a, b) => a - b)[0]
    useEffect(() => {
      if (!expiry) return
      const timer = window.setTimeout(() => setExpiryTick((n) => n + 1), Math.max(0, expiry - Date.now()))
      return () => window.clearTimeout(timer)
    }, [expiry])
    const displayPosts = reminder ? [reminder, ...posts.filter((post) => post.id !== reminder.id)] : posts
    useEffect(() => { if (newest) markFeedSeen() }, [newest])
    // opening the Feed makes sure the daily routine exists (C5: 08:00, once, on the host)
    useEffect(() => { roomsCall('feed/open', {}).catch(() => undefined) }, [])
    const routine = rooms.feed.routine

    const fail = (err: unknown) => setError(failureText(t, err))
    const prepare = () => {
      setQuiet(false)
      setError(undefined)
      roomsCall<{ status: string }>('feed/prepare', {}).then(result => setQuiet(result.status === 'quiet')).catch(fail)
    }
    const refresh = () => { setError(undefined); roomsCall('feed/refresh', {}).catch(fail) }
    const discuss = (post: FeedPost) => {
      setError(undefined)
      // the chat opens beside the feed, the post's words already in it (Muse's 讨论)
      roomsCall<{ sessionId: string }>('feed/discuss', { id: post.id }).then(({ sessionId }) => { nav.openSession(sessionId); nav.split(FEED_PANEL) }).catch(fail)
    }

    return h('div', { className: 'nm-room' },
      h('div', { className: 'nm-room-top', 'data-window-drag': true }),
      h('div', { className: 'nm-room-head' },
        h(RoomToggle, { t, panel: FEED_PANEL }),
        h('h1', { className: 'nm-room-title' }, t('railFeed')),
        h('div', { className: 'nm-room-actions' },
          rooms.busy.feed ? h('span', { className: 'nm-room-busy' }, h('span', { className: 'nm-spinner nm-spinner-sm' }), t('feedWriting')) : null,
          rooms.ready && posts.length > 0 ? h('button', { type: 'button', className: 'nm-round-btn', title: t('feedPrepare'), 'aria-label': t('feedPrepare'), disabled: rooms.busy.feed, onClick: prepare }, h(IconRefresh, { size: 18 })) : null,
          h('button', { type: 'button', className: 'nm-round-btn', title: t('feedSettings'), 'aria-label': t('feedSettings'), onClick: () => setSettings(true) }, h(IconSliders, { size: 18 })))),
      h('div', { className: 'nm-room-body' },
        h('div', { className: 'nm-room-inner nm-feed' },
          error ? h('div', { className: 'nm-room-error' }, error) : null,
          quiet && !rooms.busy.feed ? h('p', { role: 'status', className: 'nm-sheet-fine' }, t('feedQuiet')) : null,
          // the phone's intro card, until "Got it"
          !prefs.feedIntroSeen
            ? h('div', { className: 'nm-feed-intro', role: 'note' },
                h('div', { className: 'nm-feed-intro-title' }, t('feedIntroTitle')),
                h('p', { className: 'nm-feed-intro-body' }, t('feedIntroDesc')),
                h('div', { className: 'nm-feed-intro-actions' },
                  h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: () => setSettings(true) }, t('feedIntroEdit')),
                  h('button', { type: 'button', className: 'nm-pill nm-pill-sm', onClick: () => setPrefs({ feedIntroSeen: true }) }, t('feedIntroGotIt'))))
            : null,
          posts.length === 0
            ? h(Empty, { icon: h(IconFeed, { size: 28 }), text: rooms.busy.feed ? t('feedWriting') : t('feedEmptyTitle') },
                h('p', { className: 'nm-empty-sub' }, !routine.on ? t('feedPaused') : rooms.ready ? t('feedEmptyBody', { time: routine.time }) : t('feedRoutineNeedsModel')),
                rooms.ready
                  ? h('div', { className: 'nm-feed-how' },
                      h('div', { className: 'nm-feed-how-title' }, t('feedEmptyHowTitle')),
                      h('p', null, t('feedEmptyHowBody')))
                  : null,
                rooms.ready && !rooms.busy.feed ? h('button', { type: 'button', className: 'nm-pill nm-pill-sm', onClick: prepare }, t('feedPrepare')) : null)
            : displayPosts.map((post) => h(PostCard, { key: post.id, t, post, lang: rooms.lang, onDiscuss: () => discuss(post), onFail: fail })))),
      settings ? h(FeedSettings, { key: routine.checkInScope, t, instructions: rooms.feed.instructions, routine, busy: rooms.busy.feed, ready: rooms.ready, onClose: () => setSettings(false), onRefresh: refresh }) : null)
  }
}

function PostCard({ t, post, lang, onDiscuss, onFail }: { t: Translate; post: FeedPost; lang: string; onDiscuss(): void; onFail(err: unknown): void }): ReactNode {
  const [hideImage, setHideImage] = useState(false)
  const [copied, setCopied] = useState(false)
  const like = () => { roomsCall('feed/like', { id: post.id, on: !post.liked }).catch(onFail) }
  const remove = () => { roomsCall('feed/delete', { id: post.id }).catch(onFail) }
  const discussLabel = t(post.goalId || post.preparation ? 'goalOpenChat' : 'feedDiscuss')
  const follow = () => { onDiscuss() }
  return h('article', { className: 'nm-post' },
    h('div', { className: 'nm-post-mark', 'aria-hidden': true }, post.emoji || '✦'),
    h('div', { className: 'nm-post-main' },
      h('div', { className: 'nm-post-head' },
        h('h3', { className: 'nm-post-title' }, post.title),
        h('span', { className: 'nm-post-when' }, ago(t, post.at)),
        h(MoreButton, { label: t('more'), quiet: true, size: 26, items: [
          { id: 'discuss', label: discussLabel, onSelect: follow },
          ...(post.prompt ? [{ id: 'follow', label: t('feedFollowUp'), onSelect: follow }] : []),
          'sep',
          ...(post.goalId ? [{ id: 'mute', label: t('goalFeedMute'), onSelect: () => { roomsCall('goals/update', { id: post.goalId, feedMuted: true }).catch(onFail) } }] : []),
          { id: 'delete', label: t('feedRemove'), danger: true, onSelect: remove },
        ] })),
      post.preparation
        ? h('div', { className: 'nm-post-body' },
            h('p', { className: 'nm-sheet-fine' }, t(({ draft: 'feedDraft', checklist: 'feedChecklist', question: 'feedQuestion' } as const)[post.preparation.kind])),
            h('p', { style: { whiteSpace: 'pre-wrap' } }, post.body),
            h('details', null, h('summary', null, t('feedWhy')), h('p', null, post.preparation.why),
              h('ul', null, post.preparation.sources.map(source => h('li', { key: source.id },
                h('strong', null, t(({ goal: 'railGoals', file: 'railLibrary', memory: 'feedMemorySource', conversation: 'feedChatSource' } as const)[source.kind])), ' · ', source.title,
                source.quote === source.title ? null : h('blockquote', null, source.quote))))))
        : post.goalId
        ? h('div', { className: 'nm-post-body' }, post.body.split('\n\n').map((line, i) => h('p', { key: i }, line)))
        : h(Markdown, { text: post.body, className: 'nm-post-body' }),
      post.image && !hideImage
        ? h('div', { className: 'nm-post-images' }, h('img', { src: post.image, alt: '', loading: 'lazy', referrerPolicy: 'no-referrer', onError: () => setHideImage(true) }))
        : null,
      h('div', { className: 'nm-post-actions' },
        post.preparation && navigator.clipboard?.writeText ? h('button', { type: 'button', className: 'nm-post-action',
          onClick: () => navigator.clipboard.writeText(post.body).then(() => setCopied(true)).catch(onFail) },
          h(IconCopy, { size: 16 }), h('span', null, t(copied ? 'cnCopied' : 'cnCopy'))) : null,
        h('button', { type: 'button', className: `nm-post-action${post.liked ? ' nm-liked' : ''}`, 'aria-pressed': post.liked, 'aria-label': t('feedLike'), title: t('feedLike'), onClick: like }, h(IconHeart, { size: 18, filled: post.liked })),
        h('button', { type: 'button', className: 'nm-post-action', onClick: onDiscuss }, h(IconComment, { size: 18 }), h('span', null, discussLabel)),
        h('span', { className: 'nm-post-time-full' }, new Date(post.at).toLocaleString(lang || undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })))))
}

function FeedSettings({ t, instructions, routine, busy, ready, onClose, onRefresh }: { t: Translate; instructions: string; routine: FeedRoutine; busy: boolean; ready: boolean; onClose(): void; onRefresh(): void }): ReactNode {
  const [text, setText] = useState(instructions)
  const [on, setOn] = useState(routine.on)
  const [reading, setReading] = useState(routine.reading === true)
  const [checkIns, setCheckIns] = useState(routine.chatCheckIns === true)
  const [time, setTime] = useState(routine.time)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const save = (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    const checksChanged = checkIns !== (routine.chatCheckIns === true)
    if (checksChanged && checkIns && typeof Notification !== 'undefined' && Notification.permission === 'default') {
      void Notification.requestPermission().catch(() => undefined)
    }
    const routineChanged = checksChanged || on !== routine.on || time !== routine.time || reading !== (routine.reading === true)
    Promise.all([
      roomsCall('feed/instructions', { text }),
      routineChanged ? roomsCall('feed/routine', { on, time, reading, ...(checksChanged ? { chatCheckIns: checkIns, checkInScope: routine.checkInScope } : {}) }) : Promise.resolve(undefined),
    ]).then(onClose).catch((err: unknown) => setError(failureText(t, err))).finally(() => setSaving(false))
  }
  return h(Sheet, { title: t('feedSettingsTitle'), closeLabel: t('close'), onClose,
    footer: h('div', { className: 'nm-sheet-actions' },
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', disabled: busy || !ready, onClick: () => { onRefresh(); onClose() } }, h(IconRefresh, { size: 14 }), ' ', t('feedWriteNow')),
      h('span', { style: { flex: 1 } }),
      h('button', { type: 'button', className: 'nm-pill nm-pill-ghost nm-pill-sm', onClick: onClose }, t('cancel')),
      h('button', { type: 'submit', form: 'nm-feed-settings', className: 'nm-pill nm-pill-sm', disabled: saving }, t('save'))) },
    h('form', { id: 'nm-feed-settings', onSubmit: save, className: 'nm-sheet-form' },
      h('p', { className: 'nm-sheet-lead' }, t('feedSettingsLead')),
      h('textarea', { className: 'nm-textarea', rows: 6, value: text, placeholder: t('feedSettingsPlaceholder'), maxLength: 2000, onChange: (e: FormEvent<HTMLTextAreaElement>) => setText(e.currentTarget.value), 'data-modal-autofocus': true }),
      h('p', { className: 'nm-sheet-fine' }, t('feedSettingsFine')),
      // the daily routine (C5): on or off, and when
      h('label', { className: 'nm-feed-routine' },
        h('input', { type: 'checkbox', checked: on, onChange: (e: FormEvent<HTMLInputElement>) => setOn(e.currentTarget.checked) }),
        h('span', { className: 'nm-feed-routine-label' }, t('feedRoutineSwitch')),
        h('span', { className: 'nm-feed-routine-time' },
          h('input', { type: 'time', className: 'nm-field nm-field-time', value: time, disabled: !on, 'aria-label': t('feedRoutineTime', { time }), onChange: (e: FormEvent<HTMLInputElement>) => { if (/^\d{2}:\d{2}$/.test(e.currentTarget.value)) setTime(e.currentTarget.value) } }))),
      h('label', { className: 'nm-feed-routine' },
        h('input', { type: 'checkbox', checked: reading, disabled: !on, onChange: (e: FormEvent<HTMLInputElement>) => setReading(e.currentTarget.checked) }),
        h('span', null, t('feedReading'))),
      h('label', { className: 'nm-feed-routine' },
        h('input', { type: 'checkbox', checked: checkIns, disabled: !on || !routine.checkInScope, onChange: (e: FormEvent<HTMLInputElement>) => setCheckIns(e.currentTarget.checked) }),
        h('span', null, t('feedChatCheckIns'))),
      !ready ? h('p', { className: 'nm-sheet-fine' }, t('feedRoutineNeedsModel')) : null,
      error ? h('div', { className: 'nm-room-error' }, error) : null))
}
