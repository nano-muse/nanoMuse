# 路线图

nanoMuse 提供开源、低成本的个人智能体方案：在自己的设备上运行，由你选择模型，也可以自行部署中继服务。项目希望和各地的开发者、使用者共同改进，让使用者掌握自己的智能体。你可以提交 [issue](https://github.com/nano-muse/nanoMuse/issues/new/choose)（问题或建议），也可以提交 [PR](../../CONTRIBUTING.md)（供维护者审阅的代码或文档修改）。

本页面向想参与贡献的人，介绍当前重点、后续方向和各模块适合开始的任务。这里不承诺发布日期，功能在真实手机和电脑上验证可用后才发布。

0.1 系列为预览版，1.0.0 是首个稳定版。维护者每天使用手机、桌面、网页和中继，也持续记录尚待改进的问题。项目坚持提供可直接使用的智能体，在不可撤销的操作前审批，不把密钥交给模型，让用户能读写记忆，支持兼容 OpenAI 的模型，并保持软件自由开放。

本页的中继（relay）负责账号与设备通信，运行时是执行任务的程序；「手」指屏幕操作能力；hub 是账号下各设备通信的服务。更多说明见[术语表](glossary.md)。

## 当前重点：补齐与 Muse 的差距 {#now-catching-up-with-muse}

Meta 的 Muse 提供了这类智能体的一种产品形态。以下列出 nanoMuse 仍需改进的方面，以及每个方向可先着手的任务。

### 记忆 {#memory}

智能体使用 `SOUL.md`、`USER.md`、`MEMORY.md`、`HEARTBEAT.md` 和 `remember` 工具保存信息。已有定期整理和嵌入检索，即将文本转成向量后按含义查找记忆。后续需要让智能体在合适时机主动想起相关事实、让用户看见遗忘记录，以及让多台设备共用同一份记忆。

- 模块：`nanomuse/memory/` 中的 `store.py`、`consolidate.py`、`embeddings.py`，手机的 `io.github.nanomuse.sysfiles`，以及桌面资料面板中的「记忆」。
- 相关文档：[desktop-muse.md](desktop-muse.md) 的记忆页、[android.md](android.md)。
- 首项任务已完成：`tests/test_memory_recall.py` 已验证在一次对话中记住的事实，能够在下一次对话首轮主动提及。实现使用 `MEMORY_OPENING_NOTE`，以及 `MemoryStore.relevant` / `relevant_async` 为最新记忆预留的位置。下一步是显示遗忘记录，并同步多设备的记忆库。

### 主动处理任务 {#proactivity}

目前支持按计划检查目标、在 App 关闭后执行例程，以及每天早上生成动态。`nanomuse/triggers/` 已提供四种触发条件：新邮件、即将开始的日历事件、webhook（其他程序发送的事件通知）和账号下的设备上线。后续希望智能体能在定时任务之外发现有用信息，并判断是否值得提醒你。

- 模块：`nanomuse/goals/`、`nanomuse/triggers/`、`nanomuse/nudges.py`，手机的 `io.github.nanomuse.feed` 和 `goals`。
- 相关文档：[every-device.md](every-device.md)，介绍提醒如何到达你当前使用的设备。
- 首项任务已完成：`nanomuse/triggers/store.py` 已加入第四种触发器 `device`，通过 hub 的 `devices` 消息识别设备上线，沿用其他触发器的接口。`arrivals()` 用首条设备列表建立初始状态，仅在设备真正由离线变为在线时触发；`MuseService.device_came_online` 执行匹配任务，并生成「设备上线：…」动态。此功能受 hub 开关控制，测试见 `tests/test_triggers.py` 和 `tests/test_server.py`。下一步是在定时计划之外发现值得提醒的事项。

### 对话体验 {#the-conversation}

聊天承担主要交互，但目前仍有普通聊天客户端的局限。形象反馈和状态行的表现尚未在各客户端统一。自 0.1.22 移除通话后，语音只支持输入，是否朗读回复仍待决定，参见 [calls.md](../calls.md)。

屏幕操作的展示区域称为「舞台」。桌面由 `harness/dsh-nanomuse/src/client/Trajectory.tsx` 和外壳的 `glow.html` 实现，Android 由 `HandsStage.kt` 实现。它们能显示操作过程，桌面还能在每一步之前显示智能体的说明，但各客户端的过程展示仍需要更容易跟随。

- 模块：`harness/dsh-nanomuse/src/client/` 下的 `AvatarChat.tsx`、`Trajectory.tsx`、`Capsule.tsx`，Android 的 `io.github.nanomuse.chat` 和 `hands`，iOS 的 `NanoMuseChatCards.swift` 和 `NanoMuseComposer.swift`。
- 相关文档：[desktop-muse.md](desktop-muse.md)、[parity.md](parity.md) 中各客户端的待补齐项目。
- 建议先做：从 `parity.md` 选择你能运行的客户端中尚未完成的一项，实现并验证它。

### 提高屏幕操作成功率 {#hands-that-succeed-more-often}

Android 和桌面均已支持屏幕操作，桌面操作器移植自 UI-TARS-desktop。常见失败来自定位错误，即模型选错屏幕元素，以及出现意外弹窗后无法恢复。[屏幕操作回归测试](gui-regression.md) 已提供固定模拟任务，用于检查运行时改动，并按需比较真实模型。真实设备上的定位和恢复问题仍需收集失败轨迹。

- 模块：`nanomuse/computer/` 的 `operator.py`、`coords.py`、`screen.py`，`nanomuse/phone/` 的 `operator.py`、`trace.py`，`harness/desktop/src/operator.ts`，以及 Android 的 `io.github.nanomuse.hands`。
- 相关文档：[gui.md](gui.md) 中的操作器约定，以及 [troubleshooting.md](troubleshooting.md)。
- 建议先做：用 `nanomuse/phone/trace.py` 记录一次失败任务，标明出错步骤，并附上轨迹提交 issue。积累十个此类案例后，可组成评测集。

### 简化自行部署 {#self-hosting-in-one-command}

`scripts/self-host.sh` 已能启动带 TLS 的中继。TLS 用于加密网络连接。网页版运行时则使用单独的 `docker-compose.yml`。后续需要将两者整合为一条命令、在升级时保留数据，并说明家庭使用的运行成本。

- 模块：`cloud/` 下的 `docker-compose.yml`、`docker-compose.local.yml`、`Dockerfile`，`scripts/self-host.sh` 和仓库根目录的 `docker-compose.yml`。
- 相关文档：[self-hosting.md](self-hosting.md)、[cloud.md](cloud.md)、[deployment.md](deployment.md)。
- 建议先做：在干净机器上运行 `bash scripts/self-host.sh --local`，记录并报告说明中所有不准确的地方。

### 多语言支持 {#internationalisation}

App 提供英文和中文。Android 还沿用了上游的十五种其他语言，但这些语言中 nanoMuse 自己的文本（`nm_strings.xml`）得到的校对较少。README 目前有十种语言版本。

- 模块：`android/src/android/app/src/main/res/values-*/nm_strings.xml`、`android/src/ios/Localizable.xcstrings`、`harness/dsh-nanomuse/src/client/locales.ts`，以及 `cloud/nanomuse_cloud/` 下的中继控制台。
- 相关文档：[CONTRIBUTING.md](../../CONTRIBUTING.md) 的 *Every string in every language* 一节，说明各语言文本的维护规则。
- 建议先做：用你熟悉的语言打开 App，找出不自然或含义不清的文字，修改对应语言的文件。

## 后续计划 {#next}

- 公开评测集。把收集到的屏幕操作失败案例整理为固定的手机和电脑任务，以展示站的模拟手机为测试环境，见 [showcase.md](showcase.md) 和 `demo/mobilegym/`。每次发布提供可比较的结果。
- 自有屏幕操作模型。使用用户通过「数据控制」自愿贡献的轨迹训练，见 [privacy.md](privacy.md)，再用评测集衡量效果。目标是规模较小、开放模型权重、擅长中文 App 的模型。
- 记忆来源记录。每条事实标注写入模型、时间和确定程度，使错误可追溯，不确定的信息也能明确标示。
- 可分享的技能。目前技能只是 `nanomuse/skills/` 中的文件夹。后续希望支持通过链接安装和分享，并清楚声明执行风险。
- 支持更多设备。浏览器扩展可在已登录的浏览器中操作，手表可提供快捷入口，汽车和家庭设备也可接入。这些设备都作为现有 hub 的新客户端，见 [hub.md](hub.md)。
- 接入小型硬件。先让一块蓝牙开发板实现少量 hub 消息，例如开灯和读取传感器，再逐步探索物理设备。

## 长期方向 {#later-looking-up}

- 物理设备。hub 消息已能表示 *look*、*act*、*ask*，可继续接入机械臂或摄像头。但个人智能体应被允许执行哪些物理操作，仍需探索。
- 长期使用。让记忆持续积累多年仍有用；更换模型后保留用户的名称和形象；支持将导出数据迁移到其他运行时。
- 易读的个人数据。智能体保存的用户信息应能以普通文件读取，也能被其他程序理解，由用户掌握这些数据。
- 个人智能体评估。任务评测只能反映部分表现，是否了解用户、是否在合适时机请求确认，同样需要衡量。目前尚无成熟方法。

## 代码位置 {#where-the-code-is}

仓库分为两部分。`android/` 是通过 `git subtree` 引入并修改的 OpenMinis 1.13。`git subtree` 用于将外部项目作为子目录保留在本仓库中。nanoMuse 的 Android 代码位于 `io.github.nanomuse.*`，iOS 代码位于 `android/src/ios/NanoMuse/`。修改规则见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。

`nanomuse/`、`harness/`、`cloud/` 和 `web/` 由项目自行维护，分别包含为桌面和网页提供屏幕操作的 Python 运行时、DeepSeek Harness 桌面插件、中继和网页控制台。[architecture.md](architecture.md) 介绍整体结构，[AGENTS.md](../../AGENTS.md) 提供简明规则和检查命令。

## 历次发布 {#past-releases}

每个版本从对应 Git 标签构建，并发布为 GitHub release（带安装包的版本发布页），标题为 `nanoMuse <version> · <Codename>`。各版本说明见 [releases/](../releases/)，逐项记录见[更新日志](../../CHANGELOG.md)。

| 版本 | 代号 | 主要变化 |
|---|---|---|
| 0.1.1 – 0.1.11 | Foundation … Hatch | 基于 OpenMinis 建立 nanoMuse，加入名称与形象、主要聊天、授权范围、记忆文件、动态、形象工作室和小龙 |
| 0.1.12 Hands · 0.1.15 Stage | | 支持手机屏幕操作，并通过舞台展示执行过程 |
| 0.1.13 Reach | | 支持从手机控制电脑，0.1.24 起由 hub 替代 |
| 0.1.18 Open | | nanoMuse Cloud 开放注册，无须自备 key 即可开始使用，包含此前已起草但未发布的 0.1.17 Doorstep 内容 |
| 0.1.19 Ensemble | | 发布桌面 App，让运行时接入 hub，并提供 nanoMuse Web |
| 0.1.20 – 0.1.25 | Presence … Mirror | 调整账号引导，加入语音、邀请和手机号登录，统一各设备的形象 |
| 0.1.26 – 0.1.30 | Window … Rooms | 提供展示站，桌面迁至 DeepSeek Harness，采用 Muse 的布局与功能分区 |
| 0.1.31 Locks | | 修复审计发现的问题，避免令牌进入 URL，并要求远程控制先获同意 |
| 0.1.32 – 0.1.35 | Union … Accord | 补齐 iPhone 和桌面与 Android 的界面功能差异 |
| 0.1.36 – 0.1.38 | Thread · Weave · Loom | 从主要聊天开始实现跨设备对话；从 UI-TARS-desktop 移植桌面操作器；用辅助 App 处理 Mac 权限；提供文档站和单命令部署 |
| 0.1.39 | Keys | 各客户端和中继共用服务商能力目录；支持 ChatGPT 套餐登录和共享设备上的账号对话隔离；修复 Ubuntu 点击定位、Mac 辅助 App 授权保持、iPhone 引导后崩溃；补齐各语言并移除终端版 |
| 0.1.40 | Clear | 修复 iPhone 输入框被底栏遮挡并增加检查页；手机对话归属账号，退出时询问处理方式；统一中继拒绝提示；增加控制、统计和官网管理页；Mac 使用 ScreenCaptureKit 获取画面，不再返回替代图；修复移动安装目录后的 Windows 启动；让桌面灯光和操作光晕与手机行为一致 |
| 0.1.41 | Choice | 各客户端提供「模型」页的对话、操作屏幕、生成图片、生成视频四项设置；保存 key 后询问用途；自动选择依次考虑对话服务商、nanoMuse Cloud、首个具备能力的自有服务商；失败后由用户选择「这次改用 nanoMuse Cloud」；桌面使用自有 key 生成图片并即时更新屏幕模型；增加 `PUT /api/connections/image` 和 `/video`；README 加入影片，论文发布至 arXiv，文档站增加简体中文 |
| 1.0.0 | Keel | 首个稳定版，覆盖 Android、iPhone、Mac、Windows、Linux、网页和中继；支持关闭 Cloud 模型来源并使用自有 key 免登录运行；主要聊天跟随所选模型；模型选择器可折叠和搜索；桌面自有 key 可设思考深度；增加「我已经点过 Star」；兼容 Windows 较慢启动；回复跟随 App 语言；`auto` 在已读私密数据后外发或出现警告时请求审批；加固 hub 和中继，清理用户文案中的破折号 |
| 1.0.1 | Ballast | 手机使用独立 URL scheme（应用链接协议），避免与 OpenMinis 冲突；统一内容审核拒绝提示并在中继健康页单独计数；修复桌面同步聊天的起始滚动位置、全程操作光晕和 Windows 形象动画；网页可按用户选择让单轮使用 nanoMuse Cloud；TestFlight 测试版通过 Apple 审核 |
| 1.0.2 | Trim | 修复 `auto` 下 `shell` 和 `send_email` 的哨兵污染规则；Android 可与 OpenMinis 共存；修复桌面操作拒绝后的权限卡、Linux 读图导致的宿主退出、Windows 标题栏遮挡；记忆整理拒绝无法判定的改动；`doctor` 提示无效配置键；改善网页和命令行错误提示；补齐 iPhone 九种语言并清理文档破折号 |
| 1.0.3 | Helm | 将 @Ichiro786 的 Android 聊天设计扩展至 iPhone、网页和桌面，包括与输入框等宽的毛玻璃底栏、黑白消息气泡和渐隐顶栏；三端支持自定义形象视频；桌面和网页支持多个兼容 OpenAI 的端点；修复十项 Android 问题，包括自有 Anthropic key 无法发送；iPhone 操作按钮支持语音提示；各端支持 OpenCode Go；中继镜像改用非特权用户 |
| 1.0.4 | Compass | 在 1.0.3 后一周完成整体检查：邀请奖励改为好友首次请求后发放，展示邀请关系并记录运营操作；MCP 密钥进入保险库，创建例程、触发器或目标前审批；网页支持读屏和菜单键盘操作；桌面支持可解码的 HEVC 视频并列出 DeepSeek Harness 编程助手；Android 加密保存代理密码并跟随模型组；iPad 使用居中聊天列和玻璃底栏；手机可回应其他设备的审批；You.com 支持免 key 搜索 |
| 1.0.5 | Lookout | Compass 次日继续检查：运营控制台可搜索账号、账单和事件，登录接口不泄露停用账号是否存在；运行时列出 DeepSeek Harness 并合并同地址端点；修复桌面八个按钮，退出时保护任务，一分钟内识别 hub 断线，Windows 包含更新描述文件；Android 审批卡适配屏幕，ChatGPT 登录支持代理路径；iPhone 消息可从顶栏下滚动，Siri 短语覆盖九种语言，显示其他设备设置的 emoji；手机与桌面安静生成每日动态；文档改用项目自己的表述 |
| 1.0.6 | Beacon | Lookout 九天后继续检查：nanoMuse Cloud 统一使用多模态 Qwen3.6-27B 处理对话和屏幕，图片与视频改用自有服务商；中继统一错密码与未知账号提示，在同一事务中判断限额，并将每份 Hub 凭据绑定一台设备；运行时恢复重启打断的定时任务，浏览器拒绝私有地址，遗忘记录可查看和撤销；桌面重启前确认，导出数据时跳过文件链接，免登录使用自绘形象，支持设置搜索；手机读取点赞动态，限制已保存审批的适用步骤，加入 Wan 2.7；iPhone 保持隐藏步骤并显示远端任务进度；更新 README 贡献者名单 |
| 1.0.7 | Logbook | Beacon 两天后完善记录：Cloud 完整保存经其回答的轮次并将截图存为文件，App 补传自有 key 的轮次，统一各设备历史；形象短片随形象同步；各端显示服务商和模型；模型只响应 nanoMuse 客户端；重做运营控制台，实时查看模型端点，记录读取不占用模型请求路径；运行时标明调用身份、实时显示推理并支持 Parallel 搜索；桌面校验远程停止和审批者身份；手机支持每日多次定时任务及无文件备份和 shell 发起备份；iPhone 隔离账号；隐私政策说明 hub 保存的设备数据 |
| 1.0.8 | Crew | Logbook 四天后完善设备协作：电脑定时任务可在手机请求审批，各设备显示远端步骤和等待状态，首字等待显示队列位置，记录调用发起者和反馈；中继保持慢请求连接，按问题计数和读取记录；运行时保护 Windows 私密文件，兼容其文件编码，并恢复压缩网页抓取；桌面资源库支持导入文档；修复手机停止语音时崩溃并缩小提示词；iPhone 保持音乐播放并补齐繁体中文；目录加入 Opper、AtmoRouter、API Route 和 Keenable |
| 1.0.9 | Tiller | Crew 同日发布修复版：修复已登录桌面端无法启动（[#703](https://github.com/nano-muse/nanoMuse/pull/703)，对应 [#701](https://github.com/nano-muse/nanoMuse/issues/701)）和中继控制台无法加载大量记录（[#708](https://github.com/nano-muse/nanoMuse/pull/708)）；运行时增加任务预算和全记忆库检索（[#697](https://github.com/nano-muse/nanoMuse/pull/697)、[#696](https://github.com/nano-muse/nanoMuse/pull/696)） |
