# nanoMuse Desktop

The computer's Muse, in a window: nanoMuse built on
[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (`dsh`), laid out
like the Muse desktop ([desktop-muse.md](desktop-muse.md)), with the account, the face,
Hands on this computer's screen and Reach to every other device of the account as
plugins ([harness.md](harness.md)). Windows 10+, macOS 12+ and Linux x64; one
installer each, nothing to install first — the harness, the nanoMuse bundle and the
runtime for the hands are inside.

| | |
| --- | --- |
| Windows | `nanoMuse-Desktop-<version>-win-x64.exe` (NSIS; no certificate, so SmartScreen asks for *Run anyway*) |
| macOS | `nanoMuse-Desktop-<version>-mac-arm64.dmg` / `-mac-x64.dmg` (and `.zip`); ad-hoc signed unless a release was signed and notarized, then *Open Anyway* once in System Settings → Privacy & Security |
| Linux | `nanoMuse-Desktop-<version>-linux-x64.deb` (preferred) / `.AppImage` / `.tar.gz` — see [Linux notes](#linux-notes) |

Every release carries them (`.github/workflows/desktop-app.yml`; `SHA256SUMS-desktop.txt`
beside them). The code is under [`harness/`](../harness/): the bundle of plugins in
`harness/dsh-nanomuse`, the Electron shell in `harness/desktop`; how to build it yourself is
in [harness/README.md](../harness/README.md). Up to 0.1.29 the same installers wrapped the
Python runtime and the web app in an Electron shell of their own (`desktop/app`) and the
harness build shipped beside them as *nanoMuse Harness*; from 0.1.30 there is the one
desktop, and it installs over the old one (same application id).

## What it is

A dsh Host started by the shell as a child process, showing the harness's web app in a
window of ours: the rail (Chats, Search, Feed, Ideas, Goals, Library, Devices, the
hamburger), the chats column with the main chat and the side chats, the face and name
pinned over the conversation with a live status line and *Stop*, Muse's permission card
over the harness's approvals, the trajectory of a hands run in the chat (each step's
screenshot with the action drawn on it and the agent's words, to look back at during
and after the run), the profile panel with memory,
Muse's Settings pages (Connectors, Computer use, File system access, Dictation,
Permissions, Data controls with export and reset), the full-window first run. The agent
is dsh's — its agent loop, tools, skills, goals, plan mode, compaction, sub-agents, MCP
— speaking as nanoMuse through the `nanomuse` preset, with:

- **the account**: a phone number or an e-mail and a code (or a password, with a friend's
  invite code) against [nanoMuse Cloud](cloud.md); the key in dsh's credential store; the
  account's models as the *nanoMuse Cloud* provider of the harness's own OpenAI-compatible
  adapter — nothing of ours sits in the model path; Settings → Account is the whole account
  as the phone has it — the pool in yuan with the ways on when it runs low, the invite code,
  usage by kind and by model, the password, the devices holding a key, the timeline, deletion
  — read through the host's pass-through routes (`/nanomuse/cloud/me`, `/sessions`,
  `/account-events`, `/password`, `/sign-out-all`, `/delete-account`, `/config`);
- **Hands** on this computer: `nanomuse mcp` from the bundled runtime over stdio, the
  runtime's `computer_screen` and `computer_act` tools with their approvals, so "what is
  on my screen?" and "open the settings and turn the volume down" work out of the box.
  The mouse, the keyboard and the screenshot are the app's own (`src/operator.ts`, a
  port of UI-TARS-desktop's operator on `@computer-use/nut-js`), answered to the runtime
  over a loopback HTTP server with a per-launch token (`NANOMUSE_OPERATOR_URL` /
  `NANOMUSE_OPERATOR_TOKEN` in the runtime's environment; `GET /info`, `POST
  /screenshot`, `POST /execute`) — one capture path and one pointer space on every
  platform, no `xdotool` or `pyautogui` needed, and coordinates that are pixels of the
  picture the model saw ([gui.md](gui.md#hands-on-the-computer-the-picture-is-the-unit)).
  The runtime's own backends remain the fallback when the app is not the one running it.
  The connectors the runtime's `config.toml` turns on (mailbox, calendar, address book)
  arrive over the same server, and Settings → Connectors shows how to set each one up;
- **the rooms**: Feed, Ideas, Goals and Library as Muse has them, kept by the host in
  `nanomuse/rooms.json` and written by the agent in hidden chats (feed and ideas) or
  chats of their own (goals, with the harness's schedule plugin for their automations;
  Library creations under `~/nanoMuse/Library`), plus memory — what it remembers about
  you, read into every chat ([desktop-muse.md](desktop-muse.md#rail-rooms));
- **Reach**: this computer on the account's device list over the [hub](hub.md); the
  tools `devices`, `device_screen`, `device_shell`, `device_files`, `device_open`,
  `device_notify` and `delegate` for the phone and the other computers; the phone's
  `delegate` landing here as a dsh session "From <device>" with its approvals relayed
  back; remote control (`shell`, `files`, `open`, `screen`) behind a switch;
- **Coding agents**: *Settings → Coding agents* — this computer's Cursor, Codex and
  Claude Code chats (read from disk, a message starts the agent's own CLI, the run
  streams in with its tools, *Stop* ends it) and then the account's other computers',
  over the `coding.*` hub actions this computer announces too; a device card's *Coding
  agents* chip opens the page on that computer ([coding-agents.md](coding-agents.md)).
- **Network** (Settings → nanoMuse Cloud → Network): one proxy for what the app sends out —
  `http://host:port`, `https://`, `socks5://` or `socks5h://`, a `user:pass@` allowed and
  shown masked. Everything the dsh Host sends goes through it: your own keys, the ChatGPT
  sign-in's calls, *List models*, the pages the tools read, connectors, the update check,
  and the hands' runtime (`nanomuse mcp` inherits the same variables). nanoMuse Cloud — the relay, the hub's WebSocket, the sync — and loopback never
  do. The shell keeps it in `desktop.json` next to *open at login* and puts it on the dsh
  Host's environment at start (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` for SOCKS, `NO_PROXY`
  with `localhost,127.0.0.1,::1`, `cloud.nanomuse.cn` and the relay the plugin talks to, and
  `NODE_USE_ENV_PROXY=1`, which is what makes Node's fetch read them), so it takes effect
  after a restart — *Restart now* under the row restarts the Host with the window up. The
  phones have the same setting in the provider form, the web app in the own-key form, the
  runtime in `[llm] proxy` ([own-key.md](own-key.md#when-the-provider-cannot-be-reached));
- **Standing grants** (Settings → Permissions): every permission this computer remembers,
  in one list, grouped under the three tiers the phone's Permissions page uses — *Runs
  without asking* (the remote-control switch: every device of the account may run things
  here), *Remembered from the card* (a device allowed with *always* on a remote-control
  card; the hands in an app, from *Always in <app>* on a permission card), *Runs, then tells
  you* (nothing of the desktop's lands there today). Each row says what was allowed, for
  whom or where, when, and has *Revoke*; the empty state says that *always* on a card is
  what puts a row here. The Computer use page and the profile drawer keep their own shorter
  lists; this one is the complete one. The host answers `GET /nanomuse/cloud/grants` with
  the list and `POST /grants/revoke {id}` for any row of it.

## When the allowance is used up, and the relay's other answers

The account's free allowance gates the model, not the sign-in: when the relay answers a
turn with `allowance_exhausted`, the desktop shows the card the phones and the web app
show, under the turn that did not run, in the chat:

- one sentence — *The free allowance is used up.* — and that your sign-in and your devices
  keep working whichever way you pick;
- **your own model key**: the provider rows for where you are (the same rows as Settings →
  nanoMuse Cloud, with *Add key* and *Get a key* inline), *Other providers and what each key
  covers* folded under them — the list the relay sends with the refusal and with `/v1/me`
  (`spend.guidance`, [cloud.md](cloud.md#allowance)), not one written into the app — and
  the *Step-by-step guide* ([own-key.md](own-key.md));
- **a plan you already pay for**: the ChatGPT sign-in, right there, with the relay's caveat
  about it;
- **invite a friend**: the bonus for each of you and *Copy the link*;
- a star on GitHub, once, when the nudge policy allows it — the card's title and buttons are
  the app's; its sentence is the app's too unless the relay's policy carries one (`star.text`,
  `star.text_zh`, up to 200 characters; a Chinese UI takes `text_zh`, else `text`;
  [cloud.md](cloud.md));
- *Open Settings → nanoMuse Cloud* and *Try again* (the same words are sent again once a
  way on is set up).

The relay's other refusals are one plain sentence each, in the app's language, never the
status code or the JSON body:

| The relay said | The card says | Button |
| --- | --- | --- |
| `413` (the request is too big for the relay or the model's window) | *That message is too large for the model's window. Shorten it, leave out some attachments, or start a new chat.* | *New chat* |
| `401` (the key was retired elsewhere — a sign-out of every device, a deleted account) | *This sign-in is no longer valid. Sign in again under Settings → nanoMuse Cloud.* The desktop signs itself out at the same time, as it does when `/v1/me` answers 401. | *Sign in* |
| `403` (the account is disabled, or the relay does not take it) | *This account cannot use nanoMuse Cloud right now.*, with the relay's own words under it | *Open Settings → nanoMuse Cloud* |
| `429` without the allowance code (too many requests at once, the provider busy) | *Too many requests at once. Wait a moment and try again.* — with the relay's `retry_after` when it sent one | *Try again* |
| `429 daily_cap` (a relay that sets a daily share) | *Today's share of the allowance is used up. It resets tomorrow.*, with the relay's own words under it | *Try again* |
| `404 model_not_offered` | *nanoMuse Cloud does not offer that model any more.* | *Open Settings → nanoMuse Cloud* |
| `5xx`, or no answer at all (connection refused, timeout) | *nanoMuse Cloud did not answer.* / *Could not reach nanoMuse Cloud. Check the connection and try again.* | *Try again* |
| `429 allowance_exhausted` with `paused: true` (relay 0.22: the operator paused the free allowance, [cloud.md](cloud.md#controls)) | the same allowance card, led by *The free allowance is paused on this relay for now, not used up. Your sign-in, your devices and what is left stay as they are.* | the ways on, *Try again* |
| `503 service_paused` | *nanoMuse Cloud is paused by its operator for now; your sign-in and your data are kept. Try again later.* | *Try again* |
| `503 sync_paused` | *Conversation sync is paused on this relay for now; what is stored is kept and your devices keep working on their own.* | *Try again* |
| `503 hub_paused` | *The device hub is paused on this relay for now; each device keeps working on its own.* | *Try again* |
| `403 signup_closed` (at sign-in only) | the relay's own sentence — *New sign-ups are paused on this relay for now; existing accounts keep working.* | *Open Settings → nanoMuse Cloud* |

A refusal is not retried: before 0.1.40 the harness took the relay's `429` for a rate
limit and tried five more times (about twenty seconds) before the raw reply appeared; now
the card is there at once. A turn on your own key that a provider refused gets the same
shape — one sentence by the kind of failure, what came back folded under *What came back*.
The pieces are `src/refusals.ts` (the host reads the relay's reply on the `llm/stream`
waterfall and rewrites the failure to `nanomuse/<kind>`) and the chat's `turn-error` seat in
`src/client/RefusalCard.tsx`.

The pages outside the chat that talk to the relay (sign-in, the models list, the account
sheet, the avatar studio, the connectors, the devices) follow the same rule for the common
cases: the relay out of reach says *nanoMuse Cloud could not be reached. Check the connection
and try again.*, a deadline passed *nanoMuse Cloud did not answer in time. Try again in a
moment.*, a `429` *Too many requests just now. Wait a moment and try again.*, a `401` *Not
signed in to nanoMuse Cloud, or the sign-in has expired. Sign in again.*, a `5xx` *nanoMuse
Cloud ran into a problem (503). Try again in a minute.* with the status; and when the
desktop's own host on loopback does not answer at all, *This computer's nanoMuse is not
answering. Restart the app and try again.* Anything else reads *That did not work:* with the
message as it came (`failureText` in `src/client/api.ts`; the host turns a `fetch failed` or
a timeout on its side into the codes `unreachable` 503 and `timeout` 504).

**The 80 % heads-up.** After a turn on the account's model the host re-reads the account
(once a minute at most); when the relay says the pool is at 80 %, one dismissible line
shows above the composer — what is left, the invite bonus, *See the ways* — once per pool
size, as the phones show it in the chat and the web app above its composer.

## Config and data

`~/.nanomuse/desktop` (`NANOMUSE_DESKTOP_HOME` moves it) is the app's dsh home: the
profile under `profiles/nanomuse` (the bundle list, the person's own `cordis.patch.yml`
where Settings and the sign-in write the `nanoMuse Cloud` provider), dsh's credential
store with the account key, the sessions, `desktop.log` with the shell's and the Host's
lines, and `port` — the loopback port the Host had last time, tried first on the next
launch (then 38421, then any free one) so the window's origin, and with it everything
the browser side keeps in that origin's storage, stays the same from launch to launch. A
home kept by nanoMuse Harness 0.1.28–0.1.29 under `~/.nanomuse/harness`
is taken over once. `NANOMUSE_CLOUD_URL` points the account at another relay;
`NANOMUSE_PY` points the preset at another runtime for the hands. The CLI's own `~/.dsh`
is not touched. `nanomuse/hands.json` under the home (mode 0600) is the hands model as
Settings → Models resolves it — provider, model, base URL and the key — the same values
the plugin hands the runtime as its `NANOMUSE_GUI_*` environment. Since 0.1.41 the hands'
MCP client is mounted by the plugin itself (`dsh-nanomuse/hands-tools`) rather than by a
fixed preset row: a change under *Operating the screen* disposes the client and starts
`nanomuse mcp` again with the new environment, so it takes effect without a restart (a
hands call in flight finishes first). The file is removed when nothing is configured;
`nanomuse/rooms.json` keeps the rooms (feed, goals with their steps and progress, which
ideas were tried, the library index, memory).

## Models

Settings → Models, right after General, is one row per thing a model does: *Chat*,
*Operating the screen*, *Making pictures*, *Making clips*. Each picker lists nanoMuse Cloud
first while you are signed in, its recommended model marked, then one group per provider
you added under Settings → nanoMuse Cloud, each group holding only the models that can do
that row's job (the screen needs a model that sees images; the hands speak OpenAI's shape,
so an Anthropic or native Gemini key is named under the row but not listed). A row nothing
can do shows one sentence naming who could and *Add a provider*.

The picker is a button reading `provider · model` that opens a panel. A provider with a
long list (OpenRouter, SiliconFlow) shows eight models at first, its catalogue default for
that row and your current choice first, with *Show {n} more* at the foot of the group; once
the lists hold more than eight models in all, a *Search models* field at the top filters
every group by model id or name as you type (*No model matches* when nothing does). Esc
or a click outside closes the panel; the same picker serves Settings → Media. The folding
and the search live in `harness/dsh-nanomuse/src/client/model-list.ts`, checked by
`tests/model-list.test.mjs`.

What a row uses when you have not chosen: the provider new chats answer through, when it
is one of your own and has a model for the job (its catalogue default); else nanoMuse
Cloud while signed in; else the first of your providers that can. The three rows that
follow this order have *Automatic* as their first entry, with the row saying what it gives
right now (*Currently nanoMuse Cloud · qwen3.8-27b*, say); pick it to drop a choice you
made and let the row follow the order again. A chat pick is the default for new chats and
moves the main chat with it (*Applies to the main chat and to new chats; a side chat keeps
its model.*); a side chat keeps the model it was given, and the same pick twice writes
nothing. The phones follow the same rule. When the provider new chats answer through goes
away (its key removed, or the account signed out), the chat slot moves with it: to the
account while signed in, else to another key of yours, else to the stock default; it is
never left on a route no adapter serves, which showed as *no adapter registered for
provider "custom"* on every new chat in 0.1.41. Pictures through your own key go straight to that provider — Model Studio's
native image API, OpenRouter's image API, or the OpenAI shape for the rest — and nothing
is billed to the account; the avatar studio says so in place of the cost line. Clips come
from Model Studio only, through the account or your own Bailian key.

After you save a key, a small card asks *Use it for* with a toggle per thing the key can
handle, all on; *Use it* switches those rows to that provider, *Not now* changes nothing.
When a model of your own fails under a turn, the card offers *Use nanoMuse Cloud this
time* while signed in: that one message is sent again through the account and the chat
goes back to its model when the turn ends; the Models page stays as it was. *Use it* with
chat ticked moves the main chat too. Nothing falls
back on its own. The same button follows a failed studio round and a failed set of clips.

While signed in, the page starts with one switch, *Use nanoMuse Cloud models*. Off, the
account's models leave every picker and the automatic order, the harness's side calls (a
chat's title, a compaction) run on the chat row's own model instead, and a chat that still
sits on a Cloud model is not sent: a card says so and offers another model, a new chat, or
*Use nanoMuse Cloud this time*, the only thing that spends the allowance while the switch
is off. You stay signed in; sync, your devices and Settings → nanoMuse Cloud keep working.
Switching off while the chat row is the account's moves that row to your own chat model
when you have one; when you have none, the switch is refused with one sentence under it and
stays on, since nothing else could answer (the same rule on every client).

The profile's `node_modules/dsh-nanomuse` is a link (a junction on Windows) to the plugin
inside the installed app, rewritten at every launch whose install folder differs from the
link's target — an update that moved the app, say from `Programs\nanoMuse\nanomuse-desktop`
to `Programs\nanomuse-desktop`, leaves a link pointing nowhere, and 0.1.39 could not start
over it (`EEXIST: file already exists, symlink …` in `desktop.log`). Since 0.1.40 the stale
link is removed as a link and remade; should that still fail, the message names the path to
remove by hand.

A first start can be slow, on Windows in particular. The Host prints its address only once
every plugin of the profile has been loaded, and a fresh install has some 20 000 files under
`resources/dsh/node_modules` that the system reads for the first time; Windows Defender's
real-time protection checks each of them on that first read, and a slow or external disk
adds to it, so the first start can take several minutes. Up to 0.1.41 the shell gave up
after 120 seconds with "the host did not announce its address within 120 s" while the Host
was still loading (in one report it printed its address six seconds later). The shell now
waits as long as the Host process runs: after two minutes the loading page says *Still
starting*, with one sentence on why and the Host's last lines; after ten minutes a dialog
asks whether to keep waiting or quit, and quitting is the only thing that stops a Host that
is still starting. `desktop.log` carries `host: ready after N min` when a start took longer
than half a minute. A second start is quicker, since the files have been checked once;
should every start stay slow, excluding the install folder from real-time scanning helps.

## macOS permissions

The hands need two things from macOS: *Screen Recording* for the screenshots and
*Accessibility* for the mouse and the keyboard. Since 0.1.38 both belong to a small app of
their own, **nanoMuse Computer Use** (`nanoMuse.app/Contents/Helpers/nanoMuse Computer
Use.app`, bundle id `io.github.nanomuse.desktop.computer-use`): that is the row you switch
on in System Settings → Privacy & Security → Screen Recording and → Accessibility. nanoMuse
Desktop itself holds neither.

Why a second app. macOS attributes a permission request to the *responsible process* — the
one LaunchServices started, together with everything it spawned. A child process of the
app is the app, as far as the panes are concerned, which is why the bundled runtime never
appeared in them; an app bundle started through `open` is responsible for itself and gets
its own row, named for what it does (Qt's write-up *The Curious Case of the Responsible
Process* walks through the attribution; Codex's *Codex Computer Use.app* is the same
arrangement). The helper is a few hundred lines of Swift (`harness/desktop/mac/computer-use/`)
on a loopback HTTP server with a per-launch token: it reports its two grants, asks for them
with the system's own dialogs (`CGRequestScreenCaptureAccess`,
`AXIsProcessTrustedWithOptions`), takes the picture — with **ScreenCaptureKit** on macOS 14
and later (`SCShareableContent` → the main display → `SCContentFilter` →
`SCScreenshotManager.captureImage`, at the display's pixel size with the cursor in it), with
`CGDisplayCreateImage` on 12 and 13 — not Chromium's `desktopCapturer`, whose black and
absent frames were the 0.1.36 trouble — and moves the mouse and types with `CGEvent` (text
of any script goes in as the characters themselves, so 中文 types without the clipboard).
Why ScreenCaptureKit: on macOS 26 and 27 `CGDisplayCreateImage` returns nothing even with
Screen Recording granted, which 0.1.39 logged as `helper screenshot failed (no screenshot:
noImage)` and then covered with a `desktopCapturer` frame that was black or stale. The app
starts the helper at launch — to read the grants and to ask for the missing ones — and
quits it when it quits; the helper also leaves on its own when the app is gone. It has no
window and no Dock icon; Activity Monitor lists it as *nanoMuse Computer Use*.

What you do, once, on a Mac that has not granted anything yet (checked on macOS 27.0.1,
Apple silicon):

1. Open nanoMuse from the Applications folder (drag it there from the disk image first — see
   *The quarantine flag* below). Settings → Computer use → Permissions, or the first time the
   hands are about to be used: a short dialog of ours says what is being asked and why.
2. **Screen Recording.** The system's dialog appears — *"nanoMuse Computer Use" would like to
   record this computer's screen and audio* — with *Open System Settings*. The pane (called
   *Screen & System Audio Recording* on macOS 15 and later) lists **nanoMuse Computer Use**;
   switch it on. macOS may offer to *Quit & Reopen* the helper: either answer is fine, the
   app starts the helper again by itself and the next screenshot is the real screen. Nothing
   of nanoMuse itself restarts; the conversation goes on.
3. **Accessibility.** The system's dialog again, then the switch next to **nanoMuse Computer
   Use** in the Accessibility pane; macOS asks for your password or Touch ID to flip it. It
   takes effect at once.

The Permissions page shows both rows live, names the helper as the thing to switch on, and
its *Try it* buttons take a test screenshot and move the mouse through the real chain (the
app → the runtime → the helper), so what passes there passes in a chat. Switch a grant off in
the pane and the hands say so on their next step: *macOS: switch on nanoMuse Computer Use
under System Settings → Privacy & Security → Screen Recording. The helper restarts by itself;
the app does not need to.* (`403` from the operator; the runtime never falls back to `mss` or
`screencapture`).

**How the Screen Recording check works.** The helper's `/status` says `granted`, `denied` or
`unknown`. `CGPreflightScreenCaptureAccess` is asked first — TCC's own answer, no prompt —
and a *no* is `denied`. On macOS 14 and later a *yes* is confirmed with ScreenCaptureKit
(`SCShareableContent`): when that throws `userDeclined` or `noDisplayList` the grant is not
really there and the status is `denied` with the reason; another error is `unknown` with the
reason, and the next screenshot tries anyway and reports what ScreenCaptureKit said. So
`granted` means a picture will come back, not just that a switch is on. Requesting stays the
system's own dialog (`CGRequestScreenCaptureAccess`) plus the deep link to the pane.

**When the picture fails, you are told.** With the helper bundle in the app, the operator
never takes a `desktopCapturer` frame in the helper's place — a black or stale picture would
reach the model as if it were the screen. What the chat and `computer_screen` say instead:

- Screen Recording missing for the helper: *macOS: switch on nanoMuse Computer Use under
  System Settings → Privacy & Security → Screen Recording. The helper restarts by itself; the
  app does not need to.* (the `403`; Settings → Computer use says the same).
- ScreenCaptureKit failed with the grant in place: *no screenshot: nanoMuse Computer Use
  could not take the picture — no screenshot: ScreenCaptureKit userDeclined (-3801): …* — the
  SCK error by name and code, followed by the system's text (`noDisplayList`,
  `failedToStart`, `internalError`, … — a reader can look the code up).
- The helper did not start (quarantine kept, no port, App Translocation): *no screenshot:
  nanoMuse Computer Use did not start (…)* with the reason the `helper:` log lines give;
  Settings → Computer use shows the same reason as *not available*.

The pre-0.1.38 `desktopCapturer` path remains only for a build without the helper bundle
(below).

**Checking it on a Mac.** `~/.nanomuse/desktop/desktop.log` has the chain:

- `helper: nanoMuse Computer Use <version> (pid …) at http://127.0.0.1:… — screen granted,
  accessibility true, capture ScreenCaptureKit` — the helper is up and, on macOS 14+, says
  which path takes the picture (`CoreGraphics` on 12 and 13).
- `permissions: accessibility=granted screen=granted (nanoMuse Computer Use <version>,
  capture ScreenCaptureKit)` — the grants as the app read them at launch; a `screen=denied`
  here with the switch on in the pane carries ScreenCaptureKit's reason after the version.
- `operator: helper screenshot failed (…) — not falling back to desktopCapturer` — the
  picture failed, the line says why, and the chat got the same words. There is no `using the
  Electron path` any more.

Then Settings → Computer use → *Try it*: the test screenshot is the helper's picture, or the
error above.

**The quarantine flag.** The disk image you download carries macOS's quarantine flag, and so
does every file copied out of it, the helper included. Opening nanoMuse settles the flag for
nanoMuse — Gatekeeper's dialog, *Open Anyway* — but not for the helper, which LaunchServices
starts as an app of its own. A quarantined, unapproved helper is started from a *translocated*
copy — a read-only mount under `/private/var/folders/…/AppTranslocation/<random>/d/` whose
name changes on every launch — and Gatekeeper's own *could not verify* dialog can come up
for it as well, with the helper never answering. That is what 0.1.38 did: the helper ran (Activity Monitor showed it),
Accessibility could be granted, and no *nanoMuse Computer Use* row ever appeared in the
Screen Recording pane, because tccd had recorded a path that no longer existed. Since 0.1.39
the app removes the flag from the helper before the first launch (`xattr -dr
com.apple.quarantine` on `Contents/Helpers/nanoMuse Computer Use.app`; the log says
`helper: removed the quarantine flag…`), after which the helper starts in place and its rows
stay. This needs the bundle to be writable — your own copy in Applications is. Run from the
disk image or straight from Downloads, nanoMuse itself is translocated, the helper cannot be
fixed and is not started; the log says *move it to the Applications folder and open it
again*, and the hands use the app's own path meanwhile (below).

More to know:

- Screen Recording reaches freshly started processes only — that process is the helper. When
  the switch flips while the app runs, the app restarts the helper by itself (the log says
  `restarting the helper for the new grant`); the *Restart* button on the Permissions page
  restarts the helper too, never the app, and two clicks are one restart.
- The picture is the main display, at most 2 Mpx (a 3456×2234 Retina panel comes down to
  1758×1137), coordinates in points. Only the main display is captured and driven. Holding a
  key across actions (`press` / `release`, UI-TARS's names) works since 0.1.39.
- *Window mode* — the hands working inside one application's window — lists the windows
  and takes the window's picture through the helper too (`GET /windows`, `POST /window`;
  ScreenCaptureKit's `SCContentFilter(desktopIndependentWindow:)` on macOS 14+), so the
  helper's Screen Recording row covers it. The events are still posted from the runtime
  (`CGEventPostToPid`), which macOS attributes to **nanoMuse** itself: window mode needs
  the *nanoMuse* row in the Accessibility pane on top of the helper's two, and falls back to
  the whole screen with a notice when it is missing. Without the helper bundle the runtime
  captures windows itself (`CGWindowListCreateImage`; the runtime's log says `window mode:
  the runtime captures windows itself …`) and needs the *nanoMuse* Screen Recording row as
  well. Settings → Computer use says whether window mode is available.
- macOS 15 and later asks again from time to time whether an app that captures the screen
  without the system's picker may go on; answer *Allow* for nanoMuse Computer Use.
- To start the permission flow over: `tccutil reset ScreenCapture
  io.github.nanomuse.desktop.computer-use; tccutil reset Accessibility
  io.github.nanomuse.desktop.computer-use`, then Settings → Computer use → Permissions again.
  A grant left on *nanoMuse Desktop* / *nanoMuse* from an earlier version is used by window
  mode only (above) and can otherwise be switched off.

Without the helper bundle — a build without it, a development run before `build.sh` — the
app works as before 0.1.38: the grants are nanoMuse Desktop's own
(`io.github.nanomuse.desktop`), read through `@computer-use/node-mac-permissions` and
`@computer-use/mac-screen-capture-permissions`, the picture comes from `desktopCapturer`
and the input from `@computer-use/nut-js`, and a Screen Recording grant needs the app
restarted (*Restart now*). A bundle that is there but did not start (the log's `helper:`
lines say why) is not that case: the hands refuse with the reason until it starts, rather
than moving to the app's own grants that nobody switched on. The Permissions page names
whichever is in use.

The honest caveat: macOS keys a grant to the app's code signature. With a Developer ID
signature the helper's *designated requirement* (identifier + team) is the same from build
to build, so the grant survives updates. The project's certificate is still pending with
the Account Holder, so today's builds are ad-hoc signed: an ad-hoc signature is keyed to the
binary's hash, and every new build of the helper starts the two grants over (as it did for
the app itself). Until the certificate is there, expect to switch the helper on again after
each update — and, when developing, after each `build.sh`: a helper you rebuilt is a new
app to tccd, so `npm start` asks for both grants again each time the Swift changed (the
TypeScript can change freely).

## macOS signing

Without an Apple developer certificate the bundle is ad-hoc signed and macOS asks once.
With the repository secrets `MAC_CERT_P12_BASE64`, `MAC_CERT_PASSWORD`,
`APP_STORE_CONNECT_KEY_ID`, `APP_STORE_CONNECT_ISSUER_ID`, `APP_STORE_CONNECT_KEY_P8` and
(optionally) `APPLE_TEAM_ID`, `scripts/desktop-app/package-mac.sh` signs with the
Developer ID Application certificate under the hardened runtime
(`harness/desktop/resources/entitlements.mac.plist`), notarizes with notarytool and
staples. The certificate is exported from Keychain Access as a `.p12` and base64-encoded;
the App Store Connect key is the `.p8`'s text.

The helper, *nanoMuse Computer Use.app*, is built on the macOS runner by
`harness/desktop/mac/computer-use/build.sh` (plain `swiftc`, arm64 and x86_64 joined with
`lipo`, deployment target macOS 12.3 — the first with ScreenCaptureKit, which the binary
links; the SCK capture runs on 14+, CoreGraphics before) before electron-builder copies it into
`Contents/Helpers` (`mac.extraFiles` in `electron-builder.yml`). `package-mac.sh` signs it
first, as a bundle of its own — same identity, hardened runtime, its own identifier
`io.github.nanomuse.desktop.computer-use`, none of the app's entitlements — and then the
outer app. A local macOS build wants `build.sh` run before `npm run dist:dir`; without it
electron-builder only warns that the source is missing and the app ships without the
helper, on the pre-0.1.38 path.

## Linux notes

- **The `.deb` is the one to prefer** (Debian, Ubuntu and their derivatives): it installs
  `/opt/nanoMuse/nanomuse-desktop`, the icon set and the desktop entry, and the launcher
  finds it. `sudo apt install ./nanoMuse-Desktop-<version>-linux-x64.deb`.
- **The AppImage needs FUSE.** It mounts itself at start; when the machine has no
  `libfuse2`, or `fusermount` is not permitted (containers, some corporate images — the log
  says `fusermount: mount failed: Operation not permitted` / `Cannot mount AppImage, please
  check your FUSE setup`), run it unpacked instead:
  `./nanoMuse-Desktop-<version>-linux-x64.AppImage --appimage-extract-and-run`, or take the
  **`.tar.gz`** — the same app as a plain folder: unpack it anywhere and run
  `./nanomuse-desktop` from it (no FUSE, no root).
- **The icon does nothing.** The app allows one instance at a time: a click on the launcher
  while a copy is already running tells *that* copy to show its window. Up to 0.1.36 a copy
  whose window had been closed stayed alive for the tray and did not answer — the click
  looked dead. Since 0.1.37 the running copy opens its window again on the click; a copy
  from before that is still in the tray — quit it there (*Quit*), or
  `pkill -f /opt/nanoMuse/nanomuse-desktop`, and click again. Closing the window keeps the
  app in the tray only while the menu-bar switch (Settings → General → App behavior) is on;
  with it off, closing the window quits. **Ctrl+Q** quits from the window either way (Help →
  Quit; the menu bar shows on Alt).
- **No tray icon on Ubuntu 20.04.** GNOME 3.36's appindicator extension (v33) does not take
  the registration Electron 44 sends (a bus name with an object path appended), so the icon
  falls back to an XEmbed tray GNOME Shell does not show — the app is in the tray, invisibly.
  Ubuntu 22.04 and newer show it. On 20.04 use Ctrl+Q, or switch the menu-bar option off so
  that closing the window quits.
- **Wayland.** The hands drive the mouse and read the screen through X11; on a Wayland
  session they say so and stay off — Settings → Computer use's *Take a test shot* and the
  first "what is on my screen?" both answer *the hands are off on this computer: Wayland
  session: … Log in with Xorg …* — and the runtime does not try `xdotool` or `pyautogui`
  behind the app's back (under XWayland they would start and move nothing you can see).
  Choose *Ubuntu on Xorg* on the login screen. The session type is read from
  `XDG_SESSION_TYPE`; a Wayland compositor started by hand shows as `WAYLAND_DISPLAY`
  without a `DISPLAY`, which counts too.
- **Hands on this computer** (X11). Nothing to grant: the app's own operator moves the
  pointer and types through libnut (XTEST) and takes the picture through Electron's
  capturer, and the runtime's `nanomuse mcp` reaches it over loopback — no `xdotool`,
  `pyautogui` or `mss` is needed, and none is used while the app's operator answers. The
  pointer moves on the X display the app was started on (`DISPLAY`), in root pixels: on a
  HiDPI desktop that is the logical size × the scale factor (a 1920×1080 scale-2 display is
  3840×2160 to the hands), and the picture the model sees is that root scaled down to at
  most 1600 wide and 2 Mpx. The frame the app draws around the screen while the hands work
  (the glow, a light breathing along the four edges) takes no clicks: it steps aside for every pointer action — hidden before the
  pointer moves, back right after with the marker where the click landed, so it blinks for
  about 150 ms per click — and its X11 input region, which Chromium clears whenever the
  window's bounds change, is set again after every such change; should a click ever reach
  the glow anyway, the app sets the region again on the spot and writes one line to the
  log (`glow: the pointer reached the glow …`). Typing and keys do not move the pointer,
  so the glow stays up for them and focus is untouched. A window manager is needed for a
  sensible picture (without one Electron's capturer can return a black frame — the runtime
  then falls back to its own capture). Steps that act on your behalf (Enter, a submit, heavy shortcuts, clicks on words
  from the sensitive list) wait for the card in the chat or on the capsule; *Allow once*
  runs the step, *Always allow in <app>* keeps the hands going in that app until you revoke
  it under Settings → Permissions. Text outside ASCII is typed through the clipboard
  (`xclip`/`xsel` are not needed — Electron's clipboard is used) and Ctrl+V; the previous
  clipboard content is put back afterwards.
- The log is `~/.nanomuse/desktop/desktop.log` (each operator action is a line, `operator:
  click at 1249,1096`); the launcher's side is in `journalctl --user -n 200`.
