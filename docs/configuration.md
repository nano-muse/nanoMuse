# Configuration

nanoMuse reads one TOML file. `nanomuse config init` writes a commented copy of [`config/config.example.toml`](../config/config.example.toml) to `config/config.toml`; `nanomuse config show` prints the effective settings with secrets masked.

Search order:

1. `--config PATH` / `NANOMUSE_CONFIG`
2. `./config/config.toml`
3. `~/.nanomuse/config.toml`

Any string value may contain `${VAR}` or `${VAR:-default}`; it is replaced with the environment variable when the file is loaded, so API keys never need to be written down. `api_key`, `address` and `password` may also be `{{vault:NAME}}`: the value is read from the encrypted vault when the client is built, never shown to the model.

Three layers, later ones win: the file, then environment overrides, then whatever was changed in the app's *Connections* screen (`<data_dir>/app-settings.json`: model, email servers, browser switch, MCP servers added from the phone). That last file only ever refers to secrets as `{{vault:NAME}}`.

A key the runtime has no setting for (a misspelt `modle`, a key from another version) is ignored and the default applies; the loader says so in the log with the key's path (`llm.modle`), and `nanomuse doctor` lists such keys as a problem. Free-form tables (`[llm.extra_headers]`, an MCP server's `env`) and the `[channels.<name>]` tables of [channels.md](channels.md) take any key.

## Environment overrides

These win over the file. They cover the settings people change most often and what Docker needs.

| Variable | Setting |
|---|---|
| `NANOMUSE_LLM_PROVIDER`, `NANOMUSE_LLM_MODEL`, `NANOMUSE_LLM_BASE_URL`, `NANOMUSE_LLM_API_KEY`, `NANOMUSE_LLM_TOOL_MODE`, `NANOMUSE_LLM_VISION`, `NANOMUSE_LLM_IMAGE_MODEL`, `NANOMUSE_LLM_VIDEO_MODEL`, `NANOMUSE_LLM_VIDEO_BASE_URL` | `[llm]` (`video_base_url`: the asynchronous video API on another host than the chat model's; a relaying host such as the showcase gateway names itself here) |
| `DEEPSEEK_API_KEY`, `OPENAI_API_KEY` | used as `llm.api_key` when it is empty: DeepSeek's for a `*.deepseek.com` `base_url`, OpenAI's for every other host (OpenAI itself, OpenRouter, a gateway, vLLM) |
| `NANOMUSE_DATA_DIR` | `data_dir` (default `~/.nanomuse`) |
| `NANOMUSE_WORKSPACE` | `agent.workspace` (default: `./workspace` when the current directory has one, else `<data_dir>/workspace`) |
| `NANOMUSE_SENTINEL_MODE` | `sentinel.mode` |
| `NANOMUSE_SEARCH_PROVIDER`, `NANOMUSE_SEARCH_API_KEY`, `NANOMUSE_SEARCH_BASE_URL` | `[connectors.search]` |
| `NANOMUSE_SERVER_HOST`, `NANOMUSE_SERVER_PORT`, `NANOMUSE_SERVER_TOKEN` | `[server]` |
| `NANOMUSE_BROWSER_ENABLED=1` | `browser.enabled = true` (only ever turns it on; the browser Docker image sets it; the phone sets it through `NANOMUSE_DEVICE`) |
| `NANOMUSE_BROWSER_BACKEND` | `browser.backend`: `auto`, `playwright` or `device` |
| `NANOMUSE_GUI_ENABLED=1`, `NANOMUSE_GUI_PROVIDER`, `NANOMUSE_GUI_MODEL`, `NANOMUSE_GUI_BASE_URL`, `NANOMUSE_GUI_API_KEY` | `[gui]`: operating the phone, and the model that does it |
| `NANOMUSE_IMAGE_PROVIDER`, `NANOMUSE_IMAGE_MODEL`, `NANOMUSE_IMAGE_BASE_URL`, `NANOMUSE_IMAGE_API_KEY`; the same with `VIDEO` | the [`[image]` and `[video]` slots](#image-and-video): where pictures and clips come from |
| `NANOMUSE_VAULT_KEY` | Fernet key for the vault (default: `<data_dir>/vault.key`) |
| `NANOMUSE_CLOUD_BASE_URL`, `NANOMUSE_CLOUD_REQUIRED`, `NANOMUSE_CLOUD_SYNC` | `[cloud]`: the relay a hosted runtime signs in against, whether a nanoMuse Cloud account is required, and the default for *Sync conversations between my devices* (`sync`, on unless set to `0`; the person's switch in *Settings → Data controls*, once touched, is what counts; [every-device.md](every-device.md#the-same-conversations-everywhere)) ([cloud.md](cloud.md); the relay's own variables are in [cloud/README.md](../cloud/README.md)) |
| `NANOMUSE_HUB_NAME` | `hub.name`, what this device is called on the other devices |
| `NANOMUSE_CODING_HOME` | where the coding CLIs' own homes (`~/.codex`, `~/.claude`, …) are looked for, default the user's home ([coding-agents.md](coding-agents.md)) |
| `NANOMUSE_LOG_LEVEL` | `log_level` |

## `[llm]`

```toml
[llm]
provider      = "openai"           # "openai" = Chat Completions, "openai_responses" = Responses API;
                                   # "chatgpt" = a ChatGPT plan (below); or a catalogue id such as "bailian"
model         = "deepseek-flash"
base_url      = "https://api.deepseek.com"
api_key       = "${DEEPSEEK_API_KEY}"
max_tokens    = 4096
temperature   = 0.3
timeout       = 180                # seconds per request
max_retries   = 5                  # exponential back-off on 429 / 5xx / timeouts
stream        = true
tool_mode     = "auto"             # "auto" | "native" | "prompt" — see below
vision        = "auto"             # pictures attached in chat go to the model: "auto" | "on" | "off"
pass_reasoning = false             # send reasoning_content back with assistant turns (some DeepSeek endpoints)
extra_headers = {}                 # e.g. { "X-End-User-Id" = "nanomuse" }
extra_body    = {}                 # e.g. { "thinking" = { "type" = "enabled" } }
proxy         = ""                 # an HTTP(S) or SOCKS proxy for this slot only, e.g. "http://127.0.0.1:7890"
```

`proxy` sends this slot's requests (and, for a `chatgpt` slot, the sign-in's token refresh) through that proxy and ignores the environment's `HTTPS_PROXY` for them; empty, the environment decides. It never applies to nanoMuse Cloud or the hub. (The phones have the same switch under *Settings → Network*; [own-key.md](own-key.md#when-the-provider-cannot-be-reached).)

Provider recipes:

| Provider | `model` | `base_url` | Notes |
|---|---|---|---|
| DeepSeek | `deepseek-flash` | `https://api.deepseek.com` | default |
| Kimi (Moonshot) | `kimi-k2.6` | `https://api.moonshot.cn/v1` | |
| 阿里云百炼 (Alibaba Cloud Bailian) | `deepseek-v4.1-flash` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | mainland China; the hands model `qwen3.8-27b` is on the same endpoint |
| GLM (智谱) | `glm-5.2` | `https://open.bigmodel.cn/api/paas/v4` | |
| 豆包 (火山方舟) | your endpoint id | `https://ark.cn-beijing.volces.com/api/v3` | models are versioned deployments; the app lists yours |
| MiniMax | `MiniMax-M3` | `https://api.minimaxi.com/v1` | |
| OpenAI | `gpt-5.6-sol` | `https://api.openai.com/v1` | `provider = "openai_responses"` also works |
| OpenRouter | `deepseek/deepseek-v4.1-flash` | `https://openrouter.ai/api/v1` | outside mainland China; the hands model `qwen/qwen3.8-27b` is on the same endpoint |
| Ollama | `qwen3:8b` | `http://localhost:11434/v1` | `api_key = "ollama"`; see [Local models](#local-models) |
| vLLM / LM Studio | your served name | `http://localhost:8000/v1` | set `tool_mode = "prompt"` if the server ignores `tools` |
| Company gateway | as required | as required | use `extra_headers` / `extra_body`; pick the provider by the API shape the gateway speaks |

The same presets are offered in the web console (*Connections → Chat model*, and on first run), each with a link to where its key comes from; the exact hostnames live in `PROVIDERS` in `nanomuse/server/connections.py`. A `base_url` saved from the app that has no path gains `/v1` (`http://host:8000` → `http://host:8000/v1`); the presets' own hosts are kept as they are. Ollama and custom endpoints may have no key.

`provider` may also be an id from the provider catalogue, [`nanomuse/llm/providers.json`](../nanomuse/llm/providers.json) (`bailian`, `deepseek`, `moonshot`, `zhipu`, `openrouter`, `openai`, `gemini`, …), in which case `base_url` and, when empty, `model` fill in from the catalogue and only `api_key` is yours. The catalogue also says what each provider's key covers (chat, the hands, pictures, clips); `GET /api/providers` on the server reports which slots use which provider and what that leaves uncovered, and the app shows one sentence for a feature nothing covers ([own-key.md](own-key.md)).

### A ChatGPT plan instead of a key

```toml
[llm]
provider = "chatgpt"     # the sign-in from `nanomuse chatgpt login`; no base_url, no api_key
model    = ""            # empty → gpt-5.6-sol (also gpt-5.4, gpt-5.4-mini)
```

A person with a ChatGPT plan (Plus, Pro, Team) can let nanoMuse use it for chat and for the hands, the way OpenAI's own Codex CLI does: `nanomuse chatgpt login` opens OpenAI's sign-in page in the browser (PKCE, the same client id, scopes and redirect as Codex), waits for the callback on port 1455 of the machine the runtime runs on, and stores the tokens in `<data_dir>/chatgpt.json` (mode 0600), refreshed before they expire. `nanomuse chatgpt status` says who is signed in and until when (never the tokens); `nanomuse chatgpt logout` deletes the store. The same three steps are on the web console's *Connections* screen (*Or sign in with a ChatGPT plan*), which calls `POST /api/chatgpt/login`, `GET /api/chatgpt/status` and `POST /api/chatgpt/logout` on the runtime ([web.md](web.md)). After a sign-in nothing switches by itself: set `provider = "chatgpt"` here, pick *Use it for the chat* on the web, or `PUT /api/connections/llm {"provider": "chatgpt"}`. `[gui] provider = "chatgpt"` works the same way for the hands.

What it covers: chat and vision (the hands read screenshots). The Codex backend has no image or video endpoints, so pictures and clips still want a key: an `[image]` or `[video]` slot below, or a chat provider whose host draws. `base_url` and `api_key` in a `chatgpt` slot are ignored, with a warning in the log.

**The honest line**, printed on every login: *OpenAI's terms cover using a ChatGPT plan inside OpenAI's own Codex; other apps have had this access cut off before (OpenCode, January 2026). If it stops working, an API key does.*

**The callback has to reach the runtime.** OpenAI sends the browser back to `http://localhost:1455/auth/callback`, so the browser must be on the machine the runtime runs on (or forward that port to it). When it is not (a runtime on a server, the console open on a laptop), the sign-in page still works; the browser then lands on an address that does not answer. Copy that whole address (`http://localhost:1455/auth/callback?code=…&state=…`) out of the address bar and give it to the runtime: the CLI asks for it when the port is busy or nothing arrives in time; with `--json` it reads one line from stdin; the web console's card has a box for it; the server takes `POST /api/chatgpt/callback {"url": "<the address>"}` while a login started from `/api/chatgpt/login` is waiting. A `state` that is not the pending login's is refused (400 `state_mismatch`) and nothing is exchanged. `nanomuse chatgpt proxy` serves the sign-in as a loopback OpenAI-compatible endpoint (`GET /v1/models`, `POST /v1/chat/completions`, `GET /v1/usage`, a local bearer token) for other programs on the same machine; `--proxy` (or `[llm] proxy`) sends its upstream calls through a proxy.

**What is left of the plan.** OpenAI counts a plan's use in two windows (a few hours and a week) and says so in the response headers of every Codex call (`x-codex-primary-used-percent`, `…-window-minutes`, `…-reset-after-seconds`, the same for `secondary`) and on `GET https://chatgpt.com/backend-api/wham/usage`, the endpoint Codex CLI's `/status` reads. `nanomuse chatgpt usage` prints both windows (`--json` for the raw `{label, plan, limits}`), the runtime serves them at `GET /api/chatgpt/usage` for the console, and the loopback proxy at `GET /v1/usage`; the runtime also keeps the headers of the last call (`CodexClient.limits`). Nothing is cached longer than a minute.

**When it fails.** A Codex call that cannot get through is one of a few sentences, never the socket's text: *chatgpt.com cannot be reached from this network* (DNS, connect, TLS, a timeout, or an HTML page where JSON was due: an interception page), *OpenAI does not serve this region* (HTTP 403 `unsupported_country_region_territory`), *The ChatGPT sign-in is no longer valid. Sign in again* (401), *The ChatGPT plan has nothing left for now* (a 429 that names a usage limit, with OpenAI's own words and `Retry-After` after it) and *Too many requests at once* (any other 429). The loopback proxy returns them with a machine code in `error.code` (`unreachable`, `region_blocked`, `not_signed_in`, `quota`, `rate_limited`, `upstream`) so a client can act on them; the phones show the same sentences as a card ([own-key.md](own-key.md#when-the-provider-cannot-be-reached)).

### Tool calling modes

| `tool_mode` | What happens |
|---|---|
| `auto` (default) | The API's function calling. If the endpoint *rejects* the `tools` field (Ollama for a model without a tool template ("does not support tools"), vLLM started without a tool parser), nanoMuse logs one warning and describes the tools in the prompt for the rest of the run. |
| `native` | Always the function-calling API; a rejection is an error. |
| `prompt` | Tools are described in the system prompt and calls are parsed from `<tool_call>` blocks. The only mode that works with endpoints that silently *ignore* `tools` (no error, the model just never calls anything); some "agent app" gateways do this. |

### Pictures

Pictures the user attaches in chat are sent to the model as image content (Chat Completions `image_url` parts, Responses `input_image`), scaled to 1568 px on the long side first. `vision = "auto"` (the default) sends them and, when the endpoint refuses a request with images (DeepSeek, Ollama for a model without vision: "model does not support multimodal requests"), sends the same request with the text only, drops pictures for the rest of the run, and the app tells the user once; the message the model gets then says which pictures it cannot see, so it does not describe what it never saw. `on` sends them always and a refusal is an error. `off` never sends them: the model gets the file names, and text files, PDFs and spreadsheets it reads with `files` either way. Vision models that work here: GPT-4o and later, Claude through an OpenAI-compatible gateway, Gemini, Qwen-VL, `qwen3.8-*`, `gemma3` and `llava` on Ollama. Some ids are known in advance, so no request is wasted: DeepSeek models are text-only unless the id contains `v4.1`, `vision` or `ocr`; `qwen*-vl` and `qwen3.8-*` see.

### Local models

Ollama serves an OpenAI-compatible API at `http://localhost:11434/v1`; models with a tool template (Qwen 3, Llama 3.1+, Mistral, DeepSeek-R1 distills) call tools natively, the rest work through `auto`'s prompt fallback. [`scripts/provider_check.py`](../scripts/provider_check.py) runs five everyday tasks (chat, a calculation through `python_execute`, writing a file, remembering a preference, a multi-step job) against any model; results on an RTX 4070 (12 GB), Ollama 0.34:

| Model | Tool calling | provider_check | Notes |
|---|---|---|---|
| `qwen3:8b` | native (also 5/5 with `tool_mode = "prompt"`) | 5/5 | the default preset; 7–20 s per task |
| `llama3.2:3b` | native | 5/5 | often writes the call as a bare JSON object in the text and double-escapes newlines in file content; both are repaired (see below) |
| `gemma3:4b` | prompt, via the `auto` fallback | 5/5 | Ollama rejects `tools` for it; emits ```` ```tool_call ```` fences, which the prompt parser accepts |
| DeepSeek V4.1 Flash (hosted) | native | 5/5 | 1–4 s per task |

Small models bend the protocol in predictable ways, and nanoMuse meets them halfway rather than failing the task: a reply that is a bare or fenced JSON object naming one of the tools (with an arguments object) counts as a tool call in every mode; JSON strings may contain real newlines; `files.write` turns a one-line text with two or more spelled-out `\n` into lines (code, which has real newlines, is never touched). A quoted JSON object with other keys stays text.

Set `max_tokens` to what the model can produce in one turn (4096 is fine for these) and keep `agent.max_context_messages` modest: a local 8B model with an 8k context window fills up fast once tool results start coming back.

Models that emit `<think>…</think>` inside the content are handled: the reasoning is separated and shown only with `agent.show_thinking = true`.

## `[image]` and `[video]`

Where the avatar studio's pictures and the avatar's clips come from when it is not the chat model's host. Both slots empty (the default) follows one order (the Models contract, 0.1.41): the chat provider's own picture model when it has one (the account's relay, Alibaba Cloud Bailian, and any catalogue provider with `image`: its `defaults.image`; `[llm] image_model` / `video_model` still name another), else the account's relay when you are signed in to nanoMuse Cloud, even while the chat model is elsewhere, else nothing. Clips the same way: the picture host when it speaks the video API, else the relay under the account key when signed in. Set a slot to draw somewhere else, or to draw at all when the chat model is DeepSeek, a ChatGPT plan or a local model and you are not signed in:

```toml
[image]
provider = "zhipu"                    # a catalogue id: bailian | zhipu | siliconflow | volcengine | openai | gemini | openrouter | xai
model    = ""                         # empty → the catalogue's default for that provider
api_key  = "{{vault:IMAGE_API_KEY}}"  # empty → the chat model's key when the host is the same
```

```toml
[video]
provider = "bailian"                  # clips speak Bailian's video API this round; the other vendors' video models are behind task APIs not wired yet
model    = ""                         # empty → the catalogue's default (wan2.2-i2v-flash)
api_key  = "{{vault:VIDEO_API_KEY}}"
```

`base_url` may be given instead of `provider` for a host the catalogue does not list; `api_key` goes to that host (a `[video]` host of its own gets the `[video]` key, not the picture host's). A capability nothing configured covers is unavailable with one sentence that names who could (*Pictures need a provider with image models: Alibaba Cloud Bailian, Zhipu GLM, SiliconFlow or Volcengine Ark (how: docs/own-key.md)* on the mainland, OpenRouter, OpenAI, Google Gemini or xAI Grok elsewhere, in English or Chinese after `[agent] language`), in the avatar studio, under *Making pictures* and *Making clips* in Connections, and in `GET /api/providers`. The sentences and the capabilities come from the catalogue, so they change when it does.

The app layer sets the same slots: `PUT /api/connections/image` and `PUT /api/connections/video` take `provider` (a catalogue id, or `openai` / `openai_responses` with a `base_url`), `model` (empty: the catalogue's default), `base_url` and `api_key` (into the vault as `IMAGE_API_KEY` / `VIDEO_API_KEY`, or a `{{vault:NAME}}` reference kept as written; `""` removes it), write the `image` / `video` objects of `app-settings.json` with the same four keys, layered over this file like the rest, and answer the slot as set plus what it resolves to (`effective_provider`, `effective_model`, `effective_source`: `app`, `config`, `chat` or `cloud`); `GET /api/connections/image` and `/video` answer the same, and `GET /api/connections` carries both. All four empty clears the slot. A provider the catalogue lists without the capability is refused with 400 and the one sentence (`DeepSeek has no image models; Pictures need …`), as is the ChatGPT sign-in; a local server or a host the catalogue does not know passes, since it has what you installed. The web console's *Making pictures* and *Making clips* rows are these routes ([web.md](web.md)).

## `[agent]`

```toml
[agent]
name                 = "nanoMuse"      # what the agent calls itself (the app's profile overrides this)
max_steps            = 30              # tool calls per turn before it must wrap up
# workspace          = "./workspace"   # the only directory the files tool can touch; default ./workspace if present here, else <data_dir>/workspace
language             = "auto"          # or a fixed language: "English", "中文", ...
max_context_messages = 80
max_context_images   = 4               # screenshots kept in the request: the newest N; 0 keeps all
show_thinking        = false
user_profile         = ""              # free text injected into the system prompt
instructions         = ""              # extra rules appended to the system prompt
```

With `language = "auto"` the system prompt names the reply language and tells the model to answer in it: the language of the client's screens when the client sends one with the message (the web console does, as `language` on `POST /api/threads/{id}/send`; a `task` over the hub may), else the language of the latest user message, detected by script. A generic "reply in the user's language" instruction turned out to be unreliable with some models; naming it works. A fixed `language` wins over both.

`max_context_images` is for the hands. A run on a screen appends a screenshot per step and the whole conversation goes up again on every step, so a dozen full-size pictures had passed the relay's body limit (413 `too_large`, 0.1.37). Only the newest four travel now, each downscaled to at most two megapixels; the older ones are replaced by a one-line note so the model still knows a screenshot was there. The desktop app's harness keeps the same budget on its side.

## `[sync]`

```toml
[sync]
side_chats = false   # off: only the main conversation travels between devices
```

The account-wide sync switch is in the app (*Data controls → Sync*); this is the per-device default for *Also sync side chats*. Off, only the main conversation is pushed and pulled; side chats stay on the device that made them and no other device's arrive. On, this device's side chats go to the account and the other devices' come here. The person's choice in the app is kept in `sync.json` and wins over this file. [every-device.md](every-device.md#the-same-conversations-everywhere) has the whole picture.

## `[cloud]` and `[hub]`

```toml
[cloud]
base_url = "https://cloud.nanomuse.cn"   # a relay you run yourself goes here
required = true
sync = true
models = true        # the account's models as a source; the console's "Use nanoMuse Cloud models"

[hub]
enabled = true
remote_control = true
name = ""            # empty: the host name
```

`[cloud]` is the relay this runtime signs in to ([cloud.md](cloud.md)): `base_url` is its public address (your own relay's, after [self-hosting.md](self-hosting.md)); `required = false` lets the first run finish without an account, for a runtime that uses no relay at all; `sync` is the default of the account-wide *Data controls → Sync* switch, and the person's choice, once made, is what counts; `models = false` (the console's *Use nanoMuse Cloud models* switch, kept in app-settings) takes the account's models out of the automatic order of the hands, pictures and clips and out of the providers' listing while the sign-in stays, so nothing spends the allowance but an explicit *Use nanoMuse Cloud this time*. The account key itself is `NANOMUSE_CLOUD_KEY` in the vault.

`[hub]` is this computer as one of the account's devices ([hub.md](hub.md)): `enabled` joins the hub whenever the account is signed in; `remote_control = false` answers other devices with `info` and nothing else; `name` is what the other devices call this one (empty: the host name). `device_id` is per installation and written by the app.

## `[sentinel]`

```toml
[sentinel]
mode               = "ask"           # ask | strict | auto
always_ask_tools   = ["send_email", "shell"]
always_allow_tools = []
deny_tools         = []
taint_tracking     = true
egress_allowlist   = ["duckduckgo.com", "*.duckduckgo.com", "wikipedia.org", "*.wikipedia.org",
                      "github.com", "*.github.com", "*.githubusercontent.com", "pypi.org", "*.pypi.org"]
audit_file         = ""              # default <data_dir>/audit.jsonl

[[sentinel.rules]]                   # first match wins; values are glob patterns matched against str(arg)
tool   = "shell"
match  = { command = "*rm -rf*" }
action = "deny"                      # allow | ask | deny
reason = "recursive deletes are not allowed"
```

How the pieces combine is described in [sentinel.md](sentinel.md).

## `[sandbox]`

```toml
[sandbox]
mode = "auto"                        # auto | bwrap | off
```

On Linux with [bubblewrap](https://github.com/containers/bubblewrap) installed (`apt install bubblewrap`, `dnf install bubblewrap`), every `shell` and `python_execute` call runs in its own namespace: the workspace and `agent.extra_roots` are the only writable places, your home directory is not there, `/tmp` is private, and there is no network unless the call was assessed as needing it. `auto` uses it when it works here and says so in the log when it does not; `bwrap` insists (`nanomuse doctor` fails otherwise); `off` runs commands unboxed, with the scrubbed environment only. `share_read_only` lists directories the box may read (a CLI you want the agent to use: `["~/.nvm"]` for node and lark-cli), `share` those a tool must also write (its login: `["~/.lark-cli", "~/.local/share/lark-cli"]`); a shared directory under your home is visible at the same place under the box's home too, so a tool that looks in `$HOME` finds it. Details and what changes for the Sentinel in [sentinel.md → The sandbox](sentinel.md#the-sandbox).

## `[memory]`

```toml
[memory]
enabled            = true
max_inject         = 20        # memories injected into the system prompt per turn
embeddings         = "auto"    # recall by meaning: auto | on | off
embedding_model    = ""        # empty → the endpoint's default (see below)
embedding_base_url = ""        # empty → the model's endpoint and key (llm.base_url / llm.api_key)
embedding_api_key  = ""        # a key of its own, "{{vault:EMBEDDINGS_API_KEY}}" from the app
```

Recall is by keyword (rare words weigh more, Chinese is matched by character pairs) and, with an embedding endpoint, by meaning too: every memory is embedded once (the vector is kept in `memory.db` next to a hash of the text, so a changed line is embedded again and a switch back to a model is free), the message is embedded per turn, and the memories closest in meaning are fused with the keyword ranking, so "写邮件给房东" recalls "the landlord is Bob Li" though they share no word. Any OpenAI-compatible `/embeddings` works: OpenAI (`text-embedding-3-small` is the default there and on most gateways), [Ollama](https://ollama.com) with an embedding model pulled (`ollama pull qwen3-embedding:0.6b`, the default on `:11434`, small, reads Chinese and English), OpenRouter (`openai/text-embedding-3-small`). DeepSeek has none, so with it point `embedding_base_url` somewhere that has (Ollama next to DeepSeek is the usual pairing) or leave recall by keyword.

`auto` tries the endpoint once per start and falls back to keyword recall when the call fails, saying why in the log: one failed call, not one per turn; an endpoint that was unreachable is tried again after five minutes. `on` insists: recall still falls back, but the failure is a warning and `nanomuse doctor` fails on it. `off` never embeds. `embedding_api_key` empty means the model's own key on its own endpoint; set from the app it is a `{{vault:EMBEDDINGS_API_KEY}}` reference. The gateway headers in `llm.extra_headers` go to the model's endpoint only, not to another one named here. *Connections → Recall by meaning* in the app sets all of this and tests it; `nanomuse memory recall "…"` shows what would be recalled, with each memory's closeness.

## `[skills]`

```toml
[skills]
enabled  = true
dir      = ""                        # your skills; empty → <data_dir>/skills
disabled = ["inbox-triage"]          # built-in ones to leave out of the model's list
```

A skill is a folder with a `SKILL.md` (YAML front matter with `name` and `description`, then the steps in Markdown) in the [Agent Skills](https://agentskills.io) format, so skills written for other agents work here. nanoMuse reads one more key, `channel`: which rung of the [ladder](gui.md#the-ladder) the skill works on: `api` (an MCP server or connector), `cli`, `web` (a fetch), `browser`, `gui` (the phone's screen; `app-only` is accepted) or `mixed`. A `gui` skill is marked *on the phone's screen* in the agent's index, so it knows the job needs the phone before it starts; `metadata.channel` works too for skills that must stay strictly in the shared format. Eleven are built in (`weekly-review`, `trip-plan`, `inbox-triage`, `compare-options`, `meeting-prep`; `phone-messages` for the phone's screen; five for Chinese services that need no screen: `feishu` through lark-cli, `tencent-meeting` through tmeet, `amap` through the 高德 MCP server, `kuaidi100` through the 快递100 server, and `train-tickets`, which searches through the 12306 server and books on the phone only when told to; [services.md](services.md) says which have been run where); a folder in `dir` with the same name as a built-in replaces it. The model gets the index (name and description of every enabled skill) in its system prompt and reads a skill's steps with the `skills` tool when a request fits; `/name` at the start of a chat message runs one directly. Saving or removing a skill from chat is a sensitive call: it asks first, whatever the Sentinel mode. Skills switched off in the app are remembered in `app-settings.json`; the list here and that one are merged. Inside the [sandbox](sentinel.md#the-sandbox) a skill's folder (its scripts and reference files) is visible read-only. See [the app → Skills](app.md#skills) and `nanomuse skills` in the [CLI](cli.md#skills).

## Connectors

### Email

```toml
[connectors.email]
enabled       = true
imap_host     = "imap.gmail.com"
imap_port     = 993
smtp_host     = "smtp.gmail.com"
smtp_port     = 587
smtp_starttls = true
address       = "{{vault:EMAIL_ADDRESS}}"
password      = "{{vault:EMAIL_PASSWORD}}"
scrub_secrets = true   # remove one-time codes and reset links before the model reads a mail
```

Store the values with `nanomuse vault set EMAIL_ADDRESS` and `nanomuse vault set EMAIL_PASSWORD`. `read_emails` marks the conversation as tainted; `send_email` is in `always_ask_tools` by default.

### Calendar

Any calendar that offers a private iCalendar link (Google (*Settings → Integrate calendar → Secret address in iCal format*), Outlook (*Shared calendars → Publish*), iCloud (*Share Calendar → Public Calendar*), Fastmail, Nextcloud) or an `.ics` file on disk. `webcal://` links are fetched over HTTPS. The feed text is cached in `<data_dir>/calendar-cache.json` (mode 0600) so the agenda is there at startup and between refreshes.

```toml
[connectors.calendar]
enabled         = true
refresh_minutes = 30          # how often feeds are re-read in the background
day_start       = "09:00"     # working hours, for "when am I free"
day_end         = "18:00"

[[connectors.calendar.feeds]]
name = "Work"
url  = "{{vault:CALENDAR_WORK}}"   # the link is the secret: nanomuse vault set CALENDAR_WORK

[[connectors.calendar.feeds]]
name = "Family"
url  = "~/family.ics"
```

The `calendar` tool reads (agenda, search, free time) and *drafts*: an event it proposes is written as `calendar/<date>-<title>.ics` in the workspace, and the app shows it as a card with an *Add to calendar* button. It never writes to your calendar itself. Today's and tomorrow's events are in the system prompt; the Feed shows them under *Today*. `nanomuse calendar add NAME URL` does the same as the Connections screen.

### Contacts

Who is who. The agent looks people up before writing to them and never guesses an address; the approval card for an email names the recipient from the address book and warns when it does not know them. Sources are `.vcf` files (Google Contacts (*Export → vCard*), iCloud, Outlook (*People → Manage → Export*), Nextcloud, an iPhone (*Contacts → select all → Share*) and Android all export one), as a path, an upload from the phone (kept under `<data_dir>/contacts/`), or a link (kept in the vault). vCard 2.1, 3.0 and 4.0 are read, including Apple's `item1.` label groups and quoted-printable names from old phones. Link text is cached in `<data_dir>/contacts-cache.json` (mode 0600).

```toml
[connectors.contacts]
enabled = true                    # on by default: the agent's own book needs no source

[[connectors.contacts.sources]]
name = "Google"
url  = "~/Downloads/contacts.vcf"

[[connectors.contacts.sources]]
name = "Nextcloud"
url  = "{{vault:CONTACTS_NEXTCLOUD}}"   # a link, kept in the vault: nanomuse vault set CONTACTS_NEXTCLOUD
```

Besides the sources there is always *My contacts*, `<data_dir>/contacts.vcf`: the people the agent was told about in chat ("the landlord is Bob Li, bob@example.com") through `contacts` action=add, the only book it writes to, and the only one it can remove people from. The `contacts` tool searches by name, nickname, company, email or phone (every word must match, prefixes count, a character inside a Chinese name counts); a look-up is private data and taints the conversation. `nanomuse contacts search | list | add | sources | add-source | remove-source` from the CLI.

### Web search

Who answers `web_search`. DuckDuckGo needs nothing and is the default, but it is scraped rather than served: it rate-limits and breaks now and then. For searches that always work, name a provider with an API: [Brave Search](https://brave.com/search/api/) or [Tavily](https://app.tavily.com/) with a key, or a [SearXNG](https://docs.searxng.org/) instance you run yourself (with `json` among its `search.formats`). The same choice is on the phone under *Connections → Web search*, where the key goes to the vault as `SEARCH_API_KEY` and *Test* runs one search.

```toml
[connectors.search]
provider = "duckduckgo"          # duckduckgo | brave | tavily | searxng
api_key  = "{{vault:SEARCH_API_KEY}}"   # brave / tavily: nanomuse vault set SEARCH_API_KEY
base_url = ""                    # searxng: your instance, e.g. "http://127.0.0.1:8080"
fallback = true                  # false: a failed search fails instead of going to DuckDuckGo
```

Whichever is picked, a search that fails (a lapsed key, a rate limit, an instance that is down) is answered by DuckDuckGo instead, once, with a note on top of the results saying so, so the task goes on (the query then reaches DuckDuckGo's host as well as the one you chose; set `fallback = false` under `[connectors.search]` if that must not happen); `nanomuse doctor` reports a provider that is missing what it needs. The `region` argument of the tool (`cn-zh`, `us-en`) is passed to every provider in its own terms. The provider's host is a destination you chose, so a search after private data was read does not need approval the way an unknown host would (see [taint tracking](sentinel.md#taint-tracking)); `web_fetch` of a result still does.

## `[triggers]`

Triggers are standing instructions that start work when something happens: a mail arrives, a calendar event is about to start, a program calls a webhook (see [the app](app.md#triggers)). They are set in chat or under *Upcoming*, not in the config file; this section only tunes how they are watched.

```toml
[triggers]
mail_poll_minutes = 5    # how often the inbox is looked at while a mail trigger is active
hook_min_seconds  = 10   # deliveries to one webhook closer together than this get HTTP 429
```

Mail triggers need the [email connector](#email); event triggers need a [calendar](#calendar). Triggers live in `<data_dir>/triggers.db`.

### Browser

```toml
[browser]
enabled    = true      # pip install "nanomuse[browser]" && playwright install chromium
backend    = "auto"    # auto | playwright | device — the phone's own WebView when a nanoMuse app is connected, Chromium otherwise
profile    = ""        # mobile | desktop | "" (mobile on the phone, desktop on a computer)
headless   = true      # Playwright only
timeout_ms = 30000
```

Logins made in Chromium live in `<workspace>/browser-profile/` and survive a restart; on the phone they live in the app's WebView. The two backends, the take-over, the logged-in `fetch` and what cannot log in inside a WebView: [browser.md](browser.md).

### Hands on this computer (`[hands]`)

```toml
[hands]
enabled         = false    # the switch is Devices → Hands on this computer in the app
backend         = "auto"   # auto | desktop | pyautogui | xdotool (X11) — desktop: the desktop app's own hands (auto takes them when the app set NANOMUSE_OPERATOR_URL)
mode            = "auto"   # auto | screen | window — window: one app's window on macOS, events to its process, your mouse untouched; auto = window on macOS once an app is named
coords          = "pixels" # pixels | norm1000 — what the model's x, y mean: pixels of the picture it was shown (default), or a 0–1000 grid over it
max_image_width = 1600
settle_s        = 0.6
```

The picture the model sees is the unit: `computer_screen` says its size on the first line and in a closing *Coordinates:* line, and `computer_act` takes `x`, `y` (or a `box`) in it; the runtime maps them to the hands' own pixels once, whatever the display's scale. The picture is the screen capped at `max_image_width`, then snapped to the 28-pixel grid Qwen resizes to, so the model sees exactly what it is pointing at ([gui.md](gui.md#hands-on-the-computer-the-picture-is-the-unit)).

The model, the step cap and the sensitive words are `[gui]`'s. Window mode, the per-app ask (*Let <Muse> use <App>?*, a `computer_app:<id>` grant) and the macOS permissions: [every-device.md](every-device.md#hands-on-this-computer).

### The phone (`[gui]`)

With this on, the agent can look at a connected phone's screen and tap, type and swipe in its apps: the way to reach 12306, 微信 or 支付宝, which have no API. Off by default; the *Phone* card on the Connections screen is the same switch. How it works and what Sentinel does with it: [gui.md](gui.md).

```toml
[gui]
enabled          = false
provider         = "openai"          # the operator's own model; openai | openai_responses | chatgpt | a catalogue id
model            = ""                # empty: the main [llm] model does it — it must take images, the screen is a picture
base_url         = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key          = "{{vault:GUI_API_KEY}}"
max_steps        = 0                 # the most one phone_task may take; 0 = no cap
device_timeout_s = 20.0              # how long to wait for the phone to answer
reconnect_grace_s = 30.0             # how long a running task waits for a phone whose connection dropped; 0 = give up at once
sensitive_words  = ["确认支付", "立即付款", "转账", "提交订单", "发送", "删除", "pay now", "place order", "send", "delete"]  # a tap on these asks first; a shortened sample, the default has 22 words
```

`base_url` and `api_key` fall back to `[llm]` when empty. An empty `model` follows one order (the Models contract, 0.1.41): with the relay as the chat model, the relay's hands model (`qwen3.8-27b` unless `/v1/models` names another), not the chat model (the chat default reads pictures, but the hands want the model trained to point at things on a screen); with an own provider the catalogue lists with `vision`, that provider's own hands model (`defaults.hands`, `qwen3.8-27b` on Bailian, `glm-4.6v` on Zhipu) on the chat key; with a provider that cannot see (a local server by its catalogue id or host) and an account signed in, the relay's hands model under the account key, the chat model staying where it is; else the chat model, as on a host the catalogue does not list. An explicit `model` always wins. A key is only needed when the operator's `base_url` is a different service. Traces of every phone task go to `<data_dir>/phone-traces/` (the last 200 are kept; `nanomuse phone traces`).

The app layer sets this slot through `PUT /api/connections/gui`, which takes `provider` as `PUT /api/connections/llm` does: a protocol (`openai`, `openai_responses`), `chatgpt`, or a catalogue id such as `bailian`, which brings its endpoint along (`base_url` may stay empty); an id the catalogue lacks, or one whose protocol the runtime does not speak, is 400 with the choices. The answer (and `GET /api/connections` → `gui`) carries `provider` as set, `provider_id` (the catalogue entry a protocol plus URL stands for), `effective_model` and `effective_source` (`gui`, `chat` or `cloud`).

### MCP servers

Anything that speaks the [Model Context Protocol](https://modelcontextprotocol.io) becomes a set of tools named `<server>__<tool>`, each passing through Sentinel with the risk level you assign.

```toml
[[mcp.servers]]
name    = "filesystem"
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-filesystem", "./workspace"]
risk    = "moderate"             # safe | moderate | sensitive

[[mcp.servers]]
name               = "calendar"
url                = "http://localhost:8000/mcp"   # streamable HTTP; falls back to SSE
risk               = "sensitive"
egress             = true         # counts as network egress for taint tracking
reads_private_data = true         # taints the conversation when called

# one tool of a server may differ from the server's defaults
[mcp.servers.tools.list_events]
risk               = "moderate"
[mcp.servers.tools.delete_event]
risk               = "sensitive"
reads_private_data = false
```

`tools` is optional and per tool name (without the `<server>__` prefix); anything not set falls back to the server's values. It is how the phone's own tools get their defaults: on a phone the app's capabilities appear as the server `device` without any configuration ([device.md](device.md)), with the per-tool table from `nanomuse/runtime.py`.

A server that does not answer is logged and skipped, and the agent starts without its tools; the line in the log names the server and the transport's error with every URL query value masked (`?key=***`) and the vault's secrets redacted, so a refused key does not end up in `logs/`.

Three Chinese services the built-in skills know come as MCP servers, and `config/config.example.toml` has the block for each: 高德地图 (hosted, `AMAP_KEY` in the vault), 12306 (`npx -y 12306-mcp`, no key; trains, query only) and 快递100 (hosted, `KUAIDI100_KEY`; parcels, paid per tracking number). Which of them have actually been run inside the phone's root file system, and what else is out there: [services.md](services.md).

## `[server]`

```toml
[server]
host             = "127.0.0.1"   # 0.0.0.0 to reach it from your phone on the same network
port             = 8787
auth             = true          # access token required (in the QR code / link)
token            = ""            # empty → generated once, stored in <data_dir>/server_token
approval_timeout = 3600          # seconds an approval card waits before counting as "deny"
cors_origins     = []            # only for the Vite dev server, e.g. ["http://localhost:5173"]
max_upload_mb    = 25            # largest file the app may attach to a message
update_check     = true          # Settings → About says when a newer release is out (GitHub Releases, every 6 h)
start_grace      = 4             # seconds the services may take before the app answers anyway
```

`update_check` asks `api.github.com` for the latest release at most every six hours and shows
the version under *Settings → About* with a link to the release page; nothing is downloaded and
nothing about the install is sent. `NANOMUSE_NO_UPDATE_CHECK=1` turns it off too, and a hosted
web session (a runtime started with `NANOMUSE_CLOUD_KEY`) never checks; its operator updates it.

## Where things live

| Path | Contents |
|---|---|
| `~/.nanomuse/` (`data_dir`) | everything below |
| `memory.db`, `goals.db` | SQLite |
| `vault.enc`, `vault.key` | encrypted secrets and the key (or `NANOMUSE_VAULT_KEY`) |
| `audit.jsonl` | append-only audit log |
| `approvals.json` | permissions you granted for 24 hours or always (tool + target, scope, expiry) |
| `app-settings.json` | what was changed in the app's Connections screen, layered over `config.toml` (no secrets, only `{{vault:NAME}}` references) |
| `chatgpt.json` | the ChatGPT sign-in's tokens (mode 0600; `nanomuse chatgpt logout` removes it) |
| `sessions/` | CLI conversation history |
| `skills/<name>/SKILL.md` | your skills (the Agent Skills format); a name that matches a built-in replaces it |
| `threads/`, `profile.json`, `ideas.json`, `server_token`, `logs/` | app state |
| `./workspace` (`agent.workspace`) | files the agent reads and writes; `screenshots/` holds the last 400 screens a phone sent (the phone traces point at them) |
