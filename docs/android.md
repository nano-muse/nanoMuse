# The Android app

`android/` is nanoMuse for the phone: [OpenMinis](https://github.com/OpenMinis/OpenMinis)
1.13 (GPL-3.0) — a native app whose agent runs **on the phone**, with a Linux shell, a
browser, MCP servers, skills and scheduled tasks inside the APK — with nanoMuse's own
identity, design and features on top. Everything of nanoMuse's lives in
`io.github.nanomuse.*`; edits inside OpenMinis files are marked `// nanoMuse:`. The
application id is `io.github.nanomuse.app` and the URL scheme the system knows the app by is
`nanomuse://`, so a phone that also has OpenMinis installed never has two apps claiming one
scheme; inside the app, links stay `minis://…` (upstream's vocabulary, shared with the sandbox,
the system prompt and the model), a `nanomuse://` link arriving from the system is read as its
`minis://` form, and every link of the app's own that the app opens itself is addressed to
`MainActivity` by name, never resolved by the system
(`io.github.nanomuse.deeplink.OwnScheme`). The sandbox's offload socket, the abstract socket
proot talks to the app through, is the app's own too: `io.github.nanomuse.app.native-offload`
rather than upstream's `native-offload`, since abstract sockets are one namespace for every
app on the device and whichever app bound the shared name second would die at start; when
even that name is still held by a previous process of ours, the server binds a per-process
name and tells proot that one (`io.github.nanomuse.sandbox.OffloadSocketName`). The
history of this choice is in [roadmap.md](roadmap.md); what came before it (a WebView
around a Python server, two APK flavours) is kept as a design record in
[archive/android-python-line.md](archive/android-python-line.md) and is not what you
download today.

One APK, one architecture: `nanoMuse-<version>-arm64.apk` (arm64-v8a, Android 8.0 / API 26
or newer, `targetSdk` 35). Every release is signed with the same key, so a newer APK
installs over the old one and keeps its data. No Play Store listing: *Settings → Version* shows
the installed build next to the newest release (`nanomuse.cn/dl/index.json` first, this
repository's GitHub Releases second — *Latest 0.1.x, you have it* / *0.1.x is out, tap to
update*) and offers the download.

## Install

1. Download `nanoMuse-<version>-arm64.apk` from the
   [latest release](https://github.com/nano-muse/nanoMuse/releases/latest). Verify with
   `sha256sum -c nanoMuse-<version>-arm64.apk.sha256` if you like.
2. Open it. Android asks once to allow installs from your browser or file manager.
3. **Sign in.** The first screen is the account: a phone number or an e-mail address,
   a code — or a password once you have set one. It is what lets your devices work as one
   ([hub.md](hub.md)) and brings a model to start with ([cloud.md](cloud.md): a free pool per
   account — ¥10 at the time of writing — and more for each friend invited, and for them;
   the app prints the relay's current figures; then [your own key](own-key.md)). Then choose which model answers: the account's
   own, or a key of your own (any OpenAI-compatible endpoint, or the OAuth sign-ins the
   app ships with). Four models are set, not one, and they live on one page, **Settings →
   Models** (the card at the top of Settings opens it): **Chat**, the model that talks with
   you (the account's menu opens on `deepseek-v4.1-flash`); **Operating the screen**, the one
   that looks at the screen (`qwen3.8-27b`, the account's or the same model under your own
   key); **Making pictures** and **Making clips**. Each row shows `<provider> · <model>` and
   opens a picker: the *nanoMuse Cloud* group first when signed in, the recommended model
   first and marked, then one group per provider of your own with only the models that fit
   the row. A group shows eight models until you tap *Show N more* (the catalogue's default
   for the row first, then the one in use, then the rest as the provider lists them); past
   eight models in all, a *Search models* field above the groups filters every group live by
   id or name, and *No model matches* says when nothing does; the search and the opened
   groups survive a rotation and the trip through *Add a provider*. A chat pick there, or in the
   chat's own `•••` menu, is the default for new chats and moves the main chat
   (*Applies to the main chat and to new chats; a side chat keeps its model.*); a side
   chat already open keeps its model. The other three pickers
   open with *Automatic* (*Currently nanoMuse Cloud · qwen3.8-27b*), which forgets a choice
   made there and lets the row follow the order below again. Signed in, the page opens with
   one switch, *Use nanoMuse Cloud models*: off, the account leaves every picker and the
   automatic order, no side call (titles, memory, pictures, clips) runs on it, and only the
   *Use nanoMuse Cloud this time* button on a refused turn does; the sign-in stays for sync and
   your devices. If the chat model is still the account's at that moment, the Chat row moves
   to your first own chat model (the catalogue's default for that provider), as every client
   does, and the page says *Applies to the main chat and to new chats*. Switching off is
   refused with one sentence while the chat model is still the account's and you have no
   chat model of your own, since nothing else could answer: the switch stays on and *Add a
   provider of your own first; with nanoMuse Cloud off, nothing else could answer.* appears
   under it. The Cloud provider's own page (Settings → *Manage Providers*) follows the same
   rule; a provider of your own switched off there while the chat ran on it hands the chat
   to the next source, and when none is left a send says *No model can answer right now.
   Choose one under Settings › Models.* A phone with a key of
   its own works signed out: the welcome page offers *Use your own API key instead*. Running
   everything yourself with no account at all is the runtime's `cloud.required = false`.
4. Optional: the two permissions that let the agent use your phone's apps (skippable and
   revocable). *Settings → Hands* keeps its row for the screen model, which opens the same
   picker; *More picture and clip options* at the foot of the Models page is the old *Image &
   video models* page (typing a model name, what stops without each model, re-checking which
   video models a key can use), also at `minis://settings/media`.

**Use it for.** When a provider of your own is saved, a new one or a key added to one that
had none, a card asks what this key should handle: one switch per capability the catalogue
gives the vendor (chat, operating the screen, making pictures, making clips), all on. *Use
it* switches the ticked rows to this provider, each on the catalogue's default for that job
(`defaults.chat` and friends in `providers.json`), or on the first model of its list that
fits when the default is not there; *Not now* changes nothing, and so does an unticked switch.
Signed in, the body says nanoMuse Cloud keeps the rest. The page is the place to change it later.

**When you have not chosen.** Chat is the relay's recommended model when signed in, else the
first provider of your own. The screen, pictures and clips follow the chat provider when it is
a provider of your own with that capability (its catalogue default); else the relay's model
when signed in; else the first provider of your own that can. A choice always wins, and
nanoMuse Cloud never steps in front of a provider you chose. When a model of your own fails,
nothing falls back on its own: the error card gets *Use nanoMuse Cloud this time* (signed in
only), which runs that one turn on the relay's chat model and changes no row.

**Your own relay.** The sign-in screen talks to nanoMuse Cloud unless you tell it
otherwise: *Use a different server* under the sign-in form takes the address of a relay
you run yourself ([cloud.md](cloud.md), `cloud/docker-compose.yml`), *Check* asks its
`/healthz` and shows the version it answers with, *Use this server* keeps the address
across launches. `https://` is required for anything outside your own network; plain
`http://` is accepted for an address on your own network, judged by the same rule as a
model server's (below: the private ranges as parsed addresses, `localhost`, a name without
a dot, a `.local`, `.lan`, `.home`, `.internal`, `.home.arpa` or `.ts.net` name). Settings → Account shows *Server: `<host>`* with *Change*, which signs the phone out first — the key it holds belongs to the
server that issued it. Everything the app does with the account (sign-in, the hub, sync,
usage, the model menu) goes to that address.

## What the phone does

| | |
| --- | --- |
| **The agent, on the phone** | A sandboxed Alpine Linux, a real shell, files, a browser, MCP servers, skills in the Agent Skills format, memory, scheduled tasks; approvals before deleting, sending or paying. The model is the account's or your own; nothing you say passes through the project's relay when you use your own key. |
| **Hands** (`hands/`) | With *Hands* on and the accessibility service enabled, the agent looks at the phone's screen and taps, types and swipes in its apps — the last rung after APIs, fetches and the browser. A stage over the app shows where it is about to tap and a capsule with the step and **Stop** — a glow breathing along the screen's edges (blue working, amber waiting; 2.4 s in, 2.4 s out, like every working light on every client since round 9: nothing runs round the rim or slides down the screen, and the capsule's ring and bars breathe at the same pace; everything holds still under the system's reduce-motion setting); when a tap would send, post or delete, the capsule itself asks — **Allow** / **Deny**, the same request the chat card and the notification show — so you are not pulled back into nanoMuse (money is confirmed with the screen lock in the chat card; the capsule offers *Open* for that one); the capsule only ever answers its own request, never a shell or browser card of another conversation, and **Stop** while a card is waiting denies it and ends the run at once. Passwords and codes are always yours to type. The same action a third time on a screen that did not change gets a line in the history so the model changes tack, and a sixth ends the run as *infeasible* with the action named (`HandsLoopWatch`, the floor the runtime has too), instead of one model call per step until the thirty-minute limit. Every step's screenshot is written next to the run's trace under the session's `attachments/hands/<run>/`; the ten newest runs keep all of theirs, an older run keeps its trace and the last screen (the one the chat shows), and past 200 runs the oldest is removed (`HandsTraces`). [gui.md](gui.md) is the design record; the app's own hands are in `io.github.nanomuse.hands`. |
| **Reach** (`reach/`) | Your computers, from the phone: "say it on the phone, it gets done there" — a shell command, a file, the computer's screen, or a whole task for the nanoMuse running there. The way in is the hub (next row): install nanoMuse Desktop on the computer and sign in with the same account, and it is under *Account → Devices* within seconds, on any network — the only way since 0.1.24 (the local-network host script is gone). *Settings → Computers* lists the account's computers and says which account the phone uses, since a missing computer has nearly always signed in with another one. Approvals are decided on the phone before anything is sent. [every-device.md](every-device.md). |
| **The hub** (`hub/`) | Every signed-in device of the account meets on the relay's hub: the phone sees your computers, asks them to do things, gets their approvals as cards, and can be asked by them. A foreground service keeps it reachable in the background (Android 13+ asks for the notification permission for that). [hub.md](hub.md). |
| **Coding agents** (`ui/coding/`) | The Cursor, Codex and Claude Code sessions on your computers, seen and steered from the phone. [coding-agents.md](coding-agents.md). |
| **Account** (`ui/cloud/`) | Who is signed in, the password, every device holding a key, usage by kind and by model, the ways out. When the free pool is spent or past 80 %, the account page and the refused turn show the ways on: your own key — the providers of the catalogue, the region's first (Alibaba Cloud Bailian for people in mainland China: the UI in simplified Chinese, a phone-number sign-in, or the relay saying so; OpenRouter and OpenAI everywhere else), each saying what it covers — a subscription you already pay for (ChatGPT, Claude, Kimi, OpenRouter sign in instead of a key), and an invitation. See [Your own key](#your-own-key) below. A phone shows and syncs the signed-in account's conversations only — since 0.1.40 every chat has an owner, synced or not, and a sign-out asks *Keep this account's chats on this device* (off by default: the account's chats, memory, feed, goals, routines and face leave the phone; on: put aside until it returns); deleting the account removes all of it; a key the relay refuses (`401 bad_key`) puts the account's data aside as *Keep* would and the sign-in page says so until the next sign-in — only `401 account_deleted` removes it; signed out, only the chats made while signed out show ([sync.md](sync.md)). |
| **The browser handed over** (`browser/`) | A page that needs you — a login, a verification code, a payment, a CAPTCHA — is handed over instead of described: `browser_use`'s `hand_over` action opens the agent's own tab (same WebView, same session) in the browser sheet with the agent's hold released, a **Your turn** card above the composer says what the page asks of you with *Open the page* and *Done, continue*, the sheet carries the same line and button, and the tool call waits for *Done* (fifteen minutes at most) before the agent goes on from the page as it is. `io.github.nanomuse.browser.BrowserHandOver`. |
| **Connectors** (`connectors/`, `ui/connectors/`) | The services the agent can be let into — the desktop's catalogue of 75 remote MCP servers (Notion, Linear, GitHub, GitLab, Slack, Stripe, Miro, …), shipped as `assets/nanomuse/connectors.json`. The only Settings row for all of this is *Connectors*; the upstream MCP editor (by address, by command, imported JSON) is *Your own servers* at the end of the page. Open servers add with a tap; a key service takes the key; an OAuth service runs the MCP authorization flow (discovery, dynamic client registration, PKCE in a Custom Tab) and the token goes into the entry's `Authorization` header for the in-guest MCP client, refreshed at app start; a service whose authorization server registers no clients (`clientIdRequired` — GitHub, Slack, Discord, HubSpot, Render, Bitrise, PagerDuty, Box) asks for an OAuth client id and secret made at the vendor's developer page with the app's callback address, which the sheet shows and copies. A connected service is an MCP server entry under the same id — *Your own servers* manages it too. What is connected is shared with the account's other devices through the relay profile — the entries (id, label, address, kind of auth, which device, when), never a token — so the page also lists *On your other devices*: a service connected on the desktop shows as *Connected on <device> — sign in here to use it on this phone*, one tap into the same sheet. |
| **The chat, plain** | While the agent works, the line under its avatar names the step under way — *nanoMuse is using Shell*, *Writing the reply*, *On it: book the table* — never a state of mind. The tool pills, the Computer sheet and the floating step bar are **on by default** since 0.1.37; *Settings → Appearance → Show the agent's steps* turns them off. With them on, a finished step reads *nanoMuse used Shell · Done*, and its sheet closes on ×, swipe or Back. |

The web console of the same account is at the relay (`/app`), the desktop app in
[desktop.md](desktop.md); the phone, the desktop and the web share the design language
described in [brand.md](brand.md).

## Your own key

The vendors the app knows are one file, `assets/nanomuse/providers.json` — a copy of the
runtime's `nanomuse/llm/providers.json` written by `node scripts/providers-json.mjs`, the same
catalogue every client reads ([own-key.md](own-key.md)). Each entry says where the endpoint is,
where a key is made, which sign-ins it has, where it signs people up (`cn`, `global`) and what
its models can do: `chat`, `vision` (the hands' screen), `image` (pictures), `video` (clips).

**The card.** When the allowance is spent or nearly, *Use your own model key* lists the
catalogue, the region's vendors first — Alibaba Cloud Bailian on the mainland (one key covers
all four; it signs up accounts from mainland China only), OpenRouter and OpenAI elsewhere —
then the rest, three at a time behind *More providers*. Every row says what the vendor covers
(*chat · screen · pictures · clips*); *Add* opens the provider form pre-filled with its name,
endpoint and `/v1` setting (`minis://settings/providers/add?preset=<id>`), *Get a key* opens
the vendor's key page. No vendor is recommended. *A subscription you already pay for* lists
the vendors whose plan signs in instead of a key — ChatGPT (OpenAI's Codex OAuth), Claude,
Kimi (a device code) and OpenRouter; *Sign in* opens the same form on the sign-in button
(`?preset=<id>:oauth`), which runs OpenMinis' own `OpenAIOAuthManager`, `ClaudeOAuthManager`,
`KimiOAuthManager` or `OpenRouterOAuthManager`. The ChatGPT row carries the line that
OpenAI's terms cover a ChatGPT plan inside OpenAI's own Codex, that other apps have had this
access cut off before (OpenCode, January 2026), and that an API key works if it stops.
Anthropic and Gemini open on OpenMinis' own provider types for them; everything else on the
OpenAI-compatible form.

**Where the list comes from.** The relay's `/v1/me` carries `spend.guidance` (relay 0.21,
[cloud.md](cloud.md)): the providers for the person's region in the relay's order, each with
what it covers, the plans one can sign in with and which clients they are for, the local
servers, the docs link and the honest line about the ChatGPT sign-in. `cloud/Guidance.kt`
parses it, `Ways.resolve` prefers it, and the card and Settings → nanoMuse Cloud read the
bundled catalogue only when the relay sent none (an older relay) — so a vendor added on the
relay shows before the app is updated, and a provider the relay no longer lists is gone the same
day. A `429 allowance_exhausted` carries the same block beside the figures.

**What each covers.** The capabilities decide what the app offers (`cloud/Capabilities.kt`):
pictures (Settings → Models → Making pictures, the avatar studio, `nanomuse-media image`) pick a
provider only among those whose vendor has `image`; clips among those with `video` that the
app can drive (Bailian's video API); the screen's model and its picker list only models of
vendors with `vision`. A ChatGPT plan signed in through Codex is chat and vision — the Codex
backend has no image or video endpoints — so it is never offered for pictures. A vendor the
catalogue does not know (a gateway, a relay of your own, nanoMuse Cloud) is taken at its
models' word, as before. When no configured provider has a capability, the page says so in one
sentence — *Pictures need a provider with image models: Bailian, OpenAI, Gemini or
OpenRouter.* — instead of failing.

**When the provider cannot be reached** (`net/ProviderReach.kt`, `ui/chat/ProviderReachCard.kt`).
A failed turn whose error is the transport's — OkHttp's *failed to connect to chatgpt.com/… (port
443)*, *Unable to resolve host*, a TLS or timeout line — or OpenAI's *region not supported* is
shown as a card instead of the red banner: what happened, what helps (a VPN on this phone, the
proxy under *Settings → Network*, another provider with a key of your own), *Try again*, and the
raw line behind *Details*. The 401/403/429 whose bodies upstream's `mapHttpError` drops are
kept for a few seconds by `ReachSignal` (one `// nanoMuse:` spot in `OpenAIProvider`) and
written into the message as a canonical `nm_reach:` line, so an expired ChatGPT sign-in reads
*Sign in again* and a spent plan window reads *The ChatGPT plan has nothing left for now* with
OpenAI's own sentence and the reset time; a plain *Invalid API key* on a key provider stays
upstream's. The relay's `daily_cap` 429 is now read like `allowance_exhausted` and the card
says today's share is spent and comes back with the day. The allowance card also lists a model
of your own (Ollama, LM Studio, vLLM on a computer you own) and, for a signed-in account, your
computer — *@* and its name in the chat runs the turn there.

**When the relay refuses a turn** (`cloud/RelayRefusal.kt`, `ui/chat/RelayRefusalCard.kt`).
Every refusal nanoMuse Cloud sends is one plain sentence in the phone's language and the button
that fits — never a status code, the relay's JSON or upstream's *Rate limited*. The reply is
read where the body is still whole (`AllowanceSignal.noteHttpError`, through the same
`// nanoMuse:` spot in `OpenAIProvider`), stored in the message as a canonical `nm_relay:` line
and drawn by the card: `413 too_large` (also a proxy's plain 413 from the relay's host) → *That
message is too large for the model. Shorten it, leave out some attachments, or start a new
chat.* with *New chat*; `400 content_rejected` (the provider's content check declined the
words; also a provider's own `DataInspectionFailed` on a key of one's own) → *The model
provider's content check declined this request. Try different words, or start a new chat if it
keeps happening: the words it objects to can be earlier in the conversation.* with *New chat*
and *Try again*, and the compaction's split-retry (`ChatViewModel.shouldSplitOnError`) leaves it
alone, since the same words come back refused however small the request; `401 bad_key` /
`account_deleted` → *Sign in*; `403 not_invited` /
`account_disabled` / `signup_closed` → *Open Settings*; `429 too_many_in_flight` / `locked` /
`rate_limited` and `provider_busy` (with the wait from `retry_after`) → *Try again*; `404
model_not_offered` → *Open Settings*; `503 service_paused`, `sync_paused`, `hub_paused` and any
5xx or empty answer → *Try again*. `429 allowance_exhausted` and `daily_cap` keep the allowance
card; with `paused: true` (relay 0.22) its lead says the allowance is *paused on this relay for
now — not used up* and that what is left stays as it is. The sentences are
`NanoMuseCloud.describe`'s, the same ones the sign-in and account pages use, in all 17 locales
(`nm_cloud_err_*`). Unit tests: `RelayRefusalTest`, `GuidanceTest`.

**Settings → Network** (`net/OwnProviderProxy.kt`, `ui/net/NetworkScreen.kt`,
`minis://settings/network`). The HTTP proxy for own providers: host, port, optional user name
and password, off by default, in `SharedPreferences` on this phone only. It is installed in
`MinisApp.onCreate` as the process's default `ProxySelector`, so every OkHttp client asks it per
request; it answers the proxy for the catalogue's hosts, `chatgpt.com`, `auth.openai.com` and
the custom base URLs of the provider instances (never the relay's, never a LAN address), and the
system's answer for every other host — the hub, the relay, the sandbox mirrors are untouched.
Provider clients carry `OwnProviderProxy.authenticator` for a proxy that asks for a password.
*Test* fetches `https://chatgpt.com/` through the proxy as entered and reports the status and the
milliseconds. Unit tests: `ProviderReachTest`, `OwnProviderProxyTest`.

## Privacy and permissions

The relay keeps an account id, a masked identifier, usage counts and the agent's name and
look (so your devices match) — and message content only as conversation sync, on by default
when signed in and switched off under *Data controls* ([privacy.md](privacy.md),
[sync.md](sync.md)); the first conversation says so in its fourth line. On the phone, API keys, the account key and Reach
pairing tokens are in `EncryptedSharedPreferences`; since 0.1.40 the app takes no part in
the device backup at all (`allowBackup="false"` — chats, memory and keys never go to Google,
a reinstall starts empty and the account's chats come back through sync; the two rule files
under `res/xml/` are kept for the day the switch is turned on again). Hands needs the accessibility service
and the overlay permission, both optional and both revocable from the same screen (the first
run's Hands page asks for them under the app's mark, as the sign-in does); a
step that sends something — a tap on *Send*, or Enter in a message field of a messenger —
is approved one at a time, and *for this chat* answers stay bound to the app or address
they were given for. Another device of your account that wants to run, read or write
something on the phone (hub `shell`, `files`, `open`, `screen`…) is approved by the person
holding the phone first — *once* or *always for that device*, revocable under Permissions.
A path another device or the agent names (hub `files`, `nanomuse-media`, `nanomuse-pc put`)
is resolved inside the sandbox only (`io.github.nanomuse.sandbox.SandboxPaths`): `..` and a
symlink out of the rootfs lead nowhere, so the app's own private files stay out of reach.
The app allows plain `http://` only for addresses on your own network (the private ranges
`10/8`, `172.16/12`, `192.168/16`, the carrier-grade `100.64/10` Tailscale hands out, link-local,
IPv6 ULA, `localhost`, a name without a dot, and the suffixes `.local`, `.lan`, `.home`,
`.internal`, `.home.arpa`, `.localdomain`, `.ts.net`) — a model server or a computer of your own —
and refuses it at the provider URL field for anything else (`io.github.nanomuse.net.LanOnly`).
The address is parsed before it is judged, so a public name such as `10.foo.example.com` is
not taken for a private address. The same rule decides whether a relay of your own may be
`http://`; nanoMuse Cloud and the hub to it are TLS only. The in-app web view is not exported
to other apps.

## Building it yourself

JDK 17 or 21 (CI uses 21) and the Android SDK (Android Studio installs both); `scripts/android/env.sh` sets
the environment on a bare machine. The project is under `android/src/android`:

```bash
bash scripts/android/build-natives.sh   # once: proot, the Alpine rootfs and rclone.aar (NDK r27c, Go 1.25+)
cd android/src/android
./gradlew :app:assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
./gradlew :app:assembleRelease      # signed with android/keystore.properties when present
```

`rclone.aar` is built with Go, which fetches its modules through Go's default proxy
(`https://proxy.golang.org,direct`); on a mainland-China network set
`export GOPROXY=https://goproxy.cn,direct` first, and `env.sh` keeps whatever you exported.

`scripts/rebrand.py` carries the version (`VERSION_NAME`, `VERSION_CODE`) and applies
nanoMuse's naming to the OpenMinis tree; `android/BUILDING.md` covers the native pieces.
Without a signing key the release build is signed with the debug key, which installs but
cannot update a properly signed build. To sign, create a key once and keep it outside the
repository:

```bash
keytool -genkeypair -keystore ~/.nanomuse-release/nanomuse.jks -alias nanomuse \
        -keyalg RSA -keysize 4096 -validity 10950
```

and put its four values in `android/keystore.properties` (git-ignored: `storeFile`,
`storePassword`, `keyAlias`, `keyPassword`).

## Releases

`.github/workflows/android.yml` builds the debug APK on every change under `android/`
(the "debug APK · arm64-v8a" check). A release is made from a tag by
`scripts/release-apk.sh <version>`: it checks the version against `rebrand.py` and
Gradle, builds `:app:assembleRelease` with the release key, writes
`dist/nanoMuse-<version>-arm64.apk` and its `.sha256`, and with `--publish` tags
`v<version>` and attaches both to the GitHub release with the notes from
`docs/releases/v<version>.md`. A debug-signed APK never goes on a release, because it
could not be updated by a properly signed one. The `versionName` must match the tag,
like the Python package's version does.

## Where things are

| Path (`android/src/android/app/src/main/java/io/github/nanomuse/`) | Does |
| --- | --- |
| `cloud/NanoMuseCloud.kt` | The account: sign-in with a code or a password, the key in the encrypted store, `/v1/me`, usage, sessions, the localized error sentences; the relay's menu and its two defaults (`for: chat` / `for: gui`) |
| `cloud/Region.kt`, `cloud/ProviderCatalogue.kt`, `cloud/Capabilities.kt`, `cloud/OwnKeyPresets.kt`, `cloud/ProfileSync.kt` | Which region's vendors come first (mainland → Bailian, else OpenRouter and OpenAI); the own-key catalogue read from `assets/nanomuse/providers.json` and which vendor a configured provider is; what a provider covers and the one-sentence "unavailable" lines; the pre-filled provider forms (`?preset=<id>[:oauth]`); the relay profile (name, look, connectors) pulled and pushed |
| `sync/` | Conversation sync (contracts C7–C10): `SyncEngine` (what goes up and comes down; `owner` per mapping, the account's only), `ConversationSync` (when; `hidden` — the chats of another account, left out of `ChatRepository.observeSessions()`), `LocalChats`, the Room store `nanomuse_sync.db` (with the `session_owners` table of C12) |
| `account/` | Contract C12 (0.1.40, [sync.md](sync.md)): `AccountScope` (the rules — whose chat a session is, the account's key, what the lists leave out, what a refused key keeps (`keepOnRefusedKey`: everything, unless the relay says `account_deleted`); unit-tested), `AccountData` (applies them: every chat an owner row, `leave` puts the account's chats, memory, feed, goals, routines, face and preferences aside or deletes them, `enter` brings an account's back). The Library tab follows the same rule: it lists the workspaces of the sessions the chat list shows, so another account's files stay off a shared phone (`library/LibraryIndex.shows`, unit-tested) |
| `hub/` | `Hub` (state, device identity, settings), `HubClient` (the socket with backoff; a refused key is retried once a minute and shown as such, a replaced connection waits 30 s, a hub the operator paused waits two minutes and is shown as such), `HubService` (the foreground service), `HubActions` (what other devices may ask this phone; `stop {call | conversation}` ends a task the asking device started here, bookkept in `HubTasks`, unit-tested), `HubErrors` (failures in words) |
| `reach/` | `Computers` (paired computers, tokens in the encrypted store), the offload handler that sends work to a computer |
| `models/` | Settings → Models behind the screens: `ModelSlots` (the four slots, what each is set to and where that is kept, the groups a picker shows, `followPick` for the chat default, `applyProvider` for the *Use it for* card), `SlotOrder` (the resolution order and the catalogue default, pure Kotlin, unit-tested), `PickerList` (the picker's eight-row groups, their order and the search filter, pure Kotlin, unit-tested) |
| `ui/models/` | The Models page, the picker behind each row, the *Use it for* card (`minis://settings/models`) |
| `chat/CloudRetry.kt` | *Use nanoMuse Cloud this time*: whether the card offers it and the one-turn provider `ChatViewModel.retryLast` uses |
| `hands/` | The accessibility service as the hand, the stage and the capsule, the screen reader; `Hands.screenModel` picks the screen's model (chosen → the chat provider's own default when it sees → the Cloud's `qwen3.8-27b` → the same under your own key → a chat model that sees → the Vision Group) |
| `ui/coding/` | The coding agents of your computers |
| `connectors/`, `ui/connectors/` | The connectors catalogue (`ConnectorsCatalogue` reads the asset), MCP authorization discovery + registration (`McpAuthDiscovery`), connecting and token refresh (`Connectors`), what this phone connected as published to the profile and what the other devices did (`SharedConnectors`), the Settings → Connectors page |
| `ui/cloud/` | Sign-in, the Account screen, the Devices section |
| `res/values*/nm_strings.xml` | Every nanoMuse string in the seventeen languages the app has (English, 简体中文, 繁體中文, German, Spanish, Filipino, French, Indonesian, Japanese, Korean, Malay, Polish, Brazilian Portuguese, Romanian, Russian, Thai, Turkish); every file carries the same keys, and a missing one falls back to English |
