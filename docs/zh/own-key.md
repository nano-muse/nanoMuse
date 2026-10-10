# 换成自己的 key

nanoMuse 免费、非营利。它背后的模型要花钱，每个账号的起始额度由开发者出（应用里显示的是中继当前的数字）。额度用完以后，有两条路可以继续走，都不需要 nanoMuse 再提供什么：在某家模型服务商申请一把自己的 key，或者用你已经在付费的套餐——ChatGPT、Claude、Kimi——在应用里登录。

每个客户端读的都是同一份服务商清单，每家能做什么也写在里面：**对话**、**动手**（一个能看截图的模型）、**画图**（形象工作室）和**视频**（形象的短视频）。没有任何已配置的服务商能做的功能，就干脆不提供，只用一句话说明哪些服务商可以——什么都不会坏。

你的登录、邀请码和设备都不受影响：账号还是那个账号，换的只是模型服务商。用上自己的 key 或套餐之后，你说的话不再经过 nanoMuse Cloud。

## 先看你在哪 {#where-you-are-decides-who-comes-first}

| | 首选 | 一把 key 能做什么 |
|---|---|---|
| 中国大陆 | **阿里云百炼** | 对话、动手、画图、生成视频——四样都在一把 key 下 |
| 海外 | **OpenRouter**，其次 **OpenAI** | 对话、动手、画图；生成视频目前只有百炼 |

百炼只给中国大陆身份注册；海外用户一个 OpenRouter 账号就能用到几百个模型，按量付费。首选之外，下面的每一家都可以单独用，或者和另一家搭配——比如对话用 DeepSeek、画图用智谱。

四件事、四个设置、一个页面：Android、iPhone 和桌面版都是 **设置 › 模型**，网页控制台是「连接」页。四行分别是「对话」「操作屏幕」「生成图片」「生成视频」；每行显示 `服务商 · 模型`，点开是一个只列能做这件事的模型的选择器（操作屏幕需要能看图的模型）。iPhone 上「操作屏幕」这一行是灰的（「不在 iPhone 上」）：手机不能操作自己的屏幕，电脑用它自己的设置。细节见下面的[哪个模型做哪件事](#which-model-does-what)。

## 各家服务商能做什么 {#what-each-provider-covers}

对话 = 聊天；动手 = 看截图操作手机和电脑；画图 = 形象工作室的图片；视频 = 形象的短动画。

| 服务商 | 对话 | 动手 | 画图 | 视频 | 地区 | 申请 key |
|---|:-:|:-:|:-:|:-:|---|---|
| 阿里云百炼 | ● | ● | ● | ● | 中国大陆 | [bailian.console.aliyun.com](https://bailian.console.aliyun.com/?apiKey=1) |
| DeepSeek | ● | ● | | | 都可以 | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| Kimi（月之暗面） | ● | ● | | | 都可以（国内 / 国际两个版本） | [platform.moonshot.cn](https://platform.moonshot.cn/console/api-keys) · [platform.kimi.ai](https://platform.kimi.ai/console) |
| 智谱 GLM | ● | ● | ● | | 中国大陆 | [open.bigmodel.cn](https://open.bigmodel.cn/usercenter/apikeys) |
| 硅基流动 | ● | ● | ● | | 中国大陆 | [cloud.siliconflow.cn](https://cloud.siliconflow.cn/account/ak) |
| 火山方舟（豆包） | ● | ● | ● | | 中国大陆 | [console.volcengine.com](https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey) |
| MiniMax | ● | ● | | | 都可以（国内 / 国际两个版本） | [platform.minimaxi.com](https://platform.minimaxi.com/user-center/basic-information/interface-key) |
| OpenRouter | ● | ● | ● | | 海外 | [openrouter.ai/keys](https://openrouter.ai/keys) |
| OpenAI | ● | ● | ● | | 海外 | [platform.openai.com](https://platform.openai.com/api-keys) |
| Anthropic Claude | ● | ● | | | 海外 | [platform.claude.com](https://platform.claude.com/settings/keys) |
| Google Gemini | ● | ● | ● | | 海外 | [aistudio.google.com](https://aistudio.google.com/apikey) |
| xAI Grok | ● | ● | ● | | 海外 | [console.x.ai](https://console.x.ai) |
| Groq | ● | ● | | | 海外 | [console.groq.com](https://console.groq.com/keys) |
| Mistral AI | ● | ● | | | 海外 | [console.mistral.ai](https://console.mistral.ai/api-keys) |
| OpenCode Zen | ● | | | | 海外 | [opencode.ai/auth](https://opencode.ai/auth) |
| Ollama / LM Studio / vLLM（本机） | ● | | | | 都可以 | 不需要 key |

「视频」一栏只有百炼，是因为 nanoMuse 的视频生成走的是百炼的接口；其他家的视频模型用的是各自的任务接口，这一轮还没有接。「画图」一栏里，OpenRouter 走的是它的 Image API，模型例如 `openai/gpt-image-2`；Gemini 用 `gemini-2.5-flash-image`。

这张表来自仓库里的目录文件 [`nanomuse/llm/providers.json`](../../nanomuse/llm/providers.json)——每个客户端、中继都读它，地址、默认模型和「能做什么」都在里面；表里的事实在 2026 年 10 月对照各家文档核过。

## 怎么申请 key {#making-a-key}

每家的步骤都是一样的三步：注册 → 控制台里创建 API key → 复制到 nanoMuse。**key 只给 nanoMuse 用，不要发给任何人、不要贴到聊天里。**

- **阿里云百炼。** 用阿里云账号登录 [bailian.console.aliyun.com](https://bailian.console.aliyun.com/)（要实名认证），首次进入点「开通百炼服务」，再到 [API-KEY 页](https://bailian.console.aliyun.com/?apiKey=1) 创建；key 以 `sk-` 开头。新账号有一段时间的免费 token。建议在控制台设一个用量告警。
- **DeepSeek。** [platform.deepseek.com](https://platform.deepseek.com/) 注册、充值、API Keys 里创建。地址 `https://api.deepseek.com/v1`。
- **Kimi。** 国内版在 [platform.moonshot.cn](https://platform.moonshot.cn/console/api-keys)，地址 `https://api.moonshot.cn/v1`；国际版在 [platform.kimi.ai](https://platform.kimi.ai/console)，地址 `https://api.moonshot.ai/v1`。两个版本的账号和 key 不通用。
- **智谱 GLM。** [open.bigmodel.cn](https://open.bigmodel.cn/usercenter/apikeys)，地址 `https://open.bigmodel.cn/api/paas/v4`。
- **硅基流动。** [cloud.siliconflow.cn](https://cloud.siliconflow.cn/account/ak)，地址 `https://api.siliconflow.cn/v1`；模型 id 带厂商前缀，例如 `deepseek-ai/DeepSeek-V4-Flash`。
- **火山方舟。** [console.volcengine.com](https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey)，先在方舟里开通要用的模型，再创建 key；地址 `https://ark.cn-beijing.volces.com/api/v3`。
- **MiniMax。** 国内版 [platform.minimaxi.com](https://platform.minimaxi.com/user-center/basic-information/interface-key)，地址 `https://api.minimaxi.com/v1`；国际版地址 `https://api.minimax.io/v1`。
- **OpenRouter。** [openrouter.ai](https://openrouter.ai/) 用 Google、GitHub 或邮箱登录，*Credits* 里充值，*Keys* 里创建；key 以 `sk-or-v1-` 开头。*Settings → Limits* 可以给 key 设每月上限。
- **OpenAI。** [platform.openai.com](https://platform.openai.com/api-keys)，地址 `https://api.openai.com/v1`。
- **Anthropic。** [platform.claude.com](https://platform.claude.com/settings/keys)。nanoMuse 直接用 Anthropic 的接口，不需要兼容层。
- **Google Gemini。** [aistudio.google.com/apikey](https://aistudio.google.com/apikey)，地址 `https://generativelanguage.googleapis.com/v1beta/openai`。
- **xAI、Groq、Mistral。** 各自的控制台创建 key；地址分别是 `https://api.x.ai/v1`、`https://api.groq.com/openai/v1`、`https://api.mistral.ai/v1`。
- **OpenCode Zen。** 在 [opencode.ai/auth](https://opencode.ai/auth) 申请 key；按请求从余额里扣费，有几个模型免费。地址 `https://opencode.ai/zen/v1`。只有 OpenAI 格式的那些模型到得了，所以只有对话、没有动手：OpenCode 列出的视觉模型 `deepseek-v4-flash-vision-exp` 在 DeepSeek 自家平台上已经退役。OpenCode 没有套餐登录，只有 key，所以这里没有可以登录的东西。同一域名上的订阅 OpenCode Go 不在目录里：OpenCode 把它定位给编程智能体，要求客户端自报身份并在每次请求里用 `x-opencode-session` 传会话 id，nanoMuse 目前还不发。

**贴到 nanoMuse 里。**

- 手机：额度用完时卡片上的「去设置」会打开预填好的服务商表单；或者 设置 → 服务商 → 添加，选服务商，贴 key，保存。
- 桌面版：额度卡片上的「去设置」会打开 设置 → nanoMuse Cloud 并停在那家服务商的一行；或者直接在那里「可用的途径」下面那家服务商的一行里贴 key。地址已经填好。
- 网页控制台：额度卡片上的「去设置」会打开「连接」页并选好服务商；或者 连接 → 对话模型，点服务商，贴 key，保存。
- 自己跑的运行时：在 `config.toml` 里写 `[llm] provider = "bailian"`（表里任一服务商的 id）加 `api_key`，地址和默认模型会从目录文件里补上；画图、生成视频用另一家，就加 `[image]` / `[video]` 一段（[configuration.md](configuration.md#image-and-video)）。

**用它来做什么。** key 保存好之后，会弹出一张卡片问这把 key 负责哪些事：这家服务商能做的每件事一个开关（对话、操作屏幕、生成图片、生成视频），默认全开。「就这样」把勾上的几行切到这家服务商，每件事用目录里的默认模型（目录里的默认模型不在它的列表里时，用列表里第一个能做这件事的）；「暂不」什么都不改，关掉的开关也什么都不改。登录了 nanoMuse Cloud 的话，卡片会说其余仍由 nanoMuse Cloud 负责。每一行以后都可以在 设置 › 模型 里改（网页控制台：「连接」页）。

## 哪个模型做哪件事 {#which-model-does-what}

设置 › 模型（Android：设置顶部的那张卡；iPhone：设置的第一张卡；桌面版：紧跟「通用」；网页控制台：「连接」页上的「对话模型」「手的模型」「生成图片」「生成视频」几张卡）一件事一行：

| 行 | 做什么 | 列出谁 |
|---|---|---|
| 对话 | 和你说话的模型。 | 登录且开着 nanoMuse Cloud 模型时先是它的对话模型，然后是你每一家有对话模型的服务商 |
| 操作屏幕 | 看着屏幕替你操作，需要能看图的模型。 | nanoMuse Cloud 的手的模型，然后是你的服务商里能看图的模型；iPhone 上是灰的（「不在 iPhone 上」） |
| 生成图片 | 形象的肖像，以及你要的图片。 | nanoMuse Cloud，然后是你有图像模型的服务商 |
| 生成视频 | 形象的短视频。 | nanoMuse Cloud，然后是你有视频模型的服务商（百炼） |

每行显示 `服务商 · 模型`，点开是选择器：登录时 nanoMuse Cloud 一组在最前，推荐的那个有标记，然后你的每家服务商一组，只列能做这件事的模型。没有这项能力的服务商在这一行里根本不出现。一行里什么都没有时，显示那句「谁能提供」的话和「添加服务商」。对话这一行选了，就是新对话的默认，主要聊天也跟着走（「对主要聊天和新对话生效；旁聊保留自己的模型。」）：主要聊天是聊天标签页始终显示的那一个对话，永远不算「新对话」，不这样的话就会一直停在它开始时的服务商上；已经打开的旁聊保留它的模型。手机和桌面版都是这样。iPhone 上你的模型组可以带一个默认思考等级（「全部设置 › 模型组」），主要聊天跟着选择走的时候，这个等级一起带过去，和新对话、对话自己的选择器一样。

**自动。** 操作屏幕、生成图片、生成视频三行打开时第一项是「自动」，写着它现在给的是什么（比如「当前为 nanoMuse Cloud · qwen3.8-27b」）。选它，这一行忘掉在这里做过的选择，按一个顺序走：对话模型所在的服务商是你自己的、而且能做这件事时用它（目录里的默认模型）；否则登录且开着 nanoMuse Cloud 模型时用它；否则用你第一家能做这件事的服务商。你做过的选择永远优先；nanoMuse Cloud 不会排到你选的服务商前面。每台设备各自选，因为 key 不会离开录入它的那台设备。

**不会悄悄回退。** 你自己的模型在某一轮失败时，什么都不会自动切换：错误卡片上多一个按钮「这次改用 nanoMuse Cloud」（只在登录时出现），只把这一轮放到账号的模型上重跑，不改任何一行。桌面版在形象工作室的一轮失败和一组短视频失败之后也给同一个按钮。

**思考深度（桌面版）。** 输入框的模型选择器会给你自己的模型提供思考深度，前提是服务商的文档写明了怎么控制，发送时用的也是服务商自己的字段：DeepSeek、Kimi（kimi-k3）、智谱（GLM-5.2 和 5.3）、硅基流动和火山引擎（它们的 DeepSeek-V4、GLM-5.2 以及豆包 Seed 2）、MiniMax（M3.1）、OpenRouter（按它模型列表里每个模型给出的档位）、OpenAI（o 系列、GPT-5 起）、Anthropic（Claude 4.6 起）、走 OpenAI 兼容层的 Gemini、xAI（Grok 4.5 起）、Groq、Mistral，以及 Ollama 或 vLLM 上的 gpt-oss。档位就是服务商自己的（比如 DeepSeek 是 `low`、`high`、`max`），「服务商默认」什么都不发，模型按服务商文档里的默认方式思考。没有「关闭」这一项：在这些服务商那里，关掉思考是另一个开关或另一个模型。没有文档写明档位的模型不显示这个控件，百炼（它的开关是 `enable_thinking`，没法不发）、LM Studio 和自定义端点也不显示。在这个版本之前保存的 key，下次启动时会拿到这个控件。

**关掉 nanoMuse Cloud。** 登录时，模型页上有一个开关「使用 nanoMuse Cloud 模型」。关掉之后，nanoMuse Cloud 从选择器和自动顺序里退出，任何附带的调用（对话标题、记忆、形象、动手）都不会在它上面运行，唯一会消耗额度的是「这次改用 nanoMuse Cloud」这个按钮，而且只在你每次点它的时候。账号保持登录：同步、你的设备和账号页照常工作。nanoMuse Cloud 这家服务商不能像你自己添加的那样删除（删除它就等于退出登录）；退出登录在「设置 › nanoMuse Cloud」里。

**不用账号。** 有自己的 key，应用在未登录时一样能用：对话、动手、生成图片和短视频都跑在你的服务商上，第一屏在登录旁边给了「改用自己的 API key」。只有 nanoMuse Cloud 的模型、对话同步和设备互通才需要登录。

**已知的限制。** iPhone 上生成图片、生成视频两行除了 nanoMuse Cloud，只列你在 DashScope 主机上的服务商（阿里云百炼）；目录里说能画图的 key（OpenRouter、OpenAI、Gemini、自定义接口）会在选择页下方用一句「此处不提供：……」点名，并说明它在哪里能用，免得你以为手机把它弄丢了。桌面版的手只说 OpenAI 的接口形状，所以 Anthropic 和原生 Gemini 的 key 在操作屏幕那一行下面用一句话点出来、不列进去；手的改动在手的下一步生效，不用重启。用 Gemini 的 key 画图走的是 Google 的 OpenAI 兼容层：`images/generations` 接受 `gemini-2.5-flash-image`，但 Google 的页面没有写明那里有 `images/edits`，所以形象工作室里的姿势图用 Gemini 的 key 可能画不出来。

## 用你已经在付费的套餐登录 {#sign-in-with-a-plan-you-already-pay-for}

有些套餐可以直接登录使用，不用申请 key：

| 套餐 | 能做什么 | 哪里可以登录 |
|---|---|---|
| **ChatGPT**（Plus / Pro / Team） | 对话、动手 | Android、iPhone、桌面版、网页版 |
| **Claude**（Pro / Max） | 对话、动手 | Android、iPhone |
| **Kimi** | 对话、动手 | Android、iPhone（设备码登录） |
| **OpenRouter** | 对话、动手、画图 | Android、iPhone（一键登录，key 自动回到 App） |

ChatGPT 登录走的是 OpenAI 自家 Codex 的授权流程（网页控制台：连接 → 「或者用 ChatGPT 套餐登录」；桌面版：设置 → nanoMuse Cloud 里的 ChatGPT 一行；手机：设置 → 服务商 → OpenAI → 登录）。登录后只有对话和动手：Codex 这条通道没有图像和视频接口，画图和生成视频仍要配一把 key。

在终端里也可以：`nanomuse chatgpt login` 打开登录页并等浏览器回来，`nanomuse chatgpt status` 看登录的是谁、什么时候过期，`nanomuse chatgpt logout` 忘掉它；然后在 `config.toml` 里写 `[llm] provider = "chatgpt"`（不用 `base_url`、`api_key`，`model` 留空就是 `gpt-5.6-sol`）。浏览器要能访问运行时所在机器的 1455 端口；运行时在别的机器上时，把浏览器最后停在的那个地址整条复制下来，贴给命令行的提示，或者 `POST /api/chatgpt/callback {"url": …}`（[configuration.md](configuration.md#a-chatgpt-plan-instead-of-a-key)）。

**一句老实话。** OpenAI 的条款只允许在它自家的 Codex 里使用 ChatGPT 套餐；其他应用曾被切断过这条路（OpenCode，2026 年 1 月）。哪天它不能用了，API key 仍然可以。

## 服务商连不上的时候 {#when-the-provider-cannot-be-reached}

有些网络到不了 `chatgpt.com`（DNS 不解析、连接超时、TLS 失败、返回的是一张 HTML 拦截页），有些地区 OpenAI 直接拒绝（HTTP 403 `unsupported_country_region_territory`）。这时手机上的对话不再显示 socket 原文，而是一张卡片：发生了什么（「这个网络连不上 chatgpt.com」或「OpenAI 不向这个地区提供服务」）、能帮上忙的（这台手机上的 VPN；应用自己的代理，设置 → 网络；换一个服务商、用自己的 key）、一个「重试」按钮，原始错误收在「详情」里供提 issue 用。登录失效（401）显示「ChatGPT 登录已失效」和「重新登录」；套餐这几个小时的余量用完（429 且写明 usage limit）显示「ChatGPT 套餐暂时没有余量了」、OpenAI 自己的那句话和多久后恢复；其他 429 是「同时发出的请求太多」。自己的 key 遇到同样的网络问题，卡片一样出现，只是主机名换成那家服务商的。

**设置 → 网络 → 自有服务商的 HTTP 代理**（Android 和 iPhone 都有）：主机、端口、可选的用户名和密码，默认关闭，只存在这台手机上。只有发往你用自己 key 添加的服务商和 ChatGPT 套餐的请求走它；nanoMuse Cloud、你的电脑和局域网从不经过它。页面上有一行「测试」，通过这个代理抓一次 `https://chatgpt.com/`，告诉你通没通、多少毫秒。同一个设置在每个应用里都放在存 key 的地方：手机在服务商表单里；桌面版在**设置 → nanoMuse Cloud → 网络**，一个地址（`http://host:port` 或 `socks5://host:port`），应用在下次启动时写进它的 Host 进程——这一行下面有「立即重启」——于是每把自己的 key、ChatGPT 登录、手的运行时和这个应用对外发出的其他请求都走它，nanoMuse 云端永远不走（[desktop.md](desktop.md)）；网页版在自有 key 表单里有「代理」一栏；运行时是 `config.toml` 里的 `[llm] proxy`（[configuration.md](configuration.md#llm)）。

## 本机模型 {#local-models}

Ollama、LM Studio、vLLM 跑在自己电脑上的模型也能用：选对应的预设（网页控制台：「连接」；桌面版：设置 → nanoMuse Cloud；手机：设置 → 服务商），地址默认是本机端口（`http://127.0.0.1:11434/v1`、`:1234`、`:8000`），不需要 key。它们算「对话」；手的模型要能看图，本机跑一个多模态模型（例如 Ollama 的 `qwen3-vl`）再在「操作屏幕」里选它（网页控制台：在「手的模型」里手填 id）。画图和视频需要上面表里的一家。

## 其他 OpenAI 兼容服务 {#any-other-openai-compatible-endpoint}

任何 OpenAI 兼容接口都能填，选「自定义」：

| 字段 | 填什么 |
|---|---|
| 地址（Base URL） | 服务商给的地址，通常以 `/v1` 结尾 |
| API key | 服务商控制台里创建的 key（本机服务可以留空） |
| 模型 | 保存后从列表里选；接口列不出模型时，表单会请你填模型 id（逗号分开），再按这些保存 |

自定义接口能做什么由你来说：nanoMuse 会把它当作对话；手的模型、图片模型、视频模型各自填了 id 才算有。
