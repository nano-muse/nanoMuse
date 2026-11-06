# nanoMuse Cloud

每日统计图的标签和提示按站点配置的时区偏移显示，包括 UTC，不采用运营者浏览器的时区。管理控制台会对每日展示访问去重，同时出现在当前访问和最近访问列表中的一次访问只计一次，日期也按站点时区划分。带 `AsyncOpenAI/Python` 用户代理的旧版 Python 会话会归为运行时，与中继分类一致。

管理控制台定期获取设置时，如果服务器值没变，会保留你尚未保存的额度、邀请奖励和提醒策略；服务器值改变时，则更新相应编辑框。已保存的数字偏好如果为空或不是有限数值，会使用该设置的默认值。

在账号抽屉中切换账号，会清空样本列表，并忽略之前账号尚未返回的样本响应和错误。更换「活动」筛选条件后，旧条件下的待完成请求也不会更新列表。阅读较早事件的分页时，自动刷新会暂停，避免覆盖正在加载或已经展开的「更多」内容。每个 URL 刷新只采用最新响应；退出登录前发出的响应不会重新填充已清空缓存，也不会覆盖之后登录的其他账号。

你可以用中国大陆手机号或邮箱注册，获得免费额度，无需准备自己的 API key 就能使用 nanoMuse。手机号验证码通过短信发送。你仍可继续使用自己的 key，nanoMuse Cloud 只是新增的一种模型服务商。

> 术语说明：中继是处理登录、设备互联和模型转发的服务器；API 是供程序调用的接口；key 是访问服务的密钥；token 在用量统计中指模型计量输入输出的单位，在登录场景中指访问令牌；运行时是实际执行智能体任务的程序。

## 在 App 中使用 {#in-the-app}

从 0.1.20 起，各个 App 首先显示账号入口。你可以填写手机号或邮箱，接收六位验证码；已经设置密码的，也可以用密码登录。随后选择使用账号提供的模型，还是自己的 key。短信仅支持中国大陆手机号，因为号码认证服务不向其他地区发送。输入香港、台湾或海外号码时，会立即收到 `phone_region` 提示，并改用邮箱登录。

退出登录后会回到这个入口。自己部署运行时的人可以设置 `[cloud] required = false` 或 `NANOMUSE_CLOUD_REQUIRED=0`。入口中的「改用自己的 API key」允许直接进入自备 key 设置，不必先登录。配置自己的 key 后，未登录时也能聊天、操作设备、生成图片和视频。需要 nanoMuse Cloud 模型、对话同步或设备互联时，再从「连接」登录；手机入口在设置 → nanoMuse Cloud。

验证码验证成功后，App 会获得以下配置：

- 设置 → 服务商中新增 **nanoMuse Cloud**。它是普通的 OpenAI 兼容服务商，访问 key 使用中继签发的令牌。
- 如果尚未选择模型，设置 → 模型的「对话」和「操作屏幕」会使用账号的 `Qwen/Qwen3.6-27B-FP8`，网页控制台对应入口在「连接」。该模型支持图像输入，因此聊天看图和读取屏幕截图都可使用。账号不提供图片或视频生成，这两项必须在本机配置自定义服务商和自己的 API key。没有手动设置的模型项依次选择：对话模型所用的自备 key 服务商，只要它具备该能力；否则使用已登录的 nanoMuse Cloud；再否则使用第一个具备该能力的自备 key。每项的「自动」会显示当前解析结果。之后添加 key 时，App 会先询问「用它来做什么」，再修改模型分配，见 [own-key.md](own-key.md#which-model-does-what)。

设置 → nanoMuse Cloud 的「账号」页显示当前登录身份和登录时间，身份采用脱敏提示，不直接显示号码。你可以设置、修改或移除密码。密码最低长度由中继决定，默认八个字符，中继只保存 scrypt 哈希。连续输错会暂时锁定密码登录，用新验证码登录可解除锁定。

同一页面还显示今天已用额度及进度，以 ¥ 和 $ 计；按聊天、图片、视频分类的今日及累计用量；按模型划分的用量；各设备的登录记录、登录方式和最后使用时间，并允许逐项撤销。账号历史记录登录、密码变更和拒绝事件，不含消息正文。你也可以选择「退出登录」「所有设备退出登录」或「删除账号」。额度属于注册标识符对应的账号，在同一手机或其他设备重新登录只会签发新 key，不会再发一份额度。

**退出登录后的手机数据**，适用于 0.1.40、契约 C12。无论退出当前设备、退出全部设备，还是更换服务器，手机都会询问「把这个账号的聊天留在这台设备上」，默认关闭。关闭时，账号的聊天、记忆、动态、目标、例程和形象会从手机移除；若已启用同步，中继仍保留聊天，可在下次登录取回。开启时，数据暂存于本机，同一账号再次登录后恢复。切换到其他账号也会经过同样的退出流程。

「删除账号」会删除中继账号及其全部手机数据，不再询问是否保留。之后用同一地址登录，会创建新的空账号。如果中继拒绝 key，例如其他设备执行「所有设备退出登录」、中继重置或故障导致 `401 bad_key`，手机无法先询问你，所以会按保留数据处理：暂存账号数据、移除 key，并在登录页说明「这台手机上的登录已结束。重新登录即可继续；在那之前，你的聊天会留在这台设备上」。同账号登录后恢复，其他账号不能看到这份数据。只有 `401 account_deleted` 才允许直接删除本机数据，因为中继账号已不存在。这是 0.1.40 新增的错误码，旧中继两种情况都返回 `bad_key`，手机因而保留数据。每项状态的位置及各事件下的处理方式见 [sync.md](sync.md)。

你可以同时接入自己的百炼 key、DeepSeek 或本地服务器等其他服务商，并将其中的模型与中继模型放在同一模型组中使用。

## 中继保存哪些数据 {#what-the-relay-keeps}

中继代码位于 [`cloud/`](../../cloud/README.md)，保存以下内容：

- 邮箱或中国大陆手机号的 HMAC-SHA256 加盐哈希、类似 `so***@example.com` 的脱敏提示，以及标识符本身的 AES-GCM 加密副本。加密密钥由中继密钥派生，运营者可在管理页辨认账号归属，单独拿到数据库文件无法读取原标识符。
- 已签发 key 的哈希、登录设备名称、验证码或密码登录方式、最后使用时间，以及注册后的 hub 设备 ID 和类型。撤销 key 后仍保留该行，供登录列表显示撤销状态。
- 如果设置密码，保存 scrypt 哈希，不保存密码原文。
- 每次请求的类型，即聊天、图片或视频，使用模型、token 数和扣费金额。
- 中继 0.28 起，在 `calls` 表保存聊天调用的运行统计：等待服务商名额的时长、首个 token 和完整响应耗时、结束状态，包括成功、服务商错误或超时、内容检查拒绝、连接中断和额度拒绝；消息及图片数量；客户端提供和模型实际调用的工具名称；是否为屏幕操作；客户端平台。0.31 起也记录输入 token 的缓存命中数量。该表不保存对话文字，超过 `CALLS_KEEP_DAYS`，默认 90 天的行会删除。「实时」「用量」页通过汇总显示模型繁忙程度、响应速度和各平台排队情况。
- 中继 0.28 起，为下文「帮助改进」保留的每次调用生成 `sample_stats` 结构统计，包括消息数、字符数、工具调用、图片数、提示词是否过短，以及用户消息的哈希，用来统计重复。质量页面读取统计，不读取对话；删除样本时也删除统计。
- 中继 0.28 起，设备可以在 hub 的 hello 中声明 `llm {provider, model}`，仅提供两个 ID，不含 key、地址或设置，供运营者了解用户自配的服务商。1.0.6 及更早客户端不声明；1.0.7 起，使用账号模型时声明 `cloud`，使用自备 key 时声明目录中的服务商 ID，例如 `openrouter`、`bailian`，以及模型 ID。
- 账号事件时间线，包括登录、登录失败、设置或修改密码、退出、预算拒绝和上游错误。详情只记录设备名、模型或错误码，不含消息内容。
- 旧版视频任务的价格和服务商最后状态，仅供账务清理，三天后删除。托管媒体服务已停用，任务轮询与其他托管媒体接口一样返回 `410 hosted_media_retired`，不会调用服务商。
- 智能体名称和形象，接口为 `/v1/me/profile`，让账号下所有设备显示相同形象。形象可以是龙、带底色的 emoji，或形象工作室绘制的面孔及其小幅 WebP 静态图。中继 0.25 起支持部分更新：改名只发送名称，换形象才发送形象和图片；未提供的字段保留原值，空名称也不会覆盖原名。因此，尚未下载账号形象的手机只改名时，不会意外把其他设备的形象改回龙。`avatar` 改为非 `face` 时清除原图，避免其他设备因 `has_face` 误认仍在使用绘制形象。1.0.3 客户端仍按每次提交完整形象的旧方式处理。0.1.34 起还记录连接器，即哪个设备连接了哪个服务、显示名称、OAuth / key / 开放访问方式及时间。OAuth 是用户在服务商页面确认授权的方式。凭据仍留在原设备，条目出现疑似凭据字段时中继会拒绝，不保存 key 或设置。
- 中继 0.19 起，保存开启「在我的设备之间同步对话」后的对话文本，该开关默认开启。包括对话标题、类型、创建设备，以及每条消息的角色、文字、时间、设备和附件名称、大小，不保存附件文件本身。关闭开关或删除账号会清空这些数据，格式见[对话同步](#conversation-sync)。
- 中继 0.29 起，保存**完整调用记录**：中继发给模型的请求，包括所有消息、含记忆、SOUL 和指令的系统提示词、用户文字、工具结果、工具定义和采样参数，以及模型返回的内容、推理、工具调用、结束原因和用量。图片、音频和视频提取为以 SHA-256 命名的文件，每份内容只存一次，原位置用 `blob:sha256:` 引用替代。同一截图在屏幕操作的多次调用中重复发送，也只保存一个文件。记录还包含模型、平台、1.0.7 起通过 `X-NanoMuse-Device` 和 `X-NanoMuse-Conversation` 声明的设备及对话、token 用量，0.31 起包括输入缓存用量，以及请求网络地址和客户端软件。0.31 起也保存 App 声明的发起方式，如用户、定时任务、动态例程、目标检查或其他设备；对话轮次和模型步骤；所属屏幕操作任务及步骤；用户文字种类标识，如 `zh`、`latin`、`ja`，该标识不含原文。请求头见[调用来源](#provenance)。这份记录属于账号数据，可供账号设备读回，也供运营者排查完整问题，不由下文两个开关控制。读取与删除方式见[完整调用记录](#the-record)。
- 中继 0.31 起，保存 App 上报的调用周边事件，只含短代号和数值，不含消息正文。例如哨兵（Sentinel）的工具风险判定、审批结果、用户停止原因、赞踩反馈和屏幕操作步骤结果。App 知道调用 ID 时会将事件关联到该调用，类型见[客户端事件](#client-events)。删除保留调用或账号时也删除这些事件。

消息正文只按下文「完整调用记录」「数据控制」「对话同步」的规则保存，其他环节只转发请求和流式回复。中继同时最多向共享模型部署发送 `CHAT_CONCURRENCY` 个聊天请求，其余排队；仅在输出开始前重试 429 或 5xx，避免重复已开始的回复。每个响应带 `X-Nanomuse-Request` ID，便于将问题报告关联到账本行，无需在账本中记录正文。

带账号 key 调用 `POST /v1/auth/delete` 会删除账号、key、设备、配置档案、账本、事件、保留对话、视频任务、同步对话和游标，关闭 hub 连接，并清除实时工作状态。中继测试会逐表检查数据已删除，并确认相同地址再次注册时得到新的空账号，见 [privacy.md](privacy.md)。

## 数据控制 {#data-controls}

设置 → 数据控制 →「帮助改进 nanoMuse 的 AI 模型」由每位用户决定，手机、网页版、桌面版和控制台共用同一选择。关闭时，不会把请求保留为训练视图；开启时，会保存用户文字、模型回答及选择的工具调用，同时附模型、token 用量、请求头中的平台和语言，仅关联账号 ID。训练视图不包含系统提示词中的记忆、SOUL 和指令，不含工具返回的文件、屏幕或其他 App 内容，也不含图片、视频或语音，媒体位置只留标记。其用途是为社区开放模型准备训练数据。

中继 0.31 起，使用自己 key 完成并通过 `POST /v1/turns` 上传的调用，也遵守同样的训练视图规则。每条样本记录来源，包括 `meta.source` 的 `cloud` / `own`、`meta.run`、`meta.turn`、指向完整调用记录的 `meta.turn_id`，以及用户文字种类，见[调用来源](#provenance)。这样后续的赞踩和停止原因可以按调用 ID 关联。

页面显示已保留调用数。你可以随时关闭开关，停止新增训练样本；也可以通过删除入口清空已有数据，删除账号时同样会清除。开启或关闭都不影响免费额度。`cloud.nanomuse.cn` 上，中继 0.9 起新建账号默认开启，直到用户关闭；隐私政策和开关旁的说明均有告知，更早账号保持原选择。自建中继通过 `IMPROVE_DEFAULT` 决定默认值。

中继 0.29 起，这个开关仅决定训练视图是否加入训练集，完整调用本身仍按[完整调用记录](#the-record)保存。相同删除入口会一起删除两者，`DELETE /v1/me/samples` 返回 `{deleted, turns, files}`。

运营者可在管理页「数据控制」查看开启账号数、按日期、模型、App 分类的调用数、最新调用及各账号保留的完整对话。训练样本通过 `GET /v1/admin/samples/export` 以 JSON lines（每行一条 JSON）导出，不含账号 ID 和网络地址；`?account_id=` 可限定单个账号。中继 0.31 起，每行含 `subject` 化名：使用中继密钥对账号 ID 计算 HMAC，取 16 个十六进制字符。同一账号在历次导出中保持相同化名，没有密钥无法反推出账号。[删除台账](#deletions)记录后来删除数据的化名，早期导出构成的数据集可据此剔除对应数据。

App 不发送位置，所以中继收不到设备定位。但中继 0.10 起会为登录、请求、事件和设备记录网络地址及 `User-Agent` 客户端信息，例如 Android 版本、Windows / macOS / Linux 运行时或浏览器，也会保存账号首次和最近地址。管理页可按账号或地址查看，接口为 `GET /v1/admin/address?ip=`，删除账号时一并清除。0.11 起，管理页还会根据中继本地 ip2region 离线库显示地址对应的国家、省和城市。查询不请求第三方，地点在显示页面时计算，不另行存储。

## 完整调用记录 {#the-record}

中继 0.29 起，会将自己回答的每次模型调用完整保存为账号数据，使各设备能查看包含截图的历史，也便于运营者排查问题。一次调用记录包括：

- 实际发往模型的请求：含记忆、SOUL、指令的系统提示词，用户消息、工具结果、工具定义、采样参数和中继默认值。模型名按 App 使用的名称保存，不记录中继另加的 `user`、`stream_options`。
- 模型返回的完整助手消息，包括内容、推理、工具调用、结束原因和用量。流式响应会被组装成完整消息；中途断开时保存已收到内容并标为 `status: partial`。中继 0.30 起，`meta.ended` 说明原因：`client_gone` 表示 App 主动关闭，可能是用户停止或客户端超时；`upstream_timeout`、`broken` 表示服务商侧超时或中断。
- 从消息中提取的图片、音频和视频。文件保存在数据库旁的 `MEDIA_DIR`，以内容的 SHA-256 哈希命名，相同内容只存一份；消息原位置写成 `blob:sha256:<hex>`，`meta.media` 列出类型和大小。重复上传的同一屏幕截图，无论被多少次调用引用，都只占一个文件。
- 模型、平台、1.0.7 起 App 通过 `X-NanoMuse-Device`、`X-NanoMuse-Conversation` 声明的设备和对话、token 用量、客户端软件和语言，以及仅运营者可见的来源网络地址。

记录在回复发出后异步写入，不阻塞聊天请求，也不会导致聊天失败。它独立于「帮助改进」训练开关和「同步对话」开关。自建中继设置 `RECORD_TURNS=0` 可关闭完整记录。时间戳取回复完成时间，同一账号按该顺序保存，包括带媒体的回复；不同账号可独立写入。某条写入失败不会阻止该账号后续记录。

**读取权限**。账号设备可用 `GET /v1/turns` 按最新在前读取，通过 `before`、`before_id` 分页，以 `conversation=` 筛选聊天；`GET /v1/turns/{id}` 获取单次调用，`GET /v1/blobs/{sha256}` 获取文件。只有账号持有文件引用时才能访问，例如调用记录、形象动画或自己的上传。仅知道哈希不能下载文件，用户视图也不显示网络地址。

运营者可调用 `GET /v1/admin/turns`，并用 `/v1/admin/turns/export` 导出含账号 ID 的 JSON lines，因为这是账号数据。训练集仍从不含账号 ID 的 `/v1/admin/samples/export` 导出。单个文件通过 `/v1/admin/blobs/{sha256}` 访问；`GET /v1/admin/record` 返回总量、每日调用和文件数，以及存储使用量与上限。

管理控制台的「轮次」页面、账号账本和事件列表切换筛选时会建立新列表。旧分页即使稍后返回，也不能添加到新列表，或覆盖新列表的错误、加载状态。历史和样本分页使用现有时间戳索引，先跳过较新的秒，再按插入顺序处理同秒记录；导出和分析回填使用相同边界，无需数据库迁移。

**自己 key 的调用**。1.0.7 起，App 可以在使用自己 key 完成调用后上传记录，模型部署位置不影响记录完整性。每张图片先通过 `PUT /v1/blobs/{sha256}` 上传原始字节，并附 `Content-Type`，中继会校验哈希。先请求 `HEAD`，或检查返回的 `known: true`，可以得知是否已有其他设备上传。再向 `POST /v1/turns` 提交 `model`、`messages`，其中媒体可用引用或内联 data URL，以及 `response: {message, usage?}`，并按 App 已知信息附 `provider`、`ts`、`conversation`、`id`、`status`。`status: partial` 时可加 `ended`，取值为 `aborted`、`error`、`abandoned`。中继 0.31 起还可附[调用来源](#provenance)定义的 `run`、`turn`、`step`、`trajectory`、`trajectory_step`、`platform`，记录标为 `source: own`。开启「帮助改进」时，也会保留对应训练视图。

电脑已登录账号时，Python 运行时会上传每次不经过中继的模型调用，包括自配服务商、ChatGPT 登录和「手」的独立模型。调用完成后先进入内存队列，上传内容为去掉 key 的原请求、回复、用量和来源；超过两兆的图片先作为文件上传。退出登录会丢弃队列，没有账号时不上传。

引用账号从未上传的文件会得到 400 `unknown_blob`。每个账号每分钟最多上传 `RECORD_UPLOADS_PER_MINUTE` 个调用和文件，默认 120；超过返回 429 `rate_limited`，应稍后继续。账号文件总量上限为 `MEDIA_ACCOUNT_MAX_MB`，默认 2048，超过返回 413 `quota_exceeded`。全站超过 `MEDIA_MAX_GB` 时，在每小时清理完成前暂停接收所有账号的新文件，返回 507 `store_full`。调用记录和文件都在请求事件循环之外写入。

**形象动画片段**。绘制形象的动画也使用这套文件同步。生成动画的设备上传片段，再在 `PUT /v1/me/profile` 中写入 `clips: {mood: {sha256, mime, bytes}}`。其他设备下载已有片段，无需重新渲染。片段随形象关联，写入 `clips: null`、换成其他形象或调用 `DELETE /v1/me/profile` 都会清除。

**保留与删除**。设置 → 数据控制的删除入口会同时清除完整记录与训练调用，删除账号也如此。清除范围包括账号全部调用和仅由该账号引用的文件。`RECORD_KEEP_DAYS` 控制保留天数，每小时清理超期调用；`cloud.nanomuse.cn` 配置为 0，即保留到用户自行删除。媒体总量由 `MEDIA_MAX_GB` 限制，超出时优先删最久未使用的文件，调用文本仍保留，原图片位置会变成失效引用。当前形象正在使用的动画不会被清理。磁盘临时无法删除的文件，会在后续每次清理重试，直到成功。

`/v1/me.contribute.record` 返回 `{on, turns, own, files, media_bytes, keep_days}`，`POST /v1/me/contribute` 也返回相同 `record`。`/app` 账号页在「帮助改进」开关上方显示调用数、自备 key 调用数、文件数和保留期限。只要完整记录或训练数据任一存在，就显示统一删除入口。

**提问数与调用数，0.31 起**。用户发出一条消息，智能体可能多次调用模型，例如截图、点击、重新查看再回答。完整记录每行对应一次调用，不能把行数直接当作用户提问数，因此中继同时统计两者。

每行的 `turn_start` 标识是否开启新提问。App 提供 `step` 时，以 `step=1` 为起点；没有 `step` 时，看请求最后一条相关消息：来自用户则开启，来自工具或助手则继续；没有这类消息也算开启。每行还带 `turn_key`，指向该提问首行 ID。后续调用优先按对话中的 `turn` 序号寻找起点，否则取同一对话最近的前一个起点，从而能在 SQL 中按提问分组。训练视图的结构统计也包含这两个字段。

旧记录由分析循环从最早开始回填。尚未回填的记录不计入上述两种统计，在 `GET /v1/admin/record` 中显示为 `questions.pending`。`/v1/admin/record` 的总计、时间范围和每日数据都在 `n` 旁增加 `questions`，还提供提问统计块，包括总数、带图数、按 App 轨迹判断的屏幕操作数、每问调用数的 `1`、`2-3`、`4-7`、`8-15`、`16+` 分组及均值。`/v1/admin/data` 的总计、日期、模型、平台、运行来源、key 来源和账号统计，则在 `samples` 旁增加 `turns`。

**统计性能**。调用正文位于统计列之前，过去求和需要扫描每行正文。在 30 GB 数据库上，统计一周调用约需半分钟，缓存未热时更慢。现在统计和逐问列表改读 `turns_figures` 索引，只读取需要的列，通常不到一秒。升级后首次启动会扫描记录建立该索引。回填每页读取并重写一百行，每二十五行提交一次；每页完成后暂停与处理该页相同的时长，给控制台和 App 留出磁盘资源。十万次调用约需一小时回填。

`GET /v1/admin/record/turns` 可以按最新在前读取完整提问。每问只展示一次，包含用户消息、按调用排列的步骤、用户最终看到的回复、工具顺序，以及汇总的 `calls`、token、`media`、`models`、`sources`、`partial`。每步列出调用统计、模型文字或工具调用，以及下次调用前返回的工具结果、「手」的截图或用户补充消息。超过 4000 字符的文字截断并标 `truncated: true`，完整调用可从 `GET /v1/admin/turns/{id}` 获取。

筛选字段为 `account_id`、`conversation`、`platform`、`run`、`source`、`model`、`script`、`media=1`，表示提问中某处含图，`hands=1`，表示存在轨迹，以及 `since`。每页最多 100 问，使用 `before` 指定该问最后时间戳，并配合 `before_key` 分页。控制台「逐问查看」显示同样内容：图片和截图嵌入在原位置，通过管理员令牌获取，不能仅靠 `<img>` 加载；工具参数默认折叠，最终回答明确标记，并提供完整调用入口。「数据与同步」页在原调用数旁显示提问数；账号「留存轮次」标签页仍每行显示一次调用，并链接到按该账号筛选的逐问页面。

## 调用来源 {#provenance}

App 知道一次模型调用在整段对话中的位置、发起原因等信息，而请求正文不一定包含这些内容。中继 0.31 起，App 可通过聊天请求头提交；使用自己 key 后上传 `POST /v1/turns` 时，则通过同名请求体字段提交。请求体缺少的值由请求头补充。所有字段均可选，旧 App 不提供时记为「未说明」，中继不推测。

| 请求头 | 请求体字段 | 含义 |
| --- | --- | --- |
| `X-NanoMuse-Run` | `run` | 发起方式：`person` 为用户输入或点按，`schedule` 为定时任务，`feed` 为动态每日例程，`goal` 为目标检查或评测，`hub` 为替其他设备执行请求。格式为小写 `[a-z][a-z0-9_]{0,23}`；未识别的新值也原样保留 |
| `X-NanoMuse-Turn` | `turn` | 对话轮次，从 1 起。用户第一条消息对应第 1 轮，第二条消息的回答对应第 2 轮 |
| `X-NanoMuse-Step` | `step` | 本轮中第几次模型调用，从 1 起；需要工具的一轮通常包含多次调用 |
| `X-NanoMuse-Trajectory` | `trajectory` | 所属屏幕操作任务 ID，格式为 `[A-Za-z0-9_.:-]{1,80}`，同一任务各步共用 |
| `X-NanoMuse-Trajectory-Step` | `trajectory_step` | 屏幕操作任务中的步骤序号，从 1 起 |
| `X-NanoMuse-Platform` | `platform` | 当 user agent 不能准确说明平台时，由 App 明确提供。例如桌面版从 Node 上传，运行时通过 SDK 调用。接受 `android`、`ios`、`desktop`、`windows`、`macos`、`linux`、`runtime`、`browser`；其他值忽略，改按 user agent 判断 |

1.0.7 已有的 `X-NanoMuse-Device`、`X-NanoMuse-Conversation` 保持不变，可与上述字段一起发送。中继将六项来源信息保存到完整记录中，已提供的 `run`、`turn`、`step`、`trajectory`、`trajectory_step` 可通过 `GET /v1/turns` 读回；训练开关开启时，也写入样本 meta 和结构统计。调用遥测中保存 `run`，供「用量」「平台」页面区分用户任务和例程任务。

记录还包含 `script`，表示用户最后一条消息使用的文字系统，取 `zh`、`ja`、`ko`、`ru`、`ar`、`th`、`hi`、`he`、`el`、`latin` 或空值。它在记录写入时计算，用来替代多数 App 没有填写的 `Accept-Language`。

## 客户端事件 {#client-events}

中继 0.31 起，App 可上报模型请求本身未包含的周边事件。调用 `POST /v1/events`，正文为 `{"events": [{kind, ts?, turn?, conversation?, data}]}`，每次最多 100 条，每账号每分钟最多 60 次请求。超出时返回 429，应稍后发送。成功响应为 `202 {kept, dropped}`。

`kind` 使用点分小写名称。`turn` 指完整记录中的调用 ID：nanoMuse Cloud 调用使用响应头 `x-nanomuse-request`；自备 key 调用使用 App 的 `id` 并附 `"source": "own"`，由中继转换为记录中的 `own-…` 格式。`data` 是不嵌套的对象，最多包含 16 个短代号、数字或布尔值。超过 120 字符或包含 `[A-Za-z0-9_.:/ -]` 之外字符的值、嵌套对象都会被略过。格式不合法的事件按条丢弃并计数，不拒绝整次请求，从而避免此通道传递消息正文。

| kind | data |
| --- | --- |
| `sentinel.decision` | `tool`、`risk`（`safe`、`moderate`、`sensitive`、`critical`）、`decision`（`allow`、`ask`、`deny`）、`grant?`（`once`、`schedule`、`conversation`、`always`，即此次使用的授权范围）、`policy?`（询问用户前的策略结果）、`by?`（最终决定来源：`policy`、`auto`、`grant`、`person`、`timeout`）、`channel?`、`tainted?`（布尔值，是否已接触私密数据）、`warnings?`（警告数）、`ok?`（工具是否无错误执行，桌面发送，运行时不发送）、`class?`（手机的步骤分类：Android 风险门使用 `safe`、`install`、`destructive`、`outbound`、`remote`、`money`；iPhone 权限检查使用 `privacy`、`media`、`system`，对应 `apple-*` 命令类别） |
| `approval.result` | `tool?`、`risk?`、`allow`（布尔值）、`scope?`（`once`、`schedule`、`conversation`、`always`）、`by?`（`person`、`timeout`、`other_device`、`auto`；`auto` 表示 App 自行拒绝，例如 iPhone 在后台执行 hub 任务时）、`waited_s?`、`channel?`、`warnings?` |
| `turn.stopped` | `reason`：`wrong`、`slow`、`changed_mind`、`done`、`other`、`skipped`，表示用户停止回复时提供或未提供的原因；`turn_no?` |
| `turn.feedback` | `vote` 为 `up`、`down`，撤回时为 `none`；`reason?` 为 `wrong`、`unhelpful`、`unsafe`、`slow`、`other`；`turn_no?` |
| `turn.ended` | `ended` 为 `aborted`（用户点击停止）、`error`、`abandoned`，使用 App 对提前结束的命名；运行时无论使用哪种 key，被停止的任务都上报 `aborted`；另有 `turn_no?` |
| `hands.step` | `trajectory`、`step`、`action`，动作如 `tap`、`type`、`open_app`，`end` 表示整次运行结束；`outcome?` 为 `ok`、`failed`、`refused`、`stopped`、`handed_over`，`end` 时则是整次状态 `done`、`ask`、`blocked`、`stopped`、`failed`、`max_steps`；`latency_ms?` 为本步模型耗时 |
| `app.opened`、`screen.viewed` | `screen?`，页面代号 |

运营者通过 `GET /v1/admin/client-events` 按最新在前读取，可使用逗号分隔的 `kind=`、`account_id=`，以及上一页最后 ID `before=`。`/v1/admin/client-events/export?since=` 导出 JSON lines，使用 `subject` 化名，不含账号 ID。管理页「数据控制」通过 `/v1/admin/client-events/summary?days=` 展示按日、按类型的数量及代号分布，例如哨兵决定、审批结果、停止原因和赞踩情况。设置 → 数据控制中的删除操作会连同调用记录一起删除这些事件，删除账号也一样。

## 删除台账 {#deletions}

训练集一旦从中继导出，用户随后删除中继数据，不会自动删除外部数据集中的副本。因此，调用 `DELETE /v1/me/samples` 删除保留数据，或调用 `POST /v1/auth/delete` 删除账号时，中继会写一条删除台账，包含 `subject` 化名、时间和删除范围 `samples` / `account`，不附其他个人信息。

`GET /v1/admin/deletions?since=` 按最早在前返回记录。使用导出数据构建训练集的人，应在每次构建前读取台账，剔除所列化名的全部数据。没有中继密钥，无法通过化名识别人。这份台账是账号删除后有意继续保留的记录。个人控制台「数据控制」的删除入口旁和隐私页都会说明。

## 对话同步 {#conversation-sync}

设置 → 数据控制 →「在我的设备之间同步对话」从 0.1.36、中继 0.19 起提供，登录账号默认开启。每台设备上传自己的对话文字并拉取其他设备内容，使手机、电脑和网页版显示相同聊天。同步内容包括对话标题、发起设备，以及消息角色、文字、时间和设备。文件及图片本身不上传，只同步附件名称和大小，文件仍在生成设备。在一台设备删除或改名聊天，也会同步到其他设备。发给其他设备、或替其他设备执行任务的聊天，例如「来自 Pixel 8」，不参与同步。

**共用主要聊天，0.1.37 起**。一个账号只有一条主要聊天，所有设备都使用它。第一台上传的设备确定 ID，其他设备沿用；如收到 `main_exists`，采用返回的 `cid_main`，登录时先拉取现有数据。主要聊天合并各设备消息并按时间排序，同一时间本地消息优先。消息通过 `mid` 识别，避免重复，自己的消息传回时会忽略。其他设备的消息以只读气泡显示，标注「来自 Pixel 8」，模型会连同当前对话一起读取。从中继下载的旁聊也会立即成为本机聊天，保留标题、时间和对话 ID，可继续交谈。

用户消息在发送时立即上传，因此其他设备在模型回复前就可看到；助手最终文本则在本轮结束后上传。登录或开启同步时，设备按最早在前上传全部符合条件的历史，每次请求 200 条。智能体名称属于账号配置档案，在任意设备改名，包括首次对话起名，都会在其他设备下次拉取时同步。

**默认只同步主要聊天，0.1.38、中继 0.20 起**。旁聊默认留在原设备，拉取使用 `scope=main`。「同时同步旁聊」是数据控制中的另一开关，默认关闭，并且按设备独立设置，中继没有账号级开关。某台设备打开后，开始上传自己的旁聊并下载其他设备的旁聊，首次拉取从游标零重新开始。

两类聊天始终排除：桌面替其他设备执行任务的对话，例如「From Pixel 8」；以及桌面侧栏各房间为后台功能建立的内部对话，例如每日动态批次「Feed · <date>」，完成后自动归档。这里的房间指侧栏中的各个功能入口，这些对话用于智能体内部工作，不属于用户聊天。1.0.9 及更早版本曾把每日批次作为旁聊同步到手机，见 [#713](https://github.com/nano-muse/nanoMuse/issues/713)。

全新登录时，首次请求只拉取尾部最新 300 条消息及所属对话，避免长历史必须从头分页。跳过的旧消息仍在中继，不再自动下载。某台设备回答时，其他设备在末条消息下显示「kwai 正在处理…」。这条 `working` 提示经 hub 和中继内存传递，不写数据库；设备未报告结束时，十分钟后自动消失。

每账号同步上限为 20 000 条消息，超出时优先删除最早对话中的消息，保留标题。未删除旁聊上限为 2 000 个，中继 0.23 起，新增超额旁聊返回 `conversation_limit` 并留在设备上，删除一个即可释放名额。单条文字最多 16 384 字节，超出截断并标 `truncated`。

任意设备关闭同步开关，都会通知中继删除全部同步存储，并以 `sync_off` 拒绝其他设备的同步请求，直到重新开启；其他设备的开关也会更新。同页的「删除已同步的对话」只清空存储，不改变开关。同步存储仅账号设备可读取，运营者管理页 `GET /v1/admin/sync` 只显示开启和关闭的账号数量、对话数、消息数和大小，不显示正文，也不列出具体账号。

hub 的 `sync` 帧会触发拉取，见 [hub.md](hub.md#frames)。此外，启动、hub 重连、桌面窗口回到前台以及每分钟定时检查也会拉取。在桌面上，从其他设备收到的消息会排在它到达后本机发送的消息之前，即使两端时钟不同。

以下 API 全部使用账号 key 验证；没有 key 返回 401。同步关闭时，读取和写入都返回 409 `sync_off`：

```
GET    /v1/sync/state                   → {enabled, cursor, counts{conversations, messages}, limits{messages, text_bytes, conversations}, working[]}
PUT    /v1/sync/state   {enabled}       → the same; false deletes everything stored, the counter keeps counting
GET    /v1/sync/changes ?since=0&limit=500&scope=all|main&tail=K   → {cursor, more, conversations[], messages[], skipped?}
POST   /v1/sync/changes {device, conversations[], messages[]}   → {cursor, accepted, rejected[{cid | mid, reason, cid_main?}]}
POST   /v1/sync/working {cid, working, device?, state?, detail?}   → 204; the hub tells the other devices (0.31: state and step ride along)   404 no_conversation
DELETE /v1/sync/changes                 → the state, counts at zero     everything stored, switch unchanged
DELETE /v1/sync/conversations/{cid}     → {cursor, deleted: true}      a tombstone the other devices apply; 404 no_conversation
```

中继 0.20 起，`scope` 默认 `all`；`main` 只返回主要聊天及其消息。账号还没有主要聊天时，返回空页，`cursor` 仍为账号当前计数。`tail=K` 只在 `since=0` 生效，K ≤ 500，按 `seq` 顺序返回最新 K 条消息及所属对话；`cursor` 为账号计数，`more: false`，`skipped` 表示跳过的旧消息数。

中继 0.25 起，只要账号有主要聊天，tail 页就必定包含其对话行，即使 K 条消息都不属于它。新设备因此可以首次拉取就采用 `cid_main`，不必先新建第二条主要聊天再从 `main_exists` 得知正确 ID。1.0.3 客户端将新增行视为普通对话行，行为兼容。其他 `scope` 返回 400 `bad_scope`。

`POST /v1/sync/working` 表示 `device` 或 `X-Nanomuse-Device` 指定设备正在 `cid` 中回答，值为 `working: true`，或已结束，值为 `false`。中继将活跃状态放在内存十分钟，不写数据库，重启即清除。状态接口的 `working` 返回 `[{cid, from, device_name, working, at}]`，同时向账号其他 socket 发送 `working` 帧，见 [hub.md](hub.md#frames)。0.31 起，`working: true` 还可附 `state`，值为 `working` 或 `waiting`，以及 `detail`，即模型描述当前步骤的文字，最多 160 字符。帧和状态列表都会保留两项，其他设备可显示任务进展。请求正文超过 `MAX_REQUEST_BYTES` 时返回 413 `too_large`，0.20 起默认 16 MiB，并说明「请求正文 N MB；这个中继最多接受 M MB」。

重试必须沿用原 `mid`，即使中继已经接受消息、只是响应丢失，也不能生成新 ID。桌面使用设备、本地会话和本地消息行 ID 生成新消息 ID，同时继续识别已持久保存的旧 ID。允许的 ID 格式及其他客户端的 UUID 不变。上传前先保存对话映射，因此响应丢失后重启也会沿用同一对话 ID。

对话格式为 `{cid, kind: main | side, title, device, device_name, created_at, updated_at, deleted, seq}`，消息格式为 `{mid, cid, seq, device, device_name, role: user | assistant, text, truncated, attachments[{name, mime, size}], created_at, deleted}`。`cid`、`mid` 是设备生成、无需解释内容含义的 ID，长度 4–64，使用 `a-z 0-9 . _ : -` 并转成小写；时间使用 Unix 秒。每个接受的变更取得账号下一个 `seq`。设备保存已拉取的最大 `cursor`，下次以它作为 `since=`。

推送具有幂等性，即同一内容重试不会重复创建。已知 `mid` 保持原样，除非新行为墓碑记录，也就是用于同步删除状态的标记；已知 `cid` 接受较新标题。中继 0.25 起，晚于中继时钟一周以上、或早于对话开始的时间，会按对话 `created_at` 处理。旧中继以创建时间判断这一周，导致超过一周的聊天改名都被丢弃。每次最多推送 200 条消息或对话，超过返回 413 `too_many_messages`。

每页按 `seq` 列出对话和消息，也会附上页内每条消息所属的对话，即使该对话因改名导致自己的 `seq` 在后面。客户端应先应用对话，再应用消息，避免消息找不到归属。拒绝结果会指出具体行和原因：第二个 `main` 返回 `main_exists` 与 `cid_main`，设备应改用正确 ID 重发；还有 `conversation_limit`、`unknown_cid`、`conversation_deleted`、`bad_cid`、`bad_mid`、`bad_kind`、`bad_role`。墓碑记录保留 30 天后清理。中继接受推送或删除后，通过 hub `sync` 通知其他设备；控制台发出的 `DELETE` 请求以 `X-Nanomuse-Device` 指明本机，便于忽略自己的通知。

## 额度 {#allowance}

管理控制台的用量日期、日期选择器和「用户」注册图表，都按中继 `DAY_OFFSET_H` 划分。浏览器时区不同，不会导致日期标签或注册数移到相邻日期。

nanoMuse 是不收费的社区项目。公共中继 `cloud.nanomuse.cn` 的开支由开发者承担，每个账号有一份持续使用的额度。中继 0.5 起，额度按账号累计使用，不是每天重置。

| | `cloud.nanomuse.cn` |
|---|---|
| 注册 | 支持中国大陆手机号或邮箱，任何人都可注册 |
| 免费额度 | 本文所述为**每账号 ¥10**，用于托管 Qwen 的聊天、图像理解和 GUI 操作，不重置。具体金额由中继设置，可不更新 App 而调整。App 读取 `/v1/config`，账号页显示当前额度 |
| 邀请 | 每位新用户使用你的邀请码注册后，你和对方各增加 **¥5**，具体以中继设置为准。双方在受邀者首次请求后获得奖励，不在注册时到账 |
| 用完后 | 使用自己的 key 或你已经在付费的套餐。中国大陆优先[阿里云百炼](own-key.md)，同一 key 可提供聊天、手、图片和视频；其他地区优先 [OpenRouter](https://openrouter.ai/keys) 或 OpenAI，因为百炼只接受中国大陆注册。ChatGPT、Claude、Kimi 套餐可在支持其登录流程的客户端中使用；其他 OpenAI 兼容接口也可接入。登录和设备互联不受影响 |
| 成员 | 开发者及其指定用户不受额度限制，也可指定托管服务商的其他聊天模型，但同样不能使用托管图片或视频生成 |
| 请求频率 | 每分钟 30 次 |
| token | 不设数量上限，仍计量并显示用量 |

`Qwen/Qwen3.6-27B-FP8` 的额度扣费按每百万 token 输入 ¥3、输出 ¥12 计算，缓存输入按输入价格的 20%，以响应 `usage` 为准。推理 token 计为输出。图像输入属于聊天请求，并不等同于生成图片。托管图片和视频生成已不可用，因此不收这两类费用；如需生成，请在本机配置自己的服务商和 API key。

设置 → nanoMuse Cloud 显示已用、剩余额度及增加额度的方法，同时显示 ¥ 和 $。用到 80 % 时提示一次；耗尽后，中继返回 `allowance_exhausted`，App 显示自备 key、已有付费套餐和邀请选项。邀请默认双方各加 ¥5，实际按中继当天配置。

推荐服务商顺序由地区决定。0.1.34 起，中继通过号码国家码或本地 ip2region 离线库确定 `region`，不向外部服务发送数据。中国大陆账号优先推荐阿里云百炼，并预填服务商表单，见[指南](own-key.md)；其他地区推荐 OpenRouter 或 OpenAI，因为百炼仅接受大陆注册。

中继 0.21 起，契约 C11 将完整引导卡片作为数据放入 `/v1/me` 的 `spend.guidance`，以及 `allowance_exhausted` 错误旁的 `guidance`。它按地区列出服务商顺序和每家能力 `covers: chat | vision | image | video`，来源为共享目录 [`nanomuse/llm/providers.json`](../../nanomuse/llm/providers.json)，中继包含其副本。还列出已有付费套餐及适用客户端：`plans` 中 ChatGPT 适用于各端，Claude、Kimi 和 OpenRouter 的套餐登录适用于手机；另含本地服务器 `local`、文档链接和 ChatGPT 登录限制说明 `caveats.chatgpt` / `caveats.chatgpt_zh`。

旧版 0.17 的 `ways` 仍返回，并补充服务商 `name`、`name_zh`、`key_url`、`covers`、`auth`，因此 0.1.38 客户端仍显示原来的两个按钮。`/app` 根据 `guidance` 绘制卡片，旧中继则退回两个链接。要求每个对话带固定 ID 的服务商，例如目录 `session_header` 对应的 OpenCode Go，另列在 `session_providers` 并指明请求头。1.0.1 及更早手机端只读 `providers`，不会发送该 ID，因此不推荐这些服务商；支持 ID 的客户端将这份列表接到 `providers` 后。

自建中继可通过 `ALLOWANCE_CNY`、`INVITE_BONUS_CNY`、`SIGNUP_OPEN`、`ALLOWED_IDENTIFIERS` 设置不同规则。中继 0.15 起，相关三个金额可在线调整，见 [`cloud/README.md`](../../cloud/README.md)。管理页「邀请」按邀请码带来的账号数排名，同时显示实际发过请求的人数、尚未首次请求而待发奖励的人数，以及与邀请人使用相同网络地址的人数。账号页也显示邀请人和受邀者列表，接口为 `GET /v1/admin/invites`。

邀请奖励需要受邀者从不同于邀请人的网络地址，累计产生至少 `INVITE_SETTLE_MIN_SPENT_UY` 的真实成功模型消费，默认 200 微元。邮箱 `+tag` 子地址、Gmail 点号和 `googlemail.com` 别名都归入同一账号。`DEFAULT_SIGNUP_DOMAIN_BLOCK` 与 `SIGNUP_DOMAIN_BLOCK` 中的一次性邮箱域名不能注册；非知名邮箱服务商域名每天最多新增 `SIGNUP_PER_DOMAIN_DAY` 个账号，默认 5，超出返回 `domain_limited`。健康检查会提示两类可疑邀请：一天带来超过十个账号，或累计至少二十个受邀者而几乎无人发过请求。

展开「邀请」视图中的邀请人，或查看账号页「邀请的人」卡片，可以收回未花掉的邀请奖励，并可同时停用账号、删除其邀请但从未发请求的账号，接口为 `POST /v1/admin/invites/abuse`。已消费部分不收回。

运营者启用或停用账号、设置或取消成员、赠送、充值、修改额度、修改设置和删除账号，都会写入「控制」中的审计日志，记录操作者、来源和目标账号 ID 前八位；账号仍有时间线时也会写入，删除还计入「统计」。被停用账号申请验证码仍返回普通的 `204`，请求照常计入频率限制，但不实际发短信或邮件，也不透露账号存在与否或停用状态。用户使用验证码或正确密码登录时才收到 `403 account_disabled`；密码错误则与一般错误密码相同。

项目会适时邀请你在 [GitHub](https://github.com/nano-muse/nanoMuse) 点 star，帮助更多人找到它。0.1.35 起，提示时机由中继 `GET /v1/nudges` 配置：完成第 3、10、30 个任务，使用第 7、30 天，完成目标，绘制新形象，在账号页一次，以及额度耗尽时。两次至少相隔一周，每设备最多四次。提示在对应位置显示为卡片，选择「以后再说」也计入次数。访问项目页面或表示「已经点过了」后不再提示，该状态只保存在设备，不跨账号同步。

运营者可在设置 → 请求 star 中修改策略，无需更新 App。各端内置相同默认值，供无法连接中继时使用。策略除了时间，也可以指定句子：`star.text` 为英文，`star.text_zh` 为简体中文，各最多 200 字符，默认空。中文 App 优先用 `text_zh`，其次 `text`，都为空则用本机文案；其他语言优先 `text`，否则用本机文案。只替换说明句，标题和按钮不变。按中继 0.22 及更早协议构建的客户端忽略这两个字段。

## 控制 {#controls}

管理控制台「用户」表，或「用量」单日账号排行点击「更多」后，轮询刷新会保持已展开的行；列表缩短时，展开数量随之缩小。

运营者可以在线暂停中继的部分功能，无需重启或重新部署。中继 0.22 起可在管理控制台「控制」或命令 `nanomuse-cloud admin controls …` 中操作，见 [`cloud/README.md`](../../cloud/README.md#controls-022)。共六个开关，默认开启，存入数据库并在重启后保留。每次切换都记录操作者、时间和原因。五个暂停类开关关闭时，客户端行为如下：

| 开关 | 关闭时的响应 |
|---|---|
| **免费额度** | 受限账号，即未使用自己 key 且非成员的账号，请求模型得到 **429 `allowance_exhausted`**，附 `paused: true`、`reason: "allowance_paused"`。结构与额度耗尽相同，App 显示自备 key 引导卡，但说明是暂时暂停。成员、登录、设备和同步不受影响 |
| **注册** | 尚无账号的手机号或邮箱调用 `POST /v1/auth/code`、`/v1/auth/verify` 时，在发码前返回 **403 `signup_closed`**，`/v1/config` 的 `signup_open` 变为 false。已有账号继续正常登录和使用 |
| **云服务** | API 返回 **503 `service_paused`** 并附 `paused: true`，健康检查、`/v1/config`、管理控制台和 `/v1/admin/*` 除外。全部 hub socket 以 `4003 hub_paused` 关闭，不删除数据。App 保留 key，服务恢复后重新连接登录 |
| **对话同步** | `/v1/sync/*` 上传和拉取返回 **503 `sync_paused`**；`GET /v1/sync/state` 仍响应并标 `paused: true`。已存数据保留，各设备可继续本地工作 |
| **设备 hub** | `WS /v1/hub` 接受后立即以 **4003 `hub_paused`** 关闭，现有连接同样关闭；`GET /v1/devices` 返回 503 `hub_paused`。各设备仍可独立工作 |

暂停项列在 `/healthz`、公开且缓存一分钟的 `/v1/config`，以及 `/v1/me` 的 `paused` 中，客户端可以提前说明原因。手机和控制台按普通拒绝处理，显示中继说明；`allowance_exhausted` 继续使用已有引导卡。

第六项「只服务 nanoMuse 客户端」从中继 0.28 起默认开启。开启时，模型仅服务 nanoMuse 手机 App、桌面版、Python 运行时和浏览器网页控制台。其他程序使用 nanoMuse key 调用 `/v1/chat/completions`，例如池工作进程、SDK、脚本或未改名的上游 App，会收到 **403 `client_not_supported`**，`client` 字段标明识别出的客户端，并提示在该程序使用自己的 key。

识别依据为 `User-Agent`，只能约束如实声明身份的程序，不能阻止伪装。成员可从任意客户端调用；登录、账号页、同步和 hub 不受影响。拒绝不计费，在账号时间线记录 `client.refused`。nanoMuse App 都声明自身身份，不会遇到此错误。1.0.6 及更早运行时使用 OpenAI SDK 自带标识，中继也能识别；1.0.7 起运行时声明自己的名称。关闭此开关后，恢复 0.28 前行为，任何持有效 key 的客户端都可使用。

**阈值规则**。可以设置「账号数达到 N 时」关闭注册、暂停额度、暂停同步或仅通知。每次创建账号和每分钟定时检查。规则只触发一次，保存并显示触发时的数量和时间；「重新启用」或修改阈值后可再触发。每次都会写入审计日志和活动时间线。「通知」还通过 SMTP 向 `ADMIN_EMAIL` 发送仅含数量和中继地址的邮件，不包含个人信息。管理面板首行显示开关状态和下一阈值。

## 部署自己的中继 {#running-your-own}

API 请求和错误计数由中继工作线程池写入。响应会等待写入结束，但写入等待数据库锁时，不会占用事件循环。

你可以为家庭、班级或公司部署中继，再让 App 连接它。服务由一个 Python 进程和 SQLite 数据库组成，带 Docker 的 VPS 加域名即可运行：

```bash
cd cloud
cp .env.example .env    # domain, secrets, upstream key, how codes are sent
docker compose up -d    # Caddy fetches the TLS certificate
```

[`cloud/README.md`](../../cloud/README.md) 包含配置、验证码发送选项、管理充值接口和测试套件。邮箱使用 SMTP（邮件发送协议），中国大陆手机号使用阿里云短信。

少量用户可以设置 `SIGNUP_OPEN=0` 和 `ALLOWED_IDENTIFIERS=139…, me@example.com`，只允许列表中的号码与邮箱登录；其他请求在发送验证码前返回 `not_invited`。早期试用部署采用这种方式。开放注册时，同一列表指定不受每日上限约束的成员，管理页也可添加成员。

应用商店审核可配置 `REVIEW_ADDRESSES` 和六位 `REVIEW_CODE`。指定邮箱申请验证码时不实际发信，但返回与已发送相同的结果；审核员用固定代码登录，仍受普通验证码的有效期、尝试次数和速率限制。账号本身是普通账号，管理页标为「review」，不计入注册数量。两项默认都为空，不影响普通行为，见 [`cloud/README.md`](../../cloud/README.md#for-app-store-review)。

中继也通过 `/v1/hub` 提供设备互联，并在 `/app` 提供网页控制台，见 [hub.md](hub.md)。`HUB_ENABLED` 可关闭 hub，`HUB_FRAME_LIMIT` 限制单帧，默认 16 MB，文件和截图均在帧中传输。

各端默认连接 `https://cloud.nanomuse.cn`。手机登录表单下的「使用其他服务器」可填写自建中继地址，见 [android.md](android.md)、[ios.md](ios.md)；桌面版读取插件 `config.baseURL`，见 [desktop.md](desktop.md)；网页控制台使用提供 `/app` 页面的那台中继。

## 通信协议 {#protocol}

App 使用以下 JSON 接口：

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

`/v1/config` 的 `code_ttl_s`、`password_min_len` 分别来自 `CODE_TTL_S`、`PASSWORD_MIN_LEN`。网页控制台据此显示验证码时效和密码长度，自建中继修改配置后，表单说明也保持准确。旧中继缺少这两个字段时，按十分钟和八字符处理。

**模型容量**。每个模型可提供 `context_length`，即输入与输出合计的上下文容量，以及 `max_output_tokens` 输出上限。两者单位为 token，均为不超过 2147483647 的正整数。运营者可在 `CLOUD_MODELS` 模型条目配置。未知容量不返回，不按模型名猜测，也不复制计价参考模型的值。登录响应、`/v1/me`、模型列表和单模型查询使用相同的配置表示。成员可用的其他模型，如果上游明确提供容量，也会保留这两个字段。

Android 和打包桌面版在容量字段未手填时采用中继值；手动覆盖优先，模型组上下文限制仍有效。刷新会更新继承值并保留手动设置，无需重新登录。旧中继不提供容量时继续使用客户端原有默认值。上下文容量不同于累计用量，缓存输入仍占上下文。如果上游流没有 `usage`，中继会为账本估算消费，但不会把估算值伪装成实测用量写入响应流，因此会话统计可能与账号账本不同。

其他模型接口兼容 OpenAI API。`GET /v1/models` 包含 `architecture` 输入输出模态，用于识别图像模型，以及每模型的 `nanomuse` 信息块：`kind`、价格、`for`，表示聊天模型适用 `chat`、`gui` 或两者，以及 `recommended_for`。成员可通过 `GET /v1/models/{id}?kind=chat` 检查手动填写模型，返回 `listed`、`priced_as`。聊天使用支持流式响应的 `POST /v1/chat/completions`；图片接口为 `POST /v1/images/generations`、`/v1/images/edits`；视频沿用服务商路径 `POST /api/v1/services/aigc/video-generation/video-synthesis`、仅查询自己任务的 `GET /api/v1/tasks/{id}`，以及 `GET /api/v1/uploads`。

错误格式为 `{"error": {"message", "type": "nanomuse_cloud", "code"}}`，`code` 保持稳定，由 App 转为可读说明。托管服务对新图片或视频请求、上传、手动媒体模型查询、媒体估算和视频任务轮询，都在请求上游前返回 `410 hosted_media_retired`，并附 `action: configure_own_provider`。

中继 0.22 为运营者[控制开关](#controls)增加 `403 signup_closed`、`503 service_paused`、`503 sync_paused`、`503 hub_paused`，以及 hub 关闭码 `4003 hub_paused`。免费额度只是暂停而非耗尽时，`allowance_exhausted` 附 `paused: true`。`/healthz`、`/v1/config`、`/v1/me` 都在 `paused` 中列出暂停项。

**模型开始回答前的状态，中继 0.31 起**。流式聊天可先发送没有 `choices` 的数据块：`{"object": "chat.completion.chunk", "model", "created", "choices": [], "nanomuse": {"phase", "waited_ms", "ahead"?}}`。等待 `CHAT_CONCURRENCY` 名额时，每五秒发送 `phase: "queued"`，用 `ahead` 表示前面请求数；获得名额后发送 `phase: "working"`。没有排队的请求不发送这些块。服务商尚未返回首字节时，每十秒发送注释行 `: keepalive`。

SSE（服务器事件推送）解析器会按协议跳过注释，空 `choices` 块也与客户端原本支持的仅用量块结构一致。因此旧客户端仍能正常显示回复；支持 `nanomuse` 字段的 App 可显示排队人数和等待时长。这些状态不出现在非流式响应中，不计费，也不写入账本。

未知 key 返回 `401 bad_key`。从 0.1.40 起，账号已删除的 key 在所有需要验证的接口中返回 `401 account_deleted`，包括 `/v1/me`、`/v1/models`、`/v1/chat/completions`、同步和 hub。删除后保留 key 哈希 90 天，用于区分这个错误，不保留账号其他内容。旧客户端仍按普通 `401` 处理；了解新码的手机端在 `account_deleted` 时删除本地账号数据，其他情况暂存保留，见 [sync.md](sync.md)。完整错误表见 [`cloud/README.md`](../../cloud/README.md)。

设备接口：`GET /v1/devices` 列出在线或曾在线的账号设备，`DELETE /v1/devices/{id}` 移除离线设备，`WS /v1/hub` 提供互联，帧格式见 [hub.md](hub.md)。对话接口为 `/v1/sync/state`、`/v1/sync/changes`、`/v1/sync/conversations/{cid}`，见上文[对话同步](#conversation-sync)。
