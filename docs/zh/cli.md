# 命令行（CLI）

每条命令都接受 `--config PATH`（`-c`）。`--auto` 让哨兵（Sentinel）在这一次运行里切到 `auto` 模式；明确写下的拒绝规则仍然生效。

## 和智能体对话 {#talking-to-the-agent}

```bash
nanomuse serve [--host 0.0.0.0] [--port 8787] [--no-qr] [--no-auth]
```

一直在线的智能体，配合手机 App 使用。见 [app.md](app.md)。`--no-auth` 只用于本地开发。

```bash
nanomuse chat [--resume] [--show-thinking] [--auto]
```

在终端里的交互式会话，审批直接在对话中进行。斜杠命令：

| 命令 | 作用 |
|---|---|
| `/help` | 列出命令 |
| `/reset` | 清空对话和污染标记 |
| `/memory`、`/goals` | 列出记忆 / 目标 |
| `/audit [n]` | 最近的审计记录 |
| `/tools` | 智能体此刻能用的工具 |
| `/tainted` | 这段对话有没有读过私密数据 |
| `/permissions` | 你授予的长期权限（键和有效期） |
| `/revoke <key>` | 收回一项，例如 `/revoke shell:git` |

`--resume` 接着最近一次会话继续（`<data_dir>/sessions/`）。

```bash
nanomuse run "Summarise the top three Hacker News stories into hn.md" [--auto]
```

做一件事，然后退出。智能体失败时以非零码退出。

```bash
nanomuse daemon [--interval 3600] [--once]
```

推进每一个进行中的目标，休眠，再来一遍。它跑在哨兵的 `auto` 模式下，所以要配上拒绝规则和收紧的 `egress_allowlist`。App 里的「后台工作」开关在 `nanomuse serve` 内做的是同一件事：每个周期推进一个目标，进展发到聊天里。

## 目标 {#goals}

```bash
nanomuse goals list [--status active|paused|done] [--category health|finance|career|learning|…]
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

提醒是在你指定的时间说一句话；例程（`--task`）是智能体在那个时间用它的工具去做的事。两者都由运行中的 `nanomuse serve` 触发——在终端里设的落在主要聊天，在旁聊里设的留在那个旁聊。周期的写法和目标检查一样：`daily HH:MM`、`weekdays HH:MM`、`weekly <mon…sun> HH:MM`、`monthly <day> HH:MM`。

## 触发器 {#triggers}

```bash
nanomuse triggers list [--all]                                                   # --all includes cancelled ones
nanomuse triggers add mail  "Summarise it and draft a reply" --match "landlord"   # a new mail whose sender/subject has every word
nanomuse triggers add event "Put together a one-page brief"  --match "review" --lead 30   # 30 min before a matching event
nanomuse triggers add hook  "Check that the site is up"      --match "deploy"    # prints the URL to POST to
nanomuse triggers cancel t_1a2b3c
```

触发器在事情发生时触发，而不是到点触发：`mail` 需要邮件连接器（运行中的服务器每隔 `triggers.mail_poll_minutes` 查看一次收件箱，按 IMAP UID 记录，所以不会重放，也不会触发两次）；`event` 需要一个日历订阅；`hook` 是一个带密钥的 URL，任何程序都可以向它 `POST`——请求体成为智能体的上下文。每次触发都是在设置它的那个聊天里的一次后台运行，在动态里显示为 *New mail: …*、*Coming up: …* 或 *Webhook: …*。邮件或请求是作为数据交给模型的，并附带一句说明：只有你预先写下的那段话才决定做什么。

## 日历 {#calendar}

```bash
nanomuse calendar add Work "https://calendar.google.com/calendar/ical/…/basic.ics"   # link goes to the vault as CALENDAR_WORK
nanomuse calendar add Family ~/family.ics                                            # or an .ics file on disk
nanomuse calendar agenda --days 7                                                    # what is on, grouped by day
nanomuse calendar free --day tomorrow --minutes 45                                   # gaps in the working hours
nanomuse calendar feeds                                                              # each feed: events, last read, error
nanomuse calendar remove Family
```

运行中的服务器每隔 `refresh_minutes` 重新读一次订阅；`agenda --refresh` 立刻抓取。智能体通过它的 `calendar` 工具看到同样的内容，另外还有 `draft`：它写出一个 `.ics` 文件，App 显示为「添加到日历」卡片——它从不直接写你的日历。

## 联系人 {#contacts}

```bash
nanomuse contacts search "ali"                          # by name, nickname, company, email or phone
nanomuse contacts list -n 20                            # the first people alphabetically
nanomuse contacts add "Bob Li" -e bob@example.com --note landlord   # into the agent's own book
nanomuse contacts sources                               # each address book: people, last read, error
nanomuse contacts add-source Google ~/Downloads/contacts.vcf         # a .vcf file, or a link (→ vault CONTACTS_GOOGLE)
nanomuse contacts remove-source Google
```

智能体通过它的 `contacts` 工具看到同样的内容；`doctor` 会报告它认识多少人、来自哪里。

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

技能是带 `SKILL.md` 的文件夹，格式按 [Agent Skills](https://agentskills.io)；你自己的放在 `<data_dir>/skills/`，和内置技能同名的会替换掉那一个内置技能。聊天里，消息开头写 `/name` 就运行对应的技能；`doctor` 列出已加载的技能和读不了的文件夹。

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

`memory recall` 显示智能体对一条消息会得到的排序：关键词命中，以及在配置了嵌入端点时（[配置 → 记忆](configuration.md#memory)）融合进来的按语义命中，每条带余弦相近度——用它看看「写邮件给房东」能不能找到「房东是 Bob Li」，再去依赖它。`doctor` 会说明按语义回忆有没有开、用的哪个模型、索引了多少条记忆。

## 保险库 {#vault}

```bash
nanomuse vault set EMAIL_PASSWORD      # prompted; or --value for scripts
nanomuse vault list                    # names only, never values
nanomuse vault delete EMAIL_PASSWORD
```

在配置里用 `{{vault:EMAIL_PASSWORD}}` 引用机密（只限连接器；命令永远拿不到机密）。见 [sentinel.md](sentinel.md#credential-vault)。

## 手机 {#phone}

```bash
nanomuse phone traces [--limit 20]                 # every phone_task on record: id, when, status, steps, goal
nanomuse phone trace pt-20260923-230710-5be7       # one task step by step: screen, latency, action, what was sent
nanomuse phone trace pt-20260923-230710-5be7 -o trace.html   # a self-contained page with every screen and tap drawn on it
```

每当智能体操作手机时都会写下轨迹（[gui.md](gui.md#traces)）；HTML 页面是单个文件，截图内嵌，就是为了附到 issue 上。

## 审计和配置 {#audit-and-config}

```bash
nanomuse audit [-n 20] [--json]        # recent decisions, approvals, tool calls
nanomuse config init [--path config/config.toml] [--force]
nanomuse config show                   # effective settings, secrets masked
nanomuse config path                   # which file is in use
nanomuse doctor [--no-model]           # config, data dir, model, connectors — one screen
nanomuse version                       # also: nanomuse --version / -V
nanomuse mcp                           # this computer's screen and hands as an MCP server on stdio, for another host
```

`nanomuse mcp` 是给不是我们运行时的宿主用的——[跑在 DeepSeek Harness 上的 nanoMuse](harness.md)——它以运行时自己的描述提供 `computer_screen` 和 `computer_act`；哨兵会停下来问的那一步（回车、提交、重的快捷键、点到敏感词）会被拒绝并给出原因，直到调用带上 `confirmed: true`，而模型只有在对话里得到人的同意后才可以设置它。

`nanomuse doctor` 是出问题时第一个该跑的命令，也是该贴进 bug 报告的内容：用的是哪个配置文件、数据放在哪、配置了哪个模型和端点、key 有没有设、按语义回忆有没有开、索引了多少条记忆、哪个网页搜索服务商在应答、它的 key 或 URL 有没有、命令是否跑在沙箱里（如果没有，为什么）、智能体有哪些工具、连接器状态（邮箱、日历订阅、通讯录），以及对模型的一次单行调用及其延迟（`--no-model` 跳过这一项）。有东西需要修时它以非零码退出，并说明是什么。
