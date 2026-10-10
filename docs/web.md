# The web console: your model, your key, your plan

> The web console is the app `nanomuse serve` serves at `/`: the front door of
> the desktop app and of a self-hosted runtime ([app.md](app.md)). This page is
> about one part of it: how it picks the model that answers, and what it offers
> when the model lacks something. The guide for making a key is
> [own-key.md](own-key.md).

## One catalogue

The console reads the same list of providers as the phones, the desktop and the
relay: [`nanomuse/llm/providers.json`](../nanomuse/llm/providers.json) (contract
C11). Each provider says what one key there covers, `chat`, `vision` (the
hands read screenshots), `image` (the avatar studio's pictures), `video` (its
clips), and which sign-ins it has besides a key. The console asks the runtime
first (`GET /api/providers`, which also says which slots are configured today
and what that covers) and falls back to the copy bundled at build time on an
older runtime, with nothing known about what is configured. `web/src/providers.ts`
is the module; `web/src/providers.test.ts` checks the ordering, the mapping
and the sentences.

## Where it shows

**Connections → Chat model.** The provider tiles are the runtime's presets, the
region's first pick first (Alibaba Cloud Bailian on the mainland, OpenRouter
elsewhere; [region.ts](../web/src/region.ts)). Under the tiles the chosen
provider's line from the catalogue says what its key covers and what to know
about it (the Kimi editions, the OpenRouter Image API, the ChatGPT caveat). The
*Hands model* picker lists models that see; its default is the provider's own
hands model from the catalogue (`defaults.hands`), or your account's hands
model when the provider has no model that sees and you are signed in; a
provider without `vision` and no account gets the one sentence instead of a
blind hands model. A *Proxy (optional)* field under them takes an
`http://host:port`, `https://` or `socks5://` address for this provider's
requests only (`[llm] proxy`; nanoMuse Cloud never goes through it, a SOCKS
address needs `httpx[socks]` on the runtime); a saved password comes back as
dots, and an emptied field clears it.

**Connections → Making pictures, Making clips.** The two media rows of the
Models contract (0.1.41), one card each under the chat model. The value is
`provider · model` as the runtime resolves it (`GET /api/connections` →
`image` / `video`: the slot as set and its `effective_*`): an explicit choice,
else the chat provider's own picture model when it has one, else your account's
when signed in, else the one sentence and an *Add a provider* button. The
picker offers *Automatic* first, a *nanoMuse Cloud* group when signed in, *The chat model's provider* when it has the capability
(its key serves, nothing to paste), and under *Add a provider* every catalogue
provider with the capability for your region, plus *Other OpenAI-compatible
endpoint* with a base URL; a provider without the capability is not offered.
A model may be picked from what the endpoint lists (the relay's menu and the
account's other models on nanoMuse Cloud) or left to the catalogue's default.
*Save* calls `PUT /api/connections/image` or `/video` with `provider` (a
catalogue id, or `openai` with a `base_url`), `model`, `base_url`, `api_key`
(into the vault as `IMAGE_API_KEY` / `VIDEO_API_KEY`; the relay's row names the
account key, the chat provider's row leaves it to the chat key); *Automatic*
sends all four empty, which clears the slot. The three dependent slots share
one shape: *Automatic* is the first entry of the *Hands model* picker and of
both media rows' provider select, saving it returns the slot to the resolution
order (the hands with `PUT /api/connections/gui {"model": ""}`), and a
*Currently provider · model* line under the control says what that resolves to
today, from the runtime's `effective_*` fields. A runtime without these routes
shows no media rows. `web/src/models.ts` is the module (the row's value, the
picker's choices); `web/src/models.test.ts` checks it.

The *Hands model*, *Picture model* and *Clip model* controls are one picker
(`web/src/components/ModelPicker.tsx`): a button reading `provider · model`
that opens a panel with *Automatic* first. A provider with a long list
(OpenRouter, SiliconFlow) shows eight models at first, its catalogue default
for that slot and your current choice first, with *Show {n} more* at the foot
of the group; once the rows pass eight in all, a *Search models* field filters
every group by model id or name as you type (*No model matches* when nothing
does). Esc or a click outside closes it. The folding and the search are
`web/src/model-list.ts`, checked by `web/src/model-list.test.ts`.

**Connections → Or sign in with a ChatGPT plan.** The card asks the runtime to
start the Codex sign-in (`POST /api/chatgpt/login` → `{url}`), opens the page
in a new tab, polls `GET /api/chatgpt/status` every two seconds for up to ten
minutes, and when the tokens are in the runtime's store offers *Use it for the
chat* (`[llm] provider = "chatgpt"`) and *Sign out of ChatGPT*
(`POST /api/chatgpt/logout`). The card says what the sign-in covers (chat and
the hands, not pictures or clips) and carries the honest line about OpenAI's
terms. A runtime without these routes answers 404; the card then names the
command to run in a terminal, `nanomuse chatgpt login`, instead of pretending.
The sign-in's callback lands on port 1455 of the machine the runtime runs on.
When the browser cannot reach it (a runtime on another computer, or the port
taken; `port_bound: false` in the login's answer), the browser ends on an
address that will not load; the card has a box for that address and hands it
to the runtime (`POST /api/chatgpt/callback {url}`; a stale link is 400
`state_mismatch`, a login older than ten minutes 409 `no_login`). The box is
there in every case, with a sentence saying why when the port could not be
bound ([configuration.md](configuration.md#a-chatgpt-plan-instead-of-a-key)).

**The allowance card** (Account, and in the chat on `allowance_exhausted`) has
three ways on: *Use your own model key* with the region's first pick, a *Set it
up* that opens Connections on that provider, *Get a key from …*, the guide, and
under *Other providers and what each key covers* the rest of the region's list
(the relay's `guidance.providers` when the relay sends it, relay 0.21; else the
catalogue's) each with its covers line, its own *Set it up* and key link;
*Sign in with a plan you already pay for* with the ChatGPT card inline; and
the invitation. The 80 % heads-up and the first-sign-in sheet point the same
way.

**Avatar studio.** Without an image model the *Draw* button is off and the
line under it is the one sentence (*Pictures need a provider with image
models: Alibaba Cloud Bailian, Zhipu GLM, SiliconFlow or Volcengine Ark* on
the mainland, *OpenRouter, OpenAI, Google Gemini or xAI Grok* elsewhere) with
*Change model* beside it. **Settings → Image & video models** shows the same
sentence as its value when the runtime says pictures or clips are not covered.

## The first run and the chat's opening

The first-run list is *Add a model → Connect mail, calendar, contacts
(optional) → Start*. There is no naming page: *Start* asks the runtime to begin
the first conversation (`POST /api/firstrun/start {lang}`, which also marks the
first run done) and opens the chat, where the opening happens the way it does
on the phones and the desktop (contract C4 in [parity.md](parity.md)):

1. **The app speaks first**, as the agent, three lines in the console's
   language: hello, *a bit about how I work* (this computer, the files you
   point it to, asking first, where your messages go), and *what should I call
   you?* They cost no tokens and the model never sees them as messages; the
   chat draws them where the history begins (`GET /api/firstrun?lang=` returns
   them as `intro`).
2. **The model asks your name** and, when you give it (or decline), reports it
   in a ```` ```nanomuse-naming ```` block at the end of its reply, the same
   JSON the desktop and the phones read (`user_address`, `suggest`,
   `agent_name`; `nanomuse/fences.py`). The runtime owns the phases
   (`none → ask_user_name → ask_agent_name → named → done`,
   `nanomuse/server/firstrun.py`, saved as `firstrun.json` next to the
   profile), writes your address to the profile and to memory as *Call them:
   …*, and tells the page over the socket (`firstrun` frame). The block itself
   is never shown, not even half-streamed.
3. **The chooser** appears under the reply: the model's two or three name
   suggestions, or two from the built-in pool when it gave none, and
   *Something else* for a name of your own. A chip saves the name at once
   (`POST /api/firstrun/pick {name}`) and sends it as your message, so the
   model's next reply is its first as itself; a typed name reaches the model
   and comes back in the block. A card the app answers itself (the avatar
   options) dismisses the chooser (`POST /api/firstrun/dismiss`).

While the first conversation runs, its turns are never *tasks* for the star
asks. The addendum that tells the model about the ritual goes only into the
chat the conversation is bound to, never into a routine, a feed post or
another chat. *Skip setup* keeps the plain "onboarded" without the
conversation; the identity form stays under Settings for changing the name,
face and tone later. An older runtime without these routes gets the plain
greeting and the form-free list as before.

## The sentences

Every unavailable feature is one sentence, never a raw error, built by
`unavailableLine(cap, region, locale)` from the region's providers with that
capability (four at most, in the catalogue's order):

| Capability | English | 中文 |
|---|---|---|
| `image` | Pictures need a provider with image models: {providers}. | 画图需要一个有图像模型的服务商：{providers}。 |
| `video` | Clips need a provider with video models: {providers}. | 生成视频需要一个有视频模型的服务商：{providers}。 |
| `vision` | The hands need a model that sees pictures: {providers}. | 动手需要一个能看图的模型：{providers}。 |
| `chat` | Chat needs a model: {providers}. | 对话需要一个模型：{providers}。 |

A *How* link beside each goes to [own-key.md](own-key.md). The provider names
come from the catalogue in the console's language (`name` / `name_zh`).

**A turn the relay refused** is one sentence too, by the relay's `code`
(`nanomuse/server/failures.py`; the sentence is the key in `web/src/i18n/zh-CN.ts`,
so the Chinese is looked up from the English): the allowance used up (with the
ways card under it), the daily cap, a rate limit, a bad key, a disabled account,
a model the relay does not offer, the provider behind the relay in trouble,
and since 0.1.40 the four that fell through to *The model provider answered
with an error: …* and the five the operator's switches send
([cloud.md](cloud.md#controls)):

| The relay said | The chat says |
|---|---|
| `413 too_large` | That message is too large for the model's window. Shorten it, leave out some attachments, or start a new chat. |
| `403 not_invited` | This relay takes new accounts by invitation only; sign in with an invite code under Account. |
| `429 too_many_in_flight` | Too many turns are running on this account at once; wait for one to finish and try again. |
| `429 provider_busy` | The model provider is busy; try again in a moment. |
| `429 allowance_exhausted` with `paused: true` | The free allowance is paused on this relay for now, not used up. Your own model key under Connections keeps you going; your sign-in, your devices and what is left stay as they are. (the same ways card as a spent pool, the notice carries `paused`) |
| `403 signup_closed` | New sign-ups are paused on this relay for now; existing accounts keep working. Try again later. |
| `503 service_paused` | nanoMuse Cloud is paused by its operator for now; your sign-in and your data are kept. Try again later. |
| `503 sync_paused` | Conversation sync is paused on this relay for now; what is stored is kept and your devices keep working on their own. |
| `503 hub_paused` | The device hub is paused on this relay for now; each device keeps working on its own. |

The raw reply stays under *Details* for a bug report, never as the only thing shown.

**A turn your own model failed** (a refused key, a model the endpoint does not
know, a rate limit, a timeout, no connection) shows its sentence and, when you
are signed in and the chat is not on the account, *Use nanoMuse Cloud this time*
(the own-key models contract, section 4; the desktop and the phones have the
same). It sends the same words again with `via: "cloud"` (`POST
/api/threads/{id}/send`, or the socket's `send` frame): the runtime runs that
one turn on the relay's recommended chat model under the account's key, and the
next turn is back on your model. `[llm]`, *Use nanoMuse Cloud models* and the
conversation stay as they were; with the Cloud models switched off this button
is the only thing that spends the allowance. The user bubble, the reply and a
failure of that turn carry `model_used` (the model id); the reply shows
*Answered by nanoMuse Cloud this time (model)* under it, and a notice that
carries `model_used` does not offer the button again. Signed out, the runtime
answers `401 signed_out` with *Sign in to nanoMuse Cloud first.*, shown under the
button. Switching *Use nanoMuse Cloud models* off while the chat model is the
account's is refused with `409 chat_on_cloud` (*Add a provider of your own
first; with nanoMuse Cloud off, nothing else could answer.*), shown under the
switch.

**A connection test that fails** (*Test* under a model, the hands) says the same
sentence a chat turn would for that error (`POST /api/connections/llm/test`
answers `{ok: false, code, error, detail}`; `error` is the sentence, `detail`
the provider's words), with *Details* under it.

**Why the Sentinel asks** is written by the runtime from its settings
(`'shell' is in always_ask_tools`, `risk level is 'sensitive' (mode=ask)`,
`covered by your 'always' permission for shell:ls`, the taint sentence);
`localReason()` in `web/src/i18n/index.ts` knows those shapes and renders each
as a sentence in the console's language, keeping the tool, the risk and the
destination. The same words appear under a denied step in today's record. A
shape it does not know is shown as it came.

**Permissions you granted** (avatar → Permissions) are listed by the risk class
of the tool they cover, the gravest first: sensitive, moderate, low, safe (the
class comes from `GET /api/state` → `settings.tools`); each row says the tool,
how long the grant lasts and when it was given, and can be revoked on its own.

## Checks

```sh
cd web && npm run lint && LANG=en_US.UTF-8 npx vitest run && npm run build
```

The build writes `nanomuse/server/static/`, which is committed with the change;
`web/tsconfig.tsbuildinfo` is a by-product and is not.
