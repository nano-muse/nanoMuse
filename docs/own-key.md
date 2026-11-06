# Bring your own key


nanoMuse is free and non-profit. The model behind it costs money, and the
developer pays for a starting allowance per account (the app shows the relay's
current figures). When it is gone, there are two ways on that need nothing
from nanoMuse: a key of your own at a model provider, or a plan you already
pay for (ChatGPT, Claude, Kimi) signed in from the app.

Every client reads the same list of providers, with what each one covers:
**chat**, **the hands** (a model that sees screenshots), **pictures** (the
avatar studio) and **clips** (the avatar's short videos). A feature no
configured provider covers is simply not offered, with one sentence saying
which providers would; nothing breaks.

Your sign-in, your invite code and your devices are not affected: the account
stays, only the model provider changes. Nothing you say passes through nanoMuse
Cloud once your own key or plan is in use.

## Where you are decides who comes first

| | First | What one key there covers |
|---|---|---|
| Mainland China | **Alibaba Cloud Bailian** | chat, the hands, pictures and clips, all four under one key |
| Everywhere else | **OpenRouter**, then **OpenAI** | chat, the hands and pictures; clips are Bailian only for now |

Bailian only signs up accounts with a mainland Chinese identity; outside, one
OpenRouter account puts hundreds of models behind one key, pay as you go.
Beyond the first pick, every provider below works on its own or beside another:
DeepSeek for the chat and Zhipu for pictures, say.

Four jobs, four settings, one page: **Settings › Models** on Android, the
iPhone and the desktop, the *Connections* page in the web console. The rows are
*Chat*, *Operating the screen*, *Making pictures* and *Making clips*; each shows
`provider · model` and opens a picker that lists only the models that can do
that job (the screen needs a model that sees images). On the iPhone the screen
row is disabled (*Not on iPhone*): a phone cannot operate its own screen, and
your computer uses its own setting. [Which model does what](#which-model-does-what)
below has the details.

## What each provider covers

Chat = the conversation; hands = reading screenshots to operate the phone or
the computer; pictures = the avatar studio's images; clips = the avatar's
short videos.

| Provider | Chat | Hands | Pictures | Clips | Region | Make a key |
|---|:-:|:-:|:-:|:-:|---|---|
| Alibaba Cloud Bailian | ● | ● | ● | ● | mainland China | [bailian.console.aliyun.com](https://bailian.console.aliyun.com/?apiKey=1) |
| DeepSeek | ● | ● | | | both | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| Kimi (Moonshot AI) | ● | ● | | | both (a mainland and a global edition) | [platform.moonshot.cn](https://platform.moonshot.cn/console/api-keys) · [platform.kimi.ai](https://platform.kimi.ai/console) |
| Zhipu GLM | ● | ● | ● | | mainland China | [open.bigmodel.cn](https://open.bigmodel.cn/usercenter/apikeys) |
| SiliconFlow | ● | ● | ● | | mainland China | [cloud.siliconflow.cn](https://cloud.siliconflow.cn/account/ak) |
| Volcengine Ark (Doubao) | ● | ● | ● | | mainland China | [console.volcengine.com](https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey) |
| MiniMax | ● | ● | | | both (a mainland and a global edition) | [platform.minimaxi.com](https://platform.minimaxi.com/user-center/basic-information/interface-key) |
| OpenRouter | ● | ● | ● | | outside mainland China | [openrouter.ai/keys](https://openrouter.ai/keys) |
| OpenAI | ● | ● | ● | | outside mainland China | [platform.openai.com](https://platform.openai.com/api-keys) |
| Anthropic Claude | ● | ● | | | outside mainland China | [platform.claude.com](https://platform.claude.com/settings/keys) |
| Google Gemini | ● | ● | ● | | outside mainland China | [aistudio.google.com](https://aistudio.google.com/apikey) |
| xAI Grok | ● | ● | ● | | outside mainland China | [console.x.ai](https://console.x.ai) |
| Groq | ● | ● | | | outside mainland China | [console.groq.com](https://console.groq.com/keys) |
| Mistral AI | ● | ● | | | outside mainland China | [console.mistral.ai](https://console.mistral.ai/api-keys) |
| OpenCode Zen | ● | | | | outside mainland China | [opencode.ai/auth](https://opencode.ai/auth) |
| OpenCode Go | ● | | | | outside mainland China | [opencode.ai/auth](https://opencode.ai/auth) |
| Standard Compute | ● | | | | outside mainland China | [standardcompute.com](https://standardcompute.com/dashboard/api-keys) |
| API Route | ● | | | | outside mainland China | [api-route.com](https://www.api-route.com/api-keys) |
| Cheaper Inference | ● | | | | outside mainland China | [cheaperinference.com](https://cheaperinference.com/signup) |
| Opper | ● | | | | outside mainland China | [platform.opper.ai](https://platform.opper.ai) |
| AtmoRouter | ● | | | | outside mainland China | [atmorouter.dev](https://atmorouter.dev/dashboard/keys) |
| Ollama / LM Studio / vLLM (on your machine) | ● | | | | both | no key |

Only Bailian has a dot under *Clips* because nanoMuse's clip generation speaks
Bailian's video API; the other vendors' video models sit behind their own task
APIs, not wired this round. Under *Pictures*, OpenRouter goes through its
Image API with models such as `openai/gpt-image-2`; Gemini uses
`gemini-2.5-flash-image`.

The table is the repository's catalogue,
[`nanomuse/llm/providers.json`](../nanomuse/llm/providers.json): every client
and the relay read it; endpoints, default models and what each covers are in
there, checked against each vendor's documentation in October 2026.

## Making a key

The same three steps everywhere: sign up → create an API key in the console →
paste it into nanoMuse. **The key is for nanoMuse only; never send it to anyone
or paste it into a chat.**

- **Alibaba Cloud Bailian.** Sign in to [bailian.console.aliyun.com](https://bailian.console.aliyun.com/) with an Alibaba Cloud account (identity verification is required), accept *Enable Model Studio* on first entry, then create a key on the [API-KEY page](https://bailian.console.aliyun.com/?apiKey=1); it starts with `sk-`. A new account comes with free tokens for a while. Set a usage alert in the console.
- **DeepSeek.** Sign up, add credit and create a key at [platform.deepseek.com](https://platform.deepseek.com/); base URL `https://api.deepseek.com/v1`.
- **Kimi.** The mainland edition is [platform.moonshot.cn](https://platform.moonshot.cn/console/api-keys), base URL `https://api.moonshot.cn/v1`; the global one is [platform.kimi.ai](https://platform.kimi.ai/console), base URL `https://api.moonshot.ai/v1`. Accounts and keys are not shared between the two.
- **Zhipu GLM.** [open.bigmodel.cn](https://open.bigmodel.cn/usercenter/apikeys), base URL `https://open.bigmodel.cn/api/paas/v4`.
- **SiliconFlow.** [cloud.siliconflow.cn](https://cloud.siliconflow.cn/account/ak), base URL `https://api.siliconflow.cn/v1`; model ids carry the vendor prefix, e.g. `deepseek-ai/DeepSeek-V4-Flash`.
- **Volcengine Ark.** [console.volcengine.com](https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey): enable the models you want in Ark, then create a key; base URL `https://ark.cn-beijing.volces.com/api/v3`.
- **MiniMax.** Mainland edition at [platform.minimaxi.com](https://platform.minimaxi.com/user-center/basic-information/interface-key), base URL `https://api.minimaxi.com/v1`; the global base URL is `https://api.minimax.io/v1`.
- **OpenRouter.** Sign in at [openrouter.ai](https://openrouter.ai/) with Google, GitHub or an e-mail address, add credit under *Credits*, create a key under *Keys*; it starts with `sk-or-v1-`. *Settings → Limits* puts a monthly cap on a key.
- **OpenAI.** [platform.openai.com](https://platform.openai.com/api-keys), base URL `https://api.openai.com/v1`.
- **Anthropic.** [platform.claude.com](https://platform.claude.com/settings/keys). nanoMuse speaks Anthropic's own API; no compatibility layer is needed.
- **Google Gemini.** [aistudio.google.com/apikey](https://aistudio.google.com/apikey), base URL `https://generativelanguage.googleapis.com/v1beta/openai`.
- **xAI, Groq, Mistral.** A key from each console; base URLs `https://api.x.ai/v1`, `https://api.groq.com/openai/v1`, `https://api.mistral.ai/v1`.
- **OpenCode Zen.** A key from [opencode.ai/auth](https://opencode.ai/auth); pay per request from a balance, a few models are free. Base URL `https://opencode.ai/zen/v1`. Only the models on the OpenAI shape are reached, so chat and no hands: the vision model OpenCode lists, `deepseek-v4-flash-vision-exp`, is an id DeepSeek has retired on its own platform. OpenCode publishes no plan sign-in, only a key, so there is nothing to sign in with here.
- **OpenCode Go.** The subscription on the same host: Go ($10 a month) or Go Plus ($40) in the OpenCode console, then a key from [opencode.ai/auth](https://opencode.ai/auth). Base URL `https://opencode.ai/zen/go/v1`. Usage is counted per model against monthly, weekly and five hour limits. OpenCode means Go for coding agents and asks a client to name itself and to send one stable id per conversation in `x-opencode-session` ([its Go page](https://opencode.ai/go), under *Can I use Go with other coding agents?*). The runtime (and so the web console) sends `nanoMuse/<version>` as its user agent and the conversation's id in that header on every Go request; a call outside a conversation, such as the connection test, carries an id of its own. The desktop writes Go as its model adapter's own OpenCode Go route, which sends the same header and reaches each model on its own shape: the desktop offers the models that route's catalog lists, those on the Responses and Messages shapes included; elsewhere only the OpenAI shape is reached. The phone apps send it too, on chat and Responses requests to OpenCode's host: the id is the chat's prompt cache key, a hash of its first message that stays the same across its turns (two chats that open with the very same words share one). Chat only, for the same reason as Zen.
- **Standard Compute.** A key from [standardcompute.com/dashboard/api-keys](https://standardcompute.com/dashboard/api-keys); a fixed monthly plan from $19 with a monthly compute budget, and once it is used, requests stop with 402 (no overage charges). Base URL `https://api.stdcmpt.com/v1`. The default model, `standardcompute`, is a router that picks a model for each request from the ones enabled on the account's Models page; any id from `https://api.stdcmpt.com/v1/models` can be set instead. Chat only: the router's entry in that list declares no picture input, so the hands are not claimed.
- **Cheaper Inference.** A key from [cheaperinference.com/signup](https://cheaperinference.com/signup); one key reaches models from several labs. Base URL `https://api.cheaperinference.com/v1`. The default model is `gpt-5.4-mini`; any id from `https://api.cheaperinference.com/v1/models` can be set instead. Chat only here, on the OpenAI shape.
- **API Route.** Sign in and open [API keys](https://www.api-route.com/api-keys), then add balance. Base URL `https://global.api-route.com/v1`; the default model is `gpt-6.1-sol`, verified in `/v1/models` and with a chat request. Other model ids must come from the list available to your key. Usage is deducted from your prepaid API Route balance at the selected model's [current rates](https://www.api-route.com/pricing), separately from nanoMuse Cloud. Chat only here; picture input, image generation and video have not been verified. See the [provider documentation](https://www.api-route.com/docs/overview).
- **Opper.** A key from *API Keys* at [platform.opper.ai](https://platform.opper.ai); one key reaches 700+ models from 50+ providers at the providers' rates, with no markup, and the gateway is hosted in the EU. Base URL `https://api.opper.ai/v3/compat`. The default model is `claude-sonnet-4-6`; any id from `https://api.opper.ai/v3/compat/models` can be set instead, and a `provider/model` id such as `anthropic/claude-sonnet-4-6` pins one route. Chat only here, on the OpenAI shape.
- **AtmoRouter.** A key from [atmorouter.dev/dashboard/keys](https://atmorouter.dev/dashboard/keys); pay as you go, and one key reaches models from several labs. Base URL `https://atmorouter.dev/v1`. Model ids carry a route prefix, as `https://atmorouter.dev/v1/models` lists them; the default model is `cc/claude-sonnet-4-6`, and any id from that list can be set instead. Chat only here, on the OpenAI shape.

**Paste it into nanoMuse.**

- Phone: *Set it up* on the allowance card opens the provider form pre-filled; or *Settings → Providers → Add*, pick the provider, paste the key, save.
- Desktop: *Set it up* on the allowance card opens *Settings → nanoMuse Cloud* at the provider's row; or paste the key on that provider's row under *Ways on* there. The address is already filled in.
- Web console: *Set it up* on the allowance card opens *Connections* with the provider chosen; or *Connections → Chat model*, click the provider, paste the key, save.
- A runtime of your own: `[llm] provider = "bailian"` (any id from the table) and `api_key` in `config.toml`; the address and the default model fill in from the catalogue. Pictures or clips from another provider are an `[image]` / `[video]` block ([configuration.md](configuration.md#image-and-video)).

**Use it for.** Once the key is saved, a card asks what this key should handle:
one switch per job the provider can do (chat, operating the screen, making
pictures, making clips), all on. *Use it* moves those rows to this provider, on
the catalogue's default model for each job (or the first model of its list that
fits); *Not now* changes nothing, and so does a switch you turned off. The
other model choices stay as they are. Every row can be changed later under
*Settings › Models* (web console: *Connections*).

## Which model does what

*Settings › Models* (Android: the card at the top of Settings; iPhone: the
first card of Settings; desktop: right after General; web console: the *Chat
model*, *Hands model*, *Making pictures* and *Making clips* cards on
*Connections*) has one row per job:

| Row | What it does | Who is listed |
|---|---|---|
| Chat | The model that talks with you. | nanoMuse Cloud's chat models while signed in and switched on, then every provider of yours with chat models |
| Operating the screen | Looks at the screen and acts for you. Needs a model that can see images. | nanoMuse Cloud's hands model, then your providers' models that see images; disabled on the iPhone (*Not on iPhone*) |
| Making pictures | Portraits of your Muse and the pictures you ask for. | Your providers with image models |
| Making clips | Short clips of your Muse. | Your providers with video models (Bailian) |

Each row shows `provider · model` and opens a picker. Chat and screen operation
show the *nanoMuse Cloud* group first while signed in, with the relay's
lane-specific recommendation marked; media rows show only providers of yours
because the hosted Cloud does not generate pictures or clips. A self-hosted
relay appears in a media row only when its operator explicitly enabled and
advertised that capability. Each provider group holds only models that fit.
A provider without the capability does not appear in that row at all. A row
nothing covers shows the one sentence naming who could, and *Add a provider*.
A chat pick is the default
for new chats and moves the main chat (*Applies to the main chat and to new
chats; a side chat keeps its model.*): the main chat is the one conversation the
Chat tab always shows and is never new, so it would otherwise stay on the
provider it started with; a side chat already open keeps its model. A chat
that has not been written to yet takes the pick as well: the main chat right
after a sign-in (the account starts with an empty one), or a new chat you
opened and left. So what the Chat row names is what answers the next message
you send, in the main chat and in a new one, whichever source you came from:
a plan you signed in with (ChatGPT, Claude, Kimi), a key of yours or nanoMuse
Cloud; a sign-in never steps in front of a pick. The same
on the phones and the desktop. A group of yours picked in a chat's own picker
(a row of the `•••` menu, or a model under it) becomes the default as it is,
never reordered, and the main chat follows it with the model the chat resolved;
only a group named after a provider and holding that provider alone is led with
the pick, as a pick on the Models page does. On the phones, where a model group
of yours can carry a default thinking level (*All settings › Model Groups* on
the iPhone, *Model Groups* from the chat's picker on Android), the main
chat takes that level along when it follows the pick, as a new chat and the
chat's own picker do.

**Automatic.** The screen, pictures and clips rows open with an *Automatic*
entry that says what it gives right now (*Currently nanoMuse Cloud ·
Qwen/Qwen3.6-27B-FP8*, say, for screen operation). Pick it and the row forgets any choice made there and
follows one order: the chat model's provider when it is one of yours and can do
the job (its catalogue default), else a signed-in relay while switched on only
when its live menu offers that job, else the first provider of yours that can.
The hosted Cloud menu offers chat and screen operation, not media generation.
A choice you made always wins; nanoMuse Cloud
never steps in front of a provider you chose. Each device keeps its own choice,
because keys never leave the device where they were entered.

**The Cloud retry button needs your action.** After a failed turn, the error card
offers *Use nanoMuse Cloud this time* while signed in. Clicking it runs that one
turn on the account's model and changes no row. This button does not govern model
group routing: a Cloud model included in a phone's group can still be selected
automatically by that group. A failed picture or clip has no Cloud retry: fix or
choose a media provider of your own and retry there.

**Model groups can switch automatically.** This is separate from the Cloud retry
button. On Android and iPhone, a chat bound to a group can try another available
member after an error. Its alternatives come from that group's members, not every
model listed under every provider. A rate-limit error can trigger this without a
confirmation before the next request.

| Chat group setting | Android | iPhone |
| --- | --- | --- |
| Default | Rate-limit errors and provider errors identified as 5xx can advance to another member. Retryable network and server errors are retried on the current model first. | Rate limits, invalid keys and provider rejections can advance immediately. Network and transient server errors can advance after retries on the current model are exhausted. |
| Always | Other errors can also advance to another member after any applicable retries on the current model. | Other errors can advance immediately, without the usual retries on the current model. |

These group settings do not currently have an **Off** choice. To keep a phone chat
on one model, use a group containing only that model; on Android, selecting a
specific model entry instead of a group also removes the group fallback chain.
Keep other models in your provider catalogue if you need them for separate chats.
A group's current model can change after fallback, including when that chat is
opened again, so check the model and provider shown for the chat.

Each alternative receives the request context needed to answer, using its own
configured provider and credential. Its prices and billing policy can differ;
retries and fallback requests may each be billed by the provider. Review the
members before using a group with multiple models. The Cloud retry button is not
an approval gate for requests to those group members.

**Thinking level (desktop).** The composer's model picker offers a thinking
level for a model of yours where the vendor documents one, in the vendor's own
shape: DeepSeek, Kimi (kimi-k3), Zhipu (GLM-5.2 and 5.3), SiliconFlow and
Volcengine (their DeepSeek-V4 and GLM-5.2 ids, Doubao Seed 2), MiniMax
(M3.1), OpenRouter (the levels its model list gives per model), OpenAI (the
o-series, GPT-5 onwards), Anthropic (Claude 4.6 onwards), Gemini through its
OpenAI layer, xAI (Grok 4.5 onwards), Groq, Mistral, and gpt-oss on Ollama or
vLLM. The levels are the vendor's (`low`, `high`, `max` for DeepSeek, say),
and *Provider default* sends no level at all, so the model thinks the way its
vendor documents. There is no *Off* entry: with these vendors, turning
thinking off is a different switch or a different model. A model nobody
documents a level for shows no control, as do Bailian (its switch is
`enable_thinking`, which cannot be left unsent), LM Studio and a custom
endpoint. A key saved before this build gets the control at the next start.

**Switching nanoMuse Cloud off.** While signed in, the Models page has one
switch, *Use nanoMuse Cloud models*. Off, the Cloud leaves the pickers and the
automatic order, no side call (a chat's title, memory or the hands)
runs on it, and the only thing that spends your allowance is the *Use nanoMuse
Cloud this time* button, each time you tap it. You stay signed in: sync, your
devices and the account page keep working. The Cloud provider cannot be deleted
the way one of yours can (deleting it was the same as signing out); signing out
is under *Settings › nanoMuse Cloud*.

**Without an account.** With a key of your own the app works signed out: chat,
the hands, pictures and clips run on your providers, and the first screen
offers *Use your own API key instead* next to the sign-in. The sign-in is
needed only for nanoMuse Cloud's models, conversation sync and your devices
reaching each other.

**Known limits.** On the iPhone the pictures and clips rows list only your
providers on a DashScope host (Alibaba Cloud Bailian);
a key the catalogue says can draw (OpenRouter, OpenAI, Gemini, a custom
endpoint) is named in one sentence under the picker, *Not offered here: …*,
with where it does work, so you know the phone has not lost it.
On the desktop the hands speak OpenAI's shape, so an Anthropic or native Gemini
key is named under the screen row and not listed; a hands change takes effect
at the hands' next step, no restart. Pictures through a Gemini key go through
Google's OpenAI-compatible layer: `images/generations` accepts
`gemini-2.5-flash-image`, but Google's page does not document `images/edits`
there, so the pose pictures of the avatar studio may not work with a Gemini key.

## Sign in with a plan you already pay for

Some plans sign in directly, with no key to make:

| Plan | Covers | Where the sign-in is |
|---|---|---|
| **ChatGPT** (Plus / Pro / Team) | chat, the hands | Android, iPhone, desktop, web |
| **Claude** (Pro / Max) | chat, the hands | Android, iPhone |
| **Kimi** | chat, the hands | Android, iPhone (device code) |
| **OpenRouter** | chat, the hands, pictures | Android, iPhone (one tap; the key comes back to the app) |

The ChatGPT sign-in uses the authorisation flow of OpenAI's own Codex (web
console: *Connections → Or sign in with a ChatGPT plan*; desktop: the ChatGPT
row under *Settings → nanoMuse Cloud*; phone: *Settings → Providers → OpenAI →
Sign in*). Signed in, it covers chat and the hands only: the Codex backend has
no image or video endpoints, so pictures and clips still want a key.

From a terminal it is the same flow: `nanomuse chatgpt login` opens the page
and waits for the browser to come back, `nanomuse chatgpt status` says who is
signed in and until when, `nanomuse chatgpt logout` forgets it; then
`[llm] provider = "chatgpt"` in `config.toml` (no `base_url`, no `api_key`; an
empty `model` is `gpt-5.6-sol`). The browser has to reach port 1455 on the
machine the runtime runs on; when the runtime is elsewhere, copy the whole
address the browser ends on and give it to the CLI's prompt or to
`POST /api/chatgpt/callback {"url": …}`
([configuration.md](configuration.md#a-chatgpt-plan-instead-of-a-key)).

**A proxy or VPN on the phone can swallow the callback.** On Android the sign-in
page sends the browser back to `http://localhost:1455/auth/callback`, which only
the app on the same phone answers. A proxy or VPN app (Clash, for example) that
routes every address into its tunnel, or whose DNS answers for `localhost`,
takes that address too; the browser shows a connection error and the app keeps
waiting. Two ways through: add `localhost` and `127.0.0.1` to the proxy app's
bypass (direct) list and sign in again, or copy the address of the error page
and paste it into the box that appears under *Sign in* after about ten seconds
(at once when the phone's proxy settings would take the address); *Continue*
hands the code to the waiting sign-in without going through the proxy. The same
box appears for the Anthropic, xAI and OpenRouter sign-ins, which use the same
kind of redirect; the Kimi sign-in uses a device code and does not need it.

**One honest line.** OpenAI's terms cover using a ChatGPT plan inside OpenAI's
own Codex; other apps have had this access cut off before (OpenCode, January
2026). If it stops working, an API key does.

## When the provider cannot be reached

Some networks do not get to `chatgpt.com` at all (the name does not resolve,
the connection times out, TLS fails, an HTML interception page comes back
where JSON was due), and in some regions OpenAI refuses outright (HTTP 403
`unsupported_country_region_territory`). The chat on the phone then shows a
card, not the socket's words: what happened (*chatgpt.com cannot be reached
from this network* or *OpenAI does not serve this region*), what helps (a VPN
on this phone; the app's own proxy under *Settings → Network*; another
provider with a key of your own), a *Try again* button, and the raw line
behind *Details* for a bug report. An expired sign-in (401) reads *The ChatGPT
sign-in is no longer valid* with *Sign in again*; a plan whose window is spent
(a 429 that names a usage limit) reads *The ChatGPT plan has nothing left for
now* with OpenAI's own sentence and when it resets; any other 429 is *Too many
requests at once*. A key of your own that meets the same network trouble gets
the same card with that provider's host in it.

**Settings → Network → HTTP proxy for own providers** (Android and iPhone):
host, port, an optional user name and password; off by default, kept on this
phone only. Only the requests to the providers you added with your own key and
to the ChatGPT plan go through it; nanoMuse Cloud, your computers and the local
network never do. A *Test* row fetches `https://chatgpt.com/` through the proxy
as entered and says whether it got through and in how many milliseconds. The
same setting lives where each app keeps its keys: the phones have it in the
provider form; the desktop under **Settings → nanoMuse Cloud → Network**, one
address (`http://host:port` or `socks5://host:port`) that the app applies to its
host process at the next start (*Restart now* is under the row), so every own
key, the ChatGPT sign-in, the hands' runtime and whatever else the app sends out go
through it, and nanoMuse Cloud never does ([desktop.md](desktop.md)); the web app has the *Proxy* field in the
own-key form; the runtime has `[llm] proxy` in `config.toml`
([configuration.md](configuration.md#llm)).

## Local models

Ollama, LM Studio and vLLM on your own computer work too: pick the preset
(web console: *Connections*; desktop: *Settings → nanoMuse Cloud*; phone:
*Settings → Providers*); the address defaults to the local port
(`http://127.0.0.1:11434/v1`, `:1234`, `:8000`) and no key is needed. They
count as *chat*; the hands need a model that sees, so run a multimodal one
locally (Ollama's `qwen3-vl`, say) and pick it under *Operating the screen*
(web console: the *Hands model* row under *Chat model* lists what the endpoint
serves; pick it there). Pictures and clips need
one of the providers in the table.

## Any other OpenAI-compatible endpoint

Anything that speaks the OpenAI API works; choose *Custom*:

| Field | Value |
|---|---|
| Base URL | the provider's address, usually ending in `/v1`; the runtime, the web console and the desktop refuse an address with `user:pass@` in it (the key has its own field) |
| API key | the key made in the provider's console (a local server may leave it empty) |
| Model | pick from the list after saving; if the endpoint does not list its models, the form asks for their ids (comma-separated) and saves with those |

What a custom endpoint covers is yours to say: nanoMuse takes it for chat, and
the hands, picture and clip models count once their ids are filled in.

**Several at once.** On the desktop app and in the web console the custom
endpoints are a list, not one slot (#294): each one you add keeps its own key
and its own models, and adding a second never replaces the first. On the
desktop, *Settings → Account → Any OpenAI-compatible endpoint* shows one row
per endpoint (its name over its host, with *Change key*, *Rename* and
*Remove*) and an *Add an endpoint* row under them; the model pickers on
*Settings → Models* list each endpoint as a group of its own. In the web
console, *Connections → Chat model* shows one tile per endpoint under *Local or
your own endpoint* with *Add an endpoint* last; the hands, pictures and clips
pickers list the endpoints too ([web.md](web.md#where-it-shows)). A custom
endpoint set before the list existed becomes its first entry, key and all,
the next time the app starts. The phones keep one slot per provider.
