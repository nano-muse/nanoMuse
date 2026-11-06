# iOS

iPhone 上的 nanoMuse 是 OpenMinis 1.13 的 iOS 那一半，顶着 nanoMuse 的名字，由 CI 在
Mac runner 上构建后交给 TestFlight。这一页说的是：源码树里有什么、怎么构建、TestFlight
流水线需要什么、还有哪些要从 Android App 移植过来。

**现状。** 源码树、品牌、nanoMuse Cloud 登录、hub 客户端和流水线都是在一台 Linux 机器上
写的。这个 App **能构建、能签名、已经上了 TestFlight**：第一个构建 0.1.31 (2) 于 2026-10-03 走完
*iOS · TestFlight* 工作流；1.0.0 是构建 16，已通过 Apple 的 beta 审核，公开链接
（`https://testflight.apple.com/join/ZHexbDqc`）最先装的就是它；1.0.1 是构建 18，1.0.2 是构建 19，两个都在 2026-10-12 通过了审核；1.0.3 是构建 22，1.0.4 是构建 26，两个都在 2026-10-13 通过了审核，所以链接今天装的是构建 26；1.0.5 是构建 28，2026-10-14 提交审核；1.0.6 是构建 29，从 tag `v1.0.6` 构建，2026-10-24 上传（见下文*现状*）；构建 20 和 21（1.0.2）、23、24、25（tag 之后合入修复的 1.0.3）以及 27（同样情况的 1.0.4）只到了内部测试员手里。测试员的反馈推动了发布说明里的那些修复（输入框、引导、退出登录）；「设备」区
和来自其他设备的通知仍是真机上跑得最少的部分。第一次归档教会了流水线一件事：
自动签名需要一台已注册的设备，这就是它现在改为手动签名的原因。

## 它在哪里 {#where-it-lives}

`android/` 是整个 OpenMinis 仓库的 `git subtree`，不只是 Android App。iOS 那一半在项目
开始时被删掉了，现在恢复回来，放**在那个 subtree 里面**：`android/src/ios`，连同
`android/deps/` 下的 iOS 依赖脚本和 `android/deps/ish` 子模块（ARM64 的 iSH 分支）。
把它放回上游原本的位置，而不是另开一个 subtree，是让 `git subtree pull` 对两个平台同时
可用的关键。

```
android/src/ios/                 Xcode 工程：Minis.xcodeproj、App、扩展、测试
android/src/ios/NanoMuse/        我们的：nanoMuse Cloud 客户端和各个页面（Minis target 的同步
                                 文件夹；放进一个 .swift 文件就会被编译）
android/src/ios/fastlane/        TestFlight 的 lane
android/deps/build_lame.sh       LAME → FFmpeg → iSH → Alpine rootfs → rclone，按这个顺序
android/deps/build_ffmpeg.sh
android/deps/build_ish.sh
android/deps/prepare_alpine_rootfs.sh
android/deps/build_rclone_ios.sh
scripts/rebrand.py               其中的 `ios()` 一步：id、名字、版本、字符串、链接、颜色
scripts/gen-ios-icons.py         App 图标和四款备选图标，来自 assets/brand/
.github/workflows/ios-testflight.yml
```

[CONTRIBUTING.md](../../CONTRIBUTING.md) 的规则原样适用：新代码放新文件（这里是
`NanoMuse/` 文件夹），改到上游 Swift 文件里的地方带一条 `// nanoMuse:` 注释，品牌替换
只靠脚本，从不手改。

## 这里哪些是 nanoMuse 的 {#what-is-nanomuse-here}

由 `python scripts/rebrand.py` 应用（幂等；每次拉取上游后跑一遍）：

- **身份。** Bundle id `io.github.nanomuse.app`（加 `.ShareExtension`、`.AgentWidget`、
  `.FileProvider`）、app group `group.io.github.nanomuse.app`、iCloud 容器
  `iCloud.io.github.nanomuse.app`，以及带着 bundle id 的后台任务、UTType 和 URL scheme 的
  id。和 Android 不同，iOS 上没有源码包名的限制，所以整个家族一起换。系统认得这个 App 的
  URL scheme 是 `nanomuse`（分享扩展打开 `nanomuse://share`）和 `nanomuse-mcp`，这样同一部手机上
  也装了 OpenMinis 时，不会有两个 App 抢同一个 scheme。App 内部的链接仍是 `minis://…`：那是上游
  和它自己的沙箱、系统提示词和模型之间的约定；从系统进来的 `nanomuse://` 链接按它的 `minis://`
  形式读（`NanoMuse/NanoMuseOwnScheme.swift`），聊天之外我们自己的按钮打开这类链接时走深链路由，
  不经过系统。
- **名字。** 显示名 nanoMuse、「Share to nanoMuse」「nanoMuse Files」；Swift 字符串字面量、
  `Localizable.xcstrings`（键名改了，九种翻译全部更新）和 Info.plist 各语言的用途说明里，
  「Minis」→「nanoMuse」。OpenRouter 的 `HTTP-Referer` 仍指向 OpenMinis，和 Android 一样：
  那是署名，不是身份。
- **版本。** `MARKETING_VERSION` 和 `CURRENT_PROJECT_VERSION` 跟随 Android 的
  `versionName` / `versionCode`；CI 用运行编号覆盖构建号。
- **外观。** AccentColor 用 `#015CFB` / `#58A6FF`，不用 iOS 蓝；一笔画的 N 作为应用图标
  （白底方块，品牌渐变；深色外观下是深色方块），也作为应用内图标选择器的四款皮肤；智能体
  的标题符号用 🐾 代替 ✨。
- **关于。** 指向这个仓库和它的 issues 的链接、隐私页、nanoMuse 自己的口号，以及一段致谢：
  基于 OpenMinis 1.13（GPL-3.0），与 Meta 无关。

我们自己的，在 `NanoMuse/` 里：

- **对缓存稳定的智能体指令。** 系统提示把固定的工具和安全说明放在一个不变的前缀里，后面
  再接模型能力、技能和 MCP 元数据、记忆、`USER.md` 和对话引导，最后是当前时间、语言和
  可用模型数，作为一段确定的易变后缀。写一条记忆或每小时刷新一次时间，不再让支持前缀缓存
  的服务商把静态指令作废；回退模型按同样的布局重建。
- **nanoMuse Cloud。** *服务商* 页第一行就是「nanoMuse Cloud」：手机号或邮箱地址、验证码，
  然后中继（[cloud.md](cloud.md)）就成了 App 里一个普通的 OpenAI 兼容服务商，自带一个模型组，
  没有默认时它就是默认。和 Android 客户端（`io.github.nanomuse.cloud`）同样的线上格式、同样
  的规则：每个中继一个实例，不替换用户自己的任何东西，刷新时遇到 401 就移除这个服务商（并把
  账号的数据放到一边，见下文契约 C12）。任何构建都能指向另一个中继（见下文 *使用其他
  服务器*）。从 0.1.32 起这一页就是整个账号：密码作为另一种登录方式、朋友的邀请码、以元
  计的额度池和余额不多时接着用的办法（自己的 key、邀请、点一次 star）、按种类和按模型的
  用量、持有 key 的设备、时间线、删除，和手机的 `CloudAccountScreen` 相同的几块。
- **智能体的步骤，状态行。** *设置 → 聊天 → 执行步骤* 让已完成的消息里不再出现工具胶囊，
  除非你要看；正在输入的那一行写的是 *〈名字〉正在处理*，不是 *正在思考*。两处都是上游
  `AssistantBlockView` / `ContentView` 里的单行改动，标了 `// nanoMuse:`。
- **点点下面的等待（1.0.8；`NanoMuseStreamStatus.swift`）。** 一步还没等到第一个字时，
  正在输入那一行下面的 `NanoMuseWaitLine` 前十秒什么都不说，然后是「模型接口比较忙，已等待
  15 秒」和「取消」（聊天的停止）；nanoMuse Cloud 说请求正在等它的模型名额时（中继 0.31 的
  `nanomuse: {phase, ahead}` chunk，[cloud.md](cloud.md#protocol)），改为「前面还有 3 个」或
  「下一个就到你」。两个 OpenAI provider 的 SSE 循环里各一行标记的代码把字段递过来；
  `ChatMessageViews` 里一行画出这行字。
- **提示预算（1.0.8；`NanoMuseContextBudget.swift`、`NanoMusePromptDiet.swift`）。** 64k 以上
  的窗口压缩线一律 32k token（上游的分级把它放在窗口往下 20k 处），旧的大段工具结果从 28k
  起写到磁盘，`browser_use` 的 schema 改写得更紧凑而每个动作和参数都在；数据在 Android 那一页。
  `AIChatViewModel` 里的三处调用点有标记；策略自己的分级和测试没有动。
- **Muse 外壳（0.1.33；0.1.34 起 iPad 也有）。** `NanoMuseRoot` 在根上取代了上游的
  `ContentView`；*设置 → nanoMuse* 里有两个开关（*Muse 主页*、*在对话顶部显示形象和名字*），
  OpenMinis 的布局在抽屉里点一下就回得去。聊天的导航标题变成**形象 · 名字 · 状态行**
  （`NanoMuseHeader.swift`）：有问题或审批等着你时状态是 *等你回复*，然后是正在运行的工具的
  `tool_title`（模型自己对这一步的描述，比如 *打开携程网站*），然后是 *正在写回复*，然后是
  *正在处理：〈简述〉*，空闲时是模型的名字；正在画新形象时，显示的是形象流程那边的那行字。
  形象（`NanoMuseFaces.swift`：Application Support 里画出来的脸；没有的话，桌面或网页控制台设的
  emoji 配底色（存在 `avatar/emoji.json`，渲染成一张静态图；手机上还没有选它的界面）；再没有就是
  bundle 里的小龙，五种
  状态，带着其他客户端那样的呼吸、浮动、歪头、弹出和抖动；开了「减弱动态效果」静态图就不动了，
  只剩状态切换时的淡入淡出）点一下进入**智能体的页面**。
  也可以换成一段你自己的短视频来当形象（`NanoMuseOwnClip.swift`：智能体页面钢笔菜单和形象
  工作室里的 *你自己的视频…*；MP4 或 MOV，H.264 或 HEVC 视频，最长 15 秒、最大 30 MB，用之前
  先预览，只保存在这台手机的 `Application Support/nanomuse/avatar/own-clip.mp4`，连同它的
  静帧一起不进 iCloud 和电脑备份，*默认形象* 可移除；回退规则见 [avatar.md](avatar.md)
  里的那一节）。
  选好视频后，照片选择器会先收起，再显示预览。预览需要明确点击「使用」或「取消」才能关闭，
  避免切换窗口的动画误删还没确认的视频。
  抽屉里放着会话、搜索、新建旁聊、*设为主要聊天*、*全部对话* 和 nanoMuse 设置；点圆形按钮
  打开，在主要聊天里从左边缘向右滑也打开（`NanoMuseEdgeSwipe.swift`，挂在窗口上的屏幕边缘
  手势，和 Android 聊天页上的抽屉一样；推出来的旁聊仍然用系统的返回手势）。
- **智能体的页面（0.1.34）**（`NanoMuseAgentPage.swift`，对应 Android `ui/profile`）：带钢笔
  角标的大脸（*更换形象* 会把「把形象改成 」放进主要聊天的输入框，还有 *编辑名称*、
  *形象工作室*）、名字、*在线*，以及四个面板：**动态**（你要求过什么、智能体做了什么，取自
  最近两天的会话）、**审批**（长期有效的「总是允许」答复，可撤销）、**每日**（例程和目标检查
  以及各自的下次运行时间，*管理例程*）、**SOUL 与记忆**（SOUL.md 和 GLOBAL.md，可编辑），
  还有分享页（`NanoMuseAvatarShareSheet`，对应 Android `ui/avatar/AvatarShareSheet.kt`）。
- **从聊天里换形象（0.1.34）**（`NanoMuseAvatarFlow.swift`，对应 Android `avatar/AvatarFlow.kt`）：
  「换成一只橘猫」/「change your avatar to a red panda」在模型看到之前就被识别出来（同一套
  正则，在 `MinisTests/NanoMuseLogicTests.swift` 里有测试）；四个候选以一张卡片出现在聊天里，
  点一下或者说一句来选（*the second one*、*第三个*、*重新生成*）；然后是 *正在完成姿势…*、
  新脸换上、个人资料推送出去、记忆里记一笔、分享卡片。走中继时先出一张费用卡片
  （`/v1/estimate`），手机上有自己的百炼 key 时走它（`NanoMuseImageGen.swift`，DashScope
  原生的图像端点）；工作室（`NanoMuseAvatarStudio.swift`）用同一条路，并且可以选图像模型。
- **调度器（0.1.34）**（`NanoMuseScheduler.swift`）：例程（一个标签、一段提示词、一个时间，
  每天 / 工作日 / 一次或每 N 小时）在一个专属的对话里作为无头回合运行（`NanoMuseHeadless`）。
  说实话：iPhone 只在 App 打开时运行它们（变为活跃时把到期的全跑一遍，之后每分钟查一次），
  并且在每个到期时刻发一条本地通知（*检查：〈目标〉，打开即运行*），点通知打开那个对话。
  退到后台时申请的 `BGAppRefreshTask`（`io.github.nanomuse.app.scheduler`）从不运行例程：
  iOS 批下来时，处理函数只给已到期的那些发提醒，再申请下一个时间片，仅此而已。
  所有关于例程的文案都这么写明了。*设置 → nanoMuse → 定时任务* 列出全部，目标检查和动态的
  那条也在内。
- **目标（0.1.34）**（`NanoMuseGoals.swift`，对应 Android `goals/`）：*创建目标 › 类别* 把开场白
  发到主要聊天，接下来几个回合附上一段系统补充；模型的 ` ```nanomuse-goal ` 块变成目标和它
  的检查例程，` ```nanomuse-goal-update ` 块推进进度；聊天里有卡片（*目标已创建*、*目标进展*），
  目标房间里有进度、步骤、暂停 / 现在检查 / 完成 / 删除，下面是例程。
- **动态（0.1.34）**（`NanoMuseFeed.swift`，对应 Android `feed/`）：一条每日例程从记忆、日记和
  目标里写几条短帖子到 `feed/<day>/<n>.md`，带 front matter；模型通过 ` ```nanomuse-feed `
  围栏把它们交出来。动态房间按天显示、一天之内最新的一批在前，*讨论* 就这条帖子开一个旁聊，滑出的面板里放着动态
  写什么、什么时候写、开关和 *现在写一版*。**点子** 在 *发到聊天* 旁边多了 *创建例程*（按
  点子的时间安排，打开编辑器）和 *开始这个目标*。
- **第一次打开和设置（0.1.34）**（`NanoMuseFirstRun.swift`、`NanoMuseSettings.swift`、
  `NanoMuseCoding.swift`、`NanoMuseSystemFiles.swift`）：Android 引导的四页（欢迎 → 登录，
  免费开始 → 新账号设一次密码 → 哪个模型来回答 → 认识〈名字〉），*我有自己的 API key* 打开
  自己的 key 面板（整份目录，见下文 *自己的 key*），之后是第一次对话（开场白、「我该怎么
  称呼你？」、从模型的 ` ```nanomuse-naming ` 块里选名字、写入 GLOBAL.md 和 SOUL.md）。
  *设置 → nanoMuse*：账号、**编程助手**（通过 hub 的 `coding.*` 动作访问账号下各台电脑上的
  Cursor / Codex / Claude Code 会话，可以给任何一个发消息）、**定时任务**、**系统文件**
  （SOUL、GLOBAL、日记、动态的指令、例程的时间表、从别的助手 *导入记忆*）、连接器、数据控制、
  外壳的两个开关、*重新显示欢迎页*。
- **模型（0.1.34）**（`NanoMuseModels.swift`）：中继的菜单打开时停在标为 *聊天* 推荐的模型；
  项目托管中继目前给聊天和操作屏幕都推荐同一个多模态 `Qwen/Qwen3.6-27B-FP8`。在聊天的选择器里
  选了哪个，哪个就挪到 Cloud 组的最前面，新聊天跟着它走，和 Android 的 `followPick` 一样。
  DeepSeek 的 id 一律视为纯文本，除非名字里有 `v4.1` 及以后、`vision` 或 `ocr`；这是
  `LLMModel.withInferredModality()` 顶上的一步 `// nanoMuse:`。
- **模型分成四个位置（0.1.41）**（`NanoMuseModelSlots.swift`、`NanoMuseModelsView.swift`；
  对应 Android `ui/models/ModelsScreen.kt`）：*设置 → nanoMuse* 的第一张卡片是 *模型*，打开
  四行：*对话*、*操作屏幕*（iPhone 上禁用，显示 *不在 iPhone 上*，副标题 *电脑用它自己的
  设置。*）、*生成图片*、*生成视频*，每行显示 `<服务商> · <模型>`，点进去是一个选择器：只在
  中继实际菜单覆盖的行里先列 *nanoMuse Cloud*（中继推荐的那个标 *推荐*），然后每个能干这件事的自有服务商一组；
  空着的行说明缺什么并给出 *添加服务商*，页面最后一行也是它；图片和视频的选择器下方会把
  目录里说能画图、手机却驱动不了的 key（`NanoMuseModelSlots.notDriven`：只有 DashScope 主机
  能）用一句「此处不提供：……」点名，并说明它在哪里能用。选了对话模型，就把新对话的
  默认组换过去（给这个服务商建或复用一个我们的组，所选的排最前；你自己建的混合组则原样
  设为默认），主要聊天的绑定也跟着换（`NanoMuseModelSlots.mainChatFollows`：主要聊天永远
  不是新对话，0.1.41 上选了自己的 key 之后旁聊走 key、主要聊天却还留在 nanoMuse Cloud），
  页面提示 *对主要聊天和新对话生效；旁聊保留自己的模型。*；在聊天自己的选择器里选的也
  同样生效，不再只限 Cloud。图片和视频按一个顺序决定（你的选择，否则对话服务商自己的默认（当它是能画图的
  百炼 key 时），否则是实际菜单提供这类媒体能力的已登录中继，否则第一个能干的 key）。项目
  托管 Cloud 不提供媒体生成，所以这两行必须用你自己的 key；图片和视频模型来自目录的 `defaults`，不再写在代码里。图片和
  视频的选择器最上面有一项 *自动*（*当前为 〈服务商 · 模型〉*），选它就忘掉存下的选择，让这
  个位置重新按上面的顺序走；视频选择器的 *关闭* 留在它下面。每组最多先显示八行（这个位置
  在目录里的默认模型排第一，然后是当前选中的，其余按列表原顺序），多出来的收在末尾的
  *还有 n 个* 里；各组加起来超过八行时，自动一行下面出现 *搜索模型* 输入框，按模型 id 或
  显示名实时过滤所有组，命中的全部列出，没有命中的组隐藏，一个都不匹配时显示 *没有匹配的
  模型*（`NanoMusePickerList`，测试在 `NanoMuseModelSlotsTests`）。保存
  一把 key 之后，`NanoMuseVendorSheet` 显示 *用它来做什么*：这把 key 能做的每件事一个开关
  （图片和视频只在 DashScope 主机上出现，操作屏幕在 iPhone 上从不出现），默认全开；*就这样*
  把勾选的位置换成这个服务商的默认模型，*暂不* 什么都不改，保存本身不再自动切换任何东西。
  自己的对话模型出错时，失败卡片（以及上游的纯文本错误）在已登录时多一个 *这次改用 nanoMuse
  Cloud*：重试走中继的对话模型（`NanoMuseCloudOnce`，在 `resolveCurrentEntry()` 顶上读），
  任何位置都不变。媒体失败时没有 Cloud 重试。中继的菜单在登录时存在手机上，页面打开时刷新。*图像与视频模型* 作为
  快捷入口保留，里面有自动生成动态的开关和短视频按钮。
- **跨设备的连接（0.1.34）**（`NanoMuseConnectors.swift` 里的 `NanoMuseSharedConnectors`）：
  个人资料里的 `connectors` 列表记录哪台设备连了什么（id、标签、去掉查询字符串的地址、登录
  方式、是否启用、时间、设备），从不记 token；这台手机写入自己的条目，读回其他设备的，
  连接器页面在 *你的其他设备上* 下面列出它们：*已在〈设备〉上连接，在这台手机上登录一次，
  这里也能用*。账号里那张「接着用的办法」卡片跟着地区走：中国大陆百炼在前，其他地方
  *使用 OpenRouter 登录* 在前。
- **连接器**（`NanoMuseConnectors.swift`）：桌面版的目录来自内置的 `connectors.json`
  （`node scripts/connectors-json.mjs` 保持它最新，CI 里跑 `--check`）、MCP 授权流程
  （initialize → 401 → protected-resource 元数据 → authorization-server 元数据 → RFC 7591 注册
  → 上游的 `MCPOAuthController`）、key / 打开 / 自动三类服务，以及对那八个不支持注册客户端
  的服务，询问 client id 并给出可复制的回调地址。原来叫 *MCP 集成* 的设置行现在是**连接器**；
  末尾的 *你自己的服务器* 是上游的 MCP 页面。
- **数据控制**（`NanoMuseDataControls.swift`）：中继的记录里有这个账号的什么（多少轮、其中多少轮用自己的 key、
  多少张图片、这个中继保留多久；中继 0.29 起）、训练集开关和它的计数、隐私页、一次带确认的删除，记录和训练轮次一起删。
  1.0.7 起手机自己也参与记录（[cloud.md](cloud.md#the-record)）：发给账号的聊天请求带
  `X-NanoMuse-Device` 和 `X-NanoMuse-Conversation`（`NanoMuseCloudHeaders.swift`），用自己 key 答完的一轮事后连图片
  （作为文件）一起上传（`NanoMuseOwnTurns.swift`，包在 agent provider 外面；从不带 key 和 base URL），hub 的 hello
  说明新对话由什么模型回答（`device.llm`），头像的短片随头像经 profile 的 `clips` 走（`NanoMuseProfile.swift`：
  这里画出的短片传上去给其他设备，它们的落到本机的 motion 目录，一个头像每个账号只动画一次）。
  **这次调用在对话里的位置，以及一轮前后发生的事**（中继 0.31；`NanoMuseProvenance.swift`、
  `NanoMuseClientEvents.swift`、`NanoMuseFeedback.swift`、`NanoMuseGateEvents.swift`）：发给账号的聊天请求还会说明
  这一轮是谁发起的（`X-NanoMuse-Run`：你本人、例行程序、动态、目标的检查、另一台设备通过 hub 托付的任务）、
  按聊天自己的计数这是第几轮、这次调用是这一轮里的第几次，以及 `X-NanoMuse-Platform: ios`；用自己 key 跑的轮次
  上传时带同样的字段（[cloud.md](cloud.md#provenance)）。为此 agent 的 provider 又包了一层，无头运行
  （`NanoMuseHeadless.run`）会报上自己的种类，所以手打的消息、重试、例行程序的提示和 hub 任务说的都是同一套。
  登录状态下，手机还会把一轮前后发生的事以短记录发上去（`POST /v1/events`）：权限检查对每条 `apple-*` 命令的判定
  和那张确认页是怎么答的，一轮是被手动停下还是出错结束，以及最新回复下面的两个拇指和停止之后的那一个问题
  （「为什么停下来？」，五个一词的答案加「跳过」；两者都在输入框上方；例行程序或另一台设备的那一轮不会问）。
  只有代码和数字：命令名、它的类别、谁答的、等了多久；从不包含它的参数或对话里的任何一个字
  （[cloud.md](cloud.md#client-events)）；*数据控制*里的删除会把它们和轮次一起删掉。
  **Reach**（`NanoMuseReach.swift`）：账号下每台设备一个面板（打开链接、发一条便条、
  跑一行 shell、截一张图），都通过 hub。
  **交给另一台设备的任务**（`NanoMuseDeviceMention.swift`、`NanoMuseRemoteApproval.swift`）：
  以 `@〈设备〉` 开头的消息作为 hub 的 `task` 发给那台设备的 Muse（消息开头打 `@` 时，菜单在文件
  上方列出在线的设备）。运行期间回复就在聊天里画出来（`NanoMuseDeviceReply.swift`）：先是「〈设备〉正在处理…」，
  每一步是一个胶囊，那边 Muse 说的话来一段显示一段，最后答案就在原处；这期间聊天处于忙碌状态，停止按钮
  也会让那台设备停下，期间排队的消息在它结束后发出。超时或断网时，未完成的步骤显示失败；
  停止时显示已取消。即使收到最终答案，也只有收到步骤结果才会显示成功。那边有一步需要点头时，
  `approval` 事件在这里、在输入任务的地方回答（[hub.md](hub.md)），卡片上是 Android 手机的
  四个答案：*允许一次*、*在这个聊天里允许*（为那个聊天记在内存里）、*在 〈设备〉 上始终允许
  这一步*（同一步在同一台设备上，按设备 id 存在这台手机上，智能体页面的*审批*里列出并可
  *撤销*）、*拒绝*；付款只有*允许一次*和*拒绝*。对方给出的时限内（没给则 180 秒）没有回答
  就算拒绝；对方那台设备上的人先回答了的问题（`approval_result`），卡片直接离开，这边不再
  作答。卡片是根上的一张 sheet，所以已经打开的 sheet（设置、工作室）会盖住它，直到关上。
  1.0.3 之前手机对每个这样的问题都答拒绝。
- **服务商连不上时**（`NanoMuseProviderReach.swift`、`NanoMuseProviderReachCard.swift`）：
  一个失败的回合，如果错误出在传输层（*Could not connect to the server*、*A server with the
  specified hostname could not be found*、TLS 或超时的那一行），或者是 OpenAI 的 *region not
  supported*，就显示一张卡片而不是红色横幅：发生了什么、什么有帮助（VPN、*设置 → 网络* 里的
  代理、换一个用自己 key 的服务商）、*重试*、*详情* 后面的原始错误行。`LLMError` 会把出错的
  主机以 `[host: …]` 的形式附在网络错误后面，卡片就能点出它的名字；`mapHTTPError` 丢掉正文的
  401/403/429 由 `NanoMuseReachSignal` 保留几秒，再由 `friendlyErrorMessage` 以一行规范的
  `nm_reach:` 写进消息：ChatGPT 登录过期显示 *重新登录*，套餐窗口用尽显示 *ChatGPT 套餐
  暂时没有余量了*，附 OpenAI 的原话和重置时间。种类、文案和规则都和 Android 的
  `ProviderReach` 一致。
- **中继拒绝一个回合时**（`NanoMuseRelayRefusal.swift`、`NanoMuseRelayRefusalCard.swift`）：
  nanoMuse Cloud 发来的每一种拒绝都是一句用手机语言写的大白话，加一个合适的按钮，从不是
  状态码、中继的 JSON 或者上游的 *Rate limited*。`NanoMuseReachSignal` 把模型调用的每个
  非 2xx 回复先交给 `NanoMuseRelaySignal`（还是 `mapHTTPError` 里那个已有的 `// nanoMuse:`
  位置，上游文件里没有新增）；带 `type: nanomuse_cloud` 或中继某个代码的回复（或者来自
  中继主机的裸 413 / 401 / 5xx）变成消息里一行规范的 `nm_relay:`，`NanoMuseProviderReachCard`
  把它画成拒绝卡片。句子来自 `NanoMuseCloud.describe`，和登录页、账号页用的是同一套，九种
  语言都有：`413 too_large` → *这条消息对模型来说太长了。缩短一些、去掉几个附件，或者新开
  一个对话。* 配 *新对话*；`400 content_rejected`（服务商的内容审核没有放行这些内容；用自己的
  key 时服务商自己的 `DataInspectionFailed` 也算）→ *模型服务商的内容审核没有放行这次请求。换个
  说法试试；如果反复出现，就新开一个对话，被拦下的可能是对话里更早的内容。* 配 *新对话* 和
  *重试*，压缩的对半重试（`isSegmentRetryableError`）不碰它，因为请求再小，同样的内容回来还是
  被拒；中继放在流里的错误（200 里的 `data: {"error": …}`）现在以它的卡片结束这一回合，而不是
  一个空回复（`OpenAIProvider` 流循环里的一处 `// nanoMuse:`）；`401 bad_key` / `account_deleted`
  → *登录*；`403 not_invited` /
  `account_disabled` / `signup_closed` → *打开设置*；`429 too_many_in_flight` / `locked` /
  `rate_limited` 和 `provider_busy`（带 `retry_after` 给出的等待时间）→ *重试*；
  `404 model_not_offered` → *打开设置*；`503 service_paused`、`sync_paused`、`hub_paused`
  以及任何 5xx 或空回复 → *重试*。
- **聊天里的额度**（`NanoMuseAllowance.swift`、`NanoMuseAllowanceCard.swift`；对应 Android
  的 `AllowanceSignal` + `AllowanceWaysCard`）：被 `429 allowance_exhausted` 或 `daily_cap`
  拒绝的回合会在聊天标题下面钉一张卡片，钉法和 star 卡片一样（外壳的顶部 inset，
  `AIChatView.body` 上没有新的环节）：开头是 *免费额度已用完。*、*今天的免费额度……*，或者
  带 `paused: true`（中继 0.22）时的 *这个中继上暂时停了，不是用完了*，并说明剩下的原样
  保留；然后是接着用的办法和 *重试*（把当前聊天的最后一个回合再发一次）。额度池用到 80 %
  （`/v1/me` 的 `spend.warn`）时，`NanoMuseChatCardsHost` 里会有一行字挂在输入区上方，
  *快用完了：还剩 ¥…（共 ¥…）……*，每种池子大小只出现一次（新的发放会再说一次），点 ×
  划掉；卡片出现时替换掉它。
- **自己的 key**（`NanoMuseCatalogue.swift`、`NanoMuseVendorSheet.swift`、`NanoMuseModels.swift`
  里的 `NanoMuseOwnKeySheet`；[own-key.md](own-key.md)）：服务商来自内置的
  `NanoMuse/Resources/providers.json`（`node scripts/providers-json.mjs` 保持它最新，CI 里跑
  `--check`），中继发过 `spend.guidance` 时则先用它（中继 0.21；`429 allowance_exhausted`
  旁边也会带），存在 `UserDefaults` 里跨次运行保留，所以中继上新加的服务商在 App 更新之前
  就能显示出来。`NanoMuseWaysList` 是同一份列表，用在钉着的卡片、设置 → nanoMuse Cloud 和
  自己的 key 面板上：*换成自己的 key*：本地区的首选在前（大陆是阿里云百炼，其他地方是
  OpenRouter 和 OpenAI），一次三个，其余收在 *更多服务商* 后面，每一行写明它覆盖什么
  （*聊天 · 屏幕 · 图片 · 短视频*），*获取 key* 打开服务商的 key 页面，*添加* 在那个服务商上
  打开 `NanoMuseVendorSheet`（粘贴 key，用服务商的端点和 `/v1` 设置添加实例，拉取它的模型，
  以它命名的组在没有默认时成为默认）；*已付费的订阅*：ChatGPT 走上游的 `CodexOAuthManager`，
  Claude、OpenRouter，Kimi 的设备码走 `KimiDeviceLoginSheet`，ChatGPT 那行下面有一句说明：
  OpenAI 的条款只覆盖在 OpenAI 自家 Codex 里使用套餐，别的 App 的这种访问以前被切断过
  （OpenCode，2026 年 1 月），要是停了，API key 照样能用（中继发过自己的措辞时用中继的）；
  *在自己的电脑上*（Ollama、LM Studio、vLLM）填地址。不推荐任何一家。
- **网络**（`NanoMuseProxy.swift`、`NanoMuseNetworkView.swift`，*设置 → nanoMuse → 网络*）：
  给自己的服务商用的 HTTP 代理：主机、端口、可选的用户名和密码，默认关闭，只存在这台手机上：
  地址和用户名在 `UserDefaults` 里，密码在钥匙串里，是一条仅限本机的条目
  （`io.github.nanomuse.app.proxy`，规则同中继密钥；1.0.3 版存在 `UserDefaults` 里的密码会在
  第一次读取时搬过去）。`URLSession` 没有按主机切换代理的开关，所以代理是以一段代理自动配置脚本
  的形式进入会话的（`connectionProxyDictionary`）：对目录里的主机、`chatgpt.com`、
  `auth.openai.com` 和服务商实例的自定义主机返回代理（从不包括中继的主机，也从不包括局域网
  地址），其余返回 `DIRECT`；`NanoMuseProxy.apply(to:)` 在上游每个服务商会话里各占一行，
  `NanoMuseProxy.session` 在 Codex 登录和模型列表那里顶替 `URLSession.shared`。凭据存进
  共享的 `URLCredentialStorage`，归在代理的 protection space 下。*测试* 按你填的代理去取
  `https://chatgpt.com/`。
- **手机的界面框架（0.1.35）**（`NanoMuseChrome.swift`、`NanoMuseAppearance.swift`，对应 Android
  `ui/chat/MuseHeader.kt` 和 `ui/settings`）：Muse 标题栏（形象圆盘、名字胶囊和它下面的实时
  状态行、圆形的抽屉和 ••• 按钮）出现在聊天和动态、点子、目标、资源库上；侧抽屉照着 Android
  的做；智能体的回复用灰色气泡（`NanoMuseChatCards.swift` 里的 `NanoMuseAssistantBubble`）；
  智能体页面的工具栏改成圆形按钮；*设置 → nanoMuse* 按 Android 的顺序重做成 Muse 卡片
  （`NanoMuseSettingsHomeView`：图像与视频模型、形象、电脑、外观（形象大小、名字下面的模型、
  步骤、主题）、通知、账号、编程、定时任务、共享文件夹、对话文件、系统文件、版本）。一个
  `nmOnChange` 辅助函数让 `onChange` 在 iOS 16（App 的部署目标）上也能用。••• 菜单里的
  *新对话*、⌘N、*上下文已满* 弹窗和拒绝卡片发出的都是上游的 `.newChatRequested` 通知；
  `NanoMuseHomeView` 收到后新开一个草稿旁聊，和抽屉里的新对话按钮一样，因为在这个布局里
  上游的 `ContentView` 不在屏幕上（1.0.2 没有这个监听，所以点了没反应，#392）。
- **动作短视频（0.1.35）**（`NanoMuseVideoGen.swift`、`NanoMuseAvatarMotion.swift`、
  `NanoMuseMediaModels.swift`；对应 Android `avatar/VideoGen.kt`、`avatar/AvatarMotion.kt`）：
  画好的脸会得到四段 4 秒的短视频（待命、干活中、等你回复、搞定），来自 `wan2.2-i2v-flash`
  （用你自己的百炼 key；或者使用运营者明确开启旧媒体代理的自建中继，项目托管 Cloud 不提供），提示词和手机版一字不差，按设备存在
  `avatar/motion/` 下；脸用 `AVQueuePlayer` 加 `AVPlayerLooper` 播放它们（后台时暂停），
  小龙的短视频来自 bundle。*图像与视频模型* 列出模型、*换形象后自动生成动态*（默认开）和
  *生成 / 重做短视频*；工作室的费用估算把短视频也算进去。
- **版本、star 提示、动态的第一天（0.1.35）**（`NanoMuseUpdateCheck.swift`、
  `NanoMuseNudges.swift`）：版本那一行显示已安装的构建和最新版本（先查
  `nanomuse.cn/dl/index.json`，再查 GitHub，缓存一天：*最新 0.1.x，你用的就是它* /
  *0.1.x 已发布* / *没查到，点一下再试*）。star 提示遵循中继的策略（`/v1/nudges`、`/v1/me`
  里的 `nudges`，内置同样的默认值）：第一次对话里绝不出现，然后在第 3 / 10 / 30 个任务
  （`NanoMuseStarWatch`：一个由人发起、无错误地离开 `activeSessions` 的会话）、第 7 / 30 天、
  达成一个目标、换了新形象、登录、额度用完时（间隔七天，每台手机最多四次），以钉在标题下
  的卡片出现（消息列表是一个 UICollectionView，所以没法在最后一条消息下面放东西）；卡片
  里那句话，运营者在中继控制台设了（`star.text`，中文界面优先取 `star.text_zh`）就用设的，
  没设就用应用自己为那个时机写的；标题和按钮始终是应用的。动态
  打开时先是介绍卡片，空着的时候说明每日例程什么时候跑，第一次对话之后写下它的第一天；
  引导里加了一页通知。
- **输入区（0.1.38、0.1.40）**（`NanoMuseShell.swift` → `NanoMuseHomeView.body`、
  `NanoMuseChatModifiers.swift`、`NanoMuseComposerField.swift`、`NanoMuseComposerWatch.swift`、
  `NanoMuseComposerCheck.swift`，以及 `Views/Chat/AIChatView.swift` 里的那些 `// nanoMuse:` 行）。
  有四个版本报告过聊天里没有输入框（0.1.36 和 0.1.37 在维护者的 iPhone 上，第一次对话起名
  之后；0.1.39 在 iPad 上），而 0.1.37 的看门狗、0.1.38 的原生输入框和 0.1.38 的保险措施
  （overlay 什么都报不出来时启用第二个宿主）都是对着截图写的，而截图里的输入区其实一直在。
  维护者最后看到的是：App 打开时输入框在，键盘一收起就再也不见；0.1.36 的截图里，输入区的
  上边缘从底栏上方露出来一点。外壳的底栏是 `NavigationStack` 祖先上的一个 `safeAreaInset`，
  键盘弹起时隐藏；聊天在启动时尊重这个 inset，底栏离开又回来之后就不再尊重，于是整个聊天
  都跑到底栏下面去了，而输入区（贴底对齐、布局完成、按看门狗的每一项指标都正常）正好
  躲在底栏后面。从 0.1.40 起，**底栏绝不做聊天祖先上的 inset**（0.1.40 是一个 `VStack`
  的一行；从悬浮胶囊栏到 1.0.3，是聊天层上一段底栏高度的底部 padding；之后底栏高度作为环境值
  `nmBottomOverlay` 传进聊天，聊天把输入区抬高这么多）。0.1.40 到 1.0.3 之间，输入区这一列
  （卡片、工具条、输入栏）是一个变矮的消息列表下面的一行，胶囊栏的玻璃后面只剩一片空白画布；
  **从 1.0.4 起这一列重新盖在列表的底边上**：`NanoMuseComposerHost` 是一个 `ZStack`，列表保持
  聊天的整个高度，拿到的底部 inset 是这一列量出的高度加底栏，于是消息从输入区和底栏下面滚过，
  静止时最后一条停在输入区上方；`/` 和 `@` 的弹出菜单和这一列同在一个 `VStack` 里，所以从布局上
  就站在它的上边缘。输入框胶囊背后是与 Android 对齐的圆角渐隐光晕（`NanoMuseComposerVignette`）：
  列表一离开最新一条，就沿着输入框胶囊 26 pt 的圆角轮廓升起一段 90 pt 的画布色圆角渐变，并在底栏
  上方的间隙淡出为透明，不留整宽的不透明白色长方形条，好让底栏玻璃留住它后面的消息。
  没有第二个宿主可切换。看门狗作为最后一道网留着（聊天在屏幕上时，这一列脱离或者量出 0，就通过
  `.id(rebuildTick)` 重建，每次出现最多两次，这样一个量错了的健康输入区不会反复把键盘收走），
  并且把看到的都记下来：**设置 → 外观 → 输入框检查** 在这一列四周画一个红框（探针视图在
  它的背景里）并写一份报告（窗口和它的安全区、这一列的 frame、探针的每个 UIKit 祖先及其
  frame、hidden 标志和 alpha、窗口里的文本框和集合视图、看门狗的事件），附一行 *复制*，方便
  提 bug。这一页就是一台设备在没有 Mac 的情况下能给出的视图层级。胶囊里的输入框是 SwiftUI
  自己的 `TextField(axis: .vertical)`，带 `@FocusState` 和 `lineLimit(1...6)`，不是上游的
  `UIViewRepresentable` 文本视图。representable 能做而原生输入框不能做的：直接把图片粘进输入框
  （剪贴板里有图片时，加号菜单里有 *粘贴图片*）、给纠错学习器用的选中替换捕获、`@` 菜单的
  精确光标位置（现在是文本末尾）、估计超过六行的文本上的滑动发送，以及 iOS 16 上用硬件键盘的
  方向键 / Tab 在弹出菜单里导航（iOS 17 及以后通过 `onKeyPress` 有）。硬件键盘上回车发送，
  Shift+回车换行，屏幕键盘的回车跟随 *设置 → 外观 → 回车发送*；听写结束时仍是 *回到键盘输入*。
- **启动画面（0.1.38）**（`NanoMuse/NanoMuseLaunch.storyboard`、`NanoMuse/NanoMuseLaunch.xcassets`）：
  系统背景上的标志，没有文字，浅色和深色各一套。上游的 storyboard 留在源码树里；
  `scripts/rebrand.py` 把 `INFOPLIST_KEY_UILaunchStoryboardName` 指向我们的。iOS 按安装缓存
  启动画面：更新之后旧的可能还会出现几次，重装则立刻显示新的。
- **旁聊和在线状态（0.1.38，契约 C9）**（`NanoMuseSync.swift`、`NanoMusePresence.swift`、
  `NanoMuseSyncSettings.swift`、`NanoMuseFromDeviceCaption.swift`）：*数据控制 → 同时同步旁聊*
  是按设备的，默认关：只有主要聊天上传，拉取时带 `scope=main`；仍然到达的旁聊行会被忽略。
  打开它会从 `since=0&scope=all&tail=300` 拉一次（按 `mid` 幂等），旁聊随下一次推送上传；
  关掉只是把流量收窄，不删任何东西。一张表的第一次拉取是 `since=0&tail=300`：最新的 300 条
  文本，不是整个历史。在线状态：用户那一行推送之后、回合结束推送之后各 `POST /v1/sync/working
  {cid, working}` 一次；hub 的 `working` 帧和 `/v1/sync/state` 的 `working` 列表填进一张
  十分钟过期的映射表，最后一条消息是另一台设备的用户行时，聊天在它下面显示 *〈设备〉正在处理…*
  （`ChatMessage.nmWorkingDevice` 存的是整句话；帧带着 `state` 和 `detail` 时，中继 0.31，读作
  *〈设备〉正在处理：〈这一步〉* 或 *〈设备〉在等你确认*，`NanoMusePresence.sentence`）。排在末尾的远端用户行绝不会被当成这台手机被打断的回合：
  `recheckCanResumeFromHistory` 对它不开 `canResume`，所以没有横幅、没有「继续」、什么也不重发。
- **登录和中继（0.1.38）**（`NanoMuseCloud.swift`、`NanoMuseCloudView.swift`、
  `NanoMuseRelayPicker.swift`）：国家代码不是 +86 的手机号在请求验证码之前就会被告知
  *短信验证码只能发到中国大陆号码。请改用电子邮箱。*，中继的 `phone_region` 错误也是同一句。
  登录页上的 *使用其他服务器* 打开一个面板：地址、*检查*（`GET /healthz`）、*使用此服务器*；
  除非主机在自己的网络里，否则必须是 https；判断用的是代理绕行也在用的同一条规则
  （`NanoMuseProxy.isLocal`，对应 Android 的 `LanOnly`）：地址先解析再判断，所以
  `10.foo.example.com` 是公网名字；私有网段、Tailscale 分配的 `100.64/10`、回环、链路本地、
  IPv6 ULA、`localhost`、不带点的名字，以及 `.local`、`.lan`、`.home`、`.internal`、`.home.arpa`、
  `.localdomain`、`.ts.net` 后缀都算自己的网络。登录后，账号页显示 *服务器：〈主机〉* 和 *更换*，更换会先让这台手机退出
  登录：key 属于签发它的那个中继。
- **一个账号的对话，不是上一个人的（0.1.39，契约 C10）**（`NanoMuseSync.swift`、
  `NanoMuseShell.swift`）：一个对话属于最先推送或拉取它的那个账号：映射它的同步表是那个
  账号的，每个在这台手机上同步过的账号都保留自己的表（`nanomuse-sync-accounts.json`，以中继
  的不透明 `account.id` 为键，从不用手机号或邮箱）。登录后，聊天列表和「聊天」标签页显示这个
  账号自己的对话，以及还没有任何账号同步过的对话；别的账号的留在手机上，隐藏，绝不会以当前
  登录的账号推送出去；一个没有归属的对话在第一次推送时归入这个账号。换一个账号登录会把
  这个账号的游标从头开始（`tail=300` 那次拉取）并忘掉在线状态；再以第一个账号登录，它的对话
  和主要聊天都回来。退出登录后，手机上的一切都显示，什么也不动。智能体的名字和外观已经跟着
  账号走；本地的记忆文件还没有。
- **一个账号的东西不留给下一个（0.1.40，契约 C12）**（`NanoMuseAccountData.swift`、
  `NanoMuseSignOutSheet.swift`）：每个聊天都有一条归属记录（`nanomuse-owners.json`），不管
  同步没同步，列表、「聊天」标签页、资源库、*今天的对话*、Siri 快捷指令和推送都只显示当前
  登录者的；退出登录后，只显示退出状态下创建的聊天。退出登录（在这里、在任何地方、*使用
  其他服务器*）是一个带一个开关的面板，*把这个账号的聊天留在这台设备上*，默认关：关着，
  这个账号的聊天、记忆、动态、目标、例程和形象都离开手机（它的同步表也一起，这样之后的登录
  绝不会在它的其他设备上留下墓碑）；开着，它们被收到 `MinisConfig/nanomuse/accounts/<hash>/`
  下面，随账号回来。换另一个账号登录走的是同一条路。*删除账号* 把这一切全部移除，不再多问。
  刷新时被中继拒绝的 key（`401 bad_key`：从另一台设备撤销、中继重置）走的是 *保留* 这条路：
  数据收起来，key 删掉，登录表单显示 *这台手机上的登录已结束，重新登录即可继续；在那之前，
  你的聊天会留在这台设备上*，直到下一次登录（`NanoMuseCloud.signInEnded`）；只有
  `401 account_deleted` 才删除（`NanoMuseAccountData.keepOnRefusedKey`，在
  `NanoMuseAccountsTests` 里有测试）。中继的 key 只存在这台设备上
  （`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`，从不进 iCloud 钥匙串）；没有标记、
  没有服务商、没有聊天的全新安装会清掉上一次安装留下的仅限本机的钥匙串条目。完整的表格
  在 [sync.md](sync.md)。
- **审计里的小事（第 9 轮）**（`NanoMuseCloudView.swift`、`NanoMuseFirstRun.swift`、
  `NanoMuseAvatarFlow.swift`、`NanoMuseDevicesSection.swift`、`NanoMuseShell.swift`）：登录面板
  打开时输入框上方是 App 的标志，输入框写着*中国大陆手机号或邮箱*，输入其他国家区号的号码时，
  *短信验证码只发中国大陆号码……*一边输一边就出现在输入框下面，而不是点了之后才出现；脚注用
  Android 的那段小字（中继保存什么：账号 id、一个打码的标识、用量计数、智能体的名字和形象），
  链到隐私政策而不是 GitHub 页面。首次运行的「通知」页显示标志，和欢迎页、登录页一样。设了
  视频模型时选了新形象之后，回复会说四段短片随后在后台生成（Android 的那句话）。账号的设备
  列表里，离线设备显示最后一次在线的时间，点一台在线设备会打开主聊天并在输入框里填好
  `@〈名字〉 `（Reach 面板的*问这台设备*）。`NanoMuseRoot` 在知道是否需要引导之前什么都不画，
  所以全新安装绝不会在欢迎页之前闪过一帧主界面。第一次对话的第四句话不再说消息*只*发给
  模型：登录后，主对话也会跟着人到他的其他设备上，*数据控制*可以关掉，和 Android 同样的
  话，每种语言都有。
- **审计第二轮（第 10 轮）**（`NanoMuseHub.swift`、`NanoMuseDevicesSection.swift`、
  `NanoMuseScheduler.swift`、`NanoMuseSync.swift`、`NanoMuseAccountData.swift`、
  `NanoMuseProxy.swift`、`NanoMuseImageGen.swift`、`NanoMuseVideoGen.swift`）：hub 客户端会读
  中继的关闭码（[hub.md](hub.md)）：4001、4002 之后不再重试，直到重新登录，设备一行显示
  *重新登录*；4003 等 30 秒；带 `hub_paused` 原因的关闭等两分钟，一行显示*中转已暂停*；其余
  情况保持 1 → 30 秒的退避，显示*正在重新连接…*。其他设备发来的 `open` 只打开 `http` 和
  `https` 链接，`tel:` 或别的 App 的 scheme 会以 `usage` 拒绝；一次调用的超时计时器随答复
  一起结束。在当天时间点之后创建的一次性例程会在第二天运行，而不是永远不跑。同步侧表
  （`nanomuse-sync-accounts.json`、`nanomuse-owners.json`）和聊天本身一样用默认的数据保护
  等级；文件在但读不出来时（手机锁着、App 在后台被唤醒），存储等下一次调用再读，而不是从
  空表开始并把空表写回去覆盖每个账号的记录。图片和视频生成和同一服务商的聊天一样走
  「网络」里的代理（`NanoMuseProxy.SessionSlot`），失败时是每种语言都有的整句，*服务商拒绝了
  这把密钥（HTTP 401）*、*视频超过 12 分钟仍未完成*，服务商自己的话跟在「服务商说：」后面。
- **审计第三遍（第 11 轮）**（`NanoMuseHubTasks.swift`、`NanoMuseHub.swift`）：其他设备发来的
  `stop` 既能按任务帧的 id 找到这次运行（`stop {call}`，桌面端发的就是这个），也能按会话找；
  只有发起任务的设备能停它；停下之后任务按 [hub.md](hub.md) 的约定答 `cancelled`。socket
  还开着时中继针对某一帧发来的 `error`（`too_large`、`rate_limited`、`bad_frame`）只记日志，
  「设备」一行继续显示*已连接*，不再把中继的句子挂到下次重连为止。头部的名字和状态两行
  （`NanoMuseNamePill`、`NanoMuseHeaderTitle`）以及为名牌预留的高度跟随「动态字体」放大，
  最多到基准的 1.35 倍（`NanoMuseHeaderMetrics`）；侧边抽屉按所在窗口量宽度（`GeometryReader`）
  而不是 `UIScreen.main`，iPad 上比屏幕窄的窗口也能放得下；模型选择页的每一行带「已选中」
  特征给 VoiceOver，勾号不再被读成符号名。
- **审计的文案与排版（第 10 轮）**（`NanoMuseChrome.swift`、`NanoMuseFirstRun.swift`、
  `NanoMuseProviderReachCard.swift`、`NanoMuseSystemFiles.swift`、`*.lproj/InfoPlist.strings`、
  `Localizable.xcstrings`）：`NanoMuseFlowLayout` 是一个会换行的横排（iOS 16 的 `Layout`），
  第一次对话里的名字候选和服务商卡片下的按钮都放在里面，四个名字或者*重试 · 这次改用
  nanoMuse Cloud · 网络设置 · 添加自己的 key*在 iPhone SE 和大字号下也放得下，不会在右边
  被切掉；设置页的小字是一段话，*了解更多*在段尾。NFC、蓝牙和面容 ID 的权限说明有了全部
  九种语言（之前回退到 `Info.plist` 的英文），本地网络的说明讲的是这个 App，不是虚拟机。
  简体中文里中继统一叫 *nanoMuse Cloud*，和句子里指向的那一行设置同名（之前 16 处写的是
  *nanoMuse 云*或*nanoMuse 云端*）。HEARTBEAT.md 里每条例程的节奏用例程列表的词
  （*每天 · 08:00*、*每 6 小时检查*），不再是英文的 *daily*、*once*、*every 6 h*；记忆导入的
  提示词跟随 App 内的语言切换。
- **审计的后续（第 11 轮）**（`Localizable.xcstrings`、`NanoMuseVendorSheet.swift`、
  `NanoMuseFeed.swift`、`NanoMuseAppearance.swift`、`OpenAIProvider.swift` 里的 `// nanoMuse:`
  改动点、`MinisTests/NanoMuseCopyTests.swift`）：人读到的句子里不再有破折号，九种语言都是：
  73 个 key 改写成两句话、逗号、冒号或间隔号（*开始之前，我该怎么称呼你？*、*Sign in · free*、
  *Done. My new look is on.*），HEARTBEAT.md 的行和诊断报告也一并改了，十个没人再引用的 key
  删掉了；上游 OpenMinis 的 key 不是我们的，原样保留。繁體中文也和其他语言一样写
  *nanoMuse Cloud*，俄语用 *Эл. почта*。`NanoMuseCopyTests` 在 Mac 上读目录和 `NanoMuse/`
  源码，我们的 key 里出现破折号、感叹号或翻译过的中继名就失败。服务商表单在保存 key 之前先拿它
  去取服务商的模型列表：401 或 403 时手机保持原样，并在输入框下面说明原因；之前上游的回退会
  填入一份目录里的模型列表，表单像 key 正确一样关闭。订阅的 429 带的 `Retry-After` 现在会传到
  可达性卡片，ChatGPT 或 Claude 订阅也能看到「……后重置」。动态详情的几行是一个 `Grid`，标签列
  按最长的标签取宽；形象大小改成菜单，不再是五段分段控件。
- **第三轮审计：版本行（1.0.x）**（`NanoMuseUpdateCheck.swift`、
  `MinisTests/NanoMuseLogicTests.swift`）：`nanomuse.cn/dl/index.json` 的形状是
  `{"releases": [{"tag": "v1.0.0", …}, …]}`，最新的在前，版本行现在就读这个，和 Android 的
  `UpdateCheck.parseIndex` 一样；之前它找的 `ios.version`、`latest` 从来没有写进过索引，所以
  连不上 GitHub 的手机上这一行永远是*没查到*。从索引查到的版本点开去 `nanomuse.cn/dl/`，从
  GitHub 查到的去它的发布页。`parseIndex` 和 `parseGitHubLatest` 是纯函数，有测试。
- **第三轮审计：登录表单（1.0.x）**（`NanoMuseFirstRun.swift`）：欢迎页的 *Sign in · free*
  以浮层打开账号页；验证码或密码通过后，浮层自己关上（对登录状态做 `nmOnChange`），引导已经
  翻到下一页，密码页或来源页。之前浮层停在登录后的账号页上，带着设备和同步那几行，人得把它
  滑掉才发现引导已经往前走了。
- **第三轮审计：中文用词（1.0.x）**（`Localizable.xcstrings`、`NanoMuseShell.swift`、
  `NanoMuseAccountView.swift`、`MinisTests/NanoMuseCopyTests.swift`）：中文文案和 Android 说
  一样的词。19 个 key 里还写着英文 "agent" 或「代理」的地方（系统文件的说明、例程、*关于这个
  智能体*、形象失败那句）改成智能体（繁體 智慧體），「代理」在「设置 → 网络」里是代理服务器的
  意思；七句说「中转」的中继句子（*中继说*、*中继已暂停*、暂停注册、额度、同步、互联、私人
  中继）改成中继 / 中繼；*Hands* 保留英文，和 Android 的「设置 → Hands」一致；聊天标签有了
  自己的 key `tab.chat`（聊天，Android 的 `nm_tab_chat`），不再用上游的 *Chat*（闲聊）；账号页
  的用量行里对话类写「对话」（`models.slot.chat`，Android 的 `nm_usage_kind_chat`）。
  `NanoMuseCopyTests` 遇到中文里的 "agent"、英文原文说 agent 处的「代理」、「中转」和「双手」
  就失败。
- **第三轮审计：来自其他设备的任务（1.0.x）**（`NanoMuseHubTasks.swift`、
  `MinisTests/NanoMuseHubTasksTests.swift`）：`task` 帧带着发起设备的界面语言（`language`，
  见 [hub.md](hub.md)）；iPhone 的 Muse 现在被要求用这个语言回答，之前只看文字本身，所以在
  英文桌面上对一个中文网页输入 `@iPhone` 的人会得到英文回答。`NanoMuseHubTasks.prompt`
  是纯函数，有测试。手机自己发出的 `@设备` 提及从 1.0.0 起就带这个标签。
- **第三轮审计：Cloud 开关与对话（1.0.x）**（`NanoMuseModelSlots.swift`、`NanoMuseCloud.swift`、
  `NanoMuseModelsView.swift`、`ProviderInstanceDetailView.swift` 里的 `// nanoMuse:` 改动点、
  `MinisTests/NanoMuseModelSlotsTests.swift`）：新对话还由账号回答时关掉*使用 nanoMuse Cloud
  模型*（设置 › 模型，或 Cloud 服务商自己页面上的*已启用*），对话槽和主要聊天会交给第一个能对话
  的自有服务商，用目录里它的默认模型（`NanoMuseSlotResolver.nextChat`，对应 Android 的
  `ModelSlots.nextChat`；`NanoMuseModelSlots.chatLeaves` 经 `useForChat` 完成切换）。没有自有
  对话模型时开关被拒绝：`NanoMuseCloud.setModelsOn` 返回 false，开关保持打开，开关下面出现
  *先添加一个自己的服务商；关掉 nanoMuse Cloud 后没有别的模型能回答。*，模型页在卡片内，服务商
  页在「状态」一节的脚注。之前开关会关掉，对话那一行仍写着账号，主要聊天停在上游的*未配置模型*
  错误上；现在经这个开关到不了*未设置*的状态。自有服务商在自己页面上关掉仍走上游的路：对话经
  默认分组重新解析，什么都不剩时说*未配置模型。请在设置中添加服务商。*
- **底栏是一个悬浮的胶囊**（`NanoMuseShell.swift` → `NanoMuseBottomBar`，`NanoMuseFaces.swift`
  里的 `NanoMuseTones.tabIndicator` / `tabIndicatorGlyph`；对应 Android 的 `MuseBottomBar`，
  @Ichiro786 的 #329）：五个标签放在一个 `Capsule` 里，离底部安全区 12 pt，和上方的输入框
  一样宽（同样的 16 pt 边距；compact 宽度下最宽 420 pt，没有哪部手机碰得到；regular 宽度，也就是
  iPad 上，它和输入框一样是聊天列减去边距的 728 pt，见下面关于列的那条），只有图标，
  五个标签图形与 Android 的 `MuseBottomBar` 对齐（`bubble.left`、`doc.text`、`lightbulb`、
  `checkmark.square`，以及资料库的三几何图形 `Category`），无障碍标签和选中特征都和以前一样。胶囊是 `.ultraThinMaterial`，上面盖一层 55%
  不透明度的外壳 surface 色（对比度靠这层色，模糊靠材质，和 Android 在背景模糊上盖 55% surface
  一样），边上一道 1 pt 的 `NanoMuseTones.hairline`；原来那条通栏的条和它顶上的细线没有了。
  五个标签平分胶囊的宽度，每一格整格可点；当前这个用 `tabIndicatorGlyph` 色显示实心符号，底下一个
  60 × 46 pt 的 `tabIndicator` 色胶囊（聊天的墨色：浅色黑底白符号，深色白底黑符号，和 Android 的
  `MuseBottomBar` 一样），点下一个标签时它带着弹簧滑过去
  （`matchedGeometryEffect`；开了「减弱动态效果」就不带弹簧，直接过去）；其他标签用次要颜色显示线框符号。键盘弹起或聊天的语音面板打开时，
  底栏仍然离开。布局：胶囊在一个贴底对齐的 `ZStack` 里盖在房间和聊天上面。聊天拿到底栏的
  高度（70 pt：46 加上下各 6，再加 12 pt 的间隙）作为环境值 `nmBottomOverlay`，把输入区抬高这么多，
  消息从输入区和底栏下面滚过（见上面输入区那条）；`NavigationStack` 的祖先上没有任何 inset。
  房间是普通的 SwiftUI 滚动视图，同样的高度用 `safeAreaInset` 给出。两种情况下玻璃后面都有
  对话或房间可以模糊；1.0.3 之前聊天是垫在底栏上方的，玻璃后面只有空白画布，胶囊看上去就是一块
  白的（1.0.3 在 iPad 上看到的样子）。
- **聊天是单色的**（`NanoMuseFaces.swift` 里的 `NanoMuseTones.ink` / `onInk` / `agentPill`，
  `NanoMuseHeader.swift` 里的 `NanoMuseHeaderScrim`，`NanoMuseComposer.swift`，
  `NanoMuseChatCards.swift`，以及 `Views/Chat/ChatMessageViews.swift` 和
  `Views/Chat/AIChatView.swift` 里的 `// nanoMuse:` 行；对应 Android 的 #331，@Ichiro786）。开着
  Muse 外壳时，你的消息是墨色的胶囊，文字用画布色：浅色主题下白色画布上是黑胶囊白字，深色主题下
  黑色画布上是白胶囊黑字，没有蓝也没有灰。智能体的回复放在一个比
  画布深一点或浅一点的胶囊里，浅色 `#F2F2F7`，深色 `#1C1C1E`，文字用主题的文字色；代码、表格和
  原始标记照旧不加胶囊。输入胶囊里的发送箭头是同一种墨色的 30 pt 圆盘，箭头用画布色（没有可发
  的内容时圆盘是一层淡淡的墨色，箭头 40%），智能体回答时的停止方块也在同一个圆盘上；输入胶囊
  本身还是灰的。列表下面*回到最新*的圆盘也是
  同一种墨色，箭头用画布色；它上面那颗往回走的按钮保留浅色圆盘。主聊天上方的标题栏不再是模糊
  层：一层画布色的渐变遮罩，顶边 80%，过半一点 35%，到底部透明，于是对话会滚到形象下面并融进
  画布，而不是停在一条线上；列表滚离最新消息时，再从顶边以 250 ms 淡入一层完整画布色的渐变
  （外壳 `safeAreaInset` 的背景，像标题栏绑定心情那样绑定主聊天的 `isNearBottom`）。排队中的消息
  保留上游的虚线边框和灰字，*来自 {设备}* 的说明和附件都在胶囊外面，长按预览还是原来那张不透明
  的卡片。从抽屉推出的侧聊天保留系统栏，为了返回按钮和标题，但从 1.0.4 起栏自己的背景和
  细线都藏起来，后面站着同一层遮罩（`AIChatView.swift` 里的 `NavBarStyleModifier`，由外壳
  给推出的聊天设置的环境值 `nmSystemBarScrim` 打开；1.0.3 之前栏坐在 `.ultraThinMaterial`
  上）。房间从 1.0.4 起站在聊天的画布上，白色和黑色，和 Android 的各个标签页及
  [design.md](design.md) 一致：想法是每行下面一道细线的平铺行，目标的卡片描一道细线边，
  资料库是平铺列表；只有动态还保留它白卡片所在的那页灰底，和 Android 的 FeedTab 一样。
  在没有 Mac 的 Linux 上写的：iOS 检查能编译它，还没有设备显示过它。
- **iPad 的聊天是一根列**（`NanoMuseShell.swift` 里的 `NanoMuseColumn`；`AIChatView.swift` 里的
  `maxContentWidth` 一行和输入框的 frame，`NanoMuseChatCards.swift` 里智能体的胶囊）。1.0.3 在竖屏的
  iPad 上显示出三种宽度：上游在 regular 宽度下把消息列表和输入框限到 900 pt，于是输入框横贯 768 pt
  的窗口，底栏胶囊在它下面只有 420 pt 宽，智能体的回复还留在左边 340 pt 的胶囊里。现在在 regular
  宽度的 size class 下，列表、输入框和底栏胶囊共用一根居中的 760 pt 的列，即网页控制台的聊天列
  （`max-w-[760px]`）；行在列里保留 16 pt 的内边距，输入框和底栏胶囊都是列宽减去边距的 728 pt，
  于是它们的边和气泡的边、和彼此的边对齐，智能体的胶囊放宽到 600 pt，即网页宽布局的值。compact
  宽度，也就是每一部 iPhone 和窄的分屏窗格，没有变化。消息列表的单元格由 `UIHostingConfiguration`
  承载，它不传我们的 environment object，但会从单元格的 traits 传 size class；智能体的胶囊从那里
  读它。1.0.4 里只有智能体的行把内边距加在列的外面，于是它的胶囊比输入框的边往左多出
  16 pt；`CollectionViewMessageListV3.swift` 里的三个智能体单元格（头部、块、尾部）现在和用户的行
  一样把内边距放在列里面。
- **行会滚到标题栏下面。** 外壳量出 Muse 标题栏的高度，作为环境值 `nmTopOverlay` 交给聊天
  （`NanoMuseChatModifiers.swift`）；消息列表在顶部忽略容器的安全区，再把行往下留出这么多
  （`CollectionViewMessageListV3` 的 `topOverlay`，加进 `contentInset.top`），就像它已经在输入框和
  底栏胶囊下面延伸那样。于是行会滚到形象下面，被标题栏后面的遮罩淡化，和 Android 一样。1.0.3 和
  1.0.4 只把标题栏做成了 `safeAreaInset`，这对 SwiftUI 的 `ScrollView` 够用，却会把一个 UIKit 视图
  缩短：列表止于标题栏下面，行在那里被一条硬边切断，遮罩什么也没淡化。从抽屉推出的侧聊天保留
  系统栏，这个值是 0，它改为像上游 iOS 26 的布局那样把内容一直延伸到系统栏下面
  （`NavBarStyleModifier`）；系统栏是 UIKit 的，列表自己的内边距调整会让第一行停在栏下面，它的行
  也会在栏后面的遮罩里淡化。
- **动态静静地写，例程先开口**（`NanoMuseRoutineWakes.swift`；`NanoMuseSync.shows`、
  `NanoMuseHeadless.run`，以及 `ChatModels.swift`、`AIChatViewModel.swift`、
  `AIChatViewModel+Persistence.swift`、`ChatMessageViews.swift` 里的 `nmRoutine` 改动处）。到 1.0.4
  为止，每日动态是抽屉里一个叫「动态」的会话，里面有一条以本人口吻发出的「写今天的动态。」气泡，
  下面是模型的回答；用户自己建的每条例程也都这样开始一轮。现在动态的会话是智能体的工作间，列表
  不再列出它（`shows` 对它说不，就像对另一个账号的聊天那样）；帖子照旧出现在动态页。例程的一轮
  会被标成例程的：承载提示词的那一行只是一行安静的小字「例程 · 〈名称〉 · 08:00」
  （`NanoMuseRoutineWakeRow`，按行的 id 记住，重新加载后还在），模型则收到一条只管这一轮的附言
  （`NanoMuseSessionAddenda`），说明这不是本人打的字，于是它直接从结果说起，而不是感谢对方的
  提问。提示词本身没有变，这一轮照原样跑。
- **第四轮审计（1.0.x）**（`*.lproj/AppShortcuts.strings`、`NanoMuseChrome.swift`、
  `NanoMuseShell.swift`、`NanoMuseAgentPage.swift`、`NanoMuseHub.swift`、
  `NanoMuseBackgroundSettings.swift`、`Localizable.xcstrings`）：Siri 唤起短语补齐了九种语言
  （此前只有英文和两种中文，日语、韩语、德语、西班牙语、法语、俄语的手机拿到的是英文短语）。
  Muse 页面的标题、抽屉里和智能体页面上的名字跟随「动态字体」放大，和头部两行一样最多到基准的
  1.35 倍（`NanoMuseHeaderMetrics`）；此前固定在 17 pt 和 24 pt。点子上的 *创建例程* 现在真的会
  打开例程编辑器：这张表单改由外壳自己持有；此前是让目标页去打开，而看点子页时目标页并不在
  屏幕上，于是例程按点子的时间建好了，却什么也没弹出来。*后台与通知* 页说的就是手机实际做的事：
  通知要么是例程到点的提醒，要么是另一台设备发来的消息；「后台 App 刷新」只让 iOS 发出提醒，
  从不运行例程（此前写的是 App 会得到时间片把例程做完）。来自 Hub 或电脑的失败（*编程助手*、
  Reach 面板、`@设备` 消息）按 Hub 的错误码变成一句本机语言的话，和 Android 的
  `HubErrors.describe` 一样（`NanoMuseHubErrors`）：*那台电脑不在线。*、*电脑没有及时回应。*、
  *电脑上的 nanoMuse 版本较旧，不认识这个操作。*；此前直接显示中继或运行时发来的英文原句。
  资源库和账号页的分段选择器、目标、例程、动态帖子的 ••• 菜单都带上了 VoiceOver 标签。

## 朗读回复的声音 {#reply-voices}

语音输出选择「系统声音（自动）」时，聊天的系统朗读会按回复的语言，使用「后台与通知」中设置的
中文或英文声音。如果在语音输出中明确选了某个系统声音，则优先使用它。只有当前生效的语音输出
条目决定声音，默认语音输出组中排在后面、尚未启用的条目不会覆盖「自动」。云端语音的选择不变。

## 用操作按钮说一句 {#voice-prompts-from-the-action-button}

*语音提示*是 App 注册的一个快捷指令（`NanoMuse/VoicePromptIntent.swift`）：打开 nanoMuse 并开始
聆听，一句话可以说出来而不用打字。在「快捷指令」App 里绑定一次，放到操作按钮（设置 › 操作按钮 ›
快捷指令）、轻点背面或小组件上；按一下，输入框就进入语音模式、麦克风已在听，说的话一边识别一边
出现在输入框里。发送仍然是点一下发送键：识别错的一句话不能因为一个停顿就让智能体跑起来。快捷
指令带一个可选的*会话*参数；留空时送到当前打开的聊天，在 Muse 布局里就是主要聊天（压在它上面
的侧聊天会先退出）。第一次按会像麦克风按钮一样请求麦克风和语音识别权限；被拒绝时面板里会显示，
什么都不会录。

实现：意图自己驱动不了语音面板（冷启动时它在窗口存在之前就运行，面板归 SwiftUI 管），所以它在
`NanoMuseVoicePrompt` 里留下一个请求，指定了会话时按通知点击的路子跳过去
（`NotificationNavigationStore`、`.openSessionFromIntent`）。聊天的钩子（`NanoMuseChatHooks`）
取走发给自己这个聊天的请求，沿麦克风按钮的路把输入框切到内嵌语音面板，面板出现后再按下它的
麦克风，走 `VoiceInputViewModel.handleMainButtonTap` 和它的权限流程。只有一条录音路径、一套识别
栈；转写文字照常进入 `inputText`。超过 30 秒没人接的请求会被丢弃。iOS 不让 App Intent 接收自由
语音，所以这是一个语音入口，而不是一口气说完的「问 nanoMuse 某件事」；App 之所以要打开，是因为
屏幕上什么都没有而麦克风在转，看起来就像出了故障。Siri 的唤起短语在九张 `AppShortcuts.strings`
表里（每个 `<lang>.lproj` 一张，因为部署目标是 iOS 16 所以用旧式 `.strings`），意图自己的字符串在
`Localizable.xcstrings`（#296、#298）。

## 在 Mac 上构建 {#building-on-a-mac}

要求是上游的，写在 [android/BUILDING.md](../../android/BUILDING.md)：较新的 Xcode（项目用的是
iOS 26 SDK）、Homebrew 的 `ninja meson llvm lld libarchive pkg-config`、给 rclone 用的 Go 1.25。

```bash
git clone --recurse-submodules https://github.com/nano-muse/nanoMuse.git && cd nanoMuse/android
./deps/build_lame.sh && ./deps/build_ffmpeg.sh          # FFmpeg links against LAME: this order
./deps/build_ish.sh && ./deps/prepare_alpine_rootfs.sh  # the sandbox kernel and its rootfs
./deps/build_rclone_ios.sh                              # Rclone.xcframework
cp src/ios/Configs/ProviderCustomization.xcconfig.example src/ios/Configs/ProviderCustomization.xcconfig
open src/ios/Minis.xcodeproj
```

选 **Minis** scheme，在 *Signing & Capabilities* 里设好你的团队（项目里的 `DEVELOPMENT_TEAM`
是空的），面向真机构建：原生库只有真机版本，所以模拟器链接不了；见 BUILDING.md 的故障
排查一节。

聊天屏幕的一条规矩，从 0.1.38 的构建 9 学来的：**不要在 `AIChatView.body` 的修饰符链末尾
再加任何东西。** 这个 body 是一个由大约六十个链式修饰符组成的表达式；它的 getter 把不断
变大的值的副本留在栈上，0.1.38 加的四个环节就足以在 iPad 上、引导结束后聊天一出现的瞬间
撑爆主线程的 1 MB：每次启动都崩，在 `AIChatView.body.getter` →
`__swift_instantiateConcreteTypeFromMangledNameV2`。我们自己的聊天级行为放在
`NanoMuse/NanoMuseChatModifiers.swift`（`NanoMuseChatHooks`、`NanoMuseComposerHost`）里：
往那里加，或者加第三个修饰符，只占一环。输入区那一叠在那里故意用了 `AnyView`。
`MinisTests/NanoMuseRound6Tests.swift` 测量 body 值的大小和类型深度，任一超过上限就失败。

## TestFlight {#testflight}

分发方式是 TestFlight 的**内部测试员**：你加为 App Store Connect 团队用户的那些人（最多
100 个），每个构建处理完几分钟后他们就能拿到，不经 App Review。外部测试组（公开链接，
最多 10,000 名测试员）每个版本要过一次 Apple 的 beta 审核；*nanoMuse Beta* 这个组和它的公开
链接已经有了，每个构建在内部测试员用过之后加进去并提交审核。两种情况下流水线是同一条。

### 现状 {#where-it-stands}

2026-10-03 配置完成，全部在账号持有人的开发者账号（团队 `TN43QYW8K4`）下，没有一样在
仓库里：

- App 记录 *nanoMuse*，iOS，bundle id `io.github.nanomuse.app`，SKU `nanomuse-ios`，
  Apple ID `6818802049`；三个扩展的 bundle id `…app.ShareExtension`、`…app.FileProvider`、
  `…app.AgentWidget`；app group `group.io.github.nanomuse.app` 和 iCloud 容器
  `iCloud.io.github.nanomuse.app`；四个 `.entitlements` 要求的能力（App Groups、带临床记录的
  HealthKit、HomeKit、iCloud/CloudKit、NFC 标签读取、WeatherKit）已在标识符上打开；
- API key *nanoMuse CI*（角色 App Manager）、Apple Distribution 证书
  *Apple Distribution: Guangyi Liu*（有效期至 2027-10-03）和四个 App Store 描述文件
  *nanoMuse App Store*、*nanoMuse ShareExtension App Store*、*nanoMuse FileProvider App Store*、
  *nanoMuse AgentWidget App Store*；
- 下表里的六个仓库 secrets；
- 内部 TestFlight 组 *nanoMuse Core*，自动分发，所以每个处理完的构建会自己到达测试员手里；
  设备列表故意留空（这里没有什么需要设备）；
- **第一个构建**：0.1.31 (2)，2026-10-03 由工作流归档并上传，经 App Store Connect 处理
  （`VALID`，出口合规由 Info.plist 的键回答），正在内部组里做 beta 测试：第一个能从
  TestFlight 装上的东西；
- 外部组需要的测试信息，英文和简体中文各一份：beta App 描述、反馈地址、营销和隐私政策链接，
  以及每个构建的 *What to Test*（没有一处提到别的产品）；外部组 *nanoMuse Beta* 和它的公开
  链接 `https://testflight.apple.com/join/ZHexbDqc`；*Beta App Review Information* 里的 beta
  审核联系人和中继上的一个审核账号；
- **构建 16（1.0.0）** 于 2026-10-09 加进 *nanoMuse Beta* 并提交 Apple 的 beta 审核，已经通过，公开链接装的就是它
  （在那之前链接给的是构建 14，0.1.41）；构建 17 是打标签之后合并的修复加上 1.0.0，只到了内部测试员手里。
  **构建 18（1.0.1）** 于 2026-10-10、**构建 19（1.0.2）** 于 2026-10-11 加进 *nanoMuse Beta* 并提交审核，两个都在 2026-10-12 通过，所以链接装的是构建 19；**构建 22（1.0.3）** 于 2026-10-12、**构建 26（1.0.4）** 于 2026-10-13 提交审核，两个都在 2026-10-13 通过，所以链接装的是构建 26；**构建 28（1.0.5）** 于 2026-10-14 提交审核；**构建 29（1.0.6）** 于 2026-10-24 从 tag `v1.0.6` 上传，先到内部测试员手里，加进 *nanoMuse Beta* 并通过审核后才进公开链接；构建 23、24、25（tag 之后合入修复的 1.0.3）以及 27（同样情况的 1.0.4）只到了内部测试员手里。公开链接只在审核
  通过后才会给出构建，以后每个新版本都要重复这一步（审核按版本进行；已通过版本的后续构建不用再审）。任何通往 App Store 的事
  都没有：这个 App 不上架。

### 在 App Store Connect 里做一次的事 {#once-in-app-store-connect}

1. **App 记录。** *Apps → + → New App*：平台 iOS，名字 nanoMuse，bundle id
   `io.github.nanomuse.app`，一个 SKU。自动签名会注册标识符，但 App 记录本身要手动创建一次。
   列表里没有这个 bundle id 的话，先到 *Certificates, Identifiers & Profiles → Identifiers*
   注册它。
2. **标识符上的能力。** entitlements 要求 App Groups、iCloud（CloudKit）、HealthKit（带临床
   记录）、HomeKit、NFC 标签读取和 WeatherKit。自动签名会自己打开其中大部分；如果第一次归档
   在某项能力上失败，就手动在标识符上启用它，并在那里创建 iCloud 容器
   `iCloud.io.github.nanomuse.app` 和 app group `group.io.github.nanomuse.app`。WeatherKit 还
   要在标识符的 *Services* 标签页里启用。
3. **一把 API key。** *Users and Access → Integrations → App Store Connect API → Team Keys → +*，
   角色 **App Manager**（Developer 不够上传用）。`.p8` 只能下载一次；记下表格上方显示的
   Key ID 和 Issuer ID。
4. **测试员。** *TestFlight → Internal Testing → +*：一个组，以及组里的团队成员。

### 仓库 secrets {#repository-secrets}

| Secret | 是什么 |
|---|---|
| `APP_STORE_CONNECT_KEY_ID` | key 的 ID，10 个字符 |
| `APP_STORE_CONNECT_ISSUER_ID` | issuer ID，一个 UUID |
| `APP_STORE_CONNECT_KEY_P8` | `AuthKey_<ID>.p8` 的全文，从 `-----BEGIN PRIVATE KEY-----` 到末尾 |
| `APPLE_TEAM_ID` | 10 个字符的团队 id（开发者账号里的 *Membership details*） |
| `IOS_DIST_P12_BASE64` | 团队的 *Apple Distribution* 证书连同私钥，一个 `.p12`，base64 成一行 |
| `IOS_DIST_P12_PASSWORD` | 那个 `.p12` 的密码 |

### 证书，以及为什么签名是手动的 {#the-certificate-and-why-signing-is-manual}

Xcode 的自动签名（带 key 的 `-allowProvisioningUpdates`）是最初的方案，但对这样的团队行不通：
归档先用 *iOS App Development* 描述文件签名，导出时才重新签成商店用的，而开发描述文件必须
至少列出一台设备；一个只通过 TestFlight 发布的团队一台也没注册，所以归档停在
*Your team has no devices from which to generate a provisioning profile*。因此 lane 改用商店
自己的材料手动签名，这不需要设备：上面两个 secrets 里的 Apple Distribution 证书，以及四个
*App Store* 描述文件（App 和它的三个扩展），由 `get_provisioning_profile` 在每次运行开始时
用 key 从账号下载，如果它们指向的证书不是钥匙串里的那一个，就在账号里修好。

证书是在没有 Mac 的情况下做的，过期或者 key 丢了可以用同样的办法再做一次（一个团队可以
持有两三个分发证书；到上限了就先在 *Certificates, Identifiers & Profiles → Certificates* 里
吊销旧的）：

```sh
umask 077 && cd ~/.private/apple/dist                                # anywhere outside the repository
openssl genrsa -out dist.key 2048
openssl req -new -key dist.key -out dist.csr -subj "/emailAddress=<account e-mail>/CN=nanoMuse CI distribution/C=CN"
# POST /v1/certificates { certificateType: DISTRIBUTION, csrContent: <dist.csr> } with a JWT signed
# by the API key (the key's role must be App Manager or Admin); save certificateContent, base64, as dist.cer
openssl x509 -inform DER -in dist.cer -out dist.pem
openssl rand -base64 24 | tr -d '\n' > dist.p12.pass
openssl pkcs12 -export -inkey dist.key -in dist.pem -out dist.p12 -passout file:dist.p12.pass   # with OpenSSL 3 add -legacy
base64 -w0 dist.p12 | gh secret set IOS_DIST_P12_BASE64 -R nano-muse/nanoMuse
gh secret set IOS_DIST_P12_PASSWORD -R nano-muse/nanoMuse < dist.p12.pass
```

私钥留在维护者机器上的那个文件夹里（以及 secret 里）；它的任何部分都不进仓库、日志或者
聊天。描述文件是用同一套 API 在账号里创建一次的（`POST /v1/profiles`，类型 `IOS_APP_STORE`，
每个 bundle id 一个，各自指向这张证书）；缺了的话 lane 会重新创建。

### 能编译吗？ {#does-it-compile}

*iOS · build check*（`.github/workflows/ios-check.yml`）在 Mac runner 上关闭签名，面向真机构建
这个 App：不要 Apple 账号，不要 secrets。凡是改到 `android/src/ios/` 的 pull request 都会跑它；
其他情况（改了 `android/deps/` 下的脚本、还没开 pull request 的分支）用 *Actions → iOS · build
check → Run workflow* 手动启动。它和 TestFlight 工作流共用原生依赖的缓存，所以先让它变绿：
一个编译错误在这里只花几分钟，不用浪费一次上传。完整的
`xcodebuild` 日志附在运行记录上。`NanoMuse/` 下的文件只要报出一个警告，这次运行就算失败
（上游的文件不算），所以上面「零警告」的规矩是被检查的，不只是写在这里。

字符串目录另有一项检查，每个 pull request 都在 Linux 上跑：`tests/test_ios_strings.py` 逐对键值
解析 `Localizable.xcstrings`，同一个键出现两次就失败（JSON 解析器会悄悄留下其中一条、丢掉另一条，
Xcode 也一样，于是真正打进包里的翻译取决于哪一条赢了）。

### 跑起来 {#running-it}

*Actions → iOS · TestFlight → Run workflow*，或者推一个 `ios-<anything>` 标签。任务会构建原生
依赖（按脚本和 iSH 修订缓存；第一次跑大约一小时，之后几分钟加上归档的时间），用
`fastlane beta`（`android/src/ios/fastlane/Fastfile`）归档，上传，并把 `.ipa` 和 dSYM 附在
运行记录上。构建号就是工作流的运行编号，所以每次上传都比上一次新；版本是项目里的
`MARKETING_VERSION`。Info.plist 里的 `ITSAppUsesNonExemptEncryption` 已经是 `false`，所以
构建不会卡在出口合规问题上。

runner 是 `macos-26`；你的 GitHub 套餐里没有这个标签的话，退路是 `macos-15` 加
`xcode-version: latest-stable`，代价是没有项目要求的 iOS 26 SDK。

## 接下来 {#what-follows}

nanoMuse 的样子长在 Android App 里；从 0.1.34 起，iPhone 在 OpenMinis 之上有了同样的样子
（智能体的页面、从聊天里换形象、目标、动态、例程、第一次打开），文案里写明了 iOS 对后台
工作的限制。Android 代码在哪里，到了这里变成了什么：

| Android（`io.github.nanomuse.*`） | iOS 上 |
|---|---|
| `cloud`：中继客户端、登录、账号 | 已完成：`NanoMuse/NanoMuseCloud*.swift`、`NanoMuseAccount*.swift`（0.1.32：密码、邀请码、以元计的额度、用量、会话、时间线、删除） |
| `ui.onboarding`：带 *登录，免费开始* 的引导 | 已完成（0.1.34）：`NanoMuseFirstRun.swift`，含第一次对话；0.1.35 加了通知页；iOS 上没有「手」那一页 |
| `community.StarPrompt`、`community.Nudges`：按中继策略的 star 提示 | 已完成（0.1.35）：`NanoMuseNudges.swift`、`NanoMuseStar`（时机、冷却和上限来自 `/v1/nudges`） |
| `community.UpdateCheck`、版本行 | 已完成（0.1.35）：`NanoMuseUpdateCheck.swift`（已安装和最新，先 `nanomuse.cn/dl/index.json` 再 GitHub） |
| `avatar.VideoGen`、`avatar.AvatarMotion`：动作短视频 | 已完成（0.1.35）：`NanoMuseVideoGen.swift`、`NanoMuseAvatarMotion.swift`、`NanoMuseMediaModels.swift` |
| `nm.show_steps`：智能体的步骤，从 0.1.37 起默认显示 | 0.1.32：`NanoMuseSteps.swift`；已完成的消息只留对话本身，重置主对话或启动时恢复后也一样；正在进行的那条显示它的步骤 |
| `connectors`：目录、`SharedConnectors` | 已完成：`NanoMuseConnectors.swift`（0.1.33 目录，0.1.34 其他设备的条目） |
| `ui.home`、`ui.chat`、`ui.settings`、`ui.profile`：外壳、标题栏、智能体页面 | 已完成：`NanoMuseShell.swift`、`NanoMuseHeader.swift`、`NanoMuseAgentPage.swift`、`NanoMuseSettings.swift`；0.1.35 每个房间都有 Muse 标题栏，设置做成 Muse 卡片（`NanoMuseChrome.swift`、`NanoMuseAppearance.swift`） |
| `avatar`：画出来的脸、从聊天里换、工作室 | 已完成（0.1.34）：`NanoMuseAvatarFlow.swift`、`NanoMuseAvatarStudio.swift`、`NanoMuseImageGen.swift` |
| `goals`、`feed`、调度器 | 已完成（0.1.34），到 iOS 允许的程度：前台补跑、`BGAppRefreshTask`、本地通知。App 睡着时没有闹钟级的准点运行；文案里写明了 |
| `coding`：通过 hub 访问电脑上的编程助手 | 已完成（0.1.34）：`NanoMuseCoding.swift`；电脑上要跑着用同一个账号登录的 nanoMuse |
| `reach`：手机操控电脑 | 已完成：`NanoMuseReach.swift`，通过 hub |
| `hands`：手机自己的屏幕 | 没有对应物：iOS 不允许一个 App 操控另一个。App Intents / 快捷指令是那里的门 |
| 小组件 | 上游的 `AgentWidget` 原样 |

还要在真机上验证的，按顺序：用新账号从头到尾走一遍第一次打开；确认托管账号的媒体入口会
引导配置自己的服务商，再通过百炼 key 做一次从聊天里换形象，以及随后画出的四段短视频；App 在后台时一条例程到期（测试员的
手机上 iOS 批不批刷新，多久批一次）；对账号下一台电脑的编程会话；第二台设备登录后的
连接器列表。

不在计划里：App Store。TestFlight 就是分发方式：内部测试组，以及某个版本通过 Apple 的 beta
审核之后的公开链接。
