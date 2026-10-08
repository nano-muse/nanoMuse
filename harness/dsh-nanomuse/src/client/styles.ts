/**
 * The Muse look, as one stylesheet the plugin puts in the page's head. Three
 * layers: the harness's `--dsw-*` design tokens re-bound to the Muse palette
 * (so every harness surface — menus, dialogs, cards — follows without being
 * touched); the harness's conversation restyled through its stable DOM hooks
 * (`data-composer-card`, `data-chat-flow-kind`, `data-approval-key`…) into
 * Muse's pill composer, tinted user bubbles and grey agent bubbles — only
 * while the Developer switch is off (`html[data-nm-muse]`); and the `nm-*`
 * classes of the chrome we draw ourselves: the icon rail and chats column,
 * the pinned agent header, the profile drawer, the devices page, the settings
 * dialog and the first run. Everything is scoped under `html[data-nanomuse]`,
 * set by the plugin, so the harness looks like itself again the moment the
 * plugin is gone.
 *
 * The colours are the Muse desktop's, sampled: one near-black (#171717) for
 * the window, the rail, the columns and the main area alike; fields and
 * cards a step lighter (#2b2b2b / #2d2d2d); the selected row #232323; agent
 * bubbles a quiet grey; user bubbles the accent colour toned down into the
 * dark. In the light the paper is #f9f9f9, fields white, bubbles #e3e4e6.
 */

const STYLE_ID = 'nanomuse-muse-style'

/** The agent's accent, from the account's chosen colour when it has one. */
export function setAccent(color: string | undefined): void {
  const root = document.documentElement
  if (color && /^#[0-9a-f]{6}$/i.test(color)) root.style.setProperty('--nm-accent', color)
  else root.style.removeProperty('--nm-accent')
}

/** Whether the harness's own controls show (`false`: the Muse composer and column). */
export function setMuseMode(on: boolean, placeholder?: string, steps = false): void {
  const root = document.documentElement
  if (on) root.setAttribute('data-nm-muse', '')
  else root.removeAttribute('data-nm-muse')
  // "Show the agent's steps": the tool rows come back into the Muse chat
  if (steps) root.setAttribute('data-nm-steps', '')
  else root.removeAttribute('data-nm-steps')
  if (placeholder !== undefined) root.style.setProperty('--nm-placeholder', JSON.stringify(placeholder))
}

const CSS = `
html[data-nanomuse] {
  --nm-accent: #c8743a;
  --nm-blue: #2f6fd0;
  --nm-blue-hover: #2a63ba;
  --nm-rail: 66px;
  --nm-radius: 14px;
  --nm-font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
}
/* Light: paper, white fields, grey bubbles, the user's tinted with the accent. */
html[data-nanomuse] body {
  --nm-base: #f9f9f9;
  --nm-field: #ffffff;
  --nm-field-border: #e3e4e6;
  --nm-card: #ffffff;
  --nm-selected: #f0f0f1;
  --nm-hover: #f1f1f2;
  --nm-divider: #ececec;
  --nm-agent-bubble: #e9e9eb;
  --nm-user-bubble: color-mix(in srgb, var(--nm-accent) 22%, #ffffff);
  --nm-send: #111111;
  --nm-send-idle: #c9c9cc;
  --dsw-alias-bg-base: #f9f9f9;
  --dsw-alias-bg-layer-1: #f2f2f2;
  --dsw-alias-bg-layer-2: #ececec;
  --dsw-alias-bg-layer-3: #e3e4e6;
  --dsw-specific-sidebar-fill: #f9f9f9;
  --dsw-specific-bubble: #e9e9eb;
  --dsw-specific-bubble-highlight: #dedfe2;
  --dsw-specific-input-major: #ffffff;
  --dsw-alias-brand-primary: #1d1d1f;
}
/* Dark: one near-black, fields and cards a step lighter, bubbles a quiet grey. */
html[data-nanomuse] body[data-ds-dark-theme] {
  --nm-base: #171717;
  --nm-field: #2b2b2b;
  --nm-field-border: #2b2b2b;
  --nm-card: #2d2d2d;
  --nm-selected: #262626;
  --nm-hover: #222222;
  --nm-divider: #242424;
  --nm-agent-bubble: #242424;
  --nm-user-bubble: color-mix(in srgb, var(--nm-accent) 42%, #171717);
  --nm-send: #e8e8e8;
  --nm-send-idle: #3a3a3a;
  --dsw-alias-bg-base: #171717;
  --dsw-alias-bg-layer-1: #1d1d1d;
  --dsw-alias-bg-layer-2: #232323;
  --dsw-alias-bg-layer-3: #2d2d2d;
  --dsw-specific-sidebar-fill: #171717;
  --dsw-specific-bubble: #242424;
  --dsw-specific-bubble-highlight: #2f2f2f;
  --dsw-specific-input-major: #2b2b2b;
  --dsw-alias-brand-primary: #f2f2f4;
}
html[data-nanomuse] body { font-family: var(--nm-font); }

/* ---- shared controls --------------------------------------------------- */
.nm-pill { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 40px; padding: 0 22px; border: 0; border-radius: 999px; background: var(--nm-blue); color: #fff; font: inherit; font-size: 14px; font-weight: 500; cursor: pointer; transition: background 120ms, opacity 120ms; }
.nm-pill:hover:not(:disabled) { background: var(--nm-blue-hover); }
.nm-pill:disabled { opacity: 0.45; cursor: default; }
.nm-pill:focus-visible { outline: 2px solid var(--nm-blue); outline-offset: 2px; }
.nm-pill-ghost { background: var(--nm-card); color: var(--dsw-alias-label-primary); box-shadow: inset 0 0 0 1px var(--nm-field-border); }
.nm-pill-ghost:hover:not(:disabled) { background: var(--nm-selected); }
.nm-pill-sm { min-height: 30px; padding: 0 14px; font-size: 13px; }
.nm-field { box-sizing: border-box; width: 100%; height: 44px; padding: 0 14px; border: 1px solid var(--nm-field-border); border-radius: 12px; background: var(--nm-field); color: var(--dsw-alias-label-primary); font: inherit; font-size: 15px; outline: none; transition: border-color 120ms, box-shadow 120ms; }
.nm-field::placeholder { color: var(--dsw-alias-label-tertiary); }
.nm-field:focus { border-color: var(--nm-blue); box-shadow: 0 0 0 3px color-mix(in srgb, var(--nm-blue) 25%, transparent); }
.nm-seg { display: inline-flex; gap: 2px; padding: 3px; border-radius: 12px; background: var(--dsw-alias-bg-layer-2); }
.nm-seg-btn { display: inline-flex; align-items: center; justify-content: center; min-width: 44px; height: 32px; padding: 0 10px; border: 0; border-radius: 9px; background: transparent; color: var(--dsw-alias-label-secondary); font: inherit; font-size: 13px; cursor: pointer; }
.nm-seg-btn:hover { color: var(--dsw-alias-label-primary); }
.nm-seg-btn.nm-active { background: var(--nm-card); color: var(--dsw-alias-label-primary); box-shadow: 0 1px 3px rgba(0,0,0,0.18); }
.nm-spinner { width: 28px; height: 28px; border-radius: 50%; border: 3px solid color-mix(in srgb, var(--nm-blue) 25%, transparent); border-top-color: var(--nm-blue); animation: nm-spin 0.8s linear infinite; }
@keyframes nm-spin { to { transform: rotate(360deg); } }
.nm-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.nm-icon-btn { width: 30px; height: 30px; border: 0; padding: 0; border-radius: 9px; background: transparent; color: var(--dsw-alias-label-secondary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.nm-icon-btn:hover { background: var(--nm-hover); color: var(--dsw-alias-label-primary); }
.nm-icon-btn:disabled { opacity: 0.45; cursor: default; }
.nm-icon-btn-sm { width: 24px; height: 24px; border-radius: 7px; }

/* ---- sidebar: icon rail + chats column -------------------------------- */
.nm-sidebar { display: flex; height: 100%; min-height: 0; color: var(--dsw-alias-label-primary); background: var(--nm-base); }
.nm-rail { width: var(--nm-rail); flex: none; display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 10px 0 12px; box-sizing: border-box; }
.nm-rail-top { height: 12px; flex: none; }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) .nm-rail-top { height: 78px; }
.nm-rail-face { display: inline-flex; border-radius: 50%; overflow: hidden; }
/* macOS, no title bar: the empty tops of the rail, the column and the chat are drag handles.
   Windows draws its caption buttons over the top right corner (titleBarOverlay, 40px): the same
   drag handles, and the chat's header keeps clear of the buttons. Linux has its system bar. */
html:is([data-nm-platform='darwin'], [data-nm-platform='win32']) [data-window-drag], html:is([data-nm-platform='darwin'], [data-nm-platform='win32']) .nm-ob { -webkit-app-region: drag; }
html:is([data-nm-platform='darwin'], [data-nm-platform='win32']) :is([data-window-drag], .nm-ob, [data-slot="conversation.session.header"]) :is(button, a, input, select, textarea, [contenteditable], [role="button"], [role="dialog"], [role="menu"]) { -webkit-app-region: no-drag; }
/* The chat's header is not a drag region (the shell marks its <header data-window-drag>; that
   and its leading box are reset here): the only handle over the chat is .nm-header-drag, an
   empty strip above the face (MuseHeader). Chromium builds the window's drag map as
   union(drag boxes) − union(no-drag boxes), so a box that is never "drag" needs no carve-out —
   which is what kept failing for the face on macOS. The face also sits below the macOS title
   bar band (traffic lights at y 18 → ~36px), which the system handles before the page. */
html:is([data-nm-platform='darwin'], [data-nm-platform='win32']) header[data-window-drag]:has(.nm-header), html:is([data-nm-platform='darwin'], [data-nm-platform='win32']) [data-conversation-header-leading] { -webkit-app-region: initial; }
.nm-header-drag { position: absolute; left: 0; right: 0; top: 0; height: 10px; z-index: 1; }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) .nm-header-drag { height: 36px; }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) .nm-header { top: 40px; }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) .nm-header-back { top: 42px; }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) header[data-window-drag]:has(.nm-header) { min-height: 136px; }
html[data-nm-platform='win32']:not([data-nm-fullscreen]) .nm-rail-top { height: 24px; }
html[data-nm-platform='win32']:not([data-nm-fullscreen]) .nm-header-drag { height: 22px; right: 150px; }
html[data-nm-platform='win32']:not([data-nm-fullscreen]) .nm-header { top: 26px; }
html[data-nm-platform='win32']:not([data-nm-fullscreen]) .nm-header-back { top: 28px; }
html[data-nm-platform='win32']:not([data-nm-fullscreen]) header[data-window-drag]:has(.nm-header) { min-height: 122px; }
html[data-nm-platform='win32']:not([data-nm-fullscreen]) [data-slot="conversation.session.header"] > :first-child { padding-right: 150px; min-height: 40px; }
html[data-nm-platform='win32']:not([data-nm-fullscreen]) .nm-ob-pager { top: 48px; }
.nm-rail-avatar { width: 44px; height: 44px; margin: 2px 0 10px; border: 0; padding: 0; border-radius: 50%; background: transparent; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.nm-rail-avatar:focus-visible { outline: 2px solid var(--nm-accent); outline-offset: 2px; }
.nm-rail-btn { position: relative; width: 44px; height: 44px; border: 0; padding: 0; border-radius: 13px; background: transparent; color: var(--dsw-alias-label-secondary); cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background 120ms, color 120ms; }
.nm-rail-btn:hover { background: var(--nm-hover); color: var(--dsw-alias-label-primary); }
.nm-rail-btn[aria-current], .nm-rail-btn[aria-expanded="true"] { background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); }
.nm-rail-btn:focus-visible { outline: 2px solid var(--nm-accent); outline-offset: -2px; }
.nm-rail-dot { position: absolute; top: 9px; right: 9px; width: 7px; height: 7px; border-radius: 50%; background: var(--nm-accent); box-shadow: 0 0 0 2px var(--nm-base); }
.nm-rail-spacer { flex: 1; }
.nm-col { flex: 1; min-width: 0; display: flex; flex-direction: column; border-right: 1px solid var(--nm-divider); opacity: 1; transition: opacity 150ms; }
.nm-col.nm-fading { opacity: 0; }
.nm-col-top { height: 10px; flex: none; }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) .nm-col-top { height: 10px; }
.nm-col-head { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 4px 8px 4px 16px; font-size: 15px; font-weight: 600; letter-spacing: 0.01em; }
.nm-col-head-actions { display: flex; gap: 2px; }
.nm-col-body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.nm-col-body > * { min-height: 0; }
.nm-col-body > :last-child { flex: 1; }
.nm-col-foot { flex: none; display: flex; flex-direction: column; gap: 2px; padding: 6px; }
.nm-col-foot:empty { display: none; }

.nm-chats { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.nm-chats-head { flex: none; display: flex; align-items: center; gap: 4px; padding: 0 8px 8px 10px; }
.nm-chats-search { flex: 1; min-width: 0; display: flex; align-items: center; gap: 6px; height: 32px; padding: 0 10px; border-radius: 10px; background: var(--nm-field); border: 1px solid var(--nm-field-border); color: var(--dsw-alias-label-tertiary); cursor: text; }
.nm-chats-search:focus-within { border-color: var(--nm-blue); }
.nm-chats-search input { flex: 1; min-width: 0; border: 0; background: transparent; color: var(--dsw-alias-label-primary); font: inherit; font-size: 13.5px; outline: none; }
.nm-chats-search input::placeholder { color: var(--dsw-alias-label-tertiary); }
.nm-chats-search input::-webkit-search-cancel-button { -webkit-appearance: none; }
.nm-chats-list { flex: 1; min-height: 0; overflow-y: auto; padding: 0 8px 8px; display: flex; flex-direction: column; gap: 1px; }
.nm-chats-section { display: flex; align-items: center; justify-content: space-between; padding: 14px 4px 4px 10px; font-size: 13px; color: var(--dsw-alias-label-tertiary); }
.nm-chats-empty { padding: 6px 10px; font-size: 12.5px; line-height: 1.5; color: var(--dsw-alias-label-tertiary); }
.nm-chat-row { position: relative; display: flex; align-items: center; border-radius: 9px; min-height: 34px; }
.nm-chat-row:hover { background: var(--nm-hover); }
.nm-chat-row.nm-selected { background: var(--nm-selected); }
.nm-chat-open { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; height: 34px; padding: 0 8px 0 10px; border: 0; background: transparent; color: var(--dsw-alias-label-primary); font: inherit; font-size: 14px; text-align: left; cursor: pointer; border-radius: 9px; }
.nm-chat-open:focus-visible { outline: 2px solid var(--nm-accent); outline-offset: -2px; }
.nm-chat-row.nm-main .nm-chat-title { font-weight: 500; }
.nm-chat-title { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-chat-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--nm-accent); flex: none; }
.nm-chat-dot.nm-live { animation: nm-pulse 2.4s ease-in-out infinite alternate; }
.nm-chat-mark { flex: none; font-size: 12px; color: var(--dsw-alias-state-warn-primary, #d98c1f); }
.nm-chat-more { position: absolute; right: 4px; top: 50%; transform: translateY(-50%); width: 26px; height: 26px; border: 0; padding: 0; border-radius: 7px; background: transparent; color: var(--dsw-alias-label-secondary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; opacity: 0; }
.nm-chat-row:hover .nm-chat-more, .nm-chat-more:focus-visible, .nm-chat-more[aria-expanded="true"] { opacity: 1; }
.nm-chat-more:hover { background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); }
.nm-chat-row:hover .nm-chat-title { padding-right: 22px; }
.nm-chat-edit { flex: 1; min-width: 0; height: 30px; margin: 2px 4px; padding: 0 8px; border: 1px solid var(--nm-blue); border-radius: 7px; background: var(--nm-field); color: var(--dsw-alias-label-primary); font: inherit; font-size: 14px; outline: none; }
/* a turn of the conversation written on another device of the account (C8): the person's bubble on the
   right like the harness's own, the Muse's on the left, "From Pixel 8" under either (RemoteBubbles.ts) */
.nm-remote { display: flex; flex-direction: column; gap: 4px; margin: 6px 0; }
.nm-remote-user { align-items: flex-end; }
.nm-remote-assistant { align-items: flex-start; }
.nm-remote-bubble { max-width: 100%; padding: 10px 16px; border-radius: var(--dsw-radius-xl, 16px); font-size: var(--dsh-content-font-size, 14px); line-height: calc(22px + var(--dsh-content-font-delta, 0px)); white-space: pre-wrap; word-break: break-word; color: var(--dsw-alias-label-primary); }
.nm-remote-user .nm-remote-bubble { background: var(--dsw-specific-bubble, var(--nm-hover)); }
.nm-remote-assistant .nm-remote-bubble { padding-left: 0; padding-right: 0; }
.nm-remote-from { font-size: 11px; color: var(--dsw-alias-label-tertiary); padding: 0 4px; }
/* the other device is working on its last prompt (C9): a quiet line with a slow dot */
.nm-remote-working { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--dsw-alias-label-tertiary); padding: 0 4px; }
.nm-remote-working::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: currentColor; animation: nm-breathe-light 4.8s ease-in-out infinite; }
/* The breathing light: every "something is going on" light in this app breathes — 2.4 s in, 2.4 s out,
   the phone's rhythm — rather than running, sweeping or shimmering. A steady light under reduced motion. */
@keyframes nm-breathe-light { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }
/* a session with no turn of its own yet (the chat's "hero" layout centres the composer): the other
   devices' turns sit above the composer, bottom-aligned like a transcript, inside the scrolling body */
[data-conversation-content][data-content-phase="hero"] > [data-conversation-scroll]:has(.nm-remote) { justify-content: flex-end; }
[data-conversation-content][data-content-phase="hero"] > [data-conversation-scroll] > .nm-remote { flex: 0 0 auto; width: min(var(--dsh-chat-content-width, 680px), 100%); align-self: center; box-sizing: border-box; padding: 0 var(--dsh-composer-side-clearance, 16px); }
[data-conversation-content][data-content-phase="hero"] > [data-conversation-scroll] > .nm-remote:first-child { margin-top: 16px; }

/* ---- the pinned agent header over the conversation -------------------- */
header[data-window-drag]:has(.nm-header) { position: relative; min-height: 108px; }
/* Centred with auto margins, not translateX(-50%): the window's drag-region map is built from
   untransformed boxes, and a transformed, pointer-events:none box over a drag region left the
   face unclickable on macOS. The header block itself is the no-drag island (see desk-a below). */
.nm-header { position: absolute; left: 0; right: 0; top: 12px; width: fit-content; margin: 0 auto; display: flex; flex-direction: column; align-items: center; gap: 3px; z-index: 2; max-width: min(60%, 520px); }
.nm-header-face { position: relative; width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center; border: 0; padding: 0; background: transparent; cursor: pointer; box-shadow: 0 0 0 2px transparent; transition: box-shadow 300ms; }
.nm-header-face.nm-live { box-shadow: 0 0 0 2px var(--nm-accent); }
.nm-header-face.nm-wait { box-shadow: 0 0 0 2px var(--dsw-alias-state-warn-primary, #d98c1f); }
.nm-header-face:focus-visible { outline: 2px solid var(--nm-accent); outline-offset: 2px; }
.nm-header-name { font-size: 14px; font-weight: 600; line-height: 1.2; color: var(--dsw-alias-label-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.nm-header-status { display: flex; align-items: center; gap: 6px; font-size: 12px; line-height: 1.2; color: var(--dsw-alias-label-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.nm-header-status.nm-live { color: var(--dsw-alias-label-secondary); }
.nm-header-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px 3px 8px; border-radius: 999px; background: var(--dsw-alias-bg-layer-2); }
.nm-header-chip.nm-live { background: color-mix(in srgb, var(--nm-blue) 28%, var(--dsw-alias-bg-layer-2)); }
.nm-header-chip.nm-wait { background: color-mix(in srgb, #d98c1f 25%, var(--dsw-alias-bg-layer-2)); }
.nm-status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--dsw-alias-label-dimmed); flex: none; }
.nm-status-dot.nm-on { background: var(--dsw-alias-state-success-primary, #2f9e5f); }
.nm-status-dot.nm-live { background: var(--nm-accent); animation: nm-pulse 2.4s ease-in-out infinite alternate; }
.nm-status-dot.nm-wait { background: var(--dsw-alias-state-warn-primary, #d98c1f); }
@keyframes nm-pulse { from { opacity: 0.45; transform: scale(0.85); } to { opacity: 1; transform: scale(1.1); } }
@media (prefers-reduced-motion: reduce) { .nm-chat-dot.nm-live, .nm-status-dot.nm-live, .nm-remote-working::before, .nm-mic.nm-live, html[data-nm-muse] [data-chat-running]::after, .nm-traj-live { animation: none; opacity: 1; } }
.nm-stop { display: inline-flex; align-items: center; gap: 4px; margin-left: 4px; padding: 1px 8px 1px 5px; border-radius: 999px; border: 1px solid var(--dsw-alias-interactive-bg-active); background: var(--nm-base); color: var(--dsw-alias-label-primary); font-size: 12px; line-height: 18px; cursor: pointer; }
.nm-stop:hover { background: var(--nm-hover); }
.nm-stop:disabled { opacity: 0.5; cursor: default; }
.nm-invite { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 12px 0 10px; border: 0; border-radius: 999px; background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); font: inherit; font-size: 13px; cursor: pointer; }
.nm-invite:hover { background: var(--dsw-alias-bg-layer-2); }
.nm-invite-card { display: flex; flex-direction: column; gap: 14px; }
.nm-invite-code { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-radius: 12px; background: var(--dsw-alias-bg-layer-2); font-size: 22px; font-weight: 600; letter-spacing: 0.12em; }
.nm-invite-code .nm-pill { margin-left: auto; letter-spacing: 0; }
.nm-invite-link { font-size: 13px; color: var(--dsw-alias-label-secondary); word-break: break-all; }

/* ---- the Muse conversation: the harness's DOM, Muse's shapes ----------- */
/* The composer card becomes one pill: + | the text | send. */
html[data-nm-muse] [data-composer-card] { display: flex !important; flex-direction: row !important; flex-wrap: wrap; align-items: flex-end; gap: 2px 4px; padding: 5px 5px 5px 6px !important; border-radius: 26px !important; background: var(--nm-field) !important; box-shadow: 0 0 0 1px var(--nm-field-border), 0 6px 24px rgba(0,0,0,0.10) !important; }
html[data-nm-muse] [data-composer-card] > [data-input-scroll] { flex: 1 1 120px; min-width: 0; order: 0; margin: 0 !important; }
html[data-nm-muse] [data-composer-card] > [data-input-scroll] [contenteditable] { min-height: 34px !important; padding: 5px 6px 5px 8px !important; }
html[data-nm-muse] [data-composer-card] [data-composer-placeholder] { inset: 5px 6px auto 8px !important; color: transparent !important; }
html[data-nm-muse] [data-composer-card] [data-composer-placeholder]::before { content: var(--nm-placeholder, "Message"); position: absolute; inset: 0 auto auto 0; color: var(--dsw-alias-label-tertiary); white-space: nowrap; }
/* An empty chat: no greeting, the composer sits at the bottom like Muse's. */
html[data-nm-muse] [data-conversation-scroll]:has([class*="_composerHero"]) { justify-content: flex-end; }
html[data-nm-muse] [class*="_composerHero"] > [class*="_root"]:first-child { display: none; }
/* no workspace/preset chips over an empty chat: the inert composer itself opens the workspace picker when one is needed */
html[data-nm-muse] [class*="_composerHero"] > [class*="_heroWorkspaceRow"] { display: none; }
html[data-nm-muse] [data-composer-card] > div:last-child { display: contents; }
html[data-nm-muse] [data-composer-card] > div:last-child > div:first-child { order: -1; gap: 2px; }
html[data-nm-muse] [data-composer-card] > div:last-child > div:last-child { order: 1; margin-left: 0 !important; }
html[data-nm-muse] [data-composer-card] > [class*="_rail"] { flex-basis: 100%; order: -2; }
html[data-nm-muse] [data-composer-card] > [class*="_accessory"] { flex-basis: 100%; order: -3; padding-top: 4px !important; }
html[data-nm-muse] [data-composer-card] [class*="_modes"] { display: none !important; }
/* the right-hand seats stay for the microphone; the model picker goes (Settings keeps it) */
html[data-nm-muse] [data-composer-card] [class*="_standardControls"] { gap: 2px !important; }
html[data-nm-muse] [data-composer-card] [data-slot="conversation.input.model"] { display: none !important; }
html[data-nm-muse] [data-composer-card] [class*="_activity"] { display: none !important; }
html[data-nm-muse] [data-composer-card] [class*="_add"] { width: 34px; height: 34px; border-radius: 50%; color: var(--dsw-alias-label-secondary); }
html[data-nm-muse] [data-composer-card] [class*="_primary"] { width: 34px; height: 34px; transform: none !important; background: var(--nm-send) !important; color: var(--nm-base) !important; }
html[data-nm-muse] [data-composer-card] [class*="_primary"]:disabled { background: var(--nm-send-idle) !important; opacity: 1 !important; color: var(--nm-base) !important; }
html[data-nm-muse] [data-composer-card] ~ [class*="_dock"] { display: none !important; }
.nm-mic { width: 34px; height: 34px; border: 0; padding: 0; border-radius: 50%; background: transparent; color: var(--dsw-alias-label-secondary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.nm-mic:hover { background: var(--nm-hover); color: var(--dsw-alias-label-primary); }
/* recording: the red breathes (no ring running outward) */
.nm-mic.nm-live { color: #fff; background: #e0245e; box-shadow: 0 0 0 4px rgba(224,36,94,0.25); animation: nm-mic-pulse 4.8s ease-in-out infinite; }
@keyframes nm-mic-pulse { 0%, 100% { opacity: 0.72; } 50% { opacity: 1; } }
/* Muse keeps the chat bare: no tool-step disclosure, no usage, no fork, no context rows */
html[data-nm-muse] [data-chat-flow-kind="context"] { display: none !important; }
/* the "done in 6 s" accordion goes; what the agent said along the way stays a bubble, as Muse shows it (the harness folds it under the accordion with hidden=until-found) */
html[data-nm-muse] [data-chat-flow-kind="turn-process"] { display: none !important; }
html[data-nm-muse] [data-turn-process-member]:not([data-chat-flow-kind="assistant-step"]):not([data-chat-flow-kind="tool-call"]) { display: none !important; }
html[data-nm-muse] [data-chat-flow-kind="assistant-step"][hidden] { display: block !important; content-visibility: visible !important; }
/* the rooms' trigger rows and the agent's tool rows stay out of the chat (the Activity tab has them); approvals, presented files and open questions stay */
html[data-nm-muse] [data-chat-flow-kind="turn-trigger"] { display: none !important; }
html[data-nm-muse]:not([data-nm-steps]) [data-chat-flow-kind="tool-call"]:not(:has([data-approval-key], [data-tool="present"], [data-tool="ask_user_question"]:not([data-state="error"]))) { display: none !important; }
html[data-nm-muse] [data-chat-flow-kind="tool-call"][hidden]:has([data-approval-key], [data-tool="present"], [data-tool="ask_user_question"]:not([data-state="error"])) { display: block !important; content-visibility: visible !important; }
/* with "Show the agent's steps" on, every tool row is unfolded from the accordion */
html[data-nm-muse][data-nm-steps] [data-chat-flow-kind="tool-call"][hidden] { display: block !important; content-visibility: visible !important; }
/* while the agent thinks: three dots in a grey bubble, not the whale; the three breathe together (no wave running across them) */
html[data-nm-muse] [data-chat-running] { display: flex !important; flex-direction: row; align-items: center; justify-content: center; width: fit-content; min-height: 36px; margin: 6px 0; padding: 0 16px; border-radius: 18px; background: var(--nm-agent-bubble); line-height: 0; }
html[data-nm-muse] [data-chat-running] > [class*="_runningDivider"], html[data-nm-muse] [data-chat-running] > [class*="_runningContent"] { display: none !important; }
html[data-nm-muse] [data-chat-running]::after { content: ''; display: block; flex: none; width: 7px; height: 7px; margin: 0 22px 0 0; border-radius: 50%; background: var(--dsw-alias-label-secondary); box-shadow: 11px 0 0 var(--dsw-alias-label-secondary), 22px 0 0 var(--dsw-alias-label-secondary); animation: nm-breathe-light 4.8s ease-in-out infinite; }
html[data-nm-muse] [data-chat-flow-kind="turn-tail"] [class*="_endInfo"] > :not([class*="_timeEnd"]) { display: none !important; }
html[data-nm-muse] [data-chat-flow-kind="turn-tail"] [data-clock="end"] > button[class*="_action"]:nth-of-type(2) { display: none !important; }
.nm-quote-act { width: 24px; height: 24px; border: 0; padding: 0; border-radius: 6px; background: transparent; color: var(--dsw-alias-label-tertiary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.nm-quote-act:hover { background: var(--nm-hover); color: var(--dsw-alias-label-primary); }
/* the time of a message sits centred over it, small and grey, as Muse's do */
html[data-nm-muse] [data-chat-flow-kind="user"] [class*="_userRow"] { position: relative; margin-top: 18px; }
html[data-nm-muse] [data-chat-flow-kind="user"] [data-clock="start"] { position: absolute; left: 0; right: 0; top: -18px; justify-content: center; opacity: 1 !important; }
html[data-nm-muse] [data-chat-flow-kind="user"] [data-clock="start"] [class*="_timeStart"] { font-size: 11px; color: var(--dsw-alias-label-dimmed); }
html[data-nm-muse] [data-chat-flow-kind="user"] [data-clock="start"] button { opacity: 0; transition: opacity 160ms; }
html[data-nm-muse] [data-chat-flow-kind="user"]:hover [data-clock="start"] button, html[data-nm-muse] [data-chat-flow-kind="user"] [data-clock="start"] button:focus-visible { opacity: 1; }
html[data-nm-muse] [data-chat-flow-kind="turn-tail"] [class*="_timeEnd"] { font-size: 11px; color: var(--dsw-alias-label-dimmed); }
/* The user's words: a tinted bubble on the right. The agent's: a quiet grey one. */
html[data-nm-muse] [data-chat-flow-kind="user"] [class*="_bubble"] { background: var(--nm-user-bubble) !important; color: var(--dsw-alias-label-primary); border-radius: 18px !important; padding: 9px 14px !important; }
html[data-nm-muse] [data-chat-flow-kind="assistant-step"] [data-slot="conversation.chat.node"] > [class*="_root"] > [class*="_body"] { width: fit-content; max-width: 100%; box-sizing: border-box; background: var(--nm-agent-bubble); border-radius: 20px; padding: 10px 16px; }
html[data-nm-muse] [data-chat-flow-kind="assistant-step"] [data-slot="conversation.chat.node"] > [class*="_root"] > [class*="_body"]:empty { display: none; }
html[data-nm-muse] [data-chat-flow-kind="assistant-step"] [data-slot="conversation.chat.node"] > [class*="_root"] > [class*="_body"] > [class*="_markdown"] > :first-child { margin-top: 0; }
html[data-nm-muse] [data-chat-flow-kind="assistant-step"] [data-slot="conversation.chat.node"] > [class*="_root"] > [class*="_body"] > [class*="_markdown"] > :last-child { margin-bottom: 0; }
/* Timestamps and per-message actions appear on hover, as Muse keeps its chat quiet. */
html[data-nm-muse] [data-chat-flow-kind="user"] [class*="_actions"][data-clock],
html[data-nm-muse] [data-chat-flow-kind="turn-tail"] [class*="_actions"][data-clock] { opacity: 0; transition: opacity 160ms; }
html[data-nm-muse] [data-chat-flow-kind="user"]:hover [class*="_actions"][data-clock],
html[data-nm-muse] [data-chat-flow-kind="user"] [class*="_actions"][data-clock]:focus-within,
html[data-nm-muse] [data-chat-flow-kind="turn-tail"]:hover [class*="_actions"][data-clock],
html[data-nm-muse] [data-chat-flow-kind="turn-tail"] [class*="_actions"][data-clock]:focus-within { opacity: 1; }
/* The session header keeps only what Muse shows up there: Invite and the corner;
   a side chat shows its title at the left (a new one reads "New side chat"). */
html[data-nm-muse] [data-slot="conversation.session.header"] [class*="_titleCluster"] { display: none; }
html[data-nm-muse][data-nm-side] [data-slot="conversation.session.header"] [class*="_titleCluster"] { display: flex; }
html[data-nm-muse][data-nm-side] [data-slot="conversation.session.header"] [class*="_crumb"] { font-size: 13px; font-weight: 500; color: var(--dsw-alias-label-secondary); background: var(--dsw-alias-bg-layer-2); border-radius: 999px; padding: 4px 12px; }
html[data-nm-muse] [data-slot="conversation.session.header"] [class*="_headerActions"] { display: none; }
html[data-nm-muse] [data-slot="conversation.session.header"] [class*="_titleRow"] { justify-content: flex-end; }
html[data-nm-muse][data-nm-side] [data-slot="conversation.session.header"] [class*="_titleRow"] { justify-content: space-between; }
html[data-nm-muse] [data-slot="conversation.session.header"] [data-conversation-tabs] { display: none; }
/* …except while another view (the trajectory a tool row's "Inspect" opens) is up: then the
   tabs come back as the way out — a small segmented control, "Chat" first, at the top right
   (the centre is the face and its status line). Esc does the same. */
html[data-nm-muse] [data-slot="conversation.session.header"] [data-conversation-tabs]:has([role="tab"][aria-selected="true"]:not(:first-child)) { display: inline-flex; align-self: flex-start; margin: 10px 16px 0 auto; padding: 3px; gap: 2px; border-radius: 999px; background: var(--dsw-alias-bg-layer-2); }
html[data-nm-muse] [data-slot="conversation.session.header"] [data-conversation-tabs]:has([role="tab"][aria-selected="true"]:not(:first-child)) [role="tab"] { border: 0; border-radius: 999px; padding: 4px 12px; font-size: 12.5px; font-weight: 500; color: var(--dsw-alias-label-secondary); background: transparent; cursor: pointer; }
html[data-nm-muse] [data-slot="conversation.session.header"] [data-conversation-tabs]:has([role="tab"][aria-selected="true"]:not(:first-child)) [role="tab"][aria-selected="true"] { background: var(--nm-base); color: var(--dsw-alias-label-primary); box-shadow: 0 1px 2px rgba(0,0,0,.08); }
html[data-nm-muse] [data-slot="conversation.session.header.utilities"] > *:not(:has(.nm-invite)) { display: none; }
html[data-nm-muse] [data-turn-process-inline] { display: none !important; }
html[data-nm-muse] [data-slot="conversation.session.header.corner"] [data-sidebar-right-expand] { display: none; }
.nm-header-back { position: absolute; left: 14px; top: 14px; z-index: 3; width: 30px; height: 30px; border: 0; border-radius: 50%; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-primary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.nm-header-back:hover { background: var(--dsw-alias-bg-layer-3); }
.nm-header-toast { color: var(--dsw-alias-state-success-primary, #2f9e5f); }
.nm-header-status.nm-done { color: var(--dsw-alias-label-secondary); }
.nm-header-status.nm-wait { color: var(--dsw-alias-state-warn-primary, #d98c1f); }
.nm-header-line { overflow: hidden; text-overflow: ellipsis; }
.nm-spin { transform-origin: 12px 12px; animation: nm-spin 0.9s linear infinite; }
/* the rail: the face at the top (in a room, or collapsed), recent documents under the rooms */
.nm-rail-face { display: inline-flex; border-radius: 50%; overflow: hidden; box-shadow: 0 0 0 1.5px var(--nm-divider); }
.nm-rail-face.nm-live { box-shadow: 0 0 0 2px var(--nm-accent); }
.nm-rail-recent { display: flex; flex-direction: column; align-items: center; gap: 6px; padding-top: 6px; margin-top: 2px; border-top: 1px solid var(--nm-divider); }
.nm-rail-doc { width: 40px; height: 40px; border-radius: 11px; flex-direction: column; gap: 0; }
.nm-rail-doc svg { margin-top: -2px; }
.nm-rail-doc-tag { font-size: 8.5px; line-height: 1; font-weight: 600; letter-spacing: 0.02em; color: var(--dsw-alias-label-tertiary); margin-top: -3px; }
.nm-rail-doc.nm-pinned .nm-rail-doc-tag { color: var(--nm-accent); }
/* the split: the chat keeps the main area, the room docks at the right */
/* a narrow chat column at the left, the room wide at the right — the room's own top-left toggle closes it */
html[data-nm-split] { --nm-split-w: clamp(420px, 62vw, 1200px); }
.nm-split { position: fixed; top: 0; right: 0; bottom: 0; width: var(--nm-split-w, 62vw); z-index: 50; display: flex; flex-direction: column; background: var(--nm-base); border-left: 1px solid var(--nm-divider); animation: nm-slide-in 180ms ease-out; }
html[data-nm-split] [class*="_centerCol"] { min-width: 0; padding-right: var(--nm-split-w, 62vw); box-sizing: border-box; }
html[data-nm-split] .nm-header-back { left: 10px; }
.nm-header-chats { width: auto; padding: 0 10px 0 8px; gap: 6px; border-radius: 8px; font-size: 13px; font-weight: 600; }
.nm-split .nm-room-head, .nm-split .nm-room-inner { padding-left: 24px; padding-right: 24px; }
.nm-split .nm-room-title { font-size: 22px; }
.nm-split .nm-room-top { height: 44px; }
/* a room has the window beside the rail: the frame's sidebar track shrinks to the rail, no drag handle, no right bar */
html[data-nm-room] [class*="_frame"] { grid-template-columns: 66px minmax(0, 1fr) 0px !important; }
html[data-nm-room] [class*="_frame"] > [class*="_handle"] { display: none; }
/* the sidebar-toggle at a room's top left */
.nm-room-toggle { flex: none; display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; margin-left: -8px; border: 0; border-radius: 8px; background: transparent; color: var(--dsw-alias-label-secondary); cursor: pointer; }
.nm-room-toggle:hover, .nm-room-toggle.nm-active { background: var(--nm-hover); color: var(--dsw-alias-label-primary); }
.nm-lib-col-tools { display: flex; align-items: center; height: 36px; padding: 0 2px; }
.nm-lib-col-tools .nm-room-toggle { margin-left: 0; }
.nm-room-head > .nm-room-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nm-cat-row:disabled { cursor: progress; opacity: 0.7; }
/* search (⌘K) */
.nm-search-backdrop { position: fixed; inset: 0; z-index: 85; background: rgba(0,0,0,0.28); display: flex; align-items: flex-start; justify-content: center; padding-top: 12vh; animation: nm-fade-in 120ms ease-out; }
.nm-search { width: min(620px, calc(100vw - 48px)); max-height: 70vh; display: flex; flex-direction: column; border-radius: 16px; background: var(--nm-base); color: var(--dsw-alias-label-primary); box-shadow: 0 24px 80px rgba(0,0,0,0.35), 0 0 0 1px var(--nm-divider); overflow: hidden; animation: nm-rise 160ms ease-out; }
.nm-search-field { display: flex; align-items: center; gap: 10px; padding: 14px 16px; border-bottom: 1px solid var(--nm-divider); color: var(--dsw-alias-label-tertiary); }
.nm-search-input { flex: 1; min-width: 0; border: 0; background: transparent; color: var(--dsw-alias-label-primary); font: inherit; font-size: 16px; outline: none; }
.nm-search-label { font-size: 11.5px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--dsw-alias-label-tertiary); padding: 10px 16px 4px; }
.nm-search-empty { padding: 20px 16px 24px; font-size: 13.5px; color: var(--dsw-alias-label-tertiary); }
.nm-search-list { flex: 1; min-height: 0; overflow-y: auto; padding: 0 8px 8px; display: flex; flex-direction: column; gap: 1px; }
.nm-search-row { display: flex; align-items: center; gap: 12px; width: 100%; padding: 9px 10px; border: 0; border-radius: 10px; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.nm-search-row:hover, .nm-search-row.nm-active { background: var(--nm-hover); }
.nm-search-row-icon { width: 30px; height: 30px; border-radius: 9px; display: inline-flex; align-items: center; justify-content: center; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); flex: none; }
.nm-search-row-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.nm-search-row-title { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-search-row-sub { font-size: 12.5px; color: var(--dsw-alias-label-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-search-row-time { flex: none; font-size: 12px; color: var(--dsw-alias-label-dimmed); }
/* the document editor */
.nm-doc { position: fixed; inset: 0; z-index: 75; display: flex; flex-direction: column; background: var(--nm-base); color: var(--dsw-alias-label-primary); animation: nm-fade-in 140ms ease-out; }
.nm-doc-bar { flex: none; display: flex; align-items: center; gap: 8px; padding: 10px 14px 8px; border-bottom: 1px solid var(--nm-divider); }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) .nm-doc-bar { padding-top: 30px; }
.nm-doc-name { font-size: 14px; font-weight: 600; margin: 0 6px 0 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-doc-tools { display: flex; align-items: center; gap: 2px; padding: 0 4px; border-left: 1px solid var(--nm-divider); margin-left: 4px; }
.nm-doc-tool { min-width: 28px; height: 28px; padding: 0 7px; border: 0; border-radius: 7px; background: transparent; color: var(--dsw-alias-label-secondary); font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.nm-doc-tool:hover { background: var(--nm-hover); color: var(--dsw-alias-label-primary); }
.nm-doc-tool-i { font-style: italic; font-family: Georgia, serif; }
.nm-doc-state { margin-left: auto; font-size: 12px; color: var(--dsw-alias-label-tertiary); white-space: nowrap; }
.nm-doc-state.nm-dirty { color: var(--dsw-alias-state-warn-primary, #d98c1f); }
.nm-doc-error { font-size: 12.5px; color: var(--dsw-alias-state-error-primary, #d2453d); padding: 10px 24px 0; }
.nm-doc-loading { flex: 1; display: flex; align-items: center; justify-content: center; }
.nm-doc-scroll { flex: 1; min-height: 0; overflow-y: auto; }
.nm-doc-body { max-width: 760px; width: 100%; margin: 0 auto; padding: 36px 48px 120px; box-sizing: border-box; outline: none; font-size: 15px; line-height: 1.7; }
.nm-doc-body:empty::before { content: attr(data-placeholder); color: var(--dsw-alias-label-dimmed); }
.nm-doc-body h1 { font-size: 30px; margin: 0 0 14px; line-height: 1.25; letter-spacing: -0.01em; }
.nm-doc-body h2 { font-size: 22px; margin: 26px 0 8px; }
.nm-doc-body h3 { font-size: 17px; margin: 20px 0 6px; }
.nm-doc-body p { margin: 0 0 10px; }
.nm-doc-body ul, .nm-doc-body ol { margin: 0 0 10px; padding-left: 24px; }
.nm-doc-body blockquote { margin: 0 0 10px; padding: 2px 0 2px 14px; border-left: 3px solid var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-secondary); }
.nm-doc-body pre { background: var(--dsw-alias-bg-layer-2); padding: 12px 14px; border-radius: 12px; overflow-x: auto; font-size: 13px; }
.nm-doc-body code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.92em; }
.nm-doc-body hr { border: 0; height: 1px; background: var(--nm-divider); margin: 18px 0; }
.nm-doc-body table { border-collapse: collapse; margin: 0 0 12px; }
.nm-doc-body th, .nm-doc-body td { padding: 6px 12px; border: 1px solid var(--nm-divider); text-align: left; }
.nm-doc-note { color: var(--dsw-alias-label-tertiary); }
.nm-doc-source { flex: 1; min-height: 0; width: 100%; box-sizing: border-box; border: 0; outline: none; resize: none; padding: 28px 48px 120px; background: transparent; color: var(--dsw-alias-label-primary); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13.5px; line-height: 1.6; max-width: 860px; margin: 0 auto; display: block; }
@media print { html[data-nm-print] body * { visibility: hidden; } html[data-nm-print] .nm-doc, html[data-nm-print] .nm-doc * { visibility: visible; } html[data-nm-print] .nm-doc { position: absolute; inset: 0; height: auto; overflow: visible; } html[data-nm-print] .nm-doc-bar { display: none; } html[data-nm-print] .nm-doc-scroll { overflow: visible; } }
/* a task's detail (from the Activity tab) */
.nm-task-backdrop { position: fixed; inset: 0; z-index: 86; background: rgba(0,0,0,0.32); display: flex; align-items: center; justify-content: center; animation: nm-fade-in 120ms ease-out; }
.nm-task { width: min(920px, calc(100vw - 48px)); height: min(640px, calc(100vh - 48px)); display: flex; flex-direction: column; border-radius: 18px; background: var(--nm-base); color: var(--dsw-alias-label-primary); box-shadow: 0 24px 80px rgba(0,0,0,0.35), 0 0 0 1px var(--nm-divider); overflow: hidden; animation: nm-rise 160ms ease-out; }
.nm-task-head { flex: none; display: flex; align-items: center; gap: 10px; padding: 14px 14px 12px 18px; border-bottom: 1px solid var(--nm-divider); }
.nm-task-pill { flex: none; font-size: 11.5px; font-weight: 600; padding: 3px 9px; border-radius: 999px; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); }
.nm-task-pill.nm-live { background: color-mix(in srgb, var(--nm-blue) 22%, transparent); color: var(--nm-blue); }
.nm-task-pill.nm-ok { background: color-mix(in srgb, #2f9e5f 20%, transparent); color: #2f9e5f; }
.nm-task-pill.nm-err { background: color-mix(in srgb, #d2453d 20%, transparent); color: #d2453d; }
.nm-task-title { flex: 1; min-width: 0; font-size: 15px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-task-body { flex: 1; min-height: 0; display: flex; }
.nm-task-steps { flex: none; width: 300px; overflow-y: auto; padding: 10px 8px; border-right: 1px solid var(--nm-divider); display: flex; flex-direction: column; gap: 1px; }
.nm-task-step { display: flex; align-items: flex-start; gap: 10px; width: 100%; padding: 8px 10px; border: 0; border-radius: 10px; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.nm-task-step:hover, .nm-task-step.nm-active { background: var(--nm-hover); }
.nm-task-step-icon { width: 24px; height: 24px; border-radius: 7px; display: inline-flex; align-items: center; justify-content: center; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); flex: none; }
.nm-task-step-icon.nm-ok { color: #2f9e5f; }
.nm-task-step-icon.nm-err { color: #d2453d; }
.nm-task-step-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.nm-task-step-title { font-size: 13.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-task-step-time { font-size: 11.5px; color: var(--dsw-alias-label-dimmed); }
.nm-task-detail { flex: 1; min-width: 0; overflow-y: auto; padding: 18px 22px 28px; display: flex; flex-direction: column; gap: 14px; }
.nm-task-detail h3 { font-size: 12px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--dsw-alias-label-tertiary); margin: 0 0 6px; }
.nm-task-detail pre { margin: 0; padding: 12px 14px; border-radius: 12px; background: var(--dsw-alias-bg-layer-2); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; max-height: 320px; overflow: auto; }
.nm-task-muted { font-size: 13.5px; color: var(--dsw-alias-label-tertiary); }
.nm-task-empty { flex: 1; display: flex; align-items: center; justify-content: center; font-size: 13.5px; color: var(--dsw-alias-label-tertiary); }
/* the profile drawer's Identity tab */
.nm-pf-card { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 14px; background: var(--nm-card); margin: 4px 0 10px; }
.nm-pf-card-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.nm-pf-card-name { font-size: 15px; font-weight: 600; }
.nm-pf-card-sub { font-size: 12px; color: var(--dsw-alias-label-tertiary); }
.nm-pf-doc { display: flex; align-items: center; gap: 12px; width: 100%; padding: 12px 14px; border: 0; border-radius: 14px; background: var(--nm-card); color: inherit; font: inherit; text-align: left; cursor: pointer; margin-bottom: 8px; }
.nm-pf-doc:hover { background: var(--dsw-alias-bg-layer-2); }
.nm-pf-doc-icon { width: 36px; height: 36px; border-radius: 10px; display: inline-flex; align-items: center; justify-content: center; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); flex: none; }
.nm-pf-doc-soul .nm-pf-doc-icon { background: color-mix(in srgb, var(--nm-accent) 22%, transparent); color: var(--nm-accent); }
.nm-pf-doc-memory .nm-pf-doc-icon { background: color-mix(in srgb, var(--nm-blue) 20%, transparent); color: var(--nm-blue); }
.nm-pf-doc-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.nm-pf-doc-title { font-size: 14px; font-weight: 600; }
.nm-pf-doc-sub { font-size: 12px; color: var(--dsw-alias-label-tertiary); }
.nm-pf-stop { width: 26px; height: 26px; border: 0; border-radius: 50%; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-primary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; flex: none; }
.nm-pf-stop:hover { background: #d2453d; color: #fff; }
.nm-pf-row-chev { color: var(--dsw-alias-label-dimmed); flex: none; display: inline-flex; transition: transform 120ms; }
.nm-pf-row-chev.nm-open { transform: rotate(180deg); }
.nm-pf-approval { cursor: pointer; }
.nm-pf-task.nm-clickable { cursor: pointer; }
.nm-pf-row-time { flex: none; font-size: 11.5px; color: var(--dsw-alias-label-dimmed); }
.nm-pf-card-actions { display: flex; align-items: center; gap: 6px; }
.nm-pf-doc-foot { flex: none; display: flex; flex-direction: column; align-items: flex-end; gap: 2px; font-size: 11px; color: var(--dsw-alias-label-dimmed); }
.nm-seg-btn.nm-seg-text { min-width: 0; padding: 0 12px; font-size: 12.5px; }
.nm-task-loading { padding: 24px; font-size: 13.5px; color: var(--dsw-alias-label-tertiary); }
.nm-task-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--dsw-alias-label-dimmed); }
.nm-task-step-text { font-size: 13.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-task-detail-title { font-size: 16px; font-weight: 600; margin: 0 0 4px; }
.nm-task-block { display: flex; flex-direction: column; gap: 6px; }
.nm-task-label { font-size: 12px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--dsw-alias-label-tertiary); }
.nm-task-pre { margin: 0; padding: 12px 14px; border-radius: 12px; background: var(--dsw-alias-bg-layer-2); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; max-height: 320px; overflow: auto; }
/* The approval card: a dark rounded card with a shield, Allow in blue. */
/* The approval card, Muse-shaped: shield + headline, Allow (blue) first, then Reject. */
html[data-nanomuse] [data-approval-key] > div { background: var(--nm-card) !important; border: 1px solid var(--nm-divider) !important; border-radius: 18px !important; box-shadow: 0 10px 30px rgba(0,0,0,0.18) !important; padding: 14px 16px !important; outline: none !important; }
html[data-nanomuse] [data-approval-key] > div > :first-child { font-size: 12px; color: var(--dsw-alias-label-tertiary); background: transparent !important; padding: 0 !important; border: 0 !important; margin-bottom: 6px; }
html[data-nanomuse] [data-approval-key] > div > :first-child::before { content: ''; display: inline-block; width: 16px; height: 16px; margin-right: 6px; vertical-align: -3px; background: currentColor; -webkit-mask: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5 5 6.2v5.3c0 4.4 3 7.6 7 9 4-1.4 7-4.6 7-9V6.2z"/><path d="m9 12 2 2 4-4"/></svg>') center / contain no-repeat; mask: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5 5 6.2v5.3c0 4.4 3 7.6 7 9 4-1.4 7-4.6 7-9V6.2z"/><path d="m9 12 2 2 4-4"/></svg>') center / contain no-repeat; }
html[data-nanomuse] [data-approval-key] [data-approval-scroll] > :first-child { font-size: 15px; font-weight: 600; line-height: 1.4; color: var(--dsw-alias-label-primary); }
html[data-nanomuse] [data-approval-key] > div > :last-child { display: flex; flex-direction: row-reverse; justify-content: flex-end; gap: 8px; margin-top: 12px; }
html[data-nanomuse] [data-approval-key] > div > :last-child button { border-radius: 999px !important; min-height: 36px; padding: 0 20px !important; font-weight: 500; border: 0 !important; box-shadow: none !important; }
html[data-nanomuse] [data-approval-key] > div > :last-child button:last-child { background: var(--nm-blue) !important; color: #fff !important; }
html[data-nanomuse] [data-approval-key] > div > :last-child button:last-child:hover { filter: brightness(1.08); }
html[data-nanomuse] [data-approval-key] > div > :last-child button:not(:last-child) { background: var(--nm-field) !important; color: var(--dsw-alias-label-primary) !important; }

/* ---- the profile drawer ------------------------------------------------ */
.nm-pf { position: fixed; top: 0; right: 0; bottom: 0; width: 310px; z-index: 60; display: flex; flex-direction: column; background: var(--nm-base); color: var(--dsw-alias-label-primary); border-left: 1px solid var(--nm-divider); outline: none; animation: nm-slide-in 180ms ease-out; }
html[data-nm-profile] [class*="_centerCol"] { padding-right: 310px; box-sizing: border-box; }
@keyframes nm-slide-in { from { transform: translateX(24px); opacity: 0; } to { transform: none; opacity: 1; } }
.nm-pf-top { flex: none; display: flex; align-items: center; padding: 10px 10px 0; min-height: 40px; }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) .nm-pf-top { padding-top: 12px; }
.nm-pf-head { flex: none; display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 6px 20px 16px; }
.nm-pf-face { position: relative; }
.nm-pf-face-btn { display: block; border: 0; padding: 0; background: transparent; border-radius: 50%; cursor: pointer; }
.nm-pf-face-btn:focus-visible { outline: 2px solid var(--nm-accent); outline-offset: 3px; }
.nm-pf-pen { position: absolute; right: -2px; bottom: 0; width: 26px; height: 26px; border-radius: 50%; border: 2px solid var(--nm-base); background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; padding: 0; }
.nm-pf-pen:hover { background: var(--nm-blue); color: #fff; }
.nm-menu.nm-pf-menu { position: absolute; left: 50%; top: calc(100% + 6px); transform: translateX(-50%); min-width: 160px; }
.nm-pf-name { font-size: 18px; font-weight: 600; margin-top: 4px; }
.nm-pf-status { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--dsw-alias-label-secondary); }
.nm-pf .nm-seg { align-self: center; margin: 0 20px 10px; }
.nm-pf-body { flex: 1; min-height: 0; overflow-y: auto; padding: 4px 16px 20px; }
.nm-pf-day { font-size: 12px; font-weight: 600; letter-spacing: 0.04em; color: var(--dsw-alias-label-tertiary); padding: 10px 4px 6px; }
.nm-pf-rows { display: flex; flex-direction: column; gap: 2px; }
.nm-pf-row { display: flex; align-items: center; gap: 10px; padding: 8px 6px; border-radius: 10px; }
.nm-pf-row:hover { background: var(--nm-hover); }
.nm-pf-row-icon { width: 32px; height: 32px; border-radius: 9px; display: inline-flex; align-items: center; justify-content: center; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); flex: none; }
.nm-pf-row-icon.nm-live { color: var(--nm-accent); }
.nm-pf-row-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.nm-pf-row-title { font-size: 13.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-pf-row-sub { font-size: 12px; color: var(--dsw-alias-label-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-pf-row-sub.nm-wrap { white-space: normal; line-height: 1.45; }
.nm-pf-empty { font-size: 13px; line-height: 1.55; color: var(--dsw-alias-label-tertiary); margin: 6px 4px; }
.nm-pf-stack { display: flex; flex-direction: column; gap: 10px; }
.nm-pf-label { font-size: 12px; font-weight: 600; color: var(--dsw-alias-label-tertiary); }
.nm-pf-actions { display: flex; gap: 8px; }
.nm-pf-preview { display: flex; justify-content: center; padding: 6px 0; }
.nm-pf-choices { display: flex; flex-wrap: wrap; gap: 6px; }
.nm-pf-choice { width: 36px; height: 36px; border-radius: 10px; border: 2px solid transparent; background: var(--dsw-alias-bg-layer-2); font-size: 20px; cursor: pointer; }
.nm-pf-choice.nm-active { border-color: var(--nm-blue); }
.nm-pf-swatch { width: 28px; height: 28px; border-radius: 50%; border: 2px solid transparent; cursor: pointer; box-shadow: 0 0 0 1px rgba(0,0,0,0.12); }
.nm-pf-swatch.nm-active { border-color: var(--dsw-alias-label-primary); }

/* ---- the devices page ------------------------------------------------- */
.nm-page { height: 100%; min-height: 0; overflow: auto; box-sizing: border-box; padding: 28px 32px 40px; color: var(--dsw-alias-label-primary); }
.nm-page-inner { max-width: 640px; margin: 0 auto; display: flex; flex-direction: column; gap: 18px; }
.nm-page h1 { font-size: 22px; font-weight: 600; margin: 0; }
.nm-page h2 { font-size: 13px; font-weight: 600; margin: 10px 0 0; color: var(--dsw-alias-label-tertiary); text-transform: uppercase; letter-spacing: 0.06em; }
.nm-lead { font-size: 14px; line-height: 1.55; color: var(--dsw-alias-label-secondary); margin: 0; }
.nm-card { background: var(--nm-card); border-radius: var(--nm-radius); padding: 4px 14px; }
.nm-row { display: flex; align-items: center; gap: 12px; padding: 11px 0; font-size: 14px; border-bottom: 1px solid var(--nm-divider); }
.nm-row:last-child { border-bottom: 0; }
.nm-row-icon { width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); flex: none; }
.nm-row-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.nm-row-title { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-row-sub { font-size: 12.5px; line-height: 1.45; color: var(--dsw-alias-label-tertiary); }
.nm-row-sub.nm-wrap { white-space: normal; }
.nm-row-chevron { color: var(--dsw-alias-label-tertiary); flex: none; }
.nm-row-link { display: flex; align-items: center; gap: 12px; width: 100%; padding: 11px 0; border: 0; border-bottom: 1px solid var(--nm-divider); background: transparent; color: inherit; font: inherit; font-size: 14px; text-align: left; cursor: pointer; }
.nm-row-link:last-child { border-bottom: 0; }
.nm-row-link:hover .nm-row-title { color: var(--nm-blue); }
.nm-switch { position: relative; width: 40px; height: 24px; border-radius: 999px; border: 0; padding: 0; background: var(--dsw-alias-bg-layer-3); cursor: pointer; transition: background 120ms; flex: none; }
.nm-switch::after { content: ''; position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; border-radius: 50%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.3); transition: transform 120ms; }
.nm-switch[aria-checked="true"] { background: var(--nm-blue); }
.nm-switch[aria-checked="true"]::after { transform: translateX(16px); }
.nm-switch:disabled { opacity: 0.5; cursor: default; }

/* ---- settings dialog -------------------------------------------------- */
.nm-settings-overlay { position: fixed; inset: 0; z-index: 70; display: flex; align-items: center; justify-content: center; }
.nm-settings-mask { position: absolute; inset: 0; background: var(--dsw-alias-bg-mask-1, rgba(0,0,0,0.3)); }
.nm-settings { position: relative; width: min(900px, calc(100vw - 48px)); height: min(620px, calc(100vh - 48px)); display: flex; border-radius: 18px; overflow: hidden; background: var(--nm-base); color: var(--dsw-alias-label-primary); box-shadow: 0 24px 80px rgba(0,0,0,0.35), 0 0 0 1px var(--nm-divider); outline: none; }
.nm-settings-nav { width: 212px; flex: none; display: flex; flex-direction: column; background: var(--nm-base); border-right: 1px solid var(--nm-divider); padding: 18px 10px 12px; box-sizing: border-box; overflow: auto; }
.nm-settings-title { font-size: 16px; font-weight: 600; padding: 0 10px 12px; outline: none; }
.nm-settings-group { font-size: 11.5px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--dsw-alias-label-tertiary); padding: 12px 10px 6px; }
.nm-settings-cell { display: flex; align-items: center; gap: 10px; width: 100%; border: 0; text-align: left; padding: 8px 10px; border-radius: 10px; background: transparent; color: var(--dsw-alias-label-secondary); font: inherit; font-size: 14px; cursor: pointer; }
.nm-settings-cell:hover { background: var(--nm-hover); color: var(--dsw-alias-label-primary); }
.nm-settings-cell.nm-active { background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); }
.nm-settings-cell.nm-danger { color: var(--dsw-alias-state-error-primary, #d2453d); }
.nm-settings-cell svg { flex: none; }
.nm-settings-cell-label { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-settings-foot { margin-top: auto; padding-top: 10px; }
.nm-settings-content { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.nm-settings-head { flex: none; display: flex; align-items: center; justify-content: flex-end; gap: 6px; padding: 12px 14px 0; min-height: 36px; }
.nm-settings-back { margin: 0 auto 0 14px; }
.nm-settings-body { flex: 1; min-height: 0; overflow: auto; padding: 8px 28px 28px; }
.nm-settings-body > * { max-width: 560px; }
.nm-settings-body .nm-page { padding: 0; height: auto; overflow: visible; }
.nm-settings-body .nm-page h1 { display: none; }
.nm-general { display: flex; flex-direction: column; }
/* General, Muse's way: the account card, the usage bars, the key cap */
.nm-usage { padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; }
.nm-usage-row { display: flex; align-items: center; justify-content: space-between; font-size: 14px; }
.nm-usage-plan { font-weight: 600; }
.nm-usage-pct { font-size: 12.5px; color: var(--dsw-alias-label-secondary); }
.nm-usage-bar { height: 6px; border-radius: 3px; background: var(--nm-hover); overflow: hidden; }
.nm-usage-bar > span { display: block; height: 100%; border-radius: 3px; background: var(--nm-accent); transition: width 240ms; }
.nm-usage-fine { font-size: 12px; color: var(--dsw-alias-label-tertiary); }
.nm-usage-link { font-size: 13px; color: var(--nm-blue); text-decoration: none; align-self: flex-start; }
.nm-ways { display: flex; flex-direction: column; gap: 10px; margin-top: 6px; padding-top: 10px; border-top: 1px solid var(--nm-divider); }
.nm-ways-lead { font-size: 13px; line-height: 1.5; color: var(--dsw-alias-label-secondary); }
.nm-way { display: flex; gap: 10px; align-items: flex-start; }
.nm-way-icon { width: 28px; height: 28px; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex: none; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); }
.nm-way-main { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.nm-way-title { font-size: 13.5px; font-weight: 500; }
.nm-way-sub { font-size: 12.5px; line-height: 1.45; color: var(--dsw-alias-label-tertiary); }
.nm-refusal .nm-allowance.nm-ways { border-top: 0; padding-top: 0; margin-top: 0; }
.nm-allowance > .nm-ways-lead { font-size: 14px; font-weight: 600; color: var(--dsw-alias-label-primary); }
.nm-allowance .nm-ways { border-top: 0; padding-top: 0; margin-top: 0; gap: 8px; }
.nm-aw-more { display: inline-flex; align-items: center; gap: 2px; color: var(--dsw-alias-label-secondary); }
.nm-aw-chevron { display: inline-flex; transition: transform 120ms; }
.nm-aw-chevron.nm-aw-open { transform: rotate(90deg); }
.nm-aw-list { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; }
.nm-aw-list li { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; align-items: baseline; }
.nm-aw-list-actions { display: inline-flex; gap: 8px; }
.nm-aw-list-actions .nm-ob-link.nm-inline { color: var(--nm-blue); text-decoration: none; }
.nm-refusal { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; margin: 4px 0; border: 1px solid var(--nm-divider); max-width: 100%; }
.nm-refusal-text { font-size: 13.5px; line-height: 1.5; color: var(--dsw-alias-label-primary); }
.nm-refusal-sub { font-size: 12.5px; line-height: 1.45; overflow-wrap: anywhere; }
.nm-refusal-actions { flex-wrap: wrap; }
.nm-refusal-details summary { font-size: 12px; cursor: pointer; }
.nm-refusal-details pre { margin: 6px 0 0; padding: 8px 10px; border-radius: 8px; background: var(--nm-hover); font-size: 11.5px; line-height: 1.4; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--dsw-alias-label-secondary); }
.nm-headsup { display: flex; align-items: flex-start; gap: 8px; margin: 0 0 6px; padding: 8px 12px; border-radius: 12px; font-size: 12.5px; line-height: 1.45; background: color-mix(in srgb, var(--nm-accent) 12%, transparent); color: var(--dsw-alias-label-primary); }
.nm-headsup-icon { display: inline-flex; margin-top: 2px; color: var(--nm-accent); flex: none; }
.nm-headsup-text { flex: 1; min-width: 0; }
.nm-headsup-text .nm-ob-link.nm-inline { color: var(--nm-blue); font-weight: 600; font-size: 12.5px; }
.nm-headsup-close { width: 22px; height: 22px; flex: none; }
.nm-star-card { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; border-radius: var(--nm-radius); background: var(--nm-card); border: 1px solid var(--nm-divider); }
.nm-star-head { display: flex; gap: 10px; align-items: flex-start; }
.nm-star-icon { width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex: none; background: color-mix(in srgb, var(--nm-accent) 18%, transparent); color: var(--nm-accent); }
.nm-star-title { font-size: 13.5px; font-weight: 600; }
.nm-star-text { font-size: 12.5px; line-height: 1.45; color: var(--dsw-alias-label-secondary); }
.nm-star-actions { display: flex; gap: 8px; }
.nm-header-star { color: var(--nm-accent); }
.nm-header-star .nm-ob-link { color: var(--nm-blue); }
.nm-kbd { font-size: 12px; padding: 3px 8px; border-radius: 6px; background: var(--nm-hover); color: var(--dsw-alias-label-secondary); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; flex: none; }
.nm-hotkey { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; max-width: 60%; }
.nm-hotkey-row { display: flex; align-items: center; gap: 6px; }
.nm-hotkey-recording { border: 1px dashed var(--dsw-alias-label-primary); background: transparent; color: var(--dsw-alias-label-primary); cursor: default; font-family: inherit; }
.nm-hotkey-recording:focus-visible { outline: 2px solid var(--dsw-alias-label-primary); outline-offset: 1px; }
.nm-hotkey-hint { font-size: 12px; color: var(--dsw-alias-label-secondary); text-align: right; white-space: normal; line-height: 1.4; }
.nm-harness-rows > [data-slot] > * { border-bottom: 1px solid var(--nm-divider); }
.nm-harness-rows > [data-slot] > :last-child { border-bottom: 0; }
/* Connectors, Muse's shape: a search, connected / available rows with a trailing Connect, a detail per connector */
.nm-cn-search { margin: 0 0 4px; height: 36px; }
.nm-cn-row { padding: 0; gap: 0; }
.nm-cn-main { flex: 1; min-width: 0; display: flex; align-items: center; gap: 12px; padding: 11px 0; border: 0; background: none; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.nm-cn-main:hover .nm-row-title { color: var(--nm-accent); }
.nm-cn-connect { flex: none; border: 0; background: none; color: var(--nm-blue); font: inherit; font-size: 13px; font-weight: 600; padding: 6px 10px; border-radius: 8px; cursor: pointer; }
.nm-cn-connect:hover { background: var(--nm-hover); }
.nm-cn-connect-big { background: var(--nm-blue); color: #fff; padding: 7px 16px; border-radius: 999px; }
.nm-cn-connect-big:hover { background: var(--nm-blue-hover); }
.nm-cn-back { align-self: flex-start; display: inline-flex; align-items: center; gap: 2px; border: 0; background: none; color: var(--dsw-alias-label-secondary); font: inherit; font-size: 13px; padding: 4px 8px 4px 2px; border-radius: 8px; cursor: pointer; margin-bottom: -6px; }
.nm-cn-back:hover { background: var(--nm-hover); color: var(--dsw-alias-label-primary); }
.nm-cn-hero { display: flex; align-items: flex-start; gap: 14px; }
.nm-cn-hero-icon { flex: none; width: 48px; height: 48px; border-radius: 14px; display: inline-flex; align-items: center; justify-content: center; background: var(--nm-card); color: var(--dsw-alias-label-primary); }
.nm-cn-hero-main { flex: 1; min-width: 0; }
.nm-cn-hero-main h3 { margin: 4px 0 4px; font-size: 17px; font-weight: 600; }
.nm-cn-hero-main p { margin: 0; font-size: 13px; line-height: 1.5; color: var(--dsw-alias-label-secondary); }
.nm-cn-state { margin-top: 10px; }
.nm-cn-consent { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 14px; }
.nm-cn-consent-lead { margin: 4px 0 0; font-size: 13.5px; line-height: 1.5; color: var(--dsw-alias-label-secondary); }
.nm-sheet-body .nm-card + h2, .nm-sheet-body h2 { font-size: 13px; font-weight: 600; margin: 18px 0 8px; color: var(--dsw-alias-label-tertiary); text-transform: uppercase; letter-spacing: 0.06em; }
.nm-cn-steps { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 10px; font-size: 13.5px; line-height: 1.5; }
.nm-cn-command { position: relative; margin-top: 6px; }
.nm-cn-command pre { margin: 0; padding: 10px 40px 10px 12px; border-radius: 10px; background: var(--nm-card); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-break: break-all; }
.nm-cn-copy { position: absolute; top: 6px; right: 6px; width: 28px; height: 28px; border: 0; border-radius: 8px; background: transparent; color: var(--dsw-alias-label-secondary); display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
.nm-cn-copy:hover { background: var(--nm-hover); color: var(--dsw-alias-label-primary); }
.nm-cn-redirect { font-size: 12px; padding: 2px 6px; border-radius: 6px; background: var(--dsw-alias-bg-layer-2); user-select: all; white-space: nowrap; }
.nm-cn-redirect-line { display: inline-flex; flex-wrap: wrap; align-items: baseline; gap: 4px 6px; }
.nm-cn-redirect-copy { border: 0; padding: 0 4px; background: transparent; color: var(--nm-accent, var(--dsw-alias-label-primary)); font: inherit; font-size: 12.5px; cursor: pointer; }
.nm-cn-redirect-copy:hover { text-decoration: underline; }
.nm-cn-chips { margin: 2px 0 6px; }
.nm-chip-on, .nm-chip-on:hover { background: var(--dsw-alias-label-primary); color: var(--dsw-alias-bg-layer-1, #fff); }
.nm-cn-mark { flex: none; display: inline-flex; align-items: center; justify-content: center; border-radius: 10px; background: #fff; box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.08); }
.nm-cn-mark svg { display: block; }
.nm-cn-mark-letter { color: #fff; font-weight: 700; letter-spacing: 0; box-shadow: none; }
.nm-cn-builtin-mark { flex: none; }
.nm-cn-static { cursor: default; }
.nm-cn-static:hover .nm-row-title { color: inherit; }
.nm-cn-sub-warn { color: #c2410c; }
.nm-cn-warn { margin: 6px 0 0; font-size: 13px; line-height: 1.5; color: #c2410c; }
.nm-cn-hero-mark { flex: none; display: inline-flex; }
.nm-cn-hero-mark .nm-cn-mark { border-radius: 14px; }
.nm-cn-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.nm-cn-pill { min-height: 34px; padding: 0 14px; font-size: 13px; }
.nm-cn-pill-danger, .nm-cn-pill-danger:hover:not(:disabled) { background: #c2410c; color: #fff; box-shadow: none; }
.nm-cn-pill-spin { border-color: rgba(255, 255, 255, 0.35); border-top-color: #fff; }
.nm-cn-tools-lead { margin: 10px 0 -4px; white-space: normal; line-height: 1.5; }
.nm-cn-tool-off .nm-row-main { opacity: 0.55; }
.nm-cn-url code { font-size: 11.5px; word-break: break-all; }
.nm-cn-registry { margin-top: 4px; }
.nm-cn-registry-note { margin: 10px 0; }
.nm-cn-wait { display: flex; align-items: center; gap: 10px; margin: 0 0 14px; padding: 12px 14px; border-radius: 12px; background: var(--nm-card); font-size: 13.5px; line-height: 1.5; }
.nm-cn-wait-failed { flex-direction: column; align-items: flex-start; gap: 2px; }
.nm-cn-wait-failed strong { color: #c2410c; }
.nm-cn-key-where { margin: 0 0 10px; font-size: 13.5px; line-height: 1.5; color: var(--dsw-alias-label-secondary); }
.nm-cn-key, .nm-cn-field { margin-bottom: 10px; font-size: 14px; }
.nm-cn-custom-lead { margin: 0 0 12px; }
.nm-cn-more { border: 0; background: none; color: var(--nm-blue); font: inherit; font-size: 13px; padding: 0 0 10px; cursor: pointer; }
.nm-sheet-body .nm-fine { margin-top: 14px; }

.nm-close { width: 30px; height: 30px; border: 0; padding: 0; border-radius: 50%; background: var(--nm-hover); color: var(--dsw-alias-label-secondary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.nm-close:hover { background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); }
.nm-advanced-note { font-size: 12.5px; line-height: 1.5; color: var(--dsw-alias-label-tertiary); margin: 0 0 14px; }
.nm-section { display: flex; flex-direction: column; gap: 16px; }
.nm-section h2 { font-size: 13px; font-weight: 600; margin: 8px 0 -8px; color: var(--dsw-alias-label-tertiary); text-transform: uppercase; letter-spacing: 0.06em; }
.nm-section p { font-size: 13.5px; line-height: 1.55; color: var(--dsw-alias-label-secondary); margin: 0; }

/* ---- the first run: the whole window ----------------------------------- */
.nm-ob { position: fixed; inset: 0; z-index: 90; display: flex; align-items: center; justify-content: center; background: var(--nm-base); color: var(--dsw-alias-label-primary); font-family: var(--nm-font); outline: none; animation: nm-fade-in 220ms ease-out; }
.nm-ob.nm-ob-fading { opacity: 0; transition: opacity 240ms ease-in; }
@keyframes nm-fade-in { from { opacity: 0; } to { opacity: 1; } }
.nm-ob-drag { position: absolute; top: 0; left: 0; right: 0; height: 40px; }
.nm-ob-center { display: flex; flex-direction: column; align-items: center; gap: 18px; width: min(360px, calc(100vw - 48px)); text-align: center; animation: nm-rise 260ms ease-out; }
@keyframes nm-rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
.nm-ob-title { font-size: 26px; font-weight: 600; letter-spacing: -0.01em; margin: 6px 0 2px; line-height: 1.25; }
.nm-ob-title-sm { font-size: 22px; }
.nm-ob-sub { font-size: 14px; line-height: 1.55; color: var(--dsw-alias-label-secondary); margin: -6px 0 0; }
.nm-ob-cta { min-width: 132px; margin-top: 6px; }
.nm-ob-wide { width: 100%; }
.nm-ob-form { gap: 14px; }
.nm-ob-form .nm-ob-title { margin-bottom: 8px; }
.nm-ob-fine { font-size: 12px; line-height: 1.55; color: var(--dsw-alias-label-tertiary); margin: -4px 0 0; }
.nm-ob-fine a { color: var(--dsw-alias-label-secondary); text-decoration: underline; text-underline-offset: 2px; }
.nm-ob-links { display: flex; align-items: center; gap: 10px; margin-top: 2px; }
.nm-ob-sep { color: var(--dsw-alias-label-dimmed); }
.nm-ob-link { border: 0; background: transparent; padding: 6px 8px; border-radius: 8px; color: var(--dsw-alias-label-tertiary); font: inherit; font-size: 13px; cursor: pointer; }
.nm-ob-link:hover { color: var(--dsw-alias-label-primary); background: var(--nm-hover); }
.nm-ob-link.nm-inline { padding: 0 2px; font-size: 12px; text-decoration: underline; text-underline-offset: 2px; }
.nm-ob-link.nm-inline:hover { background: transparent; }
.nm-ob-link:disabled { opacity: 0.5; cursor: default; }
.nm-ob-error { font-size: 13px; color: var(--dsw-alias-state-error-primary, #d2453d); }
.nm-code { position: relative; display: flex; gap: 8px; justify-content: center; cursor: text; }
.nm-code-input { position: absolute; inset: 0; width: 100%; opacity: 0; border: 0; font-size: 16px; }
.nm-code-box { width: 46px; height: 54px; border-radius: 12px; background: var(--nm-field); border: 1px solid var(--nm-field-border); display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 600; transition: border-color 120ms; }
.nm-code:focus-within .nm-code-caret { border-color: var(--nm-blue); box-shadow: 0 0 0 3px color-mix(in srgb, var(--nm-blue) 25%, transparent); }
.nm-ob-slide-wrap { position: relative; display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; }
.nm-ob-pager { position: absolute; top: 16px; right: 18px; display: flex; gap: 6px; }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) .nm-ob-pager { top: 14px; }
.nm-ob-pager-btn { width: 30px; height: 30px; border: 0; border-radius: 50%; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.nm-ob-pager-btn:hover:not(:disabled) { background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); }
.nm-ob-pager-btn:disabled { opacity: 0.35; cursor: default; }
.nm-ob-slide { width: min(400px, calc(100vw - 48px)); gap: 14px; }
.nm-ob-slide .nm-ob-wide { width: auto; min-width: 150px; align-self: center; }
.nm-ob-skip { border: 0; background: transparent; padding: 8px 14px; border-radius: 10px; color: var(--dsw-alias-label-primary); font: inherit; font-size: 15px; cursor: pointer; }
.nm-ob-skip:hover { background: var(--nm-hover); }
.nm-ob-dots { display: flex; gap: 6px; justify-content: center; margin-top: -4px; }
.nm-ob-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--dsw-alias-label-dimmed); opacity: 0.55; }
.nm-ob-dot.nm-on { background: var(--dsw-alias-label-primary); opacity: 1; }
.nm-ob-mode { flex: none; font-size: 12.5px; color: var(--dsw-alias-label-secondary); }
.nm-ob-folder { display: inline-flex; align-items: center; gap: 8px; max-width: 100%; align-self: center; padding: 6px 12px; border-radius: 999px; background: var(--nm-card); font-size: 12.5px; color: var(--dsw-alias-label-secondary); }
.nm-ob-folder-path { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nm-ob-card-label { align-self: flex-start; font-size: 12px; color: var(--dsw-alias-label-tertiary); margin: 0 0 -8px 6px; }
.nm-ob-card { width: 100%; box-sizing: border-box; border-radius: 16px; background: var(--nm-card); padding: 2px 14px; text-align: left; box-shadow: 0 0 0 1px var(--nm-divider); }
.nm-ob-row { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--nm-divider); }
.nm-ob-row:last-child { border-bottom: 0; }
.nm-ob-row-icon { width: 34px; height: 34px; border-radius: 10px; display: inline-flex; align-items: center; justify-content: center; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); flex: none; }
.nm-ob-row-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.nm-ob-row-title { font-size: 14px; font-weight: 500; }
.nm-ob-row-sub { font-size: 12.5px; color: var(--dsw-alias-label-tertiary); }
.nm-ob-path { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; direction: rtl; text-align: left; }
.nm-ob-relaunch { display: flex; align-items: center; gap: 12px; margin-top: 10px; padding: 10px 12px; border-radius: 12px; background: color-mix(in srgb, #2f9e5f 12%, transparent); font-size: 12.5px; line-height: 1.4; color: var(--dsw-alias-label-secondary); }
.nm-ob-relaunch > span { flex: 1; }
.nm-row > .nm-ob-relaunch, .nm-card > .nm-ob-relaunch { margin: 6px 12px 10px; }
.nm-ob-granted { width: 28px; height: 28px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; background: color-mix(in srgb, #2f9e5f 22%, transparent); color: #2f9e5f; flex: none; }
.nm-ob-granted.nm-ob-pending { background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-dimmed); }
.nm-art { display: block; margin: 0 auto 4px; }
.nm-art-back { fill: var(--dsw-alias-bg-layer-2); }
.nm-art-mid { fill: var(--dsw-alias-bg-layer-3); }
.nm-art-front { fill: var(--nm-card); stroke: var(--nm-divider); }
.nm-art-dot { fill: var(--dsw-alias-label-dimmed); }
.nm-art-line { fill: var(--dsw-alias-bg-layer-3); }
.nm-art-cursor { fill: var(--dsw-alias-label-primary); }
.nm-art-accent { fill: var(--nm-accent); }
.nm-art-link { stroke: var(--nm-accent); stroke-width: 2.5; stroke-dasharray: 4 6; stroke-linecap: round; }

/* ---- the rooms: Feed, Ideas, Goals, Library ---------------------------- */
.nm-room { position: relative; display: flex; flex-direction: column; height: 100%; min-height: 0; color: var(--dsw-alias-label-primary); background: var(--nm-base); }
.nm-room-top { flex: none; height: 8px; }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) .nm-room-top { height: 30px; }
.nm-room-head { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 40px 6px; max-width: 920px; width: 100%; box-sizing: border-box; margin: 0 auto; }
.nm-room-title { font-size: 26px; font-weight: 600; letter-spacing: -0.01em; margin: 0; }
.nm-room-actions { display: flex; align-items: center; gap: 8px; }
.nm-room-busy { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--dsw-alias-label-tertiary); margin-right: 4px; }
.nm-spinner-sm { width: 14px; height: 14px; border-width: 2px; }
.nm-round-btn { width: 36px; height: 36px; border: 0; padding: 0; border-radius: 50%; background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.nm-round-btn:hover { background: var(--dsw-alias-bg-layer-2); }
.nm-more.nm-icon-btn { border-radius: 50%; background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); }
.nm-more.nm-icon-btn:hover { background: var(--dsw-alias-bg-layer-2); }
.nm-more.nm-quiet { background: transparent; color: var(--dsw-alias-label-secondary); opacity: 0; transition: opacity 120ms; }
.nm-more.nm-quiet:hover { background: var(--dsw-alias-bg-layer-3); }
:is(.nm-post, .nm-idea, .nm-goal, .nm-lib-card, .nm-auto-row):hover .nm-more.nm-quiet, .nm-more.nm-quiet:focus-visible, .nm-more.nm-quiet[aria-expanded="true"] { opacity: 1; }
.nm-room-body { flex: 1; min-height: 0; overflow-y: auto; }
.nm-room-inner { max-width: 920px; margin: 0 auto; padding: 4px 40px 48px; box-sizing: border-box; }
.nm-room-h2 { font-size: 15px; font-weight: 600; margin: 26px 0 8px; }
.nm-room-error { font-size: 13px; color: var(--dsw-alias-state-error-primary, #d2453d); padding: 8px 0; }
.nm-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; min-height: 320px; text-align: center; color: var(--dsw-alias-label-tertiary); }
.nm-empty-icon { display: inline-flex; color: var(--dsw-alias-label-dimmed); }
.nm-empty-text { font-size: 14px; }
.nm-empty-sub { max-width: 420px; font-size: 13px; line-height: 1.55; margin: 0 0 6px; }
.nm-menu-item.nm-danger { color: var(--dsw-alias-state-error-primary, #d2453d); }
.nm-pill-danger { background: var(--dsw-alias-state-error-primary, #d2453d); }
.nm-pill-danger:hover:not(:disabled) { background: #b8352f; }
/* sheets */
/* our className lands on the primitives' dialog card itself: resize and recolour it, the sheet fills it */
.nm-sheet-modal[role="dialog"] { width: min(520px, 100%); max-height: 100%; padding: 0; gap: 0; border-radius: 18px; background: var(--nm-base); color: var(--dsw-alias-label-primary); box-shadow: 0 24px 80px rgba(0,0,0,0.35), 0 0 0 1px var(--nm-divider); }
.nm-sheet-modal.nm-wide[role="dialog"] { width: min(600px, 100%); }
.nm-sheet { width: 100%; max-height: 100%; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.nm-sheet-head { flex: none; display: flex; align-items: center; gap: 8px; padding: 16px 16px 8px 20px; }
.nm-sheet-title { flex: 1; min-width: 0; font-size: 17px; font-weight: 600; margin: 0; line-height: 1.3; }
.nm-sheet-body { flex: 1; min-height: 0; overflow-y: auto; padding: 4px 20px 16px; }
.nm-sheet-foot { flex: none; padding: 10px 16px 16px; }
.nm-sheet-actions { display: flex; align-items: center; gap: 8px; }
.nm-sheet-form { display: flex; flex-direction: column; gap: 12px; }
.nm-sheet-lead { font-size: 14px; line-height: 1.6; color: var(--dsw-alias-label-secondary); margin: 0; }
.nm-sheet-fine { font-size: 12px; line-height: 1.55; color: var(--dsw-alias-label-tertiary); margin: 0; }
.nm-textarea { box-sizing: border-box; width: 100%; padding: 12px 14px; border: 1px solid var(--nm-field-border); border-radius: 14px; background: var(--nm-field); color: var(--dsw-alias-label-primary); font: inherit; font-size: 14px; line-height: 1.55; resize: vertical; outline: none; }
.nm-textarea:focus { border-color: var(--nm-blue); box-shadow: 0 0 0 3px color-mix(in srgb, var(--nm-blue) 25%, transparent); }
.nm-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.nm-chip { border: 0; padding: 7px 12px; border-radius: 999px; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); font: inherit; font-size: 12.5px; line-height: 1.4; text-align: left; cursor: pointer; }
.nm-chip:hover { background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); }
/* markdown the rooms render */
.nm-md { font-size: 14px; line-height: 1.65; }
.nm-md p { margin: 0 0 10px; }
.nm-md p:last-child { margin-bottom: 0; }
.nm-md a { color: var(--nm-blue); text-decoration: none; }
.nm-md a:hover { text-decoration: underline; }
.nm-md ul, .nm-md ol { margin: 0 0 10px; padding-left: 22px; }
.nm-md li { margin: 2px 0; }
.nm-md li.nm-done { text-decoration: line-through; color: var(--dsw-alias-label-tertiary); }
.nm-md h2, .nm-md h3, .nm-md h4, .nm-md h5, .nm-md h6 { margin: 18px 0 8px; line-height: 1.3; }
.nm-md h2 { font-size: 20px; } .nm-md h3 { font-size: 17px; } .nm-md h4 { font-size: 15px; } .nm-md h5, .nm-md h6 { font-size: 14px; }
.nm-md code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.92em; background: var(--dsw-alias-bg-layer-2); padding: 1px 5px; border-radius: 5px; }
.nm-md pre { background: var(--dsw-alias-bg-layer-2); padding: 12px 14px; border-radius: 12px; overflow-x: auto; margin: 0 0 12px; }
.nm-md pre code { background: transparent; padding: 0; }
.nm-md blockquote { margin: 0 0 10px; padding: 2px 0 2px 14px; border-left: 3px solid var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-secondary); }
.nm-md hr { border: 0; height: 1px; background: var(--nm-divider); margin: 16px 0; }
.nm-md table { border-collapse: collapse; margin: 0 0 12px; font-size: 13.5px; }
.nm-md th, .nm-md td { padding: 6px 12px; border-bottom: 1px solid var(--nm-divider); text-align: left; vertical-align: top; }
.nm-md th { font-weight: 600; color: var(--dsw-alias-label-secondary); }
/* feed */
.nm-feed { display: flex; flex-direction: column; gap: 6px; padding-top: 10px; }
.nm-post { display: flex; gap: 14px; padding: 16px 12px 14px; border-radius: 16px; }
.nm-post:hover { background: var(--nm-hover); }
.nm-post-mark { flex: none; width: 38px; height: 38px; border-radius: 11px; background: var(--dsw-alias-bg-layer-2); display: flex; align-items: center; justify-content: center; font-size: 20px; }
.nm-post-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; }
.nm-post-head { display: flex; align-items: center; gap: 10px; }
.nm-post-title { flex: 1; min-width: 0; font-size: 15px; font-weight: 600; margin: 0; line-height: 1.4; }
.nm-post-when { flex: none; font-size: 12px; color: var(--dsw-alias-label-tertiary); }
.nm-post-body { color: var(--dsw-alias-label-primary); }
.nm-post-images { display: flex; gap: 8px; }
.nm-post-images img { display: block; max-width: 100%; max-height: 260px; border-radius: 12px; object-fit: cover; }
.nm-post-actions { display: flex; align-items: center; gap: 14px; margin-top: 2px; }
.nm-post-action { display: inline-flex; align-items: center; gap: 6px; border: 0; padding: 4px 6px; margin-left: -6px; border-radius: 8px; background: transparent; color: var(--dsw-alias-label-tertiary); font: inherit; font-size: 13px; cursor: pointer; }
.nm-post-action:hover { color: var(--dsw-alias-label-primary); background: var(--dsw-alias-bg-layer-2); }
.nm-post-action.nm-liked { color: #e0245e; }
.nm-post-time-full { margin-left: auto; font-size: 12px; color: var(--dsw-alias-label-dimmed); }
/* ideas */
.nm-ideas { padding-top: 4px; }
.nm-idea-group:first-child .nm-room-h2 { margin-top: 10px; }
.nm-idea { display: flex; align-items: flex-start; gap: 14px; padding: 12px 12px; margin: 0 -12px; border-radius: 14px; cursor: pointer; }
.nm-idea:hover, .nm-idea:focus-visible { background: var(--nm-hover); outline: none; }
.nm-idea-mark { flex: none; width: 40px; height: 40px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 24px; }
.nm-idea-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.nm-idea-title { font-size: 15px; font-weight: 600; line-height: 1.4; }
.nm-idea-detail { font-size: 13px; line-height: 1.5; color: var(--dsw-alias-label-tertiary); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.nm-idea-done { flex: none; color: var(--dsw-alias-state-success-primary, #2f9e5f); display: inline-flex; margin-top: 4px; }
.nm-idea-card section { margin-top: 18px; }
.nm-idea-card h3 { font-size: 14px; font-weight: 600; margin: 0 0 6px; }
.nm-idea-card p { font-size: 14px; line-height: 1.6; margin: 0; color: var(--dsw-alias-label-secondary); }
.nm-idea-card ul { margin: 0; padding-left: 20px; font-size: 14px; line-height: 1.6; color: var(--dsw-alias-label-secondary); }
.nm-idea-prompt { margin: 0; padding: 10px 14px; border-radius: 12px; background: var(--dsw-alias-bg-layer-2); font-size: 13.5px; line-height: 1.55; color: var(--dsw-alias-label-secondary); white-space: pre-wrap; }
.nm-idea-hero { display: flex; justify-content: center; margin: 2px 0 10px; }
.nm-idea-hero-mark { font-size: 40px; line-height: 1; }
.nm-idea-kind { display: flex; align-items: center; gap: 6px; margin-top: 12px; font-size: 13px; color: var(--dsw-alias-label-secondary); }
.nm-idea-actions { display: flex; gap: 8px; }
.nm-room-toast { margin: 0 0 10px; padding: 8px 12px; border-radius: 10px; background: var(--dsw-alias-bg-layer-2); font-size: 13px; color: var(--dsw-alias-label-secondary); }
/* goals: the agent's progress and the flag */
.nm-goal-bar { position: relative; height: 5px; border-radius: 999px; background: var(--dsw-alias-bg-layer-2); overflow: hidden; margin-top: 6px; }
.nm-goal-bar > span { position: absolute; inset: 0 auto 0 0; border-radius: 999px; background: var(--nm-accent, #1d6fe0); }
.nm-goal-bar.nm-attention > span { background: #d9480f; }
.nm-goal-flag { margin-left: 8px; font-size: 11px; font-weight: 600; color: #d9480f; }
.nm-goal-progress { display: flex; align-items: center; gap: 10px; margin: 10px 0 4px; }
.nm-goal-progress .nm-goal-bar { flex: 1; margin: 0; }
.nm-goal-pct { font-size: 12px; color: var(--dsw-alias-label-secondary); white-space: nowrap; }
.nm-goal-steps { list-style: none; margin: 10px 0 0; padding: 0; display: grid; gap: 6px; font-size: 14px; }
.nm-goal-steps li { display: flex; align-items: flex-start; gap: 8px; }
.nm-goal-steps li svg { flex: none; margin-top: 3px; color: var(--dsw-alias-label-secondary); }
/* the agent's app fences as cards in the chat (goal created, goal update, feed post, new look) */
.nm-fence { margin: 6px 0; padding: 12px 14px; border-radius: 16px; border: 1px solid var(--dsw-alias-divider, rgba(127,127,127,0.25)); background: var(--dsw-alias-bg-layer-1, transparent); font-size: 14px; }
.nm-fence-kind { font-size: 12px; font-weight: 500; color: var(--dsw-alias-label-secondary); }
.nm-fence-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.nm-fence-status { font-size: 12px; font-weight: 600; color: var(--nm-accent, #1d6fe0); }
.nm-fence-status.nm-attention { color: #d9480f; }
.nm-fence-title { margin-top: 4px; font-size: 16px; font-weight: 600; }
.nm-fence-sub { margin-top: 3px; font-size: 13px; line-height: 1.5; color: var(--dsw-alias-label-secondary); }
.nm-fence-steps { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 4px; font-size: 13px; }
.nm-fence-steps li::before { content: '☐'; margin-right: 8px; color: var(--dsw-alias-label-secondary); }
.nm-fence-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 8px; }
.nm-fence-fine { font-size: 12px; color: var(--dsw-alias-label-secondary); }
.nm-fence-btn { border: 0; background: transparent; color: var(--nm-accent, #1d6fe0); font: inherit; font-size: 13px; font-weight: 600; padding: 4px 8px; border-radius: 8px; cursor: pointer; }
.nm-fence-btn:hover { background: var(--dsw-alias-bg-layer-2); }
.nm-fence-row { display: flex; align-items: center; gap: 10px; }
.nm-fence-main { flex: 1; min-width: 0; }
.nm-fence-tile { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 10px; background: var(--dsw-alias-bg-layer-2); font-size: 18px; flex: none; }
.nm-fence-face { width: 44px; height: 44px; border-radius: 50%; object-fit: cover; flex: none; }
.nm-fence .nm-goal-bar { margin-top: 10px; height: 6px; }
.nm-clamp2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
/* goals */
.nm-goals { padding-top: 8px; }
.nm-goals-label { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 500; color: var(--dsw-alias-state-success-primary, #2f9e5f); padding: 6px 0 10px; }
.nm-goals-label.nm-muted { color: var(--dsw-alias-label-tertiary); margin-top: 16px; }
.nm-goal { display: flex; align-items: flex-start; gap: 14px; padding: 12px 12px; margin: 0 -12px; border-radius: 14px; cursor: pointer; }
.nm-goal:hover, .nm-goal:focus-visible { background: var(--nm-hover); outline: none; }
.nm-goal.nm-done .nm-goal-title { color: var(--dsw-alias-label-tertiary); text-decoration: line-through; }
.nm-check { flex: none; width: 18px; height: 18px; margin-top: 2px; border-radius: 5px; border: 1.5px solid var(--dsw-alias-label-dimmed); background: transparent; color: #fff; padding: 0; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.nm-check:hover { border-color: var(--nm-blue); }
.nm-check.nm-on { background: var(--nm-blue); border-color: var(--nm-blue); }
.nm-goal-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.nm-goal-title { font-size: 15px; font-weight: 500; line-height: 1.4; }
.nm-goal-sub { font-size: 13px; line-height: 1.5; color: var(--dsw-alias-label-tertiary); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.nm-goals-create { margin-top: 28px; }
.nm-cat-row { display: flex; align-items: center; gap: 12px; width: 100%; padding: 11px 12px; margin: 0 -12px; width: calc(100% + 24px); border: 0; border-radius: 12px; background: transparent; color: inherit; font: inherit; font-size: 15px; text-align: left; cursor: pointer; }
.nm-cat-row:hover { background: var(--nm-hover); }
.nm-cat-icon { display: inline-flex; width: 24px; justify-content: center; color: var(--dsw-alias-label-secondary); }
.nm-cat-label { flex: 1; }
.nm-goal-card { display: flex; flex-direction: column; gap: 14px; }
.nm-goal-summary { font-size: 14px; margin: 0; color: var(--dsw-alias-label-primary); }
.nm-auto-card { border-radius: 14px; background: var(--dsw-alias-bg-layer-1); padding: 10px 12px 6px; }
.nm-auto-head { font-size: 11.5px; font-weight: 600; letter-spacing: 0.04em; color: var(--dsw-alias-label-tertiary); padding: 0 2px 8px; }
.nm-auto-empty { font-size: 13px; line-height: 1.5; color: var(--dsw-alias-label-tertiary); padding: 0 2px 8px; }
.nm-auto-row { display: flex; align-items: center; gap: 12px; padding: 8px 6px; border-radius: 10px; }
.nm-auto-row:hover { background: var(--nm-hover); }
.nm-auto-icon { width: 34px; height: 34px; border-radius: 10px; display: inline-flex; align-items: center; justify-content: center; background: color-mix(in srgb, var(--nm-blue) 22%, transparent); color: var(--nm-blue); flex: none; }
.nm-auto-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.nm-auto-title { font-size: 14px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-auto-sub { font-size: 12.5px; color: var(--dsw-alias-label-tertiary); }
.nm-goal-h3 { font-size: 16px; font-weight: 600; margin: 6px 0 0; }
.nm-day-label { font-size: 11.5px; font-weight: 600; letter-spacing: 0.06em; color: var(--dsw-alias-label-tertiary); padding: 8px 0 6px; }
.nm-act { display: flex; align-items: flex-start; gap: 10px; padding: 7px 0; }
.nm-act-icon { color: var(--dsw-alias-state-success-primary, #2f9e5f); display: inline-flex; margin-top: 2px; flex: none; }
.nm-act-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.nm-act-title { font-size: 14px; font-weight: 500; line-height: 1.4; }
.nm-act-text { font-size: 13px; line-height: 1.5; color: var(--dsw-alias-label-tertiary); }
/* library */
.nm-lib { flex-direction: row; }
.nm-lib-col { flex: none; width: 212px; display: flex; flex-direction: column; gap: 2px; padding: 0 10px 12px; box-sizing: border-box; border-right: 1px solid var(--nm-divider); }
.nm-lib-col-top { height: 10px; flex: none; }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) .nm-lib-col-top { height: 30px; }
.nm-lib-search { display: flex; align-items: center; gap: 8px; height: 34px; margin: 0 2px 10px; padding: 0 10px; border-radius: 10px; background: var(--nm-field); border: 1px solid var(--nm-field-border); color: var(--dsw-alias-label-tertiary); }
.nm-lib-search:focus-within { border-color: var(--nm-blue); }
.nm-lib-search input { flex: 1; min-width: 0; border: 0; background: transparent; color: var(--dsw-alias-label-primary); font: inherit; font-size: 13.5px; outline: none; }
.nm-lib-search input::-webkit-search-cancel-button { -webkit-appearance: none; }
.nm-lib-group { font-size: 12px; color: var(--dsw-alias-label-tertiary); padding: 12px 10px 4px; }
.nm-lib-shelf { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; border: 0; border-radius: 10px; background: transparent; color: var(--dsw-alias-label-primary); font: inherit; font-size: 14px; text-align: left; cursor: pointer; }
.nm-lib-shelf svg { color: var(--dsw-alias-label-secondary); flex: none; }
.nm-lib-shelf:hover { background: var(--nm-hover); }
.nm-lib-shelf.nm-active { background: var(--dsw-alias-bg-layer-3); }
.nm-lib-spacer { flex: 1; }
.nm-lib-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.nm-lib-main .nm-room-head, .nm-lib-inner { max-width: none; padding-left: 32px; padding-right: 32px; }
.nm-lib-recent { font-size: 13px; color: var(--dsw-alias-label-tertiary); padding: 10px 0 10px; }
.nm-lib-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; }
.nm-lib-card { position: relative; border-radius: 16px; background: var(--dsw-alias-bg-layer-1); overflow: hidden; cursor: pointer; outline: none; box-shadow: 0 0 0 1px transparent; transition: box-shadow 120ms; }
.nm-lib-card:hover, .nm-lib-card:focus-visible { box-shadow: 0 0 0 1px var(--dsw-alias-bg-layer-3); }
.nm-lib-card.nm-selected { box-shadow: 0 0 0 2px var(--nm-blue); }
.nm-lib-preview { position: relative; height: 180px; background: var(--dsw-alias-bg-layer-2); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.nm-lib-preview img, .nm-lib-preview video { width: 100%; height: 100%; object-fit: cover; display: block; }
.nm-lib-preview-icon { color: var(--dsw-alias-label-dimmed); }
.nm-lib-preview-text { align-self: flex-start; width: 100%; box-sizing: border-box; padding: 16px 18px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 10.5px; line-height: 1.55; color: var(--dsw-alias-label-secondary); white-space: pre-wrap; word-break: break-word; mask-image: linear-gradient(to bottom, #000 60%, transparent); }
.nm-lib-tick { position: absolute; top: 10px; left: 10px; width: 22px; height: 22px; border-radius: 50%; border: 1.5px solid rgba(255,255,255,0.8); background: rgba(0,0,0,0.35); color: #fff; display: inline-flex; align-items: center; justify-content: center; }
.nm-lib-tick.nm-on { background: var(--nm-blue); border-color: var(--nm-blue); }
.nm-lib-caption { display: flex; align-items: center; gap: 10px; padding: 10px 10px 10px 14px; }
.nm-lib-caption-icon { display: inline-flex; color: var(--dsw-alias-label-secondary); flex: none; }
.nm-lib-caption-main { flex: 1; min-width: 0; }
.nm-lib-name { font-size: 13.5px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-lib-sub { font-size: 12px; color: var(--dsw-alias-label-tertiary); }
/* the viewer */
.nm-view-bar { flex: none; display: flex; align-items: center; gap: 8px; padding: 6px 16px 8px 12px; border-bottom: 1px solid var(--nm-divider); }
.nm-view-icon { display: inline-flex; color: var(--dsw-alias-label-secondary); }
.nm-view-name { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 40%; }
.nm-view-sub { font-size: 12px; color: var(--dsw-alias-label-tertiary); white-space: nowrap; }
.nm-view-edit-actions { display: flex; gap: 6px; }
.nm-view-body { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; }
.nm-view-md { max-width: 760px; width: 100%; margin: 0 auto; padding: 28px 40px 60px; box-sizing: border-box; font-size: 15px; }
.nm-view-md h1, .nm-view-md h2:first-child { font-size: 26px; margin-top: 0; }
.nm-view-pre { max-width: 860px; width: 100%; margin: 0 auto; padding: 24px 40px; box-sizing: border-box; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.nm-view-editor { flex: 1; min-height: 0; width: 100%; box-sizing: border-box; border: 0; outline: none; resize: none; padding: 24px 40px; background: transparent; color: var(--dsw-alias-label-primary); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13.5px; line-height: 1.6; }
.nm-view-media { flex: 1; display: flex; align-items: center; justify-content: center; padding: 24px; }
.nm-view-media img, .nm-view-media video { max-width: 100%; max-height: 100%; border-radius: 12px; }
.nm-view-audio { flex-direction: column; gap: 20px; color: var(--dsw-alias-label-secondary); }
.nm-view-frame { flex: 1; border: 0; background: #fff; }
.nm-view-loading { flex: 1; display: flex; align-items: center; justify-content: center; }

/* a Muse section inside one of the harness's own pages (General's App behavior) */
.nm-section-inline { margin-top: 18px; padding: 0; }
.nm-section-inline h2 { font-size: 13px; font-weight: 600; color: var(--dsw-alias-label-secondary); margin: 0 0 8px; }

/* ---- the Connectors / Permissions / Files / Dictation pages ---- */
.nm-row-button { width: 100%; text-align: left; background: none; border: 0; border-bottom: 1px solid var(--nm-divider); color: inherit; font: inherit; cursor: pointer; }
.nm-row-button:hover .nm-row-title { color: var(--nm-accent); }
.nm-row-button:focus-visible { outline: 2px solid var(--nm-accent); outline-offset: -2px; border-radius: 8px; }
.nm-state { display: inline-flex; align-items: center; gap: 2px; font-size: 12px; color: var(--dsw-alias-label-tertiary); flex: none; }
.nm-state-on { color: #2e9e5b; }
.nm-row-sublist { padding: 4px 0 10px 42px; }
.nm-tool-list { margin: 0; padding-left: 16px; font-size: 12.5px; line-height: 1.6; color: var(--dsw-alias-label-secondary); }
.nm-tool-list code { font-size: 12px; }
.nm-path { display: block; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; opacity: 0.8; margin-top: 2px; word-break: break-all; }
.nm-fine { font-size: 12px; color: var(--dsw-alias-label-tertiary); }

/* ---- the avatar studio ---- */
.nm-st-label { font-size: 12.5px; font-weight: 600; color: var(--dsw-alias-label-secondary); margin: 12px 0 6px; }
.nm-st-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.nm-st-cell { position: relative; aspect-ratio: 1; border-radius: 16px; overflow: hidden; border: 0; padding: 0; background: var(--nm-card); box-shadow: inset 0 0 0 1px var(--nm-field-border); cursor: pointer; display: flex; align-items: center; justify-content: center; }
.nm-st-cell:disabled { cursor: default; }
.nm-st-cell img { width: 100%; height: 100%; object-fit: cover; display: block; }
.nm-st-cell.nm-active { box-shadow: 0 0 0 3px var(--nm-accent); }
.nm-st-tag { position: absolute; left: 10px; bottom: 10px; padding: 2px 8px; border-radius: 999px; background: rgba(0,0,0,0.55); color: #fff; font-size: 11.5px; }
.nm-st-wait { font-size: 28px; color: var(--dsw-alias-label-tertiary); }
.nm-st-moods { display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; margin: 6px 0 14px; }
.nm-st-mood { position: relative; width: 92px; height: 92px; border-radius: 14px; overflow: hidden; background: var(--nm-card); box-shadow: inset 0 0 0 1px var(--nm-field-border); display: flex; align-items: center; justify-content: center; }
.nm-st-mood img { width: 100%; height: 100%; object-fit: cover; display: block; }
.nm-st-mood .nm-st-tag { left: 6px; bottom: 6px; font-size: 10.5px; padding: 1px 6px; }

/* ---- memory and the data controls ---- */
.nm-mem-add { display: flex; gap: 8px; align-items: center; }
.nm-mem-input { flex: 1; min-width: 0; height: 34px; padding: 0 12px; border-radius: 10px; border: 1px solid var(--nm-field-border); background: var(--nm-card); color: var(--dsw-alias-label-primary); font: inherit; font-size: 13px; }
.nm-mem-input:focus { outline: none; border-color: var(--nm-accent); }
.nm-mem-forget { opacity: 0; }
.nm-pf-row:hover .nm-mem-forget, .nm-mem-forget:focus-visible { opacity: 1; }
.nm-danger { color: #d93025; }
.nm-pill-danger { background: #d93025; color: #fff; }
.nm-sheet-steps { margin: 0 0 12px; padding-left: 20px; color: var(--dsw-alias-label-secondary); font-size: 13px; line-height: 1.6; }

/* ---- the trajectory of a hands run, in the chat (Trajectory.tsx) ------- */
/* The phone stage's hues: Muse's action blue and its cyan, for the marks drawn on a step's picture. */
.nm-traj { --nm-traj-accent: #0a66e4; --nm-traj-cyan: #06b6d4; display: block; margin: 8px 0 10px; }
.nm-traj-card { display: flex; flex-direction: column; gap: 8px; width: 100%; max-width: 100%; box-sizing: border-box; padding: 10px 12px 12px; border-radius: 16px; background: var(--nm-card, var(--dsw-alias-bg-layer-2)); box-shadow: inset 0 0 0 1px var(--nm-field-border, var(--nm-divider)); color: var(--dsw-alias-label-primary); outline: none; }
.nm-traj-card:focus-visible { box-shadow: inset 0 0 0 2px var(--nm-accent); }
.nm-traj-head { display: flex; align-items: center; gap: 6px; min-height: 26px; font-size: 12.5px; color: var(--dsw-alias-label-secondary); }
.nm-traj-head > svg { color: var(--nm-accent); flex: none; }
.nm-traj-title { font-weight: 600; color: var(--dsw-alias-label-primary); }
.nm-traj-sub { white-space: nowrap; }
.nm-traj-space { flex: 1; }
/* the run is on: a breathing light, not a running ring */
.nm-traj-live { width: 7px; height: 7px; border-radius: 50%; background: var(--nm-accent); flex: none; animation: nm-breathe-light 4.8s ease-in-out infinite; }
.nm-traj-nav { display: inline-flex; align-items: center; gap: 2px; }
.nm-traj-nav-sheet { margin-left: auto; margin-right: 8px; }
.nm-traj-count { min-width: 44px; text-align: center; font-size: 12px; font-variant-numeric: tabular-nums; color: var(--dsw-alias-label-secondary); }
.nm-traj-btn { width: 26px; height: 26px; border: 0; padding: 0; border-radius: 8px; background: transparent; color: var(--dsw-alias-label-secondary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.nm-traj-btn:hover:not(:disabled) { background: var(--nm-hover); color: var(--dsw-alias-label-primary); }
.nm-traj-btn:disabled { opacity: 0.35; cursor: default; }
.nm-traj-open { display: block; width: 100%; border: 0; padding: 0; background: transparent; cursor: zoom-in; text-align: left; }
.nm-traj-open:focus-visible { outline: 2px solid var(--nm-accent); outline-offset: 2px; border-radius: 12px; }
.nm-traj-picture { position: relative; max-width: 100%; border-radius: 12px; overflow: hidden; background: #111; box-shadow: 0 0 0 1px rgba(0,0,0,0.08); }
.nm-traj-picture.nm-big { width: 100%; }
.nm-traj-picture img { display: block; width: 100%; height: 100%; object-fit: contain; user-select: none; }
.nm-traj-picture.nm-gone { background: var(--nm-hover); }
.nm-traj-nopic { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; padding: 12px; text-align: center; font-size: 12.5px; color: var(--dsw-alias-label-tertiary); }
.nm-traj-marks { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
/* the action's words on the picture: the phone's label pill — dark, a hairline, a cyan→blue bar at its start */
.nm-traj-chip { position: absolute; left: 8px; top: 8px; max-width: calc(100% - 16px); box-sizing: border-box; padding: 4px 10px 4px 8px; border-radius: 999px; background: rgba(17,18,24,0.88); box-shadow: inset 0 0 0 1px rgba(255,255,255,0.1); color: #fff; font-size: 12px; line-height: 1.3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; pointer-events: none; display: inline-flex; align-items: center; gap: 7px; }
.nm-traj-chip::before { content: ''; flex: none; width: 3px; height: 12px; border-radius: 2px; background: linear-gradient(var(--nm-traj-cyan), var(--nm-traj-accent)); }
.nm-traj-chip.nm-aimed { transform: translate(14px, -50%); max-width: 46%; }
.nm-traj-chip.nm-aimed.nm-left { transform: translate(calc(-100% - 14px), -50%); }
.nm-traj-caption { font-size: 13px; font-weight: 600; line-height: 1.35; overflow-wrap: anywhere; }
.nm-traj-words { font-size: 12.5px; line-height: 1.45; color: var(--dsw-alias-label-secondary); white-space: pre-wrap; overflow-wrap: anywhere; }
.nm-clamp3 { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; white-space: normal; }
.nm-traj-strip { display: flex; gap: 6px; overflow-x: auto; padding: 2px 2px 4px; scrollbar-width: thin; }
.nm-traj-thumb { position: relative; flex: none; width: 88px; height: 56px; border: 0; padding: 0; border-radius: 8px; overflow: hidden; background: #111; cursor: pointer; box-shadow: 0 0 0 1px rgba(0,0,0,0.12); opacity: 0.72; transition: opacity 150ms, box-shadow 150ms; }
.nm-traj-thumb:hover, .nm-traj-thumb:focus-visible { opacity: 1; outline: none; }
.nm-traj-thumb.nm-on { opacity: 1; box-shadow: 0 0 0 2px var(--nm-accent); }
.nm-traj-thumb img { display: block; width: 100%; height: 100%; object-fit: cover; }
.nm-traj-thumb-gone { display: block; width: 100%; height: 100%; background: var(--nm-hover); }
.nm-traj-thumb-n { position: absolute; left: 4px; bottom: 4px; min-width: 16px; padding: 0 4px; border-radius: 6px; background: rgba(0,0,0,0.65); color: #fff; font-size: 10.5px; line-height: 16px; text-align: center; }
.nm-traj-fine { font-size: 11.5px; color: var(--dsw-alias-label-tertiary); }
.nm-traj-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.nm-traj-pill { display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 12px 0 10px; border: 0; border-radius: 999px; background: var(--nm-hover); color: var(--dsw-alias-label-primary); font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.nm-traj-pill:hover:not(:disabled) { background: var(--dsw-alias-bg-layer-3, var(--nm-hover)); }
.nm-traj-pill:disabled { opacity: 0.6; cursor: default; }
.nm-traj-pill.nm-on { background: var(--nm-accent); color: #fff; }
.nm-traj-pill.nm-stop { background: rgba(155,59,59,0.14); color: #9b3b3b; }
.nm-traj-pill.nm-stop:hover:not(:disabled) { background: rgba(155,59,59,0.24); }
.nm-traj-big { display: flex; flex-direction: column; gap: 12px; }
.nm-traj-big-foot { display: flex; align-items: flex-start; gap: 12px; }
.nm-traj-big-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
/* a run's card in the "hero" layout (no row yet): the width of the thread */
[data-conversation-content][data-content-phase="hero"] > [data-conversation-scroll] > .nm-traj { flex: 0 0 auto; width: min(var(--dsh-chat-content-width, 680px), 100%); align-self: center; box-sizing: border-box; padding: 0 var(--dsh-composer-side-clearance, 16px); }
/* the agent's face: a round frame; a clip or a still inside, or an emoji on its colour */
.nm-avatar { display: block; flex: 0 0 auto; border-radius: 50%; overflow: hidden; background: var(--dsw-alias-surface-sunken, #f1efe9); will-change: transform; transform-origin: 50% 60%; }
.nm-avatar > img, .nm-avatar > video { display: block; width: 100%; height: 100%; object-fit: cover; border-radius: 50%; }
.nm-avatar-emoji { display: block; width: 100%; height: 100%; text-align: center; user-select: none; }
@keyframes nm-breathe { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.035); } }
@keyframes nm-sway { 0%, 100% { transform: rotate(-4deg) translateY(0); } 25% { transform: rotate(0deg) translateY(-2%); } 50% { transform: rotate(4deg) translateY(0); } 75% { transform: rotate(0deg) translateY(-2%); } }
@keyframes nm-hop { 0%, 70%, 100% { transform: translateY(0) scale(1); } 78% { transform: translateY(-9%) scale(1.04, 0.97); } 86% { transform: translateY(0) scale(0.98, 1.03); } 92% { transform: translateY(-3%) scale(1); } }
.nm-avatar-idle { animation: nm-breathe 4.5s ease-in-out infinite; }
.nm-avatar-working { animation: nm-sway 2.6s ease-in-out infinite; }
.nm-avatar-waiting { animation: nm-hop 3.2s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) { .nm-avatar-idle, .nm-avatar-working, .nm-avatar-waiting { animation: none; } }
/* ---- menus we draw ---------------------------------------------------- */
.nm-menu { position: fixed; z-index: 80; min-width: 200px; padding: 6px; border-radius: 12px; background: var(--dsw-alias-bg-layer-3, var(--nm-base)); color: var(--dsw-alias-label-primary); box-shadow: 0 12px 40px rgba(0,0,0,0.28), 0 0 0 1px var(--nm-divider); display: flex; flex-direction: column; gap: 1px; }
.nm-menu-item { display: flex; align-items: center; gap: 10px; width: 100%; border: 0; text-align: left; padding: 8px 10px; border-radius: 8px; background: transparent; color: inherit; font: inherit; font-size: 13.5px; cursor: pointer; }
.nm-menu-item:hover, .nm-menu-item:focus-visible { background: var(--nm-hover); outline: none; }
.nm-menu-item svg { color: var(--dsw-alias-label-secondary); flex: none; }
.nm-menu-item-label { flex: 1; min-width: 0; }
.nm-menu-sep { height: 1px; margin: 4px 6px; background: var(--nm-divider); }
.nm-menu-hint { font-size: 11px; color: var(--dsw-alias-label-tertiary); }
.nm-ask { width: min(420px, calc(100vw - 32px)); padding: 12px 14px; border-radius: 14px; background: var(--dsw-alias-bg-primary, #fff); color: var(--dsw-alias-label-primary, inherit); box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18); border: 1px solid var(--nm-divider); display: flex; flex-direction: column; gap: 8px; }
.nm-ask-title { font-size: 12px; font-weight: 600; color: var(--dsw-alias-label-secondary); }
.nm-ask-text { font-size: 14px; line-height: 1.4; word-break: break-word; }
.nm-ask-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.nm-ask-sub { font-size: 11.5px; color: var(--dsw-alias-label-tertiary); }

.nm-select { width: auto; max-width: 240px; }

/* ---- the model picker (ModelPicker.tsx): a button, a panel with search and folded groups ---- */
.nm-mp { position: relative; flex: none; max-width: 100%; }
.nm-mp-btn { display: inline-flex; align-items: center; gap: 6px; max-width: 240px; padding: 0 10px 0 14px; cursor: pointer; text-align: left; }
.nm-mp-btn:disabled { opacity: 0.55; cursor: default; }
.nm-mp-btn svg { flex: none; color: var(--dsw-alias-label-tertiary); }
.nm-mp-btn-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.nm-mp-panel { position: fixed; z-index: 80; box-sizing: border-box; display: flex; flex-direction: column; padding: 6px; border-radius: 12px; background: var(--dsw-alias-bg-layer-3, var(--nm-base)); color: var(--dsw-alias-label-primary); box-shadow: 0 12px 40px rgba(0,0,0,0.28), 0 0 0 1px var(--nm-divider); overflow: hidden; }
.nm-mp-heads { flex: none; display: flex; flex-direction: column; gap: 1px; padding-bottom: 4px; margin-bottom: 4px; border-bottom: 1px solid var(--nm-divider); }
.nm-mp-search { flex: none; display: flex; align-items: center; gap: 6px; height: 32px; margin: 0 0 6px; padding: 0 10px; border-radius: 9px; background: var(--nm-field); border: 1px solid var(--nm-field-border); color: var(--dsw-alias-label-tertiary); }
.nm-mp-search:focus-within { border-color: var(--nm-blue); }
.nm-mp-search input { flex: 1; min-width: 0; border: 0; padding: 0; background: transparent; color: var(--dsw-alias-label-primary); font: inherit; font-size: 13.5px; outline: none; }
.nm-mp-search input::placeholder { color: var(--dsw-alias-label-tertiary); }
.nm-mp-search input::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
.nm-mp-list { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 1px; }
.nm-mp-group + .nm-mp-group { margin-top: 6px; }
.nm-mp-group-label { padding: 6px 10px 3px; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--dsw-alias-label-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-mp-row { display: flex; align-items: center; gap: 8px; width: 100%; border: 0; text-align: left; padding: 7px 10px; border-radius: 8px; background: transparent; color: inherit; font: inherit; font-size: 13.5px; cursor: pointer; }
.nm-mp-row:hover, .nm-mp-row:focus-visible, .nm-mp-more:hover, .nm-mp-more:focus-visible { background: var(--nm-hover); outline: none; }
.nm-mp-row.nm-selected { color: var(--nm-blue); }
.nm-mp-row svg { flex: none; }
.nm-mp-row-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nm-mp-more { display: block; width: 100%; border: 0; text-align: left; padding: 6px 10px; border-radius: 8px; background: transparent; color: var(--nm-blue); font: inherit; font-size: 12.5px; cursor: pointer; }
.nm-mp-none { padding: 10px; font-size: 13px; color: var(--dsw-alias-label-tertiary); }
.nm-menu-dot { display: inline-block; width: 7px; height: 7px; margin-left: 6px; border-radius: 50%; background: var(--nm-accent); vertical-align: middle; }

/* ---- the look changed from the chat (AvatarChat.tsx) ------------------ */
.nm-pf-top-space { flex: 1; }
.nm-ac { position: fixed; left: 50%; bottom: 108px; transform: translateX(-50%); z-index: 58; width: min(440px, calc(100vw - 32px)); padding: 12px 14px 14px; border-radius: 16px; background: var(--dsw-alias-bg-primary, #fff); color: var(--dsw-alias-label-primary); box-shadow: 0 18px 48px rgba(0,0,0,0.22), 0 0 0 1px var(--nm-divider); animation: nm-card-in 220ms ease-out; display: flex; flex-direction: column; gap: 10px; }
@keyframes nm-card-in { from { opacity: 0; transform: translate(-50%, 8px) scale(0.98); } to { opacity: 1; transform: translateX(-50%); } }
html[data-nm-profile] .nm-ac { left: calc(50% - 155px); }
.nm-ac-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.nm-ac-title { font-size: 12px; font-weight: 600; color: var(--dsw-alias-label-secondary); letter-spacing: 0.02em; }
.nm-ac-desc { margin: 0; font-size: 14px; line-height: 1.45; }
.nm-ac-hint, .nm-ac-err { margin: 0; font-size: 12.5px; color: var(--dsw-alias-label-secondary); }
.nm-ac-err { color: var(--dsw-alias-state-error-primary, #b42318); }
.nm-ac-status { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--dsw-alias-label-secondary); }
.nm-ac-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.nm-ac-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.nm-ac-tile { position: relative; aspect-ratio: 1; border: 0; padding: 0; border-radius: 12px; overflow: hidden; background: var(--nm-hover); cursor: pointer; display: flex; align-items: center; justify-content: center; color: var(--dsw-alias-label-secondary); font-size: 13px; }
.nm-ac-tile img { width: 100%; height: 100%; object-fit: cover; display: block; }
.nm-ac-tile:hover:not(:disabled), .nm-ac-tile:focus-visible { outline: 2px solid var(--nm-accent); outline-offset: 2px; }
.nm-ac-tile:disabled { cursor: default; }
.nm-ac-n { position: absolute; left: 8px; top: 8px; min-width: 22px; height: 22px; padding: 0 6px; border-radius: 11px; background: rgba(0,0,0,0.55); color: #fff; font-size: 12px; font-weight: 600; display: inline-flex; align-items: center; justify-content: center; }
.nm-ac-final { display: flex; flex-direction: column; align-items: center; gap: 10px; }
.nm-ac-final-img { width: 160px; height: 160px; border-radius: 16px; object-fit: cover; }
.nm-ac-done p { margin: 0 0 4px; font-size: 14px; line-height: 1.45; }
.nm-ac-share-canvas { width: 100%; max-width: 360px; aspect-ratio: 1; border-radius: 14px; display: block; margin: 10px auto 0; box-shadow: 0 6px 24px rgba(0,0,0,0.18); }

/* desk-a */
/* Belt and braces: the face, the name and the status line are a no-drag island on macOS and
   Windows alike (the header itself is no longer a drag region, see the platform block above);
   the face on the rail and the drawer's own face too. Plain boxes, no transform and no
   pointer-events games: Chromium maps drag regions from layout. */
html:is([data-nm-platform='darwin'], [data-nm-platform='win32']) :is(.nm-header, .nm-header-face, .nm-header-back, .nm-rail-face, button:has(> .nm-rail-face)) { -webkit-app-region: no-drag; }

/* The first run (C4): the phone's pages, one at a time, the dots and the gear on top. */
.nm-ob { align-items: stretch; justify-content: flex-start; flex-direction: column; }
.nm-fr-top { position: relative; flex: none; height: 56px; display: flex; align-items: center; justify-content: center; }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) .nm-fr-top { height: 64px; }
.nm-fr-dots { display: flex; gap: 7px; }
.nm-fr-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--dsw-alias-label-dimmed); opacity: 0.45; transition: opacity 200ms, background 200ms; }
.nm-fr-dot.nm-on { background: var(--dsw-alias-label-primary); opacity: 1; }
.nm-fr-gear { position: absolute; right: 16px; top: 50%; transform: translateY(-50%); width: 34px; height: 34px; border: 0; border-radius: 50%; background: transparent; color: var(--dsw-alias-label-secondary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; -webkit-app-region: no-drag; }
.nm-fr-gear:hover { background: var(--nm-hover); color: var(--dsw-alias-label-primary); }
.nm-fr-scroll { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 8px 24px 32px; }
.nm-fr-page { width: min(420px, 100%); gap: 14px; margin: auto 0; }
.nm-fr-page .nm-ob-sub { margin: -4px 0 2px; }
.nm-fr-primary { margin-top: 4px; }
/* The app's mark as a page hero (sign-in, permissions): the tile on the page background, its own hairline edge, nothing added (docs/brand.md). */
.nm-fr-hero-mark { flex: none; display: block; width: 72px; height: 72px; }
.nm-ob-form > .nm-fr-hero-mark { margin-bottom: 2px; }

/* The Devices page as cards (0.1.37): this computer first, the others in a grid (one column
   narrow, two from 560px of page), 16 px corners, a hairline so the card holds in both themes. */
.nm-dv .nm-page-inner { gap: 12px; container-type: inline-size; }
.nm-dv-head { display: flex; flex-direction: column; gap: 6px; }
.nm-dv-count { margin: 0; font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--dsw-alias-label-tertiary); }
.nm-dv-card { box-sizing: border-box; min-width: 0; border-radius: 16px; background: var(--nm-card); box-shadow: 0 0 0 1px var(--nm-divider); padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.nm-dv-top { display: flex; align-items: flex-start; gap: 12px; }
.nm-dv-glyph { flex: none; width: 44px; height: 44px; border-radius: 12px; display: inline-flex; align-items: center; justify-content: center; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); }
.nm-dv-glyph.nm-on { background: color-mix(in srgb, var(--nm-blue) 12%, transparent); color: var(--nm-blue); }
.nm-dv-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.nm-dv-name-row { display: flex; align-items: center; gap: 4px; min-width: 0; }
.nm-dv-name { font-size: 15px; font-weight: 600; line-height: 1.35; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-dv-sub { font-size: 12.5px; line-height: 1.45; color: var(--dsw-alias-label-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-dv-sub.nm-wrap { white-space: normal; }
.nm-dv-rename { display: flex; align-items: center; gap: 8px; }
.nm-dv-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.nm-dv-chip { padding: 4px 10px; border-radius: 999px; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); font-size: 12px; line-height: 1.4; font-weight: 500; }
.nm-dv-hint { margin-top: 4px; font-size: 12.5px; line-height: 1.45; color: var(--dsw-alias-label-secondary); }
.nm-dv-rows { margin: 2px -16px -10px; padding: 0 16px; border-top: 1px solid var(--nm-divider); }
.nm-dv-rows .nm-row:last-child { border-bottom: 0; }
.nm-dv-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
@container (min-width: 600px) { .nm-dv-grid { grid-template-columns: 1fr 1fr; } }
.nm-dv .nm-more.nm-icon-btn { flex: none; }
.nm-dv-chip-button { border: 0; font: inherit; font-size: 12px; font-weight: 500; line-height: 1.4; cursor: pointer; color: var(--nm-blue); background: color-mix(in srgb, var(--nm-blue) 12%, transparent); }
.nm-dv-chip-button:hover { background: color-mix(in srgb, var(--nm-blue) 20%, transparent); }

/* Settings → Coding agents (CodingPanel.tsx): the agents as tiles, the chats as rows, a chat as bubbles with a composer. */
.nm-cd-where .nm-chip { display: inline-flex; align-items: center; gap: 4px; }
.nm-cd-where-label { align-self: center; margin-left: 6px; font-size: 11.5px; color: var(--dsw-alias-label-tertiary); }
.nm-cd-agents { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.nm-cd-agent { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; min-width: 0; padding: 12px 14px; border: 0; border-radius: 16px; background: var(--nm-card); box-shadow: 0 0 0 1px var(--nm-divider); color: inherit; font: inherit; text-align: left; cursor: pointer; }
.nm-cd-agent:hover:not(:disabled) { box-shadow: 0 0 0 1px var(--nm-field-border); }
.nm-cd-agent.nm-active { box-shadow: 0 0 0 2px var(--nm-blue); }
.nm-cd-agent-off { opacity: 0.5; cursor: default; }
.nm-cd-agent-top { display: flex; align-items: center; justify-content: space-between; width: 100%; margin-bottom: 4px; }
.nm-cd-agent-name { font-size: 13.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.nm-cd-agent-sub { font-size: 11.5px; color: var(--dsw-alias-label-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.nm-cd-running { display: inline-flex; align-items: center; gap: 4px; padding: 2px 7px; border-radius: 999px; font-size: 10.5px; font-weight: 600; color: var(--dsw-alias-state-success-primary, #2f9e5f); background: color-mix(in srgb, var(--dsw-alias-state-success-primary, #2f9e5f) 12%, transparent); }
.nm-cd-glyph { flex: none; display: inline-flex; align-items: center; justify-content: center; border-radius: 30%; color: #fff; font-weight: 700; letter-spacing: 0.02em; background: #4b5563; }
.nm-cd-glyph-cursor { background: linear-gradient(135deg, #334155, #0f172a); }
.nm-cd-glyph-codex { background: linear-gradient(135deg, #10b981, #0f766e); }
.nm-cd-glyph-claude { background: linear-gradient(135deg, #fb923c, #d97706); }
.nm-cd-section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.nm-cd-section-head h2 { flex: 1; }
.nm-cd-link { display: inline-flex; align-items: center; gap: 2px; border: 0; padding: 0; background: none; color: var(--nm-blue); font: inherit; font-size: 12.5px; font-weight: 500; cursor: pointer; }
.nm-cd-row-title { display: flex; align-items: center; gap: 8px; min-width: 0; }
.nm-cd-pill { flex: none; padding: 1px 7px; border-radius: 999px; font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
.nm-cd-pill-running { color: var(--dsw-alias-state-success-primary, #2f9e5f); background: color-mix(in srgb, var(--dsw-alias-state-success-primary, #2f9e5f) 12%, transparent); }
.nm-cd-pill-active { color: var(--nm-blue); background: color-mix(in srgb, var(--nm-blue) 12%, transparent); }
.nm-cd-chat { display: flex; flex-direction: column; }
.nm-cd-chat-inner { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 10px; height: 100%; }
.nm-settings-body .nm-cd-chat-inner { height: auto; min-height: 60vh; }
.nm-cd-chat-head { display: flex; align-items: center; gap: 10px; }
.nm-cd-thread { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding: 4px 0; }
.nm-cd-msg { display: flex; flex-direction: column; gap: 2px; max-width: 100%; }
.nm-cd-from-you { align-items: flex-end; }
.nm-cd-from-agent { align-items: flex-start; }
.nm-cd-bubble { max-width: 88%; padding: 9px 14px; border-radius: 18px; font-size: 14px; line-height: 1.55; color: var(--dsw-alias-label-primary); word-break: break-word; }
.nm-cd-from-you .nm-cd-bubble { background: var(--nm-user-bubble); }
.nm-cd-from-agent .nm-cd-bubble { background: var(--nm-agent-bubble); }
.nm-cd-bubble p { margin: 0 0 6px; }
.nm-cd-bubble p:last-child { margin-bottom: 0; }
.nm-cd-bubble pre { margin: 6px 0; padding: 8px 10px; border-radius: 10px; background: rgba(0,0,0,0.08); font-size: 12px; overflow-x: auto; }
.nm-cd-pre { white-space: pre-wrap; }
.nm-cd-badge { font-size: 11px; color: var(--dsw-alias-label-tertiary); padding: 0 4px; }
.nm-cd-steps { padding: 8px 12px; border-radius: 14px; background: var(--nm-card); box-shadow: 0 0 0 1px var(--nm-divider); font-size: 12.5px; }
.nm-cd-steps-head { display: flex; align-items: center; gap: 6px; font-weight: 500; color: var(--dsw-alias-label-secondary); }
.nm-cd-steps-device { margin-left: auto; display: inline-flex; align-items: center; gap: 3px; color: var(--dsw-alias-label-tertiary); font-weight: 400; }
.nm-cd-steps-list { margin: 6px 0 0; padding: 0; list-style: none; max-height: 112px; overflow-y: auto; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; color: var(--dsw-alias-label-tertiary); }
.nm-cd-steps-list li { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.6; }
.nm-cd-caret { display: inline-block; width: 4px; height: 14px; margin-left: 4px; vertical-align: middle; background: var(--nm-accent); animation: nm-breathe-light 1.2s ease-in-out infinite; }
.nm-cd-composer { flex: none; display: flex; flex-direction: column; gap: 6px; padding-top: 6px; border-top: 1px solid var(--nm-divider); }
.nm-cd-form { display: flex; align-items: flex-end; gap: 8px; }
.nm-cd-input { flex: 1; min-width: 0; min-height: 40px; max-height: 140px; padding: 9px 12px; border-radius: 14px; border: 1px solid var(--nm-field-border); background: var(--nm-card); color: var(--dsw-alias-label-primary); font: inherit; font-size: 13.5px; line-height: 1.45; resize: none; }
.nm-cd-input:focus { outline: 2px solid var(--nm-blue); outline-offset: -1px; }
.nm-cd-input:disabled { opacity: 0.6; }
.nm-cd-input-tall { min-height: 96px; width: 100%; box-sizing: border-box; }
.nm-cd-send { flex: none; width: 40px; height: 40px; border: 0; border-radius: 50%; background: var(--nm-blue); color: #fff; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
.nm-cd-send:disabled { opacity: 0.4; cursor: default; }
.nm-cd-stop { background: var(--dsw-alias-state-error-primary, #d2453d); }
.nm-cd-label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--dsw-alias-label-tertiary); }
@media (prefers-reduced-motion: reduce) { .nm-cd-caret { animation: none; } }
.nm-fr-features { width: 100%; display: flex; flex-direction: column; gap: 4px; text-align: left; }
.nm-fr-feature { display: flex; align-items: flex-start; gap: 12px; padding: 8px 6px; }
.nm-fr-feature .nm-ob-row-icon { flex: none; }
.nm-fr-feature .nm-ob-row-sub { line-height: 1.45; }
.nm-fr-notice { width: 100%; box-sizing: border-box; text-align: left; padding: 12px 14px; border-radius: 14px; background: var(--nm-card); box-shadow: 0 0 0 1px var(--nm-divider); display: flex; flex-direction: column; gap: 6px; }
.nm-fr-notice-title { font-size: 13.5px; font-weight: 600; }
.nm-fr-notice p { margin: 0; font-size: 12.5px; line-height: 1.5; color: var(--dsw-alias-label-secondary); }
.nm-fr-notice-closing { color: var(--dsw-alias-label-tertiary) !important; }
.nm-fr-choices { width: 100%; display: flex; flex-direction: column; gap: 10px; }
.nm-fr-choice { display: flex; width: 100%; box-sizing: border-box; text-align: left; padding: 14px 16px; border-radius: 14px; border: 1px solid var(--nm-divider); background: var(--nm-card); color: inherit; font: inherit; cursor: pointer; }
.nm-fr-choice:hover:not(:disabled) { border-color: var(--nm-blue); background: var(--nm-selected); }
.nm-fr-choice:disabled { opacity: 0.5; cursor: default; }
.nm-fr-choice .nm-ob-row-sub { line-height: 1.45; margin-top: 2px; }
.nm-fr-granted { display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; color: #2f9e5f; }

/* The first conversation: the app's opening lines as agent bubbles, and the name chooser. */
.nm-intro-host { width: 100%; max-width: var(--dsh-chat-content-width, 760px); box-sizing: border-box; margin: 0 auto; padding: 12px 0 0; }
html[data-nm-muse] [data-conversation-scroll]:has(> .nm-intro-host):has([class*="_composerHero"]) { justify-content: flex-start; }
html[data-nm-muse] [data-conversation-scroll]:has(> .nm-intro-host) [class*="_composerHero"] { margin-top: auto; }
.nm-intro { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
.nm-intro-bubble { width: fit-content; max-width: 100%; box-sizing: border-box; background: var(--nm-agent-bubble); border-radius: 20px; padding: 10px 16px; font-size: 15px; line-height: 1.5; white-space: pre-wrap; animation: nm-rise 260ms ease-out; }
.nm-naming { display: flex; flex-direction: column; gap: 8px; width: min(360px, 100%); box-sizing: border-box; margin: 8px 0; padding: 14px; border-radius: 16px; background: var(--nm-card); box-shadow: 0 0 0 1px var(--nm-divider); }
.nm-naming-title { font-size: 13px; font-weight: 600; color: var(--dsw-alias-label-secondary); margin-bottom: 2px; }
.nm-naming-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; box-sizing: border-box; padding: 11px 14px; border-radius: 12px; border: 1px solid var(--nm-divider); background: var(--nm-base); color: var(--dsw-alias-label-primary); font: inherit; font-size: 15px; text-align: left; cursor: pointer; transition: opacity 200ms, border-color 200ms; }
.nm-naming-row:hover:not(:disabled) { border-color: var(--nm-blue); }
.nm-naming-row:disabled { cursor: default; }
.nm-naming-row.nm-selected { border: 1.5px solid var(--nm-blue); color: var(--nm-blue); }
.nm-naming-row.nm-dimmed { opacity: 0.4; }
.nm-naming-custom { border-style: dashed; color: var(--dsw-alias-label-tertiary); background: transparent; }

/* The Feed (C5): the intro card, the "how" card under the empty state, the routine row in the sliders. */
.nm-feed-intro { display: flex; flex-direction: column; gap: 8px; margin: 0 0 14px; padding: 14px 16px; border-radius: var(--nm-radius); background: var(--nm-card); border: 1px solid var(--nm-divider); }
.nm-feed-intro-title { font-size: 14px; font-weight: 600; }
.nm-feed-intro-body { margin: 0; font-size: 13px; line-height: 1.5; color: var(--dsw-alias-label-secondary); }
.nm-feed-intro-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 2px; }
.nm-feed-how { width: min(360px, 100%); box-sizing: border-box; text-align: left; margin: 6px 0 2px; padding: 12px 14px; border-radius: 14px; background: var(--nm-card); border: 1px solid var(--nm-divider); }
.nm-feed-how-title { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
.nm-feed-how p { margin: 0; font-size: 12.5px; line-height: 1.5; color: var(--dsw-alias-label-secondary); }
.nm-feed-routine { display: flex; align-items: center; gap: 10px; margin-top: 6px; font-size: 13.5px; }
.nm-feed-routine-label { flex: 1; }
.nm-field-time { width: auto; min-width: 0; padding: 4px 8px; font: inherit; font-size: 13px; }
/* The version (C2): the two lines under one title. */
.nm-version-row .nm-row-main { gap: 3px; }
.nm-version-line { white-space: normal; }

/* desk-b */
/* Computer use: the "try it" rows, the runtime row, the black-screen notice; Media: the clips. */
.nm-hc-result { display: flex; align-items: center; gap: 10px; margin: 0 12px 10px; padding: 10px 12px; border-radius: 12px; font-size: 12.5px; line-height: 1.4; color: var(--dsw-alias-label-secondary); }
.nm-hc-result > span.nm-wrap { flex: 1; min-width: 0; }
.nm-hc-ok { background: color-mix(in srgb, #2f9e5f 12%, transparent); }
.nm-hc-ok > svg { color: #2f9e5f; flex: none; }
.nm-hc-bad { background: color-mix(in srgb, #d9534f 12%, transparent); color: var(--dsw-alias-label-primary); }
.nm-hc-thumb { width: 96px; height: auto; max-height: 72px; object-fit: cover; border-radius: 8px; flex: none; box-shadow: 0 1px 4px rgba(0,0,0,0.25); background: #000; }
.nm-hc-black { width: 48px; height: 32px; border-radius: 6px; background: #000; flex: none; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.2); }
.nm-hc-actions { display: inline-flex; gap: 8px; flex: none; flex-wrap: wrap; justify-content: flex-end; }
.nm-hc-live { margin-left: 8px; font-size: 11px; font-weight: 500; padding: 1px 7px; border-radius: 999px; background: color-mix(in srgb, #d9534f 14%, transparent); color: #c9302c; vertical-align: 1px; }
.nm-hc-live.nm-hc-live-ok { background: color-mix(in srgb, #2f9e5f 16%, transparent); color: #2f9e5f; }
.nm-hc-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; word-break: break-all; }
.nm-hc-runtime-bad { background: color-mix(in srgb, #d9534f 10%, transparent); }
.nm-hc-runtime-bad .nm-row-sub { color: var(--dsw-alias-label-primary); }
.nm-hc-black-notice { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin: 0 0 12px; padding: 12px 14px; border-radius: 14px; background: #1b1b1f; color: #fff; border: 2px solid #d9534f; box-shadow: 0 8px 28px rgba(0,0,0,0.35); font-size: 13px; line-height: 1.45; max-width: 560px; }
.nm-hc-black-notice .nm-hc-black-text { flex: 1 1 260px; display: flex; flex-direction: column; gap: 4px; }
.nm-hc-black-notice strong { font-size: 14px; }
.nm-hc-black-notice .nm-pill { background: #fff; color: #1b1b1f; }
.nm-hc-black-notice .nm-pill.nm-pill-ghost { background: transparent; color: #fff; border: 1px solid rgba(255,255,255,0.4); }
.nm-hc-compact { padding: 8px 12px; font-size: 12.5px; }
.nm-md-clip { width: 44px; height: 44px; border-radius: 50%; object-fit: cover; flex: none; background: var(--dsw-alias-bg-layer-2); }
.nm-md-clip-none { display: inline-block; border: 1px dashed var(--nm-divider); background: transparent; }
.nm-md-bar { height: 4px; margin: 0 14px 12px; border-radius: 999px; background: var(--dsw-alias-bg-layer-3); overflow: hidden; }
.nm-md-bar > span { display: block; height: 100%; background: var(--nm-accent, #0064d4); border-radius: 999px; transition: width 300ms; }
.nm-md-failed { color: #c9302c; }
`

/** Put the stylesheet in the head once and mark the document as ours. */
export function ensureStyles(): () => void {
  const root = document.documentElement
  root.setAttribute('data-nanomuse', '')
  let style = document.getElementById(STYLE_ID) as HTMLStyleElement | null
  if (!style) {
    style = document.createElement('style')
    style.id = STYLE_ID
    document.head.appendChild(style)
  }
  style.textContent = CSS
  return () => {
    style?.remove()
    root.removeAttribute('data-nanomuse')
    root.removeAttribute('data-nm-muse')
    root.style.removeProperty('--nm-accent')
  }
}
