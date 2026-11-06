# 故障排查

先运行 `nanomuse doctor`。它会列出当前使用的配置文件、数据目录、模型、端点（接收模型请求的服务地址）、是否已配置 key（访问服务的密钥）、工具和连接器，并向模型发送一次请求。下面多数问题都能先通过这条命令找到线索。

**手机打不开 URL**。 启动时加上 `--host 0.0.0.0`，默认配置只允许本机通过 localhost 访问。确认手机和服务器在同一网络，并在服务器的防火墙中放行所用端口。启动时显示的 URL 使用服务器自动检测到的局域网地址。如果地址不对，用 `ip addr` / `ipconfig` 查出服务器的实际地址，替换 URL 中的地址，并保留原来的 `#token=` 部分。这里的 token 是访问凭据，放在链接中 `#` 后的片段里，不放在查询参数中。0.1.31 之前使用的 `?token=` 链接会被拒绝，页面会说明原因。

**启动时显示「web app not built」**。 当前运行的源码目录还没有构建网页前端。执行 `cd web && npm install && npm run build`，或者改为安装已打包的软件包。

**启动时显示「port 8787 on 127.0.0.1 is already in use by nanoMuse 1.0.1」**。 已有一个 nanoMuse 服务占用了该端口，可能来自之前的 `nanomuse serve`、后台守护进程或容器。此时 `serve` 会直接退出，不会读写数据目录。可以在浏览器中打开已有服务，或者先停止它再启动新的服务。加上 `--port 8790` 可以让新服务使用另一个端口，与原服务同时运行。如果提示中写的是「by another program」，则是其他程序占用了端口，同样需要停止该程序或换端口。

**回复语言不符合预期**。 设置 `agent.language = "auto"` 时，程序会根据你最新一条消息所用的文字判断语言，并写入系统提示词。如果模型仍然使用其他语言，在 你 → 回复语言 中指定语言，或者设置 `agent.language = "English"`。

**流式回复缺少开头的文字**。 流式回复会边生成边显示。有些代理服务把 `<think>…</think>` 插在正文里，随后在服务端处理时丢失了 `</think>` 后的几个 token（模型处理和生成文字时使用的计数单位）。同一请求改用非流式响应时，内容通常完整。可以在 `[llm]` 下设置 `stream = false`。

**模型始终不调用工具**。 服务端可能忽略了 `tools` 字段，而且没有报错。默认的 `tool_mode = "auto"` 能处理明确拒绝这个字段的服务，无法识别这种静默忽略。设为 `tool_mode = "prompt"` 后，程序会将工具说明写进系统提示词，并从模型返回的 `<tool_call>` 块中解析调用。

**日志出现「does not support tools」，但智能体继续运行**。 这是 `auto` 模式的正常处理方式：Ollama 拒绝了该模型的函数调用功能，程序随后改用提示词描述工具。长任务建议使用带工具调用模板的模型，例如 `qwen3:8b` 或 `llama3.1:8b`。

**使用推理模型时，回复为空，或者「点子」始终只有初始列表**。 DeepSeek 的思考模型和 OpenAI o 系列会把推理过程计入 `max_tokens`。问题较难时，模型可能耗尽全部额度用于推理，最终没有输出正文，此时会返回 `finish_reason = "length"`。nanoMuse 会将额度提高到四倍，再请求一次。如果仍经常发生，在 `[llm]` 下提高 `max_tokens`，这些模型可以考虑设为 16384。

**出现 429 或频率限制**。 程序会逐次延长等待时间再重试，这种方式称为指数退避。重试次数由 `max_retries` 控制，默认是 5。可以调低 `agent.max_steps`，或把 `web_fetch` 加入 `always_ask_tools`，让工具执行循环放慢。

**网页控制台或桌面版聊天中的审批卡片没有出现在手机上**。 审批卡片用于询问你是否允许某项操作。电脑只会将 nanoMuse 桌面版定时任务的卡片推送到同一账号的手机，因为任务执行时电脑旁可能没人。有人正在输入的聊天，卡片仍留在该聊天中；Python 运行时（执行智能体和工具的后台程序，`nanomuse serve`）目前也不推送这些卡片。如果桌面版定时任务的卡片同样未到达，请检查中继（负责账号和设备间通信的服务器）是否为 0.31 或更新版本，其 `welcome` 消息应包含 `event_push`；手机是否登录同一账号，且 App 已打开或已开启 hub（设备互联）通知；以及该步骤是否真的需要询问。已由「此定时任务中始终允许」或 设置 → 权限 中的授权覆盖的步骤，不会在任何设备上生成卡片。参见 [hub.md](hub.md#a-computer-s-own-cards-on-the-phone)。

**终端始终没有审批卡片**。 `nanomuse daemon` 和 `--auto` 按设计使用哨兵（Sentinel，执行前检查风险和权限的组件）的 `auto` 模式。需要逐项确认时，请使用 `nanomuse chat` 或 App。

**想执行的操作被「Sentinel blocked」拦住**。 运行 `nanomuse audit -n 20` 查看原因。可能是拒绝规则、`deny_tools` 配置，或数据污染检查：当前对话已读过私密数据，现在又要把数据发往一个新的网络地址。可以把目标主机加入 `egress_allowlist`，或对此次操作选择「允许一次」。

**邮件工具没有返回需要的内容**。 开启 `scrub_secrets = true` 后，程序会先删除邮件中的验证码和密码重置链接，再交给模型阅读，这是预期行为。用 `nanomuse config show` 检查 IMAP（收取邮件的协议）设置，用 `nanomuse vault list` 检查保险库中的条目。

**Playwright 无法安装 Chromium**。 新版 Playwright 不再支持部分较旧的系统发行版。可以使用 Docker 镜像，或者保持 `browser.enabled = false`。多数只需读取网页的任务可以由 `web_fetch` 完成。

**桌面版显示「nanoMuse 没能启动」或「nanoMuse 的后台停止了」**。 桌面外壳会启动 dsh Host（承载桌面插件的后台进程），并把自身及 Host 的日志写入 `~/.nanomuse/desktop/desktop.log`。可通过 `NANOMUSE_DESKTOP_HOME` 更改目录。弹窗会显示具体错误；「复制详情」会把版本、日志末尾和 Host 最近的输出复制到剪贴板，供你提交问题；「打开日志文件夹」可以打开日志位置。如果 Host 在运行中退出，外壳会自动重启一次，之后再退出时，弹窗会提供「重新启动」。Windows 更新后常见的原因是配置中的插件链接仍指向旧安装目录，报错为 `EEXIST: file already exists, symlink …`。0.1.40 已改为重建链接；如果重建失败，提示会指出需要手动删除的路径。

第一次启动耗时几分钟，尤其是在 Windows 上，未必表示失败。Host 需要加载约 20 000 个文件，实时安全扫描会逐个检查。0.1.41 及之前，外壳会在 120 秒后放弃等待，尽管 Host 仍在加载。现在只要进程仍在运行就会继续等待；两分钟后显示「还在启动」及 Host 最近的输出，十分钟后询问是否继续等待。Windows x64 版支持在 App 内下载和安装更新，流程见[桌面版更新说明](desktop.md#updating-on-windows)。其他平台及未提供此更新功能的版本，通过应用菜单中的「帮助 → 下载页（检查新版本）」打开发布页。详见 [desktop.md](desktop.md#config-and-data)。0.1.29 及之前的桌面版采用另一套程序，即 Electron 外壳中的 Python 运行时，日志位于 `~/.nanomuse/desktop-app.log`。下面两条问题发生在那一时期。

**安装后立即提示「The data folder … is not writable」或「cannot write to the data directory」（Windows，0.1.20–0.1.21）**。 当时运行时会相对于启动器的当前目录创建 `workspace` 文件夹。安装器直接打开 App 时，该目录是 `C:\Windows\System32`，因此创建失败，程序随即退出。从 0.1.22 起，默认工作区改为 `<data dir>\workspace`，外壳也会在数据目录中启动运行时。升级即可；如果必须使用旧版，可以设置 `NANOMUSE_WORKSPACE`。

**macOS：从 dmg 拖出 nanoMuse.app 时，Finder 提示「can't complete the operation … error code -36」（0.1.20–0.1.21）**。 当时的镜像使用 HFS+ 文件系统。0.1.22 起改为 APFS，并同时提供 App 的 `.zip` 文件。下载 zip，双击解压，再把 `nanoMuse.app` 拖入「应用程序」。

**macOS 提示「nanoMuse.app is damaged and can't be opened」或「Apple could not verify…」**。 没有 Apple 开发者证书的构建采用 ad-hoc 签名，因此 macOS 会要求确认一次。使用项目 Developer ID 签名并通过公证的版本可以直接打开，签名方式见 [desktop.md](desktop.md#macos-signing)。先尝试打开 App，关闭提示，再到 系统设置 → 隐私与安全性 选择「仍要打开」；也可在终端执行 `xattr -dr com.apple.quarantine /Applications/nanoMuse.app`。Windows 出于同样原因会显示「Windows 已保护你的电脑」，可依次选择「更多信息」→「仍要运行」。

**Linux：「手」只能看屏幕，无法操作，点击没有反应，或者输入 `*` 却得到 `8`（0.1.37）。** 「手」是读取屏幕并执行点击、输入等操作的功能。0.1.38 修复了两个 X11 问题。其一，屏幕边缘的光晕本身是一个 X 窗口，每次显示窗口时，X11 都会丢失其允许点击穿透的设置，所以 0.1.37 的点击落在光晕上，`type` 甚至可能把文字输入 App 自己的输入框。其二，libnut 在输入美式键盘布局的符号时丢失了 Shift。请升级，0.1.37 没有替代解决方法。

升级后若仍有问题，检查 `~/.nanomuse/desktop/desktop.log` 中的 `operator: available · display W×H (scale N)`。如果显示 `not available (Wayland session …)`，说明当前登录的是 Wayland 会话。请在登录界面选择「Ubuntu on Xorg」。「手」不支持 Wayland，设置 → 电脑操作 中的「拍一张测试截图」和聊天都会说明这一点。`display` 表示 X 根窗口的像素尺寸；程序报告在 `x,y` 点击后，可以用 `DISPLAY=:0 xdotool getmouselocation` 核对。截图全黑通常表示没有运行窗口管理器，Electron 的截图组件需要它，此时运行时会改用自身的截图方式。若点击只偏离小按钮几像素，例如落在计算器两个按键之间，则是模型给出的坐标不准；指针实际到达的位置与模型坐标、日志和 `getmouselocation` 一致。这类界面可以优先使用较大的目标、键盘快捷键或直接输入。智能体在点不中计算器按键后，也会改为输入 `12*34` 并按回车。

**Android App 的「设备」页显示「中继拒绝了连接；重新登录一下」**。 中继已不再接受这台手机的 key，可能是账号已在所有设备上退出，或账号已被删除。在账号页退出并重新登录，hub 就会自动重新连接。

**聊天提示「模型服务商的内容审核没有放行这次请求」**。 负责回答的服务商在调用模型之前，就拒绝处理对话中的某些内容。它可能是 nanoMuse Cloud 的上游服务商，也可能是你自己的 key 对应的服务商，例如阿里云会返回 `DataInspectionFailed`。这类拒绝不是服务故障，程序不会自动重试；卡片会提供「再试一次」和「新聊天」。改换措辞通常可以继续。如果仍被拒绝，触发审核的内容可能位于较早的消息中，可以新建聊天。在中继的「健康」页中，这类拒绝与上游错误分别计数，因为它不能反映服务商是否正常运行。

**重置全部数据**。 先停止服务器，再删除 `~/.nanomuse` 或你设置的 `data_dir`。保险库的加密密钥也在其中，如需保留秘密信息，请先导出。
