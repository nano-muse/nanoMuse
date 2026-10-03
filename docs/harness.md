# nanoMuse on DeepSeek Harness

> **Status: shipping.** The code is in [`harness/`](../harness/) on `main`. From 0.1.30
> this is **nanoMuse Desktop**, the one desktop app — installers for Windows, macOS and
> Linux with the harness, the bundle and the runtime for the hands inside
> ([desktop.md](desktop.md)); the bundle alone also ships packed, `dsh-nanomuse-<v>.tgz`,
> for a DeepSeek Harness Desktop someone already runs ([harness/README.md](../harness/README.md)).
> It came in two steps — the bundle from 0.1.27, the shell as *nanoMuse Harness* beside the
> older Electron app in 0.1.28–0.1.29 ([Phases](#phases)). This page is the design and the
> plan; [desktop-muse.md](desktop-muse.md) is what the window is meant to look like.

## The decision

The desktop app today is our own harness: an Electron shell around the Python runtime,
which carries its own agent loop, tool registry, skills, schedule, memory, sub-agents and
web UI — the same code as the phone and the browser demo, which is why it exists. Every
one of those parts has a counterpart in [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
(`dsh`): an open-source (MIT) agent harness built as a plugin system on
[Cordis](https://github.com/cordiverse/cordis), with a web app, a desktop app, an MCP
client, skills, goals, plan mode, compaction, delegation, approval policies, computer use
and a model layer that takes any OpenAI-compatible endpoint from configuration. It is at
0.2.0-rc, a developer preview whose plugin API will break, and it has the community a
project of ours will not have for years.

So the next desktop is **dsh plus nanoMuse plugins**: what makes nanoMuse nanoMuse — the
account, the face, the voice, Hands, Reach, the Sentinel — goes in as plugins; the loop,
the tools and the UI are dsh's. We stop maintaining a second harness for the desktop.
The phone keeps the Python runtime (dsh is Node and does not run on Android), the browser
demo keeps it too for now, and the account is the bridge between them, as it is today.

## What runs

The first slice is a dsh **bundle**, `dsh-nanomuse` ([`harness/dsh-nanomuse/`](../harness/dsh-nanomuse/)),
linked into a profile created from dsh's own web template:

- **Account.** A host service `nanomuseCloud` signs in against the relay with the same
  two calls the phone and the desktop use (`/v1/auth/code`, `/v1/auth/verify`), keeps the
  key in dsh's credential store as `NANOMUSE_CLOUD_TOKEN`, and writes the account's chat
  models into dsh's model adapter (`dsh-llm-pi-ai`) as a provider called *nanoMuse
  Cloud* with the relay's `/v1` as its base URL. No model adapter of ours: the relay
  speaks OpenAI Chat Completions, dsh speaks it back. Sign-out removes both again. A
  loopback API (`/nanomuse/cloud/{status,code,verify,refresh,sign-out}`, same-origin
  only) serves the settings section.
- **Face and name.** The browser half fills dsh's slots: the dragon in the sidebar brand
  seat and the hero, the *nanoMuse* wordmark, and a *nanoMuse account* section in
  Settings (phone or e-mail → code → signed in, with the masked identifier, the
  allowance and the models). The stock brand plugin is disabled by the patch; the stills
  are served by the host half.
- **Voice.** dsh's web sessions compose from an *agent preset*, and a preset's persona
  wins over the global one, so the bundle declares a preset `nanomuse` — the same plugin
  list as dsh's *Standard* with nanoMuse's persona — and makes it the default. The
  person can still pick *Standard*, *PTC* or *Minimal*.
- **Hands, the first of our capabilities as a plugin.** The preset mounts dsh's MCP
  client on `nanomuse mcp` ([cli.md](cli.md#audit-and-config)): the runtime's
  `computer_screen` and `computer_act` served over stdio, with their own descriptions
  and schemas, arriving in dsh as `mcp__nanomuse__computer_screen` and
  `…computer_act`. Screenshots travel as MCP images, so a vision model sees the screen.
  What the Sentinel does in the runtime the bridge does at the model's level: a step the
  runtime would ask the person about (Enter or a submit, a heavy shortcut, a click on a
  word from the sensitive list) is refused with the reason until the call carries
  `confirmed: true`, which the model may set only after the person agreed in the
  conversation; dsh's own approval policy can add a real gate in front of the tool.
  The connectors the runtime's `config.toml` turns on ride along on the same server —
  `read_emails` / `send_email`, `calendar`, `contacts` — so a mailbox or a calendar set
  up for the runtime is a connector of the desktop too (Settings → Connectors lists
  them as connected once they appear).
  `NANOMUSE_PY` names the runtime's executable when it is not on `PATH`; without a
  runtime the preset simply has no hands.

Verified end to end on a scratch install against a local relay: sign in, the two chat
models appear under *nanoMuse Cloud* in the picker without a restart, a new session
starts as *nanoMuse*, "who are you?" is answered through the relay in nanoMuse's voice,
and "what is on my screen?" is answered after one `mcp__nanomuse__computer_screen` call
with a correct description of the desktop. [`harness/README.md`](../harness/README.md)
has the recipe.

The second slice adds what the Android app has around the chat, modelled on what
[every-device.md](every-device.md) lists for the phone:

- **The first run.** dsh's own first-run dialog asks for a DeepSeek key. The bundle
  registers its step in that seat (the shipped id `deepseek-official` in the
  `settings.onboarding` slot), so a fresh install meets the agent instead: the face, the
  one-line slogan, what Hands, Reach and the Muse style are, then *sign in with a phone
  number or e-mail (free)*, *use my own API key* (opens Models) or *later*. The step
  completes itself when a model can already answer — the account, a DeepSeek key, a
  provider the person added — unless it is reopened on purpose.
- **Name, face and moods from the account.** The host pulls the relay's profile
  (`/v1/me/profile`) when the hub says it changed and keeps it under
  `$DSH_HOME/nanomuse/`; a drawn face's five stills are cached once per face id and served
  at `/nanomuse/assets/face/<id>/<mood>.webp`. The sidebar brand mark and the hero wear
  it — the dragon stills, an emoji on its colour, or the drawn face — *working* while a
  session runs and *waiting* while one asks something; the brand name is the name the
  person gave it on any device. A system-prompt context tells the model that name, so
  "what is your name?" is answered with it. Renaming on the phone shows up on the
  desktop within the hub's round trip, no restart.
- **Reach.** A hub client (`hub.ts`, plain WebSocket, the key in the `hello` frame)
  puts this computer on the account's device list as `pc-dsh-<id>` and answers `info` and
  `notify` (a toast). A second plugin, `dsh-nanomuse/reach`, registers the tools the
  phone and the runtime have: `devices`, `device_screen` (the still admitted as an image
  when the model takes images), `device_shell` and `device_open` (dsh's approval card
  first, with the command or URL in it), `device_files`, `device_notify`, and `delegate` —
  the other device's own Muse runs the task, and when *it* asks for an approval the
  question comes back here as an approval card and the answer travels back over the hub.
  Settings → *nanoMuse account* lists the devices with online dots, renames this
  computer and forgets offline ones.
- **The capsule.** While Hands or Reach work, a pill at the top of the window shows the
  face, moving bars, *Hands · step N* or *Reach · step N*, what it is doing ("on Laptop
  B: uname -a", "asking Laptop B's Muse"), and *Stop*, which cancels the turn the way
  the composer's stop does; the in-flight call ends with *aborted: the call was
  stopped*. The host learns about the calls through dsh's `tools/execute` hook and
  streams them, with the profile, the hub state and the notices, to the client over one
  SSE connection (`/nanomuse/cloud/events`).

Verified on the same scratch install with a second runtime on the account as *Laptop B*:
the first run through to *Start*; `devices` and `device_files` on Laptop B; `device_shell`
with the approval card and the result; `delegate` with Laptop B's approval requests
relayed and answered (allow and reject) and *Stop* ending it; a `notify` from another
device shown as a toast; the name and emoji set on Laptop B worn by the desktop's brand
mark and hero within seconds, and "我叫小蓝" when asked.

The third slice makes the desktop answer the phone, so Reach runs both ways:

- **This computer's hands for the others.** `actions.ts` is a port of the runtime's
  [hub actions](hub.md): `shell` (the login shell, a clamped timeout, 124 on timeout,
  the output cap), `files`, `file.get` / `file.put` (the 8 MiB limit, `force`, the
  `.nanomuse-part` rename), `open` and `screen` (`screencapture`, PowerShell,
  `gnome-screenshot` / `spectacle` / `grim` / `scrot` / `import` in turn). Same names,
  same shapes, same error codes, so a phone cannot tell a runtime from a dsh desktop.
- **The remote-control switch.** Settings → *nanoMuse account* → under *this computer*,
  the same switch the runtime has: on, the device announces the six actions in `hello`;
  off, it announces `info` and `notify` only and refuses the rest with `not_allowed`
  (the phone sees the same message a runtime would give). Flipping it re-greets the hub
  so the account's device list updates at once. The contract is unchanged: the asking
  device judges a command before sending (Sentinel on the phone and the runtime, the
  approval card here); the target does not ask again.
- **Every call shows.** What another device did here appears as a toast — "Laptop B 在
  这里运行了：uname -a", "…看了一眼这里的屏幕" — after it actually happened; a refused
  path is the asker's error to see, not a toast here.
- **Stop reaches the other side.** Pressing *Stop* on a `delegate` now sends the
  runtime's `stop {call}` for that very call, so the thread it opened for us ends too
  instead of running on to its own approval or timeout.

Verified: a second hub client drove all six actions against the desktop (a real
3840×2160 still, a timed-out `sleep` returning 124, `exists` / `not_found` / `too_large`
codes as the runtime gives them), each one a toast; the switch off refused `shell` with
`not_allowed` while `info` and `notify` kept working and the relay list showed the
narrower action set; Laptop B's own Muse, asked in its chat to run a command "on Desk A",
did so through the relay after its own Sentinel approval and reported the output; a
delegated `sleep 120` on Laptop B stopped there within two seconds of *Stop* here.

The fourth slice is the phone's `delegate` landing here — the desktop answers `task`:

- **A task runs in a dsh session.** `task.ts` opens a session per asking device and
  conversation through dsh's session controller (`create` with the `nanomuse` preset,
  renamed "From <device>"), feeds the task as a user message that says where it came
  from and which computer this is, and follows the run on the `session/event` feed:
  `tool/call` → `tool`, `tool/result` → `tool_result`, `assistant/message` → interim
  `text`, `turn/end` → the result `{text, conversation, thread, device}`. The same
  vocabulary the runtime streams, so the phone's `delegate` card reads the same. The
  session is remembered in the host's state and resumed for the next task from the same
  place, across restarts.
- **Approvals go to the asker.** An answerer on dsh's `approval/request` waterfall, ahead
  of the UI's, claims the asks of these sessions: the question travels as an `approval`
  event (the tool call's preview, dsh's reason, this computer's name, a timeout), the
  asker's `approve {approval_id, allow}` decides it, `approval_result` closes the card.
  The person is at the other device, so the local card is not raised for these runs.
- **`stop {call}` and the rest.** Stop cancels the run's agent (`cancel({kind: 'user'})`),
  which also ends the shell child dsh started — the turn settles as aborted and the asker
  gets what was said so far. `busy` while a conversation runs, `usage`, `timeout` after
  the runtime's fifteen minutes, `failed` with the model's message on an error. `task`
  and `stop` are behind the remote-control switch like the other actions; `approve` is
  always answered. A task's arrival and its end show as toasts.

Verified with Laptop B's runtime as the asker: "ask Desk A's Muse to run `uname -s` and
`date +%M`" came back with the answer and a `Desk A used bash: …` step; a write outside the
dsh workspace raised dsh's gate, which appeared on Laptop B as "on Desk A: bash: echo
outside > ~/…" and, approved there, let the desktop write the file and answer; a long
`sleep` task stopped by `stop {call}` settled as "(stopped)" in three seconds with no
child left; after a restart of dsh the next task from Laptop B resumed the same session
and the Muse answered what it had been asked before.

The fifth slice is the window itself — the Muse shape over dsh's web app, screen by
screen in [desktop-muse.md](desktop-muse.md):

- **The sidebar.** The bundle takes the `sidebar` seat (the stock `ui-sidebar` row is
  switched off in the bundle layer) and lays it out as Muse does: a rail — Chats (a dot
  while the agent works), Search, Devices, the Schedules panel when installed, the
  hamburger at the foot — and a chats column built from the harness's `useSessions`,
  `useSessionStatus` and `useWorkspaces`: *Search* with a *···* (archived chats), *Main
  chat* (kept in `localStorage`, *Make main chat* moves it), *Side chats* with *+*,
  pinned first, each row with status marks and a menu for pin, inline rename
  (`session.rename` through the sessions service), archive. The harness's own workspace
  browser is one switch away (*Show DeepSeek Harness controls*, General).
- **The header.** The face and the name pinned at the top centre of the conversation
  (`conversation.header.leading`), with a status chip — signed out, connecting,
  connected with the devices online, thinking, *Hands · step N · what*, *Reach · step N ·
  what*, waiting for you — and a *Stop* button beside it while a turn runs. The capsule
  of the second slice becomes this chip; its toasts stay. *Invite* takes
  `conversation.session.header.utilities` (the relay's `/v1/me/invite`: code, link,
  how many came and what it earned); the harness's title row, tabs and session actions
  are hidden under the Muse styles.
- **The profile panel.** The face opens a `shell.overlay` of ours, 310 px at the right,
  beside the chat: the avatar with a pen (*Change look* → `PUT /v1/me/profile` through
  the host, worn everywhere; *Edit name*), the connection, four tabs — activity from the
  sessions and the hub's notices, approvals as answered on the cards (a document-level
  observer records each decision), schedule, memory.
- **The conversation.** A stylesheet under `html[data-nm-muse]` over the harness's
  stable hooks — `[data-composer-card]` becomes one pill (*+*, *Message*, the send
  disc), `[data-chat-flow-kind="user"]` the accent bubble, the assistant step the grey
  bubble, `[data-approval-key]` Muse's permission card (shield, headline, *Allow once*
  in blue, *Reject*), the hero greeting hidden with the composer docked at the bottom;
  the harness's model, mode and plan controls are hidden from the composer and come
  back with the Developer switch. The harness's own DOM is not touched, only styled.
- **Settings.** The `sidebar.settings` seat too (the stock `ui-settings-general` row
  off): a grouped nav — General, Account, Models, Agents, Computer use, Devices, Data
  controls, Help & support, Legal — then every page another plugin registers under
  *Advanced*, *Sign out* at the foot. The General page is ours and declares
  `settings.general.item`, so the harness's own rows (permission presets, language,
  appearance, font size, shortcuts…) mount in it, followed by About and the Developer
  switch. The onboarding coordinator and the `settings.open` chord are carried over;
  the harness's preview notice, which stores its acknowledgement in the switched-off
  plugin's settings, is passed through.
- **The first run.** Full-window, Muse's sheets: welcome with the face and one *Sign in*
  pill → *Sign in or create an account* (phone or e-mail) → six code boxes (or a
  password: `/v1/auth/login`) → spinner → the permissions carousel (‹ ›): *Allow nanoMuse
  to use your computer?* on macOS (Accessibility, Screen recording, each with *Allow*
  through the shell's bridge and a green check once granted), *…access your files?* (the
  workspace folder, *Change* through the native picker), *Your other devices* → *ready*.
- **The desktop shell's bridge.** `harness/desktop/src/preload.ts` exposes
  `window.nanomuseHarness` to the page (sandboxed, IPC to the main process):
  `permissions()`, `requestPermission(kind)` (`systemPreferences`), the System Settings
  panes, `openExternal`, `keepAwake` (a power-save blocker while a session runs),
  `setTheme` (the window's base colour follows the page); it marks the document with the
  platform so the bundle adds the macOS clearance and drag handles — the shell's window
  has no title bar there (`hiddenInset`, the traffic lights over the rail). The bundle
  works without the bridge (dsh in a browser); only the computer card and the keep-awake
  switch need it.
- **The theme.** Muse's light and dark tones over the harness's tokens
  (`--dsw-alias-bg-base`, the sidebar fill, the bubbles, the layers), the accent from
  the face's colour on the account.

Verified in a browser against the scratch install and the dev relay: the first run
from a fresh home through sign-in with a code, the files and devices cards, to the
window; the chats column with a main chat and side chats, a blank one reading *New
chat*; the header chip through *connected* → *waiting for you* with *Stop*; the pill
composer, the bubbles and the approval card in both themes, an answer recorded in the
panel's Approvals tab; the profile panel beside the chat; Settings with the nine pages.
The Electron shell boots the same bundle with its bridge on Linux (screenshot check).

## Where each part of nanoMuse goes

| nanoMuse today (Python runtime)                         | On dsh                                                                                                                                       | State      |
| ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| Cloud account, provider provisioning ([cloud.md](cloud.md)) | `dsh-nanomuse/cloud` service + `llm-pi-ai` provider + credential store                                                                    | done       |
| Persona, agent name ([design.md](design.md))            | Agent preset `nanomuse` (`@deepseek-ai/dsh-persona`); the account's chosen name from the profile, in the brand seat and a system-prompt context | done       |
| The face in the UI ([avatar.md](avatar.md))             | Slots `sidebar.brand.*`, `conversation.hero.brand.mark`; stills from the host; moods from the session status; the capsule while the hands work | done       |
| Face sync across devices                                | `profile.ts` pulls the relay's profile on the hub's `profile` frame; drawn-face stills cached and served by the host                            | done       |
| The face moving ([avatar.md](avatar.md))                | `Avatar.tsx`: the dragon's state clips from `assets/`, looped silently at 44 px and up with the still as poster; CSS breath / sway / hop for drawn faces and emoji, nothing under reduced motion | done       |
| Avatar studio (drawing a new face here)                 | A settings page over the relay's image model; today a face is drawn on the phone and worn here                                                | phase 4    |
| First run                                               | Our step in dsh's `settings.onboarding` seat, full-window: welcome, sign in, code boxes, the permissions carousel (computer on macOS, files, devices), ready | done       |
| The window ([desktop-muse.md](desktop-muse.md))         | The `sidebar`, `sidebar.settings` and `shell.overlay` seats and the Muse stylesheet: rail + main / side chats, the pinned face and status chip with Stop, Invite, the profile panel, pill composer, bubbles, permission card, grouped Settings with Advanced, Muse's tones | done       |
| Sentinel ([sentinel.md](sentinel.md))                   | dsh approval policies and the `tools/pre-execute` waterfall; our categories become an approval preset; the visible gate stays                | phase 4    |
| Hands — GUI control of this computer ([gui.md](gui.md)) | The Python hands over MCP (`nanomuse mcp`, mounted in the preset) — done; a native TypeScript driver behind dsh's computer-use seam (`ctx.computerUse.register`) later, so no Python is needed | done (bridge) |
| Reach — the phone and other devices ([hub.md](hub.md), [every-device.md](every-device.md)) | `hub.ts` + `dsh-nanomuse/reach`: `devices`, `device_screen/shell/files/open/notify`, `delegate` with relayed approvals and `stop` on *Stop*; the phone side unchanged | done       |
| Being controlled from the phone (shell, files, screen)  | `actions.ts` answers `shell`, `files`, `file.get`, `file.put`, `open`, `screen` with the runtime's shapes, behind the remote-control switch in Settings; each call a toast | done       |
| A task run here for the phone (`task`)                  | `task.ts`: the phone's `delegate` lands in a dsh session ("From <device>", resumed next time), its run streamed back as the runtime's event frames, its approvals relayed to the asker, `stop {call}` honoured | done       |
| Connectors ([desktop-muse.md](desktop-muse.md#settings)) | `connectors.ts`: a catalogue of ~70 remote MCP servers, the MCP authorization flow (metadata, DCR, PKCE, refresh), keys, the MCP Registry search, and a loopback proxy that holds the credential and filters the tools; `connectors-tools.ts` mounts a `dsh-mcp-client` per connection and follows the page | done       |
| Skills, schedule, goals, memory, sub-agents             | dsh's own (`skill`, `schedule`, `goals`, compaction, delegation) — ours are not ported                                                       | by design  |
| Web UI, zh-CN                                           | dsh's web app (it ships zh); our strings in the bundle's locale table                                                                        | done       |
| The desktop shell                                       | `harness/desktop`: our Electron shell, the harness's Host as a child in Node mode, dsh + the bundle + the runtime for the hands inside; installers for Windows, macOS, Linux from `desktop-app.yml` | done (unsigned) |
| Browser demo at nanomuse.cn/web                         | Stays on the Python runtime                                                                                                                  | unchanged  |
| The phone                                               | Stays on the Python runtime; meets the desktop through the account and Reach                                                                 | unchanged  |

## What we learned building the slice

- A bundle patch replaces a row's whole `config`, so rows we touch restate every key they
  need; `insert:` adds rows. Bundle layers are read at boot (restart after editing them);
  the profile's own patch hot-reloads.
- The preset's plugin list is a copy of dsh's *Standard* for the pinned version, because
  presets are declared whole. When dsh moves, diff against
  `@deepseek-ai/dsh-web-app/presets/standard.patch.yml`. Our own capabilities go into
  that list as plugins — that is the point.
- The hero headline (*Into the Unknown*) is a locale string in dsh's `conversation`
  namespace; a second dictionary for the same namespace and locale throws, so it cannot
  be replaced from a plugin today. Ask upstream for a slot, or live with it.
- Two slot registrations at the same rank throw, which is how the stock brand mark was
  found; disabling its row (`ui-brand-official`) is cleaner than out-ranking it.
- The model picker lists provider models by id (`qwen3.8-flash`), as it does for
  DeepSeek's own; the display name is in the provider row for when dsh uses it.
- `dsh plugin add` needs pnpm on `PATH` and links the checkout, so `pnpm build` and a
  restart is the whole loop. Node 22.19+.
- The `settings.onboarding` coordinator mounts one step at a time and only while the
  main view is a blank session; it hands the step a fresh `complete` closure on every
  render, so a step must decide once, on mount, or a re-render throws the person back to
  its first view while they are typing a code.
- `tools/execute` is an around-hook (`ctx.on('tools/execute', (exec, next) => …)`), which
  is enough to know when a Hands or Reach call starts and ends without touching the
  tools; the capsule and the step counter hang off it.
- Images a tool returns must go through the attachment store (`attachments.saveImages`)
  and only when `llm.resolveModelInfo(...).inputModalities` includes `image`; otherwise
  the tool says what it saw in words — the MCP client does the same.
- The hub has no cancel frame, and does not need one: the runtime's `stop {call}` action
  ends the thread it opened for a `task` call, so picking the call id up front and
  sending `stop` for it when the turn is aborted stops the job on the other side. The
  runtime's `stop_thread` does not kill a shell child already running in its sandbox —
  that one ends on its own — which is a runtime detail to tighten, not a protocol gap.
- The relay's `controllable` flag only says *not a browser tab*; what a device allows is
  its announced `actions` list, re-sent in `hello`. A device that turns remote control
  off must reconnect (or re-greet) for the account to see the narrower list.
- Driving a session from the host is three calls: `sessionController.create` /
  `rename`, `resolveAgent(id).agent.followup(createUserMessage(…))`, and the
  `session/event` feed for what happens (`tool/call`, `tool/result`,
  `assistant/message`, `turn/end`). `dsh-schedule` does the same for reminders. The
  `approval/request` waterfall takes an answerer registered with `prepend`, which is how
  a run's questions can be routed elsewhere without touching the UI's answerer.
- A session created without a workspace lands under *Ungrouped* in the sidebar with
  dsh's default cwd (the process's); fine for a preview, a chosen workspace later.

## Names and licences

DeepSeek Harness is MIT; it is a dependency, not vendored, and its notice travels with
it. Our bundle is GPL-3.0-or-later like the rest of nanoMuse, so the "no closed
component" promise holds. "DeepSeek Harness" and "DSH" are DeepSeek's names: we say
*built on DeepSeek Harness*, never use them in ours, and the shipped About text and
brand assets stay as they are. The usual notices — Muse is Meta's trademark, nanoMuse is
a community project with no affiliation — apply unchanged.

## Phases

1. **This slice** — account, face, voice, and Hands over MCP; verified on a scratch
   install. *Done, internal.*
2. **The Muse style and Reach** — the first run, the account's name, face and moods,
   the capsule with Stop, the hub client, the `device_*` tools and `delegate` with
   relayed approvals, the device list in Settings. *Done, internal.*
3. **Reach both ways** — the desktop answers `shell`, `files`, `file.get`, `file.put`,
   `open` and `screen` behind its remote-control switch, every call a toast, *Stop*
   stopping the delegated job on the other device; the phone's `delegate` runs in a dsh
   session here with its approvals relayed back. *Done, internal.*
4. **The window** — the Muse shape: the rail and the chats column, the pinned face with
   the status line and Stop, grouped Settings with the harness's extras under Advanced,
   the first run with its cards, the theme. *Done, internal.*
5. **Daily-driver** — the Sentinel as an approval preset, the avatar studio here, Hands
   without Python (a native driver behind dsh's computer-use seam), a chosen workspace
   for tasks from other devices; the person can live in it for ordinary work on files
   and the web.
6. **Ship** — the shell, in two steps. dsh's own desktop app is an Electron wrapper
   around the same web app with a `desktop` profile that takes external plugins (`dsh
   plugin --profile desktop add …`), so the first nanoMuse desktop was that app with the
   bundle in its profile: **from 0.1.27 every release carries the bundle packed**
   (`nanoMuse-Harness-<v>.tgz` then, `dsh-nanomuse-<v>.tgz` from 0.1.30), with the
   install in [harness/README.md](../harness/README.md) (`.github/workflows/harness.yml`
   builds, tests, packs it and installs the tarball into a fresh dsh profile). **From
   0.1.28 the second step is there too**: our own shell in
   [`harness/desktop/`](../harness/desktop/) — not dsh's `apps/desktop` rebuilt (its
   pipeline prepares a private Host, a primary runtime and hardware-token signing, a
   project of its own), but a small Electron app that does what that one does at its
   core: starts the harness's Host as a child process with its own binary in Node mode
   (`ELECTRON_RUN_AS_NODE`, `--expose-internals`; the harness's `require-builtin` addon
   fingerprints the Electron it was built for, so the shell pins `44.0.0`), from a `dsh`
   that npm installed under `resources/dsh` together with the bundle at build time,
   against a profile of its own under `~/.nanomuse/desktop` that names the bundle and
   links it from the copy inside the app. The runtime for the hands rides along as a
   PyInstaller build, and `NANOMUSE_PY` points the preset at it. `desktop-app.yml` builds
   the Windows installer, the macOS dmg/zip for both architectures and the Linux
   AppImage/deb on every release tag, boots each packaged harness once in Node mode as a
   check, and attaches them to the release (the same Apple secrets sign and notarize the
   macOS build when they are set). It shipped as *nanoMuse Harness* beside the older
   desktop app in 0.1.28 and 0.1.29; **from 0.1.30 it is nanoMuse Desktop**, the one
   desktop app — `nanoMuse-Desktop-<v>-…`, the application id of the retired
   `desktop/app` so it installs over it — and the site's downloads point here.
7. **Daily-driver on the new shell** — the rooms Muse has beside the chat (Feed, Ideas,
   Goals, Library), the live stage while the hands work on this screen, signing on both
   platforms, an update feed of our own, the macOS close-to-Dock and Windows tray
   behaviour the harness's desktop has, a chosen workspace for tasks from other devices.

The Electron shell around the Python runtime (`desktop/app`, 0.1.19–0.1.29) is gone; what
it had that the harness does not — the stage, the tray, Quick Chat — comes back here, on
dsh's seams, as phase 7 proceeds. The terminal binary in `desktop/` stays the
zero-install fallback.
