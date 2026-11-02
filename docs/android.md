# The Android app

Bundled skills in Settings → Skills can be read, exported and switched off. Their name, content and files are managed by the app, so Edit, Update and Delete are unavailable. To customize one, export it and import a copy with a different name. The bundled `skill-creator` guide uses provider-neutral instructions.

`android/` is nanoMuse for the phone: [OpenMinis](https://github.com/OpenMinis/OpenMinis)
1.13 (GPL-3.0): a native app whose agent runs **on the phone**, with a Linux shell, a
browser, MCP servers, skills and scheduled tasks inside the APK, with nanoMuse's own
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
repository's GitHub Releases second: *Latest 0.1.x, you have it* / *0.1.x is out, tap to
update*) and offers the download.

## Install

1. Download `nanoMuse-<version>-arm64.apk` from the
   [latest release](https://github.com/nano-muse/nanoMuse/releases/latest). Verify with
   `sha256sum -c nanoMuse-<version>-arm64.apk.sha256` if you like.
2. Open it. Android asks once to allow installs from your browser or file manager.
3. **Sign in.** The first screen is the account: a phone number or an e-mail address,
   a code, or a password once you have set one. It is what lets your devices work as one
   ([hub.md](hub.md)) and brings a model to start with ([cloud.md](cloud.md): a free pool per
   account (¥10 at the time of writing) and more for each friend invited, and for them,
   once the friend makes a first request; the app prints the relay's current figures; then [your own key](own-key.md)). Then choose which model answers: the account's
   own, or a key of your own (any OpenAI-compatible endpoint, or the OAuth sign-ins the
   app ships with). Four models are set, not one, and they live on one page, **Settings →
   Models** (the card at the top of Settings opens it): **Chat**, the model that talks with
   you; **Operating the screen**, the one that looks at the screen; **Making pictures** and
   **Making clips**. The hosted account recommends the same multimodal
   `Qwen/Qwen3.6-27B-FP8` for the first two jobs and does not generate pictures or clips.
   Each row shows `<provider> · <model>` and opens a picker: the *nanoMuse Cloud* group first
   when signed in only on rows its live menu covers, then one group per provider of your own
   with only the models that fit the row. A group shows eight models until you tap *Show N more* (the catalogue's default
   for the row first, then the one in use, then the rest as the provider lists them); past
   eight models in all, a *Search models* field above the groups filters every group live by
   id or name, and *No model matches* says when nothing does; the search and the opened
   groups survive a rotation and the trip through *Add a provider*. A chat pick there, or in the
   chat's own `•••` menu, is the default for new chats and moves the main chat
   (*Applies to the main chat and to new chats; a side chat keeps its model.*); a side
   chat already open keeps its model. The other three pickers
   open with *Automatic* (*Currently nanoMuse Cloud · Qwen/Qwen3.6-27B-FP8* for screen
   operation, for example), which forgets a choice
   made there and lets the row follow the order below again. Signed in, the page opens with
   one switch, *Use nanoMuse Cloud models*: off, the account leaves every picker and the
   automatic order, no side call (titles, memory or screen operation) runs on it, and only the
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
The other model choices stay as they are. The page is the place to change it later.

**When you have not chosen.** Chat is the relay's recommended model when signed in, else the
first provider of your own. The screen, pictures and clips follow the chat provider when it is
a provider of your own with that capability (its catalogue default); else the relay's model
when signed in and its live menu offers that job; else the first provider of your own that
can. The hosted Cloud menu offers chat and screen operation, not media generation. A choice
always wins, and nanoMuse Cloud never steps in front of a provider you chose. When a model of your own fails,
nothing falls back on its own: the error card gets *Use nanoMuse Cloud this time* (signed in
only) for a chat or screen turn, which runs that one turn on the relay's chat model and
changes no row. Failed media has no Cloud retry; choose or fix a provider of your own.

**Your own relay.** The sign-in screen talks to nanoMuse Cloud unless you tell it
otherwise: *Use a different server* under the sign-in form takes the address of a relay
you run yourself ([cloud.md](cloud.md), `cloud/docker-compose.yml`), *Check* asks its
`/healthz` and shows the version it answers with, *Use this server* keeps the address
across launches. `https://` is required for anything outside your own network; plain
`http://` is accepted for an address on your own network, judged by the same rule as a
model server's (below: the private ranges as parsed addresses, `localhost`, a name without
a dot, a `.local`, `.lan`, `.home`, `.internal`, `.home.arpa`, `.localdomain` or `.ts.net` name). Settings → Account shows *Server: `<host>`* with *Change*, which signs the phone out first: the key it holds belongs to the
server that issued it. Everything the app does with the account (sign-in, the hub, sync,
usage, the model menu) goes to that address.

## What the phone does

Shell progress updates preserve text beyond a shorter rewrite. Terminal color and title codes are removed before those updates, so they cannot leave escape fragments in the output.

The agent's system prompt keeps its safety, tool and phone-operation instructions in a stable
prefix. Session-dependent material (skills and MCP metadata, model/device state,
conversation-specific steering, memory and `USER.md`) is appended in a deterministic suffix, with
the date, language and available-model count in its final runtime-context section. Updating memory
or crossing into a new day therefore leaves the static prefix available to providers that support
prefix caching.

The phone budgets each request against the active model's context window, including a smaller
window configured for its model group. `ContextBudget` reserves the smaller of the requested
output limit and `max(4096, 15% of the window)`, bounded by the window itself. It then subtracts
system instructions and tool definitions to find the space available for conversation history.
Old tool content is eligible for offloading at 75% of that space; summarization starts at 90%,
and maintenance aims for 50%. The fixed prompt is added back to each threshold. These are
maintenance watermarks: the actual output limit is calculated separately from the space left
by the outgoing request. There is no universal 32k compaction limit.

Context checks include ordinary message text, structured content, summaries, reasoning sent
back to the provider, system instructions, tool definitions and images. Non-ASCII text has its
own estimate. Successful responses calibrate that estimate up or down gradually; calibration
is saved separately for each provider configuration and model and survives **Continue** or an
app restart. For an unchanged request prefix, the latest reported input usage takes precedence,
with an estimate added for new messages. Changing the provider, instructions, tool definitions
or old content invalidates that usage anchor. Invalid usage samples are ignored. Estimates for
new or rewritten input are still heuristics, not the model's own tokenizer. Native audio uses provider-reported accounting rather than treating its base64
transport as text. Requests are measured again after offloading or summarization.

Before requesting a summary, the phone can remove older reasoning from the outgoing request
and move older tool results and large tool arguments to files the model can read. It protects
the latest user request and, normally, the latest three tool iterations; under tighter pressure,
it keeps at least the latest iteration. A single oversized result in that latest completed
iteration can be saved to a file while its call, reasoning and result reference remain paired. A failed file write
leaves the original content in place. If summarization cannot make enough room, eligible older
tool steps can also be archived with a file reference. Saved conversation history retains its
original messages. Removing reasoning and replacing older history with a summary are lossy:
the model no longer receives every original detail on each call.

An early summary that fails or does not shrink the request does not stop a turn below its
capacity reserve, and does not run again after every tool result. Each agent run has at most
three automatic summary attempts. If only the calibration multiplier puts a request over the
reserve while its uncalibrated estimate still fits, the run permits one provider request to
check that estimate. Otherwise a request that cannot be reduced enough stops. A summary
stream times out after 120 seconds without a chunk; its complete operation, including segments
and retries, has a 900-second deadline. Stopping the turn cancels the summary request.

A summary separates background and completed work from the current request, its unfinished
steps and the next action. When no task is active, those task sections say so instead of
reviving old requests. After summarization, optional older turns are replayed only within the
budget left by the fixed prompt, summary and protected current turn. That budget changes with
the active model and request rather than staying at 8k. For a very long single task, the
checkpoint replaces covered older steps while the full user request and recent complete tool
iterations remain. The latest question and retained tool pairs stay intact even when that
protected tail alone is too large; the context guard then
decides whether it can be sent. Structured follow-ups and attachments also carry the summary.
Notices follow the app language. This Android loop is independent of the Python runtime's
task budgets.

`PromptDiet` shortens the `browser_use` schema descriptions while keeping every action and
parameter, and condenses the `minis-*` paragraphs in the Android tools section. Each CLI's
`--help` provides its full usage instructions.

With the default thinking rules, Qwen3.8-Max summary requests explicitly send `enable_thinking: false`. Omitting that
field leaves the provider's default in control even though the app requested thinking off.
The switch is documented in [Alibaba Cloud's thinking guide](https://help.aliyun.com/zh/model-studio/deep-thinking).
A timeout still does not identify whether the delay was in the network or at the provider.

While a turn has no first token yet, a small line sits under the typing dots (`NmWaitLine`):
nothing for ten seconds, then *The model is busy, 15 s so far* with *Cancel*; and when
nanoMuse Cloud has said the request is waiting for one of its provider slots (relay 0.31
sends a chunk with no `choices` and a `nanomuse: {phase, ahead}` field every five seconds,
[cloud.md](cloud.md#protocol)), *3 ahead of you* or *You are next* instead, as soon as that
is known (`NmStreamStatus`, one marked line in `OpenAIProvider`). Each step of a tool-using
turn counts its own wait.

| | |
| --- | --- |
| **The agent, on the phone** | A sandboxed Alpine Linux, a real shell, files, a browser, MCP servers, skills in the Agent Skills format, memory, scheduled tasks; approvals before deleting, sending or paying. The model is the account's or your own; with your own key the chat itself goes from the phone to that provider and never through the project's relay, and from 1.0.7 the finished turn is added to your account's record afterwards (the model's id and the turn, never the key) so your other devices have it ([cloud.md](cloud.md#the-record)). |
| **Hands** (`hands/`) | With *Hands* on and the accessibility service enabled, the agent looks at the phone's screen and taps, types and swipes in its apps: the last rung after APIs, fetches and the browser. A stage over the app shows where it is about to tap and a capsule with the step and **Stop**; a glow breathes along the screen's edges (blue working, amber waiting; 2.4 s in, 2.4 s out, like every working light on every client since round 9: nothing runs round the rim or slides down the screen, and the capsule's ring and bars breathe at the same pace; everything holds still under the system's reduce-motion setting); when a tap would send, post or delete, the capsule itself asks (**Allow** / **Deny**, the same request the chat card and the notification show), so you are not pulled back into nanoMuse (money is confirmed with the screen lock in the chat card; the capsule offers *Open* for that one); the capsule only ever answers its own request, never a shell or browser card of another conversation, and **Stop** while a card is waiting denies it and ends the run at once. Passwords and codes are always yours to type. The same action a third time on a screen that did not change gets a line in the history so the model changes tack, and a sixth ends the run as *infeasible* with the action named (`HandsLoopWatch`, the floor the runtime has too), instead of one model call per step until the thirty-minute limit. Every step's screenshot is written next to the run's trace under the session's `attachments/hands/<run>/`; the ten newest runs keep all of theirs, an older run keeps its trace and the last screen (the one the chat shows), and past 200 runs the oldest is removed (`HandsTraces`). [gui.md](gui.md) is the design record; the app's own hands are in `io.github.nanomuse.hands`. |
| **Reach** (`reach/`) | Your computers, from the phone: "say it on the phone, it gets done there" (a shell command, a file, the computer's screen, or a whole task for the nanoMuse running there). The way in is the hub (next row): install nanoMuse Desktop on the computer and sign in with the same account, and it is under *Account → Devices* within seconds, on any network, the only way since 0.1.24 (the local-network host script is gone). *Settings → Computers* lists the account's computers and says which account the phone uses, since a missing computer has nearly always signed in with another one. Approvals are decided on the phone before anything is sent. [every-device.md](every-device.md). |
| **The hub** (`hub/`) | Every signed-in device of the account meets on the relay's hub: the phone sees your computers, asks them to do things, gets their approvals as cards, and can be asked by them. A foreground service keeps it reachable in the background (Android 13+ asks for the notification permission for that). [hub.md](hub.md). |
| **Coding agents** (`ui/coding/`) | The Cursor, Codex and Claude Code sessions on your computers, seen and steered from the phone. [coding-agents.md](coding-agents.md). |
| **Account** (`ui/cloud/`) | Who is signed in, the password, every device holding a key, usage by kind and by model, the ways out. When the free pool is spent or past 80 %, the account page and the refused turn show the ways on: your own key, that is, the providers of the catalogue, the region's first (Alibaba Cloud Bailian for people in mainland China: the UI in simplified Chinese, a phone-number sign-in, or the relay saying so; OpenRouter and OpenAI everywhere else), each saying what it covers; a subscription you already pay for (ChatGPT, Claude, Kimi, OpenRouter sign in instead of a key); and an invitation. See [Your own key](#your-own-key) below. A phone shows and syncs the signed-in account's conversations only: since 0.1.40 every chat has an owner, synced or not, and a sign-out asks *Keep this account's chats on this device* (off by default: the account's chats, memory, feed, goals, routines and face leave the phone; on: put aside until it returns); deleting the account removes all of it; a key the relay refuses (`401 bad_key`) puts the account's data aside as *Keep* would and the sign-in page says so until the next sign-in; only `401 account_deleted` removes it; signed out, only the chats made while signed out show ([sync.md](sync.md)). |
| **The browser handed over** (`browser/`) | A page that needs you (a login, a verification code, a payment, a CAPTCHA) is handed over instead of described: `browser_use`'s `hand_over` action opens the agent's own tab (same WebView, same session) in the browser sheet with the agent's hold released, a **Your turn** card above the composer says what the page asks of you with *Open the page* and *Done, continue*, the sheet carries the same line and button, and the tool call waits for *Done* (fifteen minutes at most) before the agent goes on from the page as it is. `io.github.nanomuse.browser.BrowserHandOver`. |
| **Connectors** (`connectors/`, `ui/connectors/`) | The services the agent can be let into: the desktop's catalogue of 75 remote MCP servers (Notion, Linear, GitHub, GitLab, Slack, Stripe, Miro, …), shipped as `assets/nanomuse/connectors.json`. The only Settings row for all of this is *Connectors*; the upstream MCP editor (by address, by command, imported JSON) is *Your own servers* at the end of the page. Open servers add with a tap; a key service takes the key; an OAuth service runs the MCP authorization flow (discovery, dynamic client registration, PKCE in a Custom Tab) and the token goes into the entry's `Authorization` header for the in-guest MCP client, refreshed at app start; a service whose authorization server registers no clients (`clientIdRequired`: GitHub, Slack, Discord, HubSpot, Render, Bitrise, PagerDuty, Box) asks for an OAuth client id and secret made at the vendor's developer page with the app's callback address, which the sheet shows and copies. A connected service is an MCP server entry under the same id; *Your own servers* manages it too. What is connected is shared with the account's other devices through the relay profile, the entries (id, label, address, kind of auth, which device, when), never a token, so the page also lists *On your other devices*: a service connected on the desktop shows as *Connected on <device>. Sign in here to use it on this phone*, one tap into the same sheet. |
| **The chat, plain** | While the agent works, the line under its avatar names the step under way (*nanoMuse is using Shell*, *Writing the reply*, *On it: book the table*), never a state of mind. The tool pills, the Computer sheet and the floating step bar are **on by default** since 0.1.37; *Settings → Appearance → Show the agent's steps* turns them off. With them on, a finished step reads *nanoMuse used Shell · Done*, and its sheet closes on ×, swipe or Back. |

The chat sits on the same canvas as the pill bar, the menus and the drawer: pure black in the
dark theme, pure white in the light one. Your messages are white pills with black text (black
pills with white text in light), the agent's replies sit in a pill a shade off the canvas
(`#1C1C1E` / `#F2F2F7`), and the send button and the scroll-to-latest disc are white with a
black arrow (inverted in light); there is no blue in the conversation apart from links. The
header is not a bar but a scrim: the conversation scrolls under it and dissolves into the
canvas, and a second fade appears at the top edge while you read older messages. The palette
is upstream's `com/openminis/app/ui/theme/ChatColors.kt`, written by `scripts/rebrand.py`.

The message composer stays above the floating navigation pill, and the pill is as wide as the
composer (the same 16 dp margins; 420 dp at most, centred on a wider screen), so the two
capsules stack with one edge. While the agent uses tools,
the step bar sits above the composer; the latest message and tool pills can scroll fully
above both. The conversation still scrolls behind the navigation pill for its frosted blur.
The spacing follows the actual footer height when the composer expands or a tool preview
or approval card appears. The approval card itself takes at most two thirds of the screen:
a command longer than six lines is folded behind *Show all*, the description and the
preview scroll in the middle, and Allow and Deny stay in view at the bottom. When reading
older messages, a slightly lighter fade follows
the composer's rounded outline. Live browser controls hide it; historical tool pills and
other tools keep it. In dark-mode home and side chats, pure black surrounds the navigation
pill and fills the gap below the composer. Its glass stays open to the scrolling content
for live frosted blur. Other tabs keep their navigation appearance. With the keyboard
open the composer sits on the keyboard and the pill is behind it. The Feed, Ideas, Goals and
Library lists end above the pill as well, so their last row is never under it.

The web console of the same account is at the relay (`/app`), the desktop app in
[desktop.md](desktop.md); the phone, the desktop and the web share the design language
described in [brand.md](brand.md).

Under **Settings → Appearance**, the font-size labels for **Chat Input**, **Message Text** and **App Base** follow the app's language.

## Your own key

The vendors the app knows are one file, `assets/nanomuse/providers.json`, a copy of the
runtime's `nanomuse/llm/providers.json` written by `node scripts/providers-json.mjs`, the same
catalogue every client reads ([own-key.md](own-key.md)). Each entry says where the endpoint is,
where a key is made, which sign-ins it has, where it signs people up (`cn`, `global`) and what
its models can do: `chat`, `vision` (the hands' screen), `image` (pictures), `video` (clips).

**The card.** When the allowance is spent or nearly, *Use your own model key* lists the
catalogue, the region's vendors first: Alibaba Cloud Bailian on the mainland (one key covers
all four; it signs up accounts from mainland China only), OpenRouter and OpenAI elsewhere;
then the rest, three at a time behind *More providers*. Every row says what the vendor covers
(*chat · screen · pictures · clips*); *Add* opens the provider form pre-filled with its name,
endpoint and `/v1` setting (`minis://settings/providers/add?preset=<id>`), *Get a key* opens
the vendor's key page. No vendor is recommended. *A subscription you already pay for* lists
the vendors whose plan signs in instead of a key: ChatGPT (OpenAI's Codex OAuth), Claude,
Kimi (a device code) and OpenRouter; *Sign in* opens the same form on the sign-in button
(`?preset=<id>:oauth`), which runs OpenMinis' own `OpenAIOAuthManager`, `ClaudeOAuthManager`,
`KimiOAuthManager` or `OpenRouterOAuthManager`. The ChatGPT row carries the line that
OpenAI's terms cover a ChatGPT plan inside OpenAI's own Codex, that other apps have had this
access cut off before (OpenCode, January 2026), and that an API key works if it stops.
Anthropic and Gemini open on OpenMinis' own provider types for them; everything else on the
OpenAI-compatible form. The Claude sign-in needs an identifier Anthropic expects at the start
of every request; it is read at build time from `app/provider-customization.properties`, which
is not in this repository, so the published APK does not have it. A build without it does not
list the Claude sign-in (not on this card, not under *Add a provider*, and `?preset=anthropic:oauth`
opens the API key form), and a Claude sign-in saved by an earlier build answers each send with
*This build cannot use a Claude sign-in. Add Anthropic with an API key instead.* rather than
closing the app (`io.github.nanomuse.cloud.ClaudeSignIn`).

**Where the list comes from.** The relay's `/v1/me` carries `spend.guidance` (relay 0.21,
[cloud.md](cloud.md)): the providers for the person's region in the relay's order, each with
what it covers, the plans one can sign in with and which clients they are for, the local
servers, the docs link and the honest line about the ChatGPT sign-in. `cloud/Guidance.kt`
parses it, `Ways.resolve` prefers it, and the card and Settings → nanoMuse Cloud read the
bundled catalogue only when the relay sent none (an older relay), so a vendor added on the
relay shows before the app is updated, and a provider the relay no longer lists is gone the same
day. A `429 allowance_exhausted` carries the same block beside the figures.

**What each covers.** The capabilities decide what the app offers (`cloud/Capabilities.kt`):
pictures (Settings → Models → Making pictures, the avatar studio, `nanomuse-media image`) pick a
provider only among those whose vendor has `image`; clips among those with `video` that the
app can drive (Bailian's video API); the screen's model and its picker list only models of
vendors with `vision`. A ChatGPT plan signed in through Codex is chat and vision (the Codex
backend has no image or video endpoints), so it is never offered for pictures. A vendor the
catalogue does not know (a gateway, a relay of your own, nanoMuse Cloud) is taken at its
models' word, as before. When no configured provider has a capability, the page says so in one
sentence (*Pictures need a provider with image models: Bailian, OpenAI, Gemini or
OpenRouter.*) instead of failing.

**Which video models a key has.** Bailian's `/models` list names no video models, so the app
asks the host about each of the models this build knows (`VideoGen.KNOWN_DASHSCOPE_MODELS`,
Wan 2.2 Flash first) with an empty task that bills nothing, and remembers the answer for a day.
The *Video* picker offers that answer plus every model you listed on the provider yourself — an
entry whose name says video (`t2v`, `i2v`, …) or whose output modalities say `video` in its
details, whatever its name — as it is, probe or no probe. The remembered answer is asked again
as soon as the models to ask about change (an entry you added, a build that knows a newer
model), not only after the day is up. *Image & video models* keeps a field for typing any model
id. ([#508](https://github.com/nano-muse/nanoMuse/issues/508))

In the avatar studio, asking for a new set of candidates replaces the previous set. A picture
or failure that finishes from the previous request cannot change the new set's tiles or files.
Again starts the new request without waiting for the old picture to finish saving.

**When the provider cannot be reached** (`net/ProviderReach.kt`, `ui/chat/ProviderReachCard.kt`).
A failed turn whose error is the transport's (OkHttp's *failed to connect to chatgpt.com/… (port
443)*, *Unable to resolve host*, a TLS or timeout line) or OpenAI's *region not supported* is
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
computer: *@* and its name in the chat runs the turn there.

**When the relay refuses a turn** (`cloud/RelayRefusal.kt`, `ui/chat/RelayRefusalCard.kt`).
Every refusal nanoMuse Cloud sends is one plain sentence in the phone's language and the button
that fits, never a status code, the relay's JSON or upstream's *Rate limited*. The reply is
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
now, not used up* and that what is left stays as it is. The sentences are
`NanoMuseCloud.describe`'s, the same ones the sign-in and account pages use, in all 17 locales
(`nm_cloud_err_*`). Unit tests: `RelayRefusalTest`, `GuidanceTest`.

**Settings → Network** (`net/OwnProviderProxy.kt`, `ui/net/NetworkScreen.kt`,
`minis://settings/network`). The HTTP proxy for own providers: host, port, optional user name
and password, off by default, on this phone only: the settings in `SharedPreferences`, the
password in an `EncryptedSharedPreferences` file of its own (`nanomuse_proxy_secrets`, the way
the provider keys are kept; a password a 1.0.3 phone saved in the plain file is moved over on
the first read). It is installed in
`MinisApp.onCreate` as the process's default `ProxySelector`, so every OkHttp client asks it per
request; it answers the proxy for the catalogue's hosts, `chatgpt.com`, `auth.openai.com` and
the custom base URLs of the provider instances (never the relay's, never a LAN address), and the
system's answer for every other host: the hub, the relay, the sandbox mirrors are untouched.
Provider clients carry `OwnProviderProxy.authenticator` for a proxy that asks for a password.
*Test* fetches `https://chatgpt.com/` through the proxy as entered and reports the status and the
milliseconds. Unit tests: `ProviderReachTest`, `OwnProviderProxyTest`.

Leaving sign-in or the Network page ends its pending request, even if the server has
started to answer but has not finished sending the response.

## Voice input

On Android 13 and later, continuous system dictation keeps feeding audio when the recognizer
starts its next segment. A write that fails on the previous segment's closed pipe cannot
disable the new segment's audio stream.

Provider voice input returns to idle when a silent session reaches its limit or a very short
utterance expires without enough speech to transcribe. A transcription already in progress
still delivers its result before the session finishes.

System voice input can prefer on-device recognition. If the phone has no usable on-device
service, it falls back to the default recognition service. A language error from that
default service is shown in the voice panel. A running on-device recognizer whose language
pack is unavailable still falls back once to the default service.

The voice detector releases its allocated recorder if recording cannot start or is cancelled
before capture begins. You can retry voice input without leaving that recorder allocated.

A segment that closes on silence is transcribed and the microphone stops, and that stop used
to free the voice detector's native object from inside its own callback, on the same thread,
while the detector was still running: the app died with a native crash the moment a take of
two seconds or more fell silent (1.0.8 fixes this; upstream OpenMinis 1.14 has the same
change). A stop from inside a callback now takes effect once the detector has handed the
frame back.

## Privacy and permissions

The relay keeps an account id, a masked identifier, usage counts and the agent's name and
look (so your devices match); of your chats, the record (every turn with the relay's models
in full, and from 1.0.7 the turns on your own key too, readable by your devices and by
whoever runs the relay, deleted from *Data controls* with one tap), conversation sync (on by
default when signed in, switched off under *Data controls*), and the training set only
while *Help improve* is on ([privacy.md](privacy.md), [cloud.md](cloud.md#the-record),
[sync.md](sync.md)); the first conversation says so in its fourth line. *Data controls* shows
what the record holds of your account (turns, those on your own keys, pictures) and how long
this relay keeps a turn. On the phone, API keys and the account key
are in `EncryptedSharedPreferences`, and so is the proxy password of *Settings → Network*
(since 1.0.4; on this phone only); since 0.1.40 the app takes no part in
the device backup at all (`allowBackup="false"`: chats, memory and keys never go to Google,
a reinstall starts empty and the account's chats come back through sync; the two rule files
under `res/xml/` are kept for the day the switch is turned on again). Hands needs the accessibility service
and the overlay permission, both optional and both revocable from the same screen (the first
run's Hands page asks for them under the app's mark, as the sign-in does); a
step that sends something (a tap on *Send*, or Enter in a message field of a messenger)
is approved one at a time, and *for this chat* answers stay bound to the app or address
they were given for. Another device of your account that wants to run, read or write
something on the phone (hub `shell`, `files`, `open`, `screen`…) is approved by the person
holding the phone first: *once* or *always for that device*, revocable under Permissions.
A path another device or the agent names (hub `files`, `nanomuse-media`, `nanomuse-pc put`)
is resolved inside the sandbox only (`io.github.nanomuse.sandbox.SandboxPaths`): `..` and a
symlink out of the rootfs lead nowhere, so the app's own private files stay out of reach.
The app allows plain `http://` only for addresses on your own network (the private ranges
`10/8`, `172.16/12`, `192.168/16`, the carrier-grade `100.64/10` Tailscale hands out, link-local,
IPv6 ULA, `localhost`, a name without a dot, and the suffixes `.local`, `.lan`, `.home`,
`.internal`, `.home.arpa`, `.localdomain`, `.ts.net`), a model server or a computer of your own,
and refuses it at the provider URL field for anything else (`io.github.nanomuse.net.LanOnly`).
The address is parsed before it is judged, so a public name such as `10.foo.example.com` is
not taken for a private address. The same rule decides whether a relay of your own may be
`http://`; nanoMuse Cloud and the hub to it are TLS only. The in-app web view is not exported
to other apps. Voice input through a provider's speech model keeps the microphone open only
while a recording is on: stopping or cancelling the recording closes the recorder at once, and a
cancelled recording's audio is dropped, never sent to the provider.

**What the record is told beyond the turn itself** (relay 0.31). A chat request to nanoMuse
Cloud carries, next to the device and the conversation, where the call sits: who started the
turn (`X-NanoMuse-Run`: you, a scheduled task, the feed's routine, a goal's check, a task
another device asked for through the hub), the turn's number in the conversation as the chat
counts it, the call's number within the turn, the screen task's run and step while the hands
work, and `X-NanoMuse-Platform: android`; a turn run on a key of your own goes up with the
same fields ([cloud.md](cloud.md#provenance); `io.github.nanomuse.cloud.Provenance`, read
from the chat's coroutine so a typed message, a retry, a routine's prompt, a hub task and a
hands step all say the same). While signed in, the phone also sends short records of what
happened around a turn (`POST /v1/events`, `io.github.nanomuse.cloud.ClientEvents`): what
the risk gate decided on each shell command, browser tap or screen step and how its card was
answered, each step of the hands and how the run closed, a turn stopped by hand or ended in
an error, and the two thumbs under the newest reply and the one question after a Stop
(*Why did you stop it?*, five one-word answers and *Skip*; a routine's or another device's turn
is not asked about). Codes and numbers only — the tool's kind, the risk's tier, who answered,
how long — never the command, the page, the screen or any words of the conversation
([cloud.md](cloud.md#client-events)); *Data controls*' delete removes them with the turns.

## Building it yourself

JDK 21 (what CI uses) and the Android SDK (Android Studio installs both); `scripts/android/env.sh` sets
the environment on a bare machine. The project is under `android/src/android`:

```bash
bash scripts/android/build-natives.sh   # once: proot, the Alpine rootfs and rclone.aar (NDK r27c, Go 1.25+)
cd android/src/android
./gradlew :app:assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
./gradlew :app:assembleRelease      # signed with android/keystore.properties when present
./gradlew :app:testDebugUnitTest --tests 'io.github.nanomuse.*'   # our unit tests
./gradlew :app:lintDebug            # Android lint; the report is app/build/reports/lint-results-debug.html
```

Lint runs on a newer lint than AGP 8.7.3 bundles (`android.experimental.lint.version` in
`gradle.properties`): the Compose and lifecycle libraries ship checks the bundled one cannot
load. The upstream tree carries lint findings of its own; read the report for `io.github.nanomuse`.

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

The chat-only emulator build (`-Pnm.abi=x86_64`) excludes cached arm64 proot and Alpine root filesystem assets. Switching back to the default arm64 build includes those assets again; no cache deletion is needed.

### Windows with WSL {#windows-wsl}

On x64 Windows, use an x86_64 Ubuntu environment in WSL 2 for the complete build.
The native build scripts support Linux and macOS hosts, not Windows shells.
[Install WSL](https://learn.microsoft.com/en-us/windows/wsl/install) first if needed,
then open Ubuntu. Only this first command runs in an administrator PowerShell:

```powershell
wsl --install -d Ubuntu
```

Run the remaining commands in Ubuntu. Keep the checkout, SDK and caches in its Linux
filesystem, rather than under `/mnt/c`, and keep shell scripts as LF text:

```bash
sudo apt update
sudo apt install -y git curl unzip zip build-essential pkg-config openjdk-21-jdk-headless
mkdir -p ~/src
git clone --config core.autocrlf=false https://github.com/nano-muse/nanoMuse.git ~/src/nanoMuse
cd ~/src/nanoMuse
git submodule update --init android/deps/proot
```

Install [Go for Linux](https://go.dev/doc/install) and put its `go` command on
Ubuntu's `PATH`; the [Android workflow](https://github.com/nano-muse/nanoMuse/blob/main/.github/workflows/android.yml)
uses Go 1.26. Download the **Linux** Android SDK Command-Line Tools and follow the
[sdkmanager setup](https://developer.android.com/tools/sdkmanager), using
`$HOME/Android/Sdk` as the SDK directory. The executable must end up at
`$HOME/Android/Sdk/cmdline-tools/latest/bin/sdkmanager`. The SDK installed by
Windows Android Studio does not contain the Linux NDK executables this build needs.

```bash
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export ANDROID_HOME="$HOME/Android/Sdk"
export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/27.2.12479018"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
export GOROOT="$(go env GOROOT)"
export GOPATH="$(go env GOPATH)"
export PATH="$GOPATH/bin:$PATH"
export GOTOOLCHAIN=auto

java -version
go version                         # must report linux/amd64
sdkmanager --sdk_root="$ANDROID_HOME" --licenses
sdkmanager --sdk_root="$ANDROID_HOME" "platform-tools" "platforms;android-36" \
  "build-tools;35.0.0" "cmake;3.22.1" "ndk;27.2.12479018"

bash scripts/android/build-natives.sh
cd android/src/android
./gradlew :app:assembleDebug --console=plain --no-daemon
```

The APK is `app/build/outputs/apk/debug/app-debug.apk` relative to the Gradle
directory. Copy the completed APK to Windows if needed; keep the build tree in Linux.

Gradle creates the debug signing key at `$HOME/.android/debug.keystore` inside
Ubuntu. Preserve that key outside the checkout if later debug builds need to update
this APK. It may differ from the key in your Windows home. A debug APK cannot update
an official APK signed with another key; use the release-signing instructions above
for your own release key.

If Kotlin runs out of Java heap, check the memory available to WSL with `free -h`.
On a machine with enough memory for both Windows and WSL, a build can raise the Gradle
and Kotlin daemon limits without editing the repository. For example, from the same
Gradle directory:

```bash
./gradlew :app:assembleDebug --console=plain --no-daemon \
  '-Dorg.gradle.jvmargs=-Xmx4g -Dfile.encoding=UTF-8' \
  '-Pkotlin.daemon.jvmargs=-Xmx6g'
```

These are optional heap ceilings, not minimum requirements. Choose limits that fit
the memory available to WSL and leave room for the other processes.


## Releases

`.github/workflows/android.yml` builds the debug APK on every change under `android/`
(the "debug APK · arm64-v8a" check). A release is made from a tag by
`scripts/release-apk.sh <version>`: it checks the version against `rebrand.py` and
Gradle, builds `:app:assembleRelease` with the release key, writes
`dist/nanoMuse-<version>-arm64.apk` and its `.sha256`, and with `--publish` tags
`v<version>` and attaches both to the GitHub release with the notes from
`docs/releases/v<version>.md`. Publishing refuses a working tree with uncommitted changes
and a commit that is not on `main`. A debug-signed APK never goes on a release, because it
could not be updated by a properly signed one. The `versionName` must match the tag,
like the Python package's version does.

## Where things are

| Path (`android/src/android/app/src/main/java/io/github/nanomuse/`) | Does |
| --- | --- |
| `cloud/NanoMuseCloud.kt` | The account: sign-in with a code or a password, the key in the encrypted store, `/v1/me`, usage, sessions, the localized error sentences; the relay's menu and its two defaults (`for: chat` / `for: gui`) |
| `cloud/Region.kt`, `cloud/ProviderCatalogue.kt`, `cloud/Capabilities.kt`, `cloud/OwnKeyPresets.kt`, `cloud/ProfileSync.kt` | Which region's vendors come first (mainland → Bailian, else OpenRouter and OpenAI); the own-key catalogue read from `assets/nanomuse/providers.json` and which vendor a configured provider is; what a provider covers and the one-sentence "unavailable" lines; the pre-filled provider forms (`?preset=<id>[:oauth]`); the relay profile (name, look, connectors) pulled and pushed |
| `sync/` | Conversation sync (contracts C7–C10): `SyncEngine` (what goes up and comes down; `owner` per mapping, the account's only), `ConversationSync` (when; `hidden`: the chats of another account, left out of `ChatRepository.observeSessions()`), `LocalChats`, the Room store `nanomuse_sync.db` (with the `session_owners` table of C12) |
| `account/` | Contract C12 (0.1.40, [sync.md](sync.md)): `AccountScope` (the rules: whose chat a session is, the account's key, what the lists leave out, what a refused key keeps (`keepOnRefusedKey`: everything, unless the relay says `account_deleted`); unit-tested), `AccountData` (applies them: every chat an owner row, `leave` puts the account's chats, memory, feed, goals, routines, face and preferences aside or deletes them, `enter` brings an account's back). The Library tab follows the same rule: it lists the workspaces of the sessions the chat list shows, so another account's files stay off a shared phone (`library/LibraryIndex.shows`, unit-tested) |
| `hub/` | `Hub` (state, device identity, settings), `HubClient` (the socket with backoff; a refused key is retried once a minute and shown as such, a replaced connection waits 30 s, a hub the operator paused waits two minutes and is shown as such), `HubService` (the foreground service), `HubActions` (what other devices may ask this phone; `stop {call | conversation}` ends a task the asking device started here, bookkept in `HubTasks`, unit-tested), `HubErrors` (failures in words) |
| `reach/` | `Computers` (the account's devices as the hub lists them, and the calls to them; no pairing and no tokens of its own since 0.1.24), the offload handler that sends work to a computer |
| `models/` | Settings → Models behind the screens: `ModelSlots` (the four slots, what each is set to and where that is kept, the groups a picker shows, `followPick` for the chat default, `applyProvider` for the *Use it for* card), `SlotOrder` (the resolution order and the catalogue default, pure Kotlin, unit-tested), `PickerList` (the picker's eight-row groups, their order and the search filter, pure Kotlin, unit-tested) |
| `ui/models/` | The Models page, the picker behind each row, the *Use it for* card (`minis://settings/models`) |
| `chat/CloudRetry.kt` | *Use nanoMuse Cloud this time*: whether the card offers it and the one-turn provider `ChatViewModel.retryLast` uses |
| `chat/RoutineWakes.kt`, `ui/chat/NmRoutineWakeRow.kt` | A scheduled task's turn is the routine's, not the person's: `ScheduledAgentRunner` arms a wake before the prompt goes out, `ChatViewModel` binds it to the persisted row, and the chat draws that row as one quiet line, *Routine · 〈label〉 · 08:00*, instead of a bubble in the person's voice; the model gets a one-turn `SessionAddenda` saying so, so it opens with the result rather than thanking anyone for asking. Up to 1.0.4 the prompt stood in the chat as if the person had typed it |
| `feed/` | The Feed: `FeedFlow` keeps the daily scheduled task and the conversation it writes in, which is the agent's working room and stays out of the drawer, the chat list and the main-chat fallback (`FeedFlow.hidden`, read by `ChatRepository.observeSessions()`, `MainChat` and the move-to sheet); `FeedStore` holds the posts, newest day first and, inside a day, the newest batch first with each batch in the model's order (a batch shares its `created` time; `FeedStore.DAY_ORDER`, unit-tested). The agent reads the posts, with `liked: true` on the ones you tapped, at `/var/minis/feed/YYYY-MM-DD/NN.md`: a read-only copy (`FeedSandboxScope`, refreshed before each shell command and on every like) rather than the app's own directory, since PRoot cannot bind a folder read-only and a like is the person's, not the agent's to change; a post without `liked` is one not reacted to, which the prompt says is not a dislike. When the task has written posts while the app is in the background, one notification names them and opens the Feed tab (`minis://feed`), in place of the generic "task done" notice with the model's text that up to 1.0.4 opened the conversation |
| `chat/TurnReply` | Which assistant message a finished turn produced: the last assistant row only when it follows the last user row and carries no error. The feed, the goals and the first conversation read the reply through it, so a turn that failed before its own reply existed hands them nothing rather than the previous reply (#637) |
| `net/ModelBlip` | The retry around the sandbox's `model_use` call: a network error, a transient error or a 5xx is tried again after one and two seconds, as the chat and iOS's bridge do; anything else is thrown at once. Also names a gateway's `HTTP 0` (its upstream gave nothing) as transient (#640) |
| `hands/` | The accessibility service as the hand, the stage and the capsule, the screen reader; `Hands.screenModel` picks the screen's model (chosen → the chat provider's own default when it sees → the model Cloud recommends for `gui` → the own-key fallback → a chat model that sees → the Vision Group) |
| `ui/coding/` | The coding agents of your computers |
| `backup/` | What nanoMuse adds to the upstream backup (*Settings → Backup and restore*, `minis://settings/backup`): under *Chats*, *Files in the chats* (on by default) can be turned off so the chats travel as messages only, each session's files listed in the package as tombstones and the other categories unchanged, which keeps a 1.5 GB package down to a few MB for a server that refuses large uploads ([#561](https://github.com/nano-muse/nanoMuse/issues/561)); a `413` from a destination names the server's upload limit (`BackupHints`); and `nanomuse-backup run` in the sandbox makes one backup with the page's saved choices and every enabled destination, recorded in the page's history (`BackupRun`; `status`, `history`, `choices` read it), so a scheduled task can keep the phone backed up. It refuses when encryption is on, since the passphrase is typed on the page and never reaches the shell, and when no destination is enabled ([#560](https://github.com/nano-muse/nanoMuse/issues/560)) |
| `connectors/`, `ui/connectors/` | The connectors catalogue (`ConnectorsCatalogue` reads the asset), MCP authorization discovery + registration (`McpAuthDiscovery`), connecting and token refresh (`Connectors`), what this phone connected as published to the profile and what the other devices did (`SharedConnectors`), the Settings → Connectors page |
| `ui/cloud/` | Sign-in, the Account screen, the Devices section |
| `res/values*/nm_strings.xml` | Every nanoMuse string in the seventeen languages the app has (English, 简体中文, 繁體中文, German, Spanish, Filipino, French, Indonesian, Japanese, Korean, Malay, Polish, Brazilian Portuguese, Romanian, Russian, Thai, Turkish); every file carries the same keys, apart from the two the English file marks `translatable="false"` (the relay address example and the product name `nanoMuse Cloud`), and a missing one falls back to English |
