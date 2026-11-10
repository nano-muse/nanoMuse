# 网页版 {#应用}

联系人搜索和最近编程工作区会在切换查询、助手或设备时清空旧结果，之后返回的旧请求也不会覆盖当前结果。

> **旧版 Python 实现的设计记录**，对应 `nanomuse/` + `web/`，历史标签为 `pre-openminis`。本文介绍通过浏览器访问的 `nanomuse serve` 网页版。早期桌面版也使用这一界面，当前[桌面版](desktop.md)已改用 DeepSeek Harness。nanomuse.cn/web 则是运行在模拟手机上的演示。`android/` 手机 App 基于 OpenMinis，见 [android.md](android.md)，首次使用先登录账号，再设置模型。各端默认使用内置小龙，也可使用[形象工作室](avatar.md)绘制的形象。旧版小熊猫和玩偶已移除，旧配置仍引用它们时也显示小龙。

`nanomuse serve` 在同一个进程中运行常驻智能体，并提供适合手机访问的网页界面。前端是 React 单页应用，构建结果保存在 `nanomuse/server/static/`，随 Python 包发布；后端使用 FastAPI，通过 WebSocket 持续推送实时事件。

> 术语说明：运行时是执行智能体和工具的程序；API 是供界面或其他程序调用的接口；REST 指通过 HTTP 路径和 GET、POST 等方法组织接口；WebSocket 是可持续双向传消息的连接；构件是智能体生成、可在 App 中打开的文件或页面；对话已污染表示接触过私密数据，后续外发需要额外检查。

```bash
nanomuse serve                      # http://127.0.0.1:8787, this machine only
nanomuse serve --host 0.0.0.0       # also reachable from your phone on the same network
nanomuse serve --port 9000 --no-qr
```

<p align="center">
  <img src="../screenshots/web/chat-approval.png" width="24%" alt="聊天：一张审批卡片">
  <img src="../screenshots/web/feed.png" width="24%" alt="动态：写给你的几条">
  <img src="../screenshots/web/goals.png" width="24%" alt="目标：追踪中的和一次性的">
  <img src="../screenshots/web/library.png" width="24%" alt="资源库：带实时预览的页面">
</p>

界面以接近纯白和纯黑的底色为主，蓝色只用于链接。智能体消息采用浅灰圆角气泡，你的消息使用当前聊天的对比色，黑色背景上为白色气泡，白色背景上为黑色，见 [android.md](android.md)。聊天顶部的龙会根据工作状态改变姿势，底部悬浮的毛玻璃圆角栏包含五个图标。内置字体为 OFL 许可的 [Figtree](https://github.com/erikdkennedy/figtree)，设计依据见 [design.md](design.md)。

## 在手机上打开 {#getting-it-onto-your-phone}

1. 使用 `--host 0.0.0.0` 启动，或设置 `server.host`。终端会显示访问 URL 和二维码。
2. 手机扫码打开。访问令牌位于链接片段 `#token=…` 中，浏览器不会将片段发给服务器。App 读取并保存令牌后，会将其从地址栏移除。
3. 在浏览器菜单选择「添加到主屏幕」。网页已提供 manifest（安装信息清单）和图标，添加后可像原生 App 一样全屏打开。

令牌首次生成后保存在 `<data_dir>/server_token`。也可通过 `server.token` 或 `NANOMUSE_SERVER_TOKEN` 自行指定。在不完全受你控制的网络中，请保持 `server.auth = true`。外网访问应通过 Tailscale 或带 TLS 加密的反向代理，不要直接开放端口。

## 首次使用 {#first-run}

<p align="center">
  <img src="../screenshots/web/onboarding.png" width="24%" alt="第一次打开：认识你的 nanoMuse">
</p>

数据目录尚无内容时，App 先显示设置流程。开头说明它能替你执行任务、关闭界面后仍可继续运行，以及重要操作会先询问。你不必另填个人资料表：配置模型后，智能体会在聊天中介绍自己并询问如何称呼你。随后清单会随完成情况打勾：

1. **添加模型**。按协议分组，包括 OpenAI 兼容 Chat Completions、Responses API、本地或自定义接口，服务商提示包含 DeepSeek、Kimi、Qwen、GLM、豆包、MiniMax、OpenAI、OpenRouter、Ollama 及其他 OpenAI 兼容服务。key 默认隐藏，可切换显示，每家附「获取 key」链接。key 保存到服务器保险库，不交给模型。基础 URL 没有路径时自动加 `/v1`；Ollama、自定义接口允许不填 key。模型列表来自接口自身的 `/models`，无法连接时改用目录，但不会覆盖你手填的模型。
2. **连接邮件、日历和联系人**。这一步可选。
3. **开始**。进入聊天，由智能体先开口，询问你的名字并与你一起给它起名，见[首次对话](web.md#the-first-run-and-the-chat-s-opening)。

保存模型前，「开始」不可点击；「跳过设置」始终可用，也会跳过首次对话。刷新页面会保留已完成项。之后可从形象菜单修改名称、形象、简介和语气，「设置」也提供身份表单。设置完成或已有对话后，不再显示引导。

「开始」通过 `POST /api/firstrun/start` 标记设置完成，作用与 `POST /api/onboarded` 相同。如果此时已有对话，或首次对话结束，后台会生成第一天的动态内容，让你首次打开「动态」时即可阅读；其他情况下，动态先显示介绍卡并说明每日例程时间。

## 界面与功能 {#what-is-on-the-screen}

界面有「聊天」「动态」「点子」「目标」「资源库」五个标签，点击形象可打开菜单。手机宽度下，五个无文字图标位于底部圆角悬浮栏，距底边 12 px，与聊天输入框等宽，最大 420 px，宽屏居中。它与 Android 使用相同栏样式：半透明模糊背景、细边线，当前图标为实心，并有对比色指示底，浅色主题用黑色、深色用白色；其他图标为灰色线条。页面与输入框都会避开悬浮栏。宽窗口，以及任何宽度的桌面 App，改用侧栏。

**聊天**。包含一个主要聊天和多个旁聊，左上圆形「聊天」按钮打开列表抽屉。回复边生成边显示，工具调用以小标签出现，点击可查看参数和输出。智能体写入的文件显示为构件卡片，可直接打开。哨兵需要你决定时显示审批卡片，需要补充信息时显示提问卡片。任务执行期间输入框仍可用，新发消息会在下一次模型调用前加入当前任务。

*赞踩与停止原因*。最新完成的回复下方显示赞和踩。点踩后可选「答错了」「没帮上忙」「不该这么做」「太慢了」「其他原因」或「跳过」。再次点击相同赞踩按钮会撤回；已经标记的回复在新回复出现后仍保留标记。停止任务后，聊天中显示「为什么停下来？」，选项为「方向不对」「太慢了」「改主意了」「已经做完了」「其他原因」「跳过」。回答、跳过或等待一分半后，卡片关闭。

两类反馈都通过运行时 `POST /api/threads/{id}/feedback` 保存到对应回复。运行时已登录 nanoMuse Cloud 时，还会将原因代号和所属调用 ID 发送给账号记录，不发送对话文字。

*附件*。点击「+」或粘贴可添加照片和文件，来源为相机、相册或手机文件。每条最多十个，每文件默认 25 MB，由 `server.max_upload_mb` 控制。选中后立即上传，显示为可移除的缩略图或附件标签，也可以只发送附件。文件存入工作区 `attachments/<date>/`，因此也会出现在资源库，并能被工具读取。消息会向智能体列明文件及类型。

`llm.vision = auto` 会尝试将图片作为图像输入。接口拒绝时，例如 DeepSeek 或多数纯文本模型，此后只发送文字，并提示一次。图片仍保留为文件，智能体知道名称，但会明确说看不到，不猜测内容。`off` 从不发送图像，`on` 始终按图像发送。手机照片编码前缩至 1568 px，因此 10 MB 原图的图像调用成本与缩小后的图片相同。PDF、电子表格和文档通过 `files` 读取，PDF 按页提取文字；扫描 PDF 没有文字层时会说明。点击聊天图片或文件标签可打开。

*浏览器视图*。调用浏览器工具时，聊天显示浏览器卡片，包含每步后的网页图片、标题、URL 和操作说明，例如打开 example.com 或点击登录。运行期间实时更新，结束后保留。点击卡片可放大，「接管」允许在画面点击、向当前输入框输入、按 Enter 或打开 URL；「交还」后，智能体会了解用户操作并继续。登录时，智能体在表单前交接，由你输入密码，密码直接给网站，不经过模型。

网页画面仅保存在服务器当前会话内存中，每聊天最近约十二帧；重启后旧卡片显示占位内容。需要安装浏览器工具 `pip install "nanomuse[browser]" && playwright install chromium`，或使用 `-browser` Docker 镜像。旧版 Android 连接后也可提供自身 WebView（内嵌浏览器），卡片 `backend` 会说明实际后端。在手机上接管 WebView 时，会弹出真实网页面板，可用手机键盘和自动填充登录，再点「完成」继续。兼容性与登录限制见 [browser.md](browser.md)。

**动态**。上方「动态偏好」可填写想读的内容，例如骑行、Rust 和每周一道菜谱。每天一次，或点击「写几条新的」时，智能体根据偏好、目标和记忆生成三条短文。每条「问问 {name}」会围绕该内容开启聊天。下方「你离开期间」列出后台任务结果和文件、全部聊天中待处理审批与问题、今日日历，以及显示下次时间和待推进目标的「接下来」。未读数显示在标签上。

帖子、活动、「接下来」或日历加载失败时，只在对应区域显示错误和「重试」。重试仅请求该区域，刷新失败也保留上次成功内容，并附错误说明。

**点子**。按目标、记忆和近期聊天生成建议，分为规划、调研、目标、金钱、健康、居家、学习、人物、文件、娱乐。点击建议会作为消息发送，「刷新」重新生成。

**目标**。分为定期检查的「追踪」和逐步执行的其他「目标」。每行显示随计划推进填充的进度圆圈、下次跟进或最近更新或到期日，以及完成步数。智能体或用户都可创建，用户使用「+」。目标可分健康、财务、职业、学习、人际、家庭、居家、旅行、创作，选填到期日期和跟进周期。计划步骤可为待办、进行中、完成或受阻，并可写备注。「现在就推进」会执行一轮后台任务并将结果发送到主要聊天；「现在跟我确认进度」立即发送跟进提醒。

- *目标日期*：卡片显示「5 天后到期」或「原定 9 月 12 日到期」。后台选择任务时优先逾期目标，并告知模型。
- *跟进*：例如每天 08:00、工作日 07:30、每周一 09:00、每月 1 日。到时只发短消息，说明目标、下一小步并询问进度，不执行任务。用户主动设置的跟进在所有主动性档位有效，但会避开免打扰时段。「日程」显示后续安排。
- *计划变更*：模型发现计划不合适时，先提出剩余步骤的新方案和理由，不直接修改。提案卡片出现在目标页顶部及目标详情。「采用 nanoMuse 的计划」保留已完成步骤，替换剩余部分；「保留我的计划」维持原样。两种选择都会留下备注。

**提醒和例程**。你可以在聊天中要求，例如六点提醒打电话、每工作日 07:30 提供天气，也可从「日程」添加。提醒只在指定时间向原聊天发一条短消息；例程会使用工具执行任务，例如读收件箱、检查网页或运行脚本，再汇报。周期格式为 `daily 08:00`、`weekdays 07:30`、`weekly mon 09:00`、`monthly 1 09:00`。用户明确设置的时间不受主动性或免打扰影响，聊天繁忙时排队等待，不会丢弃。已触发项在「最近完成」保留一周。终端可用 `nanomuse reminders list | add | cancel`。

提醒、例程、目标推进、目标检查和触发器，在进入聊天队列前会先写入数据目录的 `scheduled-deliveries.db` 持久投递队列。运行结束后才标为已触发，完成、失败或停止都算结束。崩溃或重启使排队中、运行中的任务未能结束时，下次启动会重新排入一次；已完成的同一次投递不会重复。因此会修改外部数据的例程，在重做前应检查原修改是否已发生。

关机或睡眠错过的执行时间只补做一次。例如每日例程错过三天，恢复后只执行一次，再按下个时间继续。定时任务不会插入正在运行的对话，而是等待并作为独立一轮执行。

<a id="triggers"></a>**触发器：当某事发生时**。触发器由外部事件启动任务。可以在聊天中说房东回信后总结并起草回复、标题含 *review* 的会议前半小时准备简报、部署脚本调用后检查网站，也可在日程 → 当某事发生时添加。支持四类：

- 新邮件：发件人或主题包含全部指定词时触发。有此触发器时每五分钟查邮箱，首次连接不重放旧邮件。
- 日程开始前：匹配标题或地点的事件在 N 分钟后开始时触发。
- webhook：外部系统主动发请求的通知接口，使用带 key 的 URL。CI 自动构建任务、家庭自动化或 cron 定时命令中的 `curl` 等可发送 `POST`，请求正文作为任务背景。
- 设备上线：同账号设备上线，名称或类型包含全部指定词时触发。本机不作为自己的上线事件，启动时已经在线的设备也不算新上线。

任务在设置触发器的原聊天中执行，将邮件、日程、设备信息或请求作为背景，结果在动态标为「新邮件：…」「即将开始：…」「Webhook：…」「设备上线：…」。邮件 UID、日程开始时间用于去重，同一事件不重复触发；webhook 间隔不到十秒会拒绝，错误 key 与错误 URL 都返回相同表现。邮件、日程和设备在线情况属于私密数据，触发后对话会标为已污染，向允许列表之外的主机发送数据需要审批。模型被要求将事件内容视为数据，不能当作指令。「现在运行」用样例事件测试，列表显示触发次数和最近读邮箱时间。终端可用 `nanomuse triggers list | add | cancel`。

hub 自动重连时，设备触发器会保留上次观察到的在线状态。上次离线的设备若在重连后的首个设备列表中变为在线，仍会触发。退出登录、切换账号或关闭 hub 会清除这份记录，重新加入后的首个列表只记录状态，已有在线设备不会触发。

**资源库**。列出工作区全部文件，最新在前，支持搜索和按页面、文档、图片、数据、代码筛选。页面可实时查看，Markdown 格式化显示，CSV 变为表格，图片和 PDF 内嵌展示。智能体生成的页面在沙箱 iframe（隔离的嵌入页面）中运行，采用 opaque origin，即不共享主页面身份，不能读取访问令牌或调用 API。每个 HTML 响应也附 `Content-Security-Policy: sandbox` 实施相同隔离。

**形象**。聊天顶部的龙下方显示当前聊天状态：正在做什么，或等待你回答。各状态图位于 `web/public/avatars/dragon-*.webp`，待命时静候，工作时戴耳机在小电脑前输入，等待时看水晶球，完成时抱星星，工具失败或拒绝时出现汗滴。点击形象也会有回应。[形象工作室](avatar.md)绘制的面孔使用相同状态；设置中可换成整体呼吸、摇摆或跳动的 emoji。Android 还可用自己的短视频作形象，仅保留在该手机，见 [avatar.md](avatar.md#your-own-clip)。开启 `prefers-reduced-motion` 后全部动画停止。

「聊天」标签角标汇总各处待审批数。点击形象打开状态面板，显示大形象、同一状态说明、当前模型和哨兵模式。运行中显示「停止」，点击会结束任务，关闭本聊天待处理卡片，对话仍可继续。面板包括：

- 「审批」：汇总所有聊天待处理卡片，可直接回答；存在待处理项时优先打开此页。
- 「活动」：包含每次工具调用、决定和审批的审计记录，拒绝操作也记录。
- 「权限」：哨兵模式及所有可撤销的长期授权，也可以开启[模型观察](sentinel.md#optional-model-observations)，在「活动」中查看审核建议。
- 「日程」：后台工作开关、下次执行时间、排队目标、目标检查、提醒、例程和「当某事发生时」触发器，提供「+ 添加」「现在运行」和取消。webhook 的复制 URL 按钮是唯一显示 key 的位置，创建它的聊天只写地址和请求头。
- 「记忆」：按类别显示全部记忆，支持手动添加。「忘掉」会删除，模型不再读到该项，并在「最近的改动」保留原文。每轮按关键词选取相关记忆；连接 → 按含义召回配置 embedding（将文字转换为可比较向量）接口后，也能按语义匹配。例如写邮件给房东，可以找到房东姓名，即使两句话没有共同词。「整理」可手动执行，智能体也会每新增八行或每周自动执行，主动性「关闭」时除外。相同事实合并、变化事实留新版、非个人事实的一次性请求删除。模型只提案，nanoMuse 检查合并不增加原文没有的词、不删除用户亲写内容，每次最多移除记忆库五分之一。「最近的改动」列出合并、删除、更新和遗忘，保留旧文并支持「撤销」。产生修改的整理会显示在动态。
- 「技能」：保存周回顾、旅行规划、收件箱处理等任务步骤，见[技能](#skills)。
- 「连接」：管理模型和外部服务，以下说明各配置卡片。
- 「设置」：名称、形象、颜色、性格、如何称呼你；哨兵模式，平衡为 `ask`、谨慎为 `strict`、放手为 `auto`；命令是否在[沙箱](sentinel.md#the-sandbox)运行；主动性、跟进间隔和免打扰，见[后台工作](#background-work)；通知；Android 旧版「保持运行」的电池、悬浮窗、闹钟权限、重启自启和日志导出，见 [archive/android-python-line.md](../archive/android-python-line.md#keeping-it-running)；「显示思考过程」、应用语言、回复语言。版本信息始终显示已安装版本和最新版本，如「最新版 0.1.x，你已经在用了」「0.1.x 已发布 · 更新」「没能检查到最新版本 · 现在检查」。先查 `nanomuse.cn/dl/index.json`，再查 GitHub。

「连接」中的**模型**卡提供百炼、OpenRouter、DeepSeek、OpenAI、Ollama 及自定义 OpenAI 兼容服务商预设，设置模型名、工具调用模式和 API key。服务能力和 ChatGPT 登录见 [web.md](web.md)。key 以 `LLM_API_KEY` 写入保险库，并立即应用到所有对话。「测试」让模型返回一个词。托管 nanoMuse Cloud 的 `Qwen/Qwen3.6-27B-FP8` 支持聊天、附件图片理解和操作屏幕。

下方「手的模型」「生成图片」「生成视频」卡片对应手机、桌面设置 → 模型中的其他三项。「自动」依次使用具备能力的聊天服务商、实际模型菜单中提供该能力的已登录中继、其他自备服务商。托管 Cloud 因而可用于屏幕操作，不能生成媒体；图片和视频需自己的服务商及 API key。卡片显示「当前为 服务商 · 模型」。DeepSeek 仅 ID 含 `v4.1`、`vision`、`ocr` 的模型视为支持图片。

**按含义召回**通过兼容 OpenAI 的 `/embeddings` 查找语义相关记忆。选「自动」时，有向量接口就用聊天模型接口，没有则只按关键词；也可明确开启、关闭或指定另一接口。例如 DeepSeek 没有此接口时，可搭配 Ollama `qwen3-embedding:0.6b`。key 名为 `EMBEDDINGS_API_KEY`，模型留空采用接口默认。「测试」先调用一次，成功后立即为全部记忆建立索引，并显示数量。

**网页搜索**支持无需配置但可能受抓取限速影响的 DuckDuckGo；带 key 的 Brave Search、Tavily、Serply；可不带 key 的 You.com，未带时每天 100 次；Parallel，不带 key 免费但限额较低；Keenable，不带 key 每小时 1,000 次；以及指定 URL 的 SearXNG。搜索 key 存为 `SEARCH_API_KEY`。「测试」显示服务商、结果数和耗时，搜索失败时会说明并退回 DuckDuckGo。

**邮件**提供常见服务商预设，填写地址、应用专用密码和 IMAP / SMTP 收发服务器，凭据名为 `EMAIL_ADDRESS`、`EMAIL_PASSWORD`。「连接」验证两种协议均能登录，「断开」移除凭据与工具。**日历**可填私密 `.ics` 链接或文件、工作时间并「重新读取」，链接存为 `CALENDAR_<NAME>`。今日日程显示在动态，起草日程通过「加入日历」添加。**联系人**支持 `.vcf` 上传、文件路径或链接，链接存为 `CONTACTS_<NAME>`，可查看数量并搜索；「我的联系人」由智能体根据聊天补充。

**浏览器**提供开关，缺少 Playwright 时提示安装。**MCP 服务器**可添加 stdio 标准输入输出命令或 URL，选择工具风险并移除；来自 `config.toml` 的服务器只能查看。**保险库**可添加或删除机密条目，接口只返回名称，不返回真实值。

App 支持英语和简体中文。设置 → 应用语言保存在本设备浏览器，不保存在服务器。「自动」跟随浏览器语言，日期和相对时间也随之变化；「回复语言」单独决定智能体回答使用的语言。字符串位于 `web/src/i18n/`，英文原文作 key，`zh-CN.ts` 提供翻译。界面文字缺少翻译时，单元测试会失败。

### 技能 {#skills}

技能是包含 `SKILL.md` 的文件夹，文件开头声明名称和简短说明，之后用 Markdown 编写步骤。它遵守 [Agent Skills](https://agentskills.io) 格式，可以与其他智能体共用。内置十二个技能：`skill-creator`、`weekly-review`、`trip-plan`、`inbox-triage`、`compare-options`、`meeting-prep`、`phone-messages`、`feishu`、`tencent-meeting`、`amap`、`kuaidi100`、`train-tickets`。用户技能位于 `<data_dir>/skills/<name>/`，同名时覆盖内置技能。

系统提示词提供所有已启用技能的名称和说明。模型按请求选择，例如京都旅行会选 `trip-plan`，再通过 `skills` 工具读取完整步骤。你也可以输入 `/` 查看技能，按 `Tab` 补全首个匹配；`/trip-plan Kyoto, 5 days in November` 会将技能指令和你的任务一起发送。 智能体工作期间也可以调用已启用的技能，指令会在下一次模型调用前加入。技能涉及的工具操作仍遵守原有哨兵审批规则。

添加方式有三种：在技能 → 新建中编写，填好名称后有模板；粘贴原始 `SKILL.md`、GitHub 文件或目录链接并点击「获取」；任务成功后要求「把这个存成技能」。智能体写入前会请求审批，因为 `skills` 的 action=save 是敏感操作，即使 `auto` 也需要，删除同样如此。关闭技能会将其从模型索引移除。内置技能的「复制一份改成你的」会创建用户副本并打开编辑。技能脚本和参考文件在[沙箱](sentinel.md#the-sandbox)内只读可见。终端命令为 `nanomuse skills list | show | add | new | remove | enable | disable`。

### 通知 {#notifications}

设置 → 通知 →「让 nanoMuse 通知这台设备」使用标准 Web Push（浏览器网页推送），通过浏览器自身推送服务，无需另注册账号。服务器首次生成 VAPID 推送密钥对，保存在 `<data_dir>/push-vapid.json`；设备订阅保存在 `push-subscriptions.json`。

需要审批、需要回答问题、后台任务完成且有结果要汇报，或目标到跟进时间时，会发送通知。无变化的后台检查和逐步过程不发送；App 正在前台显示时也不再通知，因为卡片已经可见。点击通知打开对应聊天。添加到手机主屏幕后，图标角标显示待处理卡片数量。

推送必须在 `https://` 或 `localhost` 的安全环境中使用。局域网明文 `http://` 下，其他功能正常，开关会解释推送不可用的原因。TLS 配置见[部署](deployment.md#reaching-it-from-outside-your-network)。其他 App 内嵌浏览器通常不支持推送，应使用 Chrome、Edge、Firefox 或 Safari 16.4+；iOS 仅主屏幕安装的网页 App 支持。

「连接」中的非机密选项保存到 `<data_dir>/app-settings.json`，每次启动覆盖 `config.toml` 对应设置，命令行也沿用，因此手机操作配置无需手改文件。机密在文件中只保留 `{{vault:NAME}}` 引用。

### 打开指定对话并预填内容 {#opening-the-app-on-something}

页面支持查询参数，Android 和书签均可使用：`?thread=<id>` 打开对话，`?tab=goals` 打开指定标签，也支持 feed、ideas、library、connections；`&draft=<text>` 预填输入框，不发送；`&attach=<json>` 将工作区已有文件显示为附件，JSON 是 `POST /api/files/upload` 返回的 `{path, name, mime, size}` 列表。参数仅读取一次，随后从地址栏移除。

手机的分享 → nanoMuse 使用这一流程：先通过 `POST /api/files/upload` 上传分享文件，再用 `POST /api/threads` 建立以主题或首个文件命名的对话，打开时预填草稿和附件，等待你下指令。手机自身功能也可作为工具，工作区可从「文件」App 访问，见 [device.md](device.md)。

## 后台工作 {#background-work}

设置中的「主动性」决定智能体主动推进任务和通知你的频率：

| 档位 | 执行频率 | 何时通知 |
|---|---|---|
| 关闭 | 不执行 | — |
| 低 | 每 2 × 配置间隔 | 完成步骤或需要用户时 |
| 默认 | 每个配置间隔 | 有实际进展或值得告知的信息时 |
| 高 | 每 ½ 配置间隔 | 每次都报告，包括没有偏离计划时 |

每轮选择一个仍有待办步骤的活跃目标，在主要聊天中以哨兵 `auto` 执行。明确拒绝规则和危险调用警告仍有效，需要审批时会显示为动态卡片。模型自行判断是否值得通知。无新情况的摘要以 `[quiet]` 开头，聊天显示可展开的灰色一行，例如「已检查目标：没有新进展」，动态也只列一行，不增加角标。其他结果按普通消息显示。

免打扰时段例如「22:00–08:00」，按服务器本地时间计算。落在其中的后台任务会推迟到时段结束。「日程」与动态「接下来」显示档位、实际间隔、下次执行时间或当前免打扰结束时间。需要每一步都由你判断的目标，可以暂停该目标，或将主动性设为「关闭」。

## API {#api}

界面全部通过这套 API 调用运行时，因此 Telegram 机器人、桌面小组件等前端也能控制同一个智能体。除 `server.auth = false` 外，所有请求都需要 `Authorization: Bearer <token>`。

0.1.33 起拒绝 `?token=`，因为 URL 令牌会进入沿途访问日志。此类 HTTP 请求返回说明原因的 401；WebSocket 返回带 `code: "legacy_token"` 的 `error` 帧并以 4401 关闭。内嵌文件 `/api/files/*` 和浏览器图片可用签名链接访问：客户端用令牌生成 `?exp=<unix seconds>&sig=<HMAC-SHA256(token, "<exp>\n<path>")[:32]>`。即使链接进入日志，也只在数小时有效期内开放指定路径，不授予其他接口权限。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 检查服务是否存活，并返回版本。 |
| GET | `/api/state` | 获取配置档案、运行状态、对话列表、待审批项、目标和设置。 |
| GET / POST | `/api/threads` | 读取对话列表；或提交 `{title}` 创建对话。 |
| PATCH / DELETE | `/api/threads/{id}` | 修改对话标题；或删除对话。 |
| POST | `/api/threads/{id}/clear` | 清除该对话的聊天内容。 |
| GET | `/api/threads/{id}/events?limit=&before=` | 按限制和游标读取时间线事件。 |
| POST | `/api/threads/{id}/send` `{text, files?, language?, via?}` | 将消息加入队列后立即返回。`files` 使用上传接口返回的工作区路径，最多十个，有附件时 `text` 可空。1.0.0 起，`language` 为界面 BCP-47 标签，如 `en`、`zh-CN`；除非「回复语言」已固定，否则按该语言回答，未提供则沿用文字系统判断。`via: "cloud"` 对应「这次改用 nanoMuse Cloud」，仅此轮用账号 key 和推荐聊天模型，下轮恢复已配置模型，`[llm]` 不改。用户消息、回复和失败提示都带 `model_used`。未登录返回 `401 signed_out`。 |
| POST | `/api/threads/{id}/stop` | 结束本聊天当前运行，清空等待队列，并让本聊天待审批和提问卡片过期，之后仍能继续对话。没有运行中的任务时返回 `{ok: false}`。 |
| POST | `/api/threads/{id}/feedback` `{event, vote, reason?}` 或 `{stop_reason}` | 记录回复反馈或停止原因。`event` 指 assistant 事件 ID；`vote` 为 `up`、`down`，`""` 撤回；可选 `reason` 为 `wrong`、`unhelpful`、`unsafe`、`slow`、`other`。返回添加了 `feedback` 的事件。停止反馈使用 `stop_reason`，取 `wrong`、`slow`、`changed_mind`、`done`、`other`、`skipped`，关闭问题卡片时发送 `skipped`。反馈随对话保存；已登录 nanoMuse Cloud 时，按 assistant 的 `turn`、`turn_source` 关联为 `turn.feedback` 或 `turn.stopped` 事件，不发送回复文字，见 [cloud.md](cloud.md#client-events)。事件并非回复返回 404，非法代号返回 400。 |
| POST | `/api/files/upload?name=` （请求体：文件字节） | 将附件字节写入 `attachments/<date>/`，文件名采用经过安全处理的 `name`。返回 `{path, name, size, kind, mime}`，供消息 `files` 使用；超过 `server.max_upload_mb` 返回 413。 |
| POST | `/api/approvals/{id}` `{approved, scope, reason}` | 提交审批决定。`scope` 必须来自卡片 `grant_options`，可为 `once`、`conversation`、`session`、`24h`、`always`；旧值 `task` 仍视为 `conversation`。 |
| DELETE | `/api/approvals` | 清除全部已授予权限。 |
| DELETE | `/api/approvals/grants/{key}` | 按 `/api/activity` 返回的 `key` 撤销单项授权，例如 `shell:git`。 |
| GET / POST | `/api/goals[?status=&category=]` | 读取目标；或创建 `{title, description, steps[], category, due (YYYY-MM-DD), check_in ("daily 08:00", "weekdays 07:30", "weekly mon 09:00", "monthly 1 09:00")}`。 |
| GET / PATCH / DELETE | `/api/goals/{id}` | 获取目标；修改 `{status, note, step_index (1-based), step_status, step_note, title, description, category, due, check_in}`；或删除目标。`step_index` 从 1 起，`""` 可清除 due / check_in。 |
| POST | `/api/goals/{id}/steps` `{title}` | 用 `{title}` 为目标追加步骤。 |
| POST | `/api/goals/{id}/advance` | 立即对该目标执行一轮后台推进。 |
| POST | `/api/goals/{id}/check-in` | 立即发送该目标的跟进提醒。 |
| POST / DELETE | `/api/goals/{id}/proposal/accept`、`/api/goals/{id}/proposal` | 接受智能体建议的计划修订；或撤销该提议。 |
| GET / POST | `/api/memory` · DELETE `/api/memory/{id}` | 获取记忆列表；以 `{content, category}` 添加；或删除指定记忆。 |
| POST | `/api/memory/tidy`（`?dry_run=1`） | 立即整理记忆，报告已合并、已移除内容；带 `?dry_run=1` 时仅报告预计改动。 |
| GET | `/api/memory/changes` · POST `/api/memory/changes/{id}/restore` | 按最新在前读取合并、删除、更新和遗忘日志；或恢复某次改动。 |
| GET | `/api/ideas?refresh=1` | 获取已有建议，或按参数重新生成。 |
| GET | `/api/activity` | 返回最新审计记录、已授予的 `grants[]`，各项含 `key`、`tool`、`target`、`scope`、`expires_at`，以及对话污染标记。 |
| GET | `/api/feed?limit=` | 按最新在前返回「你离开期间」：`{id, ts, kind (background · artifact · approval · question), title, text, thread, thread_title, path}`。 |
| GET | `/api/feed/posts` | 获取动态文章：`{instructions, daily, time, generated_at, posts[{id, ts, title, body, area, prompt}], error?}`。 |
| PUT | `/api/feed/instructions` `{instructions?, daily?, time?}` | 设置文章偏好，最多 2000 字符，并配置每日例程是否开启及时间。时间格式 `HH:MM`，初始值 08:00。 |
| POST | `/api/feed/posts/refresh` | 立即生成新文章；模型拒绝时通过 `error` 说明。 |
| DELETE | `/api/feed/posts/{id}` | 删除指定文章。 |
| GET | `/api/upcoming` | 返回 `{proactivity, proactive, interval_minutes, effective_interval_minutes, quiet_hours, quiet_until, next_pass_at, next_wake_at, queue[{goal_id, title, category, due, overdue, next_step, progress}], check_ins[{goal_id, title, at, cadence}], reminders[], triggers{items[], available{mail, event, hook, device}, mail_checked_at, mail_error, mail_poll_minutes}, busy}`。`next_wake_at` 为提醒、目标检查或后台任务中最近的待执行时间，供能够设置系统闹钟的宿主使用，见 [local-runtime.md](local-runtime.md#waking-up)。 |
| POST | `/api/tick` | 立即唤醒调度器，检查并执行已到期工作，返回 `{ok, next_wake_at}`。Android 的系统闹钟触发后调用此接口。 |
| GET / POST | `/api/reminders[?all=1]` | 获取活跃提醒，带参数时获取最近全部提醒；或创建 `{text, at ("YYYY-MM-DD HH:MM") or repeat ("daily 08:00", …), kind (remind · task), thread}`。 |
| POST / DELETE | `/api/reminders/{id}/fire`、`/api/reminders/{id}` | 立即在原聊天发送提醒；或取消该提醒。 |
| GET / POST | `/api/triggers` | 列出触发器及各类型连接器是否可用；或创建 `{kind (mail · event · hook · device), text, match, lead_minutes, thread}`。hook 类型返回其 `url`。 |
| POST / DELETE | `/api/triggers/{id}/fire`、`/api/triggers/{id}` | 通过样例事件立即执行触发器；或取消它。 |
| POST | `/api/hooks/{id}?key=` | 接收 webhook，无需 App 令牌，以 key 验证，也接受 `X-Hook-Key`。请求体最多 64 KB，JSON 会格式化后作为任务背景。ID 或 key 错误都返回 404；已取消返回 409；请求过密返回 429。 |
| GET | `/api/files` · `/api/files/{path}?download=1` | 列出或读取工作区文件。HTML、SVG 响应附 `Content-Security-Policy: sandbox`。 |
| GET | `/api/data/export` | 以 ZIP 导出智能体数据，见 [parity.md](parity.md#open-for-a-decision-the-next-next-list) 备注 37。包含配置档案、侧栏各房间、联系人、授权、`threads/`、`sessions/`、数据目录技能、上传联系人、手机与电脑轨迹、定时投递、nudges 和逐项说明的 README。不含 `vault.enc`、`vault.key`、`server_token`、`push-vapid.json`、设置文件、`logs/`、`workspace/`。数据根若为符号链接或 Windows 联接，先解析一次并固定目标；其内符号链接、硬链接、Windows 重解析点、读取时改变的文件和超过 64 MB 的文件会跳过。数据库通过运行时已打开的连接执行 SQLite 在线备份，包含已提交 WAL 事务，不重新打开源路径。缺少活跃存储、未提交事务、数据库忙碌或过大时跳过，并写入 ZIP README。备份最多重试五秒，临时输出在响应前移除。ZIP 时间戳限制于 1980-2107 年，其他文件通过已验证句柄读取，父目录同时固定。作为附件返回，并附 `Cache-Control: private, no-store`。 |
| GET / PUT | `/api/settings` | 获取或修改 `{profile{name (≤ 20), avatar, emoji, color, tagline (≤ 60), tone, communication, style, user_name, proactive, goal_interval_minutes}, sentinel_mode, sentinel_review{mode, provider, model, base_url, api_key}, show_thinking, language}`。审核模式为 `off` 或 `observe`。读取结果另含 `onboarded`、`llm_ready` 和 `sentinel.review`，只返回 `has_api_key`，不返回审核 key。 |
| GET | `/api/connections` | 获取模型、服务商预设、邮件、浏览器、MCP、保险库名称和 `onboarded`。模型含 `key_source`，值为 vault · config · missing · none，引用接口列表时带 `endpoint`。`endpoints` 列出自定义 OpenAI 兼容接口 `{id, label, base_url, key_source, models, slots}`，不含 key。MCP 包含 `connected`、`tools`、`from_app`。 |
| PUT | `/api/connections/llm` `{provider, model, base_url, tool_mode, api_key}` 或 `{endpoint, model, tool_mode}` | 更换聊天模型。提供 `api_key` 时存保险库，`""` 表示不使用 key，省略则保留。`endpoint` 引用列表中的接口地址和它自己的 key。在全部对话立即生效。地址包含 `user:pass@` 返回 400，凭据应放入 `api_key`；`/api/llm/models`、`/api/connections/gui`、`/image`、`/video` 和接口列表同样拒绝这种地址。 |
| POST | `/api/connections/llm/test` | 向模型发送简短测试，返回 `{ok, reply, ms}` 或 `{ok: false, error}`。 |
| POST | `/api/llm/models` `{preset, base_url, api_key}` 或 `{endpoint}` | 通过指定 key 请求接口的 `/models`，再尝试 `/v1/models`；未提供 key 时用保险库。成功返回 `{models, source: "live"}`。不可达时返回预设目录及 `source: "catalogue"`、`error`；列表内 `endpoint` 则沿用已保存模型。带 key 的请求仅跟随同源重定向，跨源返回 `error: "redirect to another host"`。不保存配置。 |
| POST | `/api/connections/endpoints` `{label, base_url, api_key, models}` | 添加自定义 OpenAI 兼容接口，见 #294。`label` 可省略，默认主机名；可选 `api_key` 存为 `ENDPOINT_<ID>_API_KEY`。接口不提供列表时，`models` 填逗号分隔的模型 ID；两种方式均无模型则返回带说明的 400。成功返回条目。nanoMuse Cloud 或已有目录预设地址不接受，地址已被其他条目使用时返回 409 并指出该条目。 |
| PUT | `/api/connections/endpoints/{id}` `{label, base_url, api_key, models}` | 修改名称、地址、key 或手填模型列表，省略字段保持原值，`api_key: ""` 移除 key。所有使用该接口的模型项随之更新。未知 ID 返回 404，地址重复返回 409。 |
| DELETE | `/api/connections/endpoints/{id}` | 删除接口及其保险库 key。引用它的屏幕、图片、视频模型恢复自动选择；当前聊天模型仍在使用它时返回 409。 |
| POST | `/api/connections/endpoints/{id}/models` | 重新请求并保存接口模型。成功返回条目及 `source: "live"`；失败沿用原列表，并返回 `"kept"` 和 `error`。 |
| PUT | `/api/connections/embeddings` `{mode, model, base_url, api_key}` | 配置语义记忆检索。`mode` 为 auto/on/off；`base_url: ""` 使用聊天模型接口；`model: ""` 使用接口默认；`api_key` 提供时存为 `EMBEDDINGS_API_KEY`，`""` 沿用模型 key，省略不改。立即重建向量化客户端。 |
| POST | `/api/connections/embeddings/test` | 测试一次向量化调用，成功后为全部记忆索引。返回 `{ok, model, dims, indexed, ms}` 或 `{ok: false, error}`。 |
| PUT | `/api/connections/search` `{provider, api_key, base_url}` | 设置搜索服务，`provider` 支持 duckduckgo/brave/tavily/serply/you/parallel/keenable/searxng。`api_key` 提供时存为 `SEARCH_API_KEY`，`""` 移除，省略保留；`base_url` 指定 SearXNG 实例。下次搜索生效。 |
| POST | `/api/connections/search/test` | 仅测试当前搜索服务，不启用回退。返回 `{ok, provider, results, first, ms}` 或 `{ok: false, error}`。 |
| PUT / DELETE | `/api/connections/email` | 保存 `{address, password, imap_host, imap_port, smtp_host, smtp_port, smtp_starttls, enabled}`，地址和密码放入保险库；或断开并移除凭据。 |
| POST | `/api/connections/email/test` | 分别验证 IMAP 和 SMTP 登录，返回 `{ok, inbox}` 或 `{ok: false, error}`。 |
| PUT | `/api/connections/calendar` `{enabled, day_start, day_end, refresh_minutes}` | 设置日历工作时间和刷新间隔，时间格式错误返回 400。 |
| POST · DELETE | `/api/connections/calendar/feeds` `{name, url}` · `/api/connections/calendar/feeds/{name}` | 新增或替换日历源，链接以 `CALENDAR_<NAME>` 存保险库并立即读取，`error` 说明失败原因；或移除从 App 添加的日历源。 |
| POST | `/api/connections/calendar/test` | 重新读取所有日历源，返回 `{ok, events, feeds}` 或 `{ok: false, error}`。 |
| GET | `/api/calendar` | 获取今天、明天的日程：`{configured, today, events[{uid, summary, start, end, all_day, location, description, calendar}], feeds[], fetched_at, stale}`。 |
| PUT | `/api/connections/contacts` `{enabled}` | 启用或关闭联系人工具。 |
| POST · DELETE | `/api/connections/contacts/sources` `{name, url}` · `/api/connections/contacts/sources/{name}` | 新增或替换联系人来源，可为 `.vcf` 路径，或以 `CONTACTS_<NAME>` 存保险库的链接。立即读取，失败通过 `error` 说明；或移除 App 添加的来源。 |
| POST | `/api/connections/contacts/import?name=` | 上传 `.vcf` 原始文件，保存于 `<data_dir>/contacts/` 并加入来源。 |
| POST | `/api/connections/contacts/test` | 重新读取所有联系人来源，返回 `{ok, contacts, sources}` 或 `{ok: false, error}`。 |
| GET | `/api/contacts?q=&limit=` | 按与智能体相同方式查询联系人，返回 `[{id, name, emails[], phones[], org, …}]`。 |
| PUT | `/api/connections/browser` `{enabled}` | 启用或关闭浏览器工具。 |
| PUT | `/api/connections/gui` `{enabled, provider, model, base_url, api_key}` | 配置手机屏幕操作，见 [gui.md](gui.md)。开关立即添加或移除工具。模型字段指定操作器独立模型，`""` 按[配置顺序](configuration.md#the-phone-gui)自动选择，通过 `effective_model`、`effective_source` 返回结果。`api_key` 提供时存为 `GUI_API_KEY`，`""` 沿用主模型 key，省略保留。也可用 `endpoint` 代替 `provider` / `base_url` / `api_key` 引用已保存接口，与聊天模型相同；`PUT /api/connections/image`、`/video` 也支持。 |
| POST | `/api/connections/gui/test` | 向操作模型发简短测试，返回 `{ok, reply, ms}` 或 `{ok: false, error}`。 |
| GET | `/api/phone` | 获取连接手机及最后屏幕：`{connected, device{id, name, platform, gui, apps, width, height}, gui_enabled, last_screen, screen}`。 |
| GET | `/api/hands` | 获取本机屏幕操作状态，见 [gui.md](gui.md)：`{enabled, available, backend, reason, mode, coords, screen_size, picture_size, window{available, reason, active, app, title, frame}, device, task_active, task_text, last_screen}`。手机上返回 `{enabled: false, available: false, reason}`。 |
| PUT | `/api/connections/hands` `{enabled, backend (auto · desktop · pyautogui · xdotool), mode (auto · screen · window)}` | 启停本机操作工具，指定后端和操作模式。省略字段不变，未知后端或模式返回 400；返回上述状态。 |
| POST | `/api/hands/stop` | 对应「手」卡片的「停止」，本机屏幕任务在下一步停止，返回 `{stopped}`。 |
| GET / POST | `/api/holds` · `{thread, tool (browser · computer · phone), reason?}` | 获取当前等待用户的接管状态，或创建接管。当前聊天中相应工具动作暂停到用户点击「完成」。返回 `{type: "hold", id, thread, tool, status, by, reason, ts}`；未知对话返回 404。 |
| POST | `/api/holds/{id}/done` | 结束接管，让等待工具重新观察并继续；已结束则返回现状。未知 ID 返回 404。 |
| GET / PUT | `/api/connections/image` · `/api/connections/video` `{provider, model, base_url, api_key}` 或 `{endpoint, model}` | 配置[形象工作室](avatar.md)图片和视频模型。`provider` 为目录 ID，或配 `base_url` 的 `openai` / `openai_responses`；`model` 空则用目录默认。key 提供时存保险库，`""` 移除，省略保留。四字段全为 `""` 时清空该模型项，自动选择依次使用聊天服务商、实际菜单提供此媒体类型的已登录中继、其他自备服务商。托管 Cloud 不提供媒体生成。 |
| GET | `/api/providers?lang=&region=` | 返回服务商目录、各模型项当前选择、已覆盖能力及每项未覆盖能力的说明。`lang` 为 `en` · `zh`，`region` 为 `cn` · `global`。「添加模型」面板据此显示。 |
| POST · GET · GET · POST · POST | `/api/chatgpt/login` · `/status` · `/usage` · `/callback {url}` · `/logout` | 提供[已有套餐登录](own-key.md#sign-in-with-a-plan-you-already-pay-for)中的 ChatGPT 流程：启动 Codex 登录并返回页面；查看不含令牌值的令牌存储状态；查看套餐用量窗口剩余量；提交从浏览器复制的回调 URL，其他登录的 `state` 返回 400；退出并删除登录状态。 |
| POST · DELETE | `/api/connections/mcp` `{name, command, args[], env{}, url, risk}` · `/api/connections/mcp/{name}` | 立即连接 MCP 服务器，启动失败返回 502；或断开并删除从 App 添加的服务器。`env` 各值存为 `MCP_<SERVER>_<KEY>`，设置文件仅留 `{{vault:...}}`；原本填写的引用原样保留。移除服务器时删除对应凭据。返回视图中的 `env` 仅为 `[{name, vault}]`，不含值。 |
| GET | `/api/skills` | 返回技能目录：`{count, built_in, yours, dir, errors{}, skills[{name, description, source (built-in · yours), enabled, path, files[], metadata{}, channel, updated_at}]}`。 |
| GET / PUT / DELETE | `/api/skills/{name}` | 读取技能 `body` 和完整 `SKILL.md` 的 `content`；用 `{content}` 保存，同名内置技能会创建用户副本；或删除用户技能。 |
| POST | `/api/skills/{name}/enabled` `{enabled}` | 启停技能，选择保存于 `app-settings.json`。 |
| POST | `/api/skills/import` `{url}` | 获取并保存 `SKILL.md`，支持原始链接及 GitHub 文件、目录页面。 |
| GET · PUT · DELETE | `/api/vault` · `/api/vault/{name}` `{value}` | 列出机密名称、写入或删除机密；不返回真实值。 |
| POST | `/api/onboarded` `{done}` | 将首次设置标为完成。已配置模型时，立即后台生成第一天动态，返回 `feed_started`。 |
| GET | `/api/firstrun`（`?lang=`） | 返回[首次对话](web.md#the-first-run-and-the-chat-s-opening)状态：`{phase (none · ask_user_name · ask_agent_name · named · done), session_id, user_address, suggestions, chips, chosen, lang, running, started_at, finished_at, intro[]}`。`chips` 是可选名称，`intro` 是指定 `lang` 的三句介绍。 |
| POST | `/api/firstrun/start` `{lang}` | 「开始」将首次对话绑定主要聊天，完成设置，并从 `none → ask_user_name`；已有聊天时跳过起名流程，直接为 `done`。返回含 `intro` 的状态。 |
| POST | `/api/firstrun/pick` `{name}` | 在 `ask_agent_name` 阶段选名，保存到配置档案，并切到 `named`。当前不需要选择返回 409，名称为空返回 400。 |
| POST | `/api/firstrun/dismiss` | 关闭选名界面，首次流程进入 `done`。 |
| GET | `/api/nudges`（`?refresh=1`） | 获取 GitHub star 提示策略。中继 `/v1/nudges` 每日和登录时读取，覆盖内置默认值，返回 `{star{enabled, url, moments{signed_in, tasks[], new_look, exhausted, days_used[], goal_done}, cooldown_days, max_asks, text, text_zh}, version, source}`。`text` / `text_zh` 是中继指定的卡片说明，最多 200 字符，未指定用 App 自带文字。 |
| GET | `/api/update`（`?refresh=1`） | 返回 `{current, enabled, latest, newer, url, download_url, checked_at, source (nanomuse.cn · github), error}`。先查 `nanomuse.cn/dl/index.json`，再查 GitHub `releases/latest`；成功缓存一天，失败缓存一小时。 |
| GET / PUT | `/api/sync/state` · `{enabled}` | 读取或修改[设备间对话同步](every-device.md#the-same-conversations-everywhere)：`{enabled, available, paused, cursor, last_pull_at, last_push_at, error, relay}`。`available` 表示已登录且配置允许；401 后 `paused` 保持到下次登录；`relay` 为中继 `{enabled, cursor, counts{conversations, messages}, limits}`，无法读取为 `null`。`PUT {enabled: false}` 关闭本机同步并删除该账号中继同步数据，其他设备下次上传或拉取收到 `sync_off` 后跟随关闭。`PUT {enabled: true}` 重开并上传本机聊天。中继错误按原状态、代号返回，例如 `409 sync_off`。0.1.38 起还含本机默认关闭的 `side_chats`，只同步主要聊天；以及来自 hub、十分钟后过期的 `working`，格式 `[{thread, cid, device, device_name, at}]`。`PUT {side_chats: true}` 上传本机旁聊并从头拉取账号旁聊一次，`false` 则之后只保留本地。 |
| POST | `/api/sync/delete` | 清空中继全部同步对话，开关不变，返回状态。 |
| POST | `/api/sync/pull` | 立即拉取并应用其他设备变更，返回 `{applied, …state}`。 |
| GET | `/api/cloud` | 获取 App 显示的 nanoMuse Cloud 账号：`{base_url, signed_in, required, models, hint, channel, signed_in_at, has_password, account_id, member, any_model, region, is_model}`，见 [cloud.md](cloud.md)。下列 `/api/cloud/*` 遇中继拒绝时，保留中继状态和说明，并用 `X-Nanomuse-Code` 返回代号。未登录返回 401 `bad_key`。 |
| GET | `/api/cloud/config` | 获取新账号额度、邀请奖励、注册开关和项目仓库等公开配置。旧中继或未配置时返回 `{}`。 |
| POST | `/api/cloud/code` `{identifier}` | 向邮箱或手机号发送登录验证码，返回 `{ok}`。 |
| POST | `/api/cloud/verify` `{identifier, code, invite?}` | 验证码登录，首次注册可带邀请码，返回中继 `/v1/me` 并更新提醒策略。 |
| POST | `/api/cloud/login` `{identifier, password}` | 使用账号密码登录，返回结构同 `verify`。 |
| POST | `/api/cloud/password` `{password, current?}` | 设置或修改密码。已有密码时需 `current`，刚通过验证码登录的 key 除外。`password` 为空并带 `current` 时移除密码。 |
| GET | `/api/cloud/me` | 读取中继当前账号 `/v1/me`，同时刷新提醒策略。 |
| GET · DELETE | `/api/cloud/sessions` · `/api/cloud/sessions/{prefix}` | 列出全部设备登录；或按显示的前缀撤销一个登录。两者都返回 `{sessions}`。 |
| POST | `/api/cloud/sign-out` · `/api/cloud/sign-out-all` `{all}` | 退出本机；或撤销其他全部登录。`all: true` 包含本机，返回 `{signed_out}` 和账号状态。 |
| GET | `/api/cloud/events?limit=` | 获取中继账号事件 `{events}`。`limit` 为 1 至 200，默认 50。 |
| POST | `/api/cloud/models` `{on}` | 切换「使用 nanoMuse Cloud 模型」。关闭后，账号聊天和屏幕模型从自动选择和服务商列表退出，自建中继若声明媒体模型也一并退出，账号仍登录。聊天当前使用账号模型时返回 409 `chat_on_cloud`。 |
| POST | `/api/cloud/use-as-model` `{model?}` | 将账号设为聊天模型，未指定时用推荐模型，key 来自保险库，并重新启用账号模型。返回连接配置中的 `llm`。 |
| POST · DELETE | `/api/cloud/contribute` `{on}` · `/api/cloud/samples` | 切换「帮助改进 nanoMuse 的 AI 模型」，仅开启时保留训练视图；或删除已保留内容，返回 `{deleted}`。 |
| POST | `/api/cloud/delete` | 删除中继账号并退出本机登录，返回账号状态。 |
| GET / PUT | `/api/hub` · `{enabled, remote_control, name}` | 读取本机在账号 hub（设备互联）中的状态，见 [hub.md](hub.md)：`{enabled, remote_control, state, detail, device{id, name, kind, actions}, devices[], account}`；或修改加入状态、远程控制和设备名称，名称最多 60 字符。 |
| POST | `/api/hub/join` · `/api/hub/leave` · `/api/hub/refresh` | 加入 hub、离开 hub 或重新请求设备列表，均返回 hub 状态。未登录加入返回 401。 |
| DELETE | `/api/hub/devices/{device_id}` | 移除账号设备；hub 未连接时返回 502。 |
| POST | `/api/hub/ask` `{device, text?}` | 按设备 ID 或名称打开面向该设备的旁聊，不存在则创建。带 `text` 时作为首条消息交给目标设备执行，返回 `{thread, event}`；无此设备返回 404。 |
| GET | `/api/bridge/tools` | 供智能体启动的命令使用，不供 App 使用。返回 `nanomuse-device list` 的 `{ok, tools[{name, description}]}`。使用 shell 签发的单次调用令牌 `X-Nanomuse-Bridge`，不使用 App 令牌；缺失返回 401，与 `POST /api/bridge/{kind}` 相同，见 [local-runtime.md](local-runtime.md)。 |
| GET | `/api/browser/{thread}/frames/{id}.jpg` | 读取当前会话内存中的 JPEG 浏览器画面。 |
| POST | `/api/browser/{thread}/control` `{action: click(x,y as 0–1 fractions) · type(text) · key(key) · scroll(dy) · navigate(url) · look · handed_back}` | 由用户控制智能体浏览器。Android 关闭接管面板时发送 `handed_back`，触发新画面并通知智能体。浏览器未开启返回 `409`，需先导航到 URL。 |
| GET | `/api/push` | 返回 `{available, public_key, subscriptions, devices[]}`，提供订阅需要的 VAPID 公钥。 |
| POST | `/api/push/subscribe` `{subscription}`、`/api/push/unsubscribe` `{endpoint}` | 注册或删除本设备 `PushSubscription`。 |
| POST | `/api/push/test` | 向全部已订阅设备发送测试通知。 |
| WS | `/ws` | 实时消息连接，首帧为 `{"kind": "auth", "token": …}`。 |

### WebSocket {#websocket}

客户端连接后十秒内必须发送 `{"kind": "auth", "token": "…"}`，否则以 4401 关闭，错误令牌同样处理。验证通过后，服务器发送 `{"kind": "hello", "state": …}`，内容与 `/api/state` 一致。之后通过下表持续推送变化：

| 服务器 → 客户端 | 含义 |
|---|---|
| `event` | 新增时间线事件，类型为 `user`、`assistant`、`tool`、`approval`、`question`、`artifact`、`browser`、`notice`。审批含 `summary`、`purpose`，即原用户请求、`target`、`grant_key`、`grant_options`、`risk`、`warnings`、`args`。浏览器卡含 `url`、`title`、`action`、`frame` 最新图片 ID、`frames`、`status` 的 `live` / `done`、`by_user`、`backend` 的 `playwright` / `device`，以及 CSS 像素 `width` / `height`。后台事件带 `source: "background"` 和批次标签 `about`。最终 assistant 气泡带 `final: true`，可在首次发送设置，或通过 `update` 补充；过程叙述不带，后台通知应以该标记识别最终结果。已登录 nanoMuse Cloud 时，assistant 还带记录 ID `turn`，自备 key 调用另带 `turn_source: "own"`。通过 `POST /api/threads/{id}/feedback` 反馈后还带 `feedback`，取 `up` / `down`。 |
| `update` | 更新已有事件字段，例如工具完成、审批已决定或浏览器画面变化。 |
| `event_removed` | `{thread, id}` 表示从时间线移除事件，例如另一设备通过同步删除消息。 |
| `working` | `{thread, cid, device, device_name, working, at, state?, detail?}` 表示其他设备开始或结束同步对话中的一轮，分别为 `true`、`false`。工作时显示「{device} 正在处理…」，中继 0.31 提供扩展字段后可显示「{device} 正在处理：{detail}」或「{device} 在等你确认」。回复到达或十分钟后移除。hello 的 `working` 也列出当前状态。 |
| `stream_start` / `delta` / `reasoning_delta` / `stream_end` | 流式回复的开始、文字增量、推理增量和结束。`reasoning_delta` 仅在 `show_thinking` 开启时发送，不独立存储，最终 assistant 包含完整推理。流式内容最终不属于回复，例如提示词工具调用或无变化的后台检查时，`stream_end` 带 `discard: true`。 |
| `status` | 返回 idle / working / waiting 状态及简短说明。 |
| `thread`、`thread_cleared`、`thread_deleted` | 通知对话列表新增、清空或删除。 |
| `firstrun` | `{firstrun}` 表示首次对话推进，例如点击「开始」、模型输出 `nanomuse-naming`、选名或关闭选名。结构同 `GET /api/firstrun`，不含 `intro`，界面据此更新选名卡。hello 状态也在 `firstrun` 中提供。 |
| `goals`、`memory`、`ideas`、`feed_posts`、`profile`、`settings`、`connections`、`skills`、`approvals_reset` | 提示相关页面刷新数据。 |
| `phone` | 手机连接或离线，内容同 `/api/phone`。 |
| `schedule` | `next_wake_at` 发生变化，例如提醒设置或触发、目标周期调整、免打扰结束。返回 `{next_wake_at}`，没有待执行事项时为 `null`；Android 运行时据此重新设置系统闹钟。 |
| `device_ack`、`device_request` | 发给已连接手机的声明确认，以及截图或操作请求，见 [gui.md](gui.md#the-device-protocol)。 |
| `error`、`pong` | 回复客户端错误或心跳消息。 |

客户端可以发送 `{"kind": "send", "thread": "main", "text": "…", "language": "en", "via": ""}`。`language`、`via` 可选，含义同 `POST /api/threads/{id}/send`。未登录却请求 `via: "cloud"`，会收到 `{"kind": "error", "error": "…", "code": "signed_out"}`。审批回复为 `{"kind": "approval", "id": "…", "approved": true, "scope": "once"}`，心跳为 `{"kind": "ping"}`。提供屏幕操作的手机还要发送一次 `{"kind": "device", …}` 声明，并为每次请求返回 `{"kind": "device_result", …}`。

时间线按对话保存到 `<data_dir>/threads/<id>.json`，重启后仍保留历史。

## 前端开发 {#developing-the-front-end}

```bash
cd web && npm install
npm run dev          # Vite on http://localhost:5173, proxied to the server on 8787
npm run build        # writes nanomuse/server/static/; commit the result
```

使用开发服务器时，在 `[server]` 加入 `cors_origins = ["http://localhost:5173"]`。前端使用 React、TypeScript、Tailwind，没有额外状态管理库。`web/src/store.tsx` 放置 reducer（状态更新函数）和 WebSocket 客户端，`web/src/screens/` 为每个标签页提供一个文件。
