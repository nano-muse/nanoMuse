# 网页控制台：选择模型、key 和订阅套餐 {#网页控制台-你的模型、你的-key、你的套餐}

登录、退出登录或切换模型后，控制台会重新获取服务商目录。缓存失效前发出的请求不能再写回缓存，后续读取也不会复用旧请求。

刷新记忆时，最新列表和近期修改会一并保留。即使较早的请求较晚返回，也不会让已经删除的记忆重新出现。刷新失败会保留上次加载的内容；离开页面后，不再显示尚未返回的刷新错误。

技能列表同样只采用最新一次完成的刷新结果。重新加载失败时保留当前列表，离开页面后丢弃未处理的错误提示。

聊天的 `/` 菜单在刷新失败时保留已加载的技能，并忽略旧响应。关闭技能后，菜单中的相关建议和键盘补全会立即隐藏。

「每日」、首次设置清单和形象工作室都会忽略旧刷新结果，以及离开页面后才返回的错误。工作室刷新时会保留你填写的描述和当前选择；切换到另一轮绘图任务时，则会清除候选图选择，要求重新确认。

> 网页控制台是 `nanomuse serve` 在 `/` 提供的网页，用于操作自行部署的运行时。早期桌面版也使用这个界面；当前[桌面版](desktop.md)使用 DeepSeek Harness。运行时是执行智能体与工具的后台程序，详见 [app.md](app.md)。本页说明控制台如何选择回答模型，以及缺少某种模型能力时如何引导配置。创建 key（访问模型服务的密钥）见 [own-key.md](own-key.md)。

## 共用的服务商目录 {#one-catalogue}

控制台、手机、桌面版和中继共用 [`nanomuse/llm/providers.json`](../../nanomuse/llm/providers.json) 中的服务商目录，遵循约定 C11。中继是负责账号和设备间通信的服务器。目录列出各服务商 key 支持的能力：`chat` 用于对话，`vision` 用于让「手」看懂截图，`image` 用于形象工作室绘图，`video` 用于生成短视频；也列出 key 以外的登录方式。

控制台优先调用运行时的 `GET /api/providers`，同时获知当前配置的模型位置及其能力。连接不支持该接口的旧版运行时时，改用构建时打包的目录副本，但无法据此得知当前配置。实现位于 `web/src/providers.ts`，排序、映射和提示语由 `web/src/providers.test.ts` 检查。

## 各处如何选择模型 {#where-it-shows}

**连接 → 对话模型**。 服务商卡片来自运行时预设，当前地区的推荐项排在最前：中国大陆为阿里云百炼，其他地区为 OpenRouter，逻辑见 [region.ts](../../web/src/region.ts)。选中卡片后，下方会说明该 key 支持的能力和使用限制，包括 Kimi 各版本差异、OpenRouter Image API，以及 ChatGPT 的使用注意事项。API 是程序调用服务的接口。

「动手模型」列出能看图的模型，用于读取屏幕截图。默认选择该服务商目录中的 `defaults.hands`；如果它没有视觉模型，但你已登录账号，则使用账号的动手模型。如果服务商不支持 `vision`，而你也没有登录，页面只显示缺少视觉模型的说明，不会选一个无法看图的模型来操作屏幕。下方「代理（可选）」接受 `http://host:port`、`https://` 或 `socks5://` 地址，只代理该服务商的请求，对应 `[llm] proxy`。nanoMuse Cloud 不经过此代理，使用 SOCKS 需要运行时安装 `httpx[socks]`。保存过的密码显示为圆点，清空字段即可删除。

**连接 → 对话模型 → 你自己的接口**。 支持 OpenAI API、但未列入目录的服务可以保存为自定义端点，也就是一个模型服务地址，例如网关、中转服务、其他电脑上的 vLLM 或 LM Studio。运行时允许保存多个端点，见 #294。「本地或你自己的端点」下，每个已保存端点各有一张卡片，显示名称和主机名。最后的「添加接口」可填写名称（可选，默认使用主机名）、Base URL（接口基础地址）、API key 或「无需密钥」。如果服务无法通过 `/models` 列出模型，表单会提示手填模型 id。

每个端点的 key 分别存入保险库，名称为 `ENDPOINT_<ID>_API_KEY`，添加新端点不会更改已有端点的 key。选中卡片后，下方会显示 key 的存储位置、模型数量和正在使用它的模型位置，并提供「改名」「换密钥」「编辑模型」「重新获取模型」「移除」。对话选择器会列出该端点的模型。「保存」通过端点 id 设置对话模型，即 `PUT /api/connections/llm {"endpoint": "<id>", "model": ...}`，无需重新填写地址或 key。修改端点名称、key 或地址，会同时影响所有引用它的模型位置。

「动手模型」也会为列表中的其他端点各显示一组模型。选中后，屏幕截图通过该端点发送，并使用其 key，接口为 `PUT /api/connections/gui {"endpoint": "<id>", "model": ...}`。「生成图片」和「生成视频」同样在「你的接口」下列出这些端点，调用 `PUT /api/connections/image` / `/video`，传入 `endpoint` 和 `model`。

正在承担对话的端点不能删除，需要先切换对话模型。删除端点后，引用它的动手、图片和视频模型恢复「自动」，对应 key 也从保险库删除。端点列表功能出现之前，配置为「其他 OpenAI 兼容接口」的对话服务，会在运行时下次启动时自动迁移为第一个端点，并将 key 复制到该端点的保险库条目中。原条目通常是 `LLM_API_KEY`，由于 `config.toml` 可能仍在引用它，程序会保留。确认不再引用后，可用 `DELETE /api/vault/{name}` 手动删除。

同一地址只能保存一个端点。添加或修改时若与其他端点地址重复，程序会拒绝，并指出已有端点。`GET /api/connections` 的 `endpoints` 返回列表，每项为 `{id, label, base_url, key_source, models, slots}`，不包含 key。路由见 [app.md](app.md#api)。不支持端点列表的运行时仍显示原来的单张「其他 OpenAI 兼容接口」卡片。

**连接 → 生成图片、生成视频**。 这是模型约定在 0.1.41 增加的两个媒体模型位置，分别以卡片显示在对话模型下方。卡片显示运行时实际解析出的「服务商 · 模型」，来自 `GET /api/connections` 的 `image` / `video` 及 `effective_*` 字段。选择顺序为：你明确指定的模型；否则使用对话服务商提供的对应媒体模型；否则使用你配置的第一个支持该任务的服务商。均不可用时，显示说明和「添加服务商」。项目托管的 nanoMuse Cloud 不提供媒体生成。

选择器首先提供「自动」。如果对话服务商支持该能力，还会提供「对话模型的服务商」，直接沿用它的 key。「添加服务商」列出当前地区目录内具备该能力的服务商，也提供可填 Base URL 的「其他 OpenAI 兼容接口」；不具备该能力的服务商不会出现。模型可从端点返回的列表中选择，也可使用目录默认值。

「保存」调用 `PUT /api/connections/image` 或 `/video`，参数包括 `provider`（目录 id，或带 `base_url` 的 `openai`）、`model`、`base_url`、`api_key`。key 存为 `IMAGE_API_KEY` / `VIDEO_API_KEY`；选择对话服务商时沿用对话 key。「自动」会将四项全部置空，清除显式配置。动手、图片和视频三个从属位置都遵循同一规则：选择器首项是「自动」，保存后重新按默认顺序解析。动手模型对应 `PUT /api/connections/gui {"model": ""}`。控件下方的「当前为 服务商 · 模型」根据 `effective_*` 显示实际结果。旧版运行时没有这些路由时，不显示媒体卡片。实现见 `web/src/models.ts`，测试见 `web/src/models.test.ts`。

「动手模型」「图片模型」「短片模型」共用 `web/src/components/ModelPicker.tsx`。点击显示「服务商 · 模型」的按钮后打开面板，「自动」排第一。OpenRouter、硅基流动等服务商模型较多，默认只显示八个，其中该位置的目录默认模型和当前模型优先；组末可点「还有 {n} 个」。总行数超过八行时出现「搜索模型」，按模型 id 或名称实时筛选所有组，无结果时显示「没有匹配的模型」。按 Esc 或点击面板外关闭。折叠与搜索逻辑在 `web/src/model-list.ts`，由 `web/src/model-list.test.ts` 检查。

**连接 → 或者用 ChatGPT 套餐登录**。 卡片调用 `POST /api/chatgpt/login` 获取 `{url}`，在新标签页打开 Codex 登录页。随后每两秒查询 `GET /api/chatgpt/status`，最多十分钟。登录令牌存入运行时后，卡片提供「让它来回答对话」，对应 `[llm] provider = "chatgpt"`，以及「退出 ChatGPT」，对应 `POST /api/chatgpt/logout`。卡片会说明套餐支持对话和屏幕操作、不支持图片和视频生成，并提示 OpenAI 条款方面的限制。旧版运行时若返回 404，页面会改为提示终端命令 `nanomuse chatgpt login`。

登录回调会访问运行时所在电脑的 1455 端口。如果运行时在别的电脑上，或该端口被占用，浏览器最终可能停在打不开的地址。端口未成功绑定时，登录响应包含 `port_bound: false`。卡片始终提供一个地址输入框，可将浏览器最终地址交回运行时，调用 `POST /api/chatgpt/callback {url}`；链接状态不符返回 400 `state_mismatch`，登录开始已超过十分钟则返回 409 `no_login`。端口无法绑定时，输入框旁还会说明原因。详见 [configuration.md](configuration.md#a-chatgpt-plan-instead-of-a-key)。

**额度卡片**。 「账号」页以及聊天收到 `allowance_exhausted` 时都会显示三种继续方式。第一种是「换成自己的 key」：显示本地区优先推荐的服务商、「设置一下」（打开「连接」并选中该服务商）、「到 … 获取密钥」和配置指南。「其他服务商，以及各自的 key 能做什么」下还列出地区列表中的其余服务商，各自附能力说明、设置按钮和 key 链接。中继 0.21 起若返回 `guidance.providers` 就使用该列表，否则使用本地目录。第二种是「用你已经在付费的套餐登录」，卡片内直接提供 ChatGPT 登录。第三种是邀请。已用 80 % 的提醒和首次登录面板也指向这些选项。

**形象工作室**。 未配置图像模型时，「画」按钮不可用，下方说明缺少的能力。中国大陆会列出「阿里云百炼、智谱 GLM、硅基流动或火山方舟」，其他地区为「OpenRouter、OpenAI、Google Gemini 或 xAI Grok」，旁边提供「更换」。运行时报告图片或视频生成不可用时，设置 → 图像与视频模型 也会显示相同说明。

## 首次设置与聊天开场 {#the-first-run-and-the-chat-s-opening}

首次设置按「接一个模型 → 连接邮箱、日历、联系人（可选）→ 开始」进行，没有单独的起名页。「开始」调用 `POST /api/firstrun/start {lang}`，标记首次设置完成并打开第一次聊天。开场与手机、桌面版一致，遵循 [parity.md](parity.md) 中的约定 C4：

1. **App 先显示三句话**。 它以智能体身份、用控制台当前语言打招呼，介绍如何在这台电脑上工作，包括读取你指定的文件、操作前询问和消息发送去向，再问如何称呼你。这三句不消耗 token（模型输入输出的计量单位），也不会作为消息发给模型，只显示在历史开头。`GET /api/firstrun?lang=` 的 `intro` 返回这些文字。
2. **模型询问你的称呼**。 你回答或拒绝后，模型在回复末尾的 ```` ```nanomuse-naming ```` 块中报告结果，使用桌面版和手机共用的 JSON 字段 `user_address`、`suggest`、`agent_name`，解析位于 `nanomuse/fences.py`。运行时管理 `none → ask_user_name → ask_agent_name → named → done` 阶段，代码为 `nanomuse/server/firstrun.py`，状态存入资料旁的 `firstrun.json`。你的称呼会写入资料和记忆中的 `Call them: …`，并通过 socket 的 `firstrun` 消息通知页面。socket 是保持实时通信的连接。命名代码块不会显示，即使尚未接收完整也不会露出。
3. **回复下方显示起名选项**。 卡片列出模型建议的两三个名字；模型没有建议时，从内置名单取两个，再提供「换一个」供你自定。点选名字会立即通过 `POST /api/firstrun/pick {name}` 保存，并把它作为你的消息发送，让模型接着以该名字回答。1.0.8 起，「换一个」直接在卡片内打开输入框，输入后的处理与点选一致；即使模型没有在代码块中重复名字，卡片也会关闭。如果在聊天输入框里起名，则仍由模型收到，再通过命名块返回。形象选项等由 App 自行处理的卡片会调用 `POST /api/firstrun/dismiss`，关闭起名卡片。

首次对话中的轮次不会计入请求用户点 Star 所依据的任务数。说明开场流程的附加提示，只发送到绑定的首次聊天，不会进入例程、动态任务或其他聊天。「跳过设置」只标记为已完成引导，不启动这段对话。之后仍可在设置中的身份表单修改名字、形象和语气。不支持这些路由的旧版运行时，继续显示原有问候及不含表单的设置清单。

## 错误与权限提示 {#the-sentences}

功能不可用时，控制台用一句具体说明代替原始错误。`unavailableLine(cap, region, locale)` 会从地区目录中取最多四家具备该能力的服务商，按目录顺序生成提示：

| 能力 | English | 中文 |
|---|---|---|
| `image` | Pictures need a provider with image models: {providers}. | 画图需要一个有图像模型的服务商：{providers}。 |
| `video` | Clips need a provider with video models: {providers}. | 生成视频需要一个有视频模型的服务商：{providers}。 |
| `vision` | The hands need a model that sees pictures: {providers}. | 动手需要一个能看图的模型：{providers}。 |
| `chat` | Chat needs a model: {providers}. | 对话需要一个模型：{providers}。 |

每句旁边的「怎么做」链接指向 [own-key.md](own-key.md)。服务商名称按控制台语言，从目录的 `name` / `name_zh` 取得。

**中继拒绝请求时**，控制台根据 `code` 显示对应说明。说明定义于 `nanomuse/server/failures.py`，英文句子也是 `web/src/i18n/zh-CN.ts` 中查找中文的键。情况包括额度耗尽（附继续使用的选项卡片）、达到每日上限、限流、key 无效、账号停用、中继不支持该模型、上游服务商故障。0.1.40 起还区分了原先统一显示为「模型服务商返回了一个错误：…」的四类错误，以及运营者开关触发的五类状态，见 [cloud.md](cloud.md#controls)：

| 中继说 | 聊天里显示 |
|---|---|
| `413 too_large` | 这条消息超出了模型的上下文窗口。精简一下、去掉部分附件，或者开一个新对话。 |
| `403 not_invited` | 这个中继只接受邀请注册；在「账号」里用邀请码登录。 |
| `429 too_many_in_flight` | 这个账号同时进行的对话太多了，等一轮结束后再试。 |
| `429 provider_busy` | 模型服务商正忙，稍后再试。 |
| `429 allowance_exhausted` 且 `paused: true` | 这个中继暂时停发了免费额度，不是用完了。在「连接」里填上你自己的模型 key 就能继续；你的登录、设备和剩余额度都保持原样。（显示与额度耗尽相同的继续选项卡片，通知包含 `paused`） |
| `403 signup_closed` | 这个中继暂时停止了新注册，已有账号照常使用。稍后再试。 |
| `503 service_paused` | nanoMuse Cloud 被运营者暂时停用了，你的登录和数据都保留着。稍后再试。 |
| `503 sync_paused` | 这个中继暂时停止了对话同步，已存的内容保留着，各设备各自继续使用。 |
| `503 hub_paused` | 这个中继暂时停止了设备互联，各设备各自继续使用。 |

原始响应保留在「详情」中，供报告问题时使用，不会只显示原始内容。

**自己的模型请求失败时**，例如 key 被拒、模型不存在、限流、超时或连接失败，页面会说明原因。如果你已登录，且当前聊天不用账号模型，还会出现「这次改用 nanoMuse Cloud」，与桌面版、手机的 own-key 模型约定第 4 节一致。该按钮将相同消息带上 `via: "cloud"` 重新发送，通过 `POST /api/threads/{id}/send` 或 socket 的 `send` 消息提交。运行时只将这轮交给中继推荐的对话模型，使用账号 key；下一轮仍回到你自己的模型。

此操作不修改 `[llm]`、「使用 nanoMuse Cloud 模型」开关或当前对话配置。关闭 Cloud 模型后，只有主动点击此按钮才会消耗额度。用户消息、回复和该轮失败提示都会携带 `model_used` 模型 id；回复下方显示「这次由 nanoMuse Cloud 回答（模型）」。已含 `model_used` 的失败提示不再重复提供重试按钮。未登录时返回 `401 signed_out`，按钮下显示「请先登录 nanoMuse Cloud。」当前聊天仍使用账号模型时关闭 Cloud，会返回 `409 chat_on_cloud`，开关下显示「先添加一个自己的服务商；关掉 nanoMuse Cloud 后没有别的模型能回答。」

**连接测试失败时**，模型或动手设置中的「测试」会显示与聊天相同的错误说明。`POST /api/connections/llm/test` 返回 `{ok: false, code, error, detail}`，其中 `error` 是易读说明，`detail` 是服务商原文，显示在「详情」中。

**哨兵为何请求确认**，由运行时依据设置说明。哨兵（Sentinel）是执行前检查操作风险和授权的组件。原因可能是 `'shell' is in always_ask_tools`、`risk level is 'sensitive' (mode=ask)`、`covered by your 'always' permission for shell:ls`，或数据污染检查。`web/src/i18n/index.ts` 的 `localReason()` 识别这些格式，按控制台语言转换为句子，并保留工具名、风险和目标地址。今日记录中被拒绝的步骤也显示同样说明；不识别的格式则保留原文。

**已授予的权限**，可从头像 → 权限 查看。列表按工具风险从高到低排列：敏感、中等、安全，分类取自 `GET /api/state` 的 `settings.tools`。每条列出工具、授权有效期和授予时间，均可单独撤销。

## 检查 {#checks}

```sh
cd web && npm run lint && LANG=en_US.UTF-8 npx vitest run && npm run build
```

构建产物写入 `nanomuse/server/static/`，应随修改一同提交；`web/tsconfig.tsbuildinfo` 是构建过程的副产物，不提交。
