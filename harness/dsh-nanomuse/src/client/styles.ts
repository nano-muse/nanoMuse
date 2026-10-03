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
export function setMuseMode(on: boolean, placeholder?: string): void {
  const root = document.documentElement
  if (on) root.setAttribute('data-nm-muse', '')
  else root.removeAttribute('data-nm-muse')
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
html:is([data-nm-platform='darwin'], [data-nm-platform='win32']) [data-window-drag], html:is([data-nm-platform='darwin'], [data-nm-platform='win32']) .nm-ob, html:is([data-nm-platform='darwin'], [data-nm-platform='win32']) [data-slot="conversation.session.header"] > :first-child { -webkit-app-region: drag; }
html:is([data-nm-platform='darwin'], [data-nm-platform='win32']) :is([data-window-drag], .nm-ob, [data-slot="conversation.session.header"]) :is(button, a, input, select, textarea, [contenteditable], [role="button"], [role="dialog"], [role="menu"]) { -webkit-app-region: no-drag; }
html[data-nm-platform='darwin']:not([data-nm-fullscreen]) .nm-main-top { height: 12px; }
html[data-nm-platform='win32']:not([data-nm-fullscreen]) .nm-rail-top { height: 24px; }
html[data-nm-platform='win32']:not([data-nm-fullscreen]) .nm-main-top { height: 12px; }
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
.nm-chat-dot.nm-live { animation: nm-pulse 1.2s ease-in-out infinite alternate; }
.nm-chat-mark { flex: none; font-size: 12px; color: var(--dsw-alias-state-warn-primary, #d98c1f); }
.nm-chat-more { position: absolute; right: 4px; top: 50%; transform: translateY(-50%); width: 26px; height: 26px; border: 0; padding: 0; border-radius: 7px; background: transparent; color: var(--dsw-alias-label-secondary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; opacity: 0; }
.nm-chat-row:hover .nm-chat-more, .nm-chat-more:focus-visible, .nm-chat-more[aria-expanded="true"] { opacity: 1; }
.nm-chat-more:hover { background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); }
.nm-chat-row:hover .nm-chat-title { padding-right: 22px; }
.nm-chat-edit { flex: 1; min-width: 0; height: 30px; margin: 2px 4px; padding: 0 8px; border: 1px solid var(--nm-blue); border-radius: 7px; background: var(--nm-field); color: var(--dsw-alias-label-primary); font: inherit; font-size: 14px; outline: none; }

/* ---- the pinned agent header over the conversation -------------------- */
header[data-window-drag]:has(.nm-header) { position: relative; min-height: 108px; }
.nm-header { position: absolute; left: 50%; top: 12px; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; gap: 3px; pointer-events: none; z-index: 2; max-width: min(60%, 520px); }
.nm-header > * { pointer-events: auto; }
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
.nm-status-dot.nm-live { background: var(--nm-accent); animation: nm-pulse 1.2s ease-in-out infinite alternate; }
.nm-status-dot.nm-wait { background: var(--dsw-alias-state-warn-primary, #d98c1f); }
@keyframes nm-pulse { from { opacity: 0.45; transform: scale(0.85); } to { opacity: 1; transform: scale(1.1); } }
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
.nm-mic.nm-live { color: #fff; background: #e0245e; animation: nm-mic-pulse 1.2s ease-in-out infinite; }
@keyframes nm-mic-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(224,36,94,0.45); } 50% { box-shadow: 0 0 0 6px rgba(224,36,94,0); } }
/* Muse keeps the chat bare: no tool-step disclosure, no usage, no fork, no context rows */
html[data-nm-muse] [data-chat-flow-kind="context"] { display: none !important; }
/* the "done in 6 s" accordion goes; what the agent said along the way stays a bubble, as Muse shows it (the harness folds it under the accordion with hidden=until-found) */
html[data-nm-muse] [data-chat-flow-kind="turn-process"] { display: none !important; }
html[data-nm-muse] [data-turn-process-member]:not([data-chat-flow-kind="assistant-step"]):not([data-chat-flow-kind="tool-call"]) { display: none !important; }
html[data-nm-muse] [data-chat-flow-kind="assistant-step"][hidden] { display: block !important; content-visibility: visible !important; }
/* the rooms' trigger rows and the agent's tool rows stay out of the chat (the Activity tab has them); approvals, presented files and open questions stay */
html[data-nm-muse] [data-chat-flow-kind="turn-trigger"] { display: none !important; }
html[data-nm-muse] [data-chat-flow-kind="tool-call"]:not(:has([data-approval-key], [data-tool="present"], [data-tool="ask_user_question"]:not([data-state="error"]))) { display: none !important; }
html[data-nm-muse] [data-chat-flow-kind="tool-call"][hidden]:has([data-approval-key], [data-tool="present"], [data-tool="ask_user_question"]:not([data-state="error"])) { display: block !important; content-visibility: visible !important; }
/* while the agent thinks: three dots in a grey bubble, not the whale */
html[data-nm-muse] [data-chat-running] { display: flex !important; align-items: center; width: fit-content; min-height: 36px; margin: 6px 0; padding: 0 16px; border-radius: 18px; background: var(--nm-agent-bubble); }
html[data-nm-muse] [data-chat-running] > [class*="_runningDivider"], html[data-nm-muse] [data-chat-running] > [class*="_runningContent"] { display: none !important; }
html[data-nm-muse] [data-chat-running]::after { content: ''; display: block; width: 7px; height: 7px; margin: 0 20px 0 6px; border-radius: 50%; background: var(--dsw-alias-label-tertiary); box-shadow: 11px 0 0 var(--dsw-alias-label-tertiary), 22px 0 0 var(--dsw-alias-label-tertiary); animation: nm-dots 1.1s ease-in-out infinite; }
@keyframes nm-dots { 0%, 100% { box-shadow: 11px 0 0 var(--dsw-alias-label-tertiary), 22px 0 0 var(--dsw-alias-label-tertiary); opacity: 0.55; } 50% { box-shadow: 11px -3px 0 var(--dsw-alias-label-secondary), 22px 0 0 var(--dsw-alias-label-tertiary); opacity: 1; } }
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
.nm-pf-pen { position: absolute; right: -2px; bottom: 0; width: 26px; height: 26px; border-radius: 50%; border: 2px solid var(--nm-base); background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; padding: 0; }
.nm-pf-pen:hover { background: var(--nm-blue); color: #fff; }
.nm-pf-menu { position: absolute; left: 50%; top: calc(100% + 6px); transform: translateX(-50%); min-width: 160px; }
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
.nm-settings-body { flex: 1; min-height: 0; overflow: auto; padding: 8px 28px 28px; }
.nm-settings-body > * { max-width: 560px; }
.nm-settings-body .nm-page { padding: 0; height: auto; overflow: visible; }
.nm-settings-body .nm-page h1 { display: none; }
.nm-general { display: flex; flex-direction: column; }
/* General, Muse's way: the account card, the usage bars, the colour swatches, the key cap */
.nm-usage { padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; }
.nm-usage-row { display: flex; align-items: center; justify-content: space-between; font-size: 14px; }
.nm-usage-plan { font-weight: 600; }
.nm-usage-pct { font-size: 12.5px; color: var(--dsw-alias-label-secondary); }
.nm-usage-bar { height: 6px; border-radius: 3px; background: var(--nm-hover); overflow: hidden; }
.nm-usage-bar > span { display: block; height: 100%; border-radius: 3px; background: var(--nm-accent); transition: width 240ms; }
.nm-usage-fine { font-size: 12px; color: var(--dsw-alias-label-tertiary); }
.nm-usage-link { font-size: 13px; color: var(--nm-blue); text-decoration: none; align-self: flex-start; }
.nm-swatches { display: flex; flex-wrap: wrap; gap: 8px; }
.nm-swatch { width: 22px; height: 22px; border-radius: 50%; border: 0; padding: 0; cursor: pointer; box-shadow: inset 0 0 0 1px rgba(0,0,0,0.12); }
.nm-swatch.nm-on { box-shadow: 0 0 0 2px var(--nm-base), 0 0 0 4px var(--dsw-alias-label-primary); }
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

/* ---- the Live stage (picture-in-picture of the agent at work) ---------- */
.nm-stage-layer { position: fixed; right: 24px; bottom: 96px; z-index: 55; pointer-events: none; }
.nm-stage { position: relative; width: min(400px, 38vw); pointer-events: auto; border-radius: 16px; overflow: hidden; background: #111; box-shadow: 0 18px 48px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,255,255,0.08); animation: nm-stage-in 220ms ease-out; }
@keyframes nm-stage-in { from { opacity: 0; transform: translateY(8px) scale(0.98); } to { opacity: 1; transform: none; } }
.nm-stage-picture { position: relative; width: 100%; background: #000; overflow: hidden; }
.nm-stage-picture img { display: block; width: 100%; height: 100%; object-fit: contain; user-select: none; }
.nm-stage-picture.nm-dim img { filter: brightness(0.82); transition: filter 200ms; }
.nm-stage:hover .nm-stage-picture.nm-dim img { filter: brightness(0.95); }
.nm-stage-cursor { position: absolute; width: 0; height: 0; pointer-events: none; }
.nm-stage-face { position: absolute; left: -13px; top: -13px; box-shadow: 0 0 0 2px #fff, 0 2px 8px rgba(0,0,0,0.45); }
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
.nm-stage-ripple { position: absolute; left: -18px; top: -18px; width: 36px; height: 36px; border-radius: 50%; border: 2px solid rgba(255,255,255,0.9); animation: nm-ripple 900ms ease-out forwards; }
@keyframes nm-ripple { from { transform: scale(0.4); opacity: 1; } to { transform: scale(1.6); opacity: 0; } }
.nm-stage-btn { position: absolute; top: 10px; width: 28px; height: 28px; border: 0; border-radius: 50%; background: rgba(0,0,0,0.55); color: #fff; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; opacity: 0; transition: opacity 150ms, background 150ms; backdrop-filter: blur(6px); }
.nm-stage-btn:hover { background: rgba(0,0,0,0.8); }
.nm-stage-close { left: 10px; }
.nm-stage-tools { position: absolute; top: 10px; right: 10px; display: flex; align-items: center; gap: 6px; }
.nm-stage-tools .nm-stage-btn { position: static; }
.nm-stage:hover .nm-stage-btn, .nm-stage-btn:focus-visible { opacity: 1; }
.nm-stage-pill { display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 12px 0 10px; border: 0; border-radius: 999px; background: rgba(255,255,255,0.92); color: #111; font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; box-shadow: 0 2px 10px rgba(0,0,0,0.3); }
.nm-stage-pill:hover:not(:disabled) { background: #fff; }
.nm-stage-pill:disabled { opacity: 0.7; cursor: default; }
.nm-stage-caption { position: absolute; left: 10px; bottom: 10px; max-width: calc(100% - 20px); display: inline-flex; align-items: center; gap: 7px; padding: 6px 11px; border-radius: 999px; background: rgba(0,0,0,0.62); color: #fff; font-size: 12.5px; line-height: 1.3; backdrop-filter: blur(6px); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-stage-verb { font-weight: 600; }
.nm-stage-where { color: rgba(255,255,255,0.72); overflow: hidden; text-overflow: ellipsis; }
.nm-stage-dot { width: 7px; height: 7px; border-radius: 50%; background: #ff453a; box-shadow: 0 0 0 0 rgba(255,69,58,0.6); animation: nm-stage-pulse 1.4s ease-out infinite; flex: none; }
@keyframes nm-stage-pulse { 0% { box-shadow: 0 0 0 0 rgba(255,69,58,0.6); } 100% { box-shadow: 0 0 0 7px rgba(255,69,58,0); } }
.nm-stage-big { width: 100%; }
.nm-stage-big .nm-stage-picture { border-radius: 12px; }

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
