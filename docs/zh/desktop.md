# nanoMuse 桌面版

nanoMuse 桌面版将智能体放进一个独立窗口，基于 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（`dsh`）构建。DeepSeek Harness 是负责组织模型、工具和任务执行的框架。nanoMuse 通过插件加入账号、形象、手（Hands，查看和操作本机屏幕的能力），以及 Reach（访问账号下其他设备的能力），见 [harness.md](harness.md)。逐屏布局说明见 [desktop-muse.md](desktop-muse.md)。

桌面版支持 Windows 10+、macOS 12+ 和 Linux x64。各平台都提供安装包，内含 harness、nanoMuse 插件包和手的运行时，无需先安装其他组件。运行时是实际执行屏幕操作等任务的本地程序。

设备授权卡片会跟随所选的浅色或深色外观。每条用户消息的时间和「复制」按钮位于文字与附件下方，靠右排列。将鼠标移到消息上，或用键盘聚焦消息控件，即可显示「复制」。

| | |
| --- | --- |
| Windows | `nanoMuse-Desktop-<version>-win-x64.exe`，使用 NSIS 安装程序。由于没有证书，SmartScreen 会要求选择「仍要运行」 |
| macOS | `nanoMuse-Desktop-<version>-mac-arm64.dmg` / `-mac-x64.dmg`，另有 `.zip`。未经正式签名和公证的版本使用 ad-hoc 临时签名，需要在系统设置 → 隐私与安全性中选择一次「仍要打开」 |
| Linux | 优先使用 `nanoMuse-Desktop-<version>-linux-x64.deb`，也有 `.AppImage` / `.tar.gz`，见 [Linux 注意事项](#linux-notes) |

每次发布都会提供这些安装包，由 `.github/workflows/desktop-app.yml` 构建，并附带 `SHA256SUMS-desktop.txt` 校验清单。Windows 还提供 electron-updater 读取的更新信息：`latest.yml` 记录安装包名称和 SHA-512 校验值，另有安装包的 `.exe.blockmap`。CI（自动构建和检查流程）会在发布前直接用 electron-updater 检查：必须在 `latest.yml` 中找到候选版本，能从测试更新源下载并验证安装包，文件内容与校验值不符时必须拒绝，检查代码为 `harness/desktop/scripts/update-feed-check.mjs`。

更新源位于下载镜像的 [nanomuse.cn/dl/win/](https://nanomuse.cn/dl/win/)。只有 `latest.yml`、安装包、`.blockmap` 全部就绪，而且安装包校验通过，才会切换到新版本；此前继续提供旧版本。源码位于 [`harness/`](../../harness/)，其中 `harness/dsh-nanomuse` 是插件包，`harness/desktop` 是 Electron 外壳。自行构建见 [harness/README.md](../../harness/README.md)。

0.1.29 及之前，同名安装包使用 `desktop/app` 的 Electron 外壳运行 Python 运行时和网页应用，harness 实现另以 *nanoMuse Harness* 名称同时发布。从 0.1.30 起只保留新的桌面版，并沿用应用 id，可以直接覆盖安装旧版。

## Windows 软件内更新 {#updating-on-windows}

Windows x64 应用在启动后及每六小时检查一次较新的正式稳定版。设置页显示当前运行版本，与左下角菜单使用同一更新状态。点击「再查一次」可立即检查。

默认情况下，Windows 确认当前网络不按流量计费后，应用会在后台下载更新。「自动下载更新」开关会保存，重启后仍有效。关闭后不再启动新的自动下载，已经开始的下载可以继续完成。计费网络或无法判断类型的网络仍会检查版本，但菜单会说明暂停下载的原因。主动点击「下载」只覆盖本次限制，不改变开关。

菜单会显示下载及校验进度。electron-updater 验证完整安装包后，才显示「重启更新」。更新圆点表示等待你下载、重试或重启；下载期间不显示更新圆点，下载完成也不弹窗。检查和下载失败都可以从菜单重试。下载失败后最多自动重试两次，分别等待一分钟、五分钟，每次先重新检查开关和网络计费状态。之后等待手动重试或下一次六小时检查；关闭自动下载也会阻止后续检查启动下载。应用先尝试下载镜像，再从 GitHub 获取相同版本、相同校验值的文件。已经下载的安装包再次使用前也会重新验证。

重启更新使用现有安装程序正常的用户级 NSIS 升级流程。对话、设置和账号数据保存在应用文件之外，升级后会重新打开应用。如果正在生成回复、操作电脑、执行远程任务或等待审批，应用会列出受影响的工作，默认选择「继续运行」。只有你明确确认后才结束任务，安装会等待任务停止，交接期间不接收新任务。交接取消或失败后，工作可以继续。

若更新已验证就绪，下次正常退出时也会经过同样的任务保护后安装，并保持关闭。没有就绪更新时，正常执行受保护退出。关闭到托盘、闲置、崩溃或系统关机都不会触发安装。其他平台、旧外壳和独立 harness 仍使用外部下载安装包的方式。不支持软件内更新的旧版，需要先手动下载安装包升级一次。开发构建不会执行安装程序。更新继续遵循已有安装行为，多个混用副本或失效的安装登记需要另外处理。

## Windows 上连接自己的中继 {#using-your-own-relay-on-windows}

桌面版可以连接你自己部署的中继，也就是负责账号和设备消息转发的服务。先按[自己部署](cloud.md#running-your-own)搭好服务器。下面需要填入中继的 HTTPS 地址和已安装的 `nanomuse-desktop.exe` 路径，`relay.example` 和安装路径只是占位示例。不同中继各自保存账号、设备和服务端聊天历史，托管服务中的账号不会自动出现在新中继中。

1. 在 nanoMuse 菜单或托盘菜单选择「退出」，等待应用完全结束。只关闭窗口可能仍在后台运行，再次启动会复用原进程及原来的环境变量。
2. 打开 PowerShell，使用自己的中继和单独数据目录启动：

   ```powershell
   $env:NANOMUSE_CLOUD_URL = 'https://relay.example'
   $env:NANOMUSE_DESKTOP_HOME = Join-Path $env:LOCALAPPDATA 'nanoMuse-self-hosted'
   Start-Process -FilePath 'C:\Path\To\nanomuse-desktop.exe'
   ```

3. 在该中继上注册或登录。以后启动这套中继配置时继续使用同一数据目录，原桌面数据仍保存在原目录。示例变量仅影响本次 PowerShell 会话及其启动的程序，不会写入 Windows 永久环境。之后从开始菜单启动不会继承这些变量，因此使用该中继时仍需运行相同命令。

应用内置的 profile（保存插件与运行设置的配置）将 `NANOMUSE_CLOUD_URL` 用作 `nanomuse-cloud` 插件的 `config.baseURL`。如果 `<desktop-home>/profiles/nanomuse/cordis.patch.yml` 中保存了该插件的覆盖设置，会在内置 profile 之后应用，优先级更高。复用自定义 profile 时，请移除该项覆盖，或将其改为同一中继地址。上面单独的数据目录会拥有独立 profile 和登录凭据。修改自有 key 的模型服务地址，不会改变账号中继。

「网络」中的代理不用于 nanoMuse Cloud，包括中继登录、hub 和同步连接。外壳 `proxy.ts` 中的 `DEFAULT_RELAY_HOST` 只参与生成 `NO_PROXY`（绕过代理的地址列表），不能用来选择中继。上述启动方法用于连接自己的服务器，不能修复托管中继网络路径中的连接重置。

## 桌面版包含什么 {#what-it-is}

首次启动时，先选一个示例任务，再连接模型或跳过，最后开始对话。选中的任务会填入主要聊天的空输入框；已有草稿会保留。模型页可以登录 nanoMuse Cloud、登录 ChatGPT，或添加服务商 key。新建的 Cloud 账号可以设置密码，macOS 还会询问手需要的权限。

「复制」按钮可将文字写入剪贴板。选中文字后右键可复制，在可编辑字段右键可剪切、复制、粘贴或全选，也可使用「编辑」菜单和常用快捷键。网页脚本不能读取剪贴板，通过原生菜单或快捷键粘贴由你主动完成。

Electron 外壳将 dsh Host 作为子进程启动，再把 harness 的网页应用显示在 nanoMuse 窗口中。Host 是管理插件、模型和会话的后台进程。窗口包含聊天、搜索、动态、点子、目标、资源库、设备和底部菜单组成的侧栏；主要聊天与旁聊列表；固定在对话顶部的形象、名字、实时状态和「停止」；以及基于 harness 审批显示的权限卡片。

手的执行轨迹也显示在聊天中，每一步都有截图、画在图上的动作及智能体说明，运行中和结束后都能回看。资料面板包含记忆。设置提供连接器、电脑操作、文件访问、听写、权限，以及带导出和重置的数据控制，导航中的搜索框可按设置文字查找。首次引导占满整个窗口。

智能体的循环、工具、技能、目标、计划模式、上下文压缩、子智能体和 MCP 均使用 dsh 的实现，通过 `nanomuse` 预设采用 nanoMuse 人设，并接入以下功能：

- **账号**。使用手机号或邮箱加验证码登录 [nanoMuse Cloud](cloud.md)，也支持密码和朋友的邀请码。key 保存在 dsh 凭据库中，账号模型通过 harness 原有的 OpenAI 兼容适配器，以 *nanoMuse Cloud* 服务商提供，不加入独立的 nanoMuse 模型适配器。设置 → 账号与手机功能一致，包括以人民币显示的额度池、额度不足时的使用方式、邀请码、按类型和模型统计的用量、密码、持有 key 的设备、账号时间线和注销。数据经 Host 透传接口读取：`/nanomuse/cloud/me`、`/sessions`、`/account-events`、`/password`、`/sign-out-all`、`/delete-account`、`/config`。
- **自选视频形象**。智能体页的铅笔菜单和形象工作室中的「你自己的视频…」可以选择 MP4 或 MOV，最长 15 秒、最大 30 MB，支持 H.264；本机能解码时也支持 HEVC。Windows 和 macOS 有解码器，多数 Linux 构建没有，无法在预览播放的视频会被拒绝。视频先在圆形形象框中预览，再在所有状态下静音循环。它只保存在本机的 `$DSH_HOME/nanomuse/avatar/own-clip.mp4`，不会上传 nanoMuse Cloud。「默认形象」可移除，显示规则见 [avatar.md](avatar.md)。
- **本机的手**。内置运行时通过 `nanomuse mcp` 的 stdio（标准输入输出）提供 `computer_screen`、`computer_act` 及审批。因此安装后即可询问「我屏幕上是什么？」或要求「打开设置把音量调小」。MCP 是连接外部工具的统一协议。实际鼠标、键盘、截图由应用的 `src/operator.ts` 实现，它基于 `@computer-use/nut-js` 移植 UI-TARS-desktop 操作器。运行时通过本机回环 HTTP 服务访问它，每次启动使用新 token（验证调用身份的令牌），环境变量为 `NANOMUSE_OPERATOR_URL` / `NANOMUSE_OPERATOR_TOKEN`，接口为 `GET /info`、`POST /screenshot`、`POST /execute`。各平台只有一套截图和指针坐标路径，无需 `xdotool`、`pyautogui`，坐标以模型看到的图片像素为准，见 [gui.md](gui.md#hands-on-the-computer-the-picture-is-the-unit)。运行时不是由本应用启动时，仍可使用自己的备用后端。`config.toml` 中启用的邮箱、日历、通讯录连接器也通过同一服务器提供，设置 → 连接器中有各自说明。
- **功能页面与记忆**。这里所说的「房间」是聊天以外的动态、点子、目标、资源库页面，与手机版一致。Host 将数据保存在 `nanomuse/rooms.json`，智能体在隐藏会话中生成动态和点子，在各自会话中处理目标，目标自动执行使用 harness 日程插件。资源库作品保存在 `~/nanoMuse/Library`。插件创建的所有聊天，包括用户聊天、后台批处理和其他设备交来的任务，都以 `~/nanoMuse` 为工作区，不直接使用用户主目录。在 Windows 上，若整个用户目录作为工作区，沙箱临时根目录落在其中，会导致 `workspace-write` 命令无法执行，见 [#705](https://github.com/nano-muse/nanoMuse/issues/705)。关于你的记忆也会读入每段聊天，见 [desktop-muse.md](desktop-muse.md#rail-rooms)。
- **Reach**。本机通过 [hub](hub.md) 出现在账号设备列表。`devices`、`device_screen`、`device_shell`、`device_files`、`device_open`、`device_notify`、`delegate` 可访问手机和其他电脑。手机发来的 `delegate` 在本机创建「来自 <device>」dsh 会话，审批传回手机；请求方启用 `stream` 时，回复会随模型生成逐段返回。如果该会话此前被归档，新任务会像用户重新打开并输入一样恢复会话。`shell`、`files`、`open`、`screen` 等远程控制受开关管理。
- **编程助手**。设置 → 编程助手先列出本机 Cursor、Codex、Claude Code、DeepSeek Harness 的聊天，再列出账号下其他电脑。记录从磁盘读取，发送消息会启动助手自己的 CLI（命令行程序），实时显示文字及工具调用，点击「停止」结束。跨设备通过本机也声明支持的 `coding.*` hub 动作完成。设备卡片的「编程助手」标签可打开那台电脑的页面，见 [coding-agents.md](coding-agents.md)。
- **网络**。设置 → nanoMuse Cloud → 网络可配置应用对外请求的统一代理，支持 `http://host:port`、`https://`、`socks5://`、`socks5h://`，可包含 `user:pass@`，显示时会隐藏凭据。dsh Host 的自有 key 请求、ChatGPT 登录、列出模型、工具读取网页、连接器、更新检查及手的运行时都使用它，`nanomuse mcp` 会继承相同变量。nanoMuse Cloud 的中继、hub WebSocket（持续双向通信连接）、同步及本机回环不走代理。外壳将代理与登录启动选项保存在 `desktop.json`，因为地址可能含密码，权限为 0600。启动 Host 时会设置 `HTTP_PROXY`、`HTTPS_PROXY`、SOCKS 所需的 `ALL_PROXY`，以及含 `localhost,127.0.0.1,::1`、`cloud.nanomuse.cn` 和实际中继的 `NO_PROXY`，再设置 `NODE_USE_ENV_PROXY=1` 让 Node 的 fetch 使用这些变量。因此需要重启生效。该行的「立即重启」只重启 Host，窗口保持打开；如有回复、屏幕操作、远程任务或审批，会像退出时一样先询问。自建中继需在启动外壳时设置 `NANOMUSE_CLOUD_URL`，才能加入 `NO_PROXY`，插件也读取这个变量。手机的服务商表单、网页自有 key 表单及运行时的 `[llm] proxy` 提供对应设置，见 [own-key.md](own-key.md#when-the-provider-cannot-be-reached)。
- **长期授权**。设置 → 权限汇总本机保存的全部授权，沿用手机的三组：「不再询问」对应远程控制开关，开启后账号下所有设备都可在本机操作；「卡片上记住的」包含远程控制卡片上总是允许的设备，以及手在某应用、某聊天或某定时任务中的授权；「先执行再告知」目前没有桌面条目。每行写明允许的操作、对象或位置、授权时间，并可「撤回」。对话级授权注明「仅对话「…」」，还会列出它覆盖的该聊天中的定时任务。任务级授权注明「仅定时任务「…」」及所属聊天，任务删除后也会标记。空列表会说明，在审批卡片选「始终」才能保存授权。电脑操作页和资料抽屉保留简短列表，范围说明相同，权限页则展示完整列表。Host 通过 `GET /nanomuse/cloud/grants` 返回列表，`POST /grants/revoke {id}` 撤回任一条。
- **退出前保护任务**。菜单「退出」、Ctrl+Q、托盘「退出」，或没有托盘时关闭最后一个窗口，都会先询问 Host 是否正在生成回复、操作屏幕、执行其他设备任务或等待审批。确认框列出这些工作，默认「继续运行」。只有明确确认才会结束工作，等待停止后再关闭 Host。交接期间的新任务返回 busy，请求设备可稍后重发。菜单栏图标开启时，关窗口只是保留在托盘，不算退出。接口分别为汇总工作状态的 `GET /nanomuse/cloud/work`、控制交接的 `POST /work/gate {open}`、确认停止的 `POST /work/stop`。代理行「立即重启」及 macOS 录屏授权后重启应用，也使用相同确认；单独重启辅助程序不影响 Host 任务。
- **模型调用的来源记录**。从中继 0.31 起，每次调用都会记录其所属设备和任务。harness 适配器每次使用同一组服务商请求头，但调用来源会变化，因此 *nanoMuse Cloud* 服务商先连接插件自己的本机入口 `http://127.0.0.1:<端口>/v1`。启动时优先申请上次端口，保存在 `doorPort`，以便原配置继续有效。如果端口被占用，或配置来自 1.0.7、仍直接指向中继，Host 完成启动后才将配置改为当前本机入口。不能在插件启动阶段等待写入，否则 Host 会在公布地址前卡住，这是 1.0.8、#701 的修复。入口只转发携带本账号 key 的请求，其余返回 401，与中继相同。转发会附带设备、`X-NanoMuse-Platform: desktop` 及 `llm/stream` 钩子登记的信息：`X-NanoMuse-Run` 的 `person`、`schedule`、`goal` 或其他设备任务的 `hub`，对话轮次及步骤序号，操作本机时还包括手的运行和步骤。中继回复原样逐段返回，其轮次 id 保存在会话中。使用自有 key 的轮次也会事后上传相同字段，见 [cloud.md](cloud.md#provenance)。插件还通过 `POST /v1/events` 上传事件代码，不上传文字：每个工具调用的决定、决定来源，包括策略、长期授权、卡片或舞台上的用户、另一台设备、无人及时答复，以及最终是否执行；审批等待时间；手的动作类型、结果、耗时和运行结束方式；轮次被手动停止或出错；以及网页组件通过 `POST /nanomuse/cloud/feedback` 提交的赞踩或停止原因，格式为 `{session, vote: up | down | "", reason?, turn_no?}` 或 `{session, stop_reason, turn_no?}`。原因仅接受中继规定的值，其他返回 400。登录时每隔几秒批量上传，退出登录清空队列，见 [cloud.md](cloud.md#client-events)。
- **回复反馈与停止原因**。登录后，每条回复末尾的引用按钮旁有赞和踩。点踩可选「答错了」「没帮上忙」「不该这么做」「太慢了」「其他原因」或「跳过」。再次点击同一按钮可撤回，给旧回复反馈时，会按上方用户消息确定其轮次。点击「停止」后，输入框上方出现「为什么停下来？」，可选「方向不对」「太慢了」「改主意了」「已经做完了」「其他原因」或「跳过」。回答、跳过、开始下一轮或等待一分半后，提示消失；`live.stopped` 保存仍在等待回答的会话。每个答案只作为一个分类词写入 `turn.feedback`、`turn.stopped`，不附带其他内容。未登录时不显示。

## 额度不足及其他中继响应 {#when-the-allowance-is-used-up-and-the-relay-s-other-answers}

免费额度只限制模型调用，不影响登录。中继返回 `allowance_exhausted` 时，桌面版会在未能执行的那轮消息下显示与手机、网页版相同的卡片：

- 说明免费额度已用完，并告知无论选择哪种后续方式，登录和设备仍可使用。
- **自己的模型 key**：按地区显示服务商，与设置 → nanoMuse Cloud 相同，提供「添加 key」「去拿 key」，下面折叠显示更多服务商和各 key 支持的功能，并附[图文教程](own-key.md)。列表来自中继拒绝响应和 `/v1/me` 中的 `spend.guidance`，没有写死在应用中，见 [cloud.md](cloud.md#allowance)。
- **已经付费的套餐**：可直接登录 ChatGPT，并显示中继提供的相关说明。
- **邀请朋友**：说明朋友发出首个请求后双方获得的奖励，并提供「复制链接」。
- 策略允许时，显示一次在 GitHub 点 star 的提示。标题、按钮和默认说明由应用提供；中继也可通过 `star.text`、`star.text_zh` 提供最长 200 字符的文字。中文界面优先 `text_zh`，否则使用 `text`，见 [cloud.md](cloud.md)。
- 提供「打开设置 → nanoMuse Cloud」和「再试一次」。设置好可用方式后，重试会重新发送同一条消息。

其他拒绝响应会转换为应用语言中的具体说明，不直接展示状态码或 JSON：

| 中继响应 | 卡片说明 | 按钮 |
| --- | --- | --- |
| `413`，请求超过中继限制或模型上下文容量 | 消息过大，建议缩短内容、减少附件或新建聊天 | 「新聊天」 |
| `400 content_rejected`，服务商内容审核拒绝；自有 key 的 `DataInspectionFailed` 也同样处理 | 内容审核未通过，建议换个说法；反复出现时新建聊天，因为被拒绝的内容也可能在早先消息中 | 「新聊天」「再试一次」 |
| `401`，例如其他设备撤回 key、全设备退出或账号删除 | 登录已失效，请在设置 → nanoMuse Cloud 重新登录。桌面版同时退出登录，与 `/v1/me` 返回 401 时相同 | 「登录」 |
| `403`，账号被停用或中继不接受该账号 | 当前账号不能使用 nanoMuse Cloud，下方显示中继说明 | 「打开设置 → nanoMuse Cloud」 |
| 不含额度代码的 `429`，请求过多或服务商繁忙 | 请求过多，请稍候重试；有 `retry_after` 时显示等待信息 | 「再试一次」 |
| `429 daily_cap`，中继设置了每日份额 | 今日份额已用完，明天恢复，下方显示中继说明 | 「再试一次」 |
| `404 model_not_offered` | nanoMuse Cloud 已不再提供该模型 | 「打开设置 → nanoMuse Cloud」 |
| `5xx` 或无响应，例如拒绝连接、超时 | nanoMuse Cloud 没有回应，或无法连接，请检查网络后重试 | 「再试一次」 |
| `429 allowance_exhausted` 且 `paused: true`，中继 0.22 的运营者暂停免费额度，见 [cloud.md](cloud.md#controls) | 显示同一额度卡片，但注明额度只是暂停使用，并未耗尽，登录、设备和余量保持不变 | 可用的后续方式及「再试一次」 |
| `503 service_paused` | 运营者暂时停用了 nanoMuse Cloud，登录和数据保留，请稍后再试 | 「再试一次」 |
| `503 sync_paused` | 中继暂时停止对话同步，已有内容保留，各设备仍可独立使用 | 「再试一次」 |
| `503 hub_paused` | 中继暂时停止设备互联，各设备仍可独立使用 | 「再试一次」 |
| 登录时的 `403 signup_closed` | 显示中继说明：暂时停止新注册，已有账号照常使用 | 「打开设置 → nanoMuse Cloud」 |

拒绝响应不会自动重试。0.1.40 之前，harness 会把中继 `429` 视为限流，额外尝试五次、约二十秒后才显示原始响应；现在立即显示卡片。自有 key 被服务商拒绝时，也按失败类别说明，并将原响应折叠到「返回的原文」。相关实现为 `src/refusals.ts`，Host 在 `llm/stream` 处理链中读取响应并转换为 `nanomuse/<kind>`；聊天卡片由 `src/client/RefusalCard.tsx` 的 `turn-error` 插槽提供。

登录、模型列表、账号、形象工作室、连接器、设备等聊天外页面也统一处理常见故障：无法连接时提示检查网络；超时提示稍后再试；`429` 提示当前请求太多；`401` 提示未登录或登录过期；`5xx` 说明 nanoMuse Cloud 出错，并显示如 503 的状态码，建议一分钟后重试。本机回环 Host 完全无响应时，则提示这台电脑的 nanoMuse 没有响应，需重启应用。其他失败显示「没成功：」及原消息。文字由 `src/client/api.ts` 的 `failureText` 处理；Host 将自身的 `fetch failed` 和超时分别转换为 `unreachable` 503、`timeout` 504。

**使用到 80% 时提醒**。账号模型每完成一轮，Host 会刷新账号数据，最多每分钟一次。中继报告额度池使用到 80% 时，输入框上方会显示可关闭的提示，包括余量、邀请奖励和「看看办法」。每种额度池规模只提示一次，与手机聊天和网页输入框上方的提示一致。

**等待首个输出的提示，1.0.8**。使用账号模型时，在首个 token（模型输出的文本单位）到达前，Host 将会话及开始时间记入 `live.waiting`。`watchRelayStream` 会在第一个数据块、结束或连接中断时移除记录。输入区的 `WaitLine` 前十秒不显示提示，之后显示类似「模型接口比较忙，已等待 15 秒」和「取消」，取消与顶部停止按钮相同。手机也在输入指示点下显示，并可从中继 0.31 状态数据块读取「前面还有 3 个」，见 [cloud.md](cloud.md#protocol)。harness 解析器不转发这类状态块，因此桌面只显示等待时长。

### 检查打包后的运行时 {#checking-a-packaged-runtime}

构建内置运行时后，`python scripts/desktop-app/build-runtime.py --check-only` 会在空工作目录启动它，检查健康接口、网页和工作区位置。检查使用空闲回环端口，启动日志写入临时文件。等待 60 秒仍未就绪时，会显示日志末尾内容，终止子进程，再移除测试数据目录。

## 配置与数据 {#config-and-data}

登录或退出前，会先暂停对话同步，再更换凭据。旧账号的响应不能修改新账号的对话、主要聊天或同步进度，也不能给新账号的模型加入上下文。旧同步请求创建的本地聊天，即使在切换账号期间才完成创建，仍归原请求的账号。已经发给中继的请求可能仍会在服务端完成。

登录或退出如果中途未完成，重启后同步仍会暂停。重新成功登录后才会恢复。

桌面版收到同步中的明确清除通知后，会记住已清除的会话 ID，重启和切换账号后仍有效。任务记录、聊天搜索、历史、复制及继续会话都不能重新打开它们，自动子智能体会话也包括在内。单独保存的副本和普通归档会话仍可使用。清除当前主要聊天时，会创建新的主要聊天。

这限制的是应用内访问，并不从磁盘删除 dsh JSONL 日志。另行授权的文件访问仍可能读到这些日志，完整备份也可能包含。旧版曾在归档后丢弃部分清除映射，因此保护适用于新收到及仍待确认的旧清除通知，无法可靠找回升级前所有已清除会话的映射。

聊天列中选择更多 → 已归档的聊天，可在该列查看和搜索归档。「恢复」会将会话放回普通列表并打开，「返回聊天」回到正常列表。归档只保留到本机，不删除历史。

日志保留一份旧文件 `desktop.log.1`。`desktop.log` 达到 10 MiB 后，下一条日志会写入新文件，并替换较旧备份。轮换失败时仍尝试追加当前条目，之后再重试轮换。

保存的桌面端口被占用时，本次启动临时使用备用端口，不修改原设置。原端口空闲后，下次启动会重新使用它及对应的浏览器设置。临时端口下修改的设置属于该临时 origin，即由协议、主机和端口共同确定的页面来源。

Windows 的桌面环境准备脚本支持带空格的源码和临时目录路径，调用 npm、pnpm 命令脚本时会完整保留各参数。

同一秒生成多份问题报告截图时，后来的文件会添加序号，不覆盖前图。

中继收到对话上传、但响应丢失时，重试沿用消息 ID，避免其他设备收到重复消息。会话映射先保存在本机再上传，重启后仍有效；本地保存失败则暂缓上传，等待下次尝试。

Windows 停止编程任务时，还会请求系统终止其子进程，包括已分离的辅助进程。

设备完成一轮时只清除自己的工作指示。较早的停止通知不能清除同一设备后来开始的工作状态。

账号状态按顺序排队保存，先写私有临时文件，再替换 `cloud.json`。替换前中断，原有完整数据仍在。

同步缓存最多保存 64 份对话日志。需要较早记录时会从磁盘重读，已保存对话仍可访问。

`MEMORY.md` 中记忆旁的日期按本机本地日历计算。

桌面开发冒烟测试在 Windows 等平台通过文件 URL 导入 Electron，源码路径支持空格、Unicode、`#` 和 `%`。

页面加载期间关窗口，不再误报启动失败或退出应用。如果窗口仍开着而页面加载失败，仍会报告错误。

应用的 dsh 数据主目录为 `~/.nanomuse/desktop`，可用 `NANOMUSE_DESKTOP_HOME` 改位置。这里包含 `profiles/nanomuse` 下的 profile、插件列表和用户的 `cordis.patch.yml`，设置和登录流程会在其中写入 *nanoMuse Cloud* 服务商；还有保存账号 key 的 dsh 凭据库、会话、外壳及 Host 的 `desktop.log`，以及记录上次回环端口的 `port`。下次启动先尝试该端口，再尝试 38421，最后选择任意空闲端口，使窗口 origin 及浏览器按该来源保存的数据尽量保持不变。0.1.28 至 0.1.29 的 nanoMuse Harness 主目录 `~/.nanomuse/harness` 会迁入一次。`NANOMUSE_CLOUD_URL` 可更换账号中继，`NANOMUSE_PY` 可更换手的运行时。CLI 自身的 `~/.dsh` 不受影响。

主目录下权限为 0600 的 `nanomuse/hands.json` 保存设置 → 模型解析出的手的服务商、模型、base URL 和 key，与插件交给运行时的 `NANOMUSE_GUI_*` 环境变量相同。从 0.1.41 起，手的 MCP 客户端由 `dsh-nanomuse/hands-tools` 插件挂载，取代固定预设配置。修改「操作屏幕」后，会先等正在执行的调用完成，再释放客户端，用新环境重启 `nanomuse mcp`，无需重启应用。未配置时删除该文件。`nanomuse/rooms.json` 保存动态、目标及其步骤和进度、尝试过的点子、资源库索引及记忆。

`desktop.json` 先写相邻临时文件再替换，上一版保存为 `desktop.json.bak`。磁盘满或崩溃导致保存失败时，仍保留最后一次有效设置，文件损坏后下次启动会从备份恢复。因为代理地址可能含密码，两份文件都仅本人可读。「下载你的智能体数据」逐个文件写入 zip，跳过链接和超过 64 MB 的文件，并删除打包副本 `desktop.json` 中代理地址的密码。

设置 → 插件将所选插件包保存在 `profiles/nanomuse/package.json`。启动时保留列表、顺序及启停选择。只有尚未保存过选择时才写入默认值：日程默认启用，智能体团队和自动授权审查仍由用户选择。旧版若已重置选择，需要重新开启所需插件，无法自动恢复丢失的选择。已有 `cordis.yml`、`cordis.patch.yml` 保留。

## 智能体的桌面使用指南 {#the-agents-desktop-guide}

预设包含 `skill-creator`，用于编写和检查可复用技能。它与 Android、Python 运行时共享不依赖特定模型的说明。两份内置指南都按需加载，不改变审批权限。

另一份技能是 `nanomuse-desktop`。它的简介出现在 DeepSeek Harness 原生技能目录，需要时才由 `skill` 工具读取全文。询问如何连接第二大脑文件夹，也就是你的个人资料目录，或配置桌面功能时，智能体会读取本机指南，无需搜索源码。指南涵盖设置、工作区、权限、连接器与 MCP、技能、记忆和功能页面，Host 会提供实际工作区及 harness 数据目录路径。

若希望所有聊天都能找到某文件夹，指南会说明如何在工作区 `AGENTS.md` 中记录路径，或使用 `$DSH_HOME/AGENTS.md` 跨工作区记录。这只保存指引，不复制文件夹，也不授予权限。写入聊天工作区以外仍需审批，经过 Windows 目录联接或符号链接也一样。输入凭据和没有智能体工具可用的设置，仍需在原设置页完成。

## 模型 {#models}

设置 → 模型位于「通用」之后，按「对话」「操作屏幕」「生成图片」「生成视频」各列一行。登录后，只有中继实时模型菜单支持某项能力时，该行才将 nanoMuse Cloud 排在最前，并标记该用途的推荐模型。其后按设置 → nanoMuse Cloud 中添加的服务商分组，只显示能完成该用途的模型。操作屏幕需要支持图片输入；手使用 OpenAI 接口格式，因此 Anthropic 和原生 Gemini key 只会在行下说明，不列入选项。如果没有可用模型，会说明哪些服务商可用，并提供「添加服务商」。

选择器是写有「服务商 · 模型」的按钮。打开面板后，OpenRouter、硅基流动等长列表默认先显示八个模型，当前模型和该用途的目录默认模型在前，组末提供「还有 {n} 个」。所有组总数超过八个时，上方显示「搜索模型」，可按 id 或名称即时过滤，无结果时显示「没有匹配的模型」。Esc 或点击外部关闭面板。设置 → 图像与视频共用此选择器。折叠、搜索实现为 `harness/dsh-nanomuse/src/client/model-list.ts`，由 `tests/model-list.test.mjs` 检查。

如果在 `llm-pi-ai` 的模型目录中精简某服务商的对话列表，或向 `POST /nanomuse/cloud/providers/save` 传入 `catalogOnly: true`，精简结果会保存在 `cloud.json` 并用于选择器。重启和更新 key 后仍保留，不再合并回完整 `/models` 列表。

未手动选择时，先使用新聊天服务商的该用途默认模型，前提是它是自有服务商并支持该能力；其次是已登录、且实时菜单提供该能力的 nanoMuse Cloud；最后是第一家支持的自有服务商。托管 Cloud 只提供对话和屏幕操作，不提供媒体生成。按这一顺序选择的三行首项为「自动」，并说明当前结果，例如「当前为 nanoMuse Cloud · Qwen/Qwen3.6-27B-FP8」。选择「自动」会清除手动指定，恢复上述顺序。

更换对话模型会改变新聊天默认模型，也会同步更换主要聊天，旁聊保留各自模型。重复选择同一项不会写入设置，手机规则相同。新聊天服务商因移除 key 或退出账号而不可用时，对话模型会转到已登录账号，否则转到另一自有 key，最后回到内置默认值，避免留在没有适配器的路由。0.1.41 的 `no adapter registered for provider "custom"` 就由此产生。

自有 key 的图片请求直接发往服务商：百炼用原生图片 API，OpenRouter 用自身图片 API，其他用 OpenAI 格式，不消耗账号额度，形象工作室在原费用位置会注明。视频使用自己的百炼 key，或明确启用旧媒体代理的自建中继，不使用公开托管账号。

保存 key 后，小卡片会询问「用它来做什么」，每项支持能力各有开关，默认全开。点击「就这样」会将所选用途改用该服务商，选中对话也会更换主要聊天；「暂不」不改变用途选择。自有模型某一轮失败时，已登录用户可选「这次改用 nanoMuse Cloud」，将同一条消息通过账号重试，本轮结束再回到原模型，模型设置页不变。系统不会自行切换。形象或视频生成失败时，需要修复或改选自有服务商，没有托管 Cloud 媒体重试。

登录后，模型页顶部有「使用 nanoMuse Cloud 模型」。关闭后，账号模型退出所有选择器和自动顺序，生成聊天标题、压缩上下文等 harness 附带调用改用对话行的自有模型。仍使用 Cloud 的会话不能直接发送，卡片会提供换模型、新聊天或「这次改用 nanoMuse Cloud」，只有最后一项会在开关关闭时消耗额度。登录、同步、设备及 nanoMuse Cloud 设置继续可用。

关闭时若对话行仍用账号模型，有自有模型则转过去，没有则拒绝关闭，并在开关下说明，因为否则无法回答，所有客户端规则一致。反过来，在关闭状态移除最后一个自有 key，会重新启用账号模型，并把对话行切回账号，key 行也会说明。1.0.1 以前会错误落到没有 key 可用的 dsh 默认模型。

profile 中的 `node_modules/dsh-nanomuse` 是指向应用内插件的链接，Windows 使用 junction（目录联接）。启动时如安装目录与目标不同，会重建链接。例如更新将应用从 `Programs\nanoMuse\nanomuse-desktop` 移到 `Programs\nanomuse-desktop`，旧链接会失效。0.1.39 因 `EEXIST: file already exists, symlink …` 无法启动；0.1.40 起先删除旧链接本身再重建，仍失败时指出需手动删除的路径。如果刚完成软件内更新、安装程序仍占用该项，会在约一秒内重试，再决定是否报启动失败。

Windows 的只读和工作区可写 PowerShell 命令使用 DSH 受限令牌 ACL 沙箱。ACL 是控制文件访问权限的规则。Electron 启动的进程没有自己的控制台，nanoMuse 会在这一执行程序前加入短期 Node 模式辅助进程，在限制令牌前创建无窗口控制台，不支持时用隐藏控制台。PowerShell 子进程继承它，避免在 DLL 初始化时以 `0xC0000142` 退出；临时沙箱目录清理重建后也有效。这不放宽 ACL，也不用于完全访问命令。

首次启动可能耗时数分钟，Windows 尤其明显。Host 只有加载完 profile 所有插件才公布地址，全新安装的 `resources/dsh/node_modules` 约有 20 000 个文件，Windows Defender 首读时逐个扫描，慢盘或外置盘还会更久。0.1.41 及以前，外壳等待 120 秒便报 `the host did not announce its address within 120 s`，而 Host 仍在加载，有报告显示只差六秒就绪。现在只要 Host 还运行就继续等；两分钟后显示「还在启动」、原因及最近输出，十分钟后询问继续等待或退出。只有退出才停止仍在启动的 Host。超过半分钟的启动会在 `desktop.log` 记录 `host: ready after N min`。文件经过首次检查后，第二次通常更快；若每次都慢，将安装目录加入实时扫描排除项可能有帮助。

## macOS 权限 {#macos-permissions}

手需要「录屏」权限截图，需要「辅助功能」权限控制鼠标和键盘。0.1.38 起，这两项属于独立的 **nanoMuse Computer Use** 辅助应用，位置为 `nanoMuse.app/Contents/Helpers/nanoMuse Computer Use.app`，bundle id 为 `io.github.nanomuse.desktop.computer-use`。在系统设置 → 隐私与安全性 → 录屏，以及辅助功能中，需要开启的都是它，而非 nanoMuse 桌面版本身。

macOS 将权限归给 LaunchServices 启动的「责任进程」及其所有子进程，所以应用启动的 Python 运行时不会在权限面板单独出现。通过 `open` 启动的独立应用包则有自己的权限记录，可以用名称说明用途。Qt 的 *The Curious Case of the Responsible Process* 介绍了这种归属，Codex 的 *Codex Computer Use.app* 也采用相同方式。

辅助程序为数百行 Swift，源码在 `harness/desktop/mac/computer-use/`，通过每次启动更换 token 的本机 HTTP 服务报告权限、申请权限、截图和输入。申请使用系统对话框 `CGRequestScreenCaptureAccess`、`AXIsProcessTrustedWithOptions`。macOS 14+ 通过 ScreenCaptureKit 截图，依次为 `SCShareableContent`、主显示器、`SCContentFilter`、`SCScreenshotManager.captureImage`，以显示器像素尺寸捕获并包含光标；macOS 12、13 使用 `CGDisplayCreateImage`。不使用曾在 0.1.36 出现黑帧和无帧问题的 Chromium `desktopCapturer`。输入使用 `CGEvent`，直接发送字符，因此中文也不需要剪贴板。

采用 ScreenCaptureKit 是因为 macOS 26、27 即使已授予录屏，`CGDisplayCreateImage` 仍可能不返回图片。0.1.39 会记录 `helper screenshot failed (no screenshot: noImage)`，再以黑色或过时的 `desktopCapturer` 画面替代。应用现在在启动时拉起辅助程序以读取、申请权限，退出时停止它；主应用消失后，辅助程序也会自行退出。它没有窗口或 Dock 图标，在活动监视器中名为 *nanoMuse Computer Use*。

首次授权按以下操作，只需在尚未授权的 Mac 上完成一次，已在 macOS 27.0.1、Apple 芯片上验证：

1. 先从磁盘映像将 nanoMuse 拖入「应用程序」，再从该目录打开，原因见下文隔离标记。进入设置 → 电脑操作 → 权限，或等到首次使用手时，应用会先说明申请内容和原因。
2. **录屏**。系统提示 nanoMuse Computer Use 请求录制屏幕和音频，点击「打开系统设置」，开启列表中的 **nanoMuse Computer Use**。macOS 15+ 的面板名为「屏幕与系统录音」。系统可能建议「退出并重新打开」辅助程序，任意选择均可，应用会自行重启辅助程序，下一张截图即可捕获实际屏幕。主应用不重启，对话不中断。
3. **辅助功能**。系统再次提示后，在辅助功能面板开启 **nanoMuse Computer Use**，用密码或 Touch ID 确认，立即生效。

权限页实时显示两项状态，明确指出应开启辅助程序。「试一下」会经过实际链路，应用 → 运行时 → 辅助程序，截图并移动鼠标，因此通过这里的测试后，聊天也可使用。关闭某项权限后，下一步操作会提示在系统设置 → 隐私与安全性 → 录屏开启 nanoMuse Computer Use，并说明辅助程序自行重启，主应用无需重启。操作器返回 `403`，运行时不会偷偷改用 `mss` 或 `screencapture`。

**如何检查录屏权限**。辅助程序的 `/status` 返回 `granted`、`denied`、`unknown`。先调用 `CGPreflightScreenCaptureAccess`，直接读取 TCC（macOS 隐私权限管理系统）的结果，不弹窗；否表示 `denied`。macOS 14+ 返回是时，还需调用 ScreenCaptureKit 的 `SCShareableContent` 确认。若抛出 `userDeclined`、`noDisplayList`，仍为 `denied` 并说明原因；其他错误为 `unknown`，下一次仍会尝试截图并报告实际错误。因此 `granted` 表示可实际得到截图，不只是开关处于开启。申请仍通过 `CGRequestScreenCaptureAccess` 系统对话框和设置面板深层链接完成。

**截图失败会明确报告**。只要应用包含辅助程序，操作器就不会用 `desktopCapturer` 替代，以免将黑屏或旧截图冒充当前画面。聊天和 `computer_screen` 会分别说明：

- 缺录屏权限：去系统设置 → 隐私与安全性 → 录屏，开启 nanoMuse Computer Use。辅助程序自行重启，应用不必重启。返回 `403`，设置 → 电脑操作显示相同提示。
- 已授权但 ScreenCaptureKit 出错：显示类似 `no screenshot: nanoMuse Computer Use could not take the picture: ScreenCaptureKit userDeclined (-3801): …` 的错误，包含 SCK 错误名称、代码和系统说明，例如 `noDisplayList`、`failedToStart`、`internalError`，便于查询。
- 辅助程序没有启动：例如仍有隔离标记、没有端口或发生 App Translocation，显示 `no screenshot: nanoMuse Computer Use did not start (…)`，原因取自 `helper:` 日志。设置 → 电脑操作也以「不可用」显示同一原因。

只有不带辅助程序的构建仍保留 0.1.38 之前的 `desktopCapturer` 方式，见下文。

**在 Mac 上核对**。`~/.nanomuse/desktop/desktop.log` 可查看各环节：

- `helper: nanoMuse Computer Use <version> (pid …) at http://127.0.0.1:… — screen granted, accessibility true, capture ScreenCaptureKit` 表示辅助程序已启动，并说明截图方式。macOS 14+ 为 ScreenCaptureKit，12、13 为 `CoreGraphics`。
- `permissions: accessibility=granted screen=granted (nanoMuse Computer Use <version>, capture ScreenCaptureKit)` 是启动时读取的权限。如果设置开关已开却为 `screen=denied`，版本号后会附 ScreenCaptureKit 的原因。
- `operator: helper screenshot failed (…) — not falling back to desktopCapturer` 表示截图失败，附原因，与聊天中的错误相同。不会再出现 `using the Electron path`。

再进入设置 → 电脑操作，点「试一下」，应得到辅助程序截图或上述明确错误。

**隔离标记为何影响启动**。下载的磁盘映像带 macOS quarantine 隔离标记，从中复制的辅助程序等文件也带此标记。通过 Gatekeeper 的「仍要打开」只批准了 nanoMuse，LaunchServices 独立启动的辅助程序仍可能未获批准。此时它会从 `/private/var/folders/…/AppTranslocation/<random>/d/` 的只读转移副本启动，每次路径不同，也可能弹出无法验证的对话框，始终无法响应。

0.1.38 就曾出现辅助程序在活动监视器可见、辅助功能能授权，但录屏列表没有 *nanoMuse Computer Use* 的情况，因为 tccd 记录的是已失效路径。0.1.39 起，应用在首次启动辅助程序前，先对 `Contents/Helpers/nanoMuse Computer Use.app` 执行 `xattr -dr com.apple.quarantine`，日志为 `helper: removed the quarantine flag…`，随后从固定位置启动，权限记录也能保留。这要求应用包可写，放在「应用程序」的用户副本可写。如果直接从磁盘映像或下载目录运行，nanoMuse 自身也可能被转移，无法修复辅助程序，因此不会启动它。日志会要求移入「应用程序」再打开，期间使用下述应用自身路径。

还需注意：

- 录屏授权只对新启动的进程生效，这里是辅助程序。运行时拨动权限开关，应用会自动重启它，日志为 `restarting the helper for the new grant`。权限页「重启」也只重启辅助程序，不重启主应用，多次点击合并为一次；若仍在启动，会等启动后再替换。按钮显示「正在重启…」，直到替换进程响应；失败会显示原因，成功后才清除旧黑屏提示。随后重新测试截图即可检查权限。
- 只捕获和操作主显示器，图片最多 2 Mpx，3456×2234 Retina 会缩为 1758×1137，操作坐标使用 point（点）。0.1.39 起支持跨动作按住按键，即 UI-TARS 的 `press` / `release`。
- 窗口模式只在指定应用窗口中工作。窗口列表和窗口截图也由辅助程序提供，接口为 `GET /windows`、`POST /window`，macOS 14+ 使用 `SCContentFilter(desktopIndependentWindow:)`，因此辅助程序录屏权限覆盖这些操作。输入事件仍由运行时通过 `CGEventPostToPid` 发出，macOS 将其归给 **nanoMuse**，所以还需开启 nanoMuse 自身的辅助功能权限；缺少时会提示并退回整屏。没有辅助程序包时，运行时通过 `CGWindowListCreateImage` 自己截图，日志为 `window mode: the runtime captures windows itself …`，还需 nanoMuse 自身录屏权限。设置 → 电脑操作会说明窗口模式是否可用。
- macOS 15+ 会不定期再次询问，是否允许不经过系统选择器的应用继续截图，请为 nanoMuse Computer Use 选择「允许」。
- 如需重新走授权流程，运行 `tccutil reset ScreenCapture io.github.nanomuse.desktop.computer-use; tccutil reset Accessibility io.github.nanomuse.desktop.computer-use`，再进入设置 → 电脑操作 → 权限。旧版留给 *nanoMuse Desktop* / *nanoMuse* 的授权只用于上面的窗口模式，其他情况下可以关闭。

不包含辅助程序的构建，或尚未执行 `build.sh` 的开发运行，使用 0.1.38 之前的方式：权限归 nanoMuse 桌面版本身，标识符为 `io.github.nanomuse.desktop`，通过 `@computer-use/node-mac-permissions`、`@computer-use/mac-screen-capture-permissions` 读取，`desktopCapturer` 截图，`@computer-use/nut-js` 输入。录屏授权后需「立即重启」应用。如果辅助程序包存在但未启动，则不属于这种情况：手会报告 `helper:` 的具体原因并拒绝操作，直到辅助程序启动，不会改用用户未开启的主应用权限。权限页会指出当前方式。

macOS 将授权绑定到代码签名。Developer ID 签名的 designated requirement（由标识符和开发者团队组成的身份要求）跨构建保持一致，因此授权可跨更新保留。项目证书仍在等待 Account Holder，当前构建使用 ad-hoc 签名，它依赖二进制哈希，每次重新构建辅助程序都会需要两项重新授权，主应用原先也一样。正式证书就绪前，每次升级后需再次开启辅助程序权限；开发时每次 `build.sh` 后也要重新授权。Swift 变化会让 tccd 视为新应用，因此后续 `npm start` 再次申请两项权限；只改 TypeScript 不受此影响。

## macOS 签名 {#macos-signing}

`scripts/desktop-app/package-mac.sh x64` 打包 `dist/mac`，`arm64` 打包 `dist/mac-arm64`，两种构建同时存在也只使用对应目录。应用包不存在或无法唯一确定、内部 Mach-O 签名失败，或应用、辅助程序、磁盘映像验证失败时，打包会报错停止。

运行时准备步骤会保留 PyInstaller 生成的 framework 和库的相对链接，使应用在复制、签名时保持完整的 framework 结构。

未配置 Apple 开发者证书时，应用使用 ad-hoc 临时签名，macOS 会询问一次。配置仓库密钥 `MAC_CERT_P12_BASE64`、`MAC_CERT_PASSWORD`、`APP_STORE_CONNECT_KEY_ID`、`APP_STORE_CONNECT_ISSUER_ID`、`APP_STORE_CONNECT_KEY_P8`，以及可选的 `APPLE_TEAM_ID` 后，`scripts/desktop-app/package-mac.sh` 会使用 Developer ID Application 证书及 hardened runtime（强化运行时），权限文件为 `harness/desktop/resources/entitlements.mac.plist`，再通过 notarytool 公证并将票据装订到产物。证书从「钥匙串访问」导出 `.p12` 后进行 base64 编码，App Store Connect key 使用 `.p8` 文件内容。

macOS runner 通过 `harness/desktop/mac/computer-use/build.sh` 构建 *nanoMuse Computer Use.app*，直接调用 `swiftc`，用 `lipo` 合并 arm64 与 x86_64。部署目标为 macOS 12.3，即首次提供 ScreenCaptureKit 的版本，二进制会链接它，但 SCK 截图仅在 14+ 使用，更早版本使用 CoreGraphics。electron-builder 再通过 `electron-builder.yml` 的 `mac.extraFiles` 将其复制到 `Contents/Helpers`。

`package-mac.sh` 先将辅助程序作为独立应用包签名，使用同一签名身份、强化运行时和自身标识符 `io.github.nanomuse.desktop.computer-use`，不带主应用 entitlements，再签外层主应用。本地构建必须在 `npm run dist:dir` 前运行 `build.sh`，否则 electron-builder 只警告源文件缺失，最终应用没有辅助程序，使用 0.1.38 之前的方式。辅助程序属于 nanoMuse 自有代码，与 iOS 一样，任何 Swift 警告都会使 `build.sh` 失败。

## Linux 注意事项 {#linux-notes}

- **Debian、Ubuntu 及衍生版优先使用 `.deb`**。它安装 `/opt/nanoMuse/nanomuse-desktop`、图标和桌面入口，系统启动器可以识别。安装命令为 `sudo apt install ./nanoMuse-Desktop-<version>-linux-x64.deb`。
- **AppImage 依赖 FUSE**，它会在启动时挂载自己。缺少 `libfuse2`，或容器、企业系统禁止 `fusermount` 时，日志可能显示 `fusermount: mount failed: Operation not permitted` 或 `Cannot mount AppImage, please check your FUSE setup`。可改为解包运行 `./nanoMuse-Desktop-<version>-linux-x64.AppImage --appimage-extract-and-run`，或下载相同应用的 **`.tar.gz`**，解压到任意位置后运行 `./nanomuse-desktop`，无需 FUSE 和 root。
- **点击图标没有反应**。应用只运行一个实例，第二次点击启动器会要求已有实例显示窗口。0.1.36 及以前，关闭窗口后留在托盘的实例可能不响应，0.1.37 起已能重新开窗。若旧实例仍在运行，从托盘「退出」，或运行 `pkill -f /opt/nanoMuse/nanomuse-desktop`，再点击。只有设置 → 通用 → 应用行为的菜单栏开关开启时，关闭窗口才会留在托盘；关闭该开关后，关窗口即退出。两种情况下均可在窗口按 **Ctrl+Q**，或帮助 → 退出；Alt 显示菜单栏。
- **Ubuntu 20.04 看不到托盘图标**。GNOME 3.36 的 appindicator v33 不接受 Electron 44 包含对象路径的总线注册名，因此退回 GNOME Shell 不显示的 XEmbed 托盘。应用仍在运行，只是图标不可见。Ubuntu 22.04+ 可以显示。20.04 可用 Ctrl+Q，或关闭菜单栏选项，让关窗口就退出。
- **使用 WebAssembly 处理图片**。harness 用 sharp 读取和缩放模型输入图及截图。sharp 原生包自带 GLib，而 Electron Linux 连接系统 GLib 并将符号暴露到同进程，见 electron/electron#46323，可能每张图都报 `GLib-GObject-CRITICAL`，部分系统首张解码就以 SIGSEGV 崩溃，读图调用无响应，轮次丢失。因此 Linux 包使用 sharp 的 WebAssembly 版本，不带原生版。单张处理时间约翻倍，2560×1440 截图约 50 毫秒，其他行为相同。1.0.1 及以前可手动修复：在 `resources/dsh/node_modules` 运行 `npm install @img/sharp-wasm32@0.35.5`，删除 `@img/sharp-linux-x64`、`@img/sharp-libvips-linux-x64`，sharp 就会使用 WebAssembly。
- **Wayland 不支持屏幕操作**。手通过 X11 读取屏幕、控制鼠标，因此 Wayland 会话中会说明原因并保持关闭。设置 → 电脑操作的「截一张测试图」及首次询问屏幕内容，都会提示当前是 Wayland，需用 Xorg 登录。运行时不会自行尝试 `xdotool`、`pyautogui`，因为它们即使能在 XWayland 启动，也无法操作可见桌面。登录界面请选择「Ubuntu on Xorg」。会话类型读取 `XDG_SESSION_TYPE`；手动启动的 Wayland 合成器只有 `WAYLAND_DISPLAY` 而没有 `DISPLAY` 时，也会识别为 Wayland。
- **X11 的本机操作**。不需要额外授权。应用操作器通过 libnut 的 XTEST 移动鼠标和输入，通过 Electron 截图，运行时的 `nanomuse mcp` 经本机回环访问。操作器响应正常时不会使用 `xdotool`、`pyautogui`、`mss`。鼠标在启动应用的 X 显示器 `DISPLAY` 上移动，坐标是根窗口像素。HiDPI 下等于逻辑尺寸乘缩放，例如 1920×1080、2 倍缩放对应 3840×2160，模型截图再缩至宽不超过 1600、总量不超过 2 Mpx。

  手工作时，屏幕四周会显示轻微呼吸的光晕，它不应接收点击。每次指针动作前隐藏，完成后立即恢复，并在点击位置显示标记，因此每次点击约闪烁 150 ms。Chromium 改变窗口边界时会清除 X11 输入区域，应用会每次重新设置。如果点击仍到达光晕，会立即重设并记录 `glow: the pointer reached the glow …`。打字和按键不移动指针，光晕不隐藏，也不改变焦点。截图需要窗口管理器，没有时 Electron 可能返回黑帧，运行时会改用自身截图。

  回车、提交、影响较大的快捷键、点击敏感词等步骤，会等待聊天或胶囊中的审批。「允许一次」仅执行该步；「本对话中始终允许」只在当前聊天允许操作该应用；定时任务运行时改为「此定时任务中始终允许」，只作用于该任务，用户在同一聊天手动发起操作仍会询问；「在 <app> 里始终允许」则对全部聊天生效。均可在设置 → 权限撤回。定时任务可能无人值守，因此审批也会发到账号手机，提供「允许一次」「此定时任务中始终允许」「拒绝」。任一处先回答即生效，其他卡片收起，见 [hub.md](hub.md#a-computer-s-own-cards-on-the-phone)。非 ASCII 文字使用 Electron 剪贴板和 Ctrl+V 输入，无需 `xclip`/`xsel`，完成后恢复原剪贴板。
- 日志位于 `~/.nanomuse/desktop/desktop.log`，每个操作器动作各占一行，例如 `operator: click at 1249,1096`。启动器侧日志使用 `journalctl --user -n 200` 查看。
