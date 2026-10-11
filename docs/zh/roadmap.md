# 路线图

个人智能体不该只长在别人的云里，nanoMuse 想做一个开源、低成本的平替：装在自己的设备上，模型自己选，中继也能自己架。我们希望和全球的开发者、使用者一起，让每个人真正拥有自己的个人智能体。提个 [issue](https://github.com/nano-muse/nanoMuse/issues/new/choose) 或者发个 [PR](../../CONTRIBUTING.md) 都是在帮 nanoMuse 变得更好。

这一页是给想来帮忙的人画的地图：我们现在在做什么，接下来做什么，每个领域先从哪里下手。不写日期：一样东西在一台真手机和一台真电脑上能用了，就发。

0.1 系列是预览版，1.0.0 是第一个稳定版。手机、桌面、网页和中继我们每天都在用，也仍然知道哪里还粗糙；下面的清单对此如实说。不变的是：是一个智能体而不是一个框架；它和任何不可撤销的操作之间隔着一道审批；秘密永远到不了模型那里；记忆你能读、能改；任何 OpenAI 兼容的模型都能用；自由软件。

## 现在：追上 Muse {#now-catching-up-with-muse}

Meta 的 Muse 定下了这类智能体的样子；下面是我们还落后于它的地方，以及每一处的第一个任务。

### 记忆 {#memory}

智能体维护着 `SOUL.md`、`USER.md`、`MEMORY.md`、`HEARTBEAT.md` 和一个 `remember` 工具；整理会定期跑，回忆是对存储做嵌入检索。还缺的：在对的时刻自己冒出来的记忆；看得见的遗忘；每台设备上是同一份记忆，而不是各管各的。

- 模块：`nanomuse/memory/`（`store.py`、`consolidate.py`、`embeddings.py`）；手机的 `io.github.nanomuse.sysfiles`；桌面档案面板里的「记忆」。
- 阅读：[desktop-muse.md](desktop-muse.md)（记忆页）、[android.md](android.md)。
- 第一个任务：在 `tests/test_memory_recall.py` 里写一个测试：某条事实，智能体应该在之后的某次对话里不用人提就说出来；然后让它通过。

### 主动性 {#proactivity}

目标按计划检查，例程在 App 关着时照样跑，动态每天早上写一篇。还缺的：智能体在两次计划之间自己注意到事情，比如来了一封邮件（`nanomuse/triggers/mail.py` 是第一个触发器）、一个快到的日历项、一台刚上线的设备，然后判断值不值得说一句。

- 模块：`nanomuse/goals/`、`nanomuse/triggers/`、`nanomuse/nudges.py`；手机的 `io.github.nanomuse.feed` 和 `goals`。
- 阅读：[every-device.md](every-device.md)，讲一声提醒怎么到达你手里拿着的那台设备。
- 第一个任务：在 `mail.py` 旁边加第二个触发器（日历是最顺理成章的一个），接口相同，连同它产出的那条动态。

### 对话 {#the-conversation}

一切都在聊天里发生，而它现在仍然像一个聊天客户端。存在感（智能体干活时形象有反应、状态栏用人话说它在做什么）在各客户端之间参差不齐；自 0.1.22 去掉通话（[calls.md](../calls.md)）之后，语音只有输入，会回答的声音还是个没定的问题；手的舞台（桌面的 `harness/dsh-nanomuse/src/client/Trajectory.tsx` 和外壳的 `glow.html`，Android 的 `HandsStage.kt`）展示手的动作，桌面上还会在每一步之前显示智能体的话，但还没有在每个客户端上都做到让人跟得上。

- 模块：`harness/dsh-nanomuse/src/client/`（`AvatarChat.tsx`、`Trajectory.tsx`、`Capsule.tsx`），Android 的 `io.github.nanomuse.chat` 和 `hands`，iOS 的 `NanoMuseChatCards.swift`、`NanoMuseComposer.swift`。
- 阅读：[desktop-muse.md](desktop-muse.md)、[parity.md](parity.md)，各客户端之间还没合上的项。
- 第一个任务：在 `parity.md` 里挑一行，选你能跑的客户端上还没做的，把它合上。

### 让手更常成功 {#hands-that-succeed-more-often}

把屏幕当手，在 Android 和桌面上都能用（桌面的操作器移植自 UI-TARS-desktop）。它失败在定位上（模型指错元素），以及碰到意外弹窗之后的恢复；而且我们还没有一组固定的任务来衡量它。

- 模块：`nanomuse/computer/`（`operator.py`、`coords.py`、`screen.py`）、`nanomuse/phone/`（`operator.py`、`trace.py`）、`harness/desktop/src/operator.ts`、Android 的 `io.github.nanomuse.hands`。
- 阅读：[gui.md](gui.md)，操作器的约定；[troubleshooting.md](troubleshooting.md)。
- 第一个任务：用 `nanomuse/phone/trace.py` 录下一次失败的运行，写明在哪一步出了错，带着轨迹开一个 issue。十个这样的 issue 就是一套评测集。

### 一条命令自己部署 {#self-hosting-in-one-command}

`scripts/self-host.sh` 把带 TLS 的中继拉起来；网页版运行时有自己的 `docker-compose.yml`。还缺的：两者合成一条命令，升级时数据不丢，以及一页说清楚给一家人跑要花多少钱。

- 模块：`cloud/`（`docker-compose.yml`、`docker-compose.local.yml`、`Dockerfile`）、`scripts/self-host.sh`、根目录的 `docker-compose.yml`。
- 阅读：[self-hosting.md](self-hosting.md)、[cloud.md](cloud.md)、[deployment.md](deployment.md)。
- 第一个任务：在一台干净的机器上跑 `bash scripts/self-host.sh --local`，把说明里每一处写错的地方报回来。

### 国际化 {#internationalisation}

应用有英文和中文；Android 版还带着上游来的十五种语言，我们在这些语言里的字符串（`nm_strings.xml`）得到的照看远不如英文和中文多。README 有十种语言。

- 模块：`android/src/android/app/src/main/res/values-*/nm_strings.xml`、`android/src/ios/Localizable.xcstrings`、`harness/dsh-nanomuse/src/client/locales.ts`，以及 `cloud/nanomuse_cloud/` 下中继的控制台。
- 阅读：[CONTRIBUTING.md](../../CONTRIBUTING.md) 的 *Every string in every language*（每一条字符串、每一种语言）一节。
- 第一个任务：用你会说的语言打开应用，记下每一条读着不对的字符串，改那个语言的文件。

## 接下来 {#next}

- **一套公开的评测集。** 把上面说的手的失败变成一组固定的手机和电脑任务，谁都能跑，用展示站里的模拟手机（[showcase.md](showcase.md)、`demo/mobilegym/`）做测试台。每个版本一个数字，而不是一个印象。
- **我们自己的手的模型，用公开数据训。** 大家选择贡献出来的轨迹（「数据控制」，[privacy.md](privacy.md)）是训练集；评测集是尺子。小、权重公开、擅长中文 App。
- **记忆的每一行都有出处。** 智能体记下的每一条事实都应该说明是哪个模型写的、什么时候写的、有多确定，这样一条错的记忆能追溯，一条可疑的记忆能被标为可疑。
- **可以分享的技能。** 今天一个技能就是一个文件夹（`nanomuse/skills/`）；它应该是一样能递给朋友、从一个链接安装、因为风险已经声明所以可以放心的东西。
- **更多设备当手。** 一个浏览器扩展，让智能体能在你已经登录的浏览器里动手；一块手表，最短的入口；汽车和家，作为智能体能看、能动的地方。每一样都是 hub 的一个新客户端（[hub.md](hub.md)），不是一个新的智能体。
- **一块小板子当设备。** 一块走蓝牙的小开发板，会说几种 hub 帧（一盏可以打开的灯、一个可以读的传感器），作为通往下面说的物理世界的第一步。

## 更远：抬头看 {#later-looking-up}

- **物理世界。** hub 的帧已经带着 *look*、*act* 和 *ask*；一条机械臂或一个摄像头不过是再多一台设备。我们还不知道一个个人智能体有了身体之后，应该被允许做什么。
- **能用上很多年的智能体。** 长十年也不会变成噪音的记忆；换了模型仍然属于你的名字和形象；能搬到另一个运行时的导出。
- **看得懂的个人数据。** 智能体知道的关于你的一切，都是能读的普通文件，别的程序也看得懂；这样智能体是你数据的一个视图，而不是它的主人。
- **怎么评价一个个人智能体。** 上面的评测集给任务打分；一个个人智能体还要看它是否了解你、是否在该问的时候问了。这个我们还没有办法衡量。

## 代码在哪里 {#where-the-code-is}

两棵树。**`android/`** 是用 `git subtree` 拉进来、改过的 OpenMinis 1.13；我们的 Android 代码在 `io.github.nanomuse.*`，iOS 代码在 `android/src/ios/NanoMuse/`（[CONTRIBUTING.md](../../CONTRIBUTING.md) 说了在那里怎么干活）。**`nanomuse/`、`harness/`、`cloud/`、`web/`** 从头到尾都是我们自己的：给桌面和网页提供手的 Python 运行时、作为 DeepSeek Harness 插件的桌面 App、中继、网页控制台。[architecture.md](architecture.md) 画出了整体；[AGENTS.md](../../AGENTS.md) 是一屏看完的版本，附检查命令。

## 过去的版本 {#past-releases}

每个版本都是从它的标签构建出来的一个 GitHub release，标题是 `nanoMuse <version> · <Codename>`；每一版的说明在 [releases/](../releases/)，逐条的记录是[更新日志](../../CHANGELOG.md)。

| 版本 | 代号 | 一句话 |
|---|---|---|
| 0.1.1 – 0.1.11 | Foundation … Hatch | OpenMinis 变成 nanoMuse：名字和形象、一条主对话、带范围的审批、记忆文件、动态、形象工作室、小龙 |
| 0.1.12 Hands · 0.1.15 Stage | | 手机的屏幕当手，以及展示它干活的舞台 |
| 0.1.13 Reach | | 手机驱动你的电脑（0.1.24 起由 hub 取代） |
| 0.1.18 Open | | nanoMuse Cloud：不用 key 就能开始，注册向所有人开放（包含起草了但从未发布的 0.1.17 Doorstep） |
| 0.1.19 Ensemble | | 每一台设备：桌面 App、hub 上的运行时、nanoMuse Web |
| 0.1.20 – 0.1.25 | Presence … Mirror | 账号优先、一个声音、邀请、手机号登录、每台设备上同一个形象 |
| 0.1.26 – 0.1.30 | Window … Rooms | 展示站；桌面迁到 DeepSeek Harness，采用 Muse 的形态和房间 |
| 0.1.31 Locks | | 审计留下的问题都合上了：任何 URL 里都没有令牌，远程控制须经同意 |
| 0.1.32 – 0.1.35 | Union … Accord | iPhone 和桌面一屏一屏地追上手机 |
| 0.1.36 – 0.1.38 | Thread · Weave · Loom | 多台设备上同一条对话，先从主对话开始；桌面的手从 UI-TARS-desktop 移植过来，Mac 的权限交给一个辅助 App；文档站，以及一条命令的自己部署 |
| 0.1.39 | Keys | 一份服务商目录，写明每把 key 覆盖什么，每个客户端和中继都有；ChatGPT 套餐可以用来登录；共用的设备上每个账号只看到自己的对话；手的点击在 Ubuntu 上能点准，Mac 辅助 App 保得住它的授权，iPhone 引导结束后不再崩溃；每种语言都补全；终端版去掉 |
| 0.1.40 | Clear | iPhone 的输入框不再消失：它之前藏在底栏后面，现在是一个普通的行，设置里多了一个「输入框检查」页；手机上的每条聊天都属于一个账号，退出登录时会问你怎么处理它们；中继的每一种拒绝在每个客户端上都是一句话或一张卡片；中继上给运营者的「控制」「统计」「官网」页；Mac 上用 ScreenCaptureKit，不再有替代图片；Windows 在把 App 挪了位置的那次更新之后又能启动；桌面的灯光和手的光晕像手机上那样动起来 |
| 0.1.41 | Choice | 设置 › 模型 的四行（对话、操作屏幕、生成图片、生成视频），Android、iPhone、桌面和网页都有；保存 key 之后的「用它来做什么」卡片；「自动」按一个顺序走（对话服务商，然后 nanoMuse Cloud，然后第一把能做的 key）；不悄悄回退，失败的一轮给「这次改用 nanoMuse Cloud」；桌面用你自己的 key 画图，换手的模型不用重启；`PUT /api/connections/image` 和 `/video`；README 以影片开场，论文上了 arXiv，文档站有简体中文版 |
| 1.0.0 | Keel | 第一个稳定版：Android 和 iPhone 的手机 App、Mac、Windows 和 Linux 的桌面 App、网页控制台和中继，一个账号贯穿所有设备；nanoMuse Cloud 可以作为模型来源关掉，有自己 key 的设备退出登录也能用；主聊天跟着你选的对话模型走；模型选择器会折叠、能搜索；桌面上自己的 key 也能选思考深度；「我已经点过 Star」；桌面版等待 Windows 上慢的启动；回复跟随 App 的语言；`auto` 在带污点的外发和警告前会问；hub 和中继加固；人读到的话里不再有破折号 |
| 1.0.1 | Ballast | 手机 App 有了自己的 URL scheme，不再和 OpenMinis 相撞；内容审核拒绝在每个客户端都是一句话，中继的健康页把它和上游错误分开计数；桌面端从别的设备收到的聊天能滚到开头，操作屏幕时呼吸灯整段亮着，Windows 上的形象会动了；网页控制台可以让某一轮走 nanoMuse Cloud；TestFlight 测试版通过了 Apple 的审核 |
| 1.0.2 | Trim | 把项目的每一部分过了一遍：Sentinel 的污点规则在自动模式下对 `shell` 和 `send_email` 也成立；Android App 能和 OpenMinis 装在一起启动；桌面端在运行时拒绝某一步时重新弹出权限卡，Linux 上读图不再弄死 harness，Windows 的窗口按钮不再盖住页面按钮；记忆整理判断不了的就拒绝；`doctor` 会点名没人读的配置键；网页控制台和命令行的报错更清楚；iPhone 的页面有了全部九种语言；文档里没有破折号了 |
