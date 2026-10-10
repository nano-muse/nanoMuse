# 每一台设备

定义 nanoMuse 的第四件事（[路线图](roadmap.md)）：一个智能体，而你拥有的每一台设备都是它的一双手、一扇门。这一页是这个阶段的设计：每台设备上的 App 长什么样，每一台自己能做什么、能替其他设备做什么，一个任务怎么流转，各部分分别由哪些现成的东西拼起来。协议本身在 [hub.md](hub.md)；这一页讲的是产品的形状，以及围绕它的代码。

## 每台设备一个 Muse，同一个形状 {#one-muse-per-device-one-shape}

每台设备跑着自己的 Muse（手机上是基于 OpenMinis 的智能体，电脑上是带着手的 Python 运行时的 nanoMuse 桌面版），而每一台显示的都是同一个 App。Android 版是参照；其他版本跟的是它的形状，不是它的像素：

| 每台设备上都有 | Android 现状 | 电脑（这个阶段） |
|---|---|---|
| 对话顶部一张脸、一个名字胶囊、一行状态 | `HomeShell`、`AgentAvatarDisc` | 网页版的聊天头部，默认是小龙 |
| 一个主要聊天，旁聊收在抽屉里 | 抽屉 | 窄窗口用抽屉，宽窗口用侧栏 |
| 动态 · 点子 · 目标 · 资源库 | 底栏 | 底栏 / 侧栏 |
| 聊天里的审批卡片，三个层级，「记住」胶囊 | `RiskApprovalCard`、`RiskTier` | 哨兵（Sentinel）的卡片，标签相同 |
| 设置 → 权限：记住了什么，按层级列出 | `GrantsSection` | 权限页，按层级列出授权 |
| 设置 → Hands：把屏幕当手，默认关 | `Hands` | 设置 → Hands（这台电脑的屏幕） |
| 设备：账号下的其他设备、在线圆点、「远程控制」、改名、忘记、「交给这台设备」 | `DevicesSection`、`ComputersScreen` | 设备页 |
| 手干活时的舞台：一个圈标出下一次点击的落点，一个胶囊显示当前步骤和「停止」 | `HandsStage`、胶囊 | 聊天里一张实时的「手」卡片；窗口再加一层悬浮 |
| 第一次打开：它是什么，用手机号或邮箱登录（免费）或用自己的 key，Hands 的权限，见面 | `FirstRunSetup` | 同样的四页 |

## 两个角色 {#two-roles}

每台设备同时扮演这两个角色。

**它自己就是一个智能体。** 它在每台设备上爬的都是同一道阶梯（[gui.md](gui.md)）：先是技能、CLI 或 MCP 服务器；再是用你的登录态抓一个网页；然后是浏览器；最后（在你允许的前提下）才是这台设备自己的屏幕：看一张截图，决定一个动作，做掉，再看。在手机上，shell 是 App 的 Linux 沙箱，屏幕就是「手」。在电脑上，shell 是真正的 shell（运行时能加沙箱的地方就加沙箱），浏览器是 Playwright 或系统浏览器，屏幕是「这台电脑上的手」：`computer_screen`、`computer_act`、`computer_task`，手机操作器的那套循环，底下换成一台电脑。一次点击按光标下方的文字（`label`）来评估，和一次点按完全一样；同样的那些词（支付、转账、发送、删除……）会让它成为最高层级的审批，任何长期授权都盖不住。

**替其他设备当手、当门。** 登录同一个账号后，设备们在 hub（设备互联）上相遇，每一台把自己能做的事暴露为动作（`shell`、`files`、`file.get`、`file.put`、`open`、`screen`、`notify`），也可以作为整个任务的目标（`task`）。任何一台设备的智能体都把其他设备当工具用：`devices`、`device_shell`、`device_files`、`device_get`、`device_put`、`device_open`、`device_screen`、`device_notify`，还有 `delegate`，用一句话把活交给另一台设备的 Muse。所以「在我手机上找到订单号，填进我 Mac 上的表格」是一场对话就能做完的事：手机的 Muse 用「手」找到它，Mac 的 Muse 把它填进文件，而提问的人在自己打字的那个聊天里看到两头。

一台设备自己决定让其他设备做什么：「远程控制」关着时，它只回答 `info`，别的都不答，但它自己照样能驱动其他设备。开着时，*在*这台设备跟前的人仍然要先同意，另一台设备才能在这里运行、读或写东西：那块屏幕上弹一张卡片，「允许一次」或「对这台设备总是允许」（一条长期授权，和其他授权一样列在「权限」下，可以在那里撤销）。`task` 则由这台设备自己的哨兵把关；`notify` 从不询问。在 nanoMuse 桌面版上，这个开关默认关，意思是「每台设备都要在这里问一下」；打开后，账号下的每台设备都直接通过，不再问。

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

- **提问设备的大脑**跑这场对话；目标设备的 Muse 在它自己的一场对话里跑被委托的活。原始动作（`device_shell`……）完全绕开目标设备的大脑。
- **审批在提问的地方回答**：目标设备的哨兵弹出卡片，`event {stage:"approval"}` 帧把它带回来，提问方显示自己惯常的那张卡片，`approve` 把答案送回去。目标设备在自己的旁聊里也显示同一张卡片；谁先回答算谁的。在一台设备上替另一台打的命令，离开之前先在打字的这台设备上判定（手机上是 ShellGuard，这里是哨兵的评估）。
- **旁观和接手**：被委托的对话是目标设备上一场真正的旁聊，所以在那台设备跟前的人看得到它在跑，可以往里打字（并入正在进行的回合），也可以按「停止」。提问方看到工具标签和最终答案；提问方发 `stop` 也能结束它。
- 文件和截图以 base64 装在帧里传；大小限制是 hub 的。

## 到哪里都是同样的对话 {#the-same-conversations-everywhere}

从 0.1.36 起，聊天本身跟着账号走。登录后，每台设备把自己回合的文字发到中继的同步存储（[cloud.md](cloud.md#conversation-sync)），再拉回其他设备发上来的（启动时、hub 说 `sync` 时、以及每分钟一次），这样早上在手机上开始的一场聊天，到了书桌前就在电脑上，在那里接着聊，回合就在*那台*设备上跑，以同步来的记录作为历史；它回答的内容再沿同一条路回去。发给某台设备的聊天，或者在这台设备上替另一台跑的聊天，留在原地。在任何地方重命名或删除一场聊天，各处都跟着改名或删除。只同步文字：文件和图片留在产生它们的设备上，同步过来的消息只显示它们的名字和大小。

从 0.1.37 起是**一条线程**。主要聊天是跨所有设备的同一场对话：你在手机上对 Muse 说的话，会出现在电脑和网页版的主要聊天里，按时间顺序排在那边说过的话中间，是一个只读气泡，下面标着「来自 Pixel 8」；而 Muse 无论接下来在哪里回答，都已经读过它。另一台设备的旁聊从被拉取的那一刻起就是这台设备上的一场聊天，带着标题，在这里以同一场对话继续；聊天列表里不会标明一场聊天是在哪里写的，气泡会。人的消息一发出就到了其他设备上，回复在回合结束时到；登录会把这台设备的全部历史发上去，最早的在前。在任何地方给 Muse 改名（包括第一场对话里的起名），下次拉取时名字就跟过来。

从 0.1.38 起是**主要聊天优先**。除非设备另外要求，否则只有主要对话在设备间流动：旁聊留在创建它的设备上，别的设备的旁聊也不会过来。「数据控制」里同步开关下面的「同时同步旁聊」按设备设置，默认关。*关：旁聊只留在这台设备。开：这台设备的旁聊进入账号，其他设备的旁聊到这里来。*打开它会把这台设备的旁聊发上去，并从头把其他设备的拉下来一次。新登录先拉最新的 300 条消息，这样很长的历史一下子就能读，而不是从最早的开始慢慢到。另一台设备正在回答时，聊天最后一条消息下面显示「kwai 正在处理…」，一条在场提示，中继只转发、从不存储；回复到了、设备说做完了、或者过了十分钟，它就消失。从另一台设备来的消息永远不会显示为被打断，也永远不提供「继续」：只有跑那个回合的设备知道它是怎么结束的。

开关在「设置 → 数据控制 → 在我的设备之间同步对话」，默认开；关掉会让中继删除这个账号的存储，其他每台设备的开关也跟着关。「删除已同步的对话」清空存储，但保留开关。手机和网页版把每一场本地聊天映射到一个对话 id，把其他设备的改动直接套进自己的聊天列表。**nanoMuse 桌面版（dsh 插件）**把另一台设备的回合放在自己的存储里（`$DSH_HOME/nanomuse/sync-remote.json`，按会话；dsh 的会话日志只能追加，归它的智能体循环所有，在回合之外写进去的一行既不会显示也不安全），在浏览器里显示为另一台设备的气泡（`client/RemoteBubbles.ts`），按时间排在这里打的回合之间，并在模型下一步之前把到达的内容作为一条备注交给它（`agent.inject`；这条备注只是上下文，不是一行记录，也永远不会被推回去）。从中继拉下来的旁聊会立刻得到自己的 dsh 会话（列在「旁聊」里，尽管这里还没跑过回合）；主要聊天就是账号的主要对话所在的那个会话，账号已经有主要对话时，第一场对话就在它里面开始。harness 没有删除功能，日志什么都不忘：在别处删掉的消息在这里隐藏，在别处删掉的聊天在这里归档。从 0.1.38 起，插件自己保存「同时同步旁聊」的状态（默认关；关着时，这里的旁聊既不列出也不读来推送，仍然到达的旁聊行也不会生成会话），向中继请求 `scope=main`，并在第一次拉取和旁聊开关打开时请求尾部；另一台设备的「kwai 正在处理…」那一行，根据 hub 的 `working` 帧画在它最后一个气泡下面，由它的回复、`working: false` 或十分钟后清掉；远端的行从不进会话日志，所以 harness 不会把它误当成一个没结束的回合。宿主每次变化只读一遍会话日志（标题、行和提示位置一直保留到该会话的下一个事件），并把一连串 `sync` 帧合并成每秒一次拉取，所以一个大账号在空闲时对聊天没有任何开销。代码：运行时的 [`nanomuse/sync/`](../../nanomuse/sync/)（`ConversationSync`，`/api/sync/*` 见 [app.md](app.md#api)），网页版的 `SyncControls` 和 `web/src/` 里的消息说明文字，插件的 `src/sync.ts`、`client/RemoteBubbles.ts` 和 `tests/sync.test.mjs`，中继的 [`cloud/nanomuse_cloud/sync.py`](../../cloud/nanomuse_cloud/sync.py)。

**在另一台设备上干活。** 默认永远是你正在打字的这台设备。想把某一条消息发去别处，就以 `@` 加上 hub 列出的设备名开头（`@Desk compile the project and send me the log`），前缀匹配，不分大小写；输入框会在你打字时提示这些名字，提及词从正文里摘掉，气泡上写「发给 Desk」，回合前面加一行备注，告诉这台设备的智能体用 `delegate`（手机上是 `nanomuse-pc task … --on`）把它交给那台设备，并汇报它做了什么；设备页上的「交给这台设备」做的是同一件事。iPhone 没有 delegate 工具，提及词直接发到 hub（给那台设备发 `task`，它的答复作为聊天里的一个回合显示），而且只匹配在线的设备。哪些设备可以作为目标：**电脑**（nanoMuse 桌面版、运行时）只要在线就行，因为它们的 hub 连接一直保持着；**手机**（Android 和 iPhone）只在 nanoMuse App 打开时可以，因为连接活在 App 里，两个平台都不在后台保持它。不在线的设备在网页版和桌面版上照样作为目标提供，回答 `device_offline`；网页控制台永远不是目标。一台设备替另一台跑的会话保存在那台设备上，不同步。

## 一台设备显示谁的对话 {#whose-conversations-a-device-shows}

一台设备今天可以登录一个账号，明天换另一个：家里共用的平板，装了个人账号的工作笔记本，转手的手机。从 0.1.39 起，设备上的每一场对话都记得它是**谁的**：第一次上传到中继或第一次从中继到达时登录着的那个账号。于是手机、电脑、桌面版和网页控制台上的规则是一样的：

- **以 B 登录，就看到 B 的对话**，以及不属于任何人的那些：在登出状态下、这台设备上还没有任何人登录过时创建的聊天。A 的聊天不在列表里。
- **A 的聊天是隐藏，不是删除。** 它们连同文件和图片留在设备上，A 再登录的那一刻就回来。单纯退出登录什么都不隐藏；删除一场聊天仍然是删除。
- **账号之间什么都不互通。** A 的对话永远不会上传到 B 的账号，B 的对话也永远不会落进 A 的：同步不会，在这台设备上替账号的另一台设备跑的回合也不会。
- **换一个账号就从头开始。** 登录的账号变了，设备就忘记自己在另一个账号的同步里走到了哪（下次拉取是最新的 300 行，和第一次登录一样），清掉保存的其他设备的气泡和在场提示，重新读取新账号的设备列表。切回 A，就接上 A 的聊天和 A 在同步里的位置。
- **中继不参与。** 它像一直以来那样把每个账号的存储分开；归类在设备上做，所以旧版中继的行为也一样。

Muse 的名字和外观照旧跟着账号走。从 0.1.40 起，手机走得更远（约定 C12）：每一场聊天都有主人（从没同步过的聊天也算），退出登录会把账号的聊天、记忆、动态、目标、例程和形象从手机上拿走，除非打开了「把这个账号的聊天留在这台设备上」；删除账号会移除全部；被中继拒绝的 key 会把这些东西放到一边，等账号回来。每一项状态的表格在 [sync.md](sync.md)。在桌面版和网页控制台上，上面 0.1.39 的规则仍然有效，记忆文件按设备存放。代码：运行时的 `nanomuse/sync/engine.py` 和 `nanomuse/server/api.py` 里的会话列表，桌面版的 `harness/dsh-nanomuse/src/{sync,cloud}.ts`，Android 的 `io.github.nanomuse.sync.*`，iPhone 的 `NanoMuse/NanoMuseSync.swift`。

## 电脑：nanoMuse 桌面版 {#the-computer-nanomuse-desktop}

桌面端就是 Python 运行时（`nanomuse serve`），在同一个本地服务上开了三扇门：终端（`nanomuse chat`）、浏览器（它托管的网页版，同一网络下的手机也能打开）和一个窗口。这是 OpenCode v2 和 Codex 采用的形状（一个本地服务，上面架一个 CLI 和一个桌面 App），也是运行时本来就有的样子；这个阶段给它加上 hub、Cloud 账号和手。

```
   nanomuse serve  ─ FastAPI + WebSocket, 127.0.0.1:8787 ─┬─ web/ (React) in a browser or on the phone
      │ MuseAgent · Sentinel · tools                        ├─ nanomuse mcp → nanoMuse Desktop (harness/, on DeepSeek Harness)
      │ nanomuse/hub  ── wss://…/v1/hub ── the other devices └─ nanomuse chat (terminal)
      │ nanomuse/computer ── mss + pyautogui: the screen as a hand
      └ nanomuse/cloud ── the nanoMuse Cloud account (e-mail code → key → models + hub)
```

- **运行时**（`nanomuse/`）：`cloud.py` 用邮箱（或手机）验证码登录 nanoMuse Cloud，把 key 存进保险库，并且可以让中继当模型服务商，和手机上一样的「登录（免费）」第一步。`hub/` 是桌面二进制里 hub 客户端的异步移植：保持一条连接，收到的动作由 `hub/actions.py` 回答，收到的 `task` 在一个看得见的旁聊里跑、审批转发出去，发出的调用藏在 `device_*` 和 `delegate` 工具后面。`computer/` 是这台机器上把屏幕当手的那部分。设置项：`[cloud]`、`[hub]`、`[hands]`；全都可以在 App 里切换。
- **网页版**（`web/`）：设备页、发给某台设备的旁聊、审批卡片的层级和「记住」胶囊、带「停止」的「手」卡片、设置 → Hands、第一次打开时和「连接」下的 Cloud 登录、默认形象小龙。构建产物放进 `nanomuse/server/static/`。
- **窗口**：从 0.1.30 起，窗口是跑在 DeepSeek Harness（`harness/`）上的 [nanoMuse 桌面版](desktop.md)：harness 的 Host 和网页版装在我们自己的 Electron 外壳里，nanoMuse 的账号、形象、Hands 和 Reach 作为插件，再捆上这个运行时给手用（`nanomuse mcp`，走 stdio）。原来包着这个运行时和网页版的 Electron 外壳（`desktop/app`，0.1.19–0.1.29；托盘、画出手即将点击位置那个圈的透明舞台窗口、全局「停止」和快速唤起快捷键、「开机自动启动」）已经退役；这些会在 harness 的接缝上回来（[harness.md](harness.md)，第 7 阶段）。任何人在浏览器里打开 `nanomuse serve`，网页版在宽窗口上仍然按 Muse 的样子排布。
- **标准库二进制**（`desktop/nanomuse_desktop`）曾是没有 Python 的机器上免安装的后备方案，也是 `nanomuse/hub` 的源头；0.1.39 去掉了它，因为 nanoMuse 桌面版自带运行时。

### 这台电脑上的手 {#hands-on-this-computer}

`computer_task` 是手机操作器底下换了一台电脑：同样的循环（看，决定一个动作，经哨兵执行，再看），同样的汇报，同样的「停止」。不同的是方言和设备：

- **方言。** 模型说的是 Qwen 的 `computer_use` 格式（`left_click`、`double_click`、`right_click`、`left_click_drag`、`mouse_move`、`scroll`、`type`、`key`、`wait`，再加 `open`（按名字打开一个应用）、`answer`、`ask_user` 和 `terminate`），坐标用手机那套 0–999 网格，所以一个视觉模型两边通用。回复格式（Thought / Action / 一个 `<tool_call>`）和解析器都是手机的。
- **设备。** 截图走 `mss`（所有平台，按模型需要缩放）；动作走 `pyautogui`（`pip install "nanomuse[hands]"`），Linux 上装了 `xdotool` 而没装 pyautogui 时用 `xdotool` 兜底；当前窗口的标题从各平台取（`xdotool` / `osascript` / `GetForegroundWindow`），这样卡片和日志说的是「在 Firefox 里」，而不是「在屏幕上」。
- **权限。** macOS 会要一次「录屏」和「辅助功能」；设置 → Hands 会说明，并打开对应的面板。在桌面版下，这两项都归它的助手「nanoMuse Computer Use」（[desktop.md](desktop.md#macos-permissions)）；单独跑的运行时则算在启动它的那个程序头上（比如终端）。Linux 需要 X11（Wayland 还没有可移植的办法移动指针；页面上会说明）。Windows 什么都不需要。
- **按应用。** 一场对话里在某个应用中的第一个动作会问「让 Nova 使用 Safari 吗？」：一次、本次对话，或总是。答案是一条 `computer_app:<bundle id or name>` 下的哨兵授权，所以设置 → 权限会列出它，也能收回。`[sentinel] mode = "auto"` 像跳过其他询问一样跳过它。
- **手永远不打**：密码、PIN、卡号、验证码。操作器把屏幕交还给你：一张「轮到你了」卡片，写明原因；你输完，按「完成」，操作器再看一眼。

#### 窗口模式（macOS） {#window-mode-macos}

在 Mac 上，手可以只在**一个应用的窗口**里干活，而不是整个屏幕（`[hands] mode`，以及「手」卡片上的「范围」：「自动」/「单个窗口」/「整个屏幕」；`nanomuse/computer/mac_window.py`）：

- 模型看到的画面只有那个窗口，macOS 14 及以上由桌面版的助手「nanoMuse Computer Use」用 ScreenCaptureKit 截取（操作器的 `POST /window`，[gui.md](gui.md#hands-on-the-computer-the-picture-is-the-unit)），没有助手时由运行时自己的 `CGWindowListCreateImage` 截取，并按模型需要缩放；坐标是这张画面的像素，再映射回窗口在屏幕上的位置；
- 点击、拖动、滚动和按键投递给该应用的进程（`CGEventPostToPid`），不经过系统光标，鼠标还是你的，期间可以在别的窗口干活；文字以 unicode 键盘事件输入，所以中文和 emoji 都能原样打进去；授予了「辅助功能」时，落点处的按钮通过辅助功能树按下（`AXPress`），而不是模拟一次点击；
- 智能体用 `computer_act` → `computer_target`（`app`：菜单栏显示的名字，或 bundle id）指定窗口，或者在任何动作上带 `app`；`open_app` 把打开的应用设为目标。「自动」是一有应用被指名就进窗口模式，在那之前用整个屏幕。

你看到的是：「手」卡片写着「正在 Safari 的窗口里操作；鼠标仍归你用」，桌面舞台把光标画在点击的落点（手的事件带着屏幕像素的 `x`/`y`），审批卡片写明应用的名字。找不到、截不到（助手的「录屏」那一行没开：操作器的 `403`，用它的话说）或驱动不了的窗口，会退回整个屏幕，并在观察里加一句说明；什么都不会停。这一层本身出问题时（助手不在、pyobjc、窗口服务器），「自动」会在这个目标余下的时间里把手停在整个屏幕上，说明一次，等下一个应用被指名时再试窗口；「单个窗口」则照你要的继续尝试。两种情况下「手」卡片的「范围」那一行都会显示原因。Linux 和 Windows 一直用共享的屏幕；`pip install "nanomuse[hands]"` 只在 macOS 上带上 pyobjc 框架。

## 手机 {#the-phone}

从 0.1.12/0.1.13/0.1.17 起就已经两个角色都有：本地的沙箱 shell 和「手」，向外的 `nanomuse-pc` 和 hub，向内的 `task` 走无头聊天运行器。这个阶段 Android 那一轮，按顺序：hub 的 `approve` 到达 RiskGate 卡片，抽屉里加一个「设备」入口（两件都在 0.1.19 做了，见[手机，在 0.1.19](#the-phone-in-0-1-19)），以及书桌电脑的「手」事件在它干活时显示出来。这些都不挡桌面端的工作。

## 浏览器：一台模拟手机上的演示 {#the-browser-a-demo-on-a-simulated-phone}

[nanomuse.cn/web](https://nanomuse.cn/web/) 通向展示站：浏览器里的一台模拟手机（MobileGym，nanoMuse App 放在前台：`demo/mobilegym/apps/nanoMuse`），背后是展示站网关为这次访问启动的、访客自己的一份私有 nanoMuse，`ghcr.io/nano-muse/nanomuse` 镜像，跑在一个除了网关没有任何出口的网络里，和展示站的模型对话，访问结束就消失。访客先登录 nanoMuse Cloud（验证码发到手机或邮箱，或用账号密码；`demo/showcase/gateway/showcase_gateway/visitors.py`），这样项目知道是谁在试，而且到安装 App 那天，同一个账号就在那里等着。页面上直说：这是一个演示，离 Android App 还差得远，并告诉你 App 在哪里。首页 [nanomuse.cn](https://nanomuse.cn/) 把同一个页面放在一个框架里显示（`?embed=1`：没有自己的页头，手机等你点一下才开机，而不是自己亮起来，所以打开首页什么都不会启动）。

网页版早先的形状（每个 Cloud 账号一份常驻的 Muse，带命名卷，在 hub 上和其他设备一样占一个位置；`accounts.py`，`WEB_ENABLED=1`）仍然留在网关里，给自己跑网关的人用；项目自己的服务器上从 0.1.26 起关掉了。细节和设置项在 [demo/showcase/README.md](../../demo/showcase/README.md)。

## iOS、网页控制台、眼镜 {#ios-the-web-console-glasses}

iOS 会说 hub 的话（`info`、`open`、`notify`、`task`），形状从 0.1.34 起就有了（[ios.md](ios.md)）。云端控制台（`/app/`）是一扇没有自己的手的门，以后也是。眼镜是一句话进、一句话出，手在别处；hub 对它们来说已经够用了。

## 复用了什么，从哪里来 {#what-is-reused-and-from-where}

- **UI-TARS-desktop**（Apache-2.0）：操作器的模式（截图进，解析出动作，每种设备一个 `execute`），以及智能体干活时屏幕上的标记。不要它的 Electron 应用，也不要它的模型：它的动作空间是 UI-TARS 模型的，我们的是 Qwen 的 `mobile_use` / `computer_use`。
- **OpenCode v2**（MIT）：桌面端做成一个薄 Electron 外壳，启动一个本地服务，对着它渲染一个网页应用（electron-vite、electron-builder、托盘，以后还有深链接）。不要它的智能体：它是围绕一个项目目录的编程助手；nanoMuse 是围绕一个人的个人智能体。
- **Codex**（Apache-2.0）：CLI 作为通向同一个智能体的正式入口，在终端里审批，命令跑在沙箱里；运行时的 `nanomuse chat` 和哨兵已经是这个形状。
- **Qwen-Agent / MemGUI-Bench**（MIT）：`mobile_use` 和 `computer_use` 方言和回复解析器，已经在 `nanomuse/phone/operator.py` 里。
- **pyautogui**、**mss**、**xdotool**：鼠标、键盘和截图。不自己写输入库。

## 现状 {#status}

| | 手机 | 电脑 | nanoMuse Web（`WEB_ENABLED=1`；0.1.26 起是演示手机） | 网页控制台 | iOS |
|---|---|---|---|---|---|
| 本地 shell / 文件 / 浏览器 | 有 | 有（运行时） | 有，在它的容器里 | 没有手 | 无 |
| 把屏幕当手 | 「手」（0.1.12） | `computer_*`（0.1.19） | — | — | — |
| 驱动其他设备 | `nanomuse-pc`、hub | `device_*`、`delegate`（0.1.19） | 同一个运行时 | 挑一台设备，发一个任务 | — |
| 回应其他设备 | 会 | 在一个看得见的旁聊里（0.1.19） | 会 | — | info / open / notify / task |
| Android 形状的界面 | 参照 | 网页版（宽屏用侧栏）+ 窗口（0.1.19） | 网页版 | 控制台 | 0.1.34 起 |
| 手干活时的舞台 | `HandsStage` | 「手」卡片；窗口里的舞台悬浮层 | — | — | — |

随 0.1.19 发布的：APK、桌面安装包（`nanoMuse-Desktop-…`，[`.github/workflows/desktop-app.yml`](../../.github/workflows/desktop-app.yml)）、终端二进制（0.1.39 已去掉），以及 nanomuse.cn/web 上的 nanoMuse Web（0.1.26 起是模拟手机上的演示）。

## 在一台机器上调试整套东西 {#debugging-it-all-on-one-machine}

两个运行时加一个中继，都在 `127.0.0.1` 上，就够把一个任务从一台设备走到另一台再走回来。这里什么都不需要真实账号、邮件服务商或手机。

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
# ambient provider keys would be picked up as the model — clear them for a clean first run
env -u OPENAI_API_KEY -u DASHSCOPE_API_KEY -u ANTHROPIC_API_KEY -u OPENAI_BASE_URL \
  .venv/bin/nanomuse serve -c /tmp/nm-dev/a/config.toml --no-auth --no-qr --port 8799 > /tmp/nm-dev/a/serve.log 2>&1 &
env -u OPENAI_API_KEY -u DASHSCOPE_API_KEY -u ANTHROPIC_API_KEY -u OPENAI_BASE_URL \
  .venv/bin/nanomuse serve -c /tmp/nm-dev/b/config.toml --no-auth --no-qr --port 8798 > /tmp/nm-dev/b/serve.log 2>&1 &

# 3. sign both in with the same e-mail in the first run (the code is in relay.log:
#    grep -i code /tmp/nm-dev/cloud/relay.log), pick "Use the Cloud model" on each.
# 4. (0.1.19–0.1.29) the Electron window over Desk A came from desktop/app; now open
#    http://127.0.0.1:8799/ in a browser, or sign nanoMuse Desktop in as a third device.
```

然后在 Desk A 上：「设备」里能看到 Laptop B 在线；「去问它」（或聊天下面的那个标签）打开一场*在 Laptop B 上*的聊天；在那里打的任务在 B 上跑，它的工具标签和审批卡片带着设备胶囊出现在 A 里，在 A 里决定的审批两边的卡片一起关掉，B 的答复落进 A 的聊天。把端口换过来，反方向也一样。用 `ss -ltnp | grep ':879'` 和 `kill` 把这些全停掉。

## 手机，在 0.1.19 {#the-phone-in-0-1-19}

电脑做的三件事从 0.1.19 起在 Android 上有了对应：手机的 hub 客户端能读 `tool` / `tool_result` / `approval_result` 阶段（`ReachOffloadHandler`），hub 的 `approve` 帧能到达 `RiskGate`，手机自己的审批作为 `approval` 事件传给提问方（`HubActions`），抽屉里的聊天旁边多了一行「设备」。还没做的：手机发起任务时，把书桌电脑的手事件（`HandsLive`）显示成手机上的一张「手」卡片。
