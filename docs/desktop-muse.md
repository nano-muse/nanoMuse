# The desktop, the way Muse does it

> What Meta's Muse desktop app looks like and does, written down from using it, and what
> the nanoMuse desktop on DeepSeek Harness takes from it, leaves out, or does its own
> way. Interface only: no account, no conversation, no screen content from the session
> this was taken from. Muse is Meta's trademark; nanoMuse is a community project with no
> affiliation — see [the README](../README.md#disclaimer).

The desktop app here is **DeepSeek Harness plus the `dsh-nanomuse` bundle**
([harness.md](harness.md)). dsh brings the loop, the tools and a complete web app with
seats a plugin can take; the bundle takes the seats that make the window look and
behave like Muse, hides what Muse does not have, and adds what the phone app has that
Muse does not — the account on every device, Reach, an open model layer.

## The window

**Muse.** One window. A narrow icon rail on the far left, a column of chats next to it,
the conversation in the middle. The agent's face and name sit *above* the conversation,
centred, with a one-line status under the name that changes as it works ("thinking",
"looking at the screen", "generating options"). The composer at the bottom has an
attach button and a microphone; while the agent works the send button becomes a stop
square. Light, dark and system themes, an accent colour, system typography; nothing
decorative, every surface a flat tone one step from its neighbour.

**nanoMuse on dsh.** The same window, screen for screen, from dsh's `sidebar` seat and a
stylesheet over the harness's stable DOM hooks (`data-composer-card`,
`data-chat-flow-kind`, `data-approval-key`…):

- The rail, in Muse's order: Chats (a dot while the agent works), Search, Feed (a dot
  for posts you have not seen), Ideas, Goals, Library, Devices; a spacer; the hamburger
  at the foot (Schedules and the harness's other panels live in its menu). No face on
  the rail — as in Muse, the face is the pinned header and the profile
  panel. On macOS the window has no title bar: the traffic lights sit over the rail's
  empty top, which is a drag handle, and full screen takes the clearance away. Windows
  gets the same frameless window with the system's own caption buttons drawn over the
  top right (`titleBarOverlay`, recoloured with the theme); Linux keeps the window
  manager's bar, since there is no portable overlay there.
- The chats column: a *Search* field with a *···* menu (archived chats), **Main chat**
  — one session that stays at the top, the first one or the one you chose with *Make
  main chat* — and **Side chats** with a *+*: every other session, pinned first, each
  with a *···* for *Make main chat*, *Pin*, *Rename* (inline), *Archive*. A blank
  session reads *New chat*; a dot marks a running one, a mark one that waits for you.
  It collapses to the rail alone.
- Above the conversation, in the harness's `conversation.header.leading` seat, the face
  and name are pinned at the top centre with the status chip: *connected* / *not signed
  in* / *thinking…* / *Hands · step N · what it is doing* / *Reach · step N · on Laptop
  B: …* / *waiting for you*; a *Stop* button beside it while a turn runs. The chip tints
  while the agent works and while it waits for an answer. Clicking the face opens the
  profile panel. At the top right, *Invite* (with an account), then the harness's
  right-sidebar toggle; the harness's own title row, tabs (*Conversation* / *Trace*)
  and session actions are hidden — the chat rows carry rename, pin and archive.
- The conversation: your messages in bubbles toned from the accent on the right, the
  agent's in large-radius grey bubbles on the left, timestamps and the per-message
  actions on hover only; an empty chat has no greeting — the composer waits at the
  bottom, as in Muse, with the workspace and preset row above it.
- The composer is one pill: *+* (attach), *Message*, the send disc (the stop square
  while a turn runs). The harness's model picker, permission mode and plan toggle are
  hidden from it — the model lives in Settings → Models and the default permission mode
  in General, as in Muse — and come back with *Show DeepSeek Harness controls* under
  General. The microphone appears when the harness's voice input is switched on in
  Plugins (Settings → Dictation says how).
- Theme: the harness's light and dark palettes are overridden to Muse's tones (`#f9f9f9`
  surfaces, `#e3e4e6` agent bubbles in the light; `#171717` with `#242424` bubbles and
  `#2b2b2b` fields in the dark) and the accent follows the face's colour on the account,
  so a face coloured on the phone colours the desktop too. The desktop shell paints the
  window in the same base colour, so a resize never flashes white in the dark.

## The first run

**Muse.** Sign in (a phone number, an SMS code — "sign in or create an account"), a
loading page, then three full-window pages with ‹ › top right and a dots pager: *Allow
Muse to use your computer?* (accessibility for clicking and typing; screen recording
for screenshots — each row with an *Allow* button that becomes a green check, fine
print, *Skip* under the card that turns into a blue *Continue* once both are allowed),
*Allow Muse to access your files and local apps?* (a *Full Disk Access* status pill, a
list of local apps each with a read-only/… dropdown, *Continue*), *Turn on voice input*
(the microphone, *Allow*, *Skip*). Then the main window with the agent's introduction in
the chat, a card to pick its name, and a connector recommendation.

**nanoMuse on dsh.** The same pages, full-window, in the harness's `settings.onboarding`
seat (we take the shipped step's id, so a fresh install meets the agent instead of being
asked for a DeepSeek key):

1. **Welcome** — the face, *Welcome to nanoMuse*, one blue *Sign in* pill; under it, in
   small type, *Use my own API key* (opens Models) · *Later*.
2. **Sign in or create an account** — one field, *Phone number or e-mail*, the fine print
   with the terms and the privacy policy, *Continue*; the same two calls the phone uses
   (`/v1/auth/code`, `/v1/auth/verify`).
3. **Enter your code** — *A code was sent to …* with *Resend*, six code boxes that verify
   themselves on the sixth digit, *Next*, *Try another way* (a password, for accounts
   that set one: `/v1/auth/login`).
4. A spinner while the account is adopted (models, name, face), then the **three
   pages**, ‹ › top right, dots under the card, *Skip* that becomes *Continue* once the
   page is allowed: **Allow nanoMuse to use your computer?** — *Accessibility* and
   *Screen Recording* rows, each with *Allow* that asks the system through the desktop
   shell and turns into a green check as the system grants it (polled, and again when
   the window gets focus; the shell can open the System Settings pane); on Linux and
   Windows nothing is gated and both rows are checks from the start. **Allow nanoMuse
   to access your files?** — the working folder as a pill (*Change* opens the native
   folder picker and creates the workspace) and the places the agent may touch under
   the default permission preset (the working folder read and write; the home folder
   and Downloads read, asking before a write). Muse's per-app dropdowns (Mail, Messages,
   Notes) are macOS app data we do not read, so there is no such list. **Turn on voice
   input** — the *Microphone* row, *Allow* through the shell (or the page's own prompt
   in a plain browser).
5. The overlay waits on the host's `rooms/kickoff`: the **main chat** is created on the
   agent's own folder (`~/nanoMuse`, registered as a workspace so the composer is live),
   the introduction is posted into it (`rooms/intro`: hello, three names to pick from or
   one of your own through `ask_user_question`, `take_name`, a word about Settings →
   Connectors, one small question) — once per install — and the window fades into it.

The step completes itself when a model can already answer (the account, a key, a
provider the person added) and does not show again; Help & support → *See the first run
again* reopens the pages on purpose (the kickoff does not repeat).

## The profile and the face

**Muse.** The face at the top opens a profile panel on the right: a large avatar with a
pen (*change avatar* / *edit name*), tabs for the profile, the approval log (what was
allowed, when, "allowed for this task" / "always allowed"), activity, more. A new face
is drawn in the chat: four candidates in a grid, pick one, the agent confirms in words.

**nanoMuse on dsh.** The face at the top opens the same panel, 310 px on the right,
beside the chat (the chat makes room; × or Escape closes it): the avatar at 86 px with a
pen — *Change look* (the dragon, or an emoji on a colour, written to the account and
worn on every device) and *Edit name* — the name, *Connected* / *Not signed in* /
*Offline*, and a segmented control of four tabs: **Activity** (the sessions and the
hub's notices, *Today* and *Earlier*), **Approvals** (what you allowed or rejected on
the approval cards, with when; kept on this computer), **Schedule** (opens the harness's
schedules panel), **Memory** — what the agent remembers about you, one line each: a
field to add one, × to forget one, *Import memory* (Muse's sheet: paste what another
assistant knew, one line per memory), and the agent's description when the account has
one. The agent writes memory itself with the `remember` tool when you tell it something
you will expect it to know next time, and every chat's prompt carries the list back
(`rooms.json`, this computer only). *Change look* has the dragon, an emoji on a colour,
and **Draw one** — the avatar studio: describe the character, pick a style (Muse's
vinyl-toy look by default), see what it costs against today's allowance, *Draw four*,
and the four candidates come up in a 2×2 grid with *Option 1–4*; *This one* draws the
other poses from the pick (working, waiting, happy, oops) and the new look is on, for
every device of the account. The pictures come from the account's image model through
the relay (`/v1/images/generations`, `/v1/images/edits`), the browser squares each
still to 512 px WebP, and the host writes the face to the account (`PUT /v1/me/profile`
with the `face` map) and pulls it back under `faces/<id>/`. The prompts are the
runtime's, so a face drawn on the phone or here comes out alike. Asked in a chat
("change your avatar to an orange cat with a scarf"), the agent opens the studio with
the words (`draw_new_look`) rather than drawing by itself.

**The face moves.** Muse's avatar is animated per state; here the dragon's four states
(idle, working, waiting, happy) are the phone app's short clips
(`assets/dragon-<state>.mp4`), played silently in a loop wherever the face is 44 px or
larger — the header, the profile panel, the stage's cursor marker — with the still as
the poster, and the still alone below that size, when the system asks for reduced
motion, or where a list wants a quiet picture. A drawn face has stills only (the relay
keeps WebP, not video), so it and an emoji move the way CSS can: a slow breath while
idle, a sway while the agent works, a small hop when it waits for you. The faces route
(`/face/<id>/<state>.webp|mp4`) serves a clip when a profile ever brings one.

## Computer use

**Muse.** The controlled screen is shown inside the window as a dimmed live stage: an ×
to stop top-left, take-over controls top-right, a caption bottom-left saying what was
just done ("typed · <app>", "pressed ↵ · <app>"), the face as the cursor marker. Inline
permission cards in the chat — *allow <name> to take a screenshot?* / *write a file?* —
with *Allow (this task)*, *Always allow*, *Deny*.

**nanoMuse on dsh.** Hands are the runtime's `computer_screen` / `computer_act` over
MCP, so what the model sees is the screenshot it asked for and the status chip says
*Hands · step N · click "Save"* while it works. The harness's approval card is restyled
into Muse's permission card — a shield, the headline, the detail, *Allow once* in blue
first and *Reject* in grey — and every answer is written to the profile panel's
*Approvals* tab; the Sentinel's reasons ([sentinel.md](sentinel.md)) are in the
headline. dsh decides *once* or *rejected*; the standing answer is its permission mode
(General → the default for new chats). Settings → **Computer use** shows the two macOS
permissions with *Allow* and *Open System Settings* (through the desktop shell), *Keep
the screen awake while it works* (the shell holds a power-save blocker while a session
runs) and the note that anything that sends, pays or deletes is asked first.

**The live stage** is Muse's, picture-in-picture over the chat (bottom right, 400 px):
the latest screenshot the agent took, dimmed while it works, × top-left to put it away,
*Expand* top-right (the frame in a sheet), a **Take over** pill while a step runs (it
cancels the session's turn — the agent lets go, your mouse is yours), a caption bottom-
left — *looking at the screen · nanoMuse*, *clicked "Save" · Finder*, *typed "hello" ·
WeChat*, *pressed ⌘ S · Pages* — and the agent's face as the cursor marker, with a
ripple, where it last clicked. The host keeps one frame in memory and no history: a
`tools/execute` middleware around the hands' calls takes the picture out of the MCP
result (`computer_screen` returns it; `computer_act` returns the screen after the
action) with the window title and size from the first line, and `GET
/nanomuse/cloud/stage/frame?seq=N` serves it to the browser half; ten minutes after the
last step the frame is dropped. When the agent looks at a *phone* through Reach
(`device_screen`), the same stage shows that screen with the device's name — that is
what the phone app shows while its own Hands work ([gui.md](gui.md)), seen from here.

## Settings

**Muse.** A dialog with a sidebar: General (account, usage, language, appearance with
mode and accent, run on startup, show in menu bar, floating button, shortcuts, About
with version and check for updates) · Connectors · Computer use (the two macOS
permissions, keep screen awake, ask every time / always allow / always deny for computer
control and browser automation, blocked apps) · File system access · Dictation · Wallet
· Secure storage · Permissions · Message channels · Devices · Data controls (privacy,
import memory, download your data, reset) · Help · Legal · Sign out.

**nanoMuse on dsh.** The same shape, from the harness's `sidebar.settings` seat with its
stock General plugin switched off in the bundle layer:

- **General** — in Muse's order: the **account card** (the masked identifier or *Sign
  in*, opening the Account page), **Usage** (the plan and its bar — *Member* /
  *Unlimited*, or the free allowance with what is left and *Upgrade*), **Language** (the
  harness's own row in our card), **Appearance** (the harness's light / dark / system
  switch and Muse's ten **theme colours** as swatches — the accent of the whole app,
  kept on the agent's profile), **App behavior** when the desktop shell is there —
  *Open at login* (a login item; a freedesktop autostart entry on Linux), *Show in the
  menu bar* / *system tray* (an icon with *Open nanoMuse*, *New chat*, *Quit*), *Quick
  chat with ⌥ Space* (Ctrl+Alt+Space elsewhere: the window comes up with a fresh chat
  and the composer focused; pressed while it is in front, it steps aside) — kept in
  `desktop.json` under the app's home; **Shortcuts** (*Quick Chat* with its combination —
  *Change* records the next one you press, Esc cancels, *Default* puts the platform's back,
  and a line says so when another app already holds it — and the keyboard reference); **About** (nanoMuse, built on DeepSeek Harness, the bundle's version, the
  licence, *Check for updates* → the releases page); and *Developer*: *Show DeepSeek
  Harness controls* (the model picker, the modes, the workspace browser in place of the
  chats column). The harness's other rows (permission presets, font size, link opening,
  Enter to send, performance, session log) live under *Advanced → Harness*.
- **Account** (under *Advanced*) — the nanoMuse account: sign in or the masked
  identifier, the allowance, the look, the models, *Open Devices*.
- **Models**, **Agents** — the harness's pages, unchanged, under *Advanced*.
- **Connectors** — Muse's catalogue shape: a search field, category chips (*All*,
  *Built in*, *Work*, *Talk*, *Files*, *Developer*, *Data*, *Design*, *Money*,
  *Search*, *Infrastructure*…), **Connected** rows first and then the catalogue, each row
  with the service's brand mark on a white tile (the marks are
  [simple-icons](https://simpleicons.org/), CC0, written into
  `src/client/brand-marks.ts` by `scripts/brand-marks.mjs`; a letter tile where there is
  none) and *Connect* at the
  end; a detail per connector with what it can do — its tools as the server describes
  them, **one switch per tool** — what gates it (the permission preset, the Sentinel for
  the hands and the mailbox), the vendor's documentation, and *Disconnect* (asked
  twice). Three kinds of row:
  - **Built in** is what the agent can really reach: *Hands — this computer* (on when
    the runtime answered, with the reason when it did not), *Mailbox*, *Calendar*,
    *Address book* (the runtime's connectors, on when their tools arrive through
    `nanomuse mcp`), *Reach — your other devices*, *Web*, *Files*, *Terminal*, the
    rooms, *Schedule*. *Connect* on the mailbox, the calendar or the address book opens a
    **consent sheet** in Muse's manner — what the agent gets, who decides, where the
    credentials live — followed by the steps (`nanomuse vault set …`, the `config.toml`
    lines, restart) with copy buttons; there is no sign-in button on purpose, the
    credentials stay in your own vault.
  - **Services** — the catalogue (`src/connectors-catalogue.ts`, about seventy remote
    MCP servers: Notion, Linear, Atlassian, Asana, GitHub, Sentry, Vercel, Cloudflare,
    Supabase, Stripe, PayPal, Figma, Canva, Dropbox, Box, Hugging Face, DeepWiki…), each
    with its address and how it lets a client in. *Connect* asks the server itself
    (`initialize`): an **open** server is connected at once; a server that speaks **MCP
    authorization** opens the sign-in page in the system browser — protected-resource
    and authorization-server metadata, dynamic client registration (RFC 7591), PKCE,
    `resource` (RFC 8707), the loopback callback at `127.0.0.1:38417/oauth/callback`,
    refresh before expiry — and the sheet waits with *Open again*, *Try again* and
    *Start over* (a fresh registration, for a server that forgot ours); a server that
    wants a **key** asks for it in a sheet that says where the vendor hands it out. The
    rows under the search field also search the public **MCP Registry**
    (`registry.modelcontextprotocol.io`) once two characters are typed, and **Connect by
    address** takes any Streamable HTTP URL, with a key or a pre-registered OAuth client
    under *More options*. Credentials live in `$DSH_HOME/nanomuse/connectors.json`,
    this computer only, and never reach the model: the agent's `dsh-mcp-client` is
    pointed at a **loopback proxy** (`/c/<id>/mcp`, guarded by a secret header) that
    adds the token or key, refreshes it, filters `tools/list` to the switched-on tools
    and refuses `tools/call` on the rest; the tools appear as `mcp__<service>__<tool>`
    and the preset row `nanomuse-connectors-tools` mounts one client per connection and
    follows the page (connect, switch, disconnect — no restart). A connection whose
    refresh is refused turns to *Needs sign-in* with *Sign in again*; a key is replaced
    in place.
  - **Preset** — every MCP server configured in the agent preset by hand
    (`@deepseek-ai/dsh-mcp-client` rows), read-only here, with *Add a connector*
    opening the preset.

  What Muse has and this does not: the per-action permission dropdowns (ours is the
  permission preset plus the tool switches), and services whose MCP server wants a
  client registered with the vendor beforehand (Zapier, Heroku…) — those are in the
  catalogue as *key* or *address* rows, not as a sign-in.
- **Computer use** — the system permissions (macOS), keep awake, the risk note.
- **File system access** — the folders the agent uses (home, the Library, Downloads,
  nanoMuse's own files; each opens in the file manager), the rules (reading anything you
  name; writing under the chat's permission preset, asking outside its folder; the
  sandbox), and *Full Disk Access* on macOS.
- **Dictation** — the harness's own voice input (local SenseVoice; switched on in
  Plugins, a microphone appears beside Send, audio stays on the computer), the microphone
  permission on macOS, and how to use the system's dictation into the composer.
- **Devices** — this computer (its name, the remote-control switch that lets the phone
  run things here) and the other devices on the account, online dots, *Forget*.
- **Permissions** — one page that says what the agent may touch (computer use, files,
  microphone, connectors, other devices with the remote-control state), each row opening
  the page with the switch; how it asks (the permission presets, from the chip above
  the composer); the recent approvals.
- **Wallet**, **Secure storage**, **Message channels** — Muse's pages, with what is true
  here: no payment method is held and nothing is bought from a chat (the agent stops at a
  checkout and the usage lives under General); which files on this computer hold what
  (the account's login, the agent's profile, the rooms and documents, the faces — each
  with its path, *Show the folder*) and what is never kept (the system keychain, your
  passwords); which channels reach the agent (this desktop, the browser, the invite link
  when signed in, your other devices) and that no third-party messenger is wired in.
- **Data controls** — *We take your privacy seriously* with the privacy policy, *Help
  improve nanoMuse's AI models* (the relay's switch, with how many turns it kept and
  *Delete*), as on every other app; then *On this computer*: **Import memory**,
  **Download your agent data** (a zip in Downloads — the account snapshot without the
  sign-in token, the look and faces, the rooms, memory, and the chats as the harness
  keeps them; shown in the file manager) and **Reset** (memory, the rooms and the local
  look go, the account signs out; the chats stay).
- **Help & support** — the docs, the site, discussions, report an issue, the version.
- **Legal** — the licence, the Meta trademark notice, the acknowledgements (DeepSeek
  Harness, OpenMinis), the privacy policy and the terms.
- **Advanced** — every page another plugin registers (the harness's plugin manager,
  archived sessions…), grouped at the bottom so they are there and out of the way.
- **Sign out** at the foot while signed in. Signing out (or *Reset*) takes the window
  back to the welcome sheet, the way a fresh install starts.

Wallet, secure storage and message channels are not there: the Cloud has no wallet —
members have an allowance ([cloud.md](cloud.md#allowance)) — nanoMuse keeps no
passwords for the agent, and messages reach you through the phone app's notifications
rather than a messenger.

## The rail's other rooms — Feed, Ideas, Goals, Library

**Muse.** Four more rooms on the rail: a *Feed* of posts the agent makes (digests with
pictures, like / discuss, a text that steers future posts); *Ideas*, proactive
suggestions by life area, each a card with why, what it includes, how it works, *start
now*; *Goals* with categories, running automations (cron-like) and a dated timeline;
*Library*, everything generated — documents (a markdown editor), web artefacts, images,
videos, podcasts, system files.

**nanoMuse on dsh.** The four rooms are on the rail, in Muse's order (Chats, Search,
Feed, Ideas, Goals, Library, Devices), each one `main` panel of the harness's layout,
so the chat column stays where it is and a room opens in its place. One host service
(`nanomuse-rooms`, `src/rooms.ts`) keeps them in `$DSH_HOME/nanomuse/rooms.json`,
serves `/nanomuse/rooms/*` and streams changes to the browser half:

- **Feed** — posts the agent writes for you in a hidden chat (a batch when the room is
  empty and then every few hours, from your *feed instructions*, your goals and the
  profile): title, Markdown body with links inline, a picture when the page it read had
  one, ♡ and **Discuss** (a side chat opened on the post). The sliders icon opens the
  instructions sheet; a dot on the rail marks posts newer than your last visit. The
  agent can also post from any chat with `feed_post`.
- **Ideas** — suggestions in groups (*For you* first, then by theme), each a card with
  what it includes, how it works and **Start now**, which opens a chat with the idea as
  the brief; started ideas get a green check.
- **Goals** — *● Tracking* list with categories (health, relationships, money, career,
  interests, productivity), *Create goal* in the category's words; each goal is a chat
  of its own that the agent names and keeps a one-line status for (`goals_room_update`),
  **In progress** automations from the harness's schedule plugin (the agent sets them up
  in that chat; *Check in* runs one now), and a timeline grouped by day from the chat's
  turns.
- **Library** — shelves (All, Documents, Web; Media: Images, Videos, Podcasts; System
  files at the foot), *Select*, *+ Create…* (a brief → a chat that writes the file under
  `~/nanoMuse/Library` — `构件` in Chinese — with the workspace-write preset), *Recent*
  and a card grid; a viewer and a Markdown editor for text, pictures and media inline,
  *Open* / *Show in folder* for the rest. Everything the agent delivers with `present`
  lands here, and `library_add` lists a file without delivering it.

Rooms need a model that answers; signed out, they say so. The hidden chats the feed and
ideas write in are archived once parsed, so the chats column stays yours.

## The hamburger

**Muse.** Settings; report a bug (with a screenshot attached).

**nanoMuse on dsh.** Settings (with its shortcut), Keyboard shortcuts, Schedules and
the harness's other panels (Plugins and whatever else is installed), collapse / expand
the chats column, *Report a problem* — under the desktop shell a screenshot of the
window goes to Downloads and the GitHub issue page opens with the build's facts filled
in (a toast says which file to drag in); in a browser it opens the issues page.
Everything dsh has that Muse does not — the plugin manager, the panel list, archived
sessions, developer tools — is reachable from here or from Settings → Advanced and
nowhere else.

## Not in Muse, in nanoMuse

- **The account on every device.** Sign in on the phone with the same number and the
  desktop's status line counts it; *Reach* lets either side ask the other for something
  ([hub.md](hub.md)).
- **Any model, your key.** The relay's models for members, a DeepSeek key, or any
  OpenAI-compatible provider the harness supports.
- **Open source, no closed component.** The bundle is GPL-3.0-or-later; the harness is
  MIT and travels with its notice; the About row says so.
