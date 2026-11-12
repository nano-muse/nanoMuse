# 浏览器

> **本文部分内容属于旧版 Python 实现的设计记录**。Playwright 后端、工具动作、带登录态的 `fetch` 和测试说明仍适用于电脑上的 Python 运行时。手机部分，包括 `device` 后端、虚拟显示器及下文手机浏览器协议，属于旧版 Python Android App。当前 Android App 使用 OpenMinis 的 `browser_use` 工具，页面需要用户处理时通过 `hand_over` 动作交接，见 [android.md](android.md#what-the-phone-does)。

智能体使用同一个浏览器工具，底层可连接两种浏览器：服务器电脑上由 Playwright 控制的 Chromium，以及 nanoMuse 手机 App 内的 WebView（内嵌浏览器）。两种后端提供相同的动作、网页元素编号、聊天画面和接管流程。因此，为其中一种编写的技能也适用于另一种，任务从电脑移到手机时无需修改技能。

访问服务时，智能体先尝试 API（程序调用接口）、MCP 服务器（向智能体提供工具的服务）或命令行工具；其次使用带登录态的 `fetch`，也就是携带浏览器 cookie 直接发送请求，不渲染页面；然后才操作浏览器页面；最后才操作手机 App 的屏幕，见 [gui.md](gui.md)。浏览器工具负责其中第二和第三级。

## 两种后端 {#two-backends}

| | `playwright` | `device` |
| --- | --- | --- |
| 运行位置 | 服务器上的无头 Chromium，即不显示本地窗口的浏览器 | nanoMuse 手机 App 中的离屏 WebView |
| 使用条件 | `pip install "nanomuse[browser]" && playwright install chromium`，或使用 `-browser` Docker 镜像 | App 保持连接，两个构建变体都支持；local 构建始终具备此功能 |
| 登录状态存放位置 | `<workspace>/browser-profile/` 持久配置目录，重启后可保留登录 | 手机上的 App WebView cookie 存储 |
| 接管方式 | 在浏览器卡片中点击画面、输入文字或按 Enter | 将原来的 WebView 移入 App 弹出面板，不重载页面，保留 cookie，可直接触摸真实网页 |
| 网站识别到的客户端 | Linux Chrome，或配置指定的 user agent（浏览器身份标识） | Android WebView，或配置指定的 user agent |

默认的 `backend = "auto"` 会优先使用已连接且提供浏览器的 nanoMuse 手机 App，否则使用 Playwright。手机 local 构建中没有 Chromium，因为 PRoot 无法启动它，所以始终使用 WebView。

```toml
[browser]
enabled    = true
backend    = "auto"     # auto | playwright | device
profile    = ""         # mobile | desktop | "" (the backend's own: mobile on the phone, desktop on a computer)
headless   = true       # Playwright only
timeout_ms = 30000
```

`NANOMUSE_BROWSER_ENABLED=1` 用于启用工具，`NANOMUSE_BROWSER_BACKEND` 用于选择后端。手机环境 `NANOMUSE_DEVICE=android` 默认启用该工具。

如果你把运行时嵌入自己的程序，并且已经有浏览器，例如远程浏览器服务，无需再增加一种配置值。给 `Browser` 工具传入 `backend_factory` 即可。它是一个返回 `BrowserBackend` 的可调用对象，接口定义在 `nanomuse/tools/browser_backends.py`，两个内置后端也实现了这个接口。新会话会使用工厂提供的后端，之后的行为相同：通过原有动作控制，App 显示画面并支持接管，`close` 或工具清理时关闭后端，每个 URL 打开前都经过哨兵（Sentinel）检查。首次会话前，App 收到的后端类型为 `custom`，此后为后端自身的 `kind`。只有旧后端关闭后才会再次调用工厂，因此一个会话始终使用同一个后端。

## 智能体可以执行哪些操作 {#what-the-agent-can-do}

两个后端都支持下列动作：

| 动作 | 功能 |
| --- | --- |
| `navigate url` | 打开页面，返回可交互元素列表及编号 |
| `extract` | 提取页面文字的前几千个字符 |
| `click n` | 点击上次列表中编号为 `n` 的元素中心 |
| `type n text` | 向元素 `n` 输入文字，并触发页面自身的输入事件，让 React、Vue 表单识别变化 |
| `key key` | 按 Enter、Tab、Escape 等按键 |
| `scroll dy` | 按像素滚动，负数表示向上 |
| `back` | 返回浏览历史的上一页 |
| `wait [seconds]` | 最多等待 15 s，再返回页面状态，适用于 `load` 事件后还在渲染的单页应用 |
| `screenshot` | 获取新截图并显示在聊天卡片中 |
| `fetch url [method] [body]` | 携带浏览器 cookie 发送 HTTP 请求，不渲染网页，例如获取 JSON 订单列表、登录后的 `.ics` 文件或提交表单 |
| `profile name` | 切换为 `mobile`，视口 412×915 并使用手机 user agent；或 `desktop`，视口 1280×900；也可自定义 user agent 和尺寸 |
| `close` | 关闭页面，保留配置目录及 cookie |

`navigate` 仅接受公网 HTTP 和 HTTPS 地址。运行时既检查初始主机，也检查导航完成后的 URL，因此会拒绝 `localhost`、私有地址和重定向到内网的公网链接。Playwright 还会在浏览器请求继续发送前再次检查，以缩短 DNS 地址检查与实际连接之间的时间间隔。
智能体读取、截图或操作当前页面前，也会拒绝本地文件和自定义浏览器协议。空白页和内联文档（`about:blank`、`about:srcdoc`）、data URL 和 blob 资源仍可使用。浏览器的 `fetch` 只跟随 HTTP(S) 重定向。用户接管时，仍能查看自己正在使用的页面。

每次改变页面的动作都会向聊天发送一帧画面，包含网页 JPEG、标题、URL 和简短操作说明，例如「点击了登录」。画面尺寸与当前配置的视口 CSS 像素尺寸一致，图片上的坐标可直接映射到页面，接管功能据此实现。画面在会话期间保留在服务器内存中，每段聊天保留最近约十二帧。

手机沙箱中的脚本可以用 `nanomuse-browser <action> …` 调用同一工具，见 [local-runtime.md](local-runtime.md#the-python-side-on-a-phone)。例如 `nanomuse-browser fetch https://example.com/api/orders` 就是从 shell 使用第二级访问方式，同样受哨兵检查。

Python 运行时将明确请求保存的截图放入 `<workspace>/screenshots/`，文件名带时间戳。同一秒生成的截图会分配不同名称，例如 `20260101-120000-2.jpg`，不会覆盖之前的图片。

## 登录网站 {#logging-in}

需要登录时，由你操作登录页面。智能体会在表单前停下，调用 `browser` → `hand_over` 并说明原因，例如登录 12306、输入短信验证码、完成人机验证或确认付款。你完成后点击「完成」，智能体再根据当前页面继续。整个交接通过聊天中的浏览器卡片完成；你主动接管时也使用同一张卡片。

- **服务器 Chromium**：点击卡片上的「接管」，或接受智能体主动交接。随后可以点击画面、滚动、后退、在当前输入框中打字、按 Enter，或打开其他 URL。点击「完成」后交回。画面中的点按会映射到真实网页；接管期间每秒刷新一次。网页控制台也支持键盘操作：用 Tab 将焦点移到画面，方向键和 Page 键滚动，Enter 向网页发送回车，画面下方按钮可完成其他操作，无需鼠标。
- **手机 WebView**：点击「接管」后，真实 WebView 会移入 App 的底部面板，显示的是网页本身。你可以使用手机键盘、自动填充和密码管理器登录，再点击「完成」。WebView 随后移回屏幕外，智能体收到交还通知，下次查看时看到的就是操作后的页面。

接管期间会建立一个 hold（等待用户完成操作的暂停状态），这段对话中的所有浏览器动作都会等待。智能体最多等待十分钟；超时后，会依据当前页面继续，并说明你尚未回来。聊天、实时舞台、胶囊和浏览器查看器都显示同一张「轮到你了 · <reason> · 完成」卡片。API 调用方式是向 `POST /api/browser/{thread}/control` 发送 `take_over` / `handed_back`，或调用 `POST /api/holds` 和 `POST /api/holds/{id}/done`；`GET /api/state` 会列出尚未结束的 hold。

密码直接提交给网站，不经过模型。模型看到的是你完成后的页面画面。智能体只会通过 `ask_user` 询问需要知道的信息，例如使用哪个账号或哪个日期，不会向你索要密码或验证码。

登录 cookie 会持久保存。服务器上的 Playwright 使用真实 Chromium 配置目录；手机 WebView 在每次导航和 `fetch` 后将 cookie 写入磁盘。会话 cookie 不带过期时间，浏览器关闭后会丢失，两种后端在服务器重启后都无法保留它。因此，只使用会话 cookie 的网站会在 `nanomuse serve` 重启后要求重新登录。多数网站在勾选「记住我」后会设置有效期更长的 cookie。

### 不支持的情况及原因 {#what-does-not-work-and-why}

- **Google 账号不能在 WebView 中登录**。Google 禁止嵌入式登录，会返回 `disallowed_useragent`。接管面板的箭头可以在系统浏览器中打开相同 URL，但系统 Chrome 中的登录不会同步到 nanoMuse WebView。使用 Google 服务时，请采用 API 方式，例如日历私密 `.ics` 链接或邮箱应用专用密码。服务器 Chromium 可以登录 Google，但也可能被判定为「不安全」并要求额外验证。
- **同一部手机无法扫描自己屏幕中的登录二维码**。微信、支付宝、淘宝等网站要求用手机 App 扫码时，二维码已经显示在这部手机上，无法再用它的摄像头扫描。服务器 Chromium 则可以把二维码显示在聊天画面中，供手机扫描；这种情况使用服务器浏览器更方便。
- **通行密钥无法通用**。passkey（通行密钥）保存在创建它的浏览器凭据存储中。手机 Chrome 创建的通行密钥不能由 WebView 读取，服务器无头 Chromium 也没有这些凭据。密码加验证码的方式则可以在各端使用。
- **下载位置不同**。服务器 Playwright 将文件保存到 `<workspace>/downloads/`；手机 local 构建也保存到工作区，智能体可以读取。connect 构建的智能体在电脑上，下载则保存到手机「下载」文件夹。
- **仅有一个标签页**。原本要求打开新窗口的链接，会改为在当前页面打开。

## 手机浏览器的实现方式 {#how-the-phone-s-browser-works}

WebView 需要处于可见状态才能正常刷新。隐藏的 WebView 会停止 `requestAnimationFrame` 动画回调，并将定时器限制为每秒一次，导致不少页面无法完成加载。因此 App 为它创建私有虚拟显示器：以不可见的 `ImageReader` 表面作为显示目标，在其中放置承载 WebView 的 `Presentation` 窗口。不论 App 是否在前台，Chromium 都能正常合成画面。`screenshot` 返回最新一帧，因此视频、canvas 和 WebGL 内容也能反映实际状态。模拟器中 App 位于后台时，实测每秒 60 次 rAF、`setInterval(10 ms)` 每秒 100 次，`visibilityState = visible`。设备不允许创建虚拟显示器时，程序会改为手动测量和绘制 WebView。

点击通过向元素中心注入触摸事件实现。输入文字时先调用页面自身的 setter，再触发 `input` / `change`，让前端框架识别变化；Enter 则作为按键发送。整个工具只有一个页面对象，接管时将同一个 `WebView` 移入面板，完成后再移回，因此页面不重新加载。cookie 和第三方 cookie 都已启用，每次加载和 `fetch` 后调用 `CookieManager.flush()` 写入磁盘。

### 通信协议 {#the-protocol}

手机 socket（双向网络连接）建立时，会发送 `{"kind": "device", …, "browser": true}` 声明浏览器能力。此后，服务器发送带 `op: "browser"` 的 `device_request`，手机以相同 `id` 的 `device_result` 返回结果。以下操作定义在 `nanomuse/tools/browser_backends.py` 的 `DeviceBackend` 中，由 `android/…/browser/DeviceBrowser.kt` 实现：

```
open      {user_agent, width, height, mobile}  → {url, title, width, height, …}
navigate  {url}                                → {url, title, …}
evaluate  {js, arg}                            → {value, encoded: "json"}   runs (js)(arg)
tap       {x, y}                               → {}                          CSS px of the viewport
type      {text}                               → {}                          into the focused element
key       {key}                                → {}
scroll    {dy}                                 → {}
back      {}                                   → {url, title, …}
settle    {timeout_ms}                         → {}
screenshot {quality}                           → {jpeg: base64, width, height}
state     {}                                   → {url, title, width, height, loading, user_control, host}
fetch     {url, method, headers, body}         → {status, headers, body, url}   with the WebView's cookies
profile   {user_agent, width, height, mobile}  → {}
close     {}                                   → {}
```

未知操作或执行失败时，返回 `{"ok": false, "error": "…"}`，错误文字可供模型理解。其他 App 若想向 nanoMuse 服务器提供自己的浏览器，需要实现这十四个操作及初始 hello 消息。

## 测试方式 {#testing-it}

`tests/test_browser.py` 使用模拟后端检查两种实现的一致性、画面及接管交还流程。安装 Playwright 和 Chromium 后，也会测试真实后端的持久配置、重启后 cookie、携带会话的 `fetch` 和配置切换。手机部分已在 Android 13 模拟器上完成端到端验证，覆盖上述所有操作、网页设置的 cookie 能否用于 `fetch`、输入是否进入正确字段、接管面板是否显示同一个实时页面，以及交还通知能否到达服务器。仍需真机验证的部分是厂商电池管理暂停 App 进程的影响，以及 Android 8–10 的虚拟显示器兼容性。
