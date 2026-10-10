# 浏览器

智能体有一个浏览器工具，和两个可以跑它的浏览器：服务器所在电脑上经 Playwright 驱动的 Chromium，以及 nanoMuse 手机 App 里手机自己的 WebView。两边的工具是同一个（同样的动作、页面上同样编号的元素、聊天里同样的画面、同样的接管方式），所以针对一边写的技能在另一边也能用，一项任务从书桌挪到手机上，一行都不用改。

浏览器在整个顺序里的位置：智能体先通过服务的 API、MCP 服务器或命令行工具去够它；然后是**带登录态的 `fetch`**（带着浏览器 cookie 的一次请求，不渲染页面）；再然后才是浏览器页面本身；最后才是手机上某个 App 的屏幕（[gui.md](gui.md)）。浏览器是这条阶梯的第二级和第三级。

## 两个后端 {#two-backends}

| | `playwright` | `device` |
| --- | --- | --- |
| 跑在哪 | 服务器上，无头 Chromium | 手机上的 nanoMuse App 里，一个离屏 WebView |
| 需要什么 | `pip install "nanomuse[browser]" && playwright install chromium`（或者 `-browser` Docker 镜像） | App 已连接，两种版本都行；本地版一直带着它 |
| 登录态存在哪 | `<workspace>/browser-profile/`，一个持久的 profile 目录，所以登录能挺过一次重启 | App 的 WebView cookie 存储，在手机上 |
| 接管 | 在浏览器卡片上：点图片就是点击，打字，按回车 | 同一个 WebView 在 App 里滑上来：不重新加载，同样的 cookie，你的手指直接落在真实页面上 |
| 网站看到的是 | Linux 上的 Chrome（或者 profile 设定的 user agent） | Android WebView（或者 profile 设定的 user agent） |

`backend = "auto"`（默认值）在有带浏览器的 nanoMuse App 连着时用手机，否则用 Playwright。手机的本地版里没有 Chromium（PRoot 启动不了），所以 WebView 永远就是那个浏览器。

```toml
[browser]
enabled    = true
backend    = "auto"     # auto | playwright | device
profile    = ""         # mobile | desktop | "" (the backend's own: mobile on the phone, desktop on a computer)
headless   = true       # Playwright only
timeout_ms = 30000
```

`NANOMUSE_BROWSER_ENABLED=1` 打开这个工具；`NANOMUSE_BROWSER_BACKEND` 选后端。在手机上（`NANOMUSE_DEVICE=android`）这个工具默认是开着的。

## 智能体能做什么 {#what-the-agent-can-do}

工具的动作，两个后端完全一样：

| 动作 | 做什么 |
| --- | --- |
| `navigate url` | 打开一个页面；回复里列出页面上可交互的元素，带编号 |
| `extract` | 页面的文字（开头几千个字符） |
| `click n` | 点击上次列表里的元素 `n`（点它的中心，手指会做的事） |
| `type n text` | 填写元素 `n`，用页面自己的输入事件，这样 React 和 Vue 的表单能察觉到 |
| `key key` | 按 Enter、Tab、Escape…… |
| `scroll dy` | 按像素滚动，负数向上 |
| `back` | 在历史里后退一步 |
| `wait [seconds]` | 为还在自己绘制的页面（`load` 之后的单页应用）停最多 15 秒，然后给出页面状态 |
| `screenshot` | 给聊天卡片拍一张新图 |
| `fetch url [method] [body]` | 带着浏览器 cookie 的一次 HTTP 请求，不渲染页面：JSON 格式的订单列表、登录后才能拿到的 `.ics`、一次表单提交 |
| `profile name` | 以 `mobile`（412×915，手机的 user agent）或 `desktop`（1280×900）的身份出现，或者自定义 user agent 和尺寸 |
| `close` | 关闭页面；profile 和它的 cookie 留着 |

每个改变页面的动作都往聊天里发一帧：页面的 JPEG、标题和 URL，再加一句刚发生了什么的说明（「点击了“登录”」）。帧的尺寸就是 profile 视口的 CSS 像素尺寸，所以图上的一个点就是页面上的同一个点；接管靠的就是这一点。它们在服务器内存里保留到会话结束；每段聊天留最近十来帧。

在手机沙箱里的脚本中，同一个工具叫 `nanomuse-browser <action> …`（[local-runtime.md](local-runtime.md#the-python-side-on-a-phone)）：`nanomuse-browser fetch https://example.com/api/orders` 就是从 shell 里走第二级，受同一个哨兵（Sentinel）管着。

## 登录 {#logging-in}

要登录的页面是用户的事，不是模型的事。智能体在表单前停下来，把页面交出去（`browser` → `hand_over`，附上原因：*登录 12306*、*输入短信里的验证码*、*完成人机验证*、*确认付款*）；用户做完，按「完成」；智能体接着用页面当时的样子继续。这一切发生在聊天里的浏览器卡片上，用户先一步接管时出现的也是同一张卡片：

- **在服务器的 Chromium 上**：点卡片上的「接管」（或者智能体主动交出来），然后点图片就是点击、滚动、后退、往聚焦的输入框里打字、按回车，或者打开一个 URL；「完成」把页面还回去。帧就是页面；你的点按被映射到页面上；页面在你手里时每秒刷新一次。
- **在手机上**：「接管」把真实的 WebView 作为一张底部面板在 App 里滑上来，不是它的图片。用手机的键盘、自动填充和密码管理器登录，然后点「完成」。视图回到屏幕外，智能体被告知页面已经交还；它下一次看，看到的就是你留下的样子。

页面在你手里的这段时间（一次 *hold*），这段对话的所有浏览器动作都会等着；智能体最多等十分钟你点「完成」，然后就着它看到的继续，并说明你没有回来。聊天、实时舞台、胶囊和浏览器查看器显示的都是同一张*轮到你了 · <reason> · 完成*卡片。走 API 的话：`POST /api/browser/{thread}/control` 带 `take_over` / `handed_back`，或者 `POST /api/holds` 和 `POST /api/holds/{id}/done`；`GET /api/state` 列出所有未结束的 hold。

密码直接进网站，从不经过模型：模型看到的是你完成之后的那一帧。智能体只会用文字（`ask_user`）问它需要知道的事（哪个账号、哪个日期），从不问密码或验证码。

cookie 会保留。服务器上的 Playwright profile 是一个真正的 Chromium 配置目录；手机上的 WebView cookie 存储在每次导航和 `fetch` 之后都刷到磁盘。会话 cookie（那种没有过期时间、浏览器一关就丢掉的）在两边都挺不过服务器重启，所以只用这种 cookie 的网站在 `nanomuse serve` 重启之后会再问一次；大多数网站在你勾上「记住我」之后会设一个更长效的 cookie。

### 哪些不行，为什么 {#what-does-not-work-and-why}

- **Google 账号没法在 WebView 里登录。** Google 拒绝嵌入式登录（`disallowed_useragent`），理由也站得住。接管面板上有一个箭头，可以把同一个 URL 在系统浏览器里打开，但在那里完成的登录留在 Chrome 里，不在 nanoMuse 的 WebView 里。Google 的服务请走 API 这条路（日历的私密 `.ics` 链接、邮箱的应用专用密码），别用浏览器；在服务器的 Chromium 上，Google 登录能成，但可能被判为「不安全」而受到盘问。
- **二维码没法用同一部手机扫。** 靠「用我们的 App 扫码」登录的网站（微信、支付宝、淘宝……）把二维码显示在本该举着摄像头的地方。在手机的浏览器上这是条死路；在服务器的 Chromium 上，你用手机扫聊天里的那一帧就行；这是服务器浏览器反而更省事的唯一一种情况。
- **通行密钥（passkey）带不走。** 在手机 Chrome 里创建的通行密钥属于那个浏览器的凭据存储；WebView 看不到它，服务器上的无头 Chromium 更是一个都没有。密码加验证码的登录到哪里都行。
- **下载**落在工作区里：服务器上（Playwright）是 `<workspace>/downloads/`，手机的本地版上也是（智能体能读到）；在连接版里，智能体在电脑上，下载会进手机的「下载」文件夹。
- 只有一个标签页。要开新窗口的链接改为在同一个页面里打开。

## 手机的浏览器是怎么工作的 {#how-the-phone-s-browser-works}

WebView 必须以为自己在屏幕上：一个隐藏的 WebView 会把 `requestAnimationFrame` 节流到零、把定时器降到每秒一次，很多页面永远加载不完。所以 App 给它一块屏幕：一个私有的**虚拟显示器**（一个 `ImageReader` 表面，谁也看不见），上面放一个 `Presentation` 窗口，窗口里装着 WebView。不管 App 在不在屏幕上，Chromium 都以全速往那个表面上合成帧；`screenshot` 返回的就是最新一帧，所以视频、canvas 和 WebGL 出来的都是真实状态。在模拟器上、App 在后台时实测：每秒 60 次 rAF，`setInterval(10 ms)` 每秒 100 次，`visibilityState = visible`。在不给创建虚拟显示器的设备上，WebView 退回到手动测量、手动绘制。

点按以触摸事件的形式注入到元素中心，打字走页面自己的 setter 再加 `input` / `change` 事件（框架才察觉得到），回车就是按键。那一个页面是单例；接管时把同一个 `WebView` 对象挪进面板的容器再挪回来，所以什么都不重新加载。cookie 包括第三方 cookie 都开着；每次加载和 `fetch` 之后都跑 `CookieManager.flush()`。

### 协议 {#the-protocol}

手机的 socket 一打开就宣告 `{"kind": "device", …, "browser": true}`；之后服务器发 `op: "browser"` 的 `device_request` 消息，回答以同一个 `id` 的 `device_result` 回来。这些 op 来自 `nanomuse/tools/browser_backends.py`（`DeviceBackend`），实现在 `android/…/browser/DeviceBrowser.kt`：

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

未知的 op 或者一次失败，以 `{"ok": false, "error": "…"}` 返回，一条模型读得懂的消息。另一个想把自己的浏览器借给 nanoMuse 服务器的 App，实现这十四个 op 和那条 hello 就行。

## 怎么测 {#testing-it}

`tests/test_browser.py` 把工具跑在一个假后端上（两个后端的一致性、帧、接管后的交还），在装了 Playwright 和 Chromium 时也跑在真后端上（持久 profile、跨重启的 cookie、带会话的 `fetch`、profile 切换）。手机那边在 Android 13 模拟器上端到端跑过一遍：上面的每个 op、页面设下的 cookie 出现在 `fetch` 里、打字落进正确的输入框、接管面板显示的是同一个实时页面、交还到达服务器。还等着真机验证的：厂商的电池管理暂停 App 进程，以及 Android 8–10 上的虚拟显示器。
