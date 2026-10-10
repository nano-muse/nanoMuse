# nanoMuse as an app on a simulated phone

Muse lives on a phone: it sits among your other apps, and when it needs you (an approval, a
question, something it finished in the background) it comes through the notification shade.
This directory makes nanoMuse behave that way inside [MobileGym](https://github.com/Purewhiter/mobilegym),
a browser-hosted Android simulator with a launcher, a notification shade and 28 re-implemented
apps (WeChat, Alipay, 12306, …). No device, no emulator: one browser tab.

<p align="center">
  <img src="screenshots/setup.png" width="24%" alt="First launch: connect the phone to your nanoMuse server">
  <img src="screenshots/heads-up.png" width="24%" alt="A heads-up notification from nanoMuse on the home screen, badge on the icon">
  <img src="screenshots/shade.png" width="24%" alt="The notification in the shade">
  <img src="screenshots/app.png" width="24%" alt="Tapping it opens nanoMuse on that chat">
</p>

`apps/nanoMuse/` is an app module in MobileGym's own format (manifest, entry component,
navigation declaration, Zustand store; see the platform's app module contract). It is a thin
shell around the real nanoMuse web app:

- **The app** shows the nanoMuse web app full screen, served by `nanomuse serve` on your
  computer. Everything you see is the same code a real phone gets; the shell only keeps the
  tab bar clear of the simulator's gesture bar.
- **Notifications.** Real phones get Web Push. The simulator has no push service, so the
  module keeps one WebSocket to the server open for the whole simulator session (the store is
  loaded at boot, before any app is opened) and turns the events a phone would be notified
  about into simulated Android notifications: *Muse needs your approval*, *Muse has a
  question*, and the last word of a background pass or check-in. Tapping one opens nanoMuse
  on that chat. A card you decide from another device takes its notification down again; the
  launcher icon carries the unread badge.
- **The first page.** The Android app's welcome page (`FirstRunSetup.kt`): the dragon's face,
  *Welcome to nanoMuse*, the one line, the three rows, a pill. In a checkout it asks for the
  server address: paste the link `nanomuse serve` prints (it carries the access token). The
  token is checked by opening the server's WebSocket once, so the server needs no CORS
  configuration.
- **The phone as the agent's hands.** The module announces the simulator as a *device*: it lists
  the installed apps, and answers the server's requests for the screen and for actions, the
  way the Android app does. The screen is what the Android app sends: a picture (the
  simulator's DOM rendered in the page (`modern-screenshot`) at 720×1600, twice the phone's
  size, so the model reads small text) and a list of up to 120 elements read off the DOM
  (buttons, fields, links, the texts; their centres, boxes and flags, in the picture's
  pixels), with the app and route read off the simulator's OS. Actions go through MobileGym's
  own input API. While Muse works the phone shows the **same capsule the Android app has**: a
  pill at the top with the Muse's face, the step in progress (*第 3 步 · 点击「查询车票」*) and
  **Stop**; before a tap lands, a ring with the action's words marks the target, a trail each
  swipe, a chip what is being typed; a password or code field is not typed into; the capsule
  says *Your turn*, the person fills it in and taps *Continue*. When the agent hands the phone
  over on its own (the server's `hold` event, `by: agent`) the capsule says *Your turn* with the reason under it and
  **Done**; when the person took it (`by: user`) it says *You have the phone* with **Done**,
  and Done tells the server (`POST /api/holds/{id}/done`); the local password turn and a
  mirrored hold are one card, not two. An approval the agent waits for is decided on the
  capsule itself (**Allow once** / **Deny**, `POST /api/approvals/{id}` with scope `once`),
  so the person is not bounced into the app; only a question still becomes a card with
  *Open*. When the task is over (a tick, or
  *Stopped*) the phone comes back to nanoMuse, where the report is, as the Android app
  brings itself to the front; and the capsule follows the server's word on the task
  (`phone.task` in the socket's `hello`) rather than the one `end` message, so a socket that
  drops mid-task does not leave it on the screen. The marks are left out of the
  screenshots. Nothing is touched unless the server's own *Phone* switch is on too (`[gui]
  enabled`, or Connections → Phone in the app); [docs/gui.md](../../docs/gui.md) has the
  rest, including what asks for approval first.
- **Two languages.** The first page, the notifications and the capsule follow the simulator's
  language (`__OS__.locale`, MobileGym's `useAppStrings` convention: `res/strings.ts` holds
  简体中文 and English; where the Android app has the same string, the wording is its).

- **The hosted showcase.** Built with `VITE_NANOMUSE_DEMO=/api/demo`, the first page's pill
  is the Android app's door: *Sign in, free*, nanoMuse Cloud's sign-in page (a mainland phone
  number or an e-mail, a code or the account's password; the relay's refusals in the phone's
  language), then the meet page, whose *Start* asks the *showcase gateway*
  ([`demo/showcase/`](../showcase/)) for a private nanoMuse for this visitor, for a while and
  within a model budget. The browser keeps the sign-in's ticket, so the next visit goes from
  the welcome page straight to a Muse (*Signed in as* the masked number *· Sign out* under the
  pill). A showcase that asks for no sign-in (`DEMO_SIGNIN_REQUIRED=0`) starts on the first
  tap. *I have my own API key* opens the fields for the visitor's own model, *Connect your own
  nanoMuse* the form for a server of one's own, and a line under the pill says what this is (a
  demo in a simulator) and where the app is. A normal checkout has the variable empty and
  never asks the gateway for anything.

The lighter variant needs nothing installed: open the simulator's own Browser app and go to the
link `nanomuse serve` prints. That is the web app as any phone browser gets it (full screen, tab
bar, approval cards) minus the notifications, which is what this module adds.

## Run it

Node 22+, Python 3.11+, a Chromium-based desktop browser. MobileGym's 1.9 GB companion
dataset is optional here: nanoMuse does not need it, the simulated media apps just render empty
without it.

```bash
# 1. nanoMuse, as usual; prints a link with a one-time token
nanomuse serve --port 8787

# 2. MobileGym with the nanoMuse app installed
git clone --depth 1 https://github.com/Purewhiter/mobilegym.git
demo/mobilegym/install.sh mobilegym          # copies apps/nanoMuse into the checkout
cd mobilegym && npm install && npm run dev   # http://127.0.0.1:3000
```

Open the simulator, find **nanoMuse** in the launcher (search works too), paste the link from
step 1, *Connect*. Then go back to the home screen and give the agent something to do from
another tab or the CLI: `nanomuse chat`, or the web app in a normal browser tab: the phone
lights up when it needs you.

To watch it operate the phone, turn the *Phone* switch on (Connections → Phone in the web app,
or `NANOMUSE_GUI_ENABLED=1` for step 1) and ask, in the chat, for something that lives in one of
the simulated apps: "打开微信，看看最新一条消息是谁发的", "用 12306 查一下明天北京到上海最早的
高铁", "给 blank. 回一句「好的，明天见」". The agent opens the app on the simulated phone, works
through its screens, and stops at the send button until you approve.

`install.sh` only copies files; MobileGym discovers apps by directory convention, nothing in the
checkout is edited. Run it again after pulling a newer nanoMuse.

## Notes

- **Origin.** The web app runs cross-origin inside an `<iframe>` (`127.0.0.1:8787` inside
  `127.0.0.1:3000`). That is fine for using it; it only means the outer page cannot script the
  inner one, which is the point of an iframe. The one thing that crosses is a draft: the shell
  posts `{type: "nanomuse:draft", text}` to the web app, which takes it from its parent
  window only and puts the text in the composer (sending is still a tap); the web app says
  `{type: "nanomuse:ready", name}` when it is up.
- **A guest of a page.** `host.ts` exposes `window.__NANOMUSE__` on the simulator's window:
  `open()`, `draft(text)`, `start()`, `reset()`, `language(code)`, `state()`, `subscribe(fn)`,
  the way MobileGym exposes `__OS__`. `start()` is what the welcome page's *Start* pill does,
  for the page around the phone to press once it has reason to think a person is looking; it
  does nothing past a sign-in the showcase asks for, with a visitor's own key, or once a Muse
  is there (`state().startable` says whether it would). `language("en" | "zh")` is the page's
  language: a hosted Muse gets it as its reply language (*Settings › Reply language*), now and
  for the sessions that follow, so what it reads on a Chinese screen is told in the page's
  language; a server of the person's own keeps its setting. The showcase's page (`demo/showcase/site/page/`) puts the simulator in a frame on
  the same origin and uses it for the lines to try beside the phone. On a hosted session the
  web app is opened with `?ui=lite`: the phone layout whatever the window's width, drawn the
  way the Android app draws it (the home chrome, the chats drawer, the five tabs and their
  pages, Settings as a list of rows, the agent page behind the face, the approval card), with
  the first-run setup and the desktop hints off. The Android app's own things (Hands on the
  phone's screen, the system files, the battery and background switches) have no counterpart
  here; the simulator is the screen the agent operates instead.
- **Dark mode.** The web app inside the frame picks light or dark by its own setting (it
  cannot see the simulator's) and tells the shell which (`{type: "nanomuse:theme", theme}`),
  so the strips above and below its frame match it; the first page follows the simulator's
  theme.
- **Deep links.** The OS hands the app `/?thread=<id>`; the shell forwards `thread` and `tab`
  to the web app's own deep links (`docs/app.md`).
- **Not a MobileGym benchmark task.** The module declares its UI states and transitions like
  every MobileGym app, so the platform's analyzer sees it, but nanoMuse's content is live
  server output and is not deterministic; it is here to show the product, not to be graded.

## Layout

```
apps/nanoMuse/
├── manifest.ts               id, names, icon, theme (the web app's palette, the Android app's action blue)
├── NanoMuseApp.tsx           entry: router, theme vars, back handling, deep links
├── navigation.declaration.ts routes (/ and /setup), transitions, UI states
├── navigation.ts             go()/back() over the declaration
├── navigation.types.ts       re-exports the platform's shared types
├── state.ts                  Zustand store: server URL, token, notify and GUI switches, showcase session; wires the bridge
├── bridge.ts                 WebSocket → NotificationService; device announce (capsule: true), screen/act/task requests, Stop, holds and approvals decided from the capsule
├── demo.ts                   the showcase gateway's API (start/end a hosted session), used on the public site
├── gui.ts                    the simulator as a device: DOM → 720×1600 PNG + element list, actions → __SIM_INPUT__
├── stage.ts                  the capsule and the marks (the Android app's look): step, Stop, Your turn / Done, Allow once / Deny, ring/trail/keys
├── host.ts                   window.__NANOMUSE__ for the page around the phone; drafts to the web app over postMessage
├── pages/MusePage.tsx        the web app, full screen (lite on a hosted session)
├── pages/SetupPage.tsx       the welcome, sign-in and meet pages (the Android app's): a hosted Muse on the showcase, own key, own server
├── hooks/useNanoMuseGestures.ts
├── data/                     defaults
├── res/strings.ts            简体中文 and English for the shell, the notifications and the capsule
├── res/icons.tsx             the shell's icons; the launcher icon is the nanoMuse mark
├── res/mark.tsx              the mark: the one-stroke N of assets/brand/nanomuse-mark.svg, as the Android launcher icon
└── res/dragon-idle.webp      the dragon's face at rest, for the welcome page (web/public/avatars)
```
