# 让所有设备协作 {#每一台设备}

nanoMuse 的第四项设计目标是让同一智能体通过你拥有的所有设备接收请求、执行操作，见[路线图](roadmap.md)。本页说明各设备的 App 界面、本机与远程能力、任务传递过程，以及各部分复用的现有组件。设备互联协议见 [hub.md](hub.md)，这里侧重产品设计和相关代码。

Python 运行时（执行智能体和工具的后台程序）为每次 `device_screen` 截图创建独立文件，即使同一秒内连续截图，也不会互相覆盖。

## 各设备独立运行，使用一致的界面结构 {#one-muse-per-device-one-shape}

每台设备都运行自己的 Muse：手机使用基于 OpenMinis 的智能体，电脑使用 nanoMuse 桌面版及负责「手」的 Python 运行时。「手」是读取屏幕并执行点击、输入等操作的功能。各设备界面结构一致，以 Android 为参照，其他客户端沿用布局和交互方式，不要求像素完全相同：

| 每台设备上都有 | Android 现状 | 电脑（这个阶段） |
|---|---|---|
| 对话顶部一张脸、名称标签、一行状态 | `HomeShell`、`AgentAvatarDisc` | 网页版的聊天头部，默认是小龙 |
| 一个主要聊天，旁聊收在抽屉里 | 抽屉 | 窄窗口用抽屉，宽窗口用侧栏 |
| 动态 · 点子 · 目标 · 资源库 | 悬浮的毛玻璃胶囊栏，只有图标 | 手机宽度下是同一枚胶囊栏（网页版和 iOS 一样），宽窗口和桌面应用里是侧栏 |
| 聊天里的审批卡片（操作前请求你确认），三个层级，「记住」胶囊 | `RiskApprovalCard`、`RiskTier` | 哨兵（Sentinel）的卡片，标签相同 |
| 设置 → 权限：已保存的授权，按层级列出 | `GrantsSection` | 权限页，按层级列出授权 |
| 设置 → Hands：操作本机屏幕，默认关 | `Hands` | 设置 → Hands（这台电脑的屏幕） |
| 设备：账号下的其他设备、在线圆点、「远程控制」、改名、忘记、「交给这台设备」 | `DevicesSection`、`ComputersScreen` | 设备页 |
| 屏幕操作时的提示层：一个圈标出下一次点击的落点，一个胶囊显示当前步骤和「停止」 | `HandsStage`、胶囊 | 聊天里一张实时的「手」卡片；窗口再加一层悬浮 |
| 第一次打开：它是什么，用手机号或邮箱登录（免费）或用自己的 key，Hands 的权限，见面 | `FirstRunSetup` | 同样的四页 |
| 使用自己的视频作为形象：MP4 或 MOV，最长 15 秒、最大 30 MB，H.264 视频每台设备都收，HEVC 只在设备能播时才收（先验证能否播放）；不转换视频编码，拒绝时说明限制，视频留在那台设备上 | `OwnClip.kt`（目前只收 H.264） | `own-clip.ts` 和预览：电脑解不了的 HEVC 视频在预览处被拒绝 |

各设备还可在形象工作室，为待命、干活中、等你回复、搞定、出了点问题五种状态分别设置本地视频。每项均可不设：缺少专属视频时先沿用通用视频，没有通用视频再使用内置或工作室动画。各视频遵守相同格式、时长和大小限制。删除一种状态的视频不影响其他状态。视频及预览图都不通过 nanoMuse Cloud 同步。

## 两个角色 {#two-roles}

每台设备同时承担以下两项职责。

**在本机独立完成任务**。 各平台采用相同的工具优先顺序，见 [gui.md](gui.md)：先用技能、CLI（命令行工具）或 MCP 服务器（通过通用协议提供工具的服务）；再尝试带登录状态的网页抓取；然后使用浏览器；最后才在你允许后操作本机屏幕，按「截图、决定一个动作、执行、再截图」循环。手机的 shell（执行终端命令的环境）位于 App 的 Linux 沙箱中，屏幕操作由「手」完成。电脑使用系统 shell，并在运行时支持的位置加沙箱；浏览器使用 Playwright 或系统浏览器；屏幕工具为 `computer_screen`、`computer_act`、`computer_task`，沿用手机操作器的循环。点击风险根据目标文字 `label` 判断，与手机点按相同。支付、转账、发送、删除等文字会触发最高级别审批，长期授权不能免除该确认。

**为其他设备执行操作、接收任务**。 同一账号的设备通过 hub（设备互联）连接。各设备将可执行能力声明为 `shell`、`files`、`file.get`、`file.put`、`open`、`screen`、`notify`，也能用 `task` 接收完整任务。其他设备的智能体通过 `devices`、`device_shell`、`device_files`、`device_get`、`device_put`、`device_open`、`device_screen`、`device_notify` 调用这些能力，或用 `delegate` 将文字任务交给目标设备的 Muse。例如「在手机上找到订单号，填入 Mac 的表格」，可以在同一聊天完成：手机用「手」查找，Mac 写入文件，发起请求的人在原聊天中看到两部分进度。

各设备可决定允许哪些远程操作。「远程控制」关闭时，只回答 `info` 设备信息请求，但仍可操作其他设备。开启后，其他设备在此运行命令、读写文件前，本机使用者仍需在屏幕卡片上选择「允许一次」或对该设备「总是允许」。后者会作为长期授权列在「权限」中，可撤销。完整 `task` 则由目标设备自己的哨兵（Sentinel，检查执行风险和授权的组件）处理；`notify` 通知不询问。nanoMuse 桌面版这个开关默认关闭，含义是每台设备都先请求确认；打开后，同账号所有设备无需再确认即可操作。

## 一个任务怎么流转 {#how-a-task-travels}

```
you, on the phone ──"编译一下项目，把日志发我"──▶ phone's Muse
                                                  │ delegate("desk", …)
                                                  ▼  hub: call task
                                         desk's Muse, in a side chat
                                         "From Pixel" that the desk shows live
                                                  │ tool events ─▶ phone (chips)
                                                  │ approval? ──▶ phone (card) ── approve ─▶
                                                  ▼
                                         result {text} ──▶ phone's Muse ──▶ you
```

- **发起设备管理当前对话**。 目标设备的 Muse 在独立对话中执行委托任务。`device_shell` 等直接动作不经过目标设备的模型判断。
- **在发起请求的设备上确认审批**。 目标设备哨兵提出审批，通过 `event {stage:"approval"}` 消息传回，发起设备显示常规卡片，再用 `approve` 返回结果。目标设备旁聊也显示同一卡片，以最先回答为准。你在一台设备上输入给另一台执行的命令，会先在输入设备完成风险判断，再发出；手机使用 ShellGuard，此处使用哨兵评估。
- **目标设备可以查看或接手**。 委托任务在目标设备上是正常旁聊，本机使用者可以看进度、输入补充内容并入当前轮次，或点「停止」。发起设备显示工具步骤标签和最终回答，也可发送 `stop` 结束任务。
- 文件和截图通过 base64 编码装入通信消息，大小受 hub 限制。

## 到哪里都是同样的对话 {#the-same-conversations-everywhere}

0.1.36 起，对话可随账号同步。登录后，设备会把本轮文字上传到中继的同步存储，再获取其他设备的消息，详见 [cloud.md](cloud.md#conversation-sync)。同步在启动、收到 hub 的 `sync` 通知以及每分钟触发一次。早上在手机开始的聊天，可到电脑继续，后续轮次由电脑执行，并把已同步的记录作为历史；回复再同步回其他设备。发给其他设备或替其他设备执行的聊天只留在执行设备。任何地方重命名或删除聊天，其他设备同步修改。此功能只同步文字，文件和图片留在创建它们的设备，其他设备只显示名称与大小。

0.1.37 起，主要聊天在各设备之间对应同一个对话。手机上发送的消息会按时间顺序出现在电脑和网页版主要聊天中，显示为只读气泡，下方标注「来自 Pixel 8」。无论下一轮在哪台设备回答，模型都能读到该消息。其他设备的旁聊下载后，也以同一标题和对话身份显示在本机，可继续聊天；聊天列表不标注来源，气泡标注。用户消息发出即同步，模型回答在整轮结束后同步。登录时会按从旧到新的顺序上传本机全部历史。

在任意设备给 Muse 改名，包括首次对话命名，其他设备下次获取资料时会更新。手机在启动、登录后、收到 hub 的 `profile` 通知、重新回到前台时获取账号名字和形象。后台可能错过 `profile` 通知，因此返回前台时会补查。没有本地自绘形象的手机在改名或修改连接器时，不会上传外观变更，中继会保留账号原形象。只有形象工作室的重置会将形象从所有设备移除。

0.1.38 起默认只同步主要聊天，旁聊留在创建它的设备，也不下载其他设备的旁聊。「数据控制」同步开关下的「同时同步旁聊」按设备设置，默认关闭。开启后，会上传本机旁聊，并从头下载其他设备旁聊一次。首次登录先获取最新 300 条消息，使长历史能立即阅读，无需等待旧消息逐条到达。

其他设备回答时，最后一条消息下会显示「kwai 正在处理…」。中继只转发这种在线状态，不保存；收到回复、完成通知或经过十分钟后清除。1.0.8 起还能显示具体步骤，例如「kwai 正在处理：打开订票网站」，等待审批时显示「kwai 在等你确认」。电脑、手机、网页控制台都上报和显示这些进度，旧版仍只显示简单状态。远端消息不会被标为中断，也不提供「继续」，因为只有实际执行轮次的设备知道结束状态。

设置 → 数据控制 →「在我的设备之间同步对话」默认开启。关闭会删除中继上该账号的同步存储，其他设备的开关也会关闭。「删除已同步的对话」只清空数据，不改变开关。手机和网页版将本地聊天映射到对话 id，直接将其他设备的修改应用到聊天列表。

**桌面版的同步实现**。 dsh 插件将远端轮次按会话保存在 `$DSH_HOME/nanomuse/sync-remote.json`。dsh 会话日志只允许智能体循环追加，在轮次之外写入既不安全也不会显示。`client/RemoteBubbles.ts` 将远端气泡按时间插入本机消息之间；下一步执行前，用 `agent.inject` 将新内容作为上下文备注交给模型。备注不是日志记录，也不会再次上传。下载的旁聊会立即建立 dsh 会话并列入「旁聊」，即使本机尚未执行过轮次。主要聊天使用账号主对话对应的会话，账号已有主对话时，首次引导也在其中进行。即使缓存的对话记录被清空，持久化映射仍能接收最终回复，然后才推进同步游标，避免跳过回答。

harness 不提供删除，日志也不擦除内容：远端删除的消息在本机隐藏，远端删除的聊天在本机归档。0.1.38 起，插件独立保存「同时同步旁聊」设置，默认关闭。关闭时，本机旁聊不进入上传列表，也不读取上传；即使收到旁聊记录也不建立会话。插件向中继请求 `scope=main`，首次获取和开启旁聊同步时先取最新部分。hub 的 `working` 消息将远端状态显示在其最后一条气泡下；中继 0.31 提供 `state`、`detail` 时，显示步骤或等待确认。收到回答、`working: false` 或十分钟后清除。远端记录不写入会话日志，所以 harness 不会把它误判为未完成轮次。Host 在会话变化时只读一次日志，将标题、消息行和提示位置缓存到下一个会话事件，并将密集 `sync` 通知合并为每秒一次获取，避免大账号空闲时反复占用聊天资源。

代码位置：运行时 [`nanomuse/sync/`](../../nanomuse/sync/) 的 `ConversationSync`，接口 `/api/sync/*` 见 [app.md](app.md#api)；网页的 `SyncControls` 及 `web/src/` 消息来源说明；插件的 `src/sync.ts`、`client/RemoteBubbles.ts`、`tests/sync.test.mjs`；中继的 [`cloud/nanomuse_cloud/sync.py`](../../cloud/nanomuse_cloud/sync.py)。

**将任务发给其他设备**。 默认任务在当前输入设备执行。单条消息要交给其他设备时，以 `@` 加 hub 列表中的名字开头，例如 `@Desk compile the project and send me the log`，支持不分大小写的前缀匹配。输入框会提示设备名，发送时删除正文中的提及，气泡显示「发给 Desk」。本轮前会加入备注，要求本机智能体通过 `delegate`，手机上通过 `nanomuse-pc task … --on`，交给目标设备并报告结果。「设备」页的「交给这台设备」相同。iPhone 没有 delegate 工具，因此提及会直接通过 hub 的 `task` 发送，回答作为聊天一轮显示，且只匹配在线设备。电脑，包括桌面版和运行时，只要在线便可作为目标，其 hub 连接持续保持；Android、iPhone 只在 App 打开时可接收，因为连接位于 App 内，不在后台保持。网页和桌面版仍允许选择离线目标，但会返回 `device_offline`。网页控制台不能作为执行目标。替其他设备执行的会话只存于执行设备，不同步。

## 一台设备显示谁的对话 {#whose-conversations-a-device-shows}

共用平板、工作电脑、转交他人的手机都可能切换账号。0.1.39 起，设备会记录对话属于哪个账号：以首次上传到中继或首次从中继下载时登录的账号为准。手机、电脑、桌面版和网页控制台按以下规则处理：

- **登录 B 时，只显示 B 和未归属账号的对话**。 后者是设备上尚无人登录、在未登录状态创建的聊天。A 的聊天不列出。
- **A 的聊天只隐藏，不删除**。 文件、图片也保留，重新登录 A 立即恢复显示。单纯退出登录不会隐藏内容，手动删除聊天仍会删除。
- **不同账号不互传数据**。 A 的对话不上传到 B，B 的对话不写入 A；同步及代其他设备执行任务均遵循此规则。
- **切换账号时重置当前同步状态**。 设备清除另一账号当前同步进度、缓存的远端气泡及在线提示，重新读取新账号设备列表。下一次先获取最新 300 条，与首次登录相同。切回 A 时，恢复 A 的聊天和同步位置。
- **归属分类在本机完成**。 中继一直将账号存储隔离，不参与本机分类，旧版中继也适用。

Muse 的名字、形象仍跟随账号。0.1.40 的约定 C12 为手机增加了更完整的隔离：每个聊天都分配归属，包括从未同步的聊天；退出时会移除该账号的聊天、记忆、动态、目标、例程和形象，除非开启「把这个账号的聊天留在这台设备上」。删除账号会全部清除；中继拒绝 key 时则先单独保存，等待原账号重新登录。完整数据表见 [sync.md](sync.md)。桌面版和网页控制台仍按上述 0.1.39 规则处理，记忆文件按设备保存。实现见运行时 `nanomuse/sync/engine.py`、`nanomuse/server/api.py` 的会话列表，桌面版 `harness/dsh-nanomuse/src/{sync,cloud}.ts`，Android `io.github.nanomuse.sync.*`，iPhone `NanoMuse/NanoMuseSync.swift`。

## 电脑：nanoMuse 桌面版 {#the-computer-nanomuse-desktop}

这部分桌面设计以 `nanomuse serve` 的 Python 运行时为共同本地服务，提供终端 `nanomuse chat`、浏览器网页以及桌面窗口三个入口。同一局域网中的手机也可打开网页。OpenCode v2 和 Codex 同样采用本地服务上接命令行与桌面应用的结构，nanoMuse 运行时本来就支持此结构，本阶段加入 hub、Cloud 账号和屏幕操作。

```
   nanomuse serve  ─ FastAPI + WebSocket, 127.0.0.1:8787 ─┬─ web/ (React) in a browser or on the phone
      │ MuseAgent · Sentinel · tools                        ├─ nanomuse mcp → nanoMuse Desktop (harness/, on DeepSeek Harness)
      │ nanomuse/hub  ── wss://…/v1/hub ── the other devices └─ nanomuse chat (terminal)
      │ nanomuse/computer ── mss + pyautogui: the screen as a hand
      └ nanomuse/cloud ── the nanoMuse Cloud account (e-mail code → key → models + hub)
```

- **运行时**（`nanomuse/`）：`cloud.py` 用邮箱或手机验证码登录 Cloud，将 key 存入保险库，也可让中继提供模型，手机的「登录，免费开始」使用相同方式。`hub/` 将旧桌面二进制 hub 客户端改为异步实现，保持单条连接；`hub/actions.py` 响应远程动作，收到 `task` 后在可见旁聊执行并转发审批，`device_*`、`delegate` 工具负责发出调用。`computer/` 负责本机屏幕操作。`[cloud]`、`[hub]`、`[hands]` 都可在 App 设置中切换。
- **网页版**（`web/`）：提供设备页、指定设备的旁聊、分级审批卡片及记住授权按钮、带「停止」的手卡片、设置 →「手」、首次引导及「连接」中的 Cloud 登录，默认形象为小龙。构建产物位于 `nanomuse/server/static/`。
- **桌面窗口**：0.1.30 起使用基于 DeepSeek Harness（`harness/`）的 [nanoMuse 桌面版](desktop.md)，将 Host 和网页放入项目的 Electron 外壳，账号、形象、Hands、Reach 以插件提供，另捆绑运行时给「手」使用，通过标准输入输出 stdio 运行 `nanomuse mcp`。0.1.19–0.1.29 的 `desktop/app` 外壳已停用。其托盘、点击位置透明提示层、全局停止、快速唤起、开机启动等能力会在 harness 接口中重新实现，见 [harness.md](harness.md) 第 7 阶段。直接在浏览器打开 `nanomuse serve` 时，宽窗口仍使用 Muse 布局。
- **标准库二进制**（`desktop/nanomuse_desktop`）：原先供未安装 Python 的机器免安装运行，也是 `nanomuse/hub` 的来源。桌面版自带运行时后，它于 0.1.39 移除。

### 这台电脑上的手 {#hands-on-this-computer}

`computer_task` 将手机操作器的流程用于电脑：查看截图，决定一个动作，经哨兵检查后执行，再截图。汇报方式和「停止」相同，区别在动作格式和设备实现：

- **动作格式**。 使用 Qwen `computer_use`：`left_click`、`double_click`、`right_click`、`left_click_drag`、`mouse_move`、`scroll`、`type`、`key`、`wait`，另有按应用名打开的 `open`，以及 `answer`、`ask_user`、`terminate`。坐标沿用手机的 0–999 网格，视觉模型可跨两端使用。回复格式 Thought / Action / 一个 `<tool_call>` 及解析器也与手机相同。
- **截图与输入**。 各平台通过 `mss` 截图，并按模型要求缩放。通过 `pyautogui` 执行输入，安装命令为 `pip install "nanomuse[hands]"`。Linux 无 pyautogui 但有 `xdotool` 时使用后者。活动窗口标题由 `xdotool` / `osascript` / `GetForegroundWindow` 获取，使卡片、日志明确写出「在 Firefox 里」等应用名。
- **系统权限**。 macOS 首次需授予「录屏」和「辅助功能」，设置 →「手」会说明并打开系统面板。桌面版权限授予辅助程序「nanoMuse Computer Use」，见 [desktop.md](desktop.md#macos-permissions)；独立运行时的权限则归启动它的程序，例如终端。Linux 必须使用 X11，Wayland 尚无可移植的指针控制方式，页面会说明。Windows 无需额外权限。
- **应用授权**。 每段对话首次操作某应用时，会询问如「让 Nova 使用 Safari 吗？」，可允许一次、本次对话或总是。授权记录为 `computer_app:<bundle id or name>`，可在 设置 → 权限 查看、撤销。`[sentinel] mode = "auto"` 与其他询问一样，会跳过此确认。
- **敏感信息由你输入**。 手不输入密码、PIN、卡号或验证码。操作器会显示「轮到你了」并解释原因，你输入后点「完成」，操作器再查看屏幕继续。

#### 窗口模式（macOS） {#window-mode-macos}

Mac 支持只操作一个应用窗口，而非整个屏幕。通过 `[hands] mode` 或手卡片的「范围」选择「自动」「单个窗口」「整个屏幕」，实现位于 `nanomuse/computer/mac_window.py`：

- **只截目标窗口**。 macOS 14 及以上由桌面辅助程序「nanoMuse Computer Use」用 ScreenCaptureKit 截图，操作器接口为 `POST /window`，见 [gui.md](gui.md#hands-on-the-computer-the-picture-is-the-unit)。没有辅助程序时，运行时用 `CGWindowListCreateImage` 截图。图像按模型需求缩放，动作坐标以该截图像素为单位，再映射到屏幕上的窗口位置。
- **将输入发给目标应用**。 点击、拖动、滚动和按键通过 `CGEventPostToPid` 发往应用进程，不移动系统光标，你可以同时在其他窗口工作。文字使用 Unicode 键盘事件，支持中文和 emoji。获得辅助功能授权后，可通过界面控件树的 `AXPress` 激活坐标处按钮，替代模拟点击。
- **指定应用**。 可用 `computer_act` → `computer_target` 的 `app` 指定菜单栏应用名或 bundle id，也可在任何动作中传 `app`。`open_app` 将打开的应用设为目标。「自动」在已指定应用时使用窗口模式，未指定前使用整个屏幕。

手卡片会显示「正在 Safari 的窗口里操作；鼠标仍归你用」。透明提示层在实际点击处绘制指针，事件中的 `x`/`y` 是屏幕像素，审批卡片也会写明应用名。找不到窗口、无法截图或无法操作时，会退回整个屏幕，并在观察结果中说明，任务继续。截图失败也可能是辅助程序未获「录屏」权限，操作器会返回带原因的 `403`。如果整个窗口控制层不可用，例如缺少辅助程序、pyobjc 或窗口服务器故障，「自动」会在当前目标余下步骤使用全屏，只提示一次；换到下一个应用时再尝试窗口模式。「单个窗口」则持续按选择尝试。两者都会在「范围」显示原因。Linux、Windows 仍使用共享屏幕。`pip install "nanomuse[hands]"` 仅在 macOS 安装 pyobjc 框架。

## 手机 {#the-phone}

从 0.1.12/0.1.13/0.1.17 起，手机已同时具备本机和远程职责：本地有沙箱 shell 与「手」，向外通过 `nanomuse-pc`、hub 发请求，向内通过无界面聊天执行器接收 `task`。本阶段 Android 按顺序处理 hub `approve` 接入 RiskGate、在抽屉增加「设备」入口，以及实时显示电脑的手操作事件。前两项在 0.1.19 完成，见[手机在 0.1.19 的进展](#the-phone-in-0-1-19)。这些工作不阻塞桌面开发。

## 浏览器：一台模拟手机上的演示 {#the-browser-a-demo-on-a-simulated-phone}

[nanomuse.cn/web](https://nanomuse.cn/web/) 打开展示站，在浏览器内显示 MobileGym 模拟手机，前台为 `demo/mobilegym/apps/nanoMuse`。展示网关为每次访问启动独立的 nanoMuse，使用 `ghcr.io/nano-muse/nanomuse` 镜像，网络出口仅限网关，调用展示站模型，访问结束后移除。访客先通过手机或邮箱验证码、或账号密码登录 nanoMuse Cloud，代码位于 `demo/showcase/gateway/showcase_gateway/visitors.py`，使项目知道谁在体验，之后安装 App 仍可沿用该账号。页面会明确说明这是演示，与 Android App 差距较大，并给出 App 下载入口。首页 [nanomuse.cn](https://nanomuse.cn/) 通过框架嵌入同一页面，使用 `?embed=1`，不显示独立页头。模拟手机自动开机；只有页面已完成要求的登录，且检测到可能有人使用，例如进入可见区域数秒、指针、键盘或滚轮动作，才启动后台 Muse。自动化浏览器不会触发。

展示网关仍保留早期网页模式：每个 Cloud 账号有常驻 Muse、命名存储卷，并像普通设备一样接入 hub，对应 `accounts.py` 和 `WEB_ENABLED=1`。自行部署者仍可使用，项目服务器从 0.1.26 起已关闭。配置和细节见 [demo/showcase/README.md](../../demo/showcase/README.md)。

## iOS、网页控制台、眼镜 {#ios-the-web-console-glasses}

iOS 支持 hub 的 `info`、`open`、`notify`、`task`，从 0.1.34 起采用相同界面结构，见 [ios.md](ios.md)。Cloud 网页控制台 `/app/` 只提供请求入口，本身不执行设备操作，这一定位保持不变。眼镜可只负责语音或文字请求及回答，操作由其他设备完成，现有 hub 已能支持这类连接。

## 复用了什么，从哪里来 {#what-is-reused-and-from-where}

- **UI-TARS-desktop**（Apache-2.0）：借鉴输入截图、解析动作、各设备独立 `execute` 的操作器模式，以及操作时的屏幕标记。不使用其 Electron App 或模型；它使用 UI-TARS 动作格式，本项目使用 Qwen `mobile_use` / `computer_use`。
- **OpenCode v2**（MIT）：借鉴 Electron 外壳启动本地服务、显示网页的桌面结构，包括 electron-vite、electron-builder、托盘及后续深链接。不使用它围绕项目目录工作的编程智能体，nanoMuse 围绕用户提供个人智能体服务。
- **Codex**（Apache-2.0）：借鉴命令行与其他入口共用智能体、终端审批、命令沙箱。`nanomuse chat` 和哨兵已采用这类结构。
- **Qwen-Agent / MemGUI-Bench**（MIT）：复用 `mobile_use`、`computer_use` 动作格式及回复解析器，代码已位于 `nanomuse/phone/operator.py`。
- **pyautogui、mss、xdotool**：负责鼠标、键盘和截图，不另写输入库。

## 现状 {#status}

| | 手机 | 电脑 | nanoMuse Web（`WEB_ENABLED=1`；0.1.26 起是演示手机） | 网页控制台 | iOS |
|---|---|---|---|---|---|
| 本地 shell / 文件 / 浏览器 | 有 | 有（运行时） | 有，在它的容器里 | 不执行本机操作 | 无 |
| 操作本机屏幕 | 「手」（0.1.12） | `computer_*`（0.1.19） | — | — | — |
| 调用其他设备 | `nanomuse-pc`、hub | `device_*`、`delegate`（0.1.19） | 同一个运行时 | 挑一台设备，发一个任务 | — |
| 回应其他设备 | 会 | 在一个看得见的旁聊里（0.1.19） | 会 | — | info / open / notify / task |
| 与 Android 一致的界面结构 | 参照 | 网页版（宽屏用侧栏）+ 窗口（0.1.19） | 网页版 | 控制台 | 0.1.34 起 |
| 屏幕操作时的提示层 | `HandsStage` | 「手」卡片；窗口里的舞台悬浮层 | — | — | — |

0.1.19 发布时提供 APK、桌面安装包 `nanoMuse-Desktop-…`，构建见 [`.github/workflows/desktop-app.yml`](../../.github/workflows/desktop-app.yml)，也提供终端二进制及 nanomuse.cn/web 的 nanoMuse Web。终端二进制在 0.1.39 移除；网页从 0.1.26 起改为模拟手机演示。

## 在一台机器上调试整套东西 {#debugging-it-all-on-one-machine}

在 `127.0.0.1` 上启动两个运行时和一个中继，即可测试任务从一台设备发往另一台并返回的全过程，不需要真实账号、邮件服务商或手机。

```bash
# 1. the relay, in dev mode: no CLOUD_SECRET, codes go to the log; sign-up and the
#    hub are on by default. Without UPSTREAM_KEY the proxy answers 503 while sign-up
#    and the hub still work; give the relay a real key (from the environment, never
#    on the command line) if you want the Cloud model to answer.
mkdir -p /tmp/nm-dev/cloud
CLOUD_DB=/tmp/nm-dev/cloud/cloud.db CODE_SENDER=log PUBLIC_BASE=http://127.0.0.1:8790 \
  PYTHONPATH=cloud .venv/bin/python -m nanomuse_cloud --host 127.0.0.1 --port 8790 \
  > /tmp/nm-dev/cloud/relay.log 2>&1 &

# 2. two runtimes, each with its own data dir, workspace and port
for d in a b; do
  mkdir -p /tmp/nm-dev/$d/home /tmp/nm-dev/$d/ws
  printf 'data_dir = "/tmp/nm-dev/%s/home"\nworkspace = "/tmp/nm-dev/%s/ws"\n\n[llm]\napi_key = ""\n\n[cloud]\nbase_url = "http://127.0.0.1:8790"\n\n[hub]\nname = "%s"\n' \
    $d $d "$([ $d = a ] && echo 'Desk A' || echo 'Laptop B')" > /tmp/nm-dev/$d/config.toml
done
# ambient provider keys would be picked up as the model; clear them for a clean first run
env -u OPENAI_API_KEY -u DASHSCOPE_API_KEY -u ANTHROPIC_API_KEY -u OPENAI_BASE_URL \
  .venv/bin/nanomuse serve -c /tmp/nm-dev/a/config.toml --no-auth --no-qr --port 8799 > /tmp/nm-dev/a/serve.log 2>&1 &
env -u OPENAI_API_KEY -u DASHSCOPE_API_KEY -u ANTHROPIC_API_KEY -u OPENAI_BASE_URL \
  .venv/bin/nanomuse serve -c /tmp/nm-dev/b/config.toml --no-auth --no-qr --port 8798 > /tmp/nm-dev/b/serve.log 2>&1 &

# 3. sign both in with the same e-mail in the first run (the code is in relay.log:
#    grep -i code /tmp/nm-dev/cloud/relay.log), pick "Use the Cloud model" on each.
# 4. (0.1.19–0.1.29) the Electron window over Desk A came from desktop/app; now open
#    http://127.0.0.1:8799/ in a browser, or sign nanoMuse Desktop in as a third device.
```

启动后，Desk A 的「设备」中应显示 Laptop B 在线。点「去问它」或聊天下方的设备标签，打开目标为 Laptop B 的聊天。输入任务后由 B 执行，A 会显示带设备标签的工具步骤和审批卡片。在 A 确认审批后，两端卡片都会关闭，B 的回答出现在 A 聊天中。交换端口可测试反方向。结束时用 `ss -ltnp | grep ':879'` 查找进程，再用 `kill` 停止。

## 手机，在 0.1.19 {#the-phone-in-0-1-19}

Android 从 0.1.19 起对应实现了三项电脑能力：hub 客户端由 `ReachOffloadHandler` 处理 `tool` / `tool_result` / `approval_result` 阶段；`HubActions` 将 hub `approve` 传给 `RiskGate`，并把手机审批作为 `approval` 事件传回发起设备；聊天抽屉旁新增「设备」入口。仍待完成的是：手机发起任务后，将电脑的手操作事件 `HandsLive` 显示为手机中的手卡片。