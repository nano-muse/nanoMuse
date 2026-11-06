# 使用自己的 key {#换成自己的-key}

nanoMuse 免费、非营利，但调用模型需要付费。开发者为每个账号承担一笔起始额度，具体金额以 App 显示的中继数据为准。中继是负责账号和设备间通信的服务器。额度用完后，可以直接使用模型服务商的 key（调用服务所需的密钥），或在 App 中登录已经付费的 ChatGPT、Claude、Kimi 等套餐，无需 nanoMuse 再提供额度。

所有客户端共用一份服务商目录，标明各家的能力：对话、屏幕操作（模型根据截图决定如何操作）、图片生成（用于形象工作室）、视频生成（用于形象短视频）。如果当前没有配置支持某功能的服务商，界面会暂不提供该功能，并说明哪些服务商支持它，其他功能照常使用。

切换服务商不会影响登录、邀请码或设备连接，账号仍然保留。使用自己的 key 或套餐时，模型请求不再经过 nanoMuse Cloud。

## 按地区推荐服务商 {#where-you-are-decides-who-comes-first}

| | 首选 | 一把 key 能做什么 |
|---|---|---|
| 中国大陆 | **阿里云百炼** | 对话、动手、画图、生成视频，四样都在一把 key 下 |
| 海外 | **OpenRouter**，其次 **OpenAI** | 对话、动手、画图；生成视频目前只有百炼 |

百炼注册要求中国大陆身份。其他地区可使用 OpenRouter，一个账号、一份 key 即可按量调用数百个模型。除推荐项外，下表的服务商也可单独使用或组合使用，例如用 DeepSeek 对话、用智谱生成图片。

Android、iPhone 和桌面版都在 设置 → 模型 配置；网页控制台则在「连接」页配置。四项分别为「对话」「操作屏幕」「生成图片」「生成视频」，各自显示 `服务商 · 模型`。点开后只会列出具备该项能力的模型，例如屏幕操作必须选能看图的模型。iPhone 不能操作本机屏幕，因此该项不可选，并显示「不在 iPhone 上」；远程电脑使用电脑自身的设置。详见[哪个模型负责什么](#which-model-does-what)。

## 各服务商支持的能力 {#what-each-provider-covers}

下表的「对话」指聊天；「动手」指根据截图操作手机或电脑；「画图」指生成形象工作室图片；「视频」指生成形象短视频。

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
| OpenCode Go | ● | | | | 海外 | [opencode.ai/auth](https://opencode.ai/auth) |
| Standard Compute | ● | | | | 海外 | [standardcompute.com](https://standardcompute.com/dashboard/api-keys) |
| API Route | ● | | | | 海外 | [api-route.com](https://www.api-route.com/api-keys) |
| Cheaper Inference | ● | | | | 海外 | [cheaperinference.com](https://cheaperinference.com/signup) |
| Opper | ● | | | | 海外 | [platform.opper.ai](https://platform.opper.ai) |
| AtmoRouter | ● | | | | 海外 | [atmorouter.dev](https://atmorouter.dev/dashboard/keys) |
| Ollama / LM Studio / vLLM（本机） | ● | | | | 都可以 | 不需要 key |

视频一栏只有百炼，是因为 nanoMuse 当前接入的是百炼视频 API（程序调用服务的接口）。其他厂商的视频模型使用各自的任务接口，本轮尚未接入。图片方面，OpenRouter 使用 Image API，例如 `openai/gpt-image-2`；Gemini 使用 `gemini-2.5-flash-image`。

表格来自仓库目录 [`nanomuse/llm/providers.json`](../../nanomuse/llm/providers.json)。客户端和中继都读取它，其中包括接口地址、默认模型及支持能力，相关信息已在 2026 年 10 月对照厂商文档核验。

## 创建 key {#making-a-key}

基本流程都是：注册服务商账号，在控制台创建 API key，再填入 nanoMuse。**key 只应填在 nanoMuse 的配置中，不要发给他人，也不要粘贴进聊天**。

- **阿里云百炼**。 用已完成实名认证的阿里云账号登录 [bailian.console.aliyun.com](https://bailian.console.aliyun.com/)，首次进入先选择「开通百炼服务」，再到 [API-KEY 页](https://bailian.console.aliyun.com/?apiKey=1) 创建 key，其开头为 `sk-`。新账号会在一定期限内获得免费 token，token 是模型输入和输出的计量单位。可在控制台设置用量告警。
- **DeepSeek**。 在 [platform.deepseek.com](https://platform.deepseek.com/) 注册、充值并创建 key，基础地址为 `https://api.deepseek.com/v1`。
- **Kimi**。 中国大陆版在 [platform.moonshot.cn](https://platform.moonshot.cn/console/api-keys) 创建 key，地址为 `https://api.moonshot.cn/v1`；国际版在 [platform.kimi.ai](https://platform.kimi.ai/console)，地址为 `https://api.moonshot.ai/v1`。两版账号和 key 不通用。
- **智谱 GLM**。 在 [open.bigmodel.cn](https://open.bigmodel.cn/usercenter/apikeys) 创建 key，地址为 `https://open.bigmodel.cn/api/paas/v4`。
- **硅基流动**。 在 [cloud.siliconflow.cn](https://cloud.siliconflow.cn/account/ak) 创建 key，地址为 `https://api.siliconflow.cn/v1`。模型 id 含厂商前缀，例如 `deepseek-ai/DeepSeek-V4-Flash`。
- **火山方舟**。 打开 [console.volcengine.com](https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey)，先开通所需模型，再创建 key。地址为 `https://ark.cn-beijing.volces.com/api/v3`。
- **MiniMax**。 中国大陆版在 [platform.minimaxi.com](https://platform.minimaxi.com/user-center/basic-information/interface-key) 创建 key，地址为 `https://api.minimaxi.com/v1`；国际版地址为 `https://api.minimax.io/v1`。
- **OpenRouter**。 用 Google、GitHub 或邮箱登录 [openrouter.ai](https://openrouter.ai/)，在「Credits」充值，再到「Keys」创建 key，其开头为 `sk-or-v1-`。「Settings → Limits」可以为 key 设置每月用量上限。
- **OpenAI**。 在 [platform.openai.com](https://platform.openai.com/api-keys) 创建 key，地址为 `https://api.openai.com/v1`。
- **Anthropic**。 在 [platform.claude.com](https://platform.claude.com/settings/keys) 创建 key。nanoMuse 直接调用 Anthropic 原生 API，无需兼容层。
- **Google Gemini**。 在 [aistudio.google.com/apikey](https://aistudio.google.com/apikey) 创建 key，地址为 `https://generativelanguage.googleapis.com/v1beta/openai`。
- **xAI、Groq、Mistral**。 在各自控制台创建 key，地址依次为 `https://api.x.ai/v1`、`https://api.groq.com/openai/v1`、`https://api.mistral.ai/v1`。
- **OpenCode Zen**。 从 [opencode.ai/auth](https://opencode.ai/auth) 获取 key，按请求从余额扣费，部分模型免费。地址为 `https://opencode.ai/zen/v1`。此处只接入 OpenAI 格式的模型，只支持对话。OpenCode 列出的视觉模型 `deepseek-v4-flash-vision-exp` 已被 DeepSeek 在自家平台停用，因此不提供屏幕操作。OpenCode 只提供 key，没有可供这里使用的套餐登录方式。
- **OpenCode Go**。 在 OpenCode 控制台订阅 Go（每月 10 美元）或 Go Plus（每月 40 美元），再从 [opencode.ai/auth](https://opencode.ai/auth) 获取 key。地址为 `https://opencode.ai/zen/go/v1`。用量按模型统计，分别受月、周、五小时上限约束。Go 面向编程助手，要求客户端提供名称，并在 `x-opencode-session` 请求头中为每段对话发送固定 id，见[其 Go 页面](https://opencode.ai/go)的「Can I use Go with other coding agents?」。运行时及网页控制台会发送 `nanoMuse/<version>` 作为 User-Agent，并在每次 Go 请求中发送对话 id；连接测试等不属于对话的调用使用独立 id。桌面版使用模型适配器自带的 OpenCode Go 路由，同样发送该请求头，并按每个模型的原生格式调用，因此可使用该路由目录中的模型，包括 Responses 和 Messages 格式；其他客户端只调用 OpenAI 格式。手机向 OpenCode 主机发出的聊天和 Responses 请求也带此请求头，其 id 是由聊天第一条消息哈希生成的提示缓存键，在各轮保持不变，两段首条消息完全相同的聊天会共用该 id。与 Zen 一样，此处只支持对话。
- **Standard Compute**。 从 [standardcompute.com/dashboard/api-keys](https://standardcompute.com/dashboard/api-keys) 获取 key。套餐按月固定收费，19 美元起，含每月算力额度；用尽后请求返回 402，不产生超额费用。地址为 `https://api.stdcmpt.com/v1`。默认模型 `standardcompute` 实际是路由器，会为每次请求从账号「Models」页启用的模型中选择一个；也可指定 `https://api.stdcmpt.com/v1/models` 返回的任意 id。该列表未声明路由器支持图片输入，所以此处只提供对话，不声明屏幕操作能力。
- **Cheaper Inference**。 从 [cheaperinference.com/signup](https://cheaperinference.com/signup) 获取 key，即可访问多家模型厂商。地址为 `https://api.cheaperinference.com/v1`，默认模型为 `gpt-5.4-mini`，也可选择 `https://api.cheaperinference.com/v1/models` 中的其他 id。此处只通过 OpenAI 格式提供对话。
- **API Route**。 登录后打开 [API keys](https://www.api-route.com/api-keys) 创建 key，再充值。地址为 `https://global.api-route.com/v1`。默认模型 `gpt-6.1-sol` 已用 `/v1/models` 和真实对话请求核验，其他 id 须从该 key 可访问的模型列表选择。费用按所选模型的[当前价格](https://www.api-route.com/pricing)从 API Route 预付余额扣除，与 nanoMuse Cloud 分别计费。此处只提供对话，图片输入、图片生成和视频尚未核验，详见[服务商文档](https://www.api-route.com/docs/overview)。
- **Opper**。 在 [platform.opper.ai](https://platform.opper.ai) 的「API Keys」创建 key，可按服务商原价访问 50 多家服务商的 700 多个模型，不加价，网关部署在欧盟。地址为 `https://api.opper.ai/v3/compat`。默认模型为 `claude-sonnet-4-6`，也可选择 `https://api.opper.ai/v3/compat/models` 中任意 id；使用 `anthropic/claude-sonnet-4-6` 这样的 `provider/model` id 可固定线路。此处只通过 OpenAI 格式提供对话。
- **AtmoRouter**。 从 [atmorouter.dev/dashboard/keys](https://atmorouter.dev/dashboard/keys) 获取 key，按量访问多家模型厂商。地址为 `https://atmorouter.dev/v1`。模型 id 含线路前缀，以 `https://atmorouter.dev/v1/models` 为准，默认是 `cc/claude-sonnet-4-6`，也可选列表内其他 id。此处只通过 OpenAI 格式提供对话。

**将 key 填入 nanoMuse**。

- 手机：额度卡片的「去设置」会打开预填好的服务商表单；也可到 设置 → 服务商 → 添加，选服务商，粘贴 key 并保存。
- 桌面版：「去设置」会打开 设置 → nanoMuse Cloud 的对应服务商；也可在该页「可用的途径」下找到服务商，填入 key。地址已经预填。
- 网页控制台：「去设置」会打开「连接」并选中对应服务商；也可到 连接 → 对话模型，选择服务商，填入 key 后保存。
- 自行运行的运行时：在 `config.toml` 中设置 `[llm] provider = "bailian"`（可换成表内服务商 id）和 `api_key`，地址与默认模型会从目录补全。若图片或视频使用其他服务商，另加 `[image]` / `[video]` 配置，见 [configuration.md](configuration.md#image-and-video)。运行时是执行智能体及工具的后台程序。

**选择 key 的用途**。 保存 key 后，「用它来做什么」卡片会为该服务商支持的每项任务显示开关，包括对话、操作屏幕、生成图片、生成视频，默认全部打开。点「就这样」后，勾选项会改用该服务商及该任务的目录默认模型；默认模型不在列表时，使用列表中第一个符合条件的模型。「暂不」不修改任何设置，关闭的项目也不修改，其他模型选择保持原样。之后可在 设置 → 模型 修改，网页版在「连接」中修改。

## 哪个模型负责什么 {#which-model-does-what}

Android 从设置顶部卡片进入 设置 → 模型，iPhone 从设置第一张卡片进入，桌面版位于「通用」之后。网页控制台在「连接」页分别提供「对话模型」「手的模型」「生成图片」「生成视频」卡片，每项对应一种任务：

| 行 | 做什么 | 列出谁 |
|---|---|---|
| 对话 | 和你说话的模型。 | 登录且开着 nanoMuse Cloud 模型时先是它的对话模型，然后是你每一家有对话模型的服务商 |
| 操作屏幕 | 看着屏幕替你操作，需要能看图的模型。 | nanoMuse Cloud 的手的模型，然后是你的服务商里能看图的模型；iPhone 上是灰的（「不在 iPhone 上」） |
| 生成图片 | 形象的肖像，以及你要的图片。 | 你有图像模型的服务商 |
| 生成视频 | 形象的短视频。 | 你有视频模型的服务商（百炼） |

每行显示 `provider · model`，点开可选模型。登录后，对话和屏幕操作首先显示 nanoMuse Cloud 组，并标出中继针对该任务的推荐模型。项目托管 Cloud 不生成图片或视频，所以媒体项只列出你自己的服务商。自己部署的中继只有在运营者明确启用并声明媒体能力后，才会出现在媒体项中。每个服务商组只列出符合任务要求的模型；不支持该能力的服务商不会显示。没有可用模型时，页面会说明哪些服务商支持，并提供「添加服务商」。

更改「对话」会同时更新主要聊天和新聊天的默认模型，已存在的旁聊继续用原模型，页面会提示「对主要聊天和新对话生效；旁聊保留自己的模型。」主要聊天是「聊天」标签页固定显示的对话，不能只靠新聊天默认值更新，否则会一直沿用最初的服务商。尚未发送消息的聊天也跟随选择，包括刚登录后账号的空主要聊天，以及新建但未使用的聊天。因此，无论之前使用套餐登录、自己的 key 还是 nanoMuse Cloud，主要聊天或新聊天的下一条消息都会用「对话」行显示的模型；登录不会覆盖你已选的模型。手机和桌面版规则相同。

在聊天自己的选择器中，从 `•••` 菜单或其下模型项选择自建模型组后，该组原顺序会成为默认，主要聊天也改用该聊天实际解析出的模型。只有以服务商命名、且只包含该服务商的组，才会像模型页选择一样将选中模型移到最前。手机自建模型组还可配置默认思考等级，iPhone 入口是「全部设置 → 模型组」，Android 从聊天选择器进入「模型组」。主要聊天跟随模型选择时会一并采用该等级，与新聊天及聊天自身选择器的行为一致。

**自动选择**。 操作屏幕、生成图片、生成视频的第一项是「自动」，并显示当前解析结果，例如屏幕操作的「当前为 nanoMuse Cloud · Qwen/Qwen3.6-27B-FP8」。选择它会清除该项的显式设置，按以下顺序解析：先使用你自己的对话服务商所支持的对应能力及目录默认模型；否则，在账号已登录、Cloud 模型已开启且中继实际菜单提供该能力时使用中继；再否则，使用你配置的第一家具备该能力的服务商。项目托管 Cloud 只提供对话和屏幕操作，不提供媒体生成。你明确选择的模型始终优先，Cloud 不会覆盖。各设备分别保存选择，key 也只留在录入它的设备。

**主动点击才会执行 Cloud 重试**。 某轮请求失败后，已登录用户的错误卡片会提供「这次改用 nanoMuse Cloud」。点击后只用账号模型重跑这一轮，不修改任何模型配置。这个按钮与模型组自动路由无关，如果手机的模型组包含 Cloud 模型，组路由仍可能自动选到它。图片、视频失败没有 Cloud 重试，需要修复或更换自己的媒体服务商后重试。

**模型组可能自动切换模型**。 Android、iPhone 的聊天如果绑定模型组，出错后可尝试同组的其他可用成员，候选只来自该组，不来自全部服务商。限流可能直接触发下一次请求改用另一个成员，无需先确认。它与 Cloud 重试按钮是独立机制。

| 聊天模型组设置 | Android | iPhone |
| --- | --- | --- |
| 默认 | 限流错误和被识别为 5xx 的服务商错误可以触发切换；可重试的网络和服务器错误会先在当前模型上重试。 | 限流、无效 key 和服务商拒绝可以立即触发切换；网络及暂时性的服务器错误在当前模型重试用尽后也可以切换。 |
| 始终 | 其他错误也可以触发切换；如果错误适合在当前模型重试，会先重试。 | 其他错误也可以立即触发切换，跳过通常在当前模型上的重试。 |

模型组设置目前没有「关闭」选项。要固定使用一个模型，可以创建只含该模型的组；Android 也可直接选具体模型，而不选组，这会移除组内备用链。其他模型仍可保留供别的聊天使用。自动切换会改变该聊天的当前模型，重新打开后也可能继续沿用，使用时请核对聊天显示的模型和服务商。

每个备用模型都会通过自己配置的服务商与凭据，收到回答所需的上下文。它们可能采用不同价格和计费规则，重试、备用请求也可能各自收费。使用多模型组前应检查成员，Cloud 重试按钮不会为组内请求额外提供确认。

**桌面版的思考深度**。 输入框的模型选择器只对文档明确支持深度控制的自有模型显示此选项，并使用厂商原生字段发送。目前包括 DeepSeek、Kimi（kimi-k3）、智谱（GLM-5.2 和 5.3）、硅基流动和火山引擎（各自的 DeepSeek-V4、GLM-5.2、豆包 Seed 2）、MiniMax（M3.1）、OpenRouter（模型目录给出的等级）、OpenAI（o 系列、GPT-5 起）、Anthropic（Claude 4.6 起）、OpenAI 兼容层的 Gemini、xAI（Grok 4.5 起）、Groq、Mistral，以及 Ollama 或 vLLM 的 gpt-oss。等级沿用厂商定义，例如 DeepSeek 的 `low`、`high`、`max`。「服务商默认」不发送深度参数，采用厂商默认设置。没有「关闭」项，因为这些服务商需要用另一开关或模型来关闭思考。未说明等级的模型不显示此控件；百炼的 `enable_thinking` 开关无法省略，所以也不显示，LM Studio 和自定义端点同样不显示。旧版保存的 key 会在下次启动时获得该控件。

**关闭 nanoMuse Cloud 模型**。 登录后，模型页提供「使用 nanoMuse Cloud 模型」。关闭后，Cloud 从选择器和自动选择顺序中移除，对话标题、记忆、屏幕操作等辅助调用也不再使用它。只有你主动点击「这次改用 nanoMuse Cloud」时，才会消耗额度。账号仍保持登录，同步、设备互联和账号页照常使用。Cloud 服务商不能像自建服务商一样删除，因为删除等同于退出登录；退出入口在 设置 → nanoMuse Cloud。

**不登录账号**。 只要有自己的 key，未登录时也能对话、操作屏幕、生成图片和短视频，均使用自己的服务商。欢迎页提供「改用自己的 API key」。只有 Cloud 模型、对话同步及设备互联需要登录。

**当前限制**。 iPhone 的图片和视频选项只列出使用 DashScope 主机的服务商，即阿里云百炼。OpenRouter、OpenAI、Gemini、自定义接口等目录中支持绘图的来源，会在选择页下方以「此处不提供：……」说明，并指出可使用的平台，避免误以为配置丢失。桌面版的「手」只支持 OpenAI 格式，Anthropic 和原生 Gemini key 会在屏幕操作项下说明原因，不列入候选。更改手的模型在下一步生效，无需重启。Gemini 绘图通过 Google 的 OpenAI 兼容层，`images/generations` 支持 `gemini-2.5-flash-image`，但其文档未声明 `images/edits`，因此形象工作室的姿势图可能无法生成。

## 登录已付费的套餐 {#sign-in-with-a-plan-you-already-pay-for}

以下套餐可直接登录，不需要创建 key：

| 套餐 | 能做什么 | 哪里可以登录 |
|---|---|---|
| **ChatGPT**（Plus / Pro / Team） | 对话、动手 | Android、iPhone、桌面版、网页版 |
| **Claude**（Pro / Max） | 对话、动手 | Android、iPhone |
| **Kimi** | 对话、动手 | Android、iPhone（设备码登录） |
| **OpenRouter** | 对话、动手、画图 | Android、iPhone（点按登录，key 自动返回 App） |

ChatGPT 使用 OpenAI 自家 Codex 的授权流程。网页入口为 连接 →「或者用 ChatGPT 套餐登录」；桌面版为 设置 → nanoMuse Cloud 中的 ChatGPT 行；手机为 设置 → 服务商 → OpenAI →「登录」。登录后支持对话和屏幕操作，Codex 通道没有图像或视频接口，媒体生成仍需配置 key。

终端也可完成同一流程：`nanomuse chatgpt login` 打开登录页并等待浏览器回调；`nanomuse chatgpt status` 查看当前账号及有效期；`nanomuse chatgpt logout` 删除登录状态。随后在 `config.toml` 设置 `[llm] provider = "chatgpt"`，无需 `base_url` 或 `api_key`，`model` 留空时默认 `gpt-5.6-sol`。浏览器需要能访问运行时所在机器的 1455 端口。运行时位于其他机器时，将浏览器最终停留的完整地址复制到命令行提示处，或提交给 `POST /api/chatgpt/callback {"url": …}`，详见 [configuration.md](configuration.md#a-chatgpt-plan-instead-of-a-key)。

**手机代理或 VPN 可能拦截登录回调**。 Android 登录页会返回 `http://localhost:1455/auth/callback`，此地址应由同一手机上的 App 接收。Clash 等代理或 VPN 如果接管全部地址，或代为解析 `localhost`，可能把回调送入隧道，造成浏览器连接错误、App 一直等待。可把 `localhost` 和 `127.0.0.1` 加入代理直连列表后重新登录；也可复制错误页地址，粘贴到「登录」按钮下方的输入框，点「继续」，直接将授权码交给等待中的流程，绕过代理。输入框通常约十秒后出现，检测到手机代理可能接管回调时立即出现。Anthropic、xAI、OpenRouter 使用同类跳转，也有此输入框；Kimi 使用设备码登录，不需要回调框。

**套餐授权的限制**。 OpenAI 条款规定 ChatGPT 套餐用于其自家 Codex。其他 App 曾被停止这类访问，例如 2026 年 1 月的 OpenCode。若套餐登录无法继续使用，可改用 API key。

## 无法连接服务商时 {#when-the-provider-cannot-be-reached}

部分网络无法访问 `chatgpt.com`，可能表现为 DNS 无法解析、连接超时、TLS 加密连接失败，或本应收到 JSON 却返回 HTML 拦截页。部分地区会被 OpenAI 直接拒绝，返回 HTTP 403 `unsupported_country_region_territory`。手机聊天会用卡片说明「这个网络连不上 chatgpt.com」或「OpenAI 不向这个地区提供服务」，并列出可尝试的方法：手机 VPN、设置 → 网络 中的 App 代理，或换用其他服务商的 key。卡片提供「重试」，原始连接错误保留在「详情」供报告问题。

登录过期的 401 会提示「ChatGPT 登录已失效」并提供「重新登录」。套餐当前时间段额度用尽时，如果 429 明确表示 usage limit，会显示「ChatGPT 套餐暂时没有余量了」、OpenAI 原始说明和恢复时间。其他 429 则提示「同时发出的请求太多」。自有 key 遇到相同网络问题时也显示这类卡片，主机名替换为对应服务商。

**设置 → 网络 → 自有服务商的 HTTP 代理**。 Android 和 iPhone 可填主机、端口，以及可选用户名、密码，默认关闭，只保存在本机。它只代理自有服务商和 ChatGPT 套餐请求，不代理 nanoMuse Cloud、你的电脑或局域网。「测试」会按当前代理访问一次 `https://chatgpt.com/`，报告是否成功及毫秒耗时。

其他客户端也在保存 key 的位置提供代理设置：手机的服务商表单；桌面版的 设置 → nanoMuse Cloud → 网络，填写 `http://host:port` 或 `socks5://host:port`。桌面代理在下次启动时应用到 Host 进程，下方提供「立即重启」，自有 key、ChatGPT 登录、手的运行时及 App 其他外部请求都会走此代理，Cloud 始终直连，见 [desktop.md](desktop.md)。网页自有 key 表单提供「代理」，运行时在 `config.toml` 中设置 `[llm] proxy`，见 [configuration.md](configuration.md#llm)。

## 本机模型 {#local-models}

电脑上运行的 Ollama、LM Studio、vLLM 也能接入。网页从「连接」、桌面版从 设置 → nanoMuse Cloud、手机从 设置 → 服务商 选择对应预设。默认使用本机地址 `http://127.0.0.1:11434/v1`、`:1234`、`:8000`，不需要 key。这些预设提供对话；若要操作屏幕，需要运行能看图的多模态模型，例如 Ollama 的 `qwen3-vl`，再在「操作屏幕」中选它。网页版在「对话模型」下的「动手模型」中选择该端点提供的模型。图片、视频生成仍需上表中的服务商。

## 其他兼容 OpenAI 的接口 {#any-other-openai-compatible-endpoint}

其他支持 OpenAI API 的服务也可接入，选择「自定义」并填写：

| 字段 | 填什么 |
|---|---|
| 地址（Base URL） | 服务商给的地址，通常以 `/v1` 结尾；运行时、网页控制台和桌面版都会拒绝带 `user:pass@` 的地址（key 有自己的栏位） |
| API key | 服务商控制台里创建的 key（本机服务可以留空） |
| 模型 | 保存后从列表里选；接口列不出模型时，表单会请你填模型 id（逗号分开），再按这些保存 |

自定义端点的能力需要你配置。默认视为可对话；填写手、图片或视频模型的 id 后，才视为具备对应能力。

**同时保存多个端点**。 桌面版、网页控制台使用端点列表，每个端点分别保存 key 和模型，添加第二个不会替换第一个，见 #294。桌面版的 设置 → 账号 → 任何 OpenAI 兼容接口 下，每个端点各占一行，显示名称、主机名，并提供「换 key」「改名」「移除」，下方可「添加接口」。设置 → 模型 中，各端点各自成为一组。网页的 连接 → 对话模型 在「本地或你自己的端点」下为每个端点显示卡片，最后为「添加接口」；动手、图片、视频选择器也会列出这些端点，见 [web.md](web.md#where-it-shows)。旧版配置的自定义接口会在下次启动时连同 key 迁移为列表首项。手机仍为每个服务商保留一个位置。
