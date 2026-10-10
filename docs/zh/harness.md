# 跑在 DeepSeek Harness 上的 nanoMuse

> **状态：已发布。** 代码在 `main` 分支的 [`harness/`](../../harness/) 里。从 0.1.30 起，它就是
> **nanoMuse 桌面版**，唯一的那个桌面 App：Windows、macOS 和 Linux 的安装包，里面装着 harness、
> 这个 bundle 和负责「手」的运行时（[desktop.md](desktop.md)）；bundle 也单独打包发布为
> `dsh-nanomuse-<v>.tgz`，给已经在跑 DeepSeek Harness Desktop 的人用（[harness/README.md](../../harness/README.md)）。
> 它分两步到位：bundle 从 0.1.27 起就有，外壳在 0.1.28–0.1.29 以 *nanoMuse Harness* 之名和旧的
> Electron App 并列（[阶段](#phases)）。这一页是设计和计划；[desktop-muse.md](desktop-muse.md) 讲的是
> 窗口该长什么样。

## 决定 {#the-decision}

今天的桌面 App 是我们自己的 harness：一个包着 Python 运行时的 Electron 外壳，运行时自带智能体循环、
工具注册表、技能、日程、记忆、子智能体和网页界面，和手机、浏览器演示用的是同一份代码，这也是它存在的
理由。这里面的每一个部分，在 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
（`dsh`）里都有对应物：一个开源（MIT）的智能体 harness，以插件系统的形式建在
[Cordis](https://github.com/cordiverse/cordis) 之上，带网页 App、桌面 App、MCP 客户端、技能、目标、
计划模式、压缩、委派、审批策略、电脑操作，以及一个从配置里接任何 OpenAI 兼容端点的模型层。它现在是
0.2.0-rc，一个插件 API 还会变的开发者预览版，但它有的社区，我们自己的项目多年之内都不会有。

所以下一代桌面版是 **dsh 加 nanoMuse 插件**：让 nanoMuse 之所以是 nanoMuse 的那些东西，即账号、形象、
口吻、手（Hands）、Reach、哨兵（Sentinel），以插件的形式进去；循环、工具和界面是 dsh 的。我们不再为
桌面维护第二个 harness。手机继续用 Python 运行时（dsh 是 Node 的，跑不了 Android），浏览器演示暂时也
继续用，账号是它们之间的桥梁，和今天一样。

## 跑的是什么 {#what-runs}

第一块是一个 dsh **bundle**，`dsh-nanomuse`（[`harness/dsh-nanomuse/`](../../harness/dsh-nanomuse/)），
链接进一个用 dsh 自己的 web 模板建出来的 profile：

- **账号。** 宿主侧的服务 `nanomuseCloud` 用手机和桌面版同样的两个调用（`/v1/auth/code`、
  `/v1/auth/verify`）向中继登录，把 key 以 `NANOMUSE_CLOUD_TOKEN` 存进 dsh 的凭据存储，再把账号的
  聊天模型写进 dsh 的模型适配器（`dsh-llm-pi-ai`），作为一个叫 *nanoMuse Cloud* 的服务商，base URL
  是中继的 `/v1`。我们没有自己的模型适配器：中继说的是 OpenAI Chat Completions，dsh 原样回应。退出
  登录把两样都删掉。一个回环 API（`/nanomuse/cloud/{status,code,verify,refresh,sign-out}`，仅限同源）
  给设置里的那一节供数据。
- **形象和名字。** 浏览器这一半填上 dsh 的插槽：侧边栏品牌位和主视觉里的小龙、*nanoMuse* 字标，以及
  设置里的 *nanoMuse 账号* 一节（手机号或邮箱 → 验证码 → 已登录，显示打了码的标识、额度和模型）。
  原装的品牌插件被 patch 关掉；静态图由宿主这一半提供。
- **口吻。** dsh 的网页会话由一个*智能体预设*组合而成，预设里的人设优先于全局的，所以 bundle 声明了
  一个预设 `nanomuse`（插件列表和 dsh 的 *Standard* 一样，人设换成 nanoMuse 的），并把它设为默认。
  人仍然可以选 *Standard*、*PTC* 或 *Minimal*。
- **手（Hands），我们第一个以插件形式进去的能力。** 预设把 dsh 的 MCP 客户端挂在 `nanomuse mcp` 上
  （[cli.md](cli.md#audit-and-config)）：运行时的 `computer_screen` 和 `computer_act` 经 stdio 提供，
  带着它们自己的描述和 schema，到 dsh 里变成 `mcp__nanomuse__computer_screen` 和
  `…computer_act`。截图以 MCP 图片传输，所以视觉模型看得见屏幕。哨兵在运行时里做的事，桥在模型这一层
  做：运行时会停下来问人的那一步（回车或提交、重的快捷键、点到敏感词表里的词）会被拒绝并给出原因，
  直到调用带上 `confirmed: true`，而模型只有在人于对话中同意之后才可以设置它；dsh 自己的审批策略可以
  在工具前面再加一道真正的门。运行时 `config.toml` 里打开的连接器也搭同一个服务器的便车
  （`read_emails` / `send_email`、`calendar`、`contacts`），所以给运行时配好的邮箱或日历，也是桌面版的
  连接器（它们一出现，「设置 → 连接器」就把它们列为已连接）。`NANOMUSE_PY` 指定运行时的可执行文件，
  用于它不在 `PATH` 上的情况；没有运行时，预设就只是没有手。

在一个干净的安装上对着本地中继做了端到端验证：登录，两个聊天模型不用重启就出现在选择器的
*nanoMuse Cloud* 下，新会话以 *nanoMuse* 的身份开始，「你是谁？」经中继以 nanoMuse 的口吻作答，
「我屏幕上有什么？」在一次 `mcp__nanomuse__computer_screen` 调用后作答，对桌面的描述准确。
[`harness/README.md`](../../harness/README.md) 有具体做法。

第二块加上 Android App 在聊天之外的那些东西，参照 [every-device.md](every-device.md) 为手机列出的
清单：

- **第一次打开。** dsh 自己的首次运行对话框要的是一个 DeepSeek key。bundle 把自己的步骤注册在那个
  位置（`settings.onboarding` 插槽里出厂的 id `deepseek-official`），于是新装的人见到的是智能体：
  形象、一句口号、手（Hands）、Reach 和 Muse 风格是什么，然后是*用手机号或邮箱登录（免费）*、
  *用我自己的 API Key*（打开「模型」）或*以后再说*。只要已经有模型能回答（账号、一个 DeepSeek key、
  人自己加的服务商），这一步就自行完成，除非有人特意重新打开它。
- **来自账号的名字、形象和状态。** hub 说有变化时，宿主拉取中继的资料（`/v1/me/profile`），存在
  `$DSH_HOME/nanomuse/` 下；画出来的形象的五张静态图按形象 id 缓存一次，在
  `/nanomuse/assets/face/<id>/<mood>.webp` 提供。侧边栏品牌标和主视觉戴着它（小龙的静态图、它颜色上
  的一个 emoji，或者画出来的形象），会话运行时是*干活中*，会话在问问题时是*等你回复*；品牌名就是人在
  任何一台设备上给它起的名字。一条系统提示上下文把这个名字告诉模型，所以「你叫什么名字？」会用它来
  回答。在手机上改名，桌面上在 hub 一个来回之内就能看到，不用重启。
- **Reach。** 一个 hub 客户端（`hub.ts`，纯 WebSocket，key 放在 `hello` 帧里）把这台电脑以
  `pc-dsh-<id>` 列进账号的设备表，并应答 `info` 和 `notify`（弹一条提示条）。第二个插件
  `dsh-nanomuse/reach` 注册手机和运行时都有的那些工具：`devices`、`device_screen`（模型接受图片时，
  静态图作为图片送入）、`device_shell` 和 `device_open`（先出 dsh 的审批卡片，命令或 URL 写在里面）、
  `device_files`、`device_notify`，以及 `delegate`：由另一台设备自己的 Muse 来跑任务，当*它*要求
  审批时，问题以审批卡片的形式回到这里，答复再经 hub 传回去。「设置 → *nanoMuse 账号*」列出各设备，
  带在线圆点，可以给这台电脑改名、忘掉离线的设备。
- **胶囊。** 手或 Reach 工作时，窗口顶部的一个小条显示形象、跳动的竖条、*双手 · 第 N 步* 或
  *多端 · 第 N 步*、它在做什么（「on Laptop B: uname -a」「asking Laptop B's Muse」），以及*停止*，
  它像输入框的停止键一样取消这一轮；进行中的调用以 *aborted: the call was stopped* 结束。宿主通过
  dsh 的 `tools/execute` 钩子得知这些调用，并把它们连同资料、hub 状态和通知一起，经一条 SSE 连接
  （`/nanomuse/cloud/events`）流式推给客户端。

在同一个干净安装上，以账号下的第二个运行时作为 *Laptop B* 做了验证：第一次打开一路走到*开始*；
对 Laptop B 的 `devices` 和 `device_files`；`device_shell` 带审批卡片和结果；`delegate` 时 Laptop B
的审批请求被转达并作答（允许和拒绝），*停止*能结束它；另一台设备发来的 `notify` 以提示条显示；在
Laptop B 上设置的名字和 emoji 几秒内就出现在桌面版的品牌标和主视觉上，问它时回答「我叫小蓝」。

第三块让桌面版应答手机，于是 Reach 两个方向都通：

- **这台电脑的手，给别的设备用。** `actions.ts` 是运行时 [hub 动作](hub.md)的移植：`shell`（登录
  shell，有上限的超时，超时返回 124，输出有上限）、`files`、`file.get` / `file.put`（8 MiB 限制、
  `force`、`.nanomuse-part` 改名）、`open` 和 `screen`（依次尝试 `screencapture`、PowerShell、
  `gnome-screenshot` / `spectacle` / `grim` / `scrot` / `import`）。同样的名字、同样的形状、同样的
  错误码，所以手机分不出对面是运行时还是 dsh 桌面版。
- **远程控制开关。** 「设置 → *nanoMuse 账号* → *这台电脑*」下面，和运行时一样的开关：打开，设备在
  `hello` 里声明六个动作；关闭，只声明 `info` 和 `notify`，其余一律以 `not_allowed` 拒绝（手机看到的
  提示和运行时给的一样）。拨动它会重新向 hub 打招呼，账号的设备表立刻更新。约定不变：发出请求的设备
  在发送前先判断命令（手机和运行时上是哨兵，这里是审批卡片）；目标设备不再问第二遍。
- **每次调用都看得见。** 别的设备在这里做了什么，会以提示条显示（「Laptop B 在这里运行了：uname -a」
  「…看了一眼这里的屏幕」），在事情确实发生之后；被拒绝的路径是请求方该看到的错误，这里不弹提示。
- **停止传到对面。** 在 `delegate` 上按*停止*，现在会为那一次调用发送运行时的 `stop {call}`，于是它
  为我们开的线程也随之结束，而不是一直跑到它自己的审批或超时。

验证：第二个 hub 客户端对着桌面版驱动了全部六个动作（一张真实的 3840×2160 截图，一个超时的 `sleep`
返回 124，`exists` / `not_found` / `too_large` 错误码和运行时给的一致），每一个都有提示条；开关关掉后
`shell` 以 `not_allowed` 被拒，`info` 和 `notify` 照常可用，中继的列表显示收窄后的动作集；在
Laptop B 自己的聊天里让它的 Muse「在 Desk A 上」运行一条命令，它经自己的哨兵审批后通过中继做到了，
并报告了输出；在 Laptop B 上委派出去的 `sleep 120`，在这里按下*停止*后两秒内就在那边停了。

第四块是手机的 `delegate` 落到这里；桌面版应答 `task`：

- **任务跑在一个 dsh 会话里。** `task.ts` 通过 dsh 的会话控制器，为每个发起设备和对话各开一个会话
  （用 `nanomuse` 预设 `create`，改名为「From <device>」），把任务作为一条用户消息喂进去，消息里写明
  它从哪来、这是哪台电脑，然后在 `session/event` 流上跟踪运行：`tool/call` → `tool`，
  `tool/result` → `tool_result`，`assistant/message` → 中间的 `text`，`turn/end` → 结果
  `{text, conversation, thread, device}`。和运行时流出的是同一套词汇，所以手机上的 `delegate` 卡片
  读起来一样。会话记在宿主的状态里，同一处来的下一个任务从原地接着，重启也不丢。
- **审批给请求方。** dsh 的 `approval/request` 瀑布上有一个排在界面之前的应答者，认领这些会话的
  提问：问题作为 `approval` 事件传出（工具调用的预览、dsh 给的原因、这台电脑的名字、一个超时），
  请求方的 `approve {approval_id, allow}` 决定结果，`approval_result` 关掉卡片。人在另一台设备那边，
  所以这些运行不弹本地卡片。
- **`stop {call}` 和其余的。** 停止会取消该运行的智能体（`cancel({kind: 'user'})`），这也会结束 dsh
  启动的 shell 子进程；这一轮以 aborted 收尾，请求方拿到到那时为止说过的话。对话运行中返回 `busy`，
  还有 `usage`，超过运行时的十五分钟返回 `timeout`，出错时返回 `failed` 并附模型的消息。`task` 和
  `stop` 与其他动作一样在远程控制开关后面；`approve` 总是应答。任务的到达和结束都以提示条显示。

以 Laptop B 的运行时作为请求方验证：「让 Desk A 的 Muse 运行 `uname -s` 和 `date +%M`」带着答案和一条
`Desk A used bash: …` 步骤回来了；一次写到 dsh 工作区之外的操作触发了 dsh 的门，在 Laptop B 上显示为
「on Desk A: bash: echo outside > ~/…」，在那边批准后，桌面版写了文件并作答；一个长 `sleep` 任务被
`stop {call}` 停掉后三秒内以「(stopped)」收尾，没有留下子进程；dsh 重启后，Laptop B 来的下一个任务
接上了同一个会话，Muse 答出了之前问过它的事。

第五块是窗口本身，盖在 dsh 网页 App 上的 Muse 外形，一屏一屏见 [desktop-muse.md](desktop-muse.md)：

- **侧边栏。** bundle 接管 `sidebar` 位（原装的 `ui-sidebar` 行在 bundle 层关掉），按 Muse 的样子
  布置：一条窄栏，含聊天（智能体工作时有一个圆点）、搜索、设备、装了的话还有日程面板、底部的汉堡
  菜单；再加一个聊天列，用 harness 的 `useSessions`、`useSessionStatus` 和 `useWorkspaces` 搭起来：
  *搜索*带一个 *···*（已归档的聊天）、*主要聊天*（存在 `localStorage`，*设为主要聊天*可以换）、
  *旁聊*带 *+*，置顶的在前，每一行有状态标记和一个菜单，可置顶、就地改名（经会话服务的
  `session.rename`）、归档。harness 自己的工作区浏览器只隔一个开关（「通用」里的*显示 DeepSeek
  Harness 控件*）。
- **页眉。** 形象和名字钉在对话顶部正中（`conversation.header.leading`），旁边一个状态标签（
  未登录、连接中、已连接并显示在线设备、思考中、*双手 · 第 N 步 · 在做什么*、*多端 · 第 N 步 ·
  在做什么*、等你确认），一轮进行中时旁边还有一个*停止*按钮。第二块的胶囊变成了这个标签；它的提示条
  保留。*邀请*占用 `conversation.session.header.utilities`（中继的 `/v1/me/invite`：邀请码、链接、
  来了多少人、得了多少）；harness 的标题行、标签页和会话操作在 Muse 样式下隐藏。
- **资料面板。** 点形象会打开我们自己的一个 `shell.overlay`，310 px，在右侧，和聊天并排：形象带
  一支笔（*更换形象* → 经宿主 `PUT /v1/me/profile`，处处生效；*编辑名称*）、连接状态、四个标签：
  来自会话和 hub 通知的活动、卡片上作出的审批（一个文档级的观察器记录每一次决定）、日程、记忆。
- **对话。** 一张 `html[data-nm-muse]` 下的样式表，盖在 harness 稳定的挂钩上：`[data-composer-card]`
  变成一个药丸形（*+*、*消息*、发送圆钮），`[data-chat-flow-kind="user"]` 变成强调色气泡，智能体的
  步骤变成灰色气泡，`[data-approval-key]` 变成 Muse 的权限卡片（盾牌、标题、蓝色的*允许一次*、
  *拒绝*），主视觉的问候隐藏，输入框停靠在底部；harness 的模型、模式和计划控件从输入框里隐藏，打开
  「开发者」开关就回来。harness 自己的 DOM 不动，只加样式。
- **设置。** 同样接管 `sidebar.settings` 位（原装的 `ui-settings-general` 行关掉）：分组导航（
  通用、账号、模型、智能体、电脑操作、设备、数据控制、帮助与支持、法律信息），然后是其他插件注册的
  每一页，归在*高级*下，底部是*退出登录*。「通用」页是我们的，并声明了 `settings.general.item`，所以
  harness 自己的那些行（权限预设、语言、外观、字号、快捷键……）挂进来，后面是「关于」和「开发者」
  开关。引导协调器和 `settings.open` 快捷键组合沿用；harness 的预览提示（它把确认状态存在那个被
  关掉的插件的设置里）原样放行。
- **第一次打开。** 全窗口，Muse 的那几张页：带形象和一个*登录*药丸的欢迎页 → *登录或创建账户*
  （手机号或邮箱）→ 六格验证码（或密码：`/v1/auth/login`）→ 转圈 → 权限轮播（‹ ›）：macOS 上的
  *允许 nanoMuse 使用你的电脑？*（辅助功能、录屏，各有一个*允许*，经外壳的桥申请，授予后打绿勾）、
  *……访问你的文件？*（工作文件夹，*更改*走系统原生选择器）、*你的其他设备* → *就绪*。
- **桌面外壳的桥。** `harness/desktop/src/preload.ts` 把 `window.nanomuseHarness` 暴露给页面
  （沙箱化，经 IPC 到主进程）：`permissions()`、`requestPermission(kind)`（`systemPreferences`）、
  系统设置的各个面板、`openExternal`、`keepAwake`（会话运行时的防休眠阻止器）、`setTheme`（窗口的
  底色跟随页面）；它在文档上标出平台，于是 bundle 加上 macOS 的留白和拖动把手，因为外壳的窗口在那里
  没有标题栏（`hiddenInset`，红绿灯按钮压在窄栏上方）。没有桥，bundle 也能工作（浏览器里的 dsh）；
  只有电脑卡片和防休眠开关需要它。
- **主题。** Muse 的浅色和深色色调盖在 harness 的令牌上（`--dsw-alias-bg-base`、侧边栏底色、气泡、
  各层），强调色取自账号上形象的颜色。

在浏览器里对着干净安装和开发中继做了验证：从一个全新的主目录开始第一次打开，用验证码登录，经过文件和
设备卡片，到窗口；聊天列里有主要聊天和旁聊，空白的一条显示*新聊天*；页眉的状态标签从*已连接*走到
*等你确认*并带*停止*；药丸形输入框、气泡和审批卡片在两套主题下都正常，一次回答被记进面板的「审批」
标签；资料面板在聊天旁边；设置有九个页面。Electron 外壳在 Linux 上用它的桥启动同一个 bundle
（截图检查）。

## nanoMuse 的每一部分去了哪 {#where-each-part-of-nanomuse-goes}

| 今天的 nanoMuse（Python 运行时）                        | 在 dsh 上                                                                                                                                    | 状态       |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| Cloud 账号、服务商配置（[cloud.md](cloud.md)） | `dsh-nanomuse/cloud` 服务 + `llm-pi-ai` 服务商 + 凭据存储                                                                                     | 已完成     |
| 人设、智能体名字（[design.md](design.md)）            | 智能体预设 `nanomuse`（`@deepseek-ai/dsh-persona`）；账号在资料里选定的名字，放在品牌位和一条系统提示上下文里 | 已完成     |
| 界面里的形象（[avatar.md](avatar.md)）             | 插槽 `sidebar.brand.*`、`conversation.hero.brand.mark`；静态图来自宿主；状态来自会话状态；手工作时的胶囊 | 已完成     |
| 形象跨设备同步                                | `profile.ts` 在 hub 的 `profile` 帧上拉取中继的资料；画出来的形象的静态图由宿主缓存并提供                            | 已完成     |
| 会动的形象（[avatar.md](avatar.md)）                | `Avatar.tsx`：小龙的各状态短视频来自 `assets/`，44 px 及以上静音循环播放，静态图作封面；画出来的形象和 emoji 用 CSS 做呼吸 / 摇摆 / 跳一下，减弱动态下什么都不做 | 已完成     |
| 形象工作室（在这里画新形象）                 | 一个基于中继图像模型的设置页；今天形象在手机上画，这里戴                                                | 阶段 4    |
| 第一次打开                                               | 我们在 dsh `settings.onboarding` 位上的步骤，全窗口：欢迎、登录、验证码格、权限轮播（macOS 上的电脑、文件、设备）、就绪 | 已完成     |
| 窗口（[desktop-muse.md](desktop-muse.md)）         | `sidebar`、`sidebar.settings` 和 `shell.overlay` 位加 Muse 样式表：窄栏 + 主要聊天 / 旁聊、钉住的形象和带停止的状态标签、邀请、资料面板、药丸形输入框、气泡、权限卡片、带「高级」的分组设置、Muse 的色调 | 已完成     |
| 哨兵（[sentinel.md](sentinel.md)）                   | dsh 的审批策略和 `tools/pre-execute` 瀑布；我们的类别变成一个审批预设；看得见的门保留                | 阶段 4    |
| 手：这台电脑的 GUI 控制（[gui.md](gui.md)） | Python 的手经 MCP（`nanomuse mcp`，挂在预设里）：已完成；之后在 dsh 的电脑操作接缝（`ctx.computerUse.register`）后面做一个原生 TypeScript 驱动，就不再需要 Python | 已完成（桥） |
| Reach：手机和其他设备（[hub.md](hub.md)、[every-device.md](every-device.md)） | `hub.ts` + `dsh-nanomuse/reach`：`devices`、`device_screen/shell/files/open/notify`、带转达审批的 `delegate`，按*停止*时发 `stop`；手机那边不变 | 已完成     |
| 被手机控制（shell、文件、屏幕）  | `actions.ts` 以运行时的形状应答 `shell`、`files`、`file.get`、`file.put`、`open`、`screen`，在设置里的远程控制开关后面；每次调用一条提示条 | 已完成     |
| 在这里为手机跑一个任务（`task`）                  | `task.ts`：手机的 `delegate` 落进一个 dsh 会话（「From <device>」，下次接着用），运行以运行时的事件帧流回去，审批转达给请求方，`stop {call}` 照办 | 已完成     |
| 连接器（[desktop-muse.md](desktop-muse.md#settings)） | `connectors.ts`：约 70 个远程 MCP 服务器的目录、MCP 授权流程（元数据、DCR、PKCE、刷新）、key、MCP Registry 搜索，以及一个持有凭据并过滤工具的回环代理；`connectors-tools.ts` 为每个连接挂一个 `dsh-mcp-client`，并跟着页面走 | 已完成     |
| 技能、日程、目标、记忆、子智能体             | dsh 自己的（`skill`、`schedule`、`goals`、压缩、委派）；我们的不移植                                                        | 有意为之  |
| 网页界面、zh-CN                                           | dsh 的网页 App（它自带中文）；我们的字符串在 bundle 的语言表里                                                                        | 已完成     |
| 桌面外壳                                       | `harness/desktop`：我们的 Electron 外壳，harness 的 Host 作为子进程以 Node 模式运行，里面是 dsh + bundle + 负责手的运行时；Windows、macOS、Linux 的安装包由 `desktop-app.yml` 产出 | 已完成（未签名） |
| nanomuse.cn/web 的浏览器演示                         | 留在 Python 运行时上                                                                                                                  | 不变  |
| 手机                                               | 留在 Python 运行时上；通过账号和 Reach 与桌面版相遇                                                                 | 不变  |

## 做这一块时学到的 {#what-we-learned-building-the-slice}

- bundle patch 会整个替换一行的 `config`，所以我们碰到的行要把需要的每个键都重新写一遍；`insert:`
  用来加行。bundle 层在启动时读取（改完要重启）；profile 自己的 patch 可以热加载。
- 预设的插件列表是 dsh *Standard* 在钉住版本上的一份拷贝，因为预设必须整个声明。dsh 升级时，对着
  `@deepseek-ai/dsh-web-app/presets/standard.patch.yml` 做 diff。我们自己的能力以插件的身份进这个
  列表；这正是要点。
- 主视觉的大标题（*Into the Unknown*）是 dsh `conversation` 命名空间里的一条语言字符串；同一命名空间、
  同一语言再注册第二本字典会抛错，所以今天没法从插件里替换它。向上游要一个插槽，或者忍着。
- 同一等级上的两个插槽注册会抛错，原装品牌标就是这么被发现的；关掉它那一行（`ui-brand-official`）
  比压过它的等级更干净。
- 模型选择器按 id 列出服务商的模型（`qwen3.8-flash`），和 DeepSeek 自家的一样；显示名放在服务商那
  一行，等 dsh 用到它的时候。
- `dsh plugin add` 需要 `PATH` 上有 pnpm，而且它链接的是检出的源码，所以 `pnpm build` 加一次重启就是
  整个循环。Node 22.19+。
- `settings.onboarding` 协调器一次只挂一个步骤，而且只在主视图是空白会话时挂；它每次渲染都给步骤一个
  新的 `complete` 闭包，所以步骤必须在挂载时一次决定好，否则一次重渲染就会把正在输验证码的人扔回
  第一页。
- `tools/execute` 是一个环绕钩子（`ctx.on('tools/execute', (exec, next) => …)`），不碰工具就足以知道
  一次手或 Reach 的调用何时开始、何时结束；胶囊和步数计数器都挂在它上面。
- 工具返回的图片必须经附件存储（`attachments.saveImages`），而且只在
  `llm.resolveModelInfo(...).inputModalities` 包含 `image` 时才行；否则工具用文字说它看到了什么；
  MCP 客户端也是这么做的。
- hub 没有取消帧，也不需要：运行时的 `stop {call}` 动作会结束它为一次 `task` 调用开的线程，所以
  一开始就把调用 id 记下来，在这一轮被中止时为它发 `stop`，就能停掉对面的活。运行时的 `stop_thread`
  不会杀掉沙箱里已经在跑的 shell 子进程（那个会自己结束），这是运行时该收紧的细节，不是协议的缺口。
- 中继的 `controllable` 标志只表示*不是浏览器标签页*；一台设备允许什么，看它声明的 `actions` 列表，
  在 `hello` 里重发。关掉远程控制的设备必须重连（或重新打招呼），账号才能看到收窄后的列表。
- 从宿主驱动一个会话是三个调用：`sessionController.create` / `rename`、
  `resolveAgent(id).agent.followup(createUserMessage(…))`，再加 `session/event` 流看发生了什么
  （`tool/call`、`tool/result`、`assistant/message`、`turn/end`）。`dsh-schedule` 做提醒用的也是
  同一套。`approval/request` 瀑布接受用 `prepend` 注册的应答者，这样一次运行的提问就能转到别处，
  而不碰界面的应答者。
- 没带工作区创建的会话会落在侧边栏的 *Ungrouped* 下，用 dsh 的默认 cwd（进程的）；预览够用了，之后
  换成选定的工作区。

## 名字和许可 {#names-and-licences}

DeepSeek Harness 是 MIT 许可；它是依赖，不是内嵌的拷贝，它的声明随它一起走。我们的 bundle 和 nanoMuse
的其余部分一样是 GPL-3.0-or-later，所以「没有闭源组件」的承诺依然成立。「DeepSeek Harness」和「DSH」
是 DeepSeek 的名字：我们说*基于 DeepSeek Harness 构建*，从不把它们用进我们自己的名字里，出厂的「关于」
文字和品牌素材保持原样。惯常的声明（Muse 是 Meta 的商标，nanoMuse 是社区项目，与 Meta 无关）照旧
适用。

## 阶段 {#phases}

1. **这一块。** 账号、形象、口吻，以及经 MCP 的手；在干净安装上验证过。*已完成，内部。*
2. **Muse 风格和 Reach。** 第一次打开、账号的名字、形象和状态、带停止的胶囊、hub 客户端、`device_*`
   工具和带转达审批的 `delegate`、设置里的设备列表。*已完成，内部。*
3. **双向 Reach。** 桌面版在它的远程控制开关后面应答 `shell`、`files`、`file.get`、`file.put`、
   `open` 和 `screen`，每次调用一条提示条，*停止*能停掉另一台设备上委派出去的活；手机的 `delegate`
   在这里的 dsh 会话中运行，审批转回去。*已完成，内部。*
4. **窗口。** Muse 的外形：窄栏和聊天列、钉住的形象和状态行与停止、把 harness 的额外项归在「高级」下
   的分组设置、带卡片的第一次打开、主题。*已完成，内部。*
5. **日常可用。** 哨兵变成审批预设、形象工作室搬到这里、不要 Python 的手（dsh 电脑操作接缝后的原生
   驱动）、给其他设备发来的任务选定一个工作区；人可以在里面处理文件和网页上的日常工作。
6. **发布。** 外壳，分两步。dsh 自己的桌面 App 是同一个网页 App 的 Electron 包装，带一个接受外部
   插件的 `desktop` profile（`dsh plugin --profile desktop add …`），所以第一个 nanoMuse 桌面版就是
   那个 App 加上 profile 里的 bundle：**从 0.1.27 起每个版本都带打包好的 bundle**（当时叫
   `nanoMuse-Harness-<v>.tgz`，从 0.1.30 起叫 `dsh-nanomuse-<v>.tgz`），安装方法在
   [harness/README.md](../../harness/README.md)（`.github/workflows/harness.yml` 构建、测试、打包它，
   并把 tar 包装进一个全新的 dsh profile）。**从 0.1.28 起第二步也到位了**：我们自己的外壳，在
   [`harness/desktop/`](../../harness/desktop/)，不是重新构建 dsh 的 `apps/desktop`（它的流水线要
   准备一个私有 Host、一个主运行时和硬件令牌签名，本身就是一个项目），而是一个小小的 Electron App，
   做那个 App 核心上做的事：用自己的二进制以 Node 模式把 harness 的 Host 作为子进程启动
   （`ELECTRON_RUN_AS_NODE`、`--expose-internals`；harness 的 `require-builtin` 原生扩展带着它构建时
   所针对的 Electron 的指纹，所以外壳钉在 `44.0.0`），dsh 是构建时 npm 装到 `resources/dsh` 下的，
   bundle 也一起；用的是 `~/.nanomuse/desktop` 下它自己的 profile，里面写明 bundle，并链接到 App 内的
   那份拷贝。负责手的运行时以 PyInstaller 构建随行，`NANOMUSE_PY` 把预设指向它。`desktop-app.yml`
   在每个发布标签上构建 Windows 安装包、两种架构的 macOS dmg/zip 和 Linux AppImage/deb，把每个打包好
   的 harness 以 Node 模式启动一次作为检查，再列一遍 Windows 安装包里的压缩档，确认形象的四段短片在里面
   （electron-builder 的 NSIS 目标默认把视频文件排除在这个压缩档之外、再逐个加回去，加回去时跳过所有
   `node_modules`，而插件的短片正好放在那里；`electron-builder.yml` 里的
   `nsis.preCompressedFileExtensions: []` 关掉了这个行为，`tests/installer.test.mjs` 守着它），然后附到
   发布上（设置了同一组 Apple 密钥时，还会给 macOS 构建签名和公证）。它在 0.1.28 和 0.1.29 以 *nanoMuse Harness* 之名和旧桌面 App 并列发布；**从
   0.1.30 起它就是 nanoMuse 桌面版**，唯一的那个桌面 App（`nanoMuse-Desktop-<v>-…`，沿用已退役的
   `desktop/app` 的应用 id，所以可以直接覆盖安装），站点的下载也指向这里。
7. **新外壳上的日常可用。** Muse 在聊天旁边的那些房间（动态、点子、目标、资源库）、手在这块屏幕上
   工作时的实时舞台、两个平台上的签名、我们自己的更新推送、harness 桌面版有的 macOS 关闭到 Dock 和
   Windows 托盘行为、给其他设备发来的任务选定一个工作区。

包着 Python 运行时的 Electron 外壳（`desktop/app`，0.1.19–0.1.29）已经没了；它有而 harness 没有的
（舞台、托盘、快速唤起）随着阶段 7 推进，在 dsh 的接缝上回到这里。随后的终端版（0.1.30–0.1.38）在
0.1.39 里去掉了：桌面 App 是唯一的桌面形态，Python 运行时留给自己部署和网页控制台。
