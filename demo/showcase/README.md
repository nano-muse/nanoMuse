# The public showcase

A page anyone can open: a phone in the browser with 微信, 支付宝, 铁路12306 and the other
[MobileGym](https://github.com/Purewhiter/mobilegym) apps on it, and nanoMuse installed. The
page opens on the nanoMuse app, and a **private nanoMuse is started for you** on the showcase
server (your own container, your own token, phone operation on) for thirty minutes and
within a model budget. Beside the phone are a few lines to try, one set per language ([The
lines](#the-lines)): a new look for the Muse (it draws itself), the apps on the phone operated
for you ("打开微信，看看张伟最新发来的消息说了什么"; "Open Spotify and play Bad Habits by Ed
Sheeran"), a send that waits for the visitor's word, two apps read for one answer, memory and
a reminder; a tap puts the line in the chat on the phone, and anything else can be typed
there. This is nanoMuse's web entry, what [nanomuse.cn/web](https://nanomuse.cn/web/) leads
to.

The page (`site/page/`) is plain HTML and a little script, with MobileGym in a frame on the
same origin as `/phone.html`; it talks to the nanoMuse app on the phone through
`window.__NANOMUSE__` on that frame (open, draft, start, reset, state, subscribe; see
`demo/mobilegym/README.md`) and the app passes drafts on to the web app over `postMessage`.
On a hosted session the web app runs lite (`?ui=lite`): the phone layout at any width, drawn
the way the Android app draws it: the face on its disc with the name tag under it, the round
hamburger and ••• menu, the chats drawer, the five tabs (chat, feed, ideas, goals, library) and
their pages, Settings as the phone's list of rows, the agent page behind the face, the
approval card; and no first-run setup.

**The phone keeps MobileGym's own chrome.** Around the frame are the pieces of
[mobilegym.dev](https://mobilegym.dev/)'s page, nothing cut down: the Gesture Guide on the
left (Back, Home and Recents as keys, since the simulator is gesture-only, and a legend of the
gestures), the State Builder dock on the right with its drawer (session snapshots, the phone's
language, device time / battery / location, a WeChat message or contact, an Alipay balance or
bill, an SMS, a 12306 order, the weather, patched into the running phone), and *Power off*.
They are not copied into this repository: `site/compose.mjs` lifts the markup from the
checkout's `web/index.html` at build time and takes its `styles.css`, `state-builder.js`,
`boot-hero.js` and icons as they are (one default changed: the phone's address is
`/phone.html`), so an upstream change arrives with the next build. One thing is added to the
dock, first in it: nanoMuse's launcher icon, a shortcut: a tap brings the app to the front
(or turns the phone on), and it is lit while nanoMuse is the app on the screen; it carries no
State Builder tab, so their script leaves it alone (`page.js` handles it, reading `front` from
`window.__NANOMUSE__.state()`). Our panel sits beside the phone, two columns wide: the words
(the status, the headline, the notice with the downloads, *Show nanoMuse* / *Start over*, the
fine print) and the lines to try. The phone is scaled to the window's height and the panel is
no taller than the stage, so the whole page is in view at once and nothing in it scrolls (only
in a window shorter than about 600px do the lines scroll inside their column); below 1280px
their chrome folds under the phone, and below 1000px everything is one column, the phone at
its own size, and the page itself scrolls.

**The phone turns itself on, and the Muse starts when a person is looking.** On this page and
in the frame alike the phone boots as soon as the page is there and nanoMuse comes to the
front, so the first thing a visitor sees is the welcome page. Pressing *Start* is another
matter: it starts a container on the server and takes a share of the day's model budget, so
the page does not press it for every load. It presses it (`window.__NANOMUSE__.start()`, what
the pill does) once the stage has been in view for six seconds with the tab in front, or at
the first sign of a hand: a pointer moving over the page, a key, a touch, the wheel. It never
presses it for a browser that says it is driven by a script (`navigator.webdriver`), nor past
a sign-in the showcase asks for (the visitor signs in and the phone's *Start* is theirs), nor
with a visitor's own key, nor after a try that failed (the phone shows why, with *Try again*).
A line tapped in the column before the Muse exists presses *Start* too and waits in the chat.
The thirty minutes and the budget are as before; what changes is who presses the pill. The
phone's language (MobileGym's Settings, Chinese by default) follows the page's switch, and so
does the Muse's: the page sets the hosted runtime's reply language (`PUT /api/settings`, what
*Settings › Reply language* does) to the page's, so a chat read on a Chinese screen is
reported in English on the English page and the capsule's sentences follow. The chat model
still slips into Chinese now and then after Chinese screen text; the setting makes it the
exception rather than the rule.

**The frame on the project site.** [nanomuse.cn](https://nanomuse.cn/) opens on this page in an
`<iframe>` of `https://demo.nanomuse.dev/?embed=1`. In that mode the page has no header of its
own (the site's bar is above it). The site passes its language and theme on the first load
(`&lang=zh`, `&theme=dark`) and afterwards over `postMessage` (`{type: "nanomuse:lang", lang}`,
`{type: "nanomuse:theme", theme}`; only from the project site's origins), and links out of the
page open in the top window, not inside the frame. The page lays itself out in the frame's
height and nothing in it scrolls, so a wheel turned over the frame moves the homepage (the
browser hands a scroll on to the parent when the frame has nowhere to go); over the phone's
screen the phone keeps it. Dark is the page's own surfaces in the site's dark tokens, the stage
and MobileGym's guide and dock cards going dark with them.

## The lines

The column beside the phone is not one list translated twice: the English set stays on the
apps of the phone an international visitor knows by name and the Chinese set on the ones a
Chinese visitor uses, and three ideas (the look, the memory, the reminder) are the same in
both. MobileGym's phone has 27 apps of its own (nanoMuse is the 28th) and every one of them
has an English interface (`res/strings.en.ts`), but the seeded data is Chinese: the contacts,
the chats, the bills, the SMS threads. So the English lines go where that shows least: Spotify, Weather, Reddit,
X, and the Messages thread where the tap that sends is the point. The Chinese set keeps to
what the simulator is for: 微信 and 铁路12306 as re-creations, no 支付宝 statements
([docs/showcase.md](../../docs/showcase.md#never-in-public-material) says why). The texts are in
`site/page/index.html` (`.chip.en` / `.chip.zh`, the text in `data-text`); the switch at the
top shows one set, and the Muse answers in that language.

Every line was run end to end on the showcase's models (deepseek-v4.1-flash for the chat,
qwen3.8-27b for the hands) in a fresh session, and kept only when it finished. What each
costs, measured; the session's share is `SESSION_LLM_REQUESTS` (60) calls, and a screenshot
the operator reads is one call:

| | line | what it shows | calls | time |
|---|---|---|---|---|
| en | Change your look to an orange cat with round glasses | the studio: four faces, then the poses and clips of the chosen one | 1, and 8 pictures | 10 s to the faces, 50 s more for the poses |
| en | Open Spotify and play Bad Habits by Ed Sheeran | one app, a search, a tap on the result | 10 to 12 | 65 to 100 s |
| en | Open the Weather app: will it rain in Beijing tomorrow? | a screen read and reported | 2 to 7 | 40 to 70 s |
| en | In Messages, reply to the latest text with: Thanks, got it | typing, then the Sentinel's card before the send; *Allow once* on the phone | 9 to 10 | 55 to 65 s |
| en | Look at the first post in the Reddit feed and what is trending on X, then tell me in two lines what people are talking about | two apps, one answer | 6 to 16 | 70 to 75 s |
| en | Remember: I have an iced americano every morning / What do I usually drink in the morning? | memory kept and recalled | 2, then 1 or 2 | 12 to 15 s each |
| en | Remind me in 2 minutes to stand up and stretch | a reminder that fires while the visitor is there | 3 | 12 to 25 s, the notice on the minute |
| zh | 换个形象：一只戴圆框眼镜的橘猫 | the studio, as above | 1, and 8 pictures | 10 s, then 55 s |
| zh | 打开微信，看看张伟最新发来的消息说了什么 | a chat read (「明天一起去徒步吗？」) | 5 to 6 | 30 to 35 s |
| zh | 在微信里回复张伟：好啊，几点出发？ | typing, then the Sentinel's card before 「发送」 | 6 to 7 | 40 to 45 s |
| zh | 打开手机上的铁路12306，查一下明天上海到南京最早的一班车 | a date picked, a search, the list read | 7 to 8 | 65 to 70 s |
| zh | 打开天气，看看北京明天会不会下雨 | a screen read and reported | 3 to 9 | 30 to 75 s |
| zh | 张伟约我明天徒步。先在天气里看一眼北京明天会不会下雨，不下雨就在微信里回他：好啊，几点出发？ | two apps and a decision: tomorrow's weather read, the chat read, the reply typed, the Sentinel's card before 「发送」, the answer naming both | 21 | 155 s |
| zh | 记住：我每天早上要喝一杯冰美式 / 我早上一般喝什么？ | memory | 2, then 2 | 15 s each |
| zh | 2 分钟后提醒我站起来活动一下 | the reminder | 2 | 15 s, the notice on the minute |

Two runs of one line differ: the chat model sometimes hands the phone to the operator
(`phone_task`, a context of its own that ends with the task) and sometimes drives it itself
(`phone_act`, every step's screen list staying in the chat), and the second way costs more
calls and far more tokens, since each later call carries every earlier step. The ranges above
are what was seen. The session's tokens (`SESSION_LLM_TOKENS`, 300k) run out before its calls
do on the second way: one such run spent 210k tokens on one line, and the fourth line of that
session was refused.

**One change to the seed.** 张伟's message in 微信 reads 「明天一起去徒步吗？」 on the showcase,
not upstream's 「明天一起去吃火锅吗？」: a hike depends on the weather and hot pot does not, which is
what gives the two-app line its reason to look at the weather before answering him.
`demo/mobilegym/patch-seed.sh` rewrites that one string in `apps/Wechat/data/defaults.json` of
the checkout; `caddy/Dockerfile` runs it after the clone and `site/build.sh` before the build,
and it fails the build if upstream's sentence is not there exactly once (an upstream change
shows up as a red build, not as a demo quietly back on hot pot). His 朋友圈 post and profile are
upstream's. To drop the patch, delete the script and its two call sites.

What the runs taught, for the next line anyone adds: name the app ("打开手机上的铁路12306",
"in the Weather app"); without it the model tries the web first, which has no way out of a
session, and asks the visitor to approve a fetch that cannot work; the old 12306 line went
looking for an MCP server and asked a question instead of opening the app. Ask for what is on
the first screen: the Weather app's home has tomorrow's line, and a goal that wants the
"chance of rain" sends the operator digging for a detail page that is not there. A line that
writes in Notes is 6 to 20 steps (the body field is slow to take focus), so none of the kept
lines does. A line that ends in a message needs the words: told "回他去不去", the model reads the
weather and then drafts three replies and asks which to send (the `phone-messages` skill sends
only on the user's own wording); told "回他：好啊，几点出发？", it types that and the Sentinel's
card is the confirmation. A new text from the compose page is fragile (the send arrow is at the screen's
edge and the operator's taps land beside it); a reply inside a thread sends. One look per
session: a look is eight pictures and four clips, and `IMAGE_PER_SESSION` (12) and
`CLIPS_PER_SESSION` (4) are sized for one.

The container's clock is the visitor's: the phone app sends the browser's IANA time zone
with `POST /api/demo/session` (`time_zone`, the shape of a zone name or nothing), and the
gateway sets `TZ` in the container, so "in 2 minutes" is due in 2 minutes and the Muse
quotes the visitor's time, not UTC. Without it a Chinese reply took the server's `UTC+0000`
for Beijing time and set the reminder eight hours out.

Nothing about the phone runs on the server. MobileGym is a React app: the whole simulated
phone lives in the visitor's tab (~400 MB of *their* memory). The server runs three things:

| | |
|---|---|
| **Caddy** | HTTPS, the static site (the page at `/`, MobileGym + the nanoMuse app at `/phone.html`), `/api/demo/*` to the gateway, and one hostname per session |
| **gateway** (`gateway/`) | Starts a nanoMuse container per visitor, relays the phone's HTTP and WebSocket to it, proxies the container's model calls to the provider with the demo key, keeps the books |
| **sessions** | `ghcr.io/nano-muse/nanomuse` containers on an internal Docker network with no way out; the gateway is the only thing they can reach |

```
visitor's browser ──HTTPS──▶ Caddy ── demo.nanomuse.dev ──▶ /srv/site (the page; /phone.html = MobileGym + nanoMuse app)
   │  the page                   │                      └▶ /api/demo/* ──▶ gateway
   │   └ MobileGym phone (frame) └── <id>.s.nanomuse.dev ─────────────────▶ gateway ──▶ nm-<id>:8787
   │      └ nanoMuse app (iframe)                                                          │
   └──────────────────────────────────────────────────────────────────────────────┘        │
          models, pictures, clips ◀── gateway ◀── /llm/<id>/{main,gui}[/images/*|/api/v1/*] ◀─┘
```

A session is one hostname (`<id>.s.nanomuse.dev`) because the nanoMuse web app and the
MobileGym module both take a server *origin*, and because the browser then keeps each session's
token in its own `localStorage`. The wildcard certificate that needs is why Caddy is built with
the Cloudflare DNS module. The token itself travels as the socket's first frame and in the
fragment of the phone page's address, never in a query string; a page still on the older
`?token=` form is served, but no log line of the gateway (its own, uvicorn's request lines,
httpx's) carries the value: it is rewritten to `token=[redacted]` before it is written
(`gateway/showcase_gateway/logs.py`). Caddy keeps no access log for these two names.

## What the gateway enforces

- **One container per visitor**, `--read-only`, no capabilities, `no-new-privileges`, 512 MB,
  one CPU, 256 processes, tmpfs for `/data` and `/workspace`. Gone after `SESSION_TTL_S`
  (30 min) or `IDLE_TTL_S` (10 min) without traffic, and everything in it with it.
- **No network** from the containers except to the gateway (`docker network --internal`). The
  web fetch and shell tools cannot reach the internet from a demo session; the phone can.
- **The demo key never leaves the server.** Containers get a per-session key and
  `NANOMUSE_LLM_BASE_URL=http://gateway:8000/llm/<id>/main`; the gateway swaps the key and
  forwards to the provider. Streaming passes through; `usage` (asked for on streams) is what
  the budget counts.
- **Budgets:** per session `SESSION_LLM_REQUESTS` / `SESSION_LLM_TOKENS`, per day (Asia/Shanghai)
  `DAILY_LLM_REQUESTS` / `DAILY_LLM_TOKENS`. Over budget, the model call gets an OpenAI-shaped
  429 (`session_budget` / `daily_budget`) and the agent tells the visitor in those words
  (`nanomuse/server/failures.py`): the demo's share is used up, start over or install the
  app, not "the provider is rate-limiting this key".
- **Per visitor (IP):** `PER_IP_ACTIVE` sessions at once, `PER_IP_DAILY` a day. `MAX_SESSIONS`
  overall.
- **Who is trying it** (`DEMO_SIGNIN_REQUIRED=1`, the default): before the phone starts a Muse,
  the visitor signs in to nanoMuse Cloud (the Android app's door: a code to a phone or an
  inbox, or the account's password) on the phone's own pages (`demo/mobilegym`,
  `SetupPage.tsx`). The gateway puts the sign-in to the relay (`POST /v1/auth/code`,
  `/verify`, `/login`, the visitor's address forwarded), notes the account in `VISITOR_DB`: its
  opaque id, the relay's masked identifier (the first three and last four digits of a
  number, `g…@gmail.com` for an address), the channel, and never the identifier itself
  (`VISITOR_DB` is SQLite on the `gateway-data` volume); revokes the device key the
  relay issued for the sign-in (the demo talks to the showcase's model, not to the account's
  allowance) and hands the browser a ticket good for `VISITOR_TTL_S` (thirty days).
  `POST /api/demo/session` wants the ticket as a bearer; without one it answers
  `401 signin_required`, and the phone shows the sign-in. A first sign-in creates the Cloud
  account, with its free allowance, so the day the person installs the app it is already
  theirs. One account is one person wherever it signs in from: `PER_ACCOUNT_ACTIVE` Muses at
  once, `PER_ACCOUNT_DAILY` a day, on top of the address limits. The session log names the
  visitor by the masked identifier; `GET /api/demo/info` → `signin` counts them. The book
  also keeps, per visitor, the address and browser string of the first and the latest
  sign-in or demo and how many sign-ins, and one *visit* row per demo started: when, from
  which address, with which browser, whether it brought its own key, and when it ended with
  what it used (requests, tokens, pictures, clips) and why (gateway 0.3). With
  `SHOWCASE_ADMIN_TOKEN` set, `GET /api/demo/admin` (header `X-Admin-Token`) hands all of it
  to the operator (`?account=<id>` for one visitor's), and the relay's admin page shows it
  (`WEB_ADMIN_URL` / `WEB_ADMIN_TOKEN` there) next to the account; without the token the
  route is not there.
- **Bring your own key:** the visitor can enter a provider URL, model and key on the setup page.
  The gateway keeps them in memory for the session and forwards with them (no budget of ours);
  the container never sees the key. Only `https://` to hosts in `BYOK_ALLOWED_HOSTS` (the usual
  providers), never to an address inside the server's network. The model they name is the chat
  model; the hands get their own on the same key (`qwen/qwen3.8-27b` on OpenRouter,
  `qwen3.8-27b` on 阿里云百炼), and on any other provider the one model does both lanes (a
  text-only model there, DeepSeek's own API say, leaves the hands with nothing to look with).

Two lanes, two models, both set by the operator in the gateway's `.env` (`.env.example` lists
the names; `docker-compose.yml` pins none): `main` (the model that talks to the visitor) is
whatever `MAIN_MODEL` names on `MAIN_BASE_URL` with `MAIN_API_KEY`, and empty means the
gateway's own default, the chat model every nanoMuse client starts with (`deepseek-v4.1-flash`
on 阿里云百炼 at the time of writing); `gui` (the one that reads screens and taps; many small
calls with a screenshot each) is `GUI_MODEL`, and empty means `qwen3.8-27b` on the main lane's
host and key, a fixed default not derived from the chat model; set `GUI_*` to change it or to
split the lanes across keys or providers. A chat model that takes no images (DeepSeek before
V4.1: `deepseek-v4-pro`, `deepseek-v4-flash`) is kept away from screenshots
(`NANOMUSE_LLM_VISION=off`); the operator lane still looks. What a running showcase actually
uses is what `GET /api/demo/info` says (`demo_model`, `gui_model`), not this page.

**The capsule decides.** While the hands work on the simulated phone, an approval the run
raises (a tap on *Pay*, *Send*, *Delete*…) is shown on the capsule over the operated app with
**Allow once / Deny**, answered from there (`POST /api/approvals/{id}`, `scope: once`); the
visitor is not sent back into the nanoMuse app for it, and the shade gets no notification on
top of the card. A hold, whether the agent hands the phone over (*Your turn*, the reason under it) or the
visitor takes it from the chat (*You have the phone*), is a card with **Done**
(`POST /api/holds/{id}/done`). Only a question a finished task left offers *Open*.

**Pictures for a new look** (`gateway/showcase_gateway/images.py`): "换个形象：一只橘猫" in the
chat is the avatar studio's ([docs/avatar.md](../../docs/avatar.md)): eight pictures, four
candidates, then the chosen one's poses. The container speaks the OpenAI images API at its
model's address (`…/images/generations`, `…/images/edits`); the gateway answers those two
calls itself, on Model Studio's native multimodal endpoint with the demo key, the way
nanoMuse Cloud's relay does, and tells the container the model's name
(`NANOMUSE_LLM_IMAGE_MODEL`). On by itself when `MAIN_BASE_URL` is a Model Studio host
(`IMAGE_MODEL=qwen-image-3.0`), off with `IMAGE_MODEL=` empty; `IMAGE_PER_SESSION` (12) and
`DAILY_IMAGES` (400) count apart from the chat budget. A visitor's own key draws nothing
through the gateway; `/api/demo/info` says `image_model: null` and the page greys the lines
out.

**Clips of the chosen face** (`gateway/showcase_gateway/clips.py`): after the stills the
studio animates the face (four short clips, one per mood) through the asynchronous video
API, which it looks for at `[llm] video_base_url`; the gateway names the session's own model
address there (`NANOMUSE_LLM_VIDEO_BASE_URL`), so the four calls of a clip land on it: the
upload policy, the first frame, the task, the polling. Model Studio wants the frame in its
storage or at a public URL, neither of which a container without internet can manage, so the
gateway stands in for the storage (the policy points back at it, the frame is kept a few
minutes and goes up with the task inline), and the finished MP4 comes back through it too.
`VIDEO_MODEL` (`wan2.2-i2v-flash` on a Model Studio host, empty for stills only),
`CLIPS_PER_SESSION` (4, one face) and `DAILY_CLIPS` (120).

### Trial credentials for the phone app

The same proxy can hand a new phone its first model. With `TRIAL_ENABLED=1`, `POST /api/trial`
with `{"device": "<a random id the app keeps>"}` answers with a key (`nmt_…`) and two
addresses (`https://<SITE_HOST>/llm/trial/<id>/main` and `…/gui`) that go straight into the
app's `[llm]` and `[gui]` settings. Every call through them is metered against the trial's
lifetime budget, `TRIAL_TOKENS` (a million); spent, the proxy answers 429 `trial_exhausted` and
the app asks for the user's own key. One trial per device: asking again with the same id
rotates the key and keeps the count, so a reinstall recovers nothing extra. New trials are
capped per address (`TRIAL_PER_IP_DAILY`) and per day (`TRIAL_DAILY_NEW`, 200); all trials
together may spend `TRIAL_DAILY_TOKENS` a day; each is held to `TRIAL_RPM` requests a minute.
Trials live in SQLite on the `gateway-data` volume and survive restarts; `GET /api/trial/<id>`
with the key shows what is left, and `/api/demo/info` carries the totals.

### nanoMuse Web: a kept Muse per Cloud account

The showcase gives a visitor a Muse for half an hour. With `WEB_ENABLED=1` the same gateway
gives a *person* one that stays: a kept Muse per account, for anyone who would rather not
install anything. With it off (the default, and what nanomuse.cn runs since 0.1.26: the
phone in the browser, with its sign-in, took the web version's place), `/web/` redirects to
the showcase site, the phone, so [nanomuse.cn/web/](https://nanomuse.cn/web/), which the
project site's Caddy block hands to the gateway, stays the web entry either way. On, `/web/`
is a sign-in page (served by the gateway; the site's Caddy block hands `/web/*` and
`/api/web/*` over to it): an e-mail or a mobile number, then the six-digit code.
The gateway asks nanoMuse Cloud for the code and checks it (`POST /v1/auth/code`,
`/v1/auth/verify`, the visitor's address forwarded so the relay's per-address limits still
count the right person), gets the account's key back, and starts, or wakes, the account's
container: `nmw-<slug>` with three named volumes (`/data`, `/workspace`, `/home/muse`), on the
`nanomuse-web` network (a way out, and the relay next to it), signed in from the environment
(`NANOMUSE_CLOUD_KEY`, `NANOMUSE_CLOUD_BASE_URL=http://nanomuse-relay:8787`,
`NANOMUSE_HUB_NAME=Web`, `NANOMUSE_ONBOARDED=1`; `nanomuse/hub/service.py`,
`_seed_from_env`). The browser is sent to `https://<slug>.<SESSION_DOMAIN>/#token=…`, the same
door the phone's QR code opens, and the runtime there makes the Cloud its model on first
start and takes its place on the hub as one of the account's devices, so the phone can ask
it for things and it can ask the phone.

What the gateway keeps is small (`WEB_DB`, SQLite on the `gateway-data` volume): account id →
slug, access token, and when the key the container was started with runs out. The key itself
is a *session key* the relay issues to lapse on its own (`POST /v1/auth/session-key`,
`WEB_KEY_TTL_S`, 30 days); it goes into the container's environment at creation and is kept
nowhere else; the standing key the sign-in produced is signed out again at once. The slug is
an HMAC of the relay's opaque account id, so signing in from another browser lands in the same
Muse (with a fresh key: the container is recreated around the same volumes); once the key has
lapsed, the Muse is not woken; the person signs in again, which does the same. A container
that has been quiet for `WEB_IDLE_STOP_S` (six hours) is stopped, not removed; the next
request on its host that carries the account's token (the bearer header, the socket's first
frame, a signed link) starts it again, which takes a few seconds; a browser arriving with
only the address gets a small page that takes the token from the app's storage and asks for
the wake, so a bookmark still works and a stranger typing the address starts nothing.
`WEB_MAX_RUNNING` containers run at once (when
every place is taken the quietest sleeps to make room, unless it was used in the last five
minutes: `503 web_busy`), and `WEB_MAX_ACCOUNTS` may exist at all (`503 web_full`). Model
use is the account's own allowance on the relay; the gateway meters nothing here.

## Deploying

You need: a Linux box with Docker (4 cores / 8 GB is plenty for `MAX_SESSIONS=20`; a session
idles at ~150 MB), a domain on Cloudflare, and a 百炼 key (or any OpenAI-compatible provider
that takes images).

```bash
# 1. DNS on Cloudflare:   demo.nanomuse.dev  A  <server>   DNS only (see the note on the proxy)
#                         *.s.nanomuse.dev   A  <server>   DNS only; sessions are WebSockets to Caddy
#    Cloudflare → My Profile → API Tokens: Zone → DNS → Edit and Zone → Zone → Read on the zone.

# 2. the code
git clone https://github.com/nano-muse/nanoMuse.git && cd nanoMuse/demo/showcase
cp .env.example .env && $EDITOR .env          # names, ACME_EMAIL, CLOUDFLARE_API_TOKEN, keys

# 3. what the sessions run
docker pull ghcr.io/nano-muse/nanomuse:latest  # or: docker build -t nanomuse:latest ../.. && set NANOMUSE_IMAGE

# 4. (optional, 1.9 GB) MobileGym's companion data: app media and home-screen widgets.
#    Without it the phone works but media apps render empty and two home widgets show an error.
mkdir -p data && curl -L https://github.com/Purewhiter/mobilegym/releases/download/data-v0.1.0/mobilegym-data-v0.1.0.tar.gz | tar -xz -C data
#    CC BY-NC 4.0: non-commercial use only (see MobileGym's LICENSE-DATA).

# 5. up: the published images (.github/workflows/showcase.yml builds them from main) …
docker compose pull && docker compose up -d
#    … or build them here (clones MobileGym and compiles Caddy; a few minutes):
docker compose up -d --build
docker compose logs -f gateway
```

Open `https://demo.nanomuse.dev`, find nanoMuse in the launcher (search works), and it starts.
`curl https://demo.nanomuse.dev/api/demo/info` shows sessions in use and today's spend.

Updating: `git pull && docker pull ghcr.io/nano-muse/nanomuse:latest && docker compose pull && docker compose up -d`.
Sessions in flight end when the gateway restarts; visitors get *Your Muse on the showcase server
has ended* and a button for a new one.

Both certificates are obtained through Cloudflare's DNS API (`CLOUDFLARE_API_TOKEN`); the
records themselves stay "DNS only". Cloudflare's proxy can be switched on for `SITE_HOST`
when the site is under attack: Caddy is built with the
[cloudflare-ip](https://github.com/WeidiDeng/caddy-cloudflare-ip) module and trusts
`X-Forwarded-For` from Cloudflare's ranges only, so `PER_IP_*` keeps counting visitors rather
than edges (set the zone's SSL/TLS mode to *Full (strict)*: the origin has a real certificate).
It is off by default on purpose: from mainland China the free plan routes through overseas
edges, and the phone's 1.6 MB bundle that a Hong Kong server delivers in 2–3 s took 15–40 s
through the proxy in our measurements. The audience this is for reaches the origin faster.

### Other sites on the same Caddy

The Caddyfile ends with `import /etc/caddy/sites.d/*.caddy`, and `docker-compose.yml` mounts
`sites.d/` there and `www/` (or `WWW_ROOT`) at `/srv/www`, both read-only and both ignored by
git. One file per site, its files under `www/<name>/`, then `docker compose up -d caddy`; a box
that has no such sites is unchanged.

The project site is served this way at [nanomuse.cn](https://nanomuse.cn): `mirror/` holds the
site block and `sync.sh`, which a systemd timer runs every minute to pull
[nano-muse.github.io](https://github.com/nano-muse/nano-muse.github.io) into `www/nanomuse.cn/`;
a push to that repository is on the mirror within the minute, with no key or webhook anywhere.
`sudo mirror/install.sh` sets up all of it and is safe to run again after `git pull`. What is not
in the repository: two A records at the registrar (`nanomuse.cn`, `www.nanomuse.cn` → this box).
A server outside mainland China needs no ICP filing for a `.cn` name; one inside does.

The same box mirrors the releases: `mirror/release-sync.py`, run by a second timer every fifteen
minutes, asks the GitHub API for the newest two releases (drafts and pre-releases skipped) and
fetches every asset into `www/dl/<tag>/`, checking each against the SHA-256 GitHub records for it;
`www/dl/latest` points at the newest tag, `www/dl/index.json` lists what is there, older tags are
removed. The site block serves the directory at [nanomuse.cn/dl/](https://nanomuse.cn/dl/) with a
listing, and the site's download switch ("GitHub / 国内镜像") rewrites its links to
`https://nanomuse.cn/dl/<tag>/<file>`. About 1.3 GB per release; `MIRROR_RELEASES_KEEP` in
`/etc/default/nanomuse-site-mirror` changes how many are kept. `install.sh` installs this too and
starts the first fetch in the background (`journalctl -u nanomuse-release-mirror` to watch it).

And it counts: the site block writes a JSON access log (`logs/caddy/`, rolled, kept seven days),
and `mirror/traffic.py` (`nanomuse-traffic`, every ten minutes) turns what was added since the
last run into daily counts in `/var/lib/nanomuse-traffic/traffic.db`: page views, visitors (a
hash of address and browser under a salt made for the day and dropped two days later; no address
is ever written), crawlers, downloads per file from `/dl/`, referring sites, the pages; once a run
it also records the repository's stars and GitHub's own release download counts. The relay
(cloud/deploy/nanomuse-hk) mounts the database read-only and shows it on its operator page;
`nanomuse-traffic --report` prints the last two weeks in the terminal.

### Running it on your machine

The gateway runs anywhere Docker does; Caddy is only for TLS and names. Browsers resolve
`*.localhost` to the loopback, so:

```bash
docker network create --internal nanomuse-sessions
docker build -t nanomuse:local ../..                        # the sessions' image
site/build.sh                                              # clones MobileGym, builds with VITE_NANOMUSE_DEMO=/api/demo, adds the page
cd gateway && pip install -e '.[dev]' && cd ..
PUBLIC_SCHEME=http SITE_HOST=localhost SESSION_DOMAIN=s.localhost PUBLIC_PORT=:8000 \
NANOMUSE_IMAGE=nanomuse:local SITE_DIR=$PWD/site/dist \
MAIN_API_KEY=sk-... python -m showcase_gateway              # http://localhost:8000
```

`site/build.sh /path/to/mobilegym` builds from a checkout you already have. The page itself
needs no bundler: edit `site/page/` and run `build.sh` again, or just
`node site/compose.mjs /path/to/mobilegym site/page site/dist` to recompose it with
MobileGym's chrome. The phone's media is MobileGym's companion data at `/cdn` (`CDN_DIR`, or
`./data/mobilegym-data` in the compose file); without it the launcher's theme widgets show their
error cards and the media apps render empty, as on an upstream checkout without it; or build
with `MOBILEGYM_CDN_BASE=https://cdn.mobilegym.dev` (a build arg of the same name in the compose
file) and the phone takes it from MobileGym's CDN, as their own site does.

`cd gateway && pytest` runs the gateway's tests (no Docker needed; the containers are faked).

## Costs, roughly

A session that asks two or three things, one of them on the phone, is 5–15 model calls and
20–60k tokens: about ¥0.05–0.2 at DeepSeek/百炼 prices. Two hundred sessions a day is ¥20–40.
A new look is eight qwen-image pictures, about ¥2; `DAILY_IMAGES` (400) bounds that at ¥100 a
day, `IMAGE_PER_SESSION` (12) at one face and half a redraw per visitor. The four clips of the
chosen face are about ¥2 more with wan2.2-i2v-flash (4 s, 480P); `DAILY_CLIPS` (120) bounds
that at ¥60 a day, `CLIPS_PER_SESSION` (4) at one face per visitor. The daily caps in
`.env.example` (3,000 calls / 6M tokens) bound the chat's worst day at a few tens of yuan;
lower them if you like. Put a spending alert on the provider accounts too: the gateway's
counters live in memory and start from zero when it restarts.

## Known limits

- One gateway, one host. The session counters are in memory (the trials are in SQLite); that is
  fine for a showcase and would need a shared store to scale out.
- The gateway starts and stops containers, which is a lot of power over the host. It reaches
  Docker through `docker-proxy` (compose: `tecnativa/docker-socket-proxy`), which passes the
  container and network calls and refuses the rest (no exec, images, volumes or build), and
  holds the socket itself read-only on a network of its own; the gateway container has no
  socket. It is still the trusted part; keep it off the public network (compose does: only
  Caddy is published).
- A visitor's own provider (BYOK) is resolved and checked once, when the session starts, and
  the session's calls are pinned to the addresses found then (the name travels only as SNI
  and `Host`, the certificate is checked against it as usual), so a name that answered with a
  public address cannot be re-pointed at one inside our network later (DNS rebinding).
- No egress from sessions means the search, fetch and browser tools fail inside a demo. That is
  the point of the demo, the phone, but say so if visitors ask.
- The MobileGym data set is CC BY-NC 4.0; the showcase is non-commercial.
