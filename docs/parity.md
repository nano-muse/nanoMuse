# Feature parity across the clients

nanoMuse is one agent on every device: the phone (Android, iOS), the computer (nanoMuse Desktop —
the `dsh-nanomuse` harness bundle in the Electron shell) and the browser (nanoMuse Web, served by
the runtime). The rule since 0.1.32 is the **union**: whatever one client can do, every client
does, unless the platform itself forbids it (the computer does not build a mini-Linux the way the
phone does; iOS does not let an app drive another). This page is the ledger — what each client
has, what is platform-specific by design, and what is still open for a decision.

Legend: **✓** done · **◐** partial (what is missing is in the note) · **—** not on this client ·
**n/a** platform-specific, not meant to be.

## Account (nanoMuse Cloud)

| Feature | Android | iOS | Desktop | Web |
|---|---|---|---|---|
| Sign in with a code (phone / e-mail) | ✓ | ✓ | ✓ | ✓ |
| Sign in with a password | ✓ | ✓ 0.1.32 | ✓ | ✓ |
| Invite code at sign-in | ✓ | ✓ 0.1.32 | ✓ 0.1.32 | ✓ |
| Amounts from the relay (`/v1/config`) before sign-in | ✓ | ✓ 0.1.32 | ✓ 0.1.32 | ✓ |
| Allowance in yuan on the account page, the bar turning at 80 % | ✓ | ✓ 0.1.32 | ✓ 0.1.32 | ✓ |
| 80 % heads-up in the chat: one line above the composer, once per pool size, *See the ways* | ✓ | ✓ 0.1.40 *(33)* | ✓ 0.1.40 | ✓ |
| "Ways on" when the pool is spent (own key · invite · star) | ✓ | ✓ 0.1.32 | ✓ 0.1.32 | ✓ |
| Invite code and link, earnings | ✓ | ✓ 0.1.32 | ✓ | ✓ |
| Usage by kind and by model, today / all time | ✓ | ✓ 0.1.32 | ✓ 0.1.32 | ✓ |
| Set / change / remove the password | ✓ | ✓ 0.1.32 | ✓ 0.1.32 | ✓ |
| Signed-in devices, revoke one, sign out everywhere | ✓ | ✓ 0.1.32 | ✓ 0.1.32 | ✓ |
| Account timeline (sign-ins, settings, refusals) | ✓ | ✓ 0.1.32 | ✓ 0.1.32 | ✓ |
| Delete account | ✓ | ✓ 0.1.32 | ✓ 0.1.32 | ✓ |
| Data controls (what the relay keeps of the chats) | ✓ | ✓ 0.1.33 | ✓ | ✓ |
| Own-key presets (Bailian · OpenRouter, by region) | ✓ 0.1.34 | ✓ 0.1.34 | ✓ 0.1.34 | ✓ 0.1.34 |
| Chat model and Hands model as two settings (`deepseek-v4.1-flash` / `qwen3.8-27b`, the relay's `for`) | ✓ 0.1.34 | ✓ 0.1.34 *(chat; no hands)* | ✓ 0.1.34 | ✓ 0.1.34 |
| Models page, four slots (*Chat* · *Operating the screen* · *Making pictures* · *Making clips*): each row `provider · model`, a picker of nanoMuse Cloud's models (signed in, the recommended one marked) and of each own provider's models that fit; an empty row names who could and offers *Add a provider* | ✓ 0.1.41 *Settings → Models*, the card at the top of Settings opens it; *Settings → Hands* and *Image & video models* use the same choices | ✓ 0.1.41 the first card of Settings; the screen row disabled (*Not on iPhone*; the computer uses its own setting); the pictures and clips pickers list nanoMuse Cloud and own providers on a DashScope host only *(40)* | ✓ 0.1.41 right after General; the hands speak OpenAI's shape, so an Anthropic or native Gemini key is named under the row, not listed; pictures through an own provider go to it directly, nothing billed to the account | ✓ 0.1.41 *Connections*: the *Chat model* card, the *Hands model* select, the *Making pictures* and *Making clips* rows (`PUT /api/connections/image` · `/video`) |
| *Automatic* on the screen, pictures and clips rows, saying what it gives right now; the order when nothing was chosen: the chat provider's own model when it is yours and can → nanoMuse Cloud when signed in → the first own provider that can; a choice always wins | ✓ 0.1.41 `SlotOrder` | ✓ 0.1.41 pictures and clips (the screen is n/a) | ✓ 0.1.41 `handsChoice`, `imageEndpoint`, `videoEndpoint`; a hands change takes effect at the hands' next step, no restart | ✓ 0.1.41 the runtime resolves it (`effective_*`); *Currently provider · model* under each control |
| *Use it for* after a key is saved: one toggle per capability the provider has, all on; *Use it* moves those rows to the provider's catalogue defaults, *Not now* changes nothing; saving alone switches nothing | ✓ 0.1.41 | ✓ 0.1.41 (no screen toggle) | ✓ 0.1.41 | — the own-key form sets the chat provider; pictures and clips are set on their own rows *(40)* |
| *Use nanoMuse Cloud models*, a switch, not a delete: off, the account leaves the pickers and the automatic order of every slot and nothing spends the allowance but the explicit *Use nanoMuse Cloud this time*; the sign-in stays for sync and the hub, and the Cloud provider row cannot be deleted | ✓ *Settings → Models* | ✓ *Settings → Models* | ✓ *Settings → Models* | ✓ the nanoMuse Cloud card under *Connections* (`POST /api/cloud/models`); refused while the chat model is the account's, since the runtime holds one chat model |
| With a key of your own the app works signed out (chat, hands, pictures, clips); the first screen offers *Use your own API key instead* and the sign-in waits for the Cloud models, sync and the devices | ✓ | ✓ | ✓ the sign-in was never a wall | ✓ the sign-in page steps aside once a model is ready or the button was taken |
| No silent fallback: a failed turn on an own model offers *Use nanoMuse Cloud this time* (signed in), that one turn on the account, no row changed | ✓ 0.1.41 `CloudRetry` | ✓ 0.1.41 `NanoMuseCloudOnce` | ✓ 0.1.41 also after a failed studio round and a failed set of clips | — the failure is shown; the rows stay as set *(40)* |
| "Ways on" ordered by region (Bailian first on the mainland, OpenRouter first elsewhere) | ✓ 0.1.34 | ✓ 0.1.34 | ✓ 0.1.34 | ✓ 0.1.34 |
| Own-key catalogue (`providers.json`: 18 providers, what each covers — chat · screen · pictures · clips — key pages, regions; one file, generated for every client) | ✓ 0.1.39 | ✓ 0.1.40 `NanoMuseCatalogue` *(32)* | ✓ 0.1.39 | ✓ 0.1.39 |
| "Ways on" from the catalogue: the region's lead first, *more providers*, the plans one can sign in with, the key taken inline | ✓ 0.1.39 | ✓ 0.1.40 the pinned card, Settings → nanoMuse Cloud and the own-key sheet, one list (`NanoMuseWaysList`) *(32)* | ✓ 0.1.39 Settings → nanoMuse Cloud, the own-key first-run step | ✓ 0.1.39 |
| The ways read from the relay's `spend.guidance` (providers for the region, plans, caveats, docs) rather than a list in the app; the bundled catalogue only when the relay sends none | ✓ 0.1.40 `guidance` first, the catalogue when none *(34)* | ✓ 0.1.40 the same (`NanoMuseWays`) *(32)* | ✓ 0.1.40 the chat card and Settings → nanoMuse Cloud, one component | ✓ 0.1.39 |
| A refused turn (`429 allowance_exhausted`) is a card under it in the chat: one sentence, the three ways on, *Open Settings*, *Try again* — never the relay's reply as text | ✓ 0.1.39 `AllowanceWaysCard` | ✓ 0.1.40 pinned under the header like the star card (`NanoMuseAllowanceCard`) *(33)* | ✓ 0.1.40 *(before: the JSON, after five retries as a rate limit)* | ✓ 0.1.39 notice with the ways |
| The relay's other refusals as one sentence and a button: 413 *too large* → *New chat*, 401 → *Sign in*, 403, 429 busy (with the wait), the daily cap, 404 model, 5xx / no answer → *Try again*; never a status code or JSON | ✓ 0.1.40 `RelayRefusal` + `RelayRefusalCard`, 17 locales *(35)* | ✓ 0.1.40 `NanoMuseRelayRefusal` + `NanoMuseRelayRefusalCard`, 9 locales; a refused chat turn goes through `describe` *(35)* | ✓ 0.1.40 | ✓ 0.1.40 `failures.py` (413, `not_invited`, `too_many_in_flight`, `provider_busy` added) |
| The operator's switches (relay 0.22, [cloud.md](cloud.md#controls)) as plain sentences: the allowance *paused, not used up* (the same card), `service_paused`, `sync_paused`, `hub_paused`, `signup_closed` at sign-in | ✓ 0.1.40 *(35)* | ✓ 0.1.40 *(35)* | ✓ 0.1.40 | ✓ 0.1.40 |
| Sign in with a ChatGPT plan — chat and the hands' screen reading only, with the line about OpenAI's terms | ✓ 0.1.39 upstream's sign-ins (also Claude, Kimi, OpenRouter) | ✓ 0.1.40 upstream's Codex OAuth from the ways on (also Claude, Kimi, OpenRouter) *(32)* | ✓ 0.1.39 through the bundled runtime | ✓ 0.1.39 the runtime's `nanomuse chatgpt login` |
| A capability nobody configured has is one sentence naming who could (pictures, clips, the screen), never a raw error | ✓ 0.1.39 | ✓ 0.1.41 an empty Models row says what is missing and offers *Add a provider* *(32)* | ✓ 0.1.39 | ✓ 0.1.39 |
| Conversations belong to the account that synced them: another account's stay on the device, hidden, never pushed under the new key; a switch restarts the pull (contract C10) | ✓ 0.1.39 | ✓ 0.1.39 | ✓ 0.1.39 | ✓ 0.1.39 the runtime's lists |

## The agent in the chat

| Feature | Android | iOS | Desktop | Web |
|---|---|---|---|---|
| Status line says what it is on, never "Thinking" | ✓ | ✓ 0.1.32 *"is on it"* | ✓ | ✓ |
| Status line = the step's own words (`step`: *打开携程网站*), never the raw command | ✓ 0.1.33 | ✓ 0.1.33 | ✓ 0.1.33 | ✓ 0.1.33 |
| "Show the agent's steps", on by default since 0.1.37 (a stored off stays off) | ✓ 0.1.37 (`nm.show_steps`) | ✓ 0.1.37 (`nanomuse.show_steps`) *(2)* | ✓ 0.1.37 | ✓ 0.1.37 |
| Star asks at the relay's moments (`/v1/nudges`: sign-in · 3rd / 10th / 30th task · 7th / 30th day · a goal reached · a new look · allowance spent; 7 days apart, 4 per device; never in the first conversation). Every card has *I already starred* next to *Star on GitHub*; either ends the asks on that device for good | ✓ 0.1.35 | ✓ 0.1.35 *(3)* | ✓ 0.1.35 | ✓ 0.1.35 |
| First conversation: the app speaks first, asks what to call you, the model's `nanomuse-naming` fence becomes the naming card | ✓ | ✓ 0.1.34 | ✓ 0.1.35 *(25)* | ✓ *(39)* |
| First run: "Sign in — free" before anything else | ✓ | ✓ 0.1.32 *(4)* | ✓ | ✓ |
| Approval cards, three tiers, remembered grants; a Permissions page listing the remembered grants by risk tier, with Revoke | ✓ | upstream's | ✓ Settings → Permissions → *Standing grants*: the remote-control switch, the trusted devices and the hands' per-app grants under the phone's three tiers | ✓ |
| Approvals answered outside the app while the hands work | ✓ 0.1.33 capsule *Allow / Deny* | n/a *(10)* | ✓ 0.1.34 stage *Allow once / Always in app / Deny*, capsule when the window is behind *(17)* | n/a |
| Hand-over: a login / code / payment / CAPTCHA goes back to the person, the agent waits and resumes (holds) | ✓ 0.1.33 `hand_over` | — *(16)* | ✓ 0.1.34 *Your turn — Done*, *I'll take it* *(16)* | ✓ 0.1.34 drivable browser viewer, hold cards *(16)* |
| Face tap opens the agent page (Change avatar · Edit name · studio; Activity · Approvals · Daily · Soul & memory; share card) | ✓ | ✓ 0.1.34 | ✓ 0.1.34 | ✓ Muse page |
| Change the look from the chat (the same words, four candidates, pick by words, regenerate) | ✓ | ✓ 0.1.34 | ✓ 0.1.34 | ✓ studio intercept, reference picture 0.1.34 |

## Connectors, agents, devices

| Feature | Android | iOS | Desktop | Web |
|---|---|---|---|---|
| Connectors catalogue (75 remote MCP servers, sign in) | ✓ 0.1.32 *(5)* | ✓ 0.1.33 *(6)* | ✓ | — *(7)* |
| Services without dynamic registration (GitHub, Slack, Discord, …) ask for an OAuth client id | ✓ 0.1.33 | ✓ 0.1.33 | ✓ 0.1.33 | — *(7)* |
| MCP servers by hand (URL / command) | ✓ *Your own servers* under Connectors 0.1.33 | ✓ *Your own servers* under Connectors 0.1.33 | ✓ (harness) | ✓ |
| Connections shared across the account's devices (the profile's `connectors`; never a credential) | ✓ 0.1.34 | ✓ 0.1.34 | ✓ 0.1.34 | ✓ 0.1.34 *(18)* |
| Chat apps: Feishu · DingTalk · WeCom · Telegram answer as the agent (pairing codes, allowlists, deliver here) | — *(22)* | — *(22)* | ✓ 0.1.34 the web screen | ✓ 0.1.34 *Settings → Chat apps* |
| Skills | ✓ upstream | ✓ upstream | — *(8)* | ✓ |
| Coding agents (Cursor, Codex, Claude Code on the computers) | ✓ | ✓ 0.1.34 over the hub *(9)* | ✓ *Settings → Coding agents*, this computer first; announces and serves `coding.*` *(8)* | ✓ |
| Devices of the account, remote control, rename, forget | ✓ | ◐ list, Reach sheet 0.1.33 | ✓ | ✓ |
| Hub, outbound: the model reaches the account's other devices (`devices`, `device_*`, `delegate`, `@<device>`) | ✓ *Computers*, the reach offload | ◐ the Reach sheet by hand and `@device` to the hub — since round 9 also a tap on an online device in the account's Devices list, as on Android; no tool in the model's hands *(29)* | ✓ `reach.ts` | ✓ the runtime's `tools/devices.py` |
| Hub, inbound: the device answers the others (shell · files · open · screen · notify · task) | ✓ `HubActions` | ◐ info · open · notify · task; shell, files and screen answer *not supported* *(10)* | ✓ `actions.ts` | ✓ the runtime; a browser tab is not a device |
| Hands — the device's own screen as a hand | ✓ | n/a *(10)* | ✓ Linux X11 (Wayland *(21)*); macOS one window while the person keeps the mouse, per-app grants, glow and capsule out of the shots *(19)*; Windows to be tried *(31)* | n/a |
| Report a problem: one tap opens a GitHub issue | ✓ Settings → Account | ✓ About → *Report an issue* | ✓ the corner menu; under the shell a screenshot goes to Downloads and the issue opens filled in | ✓ Settings → Feedback |
| Installed and latest version, side by side (`nanomuse.cn/dl/index.json` first, GitHub second, a day's cache) | ✓ 0.1.35 Settings → Version | ✓ 0.1.35 Settings → Version | ✓ 0.1.35 About, Settings row | ✓ 0.1.35 Settings |
| A black capture is an error with the fix (Screen Recording, Wayland), never a picture | n/a | n/a | ✓ 0.1.33 | n/a |
| macOS permissions read back live; *Open System Settings* after an ask; Screen Recording relaunch notice | n/a | n/a | ✓ 0.1.33; 0.1.35: one row to switch on, *Try it* rows, a restart dialog when Screen Recording flips on; since 0.1.38 the row is *nanoMuse Computer Use*, the helper app *(26)* | n/a |
| Mini-Linux sandbox on the device | ✓ | ✓ upstream (iSH) | n/a — the runtime's own sandbox | n/a |

## Face, rooms, look

| Feature | Android | iOS | Desktop | Web |
|---|---|---|---|---|
| Avatar studio: generate, pick, pose; the face shared across devices | ✓ | ✓ 0.1.33 *(11)* | ✓ | ✓ |
| Motion clips for a drawn face (idle · working · waiting · happy; `wan2.2-i2v-flash`; *Animate the avatar after a change*) | ✓ | ✓ 0.1.35 | ✓ 0.1.35 header, sidebar, capsule | — *(27)* |
| Emoji faces | ◐ falls back to the dragon *(12)* | ◐ falls back to the dragon *(12)* | ✓ | ✓ |
| Theme colour swatches | — | — | — removed 0.1.33 *(13)* | — |
| Accent follows the avatar | ✓ | ✓ | ✓ | ✓ |
| Rooms: Feed · Ideas · Goals · Library | ✓ | ✓ 0.1.34 with a scheduler *(11)* | ✓ 0.1.34 on the phone's fence protocol | ✓ |
| Ideas by kind: chat · routine (at a time) · goal (a category) | ✓ | ✓ 0.1.34 | ✓ 0.1.34 the phone's list | ✓ 0.1.34 |
| First run: the phone's pages (sign in · password · which model answers · models · permissions · notifications · meet), then the shell; never skipped on a fresh install | ✓ | ✓ 0.1.34, notifications page 0.1.35 *(4)* | ✓ 0.1.35 kept by the host in `firstrun.json` *(25)* | ✓ onboarding |
| Feed opens on the intro card (*Write it now*), the first day is written after the first conversation, a daily routine at 08:00 | ✓ | ✓ 0.1.35 | ✓ 0.1.35 | ✓ 0.1.35 |
| Ideas prefilled with the curated list (`ideas.{en,zh}.json`, byte for byte, with a test) | ✓ | ✓ | ✓ 0.1.34; empty-when-bundled bug fixed 0.1.35 | ✓ 0.1.35 |
| Splash: wordmark and the person's own face, never the dragon | ✓ | ✓ system launch screen | ✓ 0.1.35 | n/a |
| Settings as Muse cards in one order (Models since 0.1.41 · Avatar · Computers · Appearance · … · Version; *Image & video models* kept as a shortcut) | ✓ | ✓ 0.1.35, Models first 0.1.41 | ✓ sections, Models right after General 0.1.41 | ✓ sections |
| Memory as a room | — settings page *(14)* | — | ✓ | ✓ |
| Stage / browser viewer while the hands work | ✓ stage | n/a *(10)* | ✓ the glow and the capsule while the hands work, the run's trajectory in the chat 0.1.40 (a live stage from 0.1.33 to 0.1.39); Allow/Deny, holds 0.1.34 | ✓ browser viewer you can drive 0.1.34 |
| Every working light breathes (2.4 s in, 2.4 s out), none runs; steady under reduce-motion | ✓ round 9: the stage's comet and scan line gone, the capsule's ring and bars breathe | n/a *(10)* | ✓ 0.1.40 | ✓ 0.1.40 |
| Quick chat (global shortcut) | n/a | n/a | ✓ | n/a |
| Widgets | ✓ upstream | ✓ upstream | n/a | n/a |
| Voice in: dictate into the composer | ✓ upstream | ✓ upstream | ◐ Web Speech where the shell has it; otherwise the Dictation page says what to use *(36)* | ◐ the browser's Web Speech *(36)* |
| Voice out: the reply read aloud | ✓ upstream TTS, sentence by sentence | ✓ upstream | — *(36)* | — *(36)* |
| Export: the chats and the agent's data as a file; the face card shared | ✓ `ChatExporter`, the share sheet | ✓ backup export, the share sheet | ✓ *Download your agent data* on the Memory page (a zip in Downloads) | ◐ the face card; no data export *(37)* |
| UI language | ✓ follows the system, 17 locales | ✓ follows the system, 9 locales | ◐ en · zh, the harness's General → Language row *(38)* | ✓ auto · en · zh-CN under Settings *(38)* |

## Open for a decision (the "next-next" list)

These are the gaps left open on purpose since 0.1.32 — either the platform makes them a
different design, or they are large enough that the call is the maintainer's. Numbers match the
notes above; a settled item keeps its number and says how it went.

1. **iOS · Data controls** — done in 0.1.33 (`NanoMuseDataControls.swift`).
2. **iOS · Steps.** The header line (and the face) are there since 0.1.33; the steps of the message
   still running stay visible even with the setting off, finished messages hide them. *Hide them
   too, now that the status line says what is going on?*
3. **iOS · Star after the first task** — done in 0.1.33, as a card pinned under the header (the
   message list is a UICollectionView; nothing can be placed under the last message). A cancelled
   turn counts as finished, the stream has no cancel signal. In 0.1.35 the card follows the
   relay's policy like everyone else (28): no ask in the first conversation, the 3rd task is the
   first moment.
4. **iOS · First run** — done in 0.1.34 (`NanoMuseFirstRun.swift`, the Android `needed / stage`
   logic). Shown to anyone without a Cloud account, so a person upgrading who only ever used their
   own key sees it once; *All settings* skips it.
5. **Android · OAuth connectors need a device test.** Discovery, dynamic client registration, PKCE
   and the token written into the entry's `Authorization` header compile and follow the desktop's
   flow line by line, but no connector was signed into on a device before 0.1.32 (no emulator on
   the build machine); the same goes for 0.1.33's client-id path (GitHub, Slack, …) and the
   browser hand-over. Key and open connectors are plain MCP entries and need nothing new. The
   token ends up in `servers.json` next to API keys, as the in-guest client reads it; refresh runs
   at app start and when the page opens, not in the background.
6. **iOS · Connectors** — done in 0.1.33 (`NanoMuseConnectors.swift`, the Android flow ported),
   with the same caveat as 5: compiled, not yet signed into on a device.
7. **Web · Connectors.** The runtime would have to run the OAuth flow itself and hold the tokens
   (the desktop does it in the harness host). The web app has MCP servers by hand. *Decision: run
   the flow in the runtime (`nanomuse mcp` already bridges connectors), or point the web app at a
   desktop on the account?*
8. **Desktop · Skills and coding agents pages.** The harness has its own skills, so a skills page
   would duplicate them: not done. The coding agents page is done: *Settings → Coding agents* shows
   this computer's CLIs and chats first, the account's other computers after, and the desktop
   announces and answers the `coding.*` hub actions itself (`src/coding.ts`), so a phone sees a
   computer with only the desktop app as a coding computer too.
9. **iOS · Coding agents** — done in 0.1.34 (`NanoMuseCoding.swift`, the hub's `coding.*`).
10. **iOS · Hands.** iOS does not let an app drive another; App Intents / Shortcuts are the door.
    Not planned as "hands". Settled in 0.1.36: the Settings row is there (*Hands — Not on iPhone*)
    and opens a page that says why, and what a computer of the account can do; the iPhone's own
    Muse takes `task` calls from the other devices while the app is open (`@iPhone …`).
11. **iOS · The Muse shell** — done in 0.1.33 on the iPhone; in 0.1.34 Feed and Goals are real
    (`NanoMuseScheduler.swift`: foreground catch-up, `BGAppRefreshTask`, a local notification at
    the set time), the iPad runs the shell too, the shell and header switches are in the nanoMuse
    settings page, and the studio draws through the relay or your own Bailian key. Left: a
    routine runs in the background only when iOS gives the refresh task a slot — the copy says
    so (*at the set time the phone reminds you to open it*); the hub route (a computer of the
    account runs them) is still the sure one. The iPad's layout is the iPhone's, larger —
    settled in 0.1.35: no split layout of its own.
12. **Android and iOS · Emoji faces.** A face set to an emoji on the web or the desktop shows the
    dragon on the phones. Small.
13. **Theme colour swatches** — settled in 0.1.33: removed from the desktop; one rule everywhere,
    the accent follows the avatar.
14. **Android · Memory as a room.** It is a settings page on the phone, a room elsewhere. Design
    call.
15. **Browser viewer on the desktop.** The trajectory in the chat shows the hands; a page viewer
    like the web app's is not there. Design call.
16. **Hand-over on the desktop and the web** — settled in 0.1.34, both: *holds* in the runtime
    (`nanomuse/agent/holds.py`; `hand_over` on `browser`, `computer_act`, `phone_act`; `POST
    /api/holds`, `/done`; `hold` events; the agent waits up to ten minutes and looks again). The
    desktop's stage shows *Your turn — Done* and *I'll take it*; the web's browser viewer can be
    driven (*Take over*, click, type, scroll, URL, *Done*). Left: iOS has no hands, so nothing
    to hand over there (10).
17. **Desktop · approvals outside the window** — settled in 0.1.34: the live stage carries
    *Allow once / Always in <app> / Deny*, and a small always-on-top capsule shows the same card
    when the main window is not in front. Left to check on a Mac: the capsule's `showInactive`
    must not steal focus from the app being driven — on the Mac task sheet
    (`docs/tasks/mac-check-0.1.36.md`, D).
18. **Connections shared across devices** — settled in 0.1.34: the profile's `connectors`
    (relay 0.17; merged per device, 64 at most, a key-like field name is a 400), four clients
    read and write it, the other devices' entries show as *Connected on <device> — sign in
    here*. The credential never leaves the device that minted it.
19. **Desktop · hands that do not fight the person** — settled for macOS in 0.1.34 the way the
    Codex app does it: *window mode* (`nanomuse/computer/mac_window.py`; `[hands] mode = auto`)
    captures one application's window and posts the events to its process, so the person keeps
    the mouse; each application asks once (*Let <Muse> use <App>?*). Elsewhere the screen is
    shared, with the UI-TARS-style glow and the overlays kept out of the shots. Left: Linux and
    Windows have no window mode (a virtual display or a second session would be the port — Linux
    first, cheapest); the macOS path is written against the Quartz APIs and must be tried on a
    Mac (Screen Recording fallback, AX-less clicks, Retina mapping, scroll direction). Settled in
    0.1.35: `auto` stays the default, with a fail-safe — when the Quartz layer itself fails (not
    "the window went away", which is retried every look) the hands fall back to the whole screen
    for the rest of that target and say so once; an explicit `window` mode keeps trying. Settled
    in 0.1.36 for the pointer itself: the desktop's hands are UI-TARS-desktop's operator moved
    into the Electron main process (`harness/desktop/src/operator.ts`, `@computer-use/nut-js`,
    loopback HTTP to the runtime's `desktop` backend), and the model's coordinates are pixels of
    the picture it saw, mapped once to the operator's screen (`nanomuse/computer/coords.py`) — the
    clicks that landed beside their targets on scaled displays are gone (≤1 px on a 4K display at
    scale 2). Left to try on a Mac and on Windows: the native addon in the packaged app, the
    coordinate space (points on a Mac), scroll units, ⌘ for `ctrl`, content protection — the Mac
    task sheet, F.
20. **Services without a public remote MCP server** — the chat apps are settled in 0.1.34 the
    way nanobot does it: 飞书, 钉钉, 企业微信 and Telegram are *channels* the agent answers in
    (`nanomuse/channels/`, the vendors' long-connection SDKs, no public address, pairing codes),
    which is what most people wanted from them. Still open as *connectors* (the agent reading or
    acting in the service): Zoom, LinkedIn, Zoho Invoice, WHOOP, 腾讯文档, 滴答清单, 网易邮箱, QQ
    邮箱, 微信读书 — each a bridge of its own over the vendor's REST API, one developer account
    per vendor. *Decision: which, if any, are worth a bridge?*
21. **Hands on Linux under Wayland.** The capture and the pointer need X11 or XWayland today; a
    Wayland session gives a black frame (now an error with the hint). Since 0.1.36 the operator
    says so itself (`/info` → `available: false`, *Wayland session … log in with Xorg*), and the
    Hands card shows the reason; UI-TARS-desktop has no Wayland path either. The portal route
    (`xdg-desktop-portal` ScreenCast + `libei`) would make it work natively, at the cost of a
    permission dialog per session. *Decision: worth it before the Linux desktop is promoted?*
22. **Chat apps on the phones.** The channels live in the runtime; the web app (and so the
    desktop) has the settings screen. Android and iOS would need an `/api/channels` client and
    the same card list (switch, fields, pairing codes, paired chats, Feishu QR) — the API and the
    strings are ready. *Decision: next version?* Also open: no vendor was connected end to end
    from the build machine (the SDK calls were checked offline against the real packages) — one
    test bot per vendor before announcing; Feishu sender names need `contact:user.base:readonly`;
    approvals from a chat are always *once*.
23. **Own-key presets and the chat default.** After a Bailian or OpenRouter key is saved, the
    provider's `/models` list decides what is offered; `deepseek-v4.1-flash` is not moved to the
    front automatically (only the Cloud group has `followPick`). *Recommendation: promote it when
    the list has it.*
24. **Relay billing of reasoning tokens.** Counted as completion tokens; when a provider reports
    them separately and the count exceeds the completion count they are added, otherwise taken
    as included. A provider that reports them separately *and* smaller would be under-counted.
    *Decision: keep the heuristic, or switch per provider?*
25. **Desktop · first run and first conversation** — settled in 0.1.35 after the phone: the host
    keeps `firstrun.json` and never skips the pages on a fresh install; the app speaks first
    (three scripted lines, no tokens), asks what to call you, and the model's `nanomuse-naming`
    fence becomes the naming card (`take_name` / `ask_user_question` are gone). Left, by design:
    the scripted lines are a client overlay, not stored messages; the address is a memory line
    rather than a `GLOBAL.md` edit; the gear on the first-run pages dismisses them for the
    session only.
26. **Desktop · macOS permissions** — re-audited in 0.1.35: TCC attributes the bundled runtime to
    the responsible process, so only *nanoMuse Desktop* has to be switched on (the words say so
    now; the runtime no longer appears as a second entry to hunt for). Since 0.1.38 the two grants
    belong to the helper app *nanoMuse Computer Use* instead ([desktop.md](desktop.md#macos-permissions)). Left to try on a Mac: the
    *Try it* rows after a fresh grant, the restart dialog when Screen Recording flips on, the
    capsule's `showInactive` (17), window mode's AX-less clicks and Retina mapping (19), the
    face click after 0.1.36's change (no drag region under the face at all; the face below the
    title-bar band) — all on the Mac task sheet, `docs/tasks/mac-check-0.1.36.md`, written so that
    an agent on a Mac can run it end to end and send the fixes back.
27. **Web · motion clips.** The clips are per device (drawn where the face lives: the phone, the
    iPhone, the desktop). The web app shows the still face. *Decision: draw them in the runtime
    too, or leave the web still?*
28. **Star asks · what counts.** The policy is the relay's (`/v1/admin/nudges`, console → Star
    asks) and reaches every client within a day without an update. Two small differences left:
    Android asks once per phone when the allowance is spent (the other clients the same); the
    first feed day is not written when the person changes the face during the naming conversation
    (the first run never reaches *done*). Small.
29. **One conversation on every device** — settled in 0.1.36 (contract C7 in `docs/cloud.md`): the
    text of the chats lives on the relay (`/v1/sync/*`, relay 0.19), on by default when signed in,
    with the switch and the delete under Data controls on every client; one main conversation per
    account; what a device started on its own (routines, goals, the feed, work for another device)
    stays on it. One thread since 0.1.37 (contract C8): the main chat on every device is the union
    of what was said on all of them in time order, the other devices' turns as read-only bubbles
    (*From Pixel 8*) the model reads too; a side chat from elsewhere is a chat on the device at
    once; the person's message goes up when sent, the reply at the turn's end; the whole history
    is backfilled on sign-in. The desktop appends the other devices' turns to the dsh session log
    (`user/message`, source `nanomuse-sync`) and dresses them in the browser. Left: the dsh plugin
    has no delete, so an archived session is not a tombstone, a message deleted elsewhere is hidden
    rather than removed from the log; switching sync off on one device reaches the others at
    their next push or pull (a `409`), not at once; on iOS a pulled message that arrives late sits
    after the local ones (the OpenMinis store appends). `@<device name>` runs a turn on another
    device — computers whenever online, phones while the app is open; on iOS the mention goes to
    the hub directly (no `delegate` tool there) and the iPhone answers `task` calls itself.
30. **iOS · composer, bubbles, header** — settled in 0.1.36 after the phone: the one-row pill,
    flat grey bubbles for the person, a floating translucent header. Left: on iOS 16–18 the
    transcript starts below the header's edge rather than scrolling under it (the UIKit list
    needs the inset passed down; to be tried on a device — the risk of covering the first message
    was not worth taking blind).
31. **Desktop · the operator on a Mac and on Windows.** Ported from UI-TARS-desktop and proven on
    Linux X11; the native addon, the coordinate space (points on a Mac, physical pixels on
    Windows), scroll units, ⌘ for `ctrl`, content protection of the glow are on the Mac task
    sheet (`docs/tasks/mac-check-0.1.36.md`, F). Wayland stays item 21.
32. **iOS · the ways card on the catalogue.** 0.1.39 gave the iPhone its account-scoped
    conversations (contract C10, `NanoMuseSync`) and the bundled `providers.json`, but the
    allowance card still offers the 0.1.34 presets and has no plan sign-in; the Android
    `AllowanceWaysCard` is the model (the region's lead, *more providers*, the plans, the
    one-sentence unavailable lines where a picker is empty). *Settled in 0.1.40:*
    `NanoMuseCatalogue` reads the bundled `providers.json` (or the relay's guidance),
    `NanoMuseWaysList` is the one list on the pinned card, the account page and the own-key
    sheet, and `NanoMuseVendorSheet` takes the key or runs the plan sign-in (ChatGPT through
    upstream's Codex OAuth, Claude, OpenRouter, Kimi's device code) and a local server's
    address. The one-sentence line where a picker (pictures, clips) is empty came in 0.1.41 with
    the Models page: an empty row says what is missing and offers *Add a provider*.
33. **iOS · the allowance card and the heads-up in the chat.** A turn the relay refuses with
    `allowance_exhausted` ends on iOS as upstream's error text; the ways live on the account page
    only, and `spend.warn` colours the bar there without a line in the chat. *Proposal:* a card
    pinned under the header the way the star card is (3) when the stream ends with that code,
    drawing the ways from `spend.guidance` (with 32); one line above the composer at 80 %, once per
    pool size, as the other three clients show it. *Settled in 0.1.40:* `NanoMuseAllowance`
    holds both; the shell pins `NanoMuseAllowanceCard` (with *Try again*), `NanoMuseChatCardsHost`
    shows the heads-up; no new link on `AIChatView.body`.
34. **Android · the ways from the relay's guidance.** `AllowanceWaysCard` reads the bundled
    `providers.json`; `/v1/me` carries `spend.guidance` (the region's providers, the plans, the
    caveats) and the card ignores it. *Proposal:* prefer `guidance` when the relay sends it, fall
    back to the catalogue — the web and the desktop already do; a few dozen lines in
    `AllowanceWaysCard.kt` and `NanoMuseCloud.kt`. *Settled in 0.1.40:* `Guidance.kt`
    parses it, `Ways.resolve` prefers it, the card and Settings → nanoMuse Cloud read it.
35. **Phones · 413, the remaining refusals and the operator's switches.** The phones' `describe`
    knows the allowance, the daily cap, the rate limit, a bad key, a disabled account and the
    upstream's trouble, but not `too_large` (413), `not_invited`, `too_many_in_flight` or
    `provider_busy`, nor relay 0.22's `service_paused`, `sync_paused`, `hub_paused`,
    `signup_closed` and `allowance_exhausted` with `paused: true` (the allowance card says *used
    up* where the relay says *paused*) — those reach the person as upstream's text or the relay's
    English sentence. Settled for the web and the desktop in 0.1.40 (`nanomuse/server/failures.py`,
    `harness/dsh-nanomuse/src/refusals.ts` — the reference sentences, en and zh). *Proposal:* the
    nine codes in both `describe`s with those sentences, the 413 one pointing at *New chat*, the
    paused allowance as a different lead on the same card; on iOS route a refused chat turn
    through `describe` too. Strings per locale on the phones. *Settled in 0.1.40* on both
    phones: `RelayRefusal` / `NanoMuseRelayRefusal` classify the reply, `describe` has every code,
    the card in the chat carries the button (*New chat* · *Sign in* · *Open Settings* · *Try again*).
36. **Voice on the desktop and the web.** Dictation leans on the Web Speech API, which the
    Electron shell does not ship (it is Google's service inside Chrome), so the desktop opens the
    Dictation page and the web works only in browsers that have it; neither reads a reply aloud.
    *Proposal:* speech in and out through the runtime (`/api/speech`), using a configured
    provider's models (Bailian's `paraformer` / `cosyvoice`, OpenAI's `whisper` / `tts`) with the
    person's own key or the relay — one implementation for both clients; the phones keep the
    system's engines.
37. **Web · data export.** The desktop's rooms host writes a zip of the agent's data
    (`/data/export`) to Downloads; the web app shares the face card and has Data controls, but no
    file. *Proposal:* `GET /api/data/export` in the runtime writing the same zip, a *Download your
    agent data* row under Data controls.
38. **UI language.** The phones follow the system (17 and 9 locales), the web has an in-app switch
    (auto · en · zh-CN), the desktop has English and Chinese through the harness's language row.
    *Proposal:* the desktop's `locales.ts` grows the phones' languages as people ask, de and ja
    first; an in-app override on the phones is upstream's call.
39. **Web · the first conversation.** Done the phones' way, with the runtime owning the state:
    the phase machine, the prompt addendum and the saving are `nanomuse/server/firstrun.py`
    (state in `firstrun.json` beside the profile), the fence helpers `nanomuse/fences.py`, the
    routes `/api/firstrun*`, the `firstrun` socket frame; the chat speaks the three lines and
    draws the chooser (`web/src/components/FirstConversation.tsx`), and the first-run list lost
    its *Meet your nanoMuse* page. The address goes to the profile and to memory as *Call them:
    …* (the runtime has no USER.md). The identity form stays under Settings for later changes.
    One addition to the contract: the runtime keeps the language *Start* was pressed in
    (`lang`), so the addendum quotes the opening in the words the person saw.
    [web.md](web.md#the-first-run-and-the-chats-opening) has the walk-through.
40. **Models page, four slots (0.1.41).** Settled on Android, iOS and the desktop as one page
    with the *Use it for* card after a key is saved and *Use nanoMuse Cloud this time* on a
    failed own-key turn; the web console has the same four slots on *Connections* (the runtime's
    `PUT /api/connections/gui`, `/image`, `/video` and *Automatic* on each), but no *Use it for*
    card and no one-turn retry on the account: the own-key form sets the chat provider, and a
    failed turn shows the failure. Left on iOS: the pictures and clips pickers list, besides
    nanoMuse Cloud, only own providers on a DashScope host (Alibaba Cloud Bailian), since the
    iPhone's image and clip code speaks DashScope's API only. *Proposal:* the card and the button
    on the web, and the OpenAI image shape on the iPhone, when someone asks.

## Keeping this true

- The desktop's connectors catalogue is the source (`harness/dsh-nanomuse/src/connectors-catalogue.ts`);
  `node scripts/connectors-json.mjs` writes the Android asset and the iPhone's bundled copy,
  `--check` (in the harness workflow) fails when either is stale.
- The own-key provider catalogue is `nanomuse/llm/providers.json`; `node scripts/providers-json.mjs`
  writes the desktop's, the relay's and the phones' copies and `--check` fails when one is stale.
  A new provider, a changed endpoint or a capability lands there and nowhere else.
- Relay-facing code mirrors the same wire format on every client: `nanomuse/cloud.py` (runtime),
  `harness/dsh-nanomuse/src/relay.ts` (desktop), `io.github.nanomuse.cloud.NanoMuseCloud` (Android),
  `NanoMuse/NanoMuseCloud.swift` + `NanoMuseAccount.swift` (iOS). A new relay field lands in all four.
- The relay's refusal codes (`docs/cloud.md`) become sentences in four places: `nanomuse/server/failures.py`
  (runtime and web), `harness/dsh-nanomuse/src/refusals.ts` (desktop — the host rewrites the failure,
  the client draws the card), `NanoMuseCloud.describe` on Android and on iOS. A new code lands in
  all four, with the sentence in every locale the client has; the desktop's `tests/refusals.test.mjs`
  and `tests/refusal-card.test.mjs` are the shape of the test to copy.
- The star asks follow one policy everywhere — the relay's `/v1/nudges` (contract C1 in
  `docs/cloud.md`), with the same defaults built into every client: a *task* is a turn the person
  started that got a reply, never the first conversation, a routine, a feed post or a goal
  check-in; once per moment, `cooldown_days` apart, `max_asks` per device, never again after
  *Star on GitHub* (`nm.star.*` / `nanomuse.star.*`). Every card also offers *I already starred*;
  it sets the same flag, so no ask comes back on that device whatever the cooldown and the asks
  left, and any *Star on GitHub* row in Settings or About counts as done too. The flag is per
  device: the account has no place for small settings to sync, so another device still asks
  until it is told once. Clients: `nanomuse/nudges.py`,
  `harness/dsh-nanomuse/src/nudges.ts`, `web/src/nudges.ts`, `io.github.nanomuse.community.Nudges`,
  `NanoMuse/NanoMuseNudges.swift`.
- The release check reads the same two sources in the same order on every client:
  `https://nanomuse.cn/dl/index.json`, then GitHub's `releases/latest`; a day's cache; the row
  always shows the installed version too.
- Conversation sync speaks one wire format (contract C7 in `docs/cloud.md`) from four clients and
  one relay: `cloud/nanomuse_cloud/sync.py`, `nanomuse/sync/` (runtime and web), `harness/dsh-nanomuse/src/sync.ts`
  (desktop), `io.github.nanomuse.sync` (Android), `NanoMuse/NanoMuseSync.swift` (iOS). Every client
  applies a page's conversations before its messages and moves its cursor only on a pull; every
  client pushes the person's lines and the final answer only — never tool steps, tool results or the
  system prompt — and leaves routines, goals, the feed and work for another device at home.
- `ideas.en.json` / `ideas.zh.json` are one file four times (Android assets, iOS Resources,
  `harness/dsh-nanomuse/assets`, `web/src/ideas`); the harness and web tests fail when a copy drifts.
