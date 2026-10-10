# Android App

`android/` 是手机上的 nanoMuse：[OpenMinis](https://github.com/OpenMinis/OpenMinis)
1.13（GPL-3.0）：一个原生 App，智能体**在手机上**运行，Linux shell、浏览器、MCP 服务器、
技能和定时任务都装在 APK 里，再加上 nanoMuse 自己的身份、设计和功能。属于 nanoMuse 的一切
都在 `io.github.nanomuse.*` 下；OpenMinis 文件里的改动用 `// nanoMuse:` 标出。应用 id 是
`io.github.nanomuse.app`，系统认得这个 App 的 URL scheme 是 `nanomuse://`，这样同一部手机上也装了
OpenMinis 时，不会有两个 App 抢同一个 scheme；App 内部的链接仍是 `minis://…`（上游的词汇，沙箱、
系统提示词和模型都用它），从系统进来的 `nanomuse://` 链接按它的 `minis://` 形式读，App 自己打开
自己的链接时一律按名字指向 `MainActivity`，不交给系统去解析
（`io.github.nanomuse.deeplink.OwnScheme`）。沙箱的 offload 套接字（proot 和 App 之间通信的
抽象套接字）也是 App 自己的：叫 `io.github.nanomuse.app.native-offload`，不用上游的
`native-offload`，因为抽象套接字在整台设备上只有一个命名空间，两个 App 用同一个名字，后启动的那个
会在启动时直接死掉；如果连这个名字都还被我们自己上一个进程占着，服务端就改绑一个带进程号的名字，
并把它告诉 proot（`io.github.nanomuse.sandbox.OffloadSocketName`）。这个选择的来龙去脉
在 [roadmap.md](roadmap.md)；它之前的方案（包着一个 Python 服务器的 WebView，两个 APK 变体）
作为设计记录保留在 [archive/android-python-line.md](../archive/android-python-line.md)，不是你今天
下载到的东西。

一个 APK，一种架构：`nanoMuse-<version>-arm64.apk`（arm64-v8a，Android 8.0 / API 26 及以上，
`targetSdk` 35）。每个版本都用同一把签名密钥，所以新 APK 直接覆盖旧的，数据保留。没有上架
Play 商店：「设置 → 版本」把已安装的构建和最新版本并排显示（先查 `nanomuse.cn/dl/index.json`，
再查这个仓库的 GitHub Releases：「最新 0.1.x，你用的就是它」/「0.1.x 已发布，点此更新」），
并提供下载。

## 安装 {#install}

1. 从[最新版本](https://github.com/nano-muse/nanoMuse/releases/latest)下载
   `nanoMuse-<version>-arm64.apk`。想核对的话，运行
   `sha256sum -c nanoMuse-<version>-arm64.apk.sha256`。
2. 打开它。Android 会问一次，是否允许从你的浏览器或文件管理器安装。
3. **登录。** 第一屏就是账号：手机号或邮箱，一个验证码，设过密码之后也可以用密码。账号让
   你的设备能连成一体（[hub.md](hub.md)），也带来一个起步用的模型（[cloud.md](cloud.md)：每个
   账号一份免费额度（写这页时是 ¥10），每邀请一位朋友，你和对方都再得一些；App 会显示中继
   当前的数字；之后可以[换自己的 key](own-key.md)）。然后选哪个模型来回答：账号自带的，或者
   你自己的 key（任何 OpenAI 兼容端点，或 App 内置的那几种 OAuth 登录）。设的是四个模型，
   不是一个，都在同一页「**设置 → 模型**」里（设置顶部那张卡片打开它）：**对话**，和你说话
   的模型（账号的菜单默认停在 `deepseek-v4.1-flash`）；**操作屏幕**，看屏幕的那个
   （`qwen3.8-27b`，账号的，或者你自己 key 下的同一个模型）；**生成图片**和**生成视频**。每一行
   显示「服务商 · 模型」，打开一个选择页：登录后先是 nanoMuse Cloud 一组，推荐的那个排在最前
   并标出来，然后是你自己每个服务商一组，只列能做这件事的模型。每组先只显示 8 个模型，点
   「还有 N 个」才全部展开（目录里这一行的默认模型排最前，然后是正在用的那个，其余按服务商
   列出的顺序）；所有组加起来超过 8 个时，分组上方多一个「搜索模型」输入框，按模型 id 或名称
   实时过滤每一组，都不匹配时显示「没有匹配的模型」；搜索词和已展开的分组在旋转屏幕、
   去「添加服务商」再回来之后都还在。在这里或在对话的 `•••` 菜单里
   选的对话模型，就是新对话的默认，主要聊天也跟着换（「对主要聊天和新对话生效；旁聊保留自己的模型。」）；已经打开的旁聊保留它的模型。另外三个
   选择页第一项是「自动」（「当前为 nanoMuse Cloud · qwen3.8-27b」），选它会忘掉在这里做过的
   选择，让这一行重新按下面的顺序走。登录后这一页最上面有一个开关「使用 nanoMuse Cloud
   模型」：关掉后，账号从所有选择页和自动顺序里退出，附带调用（标题、记忆、图片、视频）都不再
   走它，只有被拒绝那一轮上的「这次改用 nanoMuse Cloud」按钮例外；登录本身保留，同步和你的
   设备照常。如果关掉那一刻对话模型还是账号的，「对话」那一行会换到你自己的第一个对话模型
   （目录里该服务商的默认），每个客户端都这么做，页面上写着「对主要聊天和新对话生效」。对话
   模型还是账号的、而你又没有自己的对话模型时，关闭会被拒绝并给出一句话：开关保持打开，下面
   出现「先添加一个自己的服务商；关掉 nanoMuse Cloud 后没有别的模型能回答。」，因为没有别的
   东西能回答。Cloud 这个服务商自己的页面（「设置 → 管理提供商」）遵守同一条规则；在那里关掉
   一个正在回答对话的自己的服务商，对话会交给下一个来源，一个都不剩时发送会提示「现在没有
   能回答的模型。请在『设置 › 模型』里选一个。」。有自己 key 的手机不登录也能用：欢迎页提供
   「改用自己的 API key」。
   完全不要账号、一切自己跑，是运行时的 `cloud.required = false`。
4. 可选：让智能体能使用你手机上其他 App 的那两个权限（可跳过、可撤销）。「设置 → Hands」
   仍保留屏幕模型那一行，点开是同一个选择页；「模型」页底部的「更多图片和视频选项」就是原来的
   「图像与视频模型」页（手动输入模型名、缺了哪个模型会停下什么、重新检查一把 key 能用哪些
   视频模型），也在 `minis://settings/media`。

**用它来做什么。** 保存一个你自己的服务商之后（新建的，或给原本没有 key 的补上 key），会有一张
卡片问这把 key 负责哪些事：目录里该厂商每有一项能力就有一个开关（对话、操作屏幕、生成图片、
生成视频），默认全开。「就这样」把勾选的几行切到这个服务商，模型用目录里该项的默认
（`providers.json` 的 `defaults.chat` 等），默认不在它的列表里时用列表里第一个能做这件事的；
「暂不」什么都不改，没勾的开关也一样。登录状态下正文会说其余仍由 nanoMuse Cloud 负责。以后
在「模型」页改。

**你没选的时候。** 对话：登录了就是中继推荐的模型，否则是你自己的第一个服务商。屏幕、图片、
视频跟着对话的服务商走，只要它是你自己的、且有这项能力（用目录里的默认）；否则登录了就用中继
的模型；再否则是你自己第一个能做这件事的服务商。选过的永远优先，nanoMuse Cloud 不会插到你选
的服务商前面。你自己的模型失败时不会自动兜底：错误卡片多一个「这次改用 nanoMuse Cloud」
（仅登录后显示），只把这一轮放到中继的对话模型上跑，不改任何一行。

**自己的中继。** 登录屏默认连 nanoMuse Cloud，除非你另有指定：登录表单下方的「使用其他服务器」
接受你自己运行的中继地址（[cloud.md](cloud.md)，`cloud/docker-compose.yml`），「检查」会请求它的
`/healthz` 并显示它回答的版本，「使用这个服务器」把地址记住，下次启动仍然有效。自己网络之外的
地址必须是 `https://`；自己网络内的地址可以用明文 `http://`，判断规则与模型服务器地址相同
（见下文：按解析后的地址判断私有网段，`localhost`、不带点的名字，以及 `.local`、`.lan`、`.home`、
`.internal`、`.home.arpa`、`.ts.net` 后缀）。「设置 → 账号」显示「服务器：`<host>`」和「更改」，更改会先把
手机退出登录：它持有的 key 属于签发它的那台服务器。App 对账号做的一切（登录、hub、同步、
用量、模型菜单）都发往这个地址。

## 手机能做什么 {#what-the-phone-does}

| | |
| --- | --- |
| **智能体，在手机上** | 一个沙箱里的 Alpine Linux、一个真正的 shell、文件、浏览器、MCP 服务器、Agent Skills 格式的技能、记忆、定时任务；删除、发送、付款之前先审批。模型是账号的或你自己的；用自己的 key 时，你说的话一个字都不经过项目的中继。 |
| **手（Hands）**（`hands/`） | 打开「Hands」并启用无障碍服务之后，智能体会看手机的屏幕，在各个 App 里点、输入、滑动：这是 API、抓取和浏览器之后的最后一级。盖在 App 上的舞台显示它即将点哪里，一个胶囊显示当前步骤和**停止**；屏幕边缘有一圈呼吸的光（干活时蓝色，等你时琥珀色；亮 2.4 s、暗 2.4 s，第 9 轮起每个客户端上每一处「在干活」的灯都是这个节奏：没有东西绕着边缘跑，也没有东西从屏幕上扫下来，胶囊的环和竖条按同样的节奏呼吸；系统设了「减弱动态效果」时全部静止）；当一次点击会发送、发布或删除时，胶囊自己就会问（**允许** / **拒绝**，和聊天卡片、通知显示的是同一个请求），所以你不用被拉回 nanoMuse（付款在聊天卡片里用锁屏确认；对这一种，胶囊提供「打开」）；胶囊只回答它自己的请求，不会替另一段对话的命令行或浏览器卡片作答，卡片等待期间按**停止**会直接拒绝它并立刻结束这次运行。密码和验证码永远由你自己输。屏幕没有变化而同一个动作做到第三次，历史里会记一笔，好让模型换个法子；做到第六次，这一轮就以「做不到」结束并写明是哪个动作（`HandsLoopWatch`，运行时也有同样的底线），而不是每一步都调用一次模型，直到三十分钟上限。每一步的截图写在会话的 `attachments/hands/<run>/` 下、与这次运行的轨迹放在一起；最新的十次运行保留全部截图，更早的运行只保留轨迹和最后一张屏幕（聊天里显示的那张），超过 200 次之后最早的一次整个删除（`HandsTraces`）。[gui.md](gui.md) 是设计记录；App 自己的手在 `io.github.nanomuse.hands`。 |
| **Reach**（`reach/`） | 从手机使用你的电脑：「手机上说一句，电脑上执行」，一条 shell 命令、一个文件、电脑的屏幕，或者把整个任务交给那边运行的 nanoMuse。入口是 hub（下一行）：在电脑上装 nanoMuse 桌面版，用同一个账号登录，几秒钟内它就出现在「账号 → 设备」下，不限网络；从 0.1.24 起这是唯一的方式（局域网的 host 脚本已经去掉）。「设置 → 电脑」列出账号下的电脑，并说明手机用的是哪个账号，因为电脑不见了，几乎总是因为它登的是另一个账号。审批在手机上决定之后，才会发出任何东西。[every-device.md](every-device.md)。 |
| **hub**（`hub/`） | 账号下每台登录的设备都在中继的 hub 上相遇：手机看得到你的电脑，能拜托它们做事，把它们的审批当作卡片收到，也能被它们拜托。一个前台服务让它在后台也保持可达（Android 13 及以上为此会请求通知权限）。[hub.md](hub.md)。 |
| **编程助手**（`ui/coding/`） | 你电脑上的 Cursor、Codex 和 Claude Code 会话，在手机上看、在手机上指挥。[coding-agents.md](coding-agents.md)。 |
| **账号**（`ui/cloud/`） | 谁登录了、密码、每台持有 key 的设备、按类别和按模型的用量、退出的方式。免费额度用完或超过 80 % 时，账号页和被拒绝的那一轮都会显示接下来的路：自己的 key，也就是目录里的服务商，所在地区的排前面（中国大陆的人看到阿里云百炼：判断依据是界面语言为简体中文、用手机号登录，或者中继这么说；其他地方是 OpenRouter 和 OpenAI），每一家都写明它覆盖什么；你已经在付费的套餐（ChatGPT、Claude、Kimi、OpenRouter 用登录代替 key）；还有邀请。见下面的[自己的 key](#your-own-key)。手机只显示、只同步当前登录账号的对话：从 0.1.40 起每个聊天都有一个归属者，同步与否都是；退出登录时会问「在这台设备上保留这个账号的聊天」（默认关：这个账号的聊天、记忆、动态、目标、例程和形象都离开手机；开：先收起来，等它回来）；删除账号会把这些全部删除；中继拒绝的 key（`401 bad_key`）会像「保留」那样把账号的数据收起来，登录页会一直说明，直到下次登录；只有 `401 account_deleted` 会删除；退出登录状态下，只显示退出后产生的聊天（[sync.md](sync.md)）。 |
| **交到你手里的浏览器**（`browser/`） | 需要你亲自处理的页面（登录、验证码、付款、人机验证）会直接交到你手里，而不是用文字描述：`browser_use` 的 `hand_over` 动作把智能体自己的标签页（同一个 WebView、同一个会话）在浏览器面板里打开，智能体松手；输入框上方的**轮到你了**卡片说明页面要你做什么，带「打开页面」和「完成，继续」，面板上是同一句话和同一个按钮，工具调用会等到「完成」（最多十五分钟），然后智能体从页面当前的样子接着往下做。`io.github.nanomuse.browser.BrowserHandOver`。 |
| **连接器**（`connectors/`、`ui/connectors/`） | 智能体可以被放进去的那些服务：桌面版那份 75 个远程 MCP 服务器的目录（Notion、Linear、GitHub、GitLab、Slack、Stripe、Miro……），以 `assets/nanomuse/connectors.json` 随 App 发布。设置里管这一切的只有一行：「连接器」；上游的 MCP 编辑器（按地址、按命令、导入 JSON）是页面末尾的「你自己的服务器」。开放的服务点一下就加上；要 key 的服务填 key；OAuth 服务走 MCP 授权流程（发现、动态客户端注册、在 Custom Tab 里做 PKCE），令牌进入该条目的 `Authorization` 头，供沙箱内的 MCP 客户端使用，App 启动时刷新；授权服务器不接受注册客户端的服务（`clientIdRequired`：GitHub、Slack、Discord、HubSpot、Render、Bitrise、PagerDuty、Box）会要你在厂商的开发者页面用 App 的回调地址创建一对 OAuth client id 和 secret，面板会显示并复制这个回调地址。连接好的服务就是同一个 id 下的一个 MCP 服务器条目；「你自己的服务器」也能管它。连接了什么，会通过中继的 profile 分享给账号的其他设备，只有条目（id、名称、地址、认证方式、哪台设备、何时），从不包含令牌，所以页面还会列出「在你的其他设备上」：在桌面上连接的服务显示为「已在 <device> 上连接，在这里登录即可在这台手机上使用」，点一下进入同一个面板。 |
| **聊天，不花哨** | 智能体工作时，形象下面那一行写的是正在进行的步骤（「nanoMuse 正在用 Shell」「正在写回复」「在做了：订餐桌」），从不写心情。工具小标签、「电脑」面板和浮动的步骤条从 0.1.37 起**默认打开**；「设置 → 外观 → 显示智能体的步骤」可以关掉它们。打开时，完成的步骤显示为「nanoMuse 用过 Shell · 完成」，它的面板点 ×、滑动或返回键都能关。 |

同一个账号的网页控制台在中继上（`/app`），桌面版见 [desktop.md](desktop.md)；手机、桌面和网页共用
[brand.md](brand.md) 里描述的设计语言。

## 自己的 key {#your-own-key}

App 认识的厂商在一个文件里，`assets/nanomuse/providers.json`，运行时的
`nanomuse/llm/providers.json` 的一份拷贝，由 `node scripts/providers-json.mjs` 写出，每个客户端读的
都是这同一份目录（[own-key.md](own-key.md)）。每个条目写明端点在哪、在哪里创建 key、有哪些登录方式、
在哪里接受注册（`cn`、`global`），以及它的模型能做什么：`chat`、`vision`（手看屏幕）、`image`（图片）、
`video`（短视频）。

**卡片。** 额度用完或快用完时，「使用自己的模型 key」列出目录，所在地区的厂商在前：大陆是
阿里云百炼（一把 key 覆盖全部四项；它只接受中国大陆的账号注册），其他地方是 OpenRouter 和
OpenAI；然后是其余的，每次三家，收在「更多服务商」后面。每一行都写明这家覆盖什么
（「聊天 · 屏幕 · 图片 · 短视频」）；「添加」打开服务商表单，预填好它的名字、端点和 `/v1` 设置
（`minis://settings/providers/add?preset=<id>`），「获取 key」打开厂商的 key 页面。不推荐任何一家。
「你已经在付费的套餐」列出用套餐登录、不用 key 的厂商：ChatGPT（OpenAI 的 Codex OAuth）、
Claude、Kimi（设备码）和 OpenRouter；「登录」打开同一个表单并停在登录按钮上（`?preset=<id>:oauth`），
走的是 OpenMinis 自己的 `OpenAIOAuthManager`、`ClaudeOAuthManager`、`KimiOAuthManager` 或
`OpenRouterOAuthManager`。ChatGPT 那一行附一句话：OpenAI 的条款只允许 ChatGPT 套餐在 OpenAI
自己的 Codex 里使用，别的 App 曾被切断过这种访问（OpenCode，2026 年 1 月），如果停了，API key
照样能用。Anthropic 和 Gemini 打开的是 OpenMinis 为它们准备的服务商类型；其他都走 OpenAI
兼容表单。

**列表从哪来。** 中继的 `/v1/me` 带着 `spend.guidance`（中继 0.21，[cloud.md](cloud.md)）：这个人所在
地区的服务商，按中继的顺序，每家覆盖什么、可以登录的套餐以及它们面向哪些客户端、本地服务器、
文档链接，还有关于 ChatGPT 登录的那句实话。`cloud/Guidance.kt` 解析它，`Ways.resolve` 优先用它，
卡片和「设置 → nanoMuse Cloud」只在中继没发（旧中继）时才读内置目录，所以中继上新加的厂商
不用等 App 更新就能出现，中继不再列出的服务商当天就消失。`429 allowance_exhausted` 在数字旁边
带着同一块内容。

**各家覆盖什么。** 能力决定 App 提供什么（`cloud/Capabilities.kt`）：图片（「设置 → 模型 → 生成图片」、
形象工作室、`nanomuse-media image`）只在厂商有 `image` 的服务商里挑；短视频只在有 `video` 且 App
能驱动的里面挑（百炼的视频 API）；屏幕模型和它的选择页只列出有 `vision` 的厂商的模型。通过
Codex 登录的 ChatGPT 套餐只有聊天和视觉（Codex 后端没有图片或视频端点），所以从不会被拿来
画图。目录不认识的厂商（一个网关、你自己的中继、nanoMuse Cloud）按它模型自己的说法算，和以前
一样。没有任何已配置的服务商具备某项能力时，页面用一句话说明（「画图需要有图像模型的
提供方：百炼、OpenAI、Gemini 或 OpenRouter。」），而不是报错。

**连不上服务商的时候**（`net/ProviderReach.kt`、`ui/chat/ProviderReachCard.kt`）。失败的一轮，如果
错误来自传输层（OkHttp 的「failed to connect to chatgpt.com/…（port 443）」「Unable to resolve host」、
一条 TLS 或超时信息），或者是 OpenAI 的「region not supported」，就显示为一张卡片而不是红色横幅：
发生了什么、什么有用（这台手机上的 VPN、「设置 → 网络」下的代理、另一家用你自己 key 的服务商）、
「重试」，以及收在「详情」后面的原始信息。上游的 `mapHttpError` 会丢掉 401/403/429 的响应体，
`ReachSignal`（`OpenAIProvider` 里一处 `// nanoMuse:` 改动）把它们留几秒钟，以规范的 `nm_reach:` 行
写进消息，所以过期的 ChatGPT 登录显示「重新登录」，用完的套餐窗口显示「ChatGPT 套餐暂时没有
剩余了」，附 OpenAI 自己的那句话和重置时间；key 服务商上普通的「Invalid API key」则保持上游的
样子。中继的 `daily_cap` 429 现在和 `allowance_exhausted` 一样读取，卡片会说今天的份额用完了，
隔天回来。额度卡片还列出你自己的模型（你自己电脑上的 Ollama、LM Studio、vLLM），以及对登录
账号而言，你的电脑：聊天里打「@」加它的名字，这一轮就在那边跑。

**中继拒绝一轮的时候**（`cloud/RelayRefusal.kt`、`ui/chat/RelayRefusalCard.kt`）。nanoMuse Cloud 发来的
每一种拒绝都是手机语言的一句大白话，加上一个合适的按钮，从不显示状态码、中继的 JSON 或上游的
「Rate limited」。回复在响应体还完整时读取（`AllowanceSignal.noteHttpError`，经由 `OpenAIProvider` 里
同一处 `// nanoMuse:` 改动），以规范的 `nm_relay:` 行存进消息，由卡片绘制：`413 too_large`（也包括
中继主机上的代理返回的普通 413）→「这条消息对模型来说太大了。缩短一点、去掉一些附件，或者开
一个新聊天。」加「新聊天」；`400 content_rejected`（服务商的内容审核没有放行这些内容；用自己的
key 时服务商自己的 `DataInspectionFailed` 也算）→「模型服务商的内容审核没有放行这次请求。换个说法
试试；如果反复出现，就新开一个对话，被拦下的可能是对话里更早的内容。」加「新聊天」和「重试」，
压缩的对半重试（`ChatViewModel.shouldSplitOnError`）不碰它，因为请求再小，同样的内容回来还是被拒；
`401 bad_key` / `account_deleted` →「登录」；`403 not_invited` /
`account_disabled` / `signup_closed` →「打开设置」；`429 too_many_in_flight` / `locked` /
`rate_limited` 和 `provider_busy`（附 `retry_after` 的等待时间）→「重试」；`404
model_not_offered` →「打开设置」；`503 service_paused`、`sync_paused`、`hub_paused` 以及任何 5xx
或空响应 →「重试」。`429 allowance_exhausted` 和 `daily_cap` 保留额度卡片；带 `paused: true`
（中继 0.22）时，卡片开头说额度「在这个中继上暂停了，不是用完了」，剩下的保持不变。这些句子
来自 `NanoMuseCloud.describe`，和登录页、账号页用的是同一批，17 种语言都有（`nm_cloud_err_*`）。
单元测试：`RelayRefusalTest`、`GuidanceTest`。

**设置 → 网络**（`net/OwnProviderProxy.kt`、`ui/net/NetworkScreen.kt`、`minis://settings/network`）。
给自己的服务商用的 HTTP 代理：主机、端口、可选的用户名和密码，默认关闭，只存在这台手机的
`SharedPreferences` 里。它在 `MinisApp.onCreate` 中被装为进程默认的 `ProxySelector`，所以每个 OkHttp
客户端每次请求都会问它；对目录里的主机、`chatgpt.com`、`auth.openai.com` 和服务商实例的自定义
base URL（从不包括中继的，从不包括局域网地址）它回答代理，对其他所有主机回答系统的设置：hub、
中继、沙箱镜像都不受影响。服务商客户端带着 `OwnProviderProxy.authenticator`，应付要密码的代理。
「测试」按填写的代理抓取 `https://chatgpt.com/`，报告状态码和毫秒数。单元测试：`ProviderReachTest`、
`OwnProviderProxyTest`。

## 隐私与权限 {#privacy-and-permissions}

中继保存账号 id、一个打码的标识、用量计数，以及智能体的名字和外观（让你的设备保持一致）；
消息内容只以对话同步的形式保存：登录后默认开启，在*数据控制*里关掉（[privacy.md](privacy.md)、
[sync.md](sync.md)）；第一次对话的第四句话会这么说。在手机上，API key、账号 key 和 Reach 配对令牌放在
`EncryptedSharedPreferences` 里；从 0.1.40 起 App 完全不参与设备备份（`allowBackup="false"`：
聊天、记忆和 key 从不上传到 Google，重装后从空白开始，账号的聊天通过同步回来；`res/xml/` 下的
两个规则文件留着，等哪天开关再打开时用）。手需要无障碍服务和悬浮窗权限，两者都可选、都能在
同一屏撤销（首次运行的「手」那一页在 App 标志下面请求这两项，和登录页一样）；会发送东西的步骤（点「发送」，或在聊天软件的消息框里按回车）一次一次地审批，
「本次对话」的答复也只对当初授权的那个 App 或地址有效。账号下的另一台设备想在手机上运行、读取
或写入什么（hub 的 `shell`、`files`、`open`、`screen`……），要先经拿着手机的人批准：「一次」或
「对这台设备总是允许」，可在「权限」里撤销。另一台设备或智能体说出的路径（hub 的 `files`、
`nanomuse-media`、`nanomuse-pc put`）只在沙箱内解析（`io.github.nanomuse.sandbox.SandboxPaths`）：
`..` 和指向 rootfs 之外的符号链接都无处可去，App 自己的私有文件始终够不着。App 只对你自己网络内的地址（私有网段 `10/8`、`172.16/12`、
`192.168/16`、Tailscale 分配的 `100.64/10`、链路本地地址、IPv6 ULA、`localhost`、不带点的名字，
以及 `.local`、`.lan`、`.home`、`.internal`、`.home.arpa`、`.localdomain`、`.ts.net` 后缀），也就是一台模型
服务器或你自己的电脑，允许明文 `http://`，其他地址在服务商 URL 字段里一律拒绝
（`io.github.nanomuse.net.LanOnly`）。地址先解析再判断，所以 `10.foo.example.com` 这样的公网名字
不会被当成私有地址。自己的中继能否用 `http://` 也按同一条规则判断；nanoMuse Cloud 以及到它的
hub 只走 TLS。App 内的
web view 不对其他 App 导出。

## 自己构建 {#building-it-yourself}

JDK 17 或 21（CI 用 21）和 Android SDK（Android Studio 会把两个都装上）；`scripts/android/env.sh` 在一台空机器上
设好环境。工程在 `android/src/android` 下：

```bash
bash scripts/android/build-natives.sh   # 只需一次：proot、Alpine rootfs 和 rclone.aar（NDK r27c，Go 1.25+）
cd android/src/android
./gradlew :app:assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
./gradlew :app:assembleRelease      # signed with android/keystore.properties when present
```

`rclone.aar` 用 Go 构建，模块走 Go 自己的默认代理（`https://proxy.golang.org,direct`）；在中国大陆网络下先
`export GOPROXY=https://goproxy.cn,direct`，`env.sh` 会沿用你导出的值。

`scripts/rebrand.py` 带着版本号（`VERSION_NAME`、`VERSION_CODE`），把 nanoMuse 的命名套到
OpenMinis 树上；`android/BUILDING.md` 讲原生部分。没有签名密钥时，release 构建用 debug 密钥签名，
能安装，但不能升级一个正式签名的构建。要签名，先创建一次密钥，放在仓库之外：

```bash
keytool -genkeypair -keystore ~/.nanomuse-release/nanomuse.jks -alias nanomuse \
        -keyalg RSA -keysize 4096 -validity 10950
```

然后把它的四个值填进 `android/keystore.properties`（已 git-ignore：`storeFile`、
`storePassword`、`keyAlias`、`keyPassword`）。

## 发布 {#releases}

`.github/workflows/android.yml` 在 `android/` 下每有改动就构建 debug APK（「debug APK · arm64-v8a」
这项检查）。版本由 `scripts/release-apk.sh <version>` 从一个标签做出来：它核对版本号与 `rebrand.py`
和 Gradle 是否一致，用 release 密钥构建 `:app:assembleRelease`，写出
`dist/nanoMuse-<version>-arm64.apk` 和它的 `.sha256`，加 `--publish` 时打上 `v<version>` 标签，
并把两者连同 `docs/releases/v<version>.md` 里的说明一起附到 GitHub release 上。debug 签名的 APK
永远不进 release，因为正式签名的版本无法覆盖它。`versionName` 必须和标签一致，就像 Python 包的
版本号那样。

## 东西都在哪 {#where-things-are}

| 路径（`android/src/android/app/src/main/java/io/github/nanomuse/`） | 作用 |
| --- | --- |
| `cloud/NanoMuseCloud.kt` | 账号：用验证码或密码登录、加密存储里的 key、`/v1/me`、用量、会话、本地化的错误句子；中继的菜单和它的两个默认值（`for: chat` / `for: gui`） |
| `cloud/Region.kt`、`cloud/ProviderCatalogue.kt`、`cloud/Capabilities.kt`、`cloud/OwnKeyPresets.kt`、`cloud/ProfileSync.kt` | 哪个地区的厂商排前面（大陆 → 百炼，否则 OpenRouter 和 OpenAI）；从 `assets/nanomuse/providers.json` 读出的自带 key 目录，以及某个已配置的服务商对应哪家厂商；一个服务商覆盖什么和那些一句话的「不可用」提示；预填的服务商表单（`?preset=<id>[:oauth]`）；拉取和推送的中继 profile（名字、外观、连接器） |
| `sync/` | 对话同步（契约 C7–C10）：`SyncEngine`（什么上传、什么下载；每个映射带 `owner`，只有本账号的）、`ConversationSync`（何时同步；`hidden`：另一个账号的聊天，从 `ChatRepository.observeSessions()` 里排除）、`LocalChats`、Room 存储 `nanomuse_sync.db`（含 C12 的 `session_owners` 表） |
| `account/` | 契约 C12（0.1.40，[sync.md](sync.md)）：`AccountScope`（规则：一个会话是谁的聊天、账号的 key、列表排除什么、被拒绝的 key 保留什么（`keepOnRefusedKey`：全部保留，除非中继说 `account_deleted`）；有单元测试）、`AccountData`（执行规则：每个聊天一行归属记录，`leave` 把账号的聊天、记忆、动态、目标、例程、形象和偏好收起来或删掉，`enter` 把一个账号的东西带回来）。「库」标签遵循同一条规则：只列出聊天列表会显示的那些会话的工作区，共用一台手机时另一个账号的文件不会出现（`library/LibraryIndex.shows`，有单元测试） |
| `hub/` | `Hub`（状态、设备身份、设置）、`HubClient`（带退避的 socket；key 被拒绝时每分钟重试一次并如实显示，连接被替换时等 30 秒，运营者暂停 hub 时等两分钟并如实显示）、`HubService`（前台服务）、`HubActions`（其他设备可以让这台手机做什么；`stop {call | conversation}` 结束发起设备在这里启动的任务，由 `HubTasks` 记账，有单元测试）、`HubErrors`（用文字描述的失败） |
| `reach/` | `Computers`（已配对的电脑，令牌在加密存储里）、把工作转交给电脑的处理器 |
| `models/` | 「设置 → 模型」背后的逻辑：`ModelSlots`（四个槽位、各自设成了什么、存在哪里、选择页列出的分组、对话默认的 `followPick`、「用它来做什么」卡片的 `applyProvider`），`SlotOrder`（解析顺序和目录默认，纯 Kotlin，有单元测试），`PickerList`（选择页每组 8 行的折叠、排序和搜索过滤，纯 Kotlin，有单元测试） |
| `ui/models/` | 「模型」页、每一行背后的选择页、「用它来做什么」卡片（`minis://settings/models`） |
| `chat/CloudRetry.kt` | 「这次改用 nanoMuse Cloud」：卡片何时提供它，以及 `ChatViewModel.retryLast` 这一轮用的服务商 |
| `hands/` | 作为手的无障碍服务、舞台和胶囊、屏幕读取器；`Hands.screenModel` 选屏幕模型（已选的 → 对话服务商自己的默认，当它能看图 → Cloud 的 `qwen3.8-27b` → 你自己 key 下的同一个 → 一个能看图的聊天模型 → Vision Group） |
| `ui/coding/` | 你电脑上的编程助手 |
| `connectors/`、`ui/connectors/` | 连接器目录（`ConnectorsCatalogue` 读取资源文件）、MCP 授权发现与注册（`McpAuthDiscovery`）、连接和令牌刷新（`Connectors`）、这台手机连接了什么并发布到 profile、其他设备连接了什么（`SharedConnectors`）、「设置 → 连接器」页面 |
| `ui/cloud/` | 登录、账号屏、设备部分 |
| `res/values*/nm_strings.xml` | nanoMuse 的全部字符串，App 支持的十七种语言各一份（英语、简体中文、繁體中文、德语、西班牙语、菲律宾语、法语、印尼语、日语、韩语、马来语、波兰语、巴西葡萄牙语、罗马尼亚语、俄语、泰语、土耳其语）；每个文件的键相同，缺的回落到英语 |
