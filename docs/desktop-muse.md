# The desktop window, screen by screen

> What the nanoMuse desktop on DeepSeek Harness looks like and does, page by page: the
> window, the first run, the profile and the face, computer use, Settings, the rooms and
> the hamburger menu. Interface only; the plan and the record of the work are in
> [harness.md](harness.md).

The desktop app here is **DeepSeek Harness plus the `dsh-nanomuse` bundle**
([harness.md](harness.md)). dsh brings the loop, the tools and a complete web app with
seats a plugin can take; the bundle takes the seats that give the window the shape the
phone app has, hides the harness's own controls behind *Advanced*, and adds what the
account brings: the same agent on every device, Reach, an open model layer.

In the chat composer, press **Shift+Enter** to add a line break and **Enter** to send. The Enter setting under **Advanced → Harness** chooses how a message is delivered while an agent is busy; it does not change the line-break shortcut.

## The window

One window: a narrow icon rail on the far left, a column of chats next to it, the
conversation in the middle, the agent's face and name pinned above the conversation with
a one-line status that changes as it works, and a composer at the bottom whose send disc
becomes a stop square while a turn runs. Light, dark and system themes; nothing
decorative, every surface a flat tone one step from its neighbour. It comes from dsh's
`sidebar` seat and a stylesheet over the harness's stable DOM hooks (`data-composer-card`,
`data-chat-flow-kind`, `data-approval-key`…):

- The rail, top to bottom: Chats (a dot while the agent works), Search, Feed (a dot
  for posts you have not seen), Ideas, Goals, Library, Devices; a spacer; the hamburger
  at the foot (Schedules and the harness's other panels live in its menu). No face on
  the rail: the face is the pinned header and the profile
  panel. On macOS the window has no title bar: the traffic lights sit over the rail's
  empty top, which is a drag handle, and full screen takes the clearance away. Windows
  gets the same frameless window with the system's own caption buttons drawn over the
  top right (`titleBarOverlay`, recoloured with the theme); Linux keeps the window
  manager's bar, since there is no portable overlay there. On Windows the pages whose
  top bar has buttons at its right end (Feed, Goals, Library and its file viewer, the
  document editor, the profile panel, the first run, Plugins, Schedules, the right-hand
  dock) leave the caption buttons' width free there, so those buttons sit to the left of
  them; a task's details, a narrow column at the top right, moves its tabs down below the
  caption buttons instead. Full screen and the split pane, whose bars start lower, get no
  extra space.
- The chats column: a *Search* field with a *···* menu (archived chats), **Main chat**
  (one session that stays at the top, the first one or the one you chose with *Make
  main chat*) and **Side chats** with a *+*: every other session, pinned first, each
  with a *···* for *Make main chat*, *Pin*, *Rename* (inline), *Archive*. A blank
  session reads *New chat*; a dot marks a running one, a mark one that waits for you.
  It collapses to the rail alone. The column shows the account that is signed in: a
  synced conversation remembers the account it came from, so another account's
  conversations stay on this computer, hidden from the column and the search until that
  account signs in again, and are never pushed under a different account; a change of
  account starts the pull over from the beginning. Signed out, everything local is shown.
- Above the conversation, in the harness's `conversation.header.leading` seat, the face
  and name are pinned at the top centre with the status chip: *connected* / *not signed
  in* / *thinking…* / *Hands · step N · what it is doing* / *Reach · step N · on Laptop
  B: …* / *waiting for you*; a *Stop* button beside it while a turn runs. The chip tints
  while the agent works and while it waits for an answer. Clicking the face opens the
  profile panel. At the top right, *Invite* (with an account), then the harness's
  right-sidebar toggle; the harness's own title row, tabs (*Conversation* / *Trace*)
  and session actions are hidden: the chat rows carry rename, pin and archive.
- The conversation is monochrome, as on the phone: your messages are ink pills on the
  right (black with white text in the light theme, white with black text in the dark
  one), the agent's are large-radius grey pills a step off the canvas on the left,
  timestamps and the per-message actions on hover only; a link inside your pill keeps
  the pill's text colour, underlined. The header is a scrim over the conversation rather
  than a bar: messages scroll under the face and dissolve into the canvas, and no line
  runs under it. An empty chat has no greeting and no workspace or preset chips: the
  composer waits at the bottom and opens the workspace picker itself when a
  workspace is needed.
- The composer is one pill: *+* (attach), *Message*, the send disc (the stop square
  while a turn runs); the send disc and the harness's scroll-to-latest disc are the same
  ink as your pills, with the glyph in the opposite colour. In an active chat it keeps
  the same clear gap above the window edge that the harness dock normally provides,
  even though the dock itself stays hidden. The compact model control stays beside the
  composer; a model that supports adjustable reasoning also exposes its documented level
  there for this chat. The permission mode and plan toggle are hidden (the four job defaults
  live in Settings → Models, dsh's own Models page is under Advanced, and the default
  permission mode is in General) and come back with *Show DeepSeek Harness controls* under
  General. The microphone appears when the harness's voice input is switched on in
  Plugins (Settings → Dictation says how).
- Theme: the harness's light and dark palettes are overridden to the app's own tones (`#f9f9f9`
  surfaces with a plain white chat canvas, `#000000` user pills and `#f2f2f7` agent pills
  in the light; `#171717` with `#ffffff` user pills, `#242424` agent pills and `#2b2b2b`
  fields in the dark) and the accent follows the face's colour on the account, so a face
  coloured on the phone colours the desktop's lights and links too. The desktop shell paints the
  window in the same base colour, so a resize never flashes white in the dark.

## The first run

The phone's pages (`FirstRunSetup` on Android), full-window, in
the harness's `settings.onboarding` seat (we take the shipped step's id, so a fresh
install meets the agent instead of being asked for a DeepSeek key). The host keeps the
state in `$DSH_HOME/nanomuse/firstrun.json` (`src/firstrun.ts`): *done* once Start was
pressed, the permissions page seen, which source answers. The pages are therefore never
skipped on a fresh install and never shown twice:

1. **Welcome**: the app's mark (the avatar comes with the conversation, on the Meet page),
   *Welcome to nanoMuse*, the three feature rows (chat, hands, reach), the community notice,
   one blue *Sign in* pill and *Use your own API key instead*, which goes to the models page
   with no account (the sign-in can come later; *Skip for now* there with no key saved is
   Welcome again). Sign-in
   is the phone's: *Phone number or e-mail* with the line that a mainland China number
   gets an SMS and anything else an e-mail, the code boxes that verify themselves on the
   sixth digit, *Try another way* for a password (`/v1/auth/code`, `/v1/auth/verify`,
   `/v1/auth/login`).
2. **Set a password** (a fresh account only; *Later* skips it).
3. **Which model answers**: the Cloud account's models, or your own key.
4. **Choose models** (own key only): the providers of the catalogue
   (`assets/providers.json`, the same list as the phones' and the web app's), the ones for
   where you are first (Alibaba Cloud Bailian in mainland China, one key for chat, the
   hands, pictures and clips; OpenRouter and then OpenAI elsewhere), each row saying what it
   covers (*chat · screen operation · pictures · clips*), with *Get a key* opening the vendor's
   key page and *Add key* taking the key right there (it goes to the credential store under
   `NANOMUSE_KEY_<PROVIDER>`; `cloud.json` keeps the name only). Under OpenAI, **Sign in with
   ChatGPT**: a Plus, Pro or Team plan signed in through OpenAI's page, which covers chat and
   the hands only (no pictures, no clips), with the one honest line that OpenAI's terms
   cover using a ChatGPT plan inside OpenAI's own Codex and other apps have had this access
   cut off before. *More ways* folds out the rest of the catalogue, the servers on this
   computer (Ollama, LM Studio, vLLM) and any OpenAI-compatible endpoint by hand. *Skip for
   now* until a key is saved or a sign-in finished; *Continue* then.
5. **Allow nanoMuse to use your computer?** (macOS only): *Accessibility* and *Screen
   Recording* rows, each with *Allow* that asks the system through the desktop shell and
   turns into a green check as the system grants it (polled, and again when the window gets
   focus or the page becomes visible; one hook, `permissions.ts`, behind every place that
   shows a permission); once *Allow* has been pressed the button reads *Open System
   Settings*. The entry to switch on is **nanoMuse Computer Use**, the small helper that
   takes the pictures and moves the mouse for the app ([desktop.md](desktop.md#macos-permissions));
   the rows name it, and the helper restarts by itself once the grant is given, so the app
   does not. A build without the helper (before 0.1.38) is the app itself: the shell makes one
   capture attempt before it opens the pane, so nanoMuse is on the pane's list, and when the
   permission is granted while the app runs a dialog says macOS applies it only to freshly
   started apps, with *Restart now* (`relaunch` over the bridge). *Try it* rows (a test
   screenshot, a mouse move) and the
   runtime row say whether it works (the row names the binary and, when its last start for
   the hands failed, why, in the host's words), and a black capture gets its own notice with
   *Relaunch*.
   On Linux and Windows the page is skipped.
6. **Meet <name>**: the face, *Start*.

Start binds the **main chat** (the agent's own folder, `~/nanoMuse`, registered as a
workspace so the composer is live) as the **first conversation**, the phone's
`FirstConversation`: the app speaks first (three scripted lines, no tokens, never in the
model's history) and asks what to call you. From there the model does the talking and
reports what happened in a small `nanomuse-naming` block at the end of its reply (the
address, its name suggestions, the name it got); the chat shows the suggestions as the
naming card (*NamingCard*, a tap or a typed name), and the phase moves on that block and
on nothing else: a reply without one means the person talked about something else, the
model helped and steered back. When the agent has its name the first run is over: the
Feed's first day is written, the daily routine is set.

Help & support → *See the first run again* reopens the pages on purpose (the first
conversation does not repeat).

## The profile and the face

The face at the top opens the agent's page, the phone's
`AgentProfileScreen`, 310 px on the right beside the chat (the chat makes room; × or
Escape closes it): the avatar at 86 px with a pen (**Change avatar** puts the phone's
words in the composer ("Change your avatar to …", the chat flow below), **Edit name**,
**Avatar studio…** (the dragon, an emoji on a colour, or a drawn face, written to the
account and worn on every device)), the name, *online* / *Not signed in* / *Offline* or
what the agent is doing right now, a share button (a card with the face and the name, as
a picture to save or copy), and a segmented control of four tabs: **Activity** (the
sessions and the hub's notices, *Today* and *Earlier*), **Approvals** (the per-app
*Always allow* grants with **Revoke**, each saying when it holds in one chat or one task only, *Manage permissions* → Settings → Computer use,
then what you allowed or rejected on the approval cards, with when; kept on this
computer), **Daily** (the routines; *Manage routines* opens the harness's schedules
panel), **Soul & memory** (what the agent remembers about you, one line each): a
field to add one, × to forget one, *Import memory* (a sheet: paste what another
assistant knew, one line per memory; see the [migration guide](migration.md) for limits
and the paths for documents and connectors), and the agent's description when the account has
one. The agent writes memory itself with the `remember` tool when you tell it something
you will expect it to know next time, and every chat's prompt carries the list back
(`rooms.json`, this computer only). *Change look* has the dragon, an emoji on a colour,
and **Draw one**, the avatar studio: describe the character, pick a style (the 3D
toy look by default), choose an image provider and key of your own, *Draw four*,
and the four candidates come up in a 2×2 grid with *Option 1–4*; *This one* draws the
other poses from the pick (working, waiting, happy, oops) and the new look is on, for
every device of the account. The pictures go directly to the selected provider of your
own (or to a self-hosted relay that explicitly advertises media), the browser squares each
still to 512 px WebP, and the host writes the face to the account (`PUT /v1/me/profile`
with the `face` map) and pulls it back under `faces/<id>/`. Signed out, the face is worn
on this computer alone: the stills are already here, so they are kept under `faces/<id>/`
and the look is written locally, without another picture; a later sign-in pulls the
account's look over it, as with an emoji chosen while signed out. The prompts are the
runtime's, so a face drawn on the phone or here comes out alike.

**A new look from the chat** is the phone's `AvatarFlow`, word for word: "change your
avatar to an orange cat with a scarf", "把你的形象换成一只橘猫", "become a robot" (the
same regular expressions, `src/avatar-flow.ts`) are caught before they are sent; a card
above the composer names the provider that will draw; *Draw* brings the four candidates
up numbered in a 2×2 grid,
and you pick by clicking or in words ("the second one", "第三个", "regenerate"), then
*Finalizing* draws the other poses, the look goes on for every device, *Share avatar*
offers the card. Once it is on, the host leaves the phone's memory line (`- <date>: the
user changed my avatar to "…"`) and asks the agent to say so in one sentence and write
the `nanomuse-avatar` fence, which the chat shows as a small card with the new face. The
agent's own `draw_new_look` still opens the studio for anything it wants to propose.

**The face moves.** The face is animated per state: the dragon's four states
(idle, working, waiting, happy) are the phone app's short clips
(`assets/dragon-<state>.mp4`), played silently in a loop wherever the face is 44 px or
larger (the header, the profile panel, the stage's cursor marker), with the still as
the poster, and the still alone below that size, when the system asks for reduced
motion, or where a list wants a quiet picture. A drawn face gets clips of its own, as on
the phone: four 4-second clips (idle, working, waiting, happy) drawn from the face by
`wan2.2-i2v-flash` through your own Bailian key, or a self-hosted relay with its legacy
media proxy explicitly enabled (`src/video.ts`,
`src/motion.ts`; the phone's prompts word for word), kept under `avatar/motion/` on this
computer and served by the faces route (`/face/<id>/<state>.webp|mp4`), played in the
header, the sidebar and the capsule. Signed in, the clips travel with the face (relay
0.29): a clip drawn here is put up as a file and named in the profile's `clips`, and a
clip another device drew lands here instead of being drawn again, so a face is animated
once per account. *Settings → Media* has *Animate the avatar after a
change* (on by default), *Make / Redo clips* and the models used; the studio's cost
estimate counts the clips. Until the clips are there, or with the setting off, a drawn
face and an emoji move the way CSS can: a slow breath while idle, a sway while the agent
works, a small hop when it waits for you.

## Computer use

Hands are the runtime's `computer_screen` / `computer_act` over
MCP, so what the model sees is the screenshot it asked for and the status chip says
*Hands · step N · click "Save"* while it works. (From 0.1.34 to 0.1.39 the controlled
screen was also shown inside the window as a dimmed live stage; 0.1.40 dropped it for the
trajectory below: a picture-in-picture that follows the hands is one more thing moving,
and it cannot be looked back at.) The harness's approval card is restyled
into the permission card (a shield, the headline, the detail, *Allow once* in blue
first and *Reject* in grey), and every answer is written to the agent page's
*Approvals* tab; the Sentinel's reasons ([sentinel.md](sentinel.md)) are in the
headline. For a step of the hands, a strip above the card adds *Always in this chat* and
*Always in <app>* (the harness's card has no room for them; the app is the window title's
first part). The same question, *Allow once*, *Always in this chat*, *Always in <app>*,
*Deny* (the host's `ApprovalDesk` sits first in
the `approval/request` waterfall and answers for the card), is on the **capsule**, the
small always-on-top pill the shell shows when the nanoMuse window is not in front, so
you can answer from wherever you are.
*Always in <app>* writes a `computer_app:<app>` grant: the hands' tools in that app are
allowed without asking until you revoke the grant, on the agent page or under Settings →
Computer use → *Always allowed*. *Always in this chat* writes the same grant with the
chat's session id and title: it holds in that chat only, which is what a scheduled task
needs (its runs land in the same chat), and its row in the lists says *Only in the chat “…”*.
While a scheduled task runs (its reminder opened the turn), the strip and the capsule offer
*Always in this task* in place of *Always in this chat*: the grant also keeps the task's id
and title and holds only in the turns that task starts, until someone writes in that turn;
a turn that runs two tasks at once needs a grant for each. Its row in the lists says
*Only in the scheduled task “…”*, and says so once the task is deleted.
The grant names the app, not the person or the words: in that chat, the hands may send
anything to anyone in that app. Settings → **Computer use** shows the two macOS
permissions with *Allow* and *Open System Settings* (through the desktop shell; the
first time the hands are about to start, the shell asks for them in order with a word on
why, the phone's and Codex's way: Accessibility, then Screen Recording for nanoMuse
Desktop, which since 0.1.36 is the binary that captures and clicks; the bundled
`nanomuse` runtime only needs them when it runs without the shell), *Keep the screen
awake while it works* (the shell holds a power-save
blocker while a session runs) and the note that anything that sends, pays or deletes is
asked first.

**Holds: whose turn it is.** When the agent needs you (a password, a captcha, a choice
it should not make) it calls `computer_act` with `action: "hand_over"` and a `reason`;
the host opens a *hold* (contract C1: `{type:"hold", tool:"computer", status:"on",
by:"agent", reason}`), the trajectory card in the chat says **Your turn · <reason> ·
Done**, the capsule says it outside the window (amber, the glow amber with it), and the
tool call waits (up to ten minutes) until you press **Done**. **I'll take it**, on the
trajectory card and on the capsule, opens a hold yourself (`POST /nanomuse/cloud/holds`)
so the agent pauses before its next hands call while you use the mouse; *Done* resumes.
Questions keep *Open*. Stop (the square) still cancels the turn.

**The operator.** The hands themselves are the shell's (`src/operator.ts`, a port of
UI-TARS-desktop's `NutJSOperator` on `@computer-use/nut-js`): the screenshot through
Electron's `desktopCapturer` at the display's size (on a Mac, through the helper
*nanoMuse Computer Use* and ScreenCaptureKit instead; see [desktop.md](desktop.md#macos-permissions)),
the pointer moved straight to the
point and left there 100 ms before the click, drags, scrolls, typing through the
clipboard for anything beyond ASCII, the hotkey table (`ctrl` is ⌘ on a Mac). The
runtime's `nanomuse mcp` reaches them over a loopback HTTP server the shell starts per
launch (`NANOMUSE_OPERATOR_URL` / `NANOMUSE_OPERATOR_TOKEN` in its environment, which
the preset passes through to the MCP server), so the model's coordinates (pixels of
the picture it was shown) are mapped once to the operator's screen pixels and land
where it pointed, on a scaled display as on a plain one
([gui.md](gui.md#hands-on-the-computer-the-picture-is-the-unit)). Without the shell
(`nanomuse` run on its own) the runtime falls back to `pyautogui` / `xdotool`.

**Breathing, not flowing.** Since 0.1.40 nothing in the desktop app runs round a rim,
sweeps across a surface or shimmers: every light that says "working" (the dot by a
chat's name, the status dot in the header, the dot of another device's turn, the
thinking dots under a running turn, the microphone while it listens, the glow, the
capsule's ring and bars, the trajectory's live dot) breathes at the phone's rhythm,
2.4 s in and 2.4 s out, ease-in-out, between a dim and a full light. One-shot motions
stay (a card sliding in, the marker locking on, the two ripples of a click), and so do
the face's moods and the plain spinners. Under the system's *reduce motion* setting every
breathing light is a steady light and the marker's arc stands still.

**The glow.** While the hands have the screen, the shell puts a transparent, click-through,
always-on-top window over the whole display (UI-TARS's ScreenMarker, in the phone's
vocabulary: `HandsStage.kt` drawn for a desktop): a light breathing along the four
edges, 7 % of the shorter side deep with a 1.5 px hairline at the rim (the action blue
while the hands work, amber while a hold is on), and at the exact point the operator
acted on, the **marker**: a soft halo, a 12 px ring in the action blue with a cyan arc
turning round it, a dot with a white core at the centre, and the action's name in a dark
pill beside it (to its left near the right edge). It locks on in 220 ms from 1.8× and,
for a click, ripples twice as the click lands; for a drag it draws the path as a dashed
line from blue to cyan with an arrowhead and a landing ring at the far end and sends the
ring along it; typing, a key chord, an app opening and a wait, which have no point on the
screen, write their name where the last ring was. The marker fades 1.6 s after the
action. It comes from the operator itself (its own fractions of the display), not from
the client's reading of the tool call, so it is where the click went; when another
backend acts (the runtime's own hands), the client's point stands in, without words. The
glow is up for the whole run, from the turn's first `computer_screen` or `computer_act`
call to the turn's end, through the seconds the model thinks between two steps (the host
says which session has the screen in `hands.run`; the glow and the capsule used to follow
the calls in flight and went dark between every two), and it goes 400 ms after the turn
ends, after *Stop*, or after five minutes without a call. The glow cannot take focus or a
click, and it, the
capsule and the nanoMuse window itself while the hands have the screen all have
`setContentProtection(true)`, so none of them is in the screenshots the runtime takes;
on Linux, where content protection does nothing, the glow and the capsule step out of the
way for the instant of the capture instead. The phone's long-press ring has no desktop
equivalent (nothing is long-pressed); the phone's face follows the finger only inside its
capsule, so the desktop's face at the pointer (0.1.34–0.1.39) is gone.

**The capsule** is the phone's `HandsCapsule`, sized for a pointer: a pill at most 420 px
wide at the top centre of the work area (ink at 82 %, a white hairline), the agent's face
in a 36 px ring of three hues (the action blue, violet, cyan) breathing with four small
bars, **Step N** and what the hands are doing (*looking at the screen*, *clicked "Save"*,
*typed "hello"*; the last step's words stay while the model thinks about the next),
**I'll take it** and a red **Stop**. It slides in over 320 ms when the
hands start, stays for the whole run like the glow, is shown only while the nanoMuse
window is not the one in front (the chat
shows the same in the trajectory card), and goes 220 ms after the run ends. When the
hands are about to click or drag under it, it moves to the bottom of the work area first
(and back up next time), the way the phone's capsule dodges the finger. A hold turns it
amber with **Your turn · <reason> · Done**; a question the agent asked before a step
hangs under it as a card with *Allow once*, *Always in this chat* (*Always in this task*
in a scheduled task's run) and *Always in <app>* (for a step of the hands), *Deny*. The shell feeds it
over IPC from the main window (`nanomuse:overlay`, `{hands: {active, held, step, title,
text, face, stop, take, x, y, kind}, cards}`) and its answers come back the same way.

**The trajectory** is how a hands run is looked at, during and after it, in the chat: a
card under the run's last tool call (the chat's own row, so it scrolls with the thread)
with the step's screenshot and, drawn on it in the marker's hues, what the hands did
there (the ring and dot of a click (two rings for a double click), the dashed path and
arrowhead of a drag, a chevron for a scroll, the typed text, the key chord or the app's
name in the label pill when the action had no point), a caption in words (*Step 3 ·
clicked "Save" · Finder*), the agent's words from just before the step (its short
reasoning, clamped to three lines on the card), a filmstrip of thumbnails, *previous* and
*next* (the ← and → keys when the card has focus, Home and End for the ends), *Open
large* (the step in a sheet with the whole text) and *Copy this step*. While the run is
on the card follows the newest step with a breathing dot and offers **I'll take it** and
**Stop**; a hold shows *Your turn · <reason>* with **Done**. Pictures are loaded lazily
and only the chosen step's at full size. The host keeps the run in memory
(`src/trajectory.ts`): a *run* opens with the first hands call of a turn and closes when
the turn ends or the hands rest for ten minutes; a *step* is a frame the model was shown
(`computer_screen` returns one, `computer_act` the screen after the action; a
`tools/execute` middleware takes it out of the MCP result with the window title and size
from the first line), with the action the model then took on it and the words of its last
assistant message before acting. The caps: **40 steps per run** (older ones drop off the
front and the card says *the first N steps are no longer kept*), **4 runs in all**, and
the pictures together under **64 MB** (the oldest go first; their steps keep their words
and say the picture is gone). Nothing is written to disk; a restart forgets it. The
browser half reads `GET /nanomuse/cloud/trajectory?session=<id>` (`{rev, runs: [{id,
sessionId, source, device, startedAt, endedAt, firstCall, lastCall, dropped, steps: [{i,
seq, at, width, height, title, action, words, callId}]}]}`, no bytes) and `GET
/nanomuse/cloud/stage/frame?seq=N` for a picture (immutable, cached an hour); the live
state's `trajectory: {rev, sessions}` says when to read again. When the agent looks at a
*phone* through Reach (`device_screen`), the run is a *device* run with the phone's name:
that is what the phone app shows while its own Hands work ([gui.md](gui.md)), seen from
here.

## Skill availability {#skill-availability}

Settings → Skills lists the skills for the selected chat, including disabled skills. You can search their names and descriptions and inspect their source, provider and instruction-file path as plain text. The page does not edit or delete skill files, so tools that share `~/.agents/skills` keep their own configuration.

Choose **This workspace** to change only the workspace displayed on the page, or **All workspaces** to apply a setting throughout nanoMuse. Skills are enabled by default. Global disabling takes precedence: enable the skill under All workspaces before changing its workspace setting. A global enable does not remove an existing workspace disable. Without a selected workspace, only global settings are available; the global list may omit skills supplied by individual chats, even though its settings apply by name throughout nanoMuse. Workspace paths are resolved through symbolic links and use the nearest Git project root, matching filesystem skill discovery; subdirectories of the same project share a setting.

Settings apply to the effective skill name, including same-named copies from different sources. Disabled skills remain visible in this manager, but are excluded from the agent's skill catalog and blocked by its skill loader. These controls affect subsequent skill discovery and loading. They do not delete shared files or revoke tool permissions; use Settings → Permissions for authorization rules. Instructions already loaded into a conversation remain in its history. Workspace controls require a live agent context using the managed skill registry. A chat that has not run, or a custom preset with an unsupported skill service, is shown read-only; opening the chat alone does not establish support. You can still select All workspaces to manage global preferences. Workspace changes are checked against the selected session and its canonical path on the server. If settings cannot be read, the page disables changes and explains the limitation. An incomplete catalog is marked so missing entries are not mistaken for disabled skills.

## Settings

A dialog with a sidebar, from the harness's `sidebar.settings` seat with its
stock General plugin switched off in the bundle layer. A link on one page that opens
another (*Add a provider* on Models opens Account's ways on; the account card on General
opens Account; *The sandbox* on Files opens Agents) leaves the way back at the top of the
page it opened, named for the page you came from; a pick in the sidebar starts fresh.

- **General**: the **account card** (the masked identifier or *Sign
  in*, opening the Account page), **Usage** (the plan and its bar: *Member* /
  *Unlimited*, or the free allowance with what is left and *Upgrade*), **Language** (the
  harness's own row in our card), **Appearance** (the harness's light / dark / system
  switch; the accent follows the face), **App behavior** when the desktop shell is there:
  *Open at login* (a login item; a freedesktop autostart entry on Linux), *Show in the
  menu bar* / *system tray* (an icon with *Open nanoMuse*, *New chat*, *Quit*), *Quick
  chat with ⌥ Space* (Ctrl+Alt+Space elsewhere: the window comes up with a fresh chat
  and the composer focused; pressed while it is in front, it steps aside), all kept in
  `desktop.json` under the app's home; **Shortcuts** (*Quick Chat* with its combination:
  *Change* records the next one you press, Esc cancels, *Default* puts the platform's back,
  and a line says so when another app already holds it; and the keyboard reference); **About** (nanoMuse, built on DeepSeek Harness, the licence, and two version
  lines that are always there: *nanoMuse Desktop <app> · harness <bundle>: installed*
  and *Latest 0.1.x: you have it* / *0.1.x is out · Update* / *Could not check · tap to
  try again*; the check reads `nanomuse.cn/dl/index.json` first and GitHub's releases
  second, once a day); and *Developer*: *Show DeepSeek
  Harness controls* (the modes and the workspace browser in place of the chats column; the
  compact model and reasoning control is already beside the composer). The harness's other
  rows (permission presets, font size, link opening,
  Enter to send, performance, session log) live under *Advanced → Harness*.
- **Models** (right after General, since 0.1.41), one row per thing a model does for
  you: **Chat** (*The model that talks with you.*), **Operating the screen** (*Looks at the
  screen and acts for you. Needs a model that can see images.*), **Making pictures**
  (*Portraits of your Muse and the pictures you ask for.*) and **Making clips** (*Short
  clips of your Muse.*), a picker on each. A picker lists nanoMuse Cloud first while
  signed in only when the relay's live menu covers that row, its lane recommendation
  marked *Recommended*, then one group per provider you
  added, each holding only the models that can do the row's job; the value reads
  `<provider> · <model>`. A chat change says *Applies to new chats.*; a hands change takes
  effect at the hands' next step (the plugin restarts `nanomuse mcp` with the new model,
  no cold restart). The hands speak OpenAI's shape only, so an Anthropic or native Gemini
  key is named in one sentence under the row and not listed. A row nothing can do shows
  the gate's sentence (*Pictures need a provider with image models: Alibaba Cloud
  Bailian, Zhipu GLM, SiliconFlow, …*) and *Add a provider*; the page ends with *Add a
  provider*, which opens the ways on under Account. When you have not chosen, a row
  follows the provider new chats answer through (its catalogue default for the job) when
  that is one of your own, else nanoMuse Cloud while signed in only when its live menu
  offers the job, else the first of your providers that can. The hosted Cloud offers
  chat and screen operation, not media generation.
- **Account** (under *Advanced*), the nanoMuse account: sign in or the masked
  identifier, the allowance, the look, *Open Devices*, a line that opens Settings → Models
  with what chat and the hands use now, and the block the own keys share with the account:
  - **Ways on**: your account's row first while signed in (what it covers right now, from
    the relay's model list), then the catalogue in the first run's groups: the region's
    providers, the ChatGPT sign-in, the rest ordered by how much they cover, the local
    servers, the custom endpoints. Each row says what it covers, takes or changes a key inline,
    links to the vendor's key page and has *Remove*; removing a row drops its credential and
    any chat or hands choice that pointed at it. The custom endpoints are one row each (#294):
    a saved endpoint reads its name over its host and has *Rename* beside *Change key* and
    *Remove*; the *Add an endpoint* row under them adds another with a key of its own
    (`NANOMUSE_KEY_CUSTOM`, `NANOMUSE_KEY_CUSTOM_2`, ...) without touching the others, and
    each stands as a group of its own in the Models page's pickers. An endpoint saved before
    this stays the first row. The ChatGPT row runs the bundled runtime's
    sign-in: *Sign in* opens OpenAI's page, the row waits with *Cancel* (and *Open the
    sign-in page* again), then reads *Signed in as ChatGPT Plus* and offers *Sign out*; the
    sign-in covers chat and the hands only, not pictures or clips, and the line about
    OpenAI's terms sits under it. Without the runtime the row says so and stays disabled. A
    sign-in on file comes back after a restart, with its local bridge. Signed out of the
    account, the same block is under the sign-in form, so a key can be changed without an
    account. Once a key is saved, a card asks **Use it for** (*Pick what this key should
    handle. Other model choices stay as they are.*) with a toggle per thing the key can handle
    (chat, the screen, pictures, clips), all on, each naming the model it would get; *Use
    it* switches those rows on the Models page to the provider, *Not now* changes nothing,
    and a footnote says *You can change this any time under Settings › Models.*
- **Media**, the models that draw the face and its clips: the same two pickers as
  Settings → Models' *Making pictures* and *Making clips*, each own provider's models
  (and a self-hosted relay only when it advertises media; the video picker has *Off* too).
  Pictures
  through your own key go to that provider directly (Model Studio's native image API,
  OpenRouter's image API, the OpenAI shape for OpenAI, Zhipu, SiliconFlow, Volcengine and
  xAI), and the studio says *Drawn with <provider> · <model>. Nothing is billed to your
  nanoMuse Cloud account.* in place of the estimate; a Google key draws only through the
  OpenAI-compatible layer. When nothing configured covers pictures or clips the row says who could,
  where you are, with the way to provider setup under Settings → nanoMuse Cloud (the same sentence
  the avatar studio shows in place of the estimate), and with only the ChatGPT sign-in, that pictures and
  clips are not covered by it.
  Below: *Animate the avatar after a change*, *Make / Redo clips* with the state of each
  of the four, and the cost note. When a picture or clip through your own key fails, the
  failure line asks you to fix or choose a provider of your own; hosted Cloud is not a
  media retry.
- **Models**, **Agents**: the harness's pages, unchanged, under *Advanced*.
- **Connectors**, a catalogue: a search field, category chips (*All*,
  *Built in*, *Work*, *Talk*, *Files*, *Developer*, *Data*, *Design*, *Money*,
  *Search*, *Infrastructure*…), **Connected** rows first and then the catalogue, each row
  with the service's brand mark on a white tile (the marks are
  [simple-icons](https://simpleicons.org/), CC0, written into
  `src/client/brand-marks.ts` by `scripts/brand-marks.mjs`; a letter tile where there is
  none) and *Connect* at the
  end; a detail per connector with what it can do (its tools as the server describes
  them, **one switch per tool**), what gates it (the permission preset, the Sentinel for
  the hands and the mailbox), the vendor's documentation, and *Disconnect* (asked
  twice). Three kinds of row:
  - **Built in** is what the agent can really reach: *Hands: this computer* (on when
    the runtime answered; when it did not, the reason: no runtime, a path that leads
    nowhere, or a runtime that did not start, with the start's own error), *Mailbox*, *Calendar*,
    *Address book* (the runtime's connectors, on when their tools arrive through
    `nanomuse mcp`), *Reach: your other devices*, *Web*, *Files*, *Terminal*, the
    rooms, *Schedule*. *Connect* on the mailbox, the calendar or the address book opens a
    **consent sheet** (what the agent gets, who decides, where the
    credentials live), followed by the steps (`nanomuse vault set …`, the `config.toml`
    lines, restart) with copy buttons; there is no sign-in button on purpose, the
    credentials stay in your own vault.
  - **Services**: the catalogue (`src/connectors-catalogue.ts`, seventy-five remote
    MCP servers: Notion, Linear, Atlassian, Asana, GitHub, GitLab, Sentry, Vercel,
    Cloudflare, Supabase, Stripe, PayPal, QuickBooks, Figma, Miro, Canva, Dropbox, Box,
    Hugging Face, DeepWiki…), each
    with its address and how it lets a client in. *Connect* asks the server itself
    (`initialize`): an **open** server is connected at once; a server that speaks **MCP
    authorization** opens the sign-in page in the system browser (protected-resource
    and authorization-server metadata, dynamic client registration (RFC 7591), PKCE,
    `resource` (RFC 8707), the loopback callback at `127.0.0.1:38417/oauth/callback`,
    refresh before expiry), and the sheet waits with *Open again*, *Try again* and
    *Start over* (a fresh registration, for a server that forgot ours); a server that
    wants a **key** asks for it in a sheet that says where the vendor hands it out. A
    service whose authorization server registers no clients (GitHub, Slack, Discord,
    HubSpot, Render, Bitrise, PagerDuty, Box; `clientIdRequired` in the catalogue, and
    any address that turns out that way) gets a sheet of its own: make an OAuth app at
    the vendor's developer page (linked), give it our callback address (shown, copy
    button), paste the client id and, if there is one, the secret; the id is kept like a
    registration, so the next sign-in there does not ask. The
    rows under the search field also search the public **MCP Registry**
    (`registry.modelcontextprotocol.io`) once two characters are typed, and **Connect by
    address** takes any Streamable HTTP URL, with a key or a pre-registered OAuth client
    under *More options*. Credentials live in `$DSH_HOME/nanomuse/connectors.json`,
    this computer only, and never reach the model: the agent's `dsh-mcp-client` is
    pointed at a **loopback proxy** (`/c/<id>/mcp`, guarded by a secret header) that
    adds the token or key, refreshes it, filters `tools/list` to the switched-on tools
    and refuses `tools/call` on the rest; the tools appear as `mcp__<service>__<tool>`
    and the preset row `nanomuse-connectors-tools` mounts one client per connection and
    follows the page (connect, switch, disconnect; no restart). A connection whose
    refresh is refused turns to *Needs sign-in* with *Sign in again*; a key is replaced
    in place.
  - **Preset**: every MCP server configured in the agent preset by hand
    (`@deepseek-ai/dsh-mcp-client` rows), read-only here, with *Add a connector*
    opening the preset.

  Not here: per-action permission dropdowns (the permission preset plus the tool
  switches stand in), and a sign-in for services whose MCP server wants a client
  registered with the vendor beforehand (Zapier, Heroku…); those are in the catalogue as
  *key* or *address* rows.
- **Computer use**: the system permissions (macOS), keep awake, the risk note.
- **File system access**: the folders the agent uses (home, the Library, Downloads,
  nanoMuse's own files; each opens in the file manager, the page grants nothing), the
  rules (reading anything you name; writing under the chat's permission preset, which is
  *workspace-write* unless the Agents page says otherwise: the chat's folder freely, the
  main chat's being `~/nanoMuse`, and outside it a change is refused unless the agent asks
  you for it and you allow it once; *read-only* asks before every change, *full access*
  asks nothing; the sandbox), and *Full Disk Access* on macOS, which is only about reading
  Desktop, Documents and Downloads. The home folder, Downloads and the app's own files are
  outside the main chat's folder on purpose; a chat opened from the Library or on a folder
  of your own writes there.
- **Dictation**: the harness's own voice input (local SenseVoice; switched on in
  Plugins, a microphone appears beside Send, audio stays on the computer; the window grants
  the page its microphone and nothing else, never a camera), the microphone
  permission on macOS, and how to use the system's dictation into the composer.
- **Devices**: this computer (its name, the remote-control switch that lets the phone
  run things here) and the other devices on the account, online dots, *Forget*.
- **Permissions**: one page that says what the agent may touch (computer use, files,
  microphone, connectors, other devices with the remote-control state), each row opening
  the page with the switch; how it asks (the permission presets, from the chip above
  the composer); the recent approvals.
- **Wallet**, **Secure storage**, **Message channels**, three pages that say what is true
  here: no payment method is held and nothing is bought from a chat (the agent stops at a
  checkout and the usage lives under General); which files on this computer hold what
  (the account's login, the agent's profile, the rooms and documents, the faces; each
  with its path, *Show the folder*) and what is never kept (the system keychain, your
  passwords); which channels reach the agent (this desktop, the browser, the invite link
  when signed in, your other devices) and that no third-party messenger is wired in.
- **Data controls**: *We take your privacy seriously* with the privacy policy, *Sync
  conversations between my devices* (the account's switch, with how many chats and
  messages the relay keeps and *Delete synced conversations*) and under it *Also sync
  side chats* (同时同步旁聊; this computer's own switch, off by default; *Off: side
  chats stay on this device. On: this device's side chats go to the account and the
  other devices' side chats come here*; see [every-device.md](every-device.md)), the
  account's record (what the relay keeps of the account's turns in full, those on your own
  keys and the pictures among them, how long this relay keeps a turn; relay 0.29, see
  [cloud.md](cloud.md#the-record)), *Help improve nanoMuse's AI models* (the relay's switch,
  with how many turns joined the training set) and one *Delete* that removes the record and
  the training turns together, as on every other app. From 1.0.7 this computer takes part in
  the record itself: its chat requests to the account carry `X-NanoMuse-Device` and
  `X-NanoMuse-Conversation`, and a turn answered on a key of your own goes up afterwards with
  its pictures as files (`src/record.ts`; never the key or the base URL). Then *On this computer*: **Import memory**,
  **Download your agent data** (a zip in Downloads: the account snapshot without the
  sign-in token, the look and faces, the rooms, memory, and the chats as the harness
  keeps them; a proxy password is left out, and so are links and files over 64 MB; shown in
  the file manager) and **Reset** (memory, the rooms and the local
  look go, the account signs out; the chats stay).
- **Help & support**: the docs, the site, discussions, report an issue, the version.
- **Legal**: the licence, the Meta trademark notice, the acknowledgements (DeepSeek
  Harness, OpenMinis) and the privacy policy (`nanomuse.cn/privacy/`, the page every
  client links).
- **Advanced**: every page another plugin registers (the harness's plugin manager,
  archived sessions…), grouped at the bottom so they are there and out of the way.
- **Sign out** at the foot while signed in. Signing out (or *Reset*) takes the window
  back to the welcome sheet, the way a fresh install starts.

Wallet, secure storage and message channels are not there: the Cloud has no wallet;
members have an allowance ([cloud.md](cloud.md#allowance)). nanoMuse keeps no
passwords for the agent, and messages reach you through the phone app's notifications
rather than a messenger.

<a id="rail-rooms"></a>

## The rail's other rooms: Feed, Ideas, Goals, Library

The four rooms are on the rail (Chats, Search,
Feed, Ideas, Goals, Library, Devices), each one `main` panel of the harness's layout,
so the chat column stays where it is and a room opens in its place. One host service
(`nanomuse-rooms`, `src/rooms.ts`) keeps them in `$DSH_HOME/nanomuse/rooms.json`,
serves `/nanomuse/rooms/*` and streams changes to the browser half:

- **Feed**, posts the agent writes for you in a hidden chat, from your *feed
  instructions*, your goals and the profile: title, Markdown body with links inline, a
  picture when the page it read had one, ♡ and **Discuss** (a side chat opened on the
  post). The room opens on the phone's intro card (*About the feed*: what the posts are
  made of, *Edit preferences*, *Got it*); while it is empty the words say when the daily
  routine runs (*Every day at 08:00 I read what I remember about you …*) with **Write it
  now**; the first day is written when the first conversation ends, and the daily routine
  (08:00, a schedule you can move or switch off under the sliders) is created the first
  time the room opens. A dot on the rail marks posts newer than your last visit. The agent
  can also post from any chat with `feed_post`.
- **Ideas**: the phone's curated list (`assets/ideas.{en,zh}.json`, the same 24 items
  in six sections: Travel, Work, Everyday, Learning, Family & friends, More ideas), each
  row an emoji, a first-person pitch and a line of detail; a row opens a sheet that says
  what trying it creates (*Starts a conversation*, *Creates a routine · 08:00*,
  *Creates a goal*), with **Send to chat** (the idea's words in the composer, for you to
  finish), **Create routine** (a daily schedule at the idea's time in a chat of its own;
  *Routine created. Set the time and details*) or **Start goal** (the goal
  conversation, seeded with the idea); tried ideas get a green check, ⋯ hides one.
- **Goals**: *● Tracking* list with categories (health, relationships, money, career,
  interests, productivity), the agent's one-line status, a progress bar once it has
  reported one and a *Needs attention* flag. **Create goal › <category>** is the
  phone's flow: "I'd like to create a Health goal." goes into the chat you are in (a
  fresh one when it is busy) with the phone's shaping note; the agent asks at most three
  short questions, one at a time (what, why and by when, how often to check) and then
  writes one `nanomuse-goal` fence, which the chat shows as a *Goal created* card (title,
  why, steps, *Checks daily at 09:00* / *every N hours*, *See in Goals*) and the host
  turns into the goal: that chat becomes its home, and a check is scheduled there with
  the harness's schedule plugin (*Time to check on this goal: …*, *First time round: …*).
  Every check, and any turn where progress changed, ends with a `nanomuse-goal-update`
  fence (`goal_id`, `progress`, `status` on_track / attention / done, `note`): a *Goal
  update* card in the chat with the bar and the note, the goal's status, progress and
  timeline updated; the agent may also call `goals_room_update`. *Type it out* in the
  menu still creates a goal from your own words; *Check in* runs a check now.
- **Library**: shelves (All, Documents, Web; Media: Images, Videos, Podcasts; System
  files at the foot), *Select*, *+ Create…* (a brief → a chat that writes the file under
  `~/nanoMuse/Library`, `构件` in Chinese, with the workspace-write preset), *Recent*
  and a card grid; a viewer and a Markdown editor for text (restoring IDENTITY.md or SOUL.md
  to the stock text asks first), pictures and media inline, *Open* / *Show in folder* for the rest. Everything the agent delivers with `present`
  lands here, and `library_add` lists a file without delivering it. Documents of your own
  need no model: the menu beside *Create* has *Blank document* (an empty `Untitled.md` in
  the Library folder, opened in the editor) and *Import Markdown files…* (`.md`, `.markdown`
  and `.txt` files you pick are copied into the folder and listed under Documents; a taken
  name gets a number, a file over 2 MB or of another kind is named as skipped). Other
  formats wait for a conversion to Markdown.

Rooms need a model that answers; signed out, they say so. The chat the feed is written in
is the agent's working room: the chats column and search leave it out while it runs
(`batches` in the rooms view) and it is archived once parsed, so the chats column stays
yours; the request itself goes into that chat as a one-line notice (*Writing today's feed*),
not as a message in your voice. Up to 1.0.4 the chat appeared in the column, with the batch's
prompt as a user bubble, for as long as the batch ran. A `nanomuse-feed` fence the agent
writes in any chat (the phone's way of posting) lands in the Feed too and shows as a
*Posted to your feed* card.

## The hamburger

Settings (with its shortcut; a dot on it and on the ••• button
when a newer release is out), **Update to 0.1.x** when there is one (opens the release
page), **About nanoMuse** (the version line *nanoMuse Desktop <app> · harness <bundle>*,
the licence, GitHub / Releases / Docs / Issues), Keyboard shortcuts, Schedules and
the harness's other panels (Plugins and whatever else is installed), collapse / expand
the chats column, *Report a problem*: under the desktop shell a screenshot of the
window goes to Downloads and the GitHub issue page opens with the build's facts filled
in (a toast says which file to drag in); in a browser it opens the issues page.
Everything dsh has that the window does not show (the plugin manager, the panel list,
archived sessions, developer tools) is reachable from here or from Settings → Advanced and
nowhere else.

## What the account adds

- **The account on every device.** Sign in on the phone with the same number and the
  desktop's status line counts it; *Reach* lets either side ask the other for something
  ([hub.md](hub.md)).
- **Any model, your key.** The relay's models for members, a DeepSeek key, or any
  OpenAI-compatible provider the harness supports. Settings → Models shows four rows:
  **Chat** (the relay's `/v1/models` entries marked and recommended for `chat`),
  **Operating the screen** (recommended for `gui`; hosted Cloud currently recommends
  `Qwen/Qwen3.6-27B-FP8` for both), **Making pictures** and **Making clips**; a DeepSeek entry is shown as
  sighted only when its id says `v4.1`, `vision` or `ocr`. The hands model is written to
  `$DSH_HOME/nanomuse/hands.json` (mode 0600) and handed to `nanomuse mcp` as its
  environment by the plugin's own MCP client, which it restarts when the model changes.
  When a model of your own fails under a turn, the card offers *Use nanoMuse Cloud this
  time* (signed in): that one message again through the account, the chat back to its
  model when the turn ends, the Models page as it was. Nothing falls back on its own.
- **Connectors on every device.** What you connected here (service, label, URL for a
  custom MCP, how it signs in, which device) is published to the account's profile
  (contract C3; never a token or a key: the host refuses any field named like one), so
  the phone and the other computers list it under *On your other devices* with
  **Connect**, and this computer lists theirs.
- **Ways to get a model, by region.** With a Chinese UI, a phone sign-in or a relay
  account in the mainland, the account page lists Bailian first and OpenRouter second;
  elsewhere the other way round, each with *Get a key*.
- **Updates.** Once a day, and on *Check for updates* in About, the host reads the
  mirror's index at `nanomuse.cn/dl/index.json` first (reachable from the mainland, no
  rate limit) and GitHub's releases API when the index does not answer, then compares
  versions; a newer one shows as a dot, an *Update to 0.1.x* menu item and a *Download*
  button for this platform's asset in About (on Linux the `.deb`, or the AppImage when
  the running app is one). The result is kept for a day and read against the version
  that runs now, so an update installed in the meantime is not offered to itself. A check
  that could read neither source (the network down at start, say) is kept for an hour
  only: the host tries again by itself an hour later, and *Check for updates* asks at once
  whatever the cache says.
- **Open source, no closed component.** The bundle is GPL-3.0-or-later; the harness is
  MIT and travels with its notice; the About row says so.
