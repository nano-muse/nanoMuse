# iOS

nanoMuse on the iPhone is the iOS half of OpenMinis 1.13 under nanoMuse's name, built by CI on a
Mac runner and handed to TestFlight. This page says what is in the tree, how it is built, what
the TestFlight pipeline needs, and what is still to be ported from the Android app.

**Status.** The tree, the branding, the nanoMuse Cloud sign-in, the hub client and the pipeline
were written on a Linux machine. The app **builds, signs and is on TestFlight**: the first build,
0.1.31 (2), went through the *iOS · TestFlight* workflow on 2026-10-03; 1.0.0 is build 16, which
passed Apple's beta review, so the public link
(`https://testflight.apple.com/join/ZHexbDqc`) installs it; 1.0.1 is build 18, submitted to the
review on 2026-10-10 (*Where it stands* below). The testers' reports have driven the fixes in the release
notes (the composer, onboarding, sign-out); the Devices section and notifications from other
devices still have the fewest hours on a real device. The first archive taught the pipeline
that automatic signing wants a registered device, which is why it signs manually now.

## Where it lives

`android/` is the whole OpenMinis repository as a `git subtree`, not just the Android app. The
iOS half was deleted when the project started and is now restored **inside that subtree**, at
`android/src/ios`, together with the iOS dependency scripts under `android/deps/` and the
`android/deps/ish` submodule (the ARM64 iSH fork). Putting it back where upstream keeps it, rather
than in a second subtree, is what keeps `git subtree pull` working for both platforms at once.

```
android/src/ios/                 the Xcode project: Minis.xcodeproj, app, extensions, tests
android/src/ios/NanoMuse/        ours: nanoMuse Cloud client and screens (a synchronized folder
                                 of the Minis target; drop a .swift file in, it is compiled)
android/src/ios/fastlane/        the TestFlight lane
android/deps/build_lame.sh       LAME → FFmpeg → iSH → Alpine rootfs → rclone, in that order
android/deps/build_ffmpeg.sh
android/deps/build_ish.sh
android/deps/prepare_alpine_rootfs.sh
android/deps/build_rclone_ios.sh
scripts/rebrand.py               the `ios()` step: ids, names, versions, strings, links, colours
scripts/gen-ios-icons.py         the app icon and the four alternates, from assets/brand/
.github/workflows/ios-testflight.yml
```

The rules of [CONTRIBUTING.md](../CONTRIBUTING.md) apply unchanged: new code in new files (here:
the `NanoMuse/` folder), an edit inside an upstream Swift file carries a `// nanoMuse:` comment,
and rebranding is the script, never a hand edit.

## What is nanoMuse here

Applied by `python scripts/rebrand.py` (idempotent; run after every upstream pull):

- **Identity.** Bundle ids `io.github.nanomuse.app` (+ `.ShareExtension`, `.AgentWidget`,
  `.FileProvider`), the app group `group.io.github.nanomuse.app`, the iCloud container
  `iCloud.io.github.nanomuse.app`, the background-task, UTType and URL-scheme ids that carry the
  bundle id. Unlike Android there is no source-package constraint on iOS, so the whole family
  moves. The URL schemes the system knows the app by are `nanomuse` (the share extension opens
  `nanomuse://share`) and `nanomuse-mcp`, so a phone that also has OpenMinis installed never has
  two apps claiming one scheme. Inside the app, links stay `minis://…`: that is upstream's
  contract with its own sandbox, the system prompt and the model; a `nanomuse://` link arriving
  from the system is read as its `minis://` form (`NanoMuse/NanoMuseOwnScheme.swift`), and a
  button of ours outside the chat opens such a link through the deep-link router, never through
  the system.
- **Names.** Display name nanoMuse, "Share to nanoMuse", "nanoMuse Files"; "Minis" → "nanoMuse"
  in Swift string literals, in `Localizable.xcstrings` (keys renamed, all nine translations
  updated) and in the Info.plist usage descriptions in every language. The OpenRouter
  `HTTP-Referer` keeps pointing at OpenMinis, as on Android: it is attribution, not identity.
- **Versions.** `MARKETING_VERSION` and `CURRENT_PROJECT_VERSION` follow the Android
  `versionName` / `versionCode`; CI overrides the build number with the run number.
- **Look.** AccentColor `#015CFB` / `#58A6FF` instead of iOS blue; the one-stroke N as the app
  icon (white tile, brand gradient; a dark tile for the dark appearance) and as the four skins of
  the in-app icon picker; the agent's header glyph 🐾 instead of ✨.
- **About.** Links to this repository and its issues, the privacy page, nanoMuse's own tagline,
  and a Credits section: based on OpenMinis 1.13 (GPL-3.0), not affiliated with Meta.

Ours, in `NanoMuse/`:

- **nanoMuse Cloud.** *Providers* opens with a "nanoMuse Cloud" row: a phone number or an
  e-mail address, a code, and the relay ([cloud.md](cloud.md)) is an ordinary OpenAI-compatible
  provider in the app, with a model group of its own that becomes the default when there is none.
  Same wire format and the same rules as the Android client (`io.github.nanomuse.cloud`): one
  instance per relay, nothing of the user's own replaced, a 401 on refresh removes the provider
  (and keeps the account's data aside — Contract C12 below).
  Any build can point at another relay (*Use a different server*, below). Since 0.1.32 the page is the whole account — the
  password as the other way in, a friend's invite code, the pool in yuan with the ways on when it
  runs low (your own key, an invitation, a star once), usage by kind and by model, the devices
  holding a key, the timeline, deletion — the same sections as the phone's `CloudAccountScreen`.
- **The agent's steps, the status line.** *Settings → Chat → Steps* keeps the tool capsules out of
  finished messages unless asked for; the typing line reads *〈name〉 is on it*, not *is thinking*.
  Both are one-line edits in upstream's `AssistantBlockView` / `ContentView`, marked `// nanoMuse:`.
- **The Muse shell (0.1.33; iPad too since 0.1.34).** `NanoMuseRoot` replaces upstream's
  `ContentView` at the root; *Settings → nanoMuse* has the two switches (*Muse home*, *Face and
  name in the chat header*), and the OpenMinis layout stays one tap away in the drawer. The chat's
  navigation title becomes **face · name · status line** (`NanoMuseHeader.swift`): the status
  reads *waiting for you* while a question or an approval is up, then the running tool's
  `tool_title` — the model's own words for the step, *打开携程网站* — then *writing the reply*,
  then *On it: 〈brief〉*, and the model's name when idle; while a new face is being drawn it
  reads the avatar flow's line. The face (`NanoMuseFaces.swift`, the drawn face from Application
  Support or the dragon from the bundle, five moods with the breath, bob, tilt, pop and shake of
  the other clients) is tapped into **the agent's page**. The drawer holds the sessions, search,
  a new side chat, *Pin as the main chat*, *All chats* and the nanoMuse settings; it opens from
  the round button and, on the main chat, from a swipe in at the left edge
  (`NanoMuseEdgeSwipe.swift`, a screen-edge pan on the window, as Android's drawer on the Chat
  tab; a pushed side chat keeps the system's back swipe).
- **The agent's page (0.1.34)** (`NanoMuseAgentPage.swift`, Android `ui/profile`): the big face
  with the pen badge (*Change avatar* puts "Change your avatar to " in the main chat's composer,
  *Edit name*, *Avatar studio*), the name, *online*, and four panes — **Activity** (what you asked
  and what the agent did, from the last two days of sessions), **Approvals** (the standing
  "always allow" answers, revocable), **Daily** (the routines and the goal check-ins with their
  next run, *Manage routines*), **Soul & memory** (SOUL.md and GLOBAL.md, editable) — and the
  share sheet (`NanoMuseAvatarShareSheet`, Android `ui/avatar/AvatarShareSheet.kt`).
- **The avatar, from the chat (0.1.34)** (`NanoMuseAvatarFlow.swift`, Android `avatar/AvatarFlow.kt`):
  "换成一只橘猫" / "change your avatar to a red panda" is read before the model sees it (the same
  regexes, tested in `MinisTests/NanoMuseLogicTests.swift`); four candidates come up as a card in
  the chat, picked by tap or by words (*the second one*, *第三个*, *regenerate*); then *Finalizing
  poses…*, the new face on, the profile pushed, a line in the memory, the share card. Through the
  relay with a cost card first (`/v1/estimate`), or through the person's own Bailian key
  (`NanoMuseImageGen.swift`, DashScope's native image endpoint) when the phone has one; the studio
  (`NanoMuseAvatarStudio.swift`) uses the same path and lets the image model be picked.
- **The scheduler (0.1.34)** (`NanoMuseScheduler.swift`): routines — a label, a prompt, a time,
  daily / weekdays / once or every N hours — run as a headless turn in a conversation of their own
  (`NanoMuseHeadless`). Honestly: the iPhone runs them when the app is open (every due one on
  becoming active), asks iOS for a `BGAppRefreshTask` (`io.github.nanomuse.app.scheduler`) when
  it goes to the background and runs what is due if iOS grants it, and posts a local notification
  at each due time (*Check-in: 〈goal〉 — open to run it*) whose tap opens the conversation. Every
  piece of copy about routines says so. *Settings → nanoMuse → Scheduled tasks* lists them all,
  the goal check-ins and the feed's included.
- **Goals (0.1.34)** (`NanoMuseGoals.swift`, Android `goals/`): *Create a goal › category* sends
  the opener to the main chat with a system addendum for a few turns; the model's
  ` ```nanomuse-goal ` block becomes the goal and its check-in routine, ` ```nanomuse-goal-update `
  blocks move the progress; cards in the chat (*Goal created*, *Goal update*), the Goals room
  with progress, steps, pause / check now / done / delete, and the routines beneath.
- **Feed (0.1.34)** (`NanoMuseFeed.swift`, Android `feed/`): a daily routine writes a few short
  posts from the memory, the diary and the goals into `feed/<day>/<n>.md` with front matter; the
  ` ```nanomuse-feed ` fence is how the model hands them over. The Feed room shows them by day,
  *Discuss* opens a side chat on the post, the sliders hold what the feed is about, the time, the
  switch and *Write it now*. **Ideas** gained *Create routine* (scheduled at the idea's time, the
  editor opens) and *Start goal* beside *Send to chat*.
- **First run and settings (0.1.34)** (`NanoMuseFirstRun.swift`, `NanoMuseSettings.swift`,
  `NanoMuseCoding.swift`, `NanoMuseSystemFiles.swift`): the four pages of the Android first run
  (welcome → sign in — free → a password once for a fresh account → which model answers → meet
  〈name〉), with *I have my own API key* opening the own-key sheet (the whole catalogue —
  see *Your own key* below), and the first conversation afterwards (the
  opening lines, "what should I call you?", the name chooser from the model's ` ```nanomuse-naming `
  block, GLOBAL.md and SOUL.md written). *Settings → nanoMuse*: the account, **Coding agents**
  (Cursor / Codex / Claude Code sessions on the computers of the account over the hub's
  `coding.*` actions, a message to any of them), **Scheduled tasks**, **System files** (SOUL,
  GLOBAL, the diary, the feed's instruction, the routines' schedule, *Import memory* from another
  assistant), Connectors, Data controls, the two shell switches, *Show the welcome again*.
- **Models (0.1.34)** (`NanoMuseModels.swift`): the relay's menu opens on `deepseek-v4.1-flash`
  (the one marked recommended *for chat*; `qwen3.8-27b` is the hands' model and never the chat
  default); a pick made in the chat's picker moves to the front of the Cloud group so new chats
  follow it, as Android's `followPick`. DeepSeek ids are text-only unless they name `v4.1` or
  later, `vision` or `ocr` — a `// nanoMuse:` step at the top of `LLMModel.withInferredModality()`.
- **Models as four slots (0.1.41)** (`NanoMuseModelSlots.swift`, `NanoMuseModelsView.swift`;
  Android `ui/models/ModelsScreen.kt`): the first card of *Settings → nanoMuse* is *Models* and
  opens four rows — *Chat*, *Operating the screen* (disabled on iPhone, *Not on iPhone*, *Your
  computer uses its own setting.*), *Making pictures*, *Making clips* — each showing
  `<provider> · <model>` and opening a picker grouped *nanoMuse Cloud* first (the relay's
  recommended one marked *Recommended*) and then one group per provider of your own that can do
  it; an empty row says what is missing and offers *Add a provider*, and so does the page's last
  row; under the pictures and clips pickers a key the catalogue says can draw but the phone
  cannot drive (`NanoMuseModelSlots.notDriven`: only a DashScope host is) is named in one
  sentence, *Not offered here: …*, with where it does work. Picking a chat model sets the default group for new chats (a group of ours for that
  provider, the pick first; a mixed group you made becomes the default as it is) and moves the
  main chat's binding with it (`NanoMuseModelSlots.mainChatFollows`: the main chat is never a
  new chat, so on 0.1.41 it stayed on nanoMuse Cloud after a key of your own was chosen while
  side chats answered through the key); the page says *Applies to the main chat and to new
  chats; a side chat keeps its model.*; a pick made in a chat's own picker sticks the same way,
  for any provider, not only Cloud. Pictures and clips resolve in one order — your choice, else the chat
  provider's own default when it is a Model Studio key that draws, else nanoMuse Cloud when
  signed in, else the first key that can — so Cloud is no longer passed over for a Bailian key
  you did not pick; the image and video models come from the catalogue's `defaults`, not from
  names in the code. The pictures and clips pickers open with an *Automatic* entry (*Currently
  〈provider · model〉*) that forgets the stored choice and lets the slot follow that order
  again; the clips picker keeps *Off* under it. A group shows at most eight rows (the
  provider's catalogue default for the slot first, then the chosen model, then the rest as
  the list came) and ends in *Show n more* when it has more; once the groups together hold
  more than eight, a *Search models* field under the Automatic row filters every group live
  by model id or display name, every match shown, groups without one hidden, *No model
  matches* when nothing fits (`NanoMusePickerList`, tested in `NanoMuseModelSlotsTests`).
  After a key is saved, `NanoMuseVendorSheet` shows *Use it for*: one switch
  per slot the key covers (pictures and clips only on a DashScope host, the screen never on
  iPhone), all on; *Use it* moves the ticked slots to the provider's defaults, *Not now* changes
  nothing, and saving no longer switches anything by itself. When a model of your own fails, the
  failure card (and upstream's plain error) gains *Use nanoMuse Cloud this time* while signed
  in: the retry runs on the relay's chat model (`NanoMuseCloudOnce`, read at the top of
  `resolveCurrentEntry()`), and no slot changes. The relay's menu is kept on the phone at sign-in
  and refreshed when the page opens. *Image & video models* stays as a shortcut with the animate
  toggle and the clip buttons.
- **Connections across devices (0.1.34)** (`NanoMuseSharedConnectors` in
  `NanoMuseConnectors.swift`): the profile's `connectors` list says which device connected what
  (id, label, address without the query string, how it signs in, enabled, when, the device) and
  never a token; this phone puts its own entries, reads the others' back, and the Connectors page
  lists them under *On your other devices* — *Connected on 〈device〉 — sign in here to use it on
  this phone*. The ways-on card in the account follows the region: Bailian first in mainland
  China, *Sign in with OpenRouter* first elsewhere.
- **Connectors** (`NanoMuseConnectors.swift`): the desktop's catalogue from the bundled
  `connectors.json` (`node scripts/connectors-json.mjs` keeps it current, `--check` in CI), the
  MCP authorization flow (initialize → 401 → protected-resource metadata → authorization-server
  metadata → RFC 7591 registration → upstream's `MCPOAuthController`), key / open / auto services,
  and the client-id ask with the callback address to copy for the eight services that register no
  clients. The Settings row that was *MCP Integrations* is **Connectors**; *Your own servers* at
  its end is upstream's MCP page.
- **Data controls** (`NanoMuseDataControls.swift`): the relay's switch, the kept-turns count, the
  privacy page, deletion with a confirmation. **Reach** (`NanoMuseReach.swift`): a sheet per device
  of the account — open a link, send a note, a shell line, a screenshot — over the hub.
- **When the provider cannot be reached** (`NanoMuseProviderReach.swift`,
  `NanoMuseProviderReachCard.swift`): a failed turn whose error is the transport's — *Could not
  connect to the server*, *A server with the specified hostname could not be found*, a TLS or
  timeout line — or OpenAI's *region not supported* shows a card instead of the red banner: what
  happened, what helps (a VPN, the proxy under *Settings → Network*, another provider with a key
  of your own), *Try again*, the raw line behind *Details*. `LLMError` appends the failing host
  as `[host: …]` to a network error so the card can name it; the 401/403/429 whose bodies
  `mapHTTPError` drops are kept for a few seconds by `NanoMuseReachSignal` and written into the
  message as a canonical `nm_reach:` line by `friendlyErrorMessage` — an expired ChatGPT
  sign-in reads *Sign in again*, a spent plan window *The ChatGPT plan has nothing left for now*
  with OpenAI's sentence and the reset time. The same kinds, lines and rules as Android's
  `ProviderReach`.
- **When the relay refuses a turn** (`NanoMuseRelayRefusal.swift`,
  `NanoMuseRelayRefusalCard.swift`): every refusal nanoMuse Cloud sends is one plain sentence in
  the phone's language and the button that fits — never a status code, the relay's JSON or
  upstream's *Rate limited*. `NanoMuseReachSignal` hands each non-2xx reply of a model call to
  `NanoMuseRelaySignal` first (the same existing `// nanoMuse:` spot in `mapHTTPError`, nothing
  new in upstream's files); a reply with `type: nanomuse_cloud` or one of the relay's codes — or a
  bare 413 / 401 / 5xx from the relay's host — becomes a canonical `nm_relay:` line in the
  message, which `NanoMuseProviderReachCard` draws as the refusal card. The sentence is
  `NanoMuseCloud.describe`'s, the same the sign-in and account pages use, in all nine locales:
  `413 too_large` → *That message is too large for the model. Shorten it, leave out some
  attachments, or start a new chat.* with *New chat*; `400 content_rejected` (the provider's
  content check declined the words; also a provider's own `DataInspectionFailed` on a key of
  one's own) → *The model provider's content check declined this request. Try different words,
  or start a new chat if it keeps happening: the words it objects to can be earlier in the
  conversation.* with *New chat* and *Try again*, and the compaction's split-retry
  (`isSegmentRetryableError`) leaves it alone, since the same words come back refused however
  small the request; an error the relay puts inside a stream (`data: {"error": …}` on a 200)
  now ends the turn with its card instead of an empty reply (a `// nanoMuse:` spot in
  `OpenAIProvider`'s stream loop); `401 bad_key` / `account_deleted` → *Sign
  in*; `403 not_invited` / `account_disabled` / `signup_closed` → *Open Settings*; `429
  too_many_in_flight` / `locked` / `rate_limited` and `provider_busy` (with the wait from
  `retry_after`) → *Try again*; `404 model_not_offered` → *Open Settings*; `503 service_paused`,
  `sync_paused`, `hub_paused` and any 5xx or empty answer → *Try again*.
- **The allowance in the chat** (`NanoMuseAllowance.swift`, `NanoMuseAllowanceCard.swift`;
  Android `AllowanceSignal` + `AllowanceWaysCard`): a turn refused with `429 allowance_exhausted`
  or `daily_cap` pins a card under the chat header the way the star card is pinned (the shell's
  top inset, no new link on `AIChatView.body`): the lead — *The free allowance is used up.*,
  *Today's share …*, or with `paused: true` (relay 0.22) *paused on this relay for now — not
  used up* and that what is left stays as it is — then the ways on and *Try again* (the open
  chat's last turn once more). At 80 % of the pool (`spend.warn` from `/v1/me`) one line sits
  above the composer in `NanoMuseChatCardsHost` — *Nearly used up: ¥… of ¥… left …* — once per
  pool size (a new grant says it again), waved away with the ×; the card replaces it.
- **Your own key** (`NanoMuseCatalogue.swift`, `NanoMuseVendorSheet.swift`,
  `NanoMuseOwnKeySheet` in `NanoMuseModels.swift`; [own-key.md](own-key.md)): the vendors are
  the bundled `NanoMuse/Resources/providers.json` (`node scripts/providers-json.mjs` keeps it
  current, `--check` in CI) — and the relay's `spend.guidance` first when it sent one (relay
  0.21; also beside a `429 allowance_exhausted`), kept in `UserDefaults` between runs, so a
  vendor added on the relay shows before the app is updated. `NanoMuseWaysList` is the one list
  on the pinned card, Settings → nanoMuse Cloud and the own-key sheet: *Use your own model key*
  — the region's lead first (Alibaba Cloud Bailian on the mainland, OpenRouter and OpenAI
  elsewhere), three at a time behind *More providers*, every row saying what it covers (*chat ·
  screen · pictures · clips*), *Get a key* opening the vendor's key page, *Add* opening
  `NanoMuseVendorSheet` on that vendor (the key pasted, the instance added with the vendor's
  endpoint and `/v1` setting, its models fetched, a group named after it the default when there
  was none); *A subscription you already pay for* — ChatGPT through upstream's `CodexOAuthManager`,
  Claude, OpenRouter, Kimi's device code through `KimiDeviceLoginSheet` — with the line under the
  ChatGPT row that OpenAI's terms cover a plan inside OpenAI's own Codex, that other apps have had
  this access cut off before (OpenCode, January 2026), and that an API key works if it stops (the
  relay's own wording when it sent one); *On a computer of your own* — Ollama, LM Studio, vLLM —
  takes the address. No vendor is recommended.
- **Network** (`NanoMuseProxy.swift`, `NanoMuseNetworkView.swift`, *Settings → nanoMuse →
  Network*): the HTTP proxy for own providers — host, port, optional user name and password, off
  by default, in `UserDefaults` on this phone only. `URLSession` has no per-host proxy switch, so
  the proxy reaches a session as a proxy auto-configuration script in
  `connectionProxyDictionary` that answers the proxy for the catalogue's hosts, `chatgpt.com`,
  `auth.openai.com` and the provider instances' custom hosts (never the relay's, never a LAN
  address) and `DIRECT` for the rest; `NanoMuseProxy.apply(to:)` is one line in each of upstream's
  provider sessions, `NanoMuseProxy.session` stands in for `URLSession.shared` on the Codex
  sign-in and the model list. The credentials go to the shared `URLCredentialStorage` for the
  proxy's protection space. *Test* fetches `https://chatgpt.com/` through the proxy as entered.
- **The phone's chrome (0.1.35)** (`NanoMuseChrome.swift`, `NanoMuseAppearance.swift`, Android
  `ui/chat/MuseHeader.kt` and `ui/settings`): the Muse header — the face disc, the name pill with
  the live status line under it, round drawer and ••• buttons — on the chat and on Feed, Ideas,
  Goals and Library; the side drawer after Android's; the agent's grey bubble for its replies
  (`NanoMuseAssistantBubble` in `NanoMuseChatCards.swift`); the agent page's toolbar as round
  buttons; *Settings → nanoMuse* rebuilt as Muse cards in the Android order
  (`NanoMuseSettingsHomeView`: Image & video models, Avatar, Computers, Appearance — avatar size,
  the model under the name, the steps, the theme — Notifications, Account, Coding, Scheduled
  tasks, Shared folders, Chat files, System files, Version). A `nmOnChange` helper keeps
  `onChange` on iOS 16, the app's deployment target.
- **Motion clips (0.1.35)** (`NanoMuseVideoGen.swift`, `NanoMuseAvatarMotion.swift`,
  `NanoMuseMediaModels.swift`; Android `avatar/VideoGen.kt`, `avatar/AvatarMotion.kt`): a drawn
  face gets four 4-second clips — idle, working, waiting, happy — from `wan2.2-i2v-flash`
  (DashScope's async API through the relay, or your own Bailian key), the phone's prompts word
  for word, kept per device under `avatar/motion/`; the face plays them with an `AVQueuePlayer`
  and an `AVPlayerLooper` (suspended in the background), the dragon's clips come from the bundle.
  *Image & video models* lists the models, *Animate the avatar after a change* (on by default)
  and *Make / Redo clips*; the studio's cost estimate counts the clips.
- **Version, star asks, the feed's first day (0.1.35)** (`NanoMuseUpdateCheck.swift`,
  `NanoMuseNudges.swift`): the Version row shows the installed build and the latest release
  (`nanomuse.cn/dl/index.json` first, GitHub second, a day's cache — *Latest 0.1.x — you have it*
  / *0.1.x is out* / *Could not check — tap to try again*). The star asks follow the relay's
  policy (`/v1/nudges`, `nudges` in `/v1/me`, the same defaults built in): never in the first
  conversation, then the 3rd / 10th / 30th task (`NanoMuseStarWatch`: a person-started session
  leaving `activeSessions` without an error), the 7th / 30th day, a goal reached, a new look,
  sign-in, the allowance spent — seven days apart, four per phone — as a card pinned under the
  header (the message list is a UICollectionView, so nothing can be placed under the last
  message); the card's sentence is the one set in the relay's console (`star.text`, `star.text_zh`
  for a Chinese UI) when there is one, else the app's own line for the moment — the title and the
  buttons stay the app's. The Feed opens on the intro card, says when the daily routine runs while it is
  empty, and writes its first day after the first conversation; a Notifications page joined the
  first run.
- **The composer (0.1.38, 0.1.40)** (`NanoMuseShell.swift` → `NanoMuseHomeView.body`,
  `NanoMuseChatModifiers.swift`, `NanoMuseComposerField.swift`, `NanoMuseComposerWatch.swift`,
  `NanoMuseComposerCheck.swift`, the `// nanoMuse:` lines in `Views/Chat/AIChatView.swift`). Four
  releases reported a chat with no input field — 0.1.36 and 0.1.37 on the maintainer's iPhone after
  the first conversation's naming, 0.1.39 on the iPad — and the 0.1.37 watchdog, the 0.1.38 native
  field and the 0.1.38 fail-safe (a second host when the overlay reported nothing) were all written
  against screenshots of a composer that was, in fact, there. What the maintainer saw in the end:
  the field shows when the app opens and is gone for good once the keyboard has been dismissed; the
  0.1.36 screenshot has the top edge of the composer peeking out above the bottom bar. The shell's
  bottom bar was a `safeAreaInset` on the `NavigationStack`'s ancestor, hidden while the keyboard is
  up; the chat respected that inset at launch and no longer after the bar had left and come back,
  so the whole chat ran under the bar and the composer — bottom-aligned, laid out, healthy by every
  measure the watchdog had — sat behind it. Since 0.1.40 the **bar is a row under the rooms** (a
  `VStack`, as on Android), and the composer column (the cards, the tool strip, the input bar) is
  likewise **a row under the message list**: `NanoMuseComposerHost` is a plain `VStack`, the list is
  passed a bottom inset of 0, the `/` and `@` popup is an overlay of the list's bottom edge and so
  stands on the column's top edge by layout. Nothing lies over the UIKit list and there is no
  second host to switch to. The watch stays as the last net (a column that detaches or measures 0
  while the chat is on screen is rebuilt through `.id(rebuildTick)`, at most twice per appearance so
  a mis-measured healthy composer cannot take the keyboard away repeatedly), and it keeps what it
  sees: **Settings → Appearance → Composer check** draws a red frame around the column (the probe
  view in its background) and writes a report — the window and its safe area, the column's frame,
  every UIKit ancestor of the probe with its frame, hidden flag and alpha, the text fields and
  collection views in the window, the watch's events — with a *Copy* row for a bug report. That
  page is the view hierarchy a device can give without a Mac. The pill's field is SwiftUI's own
  `TextField(axis: .vertical)` with `@FocusState` and `lineLimit(1...6)`, not upstream's
  `UIViewRepresentable` text view. What the representable did and the native field does not: an
  image pasted straight into the field (the plus menu has *Paste image* when the pasteboard holds
  one), the select-and-replace capture for the correction learner, the exact caret for the `@` menu
  (now the end of the text), swipe-to-send on texts estimated longer than six lines, and hardware
  arrow / Tab navigation of the popups on iOS 16 (iOS 17+ has them via `onKeyPress`). Return on a
  hardware keyboard sends, Shift+Return breaks the line, the on-screen Return follows *Settings →
  Appearance → Return sends*; dictation still ends in *Back to typing*.
- **The launch screen (0.1.38)** (`NanoMuse/NanoMuseLaunch.storyboard`,
  `NanoMuse/NanoMuseLaunch.xcassets`): the mark on the system background, no words, light and
  dark. Upstream's storyboard stays in the tree; `scripts/rebrand.py` points
  `INFOPLIST_KEY_UILaunchStoryboardName` at ours. iOS caches launch screens per install: after
  an update the old one can show a few more times, a reinstall shows the new one at once.
- **Side chats and presence (0.1.38, Contract C9)** (`NanoMuseSync.swift`, `NanoMusePresence.swift`,
  `NanoMuseSyncSettings.swift`, `NanoMuseFromDeviceCaption.swift`): *Data controls → Also sync
  side chats* is per device and off by default — only the main conversation goes up and the pull
  asks `scope=main`; side rows that still arrive are ignored. Turning it on pulls once from
  `since=0&scope=all&tail=300` (idempotent by `mid`) and the side chats go up with the next push;
  turning it off narrows the traffic again and deletes nothing. A table's first pull is
  `since=0&tail=300`: the newest 300 texts, not the whole history. Presence: `POST
  /v1/sync/working {cid, working}` after the user line is pushed and after the turn's end is;
  the hub's `working` frame and `/v1/sync/state`'s `working` list fill a map that expires after
  ten minutes, and the chat shows *〈device〉 is working…* under the last message when it is
  another device's user line (`ChatMessage.nmWorkingDevice`). A remote user line as the tail is
  never this phone's interrupted turn: `recheckCanResumeFromHistory` leaves `canResume` off for
  it, so no banner, no Resume, nothing re-sent.
- **Sign-in and the relay (0.1.38)** (`NanoMuseCloud.swift`, `NanoMuseCloudView.swift`,
  `NanoMuseRelayPicker.swift`): a phone number with a country code other than +86 is told
  *Text-message codes reach mainland-China numbers only. Use an e-mail address instead.* before
  the code is requested, and the relay's `phone_region` error reads the same. *Use a different
  server* on the sign-in page opens a sheet: the address, *Check* (`GET /healthz`), *Use this
  server*; https is required unless the host is on one's own network, judged by the one rule
  the proxy's bypass uses too (`NanoMuseProxy.isLocal`, Android's `LanOnly`): the address is
  parsed first, so `10.foo.example.com` is a public name; the private ranges, the carrier-grade
  `100.64/10` Tailscale hands out, loopback, link-local, IPv6 ULA, `localhost`, a name without a
  dot and the suffixes `.local`, `.lan`, `.home`, `.internal`, `.home.arpa`, `.localdomain`,
  `.ts.net` count as one's own. Signed in, the account page shows *Server:
  〈host〉* with *Change*, which signs this phone out first — a key belongs to the relay that
  issued it.
- **One account's conversations, not the last person's (0.1.39, Contract C10)**
  (`NanoMuseSync.swift`, `NanoMuseShell.swift`): a conversation belongs to the account that first
  pushed or pulled it — the sync table that maps it is that account's, and every account that has
  synced on the phone keeps its table (`nanomuse-sync-accounts.json`, keyed by the relay's opaque
  `account.id`, never the phone number or e-mail). Signed in, the chat lists and the Chat tab show
  the account's own conversations and the ones no account has synced yet; another account's stay
  on the phone, hidden, and are never pushed under the signed-in account — an unowned one becomes
  the account's with its first push. Signing in as a different account than last time starts
  that account's cursor over (the `tail=300` pull) and forgets presence; signing back in as the
  first account brings its conversations and its main chat back. Signed out, everything on the
  phone shows and nothing moves. The agent's name and look already follow the account; the local
  memory files do not yet.
- **Nothing of one account for the next (0.1.40, Contract C12)** (`NanoMuseAccountData.swift`,
  `NanoMuseSignOutSheet.swift`): every chat has an owner row (`nanomuse-owners.json`), synced or
  not, and the lists, the Chat tab, the Library, *Today's chats*, the Siri shortcuts and the
  push show the signed-in owner's only; signed out, only the chats made while signed out. A
  sign-out — here, everywhere, *Use a different server* — is a sheet with one switch, *Keep this
  account's chats on this device*, off by default: off, the account's chats, memory, feed, goals,
  routines and face leave the phone (its sync table too, so a later sign-in never tombstones
  them on its other devices); on, they are put aside under `MinisConfig/nanomuse/accounts/<hash>/`
  and come back with the account. Signing in as another account goes through the same path.
  *Delete the account* removes all of it with no question. A key the relay refuses on a refresh
  (`401 bad_key` — revoked from another device, a relay reset) takes the *keep* path instead:
  the data goes aside, the key goes, and the sign-in form says *Your sign-in on this phone was
  ended — sign in again to continue; your chats are kept on this device until then* until the
  next sign-in (`NanoMuseCloud.signInEnded`); only `401 account_deleted` deletes
  (`NanoMuseAccountData.keepOnRefusedKey`, tested in `NanoMuseAccountsTests`). The relay's key is saved on this
  device only (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`, never iCloud Keychain); a
  fresh install with no marker, no provider and no chat sweeps the device-only Keychain items a
  previous install left. The full table is [sync.md](sync.md).
- **The audit's small things (round 9)** (`NanoMuseCloudView.swift`, `NanoMuseFirstRun.swift`,
  `NanoMuseAvatarFlow.swift`, `NanoMuseDevicesSection.swift`, `NanoMuseShell.swift`): the
  sign-in sheet opens with the app's mark above the field, the field says *Mainland China phone
  number or e-mail*, and a number with another country code gets *Text-message codes reach
  mainland-China numbers only…* under the field while it is typed, not after a tap; the footer
  carries Android's fine print (what the relay keeps — an account id, a masked identifier, usage
  counts, the agent's name and look) and links the privacy policy, not the GitHub page. The
  Notifications page of the first run shows the mark, as the welcome and sign-in do. After a
  new face is picked with a video model set, the reply says the four clips follow in the
  background (Android's sentence). In the account's Devices list an offline device shows when
  it was last seen and a tap on an online one opens the main chat with `@〈name〉 ` in the
  composer (the Reach sheet's *Ask this device*). `NanoMuseRoot` draws nothing until it knows
  whether the setup is due, so a fresh install never shows the shell for a frame before the
  welcome page. The first conversation's fourth line no longer says the messages go *only* to
  the   model: signed in, the main conversation also follows the person to their other devices,
  and *Data controls* switches that off — the same words on Android, in every language.
- **The audit's second pass (round 10)** (`NanoMuseHub.swift`, `NanoMuseDevicesSection.swift`,
  `NanoMuseScheduler.swift`, `NanoMuseSync.swift`, `NanoMuseAccountData.swift`,
  `NanoMuseProxy.swift`, `NanoMuseImageGen.swift`, `NanoMuseVideoGen.swift`): the hub client
  reads the relay's close codes ([hub.md](hub.md)) — 4001 and 4002 end the attempts until a new
  sign-in and the Devices row says *Sign in again*; 4003 waits 30 s; a close with the reason
  `hub_paused` waits two minutes and the row says *Paused by the relay*; everything else keeps
  the 1 → 30 s backoff and reads *Reconnecting…*. An `open` call from another device opens
  `http` and `https` links only, so a `tel:` or another app's scheme is refused with `usage`;
  a call's timeout timer ends with its answer. A one-off routine made after its time of day
  runs the next day instead of never. The sync side tables (`nanomuse-sync-accounts.json`,
  `nanomuse-owners.json`) use the default data-protection class like the chats themselves, and
  when the file is there but cannot be read (the phone locked, the app woken in the background)
  the store waits for the next call rather than starting empty and writing that over every
  account's table. The image and video generators go through the Network proxy like a chat
  turn on the same provider (`NanoMuseProxy.SessionSlot`), and their failures are sentences in
  every language — *The provider refused this key (HTTP 401)*, *The video took longer than 12
  minutes* — with the vendor's own words after *The provider says:* when it sent some.
- **The audit's third pass (round 11)** (`NanoMuseHubTasks.swift`, `NanoMuseHub.swift`): a
  `stop` from another device finds the run by the task frame's id (`stop {call}`, what the
  desktop sends) as well as by conversation, only the device that asked may stop it, and the
  task then answers `cancelled` as [hub.md](hub.md) says. A relay `error` frame about one frame
  (`too_large`, `rate_limited`, `bad_frame`) while the socket stays open is logged and the
  Devices row keeps saying *Connected* instead of showing the relay's sentence until the next
  reconnect. The header's name and status lines (`NanoMuseNamePill`, `NanoMuseHeaderTitle`) and
  the height reserved for the pill follow Dynamic Type up to 1.35 times their base
  (`NanoMuseHeaderMetrics`); the side drawer measures its width from the window it is in
  (`GeometryReader`) rather than `UIScreen.main`, so an iPad window narrower than the screen gets
  a drawer that fits; the model pickers' rows carry the *selected* trait for VoiceOver and the
  tick is not read as a symbol name.
- **The audit's strings and layout pass (round 10)** (`NanoMuseChrome.swift`,
  `NanoMuseFirstRun.swift`, `NanoMuseProviderReachCard.swift`, `NanoMuseSystemFiles.swift`,
  `*.lproj/InfoPlist.strings`, `Localizable.xcstrings`): `NanoMuseFlowLayout`, a wrapping row
  (iOS 16 `Layout`), holds the name chips of the first conversation and the buttons under the
  provider card, so four names or *Try again · Use nanoMuse Cloud this time · Network settings ·
  Add a key of your own* fit an iPhone SE and a large text size instead of being cut off at the
  right edge; a setup page's fine print is one paragraph with *Learn more* at its end. The
  permission prompts for NFC, Bluetooth and Face ID are in all nine languages (they fell back
  to the English `Info.plist` text), and the local-network prompt describes this app, not a
  virtual machine. In 简体中文 the relay is *nanoMuse Cloud* everywhere, as the Settings row
  that the sentences point to is named (it was *nanoMuse 云* or *nanoMuse 云端* in 16 places).
  HEARTBEAT.md renders each routine's cadence with the Routines list's words (*Daily · 08:00*,
  *Checks every 6 hours*) instead of English *daily*, *once*, *every 6 h*; the memory import
  prompt follows an in-app language change.
- **The audit's follow-ups (round 11)** (`Localizable.xcstrings`, `NanoMuseVendorSheet.swift`,
  `NanoMuseFeed.swift`, `NanoMuseAppearance.swift`, the `// nanoMuse:` spots of
  `OpenAIProvider.swift`, `MinisTests/NanoMuseCopyTests.swift`): no sentence a person reads
  carries a dash any more, in any of the nine languages: 73 keys were rewritten as two
  sentences, a comma, a colon or a middle dot (*Before we start, what should I call you?*,
  *Sign in · free*, *Done. My new look is on.*), the rows of HEARTBEAT.md and the diagnostics
  report with them, and ten keys nothing referenced were dropped; upstream OpenMinis keys are
  not ours and stay. 繁體中文 says *nanoMuse Cloud* as the other languages do, Russian says
  *Эл. почта*. `NanoMuseCopyTests` reads the catalogue and the `NanoMuse/` sources on the Mac
  and fails on a dash, an exclamation mark or a translated relay name in our keys. The vendor
  sheet tries a pasted key against the provider's model list before keeping it: a 401 or 403
  leaves the phone as it was and says so under the field, where before upstream's fallback
  seeded a catalogue list and the sheet closed as if the key were right. `Retry-After` from a
  plan's 429 reaches the reach card, so *Resets in …* shows for a ChatGPT or Claude plan. A
  post's detail rows are a `Grid` whose label column takes the longest label; the avatar size
  is a menu, not five segments.
- **The third audit: the version row (1.0.x)** (`NanoMuseUpdateCheck.swift`,
  `MinisTests/NanoMuseLogicTests.swift`): the download index at `nanomuse.cn/dl/index.json` is
  `{"releases": [{"tag": "v1.0.0", …}, …]}`, newest first, and that is what the row reads now,
  as Android's `UpdateCheck.parseIndex` does; the shapes the row used to look for (`ios.version`,
  `latest`) were never written, so on a phone that cannot reach GitHub the row always said *Could
  not check*. A release found through the index leads to `nanomuse.cn/dl/`; one found through
  GitHub leads to its release page. `parseIndex` and `parseGitHubLatest` are pure and tested.
- **The third audit: the sign-in sheet (1.0.x)** (`NanoMuseFirstRun.swift`): *Sign in · free* on
  the welcome page opens the account page as a sheet; once the code or password goes through, the
  sheet closes on its own (`nmOnChange` on the signed-in state) and the setup is on its next page,
  the password or the source. Before, the sheet stayed open on the signed-in account page, with
  its Devices and sync rows, and the person had to swipe it away to find the setup had moved on.
- **The third audit: Chinese words (1.0.x)** (`Localizable.xcstrings`, `NanoMuseShell.swift`,
  `NanoMuseAccountView.swift`, `MinisTests/NanoMuseCopyTests.swift`): the Chinese copy says what
  Android says. The agent is 智能体 (繁體 智慧體) in the 19 keys where it was still "agent" in
  English (the system files' notes, the routines, *About the agent*, the avatar's failure line) or
  代理, which in Settings → Network means the proxy; the relay is 中继 / 中繼 in the seven
  relay sentences that said 中转 / 中轉 (*The relay says*, *Paused by the relay*, the paused
  sign-ups, allowance, sync and hub, the private relay); *Hands* stays in English as Android's
  设置 → Hands does; the chat tab has its own key, `tab.chat` (聊天, Android's `nm_tab_chat`),
  instead of upstream's *Chat* (闲聊), and the account page's usage rows say 对话 for the chat
  kind (`models.slot.chat`, Android's `nm_usage_kind_chat`). `NanoMuseCopyTests` fails on
  "agent" in a Chinese value, 代理 where the English says agent, 中转 and 双手.
- **The third audit: tasks from other devices (1.0.x)** (`NanoMuseHubTasks.swift`,
  `MinisTests/NanoMuseHubTasksTests.swift`): a `task` frame carries the asking device's screen
  language (`language`, [hub.md](hub.md)); the iPhone's Muse is now told to answer in it, where
  before it went by the text alone, so a person typing `@iPhone` on an English desktop about a
  Chinese page gets the answer in English. `NanoMuseHubTasks.prompt` is pure and tested. The
  phone's own `@device` mentions have sent the tag since 1.0.0.
- **The third audit: the Cloud switch and the chat (1.0.x)** (`NanoMuseModelSlots.swift`,
  `NanoMuseCloud.swift`, `NanoMuseModelsView.swift`, the `// nanoMuse:` spots of
  `ProviderInstanceDetailView.swift`, `MinisTests/NanoMuseModelSlotsTests.swift`): *Use nanoMuse
  Cloud models* off (Settings › Models, or *Enabled* on the Cloud provider's own page) while new
  chats answer through the account now hands the Chat slot and the main chat to the first provider
  of your own that chats, on the catalogue's default for it (`NanoMuseSlotResolver.nextChat`,
  Android's `ModelSlots.nextChat`; `NanoMuseModelSlots.chatLeaves` does the move through
  `useForChat`). With no own chat model the switch is refused: `NanoMuseCloud.setModelsOn` returns
  false, the switch stays on, and *Add a provider of your own first; with nanoMuse Cloud off,
  nothing else could answer.* appears under it, inside the card on the Models page and as the
  Status section's footer on the provider page. Before, the switch went off, the Chat row kept
  naming the account, and the main chat stopped with upstream's *No model configured* error; the
  *Not set* state is no longer reachable through this switch. A provider of your own switched off
  on its page keeps upstream's path: the chat re-resolves through the default group and, when
  nothing is left, says *No model configured. Add a provider in Settings.*

## Building on a Mac

Requirements are upstream's, in [android/BUILDING.md](../android/BUILDING.md): a recent Xcode
(the project is on the iOS 26 SDK), Homebrew `ninja meson llvm lld libarchive pkg-config`, Go 1.25
for rclone.

```bash
git clone --recurse-submodules https://github.com/nano-muse/nanoMuse.git && cd nanoMuse/android
./deps/build_lame.sh && ./deps/build_ffmpeg.sh          # FFmpeg links against LAME: this order
./deps/build_ish.sh && ./deps/prepare_alpine_rootfs.sh  # the sandbox kernel and its rootfs
./deps/build_rclone_ios.sh                              # Rclone.xcframework
cp src/ios/Configs/ProviderCustomization.xcconfig.example src/ios/Configs/ProviderCustomization.xcconfig
open src/ios/Minis.xcodeproj
```

Pick the **Minis** scheme, set your team under *Signing & Capabilities* (the project ships with an
empty `DEVELOPMENT_TEAM`), build for a device: the native libraries are device-only, so the
simulator does not link — see the troubleshooting section of BUILDING.md.

One rule of the chat screen, learnt from build 9 of 0.1.38: **nothing new goes on the end of
`AIChatView.body`'s modifier chain.** The body is one expression of some sixty chained
modifiers; its getter keeps copies of the growing value on the stack, and the four links 0.1.38
added were enough to overflow the main thread's 1 MB on an iPad the moment the chat appeared
after onboarding — a crash on every launch, in `AIChatView.body.getter` →
`__swift_instantiateConcreteTypeFromMangledNameV2`. Chat-wide behaviour of ours lives in
`NanoMuse/NanoMuseChatModifiers.swift` (`NanoMuseChatHooks`, `NanoMuseComposerHost`): add to
those, or add a third modifier — one link. The composer stack is an `AnyView` there on purpose.
`MinisTests/NanoMuseRound6Tests.swift` measures the body's value size and type depth and fails
when either grows past its ceiling.

## TestFlight

Distribution is TestFlight, **internal testers**: the people you add as users of your App Store
Connect team (up to 100), who get every build minutes after it is processed, with no App Review.
An external group (public link, up to 10,000 testers) needs Apple's beta review once per version;
the group *nanoMuse Beta* and its public link exist, and each build is added to it and submitted
for review after the internal testers have had it. The pipeline is the same either way.

### Where it stands

Set up on 2026-10-03, all of it under the account holder's developer account (team
`TN43QYW8K4`), nothing of which is in the repository:

- the app record *nanoMuse*, iOS, bundle id `io.github.nanomuse.app`, SKU `nanomuse-ios`,
  Apple ID `6818802049`; the three extension bundle ids `…app.ShareExtension`,
  `…app.FileProvider`, `…app.AgentWidget`; the app group `group.io.github.nanomuse.app` and the
  iCloud container `iCloud.io.github.nanomuse.app`; the capabilities the four `.entitlements`
  ask for (App Groups, HealthKit with clinical records, HomeKit, iCloud/CloudKit, NFC tag
  reading, WeatherKit) turned on on the identifiers;
- the API key *nanoMuse CI* (role App Manager), the Apple Distribution certificate
  *Apple Distribution: Guangyi Liu* (valid to 2027-10-03) and the four App Store profiles
  *nanoMuse App Store*, *nanoMuse ShareExtension App Store*, *nanoMuse FileProvider App Store*,
  *nanoMuse AgentWidget App Store*;
- the six repository secrets of the table below;
- the internal TestFlight group *nanoMuse Core* with automatic distribution, so every processed
  build reaches its testers by itself; the device list is empty on purpose (nothing here needs
  one);
- **the first build**: 0.1.31 (2), archived and uploaded by the workflow on 2026-10-03, processed
  by App Store Connect (`VALID`, export compliance answered by the Info.plist key) and in beta
  testing with the internal group — the first thing that can be installed from TestFlight;
- the test information an external group needs, in English and Simplified Chinese: the beta app
  description, the feedback address, the marketing and privacy-policy links, and *What to Test*
  on each build (none of it names other products); the external group *nanoMuse Beta* with its
  public link, `https://testflight.apple.com/join/ZHexbDqc`; the beta-review contact and a
  review account on the relay in *Beta App Review Information*;
- **build 16 (1.0.0)** was added to *nanoMuse Beta* and submitted to Apple's beta review on
  2026-10-09 and passed it, so the public link installs it (build 14, 0.1.41, was what the link
  delivered before); build 17, 1.0.0 with the fixes merged after the tag, went to the internal
  testers only. **Build 18 (1.0.1)** was added to *nanoMuse Beta* and submitted to the review on
  2026-10-10; the link installs build 16 until it passes. The public link delivers a build only
  once a review has passed, and each new version repeats the step (the review is per version;
  later builds of an approved version need none).
  Nothing towards the App Store: the app is not going there.

### Once, in App Store Connect

1. **The app record.** *Apps → + → New App*: platform iOS, name nanoMuse, bundle id
   `io.github.nanomuse.app`, a SKU. Automatic signing registers identifiers, but the app record
   itself is created once, by hand. If the bundle id is not offered in the list, register it first
   under *Certificates, Identifiers & Profiles → Identifiers*.
2. **Capabilities on the identifier.** The entitlements ask for App Groups, iCloud (CloudKit),
   HealthKit (with clinical records), HomeKit, NFC tag reading and WeatherKit. Automatic signing
   turns most of these on by itself; if the first archive fails on a capability, enable it on the
   identifier by hand, and create the iCloud container `iCloud.io.github.nanomuse.app` and the
   app group `group.io.github.nanomuse.app` there. WeatherKit also has to be enabled on the
   *Services* tab of the identifier.
3. **An API key.** *Users and Access → Integrations → App Store Connect API → Team Keys → +*,
   role **App Manager** (Developer is not enough to upload). Download the `.p8` once; note the
   Key ID and the Issuer ID shown above the table.
4. **Testers.** *TestFlight → Internal Testing → +*: a group, and the team members in it.

### Repository secrets

| Secret | What |
|---|---|
| `APP_STORE_CONNECT_KEY_ID` | The key's ID, 10 characters |
| `APP_STORE_CONNECT_ISSUER_ID` | The issuer ID, a UUID |
| `APP_STORE_CONNECT_KEY_P8` | The full text of `AuthKey_<ID>.p8`, `-----BEGIN PRIVATE KEY-----` to the end |
| `APPLE_TEAM_ID` | The 10-character team id (*Membership details* in the developer account) |
| `IOS_DIST_P12_BASE64` | The team's *Apple Distribution* certificate with its private key, a `.p12`, base64 in one line |
| `IOS_DIST_P12_PASSWORD` | That `.p12`'s password |

### The certificate, and why signing is manual

Xcode's automatic signing (`-allowProvisioningUpdates` with the key) was the first plan and does
not work for a team like this one: an archive is signed with an *iOS App Development* profile
before the export re-signs it for the store, and a development profile has to list at least one
device — a team that only ships through TestFlight has registered none, so the archive stops at
*Your team has no devices from which to generate a provisioning profile*. The lane therefore
signs manually with the store's own material, which needs no devices: the Apple Distribution
certificate from the two secrets above, and the four *App Store* provisioning profiles (the app
and its three extensions) that `get_provisioning_profile` downloads from the account with the key
at the start of every run — and repairs there if the certificate they name is not the one in the
keychain.

The certificate was made without a Mac, and can be made again the same way when it expires or
the key is lost (a team may hold two or three distribution certificates; revoke the old one in
*Certificates, Identifiers & Profiles → Certificates* first if the limit is reached):

```sh
umask 077 && cd ~/.private/apple/dist                                # anywhere outside the repository
openssl genrsa -out dist.key 2048
openssl req -new -key dist.key -out dist.csr -subj "/emailAddress=<account e-mail>/CN=nanoMuse CI distribution/C=CN"
# POST /v1/certificates { certificateType: DISTRIBUTION, csrContent: <dist.csr> } with a JWT signed
# by the API key (the key's role must be App Manager or Admin); save certificateContent, base64, as dist.cer
openssl x509 -inform DER -in dist.cer -out dist.pem
openssl rand -base64 24 | tr -d '\n' > dist.p12.pass
openssl pkcs12 -export -inkey dist.key -in dist.pem -out dist.p12 -passout file:dist.p12.pass   # with OpenSSL 3 add -legacy
base64 -w0 dist.p12 | gh secret set IOS_DIST_P12_BASE64 -R nano-muse/nanoMuse
gh secret set IOS_DIST_P12_PASSWORD -R nano-muse/nanoMuse < dist.p12.pass
```

The private key stays in that folder on the maintainer's machine (and in the secret); nothing
of it goes into the repository, a log or a chat. The profiles were created once in the account
with the same API (`POST /v1/profiles`, type `IOS_APP_STORE`, one per bundle id, each naming the
certificate); the lane makes them again if they are missing.

### Does it compile?

*Actions → iOS · build check → Run workflow* (`.github/workflows/ios-check.yml`) builds the app
for a device on a Mac runner with signing turned off — no Apple account, no secrets. It shares
the native-dependency cache with the TestFlight workflow, so run it first: a compile error costs
minutes there, not an upload. The full `xcodebuild` log is attached to the run. The run fails
when a warning is reported in a file under `NanoMuse/` (upstream's files are not held to this),
so the zero-warnings rule above is checked, not just asked for.

The strings catalogue has a check of its own that runs on every pull request, on Linux:
`tests/test_ios_strings.py` parses `Localizable.xcstrings` with every key pair in hand and fails
when a key is listed twice (a JSON parser keeps one of the two entries and drops the other
without a word, Xcode included, so the translations that ship would depend on which one won).

### Running it

*Actions → iOS · TestFlight → Run workflow*, or push a tag `ios-<anything>`. The job builds the
native dependencies (cached on the scripts and the iSH revision; the first run takes about an
hour, later ones a few minutes plus the archive), archives with `fastlane beta`
(`android/src/ios/fastlane/Fastfile`), uploads, and attaches the `.ipa` and the dSYMs to the run.
The build number is the workflow run number, so every upload is newer than the last; the version
is `MARKETING_VERSION` from the project. `ITSAppUsesNonExemptEncryption` is already `false` in the
Info.plist, so builds do not wait for the export-compliance question.

The runner is `macos-26`; if the label is not available on your GitHub plan, `macos-15` with
`xcode-version: latest-stable` is the fallback, at the cost of the iOS 26 SDK the project asks for.

## What follows

The Android app is where nanoMuse's shape lives; since 0.1.34 the iPhone carries the same shape
over OpenMinis — the agent's page, the chat-driven avatar, goals, feed, routines, the first run —
with iOS's limits on background work spelled out in the copy. Where the Android code is, and
what became of it here:

| Android (`io.github.nanomuse.*`) | On iOS |
|---|---|
| `cloud` — relay client, sign-in, account | Done: `NanoMuse/NanoMuseCloud*.swift`, `NanoMuseAccount*.swift` (0.1.32: password, invite code, the allowance in yuan, usage, sessions, timeline, delete) |
| `ui.onboarding` — the first run with *Sign in — free* | Done (0.1.34): `NanoMuseFirstRun.swift`, the first conversation included; 0.1.35 the Notifications page; no Hands page on iOS |
| `community.StarPrompt`, `community.Nudges` — the star asks from the relay's policy | Done (0.1.35): `NanoMuseNudges.swift`, `NanoMuseStar` — the moments, the cooldown and the cap from `/v1/nudges` |
| `community.UpdateCheck`, the Version row | Done (0.1.35): `NanoMuseUpdateCheck.swift` — installed and latest, `nanomuse.cn/dl/index.json` then GitHub |
| `avatar.VideoGen`, `avatar.AvatarMotion` — the motion clips | Done (0.1.35): `NanoMuseVideoGen.swift`, `NanoMuseAvatarMotion.swift`, `NanoMuseMediaModels.swift` |
| `nm.show_steps` — the agent's steps, on by default since 0.1.37 | 0.1.32: `NanoMuseSteps.swift`; finished messages keep to the conversation, a running one shows its steps |
| `connectors` — the catalogue, `SharedConnectors` | Done: `NanoMuseConnectors.swift` (0.1.33 the catalogue, 0.1.34 the other devices' entries) |
| `ui.home`, `ui.chat`, `ui.settings`, `ui.profile` — the shell, header, agent page | Done: `NanoMuseShell.swift`, `NanoMuseHeader.swift`, `NanoMuseAgentPage.swift`, `NanoMuseSettings.swift`; 0.1.35 the Muse header on every room, the settings as Muse cards (`NanoMuseChrome.swift`, `NanoMuseAppearance.swift`) |
| `avatar` — the drawn face, the chat-driven change, the studio | Done (0.1.34): `NanoMuseAvatarFlow.swift`, `NanoMuseAvatarStudio.swift`, `NanoMuseImageGen.swift` |
| `goals`, `feed`, the scheduler | Done (0.1.34) as far as iOS allows: foreground catch-up, `BGAppRefreshTask`, local notifications. No alarm-exact runs while the app is asleep — the copy says so |
| `coding` — the computers' coding agents over the hub | Done (0.1.34): `NanoMuseCoding.swift`; the computer must run nanoMuse signed in with the same account |
| `reach` — the phone drives the computer | Done: `NanoMuseReach.swift` over the hub |
| `hands` — the phone's own screen | No equivalent: iOS does not let an app drive another. App Intents / Shortcuts are the door there |
| Widgets | Upstream's `AgentWidget` as it is |

Still to check on a device, in order: the first run end to end with a fresh account; a chat-driven
avatar change through the relay and through a Bailian key, and the four clips it draws afterwards; a routine coming due with the app in
the background (does iOS grant the refresh on the tester's phone, and how often); a coding session
against a computer of the account; the connectors list after a second device signs in.

Not in the plan: the App Store. TestFlight is the distribution: the internal group, and the
public link once Apple's beta review of a version has passed.
