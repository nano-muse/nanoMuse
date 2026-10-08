# nanoMuse Cloud

The "start now" path: sign up with a phone number (mainland China; the code comes by SMS)
or an e-mail address, get a free allowance, and use nanoMuse without an API key of your own.
Bringing your own key still works exactly as before — this is one more
provider, not a replacement.

## In the app

Since 0.1.20 the account is where every app starts: the first screen asks for a
phone number or an e-mail address and sends a six-digit code — or, once you have
set one, takes your password — and then asks which model answers: the account's
own (the Cloud) or a key of your own. Codes by SMS reach mainland China numbers
only (号码认证服务 sends nowhere else); a Hong Kong, Taiwan or overseas number is
told so at once (`phone_region`) and signs in with an e-mail address instead.
Signing out brings that screen back
(self-hosters: `[cloud] required = false` or `NANOMUSE_CLOUD_REQUIRED=0` on the
runtime). The screen is a door, not a wall: *Use your own API key instead* steps
past it into setup's own-key path, and with a key of your own the app works
signed out (chat, hands, pictures, clips); the sign-in waits under
*Connections* (phones: *Settings → nanoMuse Cloud*) for the Cloud models, sync
and your devices. After the code the app has:

- a provider called **nanoMuse Cloud** under *Settings → Providers*, an
  ordinary OpenAI-compatible provider whose key is the token the relay issued;
- the four rows of *Settings → Models* (web console: *Connections*) on the
  account's models when you had chosen none: the recommended chat model, the
  recommended hands model (the one that reads screenshots and drives a phone or
  a computer; each model on the relay's menu says which of the two it is for),
  the picture model and the clip model. A row you have not set follows one
  order: the chat model's provider when it is a key of yours that can do the
  job, else nanoMuse Cloud while signed in, else the first key of yours that
  can; the *Automatic* entry of the row says what that gives right now, and a
  key you add later asks *Use it for* before any row moves
  ([own-key.md](own-key.md#which-model-does-what)).

*Settings → nanoMuse Cloud* (the *Account* screen) shows who is signed in (a
masked hint, never the number) and since when; sets, changes or removes the
**password** (eight characters or more; scrypt on the relay; locked for a while
after repeated wrong attempts, and a fresh code sign-in opens it again); today's
spend against the allowance in ¥ and $ with a meter; **usage by kind** —
chat, pictures, video — today and in all, and **by model**; the
**sign-ins** — every device holding a key, how it signed in (code or password),
when it was last used — each revocable; the account's own **history** (sign-ins,
password changes, refusals; never message content); and the ways
out: *Sign out* on this device, *Sign out everywhere*, *Delete the account*.
The allowance belongs to the address: signing in again, on
this phone or another, gives a new key for the same account and does not grant
a second allowance.

**What a sign-out leaves on the phone** (0.1.40, contract C12). A sign-out —
on this device, everywhere, or to use a different server — asks one question,
*Keep this account's chats on this device*, off by default. Off, the account's
chats, memory, feed, goals, routines and face are removed from the phone (with
sync on, the relay still has the chats for the next sign-in); on, they are put
aside and come back when the account signs in again. Signing in as another
account goes through the same sign-out. *Delete the account* removes the account
at the relay and everything of it on the phone, no question asked; the next
sign-in with the same address is a new account that starts empty. A key the
relay refuses — `401 bad_key`: *Sign out everywhere* from another device, a
relay reset, a relay bug — is a sign-out nobody on the phone could answer, so
the phone keeps the account's data aside as *Keep* would, removes the key, and
the sign-in page says *Your sign-in on this phone was ended — sign in again to
continue; your chats are kept on this device until then*; the next sign-in as
the same account restores it, another account sees nothing of it. Only
`401 account_deleted` — the relay's answer, from 0.1.40, to a key whose account
was deleted — lets the phone remove the data, since there is nothing to come
back to. Every piece of state, where it lives and what happens to it on each
event is the table in [sync.md](sync.md). The one addition to the wire is that
error code; an older relay answers `bad_key` for both and the phone keeps the
data.

Signing in a second provider next to it — your own Model Studio key, DeepSeek,
a local server — works as always; the relay's models can be mixed with yours
in a model group.

## What the relay keeps

The relay is the code in [`cloud/`](../cloud/README.md). It stores:

- a salted hash (HMAC-SHA256) of the e-mail address or the mainland China
  phone number, a masked hint such as `so***@example.com`, and
  the address itself encrypted (AES-GCM, key derived from the relay's secret)
  so the operator can see who an account belongs to on the admin page — the
  database file alone shows nothing;
- the hash of each key issued, with the device name you signed in from, how
  (code or password) and when it was last used; revoked keys keep their row
  so the sign-ins list can say so;
- the password, if you set one, as an scrypt hash — never the password;
- per request: the kind (chat, picture, video), the model, the token counts
  and the amount charged;
- a timeline of account events — signed in, failed sign-in, password set or
  changed, signed out, refused for budget, upstream error — with a
  device name, a model or an error code as the detail, never message content;
- the id of each video task, so only the account that started one can poll it;
- the agent's name and look (`/v1/me/profile`): which face it wears — the dragon,
  an emoji on a colour, or one drawn in the avatar studio, with that face's five
  stills as small WebP pictures — so every device of the account shows the same
  one. Since 0.1.34 the same profile lists the account's **connectors**: which
  device connected which service (a label, how it signed in — OAuth, a key, or
  open — and when), so another device can say "connected on your Mac". The
  credential itself stays on the device that holds it; the relay refuses an
  entry that carries anything named like one. Never a key or a setting.
- since relay 0.19, the **synced conversations** (*Sync conversations between
  my devices*, on by default): the text of the account's chats — each
  conversation's title, kind and which device started it, each message's role,
  text, time and device, and the names and sizes of attached files, never the
  files themselves — so every device shows the same ones. Turning the switch
  off deletes all of it; so does deleting the account. The section
  [Conversation sync](#conversation-sync) below has the shape.

Images and tool results are never stored, and message content only as the
*Data controls* and *Conversation sync* sections below say — with both switches off, nothing: the request
is forwarded to the upstream model (Alibaba Cloud Model Studio) and the reply
is streamed back. Every response carries an `X-Nanomuse-Request` id so a problem report
can be matched to a ledger row without any content being logged. Deleting the
account (`POST /v1/auth/delete` with the account's key) removes all of it — the
account, keys, devices, profile, ledger, events, kept conversations, video
tasks, the synced conversations and cursors, the hub connections and the live
*working* notes; the relay's tests check every table for the account afterwards,
and that the same address signing up again is a new, empty account. See
[privacy.md](privacy.md).

## Data controls

*Settings → Data controls → Help improve nanoMuse's AI models* is a switch each
person owns, the same on the phone, the web app, the desktop and the console.
Off, the relay forwards a chat request and keeps nothing of it. On, each turn
is kept as a training view: what you wrote, what the model answered and the
tool calls it chose, with the model, the token counts and the app's platform
and language from the request headers, tied to the account id only — never the
system prompt (your memory, SOUL and instructions), never what a tool returned
(your files, your screen, what another app showed), never a picture, a clip or
a voice note (a marker stands where one was). The point is a training set for
the community's own open model. The page shows how many turns are kept; turn
the switch off at any time (nothing more is kept) and delete what was kept
with one tap; deleting the account deletes it too. Nothing is credited for
the switch either way. On `cloud.nanomuse.cn` the switch is **on for accounts
created from relay 0.9 on, until the person turns it off** — the privacy
policy says so, the page says so next to the switch, and accounts from before
keep the choice they had made; a self-hosted relay sets its own default with
`IMPROVE_DEFAULT`. The operator sees the kept turns on the admin page's *Data
controls* panel (how many accounts have it on, turns by day, model and app,
the newest turns, every account's kept conversations in full) and exports them
as JSON lines without account ids or addresses (`GET /v1/admin/samples/export`,
`?account_id=` for one account's). The relay does not receive a location — the
apps never send one — but from relay 0.10 it records the network address and
the client software (`User-Agent`: the Android app and its version, the
runtime on Windows / macOS / Linux, a browser) with each sign-in, request,
event and device, and keeps the account's first and last address; the admin
page shows them per account and per address (`GET /v1/admin/address?ip=`), and
they are deleted with the account. From relay 0.11 the admin page also says
where an address is — country, province, city — looked up in an offline copy
of ip2region's database on the relay's own disk; no third party is asked, and
nothing more is stored (the place is computed when the page is drawn).

## Conversation sync

*Settings → Data controls → Sync conversations between my devices* (0.1.36,
relay 0.19) is the other switch on that page, **on by default** for a signed-in
account. With it on, each device pushes the text of its turns to the relay and
pulls what the others pushed, so the phone, the computer and the web app show
the same chats: the title of each conversation, who started it, and each
message's role, text, time and device. Files and images are not uploaded — a
synced message carries only the names and sizes of what was attached, and the
files stay on the device that made them. Deleting a chat on one device deletes
it on all of them; renaming does the same. Chats addressed to another device
or run for one (*From Pixel 8*) are not synced at all.

**One thread** (0.1.37). An account has one main conversation, and every
device's main chat *is* it: the first device to push names its id, the others
adopt it (`main_exists` → `cid_main`, pull first on sign-in), and the main chat
on each device shows the union of what was said on all of them, ordered by
time (a tie keeps the local message first, a message is known by its `mid`, so
nothing shows twice and a device's own messages coming back are ignored). A
message written on another device is a read-only bubble with *From Pixel 8*
under it, and the model reads it with the rest of the conversation. A side
chat pulled from the relay is a chat on the device at once, with its title and
time, and continues there under the same conversation id. The person's message
goes up the moment it is sent — the other devices see it in real time, before
the reply — and the assistant's final text when the turn ends; signing in or
turning the switch on sends the device's whole eligible history, oldest first,
200 messages a request. The muse's name is part of the account's profile: a
rename on any device, including the first conversation's naming, reaches the
others on the next pull.

**Main first** (0.1.38, relay 0.20). By default only the main conversation
travels: side chats stay on the device that made them, and a device pulls with
`scope=main` so other devices' side chats never arrive. *Also sync side chats*
(a second switch under *Data controls*, off by default, **per device** — the
relay has no account-wide setting for it) turns that around for the device it is
flipped on: its side chats go up, the other devices' side chats come down, and
the first pull after the flip starts over from zero. The first pull of a fresh
sign-in asks for the **tail** — the newest 300 messages with the conversations
they belong to — so a long history opens at once instead of paging from the
start; the older messages it skipped stay on the relay and are not pulled. While a
device is answering, the others show *kwai is working…* under the last message:
a `working` note that goes through the relay's memory and the hub, is never
stored, and dies after ten minutes if the device never says it is done.

The relay keeps at most 20 000 messages per account (the oldest conversations'
messages go first, their titles stay), 2 000 live side conversations (relay
0.23: a new one past that is refused with `conversation_limit` and stays on
the device; deleting one frees a place) and 16 384 bytes per message (longer
text is cut and marked `truncated`). Turning the switch off on any device tells
the relay, which deletes everything stored and refuses the other devices with
`sync_off` until the switch is turned on again — their switches follow.
*Delete synced conversations* on the same page empties the store and leaves the
switch as it is. Nobody but the account's devices can read the store: the
operator's admin page shows counts only — accounts with it on and off, how many
conversations and messages, their size — never a text, never which account
(`GET /v1/admin/sync`). The pulls are triggered by the hub's `sync` frame
([hub.md](hub.md#frames)), at launch and once a minute.

The API, all under the account's key (401 without one; 409 `sync_off` while the
switch is off, for reads as well as writes):

```
GET    /v1/sync/state                   → {enabled, cursor, counts{conversations, messages}, limits{messages, text_bytes, conversations}, working[]}
PUT    /v1/sync/state   {enabled}       → the same; false deletes everything stored, the counter keeps counting
GET    /v1/sync/changes ?since=0&limit=500&scope=all|main&tail=K   → {cursor, more, conversations[], messages[], skipped?}
POST   /v1/sync/changes {device, conversations[], messages[]}   → {cursor, accepted, rejected[{cid | mid, reason, cid_main?}]}
POST   /v1/sync/working {cid, working, device?}   → 204; the hub tells the other devices   404 no_conversation
DELETE /v1/sync/changes                 → the state, counts at zero     everything stored, switch unchanged
DELETE /v1/sync/conversations/{cid}     → {cursor, deleted: true}      a tombstone the other devices apply; 404 no_conversation
```

`scope` (relay 0.20) is `all` unless said; `main` returns only the main
conversation and its messages, and an account with no main yet gets an empty
page whose `cursor` is the account's counter. `tail=K` (K ≤ 500, honoured with
`since=0` only) returns the newest K messages in `seq` order, the conversations
they belong to, `cursor` at the account's counter, `more: false` and `skipped`
— how many older messages were left out. Any other `scope` is 400 `bad_scope`.
`POST /v1/sync/working` says the device named in `device` (or in
`X-Nanomuse-Device`) is answering in `cid` (`working: true`) or has finished
(`false`); the relay keeps the live ones in memory for ten minutes — never in
the database, so a restart forgets them — lists them under `working` in the
state (`[{cid, from, device_name, working, at}]`) and sends a `working` frame
to the account's other sockets ([hub.md](hub.md#frames)). Request bodies over
`MAX_REQUEST_BYTES` (16 MiB by default since 0.20) are 413 `too_large` with
*Request body is N MB; this relay accepts up to M MB*.

A conversation is `{cid, kind: main | side, title, device, device_name,
created_at, updated_at, deleted, seq}` and a message `{mid, cid, seq, device,
device_name, role: user | assistant, text, truncated, attachments[{name, mime,
size}], created_at, deleted}`; `cid` and `mid` are UUIDs the device makes (4–64
characters of `a-z 0-9 . _ : -`, folded to lower case), times are Unix seconds.
Every accepted change takes the account's next `seq`; a device keeps the
highest `cursor` it has pulled and asks for `since=` that. A push is idempotent
— a known `mid` is left alone unless the new row is a tombstone, a known `cid`
takes the newer title — and at most 200 messages or conversations long (413
`too_many_messages`). A page lists its conversations and messages in `seq`
order, and the relay adds the conversation of every message in the page even
when that conversation's own `seq` lies ahead (a rename moves it), so a client
applies the page's conversations first, then its messages, and is never handed
an orphan. Refusals name the row: `main_exists` with `cid_main` when a second
`main` is pushed — the device then re-sends under `cid_main` —, `conversation_limit`
(relay 0.23, the account's side conversations are at their cap), `unknown_cid`,
`conversation_deleted`, `bad_cid`, `bad_mid`, `bad_kind`, `bad_role`. A
tombstone keeps its row for 30 days and is then swept. After an accepted push
or a deletion the hub tells the account's other devices with a `sync` frame
(`DELETE` from the console carries the deleting device in `X-Nanomuse-Device`
so it can skip its own echo).

## Allowance

nanoMuse is a community project and charges nothing. The public relay at
`cloud.nanomuse.cn` is paid for by the developer, so each account has a pool
to draw on — for its lifetime, not by the day (relay 0.5):

| | `cloud.nanomuse.cn` |
|---|---|
| sign-up | open to anyone with a mainland China mobile number or an e-mail address |
| free allowance | **¥10 per account** at the time of writing, across chat, pictures and clips; it does not reset. The figure is the relay's to set (it can go up without an app update — the apps print what the relay says, `/v1/config`), and the account page always shows the current one |
| invitations | each *new* person who signs up with your code adds **¥5** (again, the relay's figure) to your pool — and the same to theirs |
| when it is gone | bring your own key or a plan you already pay for — in mainland China, [Alibaba Cloud Bailian](own-key.md) first (one key covers chat, the hands, pictures and clips); elsewhere, [OpenRouter](https://openrouter.ai/keys) or OpenAI first (Bailian only signs up accounts from mainland China); a ChatGPT, Claude or Kimi plan signs in where the client has the flow; any OpenAI-compatible endpoint works; sign-in and your devices are unaffected |
| members | the developer and the people they list have no limit, and may set any model the provider has (a chat model for chat, an image one for pictures, a video one for clips): the apps' model picker lists them after the menu as *More models on your account* (relay 0.10 reads the provider's list under the Cloud key), and an id can still be typed — *Other model…* |
| rate | 30 requests per minute |
| tokens | no ceiling; usage is metered and shown |

Spend is counted at the model provider's list prices (Alibaba Cloud Model
Studio, Beijing region, read on 2026-10-07). `deepseek-v4.1-flash`, the chat
model since 0.1.34 (it reads pictures and thinks before it answers), is ¥2 in /
¥8 out per million tokens from 8:00 to 22:00 Beijing time and ¥1 / ¥4 the rest
of the night; the hour the reply comes in decides. `qwen3.8-27b`, the hands
model, usable for chat too, is ¥3 / ¥12; `qwen3.8-flash` ¥0.8 / ¥2.7;
`qwen-image-3.0` ¥0.18 a picture, and an edit adds ¥0.02 for the picture sent
in; `wan2.2-i2v-flash` ¥0.10 a second of video at 480P (a 5-second clip is
¥0.50), ¥0.20 a second at 720P and ¥0.48 at 1080P. The part of a prompt the
provider served from its cache (the system prompt and the history, turn after
turn) is counted at the provider's cached rate, 10 % of the input price on
DeepSeek and 20 % on the Qwen models, as the reply's `usage` reports it. The
reasoning tokens of a thinking model count as output. A typical day of
chatting costs a few fen; ¥10 is roughly two million tokens of the chat model
or fifty pictures. A new face (four candidates, four poses and four clips)
comes to about ¥3.5, and the app shows the estimate and what is left before it
draws.

*Settings → nanoMuse Cloud* shows what was used of the pool in ¥ and $, what
is left, and how the pool grows. At 80 % the app says so once; when the pool
is spent the relay refuses with `allowance_exhausted` and the app shows the
ways on: your own key, a plan you already pay for, or an invitation (+¥5 for
each of you, or whatever the relay says that day). Which provider comes first
follows where you are (0.1.34: the relay's `region`, read from the number's
country code or from an offline copy of ip2region on its own disk — nothing is
sent anywhere): a mainland China account is pointed to Alibaba Cloud Bailian —
the provider form opens pre-filled, [guide](own-key.md) — and everyone else to
OpenRouter or OpenAI, since Bailian only signs up accounts from the mainland.

Since relay 0.21 the refusal and `/v1/me` carry the whole card as data, not
only two links (contract C11): `spend.guidance` — and `guidance` beside the
`allowance_exhausted` error — lists the region's providers in order with what
each one's key covers (`covers: chat | vision | image | video`, from the shared
catalogue [`nanomuse/llm/providers.json`](../nanomuse/llm/providers.json), of
which the relay ships its own copy), the plans a person may already pay for and
which clients can sign in with them (`plans`: ChatGPT everywhere, Claude and
Kimi on the phones, OpenRouter on the phones), the local servers (`local`), the
docs link and the honest line about the ChatGPT sign-in (`caveats.chatgpt`,
`caveats.chatgpt_zh`). The 0.17 `ways` rows are still sent, each now with the
provider's `name`, `name_zh`, `key_url`, `covers` and `auth`, so a 0.1.38
client draws the same two buttons it always did. The console at `/app` draws
the card from `guidance` and falls back to the two links on an older relay.
Other relays may set other rules
(`ALLOWANCE_CNY`, `INVITE_BONUS_CNY`, `SIGNUP_OPEN`, `ALLOWED_IDENTIFIERS` —
all three figures adjustable while the relay runs, relay 0.15; see
[`cloud/README.md`](../cloud/README.md)).

nanoMuse asks for one thing in return: a star on
[GitHub](https://github.com/nano-muse/nanoMuse), which is what helps the
project be found. The moments are the relay's to set, not the app's (0.1.35):
`GET /v1/nudges` says when an ask is fair — after the third, tenth and
thirtieth task it finishes for you, on the seventh and thirtieth day you open
it, when a goal is reached, when a new face is drawn, once on the account page,
and when the pool is spent — with at least a week between two asks and at most
four per device. Each ask is a card where it happens; "Not now" counts as one,
and none comes back after you have been to the page or said "I already
starred" (per device; the account does not carry the flag). The operator changes the
policy on the admin page (*Settings › Star asks*) without an app update; every
app keeps the same defaults built in for when the relay cannot be reached. The
policy says *when* and, if the operator wants, *what*: the words on the card
are each app's own, in its language, unless the policy carries a sentence —
`star.text` (English) and `star.text_zh` (简体中文), each at most 200
characters, empty by default. An app in Chinese shows `text_zh` when it is
set, else `text` when it is set, else its own sentence; an app in any other
language shows `text` when it is set, else its own. Only the sentence on the
card changes; its title and buttons stay the app's. Apps built against relay
0.22 and earlier ignore the two fields.

## Controls

The operator can pause parts of the relay without a restart or a deploy
(relay 0.22, *Controls* on the admin console; `nanomuse-cloud admin controls
…` on the command line — [`cloud/README.md`](../cloud/README.md#controls-022)).
Five switches, each on by default, each kept in the database so a restart
keeps it, each with a line in an audit log saying who flipped it, when and
why. What an app sees when one is off:

| switch | what the app gets while it is off |
|---|---|
| **Free allowance** | a limited account (no key of its own, not a member) asking a model gets **429 `allowance_exhausted`** with `paused: true` and `reason: "allowance_paused"` — the same shape as a spent pool, so every app shows its own-key card as it does today, with a message saying the allowance is paused for now rather than spent. Members, sign-in, devices and sync are unaffected |
| **Sign-ups** | a phone number or an e-mail address that has no account yet gets **403 `signup_closed`** from `POST /v1/auth/code` and from `/v1/auth/verify`, before any code is sent; `signup_open` in `/v1/config` turns false. Every existing account signs in and works as before |
| **Cloud service** | every API call answers **503 `service_paused`** with `paused: true`, except the health check, `/v1/config`, the admin console and `/v1/admin/*`; every hub socket is closed with `4003 hub_paused`. Nothing is deleted; a signed-in app keeps its key and signs back in when the switch returns |
| **Conversation sync** | `/v1/sync/*` pushes and pulls answer **503 `sync_paused`**; `GET /v1/sync/state` still answers and says `paused: true`. What is stored stays; each device keeps working on its own |
| **Device hub** | `WS /v1/hub` accepts and closes at once with **4003 `hub_paused`**, the open sockets are closed the same way, `GET /v1/devices` answers 503 `hub_paused`. Each device keeps working on its own |

The switches that are off are listed under `paused` in `/healthz`,
`/v1/config` (public, a minute's cache) and `/v1/me`, so a client can say why
before it tries. The apps handle the codes as any refusal: the phones and the
console show the relay's sentence; the `allowance_exhausted` shape is the one
they already draw a card for.

**Thresholds.** A rule says *when the account count reaches N, do one
thing*: close sign-ups, pause the allowance, pause sync, or only notify. Rules
are checked when an account is created and once a minute; a rule fires once
(the count it fired at and the time are kept and shown), and *re-arm* or a
changed threshold lets it fire again. Every firing writes an audit line and a
line on the activity timeline; *notify* also sends an e-mail to the relay's
`ADMIN_EMAIL` through the SMTP settings (counts and the relay's address only,
nothing about any person). The state of the switches and the next threshold
are the first line of the admin dashboard.

## Running your own

Anyone can run a relay — for a family, a class, a company — and point the app
at it. The server is a single Python process over SQLite; a VPS with Docker and
a domain name is enough:

```bash
cd cloud
cp .env.example .env    # domain, secrets, upstream key, how codes are sent
docker compose up -d    # Caddy fetches the TLS certificate
```

[`cloud/README.md`](../cloud/README.md) has the settings, the sender options
(SMTP for e-mail, Aliyun SMS for mainland phones), the admin endpoints for
topping up, and the test suite.

A relay for one person, or a few: `SIGNUP_OPEN=0` with
`ALLOWED_IDENTIFIERS=139…, me@example.com` lets only those numbers and
addresses sign in; everyone else gets `not_invited` before any code is sent.
The trial deployments ran this way. With sign-up open, the same list names
the members who have no daily cap; the admin page can add more.

For an app store's review, `REVIEW_ADDRESSES` and `REVIEW_CODE` give the
reviewer a way in: a code request for one of those e-mail addresses sends
nothing and answers as if it had, and the six-digit `REVIEW_CODE` signs in,
under the same code lifetime, attempt and rate limits as anyone's. The
account is an ordinary one; the admin page tags it *review* and leaves it out
of the sign-up counts. Both empty (the default) and nothing changes. The
details are in [`cloud/README.md`](../cloud/README.md#for-app-store-review).

The relay is also the meeting point for the account's devices — the **hub** at
`/v1/hub` and the web console at `/app`; see [hub.md](hub.md). `HUB_ENABLED`
turns it off, `HUB_FRAME_LIMIT` caps one frame (files and screenshots travel
inside frames, 16 MB by default).

The apps talk to `https://cloud.nanomuse.cn` by default. *Use a different
server* under the phone's sign-in form takes the address of a relay you run
yourself ([android.md](android.md), [ios.md](ios.md)); the desktop reads it from
the plugin's `config.baseURL` ([desktop.md](desktop.md)) and the web console is
whatever relay serves it at `/app`.

## Protocol

The app's calls, all JSON:

```
POST /v1/auth/code          {identifier}                      → 204
POST /v1/auth/verify        {identifier, code, device}        → {api_key, base_url, account, tokens, models}
POST /v1/auth/login         {identifier, password, device}    → the same; 401 bad_credentials, 429 locked, 400 no_password
POST /v1/auth/password      Bearer  {password, current?}      → 204; "" with current removes it
GET  /v1/me                 Bearer                            → {region: cn | intl | unknown, account{…, has_password, sessions, signed_in_via}, usage{today, total by kind / model}, tokens, spend{…, ways}, models, recent, nudges}
GET  /v1/nudges                                               → {version, star{enabled, url, moments{signed_in, tasks[], new_look, exhausted, days_used[], goal_done}, cooldown_days, max_asks, text, text_zh}}; no key, cached an hour
GET  /v1/me/profile         Bearer  ?face=false               → {rev, device, name, avatar, …, face?, connectors: [{id, label, url, auth, device, device_id, enabled, at}]}
PUT  /v1/me/profile         Bearer  {device, name?, avatar?, …, connectors?}  → {rev, device}; a device's connectors replace only its own; 400 no_secrets_in_profile, too_many_connectors
DELETE /v1/me/profile       Bearer                            → 204
GET  /v1/me/sessions        Bearer                            → {sessions: [{prefix, device, via, created_at, last_used_at, current}]}
DELETE /v1/me/sessions/{prefix}  Bearer                       → 204
GET  /v1/me/events          Bearer  ?limit=50                 → {events: [{ts, kind, detail}]}
POST /v1/auth/sign-out      Bearer                            → 204
POST /v1/auth/sign-out-all  Bearer  {all?}                    → {signed_out}
POST /v1/auth/delete        Bearer                            → 204
```

Everything else is the OpenAI API: `GET /v1/models` (with `architecture`
modalities so the picture model is recognisable, and a `nanomuse` block per
model with its `kind`, prices, `for` — the lane(s) a chat model is for, `chat`
and / or `gui` — and `recommended_for`), `POST /v1/chat/completions`
with streaming, `POST /v1/images/generations` and `/v1/images/edits`. Errors
are `{"error": {"message", "type": "nanomuse_cloud", "code"}}` with a stable
`code` the app turns into a sentence. Relay 0.22 adds the codes of the
operator's [switches](#controls): `403 signup_closed`, `503 service_paused`,
`503 sync_paused`, `503 hub_paused` (and the hub's close code `4003
hub_paused`), and `allowance_exhausted` with `paused: true` when the free
allowance is paused rather than spent; `/healthz`, `/v1/config` and `/v1/me`
list the switches that are off under `paused`.

A key the relay does not know answers
`401 bad_key`; from 0.1.40, a key whose account was deleted answers
`401 account_deleted` instead, on every call that takes a key (`/v1/me`,
`/v1/models`, `/v1/chat/completions`, the sync and hub calls), for 90 days
after the deletion — the relay keeps the hashes of a deleted account's keys that
long, and nothing else. A client that does not know the code sees the same
`401` as before; a client that does (the phones) removes the account's local
data on `account_deleted` and keeps it aside on anything else
([sync.md](sync.md)). The full table of codes is in
[`cloud/README.md`](../cloud/README.md).

Devices: `GET /v1/devices` lists the account's devices (online or last seen),
`DELETE /v1/devices/{id}` forgets an offline one, and `WS /v1/hub` is the hub
itself — the frames are in [hub.md](hub.md). Conversations: `/v1/sync/state`,
`/v1/sync/changes` and `/v1/sync/conversations/{cid}` — the section
[Conversation sync](#conversation-sync) above.
