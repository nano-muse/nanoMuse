# nanoMuse Cloud

A small relay that lets someone use nanoMuse without owning an API key. Sign up
with a phone number or an e-mail address, get a starter allowance of tokens, and
the app talks to this server the way it would talk to any OpenAI-compatible
provider. Your own key still works exactly as before — this is the "start now"
path, not a replacement for bring-your-own-key.

It is a single Python process over SQLite. Anyone can run one: the app only needs
its base URL.

## What it does

- **Sign-up by code.** `POST /v1/auth/code` sends a six-digit code to a phone
  (Aliyun SMS) or an e-mail (SMTP). `POST /v1/auth/verify` exchanges it for an
  `nm_…` API key. One phone/e-mail is one account with one starter grant; a
  second device signing in with the same number gets a second key, not a second
  grant. `POST /v1/auth/session-key` (0.13) turns a key into one that lapses on
  its own (`ttl_s`, 90 days at most) — what nanoMuse Web starts a person's
  container with, so the gateway keeps no standing key of theirs; it shows in
  `/v1/me/sessions` with `expires_at` and `via: "session"`.
- **OpenAI-shaped proxy.** `GET /v1/models`, `POST /v1/chat/completions`
  (streaming or not) go to the upstream with the relay's key. `POST
  /v1/images/generations` and `/v1/images/edits` are translated into DashScope's
  native image API, so drawing and re-drawing the avatar works through the
  relay too.
- **Ledger.** Every request is charged from the account's grant using the
  upstream's own `usage` (for streams, from the final usage chunk). Cheaper
  models are charged with a multiplier; pictures cost a flat amount. One
  lifetime allowance per account and a per-minute limit bound the damage of a
  leaked key.
- **Privacy by construction.** Phone numbers and e-mail addresses are looked
  up by HMAC-SHA256 hash, shown as a display hint (`138****8000`,
  `so***@example.com`), and kept AES-GCM-encrypted under a key derived from
  `CLOUD_SECRET` so the operator's page can tell accounts apart; the database
  file on its own reveals none of them. Message content is forwarded, never
  written to disk. The database holds: hashed and encrypted identifier, key
  hashes, the keyed hash of a code still waiting to be used (six digits, so
  hashing it plainly would be a table an attacker could work through), video
  task ids, token counts per request, and the profile below.
- **One look on every device.** `GET` / `PUT` / `DELETE /v1/me/profile` keep
  the agent's name and face for the account — the dragon, an emoji on a colour,
  or a face drawn in the avatar studio with its five small stills (WebP, 200 KB
  each at most) — last writer wins, with a `rev` that grows on every write.
  Devices on the hub hear `{"type": "profile", "rev", "device"}` and fetch it;
  `?face=false` leaves the pictures out. Never a key or a message.
- **Which device connected what (0.17).** The same profile carries
  `connectors`: one entry per service a device connected — `id`, `label`,
  `url`, `auth` (`oauth` / `key` / `open`), `device`, `device_id`, `enabled`,
  `at` — so another device can say "connected on your Mac; sign in here to use
  it here". A device's `PUT` replaces only its own entries (those whose
  `device_id` is the writer's `device`) and leaves the other devices' as they
  were; `[]` clears its own; a write that carries only `connectors` leaves the
  name and look alone. At most 64 on an account (`400 too_many_connectors`).
  The credential never comes along: an entry with a key named like one
  (`token`, `secret`, `key`, `authorization`, `password`, at any depth) is
  refused with `400 no_secrets_in_profile` and nothing is stored.

Errors carry a stable `code` the app can turn into a sentence:

| status | code | meaning |
|---|---|---|
| 400 | `bad_identifier` | not a phone number or e-mail address |
| 400 | `phone_region` | a number the SMS sender cannot reach (号码认证 sends to mainland China only); e-mail works everywhere |
| 400 | `code_wrong` / `code_expired` | verification code |
| 400 | `channel_unsupported` | this relay's `CODE_SENDER` does not send codes that way (SMS or e-mail); the sentence says which |
| 502 | `send_failed` | the SMS or mail provider refused or did not answer; the code was not sent |
| 400 | `bad_credentials` / `no_password` / `password_short` / `password_long` / `password_weak` / `password_wrong` / `password_required` | the password sign-in and the password form (`bad_credentials` is 401; `locked` is 429 after too many wrong passwords) |
| 404 | `no_session` | the sign-in to revoke no longer exists |
| 409 | `device_online` | `DELETE /v1/devices/{id}` (or the hub's `forget`) for a device that is connected right now; sign out on it first |
| 409 | `sync_off` | a `/v1/sync/*` call while the person has conversation sync turned off |
| 413 | `too_large` | the body is over `MAX_REQUEST_BYTES`, or a profile over its limit; `too_many_conversations` / `too_many_messages` are the sync push's own 413s |
| 400 | `bad_request` | the body did not parse or a field is wrong; the message says which |
| 400 | `client_disconnected` | the app went away while its request body was still arriving; nothing reached the provider |
| 404 | `no_task` | an image or video job id the relay does not know (or not this account's) |
| 401 | `bad_key` | unknown or revoked key — the phone keeps the account's data aside for the next sign-in |
| 401 | `account_deleted` | the key's account was deleted (0.1.40; remembered for 90 days) — the phone may delete the account's data |
| 402 | `out_of_tokens` | grant used up — top up with the admin endpoint |
| 403 | `account_disabled` | |
| 403 | `session_from_session` | `POST /v1/auth/session-key` was called with a session key; only a device's standing key may mint one, so a leaked short-lived key cannot renew itself |
| 404 | `model_not_offered` | not on the menu |
| 400 | `no_secrets_in_profile` | a profile `connectors` entry carried a key named like a credential; nothing was stored |
| 400 | `too_many_connectors` | the write would leave more than 64 connectors on the account |
| 429 | `allowance_exhausted` | the account's pool is spent; the body also carries `left`, `grant`, `region`, `ways` (the ways on in order for that person), `guidance` (0.21: every provider for the region with what each covers, the plans an app can sign in with), `invite_url`, `invite_bonus_cny`, `own_key_docs`, `openrouter_url` |
| 429 | `code_too_often` / `rate_limited` / `daily_cap` | (`daily_cap` only with the legacy token cap on) |
| 429 | `too_many_in_flight` | `MAX_IN_FLIGHT` requests of the account are already under way; `retry_after` in the body |
| 429 | `provider_busy` | the image provider answered 429 even after the relay queued and retried (`IMAGE_CONCURRENCY`, `IMAGE_RETRIES`); `retry_after` seconds in the body |
| 400 | `content_rejected` | the provider's content check declined the words (a chat request or an image prompt); the provider's own line rides along under `upstream` |
| 400 | `upstream_400` | any other refusal of the request itself; the provider's message passed through |
| 502 | `upstream` / `upstream_auth` / `upstream_model` / `upstream_busy` / `upstream_<status>` | the provider failed; a plain sentence, the provider's line under `upstream` |
| 503 | `upstream_unconfigured` | `UPSTREAM_KEY` missing |
| 403 | `signup_closed` | the operator closed sign-ups (0.22, *Controls*); an identifier without an account gets this before any code is sent, existing accounts sign in as before |
| 429 | `allowance_exhausted` + `paused: true`, `reason: "allowance_paused"` | the *Free allowance* switch is off (0.22): the same body as a spent pool, with a message that says paused rather than spent; members are unaffected |
| 503 | `service_paused` | the *Cloud service* switch is off (0.22): every call but `/healthz`, `/v1/config`, `/app` and `/v1/admin/*`; `paused: true` in the body |
| 503 | `sync_paused` | the *Conversation sync* switch is off (0.22): `/v1/sync/*` except `GET /v1/sync/state`, which answers with `paused: true` |
| 503 | `hub_paused` | the *Device hub* switch is off (0.22): `GET /v1/devices`; the hub socket itself closes with `4003 hub_paused` |

## Run it

Development, no external services — codes are printed to the log:

```bash
cd cloud
pip install -e ".[dev]"
UPSTREAM_KEY=sk-… python -m nanomuse_cloud --port 8787
# in another shell
curl -X POST localhost:8787/v1/auth/code -H 'Content-Type: application/json' -d '{"identifier":"13800138000"}'
# read the code from the server log, then
curl -X POST localhost:8787/v1/auth/verify -H 'Content-Type: application/json' -d '{"identifier":"13800138000","code":"123456","device":"curl"}'
```

Production, on any VPS with Docker — `scripts/self-host.sh` at the repository root asks the five questions, writes `.env` and runs this; [docs/self-hosting.md](../docs/self-hosting.md) is the guide, including how to point each app at your relay:

```bash
cp .env.example .env      # fill in CLOUD_DOMAIN, PUBLIC_BASE, CLOUD_SECRET, CLOUD_ADMIN_TOKEN, UPSTREAM_KEY, sender settings
docker compose up -d      # Caddy fetches the TLS certificate for CLOUD_DOMAIN
curl https://$CLOUD_DOMAIN/healthz
```

Without TLS, for this machine or a LAN — the relay alone on `127.0.0.1:8787`, codes in the log:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
RELAY_BIND=0.0.0.0 docker compose -f docker-compose.yml -f docker-compose.local.yml up -d   # reachable from the LAN
```

Back up `data/cloud.db` together with `CLOUD_SECRET`: the hashes are useless
without the secret, and the secret alone is useless without the database.

The visitor's address — what the per-address limits on codes and sign-ins key on,
and what the operator's page shows — is the first hop of `X-Forwarded-For` when
the request came through a proxy on the same box or network (Caddy, a tailnet:
every loopback, private, link-local or shared address, or the list in
`TRUSTED_PROXIES`), else the socket's peer. A relay reached directly from the
internet ignores the header, so a request cannot name its own address.

Point the app at it: in nanoMuse, *Sign in — free* → enter a phone number or an e-mail → code.
The app stores the key in its encrypted preferences and sets up a provider
with `PUBLIC_BASE` as its base URL. Nothing else in the app changes; you can
add your own key next to it at any time.

## Settings

All configuration is environment variables; see [`.env.example`](.env.example)
for the full list. The ones that matter:

| variable | default | |
|---|---|---|
| `UPSTREAM_BASE` / `UPSTREAM_KEY` | Model Studio compatible-mode | where chat goes |
| `DASHSCOPE_BASE` | Model Studio native | where pictures go (same key) |
| `IMAGE_CONCURRENCY` / `IMAGE_RETRIES` | 2 / 4 | pictures drawn at once for everyone together (the provider allows an account only a couple), and how often a 429 or 5xx is retried with growing pauses before `429 provider_busy` |
| `CHAT_DEFAULTS` | `{"enable_thinking": false}` | merged into chat requests for fields the app did not set |
| `SIGNUP_OPEN` | `1` | anyone may sign in; `0` = members only (a private relay). *Runtime setting* — see below |
| `ALLOWED_IDENTIFIERS` | empty | comma-separated numbers / addresses of the **members**: no spend limit |
| `REVIEW_ADDRESSES`, `REVIEW_CODE` | empty (off) | an app store reviewer's sign-in: for these e-mail addresses no code is sent and the six-digit `REVIEW_CODE` signs in — see *For App Store review* below |
| `ALLOWANCE_CNY` | 10 | yuan per non-member account **for its lifetime**, at the list prices below; 0 = no limit. *Runtime setting* |
| `INVITE_BONUS_CNY` | 5 | added to **both** pools — the inviter's and the newcomer's — per new person who signs up with the code. *Runtime setting* |
| `REPO_URL` | `https://github.com/nano-muse/nanoMuse` | the repository the apps ask people to star, in `/v1/config` |
| `IMPROVE_DEFAULT` | `0` | what *Help improve nanoMuse's AI models* (Data controls) starts as for accounts created from now on: `1` = on until the person turns it off, `0` = off until they turn it on; existing accounts keep their setting. State it in your privacy policy |
| `PRIVACY_URL` | `https://nanomuse.cn/privacy/` | the policy the apps link from Data controls and the sign-in pages — the one that says what this relay keeps and its default |
| `INVITE_URL` | `https://nanomuse.cn/web/?invite=` | the link the apps offer to share; the code is appended |
| `OWN_KEY_DOCS` | `https://nanomuse.cn/own-key` | the guide the apps open for bringing one's own key or signing in with a plan (every provider by region, what each covers) |
| `OPENROUTER_URL` | `https://openrouter.ai/keys` | the page for a key from OpenRouter, the way on for people outside mainland China (0.17) — the apps order the two by the person's `region` |
| `DAY_OFFSET_H` | 8 | the operator's reports group by local day, midnight UTC+8 (Beijing) |
| `TRAFFIC_DB` | empty | the site's daily traffic counts (`demo/showcase/mirror/traffic.py`), mounted read-only, for the operator's page; empty = that panel says it is not connected |
| `WEB_INFO_URL` | empty | nanoMuse Web's gateway (`http://gateway:8000/api/web/info` on the same docker network) for its account and session counts on the operator's page |
| `WEB_ADMIN_URL`, `WEB_ADMIN_TOKEN` | empty | the showcase gateway's `/api/demo/admin` and its `SHOWCASE_ADMIN_TOKEN`: who tried the phone in the browser from where and with what, every demo and what it used — a panel on the operator's page and a section in the account drawer (relay 0.10) |
| `USD_CNY` | 7.1 | for showing dollars next to yuan; display only |
| `SIGNUP_TOKENS` | 0 (no ceiling) | starter token grant per account, the older allowance |
| `DAILY_CAP_TOKENS` | 0 (off) | tokens per account per day |
| `PER_MINUTE_REQUESTS` | 30 | per account — what stops a runaway loop |
| `MAX_IN_FLIGHT` | 4 | requests of one account under way at the same time (0 = off); each holds a reservation against the allowance while it runs — see *Money* |
| `PASSWORD_MAX_ATTEMPTS`, `LOCKOUT_S` | 5, 900 | wrong passwords before an account is locked for that long (a code still works) |
| `LOGIN_FAIL_PER_IP_HOUR` | 30 | wrong passwords from one network address per hour across all accounts — a list of numbers tried once each never trips the per-account lock, this does (0.12); 0 = off |
| `CODE_SENDER` | `log` | `log`, `smtp`, `aliyun` or `both` (SMS for phones, mail for addresses) |
| `ALIYUN_SMS_API` | `dypns` | `dypns` (号码认证服务 `SendSmsVerifyCode`) or `dysms` (短信服务 `SendSms`) |
| `CLOUD_MODELS` | DeepSeek + Qwen chat, Qwen image, Wan video | JSON list to replace the menu, prices and lanes (`for`, `recommended_for`) included — see below |
| `CLOUD_ANY_MODEL_MEMBERS` | `1` | members may name any model of the provider's for its kind (chat, image, video) — see below; `0` = the menu only |
| `CLOUD_CATALOG` | `1` | list the usable models under the operator's key after the menu in a member's `/v1/models`, read from the provider's own `/models` (0.10) — see below; `0` = the menu only, a member types an id |
| `CLOUD_CATALOG_TTL_S` | `3600` | how long that list is kept before the provider is asked again |
| `CLOUD_CATALOG_PROBE` | `1` | ask each chat model on that list, once, whether it answers and whether it reads a picture (0.11) — see below; `0` = go by the names |
| `CLOUD_CATALOG_PROBE_TTL_S` | 7 days | how long a model's answers stand before it is asked again |
| `CLOUD_GEOIP` | `1` | name where an address is on the operator's page — country, province, city — from ip2region's offline database, fetched once into the data directory (0.11); `0` = addresses only |
| `CLOUD_GEOIP_DB`, `CLOUD_GEOIP_URL`, `CLOUD_GEOIP_V6_URL` | next to the database; the project's `ip2region_v4.xdb`; empty | the file, where to fetch it, and the IPv6 file (37 MB) for a relay reached over IPv6 |
| `HUB_ENABLED` | `true` | the devices hub at `/v1/hub` and the web console at `/app` ([docs/hub.md](../docs/hub.md)) |
| `HUB_FRAME_LIMIT` | 16 MB | largest hub frame (files and screenshots travel inside frames); one socket may also send at most 60 frames and 8 MB a second sustained (twice that in a burst) — over it frames are dropped with one `rate_limited` error a second, and a socket that keeps flooding is closed with 4008 (0.13) |
| `MAX_REQUEST_BYTES` | 16 MB (0.20; was 6) | largest REST request body — a chat request with a few screenshots, a sync push of 200 messages; over it the answer is 413 `too_large`, *Request body is N MB; this relay accepts up to M MB*. A declared `Content-Length` over the limit is refused before a byte is read, and a body that grows past it is refused as it arrives, so the relay never buffers more than the limit for one request. Both Caddy sites (`cloud/Caddyfile`, `deploy/nanomuse-hk/cloud.nanomuse.cn.caddy`) cap bodies at `request_body max_size 20MB`: just above 16 MiB plus multipart overhead for `/v1/images/edits`, so a legitimate payload always reaches the relay's own 413 message and nothing larger reaches the relay at all; raise both together if you raise this |
| `GITHUB_REPO` | read off `REPO_URL` (`nano-muse/nanoMuse`) | the repository whose stars, forks, watchers, open issues and release downloads the relay reads (0.22, *Site* on the operator's page) — `owner/name` |
| `GITHUB_TOKEN` | empty | optional; without one GitHub allows 60 requests an hour, the collector uses two every six hours. Set it only if the relay shares its address with something else that polls GitHub (a `403` from GitHub shows on the page and says so) |
| `GITHUB_COLLECT` | `1` | `0` turns the collector off (a relay without a way out, tests) |
| `GITHUB_API` | `https://api.github.com` | where the collector reads; a mirror for a relay that cannot reach GitHub |
| `ADMIN_EMAIL` | empty | where a threshold rule's *notify* goes (0.22, *Controls*), through the `SMTP_*` settings; empty = the rule writes its audit line and the log says there was nobody to tell |

The default menu (0.17): `deepseek-v4.1-flash` (the chat model — text and
images in, ¥2 / ¥8 per million tokens, charged at 0.7×; it thinks before it
answers and returns `reasoning_content`), `qwen3.8-27b` (the hands model: the
GUI model that reads screenshots and drives a phone or a computer, usable for
chat too; ¥3 / ¥12), `qwen3.8-flash` (charged at 0.3×), `qwen-image-3.0` for
drawing (¥0.18 a picture, 30 000 tokens) and `wan2.2-i2v-flash` for short
clips (¥0.10 a second at 480P, five seconds, 200 000 tokens per clip;
`wan2.2-t2v-plus` when a clip starts from words). Until 0.4 the menu had
`qwen-image-3.0-pro` (¥0.25 / ¥0.5) and `MiniMax/MiniMax-H3` (¥0.5 a second):
a new face with its four clips cost about ¥9; it is about ¥3 now.

**Lanes (0.17).** Every chat model says what it is `for` — `chat`, `gui` or
both — and `recommended_for` names the lane(s) it is the default pick in; both
ride in each entry's `nanomuse` block of `/v1/models`, and the apps' two
pickers (the chat model, the hands model) filter on them and take the
recommended one of each lane as the default. Picture and clip models are for
neither (`"for": []`; their `kind` says what they do). On the shipped menu
`deepseek-v4.1-flash` is `for: ["chat"]`, recommended for chat;
`qwen3.8-27b` is `for: ["gui", "chat"]`, recommended for gui. In
`CLOUD_MODELS` the fields are `"for"` and `"recommended_for"` (lists of lane
names; `for` left out means `["chat"]`; a `recommended_for` needs
`"recommended": true`); the relay logs a line at start when a lane has no
recommended model or more than one. A thinking model's `enable_thinking` and
the `reasoning_content` an app sends back in the history go upstream as they
are, the reasoning in the reply (whole or as stream deltas) comes back
untouched, and reasoning tokens are counted as completion tokens whichever
way the provider reports them (`completion_tokens_details.reasoning_tokens`
inside the figure, or DashScope's `output_tokens_details` apart from it).

Any OpenAI-compatible upstream works for chat; the image and video
endpoints assume DashScope. Video is relayed under DashScope's own paths
(`/api/v1/services/aigc/video-generation/video-synthesis`, `/api/v1/tasks/{id}`,
`/api/v1/uploads`), so the app's video code only needs to point its host at
the relay; a task can be polled by the account that created it only, and the
relay polls on the account's behalf when the app does not (*Money*, below).

### Runtime settings (0.15)

Three of the values above — `ALLOWANCE_CNY`, `INVITE_BONUS_CNY` and
`SIGNUP_OPEN` — can be changed **while the relay runs**, from the operator's
page (*Settings › Runtime*) or `POST /v1/admin/settings` (`{"allowance_cny":
20}`; `null` or `""` puts a value back on its environment default). The
change is kept in the database (`settings` table), survives a restart, and
takes effect on the next request: a new sign-up gets the new allowance, the
next invitation adds the new bonus, and `/v1/config` — the public endpoint
the apps read for the figures they print ("¥20 of use to start", "+¥5 for
each of you") — says so at once, with a minute's cache. **Nobody has to
update an app or do anything**: the amounts are the relay's, the apps only
display them.

Raising the allowance does not by itself touch the accounts that exist: each
account remembers the allowance it was created under (`accounts.allowance_uy`,
seeded with the value of the day for accounts from before 0.15). The page
counts how many non-member accounts are below the current figure and
**Apply to existing accounts** (`POST /v1/admin/allowance/apply`) credits each
of them the difference as a ledger row (`from: allowance`), so a raise from
¥10 to ¥20 gives everyone who had ¥10 another ¥10 — and no one twice.
Lowering the figure only applies to accounts created from then on; the
allowance machinery never shrinks a pool. **Credit everyone** (`POST
/v1/admin/credit-all`, `{"cny": 5, "note": "..."}`, −¥100…¥100) is the one-off
present — or, negative, the one-off claw-back: every non-member, enabled
account gets the amount, once, as `from: operator`.

**Set a pool to any figure** (0.16). `POST /v1/admin/pool` with `{"account_id"
| "identifier", ...}` and exactly one of `left_cny` (what should be left right
now — the pool becomes what is spent plus that), `grant_cny` (the lifetime
total) or `delta_cny` (a difference, negative takes away), plus an optional
`note`; the pool never goes below zero, what is spent stays spent. `POST
/v1/admin/pool/batch` does the same for `account_ids: [...]` (the filtered list
on the People view — *Set the pool for these N*) or for `all: true` (every
limited account — *Set everyone's pool* under Settings › Runtime; members and
disabled accounts are left out). Each account gets a ledger row (`credit_uy`
signed, `set` the new total) and a `pool.set` line on its timeline, so the
person sees the adjustment on their account page.

`GET /v1/admin/settings` returns the values in force, the environment's,
which are overridden, and the count below the allowance; `GET /v1/config`
(no key) returns `version`, `signup_open`, `allowance_cny` / `allowance_usd`,
`invite_bonus_cny`, `invitee_bonus_cny`, `usd_cny`, `invite_url`,
`own_key_docs`, `privacy_url`, `repo_url` and `improve_default`.

### Controls (0.22)

Five switches the operator flips without a restart or a deploy, from the
*Controls* page of the console, the command line or `POST
/v1/admin/controls/{key}`: `free_allowance`, `signups`, `cloud_service`,
`sync`, `hub`. Each is on by default, kept in the `controls` table so a
restart keeps it, and applies to the next request. What each one refuses when
off is in the error table above and, from the app's side, in
[docs/cloud.md › Controls](../docs/cloud.md#controls); the console says the
same thing in the row and again in the confirmation before it flips. Turning
`cloud_service` or `hub` off closes every open hub socket (`4003 hub_paused`)
and the answer says how many. The switches that are off are listed under
`paused` in `/healthz`, `/v1/config`, `/v1/me` and `GET /v1/admin/settings`.

Every change is a row in `control_audit` — who (`X-Admin-Actor` from the
console's *Your name* field or the CLI's `--actor`, else `console` / `cli:<user>`
/ `rule:<id>`), when, which switch or rule, the new state and the note — and
a `control.switch` / `control.rule` line on the activity timeline.

**Thresholds** (`control_rules`): *when the account count reaches N, do one
action* — `close_signups`, `pause_allowance`, `pause_sync` or `notify`. Rules
are evaluated when an account is created and once a minute by a background
task; a rule fires once and remembers the count and time it fired at
(`last_fired_at`, `fired_accounts`); *re-arm* on the page (`PUT …/rules/{id}`
with `{"rearm": true}`) or a changed threshold lets it fire again; `enabled:
false` keeps the rule without evaluating it. Firing writes the audit line and
the timeline line; `notify` also sends an e-mail to `ADMIN_EMAIL` through the
`SMTP_*` settings — counts and the relay's own address only, nothing about any
person — and the audit says whether it went. *Send a test notice* on the page
(`POST /v1/admin/controls/notify-test`) checks the mail settings.

```
GET    /v1/admin/controls                       → {switches: {key: {enabled, updated_at, actor, note}}, rules, accounts_total, next_threshold, notify_configured, admin_email_set, audit}
POST   /v1/admin/controls/{key}                 {enabled, actor?, note?}  → the same, plus sockets_closed
GET    /v1/admin/controls/rules                 → {rules: [{id, threshold, action, enabled, note, created_at, last_fired_at, fired_accounts}]}
POST   /v1/admin/controls/rules                 {threshold, action, note?, enabled?}  → the rule
PUT    /v1/admin/controls/rules/{id}            {threshold?, action?, enabled?, note?, rearm?}  → the rule
DELETE /v1/admin/controls/rules/{id}            → 204
POST   /v1/admin/controls/evaluate              → {fired: [...], accounts_total}   check the rules now
POST   /v1/admin/controls/notify-test           → {sent, configured}
GET    /v1/admin/controls/audit?limit=200       → {audit: [{id, ts, actor, ip, action, target, detail}]}
```

### Star asks (0.18)

When the apps may ask for a star on GitHub used to be written into each app.
Now it is the relay's: `GET /v1/nudges` (no key, `Cache-Control: public,
max-age=3600`) returns the policy, and `/v1/me` carries the same object under
`nudges`. Every client — Android, iPhone, desktop, web — reads it at most once
a day, keeps the last good copy and falls back to the built-in defaults
(`nanomuse_cloud/nudges.py`, `DEFAULT_NUDGES`) when the relay cannot be
reached:

```json
{"version": 1, "star": {"enabled": true, "url": "https://github.com/nano-muse/nanoMuse",
 "moments": {"signed_in": true, "tasks": [3, 10, 30], "new_look": true, "exhausted": true,
             "days_used": [7, 30], "goal_done": true},
 "cooldown_days": 7, "max_asks": 4, "text": "", "text_zh": ""}}
```

`tasks` are the finished-task counts at which to ask (a task is a turn the
person started that ended in a reply; the naming conversation and background
runs never count), `days_used` the n-th distinct day the app was opened, the
named moments on or off, `cooldown_days` the least time between two asks,
`max_asks` the lifetime cap per device ("Not now" counts; a device that went
to GitHub is never asked again). `text` and `text_zh` (after 0.22) are the
sentence on the card in English and 简体中文, trimmed, at most 200 characters
each (code points, so CJK counts the same as Latin), empty by default: an app
in Chinese shows `text_zh` if set, else `text` if set, else its own sentence;
any other language shows `text` if set, else its own; the card's title and
buttons stay the app's. Apps built against 0.22 and earlier ignore both; a
policy stored by 0.22 is served with the two empty. The operator's page has a *Star asks* card
under *Settings*; `GET /v1/admin/nudges` returns the policy in force, the
defaults, whether the page set it and `updated_at`; `PUT /v1/admin/nudges`
takes the whole policy (unknown keys dropped, ints ≥ 1, lists of distinct
positive ints sorted ascending, `url` http(s) ≤ 200 characters,
`cooldown_days` 0–365, `max_asks` 0–50, `text` / `text_zh` strings ≤ 200
characters; a bad value is a 400 with a plain
message), bumps `version` so clients can tell copies apart, and notes a
`nudges.changed` event; `{"reset": true}` goes back to the defaults. The
policy lives in the `settings` table under `nudges`.

### Money

Every request is priced in yuan at the provider's Beijing list prices (set per
model: `price_in` / `price_out` per million tokens, `price_in_idle` /
`price_out_idle` for a model priced by the hour with `idle_hours` as
`[start, end]` in Beijing time, `cached_in_rate` for the share of the input
price a cached prompt token costs, `price_image` and `price_image_2k` per
picture out and `price_image_in` per picture sent in, `price_second` per second
of video at the base resolution and `price_second_res` as `{"720P": 0.2, ...}`
above it) and stored in the ledger next to the token count; a chat is priced
at the hour its reply comes in, with the provider's `cached_tokens` at the
cached rate, and the ledger line's `extra` says when either applied. A non-member account has one pool for
its lifetime — `ALLOWANCE_CNY` (¥10 by default, adjustable at runtime), grown by invites (both
sides) and the operator's credit; a picture or a clip that would go
over it is refused before it is made, a chat once the pool is spent. Clips are
not counted apart: a clip is just the dearest line on the same allowance.
Members — the identifiers in `ALLOWED_IDENTIFIERS`, or any account the
operator marks on the admin page — have no limit, and (with
`CLOUD_ANY_MODEL_MEMBERS=1`, the default) may name **any model the provider has
under the operator's key**, not only the menu's: the id goes upstream as typed,
as long as it is used for what it is — a chat model at `/v1/chat/completions`,
an image model at `/v1/images/*`, a video model under the video paths; never
across. Pictures and clips travel through the provider's qwen-image / Wan-shaped
APIs, so a model of another family gets the provider's answer. `/v1/models`
says `nanomuse.any_model` for the account, `/v1/me` the same under `account`,
and `GET /v1/models/<id>?kind=chat` checks a typed id (the answer's `listed` is
false and `priced_as` names the menu model whose prices stand in for it in the
ledger — the dearest of its kind, so the operator's page errs high). It is how
a member tries a model before it goes on the menu. From 0.10 a member does not
have to know the id: with `CLOUD_CATALOG=1` (the default) the relay reads the
provider's own `/models` under the operator's key (once an hour,
`CLOUD_CATALOG_TTL_S`), sorts the ids by their shape into chat and picture
models — the spoken, heard, embedding and rerank ones are left out, and a
video model is not on the compatible list (`catalog.py`) — and lists them in
the member's `/v1/models` after the menu, each with `catalog: true`, `listed:
false`, `priced_as` and `vision` (whether the chat model reads pictures); the
answer's `nanomuse.catalog` says how many and the provider's error if the list
could not be refreshed (the last one stands). The apps' pickers then show the
menu and *More models on your account* as two groups, and a guest sees the
menu alone. Names are a guess, and a wrong guess costs a person a feature —
DeepSeek V4 on Model Studio reads pictures, nothing in its name says so, and
an id the provider has retired still appears on `/models` — so from 0.11 the
relay checks (`CLOUD_CATALOG_PROBE=1`): after the list is read, each chat
model is asked, in the background and three at a time, to reply with one
word and then to name the colour of a small magenta square; a model the provider
refuses is left off the list, `vision` is what the model answered, and
`verified: true` marks an entry the probes have confirmed (the name's guess
stands while a probe is pending). The answers are kept in the database
(`model_probes`) for `CLOUD_CATALOG_PROBE_TTL_S`, a week by default, so a
restart asks nothing again; `/v1/admin/catalog` shows the whole of it — which
models answer, which see, which were refused and with what words — and the
operator's page has a *Model catalog* panel. The relay also reads what a
request says about reasoning before it applies `CHAT_DEFAULTS`: an app that
sends `reasoning_effort` (or `thinking`, `thinking_budget`) asked for
thinking, and the shipped `enable_thinking: false` would make Model Studio
refuse the pair, so the default follows the request. `/v1/me` carries a `spend`
block (`total`, `grant`, `left`, `unlimited`, `warn` at 80 %, `usd_cny`,
`total_usd`, `grant_usd`, `left_usd`, `today`, the bonus amounts,
`own_key_docs`, `openrouter_url` and `ways`; the 0.4 names `daily_cap` /
`left_today` / `resets_at` = 0 for one more version) and each model in
`/v1/models` carries its `nanomuse.price_cny`, so the apps show what was spent
in both currencies. The refusal, `429 allowance_exhausted`, says what is left
and where the three ways on lead (one's own key, a plan one already pays for, an invited friend) — sign-in and
the hub are never gated, only the model routes. The admin page shows spend per
account and per day (`DAY_OFFSET_H`) in ¥ and $.

**Where the person is (0.17).** `/v1/me` (and the sign-in answers) carry
`region`: `cn` for an account opened with a mainland China phone number or a
request whose address the offline geo database places in mainland China,
`intl` for an address placed anywhere else (Hong Kong, Macao and Taiwan
included — Bailian does not sign them up), `unknown` when neither is known
(no geo file, a private address). `spend.ways` lists the ways on in the order
for that person — `[{"id": "bailian", "url", "mainland_only": true},
{"id": "openrouter", "url", "mainland_only": false}, {"id": "invite", "url",
"bonus_cny"}]`, Bailian first for `cn`, OpenRouter first otherwise, the
invitation last — and the 80 % heads-up and the refusal's `ways` and
`message` follow the same order: a mainland account is pointed to Bailian's
free tier, everyone else told that Bailian only signs up mainland accounts and
that OpenRouter is the easy way outside (one account, one key, pay as you go).
Nothing is sent anywhere for this: the region is read from the number's
country code and the local ip2region file.

**What each provider covers (0.21, contract C11).** Next to `ways` — whose
two key rows now also carry `name`, `name_zh`, `key_url`, `covers` and `auth`
— `spend.guidance` (and the refusal's `guidance`) is the whole own-key card:
`{version, updated, region, docs, providers[], plans[], local[], caveats}`.
`providers` is every provider of the catalogue that signs people up where the
person is, in order — the mainland leads with Bailian (one key for chat,
hands, pictures and clips), everyone else with OpenRouter and OpenAI, the rest
by how much the key covers — each as `{id, name, name_zh, protocol, base_url,
key_url, auth[], regions[], covers[], defaults{}, one_key, note, note_zh}`
(a two-edition provider such as Kimi or MiniMax names the region's base URL
and key page). `plans` are the subscriptions an app can sign in with instead
of pasting a key — `{id: chatgpt | claude | kimi | openrouter, provider, name,
auth, clients[], covers[]}`; the ChatGPT one covers chat and hands only, and
`caveats.chatgpt` (`_zh`) is the honest line about it. `local` lists Ollama,
LM Studio and vLLM. The facts come from `nanomuse_cloud/providers.json`, a
copy of the runtime's `nanomuse/llm/providers.json` written by
`node scripts/providers-json.mjs` (CI checks it); the relay only orders it,
and the apps keep the words. Nothing is renamed: a client from before reads
`ways` as it always did.

`SIGNUP_TOKENS=0` (the default) runs the relay without a token ceiling: usage
is metered and shown, nothing is refused for lack of tokens (`/v1/me` says
`"unlimited": true` and the apps show 「不限」). `DAILY_CAP_TOKENS=0` and
`PER_MINUTE_REQUESTS=0` switch those two checks off in the same way.

**Reserve, then settle (0.13).** Requests started together used to pass the
allowance check one by one and overshoot it together. Now each request is
*reserved* while it runs and *settled* when it is over: a picture or a clip at
its known price, a chat at a typical turn's worth of its model (6 000 prompt
and 1 500 completion tokens — the ledger gets the real figure when the reply is
in), and a clip still being made holds its price until the task is seen done,
for an hour at most. A clip is charged once, at the price fixed when it was
submitted, the first time its task is seen `SUCCEEDED`: by the app's poll, or
(0.24) by the relay itself. Since an app that was closed never polls, the relay
asks the provider about every unsettled task once shortly before the hour's
hold lapses and once more before the row is purged (three days), a handful of
tasks a minute: `SUCCEEDED` charges the clip, `FAILED` or `CANCELED` lets the
hold go, a task the provider no longer knows is marked `UNKNOWN`; a provider
that does not answer is asked again next minute. A poll after the relay settled
a task charges nothing more.
The check counts what is held: a chat starts while anything is left beyond it,
a picture or a clip only when its own price fits on top. At most `MAX_IN_FLIGHT`
requests of one account run at once; the one over that is told so
(`429 too_many_in_flight`, `retry_after`) rather than queued. Reservations live
in memory and lapse on their own after the upstream timeout, so a client that
vanished before its stream began cannot hold a slot for good.

### Operator's page

`/app/admin/` asks for `CLOUD_ADMIN_TOKEN` (kept in the tab's sessionStorage)
and is the dashboard from `/v1/admin/overview`: how many accounts (with a
password, members, disabled), who was active today and over the period,
what it cost today / this week / over 7, 30 or 90 days split by kind (chat,
pictures, video) and by model, spend by day as stacked bars, the top
spenders, today's signals (sign-ins, failures, budget refusals, upstream
errors) and the timeline across accounts with a kind filter. The
accounts table showed the masked hint until 0.22 and now the number or
address itself (below); opening one account (`/v1/admin/accounts/{id}`)
shows its spend by kind / model / day, sign-ins (device names,
revoked ones too), remembered devices with presence, every request and its
whole timeline — page by page to the first line
(`/v1/admin/accounts/{id}/ledger` and `/events`, `?before=&limit=`) — with
the grant / member / disable / delete buttons. From relay 0.10 the relay
records the network address and the client (`User-Agent`) with each sign-in,
request, event and device, and the account's first / last address and last
client: the accounts table has a *Client / IP* column, the drawer an
*Addresses / IP* section (how often, first, last, platforms) and the address
on every row, and an address opens the accounts seen from it
(`/v1/admin/address?ip=`). The text of a chat is on the page only for
accounts with *Help improve nanoMuse's AI models* on, and only the training
view of it (below); every account that kept turns is in the *By account*
table of the Data controls panel, and its conversations are read in full in
the drawer — each turn expands to every message and tool call — with an
export of that account's turns (`/v1/admin/samples/export?account_id=`).
Identifiers are kept AES-GCM-encrypted with a key derived from
`CLOUD_SECRET`. A person can also remove themselves: `POST /v1/auth/delete`
with their key deletes the account, its keys, ledger and devices.

Two more panels come from `/v1/admin/series` and `/v1/admin/traffic`: the
relay's own numbers by day (sign-ins, new and active accounts, sign-ups
through an invite, data switches turned on, calls, refusals, upstream errors),
the remembered devices by kind and system, the invite funnel and — with
`WEB_INFO_URL` — how many nanoMuse Web accounts and sessions the gateway
holds; and, with `TRAFFIC_DB`, the project site's visits and downloads:
page views, visitors, crawlers, downloads per file from the mirror next to
GitHub's own download counts, stars, referring sites, the pages. The traffic
database is written by `demo/showcase/mirror/traffic.py` from Caddy's access
log — daily counts only; the script never stores an address. A fourth panel,
*The phone in the browser*, comes from the showcase gateway through
`/v1/admin/demo` (`WEB_ADMIN_URL` + `WEB_ADMIN_TOKEN`): every visitor who
signed in there with the address and browser of the first and the latest
visit, the demos running now and the period's demos — when, how long, from
where, with what, what each used (requests, tokens, pictures, clips) and why it
ended — and the same for one account in its drawer (the visitor id there is
the account id here).

From 0.11 every address on the page is named: country, province and city
from ip2region's offline database ([lionsoul2014/ip2region](https://github.com/lionsoul2014/ip2region),
Apache-2.0; city level in China, country and state elsewhere), which the
relay fetches once after start into its data directory (`CLOUD_GEOIP_DB`,
`ip2region_v4.xdb`, 11 MB) and reads in memory — no third party is ever asked
about a visitor. Every admin answer that carries addresses adds `places`
(`{ip: {country, code, province, city, isp, text}}`), the address drawer
says where the address is, and a *Where from* panel (`/v1/admin/places?days=`)
counts accounts (by their latest address), new accounts, sign-ins, requests
and the showcase's visitors by country and province; the `geo` block in
`/v1/admin/overview` says whether the file is there, still being fetched, or
failed (the panel then says so and the page works without places).
`CLOUD_GEOIP=0` switches it off. It is where the network exit is — a phone on
mobile data or a proxy shows up elsewhere — so the page says "guessed".

From 0.14 the page is pages. A side navigation holds *Overview*, *People*,
*Places*, *Money*, *Activity*, *Demo*, *Data controls*, *Site*, *Models*,
*Health* and *Settings*; the view and its filters live in the hash
(`#people?country=中国&province=广东省&status=member&sort=spent`), so a view
is a bookmark and a link the operator can paste to themselves, and each
view fetches its own numbers the first time it is opened (the period
selector applies to all of them). *Overview* keeps the headline tiles, a
health strip, spend by day, the top regions and spenders and the latest
events, each panel linking to its page. *People* is the accounts filtered:
by region (country → province → city, from the account's latest address),
sign-up channel, status (member, disabled, locked, with or without a
password, *Help improve* on, pool used up, a device online, new this
period), last activity (24 h, 7 d, 30 d, older, never), lifetime spend
bucket and last client, plus a search over the hint / id / address — and the
charts above the table are the same filters drawn: sign-ups by day, where
they are (click a country to see its provinces, a province its cities),
spend buckets, activity, channel and client, each bar a filter that one
click applies and a second removes. The table sorts by any column and
exports the current selection as CSV (with the identifiers since 0.22, as
the table shows them).
*Places* ranks countries and provinces by accounts, new accounts,
sign-ins, requests or demo visitors, and a row opens *People* with that
region chosen. *Money* has the kind chips (chat, pictures, video, calls) and
a share bar over the model table; *Activity* searches the timeline;
*Demo* filters the sessions (running, signed in, anonymous, own key) and
charts demos a day, why they ended and where visitors came from; *Models*
searches the catalog; *Health* is `/v1/admin/health` on the page (in-flight
requests, hub connections, the last hour, the database, the upstream key),
refreshed every 30 s.

From 0.22 the console shows accounts in full: the phone number or e-mail
address stands beside the hint in the *People* table, the top spenders, the
latest events and the account drawer (`/v1/admin/overview` and
`/v1/admin/accounts` decrypt them for the console's answer; the People CSV
carries them too — the file is the operator's). Everything that leaves the
console — the server log, the e-mails, `/v1/admin/health`, the public pages —
still carries the masked hint only. Two pages are new: *Controls* (the five
switches, the threshold rules and the audit log — [above](#controls-022); the
first line of *Overview* says which switches are off and the next threshold)
and *Stats*, from `GET /v1/admin/stats?days=` — one registry in
`nanomuse_cloud/stats.py` defines every figure once, with a sentence saying how
it is computed (the ⓘ on each panel) in English and Chinese: accounts per UTC
day (total, new, active by any call and by model call, sign-ins, failures,
deletions), by sign-in method and by origin (country code or e-mail domain),
devices per account and by platform, model calls and tokens per day, by model
and the top 20 accounts, how far the limited accounts' pools are used, sync
pushes / pulls / messages per day, errors per day by code, API calls per day
by group, the GitHub series, and the relay itself (version, started at,
uptime, database size, hub sockets, what is paused). Every panel has a table
and a CSV (`GET /v1/admin/stats/{id}.csv?days=`); days are UTC with the
operator's local date beside each. The counters behind the per-day figures
(active accounts, API calls, errors, sync traffic) live in the `daily` table,
so a restart loses nothing. *Site* opens with the GitHub panel from `GET
/v1/admin/github?days=`: stars, forks, watchers, open issues and release
downloads, what each day added, downloads by platform and by asset, and
*Refresh now* (`POST /v1/admin/github/refresh`); the collector
(`nanomuse_cloud/github_stats.py`) reads `GET /repos/{owner}/{name}` and
`/releases` every six hours and keeps one row per UTC day — a failed read
leaves the previous row and shows on the page, the relay runs on without
GitHub.

### Web console

`/app/` is the person's own page in the same design as the phone app: sign in
with a code or a password, the devices of the account with their Muses to
talk to, and an account sheet (`/v1/me`) with the allowance, usage by kind
and by model, the sign-ins with a way to revoke each, the recent activity,
set / change / remove the password, sign out here or everywhere.

### Invitations and the one pool (0.5, both sides since 0.9)

Every account has an eight-letter invite code (`GET /v1/me/invite`: the code,
the share link `INVITE_URL` + code, who came, what they brought). A new person
who signs up with it — `invite` in `POST /v1/auth/verify`; the web app and the
console pick it up from `?invite=…` — adds `INVITE_BONUS_CNY` to the inviter's
pool **and the same to their own** (ledger `from: invite` / `from: invited`);
the second sign-in of the same person, one's own code and an unknown code add
nothing (and are not errors). Until 0.9 joining the co-creation programme
added ¥10 once (`contribute_bonus_at` remembers who took it); that bonus is
gone, and the data switch earns nothing either way.
`GET /v1/estimate?images=5&clips=4` says what a job would cost
next to what is left, so the app can ask before a new face is made. The
operator credits an account — a merged pull request, a good bug report — with
`POST /v1/admin/credit {identifier | account_id, cny, note?}` (or the *Add
credit* button on the admin page). A database from 0.4 is moved over on the
first start: every account's pool becomes what it had spent plus the
allowance plus any unused 0.4 credit, so nobody starts in debt.

### Data controls (0.9)

*Help improve nanoMuse's AI models* is one switch per account, under Settings →
Data controls on every app and on the console's account sheet
(`/v1/me.contribute`, `POST /v1/me/contribute {on}`). With it on, each chat turn
through the relay is kept in `samples` — **the training view only**: what the
person wrote, what the model answered and the tool calls it chose, plus the
model id, token counts and the app and language headers. Never the system
prompt (the person's memory, SOUL and instructions), never what a tool
returned (their files, their screen, what another app showed), never a
picture, a clip or a voice note (a marker stands where one was), and never
next to who they are: a sample carries the account id only and the export
(`GET /v1/admin/samples/export`, JSON lines) leaves even that out. The person
sees the count, turns the switch off at any time (nothing more is kept; what
was kept stays counted so they know there is something to delete) and deletes
what was kept with `DELETE /v1/me/samples`; deleting the account deletes them
too. `IMPROVE_DEFAULT` is what an account **created from now on** starts with —
`0` (the code's default) off until the person turns it on, `1` on until they
turn it off; an account from before keeps its own setting, and a default-on
account's timeline says `contribute.default` rather than `contribute.on`, so
the operator can tell a choice from a default. Say the default in the privacy
policy you link as `PRIVACY_URL`; the apps show it next to the switch. The
operator's page has a *Data controls* panel from `GET /v1/admin/data`: how many
accounts have the switch on (and how many ever turned it off), turns kept by
day, model and app, switches turned on / default-on / off / deleted by day,
tokens, the newest turns, and the export.

## Operating

```bash
# is it well? aggregates only (0.13): requests under way, the hub's counters, the last
# hour's requests / upstream errors / refusals / sign-ins, the database, `problems` —
# what deploy/nanomuse-hk/selfcheck.sh reads every ten minutes
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" https://$CLOUD_DOMAIN/v1/admin/health
# who signed up (with the phone numbers and addresses since 0.22 — the console's answer)
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" https://$CLOUD_DOMAIN/v1/admin/accounts
# top up someone by phone/e-mail or by account id
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"identifier":"13800138000","tokens":500000}' https://$CLOUD_DOMAIN/v1/admin/grant
# thank a contributor: ¥10 more in their pool
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"identifier":"dev@example.com","cny":10,"note":"PR #12"}' https://$CLOUD_DOMAIN/v1/admin/credit
# switch an abusive account off
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"identifier":"13800138000","disabled":true}' https://$CLOUD_DOMAIN/v1/admin/disable
# raise the starter allowance for everyone from now on (0.15) — no app update needed …
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"allowance_cny":20}' https://$CLOUD_DOMAIN/v1/admin/settings
# … and give the accounts that exist the difference, once
curl -X POST -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" https://$CLOUD_DOMAIN/v1/admin/allowance/apply
# a one-off present to every non-member account
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"cny":5,"note":"1,000 stars"}' https://$CLOUD_DOMAIN/v1/admin/credit-all
# set what one account has left (0.16); grant_cny sets the total, delta_cny adds or takes
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"identifier":"13800138000","left_cny":5,"note":"reset"}' https://$CLOUD_DOMAIN/v1/admin/pool
# the same for everyone limited (or account_ids:[...] for a chosen set)
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"all":true,"left_cny":5}' https://$CLOUD_DOMAIN/v1/admin/pool/batch
# when the apps may ask for a star (0.18): the policy in force, and a new one — PUT takes
# the whole policy; a key left out goes back to its default, not to what was stored
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" https://$CLOUD_DOMAIN/v1/admin/nudges
curl -X PUT -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"star":{"moments":{"tasks":[5,20]},"cooldown_days":14,"text":"A star on GitHub helps others find nanoMuse.","text_zh":"在 GitHub 点个 star，让更多人找到 nanoMuse。"}}' \
  https://$CLOUD_DOMAIN/v1/admin/nudges
# the switches (0.22): what is on, flip one with a note for the audit log, read the log —
# from the relay's own shell (the CLI reads CLOUD_ADMIN_TOKEN and PUBLIC_BASE from the
# environment, or --token / --base; --actor names you in the log, else cli:<user>)
nanomuse-cloud admin controls list
nanomuse-cloud admin controls set free_allowance off --note "upstream bill" --actor lgy
nanomuse-cloud admin controls set free_allowance on
nanomuse-cloud admin controls audit --limit 50
# … or the same over HTTP from anywhere
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" https://$CLOUD_DOMAIN/v1/admin/controls
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" -H "X-Admin-Actor: lgy" -H 'Content-Type: application/json' \
  -d '{"enabled":false,"note":"upstream bill"}' https://$CLOUD_DOMAIN/v1/admin/controls/free_allowance
# a threshold rule: at 1,000 accounts, close sign-ups
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"threshold":1000,"action":"close_signups","note":"beta cap"}' https://$CLOUD_DOMAIN/v1/admin/controls/rules
# the figures as CSV (every id of GET /v1/admin/stats)
curl -H "X-Admin-Token: $CLOUD_ADMIN_TOKEN" "https://$CLOUD_DOMAIN/v1/admin/stats/accounts_daily.csv?days=90" -o accounts.csv
```

In Docker the CLI is `docker compose exec relay nanomuse-cloud admin controls
list --base http://127.0.0.1:8787` (the container has `CLOUD_ADMIN_TOKEN` in
its environment; `--base` keeps the call inside the container instead of going
out through Caddy).
The tables behind all of this (`daily`, `controls`, `control_rules`,
`control_audit`) are created on the first start of 0.22 — `CREATE TABLE IF NOT
EXISTS` — so a deploy is the usual image swap, no migration step.

Every response carries `X-Nanomuse-Charged` and `X-Nanomuse-Request` so a user
report can be matched to a ledger row without any content being logged.

### Sending codes

- **E-mail** (`CODE_SENDER=smtp`): any SMTP account; port 465 uses implicit
  TLS, anything else STARTTLS.
- **Mainland phones** (`CODE_SENDER=aliyun`): an Aliyun RAM user with
  `ALIYUN_ACCESS_KEY_ID/SECRET`, a signature (`ALIYUN_SMS_SIGN`) and a template
  (`ALIYUN_SMS_TEMPLATE`). `ALIYUN_SMS_API=dypns` (default) sends through
  号码认证服务's `SendSmsVerifyCode`, whose ready-made signatures and templates
  (`100001`: 「您的验证码为${code}…${min}分钟内有效」) need no review — the RAM user
  needs `AliyunDypnsFullAccess`. `ALIYUN_SMS_API=dysms` is 短信服务's `SendSms`
  with your own approved signature and a template whose only variable is
  `${code}`; that review is Aliyun's process and takes a working day or two.
  Either way the relay makes and checks the code itself.
- `both` routes by identifier type. Non-mainland numbers are accepted as
  identifiers but the Aliyun sender only covers `+86`; use e-mail for the rest
  or plug in another sender in `senders.py`.

Any sender but `log` needs `CLOUD_SECRET`: without a secret the relay would
hash every identifier with the published development key while real codes go
out to real people, so it refuses to start (`CODE_SENDER=log` on your own
machine is the one case where the development key is fine).

### For App Store review

Apple's and Google's reviewers sign in with an account you give them, and
they cannot receive our codes. `REVIEW_ADDRESSES` (comma-separated e-mail
addresses) and `REVIEW_CODE` (six digits) name that account: a code request
for one of those addresses sends nothing and answers `204` as if it had, and
`POST /v1/auth/verify` accepts exactly `REVIEW_CODE` for it — within the same
code lifetime (`CODE_TTL_S`), attempt limit (`CODE_MAX_ATTEMPTS`) and rate
limits as any address, and whether sign-up is open or paused. The account is
an ordinary one with the usual allowance; the admin page tags it *review* in
the People table and on its page and leaves it out of the sign-up counts on
the Overview and the Stats page. With either value empty nothing changes.
Put the address and the code into the review notes in App Store Connect
(`tf-contact.env`: `DEMO_NAME`, `DEMO_PASSWORD`), nowhere else, and change
the code once the review is through. Only e-mail addresses are taken; a
phone number in the list is ignored with a line in the log.

## Tests

```bash
cd cloud && pip install -e ".[dev]" && pytest
```

The suite runs the whole app in-process against a fake upstream: sign-up and
throttling, model listing, charged chat (non-stream and stream), running out of
tokens and topping up, key revocation, and the image translation.
