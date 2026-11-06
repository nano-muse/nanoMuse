# 命令行使用说明 {#命令行-cli}

CLI（命令行界面）是通过在终端输入命令来使用程序的方式。本页命令针对 Python 运行时，也就是执行智能体任务的程序。

所有命令都支持 `--config PATH`，简写为 `-c`，用于指定配置文件。`--auto` 会将本次运行的哨兵（Sentinel，操作权限检查组件）切换为 `auto` 模式；你明确设置的拒绝规则仍会生效。

## 和智能体对话 {#talking-to-the-agent}

```bash
nanomuse serve [--host 0.0.0.0] [--port 8787] [--no-qr] [--no-auth]
```

`serve` 启动持续运行的智能体服务，供手机 App 连接。详情见 [app.md](app.md)。`--no-auth` 会关闭身份验证，仅用于本地开发。

```bash
nanomuse chat [--resume] [--show-thinking] [--auto]
```

`chat` 在终端中开启交互式对话，遇到需要审批的操作时会直接在终端询问。对话中可以使用以下斜杠命令：

| 命令 | 作用 |
|---|---|
| `/help` | 列出命令 |
| `/reset` | 清空对话，并清除已读取私密数据的污染标记 |
| `/memory`、`/goals` | 列出记忆 / 目标 |
| `/audit [n]` | 显示最近的操作与权限判定记录，可指定条数 |
| `/tools` | 智能体此刻能用的工具 |
| `/tainted` | 这段对话有没有读过私密数据 |
| `/permissions` | 显示已授予的长期权限，包括授权键和有效期 |
| `/revoke <key>` | 撤销指定权限，例如 `/revoke shell:git` |
| `/forget-approvals` | 清掉所有已授予的权限 |
| `/exit` | 退出（`/quit`、`/q` 也可以） |

加上 `--resume` 可继续最近一次会话。会话数据保存在 `<data_dir>/sessions/` 中，`data_dir` 是配置的数据目录。

```bash
nanomuse run "Summarise the top three Hacker News stories into hn.md" [--auto]
```

`run` 执行指定任务后退出。如果智能体执行失败，命令返回非零退出码，便于脚本判断结果。

```bash
nanomuse daemon [--interval 3600] [--once]
```

`daemon` 会分别为每个进行中的目标创建临时会话，推进一轮并打印结果，等待指定时间后重复执行。它使用哨兵的 `auto` 模式，应配合拒绝规则和严格的 `egress_allowlist`（允许向外发送数据的主机列表）。

App 的「后台工作」由 `nanomuse serve` 提供：每个周期只选一个目标，使用原聊天的上下文和哨兵，将进展发回聊天，并能在重启后恢复未完成的轮次，见 [app.md](app.md#background-work)。`daemon` 是独立的无人值守命令，没有关联聊天，也不保存各轮执行进度。

## 目标 {#goals}

```bash
nanomuse goals list [--status active|paused|done|cancelled] [--category health|finance|career|learning|…]
nanomuse goals show g_1a2b3c
nanomuse goals add "Learn Rust" -s "Read the book, ch. 1–4" -s "Build a CLI" -s "Publish a crate" \
    --category learning --due 2026-12-31 --check-in "weekly sun 19:00"
nanomuse goals run g_1a2b3c            # one background pass now
nanomuse goals status g_1a2b3c paused
nanomuse goals delete g_1a2b3c
```

## 提醒和例程 {#reminders-and-routines}

```bash
nanomuse reminders list [--all]                                  # --all includes the recently fired
nanomuse reminders add "Call mum" --at "2026-10-01 18:00"        # one message at that time
nanomuse reminders add "Summarise unread email" --repeat "weekdays 07:30" --task   # the agent does it, then reports
nanomuse reminders cancel r_1a2b3c
```

提醒会在指定时间发送一条消息；例程（`--task`）则在指定时间调用工具执行任务。两者都需要 `nanomuse serve` 保持运行。从终端创建的任务归入主要聊天，从旁聊创建的任务留在该旁聊中。周期格式与目标检查一致：`daily HH:MM` 表示每天，`weekdays HH:MM` 表示工作日，`weekly <mon…sun> HH:MM` 表示每周指定日期，`monthly <day> HH:MM` 表示每月指定日期。

## 触发器 {#triggers}

```bash
nanomuse triggers list [--all]                                                   # --all includes cancelled ones
nanomuse triggers add mail  "Summarise it and draft a reply" --match "landlord"   # a new mail whose sender/subject has every word
nanomuse triggers add event "Put together a one-page brief"  --match "review" --lead 30   # 30 min before a matching event
nanomuse triggers add hook  "Check that the site is up"      --match "deploy"    # prints the URL to POST to
nanomuse triggers add device "Say the phone is back"         --match "pixel"     # a device of the account comes online
nanomuse triggers cancel t_1a2b3c
```

触发器根据事件启动任务。`mail` 需要邮件连接器，服务器每隔 `triggers.mail_poll_minutes` 分钟检查收件箱，按 IMAP UID（邮件在该邮箱中的唯一编号）记录已处理项，避免重复执行。`event` 需要日历订阅。`hook` 提供带密钥的 URL，其他程序可以向它发送 `POST` 请求，请求体会作为任务上下文。

`device` 要求这台电脑已加入 hub（账号下的设备通信服务）。当其他设备从离线变为在线时，它会按设备名称或类型中的词匹配触发条件。本机不会触发自身上线事件，App 启动时已经在线的设备也不算新上线。

每次触发都会在创建它的聊天中执行一轮后台任务，动态中显示 *New mail: …*、*Coming up: …*、*Webhook: …* 或 *Device online: …*。邮件和外部请求只作为数据交给模型，模型会被明确要求只按你预设的任务说明行动。

## 日历 {#calendar}

```bash
nanomuse calendar add Work "https://calendar.google.com/calendar/ical/…/basic.ics"   # link goes to the vault as CALENDAR_WORK
nanomuse calendar add Family ~/family.ics                                            # or an .ics file on disk
nanomuse calendar agenda --days 7                                                    # what is on, grouped by day
nanomuse calendar free --day tomorrow --minutes 45                                   # gaps in the working hours
nanomuse calendar feeds                                                              # each feed: events, last read, error
nanomuse calendar remove Family
```

服务器按 `refresh_minutes` 指定的间隔刷新日历订阅。使用 `agenda --refresh` 可立即刷新。智能体的 `calendar` 工具能读取相同日程，还能通过 `draft` 生成 `.ics` 日历交换文件。App 会将文件显示为「添加到日历」卡片，供你确认添加，不会直接修改你的日历。

## 联系人 {#contacts}

```bash
nanomuse contacts search "ali"                          # by name, nickname, company, email or phone
nanomuse contacts list -n 20                            # the first people alphabetically
nanomuse contacts add "Bob Li" -e bob@example.com --note landlord   # into the agent's own book
nanomuse contacts sources                               # each address book: people, last read, error
nanomuse contacts add-source Google ~/Downloads/contacts.vcf         # a .vcf file, or a link (→ vault CONTACTS_GOOGLE)
nanomuse contacts remove-source Google
```

智能体可通过 `contacts` 工具查询同一份联系人数据。`doctor` 会显示联系人总数及各通讯录来源。

## 技能 {#skills}

```bash
nanomuse skills list                                    # built-in and yours, on or off
nanomuse skills show trip-plan                          # the SKILL.md, as the model reads it
nanomuse skills new standup-notes                       # a SKILL.md to fill in, printed with its path
nanomuse skills add ./my-skill/                         # a folder or a SKILL.md file …
nanomuse skills add https://github.com/anthropics/skills/tree/main/skills/pdf   # … or a raw link / GitHub folder page
nanomuse skills disable inbox-triage                    # out of the model's list; the folder stays
nanomuse skills enable inbox-triage
nanomuse skills remove standup-notes                    # one of yours (built-in ones are disabled, not removed)
```

技能是包含 `SKILL.md` 的文件夹，按 [Agent Skills](https://agentskills.io) 格式描述某类任务的执行方法。自定义技能放在 `<data_dir>/skills/` 下；名称与内置技能相同时，优先使用自定义版本。在聊天消息开头输入 `/name` 可调用对应技能。`doctor` 会列出已加载的技能，并报告无法读取的技能目录。

## 记忆 {#memory}

```bash
nanomuse memory list
nanomuse memory add "Prefers short answers" --category preference
nanomuse memory recall "写邮件给房东"    # what the agent would recall for this, with closeness
nanomuse memory forget m_9f8e7d        # id or a phrase to search for
nanomuse memory clear --yes
nanomuse memory tidy --dry-run         # what a tidy-up would merge and drop
nanomuse memory tidy                   # do it; every change is logged
nanomuse memory changes                # the log, newest first
nanomuse memory restore c_1a2b3c4d     # undo one change
```

`memory recall` 会显示智能体面对指定消息时检索到的记忆及其排序。系统先匹配关键词；如果配置了嵌入端点，还会结合语义检索，即把文本转换为向量后比较含义，见[配置 → 记忆](configuration.md#memory)。每条结果附有余弦相似度，用于表示向量接近程度。可以用「写邮件给房东」检查能否找到「房东是 Bob Li」，再判断检索效果是否满足需求。`doctor` 会显示语义检索是否启用、所用模型和已建立索引的记忆条数。

## 保险库 {#vault}

```bash
nanomuse vault set EMAIL_PASSWORD      # prompted; or --value for scripts
nanomuse vault list                    # names only, never values
nanomuse vault delete EMAIL_PASSWORD
```

保险库用于加密保存密钥等凭据。在配置中使用 `{{vault:EMAIL_PASSWORD}}` 引用相应条目。只有连接器会解析这些引用，shell 命令不能据此取得凭据。详情见 [sentinel.md](sentinel.md#credential-vault)。

## 聊天入口 {#chat-apps}

```bash
nanomuse channels status [--json]              # 哪些入口已开启、已连接，谁已配对
nanomuse channels pending                      # 已经展示给人、等待批准的配对码
nanomuse channels approve 482913               # 让拿到这个配对码的人和 Muse 对话
nanomuse channels deny 482913
nanomuse channels login feishu [--lark]        # 扫码创建飞书机器人
nanomuse channels test feishu [--chat <id>]    # 发一条测试消息（默认发到第一个已配对的会话）
```

如果 `nanomuse serve` 正在运行，这些命令会通过 API（程序调用接口）更新服务；否则会修改数据目录中的文件，供服务器下次启动时读取。各聊天应用的配置要求和配对步骤见 [channels.md](channels.md)。

## ChatGPT 登录 {#chatgpt-sign-in}

```bash
nanomuse chatgpt login [--no-browser] [--port 1455] [--timeout 600]   # 浏览器打开 OpenAI 的登录页
nanomuse chatgpt status                        # 谁已登录、有效期到何时；不访问网络
nanomuse chatgpt usage                         # 套餐用量窗口还剩多少
nanomuse chatgpt logout                        # 忘掉这次登录；上游不会撤销
nanomuse chatgpt proxy [--port 0] [--token …]  # 回环地址上的一个 OpenAI 兼容服务
```

所有子命令都支持 `--json`，按每行一个 JSON 对象输出，便于程序读取。需要访问 chatgpt.com 的子命令还支持 `--proxy`，默认沿用 `[llm] proxy` 配置。登录可使用哪些能力、授权令牌保存在哪里，见 [own-key.md](own-key.md#sign-in-with-a-plan-you-already-pay-for)。

## 手机 {#phone}

```bash
nanomuse phone traces [--limit 20]                 # every phone_task on record: id, when, status, steps, goal
nanomuse phone trace pt-20260923-230710-5be7       # one task step by step: screen, latency, action, what was sent
nanomuse phone trace pt-20260923-230710-5be7 -o trace.html   # a self-contained page with every screen and tap drawn on it
```

每次手机操作都会记录轨迹，即按顺序保存截图、动作和结果，见 [gui.md](gui.md#traces)。导出的 HTML 是包含内嵌截图的独立文件，可附在 issue（问题报告）中。

## 审计和配置 {#audit-and-config}

```bash
nanomuse audit [-n 20] [--json]        # recent decisions, approvals, tool calls
nanomuse config init [--path config/config.toml] [--force]
nanomuse config show                   # effective settings, secrets masked
nanomuse config path                   # which file is in use
nanomuse doctor [--no-model]           # config, data dir, model, connectors, one screen
nanomuse version                       # also: nanomuse --version / -V
nanomuse mcp                           # this computer's screen and hands as an MCP server on stdio, for another host
```

`nanomuse mcp` 通过 MCP（让智能体接入外部工具的协议）向其他宿主提供 `computer_screen` 和 `computer_act`，工具描述与本运行时一致。用法见[在 DeepSeek Harness 中运行 nanoMuse](harness.md)。对于回车、提交、可能产生较大影响的快捷键，以及涉及敏感词的点击，哨兵会拒绝执行并说明原因，直到调用包含 `confirmed: true`。模型只有在对话中得到用户同意后，才能设置该字段。

排查问题时先运行 `nanomuse doctor`，提交错误报告时也可附上诊断结果。它会检查配置文件路径及未被程序使用的配置键、数据目录、模型与服务地址、密钥是否已设置、语义记忆检索与索引数量、网页搜索服务及其密钥或 URL、命令是否在沙箱中运行及未启用的原因、可用工具，以及邮箱、日历和通讯录的连接状态。沙箱是限制命令可访问资源的隔离环境。

诊断还会向模型发送一次简短请求并显示耗时，可用 `--no-model` 跳过。发现需要修复的问题时，命令返回非零退出码并说明原因。
