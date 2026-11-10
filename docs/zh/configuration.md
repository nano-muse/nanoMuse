# 配置

nanoMuse 从一个 TOML 配置文件读取设置。TOML 是一种用键和值、分组标题表示设置的文本格式。运行 `nanomuse config init`，会把带注释的示例 [`config/config.example.toml`](../../config/config.example.toml) 复制到 `config/config.toml`。`nanomuse config show` 可查看最终生效的设置，其中的密钥等敏感内容会隐藏。

配置文件按以下顺序查找：

1. `--config PATH` / `NANOMUSE_CONFIG`
2. `./config/config.toml`
3. `~/.nanomuse/config.toml`

任何字符串值都可以包含 `${VAR}` 或 `${VAR:-default}`。加载文件时，程序会将其替换为相应环境变量的值，因此无需把 API key（调用服务所需的密钥）直接写入文件。`api_key`、`address`、`password` 还支持 `{{vault:NAME}}`，程序创建客户端时才从加密保险库读取真实值，不会提供给模型。

设置分三层，后者覆盖前者：配置文件、环境变量、应用「连接」页保存的设置。应用设置保存在 `<data_dir>/app-settings.json`，包括模型、邮件服务器、浏览器开关和从手机添加的 MCP 服务器。MCP 是让智能体以统一方式连接外部工具的协议。这份应用设置文件只使用 `{{vault:NAME}}` 引用敏感信息。

无法识别的键会被忽略，对应设置使用默认值。例如拼错的 `modle` 或其他版本的配置键，加载器会在日志中指出完整路径，如 `llm.modle`，`nanomuse doctor` 也会将它列为问题。允许任意内容的配置段不受此限制，包括 `[llm.extra_headers]`、MCP 服务器的 `env`，以及 [channels.md](channels.md) 中的 `[channels.<name>]`。

日期和标题相同的日历草稿会用序号区分，例如 `calendar/<date>-<title>-2.ics`，不会覆盖已有草稿。

## 环境变量覆盖 {#environment-overrides}

以下环境变量优先于配置文件，涵盖常用设置和 Docker 所需设置。运行时指执行 nanoMuse 任务的程序，容器则是打包并隔离该程序运行环境的方式。

| 变量 | 对应设置 |
|---|---|
| `NANOMUSE_LLM_PROVIDER`、`NANOMUSE_LLM_MODEL`、`NANOMUSE_LLM_BASE_URL`、`NANOMUSE_LLM_API_KEY`、`NANOMUSE_LLM_TOOL_MODE`、`NANOMUSE_LLM_VISION`、`NANOMUSE_LLM_IMAGE_MODEL`、`NANOMUSE_LLM_VIDEO_MODEL`、`NANOMUSE_LLM_VIDEO_BASE_URL` | `[llm]`。其中 `video_base_url` 指位于其他服务地址的异步视频 API；展示站网关等转发服务会在这里设置自己的地址。异步 API 在创建任务后另行查询生成结果 |
| `DEEPSEEK_API_KEY`、`OPENAI_API_KEY` | 当 `llm.api_key` 为空时使用。`base_url` 属于 `*.deepseek.com` 时用 DeepSeek key，其他服务地址，包括 OpenAI、OpenRouter、网关、vLLM，使用 OpenAI key |
| `NANOMUSE_DATA_DIR` | `data_dir`，默认 `~/.nanomuse` |
| `NANOMUSE_WORKSPACE` | `agent.workspace`。当前目录中有 `./workspace` 时默认使用它，否则使用 `<data_dir>/workspace` |
| `NANOMUSE_SENTINEL_MODE` | `sentinel.mode` |
| `NANOMUSE_SEARCH_PROVIDER`、`NANOMUSE_SEARCH_API_KEY`、`NANOMUSE_SEARCH_BASE_URL` | `[connectors.search]` |
| `NANOMUSE_SERVER_HOST`、`NANOMUSE_SERVER_PORT`、`NANOMUSE_SERVER_TOKEN` | `[server]` |
| `NANOMUSE_BROWSER_ENABLED=1` | 设置 `browser.enabled = true`，只能启用，不能关闭。浏览器 Docker 镜像会设置此项，手机通过 `NANOMUSE_DEVICE` 设置 |
| `NANOMUSE_BROWSER_BACKEND` | `browser.backend`，可用值为 `auto`、`playwright`、`device` |
| `NANOMUSE_GUI_ENABLED=1`、`NANOMUSE_GUI_PROVIDER`、`NANOMUSE_GUI_MODEL`、`NANOMUSE_GUI_BASE_URL`、`NANOMUSE_GUI_API_KEY` | `[gui]`，控制手机操作及使用的模型 |
| `NANOMUSE_IMAGE_PROVIDER`、`NANOMUSE_IMAGE_MODEL`、`NANOMUSE_IMAGE_BASE_URL`、`NANOMUSE_IMAGE_API_KEY`；将 `IMAGE` 换为 `VIDEO` 同样适用 | [`[image]` 和 `[video]` 配置](#image-and-video)，指定图片和视频的生成服务 |
| `NANOMUSE_VAULT_KEY` | 保险库使用的 Fernet 加密密钥，默认保存在 `<data_dir>/vault.key` |
| `NANOMUSE_CLOUD_BASE_URL`、`NANOMUSE_CLOUD_REQUIRED`、`NANOMUSE_CLOUD_SYNC` | `[cloud]`，分别指定托管运行时登录的中继、是否必须登录 nanoMuse Cloud，以及「在我的设备之间同步对话」的默认状态。中继是负责账号和设备消息转发的服务。`sync` 未设为 `0` 时默认开启，但用户在设置 → 数据控制中选择后，以用户选择为准，见 [every-device.md](every-device.md#the-same-conversations-everywhere)。另见 [cloud.md](cloud.md)，中继自身的变量见 [cloud/README.md](../../cloud/README.md) |
| `NANOMUSE_HUB_NAME` | `hub.name`，其他设备看到的本机名称 |
| `NANOMUSE_CLOUD_KEY`、`NANOMUSE_CLOUD_HINT`、`NANOMUSE_CLOUD_CHANNEL`、`NANOMUSE_ONBOARDED` | 让托管运行时 nanoMuse Web 启动即登录。创建容器的网关传入账号 key、脱敏账号标识、账号渠道及首次引导完成状态。key 与手动输入时一样存入保险库；保险库已有 key 时不再处理 |
| `NANOMUSE_IN_CONTAINER=1` | 表示运行时位于容器内。镜像会设置，程序也会检查 `/.dockerenv`。此时 `sandbox.mode = auto` 将容器本身视为隔离环境，不再因缺少 bubblewrap 报告问题 |
| `NANOMUSE_CODING_HOME` | 查找编程 CLI（命令行程序）数据目录的位置，例如 `~/.codex`、`~/.claude`，默认从用户主目录查找，见 [coding-agents.md](coding-agents.md) |
| `NANOMUSE_LOG_LEVEL` | `log_level` |

仓库根目录的 Docker compose 文件通过 `NANOMUSE_RUNTIME_PORT` 设置网页版映射到宿主机的端口，默认 8787。这是 compose 变量，不属于运行时设置，也不能代替 `NANOMUSE_SERVER_PORT`，见[部署](deployment.md#docker)。

## `[llm]` {#llm}

`[llm]` 配置对话模型。`max_tokens` 中的 token 是模型计算输入输出长度的文本单位，并不等同于字数。

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
tool_mode     = "auto"             # "auto" | "native" | "prompt"; see below
vision        = "auto"             # pictures attached in chat go to the model: "auto" | "on" | "off"
pass_reasoning = false             # send reasoning_content back with assistant turns (some DeepSeek endpoints)
extra_headers = {}                 # e.g. { "X-End-User-Id" = "nanomuse" }
extra_body    = {}                 # e.g. { "thinking" = { "type" = "enabled" } }
proxy         = ""                 # an HTTP(S) or SOCKS proxy for this slot only, e.g. "http://127.0.0.1:7890"
image_model   = ""                 # the older way to name the avatar studio's picture model on this host; see [image] below
video_model   = ""                 # the same for clips
video_base_url = ""                # the asynchronous video API when it is not on this host (a relaying gateway)
```

`proxy` 只让本组模型请求使用指定代理，`chatgpt` 组还包括登录 token 的刷新。设定后，这些请求不再使用环境中的 `HTTPS_PROXY`；留空时由环境决定。它不影响 nanoMuse Cloud 或 hub（设备互联）连接。手机上的对应设置位于设置 → 网络，见 [own-key.md](own-key.md#when-the-provider-cannot-be-reached)。

各服务商的配置示例：

| 服务商 | `model` | `base_url` | 说明 |
|---|---|---|---|
| DeepSeek | `deepseek-flash` | `https://api.deepseek.com` | 默认配置 |
| Kimi（Moonshot） | `kimi-k2.6` | `https://api.moonshot.cn/v1` | |
| 阿里云百炼（Alibaba Cloud Bailian） | `deepseek-v4.1-flash` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 中国大陆服务；操作屏幕的模型 `qwen3.8-27b` 使用同一接口 |
| GLM（智谱） | `glm-5.3` | `https://open.bigmodel.cn/api/paas/v4` | |
| 豆包（火山方舟） | 你的接入点 id | `https://ark.cn-beijing.volces.com/api/v3` | 模型以版本化部署提供，应用会列出你的部署 |
| MiniMax | `MiniMax-M3` | `https://api.minimaxi.com/v1` | |
| OpenAI | `gpt-5.4-mini` | `https://api.openai.com/v1` | 也支持 `provider = "openai_responses"` |
| OpenRouter | `deepseek/deepseek-v4.1-flash` | `https://openrouter.ai/api/v1` | 中国大陆以外的服务；操作屏幕的模型 `qwen/qwen3.8-27b` 使用同一接口 |
| Ollama | `qwen3:8b` | `http://localhost:11434/v1` | 使用 `api_key = "ollama"`，见[本地模型](#local-models) |
| vLLM / LM Studio | 你部署的模型名称 | `http://localhost:8000/v1` | 如果服务器忽略 `tools`，设置 `tool_mode = "prompt"` |
| 公司网关 | 按网关要求 | 按网关要求 | 可用 `extra_headers` / `extra_body`，按网关支持的 API 协议选择 provider |

网页控制台的连接 → 对话模型和首次引导也提供这些预设，并附上申请 key 的链接。准确的服务地址保存在 `nanomuse/server/connections.py` 的 `PROVIDERS` 中。从应用保存的 `base_url` 如果不含路径，会自动补上 `/v1`，例如 `http://host:8000` 变为 `http://host:8000/v1`；预设自带的地址则保持原样。Ollama 和自定义接口可以不填 key。

网页版添加的自定义接口保存在 `app-settings.json` 的 `endpoints` 列表中，每项为 `{id, label, base_url, api_key, models}`，key 存入保险库，名称为 `ENDPOINT_<ID>_API_KEY`。某项模型配置使用该接口时，会保存服务地址和保险库引用，因此无需在本文件重复配置接口列表，见 [web.md](web.md#where-it-shows)。如果你在本文件的 `[llm]` 中配置了未收录的服务地址，程序会保留原配置；只有从应用设置的接口才会加入列表。

`provider` 也可以填写[服务商目录 `nanomuse/llm/providers.json`](../../nanomuse/llm/providers.json)中的 id，如 `bailian`、`deepseek`、`moonshot`、`zhipu`、`openrouter`、`openai`、`gemini`。此时程序从目录补全 `base_url`，并在 `model` 为空时填入默认模型，你只需提供自己的 `api_key`。目录还记录各家 key 能用于对话、操作屏幕、图片或视频中的哪些功能。服务器的 `GET /api/providers` 会报告每项配置使用的服务商及尚未覆盖的功能，应用也会为不可用功能显示一句说明，见 [own-key.md](own-key.md)。

### 使用 ChatGPT 套餐 {#a-chatgpt-plan-instead-of-a-key}

```toml
[llm]
provider = "chatgpt"     # the sign-in from `nanomuse chatgpt login`; no base_url, no api_key
model    = ""            # empty → gpt-5.6-sol (also gpt-6.1-sol, gpt-6-sol, gpt-6-luna, gpt-6-astra, gpt-5.4, gpt-5.4-mini)
```

已有 ChatGPT Plus、Pro 或 Team 套餐时，可以像 OpenAI 的 Codex CLI 一样，登录后供 nanoMuse 对话和操作屏幕使用。运行 `nanomuse chatgpt login` 会在浏览器打开 OpenAI 登录页，采用 PKCE（防止授权码被截取后冒用的校验方式），client id、权限范围和重定向地址与 Codex 相同。运行时在本机 1455 端口等待登录回调，将 token（证明登录身份的访问令牌）保存在 `<data_dir>/chatgpt.json`，文件权限为 0600，并在到期前刷新。

`nanomuse chatgpt status` 显示登录账号和有效期，不显示 token；`nanomuse chatgpt logout` 删除凭据。网页控制台连接页的「或者用 ChatGPT 套餐登录」也提供同样流程，分别调用 `POST /api/chatgpt/login`、`GET /api/chatgpt/status`、`POST /api/chatgpt/logout`，见 [web.md](web.md)。登录完成不会自动切换模型。你还需在本文件设置 `provider = "chatgpt"`，在网页选择用于对话，或调用 `PUT /api/connections/llm {"provider": "chatgpt"}`。为手设置 `[gui] provider = "chatgpt"` 的方式相同。

ChatGPT 套餐可用于对话和图片理解，后者供手读取截图。Codex 后端没有图片或视频生成接口，因此这些功能仍需要自己的 key，可配置下面的 `[image]`、`[video]`，或使用支持媒体生成的对话服务商。`chatgpt` 配置中的 `base_url`、`api_key` 会被忽略，日志会给出警告。

**每次登录都会显示的说明**：OpenAI 的条款涵盖在其自家 Codex 中使用 ChatGPT 套餐。其他应用曾被停止此类访问，例如 2026 年 1 月的 OpenCode。如果这种登录方式失效，可以改用 API key。

**登录回调必须送达运行时**。OpenAI 最后会将浏览器跳转至 `http://localhost:1455/auth/callback`。因此，浏览器应与运行时位于同一台电脑，或把该端口转发到运行时。若运行时在服务器、浏览器在笔记本，登录页面仍可完成操作，但最后会跳转到没有服务响应的本机地址。

此时，复制地址栏中的完整地址 `http://localhost:1455/auth/callback?code=…&state=…`，交给运行时。端口被占用或等待超时时，CLI 会提示你输入；带 `--json` 时从标准输入读取一行；网页控制台卡片也有输入框。由 `/api/chatgpt/login` 发起的登录仍在等待时，服务器接受 `POST /api/chatgpt/callback {"url": "<the address>"}`。如果 `state` 与待完成登录不符，会返回 400 `state_mismatch`，不交换任何凭据。

`nanomuse chatgpt proxy` 会把登录后的服务提供为本机 OpenAI 兼容接口，供同一台电脑的其他程序调用，包括 `GET /v1/models`、`POST /v1/chat/completions`、`GET /v1/usage`，通过本地 Bearer token 验证访问。使用 `--proxy` 或 `[llm] proxy`，可让这个服务向上游发出的请求经过代理。

桌面版在浏览器授权完成后保存登录信息，本地代理启动后才会显示 ChatGPT 模型。`nanomuse chatgpt proxy --json` 的 `ready` 事件包含模型列表，桌面版据此注册服务商。能够向 OpenAI 获取列表时使用其返回值，否则使用内置列表。

**查看套餐余量**。OpenAI 按几小时和一周两个用量周期统计使用情况。每次 Codex 响应头都有 `x-codex-primary-used-percent`、`…-window-minutes`、`…-reset-after-seconds`，以及对应的 `secondary` 字段。`GET https://chatgpt.com/backend-api/wham/usage` 也提供用量，Codex CLI 的 `/status` 就读取此接口。`nanomuse chatgpt usage` 显示两个周期，`--json` 返回原始 `{label, plan, limits}`。运行时通过 `GET /api/chatgpt/usage` 提供给控制台，本机代理通过 `GET /v1/usage` 提供。运行时还保留最近一次响应头中的 `CodexClient.limits`，所有缓存都不超过一分钟。

**连接失败时的提示**。Codex 请求失败会被转换为具体说明，不会直接显示底层 socket 错误：网络无法访问 chatgpt.com，可能是 DNS、连接、TLS、超时或收到 HTML 拦截页而非 JSON；OpenAI 不向当前地区提供服务，对应 HTTP 403 `unsupported_country_region_territory`；ChatGPT 登录失效需重新登录，对应 401；套餐暂时用尽，对应说明用量限制的 429，并附 OpenAI 信息和 `Retry-After`；其他 429 则说明同时请求过多。本机代理还会在 `error.code` 中提供 `unreachable`、`region_blocked`、`not_signed_in`、`quota`、`rate_limited`、`upstream`，方便客户端按类别处理。手机会将相同说明显示为卡片，见 [own-key.md](own-key.md#when-the-provider-cannot-be-reached)。

### 工具调用模式 {#tool-calling-modes}

| `tool_mode` | 行为 |
|---|---|
| `auto`（默认） | 使用 API 原生函数调用。如果接口拒绝 `tools` 字段，例如 Ollama 模型没有工具模板并返回 "does not support tools"，或 vLLM 未启用工具解析器，nanoMuse 会记录一次警告，本次运行后续改为在提示词中描述工具 |
| `native` | 始终使用原生函数调用 API，被拒绝时直接报错 |
| `prompt` | 在系统提示词中描述工具，再从 `<tool_call>` 块解析调用。对于忽略 `tools` 却不报错、模型从不调用工具的接口，这是唯一可用方式；部分智能体应用网关采用这种行为 |

### 图片 {#pictures}

聊天附件中的图片会先将长边缩至 1568 px，再作为图片内容发送给模型：Chat Completions 使用 `image_url`，Responses 使用 `input_image`。

默认 `vision = "auto"` 会先尝试发送图片。如果接口拒绝带图请求，例如 DeepSeek 或不支持视觉的 Ollama 模型返回 "model does not support multimodal requests"，程序会只保留文字重新请求，本次运行后续也不再发送图片，并向用户提示一次。模型收到的消息会注明哪些图片不可见，避免它描述未看到的内容。`on` 始终发送图片，拒绝则报错；`off` 从不发送图片，模型只能看到文件名。无论视觉设置如何，文本文件、PDF 和表格都由 `files` 工具读取。

支持的视觉模型包括 GPT-4o 及之后的版本、经 OpenAI 兼容网关调用的 Claude、Gemini、Qwen-VL、`qwen3.8-*`，以及 Ollama 的 `gemma3` 和 `llava`。部分模型可通过 id 预先判断，无需试错：DeepSeek 默认只支持文字，除非 id 包含 `v4.1`、`vision` 或 `ocr`；`qwen*-vl` 和 `qwen3.8-*` 支持图片。

### 本地模型 {#local-models}

Ollama 在 `http://localhost:11434/v1` 提供 OpenAI 兼容 API。带工具模板的模型，例如 Qwen 3、Llama 3.1+、Mistral 和 DeepSeek-R1 蒸馏模型，可以原生调用工具；其余模型使用 `auto` 的提示词备用方式。[`scripts/provider_check.py`](../../scripts/provider_check.py) 可用任意模型测试五种日常任务：对话、用 `python_execute` 计算、写文件、记住偏好及多步骤任务。以下是在 RTX 4070（12 GB）、Ollama 0.34 上的结果：

| 模型 | 工具调用 | provider_check | 说明 |
|---|---|---|---|
| `qwen3:8b` | 原生，`tool_mode = "prompt"` 也通过 5/5 | 5/5 | 默认预设，每项任务 7–20 秒 |
| `llama3.2:3b` | 原生 | 5/5 | 常将调用写成正文中的普通 JSON 对象，或对文件换行重复转义，程序会修正这两种情况，见下文 |
| `gemma3:4b` | `auto` 失败后使用提示词方式 | 5/5 | Ollama 拒绝它的 `tools`，它输出的 ```` ```tool_call ```` 代码块可由提示词解析器读取 |
| DeepSeek V4.1 Flash（托管） | 原生 | 5/5 | 每项任务 1–4 秒 |

小模型有时不能严格遵循工具协议，nanoMuse 会处理已知情况：若回复是普通或代码块中的 JSON 对象，指定了现有工具并包含 arguments 对象，所有模式都将其视为工具调用；JSON 字符串也允许实际换行。`files.write` 遇到单行文本且包含至少两个字面量 `\n` 时，会将其转换为多行；本身已有实际换行的代码不会改动。带有其他键、以引用形式出现的 JSON 对象仍视为文字。

`max_tokens` 应设置为模型单轮能生成的上限，上述模型使用 4096 即可。`agent.max_context_messages` 不宜过大，本地 8B 模型若只有 8k 上下文窗口，加入工具返回值后很快就会填满。上下文窗口指模型一次请求能够处理的全部历史和内容。

如果模型在正文中输出 `<think>…</think>`，程序会分离其中的推理，只在 `agent.show_thinking = true` 时显示。开启后，服务商逐段发送的推理也会实时显示，包括 Chat Completions 中的 `reasoning_content` 和 Responses API 的推理增量。终端会在暗色 `⌗` 行下显示，网页则在聊天气泡中显示。开始回答后，推理折叠到「显示思考」，最终只保存完整推理。

## `[image]` 和 `[video]` {#image-and-video}

这两组配置用于为形象工作室的图片和视频指定独立服务。默认均为空时，遵循 0.1.41 的模型约定，按以下顺序寻找：先使用对话服务商自己的媒体模型，前提是目录标有 `image` 或 `video` 能力，并使用其相应默认模型，旧的 `[llm] image_model` / `video_model` 仍可指定其他模型；再检查已登录中继的实时模型菜单，只有明确提供该媒体类型时才使用；最后使用你添加的第一家支持相应功能的服务商。

公开的 nanoMuse Cloud 菜单不提供图片或视频生成模型，因此用户需要自己的服务商及 API key。自己部署的中继可由运营者明确启用旧媒体代理。填写相应配置，可以改用其他生成服务，也可以为 DeepSeek、ChatGPT 套餐或本地对话模型补充媒体生成功能：

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

目录未收录的服务，可以不填 `provider`，直接指定 `base_url`。`api_key` 会发给这个服务地址。如果视频使用独立服务，则使用 `[video]` 的 key，不会使用图像服务的 key。

没有任何配置能提供某项能力时，该功能不可用，并会说明需要什么服务商。例如在中国大陆，图片功能会提示需要阿里云百炼、智谱 GLM、SiliconFlow 或火山方舟等图像服务商，并指向 `docs/own-key.md`；其他地区列出 OpenRouter、OpenAI、Google Gemini 或 xAI Grok。语言遵循 `[agent] language`。这些说明出现在形象工作室、连接页的「生成图片」「生成视频」下方及 `GET /api/providers` 中，内容和能力都来自目录，会随目录更新。

应用通过 `PUT /api/connections/image`、`PUT /api/connections/video` 设置同样的配置。它们接受四个字段：`provider` 可以是目录 id，或配合 `base_url` 的 `openai` / `openai_responses`；`model` 留空时使用目录默认值；`base_url` 指定服务地址；`api_key` 存入保险库的 `IMAGE_API_KEY` / `VIDEO_API_KEY`，已有 `{{vault:NAME}}` 引用会原样保留，`""` 会删除密钥。四个字段写入 `app-settings.json` 的 `image` / `video` 对象，并覆盖本文件。

响应既包含填写的设置，也包含解析后的 `effective_provider`、`effective_model` 和 `effective_source`，来源可为 `app`、`config`、`chat` 或 `cloud`。`GET /api/connections/image`、`/video` 返回相同结构，`GET /api/connections` 同时返回两组。四项都留空会清除该配置。如果目录明确记录该服务商没有此能力，或选择了 ChatGPT 登录，会返回 400 并说明原因，例如 `DeepSeek has no image models; Pictures need …`。本地服务器及目录未知的地址不作这项限制，因为实际能力取决于你部署的服务。网页控制台的「生成图片」「生成视频」使用的就是这些接口，见 [web.md](web.md)。

## `[agent]` {#agent}

```toml
[agent]
name                 = "nanoMuse"      # what the agent calls itself (the app's profile overrides this)
max_steps            = 30              # tool calls per turn before it must wrap up
# workspace          = "./workspace"   # the only directory the files tool can touch; default ./workspace if present here, else <data_dir>/workspace
extra_roots          = []              # directories outside the workspace the files tool may read and write, e.g. ["~/Documents/notes"]; writable inside the sandbox too
language             = "auto"          # or a fixed language: "English", "中文", ...
max_context_messages = 80
max_context_images   = 4               # screenshots kept in the request: the newest N; 0 keeps all
show_thinking        = false
user_profile         = ""              # free text injected into the system prompt
instructions         = ""              # extra rules appended to the system prompt
```

在 Windows 上，运行时的 `files` 工具和 hub 文件动作会拒绝系统保留设备名，包括 `NUL.txt`，也会拒绝以点或空格结尾的路径部分。遇到这种情况请改名，不要依赖 Windows 自动处理。其他平台遵循各自的文件命名规则。

`language = "auto"` 时，系统提示词会明确告诉模型应使用哪种语言。有客户端随消息传来的界面语言时优先使用它：网页控制台会在 `POST /api/threads/{id}/send` 的 `language` 中传入，hub 的 `task` 也可携带。否则根据最新用户消息的文字判断。部分模型无法可靠执行笼统的「用用户的语言回答」，明确写出语言后才可靠。固定设置的 `language` 优先于上述两种判断。

`max_context_images` 主要限制屏幕操作时的截图数量。每一步都会新增截图，而下一步会重新上传整段对话。0.1.37 时，十几张原尺寸截图曾超出中继请求体限制，返回 413 `too_large`。现在默认只上传最新四张，每张最多两百万像素，旧图替换为一行说明，让模型仍知道该处曾有截图。桌面版 harness 的适配器只接受字节限制，因此将单次请求图片的 base64 总量限制为 2 MiB，约相当于最新四至八张截图，旧图同样以文字说明替代。

`max_context_messages` 尽量在用户消息边界裁去旧历史。如果单轮任务就填满上下文，运行时会保留最新消息，并在截断位置保留完整的一组工具调用和结果。因此，实际条数可能略高于设置，以免拆散这组消息。本轮用户的要求即使落到窗口之外，也会一直留在请求里，长任务不会忘记被要求做什么；到达 `max_steps` 收尾时，模型也仍能看到这一轮做过的工作。已保存的聊天历史不会改变。

## `[sync]` {#sync}

```toml
[sync]
side_chats = false   # off: only the main conversation travels between devices
```

整个账号的同步开关位于应用的数据控制 → 同步。这里设置的是本机「同时同步旁聊」的默认值。关闭时，只上传和拉取主要聊天，旁聊留在创建它的设备，也不会接收其他设备的旁聊。开启后，本机旁聊会同步到账号，也会接收其他设备的旁聊。用户在应用中的选择保存在 `sync.json`，优先于本文件，详见 [every-device.md](every-device.md#the-same-conversations-everywhere)。

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

`[cloud]` 指定运行时登录的中继，见 [cloud.md](cloud.md)。`base_url` 填写中继的公网地址，自己部署后可按 [self-hosting.md](self-hosting.md) 修改。`required = false` 允许不登录账号就完成首次引导，适合完全不使用中继的运行时。`sync` 是账号级「数据控制 → 同步」的默认值，用户选择过后以用户设置为准。

`models = false` 对应控制台的「使用 nanoMuse Cloud 模型」开关，应用中的值保存在 app-settings。关闭后，中继声明的所有模型都会退出自动选择顺序和服务商列表，但账号保持登录。除非主动选择「这次改用 nanoMuse Cloud」，否则不会消耗账号额度。公开的 nanoMuse Cloud 目前只提供对话和界面操作模型，生成图片和视频需要自己的服务商；自建中继可声明其他能力。账号密钥保存在保险库的 `NANOMUSE_CLOUD_KEY`。

`[hub]` 将本机作为账号设备加入设备互联，见 [hub.md](hub.md)。`enabled` 开启后，账号一登录就连接 hub；`remote_control = false` 时，对其他设备只应答 `info`，不允许其他动作；`name` 是其他设备看到的名称，留空使用主机名。`device_id` 每次安装各自生成，由应用写入。

## `[sentinel]` {#sentinel}

哨兵（Sentinel）在操作执行前检查风险，按配置决定允许、询问审批或拒绝。

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

各项规则如何配合，见 [sentinel.md](sentinel.md)。

## `[sandbox]` {#sandbox}

沙箱用于限制命令可以访问的文件和网络。

```toml
[sandbox]
mode = "auto"                        # auto | bwrap | off
```

Linux 安装 [bubblewrap](https://github.com/containers/bubblewrap) 后，例如 `apt install bubblewrap` 或 `dnf install bubblewrap`，每次 `shell`、`python_execute` 都在独立的命名空间中运行。这种隔离下，只有工作区和 `agent.extra_roots` 可写，用户主目录不可见，`/tmp` 为私有目录；只有经评估需要网络的调用才能联网。

`auto` 会在可用时启用沙箱，不可用时在日志中说明；`bwrap` 要求沙箱必须可用，否则 `nanomuse doctor` 报告失败；`off` 则只清理环境变量，直接执行命令，不进行沙箱隔离。`share_read_only` 列出允许读取的目录，例如 `["~/.nvm"]` 可提供 node 和 lark-cli 的安装目录；`share` 列出工具需要写入的目录，例如登录信息所在的 `["~/.lark-cli", "~/.local/share/lark-cli"]`。共享的主目录下路径在沙箱主目录中保持相同相对位置，所以工具仍能通过 `$HOME` 找到它们。更多细节及沙箱中哨兵的行为见 [sentinel.md → 沙箱](sentinel.md#the-sandbox)。

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

记忆默认按关键词检索，少见词权重更高，中文按相邻两个字匹配。如果配置了 embedding 接口，还能按含义查找。Embedding（文本向量化）把文字转换为可比较语义接近程度的数字表示。每条记忆只转换一次，向量和文本哈希保存在 `memory.db`；内容改变后才重新生成，切回曾使用的模型可以复用已有结果。每轮再为当前消息生成向量，将语义接近度与关键词排名合并。例如，即使文字没有相同单词，「写邮件给房东」也能找到「the landlord is Bob Li」。

任何 OpenAI 兼容的 `/embeddings` 接口都可使用，包括 OpenAI，默认 `text-embedding-3-small`，多数网关也采用该默认值；[Ollama](https://ollama.com)，需先运行 `ollama pull qwen3-embedding:0.6b`，该小模型支持中英文，也是 `:11434` 的默认值；OpenRouter 则使用 `openai/text-embedding-3-small`。DeepSeek 不提供向量模型，可将 `embedding_base_url` 指向其他服务，常见做法是搭配本地 Ollama，也可以只用关键词检索。

`auto` 在每次启动时尝试一次接口，失败后改用关键词检索并记录原因，不会每轮重复失败；无法连接的接口会在五分钟后重试。`on` 同样允许检索退回关键词，但会将失败记为警告，并使 `nanomuse doctor` 检查失败。`off` 不生成向量。

`embedding_api_key` 为空时，在模型自身接口使用模型的 key；从应用设置时会保存为 `{{vault:EMBEDDINGS_API_KEY}}`。`llm.extra_headers` 只发往对话模型的服务地址，不会发给这里配置的其他地址。应用的连接 → 按含义召回可配置并测试这些选项；`nanomuse memory recall "…"` 会显示能找到哪些记忆及其接近程度。

## `[skills]` {#skills}

```toml
[skills]
enabled  = true
dir      = ""                        # your skills; empty → <data_dir>/skills
disabled = ["inbox-triage"]          # built-in ones to leave out of the model's list
```

技能是包含 `SKILL.md` 的目录，采用 [Agent Skills](https://agentskills.io) 格式。文件开头的 YAML 元数据包含 `name`、`description`，后面用 Markdown 写操作步骤，因此为其他智能体编写的技能也能使用。

nanoMuse 还会读取 `channel`，说明技能使用哪类操作方式，见[工具选择顺序](gui.md#the-ladder)：`api` 表示 MCP 服务器或连接器，`cli` 表示命令行，`web` 表示网页抓取，`browser` 表示浏览器，`gui` 表示手机屏幕，也接受 `app-only`，`mixed` 表示混合使用。`gui` 技能在索引中标注「在手机屏幕上」，让智能体执行前就知道需要手机。要严格保持通用格式的技能可写 `metadata.channel`。

内置十二个技能：`skill-creator`、`weekly-review`、`trip-plan`、`inbox-triage`、`compare-options`、`meeting-prep`；操作手机屏幕的 `phone-messages`；以及五个可不使用屏幕的中国服务技能：通过 lark-cli 的 `feishu`、通过 tmeet 的 `tencent-meeting`、通过高德 MCP 的 `amap`、通过快递100 的 `kuaidi100`，以及通过 12306 服务器查询、只有明确要求才在手机订票的 `train-tickets`。实际验证过的服务和环境见 [services.md](services.md)。`dir` 中与内置技能同名的目录会替换内置版本。

模型在系统提示中收到所有启用技能的名称和描述。遇到适用请求时，会用 `skills` 工具读取详细步骤；聊天消息以 `/name` 开头则直接调用该技能。从聊天中保存或删除技能属于敏感操作，无论哨兵模式如何，都必须先征求允许。应用中停用的技能保存在 `app-settings.json`，会与此处的停用列表合并。技能目录中的脚本和参考文件在[沙箱](sentinel.md#the-sandbox)内以只读方式提供。另见[应用 → 技能](app.md#skills)和 [CLI](cli.md#skills) 中的 `nanomuse skills`。

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

用 `nanomuse vault set EMAIL_ADDRESS`、`nanomuse vault set EMAIL_PASSWORD` 保存邮箱地址和密码。调用 `read_emails` 后，对话会标为「已污染」，表示其中已包含私密数据，后续外发操作需要相应检查。`send_email` 默认列在 `always_ask_tools`，每次发送都需要审批。

### 日历 {#calendar}

可以使用提供 iCalendar 私密订阅链接的日历，也可读取磁盘上的 `.ics` 文件。支持的来源包括 Google 的设置 → 整合日历 → iCal 格式的私密地址，Outlook 的共享日历 → 发布，iCloud 的共享日历 → 公共日历，以及 Fastmail、Nextcloud。`webcal://` 链接使用 HTTPS 获取。订阅内容缓存在 `<data_dir>/calendar-cache.json`，权限 0600，启动时及刷新间隔内也能查看日程。

日程会包含通过 `RDATE` 额外加入重复事件的日期，也支持全天日期。同一天重复列出时只显示一次，`EXDATE` 仍可排除某一次。带独立持续时间的 `RDATE`，即 `VALUE=PERIOD`，暂不支持，会被跳过。

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

`calendar` 可以读取日程、搜索、查找空闲时间，也能起草事件。草稿写入工作区的 `calendar/<date>-<title>.ics`，应用显示带「加入日历」按钮的卡片，工具本身不会直接修改日历。今天和明天的日程会加入系统提示，也显示在动态的「今天」下。`nanomuse calendar add NAME URL` 与连接页添加订阅的效果相同。

### 联系人 {#contacts}

智能体联系某个人前会先查通讯录，不猜邮箱地址。邮件审批卡片会显示通讯录中的收件人姓名，查不到时提示你。来源为 `.vcf` 文件，可以指定文件路径、从手机上传到 `<data_dir>/contacts/`，或提供保存在保险库中的链接。Google 通讯录的导出 → vCard、iCloud、Outlook 的人员 → 管理 → 导出、Nextcloud、iPhone 的通讯录 → 全选 → 共享，以及 Android 都能导出此类文件。

程序支持 vCard 2.1、3.0、4.0，包括 Apple 的 `item1.` 标签分组，以及旧手机用 quoted-printable 编码保存的姓名。链接返回的内容缓存在 `<data_dir>/contacts-cache.json`，权限 0600。

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

除这些来源外，程序始终保留「我的联系人」，文件为 `<data_dir>/contacts.vcf`。聊天中告诉智能体的人，例如「房东是 Bob Li，bob@example.com」，会通过 `contacts` 的 action=add 加入这里。这是智能体唯一可以写入和删除联系人的通讯录。

`contacts` 可按姓名、昵称、公司、邮箱或电话搜索，要求每个搜索词都匹配，支持前缀，中文姓名中的单个字也可匹配。查询联系人会读取私密数据，因此将对话标为已污染。CLI 对应命令为 `nanomuse contacts search | list | add | sources | add-source | remove-source`。

### 网页搜索 {#web-search}

此处设置 `web_search` 使用的服务商。默认 DuckDuckGo 无需配置，但通过抓取网页获取结果，可能限流或偶尔失效。需要 API 服务时，可选带 key 的 [Brave Search](https://brave.com/search/api/)、[Tavily](https://app.tavily.com/)、[Serply](https://serply.io/)，后者提供 Google 结果；也可选支持无 key 使用的 [You.com](https://you.com/platform/api-keys)、[Parallel](https://docs.parallel.ai/integrations/mcp/search-mcp)、[Keenable](https://docs.keenable.ai/api-reference)，或自己部署 [SearXNG](https://docs.searxng.org/)，并在 `search.formats` 中启用 `json`。

手机的连接 → 网页搜索提供相同选择，key 以 `SEARCH_API_KEY` 存入保险库，点击「测试」会实际搜索一次。

```toml
[connectors.search]
provider = "duckduckgo"          # duckduckgo | brave | tavily | serply | you | parallel | keenable | searxng
api_key  = "{{vault:SEARCH_API_KEY}}"   # brave / tavily / serply，以及有 key 的 you、parallel 或 keenable：nanomuse vault set SEARCH_API_KEY
base_url = ""                    # searxng: your instance, e.g. "http://127.0.0.1:8080"
fallback = true                  # false：搜索失败就失败，不再转去 DuckDuckGo
```

You.com 不带 key 时访问 `api.you.com`，每个地址每天可免费搜索 100 次，无需账号。超限时会说明原因，再由 DuckDuckGo 补查一次。带 key 时访问额度更高的 `ydc-index.io` Search API，哨兵会显示实际访问的地址。按厂商要求，请求的 User-Agent 为 `youdotcom-integration/nano-muse-nanomuse`，用来识别 nanoMuse 流量，不额外发送其他信息，其他服务商也不会收到这个标识。

Parallel 每次搜索调用一次 [Search MCP](https://docs.parallel.ai/integrations/mcp/search-mcp) 的 `web_search`，地址为 `search.parallel.ai`。同一查询同时用作搜索目标和唯一关键词。不带 key 时使用免费 Fast 模式，限流较严格，无需账号；运行时会使用随机会话 id，直到重启都保持相同，供 Parallel 统计免费用量。[platform.parallel.ai](https://platform.parallel.ai/) 提供的 key 以 Bearer token 发送，可提高限额。结果摘要由多段摘录合并为一行。工具错误、限流、key 被拒绝或没有结果时，失败或备用搜索说明会保留相应错误信息。

Keenable 不带 key 时访问 `api.keenable.ai/v1/search/public`，每个地址每小时可搜索 1,000 次，无需账号。超限后会说明原因，由 DuckDuckGo 补查一次。[keenable.ai/console](https://keenable.ai/console) 提供的 key 以 `X-API-Key` 发送到同一主机的 `/v1/search`，解除每小时限制，所以哨兵始终显示 `api.keenable.ai`。每个请求都包含无 key 接口要求的 `X-Keenable-Title: nanoMuse`，用于标识调用应用；除此之外只发送查询和结果数量。摘要取页面正文开头，并整理为一行。

无论选择哪家，搜索因 key 过期、限流或服务不可用而失败时，默认会由 DuckDuckGo 再查一次，并在结果顶部注明，方便任务继续。这意味着查询会同时到达所选服务商和 DuckDuckGo；不希望这样时，在 `[connectors.search]` 中设置 `fallback = false`。`nanomuse doctor` 会指出服务商缺少的必要配置。

工具的 `region` 参数，例如 `cn-zh`、`us-en`，会转换为各家支持的格式，Tavily、Parallel、Keenable 不接受地区参数。搜索服务地址是你主动选定的，因此读取私密数据后，搜索不必像访问未知主机那样再次审批，见[污染追踪](sentinel.md#taint-tracking)。但用 `web_fetch` 访问搜索结果页面时，仍需检查。

## `[triggers]` {#triggers}

触发器是事件发生时自动启动任务的长期指令，例如收到邮件、日程即将开始，或其他程序调用 webhook（向指定接口发送事件通知）。触发器在聊天或「日程」中设置，不在本配置文件中创建，见[应用](app.md#triggers)。本节只调整检查方式。

```toml
[triggers]
mail_poll_minutes = 5    # how often the inbox is looked at while a mail trigger is active
hook_min_seconds  = 10   # deliveries to one webhook closer together than this get HTTP 429
```

邮件触发器需要[邮件连接器](#email)，日程触发器需要[日历](#calendar)，触发器记录保存在 `<data_dir>/triggers.db`。

### 浏览器 {#browser}

```toml
[browser]
enabled    = true      # pip install "nanomuse[browser]" && playwright install chromium
backend    = "auto"    # auto | playwright | device; device: the phone's own WebView when a nanoMuse app is connected, Chromium otherwise
profile    = ""        # mobile | desktop | "" (mobile on the phone, desktop on a computer)
headless   = true      # Playwright only
timeout_ms = 30000
```

Chromium 的登录状态保存在 `<workspace>/browser-profile/`，重启后保留。手机则保存在应用 WebView（嵌入应用的浏览器组件）中。两种后端、用户接管、带登录状态的 `fetch`，以及 WebView 不支持的登录方式，见 [browser.md](browser.md)。

### 操作本机（`[hands]`） {#hands-on-this-computer-hands}

```toml
[hands]
enabled         = false    # the switch is Devices → Hands on this computer in the app
backend         = "auto"   # auto | desktop | pyautogui | xdotool (X11); desktop: the desktop app's own hands (auto takes them when the app set NANOMUSE_OPERATOR_URL)
mode            = "auto"   # auto | screen | window; window: one app's window on macOS, events to its process, your mouse untouched; auto = window on macOS once an app is named
coords          = "pixels" # pixels | norm1000; what the model's x, y mean: pixels of the picture it was shown (default), or a 0–1000 grid over it
max_image_width = 1600
settle_s        = 0.6
```

操作坐标以模型实际看到的图片为准。`computer_screen` 会在第一行及末尾的 *Coordinates:* 行说明图片尺寸；`computer_act` 接受图中的 `x`、`y` 或 `box`。运行时再一次性换算为操作器使用的实际坐标，适配显示缩放。截图先受 `max_image_width` 限制，再对齐 Qwen 缩放使用的 28 像素网格，因此模型指出的位置与图片内容一致，见 [gui.md](gui.md#hands-on-the-computer-the-picture-is-the-unit)。

模型、步数上限和敏感词沿用 `[gui]`。窗口模式、按应用授权的「允许 <Muse> 使用 <App>？」及 `computer_app:<id>` 授权记录，以及 macOS 权限，见 [every-device.md](every-device.md#hands-on-this-computer)。

### 手机（`[gui]`） {#the-phone-gui}

开启后，智能体可以查看已连接手机的屏幕，在应用中点击、输入和滑动。这让它能使用没有 API 的 12306、微信、支付宝等应用。默认关闭，连接页的「手机」卡片控制同一开关。操作流程和哨兵检查见 [gui.md](gui.md)。

```toml
[gui]
enabled          = false
provider         = "openai"          # the operator's own model; openai | openai_responses | chatgpt | a catalogue id
model            = ""                # 留空 = 自动（按下面的顺序：中继的手的模型、聊天服务商自己的、或者聊天模型）；不管是哪个都得能看图，屏幕是一张图
base_url         = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key          = "{{vault:GUI_API_KEY}}"
max_steps        = 0                 # 一次 phone_task 最多走多少步；0 = 不设上限
device_timeout_s = 20.0              # how long to wait for the phone to answer
reconnect_grace_s = 30.0             # 手机掉线后，进行中的任务等它回来多久；0 = 立刻放弃
sensitive_words  = ["确认支付", "立即付款", "转账", "提交订单", "发送", "删除", "pay now", "place order", "send", "delete"]  # a tap on these asks first; 这里是节选，默认列表有 22 个词
```

`base_url`、`api_key` 为空时沿用 `[llm]`。`model` 为空时遵循 0.1.41 模型约定：对话使用中继时，选择 `/v1/models` 为 `gui` 推荐的模型，公开 Cloud 目前推荐与对话相同的多模态 `Qwen/Qwen3.6-27B-FP8`；对话使用自有服务商且目录标有 `vision` 时，使用该服务商的 `defaults.hands`，百炼为 `qwen3.8-27b`，智谱为 `glm-4.6v`，沿用对话 key；对话服务商不能识图，例如按目录 id 或主机判断为本地服务器，而账号已登录，则用账号 key 调用中继的屏幕操作模型，对话模型保持原处；其他情况沿用对话模型，未收录服务地址也如此。

明确填写 `model` 时始终优先。只有操作器的 `base_url` 指向另一项服务时才需单独 key。每次手机任务的轨迹保存在 `<data_dir>/phone-traces/`，保留最近 200 条，可用 `nanomuse phone traces` 查看。

应用通过 `PUT /api/connections/gui` 保存此配置，`provider` 规则与 `PUT /api/connections/llm` 相同：可以填 `openai`、`openai_responses` 协议，`chatgpt`，或 `bailian` 等目录 id。目录 id 自带接口地址，`base_url` 可以留空。不在目录中或运行时不支持其协议的 id 会返回 400，并列出可选项。响应及 `GET /api/connections` 的 `gui` 中，包含原始 `provider`、由协议与 URL 对应到的目录 `provider_id`、`effective_model`，以及 `effective_source`，来源为 `gui`、`chat` 或 `cloud`。

### MCP 服务器 {#mcp-servers}

支持 [Model Context Protocol](https://modelcontextprotocol.io) 的服务可以接入为 `<server>__<tool>` 工具。每次调用都按你指定的风险等级经过哨兵检查。

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
connect_timeout_s  = 30           # 握手（连接、initialize、工具列表）的秒数；超时就跳过这个服务器
call_timeout_s     = 120          # 一次调用的秒数；超时这次调用失败，任务继续

# one tool of a server may differ from the server's defaults
[mcp.servers.tools.list_events]
risk               = "moderate"
[mcp.servers.tools.delete_event]
risk               = "sensitive"
reads_private_data = false
```

不填 `egress` 时，程序根据地址判断是否向外发送数据：`url` 指向其他主机时，每次调用的参数都会发过去，因此算作向该主机外发；如果对话已读取私密数据，污染追踪会要求先审批，除非该主机在 `egress_allowlist` 中。通过 `command` 启动的本地程序或回环地址默认不算外发。你也可以显式设置 `egress` 覆盖判断。审批卡片和审计日志只记录工具名与参数结构，例如字符串长度、列表长度、对象键，不记录参数值。

可选的 `tools` 配置按工具名填写，不含 `<server>__` 前缀，未指定的项沿用服务器默认值。手机内置工具也用这个机制：应用能力无需配置即以 `device` 服务器出现，见 [device.md](device.md)，各工具的默认值来自 `nanomuse/runtime.py`。

需要 key 的命令通过 `env` 获取，真实 key 存入保险库。例如 `env = { AMAP_MAPS_API_KEY = "{{vault:AMAP_KEY}}" }` 仅在启动服务器时解析，不会将真实值写入磁盘或显示在应用中。连接页添加服务器也会自动这样处理：每个输入的 `env` 值存到保险库的 `MCP_<SERVER>_<KEY>`，名称全部大写，例如 `amap` 与 `AMAP_MAPS_API_KEY` 组成 `MCP_AMAP_AMAP_MAPS_API_KEY`，`app-settings.json` 只保留 `{{vault:...}}`。移除服务器也会删除对应保险库条目。已经是引用的输入保持原样。`config.toml` 中的明文值仍可使用，但连接页会标出该服务器，提醒你移入保险库。

无法响应的服务器会记录日志并跳过，智能体仍会启动，只是没有该服务的工具。日志会标明服务器名称及传输错误，将所有 URL 查询参数值隐藏为 `?key=***`，并移除保险库敏感值，避免被拒绝的 key 写进 `logs/`。

内置技能使用的三个中国服务通过 MCP 提供，`config/config.example.toml` 含有相应配置：高德地图是托管服务，`AMAP_KEY` 放保险库；12306 使用 `npx -y 12306-mcp`，无需 key，只能查票；快递100 是托管服务，使用 `KUAIDI100_KEY`，按快递单号付费。哪些服务已在手机根文件系统中实际运行，以及其他可选服务，见 [services.md](services.md)。

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

`update_check` 每天检查一次最新版本，优先访问下载镜像索引 `nanomuse.cn/dl/index.json`，没有响应时再访问 `api.github.com`。点击「现在检查」可以提前检查；失败时，例如运行时先于网络启动，会在一小时后重试。结果显示在设置 → 关于，包含版本号和发布页链接。检查不会下载安装文件，也不会发送安装信息，请求的 `User-Agent` 只携带运行时版本号。设置 `NANOMUSE_NO_UPDATE_CHECK=1` 也能关闭。通过 `NANOMUSE_CLOUD_KEY` 启动的托管网页会话从不检查，由运营者负责更新。

这些设置仅适用于 Python 运行时。Windows 桌面外壳会在启动后及每六小时独立检查。它默认开启自动下载并保存开关状态，但计费或未知网络需要用户主动下载，见[桌面版](desktop.md#updating-on-windows)。

## 数据保存在哪里 {#where-things-live}

| 路径 | 内容 |
|---|---|
| `~/.nanomuse/`（`data_dir`） | 以下数据的根目录 |
| `memory.db`、`goals.db` | SQLite 数据库 |
| `vault.enc`、`vault.key` | 加密的敏感信息和加密密钥，也可使用 `NANOMUSE_VAULT_KEY` |
| `audit.jsonl` | 只追加、不覆盖的审计日志 |
| `approvals.json` | 已授予 24 小时或永久的权限，包含工具、目标、范围、到期时间 |
| `app-settings.json` | 应用连接页的设置，覆盖 `config.toml`，只有 `{{vault:NAME}}` 引用，没有真实密钥 |
| `chatgpt.json` | ChatGPT 登录 token，权限 0600，`nanomuse chatgpt logout` 可删除 |
| `sessions/` | CLI 对话历史 |
| `skills/<name>/SKILL.md` | Agent Skills 格式的自定义技能，同名时替换内置技能 |
| `threads/`、`profile.json`、`ideas.json`、`server_token`、`logs/` | 应用状态 |
| `./workspace`（`agent.workspace`） | 智能体读写的文件；`screenshots/` 保留手机最近发送的 400 张截图，手机轨迹会引用这些文件 |
