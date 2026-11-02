# nanoMuse Cloud

The "start now" path: sign up with a phone number (mainland China; the code comes by SMS)
or an e-mail address, get a free allowance, and use nanoMuse without an API key of your own.
Bringing your own key still works exactly as before: this is one more
provider, not a replacement.

If a saved numeric admin-console preference is blank or is not a finite number, the console uses that setting’s default value.

Admin-console refreshes keep the newest response for each URL. Responses from before sign-out cannot repopulate the cleared cache or replace a later account’s data.

## In the app

Since 0.1.20 the account is where every app starts: the first screen asks for a
phone number or an e-mail address and sends a six-digit code (or, once you have
set one, takes your password) and then asks which model answers: the account's
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
- the chat and hands rows of *Settings → Models* (web console: *Connections*) on
  the account's `Qwen/Qwen3.6-27B-FP8` when you had chosen none. It reads image
  input, so pictures in chat and screenshots used for GUI operation still work.
  The account does not provide image or video generation; those two rows require
  a custom provider and API key on the device. A row you have not set follows one
  order: the chat model's provider when it is a key of yours that can do the
  job, else nanoMuse Cloud while signed in, else the first key of yours that
  can; the *Automatic* entry of the row says what that gives right now, and a
  key you add later asks *Use it for* before any row moves
  ([own-key.md](own-key.md#which-model-does-what)).

*Settings → nanoMuse Cloud* (the *Account* screen) shows who is signed in (a
masked hint, never the number) and since when; sets, changes or removes the
**password** (the relay sets the minimum, eight characters by default; scrypt on the relay; locked for a while
after repeated wrong attempts, and a fresh code sign-in opens it again); today's
spend against the allowance in ¥ and $ with a meter; **usage by kind** (chat,
pictures, video) today and in all, and **by model**; the
**sign-ins**: every device holding a key, how it signed in (code or password),
when it was last used, each revocable; the account's own **history** (sign-ins,
password changes, refusals; never message content); and the ways
out: *Sign out* on this device, *Sign out everywhere*, *Delete the account*.
The allowance belongs to the address: signing in again, on
this phone or another, gives a new key for the same account and does not grant
a second allowance.

**What a sign-out leaves on the phone** (0.1.40, contract C12). A sign-out (on
this device, everywhere, or to use a different server) asks one question,
*Keep this account's chats on this device*, off by default. Off, the account's
chats, memory, feed, goals, routines and face are removed from the phone (with
sync on, the relay still has the chats for the next sign-in); on, they are put
aside and come back when the account signs in again. Signing in as another
account goes through the same sign-out. *Delete the account* removes the account
at the relay and everything of it on the phone, no question asked; the next
sign-in with the same address is a new account that starts empty. A key the
relay refuses (`401 bad_key`: *Sign out everywhere* from another device, a
relay reset, a relay bug) is a sign-out nobody on the phone could answer, so
the phone keeps the account's data aside as *Keep* would, removes the key, and
the sign-in page says *Your sign-in on this phone was ended. Sign in again to
continue; your chats are kept on this device until then*; the next sign-in as
the same account restores it, another account sees nothing of it. Only
`401 account_deleted` (the relay's answer, from 0.1.40, to a key whose account
was deleted) lets the phone remove the data, since there is nothing to come
back to. Every piece of state, where it lives and what happens to it on each
event is the table in [sync.md](sync.md). The one addition to the wire is that
error code; an older relay answers `bad_key` for both and the phone keeps the
data.

Signing in a second provider next to it (your own Model Studio key, DeepSeek,
a local server) works as always; the relay's models can be mixed with yours
in a model group.

## What the relay keeps

The relay is the code in [`cloud/`](../cloud/README.md). It stores:

- a salted hash (HMAC-SHA256) of the e-mail address or the mainland China
  phone number, a masked hint such as `so***@example.com`, and
  the address itself encrypted (AES-GCM, key derived from the relay's secret)
  so the operator can see who an account belongs to on the admin page (the
  database file alone shows nothing);
- the hash of each key issued, with the device name you signed in from, how
  (code or password), when it was last used and, once registered, its Hub
  device id and kind; revoked keys keep their row so the sign-ins list can say
  so;
- the password, if you set one, as an scrypt hash, never the password;
- per request: the kind (chat, picture, video), the model, the token counts
  and the amount charged;
- since relay 0.28, per chat request, how it went (the `calls` table): how
  long it waited for a slot at the provider, the time to the first token and
  the whole, how it ended (ok, a provider error or timeout, a content-check
  refusal, a broken connection, an allowance refusal), how many messages and
  pictures the request carried, which tools the client offered and which the
  reply called (names only), whether it was a screen-operation turn, the
  client platform and, from relay 0.31, how many of the prompt tokens the
  provider served from its cache. Never a word of the conversation. Rows older than
  `CALLS_KEEP_DAYS` (90) are removed, and the operator's *Live* and *Usage*
  pages read these rows in aggregate (how busy the model endpoint is, how
  fast it answers, which platforms queue);
- since relay 0.28, beside each kept turn (*Help improve*, below) a shape row
  (`sample_stats`): message count, character counts, tool calls, pictures,
  whether the prompt was trivially short, and a hash of the person's message
  so repeats can be counted. The quality page reads the shapes, not the turns;
  deleting the turns deletes the shapes;
- since relay 0.28, a device may say in its hub hello which model it runs on
  (`llm {provider, model}`, the two ids and nothing else: never a key, an
  address or a setting), so the operator can see which providers people
  configure for themselves. The apps of 1.0.6 and earlier say nothing; from
  1.0.7 every client says `cloud` while the account's models answer and the
  catalogue's vendor id (`openrouter`, `bailian`) with the model id on a key
  of its own;
- a timeline of account events (signed in, failed sign-in, password set or
  changed, signed out, refused for budget, upstream error) with a
  device name, a model or an error code as the detail, never message content;
- legacy video-task rows with their price and the provider's last word, retained
  only for accounting cleanup and removed after three days. Hosted media is
  fully retired, so task polling returns `410 hosted_media_retired` like every
  other hosted media route and never reaches the provider;
- the agent's name and look (`/v1/me/profile`): which face it wears (the dragon,
  an emoji on a colour, or one drawn in the avatar studio, with that face's five
  stills as small WebP pictures), so every device of the account shows the same
  one. The write is partial from relay 0.25: a device sends what changed on it,
  the name alone for a rename, the face with its pictures for a new look, and
  every field it leaves out keeps its stored value (a blank name too), so a
  phone that renames the muse before it has pulled the account's face no
  longer sends the dragon in the name's place and takes the face off every
  other device; an `avatar` other than `face` drops the stored pictures, so no
  device reads `has_face` as a face still worn. The clients of 1.0.3 send the
  whole look on every write and are read exactly as before. Since 0.1.34 the
  same profile lists the account's **connectors**: which
  device connected which service (a label; how it signed in: OAuth, a key, or
  open; and when), so another device can say "connected on your Mac". The
  credential itself stays on the device that holds it; the relay refuses an
  entry that carries anything named like one. Never a key or a setting.
- since relay 0.19, the **synced conversations** (*Sync conversations between
  my devices*, on by default): the text of the account's chats (each
  conversation's title, kind and which device started it, each message's role,
  text, time and device, and the names and sizes of attached files, never the
  files themselves), so every device shows the same ones. Turning the switch
  off deletes all of it; so does deleting the account. The section
  [Conversation sync](#conversation-sync) below has the shape.

- since relay 0.29, **the record**: every chat turn the relay answered, in
  full: the request as the relay sent it to the model (every message: the
  system prompt with your memory, SOUL and instructions, what you wrote, what
  tools returned; the tool definitions; the sampling fields) and the answer as
  the model gave it (content, reasoning, tool calls, finish reason, usage).
  Pictures, audio and clips are taken out and kept once each as files named by
  their SHA-256, a `blob:sha256:` reference standing where each was; a
  screenshot the app resends with every turn of a screen operation is one
  file. With the turn: the model, the platform, the device and conversation
  the app named (`X-NanoMuse-Device`, `X-NanoMuse-Conversation`, 1.0.7 on),
  the token counts (from relay 0.31 with the cached part of the prompt), and
  the address and client software like every request. From relay 0.31 also
  where the turn came from as the app says it: who started it (a person, a
  scheduled task, the feed's routine, a goal's check, another device), its
  turn and step in the conversation, the screen-operation task and step it
  belongs to, and the script of what the person wrote (one word: `zh`,
  `latin`, `ja`, …; never the text itself). The section
  [Provenance](#provenance) has the headers.
  It is the account's own data, so its devices can read it back and the
  operator can see a problem whole; it does not depend on either switch
  below. The section [The record](#the-record) says what is kept, who reads
  it and how it goes.

- since relay 0.31, **what the apps report around a turn**: short records of
  codes and numbers, never a message — what the Sentinel decided about a tool
  call and at which risk, how an approval went, why a reply was stopped by
  hand, a thumb up or down on an answer, how a screen-operation step went.
  Each is tied to the turn's id when the app knows it; the section [Client
  events](#client-events) lists them. They go with the kept turns when the
  person deletes them, and with the account.

Message content is kept as *The record*, *Data controls* and *Conversation
sync* below say, and not otherwise: the request is forwarded to the
operator-configured upstream model and the reply is streamed back. The relay admits at most `CHAT_CONCURRENCY` chat requests to that shared
deployment at once and retries a 429 or 5xx only before output starts; the
remaining requests wait without duplicating a turn. Every response carries an
`X-Nanomuse-Request` id so a problem report
can be matched to a ledger row without any content being logged. Deleting the
account (`POST /v1/auth/delete` with the account's key) removes all of it: the
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
and language from the request headers, tied to the account id only, never the
system prompt (your memory, SOUL and instructions), never what a tool returned
(your files, your screen, what another app showed), never a picture, a clip or
a voice note (a marker stands where one was). The point is a training set for
the community's own open model. From relay 0.31 a turn the app ran on a key
of your own and sent up to the record (`POST /v1/turns`) is kept in the same
training view when the switch is on — a turn is a turn whichever key answered
it — and each kept turn says where it came from (`meta.source` `cloud` or
`own`, `meta.run`, `meta.turn`, `meta.turn_id` naming the record's turn, the
script of what you wrote; see [Provenance](#provenance)), so the app's later
word on it (a thumb, why it was stopped) can be joined by the turn's id. The page shows how many turns are kept; turn
the switch off at any time (nothing more is kept) and delete what was kept
with one tap; deleting the account deletes it too. Nothing is credited for
the switch either way. On `cloud.nanomuse.cn` the switch is **on for accounts
created from relay 0.9 on, until the person turns it off**: the privacy
policy says so, the page says so next to the switch, and accounts from before
keep the choice they had made; a self-hosted relay sets its own default with
`IMPROVE_DEFAULT`. Since relay 0.29 the switch decides only whether the
training view of a turn joins the training set; the turn itself is in [the
record](#the-record) either way, and the same delete tap removes both
(`DELETE /v1/me/samples` answers `{deleted, turns, files}`). The operator sees the kept turns on the admin page's *Data
controls* panel (how many accounts have it on, turns by day, model and app,
the newest turns, every account's kept conversations in full) and exports them
as JSON lines without account ids or addresses (`GET /v1/admin/samples/export`,
`?account_id=` for one account's). From relay 0.31 each exported line carries
`subject`, a pseudonym for the account (an HMAC of the account id under the
relay's secret, 16 hex characters: the same account is the same subject in
every export, and nothing recovers the account from it without the secret),
and the [deletions ledger](#deletions) names the subjects whose data was
deleted since, so a set built from an earlier export can drop them. The relay does not receive a location (the
apps never send one), but from relay 0.10 it records the network address and
the client software (`User-Agent`: the Android app and its version, the
runtime on Windows / macOS / Linux, a browser) with each sign-in, request,
event and device, and keeps the account's first and last address; the admin
page shows them per account and per address (`GET /v1/admin/address?ip=`), and
they are deleted with the account. From relay 0.11 the admin page also says
where an address is (country, province, city), looked up in an offline copy
of ip2region's database on the relay's own disk; no third party is asked, and
nothing more is stored (the place is computed when the page is drawn).

## The record

Since relay 0.29 the relay keeps every chat turn it answered, in full, as the
account's own data, so that a person's devices show the same history with the
screenshots in it, and the operator can see a problem whole instead of
guessing from counts. A turn is:

- the request as the relay sent it to the model: every message (the system
  prompt with your memory, SOUL and instructions; what you wrote; what tools
  returned), the tool definitions, the sampling fields and the relay's
  defaults, with the model named as the app knows it and the relay's own
  `user` and `stream_options` left out;
- the answer as the model gave it: the assistant's message whole (content,
  reasoning, tool calls, finish reason), assembled from the stream when it
  streamed, with the usage; a stream that broke off is kept with what arrived
  and `status: partial`, and `meta.ended` says why (relay 0.30):
  `client_gone` is the app closing the stream (the person stopped it, or the
  app gave up waiting), `upstream_timeout` and `broken` are the provider's
  end;
- the pictures, audio and clips, taken out of the messages and written once
  each to a file named by its SHA-256 (`MEDIA_DIR`, next to the database);
  `blob:sha256:<hex>` stands where each was and the turn's `meta.media` lists
  them with type and size. A screenshot that an app resends with every turn
  of a screen operation is one file however many turns name it;
- the model, the platform, the device and conversation the app named
  (`X-NanoMuse-Device`, `X-NanoMuse-Conversation` on the chat request, 1.0.7
  on), the token counts, the client software and language, and the address
  the request came from (the operator's view only).

It is written after the answer has left, off the request's path, and is never
the reason a chat fails. It does not depend on *Help improve* (that switch is
about the training set) or on *Sync conversations* (that is the apps' own
copy of a chat); `RECORD_TURNS=0` on a relay you run keeps none of it.
The timestamp is captured when the reply finishes. Records from the same account
are saved in that order, including replies with media, while other accounts can
record independently. A failed write does not block that account's later turns.

**Who reads it.** The account's devices: `GET /v1/turns` (newest first; paged
with `before` and `before_id`; `conversation=` for one chat), `GET
/v1/turns/{id}`, and the files at `GET /v1/blobs/{sha256}`; a file opens
only for an account that holds a reference to it (one of its turns, its
profile's clips, an upload of its own); knowing a hash opens nothing. The
person's view leaves the address out. The operator: `GET /v1/admin/turns`,
the export as JSON lines (`/v1/admin/turns/export`, account ids included:
this is the account's data, not the training set, which stays
`/v1/admin/samples/export` without them), one file at
`/v1/admin/blobs/{sha256}`, and `GET /v1/admin/record` for the figures:
turns and files in all and per day, the store against its cap.

In the admin console, changing a filter on Turns or an account's ledger and events
starts a new list. An older page still loading cannot add its rows to that list
or replace its error and loading state.

History and sample pages use the existing timestamp indexes to skip newer seconds before applying the insertion-order tie-break. Exports and the analytics backfill use the same paging boundary; no database migration is needed.

**Turns on your own key.** From 1.0.7 an app that ran a turn on a key of its
own sends it up afterwards, so the record is whole wherever the model was:
`PUT /v1/blobs/{sha256}` for each picture (raw body with its `Content-Type`;
the hash is checked; `HEAD` first, or `known: true` in the answer, says
another device already sent it), then `POST /v1/turns` with `model`,
`messages` (references, or data URLs inline), `response: {message, usage?}`,
and `provider`, `ts`, `conversation`, `id` and `status` as the app has
them (with `status: partial`, `ended` in the app's word: `aborted`, `error`,
`abandoned`), and from relay 0.31 `run`, `turn`, `step`, `trajectory`,
`trajectory_step` and `platform` as [Provenance](#provenance) defines them;
the row says `source: own`. With *Help improve* on, the turn's training view
is kept too, as for a turn the relay answered. The Python runtime does this
for every model call that does not go to the relay — a configured provider,
the ChatGPT sign-in, the hands' own model — while an account is signed in on
the computer: the call is sent up afterwards from a queue in memory, with
the request as it went (less the key), the reply, the usage and the
provenance; pictures past two megabytes go as files first. Signing out
drops the queue; nothing is sent without an account. A reference to a file the account
never put up is a 400 `unknown_blob`. One account sends at most
`RECORD_UPLOADS_PER_MINUTE` turns and files a minute (120; a 429
`rate_limited` says to send the rest later) and holds at most
`MEDIA_ACCOUNT_MAX_MB` of files (2048; a 413 `quota_exceeded`); past
`MEDIA_MAX_GB` in all, nothing is taken from anyone until the hourly trim
has run (507 `store_full`). Both are written off the request's loop.

**The face's clips.** The same files carry the drawn face's clips between
devices: the device that animated it puts the clips up and names them in the
profile (`clips: {mood: {sha256, mime, bytes}}` on `PUT /v1/me/profile`),
the others download them instead of rendering their own. The clips go with
the face: `clips: null`, another avatar or `DELETE /v1/me/profile` clears
them.

**How it goes.** *Settings → Data controls*' delete removes the record with
the training turns: every turn of the account and every file only it
referenced; deleting the account does the same; `RECORD_KEEP_DAYS` (0 on
`cloud.nanomuse.cn`: kept until you delete it) sweeps older turns once an
hour. The files are bounded by `MEDIA_MAX_GB`: past it the least recently
used go first, the turns stay and show a reference to nothing where those
pictures were; a clip a profile wears is never trimmed. A file the disk would
not let go of at the moment of a delete is tried again at every sweep until
it is gone. `/v1/me.contribute.record` tells the apps what is held:
`{on, turns, own, files, media_bytes, keep_days}`, and the answer to `POST
/v1/me/contribute` carries the same `record`. The account page at `/app`
shows the record (turns, own-key turns, files, how long the relay keeps
them) above the *Help improve* switch, and offers the one delete whenever
either holds anything.

**Questions and calls (0.31).** A person's one message often takes the
agent several model calls: it asks for a screenshot, taps, reads the screen
again, answers. The record keeps one row per call, so counting rows
overstates what people asked; the relay now counts both ways. Each row says
whether it *opened a question* (`turn_start`): the app's `step` settles it
(1 opens); without one, the last message of the request does — from the
person it opens, from a tool or the assistant it continues; a request with
no message of either kind opens. Every row carries `turn_key`, the id of the
row that opened its question (a continuation finds it by the conversation's
`turn` number, or failing that the nearest earlier opener in the same
conversation), so the question's calls group in SQL; the training view's
shape rows carry the same two fields. Rows from before get theirs from a
backfill in the analytics loop, oldest first; until it reaches them they are
counted in neither figure and `GET /v1/admin/record` reports them as
`questions.pending`. The figures: `/v1/admin/record` has `questions` beside
`n` for the whole, the period and each day, and a `questions` block (how
many, how many carried a picture or ran the hands by the trajectory the app
named, how many calls each took as buckets `1`, `2-3`, `4-7`, `8-15`,
`16+`, and the mean); `/v1/admin/data` has `turns` beside `samples` in its
totals, days, models, platforms, runs, sources and accounts.

**What that costs.** A turn's row carries its request, and the columns the
figures sum sit after it in the row, so a sum that read them walked every
body: half a minute for a week of turns on a 30 GB file, more with the
cache cold. The figures and the question-by-question list read an index of
those columns instead (`turns_figures`, built at the first start after the
upgrade in one pass over the record) and answer in well under a second. The
backfill reads and rewrites the record's rows a hundred at a time, writes
them twenty-five per transaction, and pauses after each page for as long as
the page took, so the console and the apps keep their share of the disk
while it runs: an hour or so for a hundred thousand calls.

To read a question whole, `GET /v1/admin/record/turns` returns the newest
questions first, each laid out once from its calls: the person's message,
a step per call (the call's figures, what the model said or the tools it
called, and what came back before the next call — tool results, the hands'
screenshots, a message the person added), the reply the person saw, the
tools in order, and the figures summed (`calls`, tokens, `media`, `models`,
`sources`, `partial`). Texts over 4000 characters are cut with `truncated:
true`; `GET /v1/admin/turns/{id}` has the whole call. Filters: `account_id`,
`conversation`, `platform`, `run`, `source`, `model`, `script`, `media=1`
(a picture somewhere in the question), `hands=1` (a trajectory named),
`since`; pages of up to 100 with `before` (the question's last timestamp)
and `before_key`. The console's *Question by question* page shows the same:
the pictures and screenshots inline where they were sent (fetched with the
admin token, so an `<img>` alone would not do), each tool call with its
arguments folded, the final reply marked, and the whole call one click away;
the *Data and sync* page shows questions beside calls everywhere it counted
calls before, and an account's *Kept turns* tab (one row per call) links to
the same page filtered to that account.

## Provenance

A model call is one of many in a conversation, and the app knows things about
it that the request body does not say. From relay 0.31 the apps say them in a
few headers on the chat request, and in fields of the same names on a turn
they send up from a key of their own (`POST /v1/turns`; the headers fill in
what the body leaves out). Each is optional; an app from before sends none,
and the relay stores *not said*, never a guess.

| header | body field | what it says |
| --- | --- | --- |
| `X-NanoMuse-Run` | `run` | who started the turn: `person` (someone typed or tapped), `schedule` (a scheduled task), `feed` (the feed's daily routine), `goal` (a goal's check or evaluation), `hub` (this device ran it for another device's request). Lower case, `[a-z][a-z0-9_]{0,23}`; a word the relay has not met is kept as said |
| `X-NanoMuse-Turn` | `turn` | the turn's number in the conversation, from 1: the person's first message is turn 1, the reply to their second message is turn 2 |
| `X-NanoMuse-Step` | `step` | the model call's number within the turn, from 1: a turn that calls tools makes several |
| `X-NanoMuse-Trajectory` | `trajectory` | the id of the screen-operation task this call belongs to (`[A-Za-z0-9_.:-]{1,80}`), the same on every step of it |
| `X-NanoMuse-Trajectory-Step` | `trajectory_step` | the step's number within the task, from 1 |
| `X-NanoMuse-Platform` | `platform` | the app's own word on its platform when its user agent would not say (the desktop's uploads go out from Node; the runtime's calls from an SDK): one of `android`, `ios`, `desktop`, `windows`, `macos`, `linux`, `runtime`, `browser`. Anything else is ignored and the user agent decides |

`X-NanoMuse-Device` and `X-NanoMuse-Conversation` (1.0.7) are unchanged and
go with these. The relay keeps the six in the turn's row of the record
(`run`, `turn`, `step`, `trajectory`, `trajectory_step`, read back on `GET
/v1/turns` when said), in the kept turn's meta when the switch is on, in the
call's telemetry row (`run`, so the Usage and Platforms pages can tell a
person's turn from a routine's) and in the training view's shape rows. The
record's row also carries `script`, one word for the script of the person's
last message (`zh`, `ja`, `ko`, `ru`, `ar`, `th`, `hi`, `he`, `el`, `latin`,
or none), computed as the turn is written and kept instead of the
`Accept-Language` header most apps leave empty.

## Client events

From relay 0.31 the apps report what happened around a turn that the request
itself does not show, as short records of codes and numbers: `POST /v1/events`
with `{"events": [{kind, ts?, turn?, conversation?, data}]}`, at most 100 per
request and 60 requests a minute from one account (a 429 says to send the rest
later); the answer is `202 {kept, dropped}`. `kind` is dotted lower case;
`turn` is the record's id for the turn (the `x-nanomuse-request` header of a
Cloud turn; an own-key turn's `id` with `"source": "own"` beside it, which the
relay turns into the record's `own-…` form); `data` is a flat object of at
most 16 short codes, numbers and booleans. A value that looks like prose (over
120 characters, or not of `[A-Za-z0-9_.:/ -]`) is left out, a nested object is
left out, an event of the wrong shape is dropped and counted, not refused:
this is how the relay keeps the promise that no message travels here. The
kinds and what their `data` holds:

| kind | data |
| --- | --- |
| `sentinel.decision` | `tool`, `risk` (`safe`, `moderate`, `sensitive`, `critical`), `decision` (`allow`, `ask`, `deny`), `grant?` (`once`, `schedule`, `conversation`, `always`: the permission that covered it), `policy?` (what the policy said before anyone was asked), `by?` (who settled it: `policy`, `auto`, `grant`, `person`, `timeout`), `channel?`, `tainted?` (bool), `warnings?` (count), `ok?` (bool: whether the tool then ran without an error; the desktop sends it, the runtime does not), `class?` (the phone's own class of the step: Android's risk gate says `safe`, `install`, `destructive`, `outbound`, `remote` or `money`; the iPhone's permission check says `privacy`, `media` or `system`, the category of the `apple-*` command) |
| `approval.result` | `tool?`, `risk?`, `allow` (bool), `scope?` (`once`, `schedule`, `conversation`, `always`), `by?` (`person`, `timeout`, `other_device`, `auto`: the app answered no itself, as the iPhone does for a hub task while it is not on screen), `waited_s?`, `channel?`, `warnings?` |
| `turn.stopped` | `reason`: `wrong`, `slow`, `changed_mind`, `done`, `other`, `skipped` (the person stopped a reply and said, or did not say, why), `turn_no?` |
| `turn.feedback` | `vote` (`up`, `down`, `none` when taken back), `reason?` (`wrong`, `unhelpful`, `unsafe`, `slow`, `other`), `turn_no?` |
| `turn.ended` | `ended`: `aborted` (the person pressed Stop), `error`, `abandoned` (a turn kept short, in the app's word; the runtime sends `aborted` for every stopped run, whichever key it ran on), `turn_no?` |
| `hands.step` | `trajectory`, `step`, `action` (the action's kind: `tap`, `type`, `open_app`, …; `end` closes the run), `outcome?` (`ok`, `failed`, `refused`, `stopped`, `handed_over`; on `end`, the run's status: `done`, `ask`, `blocked`, `stopped`, `failed`, `max_steps`), `latency_ms?` (the model's time on the step) |
| `app.opened`, `screen.viewed` | `screen?` (a screen's code name) |

The operator reads them at `GET /v1/admin/client-events` (newest first;
`kind=` a comma list, `account_id=`, `before=` the last id shown), exports
them as JSON lines with the `subject` pseudonym and no account id
(`/v1/admin/client-events/export?since=`), and sees the figures on the admin
page's *Data controls* panel (`/v1/admin/client-events/summary?days=`: by day
and kind, and the split of each kind's codes: what the Sentinel decided, how
approvals went, why replies were stopped, how the thumbs fell). *Settings →
Data controls*' delete removes them with the turns; deleting the account
removes them too.

## Deletions

A training set built from an export outlives the relay's rows: when a person
deletes their kept data (`DELETE /v1/me/samples`) or their account (`POST
/v1/auth/delete`), the relay writes one line to a ledger — the account's
`subject` pseudonym, the time and the scope (`samples` or `account`) — and
nothing else about them stays. `GET /v1/admin/deletions?since=` lists the
lines, oldest first; whoever builds a set from the exports reads it before
each build and drops every line of those subjects. The pseudonym names nobody
without the relay's secret, and the ledger is all that outlives the account on
purpose. The person console's *Data controls* page says so next to the delete,
and the privacy page repeats it.

## Conversation sync

*Settings → Data controls → Sync conversations between my devices* (0.1.36,
relay 0.19) is the other switch on that page, **on by default** for a signed-in
account. With it on, each device pushes the text of its turns to the relay and
pulls what the others pushed, so the phone, the computer and the web app show
the same chats: the title of each conversation, who started it, and each
message's role, text, time and device. Files and images are not uploaded; a
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
goes up the moment it is sent (the other devices see it in real time, before
the reply) and the assistant's final text when the turn ends; signing in or
turning the switch on sends the device's whole eligible history, oldest first,
200 messages a request. The muse's name is part of the account's profile: a
rename on any device, including the first conversation's naming, reaches the
others on the next pull.

**Main first** (0.1.38, relay 0.20). By default only the main conversation
travels: side chats stay on the device that made them, and a device pulls with
`scope=main` so other devices' side chats never arrive. *Also sync side chats*
(a second switch under *Data controls*, off by default, **per device**; the
relay has no account-wide setting for it) turns that around for the device it is
flipped on: its side chats go up, the other devices' side chats come down, and
the first pull after the flip starts over from zero. Two kinds of chat never
travel, switch or no switch: a chat the desktop runs for another device's task
(*From Pixel 8*, that device's conversation) and a chat the desktop's rooms run
for themselves, the feed's daily batch among them (*Feed · <date>*, archived
when it is done) — those are the agent's workbench, not conversations of the
person's, and through 1.0.9 the batches did reach the phones as side chats
once a day ([#713](https://github.com/nano-muse/nanoMuse/issues/713)). The first pull of a fresh
sign-in asks for the **tail**, the newest 300 messages with the conversations
they belong to, so a long history opens at once instead of paging from the
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
`sync_off` until the switch is turned on again; their switches follow.
*Delete synced conversations* on the same page empties the store and leaves the
switch as it is. Nobody but the account's devices can read the store: the
operator's admin page shows counts only (accounts with it on and off, how many
conversations and messages, their size), never a text, never which account
(`GET /v1/admin/sync`). The pulls are triggered by the hub's `sync` frame
([hub.md](hub.md#frames)), at launch, when the hub socket reconnects or the
desktop window comes back to the front, and once a minute; on the desktop a
turn already received from another device stays above any prompt sent on this
computer after it arrived, even if the two devices' clocks disagree.

The API, all under the account's key (401 without one; 409 `sync_off` while the
switch is off, for reads as well as writes):

```
GET    /v1/sync/state                   → {enabled, cursor, counts{conversations, messages}, limits{messages, text_bytes, conversations}, working[]}
PUT    /v1/sync/state   {enabled}       → the same; false deletes everything stored, the counter keeps counting
GET    /v1/sync/changes ?since=0&limit=500&scope=all|main&tail=K   → {cursor, more, conversations[], messages[], skipped?}
POST   /v1/sync/changes {device, conversations[], messages[]}   → {cursor, accepted, rejected[{cid | mid, reason, cid_main?}]}
POST   /v1/sync/working {cid, working, device?, state?, detail?}   → 204; the hub tells the other devices (0.31: state and step ride along)   404 no_conversation
DELETE /v1/sync/changes                 → the state, counts at zero     everything stored, switch unchanged
DELETE /v1/sync/conversations/{cid}     → {cursor, deleted: true}      a tombstone the other devices apply; 404 no_conversation
```

`scope` (relay 0.20) is `all` unless said; `main` returns only the main
conversation and its messages, and an account with no main yet gets an empty
page whose `cursor` is the account's counter. `tail=K` (K ≤ 500, honoured with
`since=0` only) returns the newest K messages in `seq` order, the conversations
they belong to, `cursor` at the account's counter, `more: false` and `skipped`
(how many older messages were left out). From relay 0.25 the tail page also
carries the account's main conversation's row whenever it exists, even with no
message of its own among the K, so a fresh device adopts `cid_main` from its
first pull instead of minting a second main and learning the id from a
`main_exists` refusal (a 1.0.3 client reads the extra row as any conversation
row and behaves the same). Any other `scope` is 400 `bad_scope`.
`POST /v1/sync/working` says the device named in `device` (or in
`X-Nanomuse-Device`) is answering in `cid` (`working: true`) or has finished
(`false`); the relay keeps the live ones in memory for ten minutes (never in
the database, so a restart forgets them), lists them under `working` in the
state (`[{cid, from, device_name, working, at}]`) and sends a `working` frame
to the account's other sockets ([hub.md](hub.md#frames)). Since 0.31 a
`working: true` may also say `state` (`working` | `waiting`) and `detail` —
the run's current step in the model's own words, capped at 160 characters —
and the frame and the state's `working` rows carry both, so the other devices
see the run move between its start and its end. Request bodies over
`MAX_REQUEST_BYTES` (16 MiB by default since 0.20) are 413 `too_large` with
*Request body is N MB; this relay accepts up to M MB*.

A retry keeps the original `mid`, including when the relay accepted the message but
its response was lost. The desktop derives new message IDs from the device, local
session and local line ID; existing persisted message IDs remain recognized. The
accepted ID format and other clients' UUIDs are unchanged. The desktop saves its
conversation mapping before upload, so a lost response followed by a restart also
keeps the same conversation ID.

A conversation is `{cid, kind: main | side, title, device, device_name,
created_at, updated_at, deleted, seq}` and a message `{mid, cid, seq, device,
device_name, role: user | assistant, text, truncated, attachments[{name, mime,
size}], created_at, deleted}`; `cid` and `mid` are opaque IDs the device makes (4–64
characters of `a-z 0-9 . _ : -`, folded to lower case), times are Unix seconds.
Every accepted change takes the account's next `seq`; a device keeps the
highest `cursor` it has pulled and asks for `since=` that. A push is idempotent
(a known `mid` is left alone unless the new row is a tombstone, a known `cid`
takes the newer title; a time more than a week past the relay's clock, or
before the conversation began, is read as the conversation's `created_at`,
relay 0.25, where earlier relays measured the week from `created_at` and so
dropped every rename of a chat older than a week) and at most 200 messages or
conversations long (413 `too_many_messages`). A page lists its conversations and messages in `seq`
order, and the relay adds the conversation of every message in the page even
when that conversation's own `seq` lies ahead (a rename moves it), so a client
applies the page's conversations first, then its messages, and is never handed
an orphan. Refusals name the row: `main_exists` with `cid_main` when a second
`main` is pushed (the device then re-sends under `cid_main`), `conversation_limit`
(relay 0.23, the account's side conversations are at their cap), `unknown_cid`,
`conversation_deleted`, `bad_cid`, `bad_mid`, `bad_kind`, `bad_role`. A
tombstone keeps its row for 30 days and is then swept. After an accepted push
or a deletion the hub tells the account's other devices with a `sync` frame
(`DELETE` from the console carries the deleting device in `X-Nanomuse-Device`
so it can skip its own echo).

## Allowance

The admin console's Usage dates, day picker and People sign-up chart follow the
relay's `DAY_OFFSET_H` calendar. Viewing them from a different browser timezone
does not shift a day's label or move its sign-ups into an adjacent day.

nanoMuse is a community project and charges nothing. The public relay at
`cloud.nanomuse.cn` is paid for by the developer, so each account has a pool
to draw on, for its lifetime, not by the day (relay 0.5):

| | `cloud.nanomuse.cn` |
|---|---|
| sign-up | open to anyone with a mainland China mobile number or an e-mail address |
| free allowance | **¥10 per account** at the time of writing, for the hosted Qwen chat/vision/GUI model; it does not reset. The figure is the relay's to set (it can go up without an app update; the apps print what the relay says, `/v1/config`), and the account page always shows the current one |
| invitations | each *new* person who signs up with your code adds **¥5** (again, the relay's figure) to your pool, and the same to theirs; both sides get it after your friend's first request, not at sign-up |
| when it is gone | bring your own key or a plan you already pay for: in mainland China, [Alibaba Cloud Bailian](own-key.md) first (one key covers chat, the hands, pictures and clips); elsewhere, [OpenRouter](https://openrouter.ai/keys) or OpenAI first (Bailian only signs up accounts from mainland China); a ChatGPT, Claude or Kimi plan signs in where the client has the flow; any OpenAI-compatible endpoint works; sign-in and your devices are unaffected |
| members | the developer and the people they list have no limit and may name other chat models from the hosted provider; hosted image and video generation stays disabled for them too |
| rate | 30 requests per minute |
| tokens | no ceiling; usage is metered and shown |

Spend on `Qwen/Qwen3.6-27B-FP8` is counted at ¥3 input / ¥12 output per
million tokens, with cached input at 20% of the input price, as reported in
the reply's `usage`. Reasoning tokens count as output. Image input is part of
that chat request; it is not image generation. Hosted picture and clip
generation is not charged because it is not available: add a provider and API
key of your own for those capabilities.

*Settings → nanoMuse Cloud* shows what was used of the pool in ¥ and $, what
is left, and how the pool grows. At 80 % the app says so once; when the pool
is spent the relay refuses with `allowance_exhausted` and the app shows the
ways on: your own key, a plan you already pay for, or an invitation (+¥5 for
each of you, or whatever the relay says that day). Which provider comes first
follows where you are (0.1.34: the relay's `region`, read from the number's
country code or from an offline copy of ip2region on its own disk; nothing is
sent anywhere): a mainland China account is pointed to Alibaba Cloud Bailian
(the provider form opens pre-filled, [guide](own-key.md)) and everyone else to
OpenRouter or OpenAI, since Bailian only signs up accounts from the mainland.

Since relay 0.21 the refusal and `/v1/me` carry the whole card as data, not
only two links (contract C11): `spend.guidance` (and `guidance` beside the
`allowance_exhausted` error) lists the region's providers in order with what
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
A provider whose vendor wants one stable id per conversation (the catalogue's
`session_header`, OpenCode Go) is listed apart, under `session_providers`, with
that header named: the phone apps of 1.0.1 and before read `providers` only and
do not send the id, so they never offer it; the apps that send it append the
list to `providers`.
Other relays may set other rules
(`ALLOWANCE_CNY`, `INVITE_BONUS_CNY`, `SIGNUP_OPEN`, `ALLOWED_IDENTIFIERS`;
all three figures adjustable while the relay runs, relay 0.15; see
[`cloud/README.md`](../cloud/README.md)). The operator can see who invited
whom: the admin page's *Invites* view ranks the inviters by the accounts their
code brought, with how many of those ever made a request, how many are still
pending (no first request yet, so no bonus yet) and how many were seen from
one of the inviter's own addresses, and an account's page names its inviter
and lists the people it brought (`GET /v1/admin/invites`). Padding one's own
pool is not worth the trouble: the bonus is paid once the invitee has
accumulated real successful provider spend (`INVITE_SETTLE_MIN_SPENT_UY`, 200
micro-yuan by default) from a network address different from the inviter's,
e-mail `+tag` subaddresses and Gmail dot or `googlemail.com` aliases map to
the same account, disposable mail domains (`DEFAULT_SIGNUP_DOMAIN_BLOCK` plus
`SIGNUP_DOMAIN_BLOCK`) are refused, new accounts from a mail domain that is
not a well-known provider are limited per day (`SIGNUP_PER_DOMAIN_DAY`, 5 by
default; the refusal is `domain_limited`), and the health check raises two
alerts, an inviter whose code brought more than ten accounts in a day and an
inviter with twenty or more invitees of whom almost none ever made a request.
Each unfolded inviter in the *Invites* view, and the *Brought* card of its
account page, has one action that reclaims the invite credit (what was
already spent stays), and may disable the account and delete the invited
accounts that never made a request (`POST /v1/admin/invites/abuse`).
Every operator action on an account is on record: disabling or enabling it,
making or unmaking a member, a grant, a credit, a pool change, a settings change
and a deletion each write a line in the audit log of the Controls section (who,
from where, which account by the first eight characters of its id) and, where the
account keeps a timeline, a line on it too; a deletion is counted on the Stats
page. A disabled account that asks for a sign-in code gets the same `204` as anyone
and no message is sent: the request counts towards the usual limits, nothing goes
out, and the route says nothing about whether the number has an account or whether
it is off; the person is told `403 account_disabled` when they sign in with a code,
or with the right password (a wrong one is answered like any wrong password).

nanoMuse asks for one thing in return: a star on
[GitHub](https://github.com/nano-muse/nanoMuse), which is what helps the
project be found. The moments are the relay's to set, not the app's (0.1.35):
`GET /v1/nudges` says when an ask is fair: after the third, tenth and
thirtieth task it finishes for you, on the seventh and thirtieth day you open
it, when a goal is reached, when a new face is drawn, once on the account page,
and when the pool is spent, with at least a week between two asks and at most
four per device. Each ask is a card where it happens; "Not now" counts as one,
and none comes back after you have been to the page or said "I already
starred" (per device; the account does not carry the flag). The operator changes the
policy on the admin page (*Settings › Star asks*) without an app update; every
app keeps the same defaults built in for when the relay cannot be reached. The
policy says *when* and, if the operator wants, *what*: the words on the card
are each app's own, in its language, unless the policy carries a sentence:
`star.text` (English) and `star.text_zh` (简体中文), each at most 200
characters, empty by default. An app in Chinese shows `text_zh` when it is
set, else `text` when it is set, else its own sentence; an app in any other
language shows `text` when it is set, else its own. Only the sentence on the
card changes; its title and buttons stay the app's. Apps built against relay
0.22 and earlier ignore the two fields.

## Controls

In the admin console, a People table or a Usage day's top accounts expanded with
*More* keeps its visible rows when polling refreshes the data. If the list becomes
shorter, the expansion shrinks with it.

The operator can pause parts of the relay without a restart or a deploy
(relay 0.22, *Controls* on the admin console; `nanomuse-cloud admin controls
…` on the command line; see [`cloud/README.md`](../cloud/README.md#controls-022)).
Six switches, each on by default, each kept in the database so a restart
keeps it, each with a line in an audit log saying who flipped it, when and
why. What an app sees when one of the five pauses is off:

| switch | what the app gets while it is off |
|---|---|
| **Free allowance** | a limited account (no key of its own, not a member) asking a model gets **429 `allowance_exhausted`** with `paused: true` and `reason: "allowance_paused"`, the same shape as a spent pool, so every app shows its own-key card as it does today, with a message saying the allowance is paused for now rather than spent. Members, sign-in, devices and sync are unaffected |
| **Sign-ups** | a phone number or an e-mail address that has no account yet gets **403 `signup_closed`** from `POST /v1/auth/code` and from `/v1/auth/verify`, before any code is sent; `signup_open` in `/v1/config` turns false. Every existing account signs in and works as before |
| **Cloud service** | every API call answers **503 `service_paused`** with `paused: true`, except the health check, `/v1/config`, the admin console and `/v1/admin/*`; every hub socket is closed with `4003 hub_paused`. Nothing is deleted; a signed-in app keeps its key and signs back in when the switch returns |
| **Conversation sync** | `/v1/sync/*` pushes and pulls answer **503 `sync_paused`**; `GET /v1/sync/state` still answers and says `paused: true`. What is stored stays; each device keeps working on its own |
| **Device hub** | `WS /v1/hub` accepts and closes at once with **4003 `hub_paused`**, the open sockets are closed the same way, `GET /v1/devices` answers 503 `hub_paused`. Each device keeps working on its own |

The switches that are off are listed under `paused` in `/healthz`,
`/v1/config` (public, a minute's cache) and `/v1/me`, so a client can say why
before it tries. The apps handle the codes as any refusal: the phones and the
console show the relay's sentence; the `allowance_exhausted` shape is the one
they already draw a card for.

The sixth switch, **nanoMuse clients only** (relay 0.28, on by default), works
the other way round: while it is on, the models answer the nanoMuse apps, the
desktop app, the Python runtime and the web console in a browser, and any
other software calling `/v1/chat/completions` with a nanoMuse key (a pool
worker, an SDK, a script, the unbranded upstream app) gets **403
`client_not_supported`** with the client's name under `client` and a sentence
saying to use a key of its own there. The relay reads the `User-Agent` for
this, so it stops honest programs, not impostors. Members are answered from
anything; sign-in, the account page, sync and the hub are not affected; a
refusal costs nothing and is a `client.refused` line on the account's
timeline. The apps never see this code: every one of them names itself, and
the runtime of 1.0.6 and earlier, whose model calls carried the OpenAI SDK's
own string, is recognised by that string (the runtime names itself from
1.0.7). Off, the relay answers any client with a valid key, as it did before
0.28.

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

API and error counters are written through the relay's worker pool. The response awaits these writes, while the event loop remains available if a counter write waits for a database lock.

Anyone can run a relay (for a family, a class, a company) and point the app
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

The relay is also the meeting point for the account's devices: the **hub** at
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
GET  /healthz                                                 → {ok, version, models[], paused[]}; no key
GET  /v1/config                                               → {version, signup_open, paused[], allowance_cny, allowance_usd, invite_bonus_cny, invitee_bonus_cny, usd_cny, invite_url, own_key_docs, openrouter_url, privacy_url, repo_url, improve_default, code_ttl_s, password_min_len}; no key, a minute's cache
POST /v1/auth/code          {identifier}                      → 204 (a disabled account gets the same 204 and nothing is sent); 400 phone_region, 403 not_invited | signup_closed, 429 code_too_often | domain_limited, 502 send_failed
POST /v1/auth/verify        {identifier, code, device, invite?, device_id?, device_kind?} → {api_key, base_url, account, tokens, models, created, region}; the optional identity binds the key to that Hub device (hub.md); 400 code_wrong | code_expired | bad_device, 403 account_disabled
POST /v1/auth/login         {identifier, password, device, device_id?, device_kind?} → the same; 401 bad_credentials, 429 locked, 400 bad_device
POST /v1/auth/password      Bearer  {password, current?}      → 204; "" with current removes it; 400 password_short | password_long | password_weak | password_wrong | password_required
POST /v1/auth/session-key   Bearer  {device?, ttl_s?}         → {api_key, expires_at}; a key that lapses on its own (90 days at most); 403 session_from_session
GET  /v1/me                 Bearer                            → {region: cn | intl | unknown, account{…, has_password, sessions, signed_in_via}, usage{today, total by kind / model}, tokens, spend{…, ways, guidance}, invite, contribute, models, defaults, base_url, clips, recent, nudges, paused[]}
GET  /v1/me/invite          Bearer                            → {code, url, invites, bonus_cny, invitee_bonus_cny, bonus_when: "first_use", settled, pending, earned_cny, friends[]}
GET  /v1/estimate           Bearer  ?images=5&clips=4&image_model=&video_model=&size=  → {cny, usd, parts[{kind, model, count, seconds?, cny}], left_cny, grant_cny, unlimited, affordable}; nothing charged
POST /v1/me/contribute      Bearer  {on}                      → {on, samples, default_on, keeps[], privacy_url}; the "help improve" switch
DELETE /v1/me/samples       Bearer                            → {deleted}; every turn kept from this account
GET  /v1/nudges                                               → {version, star{enabled, url, moments{signed_in, tasks[], new_look, exhausted, days_used[], goal_done}, cooldown_days, max_asks, text, text_zh}}; no key, cached an hour
GET  /v1/me/profile         Bearer  ?face=false               → {rev, device, name, avatar, …, face?, connectors: [{id, label, url, auth, device, device_id, enabled, at}]}
PUT  /v1/me/profile         Bearer  {device, name?, avatar?, …, face?, connectors?}  → {rev, device}; a field that is absent keeps what is stored (relay 0.25); a device's connectors replace only its own; 400 no_secrets_in_profile, too_many_connectors
DELETE /v1/me/profile       Bearer                            → 204
GET  /v1/me/sessions        Bearer                            → {sessions: [{prefix, device, via, created_at, last_used_at, expires_at, current}]}
DELETE /v1/me/sessions/{prefix}  Bearer                       → 204; 404 no_session
GET  /v1/me/events          Bearer  ?limit=50                 → {events: [{ts, kind, detail}]}
POST /v1/auth/sign-out      Bearer                            → 204
POST /v1/auth/sign-out-all  Bearer  {all?}                    → {signed_out}
POST /v1/auth/delete        Bearer                            → 204
GET  /v1/devices            Bearer                            → {devices: [{id, name, kind, os, version, actions[], online, last_seen, controllable, ip}]}; 503 hub_paused
DELETE /v1/devices/{id}     Bearer                            → 204; 409 device_online
```

`code_ttl_s` and `password_min_len` in `/v1/config` are the relay's `CODE_TTL_S`
and `PASSWORD_MIN_LEN`; the web console prints them in its sign-in and password
forms, so a relay that sets other figures is described rightly, and an older
relay without the two fields is read as ten minutes and eight characters.

Everything else is the OpenAI API: `GET /v1/models` (with `architecture`
modalities so the picture model is recognisable, and a `nanomuse` block per
model with its `kind`, prices, `for` (the lane(s) a chat model is for: `chat`
and / or `gui`) and `recommended_for`), `GET /v1/models/{id}?kind=chat` (a
member checks a typed id: `listed`, `priced_as`), `POST /v1/chat/completions`
with streaming, `POST /v1/images/generations` and `/v1/images/edits`, and the
clips under the provider's own paths (`POST
/api/v1/services/aigc/video-generation/video-synthesis`, `GET
/api/v1/tasks/{id}` for the account's own tasks, `GET /api/v1/uploads`). Errors
are `{"error": {"message", "type": "nanomuse_cloud", "code"}}` with a stable
`code` the app turns into a sentence. On the hosted service, new image/video
requests, uploads, typed media-model lookups, media estimates and video-task
polling return `410 hosted_media_retired` with
`action: configure_own_provider` before any upstream request. Relay 0.22 adds the codes of the
operator's [switches](#controls): `403 signup_closed`, `503 service_paused`,
`503 sync_paused`, `503 hub_paused` (and the hub's close code `4003
hub_paused`), and `allowance_exhausted` with `paused: true` when the free
allowance is paused rather than spent; `/healthz`, `/v1/config` and `/v1/me`
list the switches that are off under `paused`.

**Before the model says anything (relay 0.31).** A streamed chat turn may begin with
chunks that have no `choices`: `{"object": "chat.completion.chunk", "model", "created",
"choices": [], "nanomuse": {"phase", "waited_ms", "ahead"?}}`. While the request waits for
one of the relay's provider slots (`CHAT_CONCURRENCY`), one comes every five seconds with
`phase: "queued"` and `ahead`, how many requests are in front of it; when its slot comes,
one with `phase: "working"`; a request that never waited gets none. While the provider
takes its time over the first bytes, a comment line (`: keepalive`) goes out every ten
seconds. An SSE parser skips comment lines by definition, and a chunk without choices is
the shape of the usage-only chunk every client already handles, so a client that knows
nothing of either sees the reply it always saw; the apps read the field and say how many
are ahead and how long the turn has waited. Nothing of this is in a non-streamed turn,
and nothing of it is charged or recorded.

A key the relay does not know answers
`401 bad_key`; from 0.1.40, a key whose account was deleted answers
`401 account_deleted` instead, on every call that takes a key (`/v1/me`,
`/v1/models`, `/v1/chat/completions`, the sync and hub calls), for 90 days
after the deletion; the relay keeps the hashes of a deleted account's keys that
long, and nothing else. A client that does not know the code sees the same
`401` as before; a client that does (the phones) removes the account's local
data on `account_deleted` and keeps it aside on anything else
([sync.md](sync.md)). The full table of codes is in
[`cloud/README.md`](../cloud/README.md).

Devices: `GET /v1/devices` lists the account's devices (online or last seen),
`DELETE /v1/devices/{id}` forgets an offline one, and `WS /v1/hub` is the hub
itself; the frames are in [hub.md](hub.md). Conversations: `/v1/sync/state`,
`/v1/sync/changes` and `/v1/sync/conversations/{cid}`; see the section
[Conversation sync](#conversation-sync) above.
