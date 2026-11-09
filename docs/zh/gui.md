# 操作手机屏幕 {#操作手机}

> **旧版 Python 实现的设计记录**。当前 Android App 的「手」位于 `io.github.nanomuse.hands`，从 0.1.12 起沿用本文的工具选择顺序、带「停止」按钮的胶囊和审批机制，但智能体直接在手机上执行，见 [android.md](android.md)。下文旧方案提到的小熊猫，在当前胶囊中已替换为智能体自己的形象，默认为龙。

Muse 在西方主要通过 API（供程序调用的接口）接入服务。中国用户常用的 12306、微信、支付宝、美团等 App，大多没有可供个人智能体调用的接口。因此 nanoMuse 还提供屏幕操作工具，称为「手」：打开「手机」开关后，智能体可以查看屏幕，在 App 中点击、输入和滑动。这些仍由同一个智能体发起，也经过同一个哨兵（Sentinel）检查；每步 GUI（图形界面）操作都作为工具调用处理。

设计遵循以下原则：

- **在指定设备运行**。智能体运行在你选择的机器上，Android 版则运行在手机本身。屏幕只发送给你配置的模型，不交给其他服务。
- **优先适配中国使用场景**。nanoMuse Cloud 账号使用中继为 `gui` 推荐的模型，目前为 `Qwen/Qwen3.6-27B-FP8`。中继是负责账号和请求转发的服务器。使用自己的 key 时，按服务商目录选择同一接口上的操作模型，中国大陆为阿里云百炼 `qwen3.8-27b`，其他地区为 OpenRouter `qwen/qwen3.8-27b`，具体见下文模型选择说明。示例任务使用 12306 和微信，敏感词以中文为主。
- **不依赖逐个 App 接入**。操作器通过图片理解屏幕，再按坐标点击，不要求无障碍树、带标签按钮或专用集成。同一操作循环既可订车票，也可读聊天。无障碍树是系统提供的界面元素结构；Android 能提供时，会作为辅助输入，帮助辨认小字和密码框，但流程不依赖它。
- **最后才使用屏幕**。优先选择能准确完成任务的技能、CLI（命令行工具）或 MCP 服务器（通过统一协议提供工具的服务），其次携带登录状态获取网页，再用 App 内浏览器，最后操作手机屏幕。每个屏幕步骤都要调用模型并发送图片，因此只有前面的方式无法完成时才升级，开始前会说明。

手机屏幕操作默认关闭。开启之前，模型不会收到这部分手机内容。

## 工具选择顺序 {#the-ladder}

访问服务时，依次尝试以下四种方式：

| 级别 | 方式 | 适用情况 |
|---|---|---|
| 1 | **技能**、**CLI** 或 **MCP 服务器**，例如 `feishu` 调用 lark-cli，`amap` 调用 MCP，以及邮件、日历和文件工具 | 有可用接口时优先选择，直接准确获取结果，无需查看屏幕 |
| 2 | **携带用户登录状态获取页面**，例如 `browser` 的 action=fetch、`web_fetch` | 登录后直接请求页面就能得到答案 |
| 3 | **App 内浏览器**逐页操作 | 网站需要点击或填写后才能完成 |
| 4 | **手机屏幕**，工具为 `phone_task` | 仅在 App 中提供的功能，例如微信聊天、12306 实时余票、美团订单或付款 |

技能在 front matter（文件开头的元数据区）中用 `channel:` 声明接入方式：`api`、`cli`、`web`、`browser`、`gui`、`mixed`，其中 `app-only`、`phone` 也作为 `gui` 接受。`gui` 技能在索引中标为 *[on the phone's screen]*，让智能体知道需要屏幕操作。内置示例为 `train-tickets` 和 `phone-messages`。首次操作屏幕前，智能体会用一句话说明要做什么；如果你没有主动要求使用手机，而是其他方式失败后需要升级，它会先征求同意。「活动」视图统计会话中的屏幕操作步数，供你检查是否遵循这个顺序。

## 实际使用过程 {#what-it-looks-like}

你说「帮我看看明天北京到上海最早的高铁」，智能体会打开手机 12306，设置车站与日期，点击「查询车票」，筛选「只看高铁」，再汇报列表。让它回复微信时，它会进入聊天、输入文字，在发送前停下等待审批。如果任务同时涉及网页研究、12306 订票和日历日程，它会按需要交替使用直接工具和屏幕。

每个屏幕步骤会出现在聊天中，例如 `phone_act: tap "发送" at (318,742) in 微信 (wechat)`。手机上会显示点击圆环和当前操作文字，见[显示操作位置](#showing-the-finger)。任务结束后，`nanomuse phone traces` 可列出任务，`nanomuse phone trace <id> -o trace.html` 可生成包含每张屏幕和点击标记的查看页面。

## 启用操作工具 {#turning-it-on}

在 App 中进入连接 → 手机，打开开关；也可以在 `config.toml` 设置：

```toml
[gui]
enabled = true
```

或使用环境变量 `NANOMUSE_GUI_ENABLED=1`。启用后，智能体会获得下文三个工具，系统提示词也会加入已连接手机信息。关闭时，这些工具不会注册。

### 选择屏幕操作模型 {#the-model-that-moves-the-finger}

操作器每步都需要读取截图，会产生多次带图请求，因此可以使用与聊天模型不同的独立模型：

```toml
[gui]
enabled  = true
provider = "openai"                                   # or openai_responses
model    = "qwen3.8-27b"                              # must take images; a fast one that reads well is enough
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key  = "{{vault:GUI_API_KEY}}"
```

手机和桌面版通过设置 → 模型的「操作屏幕」设置，网页控制台通过「连接」中的「手的模型」下拉框设置，配置文件则使用 `[gui] model`。聊天和操作屏幕是独立设置。留空或选择「自动」时，按下列顺序决定：

- 如果对话使用自己的 key，且服务商目录为同一接口指定了操作模型，则用该模型，例如百炼 `qwen3.8-27b`、OpenRouter `qwen/qwen3.8-27b`。已知不支持图片的模型不会列为操作模型，例如 ID 不含 `v4.1`、`vision`、`ocr` 的 DeepSeek 模型。
- 否则，已登录 nanoMuse Cloud 时，使用中继为 `gui` 推荐的模型。`/v1/models` 通过 `for` 和 `recommended_for` 标明模型适用于 `chat`、`gui` 或两者。托管服务目前用同一个多模态 `Qwen/Qwen3.6-27B-FP8` 处理聊天和屏幕，但两项仍可分别配置。
- 否则使用聊天模型本身，前提是支持看图。手机和桌面版在这之前还会尝试第一个支持视觉模型的自备 key。

手动选择始终优先，「自动」项会显示当前实际选择。自己的操作模型失败时不会自动切换，卡片会提供「这次改用 nanoMuse Cloud」，只应用于当前一轮，见 [own-key.md](own-key.md#which-model-does-what)。

key 与其他凭据一样放入保险库，可运行 `nanomuse vault set GUI_API_KEY`，或在「手机」卡片中填写。操作模型必须支持图像输入，因为主要观察来自截图。调用时温度设为 0，即减少采样随机性，让模型按首选判断定位。

可用环境变量覆盖：`NANOMUSE_GUI_ENABLED`、`NANOMUSE_GUI_PROVIDER`、`NANOMUSE_GUI_MODEL`、`NANOMUSE_GUI_BASE_URL`、`NANOMUSE_GUI_API_KEY`。

其他设置包括 `max_steps`，默认 0 表示不限制单次 `phone_task` 步数；`device_timeout_s`，默认 20，表示每次设备请求等待秒数；以及下文的 `sensitive_words`。

## 连接手机 {#connecting-a-phone}

智能体不必与手机运行在同一设备。手机可以通过 App 使用的 WebSocket 连接 nanoMuse 服务器。WebSocket 是保持连接、双向收发消息的协议；设备先声明自身信息，再响应截图和操作请求。目前有以下两种实现：

- **MobileGym**。位于 [mobilegym.dev](https://mobilegym.dev/) 的模拟手机，将微信、支付宝、铁路12306、地图、小红书等模拟为浏览器中的 React App。`demo/mobilegym/` 模块的设置页提供「允许 nanoMuse 操作这台手机」。展示站使用这个环境，不操作真实账号或服务。
- **Android**。nanoMuse App 通过自己的无障碍服务执行真实操作。`takeScreenshot()` 截图，`dispatchGesture()` 发送手势，无障碍树提供元素列表，`performGlobalAction` 执行返回、主屏和最近任务，`open_app` 使用 App 可启动列表。协议与模拟器相同。需要 Android 11 或更新版本，因为无障碍服务从该版本起支持截图，并需要启用服务：

  1. 进入连接 → 手机 → 这台手机 → 打开无障碍设置，在「已下载的应用」中找到「nanoMuse」并开启。Android 会说明查看屏幕、执行手势等能力，并要求确认。
  2. Android 13 及更新版本中，从应用商店以外安装的 App 可能显示灰色「受限设置」。点击同卡片的「应用设置」，打开系统 App 页面，选择 ⋮ →「允许受限设置」，再执行第 1 步。
  3. 更新、厂商电池清理或某些手机重启后，Android 可能自动关闭无障碍服务。「手机」卡片实时显示「就绪」或「还没有」，手机无响应时先检查这里。服务启停会立即通知服务器，因此连接 → 手机能及时反映状态。

  服务不会自行操作，只在 `phone_*` 请求时截图。任务执行期间，顶部胶囊显示形象、当前步骤和「停止」，见下文。

连接 → 手机显示已连接设备及其 App 数量。`GET /api/phone` 返回同样信息和最近一次屏幕读取。

## 工具 {#the-tools}

| 工具 | 风险 | 功能 |
|---|---|---|
| `phone_screen` | SAFE，读取私密数据 | 获取当前截图供模型查看，并附说明，例如 `铁路12306 (railway12306) · /station-select · 360×800 · keyboard hidden` |
| `phone_act` | MODERATE，特定情况升为 SENSITIVE，见下文 | 执行单个动作：带 `x` / `y`、`label` 的 `tap`、`long_press`、`double_tap`；指定 `x2` / `y2` 或 `direction` 的 `swipe`；以及 `type`、`enter`、`back`、`home`、`recents`、`open_app`、`wait`。返回操作后的屏幕 |
| `phone_task` | 按每步分别判断 | 将目标交给手机操作器。它用独立模型循环查看和操作，直到完成、需要用户或无法继续。每步转换为 `phone_act`，并经过哨兵 |

SAFE、MODERATE、SENSITIVE 分别是安全、中等和敏感风险。屏幕仍是最后选择：搜索、网页、邮件、日历、文件或连接器能直接准确完成时，优先使用。只有用户自己的 App 和账号才能完成的操作，例如实时余票、微信聊天、美团订单或账号付款，才需要手机。屏幕操作较慢，且每步都要调用模型，因此不会为了查北京到上海的距离而打开 12306，见[工具选择顺序](#the-ladder)。

超过一两步的工作通常交给 `phone_task`，例如打开 12306、找明天北京到上海最早车次并报告前三趟。主智能体只需查看或执行单项动作时，则用 `phone_screen` / `phone_act`。操作器将详细过程留在内部，可减少主模型上下文，也就是每次需要读取的历史内容。

## 操作器 {#the-operator}

`phone_task(goal, app?, max_steps?)` 启动内部循环，实现移植自 MIT 许可的 [MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench) `mobile_use` 操作器：

1. **查看**。获取当前截图，将目标及历史步骤一并交给操作模型。每个历史步骤缩成一句话，例如 `Step 3: 点击「查询车站」按钮。; Result: …`。设备提供元素列表时，附最多 60 行，输入框优先，每行包括文字、类型、标记和中心坐标，使用与模型输出一致的 999 网格，例如 `- "密码" · EditText [editable, password] @ 500,375`。这些信息辅助读小字和定位，截图仍是主要输入。
2. **决定**。模型必须返回一行 `Thought:`、一条使用用户语言的 `Action:`，以及调用 `mobile_use` 的 `<tool_call>`。动作支持 `click`、`long_press`、`swipe`、`type`、`open`、`system_button`，后者包括 Back、Home、Menu、Enter，以及 `wait`、`answer`、`ask_user`、`terminate`。坐标使用 999×999 网格，再换算为手机像素。格式错误时会附提醒交回模型修正，最多三次。
3. **执行**。将决定转换为 `phone_act`，用 Action 句子作为 `label`，供哨兵判断、审批卡片展示和轨迹记录，然后回到第 1 步。

完成时返回 `done` 和模型 `answer`，从屏幕读出的文字放在答案中。模型调用 `ask_user` 或哨兵需要决定时返回 `ask`，由主智能体询问用户后继续；两次拒绝后返回 `blocked`；用户点「停止」后返回 `stopped`。调用 `terminate(failure)`、达到 `max_steps` 或手机不再响应时以 `failed` 结束。相同动作连续三次会在历史中加提示，要求模型调整做法。没有设置上限时不限制总步数，但连续六步未改变屏幕，例如未知函数、设备拒绝或重复无效动作，会以 `failed` 结束，避免无人值守时不断消耗无效调用。

支持胶囊的设备还会收到任务开始、结束和需要用户的通知。开始时显示目标，结束时收起；`ask`、`blocked` 会变成带问题和「打开」按钮的卡片，方便你正在查看微信等 App 时直接返回 nanoMuse。

操作器提示词规定：不输入密码、PIN、卡号或验证码，先调用 `ask_user`；不确认未经明确要求的付款或转账；只执行任务要求。请求只是查询时，读完就调用 `answer`，不继续点击。

## 哨兵如何检查屏幕操作 {#what-sentinel-does-with-it}

屏幕内容按私密数据处理。首次 `phone_screen` 后，当前对话会标为 tainted，即已污染，表示后续内容可能包含隐私。此后向外发送数据的操作要遵守更严格规则，见 [sentinel.md](sentinel.md)。

普通 `phone_act` 为 MODERATE，默认模式可直接执行；可能提交、发送或确认操作时，会升为带警告的 SENSITIVE。带警告意味着必须询问，并且只批准当前一次：

- `tap`、`long_press`、`double_tap`、`enter` 的 `label` 含 `sensitive_words`，例如确认支付、立即付款、转账、提交订单、立即购买、发送、删除、注销、pay now、place order、send、delete。App 名称不触发这条规则，因此点击支付宝图标不等于付款。
- `type` 同时带 `submit`，把输入与提交合为一步。操作器不会这样做，而是先输入，再在下一步点击发送，让审批能检查输入框中的内容。

带坐标的动作必须提供 `label`，说明屏幕上将要点击什么；操作器使用 Action 句子。缺少 label 的点击仍会执行检查，但附「没有任何信息说明手指下面是什么」警告；越出屏幕的坐标在发送到手机前直接拒绝。如果最近屏幕数据中有覆盖该坐标的元素边界，哨兵还会读取元素文字，与 label 分别判断并采用较严格结果。没有元素列表时，仍按 label 检查。

默认敏感词包含中文和英文，其他 App 或语言可修改 `[gui] sensitive_words`。这类审批仅对一次操作有效，批准一条消息不会自动批准下一条。

电脑还会按 App 请求授权：每段对话中首次对某 App 调用 `computer_act`，会显示「让 <Muse> 使用 <App>？」。你可选「允许一次」「本次对话都允许」「总是允许」，保存为 `computer_app:<id>`，可在设置 → 权限查看。App 内每个动作仍遵守上述规则。macOS 还支持只在该 App 的窗口中工作，见 [every-device.md](every-device.md#window-mode-macos)。

### 将屏幕交给用户 {#handing-the-screen-over}

密码、验证码、人机验证和付款确认由用户处理。操作器的 `hand_over`，或 `computer_act` / `phone_act` / `browser` 的 `hand_over` 加 `reason`，会在聊天及胶囊显示「轮到你了：<reason>」和「完成」。桌面版显示在任务轨迹卡片中，最多等十分钟。

这段等待称为 hold。期间同一线程中该工具的所有动作暂停。你处理后点击「完成」，操作器重新截图，并收到用户曾接管、需要重新观察的提示。焦点位于密码框时，`type` 会自动转为交接。你也可以主动点击「手」或浏览器卡片的「接管」，或调用 `POST /api/holds {"thread","tool","reason"}`。`POST /api/holds/{id}/done` 结束等待，`GET /api/state` 列出尚未完成的 hold。

哨兵根据模型提供的 label 和设备可提供的目标元素文字判断，不要求一定存在无障碍树。这也限定了它能知道的内容。因此 label 必填，付款另有操作器主动停止并询问的规则，授权也仅限一次。

## 任务轨迹 {#traces}

每次 `phone_task` 都会写入 `<data_dir>/phone-traces/pt-<timestamp>-<id>.jsonl`。JSONL 是每行一条 JSON 的记录格式。开头 `task` 记录目标、App、上下文；每次循环的 `step` 记录 App、路由、截图路径、模型想法和 Action、工具调用、实际设备动作、耗时及错误；最后 `end` 记录状态、说明、步数和秒数。最多保留最近 200 份轨迹、400 张截图。

```
nanomuse phone traces                    # newest first: id, when, status, steps, goal
nanomuse phone trace pt-20260923-230710-5be7
nanomuse phone trace pt-20260923-230710-5be7 -o trace.html
```

生成的 HTML 会内嵌全部截图，在模型当时看到的图片上用圆环标点击、用线标滑动，因此可以作为单个文件分享或附到 issue。

## 设备通信协议 {#the-device-protocol}

这一节供实现其他执行器的人参考。执行器是接收请求、实际操作设备的程序。消息通过 App 的 `/ws` WebSocket 传输，首帧携带令牌。

设备先声明自身信息：

```json
{"kind": "device", "name": "MobileGym", "platform": "mobilegym", "gui": true, "capsule": true,
 "apps": [{"id": "wechat", "name": "微信"}, {"id": "railway12306", "name": "铁路12306"}],
 "screen": {"width": 720, "height": 1600}}
```

服务器返回 `{"kind": "device_ack", "phone": {…}}`。状态变化时可在同一连接再次声明，例如 Android 无障碍服务开关变化会更新 `gui`；服务器保留原连接时间，更新其他信息。`"capsule": true` 表示支持带停止按钮的步骤胶囊，并希望接收下述 `task` 通知。之后服务器一次发送一个请求：

```json
{"kind": "device_request", "id": "r1", "op": "screen", "params": {}}
{"kind": "device_request", "id": "r2", "op": "act", "params": {"action": "tap", "x": 68.5, "y": 447.6, "label": "点击热门车站中的「北京」。"}}
```

设备以 `{"kind": "device_result", "id": "r1", "ok": true, "result": …}` 返回成功，或以 `{"kind": "device_result", "id": "r1", "ok": false, "error": "…"}` 返回失败。

`screen` 返回截图和屏幕信息：

```json
{"app": "railway12306", "app_name": "铁路12306", "route": "/station-select",
 "width": 360, "height": 800, "keyboard": false,
 "screenshot": "<base64 PNG or JPEG>", "note": "optional"}
```

`screenshot` 是整屏图片，尺寸为 `width` × `height`，与设备接受点击的坐标空间一致，图中坐标可直接用于点击。未提供尺寸时，服务器从图片读取。旧字段名 `image` 仍被接受。坐标以左上角为原点，单位为图片像素。`app`、`app_name`、`route`、`keyboard` 可选，用于完善画面说明、哨兵摘要和轨迹。

如果设备提供无障碍树，或像 MobileGym 一样有 DOM（网页元素结构），可以附 `nodes`。列表为最多 120 个含文字或可操作的元素，使用截图像素坐标：

```json
{"nodes": [
  {"id": "0.3.1", "class": "Button", "text": "查询车票", "cx": 180, "cy": 612, "box": [24, 588, 336, 636], "clickable": true},
  {"id": "0.2.0", "class": "EditText", "hint": "密码", "cx": 180, "cy": 400, "editable": true, "password": true}
]}
```

`id` 是元素在树中的稳定索引路径；`text`、`desc`、`hint` 提供文字；`res` 为资源 ID。可用标记为 `clickable`、`long_clickable`、`editable`、`password`、`checked`、`scrollable`、`focused`、`selected`、`disabled`。服务器保留前 120 项，选其中最有用的 60 项交给操作器，输入框优先。列表不是必需项：WebView、Flutter App、游戏或 `FLAG_SECURE` 屏幕可能不提供，操作循环仍可运行。Android 发送前将截图缩至 720 px 宽，收到坐标后按比例放大，因此模型使用的图片坐标与点击坐标对应。

`act` 返回 `{"note": "…", "screen": {…}}`，包含动作结束且页面稳定后的屏幕，单步只需一次请求往返。

设备需要支持以下动作：

| 动作 | 参数 |
|---|---|
| `tap`、`double_tap` | `x`、`y` |
| `long_press` | `x`、`y`、`seconds`，≤ 5 |
| `swipe` | `x`、`y`、`x2`、`y2`；或 `direction`，取 up/down/left/right，配合占屏幕比例的 `distance` 和可选起点 |
| `type` | `text`、`clear`，表示先清空输入框，`submit`，表示输入后回车；已知时附输入框 `x`、`y` |
| `enter`、`back`、`home`、`recents` | — |
| `open_app` | `app`，使用声明列表中的 ID 或名称 |
| `wait` | `seconds`，≤ 10 |

每个带坐标的动作还含 `label`。执行器应显示它，见下文，也可写入日志，无需另外解析它。

声明 `"capsule": true` 的设备还会接收 `task` 请求，例如 `{"op": "task", "params": {"event": "begin", "text": "<goal>"}}`，以及 `"end"`、带用户问题的 `"notice"`。设备返回空的成功 `ok` 即可。这些通知尽力发送，3 s 内没有应答就不再等。无论任务完成、被停止、设备离线、模型失败还是聊天取消，服务器都会尝试发送 `end` 或 `notice`，但恰好断线的设备可能收不到。

因此，服务器也在手机状态中保存正在运行的任务。每条 socket 的 `hello` 都包含 `"phone": {…, "task": {"goal": "…", "since": <unix seconds>}}`，无任务时 `task` 为 `null`。设备连接或重连时应据此恢复胶囊：任务仍在运行就显示，中途已结束就关闭。连接永久关闭，或所谓运行中的任务长时间没有向设备发出任何请求时，也应自行隐藏；MobileGym 使用三分钟超时。

**停止操作**。用户点击「停止」后，执行器应让当前请求及之后所有请求失败，直到收到下一次 `task begin`。错误必须带 `nanomuse:stop`。服务器将其识别为 `stopped`：操作器结束循环，`phone_act` 返回可读说明，主智能体收到指示，不再继续操作手机，先询问下一步。没有胶囊的设备无需发送该标记。

MobileGym 的 `demo/mobilegym/apps/nanoMuse/gui.ts` 可作为参考。它用 `modern-screenshot` 在页面中将模拟器 DOM 渲染成 PNG，抵消手机 CSS 变换并排除舞台，输出手机两倍尺寸的 720×1600 图片以便读取小字，再将点击缩回手机坐标。它遍历可见、未遮挡、可交互或含文字的 DOM 元素生成 `nodes`，通过标签和 role 推断类型，从模拟器 OS 对象读取 App 和路由，并调用 MobileGym 自身输入 API 执行动作。它和 Android 一样拒绝对密码或验证码输入框调用 `type`，改由胶囊请用户填写并点击「继续」。

## 显示操作位置 {#showing-the-finger}

设备应把智能体的操作位置和当前动作显示出来，方便用户跟踪。标记使用手机坐标，绘制在不进入截图的独立图层上，避免模型把标记当作页面内容。MobileGym 是参考实现，Android 使用两个无障碍悬浮窗：不可接收触摸的全屏标记层，以及胶囊层；截图瞬间会隐藏两者。

| 操作 | 显示方式 | 时长 |
|---|---|---|
| `tap`、`double_tap` | 从点击位置扩散并淡出的圆环 | 520 ms |
| `long_press` | 保持按住状态的圆环，结束后淡出 | 按 `seconds` 保持，再用 300 ms 淡出 |
| `swipe` | 从起点到终点的路径线，终点带圆环 | 随滑动持续 320 ms，然后淡出 |
| `type` | 字符逐个出现 | 每字符 40 ms |
| 所有动作 | 底部说明 `Muse · <label>`，或 `输入 “…”`、`打开 <app>`、`滑动 up` | 2.6 s，下一条会替换 |

执行动作后先等界面稳定，再返回截图。MobileGym 等 650 ms；Android 等到无障碍事件连续安静 450 ms，最多等 3 s。等待属于动作本身，因此 `screen` 不会读到切换中的画面。

### 胶囊 {#the-capsule}

胶囊是屏幕顶部的小型任务状态条。Android 和 MobileGym 都显示它，浮在被操作 App 上方，包含形象、当前步骤，例如 *Muse · 点击「查询车票」*，以及「停止」。`task begin` 时出现，随步骤更新，`task end` 时短暂显示勾号后收起，手机返回 nanoMuse 查看任务报告。Android 将自身带回前台，MobileGym 恢复 nanoMuse 模拟 App。胶囊不进入截图。

点击「停止」即可中止，无需长按或展开菜单。当前动作以 `nanomuse:stop` 失败，胶囊显示「已停止」并隐藏，返回 nanoMuse，智能体询问后续安排。任务需要用户处理，即 `ask`、`blocked` 时，胶囊展开为问题卡片，并提供「打开」返回 nanoMuse，显示一分钟后收起。

### 桌面上的同类提示 {#the-same-on-the-desktop}

桌面版沿用相同操作提示，并按鼠标指针调整，见 [desktop-muse.md](desktop-muse.md#computer-use)。显示器边缘的光晕用蓝色表示工作、琥珀色表示等待；目标位置显示圆环、旋转青色弧、精确圆点和动作名称；拖动显示带箭头的虚线路径。nanoMuse 窗口不在前台时，屏幕顶部胶囊显示形象、「第 N 步」、步骤说明、「我来接手」和「停止」。光效不流动或扫过，而以 2.4 s 变亮、2.4 s 变暗的节奏变化；开启「减弱动态效果」后保持静止。

**轨迹回看**。桌面聊天在本次运行最后一次操作工具调用下，显示各步截图、操作标记和操作前的智能体文字。点击用标记、拖动用箭头、滚动用 V 形符号，输入文字或组合键显示在标签胶囊中。你可以切换上一步、下一步，使用方向键，或点击「放大查看」「复制这一步」。

这些内容从既有结果构建：`computer_screen` / `computer_act` / `device_screen` 提供图片，第一行提供标题和尺寸；`computer_act` 参数提供动作、拖动终点 `x2` / `y2` 或 `box2`，以及滚动 `dy`。工具、MCP 结果和 hub 帧无需新增字段。宿主内存最多保留每次运行 40 步、4 次运行、64 MB 图片，通过 `GET /nanomuse/cloud/trajectory?session=<id>`、`GET /nanomuse/cloud/stage/frame?seq=N` 提供给窗口。数据格式和上限见 [desktop-muse.md](desktop-muse.md#computer-use)。

## 电脑操作统一使用图片坐标 {#hands-on-the-computer-the-picture-is-the-unit}

电脑的 `computer_screen` / `computer_act` 遵守手机相同原则，见 [every-device.md](every-device.md#hands-on-this-computer)，但需要额外处理显示缩放。4K 显示器对 X11 和鼠标是 3840×2160，对 Electron 是 1920×1080 逻辑尺寸，给模型的图片可能是 1596×896。0.1.36 以前，模型获知屏幕尺寸却看到缩小图片，返回坐标又直接用于点击，导致 Linux 点击偏离目标。

现在所有模型坐标以图片为准。`computer_screen` 第一行报告 `<window in front> · 1596×896 · …`，结尾注明 *Coordinates: pixels of this 1596×896 picture, (0,0) top-left.*。`computer_act` 的 `x`、`y` 指图片像素；`box` 为 `[x1, y1, x2, y2]` 并取中心。`drag` 的 `x2`、`y2` / `box2` 使用同样规则。运行时将操作器实际屏幕坐标与图片坐标分开，在执行前通过 `nanomuse/computer/coords.py` 的 `Mapping` 换算，并为轨迹和光晕再次映射。

截图先按 `[hands] max_image_width` 限制，再对齐 Qwen3-VL 使用的 28 像素缩放网格，即 UI-TARS 的 `smart_resize`。这样模型不必再改变图片尺寸，指定像素与看到的像素一致。如果模型按归一化坐标训练，可以设 `[hands] coords = "norm1000"`，让 `x`、`y` 使用覆盖整张图的 0–1000 网格。

各后端的实际操作坐标来源如下：

| 后端 | 实际操作坐标空间 | 说明 |
|---|---|---|
| `desktop`，桌面版 | 显示器逻辑尺寸 × 缩放系数；macOS 系数为 1，单位为点 | App 自带操作器 `@computer-use/nut-js`，移植自 UI-TARS-desktop，通过回环 HTTP 通信。App 设置 `NANOMUSE_OPERATOR_URL` 后，`auto` 优先使用它 |
| `pyautogui` | `pyautogui.size()` | macOS 为点，其他平台为物理像素；Mac 桌面版不使用此后端 |
| `xdotool` | `xdotool getdisplaygeometry` | X11 根窗口像素 |

macOS 桌面版始终由操作器执行截图和输入，失败时直接返回原因，不尝试其他截图程序。缺少录屏权限时会提示在系统设置 → 隐私与安全性 → 录屏中启用 nanoMuse Desktop，再退出重开；拒绝授权或全黑截图会返回 `403`。不回退至 `mss`、`screencapture`、`pyautogui`，是因为权限绑定 App 包，回退会使 TCC（macOS 隐私权限管理机制）为另一个未出现在设置中的进程请求授权，还可能把黑图当作正常屏幕传给模型。Linux、Windows 和不经桌面 App 启动的运行时仍保留 Python 回退，见 [desktop.md](desktop.md#macos-permissions)。

从 0.1.38 起，Mac 操作器把截图和输入交给桌面包中的 Swift 辅助 App **nanoMuse Computer Use**，由它自己持有录屏和辅助功能授权。macOS 14 及更新版使用 ScreenCaptureKit 的 `SCScreenshotManager` 截主屏，12、13 使用 `CGDisplayCreateImage`；鼠标键盘使用 `CGEvent`，可直接输入任意文字系统的字符。

macOS 将权限归给 LaunchServices 启动的进程。辅助 App 通过 `open` 启动，因此在录屏、辅助功能设置中有独立条目，应打开「nanoMuse Computer Use」。录屏授权需重启该辅助进程才生效，桌面 App 会自动处理。操作器路由、点坐标和缺权限时的 `403` 不变，提示中的程序名称改为辅助 App。

辅助程序截图失败时，例如 ScreenCaptureKit 拒绝、没有图像、进程退出或未启动，操作器不会改用 `desktopCapturer`。`/screenshot` 返回辅助程序原因，例如 `no screenshot: nanoMuse Computer Use could not take the picture: ScreenCaptureKit userDeclined (-3801): …` 或 `… did not start (…)`。日志写入 `helper screenshot failed (…) — not falling back to desktopCapturer`，`computer_screen` 将说明显示到聊天。只有未打包辅助 App 的构建继续使用 `desktopCapturer` 和 nut.js，见 [desktop.md](desktop.md#macos-permissions)。

**macOS 窗口模式**也使用同一辅助 App，见 [every-device.md](every-device.md#window-mode-macos)。运行时调用 `GET /windows` 获取窗口 ID、进程、应用、bundle ID、标题和以点计的位置尺寸；调用 `POST /window {id}` 获取该窗口独立像素，使用 `SCContentFilter(desktopIndependentWindow:)`，不含阴影或光标，并返回窗口位置，使图片像素能映射到屏幕点。

在桌面 App 下，Mac 运行时不自行截取窗口；窗口模式的鼠标键盘事件仍由运行时通过 `CGEventPostToPid` 发往目标进程，因此辅助功能中还需要「nanoMuse」条目授权。辅助 App 没有录屏权限时返回 `403`，窗口消失时返回 `404`，原因原样传回，下次观察再试。辅助 App 完全不存在时，对该目标使用全屏并在观察中说明。未打包辅助 App 的构建则保留运行时的 `CGWindowListCreateImage` 路径，并记录 `window mode: the runtime captures windows itself …`。

Linux 操作器仅支持 **X11（Xorg）**。实际坐标是 X 根窗口像素；HiDPI 下为逻辑尺寸乘缩放系数，例如 1920×1080、缩放 2 对应 3840×2160。`/info` 会说明，截图再按前述规则缩放给模型。

**Wayland** 不允许程序直接控制全局屏幕或光标。因此 `/info` 表示操作工具关闭并提示使用 Xorg 登录，`/screenshot` 以相同说明返回 `503`，不会打开屏幕选择器。运行时首次尝试就明确报告，也不会回退到 `xdotool`、`pyautogui`，因为它们即使在 XWayland 启动，也无法操作用户实际桌面。会话类型由 `XDG_SESSION_TYPE` 判断，或由存在 `WAYLAND_DISPLAY` 而没有 `DISPLAY` 判断。

0.1.38 修复了 X11 的两类问题。其一，光晕本身也是 X 窗口，每次映射或调整配置后，X11 可能丢失点击穿透设置，导致点击被光晕拦住。现在操作器先确认光晕可穿透，再移动指针。其二，libnut 输入美式键盘符号时丢失 Shift，例如 `*` 变 `8`、`!` 变 `1`、`_` 变 `-`；现在按 Shift 加对应键输入。非 ASCII 文字仍通过剪贴板和 Ctrl+V 输入。

图片同时受 `[hands] max_image_width`，默认 1600，以及 2 Mpx 像素总量限制。后者定义为 `nanomuse/computer/coords.py` 的 `PICTURE_MAX_PIXELS`；操作器 `/screenshot` 接受相同 `max_pixels`，0 表示原始屏幕。两项都在对齐 28 像素网格前保持宽高比。4K 屏幕边长约缩至一半，1080p 略作缩小。此前请求含多张未缩小 4K 图片会触发中继 `413`。

`computer_screen` 在 `status()` 和事件中分别提供 `picture_size`、`screen_size`。桌面版使用操作器提供的显示器相对比例绘制旋转虚线圆环、精确圆点、动作名及拖动虚线，因此标记反映实际点击位置。

## 限制 {#limits}

- 一次只操作一台手机，选择最近连接且声明 `gui: true` 的设备。
- 操作器只能根据设备提供的画面判断，无法操作看不清的文字。点击偏移时先检查截图分辨率。图片和点击共享 `width` × `height` 空间，提供更清晰图片时，设备也要按相应大尺寸声明和接收点击。
- MobileGym 中由 iframe 嵌入的 App，例如 nanoMuse 自身，在页内截图中会空白。系统会告知操作器画面是黑的，不会误当作有效截图。
- 哨兵同时检查模型 label 和可用的目标元素文字，取较严格结果。如果付款藏在无文字图标中，敏感词可能无法命中，因此还依赖操作器付款前主动停止并询问，以及付款逐次授权。Android 仅在锁屏确认后才允许为单个 App 或网站保存付款授权，并将其列在设置 → 权限最前面。Android 还会将无障碍树的实际目标文字与模型 label 一起检查。
- Android 执行器需要 Android 11+。`FLAG_SECURE` 保护的银行 App、支付页或密码管理器会返回黑图，并明确告知操作器。无论 label 如何，Android 执行器都不向密码框 `type`。系统可能拒绝后台 `open_app`，此时执行器会说明并让用户按主屏键、点击图标；Android 14 前，「显示在其他应用上层」权限可改善该情况。输入框允许时使用 `ACTION_SET_TEXT`，否则通过剪贴板粘贴。

Android 还会在同一对话、同一已识别 App 的后续明确请求之间保留有限记录，支持可选的更大幅度纵向滚动，并保留完整 JSON 结果，见[继续操作屏幕](android.md#hands-continuity)。
