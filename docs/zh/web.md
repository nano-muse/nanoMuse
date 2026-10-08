# 网页控制台：你的模型、你的 key、你的套餐

> 网页控制台是 `nanomuse serve` 在 `/` 上托管的那个应用——桌面版和自己部署的运行时的大门（[app.md](app.md)）。这一页只讲它的一部分：它怎么挑选回答的模型，以及模型缺了什么时它给出什么。做一把 key 的指南在 [own-key.md](own-key.md)。

## 一份目录 {#one-catalogue}

控制台读的服务商列表和手机、桌面版、中继是同一份：[`nanomuse/llm/providers.json`](../../nanomuse/llm/providers.json)（约定 C11）。每个服务商写明一把 key 在那里能覆盖什么——`chat`、`vision`（手看截图）、`image`（形象工作室的图片）、`video`（它的短视频）——以及除了 key 之外还有哪些登录方式。控制台先问运行时（`GET /api/providers`，它还会说今天配置了哪些位置、各覆盖什么），在旧版运行时上退回构建时打包的那份副本，这时对配置了什么一无所知。模块是 `web/src/providers.ts`；`web/src/providers.test.ts` 检查排序、映射和那些句子。

## 显示在哪里 {#where-it-shows}

**连接 → 对话模型。** 服务商卡片是运行时的预设，所在地区的首选排第一（中国大陆是阿里云百炼，其他地方是 OpenRouter——[region.ts](../../web/src/region.ts)）。卡片下面是所选服务商在目录里的那一行：它的 key 覆盖什么，以及需要知道的事（Kimi 的几个版本、OpenRouter 的 Image API、ChatGPT 的注意事项）。「动手模型」选择器列出能看图的模型；它的默认值是目录里这个服务商自己的动手模型（`defaults.hands`），服务商没有能看图的模型而你登录了账号时，则是账号的动手模型；既没有 `vision` 也没有账号的服务商得到的是那一句话，而不是一个看不见的动手模型。下面的「代理（可选）」接受 `http://host:port`、`https://` 或 `socks5://` 地址，只用于这个服务商的请求（`[llm] proxy`；nanoMuse Cloud 的请求从不经过它，SOCKS 地址需要运行时装了 `httpx[socks]`）；存过的密码回显为圆点，清空字段就清掉它。

**连接 → 生成图片、生成视频。** 模型约定（0.1.41）的两行媒体槽位，各一张卡片，放在对话模型下面。值是运行时解析出的「服务商 · 模型」（`GET /api/connections` → `image` / `video`：槽位的设置和它的 `effective_*`）：明确的选择优先，否则是对话服务商自己的图片模型（它有的话），否则登录时是账号的，再否则是那一句话和一个「添加服务商」按钮。选择器第一项是「自动」，然后是登录时的「nanoMuse Cloud」一组、有这项能力时的「对话模型的服务商」（用它的 key，不用再粘贴），以及「添加服务商」下面所在地区每一家有这项能力的目录服务商，加上一个带 Base URL 的「其他 OpenAI 兼容接口」；没有这项能力的服务商不会出现。模型可以从接口列出的里面选（nanoMuse Cloud 上是中继的菜单和账号可用的其他模型），也可以留给目录的默认值。「保存」调用 `PUT /api/connections/image` 或 `/video`，带 `provider`（目录 id，或 `openai` 加 `base_url`）、`model`、`base_url`、`api_key`（进保险库，名为 `IMAGE_API_KEY` / `VIDEO_API_KEY`；中继那一行写的是账号的 key，对话服务商那一行留给对话的 key）；「自动」把四项都发空，也就是清掉这个槽位。三个依赖槽位的样子一致：「自动」是「动手模型」选择器和两行媒体槽位的服务商下拉框的第一项，保存它就让槽位回到解析顺序（动手是 `PUT /api/connections/gui {"model": ""}`），控件下面一行「当前为 服务商 · 模型」说明今天解析成什么，来自运行时的 `effective_*` 字段。没有这些路由的运行时不显示这两行。模块是 `web/src/models.ts`（行的值、选择器的选项）；`web/src/models.test.ts` 检查它。

「动手模型」「图片模型」「短片模型」三个控件是同一个选择器（`web/src/components/ModelPicker.tsx`）：一个写着「服务商 · 模型」的按钮，点开是一个面板，「自动」排第一。列表很长的服务商（OpenRouter、硅基流动）起初只显示八个模型，目录里这个槽位的默认模型和你当前选的排在最前，组尾是「还有 {n} 个」；所有行加起来超过八个时，「搜索模型」输入框边打字边按模型 id 或名称过滤每一组（都不匹配时显示「没有匹配的模型」）。按 Esc 或点面板外面关闭。折叠和搜索的逻辑在 `web/src/model-list.ts`，由 `web/src/model-list.test.ts` 检查。

**连接 → 或者用 ChatGPT 套餐登录。** 这张卡片让运行时启动 Codex 登录（`POST /api/chatgpt/login` → `{url}`），在新标签页打开那个页面，每两秒轮询一次 `GET /api/chatgpt/status`，最多十分钟，令牌进了运行时的存储之后，提供「让它来回答对话」（`[llm] provider = "chatgpt"`）和「退出 ChatGPT」（`POST /api/chatgpt/logout`）。卡片写明这个登录覆盖什么——对话和手，不包括图片和短视频——并带着关于 OpenAI 条款的那句实话。没有这些路由的运行时回答 404；这时卡片直接给出要在终端里跑的命令 `nanomuse chatgpt login`，而不是装作能行。登录的回调落在运行时所在机器的 1455 端口。浏览器够不到它时（运行时在另一台电脑上，或者端口被占——登录回答里 `port_bound: false`），浏览器最后会停在一个打不开的地址上；卡片有一个输入框接收这个地址，再交给运行时（`POST /api/chatgpt/callback {url}`；过期的链接是 400 `state_mismatch`，超过十分钟的登录是 409 `no_login`）。这个输入框任何情况下都在，端口绑不上时会多一句话说明原因（[configuration.md](configuration.md#a-chatgpt-plan-instead-of-a-key)）。

**额度卡片**（在「账号」里，以及聊天里出现 `allowance_exhausted` 时）给出三条路：「换成自己的 key」，带所在地区的首选、一个打开「连接」并定位到该服务商的「设置一下」、「到 … 获取密钥」、指南，以及「其他服务商，以及各自的 key 能做什么」下面地区列表里的其余服务商（中继发来 `guidance.providers` 时用中继的，中继 0.21；否则用目录的），每一个都带自己的覆盖说明、自己的「设置一下」和 key 链接；「用你已经在付费的套餐登录」，ChatGPT 卡片就嵌在里面；还有邀请。80 % 的提前提醒和第一次登录的面板指向同一个地方。

**形象工作室。** 没有图像模型时，「画」按钮不可用，下面那一行就是那一句话——中国大陆是「画图需要一个有图像模型的服务商：阿里云百炼、智谱 GLM、硅基流动或火山方舟」，其他地方是「OpenRouter、OpenAI、Google Gemini 或 xAI Grok」——旁边是「更换」。**设置 → 图像与视频模型**在运行时说图片或短视频没有覆盖时，把同一句话显示为它的值。

## 第一次打开与聊天的开场 {#the-first-run-and-the-chats-opening}

首次运行的清单是「接一个模型 → 连接邮箱、日历、联系人（可选）→ 开始」。没有起名那一页：「开始」让运行时开启第一次对话（`POST /api/firstrun/start {lang}`，同时把首次运行标记为完成）并打开聊天，开场在那里进行，和手机、桌面版一样（[parity.md](parity.md) 里的约定 C4）：

1. **App 先开口**，以智能体的身份说三句，用控制台的语言——你好、「先说说我怎么工作」（这台电脑、你指给它的文件、关键一步先问、消息发到哪里）、「我该怎么称呼你？」。这三句不花 token，模型从不把它们当作消息看到；聊天把它们画在历史的开头（`GET /api/firstrun?lang=` 以 `intro` 返回）。
2. **模型问你的名字**，你说了（或者不想说）之后，它在回复末尾用一个 ```` ```nanomuse-naming ```` 代码块汇报——和桌面版、手机读的是同一份 JSON（`user_address`、`suggest`、`agent_name`；`nanomuse/fences.py`）。阶段由运行时掌握（`none → ask_user_name → ask_agent_name → named → done`，`nanomuse/server/firstrun.py`，存为资料旁边的 `firstrun.json`），它把你的称呼写进资料和记忆（「Call them: …」），并通过 socket 通知页面（`firstrun` 帧）。那个代码块本身从不显示，流式传到一半也不显示。
3. **起名卡片**出现在回复下面：模型给的两三个名字建议，或者它没给时内置名单里的两个，再加一个「换一个」让你自己起。点一个名字立刻保存（`POST /api/firstrun/pick {name}`）并把它作为你的消息发出去，模型的下一条回复就是它以这个名字说的第一句；自己输入的名字会到模型那里，再从代码块里回来。App 自己回答的卡片（形象选项）会撤掉起名卡片（`POST /api/firstrun/dismiss`）。

第一次对话进行期间，它的回合对请求点 Star 来说从不算*任务*。告诉模型这套开场的附加提示只进入对话绑定的那个聊天，从不进入例程、动态或别的聊天。「跳过设置」只做普通的「已完成首次运行」，不开启对话；身份表单留在「设置」里，以后改名字、形象和语气用。没有这些路由的旧版运行时得到的是原来的问候和没有表单的清单。

## 那些句子 {#the-sentences}

每个不可用的功能都是一句话，从不是原始错误，由 `unavailableLine(cap, region, locale)` 根据所在地区具备该能力的服务商生成（最多四个，按目录顺序）：

| 能力 | English | 中文 |
|---|---|---|
| `image` | Pictures need a provider with image models: {providers}. | 画图需要一个有图像模型的服务商：{providers}。 |
| `video` | Clips need a provider with video models: {providers}. | 生成视频需要一个有视频模型的服务商：{providers}。 |
| `vision` | The hands need a model that sees pictures: {providers}. | 动手需要一个能看图的模型：{providers}。 |
| `chat` | Chat needs a model: {providers}. | 对话需要一个模型：{providers}。 |

每句旁边有一个「怎么做」链接，指向 [own-key.md](own-key.md)。服务商的名字按控制台的语言取自目录（`name` / `name_zh`）。

**中继拒绝的一个回合**也是一句话，按中继的 `code` 来（`nanomuse/server/failures.py`；这句话就是 `web/src/i18n/zh-CN.ts` 里的键，所以中文是从英文查出来的）：额度用完（下面带那张几条路的卡片）、每日上限、限流、key 无效、账号被停用、中继不提供的模型、中继背后的服务商出了问题——以及从 0.1.40 起，原来落到「模型服务商返回了一个错误：…」的那四种，和运营者的开关发出的那五种（[cloud.md](cloud.md#controls)）：

| 中继说 | 聊天里显示 |
|---|---|
| `413 too_large` | 这条消息超出了模型的上下文窗口。精简一下、去掉部分附件，或者开一个新对话。 |
| `403 not_invited` | 这个中继只接受邀请注册；在「账号」里用邀请码登录。 |
| `429 too_many_in_flight` | 这个账号同时进行的对话太多了，等一轮结束后再试。 |
| `429 provider_busy` | 模型服务商正忙，稍后再试。 |
| `429 allowance_exhausted` 且 `paused: true` | 这个中继暂时停发了免费额度，不是用完了。在「连接」里填上你自己的模型 key 就能继续；你的登录、设备和剩余额度都保持原样。——和额度用完时同一张几条路的卡片，通知带着 `paused` |
| `403 signup_closed` | 这个中继暂时停止了新注册，已有账号照常使用。稍后再试。 |
| `503 service_paused` | nanoMuse Cloud 被运营者暂时停用了，你的登录和数据都保留着。稍后再试。 |
| `503 sync_paused` | 这个中继暂时停止了对话同步，已存的内容保留着，各设备各自继续使用。 |
| `503 hub_paused` | 这个中继暂时停止了设备互联，各设备各自继续使用。 |

原始回复留在「详情」下面，供提 bug 时用，从不作为唯一显示的内容。

**你自己的模型失败的一个回合**（key 被拒、端点不认识这个模型、限流、超时、连不上）显示它那句话，并且在你已登录、聊天没有用账号模型时，多一个按钮「这次改用 nanoMuse Cloud」（own-key 模型约定第 4 节；桌面端和手机端有同样的按钮）。它把同样的话带着 `via: "cloud"` 再发一次（`POST /api/threads/{id}/send`，或 socket 的 `send` 帧）：运行时用账号的 key 在中继推荐的聊天模型上跑这一个回合，下一回合回到你的模型。`[llm]`、「使用 nanoMuse Cloud 模型」开关和这段对话都不动；关掉 Cloud 模型后，只有这个按钮会花额度。用户气泡、回复和这一回合的失败提示都带 `model_used`（模型 id）；回复下面显示「这次由 nanoMuse Cloud 回答（模型）」，带 `model_used` 的失败提示不再给出这个按钮。未登录时运行时回 `401 signed_out`，句子是「请先登录 nanoMuse Cloud。」，显示在按钮下面。聊天模型是账号的时候关掉「使用 nanoMuse Cloud 模型」会被拒绝（`409 chat_on_cloud`，「先添加一个自己的服务商；关掉 nanoMuse Cloud 后没有别的模型能回答。」），显示在开关下面。

**连接测试失败**（模型、动手下面的「测试」）说的是同一个错误在聊天里会说的那句话（`POST /api/connections/llm/test` 返回 `{ok: false, code, error, detail}`；`error` 是那句话，`detail` 是服务商的原话），下面带「详情」。

**哨兵为什么询问**由运行时根据它的设置写出（`'shell' is in always_ask_tools`、`risk level is 'sensitive' (mode=ask)`、`covered by your 'always' permission for shell:ls`、污点那句）；`web/src/i18n/index.ts` 里的 `localReason()` 认识这些形状，把每一条按控制台的语言写成一句话，保留工具、风险和目的地。今日记录里被拒绝的一步下面是同样的话。不认识的形状原样显示。

**你授予的权限**（头像 → 权限）按它覆盖的工具的风险等级列出，最重的在前：敏感、中等、低、安全（等级来自 `GET /api/state` → `settings.tools`）；每一行写明工具、授权持续多久、什么时候给的，可以单独撤销。

## 检查 {#checks}

```sh
cd web && npm run lint && LANG=en_US.UTF-8 npx vitest run && npm run build
```

构建会写出 `nanomuse/server/static/`，它随改动一起提交；`web/tsconfig.tsbuildinfo` 是副产物，不提交。
