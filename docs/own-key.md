# Bring your own key


nanoMuse is free and non-profit. The model behind it costs money, and the
developer pays for a starting allowance per account (the app shows the relay's
current figures). When it is gone, there are two ways on that need nothing
from nanoMuse: a key of your own at a model provider, or a plan you already
pay for — ChatGPT, Claude, Kimi — signed in from the app.

Every client reads the same list of providers, with what each one covers:
**chat**, **the hands** (a model that sees screenshots), **pictures** (the
avatar studio) and **clips** (the avatar's short videos). A feature no
configured provider covers is simply not offered, with one sentence saying
which providers would — nothing breaks.

Your sign-in, your invite code and your devices are not affected: the account
stays, only the model provider changes. Nothing you say passes through nanoMuse
Cloud once your own key or plan is in use.

## Where you are decides who comes first

| | First | What one key there covers |
|---|---|---|
| Mainland China | **Alibaba Cloud Bailian** | chat, the hands, pictures and clips — all four under one key |
| Everywhere else | **OpenRouter**, then **OpenAI** | chat, the hands and pictures; clips are Bailian only for now |

Bailian only signs up accounts with a mainland Chinese identity; outside, one
OpenRouter account puts hundreds of models behind one key, pay as you go.
Beyond the first pick, every provider below works on its own or beside another
— DeepSeek for the chat and Zhipu for pictures, say.

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
| Ollama / LM Studio / vLLM (on your machine) | ● | | | | both | no key |

Only Bailian has a dot under *Clips* because nanoMuse's clip generation speaks
Bailian's video API; the other vendors' video models sit behind their own task
APIs, not wired this round. Under *Pictures*, OpenRouter goes through its
Image API with models such as `openai/gpt-image-2`; Gemini uses
`gemini-2.5-flash-image`.

The table is the repository's catalogue,
[`nanomuse/llm/providers.json`](../nanomuse/llm/providers.json) — every client
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
- **Volcengine Ark.** [console.volcengine.com](https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey) — enable the models you want in Ark, then create a key; base URL `https://ark.cn-beijing.volces.com/api/v3`.
- **MiniMax.** Mainland edition at [platform.minimaxi.com](https://platform.minimaxi.com/user-center/basic-information/interface-key), base URL `https://api.minimaxi.com/v1`; the global base URL is `https://api.minimax.io/v1`.
- **OpenRouter.** Sign in at [openrouter.ai](https://openrouter.ai/) with Google, GitHub or an e-mail address, add credit under *Credits*, create a key under *Keys*; it starts with `sk-or-v1-`. *Settings → Limits* puts a monthly cap on a key.
- **OpenAI.** [platform.openai.com](https://platform.openai.com/api-keys), base URL `https://api.openai.com/v1`.
- **Anthropic.** [platform.claude.com](https://platform.claude.com/settings/keys). nanoMuse speaks Anthropic's own API; no compatibility layer is needed.
- **Google Gemini.** [aistudio.google.com/apikey](https://aistudio.google.com/apikey), base URL `https://generativelanguage.googleapis.com/v1beta/openai`.
- **xAI, Groq, Mistral.** A key from each console; base URLs `https://api.x.ai/v1`, `https://api.groq.com/openai/v1`, `https://api.mistral.ai/v1`.

**Paste it into nanoMuse.**

- Phone: *Set it up* on the allowance card opens the provider form pre-filled; or *Settings → Providers → Add*, pick the provider, paste the key, save.
- Desktop: *Set it up* on the allowance card opens *Settings → nanoMuse Cloud* at the provider's row; or paste the key on that provider's row under *Ways on* there. The address is already filled in.
- Web console: *Set it up* on the allowance card opens *Connections* with the provider chosen; or *Connections → Chat model*, click the provider, paste the key, save.
- A runtime of your own: `[llm] provider = "bailian"` (any id from the table) and `api_key` in `config.toml`; the address and the default model fill in from the catalogue. Pictures or clips from another provider are an `[image]` / `[video]` block ([configuration.md](configuration.md#image-and-video)).

**Use it for.** Once the key is saved, a card asks what this key should handle:
one switch per job the provider can do (chat, operating the screen, making
pictures, making clips), all on. *Use it* moves those rows to this provider, on
the catalogue's default model for each job (or the first model of its list that
fits); *Not now* changes nothing, and so does a switch you turned off. Signed
in, the card says nanoMuse Cloud keeps the rest. Every row can be changed later
under *Settings › Models* (web console: *Connections*).

## Which model does what

*Settings › Models* (Android: the card at the top of Settings; iPhone: the
first card of Settings; desktop: right after General; web console: the *Chat
model*, *Hands model*, *Making pictures* and *Making clips* cards on
*Connections*) has one row per job:

| Row | What it does | Who is listed |
|---|---|---|
| Chat | The model that talks with you. | nanoMuse Cloud's chat models while signed in and switched on, then every provider of yours with chat models |
| Operating the screen | Looks at the screen and acts for you. Needs a model that can see images. | nanoMuse Cloud's hands model, then your providers' models that see images; disabled on the iPhone (*Not on iPhone*) |
| Making pictures | Portraits of your Muse and the pictures you ask for. | nanoMuse Cloud, then your providers with image models |
| Making clips | Short clips of your Muse. | nanoMuse Cloud, then your providers with video models (Bailian) |

Each row shows `provider · model` and opens a picker: the *nanoMuse Cloud*
group first while signed in, its recommended model marked, then one group per
provider of yours holding only the models that fit. A provider without the
capability does not appear in that row at all. A row nothing covers shows the
one sentence naming who could, and *Add a provider*. A chat pick is the default
for new chats and moves the main chat (*Applies to the main chat and to new
chats; a side chat keeps its model.*): the main chat is the one conversation the
Chat tab always shows and is never new, so it would otherwise stay on the
provider it started with; a side chat already open keeps its model. The same
on the phones and the desktop. On the iPhone, where a model group of yours can
carry a default thinking level (*All settings › Model Groups*), the main chat
takes that level along when it follows the pick, as a new chat and the chat's
own picker do.

**Automatic.** The screen, pictures and clips rows open with an *Automatic*
entry that says what it gives right now (*Currently nanoMuse Cloud ·
qwen3.8-27b*, say). Pick it and the row forgets any choice made there and
follows one order: the chat model's provider when it is one of yours and can do
the job (its catalogue default), else nanoMuse Cloud while signed in and switched on, else the
first provider of yours that can. A choice you made always wins; nanoMuse Cloud
never steps in front of a provider you chose. Each device keeps its own choice,
because keys never leave the device where they were entered.

**No silent fallback.** When a model of your own fails under a turn, nothing
switches by itself: the error card offers *Use nanoMuse Cloud this time*
(signed in only), which runs that one turn on the account's model and changes
no row. The desktop shows the same button after a failed studio round and a
failed set of clips.

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
automatic order, no side call (a chat's title, memory, a portrait, the hands)
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

**Known limits.** On the iPhone the pictures and clips rows list, besides
nanoMuse Cloud, only your providers on a DashScope host (Alibaba Cloud Bailian);
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
host process at the next start — *Restart now* is under the row — so every own
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
(web console: type its id on the *Hands model* row). Pictures and clips need
one of the providers in the table.

## Any other OpenAI-compatible endpoint

Anything that speaks the OpenAI API works — choose *Custom*:

| Field | Value |
|---|---|
| Base URL | the provider's address, usually ending in `/v1` |
| API key | the key made in the provider's console (a local server may leave it empty) |
| Model | pick from the list after saving; if the endpoint does not list its models, the form asks for their ids (comma-separated) and saves with those |

What a custom endpoint covers is yours to say: nanoMuse takes it for chat, and
the hands, picture and clip models count once their ids are filled in.
