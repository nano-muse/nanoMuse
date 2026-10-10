# nanoMuse Cloud

「现在就开始」这条路：用手机号（中国大陆；验证码走短信）或邮箱注册，拿一份免费额度，不用自己的 API key 就能用 nanoMuse。用自己的 key 的方式和以前完全一样：这只是多了一个服务商，不是替代。

## 在应用里 {#in-the-app}

0.1.20 起，账号是每个 App 的起点：第一屏要你填手机号或邮箱，发一个六位验证码（或者，设过密码的话，直接输密码），然后问由哪个模型来回答：账号自带的（Cloud），还是你自己的 key。短信验证码只发中国大陆号码（号码认证服务不往别处发）；香港、台湾或海外号码会立刻被告知（`phone_region`），改用邮箱登录。退出登录会回到那一屏（自己部署的：在运行时上设 `[cloud] required = false` 或 `NANOMUSE_CLOUD_REQUIRED=0`）。那一屏是门，不是墙：点「改用自己的 API key」就能越过它进入设置里的自备 key 路径；有了自己的 key，App 不登录也能用（聊天、动手、图片、短片），登录入口留在「连接」里（手机上是「设置 → nanoMuse Cloud」），用于 Cloud 模型、同步和你的设备。输完验证码后，App 有了：

- *设置 → 服务商* 下一个叫 **nanoMuse Cloud** 的服务商，一个普通的 OpenAI 兼容服务商，它的 key 就是中继发的 token；
- *设置 → 模型*（网页控制台：「连接」页）的四行在你没选过时落在账号的模型上：推荐的聊天模型、推荐的手的模型（读截图、操作手机或电脑的那个；中继菜单上每个模型都写明它是给这两者中的哪一个用的）、图像模型和视频模型。你没设过的一行按一个顺序走：对话模型所在的服务商是你自己的 key、而且能做这件事时用它，否则登录时用 nanoMuse Cloud，否则用你第一把能做这件事的 key；那一行的「自动」写着它现在给的是什么，以后再加一把 key 会先问「用它来做什么」，然后才会动任何一行（[own-key.md](own-key.md#which-model-does-what)）。

*设置 → nanoMuse Cloud*（「账号」页）显示谁登录了（一个打码的提示，从不显示号码）、从什么时候起；设置、修改或移除**密码**（八个字符以上；中继上用 scrypt；连续输错会锁一段时间，用验证码重新登录一次就解开）；今天花了多少额度，以 ¥ 和 $ 计，配一个仪表；**按类型的用量**（聊天、图片、视频）今天和累计，以及**按模型**的用量；**登录记录**：每一台持有 key 的设备、它怎么登录的（验证码还是密码）、最后一次使用的时间，每条都可以吊销；账号自己的**历史**（登录、改密码、被拒绝；从不包含消息内容）；还有几条退路：在这台设备「退出登录」、「所有设备退出登录」、「删除账号」。额度属于那个地址：再次登录，不管在这台手机还是另一台，拿到的是同一个账号的新 key，不会多给一份额度。

**退出登录在手机上留下什么**（0.1.40，契约 C12）。退出登录（在这台设备、在所有设备，或者为了换一个服务器）只问一个问题：「把这个账号的聊天留在这台设备上」，默认关。关着，账号的聊天、记忆、动态、目标、例程和形象会从手机上移除（同步开着的话，中继那里还留着聊天，下次登录能拿回来）；开着，它们被收起来，等账号再次登录时回来。改用另一个账号登录也要经过同样的退出流程。「删除账号」在中继删掉账号，也删掉手机上属于它的一切，不再多问；之后用同一个地址登录是一个全新的空账号。中继拒绝的 key（`401 bad_key`：另一台设备上点了「所有设备退出登录」、中继重置、中继的 bug）是一次手机上没人能回答的退出，所以手机把账号的数据像「保留」那样收起来，移除 key，登录页写着「这台手机上的登录已结束。重新登录即可继续；在那之前，你的聊天会留在这台设备上」；下次以同一个账号登录就恢复，换一个账号则什么也看不到。只有 `401 account_deleted`（0.1.40 起中继对账号已删除的 key 的回答）才让手机把数据删掉，因为已经没有可以回去的地方了。每一样状态存在哪里、每个事件发生时它怎么样，是 [sync.md](sync.md) 里的那张表。协议上唯一的新增是那个错误码；旧版中继两种情况都答 `bad_key`，手机就保留数据。

在它旁边再登录第二个服务商（你自己的百炼 key、DeepSeek、一台本地服务器）一如既往可行；中继的模型可以和你的放在同一个模型组里混用。

## 中继保存什么 {#what-the-relay-keeps}

中继就是 [`cloud/`](../../cloud/README.md) 里的代码。它存：

- 邮箱地址的加盐哈希（HMAC-SHA256）（0.1.18–0.1.21 的手机号账号继续可用）、一个打码的提示如 `so***@example.com`，以及地址本身的加密副本（AES-GCM，密钥由中继的 secret 派生），让运营者能在管理页上看到账号属于谁（单看数据库文件什么也看不出来）；
- 每个已发 key 的哈希，连同你登录时的设备名、方式（验证码还是密码）和最后使用时间；吊销的 key 保留它那一行，登录记录列表才能说明这一点；
- 密码，如果你设了，以 scrypt 哈希保存，从不保存密码本身；
- 每次请求：类型（聊天、图片、视频）、模型、token 数和扣费金额；
- 一条账号事件时间线（登录、登录失败、设置或修改密码、退出登录、因预算被拒、上游错误），细节是设备名、模型或错误码，从不是消息内容；
- 每个视频任务的 id，这样只有发起它的账号能轮询它；
- 智能体的名字和形象（`/v1/me/profile`）：它用的是哪一张（小龙、某个颜色底上的 emoji，或者形象工作室里画的一张，连同那张形象的五张小 WebP 图），好让账号的每台设备显示同一个。0.1.34 起，同一份 profile 还列出账号的**连接器**：哪台设备连接了哪个服务（一个标签；登录方式：OAuth、key 或开放；以及时间），这样另一台设备能说「已在你的 Mac 上连接」。凭据本身留在持有它的设备上；中继拒绝任何带着像凭据一样命名的字段的项。从不存 key 或设置。
- 中继 0.19 起，**同步的对话**（「在我的设备之间同步对话」，默认开）：账号聊天的文本（每个对话的标题、类型和由哪台设备发起，每条消息的角色、文本、时间和设备，以及附件的名字和大小，从不存文件本身），好让每台设备显示同样的对话。关掉开关会删掉全部；删除账号也一样。下面的[对话同步](#conversation-sync)一节有它的形状。

图片和工具结果从不保存，消息内容只按下面「数据控制」和「对话同步」两节所说的方式保存；两个开关都关时，什么都不存：请求转发给上游模型（阿里云百炼），回复流式传回。每个响应都带一个 `X-Nanomuse-Request` id，这样一份问题报告可以对上账本里的一行，而不用记录任何内容。删除账号（带账号 key 的 `POST /v1/auth/delete`）会移除全部：账号、key、设备、profile、账本、事件、保留的对话、视频任务、同步的对话和游标、hub 连接，以及实时的「正在处理」提示；中继的测试会在之后检查每一张表里是否还有这个账号的痕迹，并确认同一个地址再注册是一个全新的空账号。见 [privacy.md](privacy.md)。

## 数据控制 {#data-controls}

*设置 → 数据控制 → 帮助改进 nanoMuse 的 AI 模型* 是一个属于每个人自己的开关，在手机、网页版、桌面版和控制台上是同一个。关着，中继转发聊天请求，什么都不留。开着，每一轮会作为训练视图保留：你写的、模型答的、它选择的工具调用，连同模型、token 数，以及请求头里 App 的平台和语言，只和账号 id 关联，从不保留系统提示词（你的记忆、SOUL 和指令），从不保留工具返回的内容（你的文件、你的屏幕、别的 App 显示的东西），从不保留图片、短视频或语音（原位置留一个标记）。目的是给社区自己的开放模型准备一份训练集。页面显示保留了多少轮；随时可以关掉开关（之后不再保留），点一下就能删掉已保留的内容；删除账号也会一并删掉。开关开或关都不会换来任何额度。在 `cloud.nanomuse.cn` 上，这个开关**对中继 0.9 之后创建的账号默认开启，直到这个人把它关掉**：隐私政策这么写，页面在开关旁边也这么写，之前的账号保持它们当初的选择；自己部署的中继用 `IMPROVE_DEFAULT` 定自己的默认值。运营者在管理页的「数据控制」面板看到保留的轮次（多少账号开着、按天、按模型和按 App 的轮次数、最新的轮次、每个账号保留的完整对话），并以 JSON lines 导出，不带账号 id 或地址（`GET /v1/admin/samples/export`，`?account_id=` 导出某一个账号的）。中继收不到位置（各个 App 从不发送），但从中继 0.10 起，它随每次登录、请求、事件和设备记录网络地址和客户端软件（`User-Agent`：Android App 及其版本、Windows / macOS / Linux 上的运行时、某个浏览器），并保留账号的第一个和最后一个地址；管理页按账号、按地址显示它们（`GET /v1/admin/address?ip=`），随账号一起删除。从中继 0.11 起，管理页还会说一个地址在哪里（国家、省、市），查的是中继自己磁盘上一份 ip2region 数据库的离线副本；不问任何第三方，也不多存任何东西（地点在页面绘制时才计算）。

## 对话同步 {#conversation-sync}

*设置 → 数据控制 → 在我的设备之间同步对话*（0.1.36，中继 0.19）是那一页上的另一个开关，登录账号**默认开启**。开着时，每台设备把自己各轮的文本推到中继，并拉取别的设备推上来的，于是手机、电脑和网页版显示同样的聊天：每个对话的标题、谁发起的，每条消息的角色、文本、时间和设备。文件和图片不上传；同步的消息只带附件的名字和大小，文件留在生成它们的设备上。在一台设备上删除一个聊天，所有设备上都删除；重命名也一样。发给另一台设备的聊天，或替某台设备跑的聊天（「来自 Pixel 8」），完全不同步。

**一条线**（0.1.37）。一个账号只有一个主要聊天，每台设备的主要聊天*就是*它：第一台推送的设备定下它的 id，其他设备沿用（`main_exists` → `cid_main`，登录时先拉取），每台设备的主要聊天显示所有设备上说过的话的并集，按时间排序（时间相同时本地消息在前；消息以 `mid` 识别，所以不会重复显示，设备自己的消息传回来也会被忽略）。在另一台设备上写的消息是一个只读气泡，下面标着「来自 Pixel 8」，模型会把它和对话的其余部分一起读。从中继拉下来的旁聊立刻就是这台设备上的一个聊天，带着它的标题和时间，并在同一个对话 id 下继续。这个人的消息一发出就上传（其他设备实时看到，在回复之前），助手的最终文本则在这一轮结束时上传；登录或打开开关时，设备会把自己全部符合条件的历史发上去，从最旧的开始，每次请求 200 条。muse 的名字是账号 profile 的一部分：在任何设备上改名，包括第一个对话里的起名，下次拉取时就会传到其他设备。

**主要聊天优先**（0.1.38，中继 0.20）。默认只有主要聊天在设备之间走：旁聊留在创建它的设备上，设备拉取时带 `scope=main`，别的设备的旁聊永远不会到来。「同时同步旁聊」（「数据控制」下的第二个开关，默认关，**按设备**；中继没有账号级的设置）把打开它的那台设备反过来：它的旁聊上传，其他设备的旁聊下载，切换后的第一次拉取从零重新开始。全新登录的第一次拉取请求的是**尾部**（最新的 300 条消息及其所属对话），这样很长的历史能立刻打开，不用从头翻页；跳过的更早消息留在中继上，不再拉取。一台设备正在回答时，其他设备在最后一条消息下面显示「kwai 正在处理…」：这是一条 `working` 提示，经过中继的内存和 hub，从不保存，设备一直不说完成的话，十分钟后就消失。

中继每个账号最多保留 20 000 条消息（最老的对话的消息先删，标题保留）、2 000 个未删除的旁聊（中继 0.23：超出后新的旁聊被拒绝，原因 `conversation_limit`，留在设备上；删掉一个就腾出一个位置），每条消息 16 384 字节（更长的文本被截断并标记 `truncated`）。在任何一台设备上关掉开关都会通知中继，中继删掉保存的全部内容，并用 `sync_off` 拒绝其他设备，直到开关再次打开；它们的开关跟着变。同一页上的「删除已同步的对话」清空存储，开关保持原样。除了账号的设备没人能读这个存储：运营者的管理页只显示数量（开着和关着的账号数、多少对话和消息、占多大），从不显示文本，也不显示是哪个账号（`GET /v1/admin/sync`）。拉取由 hub 的 `sync` 帧触发（[hub.md](hub.md#frames)），在启动时以及每分钟一次。

API，全部在账号的 key 之下（没有 key 是 401；开关关着时读写都是 409 `sync_off`）：

```
GET    /v1/sync/state                   → {enabled, cursor, counts{conversations, messages}, limits{messages, text_bytes, conversations}, working[]}
PUT    /v1/sync/state   {enabled}       → the same; false deletes everything stored, the counter keeps counting
GET    /v1/sync/changes ?since=0&limit=500&scope=all|main&tail=K   → {cursor, more, conversations[], messages[], skipped?}
POST   /v1/sync/changes {device, conversations[], messages[]}   → {cursor, accepted, rejected[{cid | mid, reason, cid_main?}]}
POST   /v1/sync/working {cid, working, device?}   → 204; the hub tells the other devices   404 no_conversation
DELETE /v1/sync/changes                 → the state, counts at zero     everything stored, switch unchanged
DELETE /v1/sync/conversations/{cid}     → {cursor, deleted: true}      a tombstone the other devices apply; 404 no_conversation
```

`scope`（中继 0.20）不写就是 `all`；`main` 只返回主要聊天及其消息，还没有主要聊天的账号得到一个空页，其 `cursor` 是账号的计数器。`tail=K`（K ≤ 500，只在 `since=0` 时生效）按 `seq` 顺序返回最新的 K 条消息、它们所属的对话、位于账号计数器的 `cursor`、`more: false`，以及 `skipped`（略过了多少条更早的消息）。其他任何 `scope` 都是 400 `bad_scope`。`POST /v1/sync/working` 表示 `device`（或 `X-Nanomuse-Device`）里指名的设备正在 `cid` 里回答（`working: true`）或已经结束（`false`）；中继把活跃的那些在内存里保留十分钟（从不进数据库，所以重启就忘），在状态的 `working` 下列出（`[{cid, from, device_name, working, at}]`），并向账号的其他套接字发一个 `working` 帧（[hub.md](hub.md#frames)）。请求正文超过 `MAX_REQUEST_BYTES`（0.20 起默认 16 MiB）是 413 `too_large`，附一句「请求正文 N MB；这个中继最多接受 M MB」。

一个对话是 `{cid, kind: main | side, title, device, device_name, created_at, updated_at, deleted, seq}`，一条消息是 `{mid, cid, seq, device, device_name, role: user | assistant, text, truncated, attachments[{name, mime, size}], created_at, deleted}`；`cid` 和 `mid` 是设备生成的 UUID（4–64 个字符，取自 `a-z 0-9 . _ : -`，折叠为小写），时间是 Unix 秒。每个被接受的变更拿到账号的下一个 `seq`；设备记住自己拉到过的最高 `cursor`，下次用 `since=` 它来请求。推送是幂等的（已知的 `mid` 原样不动，除非新行是墓碑记录；已知的 `cid` 取较新的标题），而且一次最多 200 条消息或对话（413 `too_many_messages`）。一页按 `seq` 顺序列出它的对话和消息，中继还会把页里每条消息所属的对话一并加上，即使那个对话自己的 `seq` 在更后面（重命名会把它挪后），所以客户端先应用页里的对话、再应用消息，永远不会拿到一个没有归属的孤儿。拒绝会指名那一行：第二个 `main` 被推上来时是 `main_exists` 加 `cid_main`（设备随后改用 `cid_main` 重发），还有 `conversation_limit`（中继 0.23，账号的旁聊已到上限）、`unknown_cid`、`conversation_deleted`、`bad_cid`、`bad_mid`、`bad_kind`、`bad_role`。墓碑记录保留 30 天，然后清扫掉。推送被接受或删除之后，hub 用一个 `sync` 帧通知账号的其他设备（控制台发出的 `DELETE` 在 `X-Nanomuse-Device` 里带着执行删除的设备，好让它跳过自己的回声）。

## 额度 {#allowance}

nanoMuse 是社区项目，不收费。`cloud.nanomuse.cn` 这个公共中继由开发者出钱，所以每个账号有一个可以取用的池子，按账号的整个生命周期算，不按天（中继 0.5）：

| | `cloud.nanomuse.cn` |
|---|---|
| 注册 | 任何有中国大陆手机号或邮箱的人都可以 |
| 免费额度 | 写这篇时是**每个账号 ¥10**，聊天、图片和短视频共用；不重置。数字由中继决定（可以不更新 App 就上调；App 显示的是中继说的数，`/v1/config`），账号页始终显示当前的 |
| 邀请 | 每有一个*新*人用你的邀请码注册，你的池子加 **¥5**（同样是中继定的数），对方也加同样多 |
| 用完之后 | 用自己的 key 或你已经在付费的套餐：在中国大陆，优先[阿里云百炼](own-key.md)（一把 key 覆盖聊天、手、图片和短视频）；其他地方优先 [OpenRouter](https://openrouter.ai/keys) 或 OpenAI（百炼只接受中国大陆的注册）；ChatGPT、Claude 或 Kimi 套餐在有该登录流程的客户端上登录；任何 OpenAI 兼容端点都可以；登录和你的设备不受影响 |
| 成员 | 开发者和他们列出的人没有上限，可以设服务商有的任何模型（聊天用聊天模型，图片用图像模型，短视频用视频模型）：App 的模型选择器在菜单之后列出它们，叫「账号还能用的更多模型」（中继 0.10 用 Cloud key 读取服务商的列表），也仍然可以手动输入一个 id（「其他模型名」） |
| 速率 | 每分钟 30 次请求 |
| token | 没有上限；用量会计量并显示 |

消费按模型服务商的目录价计算（阿里云百炼，北京地域，2026 年 10 月 7 日查阅）。`deepseek-v4.1-flash` 是 0.1.34 起的聊天模型（能看图，回答前会思考）：北京时间 8:00 到 22:00 每百万 token 输入 ¥2 / 输出 ¥8，其余夜间时段 ¥1 / ¥4，以回复到达的那一刻为准。`qwen3.8-27b` 是手的模型，也能用来聊天：¥3 / ¥12；`qwen3.8-flash` ¥0.8 / ¥2.7；`qwen-image-3.0` 每张图 ¥0.18，编辑时送进去的那张图另加 ¥0.02；`wan2.2-i2v-flash` 480P 视频每秒 ¥0.10（一段 5 秒的短视频是 ¥0.50），720P 每秒 ¥0.20，1080P 每秒 ¥0.48。提示词里被服务商从缓存里取出的那部分（系统提示和历史记录，一轮接一轮）按服务商的缓存价计：DeepSeek 是输入价的 10%，Qwen 模型是 20%，以回复里 `usage` 报告的数为准。思考模型的推理 token 算作输出。普通的一天聊下来花几分钱；¥10 大约是聊天模型的两百万 token，或者五十张图。一个新形象（四张候选、四个姿势、四段短视频）大约 ¥3.5，App 在画之前会显示估算和剩余额度。

*设置 → nanoMuse Cloud* 显示池子用了多少（以 ¥ 和 $ 计）、还剩多少、池子怎么增长。用到 80 % 时 App 提示一次；池子花完后中继以 `allowance_exhausted` 拒绝，App 显示接下来的路：自己的 key、你已经在付费的套餐，或者邀请（你们各加 ¥5，或者中继当天说的数）。先推荐哪家服务商取决于你在哪里（0.1.34：中继的 `region`，从号码的国家码或它自己磁盘上一份 ip2region 的离线副本读出；什么都不往外发）：中国大陆账号被指向阿里云百炼（服务商表单打开时已经预填好，[指南](own-key.md)），其他所有人指向 OpenRouter 或 OpenAI，因为百炼只接受中国大陆的注册。

中继 0.21 起，拒绝响应和 `/v1/me` 把整张卡片作为数据带上，而不只是两个链接（契约 C11）：`spend.guidance`（以及 `allowance_exhausted` 错误旁边的 `guidance`）按顺序列出该地区的服务商和每家 key 覆盖的范围（`covers: chat | vision | image | video`，来自共享目录 [`nanomuse/llm/providers.json`](../../nanomuse/llm/providers.json)，中继自带一份副本）、一个人可能已经在付费的套餐和哪些客户端能用它们登录（`plans`：ChatGPT 到处都行，Claude 和 Kimi 在手机上，OpenRouter 在手机上）、本地服务器（`local`）、文档链接，以及关于 ChatGPT 登录的那句实话（`caveats.chatgpt`、`caveats.chatgpt_zh`）。0.17 的 `ways` 行仍然发送，现在每行带着服务商的 `name`、`name_zh`、`key_url`、`covers` 和 `auth`，所以 0.1.38 的客户端照旧画出它一直画的那两个按钮。`/app` 的控制台用 `guidance` 画卡片，遇到旧中继则退回两个链接。其他中继可以定其他规则（`ALLOWANCE_CNY`、`INVITE_BONUS_CNY`、`SIGNUP_OPEN`、`ALLOWED_IDENTIFIERS`；三个数字都能在中继运行时调整，中继 0.15；见 [`cloud/README.md`](../../cloud/README.md)）。

nanoMuse 只求一样回报：在 [GitHub](https://github.com/nano-muse/nanoMuse) 上点一个 star，这是帮项目被人找到的东西。什么时候开口由中继定，不由 App 定（0.1.35）：`GET /v1/nudges` 说明什么时候问是合理的：它替你完成第三、第十和第三十个任务之后，你打开它的第七天和第三十天，达成一个目标时，画出一个新形象时，在账号页上一次，以及池子花完时，两次之间至少隔一周，每台设备最多四次。每次都是一张出现在当下位置的卡片；「以后再说」也算一次，去过那个页面或点了「已经点过了」之后就不再出现（只记在本机，账号不同步这个标记）。运营者在管理页（*设置 › 请求 star*）改这项策略，不用更新 App；每个 App 都内置同样的默认值，供连不上中继时使用。策略定的是*什么时候*，运营者愿意的话也可以定*说什么*：卡片上的文字默认是每个 App 自己的、用它的语言写的；策略里带了句子就用策略的：`star.text`（英文）和 `star.text_zh`（简体中文），各最多 200 字，默认为空。中文界面的 App 先看 `text_zh`，没有再看 `text`，都没有就用自己的句子；其他语言的 App 看 `text`，没有就用自己的。只换卡片上的那句话，标题和按钮还是 App 自己的。按中继 0.22 及更早版本做的 App 不认这两个字段。

## 控制 {#controls}

运营者可以不重启、不重新部署就暂停中继的某些部分（中继 0.22，管理控制台的「控制」；命令行是 `nanomuse-cloud admin controls …`；见 [`cloud/README.md`](../../cloud/README.md#controls-022)）。五个开关，默认都开，都存在数据库里所以重启后不变，每次切换都在审计日志里记一行：谁、什么时候、为什么。某个开关关着时 App 看到的是：

| 开关 | 关着时 App 得到什么 |
|---|---|
| **免费额度** | 受限账号（没有自己的 key，也不是成员）请求模型时得到 **429 `allowance_exhausted`**，带 `paused: true` 和 `reason: "allowance_paused"`，和池子花完时形状相同，所以每个 App 像今天一样显示它的「自己的 key」卡片，只是消息说额度暂时暂停，而不是花完了。成员、登录、设备和同步不受影响 |
| **注册** | 还没有账号的手机号或邮箱从 `POST /v1/auth/code` 和 `/v1/auth/verify` 得到 **403 `signup_closed`**，在发出任何验证码之前；`/v1/config` 里的 `signup_open` 变成 false。所有已有账号照常登录、照常使用 |
| **云服务** | 每个 API 调用都回答 **503 `service_paused`**，带 `paused: true`，例外是健康检查、`/v1/config`、管理控制台和 `/v1/admin/*`；每条 hub 套接字以 `4003 hub_paused` 关闭。什么都不删；已登录的 App 保留它的 key，开关恢复后重新登录 |
| **对话同步** | `/v1/sync/*` 的推送和拉取回答 **503 `sync_paused`**；`GET /v1/sync/state` 仍然应答并说 `paused: true`。已存的内容保留；每台设备各自继续工作 |
| **设备 hub** | `WS /v1/hub` 接受后立即以 **4003 `hub_paused`** 关闭，已打开的套接字以同样方式关闭，`GET /v1/devices` 回答 503 `hub_paused`。每台设备各自继续工作 |

关着的开关列在 `/healthz`、`/v1/config`（公开，缓存一分钟）和 `/v1/me` 的 `paused` 下，客户端可以在尝试之前先说明原因。各个 App 把这些码当成普通的拒绝处理：手机和控制台显示中继的那句话；`allowance_exhausted` 这个形状它们本来就会画成一张卡片。

**阈值。** 一条规则说「账号数达到 N 时，做一件事」：关闭注册、暂停额度、暂停同步，或者只是通知。规则在创建账号时检查，另外每分钟一次；一条规则只触发一次（触发时的数字和时间会保存并显示），「重新启用」或改动阈值能让它再次触发。每次触发写一行审计日志和活动时间线上的一行；「通知」还会通过 SMTP 设置给中继的 `ADMIN_EMAIL` 发一封邮件（只有数字和中继的地址，不涉及任何人）。开关的状态和下一个阈值是管理面板的第一行。

## 自己部署 {#running-your-own}

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
POST /v1/auth/code          {identifier}                      → 204
POST /v1/auth/verify        {identifier, code, device}        → {api_key, base_url, account, tokens, models}
POST /v1/auth/login         {identifier, password, device}    → the same; 401 bad_credentials, 429 locked, 400 no_password
POST /v1/auth/password      Bearer  {password, current?}      → 204; "" with current removes it
GET  /v1/me                 Bearer                            → {region: cn | intl | unknown, account{…, has_password, sessions, signed_in_via}, usage{today, total by kind / model}, tokens, spend{…, ways}, models, recent, nudges}
GET  /v1/nudges                                               → {version, star{enabled, url, moments{signed_in, tasks[], new_look, exhausted, days_used[], goal_done}, cooldown_days, max_asks, text, text_zh}}; no key, cached an hour
GET  /v1/me/profile         Bearer  ?face=false               → {rev, device, name, avatar, …, face?, connectors: [{id, label, url, auth, device, device_id, enabled, at}]}
PUT  /v1/me/profile         Bearer  {device, name?, avatar?, …, connectors?}  → {rev, device}; a device's connectors replace only its own; 400 no_secrets_in_profile, too_many_connectors
DELETE /v1/me/profile       Bearer                            → 204
GET  /v1/me/sessions        Bearer                            → {sessions: [{prefix, device, via, created_at, last_used_at, current}]}
DELETE /v1/me/sessions/{prefix}  Bearer                       → 204
GET  /v1/me/events          Bearer  ?limit=50                 → {events: [{ts, kind, detail}]}
POST /v1/auth/sign-out      Bearer                            → 204
POST /v1/auth/sign-out-all  Bearer  {all?}                    → {signed_out}
POST /v1/auth/delete        Bearer                            → 204
```

其余都是 OpenAI API：`GET /v1/models`（带 `architecture` 模态，好认出图像模型，每个模型还有一个 `nanomuse` 块，含它的 `kind`、价格、`for`（聊天模型适用的通道：`chat` 和 / 或 `gui`）以及 `recommended_for`）、流式的 `POST /v1/chat/completions`、`POST /v1/images/generations` 和 `/v1/images/edits`。错误是 `{"error": {"message", "type": "nanomuse_cloud", "code"}}`，`code` 稳定不变，App 把它变成一句话。中继 0.22 加了运营者[开关](#controls)的码：`403 signup_closed`、`503 service_paused`、`503 sync_paused`、`503 hub_paused`（以及 hub 的关闭码 `4003 hub_paused`），还有免费额度是被暂停而不是花完时带 `paused: true` 的 `allowance_exhausted`；`/healthz`、`/v1/config` 和 `/v1/me` 在 `paused` 下列出关着的开关。

中继不认识的 key 得到 `401 bad_key`；0.1.40 起，账号已被删除的 key 改为得到 `401 account_deleted`，在每一个需要 key 的调用上都如此（`/v1/me`、`/v1/models`、`/v1/chat/completions`、同步和 hub 的调用），删除后持续 90 天；中继把已删除账号的 key 哈希保留这么久，别的什么都不留。不认识这个码的客户端看到的是和以前一样的 `401`；认识的客户端（手机）在 `account_deleted` 时删除账号的本地数据，其他情况都收起来保留（[sync.md](sync.md)）。完整的错误码表在 [`cloud/README.md`](../../cloud/README.md)。

设备：`GET /v1/devices` 列出账号的设备（在线或最后出现的时间），`DELETE /v1/devices/{id}` 忘记一台离线的设备，`WS /v1/hub` 就是 hub 本身；帧在 [hub.md](hub.md)。对话：`/v1/sync/state`、`/v1/sync/changes` 和 `/v1/sync/conversations/{cid}`；见上面的[对话同步](#conversation-sync)一节。
