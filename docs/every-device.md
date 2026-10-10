# Every device

The fourth thing that defines nanoMuse ([roadmap](roadmap.md)): one agent, and
every device you own is a pair of hands and a front door for it. This page is
the design for that stage — what every device's app looks like, what each one
can do on its own and for the others, how a task travels, and which existing
pieces each part is built from. The protocol itself is in [hub.md](hub.md);
this page is about the product shape and the code around it.

## One Muse per device, one shape

Every device runs its own Muse — the phone its OpenMinis-based agent, the
computer nanoMuse Desktop with the Python runtime for the hands — and every one of them shows the same app. The
Android app is the reference; the others follow its shape, not its pixels:

| On every device | Android today | Computer (this stage) |
|---|---|---|
| A face with a name pill and a status line at the top of the conversation | `HomeShell`, `AgentAvatarDisc` | the web app's chat header, dragon by default |
| One main chat, side chats in a drawer | drawer | drawer on narrow windows, a sidebar on wide ones |
| Feed · Ideas · Goals · Library | floating frosted-glass pill bar, icons only | bottom bar / sidebar |
| Approval cards in the chat, three tiers, *remember* pills | `RiskApprovalCard`, `RiskTier` | the Sentinel's card with the same labels |
| Settings → Permissions: what was remembered, by tier | `GrantsSection` | Permissions page, grants by tier |
| Settings → Hands: the screen as a hand, off by default | `Hands` | Settings → Hands (this computer's screen) |
| Devices: the account's other devices, online dots, *Remote control*, rename, forget, *ask this device* | `DevicesSection`, `ComputersScreen` | Devices page |
| The stage while the hands work: a ring where the next tap lands, a capsule with the step and **Stop** | `HandsStage`, capsule | a live *Hands* card in the chat; the window adds an overlay |
| First run: what it is, sign in with a phone number or an e-mail (free) or your own key, the Hands permissions, meet | `FirstRunSetup` | the same four pages |

## Two roles

Each device plays both, at the same time.

**An agent of its own.** It climbs the same ladder everywhere ([gui.md](gui.md)):
a skill, a CLI or an MCP server first; a page fetched with your login; the
browser; and last, when you allowed it, the device's own screen — looking at a
screenshot, deciding one action, doing it, looking again. On the phone the
shell is the app's Linux sandbox and the screen is *Hands*. On the computer the
shell is the real shell (sandboxed where the runtime can), the browser is
Playwright or the system browser, and the screen is *Hands on this computer*:
`computer_screen`, `computer_act`, `computer_task` — the phone operator's loop
with a computer under it. A click is assessed by the words under the cursor
(`label`), exactly as a tap is, and the same words (pay, transfer, send,
delete…) make it a highest-tier approval that no standing permission covers.

**Hands and a front door for the others.** Signed in to one account, the
devices meet over the hub and each one exposes what it can do as actions
(`shell`, `files`, `file.get`, `file.put`, `open`, `screen`, `notify`) and as a
target for whole tasks (`task`). Any device's agent has the others as tools:
`devices`, `device_shell`, `device_files`, `device_get`, `device_put`,
`device_open`, `device_screen`, `device_notify`, and `delegate` — a job in
words for the other device's Muse. So "find the order number on my phone, then
put it in the spreadsheet on my Mac" is one conversation: the phone's Muse
finds it with Hands, the Mac's puts it in the file, and the person who asked
sees both halves in the chat they typed in.

A device decides what it lets the others do: **Remote control** off makes it
answer `info` and nothing else, while it still drives the rest. With it on, the
person *at* the device still agrees before another device runs, reads or writes
something there — a card on that screen, *once* or *always for that device*
(a standing permission listed under Permissions like any other, revocable there).
A `task` runs under the device's own Sentinel instead; `notify` never asks. On
nanoMuse Desktop the switch is off by default and means "each device asks here";
on lets every device of the account through without the question.

## How a task travels

```
you, on the phone ──"编译一下项目，把日志发我"──▶ phone's Muse
                                                  │ delegate("desk", …)
                                                  ▼  hub: call task
                                         desk's Muse, in a side chat
                                         "From Pixel" that the desk shows live
                                                  │ tool events ─▶ phone (chips)
                                                  │ approval? ──▶ phone (card) ── approve ─▶
                                                  ▼
                                         result {text} ──▶ phone's Muse ──▶ you
```

- The **asking device's brain** runs the conversation; the target device's
  Muse runs the delegated job in a conversation of its own. Raw actions
  (`device_shell`…) skip the target's brain entirely.
- **Approvals are answered where the question was asked**: the target's
  Sentinel raises the card, the frame `event {stage:"approval"}` carries it
  back, the asker shows its usual card, and `approve` carries the answer. The
  target also shows the same card in its own side chat; the first answer wins.
  Commands typed on one device for another are judged on the typing device
  before they leave (ShellGuard on the phone, the Sentinel's assessment here).
- **Watching and taking over**: the delegated conversation is a real side chat
  on the target, so a person at that device sees it run, can type into it
  (folded into the running turn) and can press Stop. The asker sees the chips
  and the final answer; `stop` from the asker ends it too.
- Files and screenshots travel base64 in the frames; the size limits are the
  hub's.

## The same conversations everywhere

Since 0.1.36 the chats themselves follow the account. Signed in, each device
sends the text of its turns to the relay's sync store
([cloud.md](cloud.md#conversation-sync)) and pulls what the others sent — at
launch, when the hub says `sync`, and once a minute — so a chat begun on the
phone in the morning is on the computer at the desk, and continuing it there
runs the turn on *that* device with the synced transcript as its history; what
it answers goes back the same way. Chats addressed to a device, or run on this
device for another, stay where they are. Rename or delete a chat anywhere and
it is renamed or deleted everywhere. Text only: files and images stay on the
device they were made on, and a synced message shows their names and sizes.

Since 0.1.37 it is **one thread**. The main chat is one conversation across
all devices: what you say to the muse on the phone is in the main chat on the
computer and in the web app, in time order among what was said there, as a
read-only bubble with *From Pixel 8* (来自 Pixel 8) under it — and the muse,
wherever it answers next, has read it. A side chat from another device is a
chat on this one from the moment it is pulled, with its title, and continues
here under the same conversation; nothing in the chat list says where a chat
was written, the bubbles do. The person's message is on the other devices as
soon as it is sent, the reply when the turn ends; signing in sends the device's
whole history, oldest first. Rename the muse anywhere — the first
conversation's naming included — and the name follows on the next pull.

Since 0.1.38 it is **main first**. Only the main conversation travels unless a
device asks for more: side chats stay on the device that made them, and no other
device's side chats arrive. *Also sync side chats* (同时同步旁聊), under the sync
switch in *Data controls*, is per device and off by default — *Off: side chats
stay on this device. On: this device's side chats go to the account and the
other devices' side chats come here.* Turning it on sends this device's side
chats up and pulls the others' down once from the start. A fresh sign-in pulls
the newest 300 messages first so a long history is readable at once instead of
arriving oldest-first. While another device is answering, the chat shows *kwai
is working…* (kwai 正在处理…) under the last message — a presence note the relay
passes on and never stores; it goes when the reply lands, when the device says
it is done, or after ten minutes. A message that arrived from another device is
never shown as interrupted and never offers *Continue* — only the device that
ran the turn knows how it ended.

The switch is *Settings → Data controls → Sync conversations between my
devices*, on by default; off tells the relay to delete the account's store, and
every other device's switch follows. *Delete synced conversations* empties the
store and keeps the switch. The phone and the web app map each local chat to a
conversation id and apply the other devices' changes straight into their chat
lists. **nanoMuse Desktop (the dsh plugin)** keeps another device's turns in
its own store (`$DSH_HOME/nanomuse/sync-remote.json`, by session — a dsh session
log is append-only and owned by its agent loop, and a row written into it
outside a turn is neither shown nor safe), shows them in the browser as the
other device's bubbles (`client/RemoteBubbles.ts`), placed by time among the
turns typed here, and hands the model what arrived as one note before its next
step (`agent.inject`; the note is context, never a row, never pushed back). A side
conversation pulled from the relay gets its dsh session at once (listed in
*Side chats* though no turn ran here yet); the main chat is the session the
account's main conversation lives in, and the first conversation starts in it
when the account already has one. The harness has no delete and a log forgets
nothing: a message deleted elsewhere is hidden here, a chat deleted elsewhere
is archived here. Since 0.1.38 the plugin keeps *Also sync side chats* with its
own state (off by default; off, a side chat here is neither listed nor read for
the push, and a side row that still arrives makes no session), asks the relay
for `scope=main` and, on the first pull and when the side switch goes on, for
the tail; the other device's *kwai is working…* line is drawn under its last
bubble from the hub's `working` frame and cleared by its reply, by
`working: false` or after ten minutes — the remote rows are never in the
session log, so the harness cannot take one for an unfinished turn. The host
reads a session's log once per change (title, lines and prompt positions are
kept until the session's next event) and turns a burst of `sync` frames into
one pull a second, so a big account costs the chat nothing while idle.
Code: the runtime's [`nanomuse/sync/`](../nanomuse/sync/)
(`ConversationSync`, `/api/sync/*` in [app.md](app.md#api)), the web app's
`SyncControls` and the message captions in `web/src/`, the plugin's
`src/sync.ts`, `client/RemoteBubbles.ts` and `tests/sync.test.mjs`, the relay's
[`cloud/nanomuse_cloud/sync.py`](../cloud/nanomuse_cloud/sync.py).

**Work on another device.** The default is always the device you are typing
on. To send one message elsewhere, start it with `@` and the device's name as
the hub lists it — `@Desk compile the project and send me the log` — a prefix
match, case-insensitive; the composer offers the names as you type, the mention
is taken off the text, the bubble says *to Desk*, and a one-line note in front
of the turn tells this device's agent to hand it to that device with `delegate`
(`nanomuse-pc task … --on` on the phone) and report what it did; the Devices
page's *Ask this device* does the same. On the iPhone, which has no delegate
tool, the mention goes to the hub directly — `task` to that device, its answer
shown as a turn in the chat — and only devices that are online are matched.
Which devices can be a target: **computers** — nanoMuse Desktop, a runtime —
whenever they are online, since their hub socket stays up; **phones** — Android
and the iPhone — only while the nanoMuse app is open, because the socket lives
in the app and neither keeps it in the background. A device that is not online
is offered as a target all the same on the web and the desktop and answers
`device_offline`; the web console is never one. The session a device runs for
another is kept on that device and is not synced.

## Whose conversations a device shows

A device can be signed in as one account today and another tomorrow — a
family's tablet, a work laptop with a personal account on it, a phone handed
on. Since 0.1.39 every conversation on a device remembers **whose** it is: the
account that was signed in when it first went up to the relay or first arrived
from it. The rule is then the same on the phone, the computer, the desktop app
and the web console:

- **Signed in as B, you see B's conversations** — and the ones that belong to
  nobody: chats made while signed out, before anyone had signed in on this
  device. A's chats are not in the list.
- **A's chats are hidden, not deleted.** They stay on the device, with their
  files and images, and are back the moment A signs in again. Signing out on
  its own hides nothing; deleting a chat still deletes it.
- **Nothing crosses accounts.** A conversation of A's is never sent up to B's
  account, and B's conversations never land in A's — not by sync, not by a
  turn run on this device for another device of the account.
- **A different account starts fresh.** When the signed-in account changes, the
  device forgets where it was in the other account's sync (the next pull is
  the newest 300 lines, as on a first sign-in), clears what it kept of the
  other devices' bubbles and presence, and reads the new account's device
  list anew. Switching back to A picks up A's chats and A's place in the sync.
- **The relay is not involved.** It keeps each account's store apart as it
  always did; the sorting is done on the device, so an older relay behaves the
  same.

The muse's name and look follow the account as before. Since 0.1.40 the phones
go further (contract C12): every chat has an owner — a chat that was never
synced included — and a sign-out takes the account's chats, memory, feed, goals,
routines and face off the phone unless *Keep this account's chats on this
device* is turned on; deleting the account removes all of it; a key the relay
refuses keeps it aside for the account's return. The table of every piece of
state is [sync.md](sync.md). On the desktop and the web console
the 0.1.39 rule above still holds, and the memory files are per device.
Code: the runtime's `nanomuse/sync/engine.py` and the session list in
`nanomuse/server/api.py`, the desktop's `harness/dsh-nanomuse/src/{sync,cloud}.ts`,
Android's `io.github.nanomuse.sync.*`, the iPhone's `NanoMuse/NanoMuseSync.swift`.

## The computer: nanoMuse Desktop

The desktop is the Python runtime (`nanomuse serve`) with three front doors on
the same local service — the terminal (`nanomuse chat`), the browser (the web
app it serves, also reachable from the phone on the same network) and a
window. That is the shape OpenCode v2 and Codex take (a local service, a CLI
and a desktop app over it) and it is what the runtime already was; this stage
adds the hub, the Cloud account and the hands to it.

```
   nanomuse serve  ─ FastAPI + WebSocket, 127.0.0.1:8787 ─┬─ web/ (React) in a browser or on the phone
      │ MuseAgent · Sentinel · tools                        ├─ nanomuse mcp → nanoMuse Desktop (harness/, on DeepSeek Harness)
      │ nanomuse/hub  ── wss://…/v1/hub ── the other devices └─ nanomuse chat (terminal)
      │ nanomuse/computer ── mss + pyautogui: the screen as a hand
      └ nanomuse/cloud ── the nanoMuse Cloud account (e-mail code → key → models + hub)
```

- **Runtime** (`nanomuse/`): `cloud.py` signs in to nanoMuse Cloud with an
  e-mail (or phone) code, keeps the key in the vault and can make the relay the
  model provider — the same *Sign in — free* first step as on the
  phone. `hub/` is the async port of the desktop binary's hub client: one
  socket kept up, incoming actions answered by `hub/actions.py`, incoming
  `task`s run in a visible side chat with their approvals relayed, outgoing
  calls behind the `device_*` and `delegate` tools. `computer/` is the screen
  as a hand on this machine. Settings: `[cloud]`, `[hub]`, `[hands]`; all of
  them switchable from the app.
- **Web app** (`web/`): the Devices page, side chats addressed to a device,
  the approval card's tiers and *remember* pills, the Hands card with Stop,
  Settings → Hands, the Cloud sign-in in the first run and under Connections,
  the dragon as the default face. Built into `nanomuse/server/static/`.
- **Window**: from 0.1.30 the window is [nanoMuse Desktop](desktop.md) on
  DeepSeek Harness (`harness/`): the harness's Host and web app in an Electron
  shell of ours, nanoMuse's account, face, Hands and Reach as plugins, and this
  runtime bundled for the hands (`nanomuse mcp` over stdio). The Electron shell
  around this runtime and the web app (`desktop/app`, 0.1.19–0.1.29) — the
  tray, the transparent stage window that drew the ring where the hands were
  about to click, the global Stop and quick-chat shortcuts, *Start with the
  computer* — is retired; those come back on the harness's seams
  ([harness.md](harness.md), phase 7). The web app still lays itself out the
  Muse way on a wide window for anyone who opens `nanomuse serve` in a browser.
- **The standard-library binary** (`desktop/nanomuse_desktop`) was the
  zero-install fallback for a machine without Python and the origin of
  `nanomuse/hub`; dropped in 0.1.39, since nanoMuse Desktop carries the runtime.

### Hands on this computer

`computer_task` is the phone operator with a computer under it: the same loop
(look, decide one action, act through the Sentinel, look again), the same
report, the same Stop. What differs is the dialect and the device:

- **Dialect.** The model speaks Qwen's `computer_use` shape — `left_click`,
  `double_click`, `right_click`, `left_click_drag`, `mouse_move`, `scroll`,
  `type`, `key`, `wait`, plus `open` (an app by name), `answer`, `ask_user` and
  `terminate` — with coordinates on the 0–999 grid the phone uses, so one
  vision model serves both. The reply format (Thought / Action / one
  `<tool_call>`) and the parser are the phone's.
- **Device.** Screenshots through `mss` (every platform, scaled for the
  model); actions through `pyautogui` (`pip install "nanomuse[hands]"`), with
  `xdotool` as the fallback on Linux when it is there and pyautogui is not; the
  active window's title from the platform (`xdotool` / `osascript` /
  `GetForegroundWindow`) so the card and the log say *in Firefox*, not *on the
  screen*.
- **Permissions.** macOS asks for Screen Recording and Accessibility once;
  Settings → Hands says so and opens the panes. Under the desktop app both
  belong to its helper *nanoMuse Computer Use*
  ([desktop.md](desktop.md#macos-permissions)); a runtime run on its own is
  attributed to whatever started it (the terminal, say). Linux
  needs X11 (Wayland has no portable way to move the pointer yet; the page
  says so). Windows needs nothing.
- **Per app.** The first action in an application in a conversation asks:
  *Let Nova use Safari?* — once, for this conversation, or always. The answer
  is a Sentinel grant under `computer_app:<bundle id or name>`, so Settings →
  Permissions lists it and can take it back. `[sentinel] mode = "auto"` skips
  it like every other ask.
- **Never** typed by the hands: passwords, PINs, card numbers, one-time codes.
  The operator hands the screen over instead — a *Your turn* card with the
  reason; the person types, presses **Done**, and the operator looks again.

#### Window mode (macOS)

On a Mac the hands can work in **one application's window** instead of the
whole screen (`[hands] mode`, and *Where* on the Hands card: *Auto* / *One
window* / *Whole screen*; `nanomuse/computer/mac_window.py`):

- the picture the model sees is that window only — taken by the desktop app's
  helper *nanoMuse Computer Use* with ScreenCaptureKit on macOS 14 and later
  (`POST /window` of the operator, [gui.md](gui.md#hands-on-the-computer-the-picture-is-the-unit));
  by the runtime's own `CGWindowListCreateImage` when there is no helper —
  scaled for the model; coordinates are pixels of that picture and are mapped
  back to the window's place on the screen;
- clicks, drags, scrolls and keys are delivered to the application's process
  (`CGEventPostToPid`), not to the system cursor — the person keeps the mouse
  and can work in another window meanwhile; text goes in as unicode keyboard
  events, so 中文 and emoji arrive as typed; when Accessibility is granted, a
  button under the point is pressed through the accessibility tree (`AXPress`)
  rather than by a synthetic click;
- the agent names the window with `computer_act` → `computer_target` (`app`:
  a name as the menu bar shows it, or a bundle id) or with `app` on any
  action; `open_app` makes the opened application the target. *Auto* is
  window mode as soon as an application is named, the screen until then.

What the person sees: the Hands card says *Working in Safari's window; the
mouse stays yours*, the desktop stage draws the cursor where the click lands
(the hands' events carry `x`/`y` in screen pixels), and the approval cards
name the application. A window that cannot be found, captured (the helper's
Screen Recording row off — the operator's `403`, in its words) or driven drops
back to the whole screen with a note in the observation; nothing stops. When
the layer itself fails (the helper not there, pyobjc, the window server) *Auto* parks the hands on the whole
screen for the rest of that target, says so once, and tries the window again
when the next application is named; *One window* keeps trying, as asked —
the Hands card's *Where* line shows the reason either way. Linux and Windows stay
on the shared screen; `pip install "nanomuse[hands]"` brings the pyobjc
frameworks on macOS only.

## The phone

Already both roles since 0.1.12/0.1.13/0.1.17: the sandbox shell and Hands
locally, `nanomuse-pc` and the hub outward, `task` inward through the headless
chat runner. This stage's Android pass, in order: the hub `approve`
reaching the RiskGate card, a *Devices* entry in the drawer (both done in
0.1.19, see [The phone, in 0.1.19](#the-phone-in-0-1-19)), and the desk's
Hands events shown while it works. None of it blocks the desktop work.

## The browser: a demo on a simulated phone

[nanomuse.cn/web](https://nanomuse.cn/web/) leads to the showcase: a simulated
phone in the browser (MobileGym, with the nanoMuse app brought to the front —
`demo/mobilegym/apps/nanoMuse`) and, behind it, a private nanoMuse of the
visitor's own that the showcase gateway starts for the visit — the
`ghcr.io/nano-muse/nanomuse` image on a network with no way out but the
gateway, talking with the showcase's model, gone when the visit ends. A visitor
signs in to nanoMuse Cloud first (a code to a phone or an inbox, or the
account's password; `demo/showcase/gateway/showcase_gateway/visitors.py`), so
the project knows who is trying it and the same account is there on the day
the app is installed. The page says so plainly: this is a demo, a long way from
the Android app, and where the apps are. The homepage at
[nanomuse.cn](https://nanomuse.cn/) shows the same page in a frame (`?embed=1`,
no header of its own). The phone turns itself on; the Muse behind it is started
once the page has reason to think a person is looking (a few seconds in view,
or a pointer, key or wheel), never for a scripted browser, and never before the
sign-in the showcase asks for.

The earlier shape of the web — a kept Muse per Cloud account, with named
volumes and a seat on the hub like any other device (`accounts.py`,
`WEB_ENABLED=1`) — is still in the gateway for anyone who runs one, and off on
the project's server since 0.1.26. Details and the settings in
[demo/showcase/README.md](../demo/showcase/README.md).

## iOS, the web console, glasses

iOS speaks the hub (`info`, `open`, `notify`, `task`) and has had the shape
since 0.1.34 ([ios.md](ios.md)). The cloud console (`/app/`) is a front door with no hands
of its own and stays that way. Glasses are a sentence in and a sentence back,
the hands elsewhere — the hub is already enough for them.

## What is reused, and from where

- **UI-TARS-desktop** (Apache-2.0): the operator pattern — screenshot in,
  parsed action out, an `execute` per device — and the on-screen marker while
  the agent works. Not its Electron app or its model: its action space is the
  UI-TARS model's, ours is Qwen's `mobile_use` / `computer_use`.
- **OpenCode v2** (MIT): the desktop as a thin Electron shell that starts a
  local service and renders a web app against it (electron-vite,
  electron-builder, a tray, deep links later). Not its agent: it is a coding
  agent around a project directory; nanoMuse is a personal one around a person.
- **Codex** (Apache-2.0): the CLI as a first-class front door to the same
  agent, approvals in the terminal, a sandbox for commands — the runtime's
  `nanomuse chat` and the Sentinel already have that shape.
- **Qwen-Agent / MemGUI-Bench** (MIT): the `mobile_use` and `computer_use`
  dialects and the reply parser, already in `nanomuse/phone/operator.py`.
- **pyautogui**, **mss**, **xdotool**: mouse, keyboard and screenshots. No
  input library of our own.

## Status

| | Phone | Computer | nanoMuse Web (`WEB_ENABLED=1`; the demo phone since 0.1.26) | Web console | iOS |
|---|---|---|---|---|---|
| Local shell / files / browser | yes | yes (runtime) | yes, inside its container | no hands | no |
| Screen as a hand | Hands (0.1.12) | `computer_*` (0.1.19) | — | — | — |
| Drives other devices | `nanomuse-pc`, hub | `device_*`, `delegate` (0.1.19) | the same runtime | picks a device, sends a task | — |
| Answers other devices | yes | in a visible side chat (0.1.19) | yes | — | info / open / notify / task |
| GUI in the Android shape | reference | web app (sidebar on wide screens) + window (0.1.19) | the web app | console | since 0.1.34 |
| Stage while the hands work | `HandsStage` | Hands card; the stage overlay in the window | — | — | — |

Released with 0.1.19: the APK, the desktop installers (`nanoMuse-Desktop-…`,
[`.github/workflows/desktop-app.yml`](../.github/workflows/desktop-app.yml)),
the terminal binary (dropped in 0.1.39), and nanoMuse Web at nanomuse.cn/web (the demo on a
simulated phone since 0.1.26).

## Debugging it all on one machine

Two runtimes and a relay on `127.0.0.1` are enough to walk a task from one
device to another and back. Nothing here needs a real account, an e-mail
provider or a phone.

```bash
# 1. the relay, in dev mode: no CLOUD_SECRET, codes go to the log; sign-up and the
#    hub are on by default. Without UPSTREAM_KEY the proxy answers 503 while sign-up
#    and the hub still work; give the relay a real key (from the environment, never
#    on the command line) if you want the Cloud model to answer.
mkdir -p /tmp/nm-dev/cloud
CLOUD_DB=/tmp/nm-dev/cloud/cloud.db CODE_SENDER=log PUBLIC_BASE=http://127.0.0.1:8790 \
  PYTHONPATH=cloud .venv/bin/python -m nanomuse_cloud --host 127.0.0.1 --port 8790 \
  > /tmp/nm-dev/cloud/relay.log 2>&1 &

# 2. two runtimes, each with its own data dir, workspace and port
for d in a b; do
  mkdir -p /tmp/nm-dev/$d/home /tmp/nm-dev/$d/ws
  printf 'data_dir = "/tmp/nm-dev/%s/home"\nworkspace = "/tmp/nm-dev/%s/ws"\n\n[llm]\napi_key = ""\n\n[cloud]\nbase_url = "http://127.0.0.1:8790"\n\n[hub]\nname = "%s"\n' \
    $d $d "$([ $d = a ] && echo 'Desk A' || echo 'Laptop B')" > /tmp/nm-dev/$d/config.toml
done
# ambient provider keys would be picked up as the model — clear them for a clean first run
env -u OPENAI_API_KEY -u DASHSCOPE_API_KEY -u ANTHROPIC_API_KEY -u OPENAI_BASE_URL \
  .venv/bin/nanomuse serve -c /tmp/nm-dev/a/config.toml --no-auth --no-qr --port 8799 > /tmp/nm-dev/a/serve.log 2>&1 &
env -u OPENAI_API_KEY -u DASHSCOPE_API_KEY -u ANTHROPIC_API_KEY -u OPENAI_BASE_URL \
  .venv/bin/nanomuse serve -c /tmp/nm-dev/b/config.toml --no-auth --no-qr --port 8798 > /tmp/nm-dev/b/serve.log 2>&1 &

# 3. sign both in with the same e-mail in the first run (the code is in relay.log:
#    grep -i code /tmp/nm-dev/cloud/relay.log), pick "Use the Cloud model" on each.
# 4. (0.1.19–0.1.29) the Electron window over Desk A came from desktop/app; now open
#    http://127.0.0.1:8799/ in a browser, or sign nanoMuse Desktop in as a third device.
```

Then on Desk A: *Devices* shows Laptop B online; *Ask* (or the chip under the
chats) opens a chat *on Laptop B*; a task typed there runs on B, its tool
chips and approval cards appear in A with the device pill, an approval decided
in A closes the card on both sides, and B's answer lands in A's chat. Swap the
ports and the same happens the other way. Stop everything with
`ss -ltnp | grep ':879'` and `kill`.

## The phone, in 0.1.19

Three things the computer does are mirrored on Android since 0.1.19: the
phone's hub client reads the `tool` / `tool_result` / `approval_result` stages
(`ReachOffloadHandler`), hub `approve` frames reach `RiskGate` and the phone's
own approvals travel to the asker as `approval` events (`HubActions`), and a
*Devices* row sits in the drawer next to the chats. Still to come: the desk's
hands events (`HandsLive`) as a Hands card on the phone when the phone asked
for the task.
