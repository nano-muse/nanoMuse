# Android App

在 设置 → 技能 中，可以阅读、导出或停用内置技能。它们的名称、内容和文件由 App 维护，因此不能编辑、更新或删除。要自行修改，请先导出，再改名后导入为副本。内置 `skill-creator` 指南不依赖特定模型服务商。

模型会看到当前对话中每个已启用技能的名称、最多 1024 个 Unicode 字符的描述，以及实际 `SKILL.md` 路径，完整指令仍按需从文件读取。导入或更新技能会保留完整源文件，包括许可证、允许的工具和嵌套元数据。带引号或多行描述会按文本解析，嵌套字段不能覆盖顶层名称或描述。查看文件时显示实际内容，编辑技能不会更改已有目录 ID。名称中没有英文字母或数字时，也会生成稳定的目录 ID。

旧版导入时已丢失的字段，需要用原文件或原网址更新才能恢复。更新会保留已有技能的启用状态和各对话的覆盖设置。

`android/` 是 nanoMuse 的 Android 原生 App，基于 [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13，使用 GPL-3.0 许可证。智能体直接在手机上运行，APK（Android 安装包）内包含 Linux shell（运行终端命令的环境）、浏览器、MCP 服务器（通过通用协议提供工具的服务）、技能和定时任务，再加入 nanoMuse 的身份、设计和功能。nanoMuse 自有代码位于 `io.github.nanomuse.*`，对 OpenMinis 文件的改动均标有 `// nanoMuse:`。

应用 id 为 `io.github.nanomuse.app`，系统用 `nanomuse://` 这一 URL scheme（唤起 App 的链接前缀）识别它，避免与同机安装的 OpenMinis 争用前缀。App 内仍使用上游的 `minis://…`，以兼容沙箱、系统提示词和模型。系统传入的 `nanomuse://` 会按 `minis://` 处理；App 打开自身链接时，直接指定 `MainActivity`，不交给系统选择处理程序，实现见 `io.github.nanomuse.deeplink.OwnScheme`。

沙箱的 offload 抽象套接字用于 proot 与 App 通信，也采用专用名称 `io.github.nanomuse.app.native-offload`，而非上游的 `native-offload`。抽象套接字名称在整台设备共享，同名会让后启动的 App 失败。如果专用名称仍被 nanoMuse 的旧进程占用，服务端会改用带进程标识的名称，并通知 proot，见 `io.github.nanomuse.sandbox.OffloadSocketName`。相关选择见 [roadmap.md](roadmap.md)。早期 WebView 包装 Python 服务、提供两种 APK 的方案只作为历史记录保存在 [archive/android-python-line.md](../archive/android-python-line.md)，当前下载版本不再采用。

每个版本只提供 `nanoMuse-<version>-arm64.apk`，适用于 arm64-v8a、Android 8.0 / API 26 及以上，`targetSdk` 为 35。各版本使用同一签名密钥，新 APK 可覆盖安装并保留数据。App 未上架 Play 商店。设置 → 版本 会对照已安装版本和最新版，先查询 `nanomuse.cn/dl/index.json`，再查询仓库 GitHub Releases，显示「最新 0.1.x，你用的就是它」或「0.1.x 已发布，点此更新」，并提供下载。

## 安装 {#install}

1. 从[最新版本](https://github.com/nano-muse/nanoMuse/releases/latest)下载 `nanoMuse-<version>-arm64.apk`。如需校验文件完整性，执行 `sha256sum -c nanoMuse-<version>-arm64.apk.sha256`。
2. 打开 APK，按 Android 提示允许浏览器或文件管理器安装应用，只需授权一次。
3. **登录并选择模型**。 首屏可用手机号或邮箱接收验证码，设置过密码后也可用密码。账号用于设备互联，见 [hub.md](hub.md)，并提供起始模型及免费额度。写本文时每账号为 ¥10，邀请朋友注册并完成首次请求后，双方还会获得额度；具体数字以 App 显示的中继数据为准。详见 [cloud.md](cloud.md)，之后也可[使用自己的 key](own-key.md)。key 是调用模型服务的密钥。回答模型可使用账号模型、自有 key 对应的 OpenAI 兼容端点，或 App 内置的 OAuth 登录。端点是接收请求的服务地址，OAuth 是不用向 App 提供密码的授权登录流程。

   设置 → 模型 从设置顶部卡片进入，集中配置四种任务：「对话」「操作屏幕」「生成图片」「生成视频」。对话模型与你聊天，屏幕模型读取截图并决定动作。项目托管账号为前两项推荐同一个多模态模型 `Qwen/Qwen3.6-27B-FP8`，不生成图片或视频。每行显示「服务商 · 模型」，选择器只列出适合该任务的模型。已登录时，只有中继实际提供该能力的行才首先显示 nanoMuse Cloud，之后各自有服务商分别成组。

   每组先显示 8 个模型，顺序为该任务的目录默认模型、当前模型、服务商列表中的其他模型，点「还有 N 个」展开。总数超过 8 个时，可在「搜索模型」按 id 或名称实时筛选所有组，没有结果会显示「没有匹配的模型」。旋转屏幕，或前往「添加服务商」再返回，搜索和展开状态都保留。在此页或聊天 `•••` 菜单更换对话模型，会更新主要聊天及新对话默认值，已有旁聊沿用原模型，提示为「对主要聊天和新对话生效；旁聊保留自己的模型。」其他三项首先提供「自动」，例如屏幕项显示「当前为 nanoMuse Cloud · Qwen/Qwen3.6-27B-FP8」，选中会清除该项显式选择，重新按后文顺序解析。

   已登录时，模型页顶部提供「使用 nanoMuse Cloud 模型」。关闭后，Cloud 会从全部选择器与自动顺序移除，标题、记忆、屏幕操作等辅助请求也不再使用它。只有错误卡片上的「这次改用 nanoMuse Cloud」能对单轮使用它，账号仍保持登录，同步和设备互联照常工作。如果当前对话用的是账号模型，会改用第一个自有对话服务商的目录默认模型，并提示「对主要聊天和新对话生效」。没有任何自有对话模型时不能关闭，开关保持开启，下方说明「先添加一个自己的服务商；关掉 nanoMuse Cloud 后没有别的模型能回答。」

   设置 → 管理服务商 中 Cloud 页面采用相同规则。如果关闭当前负责对话的自有服务商，则转交下一个来源；没有来源时，发送会提示「现在没有能回答的模型。请在『设置 › 模型』里选一个。」有自己的 key 时，可在欢迎页选「改用自己的 API key」，不登录也能使用。完全自行运行、无需账号的配置为运行时的 `cloud.required = false`。
4. **按需授权屏幕操作**。 智能体操作其他 App 需要两项权限，均可跳过，也可撤销。设置 →「手」仍提供屏幕模型行，打开同一个选择器。模型页底部「更多图片和视频选项」进入原「图像与视频模型」页，可手填模型名、查看缺少模型会影响什么、重新检查 key 可用的视频模型，也可通过 `minis://settings/media` 打开。

**选择自有 key 的用途**。 新建自有服务商，或为原本没有 key 的服务商补上 key 后，会显示「用它来做什么」卡片。目录中的每种能力各有一个开关，包括对话、操作屏幕、生成图片、生成视频，默认全开。「就这样」将勾选项改为该服务商，使用 `providers.json` 中的 `defaults.chat` 等对应默认模型；默认模型不在列表时，选第一个符合该任务的模型。「暂不」以及关闭的开关都不修改配置，其他模型选择保留。以后可在模型页调整。

**未明确选择时的顺序**。 对话在登录后使用中继推荐模型，未登录则使用第一个自有服务商。屏幕、图片、视频先使用自有对话服务商支持的对应能力及目录默认模型；否则使用登录后中继实际菜单提供的对应模型；再否则选第一个支持该能力的自有服务商。项目托管 Cloud 只支持对话和屏幕操作。显式选择始终优先，Cloud 不会覆盖。自有模型失败时不会自行切换，已登录用户的错误卡片会提供「这次改用 nanoMuse Cloud」，点击后只用中继对话模型重跑当前对话或屏幕请求，不修改设置。图片和视频失败没有 Cloud 重试，须修复或更换自己的媒体服务商。

**使用自己部署的中继**。 默认登录 nanoMuse Cloud，也可在登录表单下选「使用其他服务器」，填写自建中继地址，见 [cloud.md](cloud.md) 和 `cloud/docker-compose.yml`。「检查」会请求 `/healthz` 并显示版本，「使用这个服务器」保存地址，重启后仍有效。自有网络之外必须使用 `https://`；局域网可用明文 `http://`，判断规则与模型地址相同：先解析私有地址，或识别 `localhost`、无点主机名，以及 `.local`、`.lan`、`.home`、`.internal`、`.home.arpa`、`.localdomain`、`.ts.net` 后缀。设置 → 账号 会显示「服务器：`<host>`」和「更改」。更改前会退出登录，因为当前 key 只属于签发它的服务器。登录、hub、同步、用量、模型菜单等账号请求都会发往选定地址。

## 手机能做什么 {#what-the-phone-does}

Shell 进度更新若把较长内容改为较短文字，会保留未被覆盖的部分。更新前会去掉终端颜色、标题控制码，避免显示残缺的转义序列。

系统提示词将安全、工具和手机操作规则放在稳定前缀中。技能与 MCP 元数据、模型和设备状态、对话专属要求、记忆、`USER.md` 等会变化的内容，按固定顺序追加在后；日期、语言、可用模型数放在最后的运行上下文中。因此，更新记忆或跨日不会改变稳定前缀，支持前缀缓存的服务商仍可复用它。

手机会按当前模型的上下文窗口，即单次能接收和生成的内容容量，计算每次请求预算；模型组限制更小时以组限制为准。`ContextBudget` 预留输出空间，取请求输出上限与 `max(4096, 窗口的 15%)` 中较小者，且不超过窗口本身，再扣除系统指令和工具定义，得到历史容量。历史占该容量 75% 时可将旧工具内容移入文件，90% 时开始摘要，整理目标为 50%。各阈值会再加回固定提示词用量。这些比例只决定何时整理，实际输出上限另按待发送请求剩余容量计算，不存在统一的 32k 压缩上限。

容量检查包括普通文本、结构化内容、摘要、回传服务商的推理文本、系统指令、工具定义和图片。非 ASCII 文字单独估算。成功响应的输入用量会逐步上下校准估算，按服务商配置和模型分别保存，点「继续」或重启后仍有效。请求前缀未变时，优先使用最近一次服务商报告的输入用量，再估算新增消息。更换服务商、指令、工具定义或旧内容会使该基准失效，异常样本不参与校准。新增、改写内容仍使用启发式估算，并非模型分词器的精确计数。原生音频采用服务商报告的用量，不把 base64 传输内容当文字计算。移出工具内容或生成摘要后，程序会重新测量请求。

生成摘要前，可先从待发送请求删除旧推理文本，将旧工具结果及较大参数保存到模型可读文件。最新用户要求受保护，通常也保留最近三个完整工具迭代；空间紧张时至少保留最近一个。最近完成的迭代中，单个结果过大也可存文件，但调用、推理和文件引用仍保持配对。写文件失败则保留原文。摘要后仍放不下时，可把符合条件的旧工具步骤归档并留下文件引用。磁盘上的原聊天历史不变。但去掉推理和用摘要替代旧历史都会丢失细节，模型不再每次收到全部原文。

提前摘要失败或未缩短请求时，只要内容尚未超过容量预留界限，本轮就继续，也不会每收到工具结果都再次摘要。每次智能体运行最多自动尝试三次。若只有校准倍率使请求超限，未校准估算仍能容纳，则允许向服务商发一次请求检验估算；其他无法缩小到合适容量的请求会停止。摘要流连续 120 秒没有数据块即超时，包含分段、重试的整个摘要操作限时 900 秒。停止本轮也会取消摘要。
发送摘要请求前，手机会先预留摘要的输出空间。如果对话内容挤占了这部分空间，就在同一重试次数限制内分段摘要。单条消息仍然无法容纳时，会保留原文。

摘要分别记录背景、已完成工作、当前要求、未完成步骤和下一步。没有活动任务时会明确说明，不重新激活旧要求。摘要后，仅在固定提示词、摘要和受保护当前轮之外的剩余空间内，补回可选的旧轮次原文。此预算随模型和请求变化，不固定为 8k。长任务用检查点替换已覆盖的旧步骤，保留完整用户要求与最近的完整工具迭代。最新问题、保留的工具调用和结果仍保持完整；即使它们已过大，也不截断，由容量检查决定能否发送。结构化追问和附件同样带上摘要，提示使用 App 当前语言。这套 Android 原生循环不依赖 Python 运行时的任务预算。

`PromptDiet` 会精简 `browser_use` 的 schema（参数结构）描述，保留全部动作、参数，同时压缩 Android 工具部分的 `minis-*` 说明。完整用法仍可通过各 CLI 的 `--help` 查看。

默认思考规则下，Qwen3.8-Max 摘要请求会显式发送 `enable_thinking: false`。如果省略该字段，即使 App 已请求关闭思考，服务商仍会采用自身默认值。详见[阿里云思考模式文档](https://help.aliyun.com/zh/model-studio/deep-thinking)。单凭超时无法判断延迟发生在网络还是服务商。

尚未收到首个 token（模型处理文字的计量单位）时，输入状态圆点下方由 `NmWaitLine` 显示等待信息。前十秒不显示，随后显示如「模型接口比较忙，已等待 15 秒」和「取消」。如果 Cloud 告知请求正在排队，则立即改为「前面还有 3 个」或「下一个就到你」。中继 0.31 每 5 秒发送不含 `choices`、带 `nanomuse: {phase, ahead}` 的数据块，协议见 [cloud.md](cloud.md#protocol)，由 `NmStreamStatus` 及 `OpenAIProvider` 的标记行处理。多工具步骤中，每一步独立计时。

| | |
| --- | --- |
| **本机智能体** | 在隔离的 Alpine Linux 中使用 shell、文件、浏览器、MCP 服务器、Agent Skills 格式技能、记忆和定时任务。删除、发送、付款前先审批（请求你确认操作）。模型可用账号或自有来源。自有 key 的请求直接从手机发往服务商，不经过项目中继；1.0.7 起，完成后会将模型 id 和整轮内容补到账号记录，不上传 key，供其他设备读取，见 [cloud.md](cloud.md#the-record)。 |
| **手（Hands）**（`hands/`） | 开启「手」及无障碍服务后，可根据手机截图在 App 中点击、输入、滑动。技能或 API、网页抓取、浏览器无法完成时，才使用这一步。覆盖在 App 上的「舞台」是显示下一点击位置的提示层，「胶囊」是显示步骤和「停止」的浮动控制条。屏幕边缘光晕以 2.4 s 变亮、2.4 s 变暗，工作蓝色、等待琥珀色。第 9 轮起各客户端工作指示采用相同节奏，光不绕边缘移动或扫过屏幕，胶囊环与条也同步呼吸；系统减少动态效果时全部静止。发送、发布、删除时，胶囊直接显示「允许」「拒绝」，与聊天、通知是同一个请求，不用返回 App。付款须在聊天卡片验证锁屏，胶囊提供「打开」。胶囊只能回应自身请求，不能替其他聊天的 shell 或浏览器审批作答。等待卡片时点「停止」会拒绝并立即结束。密码和验证码由你输入。若屏幕不变、同一动作重复第三次，历史会提醒模型换方法；第六次以「做不到」结束并注明动作，避免持续调用直到三十分钟上限。此规则由 `HandsLoopWatch` 实现，运行时相同。截图与轨迹保存在会话 `attachments/hands/<run>/`，最新十次保留全部截图，更早仅留轨迹和最后一张聊天展示图，超过 200 次删除最早运行，见 `HandsTraces`。设计见 [gui.md](gui.md)，实现位于 `io.github.nanomuse.hands`。 |
| **Reach**（`reach/`） | 从手机调用电脑的 shell、文件、屏幕，或将完整任务交给电脑的 nanoMuse。电脑安装桌面版并登录同一账号后，数秒内出现在 账号 → 设备，跨网络也可连接。0.1.24 起仅通过 hub 连接，原局域网 host 脚本已移除。设置 → 电脑 显示账号下电脑及手机当前账号，找不到电脑时通常是两端账号不同。请求发出前先在手机完成审批，见 [every-device.md](every-device.md)。 |
| **hub（设备互联）**（`hub/`） | 同一账号所有已登录设备经中继连接。手机可查看电脑、发送任务、接收审批卡片，也可接受电脑请求。Android 前台服务使 App 进入后台后仍可连接，Android 13 及以上会为此请求通知权限，见 [hub.md](hub.md)。 |
| **编程助手**（`ui/coding/`） | 在手机上查看、引导电脑中的 Cursor、Codex、Claude Code 会话，见 [coding-agents.md](coding-agents.md)。 |
| **账号**（`ui/cloud/`） | 查看当前账号、密码、持有登录 key 的设备，以及按类型、模型分类的用量，并管理退出。额度耗尽或已用超过 80 % 时，账号页和失败轮次会列出自有 key、已付费套餐、邀请三类方式。服务商按地区排列：中国大陆优先百炼，依据简体中文界面、手机号登录或中继地区信息判断，其他地区优先 OpenRouter、OpenAI，各有能力说明。套餐包括 ChatGPT、Claude、Kimi、OpenRouter，详见[自己的 key](#your-own-key)。手机只显示和同步当前账号聊天。0.1.40 起，无论是否同步，每个聊天都有归属。退出时「在这台设备上保留这个账号的聊天」默认关，关闭会移除账号聊天、记忆、动态、目标、例程和形象，开启则单独保存，等待重新登录。删除账号会全部删除；`401 bad_key` 按保留处理，并在登录页持续提示；只有 `401 account_deleted` 直接删除。未登录时只显示未登录期间创建的聊天，见 [sync.md](sync.md)。 |
| **接手浏览器**（`browser/`） | 登录、验证码、付款、人机验证等必须你亲自完成时，`browser_use` 的 `hand_over` 会在浏览器面板打开智能体原标签页，保留同一 WebView 和会话，智能体暂停。输入框上方「轮到你了」卡片说明所需操作，提供「打开页面」「完成，继续」，浏览器面板显示相同提示、按钮。工具等待「完成」，最长十五分钟，随后从页面现状继续。实现为 `io.github.nanomuse.browser.BrowserHandOver`。 |
| **连接器**（`connectors/`、`ui/connectors/`） | 用于接入 Notion、Linear、GitHub、GitLab、Slack、Stripe、Miro 等服务。复用桌面版 75 个远程 MCP 服务器目录，打包为 `assets/nanomuse/connectors.json`。设置统一入口为「连接器」，页面末尾「你自己的服务器」进入上游 MCP 编辑器，可按地址、命令或导入 JSON 管理。公开服务点选即可加入，需要 key 则填写，OAuth 服务执行发现、动态客户端注册、Custom Tab 内 PKCE 验证。令牌写入条目 `Authorization` 头供沙箱 MCP 客户端使用，启动时刷新。GitHub、Slack、Discord、HubSpot、Render、Bitrise、PagerDuty、Box 等不支持动态注册的服务标记 `clientIdRequired`，需要你在厂商开发页创建 OAuth client ID，并按服务商要求填写 client secret，面板会显示并允许复制 App 回调地址。连接结果是相同 id 的 MCP 条目，也可在自有服务器编辑器管理。连接清单经中继 profile 共享给其他设备，只含 id、名称、地址、认证方式、来源设备、时间，不含令牌。页面「在你的其他设备上」显示如「已在 <device> 上连接，在这里登录即可在这台手机上使用」，点开同一配置面板。 |
| **聊天中的进度** | 智能体工作时，形象下方说明当前步骤，例如「nanoMuse 正在用 Shell」「正在写回复」「在做了：订餐桌」，不写情绪。0.1.37 起，工具标签、电脑面板、浮动步骤条默认开启，可在 设置 → 外观 →「显示智能体的步骤」关闭。完成后标签显示如「nanoMuse 用过 Shell · 完成」，点 ×、滑动或返回均可关闭面板。 |

默认情况下，聊天、胶囊导航栏、菜单、抽屉使用统一底色，深色为纯黑，浅色为纯白。用户消息在深色模式为白底黑字，浅色模式为黑底白字。智能体消息使用稍有区分的底色 `#1C1C1E` / `#F2F2F7`。发送和「回到最新」按钮在深色模式为白底黑箭头，浅色反向。除链接外，聊天不使用蓝色。顶栏采用渐隐层，内容滚过时融入背景，翻看旧消息时顶部再加一层渐隐。配色由 `scripts/rebrand.py` 写入上游 `com/openminis/app/ui/theme/ChatColors.kt`。

输入框位于浮动导航胶囊上方，二者边缘对齐，左右边距同为 16 dp，最大宽度 420 dp，宽屏居中。使用工具时，步骤条位于输入框上方，最新消息和工具标签能完整滚到两者上面。对话仍可从胶囊背后滚过，形成实时磨砂效果。输入框展开、工具预览或审批卡片出现时，内容间距按底部实际高度调整。审批卡片最多占屏幕三分之二，超过六行的命令折叠在「全部显示」下，说明、预览在中间滚动，底部「允许」「拒绝」始终可见。阅读旧消息时，输入框圆角周围有较浅渐隐；实时浏览器控制会隐藏它，历史工具标签和其他工具不会。深色主要聊天及旁聊的导航胶囊周围、输入框下方间隙跟随所选聊天背景，默认为纯黑，胶囊玻璃仍透出滚动内容，其余标签页导航不变。键盘打开时输入框贴在键盘上方，导航栏位于键盘后。动态、点子、目标、资源库列表也在导航栏上方结束，最后一行不会被遮挡。

回复生成时，向旧消息方向滚动会立即暂停自动跟随。后续文字、工具卡片和键盘布局变化不会恢复自动跟随。点击向下箭头、滚回最新消息，或发送一条消息，即可重新跟随对话。

同账号网页控制台位于中继的 `/app`，桌面版见 [desktop.md](desktop.md)。手机、桌面、网页采用 [brand.md](brand.md) 所述的统一设计规范。

「设置 → 外观 → 聊天背景」提供默认、暖色、蓝色、绿色和紫色。
选择后立即应用于本机所有聊天，重启 App 后仍会保留。每种颜色都会随 App 的浅色或深色模式调整，
顶栏和底部的渐隐效果、导航胶囊周围的区域也使用相同背景。选择「默认」即可恢复原样。
消息气泡、文字、强调色和其他页面保持原有配色。目前不包含背景图片、渐变背景或主题导入。

设置 → 外观 中，「聊天输入」「消息文本」「应用基础」的字号名称按 App 当前语言显示。


## 自己的 key {#your-own-key}

服务商信息保存在 `assets/nanomuse/providers.json`，它由 `node scripts/providers-json.mjs` 从运行时的 `nanomuse/llm/providers.json` 生成，各客户端共用同一目录，见 [own-key.md](own-key.md)。每项包括端点、key 创建页、登录方式、可注册地区 `cn` / `global`，以及模型能力 `chat`、`vision`（看屏幕）、`image`（图片）、`video`（短视频）。

**额度提示卡片**。 额度接近用尽或已用尽时，「使用自己的模型 key」按地区排列目录：中国大陆先列阿里云百炼，它只接受大陆身份注册，一个 key 支持四种任务；其他地区先列 OpenRouter 和 OpenAI。其余服务商在「更多服务商」后每次展开三家。各行说明「聊天 · 屏幕 · 图片 · 短视频」等能力；「添加」打开预填名称、端点和 `/v1` 设置的表单，路径为 `minis://settings/providers/add?preset=<id>`；「获取 key」打开厂商页面。卡片不单独背书某一家。

「你已经在付费的套餐」列出 ChatGPT、Claude、Kimi、OpenRouter。ChatGPT 使用 Codex OAuth，Kimi 使用设备码。「登录」通过 `?preset=<id>:oauth` 打开对应表单，调用 OpenMinis 的 `OpenAIOAuthManager`、`ClaudeOAuthManager`、`KimiOAuthManager`、`OpenRouterOAuthManager`。ChatGPT 行说明：OpenAI 条款只允许套餐用于自家 Codex，其他 App 曾被停止访问，例如 2026 年 1 月 OpenCode，失效后仍可改用 API key。Anthropic、Gemini 使用各自原生服务商类型，其余采用 OpenAI 兼容表单。

Claude 登录要求每次请求开头包含 Anthropic 规定的标识，该值在构建时读取 `app/provider-customization.properties`。此文件不在仓库，发布 APK 也不包含该标识。缺少它的构建不会在额度卡片或「添加服务商」显示 Claude 登录，`?preset=anthropic:oauth` 会打开 key 表单。旧构建保存的 Claude 登录在发送时会提示「这个版本不能用 Claude 账号登录。请改用 API key 添加 Anthropic。」，不会使 App 退出，代码见 `io.github.nanomuse.cloud.ClaudeSignIn`。

**选项列表的来源**。 中继 0.21 起，`/v1/me` 通过 `spend.guidance` 返回地区服务商顺序、各能力、可登录套餐及适用客户端、本地服务、文档链接和 ChatGPT 条款说明，见 [cloud.md](cloud.md)。`cloud/Guidance.kt` 解析，`Ways.resolve` 优先采用。卡片和 设置 → nanoMuse Cloud 只在旧中继没有返回时使用打包目录，因此中继新增服务商无需等待 App 更新，移除也会当天生效。`429 allowance_exhausted` 会在用量数据旁返回同一结构。

**按能力提供功能**。 `cloud/Capabilities.kt` 决定候选来源：设置 → 模型 → 生成图片、形象工作室及 `nanomuse-media image` 只选支持 `image` 的厂商；视频只选支持 `video` 且 App 已接入其 API 的厂商，目前为百炼；屏幕选择器只列支持 `vision` 的模型。Codex 登录的 ChatGPT 仅支持对话和视觉，不提供图片、视频接口，不列入绘图来源。目录未识别的网关、自建中继、nanoMuse Cloud 继续按模型自己声明的能力判断。没有配置对应能力时，页面说明「画图需要有图像模型的服务商：百炼、OpenAI、Gemini 或 OpenRouter。」，不直接报错。

**检查 key 可用的视频模型**。 百炼 `/models` 不列视频模型，App 会用不计费的空任务逐个探测 `VideoGen.KNOWN_DASHSCOPE_MODELS` 中本版本已知模型，先探测万相 2.2 Flash，结果缓存一天。「视频」选择器除探测结果外，也保留你手动列入该服务商的模型：名称含 `t2v`、`i2v` 等视频标识，或详情输出模态包含 `video`，都按原样列出，不以探测成功为前提。手动新增模型或升级后已知模型列表变化，会立即重新探测，无需等满一天。「图像与视频模型」仍允许手填任意模型 ID，见 [#508](https://github.com/nano-muse/nanoMuse/issues/508)。

形象工作室开始新一轮候选图生成时，会替换上一组。旧请求稍后完成或失败，都不会再改动新组的图片格和文件。「重新生成」立即发起新请求，不必等待旧图保存完成。

**无法连接服务商**。 `net/ProviderReach.kt`、`ui/chat/ProviderReachCard.kt` 会把连接失败显示为说明卡片，而非红色错误横幅。可识别 OkHttp 的 `failed to connect to chatgpt.com/… (port 443)`、`Unable to resolve host`、TLS 或超时错误，以及 OpenAI 的地区不支持。卡片说明情况，建议使用本机 VPN、设置 → 网络 的代理或其他自有 key 服务商，并提供「重试」，原错误放在「详情」。上游 `mapHttpError` 会丢弃 401/403/429 响应体，`ReachSignal` 通过 `OpenAIProvider` 的一处 `// nanoMuse:` 改动短暂保留，再以 `nm_reach:` 标准行写入消息，因此登录过期能显示「重新登录」，套餐时间段额度用尽能显示「ChatGPT 套餐暂时没有剩余了」、OpenAI 原因及恢复时间。普通 key 的「Invalid API key」保持上游处理。中继 `daily_cap` 429 与 `allowance_exhausted` 一样进入额度卡片，说明今日份额已用完，次日恢复。卡片也列出本机模型方案，包括电脑上的 Ollama、LM Studio、vLLM；已登录时还列出你的电脑，聊天输入 `@` 加设备名即可交给它执行。

**中继拒绝请求**。 `cloud/RelayRefusal.kt` 和 `ui/chat/RelayRefusalCard.kt` 用手机当前语言显示具体说明及适当按钮，不只展示状态码、JSON 或「Rate limited」。`AllowanceSignal.noteHttpError` 在响应体完整时经 `OpenAIProvider` 同一处 `// nanoMuse:` 接入读取，以 `nm_relay:` 标准行存入消息。`413 too_large`，包括中继代理的普通 413，会说明消息太大，可缩短、移除附件或新建聊天，并提供「新聊天」。`400 content_rejected`，包括自有 key 返回 `DataInspectionFailed`，会说明服务商内容审核拒绝请求，建议改写，反复出现时新建聊天，因为触发内容也可能在旧消息中；提供「新聊天」「重试」。`ChatViewModel.shouldSplitOnError` 不对这种错误拆分重试，因为缩小请求仍包含相同内容。`401 bad_key` / `account_deleted` 提供「登录」；`403 not_invited` / `account_disabled` / `signup_closed` 提供「打开设置」；`429 too_many_in_flight` / `locked` / `rate_limited` / `provider_busy` 提供「重试」，并使用 `retry_after` 等待时间；`404 model_not_offered` 提供「打开设置」；`503 service_paused`、`sync_paused`、`hub_paused`、其他 5xx 或空响应提供「重试」。`429 allowance_exhausted`、`daily_cap` 继续显示额度卡片，中继 0.22 返回 `paused: true` 时，说明额度暂停发放而非耗尽，剩余额度保留。提示由 `NanoMuseCloud.describe` 提供，与登录、账号页一致，覆盖 17 种语言的 `nm_cloud_err_*`。测试为 `RelayRefusalTest`、`GuidanceTest`。

**设置 → 网络**。 `net/OwnProviderProxy.kt`、`ui/net/NetworkScreen.kt`、`minis://settings/network` 提供自有服务商 HTTP 代理，可填主机、端口及可选用户名、密码，默认关闭，仅保存在此手机。普通设置存在 `SharedPreferences`，密码单独加密存入 `nanomuse_proxy_secrets` 的 `EncryptedSharedPreferences`，与服务商 key 的方式相同。1.0.3 保存在普通文件的密码会在首次读取时迁移。`MinisApp.onCreate` 将它设为进程默认 `ProxySelector`，每个 OkHttp 客户端每次请求都查询：目录主机、`chatgpt.com`、`auth.openai.com`、已配置服务商自定义 Base URL 使用代理；中继和局域网地址不使用，其他主机沿用系统设置。因此 hub、中继、沙箱镜像不受影响。服务商客户端使用 `OwnProviderProxy.authenticator` 处理代理密码。「测试」通过当前代理请求 `https://chatgpt.com/`，报告状态及毫秒耗时，测试为 `ProviderReachTest`、`OwnProviderProxyTest`。

退出登录页面或网络设置页面后，会取消该页未完成的请求，即使服务器已经开始返回、但响应尚未传输完毕。

## 语音输入 {#voice-input}

语音输入、语音输出和聊天模型可以分别选择，也可以来自不同服务商。通过语音模型组或语音选择器设置即可。
阿里云百炼的 `paraformer-realtime-v2` 使用 DashScope 原生 WebSocket 接口转写录好的语音；
朗读支持通过该接口调用 `cosyvoice-v2`，以及通过原生 HTTP 接口调用 `qwen3-tts-flash`。
请求会保留服务商配置中的地域和工作空间。API Key、模型和音色须在对应地域可用；
CosyVoice 默认音色为 `longxiaochun_v2`，Qwen 默认音色为 `Cherry`。
Qwen TTS 只提供 WAV 音频，App 按该格式请求并播放，不会将它当作 MP3。
显式指定的旧 CosyVoice 音色 `longxiaochun` 会自动换用 `longxiaochun_v2`。

这些适配用于录音结束后的转写和回复朗读，尚不提供全双工实时语音对话。
现有语音控件不支持 Qwen ASR Realtime、Qwen TTS Realtime 和 Omni Realtime 的会话协议；
这些模型会在发起服务商请求前被拒绝；服务商朗读失败后，仍会按现有机制尝试设备的语音引擎。
协议说明参见阿里云的 [Paraformer 文档](https://help.aliyun.com/en/model-studio/websocket-for-paraformer-real-time-service)、
[CosyVoice 文档](https://help.aliyun.com/en/model-studio/cosyvoice-websocket-api) 和
[Qwen TTS HTTP 接口](https://help.aliyun.com/en/model-studio/qwen-tts-api)。

Android 13 及以上，系统连续听写切换到新语音段时会继续传送音频。即使旧段已关闭的管道发生写入错误，也不会关闭新段音频流。


用服务商模型输入语音时，静默达到录音时限，或太短的语音未能在等待期内补足可转写内容，界面会恢复待命。若已经开始转写，则等结果返回后才结束本次会话。

系统语音可优先选择本机识别。没有可用本机服务时，自动转到系统默认识别服务；默认服务的语言错误会显示在语音面板。已启动的本机识别器若缺少语言包，也会尝试一次默认服务。

无法开始录音，或尚未开始采集就被取消时，语音检测器会释放已分配的录音器，避免重试时仍占用旧录音资源。

语音段遇到静音后会提交转写并停止麦克风。旧实现会在检测器自身的回调线程中直接释放仍在运行的原生对象，导致说话两秒以上、停下来时 App 崩溃。1.0.8 已修复，上游 OpenMinis 1.14 也包含同一修复。现在回调内部提出停止时，会等当前音频帧处理返回后再生效。

## 隐私与权限 {#privacy-and-permissions}

中继保存账号 id、打码标识、用量，以及用于各设备保持一致的智能体名字和形象。对话相关数据分三类：完整请求记录，包含中继模型每轮及 1.0.7 起上传的自有 key 轮次，你的设备和中继运营者可读，可在「数据控制」删除；默认开启、可关闭的对话同步；仅在「帮助改进」开启时收录的训练集。详见 [privacy.md](privacy.md)、[cloud.md](cloud.md#the-record)、[sync.md](sync.md)，首次对话第四句话也会说明。「数据控制」显示记录总轮数、自有 key 轮数、图片数和中继保留期限。

API key、账号 key 和设置 → 网络 的代理密码都使用 `EncryptedSharedPreferences` 加密保存；代理密码从 1.0.4 起采用此方式，仅留本机。0.1.40 起，App 不参与系统设备备份，`allowBackup="false"`，聊天、记忆、key 不上传 Google。重装从空白开始，账号聊天通过同步恢复；`res/xml/` 的两个备份规则文件仍保留，供未来重新开启时使用。

「手」需要无障碍服务和悬浮窗权限，均可选，可在同一页面撤销。首次引导的手页面与登录页一样，在 App 标志下请求权限。发送步骤，例如点「发送」或在聊天框按回车，要逐次审批；「本次对话」授权也仅限原先指定 App 或地址。其他设备通过 hub 的 `shell`、`files`、`open`、`screen` 等操作手机前，须由持机者允许一次或对该设备总是允许，授权可在「权限」撤销。

远端设备及智能体提供的文件路径，包括 hub `files`、`nanomuse-media`、`nanomuse-pc put`，均由 `io.github.nanomuse.sandbox.SandboxPaths` 限定在沙箱内解析。`..` 或指向 rootfs 外的符号链接无法越界访问 App 私有文件。只有自有网络地址可用明文 `http://`：私有网段 `10/8`、`172.16/12`、`192.168/16`、Tailscale 的 `100.64/10`、链路本地地址、IPv6 ULA、`localhost`、无点名称，以及 `.local`、`.lan`、`.home`、`.internal`、`.home.arpa`、`.localdomain`、`.ts.net` 后缀。其他地址在服务商 URL 字段会被 `io.github.nanomuse.net.LanOnly` 拒绝。先解析再判断，因此 `10.foo.example.com` 不会被误判为私网地址。自建中继也用同一规则；nanoMuse Cloud 和到它的 hub 连接只使用 TLS 加密。App 内 WebView 不向其他 App 导出。服务商语音输入只在录音时开启麦克风，停止或取消会立即关闭录音器，取消的音频直接丢弃，不发送给服务商。

**请求记录还包括哪些来源信息**。 中继 0.31 起，Cloud 请求除设备和对话 id 外，还通过 `X-NanoMuse-Run` 标明发起者：用户、定时任务、动态例程、目标检查或其他设备的 hub 任务；注明对话轮次序号、轮内模型调用序号、屏幕任务运行与步骤，以及 `X-NanoMuse-Platform: android`。自有 key 轮次上传时也包含相同字段，见 [cloud.md](cloud.md#provenance)。`io.github.nanomuse.cloud.Provenance` 从聊天协程读取，保证输入、重试、例程、hub 任务、手操作采用统一来源格式。登录时还通过 `POST /v1/events` 和 `io.github.nanomuse.cloud.ClientEvents` 上报每轮附近的事件：shell、浏览器点击、屏幕步骤的风险判定和审批结果，手的各步骤及结束情况，手动停止或错误，以及最新回复下的赞踩。用户点停止后会问「为什么停下来？」，提供五个单词选项和「跳过」，例程与其他设备发起的轮次不问。报告仅含工具种类、风险级别、回答者、等待时间等代码与数字，不含命令、网页、屏幕或对话文字，见 [cloud.md](cloud.md#client-events)。「数据控制」删除轮次时会一并删除这些事件。

## 自己构建 {#building-it-yourself}

构建需要 JDK 21，与 CI 一致，以及 Android SDK，Android Studio 可安装这两项。空白机器可通过 `scripts/android/env.sh` 设置环境。工程目录为 `android/src/android`：

```bash
bash scripts/android/build-natives.sh   # 只需一次：proot、Alpine rootfs 和 rclone.aar（NDK r27c，Go 1.25+）
cd android/src/android
./gradlew :app:assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
./gradlew :app:assembleRelease      # signed with android/keystore.properties when present
./gradlew :app:testDebugUnitTest --tests 'io.github.nanomuse.*'   # 我们的单元测试
./gradlew :app:lintDebug            # Android lint；报告在 app/build/reports/lint-results-debug.html
```

Lint 静态检查使用比 AGP 8.7.3 自带版本更新的版本，由 `gradle.properties` 的 `android.experimental.lint.version` 指定，因为旧版无法加载 Compose、lifecycle 库附带的检查。上游代码也有自己的 lint 问题，查看报告时关注 `io.github.nanomuse` 部分。

`rclone.aar` 通过 Go 构建，模块默认经 `https://proxy.golang.org,direct` 下载。中国大陆网络可先执行 `export GOPROXY=https://goproxy.cn,direct`，`env.sh` 会保留你已导出的设置。

`scripts/rebrand.py` 定义 `VERSION_NAME`、`VERSION_CODE` 并将 nanoMuse 名称应用到 OpenMinis 代码树；原生组件构建见 `android/BUILDING.md`。未配置发布签名时，release 也会用 debug 密钥签名，可以安装，但无法更新正式签名的 App。要发布自己的签名版本，先创建密钥并保存在仓库外：

```bash
keytool -genkeypair -keystore ~/.nanomuse-release/nanomuse.jks -alias nanomuse \
        -keyalg RSA -keysize 4096 -validity 10950
```

将四项签名配置写入已被 Git 忽略的 `android/keystore.properties`：`storeFile`、`storePassword`、`keyAlias`、`keyPassword`。

使用 `-Pnm.abi=x86_64` 构建模拟器聊天测试版本时，会排除缓存里的 arm64 proot 和 Alpine 根文件系统资源。切回默认 arm64 构建会自动重新包含它们，不需要删除缓存。

### 在 Windows 上使用 WSL {#windows-wsl}

x64 Windows 需要在 WSL 2 的 x86_64 Ubuntu 中完成整个构建。WSL 是 Windows 提供的 Linux 环境；原生构建脚本支持 Linux、macOS 主机，不支持 Windows shell。若尚未安装，请先按 [WSL 安装说明](https://learn.microsoft.com/zh-cn/windows/wsl/install)设置并打开 Ubuntu。以下只有第一条命令在管理员 PowerShell 执行：

```powershell
wsl --install -d Ubuntu
```

以下其余命令全部在 Ubuntu 中执行。源码、SDK、缓存应放在 Linux 文件系统内，避免放在 `/mnt/c`。shell 脚本使用 LF 换行格式：

```bash
sudo apt update
sudo apt install -y git curl unzip zip build-essential pkg-config openjdk-21-jdk-headless
mkdir -p ~/src
git clone --config core.autocrlf=false https://github.com/nano-muse/nanoMuse.git ~/src/nanoMuse
cd ~/src/nanoMuse
git submodule update --init android/deps/proot
```

安装 [Linux 版 Go](https://go.dev/doc/install)，将 `go` 加入 Ubuntu 的 `PATH`。[Android 工作流](https://github.com/nano-muse/nanoMuse/blob/main/.github/workflows/android.yml)使用 Go 1.26。另下载 Linux 版 Android SDK Command-Line Tools，按 [sdkmanager 安装说明](https://developer.android.com/tools/sdkmanager)设置，SDK 路径用 `$HOME/Android/Sdk`，确保命令位于 `$HOME/Android/Sdk/cmdline-tools/latest/bin/sdkmanager`。Windows Android Studio 安装的 SDK 不包含本次构建需要的 Linux NDK 工具。

```bash
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export ANDROID_HOME="$HOME/Android/Sdk"
export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/27.2.12479018"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
export GOROOT="$(go env GOROOT)"
export GOPATH="$(go env GOPATH)"
export PATH="$GOPATH/bin:$PATH"
export GOTOOLCHAIN=auto

java -version
go version                         # 应显示 linux/amd64
sdkmanager --sdk_root="$ANDROID_HOME" --licenses
sdkmanager --sdk_root="$ANDROID_HOME" "platform-tools" "platforms;android-36" \
  "build-tools;35.0.0" "cmake;3.22.1" "ndk;27.2.12479018"

bash scripts/android/build-natives.sh
cd android/src/android
./gradlew :app:assembleDebug --console=plain --no-daemon
```

生成的 APK 位于 Gradle 目录下的 `app/build/outputs/apk/debug/app-debug.apk`。需要时可以把 APK 复制到 Windows，但构建代码树继续留在 Linux。

Gradle 会在 Ubuntu 的 `$HOME/.android/debug.keystore` 创建 debug 签名密钥。如果后续 debug APK 需要覆盖安装，请保留这把仓库外的密钥，它不一定与 Windows 用户目录下的密钥相同。debug APK 不能覆盖用另一密钥签名的官方 APK。要用自己的 release 密钥，请按前文签名步骤配置。

若 Kotlin 提示 Java 堆内存不足，先用 `free -h` 查看 WSL 可用内存。机器内存足够同时供 Windows、WSL 使用时，可以仅为当前构建提高 Gradle 和 Kotlin 后台进程的内存上限，无需改仓库配置。例如在同一 Gradle 目录运行：

```bash
./gradlew :app:assembleDebug --console=plain --no-daemon \
  '-Dorg.gradle.jvmargs=-Xmx4g -Dfile.encoding=UTF-8' \
  '-Pkotlin.daemon.jvmargs=-Xmx6g'
```

示例数值是可选的堆内存上限，不是最低需求。应按 WSL 实际可用内存调整，并为其他进程预留空间。


## 发布 {#releases}

修改 `android/` 后，`.github/workflows/android.yml` 会构建 debug APK，对应「debug APK · arm64-v8a」检查。发布使用 `scripts/release-apk.sh <version>`：核对 `rebrand.py`、Gradle 版本，用 release 密钥构建 `:app:assembleRelease`，输出 `dist/nanoMuse-<version>-arm64.apk` 及 `.sha256`。带 `--publish` 时创建 `v<version>` 标签，并将两文件与 `docs/releases/v<version>.md` 说明发布到 GitHub release。工作区未提交干净或当前提交不在 `main` 时拒绝发布。release 不上传 debug 签名 APK，因为正式签名版本无法覆盖它。`versionName` 必须与标签及 Python 包版本一样保持一致。

## 代码位置 {#where-things-are}

| 路径（`android/src/android/app/src/main/java/io/github/nanomuse/`） | 作用 |
| --- | --- |
| `cloud/NanoMuseCloud.kt` | 处理验证码、密码登录，加密存储 key，读取 `/v1/me`、用量、会话及本地化错误；读取中继模型菜单和 `for: chat` / `for: gui` 两类默认模型。 |
| `cloud/Region.kt`、`cloud/ProviderCatalogue.kt`、`cloud/Capabilities.kt`、`cloud/OwnKeyPresets.kt`、`cloud/ProfileSync.kt` | 按地区排列服务商，大陆先百炼，其他地区先 OpenRouter、OpenAI。从 `assets/nanomuse/providers.json` 读取自有 key 目录，识别已配置服务商及其能力，生成不可用提示。用 `?preset=<id>[:oauth]` 预填表单，同步中继 profile 中的名字、形象、连接器。 |
| `sync/` | 实现约定 C7–C10。`SyncEngine` 决定上传、下载，每个映射保存 `owner`，只同步当前账号；`ConversationSync` 决定时机，其 `hidden` 使 `ChatRepository.observeSessions()` 隐藏其他账号聊天。另有 `LocalChats` 和基于 Room 的 `nanomuse_sync.db`，其中 `session_owners` 属于 C12。 |
| `account/` | 实现 C12（0.1.40），见 [sync.md](sync.md)。`AccountScope` 定义聊天归属、账号标识、列表过滤、key 被拒后的保留规则：`keepOnRefusedKey` 保留全部，除非中继返回 `account_deleted`，均有单元测试。`AccountData` 为各聊天写归属记录；`leave` 删除或单独保存聊天、记忆、动态、目标、例程、形象、偏好，`enter` 恢复账号数据。「资源库」同样只列出聊天列表可见会话的工作区，避免共用手机时暴露其他账号文件，检查位于有单元测试的 `library/LibraryIndex.shows`。 |
| `hub/` | `Hub` 维护连接状态、设备身份、设置。`HubClient` 保持 socket 并按退避策略重连：key 被拒每分钟一次，连接被替换等 30 秒，运营者暂停 hub 等两分钟，均显示原因。`HubService` 是前台服务。`HubActions` 执行允许的远程动作，`stop {call \| conversation}` 可结束发起设备在此启动的任务，`HubTasks` 记录归属并有单元测试。`HubErrors` 将失败转成文字。 |
| `reach/` | `Computers` 读取 hub 的账号设备列表并调用设备。0.1.24 起不再单独配对、保存令牌。此处也包含向电脑转交任务的处理器。 |
| `models/` | 实现 设置 → 模型。`ModelSlots` 保存四种用途的配置及存储位置、选择器分组，用 `followPick` 更新对话默认模型，用 `applyProvider` 应用「用它来做什么」卡片。`SlotOrder` 定义解析顺序和目录默认值，`PickerList` 处理每组八行、排序和搜索；后二者为纯 Kotlin，均有单元测试。 |
| `ui/models/` | 提供模型页、各用途选择器和「用它来做什么」卡片，入口 `minis://settings/models`。 |
| `chat/CloudRetry.kt` | 判断何时显示「这次改用 nanoMuse Cloud」，并决定 `ChatViewModel.retryLast` 在该轮使用哪个服务商。 |
| `chat/RoutineWakes.kt`、`ui/chat/NmRoutineWakeRow.kt` | 将定时任务轮次标为例程发起，而非用户发起。`ScheduledAgentRunner` 发出提示前登记唤醒，`ChatViewModel` 关联到持久消息，`NmRoutineWakeRow` 只显示「例程 · 〈名称〉 · 08:00」，不用用户消息气泡。仅该轮附加的 `SessionAddenda` 会让模型直接报告结果，而非感谢用户提问。1.0.4 及之前，提示显示得像用户亲自输入。 |
| `feed/` | `FeedFlow` 维护每日定时任务及写作会话，后者仅供智能体工作，不进入抽屉、聊天列表、主要聊天候选；`FeedFlow.hidden` 由 `ChatRepository.observeSessions()`、`MainChat` 和移动面板使用。`FeedStore` 按最新日期、同日最新批次排序，批内保持模型顺序，以相同 `created` 标识同批次，`FeedStore.DAY_ORDER` 有测试。智能体在 `/var/minis/feed/YYYY-MM-DD/NN.md` 读取只读副本，已点赞内容含 `liked: true`。`FeedSandboxScope` 在 shell 命令前及点赞后刷新副本，避免 PRoot 不能只读挂载、智能体可能修改点赞的问题。没有 `liked` 表示未评价，提示词明确说明并非不喜欢。后台写出动态后，通知会列出标题并打开动态页 `minis://feed`，替代 1.0.4 及之前显示模型正文、打开工作会话的通用任务完成通知。 |
| `chat/TurnReply` | 识别本轮有效回复：只接受最后用户消息之后、未附错误的最后一条助手消息。动态、目标、首次对话通过它读取，因此尚未产出回复就失败的轮次返回空，不会误取上一轮回答，见 #637。 |
| `net/ModelBlip` | 为沙箱 `model_use` 加重试：网络错误、临时错误、5xx 分别等待一秒、两秒后再试，与聊天及 iOS 桥接一致；其他错误立即抛出。网关上游无响应的 `HTTP 0` 也视为临时错误，见 #640。 |
| `hands/` | 包含无障碍执行服务、屏幕提示层、浮动胶囊和屏幕读取器。`Hands.screenModel` 按顺序选择：显式选择；具备视觉能力的自有对话服务商默认模型；Cloud 的 `gui` 推荐；自有 key 备用；能看图的聊天模型；Vision Group。 |
| `ui/coding/` | 提供电脑编程助手的手机界面。 |
| `backup/` | 在上游 设置 → 备份与恢复（`minis://settings/backup`）扩展备份。「对话里的文件」默认开启，关闭后只导出消息，文件以墓碑记录即仅有条目、无实际内容的方式列入，各其他类别不变，可将 1.5 GB 包缩成几 MB，适配限制上传大小的服务器，见 [#561](https://github.com/nano-muse/nanoMuse/issues/561)。`BackupHints` 将目标 `413` 解释为服务器上传上限。沙箱 `nanomuse-backup run` 使用页面保存的选项和全部启用目标执行一次备份，`BackupRun` 写入历史，`status`、`history`、`choices` 可读取，便于定时任务备份。加密开启时拒绝命令行备份，因为口令只在页面输入、不进入 shell；未启用目标时也拒绝，见 [#560](https://github.com/nano-muse/nanoMuse/issues/560)。 |
| `connectors/`、`ui/connectors/` | `ConnectorsCatalogue` 读取连接器资源目录；`McpAuthDiscovery` 发现授权及注册；`Connectors` 连接、刷新令牌；`SharedConnectors` 发布本机连接清单到 profile 并读取其他设备清单。另提供 设置 → 连接器 页面。 |
| `ui/cloud/` | 提供登录页、账号页和设备设置。 |
| `res/values*/nm_strings.xml` | 保存 nanoMuse 全部界面文字，共十七种语言：英语、简体中文、繁體中文、德语、西班牙语、菲律宾语、法语、印尼语、日语、韩语、马来语、波兰语、巴西葡萄牙语、罗马尼亚语、俄语、泰语、土耳其语。各文件键保持一致，英语中标记 `translatable="false"` 的中继地址示例、`nanoMuse Cloud` 产品名除外。缺少翻译时使用英语。 |

## 继续中断的备份 {#export-resume}

「备份与恢复」可对中断的导出选择「继续」或「丢弃」。继续时必须沿用原类别、文件大小限制、对话文件和凭据选项，保留原导出标识与时间截止点，并复用已校验完成的类别。加密导出需要重新输入密码，不能改成明文继续，日志不记录密码。加密与打包会使用一次性副本，需要额外临时磁盘空间。失败后的私有暂存数据会一直保留，直到继续或丢弃。定时备份遇到待恢复导出时，会报告需要选择，不覆盖它。完成的文件仍采用可互操作的 .minisbak 格式。

继续导出时，不仅校验暂存数据和内容文件，也校验已提交的文件索引。即使索引长度相同，只要目标路径或元数据变化，也会拒绝继续。

## 中断还原的恢复 {#restore-recovery}

Android 在恢复共享文件、技能、记忆、MCP 配置、服务商或环境变量前，会保存恢复快照。某类别恢复失败则撤销该类别修改；过程中断时，下次启动会在打开数据仓库前核对并恢复该类别。恢复仍失败时保留快照、阻止正常启动，以便再次尝试。聊天继续沿用既有合并规则，不支持把整段聊天历史回退。恢复元数据不放入导出包。

环境变量元数据恢复后，也会更新正在运行的 App，即使原先不存在该元数据文件。

## 直接向另一台设备发送任务 {#direct-tasks-to-another-device}

「新聊天」可选择本机或同账号的另一台设备。选择其他设备会按设备 ID 建立独立对话。目标选择器和抽屉中的设备对话列表较长时可以滚动。目标离线时，对话和草稿仍会保留，发送须等设备在线且支持该功能。每个对话单独保存草稿，等待上一条请求期间修改的文字也会保留。

消息以 `@设备名称` 开头时，文字直接经 hub 发往目标设备，本机模型不再额外用一轮判断如何委派。目标设备用自己的模型、工具、配置执行。此指定只适用于当前任务，不会改变后续消息的默认执行设备。

远端执行时，聊天实时显示设备名、工具步骤和回复。未完成的流式文字替换当前片段，不重复插入消息；不提供流式输出的设备则返回最终回答。审批与模型委派任务一样，使用本机卡片和限定范围的授权。点「停止」会取消目标设备的本次调用，并撤回尚未回答的审批卡片。

目标离线或名称不明确时，消息保留在输入框。跨设备任务只接收文字，发送前需移除附件和粘贴文件的内容。须等活动轮次结束才能再发设备任务，普通本机消息仍可进入原有队列。调用报错前可能已执行部分步骤，因此界面会明确显示失败或缺少回答。最终文字及设备来源只保存一次，重新打开聊天不会重建实时远端工具胶囊。

Android 等待设备任务的上限为十五分钟，与中继期限相同。发起端超时或取消后，会尽力向目标发送针对该调用 id 的停止请求，最多等待十五秒完成清理。过期调用 id 无法停止同一对话后来启动的任务。

远端任务与本地回答使用相同的前台服务跟踪。你离开该聊天后，成功完成并保存的回复会标为未读；取消、失败、未保存的回复不标记。

## 未读回复 {#unread-replies}

回复成功完成时，如果聊天不可见，Muse 抽屉和经典会话列表会显示未读，经典布局折叠分组也保留提示。打开聊天即清除。失败、取消、重复完成事件不产生标记。未读状态只保存在本机当前进程中，与运行、暂停徽标分开。Muse 抽屉还会在本机跟踪到任务进行中的主对话、侧对话旁显示小型进度环，也包括从这里发起的 `@device` 直连任务。任务结束后进度环消失，不影响未读回复的判断。它暂不区分等待审批、不显示每个对话的当前步骤，也不代表从另一台设备独立发起的任务状态；#531 的这些部分仍需另行处理。

两种布局都按当前已恢复到前台的聊天判断可见性，新草稿发出首条消息后也适用。切换标签、被其他页面遮住或 App 进入后台后，完成的回复会标为未读。

## 用 @ 选择设备 {#picking-a-device-with}

在消息起始位置键入 `@`，会在常规文件结果前列出在线、可接收任务的设备。可按名字筛选后点选，或沿用方向键和回车选择。每行显示名称、手机或电脑图标、系统、在线状态、设备 ID。

选择设备会插入完整名称。同名设备使用 `@名称 [设备ID]` 区分，不明确的简称或无 id 的同名不会自动匹配第一项。委派实际使用稳定设备 ID。消息中间输入 `@` 仍只建议文件。

## 来自其他设备的 Emoji 形象 {#emoji-avatars-from-another-device}

桌面版或网页版选定的 emoji 形象及背景色会同步显示到 Android。手机会将 emoji 与自绘形象一并保留，重启后仍有效，也遵循账号隔离。空 emoji 使用 ✨，无效颜色使用蓝色 `#0064d4`。

自绘形象和个人视频继续按既有优先级显示。改名、修改连接器不会动未变化的远端外观。明确重置形象才恢复小龙。此项不包含 Android 本机选择 emoji 的功能。

## 应用锁 {#app-lock}

Android 可要求先验证设备锁屏，再显示 App 内容。在设置启用应用锁、选择重新锁定时间，保存前需要验证。解锁只在当前进程有效。两种布局、外部分享入口、安全模式诊断都受同一访问检查保护。重新锁定会关闭原生诊断窗口，从导出文件选择器返回后，也必须重新获得访问权限才写诊断数据。这是 App 内访问控制，不加密存储，后台任务仍继续。

待执行的诊断导出，必须同时满足导出页面已回到前台、App 已解锁，才会开始。在其他窗口解锁，不会放行尚在后台的导出。

访问权限到期时，原生服务商导入、权限修复弹窗也会关闭，尚未确认的权限选择会取消。

## 受保护的对话 {#session-lock}

可在聊天菜单用设备锁屏保护单个对话。开启、解除保护，导出、复制已锁聊天，或根据正文重新生成标题，都需验证。复制品继承保护，但必须单独解锁。保护新对话时先保存聊天；若取消验证，草稿保持原样。设置可指定重新锁定间隔，也可选离开即锁。两种布局、通知、深链接入口都使用此检查，受保护聊天不显示预览，也隐藏正文搜索命中。

手动备份若包含锁定聊天，会先请求确认，授权只针对该次备份，不会解锁所有聊天。定时备份、同步、后台工作照常进行。保护信息在本机跨重启保存，解锁状态不保存；二者均不通过聊天同步或备份传输，也不加密聊天存储。

使用「退出时」重新锁定选项时，切换到其他 Muse 标签也算离开对话，即使聊天仍在后台保留。


## 连接器 OAuth 登录 {#connector-oauth}

交换和刷新令牌时会明确请求 JSON 响应。即使服务商返回 HTTP 200，只要响应包含 OAuth 错误，就会视为登录失败。错误提示只显示固定错误码，不展示服务商响应原文或凭据。刷新响应无效时，已保存的令牌不会被替换。

出现 `incorrect_client_credentials` 或 `invalid_client` 时，请核对 OAuth 应用的 client ID；如果服务商要求 client secret，也要核对该值。出现 `redirect_uri_mismatch` 时，请核对服务商登记的回调地址与 App 显示的地址是否一致。出现 `bad_verification_code` 或 `invalid_grant` 时，请重新发起登录。并非所有连接器都需要 client secret。GitHub 的官方文档说明了 [JSON 响应协商](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)和[令牌错误码](https://docs.github.com/en/apps/oauth-apps/maintaining-oauth-apps/troubleshooting-oauth-app-access-token-request-errors)。

## 继续操作屏幕 {#hands-continuity}

同一聊天再次明确要求「手」操作同一已识别应用时，Android 会附上上次执行的任务、结束状态、结果和最后八步，作为简短历史记录。记录只存内存，最多三十分钟，最多三十二组聊天与应用组合。它不代表允许重复操作或恢复已停止任务，当前要求和新截图优先。没有聊天或未识别应用的运行不复用记录；明确切换到别的应用的运行不保存共用记录。清空、编辑、删除聊天，替换同步历史，退出账号或重启，都会丢弃对应记录。

屏幕模型可为 `scroll` 加上 `"distance":"large"`，执行约屏幕高度 65% 的纵向滑动。不传时维持约 45%，横向手势不变。主智能体会收到要求，保留 `nanomuse-hands run` 的完整 JSON，尤其是结束状态和最终回答，不以 `head`、`tail` 截掉内容。
