# Roadmap

nanoMuse is an open-source personal agent for every device you own. This page is a map for people who want to help: what we are working on now, what comes after, and where to put your hands first in each area. No dates — a thing ships when it works on a real phone and a real computer.

The 0.1 versions were a preview; 1.0.0 is the first stable version. We use the phone, the desktop, the web and the relay every day and still know where they are rough; the list below is honest about it. What does not change: one agent rather than a framework, an approval between it and anything irreversible, secrets that never reach the model, memory you can read and edit, any OpenAI-compatible model, free software.

## Now — catching up with Muse

Meta's Muse set the shape of this kind of agent; these are the places where ours is still behind it, and the first task in each.

### Memory

The agent keeps `SOUL.md`, `USER.md`, `MEMORY.md` and `HEARTBEAT.md` and a `remember` tool; consolidation runs, recall is embeddings over the store. What is missing: memory that surfaces on its own at the right moment, forgetting that you can see, and the same memory on every device rather than per device.

- Module: `nanomuse/memory/` (`store.py`, `consolidate.py`, `embeddings.py`); the phone's `io.github.nanomuse.sysfiles`; the desktop's profile panel *Memory*.
- Read: [desktop-muse.md](desktop-muse.md) (the Memory page), [android.md](android.md).
- First task: a test in `tests/test_memory_recall.py` for a fact the agent should bring up unprompted in a later conversation, then make it pass.

### Proactivity

Goals are checked on a schedule, routines run with the app closed, the feed is written each morning. What is missing: the agent noticing things between schedules — a mail that arrived (`nanomuse/triggers/mail.py` is the first trigger), a calendar entry coming up, a device that came online — and deciding whether it is worth a word.

- Module: `nanomuse/goals/`, `nanomuse/triggers/`, `nanomuse/nudges.py`; the phone's `io.github.nanomuse.feed` and `goals`.
- Read: [every-device.md](every-device.md) for how a nudge reaches the device you are holding.
- First task: a second trigger next to `mail.py` (calendar is the obvious one) with the same interface, and the feed entry it produces.

### The conversation

The chat is where everything happens, and it still feels like a chat client. Presence — the face reacting while the agent works, the status line in words — is uneven between the clients; voice is input only since the calls were removed in 0.1.22 ([calls.md](calls.md)), and a voice that answers is an open question; the hands' stage (desktop `harness/dsh-nanomuse/src/client/Trajectory.tsx` and the shell's `glow.html`, Android `HandsStage.kt`) shows the hands and, on the desktop, the agent's words before each step, but not yet across every client in a way a person can follow.

- Module: `harness/dsh-nanomuse/src/client/` (`AvatarChat.tsx`, `Trajectory.tsx`, `Capsule.tsx`), Android `io.github.nanomuse.chat` and `hands`, iOS `NanoMuseChatCards.swift`, `NanoMuseComposer.swift`.
- Read: [desktop-muse.md](desktop-muse.md), [parity.md](parity.md) — the open items between the clients.
- First task: pick one row of `parity.md` that is open on a client you can run, and close it.

### Hands that succeed more often

The screen as a hand works on Android and on the desktop (the desktop operator is a port of UI-TARS-desktop's). It fails on grounding — the model names the wrong element — and on recovery after an unexpected dialog, and we have no fixed set of tasks to measure it against.

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
- **A gadget as a device.** A small board over Bluetooth that speaks a few hub frames — a light to turn on, a sensor to read — as the first step towards the physical world below.

## Later — looking up

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
| 0.1.40 | Clear | The iPhone's input field stays — it sat behind the bottom bar, now a plain row, with a Composer check page in Settings; every chat on a phone belongs to an account and signing out asks about them; every refusal from the relay is one sentence or a card on every client; the operator's Controls, Stats and Site pages on the relay; ScreenCaptureKit on the Mac, no substitute picture; Windows starts again after the update that moved the app; the desktop's lights and the hands' glow move as the phone's do |
| 0.1.41 | Choice | Settings › Models with four rows (Chat, Operating the screen, Making pictures, Making clips) on Android, iPhone, desktop and web; a *Use it for* card after a key is saved; *Automatic* with one order (the chat provider, then nanoMuse Cloud, then the first key that can); no silent fallback, *Use nanoMuse Cloud this time* on a failed turn; the desktop draws through your own key and picks up a new hands model without a restart; `PUT /api/connections/image` and `/video`; the film in the README, the paper on arXiv, the docs site in 简体中文 |
| 1.0.0 | Keel | The first stable version: the phone app for Android and the iPhone, the desktop app for the Mac, Windows and Linux, the web console and the relay, one account across them; nanoMuse Cloud can be switched off as a model source and a device with a key of its own works signed out; the main chat follows the chat model you pick; folded, searchable model pickers; a thinking level for your own key on the desktop; *I already starred*; the desktop waits for a slow Windows start; the reply follows the language of the app; `auto` asks before a tainted send and on a warning; the hub and the relay hardened; no dashes in anything a person reads |
| 1.0.1 | Ballast | The phone app has its own URL scheme, so it no longer collides with OpenMinis; a content check saying no is one sentence on every client and counted apart on the relay's Health page; a chat the desktop received from another device scrolls to its start, the glow stays up for a whole hands run and the face moves on Windows; one turn on nanoMuse Cloud on request from the web; the TestFlight beta passed Apple's review |
