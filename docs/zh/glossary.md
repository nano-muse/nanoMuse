# 术语表

这页解释文档中的常见术语。遇到陌生词时，可以先查中文含义，再对照 App 的名称、配置键或代码。界面名称沿用 App 的译法；技术标识和产品名保持原样。

## 智能体与设备 {#agent-and-devices}

| 名称 | 含义 |
|---|---|
| 智能体<br>Agent | 能调用工具、执行任务的 AI 程序。 |
| 运行时<br>Runtime | 实际执行智能体循环、工具和定时任务的程序。 |
| 宿主 / 执行框架<br>Host / harness | 加载智能体并提供运行环境的应用或框架。DeepSeek Harness 是 nanoMuse 桌面插件的宿主。 |
| 中继 / nanoMuse Cloud<br>Relay / nanoMuse Cloud | 负责账号登录、模型请求转发和账号下设备通信的服务。nanoMuse Cloud 是产品名称，保持英文。 |
| hub（设备互联）<br>Hub | 中继中的设备通信服务，让同一账号下的设备互发请求和事件。 |
| 远程控制<br>Remote control | 允许账号下的其他设备请求本机执行操作。 |
| 「手」<br>Hands | 智能体读取屏幕，并执行点击、输入、滑动等动作的能力名称。 |
| 操作器<br>Operator | 反复读取屏幕、让模型决定下一步并执行动作的组件。 |
| 胶囊<br>Capsule | 操作期间显示当前步骤和「停止」按钮的圆角浮层。 |
| 舞台 / 光晕 / 标记<br>Stage / glow / marker | 分别指操作过程展示区域、屏幕或窗口边缘的状态提示，以及点击位置等动作提示。 |
| 轨迹<br>Trajectory / trace | 按执行顺序保存的截图、动作和结果，用来回看过程或定位失败。 |
| 主要聊天 / 旁聊<br>Main chat / side chat | 主要聊天用于持续交流；旁聊是为其他主题或任务创建的独立对话。 |
| 上下文 / 系统提示词<br>Context / system prompt | 上下文是模型本次收到的消息和相关资料；系统提示词是其中规定身份、规则和行为的固定指示。 |
| 动态 / 点子 / 目标 / 资源库<br>Feed / Ideas / Goals / Library | 依次展示为你撰写的内容、可发起的任务建议、带步骤的计划，以及智能体生成的文件。文档中的「房间」指这些功能页。 |
| 例程 / 触发器 / 目标检查<br>Routine / trigger / goal check | 例程按指定时间执行任务；触发器在新邮件等事件发生时启动；目标检查按计划询问或查看目标进度。 |

## 模型与凭据 {#models-and-credentials}

| 名称 | 含义 |
|---|---|
| 大语言模型<br>LLM, large language model | 能理解和生成语言的模型。智能体会让模型决定回答内容或下一步工具调用；是否支持图片取决于具体模型。 |
| 服务商<br>Provider | 提供模型调用服务的厂商或服务，也可以是你自己部署的服务。 |
| 端点 / 基础地址<br>Endpoint / Base URL | 端点是接收程序请求的接口地址；Base URL 是拼接各接口路径时使用的基础地址。 |
| API 密钥（key）<br>API key | 调用服务时用于身份验证的凭据。它不是模型名称，也不是免费额度。 |
| 访问令牌<br>Access token | 登录或授权后签发的访问凭据，可能有有效期。不要与计量模型用量的 token 混淆。 |
| 模型 token 用量<br>Token usage | 模型处理输入和输出的计量单位，不等同于字数或字符数。具体切分取决于模型。 |
| 额度<br>Allowance | 账号可使用的模型调用额度，与服务商密钥本身是两回事。 |
| 模型用途设置 / 自动<br>Model slot / Automatic | 对话、操作屏幕、生成图片、生成视频各自的模型选择。「自动」按文档规定的顺序寻找能完成该用途的来源。 |
| 多模态 / 视觉能力<br>Multimodal / vision | 多模态指支持文字、图片等多种数据类型；视觉能力通常指能读取图片，不能据此推断也能生成图片。 |
| 嵌入向量 / 语义检索<br>Embeddings / semantic recall | 把文本转换为数值向量，再比较含义的接近程度来查找记忆，不只依赖相同关键词。 |
| OAuth / PKCE<br>OAuth / PKCE | OAuth 是让应用获得服务访问授权的流程；PKCE 在此流程中校验发起方，降低授权码被截获后冒用的风险。 |
| 保险库<br>Vault | 加密保存凭据的组件。配置以 `{{vault:NAME}}` 引用条目，模型看到的是引用名称。 |

## 工具与连接 {#tools-and-connections}

| 名称 | 含义 |
|---|---|
| 工具调用<br>Tool call | 模型按约定格式请求程序执行操作，例如读文件、查日历或点击屏幕。 |
| 技能<br>Skill | 包含 `SKILL.md` 的文件夹，说明某类任务的步骤和使用方法。技能本身不等于外部服务连接。 |
| 连接器<br>Connector | 让智能体访问某项服务的工具或数据的连接配置。 |
| MCP 服务器<br>MCP server | 通过 MCP（模型上下文协议）向智能体提供工具或数据的服务。 |
| 命令行工具 / shell<br>CLI / shell | CLI 通过终端中的文字命令使用；shell 是解析并执行这些命令的程序。 |
| 程序接口 / REST<br>API / REST | API 是程序之间调用功能或交换数据的接口；REST 通常通过 HTTP 路径及 GET、POST 等方法组织请求。 |
| JSON / TOML<br>JSON / TOML | JSON 是程序交换结构化数据的格式；TOML 是便于人阅读和编辑的配置格式，例如 `config.toml`。 |
| 标准输入输出<br>stdio | 通过本地进程的输入、输出通道交换数据，不一定需要网络端口。 |
| WebSocket / 消息帧<br>WebSocket / frame | WebSocket 是持续连接的双向通信方式；帧是连接中发送的一条消息单元。 |
| 服务器发送事件<br>SSE | 服务器通过持续的 HTTP 连接向客户端推送事件的方式。 |
| 事件回调<br>Webhook | 供其他程序在事件发生时发送 HTTP 请求的地址，例如部署完成后通知智能体检查网站。 |
| 内嵌网页组件 / 浏览器自动化工具<br>WebView / Playwright | WebView 在 App 内显示网页；Playwright 用程序控制浏览器。它们是不同的浏览器后端。 |
| 无障碍树 / 文字识别<br>Accessibility tree / OCR | 无障碍树提供控件的文字、类型和位置；OCR 从截图中识别文字。它们不是同一种屏幕信息。 |
| 图形界面 / 屏幕定位<br>GUI / grounding | GUI 是用户看到的图形界面；grounding 是把要操作的按钮或文字对应到屏幕坐标。 |

## 权限、部署与评测 {#permissions-and-deployment}

| 名称 | 含义 |
|---|---|
| 哨兵（Sentinel）<br>Sentinel | 检查工具调用风险，并决定允许、请求审批或拒绝的组件。 |
| 审批 / 授权范围<br>Approval / grant scope | 审批是对某次操作作出决定；授权范围说明该决定只适用一次、当前对话，还是指定对象的后续操作。 |
| 污染标记<br>Taint | 表示对话已读取私密数据的标记，用于检查之后向外发送数据的行为。它不表示文件损坏或设备中毒。 |
| 沙箱 / 工作区<br>Sandbox / workspace | 沙箱限制命令可访问的资源；工作区是智能体读写工作文件的目录。 |
| 外发白名单<br>Egress allowlist | 按配置允许向外发送数据的目标主机列表。 |
| ARM64 / x64<br>ARM64 / x64 | 两类处理器架构。安装包必须与设备架构匹配，ARM64 常用于手机和 Apple 芯片电脑，x64 常用于 Intel、AMD 电脑。 |
| 自行部署 / Docker<br>Self-hosting / Docker | 自行部署是在自己的服务器上运行服务；Docker 用容器封装程序和运行环境。 |
| 回环地址 / 局域网 / 反向代理<br>Loopback / LAN / reverse proxy | 回环地址如 `127.0.0.1` 指本机；局域网连接附近设备；反向代理接收外部请求并转给内部服务。 |
| 连接加密 / HTTPS<br>TLS / HTTPS | TLS 用于加密网络连接；HTTPS 是使用 TLS 保护的 HTTP。 |
| 持续集成 / 回归测试<br>CI / regression test | CI 自动执行项目检查；回归测试确认修改后既有功能仍然符合预期。 |
| 模拟模型 / 回放 / 真实模型运行<br>MockLLM / replay / live | MockLLM 按脚本返回回答；回放重复使用已录制的回答；live 向配置的真实模型发送新请求。 |
| P95 耗时<br>P95 latency | 将样本按耗时排序后，95% 的样本不超过的耗时值，用来观察较慢请求的表现。 |
| 幂等 / 游标 / 删除标记<br>Idempotent / cursor / tombstone | 幂等指重复处理不会额外产生副作用；游标记录增量读取的位置；删除标记让其他设备知道某项内容已删除。 |
