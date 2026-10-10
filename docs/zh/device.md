# 手机自己的能力

> **Python 线路的设计记录。** 在当前的 Android 应用里，手机的能力就是 OpenMinis 的设备工具，
> 电脑则通过 Reach 和 hub 够到（[android.md](android.md)、[hub.md](hub.md)）；下文提到的
> 「connect 构建」已经不存在了。


在手机上，nanoMuse 够得着手机上有的东西：剪贴板、日历、联系人、手机在哪里、时钟里的闹钟和计时器、通知栏，以及通过系统选择器访问的相册。本页讲这些是怎么工作的、每个工具可以做什么、它会问用户什么，以及它刻意做不到什么。

设计的原则：**模型拿到的是工具，用户看到的是 Android 自己的对话框。** nanoMuse 从不自己给自己授权。每一项权限都由平台的对话框来问，相册只能通过平台的选择器看到，闹钟交给用户已有的时钟 App。Python 大脑不为了跑在手机上而改动；Kotlin 这一侧只是一个小小的工具宿主。

```
 nanomuse serve (Python, in PRoot)                 the app (Kotlin)
 ┌──────────────────────────────┐   HTTP, 127.0.0.1    ┌───────────────────────────────┐
 │ MCP client  ── device__* ────┼──────────────────────►│ McpEndpoint  (Streamable HTTP) │
 │ Sentinel: per-tool defaults  │   Bearer / ?token=    │  DeviceTools: 13 tools         │
 │ nanomuse-device (CLI bridge) │◄──────────────────────┤  Ask: Android's dialogs        │
 └──────────────────────────────┘   SSE + heartbeats    │  DeviceAskActivity (invisible) │
                                                        └───────────────────────────────┘
```

## 工具怎么到模型那里 {#how-the-tools-reach-the-model}

应用在 `127.0.0.1` 上启动一个 MCP 服务器（随机端口、随机 token，两者作为 `NANOMUSE_HOST_URL` 和 `NANOMUSE_HOST_TOKEN` 交给运行时）。`nanomuse serve` 看到它们，就把这个服务器加为 `device`（不用配置，不用安装），于是这些工具像任何别的 MCP 服务器的工具一样出现，名字是 `device__<tool>`（`device__calendar_list`、`device__clipboard_read`……）。系统提示词里多出一小段「这台手机」，列出这些工具，以及模型必须知道的基本规则：第一次用某项能力时 Android 会问用户，剪贴板只能在应用在屏幕上时读。

端点说的是 [Streamable HTTP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)：`POST /mcp` 走 JSON-RPC；`tools/call` 以 SSE 流回答，每 8 s 一行 `: keep-alive`，因为一次调用可能要等用户回答对话框等上几分钟；`GET /mcp` 是 `405`；token 放在 `Bearer` 头或 `?token=` 里；`Mcp-Session-Id` 头在 `initialize` 时发出，客户端的 `protocolVersion` 原样回传。只有 `/mcp` 这一个路径。它只绑定回环接口，没有 token 的请求一律拒绝（用常量时间比较）。

智能体在沙箱里跑的脚本通过 CLI 桥够到同一批工具（[local-runtime.md](local-runtime.md#the-python-side-on-a-phone)）：`nanomuse-device clipboard read`、`nanomuse-device calendar list from=2026-09-24`、`nanomuse-device alarm set hour=7 minute=30 message=Train`、`nanomuse-device notify title=Done body=Booked`、`nanomuse-device location`、`nanomuse-device photo pick`；`nanomuse-device list` 列出这台手机有什么。每一条都和模型调用一样经过同一个哨兵（Sentinel）。

## 工具 {#the-tools}

| 工具 | 做什么 | 参数 | Android 权限 | 风险 | `ask` 模式下会问？ |
| --- | --- | --- | --- | --- | --- |
| `clipboard_read` | 剪贴板里的文字 | — | 无，但**只能在应用在屏幕上时**（Android 10+） | moderate，隐私 | 否 |
| `clipboard_write` | 把文字放进剪贴板 | `text` | 无 | safe | 否 |
| `notify` | 发一条通知；点它打开聊天 | `title`、`body`、`thread` | `POST_NOTIFICATIONS`（13+） | safe | 否 |
| `calendars` | 手机上的日历 | — | `READ_CALENDAR` | moderate，隐私 | 否 |
| `calendar_list` | 某个时间段里的日程，可按关键词筛选 | `from`、`to`、`query`、`calendar_id`、`limit` | `READ_CALENDAR` | moderate，隐私 | 否 |
| `calendar_create` | 新建日程；全天日程给日期 | `title`、`start`、`end`、`all_day`、`location`、`description`、`calendar_id`、`reminder_minutes` | `WRITE_CALENDAR` | moderate | 否 |
| `calendar_update` | 改给出的那些字段 | `id`、`title`、`start`、`end`、`all_day`、`location`、`description` | `WRITE_CALENDAR` | moderate | 否 |
| `calendar_delete` | 删除一条日程 | `id` | `WRITE_CALENDAR` | **sensitive** | **是** |
| `contacts_search` | 按姓名、号码或邮箱找人；只读 | `query`、`limit` | `READ_CONTACTS` | moderate，隐私 | 否 |
| `location` | 坐标、精度，能查到时还有地址 | `accuracy`（`fine`/`coarse`）、`max_age_seconds` | `ACCESS_FINE_LOCATION` / `ACCESS_COARSE_LOCATION` | moderate，隐私 | 否 |
| `alarm_set` | 在时钟 App 里设一个闹钟 | `hour`、`minute`、`message`、`days`、`vibrate` | `SET_ALARM`（安装时授予） | moderate | 否 |
| `timer_set` | 在时钟 App 里设一个倒计时 | `seconds` 或 `minutes`、`message` | `SET_ALARM` | moderate | 否 |
| `photo_pick` | 用户在系统选择器里挑照片；副本落在工作区里 | `max`（≤ 10）、`why` | 无：Photo Picker 不需要权限 | safe，隐私 | 否 |

*风险*和*隐私*是 `nanomuse/runtime.py` 里 `DEVICE_TOOLS` 给出的哨兵默认值，通过 MCP 服务器条目的 `tools` 映射逐个工具套用（[configuration.md](configuration.md#mcp-servers)）。「会问」对应 [sentinel.md](sentinel.md) 里的 `ask` 模式那一列；`strict` 模式下每个 moderate 工具也会问。*隐私*工具会给这段对话带上隐私标记：`contacts_search` 或 `location` 之后，任何向未知主机发送数据的操作都会问。时间用手机本地时间（`YYYY-MM-DD HH:MM`，全天日程用日期）；全天日程的结束显示为它的最后一天。`location` 里的地址来自平台的地理编码器，手机上有它才有；没有的话工具只返回坐标。

Kotlin 这边的列表（`DeviceTools.kt`）和 Python 这边的表（`DEVICE_TOOLS`）必须一致；`tests/test_bridge.py` 检查名字和默认值。

## 用户看到什么 {#what-the-user-sees}

工具需要用户做的一切都是 Android 对话框，由应用的一个不可见 activity（`DeviceAskActivity`）打开，这样不管智能体在哪里跑它都能出现。Android 10+ 不允许后台应用启动 activity，所以有两条路：

- **应用在屏幕上** → 对话框立刻盖在它上面出现。
- **应用在后台** → 一条通知（「nanoMuse 需要一项权限」/「nanoMuse 想读取剪贴板」/「……想要一张照片」），附一行为什么；点它就弹出对话框。工具调用在这期间等着（权限等 2 分钟，剪贴板等 1.5 分钟，照片等 4 分钟），不管哪种结果都会告诉模型发生了什么。

到模型那里的结果有三种，用它可以转述的话说：已允许（工具运行）；「用户没有允许：现在不要再问，之后可以在 Android 的设置里允许」；「没有人回答：请用户打开 nanoMuse 再试一次」。

一些具体的规则，每一条都来自平台，而不是我们定的：

- **剪贴板。** 从 Android 10 起只有拿到焦点的应用才能读剪贴板。所以从后台发起的 `clipboard_read` 走通知那条路；用户点通知的那一刻才读。写入任何时候都可以。
- **闹钟和计时器。** 用标准的 `AlarmClock` intent 交给时钟 App，跳过它的界面（闹钟出现在时钟里，就像手动设的一样）。在前台（或者应用有「显示在其他应用上层」权限时），交接是即时的；在后台 Android 禁止启动另一个应用，所以发一条通知，用户点它时闹钟才设好。时钟 App 就是用户手机上的那个；没有时钟 App 的手机上，工具会这么说。
- **照片。** 只走 [Photo Picker](https://developer.android.com/training/data-storage/shared/photopicker)：用户挑，应用拿到的正是那几项，复制到 `workspace/attachments/<date>/` 下并返回路径。相册里的其他东西都读不到，不申请 `READ_MEDIA_IMAGES`，选择器本身在屏幕上也会这么说。
- **位置。** 用平台的 `LocationManager`，不用 Play 服务；上一次定位足够新（`max_age_seconds`，默认 2 分钟）就用它，否则重新定位一次，最多等 25 s。`coarse` 只申请大致位置权限。
- **联系人**只读。**日历**通过平台的 provider 读写；删除是唯一一个总会问的动作。
- `notify` 发出的**通知**走普通渠道；点它打开对应的线程。读取通知栏**不提供**：它需要通知监听这项特殊访问权，Android 把它当作全设备范围的特权；如果以后做（P2），它会是一个单独的开关，默认关闭，在哨兵的表里有自己的一行。

## 「文件」App 里的工作区 {#the-workspace-in-the-files-app}

本地构建注册了一个 `DocumentsProvider`：智能体的工作区以智能体的名字作为一个根，出现在系统的「文件」App 里，以及手机上每一个打开 / 保存对话框里（存储访问框架）。智能体做出来的文件是普通文件；放进去的文件就在工作区里。隐藏条目和浏览器配置目录不显示。connect 构建在手机上没有工作区，也不显示这个根。

## 分享到 nanoMuse {#sharing-into-nanomuse}

nanoMuse 在系统分享面板里接收文字、链接和文件。一次分享变成一个**新对话**：文件上传到工作区（`attachments/<date>/…`），线程以主题或第一个文件命名，聊天打开时分享的文字已在输入框里作为草稿，文件作为附件标签，等你说要拿它们做什么；你开口之前，什么都不会发给模型。两种构建都这么做（connect 构建上传到电脑）。

## connect 模式 {#connect-mode}

connect 构建（把手机当成电脑上 `nanomuse serve` 的遥控器）有同一套 Kotlin 工具，但服务器够不到手机上的 `127.0.0.1`；这需要经由手机的 WebSocket 做一次中转。这在计划里（P1，[launch-checklist.md](../launch-checklist.md)）；在那之前，设备工具是跑在手机上才有的功能。

## 没有手机怎么测 {#testing-without-a-phone}

模拟器（x86_64）跑不了 arm64 的 PRoot 运行时，但工具宿主可以直接测：connect 的 **debug** 构建会自己启动 MCP 服务器，并在日志里写 `device MCP (debug): http://127.0.0.1:<port>/mcp token=<token>`。然后：

```bash
adb forward tcp:9410 tcp:<port>
# any MCP client, e.g. the reference Python one:
#   streamable_http_client("http://127.0.0.1:9410/mcp?token=<token>")
```

`adb shell pm revoke <app id> android.permission.READ_CALENDAR` 让权限对话框重新出现；`adb shell input keyevent KEYCODE_HOME` 走一遍通知那条路；`adb emu geo fix <lon> <lat>` 给 `location` 喂数据。`McpEndpointTest` 在 JVM 上覆盖传输层本身（initialize、`tools/list`、一次带心跳的 SSE 调用、一个失败的工具作为 `isError`、错误的 token 和方法）。

## 这个版本里没有的 {#not-in-this-release}

读取通知、写联系人、整个相册、短信和通话记录，以及 connect 模式的中转。每一项到来时都是一个单独的开关，默认关闭。
