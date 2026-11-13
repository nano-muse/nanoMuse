# iOS

iPhone 版 nanoMuse 基于 OpenMinis 1.13 的 iOS 代码，采用 nanoMuse 的名称和设计。CI（自动构建与检查流程）在 Mac 执行器上构建，再上传到 TestFlight（Apple 的应用测试分发服务）。本页介绍源码位置、构建方法、TestFlight 配置，以及 Android 功能的移植情况。

**发布状态**。 源码、品牌调整、nanoMuse Cloud 登录、hub（设备互联）客户端和发布流程最初都在 Linux 上编写。App 已完成构建、签名并通过 TestFlight 分发。首个版本 0.1.31 (2) 于 2026-10-03 通过「iOS · TestFlight」工作流发布。1.0.0 构建 16 通过 Apple 测试审核后，公开链接 `https://testflight.apple.com/join/ZHexbDqc` 首次可安装它。1.0.1 构建 18、1.0.2 构建 19 在 2026-10-12 通过审核；1.0.3 构建 22、1.0.4 构建 26 在 2026-10-13 通过，因此本文记录的公开链接安装版本为构建 26。1.0.5 构建 28 于 2026-10-14 提审，1.0.6 构建 29 由 `v1.0.6` 标签构建，于 2026-10-24 上传，详见下文发布进展。构建 20、21（1.0.2），23、24、25（标签后合入修复的 1.0.3），27（同类 1.0.4）仅供内部测试。测试反馈促成了输入框、首次引导、退出登录等修复；设备列表与远端通知的真机测试仍相对较少。首次归档发现自动签名要求注册设备，因此目前采用手动签名。

## 源码位置 {#where-it-lives}

`android/` 通过 `git subtree` 引入整个 OpenMinis 仓库，并非只有 Android。项目初期删除的 iOS 代码已恢复到上游原位置 `android/src/ios`，同时恢复 `android/deps/` 的 iOS 依赖脚本和 `android/deps/ish` 子模块，即 ARM64 iSH 分支。git subtree 是把另一仓库作为子目录维护的方式。保持两平台都位于同一上游子树，才能继续用 `git subtree pull` 一起更新。

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

仍须遵守 [CONTRIBUTING.md](../../CONTRIBUTING.md)：自有代码放入新文件，即 `NanoMuse/`；修改上游 Swift 文件时在相应位置标 `// nanoMuse:`；名称和品牌调整通过脚本生成，不手改结果。

## 设备对话 {#device-chats}

在 Muse 布局中打开「新建对话」，选择同账号下的一台设备。也可以从聊天抽屉的「电脑」页面发起设备对话，再从「旁聊」打开。按 Command-N 也会打开同一个设备选择列表。后续消息会发往选定的设备，每个设备对话各有自己的上下文和草稿。目标离线时也可以创建对话，发送时目标需要在线并支持 `task.status`。

在消息开头输入 `@设备名`，可以把这一轮交给另一台支持设备对话的设备。如果有重名设备，请输入 `@设备名 [设备ID]`。断线后，重新打开对话或点「刷新」可向目标设备查询原轮次的状态。iPhone 将对话记录保存在发起设备上。移除设备对话只会删除这台 iPhone 上的副本。投递状态不确定时，确认框会说明目标可能仍在运行，移除后会失去这台 iPhone 保存的恢复信息；这不会停止远端轮次。详见 [Hub 协议](hub.md#persistent-device-conversations)。

## 这里哪些是 nanoMuse 的 {#what-is-nanomuse-here}

`python scripts/rebrand.py` 应用以下调整。脚本可重复执行且结果一致，每次更新上游后都应运行：

- **应用标识**。 Bundle id 改为 `io.github.nanomuse.app` 及 `.ShareExtension`、`.AgentWidget`、`.FileProvider` 扩展，App Group 为 `group.io.github.nanomuse.app`，iCloud 容器为 `iCloud.io.github.nanomuse.app`。包含 bundle id 的后台任务、UTType 和 URL scheme 标识也一起修改。iOS 没有 Android 的源码包名限制，因此整组标识可统一调整。系统注册的链接前缀为 `nanomuse` 和 `nanomuse-mcp`，分享扩展使用 `nanomuse://share`，避免与同机 OpenMinis 冲突。App 内部继续采用上游 `minis://…`，兼容沙箱、系统提示词和模型；系统传入的 `nanomuse://` 由 `NanoMuse/NanoMuseOwnScheme.swift` 转为对应 `minis://`。聊天以外的自有按钮通过 App 深链接路由打开，不交给系统。
- **名称**。 显示为 nanoMuse、「Share to nanoMuse」「nanoMuse Files」。Swift 字符串、`Localizable.xcstrings` 的键及全部九种翻译、各语言 Info.plist 权限用途说明中的「Minis」均替换为「nanoMuse」。与 Android 一样，OpenRouter 的 `HTTP-Referer` 保留 OpenMinis，用于注明来源。
- **版本号**。 `MARKETING_VERSION`、`CURRENT_PROJECT_VERSION` 跟随 Android 的 `versionName` / `versionCode`，CI 再用工作流运行编号覆盖构建号。
- **配色与图标**。 AccentColor 使用 `#015CFB` / `#58A6FF`。一笔画 N 作为应用图标，浅色用白底、深色用暗底并配品牌渐变；应用内图标选择器的四款外观也使用该图案。智能体标题符号由 ✨ 改为 🐾。
- **关于页面**。 链接到本仓库、问题列表及隐私页，使用 nanoMuse 的简介，并在致谢中说明基于 OpenMinis 1.13（GPL-3.0），与 Meta 无关联。

`NanoMuse/` 中实现了以下自有功能：

- **让固定指令可被缓存**。 系统提示词先放稳定的工具、安全说明，再按确定顺序追加模型能力、技能、MCP 元数据、记忆、`USER.md`、对话要求，最后追加时间、语言、可用模型数。MCP 是向智能体提供工具与数据的通用协议。支持前缀缓存的服务商可复用固定部分，写记忆或每小时更新时间不会使其失效；切换备用模型时也重建相同布局。
- **nanoMuse Cloud**。 「服务商」首行提供 Cloud 登录，使用手机号或邮箱验证码。登录后，中继（负责账号与设备通信的服务器，见 [cloud.md](cloud.md)）作为普通 OpenAI 兼容服务商加入，并有独立模型组，没有默认组时才设为默认。线上格式和规则与 Android 的 `io.github.nanomuse.cloud` 一致：每个中继一个实例，不覆盖自有配置；刷新返回 401 会移除服务商并单独保存账号数据，见后文 C12。任何构建都可连接其他中继，使用后文「使用其他服务器」。0.1.32 起页面扩展为完整账号页，包括密码登录、朋友邀请码、人民币额度及不足时的继续方式（自有 key、邀请、点一次 Star）、按类型和模型的用量、登录设备、时间线、删除，与 Android `CloudAccountScreen` 对齐。key 是访问服务的密钥。
- **执行步骤与状态**。 设置 → 聊天 →「执行步骤」控制是否在已完成消息中显示工具胶囊，默认只保留对话内容。输入状态显示「〈名字〉正在处理」。实现分别是上游 `AssistantBlockView`、`ContentView` 中带 `// nanoMuse:` 标记的单行改动。
- **等待提示**（1.0.8，`NanoMuseStreamStatus.swift`）。每步等待首个 token 时，`NanoMuseWaitLine` 前十秒不显示，之后显示「模型接口比较忙，已等待 15 秒」和「取消」，后者调用聊天停止。token 是模型输入输出的计量单位。如果 Cloud 已通过中继 0.31 的 `nanomuse: {phase, ahead}` 数据块告知排队，则显示「前面还有 3 个」或「下一个就到你」，协议见 [cloud.md](cloud.md#protocol)。两个 OpenAI 服务商的 SSE（服务器持续推送数据）循环各有一行传递字段，`ChatMessageViews` 的一行负责显示。
- **提示词容量管理**（1.0.8，`NanoMuseContextBudget.swift`、`NanoMusePromptDiet.swift`）。上下文窗口是模型单次能接收、生成的内容容量。对于 64k 及以上窗口，摘要阈值统一为 32k token，上游原规则是距窗口上限 20k；旧的大型工具结果从 28k 起存到磁盘。`browser_use` 参数结构说明已精简，但保留所有动作、参数。数字依据见 Android 页。`AIChatViewModel` 的三处调用有标记，原策略分级及测试不变。
- **Muse 主界面**（0.1.33，iPad 从 0.1.34 起支持）。根视图由 `NanoMuseRoot` 替代上游 `ContentView`。设置 → nanoMuse 的「Muse 主页」「在对话顶部显示形象和名字」控制布局，抽屉中也可切回 OpenMinis 布局。聊天顶部由 `NanoMuseHeader.swift` 显示形象、名字、状态。优先级为：有问题或审批（操作前请求你确认）时「等你回复」；否则工具的 `tool_title`，如「打开携程网站」；再是「正在写回复」「正在处理：〈简述〉」；空闲显示模型名。绘制新形象时改为形象流程进度。`NanoMuseFaces.swift` 优先使用 Application Support 的自绘形象，其次使用桌面或网页设置的 emoji 与背景色，保存在 `avatar/emoji.json`，作为静态图显示，手机尚无选择器；再否则使用包内小龙。五种状态沿用其他客户端的呼吸、浮动、倾斜、弹出、抖动；开启「减弱动态效果」后，静态形象不动，仅保留状态淡入淡出。点形象进入智能体页面。

  可通过智能体页面钢笔菜单或形象工作室的「你自己的视频…」使用个人短片，代码为 `NanoMuseOwnClip.swift`。接受 MP4、MOV，H.264 或 HEVC，最长 15 秒、最大 30 MB，预览确认后使用，仅存于本机 `Application Support/nanomuse/avatar/own-clip.mp4`。视频和静帧都排除在 iCloud、电脑备份之外，点「默认形象」可移除，备用规则见 [avatar.md](avatar.md)。选择视频后先关闭照片选择器，再打开预览；预览须明确点「使用」或「取消」才关闭，避免动画切换丢失候选。

  抽屉提供会话、搜索、新旁聊、「设为主要聊天」「全部对话」和 nanoMuse 设置。点圆形按钮可打开，主要聊天也可从左边缘滑入。`NanoMuseEdgeSwipe.swift` 把屏幕边缘手势挂到窗口，与 Android 聊天页一致；打开的旁聊仍保留系统返回手势。
- **智能体页面**（0.1.34，`NanoMuseAgentPage.swift`，对应 Android `ui/profile`）。页面显示大形象、钢笔角标、名字、「在线」。钢笔提供「更换形象」，向主要聊天输入框填入「把形象改成 」，以及「编辑名称」「形象工作室」。四个面板为：「动态」，汇总最近两天的用户要求和执行情况；「审批」，查看并撤销长期「总是允许」授权；「每日」，显示例程、目标检查及下次时间，可「管理例程」；「SOUL 与记忆」，编辑 SOUL.md、GLOBAL.md。另有分享面板 `NanoMuseAvatarShareSheet`，对应 Android `ui/avatar/AvatarShareSheet.kt`。
- **通过聊天更换形象**（0.1.34，`NanoMuseAvatarFlow.swift`，对应 Android `avatar/AvatarFlow.kt`）。「换成一只橘猫」或「change your avatar to a red panda」会先被本地规则识别，再交给模型；两端使用相同正则，测试在 `MinisTests/NanoMuseLogicTests.swift`。聊天卡片显示四张候选图，可点选或用「the second one」「第三个」「重新生成」选择。随后显示「正在完成姿势…」，应用新形象、同步资料、写入记忆并显示分享卡。走中继时先用 `/v1/estimate` 显示费用；有自有百炼 key 时通过 `NanoMuseImageGen.swift` 调用 DashScope 原生图像接口。`NanoMuseAvatarStudio.swift` 使用同一流程，也可选图像模型。
- **定时调度**（0.1.34，`NanoMuseScheduler.swift`）。例程包含标签、提示、时间，可每天、工作日、单次或每 N 小时执行，通过 `NanoMuseHeadless` 在专属聊天中进行无界面轮次。iPhone 只在 App 打开时执行：回到前台先补跑到期项，再每分钟检查。每个到期时刻也会发本地通知，如「检查：〈目标〉，打开即运行」，点后打开对应聊天。退后台申请的 `BGAppRefreshTask`，标识为 `io.github.nanomuse.app.scheduler`，仅在 iOS 分配机会时发送到期提醒、申请下次刷新，不执行例程。相关文案都明确此限制。设置 → nanoMuse → 定时任务 列出全部例程，也包括动态和目标检查。
- **目标**（0.1.34，`NanoMuseGoals.swift`，对应 Android `goals/`）。「创建目标 → 类别」向主要聊天发送开场要求，并在随后几个轮次附加系统说明。模型的 ` ```nanomuse-goal ` 块创建目标和检查例程，` ```nanomuse-goal-update ` 块更新进度。聊天显示「目标已创建」「目标进展」卡片。「目标」功能页显示进度、步骤，提供暂停、现在检查、完成、删除，下方列出例程。
- **动态**（0.1.34，`NanoMuseFeed.swift`，对应 Android `feed/`）。每日例程根据记忆、日记、目标生成短文，写入 `feed/<day>/<n>.md`，包含 front matter，即文件开头的结构化信息，模型用 ` ```nanomuse-feed ` 块提交内容。「动态」按天显示，同日最新批次优先。「讨论」针对该内容打开旁聊，设置面板可选主题、时间、开关及「现在写一版」。「点子」除「发到聊天」外，还提供「创建例程」，按点子时间安排并打开编辑器，以及「开始这个目标」。
- **首次引导与设置**（0.1.34，`NanoMuseFirstRun.swift`、`NanoMuseSettings.swift`、`NanoMuseCoding.swift`、`NanoMuseSystemFiles.swift`）。沿用 Android 引导的四页流程：欢迎、登录免费开始、新账号设置密码、选择回答模型、认识〈名字〉。「我有自己的 API key」打开含完整目录的自有 key 面板，详见后文。之后进行首次聊天，显示开场、询问称呼、用模型 ` ```nanomuse-naming ` 块显示名字选择，并写入 GLOBAL.md、SOUL.md。设置 → nanoMuse 包含账号、编程助手、定时任务、系统文件、连接器、数据控制、两项界面开关和「重新显示欢迎页」。编程助手通过 hub `coding.*` 访问同账号电脑的 Cursor、Codex、Claude Code 会话并可发送消息。系统文件包括 SOUL、GLOBAL、日记、动态指令、例程时间表，还支持从其他助手「导入记忆」。
- **模型选择**（0.1.34，`NanoMuseModels.swift`）。中继菜单默认选中标为对话推荐的模型，项目托管中继为对话和屏幕操作推荐同一个多模态模型 `Qwen/Qwen3.6-27B-FP8`。聊天选择器中的选项会移到 Cloud 组首位，供新聊天沿用，与 Android `followPick` 一致。DeepSeek id 默认只视为文本模型，只有含 `v4.1` 或更高版本、`vision`、`ocr` 才视为视觉模型，该处理位于 `LLMModel.withInferredModality()` 开头带 `// nanoMuse:` 的位置。
- **四种用途分别选模型**（0.1.41，`NanoMuseModelSlots.swift`、`NanoMuseModelsView.swift`，对应 Android `ui/models/ModelsScreen.kt`）。设置 → nanoMuse 的首张「模型」卡片显示「对话」「操作屏幕」「生成图片」「生成视频」。iPhone 的屏幕项禁用，说明「不在 iPhone 上」「电脑用它自己的设置。」每行显示 `<provider> · <model>`。仅当中继实际菜单提供该项时，选择器首先列 nanoMuse Cloud 并标出「推荐」，然后按自有服务商分组，只列符合该任务的模型。空项和页面末尾均提供「添加服务商」。图片、视频下还会通过 `NanoMuseModelSlots.notDriven` 说明目录支持、但手机当前无法调用的来源，提示「此处不提供：……」及适用客户端；目前手机只接入 DashScope 主机。

  更换对话模型会设置新聊天默认组，服务商专属组将所选模型置首，自建混合组则保留原顺序，并让主要聊天同步更换绑定。`NanoMuseModelSlots.mainChatFollows` 修复了 0.1.41 中主要聊天因不是新聊天而留在 Cloud、自有 key 只用于旁聊的问题。页面说明「对主要聊天和新对话生效；旁聊保留自己的模型。」聊天内部选择器也按同样规则处理所有服务商。图片、视频依次使用显式选择、对话服务商可绘图的百炼默认模型、已登录且实际声明对应媒体能力的中继、第一个可用 key。项目托管 Cloud 无媒体生成，所以需要自有 key；默认值来自目录 `defaults`，不在代码写死。「自动」显示当前解析值，并清除显式选择重新按该顺序解析；视频的「关闭」位于其后。

  模型组先显示八项，依次为任务目录默认、当前选项、原列表顺序，末尾「还有 n 个」展开。总数超过八项时，「自动」下方出现「搜索模型」，按 id 或显示名即时过滤，显示全部匹配项，隐藏无匹配组，没有结果显示「没有匹配的模型」。`NanoMusePickerList` 由 `NanoMuseModelSlotsTests` 测试。保存 key 后，`NanoMuseVendorSheet` 显示「用它来做什么」，支持的用途各有默认开启的开关，图片和视频仅 DashScope 显示，iPhone 不显示操作本机屏幕。「就这样」将勾选项改用服务商默认模型，「暂不」不修改，单纯保存 key 不再切换。自有对话模型失败时，已登录用户的失败卡片及上游普通错误会增加「这次改用 nanoMuse Cloud」，由 `NanoMuseCloudOnce` 在 `resolveCurrentEntry()` 开头让本轮走中继模型，不更改任何配置。媒体失败没有 Cloud 重试。中继菜单登录时保存在本机，打开页面时刷新。「图像与视频模型」快捷入口仍保留，提供自动生成动画开关和短片按钮。
- **共享连接器清单**（0.1.34，`NanoMuseConnectors.swift` 的 `NanoMuseSharedConnectors`）。profile 的 `connectors` 记录哪些设备连接了哪些服务，包含 id、标签、去掉查询参数的地址、登录方式、启用状态、时间、设备，不含令牌。手机上传自己的条目并获取其他设备条目，在「你的其他设备上」显示「已在〈设备〉上连接，在这台手机上登录一次，这里也能用」。账号继续使用选项按地区排列，中国大陆优先百炼，其他地区优先「使用 OpenRouter 登录」。
- **连接器**（`NanoMuseConnectors.swift`）。内置 `connectors.json` 来自桌面目录，由 `node scripts/connectors-json.mjs` 更新，CI 用 `--check` 校验。MCP 授权依次执行 initialize、401、受保护资源元数据、授权服务器元数据、RFC 7591 注册，再交上游 `MCPOAuthController`；也支持 key、公开、自动类型服务。八个不接受客户端注册的服务会要求提供 client id，并显示可复制的回调地址。设置原「MCP Integrations」改为「连接器」，末尾「你自己的服务器」进入上游 MCP 编辑页。
- **数据控制**（`NanoMuseDataControls.swift`）。显示中继 0.29 请求记录的轮数、自有 key 轮数、图片数和保留期限，提供训练集开关及数量、隐私页，以及确认后同时删除完整记录和训练轮次的操作。1.0.7 起手机参与完整记录，见 [cloud.md](cloud.md#the-record)：账号聊天请求由 `NanoMuseCloudHeaders.swift` 带 `X-NanoMuse-Device`、`X-NanoMuse-Conversation`；自有 key 轮次结束后，`NanoMuseOwnTurns.swift` 包装服务商，将整轮和图片文件上传，不上传 key、Base URL。hub hello 的 `device.llm` 标明新聊天模型来源。`NanoMuseProfile.swift` 通过 profile 的 `clips` 上传本机生成的形象短片，并将其他设备的短片保存到动画目录，使同账号形象只生成一套动画。

  **来源与执行事件**。 中继 0.31 起，`NanoMuseProvenance.swift`、`NanoMuseClientEvents.swift`、`NanoMuseFeedback.swift`、`NanoMuseGateEvents.swift` 为请求附上 `X-NanoMuse-Run`，注明用户、例程、动态、目标检查或 hub 远端任务，另有聊天轮次、轮内调用序号和 `X-NanoMuse-Platform: ios`。自有 key 上传同样字段，见 [cloud.md](cloud.md#provenance)。智能体服务商再包装一层，`NanoMuseHeadless.run` 注明后台任务类型，保证输入、重试、例程、hub 任务使用同一格式。登录后，`POST /v1/events` 上报 `apple-*` 命令权限检查与面板回答、本轮手动停止或错误，以及最新回复的赞踩。停止后输入框上方会问「为什么停下来？」，提供五个单词选项和「跳过」，例程和远端任务不问。仅发送命令名、类别、回答者、等待时间等代码和数字，不含参数或对话文字，见 [cloud.md](cloud.md#client-events)，删除轮次时一并清除。

  **Reach 与跨设备任务**。 `NanoMuseReach.swift` 为各设备提供操作面板，可打开链接、发通知、执行 shell 命令或截图。`NanoMuseDeviceMention.swift`、`NanoMuseRemoteApproval.swift` 将开头的 `@〈device〉` 文字直接作为 hub `task` 发给目标 Muse。消息开头的 `@` 菜单在文件上方列在线设备。`NanoMuseDeviceReply.swift` 实时显示「〈device〉正在处理…」、工具胶囊和远端文字，结束时保留最终回答。执行期间聊天为忙碌状态，停止也会取消远端任务，期间排队的消息在结束后发出。超时或断线将未完成步骤标为失败，停止将其取消；仅收到最终回答、未收到步骤结果时，不把该步骤标为成功。

  远端 `approval` 会在发起设备显示卡片，见 [hub.md](hub.md)，与 Android 一样提供「允许一次」「本次对话都允许」「在〈设备〉上总是允许此操作」「拒绝」。会话授权只存内存；长期授权按设备 id 保存在本机，只覆盖该设备的相同步骤，可在智能体页「审批」撤销。付款仅提供允许一次、拒绝。目标指定期限内无回答视为拒绝，未指定则为 180 秒。目标设备使用者先回答并发回 `approval_result` 时，本机卡片关闭、不重复作答。审批面板放在根视图，如果设置或工作室面板已经打开，需先关闭才能看到。1.0.3 及之前，手机会拒绝所有此类请求。
- **服务商连接失败**（`NanoMuseProviderReach.swift`、`NanoMuseProviderReachCard.swift`）。无法连接服务器、找不到主机、TLS 或超时，以及 OpenAI 地区限制，都显示为具体说明卡片，列出 VPN、设置 → 网络 的代理、其他服务商 key 等办法，提供「重试」，原始信息放在「详情」。`LLMError` 给网络错误附 `[host: …]`，使卡片能指出目标主机。`mapHTTPError` 原本丢弃的 401/403/429 响应体由 `NanoMuseReachSignal` 短暂保留，`friendlyErrorMessage` 将其写为 `nm_reach:` 标准行。ChatGPT 登录过期显示「重新登录」，套餐时段用量耗尽则显示「ChatGPT 套餐暂时没有剩余了」、OpenAI 原因和恢复时间。分类、文案、规则与 Android `ProviderReach` 一致。
- **中继拒绝请求**（`NanoMuseRelayRefusal.swift`、`NanoMuseRelayRefusalCard.swift`）。Cloud 拒绝会用当前语言说明情况并给出合适按钮，不只展示状态码、JSON 或「Rate limited」。`NanoMuseReachSignal` 将非 2xx 模型响应先交给 `NanoMuseRelaySignal`，复用 `mapHTTPError` 的原有 `// nanoMuse:` 接入点，不新增上游改动。`type: nanomuse_cloud`、已知中继代码，以及中继主机返回的普通 413 / 401 / 5xx，会转为 `nm_relay:` 标准行，由 `NanoMuseProviderReachCard` 显示。说明来自 `NanoMuseCloud.describe`，与登录、账号页共用，覆盖九种语言。`413 too_large` 提示精简消息、移除附件或新建聊天，提供「新聊天」。`400 content_rejected`，包括自有 key 的 `DataInspectionFailed`，提示内容审核未通过，可改写或新建聊天，旧消息也可能触发，提供「新聊天」「重试」。`isSegmentRetryableError` 不做分段重试，因为内容不变仍会被拒。即使 HTTP 为 200，流中 `data: {"error": …}` 也会经 `OpenAIProvider` 流循环的 `// nanoMuse:` 处理结束并显示卡片，避免空回答。`401 bad_key` / `account_deleted` 提供「登录」；`403 not_invited` / `account_disabled` / `signup_closed` 提供「打开设置」；`429 too_many_in_flight` / `locked` / `rate_limited` / `provider_busy` 提供「重试」并采用 `retry_after`；`404 model_not_offered` 提供「打开设置」；`503 service_paused`、`sync_paused`、`hub_paused` 及其他 5xx、空响应提供「重试」。
- **聊天中的额度提醒**（`NanoMuseAllowance.swift`、`NanoMuseAllowanceCard.swift`，对应 Android `AllowanceSignal`、`AllowanceWaysCard`）。`429 allowance_exhausted` 或 `daily_cap` 会把卡片固定在聊天头部下方，使用外壳顶部留白，与 Star 卡片相同，不向 `AIChatView.body` 新增修饰器。开头区分免费额度已用完、今日份额已用完，或中继 0.22 的 `paused: true`，即暂时停发、剩余额度保留。随后列出继续使用的方式及「重试」，重发当前聊天最后一轮。用至 80 % 时，`/v1/me` 的 `spend.warn` 会让 `NanoMuseChatCardsHost` 在输入框上方显示「即将用完：¥… 中还剩 ¥…」，每个额度总量只提醒一次，新增加额度可再次提醒，× 可关闭，正式卡片出现时替代该行。
- **自己的 key**（`NanoMuseCatalogue.swift`、`NanoMuseVendorSheet.swift`、`NanoMuseModels.swift` 的 `NanoMuseOwnKeySheet`，见 [own-key.md](own-key.md)）。目录打包在 `NanoMuse/Resources/providers.json`，由 `node scripts/providers-json.mjs` 更新、CI `--check` 校验。中继 0.21 若返回 `spend.guidance` 则优先采用，`429 allowance_exhausted` 也可携带，结果跨启动保存在 `UserDefaults`，因此中继新服务商可在 App 更新前出现。固定额度卡片、设置 → nanoMuse Cloud、自有 key 面板共用 `NanoMuseWaysList`。

  「使用自己的模型 key」按地区排序，大陆优先百炼，其他地区优先 OpenRouter、OpenAI，「更多服务商」每次显示三家。每行说明对话、屏幕、图片、视频能力。「获取 key」打开厂商页面，「添加」打开 `NanoMuseVendorSheet`，粘贴 key 后按厂商端点和 `/v1` 设置添加实例、获取模型，没有默认组时将同名组设为默认。「你已经在付费的套餐」提供 ChatGPT（上游 `CodexOAuthManager`）、Claude、OpenRouter、Kimi 设备码（`KimiDeviceLoginSheet`）。ChatGPT 行说明 OpenAI 条款仅覆盖自家 Codex，其他 App 曾被停止访问，例如 2026 年 1 月 OpenCode，失效后可用 API key；若中继提供文案则用中继版本。「你自己的电脑」可填写 Ollama、LM Studio、vLLM 地址。页面不对某一家单独背书。
- **网络代理**（`NanoMuseProxy.swift`、`NanoMuseNetworkView.swift`，设置 → nanoMuse → 网络）。自有服务商 HTTP 代理可填主机、端口、可选用户名和密码，默认关闭，仅存本机。地址、用户名存 `UserDefaults`，密码存为钥匙串设备专用条目 `io.github.nanomuse.app.proxy`，规则与中继 key 相同；1.0.3 存在 `UserDefaults` 的密码首次读取时迁移。由于 `URLSession` 无逐主机代理开关，程序在 `connectionProxyDictionary` 中使用自动代理脚本：目录主机、`chatgpt.com`、`auth.openai.com`、自有服务商自定义主机走代理，中继、局域网及其他地址用 `DIRECT`。各上游服务商会话只加一行 `NanoMuseProxy.apply(to:)`，Codex 登录和模型列表用 `NanoMuseProxy.session` 替代 `URLSession.shared`。凭据放入共享 `URLCredentialStorage` 对应代理认证域。「测试」按当前代理访问 `https://chatgpt.com/`。
- **统一界面组件**（0.1.35，`NanoMuseChrome.swift`、`NanoMuseAppearance.swift`，对应 Android `ui/chat/MuseHeader.kt`、`ui/settings`）。聊天及动态、点子、目标、资源库各页都显示形象圆盘、名称标签、实时状态、抽屉及 `•••` 圆按钮。抽屉沿用 Android 结构；`NanoMuseChatCards.swift` 的 `NanoMuseAssistantBubble` 为回复加灰色气泡，智能体页工具栏改为圆按钮。`NanoMuseSettingsHomeView` 按 Android 顺序排设置卡片：图像与视频模型、形象、电脑、外观（形象大小、名字下的模型、步骤、主题）、通知、账号、编程助手、定时任务、共享文件夹、聊天文件、系统文件、版本。`nmOnChange` 让 `onChange` 兼容最低目标 iOS 16。`•••` 的「新聊天」、⌘N、「Context Full」提示、拒绝卡片均发送上游 `.newChatRequested`，由 `NanoMuseHomeView` 创建新草稿旁聊，与抽屉一致。Muse 布局不显示上游 `ContentView`，1.0.2 因此缺少监听、入口无效，见 #392。
- **形象短视频**（0.1.35，`NanoMuseVideoGen.swift`、`NanoMuseAvatarMotion.swift`、`NanoMuseMediaModels.swift`，对应 Android `avatar/VideoGen.kt`、`avatar/AvatarMotion.kt`）。自绘形象可经自有百炼 key 调用 `wan2.2-i2v-flash`，生成待命、干活中、等你回复、搞定四段各 4 秒短片，提示与手机端一致。自建中继明确启用旧媒体代理时也可使用，公共 Cloud 不提供。视频按设备保存在 `avatar/motion/`，通过 `AVQueuePlayer`、`AVPlayerLooper` 循环播放，后台暂停。小龙视频由安装包提供。「图像与视频模型」列模型，提供默认开启的「更换形象后生成动画」及「生成 / 重做短视频」。工作室费用估算包含短片。
- **版本、Star 提醒、首次动态**（0.1.35，`NanoMuseUpdateCheck.swift`、`NanoMuseNudges.swift`）。版本行显示已安装与最新版，先查 `nanomuse.cn/dl/index.json`，再查 GitHub，缓存一天，区分已是最新、有新版本、无法检查可重试。Star 提醒遵循 `/v1/nudges`、`/v1/me` 的 `nudges`，无返回时使用相同内置默认。首次聊天不提醒，之后可在第 3 / 10 / 30 个任务、第 7 / 30 天、完成目标、更换形象、登录、额度耗尽时提醒，间隔至少七天，每手机最多四次。`NanoMuseStarWatch` 把用户发起、无错误且离开 `activeSessions` 的会话计为任务。提醒固定在标题下，因为消息列表为 UICollectionView，无法插在最后一条之后。句子优先用运营控制台的 `star.text`、中文界面的 `star.text_zh`，没有则用本机对应时机文案，标题、按钮仍由 App 提供。动态页先显示介绍卡，空白时说明每日执行时间，首次聊天后写第一批内容。首次引导也增加通知页。
- **聊天输入区**（0.1.38、0.1.40）。相关代码为 `NanoMuseShell.swift` 的 `NanoMuseHomeView.body`、`NanoMuseChatModifiers.swift`、`NanoMuseComposerField.swift`、`NanoMuseComposerWatch.swift`、`NanoMuseComposerCheck.swift`，以及 `Views/Chat/AIChatView.swift` 的 `// nanoMuse:` 改动。0.1.36、0.1.37 的维护者 iPhone 在首次命名后，以及 0.1.39 的 iPad，都反馈输入框消失。0.1.37 监视器、0.1.38 原生输入框及备用第二宿主，是依据实际上仍存在输入框的截图编写的。最终发现：首次打开时输入框可见，关闭键盘后永久被遮住；0.1.36 截图中还能看到它露在底栏上方的顶边。底栏原来是 `NavigationStack` 祖先的 `safeAreaInset`，键盘打开时隐藏；重新出现后聊天不再遵守此留白，整个聊天被放到底栏下面。输入框已经正常布局、各项监测也正常，只是被底栏盖住。

  0.1.40 起，底栏不再作为聊天祖先的 inset：先使用 `VStack` 行，后改为给聊天层添加底栏高度的 padding，直到 1.0.3。之后将高度通过 `nmBottomOverlay` 环境值交给聊天，由输入框自行抬高。0.1.40 至 1.0.3，卡片、工具条、输入框组成的列位于缩短后的消息列表下方，导致玻璃导航背后只是空白底色。1.0.4 起，`NanoMuseComposerHost` 改为 `ZStack`，输入列重新覆盖完整消息列表底边；列表底部 inset 为输入列实测高度加导航高度，使消息能滚到二者背后，静止时最后一条停在输入列上方。`/`、`@` 弹层与输入列放在同一 `VStack`，自然紧贴其顶部。

  输入框后由 `NanoMuseComposerVignette` 提供 Android 同款圆角渐隐。列表离开最新消息时，90 pt 高的背景光圈沿输入框 26 pt 圆角轮廓展开，向导航栏上方间隙渐透明，保留玻璃后的消息，不出现实色矩形条。实现不再切换第二宿主。监视器只在聊天可见而输入列脱离视图或测高为 0 时，通过 `.id(rebuildTick)` 重建，每次显示最多两次，避免误测正常输入框时反复收起键盘。

  设置 → 外观 →「输入区检查」会给输入列画红框，并生成诊断报告：窗口和安全区域、输入列位置、探测视图全部 UIKit 祖先的位置、隐藏和透明度、窗口内文本框和集合视图、监视事件，可用「复制」提交问题，无需 Mac 即能提供视图层级。输入框采用 SwiftUI `TextField(axis: .vertical)`、`@FocusState`、`lineLimit(1...6)`，替代上游 `UIViewRepresentable` 文本视图。原实现支持而新实现不提供的能力包括：直接粘贴图片（改从加号菜单「粘贴图片」操作，仅剪贴板有图时出现）、选择替换以供纠错学习、`@` 菜单精确光标位置（现在使用末尾）、预计超过六行文字的滑动发送，以及 iOS 16 弹层硬件方向键 / Tab 导航，iOS 17+ 通过 `onKeyPress` 支持。硬件回车发送，Shift+Return 换行；屏幕回车依 设置 → 外观 →「回车发送」设置，听写仍通过「返回键盘输入」结束。
- **启动画面**（0.1.38，`NanoMuse/NanoMuseLaunch.storyboard`、`NanoMuse/NanoMuseLaunch.xcassets`）。在系统背景上显示标志，不含文字，支持深浅色。上游 storyboard 保留，`scripts/rebrand.py` 将 `INFOPLIST_KEY_UILaunchStoryboardName` 指向自有文件。iOS 按安装缓存启动画面，更新后可能仍显示几次旧图，重装会立即显示新图。
- **旁聊同步与执行状态**（0.1.38，约定 C9，`NanoMuseSync.swift`、`NanoMusePresence.swift`、`NanoMuseSyncSettings.swift`、`NanoMuseFromDeviceCaption.swift`）。数据控制 →「同时同步旁聊」按设备保存，默认关；只上传主要聊天，下载请求带 `scope=main`，仍收到的旁聊记录会忽略。打开后以 `since=0&scope=all&tail=300` 获取一次，按 `mid` 去重，旁聊在下一次上传时发送；关闭后缩小同步范围，不删除数据。同步表首次拉取使用 `since=0&tail=300`，先取最近 300 条文字，而非全部历史。用户消息上传后及本轮结束上传后，调用 `POST /v1/sync/working {cid, working}` 更新状态。hub `working` 和 `/v1/sync/state` 的 `working` 列表形成十分钟过期的映射，远端用户消息下方显示「〈device〉正在处理…」。句子存在 `ChatMessage.nmWorkingDevice`，中继 0.31 有 `state`、`detail` 时，`NanoMusePresence.sentence` 显示具体步骤或「〈device〉在等你确认」。末尾为远端用户消息时，`recheckCanResumeFromHistory` 不开启 `canResume`，因为它不是本机中断轮次，不显示恢复提示、不提供继续、不重发。
- **登录与中继选择**（0.1.38，`NanoMuseCloud.swift`、`NanoMuseCloudView.swift`、`NanoMuseRelayPicker.swift`）。手机号国家码不是 +86 时，在请求验证码前即提示「短信验证码目前只发往中国大陆号码。请改用邮箱。」，中继 `phone_region` 同样显示此说明。登录页「使用其他服务器」打开地址面板，可「检查」`GET /healthz`，再「使用这个服务器」。除自有网络外必须 HTTPS，地址判断与代理直连一致，由 `NanoMuseProxy.isLocal`、Android `LanOnly` 实现。先解析地址，所以 `10.foo.example.com` 是公网名称；私网、Tailscale 的 `100.64/10`、回环、链路本地、IPv6 ULA、`localhost`、无点名称，以及 `.local`、`.lan`、`.home`、`.internal`、`.home.arpa`、`.localdomain`、`.ts.net` 视为自有网络。登录后账号页显示「服务器：〈host〉」与「更改」，更改会先退出，因为 key 只属于签发它的中继。
- **按账号显示聊天**（0.1.39，约定 C10，`NanoMuseSync.swift`、`NanoMuseShell.swift`）。对话归首次上传或下载它时登录的账号，映射存在该账号的同步表。`nanomuse-sync-accounts.json` 为每个曾登录账号保留独立表，以中继内部 `account.id` 为键，不使用手机号、邮箱。登录后，列表和聊天页显示本账号以及尚未被任何账号同步的聊天；其他账号聊天保留但隐藏，不会传到当前账号。未归属聊天首次上传后即归当前账号。换账号时重新设置游标，先获取 `tail=300` 并清除在线状态；切回原账号恢复其对话、主要聊天。此版本退出时显示本机全部聊天，但不再同步。名字、形象已按账号同步，本地记忆在这时尚未隔离。
- **完整的账号数据隔离**（0.1.40，约定 C12，`NanoMuseAccountData.swift`、`NanoMuseSignOutSheet.swift`）。所有聊天无论是否同步，都在 `nanomuse-owners.json` 中有归属记录。聊天列表、「聊天」「资源库」「今天的聊天」、Siri 快捷方式及上传，只处理当前账号内容。退出后只显示未登录时创建的聊天。本机退出、所有设备退出、切换服务器都显示同一面板，「把这个账号的聊天留在这台设备上」默认关闭。关闭会删除本机账号聊天、记忆、动态、目标、例程、形象和同步表，避免以后登录把删除误同步到其他设备。开启则移到 `MinisConfig/nanomuse/accounts/<hash>/`，同账号重新登录恢复。换账号也走此流程，删除账号不询问、全部移除。刷新遇到 `401 bad_key`，例如其他设备撤销或中继重置，则默认走保留流程：数据单独保存、key 删除，`NanoMuseCloud.signInEnded` 让登录页持续提示登录已结束、聊天保留等待重新登录。只有 `401 account_deleted` 才删除，规则为 `NanoMuseAccountData.keepOnRefusedKey`，由 `NanoMuseAccountsTests` 测试。中继 key 使用 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`，不进入 iCloud 钥匙串。全新安装若无标记、服务商、聊天，会清理上次遗留的本机专用钥匙串条目。完整表见 [sync.md](sync.md)。
- **第 9 轮检查的界面调整**（`NanoMuseCloudView.swift`、`NanoMuseFirstRun.swift`、`NanoMuseAvatarFlow.swift`、`NanoMuseDevicesSection.swift`、`NanoMuseShell.swift`）。登录输入框上方显示 App 标志，提示为「中国大陆手机号或邮箱」。输入其他国家码时即时显示短信仅支持大陆的说明，无需提交后才发现。底部说明中继保存账号 id、打码标识、用量、名字、形象，与 Android 一致，并链接隐私政策，替代 GitHub。首次通知页同样显示标志。设置视频模型后选好新形象，会说明四段短片将在后台生成。设备列表显示离线设备上次在线时间；点在线设备在主要聊天填入 `@〈name〉 `，与 Reach「交给这台设备」相同。`NanoMuseRoot` 先确认是否需引导再绘制，避免新安装先闪现主界面。首次对话第四句也说明登录后主要聊天会同步到其他设备，可在「数据控制」关闭，不再声称只发给模型，各语言、Android 一致。
- **第 10 轮检查的连接与存储调整**（`NanoMuseHub.swift`、`NanoMuseDevicesSection.swift`、`NanoMuseScheduler.swift`、`NanoMuseSync.swift`、`NanoMuseAccountData.swift`、`NanoMuseProxy.swift`、`NanoMuseImageGen.swift`、`NanoMuseVideoGen.swift`）。hub 按 [hub.md](hub.md) 处理关闭码：4001、4002 停止重试直到重新登录，设备行显示「重新登录」；4003 等 30 s；原因为 `hub_paused` 等两分钟并显示「中继已暂停」；其他情况保持 1 → 30 s 退避并显示「正在重新连接…」。远端 `open` 只允许 `http`、`https`，`tel:` 或其他 App scheme 返回 `usage`；调用结束即取消超时计时器。单次例程若创建时已过当天时间，改为次日执行，避免永不运行。`nanomuse-sync-accounts.json`、`nanomuse-owners.json` 与聊天使用默认数据保护等级；锁屏后台唤醒等情况下文件存在但不可读，会等待下次调用，不把空表覆盖所有账号。图像、视频生成通过 `NanoMuseProxy.SessionSlot` 使用同服务商代理，错误各语言显示具体句子，如 key 被拒 HTTP 401、视频超过 12 分钟，服务商有原文时附在「服务商说：」后。
- **第 11 轮检查的任务与辅助功能调整**（`NanoMuseHubTasks.swift`、`NanoMuseHub.swift`）。远端 `stop` 可按任务帧 id，即桌面使用的 `stop {call}`，或按对话查找，只允许原发起设备停止，任务按 [hub.md](hub.md) 返回 `cancelled`。连接未断开时，针对单条消息的中继 `error`，如 `too_large`、`rate_limited`、`bad_frame`，只写日志，设备状态继续为「已连接」，不持续显示错误直到重连。标题名字和状态 `NanoMuseNamePill`、`NanoMuseHeaderTitle`，以及预留高度，按 Dynamic Type（系统文字缩放）调整，`NanoMuseHeaderMetrics` 上限为基础 1.35 倍。抽屉通过 `GeometryReader` 按实际窗口宽度布局，不再用 `UIScreen.main`，适配窄于屏幕的 iPad 窗口。模型行给 VoiceOver 提供已选状态，勾选符不再读成符号名。
- **第 10 轮检查的文字与排版调整**（`NanoMuseChrome.swift`、`NanoMuseFirstRun.swift`、`NanoMuseProviderReachCard.swift`、`NanoMuseSystemFiles.swift`、`*.lproj/InfoPlist.strings`、`Localizable.xcstrings`）。iOS 16 `Layout` 实现的 `NanoMuseFlowLayout` 让首次聊天名字按钮及服务商卡片操作自动换行，使四个名字及「重试」「这次改用 nanoMuse Cloud」「网络设置」「添加自己的 key」在 iPhone SE 和大字号下不被右边缘截断。引导页细则合为一段，末尾提供「了解更多」。NFC、蓝牙、Face ID 权限提示补齐九种语言，不再回落英文；局域网提示说明本 App 用途，不再描述虚拟机。简体中文统一使用设置中对应的「nanoMuse Cloud」，修正原 16 处其他译名。HEARTBEAT.md 按例程列表的语言写「每天 · 08:00」「每 6 小时检查」，不直接输出 `daily`、`once`、`every 6 h`。记忆导入提示随 App 内语言切换更新。
- **第 11 轮检查的文字与凭据调整**（`Localizable.xcstrings`、`NanoMuseVendorSheet.swift`、`NanoMuseFeed.swift`、`NanoMuseAppearance.swift`、`OpenAIProvider.swift` 的 `// nanoMuse:` 位置、`MinisTests/NanoMuseCopyTests.swift`）。九种语言的用户文案均不用长横线，73 个键改用分句、逗号、冒号或间隔点，HEARTBEAT.md、诊断报告也一起改，移除十个未引用键。上游 OpenMinis 键不改。繁体中文同样使用「nanoMuse Cloud」，俄语邮箱为「Эл. почта」。`NanoMuseCopyTests` 在 Mac 读取目录及 `NanoMuse/` 源码，自有键中出现长横线、感叹号或翻译后的产品名会失败。服务商表单保存前先用 key 请求模型列表，401、403 会保留原配置并在字段下说明；不再因上游备用目录填充而像验证成功一样关闭。套餐 429 的 `Retry-After` 会传给连接卡片，ChatGPT、Claude 可显示恢复时间。动态详情采用 `Grid`，标签列按最长文字宽度；形象大小改用菜单，替代五段选择器。
- **第三轮检查：版本查询**（1.0.x，`NanoMuseUpdateCheck.swift`、`MinisTests/NanoMuseLogicTests.swift`）。下载索引 `nanomuse.cn/dl/index.json` 实际格式为 `{"releases": [{"tag": "v1.0.0", …}, …]}`，按新到旧排序，现与 Android `UpdateCheck.parseIndex` 一样正确读取。旧代码寻找从未提供过的 `ios.version`、`latest`，导致无法访问 GitHub 的手机始终显示检查失败。通过索引找到版本时打开 `nanomuse.cn/dl/`，通过 GitHub 找到则打开对应发布页。`parseIndex`、`parseGitHubLatest` 都是有测试的纯函数。
- **第三轮检查：登录面板**（1.0.x，`NanoMuseFirstRun.swift`）。欢迎页「登录，免费开始」以面板打开账号页。验证码或密码成功后，监听登录状态的 `nmOnChange` 会自动关闭面板，让引导显示下一步密码或模型来源页。旧版会停在带设备、同步设置的已登录账号页，用户必须手动收起才知道引导已前进。
- **第三轮检查：中文术语**（1.0.x，`Localizable.xcstrings`、`NanoMuseShell.swift`、`NanoMuseAccountView.swift`、`MinisTests/NanoMuseCopyTests.swift`）。19 个仍保留英文 agent 或误译为代理的键，统一改为「智能体」，繁体为「智慧體」，包括系统文件说明、例程、关于智能体、形象错误提示。「代理」只在网络设置表示 proxy。七处 relay 提示统一用「中继 / 中繼」，包括服务商提示、暂停注册、额度、同步、hub、自建中继等。Hands 沿用 Android 设置名称中的英文。聊天标签使用独立 `tab.chat`，对应「聊天」和 Android `nm_tab_chat`，不再沿用上游译为「闲聊」的 Chat；账号用量类型的 chat 使用「对话」，键为 `models.slot.chat`，对应 Android `nm_usage_kind_chat`。`NanoMuseCopyTests` 检查中文值中遗留英文 agent、将 agent 译为代理、使用中转或双手等错误。
- **第三轮检查：远端任务语言**（1.0.x，`NanoMuseHubTasks.swift`、`MinisTests/NanoMuseHubTasksTests.swift`）。`task` 帧携带发起设备的界面语言 `language`，见 [hub.md](hub.md)。iPhone Muse 会按该语言回答，不再只从任务文本推测。例如英文桌面输入 `@iPhone` 处理中文网页，仍得到英文回答。`NanoMuseHubTasks.prompt` 为有测试的纯函数。手机发出的 `@device` 从 1.0.0 起已带语言。
- **第三轮检查：关闭 Cloud 后的模型**（1.0.x，`NanoMuseModelSlots.swift`、`NanoMuseCloud.swift`、`NanoMuseModelsView.swift`、`ProviderInstanceDetailView.swift` 的 `// nanoMuse:` 位置、`MinisTests/NanoMuseModelSlotsTests.swift`）。新聊天使用账号模型时，在 设置 → 模型 关闭「使用 nanoMuse Cloud 模型」，或在 Cloud 服务商页关闭「启用」，会将对话位置和主要聊天转交第一个可对话的自有服务商，使用目录默认模型。解析为 `NanoMuseSlotResolver.nextChat`，对应 Android `ModelSlots.nextChat`，移动由 `NanoMuseModelSlots.chatLeaves` 经 `useForChat` 完成。没有自有模型时，`NanoMuseCloud.setModelsOn` 返回 false，开关保持开启，模型页卡片下及服务商页状态区底部说明「先添加一个自己的服务商；关掉 nanoMuse Cloud 后没有别的模型能回答。」旧版允许关闭却仍显示账号模型，主要聊天随后报「No model configured」。现在该开关不会产生未设置状态。关闭自有服务商仍沿用上游逻辑，按默认组重新解析，均不可用时提示「No model configured. Add a provider in Settings.」。
- **浮动胶囊导航栏**（`NanoMuseShell.swift` 的 `NanoMuseBottomBar`，`NanoMuseFaces.swift` 的 `NanoMuseTones.tabIndicator` / `tabIndicatorGlyph`，对应 Android `MuseBottomBar`，#329，@Ichiro786）。五个标签只显示图标，位于距底部安全区域 12 pt 的 `Capsule` 内，与输入框同宽、左右边距 16 pt。紧凑宽度最大 420 pt，目前手机均达不到；常规宽度如 iPad 使用聊天列减边距的 728 pt。图标与 Android 对齐，分别为 `bubble.left`、`doc.text`、`lightbulb`、`checkmark.square`、资源库三图形 `Category`，辅助功能标签和选中状态保留。胶囊由 `.ultraThinMaterial` 加 55 percent 不透明度的表面色构成，前者提供模糊、后者保证对比，边缘为 1 pt `NanoMuseTones.hairline`，替代原全宽底栏和顶部细线。

  五项均分宽度、整格可点。选中项显示实心 `tabIndicatorGlyph`，底部 60 × 46 pt `tabIndicator` 胶囊在浅色为黑底白图、深色为白底黑图，与 Android 一致；通过 `matchedGeometryEffect` 弹簧移动到新项，减弱动态效果开启后不使用弹簧。未选项用次级色线框。键盘或聊天语音面板显示时底栏隐藏。布局使用底部对齐 `ZStack`，覆盖聊天和各功能页。聊天通过 `nmBottomOverlay` 获得 70 pt 高度，即 46 加上下各 6 及间距 12，抬高输入框，消息可滚至两者下方，不对 `NavigationStack` 祖先加 inset。普通 SwiftUI 滚动功能页则使用同高度 `safeAreaInset`。两种方式都让玻璃背后有实际内容。1.0.3 及之前聊天整体抬到导航栏上方，玻璃后仅空白，在 iPad 上看起来像白色实心胶囊。
- **黑白聊天配色**（`NanoMuseFaces.swift` 的 `NanoMuseTones.ink` / `onInk` / `agentPill`，`NanoMuseHeader.swift` 的 `NanoMuseHeaderScrim`，`NanoMuseComposer.swift`、`NanoMuseChatCards.swift`，以及 `Views/Chat/ChatMessageViews.swift`、`Views/Chat/AIChatView.swift` 的 `// nanoMuse:` 改动，对应 Android #331，@Ichiro786）。Muse 布局下，用户气泡浅色为黑底白字、深色为白底黑字。智能体回复用略区别于背景的 `#F2F2F7` / `#1C1C1E`，文字随主题；代码、表格、原始标记仍不包气泡。输入框保留灰色，发送按钮使用 30 pt 墨色圆盘、背景色箭头，无可发送内容时圆盘很浅、箭头 40 percent 透明度。回复中的停止方块使用同一圆盘。「回到最新」也是墨色盘、背景色箭头，上方回退按钮保留浅色盘。

  主要聊天顶部不再模糊，而是背景色渐隐：顶端 80 percent，中间略下 35 percent，底部透明，让消息滚过形象下方逐渐消失。离开最新消息时，顶端另一个完整背景色渐隐在 250 ms 内出现，依赖主要聊天 `isNearBottom`，如同标题栏状态绑定。排队消息仍用上游虚线框和灰字，来自设备说明、附件位于气泡外，长按预览仍为不透明卡片。抽屉打开的旁聊保留系统返回和标题栏，1.0.4 起隐藏其自带背景、细线，改由 `AIChatView.swift` 的 `NavBarStyleModifier` 和 `nmSystemBarScrim` 显示同款渐隐；1.0.3 及之前为 `.ultraThinMaterial`。

  1.0.4 起，点子、目标、资源库采用与聊天一致的黑白背景，参照 Android 和 [design.md](design.md)。点子为细线分隔普通行，目标卡片细线描边，资源库用普通列表；仅动态保留灰底白卡，与 Android FeedTab 一致。这部分在 Linux 编写，iOS 检查已编译通过，本文记录时尚无设备展示结果。
- **iPad 使用统一聊天列宽**（`NanoMuseShell.swift` 的 `NanoMuseColumn`，`AIChatView.swift` 的 `maxContentWidth`、输入框 frame，`NanoMuseChatCards.swift` 的智能体气泡）。1.0.3 竖屏 iPad 原有三种宽度：上游列表、输入框最大 900 pt，因此输入框铺满 768 pt 窗口；底部导航仅 420 pt；回复气泡仅 340 pt 并靠左。现在常规宽度下，列表、输入框、导航共用居中 760 pt 列，与网页 `max-w-[760px]` 一致。列表行内部左右留 16 pt，输入框和导航为 728 pt，边缘彼此及气泡对齐；回复气泡可扩到网页宽屏值 600 pt。iPhone、窄分屏等紧凑宽度不变。列表单元使用 `UIHostingConfiguration`，不传自定义环境对象，但会从单元 traits 传 size class，气泡据此判断宽度。1.0.4 曾只给助手行在列外加边距，导致其左缘比输入框左偏 16 pt；`CollectionViewMessageListV3.swift` 的助手头部、正文、底部三类单元现改为列内加边距，与用户行一致。
- **消息可滚到标题栏背后**。 `NanoMuseChatModifiers.swift` 将实测 Muse 顶部高度以 `nmTopOverlay` 传入聊天。列表忽略容器顶部安全区域，再通过 `CollectionViewMessageListV3` 的 `topOverlay` 加入 `contentInset.top`，让初始消息保持下移，滚动时进入形象和渐隐层背后，与输入框、导航栏下方的处理相同。1.0.3、1.0.4 仅用 `safeAreaInset`，适合 SwiftUI `ScrollView`，却会缩短 UIKit 列表，使消息在顶栏下被硬切、渐隐无内容可处理。旁聊保留系统栏，值为 0，使用上游 iOS 26 的 `NavBarStyleModifier` 让内容滚入系统栏下；列表自身 inset 调整使首条消息起初位于栏下，滚动后也由同款渐隐处理。
- **隐藏动态工作会话，标明例程来源**（`NanoMuseRoutineWakes.swift`，`NanoMuseSync.shows`、`NanoMuseHeadless.run`，`ChatModels.swift`、`AIChatViewModel.swift`、`AIChatViewModel+Persistence.swift`、`ChatMessageViews.swift` 中的 `nmRoutine` 位置）。1.0.4 及之前，抽屉会显示名为 Feed 的写作会话，其中「Write today's feed.」被画成用户气泡，普通例程也如此。现在动态工作会话由智能体内部使用，`shows` 像过滤其他账号聊天一样将其排除，文章仍显示在动态页。例程提示行改为「例程 · 〈名称〉 · 08:00」，由 `NanoMuseRoutineWakeRow` 按消息 id 保存，重新加载仍可显示。`NanoMuseSessionAddenda` 为该轮说明提示并非用户亲自输入，使模型先报告结果，不感谢用户提问。原提示内容不变，执行方式也不变。
- **第四轮检查**（1.0.x，`*.lproj/AppShortcuts.strings`、`NanoMuseChrome.swift`、`NanoMuseShell.swift`、`NanoMuseAgentPage.swift`、`NanoMuseHub.swift`、`NanoMuseBackgroundSettings.swift`、`Localizable.xcstrings`）。Siri 语句补齐九种语言，原来仅英文和两种中文，日语、韩语、德语、西班牙语、法语、俄语都回落英文。Muse 页面标题、抽屉和智能体页名字使用 Dynamic Type，按 `NanoMuseHeaderMetrics` 限制为基础字号 1.35 倍，原固定 17、24 pt。「点子」的「创建例程」现由外壳显示编辑器，避免向当时不可见的目标页请求打开，导致只创建例程而不显示编辑器。「后台与通知」明确：通知来自例程提醒或其他设备，后台刷新只让 iOS 发提醒，不执行例程，不再误称可在后台时段完成任务。编程助手、Reach、`@device` 的 hub 或电脑错误由 `NanoMuseHubErrors` 按代码转换为手机语言，与 Android `HubErrors.describe` 一致，能说明电脑离线、超时、版本太旧不支持动作，不再直接显示远端英文。资源库、账号页分段选择器，以及目标、例程、动态的 `•••` 菜单补上 VoiceOver 标签。
## 朗读回复的声音 {#reply-voices}

语音输出为「系统声音（自动）」时，系统朗读按回复语言，选用「后台与通知」配置的中文或英文声音。如果语音输出明确选定某个系统声音，则优先使用该声音。只有当前启用的输出条目决定声音，默认输出组中排在后面、未启用的成员不会覆盖「自动」。Cloud 语音选择规则不变。

## 通过操作按钮输入语音 {#voice-prompts-from-the-action-button}

「语音提示」是 App 注册的快捷指令，位于 `NanoMuse/VoicePromptIntent.swift`，会打开 nanoMuse 并开始听写。可在「快捷指令」App 绑定到操作按钮，入口为 设置 → 操作按钮 → 快捷指令，也可绑定轻点背面或小组件。按下后，输入框进入语音模式、开启麦克风，识别结果实时写入输入框。发送仍需点发送按钮，避免识别错误因停顿就触发执行。指令可选「会话」参数，留空则用当前聊天。Muse 布局中默认打开主要聊天，若其上有旁聊会先返回。首次与麦克风按钮相同，会请求录音、语音识别权限；拒绝时面板说明，不会录音。

App Intent 是系统调用快捷指令的接口，无法直接控制 SwiftUI 语音面板，冷启动时甚至还没有窗口。因此指令先在 `NanoMuseVoicePrompt` 保存请求；指定会话时，通过与通知相同的 `NotificationNavigationStore`、`.openSessionFromIntent` 跳转。`NanoMuseChatHooks` 只取属于当前聊天的请求，沿现有麦克风按钮流程打开内嵌面板，显示后调用 `VoiceInputViewModel.handleMainButtonTap` 及权限检查开始录音。录音、转写共用原流程，文字仍进入 `inputText`。超过 30 秒的请求丢弃。iOS 的 App Intent 不能接收任意自由语音，所以该指令负责进入语音输入，不能在一句唤起语中直接完成提问；录音时也会打开 App，让用户看到麦克风状态。Siri 语句保存在九种语言各自 `<lang>.lproj` 的 `AppShortcuts.strings`，因最低 iOS 16 而使用传统 `.strings`；指令自身文案在 `Localizable.xcstrings`，见 #296、#298。

## 崩溃与退出诊断 {#crash-and-exit-diagnostics}

构建中缺少 Claude 登录配置时，请求会返回可恢复的服务商错误，不再终止 App。API key 请求不依赖这项配置。检查也覆盖后台标题生成和预热请求，它们使用的模型可能与主要聊天不同。

「设置 → 日志」中的报告会区分残留启动标记和 MetricKit 诊断。标记残留只表示没有正常退出回调将它移除，不能证明发生了崩溃、SIGKILL、看门狗终止或内存故障。其中的阶段和内存数值是最后一次记录的观察值。连续前台退出标记仍作为跳过会话恢复的保护依据，但它只是恢复时使用的判断线索。

报告日期表示生成报告的时间。MetricKit 报告另列诊断覆盖时段，该时段不是事件的准确发生时间；日志尾部也会注明来自生成报告的进程。报告不会把这个进程的终端命令、信号文件或卡顿快照当作更早事件的证据，同一秒收到的报告也会分别保存。排查运行时陷阱需要系统 `.ips` 和对应构建的符号；SIGKILL 应查看系统报告中的 [Termination Reason](https://developer.apple.com/documentation/xcode/sigkill)。

## 在 Mac 上构建 {#building-on-a-mac}

构建环境沿用上游要求，见 [android/BUILDING.md](../../android/BUILDING.md)：较新 Xcode，项目使用 iOS 26 SDK；Homebrew 安装 `ninja meson llvm lld libarchive pkg-config`；构建 rclone 使用 Go 1.25。

```bash
git clone --recurse-submodules https://github.com/nano-muse/nanoMuse.git && cd nanoMuse/android
./deps/build_lame.sh && ./deps/build_ffmpeg.sh          # FFmpeg links against LAME: this order
./deps/build_ish.sh && ./deps/prepare_alpine_rootfs.sh  # the sandbox kernel and its rootfs
./deps/build_rclone_ios.sh                              # Rclone.xcframework
cp src/ios/Configs/ProviderCustomization.xcconfig.example src/ios/Configs/ProviderCustomization.xcconfig
open src/ios/Minis.xcodeproj
```

选择「Minis」scheme，在「Signing & Capabilities」设置你的开发团队，项目默认 `DEVELOPMENT_TEAM` 留空。目标必须是真机，原生库没有模拟器版本，无法在模拟器链接，参见 BUILDING.md 故障排查。

聊天代码须遵守一条构建约束：不要继续向 `AIChatView.body` 修饰器链末尾追加代码。0.1.38 构建 9 表明，这个约六十层链式修饰器的单一表达式，会在 getter 栈中保留不断增大的值副本。该版增加四层就耗尽 iPad 主线程 1 MB 栈，首次引导后显示聊天即崩溃，之后每次启动也崩，堆栈位于 `AIChatView.body.getter` → `__swift_instantiateConcreteTypeFromMangledNameV2`。自有聊天行为应放入 `NanoMuse/NanoMuseChatModifiers.swift` 的 `NanoMuseChatHooks`、`NanoMuseComposerHost`，或新增第三个修饰器，只占一层。输入区在那里特意使用 `AnyView` 降低类型复杂度。`MinisTests/NanoMuseRound6Tests.swift` 测量 body 值大小、类型深度，超过任一上限即失败。

## TestFlight {#testflight}

TestFlight 内部测试员是加入 App Store Connect 团队的用户，最多 100 人，构建处理完几分钟后即可收到，无需 App Review。外部组通过公开链接分发，最多 10,000 人，每个新版本需一次 Apple 测试审核。项目已建立「nanoMuse Beta」及公开链接。将构建交给外部组，运行 `.github/workflows/ios-beta-external.yml` 的「iOS · Beta group」工作流，在「Run workflow」填写 TestFlight 构建号及「What to Test」说明；构建号留空时使用最新构建。Fastfile 的 `external` lane 会加入组、填写说明、提交审核，只需三个 App Store Connect secrets。审核通过后通知测试员。内外测试使用同一条构建发布流程。

### 发布配置与进展 {#where-it-stands}

以下配置于 2026-10-03 完成，均位于账号持有人的开发者账号，团队为 `TN43QYW8K4`，配置材料不放入仓库：

- App 记录为「nanoMuse」，平台 iOS，bundle id `io.github.nanomuse.app`，SKU `nanomuse-ios`，Apple ID `6818802049`。扩展为 `…app.ShareExtension`、`…app.FileProvider`、`…app.AgentWidget`，App Group 为 `group.io.github.nanomuse.app`，iCloud 容器为 `iCloud.io.github.nanomuse.app`。四个 `.entitlements` 要求的 App Groups、含临床记录 HealthKit、HomeKit、iCloud/CloudKit、NFC 标签读取、WeatherKit 均已在标识符开启。
- API key「nanoMuse CI」角色为 App Manager；分发证书「Apple Distribution: Guangyi Liu」有效至 2027-10-03；四个 App Store 描述文件为「nanoMuse App Store」「nanoMuse ShareExtension App Store」「nanoMuse FileProvider App Store」「nanoMuse AgentWidget App Store」。
- 下表六项仓库 secrets 均已配置。
- 内部组「nanoMuse Core」开启自动分发，处理完成后构建自动提供给测试员。此流程不需要注册设备，设备列表特意留空。
- 首个构建 0.1.31 (2) 于 2026-10-03 归档上传，App Store Connect 处理为 `VALID`，Info.plist 已回答出口合规问题，并分发到内部组，成为首个可经 TestFlight 安装的版本。
- 外部测试资料均有英文和简体中文，包括测试版介绍、反馈地址、营销页、隐私政策链接、各构建「What to Test」，不提其他产品。外部组「nanoMuse Beta」公开链接为 `https://testflight.apple.com/join/ZHexbDqc`，「Beta App Review Information」中已设置审核联系人和中继审核账号。
- 1.0.0 构建 16 于 2026-10-09 加入外部组并提审，已通过，取代此前公开链接的 0.1.41 构建 14；标签后修复的 1.0.0 构建 17 只供内部。1.0.1 构建 18 于 2026-10-10、1.0.2 构建 19 于 2026-10-11 提审，两者在 2026-10-12 通过，公开链接随后使用构建 19。1.0.3 构建 22 于 2026-10-12、1.0.4 构建 26 于 2026-10-13 提审，两者在 2026-10-13 通过，公开链接随后使用构建 26。1.0.5 构建 28 于 2026-10-14 提审。1.0.6 构建 29 于 2026-10-24 从 `v1.0.6` 上传，先供内部，加入外部组并审核通过后才进入公开链接。构建 23、24、25 是标签后修复的 1.0.3，27 是同类 1.0.4，均只供内部。公开链接须审核通过后才提供对应构建，审核按版本进行，同版后续构建不重复审核。项目不计划上架 App Store。

### 首次配置 App Store Connect {#once-in-app-store-connect}

1. **创建 App 记录**。 在 Apps → + → New App 选择 iOS，名称 nanoMuse，bundle id `io.github.nanomuse.app`，填写 SKU。自动签名会注册标识符，但 App 记录仍需手动创建。若列表没有 bundle id，先到 Certificates, Identifiers & Profiles → Identifiers 注册。
2. **开启能力**。 按 entitlements 启用 App Groups、iCloud（CloudKit）、HealthKit（含临床记录）、HomeKit、NFC 标签读取、WeatherKit。自动签名通常可开多数能力，首次归档若因某能力失败，则手动启用，并创建 `iCloud.io.github.nanomuse.app` 容器、`group.io.github.nanomuse.app` App Group。WeatherKit 还需在标识符「Services」标签启用。
3. **创建 API key**。 到 Users and Access → Integrations → App Store Connect API → Team Keys → +，角色选「App Manager」，Developer 无上传权限。`.p8` 只能下载一次，并记下表格上方的 Key ID、Issuer ID。
4. **添加测试员**。 到 TestFlight → Internal Testing → + 创建组，加入团队成员。

### 仓库 secrets 配置 {#repository-secrets}

| Secret | 是什么 |
|---|---|
| `APP_STORE_CONNECT_KEY_ID` | API key 的 10 字符 ID。 |
| `APP_STORE_CONNECT_ISSUER_ID` | 签发者 ID，格式为 UUID（通用唯一标识）。 |
| `APP_STORE_CONNECT_KEY_P8` | `AuthKey_<ID>.p8` 完整文本，从 `-----BEGIN PRIVATE KEY-----` 到文件末尾。 |
| `APPLE_TEAM_ID` | 开发团队 10 字符 id，可在开发者账号「Membership details」查看。 |
| `IOS_DIST_P12_BASE64` | 团队「Apple Distribution」证书及私钥，导出为 `.p12` 后编码为单行 base64。 |
| `IOS_DIST_P12_PASSWORD` | 上述 `.p12` 文件的密码。 |

### 证书，以及为什么签名是手动的 {#the-certificate-and-why-signing-is-manual}

最初尝试 Xcode 自动签名，即带 API key 的 `-allowProvisioningUpdates`。它归档时先使用「iOS App Development」描述文件，导出才改签为商店版本；开发描述文件必须至少包含一台注册设备，而仅通过 TestFlight 发布的团队没有设备，因此出现「Your team has no devices from which to generate a provisioning profile」。现改为手动使用无需设备的商店签名材料：上表两项 secrets 保存的 Apple Distribution 证书，以及 App 和三个扩展的四份「App Store」描述文件。每次开始时，`get_provisioning_profile` 使用 API key 下载；若描述文件引用的证书与钥匙串不同，会在账号侧修复。

证书可以不用 Mac 创建，过期或密钥遗失时也可按下面步骤重建。团队可有两到三个分发证书；若达到数量上限，先到 Certificates, Identifiers & Profiles → Certificates 吊销旧证书：

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

私钥只留在维护者本机该目录及仓库 secret 中，不得进入仓库、日志或聊天。描述文件通过同一 API 在账号中创建一次，调用 `POST /v1/profiles`，类型 `IOS_APP_STORE`，每个 bundle id 一份并引用该证书。缺失时发布流程会重新创建。

### 编译检查 {#does-it-compile}

「iOS · build check」位于 `.github/workflows/ios-check.yml`，在 Mac 上关闭签名、面向真机构建，不需要 Apple 账号或 secrets。改动 `android/src/ios/` 的每个 pull request 都会运行。修改 `android/deps/`、尚无 pull request 的分支等情况，可从 Actions → iOS · build check → Run workflow 手动启动。它与 TestFlight 共用原生依赖缓存，应先通过该检查，让编译错误在几分钟内暴露，避免到上传阶段才失败。完整 `xcodebuild` 日志附在运行记录中。`NanoMuse/` 内任一警告都会使检查失败，上游文件不受此限制，零警告要求由流程强制验证。

每个 pull request 还在 Linux 上运行 `tests/test_ios_strings.py`，检查 `Localizable.xcstrings` 的全部键值对，发现重复键即失败。普通 JSON 解析器和 Xcode 会静默保留重复项之一，导致最终翻译取决于哪项被选中，因此需单独检查。

### 执行发布流程 {#running-it}

从 Actions → iOS · TestFlight → Run workflow 启动，或推送 `ios-<anything>` 标签。任务先构建原生依赖，缓存按脚本和 iSH 修订决定；首次约一小时，后续通常为几分钟加归档时间。随后运行 `android/src/ios/fastlane/Fastfile` 的 `fastlane beta` 归档、上传，并将 `.ipa`、dSYM 调试符号附到运行记录。构建号使用工作流运行编号，确保每次比上次新；版本取项目 `MARKETING_VERSION`。Info.plist 的 `ITSAppUsesNonExemptEncryption` 已设 `false`，无需等待出口合规问答。

默认执行器为 `macos-26`。若 GitHub 套餐不提供此标签，可改为 `macos-15`、`xcode-version: latest-stable`，但将缺少项目要求的 iOS 26 SDK。

## 连接器 OAuth 登录 {#connector-oauth}

交换和刷新令牌时会明确请求 JSON 响应。即使服务商返回 HTTP 200，只要响应包含 OAuth 错误，就会视为登录失败。错误提示只显示固定错误码，不展示服务商响应原文或凭据。刷新响应无效时，已保存的令牌不会被替换。

出现 `incorrect_client_credentials` 或 `invalid_client` 时，请核对 OAuth 应用的 client ID；如果服务商要求 client secret，也要核对该值。出现 `redirect_uri_mismatch` 时，请核对服务商登记的回调地址与 App 显示的地址是否一致。出现 `bad_verification_code` 或 `invalid_grant` 时，请重新发起登录。并非所有连接器都需要 client secret。GitHub 的官方文档说明了 [JSON 响应协商](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)和[令牌错误码](https://docs.github.com/en/apps/oauth-apps/maintaining-oauth-apps/troubleshooting-oauth-app-access-token-request-errors)。

## 接下来 {#what-follows}

Android 是 nanoMuse 界面与交互的参照。0.1.34 起，iPhone 在 OpenMinis 上实现了同样的智能体页、聊天换形象、目标、动态、例程和首次引导，并在文字中明确 iOS 后台限制。对应关系如下：

| Android（`io.github.nanomuse.*`） | iOS 上 |
|---|---|
| `cloud`：中继客户端、登录、账号 | 已实现 `NanoMuse/NanoMuseCloud*.swift`、`NanoMuseAccount*.swift`。0.1.32 包含密码、邀请码、人民币额度、用量、会话、时间线和删除。 |
| `ui.onboarding`：带 *登录，免费开始* 的引导 | 0.1.34 由 `NanoMuseFirstRun.swift` 实现，包含首次对话；0.1.35 增加通知页。iOS 没有本机屏幕操作授权页。 |
| `community.StarPrompt`、`community.Nudges`：按中继策略的 star 提示 | 0.1.35 由 `NanoMuseNudges.swift`、`NanoMuseStar` 实现，时机、间隔、上限取自 `/v1/nudges`。 |
| `community.UpdateCheck`、版本行 | 0.1.35 由 `NanoMuseUpdateCheck.swift` 实现，显示已安装和最新版本，先查 `nanomuse.cn/dl/index.json`，再查 GitHub。 |
| `avatar.VideoGen`、`avatar.AvatarMotion`：动作短视频 | 0.1.35 已实现 `NanoMuseVideoGen.swift`、`NanoMuseAvatarMotion.swift`、`NanoMuseMediaModels.swift`。 |
| `nm.show_steps`：智能体的步骤，从 0.1.37 起默认显示 | 0.1.32 由 `NanoMuseSteps.swift` 实现。完成消息仅显示聊天内容，重置主聊天、启动恢复后也相同；活动消息显示步骤。 |
| `connectors`：目录、`SharedConnectors` | 已实现 `NanoMuseConnectors.swift`，0.1.33 接入目录，0.1.34 增加其他设备连接条目。 |
| `ui.home`、`ui.chat`、`ui.settings`、`ui.profile`：外壳、标题栏、智能体页面 | 已实现 `NanoMuseShell.swift`、`NanoMuseHeader.swift`、`NanoMuseAgentPage.swift`、`NanoMuseSettings.swift`。0.1.35 为各功能页加入 Muse 头部，将设置改为卡片，由 `NanoMuseChrome.swift`、`NanoMuseAppearance.swift` 提供。 |
| `avatar`：画出来的脸、从聊天里换、工作室 | 0.1.34 已实现 `NanoMuseAvatarFlow.swift`、`NanoMuseAvatarStudio.swift`、`NanoMuseImageGen.swift`。 |
| `goals`、`feed`、调度器 | 0.1.34 在 iOS 允许范围内实现前台补执行、`BGAppRefreshTask`、本地通知。App 未运行时不保证到点执行，界面已有说明。 |
| `coding`：通过 hub 访问电脑上的编程助手 | 0.1.34 由 `NanoMuseCoding.swift` 实现，电脑需运行 nanoMuse 并登录同一账号。 |
| `reach`：手机操控电脑 | 已通过 hub 在 `NanoMuseReach.swift` 实现。 |
| `hands`：手机自己的屏幕 | 无对应能力，iOS 不允许 App 操作其他 App；可通过 App Intents 或快捷指令接入。 |
| 小组件 | 直接沿用上游 `AgentWidget`。 |

仍需依次在真机验证：用新账号完整走首次引导；确认项目托管账号的媒体入口要求配置自有服务商，再用百炼 key 在聊天更换形象并生成后续四段短片；App 在后台时例程到期，检查测试设备是否获 iOS 刷新机会及频率；连接同账号电脑的编程会话；第二台设备登录后查看连接器列表。

分发继续使用 TestFlight，包括内部组，以及通过 Apple 测试审核后的公开链接。项目不计划上架 App Store。
