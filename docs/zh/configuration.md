# 配置

nanoMuse 只读一个 TOML 文件。`nanomuse config init` 把带注释的 [`config/config.example.toml`](../../config/config.example.toml) 抄一份写到 `config/config.toml`；`nanomuse config show` 打印实际生效的设置，机密值打码。

查找顺序：

1. `--config PATH` / `NANOMUSE_CONFIG`
2. `./config/config.toml`
3. `~/.nanomuse/config.toml`

任何字符串值都可以写 `${VAR}` 或 `${VAR:-default}`，加载文件时会替换成环境变量，所以 API key 不必落在文件里。`api_key`、`address` 和 `password` 还可以写成 `{{vault:NAME}}`：值在构建客户端时才从加密的保险库里读出，从不给模型看。

三层设置，后面的覆盖前面的：先是这个文件，然后是环境变量覆盖，最后是 App 里「连接」屏幕改过的东西（`<data_dir>/app-settings.json`：模型、邮件服务器、浏览器开关、从手机上添加的 MCP 服务器）。最后这个文件里提到机密，一律只写 `{{vault:NAME}}`。

运行时没有对应设置的键（拼错的 `modle`、来自另一个版本的键）会被忽略，取默认值；加载时会在日志里带着键的路径（`llm.modle`）说明，`nanomuse doctor` 把这类键列为问题。自由格式的表（`[llm.extra_headers]`、MCP 服务器的 `env`）和 [channels.md](channels.md) 里的 `[channels.<name>]` 表接受任何键。

## 环境变量覆盖 {#environment-overrides}

这些优先于文件。它们覆盖了人们最常改的设置，以及 Docker 需要的东西。

| 变量 | 设置 |
|---|---|
| `NANOMUSE_LLM_PROVIDER`、`NANOMUSE_LLM_MODEL`、`NANOMUSE_LLM_BASE_URL`、`NANOMUSE_LLM_API_KEY`、`NANOMUSE_LLM_TOOL_MODE`、`NANOMUSE_LLM_VISION`、`NANOMUSE_LLM_IMAGE_MODEL`、`NANOMUSE_LLM_VIDEO_MODEL`、`NANOMUSE_LLM_VIDEO_BASE_URL` | `[llm]`（`video_base_url`：异步视频 API 在聊天模型以外的另一台主机上；转发用的主机，比如展示站的网关，会在这里报上自己的名字） |
| `DEEPSEEK_API_KEY`、`OPENAI_API_KEY` | `llm.api_key` 为空时顶上：`base_url` 是 `*.deepseek.com` 用 DeepSeek 的，其他所有主机（OpenAI 自己、OpenRouter、网关、vLLM）用 OpenAI 的 |
| `NANOMUSE_DATA_DIR` | `data_dir`（默认 `~/.nanomuse`） |
| `NANOMUSE_WORKSPACE` | `agent.workspace`（默认：当前目录下有 `./workspace` 就用它，否则 `<data_dir>/workspace`） |
| `NANOMUSE_SENTINEL_MODE` | `sentinel.mode` |
| `NANOMUSE_SEARCH_PROVIDER`、`NANOMUSE_SEARCH_API_KEY`、`NANOMUSE_SEARCH_BASE_URL` | `[connectors.search]` |
| `NANOMUSE_SERVER_HOST`、`NANOMUSE_SERVER_PORT`、`NANOMUSE_SERVER_TOKEN` | `[server]` |
| `NANOMUSE_BROWSER_ENABLED=1` | `browser.enabled = true`（只能打开，不能关；浏览器版 Docker 镜像会设它；手机通过 `NANOMUSE_DEVICE` 设它） |
| `NANOMUSE_BROWSER_BACKEND` | `browser.backend`：`auto`、`playwright` 或 `device` |
| `NANOMUSE_GUI_ENABLED=1`、`NANOMUSE_GUI_PROVIDER`、`NANOMUSE_GUI_MODEL`、`NANOMUSE_GUI_BASE_URL`、`NANOMUSE_GUI_API_KEY` | `[gui]`：操作手机，以及干这件事的模型 |
| `NANOMUSE_IMAGE_PROVIDER`、`NANOMUSE_IMAGE_MODEL`、`NANOMUSE_IMAGE_BASE_URL`、`NANOMUSE_IMAGE_API_KEY`；把 `IMAGE` 换成 `VIDEO` 也一样 | [`[image]` 和 `[video]` 槽位](#image-and-video)：图片和短视频从哪里来 |
| `NANOMUSE_VAULT_KEY` | 保险库的 Fernet 密钥（默认：`<data_dir>/vault.key`） |
| `NANOMUSE_CLOUD_BASE_URL`、`NANOMUSE_CLOUD_REQUIRED`、`NANOMUSE_CLOUD_SYNC` | `[cloud]`：托管运行时登录的那个中继、是否必须有 nanoMuse Cloud 账号，以及「在我的设备之间同步对话」的默认值（`sync`，除非设为 `0` 否则是开的；「设置 → 数据控制」里的开关只要动过一次，就以它为准；[every-device.md](every-device.md#the-same-conversations-everywhere)）（[cloud.md](cloud.md)；中继自己的变量在 [cloud/README.md](../../cloud/README.md)） |
| `NANOMUSE_HUB_NAME` | `hub.name`，这台设备在其他设备上叫什么 |
| `NANOMUSE_CLOUD_KEY`、`NANOMUSE_CLOUD_HINT`、`NANOMUSE_CLOUD_CHANNEL`、`NANOMUSE_ONBOARDED` | 托管的运行时（nanoMuse Web）一启动就是登录状态：创建容器的网关交来账号 key（和手动输入的一样进保险库）、账号页要显示的打码标识和渠道，以及首次运行是否已经完成；保险库里已经有 key 时什么都不做 |
| `NANOMUSE_IN_CONTAINER=1` | 说明运行时在容器里（镜像会设置它；`/.dockerenv` 也会被读取），于是 `sandbox.mode = auto` 把容器当作箱子，而不是报告缺少 bubblewrap |
| `NANOMUSE_CODING_HOME` | 到哪里找编程 CLI 各自的家目录（`~/.codex`、`~/.claude`……），默认是用户的家目录（[coding-agents.md](coding-agents.md)） |
| `NANOMUSE_LOG_LEVEL` | `log_level` |

## `[llm]` {#llm}

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

`proxy` 让这个槽位的请求（`chatgpt` 槽位还包括登录的令牌刷新）走那个代理，并对它们忽略环境里的 `HTTPS_PROXY`；留空则由环境决定。它从不作用于 nanoMuse Cloud 和 hub。（手机上同样的开关在「设置 → 网络」；[own-key.md](own-key.md#when-the-provider-cannot-be-reached)。）

各服务商的写法：

| 服务商 | `model` | `base_url` | 说明 |
|---|---|---|---|
| DeepSeek | `deepseek-flash` | `https://api.deepseek.com` | 默认 |
| Kimi（月之暗面） | `kimi-k2.6` | `https://api.moonshot.cn/v1` | |
| 阿里云百炼 | `deepseek-v4.1-flash` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 中国大陆；手的模型 `qwen3.8-27b` 在同一个端点上 |
| GLM（智谱） | `glm-5.3` | `https://open.bigmodel.cn/api/paas/v4` | |
| 豆包（火山方舟） | 你的接入点 id | `https://ark.cn-beijing.volces.com/api/v3` | 模型是带版本的部署；App 会列出你的 |
| MiniMax | `MiniMax-M3` | `https://api.minimaxi.com/v1` | |
| OpenAI | `gpt-5.4-mini` | `https://api.openai.com/v1` | `provider = "openai_responses"` 也可以 |
| OpenRouter | `deepseek/deepseek-v4.1-flash` | `https://openrouter.ai/api/v1` | 中国大陆以外；手的模型 `qwen/qwen3.8-27b` 在同一个端点上 |
| Ollama | `qwen3:8b` | `http://localhost:11434/v1` | `api_key = "ollama"`；见[本地模型](#local-models) |
| vLLM / LM Studio | 你起的服务名 | `http://localhost:8000/v1` | 服务器不理会 `tools` 的话，设 `tool_mode = "prompt"` |
| 公司网关 | 按要求 | 按要求 | 用 `extra_headers` / `extra_body`；按网关说的 API 形状来选 provider |

网页控制台提供同一组预设（「连接 → 对话模型」，以及第一次打开时），每个都带一个链接，指向它的 key 从哪里领；确切的主机名在 `nanomuse/server/connections.py` 的 `PROVIDERS` 里。从 App 保存的 `base_url` 如果没有路径，会补上 `/v1`（`http://host:8000` → `http://host:8000/v1`）；预设自带的主机原样保留。Ollama 和自定义端点可以没有 key。从网页控制台添加的自定义接口是一个列表（`app-settings.json` 里的 `endpoints`，每项是 `{id, label, base_url, api_key, models}`，key 以 `ENDPOINT_<ID>_API_KEY` 存在保险库里）；设在其中一个接口上的槽位带着它的地址和那个保险库引用，所以这个文件不需要知道列表的存在（[web.md](web.md#where-it-shows)）。在这里设在目录外主机上的 `[llm]` 对话模型保持原样；只有从 App 里设的那个会搬进列表。

`provider` 也可以是服务商目录 [`nanomuse/llm/providers.json`](../../nanomuse/llm/providers.json) 里的一个 id（`bailian`、`deepseek`、`moonshot`、`zhipu`、`openrouter`、`openai`、`gemini`……），这时 `base_url` 以及（为空时的）`model` 从目录里填上，只有 `api_key` 是你自己的。目录还写明每家服务商的 key 覆盖什么（聊天、手、图片、短视频）；服务器上的 `GET /api/providers` 报告每个槽位用的是哪家服务商、还剩哪些没被覆盖，App 对一项没人覆盖的功能只显示一句话（[own-key.md](own-key.md)）。

### 用 ChatGPT 套餐代替 key {#a-chatgpt-plan-instead-of-a-key}

```toml
[llm]
provider = "chatgpt"     # the sign-in from `nanomuse chatgpt login`; no base_url, no api_key
model    = ""            # empty → gpt-5.6-sol (also gpt-5.4, gpt-5.4-mini)
```

有 ChatGPT 套餐（Plus、Pro、Team）的人可以让 nanoMuse 用它来聊天和动手，方式和 OpenAI 自己的 Codex CLI 一样：`nanomuse chatgpt login` 在浏览器里打开 OpenAI 的登录页（PKCE，和 Codex 相同的 client id、scope 和重定向地址），在运行时所在机器的 1455 端口等回调，然后把令牌存进 `<data_dir>/chatgpt.json`（权限 0600），到期前自动刷新。`nanomuse chatgpt status` 说明是谁登录的、有效到什么时候（从不显示令牌）；`nanomuse chatgpt logout` 删掉存储。同样的三步也在网页控制台的「连接」屏幕上（「或者用 ChatGPT 套餐登录」），它调用运行时的 `POST /api/chatgpt/login`、`GET /api/chatgpt/status` 和 `POST /api/chatgpt/logout`（[web.md](web.md)）。登录之后什么都不会自己切换：在这里设 `provider = "chatgpt"`，在网页上选「让它来回答对话」，或者 `PUT /api/connections/llm {"provider": "chatgpt"}`。`[gui] provider = "chatgpt"` 对手同样适用。

它覆盖什么：聊天和视觉（手要读截图）。Codex 后端没有图片和视频端点，所以图片和短视频仍然需要一把 key：下面的 `[image]` 或 `[video]` 槽位，或者一家主机会画图的聊天服务商。`chatgpt` 槽位里的 `base_url` 和 `api_key` 会被忽略，并在日志里留一条警告。

**实话一句**，每次登录都会打印：*OpenAI 的条款只允许在 OpenAI 自己的 Codex 里使用 ChatGPT 套餐；别的应用曾被切断过这种访问（OpenCode，2026 年 1 月）。哪天它不能用了，API key 还能用。*

**回调必须到得了运行时。** OpenAI 把浏览器送回 `http://localhost:1455/auth/callback`，所以浏览器必须和运行时在同一台机器上（或者把这个端口转发过去）。不在同一台时（运行时在服务器上、控制台开在笔记本上），登录页照样能用，只是浏览器最后落在一个没人应答的地址上。把地址栏里那整个地址（`http://localhost:1455/auth/callback?code=…&state=…`）复制出来交给运行时：端口被占或者迟迟没有回调时，CLI 会问你要；带 `--json` 时它从 stdin 读一行；网页控制台的卡片上有一个输入框；从 `/api/chatgpt/login` 发起的登录还在等待期间，服务器接受 `POST /api/chatgpt/callback {"url": "<the address>"}`。`state` 和正在等待的那次登录对不上会被拒绝（400 `state_mismatch`），什么都不会交换。`nanomuse chatgpt proxy` 把这个登录以回环地址上一个 OpenAI 兼容端点的形式提供出来（`GET /v1/models`、`POST /v1/chat/completions`、`GET /v1/usage`，一个本地 bearer 令牌），给同一台机器上的其他程序用；`--proxy`（或 `[llm] proxy`）让它的上游调用走代理。

**套餐还剩多少。** OpenAI 按两个窗口（几小时和一周）统计套餐用量，并在每次 Codex 调用的响应头里（`x-codex-primary-used-percent`、`…-window-minutes`、`…-reset-after-seconds`，`secondary` 也有同样一组）和 `GET https://chatgpt.com/backend-api/wham/usage`（Codex CLI 的 `/status` 读的就是这个端点）上写明。`nanomuse chatgpt usage` 打印两个窗口（`--json` 给原始的 `{label, plan, limits}`），运行时在 `GET /api/chatgpt/usage` 提供给控制台，回环代理在 `GET /v1/usage` 提供；运行时还保留最近一次调用的响应头（`CodexClient.limits`）。没有什么会缓存超过一分钟。

**失败的时候。** 一次过不去的 Codex 调用会归结为少数几句话之一，从不原样照抄 socket 的报错：*这个网络连不上 chatgpt.com*（DNS、连接、TLS、超时，或者该返回 JSON 的地方给了一个 HTML 页面：拦截页）、*OpenAI 不向这个地区提供服务*（HTTP 403 `unsupported_country_region_territory`）、*ChatGPT 登录已失效。请重新登录*（401）、*ChatGPT 套餐暂时没有余量了*（指明用量上限的 429，后面附上 OpenAI 的原话和 `Retry-After`）以及*同时发出的请求太多*（其他任何 429）。回环代理返回这些句子时在 `error.code` 里带一个机器码（`unreachable`、`region_blocked`、`not_signed_in`、`quota`、`rate_limited`、`upstream`），客户端可以据此处理；手机上把同样的句子显示成一张卡片（[own-key.md](own-key.md#when-the-provider-cannot-be-reached)）。

### 工具调用模式 {#tool-calling-modes}

| `tool_mode` | 发生什么 |
|---|---|
| `auto`（默认） | 用 API 的函数调用。如果端点*拒绝* `tools` 字段（Ollama 跑一个没有工具模板的模型（"does not support tools"）、vLLM 启动时没带工具解析器），nanoMuse 记一条警告，这次运行余下的时间改在提示词里描述工具。 |
| `native` | 始终用函数调用 API；被拒绝就是错误。 |
| `prompt` | 工具写在系统提示词里，调用从 `<tool_call>` 块里解析。对那些默默*无视* `tools` 的端点（不报错，模型就是从不调用任何东西）来说，这是唯一能用的模式；有些「agent 应用」网关就是这样。 |

### 图片 {#pictures}

用户在聊天里附的图片会作为图片内容发给模型（Chat Completions 的 `image_url` 部分，Responses 的 `input_image`），先把长边缩到 1568 px。`vision = "auto"`（默认）会发送图片；端点拒绝带图的请求时（DeepSeek，或 Ollama 跑一个没有视觉的模型："model does not support multimodal requests"），就只带文字再发一次同样的请求，这次运行余下的时间不再发图片，App 提醒用户一次；之后模型收到的消息会说明哪些图片它看不到，免得它去描述自己从没见过的东西。`on` 始终发送，被拒绝就是错误。`off` 从不发送：模型只拿到文件名；文本文件、PDF 和表格无论如何它都是用 `files` 读的。在这里能用的视觉模型：GPT-4o 及之后的版本、经 OpenAI 兼容网关的 Claude、Gemini、Qwen-VL、`qwen3.8-*`，以及 Ollama 上的 `gemma3` 和 `llava`。有些 id 事先就知道，不用白费一次请求：DeepSeek 的模型只认文字，除非 id 里含 `v4.1`、`vision` 或 `ocr`；`qwen*-vl` 和 `qwen3.8-*` 看得见。

### 本地模型 {#local-models}

Ollama 在 `http://localhost:11434/v1` 提供 OpenAI 兼容的 API；带工具模板的模型（Qwen 3、Llama 3.1 及以上、Mistral、DeepSeek-R1 蒸馏版）原生调用工具，其余的通过 `auto` 的提示词回退方式工作。[`scripts/provider_check.py`](../../scripts/provider_check.py) 对任意模型跑五个日常任务（聊天、通过 `python_execute` 做一次计算、写一个文件、记住一个偏好、一个多步任务）；在 RTX 4070（12 GB）、Ollama 0.34 上的结果：

| 模型 | 工具调用 | provider_check | 说明 |
|---|---|---|---|
| `qwen3:8b` | 原生（`tool_mode = "prompt"` 也是 5/5） | 5/5 | 默认预设；每个任务 7–20 秒 |
| `llama3.2:3b` | 原生 | 5/5 | 经常把调用写成正文里一个光秃秃的 JSON 对象，并把文件内容里的换行双重转义；两种情况都会修复（见下） |
| `gemma3:4b` | 提示词，经 `auto` 回退 | 5/5 | Ollama 对它拒绝 `tools`；它输出 ```` ```tool_call ```` 围栏，提示词解析器接受 |
| DeepSeek V4.1 Flash（在线） | 原生 | 5/5 | 每个任务 1–4 秒 |

小模型会以可预料的方式扭曲协议，nanoMuse 选择迁就它们而不是让任务失败：回复如果是一个光秃秃的或围栏里的 JSON 对象、点名了某个工具（并带一个 arguments 对象），在任何模式下都算作工具调用；JSON 字符串里可以有真正的换行；`files.write` 遇到只有一行、却含两个及以上拼出来的 `\n` 的文本时会把它拆成多行（代码本来就有真正的换行，从不动它）。带其他键的加引号 JSON 对象仍当文字。

把 `max_tokens` 设成模型一轮能产出的量（对这些模型 4096 就够），`agent.max_context_messages` 别太大：一个 8k 上下文窗口的本地 8B 模型，工具结果一开始回传，很快就满了。

在内容里输出 `<think>…</think>` 的模型也有处理：推理部分被单独分出来，只在 `agent.show_thinking = true` 时显示。

## `[image]` 和 `[video]` {#image-and-video}

形象工作室的图片和形象的短视频不在聊天模型的主机上生成时，从哪里来。两个槽位都空（默认）时按一个顺序来（模型约定，0.1.41）：聊天服务商自己的图片模型（它有的话），账号的中继、阿里云百炼，以及目录里任何带 `image` 的服务商（它的 `defaults.image`；`[llm] image_model` / `video_model` 仍可指定别的）；否则在你登录了 nanoMuse Cloud 时是账号的中继，哪怕聊天模型在别处；再否则没有。短视频同理：图片主机会说视频 API 就用它，否则登录时用账号 key 走中继。设一个槽位，就能换到别处画，或者在聊天模型是 DeepSeek、ChatGPT 套餐或本地模型而你没有登录时才有地方画：

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

目录里没有的主机可以不写 `provider`，改写 `base_url`；`api_key` 发给那台主机（`[video]` 自己的主机用 `[video]` 的 key，不用图片主机的）。一项没有任何配置覆盖的功能就是不可用，并用一句话说明谁可以（大陆是*图片需要一家有图像模型的服务商：阿里云百炼、智谱 GLM、SiliconFlow 或火山方舟（怎么做：docs/own-key.md）*，其他地方是 OpenRouter、OpenAI、Google Gemini 或 xAI Grok，按 `[agent] language` 用英文或中文），出现在形象工作室、「连接」里的「生成图片」和「生成视频」下，以及 `GET /api/providers` 里。这些句子和能力都来自目录，目录变它们就变。

应用层设置的是同样的槽位：`PUT /api/connections/image` 和 `PUT /api/connections/video` 接受 `provider`（目录 id，或 `openai` / `openai_responses` 加 `base_url`）、`model`（空：目录的默认值）、`base_url` 和 `api_key`（进保险库，名为 `IMAGE_API_KEY` / `VIDEO_API_KEY`，或原样保留的 `{{vault:NAME}}` 引用；`""` 删掉它），写 `app-settings.json` 的 `image` / `video` 对象，键和这里一样是四个，像其他设置一样叠在这个文件之上，并回答槽位的设置加上它解析成什么（`effective_provider`、`effective_model`、`effective_source`：`app`、`config`、`chat` 或 `cloud`）；`GET /api/connections/image` 和 `/video` 回答同样的内容，`GET /api/connections` 两者都带。四项都空就清掉槽位。目录里列出但没有这项能力的服务商被拒绝，400 加那一句话（`DeepSeek has no image models; Pictures need …`），ChatGPT 登录也一样；本地服务器或目录不认识的主机放行，因为它有的是你装的东西。网页控制台的「生成图片」和「生成视频」两行用的就是这些路由（[web.md](web.md)）。

## `[agent]` {#agent}

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

`max_web_calls` 限制 `web_search` 和 `web_fetch` 的合计派发次数，失败或被拒绝的调用也计入。默认是 8 次，用完后两个工具暂停到本轮结束，同一次模型回复里多出的调用也会被拒绝，其他工具仍可用于交付内容。新请求或运行中收到的排队消息会重新计数，回答 `ask_user` 不会重置预算。设为 0 可取消这个上限，需要更多来源时也可以调高。它限制的是调用次数，不是耗时，也没有给其他工具的查询设置硬上限。模型指令禁止通过命令、浏览器或其他服务绕过这个预算。每次实际派发的调用仍经过哨兵。

`language = "auto"` 时，系统提示词会点明回复语言并告诉模型用它回答：客户端随消息送来了界面语言（网页控制台会送，即 `POST /api/threads/{id}/send` 的 `language`；hub 上的 `task` 也可以带）就用界面语言，否则按最近一条用户消息的文字书写系统判断。笼统的一句「用用户的语言回复」在某些模型上不可靠；点名就管用。固定的 `language` 优先于两者。

`max_context_images` 是给手用的。在屏幕上跑一次任务，每一步都会追加一张截图，而整段对话每一步都要重新上传，所以十几张全尺寸图片曾经超过中继的请求体上限（413 `too_large`，0.1.37）。现在只带最新的四张，每张缩到最多两百万像素；更早的换成一行说明，模型仍然知道那里有过一张截图。桌面版的 harness 在它那一侧守着同样的预算。

## `[sync]` {#sync}

```toml
[sync]
side_chats = false   # off: only the main conversation travels between devices
```

整个账号的同步开关在 App 里（「数据控制 → 同步」）；这里是「同时同步旁聊」在这台设备上的默认值。关着时只推送、拉取主要聊天；旁聊留在创建它的设备上，别的设备的也不会过来。开着时这台设备的旁聊进入账号，其他设备的也到这里来。你在 App 里的选择保存在 `sync.json`，优先于这个文件。全貌见 [every-device.md](every-device.md#the-same-conversations-everywhere)。

## `[cloud]` 与 `[hub]` {#cloud-and-hub}

```toml
[cloud]
base_url = "https://cloud.nanomuse.cn"   # 自己架的中继写在这里
required = true
sync = true
models = true        # 账号的模型是否作为来源；控制台里的「使用 nanoMuse Cloud 模型」

[hub]
enabled = true
remote_control = true
name = ""            # 空：用主机名
```

`[cloud]` 是这个运行时登录的中继（[cloud.md](cloud.md)）：`base_url` 是它的公网地址（按 [self-hosting.md](self-hosting.md) 自己架一台后填这里）；`required = false` 允许首次运行不登录账号就完成，适合完全不用中继的运行时；`sync` 是整个账号「数据控制 → 同步」开关的默认值，人一旦选过，以选择为准；`models = false`（控制台里的「使用 nanoMuse Cloud 模型」开关，存在 app-settings 里）把账号的模型从动手、生成图片、短视频的自动顺序和服务商列表里拿掉，登录保持不变，于是除了明确点下的「这次改用 nanoMuse Cloud」，没有什么会消耗额度。账号密钥本身是保险库里的 `NANOMUSE_CLOUD_KEY`。

`[hub]` 是把这台电脑当作账号的一台设备（[hub.md](hub.md)）：`enabled` 表示账号登录后就加入 hub；`remote_control = false` 时，其他设备只能从这台拿到 `info`，别的什么都做不了；`name` 是其他设备对它的称呼（空：用主机名）。`device_id` 按安装生成，由 App 写入。

## `[sentinel]` {#sentinel}

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

这些部分怎么组合起来，见 [sentinel.md](sentinel.md)。

## `[sandbox]` {#sandbox}

```toml
[sandbox]
mode = "auto"                        # auto | bwrap | off
```

在装了 [bubblewrap](https://github.com/containers/bubblewrap) 的 Linux 上（`apt install bubblewrap`、`dnf install bubblewrap`），每次 `shell` 和 `python_execute` 调用都在自己的命名空间里跑：工作区和 `agent.extra_roots` 是仅有的可写位置，你的家目录不在里面，`/tmp` 是私有的，而且除非这次调用被评估为需要网络，否则没有网络。`auto` 在这里能用就用，不能用时在日志里说明；`bwrap` 则坚持要用（否则 `nanomuse doctor` 失败）；`off` 不装箱直接跑命令，只有清理过的环境变量。`share_read_only` 列出箱子可以读的目录（你想让智能体用的某个 CLI：`["~/.nvm"]` 给 node 和 lark-cli），`share` 列出工具还必须写的目录（它的登录态：`["~/.lark-cli", "~/.local/share/lark-cli"]`）；你家目录下的共享目录在箱子的家目录下同一位置也看得到，所以到 `$HOME` 里找东西的工具能找到。细节和哨兵（Sentinel）在沙箱里有什么变化，见 [sentinel.md → 沙箱](sentinel.md#the-sandbox)。

## `[memory]` {#memory}

```toml
[memory]
enabled            = true
max_inject         = 20        # memories injected into the system prompt per turn
embeddings         = "auto"    # recall by meaning: auto | on | off
embedding_model    = ""        # empty → the endpoint's default (see below)
embedding_base_url = ""        # empty → the model's endpoint and key (llm.base_url / llm.api_key)
embedding_api_key  = ""        # a key of its own, "{{vault:EMBEDDINGS_API_KEY}}" from the app
```

回忆按关键词进行（生僻词权重更高，中文按字的两两组合匹配），有了嵌入端点，还能按含义回忆：每条记忆只嵌入一次（向量和文本的哈希一起存在 `memory.db` 里，所以改过的行会重新嵌入，换回某个模型不花代价），每轮把消息嵌入一次，含义最接近的记忆和关键词排名融合在一起，于是「写邮件给房东」能唤起「房东是 Bob Li」，虽然两句话没有一个词相同。任何 OpenAI 兼容的 `/embeddings` 都行：OpenAI（`text-embedding-3-small` 是那里和多数网关的默认值）、拉取了嵌入模型的 [Ollama](https://ollama.com)（`ollama pull qwen3-embedding:0.6b`，`:11434` 上的默认值，很小，中英文都读）、OpenRouter（`openai/text-embedding-3-small`）。DeepSeek 没有嵌入模型，所以用它时把 `embedding_base_url` 指到一个有的地方（DeepSeek 旁边放一个 Ollama 是常见搭配），或者就只按关键词回忆。

`auto` 每次启动试一次端点，调用失败就退回关键词回忆，在日志里说明原因：失败一次，不是每轮一次；连不上的端点五分钟后再试。`on` 则坚持要用：回忆照样退回，但失败算警告，`nanomuse doctor` 会因此失败。`off` 从不嵌入。`embedding_api_key` 为空表示在模型自己的端点上用模型自己的 key；从 App 里设置时它是一个 `{{vault:EMBEDDINGS_API_KEY}}` 引用。`llm.extra_headers` 里的网关请求头只发给模型的端点，不发给这里指定的另一个端点。App 里的「连接 → 按含义召回」设置并测试这一切；`nanomuse memory recall "…"` 显示会回忆起什么，带每条记忆的接近程度。

### `[memory.openviking]` {#memory-openviking}

Python 运行时可以在本地显式记忆之外接入 OpenViking，覆盖网页控制台、终端，以及
通过 `nanomuse-gateway` 把对话转给此运行时的设备。桌面 DSH 插件单独配置，见
[桌面版](desktop.md#openviking-memory)。

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

默认关闭；`[memory] enabled = false` 也会关闭此接入。修改配置后重启运行时。
使用 trusted 身份请求头时，设为 `auth_mode = "trusted"`，并同时填写 `account` 和
`user`。需要共享记忆的入口使用同一个服务端身份；API key 模式的身份由服务端凭据决定。
`peer_id` 可标识这个智能体，留空时使用用户的共享记忆空间。
凭据放在环境变量或保险库中，例如 `{{vault:OPENVIKING_API_KEY}}`。

支持的环境变量覆盖项为 `NANOMUSE_OPENVIKING_ENABLED`、`NANOMUSE_OPENVIKING_URL`、
`NANOMUSE_OPENVIKING_API_KEY`、`NANOMUSE_OPENVIKING_AUTH_MODE`、
`NANOMUSE_OPENVIKING_ACCOUNT`、`NANOMUSE_OPENVIKING_USER` 和
`NANOMUSE_OPENVIKING_PEER_ID`，无需额外安装 OpenViking SDK。

模型处理每轮输入前，智能体会先重试待同步内容，再召回相关记忆。召回内容标为历史参考，
读取后会把当前对话标记为已访问私密数据。用户轮次完成后，把实际用户输入和最终回复写入
独立的 OpenViking 会话，并提交异步记忆提取。后台提示、取消的轮次、恢复的旧历史、工具
输出、截图和模型思考过程不自动采集；已知保险库密文对应的明文值及保险库引用会被脱敏。
每条消息和召回上下文分别限制为 `max_chars` 个字符。读写经过哨兵，分别使用
`openviking_recall` 和 `openviking_sync`，风险为 moderate，目标是配置指定的外发地址。
拒绝规则和 strict 模式的审批仍然生效。

写入失败时，`<data_dir>/openviking-outbox.db` 以仅当前用户可访问的文件权限保存待同步
内容，在后续轮次和正常退出时重试。每次操作的总时间预算为 `timeout` 秒。
更换服务地址、凭据或身份后，旧队列保持隔离，不会转发给新目标。服务已接收但响应超时的
情况下，重试可能重复写入一条消息。提交被接收后由服务端负责后续处理，提取仍可能失败。
召回或同步不可用时，本地对话继续运行。

App 的「记忆」页新增独立的「OpenViking 记忆」区域，可以浏览目录、搜索、打开条目、
修改正文或删除单个文件，同时显示待同步数量和最近 20 个提取任务的状态。
「重试待同步内容」只重发本地队列；已被 OpenViking 接收但提取失败的任务，需要在
服务端检查。保存时使用文件版本检查并发修改。删除前检查版本，只删除单个文件，
不递归删除目录，也不允许访问当前配置用户的记忆空间以外的数据。

「自动保存对话」覆盖当前服务地址和身份的 `capture_conversations` 默认值，立即生效，
重启后保留。关闭后不会删除现有记忆或待同步内容，仍可召回或明确要求保存某个事实。
自动化请求或一次性任务可以在消息 API 中传入 `capture_memory: false`，让该任务
不自动采集，同时禁止模型调用本地和远程记忆写入工具。轮次进行中收到这种消息时，
整轮都不采集。当前 hub 协议无法向其他设备传递这个限制，因此转发给其他设备的会话
会拒绝这个参数；不传时保持旧客户端的行为。以普通用户消息发送的自动化指令，若没有
该参数且采集开关开启，仍可能进入记忆提取。

模型可通过 `openviking_memory` 工具浏览、搜索、读取、明确保存、更正或删除远程记忆。
所有操作经过哨兵，修改和删除属于敏感操作。已鉴权的记忆页操作只批准当次请求，
显式拒绝规则仍然有效，模型无法改变采集开关。本地 `remember`、`recall`、`forget`
工具和整理历史仍单独管理 SQLite 记忆。

启用 `personalization = true` 后，运行时还会在 `openviking-outbox.db` 中维护个人画像，
由持久化的所有者 ID 和记忆空间标识。轮换 OpenViking 凭据后，画像和采集开关仍保留。
`profile_id` 留空时，按当前服务地址及 account/user 身份分配并保存 ID；只有明确迁移
所有者时，才填写已有的 `profile_id`。未指定 ID 而更换服务地址或 account/user 时，
会创建另一个所有者。旧画像只从当前连接对应的命名空间迁移。待同步队列仍绑定原来的
连接和凭据，轮换凭据不会将旧对话转发到新目标。画像保存在当前运行时，与远程记忆互补。

符合采集条件的用户轮次完成后，先把用户依据写入磁盘队列。运行时空闲时，后台工作器
使用当前配置的对话模型提取最多六条候选事实，回复无需等待这次调用。每次尝试的预算为
`personalization_timeout` 秒，失败后间隔三十秒重试，最多五次；记忆页可重试失败任务。
退出时取消的任务仍保留在队列中。后台学习需要运行时继续在线，短命的 CLI 进程可能把
任务留给后续运行的实例。每个空间最多一千条待处理任务；每项最多保留最后八条符合条件
的用户消息，每条最多八千字符，合计最多三万二千字符。
提取结果必须对应用户原话；明确表达的事实直接以原话作为内容，推测出的偏好先列为
待确认项，需要在记忆页确认后才参与回答。助手回复和恢复的历史对话不作为画像来源。
提取失败时保留已有画像。手动确认或更正会使此前排队的提取失效，避免旧任务覆盖新决定。
关闭采集也会暂停队列中的画像学习。

画像区分个人事实、偏好、项目、临时状态和经验。带适用范围的事实只用于匹配的问题，
少量技术术语也能匹配编程和部署问题。临时状态默认七天到期，最长三十天；经验默认
九十天，最长一百八十天；其他事实可不设期限，模型提出的期限最多三百六十五天。
「这次简短一点」这样的单次要求不会形成长期偏好。新表述和主题对应关系仍依赖模型判断。

后续回答前会加载当前有效的画像，新对话也会使用。当前用户指令优先，画像优先于较旧的
远程参考，但不能授予操作权限或覆盖哨兵规则。待确认项和到期项不参与回答。明确更正可
替换旧事实并保留历史；已经由用户确认的事实，需要明确更正才能被自动替换。

在「记忆 → OpenViking 记忆 → 个人画像」中，可以查看来源原话、适用范围和有效期，
确认候选项、更正或停止使用某条事实。操作带版本检查，避免覆盖并发修改。停止使用后
保留拒绝标记，避免相同内容换个主题名称又被自动学回，用户仍可明确恢复使用。
这不会删除 OpenViking 的远程文件或归档对话，需要另行管理这些内容。
`personalization = false` 同时关闭画像学习和画像上下文。关闭自动采集只停止学习新内容，
已有画像仍可参与回答；后台任务和 `capture_memory: false` 的轮次不学习画像。

#### 记忆空间 {#memory-spaces}

「记忆 → 记忆空间」默认有「个人」和「工作」，可以添加项目空间并从该空间开始对话。
选择随线程保存，已有对话和旧客户端继续使用 `personal`。画像、本地显式记忆工具及
远程检索分别绑定所选空间，不会继承其他空间的个人偏好。非个人空间使用派生的
OpenViking peer ID，「个人」继续使用配置中的 peer 和原有数据。远程召回通过 `find`
限定在所选记忆根目录，并检查结果 URI。关闭 OpenViking 后仍可阅读空间对话，但其
记忆工具要等接入恢复后才能继续使用。

采集到 peer 空间时，用户消息带上对应 peer ID，会话明确开启 peer 提取、关闭 self 提取。
会话接口不会根据 actor-peer 请求头决定提取归属。运行时在写入和提交前检查已保存的策略，
重试时也会检查；不兼容的会话留在队列中，不再提交到共享记忆。无法返回该策略的旧服务端
不能接收 peer 空间的采集。修复不会移动或删除已经提取的文件，已有内容需要另行检查。
每个空间也绑定自己的文件、上传、文件库及 Shell/Python 工作目录。个人空间沿用
`agent.workspace`，其他空间位于 `<data_dir>/space-workspaces/<owner-hash>/<space>`，
不自动移动原有共享文件。关闭 OpenViking 后，文件目录和所有者绑定仍保留。
文件工具拒绝越界路径和符号链接；聊天命令使用可继承的 Linux
[Landlock 文件系统限制](https://docs.kernel.org/userspace-api/landlock.html)，只读系统库，
只允许写入当前空间。需要 ABI 3 或更新版本，不支持的平台会拒绝执行。
运行时数据不能位于可读工作区或系统目录内。已有可用的 bubblewrap 网络隔离会作为外层
保留；Landlock 本身不隔离网络。`sandbox.mode = off` 不会关闭空间文件边界，配置中的
额外目录和共享登录目录也不会自动提供给空间命令。
未启用 OpenViking 且没有已保存额外空间的运行时仍使用配置中的命令沙箱，macOS 和
Windows 也沿用原方式；已有额外空间时，即使关闭 OpenViking，严格边界仍保留。

外部连接器、编程代理、浏览器与设备控制、技能、目标、联系人和日历尚无空间身份，
暂时只在个人空间提供。非个人空间的提示词也不注入这些个人资料。公开网页搜索与读取
可在所有空间使用。这仍是单所有者运行时，已认证的管理入口属于所有者。

网页中的「启用记忆」总开关按所有者和空间保存，默认开启，与自动采集独立。关闭后暂停
本地和远程召回、模型记忆工具、对话采集、排队同步和画像学习；已有数据、排队任务及采集
设置都会保留，重启后仍生效。你仍可通过已认证的记忆管理页面查看和删除数据。
个人空间关闭时，新生成的点子和动态不再读取个人记忆或主对话历史，自动记忆整理也会暂停。
全局 `memory.enabled = false` 的优先级更高。已提交的远端提取仍可能完成，但关闭期间不会
召回这些结果。当前聊天历史和手动设置的应用风格仍有效，文件边界独立执行。

所有空间属于同一位运行时所有者，共用运行时 Token。它们是逻辑记忆边界，不是独立的
操作系统用户或托管租户；其他工具仍遵循各自的哨兵和文件权限规则。连接同一运行时的
客户端共用这些空间。独立桌面 DSH 插件仍有自己的记忆配置，不加载这些本地画像。
当前会话同步协议未携带空间身份，因此非个人空间对话留在当前运行时，不会作为个人对话
同步给旧客户端。


#### 检查事实副本 {#reviewed-fact-copies}

`POST /api/memory/spaces/{space}/facts` 接受 `action`（`preview`、`apply`、
`status`、`unblock`）、`term`、可选的 `replacement` 和 `aliases`，以及 `apply` 时使用的预览
`revision`。这个需要认证的入口以 `memory_facts` 通过哨兵（Sentinel），显式禁止规则
仍生效。记忆关闭时也能管理，未启用 OpenViking 时可管理本地笔记。片段为 3 到 500 字，
替换内容最多 500 字。`aliases` 最多 20 项，每项 3 到 500 字，预览版本同时绑定这些说法。
命中文本后，同一字段、类型和适用范围的画像版本会自动关联，预览中会标明；其他措辞
需要手动补充并确认。关联的停用规则共用 `fact_id`，备份会保留。预览版本绑定空间、
当前管理的数据和准确的修改内容。扫描超过
备份限制、1,000 条本地笔记或 1,000 条撤销历史时会失败，不截断，也不搜索普通工作区文件。

用户确认的停用规则和替换值存于 `memory-usage.db`，按所有者和空间区分。本地召回、
远程召回及模型浏览和读取、记忆写入、对话采集和画像学习都会过滤命中旧片段的记录。
经过认证的管理页面仍能检查这些内容。命中记录中的其他文字也暂不提供给助手，需要
更正文件后才能使用。准确片段匹配无法识别任意改写。停用列表本身会保留旧片段，以便
阻止再次出现的记录。空间备份包含规则；清理会删除规则，恢复时保留已有同片段规则。

操作会移除命中的画像版本、本地撤销记录、排队内容，以及能确定归属和内容的归档会话。
替换会更正当前事实和远程文件中的文字，删除命中的归档证据，并将当前值标为用户确认
的优先值。操作会使排队的画像学习失效，防止旧任务撤回人工修改。其他空间和未记录的
旧归档仍单独管理。跨存储的网络修改不是原子操作，停用规则先于数据修改保存，部分
失败后仍然生效。`memory-usage.db` 保存每个来源的扫描、匹配、修改数量和完成状态，
每个空间保留最近 20 次操作，`status` 返回最近一次结果。中断的操作在下次查询时标为
未完成。请先检查剩余副本再重试，不重放旧预览。报告不包含事实正文；聊天记录、审计
日志、未记录的归档和普通工作区文件不在这项操作范围内。

记忆关闭时，运行时识别明确要求记住、召回或忘掉的中英文请求，直接答复，不调用模型
或工具。这无法覆盖所有改写，因此执行层还会默认拦截存储和动作工具。只有当前用户请求
明确提出文件、文档、命令或编程任务时，才允许文件、Shell 和 Python 工具，长期授权不能
绕过限制。公开网页搜索、读取和向用户提问仍可使用；含糊的合法任务可能需要补充明确的
文件或代码要求。

#### 记忆备份 {#memory-backups}

在空间内下载备份后，才能使用「导出后清理」。导出包含所有画像版本、拒绝标记、当前
本地笔记、可见远程记忆文件、本运行时记录的采集轮次，以及待同步和待学习的依据。
不包含凭据、聊天记录、本地撤销日志或哨兵审计日志。完整轮次从安装此功能后的采集开始
记录；较早的远程会话只能通过仍保留的待同步和提交记录识别。远程目录树超过一千个条目、
单个远程文件超过 32,000 个字符或总计超过 10 MB 时，备份失败，不会静默截断。

清理会检查导出版本，要求当前对话及已知远程提取完成，关闭采集并使学习任务失效，
删除有归属记录的远程会话和可见记忆文件，再清除该空间的本地事实、撤销历史、向量及
待处理任务。未记录归属的会话、其他远程 peer、本地聊天记录和审计日志需单独管理。
这是逻辑删除，不保证清除存储备份或空闲页。网络失败可能留下部分已清理的远程空间，
此时采集保持关闭；请保留下载的备份，导出剩余状态并检查后再重试。

恢复要求相同所有者 ID 和空间，会检查路径与校验和，采用事实并创建缺失的远程记忆文件。
已有远程正文不同则拒绝覆盖，当前已有的画像主题会保留。恢复不重放采集对话或排队任务，
不重建原始远程归档，也不自动开启采集。导出的轮次依据仍保留在下载的备份中。
这些已鉴权的操作经过哨兵，显式拒绝规则仍然有效。

删除提取后的记忆不会删除归档对话，重新处理归档可能再次生成它。清空聊天、关闭接入
或删除本地记忆，都不会清除服务端记忆或待同步队列。

真实验证时，告诉智能体一条容易辨认的项目名称和编号，等服务端提交任务完成后，新建一个
运行时线程，再问它编号。同时检查服务端保存的记忆和召回请求，只在原对话中答对不能证明
跨会话召回生效。

在本地开发服务上直接检查远程召回时，使用与运行时相同的身份：

```sh
curl --fail-with-body -sS http://127.0.0.1:1933/api/v1/search/search \
  -H 'Content-Type: application/json' \
  -H 'X-OpenViking-Account: personal' \
  -H 'X-OpenViking-User: me' \
  -d '{"query":"project identifier","mode":"context","context_type":"memory","max_tokens":1000,"rewrite":false}'
```

按实际配置修改身份请求头。context 模式使用 `context_type` 筛选记忆，不接受
`target_uri`；兼容旧版服务的 `/search/find` 查询才使用 `target_uri`。HTTP 200
但结果没有条目，表示未找到相关的已索引记忆，并非连接失败。提交成功也不代表记忆提取
已经完成。

Docker 里的 `127.0.0.1` 指容器自身，需要填写容器可访问的地址。宿主机服务若仅监听
回环地址，单独改成 `host.docker.internal` 也无法访问，应使用合适的网络配置或带鉴权的
服务端点。运行中的容器必须包含本次 Python 代码，单独重建桌面插件不会更新这个容器。

## `[skills]` {#skills}

```toml
[skills]
enabled  = true
dir      = ""                        # your skills; empty → <data_dir>/skills
disabled = ["inbox-triage"]          # built-in ones to leave out of the model's list
```

一个技能就是一个带 `SKILL.md` 的文件夹（YAML front matter 里有 `name` 和 `description`，后面是 Markdown 写的步骤），采用 [Agent Skills](https://agentskills.io) 格式，所以给其他智能体写的技能在这里也能用。nanoMuse 多读一个键 `channel`：技能在[阶梯](gui.md#the-ladder)的哪一级上工作：`api`（MCP 服务器或连接器）、`cli`、`web`（一次抓取）、`browser`、`gui`（手机屏幕；也接受 `app-only`）或 `mixed`。`gui` 技能在智能体的索引里标为*在手机屏幕上*，这样它开始之前就知道这活需要手机；必须严格遵守共享格式的技能可以改用 `metadata.channel`。内置十一个（`weekly-review`、`trip-plan`、`inbox-triage`、`compare-options`、`meeting-prep`；`phone-messages` 用于手机屏幕；五个面向不需要屏幕的中国服务：`feishu` 经 lark-cli、`tencent-meeting` 经 tmeet、`amap` 经高德 MCP 服务器、`kuaidi100` 经快递100 服务器，以及 `train-tickets`，它通过 12306 服务器查询，只在被明确要求时才在手机上订票；哪些在哪里跑过，见 [services.md](services.md)）；`dir` 里一个和内置同名的文件夹会替换掉内置的那个。模型在系统提示词里拿到索引（每个启用技能的名字和描述），请求合适时用 `skills` 工具读取技能的步骤；聊天消息开头的 `/name` 直接运行一个。从聊天里保存或删除技能是敏感调用：无论哨兵是什么模式，都先问。在 App 里关掉的技能记在 `app-settings.json`；这里的列表和那份会合并。在[沙箱](sentinel.md#the-sandbox)里，技能的文件夹（它的脚本和参考文件）以只读方式可见。见 [App → 技能](app.md#skills)和 [CLI](cli.md#skills) 里的 `nanomuse skills`。

## 连接器 {#connectors}

### 邮件 {#email}

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

用 `nanomuse vault set EMAIL_ADDRESS` 和 `nanomuse vault set EMAIL_PASSWORD` 存值。`read_emails` 会把这段对话标记为已污染；`send_email` 默认在 `always_ask_tools` 里。

### 日历 {#calendar}

任何提供私密 iCalendar 链接的日历都行（Google（「设置 → 整合日历 → iCal 格式的私密地址」）、Outlook（「共享日历 → 发布」）、iCloud（「共享日历 → 公共日历」）、Fastmail、Nextcloud），或者磁盘上的一个 `.ics` 文件。`webcal://` 链接通过 HTTPS 抓取。订阅源的文本缓存在 `<data_dir>/calendar-cache.json`（权限 0600），这样启动时和两次刷新之间都有日程可看。

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

`calendar` 工具负责读（日程、搜索、空闲时间）和*起草*：它提议的日程写成工作区里的 `calendar/<date>-<title>.ics`，App 把它显示成一张带「加入日历」按钮的卡片。它自己从不写你的日历。今天和明天的日程在系统提示词里；动态在「今天」下面显示它们。`nanomuse calendar add NAME URL` 和「连接」屏幕做的是同一件事。

### 联系人 {#contacts}

谁是谁。智能体写信给人之前会先查这个人，从不猜地址；邮件的审批卡片用通讯录里的名字标出收件人，不认识时会提醒。来源是 `.vcf` 文件（Google 通讯录（「导出 → vCard」）、iCloud、Outlook（「人员 → 管理 → 导出」）、Nextcloud、iPhone（「通讯录 → 全选 → 共享」）和 Android 都能导出），可以是一个路径、从手机上传（存在 `<data_dir>/contacts/` 下），或者一个链接（存在保险库里）。vCard 2.1、3.0 和 4.0 都能读，包括 Apple 的 `item1.` 标签分组和老手机导出的 quoted-printable 编码的名字。链接的文本缓存在 `<data_dir>/contacts-cache.json`（权限 0600）。

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

除了这些来源，始终还有一本「我的联系人」，`<data_dir>/contacts.vcf`：在聊天里告诉过智能体的人（「房东是 Bob Li，bob@example.com」），通过 `contacts` 的 action=add 加进去；这是它唯一会写的一本，也是唯一能从里面删人的一本。`contacts` 工具按姓名、昵称、公司、邮箱或电话搜索（每个词都要匹配上，前缀算数，中文名里的一个字也算数）；一次查询属于私密数据，会污染这段对话。命令行用 `nanomuse contacts search | list | add | sources | add-source | remove-source`。

### 网页搜索 {#web-search}

谁来回答 `web_search`。DuckDuckGo 什么都不需要，是默认值，但它是抓网页而不是正规接口：会限流，时不时出问题。想要每次都能搜到，指定一家带 API 的服务商：带 key 的 [Brave Search](https://brave.com/search/api/) 或 [Tavily](https://app.tavily.com/)，有没有 key 都行的 [You.com](https://you.com/platform/api-keys)，或者你自己跑的一个 [SearXNG](https://docs.searxng.org/) 实例（`search.formats` 里要有 `json`）。手机上同样的选项在「连接 → 网页搜索」，key 以 `SEARCH_API_KEY` 存进保险库，「测试」跑一次搜索。

```toml
[connectors.search]
provider = "duckduckgo"          # duckduckgo | brave | tavily | you | searxng
api_key  = "{{vault:SEARCH_API_KEY}}"   # brave / tavily，以及有 key 的 you：nanomuse vault set SEARCH_API_KEY
base_url = ""                    # searxng: your instance, e.g. "http://127.0.0.1:8080"
fallback = true                  # false：搜索失败就失败，不再转去 DuckDuckGo
```

You.com 不带 key 时走 `api.you.com`，每个地址每天 100 次，不用注册；超出后搜索会说明原因，由 DuckDuckGo 补答一次。带 key 时走 `ydc-index.io`，也就是额度更高的付费 Search API；哨兵显示的是这次搜索真正去的主机。发往 You.com 的请求带 `youdotcom-integration/nano-muse-nanomuse` 这个 User-Agent，是应对方要求加的，方便他们认出来自 nanoMuse 的流量；除此之外不多发任何东西，其他服务商也不会收到它。

不管选的是谁，一次失败的搜索（key 过期、被限流、实例挂了）都改由 DuckDuckGo 回答，只补这一次，并在结果顶上加一条说明，任务就能继续（这时查询词除了到你选的服务商，也会到 DuckDuckGo 的主机；不希望这样，就在 `[connectors.search]` 下设 `fallback = false`）；`nanomuse doctor` 会报告缺了必要配置的服务商。工具的 `region` 参数（`cn-zh`、`us-en`）按每家服务商自己的写法传过去。服务商的主机是你选定的目的地，所以读过私密数据之后再搜索，不像去一个陌生主机那样需要审批（见[污点追踪](sentinel.md#taint-tracking)）；对搜索结果做 `web_fetch` 仍然需要。

网页工具连续三次报错或返回空搜索结果后，会暂停到本轮结束。DuckDuckGo 已知的
`No results found` 回复按空结果处理，不能据此认定航班、路线或服务不存在。
连接和 TLS 等传输错误仍然按错误处理。

`web_fetch` 会在每次跳转时检查 DNS，拒绝非公网目标，即使你已经批准向该站点发送请求。
如果代理返回 `198.18.0.0/15` 的虚拟地址，公网网页也会被拦截，错误信息会说明这种可能。
请让运行时或代理使用真实 DNS 解析，保留内部地址保护。批准域名不能覆盖这项 DNS 检查。

## `[triggers]` {#triggers}

触发器是常设的指令，某件事发生时就开工：来了一封邮件、一个日程快开始了、某个程序调用了 webhook（见 [App](app.md#triggers)）。它们在聊天里或「日程」下设置，不在配置文件里；这一节只调它们被监视的方式。

```toml
[triggers]
mail_poll_minutes = 5    # how often the inbox is looked at while a mail trigger is active
hook_min_seconds  = 10   # deliveries to one webhook closer together than this get HTTP 429
```

邮件触发器需要[邮件连接器](#email)；日程触发器需要[日历](#calendar)。触发器存在 `<data_dir>/triggers.db`。

### 浏览器 {#browser}

```toml
[browser]
enabled    = true      # pip install "nanomuse[browser]" && playwright install chromium
backend    = "auto"    # auto | playwright | device — the phone's own WebView when a nanoMuse app is connected, Chromium otherwise
profile    = ""        # mobile | desktop | "" (mobile on the phone, desktop on a computer)
headless   = true      # Playwright only
timeout_ms = 30000
```

在 Chromium 里完成的登录保存在 `<workspace>/browser-profile/`，重启后还在；在手机上则保存在 App 的 WebView 里。两种后端、接管、带登录态的 `fetch`，以及什么东西在 WebView 里登录不了：[browser.md](browser.md)。

### 操作这台电脑（`[hands]`） {#hands-on-this-computer-hands}

```toml
[hands]
enabled         = false    # the switch is Devices → Hands on this computer in the app
backend         = "auto"   # auto | desktop | pyautogui | xdotool (X11) — desktop: the desktop app's own hands (auto takes them when the app set NANOMUSE_OPERATOR_URL)
mode            = "auto"   # auto | screen | window — window: one app's window on macOS, events to its process, your mouse untouched; auto = window on macOS once an app is named
coords          = "pixels" # pixels | norm1000 — what the model's x, y mean: pixels of the picture it was shown (default), or a 0–1000 grid over it
max_image_width = 1600
settle_s        = 0.6
```

模型看到的那张图就是度量单位：`computer_screen` 在第一行和结尾的 *Coordinates:* 一行里说明它的尺寸，`computer_act` 接受这张图里的 `x`、`y`（或一个 `box`）；运行时把它们一次性换算成手自己的像素，不管显示器是什么缩放比例。这张图是屏幕先按 `max_image_width` 封顶，再对齐到 Qwen 缩放时用的 28 像素网格，所以模型看到的正是它所指的东西（[gui.md](gui.md#hands-on-the-computer-the-picture-is-the-unit)）。

模型、步数上限和敏感词都用 `[gui]` 的。窗口模式、按 App 逐个询问（*允许 <Muse> 使用 <App>？*，一条 `computer_app:<id>` 授权）和 macOS 权限：[every-device.md](every-device.md#hands-on-this-computer)。

### 手机（`[gui]`） {#the-phone-gui}

打开它，智能体就能看连着的手机的屏幕，在上面的 App 里点、输入、滑动：这是够到 12306、微信或支付宝的办法，它们没有 API。默认关闭；「连接」屏幕上的「手机」卡片是同一个开关。它怎么工作、哨兵拿它怎么办：[gui.md](gui.md)。

```toml
[gui]
enabled          = false
provider         = "openai"          # the operator's own model; openai | openai_responses | chatgpt | a catalogue id
model            = ""                # empty: the main [llm] model does it — it must take images, the screen is a picture
base_url         = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key          = "{{vault:GUI_API_KEY}}"
max_steps        = 0                 # 一次 phone_task 最多走多少步；0 = 不设上限
device_timeout_s = 20.0              # how long to wait for the phone to answer
reconnect_grace_s = 30.0             # 手机掉线后，进行中的任务等它回来多久；0 = 立刻放弃
sensitive_words  = ["确认支付", "立即付款", "转账", "提交订单", "发送", "删除", "pay now", "place order", "send", "delete"]  # a tap on these asks first; 这里是节选，默认列表有 22 个词
```

`base_url` 和 `api_key` 为空时回退到 `[llm]`。空的 `model` 按一个顺序来（模型约定，0.1.41）：以中继为聊天模型时，是中继的手的模型（`qwen3.8-27b`，除非 `/v1/models` 另有指定），而不是聊天模型（聊天的默认模型看得懂图片，但手需要的是训练过、会在屏幕上指东西的模型）；聊天服务商是目录里带 `vision` 的自有服务商时，是它自己的手的模型（`defaults.hands`，百炼是 `qwen3.8-27b`，智谱是 `glm-4.6v`），用聊天的 key；聊天服务商看不了图（按目录 id 或主机识别出的本地服务器）而账号已登录时，是中继的手的模型，用账号的 key，聊天模型留在原处；其余情况是聊天模型，目录里没有的主机也是。明确写了 `model` 总是优先。只有操作器的 `base_url` 是另一个服务时才需要 key。每次手机任务的轨迹都进 `<data_dir>/phone-traces/`（保留最近 200 条；`nanomuse phone traces`）。

应用层通过 `PUT /api/connections/gui` 设置这个槽位，它接受的 `provider` 和 `PUT /api/connections/llm` 一样：协议（`openai`、`openai_responses`）、`chatgpt`，或者 `bailian` 这样的目录 id，后者自带接口地址（`base_url` 可以留空）；目录里没有的 id，或运行时不会说其协议的 id，回 400 并列出可选项。回答（以及 `GET /api/connections` → `gui`）带 `provider` 原样、`provider_id`（协议加 URL 对应的目录条目）、`effective_model` 和 `effective_source`（`gui`、`chat` 或 `cloud`）。

### MCP 服务器 {#mcp-servers}

任何会说 [Model Context Protocol](https://modelcontextprotocol.io) 的东西都变成一组名为 `<server>__<tool>` 的工具，每个都带着你指定的风险级别经过哨兵。

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

`tools` 是可选的，按工具名（不带 `<server>__` 前缀）逐个写；没写的都回退到服务器的值。手机自带的工具就是这样拿到默认值的：在手机上，App 的能力不用任何配置就以 `device` 这个服务器的身份出现（[device.md](device.md)），逐工具的表来自 `nanomuse/runtime.py`。

需要 key 的命令通过 `env` 拿到它，而 key 本身放在保险库里：写 `env = { AMAP_MAPS_API_KEY = "{{vault:AMAP_KEY}}" }`，引用在服务器启动时才解析，不会写进磁盘，也不会显示在 App 里。从 App（连接页）添加的服务器也是同样的做法，不需要你额外操作：你输入的每个 `env` 值都存进保险库，名字是 `MCP_<SERVER>_<KEY>`（全部大写，`amap` 配 `AMAP_MAPS_API_KEY` 就是 `MCP_AMAP_AMAP_MAPS_API_KEY`），`app-settings.json` 里只保留 `{{vault:...}}`；移除服务器时这些条目一并删除。本来就写成引用的值原样保留。`config.toml` 里的明文值仍然可用，连接页会给这个服务器打上标记，提醒你把它挪进保险库。

连不上的服务器会记一条日志然后跳过，智能体照常启动，只是没有它的工具；日志那一行写明服务器名和传输层的错误，URL 查询参数的值一律打码（`?key=***`），保险库里的机密也会被替换，所以被拒绝的 key 不会落进 `logs/`。

内置技能认识的三个中国服务以 MCP 服务器的形式提供，`config/config.example.toml` 里每个都有一段：高德地图（托管，`AMAP_KEY` 放保险库）、12306（`npx -y 12306-mcp`，不要 key；火车票，只能查询）和快递100（托管，`KUAIDI100_KEY`；快递，按单号付费）。其中哪些真的在手机的根文件系统里跑过，外面还有些什么：[services.md](services.md)。

## `[server]` {#server}

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

`update_check` 每天一次（点「现在检查」时提前；查询失败时，比如运行时比网络先起来，一小时后再试）先问下载镜像的索引（`nanomuse.cn/dl/index.json`），
它不答再问 `api.github.com` 最新版本，并在「设置 → 关于」下显示版本号和指向发布页的链接；什么都不下载，
除了请求 `User-Agent` 里的运行时版本号，也不发送任何关于这次安装的信息。
`NANOMUSE_NO_UPDATE_CHECK=1` 同样能关掉它；托管的网页会话（用 `NANOMUSE_CLOUD_KEY`
启动的运行时）从不检查；由它的运营者来更新。

这些设置只适用于 Python 运行时。Windows 桌面壳在启动后和每六小时独立检查，自动下载
开关默认开启并保存，计费或未知网络等待主动下载，详见[桌面版](desktop.md#updating-on-windows)。

## 东西都在哪 {#where-things-live}

| 路径 | 内容 |
|---|---|
| `~/.nanomuse/`（`data_dir`） | 下面所有的东西 |
| `memory.db`、`goals.db` | SQLite |
| `vault.enc`、`vault.key` | 加密存放的机密和它的密钥（或 `NANOMUSE_VAULT_KEY`） |
| `audit.jsonl` | 只追加的审计日志 |
| `approvals.json` | 你授予 24 小时或永久的权限（工具 + 目标、范围、过期时间） |
| `app-settings.json` | App「连接」屏幕里改过的东西，叠在 `config.toml` 之上（没有密钥，只有 `{{vault:NAME}}` 引用） |
| `chatgpt.json` | ChatGPT 登录的令牌（权限 0600；`nanomuse chatgpt logout` 删掉它） |
| `sessions/` | CLI 的对话历史 |
| `skills/<name>/SKILL.md` | 你的技能（Agent Skills 格式）；和内置同名的会替换掉内置的 |
| `threads/`、`profile.json`、`ideas.json`、`server_token`、`logs/` | App 状态 |
| `./workspace`（`agent.workspace`） | 智能体读写的文件；`screenshots/` 存着手机最近发来的 400 张屏幕（手机轨迹指向它们） |
