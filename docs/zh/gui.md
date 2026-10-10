# 操作手机

> **Python 线路的设计记录。** 当前 Android 应用的手（`io.github.nanomuse.hands`，0.1.12 起）
> 沿用的就是这套设计（阶梯、带「停止」的胶囊、审批），只是智能体直接跑在手机上
> （[android.md](android.md)）。本页写「小熊猫」的地方，胶囊里显示的是智能体自己的脸
> （默认是那只小龙）。


Muse 在西方的能力来自带 API 的服务。而中国人在手机上做的大多数事（12306、微信、支付宝、美团）都没有一个个人智能体可以调用的 API。所以 nanoMuse 多了第二双手：打开「手机」开关后，智能体可以看手机的屏幕，在各个 App 里点、输入、滑动，像人一样操作。它还是同一个智能体，前面挡着的还是同一个哨兵（Sentinel）；屏幕上的每一步只是多出来的工具调用。

这部分怎么做，由三件事决定：

- **本地。** 大脑跑在你让它跑的地方（你的机器，或者在 Android 版里就是手机本身），屏幕只发给你配置的那个模型，不给别人。
- **中国优先。** 默认模型在中国大陆用阿里云百炼，其他地方用 OpenRouter（`qwen/qwen3.8-27b`）；示例任务是 12306 和微信；敏感词表以中文为先。
- **任何 App。** 操作器把屏幕当一张图来看，按位置点。它不需要无障碍树、带标签的按钮或者针对某个 App 的接入，所以多一个 App 不花任何成本：订火车票的那套循环同样能读一段聊天。设备*有*树的时候（Android 应用），树会作为第二路输入一并送上（小字变得可读，密码框能被认出来），但没有任何环节依赖它。
- **最后手段。** 屏幕是阶梯的第四级（见下）：先是能把事情做准确的技能、命令行工具或 MCP 服务器，然后是用你的登录态抓取页面，再然后是内置浏览器。屏幕上每一步都是一次模型调用加一张图；只有下一级做不到时智能体才往上爬，而且开始之前会先说一声。

默认关闭。你打开之前，手机上的任何东西都到不了模型那里。

## 阶梯 {#the-ladder}

够到一个服务有四条路，从最低的一级开始试：

| 级 | 怎么做 | 什么时候 |
|---|---|---|
| 1 | **技能**、**CLI** 或 **MCP 服务器**：`feishu` 走 lark-cli，`amap` 走它的 MCP 服务器，还有邮件、日历、文件 | 只要有就用：准确、即时、不碰屏幕 |
| 2 | **带你登录态的抓取**：`browser` action=fetch、`web_fetch` | 登录之后就能直接看到答案的页面 |
| 3 | **内置浏览器**，一页一页来 | 需要一路点下去、但终究是个网站的东西 |
| 4 | **手机屏幕**：`phone_task` | 只住在 App 里、别处没有的东西：一段微信聊天、12306 的真实余票、美团里的一笔订单、一次付款 |

技能在 front matter 里用 `channel:` 说明自己在哪一级工作：`api`、`cli`、`web`、`browser`、`gui` 或 `mixed`（`app-only` 和 `phone` 也接受，等同于 `gui`）。`gui` 技能在智能体的技能索引里显示为 *[on the phone's screen]*，这样智能体一看就知道这是第四级的活；`train-tickets` 和 `phone-messages` 是内置的例子。在屏幕上走第一步之前，智能体会用一句话说明它要在手机上做什么；如果不是你自己要求用手机（它是因为下面几级失败才往上爬的），它会先问你。「活动」视图会统计一次会话里有多少步是在屏幕上做的，你能看到阶梯有没有被守住。

## 看起来是什么样 {#what-it-looks-like}

问一句「帮我看看明天北京到上海最早的高铁」，智能体就在手机上打开 12306，设好车站和日期，按「查询车票」，筛选「只看高铁」，再把列表读给你。让它在微信上回复某个人，它会打开那段聊天，输入文字，然后**停在发送按钮前，等你批准**。要是一件事横跨两个世界（网上查资料、12306 里订票、日历里建日程），它会一边做一边在原生工具和屏幕之间来回切换。

聊天里每个屏幕步骤都显示为一行，比如 `phone_act: tap "发送" at (318,742) in 微信 (wechat)`，你能看到它做了什么；手机上有一圈涟漪标出手指的落点，还有一行字幕说明 Muse 正在做什么（见[显示手指](#showing-the-finger)）。事后 `nanomuse phone traces` 列出每个任务，`nanomuse phone trace <id> -o trace.html` 把其中一个渲染成网页，每一屏和每一次点击都画在上面。

## 打开 {#turning-it-on}

在应用里：「连接 → 手机」，拨开开关。在 `config.toml` 里：

```toml
[gui]
enabled = true
```

或者 `NANOMUSE_GUI_ENABLED=1`。开关打开后，智能体多出三个工具（见下文），系统提示词里多出一段关于已连接手机的话。关掉时，这些工具不存在。

### 动手指的那个模型 {#the-model-that-moves-the-finger}

每一步都读一次屏幕，意味着很多次带图的小调用，所以操作器可以用自己的模型，和主模型分开：

```toml
[gui]
enabled  = true
provider = "openai"                                   # or openai_responses
model    = "qwen3.8-27b"                              # must take images; a fast one that reads well is enough
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key  = "{{vault:GUI_API_KEY}}"
```

聊天模型和手的模型是两个设置：手机和桌面版是 设置 → 模型 里的「操作屏幕」一行，网页控制台是「连接」页的「手的模型」下拉，这里是 `[gui] model`。留空（也就是那一行的「自动」）时，手按一个顺序走：

- 对话模型所在的服务商，只要它是你自己的 key、而且目录里给它在同一个端点上指定了手的模型（阿里云百炼 `qwen3.8-27b`，OpenRouter `qwen/qwen3.8-27b`）；已知看不见图的模型（不含 `v4.1`、`vision` 或 `ocr` 的 DeepSeek id）从不会被列为手的模型；
- 否则，有 nanoMuse Cloud 账号时用中继的手的模型：除非中继另有指定，否则是 `qwen3.8-27b`（`/v1/models` 会说明哪些模型 `for` `chat`、`gui` 或两者皆可）；那边的聊天默认模型是 `deepseek-v4.1-flash`，它也能看图，但手需要的是专门训练过、会在屏幕上指位置的模型，所以两者分开；
- 否则就用聊天模型本身，前提是它能看图（手机和桌面版在这之前还会先试你第一把带能看图模型的 key）。

你在那一行做过的选择永远优先，那一行也写着「自动」现在给的是什么。你自己的手的模型失败时什么都不会自动切换；卡片上给「这次改用 nanoMuse Cloud」，只管这一轮（[own-key.md](own-key.md#which-model-does-what)）。

key 和其他 key 一样放进保险库（`nanomuse vault set GUI_API_KEY`，或者直接在「手机」卡片里输入）。操作器的模型**必须接受图片**：一张截图就是全部的观察。操作器以温度 0 调用它：定位要的是模型的第一选择，不是采样。

环境变量覆盖：`NANOMUSE_GUI_ENABLED`、`NANOMUSE_GUI_PROVIDER`、`NANOMUSE_GUI_MODEL`、`NANOMUSE_GUI_BASE_URL`、`NANOMUSE_GUI_API_KEY`。

其他设置：`max_steps`（默认 0 = 不设上限；设一个数可以限制单次 `phone_task` 的步数）、`device_timeout_s`（默认 20，等手机回应一次请求的时长）、`sensitive_words`（下面那张词表）。

## 连接手机 {#connecting-a-phone}

智能体不一定要跑在手机上。一台*设备*通过应用用的同一条 WebSocket 连到 nanoMuse 服务器，报上自己，然后回应屏幕请求和动作请求。目前有两种设备：

- **MobileGym**：[mobilegym.dev](https://mobilegym.dev/) 上的模拟手机，里面的中国 App（微信、支付宝、铁路12306、地图、小红书……）是浏览器里的 React 应用。它的 nanoMuse 模块（`demo/mobilegym/`）在设置页上有「允许 nanoMuse 操作这台手机」开关。这是展示站用的环境：不会碰到任何真实的东西。
- **Android**：nanoMuse 应用，通过它自己的无障碍服务：`takeScreenshot()` 取图，`dispatchGesture()` 动手指，无障碍树给元素列表，`performGlobalAction` 做返回 / 主屏 / 最近任务，`open_app` 用应用自己维护的可启动 App 列表。同一套协议，真实的 App。需要 **Android 11 或更新**（从这个版本起无障碍服务才能截图），并且把服务打开：

  1. 「连接 → 手机 → 这台手机 → 打开无障碍设置」，在「已下载的应用」下找到 **nanoMuse** 并打开。Android 会说明这个服务能做什么（查看屏幕、执行手势），并要你确认。
  2. Android 13 及更新版本上，从下载（而不是应用商店）安装的应用，开关会变灰并显示「受限设置」。打开应用在设置里的页面（同一张卡片上的「应用设置」），点 ⋮ → **允许受限设置**，再回到第 1 步。
  3. Android 时不时会自己把无障碍服务关掉：更新之后、激进的电池清理之后、有些手机重启之后。「手机」卡片实时显示「就绪」/「还没有」；手机不回应时先看这里。服务一开一关，应用立刻把变化报告给服务器，所以「连接 → 手机」不会过时。

  这个服务自己不做任何事：只在 `phone_*` 工具要屏幕时才取一次屏幕，而且每个任务都会在屏幕顶部显示一个胶囊：小熊猫、正在进行的步骤和一个**停止**按钮（见下文）。

「连接 → 手机」显示连着哪台设备、它列出了多少个 App。`GET /api/phone` 返回同样的内容，外加最后一次读到的屏幕。

## 工具 {#the-tools}

| 工具 | 风险 | 做什么 |
|---|---|---|
| `phone_screen` | SAFE，读取隐私数据 | 当前屏幕：一张给模型看的截图，带一行说明：`铁路12306 (railway12306) · /station-select · 360×800 · keyboard hidden` |
| `phone_act` | MODERATE，或 SENSITIVE（见下文） | 按位置做一个动作：`tap`、`long_press`、`double_tap` 带 `x`/`y` 和 `label`；`swipe` 到 `x2`/`y2` 或按 `direction`；`type`、`enter`、`back`、`home`、`recents`、`open_app`、`wait`。返回动作之后的屏幕 |
| `phone_task` | 取决于它的各步 | 把一个目标交给*手机操作器*：一个用自己模型的循环，看、做、再看，直到目标达成、需要你，或者放弃。它的每一步都是一次 `phone_act`，和其他调用一样经过哨兵 |

**屏幕是最后一级。** 搜索、网页、邮件、日历、文件、连接器：只要其中一个能即时、准确地给出答案，智能体就用它；手机留给只有你自己的 App 和账号才能做的事：12306 的真实余票和价格、一段微信聊天、美团里的一笔订单、需要你账号的一次付款。手机比工具慢，每一步都是一次模型调用，所以智能体不会为了知道北京离上海多远而打开 12306（见[阶梯](#the-ladder)）。

主智能体把超过一两步的事交给 `phone_task`（「打开 12306，找明天北京到上海最早的车，报前三趟」），想自己看一眼或做一件事时用 `phone_screen` / `phone_act`。两种用法都可以；操作器让主模型的上下文保持小巧。

## 操作器 {#the-operator}

`phone_task(goal, app?, max_steps?)` 跑一个内层循环，移植自 [MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench)（MIT）里的 `mobile_use` 操作器：

1. **看。** 取屏幕。操作器的模型拿到一张图（当前屏幕），加上目标和它到目前为止做过的事，早先的每一步是一句话（`Step 3: 点击「查询车站」按钮。; Result: …`）。设备送了元素列表时，列表里最多 60 行跟在后面，输入框排在前面，每行有它的文字、类型、标志和中心点，中心点用的是模型作答时同一套 999 网格（`- "密码" · EditText [editable, password] @ 500,375`）：这是读小字和瞄准用的第二路输入，从来不是第一路。
2. **决定。** 模型按固定格式回答：一行 `Thought:`，一句用你的语言写的 `Action:`，以及一个调用 `mobile_use` 的 `<tool_call>`，动作是 `click`、`long_press`、`swipe`、`type`、`open`、`system_button`（Back、Home、Menu、Enter）、`wait`、`answer`、`ask_user` 或 `terminate`。坐标按 999×999 的网格返回，再换算成手机的像素。格式不对的回答会连同一句提醒退回去一次，最多三次。
3. **做。** 这一步变成一次 `phone_act`，把 Action 那句话当作 `label`：哨兵读的是这句话，审批卡片显示的是这句话，轨迹里留下的也是这句话。然后回到第 1 步。

它以 `done` 结束，附带模型的 `answer`（从屏幕上读到的文字放在这里）；模型调用 `ask_user` 或哨兵需要一个决定时以 `ask` 结束（主智能体问你，再拿你的回答继续）；两次被拒之后是 `blocked`；你在手机上按下**停止**是 `stopped`；`terminate(failure)`、超过 `max_steps` 或手机不再回应时是 `failed`。同一个动作连续三次会在历史里记一笔，好让模型换个法子。

在带胶囊的设备上，操作器还会告诉手机任务什么时候**开始**（胶囊带着目标出现）、什么时候**结束**（胶囊消失）、什么时候**需要你**：一次 `ask` 或 `blocked` 会在手机上变成一张卡片，上面是问题和一个进入聊天的「打开」按钮，因为你那一刻看着的是微信，不是 nanoMuse。

操作器自己的规则写在它的提示词里：绝不输入密码、PIN、卡号或验证码（先 `ask_user`）；绝不确认一笔没有被明确要求的付款或转账；只做查询要求的事，查询是「查一下」的时候，读完就 `answer`，不再多按。

## 哨兵怎么处理它 {#what-sentinel-does-with-it}

从屏幕上读到的一切都是隐私数据：第一次 `phone_screen` 之后这段对话就带上了隐私标记（tainted），之后把数据发到别处的步骤按更严的规则处理（见 [sentinel.md](sentinel.md)）。

一次 `phone_act` 是 MODERATE（默认模式下可以自行执行），除非它看起来像是在做出某种承诺，这时它是带警告的 SENSITIVE，而警告永远意味着**问一次**：

- `tap`、`long_press`、`double_tap` 或 `enter` 的 `label` 里含有 `sensitive_words` 中的一个：确认支付、立即付款、转账、提交订单、立即购买、发送、删除、注销、pay now、place order、send、delete……（App 的名字除外：点支付宝的图标不算付款步骤）
- 带 `submit` 的 `type`，输入和提交合在一步，操作器从不这么做：它先输入，下一步再点发送按钮，这样那一步可以连同输入框里的文字一起被检查

一个带坐标的动作**必须**带 `label`：手指下面的字，按屏幕上显示的原样；操作器填的是它的 Action 句子。没有 label 的点击照样执行，但带一条警告（「没有任何信息说明手指下面是什么」）；屏幕之外的点在到达手机之前就被拒绝。

默认词表是中英文；其他 App 或语言请编辑 `[gui] sensitive_words`。这里批准的审批只算*一次*：发一条消息永远不会变成不问就发下一条。

在电脑上还多一道询问，按应用计：一次对话里在某个应用中的第一次 `computer_act` 会问「让 <Muse> 使用 <App>？」，可选一次 / 本次对话 / 总是，记为一条 `computer_app:<id>` 授权（设置 → 权限）。上面按动作的规则在应用内部照样适用。macOS 上手可以只在那个应用的窗口里工作：[every-device.md](every-device.md#window-mode-macos)。

### 把屏幕交给你 {#handing-the-screen-over}

密码、验证码、人机验证和付款确认由人来输入。操作器的 `hand_over` 动作（以及 `computer_act` / `phone_act` / `browser` → `hand_over`，带一个 `reason`）会在聊天里（桌面版上是在这次运行的轨迹卡片上）和胶囊上放一张「轮到你了：<reason>」卡片，带一个**完成**按钮，最多等十分钟。等待（hold）期间，那个线程里这个工具的每个动作都等着；人做完自己的部分，按**完成**；操作器重新截一张图，并被告知「用户接管了一会儿；再看一眼」。焦点落在密码框上时，`type` 会自动变成一次交接。人也可以先接管：「手」卡片或浏览器卡片上的「接管」，或者 `POST /api/holds {"thread","tool","reason"}`；`POST /api/holds/{id}/done` 结束它，`GET /api/state` 列出还没结束的等待。

因为观察是一张图，哨兵依据的是 *label*（模型自己对它将要按什么的描述），而不是从某棵树里找到的文字。这对操作器所知道的东西是诚实的；也正因为如此，label 是必填的，付款步骤还另外有操作器自己停下来问的规则，授权也只算一次。

## 轨迹 {#traces}

每次 `phone_task` 在 `<data_dir>/phone-traces/pt-<timestamp>-<id>.jsonl` 下写一份 JSONL 轨迹：一条 `task` 记录（目标、App、上下文），每次迭代一条 `step` 记录（屏幕上的 App 和路由、截图路径、模型的想法和 Action 句子、工具调用、实际发给设备的动作、延迟、错误如果有的话），以及一条 `end` 记录（状态、消息、步数、秒数）。保留最近 200 份轨迹和最近 400 张截图。

```
nanomuse phone traces                    # newest first: id, when, status, steps, goal
nanomuse phone trace pt-20260923-230710-5be7
nanomuse phone trace pt-20260923-230710-5be7 -o trace.html
```

这个 HTML 页面是自包含的（每张截图都内嵌，点击画成一个圆环、滑动画成一条线，就画在模型当时看到的那一屏上），所以一次运行可以当作一个文件传来传去，或者附在 issue 里。

## 设备协议 {#the-device-protocol}

写给想另写一个执行器的人。消息走应用的 WebSocket（`/ws`，token 放在第一帧）。

设备报到一次：

```json
{"kind": "device", "name": "MobileGym", "platform": "mobilegym", "gui": true, "capsule": true,
 "apps": [{"id": "wechat", "name": "微信"}, {"id": "railway12306", "name": "铁路12306"}],
 "screen": {"width": 720, "height": 1600}}
```

然后收到 `{"kind": "device_ack", "phone": {…}}`。有变化时设备可以在同一条连接上再报一次（Android 应用在无障碍服务开关变化时会这么做；`gui` 随之翻转）；服务器保留这条连接的到达时间，更新其余部分。`"capsule": true` 表示设备会显示一个带停止按钮的步骤胶囊，并且想收到下面的 `task` 请求。随后服务器一次一个地发请求：

```json
{"kind": "device_request", "id": "r1", "op": "screen", "params": {}}
{"kind": "device_request", "id": "r2", "op": "act", "params": {"action": "tap", "x": 68.5, "y": 447.6, "label": "点击热门车站中的「北京」。"}}
```

设备回答 `{"kind": "device_result", "id": "r1", "ok": true, "result": …}` 或 `{"kind": "device_result", "id": "r1", "ok": false, "error": "…"}`。

`screen` 的结果是一张图加几条关于它的事实：

```json
{"app": "railway12306", "app_name": "铁路12306", "route": "/station-select",
 "width": 360, "height": 800, "keyboard": false,
 "screenshot": "<base64 PNG or JPEG>", "note": "optional"}
```

`screenshot` 是整个屏幕，`width` × `height` 像素，和设备执行点击用的是同一个空间，所以图上的一个点就是屏幕上的一个点，不需要换算；设备完全不发尺寸时，服务器从图上读。（`image` 作为同一个字段的旧名字也接受。）模型读这张图，坐标是图里的像素，原点在左上角。`app`、`app_name`、`route` 和 `keyboard` 可选，但有了它们，说明文字、哨兵的摘要和轨迹都会更好。

有无障碍树的设备（或者像 MobileGym 模块那样有 DOM）可以加上 `nodes`，即那些有文字或能做事的元素，摊平，最多 120 个，用图片的像素空间：

```json
{"nodes": [
  {"id": "0.3.1", "class": "Button", "text": "查询车票", "cx": 180, "cy": 612, "box": [24, 588, 336, 636], "clickable": true},
  {"id": "0.2.0", "class": "EditText", "hint": "密码", "cx": 180, "cy": 400, "editable": true, "password": true}
]}
```

`id` 是进入树的稳定索引路径，`text` / `desc` / `hint` 是元素的文字，`res` 是它的资源 id；标志有 `clickable`、`long_clickable`、`editable`、`password`、`checked`、`scrollable`、`focused`、`selected`、`disabled`。服务器保留前 120 个，给操作器看最有用的 60 个（输入框在前），而且从不强制要求这个列表：WebView、Flutter 应用、游戏或 `FLAG_SECURE` 屏幕都没有，没有它循环也一样。Android 应用在发送前把截图缩到 720 px 宽，收到的坐标再按比例放大回去，所以模型看到的空间就是它点击的空间。

`act` 的结果是 `{"note": "…", "screen": {…}}`：动作稳定下来之后屏幕的样子，所以一步只要一个来回。

设备必须处理的动作：

| 动作 | 参数 |
|---|---|
| `tap`、`double_tap` | `x`、`y` |
| `long_press` | `x`、`y`、`seconds`（≤ 5） |
| `swipe` | `x`、`y`、`x2`、`y2`；或者 `direction` up/down/left/right 加 `distance`（占屏幕的比例）和可选的起点 |
| `type` | `text`、`clear`（先清空输入框）、`submit`（之后按回车）；知道的话加上输入框的 `x`、`y` |
| `enter`、`back`、`home`、`recents` | — |
| `open_app` | `app`：报到列表里的一个 id 或名字 |
| `wait` | `seconds`（≤ 10） |

每个带坐标的动作还带 `label`：执行器应当把它显示出来（见下文），也可以记日志；除此之外不需要拿它做别的。

报到时带了 `"capsule": true` 的设备还会收到 `task` 请求（`{"op": "task", "params": {"event": "begin", "text": "<goal>"}}`、`"end"`，以及带着智能体要问用户的那个问题的 `"notice"`），用一个空的 `ok` 回答它们；它们是尽力而为的，3 秒内不回答的设备不会被等。不管任务怎么结束（完成、停止、设备离线、模型失败、聊天运行被取消），`end`（或 `notice`）都会发出，但恰好在那一刻断开的 socket 永远收不到。所以服务器还把进行中的任务放在手机状态里（每条 socket 的 `hello` 里都有 `"phone": {…, "task": {"goal": "…", "since": <unix seconds>}}`，没有任务时为 `null`），设备（重新）连接时应当据此设置胶囊：还在进行的任务拿回它的胶囊，中途结束的任务把胶囊收起来。socket 彻底关闭时，或者一个号称在进行的任务很久没有向设备要任何东西时（MobileGym 模块用三分钟），胶囊也应当自己收起来。

**停止。** 用户在设备上按下停止时，设备让正在进行的请求失败（以及之后直到下一次 `task begin` 为止的每一个请求），错误里带上标记 `nanomuse:stop`。服务器把它变成 `stopped` 结果：操作器结束循环，`phone_act` 用平实的话报告，主智能体被告知不要继续操作手机，而是问接下来做什么。没有胶囊的设备永远不需要发这个标记。

MobileGym 执行器（`demo/mobilegym/apps/nanoMuse/gui.ts`）是一个可读的例子：它在页面里把模拟器的 DOM 渲染成 PNG（`modern-screenshot`，抵消掉手机的 CSS 变换、去掉舞台），尺寸是手机的两倍（720×1600，这样模型读得清小字，点击再按比例缩回手机），遍历 DOM 得到 `nodes`（可交互或有文字、可见、没被遮住的元素；类型从标签和 role 猜），从模拟器的 OS 对象读 App 和路由，并驱动 MobileGym 自己的输入 API 来执行动作，让一次点击落下去就像手指一样。它和 Android 执行器一样拒绝往密码框或验证码框里 `type`：胶囊会请人自己填好，再点「继续」。

## 显示手指 {#showing-the-finger}

一个一声不响地动的执行器，看着让人不安，也没法跟上。设备应当在手机自己的坐标空间里画出 Muse 在做什么，画在一个**不进截图**的图层上（模型不能看到这些标记）。MobileGym 模块是参考实现；Android 应用按同一套规范实现，用了两个无障碍悬浮窗（一个不可触碰的全屏层画标记，另一个是胶囊），截图的那一瞬间两个都隐藏。

| 什么 | 怎么显示 | 时长 |
|---|---|---|
| `tap`、`double_tap` | 一个从落点扩散、再淡出的圆环 | 520 ms |
| `long_press` | 一个保持住、再淡出的圆环 | `seconds`，然后 300 ms 淡出 |
| `swipe` | 从起点画到终点的一条线，终点有一个圆环 | 滑动本身的时长（320 ms），然后淡出 |
| `type` | 字符一个一个出现 | 每个字符 40 ms |
| 每个动作 | 底部一行字幕：`Muse · <label>`（或 `输入 “…”`、`打开 <app>`、`滑动 up`） | 2.6 s，被下一条替换 |

动作之后，执行器等 UI 稳定下来（MobileGym 上 650 ms；Android 上等到无障碍事件安静 450 ms，最多 3 s）再取要返回的屏幕。这段等待是动作的一部分，所以 `screen` 读到的永远不会是切换到一半的画面。

### 胶囊 {#the-capsule}

在带胶囊的设备上（Android 应用，以及在模拟手机里画同一个胶囊的 MobileGym 模块），任务从来不是无声的：屏幕顶部有一个胶囊，显示小熊猫、正在进行的步骤（*Muse · 点击「查询车票」*）和一个**停止**按钮，盖在正被操作的 App 上面。它在 `task begin` 时出现，跟着每一步走，在 `task end` 时消失：先打一个勾停留片刻，然后手机回到 nanoMuse，那里有智能体的报告（Android 应用把自己拉到前台；MobileGym 模块恢复 nanoMuse 应用）；它不在截图里。停止是用户的刹车；不用长按、没有菜单：点一下，进行中的动作以 `nanomuse:stop` 失败，胶囊显示「已停止」并隐藏自己，手机回到 nanoMuse，智能体不再继续，而是问接下来做什么。智能体需要用户时（`ask`、`blocked`），胶囊长成一张卡片，上面是问题和一个把 nanoMuse 拉到前台的「打开」按钮；停留一分钟，然后收起。

### 桌面上也一样 {#the-same-on-the-desktop}

桌面版用手机那套词汇画手，只是按指针的尺度缩放（[desktop-muse.md](desktop-muse.md#computer-use)）：沿显示器边缘呼吸的光晕（蓝色是在干活，琥珀色是在等），操作器动过的那个点上的标记（圆环、转动的青色弧、圆点、胶囊里的动作名），拖动是一条带箭头的虚线，屏幕顶部一个胶囊，有脸、*第 N 步*、这一步的话、「我来接手」和「停止」，在 nanoMuse 窗口不在前台时显示。那里没有任何东西流动或扫过；每一处光都以 2.4 s 亮起、2.4 s 暗下的节奏呼吸，在「减弱动态效果」下保持静止。

**轨迹。** 手机把手指的动作当场显示出来，桌面版还把这次运行留下来可以回看：聊天里，在这次运行最后一次手的调用下面，显示每一步的截图，动作画在上面（点击标记、拖动箭头、滚动的 V 形、标签胶囊里输入的文字或按键组合），还有智能体在这一步之前说的话；可以上一步 / 下一步、用方向键、「放大查看」和「复制这一步」。它完全由手本来就返回的东西拼成：`computer_screen` / `computer_act` / `device_screen` 给出图片，图片的第一行给出标题和尺寸；`computer_act` 的参数给出动作，包括拖动的 `x2`/`y2`（或 `box2`）和滚动的 `dy`。所以工具、MCP 结果和 hub 帧都没有为它增加任何东西。宿主在内存里保留**每次运行 40 步、4 次运行、64 MB 图片**，通过 `GET /nanomuse/cloud/trajectory?session=<id>` 和 `GET /nanomuse/cloud/stage/frame?seq=N` 提供给窗口；格式和上限见 [desktop-muse.md](desktop-muse.md#computer-use)。

## 电脑上的手：以图为单位 {#hands-on-the-computer-the-picture-is-the-unit}

电脑的手（`computer_screen` / `computer_act`，[every-device.md](every-device.md#hands-on-this-computer)）遵守和手机一样的规则，只是多一步，因为电脑的图和它的指针很少是同一个尺寸：一块 4K 显示器在 X11 和鼠标看来是 3840×2160，在 Electron 看来是 1920×1080 的「逻辑」尺寸，而模型看到的图是 1596×896。0.1.36 之前这几个空间混在一起（告诉模型的是屏幕尺寸，给它看的是更小的图，它报的数字直接拿去点），Linux 上点击落在目标旁边就是这个原因。

现在**以图为单位**。`computer_screen` 在第一行说明图的尺寸（`<window in front> · 1596×896 · …`），结尾是 *Coordinates: pixels of this 1596×896 picture, (0,0) top-left.*；`computer_act` 接受这张图里的 `x`、`y`（或者一个 `box` `[x1, y1, x2, y2]`，取其中心），`drag` 的 `x2`、`y2` / `box2` 同理。运行时把手自己的空间（操作器的屏幕像素）和图分开，只在动作之前换算一次，再为轨迹和光晕换算一次（`nanomuse/computer/coords.py`，`Mapping`）。图是屏幕按 `[hands] max_image_width` 封顶，再对齐到 Qwen3-VL 缩放用的 28 像素网格（UI-TARS 的 `smart_resize`），这样模型自己的缩放就是恒等变换，它说出的像素就是它看到的像素。`[hands] coords = "norm1000"` 则把 `x`、`y` 变成图上 0–1000 的网格，给按那种方式训练的手的模型用。

手的空间从哪里来，按后端分：

| 后端 | 手的空间 | 说明 |
|---|---|---|
| `desktop`（桌面版） | 显示器的逻辑尺寸 × 缩放系数；macOS 上缩放系数为 1（点） | 应用自己的操作器（`@computer-use/nut-js`，移植自 UI-TARS-desktop 的），走本机回环 HTTP；只要应用设置了 `NANOMUSE_OPERATOR_URL`，`auto` 就选它 |
| `pyautogui` | `pyautogui.size()` | macOS 上是点，其他平台是物理像素；在桌面版下的 Mac 上不用 |
| `xdotool` | `xdotool getdisplaygeometry` | X11 根窗口像素 |

在桌面版下的 macOS 上**只有一条路**：每张截图、每次移动都由操作器来做，否则工具带着操作器给的原因失败；没有录屏权限时，那句话是「macOS：在系统设置 → 隐私与安全性 → 录屏 里打开 nanoMuse Desktop，然后退出并重新打开应用。」（操作器检测到拒绝和全黑的截图，回答 `403`）。运行时在那里从不回退到 `mss` / `screencapture` 或 `pyautogui`：权限属于应用包，回退会让 TCC 为一个不在面板里的进程再问一次，而一张黑图会被当成屏幕送到模型那里。Linux 和 Windows 保留 Python 回退，不经应用启动的运行时也保留（[desktop.md](desktop.md#macos-permissions)）。

从 0.1.38 起，Mac 上的操作器把截图和输入交给 **nanoMuse Computer Use**，桌面包里的一个小 Swift 应用，两项授权都由它自己持有（截图用 ScreenCaptureKit，macOS 14 及更新版本上是主显示器的 `SCScreenshotManager`，12 和 13 上是 `CGDisplayCreateImage`；鼠标和键盘用 `CGEvent`，任何文字的字符都直接输入）。macOS 把权限归到 LaunchServices 启动的那个进程上，所以通过 `open` 启动的辅助程序在录屏和辅助功能面板里有自己的一行（要打开的是「nanoMuse Computer Use」，不是应用本身），录屏授权要等应用重启那一个进程后才生效，这一步应用会自己做。上面说的操作器契约不变：同样的路由、同样的坐标（点）、缺少授权时同样的 `403`，只是那句话现在点名的是辅助程序。辅助程序取图失败时（ScreenCaptureKit 拒绝、没有图像、辅助程序死掉或根本没启动），操作器**不会**改用一帧 `desktopCapturer` 顶上：`/screenshot` 带着辅助程序自己的话失败（「没有截图：nanoMuse Computer Use 拍不到图，ScreenCaptureKit userDeclined (-3801)：……」，或「……没有启动（……）」），日志写 `helper screenshot failed (…) — not falling back to desktopCapturer`，`computer_screen` 把这句话带进聊天。`desktopCapturer` 和 nut.js 只在没有辅助程序包的构建里仍是那条路（[desktop.md](desktop.md#macos-permissions)）。

**macOS 上的窗口模式**（[every-device.md](every-device.md#window-mode-macos)）走同一个辅助程序：运行时向操作器要屏幕上的窗口（`GET /windows`：id、进程、应用、bundle id、标题、以点为单位的位置和尺寸），以及某一个窗口自己的像素（`POST /window {id}`：`SCContentFilter(desktopIndependentWindow:)`，不带阴影、不带光标，连同窗口位置一起返回，这样图上的一个像素能对应到屏幕上的一个点）。在应用下的 Mac 上，运行时从不自己截取窗口；窗口模式的鼠标和键盘事件仍由运行时发给窗口所属的进程（`CGEventPostToPid`），这就是为什么辅助功能面板里除了辅助程序那一行，还需要「nanoMuse」那一行。拒绝（辅助程序的录屏那一行没开，`403`）或窗口已不在（`404`）都以操作器的话返回，下一次看屏幕时重试；辅助程序根本不存在时，手对这个目标退回到整个屏幕，原因写进观察里。没有辅助程序包时，运行时保留自己的 `CGWindowListCreateImage` 路径，并在日志里说明（`window mode: the runtime captures windows itself …`）。

Linux 上操作器只在 **X11**（Xorg）下工作。手的空间是以像素计的 X 根窗口（HiDPI 桌面上那是逻辑尺寸 × 缩放系数，1920×1080、缩放 2 的显示器就是 3840×2160），`/info` 会这么说；图就是这个根窗口，按上面的方式为模型缩放。**Wayland** 下没有程序可以驱动的全局屏幕或光标，所以 `/info` 说手是关着的（「Wayland 会话：……请用 Xorg 登录……」），`/screenshot` 用同一句话拒绝（`503`）而不是打开门户的选择器，运行时在第一次尝试时就直说：它不会落到 `xdotool` 或 `pyautogui` 上，那两个会在 XWayland 下启动，然后什么你能看到的东西都动不了。会话类型从 `XDG_SESSION_TYPE` 读，或者从一个没有 `DISPLAY` 的 `WAYLAND_DISPLAY` 判断。0.1.38 在 X11 路径上修了两件事：光晕（手干活时应用沿屏幕画的那个框）也是一个 X 窗口，而 X11 每次映射或重新配置它时都会忘掉它的点击穿透形状，所以点进去的每一下都落了空：现在操作器会等光晕可以穿透之后再移动指针；还有 libnut 的 `type` 在美式键盘布局的符号上丢了 Shift（`*` 打成 `8`，`!` 打成 `1`，`_` 打成 `-`），现在这些以 Shift + 下面那个键的方式输入，ASCII 之外的文字仍像以前一样通过剪贴板和 Ctrl+V 输入。

图的尺寸有两重限制：`[hands] max_image_width`（1600）和 2 Mpx 的像素预算（`nanomuse/computer/coords.py`，`PICTURE_MAX_PIXELS`；操作器的 `/screenshot` 接受同样的 `max_pixels`，0 表示屏幕原样），两者都在 28 像素对齐之前保持宽高比。4K 屏幕的边长缩到一半，1080p 略微裁一点；一次请求里带着几张没封顶的 4K 图，正是中继以 `413` 拒绝的那种情况。

`computer_screen` 向客户端报告的（`status()` / 事件）：`picture_size` 和 `screen_size` 分开给。桌面版画预测标记（一个转动的虚线圆环、精确落点上的一个圆点、旁边的动作名、拖动的一条虚线），用的是操作器自己给出的显示器比例，所以你看到的就是它点的地方，不是客户端以为它会点的地方。

## 限制 {#limits}

- 一次一台手机：最近连上的、`gui: true` 的设备就是智能体操作的那台。
- 操作器看到的正是设备画出来的东西。图里读不出的字它就没法去动：它点到目标旁边时，第一件要查的是截图分辨率低不低。图和点击空间是同一个 `width` × `height`，所以更清楚的图意味着设备要报到（并在其中点击）一个更大的尺寸。
- MobileGym 里用 iframe 渲染的 App（nanoMuse 自己就是一个）在页内截图里是空白的；操作器会被告知屏幕是黑的，而不是看到错误的东西。
- 哨兵依据操作器自己对它要按什么的描述来判断。一个把「支付」藏在没有文字的图标后面的屏幕不会触发词表，所以付款步骤还另外有操作器自己付款前停下来问的规则，付款也一次只批准一次；Android 应用只允许在用锁屏确认之后，为单个 App 或网站记住一次，并把它列在设置 → 权限的最前面。Android 上审批还会读无障碍树说手指下面是什么，和操作器报告的 label 并排，两者中更严的那个说了算。
- Android 上：执行器需要 Android 11+；`FLAG_SECURE` 屏幕（银行 App、支付面板、密码管理器）回来是黑的，操作器会被告知；Android 执行器完全拒绝往密码框里 `type`，不管 label 怎么写；而且 Android 可能悄悄拒绝从后台发起的 `open_app`：执行器会说明，并请用户按主屏键再点图标（Android 14 之前，「显示在其他应用上层」权限会有帮助）。文字在输入框允许时通过 `ACTION_SET_TEXT` 输入，否则通过剪贴板粘贴。
