# hub：让各台设备协作 {#hub-每台设备都是一个-muse}

## 固定在设备上的对话 {#persistent-device-conversations}

#815 原型可从 Android 和桌面版的「新建对话」或「设备」页面创建独立对话。按稳定的设备 ID 选择目标，在线状态会单独显示。设备离线或不支持持久任务时仍可创建对话并保存草稿；设备重新连接且支持 `task.status` 后才能发送。不会改为本机执行，也不会自动重发。每条对话保存设备 ID 和独立的对话 UUID。目标设备使用本机模型和工具执行，发起设备在本地保留记录，无需开启侧聊同步。

桌面版为每个设备对话分别保留草稿，切换聊天不会混用。发送请求尚未返回时继续编辑的文字，会在请求返回后保留在输入框中。草稿按输入顺序保存，发送结果只会清除已经发送的那份草稿；Android 也会保留旧请求完成前新保存的草稿。

消息开头提及设备时，这一轮使用独立会话，并显示临时选中的目标。设备重名时可输入 `@设备名 [设备ID] 消息`。下一条普通消息仍会发往绑定的设备。

首轮通过 `task {text, conversation, turn_id, new_conversation: true, stream: true}` 发送。后续保留 `conversation`，每轮生成新的 `turn_id`，并设置 `new_conversation: false`。已绑定的会话不存在时返回 `context_lost`，只有首轮可以创建绑定。没有 `turn_id` 的请求沿用原有行为。

如果目标在接收前明确拒绝调用，例如返回 `no_model` 或 `denied`，首轮尚未绑定会话。修正配置后，可以用新的轮次 ID 和 `new_conversation: true` 再次发送。已接收轮次返回的结果，包括 `failed`，以及送达未确定的情况，都不允许重新创建上下文。

目标设备先保存会话绑定和本轮记录，再发送 `event {stage: "accepted", turn_id}` 并执行。绑定按已验证的账号和发起设备隔离。发起端也先保存记录再发送。同一轮重复到达时只返回已记录的状态，同一对话有任务正在执行时，新的一轮返回 `busy`。

断线后用新的 Hub 调用查询 `task.status {conversation, turn_id}`。状态包括 `accepted`、`completed`、`failed`、`cancelled`、`interrupted` 和 `unknown`。完成结果包含 `text`，失败包含 `error`，有说明时还包含 `message`。执行中的结果可带近期进度和未过期审批的 `events` 快照。发起端替换快照，并按轮次 ID 保存最终回复。

查不到记录表示送达情况未确定。目标设备重启后，已接收但没有最终记录的任务显示为中断，部分操作可能已经执行。恢复时不重发。使用 `stop {conversation, turn_id}` 请求停止指定轮次，`stopped` 表示请求是否到达正在执行的任务，最终状态确认停止结果。已请求停止的轮次结束后保存为 `cancelled`，晚到的回复不能把它改为 `completed`。Android 的持久对话只接受本轮已保存用户消息之后、下一条用户消息之前的回复。会话正在运行或压缩、发送未启动、结果为空或出错时，均报告失败，不复用旧回复。审批沿用既有权限范围。中继仅转发消息，不保存对话和结果。

在手机、电脑和浏览器中登录同一个 nanoMuse Cloud 账号后，这些设备就能发现彼此。手机和电脑各自运行智能体，并使用本机的操作工具，也就是「手」：手机可以访问 App 和沙箱，电脑可以使用 shell（系统命令）和屏幕。无论连接哪个网络，设备都能向账号下的其他设备请求操作。网页控制台自身没有操作工具，它负责把请求交给其他设备。

> 术语说明：hub 是设备互联服务；中继是验证账号并转发设备消息的服务器；WebSocket 是保持连接、双向传消息的协议；帧是该连接中传递的一条消息；运行时是执行智能体和工具的程序。

```
phone ──┐                         ┌── computer (nanoMuse Desktop)
        ├──▶  nanoMuse Cloud  ◀───┤
web  ───┘        /v1/hub          └── another phone / computer
```

每台设备都会主动向中继建立一条 WebSocket 并保持连接。设备不开放监听端口，不需要端口转发，也不必连接同一 Wi-Fi。中继只在同一账号的设备之间转发消息帧，不分析任务内容。添加电脑时，在电脑上安装 nanoMuse 桌面版并登录同一账号即可，不用另外手动下载组件或输入配对码。以前通过局域网配对的独立主机脚本已在 0.1.13–0.1.23 之后移除，现在只通过账号接入。如果手机设备列表中没有电脑，通常是两端登录了不同账号；手机的设置 → 电脑可以查看当前账号。

### 编程助手协议 2

编程子协议 2 增加只读的 `coding.projects`、`coding.project.validate`、`coding.item`、`coding.diff` 和快照查询 `coding.watch`，各助手声明独立能力。会话与列表支持有版本的分页游标；发送支持去重 `request_id`，并增加结构化 `item` 更新。原 Hub 帧与纯文本客户端保持兼容，详见[编程协议](coding-agents.md#结构化浏览-协议-2)。

Codex 会话写入被占用时，运行可携带 `resume_conflict: {process, continuation}`。这是 `coding.send` 返回值及 `coding.watch` / `coding.runs` 中运行的可选新增字段，运行以 `failed` 结束，不自动重试。确认新建后，仍通过已有权限检查下的 `coding.send` 发送，`session_id` 为空，`text` 使用返回的上下文文本。

等待电脑授权的发送可以返回 `authorization` 事件。传 `wait: false` 时，发送结果确认已启动的运行，随后通过带 `run_id` 的 `coding.watch` 查询状态；旧电脑使用 `coding.runs`，不必让发送请求一直等待。

## 如何向其他设备发起请求 {#what-you-can-say}

在手机的任意聊天中，可以这样说：

- 「在我 Mac 上列一下下载文件夹」：`nanomuse-pc ls ~/Downloads --on mac`
- 「让电脑把项目编译一遍，把日志发给我」：`nanomuse-pc task "…" --on desk`
- 「电脑截个图给我看」：`nanomuse-pc screen --on desk`

在电脑的 nanoMuse 桌面版或终端 `nanomuse chat` 中，可以这样说：

- 「在我手机上截个图」：`device_screen`
- 「让手机的 Muse 把最后一条通知读给我」：`delegate`
- 「给手机发个通知：晚饭好了」：`device_notify`

网页控制台 `/app` 中，选中设备后输入请求即可。任务由目标设备的智能体执行，需要审批时，网页会显示卡片让你确认是否允许操作。

hub 传递以下请求：

- **直接动作**。包括 `info`、`shell`、`files`、`file.get`、`file.put`、`open`、`screen`、`notify`，用于立即获取信息或执行单项操作。`shell` 命令会在发送前由发起设备判断风险，采用与本地命令相同的规则，即手机 ShellGuard 或桌面 `guard.py`。读取和构建通常直接放行；删除、发送、付款和系统命令则需要在发起设备的审批卡片上确认。
- **完整任务**。格式为 `task {text, conversation?, language?, stream?}`，把自然语言描述的工作交给目标设备的智能体。任务在目标设备独立的对话中执行，`conversation` 指定对话，省略时使用发起设备 ID。可选 `language` 从运行时 1.0.0 起支持，使用 BCP-47 语言标签表示发起设备的界面语言，目标按它回答，不再从请求文本猜测。

  任务可能需要几分钟。目标智能体遇到需审批的步骤时，会通过 `event {stage:"approval"}` 把问题发回，发起设备显示自己的常用审批界面：手机 RiskGate、桌面终端提示或网页控制台卡片。用户回答再以 `approve {approval_id, allow}` 发回目标设备。

  发起设备可用 `stop {call}` 停止任务，`call` 是原始 `task` 帧 ID；也可用 `stop {conversation}`，指定当时命名的对话，省略对话名时就是它自身对应的设备对话。目标会在当前步骤结束后取消运行，返回 `{stopped: true}`，原 `task` 调用随后以 `cancelled` 失败。`{stopped: false}` 表示没有属于该发起设备的可停止任务，一台设备不能停止其他设备发起的任务。运行时、桌面版和手机都遵守这项规则。

  运行时收到的 `task` 如果指定了正在执行任务的对话，会立即返回 `busy`。发起方应等待前一任务完成，或先停止它，再发起新任务。超过 hub 时限仍无回答时返回 `timeout`；目标智能体无法执行时返回 `failed`。任务虽已送达对话，但在请求模型前就被拒绝、未开始执行时，也返回 `failed` 并提供说明，不会返回空答案。桌面版收到新任务时，如果对应聊天在上次交付后已归档，会恢复该聊天，与用户打开聊天继续输入的行为一致。

  `stream: true` 表示发起方会把每条 `text` 更新到上一个 `tool` 之后的文字位置。此时 nanoMuse 桌面版还会发送 `text {text, interim, partial: true}`，包含模型正在撰写的消息，最多每 250 ms 更新一次，完成后仍发送完整消息。未请求流式显示的客户端每条消息只收到一次；Android 的 `nanomuse-pc task` 会把每条 `text` 列为一个步骤。运行时目前忽略 `stream`。

  运行时和 iPhone 发起任务后最多等待 15 分钟，与桌面版和运行时目标的任务时限一致。本地等待超时或收到中继的 `timeout` 后，发起方会使用原始调用 ID 发送 `stop {call}`，另外最多等待 15 秒清理。运行时取消任务时也使用同一个精确调用 ID。这项清理只是尽力执行：断线目标可能收不到，因此调用方保留原始失败信息，不宣称远程工作已经停止。目标自身的任务时限仍然有效。明确指定的调用已结束时，必须返回 `{stopped: false}`，不能转而停止该对话后来的任务。这些规则不改变帧格式，旧客户端仍可使用。

  执行期间，目标通过 `event` 帧的 `body.stage` 告诉调用方应显示什么，使两端能看到相同过程。工具开始时发送 `tool {id, name, summary}`，结束时发送相同 `id` 的 `tool_result {id, name, ok, summary}`；审批使用 `approval {approval_id, preview, risk, reason, device, timeout, grant_key}`，任一端决定后发送 `approval_result {approval_id, status}`。中途文字使用 `text {text, interim}`，生成内容使用 `image`、`file`，错误使用 `error`，最终答案放在 `result` 帧中。

  调用方将 `text` 替换到上一个 `tool` 之后的文字位置，因此目标可以多次发送同一消息逐渐增长的内容，界面也会逐步更新；每条消息只发送一次的目标仍正常显示。1.0.6 起的 `grant_key` 指定发起设备保存授权时的覆盖范围：运行时使用自身授权键，例如工具加目标 `shell:git`；桌面版使用工具加完整主参数。旧发送方没有该字段时，仍以 `preview` 前 60 个字符作为键，可能使开头相同的不同步骤共用一个键。
- **编程助手请求**。`coding.agents`、`coding.sessions`、`coding.session`、`coding.send`、`coding.stop`、`coding.runs` 用于电脑上的 Cursor、Codex、Claude Code 会话。目标电脑的运行时或桌面版从磁盘读取会话，并通过相应助手的 CLI（命令行工具）控制它。`coding.send {agent, text, session_id?, workspace?, wait}` 通过 `event` 帧返回 `started`、`text`、`tool`、`done`、`error`，每条都带运行 ID，供调用方使用 `coding.stop`；最终返回完整执行结果。只有安装相关模块的电脑运行时或桌面版会声明支持这些动作，见 [coding-agents.md](coding-agents.md)。

每台设备决定自己接受哪些远程操作。手机的设置 → nanoMuse Cloud → 设备中，关闭「允许其他设备操作这台手机」后，只回应 `info`，但仍可查看和控制其他设备。运行时关闭远程控制后，`info` 也只返回电脑名称和系统，不返回账号名、主目录、工作目录或 shell 信息，支持动作列表中仅保留 `info`。

开启远程控制后，`shell`、`files`、`file.get`、`file.put`、`open`、`screen`、`coding.send`、`coding.stop` 等会在目标设备上执行、读写的直接动作，还需目标设备旁的用户同意。审批选项为「允许一次」或「对这台设备总是允许」；后者会在「权限」中保存为 `remote_control:<device id>`。桌面版默认也显示同样的卡片；设置 → 设备中的「免询问远程控制」允许账号下所有设备直接执行远程操作。无人回答、卡片过期时，调用方收到 `not_allowed`。

`info` 和 `notify` 不需要审批。`task` 则受目标设备自己的哨兵约束，任务内审批仍发回调用方。设备只能回答自己发起的任务中、已发送给它的卡片，不能替目标设备回答「是否允许它远程操作」的卡片。唯一例外是电脑主动推送、带 `any_device` 的卡片，账号下任意设备都能回答，见[下文](#a-computer-s-own-cards-on-the-phone)。

### 在手机上回答电脑自身任务的审批 {#a-computer-s-own-cards-on-the-phone}

桌面版执行定时任务时，电脑旁可能没人，因此会把审批卡片推送给账号下的手机。这些卡片没有对应的远程调用，使用中继 0.31 的推送机制，见[消息帧](#frames)。只有 `welcome.server.features` 包含 `event_push` 时，电脑才发送；中继只交给 `hello` 中声明了 `approve.any` 的设备，目前是 Android 和 iPhone App。

推送仅用于这种无人值守的桌面任务。用户正在电脑或网页控制台聊天时，审批留在原界面；其他设备委派的任务，审批沿原调用返回发起设备，见[上文](#what-you-can-say)。Python 运行时 `nanomuse serve` 目前不推送，它的定时任务卡片仍在网页版等待，见 [#704](https://github.com/nano-muse/nanoMuse/issues/704)。

```
→ event {to:"*", body:{stage:"approval", approval_id, preview, preview_zh, reason, app,
                      task:{id, title}, chat, scopes:["once", "schedule"?], timeout, device,
                      any_device:true}}
← call  {action:"approve", args:{approval_id, allow, scope?:"once" | "schedule"}}   （发给电脑）
→ event {to:"*", body:{stage:"approval_result", approval_id, status, by?:{id, name}}}
```

`preview` 和 `preview_zh` 分别是英文、中文操作说明，手机按界面语言选择。`app` 表示「手」将操作的应用，`task` 和 `chat` 指明任务及所属聊天，`device` 指目标电脑，`timeout` 是手机显示卡片的秒数，当前为 600。

`scopes` 列出除「拒绝」外可选的授权范围。`schedule` 对应「此定时任务中始终允许」，仅用于一个任务的运行中由「手」执行的步骤。该授权保存在电脑，不保存在手机。`any_device` 表示账号下任何设备都能回答；普通卡片仅接受任务发起方回答，这种卡片则以电脑或任意手机上最先提交的回答为准。电脑随后推送 `approval_result`，用 `status` 表示 `approved`、`denied`，或任务已放弃卡片时的 `cancelled`，并通过 `by` 标明回答设备。手机收到后关闭卡片。

手机上超时无人回答时，只关闭本机卡片，不发送拒绝，电脑上的卡片仍可继续等待。命中付款敏感词的卡片也会推送；只有手机声明 `approve.any`，回答受手机锁屏保护。操作实际在电脑执行，因此即使关闭「允许其他设备操作这台手机」，也会显示这类卡片。App 位于后台时，Android 会显示通知；iOS 在 hub 连接仍保持时也会发通知。

### 提案 `proxy_fetch`：让手机借用电脑连接服务商 {#proposed-proxy-fetch-the-phone-uses-the-computer-s-connection}

这项功能尚未实现。此处先记录协议，让各端在开发前对齐。适用场景是手机无法访问 `chatgpt.com` 或服务商主机，而用户的电脑可以访问，见 [own-key.md](own-key.md#when-the-provider-cannot-be-reached)。设计中，电脑运行时会通过 hub 转发这一次服务商请求，充当仅面向该请求的代理。

```
→ call   {id, to, action:"proxy_fetch",
          args:{method, url, headers:{…}, body?, stream?}}     body base64; stream: want SSE chunks as events
← event  {id, from, body:{stage:"headers", status, headers:{…}}}
← event  {id, from, body:{stage:"chunk", data}}                data base64; one per SSE chunk when stream is true
← result {id, ok:true, body:{status, headers:{…}, data?}}      data base64 when stream was false
← result {id, ok:false, error:"not_allowed" | "host_refused" | "too_large" | "upstream", message}
```

提供转发服务的电脑需要实施以下规则：

- **由用户在电脑上开启**。桌面插件仅在设置 → 设备中的「让我的手机借用这台电脑的网络访问服务商」开启时，在 `hello` 声明 `proxy_fetch`，关闭时返回 `unknown_call`。权限与 `device_shell` 相同：目标设备须开启「远程控制」，首次调用需在卡片上选择「允许一次」或「对这台设备总是允许」，后者保存为 `remote_control:<device id>`。
- **限制目标主机**。只转发到 `providers.json` 服务商目录中的主机、`chatgpt.com`、`auth.openai.com`，以及电脑自身配置的服务商自定义基础地址。其他目标返回 `host_refused`，中继、局域网地址和 `file:` 均不允许。
- **转发凭据，不保存凭据**。手机发送自身 `Authorization`，其中可以是套餐令牌或自己的 key。电脑原样转发，只记录主机、状态和大小，不记录请求头或正文。
- **限制请求规模**。请求正文超过 8 MB，或响应单帧超过 `HUB_FRAME_LIMIT`，返回 `too_large`。流式响应最多持续十分钟，每台调用设备同时只能有一个请求。
- **由手机用户选择**。只有在线电脑声明支持 `proxy_fetch` 时，连接失败卡片才显示「用我电脑的网络」。选择按服务商实例保存，并在该实例中明确显示，提醒用户自己的 key 将经过电脑。

它仍是设计方案，因为电脑端转发器会接触用户的服务商令牌，形成新的信任边界。手机的两套 HTTP 实现也分别需要传输适配层，将请求转成 hub 帧，再把帧还原为响应。总计三个实现，还需另一处与它们保持一致的主机列表，本轮工作范围尚不足以完成。现有[代理设置](own-key.md#when-the-provider-cannot-be-reached)可以处理常见场景：在电脑运行 Clash 或 `ssh -D` 等代理，再让手机连接它。

## 消息帧 {#frames}

hub 通过 `WS /v1/hub` 传输 JSON 文本帧，使用 `Authorization: Bearer nm_…` 验证；浏览器改为在 `hello` 中携带 key。

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

关闭码含义如下：

- `4000`：需要先发送 hello。建立连接后 15 s 内没有 hello，或首帧不是 hello 时触发，首帧为二进制也算。
- `4001`：key 无效，原因可能为 `bad_key` 或 `account_deleted`。活动连接所属账号被删除或停用时，原因是 `account_gone`。中继 0.25.0 起，连接期间 key 被撤销也会返回 `bad_key`，例如其他设备执行「在所有设备上退出」、账号页撤销该登录，或设备主动退出。这样丢失手机会立即断开，其他设备随即看到它离线。
- `4002`：设备无效。
- `4003`：同一设备 ID 的新连接取代旧连接。中继 0.22 起，如果原因是 `hub_paused`，则表示运营者暂停了 hub 或整个服务；客户端应等待后再连，见 [cloud.md › 控制](cloud.md#controls)。
- `4008`：持续超过帧速率限制。中继 0.30 起，原因也可能为 `too_many_connections`：同一地址一分钟内建立超过 60 条连接，或账号已有 32 台设备在线。同一设备替换自己的旧连接不计入新增设备。
- `4009`：客户端读取太慢，单个连接已积压 512 帧或 32 MB。客户端应像网络断开时一样，逐步延长间隔后重连。

`Authorization` 中的 key 被拒绝时，与 `hello` 中被拒绝的处理一致：先完成握手，发送带错误码的 `error` 帧，再以 `4001` 关闭。遇到 `4001`、`4002` 的客户端会退出通常的延迟重连流程，显示 hub 拒绝连接并提示重新登录。运行时仍每分钟尝试一次，便于中继恢复 key 后无需重启即可连接。其他关闭按网络问题处理，重试间隔逐渐增加。

笔记本睡眠或切换 Wi-Fi 后，socket 可能仍显示打开，但已无法通信，此时就收不到 `pong`。运行时使用协议 ping，超时为 20 s；桌面版如果两次 `ping` 帧之间完全没有收到消息，约 50 s，就主动断开并按同样方式重连。

中继 0.31 起，`event` 可以不带 `id`，用于独立推送，而非某次调用的进度。电脑用它发送自身任务的审批卡片和审批已回答的通知。`to` 可以是单个设备 ID，也可以是代表账号所有设备的 `"*"`；但中继始终只转发给 `hello` 中声明 `approve.any` 的设备，且不回传发送方。发送方无需维护接收名单，旧版 App 也不会收到无法处理的推送。只有 `approval` 和 `approval_result` 两种阶段会通过，其他阶段丢弃并记日志。每台设备每分钟最多推送 30 条，超过返回 `rate_limited`；每个 `body` 最多 16 KB，超过返回 `too_large`。客户端仅在 `welcome.server.features` 包含 `event_push` 时发送，因此不会向旧中继发送推送。

无法识别的帧，包括没有处理器的 `type`、内容不是 JSON 对象的文本帧和二进制帧，都会收到 `error bad_frame`，连接保持。这样新客户端连接旧中继时，只影响那一帧。超过 `frame_limit` 返回 `too_large`；每秒超过 60 帧或 8 MB 返回 `rate_limited`，每秒最多警告一次，多余帧丢弃，持续超限会以 `4008` 关闭。

每条连接分别排队、按顺序发送，因此向某台设备发消息不会阻塞等待它读取。接收方停止读取并积压到 512 帧或 32 MB 后，连接以 `4009` 关闭，一台卡住的手机不会拖住呼叫它的电脑。无人回答的 `call` 在 15 分钟后向调用方返回 `timeout`。中继在收到 call 或 ping 时检查超时，持续发送 ping 的调用方会在截止后一分钟内得知结果。`forget` 无法移除仍在线的设备，会返回 `device_online`。

设备 ID 按安装实例生成，例如 `phone-…`、`pc-…`；设备名称供用户辨认，可在设备上修改。`web` 设备不能作为调用目标，也不会被持久记录。`file.get`、`file.put`、`screen` 使用 base64 编码的 `data` 和 `mime` 传输文件内容；桌面版拒绝超过 8 MB 的文件，中继拒绝超过 `HUB_FRAME_LIMIT` 的帧。

Python 运行时的 `files` 最多返回 2,000 个目录项。如果还有更多可读项，会附带 `truncated: true` 和 `total`。`total` 是逐项读取前观察到的目录名称总数，已消失或无法读取的项可能被略过。恰好达到列表上限不标为截断。这两个字段均为可选新增字段，客户端也必须接受没有它们的旧响应。

中继 0.27 起，每个凭据绑定唯一 hub 身份，包括固定的 `device.id` 和 `device.kind`。通过 `POST /v1/auth/verify` 或 `/login` 登录时传入 `device_id`、`device_kind`，会在签发凭据时绑定；未传入时，则在首次有效 `hello` 时绑定。同一个凭据可以重连并替换自己的旧 socket，但使用不同 ID 或类型会被 `bad_device` 拒绝。

已经由有效 key 占用的设备 ID，只能由后续验证码或密码登录签发的新 key 接管。例如手机没有先退出就重新登录、运行时保险库被重置，或退出请求未到达中继时，就可能发生接管。旧 key 仍可访问账号，但不能再代表该设备。key 被撤销或失效后会释放 ID。`/v1/auth/session-key` 签发的会话 key 用于 nanoMuse Web 容器，只能注册尚未被占用的 ID，不能接管设备。旧客户端保留原 key，在下次连接时绑定；登录时已提交身份的新客户端会立即绑定。

智能体的名称和形象属于账号，通过中继 `GET` / `PUT /v1/me/profile` 保存。形象可以是龙、带底色的 emoji，或形象工作室绘制的面孔及其小幅静态图。最后一次写入生效；中继用 `profile` 帧通知其他设备获取新的 `rev`。运行时实现在 `nanomuse/hub/profile.py`，Android 实现在 `io.github.nanomuse.cloud.ProfileSync`，写入设备会忽略自己的回传通知。

同一配置档案从 0.1.34 起还记录**各设备连接了哪些服务**。`connectors` 列表中的每项包含连接器 ID、名称、可用时的地址、登录方式 `oauth` / `key` / `open`、设备名称和 ID、是否启用及时间。OAuth 是由用户在服务商页面确认授权的登录方式。每台设备只更新自己持有的条目，中继保留其他设备条目，最多存 64 项。包含 token、secret、key、authorization 或 password 字段的条目会被拒绝，凭据始终留在登录设备。其他设备在连接器目录中显示「已在〈设备〉连接；如需在本设备使用，请在这里登录」，实际操作仍是在本机正常登录。

中继 0.29 起，配置档案还可引用形象的**动画片段**。生成动画的设备先通过 `PUT /v1/blobs/{sha256}` 上传文件，见 [cloud.md](cloud.md#the-record)，再写入 `clips: {mood: {sha256, mime, bytes}}`。其他设备收到同样的 `profile` 帧后，通过 `GET /v1/blobs/{sha256}` 下载，不再各自重新生成。片段与面孔绑定；写入 `clips: null`、更换形象或调用 `DELETE /v1/me/profile` 都会清除。1.0.6 及更早 App 忽略这个字段。

从 0.1.36 起，**对话**也能跨设备同步，但走独立通道：文本通过 REST 请求写入中继 `/v1/sync/*` 存储，hub 只发更新提醒，见 [cloud.md](cloud.md#conversation-sync)。推送被中继接受或对话被删除后，账号下其他 socket 收到 `sync {what:"conversations", cursor, from}`。`cursor` 为变更后的账号计数器，`from` 为发起设备 ID。各设备再从自己的游标拉取新增内容；`from` 与自身 ID 相同则忽略。

从 0.1.38、中继 0.20 起，hub 还传递**哪台设备正在回答**。设备开始或结束同步对话中的一轮任务时，调用 `/v1/sync/working`，其他连接收到 `working {cid, from, device_name, working, at}`。App 会在最后一条消息下显示「kwai 正在处理…」，直到收到 `working: false`、实际回复，或经过十分钟。中继 0.31 起，`working: true` 可附 `state` 和 `detail`：`state` 为 `working` 或等待用户卡片的 `waiting`；`detail` 为最多 160 字的步骤描述。例如界面可显示「kwai 正在处理：打开订票网站」或「kwai 在等你确认」。未发送新字段的设备仍显示一般工作状态，旧客户端忽略新字段。这些状态仅保存在中继内存。

默认只同步主要聊天；旁聊仅在都开启「同时同步旁聊」的设备之间同步。key、服务商和设置仍留在填写它们的设备，文件和图片仍留在生成设备。各端的使用方式见 [every-device.md](every-device.md#the-same-conversations-everywhere)。

## 代码位置 {#the-code}

设备页、面向某台设备的旁聊、两端审批及电脑操作工具如何使用这些帧，见 [every-device.md](every-device.md)。

- 中继：[`cloud/nanomuse_cloud/hub.py`](../../cloud/nanomuse_cloud/hub.py) 管理按账号划分的设备注册、路由、`GET /v1/devices`、`DELETE /v1/devices/{id}`；控制台位于 [`cloud/nanomuse_cloud/console/`](../../cloud/nanomuse_cloud/console/)。
- Android：`io.github.nanomuse.hub` 中，`HubClient` 负责 OkHttp 连接与重连；`Hub` 管理状态、偏好和 `call` / `find`；`HubActions` 实现手机接受的动作，包括通过无界面聊天执行器运行且遵守 `language` 的 `task`；`HubService` 以前台 `remoteMessaging` 服务运行。`io.github.nanomuse.reach` 的 `nanomuse-pc` 让手机沙箱 shell 访问 hub 设备。
- nanoMuse 桌面版：[`harness/dsh-nanomuse/src/hub.ts`](../../harness/dsh-nanomuse/src/hub.ts) 管理 socket 和重连；[`harness/dsh-nanomuse/src/actions.ts`](../../harness/dsh-nanomuse/src/actions.ts) 实现电脑接受的动作，以及远程操作前的审批卡片，见 [desktop.md](desktop.md)。
- iOS：[`NanoMuse/NanoMuseHub.swift`](../../android/src/ios/NanoMuse/NanoMuseHub.swift) 支持 `info`、`open`、遵守 `language` 的 `task`、`notify` 和 `stop`。`screen` 返回 `no_screen`，shell 和文件动作返回 `not_supported`。目标为 iPhone 时，`task` 内的审批步骤不会以 `event` 回传：nanoMuse 在前台就显示本机卡片，后台则拒绝并在回答中说明。反过来，手机通过 `@〈设备〉` 发起的任务，见 [`NanoMuseDeviceMention.swift`](../../android/src/ios/NanoMuse/NanoMuseDeviceMention.swift)，会由 [`NanoMuseRemoteApproval.swift`](../../android/src/ios/NanoMuse/NanoMuseRemoteApproval.swift) 显示收到的 `approval`，将 `approve` 发回，并在收到 `approval_result` 后关闭卡片。电脑[主动推送的审批](#a-computer-s-own-cards-on-the-phone)也使用这张卡片，提供「允许一次」「此定时任务中始终允许」「拒绝」。[`NanoMuseDeviceReply.swift`](../../android/src/ios/NanoMuse/NanoMuseDeviceReply.swift) 在目标工作时持续更新回复，以步骤胶囊显示 `tool` / `tool_result`，逐段显示 `text`；停止按钮发送 `stop {call}`。
- 运行时 `nanomuse serve`：[`nanomuse/cloud.py`](../../nanomuse/cloud.py) 管理账号；[`nanomuse/hub/client.py`](../../nanomuse/hub/client.py) 管理连接与重连；[`nanomuse/hub/actions.py`](../../nanomuse/hub/actions.py) 实现电脑动作；[`nanomuse/hub/service.py`](../../nanomuse/hub/service.py) 将收到的 `task` 放入可见旁聊，处理双向 `tool` / `tool_result` / `approval` / `approval_result` 及设备线程；[`nanomuse/tools/devices.py`](../../nanomuse/tools/devices.py) 提供 `devices`、`device_*`、`delegate`。`/api/cloud/*` 和 `/api/hub/*` 定义在 [`nanomuse/server/api.py`](../../nanomuse/server/api.py)。`tests/test_hub.py` 使用模拟中继测试。
- 网页版：[`web/src/`](../../web/src/) 中的 `DevicesScreen`、设备聊天和远程审批卡片，见 [every-device.md](every-device.md)。

## 信任边界 {#trust}

中继使用绑定设备 ID 和类型的凭据验证每条连接，只在同一账号内路由。它保存设备名和最后在线时间，不保存任务请求。设备只接受同账号设备的操作；执行、读取或写入还需开启「远程控制」，并由目标用户授权一次，或对发起设备持续授权。命令在发起设备输入时先判断风险，再发送。远程智能体提出的审批由发起用户回答，不能由另一个智能体代答。

设备退出登录会在中继撤销自身 key，并断开 hub。手机和控制台的「设备」列表显示所有登录过的设备，方便你发现不认识的条目；设备离线后可以点击「移除」。
