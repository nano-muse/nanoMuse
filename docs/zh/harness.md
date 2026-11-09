# 基于 DeepSeek Harness 的 nanoMuse {#跑在-deepseek-harness-上的-nanomuse}

> **状态：已发布**。代码位于 `main` 分支的 [`harness/`](../../harness/)。从 0.1.30 起，这套实现就是 **nanoMuse 桌面版**，也是唯一的桌面应用。Windows、macOS 和 Linux 安装包都内置了 harness（负责组织模型、工具和任务执行的智能体框架）、nanoMuse 插件包，以及负责电脑操作的运行时，见 [desktop.md](desktop.md)。插件包也会单独发布为 `dsh-nanomuse-<v>.tgz`，供已安装 DeepSeek Harness Desktop 的用户使用，见 [harness/README.md](../../harness/README.md)。
> 这次替换分两步完成：0.1.27 开始发布插件包，0.1.28 至 0.1.29 将新外壳作为 *nanoMuse Harness* 与旧 Electron 应用同时发布，见[阶段](#phases)。本页保留设计与实施计划，[desktop-muse.md](desktop-muse.md) 则逐屏说明窗口的设计。

## 为什么采用这套方案 {#the-decision}

作出这项决定时，桌面版使用自行维护的框架：Electron 外壳内运行 Python 程序，程序自己实现智能体循环、工具注册、技能、日程、记忆、子智能体和网页界面。它与手机和浏览器演示共用代码，这是采用该方案的原因。

这些功能在 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（`dsh`）中都有对应实现。dsh 是采用 MIT 许可证的开源智能体框架，插件系统建立在 [Cordis](https://github.com/cordiverse/cordis) 上。它提供网页版、桌面版、MCP 客户端（按统一协议连接外部工具的组件）、技能、目标、计划模式、上下文压缩、任务委派、审批策略、电脑操作，以及可在配置中接入任意 OpenAI 兼容接口的模型层。作出决定时的版本是 0.2.0-rc，属于开发者预览版，插件 API 仍会发生不兼容变更。不过，它已有的社区规模，是本项目自行开发多年也难以达到的。

因此，新桌面版采用 **dsh 加 nanoMuse 插件**。账号、形象、口吻、手（Hands，查看并操作屏幕的能力）、Reach（跨设备访问和委派任务的能力）及哨兵（Sentinel，检查操作风险和权限的组件）通过插件接入；智能体循环、工具体系和界面使用 dsh 的实现。项目不再为桌面版单独维护另一套框架。手机继续使用 Python 运行时，因为 dsh 基于 Node，无法在 Android 上运行。浏览器演示暂时也继续使用 Python。不同实现仍通过同一个账号互通。

## 各阶段实现了什么 {#what-runs}

第一部分是 dsh 插件包 `dsh-nanomuse`，源码位于 [`harness/dsh-nanomuse/`](../../harness/dsh-nanomuse/)。它被链接到根据 dsh 网页模板创建的 profile（保存插件和运行配置的一组配置文件）中。

- **账号**。宿主服务 `nanomuseCloud` 使用与手机和旧桌面版相同的两个接口 `/v1/auth/code`、`/v1/auth/verify` 登录中继（负责账号和设备通信的服务）。它将 key 以 `NANOMUSE_CLOUD_TOKEN` 存入 dsh 凭据库，并在模型适配器 `dsh-llm-pi-ai` 中添加名为 *nanoMuse Cloud* 的服务商，base URL 为中继的 `/v1`。这里直接使用 dsh 的适配器，因为两端都支持 OpenAI Chat Completions 协议。退出登录时，凭据和服务商配置都会删除。设置页通过仅允许同源访问的本机回环 API `/nanomuse/cloud/{status,code,verify,refresh,sign-out}` 获取数据。「回环」指通信只在本机内部进行。
- **形象和名字**。网页组件使用 dsh 的插槽，即插件预留的界面位置，在侧栏品牌区和欢迎区显示小龙及 *nanoMuse* 字标，并在设置中添加 nanoMuse 账号区域。登录流程为手机号或邮箱、验证码、已登录，随后显示脱敏账号标识、额度和模型。配置补丁会关闭默认品牌插件，静态图片由宿主提供。
- **口吻**。dsh 网页会话使用智能体预设，预设内的人设优先于全局人设。因此，插件包声明并默认使用 `nanomuse` 预设，插件列表与 dsh 的 *Standard* 相同，人设改为 nanoMuse。用户仍可选择 *Standard*、*PTC* 或 *Minimal*。
- **手，首个以插件接入的 nanoMuse 能力**。预设将 dsh 的 MCP 客户端连接到 `nanomuse mcp`，见 [cli.md](cli.md#audit-and-config)。运行时通过 stdio（程序的标准输入和输出）提供 `computer_screen`、`computer_act` 及它们的描述和参数结构，在 dsh 中分别显示为 `mcp__nanomuse__computer_screen`、`…computer_act`。截图作为 MCP 图片传输，因此视觉模型能够查看屏幕。桥接组件会在模型调用层执行原本由运行时哨兵负责的检查：按回车或提交、使用影响较大的快捷键、点击敏感词清单中的文字时，会先拒绝调用并说明原因。只有用户在对话中同意后，模型才可添加 `confirmed: true` 再调用。dsh 自身的审批策略还可以在工具执行前加入实际的权限拦截。运行时 `config.toml` 中启用的连接器也由同一个服务器提供，包括 `read_emails` / `send_email`、`calendar`、`contacts`。因此，为运行时配置的邮箱或日历也能在桌面版使用，工具出现后，设置 → 连接器会将它们列为已连接。如果运行时不在 `PATH`（系统搜索可执行文件的目录列表）中，可以用 `NANOMUSE_PY` 指定路径。未安装运行时时，预设仍可使用，但没有屏幕操作能力。

这一部分已在全新安装、本地中继环境下完成端到端验证：登录后，无需重启，模型选择器就在 *nanoMuse Cloud* 下显示两个对话模型；新会话使用 *nanoMuse* 预设；「你是谁？」经中继得到符合 nanoMuse 人设的回答；「我屏幕上有什么？」调用一次 `mcp__nanomuse__computer_screen` 后，正确描述了桌面。具体复现步骤见 [`harness/README.md`](../../harness/README.md)。

第二部分参照 [every-device.md](every-device.md) 中的手机功能，补齐 Android 应用在聊天之外的功能：

- **首次运行引导**。dsh 默认要求输入 DeepSeek key。插件包在 `settings.onboarding` 插槽中，以默认的 `deepseek-official` id 注册自己的步骤。全新安装先显示形象、一句介绍、手和 Reach 的说明，再提供「用手机号或邮箱登录（免费）」「用我自己的 API key」（打开模型页）和「以后再说」。如果已有可回答的模型，无论来自账号、DeepSeek key 还是用户添加的服务商，引导会自行完成；用户主动重开时除外。
- **账号中的名字、形象和状态**。hub（设备互联）发出资料变更消息后，宿主从 `/v1/me/profile` 获取资料，保存到 `$DSH_HOME/nanomuse/`。生成形象的五张静态图按形象 id 缓存一次，通过 `/nanomuse/assets/face/<id>/<mood>.webp` 提供。侧栏品牌区和欢迎区显示账号选择的小龙静态图、带背景色的 emoji 或生成形象；会话运行时切换为「干活中」，等待回答时切换为「等你回复」。名称使用用户在任意设备上设置的名字，并通过系统提示上下文告知模型，因此它也能用这个名字回答「你叫什么名字？」。在手机改名后，桌面版经过一次 hub 通信往返即可更新，无需重启。
- **Reach**。`hub.ts` 使用 WebSocket（可持续双向收发消息的网络连接），在 `hello` 帧中携带 key，将电脑以 `pc-dsh-<id>` 加入账号设备列表，并应答 `info`、`notify`，后者显示临时提示。`dsh-nanomuse/reach` 插件注册与手机和运行时相同的工具：`devices`、`device_screen`、`device_shell`、`device_open`、`device_files`、`device_notify`、`delegate`。模型支持图片输入时，`device_screen` 会返回图片；`device_shell` 和 `device_open` 先显示包含命令或 URL 的 dsh 审批卡片。`delegate` 将任务交给另一台设备上的 nanoMuse；对方需要审批时，卡片传回本机，回答再经 hub 返回。设置中的 nanoMuse 账号页列出设备及在线状态，还可为本机改名、移除离线设备。
- **胶囊状态条**。手或 Reach 工作时，窗口顶部的圆角状态条显示形象、动态竖条、「手 · 第 N 步」或「Reach · 第 N 步」、当前操作，例如在 Laptop B 上运行 `uname -a` 或请求其 nanoMuse，以及「停止」按钮。点击后与输入框中的停止按钮一样，会取消当前轮次，正在执行的调用返回 *aborted: the call was stopped*。宿主通过 dsh 的 `tools/execute` 钩子获知调用进度，并通过一条 SSE 连接 `/nanomuse/cloud/events`，将进度、资料、hub 状态和通知持续推送给客户端。SSE 是服务器向页面持续发送事件的方式。

验证仍使用同一全新安装，并在账号下增加一个名为 *Laptop B* 的运行时：首次引导可以走到「开始」；可对 Laptop B 调用 `devices`、`device_files`；`device_shell` 正确显示审批和结果；`delegate` 可转发 Laptop B 的审批并接受允许或拒绝，「停止」也能结束委派。另一台设备发送的 `notify` 会显示提示。在 Laptop B 设置的名字和 emoji，几秒后会显示在桌面版侧栏和欢迎区；询问名字时，智能体回答「我叫小蓝」。

第三部分让桌面版接收手机请求，使 Reach 支持双向操作：

- **让其他设备操作本机**。`actions.ts` 移植运行时的 [hub 动作](hub.md)，包括 `shell`、`files`、`file.get` / `file.put`、`open`、`screen`。`shell` 使用登录 shell，限制超时和输出大小，超时返回 124；文件传输保持 8 MiB 限制、`force` 和 `.nanomuse-part` 临时文件重命名机制；截图按平台依次尝试 `screencapture`、PowerShell、`gnome-screenshot` / `spectacle` / `grim` / `scrot` / `import`。名称、数据结构和错误码与运行时相同，手机不需要区分对方是哪种实现。
- **远程控制开关**。位于设置中的 nanoMuse 账号页「这台电脑」下，与运行时一致。开启时，设备在 `hello` 中声明六种动作；关闭时只声明 `info`、`notify`，其余返回 `not_allowed`，手机看到的提示也与运行时相同。切换后会重新向 hub 发送设备声明，立即更新账号设备列表。权限约定不变：请求方在发送前检查命令，手机和运行时使用哨兵，桌面版显示审批卡片；目标设备不重复询问。
- **显示实际执行的调用**。其他设备确实在本机完成操作后，会显示提示，例如「Laptop B 在这里运行了：uname -a」或「看了一眼这里的屏幕」。被拒绝的文件路径由请求方看到错误，本机不显示提示。
- **停止对端任务**。停止 `delegate` 时，会针对该次调用发送 `stop {call}`，结束对端为它创建的执行线程，不再任由任务继续到下一次审批或超时。

验证中，第二个 hub 客户端在桌面版执行了全部六种动作：获取真实的 3840×2160 截图，超时的 `sleep` 返回 124，文件操作返回与运行时相同的 `exists` / `not_found` / `too_large`，每次成功操作均显示提示。关闭远程控制后，`shell` 返回 `not_allowed`，`info`、`notify` 仍可用，中继设备列表也显示缩减后的动作集。在 Laptop B 的聊天中要求它「在 Desk A 上」执行命令，经 Laptop B 的哨兵批准后，命令通过中继执行并返回输出。在本机停止委派给 Laptop B 的 `sleep 120`，对端会在两秒内停止。

第四部分让手机的 `delegate` 任务在桌面版执行，桌面版开始应答 `task`：

- **在 dsh 会话中执行任务**。`task.ts` 通过 dsh 会话控制器，为每个请求设备及其对话创建会话，使用 `nanomuse` 预设调用 `create`，并命名为「From <device>」。任务作为用户消息传入，同时说明来源和本机身份。运行进度来自 `session/event`：`tool/call` 转为 `tool`，`tool/result` 转为 `tool_result`，`assistant/message` 转为中间 `text`，`turn/end` 转为 `{text, conversation, thread, device}`。这些事件名称与运行时相同，手机的 `delegate` 卡片可直接显示。宿主会保存会话对应关系，即使重启，同一来源的下个任务仍会继续原会话。
- **将审批交给请求方**。插件在 dsh 的 `approval/request` 处理链中注册一个早于本地界面的处理器，接管这些会话的审批。它通过 `approval` 事件发送工具调用预览、dsh 给出的原因、本机名称和超时时间；请求方以 `approve {approval_id, allow}` 回答，`approval_result` 关闭卡片。因为用户在另一台设备上，这些任务不会弹出本机审批卡片。
- **处理 `stop {call}` 和其他状态**。停止操作调用 `cancel({kind: 'user'})` 取消本轮智能体运行，同时结束 dsh 启动的 shell 子进程。轮次以 aborted 结束，请求方仍能收到已生成的文字。对话正在执行时返回 `busy`，另有 `usage`；超过运行时规定的十五分钟返回 `timeout`；模型出错则返回 `failed` 和错误信息。`task`、`stop` 与其他动作一样受远程控制开关限制，`approve` 则始终应答。任务到达和结束都会显示提示。

使用 Laptop B 的运行时验证了这些行为：要求「让 Desk A 的 nanoMuse 运行 `uname -s` 和 `date +%M`」后，收到了回答和 `Desk A used bash: …` 步骤。写入 dsh 工作区以外的文件时，审批在 Laptop B 上显示为「on Desk A: bash: echo outside > ~/…」，在对端批准后桌面版才写入并回答。长时间 `sleep` 任务收到 `stop {call}` 后，三秒内返回「(stopped)」，没有残留子进程。重启 dsh 后，Laptop B 的下个任务仍能继续原会话，智能体也记得先前的问题。

第五部分实现窗口界面，在 dsh 网页应用上采用手机应用的布局，逐屏设计见 [desktop-muse.md](desktop-muse.md)：

- **侧栏**。插件包接管 `sidebar` 插槽，在自身配置层关闭默认的 `ui-sidebar`。左侧窄栏包含聊天、搜索、设备、已安装时显示的日程面板，以及底部菜单；智能体工作时，聊天图标带圆点。旁边的聊天列用 harness 的 `useSessions`、`useSessionStatus`、`useWorkspaces` 构建，包含带「···」归档入口的搜索、「主要聊天」和带「+」的「旁聊」。主要聊天选择保存在 `localStorage`，可用「设为主要聊天」更换。置顶会话排在前面，每行显示状态，并提供置顶、直接改名和归档菜单。改名通过会话服务的 `session.rename` 完成。在通用设置开启「显示 DeepSeek Harness 控件」，即可显示 harness 自带的工作区浏览器。
- **对话顶部**。`conversation.header.leading` 将形象和名字固定在顶部中央，旁边显示状态：未登录、连接中、已连接及在线设备数、思考中、手或 Reach 的步数与当前操作、等你回复。运行期间还有「停止」。第二部分的胶囊变为这里的状态标签，临时通知继续保留。「邀请」占用 `conversation.session.header.utilities`，通过中继 `/v1/me/invite` 显示邀请码、链接、受邀人数和奖励。插件样式会隐藏 harness 默认标题行、标签页和会话操作。
- **资料面板**。点击形象会通过 `shell.overlay` 在聊天右侧打开 310 px 宽的面板。形象旁有铅笔，可「更换形象」或「编辑名称」；更换通过宿主调用 `PUT /v1/me/profile`，各设备同步生效。面板还显示连接状态和四个标签：来自会话及 hub 通知的活动、审批、日程、记忆。审批记录由文档级观察器收集卡片上的每次决定。
- **对话样式**。样式限定在 `html[data-nm-muse]`，使用 harness 稳定的界面标记。`[data-composer-card]` 变为包含「+」、消息输入和圆形发送按钮的圆角输入条；`[data-chat-flow-kind="user"]` 的用户气泡在浅色主题下黑底白字，在深色主题下白底黑字；助手步骤使用灰色圆角气泡；对话在顶部的渐隐遮罩下滚动。`[data-approval-key]` 显示带盾牌、标题、蓝色「允许一次」和「拒绝」的权限卡片。欢迎语隐藏，输入框固定到底部。模型、模式、计划控件默认隐藏，打开「开发者」开关后显示。实现仅调整样式，不修改 harness 的 DOM 结构。
- **设置**。插件包也接管 `sidebar.settings`，关闭默认 `ui-settings-general`。导航按通用、账号、模型、智能体、电脑操作、设备、数据控制、帮助与支持、法律信息分组；其他插件注册的页面放在「高级」，底部为「退出登录」。nanoMuse 的通用页声明 `settings.general.item`，供 harness 的权限预设、语言、外观、字号、快捷键等设置挂载，再加上「关于」和「开发者」开关。原有引导协调器及 `settings.open` 快捷键继续使用。harness 的预览提示也继续显示，其确认状态仍存于已关闭插件的设置中。
- **首次运行**。全窗口引导依次为：带形象和「登录」按钮的欢迎页；「登录或创建账户」，支持手机号或邮箱；六格验证码或密码登录 `/v1/auth/login`；加载指示；可用 ‹ › 切换的权限页面。在 macOS 上先询问是否允许 nanoMuse 操作电脑，分别申请辅助功能和录屏权限，每项有「允许」按钮，经外壳桥接申请，成功后显示绿勾。随后是文件访问，展示工作区并用系统选择器「更改」；再是「你的其他设备」；最后显示就绪。
- **桌面外壳桥接**。`harness/desktop/src/preload.ts` 向页面提供 `window.nanomuseHarness`。页面运行在沙箱中，通过 IPC（进程间通信）调用主进程的 `permissions()`、`requestPermission(kind)`，后者使用 `systemPreferences`；还可打开系统设置面板、调用 `openExternal`、用 `keepAwake` 在会话运行期间防止休眠、用 `setTheme` 让窗口底色跟随页面。桥接会标记当前平台，以便插件包为 macOS 添加留白和可拖动区域，因为 macOS 使用无标题栏的 `hiddenInset` 窗口，窗口控制按钮位于窄栏上方。在浏览器运行 dsh 时没有这套桥接，插件包仍可工作，只有电脑权限卡片和防休眠开关依赖它。
- **主题**。应用的浅色和深色主题使用 harness 的样式变量，例如 `--dsw-alias-bg-base`，统一侧栏、气泡和各层背景。强调色来自账号的形象颜色。

这部分已在浏览器、全新安装和开发中继环境下验证：从新数据目录开始，验证码登录，经过文件和设备卡片进入主窗口；聊天列显示主要聊天、旁聊，空白会话名为「新聊天」；顶部状态从已连接切换为等你回复，并显示「停止」；两种主题下的输入条、气泡和审批卡片均正常；审批回答进入资料面板的审批标签；资料面板在聊天右侧；设置包含九个页面。Linux Electron 外壳启动了同一插件包及桥接，并完成截图检查。

## nanoMuse 各组件在 dsh 中的位置 {#where-each-part-of-nanomuse-goes}

| 现有 nanoMuse 组件（Python 运行时） | dsh 中的实现 | 状态 |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| Cloud 账号、服务商配置（[cloud.md](cloud.md)） | `dsh-nanomuse/cloud` 服务、`llm-pi-ai` 服务商及凭据库 | 已完成 |
| 人设与智能体名字（[design.md](design.md)） | `nanomuse` 智能体预设（`@deepseek-ai/dsh-persona`）；从账号资料读取名字，用于品牌区和系统提示上下文 | 已完成 |
| 界面形象（[avatar.md](avatar.md)） | 使用 `sidebar.brand.*`、`conversation.hero.brand.mark` 插槽；宿主提供静态图，会话状态决定形象状态，手工作时显示胶囊 | 已完成 |
| 跨设备形象同步 | `profile.ts` 收到 hub 的 `profile` 帧后获取中继资料；宿主缓存并提供生成形象的静态图 | 已完成 |
| 形象动画（[avatar.md](avatar.md)） | `Avatar.tsx` 在 44 px 及以上静音循环播放 `assets/` 的小龙状态视频，静态图作封面；生成形象和 emoji 用 CSS 做呼吸、摇摆、跳跃效果，减少动态效果模式下不播放 | 已完成 |
| 形象工作室，在本机生成形象 | `AvatarStudio.tsx` 提供四个本地化灵感预设或文字描述，使用「模型」中选择的自有图像服务商和 API key 生成候选及状态图；公开托管的 Cloud 不提供媒体生成 | 已完成 |
| 首次运行 | 在 dsh 的 `settings.onboarding` 插槽注册全窗口流程：欢迎、登录、验证码、权限切换卡片（macOS 电脑权限、文件、设备）、就绪 | 已完成 |
| 窗口（[desktop-muse.md](desktop-muse.md)） | `sidebar`、`sidebar.settings`、`shell.overlay` 插槽及插件包样式：窄栏、主要聊天和旁聊、固定形象、带停止的状态标签、邀请、资料面板、圆角输入条、气泡、权限卡片、带高级分组的设置和应用主题 | 已完成 |
| 哨兵（[sentinel.md](sentinel.md)） | dsh 审批策略和 `tools/pre-execute` 顺序处理链；将 nanoMuse 风险类别映射为审批预设，保留可见的确认步骤 | 阶段 4 |
| 手，本机图形界面操作（[gui.md](gui.md)） | 已通过 MCP 连接 Python 的手（`nanomuse mcp`，在预设中挂载）；之后计划在 dsh 电脑操作扩展接口 `ctx.computerUse.register` 后接入原生 TypeScript 驱动，去掉 Python 依赖 | 已完成桥接 |
| Reach，手机与其他设备（[hub.md](hub.md)、[every-device.md](every-device.md)） | `hub.ts` 和 `dsh-nanomuse/reach` 提供 `devices`、`device_screen/shell/files/open/notify`、转发审批的 `delegate`，点击「停止」发送 `stop`；手机实现不变 | 已完成 |
| 手机远程操作本机的命令、文件和屏幕 | `actions.ts` 按运行时的数据结构应答 `shell`、`files`、`file.get`、`file.put`、`open`、`screen`，受设置中的远程控制开关限制，每次调用显示提示 | 已完成 |
| 为手机执行任务（`task`） | `task.ts` 将手机 `delegate` 交给名为「From <device>」的 dsh 会话，下次继续使用；以运行时的事件帧回传进度，将审批交给请求方，并处理 `stop {call}` | 已完成 |
| 连接器（[desktop-muse.md](desktop-muse.md#settings)） | `connectors.ts` 提供约 70 个远程 MCP 服务器目录、MCP 授权流程（元数据、DCR 动态客户端注册、PKCE 授权码校验、凭据刷新）、key、MCP Registry 搜索，以及保存凭据并过滤工具的本机代理；`connectors-tools.ts` 为每个连接挂载 `dsh-mcp-client`，并随页面设置更新 | 已完成 |
| 技能、日程、目标、记忆、子智能体 | 使用 dsh 的 `skill`、`schedule`、`goals`、上下文压缩和委派，不移植原实现 | 按设计使用 dsh |
| 网页界面、zh-CN | 使用已内置中文的 dsh 网页应用；nanoMuse 文案保存在插件包的语言表中 | 已完成 |
| 桌面外壳 | `harness/desktop` 的 Electron 外壳以 Node 模式将 harness Host 作为子进程启动，内含 dsh、插件包和手的运行时；`desktop-app.yml` 生成 Windows、macOS、Linux 安装包 | 已完成，未签名 |
| nanomuse.cn/web 浏览器演示 | 继续使用 Python 运行时 | 不变 |
| 手机 | 继续使用 Python 运行时，通过账号和 Reach 与桌面版互通 | 不变 |

## 实现中需要注意的事项 {#what-we-learned-building-the-slice}

- 插件包补丁会替换整行 `config`，所以修改某行时必须重新写明该行需要的全部键。`insert:` 用于新增行。插件包配置层只在启动时读取，修改后要重启；profile 自身的补丁支持热重载。
- 预设必须完整声明插件列表，因此 `nanomuse` 的列表复制自所固定 dsh 版本的 *Standard*。升级 dsh 时，要与 `@deepseek-ai/dsh-web-app/presets/standard.patch.yml` 比较差异。nanoMuse 的能力作为插件加入这份列表。
- 欢迎区标题 *Into the Unknown* 是 dsh 的 `conversation` 命名空间中的语言字符串。同一命名空间、同一语言注册第二份词典会报错，因此目前插件无法替换它。需要上游增加插槽，或保留原文。
- 两个界面组件以相同优先级注册同一插槽会报错，默认品牌图标的冲突就是这样发现的。应关闭其 `ui-brand-official` 配置行，无需再提高 nanoMuse 的优先级。
- 模型选择器与列出 DeepSeek 模型一样，按 id 显示服务商模型，例如 `qwen3.8-flash`。显示名称保存在服务商配置行中，供 dsh 使用。
- `dsh plugin add` 要求 `PATH` 中有 pnpm，并链接当前检出的源码。因此开发循环为 `pnpm build` 后重启，需要 Node 22.19+。
- `settings.onboarding` 协调器每次只挂载一个步骤，且主视图必须是空白会话。它每次渲染都会提供新的 `complete` 闭包，所以步骤应只在初次挂载时作出完成判断，否则用户正在输入验证码时，一次重新渲染就可能将其退回第一页。
- `tools/execute` 是能包住调用前后过程的钩子，写法为 `ctx.on('tools/execute', (exec, next) => …)`。不改工具本身，也能获知手或 Reach 的调用开始与结束，胶囊和步数计数器都据此更新。
- 工具返回的图片必须经过附件存储 `attachments.saveImages`，并且 `llm.resolveModelInfo(...).inputModalities` 包含 `image` 时才能送入模型。否则工具只用文字描述看到的内容，MCP 客户端也遵守此规则。
- hub 不需要单独的取消帧。运行时的 `stop {call}` 会结束为某次 `task` 创建的线程，只要开始时保存调用 id，在轮次中止时为它发送 `stop`，就能停止对端任务。运行时的 `stop_thread` 尚不会终止沙箱中已经启动的 shell 子进程，该进程会自行结束。这是运行时实现需要改进之处，不是协议缺少能力。
- 中继的 `controllable` 只表示设备不是浏览器标签页。设备支持哪些操作，要看它在 `hello` 中声明的 `actions` 列表。关闭远程控制时，必须重连或重新发送声明，账号设备列表才会看到缩减后的动作。
- 宿主驱动会话涉及三类调用：用 `sessionController.create` / `rename` 创建和命名，调用 `resolveAgent(id).agent.followup(createUserMessage(…))` 发送消息，再通过 `session/event` 观察 `tool/call`、`tool/result`、`assistant/message`、`turn/end`。`dsh-schedule` 的提醒也采用这套方式。`approval/request` 顺序处理链支持以 `prepend` 注册优先处理器，因此可以将某次运行的审批转到其他设备，无需修改界面原有处理器。
- 创建会话时未指定工作区，会将其列入侧栏的 *Ungrouped*，并使用 dsh 进程的默认 cwd（当前工作目录）。这足以用于预览，之后应改为明确选择工作区。

## 名称与许可证 {#names-and-licences}

DeepSeek Harness 使用 MIT 许可证。项目将它作为依赖引入，没有把源码复制进来，相关声明随依赖保留。nanoMuse 插件包与项目其余部分一样，采用 GPL-3.0-or-later，因此仍然没有闭源组件。

「DeepSeek Harness」和「DSH」属于 DeepSeek 的名称。项目使用「基于 DeepSeek Harness 构建」的表述，不将它们作为自己的产品名，也保留随软件提供的「关于」文字和品牌素材。原有声明继续适用：Muse 是 Meta 的商标，nanoMuse 是与 Meta 无关联的社区项目。

## 阶段 {#phases}

1. **基础接入**。账号、形象、口吻，以及通过 MCP 提供的手，已在全新安装中验证。*已在内部完成。*
2. **外观与 Reach**。首次引导、账号名字、形象和状态、带停止按钮的胶囊、hub 客户端、`device_*` 工具、转发审批的 `delegate`、设置中的设备列表。*已在内部完成。*
3. **双向 Reach**。桌面版根据远程控制开关应答 `shell`、`files`、`file.get`、`file.put`、`open`、`screen`，每次调用显示提示；「停止」可结束另一台设备上的委派；手机 `delegate` 在桌面 dsh 会话中执行，并将审批发回手机。*已在内部完成。*
4. **窗口界面**。采用手机应用的窄栏和聊天列，固定显示形象、状态及停止按钮，设置分组并将 harness 额外选项放在「高级」，补齐首次引导卡片和主题。*已在内部完成。*
5. **日常使用**。将哨兵类别实现为审批预设，在桌面加入形象工作室，为 dsh 电脑操作接口实现无需 Python 的原生驱动，为其他设备发来的任务选择工作区，使用户能够在其中处理日常文件和网页工作。
6. **发布，分两步完成外壳**。dsh 自带桌面版是同一网页应用的 Electron 封装，`desktop` profile 支持通过 `dsh plugin --profile desktop add …` 加载外部插件。因此，nanoMuse 最初是在这个应用的 profile 中加入插件包。**从 0.1.27 起，每个版本都发布打包后的插件包**，当时名为 `nanoMuse-Harness-<v>.tgz`，0.1.30 起改为 `dsh-nanomuse-<v>.tgz`。安装见 [harness/README.md](../../harness/README.md)。`.github/workflows/harness.yml` 会构建、测试、打包，再将 tar 包安装到全新 dsh profile 中验证。

   **从 0.1.28 起也提供独立外壳**，源码位于 [`harness/desktop/`](../../harness/desktop/)。项目没有重建 dsh 的 `apps/desktop`，因为其流水线还包含私有 Host、主运行时和硬件令牌签名。nanoMuse 使用一个较小的 Electron 应用完成相同的核心任务：利用自己的二进制，以 Node 模式将 harness Host 作为子进程启动，使用 `ELECTRON_RUN_AS_NODE` 和 `--expose-internals`。harness 的 `require-builtin` 原生扩展记录了构建时所用 Electron 的指纹，因此外壳固定使用准确的 Electron 版本。

   构建时，npm 会将 dsh 和插件包安装到 `resources/dsh`。应用使用 `~/.nanomuse/desktop` 下独立的 profile，声明插件包并链接应用内的副本。手的运行时以 PyInstaller 打包，预设通过 `NANOMUSE_PY` 找到它。每个发布标签都会触发 `desktop-app.yml`，构建 Windows 安装程序、两种架构的 macOS dmg/zip，以及 Linux AppImage/deb。流水线会以 Node 模式启动一次各平台打包后的 harness，并检查 Windows 安装程序压缩包中是否包含形象的四段视频。electron-builder 的 NSIS 目标默认将视频从压缩包中排除，再逐个添加回来，但会跳过 `node_modules`，而插件视频恰好放在该目录。因此，`electron-builder.yml` 设置 `nsis.preCompressedFileExtensions: []` 关闭这一行为，并由 `tests/installer.test.mjs` 检查。

   构建产物会附到发布中，配置了相应 Apple 密钥时，macOS 产物还会签名并公证。0.1.28 和 0.1.29 期间，新外壳以 *nanoMuse Harness* 名称与旧桌面版同时发布。**从 0.1.30 起，它成为 nanoMuse 桌面版**，安装包名为 `nanoMuse-Desktop-<v>-…`。它沿用已停用的 `desktop/app` 的应用 id，因此能覆盖安装旧版，网站下载也指向这一版。
7. **完善新外壳的日常体验**。补齐聊天之外的动态、点子、目标、资源库页面，手操作本机屏幕时显示的实时舞台、两个平台的签名、自有更新源、与 harness 桌面版相同的 macOS 关闭到 Dock 和 Windows 托盘行为，并为其他设备发来的任务选择工作区。

围绕 Python 运行时的旧 Electron 外壳 `desktop/app`（0.1.19 至 0.1.29）已移除。它曾有、而 harness 缺少的舞台、托盘和快速唤起功能，会在阶段 7 中通过 dsh 的扩展接口逐步实现。之后提供的终端版（0.1.30 至 0.1.38）已在 0.1.39 移除。桌面应用是唯一的桌面形态，Python 运行时继续用于自己部署和网页控制台。
