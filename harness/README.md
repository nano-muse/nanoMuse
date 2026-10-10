# nanoMuse on DeepSeek Harness

> This directory is **nanoMuse Desktop**: nanoMuse as a set of plugins on
> [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (`dsh`), in an
> Electron shell of our own. Two things ship from here with every release: the desktop
> app — `nanoMuse-Desktop-<v>-…` installers for Windows, macOS and Linux with the harness,
> the bundle and the runtime for the hands inside (below, *The desktop app*) — and the
> bundle alone, `dsh-nanomuse-<v>.tgz`, for people who already run DeepSeek Harness
> Desktop and want the Muse in it (below, *In dsh's desktop app*). From 0.1.30 this is the
> one desktop app; the Electron shell around the Python runtime (`desktop/app`, 0.1.19 to
> 0.1.29) and the terminal binary that followed it (0.1.30 to 0.1.38) are retired, and the
> Python runtime stays for self-hosting and the web console. Why and where it goes: [docs/harness.md](../docs/harness.md);
> what it has of Muse's and what it still lacks: [docs/desktop-muse.md](../docs/desktop-muse.md).

`dsh-nanomuse/` is one **bundle** — a package dsh loads into a profile, carrying a patch
over the stock configuration and the plugins the patch names:

| Row                | Half    | What it does                                                                                                                              |
| ------------------ | ------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `nanomuse`         | host    | Serves the face's stills under `/nanomuse/assets/` — the dragon's, and the account's drawn face at `face/<id>/<mood>.webp`.                 |
| `nanomuse-cloud`   | host    | The account: sign-in by phone or e-mail code against the relay, the key in dsh's credential store, the account's chat models written into `dsh-llm-pi-ai` as the `nanoMuse Cloud` provider. The hub client: this computer on the account's device list, answering `info` and `notify` always, `shell`, `files`, `file.get`, `file.put`, `open`, `screen` (the runtime's shapes, in `actions.ts`) and `task` (the phone's `delegate`, run in a dsh session "From <device>" with its approvals relayed back, in `task.ts`) while the remote-control switch is on. The profile pulled from the relay (name, face), the Hands/Reach calls in flight, the calls other devices made here, all streamed to the browser over SSE. Loopback API under `/nanomuse/cloud/`. |
| `nanomuse-reach`   | host    | **Reach**: the tools `devices`, `device_screen`, `device_shell`, `device_files`, `device_open`, `device_notify`, `delegate` over the hub, approvals through dsh's card, *Stop* stopping the delegated job on the other device; a system-prompt context with the agent's name, its look and the devices online. |
| `nanomuse-rooms`   | host    | **The rooms**: Feed, Ideas, Goals and Library in `$DSH_HOME/nanomuse/rooms.json` under `/nanomuse/rooms/*` with SSE — the feed and ideas written by the agent in hidden chats, goals as chats of their own with the schedule plugin's automations, the Library from `present` and `library_add` under `~/nanoMuse/Library`; **memory** (one-line facts, read into every chat; import, forget); the tool catalogue the Connectors page shows; data export (a zip) and reset. `nanomuse-rooms-tools` (in the preset) adds `goals_room_update`, `feed_post`, `library_add`, `remember` and the prompt context. |
| `nanomuse` (client)| browser | The window the way Muse shapes it ([docs/desktop-muse.md](../docs/desktop-muse.md)): the `sidebar` seat as a rail (Chats, Search, Feed, Ideas, Goals, Library, Devices, hamburger) plus a chats column of *Main chat* and *Side chats*; the four rooms as `main` panels; the live stage (the screen the agent works on, picture-in-picture, caption, take-over) as a `shell.overlay`; the face, name and a live status chip pinned above the conversation with *Stop*, *Invite* at the top right; a profile panel beside the chat (look, name, activity, approvals, schedule, memory); the composer as one pill, the bubbles and Muse's permission card as styles over the harness's DOM; the `sidebar.settings` seat as a grouped dialog (General with the harness's own rows and the shell's App behavior, Account, Models, Agents, Connectors, Computer use, File system access, Dictation, Devices, Permissions, Data controls with import memory / download your data / reset, Help & support, Legal, the other plugins' pages under Advanced, Sign out); the first run full-window (welcome → sign in → code boxes → the permissions carousel → ready); Muse's light and dark tones with the accent from the face's colour; toasts for notices from other devices and for what they did here. |
| `preset-nanomuse`  | patch   | An agent preset with nanoMuse's voice and the same tools as dsh's *Standard*, plus **Hands**: dsh's MCP client on `nanomuse mcp`, the runtime's `computer_screen`/`computer_act` over stdio, and the Reach plugin. New sessions start from it. |
| `system-prompt`, `agent-preset-registry`, `ui-brand-official`, `ui-sidebar`, `ui-settings-general` | patch | The persona for preset-free compositions, the default preset, and the stock brand mark, sidebar and settings shell stepping aside for ours. |

Everything else — the agent loop, tools, skills, goals, plan mode, compaction,
sub-agents, MCP, the web UI — is dsh's, unchanged.

## Run it

Node 22.19+ (24 is what we use) and pnpm. dsh is installed separately; the bundle is
linked into a profile of it, so you can hack on the bundle and restart.

```sh
# 1. a scratch dsh and a scratch home (nothing touches ~/.dsh)
mkdir -p /tmp/nm-dev/dsh && cd /tmp/nm-dev/dsh && npm init -y >/dev/null && npm install @deepseek-ai/dsh@0.2.0-rc.2
export DSH_HOME=/tmp/nm-dev/dsh-home

# 2. build the bundle
cd /path/to/nanoMuse/harness/dsh-nanomuse
pnpm install && pnpm build && pnpm test

# 3. a profile from dsh's web template, with the schedule bundle (the goals' automations) and ours linked in
/tmp/nm-dev/dsh/node_modules/.bin/dsh --profile nanomuse --from-default-profile web --dump-config >/dev/null
/tmp/nm-dev/dsh/node_modules/.bin/dsh plugin --profile nanomuse add @deepseek-ai/dsh-experimental-schedule-bundle
/tmp/nm-dev/dsh/node_modules/.bin/dsh plugin --profile nanomuse add "$PWD"

# 4. boot — against the production relay, or a local one (docs/every-device.md, "Debugging it all on one machine");
#    NANOMUSE_PY points at the runtime that serves the hands when `nanomuse` is not on PATH
NANOMUSE_CLOUD_URL=http://127.0.0.1:8790 NANOMUSE_PY=/path/to/nanoMuse/.venv/bin/nanomuse \
  /tmp/nm-dev/dsh/node_modules/.bin/dsh nanomuse --no-open --port 3082
```

Open the printed `?token=` URL. The first run meets the agent and signs in (a local
relay started with `CODE_SENDER=log` prints the code in its log); Settings → *nanoMuse
account* does the same later. The account's models then appear in the model picker
under *nanoMuse Cloud* and a new session answers through the relay, as nanoMuse. "What
is on my screen?" makes it call `mcp__nanomuse__computer_screen` — the runtime's hands,
started by dsh as a child process (`nanomuse mcp`; a display is needed for a picture) —
with the capsule at the top while it works. `dsh --profile nanomuse --dump-config` shows
the composed configuration with our rows marked `patched by dsh-nanomuse`.

For Reach, put a second device on the same account: a dev runtime from the recipe in
[docs/every-device.md](../docs/every-device.md) ("Debugging it all on one machine"),
signed in with the same identifier, is enough — it appears under *Devices* in the
settings section and in the agent's context, and "list the home folder on Laptop B",
"run `uname -a` on Laptop B" (approval card first) and "ask Laptop B's Muse what time it
is" (`delegate`; its approval requests come back here) exercise the tools. Renaming the
agent or picking an emoji on that runtime changes the desktop's brand mark within
seconds. The other way round, "run `uname -a` on <this computer's name>" in that
runtime's chat runs here (after its own Sentinel approval) and shows as a toast;
"ask Desk A's Muse to …" there (`delegate`) runs as a session named *From Laptop B* here,
with any approval it needs shown on Laptop B. By default each of those asks the person
at this computer first — a card at the top of the window: *Allow once*, *Always for
Laptop B*, *Not now* (the always list is under Devices, with *Ask again* beside each) —
and the *Remote control without asking* switch under *this computer* lets every device
of the account through without the card.

After changing `src/`, `pnpm build` and restart dsh (the client half is served from
`lib/client.js`; append `?v=N` to the page URL if the browser keeps the old one).
Changes to `cordis.patch.yml` or `presets/` also need a restart — bundle layers are
read at boot.

## In dsh's desktop app

dsh's own desktop app ([`apps/desktop`](https://github.com/deepseek-ai/deepseek-harness/tree/master/apps/desktop))
is an Electron shell around the same web app, with a profile named `desktop` that takes
external plugins. The bundle goes in the same way as above. Every release carries it
packed, `dsh-nanomuse-<v>.tgz` (`nanoMuse-Harness-<v>.tgz` up to 0.1.29) with its line in
`SHA256SUMS-harness.txt` (built by
`.github/workflows/harness.yml`, which also installs the tarball into a fresh dsh
profile to be sure it loads): install DeepSeek Harness Desktop 0.2.0-rc.2 from
[its releases](https://github.com/deepseek-ai/deepseek-harness/releases), start it once
so the `desktop` profile exists, quit it fully, then

```sh
dsh plugin --profile desktop add ~/Downloads/dsh-nanomuse-0.1.30.tgz   # or the source tree, /path/to/nanoMuse/harness/dsh-nanomuse
```

and start it again — the window comes up as nanoMuse ([docs/desktop-muse.md](../docs/desktop-muse.md)):
the rail, the pinned face, our Settings and first run, the harness's own pages under
*Advanced*. `dsh` here is the command the desktop app installs (*Manage dsh Command…* in
its menu) or any dsh of the same version with `DSH_HOME` pointing at the app's home;
`dsh plugin --profile desktop remove dsh-nanomuse` takes it out again. Hands need the
runtime on this computer too (`pipx install "git+https://github.com/nano-muse/nanoMuse"`,
or `NANOMUSE_PY` pointing at it) — the preset starts `nanomuse mcp` for them. The app's
name, icon and About are DeepSeek Harness's there; the app below is ours.

## The desktop app: nanoMuse Desktop

`desktop/` is an Electron shell of our own around the same web app — the name, the icon,
the About, the first run and everything else nanoMuse's — with **dsh and the bundle
inside it**, so nothing is installed at first launch and no Node, pnpm or Python is
needed on the machine:

| | |
| --- | --- |
| Windows | `nanoMuse-Desktop-<v>-win-x64.exe` (NSIS; no certificate, so SmartScreen asks for *Run anyway*) |
| macOS | `nanoMuse-Desktop-<v>-mac-arm64.dmg`, `-mac-x64.dmg` (and `.zip`; ad-hoc signed unless the Apple secrets are set, then *Open Anyway* once in System Settings → Privacy & Security) |
| Linux | `nanoMuse-Desktop-<v>-linux-x64.AppImage`, `.deb` |

How it runs, in one paragraph: the shell starts the harness's Host as a child process —
its own Electron binary in Node mode (`ELECTRON_RUN_AS_NODE`, `--expose-internals`, the way
DeepSeek Harness's desktop does; the harness's `require-builtin` addon accepts exactly the
Electron the harness was built against, so [`package.json`](desktop/package.json) pins
`44.0.0`) running the `dsh` under `resources/dsh`, where npm installed `@deepseek-ai/dsh`
and `dsh-nanomuse` side by side at build time. The profile the Host boots lives under
`~/.nanomuse/desktop/profiles/nanomuse` (its own home; the CLI's `~/.dsh` is not touched; a
home left by nanoMuse Harness 0.1.28–0.1.29 under `~/.nanomuse/harness` is taken over once):
a manifest naming the three bundles and a link `node_modules/dsh-nanomuse` to the copy
under resources, refreshed every start, which is how the Loader finds a bundle that is not
among the harness's own packages. The shell reads the Host's `dsh web: http://127.0.0.1:…`
line and loads that URL; external links open in the browser; a Host that does not come up
gets a dialog with the log's tail on the clipboard. The runtime for the hands is bundled
too (a PyInstaller build of the Python package, `resources/runtime`), and
`NANOMUSE_PY` points the preset's `nanomuse mcp` at it — so "what is on my screen?" works
out of the box. `~/.nanomuse/desktop/desktop.log` has the shell's and the Host's lines.

Build it yourself (Node 22+, pnpm; Python 3.12 with `pip install -e ".[hands]" pyinstaller`
for the hands):

```sh
cd harness/dsh-nanomuse && pnpm install && pnpm build          # the bundle
cd ../desktop && npm ci
node scripts/prepare-dsh.mjs                                     # dsh + the bundle → dsh/ (npm, public registry, this platform's prebuilds)
python ../../scripts/desktop-app/build-runtime.py --target harness/desktop/runtime   # optional: the hands
npm start                                                        # or: npm run dist (installers under dist/)
node scripts/smoke.mjs                                           # boots the staged harness once in Node mode
```

`.github/workflows/desktop-app.yml` does the same per platform on every release tag
and attaches the installers to the release (`SHA256SUMS-desktop.txt` beside them); a
push that touches `harness/` builds Linux and boots the packaged harness once.
`NANOMUSE_DESKTOP_HOME` moves the home, `NANOMUSE_CLOUD_URL` points the account at
another relay, `--screenshot=<png>` writes the window once the web app is up and quits
(the check the shell has for itself).

What is DeepSeek Harness's in the window stays theirs: the preview notice, the plugin
manager (which cannot install anything here — there is no pnpm; the bundle is the one
plugin), the terminal, Creator. What is still ahead for this app is in
[docs/harness.md](../docs/harness.md#phases): signing, an update feed, and the day
`desktop/` retires.

## Layout

```
dsh-nanomuse/
  package.json          the bundle: dsh.bundle.patch, dsh.client (platform web, injected client packages)
  cordis.patch.yml      our layer over dsh-base + dsh-web-app
  presets/nanomuse.patch.yml   the agent preset (Standard's tools, nanoMuse's voice)
  src/index.ts          host root row: the stills routes (the dragon's, the account's face)
  src/cloud.ts          host service `nanomuseCloud`: state, credential, provider row, hub + profile owner,
                        the Hands/Reach call tracker (tools/execute hook), SSE, loopback API
  src/hub.ts            the hub as a client: hello/welcome/devices, calls out and in, reconnect (no Cordis)
  src/actions.ts        this computer's hands for the other devices: shell, files, file.get/put, open, screen
                        (the runtime's shapes, limits and error codes)
  src/task.ts           a task from another device run in a dsh session: the session per conversation, the run
                        streamed back as the runtime's event frames, approvals relayed to the asker, stop
  src/profile.ts        the account profile on disk: pull when newer, face stills cached per face id
  src/reach.ts          plugin `nanomuse-reach`: the device_* tools, delegate, the system-prompt context
  src/rooms.ts          host service `nanomuseRooms`: the rooms' store and routes, the hidden generation chats, goal
                        chats and their timeline, the Library index, memory, the tool catalogue, export (a zip writer) and reset
  src/rooms-tools.ts    plugin `nanomuse-rooms-tools` (in the preset): goals_room_update, feed_post, library_add, remember, the prompt context
  src/relay.ts          the relay as a client (plain fetch; tested against a fake relay)
  src/client/
    index.ts            slot registrations: the sidebar and settings seats, brand mark/name with moods,
                        hero mark, the header, the Devices panel and section, onboarding steps, toasts
    live.ts             the SSE store (profile, hub, calls, notices) behind useLive()
    styles.ts           Muse's tones over the harness's tokens (light/dark), the accent, every nm-* class
    MuseSidebar.tsx     the rail (Chats, Search, Feed, Ideas, Goals, Library, Devices, hamburger) and the column that holds the chats
    FeedPanel.tsx, IdeasPanel.tsx, GoalsPanel.tsx, LibraryPanel.tsx
                        the four rooms, Muse's layouts; rooms.ts is their SSE store and fetch helper
    LiveStage.tsx       the live stage: the latest frame, the caption, the cursor marker, expand and take over
    Memory.tsx          the Memory tab's list, Muse's import-memory sheet, the Data controls rows (download, reset)
    AvatarStudio.tsx    the avatar studio: describe, four candidates in a grid, pick, the poses, worn on the account
    Pages.tsx           Settings → Connectors, Permissions, File system access, Dictation
    MuseChats.tsx       the chats column: Search, Main chat, Side chats — pin, rename, archive, make main
    MuseHeader.tsx      the face, name and status chip pinned above the conversation, with Stop
    Invite.tsx          the Invite button at the top right and its dialog (code, link, what it earned)
    ProfileDrawer.tsx   the profile panel: avatar with a pen (change look / edit name), the connection, four tabs
    MuseSettings.tsx    the settings dialog: grouped nav, Advanced, Sign out; the General page; the onboarding coordinator
    Sections.tsx        Settings → Computer use, Help & support, Legal; App behavior and the Developer rows on General
    DevicesPanel.tsx    Settings → Devices and the rail's Devices page: this computer, the others, the switch
    Avatar.tsx          the face in five moods: dragon stills, emoji on a colour, drawn face from the host
    Onboarding.tsx      the first run, full-window: welcome → sign in → code → the permissions carousel → ready
    SignIn.tsx          the two-step form (identifier → code), shared with Settings → nanoMuse Cloud
    CloudSection.tsx    Settings → nanoMuse Cloud (the account, the look, the models, the relay, Open Devices) and Data controls
    Capsule.tsx         the toasts (and the words for a Hands/Reach call, shared with the header)
    bridge.ts, prefs.ts the desktop shell's bridge (window.nanomuseHarness: permissions, links, keep awake, app behavior, bug report, quick chat) and the local preferences (Developer switch, keep awake, approvals)
    icons.tsx, keys.ts, bus.ts, panels.ts
                        inline icons; synthetic key chords for the harness's commands; the settings and profile buses; panel ids
    api.ts, locales.ts  the fetch helper and the en/zh copy
  assets/               dragon-{idle,working,waiting,happy,error}.webp
  build.mjs             esbuild: host ESM (split, so HubError is one class) + client lazy-CJS factory + .d.ts
  tests/                node:test — the relay client against a fake relay, the hub client against a fake socket, the actions on a temp dir and fake platforms, the task runner against a fake session controller
```

Secrets never pass through here: the account key lives in dsh's `.credentials.yaml`
(as `NANOMUSE_CLOUD_TOKEN`), the state file `$DSH_HOME/nanomuse/cloud.json` holds the
account's masked hint, model list and this computer's device id only, `profile.json`
the name and look, all mode 0600. The hub key travels in the `hello` frame, as the
browser's does.

## Licence and names

The bundle and the shell are GPL-3.0-or-later like the rest of nanoMuse. DeepSeek
Harness is MIT and is not vendored in this repository — it is a dependency: installed by
the person for the bundle, installed by npm at build time and carried unmodified, with
every package's licence file, inside nanoMuse Desktop. "DeepSeek Harness" and "DSH" are
DeepSeek's names: we say *built on DeepSeek Harness* (the About says so, the welcome
dialog says so), and never use them in ours — the app is *nanoMuse*, and *harness* in this
directory's name is the word, not their name. DeepSeek Harness is a developer preview (0.2.0-rc); its plugin API
will break, and this bundle pins the version it was written against.
