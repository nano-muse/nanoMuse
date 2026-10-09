# 故障排查

先跑 `nanomuse doctor`：它会打印正在用的配置文件、数据目录、模型和端点（以及有没有设 key）、工具和连接器，并向模型发一次调用。下面的大多数问题都会先在那里露头。

**手机打不开那个 URL。** 用 `--host 0.0.0.0` 启动（默认只绑定 localhost），确认两台设备在同一个网络里，并在这台机器的防火墙上放行端口。显示出来的 URL 用的是服务器能探测到的局域网地址；如果不对，就用 `ip addr` / `ipconfig` 查到的机器地址，带上同样的 `#token=` 部分（token 放在链接的片段里，从不放在查询字符串里——0.1.31 之前那种 `?token=` 链接会被拒绝，并提示原因）。

**启动时提示「web app not built」。** 你是在一个没有构建前端的检出目录里运行。`cd web && npm install && npm run build`，或者改为安装软件包。

**回复的语言不对。** `agent.language = "auto"` 时，系统提示词会写明你最新一条消息的语言（按文字系统检测）。如果模型还是跑偏，在「你 → 回复语言」里设一个固定语言，或者 `agent.language = "English"`。

**流式回复的开头缺了一截。** 有些代理把 `<think>…</think>` 内联进正文，在服务端会丢掉 `</think>` 之后的头几个 token。非流式的响应是完整的；在 `[llm]` 下设 `stream = false`。

**模型从来不调用工具。** 端点多半是默默忽略了 `tools` 字段而没有报错（*拒绝*这个字段的端点由默认的 `tool_mode = "auto"` 处理）。设 `tool_mode = "prompt"`；工具就会写进系统提示词，并从 `<tool_call>` 块里解析出来。

**日志里出现「does not support tools」，然后智能体接着干。** 这是 `auto` 在尽职：Ollama 拒绝了这个模型的函数调用，于是从那以后工具都写在提示词里。选一个带工具模板的模型（`qwen3:8b`、`llama3.1:8b`），长任务上效果更好。

**用推理模型时回复为空，或者点子一直停在初始列表上。** DeepSeek 的思考版本和 OpenAI 的 o 系列把推理也算进 `max_tokens`；碰到难的提示词，它们可能把整个预算都花在思考上，什么也不返回（`finish_reason = "length"`）。遇到这种情况 nanoMuse 会用四倍预算再问一次。如果还是反复出现，调高 `[llm]` 下的 `max_tokens`（对这些模型来说 16384 是个合理的值）。

**429 / 频率限制。** 请求会按指数退避重试（`max_retries`，默认 5）。调低 `agent.max_steps`，或者把 `web_fetch` 加进 `always_ask_tools` 让循环慢下来。

**终端里一直不出现审批卡片。** `nanomuse daemon` 和 `--auto` 按设计跑在哨兵（Sentinel）的 `auto` 模式下。要交互式审批，用 `nanomuse chat` 或者 App。

**你想做的事被提示「Sentinel blocked」。** 查 `nanomuse audit -n 20` 看原因：一条拒绝规则、`deny_tools`，或者污染（这段对话早先读过私密数据，又出现了新的网络目的地）。把主机加进 `egress_allowlist`，或者允许一次。

**邮件工具返回不了有用的东西。** `scrub_secrets = true` 时，验证码和重置链接会在模型读邮件之前被去掉；这是有意为之。用 `nanomuse config show` 检查 IMAP 设置，用 `nanomuse vault list` 检查保险库条目。

**Playwright 装不上 Chromium。** 较旧的发行版不被新版 Playwright 支持。用 Docker 镜像，或者保持 `browser.enabled = false`；`web_fetch` 能应付大多数阅读类任务。

**nanoMuse 桌面版显示「nanoMuse 没能启动」或「nanoMuse 的后台停止了」。** 外壳把 dsh Host 作为子进程启动，自己的和 Host 的日志都写在 `~/.nanomuse/desktop/desktop.log`（`NANOMUSE_DESKTOP_HOME` 可以换位置）。对话框会引用错误；「复制详情」把版本号、日志末尾和 Host 最后的输出放进剪贴板，发 issue 时贴上；「打开日志文件夹」打开这个文件。Host 后来停了会被重启一次，再出的对话框里有「重新启动」。Windows 上更新之后最常见的原因是配置里的插件链接还指向旧的安装目录（`EEXIST: file already exists, symlink …`；0.1.40 修了，会把链接重建，仍然失败时消息会写出要手动删掉的路径）。第一次启动要花几分钟（Windows 上尤其）不是故障：Host 要加载两万来个文件，实时防护会逐个检查一遍，0.1.41 及之前外壳等 120 秒就放弃了，而 Host 其实还在加载；现在只要进程还在就一直等，两分钟后显示「还在启动」和 Host 最近几行输出，十分钟后问是否继续等。更新不会自己装上：托盘菜单的「下载页（检查新版本）」打开发布页。细节见 [desktop.md](desktop.md#config-and-data)。（0.1.29 之前的桌面版是另一个程序，Electron 外壳里的 Python 运行时，日志在 `~/.nanomuse/desktop-app.log`；下面两条来自那个时期。）

**刚装好就提示「The data folder … is not writable」/「cannot write to the data directory」（Windows，0.1.20–0.1.21）。** 运行时把 `workspace` 文件夹建在了启动器启动它时所在的位置——安装程序打开 App 时是 `C:\Windows\System32`——失败后就停了。从 0.1.22 起工作区默认在 `<data dir>\workspace`，外壳也改在数据文件夹里启动运行时；更新即可，旧版本可以设 `NANOMUSE_WORKSPACE`。

**macOS：把 nanoMuse.app 从 dmg 里拖出来时，Finder 提示「can't complete the operation … error code -36」（0.1.20–0.1.21）。** 那个镜像是 HFS+ 的；从 0.1.22 起 dmg 是 APFS，版本里还附带一个 App 的 `.zip`——下载、双击解压、把 `nanoMuse.app` 拖进「应用程序」。

**macOS：「nanoMuse.app is damaged and can't be opened」或者「Apple could not verify…」。** 没有 Apple 开发者证书的构建是 ad-hoc 签名的，所以 macOS 会问一次（用项目的 Developer ID 签名并公证的版本不会问；怎么做见 [desktop.md](desktop.md#macos-signing)）。打开它，关掉对话框，然后 系统设置 → 隐私与安全性 → 「仍要打开」（或者在终端里 `xattr -dr com.apple.quarantine /Applications/nanoMuse.app`）。Windows 出于同样的原因显示「Windows 已保护你的电脑」：「更多信息」→「仍要运行」。

**Linux：手只看不动——点击落不到任何地方，或者输入 `*` 出来的是 `8`（0.1.37）。** 两个 X11 的 bug，0.1.38 修了。手工作时 App 在屏幕四周画的光晕是一个 X 窗口，它的点击穿透形状 X11 每次映射都会忘掉，所以 0.1.37 的点击都落进了光晕本身（一次 `type` 也可能落进 App 自己的输入区）；另外 libnut 在美式键盘布局的符号上丢掉了 Shift。更新即可（0.1.37 没有变通办法）。更新后还是不行：看 `~/.nanomuse/desktop/desktop.log` 里的 `operator: available · display W×H (scale N)`——`not available (Wayland session …)` 说明登录的是 Wayland 会话（在登录屏幕上选 *Ubuntu on Xorg*；手在 Wayland 下没法工作，设置 → 电脑操作 里的「拍一张测试截图」和聊天里都会这样说）。`display` 是 X 根窗口的像素尺寸；App 说它在 `x,y` 点了一下，可以用 `DISPLAY=:0 xdotool getmouselocation` 核对。一张全黑的图通常说明没有窗口管理器在跑（Electron 的捕获器需要一个；这时运行时会用自己的捕获方式）。点击落在小按钮旁边几个像素的地方（计算器两个键之间的缝）是聊天模型瞄得不准，不是手的问题：指针去的正是模型说的位置（日志行和 `getmouselocation` 一致）。更大的目标、键盘快捷键和打字才是过这类屏幕的可靠办法（智能体自己在按键点不中之后，就改成输入 `12*34` + 回车了）。

**Android App 在「设备」下显示「中继拒绝了连接——重新登录一下」。** 中继不再接受这台手机的 key（在所有设备上退出了登录，或者账号被删了）。在账号页退出再登录；hub 会自己重新加入。

**聊天里说「模型服务商的内容审核没有放行这次请求」。** 负责回答的服务商（nanoMuse Cloud 的上游，或者你自己 key 背后的厂商，比如阿里云的 `DataInspectionFailed`）在模型跑起来之前就读到了对话里它不愿处理的内容，于是直接拒绝。这不是故障，也不会自动重试：卡片上有「再试一次」和「新聊天」。换个说法通常就能过；如果拒绝反复出现，被拦下的多半是对话里更早的内容，开一个新聊天就好。在中继的健康页上，这类拒绝和上游错误分开计数，因为它们说明不了服务商的健康状况。

**全部重置。** 停掉服务器，删除 `~/.nanomuse`（或者你的 `data_dir`）。保险库的密钥也在那里，需要的话先把秘密导出来。
