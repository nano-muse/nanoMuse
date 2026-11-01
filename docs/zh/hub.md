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
- **任务。** `task {text, conversation?, language?, stream?}`：用自然语言描述的一整件事，交给目标设备自己的 Muse，在它自己的一个对话里完成（`conversation` 指定是哪个对话，缺省时用发起方的 id）。`language`（运行时 1.0.0 起，可选）是发起设备界面语言的 BCP-47 标签；目标设备用这个语言作答，而不是从文字里猜。可能要几分钟。那个 Muse 碰到需要审批的事时不会自己拿主意：问题以 `event {stage:"approval"}` 传回来，发起设备显示它惯常的卡片（手机上是 RiskGate，桌面上是终端提示，网页控制台里是一张卡片）。回答以 `approve {approval_id, allow}` 传回去。发起设备可以用 `stop {call}`（它那条 `task` 帧的 id）或 `stop {conversation}`（它指定的对话，没指定时就是它自己的那个按设备分的对话）结束自己发起的任务：目标设备在进行中的一步之后取消运行，回答 `{stopped: true}`，随后那条 `task` 调用本身以 `cancelled` 失败。`{stopped: false}` 表示没有属于发起方的可停之事；一台设备绝不会停掉别的设备发起的任务。运行时、桌面版和手机都这样做。对一个已经在跑任务的对话再发 `task`，会立刻以 `busy` 失败（运行时）：发起方等前一个答完，或者先停掉它，再问一次。超过 hub 时限还没答的任务以 `timeout` 失败，目标那边的 Muse 跑不起来的以 `failed` 失败。任务已经送达对话，但在请求模型前就被拒绝、没有开始执行时，也会以 `failed` 失败，不再返回空答案；发起设备会显示失败说明。nanoMuse 桌面版会在新任务到来时恢复上次任务后被归档的聊天，和打开聊天继续输入一样。`stream: true` 表示发起方把每条 `text` 画在上一个 `tool` 之后那段文字的位置上；nanoMuse 桌面版这时还会发 `text {text, interim, partial: true}`，带着模型正在写的那条消息的文字，最多每 250 毫秒一次，写完的消息照旧发。没有要求的发起方每条消息只收到一次（Android 的 `nanomuse-pc task` 把每条 `text` 列成一步）；运行时暂时忽略 `stream`。

  任务运行期间，目标设备发送 `event` 帧，`body.stage` 告诉发起方该画什么，于是这次运行在发起方的聊天里读起来和在目标设备自己那里一样：工具开始时是 `tool {id, name, summary}`，结束时是 `tool_result {id, name, ok, summary}`（同一个 `id`）；`approval {approval_id, preview, risk, reason, device, timeout, grant_key}`，以及任一方作出决定后的 `approval_result {approval_id, status}`；`text {text, interim}` 是 Muse 一路上说的话；`image` 和 `file` 是它做出来的东西；`error`。`result` 帧带着最终答案。发起方把一条 `text` 画在上一个 `tool` 之后那段文字的位置上，所以目标设备可以把同一条消息越写越长地发好几次，发起方随之显示；每条消息只发一次的目标设备显示效果不变。`grant_key`（1.0.6 起）是发起方记住的回答所覆盖的范围：运行时发的是它自己的授权所用的键（工具和目标，如 `shell:git`），桌面版发的是工具加完整的主参数；没有这个字段的发送方，照旧按 `preview` 的前 60 个字符记，而两个不同的步骤可能开头相同。

- **编程助手。** `coding.agents`、`coding.sessions`、`coding.session`、`coding.send`、`coding.stop`、`coding.runs`：电脑上的 Cursor / Codex / Claude Code 会话，由那里的运行时或桌面版从磁盘读取，并通过这些助手自己的 CLI 来驱动。`coding.send {agent, text, session_id?, workspace?, wait}` 以 `event` 帧把运行过程流式传回（`started`、`text`、`tool`、`done`、`error`，每个都带运行 id，发起方据此可以 `coding.stop`），最后以完成的运行作答。只有电脑会宣告这些动作：装了这个模块的运行时，或者桌面版。[coding-agents.md](coding-agents.md)。

每台设备自己决定允许别人做什么。手机上，「允许其他设备操作这台手机」（*设置 → nanoMuse Cloud → 设备*）关着时，这台手机只回答 `info`，别的一概不答；它仍然能看见并操纵其他设备。运行时这时的 `info` 只报电脑的名字和系统（没有账号名、主目录、工作目录和 shell），动作列表里只有 `info`。开着时，任何*对*这台设备做事的原始动作（`shell`、`files`、`file.get`、`file.put`、`open`、`screen`、`coding.send`、`coding.stop`）都要先经这台设备旁的人同意：惯常的审批卡片，「允许一次」或「对这台设备总是允许」；后一种长期有效的回答是「权限」下的一条授权（`remote_control:<device id>`）。nanoMuse 桌面版默认用同一张卡片询问；它的「免询问远程控制」（设置 → 设备）让账号下的每台设备都能不经卡片在那里做事。旁边没人，卡片过期后发起方听到的是 `not_allowed`。`info` 和 `notify` 从不询问；`task` 在设备自己的哨兵（Sentinel）之下运行，它的卡片照旧传回发起方。一台设备只能 `approve` 发给它的、属于它自己发起的运行的卡片，绝不能回答「是否允许它运行某事」的那张卡片；唯一的例外是电脑自己发出、标了 `any_device` 的卡片（[见下](#a-computer-s-own-cards-on-the-phone)），账号下任何一台设备都能回答。

### 电脑自己的卡片送到手机上 {#a-computer-s-own-cards-on-the-phone}

nanoMuse 桌面版上的定时任务运行时，电脑旁边可能没人，所以这次运行的审批卡片也会送到账号下的手机上。这种卡片背后没有调用，所以作为推送发出（中继 0.31，见[帧](#frames)）：电脑只在 `welcome.server.features` 列出 `event_push` 时才发，中继只转给在 `hello` 里声明了 `approve.any` 的设备（Android 和 iPhone 的 App）。推送的就只有这些：有人正在电脑上或网页控制台里聊着的那条会话，它的卡片留在发问的地方（人就在那里）；别的设备发来的任务里的卡片，顺着那次调用回到发起的设备（见[上文](#what-you-can-say)）；Python 运行时（`nanomuse serve`）目前不推送，它的定时任务的卡片留在网页版里等着（[#704](https://github.com/nano-muse/nanoMuse/issues/704)）：

```
→ event {to:"*", body:{stage:"approval", approval_id, preview, preview_zh, reason, app,
                      task:{id, title}, chat, scopes:["once", "schedule"?], timeout, device,
                      any_device:true}}
← call  {action:"approve", args:{approval_id, allow, scope?:"once" | "schedule"}}   （发给电脑）
→ event {to:"*", body:{stage:"approval_result", approval_id, status, by?:{id, name}}}
```

`preview` 和 `preview_zh` 分别用英文和中文说明这一步要做什么（手机按自己的语言挑一个），`app` 是手要操作的应用，`task` 和 `chat` 是任务和它所在的对话，`device` 是那台电脑，`timeout` 是手机上卡片显示的秒数（600）。`scopes` 列出卡片除了「拒绝」之外还能给的回答：`schedule`（「此定时任务中始终允许」）只出现在只有一个任务的运行里、手的一步上；这条授权记在电脑上，从不记在手机上。`any_device` 表示账号下任何一台设备都能回答：这张卡片的 `approve` 电脑收哪台设备先发来的都算，而别的卡片只有发起那次运行的设备能答。电脑上或任何一部手机上先给出的回答算数；随后电脑推送 `approval_result`，带上 `status`（`approved`、`denied`，运行放弃了这张卡片时是 `cancelled`）和 `by`（是哪台设备答的），手机收起卡片。手机上没人及时回答时，只收起自己的卡片，什么也不发，电脑上的卡片继续等。命中支付类敏感词的卡片也会送过去：声明 `approve.any` 的只有手机，手机在锁屏之后才能回答。这件事不会在手机上运行任何东西，所以「允许其他设备操作这台手机」关着时卡片也照样显示。在后台时，Android 把卡片显示成一条通知；iOS 在 hub 连接还开着时发一条通知。

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
→ hello    {device:{id,name,kind,os,version,actions[],llm?}}   kind: phone | computer | web
           llm（中继 0.28，可选）：{provider, model}，这台设备跑模型所用的标识（"cloud"、"openrouter"、某个模型 id）；
           只收纯标识，key 和 URL 一律丢弃；记在设备行上，供运营者查看
← welcome  {device_id, devices:[…], server:{version,frame_limit,time,features?}}   features (relay 0.31): ["event_push"]
← devices  {devices:[{id,name,kind,os,version,actions[],online,last_seen,controllable,ip}]}

→ call     {id, to, action, args}
← call     {id, from:{id,name,kind}, action, args}          (delivered to the target)
→ event    {id, body}          ← event  {id, from, body}    progress, approvals, images
→ event    {to, body}          ← event  {from, body}        no id: a push to a device or "*" (relay 0.31, below)
→ result   {id, ok, body | error, message}                  ← result (to the caller)
← error    {code, message, id?}   device_offline · not_controllable · self_call · duplicate_call · unknown_call · timeout
                                  too_large · rate_limited · bad_frame · device_online · bad_key · bad_device

→ devices  {}        → rename {name}        → forget {device_id}        → ping  ← pong
← profile  {rev, device}       the account's name, look or connectors changed (PUT /v1/me/profile); fetch it
← sync     {what:"conversations", cursor, from}   another device pushed or deleted synced conversations; pull /v1/sync/changes
← working  {cid, from, device_name, working, at, state?, detail?}  another device started (true) or finished (false) a turn in that synced conversation; on a true, since relay 0.31, what it is doing (`state`: working | waiting; `detail`: the step, up to 160 characters)
```

关闭码：`4000` 期待 hello（15 秒内没有 hello，或第一帧不是 hello，二进制帧也算）、`4001` key 无效（原因 `bad_key` 或 `account_deleted`；账号在连接期间被删除或停用时为 `account_gone`；从中继 0.25.0 起，连接期间 key 刚被吊销时也会收到 `bad_key`：另一台设备点了「在所有设备上退出」、在账号页退出了这个登录，或这台设备自己退出登录，这样丢失的手机会立刻断线，其他设备看到它离线）、`4002` 设备无效、`4003` 被同一设备 id 的更新连接顶替，或者，带原因 `hub_paused`（中继 0.22）时，是运营者关掉了 hub 或整个服务：客户端应等一会儿再重连，而不是立刻重试（[cloud.md › 控制](cloud.md#controls)）；`4008` 帧太多（无视了下面的限速），或者带原因 `too_many_connections`（中继 0.30）时是连接太多：同一个地址一分钟内开了 60 条以上，或者这个账号已经有 32 台设备在线（同一台设备重新顶替自己的位置不算），以及 `4009` 读得太慢（这条连接上已经积压了 512 帧或 32 MB 而对方一直不读；客户端像遇到任何网络断开一样退避重连）。发往某台设备的帧从不等那台设备：每条连接各有一个队列，按顺序随 socket 排空写出；一部卡住的手机不会拖住正在呼叫它的电脑。

`Authorization` 头里的 key 被拒时，处理方式与 `hello` 里的 key 被拒一致：握手完成，先发一个带 code 的 `error` 帧，再以 `4001` 关闭。客户端看到 `4001` 或 `4002` 就离开退避重连，把 hub 显示为「被拒绝」并请人重新登录（运行时仍每分钟试一次，这样在中继上恢复的 key 不用重启也能接回来）；其他关闭都视为网络问题，按退避重试。网络已经断了而 socket 还开着（笔记本睡过一觉、换了 Wi-Fi）时收不到 `pong`：运行时的客户端用协议自带的 ping，超时 20 秒；桌面版的客户端在两个 `ping` 帧之间什么都没收到（约 50 秒）就丢掉这条 socket，照样退避重连。

中继 0.31 起，`event` 也可以不带 `id` 发出：这是一次推送，不是某个调用的进度。电脑用它发自己的审批卡片（这种卡片背后没有调用），以及「这张卡片已经有人答了」。`to` 是一台设备的 id，或 `"*"` 表示账号下所有设备；两种情况下中继都只转给在 `hello` 里声明了 `approve.any` 的设备，不回发给发送方，所以发送方不用自己维护名单，旧版 App 也收不到。只放行 `approval` 和 `approval_result` 两种 stage，其他的丢掉并记日志。一台设备每分钟最多推 30 条（超过回 `rate_limited`），每条 `body` 最多 16 KB（超过回 `too_large`）。支持这件事的中继在 `welcome.server.features` 里列出 `event_push`；客户端看到它才推送，所以旧中继收不到推送。

中继不认识的帧（没有处理器的 `type`、不是 JSON 对象的文本帧、二进制帧）都回 `error bad_frame`，连接保持打开，所以新客户端对着旧中继只会丢一帧，不会掉线。超过 `frame_limit` 的帧回 `too_large`；每秒超过 60 帧或 8 MB 回 `rate_limited`（每秒最多提醒一次，多出的帧被丢弃），持续下去则以 `4008` 关闭。15 分钟内没人应答的 `call` 向发起方回 `timeout`（中继在有 call 或 `ping` 到达时检查，所以一个会 ping 的发起方在期限过后一分钟内就能听到）；对当前在线的设备发 `forget` 会被拒绝，回 `device_online`。

设备 id 按安装生成（`phone-…`、`pc-…`）；名字是给人看的，可以在设备上改。`web` 设备从不作为目标，也不会被记住。`file.get`、`file.put` 和 `screen` 的正文以 base64 携带字节（`data`）并附 `mime`；桌面拒绝超过 8 MB 的文件，中继拒绝超过 `HUB_FRAME_LIMIT` 的帧。

Python 运行时的 `files` 动作最多返回 2,000 个目录条目。还有更多可读条目时，结果会附带
`truncated: true` 和 `total`，后者是逐项读取之前在目录中看到的名称总数。读取前消失或
无法读取的条目可能被跳过。恰好达到上限的完整列表不会标记为截断。这两个字段是可选的
新增字段，客户端仍需接受不含它们的旧响应。

从中继 0.27 起，一份凭据只属于一个 Hub 身份。凭据签发时可以用 `device_id` 和
`device_kind` 固定 `device.id` 与 `device.kind`（`POST /v1/auth/verify` 和 `/login`）；
签发时没带的凭据，则在第一次通过的 `hello` 时登记。同一份凭据重连仍会顶替自己的旧
套接字，改报其他 id 或类型会得到 `bad_device`。一个仍有效的 key 持有的 id，只有更晚
一次验证码或密码登录签发的 key 才能接手（手机没退出就又登录了一次、运行时的保险库
重置了、退出登录没传到中继）：旧 key 仍能打开账号，但不再代表这台设备。吊销或过期
的 key 会释放它的 id。session key（`/v1/auth/session-key`，nanoMuse Web 的容器）只能
登记没人持有的 id，从不接手别人的。现有客户端保留原 key，下次连接时登记；登录时
带上身份的客户端在登录时就绑定。

智能体的名字和形象属于账号，不属于某台设备：中继上的 `GET` / `PUT /v1/me/profile` 保存它们（小龙、某个颜色底上的 emoji，或者形象工作室里画的一张形象及其五张小图），后写的胜出，一个 `profile` 帧通知其他设备去取新的 `rev`。运行时在 `nanomuse/hub/profile.py` 里做这件事，手机在 `io.github.nanomuse.cloud.ProfileSync` 里做；写入的那台设备会跳过自己的回声。

同一份 profile 还带着**哪台设备连接了什么**（0.1.34）：一个 `connectors` 列表，每一项有连接器的 id 和标签、有地址的话还有地址、登录方式（`oauth`、`key` 或 `open`）、设备的名字和 id、是否启用，以及时间。一台设备只写自己持有的那些项；中继保留其他设备的项，列表上限 64 项，并拒绝任何带有 token、secret、key、authorization 或 password 字段的项；凭据绝不离开登录它的那台设备。其他设备在连接器目录下把这些项列为「已在 \<device\> 上连接，在这里登录即可在这台设备上使用」，照常的本地登录就是对应的操作。

中继 0.29 起，profile 还可以指明画出来的形象的**短视频**：做了动画的那台设备把每段短视频作为文件传上去（`PUT /v1/blobs/{sha256}`，见 [cloud.md](cloud.md#the-record)），写入 `clips: {mood: {sha256, mime, bytes}}`；其他设备收到同一个 `profile` 帧后，从 `GET /v1/blobs/{sha256}` 下载短视频，不用各自再渲染。短视频随形象走：`clips: null`、换成别的形象或 `DELETE /v1/me/profile` 都会清掉。1.0.6 及更早的 App 忽略这个字段。

0.1.36 起，**对话**也会跟着走，但走的是另一条路：它们的文本经 REST（`/v1/sync/*`，[cloud.md](cloud.md#conversation-sync)）进入中继的同步存储，hub 只负责捎个信。中继接受了一次推送之后，或者一次删除之后，账号的每一条*其他*套接字都会收到 `sync {what:"conversations", cursor, from}`（`cursor` 是变更后账号的计数器，`from` 是做出变更的设备 id），然后从自己的游标开始拉取新内容。在 `from` 里看到自己 id 的设备忽略这一帧。0.1.38 起（中继 0.20），hub 还带着**谁在回答**：一台设备在某个同步对话里开始或结束一轮时，会 POST `/v1/sync/working`，其他套接字收到 `working {cid, from, device_name, working, at}`；各个 App 在最后一条消息下面显示「kwai 正在处理…」，直到 `working: false` 到来、回复本身到达，或者过了十分钟。中继 0.31 起，`working: true` 还会说这一轮在做什么：`state` 是 `working` 或 `waiting`（停在一张卡片上等人），`detail` 是这一步自己的话，最多 160 个字符，于是那一行读作「kwai 正在处理：打开订票网站」或「kwai 在等你确认」。没带这两个字段的设备照旧显示为正在处理；不认识它们的客户端忽略即可。中继只在内存里保留这些。默认只同步主要聊天；旁聊只在打开了「同时同步旁聊」的设备之间来往。其他什么都不同步：key、服务商和设置留在输入它们的地方，文件和图片留在生成它们的设备上。各个 App 怎么用它，见 [every-device.md](every-device.md#the-same-conversations-everywhere)。

## 代码 {#the-code}

各设备的 App 怎样围绕这些帧搭起来（设备页、发给某台设备的旁聊、两端都能回答的审批、电脑自己的手），在 [every-device.md](every-device.md) 里。

- 中继：[`cloud/nanomuse_cloud/hub.py`](../../cloud/nanomuse_cloud/hub.py)：按账号的注册表、路由、`GET /v1/devices`、`DELETE /v1/devices/{id}`；控制台在 [`cloud/nanomuse_cloud/console/`](../../cloud/nanomuse_cloud/console/) 下。
- Android：`io.github.nanomuse.hub`：`HubClient`（OkHttp，重连）、`Hub`（状态、偏好、`call`/`find`）、`HubActions`（手机替别人做的事，包括通过无界面聊天运行器执行的 `task`，其 `language` 会被遵守）、`HubService`（前台服务，`remoteMessaging`）。`nanomuse-pc`（`io.github.nanomuse.reach`）从手机的沙箱 shell 访问 hub 上的设备。
- nanoMuse 桌面版：[`harness/dsh-nanomuse/src/hub.ts`](../../harness/dsh-nanomuse/src/hub.ts)（套接字、重连）、[`harness/dsh-nanomuse/src/actions.ts`](../../harness/dsh-nanomuse/src/actions.ts)（这台电脑替别人做的事，远程动作之前的那张卡片）；见 [desktop.md](desktop.md)。
- iOS：[`NanoMuse/NanoMuseHub.swift`](../../android/src/ios/NanoMuse/NanoMuseHub.swift)：`info`、`open`、`notify`、`task`（它的 `language` 会被遵守）、`stop`；`screen` 以 `no_screen` 拒绝，shell 和文件类动作以 `not_supported` 拒绝。`task` 里需要批准的一步不会作为 `event` 发回去：nanoMuse 在前台时手机显示自己的卡片，在后台时这一步被拒绝，回答里会说明。反过来，手机发出的 `task`（`@〈设备〉`，[`NanoMuseDeviceMention.swift`](../../android/src/ios/NanoMuse/NanoMuseDeviceMention.swift)）收到的 `approval` 事件在手机的卡片上回答（[`NanoMuseRemoteApproval.swift`](../../android/src/ios/NanoMuse/NanoMuseRemoteApproval.swift)），`approve` 发回去；`approval_result` 关掉卡片。电脑推送的卡片（[见上](#a-computer-s-own-cards-on-the-phone)）也落在同一张卡片上，可以选「允许一次」「此定时任务中始终允许」或「拒绝」。那台设备干活的时候回复就在画（[`NanoMuseDeviceReply.swift`](../../android/src/ios/NanoMuse/NanoMuseDeviceReply.swift)）：`tool`/`tool_result` 是步骤胶囊，`text` 来一段显示一段；聊天里的停止按钮发 `stop {call}`。
- 运行时（`nanomuse serve`）：[`nanomuse/cloud.py`](../../nanomuse/cloud.py)（账号）、[`nanomuse/hub/client.py`](../../nanomuse/hub/client.py)（套接字、重连）、[`nanomuse/hub/actions.py`](../../nanomuse/hub/actions.py)（这台电脑替别人做的事）、[`nanomuse/hub/service.py`](../../nanomuse/hub/service.py)（收到的 `task` 放进一个可见的旁聊，`tool`/`tool_result`/`approval`/`approval_result` 各阶段双向传递，设备线程）、[`nanomuse/tools/devices.py`](../../nanomuse/tools/devices.py)（`devices`、`device_*`、`delegate`）；`/api/cloud/*` 和 `/api/hub/*` 在 [`nanomuse/server/api.py`](../../nanomuse/server/api.py)。测试：`tests/test_hub.py`，用一个假中继。
- 网页版：`DevicesScreen`、设备聊天和转发过来的审批卡片，在 [`web/src/`](../../web/src/)；见 [every-device.md](every-device.md)。

## 信任 {#trust}

中继用绑定了设备 id 和类型的凭据验证每一条套接字，并且只在账号内部路由；它存设备名和最后在线时间，不存问了什么。一台设备只回答自己账号的设备，而且只在它的「远程控制」开关开着时，对于任何会在那里运行、读取或写入的事，还要那台设备旁的人同意过（一次，或对发起设备总是允许）。命令在输入它的地方判定，然后才发出；远端 Muse 的审批由发起的人回答，绝不由另一个 Muse 回答。在一台设备上退出登录会在中继吊销那台设备的 key，并把它从 hub 上摘下来；手机和控制台的「设备」列表显示所有登录过的设备，所以你不认识的设备是看得见的，等它离线后「移除」就能把它去掉。
