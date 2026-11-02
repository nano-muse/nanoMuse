# nanoMuse Cloud

「现在就开始」这条路：用手机号（中国大陆；验证码走短信）或邮箱注册，拿一份免费额度，不用自己的 API key 就能用 nanoMuse。用自己的 key 的方式和以前完全一样：这只是多了一个服务商，不是替代。

管理控制台保存的数字设置为空或不是有限数值时，会使用该设置的默认值。

管理控制台刷新时，每个 URL 只保留最新请求的结果。退出登录前尚未返回的请求不会重新填充已清空的缓存，也不会覆盖之后登录账号的数据。

## 在应用里 {#in-the-app}

0.1.20 起，账号是每个 App 的起点：第一屏要你填手机号或邮箱，发一个六位验证码（或者，设过密码的话，直接输密码），然后问由哪个模型来回答：账号自带的（Cloud），还是你自己的 key。短信验证码只发中国大陆号码（号码认证服务不往别处发）；香港、台湾或海外号码会立刻被告知（`phone_region`），改用邮箱登录。退出登录会回到那一屏（自己部署的：在运行时上设 `[cloud] required = false` 或 `NANOMUSE_CLOUD_REQUIRED=0`）。那一屏是门，不是墙：点「改用自己的 API key」就能越过它进入设置里的自备 key 路径；有了自己的 key，App 不登录也能用（聊天、动手、图片、短片），登录入口留在「连接」里（手机上是「设置 → nanoMuse Cloud」），用于 Cloud 模型、同步和你的设备。输完验证码后，App 有了：

- *设置 → 服务商* 下一个叫 **nanoMuse Cloud** 的服务商，一个普通的 OpenAI 兼容服务商，它的 key 就是中继发的 token；
- *设置 → 模型*（网页控制台：「连接」页）的聊天和手两行在你没选过时使用账号的 `Qwen/Qwen3.6-27B-FP8`。它能接收图片，所以聊天看图和 GUI 操作读取截图不受影响。账号不再提供生图或生视频；图片和视频两行必须在设备上配置你自己的服务商和 API key。你没设过的一行按现有自动顺序解析，以后再加一把 key 会先问「用它来做什么」，然后才会动任何一行（[own-key.md](own-key.md#which-model-does-what)）。

*设置 → nanoMuse Cloud*（「账号」页）显示谁登录了（一个打码的提示，从不显示号码）、从什么时候起；设置、修改或移除**密码**（最短长度由中继设置，默认八个字符；中继上用 scrypt；连续输错会锁一段时间，用验证码重新登录一次就解开）；今天花了多少额度，以 ¥ 和 $ 计，配一个仪表；**按类型的用量**（聊天、图片、视频）今天和累计，以及**按模型**的用量；**登录记录**：每一台持有 key 的设备、它怎么登录的（验证码还是密码）、最后一次使用的时间，每条都可以吊销；账号自己的**历史**（登录、改密码、被拒绝；从不包含消息内容）；还有几条退路：在这台设备「退出登录」、「所有设备退出登录」、「删除账号」。额度属于那个地址：再次登录，不管在这台手机还是另一台，拿到的是同一个账号的新 key，不会多给一份额度。

**退出登录在手机上留下什么**（0.1.40，契约 C12）。退出登录（在这台设备、在所有设备，或者为了换一个服务器）只问一个问题：「把这个账号的聊天留在这台设备上」，默认关。关着，账号的聊天、记忆、动态、目标、例程和形象会从手机上移除（同步开着的话，中继那里还留着聊天，下次登录能拿回来）；开着，它们被收起来，等账号再次登录时回来。改用另一个账号登录也要经过同样的退出流程。「删除账号」在中继删掉账号，也删掉手机上属于它的一切，不再多问；之后用同一个地址登录是一个全新的空账号。中继拒绝的 key（`401 bad_key`：另一台设备上点了「所有设备退出登录」、中继重置、中继的 bug）是一次手机上没人能回答的退出，所以手机把账号的数据像「保留」那样收起来，移除 key，登录页写着「这台手机上的登录已结束。重新登录即可继续；在那之前，你的聊天会留在这台设备上」；下次以同一个账号登录就恢复，换一个账号则什么也看不到。只有 `401 account_deleted`（0.1.40 起中继对账号已删除的 key 的回答）才让手机把数据删掉，因为已经没有可以回去的地方了。每一样状态存在哪里、每个事件发生时它怎么样，是 [sync.md](sync.md) 里的那张表。协议上唯一的新增是那个错误码；旧版中继两种情况都答 `bad_key`，手机就保留数据。

在它旁边再登录第二个服务商（你自己的百炼 key、DeepSeek、一台本地服务器）一如既往可行；中继的模型可以和你的放在同一个模型组里混用。

## 中继保存什么 {#what-the-relay-keeps}

中继就是 [`cloud/`](../../cloud/README.md) 里的代码。它存：

- 邮箱地址或中国大陆手机号的加盐哈希（HMAC-SHA256）、一个打码的提示如 `so***@example.com`，以及地址本身的加密副本（AES-GCM，密钥由中继的 secret 派生），让运营者能在管理页上看到账号属于谁（单看数据库文件什么也看不出来）；
- 每个已发 key 的哈希，连同你登录时的设备名、方式（验证码还是密码）、最后使用时间，以及登记后的 Hub 设备 id 和类型；吊销的 key 保留它那一行，登录记录列表才能说明这一点；
- 密码，如果你设了，以 scrypt 哈希保存，从不保存密码本身；
- 每次请求：类型（聊天、图片、视频）、模型、token 数和扣费金额；
- 中继 0.28 起，每次聊天请求的经过（`calls` 表）：在服务商闸门前等了多久、首字和整体用了多久、怎么结束的（成功、服务商错误或超时、内容审查拒绝、连接中断、额度拒绝）、请求里有几条消息和几张图、客户端提供了哪些工具、回复调用了哪些（只记名字）、是不是一次屏幕操作、来自哪个平台，中继 0.31 起还有输入 tokens 里有多少是服务商从缓存里给出的。从不记对话里的一个字。超过 `CALLS_KEEP_DAYS`（90）天的行会删除；运营者的「实时」和「用量」页按汇总读这些行（模型接口有多忙、答得多快、哪些平台在排队）；
- 中继 0.28 起，每一轮保留的对话（下面的「帮助改进」）旁边有一行形状（`sample_stats`）：消息数、字符数、工具调用、图片数、提问是否过短，以及这个人那句话的哈希，用来数重复。质量页读的是形状，不是对话；删除保留的轮次时形状一起删；
- 中继 0.28 起，设备可以在 hub 握手里说明自己跑在哪个模型上（`llm {provider, model}`，只有这两个 id，从不是 key、地址或设置），运营者由此知道大家自己配了哪些服务商。1.0.6 及更早的 App 什么都不说；1.0.7 起每个客户端在账号的模型回答时说 `cloud`，用自己的 key 时说目录里的服务商 id（`openrouter`、`bailian`）和模型 id；
- 一条账号事件时间线（登录、登录失败、设置或修改密码、退出登录、因预算被拒、上游错误），细节是设备名、模型或错误码，从不是消息内容；
- 旧视频任务的记录，包含价格和服务商最后一次返回的状态，只用于账务清理，三天后删除。托管媒体已经全面下线，所以轮询任务和其他托管媒体接口一样返回 `410 hosted_media_retired`，不会请求服务商；
- 智能体的名字和形象（`/v1/me/profile`）：它用的是哪一张（小龙、某个颜色底上的 emoji，或者形象工作室里画的一张，连同那张形象的五张小 WebP 图），好让账号的每台设备显示同一个。从中继 0.25 起写入是部分的：设备只发它这边变了的字段，改名只发名字，换脸发形象和图片，没发的字段保持中继存着的值（空名字也算没发），所以一台还没拉到账号形象就先改名的手机不会再把「小龙」当成名字一起发上去、让其他设备的形象都被换掉；`avatar` 不是 `face` 时存着的图片一并丢掉，这样没有哪台设备会把 `has_face` 读成还戴着的脸。1.0.3 的客户端每次写整个形象，读法和以前完全一样。0.1.34 起，同一份 profile 还列出账号的**连接器**：哪台设备连接了哪个服务（一个标签；登录方式：OAuth、key 或开放；以及时间），这样另一台设备能说「已在你的 Mac 上连接」。凭据本身留在持有它的设备上；中继拒绝任何带着像凭据一样命名的字段的项。从不存 key 或设置。
- 中继 0.19 起，**同步的对话**（「在我的设备之间同步对话」，默认开）：账号聊天的文本（每个对话的标题、类型和由哪台设备发起，每条消息的角色、文本、时间和设备，以及附件的名字和大小，从不存文件本身），好让每台设备显示同样的对话。关掉开关会删掉全部；删除账号也一样。下面的[对话同步](#conversation-sync)一节有它的形状。

- 中继 0.29 起，**记录**：中继答过的每一轮聊天，完整保留：中继发给模型的请求原样（每条消息：带着你的记忆、SOUL 和指令的系统提示词、你写的、工具返回的；工具定义；采样参数）和模型给出的回答原样（内容、推理、工具调用、结束原因、用量）。图片、音频和短视频从消息里取出，按各自的 SHA-256 命名，每个只存一份文件，原位置留一个 `blob:sha256:` 引用；屏幕操作时 App 每一轮都重发的那张截图，只是一个文件。随这一轮一起的还有：模型、平台、App 报的设备和对话（`X-NanoMuse-Device`、`X-NanoMuse-Conversation`，1.0.7 起）、token 数（中继 0.31 起含输入里命中缓存的部分），以及和每次请求一样的网络地址与客户端软件。中继 0.31 起还有 App 报上来的这一轮的来历：是谁发起的（人、定时任务、动态日报、目标检查、另一台设备）、它是对话里的第几轮、这一轮里的第几次模型调用、属于哪个屏幕操作任务的第几步，以及你写的那句话用的是哪种文字（一个词：`zh`、`latin`、`ja`……，从不是原文）。请求头见[来历](#provenance)一节。这是账号自己的数据，它的各台设备可以读回来，运营者也能看清一个问题的全貌；它不取决于下面的任何一个开关。[记录](#the-record)一节说明保留什么、谁能读、怎么删。

- 中继 0.31 起，**App 在一轮前后回报的事件**：只有代号和数字的短记录，从不是消息——Sentinel 对某次工具调用的判定和风险档、一次审批的结果、人为什么手动停掉一条回复、对某条回答点了赞还是踩、屏幕操作的某一步结果如何。App 知道轮次 id 时就挂在那一轮上；[客户端事件](#client-events)一节列了全部类型。人删掉留存的轮次时它们一起删，注销账号时也一起删。

消息内容只按下面「记录」「数据控制」和「对话同步」三节所说的方式保存，此外不存：请求转发给运营者配置的上游模型，回复流式传回。中继一次最多向这套共享部署发送 `CHAT_CONCURRENCY` 个聊天请求，其余请求在中继等待；只有在回复开始前收到 429 或 5xx 才会重试，不会重复已经开始的轮次。每个响应都带一个 `X-Nanomuse-Request` id，这样一份问题报告可以对上账本里的一行，而不用记录任何内容。删除账号（带账号 key 的 `POST /v1/auth/delete`）会移除全部：账号、key、设备、profile、账本、事件、保留的对话、视频任务、同步的对话和游标、hub 连接，以及实时的「正在处理」提示；中继的测试会在之后检查每一张表里是否还有这个账号的痕迹，并确认同一个地址再注册是一个全新的空账号。见 [privacy.md](privacy.md)。

## 数据控制 {#data-controls}

*设置 → 数据控制 → 帮助改进 nanoMuse 的 AI 模型* 是一个属于每个人自己的开关，在手机、网页版、桌面版和控制台上是同一个。关着，中继转发聊天请求，什么都不留。开着，每一轮会作为训练视图保留：你写的、模型答的、它选择的工具调用，连同模型、token 数，以及请求头里 App 的平台和语言，只和账号 id 关联，从不保留系统提示词（你的记忆、SOUL 和指令），从不保留工具返回的内容（你的文件、你的屏幕、别的 App 显示的东西），从不保留图片、短视频或语音（原位置留一个标记）。目的是给社区自己的开放模型准备一份训练集。中继 0.31 起，App 用你自己的 key 跑完并传到记录里的轮次（`POST /v1/turns`），在开关开着时也按同样的训练视图保留——不论哪把 key 答的，一轮就是一轮；每条留存的轮次都记下来历（`meta.source` 是 `cloud` 还是 `own`、`meta.run`、`meta.turn`、指向记录里那一轮的 `meta.turn_id`、你写的那句话的文字种类；见[来历](#provenance)），这样 App 之后对它的评价（赞或踩、为什么停掉）可以按轮次 id 对上。页面显示保留了多少轮；随时可以关掉开关（之后不再保留），点一下就能删掉已保留的内容；删除账号也会一并删掉。开关开或关都不会换来任何额度。在 `cloud.nanomuse.cn` 上，这个开关**对中继 0.9 之后创建的账号默认开启，直到这个人把它关掉**：隐私政策这么写，页面在开关旁边也这么写，之前的账号保持它们当初的选择；自己部署的中继用 `IMPROVE_DEFAULT` 定自己的默认值。中继 0.29 起，这个开关只决定一轮的训练视图是否进入训练集；这一轮本身无论如何都在[记录](#the-record)里，同一个删除按钮两者一起删（`DELETE /v1/me/samples` 返回 `{deleted, turns, files}`）。运营者在管理页的「数据控制」面板看到保留的轮次（多少账号开着、按天、按模型和按 App 的轮次数、最新的轮次、每个账号保留的完整对话），并以 JSON lines 导出，不带账号 id 或地址（`GET /v1/admin/samples/export`，`?account_id=` 导出某一个账号的）。中继 0.31 起，导出的每一行带一个 `subject`，是账号的化名（账号 id 在中继密钥下的 HMAC，16 个十六进制字符：同一个账号在每次导出里都是同一个化名，没有密钥则无从反推账号），[删除台账](#deletions)会列出这之后删过数据的化名，用早先导出训练的数据集据此剔除。中继收不到位置（各个 App 从不发送），但从中继 0.10 起，它随每次登录、请求、事件和设备记录网络地址和客户端软件（`User-Agent`：Android App 及其版本、Windows / macOS / Linux 上的运行时、某个浏览器），并保留账号的第一个和最后一个地址；管理页按账号、按地址显示它们（`GET /v1/admin/address?ip=`），随账号一起删除。从中继 0.11 起，管理页还会说一个地址在哪里（国家、省、市），查的是中继自己磁盘上一份 ip2region 数据库的离线副本；不问任何第三方，也不多存任何东西（地点在页面绘制时才计算）。

## 记录 {#the-record}

中继 0.29 起，中继把它答过的每一轮聊天完整保留下来，作为账号自己的数据，这样一个人的各台设备能显示同一份带截图的历史，运营者也能看清一个问题的全貌，而不是靠计数猜。一轮包括：

- 中继发给模型的请求原样：每条消息（带着你的记忆、SOUL 和指令的系统提示词；你写的；工具返回的）、工具定义、采样参数和中继的默认值，模型按 App 认识的名字记，中继自己加的 `user` 和 `stream_options` 不记；
- 模型给出的回答原样：助手的整条消息（内容、推理、工具调用、结束原因），流式时从流里拼起来，连同用量；中途断掉的流保留已到的部分，`status: partial`，`meta.ended` 记下原因（中继 0.30）：`client_gone` 是 App 关掉了流（人按了停止，或者 App 等不下去了），`upstream_timeout` 和 `broken` 是模型服务商那头断的；
- 图片、音频和短视频，从消息里取出，按各自的 SHA-256 命名，每个只写一份文件（`MEDIA_DIR`，默认在数据库旁边）；原位置留 `blob:sha256:<hex>`，这一轮的 `meta.media` 列出它们的类型和大小。屏幕操作时 App 每一轮都重发的那张截图，不论多少轮引用，只是一个文件；
- 模型、平台、App 在聊天请求里报的设备和对话（`X-NanoMuse-Device`、`X-NanoMuse-Conversation`，1.0.7 起）、token 数、客户端软件和语言，以及请求来自的网络地址（只有运营者看得到）。

它在回答发出之后、在请求路径之外写入，永远不是一次聊天失败的原因。它不取决于「帮助改进」（那个开关管的是训练集），也不取决于「同步对话」（那是各个 App 自己的一份聊天副本）；自己部署的中继设 `RECORD_TURNS=0` 就什么都不留。时间戳在回复结束时确定，同一账号的记录按回复顺序保存，带媒体文件的回复也不会颠倒顺序。其他账号可以独立写入；一次写入失败不会阻止这个账号后续的轮次。

**谁能读。** 账号的各台设备：`GET /v1/turns`（最新在前；用 `before` 和 `before_id` 翻页；`conversation=` 只看一个对话）、`GET /v1/turns/{id}`，以及 `GET /v1/blobs/{sha256}` 取文件；只对持有这个文件引用的账号打开（它的某一轮、它 profile 里的短视频、它自己上传的），知道哈希本身打不开任何东西。本人的视图不含地址。运营者：`GET /v1/admin/turns`、JSON lines 导出（`/v1/admin/turns/export`，含账号 id：这是账号的数据，不是训练集；训练集仍是不含 id 的 `/v1/admin/samples/export`）、`/v1/admin/blobs/{sha256}` 取一个文件，以及 `GET /v1/admin/record` 看数字：总计和按天的轮次与文件数、存储量对上限。

在管理控制台的轮次页、账号账单或事件列表中，更换筛选条件会重新加载列表。尚未返回的旧分页不会混入新列表，也不会覆盖新请求的错误或加载状态。

历史记录和样本分页利用现有时间索引跳过较新的秒，再按插入顺序处理同一秒内的记录。导出和分析回填沿用这一分页边界，无需迁移数据库。

**用自己 key 跑的轮次。** 1.0.7 起，App 用自己的 key 跑完一轮后把它传上来，这样不论模型在哪，记录都是完整的：先对每张图 `PUT /v1/blobs/{sha256}`（请求体是原始字节，带 `Content-Type`；哈希会被校验；先 `HEAD` 一下，或者看返回里的 `known: true`，就知道别的设备是不是已经传过），再 `POST /v1/turns`，带 `model`、`messages`（引用，或者内联的 data URL）、`response: {message, usage?}`，以及 App 手里的 `provider`、`ts`、`conversation`、`id` 和 `status`（`status: partial` 时再带一个 `ended`，用 App 自己的词：`aborted`、`error`、`abandoned`），中继 0.31 起还有按[来历](#provenance)一节定义的 `run`、`turn`、`step`、`trajectory`、`trajectory_step` 和 `platform`；这一行记 `source: own`。「帮助改进」开着时，这一轮的训练视图也一并保留，和中继自己答的一轮一样。Python 运行时对每一次不是发给中继的模型调用都这么做——自己配置的服务商、ChatGPT 登录、双手用的模型——只要这台电脑上登录了账号：调用结束后从内存里的队列发上去，带发出去的请求（去掉 key）、回复、token 用量和来历；超过两兆的图片先作为文件传。退出登录时队列直接丢弃；没有账号时什么都不发。引用一个账号从未上传的文件，返回 400 `unknown_blob`。一个账号每分钟最多传 `RECORD_UPLOADS_PER_MINUTE` 个轮次和文件（120；超过回 429 `rate_limited`，剩下的晚点再传），文件总量最多 `MEDIA_ACCOUNT_MAX_MB`（2048；超过回 413 `quota_exceeded`）；整个存储超过 `MEDIA_MAX_GB` 后，在每小时的清理跑过之前谁的文件都不收（507 `store_full`）。两者都在请求的事件循环之外写入。

**形象的短视频。** 同一套文件也把画出来的形象的短视频在设备间传递：做了动画的那台设备把短视频传上来，在 profile 里指明（`PUT /v1/me/profile` 的 `clips: {mood: {sha256, mime, bytes}}`），其他设备直接下载，不用各自再渲染。短视频随形象走：`clips: null`、换成别的形象或 `DELETE /v1/me/profile` 都会清掉。

**怎么删。** *设置 → 数据控制* 的删除把记录和训练轮次一起删：这个账号的每一轮和只有它引用过的每个文件；删除账号同样；`RECORD_KEEP_DAYS`（`cloud.nanomuse.cn` 上是 0：保留到你删掉为止）每小时清一次更早的轮次。文件总量受 `MEDIA_MAX_GB` 约束：超过后最久没用到的先删，轮次还在，那些图片的位置显示一个指向空处的引用；形象正在用的视频片段不会被清掉。删除时磁盘一时不肯放手的文件，每次清理都会再试，直到删掉为止。`/v1/me.contribute.record` 告诉 App 保留了什么：`{on, turns, own, files, media_bytes, keep_days}`，`POST /v1/me/contribute` 的回答里也带同样的 `record`。`/app` 的账号页在「帮助改进」开关上方显示记录（轮次、用自己 key 的轮次、文件数、中继保留多久），只要记录或训练轮次任一不为空，就给出那一个删除入口。

**提问和调用（0.31）。** 一个人的一句话往往要让 agent 调用好几次模型：先要一张截图，点一下，再看一次屏幕，再回答。记录是一次调用一行，照行数算就把人问的次数算多了；中继现在按两个口径一起算。每一行都记下它是不是*开了一问*（`turn_start`）：App 报了 `step` 就按它来（1 是开问）；没报的，看请求里最后一条消息——来自本人的开问，来自工具或助手的是接着上一步；两种消息都没有的也算开问。每一行还带 `turn_key`，即开了这一问的那一行的 id（接着上一步的行按对话里的 `turn` 号找到它，找不到就取同一对话里最近的上一个开问行），这样一问的所有调用在 SQL 里就能归到一组；训练视图的形状行带同样的两个字段。更早的行由分析循环里的回填从最旧的开始补上；没补到之前两个口径都不计，`GET /v1/admin/record` 的 `questions.pending` 报出它们的数量。数字在：`/v1/admin/record` 的总计、周期和每一天里 `n` 旁边多了 `questions`，另有一块 `questions`（多少问、其中带图的和用到屏幕操作的——按 App 报的轨迹算——有多少、每问用了几次调用按 `1`、`2-3`、`4-7`、`8-15`、`16+` 分桶、以及平均值）；`/v1/admin/data` 的总计、每天、按模型、按平台、按发起方式、按所用 key 和按账号里 `samples` 旁边多了 `turns`。

**这要花多少。** 一行调用记录里带着请求正文，而数字要加的那几列排在正文后面，所以以前每算一遍都得把每一行的正文走一遍：30 GB 的库上，一周的调用要算半分钟，缓存冷的时候更久。现在这些数字和逐问查看的列表改读一个只含这几列的索引（`turns_figures`，升级后第一次启动时把记录过一遍建好），一秒以内出结果。回填一次读写记录的一百行，每二十五行提交一次，每页之后停的时间和这页花的一样长，这样它跑着的时候控制台和 App 照样有盘可用：十万次调用大约一个小时补完。

要把一问完整看下来，`GET /v1/admin/record/turns` 按最新在前返回一个个提问，每问由它的各次调用一次性排好：本人的那条消息，每次调用一步（这一步的数字、模型说了什么或调了哪些工具、下一次调用之前收到了什么——工具的返回、双手的截图、本人补充的话），本人看到的回答，依次调过的工具，以及加总的数字（`calls`、token、`media`、`models`、`sources`、`partial`）。超过 4000 字的文本截断并标 `truncated: true`；整条调用在 `GET /v1/admin/turns/{id}`。筛选：`account_id`、`conversation`、`platform`、`run`、`source`、`model`、`script`、`media=1`（这一问里某处带图）、`hands=1`（报了轨迹）、`since`；每页最多 100，用 `before`（这一问最后一次调用的时间）和 `before_key` 翻页。控制台的「逐问查看」页显示的就是这些：图片和截图就在发出的位置显示（带管理口令取回，单靠 `<img>` 做不到），每个工具调用的参数折叠着，最终回答标出来，整条调用一点就开；「数据与同步」页原先数调用的地方都把提问数并排给出；账号抽屉的「留存轮次」页签（一行一次调用）有一个链接，直接跳到按这个账号过滤的逐问查看。

## 来历 {#provenance}

一次模型调用只是一段对话里的许多次之一，而 App 知道一些请求体里看不出来的事。中继 0.31 起，App 在聊天请求上用几个请求头说明它们，用自己 key 跑的轮次传上来时（`POST /v1/turns`）则用同名字段（请求体没写的，由请求头补上）。每一项都可选；旧版 App 一个都不发，中继记为「未说明」，绝不猜。

| 请求头 | 请求体字段 | 含义 |
| --- | --- | --- |
| `X-NanoMuse-Run` | `run` | 谁发起的这一轮：`person`（有人打字或点了一下）、`schedule`（定时任务）、`feed`（动态的每日例行）、`goal`（目标的检查或评估）、`hub`（这台设备替另一台设备的请求跑的）。小写，`[a-z][a-z0-9_]{0,23}`；中继没见过的词照记 |
| `X-NanoMuse-Turn` | `turn` | 这一轮在对话里的序号，从 1 起：本人的第一条消息是第 1 轮，对第二条消息的回复是第 2 轮 |
| `X-NanoMuse-Step` | `step` | 这次模型调用在本轮里的序号，从 1 起：调用了工具的一轮会有好几次 |
| `X-NanoMuse-Trajectory` | `trajectory` | 这次调用所属的屏幕操作任务的 id（`[A-Za-z0-9_.:-]{1,80}`），同一个任务的每一步都一样 |
| `X-NanoMuse-Trajectory-Step` | `trajectory_step` | 这一步在任务里的序号，从 1 起 |
| `X-NanoMuse-Platform` | `platform` | 当 User-Agent 说不清时 App 自己报的平台（桌面版的上传走 Node，运行时的调用走 SDK）：`android`、`ios`、`desktop`、`windows`、`macos`、`linux`、`runtime`、`browser` 之一。别的值一律忽略，仍由 User-Agent 决定 |

`X-NanoMuse-Device` 和 `X-NanoMuse-Conversation`（1.0.7）不变，和这些一起发。中继把这六项记在记录里这一轮自己的行上（`run`、`turn`、`step`、`trajectory`、`trajectory_step`，说明了的在 `GET /v1/turns` 里读得回来），开关开着时记在留存轮次的 meta 里，记在这次调用的遥测行上（`run`，这样用量页和平台页能分清一个人发的和例行任务发的），也记在训练视图的形状行上。记录的行上还有 `script`，一个词说明本人最后那条消息用的文字（`zh`、`ja`、`ko`、`ru`、`ar`、`th`、`hi`、`he`、`el`、`latin`，或没有），在写入这一轮时算出来，代替大多数 App 留空的 `Accept-Language`。

## 客户端事件 {#client-events}

中继 0.31 起，App 把请求本身看不出来的、一轮前后发生的事回报上来，形式是只有代号和数字的短记录：`POST /v1/events`，请求体 `{"events": [{kind, ts?, turn?, conversation?, data}]}`，一次最多 100 条，一个账号每分钟最多 60 次（超过回 429，剩下的晚点再发）；回答是 `202 {kept, dropped}`。`kind` 是点分的小写词；`turn` 是记录里这一轮的 id（Cloud 轮次是响应头 `x-nanomuse-request`；自己 key 的轮次用 App 自己的 `id`，旁边加 `"source": "own"`，中继会换成记录里的 `own-…` 形式）；`data` 是一个扁平对象，最多 16 个短代号、数字和布尔值。看起来像句子的值（超过 120 个字符，或不在 `[A-Za-z0-9_.:/ -]` 里）会被丢掉，嵌套对象会被丢掉，形状不对的一整条会被丢掉并计数，而不是整个请求被拒：中继就是这样兑现「这里不会传任何消息内容」的承诺。类型和各自的 `data`：

| kind | data |
| --- | --- |
| `sentinel.decision` | `tool`、`risk`（`safe`、`moderate`、`sensitive`、`critical`）、`decision`（`allow`、`ask`、`deny`）、`grant?`（`once`、`schedule`、`conversation`、`always`：放行它的那条授权）、`policy?`（问人之前策略本身的判定）、`by?`（最后由谁定的：`policy`、`auto`、`grant`、`person`、`timeout`）、`channel?`、`tainted?`（布尔）、`warnings?`（条数）、`ok?`（布尔：工具随后有没有正常跑完；桌面版会发，运行时不发）、`class?`（手机自己给这一步的分类：Android 的风险闸门发 `safe`、`install`、`destructive`、`outbound`、`remote`、`money`；iPhone 的权限检查发 `privacy`、`media`、`system`，即 `apple-*` 命令的类别） |
| `approval.result` | `tool?`、`risk?`、`allow`（布尔）、`scope?`（`once`、`schedule`、`conversation`、`always`）、`by?`（`person`、`timeout`、`other_device`、`auto`：应用自己答了不，比如 iPhone 不在前台时收到的 hub 任务）、`waited_s?`、`channel?`、`warnings?` |
| `turn.stopped` | `reason`：`wrong`、`slow`、`changed_mind`、`done`、`other`、`skipped`（人手动停了一条回复，说了或没说为什么）、`turn_no?` |
| `turn.feedback` | `vote`（`up`、`down`，收回时是 `none`）、`reason?`（`wrong`、`unhelpful`、`unsafe`、`slow`、`other`）、`turn_no?` |
| `turn.ended` | `ended`：`aborted`（人按了停止）、`error`、`abandoned`（一轮中途结束，用 App 自己的词；运行时对每次被停掉的运行都发 `aborted`，不管跑在哪个 key 上）、`turn_no?` |
| `hands.step` | `trajectory`、`step`、`action`（动作的种类：`tap`、`type`、`open_app`……；`end` 表示这次运行结束）、`outcome?`（`ok`、`failed`、`refused`、`stopped`、`handed_over`；`end` 那条上是整次运行的状态：`done`、`ask`、`blocked`、`stopped`、`failed`、`max_steps`）、`latency_ms?`（模型在这一步花的时间） |
| `app.opened`、`screen.viewed` | `screen?`（页面的代号） |

运营者在 `GET /v1/admin/client-events` 读它们（最新在前；`kind=` 逗号分隔，`account_id=`，`before=` 上一页最后一条的 id），以 JSON lines 导出（`/v1/admin/client-events/export?since=`，带化名 `subject`，不带账号 id），并在管理页「数据控制」面板看数字（`/v1/admin/client-events/summary?days=`：按天和类型的条数，以及每种类型各代号的分布：Sentinel 判了什么、审批怎么走的、回复为什么被停、赞踩各多少）。*设置 → 数据控制* 的删除把它们和轮次一起删；注销账号也一起删。

## 删除台账 {#deletions}

从导出做出来的训练集比中继里的行活得久：当一个人删掉留存的数据（`DELETE /v1/me/samples`）或注销账号（`POST /v1/auth/delete`）时，中继往一份台账里写一行——这个账号的化名 `subject`、时间和范围（`samples` 或 `account`），关于这个人的其他一切都不留。`GET /v1/admin/deletions?since=` 按时间顺序列出这些行；谁用导出来构建数据集，每次构建前先读它，把这些化名的每一行都剔除。化名在没有中继密钥时指不出任何人，这份台账是账号注销后有意留下的唯一一样东西。个人控制台的「数据控制」页在删除按钮旁这么写，隐私页也这么写。

## 对话同步 {#conversation-sync}

*设置 → 数据控制 → 在我的设备之间同步对话*（0.1.36，中继 0.19）是那一页上的另一个开关，登录账号**默认开启**。开着时，每台设备把自己各轮的文本推到中继，并拉取别的设备推上来的，于是手机、电脑和网页版显示同样的聊天：每个对话的标题、谁发起的，每条消息的角色、文本、时间和设备。文件和图片不上传；同步的消息只带附件的名字和大小，文件留在生成它们的设备上。在一台设备上删除一个聊天，所有设备上都删除；重命名也一样。发给另一台设备的聊天，或替某台设备跑的聊天（「来自 Pixel 8」），完全不同步。

**一条线**（0.1.37）。一个账号只有一个主要聊天，每台设备的主要聊天*就是*它：第一台推送的设备定下它的 id，其他设备沿用（`main_exists` → `cid_main`，登录时先拉取），每台设备的主要聊天显示所有设备上说过的话的并集，按时间排序（时间相同时本地消息在前；消息以 `mid` 识别，所以不会重复显示，设备自己的消息传回来也会被忽略）。在另一台设备上写的消息是一个只读气泡，下面标着「来自 Pixel 8」，模型会把它和对话的其余部分一起读。从中继拉下来的旁聊立刻就是这台设备上的一个聊天，带着它的标题和时间，并在同一个对话 id 下继续。这个人的消息一发出就上传（其他设备实时看到，在回复之前），助手的最终文本则在这一轮结束时上传；登录或打开开关时，设备会把自己全部符合条件的历史发上去，从最旧的开始，每次请求 200 条。muse 的名字是账号 profile 的一部分：在任何设备上改名，包括第一个对话里的起名，下次拉取时就会传到其他设备。

**主要聊天优先**（0.1.38，中继 0.20）。默认只有主要聊天在设备之间走：旁聊留在创建它的设备上，设备拉取时带 `scope=main`，别的设备的旁聊永远不会到来。「同时同步旁聊」（「数据控制」下的第二个开关，默认关，**按设备**；中继没有账号级的设置）把打开它的那台设备反过来：它的旁聊上传，其他设备的旁聊下载，切换后的第一次拉取从零重新开始。有两种聊天不管开关开没开都不会走：桌面版替另一台设备的任务开的聊天（「From Pixel 8」，那是那台设备的对话），以及桌面版的房间替自己开的聊天，比如动态每天那一批（「Feed · <日期>」，跑完即归档）——这些是智能体的工作台，不是人的对话；1.0.9 及之前，那一批确实每天作为旁聊到过手机上（[#713](https://github.com/nano-muse/nanoMuse/issues/713)）。全新登录的第一次拉取请求的是**尾部**（最新的 300 条消息及其所属对话），这样很长的历史能立刻打开，不用从头翻页；跳过的更早消息留在中继上，不再拉取。一台设备正在回答时，其他设备在最后一条消息下面显示「kwai 正在处理…」：这是一条 `working` 提示，经过中继的内存和 hub，从不保存，设备一直不说完成的话，十分钟后就消失。

中继每个账号最多保留 20 000 条消息（最老的对话的消息先删，标题保留）、2 000 个未删除的旁聊（中继 0.23：超出后新的旁聊被拒绝，原因 `conversation_limit`，留在设备上；删掉一个就腾出一个位置），每条消息 16 384 字节（更长的文本被截断并标记 `truncated`）。在任何一台设备上关掉开关都会通知中继，中继删掉保存的全部内容，并用 `sync_off` 拒绝其他设备，直到开关再次打开；它们的开关跟着变。同一页上的「删除已同步的对话」清空存储，开关保持原样。除了账号的设备没人能读这个存储：运营者的管理页只显示数量（开着和关着的账号数、多少对话和消息、占多大），从不显示文本，也不显示是哪个账号（`GET /v1/admin/sync`）。拉取由 hub 的 `sync` 帧触发（[hub.md](hub.md#frames)），在启动时、hub 套接字重连或桌面窗口切回前台时，以及每分钟一次；在桌面端，已经从另一台设备收到的轮次会排在它到达之后本机发出的消息上方，即使两台设备的时钟不一致。

API，全部在账号的 key 之下（没有 key 是 401；开关关着时读写都是 409 `sync_off`）：

```
GET    /v1/sync/state                   → {enabled, cursor, counts{conversations, messages}, limits{messages, text_bytes, conversations}, working[]}
PUT    /v1/sync/state   {enabled}       → the same; false deletes everything stored, the counter keeps counting
GET    /v1/sync/changes ?since=0&limit=500&scope=all|main&tail=K   → {cursor, more, conversations[], messages[], skipped?}
POST   /v1/sync/changes {device, conversations[], messages[]}   → {cursor, accepted, rejected[{cid | mid, reason, cid_main?}]}
POST   /v1/sync/working {cid, working, device?, state?, detail?}   → 204; the hub tells the other devices (0.31: state and step ride along)   404 no_conversation
DELETE /v1/sync/changes                 → the state, counts at zero     everything stored, switch unchanged
DELETE /v1/sync/conversations/{cid}     → {cursor, deleted: true}      a tombstone the other devices apply; 404 no_conversation
```

`scope`（中继 0.20）不写就是 `all`；`main` 只返回主要聊天及其消息，还没有主要聊天的账号得到一个空页，其 `cursor` 是账号的计数器。`tail=K`（K ≤ 500，只在 `since=0` 时生效）按 `seq` 顺序返回最新的 K 条消息、它们所属的对话、位于账号计数器的 `cursor`、`more: false`，以及 `skipped`（略过了多少条更早的消息）。从中继 0.25 起，只要账号有主要聊天，tail 页就一定带上它的那一行，哪怕最新的 K 条里没有它自己的消息，这样新设备第一次拉取就认领 `cid_main`，而不是先造第二个 main、再从 `main_exists` 的拒绝里学到那个 id（1.0.3 的客户端把多出的这一行当作普通对话行处理，行为不变）。其他任何 `scope` 都是 400 `bad_scope`。`POST /v1/sync/working` 表示 `device`（或 `X-Nanomuse-Device`）里指名的设备正在 `cid` 里回答（`working: true`）或已经结束（`false`）；中继把活跃的那些在内存里保留十分钟（从不进数据库，所以重启就忘），在状态的 `working` 下列出（`[{cid, from, device_name, working, at}]`），并向账号的其他套接字发一个 `working` 帧（[hub.md](hub.md#frames)）。请求正文超过 `MAX_REQUEST_BYTES`（0.20 起默认 16 MiB）是 413 `too_large`，附一句「请求正文 N MB；这个中继最多接受 M MB」。

重试时沿用原来的 `mid`，包括中继已经接收消息但响应丢失的情况。桌面端根据设备、本地会话和本地消息行 ID 生成新消息的 ID，并继续识别已经保存的消息 ID。允许的 ID 格式和其他客户端使用的 UUID 保持不变。桌面端在上传前保存会话映射，因此响应丢失并重启后，会话 ID 也保持不变。

一个对话是 `{cid, kind: main | side, title, device, device_name, created_at, updated_at, deleted, seq}`，一条消息是 `{mid, cid, seq, device, device_name, role: user | assistant, text, truncated, attachments[{name, mime, size}], created_at, deleted}`；`cid` 和 `mid` 是设备生成的不透明 ID（4–64 个字符，取自 `a-z 0-9 . _ : -`，折叠为小写），时间是 Unix 秒。每个被接受的变更拿到账号的下一个 `seq`；设备记住自己拉到过的最高 `cursor`，下次用 `since=` 它来请求。推送是幂等的（已知的 `mid` 原样不动，除非新行是墓碑记录；已知的 `cid` 取较新的标题；比中继时钟晚一周以上、或早于对话开始的时间，按对话的 `created_at` 读，中继 0.25。更早的中继从 `created_at` 起算这一周，所以超过一周的聊天每一次改名都被丢掉），而且一次最多 200 条消息或对话（413 `too_many_messages`）。一页按 `seq` 顺序列出它的对话和消息，中继还会把页里每条消息所属的对话一并加上，即使那个对话自己的 `seq` 在更后面（重命名会把它挪后），所以客户端先应用页里的对话、再应用消息，永远不会拿到一个没有归属的孤儿。拒绝会指名那一行：第二个 `main` 被推上来时是 `main_exists` 加 `cid_main`（设备随后改用 `cid_main` 重发），还有 `conversation_limit`（中继 0.23，账号的旁聊已到上限）、`unknown_cid`、`conversation_deleted`、`bad_cid`、`bad_mid`、`bad_kind`、`bad_role`。墓碑记录保留 30 天，然后清扫掉。推送被接受或删除之后，hub 用一个 `sync` 帧通知账号的其他设备（控制台发出的 `DELETE` 在 `X-Nanomuse-Device` 里带着执行删除的设备，好让它跳过自己的回声）。

## 额度 {#allowance}

管理控制台的用量日期、日期选择器和用户注册图表，都按中继的 `DAY_OFFSET_H` 划分日期。
浏览器处在不同时区时，也不会把日期标签或注册人数挪到相邻的一天。

nanoMuse 是社区项目，不收费。`cloud.nanomuse.cn` 这个公共中继由开发者出钱，所以每个账号有一个可以取用的池子，按账号的整个生命周期算，不按天（中继 0.5）：

| | `cloud.nanomuse.cn` |
|---|---|
| 注册 | 任何有中国大陆手机号或邮箱的人都可以 |
| 免费额度 | 写这篇时是**每个账号 ¥10**，用于托管的 Qwen 对话、图片输入和 GUI 操作模型；不重置。数字由中继决定（可以不更新 App 就上调；App 显示的是中继说的数，`/v1/config`），账号页始终显示当前的 |
| 邀请 | 每有一个*新*人用你的邀请码注册，你的池子加 **¥5**（同样是中继定的数），对方也加同样多；两边都在朋友第一次发请求之后到账，不是注册时 |
| 用完之后 | 用自己的 key 或你已经在付费的套餐：在中国大陆，优先[阿里云百炼](own-key.md)（一把 key 覆盖聊天、手、图片和短视频）；其他地方优先 [OpenRouter](https://openrouter.ai/keys) 或 OpenAI（百炼只接受中国大陆的注册）；ChatGPT、Claude 或 Kimi 套餐在有该登录流程的客户端上登录；任何 OpenAI 兼容端点都可以；登录和你的设备不受影响 |
| 成员 | 开发者和他们列出的人没有上限，也可以指定托管服务商的其他聊天模型；托管生图和生视频对成员同样关闭 |
| 速率 | 每分钟 30 次请求 |
| token | 没有上限；用量会计量并显示 |

`Qwen/Qwen3.6-27B-FP8` 按每百万 token 输入 ¥3、输出 ¥12 计费，缓存命中的输入按输入价的 20% 计，以回复里的 `usage` 为准；推理 token 算输出。把图片发给对话属于这个多模态聊天请求，不是生图。托管 Cloud 不再提供生图和生视频，因此也不会从账号额度中扣这两类费用；需要这些能力时，请在客户端接入你自己的供应商和 API key。

*设置 → nanoMuse Cloud* 显示池子用了多少（以 ¥ 和 $ 计）、还剩多少、池子怎么增长。用到 80 % 时 App 提示一次；池子花完后中继以 `allowance_exhausted` 拒绝，App 显示接下来的路：自己的 key、你已经在付费的套餐，或者邀请（你们各加 ¥5，或者中继当天说的数）。先推荐哪家服务商取决于你在哪里（0.1.34：中继的 `region`，从号码的国家码或它自己磁盘上一份 ip2region 的离线副本读出；什么都不往外发）：中国大陆账号被指向阿里云百炼（服务商表单打开时已经预填好，[指南](own-key.md)），其他所有人指向 OpenRouter 或 OpenAI，因为百炼只接受中国大陆的注册。

中继 0.21 起，拒绝响应和 `/v1/me` 把整张卡片作为数据带上，而不只是两个链接（契约 C11）：`spend.guidance`（以及 `allowance_exhausted` 错误旁边的 `guidance`）按顺序列出该地区的服务商和每家 key 覆盖的范围（`covers: chat | vision | image | video`，来自共享目录 [`nanomuse/llm/providers.json`](../../nanomuse/llm/providers.json)，中继自带一份副本）、一个人可能已经在付费的套餐和哪些客户端能用它们登录（`plans`：ChatGPT 到处都行，Claude 和 Kimi 在手机上，OpenRouter 在手机上）、本地服务器（`local`）、文档链接，以及关于 ChatGPT 登录的那句实话（`caveats.chatgpt`、`caveats.chatgpt_zh`）。0.17 的 `ways` 行仍然发送，现在每行带着服务商的 `name`、`name_zh`、`key_url`、`covers` 和 `auth`，所以 0.1.38 的客户端照旧画出它一直画的那两个按钮。`/app` 的控制台用 `guidance` 画卡片，遇到旧中继则退回两个链接。厂商要求每个对话带一个固定 id 的服务商（目录里的 `session_header`，比如 OpenCode Go）单独列在 `session_providers` 里，并写明那个请求头：1.0.1 及更早的手机端只读 `providers`，也不发这个 id，所以不会推荐它；会发 id 的应用把这份列表接在 `providers` 后面。其他中继可以定其他规则（`ALLOWANCE_CNY`、`INVITE_BONUS_CNY`、`SIGNUP_OPEN`、`ALLOWED_IDENTIFIERS`；三个数字都能在中继运行时调整，中继 0.15；见 [`cloud/README.md`](../../cloud/README.md)）。运营者能看到谁邀请了谁：管理页的「邀请」视图按邀请码带来的账号数给邀请人排序，并列出其中有多少人用过、有多少人还待到账（没发过第一次请求，所以还没有奖励）、有多少人的地址与邀请人相同；一个账号的页面写明它的邀请人，并列出它带来的人（`GET /v1/admin/invites`）。给自己刷额度不划算：被邀请人必须在与邀请人不同的网络地址累计产生真实成功消费，达到 `INVITE_SETTLE_MIN_SPENT_UY`（默认 200 微元），奖励才到账；Hub 设备记录不能代替消费。邮箱的 `+tag` 子地址与 Gmail 的点号或 `googlemail.com` 别名都归入同一个账号；一次性邮箱域名（内置名单 `DEFAULT_SIGNUP_DOMAIN_BLOCK` 加 `SIGNUP_DOMAIN_BLOCK`）直接拒绝新注册；来自非知名邮箱服务商域名的新账号按天限量（`SIGNUP_PER_DOMAIN_DAY`，默认 5；拒绝码是 `domain_limited`）；健康检查会提出两种警报，一天之内邀请码带来超过十个账号的邀请人，以及带来二十个以上账号而几乎没人发过请求的邀请人。「邀请」视图里每个展开的邀请人、以及它账号页的「邀请的人」卡片，都有一个动作：收回邀请奖励（已经花掉的部分不动），并可同时停用这个账号、删除它邀请来的从没发过请求的账号（`POST /v1/admin/invites/abuse`）。运营者对账号的每个操作都有记录：停用或启用、设为或取消成员、赠送、充值、改额度池、改设置和删除，每一个都在「控制」区的审计日志里留一行（谁、从哪里、对哪个账号，账号只记 id 的前八位），账号自己的时间线也记一笔；删除会计入统计页。被停用的账号申请登录验证码时得到和任何人一样的 `204`，但不会发出任何短信或邮件：这次请求照常计入频率限制，接口不透露这个号码有没有账号、账号有没有被停用；本人用验证码登录、或密码输对时才会看到 `403 account_disabled`（密码输错得到的回答和任何错误密码一样）。

nanoMuse 只求一样回报：在 [GitHub](https://github.com/nano-muse/nanoMuse) 上点一个 star，这是帮项目被人找到的东西。什么时候开口由中继定，不由 App 定（0.1.35）：`GET /v1/nudges` 说明什么时候问是合理的：它替你完成第三、第十和第三十个任务之后，你打开它的第七天和第三十天，达成一个目标时，画出一个新形象时，在账号页上一次，以及池子花完时，两次之间至少隔一周，每台设备最多四次。每次都是一张出现在当下位置的卡片；「以后再说」也算一次，去过那个页面或点了「已经点过了」之后就不再出现（只记在本机，账号不同步这个标记）。运营者在管理页（*设置 › 请求 star*）改这项策略，不用更新 App；每个 App 都内置同样的默认值，供连不上中继时使用。策略定的是*什么时候*，运营者愿意的话也可以定*说什么*：卡片上的文字默认是每个 App 自己的、用它的语言写的；策略里带了句子就用策略的：`star.text`（英文）和 `star.text_zh`（简体中文），各最多 200 字，默认为空。中文界面的 App 先看 `text_zh`，没有再看 `text`，都没有就用自己的句子；其他语言的 App 看 `text`，没有就用自己的。只换卡片上的那句话，标题和按钮还是 App 自己的。按中继 0.22 及更早版本做的 App 不认这两个字段。

## 控制 {#controls}

在管理控制台，用户表格或用量单日详情里的账号排行点过「更多」后，轮询刷新不会收起
已经展开的行。列表变短时，展开范围会随之缩小。

运营者可以不重启、不重新部署就暂停中继的某些部分（中继 0.22，管理控制台的「控制」；命令行是 `nanomuse-cloud admin controls …`；见 [`cloud/README.md`](../../cloud/README.md#controls-022)）。六个开关，默认都开，都存在数据库里所以重启后不变，每次切换都在审计日志里记一行：谁、什么时候、为什么。五个「暂停」开关里某一个关着时 App 看到的是：

| 开关 | 关着时 App 得到什么 |
|---|---|
| **免费额度** | 受限账号（没有自己的 key，也不是成员）请求模型时得到 **429 `allowance_exhausted`**，带 `paused: true` 和 `reason: "allowance_paused"`，和池子花完时形状相同，所以每个 App 像今天一样显示它的「自己的 key」卡片，只是消息说额度暂时暂停，而不是花完了。成员、登录、设备和同步不受影响 |
| **注册** | 还没有账号的手机号或邮箱从 `POST /v1/auth/code` 和 `/v1/auth/verify` 得到 **403 `signup_closed`**，在发出任何验证码之前；`/v1/config` 里的 `signup_open` 变成 false。所有已有账号照常登录、照常使用 |
| **云服务** | 每个 API 调用都回答 **503 `service_paused`**，带 `paused: true`，例外是健康检查、`/v1/config`、管理控制台和 `/v1/admin/*`；每条 hub 套接字以 `4003 hub_paused` 关闭。什么都不删；已登录的 App 保留它的 key，开关恢复后重新登录 |
| **对话同步** | `/v1/sync/*` 的推送和拉取回答 **503 `sync_paused`**；`GET /v1/sync/state` 仍然应答并说 `paused: true`。已存的内容保留；每台设备各自继续工作 |
| **设备 hub** | `WS /v1/hub` 接受后立即以 **4003 `hub_paused`** 关闭，已打开的套接字以同样方式关闭，`GET /v1/devices` 回答 503 `hub_paused`。每台设备各自继续工作 |

关着的开关列在 `/healthz`、`/v1/config`（公开，缓存一分钟）和 `/v1/me` 的 `paused` 下，客户端可以在尝试之前先说明原因。各个 App 把这些码当成普通的拒绝处理：手机和控制台显示中继的那句话；`allowance_exhausted` 这个形状它们本来就会画成一张卡片。

第六个开关**只服务 nanoMuse 客户端**（中继 0.28，默认开）方向相反：开着时，模型只回答 nanoMuse 的手机 App、桌面版、Python 运行时和浏览器里的网页控制台；其他软件拿着 nanoMuse 的 key 调 `/v1/chat/completions`（池子的 worker、SDK、脚本、未改名的上游 App）得到 **403 `client_not_supported`**，`client` 里写着客户端的名字，消息说在那里请用自己的 key。中继看的是 `User-Agent`，所以它挡住的是诚实的程序，不是伪装者。成员用什么都能被回答；登录、账号页、同步和 hub 不受影响；一次拒绝不花钱，只在账号时间线上记一行 `client.refused`。各个 App 永远不会碰到这个码，因为它们都报了自己的名字；1.0.6 及更早的运行时调用模型时带的是 OpenAI SDK 自己的名字，中继按这个名字认出它（运行时从 1.0.7 起报自己的名字）。关掉后，中继像 0.28 之前一样回答任何持有效 key 的客户端。

**阈值。** 一条规则说「账号数达到 N 时，做一件事」：关闭注册、暂停额度、暂停同步，或者只是通知。规则在创建账号时检查，另外每分钟一次；一条规则只触发一次（触发时的数字和时间会保存并显示），「重新启用」或改动阈值能让它再次触发。每次触发写一行审计日志和活动时间线上的一行；「通知」还会通过 SMTP 设置给中继的 `ADMIN_EMAIL` 发一封邮件（只有数字和中继的地址，不涉及任何人）。开关的状态和下一个阈值是管理面板的第一行。

## 自己部署 {#running-your-own}

API 请求和错误计数在线程池中写入。响应会等待计数写入完成；计数写入等待数据库锁时，不占用事件循环。

任何人都可以跑一个中继（给一家人、一个班、一家公司），然后把 App 指向它。服务器是 SQLite 之上的单个 Python 进程；一台装了 Docker 的 VPS 加一个域名就够了：

```bash
cd cloud
cp .env.example .env    # domain, secrets, upstream key, how codes are sent
docker compose up -d    # Caddy fetches the TLS certificate
```

[`cloud/README.md`](../../cloud/README.md) 有各项设置、发送方式的选项（邮件走 SMTP，大陆手机号走阿里云短信）、充值用的管理端点，以及测试套件。

一个人或几个人用的中继：`SIGNUP_OPEN=0` 加 `ALLOWED_IDENTIFIERS=139…, me@example.com`，只让这些号码和地址登录；其他人在发出任何验证码之前就得到 `not_invited`。试用部署就是这么跑的。注册开放时，同一份列表指定的是没有每日上限的成员；管理页可以再加。

为了应用商店的审核，`REVIEW_ADDRESSES` 和 `REVIEW_CODE` 给审核员留一条进路：对这些邮箱之一请求验证码时什么都不发，但回答得像发了一样，而六位的 `REVIEW_CODE` 可以登录，受和所有人一样的验证码有效期、尝试次数和速率限制约束。这个账号是普通账号；管理页给它打上「review」标签，并把它排除在注册计数之外。两者都为空（默认）则一切照旧。细节在 [`cloud/README.md`](../../cloud/README.md#for-app-store-review)。

中继也是账号各设备的会合点：`/v1/hub` 的 **hub** 和 `/app` 的网页控制台；见 [hub.md](hub.md)。`HUB_ENABLED` 可以关掉它，`HUB_FRAME_LIMIT` 限制单帧大小（文件和截图在帧里传，默认 16 MB）。

各端默认连 `https://cloud.nanomuse.cn`。手机登录表单下面的「使用其他服务器」可以填你自己跑的中继地址（[android.md](android.md)、[ios.md](ios.md)）；桌面端从插件的 `config.baseURL` 读（[desktop.md](desktop.md)）；网页控制台就是在 `/app` 提供它的那台中继。

## 协议 {#protocol}

App 的调用，全部是 JSON：

```
GET  /healthz                                                 → {ok, version, models[], paused[]}; no key
GET  /v1/config                                               → {version, signup_open, paused[], allowance_cny, allowance_usd, invite_bonus_cny, invitee_bonus_cny, usd_cny, invite_url, own_key_docs, openrouter_url, privacy_url, repo_url, improve_default, code_ttl_s, password_min_len}; no key, a minute's cache
POST /v1/auth/code          {identifier}                      → 204（被停用的账号得到同样的 204，不发任何东西）; 400 phone_region, 403 not_invited | signup_closed, 429 code_too_often | domain_limited, 502 send_failed
POST /v1/auth/verify        {identifier, code, device, invite?, device_id?, device_kind?} → {api_key, base_url, account, tokens, models, created, region}; 可选的身份把 key 绑到那台 Hub 设备（hub.md）；400 code_wrong | code_expired | bad_device, 403 account_disabled
POST /v1/auth/login         {identifier, password, device, device_id?, device_kind?} → the same; 401 bad_credentials, 429 locked, 400 bad_device
POST /v1/auth/password      Bearer  {password, current?}      → 204; "" with current removes it; 400 password_short | password_long | password_weak | password_wrong | password_required
POST /v1/auth/session-key   Bearer  {device?, ttl_s?}         → {api_key, expires_at}; a key that lapses on its own (90 days at most); 403 session_from_session
GET  /v1/me                 Bearer                            → {region: cn | intl | unknown, account{…, has_password, sessions, signed_in_via}, usage{today, total by kind / model}, tokens, spend{…, ways, guidance}, invite, contribute, models, defaults, base_url, clips, recent, nudges, paused[]}
GET  /v1/me/invite          Bearer                            → {code, url, invites, bonus_cny, invitee_bonus_cny, bonus_when: "first_use", settled, pending, earned_cny, friends[]}
GET  /v1/estimate           Bearer  ?images=5&clips=4&image_model=&video_model=&size=  → {cny, usd, parts[{kind, model, count, seconds?, cny}], left_cny, grant_cny, unlimited, affordable}; nothing charged
POST /v1/me/contribute      Bearer  {on}                      → {on, samples, default_on, keeps[], privacy_url}; the "help improve" switch
DELETE /v1/me/samples       Bearer                            → {deleted}; every turn kept from this account
GET  /v1/nudges                                               → {version, star{enabled, url, moments{signed_in, tasks[], new_look, exhausted, days_used[], goal_done}, cooldown_days, max_asks, text, text_zh}}; no key, cached an hour
GET  /v1/me/profile         Bearer  ?face=false               → {rev, device, name, avatar, …, face?, connectors: [{id, label, url, auth, device, device_id, enabled, at}]}
PUT  /v1/me/profile         Bearer  {device, name?, avatar?, …, face?, connectors?}  → {rev, device}; a field that is absent keeps what is stored (relay 0.25); a device's connectors replace only its own; 400 no_secrets_in_profile, too_many_connectors
DELETE /v1/me/profile       Bearer                            → 204
GET  /v1/me/sessions        Bearer                            → {sessions: [{prefix, device, via, created_at, last_used_at, expires_at, current}]}
DELETE /v1/me/sessions/{prefix}  Bearer                       → 204; 404 no_session
GET  /v1/me/events          Bearer  ?limit=50                 → {events: [{ts, kind, detail}]}
POST /v1/auth/sign-out      Bearer                            → 204
POST /v1/auth/sign-out-all  Bearer  {all?}                    → {signed_out}
POST /v1/auth/delete        Bearer                            → 204
GET  /v1/devices            Bearer                            → {devices: [{id, name, kind, os, version, actions[], online, last_seen, controllable, ip}]}; 503 hub_paused
DELETE /v1/devices/{id}     Bearer                            → 204; 409 device_online
```

`/v1/config` 里的 `code_ttl_s` 和 `password_min_len` 就是中继的 `CODE_TTL_S` 和 `PASSWORD_MIN_LEN`；网页控制台的登录表单和密码表单打印这两个数，所以设了别的数值的中继也能被说对，没有这两个字段的旧中继按十分钟和 8 位读。

其余都是 OpenAI API：`GET /v1/models`（带 `architecture` 模态，好认出图像模型，每个模型还有一个 `nanomuse` 块，含它的 `kind`、价格、`for`（聊天模型适用的通道：`chat` 和 / 或 `gui`）以及 `recommended_for`）、`GET /v1/models/{id}?kind=chat`（成员检查一个手动输入的 id：`listed`、`priced_as`）、流式的 `POST /v1/chat/completions`、`POST /v1/images/generations` 和 `/v1/images/edits`，以及走服务商自己路径的短视频（`POST /api/v1/services/aigc/video-generation/video-synthesis`、只能查自己任务的 `GET /api/v1/tasks/{id}`、`GET /api/v1/uploads`）。项目托管服务对图片/视频请求、上传、手动媒体模型查询、媒体估算和视频任务轮询，在调用上游之前统一返回 `410 hosted_media_retired`，并带 `action: configure_own_provider`。错误是 `{"error": {"message", "type": "nanomuse_cloud", "code"}}`，`code` 稳定不变，App 把它变成一句话。中继 0.22 加了运营者[开关](#controls)的码：`403 signup_closed`、`503 service_paused`、`503 sync_paused`、`503 hub_paused`（以及 hub 的关闭码 `4003 hub_paused`），还有免费额度是被暂停而不是花完时带 `paused: true` 的 `allowance_exhausted`；`/healthz`、`/v1/config` 和 `/v1/me` 在 `paused` 下列出关着的开关。

**模型开口之前（中继 0.31）。** 一次流式对话可能先收到几段没有 `choices` 的 chunk：`{"object": "chat.completion.chunk", "model", "created", "choices": [], "nanomuse": {"phase", "waited_ms", "ahead"?}}`。请求在中继的模型名额（`CHAT_CONCURRENCY`）前排队时，每 5 秒来一段 `phase: "queued"`，`ahead` 是排在它前面的请求数；轮到它时来一段 `phase: "working"`；没排过队的请求一段也不会收到。模型迟迟不吐出第一个字节的时候，每 10 秒发一行注释（`: keepalive`）。SSE 解析器按定义会跳过注释行，而没有 choices 的 chunk 正是每个客户端早已处理的只带 usage 的那种形状，所以不认识这些的客户端看到的回复和从前一样；手机和桌面读这个字段，告诉你前面还有几个、这一轮等了多久。非流式对话里没有这些；这些也不计费、不入账。

中继不认识的 key 得到 `401 bad_key`；0.1.40 起，账号已被删除的 key 改为得到 `401 account_deleted`，在每一个需要 key 的调用上都如此（`/v1/me`、`/v1/models`、`/v1/chat/completions`、同步和 hub 的调用），删除后持续 90 天；中继把已删除账号的 key 哈希保留这么久，别的什么都不留。不认识这个码的客户端看到的是和以前一样的 `401`；认识的客户端（手机）在 `account_deleted` 时删除账号的本地数据，其他情况都收起来保留（[sync.md](sync.md)）。完整的错误码表在 [`cloud/README.md`](../../cloud/README.md)。

设备：`GET /v1/devices` 列出账号的设备（在线或最后出现的时间），`DELETE /v1/devices/{id}` 忘记一台离线的设备，`WS /v1/hub` 就是 hub 本身；帧在 [hub.md](hub.md)。对话：`/v1/sync/state`、`/v1/sync/changes` 和 `/v1/sync/conversations/{cid}`；见上面的[对话同步](#conversation-sync)一节。
