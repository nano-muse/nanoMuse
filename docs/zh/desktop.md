# nanoMuse 桌面版

设备授权卡片会跟随浅色或深色外观。聊天中，每条用户消息的时间和复制按钮
都在文字及附件下方靠右排列。将鼠标移到消息上，或用键盘选中按钮，即可显示复制操作。

电脑上的 Muse，装在一个窗口里：nanoMuse 建在
[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（`dsh`）之上，窗口的
布局一屏一屏见 [desktop-muse.md](desktop-muse.md)，账号、形象、在这台电脑屏幕上动手的
「手」（Hands）、够得着账号下每一台其他设备的 Reach，都以插件的形式加进来
（[harness.md](harness.md)）。支持 Windows 10 以上、macOS 12 以上和 Linux x64；每个平台一个
安装包，不需要先装别的：harness、nanoMuse 插件包和负责手的运行时都在里面。

| | |
| --- | --- |
| Windows | `nanoMuse-Desktop-<version>-win-x64.exe`（NSIS；没有证书，所以 SmartScreen 会要你点「仍要运行」） |
| macOS | `nanoMuse-Desktop-<version>-mac-arm64.dmg` / `-mac-x64.dmg`（另有 `.zip`）；除非该版本签了名并公证过，否则是 ad-hoc 签名，需要在「系统设置 → 隐私与安全性」里点一次「仍要打开」 |
| Linux | `nanoMuse-Desktop-<version>-linux-x64.deb`（推荐）/ `.AppImage` / `.tar.gz`；见 [Linux 注意事项](#linux-notes) |

每个版本都带着这些安装包（`.github/workflows/desktop-app.yml`；旁边有 `SHA256SUMS-desktop.txt`）。
Windows 版本还带着 electron-updater 要读的更新元数据：`latest.yml` 写着安装包的名字和它的
SHA-512，旁边是安装包的 `.exe.blockmap`。CI 在把它们附上 release 之前，会先让 electron-updater
亲自检查这一套：它必须能在 `latest.yml` 里找到候选版本、从测试源下载安装包并校验通过，字节对不上
的会被拒绝（`harness/desktop/scripts/update-feed-check.mjs`）。这套元数据对应的更新源是下载镜像的
[nanomuse.cn/dl/win/](https://nanomuse.cn/dl/win/)：只有当一个版本的 `latest.yml`、安装包和 `.blockmap`
三个都到齐、安装包的字节也对得上时，它才切到这个版本；在那之前继续提供上一个版本。
代码在 [`harness/`](../../harness/) 下：插件包在 `harness/dsh-nanomuse`，Electron 外壳在
`harness/desktop`；自己怎么构建见 [harness/README.md](../../harness/README.md)。到 0.1.29 为止，
同名的安装包装的是 Python 运行时和网页版，套在它们自己的 Electron 外壳里（`desktop/app`），
harness 构建以 *nanoMuse Harness* 的名字另放在旁边；从 0.1.30 起只有这一个桌面版，直接覆盖安装
在旧的上面（应用 id 相同）。

## Windows 软件内更新 {#updating-on-windows}

Windows x64 桌面版在启动后和每六小时检查一次较新的正式稳定版。设置里的版本信息
和左下角菜单共用同一份更新状态，点击「再查一次」立即刷新。

默认在 Windows 确认网络不按流量计费时后台下载更新。设置中的「自动下载更新」开关会
保存，重启后继续沿用。关闭后不再开始新的自动下载，已经进行的下载可以完成。计费或
无法识别的网络仍会检查版本，菜单说明暂停原因；主动选择「下载」可以覆盖本次暂停，
不会修改自动下载开关。

菜单会显示下载进度和校验状态，完整安装包
通过 electron-updater 校验后，才显示「重启更新」。橙点表示需要你下载、重试或重启；
下载中没有更新橙点，完成后不弹窗。检查和下载失败都能从菜单重试。下载失败后最多
自动重试两次，分别等待一分钟、五分钟，每次重新检查开关和网络计费状态。耗尽后等待
主动重试或下一次六小时检查；关闭自动下载后，后续检查也不会开始下载。下载先尝试官方镜像，
失败后从 GitHub 获取同版本、同校验值的包。已下载的完整包复用前会再次校验。

重启更新沿用现有用户级 NSIS 的正常原地升级流程，保留应用程序文件之外的对话、设置
和账号数据，安装后重新打开软件。有回复、电脑操作、远端任务或待审批工作时，软件先列出
受影响的工作，默认继续运行。只有你明确确认结束，才中止工作；安装须等中止完成，交接期间
不接收新工作。取消或交接失败后可以继续工作。

下次主动真正退出时，已经校验就绪的更新会经过同样的工作保护再安装，完成后保持退出。
没有已就绪更新时沿用正常的受保护退出。关闭到托盘、空闲、崩溃和系统关机都不请求安装。
其他平台、旧桌面壳和独立
harness 保留外部下载方式。不带软件内更新能力的版本，需先下载安装包升级一次。
开发构建不会运行安装器。更新沿用现有安装行为，混合安装副本或过期的安装登记需另行整理。

## 它是什么 {#what-it-is}

页面里的「复制」按钮可以把文字写入剪贴板。选中文字后右键可以复制，在输入框里右键可以
剪切、复制、粘贴和全选，也可以使用「编辑」菜单和常用快捷键。网页脚本不能读取剪贴板，
通过原生菜单或快捷键粘贴仍由你主动操作。

一个由外壳作为子进程启动的 dsh Host，把 harness 的网页应用显示在我们自己的窗口里：侧栏
（聊天、搜索、动态、点子、目标、资源库、设备，还有汉堡菜单），放着主要聊天和旁聊的聊天列，
钉在对话上方的形象和名字，带一行实时状态和「停止」，盖在 harness 审批之上的权限卡片，
聊天里手的一次运行的轨迹（每一步的截图、画在上面的动作和智能体说的话，运行中和运行后都能
回看），带记忆的个人资料面板，那些设置页（连接器、电脑操作、文件访问、听写、权限、
带导出和重置的数据控制，导航里有一个搜索框，按设置项自己的文字就能找到它），以及占满
整个窗口的第一次打开。智能体是 dsh 的（它的智能体循环、
工具、技能、目标、计划模式、压缩、子智能体、MCP），通过 `nanomuse` 预设以 nanoMuse 的身份
说话，再加上：

- **账号**：手机号或邮箱加验证码（或者密码，配上朋友的邀请码），对着
  [nanoMuse Cloud](cloud.md) 登录；key 放在 dsh 的凭据存储里；账号的模型作为 harness 自带的
  OpenAI 兼容适配器下的 *nanoMuse Cloud* 服务商（模型通路上没有任何我们自己的东西）；
  「设置 → 账号」就是手机上那整个账号页（以人民币计的额度池和额度快用完时继续用的几条路、
  邀请码、按类型和按模型的用量、密码、持有 key 的设备、时间线、注销），通过 Host 的透传路由
  读出来（`/nanomuse/cloud/me`、`/sessions`、`/account-events`、`/password`、`/sign-out-all`、
  `/delete-account`、`/config`）；
- **一段你自己的视频当形象**：智能体页面钢笔菜单和形象工作室里的「你自己的视频…」接受一段
  MP4 或 MOV（最长 15 秒、最大 30 MB；H.264 视频，或这台电脑能解码的 HEVC：Windows 和 macOS
  带解码器，多数 Linux 构建没有，预览放不出来的视频会在那里被拒绝），先在形象的圆形框里预览，再在所有状态下
  静音循环播放；视频只保存在这台电脑的 `$DSH_HOME/nanomuse/avatar/own-clip.mp4`，不会发给
  nanoMuse Cloud，「默认形象」可移除（回退规则见 [avatar.md](avatar.md)）；
- **手（Hands）**，在这台电脑上：自带运行时的 `nanomuse mcp` 走 stdio，运行时的
  `computer_screen` 和 `computer_act` 工具连同它们的审批一起接进来，所以「我屏幕上是什么？」
  和「打开设置把音量调小」开箱就能用。鼠标、键盘和截图是应用自己的（`src/operator.ts`，
  把 UI-TARS-desktop 的操作器移植到了 `@computer-use/nut-js` 上），通过一个带每次启动随机令牌的
  回环 HTTP 服务器回答运行时（运行时环境里的 `NANOMUSE_OPERATOR_URL` /
  `NANOMUSE_OPERATOR_TOKEN`；`GET /info`、`POST /screenshot`、`POST /execute`）：每个平台上
  都是同一条截图路径、同一个指针坐标空间，不需要 `xdotool` 或 `pyautogui`，坐标就是模型看到的
  那张图的像素（[gui.md](gui.md#hands-on-the-computer-the-picture-is-the-unit)）。不是由这个
  应用来跑运行时的时候，运行时自己的后端仍然是退路。运行时 `config.toml` 里打开的连接器
  （邮箱、日历、通讯录）经同一个服务器送过来，「设置 → 连接器」里有每一个的设置方法；
- **房间**：动态、点子、目标和资源库，和手机上的一样，由 Host 保存在
  `nanomuse/rooms.json` 里，由智能体在隐藏聊天里写（动态和点子）或在各自的聊天里写（目标，
  自动化部分用 harness 的日程插件；资源库里的作品放在 `~/nanoMuse/Library` 下；插件开的每一段聊天，
  不管是给人的、自己的一批还是别的设备发来的任务，都从 `~/nanoMuse` 这个工作区开始，绝不直接落在
  用户主目录——Windows 上，工作区若是整个用户目录，`workspace-write` 的命令一条也跑不了，因为沙箱的
  临时目录就在它里面，[#705](https://github.com/nano-muse/nanoMuse/issues/705)），再加上记忆：
  它对你的了解，每段聊天都会读进去（[desktop-muse.md](desktop-muse.md#rail-rooms)）；
- **Reach**：这台电脑出现在账号的设备列表里，走 [hub](hub.md)（设备互联）；`devices`、
  `device_screen`、`device_shell`、`device_files`、`device_open`、`device_notify` 和 `delegate`
  这些工具面向手机和其他电脑；手机发来的 `delegate` 在这里落成一段「来自 <device>」的 dsh
  会话，它的审批被转回手机，发起方要求时（`stream`）模型边写边把文字发过去；如果这段聊天在上次任务后被归档，
  新任务到来时会先恢复聊天，和打开聊天继续输入一样；远程控制（`shell`、`files`、`open`、`screen`）在一个开关后面；
- **编程助手**：「设置 → 编程助手」，这台电脑上的 Cursor、Codex、Claude Code 和 DeepSeek Harness
  聊天（从磁盘读取，发一条消息就启动助手自己的 CLI，运行连同它的工具一边跑一边显示，「停止」
  结束它），之后是账号下其他电脑的，走这台电脑同样声明的 `coding.*` hub 动作；设备卡片上的
  「编程助手」标签打开那台电脑的这一页（[coding-agents.md](coding-agents.md)）。
- **网络**（设置 → nanoMuse Cloud → 网络）：给这个应用对外请求用的一个代理（`http://host:port`、
  `https://`、`socks5://` 或 `socks5h://`，可以带 `user:pass@`，显示时会遮住）。dsh Host 发出的请求
  都经过它：你自己的 key、ChatGPT 登录的调用、「列出模型」、工具读取的网页、连接的服务、更新检查，
  还有手的运行时（`nanomuse mcp` 继承同一组变量）。nanoMuse Cloud（中继、hub 的 WebSocket、同步）和本机回环永远不经过。
  外壳把它存在 `desktop.json` 里（权限 0600，因为地址里可能带密码），和「登录时启动」放在一起，启动 dsh Host 时写进它的环境
  （`HTTP_PROXY`、`HTTPS_PROXY`、SOCKS 时还有 `ALL_PROXY`，`NO_PROXY` 带着
  `localhost,127.0.0.1,::1`、`cloud.nanomuse.cn` 和插件所连的中继，以及让 Node 的 fetch 读这些
  变量的 `NODE_USE_ENV_PROXY=1`），所以重启后生效；这一行下面的「立即重启」会在窗口不关的
  情况下重启 Host，有回复、手、别的设备发来的任务或审批在进行时会先问一声，和退出一样（下面
  第二条）。自建的中继要进 `NO_PROXY`，启动外壳时带上 `NANOMUSE_CLOUD_URL` 即可，插件读的也是
  这个变量。手机上同样的设置在服务商表单里，网页版在自有 key 表单里，运行时是
  `[llm] proxy`（[own-key.md](own-key.md#when-the-provider-cannot-be-reached)）；
- **长期授权**（设置 → 权限）：这台电脑记住的所有授权列成一张表，按手机权限页的三档分组：
  「不再询问」（远程控制开关：账号下的每台设备都可以在这里执行操作）、「卡片上记住的」
  （在远程控制卡片上选了「始终」的设备；在权限卡片上选了「在 <应用> 里始终允许」「本对话中始终允许」
  或「此定时任务中始终允许」的手）、「先执行再告知」（桌面版目前没有东西落在这一档）。每一行写明
  允许了什么、给谁或在哪里、什么时候，带一个「撤回」；只在一个对话里算数的授权写着「仅对话「…」」，
  并列出这个对话里的定时任务，它们也在这条授权之内；只在一个定时任务里算数的写着「仅定时任务「…」」
  和所在的对话，任务删掉后也会注明。空状态说明是卡片上的「始终」把一行放到这里来的。电脑操作页和
  个人资料抽屉各自保留较短的列表，每一行同样写明范围；这一张是完整的。Host 用 `GET /nanomuse/cloud/grants` 回答这张表，
  `POST /grants/revoke {id}` 撤回其中任何一行。
- **真正的退出会保护进行中的工作。** 退出（菜单里的「退出」、Ctrl+Q、托盘的「退出」，或者在没有
  托盘时关闭最后一个窗口）先问 Host 还有什么在进行：正在生成的回复、屏幕上的电脑操作、其他设备
  交来的任务、等你确认的操作。弹窗会列出这些工作，「继续运行」是默认；只有在这里明确确认，工作才会
  被结束，退出也会等工作结束之后才停止 Host。退出交接期间到来的任务会得到和平时一样的 busy 拒绝，
  请它的设备稍后再发一次。开着菜单栏图标时关闭窗口只是留在托盘，从来不算退出。相关路由是插件的
  `GET /nanomuse/cloud/work`（聚合）、`POST /work/gate {open}`（交接）和 `POST /work/stop`（确认后的结束）。
  代理那一行下面的「立即重启」，以及 macOS 授予屏幕录制权限后要求的重启，都会先问同样的问题；
  只重启助手程序不碰 Host 的工作。
- **每次模型调用都会告诉账号记录它处在哪里**（中继 0.31）。harness 的模型适配器对每个请求都带同一组
  服务商请求头，而一次调用的来源每次都不一样，所以 `nanoMuse Cloud` 这一行服务商指向插件自己的
  一个本机回环入口（`http://127.0.0.1:<端口>/v1`；端口每次启动各一个，启动时会把这一行重新指过去）。
  请求只有带着本账号自己的 key 才会被转发（否则在这里就是 401，和到中继一样），转发时加上设备、
  平台（`X-NanoMuse-Platform: desktop`）以及 `llm/stream` 钩子为这次调用登记的信息：这一轮是谁
  发起的（`X-NanoMuse-Run`：`person`、`schedule`、`goal`，别的设备通过 hub 交来的任务是 `hub`）、
  在对话里的轮次和步骤序号，以及正在操作这台电脑屏幕时所在的手的运行和步骤。中继的回复原样
  流式传回，中继给这一轮的 id 留给这个会话。用你自己的 key 跑的一轮事后也带同样的字段上传
  （[cloud.md](cloud.md#provenance)）。围绕一轮对话，插件给记录发的只有代码，没有文字
  （`POST /v1/events`）：每次工具调用是怎么定的、谁定的（策略、长期授权、卡片或舞台上的人、
  另一台设备，或者没人及时答复）以及工具随后有没有跑成；一次审批等了多久；手的每一步（动作种类、
  结果、耗时）和这次运行怎么收尾；被人手动停掉或出错结束的一轮；还有浏览器那一半通过
  `POST /nanomuse/cloud/feedback` 发来的赞/踩或停止原因（`{session, vote: up | down | "", reason?,
  turn_no?}` 或 `{session, stop_reason, turn_no?}`，只收中继规定的那几个词，其他一律 400）。
  登录状态下这些记录隔几秒成批上传；退出登录会清空队列（[cloud.md](cloud.md#client-events)）。
- **每条回复旁有赞和踩，按下停止后问一句为什么。** 登录状态下，每条回复末尾的引用按钮旁边多了
  一个赞和一个踩。点踩会展开五个一词的原因（「答错了」「没帮上忙」「不该这么做」「太慢了」
  「其他原因」）和「跳过」；再点一次同一个按钮就收回；给前面某条回复点的标记会记到那条回复所在的
  轮次上，轮次按它上方你的消息数出来。刚按下「停止」时，输入框上方出现一行「为什么停下来？」，
  可选「方向不对」「太慢了」「改主意了」「已经做完了」「其他原因」和「跳过」；选了、跳过了、
  下一轮开始了，或者过了一分半没理它，这一行就消失（`live.stopped` 列着还在问的会话）。
  每个回答到账号记录里只是一个词（`turn.feedback`、`turn.stopped`），不带别的；未登录时什么都不显示。

## 额度用完时，以及中继的其他回答 {#when-the-allowance-is-used-up-and-the-relay-s-other-answers}

账号的免费额度管的是模型，不是登录：中继用 `allowance_exhausted` 回答某一轮时，桌面版在
聊天里、在那一轮没跑成的消息下面，显示手机和网页版显示的同一张卡片：

- 一句话（*免费额度已用完。*），以及不管选哪条路，你的登录和设备都照常工作；
- **自己的模型 key**：按你所在地区列出的服务商行（和「设置 → nanoMuse Cloud」里的同一组行，
  「添加 key」和「去拿 key」就在行内），下面折叠着「更多服务商，以及每把 key 各管什么」，
  这份清单是中继随拒绝和 `/v1/me` 一起发来的（`spend.guidance`，[cloud.md](cloud.md#allowance)），
  不是写死在应用里的，还有「图文教程」（[own-key.md](own-key.md)）；
- **你已经在付费的套餐**：ChatGPT 登录就在这里，附上中继对它的提醒；
- **邀请朋友**：朋友发出第一次请求后你们各得的奖励，和「复制链接」；
- 请你在 GitHub 上点一颗 star，只出现一次，且只在提示策略允许时：卡片的标题和按钮是应用
  自己的；那句话也是应用自己的，除非中继的策略带了一句（`star.text`、`star.text_zh`，最多
  200 个字符；中文界面取 `text_zh`，没有就取 `text`；[cloud.md](cloud.md)）；
- 「打开“设置 → nanoMuse Cloud”」和「再试一次」（设好一条路之后，同样的话会再发一遍）。

中继的其他拒绝，每一种都是一句平实的话，用应用的语言说，从不直接显示状态码或 JSON 正文：

| 中继说的 | 卡片说的 | 按钮 |
| --- | --- | --- |
| `413`（请求对中继或模型的窗口来说太大） | *这条消息超过了模型的窗口。缩短一些、去掉几个附件，或者开一个新聊天。* | 「新聊天」 |
| `400 content_rejected`（服务商的内容审核没有放行这些内容；用自己的 key 时服务商自己的 `DataInspectionFailed` 读法相同） | *模型服务商的内容审核没有放行这次请求。换个说法试试；如果反复出现，就开一个新聊天，被拦下的可能是对话里更早的内容。* | 「新聊天」「再试一次」 |
| `401`（key 在别处被收回了：在所有设备上退出登录、账号被删除） | *这次登录已失效。请在「设置 → nanoMuse Cloud」重新登录。* 桌面版同时自己退出登录，和 `/v1/me` 返回 401 时一样。 | 「登录」 |
| `403`（账号被停用，或者中继不接受它） | *这个账号目前不能使用 nanoMuse Cloud。*，下面附中继的原话 | 「打开“设置 → nanoMuse Cloud”」 |
| `429` 不带额度代码（同时的请求太多、服务商正忙） | *同时的请求太多。稍等片刻再试。*，中继给了 `retry_after` 时带上它 | 「再试一次」 |
| `429 daily_cap`（设了每日份额的中继） | *今天的额度用完了，明天恢复。*，下面附中继自己的原话 | 「再试一次」 |
| `404 model_not_offered` | *nanoMuse Cloud 不再提供这个模型。* | 「打开“设置 → nanoMuse Cloud”」 |
| `5xx`，或者完全没有回应（连接被拒绝、超时） | *nanoMuse Cloud 没有回应。* / *连不上 nanoMuse Cloud。检查网络后再试。* | 「再试一次」 |
| `429 allowance_exhausted` 且 `paused: true`（中继 0.22：运营者暂停了免费额度，[cloud.md](cloud.md#controls)） | 同一张额度卡片，开头换成 *这个中继暂时停发了免费额度，不是用完了。你的登录、设备和剩余额度都保持原样。* | 继续用的几条路，「再试一次」 |
| `503 service_paused` | *nanoMuse Cloud 被运营者暂时停用了，你的登录和数据都保留着。稍后再试。* | 「再试一次」 |
| `503 sync_paused` | *这个中继暂时停止了对话同步，已存的内容保留着，各设备各自继续使用。* | 「再试一次」 |
| `503 hub_paused` | *这个中继暂时停止了设备互联，各设备各自继续使用。* | 「再试一次」 |
| `403 signup_closed`（只在登录时） | 中继自己的那句话：*这个中继暂时关闭了新注册；已有账号照常使用。* | 「打开“设置 → nanoMuse Cloud”」 |

拒绝不会被重试：0.1.40 之前，harness 把中继的 `429` 当成限流，再试五次（大约二十秒）之后才把
原始回复摆出来；现在卡片立刻就在。用自己的 key 时被服务商拒绝的一轮也是同样的形状：按失败
类型给一句话，返回的内容折叠在「返回的原文」下面。相关代码是 `src/refusals.ts`（Host 在
`llm/stream` 瀑布流上读中继的回复，把失败改写成 `nanomuse/<kind>`）和
`src/client/RefusalCard.tsx` 里聊天的 `turn-error` 位置。

聊天之外那些和中继打交道的页面（登录、模型列表、账号页、形象工作室、连接器、设备）对常见
情况遵循同一条规则：连不上中继说 *连不上 nanoMuse Cloud。检查网络后再试。*，超时说
*nanoMuse Cloud 没有及时响应。稍后再试。*，`429` 说 *刚才的请求太多了。稍等一下再试。*，
`401` 说 *尚未登录 nanoMuse Cloud，或登录已失效。请重新登录。*，`5xx` 说 *nanoMuse Cloud
出了点问题（503）。过一分钟再试。* 并带上状态码；桌面端自己在本机回环上的 Host 完全没有
响应时，说 *这台电脑上的 nanoMuse 没有响应。重启应用后再试。*。其他情况仍然是 *没成功：*
加上原样的消息（`src/client/api.ts` 里的 `failureText`；Host 这边把 `fetch failed` 或超时
改写成 `unreachable` 503 和 `timeout` 504 两个代码）。

**80% 的提前提醒。** 用账号的模型跑完一轮后，Host 会重新读一次账号（最多一分钟一次）；
中继说额度池用到 80% 时，输入框上方出现一行可以关掉的提示（还剩多少、邀请奖励、
「看看办法」），每个额度池规模只出现一次，和手机在聊天里、网页版在输入框上方显示的一样。

**输入框上方的等待（1.0.8）。** 某个对话用账号的模型发出的一轮还没等到第一个字时，Host 把这次调用列在
`live.waiting` 里（它的会话和开始时间；`watchRelayStream` 在第一个 chunk、结束或流断掉时把它移除），
那个对话输入区里的 `WaitLine` 前十秒什么都不说，然后是「模型接口比较忙，已等待 15 秒」和「取消」，
也就是标题栏的停止。手机在输入中的点点下面画同一行字，还会根据中继的状态 chunk 加上「前面还有 3 个」
（中继 0.31，[cloud.md](cloud.md#protocol)）；Harness 的解析器不会把那些递过来，所以桌面只说等了多久。

### 检查打包后的运行时 {#checking-a-packaged-runtime}

构建自带运行时后，运行 `python scripts/desktop-app/build-runtime.py --check-only`，会从空工作目录
启动它，检查健康接口、网页和工作区位置。检查会选择空闲回环端口，将启动日志写入临时文件。
运行时等待 60 秒仍未就绪时，会报告日志末尾内容，停止子进程，然后清理检查用的数据目录。

## 配置和数据 {#config-and-data}

同一秒内多次反馈问题并截图时，后来的截图会使用带序号的文件名，不会覆盖前一张。

对话上传已被中继接收但响应丢失时，重试会沿用相同的消息 ID，避免其他设备收到重复消息。会话映射会在上传前保存，重启后仍可沿用；本地保存失败时，这次上传会留待后续重试。

Windows 上停止编程任务时，也会请求系统结束它的子进程，包括分离运行的辅助进程。

一台设备完成一轮任务时，只会清除自己的工作状态。较早的停止通知不会清除同一设备后来发出的工作状态。

账号状态按顺序保存，先写入私有临时文件，再替换 `cloud.json`。替换前写入如果中断，原来的完整状态仍然保留。

桌面端的同步缓存最多保留最近使用的 64 个对话日志。需要更早的日志时会重新从磁盘读取，保存的对话仍可正常使用。

`MEMORY.md` 中每条记忆旁的日期使用这台电脑的本地日期。

桌面开发环境的冒烟测试在 Windows 等平台通过文件 URL 导入 Electron，仓库路径可以包含空格、Unicode 字符、`#` 或 `%`。

`~/.nanomuse/desktop`（`NANOMUSE_DESKTOP_HOME` 可以把它挪到别处）是应用的 dsh 主目录：
`profiles/nanomuse` 下的 profile（插件列表，以及本人的 `cordis.patch.yml`，设置页和登录流程把
`nanoMuse Cloud` 服务商写在这里），存着账号 key 的 dsh 凭据存储，会话，记录外壳和 Host 两边
日志行的 `desktop.log`，还有 `port`，Host 上一次用的回环端口，下次启动先试它（然后试 38421，
再任选一个空闲端口），这样窗口的来源（origin）以及浏览器侧存在那个来源下的一切，每次启动都
保持不变。nanoMuse Harness 0.1.28–0.1.29 留在 `~/.nanomuse/harness` 下的主目录会被接管一次。
`NANOMUSE_CLOUD_URL` 把账号指向另一个中继；`NANOMUSE_PY` 把预设指向另一个负责手的运行时。
CLI 自己的 `~/.dsh` 不会被碰。主目录下的 `nanomuse/hands.json`（权限 0600）是「设置 → 模型」
解析出来的手的模型（服务商、模型、base URL 和 key），和插件交给运行时的 `NANOMUSE_GUI_*` 环境变量
是同一组值。0.1.41 起，手的 MCP 客户端由插件自己挂载（`dsh-nanomuse/hands-tools`），不再是预设里
固定的一行：在「操作屏幕」下换了模型，插件会释放客户端并用新环境变量重新启动 `nanomuse mcp`，
不用重启就生效（进行中的一次手的调用先做完）。什么都没配时这个文件会被删除；`nanomuse/rooms.json`
保存房间（动态，目标连同它们的步骤和进度，哪些点子试过了，资源库索引，记忆）。
`desktop.json` 先写到旁边的临时文件再换进去，上一份留作 `desktop.json.bak`：保存失败（磁盘满、
崩溃）时留下的还是上一份好的设置，文件损坏时下次启动从备份换回来。两个文件都只有本人可读，因为
代理地址里可能带密码。「下载你的智能体数据」一次只把一个文件写进 zip，链接和超过 64 MB 的文件
不打包，打包进去的 `desktop.json` 会去掉代理地址里的密码。

## 智能体的桌面使用指南 {#the-agents-desktop-guide}

预设还包含 `skill-creator`，用于编写和检查可复用技能。它与 Android 和 Python 运行时共用不绑定模型服务商的说明。两份内置指南都按需加载，不会改变审批权限。

nanoMuse 预设内置了 `nanomuse-desktop` 技能。DeepSeek Harness 的技能目录只展示它的简介，
需要时才由 `skill` 工具加载完整指南。你问怎样连接第二大脑文件夹、怎样设置桌面功能时，
智能体可以读本机指南，不必搜索 App 源码。指南包括设置、工作区、权限、连接器和 MCP、技能、
记忆及各个房间，宿主还会提供当前工作区和 harness 主目录的实际路径。

如果希望每段聊天都能找到一个文件夹，指南会说明怎样把路径记在工作区的 `AGENTS.md` 中，
或用 `$DSH_HOME/AGENTS.md` 覆盖不同工作区。这不会复制文件夹，也不会授予访问权限：
工作区之外的写入仍需审批，通过 Windows 目录联接或符号链接访问也一样。密钥录入，以及
没有智能体工具的设置项，仍在已有的设置页面中操作。

## 模型 {#models}

「设置 → 模型」紧跟在「通用」后面，模型替你做的每件事占一行：「对话」「操作屏幕」「生成图片」
「生成视频」。登录时只在中继实际菜单覆盖的行里把 nanoMuse Cloud 排在最前，并标出这条通道的
推荐模型，之后是你在
「设置 → nanoMuse Cloud」下添加的每个服务商各一组，每组只有能做这件事的模型（操作屏幕需要能看图的
模型；手只会说 OpenAI 的接口格式，所以 Anthropic 或 Google 原生接口的 key 在行下点名、不进列表）。
什么都做不了的一行用一句话说明谁能做，并给出「添加服务商」。

选择器是一个写着「服务商 · 模型」的按钮，点开是一个面板。列表很长的服务商（OpenRouter、硅基流动）
起初只显示八个模型，目录里这一行的默认模型和你当前选的排在最前，组尾是「还有 {n} 个」；所有组加起来
超过八个模型时，面板顶部出现「搜索模型」输入框，边打字边按模型 id 或名称过滤每一组（都不匹配时显示
「没有匹配的模型」）。按 Esc 或点面板外面关闭；「设置 → 图像与视频」用的是同一个选择器。折叠和搜索
的逻辑在 `harness/dsh-nanomuse/src/client/model-list.ts`，由 `tests/model-list.test.mjs` 检查。如果你在
`llm-pi-ai` 设置的「模型目录」里删减了某个服务商的对话模型列表（或在 `POST /nanomuse/cloud/providers/save`
中传入 `catalogOnly: true`），桌面版会在 `cloud.json`、各个模型选择器、重启后以及后续更新 key 时保留这份
精简后的模型列表，不再把网关 `/models` 返回的完整列表重新合并回来。

没选的时候一行用什么：新对话用的那个服务商，前提是它是你自己的、而且对这件事有模型（目录里的默认
模型）；否则只在中继实际菜单提供这项能力时用 nanoMuse Cloud；再否则用你第一个能做这件事的服务商。
项目托管 Cloud 只有对话和操作屏幕，不提供媒体生成。按这个顺序走的三行，选择器
第一项是「自动」，行下写明现在落到哪个（比如操作屏幕的「当前为 nanoMuse Cloud · Qwen/Qwen3.6-27B-FP8」）；选它就撤掉你
选过的那个，这一行重新按顺序走。选对话模型，新对话用它，主要聊天也跟着换过去（「对主要聊天和新对话
生效；旁聊保留自己的模型。」）；旁聊保留各自的模型，同一个选择再选一次不会重写。手机上是同一条规则。
新对话用的那个服务商没了（移除了它的 key，或退出了登录）时，对话这一格跟着挪：登录时挪到账号，否则挪到你
另一把 key，再否则回到自带的默认模型；不会留在没人接的路由上（0.1.41 里那会让每个新对话都报
「no adapter registered for provider "custom"」）。
用自己的 key 画图直接走那个服务商（百炼的原生图像接口、OpenRouter 的图像接口，其余走 OpenAI 的
格式），不计入账号；形象工作室在费用那一行的位置写明。短视频只有百炼能做，用你自己的百炼 key
（或者运营者明确开启旧媒体代理的自建中继），不会走项目托管账号。

存好一把 key 之后，一张小卡片问「用它来做什么」，这把 key 能做的每件事一个开关，默认全开；「就这样」
把那几行换成这个服务商，「暂不」什么都不改。自己的模型在某一轮失败时，卡片在已登录的情况下给出
「这次改用 nanoMuse Cloud」：这一条消息再走一次账号，这一轮结束后对话回到原来的模型，模型页保持
原样。「就这样」勾着对话时，主要聊天也一起换过去。不会自动回退。工作室画图或生成短视频失败时，
需要修好或更换你自己的媒体服务商，没有托管 Cloud 重试。

登录时，这一页最上面有一个开关「使用 nanoMuse Cloud 模型」。关掉之后，账号的模型从每个选择器和自动顺序里
退出，Harness 的附带调用（对话标题、压缩上下文）改在对话那一行自己的模型上运行，还停在 nanoMuse Cloud 模型上的
对话不会发出：一张卡片说明原因，给出换一个模型、新开对话，或「这次改用 nanoMuse Cloud」，后者是开关关着时唯一
会消耗额度的东西。账号保持登录；同步、你的设备和「设置 → nanoMuse Cloud」照常工作。
关掉时如果对话那一行还是账号的模型：你有自己的对话模型，就把这一行挪过去；一个都没有，就拒绝关闭，开关下面
写一句原因，开关保持打开，因为没有别的模型能回答（四个客户端同一条规则）。反过来也一样：开关关着时移除最后
一把自己的 key，账号的模型会重新打开，对话那一行回到账号的对话模型，key 那一行写一句说明；1.0.1 之前，对话
会落到 dsh 自带的默认模型上，而没有任何 key 在为它服务。

profile 里的 `node_modules/dsh-nanomuse` 是一个链接（Windows 上是 junction），指向已安装应用里的
插件；每次启动时，只要安装目录和链接目标不一致，就重写它：一次挪动了应用位置的更新，比如从
`Programs\nanoMuse\nanomuse-desktop` 挪到 `Programs\nanomuse-desktop`，会留下一个指向空处的链接，
0.1.39 跨不过它，起不来（`desktop.log` 里是 `EEXIST: file already exists, symlink …`）。从 0.1.40
起，失效的链接按链接删掉再重建；万一还是失败，提示信息会写明要手动删除的路径。

Windows 上的只读和工作区可写 PowerShell 命令会经过 DSH 的受限令牌 ACL 沙箱。Electron 托管的
进程本身没有控制台，因此 nanoMuse 只在这条 ACL runner 前加一个短命的 Node 模式跳板，在令牌
受限之前为它建立无窗口控制台（不支持时退到隐藏控制台）。PowerShell 子进程继承这个控制台，
不会再在 DLL 初始化阶段以 `0xC0000142` 退出；临时沙箱目录被清理并重建后也是如此。这个跳板
不会放宽 ACL 策略，也不会介入完全访问模式的命令。

第一次启动可能很慢，Windows 上尤其如此。Host 要等 profile 里的每个插件都加载完才打印地址，而刚装好的
应用在 `resources/dsh/node_modules` 下有两万来个文件，系统是第一次读它们；Windows Defender 的实时
防护会在第一次读取时逐个检查，磁盘慢或者装在移动硬盘上就更久，所以第一次启动可能要好几分钟。0.1.41
及之前，外壳等 120 秒就放弃，提示「the host did not announce its address within 120 s」，而 Host
其实还在加载（有一份报告里，它六秒之后就打印出了地址）。现在只要 Host 进程还在，外壳就一直等：两分钟
后加载页改为显示「还在启动」，附一句原因和 Host 最近几行输出；十分钟后弹出对话框问是继续等还是退出，
只有退出才会停掉还在启动的 Host。一次启动超过半分钟时，`desktop.log` 里会有一行 `host: ready after
N min`。第二次启动会快很多，因为文件已经检查过一遍；如果每次都慢，把安装目录加进实时防护的排除列表
会有帮助。

## macOS 权限 {#macos-permissions}

手需要 macOS 给两样东西：截图要「录屏」，鼠标和键盘要「辅助功能」。从 0.1.38 起，这两项权限都
归一个独立的小应用所有，即 **nanoMuse Computer Use**（`nanoMuse.app/Contents/Helpers/nanoMuse Computer
Use.app`，bundle id 为 `io.github.nanomuse.desktop.computer-use`）：你在「系统设置 → 隐私与安全性 →
录屏」和「→ 辅助功能」里要打开的就是这一行。nanoMuse 桌面版本身两项都不持有。

为什么要多一个应用。macOS 把一次权限请求归到「责任进程」（responsible process）头上，即
LaunchServices 启动的那个进程，连同它派生出来的一切。在这几个面板看来，应用的子进程就是应用
本身，所以自带的运行时从来不会出现在面板里；而通过 `open` 启动的一个应用包对自己负责，有自己
的一行，名字说明它是干什么的（Qt 的文章 *The Curious Case of the Responsible Process* 把这套归属
讲了一遍；Codex 的 *Codex Computer Use.app* 是同样的安排）。这个助手程序是几百行 Swift
（`harness/desktop/mac/computer-use/`），跑在一个带每次启动随机令牌的回环 HTTP 服务器上：它报告
自己的两项授权，用系统自己的对话框去申请（`CGRequestScreenCaptureAccess`、
`AXIsProcessTrustedWithOptions`），负责截图，macOS 14 及以后用 **ScreenCaptureKit**
（`SCShareableContent` → 主显示器 → `SCContentFilter` → `SCScreenshotManager.captureImage`，按显示器
的像素尺寸、带光标），12 和 13 用 `CGDisplayCreateImage`（而不是 Chromium 的 `desktopCapturer`，
它的黑帧和缺帧正是 0.1.36 的麻烦所在），并用 `CGEvent` 移动鼠标和打字（任何文字都以字符本身
输入，所以中文不用经过剪贴板就能直接打出来）。为什么用 ScreenCaptureKit：在 macOS 26 和 27 上，
即便已经授予录屏权限，`CGDisplayCreateImage` 也什么都不返回，0.1.39 把这记成 `helper screenshot
failed (no screenshot: noImage)`，然后用一帧 `desktopCapturer` 的画面盖过去，而那一帧要么全黑要么
是旧的。应用启动时就启动这个助手程序（读取授权，并申请缺的那几项），退出时把它关掉；应用
不在了，助手程序也会自己离开。它没有窗口，没有 Dock 图标；活动监视器里列为 *nanoMuse Computer
Use*。

在一台什么都还没授权的 Mac 上，你要做的事，只做一次（在 macOS 27.0.1、Apple 芯片上验证过）：

1. 从「应用程序」文件夹打开 nanoMuse（先把它从磁盘映像拖进去；见下面的*隔离标记*）。
   「设置 → 电脑操作 → 权限」，或者第一次要用到手的时候：我们自己的一个简短对话框会说明在申请
   什么、为什么。
2. **录屏。** 系统对话框出现（*“nanoMuse Computer Use”想录制这台电脑的屏幕和音频*），带
   「打开系统设置」。那个面板（macOS 15 及以后叫*屏幕与系统录音*）里列着 **nanoMuse Computer
   Use**；打开它。macOS 可能会提议「退出并重新打开」助手程序：怎么答都行，应用会自己再把助手
   程序拉起来，下一张截图就是真实的屏幕。nanoMuse 本身什么都不重启；对话继续。
3. **辅助功能。** 又是系统对话框，然后在辅助功能面板里打开 **nanoMuse Computer Use** 旁边的开关；
   macOS 会要你的密码或 Touch ID 才能拨动它。立即生效。

权限页实时显示这两行，点明要打开的是这个助手程序，它的「试一下」按钮会截一张测试图、动一下
鼠标，走的是真实的链路（应用 → 运行时 → 助手程序），所以那里能通过的，聊天里也能通过。在面板里
关掉一项授权，手在下一步就会说出来：*macOS：到「系统设置 → 隐私与安全性 → 录屏」里打开 nanoMuse
Computer Use。助手程序会自己重启；应用不需要。*（操作器返回 `403`；运行时从不退回到 `mss` 或
`screencapture`）。

**录屏检查是怎么做的。** 助手程序的 `/status` 回答 `granted`、`denied` 或 `unknown`。先问
`CGPreflightScreenCaptureAccess`（这是 TCC 自己的答案，不会弹窗），答「否」就是 `denied`。在
macOS 14 及以后，答「是」还要再用 ScreenCaptureKit（`SCShareableContent`）确认一遍：它抛出
`userDeclined` 或 `noDisplayList` 时，说明授权其实不在，状态是 `denied` 并附原因；别的错误是
`unknown` 并附原因，下一张截图照样尝试，并报告 ScreenCaptureKit 说了什么。所以 `granted` 的意思是
真能截回一张图，而不只是某个开关开着。申请仍然是系统自己的对话框
（`CGRequestScreenCaptureAccess`）加上指向那个面板的深层链接。

**截图失败时，会告诉你。** 只要应用里带着助手程序的 bundle，操作器就绝不会用一帧
`desktopCapturer` 的画面顶替助手程序，因为一张全黑或过时的图会被当成屏幕送到模型面前。聊天和
`computer_screen` 改为这样说：

- 助手程序缺录屏权限：*macOS：到「系统设置 → 隐私与安全性 → 录屏」里打开 nanoMuse Computer Use。
  助手程序会自己重启；应用不需要。*（就是那个 `403`；「设置 → 电脑操作」说的也一样）。
- 授权在、ScreenCaptureKit 却失败了：*没有截图：nanoMuse Computer Use 没能截到图：
  ScreenCaptureKit userDeclined (-3801): …*，SCK 错误的名字和代码，后面跟着系统给的文字
  （`noDisplayList`、`failedToStart`、`internalError`……；读者可以按代码去查）。
- 助手程序没有启动（隔离标记还在、没有端口、App Translocation）：*没有截图：nanoMuse Computer Use
  没有启动（…）*，附上日志里 `helper:` 行给出的原因；「设置 → 电脑操作」把同一个原因显示为
  *不可用*。

0.1.38 之前的 `desktopCapturer` 路径只为没有助手程序 bundle 的构建保留（见下）。

**在 Mac 上核对。** `~/.nanomuse/desktop/desktop.log` 里有整条链路：

- `helper: nanoMuse Computer Use <version> (pid …) at http://127.0.0.1:… — screen granted, accessibility true, capture ScreenCaptureKit`：
  助手程序起来了，并且在 macOS 14+ 上说明用哪条路径截图（12 和 13 上是 `CoreGraphics`）。
- `permissions: accessibility=granted screen=granted (nanoMuse Computer Use <version>, capture ScreenCaptureKit)`：
  应用启动时读到的授权；面板里开关开着、这里却是 `screen=denied` 时，版本号后面会带上
  ScreenCaptureKit 给的原因。
- `operator: helper screenshot failed (…) — not falling back to desktopCapturer`：截图失败了，
  这一行说明原因，聊天里收到的是同样的话。不再有 `using the Electron path` 这种行了。

然后「设置 → 电脑操作 → 试一下」：测试截图要么是助手程序截的图，要么是上面那个错误。

**隔离标记。** 你下载的磁盘映像带着 macOS 的隔离标记（quarantine），从里面拷出来的每个文件也都
带着，助手程序也不例外。打开 nanoMuse 会把 nanoMuse 自己的标记处理掉（Gatekeeper 的对话框，
「仍要打开」），但助手程序的不会，因为 LaunchServices 把它当作一个独立的应用来启动。一个带隔离
标记、未经批准的助手程序会从一份「转移」（translocated）副本启动
（`/private/var/folders/…/AppTranslocation/<random>/d/` 下的一个只读挂载，名字每次启动都变），
Gatekeeper 自己的「无法验证」对话框也可能为它弹出来，而助手程序始终不回应。0.1.38 就是这样：
助手程序在跑（活动监视器里看得到），辅助功能能授权，但录屏面板里始终不出现 *nanoMuse Computer
Use* 这一行，因为 tccd 记下的是一条已经不存在的路径。从 0.1.39 起，应用在第一次启动助手程序之前
先去掉它的标记（对 `Contents/Helpers/nanoMuse Computer Use.app` 执行 `xattr -dr
com.apple.quarantine`；日志里写 `helper: removed the quarantine flag…`），之后助手程序就在原地
启动，它的那几行也留得住。这需要 bundle 可写；你放在「应用程序」里的那份就是。如果直接从磁盘
映像或「下载」文件夹里运行，nanoMuse 本身就被转移了，助手程序修不了，也不会被启动；日志会说
*把它移到「应用程序」文件夹再打开一次*，这期间手走应用自己的路径（见下）。

还有几点：

- 录屏权限只对新启动的进程生效；这里的进程就是助手程序。应用运行期间开关被拨动时，应用会
  自己重启助手程序（日志写 `restarting the helper for the new grant`）；权限页上的「重启」按钮
  重启的也是助手程序，从不重启应用，连点两下算一次重启。如果助手程序还在启动，重启会等它启动完再替换它。
  按钮会显示「正在重启…」，直到新进程回应；失败时显示原因，成功后才清除旧的黑屏提示。
  再拍一张测试截图即可检查录屏权限是否生效。
- 截的是主显示器，最多 2 Mpx（3456×2234 的 Retina 面板会缩到 1758×1137），坐标以点（point）为
  单位。只截取、只操作主显示器。跨动作按住一个键（`press` / `release`，UI-TARS 的叫法）从 0.1.39
  起可用。
- *窗口模式*（手只在某一个应用的窗口里干活）列窗口和截取窗口画面也走助手程序
  （`GET /windows`、`POST /window`；macOS 14+ 上用 ScreenCaptureKit 的
  `SCContentFilter(desktopIndependentWindow:)`），所以助手程序的录屏那一行就覆盖了它。事件仍然
  由运行时发出（`CGEventPostToPid`），macOS 把它们归到 **nanoMuse** 本身名下：所以窗口模式在助手
  程序的两行之外，还需要辅助功能面板里的 *nanoMuse* 那一行，缺了就退回整个屏幕并给出提示。
  没有助手程序 bundle 时，运行时自己截取窗口（`CGWindowListCreateImage`；运行时日志写
  `window mode: the runtime captures windows itself …`），同样需要 *nanoMuse* 的录屏那一行。
  「设置 → 电脑操作」会说明窗口模式是否可用。
- macOS 15 及以后会时不时再问一次，一个不经系统选择器就截屏的应用能不能继续；给 nanoMuse
  Computer Use 答「允许」。
- 想把授权流程从头来过：`tccutil reset ScreenCapture
  io.github.nanomuse.desktop.computer-use; tccutil reset Accessibility
  io.github.nanomuse.desktop.computer-use`，然后再走一遍「设置 → 电脑操作 → 权限」。早先版本留在
  *nanoMuse Desktop* / *nanoMuse* 名下的授权只有窗口模式会用到（见上），其他情况下可以关掉。

没有助手程序 bundle 时（不带它的构建、`build.sh` 之前的开发运行），应用的行为和 0.1.38 之前
一样：授权是 nanoMuse 桌面版自己的（`io.github.nanomuse.desktop`），通过
`@computer-use/node-mac-permissions` 和 `@computer-use/mac-screen-capture-permissions` 读取，画面
来自 `desktopCapturer`，输入来自 `@computer-use/nut-js`，录屏授权之后需要重启应用（「立即重启」）。
bundle 在、却没启动起来（日志的 `helper:` 行会说原因）不属于这种情况：手会带着原因拒绝，直到它
启动为止，而不是转去用那套没人打开过的应用自身授权。权限页会写明当前用的是哪一套。

得老实说一句：macOS 把授权绑在应用的代码签名上。有 Developer ID 签名时，助手程序的「指定要求」
（designated requirement，标识符加团队）在每次构建之间都一样，授权能跨更新保留。项目的证书还在
等 Account Holder 那边，所以今天的构建都是 ad-hoc 签名：ad-hoc 签名绑的是二进制的哈希，助手程序
每出一个新构建，两项授权都得重新来过（应用本身以前也是这样）。证书到手之前，每次更新后都得再把
助手程序打开一次，开发时则是每次 `build.sh` 之后：你重新构建的助手程序对 tccd 来说是一个新
应用，所以只要 Swift 代码变了，`npm start` 每次都会再要这两项授权（TypeScript 随便改）。

## macOS 签名 {#macos-signing}

`scripts/desktop-app/package-mac.sh x64` 打包 `dist/mac`，`arm64` 打包 `dist/mac-arm64`，
即使两种构建同时存在也只选择对应目录。应用包缺失或无法唯一确定、内部 Mach-O 签名失败，
或者应用、助手程序、磁盘镜像校验失败时，打包会报错退出。

运行时打包步骤保留 PyInstaller 生成的 framework 和库的相对符号链接，
让应用在复制和签名时保持 framework 的目录结构。

没有 Apple 开发者证书时，bundle 是 ad-hoc 签名，macOS 会问一次。配好仓库密钥
`MAC_CERT_P12_BASE64`、`MAC_CERT_PASSWORD`、`APP_STORE_CONNECT_KEY_ID`、
`APP_STORE_CONNECT_ISSUER_ID`、`APP_STORE_CONNECT_KEY_P8` 以及（可选的）`APPLE_TEAM_ID` 之后，
`scripts/desktop-app/package-mac.sh` 会用 Developer ID Application 证书在 hardened runtime 下签名
（`harness/desktop/resources/entitlements.mac.plist`），用 notarytool 公证，并装订（staple）票据。
证书从「钥匙串访问」导出为 `.p12` 再做 base64 编码；App Store Connect 密钥就是 `.p8` 文件的文本。

助手程序 *nanoMuse Computer Use.app* 在 macOS runner 上由
`harness/desktop/mac/computer-use/build.sh` 构建（纯 `swiftc`，arm64 和 x86_64 用 `lipo` 合并，
部署目标 macOS 12.3，即第一个有 ScreenCaptureKit 的版本，二进制链接了它；SCK 截图在 14+ 上运行，
之前的版本用 CoreGraphics），然后 electron-builder 把它拷进 `Contents/Helpers`
（`electron-builder.yml` 里的 `mac.extraFiles`）。`package-mac.sh` 先给它签名，作为一个独立的
bundle（同一身份、hardened runtime、它自己的标识符 `io.github.nanomuse.desktop.computer-use`、
不带应用的任何 entitlement），然后再签外层的应用。本地 macOS 构建要在 `npm run dist:dir` 之前跑
`build.sh`；不跑的话 electron-builder 只会警告源文件缺失，应用就不带助手程序出厂，走 0.1.38 之前
的路径。助手程序里有 Swift 警告时 `build.sh` 直接失败，和 iOS 应用的规矩一样：助手程序是
nanoMuse 自己的代码。

## Linux 注意事项 {#linux-notes}

- **优先选 `.deb`**（Debian、Ubuntu 及其衍生版）：它安装 `/opt/nanoMuse/nanomuse-desktop`、
  图标集和桌面入口，启动器能找到它。`sudo apt install ./nanoMuse-Desktop-<version>-linux-x64.deb`。
- **AppImage 需要 FUSE。** 它启动时把自己挂载起来；机器上没有 `libfuse2`，或者不允许
  `fusermount`（容器、某些企业镜像；日志写 `fusermount: mount failed: Operation not permitted` /
  `Cannot mount AppImage, please check your FUSE setup`）时，改为解包运行：
  `./nanoMuse-Desktop-<version>-linux-x64.AppImage --appimage-extract-and-run`，或者拿
  **`.tar.gz`**，同一个应用，只是一个普通文件夹：解压到任何地方，在里面运行
  `./nanomuse-desktop`（不要 FUSE，不要 root）。
- **图标点了没反应。** 应用一次只允许一个实例：已经有一份在跑时点启动器，是在告诉*那一份*把
  窗口显示出来。到 0.1.36 为止，关掉了窗口的那一份会为了托盘图标继续活着，却不回应；点击看
  起来像死了。从 0.1.37 起，正在跑的那一份收到点击会重新打开窗口；更早版本的那一份还在托盘
  里：在那里退出它（「退出」），或者 `pkill -f /opt/nanoMuse/nanomuse-desktop`，再点一次。
  只有「设置 → 通用 → 应用行为」里的菜单栏开关打开时，关窗口才会让应用留在托盘里；关着时，
  关窗口就是退出。不管哪种情况，在窗口里 **Ctrl+Q** 都能退出（帮助 → 退出；按 Alt 显示菜单栏）。
- **Ubuntu 20.04 上没有托盘图标。** GNOME 3.36 的 appindicator 扩展（v33）不接受 Electron 44 发来
  的注册（总线名后面附了对象路径），于是图标退回到 GNOME Shell 不显示的 XEmbed 托盘：应用在
  托盘里，只是看不见。Ubuntu 22.04 及更新的版本能显示。在 20.04 上用 Ctrl+Q，或者关掉菜单栏
  选项，让关窗口就退出。
- **图片走 WebAssembly。** harness 用 sharp 读取和缩放图片（给模型看的图、手的截图），sharp 的原生
  版本自带一份 GLib；Electron 的 Linux 二进制链接的是系统的 GLib，并把符号泄漏到同一个进程里
  （electron/electron#46323），结果每处理一张图就打一行 `GLib-GObject-CRITICAL`，在某些系统上
  解码第一张图时 harness 直接 SIGSEGV 退出，「读图」调用没有任何回答，这一轮就丢了。所以 Linux 包
  带的是 sharp 的 WebAssembly 版本，不带原生版本；一张图大约多花一倍时间（2560×1440 的截图约
  50 毫秒），其他不变。1.0.1 及更早的副本可以手工修：在 `resources/dsh/node_modules` 里运行
  `npm install @img/sharp-wasm32@0.35.5`，再删掉 `@img/sharp-linux-x64` 和
  `@img/sharp-libvips-linux-x64`，sharp 就会改用 WebAssembly 版本。
- **Wayland。** 手通过 X11 操作鼠标、读取屏幕；在 Wayland 会话里它们会说明情况并保持关闭
  （「设置 → 电脑操作」里的「截一张测试图」和第一句「我屏幕上是什么？」都会回答*这台电脑上手是
  关着的：Wayland 会话：…用 Xorg 登录…*），运行时也不会背着应用去试 `xdotool` 或 `pyautogui`
  （在 XWayland 下它们能启动，却动不了任何你看得见的东西）。在登录界面选「Ubuntu on Xorg」。
  会话类型从 `XDG_SESSION_TYPE` 读；手动启动的 Wayland 合成器表现为只有 `WAYLAND_DISPLAY`、
  没有 `DISPLAY`，这也算。
- **在这台电脑上动手**（X11）。什么都不用授权：应用自己的操作器通过 libnut（XTEST）移动指针和
  打字，通过 Electron 的截图器截图，运行时的 `nanomuse mcp` 经回环地址连到它；不需要 `xdotool`、
  `pyautogui` 或 `mss`，只要应用的操作器在回应，它们一个都不会被用到。指针在应用启动时所在的
  那个 X 显示（`DISPLAY`）上移动，坐标是根窗口像素：在 HiDPI 桌面上，那是逻辑尺寸乘以缩放系数
  （1920×1080、缩放 2 倍的显示器，对手来说是 3840×2160），模型看到的图是那个根窗口缩小到最宽
  1600、最多 2 Mpx。手干活时应用在屏幕边缘画的那一圈（光晕，沿四条边轻轻呼吸的一道光）不接收
  点击：每次指针动作它都会让开（指针移动前先隐藏，移动后立刻回来，标记落在点击的位置上，
  所以每次点击它会闪大约 150 ms），它的 X11 输入区域（Chromium 在窗口边界每次变化时都会清掉）
  在每次这样的变化之后都重新设置；万一有一次点击还是落到了光晕上，应用当场再设一次区域，并往
  日志里写一行（`glow: the pointer reached the glow …`）。打字和按键不动指针，所以这时光晕留着
  不动，焦点也不受影响。要有一个窗口管理器才能截出像样的图（没有的话 Electron 的截图器可能返回
  全黑的一帧，这时运行时退回到自己的截图方式）。替你出手的步骤（回车、提交、重量级快捷键、
  点在敏感词清单上的字眼）会等聊天里或胶囊上的卡片；「允许一次」执行这一步；「本对话中始终允许」
  只在这个对话里让手在那个应用里不再询问；定时任务运行时，这个按钮换成「此定时任务中始终允许」，
  只在这个任务运行时不再询问，你在同一个对话里手动让它做的事照样会问；「在 <app> 里始终允许」
  在所有对话里都不再询问。这几种都可以在「设置 → 权限」里撤回。定时任务运行时电脑旁可能没人，
  所以它的卡片也会送到账号下的手机上：手机上可以选「允许一次」「此定时任务中始终允许」或「拒绝」，
  哪里先回答就按哪里的算，其余的卡片随之收起（[hub.md](hub.md#a-computer-s-own-cards-on-the-phone)）。ASCII 之外的文字通过剪贴板
  和 Ctrl+V 输入（不需要 `xclip`/`xsel`，用的是 Electron 的剪贴板）；之后把原来的剪贴板内容
  放回去。
- 日志是 `~/.nanomuse/desktop/desktop.log`（操作器的每个动作一行，`operator: click at 1249,1096`）；
  启动器那边的在 `journalctl --user -n 200`。
