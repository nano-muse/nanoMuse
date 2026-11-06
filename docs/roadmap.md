# Roadmap

A personal agent should not live only in someone else's cloud, so nanoMuse is the open-source, low-cost alternative: on your own devices, with a model you choose and a relay you can host yourself. We want to build it with developers and users everywhere, so that each person truly owns a personal agent. Open an [issue](https://github.com/nano-muse/nanoMuse/issues/new/choose) or send a [pull request](../CONTRIBUTING.md); either one helps nanoMuse get better.

This page is a map for people who want to help: what we are working on now, what comes after, and where to put your hands first in each area. No dates: a thing ships when it works on a real phone and a real computer.

The 0.1 versions were a preview; 1.0.0 is the first stable version. We use the phone, the desktop, the web and the relay every day and still know where they are rough; the list below is honest about it. What does not change: one agent rather than a framework, an approval between it and anything irreversible, secrets that never reach the model, memory you can read and edit, any OpenAI-compatible model, free software.

## Now: catching up with Muse

Meta's Muse set the shape of this kind of agent; these are the places where ours is still behind it, and the first task in each.

### Memory

The agent keeps `SOUL.md`, `USER.md`, `MEMORY.md` and `HEARTBEAT.md` and a `remember` tool; consolidation runs, recall is embeddings over the store. What is missing: memory that surfaces on its own at the right moment, forgetting that you can see, and the same memory on every device rather than per device.

- Module: `nanomuse/memory/` (`store.py`, `consolidate.py`, `embeddings.py`); the phone's `io.github.nanomuse.sysfiles`; the desktop's profile panel *Memory*.
- Read: [desktop-muse.md](desktop-muse.md) (the Memory page), [android.md](android.md).
- Done first task: `tests/test_memory_recall.py` now covers a fact stored in one conversation that the agent brings up unprompted on the opening turn of the next (`MEMORY_OPENING_NOTE` + most-recent slot reservation in `MemoryStore.relevant` / `relevant_async`). Next task: forgetting that you can see in the chat and syncing the same memory store across devices.

### Proactivity

Goals are checked on a schedule, routines run with the app closed, the feed is written each morning. Four triggers exist (`nanomuse/triggers/`: a mail that arrived, a calendar entry coming up, a webhook, a device of the account coming online). What is missing: the agent noticing other things between schedules and deciding whether what it noticed is worth a word.

- Module: `nanomuse/goals/`, `nanomuse/triggers/`, `nanomuse/nudges.py`; the phone's `io.github.nanomuse.feed` and `goals`.
- Read: [every-device.md](every-device.md) for how a nudge reaches the device you are holding.
- Done first task: the fourth trigger kind, `device`, next to the three in `nanomuse/triggers/store.py` (a device of the account coming online, from the hub's `devices` frame, with the same interface): `arrivals()` seeds the first frame and fires only on a real offline to online transition, `MuseService.device_came_online` runs each matching trigger with the `Device online: …` feed entry, and the kind is gated on the hub (`tests/test_triggers.py`, `tests/test_server.py`). Next task: the agent noticing other things between schedules, and deciding whether what it noticed is worth a word.

### The conversation

The chat is where everything happens, and it still feels like a chat client. Presence (the face reacting while the agent works, the status line in words) is uneven between the clients; voice is input only since the calls were removed in 0.1.22 ([calls.md](calls.md)), and a voice that answers is an open question; the hands' stage (desktop `harness/dsh-nanomuse/src/client/Trajectory.tsx` and the shell's `glow.html`, Android `HandsStage.kt`) shows the hands and, on the desktop, the agent's words before each step, but not yet across every client in a way a person can follow.

- Module: `harness/dsh-nanomuse/src/client/` (`AvatarChat.tsx`, `Trajectory.tsx`, `Capsule.tsx`), Android `io.github.nanomuse.chat` and `hands`, iOS `NanoMuseChatCards.swift`, `NanoMuseComposer.swift`.
- Read: [desktop-muse.md](desktop-muse.md), [parity.md](parity.md), the open items between the clients.
- First task: pick one row of `parity.md` that is open on a client you can run, and close it.

### Hands that succeed more often

The screen as a hand works on Android and on the desktop (the desktop operator is a port of UI-TARS-desktop's). It fails on grounding (the model names the wrong element) and on recovery after an unexpected dialog. [GUI regression](gui-regression.md) now provides fixed simulated tasks for runtime regression and opt-in model comparisons; real-device grounding and recovery still need recorded failures.

- Module: `nanomuse/computer/` (`operator.py`, `coords.py`, `screen.py`), `nanomuse/phone/` (`operator.py`, `trace.py`), `harness/desktop/src/operator.ts`, Android `io.github.nanomuse.hands`.
- Read: [gui.md](gui.md) for the operator's contract, [troubleshooting.md](troubleshooting.md).
- First task: record one failed run with `nanomuse/phone/trace.py`, write down the step where it went wrong, and open an issue with the trace. Ten of those become the evaluation set.

### Self-hosting in one command

`scripts/self-host.sh` brings up the relay with TLS; the web runtime has its own `docker-compose.yml`. What is missing: one command for both, updates that keep the data, and a page that says how much it costs to run for a family.

- Module: `cloud/` (`docker-compose.yml`, `docker-compose.local.yml`, `Dockerfile`), `scripts/self-host.sh`, the root `docker-compose.yml`.
- Read: [self-hosting.md](self-hosting.md), [cloud.md](cloud.md), [deployment.md](deployment.md).
- First task: run `bash scripts/self-host.sh --local` on a clean machine and report every place the instructions were wrong.

### Internationalisation

The apps are in English and Chinese; the Android app carries fifteen more locales from upstream, and our strings in them (`nm_strings.xml`) have had far less attention than the English and Chinese. The READMEs are in ten languages.

- Module: `android/src/android/app/src/main/res/values-*/nm_strings.xml`, `android/src/ios/Localizable.xcstrings`, `harness/dsh-nanomuse/src/client/locales.ts`, the relay's console under `cloud/nanomuse_cloud/`.
- Read: the *Every string in every language* section of [CONTRIBUTING.md](../CONTRIBUTING.md).
- First task: open the app in a language you speak, note every string that reads wrong, and fix the file for that locale.

## Next

- **An open evaluation suite.** The hands' failures above, turned into a fixed set of phone and computer tasks anyone can run, with the simulated phone from the showcase ([showcase.md](showcase.md), `demo/mobilegym/`) as the harness. A number per release, not an impression.
- **A hands model of our own, on open data.** The traces people choose to contribute (*Data controls*, [privacy.md](privacy.md)) are the training set; the evaluation suite is the yardstick. Small, open weights, good at Chinese apps.
- **Provenance on every line of memory.** Each fact the agent keeps should say which model wrote it, when, and how sure it was, so that a wrong memory can be traced and a doubtful one shown as doubtful.
- **Shareable skills.** A skill is a folder today (`nanomuse/skills/`); it should be something you can hand to a friend, install from a link, and trust because its risk is declared.
- **More devices as hands.** A browser extension so the agent can act in your signed-in browser; a watch for the shortest front door; the car and the home as places the agent can see and act. Each is a new client of the hub ([hub.md](hub.md)), not a new agent.
- **A gadget as a device.** A small board over Bluetooth that speaks a few hub frames (a light to turn on, a sensor to read) as the first step towards the physical world below.

## Later: looking up

- **The physical world.** The hub frames already carry *look*, *act* and *ask*; a robot arm or a camera is one more device. We do not know yet what a personal agent should be allowed to do with a body.
- **An agent that lasts years.** Memory that grows for a decade without becoming noise; a face and a name that stay yours through model changes; an export you could move to another runtime.
- **Legible personal data.** Everything the agent knows about you readable as plain files, understood by other programs too, so the agent is a view onto your data rather than the owner of it.
- **Evaluating personal agents.** The suites above score tasks; a personal agent is also judged by whether it knows you and whether it asked at the right moments. We do not have a way to measure that yet.

## Where the code is

Two trees. **`android/`** is a modified copy of OpenMinis 1.13 pulled in with `git subtree`; our Android code is in `io.github.nanomuse.*`, our iOS code in `android/src/ios/NanoMuse/` ([CONTRIBUTING.md](../CONTRIBUTING.md) says how to work there). **`nanomuse/`, `harness/`, `cloud/`, `web/`** are ours end to end: the Python runtime that gives the desktop and the web their hands, the desktop app as a DeepSeek Harness plugin, the relay, the web console. [architecture.md](architecture.md) draws the whole thing; [AGENTS.md](../AGENTS.md) is the one-screen version with the check commands.

## Past releases

Every version is a GitHub release built from its tag, titled `nanoMuse <version> · <Codename>`; the notes for each are in [releases/](releases/) and the line-by-line record is the [CHANGELOG](../CHANGELOG.md).

| Version | Codename | In one line |
|---|---|---|
| 0.1.1 – 0.1.11 | Foundation … Hatch | OpenMinis as nanoMuse: the name and face, one home conversation, approvals with scope, memory files, the feed, the avatar studio, the dragon |
| 0.1.12 Hands · 0.1.15 Stage | | The phone's screen as a hand, and the stage that shows it working |
| 0.1.13 Reach | | The phone drives your computer (replaced by the hub in 0.1.24) |
| 0.1.18 Open | | nanoMuse Cloud: start without a key, sign-up open to everyone (carries 0.1.17 Doorstep, drafted and never released) |
| 0.1.19 Ensemble | | Every device: the desktop app, the runtime on the hub, nanoMuse Web |
| 0.1.20 – 0.1.25 | Presence … Mirror | The account first, a voice, invitations, phone-number sign-in, one look on every device |
| 0.1.26 – 0.1.30 | Window … Rooms | The showcase; the desktop moves to DeepSeek Harness and takes Muse's shape and rooms |
| 0.1.31 Locks | | The audit's open points closed: no token in any URL, remote control by consent |
| 0.1.32 – 0.1.35 | Union … Accord | The iPhone and the desktop catch up with the phone, screen for screen |
| 0.1.36 – 0.1.38 | Thread · Weave · Loom | One conversation across the devices, the main one first; the desktop's hands ported from UI-TARS-desktop, with a helper app for the Mac's permissions; a docs site and self-hosting in one command |
| 0.1.39 | Keys | One provider catalogue with what each key covers, on every client and the relay; a ChatGPT plan as a sign-in; each account sees its own conversations on a shared device; the hands' clicks land on Ubuntu, the Mac helper keeps its grants, the iPhone no longer crashes after onboarding; every language complete; the Terminal edition dropped |
| 0.1.40 | Clear | The iPhone's input field stays: it sat behind the bottom bar, now a plain row, with a Composer check page in Settings; every chat on a phone belongs to an account and signing out asks about them; every refusal from the relay is one sentence or a card on every client; the operator's Controls, Stats and Site pages on the relay; ScreenCaptureKit on the Mac, no substitute picture; Windows starts again after the update that moved the app; the desktop's lights and the hands' glow move as the phone's do |
| 0.1.41 | Choice | Settings › Models with four rows (Chat, Operating the screen, Making pictures, Making clips) on Android, iPhone, desktop and web; a *Use it for* card after a key is saved; *Automatic* with one order (the chat provider, then nanoMuse Cloud, then the first key that can); no silent fallback, *Use nanoMuse Cloud this time* on a failed turn; the desktop draws through your own key and picks up a new hands model without a restart; `PUT /api/connections/image` and `/video`; the film in the README, the paper on arXiv, the docs site in 简体中文 |
| 1.0.0 | Keel | The first stable version: the phone app for Android and the iPhone, the desktop app for the Mac, Windows and Linux, the web console and the relay, one account across them; nanoMuse Cloud can be switched off as a model source and a device with a key of its own works signed out; the main chat follows the chat model you pick; folded, searchable model pickers; a thinking level for your own key on the desktop; *I already starred*; the desktop waits for a slow Windows start; the reply follows the language of the app; `auto` asks before a tainted send and on a warning; the hub and the relay hardened; no dashes in anything a person reads |
| 1.0.1 | Ballast | The phone app has its own URL scheme, so it no longer collides with OpenMinis; a content check saying no is one sentence on every client and counted apart on the relay's Health page; a chat the desktop received from another device scrolls to its start, the glow stays up for a whole hands run and the face moves on Windows; one turn on nanoMuse Cloud on request from the web; the TestFlight beta passed Apple's review |
| 1.0.2 | Trim | A pass over every part of the project: the Sentinel's taint rule holds for `shell` and `send_email` in auto mode; the Android app starts beside OpenMinis; the desktop's permission card comes up for the hands' refusals, a picture on Linux no longer kills the harness and the Windows caption buttons cover nothing; the memory tidy-up refuses what it cannot judge; `doctor` names a config key nothing reads; clearer errors in the web console and the CLI; the iPhone's pages in all nine languages; the docs without em dashes |
| 1.0.3 | Helm | The chat reads the same on every device: a floating frosted-glass bottom bar as wide as the composer, black and white pills on the theme's canvas and a scrim for a header, from @Ichiro786's Android redesign to the iPhone, the web console and the desktop; a clip of your own as the face on Android, the iPhone and the desktop; several custom OpenAI-compatible endpoints at once on the desktop and in the web console; ten Android reports from one afternoon fixed, an own Anthropic key sending again among them; a voice prompt from the iPhone's Action Button; OpenCode Go on every client; the relay's image runs as an unprivileged user |
| 1.0.4 | Compass | A health check of the whole project in the week after 1.0.3: the relay pays the invite bonus at the friend's first request, shows who invited whom and records every operator action; the runtime keeps an MCP server's secrets in the vault and asks before a routine, a trigger or a goal is set up; the web console reads to a screen reader and takes the keyboard in its menus; the desktop plays an HEVC clip where it can and lists DeepSeek Harness beside Cursor, Codex and Claude Code; the Android phone keeps the proxy password encrypted and follows a picked model group; the iPad's chat is one column under a glass pill bar, and a step another device's Muse asks about is answered on the phone; You.com searches without a key |
| 1.0.5 | Lookout | A second check the day after Compass: the operator's console searches people, statements and events; a disabled account cannot be probed through the sign-in routes; the runtime lists DeepSeek Harness and keeps one endpoint per address; on the desktop eight dead buttons post again, a quit protects the work in progress, a dead hub link is noticed within a minute and the Windows release carries its update feed; the Android approval card fits the screen and the ChatGPT sign-in has a way through a proxy; the iPhone scrolls under the header, hears Siri's phrases in nine languages and shows an emoji face set elsewhere; the daily feed is written quietly on the phones and the desktop; the docs describe nanoMuse in its own words |
| 1.0.6 | Beacon | A third check nine days after Lookout: nanoMuse Cloud serves one multimodal model, Qwen3.6-27B, for chat and the screen, and no longer pays for pictures or clips, which come from a provider of your own on every client; the relay answers a wrong password and an unknown account alike, decides its limits in one transaction and ties a Hub credential to one device; the runtime finishes the scheduled work a restart interrupted, refuses private addresses in the browser and makes a forgotten memory visible and undoable; the desktop asks before a restart, exports your data past a link, wears a face drawn signed out and searches its settings; the phone reads your liked Feed posts, keeps a remembered approval to its own step and lists Wan 2.7; the iPhone keeps hidden steps hidden and shows a remote task's progress; the READMEs' contributors are current |
| 1.0.7 | Logbook | A fourth look two days after Beacon, around the record: nanoMuse Cloud keeps every chat turn it answers in full, screenshots as files, and the apps add the turns they ran on a key of their own, so every device shares one history; the face's clips travel with the face; each device says which provider and model answer it; the models answer the nanoMuse apps only; the operator's console is rebuilt with a live view of the model endpoint and reads off the requests' path; the runtime names itself on every call, shows a thinking model's reasoning live and searches with Parallel; the desktop checks who stops or approves a remote task; the phone runs a scheduled task several times a day and backs up without files, from the shell too; the iPhone keeps two accounts apart; the privacy policy says what the hub keeps about each device |
| 1.0.8 | Crew | A fifth look four days after Logbook, around the devices keeping each other posted: a scheduled task on the computer asks on your phone, every device reads the step another is on and says when it waits for you, the wait before a first token is spoken of with the place in the queue, and the record says who started each call and what you thought of the reply; the relay keeps a slow turn connected, counts the record by questions and reads it question by question; the runtime keeps a private file private on Windows, reads and writes files as Windows wrote them and fetches compressed pages again; the desktop's Library takes documents of your own; the phone no longer crashes when you stop talking and sends smaller prompts; the iPhone no longer stops your music and reads whole in Traditional Chinese; Opper, AtmoRouter, API Route and Keenable join the catalogues |
| 1.0.9 | Tiller | A fix release the same day as Crew: the desktop starts again when you are signed in ([#703](https://github.com/nano-muse/nanoMuse/pull/703), for [#701](https://github.com/nano-muse/nanoMuse/issues/701)), the relay's console loads on a large record ([#708](https://github.com/nano-muse/nanoMuse/pull/708)), and the runtime takes a budget for a task and recalls from the whole memory store ([#697](https://github.com/nano-muse/nanoMuse/pull/697), [#696](https://github.com/nano-muse/nanoMuse/pull/696)). |
