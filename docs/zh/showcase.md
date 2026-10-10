# 展示站：中国人一天里要办的七件事

nanoMuse 是一个智能体，有好几只手。它读写文件、搜网页、跑命令、开浏览器；调用 MCP 服务器和命令行工具；照技能办事；跑在手机上时，还会用手机自己的日历、剪贴板和闹钟；实在没别的办法了，才去动手机屏幕上的 App。[阶梯](gui.md#the-ladder)规定哪只手先上：技能、CLI 或 MCP 服务器；然后是带着用户登录态的 fetch；然后是应用内浏览器；最后才是屏幕。下面七个案例里，只有一个用到了屏幕。这正是要说明的。

这里没有一处会花钱：每一次发送、下单或付款都会停下来等你审批，操作器从不填密码和验证码。这些案例背后是哪些服务、各自在哪里跑过：[services.md](services.md)。

**轨迹。** 每个案例都链接到实际发生的过程：App 存下来的聊天时间线，或者一份带每个屏幕、每次点按的手机轨迹。标为*待跑*的案例还没有端到端跑过，那一行写着它在等什么：四个 Tier-1 服务需要所有者的 key 和登录（一把高德 key、一个飞书和一个腾讯会议登录），手机案例需要一台装了这些 App 的 Android 手机。[发布清单](../launch-checklist.md#9-chinese-services-and-the-showcase-p0)在跟踪它们。

## 1. 一句话安排一趟出差 {#_1-a-business-trip-in-one-sentence}

> 明天要去上海开会，下午两点在虹桥附近。帮我看看北京到上海上午出发、下午一点前能到虹桥的高铁，挑一班合适的；查一下从家到北京南站几点得出发；把出发时间写进日历，车次发到飞书的「出差」群。另外记住：我坐高铁只坐二等座、靠窗。

| 手 | 做什么 |
|---|---|
| `skills` | 读 `train-tickets`：查票走 12306 服务器，只在被明确要求时才在手机上订 |
| `remember` | 二等座、靠窗：一条偏好，下次说到火车时会用上 |
| `12306__get-current-date` · `get-station-code-of-citys` · `get-station-code-by-names` · `get-tickets` | 从服务器拿明天的日期、北京和上海虹桥的车站代码、13:00 前的 G 字头车次及余票和票价；第一次查到的卖完了就再查一次 |
| `amap__maps_geo` · `maps_direction_transit_integrated` | 家（记住的）→ 北京南站，那个时段：06:40 前出发 |
| `calendar` | 一条出发时间的草稿，带车次和座位，等你确认 |
| `shell: lark-cli im +chat-search` · `im +messages-send --idempotency-key …` | 「出差」群，那一条消息；正文先出现在审批卡片上 |

全程没碰屏幕。哨兵（Sentinel）只问一次，为了那条消息；其余的要么只读，要么在你自己的工作区里。

**轨迹：**[火车那一半](../traces/case-1-train.md)，2026-09-24 在网页版用 12306 服务器录的；模型发现 13:00 前的二等座全卖完了，如实说了，并给出最接近的替代车次，而不是装作有票。高德路线、日历草稿和飞书消息*待跑*：测试机上需要一把高德 key 和一个飞书登录。

## 2. 早间简报 {#_2-the-morning-brief}

> 每个工作日早上 7:30 给我一条简报：今天北京的天气、飞书上的日程和没做完的任务、腾讯会议里今天有哪些会，一条通知就好。

| 手 | 做什么 |
|---|---|
| `reminders`（一条例程） | `weekdays 07:30`，App 关着也以通知送达；在手机上，运行时的闹钟为此把它叫醒 |
| `amap__maps_weather` | 北京今天：气温、降雨、空气 |
| `shell: lark-cli calendar +agenda --as user` · `task +get-my-tasks --as user` | 今天的日程和未完成的任务，用 `--jq` 精简 |
| `shell: tmeet meeting list --compact` | 今天的会议，带会议号和链接 |
| 通知 | 一张卡片；点开进入聊天，看到完整简报 |

**轨迹：***待跑*：高德 key、飞书和腾讯会议登录。例程和通知这条路本身已经由 App 的测试和模拟器验证过（[archive/android-python-line.md](../archive/android-python-line.md#keeping-it-running) 里*让它一直跑*那部分的工作）。

## 3. 我的京东订单到哪了 {#_3-where-is-my-京东-order}

> 我上周在京东买的耳机到哪了？

| 手 | 做什么 |
|---|---|
| `browser`（手机的 WebView，离屏） | 在后台打开京东的订单页 |
| 登录墙 | 智能体停下来：「接管」把真实页面作为底部面板滑上来，你登录一次，「完成」交还；登录态保留在 App 自己的浏览器 profile 里 |
| `browser` `extract` | 订单，以及它的运单号和快递公司 |
| `kuaidi100__query_trace`（配置了的话） | 包裹的物流事件；否则用订单页自带的物流列表 |
| 回复 | 在哪，预计什么时候到 |

第二级（App 里一个带着你登录态的页面）排在任何屏幕之前：京东没有个人 API，但它的网页版不用 App 也能用。配置好快递100，查物流就成了一次工具调用。

**轨迹：***待跑*：一台装了本地版的手机上的京东登录。浏览器后端、接管面板和登录态的保留已经在模拟器上验证过，见 [browser.md](browser.md)。

## 4. 国庆成都行的预算表 {#_4-a-budget-table-for-成都-over-the-holiday}

> 国庆去成都三晚，住春熙路附近。帮我在去哪儿网上看看每晚 400 元左右、评分 4.5 以上的酒店，挑三家做成预算表存到 trips/chengdu-2026-10/budget.md，只看不订。

| 手 | 做什么 |
|---|---|
| `browser`（电脑上的 Playwright，或手机的 WebView） | 按日期和区域在去哪儿搜酒店，加筛选，读三条列表 |
| `files` | `trips/chengdu-2026-10/budget.md`：名称、位置、每晚价格、三晚合计、评分 |
| 资源库 | 这张表在 App 里作为一个页面打开 |

第三级：公开网站，不用登录，在后台浏览，你可以去忙别的。智能体不下单；「只看不订」也正是 `browser` 工具的哨兵规则对下单和付款按钮的要求。

**轨迹：**2026-09-24 那次运行见本页末尾的说明。

## 5. 约一个会，告诉群里 {#_5-book-a-meeting-and-tell-the-group}

> 下周三下午三点跟设计组开半小时的评审会，用腾讯会议，把会议号发到飞书「设计评审」群。

| 手 | 做什么 |
|---|---|
| `calendar` | 那个时段空着 |
| `shell: tmeet meeting create --subject 设计评审 --start 2026-09-30T15:00+08:00 --end 2026-09-30T15:30+08:00` | 一张审批卡片，带完整命令；返回里有 `meeting_code` 和 `join_url` |
| `shell: lark-cli im +messages-send --chat-id oc_… --text "…"` | 群消息，带会议号和链接；正文在第二张卡片上 |
| `reminders` | 提前十分钟 |

两个 CLI，两次审批，没打开任何 App。**轨迹：***待跑*：测试机上的腾讯会议和飞书登录（`tmeet auth login`、`lark-cli auth login`）。

## 6. 剪贴板 → 日历 + 闹钟 {#_6-clipboard-→-calendar-alarm}

> （复制了一条消息：「周五上午10点，海淀区中关村大街1号3层会议室，带上合同」）把剪贴板里的这个安排加到日历，提前一小时给我设个闹钟。

| 手 | 做什么 |
|---|---|
| `device__clipboard_read` | 那段文字（Android 只允许 App 在前台时读剪贴板；不在前台时工具会说明） |
| `device__calendar_create` | 周五 10:00，地址作为地点，「带上合同」写进备注；第一次会弹 Android 自己的权限对话框 |
| `device__alarm_set` | 周五 09:00，通过时钟 App |
| `amap__maps_geo`（可选） | 核对地址，把路上时间加进备注 |

手机自己的能力作为 MCP 工具（[device.md](device.md)）；除了可选的那次地理编码，什么都不离开手机。**轨迹：***待跑*：Android 手机上的本地版（设备服务器只在那里跑）。

## 7. 一单美团，停在付款前 {#_7-a-美团-order-that-stops-before-payment}

> 用美团给我点一份公司附近的麦当劳板烧鸡腿堡套餐，送到公司，到付款前停下来。

| 手 | 做什么 |
|---|---|
| 在美团里的 `phone_task` | 搜索、餐厅、套餐、地址；整个过程中胶囊显示当前步骤和「停止」 |
| 哨兵 | 点「提交订单」属于 SENSITIVE（`sensitive_words`）：直接在胶囊上「允许一次」/「拒绝」，Android 手机和托管演示里的手机都一样；聊天卡片带着同一个请求 |
| 停下 | 操作器在付款页结束并说明；付款是你的事，在 App 里 |

唯一一个在屏幕上做的案例，因为美团没有个人 API，它的网页版又需要 App 的登录。操作器看到和做过的一切都在轨迹里，每次点按都画在对应的截图上。两个模型分工：聊天模型负责计划和汇报（展示站机器 `.env` 里的 `MAIN_MODEL`；留空时是 `deepseek-v4.1-flash`），手的模型读每张截图、决定点哪里（`qwen3.8-27b`，`GUI_MODEL`）；访客用自己的 OpenRouter key 时，手用的是 `qwen/qwen3.8-27b`。

**轨迹：***待跑*：一台装了美团的 Android 手机（x86 模拟器跑不了它）。执行器、胶囊和「停止」已经在模拟器上验证过，见 [gui.md](gui.md)。

## 写下来了，没有演示 {#documented-not-shown}

另有四个屏幕案例写在 `train-tickets` 和 `phone-messages` 技能里，停在同一个地方；最后一步确认由你来：

- 交管12123：查罚单，付款前停下。
- 滴滴：填好目的地，「呼叫」前停下。
- 12306 App：订票到「提交订单」为止（查票本身已经不需要屏幕了）。
- 京东 App：购物车到「结算」为止。

## 绝不出现在公开材料里 {#never-in-public-material}

你要求的话，智能体可以在手机屏幕上读微信，也会有人这么用。但它不会出现在展示站、网站或影片里，支付宝账单、医保和个税也不会：这些服务要么条款禁止自动化，要么数据不该出现在演示里。

## 读懂留下的痕迹 {#reading-the-trail}

每一步都是聊天里的一行（`12306__get-tickets(…)`、`shell: lark-cli calendar +agenda --as user`、`phone_act: tap "提交订单" at (318,742) in 美团`），每张审批卡片都说明将要做什么、为什么要问。形象下方的 `Activity` 保存着审计日志，记着每次调用走的通道；`Permissions` 显示已有的授权，手机步骤的授权永远只有*一次*。在你自己的服务器上，`nanomuse phone traces` 列出每个手机任务，`nanomuse phone trace <id> -o trace.html` 把其中一个渲染成页面，带操作器看到的每个屏幕和画在上面的每次点按（[gui.md → 轨迹](gui.md#traces)）。[`docs/traces/`](../traces/) 下的 Markdown 轨迹是同样的时间线，渲染成便于阅读的样子。

十一个技能带着这些习惯：`feishu`、`tencent-meeting`、`amap`、`kuaidi100` 和 `train-tickets` 对应上面的服务，`phone-messages` 对应屏幕，`trip-plan`、`meeting-prep`、`inbox-triage`、`compare-options` 和 `weekly-review` 是智能体自己的活。App 里的 `Skills` 列着它们；你自己放一个同名文件夹就能替换掉一个。按 [Agent Skills](https://agentskills.io) 格式为其他智能体写的技能，原样放进 `<data_dir>/skills` 就能用，Larksuite 自己的 `lark-*` 技能也包括在内。
