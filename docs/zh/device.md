# 使用手机自身的功能 {#手机自己的能力}

> **旧版 Python 实现的设计记录**。当前 Android App 使用 OpenMinis 提供的设备工具，并通过 Reach 和 hub（设备互联）访问电脑，见 [android.md](android.md)、[hub.md](hub.md)。下文提到的 connect 构建已不再提供。

在手机上运行时，nanoMuse 可以使用剪贴板、日历、联系人、位置、时钟 App 的闹钟和计时器、通知栏，以及通过系统选择器选中的照片。本文说明这些功能如何接入、每个工具能做什么、何时需要用户授权，以及它们的访问边界。

设计原则是：模型通过工具调用手机功能，授权则由 Android 自己的对话框完成。nanoMuse 不能给自己授权。每项权限都由系统询问用户，照片必须由用户在系统选择器中选择，闹钟交给用户已有的时钟 App 设置。Python 智能体无需为了手机而更改实现，Kotlin 程序负责提供这些工具。

```
 nanomuse serve (Python, in PRoot)                 the app (Kotlin)
 ┌──────────────────────────────┐   HTTP, 127.0.0.1    ┌───────────────────────────────┐
 │ MCP client  ── device__* ────┼──────────────────────►│ McpEndpoint  (Streamable HTTP) │
 │ Sentinel: per-tool defaults  │   Bearer / ?token=    │  DeviceTools: 13 tools         │
 │ nanomuse-device (CLI bridge) │◄──────────────────────┤  Ask: Android's dialogs        │
 └──────────────────────────────┘   SSE + heartbeats    │  DeviceAskActivity (invisible) │
                                                        └───────────────────────────────┘
```

## 模型如何获得这些工具 {#how-the-tools-reach-the-model}

App 会在 `127.0.0.1` 上启动 MCP 服务器。MCP 是让智能体发现并调用工具的协议。服务器使用随机端口和随机令牌，分别通过 `NANOMUSE_HOST_URL` 和 `NANOMUSE_HOST_TOKEN` 交给运行时（执行智能体任务的程序）。`nanomuse serve` 读取后，将服务器注册为 `device`，无需手动配置或安装。工具与其他 MCP 工具一样使用，名称为 `device__<tool>`，例如 `device__calendar_list`、`device__clipboard_read`。系统提示词会加入「这台手机」一节，列出工具，并说明基本约束：首次使用某项功能时 Android 会请求用户授权；只有 App 位于前台时才能读取剪贴板。

接口使用 [Streamable HTTP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports) 传输，通过 `POST /mcp` 接收 JSON-RPC 格式的请求。`tools/call` 用 SSE（服务器持续推送事件的连接）返回结果，并每 8 s 发送一行 `: keep-alive` 心跳，因为等待用户操作对话框可能需要几分钟。`GET /mcp` 返回 `405`。令牌可放在 `Bearer` 请求头或 `?token=` 参数中。服务器在 `initialize` 时发出 `Mcp-Session-Id` 请求头，并原样返回客户端的 `protocolVersion`。服务仅提供 `/mcp` 路径，只监听本机回环接口；缺少正确令牌的请求会被拒绝，令牌使用恒定时间比较。

智能体在沙箱内运行的脚本，也能通过命令行桥接访问这些工具，见 [local-runtime.md](local-runtime.md#the-python-side-on-a-phone)。例如：`nanomuse-device clipboard read`、`nanomuse-device calendar list from=2026-09-24`、`nanomuse-device alarm set hour=7 minute=30 message=Train`、`nanomuse-device notify title=Done body=Booked`、`nanomuse-device location`、`nanomuse-device photo pick`。`nanomuse-device list` 可以列出手机支持的功能。这些调用与模型直接调用一样，都经过哨兵（Sentinel）检查。

## 工具列表 {#the-tools}

| 工具 | 功能 | 参数 | Android 权限 | 风险 | `ask` 模式下需要审批？ |
| --- | --- | --- | --- | --- | --- |
| `clipboard_read` | 读取剪贴板文字 | — | 无，但 Android 10+ 要求 **App 位于前台** | moderate，隐私 | 否 |
| `clipboard_write` | 将文字写入剪贴板 | `text` | 无 | safe | 否 |
| `notify` | 发送通知，点击后打开聊天 | `title`、`body`、`thread` | `POST_NOTIFICATIONS`（13+） | safe | 否 |
| `calendars` | 列出手机上的日历 | — | `READ_CALENDAR` | moderate，隐私 | 否 |
| `calendar_list` | 查询指定时间段的日程，可按关键词筛选 | `from`、`to`、`query`、`calendar_id`、`limit` | `READ_CALENDAR` | moderate，隐私 | 否 |
| `calendar_create` | 新建日程，全天日程使用日期 | `title`、`start`、`end`、`all_day`、`location`、`description`、`calendar_id`、`reminder_minutes` | `WRITE_CALENDAR` | moderate | 否 |
| `calendar_update` | 修改传入的日程字段 | `id`、`title`、`start`、`end`、`all_day`、`location`、`description` | `WRITE_CALENDAR` | moderate | 否 |
| `calendar_delete` | 删除日程 | `id` | `WRITE_CALENDAR` | **sensitive** | **是** |
| `contacts_search` | 按姓名、号码或邮箱查找联系人，只读 | `query`、`limit` | `READ_CONTACTS` | moderate，隐私 | 否 |
| `location` | 获取坐标和精度，能解析时也返回地址 | `accuracy`（`fine`/`coarse`）、`max_age_seconds` | `ACCESS_FINE_LOCATION` / `ACCESS_COARSE_LOCATION` | moderate，隐私 | 否 |
| `alarm_set` | 在时钟 App 中设置闹钟 | `hour`、`minute`、`message`、`days`、`vibrate` | `SET_ALARM`（安装时授予） | moderate | 否 |
| `timer_set` | 在时钟 App 中设置倒计时 | `seconds` 或 `minutes`、`message` | `SET_ALARM` | moderate | 否 |
| `photo_pick` | 由用户在系统选择器中挑选照片，并复制到工作区 | `max`（≤ 10）、`why` | 无，Photo Picker 不需要权限 | safe，隐私 | 否 |

表中的风险等级和隐私标记来自 `nanomuse/runtime.py` 的 `DEVICE_TOOLS`，是哨兵为这些工具设置的默认值。`safe`、`moderate`、`sensitive` 分别表示安全、中等和敏感风险。默认值通过 MCP 服务器条目的 `tools` 映射逐项应用，见 [configuration.md](configuration.md#mcp-servers)。「需要审批」指哨兵是否询问你允许此次操作，对应 [sentinel.md](sentinel.md) 中的 `ask` 模式；在 `strict` 模式下，moderate 工具也都需要审批。标为隐私的工具会将当前对话标记为已污染，即后续可能包含私密信息。例如调用 `contacts_search` 或 `location` 后，向未知主机发送数据的操作都需要你确认。时间采用手机当地时间，格式为 `YYYY-MM-DD HH:MM`，全天日程只用日期；全天日程的结束时间显示为最后一天。`location` 的地址由手机平台的地理编码服务解析，没有该服务时只返回坐标。

Kotlin 的 `DeviceTools.kt` 与 Python 的 `DEVICE_TOOLS` 必须保持一致。`tests/test_bridge.py` 会检查工具名称和默认规则。

## 用户看到的授权流程 {#what-the-user-sees}

工具需要用户确认时，都通过 Android 对话框完成。App 使用不可见的 activity（Android 界面组件）`DeviceAskActivity` 打开对话框，让智能体无论在哪里执行都能请求授权。Android 10+ 不允许后台 App 直接启动 activity，因此分两种情况：

- **App 位于前台**：对话框立即显示在 App 上方。
- **App 位于后台**：先发送通知，例如「nanoMuse 需要一项权限」「nanoMuse 想读取剪贴板」或「nanoMuse 想要一张照片」，并用一行文字说明原因。点击通知后才显示对话框。工具会等待结果：权限最多等 2 分钟，剪贴板 1.5 分钟，照片 4 分钟。无论结果如何，模型都会收到说明。

模型收到三种结果之一：用户已允许，工具继续执行；用户未允许，当前不要再次询问，之后可在 Android 设置中授权；无人回应，请用户打开 nanoMuse 后重试。这些说明可以直接转述给用户。

以下行为由 Android 平台规则决定：

- **剪贴板**。从 Android 10 起，只有获得焦点的 App 能读取剪贴板。因此后台发起 `clipboard_read` 时先发通知，用户点击通知的那一刻才读取。写入不受前台限制。
- **闹钟和计时器**。工具使用标准 `AlarmClock` intent（交给其他 App 处理的系统请求）调用时钟 App，跳过它的设置界面，生成的闹钟与手动设置相同。App 位于前台，或具有「显示在其他应用上层」权限时，会立即完成交接。后台时 Android 禁止直接启动其他 App，因此先发通知，用户点击后才设置闹钟。工具使用手机已有的时钟 App；如果没有，会明确告知。
- **照片**。仅通过 [Photo Picker](https://developer.android.com/training/data-storage/shared/photopicker) 访问。用户选中哪些照片，App 就只获得哪些，将副本放入 `workspace/attachments/<date>/` 并返回路径。相册其他内容不可读取，也不会申请 `READ_MEDIA_IMAGES`。系统选择器界面也会说明这个范围。
- **位置**。使用平台 `LocationManager`，不依赖 Play 服务。上次定位足够新时直接使用，时效由 `max_age_seconds` 控制，默认 2 分钟；否则重新定位，最多等待 25 s。`coarse` 只申请大致位置权限。
- **联系人与日历**。联系人只能读取；日历通过系统内容提供器读写。删除日程是其中始终需要审批的操作。
- **通知**。`notify` 通过普通通知渠道发送，点击后打开相应对话线程。不提供读取通知栏功能，因为它需要「通知使用权」，Android 将其视为覆盖整个设备的特殊权限。如果以后实现这项功能（P2），会提供单独开关，默认关闭，并在哨兵规则表中单独列出。

## 在「文件」App 中访问工作区 {#the-workspace-in-the-files-app}

local 构建会注册 `DocumentsProvider`，通过 Android 存储访问框架把智能体工作区显示为一个以智能体命名的根目录。你可以在系统「文件」App，以及手机上的打开或保存对话框中访问它。智能体生成的是普通文件，放入该目录的文件也会进入工作区。隐藏条目和浏览器配置目录不显示。connect 构建不在手机上保存工作区，因此不会显示该根目录。

## 分享到 nanoMuse {#sharing-into-nanomuse}

系统分享面板支持将文字、链接和文件分享给 nanoMuse。每次分享都会创建新对话：文件上传到工作区的 `attachments/<date>/…`，对话按主题或第一个文件命名；打开聊天后，分享文字先放在输入框中作为草稿，文件显示为附件标签，等待你说明如何处理。你发送指令前，不会向模型发送任何内容。两个构建都支持该流程，其中 connect 构建将文件上传到电脑。

## connect 模式 {#connect-mode}

connect 构建将手机作为电脑上 `nanomuse serve` 的远程界面。它虽然包含同样的 Kotlin 工具，但电脑服务器无法访问手机的 `127.0.0.1`，需要通过手机 WebSocket（保持双向通信的网络连接）转发请求。旧版计划将其列为 P1，见 [launch-checklist.md](../launch-checklist.md)。在该功能实现前，设备工具只能由手机本地运行时使用。

## 没有手机时如何测试 {#testing-without-a-phone}

x86_64 模拟器无法运行 arm64 PRoot 运行时，但可以直接测试 Kotlin 工具服务。connect 的 debug 构建会自行启动 MCP 服务器，并打印日志 `device MCP (debug): http://127.0.0.1:<port>/mcp token=<token>`。随后运行：

```bash
adb forward tcp:9410 tcp:<port>
# any MCP client, e.g. the reference Python one:
#   streamable_http_client("http://127.0.0.1:9410/mcp?token=<token>")
```

`adb shell pm revoke <app id> android.permission.READ_CALENDAR` 可以撤销日历权限，让系统再次显示授权对话框；`adb shell input keyevent KEYCODE_HOME` 可以让 App 退到后台，测试通知流程；`adb emu geo fix <lon> <lat>` 可以为 `location` 提供模拟坐标。`McpEndpointTest` 在 JVM 上测试传输协议，包括 initialize、`tools/list`、带心跳的 SSE 调用、将工具失败表示为 `isError`，以及错误令牌和请求方法。

## 这个版本不提供的功能 {#not-in-this-release}

不提供读取通知、修改联系人、访问整个相册、读取短信和通话记录，也不提供 connect 模式的设备请求转发。以后加入这些功能时，每项都会有独立开关，并默认关闭。
