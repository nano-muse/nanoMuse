# The hub: every device is a Muse

Sign in to the same nanoMuse Cloud account on a phone, a computer and a browser,
and they see each other. Each device runs its own Muse with its own hands (the
phone's apps and sandbox, the computer's shell and screen), and any of them can
ask any other for something, from any network. The web console has no hands of
its own; it is a front door to the rest.

```
phone ──┐                         ┌── computer (nanoMuse Desktop)
        ├──▶  nanoMuse Cloud  ◀───┤
web  ───┘        /v1/hub          └── another phone / computer
```

Every device opens one outbound WebSocket to the relay and keeps it. Nothing
listens on the device, nothing needs a port forwarded or a shared Wi-Fi; the
relay only routes frames between devices of one account and never looks inside
a task. This is the way to add a computer: install nanoMuse Desktop on it and
sign in with the same account; nothing to download by hand, no code to type.
It is the only way in: the stand-alone host script that paired over the local
network (0.1.13–0.1.23) is gone, so a computer that is missing from the phone's
list has, nearly always, signed in with another account; *Settings → Computers*
on the phone shows which account the phone uses.

## What you can say

On the phone, in any chat:

- "在我 Mac 上列一下下载文件夹": `nanomuse-pc ls ~/Downloads --on mac`
- "让电脑把项目编译一遍，把日志发给我": `nanomuse-pc task "…" --on desk`
- "电脑截个图给我看": `nanomuse-pc screen --on desk`

On the computer, in nanoMuse Desktop (or `nanomuse chat` in a terminal):

- "on my phone, take a screenshot": `device_screen`
- "tell the phone's Muse to read me the last notification": `delegate`
- "send the phone a notification: dinner's ready": `device_notify`

In the web console (`/app`): pick a device, type. The task runs on that
device's Muse; approvals show as cards in the page.

Two kinds of request travel over the hub:

- **Actions.** `info`, `shell`, `files`, `file.get`, `file.put`, `open`,
  `screen`, `notify`. Raw and immediate. A `shell` command is judged *on the
  caller* before it is sent, with the same ladder as a local command (the
  phone's ShellGuard, the desktop's `guard.py`): reads and builds go quietly,
  deleting / sending / paying / system commands wait for the approval card on
  the device that asked.
- **Tasks.** `task {text, conversation?, language?, stream?}`: a whole job in words for the target device's own
  Muse, in a conversation of its own (`conversation` names it; the sender's id
  when absent). `language` (runtime 1.0.0, optional) is the BCP-47 tag of the
  asking device's screens; the target answers in it instead of guessing from
  the text. It may take minutes. When that Muse hits
  something that needs approval, it does not decide alone: the question travels
  back as an `event {stage:"approval"}` and the asking device shows its usual
  card (RiskGate on the phone, the terminal prompt on the desktop, a card in the
  web console). The answer goes back as `approve {approval_id, allow}`.
  The asking device may end a task it started with `stop {call}` (the id of
  its `task` frame) or `stop {conversation}` (the conversation it named, or
  its own per-device one when it named none): the target cancels the run
  after the step in flight, answers `{stopped: true}`, and the `task` call
  itself then fails with `cancelled`. `{stopped: false}` means there was
  nothing of the caller's to stop; a device never stops another device's
  task. The runtime, the desktop app and the phone all do this. A `task`
  for a conversation that is already running one fails at once with `busy`
  (the runtime): the caller waits for the first to answer, or stops it, and
  asks again. A task that has not answered within the hub's limit fails with
  `timeout`, one the target's Muse could not run with `failed`. A task that reached its
  conversation but never started (the step was refused before the model was asked) fails
  too, with `failed`, rather than answering with no words: the asking device shows that
  sentence and not an empty result. On nanoMuse Desktop a chat of the conversation that
  was archived since the last delivery is brought back when a task arrives, as opening the
  chat and typing in it does.
  `stream: true` says the caller draws each `text` in place of the text since the last `tool`;
  nanoMuse Desktop then also sends `text {text, interim, partial: true}` with the text of the
  message the model is writing, at most every 250 ms, and the finished message as before. A
  caller that does not ask gets each message once (Android's `nanomuse-pc task` lists every
  `text` as a step); the runtime ignores `stream` for now.

  While a task runs the target sends `event` frames whose `body.stage` tells
  the caller what to draw, so the run reads the same in the caller's chat as in
  the target's own: `tool {id, name, summary}` when a tool starts and
  `tool_result {id, name, ok, summary}` when it ends (same `id`), `approval
  {approval_id, preview, risk, reason, device, timeout, grant_key}` and, once decided on
  either side, `approval_result {approval_id, status}`, `text {text, interim}`
  for what the Muse says along the way, `image` and `file` for things it made,
  `error`. The `result` frame carries the final answer. A caller draws a `text` in place of the
  text since the last `tool`, so a target may send the growing text of one message more than
  once and the caller shows it as it grows; a target that sends each message once is shown the same.
  `grant_key` (since 1.0.6) is what an answer remembered on the asking device covers:
  the runtime sends the key its own grants use (the tool and its target, `shell:git`),
  the desktop the tool and its whole main argument; a sender without it is remembered
  by the first 60 characters of `preview`, as before, which two different steps can share.

- **Coding agents.** `coding.agents`, `coding.sessions`, `coding.session`,
  `coding.send`, `coding.stop`, `coding.runs`: the Cursor / Codex / Claude Code
  sessions on a computer, read from disk and steered through the agents' own
  CLIs by the runtime or the desktop app there. `coding.send {agent, text,
  session_id?, workspace?, wait}` streams the run back as `event` frames
  (`started`, `text`, `tool`, `done`, `error`, each with the run id so the
  caller can `coding.stop`) and answers with the finished run. Only a computer
  announces these actions: a runtime that has the module, or the desktop app.
  [coding-agents.md](coding-agents.md).

Each device decides what it lets others do. On the phone, *Let other devices
operate this phone* (*Settings → nanoMuse Cloud → Devices*) off makes the phone
answer `info` and nothing else; it still sees and drives the others. The
runtime's `info` then names the computer and its system only (no account
name, home or working directory, no shell) and lists `info` as the one
action.
With it on, a raw action that does something *to* the device (`shell`, `files`,
`file.get`, `file.put`, `open`, `screen`, `coding.send`, `coding.stop`) is first
agreed to by the person at that device: the usual approval card, *once* or
*always for that device*; the standing answer is a grant
(`remote_control:<device id>`) under Permissions. nanoMuse Desktop asks with the
same card by default; its *Remote control without asking* (*Settings → Devices*)
lets every device of the account run things there without the card. Nobody there, and the caller
hears `not_allowed` when the card expires. `info` and `notify` never ask; a
`task` runs under the device's own Sentinel, whose cards travel back to the
caller as before. A device may `approve` only cards of its own runs that were
sent to it, never the card asking whether it may run something; the one exception is a
computer's own card marked `any_device` ([below](#a-computer-s-own-cards-on-the-phone)), which
any device of the account may answer.

### A computer's own cards on the phone

A scheduled task on nanoMuse Desktop runs while nobody may be at the computer, so the cards of
its run also go to the account's phones. No call stands behind such a card, so it travels as a
push (relay 0.31, [below](#frames)); the computer sends it only when `welcome.server.features`
lists `event_push`, and the relay passes it only to devices whose `hello` announces
`approve.any` (the Android app and the iPhone app). That is the whole of it: a card of a
chat somebody is typing in on the computer or in the web console stays where it was asked (a
person is there), a card inside a task another device sent goes back to that device inside the
call ([above](#what-you-can-say)), and the Python runtime (`nanomuse serve`) pushes nothing yet — its
scheduled tasks' cards wait in the web app
([#704](https://github.com/nano-muse/nanoMuse/issues/704)):

```
→ event {to:"*", body:{stage:"approval", approval_id, preview, preview_zh, reason, app,
                      task:{id, title}, chat, scopes:["once", "schedule"?], timeout, device,
                      any_device:true}}
← call  {action:"approve", args:{approval_id, allow, scope?:"once" | "schedule"}}   (to the computer)
→ event {to:"*", body:{stage:"approval_result", approval_id, status, by?:{id, name}}}
```

`preview` and `preview_zh` say what the step does in English and in Chinese (the phone picks
by its language), `app` is the app the hands would act in, `task` and `chat` name the task and
the chat it lives in, `device` the computer, `timeout` is how many seconds the phone shows the
card (600). `scopes` lists what the card may offer besides *Deny*: `schedule` (*Always in this
task*) only for a hands step in a run of one task; that grant is kept on the computer, never on
the phone. `any_device` says any device of the account may answer: the computer takes `approve`
for this card from whichever device sends it first, where every other card is answered only by
the device that started the run. The first answer, on the computer or on any phone, decides;
the computer then pushes `approval_result` with `status` (`approved`, `denied`, or `cancelled`
when the run let the card go) and `by`, the device that answered, and the phones drop the card.
A phone where nobody answers in time only drops its own card and sends nothing, so the card on
the computer keeps waiting. A card that hits a payment word goes too: only phones announce
`approve.any`, and a phone answers behind its screen lock. Nothing runs on the phone, so the
card is shown with *Let other devices operate this phone* off as well. In the background
Android shows the card as a notification; iOS posts a notification while its hub connection is
still open.

### Proposed `proxy_fetch`: the phone uses the computer's connection

Not built yet; written down here so the three implementations agree before
anyone starts. The case: the phone's network does not reach `chatgpt.com` or a
provider's host (the card in [own-key.md](own-key.md#when-the-provider-cannot-be-reached)),
the person's computer does. The computer's runtime would relay the provider
call (only that) the way a proxy would, over the hub.

```
→ call   {id, to, action:"proxy_fetch",
          args:{method, url, headers:{…}, body?, stream?}}     body base64; stream: want SSE chunks as events
← event  {id, from, body:{stage:"headers", status, headers:{…}}}
← event  {id, from, body:{stage:"chunk", data}}                data base64; one per SSE chunk when stream is true
← result {id, ok:true, body:{status, headers:{…}, data?}}      data base64 when stream was false
← result {id, ok:false, error:"not_allowed" | "host_refused" | "too_large" | "upstream", message}
```

The rules that make it acceptable, each one a line of code on the serving
side:

- **Opt-in on the computer.** The desktop plugin announces `proxy_fetch` in its
  `hello` only while *Let my phone use this computer's connection for
  providers* is on (*Settings → Devices*); off, the action is `unknown_call`.
  Same trust as `device_shell`: the device's *Remote control* must be on, and
  the first call from a device raises the usual card, *once* or *always for
  this device* (a `remote_control:<device id>` grant).
- **Hosts, not the open internet.** The computer forwards only to hosts of the
  provider catalogue (`providers.json`), `chatgpt.com` and `auth.openai.com`,
  and to the custom base URLs of its own configured providers; anything else
  is `host_refused`. Never the relay, never a LAN address, never `file:`.
- **Headers pass, secrets do not stay.** The phone sends its own
  `Authorization` (the plan's token, its own key); the computer forwards it and
  logs the host, the status and the size, never a header or a body.
- **Bounded.** Request bodies over 8 MB and responses over `HUB_FRAME_LIMIT`
  per frame are `too_large`; a stream is cut at ten minutes; one call at a time
  per asking device.
- **The phone chooses.** The reach card offers *Use my computer's connection*
  only when a computer that announces `proxy_fetch` is online; the choice is
  kept per provider instance and shows on the instance as a line, so nobody
  forgets that their key travels through the computer.

Why it is a design and not code in this change: the hub frame itself is small,
but the serving side is a new trust surface on the computer (a forwarder that
carries the person's provider tokens) and the phone's two HTTP stacks would
each need a transport that turns a request into frames and frames back into a
response: three implementations and a fourth place that must agree on the
host list, which this round's budget did not cover honestly. The proxy setting
([own-key.md](own-key.md#when-the-provider-cannot-be-reached)) covers the
common case meanwhile: a proxy on the computer (Clash, a `ssh -D`) with the
phone pointed at it.

## Frames

JSON text frames over `WS /v1/hub`, `Authorization: Bearer nm_…` (browsers put
the key in `hello` instead).

```
→ hello    {device:{id,name,kind,os,version,actions[],llm?}}   kind: phone | computer | web
           llm (relay 0.28, optional): {provider, model}, the ids the device runs its model under ("cloud",
           "openrouter", a model id); plain ids only, never a key or a URL; kept on the device row for the operator
← welcome  {device_id, devices:[…], server:{version,frame_limit,time,features?}}   features (relay 0.31): ["event_push"]
← devices  {devices:[{id,name,kind,os,version,actions[],online,last_seen,controllable,ip}]}

→ call     {id, to, action, args}
← call     {id, from:{id,name,kind}, action, args}          (delivered to the target)
→ event    {id, body}          ← event  {id, from, body}    progress, approvals, images
→ event    {to, body}          ← event  {from, body}        no id: a push to a device or "*" (relay 0.31, below)
→ result   {id, ok, body | error, message}                  ← result (to the caller)
← error    {code, message, id?}   device_offline · not_controllable · self_call · duplicate_call · unknown_call · timeout
                                  too_large · rate_limited · bad_frame · device_online · bad_key · bad_device

→ devices  {}        → rename {name}        → forget {device_id}        → ping  ← pong
← profile  {rev, device}       the account's name, look or connectors changed (PUT /v1/me/profile); fetch it
← sync     {what:"conversations", cursor, from}   another device pushed or deleted synced conversations; pull /v1/sync/changes
← working  {cid, from, device_name, working, at, state?, detail?}  another device started (true) or finished (false) a turn in that synced conversation; on a true, since relay 0.31, what it is doing (`state`: working | waiting; `detail`: the step, up to 160 characters)
```

Close codes: `4000` hello expected (no hello within 15 s, or a frame that is
not a hello first; a binary frame counts), `4001` bad key (reason `bad_key`
or `account_deleted`; `account_gone` when the account was deleted or disabled
under a live socket; from relay 0.25.0 also `bad_key`
under a live socket whose key was just revoked, by *Sign out everywhere*
from another device, a
session revoked on the account page or the device's own sign-out, so a lost
phone loses its line at once and the other devices see it offline), `4002`
bad device, `4003` replaced
by a newer connection of the same device id, or, with the reason
`hub_paused` (relay 0.22), the operator switched the hub or the whole service
off: a client waits and reconnects later instead of retrying at once
([cloud.md › Controls](cloud.md#controls)); `4008` too many frames (the
rate limit below was ignored) or, with the reason `too_many_connections`
(relay 0.30), too many sockets: one address opened more than 60 in a minute,
or the account already has 32 devices connected (a device taking its own
place again is not counted); and `4009` slow consumer (the relay had 512
frames or 32 MB queued for a socket that was not reading them; the client
reconnects with backoff like after any network close).

A key refused in the `Authorization` header is answered the same way as one
refused in `hello`: the handshake completes, an `error` frame carries the
code, then the close with `4001`. A client that sees `4001` or `4002` leaves
the backoff, shows the hub as refused and asks the person to sign in again (the
runtime still tries once a minute, so a key restored on the relay comes back
without a restart); any other close is the network and is retried with
backoff. A socket that stays open after the network went away (a laptop that
slept, a Wi-Fi that changed) hears no `pong`: the runtime's client uses the
protocol's own ping with a 20 s timeout, the desktop's drops the socket when
nothing at all arrived between two of its `ping` frames (about 50 s) and
reconnects the same way.

Since relay 0.31 an `event` may also be sent without an `id`: a push, not
progress on a call. A computer uses it for its own approval cards, which no
call stands behind, and for the word that one was answered. `to` is one
device id or `"*"`, every device of the account; either way the relay passes
the frame only to devices whose `hello` announced `approve.any`, never back to
the sender, so the sender keeps no list and an older app never sees one. Only
the stages `approval` and `approval_result` pass; any other is dropped and
logged. One device may push 30 a minute (over that, `rate_limited`), each
`body` 16 KB at most (over that, `too_large`). A relay that has this lists
`event_push` in `welcome.server.features`; a client sends a push only when it
sees that, so an older relay hears none.

Frames the relay does not know (`type` it has no handler for, a text frame
that is not a JSON object, a binary frame) are answered with
`error bad_frame` and the socket stays open, so a newer client talking to an
older relay loses one frame, not the connection. Frames over `frame_limit`
get `too_large`; more than 60 frames or 8 MB a second get `rate_limited`
(one warning a second, the extra frames dropped) and, if that goes on,
the close with `4008`. A send to a device never waits on that device: frames
queue per connection and are written in order as the socket drains; a socket
that stops reading is closed with `4009` once 512 frames or 32 MB are waiting,
so one stalled phone cannot hold the computer calling it. A `call` nobody
answers within 15 minutes fails with `timeout` to its caller (the relay checks
when a call or a `ping` arrives, so a caller that pings hears it within a
minute of the deadline); `forget` of a device that is connected right now is
refused with `device_online`.

Device ids are per installation (`phone-…`, `pc-…`); names are for people and
can be changed on the device. A `web` device is never a target and is not
remembered. Bodies for `file.get`, `file.put` and `screen` carry the bytes in
base64 (`data`) with `mime`; the desktop refuses files over 8 MB, the relay
refuses frames over `HUB_FRAME_LIMIT`.

The Python runtime's `files` action returns at most 2,000 directory entries. When more
readable entries exist, the result also includes `truncated: true` and `total`, the number
of names observed in the directory before per-entry reads. An entry that disappears or
cannot be read may be omitted. An exactly full listing is not marked truncated. These
fields are optional additions; clients must also accept responses without them.

From relay 0.27, a credential owns one Hub identity: its `device.id` and
`device.kind` are fixed when the credential is issued with `device_id` and
`device_kind` (`POST /v1/auth/verify` and `/login`), or else at the first
accepted `hello` of a credential that was issued without them. The same
credential may reconnect and replace its own older socket, but `bad_device`
rejects another id or kind. An id a live key holds is taken over only by a key
from a later code or password sign-in (the phone signed in again without
signing out, the runtime's vault was reset, a sign-out that never reached the
relay): the older key still opens the account but no longer speaks for the
device. A revoked or lapsed key releases its id. A session key
(`/v1/auth/session-key`, nanoMuse Web's containers) registers an id nobody
holds and never takes one over. Existing clients keep their keys and register
at their next connection; clients that send the identity at sign-in bind it
there.

The agent's name and look are the account's, not a device's: `GET` / `PUT
/v1/me/profile` on the relay keep them (the dragon, an emoji on a colour, or a
face drawn in the avatar studio with its five small stills), last writer wins,
and a `profile` frame tells the other devices to fetch the new `rev`. The
runtime does this in `nanomuse/hub/profile.py`, the phone in
`io.github.nanomuse.cloud.ProfileSync`; the device that wrote it skips its own
echo.

The same profile carries **which device connected what** (0.1.34): a
`connectors` list with, per entry, the connector's id and label, its address
when it has one, how it signs in (`oauth`, `key` or `open`), the device's name
and id, whether it is enabled, and when. A device writes only the entries it
holds; the relay keeps the other devices' entries, caps the list at 64 and
refuses any entry that carries a token, secret, key, authorization or password
field; credentials never leave the device that signed in. The other devices
list those entries under the connectors catalogue as *Connected on \<device\>;
sign in here to use it on this device*, and the usual local sign-in is the
action.

Since relay 0.29 the profile can also name the drawn face's **clips**: the
device that animated the face puts each clip up as a file (`PUT
/v1/blobs/{sha256}`, [cloud.md](cloud.md#the-record)) and writes `clips:
{mood: {sha256, mime, bytes}}`; the other devices, told by the same `profile`
frame, download the clips from `GET /v1/blobs/{sha256}` instead of rendering
their own. The clips go with the face: `clips: null`, another avatar or
`DELETE /v1/me/profile` clears them. The apps of 1.0.6 and earlier ignore the
field.

Since 0.1.36 the **conversations** travel too, by a different road: their text
goes to the relay's sync store over REST (`/v1/sync/*`, [cloud.md](cloud.md#conversation-sync)),
and the hub only carries the nudge. After a push that the relay accepted, or a
deletion, every *other* socket of the account gets `sync {what:"conversations",
cursor, from}` (`cursor` is the account's counter after the change, `from` the
device id that made it) and pulls what is new from its own cursor. A device that
sees its own id in `from` ignores the frame. Since 0.1.38 (relay 0.20) the hub
also carries **who is answering**: a device that starts or ends a turn in a
synced conversation posts `/v1/sync/working`, and the other sockets get
`working {cid, from, device_name, working, at}`; the apps show *kwai is
working…* under the last message until `working: false` arrives, the reply
itself lands, or ten minutes pass. Since relay 0.31 a `working: true` also says
what the run is doing: `state` is `working` or `waiting` (the run is parked on a
card for the person), and `detail` is the step's own words, at most 160
characters, so the line reads *kwai is working: opening the booking site* or
*kwai is waiting for you*. A device that posts without the two fields is shown
as plain working; a client that does not know them ignores them. The relay
keeps these in memory only. By
default only the main conversation is synced; side chats travel only from and to
devices that turned *Also sync side chats* on. Nothing else is synchronised:
keys, providers and settings stay where they were entered, and files and images
stay on the device that made them. How the apps use it is in
[every-device.md](every-device.md#the-same-conversations-everywhere).

## The code

How the devices' apps are shaped around these frames (the Devices page, a
side chat addressed to a device, approvals answered on either end, the
computer's own hands) is in [every-device.md](every-device.md).

- Relay: [`cloud/nanomuse_cloud/hub.py`](../cloud/nanomuse_cloud/hub.py):
  per-account registry, routing, `GET /v1/devices`, `DELETE /v1/devices/{id}`;
  the console under [`cloud/nanomuse_cloud/console/`](../cloud/nanomuse_cloud/console/).
- Android: `io.github.nanomuse.hub`: `HubClient` (OkHttp, reconnect),
  `Hub` (state, prefs, `call`/`find`), `HubActions` (what the phone does for
  others, including `task` through the headless chat runner, its `language`
  honoured), `HubService`
  (foreground, `remoteMessaging`). `nanomuse-pc` (`io.github.nanomuse.reach`)
  reaches the hub devices from the phone's sandbox shell.
- nanoMuse Desktop: [`harness/dsh-nanomuse/src/hub.ts`](../harness/dsh-nanomuse/src/hub.ts)
  (the socket, reconnect), [`harness/dsh-nanomuse/src/actions.ts`](../harness/dsh-nanomuse/src/actions.ts)
  (what this computer does for others, the card before a remote action); see [desktop.md](desktop.md).
- iOS: [`NanoMuse/NanoMuseHub.swift`](../android/src/ios/NanoMuse/NanoMuseHub.swift):
  `info`, `open`, `notify`, `task` (its `language` is honoured), `stop`; `screen` is
  refused (`no_screen`), the shell and files actions with `not_supported`. A step of a
  `task` that needs approval is not sent back as an `event`: with nanoMuse in front the
  phone shows its own card, in the background the step is declined and the answer says so.
  The other way round, a `task` the phone sends (`@〈device〉`,
  [`NanoMuseDeviceMention.swift`](../android/src/ios/NanoMuse/NanoMuseDeviceMention.swift))
  has its `approval` events answered on the phone's card
  ([`NanoMuseRemoteApproval.swift`](../android/src/ios/NanoMuse/NanoMuseRemoteApproval.swift))
  and `approve` sent back; `approval_result` closes the card. A computer's pushed card
  ([above](#a-computer-s-own-cards-on-the-phone)) lands on the same card with *Allow once*,
  *Always in this task* and *Deny*. The reply is drawn while that
  device works ([`NanoMuseDeviceReply.swift`](../android/src/ios/NanoMuse/NanoMuseDeviceReply.swift)):
  `tool`/`tool_result` as step capsules, `text` as it comes; the chat's stop sends `stop {call}`.
- Runtime (`nanomuse serve`): [`nanomuse/cloud.py`](../nanomuse/cloud.py)
  (the account), [`nanomuse/hub/client.py`](../nanomuse/hub/client.py) (the
  socket, reconnect), [`nanomuse/hub/actions.py`](../nanomuse/hub/actions.py)
  (what this computer does for others), [`nanomuse/hub/service.py`](../nanomuse/hub/service.py)
  (incoming `task`s in a visible side chat, the `tool`/`tool_result`/`approval`/
  `approval_result` stages both ways, device threads), [`nanomuse/tools/devices.py`](../nanomuse/tools/devices.py)
  (`devices`, `device_*`, `delegate`); `/api/cloud/*` and `/api/hub/*` in
  [`nanomuse/server/api.py`](../nanomuse/server/api.py). Tests:
  `tests/test_hub.py` with a fake relay.
- Web app: `DevicesScreen`, the device chats and the relayed approval cards in
  [`web/src/`](../web/src/); see [every-device.md](every-device.md).

## Trust

The relay authenticates every socket with a credential bound to its device id
and kind, and routes only within the account; it stores device names and
last-seen times, not what was asked. A device answers only devices of its own account, and only while its
*Remote control* switch is on, and, for anything that runs, reads or writes
there, after the person at that device agreed (once, or always for the asking
device). Commands are judged where they are typed, before they leave; a remote
Muse's approvals are answered by the person who asked, never by the other Muse. Signing out on a device revokes that device's key at
the relay and takes it off the hub; the *Devices* list on the phone and the
console shows every device that has ever signed in, so a device you no longer
recognise is visible, and *Forget* removes it once it is offline.
