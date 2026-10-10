# hub：每台设备都是一个 Muse

在手机、电脑和浏览器上登录同一个 nanoMuse Cloud 账号，它们就能看见彼此。每台设备跑着自己的 Muse，带着自己的手（手机上的 App 和沙箱，电脑上的 shell 和屏幕），其中任何一台都可以从任何网络拜托任何另一台做点什么。网页控制台自己没有手；它是通往其余设备的前门。

```
phone ──┐                         ┌── computer (nanoMuse Desktop)
        ├──▶  nanoMuse Cloud  ◀───┤
web  ───┘        /v1/hub          └── another phone / computer
```

每台设备向中继开一条出站的 WebSocket 并一直保持。设备上不监听任何东西，不需要端口转发，也不需要同一个 Wi-Fi；中继只在一个账号的设备之间转发帧，从不看任务里面是什么。添加一台电脑就是这么做的：在上面装 nanoMuse Desktop，用同一个账号登录，不用手动下载什么，也不用输什么码。这也是唯一的入口：那个通过局域网配对的独立主机脚本（0.1.13–0.1.23）已经去掉了，所以手机列表里缺了一台电脑，几乎总是因为它登录的是另一个账号；手机上的 *设置 → 电脑* 显示手机用的是哪个账号。

## 你可以说什么 {#what-you-can-say}

在手机上，任何聊天里：

- 「在我 Mac 上列一下下载文件夹」：`nanomuse-pc ls ~/Downloads --on mac`
- 「让电脑把项目编译一遍，把日志发给我」：`nanomuse-pc task "…" --on desk`
- 「电脑截个图给我看」：`nanomuse-pc screen --on desk`

在电脑上，nanoMuse 桌面版里（或终端里的 `nanomuse chat`）：

- 「在我手机上截个图」：`device_screen`
- 「让手机的 Muse 把最后一条通知读给我」：`delegate`
- 「给手机发个通知：晚饭好了」：`device_notify`

在网页控制台（`/app`）里：选一台设备，打字。任务在那台设备的 Muse 上跑；审批以卡片的形式显示在页面里。

hub 上传递两类请求：

- **动作。** `info`、`shell`、`files`、`file.get`、`file.put`、`open`、`screen`、`notify`。原始、即时。一条 `shell` 命令在发出之前先在*发起方*判定，用的和本地命令同一套阶梯（手机的 ShellGuard、桌面的 `guard.py`）：读取和构建静默放行，删除 / 发送 / 付款 / 系统命令则等发起设备上的审批卡片。
- **任务。** `task {text, conversation?, language?}`：用自然语言描述的一整件事，交给目标设备自己的 Muse，在它自己的一个对话里完成（`conversation` 指定是哪个对话，缺省时用发起方的 id）。`language`（运行时 1.0.0 起，可选）是发起设备界面语言的 BCP-47 标签；目标设备用这个语言作答，而不是从文字里猜。可能要几分钟。那个 Muse 碰到需要审批的事时不会自己拿主意：问题以 `event {stage:"approval"}` 传回来，发起设备显示它惯常的卡片（手机上是 RiskGate，桌面上是终端提示，网页控制台里是一张卡片）。回答以 `approve {approval_id, allow}` 传回去。发起设备可以用 `stop {call}`（它那条 `task` 帧的 id）或 `stop {conversation}`（它指定的对话，没指定时就是它自己的那个按设备分的对话）结束自己发起的任务：目标设备在进行中的一步之后取消运行，回答 `{stopped: true}`，随后那条 `task` 调用本身以 `cancelled` 失败。`{stopped: false}` 表示没有属于发起方的可停之事；一台设备绝不会停掉别的设备发起的任务。运行时、桌面版和手机都这样做。

  任务运行期间，目标设备发送 `event` 帧，`body.stage` 告诉发起方该画什么，于是这次运行在发起方的聊天里读起来和在目标设备自己那里一样：工具开始时是 `tool {id, name, summary}`，结束时是 `tool_result {id, name, ok, summary}`（同一个 `id`）；`approval {approval_id, preview, risk, reason, device, timeout}`，以及任一方作出决定后的 `approval_result {approval_id, status}`；`text {text, interim}` 是 Muse 一路上说的话；`image` 和 `file` 是它做出来的东西；`error`。`result` 帧带着最终答案。

- **编程助手。** `coding.agents`、`coding.sessions`、`coding.session`、`coding.send`、`coding.stop`、`coding.runs`：电脑上的 Cursor / Codex / Claude Code 会话，由那里的运行时或桌面版从磁盘读取，并通过这些助手自己的 CLI 来驱动。`coding.send {agent, text, session_id?, workspace?, wait}` 以 `event` 帧把运行过程流式传回（`started`、`text`、`tool`、`done`、`error`，每个都带运行 id，发起方据此可以 `coding.stop`），最后以完成的运行作答。只有电脑会宣告这些动作：装了这个模块的运行时，或者桌面版。[coding-agents.md](coding-agents.md)。

每台设备自己决定允许别人做什么。手机上，「允许其他设备操作这台手机」（*设置 → nanoMuse Cloud → 设备*）关着时，这台手机只回答 `info`，别的一概不答；它仍然能看见并操纵其他设备。开着时，任何*对*这台设备做事的原始动作（`shell`、`files`、`file.get`、`file.put`、`open`、`screen`、`coding.send`、`coding.stop`）都要先经这台设备旁的人同意：惯常的审批卡片，「允许一次」或「对这台设备总是允许」；后一种长期有效的回答是「权限」下的一条授权（`remote_control:<device id>`）。nanoMuse 桌面版默认用同一张卡片询问；它的「免询问远程控制」（设置 → 设备）让账号下的每台设备都能不经卡片在那里做事。旁边没人，卡片过期后发起方听到的是 `not_allowed`。`info` 和 `notify` 从不询问；`task` 在设备自己的哨兵（Sentinel）之下运行，它的卡片照旧传回发起方。一台设备只能 `approve` 发给它的、属于它自己发起的运行的卡片，绝不能回答「是否允许它运行某事」的那张卡片。

### 提案 `proxy_fetch`：手机借用电脑的网络 {#proposed-proxy-fetch-the-phone-uses-the-computer-s-connection}

还没做；先写在这里，让三个实现在有人动手之前先取得一致。场景：手机的网络连不上 `chatgpt.com` 或某个服务商的主机（[own-key.md](own-key.md#when-the-provider-cannot-be-reached) 里的那张卡片），而这个人的电脑连得上。电脑的运行时通过 hub 转发那次服务商调用（只转发那个），像代理一样。

```
→ call   {id, to, action:"proxy_fetch",
          args:{method, url, headers:{…}, body?, stream?}}     body base64; stream: want SSE chunks as events
← event  {id, from, body:{stage:"headers", status, headers:{…}}}
← event  {id, from, body:{stage:"chunk", data}}                data base64; one per SSE chunk when stream is true
← result {id, ok:true, body:{status, headers:{…}, data?}}      data base64 when stream was false
← result {id, ok:false, error:"not_allowed" | "host_refused" | "too_large" | "upstream", message}
```

让它可以接受的几条规则，每条在提供服务的一方都是一行代码：

- **电脑上主动开启。** 桌面插件只在「让我的手机借用这台电脑的网络访问服务商」打开时（*设置 → 设备*）才在 `hello` 里宣告 `proxy_fetch`；关着时，这个动作是 `unknown_call`。信任级别和 `device_shell` 相同：这台设备的「远程控制」必须开着，某台设备的第一次调用会弹出惯常的卡片，「允许一次」或「对这台设备总是允许」（一条 `remote_control:<device id>` 授权）。
- **只到指定主机，不是整个互联网。** 电脑只向服务商目录（`providers.json`）里的主机、`chatgpt.com` 和 `auth.openai.com`，以及它自己配置的服务商的自定义 base URL 转发；其余一律 `host_refused`。绝不转发到中继、局域网地址或 `file:`。
- **请求头照传，秘密不留。** 手机发送自己的 `Authorization`（套餐的 token、它自己的 key）；电脑原样转发，只记录主机、状态码和大小，从不记录请求头或正文。
- **有上限。** 请求正文超过 8 MB、响应单帧超过 `HUB_FRAME_LIMIT` 都是 `too_large`；流在十分钟处切断；每台发起设备同一时间只有一个调用。
- **手机来选。** 「连不上」的那张卡片只在有一台宣告了 `proxy_fetch` 的电脑在线时才提供「用我电脑的网络」这个选项；这个选择按服务商实例保存，并在实例上显示为一行，免得有人忘了自己的 key 要经过电脑。

为什么这次只是设计而不是代码：hub 帧本身很小，但提供服务的一方是电脑上一个新的信任面（一个携带这个人服务商 token 的转发器），而手机的两套 HTTP 栈各自都需要一个传输层，把请求变成帧、再把帧还原成响应：三个实现，加上第四处必须对主机列表取得一致的地方，这一轮的预算老实说盖不住。在此期间，代理设置（[own-key.md](own-key.md#when-the-provider-cannot-be-reached)）覆盖了常见情形：电脑上开一个代理（Clash、一条 `ssh -D`），手机指向它。

## 帧 {#frames}

`WS /v1/hub` 上的 JSON 文本帧，`Authorization: Bearer nm_…`（浏览器则把 key 放在 `hello` 里）。

```
→ hello    {device:{id,name,kind,os,version,actions[]}}     kind: phone | computer | web
← welcome  {device_id, devices:[…], server:{version,frame_limit,time}}
← devices  {devices:[{id,name,kind,os,version,actions[],online,last_seen,controllable,ip}]}

→ call     {id, to, action, args}
← call     {id, from:{id,name,kind}, action, args}          (delivered to the target)
→ event    {id, body}          ← event  {id, from, body}    progress, approvals, images
→ result   {id, ok, body | error, message}                  ← result (to the caller)
← error    {code, message, id?}   device_offline · not_controllable · self_call · unknown_call · timeout
                                  too_large · rate_limited · bad_frame · device_online · bad_key · bad_device

→ devices  {}        → rename {name}        → forget {device_id}        → ping  ← pong
← profile  {rev, device}       the account's name, look or connectors changed (PUT /v1/me/profile); fetch it
← sync     {what:"conversations", cursor, from}   another device pushed or deleted synced conversations; pull /v1/sync/changes
← working  {cid, from, device_name, working, at}  another device started (true) or finished (false) a turn in that synced conversation
```

关闭码：`4000` 期待 hello（15 秒内没有 hello，或第一帧不是 hello，二进制帧也算）、`4001` key 无效（原因 `bad_key` 或 `account_deleted`；账号在连接期间被删除或停用时为 `account_gone`）、`4002` 设备无效、`4003` 被同一设备 id 的更新连接顶替，或者，带原因 `hub_paused`（中继 0.22）时，是运营者关掉了 hub 或整个服务：客户端应等一会儿再重连，而不是立刻重试（[cloud.md › 控制](cloud.md#controls)）；`4008` 帧太多（无视了下面的限速），以及 `4009` 读得太慢（这条连接上已经积压了 512 帧或 32 MB 而对方一直不读；客户端像遇到任何网络断开一样退避重连）。发往某台设备的帧从不等那台设备：每条连接各有一个队列，按顺序随 socket 排空写出；一部卡住的手机不会拖住正在呼叫它的电脑。

`Authorization` 头里的 key 被拒时，处理方式与 `hello` 里的 key 被拒一致：握手完成，先发一个带 code 的 `error` 帧，再以 `4001` 关闭。客户端看到 `4001` 或 `4002` 就离开退避重连，把 hub 显示为「被拒绝」并请人重新登录（运行时仍每分钟试一次，这样在中继上恢复的 key 不用重启也能接回来）；其他关闭都视为网络问题，按退避重试。

中继不认识的帧（没有处理器的 `type`、不是 JSON 对象的文本帧、二进制帧）都回 `error bad_frame`，连接保持打开，所以新客户端对着旧中继只会丢一帧，不会掉线。超过 `frame_limit` 的帧回 `too_large`；每秒超过 60 帧或 8 MB 回 `rate_limited`（每秒最多提醒一次，多出的帧被丢弃），持续下去则以 `4008` 关闭。15 分钟内没人应答的 `call` 向发起方回 `timeout`（中继在有 call 或 `ping` 到达时检查，所以一个会 ping 的发起方在期限过后一分钟内就能听到）；对当前在线的设备发 `forget` 会被拒绝，回 `device_online`。

设备 id 按安装生成（`phone-…`、`pc-…`）；名字是给人看的，可以在设备上改。`web` 设备从不作为目标，也不会被记住。`file.get`、`file.put` 和 `screen` 的正文以 base64 携带字节（`data`）并附 `mime`；桌面拒绝超过 8 MB 的文件，中继拒绝超过 `HUB_FRAME_LIMIT` 的帧。

智能体的名字和形象属于账号，不属于某台设备：中继上的 `GET` / `PUT /v1/me/profile` 保存它们（小龙、某个颜色底上的 emoji，或者形象工作室里画的一张形象及其五张小图），后写的胜出，一个 `profile` 帧通知其他设备去取新的 `rev`。运行时在 `nanomuse/hub/profile.py` 里做这件事，手机在 `io.github.nanomuse.cloud.ProfileSync` 里做；写入的那台设备会跳过自己的回声。

同一份 profile 还带着**哪台设备连接了什么**（0.1.34）：一个 `connectors` 列表，每一项有连接器的 id 和标签、有地址的话还有地址、登录方式（`oauth`、`key` 或 `open`）、设备的名字和 id、是否启用，以及时间。一台设备只写自己持有的那些项；中继保留其他设备的项，列表上限 64 项，并拒绝任何带有 token、secret、key、authorization 或 password 字段的项；凭据绝不离开登录它的那台设备。其他设备在连接器目录下把这些项列为「已在 \<device\> 上连接，在这里登录即可在这台设备上使用」，照常的本地登录就是对应的操作。

0.1.36 起，**对话**也会跟着走，但走的是另一条路：它们的文本经 REST（`/v1/sync/*`，[cloud.md](cloud.md#conversation-sync)）进入中继的同步存储，hub 只负责捎个信。中继接受了一次推送之后，或者一次删除之后，账号的每一条*其他*套接字都会收到 `sync {what:"conversations", cursor, from}`（`cursor` 是变更后账号的计数器，`from` 是做出变更的设备 id），然后从自己的游标开始拉取新内容。在 `from` 里看到自己 id 的设备忽略这一帧。0.1.38 起（中继 0.20），hub 还带着**谁在回答**：一台设备在某个同步对话里开始或结束一轮时，会 POST `/v1/sync/working`，其他套接字收到 `working {cid, from, device_name, working, at}`；各个 App 在最后一条消息下面显示「kwai 正在处理…」，直到 `working: false` 到来、回复本身到达，或者过了十分钟。中继只在内存里保留这些。默认只同步主要聊天；旁聊只在打开了「同时同步旁聊」的设备之间来往。其他什么都不同步：key、服务商和设置留在输入它们的地方，文件和图片留在生成它们的设备上。各个 App 怎么用它，见 [every-device.md](every-device.md#the-same-conversations-everywhere)。

## 代码 {#the-code}

各设备的 App 怎样围绕这些帧搭起来（设备页、发给某台设备的旁聊、两端都能回答的审批、电脑自己的手），在 [every-device.md](every-device.md) 里。

- 中继：[`cloud/nanomuse_cloud/hub.py`](../../cloud/nanomuse_cloud/hub.py)：按账号的注册表、路由、`GET /v1/devices`、`DELETE /v1/devices/{id}`；控制台在 [`cloud/nanomuse_cloud/console/`](../../cloud/nanomuse_cloud/console/) 下。
- Android：`io.github.nanomuse.hub`：`HubClient`（OkHttp，重连）、`Hub`（状态、偏好、`call`/`find`）、`HubActions`（手机替别人做的事，包括通过无界面聊天运行器执行的 `task`）、`HubService`（前台服务，`remoteMessaging`）。`nanomuse-pc`（`io.github.nanomuse.reach`）从手机的沙箱 shell 访问 hub 上的设备。
- nanoMuse 桌面版：[`harness/dsh-nanomuse/src/hub.ts`](../../harness/dsh-nanomuse/src/hub.ts)（套接字、重连）、[`harness/dsh-nanomuse/src/actions.ts`](../../harness/dsh-nanomuse/src/actions.ts)（这台电脑替别人做的事，远程动作之前的那张卡片）；见 [desktop.md](desktop.md)。
- iOS：[`NanoMuse/NanoMuseHub.swift`](../../android/src/ios/NanoMuse/NanoMuseHub.swift)：`info`、`open`、`notify`、`task`（它的 `language` 会被遵守）、`stop`；`screen` 以 `no_screen` 拒绝，shell 和文件类动作以 `not_supported` 拒绝。`task` 里需要批准的一步不会作为 `event` 发回去：nanoMuse 在前台时手机显示自己的卡片，在后台时这一步被拒绝，回答里会说明。
- 运行时（`nanomuse serve`）：[`nanomuse/cloud.py`](../../nanomuse/cloud.py)（账号）、[`nanomuse/hub/client.py`](../../nanomuse/hub/client.py)（套接字、重连）、[`nanomuse/hub/actions.py`](../../nanomuse/hub/actions.py)（这台电脑替别人做的事）、[`nanomuse/hub/service.py`](../../nanomuse/hub/service.py)（收到的 `task` 放进一个可见的旁聊，`tool`/`tool_result`/`approval`/`approval_result` 各阶段双向传递，设备线程）、[`nanomuse/tools/devices.py`](../../nanomuse/tools/devices.py)（`devices`、`device_*`、`delegate`）；`/api/cloud/*` 和 `/api/hub/*` 在 [`nanomuse/server/api.py`](../../nanomuse/server/api.py)。测试：`tests/test_hub.py`，用一个假中继。
- 网页版：`DevicesScreen`、设备聊天和转发过来的审批卡片，在 [`web/src/`](../../web/src/)；见 [every-device.md](every-device.md)。

## 信任 {#trust}

中继用账号 key 验证每一条套接字，并且只在账号内部路由；它存设备名和最后在线时间，不存问了什么。一台设备只回答自己账号的设备，而且只在它的「远程控制」开关开着时，对于任何会在那里运行、读取或写入的事，还要那台设备旁的人同意过（一次，或对发起设备总是允许）。命令在输入它的地方判定，然后才发出；远端 Muse 的审批由发起的人回答，绝不由另一个 Muse 回答。在一台设备上退出登录会在中继吊销那台设备的 key，并把它从 hub 上摘下来；手机和控制台的「设备」列表显示所有登录过的设备，所以你不认识的设备是看得见的，等它离线后「移除」就能把它去掉。
