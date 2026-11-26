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
| `NANOMUSE_CLOUD_KEY`, `NANOMUSE_CLOUD_HINT`, `NANOMUSE_CLOUD_CHANNEL`, `NANOMUSE_ONBOARDED` | a hosted runtime (nanoMuse Web) starts signed in: the gateway that made the container hands over the account key (it goes into the vault like one typed in), the masked identifier and channel for the account page, and whether the first run is already done; nothing happens when the vault already holds a key |
| `NANOMUSE_IN_CONTAINER=1` | says the runtime is inside a container (the image sets it; `/.dockerenv` is read too), so `sandbox.mode = auto` treats the container as the box instead of reporting bubblewrap missing |
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
image_model   = ""                 # the older way to name the avatar studio's picture model on this host; see [image] below
video_model   = ""                 # the same for clips
video_base_url = ""                # the asynchronous video API when it is not on this host (a relaying gateway)
```

`proxy` sends this slot's requests (and, for a `chatgpt` slot, the sign-in's token refresh) through that proxy and ignores the environment's `HTTPS_PROXY` for them; empty, the environment decides. It never applies to nanoMuse Cloud or the hub. (The phones have the same switch under *Settings → Network*; [own-key.md](own-key.md#when-the-provider-cannot-be-reached).)

Provider recipes:

| Provider | `model` | `base_url` | Notes |
|---|---|---|---|
| DeepSeek | `deepseek-flash` | `https://api.deepseek.com` | default |
| Kimi (Moonshot) | `kimi-k2.6` | `https://api.moonshot.cn/v1` | |
| 阿里云百炼 (Alibaba Cloud Bailian) | `deepseek-v4.1-flash` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | mainland China; the hands model `qwen3.8-27b` is on the same endpoint |
| GLM (智谱) | `glm-5.3` | `https://open.bigmodel.cn/api/paas/v4` | |
| 豆包 (火山方舟) | your endpoint id | `https://ark.cn-beijing.volces.com/api/v3` | models are versioned deployments; the app lists yours |
| MiniMax | `MiniMax-M3` | `https://api.minimaxi.com/v1` | |
| OpenAI | `gpt-5.4-mini` | `https://api.openai.com/v1` | `provider = "openai_responses"` also works |
| OpenRouter | `deepseek/deepseek-v4.1-flash` | `https://openrouter.ai/api/v1` | outside mainland China; the hands model `qwen/qwen3.8-27b` is on the same endpoint |
| Ollama | `qwen3:8b` | `http://localhost:11434/v1` | `api_key = "ollama"`; see [Local models](#local-models) |
| vLLM / LM Studio | your served name | `http://localhost:8000/v1` | set `tool_mode = "prompt"` if the server ignores `tools` |
| Company gateway | as required | as required | use `extra_headers` / `extra_body`; pick the provider by the API shape the gateway speaks |

The same presets are offered in the web console (*Connections → Chat model*, and on first run), each with a link to where its key comes from; the exact hostnames live in `PROVIDERS` in `nanomuse/server/connections.py`. A `base_url` saved from the app that has no path gains `/v1` (`http://host:8000` → `http://host:8000/v1`); the presets' own hosts are kept as they are. Ollama and custom endpoints may have no key. Custom endpoints added from the web console are a list (`endpoints` in `app-settings.json`, each `{id, label, base_url, api_key, models}` with the key in the vault as `ENDPOINT_<ID>_API_KEY`); a slot set on one of them carries its address and that vault reference, so this file never needs to know about the list ([web.md](web.md#where-it-shows)). A `[llm]` chat model set here on an unlisted host stays as it is; only one set from the app is moved into the list.

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
max_steps            = 30              # model steps per turn before it must wrap up
max_web_calls        = 8               # combined web_search / web_fetch calls per turn; 0 = no cap
# workspace          = "./workspace"   # the only directory the files tool can touch; default ./workspace if present here, else <data_dir>/workspace
extra_roots          = []              # directories outside the workspace the files tool may read and write, e.g. ["~/Documents/notes"]; writable inside the sandbox too
language             = "auto"          # or a fixed language: "English", "中文", ...
max_context_messages = 80
max_context_images   = 4               # screenshots kept in the request: the newest N; 0 keeps all
show_thinking        = false
user_profile         = ""              # free text injected into the system prompt
instructions         = ""              # extra rules appended to the system prompt
```

`max_web_calls` limits combined `web_search` and `web_fetch` dispatches, including failed or denied calls. At the default of 8, both tools are withheld for the rest of the turn once the budget is used, and extra calls in the same model response are refused. Other tools remain available to deliver work. A fresh request or queued user message resets the budget; an answer to `ask_user` does not. Set it to 0 to remove this cap, or raise it for tasks that require more sources. This bounds calls, not elapsed time or research through other tools. Model instructions prohibit bypassing the cap through shell, browser or another service. Sentinel decisions still apply to every dispatched call.

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

### `[memory.openviking]`

The Python runtime can use OpenViking alongside its local explicit memory. This
covers the web console, terminal and devices whose `nanomuse-gateway` forwards
conversations to this runtime. The desktop DSH plugin is configured separately
in [Desktop](desktop.md#openviking-memory).

```toml
[memory.openviking]
enabled = true
url = "http://127.0.0.1:1933"
api_key = "${NANOMUSE_OPENVIKING_API_KEY:-}"
auth_mode = "api_key"
account = ""
user = ""
peer_id = ""
profile_id = ""
capture_conversations = true
personalization = true
personalization_timeout = 15.0
timeout = 5.0
max_chars = 8000
```

Disabled by default; `[memory] enabled = false` disables it too. Restart the
runtime after changing these settings. For trusted identity headers, set
`auth_mode = "trusted"` and supply both `account` and `user`. Use the same server
identity across entry points when they should share memory. API-key mode derives
the identity from the server's credential. `peer_id` optionally identifies this
agent; empty keeps memory in the user's shared space. Credentials belong in the
environment or the vault, such as `{{vault:OPENVIKING_API_KEY}}`.

Environment overrides are `NANOMUSE_OPENVIKING_ENABLED`, `NANOMUSE_OPENVIKING_URL`,
`NANOMUSE_OPENVIKING_API_KEY`, `NANOMUSE_OPENVIKING_AUTH_MODE`,
`NANOMUSE_OPENVIKING_ACCOUNT`, `NANOMUSE_OPENVIKING_USER` and
`NANOMUSE_OPENVIKING_PEER_ID`. No OpenViking SDK is required.

Before a model turn, the agent retries pending writes and recalls relevant
OpenViking memory. Recall is marked as historical evidence, and reads mark the
conversation as having accessed private data. After a completed user turn, it
saves the actual user input and final answer into a separate OpenViking session
and commits it for asynchronous extraction. Background prompts, cancelled turns,
old restored history, tool output, screenshots and reasoning are not captured.
Known vault values and vault references are scrubbed. Each message and recalled
context is capped at `max_chars`. Reads and writes pass through the Sentinel as
moderate-risk, configured outbound operations, named `openviking_recall` and
`openviking_sync`; deny rules and strict-mode approvals still apply.

`<data_dir>/openviking-outbox.db` retains failed writes with owner-only file
permissions. Retries happen at subsequent turns and normal shutdown, with a
total `timeout` budget per operation. Changing the endpoint, credential or
identity leaves the previous queue isolated. A timeout after server acceptance
can result in a repeated message. Accepted commits remain the server's
responsibility; extraction can still fail after acceptance. Local conversation
continues when recall or synchronization is unavailable.

The app's *Memory* page has a separate *OpenViking memories* section. Browse
folders, search, open a file, edit its text or delete that file. It shows the
pending queue and the latest 20 extraction tasks. *Retry pending turns* resends
queued writes; failed extraction tasks already accepted by OpenViking need
investigation on that server. Updates use the file's revision to reject concurrent
changes. Deletion checks the revision before removing one file, without recursive
directory deletion. Files outside the configured user's memory space are refused.

*Automatically save conversations* overrides `capture_conversations` for the
current endpoint and identity, persists across restarts and takes effect without
a restart. Turning it off keeps existing memories and pending writes; recall and
explicit saves remain available. For automation or one-off tasks, send
`capture_memory: false` to the runtime's message API. This skips automatic capture
for that task and prevents the model from using the local or remote memory write
tools. If such a message arrives during a turn, capture is skipped for the whole
turn. This flag is rejected for chats forwarded to another device because the
current hub protocol cannot enforce it there. Omitting the flag keeps existing
clients working. Automation sent as an ordinary user message is still eligible
for extraction unless this flag or the capture switch excludes it.

The model's `openviking_memory` tool can list, search, read, explicitly remember,
correct or delete remote memories. Changes pass through the Sentinel; update and
delete are sensitive actions. Authenticated memory-page actions supply approval
for that one action, while explicit deny rules still win. The model cannot change
the capture switch. The local `remember`, `recall`, `forget` tools and tidy history
continue to manage SQLite separately.

With `personalization = true`, the runtime also maintains a personal profile in
`openviking-outbox.db`. A persisted owner ID and memory space identify the profile;
rotating the OpenViking credential keeps it and the capture switch. An empty
`profile_id` allocates an ID for the configured endpoint and account/user identity.
Set `profile_id` to an existing owner's ID only for a deliberate owner migration.
Changing the endpoint or account/user with no explicit ID creates another owner.
Legacy profiles migrate only from the exact current connection's namespace.
Outbound queues remain bound to their original connection and credential, so a
credential change never retargets pending conversations. This derived profile is
local to this runtime and complements OpenViking's remote memories.

After an eligible completed turn, user evidence is queued on disk. While the
runtime is idle, a background worker calls its currently configured conversation
model to extract up to six proposed facts. The reply does not wait for that model
call. Each attempt has a `personalization_timeout` budget. Failed attempts retry
after 30 seconds, up to five attempts; the memory page can retry failed jobs.
Shutdown cancellation leaves the job queued. Learning needs the runtime to stay
online; short-lived CLI processes may leave jobs for a later running instance.
Each space holds up to 1,000 pending jobs; a job retains at most the last eight
eligible user messages, capped at 8,000 characters each and 32,000 in total.
Only proposals supported by a verbatim user quote are accepted. Explicit facts
retain that quote as their value; inferred preferences stay as candidates until
confirmed in the memory page. Assistant replies and restored conversation history
are not sources for this profile. Extraction failures leave the existing profile
intact. Manual review invalidates previously queued proposals, so stale learning
cannot undo a correction. Turning capture off pauses queued learning too.

The profile distinguishes personal facts, preferences, projects, temporary states
and experiences. Scoped facts participate only in matching queries, with a small
set of technical terms also recognizing coding and deployment questions. Temporary
states expire after seven days by default, with a 30-day maximum. Experiences
default to 90 days, with a 180-day maximum. Other proposed lifetimes are optional
and capped at 365 days. One-off wording such as "this time" does not establish a
lasting preference. Novel wording and topic matching still depend on the model.

Active facts are supplied before later replies, including in new conversations.
Current user instructions take precedence, and the profile takes precedence over
older remote evidence. It grants no permissions and cannot override the Sentinel.
Candidates and expired facts do not participate. Explicit corrections can replace
earlier facts while retaining their history; an owner-confirmed fact requires an
explicit correction before automatic replacement.

In *Memory → OpenViking memories → Personal profile*, inspect source quotes,
scope and expiry, confirm candidates, edit facts or stop using them. Reviews check
versions to reject concurrent changes. Stopping use retains a rejection marker
to prevent the same value being learned again, including under a renamed topic;
the owner can restore it explicitly. It does not delete remote OpenViking files
or archived conversations. To erase those, manage them separately. Setting
`personalization = false` disables profile learning and profile context. Turning
off automatic capture stops new learning while keeping existing facts available;
background turns and `capture_memory: false` turns do not teach the profile.

#### Memory spaces

*Memory → Memory spaces* starts with *Personal* and *Work*. Add a named project
space and start a conversation from it. The choice is persisted with that thread;
existing conversations and old clients keep `personal`. Spaces separately bind
profile facts, explicit local memory tools and remote retrieval. They do not
inherit another space's personal preferences. Non-personal spaces use a derived
OpenViking peer ID, while Personal keeps the configured peer and existing data.

Peer-scoped capture tags user messages with that peer ID and creates sessions
with peer extraction enabled and self extraction disabled. Session routes do
not use the actor-peer request header for extraction. The runtime checks the
stored policy before writing or committing, including on retries; incompatible
sessions stay queued instead of being committed to shared memory. Servers that
cannot report this policy cannot accept peer-scoped capture. Previously extracted
files are not moved or deleted by this fix and require separate review.
Each space also binds its files, uploads, library and Shell/Python working directory.
Personal keeps `agent.workspace`; other spaces use
`<data_dir>/space-workspaces/<owner-hash>/<space>`. Existing shared files are not moved.
Disabling OpenViking preserves these directories and their owner binding. File tools reject
paths and symbolic links escaping their root. Chat commands use inherited Linux
[Landlock filesystem restrictions](https://docs.kernel.org/userspace-api/landlock.html),
with read-only system libraries and writes limited to the selected workspace. They require
ABI 3 or newer and refuse execution when unavailable, including unsupported platforms.
Runtime data must be outside readable workspace and system roots. Working bubblewrap
network isolation is retained as an outer layer; Landlock itself does not isolate the
network. `sandbox.mode = off` does not disable the space filesystem boundary.
Configured extra roots and shared login directories are not granted to space-bound commands.
A runtime with OpenViking off and no saved additional spaces retains its configured command
sandbox, including on macOS and Windows. Existing saved spaces keep the stricter boundary
when OpenViking is turned off.

External connectors, coding agents, browser/device control, skills, goals, contacts and
calendar have no space identity and are exposed only in Personal. Non-personal prompts
also omit personal goals, calendar, contacts and skills. Public web search and fetch are
available in every space. This does not turn a single-owner runtime into a hosted tenant
sandbox; authenticated management still belongs to its owner.

The web page's **Enable memory** switch is persisted per owner and space, defaults
to on, and controls assistant use independently of automatic capture. Off pauses
local and remote recall, model memory tools, capture, queued sync and profile
learning. Personal memory also stays out of newly generated ideas and feed posts,
and automatic memory tidy-up pauses. It preserves saved data, queued work and the capture preference across
restarts. Authenticated memory controls remain usable for inspection and removal.
The global `memory.enabled = false` setting takes precedence. Already submitted
remote extraction can finish, but its results are not recalled while the space
is off. Current chat history and manually configured app style remain available;
the switch does not erase those sources. File boundaries are enforced independently.

Remote retrieval uses `find` within the selected memory root and validates hit
URIs. Turning OpenViking off leaves scoped conversations readable, with their
memory tools unavailable until the integration returns.

All spaces belong to one runtime owner and use its runtime token. They are logical
memory boundaries, not isolated operating-system users or hosted tenants. Other
tools still follow their own Sentinel and filesystem policies. Clients connected
to this runtime share its spaces. The standalone desktop DSH plugin retains its
separate memory configuration and does not load these local profiles. Current
conversation sync does not carry space identity, so non-personal conversations
stay on this runtime rather than being synced as personal chats to older clients.


#### Reviewed fact copies

`POST /api/memory/spaces/{space}/facts` accepts `action` (`preview`, `apply`,
`status`, `unblock`), `term`, optional `replacement` and `aliases`, and the preview `revision` for
`apply`. This authenticated control passes through the Sentinel as `memory_facts`;
explicit deny rules still win. It is available with memory off and without OpenViking
for local notes. A fragment contains 3 to 500 characters; replacements at most 500.
Preview binds the revision to the space, current managed state and exact requested
change, including the aliases. At most 20 aliases of 3 to 500 characters are accepted.
Profile versions sharing a field, kind and scope are linked automatically after a text
match; previews label linked versions. Other wording requires explicit aliases and owner
review. Applied exclusions share a `fact_id`, preserved in backups. Scans fail rather than truncate above the backup limits, 1,000 local notes
or 1,000 undo entries. They do not search ordinary workspace files.

Owner-reviewed exclusions and replacement values live in `memory-usage.db`, scoped
by owner and space. Local recall, remote recall and model browsing/reading, memory
writes, capture and profile learning filter records containing retired fragments.
Authenticated controls can still inspect them. Unrelated text in a filtered record
is also unavailable to the assistant until the file is corrected. Literal matching
does not detect arbitrary paraphrases. Retired fragments remain in the exclusion
list itself so returning records can be blocked. Backups include these rules; clear
removes them, and restore keeps existing rules when the same fragment is present.

Reconciliation removes matching profile revisions, local undo records, queued
evidence and identifiable archived sessions. Replacement edits current facts and
remote file text, deletes matching archived evidence, and records current values
as owner-confirmed overrides. It invalidates queued profile learning so stale jobs
cannot reverse a review. Other spaces and untracked legacy archives remain separate.
Network changes across stores are not atomic; exclusions are saved before mutations
and survive partial failures. A durable report in `memory-usage.db` records per-source
scanned, matched and changed counts and completion status. `status` returns the most recent
report; the last 20 operations per space are retained. Interrupted operations become
incomplete on the next status read. Inspect remaining copies before retrying, rather than
replaying an old preview. Reports omit fact text; chat timelines, audit logs, untracked
archives and workspace files stay outside reconciliation.

The memory-off fast path recognizes explicit Chinese and English requests to
remember, recall or forget and answers without calling a model or tools. It does
not classify every possible paraphrase. An execution restriction therefore defaults to
blocking storage and action tools while memory is off. File, shell and Python tools require
an explicit file, document, command or coding task in the current user request; an existing
approval cannot override the restriction. Public web search, fetch and asking the user
remain available. This conservative rule may require rephrasing a legitimate task to name
the file or code work.

#### Memory backups

Within a space, download a backup before enabling *Clear after exporting*. Export
includes all stored profile revisions, rejection markers, current local notes,
visible remote memory files, recorded captured turns, and pending sync/learning
evidence. It excludes credentials, chat timelines, local undo logs and Sentinel
audit logs. Recorded turns cover captures made after this feature was installed;
older remote sessions are known only where retained pending/commit records identify
them. Backups fail rather than truncate above 1,000 remote tree entries, 32,000
characters in a remote file, or 10 MB in total.

Clear checks the exported revision, requires conversations and known extraction
tasks to finish, disables capture, invalidates learning, deletes recorded remote
sessions and visible remote memory files, then erases the space's local facts,
undo history, vectors and pending jobs. Sessions whose ownership was never recorded,
other remote peers, local chat timelines and audit logs are managed separately.
This is logical deletion, not a promise to erase storage backups or free pages.
Network failures can leave a partially cleared remote space with capture off;
retain the downloaded backup, export the remaining state and inspect before retrying.

Restore requires the same owner ID and space, validates paths and the checksum,
adopts facts and creates missing remote memory files. It refuses to overwrite
different existing remote text and keeps current profile topics. It does not
replay captured conversations or queued jobs, recreate original remote archives,
or turn capture on. The exported turn evidence remains in the downloaded backup.
These authenticated controls use the Sentinel; explicit deny rules still apply.

Deleting an extracted memory does not delete archived conversations. Reprocessing
an archive can recreate it. Clearing a chat, disabling this integration or deleting
a local memory does not erase server memories or the outbox.

For a real check, tell the agent a distinctive project name and identifier. Wait
for the server's commit task to complete, open a new runtime thread and ask for
that identifier. Inspect both the stored memory and the recall request. An
answer in the original thread does not establish cross-session recall.

To inspect remote recall directly in a local development server, use the same
identity as the runtime:

```sh
curl --fail-with-body -sS http://127.0.0.1:1933/api/v1/search/search \
  -H 'Content-Type: application/json' \
  -H 'X-OpenViking-Account: personal' \
  -H 'X-OpenViking-User: me' \
  -d '{"query":"project identifier","mode":"context","context_type":"memory","max_tokens":1000,"rewrite":false}'
```

Replace the identity headers when needed. Context mode uses `context_type` to
select memories and does not accept `target_uri`; the legacy `/search/find`
fallback uses `target_uri` instead. An HTTP 200 response with no entries means
no relevant indexed memory was found, not a connection failure. Commit acceptance
alone does not mean extraction has completed.

In Docker, `127.0.0.1` refers to the container. Set a URL reachable from that
container; a host service bound only to loopback is not reachable just by using
`host.docker.internal`. Use an appropriate network configuration or an
authenticated service endpoint. The running container must include this version
of the Python code; rebuilding the desktop plugin alone does not update it.

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

Who answers `web_search`. DuckDuckGo needs nothing and is the default, but it is scraped rather than served: it rate-limits and breaks now and then. For searches that always work, name a provider with an API: [Brave Search](https://brave.com/search/api/) or [Tavily](https://app.tavily.com/) with a key, [You.com](https://you.com/platform/api-keys) with or without one, or a [SearXNG](https://docs.searxng.org/) instance you run yourself (with `json` among its `search.formats`). The same choice is on the phone under *Connections → Web search*, where the key goes to the vault as `SEARCH_API_KEY` and *Test* runs one search.

```toml
[connectors.search]
provider = "duckduckgo"          # duckduckgo | brave | tavily | you | searxng
api_key  = "{{vault:SEARCH_API_KEY}}"   # brave / tavily, and you if you have one: nanomuse vault set SEARCH_API_KEY
base_url = ""                    # searxng: your instance, e.g. "http://127.0.0.1:8080"
fallback = true                  # false: a failed search fails instead of going to DuckDuckGo
```

You.com without a key goes to `api.you.com` and allows 100 searches a day per address, with no account; past that the search says so and DuckDuckGo answers once. With a key it goes to `ydc-index.io`, the keyed Search API with higher limits; the Sentinel shows whichever host the search really uses. Requests to You.com carry the user agent `youdotcom-integration/nano-muse-nanomuse`, at the vendor's request, so they can tell nanoMuse's traffic apart; nothing else is sent, and no other provider gets it.

Whichever is picked, a search that fails (a lapsed key, a rate limit, an instance that is down) is answered by DuckDuckGo instead, once, with a note on top of the results saying so, so the task goes on (the query then reaches DuckDuckGo's host as well as the one you chose; set `fallback = false` under `[connectors.search]` if that must not happen); `nanomuse doctor` reports a provider that is missing what it needs. The `region` argument of the tool (`cn-zh`, `us-en`) is passed to every provider in its own terms. The provider's host is a destination you chose, so a search after private data was read does not need approval the way an unknown host would (see [taint tracking](sentinel.md#taint-tracking)); `web_fetch` of a result still does.

Web tools pause for the rest of a turn after three consecutive errors or empty search
results. The known DuckDuckGo `No results found` response is treated as an empty result,
not proof that a flight, route or service does not exist. Transport errors stay errors.

`web_fetch` checks DNS on every redirect and refuses non-public destinations, even after
you approve a site's outbound request. A proxy returning virtual addresses from
`198.18.0.0/15` will therefore block public pages too. The error explains this possibility.
Configure real DNS resolution for the runtime or its proxy; keep internal-address
protection enabled. Approving a domain does not override the DNS check.

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

A command that needs a key takes it through `env`, and the key itself lives in the vault: write `env = { AMAP_MAPS_API_KEY = "{{vault:AMAP_KEY}}" }` and the reference is resolved when the server is started, never written to disk or shown in the app. A server added from the app (the Connections page) works the same way without you doing anything: each `env` value you type is stored in the vault under `MCP_<SERVER>_<KEY>` (upper-cased, `amap` with `AMAP_MAPS_API_KEY` becomes `MCP_AMAP_AMAP_MAPS_API_KEY`) and `app-settings.json` keeps `{{vault:...}}`; removing the server removes those entries. A value typed as a reference already is kept as typed. A plain value in `config.toml` still works, and the Connections page marks the server so you can move it.

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
update_check     = true          # Settings → About says when a newer release is out (the download index, then GitHub Releases; once a day)
start_grace      = 4             # seconds the services may take before the app answers anyway
```

`update_check` asks the download mirror's index (`nanomuse.cn/dl/index.json`) and, when that does
not answer, `api.github.com`, for the latest release once a day (sooner on *Check now*; a check
that failed, as when the runtime came up before its network, is tried again after an hour) and shows
the version under *Settings → About* with a link to the release page; nothing is downloaded and
nothing about the install is sent beyond the runtime's version in the request's `User-Agent`. `NANOMUSE_NO_UPDATE_CHECK=1` turns it off too, and a hosted
web session (a runtime started with `NANOMUSE_CLOUD_KEY`) never checks; its operator updates it.

These settings apply to the Python runtime. The Windows desktop shell checks separately
after startup and every six hours. Its saved automatic download switch is on by default,
but metered or unknown networks wait for a manual download. See [desktop.md](desktop.md#updating-on-windows).

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
